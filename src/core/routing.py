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

import bisect
import dataclasses
import http.client
import itertools
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings
from django.db import connection
from django.utils import timezone

from pipeline.schema import MASS_WIDTH_COLUMN, validate_schema_name
from pipeline.variants import Variant
from routemaker import calm, climbs, describe, flow, intersections, ridetime, trace_junctions, zoo
from routemaker import detour as detour_rules
from routemaker import profile as profile_rules
from routemaker.facility import FACILITIES
from routemaker.geo import Point, haversine
from routemaker.massflow import band_of
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

STRESS_KEYS = ("1", "2", "3", "4", "5", "unknown")
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
    """The router answered 4xx, or 500 with one of its catch-all codes;
    `code` is Valhalla's error_code if it gave one."""

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


# Valhalla's catch-all error codes, one per service stage (src/exceptions.cc).
UNKNOWN_ERROR_CODES = frozenset({199, 299, 499})


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
        try:
            body = json.loads(error.read() or b"{}")
        except (OSError, http.client.HTTPException, ValueError):
            # Unreadable, cut off or not JSON: the status alone decides.
            body = {}
        if not isinstance(body, dict):
            body = {}
        # From 3.6.0 Valhalla answers its catch-all "Unknown" errors (199, 299,
        # 499: an exception it did not classify while serving this request) with
        # 500 rather than 400 (valhalla/valhalla#5359). That is still one
        # request the router could not serve, not a router that is down, so it
        # is a refusal as it was under 3.5.1: read as an outage it would mark a
        # weekend or off-road router down for every rider over one bad request.
        if 400 <= error.code < 500 or (
            error.code == 500 and body.get("error_code") in UNKNOWN_ERROR_CODES
        ):
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
    return trace_junctions.decode_polyline6(encoded)


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
    # What the route description reads (routemaker.describe): the edge's street
    # names, Valhalla's `use`, and the compass headings it begins and ends on.
    # Not part of a piece's identity, and all optional: a trace from a router
    # that was not asked for them (an older one, a test double) has none.
    names: tuple[str, ...] = field(default=(), compare=False)
    use: str = field(default="", compare=False)
    heading_in: float | None = field(default=None, compare=False)
    heading_out: float | None = field(default=None, compare=False)
    # The edge's costing attributes (`calm.road_of_edge`), which the rolling stress score
    # prices each road by (docs/stress/stress-number.md section 4); None from a trace that
    # has none.
    road: calm.Road | None = field(default=None, compare=False)


def _heading(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


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
        names = tuple(n for n in edge.get("names") or () if isinstance(n, str) and n.strip())
        # Keyword arguments for every piece of this edge.
        info = {
            "names": names,
            "use": str(edge.get("use") or ""),
            "heading_in": _heading(edge.get("begin_heading")),
            "heading_out": _heading(edge.get("end_heading")),
            "road": calm.road_of_edge(edge, miles=trace.get("units") == "miles"),
        }
        stretches = []
        for a, b in zip(shape[begin:end], shape[begin + 1 : end + 1], strict=True):
            stretches.append((a, b, haversine(Point(*a), Point(*b))))
        ground = sum(s[2] for s in stretches)
        if ground <= 0:
            # A degenerate edge: all its length on its first vertex.
            (lon, lat) = shape[begin]
            pieces.append(Piece(way_id, lon, lat, length, **info))
            continue
        for a, b, d in stretches:
            if d > 0:
                pieces.append(
                    Piece(way_id, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, length * d / ground, **info)
                )
    return pieces


# One row per piece, in the pieces' order: the tier and facility class of the
# segment nearest the piece on its way. The breakdown sums them; the route's
# coloured sections (`stress_spans`) keep their order.
_STRESS_JOIN = """
SELECT {tier}, {facility}, seg.is_unpaved, seg.road_lanes, seg.road_oneway{capacity_out}
FROM unnest(%s::bigint[], %s::float8[], %s::float8[])
     WITH ORDINALITY AS p(way_id, lon, lat, ordinality)
LEFT JOIN LATERAL (
    SELECT s.stress_tier, s.is_unpaved, {traits}, {columns}
    FROM {schema}.segment AS s
    WHERE s.osm_way_id = p.way_id
    ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)
    LIMIT 1
) AS seg ON true
ORDER BY p.ordinality
"""

# Whether the live segment table has the Mass Ride capacity column
# (`pipeline.schema.MASS_WIDTH_COLUMN`): written by the first rebuild after the
# capacity map shipped. Without it a Mass Ride's sections carry no capacity and
# the map draws them by stress, as it did. Remembered once seen, as above.
_capacity_column_seen = False


def _has_capacity_column(schema: str) -> bool:
    global _capacity_column_seen
    if _capacity_column_seen:
        return True
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'segment' AND column_name = %s",
            [schema, MASS_WIDTH_COLUMN],
        )
        _capacity_column_seen = cursor.fetchone()[0] == 1
    return _capacity_column_seen


# A road closed to motor traffic only at set times is a path for a ride inside
# the closure, and the road it is otherwise for any other (routemaker.facility).
_FACILITY_AT = "CASE WHEN %s = ANY(seg.car_free_when) THEN 'path' ELSE seg.facility END"
# And its stress is a closed road's: tier 1, as the weekend graph routes it
# (pipeline.run.facility_derived), rather than the tier of the road with cars on it.
_TIER_AT = "CASE WHEN %s = ANY(seg.car_free_when) THEN 1 ELSE seg.stress_tier END"

# Whether the live segment table has the facility columns yet. They arrive with
# the first rebuild after this code; until then the breakdown is all unknown
# rather than an error. Remembered once seen, since a schema is only ever
# replaced by a newer build of itself.
_facility_columns_seen = False


def _has_trait_columns(schema: str) -> bool:
    from .junctions import has_trait_columns

    return has_trait_columns(schema)


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


# The facility classes a ride on the roadway does not use: a mass ride takes
# the general lanes whatever the street marks for bicycles (the owner,
# 2026-09-27: "Mass rides don't need to consider these. Even protected bike
# lanes aren't used."), so on a Mass Ride their length is "none". Only there:
# a rider with "Keep to roads, not trails" on rides the lanes the road has, and
# its breakdown says so (the trails-off correctness review, 3), though the
# no-trail graph gives them no credit (`facility_neutral`).
ROADWAY_ONLY_AS_NONE = frozenset({"protected", "lane"})


class PieceClass(tuple):
    """A piece's (stress key, facility key), as `classify` answers it, with the
    segment's surface beside it: `unpaved` True, False, or None where not known
    (OWNER-DECISIONS 280, for the route description). Still a pair, so every
    reader that unpacks (tier, facility) is unchanged. It also carries the road's
    through lanes a direction and whether it is one-way where the segment table has
    them (None where not), which a Mass Ride's flow figure reads the width from
    (`routemaker.flow`, OWNER-DECISIONS 328)."""

    unpaved: bool | None
    lanes: int | None
    oneway: bool | None
    # The segment's Mass Ride usable width, metres (`pipeline.schema.MASS_WIDTH_COLUMN`:
    # the ride's own direction, parked cars out, DC's Roadway Block first; OWNER-DECISIONS
    # 404, 406), and the riders a minute on the flat it gives (`rpm`), or None where the
    # table has none. The route chart reads its width from here, so the chart and the
    # capacity map always agree (`_flow_stretches`).
    width_m: float | None
    rpm: int | None

    def __new__(
        cls,
        tier: str,
        facility: str,
        unpaved: bool | None = None,
        lanes: int | None = None,
        oneway: bool | None = None,
        width_m: float | None = None,
    ):
        pair = super().__new__(cls, (tier, facility))
        pair.unpaved = unpaved
        pair.lanes = lanes
        pair.oneway = oneway
        pair.width_m = width_m
        pair.rpm = round(flow.level_riders_per_min(width_m)) if width_m is not None else None
        return pair

    def __getnewargs__(self):
        return (self[0], self[1], self.unpaved, self.lanes, self.oneway, self.width_m)


def classify(pieces: list[Piece], when: str, roadway_only: bool = False) -> list[tuple[str, str]]:
    """Each piece's stress key ("1".."5" or "unknown") and facility key
    ("path", "protected", "lane", "none" or "unknown"), in the pieces' order,
    for a ride at `when`, each a `PieceClass` that also carries the segment's
    surface. With `roadway_only` (a ride that takes the roadway: Mass Ride,
    not every ride on the no-trail variant), bicycle lanes of either class are
    "none"; a road closed to cars is still a path."""
    if not pieces:
        return []
    # The schema name comes from settings and is validated the way every DDL
    # that names it is; an identifier cannot be a query parameter.
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    with_facility = _has_facility_columns(schema)
    with_capacity = _has_capacity_column(schema)
    query = _STRESS_JOIN.format(
        schema=schema,
        tier=_TIER_AT if with_facility else "seg.stress_tier",
        facility=_FACILITY_AT if with_facility else "NULL",
        columns=("s.facility, s.car_free_when" if with_facility else "NULL AS facility")
        + (f", s.{MASS_WIDTH_COLUMN}" if with_capacity else ""),
        traits=(
            "s.road_lanes, s.road_oneway"
            if _has_trait_columns(schema)
            else "NULL::smallint AS road_lanes, NULL::boolean AS road_oneway"
        ),
        capacity_out=f", seg.{MASS_WIDTH_COLUMN}" if with_capacity else "",
    )
    arrays = [[p.way_id for p in pieces], [p.lon for p in pieces], [p.lat for p in pieces]]
    classes = []
    with connection.cursor() as cursor:
        cursor.execute(query, ([when, when] if with_facility else []) + arrays)
        for row in cursor.fetchall():
            tier, kind = row[0], row[1]
            unpaved = row[2] if len(row) > 2 and isinstance(row[2], bool) else None
            lanes = row[3] if len(row) > 3 and isinstance(row[3], int) else None
            oneway = row[4] if len(row) > 4 and isinstance(row[4], bool) else None
            width = row[5] if with_capacity and len(row) > 5 and row[5] is not None else None
            if roadway_only and kind in ROADWAY_ONLY_AS_NONE:
                kind = "none"
            classes.append(
                PieceClass(
                    str(tier) if tier in (1, 2, 3, 4, 5) else "unknown",
                    kind if kind in FACILITY_KEYS else "unknown",
                    unpaved,
                    lanes,
                    oneway,
                    None if width is None else float(width),
                )
            )
    return classes


def breakdown(
    pieces: list[Piece], when: str, roadway_only: bool = False
) -> tuple[dict[str, float], dict[str, float]]:
    """Metres per stress tier and per facility class, for a ride at `when`.

    Stress is keyed "1".."5" and "unknown", facility "path", "protected",
    "lane", "none" and "unknown"; each sums to the traced length
    (`classify`, summed).
    """
    return totals(zip(pieces, classify(pieces, when, roadway_only), strict=True))


def totals(classified) -> tuple[dict[str, float], dict[str, float]]:
    """Metres per stress key and per facility key of (piece, (tier, facility)) pairs."""
    stress = dict.fromkeys(STRESS_KEYS, 0.0)
    facility = dict.fromkeys(FACILITY_KEYS, 0.0)
    for piece, (tier, kind) in classified:
        stress[tier] += piece.metres
        facility[kind] += piece.metres
    return stress, facility


# A coloured section shorter than this is folded into its neighbour: a few
# metres of a crossing or a driveway cannot be seen on the map at any zoom the
# planner is used at, and a long ride would otherwise carry thousands of them.
# The totals (`stress_m`, `facility_m`) are summed from the pieces, not from
# the sections, so they stay exact.
MIN_SPAN_M = 10.0


