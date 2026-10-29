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
import contextvars
import copy
import dataclasses
import functools
import hashlib
import http.client
import itertools
import json
import logging
import math
import time
import urllib.error
import urllib.request
from array import array
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_EXCEPTION, Future
from concurrent.futures import wait as wait_futures
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from pipeline.schema import (
    HAZARD_COLUMN,
    MASS_WIDTH_COLUMN,
    ROUGH_COLUMN,
    SCENIC_COLUMN,
    SIDEPATH_NAME_COLUMN,
    STRESS_HALF_COLUMN,
    TRAIL_NAME_COLUMN,
    TRAIL_RUN_COLUMN,
    validate_schema_name,
)
from pipeline.variants import Variant
from routemaker import avoid_junctions as avoid_rules
from routemaker import (
    calm,
    circleparks,
    climbs,
    describe,
    flow,
    grade_stress,
    hill_cost,
    intersections,
    junction_delay,
    mass_route,
    mdot_aadt,
    mtbmode,
    ridetime,
    steep_grades,
    time_marks,
    trace_junctions,
    zoo,
)
from routemaker import detour as detour_rules
from routemaker import profile as profile_rules
from routemaker.facility import FACILITIES
from routemaker.geo import (
    Point,
    bearing,
    bearing_delta,
    bearing_lonlat,
    haversine,
    haversine_lonlat,
)
from routemaker.lang import t
from routemaker.massflow import band_of
from routemaker.measure import elevation_gain

from . import (
    avoid_junctions,
    beside_roads,
    mass_hazards,
    mtb,
    novice_walks,
    parallel,
    presets,
    route_cache,
    route_hazards,
    route_scenic,
    segment_info,
    timing,
    trail_touch,
)
from . import workzones as work_zones

logger = logging.getLogger(__name__)

# Metres between elevation samples. 3DEP at 1 arc-second is about 30 m on the
# ground here, so a finer interval samples the same cell twice.
ELEVATION_INTERVAL_M = 30
# The rider's stops are matched to every way within this many metres of where they
# were put, and the router takes the one the route costs least from (Valhalla's
# location `radius`), rather than only the nearest. A stop put on the Fairfax County
# Parkway Trail lies 4.5 m from a ramp and 5.9 m from the trail; matched to the ramp
# alone, the route left the trail for 0.6 mi of the Avoid-rated parkway to reach it
# (Stephen, 2026-10-11).
STOP_RADIUS_M = 15

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


class StrayTrails(Exception):
    """A route planned on the off-road graph for a dirt trail a point touches
    (`core.trail_touch`) took dirt trails no point touches: `rings` leave them out, and
    `plan` plans again; `touched` is the trails each point touches, not looked up again."""

    def __init__(self, rings: tuple, touched: tuple[frozenset[int], ...]) -> None:
        super().__init__(f"{len(rings)} dirt trail run(s) no point touches")
        self.rings = rings
        self.touched = touched


# How many times a plan is made again without the dirt trails it found for itself
# (`StrayTrails`) before it is made on the ride type's own graph, the touched trail closed.
STRAY_ROUNDS = 3


class NoRoute(Exception):
    """No route joins these points on this preset's variant.

    `no_path` is true only when the router said there is no path at all, as
    opposed to no road near a point or some other refusal.
    """

    def __init__(self, message: str, no_path: bool = False) -> None:
        super().__init__(message)
        self.no_path = no_path


class StraySideRoute(NoRoute):
    """A side route (a candidate, the way round a junction or through a closure) of such a
    plan takes a dirt trail no point touches: that side route alone is dropped."""


class TooLong(Exception):
    """The router refused the request as beyond one of its limits."""


class DeadlineExceeded(Exception):
    """The request's time budget ran out before the router had answered."""


class PlanCancelled(DeadlineExceeded):
    """The rider replaced this plan with a newer one (POST /api/route/cancel,
    `core.plan_cancel`): its budget is spent at once. A DeadlineExceeded, so every step
    that already gives way for time gives way for it too, and the plan ends without
    another router call (each later `_call` raises it again)."""


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
    except (
        TimeoutError,
        urllib.error.URLError,
        ConnectionError,
        # A reply cut off part way (IncompleteRead, BadStatusLine): review api-2.
        http.client.HTTPException,
        ValueError,
    ) as error:
        raise RouterUnavailable(str(error)) from error


@dataclass(frozen=True)
class Deadline:
    """When the request's budget ends (monotonic), and the most one call may take."""

    at: float
    per_call_s: float


# When the plan running in this context must be done (monotonic; `plan` sets it, in a
# context of its own): its segment-table reads run under a statement timeout of what is
# left (`plan_cursor`), so a slow or blocked database ends the plan as its clock does, 503
# with retry advice, not at gunicorn's kill (review speed-9). None outside a plan.
_plan_ends: contextvars.ContextVar[float | None] = contextvars.ContextVar("plan_ends", default=None)
# Postgres's query_canceled, which a statement timeout raises.
QUERY_CANCELED = "57014"


@contextmanager
def plan_cursor(cap_s: float | None = None) -> Iterator:
    """A cursor for one of the plan's own reads of the segment table, under a statement
    timeout of the time the plan has left, or `cap_s` where that is less; a read it cancels
    raises DeadlineExceeded. Outside a plan, a cursor under `cap_s`, or a plain one."""
    # A plan cancelled meanwhile reads no more (as found by a router call's ask: no poll here).
    check_cancel(poll=False)
    ends = _plan_ends.get()
    if ends is None and cap_s is None:
        with connection.cursor() as cursor:
            yield cursor
        return
    left_s = cap_s if ends is None else ends - clock()
    if cap_s is not None:
        left_s = min(left_s, cap_s)
    left_ms = int(left_s * 1000)
    if left_ms <= 0:
        raise DeadlineExceeded("no time left to read the segment table")
    outer = connection.in_atomic_block
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            previous = None
            if outer:
                # Inside a caller's transaction the setting would outlive this read.
                cursor.execute("SELECT current_setting('statement_timeout')")
                previous = cursor.fetchone()[0]
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [str(left_ms)])
            yield cursor
            if previous is not None:
                cursor.execute("SELECT set_config('statement_timeout', %s, true)", [previous])
    except DatabaseError as error:
        if _canceled(error):
            raise DeadlineExceeded(f"a segment table read ran past {left_ms} ms") from error
        raise


def _canceled(error: BaseException) -> bool:
    """Whether `error` (Django's wrapper, or the driver's own error under it) is
    Postgres canceling the statement: psycopg's QueryCanceled, or sqlstate (psycopg 3)
    or pgcode (psycopg 2) 57014."""
    try:
        from psycopg.errors import QueryCanceled
    except ImportError:  # pragma: no cover - psycopg 3 is the driver in use
        QueryCanceled = ()  # noqa: N806
    for each in (error, error.__cause__):
        if each is None:
            continue
        if isinstance(each, QueryCanceled):
            return True
        for name in ("sqlstate", "pgcode"):
            if getattr(each, name, None) == QUERY_CANCELED:
                return True
    return False


# The cancel watch of the plan running in this context (`core.plan_cancel.Watch`), or None:
# the API sets it for a request that names its plan (X-Plan-Id). Server-side cancel of a
# superseded Go plan, the owner, 2026-10-27 (routing audit S7, option B): "approved". Each
# router call asks it first, so a cancelled plan stops at its next call: the flag is seen
# between calls, never inside one. The pool's tasks carry it with the request's context.
_cancel_watch: contextvars.ContextVar = contextvars.ContextVar("cancel_watch", default=None)


def watch_cancel(watch) -> contextvars.Token:
    """Run what follows in this context under `watch` (`core.plan_cancel.Watch`, or None)."""
    return _cancel_watch.set(watch)


def unwatch_cancel(token: contextvars.Token) -> None:
    _cancel_watch.reset(token)


def check_cancel(poll: bool = True) -> None:
    """Raise PlanCancelled where the plan running here has been cancelled. `poll`: ask
    the store (at most every `plan_cancel.POLL_S`, from the request's own thread only);
    otherwise only what an earlier ask found."""
    watch = _cancel_watch.get()
    if watch is not None:
        watch.check(poll)


def cancel_seen() -> bool:
    """Whether the plan running here has been found cancelled (no ask of the store)."""
    watch = _cancel_watch.get()
    return watch is not None and watch.cancelled


# How often the request's thread, blocked on calls it gave the pool, asks whether its plan
# has been cancelled (`await_future`): the pool's threads never read the store, so without this a
# cancel waited for every call already submitted (each up to ALTERNATES_TIMEOUT_S).
CANCEL_WAIT_STEP_S = 0.1


def await_future(future: Future, timeout: float | None = None):
    """`future.result(timeout)`, read on the request's thread so that a cancel of its plan
    (`check_cancel`) is seen while it waits: it raises PlanCancelled within about a
    CANCEL_WAIT_STEP_S of the flag being seen, and the calls not yet started never go (the
    pool's threads see the watch's `cancelled` at their next call). Where no plan is
    watched, or on a pool thread, exactly `future.result(timeout)`. `timeout` (seconds, or
    None for no limit): TimeoutError past it, as `future.result` raises, the future left
    running (the early alternatives' ask, `refine._router_alternates`, review of S7)."""
    watch = _cancel_watch.get()
    if watch is None or parallel.inside():
        return future.result(timeout=timeout)
    ends = None if timeout is None else clock() + max(timeout, 0.0)
    while not future.done():
        try:
            watch.check()
        except PlanCancelled:
            future.cancel()
            raise
        step = CANCEL_WAIT_STEP_S
        if ends is not None:
            left = ends - clock()
            if left <= 0:
                raise TimeoutError
            step = min(step, left)
        wait_futures([future], timeout=step, return_when=FIRST_EXCEPTION)
    return future.result()


def _own_context(fn):
    """`fn` run in a copy of the caller's context, so what it sets there (`_plan_ends`)
    ends with it."""

    @functools.wraps(fn)
    def run(*args, **kwargs):
        return contextvars.copy_context().run(fn, *args, **kwargs)

    return run


def _skipped_for_time() -> None:
    """A check left out because too little of the budget was left for it: counted as a
    failed router call, so the plan answered without it is not kept in the answer cache
    (`core.route_cache.keepable`)."""
    timing.record_call(0.0, True)


def _call(variant: str, endpoint: str, payload: dict, deadline: Deadline) -> dict:
    """One router call inside the request's budget."""
    url = f"{settings.VALHALLA_UPSTREAMS[variant]}/{endpoint}"
    began = timing.now()
    failed = True
    try:
        # Inside the try: a cancelled plan's call, and one skipped for want of time,
        # count as failed, so the answer is never kept in the answer cache
        # (`core.route_cache.keepable`).
        remaining = deadline.at - clock()
        if remaining <= 0:
            raise DeadlineExceeded(f"no time left for {endpoint}")
        check_cancel()
        answer = _transport(url, payload, min(deadline.per_call_s, remaining))
        failed = False
        return answer
    except RouterRefused:
        # An answer, if not a route: nothing was cut short.
        failed = False
        raise
    except RouterUnavailable as error:
        if clock() >= deadline.at:
            raise DeadlineExceeded(f"{endpoint} ran past the budget") from error
        raise
    finally:
        # Server-Timing's `router` (`core.timing`): every call's own time, and whether it
        # failed for want of an answer (a plan the answer cache then does not keep).
        timing.record_call(timing.now() - began, failed)


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
    # Where the piece's edge begins at a fork the route leaves the straight-ahead way
    # by (`describe.fork_movement`): the movement to say there; None elsewhere, and on
    # every piece of an edge but its first.
    fork: str | None = field(default=None, compare=False)
    # The other ways at the node the piece's edge begins at, each (its heading away from
    # the node, Valhalla's `use`, its road class and driveability), for the ride card's
    # junction diagram (`describe.junction_shape`); None on every piece of an edge but
    # its first.
    others: tuple | None = field(default=None, compare=False)
    # The other ways at the junctions just short of that node (`describe.SHAPE_NEAR_M`),
    # as `others`: where a main road was crossed just before a turn onto its service
    # road; None elsewhere.
    prior: tuple | None = field(default=None, compare=False)
    # The compass bearing of the piece's own stretch, unwrapped along the trace: each
    # piece's is the one before's plus the turn between them (-180 to 180), so the
    # difference between two pieces' is the way the route really turned between them
    # (`describe.turn_between`: a hairpin right reads +190, never a left of -170).
    bearing: float | None = field(default=None, compare=False)
    # The turn the route's own line makes at the node the piece's edge begins at, clockwise
    # positive, each side a chord over up to `describe.LINE_SPAN_M` (`_line_headings`); None
    # on every piece of an edge but its first, and where the line runs out within
    # `describe.JUNCTION_M` of the node.
    turn: float | None = field(default=None, compare=False)
    # Whether another way a bicycle may ride away on meets that node (`_choice_of`); None
    # where `turn` is.
    choice: bool | None = field(default=None, compare=False)
    # Whether the piece's edge is on the way the edge before was on and the line goes back
    # there over the points it came in on (`_retraces`): a turnaround on the way itself,
    # said as a U-turn (`describe.UTURN_DEG`, round-3 audit D31). False on every piece of
    # an edge but its first.
    retrace: bool = field(default=False, compare=False)


def _heading(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


# The plan's memo of its readings of each trace (audit S19): the trace cut into pieces
# (`pieces_of_trace`) and its junctions and edge middles (`trace_junctions.read_edges`), read
# at the leg's start once and shifted for each caller. A plan reads the same trace several
# times: the hill guards' `_exposure` (the kept trip twice), the calm search's
# `refine.analyse` (a stress-only reading is never kept as an analysis) and the answer.
# Keyed by the trace object's id. Each entry holds the trace itself: that keeps the id from
# being reused, and it also pins the trace (its whole parsed JSON) for as long as the entry
# lives. The cap counts pieces, not those traces, so `_plan_rounds` empties the memo with the
# rounds' own traces before the final round, whose traces are new objects no entry can match
# (review of audit S19). Pieces and junctions are frozen, so the entries' are shared, in new
# lists; an analysis kept for the plan holds the same pieces, so an entry adds little beside
# it. At most READING_MEMO_PIECES pieces, the least recently used trace dropped first: about
# 0.5 KB a piece with its junctions, so a few MB at most beside the plan's own analyses and
# traces (measured in tests/test_trace_reading.py, `test_the_memo_holds_little_beside_the_
# plans_own_analyses`, which leaves the traces out as the plan holds them anyway). `plan`
# sets it for its own context and clears it as it ends; None outside a plan (nothing
# remembered).
_reading_memo: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "reading_memo", default=None
)
READING_MEMO_PIECES = 12_000


@dataclass
class _Reading:
    trace: dict
    pieces: tuple[Piece, ...] | None = None
    edges: trace_junctions.EdgeReading | None = None


def trace_reading(
    trace: dict, shape: list | None = None, edges: bool = False, marks: bool = False
) -> tuple[list[Piece], trace_junctions.EdgeReading | None]:
    """The trace's pieces (`pieces_of_trace`, a new list) and, with `edges` or `marks`, its
    junctions (and with `marks` its edge middles) at the leg's start, `trace_junctions.
    read_edges`; `shape` the leg's own shape decoded, read only where the trace has none.
    Read once a plan (`_reading_memo`), the trace's shape decoded once for all of it."""
    memo = _reading_memo.get()
    entry = memo.pop(id(trace), None) if memo is not None else None
    if entry is None or entry.trace is not trace:
        entry = _Reading(trace)
    want_edges = edges or marks
    need_edges = want_edges and (entry.edges is None or (marks and entry.edges.marks is None))
    encoded = trace.get("shape") or ""
    own = decode_polyline6(encoded) if entry.pieces is None or need_edges else None
    if entry.pieces is None:
        entry.pieces = tuple(pieces_of_trace(trace, own))
    found = entry.edges
    if need_edges:
        found = trace_junctions.read_edges(trace, shape or [], marks, own)
        # Only a reading of the trace's own shape is kept: one read from the leg's is the
        # leg's, not the trace's.
        if encoded:
            entry.edges = found
    if memo is not None:
        memo[id(trace)] = entry  # the most recently used last
        held = sum(len(kept.pieces or ()) for kept in memo.values())
        while held > READING_MEMO_PIECES and len(memo) > 1:
            dropped = memo.pop(next(iter(memo)))
            held -= len(dropped.pieces or ())
    return list(entry.pieces), found if want_edges else None


def pieces_of_trace(trace: dict, shape: list | None = None) -> list[Piece]:
    """Cut every traced edge at its shape vertices, apportioning its length. `shape` is the
    trace's own shape decoded, where the caller has it already (`trace_reading`)."""
    if shape is None:
        shape = decode_polyline6(trace.get("shape", ""))
    to_metres = 1609.344 if trace.get("units") == "miles" else 1000.0
    pieces: list[Piece] = []
    # The last edge kept: the node a fork is read at is where it ends; and every one
    # kept, with its length, for the junctions just short of that node.
    before: dict | None = None
    kept: list[tuple[dict, float]] = []
    # The last stretch's bearing, unwrapped (`Piece.bearing`).
    unwrapped: float | None = None
    # How far along the route's line each piece begins, on the line's own measure
    # (`_one_turn_per_junction`).
    along: list[float] = []
    walked = 0.0
    # The vertices the trace's edges begin at: its nodes (`_line_point`).
    nodes = frozenset(
        e["begin_shape_index"]
        for e in trace.get("edges", [])
        if isinstance(e.get("begin_shape_index"), int)
    )
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
        line_in = line_out = turn = None
        choice = None
        retrace = False
        if before is not None:
            retrace = bool(way_id) and way_id == int(before.get("way_id") or 0)
            retrace = retrace and _retraces(shape, begin)
            line_in, line_out, first, last = _line_headings(shape, begin, nodes)
            turn = _line_turn(shape, line_in, line_out, first, last)
            choice = _choice_of(
                before,
                line_in if line_in is not None else _heading(before.get("end_heading")),
                line_out if line_out is not None else info["heading_in"],
            )
        fork = _fork_of(before, edge, line_in, line_out)
        others = _others_of(before)
        prior = _behind_of(kept)
        before = edge
        kept.append((edge, length))
        stretches = []
        for a, b in zip(shape[begin:end], shape[begin + 1 : end + 1], strict=True):
            stretches.append((a, b, haversine_lonlat(a, b)))
        ground = sum(s[2] for s in stretches)
        if ground <= 0:
            # A degenerate edge: all its length on its first vertex.
            (lon, lat) = shape[begin]
            along.append(walked)
            pieces.append(
                Piece(
                    way_id,
                    lon,
                    lat,
                    length,
                    **info,
                    fork=fork,
                    others=others,
                    prior=prior,
                    turn=turn,
                    choice=choice,
                    retrace=retrace,
                )
            )
            continue
        for a, b, d in stretches:
            if d > 0:
                along.append(walked)
                walked += d
                compass = bearing_lonlat(a, b)
                unwrapped = (
                    compass
                    if unwrapped is None
                    else unwrapped + (compass - unwrapped + 540.0) % 360.0 - 180.0
                )
                pieces.append(
                    Piece(
                        way_id,
                        (a[0] + b[0]) / 2,
                        (a[1] + b[1]) / 2,
                        length * d / ground,
                        **info,
                        fork=fork,
                        others=others,
                        prior=prior,
                        bearing=unwrapped,
                        turn=turn,
                        choice=choice,
                        retrace=retrace,
                    )
                )
                fork = None
                others = None
                prior = None
                turn = None
                choice = None
                retrace = False
    return _one_turn_per_junction(pieces, along)


# How near the line must come back to the points it went out on, at a node, for the turn
# there to be a retrace (`_retraces`): a dead end's way back is the same points, give or
# take the router's rounding.
RETRACE_M = 1.0


def _retraces(shape: list, at: int) -> bool:
    """Whether the route's line, at shape vertex `at`, goes back over the points it came
    in on: the first vertex on from `at` lies on the last stretch in (within RETRACE_M of
    it), or the last vertex in lies on the first stretch out (a leg begun part way along
    the way, short of the node). Only where both stretches have a length."""
    if not 0 < at < len(shape) - 1:
        return False
    node = shape[at]
    back = next((shape[j] for j in range(at - 1, -1, -1) if shape[j] != node), None)
    ahead = next((shape[j] for j in range(at + 1, len(shape)) if shape[j] != node), None)
    if back is None or ahead is None:
        return False
    return (
        _off_stretch_m(ahead, node, back) <= RETRACE_M
        or _off_stretch_m(back, node, ahead) <= RETRACE_M
    )


def _off_stretch_m(point: tuple, a: tuple, b: tuple) -> float:
    """How far `point` is from the stretch from `a` to `b` (each lon, lat), in metres, on
    a flat projection about `a` (a few metres of a node)."""
    scale = math.cos(math.radians(a[1]))
    bx, by = (b[0] - a[0]) * scale, b[1] - a[1]
    px, py = (point[0] - a[0]) * scale, point[1] - a[1]
    length2 = bx * bx + by * by
    f = 0.0 if length2 <= 0 else max(0.0, min(1.0, (px * bx + py * by) / length2))
    near = (a[0] + bx * f / scale, a[1] + by * f)
    return haversine_lonlat(point, near)


