"""One route, planned through the preset's Valhalla variant, with its stats.

The request path PLAN.md's Deployment section describes: a routing call plus
database queries, synchronous, nothing saved. A signed-out plan is not stored
anywhere (owner decision of 2026-09-26), and nothing here writes.

Three calls per leg set at most:

1. `/route` on the preset's variant with the preset's costing options, which
   gives the shape, distance, moving time and - with `elevation_interval` -
   an evenly spaced elevation profile.
2. `/trace_attributes` on each leg's shape, to the same variant and costing
   (PLAN, Stats source: tracing a Mass Ride route against the standard variant
   would return edges that route could not have used), with
   `shape_match: edge_walk` and a `map_snap` fallback. It gives each edge's OSM
   way id and length.
3. One query joining those edges to the live segment table, for the stress
   breakdown.

The join follows PLAN's Stats source: by `edge.way_id` plus position, so that an
edge spanning several segments of one way has its length apportioned between
them. Each edge is cut at its shape vertices, each piece goes to the nearest
segment of the same way, and the edge's reported length is shared between its
pieces in proportion to their ground length. Pieces are per traversal, so a
route that rides the same way twice counts it twice (PLAN: the out-and-back
fixture). A way with no segment row, and any leg the router refused to trace
by both matches, counts as "unknown" rather than being guessed at; a router
that stops answering mid-trace is a 502 like any other.

That is a deviation from PLAN's Stats source in one respect, recorded in the
handoff: the plan asks for "linear overlap of the edge shape against stored
segment geometry", and what is here is the nearest same-way segment to each
piece's midpoint. The two agree wherever a piece lies along one segment, which
is nearly every piece - the promoted build has 1,357,800 segments on 1,341,939
ways - and differ only for a piece that straddles a segment boundary, whose
length all goes to the segment nearer its middle instead of being split there.

Every request has one time budget, `PLAN_BUDGET_S` (`LONG_PLAN_BUDGET_S` for a
long ride), counted from when Django's first middleware sees it
(`core.middleware.RequestClockMiddleware`), so the other middleware, the count,
the slots and the answer are inside it.
gunicorn kills a worker at its 60 s timeout and Caddy then answers an empty
502; the budget ends the request well before that. The router calls get the
budget less `ANSWER_RESERVE_S`, kept back for the stress join and the
answer, and each call's socket timeout is the smaller of its per-call limit
and what is left of that. A /route that runs out of it is 503 with
Retry-After; a trace that does leaves its leg, and the legs after it, unknown,
so a route already found is still answered.

Climb and descent come from the route's elevation profile through
`routemaker.measure.elevation_gain`, the same hysteresis definition the
reference-route invariants use, so the number a test asserts and the number a
rider is shown come from one function. Descent is the same definition applied
to the profile turned upside down.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import connection
from django.utils import timezone

from pipeline.schema import validate_schema_name
from pipeline.variants import Variant
from routemaker import ridetime
from routemaker.facility import FACILITIES
from routemaker.geo import Point, haversine
from routemaker.measure import elevation_gain

from . import presets

logger = logging.getLogger(__name__)

# Metres between elevation samples. 3DEP at 1 arc-second is about 30 m on the
# ground here, so a finer interval samples the same cell twice.
ELEVATION_INTERVAL_M = 30

# The whole request's budget, from its arrival to its answer. gunicorn's
# --timeout is 60 s (GUNICORN_TIMEOUT in docker/api-entrypoint.sh), and this is
# an answer well inside it rather than a killed worker.
PLAN_BUDGET_S = 40

# Of each budget, the seconds no router call may use: the stress join over the
# traced pieces and the serialised answer. For a long route with the host
# loaded the two together took about 3 s (review round 3).
ANSWER_RESERVE_S = 3

# How long one router call may take, at most, before the answer is 502; it is
# also never more than what is left of the budget. The plan's latency target
# is p95 under 3 s for a 50-mile preview, but an ordinary plan is up to 150 km
# of straight line: on a loaded host the /route for a 169 km Mass Ride loop
# spanning 141 km took 20.8 s and 23.5 s (review round 3), which a fixed 20 s
# made a 502 with most of the budget unspent. 35 s is nearly all of the 37 s
# the budget leaves the routers, and still lets a trace start after it.
ROUTER_TIMEOUT_S = 35

# A long ride (past 150 km of straight line) has more of both; the owner's
# answer of 2026-09-26 is 50 s in all for a confirmed long ride, where
# ordinary plans keep 40 s. A single long leg is one /route search, and on
# the real routers with the host loaded a cold one - its graph tiles not yet
# in the router's cache - took 43.9 s for Culpeper to Baltimore, 150.4 km of
# straight line and 183 km routed, and the same request 9.5 s warm. Only one
# long ride runs at a time in the whole api (core.ratelimit.
# LONG_ROUTING_IN_FLIGHT), so the longer hold is one worker's. 50 s leaves
# gunicorn's 60 s kill ten seconds.
LONG_ROUTER_TIMEOUT_S = 45
LONG_PLAN_BUDGET_S = 50


def clock() -> float:
    """The monotonic clock every budget is read from."""
    return time.monotonic()


# PLAN, Time-dependent behavior: requests carry a planning time so conditional
# restrictions are evaluated rather than ignored; type 3 is invariant time,
# which keeps bidirectional A*. The time is the ride-time setting's
# (`routemaker.ridetime`): the owner's three settings of 2026-09-27, the
# weekend one being PLAN's own default of the next Saturday at 9:00.

STRESS_KEYS = ("1", "2", "3", "4", "unknown")
FACILITY_KEYS = (*FACILITIES, "unknown")

# Valhalla's error codes, sorted by what they mean to the person asking.
# No path between the points (442, 443): the one case where a no-trail
# variant's missing crossings are the likely explanation.
NO_PATH_CODES = frozenset({442, 443})
# No routable edge near a location (170, 171): no route, but not for want of a
# crossing.
NO_EDGE_CODES = frozenset({170, 171})
# The 15x family is the service's request limits - too many locations, a path
# over the distance limit (154), too many shape points and so on. The request
# asked for too much, which is the caller's 400. Any other refusal is still
# reported as no route, and logged, because it means this module built a
# request the router does not accept.
REQUEST_LIMIT_CODES = frozenset(range(150, 160))


class RouterUnavailable(Exception):
    """The variant's router did not answer, or answered with a server error."""