def stress_spans(stretches: list[tuple], capacity: bool = False) -> list[dict]:
    """The route's coloured sections, in route order.

    `stretches` is (metres, stress key, facility key[, unpaved[, rpm[, outside DC]]]) in the order
    ridden; the answer is [{from_m, to_m, tier, facility, unpaved}] in whole metres
    along the route, adjacent equal sections merged and those under MIN_SPAN_M
    folded into the one before (or, first on the route, the one after). `tier` is
    1-5 or null (unknown); `facility` is the class or null; `unpaved` True or False
    where the segments say, else null (OWNER-DECISIONS 302: the route line draws an
    unpaved section in the brown ramp, so a section ends where the surface changes).

    With `capacity` (a Mass Ride on a table that has the capacity column; OWNER-DECISIONS
    325-327) a section also ends where the capacity changes band, and carries `rpm`: the
    lowest capacity along it, riders a minute, or null where the segments have none. A
    stretch marked Avoid (tier 5) is one section whatever its capacity: it shows only
    "Avoid" (325). A section folded into its neighbour does not lower the neighbour's
    `rpm`, so a section's figure always lies in the band its colour says. A stretch
    outside the District (OWNER-DECISIONS 427; border roads are inside, 420) is its own
    section with `rpm` null and `outside_dc` true: Mass Ride figures are not supported there.
    """
    # Pieces are cut at every shape vertex, so a long stretch of one class
    # arrives as many short pieces: they are joined before anything is judged
    # too short to show.
    spans: list[list] = []  # [length, tier, facility, unpaved, band, lowest rpm]
    for stretch in stretches:
        metres, tier, kind = stretch[:3]
        unpaved = stretch[3] if len(stretch) > 3 else None
        outside = capacity and len(stretch) > 5 and bool(stretch[5])
        rpm = stretch[4] if capacity and len(stretch) > 4 and not outside else None
        band = (
            "outside"
            if outside
            else band_of(rpm)
            if capacity and rpm is not None and tier != "5"
            else None
        )
        if spans and spans[-1][1:5] == [tier, kind, unpaved, band]:
            spans[-1][0] += metres
            spans[-1][5] = _lowest(spans[-1][5], rpm)
        else:
            spans.append([metres, tier, kind, unpaved, band, rpm])
    folded: list[list] = []
    for span in spans:
        if folded and (span[0] < MIN_SPAN_M or folded[-1][1:5] == span[1:5]):
            folded[-1][0] += span[0]
            if folded[-1][1:5] == span[1:5]:
                folded[-1][5] = _lowest(folded[-1][5], span[5])
        elif folded and folded[-1][0] < MIN_SPAN_M:
            # The first section was the short one: it takes this one's class.
            folded[-1] = [folded[-1][0] + span[0], *span[1:]]
        else:
            folded.append(list(span))
    out = []
    at = 0.0
    for length, tier, kind, unpaved, _band, rpm in folded:
        start, at = at, at + length
        if out and out[-1]["to_m"] == round(at):
            out[-1]["to_m"] = round(at)
            continue
        entry = {
            "from_m": round(start),
            "to_m": round(at),
            "tier": int(tier) if tier != "unknown" else None,
            "facility": kind if kind != "unknown" else None,
            "unpaved": unpaved,
        }
        if capacity:
            entry["rpm"] = None if tier == "5" else rpm
            if _band == "outside":
                entry["outside_dc"] = True
        out.append(entry)
    return out


def _lowest(a: int | None, b: int | None) -> int | None:
    """The lower of two capacities, ignoring a missing one."""
    return b if a is None else a if b is None else min(a, b)


_ADJUSTMENT_JOIN = """
SELECT seg.stress_adjustment_id, seg.stress_tier, seg.stress_adjustment_direction,
       seg.stress_adjustment_category, seg.stress_adjustment_note,
       seg.stress_adjustment_display, sum(p.metres)
FROM unnest(%s::bigint[], %s::float8[], %s::float8[], %s::float8[])
     WITH ORDINALITY AS p(way_id, lon, lat, metres, ordinality)
JOIN LATERAL (
    SELECT s.stress_tier, s.stress_adjustment_id, s.stress_adjustment_direction,
           s.stress_adjustment_category, s.stress_adjustment_note, s.stress_adjustment_display
    FROM {schema}.segment AS s
    WHERE s.osm_way_id = p.way_id
    ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)
    LIMIT 1
) AS seg ON true
WHERE seg.stress_adjustment_id IS NOT NULL
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY min(p.ordinality)
"""
ADJUSTMENT_COLUMNS = (
    "stress_adjustment_id",
    "stress_adjustment_direction",
    "stress_adjustment_category",
    "stress_adjustment_note",
    "stress_adjustment_display",
)
_adjustment_columns_seen = False


def _has_adjustment_columns(schema: str) -> bool:
    global _adjustment_columns_seen
    if _adjustment_columns_seen:
        return True
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'segment' AND column_name = ANY(%s)",
            [schema, list(ADJUSTMENT_COLUMNS)],
        )
        _adjustment_columns_seen = cursor.fetchone()[0] == len(ADJUSTMENT_COLUMNS)
    return _adjustment_columns_seen


def adjustments_used(pieces: list[Piece]) -> list[dict]:
    """The curated stress adjustments the route rides over, in route order.

    The owner, 2026-09-27: "In many cases there's an acceptable trail. Only
    provide the warnings if the route goes over the road." So a note belongs
    in the answer of a route that uses the stretch, and this is where it
    comes from. Each entry is the adjustment's id, the tier the route rode at
    and the metres on it; the why (direction, category, note, display) is null
    except where the segment table carries it, which is a public adjustment whose
    words the owner approved (`pipeline.writers._adjustment_columns`). A
    hidden one is only "adjusted". Empty until the live table has the columns.
    """
    if not pieces:
        return []
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not _has_adjustment_columns(schema):
        return []
    arrays = [
        [p.way_id for p in pieces],
        [p.lon for p in pieces],
        [p.lat for p in pieces],
        [p.metres for p in pieces],
    ]
    query = _ADJUSTMENT_JOIN.format(schema=schema)
    used = []
    with connection.cursor() as cursor:
        cursor.execute(query, arrays)
        for adjustment_id, tier, direction, category, note, display, metres in cursor.fetchall():
            # The why is null where the table holds none: a hidden or
            # unapproved adjustment, which the writer never fills.
            used.append(
                {
                    "adjustment_id": adjustment_id,
                    "tier": tier,
                    "adjusted": True,
                    "length_m": round(float(metres), 1),
                    "direction": direction,
                    "category": category,
                    "public_note": note,
                    "display": display,
                }
            )
    return used


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
                    # The route description's street names (routemaker.describe).
                    "edge.names",
                    "shape",
                    # What the intersection model reads (core.junctions), and what the
                    # rolling stress score prices each road by (routemaker.calm).
                    *dict.fromkeys(trace_junctions.TRACE_ATTRIBUTES + calm.TRACE_ATTRIBUTES),
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
    avoid_gravel: bool = False
    # "Keep to roads, not trails" (trails off): plan on the no-trail graph, whatever the ride type
    # (`presets.variant_for_ride`). Mass Ride is always on it.
    trails_off: bool = False
    # The rider's "Target distance" (metres, OWNER-DECISIONS 271), for the top of the
    # stress slider only (`presets.maxcalm_for`): a soft goal with a hard ceiling
    # (`presets.target_ceiling_m`); None: no target, `presets.default_ceiling_m`.
    target_distance_m: int | None = None
    # The rider's total system weight in kilograms (OWNER-DECISIONS 264): rider, bike
    # and load, for the effort the Hills slider's avoid half weighs at the top of the
    # stress slider; None: `presets.system_weight_for`.
    system_weight_kg: int | None = None
    # "Make it a loop" (OWNER-DECISIONS 266): return to the start by a different way.
    # A ride whose last point is its first is a loop whatever this says.
    loop: bool = False


# A ride ends where it starts if its last point is within this of its first (metres).
LOOP_SAME_M = 50.0


def is_round_trip(points: list) -> bool:
    """Whether the points start and end in the same place, with a place between."""
    return len(points) >= 3 and haversine(Point(*points[0]), Point(*points[-1])) <= LOOP_SAME_M


def loop_wanted(points: list, flag: bool, preset_name: str) -> bool:
    """Whether a plan is a loop (OWNER-DECISIONS 266): the rider asked for one, or the
    ride ends where it starts. Not on a Mass Ride, which is one route by design."""
    return preset_name != "mass-ride" and len(points) >= 2 and (flag or is_round_trip(points))


def loop_points(points: list, loop: bool) -> list:
    """The points a loop is planned through: the rider's, and the start again unless
    the ride already ends there."""
    if not loop or is_round_trip(points):
        return points
    return [*points, points[0]]


def loop_stats(pieces: list, leg_runs: list) -> dict | None:
    """What a loop's way back shares with its way out, from its traced pieces and the
    run of pieces of each leg: `shared_m` of `return_m` metres, as `overlap_pct`; None
    where the last leg was not traced."""
    if len(leg_runs) < 2 or not isinstance(leg_runs[-1], tuple):
        return None
    start, end = leg_runs[-1]
    out_ways = {piece.way_id for piece in pieces[:start] if piece.way_id}
    back = pieces[start:end]
    shared = sum(piece.metres for piece in back if piece.way_id in out_ways)
    total = sum(piece.metres for piece in back)
    return {
        "shared_m": round(shared, 1),
        "return_m": round(total, 1),
        "overlap_pct": round(100.0 * shared / total, 1) if total > 0 else None,
    }


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

# The avoid half's span, shorter: it is where Cargo, Group Ride, E-bike and
# Mass Ride start, so most of their rides ask for alternatives, and on the live
# router (OPS review, 2026-09-28, host loaded) a 42-48 km request with them took
# 43-47 s where the plain one answered in 33 s.
AVOID_MAX_SPAN_M = 25_000

# The most a request for alternatives may take before it is asked again
# without them, inside what is left of the budget: the search for a better
# climb or a gentler route is worth a few seconds, not the ride.
ALTERNATES_TIMEOUT_S = 18

# The weekend router, a fourth service that may not be up yet (between the
# deploy and `up -d valhalla-weekend`) or may hang: one call to it may take at
# most this long before the ride is planned on the standard graph, and a
# failure is remembered this long, so every weekend ride in the meantime goes
# straight to the standard graph instead of paying the failure again.
WEEKEND_TIMEOUT_S = 15
WEEKEND_FAILURE_TTL_S = 60

# The traffic-wins check (`no_busier_than_middle`) runs after the ride's own
# route and before the answer's traces, so it must leave those traces their
# time: the middle call and its two exposure traces run inside what is left of
# the budget less this reserve, and are skipped - the hill-avoiding route kept -
# when less than MIDDLE_MIN_S would be left for the middle call (correctness
# review, round 3: a slow first route and a hung middle call answered at 37 s
# with the whole breakdown "unknown").
MIDDLE_TRACE_RESERVE_S = 8
MIDDLE_MIN_S = 4
_weekend_failed_at: float | None = None
# The off-road router (`Variant.OFFROAD`, Gravel and Mountain Goat) is a fifth
# service and falls back to the standard graph exactly as the weekend one does,
# on the same timeout and failure memory: a deployment that has not built it
# yet, or whose router is down, still answers, without the mountain-bike class.
_offroad_failed_at: float | None = None
TWIN_VARIANTS = (Variant.WEEKEND.value, Variant.OFFROAD.value)


def _weekend_down() -> bool:
    return _weekend_failed_at is not None and clock() - _weekend_failed_at < WEEKEND_FAILURE_TTL_S


def _offroad_down() -> bool:
    return _offroad_failed_at is not None and clock() - _offroad_failed_at < WEEKEND_FAILURE_TTL_S


def _twin_down(variant: str) -> bool:
    return _offroad_down() if variant == Variant.OFFROAD.value else _weekend_down()


def _promoted_row(variant: str) -> bool:
    """Whether a build of this variant has been promoted: its settings row
    exists. A deployment before its first rebuild with the graph, or after a
    rollback that withdrew it, has none."""
    from core.models import ValhallaUpstream

    return ValhallaUpstream.objects.filter(variant=variant).exclude(build_id="").exists()