def _one_turn_per_junction(pieces: list[Piece], along: list[float]) -> list[Piece]:
    """`pieces` with each junction's turn read once. Nodes nearer one another than
    `describe.JUNCTION_M` along the line (`along`: where each piece begins, on the line's
    own measure, never the trace's lengths, so the two always agree) are one junction,
    and the line is read through them all (`_line_point`), so each reads the same turn:
    it is left on one of them, the one where the way changes (the turn is onto it) or
    else the sharpest, and the others are straight on, with no fork of their own. Nodes
    further apart each read their own turn, the line stopping at the other."""
    nodes = [i for i, p in enumerate(pieces) if p.turn is not None]
    clusters: list[list[int]] = []
    for i in nodes:
        if clusters and along[i] - along[clusters[-1][-1]] < describe.JUNCTION_M:
            clusters[-1].append(i)
        else:
            clusters.append([i])
    out = list(pieces)
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        changes = [
            i
            for i in cluster
            if i > 0
            and (pieces[i].names, pieces[i].use) != (pieces[i - 1].names, pieces[i - 1].use)
        ]
        keep = max(changes or cluster, key=lambda i: abs(pieces[i].turn))
        for i in cluster:
            if i != keep:
                out[i] = dataclasses.replace(pieces[i], turn=0.0, fork=None)
    return out


def _line_point(shape: list, at: int, step: int, nodes: frozenset[int]) -> tuple:
    """Where the route's line is `describe.LINE_SPAN_M` from vertex `at`, walking `step`
    (1 on, -1 back): (the point, the last vertex walked to). It stops short at another
    node at least `describe.JUNCTION_M` away, so a turn at the next junction never tilts
    this one, and goes on past a nearer one, as part of the same junction. The point is
    None where the line runs out within JUNCTION_M."""
    here = shape[at]
    gone = 0.0
    j = at
    while 0 <= j + step < len(shape):
        if j != at and j in nodes and gone >= describe.JUNCTION_M:
            return here, j
        nxt = shape[j + step]
        d = haversine_lonlat(here, nxt)
        if d > 0 and gone + d >= describe.LINE_SPAN_M:
            f = (describe.LINE_SPAN_M - gone) / d
            return (here[0] + (nxt[0] - here[0]) * f, here[1] + (nxt[1] - here[1]) * f), j + step
        gone += d
        here = nxt
        j += step
    return (here if gone >= describe.JUNCTION_M else None), j


def _line_headings(shape: list, at: int, nodes: frozenset[int]) -> tuple:
    """The compass headings the route's own line arrives at shape vertex `at` on and
    leaves it on, each a chord to `_line_point`, and the first and last vertices they
    span. Valhalla's headings are the edge's own, so a tiny edge at a junction (a kerb
    or crossing node a few metres on) can tilt them far off the way the rider goes (the
    owner, 2026-10-23, on Sligo Creek Trail: "Left to stay on" a gentle bend)."""
    if not 0 <= at < len(shape):
        return None, None, at, at
    node = shape[at]
    back, first = _line_point(shape, at, -1, nodes)
    ahead, last = _line_point(shape, at, 1, nodes)
    return (
        bearing_lonlat(back, node) if back is not None else None,
        bearing_lonlat(node, ahead) if ahead is not None else None,
        first,
        last,
    )


def _line_turn(
    shape: list, line_in: float | None, line_out: float | None, first: int, last: int
) -> float | None:
    """The turn the route's line makes at a node (`Piece.turn`), clockwise positive: from
    its chords (`_line_headings`), but past `describe.HAIRPIN_DEG` on the side the line
    itself winds between vertices `first` and `last` (its segments' turns added up), so a
    turnaround right a little past straight back reads +190, never -170."""
    if line_in is None or line_out is None:
        return None
    turn = (line_out - line_in + 540.0) % 360.0 - 180.0
    if abs(turn) < describe.HAIRPIN_DEG:
        return turn
    wound = 0.0
    previous = None
    for a, b in zip(shape[first:last], shape[first + 1 : last + 1], strict=True):
        if haversine_lonlat(a, b) <= 0:
            continue
        compass = bearing_lonlat(a, b)
        if previous is not None:
            wound += (compass - previous + 540.0) % 360.0 - 180.0
        previous = compass
    sides = [
        t for t in (turn, turn - 360.0, turn + 360.0) if abs(t) <= 360.0 - describe.HAIRPIN_DEG
    ]
    return min(sides, key=lambda t: abs(t - wound))


def _choice_of(before: dict, heading_in: float | None, heading_out: float | None) -> bool:
    """Whether another way a bicycle may ride away on meets the node `before` ends at
    (`Piece.choice`): not one of `describe.FORK_IGNORED_USES`, nor a sidewalk, nor one
    that runs back nearly the way the rider came (`describe.CHOICE_BACK_DEG`) and lies
    well off the route's own way out (`describe.CHOICE_BACK_CLEAR_DEG`), which no one
    takes for the way on (Rock Creek Trail, the Mount Vernon and Custis Trails)."""

    def apart(a: float, b: float) -> float:
        return abs((a - b + 540.0) % 360.0 - 180.0)

    return any(
        (heading := _heading(other.get("begin_heading"))) is not None
        and (
            heading_in is None
            or apart(heading, heading_in) <= describe.CHOICE_BACK_DEG
            or (
                heading_out is not None
                and apart(heading, heading_out) <= describe.CHOICE_BACK_CLEAR_DEG
            )
        )
        and other.get("use") not in describe.FORK_IGNORED_USES
        and other.get("use") not in describe.SHAPE_IGNORED_USES
        and other.get("cyclability") not in ("none", "backward")
        for other in (before.get("end_node") or {}).get("intersecting_edges") or []
    )


def _fork_of(
    before: dict | None,
    edge: dict,
    line_in: float | None = None,
    line_out: float | None = None,
) -> str | None:
    """`describe.fork_movement` at the node between two traced edges: the other
    ways there are the first edge's `end_node.intersecting_edges`. The route's own
    way is read from its line (`_line_headings`) where it is known, else from
    Valhalla's headings of the two edges."""
    if before is None:
        return None
    others = [
        (_heading(other.get("begin_heading")), other.get("use"), other.get("cyclability"))
        for other in (before.get("end_node") or {}).get("intersecting_edges") or []
    ]
    return describe.fork_movement(
        line_in if line_in is not None else _heading(before.get("end_heading")),
        line_out if line_out is not None else _heading(edge.get("begin_heading")),
        others,
        trail=edge.get("use") in describe.TRAIL_USES,
    )


def _others_of(before: dict | None) -> tuple | None:
    """The other ways at the node a traced edge begins at (`describe.junction_shape`):
    the edge before's `end_node.intersecting_edges`, each (heading away, use, road class,
    driveability)."""
    if before is None:
        return None
    return tuple(
        (
            _heading(other.get("begin_heading")),
            other.get("use"),
            other.get("road_class"),
            other.get("driveability"),
        )
        for other in (before.get("end_node") or {}).get("intersecting_edges") or []
    )


def _behind_of(kept: list[tuple[dict, float]]) -> tuple | None:
    """The other ways at the junctions within `describe.SHAPE_NEAR_M` short of the node
    the last edge kept ends at, as `_others_of`; None where none."""
    found: list = []
    gap = 0.0
    for i in range(len(kept) - 1, 0, -1):
        gap += kept[i][1]
        if gap >= describe.SHAPE_NEAR_M:
            break
        found.extend(_others_of(kept[i - 1][0]) or ())
    return tuple(found) or None


# One row per piece, in the pieces' order: the tier and facility class of the
# segment nearest the piece on its way. The breakdown sums them; the route's
# coloured sections (`stress_spans`) keep their order. The answer's scenic roads and stress
# adjustments are read in it too (audit S17), each where the table has its columns.
_STRESS_JOIN = """
SELECT {tier}, {facility}, seg.is_unpaved, seg.road_lanes,
       seg.road_oneway{capacity_out}{half_out}{rough_out}{hazard_out}{scenic_out}{adjustment_out}
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
# the map draws them by stress, as it did. Every such check reads the one shared
# answer, `segment_info.live_columns` (review CH-1).


def _has_capacity_column(schema: str) -> bool:
    return segment_info.has_columns(schema, MASS_WIDTH_COLUMN)


# Whether the live segment table has the half-step column (`pipeline.schema.
# STRESS_HALF_COLUMN`): written by the first rebuild after half steps shipped, or added in
# place by `manage.py add_stress_half_column`. Without it every piece is a whole step.


def _has_half_column(schema: str) -> bool:
    return segment_info.has_columns(schema, STRESS_HALF_COLUMN)


# A road closed to motor traffic only at set times is a path for a ride inside
# the closure, and the road it is otherwise for any other (routemaker.facility).
_FACILITY_AT = "CASE WHEN %s = ANY(seg.car_free_when) THEN 'path' ELSE seg.facility END"
# And its stress is a closed road's: tier 1, as the weekend graph routes it
# (pipeline.run.facility_derived), rather than the tier of the road with cars on it.
_TIER_AT = "CASE WHEN %s = ANY(seg.car_free_when) THEN 1 ELSE seg.stress_tier END"

# Whether the live segment table has the facility columns yet. They arrive with
# the first rebuild after this code; until then the breakdown is all unknown
# rather than an error.


def _has_trait_columns(schema: str) -> bool:
    from .junctions import has_trait_columns

    return has_trait_columns(schema)


def _has_facility_columns(schema: str) -> bool:
    return segment_info.has_columns(schema, "facility", "car_free_when")


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
    # A half step (OWNER-DECISIONS 441i-441l, 461a): the piece is half a level above its
    # stress key ("3" and half is 3.5). The key stays the whole level, so the breakdown and
    # every reader that compares keys read the lower level; the ranking reads the half as
    # the midpoint (`core.refine`, docs/stress/stress-number.md section 3).
    half: bool
    # Whether the segment's surface sheds riders (`routemaker.stress.is_rough`: dirt, grass and
    # the like, a rutted track); None where the table has no such column. An unpaved section
    # that is rough is drawn brown, any other unpaved one gravel grey (the owner, 2026-10-21).
    rough: bool | None

    def __new__(
        cls,
        tier: str,
        facility: str,
        unpaved: bool | None = None,
        lanes: int | None = None,
        oneway: bool | None = None,
        width_m: float | None = None,
        half: bool = False,
        rough: bool | None = None,
    ):
        pair = super().__new__(cls, (tier, facility))
        pair.unpaved = unpaved
        pair.lanes = lanes
        pair.oneway = oneway
        pair.width_m = width_m
        pair.rpm = round(flow.level_riders_per_min(width_m)) if width_m is not None else None
        pair.half = bool(half) and tier in ("1", "2", "3", "4")
        pair.rough = rough
        return pair

    def __getnewargs__(self):
        return (
            self[0],
            self[1],
            self.unpaved,
            self.lanes,
            self.oneway,
            self.width_m,
            self.half,
            self.rough,
        )


class Classes(list):
    """`classify`'s answer: a list of `PieceClass`, with each piece's hazard kinds beside
    it (`hazards`, as `route_hazards.kinds_of` reads them), read in the same query rather than
    a second one over the same pieces (audit S16); None where the live table has no hazard
    column. Beside the classes, not on them: `refine.shift_classes` and `hazard_priced`
    make new ones.

    The answer's scenic designations and stress adjustments are read in the same query too
    (audit S17), kept only for the pieces that have one, by the piece's index: `scenic`
    {index: designation in words} (as `route_scenic.designations_of` reads them) and
    `adjustments` {index: (id, the table's own tier, direction, category, note, display)}
    (as `adjustments_used` groups them). None where the table has no such columns. Off the
    per-piece classes, so their long text costs nothing on the pieces without it."""

    hazards: list[tuple[str, ...]] | None = None
    scenic: dict[int, str] | None = None
    adjustments: dict[int, tuple] | None = None


def hazards_read(classes, pieces: list) -> list[tuple[str, ...]] | None:
    """The hazard kinds `classify` read beside `classes` for `pieces`, or None where it read
    none (a table without the column, or classes not from `classify`)."""
    kinds = getattr(classes, "hazards", None)
    return kinds if kinds is not None and len(kinds) == len(pieces) else None


# The plan's memo of its stress readings (`classify`, audit S18): a hill-avoiding plan reads
# the trip it keeps two or three times (`calmer_or_own`, `no_busier_than_middle`, then the
# calm search's `refine.analyse`), each the same nearest-segment search with the same answer.
# Keyed by the live table's name, the ride time and a digest of the pieces' ways and points;
# each entry the readings as plain rows, each row kept once (the rows repeat: a few hundred
# distinct in a long route), and the hazard kinds beside: about 16 bytes a piece, so under
# 1 MB at STRESS_MEMO_TRIPS long routes. Only a reading that finished is kept. `plan` sets it
# for its own context and clears it as it ends; None outside a plan (nothing remembered).
_stress_memo: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "stress_memo", default=None
)
# The most readings remembered, the least recently used dropped first.
STRESS_MEMO_TRIPS = 8


def _stress_key(schema: str, when: str, pieces: list[Piece]) -> tuple:
    digest = hashlib.blake2b(digest_size=16)
    digest.update(array("q", [p.way_id for p in pieces]).tobytes())
    digest.update(array("d", [p.lon for p in pieces]).tobytes())
    digest.update(array("d", [p.lat for p in pieces]).tobytes())
    return (schema, when, len(pieces), digest.digest())


def classify(pieces: list[Piece], when: str, roadway_only: bool = False) -> list[tuple[str, str]]:
    """Each piece's stress key ("1".."5" or "unknown") and facility key
    ("path", "protected", "lane", "none" or "unknown"), in the pieces' order,
    for a ride at `when`, each a `PieceClass` that also carries the segment's
    surface. With `roadway_only` (a ride that takes the roadway: Mass Ride,
    not every ride on the no-trail variant), bicycle lanes of either class are
    "none"; a road closed to cars is still a path. A `Classes`, with the
    pieces' hazard kinds beside. Read once a plan (`_stress_memo`); each call is
    given classes of its own."""
    if not pieces:
        return Classes()
    # The schema name comes from settings and is validated the way every DDL
    # that names it is; an identifier cannot be a query parameter.
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    memo = _stress_memo.get()
    key = _stress_key(schema, when, pieces) if memo is not None else None
    found = memo.pop(key, None) if memo is not None else None
    if found is None:
        found = _read_stress(pieces, when, schema)
    if memo is not None:
        memo[key] = found  # the most recently used last
        while len(memo) > STRESS_MEMO_TRIPS:
            memo.pop(next(iter(memo)))
    # A reading without the scenic and adjustment parts leaves them to queries of their own.
    rows, hazards, *side = found
    classes = Classes()
    for tier, kind, *rest in rows:
        # After the lookup, so a Mass Ride and any other plan share one reading.
        if roadway_only and kind in ROADWAY_ONLY_AS_NONE:
            kind = "none"
        classes.append(PieceClass(tier, kind, *rest))
    if hazards is not None:
        classes.hazards = list(hazards)
    scenic, adjustments = side[0] if side else (None, None)
    if scenic is not None:
        classes.scenic = dict(scenic)
    if adjustments is not None:
        classes.adjustments = dict(adjustments)
    return classes


def scenic_read(classes, pieces: list) -> list[str | None] | None:
    """Each piece's scenic designations as `classify` read them beside `classes`, in the
    pieces' order (`route_scenic.along`'s `designations`), or None where it read none."""
    if len(classes) != len(pieces):
        return None
    return designations_from(getattr(classes, "scenic", None), pieces)


def designations_from(found: dict | None, pieces: list) -> list[str | None] | None:
    """The designations of `found` ({index: designation}, as `Classes.scenic`) as a list a
    piece; None where `found` is None."""
    if found is None:
        return None
    return [found.get(i) for i in range(len(pieces))]


def adjustments_read(classes, pieces: list) -> list[dict] | None:
    """`adjustments_used(pieces)` from the adjustments `classify` read beside `classes`,
    with no query of its own (audit S17); None where it read none."""
    if len(classes) != len(pieces):
        return None
    return adjustments_from(getattr(classes, "adjustments", None), pieces)


def adjustments_from(found: dict | None, pieces: list) -> list[dict] | None:
    """`adjustments_used`'s answer built from `found` ({index: (id, tier, direction,
    category, note, display)}, as `Classes.adjustments`) by its query's own rules: a piece on
    no segment or on no adjustment is left out; the metres are summed per (id, tier,
    direction, category, note, display), each in the order the route first rides it. None
    where `found` is None."""
    if found is None:
        return None
    metres: dict[tuple, float] = {}
    for index in sorted(found):
        key = found[index]
        metres[key] = metres.get(key, 0.0) + pieces[index].metres
    return [_adjustment_entry(*key, total) for key, total in metres.items()]


def _read_stress(pieces: list[Piece], when: str, schema: str) -> tuple[list[tuple], list | None]:
    """`classify`'s reading of the segment table: a row a piece (the `PieceClass` arguments,
    before the roadway-only lanes are made "none"), and the hazard kinds (None where the
    table has no hazard column)."""
    with_facility = _has_facility_columns(schema)
    with_capacity = _has_capacity_column(schema)
    with_half = _has_half_column(schema)
    with_rough = segment_info.has_columns(schema, ROUGH_COLUMN)
    with_hazard = segment_info.has_columns(schema, HAZARD_COLUMN)
    with_scenic = segment_info.has_columns(schema, SCENIC_COLUMN)
    with_adjustments = _has_adjustment_columns(schema)
    query = _STRESS_JOIN.format(
        schema=schema,
        tier=_TIER_AT if with_facility else "seg.stress_tier",
        facility=_FACILITY_AT if with_facility else "NULL",
        columns=("s.facility, s.car_free_when" if with_facility else "NULL AS facility")
        + (f", s.{MASS_WIDTH_COLUMN}" if with_capacity else "")
        + (f", s.{STRESS_HALF_COLUMN}" if with_half else "")
        + (f", s.{ROUGH_COLUMN}" if with_rough else "")
        + (f", s.{HAZARD_COLUMN}" if with_hazard else "")
        + (f", s.{SCENIC_COLUMN}" if with_scenic else "")
        + ("".join(f", s.{name}" for name in ADJUSTMENT_COLUMNS) if with_adjustments else ""),
        traits=(
            "s.road_lanes, s.road_oneway"
            if _has_trait_columns(schema)
            else "NULL::smallint AS road_lanes, NULL::boolean AS road_oneway"
        ),
        capacity_out=f", seg.{MASS_WIDTH_COLUMN}" if with_capacity else "",
        # A road closed to cars in this ride time is a path at tier 1, never a half step.
        half_out=(
            ""
            if not with_half
            else ", CASE WHEN %s = ANY(seg.car_free_when) THEN false "
            f"ELSE seg.{STRESS_HALF_COLUMN} END"
            if with_facility
            else f", seg.{STRESS_HALF_COLUMN}"
        ),
        rough_out=f", seg.{ROUGH_COLUMN}" if with_rough else "",
        hazard_out=f", seg.{HAZARD_COLUMN}" if with_hazard else "",
        scenic_out=f", seg.{SCENIC_COLUMN}" if with_scenic else "",
        # In `adjustments_used`'s order: the id, then the table's own tier (as it groups by
        # it: never the ride time's), then the why.
        adjustment_out=(
            f", seg.{ADJUSTMENT_COLUMNS[0]}, seg.stress_tier"
            + "".join(f", seg.{name}" for name in ADJUSTMENT_COLUMNS[1:])
            if with_adjustments
            else ""
        ),
    )
    arrays = [[p.way_id for p in pieces], [p.lon for p in pieces], [p.lat for p in pieces]]
    whens = ([when, when] + ([when] if with_half else [])) if with_facility else []
    rows: list[tuple] = []
    seen: dict[tuple, tuple] = {}
    hazard_values = []
    scenic: dict[int, str] | None = {} if with_scenic else None
    adjustments: dict[int, tuple] | None = {} if with_adjustments else None
    kept: dict = {}
    with plan_cursor() as cursor:
        cursor.execute(query, whens + arrays)
        for index, row in enumerate(cursor.fetchall()):
            tier, kind = row[0], row[1]
            unpaved = row[2] if len(row) > 2 and isinstance(row[2], bool) else None
            lanes = row[3] if len(row) > 3 and isinstance(row[3], int) else None
            oneway = row[4] if len(row) > 4 and isinstance(row[4], bool) else None
            # After the five fixed columns: the capacity, the half step, the surface's
            # roughness and the hazards, each where the table has it, in that order.
            extra = list(row[5:])
            width = extra.pop(0) if with_capacity else None
            half = extra.pop(0) is True if with_half else False
            rough = extra.pop(0) if with_rough else None
            rough = rough if isinstance(rough, bool) else None
            if with_hazard:
                hazard_values.append(extra.pop(0))
            # Then the scenic designations and the adjustment, each kept once (they repeat).
            if scenic is not None:
                words = route_scenic.designation_of(extra.pop(0))
                if words is not None:
                    scenic[index] = kept.setdefault(words, words)
            if adjustments is not None:
                adjustment = tuple(extra[:6])
                del extra[:6]
                # No segment, or no adjustment on it: the adjustments' own query leaves it out.
                if adjustment[0] is not None:
                    adjustments[index] = kept.setdefault(adjustment, adjustment)
            read = (
                str(tier) if tier in (1, 2, 3, 4, 5) else "unknown",
                kind if kind in FACILITY_KEYS else "unknown",
                unpaved,
                lanes,
                oneway,
                None if width is None else float(width),
                half,
                rough,
            )
            rows.append(seen.setdefault(read, read))
    hazards = route_hazards.decoded(hazard_values) if with_hazard else None
    return rows, hazards, (scenic, adjustments)


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

    `stretches` is (metres, stress key, facility key[, unpaved[, rpm[, outside DC[, half[,
    rough]]]]]) in the order ridden; the answer is [{from_m, to_m, tier, facility,
    unpaved}] in whole metres along the route, adjacent equal sections merged and those
    under MIN_SPAN_M folded into the one before (or, first on the route, the one after). `tier` is
    1-5 or null (unknown); `facility` is the class or null; `unpaved` True or False
    where the segments say, else null (OWNER-DECISIONS 302: the route line draws an
    unpaved section in the brown ramp, so a section ends where the surface changes). An
    unpaved section also says `rough`: True on a natural surface (brown), False on gravel
    (grey; the owner, 2026-10-21), None where the table does not say (brown, as before).

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
        # A half step is a section of its own (OWNER-DECISIONS 461a): its key carries the
        # half ("3h"), and the section says `half: true`.
        if len(stretch) > 6 and stretch[6] and tier in ("1", "2", "3", "4"):
            tier = f"{tier}h"
        unpaved = stretch[3] if len(stretch) > 3 else None
        # The surface key: an unpaved stretch's roughness splits it from gravel (True, False or
        # None).
        if unpaved is True:
            unpaved = ("rough", stretch[7] if len(stretch) > 7 else None)
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
        half = tier.endswith("h")
        tier = tier.removesuffix("h")
        entry = {
            "from_m": round(start),
            "to_m": round(at),
            "tier": int(tier) if tier != "unknown" else None,
            "facility": kind if kind != "unknown" else None,
            "unpaved": unpaved if not isinstance(unpaved, tuple) else True,
        }
        if isinstance(unpaved, tuple):
            entry["rough"] = unpaved[1]
        if half:
            entry["half"] = True
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


def _has_adjustment_columns(schema: str) -> bool:
    return segment_info.has_columns(schema, *ADJUSTMENT_COLUMNS)


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
    with plan_cursor() as cursor:
        cursor.execute(query, arrays)
        for adjustment_id, tier, direction, category, note, display, metres in cursor.fetchall():
            used.append(
                _adjustment_entry(adjustment_id, tier, direction, category, note, display, metres)
            )
    return used


def _adjustment_entry(adjustment_id, tier, direction, category, note, display, metres) -> dict:
    """One entry of `adjustments_used`. The why is null where the table holds none: a
    hidden or unapproved adjustment, which the writer never fills."""
    return {
        "adjustment_id": adjustment_id,
        "tier": tier,
        "adjusted": True,
        "length_m": round(float(metres), 1),
        "direction": direction,
        "category": category,
        "public_note": note,
        "display": display,
    }


# The map snap `trace_leg` falls back to looks this far from each point for an edge (audit
# round 3, S29): the leg's shape is the router's own, so it lies on the graph, and Valhalla's
# default 50 m only made each match slower. A snap refused at this radius is asked again at the
# default, so no leg's stress is lost to it. GPX matching (core.map_match, core.follow) keeps
# its own 50 m: a rider's track is not on the graph.
TRACE_SNAP_RADIUS_M = 10
# The matches `trace_leg` asks for, in turn: (shape_match, trace_options or None).
TRACE_MATCHES: tuple[tuple[str, dict | None], ...] = (
    ("edge_walk", None),
    ("map_snap", {"search_radius": TRACE_SNAP_RADIUS_M}),
    ("map_snap", None),
)


def trace_leg(variant: str, costing: dict, shape: str, deadline: Deadline) -> dict | None:
    """The leg's edges, by edge walk, then by a close map snap, then by a plain one; None if
    none works."""
    for match, options in TRACE_MATCHES:
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
        if options is not None:
            payload["trace_options"] = options
        try:
            return _call(variant, "trace_attributes", payload, deadline)
        except RouterRefused as refusal:
            logger.info(
                "trace_attributes %s%s refused on %s: %s",
                match,
                "" if options is None else f" {options}",
                variant,
                refusal,
            )
    return None


def busy_and_waits(
    variant: str, costing: dict, shape: str, when: str, deadline: Deadline
) -> tuple[float, float] | None:
    """One routed leg's metres on busy roads (LTS 3 and up, Avoid included) and its junction
    waits in seconds (`routemaker.junction_delay`, which `plan` adds to its time), read from
    its trace as `plan` reads a route's; None where it could not be traced. For the transit
    ride types' candidate rides (core.transit), which are routed without a trace."""
    from .flashing_signals import active as active_beacons

    trace = trace_leg(variant, costing, shape, deadline)
    if trace is None:
        return None
    stress, _facility = breakdown(pieces_of_trace(trace), when)
    junctions = trace_junctions.junctions_of_trace(trace, decode_polyline6(shape), 0.0)
    beacons = active_beacons()
    waits = junction_delay.delay_s(
        junctions,
        stop_as_yield,
        lambda lon, lat: intersections.beacon_at(lon, lat, beacons) is not None,
    )
    return stress["3"] + stress["4"] + stress["5"], float(waits)


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
    # Off by default: the answer lists EVERY junction with its cost (`junctions_debug`),
    # flagged or not, for re-running a sample with all junctions counted (468).
    debug_junctions: bool = False
    # Mountain Bike only: the hardest trail level the rider takes, 1-4 (docs/MTB-TOPO-PLAN.md,
    # slice 6); None: `routemaker.mtbmode.DEFAULT_MAX_LEVEL`, level 2.
    mtb_level: int | None = None
    # Mountain Bike only, the second pass: the trail level the rider prefers, 1-4, never above
    # `mtb_level` (`mtbmode.preferred_level`); None: level 2, or `mtb_level` where that is lower.
    mtb_preferred: int | None = None
    # v0.7.0 "Route through anyway": the closures this plan routes through (their ids).
    closure_bypass: tuple[str, ...] = ()
    # A dirt trail a point is on is ridden on a ride type that does not plan on them
    # (`core.trail_touch`); False plans on the ride type's own graph alone. Set by `plan`.
    trail_touch: bool = True
    # The dirt trails each point touches, in order, once looked up (None: not yet). Set by
    # `plan`.
    trail_touched: tuple[frozenset[int], ...] | None = None
    # A ride's re-plan: the first point is the rider, so a dirt trail there counts, and any
    # dirt trail may be ridden (`core.trail_touch`). `dirt_ridden`: the rider has been on one
    # this ride, so any may be ridden wherever the rider is now.
    ride_replan: bool = False
    dirt_ridden: bool = False
    # With `ride_replan`: the rider marked a dirt trail closed earlier this ride (an answer's
    # `dirt_closed`), so no dirt trail is ridden, whatever `blocked` still holds.
    dirt_closed: bool = False
    # The dirt trails such a plan found for itself, each a short strip across it (a ring),
    # left out as `blocked` is. Set by `plan`.
    trail_strays: tuple[tuple[tuple[float, float], ...], ...] = ()
    # v0.9.1, Go and a ride: DDOT's permits, which say a road may be closed
    # (`routemaker.workzones.possible`), left off the answer. A plan flags them only.
    closures_now: bool = False
    # v0.8.2, Ride's "Road closed" button: stretches of road the rider found closed on this
    # ride, each a line of (lon, lat), left out of every request the plan makes.
    blocked: tuple[tuple[tuple[float, float], ...], ...] = ()
    # Via points (v0.7.0, "Via points vs stops"): the indices of the rider's points that
    # only shape the route. The router passes them without a U-turn or a stop
    # (`VIA_LOCATION_TYPE`); every other point is a stop ("break"), as before.
    vias: tuple[int, ...] = ()
    # The pace the plan's costing rides at instead of the ride type's own (km/h); None: its
    # own. Set by the rider's Riding speed (`presets.rider_speed`), and by a transit trip's lines
    # priced as Novice on a share bike (`api._transit_body`, `novice_legs` on Bikeshare + Transit),
    # so the lines are timed as its candidates were.
    cycling_speed_kmh: float | None = None
    # Novice and Nervous's walks past a short busy stretch (`core.novice_walks`); off for a
    # transit trip's lines priced as Novice (`novice_legs`), which say no walks.
    novice_walks: bool = True
    # An opened file's line to follow exactly, [(lon, lat), ...] (`core.follow`); None: plan.
    follow: tuple[tuple[float, float], ...] | None = None
    # Follow it exactly, rules or not (`core.follow.EXACT`): the manual mode.
    follow_exact: bool = False
    # Plan's manual mode (v0.9.1): the legs the rider drew as straight lines, by index (leg i
    # runs from point i to point i + 1); the others are routed (`_drawn`).
    straight: tuple[int, ...] = ()
    # "Make it a loop" (OWNER-DECISIONS 266): return to the start by a different way.
    # A ride whose last point is its first is a loop whatever this says.
    loop: bool = False
    # A ride's re-route: the way the rider is going at the first point (degrees clockwise from
    # north), so the route sets off that way rather than turning round (`plan_onward`); None:
    # either way.
    heading: float | None = None
    # A re-route after the rider has ridden on past two U-turns (the owner, 2026-10-20: "give two
    # reroutes and on the third time assume that the user wants to stay on that path"): the route
    # that sets off ahead is taken whatever turning round would save (`plan_onward`).
    ahead_only: bool = False
    # Mass Ride's "Anticipated ride size" (PLAN items 128, 129), riders: the capacity a road
    # needs, which the route choice prices (`choose_by_capacity`); None: 500.
    ride_size: int | None = None