class RouterRefused(Exception):
    """The router answered 4xx; `code` is Valhalla's error_code if it gave one."""

    def __init__(self, status: int, code: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class NoRoute(Exception):
    """No route joins these points on this preset's variant.

    `no_path` is true only when the router said there is no path at all, as
    opposed to no road near a point or some other refusal.
    """

    def __init__(self, message: str, no_path: bool = False) -> None:
        super().__init__(message)
        self.no_path = no_path


class TooLong(Exception):
    """The router refused the request as beyond one of its limits."""


class DeadlineExceeded(Exception):
    """The request's time budget ran out before the router had answered."""


def _transport(url: str, payload: dict, timeout: float) -> dict:
    """POST JSON, return JSON. The one place this module touches the network."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500:
            try:
                body = json.loads(error.read() or b"{}")
            except ValueError:
                body = {}
            raise RouterRefused(
                error.code, body.get("error_code"), str(body.get("error", ""))
            ) from error
        raise RouterUnavailable(f"router answered {error.code}") from error
    except (TimeoutError, urllib.error.URLError, ConnectionError, ValueError) as error:
        raise RouterUnavailable(str(error)) from error


@dataclass(frozen=True)
class Deadline:
    """When the request's budget ends (monotonic), and the most one call may take."""

    at: float
    per_call_s: float


def _call(variant: str, endpoint: str, payload: dict, deadline: Deadline) -> dict:
    """One router call inside the request's budget."""
    remaining = deadline.at - clock()
    if remaining <= 0:
        raise DeadlineExceeded(f"no time left for {endpoint}")
    url = f"{settings.VALHALLA_UPSTREAMS[variant]}/{endpoint}"
    try:
        return _transport(url, payload, min(deadline.per_call_s, remaining))
    except RouterUnavailable as error:
        if clock() >= deadline.at:
            raise DeadlineExceeded(f"{endpoint} ran past the budget") from error
        raise


def planning_time(now: datetime | None = None, when: str = ridetime.WEEKEND) -> str:
    """The next instant of a ride-time setting, as Valhalla's local time.

    For the weekend that is the next Saturday at 9:00, PLAN's own default; the
    weekday settings are the next Tuesday at 8:00 and at 12:00
    (`routemaker.ridetime.REPRESENTATIVE_TIME`).
    """
    return ridetime.representative_time(when, now or timezone.now())


def default_when(now: datetime | None = None) -> str:
    """The ride-time setting of the moment the plan is made."""
    return ridetime.when_at(now or timezone.now())


def decode_polyline6(encoded: str) -> list[tuple[float, float]]:
    """Valhalla's encoded shape (precision 6) as [(lon, lat), ...]."""
    coordinates: list[tuple[float, float]] = []
    index = lat = lon = 0
    while index < len(encoded):
        for axis in (0, 1):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        coordinates.append((lon / 1e6, lat / 1e6))
    return coordinates


def climb_and_descent(elevations: list[float | None]) -> tuple[float, float]:
    points = [Point(0.0, 0.0, e) for e in elevations]
    inverted = [Point(0.0, 0.0, None if e is None else -e) for e in elevations]
    return elevation_gain(points), elevation_gain(inverted)


@dataclass(frozen=True)
class Piece:
    """A stretch of one traversed edge, between two consecutive shape vertices."""

    way_id: int
    lon: float
    lat: float
    metres: float


def pieces_of_trace(trace: dict) -> list[Piece]:
    """Cut every traced edge at its shape vertices, apportioning its length."""
    shape = decode_polyline6(trace.get("shape", ""))
    to_metres = 1609.344 if trace.get("units") == "miles" else 1000.0
    pieces: list[Piece] = []
    for edge in trace.get("edges", []):
        length = float(edge.get("length") or 0.0) * to_metres
        begin, end = edge.get("begin_shape_index"), edge.get("end_shape_index")
        # An index past the shape is a response this module does not
        # understand, and is skipped rather than guessed at. `begin == end` is
        # not: it is an edge that starts and ends on one vertex, and its length
        # is kept, on that vertex.
        if length <= 0 or begin is None or end is None or end < begin or end >= len(shape):
            continue
        way_id = int(edge.get("way_id") or 0)
        stretches = []
        for a, b in zip(shape[begin:end], shape[begin + 1 : end + 1], strict=True):
            stretches.append((a, b, haversine(Point(*a), Point(*b))))
        ground = sum(s[2] for s in stretches)
        if ground <= 0:
            # A degenerate edge: all its length on its first vertex.
            (lon, lat) = shape[begin]
            pieces.append(Piece(way_id, lon, lat, length))
            continue
        for a, b, d in stretches:
            if d > 0:
                pieces.append(
                    Piece(way_id, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, length * d / ground)
                )
    return pieces


_STRESS_JOIN = """
SELECT seg.stress_tier, {facility}, sum(p.metres)
FROM unnest(%s::bigint[], %s::float8[], %s::float8[], %s::float8[])
     AS p(way_id, lon, lat, metres)
LEFT JOIN LATERAL (
    SELECT s.stress_tier, {columns}
    FROM {schema}.segment AS s
    WHERE s.osm_way_id = p.way_id
    ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)
    LIMIT 1
) AS seg ON true
GROUP BY 1, 2
"""

# A road closed to motor traffic only at set times is a path for a ride inside
# the closure, and the road it is otherwise for any other (routemaker.facility).
_FACILITY_AT = "CASE WHEN %s = ANY(seg.car_free_when) THEN 'path' ELSE seg.facility END"

# Whether the live segment table has the facility columns yet. They arrive with
# the first rebuild after this code; until then the breakdown is all unknown
# rather than an error. Remembered once seen, since a schema is only ever
# replaced by a newer build of itself.
_facility_columns_seen = False


def _has_facility_columns(schema: str) -> bool:
    global _facility_columns_seen
    if _facility_columns_seen:
        return True
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'segment' AND column_name IN ('facility', 'car_free_when')",
            [schema],
        )
        _facility_columns_seen = cursor.fetchone()[0] == 2
    return _facility_columns_seen