def _weekend_is_promoted() -> bool:
    return _promoted_row(Variant.WEEKEND.value)


def _offroad_is_promoted() -> bool:
    return _promoted_row(Variant.OFFROAD.value)


def _is_promoted(variant: str) -> bool:
    if variant == Variant.OFFROAD.value:
        return _offroad_is_promoted()
    return _weekend_is_promoted()


def _mark_weekend(ok: bool) -> None:
    global _weekend_failed_at
    _weekend_failed_at = None if ok else clock()


def _mark_twin(variant: str, ok: bool) -> None:
    global _offroad_failed_at
    if variant == Variant.OFFROAD.value:
        _offroad_failed_at = None if ok else clock()
    else:
        _mark_weekend(ok)


def _climb_of(trip: dict) -> float:
    return climb_and_descent(
        [e for leg in trip.get("legs") or [] for e in leg.get("elevation") or []]
    )[0]


def grade_profile(trip: dict) -> list[tuple[float, float | None]]:
    """The trip's elevation profile, (metres along it, elevation), in the order
    ridden: the router samples every ELEVATION_INTERVAL_M along each leg."""
    profile: list[tuple[float, float | None]] = []
    offset = 0.0
    for leg in trip.get("legs") or []:
        heights = leg.get("elevation") or []
        profile.extend((offset + i * ELEVATION_INTERVAL_M, h) for i, h in enumerate(heights))
        offset += float((leg.get("summary") or {}).get("length", 0.0)) * 1000.0
        # A leg's samples do not join the next leg's: a gap between them.
        profile.append((offset, None))
    return profile


def _router_cost(trip: dict) -> float:
    """Valhalla's own cost of a trip: its time with every cost-only penalty
    the request priced in (the stress penalty, the tier-5 entry charge, the
    grade penalty, maneuvers, gates). A body without it (an older router)
    falls back to the time."""
    summary = trip.get("summary") or {}
    return float(summary.get("cost", summary.get("time", 0.0)))


def choose_gentlest(trips: list[dict], weight: float, brake_grade: float | None) -> int:
    """The index of the trip whose router cost plus weighted sustained-grade
    cost is least (routemaker.climbs): the avoid half of the hills slider.

    The first trip is the router's own best route, already the cheapest by
    Valhalla's own cost, which carries the stress, tier-5 and per-edge grade
    penalties; an alternative wins only where what that cost cannot see - how
    long each climb and descent goes on - saves more than it costs. Ranked by
    time, as it first was, a faster alternative won on time alone and traded
    calm roads for busy ones (correctness review, 2026-09-28: Mass Ride at -95
    over the Frederick Douglass roadway).
    """
    best, best_score = 0, None
    for index, trip in enumerate(trips):
        score = _router_cost(trip) + weight * climbs.grade_cost_s(grade_profile(trip), brake_grade)
        if best_score is None or score < best_score:
            best, best_score = index, score
    return best


def _trace(
    variant: str, costing: dict, shape: str, deadline: Deadline, traces: dict | None = None
) -> dict | None:
    """`trace_leg`, remembered in `traces` (one plan's) so that a route traced
    for a guard is not traced again for the answer. A trace that raised is not
    remembered."""
    if traces is None:
        return trace_leg(variant, costing, shape, deadline)
    key = (variant, shape, json.dumps(costing, sort_keys=True))
    if key not in traces:
        traces[key] = trace_leg(variant, costing, shape, deadline)
    return traces[key]


def _exposure(
    variant: str,
    costing: dict,
    trip: dict,
    when: str,
    deadline: Deadline,
    traces: dict | None = None,
    exposure: presets.Exposure = presets.EXPOSURE_STANDARD,
):
    """A trip's traffic exposure by the plan's weights (`presets.Exposure`: LTS 3
    once, LTS 4 twice and Avoid three times unless the ride type weighs them
    otherwise) and its metres of LTS 4 and Avoid, as (exposure, metres); None
    when a leg cannot be traced."""
    pieces: list[Piece] = []
    for leg in trip.get("legs") or []:
        trace = _trace(variant, costing, leg.get("shape", ""), deadline, traces)
        if trace is None:
            return None
        pieces.extend(pieces_of_trace(trace))
    stress, _facility = breakdown(pieces, when)
    weights = exposure.weights
    return sum(weights[tier] * stress[tier] for tier in weights), stress["4"] + stress["5"]


def _hold_refuses(held: tuple, reference: tuple, exposure: presets.Exposure) -> bool:
    """Whether the LTS 4 hold (OWNER-DECISIONS 250) refuses a route: on a
    stress-averse ride, more LTS 4 and Avoid metres than the reference's (an
    exposure reading's second item), with `refine.LTS4_SLACK_M` of slack."""
    from . import refine

    return exposure.hold_lts4 and held[1] > reference[1] + refine.LTS4_SLACK_M


def calmer_or_own(
    trips: list[dict],
    chosen: int,
    variant: str,
    costing: dict,
    when: str,
    deadline: Deadline,
    traces: dict | None = None,
    exposure: presets.Exposure = presets.EXPOSURE_STANDARD,
) -> int:
    """`chosen`, if it is no busier than the router's own route, else 0. Busier
    is by the plan's exposure weights, and on a ride with the LTS 4 hold (Trailmaxxing,
    Cargo with passengers) an alternative with more LTS 4 and Avoid metres is
    never chosen, so that the search after it measures its hold against the
    router's own route (GATE-corr SF1).

    The avoid half weighs sustained grades the router's cost cannot see, and
    on a few plans that bought a gentler profile with busier roads
    (correctness review, 2026-09-28: Foggy Bottom to Mount Pleasant at stress
    90 took 1.1 km more of LTS 3-4 to save 7.5 s of sustained climbing). The
    hills slider never trades calm roads for busy ones: the alternative is
    traced, and kept only if its exposure is no worse than the router's own
    route's. Only when an alternative won, so a plain plan pays nothing.
    """
    if chosen == 0:
        return 0
    try:
        own = _exposure(variant, costing, trips[0], when, deadline, traces, exposure)
        alternative = _exposure(variant, costing, trips[chosen], when, deadline, traces, exposure)
    except (DeadlineExceeded, RouterUnavailable):
        return 0
    if own is None or alternative is None or alternative[0] > own[0]:
        return 0
    if _hold_refuses(alternative, own, exposure):
        return 0
    return chosen


def no_busier_than_middle(
    trip: dict,
    request: dict,
    variant: str,
    costing: dict,
    middle_costing: dict,
    when: str,
    deadline: Deadline,
    traces: dict | None = None,
    exposure: presets.Exposure = presets.EXPOSURE_STANDARD,
) -> tuple[dict, bool]:
    """The route to answer on the avoid half, and whether it is the middle's.

    The owner, 2026-09-28 (OWNER-DECISIONS item 61), asked whether hill
    avoidance may make a route busier: "Traffic wins (Recommended)". Valhalla's
    own `use_hills` trades grade against the stress penalty inside its cost, so
    at the avoid end the router's own route can be flatter and busier than the
    same trip at the middle of the hills slider (89 plans of the correctness
    reviewer's grid). So the same trip is asked for again at the middle - one
    /route without alternatives, at most ALTERNATES_TIMEOUT_S - and both are
    traced: if the hill-avoiding route's exposure (by the plan's weights, LTS 3 +
    2 x LTS 4 + 3 x tier 5 metres unless the ride type weighs them otherwise) is
    worse, the middle's route is the answer, unless it has more LTS 4 and Avoid
    metres and the ride holds them (GATE-corr SF1). A middle call
    or a trace that fails, or no time left, keeps the hill-avoiding route.

    All of it runs inside the budget less MIDDLE_TRACE_RESERVE_S, which is the
    answer's own traces' time, and none of it runs if that leaves the middle
    call less than MIDDLE_MIN_S; on the weekend graph the middle call is held
    to WEEKEND_TIMEOUT_S, as every call there is.
    """
    step = Deadline(deadline.at - MIDDLE_TRACE_RESERVE_S, deadline.per_call_s)
    limit = min(deadline.per_call_s, ALTERNATES_TIMEOUT_S, step.at - clock())
    if variant in TWIN_VARIANTS:
        limit = min(limit, WEEKEND_TIMEOUT_S)
    if limit < MIDDLE_MIN_S:
        return trip, False
    middle_request = {key: value for key, value in request.items() if key != "alternates"} | {
        "costing_options": middle_costing
    }
    try:
        answer = _call(variant, "route", middle_request, Deadline(step.at, limit))
        middle = answer.get("trip") or {}
        if not middle.get("legs"):
            return trip, False
        own = _exposure(variant, costing, trip, when, step, traces, exposure)
        calmer = _exposure(variant, middle_costing, middle, when, step, traces, exposure)
    except (DeadlineExceeded, RouterUnavailable, RouterRefused):
        return trip, False
    if own is None or calmer is None or own[0] <= calmer[0]:
        return trip, False
    if _hold_refuses(calmer, own, exposure):
        return trip, False
    return middle, True


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


def _route(variant: str, request: dict, deadline: Deadline) -> tuple[dict, bool]:
    """One /route, and whether a request for alternatives was abandoned.

    A request with alternatives gets at most ALTERNATES_TIMEOUT_S; if it does
    not answer in that, the same route is asked again without them inside what
    is left of the budget, and the ride keeps the router's own route. The
    weekend router gets at most WEEKEND_TIMEOUT_S in all, so a hung one leaves
    the standard graph time to answer: a request for alternatives it does not
    answer is not asked again there, and the caller falls back to the
    standard graph (correctness review, round 2: the retry made it 30 s).
    """
    limit = deadline.per_call_s
    if variant in TWIN_VARIANTS:
        limit = min(limit, WEEKEND_TIMEOUT_S)
    if "alternates" not in request:
        return _call(variant, "route", request, Deadline(deadline.at, limit)), False
    alternates_limit = min(limit, ALTERNATES_TIMEOUT_S)
    try:
        return _call(variant, "route", request, Deadline(deadline.at, alternates_limit)), False
    except RouterUnavailable:
        if variant in TWIN_VARIANTS:
            raise
        logger.warning(
            "the %s router did not answer a request for alternatives in %s s; asking without",
            variant,
            alternates_limit,
        )
        plain = {key: value for key, value in request.items() if key != "alternates"}
        return _call(variant, "route", plain, Deadline(deadline.at, limit)), True


def plan_alternates(request: dict, trips: list, timed_out: bool, refitted: bool) -> list | None:
    """The router's routes the calm search may rank as this request's alternatives
    (OWNER-DECISIONS 435, `refine.Context.router_trips`): the plan's own where it asked
    for them (the hills slider's avoid half) and the request was not asked again with
    another costing since (`refitted`: the target fitting, `_fit_target` and
    `_past_target`); an empty list where that ask timed out, so none is asked again;
    None where the search must ask for itself."""
    if "alternates" not in request or refitted:
        return None
    return [] if timed_out else trips


def straight_span_m(points: list) -> float:
    """The sum of the straight-line distances between consecutive points."""
    return sum(haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False))


def long_calm_for(
    preset_name: str, points: list, stress: int, long_ride: bool, trails_off: bool = False
) -> bool:
    """Whether a plan is a long calm plan (OWNER-DECISIONS 256): the top of the
    stress slider on a ride type that plans past the calm search's working span
    leg by leg (`Preset.long_calm`, Trailmaxxing), for a start and an end and
    stops that are past `refine.REFINE_MAX_SPAN_M` of straight line and not a long
    ride (past the confirm span, which has its own rules). The Hills slider seeking
    climbs does not change it: at the top of the stress slider seeking hills keeps
    the stress order and the target (OWNER-DECISIONS 298(3)). Not with trails off
    ("Keep to roads, not trails"): the leg-by-leg search spends the long ride's
    budget looking for trails, which that ride has turned off (the trails-off
    correctness review, 7), so it plans as any other ride at the top does."""
    from . import refine

    return (
        not trails_off
        and presets.PRESETS[preset_name].long_calm
        and presets.maxcalm_for(stress)
        and len(points) >= 2
        and not long_ride
        and straight_span_m(points) > refine.REFINE_MAX_SPAN_M
    )