def _same_pace(options: dict, request: dict) -> dict:
    """`options` (a fresh `presets.costing`) at the pace `request` is routed at, so a derived
    request (the detour probe, the target fit, the middle of the hills) times its route as the
    plan's own does (`Dials.cycling_speed_kmh`)."""
    speed = ((request.get("costing_options") or {}).get("bicycle") or {}).get("cycling_speed")
    if speed is not None:
        options["bicycle"]["cycling_speed"] = speed
    return options


# How a via point is sent to the router (v0.7.0, "Via points vs stops"). The plan names
# Valhalla's "through" (no forced stop, no U-turn). "break_through" is the same at the
# point itself (no U-turn) but keeps the leg there, so the answer keeps one leg per point
# and every per-leg figure (`leg_ends`, the calm search's legs, the stop list's distances)
# lines up with the rider's points as before; the page does not announce or number a via
# point, and the description lists it as "Via point at ..." and reads the turn at it as
# any other (`via_boundaries`, round-3 audit D29), so nothing reads it as a stop.
VIA_LOCATION_TYPE = "break_through"


def location_type(index: int, count: int, vias: tuple[int, ...]) -> str:
    """The router's type for the rider's point `index` of `count`: a via point's
    (`VIA_LOCATION_TYPE`) where the point is one and not an end, else a stop's."""
    if 0 < index < count - 1 and index in vias:
        return VIA_LOCATION_TYPE
    return "break"


def via_boundaries(count: int, vias, legs: int) -> tuple[int, ...]:
    """The leg boundaries the route rides through at a via point, for the description
    (`describe_route`), each by the number of the leg it begins: the rider's point there,
    one of `vias` (`location_type`). Empty where the answer's legs are not one per gap
    between the `count` points, as then a boundary is not known to be a point's."""
    if legs != count - 1:
        return ()
    return tuple(sorted(i for i in set(vias or ()) if 0 < i < count - 1))


# Novice and Nervous (v0.7.0 plan): real LTS 3 or worse along the bike route past this
# (metres, about a block, so a crossing of a busy road is not counted as riding on it), or a
# route held at the ceiling, offers transit and bikeshare beside it (`novice_note`).
NOVICE_BUSY_SLACK_M = 80.0


def busiest_stretch(pieces: list, classes: list) -> dict | None:
    """The longest run of real LTS 3 or worse along a route, by the road's name: its name
    (None where the road has none), its metres, its worst level, and where it begins and
    ends (`from` and `to`, [lon, lat], the middles of its first and last pieces, near
    enough for the stations around them; v0.11.0, the transit hop past it,
    `transit.plan_bike`'s `hop`). None where there is no such run."""
    runs: list[list] = []  # [name, metres, worst, first piece, last piece]
    last = None
    for piece, cls in zip(pieces, classes, strict=False):
        tier = cls[0]
        busy = tier in ("3", "4", "5")
        if not busy:
            last = None
            continue
        names = getattr(piece, "names", None) or ()
        name = names[0] if names else None
        if last is not None and last[0] == name:
            last[1] += piece.metres
            last[2] = max(last[2], int(tier))
            last[4] = piece
        else:
            last = [name, piece.metres, int(tier), piece, piece]
            runs.append(last)
    if not runs:
        return None
    name, metres, worst, first, final = max(runs, key=lambda run: run[1])
    return {
        "name": name,
        "metres": round(metres, 1),
        "level": worst,
        "from": [round(first.lon, 6), round(first.lat, 6)],
        "to": [round(final.lon, 6), round(final.lat, 6)],
    }


def novice_note(
    stress_m: dict,
    calm_search: dict | None,
    busiest: dict | None,
    walked_m: float = 0.0,
    walks: list[dict] | None = None,
) -> dict:
    """Novice and Nervous's reading of its own route (v0.7.0 plan, item 4): its real LTS 3
    and worse metres ridden, the busiest stretch ridden, whether the search was held at the
    ceiling, and whether to offer Own bike + Transit and Bikeshare + Transit beside it. The
    busy stretches walked instead (v0.11.0, `core.novice_walks`: `walked_m` of them, the
    walks themselves in `walks`) are not ridden, and are left out of the busy metres."""
    busy_m = max(0.0, sum(float(stress_m.get(key, 0.0)) for key in ("3", "4", "5")) - walked_m)
    held = bool(calm_search) and (calm_search or {}).get("limited") == "ceiling"
    return {
        "busy_m": round(busy_m, 1),
        "busiest": busiest,
        "over_ceiling": held,
        "transit": busy_m > NOVICE_BUSY_SLACK_M or held,
        "walked_m": round(walked_m, 1),
        "walks": walks or [],
    }


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
# The Mountain Bike router (`Variant.MTB`, docs/MTB-TOPO-PLAN.md, slice 6), a sixth behind the
# same profile, falls back the same way: the ride is then planned on the standard graph and
# its answer says so (`mtb.limited` = no_mtb_graph).
_mtb_failed_at: float | None = None
TWIN_VARIANTS = (Variant.WEEKEND.value, Variant.OFFROAD.value, Variant.MTB.value)


def _weekend_down() -> bool:
    return _weekend_failed_at is not None and clock() - _weekend_failed_at < WEEKEND_FAILURE_TTL_S


def _offroad_down() -> bool:
    return _offroad_failed_at is not None and clock() - _offroad_failed_at < WEEKEND_FAILURE_TTL_S


def _mtb_down() -> bool:
    return _mtb_failed_at is not None and clock() - _mtb_failed_at < WEEKEND_FAILURE_TTL_S


def _twin_down(variant: str) -> bool:
    if variant == Variant.MTB.value:
        return _mtb_down()
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


def _mtb_is_promoted() -> bool:
    return _promoted_row(Variant.MTB.value)


def _is_promoted(variant: str) -> bool:
    if variant == Variant.MTB.value:
        return _mtb_is_promoted()
    if variant == Variant.OFFROAD.value:
        return _offroad_is_promoted()
    return _weekend_is_promoted()


def _mark_weekend(ok: bool) -> None:
    global _weekend_failed_at
    _weekend_failed_at = None if ok else clock()


def _mark_twin(variant: str, ok: bool) -> None:
    global _offroad_failed_at, _mtb_failed_at
    if variant == Variant.MTB.value:
        _mtb_failed_at = None if ok else clock()
    elif variant == Variant.OFFROAD.value:
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


def refine_flat_speed_ms(costing: dict) -> float:
    """`refine.flat_speed_ms`: the request's flat riding speed, metres a second."""
    from . import refine

    return refine.flat_speed_ms(costing)


def _quiet_cost(costing: dict) -> float:
    """`refine.quiet_cost_per_m`: the router's cost of a quiet metre at this costing."""
    from . import refine

    return refine.quiet_cost_per_m(costing)


def _router_cost(trip: dict) -> float:
    """Valhalla's own cost of a trip: its time with every cost-only penalty
    the request priced in (the stress penalty, the tier-5 entry charge, the
    grade penalty, maneuvers, gates). A body without it (an older router)
    falls back to the time."""
    summary = trip.get("summary") or {}
    return float(summary.get("cost", summary.get("time", 0.0)))


@dataclass(frozen=True)
class HillPrice:
    """What the route choice needs to price a trip's climbing (`hill_s`): the rider's system
    weight and flat speed, the hills slider's position (which sets the LT1 grade,
    `hill_cost.lt1_grade_for`), the request's `use_hills` (whose router charge is taken off),
    and, on the avoid half, the weight of the sustained-descent cost past the ride type's
    brake grade (`climbs.descent_cost_s`)."""

    mass_kg: float
    flat_ms: float
    hills: int
    use_hills: float
    descent_weight: float = 0.0
    brake_grade: float | None = None
    # A Mass Ride's or a Novice and Nervous ride's price for steep grades either way
    # (`routemaker.steep_grades`, the owner, 2026-10-26).
    steep: bool = False


def rider_hill_s(trip: dict, price: HillPrice, quiet_cost: float) -> float:
    """What a trip's climbing and steep descents cost the rider, in the router's cost
    seconds: the climbs' extra time plus their steepness penalty past the LT1 grade the
    slider sets (`hill_cost.hill_cost_m`, the owner, 2026-10-23: "always assume time
    equivalent, but the slider should determine a further penalty for steepness"), plus the
    avoid half's descent cost, and on a Mass Ride or a Novice and Nervous ride the steep
    grades' price (`routemaker.steep_grades`)."""
    profile = grade_profile(trip)
    rider_m = hill_cost.hill_cost_m(profile, price.mass_kg, price.flat_ms, price.hills)
    if price.steep:
        rider_m += steep_grades.penalty_s(profile) * price.flat_ms
    descents = sum(
        climbs.descent_cost_s(run, price.brake_grade)
        for run in climbs.runs(profile)
        if run.rise_m < 0
    )
    return quiet_cost * rider_m + price.descent_weight * descents


def hill_s(trip: dict, price: HillPrice, quiet_cost: float) -> float:
    """What a trip's climbing adds to its router cost once the router's own climbing charge
    (`climbs.router_climb_m`) is swapped for the rider's (`rider_hill_s`): negative where
    the router charged more than the rider pays."""
    charge_m = climbs.router_climb_m(grade_profile(trip), price.use_hills)
    return rider_hill_s(trip, price, quiet_cost) - quiet_cost * charge_m


def choose_by_hills(trips: list[dict], price: HillPrice, quiet_cost: float) -> int:
    """The index of the trip whose router cost, with its climbing priced as the rider pays
    it (`hill_s`), is least: both halves of the hills slider on every ride type but
    Mountain Goat (whose right half seeks climbs, `choose_climb`). Toward "fine with hills"
    the LT1 grade rises, so a climb costs little more than its time and the shorter or more
    direct route wins where it is about as quick; toward avoid the grade falls and the
    steepness penalty grows. The stress, turn and gate
    prices stay. The first trip, the router's own best, is kept unless another saves more
    than HILLS_EPS_S (the elevation samples' noise).
    """
    best, best_score = 0, None
    for index, trip in enumerate(trips):
        score = _router_cost(trip) + hill_s(trip, price, quiet_cost)
        if best_score is None or score < best_score - HILLS_EPS_S:
            best, best_score = index, score
    return best


def choose_by_steep(trips: list[dict], price: HillPrice, quiet_cost: float) -> int:
    """The index of the trip whose router cost plus its steep grades' price
    (`routemaker.steep_grades`) is least: a Mass Ride or Novice ride where the hills slider
    does not price climbing itself. The router's own route is kept unless another saves more
    than HILLS_EPS_S."""
    best, best_score = 0, None
    for index, trip in enumerate(trips):
        steep_m = steep_grades.penalty_s(grade_profile(trip)) * price.flat_ms
        score = _router_cost(trip) + quiet_cost * steep_m
        if best_score is None or score < best_score - HILLS_EPS_S:
            best, best_score = index, score
    return best


# What an alternative must save, in the router's cost seconds, for the hills choice to take
# it over the router's own route: a few seconds is the elevation samples' noise.
HILLS_EPS_S = 5.0


def capacity_stretches(
    variant: str,
    costing: dict,
    trip: dict,
    when: str,
    deadline: Deadline,
    traces: dict | None = None,
    names: bool = False,
) -> list[tuple] | None:
    """A trip's Mass Ride stretches (`_flow_stretches`: metres, usable width, note; with
    `names` its street name fourth), read as the answer reads them; None where a leg cannot
    be traced."""
    prefetch_traces(variant, costing, [trip], deadline, traces)
    pieces: list[Piece] = []
    for leg in trip.get("legs") or []:
        trace = _trace(variant, costing, leg.get("shape", ""), deadline, traces)
        if trace is None:
            return None
        pieces.extend(trace_reading(trace)[0])
    classes = classify(pieces, when, roadway_only=True)
    capacity = _has_capacity_column(validate_schema_name(settings.SEGMENT_SCHEMA_LIVE))
    outside = [_outside_dc(piece) for piece in pieces]
    found = _flow_stretches([(0, len(pieces))], pieces, classes, capacity, outside)
    if names:
        found = _named(found, [(0, len(pieces))], pieces)
    return found