def breakdown(pieces: list[Piece], when: str) -> tuple[dict[str, float], dict[str, float]]:
    """Metres per stress tier and per facility class, for a ride at `when`.

    Stress is keyed "1".."4" and "unknown", facility "path", "protected",
    "lane", "none" and "unknown"; each sums to the traced length.
    """
    stress = dict.fromkeys(STRESS_KEYS, 0.0)
    facility = dict.fromkeys(FACILITY_KEYS, 0.0)
    if not pieces:
        return stress, facility
    # The schema name comes from settings and is validated the way every DDL
    # that names it is; an identifier cannot be a query parameter.
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    with_facility = _has_facility_columns(schema)
    query = _STRESS_JOIN.format(
        schema=schema,
        facility=_FACILITY_AT if with_facility else "NULL",
        columns="s.facility, s.car_free_when" if with_facility else "NULL",
    )
    arrays = [
        [p.way_id for p in pieces],
        [p.lon for p in pieces],
        [p.lat for p in pieces],
        [p.metres for p in pieces],
    ]
    with connection.cursor() as cursor:
        cursor.execute(query, ([when] if with_facility else []) + arrays)
        for tier, kind, metres in cursor.fetchall():
            stress[str(tier) if tier in (1, 2, 3, 4) else "unknown"] += float(metres)
            facility[kind if kind in FACILITY_KEYS else "unknown"] += float(metres)
    return stress, facility