def _refine_limit(
    preset_name: str,
    points: list,
    long_ride: bool,
    seeking: bool,
    deadline: Deadline,
    long_calm: bool = False,
) -> str | None:
    """Why the search over the router's routes does not run on this plan, or
    None where it does. A Mass Ride has its own rules (OWNER-DECISIONS 133 to
    136, 171: its crossings are priced for the group, and its slider is locked),
    and the search runs only for a start and an end, inside what is left of the
    budget."""
    from . import refine

    if preset_name == "mass-ride":
        return "mass_ride"
    if len(points) < 2:
        return "points"
    if long_ride:
        return "long_ride"
    if seeking:
        return "seeking"
    if straight_span_m(points) > refine.REFINE_MAX_SPAN_M and not long_calm:
        return "span"
    if deadline.at - clock() < refine.REFINE_ROUND_MIN_S + refine.REFINE_TRACE_RESERVE_S:
        return "time"
    return None


def _events(refine_context, legs: list, raws: list, deadline: Deadline) -> list | None:
    """The route's junction events: the search's, where it read this very
    route, else read now. None where they could not be read in time."""
    from . import refine

    analysed = refine_context.analyses.get(tuple(leg.get("shape", "") for leg in legs))
    if analysed is not None:
        return analysed.events
    try:
        return refine.events_of_raws(raws, refine_context, deadline)
    except (DeadlineExceeded, RouterUnavailable):
        return None


# Whether the live segment table has the walk_bike column yet (a table built
# before NO-BIKE-PATHS has none; the route then carries no walk notes).
_walk_column_seen = False


def _has_walk_column(schema: str) -> bool:
    global _walk_column_seen
    if _walk_column_seen:
        return True
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'segment' AND column_name = 'walk_bike'",
            [schema],
        )
        _walk_column_seen = cursor.fetchone()[0] == 1
    return _walk_column_seen


def walk_spans(leg_runs: list, pieces: list[Piece]) -> list[tuple[float, float]]:
    """The stretches of the route over a short `bicycle=dismount` connector that
    routing keeps (OWNER-DECISIONS 291(5)): (from, to) in metres along the traced
    pieces, neighbouring pieces on such ways joined. A table without the column,
    or a failed query, has none: the route is answered without the note."""
    if not pieces:
        return []
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    try:
        if not _has_walk_column(schema):
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT DISTINCT osm_way_id FROM {schema}.segment "
                "WHERE osm_way_id = ANY(%s) AND walk_bike",
                [sorted({p.way_id for p in pieces})],
            )
            walking = {row[0] for row in cursor.fetchall()}
    except Exception:  # noqa: BLE001 - a route is answered without its walk notes
        logger.warning("the walk-your-bike ways could not be read", exc_info=True)
        return []
    if not walking:
        return []
    spans: list[tuple[float, float]] = []
    at = 0.0
    open_from: float | None = None
    for run in leg_runs:
        if not isinstance(run, tuple):
            at += float(run)
            if open_from is not None:
                spans.append((open_from, at - float(run)))
                open_from = None
            continue
        for index in range(run[0], run[1]):
            piece = pieces[index]
            if piece.way_id in walking:
                if open_from is None:
                    open_from = at
            elif open_from is not None:
                spans.append((open_from, at))
                open_from = None
            at += piece.metres
        if open_from is not None:
            spans.append((open_from, at))
            open_from = None
    return spans


# What a Mass Ride's stretch with no width is (`_flow_stretches`): marked Avoid (325: no
# carrying capacity, said "Avoid"), or on a leg that could not be traced (neither its
# width nor its junctions are known, so its intersections were not checked).
STRETCH_AVOID = "avoid"
STRETCH_UNTRACED = "untraced"
# Outside the District (OWNER-DECISIONS 427): Mass Ride figures are not supported there yet,
# so the stretch has no width and no riders a minute; border roads count as inside (420).
STRETCH_OUTSIDE_DC = "outside_dc"


def _outside_dc(piece) -> bool:
    """Whether a traced piece lies outside the District (its midpoint; a piece with no
    position is taken as inside)."""
    from .mass_tiles import inside_dc

    lon, lat = getattr(piece, "lon", None), getattr(piece, "lat", None)
    return lon is not None and lat is not None and not inside_dc(lon, lat)


def _flow_stretches(
    leg_runs: list, pieces: list[Piece], classes: list, capacity: bool = False
) -> list[tuple[float, float | None, str | None]]:
    """(metres, physical usable width, note) along the route in the order ridden, as the
    stress sections are cut (`stress_spans`): the width a Mass Ride's group has, None with
    `STRETCH_AVOID` on a stretch marked Avoid and with `STRETCH_UNTRACED` on a leg that
    could not be traced.

    With `capacity` (the live table has `segment.mass_usable_width_m`) the width is the
    segment's own, as the capacity map colours it (`PieceClass.width_m`: the ride's own
    direction, parked cars out, DC's Roadway Block first; OWNER-DECISIONS 404, 406), so the
    chart and the map always agree; a piece on no segment has none. Without the column (a
    table built before the rebuild bundle) it is `routemaker.flow.usable_width_m`'s
    estimate from the classifier's lanes."""
    out: list[tuple[float, float | None, str | None]] = []
    for run in leg_runs:
        if isinstance(run, tuple):
            for i in range(run[0], run[1]):
                klass = classes[i]
                avoid = flow.is_avoid(klass[0])
                outside = _outside_dc(pieces[i])
                if avoid or outside:
                    width = None
                elif capacity:
                    width = getattr(klass, "width_m", None)
                else:
                    width = flow.usable_width_m(
                        klass[0],
                        klass[1],
                        getattr(klass, "lanes", None),
                        getattr(klass, "oneway", None),
                    )
                note = STRETCH_AVOID if avoid else STRETCH_OUTSIDE_DC if outside else None
                out.append((pieces[i].metres, width, note))
        else:
            out.append((run, None, STRETCH_UNTRACED))
    return out


def _calm_pieces(leg_runs: list, pieces: list[Piece], classes: list) -> list[calm.Costed]:
    """The traced pieces as the rolling stress score prices them (`calm.Costed`), in the order
    ridden and cut as the stress sections are (`stress_spans`): each piece's length, tier,
    facility and edge attributes, so each road counts at its own routing cost. A leg that
    could not be traced is one unrated stretch."""
    out: list[calm.Costed] = []
    for run in leg_runs:
        if isinstance(run, tuple):
            for i in range(run[0], run[1]):
                tier, kind = classes[i][0], classes[i][1]
                out.append(
                    (
                        pieces[i].metres,
                        int(tier) if tier in STRESS_KEYS and tier != "unknown" else None,
                        kind if kind != "unknown" else None,
                        pieces[i].road,
                    )
                )
        else:
            out.append((run, None, None, None))
    return out