def _mass_capacity(
    stretches: list[tuple],
    profile: dict | None,
    length_m: float,
    riders: int,
    choice: dict | None,
) -> dict | None:
    """The answer's `mass_capacity`: what the route carries against what the ride size needs,
    where it falls short, and the corkers it needs (`routemaker.mass_route`); None where it
    cannot be read (the route is answered without it)."""
    try:
        priced = mass_route.price(stretches, riders)
        narrowest = priced.narrowest_riders_per_min
        return {
            "riders": riders,
            "need_riders_per_min": priced.need_per_min,
            "hold_minutes": mass_route.HOLD_MINUTES,
            "narrowest_riders_per_min": None if narrowest is None else round(narrowest),
            "narrowest_m": None if priced.narrowest_m is None else round(priced.narrowest_m),
            "below_need_m": round(priced.below_need_m),
            "capacity_changes": priced.transitions,
            "capacity_price_s": round(priced.total_s, 1),
            "narrow_stretches": mass_route.narrow_stretches(stretches, priced.need_per_min),
            "corkers": mass_route.corker_load(profile, length_m, riders),
            "choice": choice,
        }
    except Exception:  # noqa: BLE001 - the route is answered without its capacity summary
        logger.warning("the Mass Ride capacity summary could not be built", exc_info=True)
        return None


def _named(stretches: list[tuple], leg_runs: list, pieces: list[Piece]) -> list[tuple]:
    """`_flow_stretches`' stretches with each one's street name fourth (None on a leg that
    was not traced, or an unnamed way), for the answer's narrow stretches."""
    names: list[str | None] = []
    for run in leg_runs:
        if isinstance(run, tuple):
            names.extend(
                (pieces[i].names[0] if pieces[i].names else None) for i in range(run[0], run[1])
            )
        else:
            names.append(None)
    return [(*stretch, name) for stretch, name in zip(stretches, names, strict=True)]


def choose_by_capacity(
    trips: list[dict],
    hill_part: Callable[[dict], float],
    riders: int,
    variant: str,
    costing: dict,
    when: str,
    deadline: Deadline,
    traces: dict | None = None,
) -> tuple[int, dict | None]:
    """A Mass Ride's choice among the router's routes by road capacity (PLAN "Mass Ride map
    and mode", items 120-123, 128; `routemaker.mass_route`): the index of the trip whose router
    cost plus its climbing (`hill_part`) plus its capacity price for a group of `riders` is
    least, and what was weighed. The router's own route is kept unless another saves more than
    HILLS_EPS_S. Busier roads are not held against an alternative: a Mass Ride is corked and
    judged by what a road carries, not its LTS (OWNER-DECISIONS 125, 325). Where the router's
    own route cannot be read in time, (0, None): the caller chooses as before; an alternative
    that cannot be read is passed over."""
    prefetch_traces(variant, costing, trips, deadline, traces)
    best, best_score = 0, None
    weighed: list[dict] = []
    for index, trip in enumerate(trips):
        try:
            stretches = capacity_stretches(variant, costing, trip, when, deadline, traces)
        except (DeadlineExceeded, RouterUnavailable):
            stretches = None
        except Exception:  # noqa: BLE001 - a reading that fails costs the choice, not the plan
            logger.warning("a Mass Ride route could not be read for capacity", exc_info=True)
            stretches = None
        if stretches is None:
            if index == 0:
                return 0, None
            continue
        priced = mass_route.price(stretches, riders)
        score = _router_cost(trip) + hill_part(trip) + priced.total_s
        weighed.append(
            {
                "route": index,
                "capacity_s": round(priced.total_s, 1),
                "narrow_s": round(priced.narrow_s, 1),
                "transitions": priced.transitions,
                "below_need_m": round(priced.below_need_m),
            }
        )
        if best_score is None or score < best_score - HILLS_EPS_S:
            best, best_score = index, score
    return best, {"riders": riders, "routes_weighed": weighed, "chosen": best}


def _trace(
    variant: str, costing: dict, shape: str, deadline: Deadline, traces: dict | None = None
) -> dict | None:
    """`trace_leg`, remembered in `traces` (one plan's) so that a route traced
    for a guard is not traced again for the answer. A trace that raised is not
    remembered."""
    if traces is None:
        return trace_leg(variant, costing, shape, deadline)
    key = _trace_key(variant, costing, shape)
    if key not in traces:
        traces[key] = trace_leg(variant, costing, shape, deadline)
    prefetched = isinstance(traces[key], Future)
    try:
        return _settled(traces, key)
    except DeadlineExceeded:
        # A trace prefetched for a step held to a shorter deadline than this reader's (the
        # middle-of-the-hills check runs to its own, `_middle_or_avoid`): its running out is
        # not this reader's. Asked again inline, within this reader's own budget.
        if not prefetched or deadline.at - clock() <= 0:
            raise
    traces[key] = trace_leg(variant, costing, shape, deadline)
    return traces[key]


def _trace_key(variant: str, costing: dict, shape: str) -> tuple:
    return (variant, shape, json.dumps(costing, sort_keys=True))


def _settled(traces: dict, key):
    """`traces[key]`, waiting for it where it is still being asked for on the pool
    (`prefetch_traces`). One that raised is not remembered, as before: the error is
    raised here, once, to the reader that would have asked for it."""
    value = traces[key]
    if isinstance(value, Future):
        try:
            value = await_future(value)
        except BaseException:
            if traces.get(key) is value:
                del traces[key]
            raise
        traces[key] = value
    return value


def prefetch_traces(
    variant: str,
    costing: dict,
    trips: list[dict],
    deadline: Deadline,
    traces: dict | None,
    at_least: int = 2,
) -> None:
    """Start the traces of `trips`' legs together on the pool (`core.parallel`, v0.7.0
    step 3), so the reader that walks them one by one (`_trace`) finds them asked for
    already. Only legs not asked for yet; nothing where the pool is off, there is no
    plan's `traces` to keep them in, or fewer than `at_least` legs are wanted (one leg
    alone is asked inline, unless something else runs beside it). Each call keeps the
    plan's deadline."""
    if traces is None or not parallel.enabled():
        return
    wanted: dict[tuple, str] = {}
    for trip in trips:
        for leg in (trip or {}).get("legs") or []:
            if leg.get("drawn"):
                continue
            shape = leg.get("shape", "")
            key = _trace_key(variant, costing, shape)
            if key not in traces and key not in wanted:
                wanted[key] = shape
    if not wanted or len(wanted) < at_least:
        return
    for key, shape in wanted.items():
        traces[key] = parallel.submit(trace_leg, variant, costing, shape, deadline)


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
    when a leg cannot be traced. A half step counts as the calm search counts it, at
    its midpoint (`refine.half_exposure_m`, `refine.stress_totals`; review RL-7)."""
    from . import refine

    prefetch_traces(variant, costing, [trip], deadline, traces)
    pieces: list[Piece] = []
    for leg in trip.get("legs") or []:
        trace = _trace(variant, costing, leg.get("shape", ""), deadline, traces)
        if trace is None:
            return None
        pieces.extend(trace_reading(trace)[0])
    classes = refine.shift_classes(classify(pieces, when), exposure.shift)
    stress = totals(zip(pieces, classes, strict=True))[0]
    halves = refine.half_metres(pieces, classes)
    weights = exposure.weights
    return (
        sum(weights[tier] * stress[tier] for tier in weights)
        + refine.half_exposure_m(halves, weights),
        refine.stress_totals(stress, halves)["lts4_m"],
    )


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
    # Both routes' traces at once (v0.7.0 step 3); read below in the same order.
    prefetch_traces(variant, costing, [trips[0], trips[chosen]], deadline, traces)
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
        _skipped_for_time()
        return trip, False
    middle_request = {key: value for key, value in request.items() if key != "alternates"} | {
        "costing_options": middle_costing
    }
    # The hill-avoiding route's own trace runs beside the middle's /route (v0.7.0 step 3).
    prefetch_traces(variant, costing, [trip], step, traces, at_least=1)
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


def _trip_line(trip: dict) -> list[tuple[float, float]]:
    """A trip's line, its legs joined."""
    line: list[tuple[float, float]] = []
    for leg in trip.get("legs") or []:
        shape = decode_polyline6(leg.get("shape", ""))
        line.extend(shape[1:] if line else shape)
    return line


def hill_seek(
    trips: list[dict],
    points: list,
    request: dict,
    variant: str,
    deadline: Deadline,
    ratio: float,
    avoid_gravel: bool = False,
):
    """The hill seek (`core.hillseek`, FOLLOWUP-HILL-SEEK, OWNER-DECISIONS 205): routes
    through the categorised climbs near the line, within `ratio` of the router's own
    route, for the climb search to choose among with the router's own. Each is one
    /route with the climb's points as `through` locations, inside the seek's own
    budget and short of the answer's traces; a route the router has none for is
    skipped, and a router out of time ends the seek."""
    from . import hillseek

    stop_at = min(clock() + hillseek.SEEK_BUDGET_S, deadline.at - hillseek.TRACE_RESERVE_S)
    plain = {key: value for key, value in request.items() if key != "alternates"}
    locations = plain.get("locations") or []

    def ask(vias: list) -> dict | None:
        trial = dict(plain)
        trial["locations"] = [
            locations[0],
            *({"lon": lon, "lat": lat, "type": "through"} for lon, lat in vias),
            locations[-1],
        ]
        call = Deadline(stop_at, min(deadline.per_call_s, ALTERNATES_TIMEOUT_S))
        try:
            answer = _call(variant, "route", trial, call)
        except RouterRefused:
            return None
        except (DeadlineExceeded, RouterUnavailable) as error:
            raise hillseek.OutOfTime(str(error)) from error
        return answer.get("trip") or None

    return hillseek.seek(
        hillseek.load(),
        (float(points[0][0]), float(points[0][1])),
        (float(points[-1][0]), float(points[-1][1])),
        _trip_length_m(trips[0]) * ratio,
        [_trip_line(trip) for trip in trips],
        ask,
        lambda: stop_at - clock(),
        avoid_gravel=avoid_gravel,
    )


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
    if "shape" in request:
        return _followed(variant, request, Deadline(deadline.at, limit)), False
    if DRAWN_KEY in request:
        return _drawn(variant, request, Deadline(deadline.at, limit)), False
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


def _followed(variant: str, request: dict, deadline: Deadline) -> dict:
    """A followed line's `/trace_route` (`core.follow.request_for`), as one trip along the line:
    its breaks, and its ends where the match stops short of the line's, joined by routes."""
    from . import follow

    line = [(p["lon"], p["lat"]) for p in request["shape"]]
    options = request.get("costing_options") or {}
    exact = follow.is_exact(options)

    def trace_attributes(payload: dict) -> dict:
        return _call(variant, "trace_attributes", payload, deadline)

    around = None
    if not exact:
        # By default the file's stretches against one-way traffic are left out of the match,
        # and the router goes round them (`follow.wrong_way`).
        keep = {i for i, p in enumerate(request["shape"]) if p.get("type") == VIA_LOCATION_TYPE}
        keep |= {0, len(line) - 1}
        found = follow.wrong_way(line, keep, trace_attributes, options)
        if found is not None:
            dropped, around = found
            if dropped:
                shape = [p for i, p in enumerate(request["shape"]) if i not in dropped]
                request = {**request, "shape": shape}
    answer = _call(variant, "trace_route", request, deadline)
    # The router's own way across a gap keeps every rule the ride type rides by.
    bridge = {k: v for k, v in request.items() if k not in follow.TRACE_ONLY}
    bridge["costing_options"] = follow.without_ignored(request.get("costing_options") or {})

    def route_between(a, b) -> dict | None:
        asked = {
            **bridge,
            "locations": [
                {"lon": a[0], "lat": a[1], "type": "break", "radius": STOP_RADIUS_M},
                {"lon": b[0], "lat": b[1], "type": "break", "radius": STOP_RADIUS_M},
            ],
        }
        try:
            legs = (_call(variant, "route", asked, deadline).get("trip") or {}).get("legs") or []
        except (RouterRefused, RouterUnavailable):
            return None
        return legs[0] if len(legs) == 1 else None

    joined = follow.joined(answer, line, route_between, request.get("elevation_interval"))
    joined["against_traffic"] = (
        follow.against_traffic(_trip_line(joined["trip"]), trace_attributes, options)
        if exact
        else around
        if around is None
        else follow.gone_round(around, _trip_line(joined["trip"]))
    )
    return joined


# The key `plan` puts its drawn legs under in the request it hands `_route` (never sent).
DRAWN_KEY = "_straight_legs"
# The pace a drawn leg is timed at where the costing names none: Valhalla's own default
# for each bicycle type (km/h).
BICYCLE_TYPE_KMH = {"Road": 25.0, "Cross": 20.0, "Hybrid": 18.0, "Mountain": 16.0}


def straight_leg(a, b, speed_kmh: float, heights=None) -> dict:
    """A leg drawn by the rider (Plan's manual mode): the straight line from `a` to `b`,
    shaped as a router's leg so the plan reads it as one. Its length is the line's, its
    time at `speed_kmh`; `heights` are its elevations every ELEVATION_INTERVAL_M where they
    are known. `drawn` marks it: it is not traced, so its stress is unknown."""
    from .dedodge import encode_polyline6

    a, b = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
    km = haversine(Point(*a), Point(*b)) / 1000.0
    seconds = km / speed_kmh * 3600.0 if speed_kmh > 0 else 0.0
    leg = {
        "shape": encode_polyline6([a, b]),
        "summary": {"length": km, "time": seconds, "cost": seconds},
        # A start and an arrival, as a router's leg has, and nothing between: no turns.
        "maneuvers": [
            {
                "type": 1,
                "length": km,
                "time": seconds,
                "begin_shape_index": 0,
                "end_shape_index": 1,
            },
            {"type": 4, "length": 0.0, "time": 0.0, "begin_shape_index": 1, "end_shape_index": 1},
        ],
        "drawn": True,
    }
    if heights is not None:
        leg["elevation"] = list(heights)
    return leg