def stress_breakdown(pieces: list[Piece]) -> dict[str, float]:
    """Metres per stress tier, keyed "1".."4" and "unknown"."""
    return breakdown(pieces, ridetime.WEEKEND)[0]


def trace_leg(variant: str, costing: dict, shape: str, deadline: Deadline) -> dict | None:
    """The leg's edges, by edge walk and then by map snap; None if neither works."""
    for match in ("edge_walk", "map_snap"):
        payload = {
            "encoded_polyline": shape,
            "shape_match": match,
            "costing": "bicycle",
            "costing_options": costing,
            "filters": {
                "attributes": [
                    "edge.way_id",
                    "edge.length",
                    "edge.begin_shape_index",
                    "edge.end_shape_index",
                    "shape",
                ],
                "action": "include",
            },
        }
        try:
            return _call(variant, "trace_attributes", payload, deadline)
        except RouterRefused as refusal:
            logger.info("trace_attributes %s refused on %s: %s", match, variant, refusal)
    return None


@dataclass(frozen=True)
class Dials:
    """Where the rider has the sliders and the ride-time setting.

    `None` is the preset's own starting position (`core.presets`); `when`
    `None` is the setting of the moment the plan is made.
    """

    stress: int | None = None
    hills: int | None = None
    when: str | None = None
    carrying: str | None = None
    assist: bool = False


# How many alternatives a climb search asks the router for, besides its best
# route. The service's `max_alternates` is 3 (valhalla/valhalla-*.json).
SEEK_ALTERNATES = 3

# The longest straight-line span a climb search runs on. Measured on the live
# standard router (2026-09-27, host loaded): three alternates roughly doubled a
# warm 12 km search (0.2 s to 1-2 s) and a warm 65 km one (1.9 s to 3.6 s),
# but a cold 65 km search took 51 s with them and 39 s without, past the 40 s
# budget either way. Past this span the direct route is kept and the answer
# says so, rather than risking a 503 for a route that was always available.
SEEK_MAX_SPAN_M = 50_000


def _climb_of(trip: dict) -> float:
    return climb_and_descent(
        [e for leg in trip.get("legs") or [] for e in leg.get("elevation") or []]
    )[0]