def _round_or_none(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


def _int_or_none(value: float | None) -> int | None:
    return None if value is None else round(value)


def _note_of(stretch: tuple) -> str | None:
    return stretch[2] if len(stretch) > 2 else None


def _stretch_ranges(stretches: list[tuple], note: str, end_m: float) -> list[dict]:
    """The runs of stretches with this note, as {from_m, to_m}, by the stretches' own
    summed metres (correctness re-review R1: never read off the samples, which step
    over a stretch shorter than their spacing and trim a range by up to a spacing at
    each end), clipped to the profile's end."""
    found: list[tuple[float, float]] = []
    at = 0.0
    start: float | None = None
    for stretch in stretches:
        begin, at = at, at + stretch[0]
        on = _note_of(stretch) == note
        if on and start is None:
            start = begin
        elif not on and start is not None:
            found.append((start, begin))
            start = None
    if start is not None:
        found.append((start, at))
    return [
        {"from_m": round(a), "to_m": round(min(b, end_m))} for a, b in found if a < end_m and b > a
    ]


def _height_between(
    samples: list[tuple[float, float | None]],
    grade_at: list[float | None],
    sample_m: list[float],
    x: float,
) -> tuple[float | None, float | None]:
    """The height and grade a riders sample at `x` is drawn with: a sample's own where
    one is there, else the line between its two neighbours (the chart draws that line
    anyway) with the nearer one's grade; None across a gap."""
    j = bisect.bisect_right(sample_m, x)
    if j > 0 and sample_m[j - 1] == x:
        return samples[j - 1][1], grade_at[j - 1]
    if j == 0 or j >= len(samples):
        return None, None
    (m0, h0), (m1, h1) = samples[j - 1], samples[j]
    if h0 is None or h1 is None or m1 <= m0:
        return None, None
    t = (x - m0) / (m1 - m0)
    return h0 + t * (h1 - h0), grade_at[j - 1] if t < 0.5 else grade_at[j]


def _flow_samples(
    samples: list[tuple[float, float | None]],
    grade_at: list[float | None],
    legs: list,
    stretches: list[tuple],
    interval_m: float,
) -> tuple[list[tuple[float, float | None]], list[float | None], list[int | None], list[bool]]:
    """The positions a Mass Ride's riders are read at (correctness re-review R1): the
    elevation samples; one every `interval_m` along a leg the router gave no heights for
    (a None height: the line stays broken, but the riders figure is drawn); and a pair at
    each place the width or the note changes, the end of one stretch and the start of the
    next at one distance, so a stretch shorter than the sample spacing (a one-block
    bottleneck, a crossing-length Avoid) is never stepped over and the riders line steps
    where the width does. The climbs are found on the elevation samples alone, before
    this.

    (samples, grades, the stretch each is on, and whether it is on the elevation
    grid: the typical figure is read from those only, so a boundary pair does not weigh
    in it twice)."""
    sample_m = [m for m, _h in samples]
    end_m = sample_m[-1]
    rows: list[tuple[float, int | None, float | None, float | None, bool]] = [
        (m, None, h, g, True) for (m, h), g in zip(samples, grade_at, strict=True)
    ]
    for leg in legs:
        if leg.heights:
            continue
        k = 1
        while k * interval_m < leg.length_m:
            rows.append((leg.start_m + k * interval_m, None, None, None, True))
            k += 1
    at = 0.0
    previous = None
    for i, stretch in enumerate(stretches):
        begin, at = at, at + stretch[0]
        key = (stretch[1], _note_of(stretch))
        if previous is not None and key != previous and 0.0 < begin < end_m:
            height, grade = _height_between(samples, grade_at, sample_m, begin)
            rows.append((begin, i - 1, height, grade, False))
            rows.append((begin, i, height, grade, False))
        previous = key
    found = flow.stretch_index([row[0] for row in rows], stretches)
    rows = [
        (m, index if index is not None else found[k], h, g, regular)
        for k, (m, index, h, g, regular) in enumerate(rows)
    ]
    rows.sort(key=lambda row: (row[0], -1 if row[1] is None else row[1]))
    return (
        [(m, h) for m, _i, h, _g, _r in rows],
        [g for _m, _i, _h, g, _r in rows],
        [i for _m, i, _h, _g, _r in rows],
        [r for _m, _i, _h, _g, r in rows],
    )


def _crossing_out(major) -> dict:
    return {
        "m": round(major.m),
        "street": describe.street_name_of(major),
        "severity": major.severity,
        "control": major.control.value,
        "lanes": major.lanes,
        "crossed_tier": major.crossed_tier,
        "kind": getattr(major, "kind", intersections.MAJOR_FLAGGED),
        "corkers_needed": major.corkers_needed,
    }


def route_profile(
    legs: list,
    spans: list[dict],
    flow_stretches: list[tuple] | Callable[[], list[tuple]] | None = None,
    majors: list | None = None,
    majors_complete: bool = True,
    calm_pricing: calm.Pricing | Callable[[], calm.Pricing] | None = None,
    events: list | None = None,
    calm_pieces: list[calm.Costed] | None = None,
) -> dict | None:
    """The route's elevation profile for the chart (OWNER-DECISIONS 322, 323), from the
    router's per-leg samples (`ELEVATION_INTERVAL_M`): where each sample is along the
    route, its height, the grade there (`routemaker.profile`), and the sustained climbs.

    On a Mass Ride (`flow_stretches`: (metres, width, note) along the route,
    `_flow_stretches`) it also has the grade-adjusted riders a minute at each sample
    (OWNER-DECISIONS 328, `routemaker.flow`), the narrowest point, the capacity each climb
    costs, where the route is marked Avoid (325) or was not traced, and the major junctions
    (`majors`, OWNER-DECISIONS 333, 396). `majors` None is "not checked" (the junctions
    were not read: over budget, or the reads failed), sent as `crossings: null`, never as
    an empty list, which says there are none. `majors_complete` False is a list of the
    flagged junctions only (finding the busy-road ones failed: `junctions.with_majors`),
    sent with `crossings_complete: false` so the chart says it may be incomplete
    (correctness re-review R3). `flow_stretches` may be given as a function that makes
    them, so a failure there costs only the chart (operations re-review B).

    The Avoid and untraced ranges are the stretches' own (`_stretch_ranges`), and on a
    Mass Ride the riders are read at the stretch boundaries and along legs without
    heights too (`_flow_samples`).

    Off a Mass Ride (`calm_pricing` given) it also has the rolling stress score
    (`routemaker.calm`, OWNER-DECISIONS 460.12, 461d, 461e): calm miles per mile over the
    mile around each sample, from the sections (`spans`) and the junction `events` (None:
    not read, so not counted, and the answer says so); the highest window's sample is kept
    when a long route is thinned. `calm_pricing` may be a function that makes it. Each road
    is priced by its own routing cost from `calm_pieces`, the traced pieces with their
    edges' attributes (`calm.Costed`); without them each section takes its tier's figure,
    an estimate, and the answer says so. A failure there costs only the score, sent as
    `calm: null`.

    The climbs (`climbs.runs`) are found once, and every figure is worked out on every
    sample; a long route's arrays are then thinned to about `profile.MAX_SAMPLES`
    (`profile.thin`). None where no leg had any elevation: the route is answered all the
    same."""
    try:
        if callable(flow_stretches):
            flow_stretches = flow_stretches()
        chart_legs = []
        offset = 0.0
        for leg in legs:
            length = float((leg.get("summary") or {}).get("length", 0.0)) * 1000.0
            chart_legs.append(profile_rules.Leg(offset, length, leg.get("elevation") or []))
            offset += length
        samples = profile_rules.sample_positions(chart_legs, ELEVATION_INTERVAL_M)
        if not any(height is not None for _m, height in samples):
            return None
        sample_m = [m for m, _h in samples]
        grade_at = profile_rules.grades(samples)
        runs = climbs.runs(samples)
        found = profile_rules.climb_list(samples, grade_at, spans, runs)
        riders = level = None
        regular: list[bool] = [True] * len(samples)
        if flow_stretches is not None:
            samples, grade_at, where, regular = _flow_samples(
                samples, grade_at, chart_legs, flow_stretches, ELEVATION_INTERVAL_M
            )
            sample_m = [m for m, _h in samples]
            pairs = [(stretch[0], stretch[1]) for stretch in flow_stretches]
            riders, level = flow.per_sample(samples, grade_at, pairs, runs, where)
        rows = []
        for climb in found:
            row = {
                "from_m": round(climb.from_m),
                "to_m": round(climb.to_m),
                "gain_m": round(climb.gain_m, 1),
                "avg_grade_pct": round(climb.avg_grade * 100, 1),
                "max_grade_pct": round(climb.max_grade * 100, 1),
                "tier": climb.tier,
                "capacity_drop_pct": None,
                "min_riders_per_min": None,
            }
            if riders is not None and level is not None:
                on = [
                    (riders[i], level[i])
                    for i in profile_rules.inside(sample_m, climb.from_m, climb.to_m)
                    if riders[i] is not None and level[i]
                ]
                if on:
                    row["capacity_drop_pct"] = round(max(100 * (1 - r / v) for r, v in on))
                    row["min_riders_per_min"] = round(min(r for r, _v in on))
            rows.append(row)
        heights = [h for _m, h in samples]
        keep = profile_rules.thin(heights, grade_at, riders)
        pricing = None
        if calm_pricing is not None:
            try:
                pricing = calm_pricing() if callable(calm_pricing) else calm_pricing
                peak = calm.peak_index(spans, events, pricing, sample_m, pieces=calm_pieces)
                if peak is not None and peak not in keep:
                    keep = sorted([*keep, peak])
            except Exception:  # noqa: BLE001 - the chart is drawn without the score
                logger.warning("the rolling stress score could not be built", exc_info=True)
                pricing = None
        body: dict = {
            "interval_m": ELEVATION_INTERVAL_M,
            "m": [round(sample_m[i]) for i in keep],
            "elevation_m": [_round_or_none(heights[i]) for i in keep],
            "grade_pct": [
                _round_or_none(None if grade_at[i] is None else grade_at[i] * 100) for i in keep
            ],
            "climbs": rows,
            "riders_per_min": None,
            "flow": None,
            "crossings": None,
            "avoid": None,
            "unchecked": None,
            "outside_dc": None,
            "crossings_complete": None,
            "calm": None,
        }
        if pricing is not None:
            try:
                body["calm"] = calm.score(
                    spans, events, pricing, [sample_m[i] for i in keep], pieces=calm_pieces
                )
            except Exception:  # noqa: BLE001 - the chart is drawn without the score
                logger.warning("the rolling stress score could not be built", exc_info=True)
        if riders is not None:
            body["riders_per_min"] = [_int_or_none(riders[i]) for i in keep]
            known = [(round(r), m) for m, r in zip(sample_m, riders, strict=True) if r is not None]
            narrow = min(known, default=None)
            typical = sorted(
                round(r) for r, on in zip(riders, regular, strict=True) if r is not None and on
            )
            body["flow"] = {
                "narrowest_riders_per_min": narrow[0] if narrow else None,
                "narrowest_m": round(narrow[1]) if narrow else None,
                "typical_riders_per_min": typical[len(typical) // 2] if typical else None,
            }
            end_m = sample_m[-1]
            body["avoid"] = _stretch_ranges(flow_stretches, STRETCH_AVOID, end_m)
            body["unchecked"] = _stretch_ranges(flow_stretches, STRETCH_UNTRACED, end_m)
            # 427: the parts of a Mass Ride outside DC, said in words, with no figure.
            body["outside_dc"] = _stretch_ranges(flow_stretches, STRETCH_OUTSIDE_DC, end_m)
            body["crossings"] = None if majors is None else [_crossing_out(x) for x in majors]
            body["crossings_complete"] = None if majors is None else bool(majors_complete)
        return body
    except Exception:  # noqa: BLE001 - a route is answered without its profile
        logger.warning("the route profile could not be built", exc_info=True)
        return None


def describe_route(
    leg_runs: list,
    pieces: list[Piece],
    classes: list,
    events: list | None,
    summary: dict,
    walks: list[tuple[float, float]] | None = None,
) -> tuple[list[dict], list[dict]] | None:
    """The route as words, in full and as an overview (`routemaker.describe`,
    OWNER-DECISIONS 220 and 226): built
    from the pieces and junction events the plan already has, with no router
    call and no query. None where it could not be built: the route is answered
    all the same."""
    try:
        legs: list = []
        for run in leg_runs:
            if isinstance(run, tuple):
                legs.append(
                    [
                        describe.Atom(
                            pieces[i].metres,
                            classes[i][0],
                            classes[i][1],
                            pieces[i].names,
                            pieces[i].use,
                            pieces[i].heading_in,
                            pieces[i].heading_out,
                            getattr(classes[i], "unpaved", None),
                        )
                        for i in range(run[0], run[1])
                    ]
                )
            else:
                legs.append(run)
        length = float(summary.get("length", 0.0)) * 1000.0
        return describe.describe_both(legs, events, length or None, walks)
    except Exception:  # noqa: BLE001 - a route is answered without its description
        logger.warning("the route description could not be built", exc_info=True)
        return None


def _intersection_rows(events: list) -> list[dict]:
    """The flagged junctions of a route, as the contract has them (OWNER-DECISIONS
    172): where, orange or red, why, and the crossed road's tier. A
    neighbourhood stop sign is never flagged."""
    return [
        {
            "m": round(event.m),
            "lon": round(event.lon, 6),
            "lat": round(event.lat, 6),
            "severity": event.severity,
            "reason": event.reason,
            "crossed_tier": event.crossed_tier,
            "movement": event.movement.value,
            "control": event.control.value,
            "kind": event.kind,
            "cost_ft": round(event.cost_ft),
            "group": event.group,
        }
        for event in events
        if event.flagged
    ]


def _intersection_groups(events: list) -> list[dict]:
    """A Mass Ride's groups of signalized crossings (OWNER-DECISIONS 233 and 234),
    for the junction list: where each runs, how many, the first streets, how many
    are LTS 4, its worst severity, and its sentence. `members` are positions in
    the `intersections` list, which holds every crossing as before."""
    flagged = [event for event in events if event.flagged]
    rows = []
    for group in intersections.crossing_groups(flagged):
        streets = describe.group_streets(group)
        rows.append(
            {
                "group": group.number,
                "from_m": round(group.from_m),
                "to_m": round(group.to_m),
                "count": group.count,
                "lts4": group.lts4,
                "streets": streets[: describe.MAX_NAMED_STREETS],
                "more": max(len(streets) - describe.MAX_NAMED_STREETS, 0),
                "severity": group.severity,
                "members": [i for i, event in enumerate(flagged) if event.group == group.number],
                "text": describe.group_words(group, group.from_m, group.to_m),
            }
        )
    return rows


# The least time the direct route's probe is started with; and the busy-road
# comparison, which traces it as well, wants this much more.
DETOUR_PROBE_MIN_S = 4
DETOUR_AVOIDED_MIN_S = 7


def _detour(
    route_m: float,
    straight_m: float,
    request: dict,
    variant: str,
    preset_name: str,
    dials: tuple,
    busy_m: float,
    when: str,
    deadline: Deadline,
    traces: dict,
) -> dict | None:
    """How much longer the route is than the most direct legal one, for the
    answer's warning (OWNER-DECISIONS 164; `routemaker.detour`).

    Nothing to say, and no second route asked for, while the route is within
    the allowance of the straight line, which the direct route can only exceed.
    Otherwise the router is asked for the most direct route (the traffic
    tolerant end, the hills detent); where it cannot be had in time, or on a
    Mass Ride, which is the direct route by design, the straight line is the
    reference and only a route twice as long says so."""
    if straight_m <= 0 or route_m <= max(
        straight_m * detour_rules.SILENT_RATIO, straight_m + detour_rules.SILENT_EXTRA_M
    ):
        return None
    stress_dial, assist, avoid_gravel = dials
    # At or below Default the rider asked for no calm detour, and the route
    # cannot be more than the straight line's ratio longer than the direct one
    # (1.5 times at most, a note): the second route is asked for from just above
    # Default, or where the route is twice the straight line at any position.
    asked_for_calm = stress_dial > presets.STRESS_DEFAULT_AT or route_m >= (
        detour_rules.STRONG_RATIO * straight_m
    )
    if (
        preset_name != "mass-ride"
        and asked_for_calm
        and deadline.at - clock() >= DETOUR_PROBE_MIN_S
    ):
        direct_costing = presets.costing(
            preset_name, 0, 0, assist=assist, avoid_gravel=avoid_gravel
        )
        direct_request = {
            key: value
            for key, value in request.items()
            if key not in ("alternates", "exclude_locations")
        } | {"costing_options": direct_costing}
        # Asked once for a plan and its candidate routes (OWNER-DECISIONS 265).
        direct_key = ("direct-route", json.dumps(direct_request, sort_keys=True))
        if direct_key in traces:
            direct, direct_m = traces[direct_key]
        else:
            try:
                answer = _call(
                    variant,
                    "route",
                    direct_request,
                    Deadline(deadline.at, min(deadline.per_call_s, ALTERNATES_TIMEOUT_S)),
                )
                direct = answer.get("trip") or {}
                direct_m = float((direct.get("summary") or {}).get("length", 0.0)) * 1000.0
            except (DeadlineExceeded, RouterUnavailable, RouterRefused):
                direct, direct_m = {}, 0.0
            traces[direct_key] = (direct, direct_m)
        if direct_m > 0:
            avoided = None
            level = detour_rules.level(route_m, direct_m)
            if level is not None and deadline.at - clock() >= DETOUR_AVOIDED_MIN_S:
                try:
                    pieces: list[Piece] = []
                    for leg in direct.get("legs") or []:
                        trace = _trace(
                            variant, direct_costing, leg.get("shape", ""), deadline, traces
                        )
                        if trace is None:
                            raise RouterUnavailable("no trace")
                        pieces.extend(pieces_of_trace(trace))
                    direct_stress, _facility = breakdown(pieces, when)
                    avoided = direct_stress["3"] + direct_stress["4"] + direct_stress["5"] - busy_m
                except (DeadlineExceeded, RouterUnavailable):
                    avoided = None
            return detour_rules.describe(route_m, direct_m, detour_rules.DIRECT_ROUTE, avoided)
    return detour_rules.describe(route_m, straight_m, detour_rules.STRAIGHT_LINE)


def _joined_runs(runs: list, pieces: list) -> tuple[int, int] | float:
    """The runs of the legs a plan's leg was searched in, as one: a run of traced
    pieces where all of them are (their pieces are in order, end to start), else
    the plan leg's length in metres, untraced."""
    if all(isinstance(run, tuple) for run in runs):
        return (runs[0][0], runs[-1][1])
    return float(
        sum(
            sum(piece.metres for piece in pieces[run[0] : run[1]])
            if isinstance(run, tuple)
            else run
            for run in runs
        )
    )


# The least time left (seconds) for reading and describing one more candidate route
# (OWNER-DECISIONS 265): its junctions, and its description built from them.
ALTERNATE_MIN_S = 6


# The traffic positions a target distance that the router's own route is past is
# asked at, calmest first, until a route fits (`_fit_target`): Default's, a balanced
# one, and the most direct.
FIT_STRESS_LADDER = (presets.STRESS_DEFAULT_AT, 40, 0)
# The least time left for another rung (a whole-trip /route and no more).
FIT_MIN_S = 12


# After the ladder finds the calmest rung that fits, the stretch between it and the
# rung before (the one that did not) is bisected this many times for a calmer route
# that still fits: a target between two rungs' routes is common (Union Station to
# Baltimore Penn at 50 mi: the calm route is 58 mi, the direct one 40).
FIT_BISECT_STEPS = 3


def _trip_length_m(trip: dict) -> float:
    return float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0


def _fit_target(
    trip: dict,
    request: dict,
    costing: dict,
    trace_costing: dict,
    target_m: float | None,
    preset_name: str,
    hills_dial: int,
    assist: bool,
    avoid_gravel: bool,
    variant: str,
    deadline: Deadline,
) -> tuple[tuple | None, list[tuple]]:
    """The first route for a rider's target distance (OWNER-DECISIONS 256, 271): the
    router's own route if it is within it, else the calmest route the router gives
    that is, from its own costing at the traffic positions of FIT_STRESS_LADDER and
    then between the last two (FIT_BISECT_STEPS). Each route is a tuple of the trip,
    the request and costings to search with, and the traffic position it was found at
    (None: the ride's own). Returns the route that fits (None where none does) and
    every route found past the target, the router's own first (`_past_target`
    chooses among them: the target is soft)."""
    length = _trip_length_m(trip)
    own = (trip, request, costing, trace_costing, None)
    if target_m is None or length <= target_m:
        return own, []
    past = [own]

    def ask(position: int):
        """The route at a traffic position: (length m, the tuple), or None where there
        is none, and False where there is no time or the router refused."""
        options = presets.costing(
            preset_name, position, hills_dial, assist=assist, avoid_gravel=avoid_gravel
        )
        asked = {k: v for k, v in request.items() if k != "alternates"} | {
            "costing_options": options
        }
        try:
            answer = _call(
                variant, "route", asked, Deadline(deadline.at, min(deadline.per_call_s, 30))
            )
        except (DeadlineExceeded, RouterUnavailable, RouterRefused):
            return False
        found = answer.get("trip") or {}
        if not found.get("legs"):
            return None
        return _trip_length_m(found), (found, asked, options, options, position)

    over = presets.STRESS_TODAYS_TOP  # the calmest position that is not the router's own
    for rung in FIT_STRESS_LADDER:
        if deadline.at - clock() < FIT_MIN_S:
            return None, past
        got = ask(rung)
        if got is False:
            return None, past
        if got is None:
            continue
        found_m, answer = got
        if found_m > target_m:
            over = rung
            past.append(answer)
            continue
        # This rung fits: look between it and the one before for a calmer one that does.
        best, fits = answer, rung
        for _step in range(FIT_BISECT_STEPS):
            middle = (over + fits) // 2
            if middle in (over, fits) or deadline.at - clock() < FIT_MIN_S:
                break
            probe = ask(middle)
            if probe is False:
                break
            if probe is None:
                continue
            probe_m, probe_answer = probe
            if probe_m <= target_m:
                best, fits = probe_answer, middle
            else:
                over = middle
                past.append(probe_answer)
        return best, past
    return None, past


def _past_target(fit: tuple | None, past: list[tuple], ceiling_m: float, ctx) -> tuple:
    """Which first route a plan keeps where the router's own route is past the rider's
    target distance (OWNER-DECISIONS 267, 268, 271), from `_fit_target`'s:
    - where one fits, the route past the target (within the ceiling) that is calmer
      and worth its miles over it (`refine.better`, whose diminishing-returns bar is
      the stricter one past the target), else the one that fits;
    - where none fits (267, "Least-stress route, flagged"), the least stressful within
      the ceiling, in the order of 258-262 (`refine.calmer`, then the shorter), else,
      none being within the ceiling, the least stressful of all those found, in the
      same order (OWNER-DECISIONS 298(2), "Calmest found, flagged (Recommended)": it
      amends the shortest, as first built), flagged with how far over the target it is.
    A route that cannot be read in time is not chosen; where none can be, the shortest.
    Each is read inside the late deadline (`refine.late_deadline`, combined correctness
    review S3), keeping the answer's reserve."""
    from . import refine

    within = sorted(
        (o for o in past if _trip_length_m(o[0]) <= ceiling_m), key=lambda o: _trip_length_m(o[0])
    )
    late = refine.late_deadline(ctx)

    def read(option: tuple):
        try:
            got = refine.analyse(option[0], dataclasses.replace(ctx, costing=option[3]), late)
        except (DeadlineExceeded, RouterUnavailable):
            return None
        return got if got is not None and got.events is not None else None

    if fit is not None:
        current = read(fit) if within else None
        if current is None:
            return fit
        best = fit
        for option in within:
            got = read(option)
            if got is not None and refine.better(got, current, ctx):
                best, current = option, got
        return best
    if not within:
        within = sorted(past, key=lambda o: _trip_length_m(o[0]))
    best, current = within[0], None
    for option in within:
        got = read(option)
        if got is None:
            continue
        if current is None or refine.calmer(got, current, ctx):
            best, current = option, got
    return best


def target_fields(final_m: float, target_m: float | None, ceiling_m: float | None) -> dict:
    """What the answer says of the distance at the top of the slider (OWNER-DECISIONS
    271): the rider's target and whether they set one, the ceiling, whether the route
    is within the target, and how far over it it is (0 within it; None without one)."""
    over = None if target_m is None else round(max(final_m - target_m, 0.0), 1)
    return {
        "target_distance_m": round(target_m, 1) if target_m is not None else None,
        "target_distance_set": target_m is not None,
        "ceiling_m": round(ceiling_m, 1) if ceiling_m is not None else None,
        "fits": None if target_m is None else final_m <= target_m,
        "over_target_m": over,
    }


ZOO_NOTE = (
    "This point is inside the National Zoo, where bicycles are not ridden beyond the "
    "bike racks by the Harvard Street entrance. The route goes to the racks."
)


def move_zoo_points(points: list[list[float]]) -> tuple[list[list[float]], list[dict]]:
    """A trip point inside the Zoo is moved to its bike racks: a route to the
    Zoo ends at the racks (OWNER-DECISIONS 291(4)). Returns the points and, for
    each one moved, what the answer reports (`moved_points`)."""
    out: list[list[float]] = []
    moved: list[dict] = []
    for index, (lon, lat) in enumerate(points):
        target = zoo.redirect(lon, lat)
        if target is None:
            out.append([lon, lat])
            continue
        out.append([target[0], target[1]])
        moved.append(
            {
                "index": index,
                "asked": [round(lon, 6), round(lat, 6)],
                "routed": [round(target[0], 6), round(target[1], 6)],
                "reason": "zoo_racks",
                "note": ZOO_NOTE,
            }
        )
    return out, moved


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
    points, moved_points = move_zoo_points(points)
    preset = presets.PRESETS[preset_name]
    stress_dial = (
        presets.stress_start(preset_name, dials.carrying) if dials.stress is None else dials.stress
    )
    hills_dial = preset.hills if dials.hills is None else dials.hills
    seeking = hills_dial > 0 and preset.hills_seek
    maxcalm = presets.maxcalm_for(stress_dial)
    # Seeking hills at the top of the stress slider keeps the stress order and the
    # target; only the effort tiebreak (`refine.level3`) inverts, to prefer climbing
    # (OWNER-DECISIONS 298(3), "Keep stress order + target (Recommended)"). Below the
    # top the slider is the climb search among the router's alternatives, as before.
    calm_seek = seeking and maxcalm
    climb_seek = seeking and not maxcalm
    # A loop is planned through its start again (OWNER-DECISIONS 266).
    loop = loop_wanted(points, dials.loop, preset_name)
    points = loop_points(points, loop)
    # A long calm plan (Trailmaxxing at the top of the slider past the calm
    # search's working span, planned leg by leg) has the long ride's time
    # limits: 50 s in all, under gunicorn's 60 s timeout, as the owner chose
    # for a long ride (2026-09-26). It is the same plan the ordinary budget
    # would cut short after its first legs, and no more than the router calls
    # a long ride makes (docs/OPERATIONS.md, "Long calm plans").
    long_calm = not loop and long_calm_for(
        preset_name, points, stress_dial, long_ride, trails_off=bool(dials.trails_off)
    )
    if long_ride or long_calm:
        budget_s, per_call_s = LONG_PLAN_BUDGET_S, LONG_ROUTER_TIMEOUT_S
    else:
        budget_s, per_call_s = PLAN_BUDGET_S, ROUTER_TIMEOUT_S
    deadline = Deadline(started + budget_s - ANSWER_RESERVE_S, per_call_s)
    exposure = presets.exposure_for(preset_name, dials.carrying)
    # The rider's target distance counts at the top of the slider only.
    target_m = float(dials.target_distance_m) if dials.target_distance_m and maxcalm else None
    when = dials.when or default_when()
    assist = bool(dials.assist) and preset.assist_speed_kmh is not None
    trails_off = bool(dials.trails_off)
    variant = presets.variant_for_ride(preset_name, when, assist, trails_off)
    # Bike lanes are "none" in the breakdown on a ride that takes the roadway (Mass
    # Ride, whose own graph is no-trail), not on every trails-off ride.
    lanes_as_roadway = preset.variant == Variant.NO_TRAIL.value
    avoid_gravel = bool(dials.avoid_gravel)
    costing = presets.costing(
        preset_name, stress_dial, hills_dial, assist=assist, avoid_gravel=avoid_gravel
    )
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
    # Below it the slider also weighs sustained climbs and brake-riding
    # descents (routemaker.climbs; the owner, 2026-09-28) among the same
    # alternatives, by `-hills/100`.
    avoiding = hills_dial < 0
    seek_limited = "calm_first" if calm_seek else None
    if climb_seek or avoiding:
        span_limit = SEEK_MAX_SPAN_M if climb_seek else AVOID_MAX_SPAN_M
        if len(points) != 2:
            seek_limited = "two_points"
        elif long_ride or haversine(Point(*points[0]), Point(*points[1])) > span_limit:
            seek_limited = "long_ride"
        else:
            request["alternates"] = SEEK_ALTERNATES
    if variant in TWIN_VARIANTS and (_twin_down(variant) or not _is_promoted(variant)):
        logger.info("the %s graph is not being served; planning on the standard graph", variant)
        variant = Variant.STANDARD.value
    try:
        try:
            answer, timed_out = _route(variant, request, deadline)
            if variant in TWIN_VARIANTS:
                _mark_twin(variant, True)
        except RouterUnavailable:
            # The weekend graph is a fourth router, and a deployment that has
            # not built it yet - or one whose weekend router is down or hung -
            # still answers a weekend ride, on the standard graph it is the
            # twin of. The answer names the graph it came from, and the failure
            # is remembered for WEEKEND_FAILURE_TTL_S.
            if variant not in TWIN_VARIANTS:
                raise
            _mark_twin(variant, False)
            logger.warning("the %s router did not answer; planning on the standard graph", variant)
            variant = Variant.STANDARD.value
            answer, timed_out = _route(variant, request, deadline)
        except RouterRefused as refusal:
            # A weekend router with no tiles - started on an empty directory
            # before the first weekend promotion, or after a rollback withdrew
            # it - stays up and answers every ride 170/171, "no suitable
            # edges" (OPS review, 2026-09-28). That is asked of the standard
            # graph too, and only if the standard graph answers is the weekend
            # one taken to be missing its tiles and remembered as down; a
            # point the standard graph cannot place either is a real refusal
            # and is reported as one.
            if variant not in TWIN_VARIANTS or refusal.code not in NO_EDGE_CODES:
                raise
            answer, timed_out = _route(Variant.STANDARD.value, request, deadline)
            _mark_twin(variant, False)
            logger.warning(
                "the %s router placed no edge the standard graph could (code %s); "
                "planning on the standard graph",
                variant,
                refusal.code,
            )
            variant = Variant.STANDARD.value
        if timed_out and not calm_seek:
            seek_limited = "timed_out"
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

    routed_at = clock()
    trips = [answer.get("trip") or {}] + [
        (alternate or {}).get("trip") or {} for alternate in answer.get("alternates") or []
    ]
    avoid_weight = -hills_dial / 100 if avoiding else 0.0
    # This plan's traces, so a route the guards traced is not traced again.
    traces: dict = {}
    if climb_seek:
        chosen = choose_climb(trips, presets.seek_distance_ratio(hills_dial))
    elif avoiding:
        chosen = calmer_or_own(
            trips,
            choose_gentlest(trips, avoid_weight, preset.brake_grade),
            variant,
            costing,
            when,
            deadline,
            traces,
            exposure,
        )
    else:
        chosen = 0
    trip = trips[chosen]
    kept_middle = False
    trace_costing = costing
    if avoiding:
        middle_costing = presets.costing(
            preset_name, stress_dial, 0, assist=assist, avoid_gravel=avoid_gravel
        )
        trip, kept_middle = no_busier_than_middle(
            trip, request, variant, costing, middle_costing, when, deadline, traces, exposure
        )
        if kept_middle:
            # Traced with the costing it was routed with, which the check
            # already did: the trace is reused, not asked for again.
            trace_costing = middle_costing
    # The calm detour and crossing avoidance (core.refine): the router's own
    # routes, searched for a better score. Only where it can run inside the
    # budget; `refined` says what it did, or why it did not.
    from . import dedodge, refine, trailseek

    refine_limited = _refine_limit(preset_name, points, long_ride, climb_seek, deadline, long_calm)
    ceiling = None
    fitted_at = None
    fit, past = None, []
    if maxcalm and refine_limited is None:
        fit, past = _fit_target(
            trip, request, costing, trace_costing, target_m, preset_name, hills_dial, assist,
            avoid_gravel, variant, deadline,
        )  # fmt: skip
        if fit is not None:
            trip, request, costing, trace_costing, fitted_at = fit
        ceiling = (
            presets.target_ceiling_m(target_m)
            if target_m
            else presets.default_ceiling_m(_trip_length_m(trip))
        )
    refine_context = refine.Context(
        variant=variant,
        request=request,
        costing=trace_costing,
        when=when,
        deadline=deadline,
        traces=traces,
        points=points,
        roadway_only=variant == Variant.NO_TRAIL.value,
        lanes_as_roadway=lanes_as_roadway,
        with_facility=_has_facility_columns(validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)),
        group=preset_name == "mass-ride",
        rate=presets.calm_rate_for(stress_dial),
        weight=refine.intersection_weight(stress_dial),
        climb_weight=avoid_weight * refine.CLIMB_EQUIVALENT_M,
        hills_weight=avoid_weight,
        hills_seek_weight=hills_dial / 100 if calm_seek else 0.0,
        mass_kg=presets.system_weight_for(preset_name, dials.carrying, dials.system_weight_kg),
        quiet_cost=refine.quiet_cost_per_m(trace_costing),
        wide=refine.wide_search_for(presets.calm_rate_for(stress_dial)),
        seek=trailseek.seek_for(presets.calm_rate_for(stress_dial)),
        schema=validate_schema_name(settings.SEGMENT_SCHEMA_LIVE),
        avoid_gravel=avoid_gravel,
        exposure=exposure,
        maxcalm=maxcalm,
        ceiling_m=ceiling,
        target_m=target_m,
        # Up to ALT_MAX routes to choose from at the top of the slider (OWNER-DECISIONS 265).
        alternates=refine.ALT_MAX if maxcalm and preset_name != "mass-ride" else 0,
        # The router's own alternatives ranked with the calm search's (OWNER-DECISIONS 435):
        # the plan's own, where it asked for them with the request the search starts
        # from (none again where that ask timed out), else asked for by the search.
        rank_alternates=presets.calm_rate_for(stress_dial) > 0,
        router_trips=plan_alternates(request, trips, timed_out, fit is not None or bool(past)),
        options=[] if maxcalm and preset_name != "mass-ride" and not long_calm else None,
    )
    if past:
        # The router's own route is past the target: the calmer route past it where
        # that is worth its miles, or the least stressful where none fits (267).
        trip, request, costing, trace_costing, fitted_at = _past_target(
            fit, past, ceiling, refine_context
        )
        refine_context.request = request
        refine_context.costing = trace_costing
        refine_context.quiet_cost = refine.quiet_cost_per_m(trace_costing)
    loop_info = None
    if loop:
        # The way back by a different way, before the search, which then keeps it so.
        trip, loop_info = refine.make_loop(trip, refine_context)
        if loop_info["fallback"] is None and loop_info["overlap_pct"] is not None:
            refine_context.loop_overlap = loop_info["overlap_pct"] / 100.0
    refined = None
    if refine_limited is None:
        if past and fit is None:
            # No route fits the target (OWNER-DECISIONS 267): the least stressful one
            # found is the answer, flagged with how far over it is, and nothing is
            # searched.
            refined = {
                "rate": refine_context.rate,
                "rounds": 0,
                "excluded": 0,
                "limited": "target_distance",
                "no_fit": True,
            }
        elif long_calm:
            trip, refined = refine.refine_long(trip, refine_context)
        else:
            trip, refined = refine.refine(trip, refine_context)
    elif refine_context.rate > 0:
        # A calm search was asked for and could not run: say so.
        refined = {
            "rate": refine_context.rate,
            "rounds": 0,
            "excluded": 0,
            "limited": refine_limited,
        }
    # No weaving through side streets beside a busier road unless it buys a
    # meaningful length of calm (OWNER-DECISIONS 272, 273): the main road's stretch
    # replaces such a dodge. A loop's way back is kept as it was made, not to share
    # more of the way out (266). The answer's route alone: the routes to choose from
    # are the search's near-ties, picked again against the answer as it now is
    # (`dedodge.settle`), so the pass's bounds are the plan's.
    dodges = None
    if not loop:
        trip, dodges = dedodge.apply(trip, refine_context)
        dedodge.settle(trip, refine_context, refined, dodges)
    if refined is not None and maxcalm:
        refined.update(target_fields(_trip_length_m(trip), target_m, ceiling))
        if fitted_at is not None:
            refined["fitted_at"] = fitted_at
        # `no_fit`: no route within the target was found (OWNER-DECISIONS 267, 298(2));
        # the front end says so on it alone (combined correctness review, S2). Null
        # without a target.
        if target_m is None:
            refined["no_fit"] = None
        elif refined.get("no_fit") and dodges and dodges["removed"] and refined["fits"]:
            # No route fitted the target until a dodge was taken out of the least
            # stressful: only then is the flag cleared (mutation review, X16).
            refined["no_fit"] = False
            refined["limited"] = None
        else:
            refined["no_fit"] = bool(refined.get("no_fit"))

    # A long calm plan searched in legs of its own answers in the plan's legs: the
    # grouping of its search legs into the plan's, the answer's and its candidates'
    # alike (combined correctness review, S1: a candidate kept the search's legs, and
    # its description a "Stop 1" the rider never placed).
    long_info = (refined or {}).get("long") or {}
    plan_groups = long_info.get("stops") if long_info.get("answered") == "legs" else None

    def _answer(
        trip: dict, refined: dict | None, alternate: bool = False, dodges_of: dict | None = None
    ) -> dict:
        """The contract's body for one route (the plan's own, or one of its
        candidates, OWNER-DECISIONS 265)."""
        legs = trip.get("legs") or []
        if not legs:
            raise NoRoute("the router returned no legs")

        coordinates: list[tuple[float, float]] = []
        elevations: list[float | None] = []
        stress = dict.fromkeys(STRESS_KEYS, 0.0)
        facility = dict.fromkeys(FACILITY_KEYS, 0.0)
        pieces: list[Piece] = []
        # Where the route passes a node, for the intersection model, and how far
        # along the traced length it has got.
        raw_junctions: list = []
        traced_m = 0.0
        # The route in the order ridden, for its coloured sections: each leg is
        # either a run of traced pieces (start, end) or an untraced length.
        leg_runs: list[tuple[int, int] | float] = []
        # The index in `coordinates` of each leg's last vertex: the joints are
        # shared, so leg k runs from leg_ends[k - 1] (or 0) to leg_ends[k]. The
        # front end reads which leg a point on the line belongs to from these.
        leg_ends: list[int] = []
        # Where each leg begins along the traced length: the stops (and the start,
        # which no crossing lies before), which a Mass Ride's crossing group never
        # spans (OWNER-DECISIONS 247).
        stops_m: list[float] = []
        for leg in legs:
            stops_m.append(traced_m)
            shape = decode_polyline6(leg.get("shape", ""))
            coordinates.extend(shape[1:] if coordinates else shape)
            leg_ends.append(len(coordinates) - 1)
            elevations.extend(leg.get("elevation") or [])
            try:
                trace = _trace(variant, trace_costing, leg.get("shape", ""), deadline, traces)
            except DeadlineExceeded:
                # The route is found, so it is answered; a leg left untraced is
                # unknown, and once the budget is gone `_call` starts no more.
                logger.info("the budget ran out tracing a leg on %s", variant)
                trace = None
            if trace is None:
                untraced = float(leg.get("summary", {}).get("length", 0.0)) * 1000.0
                stress["unknown"] += untraced
                facility["unknown"] += untraced
                leg_runs.append(untraced)
                traced_m += untraced
            else:
                start = len(pieces)
                pieces.extend(pieces_of_trace(trace))
                leg_runs.append((start, len(pieces)))
                raw_junctions.extend(trace_junctions.junctions_of_trace(trace, shape, traced_m))
                traced_m += sum(piece.metres for piece in pieces[start:])
        # A long calm plan was searched in legs of its own: the answer has the plan's
        # legs, as the front end reads which leg a point on the line belongs to, and
        # a Mass Ride's stops and the description's are the plan's stops.
        groups = plan_groups
        if groups:
            if sum(groups) == len(legs):
                ends = list(itertools.accumulate(groups))
                first = [e - g for e, g in zip(ends, groups, strict=True)]
                leg_ends = [leg_ends[e - 1] for e in ends]
                stops_m = [stops_m[f] for f in first]
                leg_runs = [
                    _joined_runs(leg_runs[f:e], pieces) for f, e in zip(first, ends, strict=True)
                ]
        traced_at = clock()
        # The joins over the traced pieces are the work after the routers, and the
        # budget's reserve is for them. Once the budget itself is gone they are
        # skipped - the route is answered with its stress unknown - rather than run
        # past it (correctness review, 2026-09-28: one request took 49 s).
        over_budget = traced_at >= started + budget_s
        effort_m = None
        if over_budget:
            untraced = sum(piece.metres for piece in pieces)
            stress["unknown"] += untraced
            facility["unknown"] += untraced
            used_adjustments: list[dict] = []
            # Unknown along its whole length, as its totals are.
            classes = [("unknown", "unknown")] * len(pieces)
        else:
            analysed = refine_context.analyses.get(tuple(leg.get("shape", "") for leg in legs))
            effort_m = round(analysed.effort_m, 1) if analysed is not None else None
            classes = (
                analysed.classes
                if analysed is not None and len(analysed.pieces) == len(pieces)
                else classify(pieces, when, roadway_only=lanes_as_roadway)
            )
            traced_stress, traced_facility = totals(zip(pieces, classes, strict=True))
            for key, metres in traced_stress.items():
                stress[key] += metres
            for key, metres in traced_facility.items():
                facility[key] += metres
            used_adjustments = adjustments_used(pieces)
        stretches: list[tuple] = []
        for run in leg_runs:
            if isinstance(run, tuple):
                stretches.extend(
                    (
                        pieces[i].metres,
                        *classes[i],
                        getattr(classes[i], "unpaved", None),
                        getattr(classes[i], "rpm", None),
                        preset_name == "mass-ride" and _outside_dc(pieces[i]),
                    )
                    for i in range(run[0], run[1])
                )
            else:
                stretches.append((run, "unknown", "unknown"))
        capacity = preset_name == "mass-ride" and _has_capacity_column(
            validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
        )
        spans = stress_spans(stretches, capacity=capacity)
        events = None
        if not over_budget:
            events = _events(refine_context, legs, raw_junctions, deadline)
        # A Mass Ride's major junctions ride beside the events (`junctions.events_of`); the
        # numbering below makes a plain list of them.
        majors = getattr(events, "majors", None)
        majors_complete = getattr(events, "complete", True)
        if events is not None and majors is None and refine_context.group:
            # Events with no majors beside them: the flagged ones stand in, and the chart
            # says the list may be incomplete (correctness re-review R3).
            majors = intersections.majors_of_events(events)
            majors_complete = False
        if events is not None and refine_context.group:
            events = intersections.number_groups(events, stops_m)
        walks = [] if over_budget else walk_spans(leg_runs, pieces)
        profiled_from = clock()
        mass_ride = preset_name == "mass-ride"
        profile = route_profile(
            legs,
            spans,
            (lambda: _flow_stretches(leg_runs, pieces, classes, capacity)) if mass_ride else None,
            majors if mass_ride else None,
            majors_complete,
            None
            if mass_ride
            else lambda: calm.Pricing(
                use_roads=presets.use_roads_for(stress_dial),
                rate=presets.calm_rate_for(stress_dial),
                weights=(exposure.lts3, exposure.lts4, exposure.avoid),
                lts2=exposure.lts2,
                maxcalm=maxcalm,
                target=target_m is not None,
                no_trail=variant == Variant.NO_TRAIL.value,
                quiet_cost_s=refine_context.quiet_cost,
                junction_weight=refine.intersection_weight(stress_dial),
            ),
            events,
            None if mass_ride else _calm_pieces(leg_runs, pieces, classes),
        )
        profile_s = clock() - profiled_from
        described = describe_route(
            leg_runs, pieces, classes, events, trip.get("summary") or {}, walks
        )
        described_full, described_overview = described if described else (None, None)
        joined_at = clock()
        if joined_at - started > budget_s:
            logger.warning(
                "a %s plan on %s took %.1f s, past its %s s budget: route %.1f s, trace %.1f s, "
                "joins %.1f s (the chart's profile %.2f s of them)%s",
                preset_name,
                variant,
                joined_at - started,
                budget_s,
                routed_at - started,
                traced_at - routed_at,
                joined_at - traced_at,
                profile_s,
                " (skipped)" if over_budget else "",
            )

        summary = trip.get("summary") or {}
        climb, descent = climb_and_descent(elevations)
        hills_seek = None
        if calm_seek and not alternate:
            # No climb search among alternatives: the stress order chose, and the
            # climbing only broke its ties (298(3)).
            hills_seek = {
                "candidates": 1,
                "chosen": 0,
                "extra_climb_m": 0.0,
                "extra_distance_m": 0.0,
                "limited": seek_limited,
            }
        elif seeking and not alternate:
            direct = trips[0].get("summary") or {}
            hills_seek = {
                "candidates": len(trips),
                "chosen": chosen,
                "extra_climb_m": round(climb - _climb_of(trips[0]), 1),
                "extra_distance_m": round(
                    (float(summary.get("length", 0.0)) - float(direct.get("length", 0.0))) * 1000.0,
                    1,
                ),
                "limited": seek_limited,
            }
        hills_avoid = None
        if avoiding and not alternate:
            direct = trips[0].get("summary") or {}
            hills_avoid = {
                "candidates": len(trips),
                "chosen": chosen,
                "weight": round(avoid_weight, 2),
                "brake_grade": preset.brake_grade,
                "grade_cost_s": round(
                    climbs.grade_cost_s(grade_profile(trip), preset.brake_grade), 1
                ),
                "direct_grade_cost_s": round(
                    climbs.grade_cost_s(grade_profile(trips[0]), preset.brake_grade), 1
                ),
                "extra_distance_m": round(
                    (float(summary.get("length", 0.0)) - float(direct.get("length", 0.0))) * 1000.0,
                    1,
                ),
                "limited": seek_limited,
                "kept_middle": kept_middle,
            }
        straight_m = sum(
            haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False)
        )
        detour = _detour(
            round(float(summary.get("length", 0.0)) * 1000.0, 1),
            straight_m,
            request,
            variant,
            preset_name,
            dials=(stress_dial, assist, avoid_gravel),
            busy_m=stress["3"] + stress["4"] + stress["5"],
            when=when,
            deadline=deadline,
            traces=traces,
        )
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
            "stress_adjustments": used_adjustments,
            "stress_spans": spans,
            "profile": profile,
            "dials": {
                "stress": stress_dial,
                "hills": hills_dial,
                "when": when,
                "carrying": presets.carrying_of(preset_name, dials.carrying),
                "assist": assist,
                "avoid_gravel": avoid_gravel,
                # What was planned, not what was asked: Mass Ride is always trails-off.
                "trails_off": trails_off or preset.variant == Variant.NO_TRAIL.value,
                "target_distance_m": int(target_m) if target_m else None,
                "system_weight_kg": dials.system_weight_kg if maxcalm else None,
                "loop": loop,
            },
            "hills_seek": hills_seek,
            "hills_avoid": hills_avoid,
            "attribution": list(ATTRIBUTION),
            "leg_ends": leg_ends,
            "intersections": None if events is None else _intersection_rows(events),
            "intersection_groups": None if events is None else _intersection_groups(events),
            "calm_search": refined,
            "dodges": dodges_of,
            "effort_m": effort_m,
            "loop": (
                {**({} if alternate else loop_info or {}), **(loop_stats(pieces, leg_runs) or {})}
                if loop
                else None
            ),
            "detour": detour,
            "description": described_full,
            "description_overview": described_overview,
            "moved_points": moved_points,
        }

    body = _answer(trip, refined, dodges_of=dodges)
    candidates = []
    for found, _reading in refine_context.candidates[1:]:
        # Each is read in full (its traces are remembered, its junctions read once
        # across the joints of a long plan), inside what is left of the budget.
        if deadline.at - clock() < ALTERNATE_MIN_S:
            break
        # A candidate is answered as the search found it (its `dodges` null): the
        # dodge pass is the answer's alone, one bounded pass a plan.
        try:
            refine.analyse(found, refine_context, deadline)
            candidate = _answer(found, None, True)
            if maxcalm and target_m:
                candidate["over_target_m"] = target_fields(
                    _trip_length_m(found), target_m, ceiling
                )["over_target_m"]
            candidates.append({**candidate, "rank": len(candidates) + 2})
        except (DeadlineExceeded, RouterUnavailable, NoRoute):
            break
    body["candidates"] = candidates or None
    body["rank"] = 1 if candidates else None
    return body