def samples_along(a, b, interval_m: float) -> list[tuple[float, float]]:
    """Points every `interval_m` along the straight line `a`-`b`, its ends included: where a
    router's leg has its elevations (`elevation_interval`)."""
    metres = haversine(Point(*a), Point(*b))
    steps = max(1, round(metres / interval_m)) if interval_m else 1
    return [
        (a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
        for i in range(steps + 1)
    ]


def _heights(variant: str, line: list, deadline: Deadline) -> list | None:
    """The router's elevations of `line`'s points (`/height`), or None where it has none."""
    try:
        answer = _call(
            variant, "height", {"shape": [{"lon": p[0], "lat": p[1]} for p in line]}, deadline
        )
    except (RouterRefused, RouterUnavailable):
        return None
    heights = answer.get("height")
    if not isinstance(heights, list) or len(heights) != len(line):
        return None
    return [h if isinstance(h, (int, float)) and h > -1000 else None for h in heights]


def _drawn(variant: str, request: dict, deadline: Deadline) -> dict:
    """A plan with legs the rider drew (`DRAWN_KEY`, Plan's manual mode), as one trip: each
    drawn leg the straight line between its points (`straight_leg`), each run of the other
    legs one `/route` through its points, as the plan would ask it. One leg per pair of
    points, as `VIA_LOCATION_TYPE` keeps them, so `leg_ends` line up with the points."""
    drawn = set(request[DRAWN_KEY])
    asked = {k: v for k, v in request.items() if k not in (DRAWN_KEY, "alternates")}
    locations = asked["locations"]
    bicycle = (asked.get("costing_options") or {}).get("bicycle") or {}
    speed = bicycle.get("cycling_speed") or BICYCLE_TYPE_KMH.get(
        bicycle.get("bicycle_type", "Hybrid"), BICYCLE_TYPE_KMH["Hybrid"]
    )
    interval = asked.get("elevation_interval")
    # A router that refuses `/height` (its config without the action) is asked once a plan.
    heights_served = True
    legs: list[dict] = []
    i = 0
    while i < len(locations) - 1:
        if i in drawn:
            a = (locations[i]["lon"], locations[i]["lat"])
            b = (locations[i + 1]["lon"], locations[i + 1]["lat"])
            heights = None
            if interval:
                samples = samples_along(a, b, interval)
                heights = _heights(variant, samples, deadline) if heights_served else None
                heights_served = heights is not None
                heights = heights or [None] * len(samples)
            legs.append(straight_leg(a, b, float(speed), heights))
            i += 1
            continue
        j = i + 1
        while j < len(locations) - 1 and j not in drawn:
            j += 1
        # A run's own ends are where it stops: the run before or after a drawn leg starts there.
        run = [dict(location) for location in locations[i : j + 1]]
        run[0]["type"] = run[-1]["type"] = "break"
        answer = _call(variant, "route", {**asked, "locations": run}, deadline)
        legs.extend((answer.get("trip") or {}).get("legs") or [])
        i = j
    summary = {
        key: sum(float((leg.get("summary") or {}).get(key, 0.0)) for leg in legs)
        for key in ("length", "time", "cost")
    }
    return {"trip": {"legs": legs, "summary": summary, "units": "kilometers"}}


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


def _has_walk_column(schema: str) -> bool:
    return segment_info.has_columns(schema, "walk_bike")


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
        with plan_cursor() as cursor:
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


def stop_as_yield(lon: float, lat: float) -> bool:
    """Whether a rider may take a stop sign at this point as a yield sign: inside the
    District, its border roads not included (`routemaker.junction_delay`)."""
    from .mass_tiles import dc_boundary, inside_dc

    west, south, east, north = dc_boundary()[1]
    if not (west <= lon <= east and south <= lat <= north):
        return False
    return inside_dc(lon, lat, tolerance_m=0.0)


def _outside_dc(piece) -> bool:
    """Whether a traced piece lies outside the District (its midpoint; a piece with no
    position is taken as inside)."""
    from .mass_tiles import inside_dc

    lon, lat = getattr(piece, "lon", None), getattr(piece, "lat", None)
    return lon is not None and lat is not None and not inside_dc(lon, lat)


def _flow_stretches(
    leg_runs: list,
    pieces: list[Piece],
    classes: list,
    capacity: bool = False,
    outside: list[bool] | None = None,
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
    estimate from the classifier's lanes. `outside`: each piece's `_outside_dc`, where the
    caller has already read it (audit S20)."""
    out: list[tuple[float, float | None, str | None]] = []
    for run in leg_runs:
        if isinstance(run, tuple):
            for i in range(run[0], run[1]):
                klass = classes[i]
                avoid = flow.is_avoid(klass[0])
                beyond = outside[i] if outside is not None else _outside_dc(pieces[i])
                if avoid or beyond:
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
                note = STRETCH_AVOID if avoid else STRETCH_OUTSIDE_DC if beyond else None
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
                        getattr(classes[i], "half", False) is True,
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
        "oneway": getattr(major, "oneway", None),
        "divided": getattr(major, "divided", False),
        "approach_lanes": getattr(major, "approach_lanes", None),
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
            "level_riders_per_min": None,
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
            # The group's length at a ride size is read from these (PLAN items 128, 139).
            body["level_riders_per_min"] = [
                _int_or_none(level[i]) if level is not None else None for i in keep
            ]
            known = [(round(r), m) for m, r in zip(sample_m, riders, strict=True) if r is not None]
            narrow = min(known, default=None)
            typical = sorted(
                round(r) for r, on in zip(riders, regular, strict=True) if r is not None and on
            )
            body["flow"] = {
                "narrowest_riders_per_min": narrow[0] if narrow else None,
                "narrowest_m": round(narrow[1]) if narrow else None,
                "typical_riders_per_min": typical[len(typical) // 2] if typical else None,
                "cruise_pace_ms": round(flow.CRUISE_PACE_MS, 4),
                "default_level_riders_per_min": round(
                    flow.level_riders_per_min(flow.GROUP_DEFAULT_WIDTH_M), 2
                ),
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


# Valhalla's maneuver types for arriving with the destination on the right or the left
# (`DirectionsLeg_Maneuver_Type`: kDestinationRight 5, kDestinationLeft 6; kDestination 4
# says no side).
_DESTINATION_SIDES = {5: "right", 6: "left"}


def arrival_side_of(trip: dict) -> str | None:
    """Which side of the street the destination is on (v0.7.0 "Go riding fixes" item 5):
    the last leg's destination maneuver, else the destination location's `side_of_street`
    as the router stated it. None where it says neither (a route made of pieces, an older
    router, a destination on the line itself)."""
    try:
        legs = trip.get("legs") or []
        maneuvers = (legs[-1].get("maneuvers") or []) if legs else []
        if maneuvers:
            side = _DESTINATION_SIDES.get(maneuvers[-1].get("type"))
            if side:
                return side
        locations = trip.get("locations") or []
        side = (locations[-1] or {}).get("side_of_street") if locations else None
        return side if side in ("left", "right") else None
    except (AttributeError, IndexError, TypeError):
        return None


def leg_arrival_side(leg: dict) -> str | None:
    """Which side of the street a leg's end is on, from its own destination maneuver
    (round-2 audit D17: every rider point is a break, so every leg ends with one); None
    where the router says no side (a stop on the line itself, a drawn leg, a leg without
    maneuvers)."""
    try:
        maneuvers = leg.get("maneuvers") or []
        return _DESTINATION_SIDES.get(maneuvers[-1].get("type")) if maneuvers else None
    except (AttributeError, IndexError, TypeError):
        return None


# A trail relation names an unnamed way only where its named run is longer than this
# (a quarter mile).
RELATION_NAME_MIN_RUN_M = 1609.344 / 4


def sidepath_names_of(pieces: list[Piece]) -> dict[int, str]:
    """The names of the route's ways that have no name of their own, by way id: the
    name of the trail's route relation the way is in (`segment.trail_name`,
    `pipeline.trail_routes.way_name`), as a `describe.RelationName`, so a change of
    trail on a way named only by its relation is in the description (the owner,
    2026-10-16); else its street-side name (`segment.sidepath_name`,
    `routemaker.facility.side_street_names`). The trail's name comes first, as the map
    labels the way: an unnamed stretch of the Metropolitan Branch Trail beside Blair
    Road was "Blair Road Northwest bike lane", and the ride said "Continue onto
    Metropolitan Branch Trail" where it went on as the trail it already was (the
    owner, 2026-10-27: "why continue"). A relation name is taken only for a named run
    (`trail_run_m`) longer than RELATION_NAME_MIN_RUN_M and never a national or
    international route's (`describe.NATIONAL_ROUTE_NAME`): the table keeps no network
    per way, and an East Coast Greenway connector is not "onto East Coast Greenway";
    such a way keeps its street-side name. Empty where the live
    table has neither column yet (a table built before it) or the query fails: those
    ways are then just "path"."""
    ids = sorted({p.way_id for p in pieces if not p.names and p.way_id})
    if not ids:
        return {}
    try:
        schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
        side = segment_info.has_columns(schema, SIDEPATH_NAME_COLUMN)
        trail = segment_info.has_columns(schema, TRAIL_NAME_COLUMN, TRAIL_RUN_COLUMN)
        if not side and not trail:
            return {}
        # On a road the column names the side path it asks riders to use (review RL-1), never the
        # road itself: only a trail-class way's side-path name describes the way.
        side_sql = f"max({SIDEPATH_NAME_COLUMN}) FILTER (WHERE is_trail_class)" if side else "NULL"
        trail_sql = (
            f"max({TRAIL_NAME_COLUMN}) FILTER (WHERE {TRAIL_RUN_COLUMN} > %s)" if trail else "NULL"
        )
        with plan_cursor() as cursor:
            cursor.execute(
                f"SELECT osm_way_id, {side_sql}, {trail_sql} FROM {schema}.segment "
                "WHERE osm_way_id = ANY(%s) GROUP BY osm_way_id",
                [RELATION_NAME_MIN_RUN_M, ids] if trail else [ids],
            )
            names: dict[int, str] = {}
            for way, side_name, trail_name in cursor.fetchall():
                if trail_name and not describe.NATIONAL_ROUTE_NAME.search(str(trail_name)):
                    names[int(way)] = describe.RelationName(str(trail_name))
                elif side_name:
                    names[int(way)] = str(side_name)
            return names
    except Exception:  # noqa: BLE001 - the description says "path" without them
        logger.warning("the street-side names of unnamed ways could not be read", exc_info=True)
        return {}


def _way_names_of(pieces: list[Piece]) -> dict[int, str]:
    """The names the description gives the route's unnamed ways: the rebuild's street-side
    and trail names (`sidepath_names_of`), then, for an unnamed service road, path or
    sidewalk still without one, the major road it runs beside (`beside_roads.names_of`)."""
    names = sidepath_names_of(pieces)
    try:
        names.update(beside_roads.names_of(pieces, names))
    except Exception:  # noqa: BLE001 - the ways are then just "service road" or "path"
        logger.warning("the roads beside the route's unnamed ways could not be read", exc_info=True)
    return names


def _piece_names(piece: Piece, side_names: dict[int, str]) -> tuple[str, ...]:
    """A piece's names for the description: its own, else its way's in `side_names`; a
    road-beside name (`describe.BesideName`) in place of its own too."""
    side = side_names.get(piece.way_id)
    if side is not None and (not piece.names or isinstance(side, describe.BesideName)):
        return (side,)
    return piece.names


def describe_route(
    leg_runs: list,
    pieces: list[Piece],
    classes: list,
    events: list | None,
    summary: dict,
    walks: list[tuple[float, float]] | None = None,
    side_names: dict[int, str] | None = None,
    through: tuple[int, ...] = (),
) -> tuple[list[dict], list[dict]] | None:
    """The route as words, in full and as an overview (`routemaker.describe`,
    OWNER-DECISIONS 220 and 226): built
    from the pieces and junction events the plan already has, with no router
    call. `side_names` (`sidepath_names_of`) names a piece of a way with no name of
    its own after the street it runs alongside ("9th Street Northwest protected bike
    lane"), or after its trail's route relation (a `describe.RelationName`): a stretch
    named only so is flagged `relation_name`. `through` are the leg boundaries that are
    via points, by the number of the leg each begins (`via_boundaries`): the description
    reads a turn there as anywhere else and numbers the stops among themselves (round-3
    audit D29). None where it could not be built: the route is answered all the same."""
    side_names = side_names or {}
    try:
        # A relation's name that no way of the route carries itself: only that is "by relation".
        own = {n.lower() for piece in pieces for n in piece.names}
        by_relation = frozenset(
            n.lower()
            for n in side_names.values()
            if isinstance(n, describe.RelationName) and n.lower() not in own
        )
        legs: list = []
        for run in leg_runs:
            if isinstance(run, tuple):
                legs.append(
                    [
                        describe.Atom(
                            pieces[i].metres,
                            classes[i][0],
                            classes[i][1],
                            _piece_names(pieces[i], side_names),
                            pieces[i].use,
                            pieces[i].heading_in,
                            pieces[i].heading_out,
                            getattr(classes[i], "unpaved", None),
                            bool(pieces[i].road and pieces[i].road.roundabout),
                            pieces[i].fork,
                            pieces[i].others,
                            pieces[i].prior,
                            bearing=pieces[i].bearing,
                            turn=pieces[i].turn,
                            choice=bool(pieces[i].choice),
                            oneway=getattr(classes[i], "oneway", None),
                            retrace=bool(getattr(pieces[i], "retrace", False)),
                        )
                        for i in range(run[0], run[1])
                    ]
                )
            else:
                legs.append(run)
        length = float(summary.get("length", 0.0)) * 1000.0
        return describe.describe_both(
            legs, events, length or None, walks, by_relation, through=through
        )
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
            "calm_mi": round(intersections.calm_miles(event.cost_ft), 2),
            "calm_km": round(
                intersections.calm_miles(event.cost_ft) * intersections.KM_PER_MILE, 2
            ),
            "group": event.group,
            "time_band": event.time_band,
        }
        for event in events
        if event.flagged
    ]


def _junction_debug_rows(events: list) -> list[dict]:
    """EVERY junction event of a route, flagged or not, with its cost (OWNER-DECISIONS
    468: "an API debug field listing every junction"). Off unless the request sets
    `debug_junctions`. Only route-derived facts: no account, no request detail."""
    return [
        {
            "m": round(event.m),
            "lon": round(event.lon, 6),
            "lat": round(event.lat, 6),
            "kind": event.kind,
            "movement": event.movement.value,
            "control": event.control.value,
            "crossed_tier": event.crossed_tier,
            "cost_ft": round(event.cost_ft),
            "calm_mi": round(intersections.calm_miles(event.cost_ft), 3),
            "calm_km": round(
                intersections.calm_miles(event.cost_ft) * intersections.KM_PER_MILE, 3
            ),
            "text": intersections.calm_text(event.cost_ft),
            "severity": event.severity,
            "flagged": event.flagged,
            "time_factor": event.time_factor,
            "assumed_speed": event.assumed_speed,
            "reason": event.reason,
        }
        for event in events
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
# The least time left for the probe to be asked early, beside the search (`_ask_direct_early`,
# audit S23): the busy-road comparison's and the calm search's trace reserve on top, so a
# plan short of time never gives a router slot to it that the search needs.
EARLY_DIRECT_MIN_S = DETOUR_AVOIDED_MIN_S + 6


def _direct_request(
    request: dict, preset_name: str, dials: tuple
) -> tuple[dict, dict, tuple[str, str]]:
    """The detour check's ask for the most direct legal route (`_detour`): its costing, the
    request, and the key it is remembered by in a plan's traces (OWNER-DECISIONS 265)."""
    _stress_dial, assist, avoid_gravel = dials
    direct_costing = _same_pace(
        presets.costing(preset_name, 0, 0, assist=assist, avoid_gravel=avoid_gravel), request
    )
    direct_request = {
        key: value
        for key, value in request.items()
        if key not in ("alternates", "exclude_locations")
    } | {"costing_options": direct_costing}
    return (
        direct_costing,
        direct_request,
        ("direct-route", json.dumps(direct_request, sort_keys=True)),
    )


def _beyond_allowance(route_m: float, straight_m: float) -> bool:
    """Whether a route of `route_m` is past the detour warning's allowance of the straight
    line, where the direct route is asked for (`_detour`)."""
    return straight_m > 0 and route_m > max(
        straight_m * detour_rules.SILENT_RATIO, straight_m + detour_rules.SILENT_EXTRA_M
    )


def _ask_direct_early(
    first_m: float,
    straight_m: float,
    request: dict,
    variant: str,
    preset_name: str,
    dials: tuple,
    deadline: Deadline,
    traces: dict,
) -> dict[tuple[str, str], Future]:
    """The detour check's direct route started on the pool now, beside the search, where
    its answer will almost surely be wanted (audit S23, round 1's S6 without the
    neighbours): above Default (where `_detour` asks for it), never on a Mass Ride, where
    the router's first route (`first_m`) is already past the allowance (a calmer route is
    longer still), with EARLY_DIRECT_MIN_S to spare, on the pool only. {its key: the
    future}, for `_detour` to read; empty where not asked."""
    if (
        preset_name == "mass-ride"
        or not parallel.enabled()
        or dials[0] <= presets.STRESS_DEFAULT_AT
        or not _beyond_allowance(first_m, straight_m)
        or deadline.at - clock() < EARLY_DIRECT_MIN_S
    ):
        return {}
    _costing, direct_request, direct_key = _direct_request(request, preset_name, dials)
    if direct_key in traces:
        return {}
    future = parallel.submit(
        _call,
        variant,
        "route",
        copy.deepcopy(direct_request),
        Deadline(deadline.at, min(deadline.per_call_s, ALTERNATES_TIMEOUT_S)),
    )
    return {direct_key: future}


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
    early: dict | None = None,
) -> dict | None:
    """How much longer the route is than the most direct legal one, for the
    answer's warning (OWNER-DECISIONS 164; `routemaker.detour`).

    Nothing to say, and no second route asked for, while the route is within
    the allowance of the straight line, which the direct route can only exceed.
    Otherwise the router is asked for the most direct route (the traffic
    tolerant end, the hills detent); where it cannot be had in time, or on a
    Mass Ride, which is the direct route by design, the straight line is the
    reference and only a route twice as long says so. `early`: the direct route
    already asked for (`_ask_direct_early`), by its key, read where the key is this
    request's; a fresh ask where it is not."""
    if not _beyond_allowance(route_m, straight_m):
        return None
    stress_dial = dials[0]
    # At or below Default the rider asked for no calm detour, and the route
    # cannot be more than the straight line's ratio longer than the direct one
    # (1.5 times at most, a note): the second route is asked for from just above
    # Default, or where the route is twice the straight line at any position.
    asked_for_calm = stress_dial > presets.STRESS_DEFAULT_AT or route_m >= (
        detour_rules.STRONG_RATIO * straight_m
    )
    probe = preset_name != "mass-ride" and asked_for_calm
    if probe and deadline.at - clock() < DETOUR_PROBE_MIN_S:
        _skipped_for_time()
        probe = False
    if probe:
        direct_costing, direct_request, direct_key = _direct_request(request, preset_name, dials)
        # Asked once for a plan and its candidate routes (OWNER-DECISIONS 265).
        asked = (early or {}).pop(direct_key, None)
        if direct_key in traces:
            direct, direct_m = traces[direct_key]
        else:
            try:
                answer = (
                    await_future(asked)
                    if asked is not None and not asked.cancelled()
                    else _call(
                        variant,
                        "route",
                        direct_request,
                        Deadline(deadline.at, min(deadline.per_call_s, ALTERNATES_TIMEOUT_S)),
                    )
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
                    prefetch_traces(variant, direct_costing, [direct], deadline, traces)
                    pieces: list[Piece] = []
                    for leg in direct.get("legs") or []:
                        trace = _trace(
                            variant, direct_costing, leg.get("shape", ""), deadline, traces
                        )
                        if trace is None:
                            raise RouterUnavailable("no trace")
                        pieces.extend(trace_reading(trace)[0])
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
        options = _same_pace(
            presets.costing(
                preset_name, position, hills_dial, assist=assist, avoid_gravel=avoid_gravel
            ),
            request,
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


# A stop or the end on a road not open to the public (the owner, 2026-10-29: "It would only be
# routed to if there's a destination that would use those roads. Basically when you set a
# destination: This end point is not typically open to the public, make sure you're authorized
# to go here."). Such roads stay routable as a destination; one the route only passes along
# says nothing. The reasons are `segment.bike_access_reason`'s (core.segment_info.ACCESS_WORDS):
# private or no public access (an `access` or `vehicle` of no, private, permit, restricted or
# military, or `bicycle=private`), a military or secure site, and a farm or forest track with
# no sign it is public.
NOT_PUBLIC_REASONS = ("private", "military", "secured", "track")
NOT_PUBLIC_NOTE = (
    "This end point is not typically open to the public, make sure you're authorized to go here."
)


def not_public_ends(pieces: list[Piece], leg_runs: list, count: int) -> list[dict]:
    """The `point_notes` of the stops and the end whose leg finishes on a road not open to the
    public (NOT_PUBLIC_REASONS): each {index, reason, note}, `index` the point's in the rider's
    `count` points (leg k ends at point k + 1). The start is not one: it is not a destination.
    An untraced leg says nothing."""
    ends: dict[int, int] = {}
    for k, run in enumerate(leg_runs):
        if k + 1 >= count or not isinstance(run, tuple) or run[1] <= run[0]:
            continue
        way = pieces[run[1] - 1].way_id
        if way:
            ends[k + 1] = way
    if not ends:
        return []
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    try:
        if not segment_info.has_columns(schema, "bike_access_reason"):
            return []
        with plan_cursor() as cursor:
            cursor.execute(
                f"SELECT DISTINCT osm_way_id FROM {schema}.segment "
                "WHERE osm_way_id = ANY(%s) AND bike_access_reason = ANY(%s)",
                [sorted(set(ends.values())), list(NOT_PUBLIC_REASONS)],
            )
            closed = {int(row[0]) for row in cursor.fetchall()}
    except Exception:  # noqa: BLE001 - a route is answered without its end notes
        logger.warning("the not-public end roads could not be read", exc_info=True)
        return []
    return [
        {"index": index, "reason": "not_public", "note": t(NOT_PUBLIC_NOTE)}
        for index, way in sorted(ends.items())
        if way in closed
    ]


# A stop the bike cannot be ridden to the door of (the owner, 2026-10-17: "There are some
# cases where people could mark stops on a bike trip that should have a dismount like the
# MLK or FDR memorial. In those cases, we should let them route there, but switch to walk
# mode. You're almost always able to portage your bike."): where the ride ends farther than
# WALK_IN_MIN_M from the point the rider put, the walk from the ride's end to it, on foot,
# is answered beside the route (`walk_in`), up to WALK_IN_MAX_M. Below the minimum the
# rider is there; past the maximum the walk is not the last few steps, and is not offered.
# 60 m (about 200 ft): a geocoded address or a map tap often sits 25-60 m off the street,
# and that is not a walk.
WALK_IN_MIN_M = 60.0
WALK_IN_MAX_M = 800.0
WALK_IN_SPEED_KMH = 4.8  # bikeshare.WALK_SPEED_KMH: walking beside a bike
# The least of the budget a walk-in may start with; it is a few hundred metres on foot.
WALK_IN_MIN_LEFT_S = 1.0
# The most one walk-in call may take, so a slow one leaves the candidates their time.
WALK_IN_CALL_S = 2.0


# A walk past a busy stretch (`novice_walks`) prefers sidewalks and footpaths to the
# road's own edge by this factor (Valhalla's `sidewalk_factor` and `walkway_factor`): a
# sidewalk mapped as its own way is only reached by crossing to it, which a walk that
# starts on the road would otherwise not do.
WALKWAY_PREFERENCE = 0.5


def walk_leg(
    a: list[float], b: list[float], deadline: Deadline, prefer_walkways: bool = False
) -> dict | None:
    """The walk from `a` to `b` on the standard graph's pedestrian costing, as the answer
    carries it, or None where there is none on foot, it is too long, or no time is left.
    `prefer_walkways`: keep to sidewalks and paths where there are (`WALKWAY_PREFERENCE`)."""
    if deadline.at - clock() < WALK_IN_MIN_LEFT_S:
        return None
    pedestrian: dict = {"walking_speed": WALK_IN_SPEED_KMH}
    if prefer_walkways:
        pedestrian["sidewalk_factor"] = WALKWAY_PREFERENCE
        pedestrian["walkway_factor"] = WALKWAY_PREFERENCE
    payload = {
        "locations": [{"lon": p[0], "lat": p[1], "type": "break"} for p in (a, b)],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": pedestrian},
        "directions_type": "none",
        "units": "kilometers",
    }
    try:
        answer = _call(
            Variant.STANDARD.value,
            "route",
            payload,
            Deadline(deadline.at, min(deadline.per_call_s, WALK_IN_CALL_S)),
        )
    except RouterRefused as refusal:
        if refusal.code not in NO_PATH_CODES | NO_EDGE_CODES:
            logger.warning("a walk-in was refused: %s", refusal)
        return None
    except (DeadlineExceeded, RouterUnavailable):
        return None
    legs = (answer.get("trip") or {}).get("legs") or []
    if not legs:
        return None
    metres = float((legs[0].get("summary") or {}).get("length", 0.0)) * 1000.0
    if metres > WALK_IN_MAX_M:
        return None
    shape = decode_polyline6(legs[0].get("shape", ""))
    return {
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in shape],
        },
        "distance_m": round(metres, 1),
        "duration_s": round(float((legs[0].get("summary") or {}).get("time", 0.0)), 1),
    }


# What a walk beside a busy road may be on (`walk_roadside_m`): Valhalla's uses that are
# not a carriageway, and the road classes a walk may follow without a sidewalk.
WALKWAY_USES = frozenset(
    {
        "footway",
        "sidewalk",
        "path",
        "pedestrian",
        "cycleway",
        "pedestrian_crossing",
        "steps",
        "mountain_bike",
        "bridleway",
        "living_street",
        "elevator",
    }
)
MAIN_ROAD_CLASSES = frozenset(
    {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified"}
)
# How far from the walk's line its map-snap fallback may look for an edge: the walk is the
# router's own line, so it lies on the graph, and a small radius keeps it from snapping a
# carriageway walk onto a separately mapped sidewalk beside it, or the other way round.
WALK_SNAP_RADIUS_M = 10


def walk_roadside_m(line: list, deadline: Deadline) -> float | None:
    """The metres of a walk (`walk_leg`'s line) along a main road's carriageway with no
    sidewalk mapped on it, as the standard graph's pedestrian costing traces it; None
    where it cannot be traced or no time is left (`novice_walks`: such a walk is not
    offered)."""
    if len(line) < 2 or deadline.at - clock() < WALK_IN_MIN_LEFT_S:
        return None
    payload = {
        "shape": [{"lon": p[0], "lat": p[1]} for p in line],
        "shape_match": "edge_walk",
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"walking_speed": WALK_IN_SPEED_KMH}},
        "filters": {
            "attributes": ["edge.length", "edge.use", "edge.road_class", "edge.sidewalk"],
            "action": "include",
        },
        "units": "kilometers",
    }
    # By edge walk, and where that is refused by map snap held to WALK_SNAP_RADIUS_M, as
    # `trace_leg` falls back (audit round 3, R6): without it a walk the edge walk could not
    # follow was quietly not offered. Both are held to the walk check's own deadline.
    answer = None
    snap = {"shape_match": "map_snap", "trace_options": {"search_radius": WALK_SNAP_RADIUS_M}}
    for extra in ({}, snap):
        try:
            answer = _call(
                Variant.STANDARD.value,
                "trace_attributes",
                {**payload, **extra},
                Deadline(deadline.at, min(deadline.per_call_s, WALK_IN_CALL_S)),
            )
            break
        except RouterRefused as refusal:
            logger.info("walk trace %s refused: %s", extra.get("shape_match", "edge_walk"), refusal)
        except (DeadlineExceeded, RouterUnavailable):
            return None
    if answer is None:
        return None
    edges = answer.get("edges") or []
    if not edges:
        return None
    metres = 0.0
    for edge in edges:
        if str(edge.get("use") or "") in WALKWAY_USES:
            continue
        if str(edge.get("road_class") or "") not in MAIN_ROAD_CLASSES:
            continue
        if str(edge.get("sidewalk") or "none") in ("left", "right", "both"):
            continue
        metres += float(edge.get("length") or 0.0) * 1000.0
    return round(metres, 1)