def choose_climb(trips: list[dict], ratio: float) -> int:
    """The index of the trip that climbs most within `ratio` of the first's length.

    The first trip is the router's own best route at the hills detent, so it is
    the direct route the budget is measured against, and it is what is kept
    when nothing else climbs more.
    """
    direct = float((trips[0].get("summary") or {}).get("length", 0.0))
    best, best_climb = 0, _climb_of(trips[0])
    for index, trip in enumerate(trips[1:], start=1):
        length = float((trip.get("summary") or {}).get("length", 0.0))
        climb = _climb_of(trip)
        if length <= direct * ratio and climb > best_climb:
            best, best_climb = index, climb
    return best


def plan(
    points: list[list[float]],
    preset_name: str,
    long_ride: bool = False,
    started: float | None = None,
    dials: Dials | None = None,
) -> dict:
    """Route through `points` on `preset_name`, returning the contract's body.

    `long_ride` gives the request the long-ride time limits, and `started`
    (from `clock()`) is when the request arrived; the budget runs from then,
    or from now if it is not given. `dials` are the sliders and the ride time.
    Raises NoRoute, TooLong, RouterUnavailable, DeadlineExceeded, or KeyError
    for an unknown preset.
    """
    if started is None:
        started = clock()
    dials = dials or Dials()
    if long_ride:
        budget_s, per_call_s = LONG_PLAN_BUDGET_S, LONG_ROUTER_TIMEOUT_S
    else:
        budget_s, per_call_s = PLAN_BUDGET_S, ROUTER_TIMEOUT_S
    deadline = Deadline(started + budget_s - ANSWER_RESERVE_S, per_call_s)
    preset = presets.PRESETS[preset_name]
    stress_dial = (
        presets.stress_start(preset_name, dials.carrying) if dials.stress is None else dials.stress
    )
    hills_dial = preset.hills if dials.hills is None else dials.hills
    when = dials.when or default_when()
    assist = bool(dials.assist) and preset.assist_speed_kmh is not None
    variant = presets.variant_for_ride(preset_name, when, assist)
    costing = presets.costing(preset_name, stress_dial, hills_dial, assist=assist)
    request = {
        "locations": [{"lon": lon, "lat": lat, "type": "break"} for lon, lat in points],
        "costing": "bicycle",
        "costing_options": costing,
        "elevation_interval": ELEVATION_INTERVAL_M,
        "date_time": {"type": 3, "value": planning_time(when=when)},
        "directions_type": "none",
        "units": "kilometers",
    }
    # Past the detent the hills slider is a climb search among the router's
    # alternatives. Valhalla computes alternatives only between two locations,
    # and not inside a long ride's budget, so anything else keeps the route
    # the detent gives and says so.
    seeking = hills_dial > 0 and preset.hills_seek
    seek_limited = None
    if seeking:
        if len(points) != 2:
            seek_limited = "two_points"
        elif long_ride or haversine(Point(*points[0]), Point(*points[1])) > SEEK_MAX_SPAN_M:
            seek_limited = "long_ride"
        else:
            request["alternates"] = SEEK_ALTERNATES
    try:
        try:
            answer = _call(variant, "route", request, deadline)
        except RouterUnavailable:
            # The weekend graph is a fourth router, and a deployment that has
            # not built it yet - or one whose weekend router is down - still
            # answers a weekend ride, on the standard graph it is the twin of.
            # The answer names the graph it came from.
            if variant != Variant.WEEKEND.value:
                raise
            logger.warning("the weekend router did not answer; planning on the standard graph")
            variant = Variant.STANDARD.value
            answer = _call(variant, "route", request, deadline)
    except RouterRefused as refusal:
        if refusal.code in REQUEST_LIMIT_CODES:
            raise TooLong(str(refusal)) from refusal
        if refusal.code not in NO_PATH_CODES | NO_EDGE_CODES:
            logger.warning(
                "the %s router refused a route request (%s, code %s): %s",
                variant,
                refusal.status,
                refusal.code,
                refusal,
            )
        raise NoRoute(str(refusal), no_path=refusal.code in NO_PATH_CODES) from refusal

    trips = [answer.get("trip") or {}] + [
        (alternate or {}).get("trip") or {} for alternate in answer.get("alternates") or []
    ]
    chosen = choose_climb(trips, presets.seek_distance_ratio(hills_dial)) if seeking else 0
    trip = trips[chosen]
    legs = trip.get("legs") or []
    if not legs:
        raise NoRoute("the router returned no legs")

    coordinates: list[tuple[float, float]] = []
    elevations: list[float | None] = []
    stress = dict.fromkeys(STRESS_KEYS, 0.0)
    facility = dict.fromkeys(FACILITY_KEYS, 0.0)
    pieces: list[Piece] = []
    for leg in legs:
        shape = decode_polyline6(leg.get("shape", ""))
        coordinates.extend(shape[1:] if coordinates else shape)
        elevations.extend(leg.get("elevation") or [])
        try:
            trace = trace_leg(variant, costing, leg.get("shape", ""), deadline)
        except DeadlineExceeded:
            # The route is found, so it is answered; a leg left untraced is
            # unknown, and once the budget is gone `_call` starts no more.
            logger.info("the budget ran out tracing a leg on %s", variant)
            trace = None
        if trace is None:
            untraced = float(leg.get("summary", {}).get("length", 0.0)) * 1000.0
            stress["unknown"] += untraced
            facility["unknown"] += untraced
        else:
            pieces.extend(pieces_of_trace(trace))
    traced_stress, traced_facility = breakdown(pieces, when)
    for key, metres in traced_stress.items():
        stress[key] += metres
    for key, metres in traced_facility.items():
        facility[key] += metres

    summary = trip.get("summary") or {}
    climb, descent = climb_and_descent(elevations)
    hills_seek = None
    if seeking:
        direct = trips[0].get("summary") or {}
        hills_seek = {
            "candidates": len(trips),
            "chosen": chosen,
            "extra_climb_m": round(climb - _climb_of(trips[0]), 1),
            "extra_distance_m": round(
                (float(summary.get("length", 0.0)) - float(direct.get("length", 0.0))) * 1000.0, 1
            ),
            "limited": seek_limited,
        }
    return {
        "preset": preset.name,
        "variant": variant,
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in coordinates],
        },
        "distance_m": round(float(summary.get("length", 0.0)) * 1000.0, 1),
        "duration_s": round(float(summary.get("time", 0.0)), 1),
        "climb_m": round(climb, 1),
        "descent_m": round(descent, 1),
        "stress_m": {key: round(metres, 1) for key, metres in stress.items()},
        "facility_m": {key: round(metres, 1) for key, metres in facility.items()},
        "dials": {
            "stress": stress_dial,
            "hills": hills_dial,
            "when": when,
            "carrying": presets.carrying_of(preset_name, dials.carrying),
            "assist": assist,
        },
        "hills_seek": hills_seek,
        "attribution": list(ATTRIBUTION),
    }


# PLAN, Licensing, and the public-tier rules in force (owner decision of
# 2026-09-26): ODbL attribution for everything OpenStreetMap-derived, which is
# the route itself and its stress tiers. DDOT's traffic volume ("2024 Traffic
# Volume" on Open Data DC) is CC BY 4.0, whose section 3(a)(1)(B) asks that an
# adaptation say it was modified and link the licence: the counts are
# normalised and fed to the classifier, so the credit says "adapted". VDOT's
# volume layer states no licence and is credited plainly. USGS 3DEP for the
# elevation the climb is computed from. Protomaps is credited by the map,
# which draws its basemap; nothing in a route response comes from it.
ATTRIBUTION = (
    "© OpenStreetMap contributors, ODbL",
    "Stress tiers use traffic volume from the District Department of Transportation,"
    " adapted, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
    "Traffic volume: Virginia Department of Transportation",
    "Elevation: USGS 3D Elevation Program",
)