# The credits are brief, as an in-text citation is (OWNER-DECISIONS 306: "keep it
# brief and put the full information in documentation"); docs/SOURCES.md is the
# reference list, and tests/test_credits.py holds each line here to an entry there.
# ODbL keeps its own form, and the District's CC BY 4.0 layers keep what that licence
# asks of a credit (section 3(a)(1)): the licence, linked, and that they were adapted.
# PLAN, Licensing, and the public-tier rules in force (owner decision of
# 2026-09-26): ODbL attribution for everything OpenStreetMap-derived, which is
# the route itself and its stress tiers. DDOT's traffic volume ("2024 Traffic
# Volume" on Open Data DC) is CC BY 4.0, whose section 3(a)(1)(B) asks that an
# adaptation say it was modified and link the licence: the counts are
# normalised and fed to the classifier, so the credit says "adapted". VDOT's
# volume layer states no licence and is credited plainly. USGS 3DEP for the
# elevation the climb is computed from. DDOT's Central Business District boundary
# (fixtures/cbd, CC BY 4.0) decides which sidewalks bicycles may not ride
# (routemaker.cbd), so it shares DDOT's line. The Architect of the Capitol's
# jurisdiction polygon (fixtures/cbd, Open Data DC, DC GIS, CC BY 4.0) decides
# which of those sidewalks are the Capitol grounds' and exempt, and has a line of
# its own; it is used as published, so it is not marked adapted. DC's Roadway
# Block (fixtures/datasets, Open Data DC, DDOT / DC GIS, CC BY 4.0) sets the
# posted speed, the lanes each way, one-way streets, bike lanes, parking and,
# where no count layer reached a street, the traffic count the District's stress
# tiers are scored on (routemaker.agency_roads), and is parsed and combined with
# OSM, so it is credited as adapted. Baltimore's street centerline, bike
# facilities and multiuse trails (Open Baltimore; open licence by Baltimore City
# Code Art. 1 §9-1(h)) set Baltimore's speeds where OSM has none, its one-way
# streets, and the bike lanes and trail access the 2026-10-01 override file
# corrects; the credit line is the owner's (OWNER-DECISIONS 159), the items
# themselves carry none. Montgomery County Planning's Bicycle Level of Traffic
# Stress sets the Montgomery County roads loaded as Avoid (OWNER-DECISIONS 149,
# 181); its licence asks for "attribution to the Montgomery County Planning
# Department", in the same change as the rows. Protomaps is credited by the map,
# which draws its basemap; nothing in a route response comes from it.
ATTRIBUTION = (
    "© OpenStreetMap contributors (ODbL)",
    "DC Open Data (CC BY 4.0, adapted): https://creativecommons.org/licenses/by/4.0/",
    "VDOT",
    "Open Baltimore",
    "Montgomery County Planning Department",
    "USGS 3DEP",
    "U.S. Census Bureau",
)