def walk_in(
    asked_start: list[float] | None,
    asked_end: list[float] | None,
    line: list,
    deadline: Deadline,
) -> dict | None:
    """The walks at either end of a route whose ride stops short of the point asked
    (`WALK_IN_MIN_M`): from the start asked to where the ride begins, and from where it
    ends to the end asked. None where neither end needs one. A point the planner moved
    (the Zoo's racks) is passed as None: the route goes where it was moved to."""
    if len(line) < 2:
        return None
    found: dict[str, dict | None] = {"start": None, "end": None}
    for key, asked, ride_end, a_to_b in (
        ("start", asked_start, line[0], False),
        ("end", asked_end, line[-1], True),
    ):
        if asked is None:
            continue
        gap = haversine(Point(*asked[:2]), Point(*ride_end[:2]))
        if gap < WALK_IN_MIN_M:
            continue
        a, b = (list(ride_end), list(asked)) if a_to_b else (list(asked), list(ride_end))
        leg = walk_leg(a, b, deadline)
        if leg is not None:
            found[key] = {**leg, "to": "your destination" if a_to_b else "the route"}
    return found if any(found.values()) else None


def walk_in_for(offered: dict, answer: dict) -> dict | None:
    """The answer's walk-in on a route offered beside it (a candidate, the way round an
    Avoid-rated junction) whose ride starts and ends where the answer's does, so the
    walk stays when the rider picks it; None where an end differs (no second walk is
    asked for: the answer's own budget is spent on the candidates)."""
    walk = answer.get("walk_in")
    line, own = offered["geometry"]["coordinates"], answer["geometry"]["coordinates"]
    if not walk or len(line) < 2 or len(own) < 2:
        return None
    for i in (0, -1):
        if haversine(Point(*line[i][:2]), Point(*own[i][:2])) >= WALK_IN_MIN_M:
            return None
    return walk


def circle_park_filter(lon: float, lat: float) -> dict:
    """A trip point inside one of DC's circle parks is never matched to a tunnel
    (`routemaker.circleparks`, owner 2026-10-17): Dupont, Scott and Thomas Circles
    each sit over a road underpass, so a point in the middle of one can lie nearer
    the tunnel below it than the walkways it stands on, and the route would end in
    the underpass instead of in the park. Valhalla's `search_filter` keeps it to
    the ways at street level."""
    if circleparks.contains((lon, lat)):
        return {"search_filter": {"exclude_tunnel": True}}
    return {}


@_own_context
def plan(
    points: list[list[float]],
    preset_name: str,
    long_ride: bool = False,
    started: float | None = None,
    dials: Dials | None = None,
    quick: bool = False,
    candidates: bool = True,
) -> dict:
    """Route through `points` on `preset_name`, returning the contract's body (`_plan`).

    A plan that rides a dirt trail a point touches and found others for itself
    (`StrayTrails`) is made again without them, STRAY_ROUNDS times at most, then on the
    ride type's own graph, the dirt trails closed as before. So it is too where leaving them
    out leaves no route. A round checks the router's own route for strays before its search
    (`_early_strays`, audit S12 part 1), so one that strays there starts the next at once.

    The rounds share their traces and `/locate` answers (audit S12, part 2): a round
    re-plans the whole search with the strays left out, and most of what it traces and
    locates the round before already had. Both are keyed by what was asked (the shape and
    costing; the graph, place and radius), never by the round, so a later round reads
    nothing a different question answered. They are dropped before the final plan on the
    ride type's own graph, which asks other questions and so would only hold them longer
    on the 512M worker.
    """
    # Its stress readings, for its own context only (audit S18), dropped as it ends: a pool
    # task still running after it holds a copy of the context, never the readings.
    memo: dict = {}
    _stress_memo.set(memo)
    # And its readings of each trace (audit S19), the same way.
    readings: dict = {}
    _reading_memo.set(readings)
    try:
        return _plan_rounds(points, preset_name, long_ride, started, dials, quick, candidates)
    finally:
        memo.clear()
        readings.clear()


def _plan_rounds(
    points: list[list[float]],
    preset_name: str,
    long_ride: bool,
    started: float | None,
    dials: Dials | None,
    quick: bool,
    candidates: bool,
) -> dict:
    """`plan`'s rounds."""
    if started is None:
        started = clock()
    dials = dials or Dials()
    traces: dict = {}
    located: dict = {}
    for _round in range(STRAY_ROUNDS):
        try:
            return _plan_round(
                points, preset_name, long_ride, started, dials, quick, candidates,
                traces=traces, located=located,
            )  # fmt: skip
        except StrayTrails as found:
            logger.info("planning again without %s", found)
            dials = dataclasses.replace(
                dials,
                trail_touched=found.touched,
                trail_strays=dials.trail_strays + tuple(map(_ring_tuple, found.rings)),
            )
        except PlanCancelled:
            # A newer plan replaced this one: no round on the ride type's own graph either.
            raise
        except (NoRoute, DeadlineExceeded, RouterUnavailable):
            # Leaving the strays out left no route, or no time for another round: the plan
            # the ride type makes on its own graph, in what is left of the budget.
            if not dials.trail_strays:
                raise
            logger.info("no route without the dirt trails found; planning without dirt trails")
            break
    dials = dataclasses.replace(dials, trail_touch=False, trail_strays=())
    traces.clear()
    located.clear()
    # The earlier rounds' readings too: keyed by trace objects the final round never asks
    # about, and each entry pins its trace, so keeping them would hold every trace above
    # through the final round all the same (review of audit S19). The stress memo stays: it is
    # keyed by the pieces read, which the final round can ask again, and holds no trace.
    readings = _reading_memo.get()
    if readings is not None:
        readings.clear()
    return _plan_round(points, preset_name, long_ride, started, dials, quick, candidates)


def _plan_round(*args, **kwargs) -> dict:
    """`_plan`, with the calm search's early ask for the router's alternatives
    (`refine.ask_alternates_early`) cancelled however the plan ends. The search cancels it
    once it is done with it; where anything between the ask and the search raises (a router
    or database error, the clock), one still queued on the pool is never sent, so beta's
    two router slots never run an ask nobody waits for (review of audit batch 1, S2b). One
    already running ends at its own deadline, as before."""
    early: list[Future] = []
    try:
        return _plan(*args, early=early, **kwargs)
    finally:
        for future in early:
            future.cancel()


def _over_budget(rings) -> bool:
    perimeter, vertices = work_zones.rules.budget_used(rings)
    return perimeter > work_zones.rules.MAX_PERIMETER_M or vertices > work_zones.rules.MAX_VERTICES


def _ring_tuple(ring) -> tuple[tuple[float, float], ...]:
    return tuple((float(lon), float(lat)) for lon, lat in ring)


