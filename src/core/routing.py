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

Every request has one time budget, `PLAN_BUDGET_S`, across all of its router
calls. gunicorn kills a worker at its 60 s timeout and Caddy then answers an
empty 502; the budget ends the request well before that with an answer the
contract names (503 with Retry-After), and every call's socket timeout is
clipped to what is left of it.

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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.utils import timezone

from pipeline.schema import validate_schema_name
from routemaker.geo import Point, haversine
from routemaker.measure import elevation_gain

from . import presets

logger = logging.getLogger(__name__)

# Metres between elevation samples. 3DEP at 1 arc-second is about 30 m on the
# ground here, so a finer interval samples the same cell twice.
ELEVATION_INTERVAL_M = 30

# How long one call to a router may take before the answer is 502. The plan's
# latency target is p95 under 3 s for a 50-mile preview; this is the ceiling
# past which the router is treated as not answering at all.
ROUTER_TIMEOUT_S = 20

# The whole request's budget across every router call. gunicorn's --timeout is
# 60 s (docker/api-entrypoint.sh); 40 leaves room for the stress query and the
# response and is still an answer rather than a killed worker.
PLAN_BUDGET_S = 40

# PLAN, Time-dependent behavior: with no planning time set, requests assume the
# next Saturday at 9:00 local time, so conditional restrictions are evaluated
# rather than ignored. Type 3 is invariant time, which keeps bidirectional A*.
PLANNING_ZONE = ZoneInfo("America/New_York")
PLANNING_WEEKDAY = 5  # Saturday
PLANNING_HOUR = 9

STRESS_KEYS = ("1", "2", "3", "4", "unknown")

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


def _call(variant: str, endpoint: str, payload: dict, deadline: float) -> dict:
    """One router call inside the request's budget; `deadline` is monotonic."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DeadlineExceeded(f"no time left for {endpoint}")
    url = f"{settings.VALHALLA_UPSTREAMS[variant]}/{endpoint}"
    try:
        return _transport(url, payload, min(ROUTER_TIMEOUT_S, remaining))
    except RouterUnavailable as error:
        if time.monotonic() >= deadline:
            raise DeadlineExceeded(f"{endpoint} ran past the budget") from error
        raise


def planning_time(now: datetime | None = None) -> str:
    """The next Saturday at 9:00 in the region's time, as Valhalla's local time."""
    local = (now or timezone.now()).astimezone(PLANNING_ZONE)
    days = (PLANNING_WEEKDAY - local.weekday()) % 7
    candidate = (local + timedelta(days=days)).replace(
        hour=PLANNING_HOUR, minute=0, second=0, microsecond=0
    )
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate.strftime("%Y-%m-%dT%H:%M")


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
SELECT seg.stress_tier, sum(p.metres)
FROM unnest(%s::bigint[], %s::float8[], %s::float8[], %s::float8[])
     AS p(way_id, lon, lat, metres)
LEFT JOIN LATERAL (
    SELECT s.stress_tier
    FROM {schema}.segment AS s
    WHERE s.osm_way_id = p.way_id
    ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)
    LIMIT 1
) AS seg ON true
GROUP BY seg.stress_tier
"""


def stress_breakdown(pieces: list[Piece]) -> dict[str, float]:
    """Metres per stress tier, keyed "1".."4" and "unknown"."""
    totals = dict.fromkeys(STRESS_KEYS, 0.0)
    if not pieces:
        return totals
    # The schema name comes from settings and is validated the way every DDL
    # that names it is; an identifier cannot be a query parameter.
    query = _STRESS_JOIN.format(schema=validate_schema_name(settings.SEGMENT_SCHEMA_LIVE))
    with connection.cursor() as cursor:
        cursor.execute(
            query,
            [
                [p.way_id for p in pieces],
                [p.lon for p in pieces],
                [p.lat for p in pieces],
                [p.metres for p in pieces],
            ],
        )
        for tier, metres in cursor.fetchall():
            key = str(tier) if tier in (1, 2, 3, 4) else "unknown"
            totals[key] += float(metres)
    return totals


def trace_leg(variant: str, costing: dict, shape: str, deadline: float) -> dict | None:
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


def plan(points: list[list[float]], preset_name: str) -> dict:
    """Route through `points` on `preset_name`, returning the contract's body.

    Raises NoRoute, TooLong, RouterUnavailable, DeadlineExceeded, or KeyError
    for an unknown preset.
    """
    deadline = time.monotonic() + PLAN_BUDGET_S
    preset = presets.PRESETS[preset_name]
    costing = presets.costing(preset_name)
    request = {
        "locations": [{"lon": lon, "lat": lat, "type": "break"} for lon, lat in points],
        "costing": "bicycle",
        "costing_options": costing,
        "elevation_interval": ELEVATION_INTERVAL_M,
        "date_time": {"type": 3, "value": planning_time()},
        "directions_type": "none",
        "units": "kilometers",
    }
    try:
        answer = _call(preset.variant, "route", request, deadline)
    except RouterRefused as refusal:
        if refusal.code in REQUEST_LIMIT_CODES:
            raise TooLong(str(refusal)) from refusal
        if refusal.code not in NO_PATH_CODES | NO_EDGE_CODES:
            logger.warning(
                "the %s router refused a route request (%s, code %s): %s",
                preset.variant,
                refusal.status,
                refusal.code,
                refusal,
            )
        raise NoRoute(str(refusal), no_path=refusal.code in NO_PATH_CODES) from refusal

    trip = answer.get("trip") or {}
    legs = trip.get("legs") or []
    if not legs:
        raise NoRoute("the router returned no legs")

    coordinates: list[tuple[float, float]] = []
    elevations: list[float | None] = []
    stress = dict.fromkeys(STRESS_KEYS, 0.0)
    pieces: list[Piece] = []
    for leg in legs:
        shape = decode_polyline6(leg.get("shape", ""))
        coordinates.extend(shape[1:] if coordinates else shape)
        elevations.extend(leg.get("elevation") or [])
        trace = trace_leg(preset.variant, costing, leg.get("shape", ""), deadline)
        if trace is None:
            stress["unknown"] += float(leg.get("summary", {}).get("length", 0.0)) * 1000.0
        else:
            pieces.extend(pieces_of_trace(trace))
    for key, metres in stress_breakdown(pieces).items():
        stress[key] += metres

    summary = trip.get("summary") or {}
    climb, descent = climb_and_descent(elevations)
    return {
        "preset": preset.name,
        "variant": preset.variant,
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in coordinates],
        },
        "distance_m": round(float(summary.get("length", 0.0)) * 1000.0, 1),
        "duration_s": round(float(summary.get("time", 0.0)), 1),
        "climb_m": round(climb, 1),
        "descent_m": round(descent, 1),
        "stress_m": {key: round(metres, 1) for key, metres in stress.items()},
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