def _plan(
    points: list[list[float]],
    preset_name: str,
    long_ride: bool = False,
    started: float | None = None,
    dials: Dials | None = None,
    quick: bool = False,
    candidates: bool = True,
    traces: dict | None = None,
    located: dict | None = None,
    early: list[Future] | None = None,
) -> dict:
    """Route through `points` on `preset_name`, returning the contract's body.

    `long_ride` gives the request the long-ride time limits, and `started`
    (from `clock()`) is when the request arrived; the budget runs from then,
    or from now if it is not given. `dials` are the sliders and the ride time.
    `quick` asks for the first good route only (`quick_applies`; v0.7.0, "Faster
    routing" step 2): the answer then says `provisional`. `candidates` False looks for
    no routes to choose from beside the answer (Ride mode's re-plans, review speed-5).
    Raises NoRoute, TooLong, RouterUnavailable, DeadlineExceeded, or KeyError
    for an unknown preset. `traces` and `located` are `plan`'s, shared by its rounds; a
    plan of its own where they are not given. `early` is given the pending early ask for
    alternatives, for `_plan_round` to cancel.
    """
    if started is None:
        started = clock()
    timing.restart()
    dials = dials or Dials()
    asked_points = [list(p) for p in points]
    points, moved_points = move_zoo_points(points)
    moved_indices = {m["index"] for m in moved_points}
    preset = presets.PRESETS[preset_name]
    stress_dial = (
        presets.stress_start(preset_name, dials.carrying) if dials.stress is None else dials.stress
    )
    hills_dial = preset.hills if dials.hills is None else dials.hills
    # The slider's right half (FOLLOWUP-HILLS-TOLERATE, OWNER-DECISIONS 242): it seeks
    # climbs on Mountain Goat only; everywhere else it is "fine with hills".
    right_half = hills_dial > 0 and preset.hills_seek
    seeking = right_half and not preset.hills_tolerate
    tolerating = right_half and preset.hills_tolerate
    maxcalm = presets.maxcalm_for(stress_dial)
    # Seeking hills at the top of the stress slider keeps the stress order and the
    # target; only the effort tiebreak (`refine.level3`) inverts, to prefer climbing
    # (OWNER-DECISIONS 298(3), "Keep stress order + target (Recommended)"). Below the
    # top the slider is the climb search among the router's alternatives, as before.
    calm_seek = seeking and maxcalm
    climb_seek = seeking and not maxcalm
    # "Fine with hills" below the top of the stress slider weighs the router's own
    # alternatives with each climb at its time and no steepness penalty (`choose_by_hills`).
    # At the top the stress order decides and its third level counts each climb's time
    # (`refine.level3`): said as "calm_first".
    calm_tolerate = tolerating and maxcalm
    direct_tolerate = tolerating and not maxcalm
    tolerate_weight = presets.tolerate_weight(hills_dial) if tolerating else 0.0
    # An opened file's line, followed rather than planned (`core.follow`): the router's
    # trace of it is the route, and nothing is searched for beside it. Not where the rider
    # asked for a loop: that is planned, its way back by another way.
    following = dials.follow is not None and not dials.loop
    from . import follow

    # Plan's manual mode (Stephen 2026-10-19, "a 'manual mode' where you can just route
    # directly"): the legs the rider drew are straight lines, the rest routed as asked
    # (`_drawn`). Like a followed line, the route is the rider's own: nothing is searched
    # for beside it. Not on a loop, nor with a line to follow, which is the whole ride.
    drawing = bool(dials.straight) and not following and not dials.loop
    fixed = following or drawing
    # A loop is planned through its start again (OWNER-DECISIONS 266); a followed line is
    # already the whole ride.
    loop = not fixed and loop_wanted(points, dials.loop, preset_name)
    points = loop_points(points, loop)
    # A long calm plan (Trailmaxxing at the top of the slider past the calm
    # search's working span, planned leg by leg) has the long ride's time
    # limits: 50 s in all, under gunicorn's 60 s timeout, as the owner chose
    # for a long ride (2026-09-26). It is the same plan the ordinary budget
    # would cut short after its first legs, and no more than the router calls
    # a long ride makes (docs/OPERATIONS.md, "Long calm plans").
    long_calm = (
        not loop
        and not fixed
        and long_calm_for(
            preset_name, points, stress_dial, long_ride, trails_off=bool(dials.trails_off)
        )
    )
    if long_ride or long_calm:
        budget_s, per_call_s = LONG_PLAN_BUDGET_S, LONG_ROUTER_TIMEOUT_S
    else:
        budget_s, per_call_s = PLAN_BUDGET_S, ROUTER_TIMEOUT_S
    deadline = Deadline(started + budget_s - ANSWER_RESERVE_S, per_call_s)
    # The segment table's reads may run to the end of the whole budget, the answer's own
    # reserve included (`plan_cursor`).
    _plan_ends.set(started + budget_s)
    # The first good route only, where that is a route the rider may be shown (Go,
    # `quick_applies`): the router's own route, its closures, stress and words, with no
    # search after it. The full plan follows it from the client.
    # A followed line is a single router call already: never a first route with more to come.
    quick = quick and not fixed and quick_applies(preset_name, loop, long_ride, long_calm)
    exposure = presets.exposure_for(preset_name, dials.carrying)
    # The approved Avoid-rated junctions (FOLLOWUP-ISECT-AVOID, 307-310, 335), read at
    # request time: empty as shipped.
    # Each of these is read once a request: the answer cache's key read them already where
    # it was made (`route_cache.approval`).
    avoid_list = route_cache.avoid_list()
    # A Mass Ride's rider-marked hazards (FOLLOWUP-MASSRIDE-MAP part 3, 325), read once a plan:
    # empty as shipped, and never read for another ride type (325: "for this mode only").
    hazard_list = route_cache.mass_ride_hazards() if preset_name == "mass-ride" else {}
    # The approved rider ratings of junctions (OWNER-DECISIONS 232), read the same way.
    junction_ratings = route_cache.junction_ratings()
    # The flashing beacons the map has as signals (the owner's and MDOT SHA's), the same way.
    beacons = route_cache.beacons()
    # The rider's target distance counts at the top of the slider only.
    target_m = float(dials.target_distance_m) if dials.target_distance_m and maxcalm else None
    when = dials.when or default_when()
    assist = bool(dials.assist) and preset.assist_speed_kmh is not None
    trails_off = bool(dials.trails_off)
    variant = presets.variant_for_ride(preset_name, when, assist, trails_off)
    # A dirt trail the rider put a stop, via or end on (the owner, 2026-10-20: "Don't plan on
    # the route, but if you enter it or mark a waypoint in it, it will continue to route
    # through"): planned on the off-road graph, where it is open, with this ride type's
    # costing; the dirt trails the plan finds for itself are left out again (`StrayTrails`,
    # `core.trail_touch`). The start alone does not (2026-10-21: "I wouldn't use that as a
    # start for routing unless "opted-in""), but on a ride's re-plan the start is the rider:
    # on a dirt trail, or after one, any dirt trail may be ridden ("If someone goes onto a dirt
    # trail, any reroutes should include dirt"). A dirt trail the rider marked closed on this
    # ride says its conditions are bad: no dirt trail at all for the rest of the ride
    # (2026-10-21: "assume that means bad riding conditions until it's opted back in").
    touched_trails: frozenset[int] = frozenset()
    per_point: tuple[frozenset[int], ...] = ()
    dirt_closed = False
    any_dirt = False
    if (
        variant == Variant.STANDARD.value
        and dials.trail_touch
        and dials.follow is None
        and not dials.straight
    ):
        dirt_closed = dials.dirt_closed or (
            bool(dials.blocked) and trail_touch.closed_on_dirt(dials.blocked)
        )
        if not dirt_closed:
            per_point = dials.trail_touched
            if per_point is None:
                per_point = trail_touch.touched(points)
            # Not the start, nor the start again at the end of a loop or a round trip.
            chosen = per_point if dials.ride_replan else per_point[1:]
            if not dials.ride_replan and len(points) > 1 and is_round_trip(points):
                chosen = chosen[:-1]
            touched_trails = frozenset().union(*chosen)
            any_dirt = dials.ride_replan and (dials.dirt_ridden or bool(per_point[0]))
            if touched_trails or any_dirt:
                variant = Variant.OFFROAD.value
    # Bike lanes are "none" in the breakdown on a ride that takes the roadway (Mass
    # Ride, whose own graph is no-trail), not on every trails-off ride.
    lanes_as_roadway = preset.variant == Variant.NO_TRAIL.value
    avoid_gravel = bool(dials.avoid_gravel)
    costing = presets.costing(
        preset_name, stress_dial, hills_dial, assist=assist, avoid_gravel=avoid_gravel
    )
    if dials.cycling_speed_kmh is not None:
        costing["bicycle"]["cycling_speed"] = float(dials.cycling_speed_kmh)
    if following and dials.follow_exact:
        # The manual mode: the file is followed the way it goes, a one-way ridden against its
        # traffic, a turn the map restricts and a way closed to bicycles (a road the police
        # close for a parade) matched as ridden. Otherwise the ride type's rules hold, and
        # the router goes round where the file breaks them (`_followed`).
        costing["bicycle"].update(follow.EXACT)
    request = {
        "locations": [
            {
                "lon": lon,
                "lat": lat,
                "type": location_type(index, len(points), dials.vias),
                "radius": STOP_RADIUS_M,
                **circle_park_filter(lon, lat),
            }
            for index, (lon, lat) in enumerate(points)
        ],
        "costing": "bicycle",
        "costing_options": costing,
        "elevation_interval": ELEVATION_INTERVAL_M,
        "date_time": {"type": 3, "value": planning_time(when=when)},
        # Maneuvers, without their narrative: the destination maneuver says which side of
        # the street the destination is on (`arrival_side_of`, v0.7.0 "Go riding fixes" 5).
        "directions_type": "maneuvers",
        "units": "kilometers",
    }
    if dials.heading is not None and not following and not loop:
        # Only the ways that set off within HEADING_TOLERANCE_DEG of the rider's heading.
        request["locations"][0].update(
            heading=round(dials.heading) % 360, heading_tolerance=HEADING_TOLERANCE_DEG
        )
    # Live work zones (FOLLOWUP-WORKZONES, 341-349), in force at the ride time: a closure
    # to bicycles is left out of every request this plan makes (the derived requests
    # copy this one), and the zones a rider may pass are weighed once the router has
    # answered (`work_zones.settle_penalties`). None where no refresh has ever run.
    # The roads the rider marked closed on this ride (v0.8.2): left out as a closure is,
    # after the closures' own rings, and kept out where those are let back in. They take
    # the router's polygon budget first (the latest kept), and the closures fit the rest.
    # The strips across dirt trails a plan found for itself (`plan`) are always kept, a few
    # metres each: the rider's own fit beside them, the earliest let go first.
    strips = [[list(p) for p in ring] for ring in dials.trail_strays]
    blocked = work_zones.blocked_rings(dials.blocked)
    while blocked and _over_budget(strips + blocked):
        blocked = blocked[1:]
    blocked = strips + blocked
    zones_plan = work_zones.plan_zones(
        points,
        when,
        bypass=dials.closure_bypass,
        reserve=work_zones.rules.budget_used(blocked),
        now_only=dials.closures_now,
    )
    if zones_plan is not None:
        zones_plan.blocked = blocked
        zones_plan.exclude = list(zones_plan.exclude) + blocked
    if zones_plan is not None and following:
        # The file's line is followed through them: each is warned of in red instead.
        work_zones.drop_exclusions(request, zones_plan)
    elif zones_plan is not None and zones_plan.exclude:
        request["exclude_polygons"] = list(zones_plan.exclude)
    elif blocked:
        request["exclude_polygons"] = list(blocked)
    # Past the detent the hills slider is a climb search among the router's
    # alternatives. Valhalla computes alternatives only between two locations,
    # and not inside a long ride's budget, so anything else keeps the route
    # the detent gives and says so.
    # Below it the slider also weighs sustained climbs and brake-riding
    # descents (routemaker.climbs; the owner, 2026-09-28) among the same
    # alternatives, by `-hills/100`.
    # "Fine with hills" asks for them as the avoid half does, inside its shorter span:
    # it is where the E-bike ride type starts (242).
    avoiding = hills_dial < 0
    seek_limited = "calm_first" if calm_seek or calm_tolerate else None
    if climb_seek or avoiding or direct_tolerate:
        span_limit = SEEK_MAX_SPAN_M if climb_seek else AVOID_MAX_SPAN_M
        if len(points) != 2:
            seek_limited = "two_points"
        elif long_ride or haversine(Point(*points[0]), Point(*points[1])) > span_limit:
            seek_limited = "long_ride"
        elif not quick:
            request["alternates"] = SEEK_ALTERNATES
    # Mountain Bike ranks the router's own routes by its trail rules (`core.mtb`): two-point
    # plans ask for them, as the hills search does.
    if preset_name == mtb.PRESET and len(points) == 2 and not long_ride:
        request.setdefault("alternates", SEEK_ALTERNATES)
    if variant in TWIN_VARIANTS and (_twin_down(variant) or not _is_promoted(variant)):
        logger.info("the %s graph is not being served; planning on the standard graph", variant)
        variant = Variant.STANDARD.value
    # The first router call: the plan's own request, or the trace of the followed line.
    if following:
        asked = follow.request_for(dials.follow, points, request)
    elif drawing:
        asked = {**request, DRAWN_KEY: dials.straight}
    else:
        asked = request
    try:
        try:
            answer, timed_out = _route(variant, asked, deadline)
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
            answer, timed_out = _route(variant, asked, deadline)
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
            answer, timed_out = _route(Variant.STANDARD.value, asked, deadline)
            _mark_twin(variant, False)
            logger.warning(
                "the %s router placed no edge the standard graph could (code %s); "
                "planning on the standard graph",
                variant,
                refusal.code,
            )
            variant = Variant.STANDARD.value
        if timed_out and not (calm_seek or calm_tolerate):
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
        closures_left_out = zones_plan is not None and len(zones_plan.exclude) > len(blocked)
        if not (closures_left_out and refusal.code in NO_PATH_CODES):
            raise NoRoute(str(refusal), no_path=refusal.code in NO_PATH_CODES) from refusal
        # No way round the work zones closed to bicycles: plan through them, each one
        # warned of in red, rather than answer no route (the rider can walk through or
        # choose; `work_zones.drop_exclusions`).
        work_zones.drop_exclusions(request, zones_plan)
        try:
            # The rider's drawn legs stay drawn (`_drawn`).
            again = {**request, DRAWN_KEY: dials.straight} if drawing else request
            answer, timed_out = _route(variant, again, deadline)
        except RouterRefused as again:
            raise NoRoute(str(again), no_path=again.code in NO_PATH_CODES) from again

    timing.mark("route")
    delays = None
    if zones_plan is not None and not fixed:
        answer = work_zones.settle_penalties(
            answer,
            request,
            zones_plan,
            lambda trial: _route(variant, trial, deadline)[0],
            lambda: deadline.at - clock(),
        )
    # This plan's traces, so a route the guards traced is not traced again; `plan`'s, where
    # it re-plans without stray dirt trails, so a later round does not trace them again.
    traces = {} if traces is None else traces
    if (touched_trails or any_dirt) and variant == Variant.OFFROAD.value:
        # The router's own route is checked for stray dirt trails at once, before the search
        # and anything started beside it, so a round that strays starts again without them
        # now instead of after the whole search (audit S12, part 1; the owner, 2026-10-27
        # 7:52 PM ET: "make the banked changes"). Its traces are the plan's, which the search
        # and the answer read again, so a route that does not stray is traced once as before.
        stray = _early_strays(
            answer.get("trip") or {}, variant, costing, deadline, traces, touched_trails, any_dirt
        )
        if stray:
            raise StrayTrails(tuple(stray), per_point)
    if zones_plan is not None and not fixed:
        # What each closure did to this route and the time its detour adds (v0.7.0,
        # "Closures on the map"): the card's "Detour adds about 4 min". It changes no
        # route, so it runs beside the rest of the plan (v0.7.0 "Faster routing", step
        # 3) and is waited for before the closures are written on the answer.
        delays = parallel.submit(
            work_zones.measure_delays,
            answer,
            dict(request),
            zones_plan,
            lambda trial, variant=variant: _route(variant, trial, deadline)[0],
            lambda: deadline.at - clock(),
        )
        timing.mark("zones")
    routed_at = clock()
    trips = [answer.get("trip") or {}] + [
        (alternate or {}).get("trip") or {} for alternate in answer.get("alternates") or []
    ]
    # The calm search's ask for the router's alternatives (`refine._router_alternates`)
    # depends on the request alone: where the search will make it, it starts now on the
    # pool, beside the reading of this route, instead of after it (v0.13.0 routing audit,
    # S2). Not where the plan asked for them itself, nor where the target fitting will
    # ask again with another request (this route is past the target).
    early_alternates = None
    if (
        presets.calm_rate_for(stress_dial) > 0
        and "alternates" not in request
        and len(points) == 2
        and not (quick or fixed or loop or long_calm)
        and not (maxcalm and target_m is not None and _trip_length_m(trips[0]) > target_m)
        and _refine_limit(preset_name, points, long_ride, climb_seek, deadline, long_calm) is None
    ):
        from . import refine

        early_alternates = refine.ask_alternates_early(variant, request, deadline)
        if early_alternates is not None and early is not None:
            early.append(early_alternates.future)
    avoid_weight = -hills_dial / 100 if avoiding else 0.0
    # Steep grades warned of and priced either way (`routemaker.steep_grades`): a Mass Ride
    # and a Novice and Nervous ride, wherever the hills slider sits.
    steep_ride = preset_name in steep_grades.RIDE_TYPES
    # How the route choice prices climbing (`HillPrice`): the rider's weight and speed, the
    # slider's steepness scale, the router's own charge to take off, the avoid half's descents.
    hill_price = HillPrice(
        mass_kg=presets.system_weight_for(preset_name, dials.carrying, dials.system_weight_kg),
        flat_ms=refine_flat_speed_ms(costing),
        hills=hills_dial,
        use_hills=float((costing.get("bicycle") or {}).get("use_hills", 1.0)),
        descent_weight=avoid_weight,
        brake_grade=preset.brake_grade,
        steep=steep_ride,
    )
    # The detour check's direct route depends on the request alone: where it will surely be
    # asked for, it starts now on the pool, beside the search, as the early alternatives do
    # (audit S23). Not on a first route or the rider's own line (no detour check), nor where
    # the target fitting will ask with another request. One not read is cancelled however
    # the plan ends (`_plan_round`; one already running ends at its own deadline).
    early_direct: dict[tuple[str, str], Future] = {}
    if not (quick or fixed or (maxcalm and target_m is not None)):
        early_direct = _ask_direct_early(
            _trip_length_m(trips[0]),
            sum(haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False)),
            request,
            variant,
            preset_name,
            (stress_dial, assist, avoid_gravel),
            deadline,
            traces,
        )
        if early is not None:
            early.extend(early_direct.values())
    # The hill seek (FOLLOWUP-HILL-SEEK, 205): routes through the climbs near the line
    # join the router's own, where the climb search runs at all; without the climbs
    # file it asks nothing and the search is the router's alternatives alone, as before.
    # Not on a round trip (it ends within LOOP_SAME_M of its start): the corridor round
    # a line of no length is a circle, and a route there through a climb is an
    # out-and-back up it and down again, not a ride through it. A loop has its stops
    # (`loop_points`), so it is already a two-point limit; this is the start and end
    # put on one place.
    round_trip = loop or haversine(Point(*points[0]), Point(*points[-1])) <= LOOP_SAME_M
    sought = None
    if climb_seek and seek_limited is None and not round_trip and not quick and not fixed:
        sought = hill_seek(
            trips,
            points,
            request,
            variant,
            deadline,
            presets.seek_distance_ratio(hills_dial),
            avoid_gravel,
        )
        trips = trips + sought.trips
    # A Mass Ride chooses among the router's routes by road capacity for its ride size
    # (`choose_by_capacity`), its climbing priced as the rest of this choice prices it.
    ride_size = mass_route.fit_ride_size(dials.ride_size)
    # The router gives alternatives only between two points and on the avoid half
    # (`AVOID_MAX_SPAN_M`), where a Mass Ride starts: with stops or vias, or a longer span, its
    # route is the router's own and `mass_capacity` only reports on it.
    capacity_choice = None
    if preset_name == "mass-ride" and not fixed and not quick and len(trips) > 1:
        chosen, capacity_choice = choose_by_capacity(
            trips,
            lambda one: hill_s(one, hill_price, _quiet_cost(costing)),
            ride_size,
            variant,
            costing,
            when,
            deadline,
            traces,
        )
    if capacity_choice is not None:
        pass  # chosen by capacity, above
    elif fixed:
        chosen = 0
    elif climb_seek:
        chosen = choose_climb(trips, presets.seek_distance_ratio(hills_dial))
    elif direct_tolerate or avoiding:
        # Never a busier route for it (`calmer_or_own`, "Traffic wins").
        chosen = calmer_or_own(
            trips,
            choose_by_hills(trips, hill_price, _quiet_cost(costing)),
            variant,
            costing,
            when,
            deadline,
            traces,
            exposure,
        )
    elif steep_ride and not calm_tolerate:
        # Elsewhere on the slider a Mass Ride or Novice ride still weighs its steep grades
        # alone (`choose_by_steep`), never a busier route for it.
        chosen = calmer_or_own(
            trips,
            choose_by_steep(trips, hill_price, _quiet_cost(costing)),
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
    # Not on a Mass Ride weighed by capacity: the middle's check is by LTS, which would undo
    # a wider road chosen for the group (OWNER-DECISIONS 125, 325).
    if avoiding and not quick and not fixed and capacity_choice is None:
        middle_costing = _same_pace(
            presets.costing(preset_name, stress_dial, 0, assist=assist, avoid_gravel=avoid_gravel),
            request,
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

    timing.mark("choose")
    refine_limited = _refine_limit(preset_name, points, long_ride, climb_seek, deadline, long_calm)
    if quick:
        refine_limited = "quick"
    elif fixed:
        refine_limited = "follow" if following else "drawn"
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
            else presets.default_ceiling_m(_trip_length_m(trip), preset_name)
        )
    # Routes to choose from beside the answer: at the top of the slider, never on a Mass Ride,
    # and not where the request wants the route alone (a ride's re-plan, review speed-5).
    offering = maxcalm and preset_name != "mass-ride" and candidates
    refine_context = refine.Context(
        variant=variant,
        request=request,
        costing=trace_costing,
        when=when,
        deadline=deadline,
        traces=traces,
        located={} if located is None else located,
        points=points,
        roadway_only=variant == Variant.NO_TRAIL.value,
        lanes_as_roadway=lanes_as_roadway,
        with_facility=_has_facility_columns(validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)),
        group=preset_name == "mass-ride",
        rate=presets.calm_rate_for(stress_dial),
        weight=refine.intersection_weight(stress_dial),
        hills_seek_weight=hills_dial / 100 if calm_seek else 0.0,
        hills=hills_dial,
        # The hill factor's coefficient is the hills slider's (409; the owner: "The sliders
        # control the various coefficients for each component"), 0 at "fine with hills".
        hill_coefficient=grade_stress.coefficient_for(hills_dial),
        brake_grade=preset.brake_grade,
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
        # Up to ALT_MAX routes to choose from (OWNER-DECISIONS 265).
        alternates=refine.ALT_MAX if offering else 0,
        # The router's own alternatives ranked with the calm search's (OWNER-DECISIONS 435):
        # the plan's own, where it asked for them with the request the search starts
        # from (none again where that ask timed out), else asked for by the search.
        # Refitted only where the target fitting asked again (`past`): a route already
        # within the target is the plan's own request, its alternatives already in `trips`.
        rank_alternates=presets.calm_rate_for(stress_dial) > 0,
        router_trips=plan_alternates(request, trips, timed_out, bool(past)),
        early_alternates=early_alternates,
        options=[] if offering and not long_calm else None,
        avoid=avoid_list,
        junction_ratings=junction_ratings,
        beacons=beacons,
        steep_grades=steep_ride,
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
    if len(trip.get("legs") or []) > 1 and not quick and not fixed:
        # A slight price on riding a way twice (the owner, 2026-10-18): each later leg that
        # repeats an earlier one's ways is asked for again (`refine.fewer_repeats`).
        trip, repeat_info = refine.fewer_repeats(trip, refine_context)
        logger.info("fewer repeats: %s", repeat_info)
    refined = None
    # A plan the rider has replaced (`core.plan_cancel`) starts no search.
    check_cancel()
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
    elif refine_context.rate > 0 and not quick and not fixed:
        # A calm search was asked for and could not run: say so.
        refined = {
            "rate": refine_context.rate,
            "rounds": 0,
            "excluded": 0,
            "limited": refine_limited,
        }
    if early_alternates is not None:
        # Not started yet where the search ended before it was wanted: not asked at all.
        early_alternates.future.cancel()
    # Mountain Bike (docs/MTB-TOPO-PLAN.md, slice 6): the rider's hardest trail level held, the
    # trail-seeking ranking and the connecting-road rule, on the route as it now is and the
    # router's own alternatives (`core.mtb.settle`). Before the dodge and Avoid passes, so what
    # they say (`dodges`, `avoid_search`) is said of the route answered; should they change it,
    # it is read again after them (`mtb.reread`). Only on its own graph: a trails-off ride, or
    # one the standard graph answered while the mountain-bike router was down, has no trails
    # to weigh.
    mtb_info = None
    mtb_level_held = preset_name == mtb.PRESET and variant == Variant.MTB.value and not fixed
    if mtb_level_held:
        searched_trip = trip
        trip, mtb_info = mtb.settle(
            # A loop is weighed alone: the router's alternatives are not loops.
            [trip] if loop else trips, trip, request, variant, trace_costing, when,
            deadline, traces,
            dials.mtb_level, points, preferred_level=dials.mtb_preferred,
        )  # fmt: skip
        if trip is not searched_trip:
            # The routes to choose from were near-ties of the route it replaced: none are
            # offered beside a route they were not weighed against (as the Avoid pass).
            refine_context.candidates = refine_context.candidates[:1]
    elif preset_name == mtb.PRESET and not trails_off and not fixed:
        # Trails off is the rider's own choice, said by the answer's `dials`; this is the
        # router not being there.
        mtb_info = {
            "max_level": mtbmode.clamp_level(dials.mtb_level),
            "preferred_level": mtbmode.preferred_level(dials.mtb_preferred, dials.mtb_level),
            "limited": "no_mtb_graph",
        }
    mtb_trip = trip
    # No weaving through side streets beside a busier road unless it buys a
    # meaningful length of calm (OWNER-DECISIONS 272, 273): the main road's stretch
    # replaces such a dodge. A loop's way back is kept as it was made, not to share
    # more of the way out (266). The answer's route alone: the routes to choose from
    # are the search's near-ties, picked again against the answer as it now is
    # (`dedodge.settle`), so the pass's bounds are the plan's.
    dodges = None
    if not loop and not quick and not fixed:
        trip, dodges = dedodge.apply(trip, refine_context)
        dedodge.settle(trip, refine_context, refined, dodges)
    # An Avoid-rated junction still on the answer (307-310, 335): the way round, taken
    # where it is worth 30 minutes a pass and the search did not already weigh it (on
    # Mass Ride and Group Ride, where it adds no LTS 4 and not too much distance; never
    # on a loop), else offered (`core.avoid_junctions`). `searched` is what the search
    # did: at least one round, not cut short.
    avoid_info, avoid_trip = None, None
    if avoid_list and not quick and not fixed:
        searched = (
            refined is not None and (refined.get("rounds") or 0) > 0 and not refined.get("limited")
        )
        trip, avoid_info, avoid_trip = avoid_junctions.settle(
            trip,
            refine_context.request,
            variant,
            preset_name,
            deadline,
            avoid_list,
            searched,
            ctx=refine_context,
            loop=bool(loop),
        )
        if avoid_info is not None and avoid_info["decision"] == "avoided":
            dodges = None
            # The routes to choose from were near-ties of the route it replaced: none
            # are offered beside a route they were not weighed against.
            refine_context.candidates = refine_context.candidates[:1]
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
    if mtb_level_held and mtb_info is not None and trip is not mtb_trip:
        # A dodge taken out, or the way round an Avoid-rated junction, changed the route
        # `mtb.settle` chose: its figures, the over-level warning's among them, are read again
        # from the route answered.
        again = mtb.reread(
            trip, variant, trace_costing, when, deadline, traces, dials.mtb_level,
            dials.mtb_preferred,
        )  # fmt: skip
        if again is not None:
            limited = mtb_info.get("limited")
            if again["over_level_m"] > 1.0 and limited is None:
                limited = "no_way_round"
            mtb_info.update({**again, "limited": limited})

    # A long calm plan searched in legs of its own answers in the plan's legs: the
    # grouping of its search legs into the plan's, the answer's and its candidates'
    # alike (combined correctness review, S1: a candidate kept the search's legs, and
    # its description a "Stop 1" the rider never placed).
    long_info = (refined or {}).get("long") or {}
    plan_groups = long_info.get("stops") if long_info.get("answered") == "legs" else None
    timing.mark("search")

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
        # The side of the street each leg ends on (`leg_arrival_side`), one per leg as
        # `leg_ends`: a stop's side for its cue (round-2 audit D17).
        leg_sides: list[str | None] = []
        # Where each leg begins along the traced length: the stops (and the start,
        # which no crossing lies before), which a Mass Ride's crossing group never
        # spans (OWNER-DECISIONS 247).
        stops_m: list[float] = []
        # Every leg's trace at once (v0.7.0 step 3), read in order below.
        prefetch_traces(variant, trace_costing, [trip], deadline, traces)
        for leg in legs:
            stops_m.append(traced_m)
            shape = decode_polyline6(leg.get("shape", ""))
            coordinates.extend(shape[1:] if coordinates else shape)
            leg_ends.append(len(coordinates) - 1)
            leg_sides.append(leg_arrival_side(leg))
            elevations.extend(leg.get("elevation") or [])
            try:
                # A leg the rider drew follows no road: it is not traced, and its stress is
                # unknown (`_drawn`).
                trace = (
                    None
                    if leg.get("drawn")
                    else _trace(variant, trace_costing, leg.get("shape", ""), deadline, traces)
                )
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
                made, read = trace_reading(trace, shape, edges=True)
                pieces.extend(made)
                leg_runs.append((start, len(pieces)))
                raw_junctions.extend(trace_junctions.junctions_along(read, traced_m))
                traced_m += sum(piece.metres for piece in pieces[start:])
        # The router's seconds along the line, read before a long plan's legs are grouped.
        router_at = time_marks.router_marks(legs, coordinates, leg_ends)
        dirt_trails = False
        if (touched_trails or any_dirt) and variant == Variant.OFFROAD.value:
            ways = trail_touch.off_road_ways([piece.way_id for piece in pieces])
            stray = trail_touch.stray_rings(pieces, ways, touched_trails, any_dirt)
            if stray:
                if alternate:
                    # A side route (a candidate, the way round a junction or through a
                    # closure) is dropped, not the plan made again.
                    raise StraySideRoute("a side route takes a dirt trail no point touches")
                _wait_for_delays(delays)
                raise StrayTrails(tuple(stray), per_point)
            dirt_trails = trail_touch.rides_dirt(pieces, ways)
        # A long calm plan was searched in legs of its own: the answer has the plan's
        # legs, as the front end reads which leg a point on the line belongs to, and
        # a Mass Ride's stops and the description's are the plan's stops.
        groups = plan_groups
        if groups:
            if sum(groups) == len(legs):
                ends = list(itertools.accumulate(groups))
                first = [e - g for e, g in zip(ends, groups, strict=True)]
                leg_ends = [leg_ends[e - 1] for e in ends]
                leg_sides = [leg_sides[e - 1] for e in ends]
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
        hazard_kinds = None
        # The scenic roads as the stress query read them (audit S17), else read below.
        designations = None
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
            if analysed is not None and len(analysed.pieces) == len(pieces):
                classes = analysed.rated_classes
                hazard_kinds = analysed.hazard_kinds
                designations = designations_from(analysed.scenic, pieces)
                read_adjustments = adjustments_from(analysed.adjustments, pieces)
            else:
                classes = classify(pieces, when, roadway_only=lanes_as_roadway)
                hazard_kinds = hazards_read(classes, pieces)
                designations = scenic_read(classes, pieces)
                read_adjustments = adjustments_read(classes, pieces)
            traced_stress, traced_facility = totals(zip(pieces, classes, strict=True))
            for key, metres in traced_stress.items():
                stress[key] += metres
            for key, metres in traced_facility.items():
                facility[key] += metres
            # As the stress query read them (audit S17), else in a query of their own.
            used_adjustments = (
                adjustments_used(pieces) if read_adjustments is None else read_adjustments
            )
        # Each piece outside the District or not, read once for the sections and the flow
        # chart both (audit S20); a Mass Ride's only.
        outside_dc = (
            [_outside_dc(piece) for piece in pieces] if preset_name == "mass-ride" else None
        )
        stretches: list[tuple] = []
        for run in leg_runs:
            if isinstance(run, tuple):
                stretches.extend(
                    (
                        pieces[i].metres,
                        *classes[i],
                        getattr(classes[i], "unpaved", None),
                        getattr(classes[i], "rpm", None),
                        outside_dc is not None and outside_dc[i],
                        getattr(classes[i], "half", False),
                        getattr(classes[i], "rough", None),
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
            (lambda: _flow_stretches(leg_runs, pieces, classes, capacity, outside_dc))
            if mass_ride
            else None,
            majors if mass_ride else None,
            majors_complete,
            None
            if mass_ride
            else lambda: calm.Pricing(
                use_roads=presets.use_roads_for(stress_dial),
                rate=presets.calm_rate_for(stress_dial),
                weights=(exposure.lts3, exposure.lts4, exposure.avoid),
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
            leg_runs,
            pieces,
            classes,
            events,
            trip.get("summary") or {},
            walks,
            _way_names_of(pieces),
            via_boundaries(len(points), dials.vias, len(leg_runs)),
        )
        described_full, described_overview = described if described else (None, None)
        # The Avoid-rated junctions it passes (307, 335), at their distance along the
        # route as the router measures it; each also an entry of the description.
        avoid_found = avoid_rules.passages(coordinates, avoid_list) if avoid_list else []
        line_m = avoid_rules.line_length_m(coordinates)
        length_m = float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0
        avoid_scale = length_m / line_m if line_m > 0 and length_m > 0 else 1.0
        described_full = avoid_rules.with_entries(described_full, avoid_found, avoid_scale)
        described_overview = avoid_rules.with_entries(described_overview, avoid_found, avoid_scale)
        # The known hazards it rides (v0.10.0, `core.route_hazards`): said in place in the
        # directions and drawn as symbols on the route only.
        # Their kinds as the stress query read them (audit S16), else read here.
        hazards_ridden = route_hazards.along(leg_runs, pieces, hazard_kinds)
        described_full = route_hazards.with_entries(described_full, hazards_ridden)
        described_overview = route_hazards.with_entries(described_overview, hazards_ridden)
        # Its rustic roads, byways and named bike routes (v0.12.3): for the connector's road list.
        scenic_ridden = [] if over_budget else route_scenic.along(leg_runs, pieces, designations)
        # The climbs the route rides uphill, where the hill seek ran (205): each named in
        # `hills_seek.climbs` and as an entry of the description.
        climbs_ridden = []
        if sought is not None and not alternate and len(coordinates) >= 2:
            from . import hillseek

            pool = hillseek.candidates_for_naming(
                hillseek.load() or (), coordinates[0], coordinates[-1], line_m
            )
            climbs_ridden = hillseek.ridden(coordinates, pool)
            asked_ids = {c.id for proposal in sought.asked_for for c in proposal}
            climb_entries = [hillseek.entry(item, avoid_scale) for item in climbs_ridden]
            described_full = hillseek.with_entries(described_full, climb_entries)
            described_overview = hillseek.with_entries(described_overview, climb_entries)
            climbs_ridden = [
                {**hillseek.row(item, avoid_scale), "sought": item.climb.id in asked_ids}
                for item in climbs_ridden
            ]
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
        if calm_seek and not alternate and not fixed:
            # No climb search among alternatives: the stress order chose, and the
            # climbing only broke its ties (298(3)).
            hills_seek = {
                "candidates": 1,
                "chosen": 0,
                "extra_climb_m": 0.0,
                "extra_distance_m": 0.0,
                "limited": seek_limited,
                "climbs": [],
                "climb_seek": None,
            }
        elif seeking and not alternate and not fixed:
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
                # The climbs ridden (205), and what the hill seek did; null where it
                # did not run (the search was limited, or at the top of the stress slider).
                "climbs": climbs_ridden,
                "climb_seek": None if sought is None else sought.info(),
            }
        hills_tolerate = None
        if tolerating and not alternate and not fixed:
            direct = trips[0].get("summary") or {}
            # The climbing cost not charged, in the router's cost seconds: what the detent's
            # LT1 grade would charge the kept route over what this position's does.
            # None at the top of the stress slider, where the stress order decides
            # (`calm_first`).
            kept_profile = grade_profile(trip)
            at = {
                h: sum(
                    hill_cost.profile_cost_s(
                        kept_profile, hill_price.mass_kg, hill_price.flat_ms, h
                    )
                )
                for h in (0, hills_dial)
            }
            discount_m = (at[0] - at[hills_dial]) * hill_price.flat_ms if direct_tolerate else 0.0
            hills_tolerate = {
                "candidates": len(trips) if direct_tolerate else 1,
                "chosen": chosen if direct_tolerate else 0,
                "weight": round(tolerate_weight, 2),
                "discount_s": round(discount_m * _quiet_cost(costing), 1),
                "extra_climb_m": round(climb - _climb_of(trips[0]), 1),
                "extra_distance_m": round(
                    (float(summary.get("length", 0.0)) - float(direct.get("length", 0.0))) * 1000.0,
                    1,
                ),
                "limited": seek_limited,
            }
        hills_avoid = None
        if avoiding and not alternate and not fixed:
            direct = trips[0].get("summary") or {}
            hills_avoid = {
                "candidates": len(trips),
                "chosen": chosen,
                "weight": round(avoid_weight, 2),
                "brake_grade": preset.brake_grade,
                "grade_cost_s": round(rider_hill_s(trip, hill_price, _quiet_cost(costing)), 1),
                "direct_grade_cost_s": round(
                    rider_hill_s(trips[0], hill_price, _quiet_cost(costing)), 1
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
        # Not on a first route (`quick`): the direct route it would be weighed against is a
        # second /route, and the full plan that follows says it.
        detour = (
            None
            if quick or fixed
            else _detour(
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
                early=early_direct,
            )
        )
        # The time its junctions cost the rider, which the router's own time leaves out
        # (`routemaker.junction_delay`): part of the time shown.
        waits = junction_delay.delay_runs(
            raw_junctions,
            stop_as_yield,
            lambda lon, lat: intersections.beacon_at(lon, lat, beacons) is not None,
        )
        delay = float(sum(wait for _m, wait in waits))
        route_m = round(float(summary.get("length", 0.0)) * 1000.0, 1)
        route_s = float(summary.get("time", 0.0))
        # Novice and Nervous (v0.11.0, `core.novice_walks`): the short stretches of real LTS 4
        # or worse with a sidewalk beside them, walked; on the plan's own route only, so the
        # candidates do not spend its time.
        walked: list[dict] = []
        novice_classes = classes
        if (
            preset_name == presets.NOVICE
            and dials.novice_walks
            and not over_budget
            and not quick
            and not alternate
        ):
            # One small budget for all of them, so they never hold a slow plan up.
            walks_until = Deadline(
                min(deadline.at, clock() + novice_walks.BUDGET_S), deadline.per_call_s
            )
            walked = novice_walks.walks(
                novice_walks.stretches(leg_runs, pieces, classes),
                coordinates,
                sum(p.metres for p in pieces)
                + sum(float(r) for r in leg_runs if not isinstance(r, tuple)),
                route_m,
                lambda a, b: walk_leg(a, b, walks_until, prefer_walkways=True),
                lambda line: walk_roadside_m(line, walks_until),
            )
            if walked:
                described_full = novice_walks.with_entries(described_full, walked)
                described_overview = novice_walks.with_entries(described_overview, walked)
                gone = {i for walk in walked for i in walk["pieces"]}
                novice_classes = [
                    PieceClass("1", "none") if i in gone else cls for i, cls in enumerate(classes)
                ]
        # The walked pieces' own metres, as `stress` counts them (a join gap left out).
        walked_m = sum(
            pieces[i].metres
            for walk in walked
            for i in walk["pieces"]
            if classes[i][0] in novice_walks.WALK_TIERS
        )
        walk_change_s = novice_walks.time_change_s(walked, route_m, route_s)
        return {
            "preset": preset.name,
            "variant": variant,
            "dirt_trails": dirt_trails,
            "dirt_closed": dirt_closed,
            "geometry": {
                "type": "LineString",
                "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in coordinates],
            },
            "distance_m": round(float(summary.get("length", 0.0)) * 1000.0, 1),
            "duration_s": round(route_s + delay + walk_change_s, 1),
            "junction_delay_s": round(delay, 1),
            # Where along the line that time falls, hills and junction waits in place, for a
            # ride's arrival times (`routemaker.time_marks`).
            "time_marks": time_marks.time_marks(router_at, waits, traced_m),
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
            "hills_tolerate": hills_tolerate,
            "attribution": list(ATTRIBUTION),
            "leg_ends": leg_ends,
            "arrival_side": arrival_side_of(trip),
            "leg_arrival_sides": leg_sides,
            "intersections": None if events is None else _intersection_rows(events),
            "intersection_groups": None if events is None else _intersection_groups(events),
            "junctions_debug": (
                _junction_debug_rows(events)
                if dials.debug_junctions and events is not None
                else None
            ),
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
            # A stop or the end on a road not open to the public (the owner, 2026-10-29).
            "point_notes": (
                []
                if over_budget or len(leg_runs) != len(points) - 1
                else not_public_ends(pieces, leg_runs, len(asked_points))
            ),
            "avoid_junctions": avoid_junctions.rows(avoid_found, avoid_scale),
            "avoid_notice": avoid_rules.notice(avoid_found),
            # The known hazards the route rides (v0.10.0): cobbles, rails; [] where none.
            "road_hazards": hazards_ridden,
            # The scenic designations it rides (v0.12.3): rustic roads, byways; [] where none.
            "scenic_roads": scenic_ridden,
            # Steep grades either way past 5% and 8% (v0.12.5, `routemaker.steep_grades`), in
            # riding order, metres along the router's profile; null off a Mass Ride or Novice.
            "steep_grades": (
                steep_grades.public(steep_grades.stretches(grade_profile(trip)))
                if steep_ride
                else None
            ),
            # A Mass Ride's approved hazards in riding order (325); null on other ride types.
            "mass_hazards": (
                mass_hazards.along(leg_runs, pieces, classes, hazard_list)
                if preset_name == "mass-ride"
                else None
            ),
            # A Mass Ride's road capacity for its ride size and the corkers it needs
            # (`routemaker.mass_route`), for the page and the assistants' tool to improve on;
            # null on other ride types.
            "mass_capacity": (
                _mass_capacity(
                    _named(
                        _flow_stretches(leg_runs, pieces, classes, capacity, outside_dc),
                        leg_runs,
                        pieces,
                    ),
                    profile,
                    max(_trip_length_m(trip), ((profile or {}).get("m") or [0])[-1] or 0, 1),
                    ride_size,
                    None if alternate else capacity_choice,
                )
                if preset_name == "mass-ride" and not over_budget
                else None
            ),
            # Novice and Nervous (v0.7.0): the busiest stretch, read on the real levels.
            # Not on a first route (`quick`): the offer is decided on the route the search
            # settles, so it does not come and go as the better route arrives.
            "novice": (
                novice_note(
                    stress,
                    refined,
                    busiest_stretch(pieces, novice_classes),
                    walked_m,
                    novice_walks.public(walked),
                )
                if preset_name == presets.NOVICE and not over_budget and not quick
                else None
            ),
        }

    answered = _answer(trip, refined, dodges_of=dodges)
    end_index = 0 if loop else len(asked_points) - 1
    answered["walk_in"] = walk_in(
        None if 0 in moved_indices else asked_points[0],
        None if end_index in moved_indices else asked_points[end_index],
        answered["geometry"]["coordinates"],
        deadline,
    )
    _wait_for_delays(delays)
    body = work_zones.with_work_zones(answered, zones_plan)
    body["provisional"] = quick
    body["follows_file"] = following
    body["against_traffic"] = answer.get("against_traffic") if following else None
    body["follows_exactly"] = following and dials.follow_exact
    body["drawn_legs"] = sorted(dials.straight) if drawing else None
    timing.mark("answer")

    def _with_mtb(answered: dict, info: dict | None) -> dict:
        """A Mountain Bike route's reading on its body, and its time at about 6 mph
        (10 km/h) on singletrack (`mtbmode.duration_s`), the router's own time kept."""
        answered["mtb"] = info
        if info and info.get("singletrack_m"):
            # The junction delay is added after the singletrack retiming, so the router's
            # own time stays the router's and the delay is not scaled with the trail.
            delay = answered.get("junction_delay_s") or 0.0
            router_s = answered["duration_s"] - delay
            info["router_duration_s"] = round(router_s, 1)
            answered["duration_s"] = round(
                mtbmode.duration_s(router_s, answered["distance_m"], info["singletrack_m"]) + delay,
                1,
            )
        return answered

    def _offered_mtb(offered: dict) -> dict | None:
        """The reading of a route offered beside the answer (a candidate, the way round an
        Avoid-rated junction): its own, so a harder trail on it is said when it is shown."""
        if not mtb_level_held:
            return None
        return mtb.reread(
            offered, variant, trace_costing, when, deadline, traces, dials.mtb_level,
            dials.mtb_preferred,
        )  # fmt: skip

    _with_mtb(body, mtb_info)
    body["avoid_search"] = avoid_info
    body["avoid_alternate"] = None
    if avoid_list:
        avoid_junctions.record(avoid_junctions.passages_of(trip, avoid_list))
    if avoid_trip is not None:
        # The best route round the junction, however much longer (335), answered as a
        # whole route of its own so the client draws and describes it as it does this one:
        # a trace for each of its legs.
        if deadline.at - clock() >= ALTERNATE_MIN_S:
            try:
                around = work_zones.with_work_zones(_answer(avoid_trip, None, True), zones_plan)
                _with_mtb(around, _offered_mtb(avoid_trip))
                around["walk_in"] = walk_in_for(around, body)
                around["extra_distance_m"] = round(around["distance_m"] - body["distance_m"], 1)
                around["extra_duration_s"] = round(around["duration_s"] - body["duration_s"], 1)
                body["avoid_alternate"] = around
            except StraySideRoute:
                pass
            except (DeadlineExceeded, RouterUnavailable, NoRoute):
                avoid_info["alternate"] = "time"
        else:
            avoid_info["alternate"] = "time"
    # The standard way through the closures this route goes round (v0.8.2; the owner,
    # 2026-10-17: "several closures marked that aren't actually closed. We should have
    # both the standard route and the detour"): a whole route of its own, drawn beside
    # it, which Ride follows where the rider takes it.
    body["closure_through"] = None
    through = None if zones_plan is None else zones_plan.through
    if through is not None and deadline.at - clock() >= ALTERNATE_MIN_S:
        try:
            standard = work_zones.with_work_zones(_answer(through, None, True), zones_plan)
            _with_mtb(standard, _offered_mtb(through))
            standard["extra_distance_m"] = round(standard["distance_m"] - body["distance_m"], 1)
            standard["extra_duration_s"] = round(standard["duration_s"] - body["duration_s"], 1)
            standard["closure_ids"] = sorted(zones_plan.affecting)
            body["closure_through"] = standard
        except (DeadlineExceeded, RouterUnavailable, NoRoute):
            pass
    candidates = []
    # The candidates' traces at once (v0.7.0 step 3); each is read in full below, in order.
    prefetch_traces(
        variant,
        trace_costing,
        [found for found, _reading in refine_context.candidates[1:]],
        deadline,
        traces,
    )
    for found, _reading in refine_context.candidates[1:]:
        # Each is read in full (its traces are remembered, its junctions read once
        # across the joints of a long plan), inside what is left of the budget.
        if deadline.at - clock() < ALTERNATE_MIN_S:
            break
        # A candidate is answered as the search found it (its `dodges` null): the
        # dodge pass is the answer's alone, one bounded pass a plan.
        try:
            refine.analyse(found, refine_context, deadline)
            candidate = work_zones.with_work_zones(_answer(found, None, True), zones_plan)
            _with_mtb(candidate, _offered_mtb(found))
            candidate["walk_in"] = walk_in_for(candidate, body)
            if maxcalm and target_m:
                candidate["over_target_m"] = target_fields(
                    _trip_length_m(found), target_m, ceiling
                )["over_target_m"]
            candidates.append({**candidate, "rank": len(candidates) + 2})
        except StraySideRoute:
            continue
        except (DeadlineExceeded, RouterUnavailable, NoRoute):
            break
    body["candidates"] = candidates or None
    body["rank"] = 1 if candidates else None
    timing.mark("more")
    return body


# A re-route's U-turn (the owner, 2026-10-18: "Penalize U turns. Basically you'd have to save
# about half a mile on that road for it to make sense", "For rerouting"). A route that sets off
# back the way the rider is going is kept only where it is at least UTURN_SAVING_M shorter than
# the best one that sets off ahead.
UTURN_SAVING_M = 1609.344 / 2
# A start this far from the rider's heading is a U-turn.
UTURN_MIN_DEG = 120.0
# How far along the route its setting-off direction is read: past the snap to the road.
UTURN_READ_M = 25.0
# Valhalla's `heading_tolerance` for the route that sets off ahead: wide enough for a GPS
# heading's wobble and a bend, never wide enough to take the way back.
HEADING_TOLERANCE_DEG = 75


def sets_off_back(answer: dict, heading: float) -> bool:
    """Whether the route in `answer` (`plan`'s body) sets off back the way the rider is heading."""
    line = [Point(lon, lat) for lon, lat in answer["geometry"]["coordinates"]]
    if len(line) < 2:
        return False
    along = 0.0
    for a, b in zip(line, line[1:], strict=False):
        along += haversine(a, b)
        if along >= UTURN_READ_M:
            break
    if along < 1.0:
        return False
    return bearing_delta(bearing(line[0], b), heading) >= UTURN_MIN_DEG


def plan_onward(
    points: list[list[float]],
    preset_name: str,
    long_ride: bool = False,
    started: float | None = None,
    dials: Dials | None = None,
    quick: bool = False,
    candidates: bool = True,
) -> dict:
    """`plan`, with a re-route's U-turn penalised: where `dials.heading` is given and the route
    sets off back the other way, the best route that sets off ahead is planned too, and the
    U-turn kept only where it saves UTURN_SAVING_M (never with `dials.ahead_only`, where the
    route ahead is planned first: `_plan_ahead_first`). Anything that stops the second plan (no
    route ahead, no time left) keeps the first: the rider is never left without one."""
    dials = dials or Dials()
    heading = dials.heading
    asked = dict(long_ride=long_ride, started=started, quick=quick, candidates=candidates)
    if (
        heading is not None
        and dials.ahead_only
        and dials.follow is None
        and not loop_wanted(points, dials.loop, preset_name)
    ):
        return _plan_ahead_first(points, preset_name, dials, heading, asked)
    answered = plan(points, preset_name, dials=dataclasses.replace(dials, heading=None), **asked)
    # `plan` sets no heading on a followed line or a loop: a second plan would be the same.
    if (
        heading is None
        or dials.follow is not None
        or loop_wanted(points, dials.loop, preset_name)
        or not sets_off_back(answered, heading)
    ):
        return answered
    timings = timing.current()
    if timings is not None:
        timings.note("uturn", "replanned")
    try:
        ahead = plan(points, preset_name, dials=dials, **asked)
    except PlanCancelled:
        # A DeadlineExceeded too, but the rider has moved on: no answer is kept (review of S7).
        raise
    except (NoRoute, TooLong, RouterUnavailable, DeadlineExceeded) as error:
        logger.info("a re-route turns round: no route ahead (%s)", type(error).__name__)
        return answered
    saving = float(ahead["distance_m"]) - float(answered["distance_m"])
    # The router takes the way back where it has no way ahead within its tolerance.
    if (saving >= UTURN_SAVING_M and not dials.ahead_only) or sets_off_back(ahead, heading):
        logger.info("a re-route turns round: it saves %.0f m", saving)
        return answered
    return ahead


def _plan_ahead_first(
    points: list[list[float]], preset_name: str, dials: Dials, heading: float, asked: dict
) -> dict:
    """`plan_onward` after the rider has ridden on past two U-turns (`dials.ahead_only`): the
    route that sets off ahead is planned first, as it is the answer whatever turning round would
    save (audit S5; the owner approved planning ahead first on 2026-10-27). Where that plan
    answers, its route is the answer at once, even where it still turns round: it is the way
    ahead the rider chose by riding past two U-turns, and a second plan would cost beta a whole
    plan (audit round 2, R1 option; the owner, 2026-10-27 7:52 PM ET: "make the banked
    changes"). The plan that ignores the heading is made only where the first fails, on the
    same `started`, so it has what time the first left."""
    timings = timing.current()
    if timings is not None:
        timings.note("uturn", "ahead first")
    try:
        ahead = plan(points, preset_name, dials=dials, **asked)
    except PlanCancelled:
        # A DeadlineExceeded too, but no second plan is started for a rider who has moved on
        # (review of S7).
        raise
    except (NoRoute, TooLong, RouterUnavailable, DeadlineExceeded) as error:
        logger.info("a re-route ahead only: no route ahead (%s)", type(error).__name__)
    else:
        if sets_off_back(ahead, heading):
            # The router takes the way back where it has no way ahead within its tolerance.
            logger.info("a re-route ahead only: the route ahead turns round, kept")
        return ahead
    if timings is not None:
        timings.note("uturn", "ahead first, replanned")
    return plan(points, preset_name, dials=dataclasses.replace(dials, heading=None), **asked)


def _early_strays(
    trip: dict,
    variant: str,
    costing: dict,
    deadline: Deadline,
    traces: dict,
    touched_trails: frozenset[int],
    any_dirt: bool,
) -> list:
    """The strips across the stray dirt trails (`trail_touch.stray_rings`) of the router's own
    route `trip`, read as the answer reads them (`_plan`, audit S12 part 1); none where a leg
    is drawn or the router cannot trace it now: the answer's own check still runs. A cancel is
    raised (review of S7)."""
    legs = trip.get("legs") or []
    if not legs or any(leg.get("drawn") for leg in legs):
        return []
    prefetch_traces(variant, costing, [trip], deadline, traces)
    pieces: list[Piece] = []
    for leg in legs:
        try:
            trace = _trace(variant, costing, leg.get("shape", ""), deadline, traces)
        except PlanCancelled:
            raise
        except (DeadlineExceeded, RouterUnavailable) as error:
            logger.info("dirt trails: no early check (%s)", type(error).__name__)
            return []
        if trace is not None:
            pieces.extend(pieces_of_trace(trace))
    ways = trail_touch.off_road_ways([piece.way_id for piece in pieces])
    return trail_touch.stray_rings(pieces, ways, touched_trails, any_dirt)


def quick_applies(preset_name: str, loop: bool, long_ride: bool, long_calm: bool) -> bool:
    """Whether a plan may answer its first good route alone (`plan(quick=True)`; v0.7.0,
    "Faster routing" step 2). Not a loop (its way back is made by the search), a long
    ride or a long calm plan (planned leg by leg), nor Mountain Bike, whose hardest-level
    rule picks among the router's routes: a first route there could be one the rider
    must not be sent on. Bikeshare and the transit ride types plan their own way."""
    return not (loop or long_ride or long_calm or preset_name == mtb.PRESET)


def _wait_for_delays(delays: Future | None) -> None:
    """The closures' delay probes started beside the plan (`work_zones.measure_delays`):
    waited for, as the closures are written from them. They never fail a plan."""
    if delays is None:
        return
    try:
        delays.result()
    except Exception:  # noqa: BLE001 - a delay not worked out is None, as before
        logger.info("closures: the delays could not be worked out", exc_info=True)


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
    # MDOT SHA's traffic counts (FOLLOWUP-MDOT-AADT): Maryland iMAP's terms ask that
    # derived data acknowledge the State of Maryland, so the credit names it.
    mdot_aadt.CREDIT,
    # DDOT's Pavement Condition Index (DC-PCI): District streets' smoothness reading.
    # District data terms (CC0 1.0 or CC BY 4.0, credited), owner-confirmed 2026-10-16.
    "DDOT Pavement Condition Index (DC GIS)",
    "Open Baltimore",
    # Alexandria's posted speeds where OSM has none (PLAN.md item 183), CC0 from the
    # city's OpenData portal; credited as every source is (OWNER-DECISIONS 301).
    "City of Alexandria",
    "Montgomery County Planning Department",
    "USGS 3DEP",
    "U.S. Census Bureau",
)
