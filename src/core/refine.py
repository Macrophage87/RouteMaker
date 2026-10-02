"""A search over the router's own routes: the calm detour and crossing avoidance.

Why a search and not a cost. Valhalla 3.5.1's bicycle costing prices a road by
`use_roads`, which runs 0 to 1 and no further, and at 0 an LTS 3 way is already
at its ceiling (about 5 to 13 times its time). It has no hook that knows which
road a rider crosses or how they turn (`routemaker.intersections`, "Why this is
not in the graph"). So the two things the owner asked for on 2026-10-01 -

- item 163, a top end where "I'm willing to add 10 or 20 miles to my trip just
  so it's more relaxing", with item 164's "the upper end could be much greater
  than straight line distance, just warn people", and
- item 165, "crossing a busy road should get some level of penalty, especially
  in rural areas where it's usually a stop sign against free-flowing traffic",

- are priced here, on whole routes, and the router is steered with its own
  `exclude_locations`: the busy ways (or the approach to a bad crossing) of the
  best route so far are excluded, the router is asked again, and the new route
  is kept if it scores better. Exclusions accumulate, so each round can clear
what the last one found. The score is the router's own cost for the route
(its time with the stress, hill, turn and gate prices of the request) plus an
extra price, in the router's cost seconds, for what the router cannot see:

    router cost + QUIET COST x ( CALM RATE x (LTS 3 metres + 2 x LTS 4 + 3 x Avoid)
                               + INTERSECTION WEIGHT x (the junction events' cost in metres)
                               + CLIMB WEIGHT x climb )

QUIET COST is what a metre of quiet-street riding costs the router at the
request's speed (`quiet_cost_per_m`: 2.2 times its time, measured on the live
router). The calm rate is `presets.calm_rate_for(stress)` (0 up to the old top
of the slider, then exponential): metres of quiet riding accepted per metre of
LTS 3 avoided, on top of the router's own price for it. The intersection weight
rises from 0.25 at the traffic tolerant end to 1 at Default (turn and
intersection costs stay active at every setting, as the literature review's
guardrail asks), and the climb weight is the hills slider's avoid half, so a
relaxed ride is not a zig-zag over a hill.

There is no cap on the detour. The search stops when a round finds nothing
left to exclude, when two rounds in a row do not improve the score, when the
router has no route left (every way out is excluded), or when the time runs
out; `info["limited"]` says which, so the answer can say a calm route was
looked for and not found.
"""

from __future__ import annotations

import bisect
import contextlib
import logging
import math
import os
import tempfile
import threading
from dataclasses import dataclass, field

from routemaker import intersections as model
from routemaker import trace_junctions
from routemaker.geo import Point, haversine

from . import junctions, presets, routing

logger = logging.getLogger(__name__)

# The most rounds of exclusion and re-routing. Crossing avoidance alone gets
# fewer: it runs for most plans, where the calm search runs only past the old
# top of the slider.
REFINE_MAX_ROUNDS = 5
CROSSING_ONLY_ROUNDS = 1
# Seconds, at most, the whole search may take; and the least a round may be
# started with (a /route, its trace, the joins and a /locate), and what is kept
# back from the request's budget for the answer's own traces.
REFINE_BUDGET_S = 14
REFINE_ROUND_MIN_S = 5
REFINE_TRACE_RESERVE_S = 6
# Rounds in a row that may not beat the best score before the search gives up.
REFINE_PATIENCE = 2
# The longest span (metres of straight line) the search runs on, as the avoid
# half of the hills slider has its own (`routing.AVOID_MAX_SPAN_M`): on the live
# router a cold 42-48 km request took 33 s without alternates.
REFINE_MAX_SPAN_M = 30_000
# A junction is a target for avoidance from this cost (feet): the red ones. An
# orange crossing is worth about a block of detour, which is not worth the
# second route the search costs (2 to 3 s on the live host); it still counts in
# every candidate's score, so the calm rounds weigh it.
REFINE_MIN_EVENT_FT = model.RED_MIN_FT
# How many ways one round excludes, and the junctions it takes up; the router's
# own limit on `exclude_locations` is 200 (`valhalla/*.json`).
CALM_POINTS_PER_ROUND = 60
CROSSING_POINTS_PER_ROUND = 3
MAX_EXCLUDES = 150
# Samples along a busy stretch this far apart (metres): every edge of a street is
# longer than half of it, so each gets one. Each is the middle of a traced edge,
# interpolated half way along it (`trace_junctions.edge_midpoints`), never a
# vertex: an exclusion on a node takes out every edge there, the cross street's
# too. An edge shorter than CALM_MIN_EDGE_M has its middle within a couple of
# metres of a node and is not sampled.
CALM_SAMPLE_M = 40.0
CALM_MIN_EDGE_M = 6.0
# Never exclude within this far along the route of its start or its end, nor of
# a via point: the router must be able to leave and arrive, and the way out of a
# trailhead or a cul-de-sac is often the one busy road. (Measured on the live
# router: a Bethesda start whose only exit was an LTS 4 road 150 m long made
# every calm round "no route" at the 120 m this was first.)
ENDPOINT_CLEARANCE_M = 500.0
# "Traffic wins" (OWNER-DECISIONS 61, on hill avoidance): the search never makes
# a route busier. A candidate whose LTS 3, 4 and Avoid exposure (the weighted
# metres) is more than this share, and `EXPOSURE_SLACK_M` metres, over the
# router's own route's is not taken, however many crossings it avoids: measured on
# the live router, Rockville to Silver Spring at the old top of the slider
# traded 1.6 mi more LTS 3-4 for fewer crossings.
EXPOSURE_TOLERANCE = 0.02
EXPOSURE_SLACK_M = 50.0
# A candidate must beat the best by this (cost seconds) to replace it.
IMPROVEMENT_EPS_S = 10.0
# What a metre of quiet-street riding costs the router, as a multiple of its
# time: a residential street with no lane, measured on the live standard router
# at every `use_roads` (median 2.2, 1.8 to 2.9).
QUIET_COST_FACTOR = 2.2
# PROPOSALS for the owner. A metre of climb is this many metres of riding on the
# hills slider's avoid end; the intersection weight at the traffic tolerant end.
CLIMB_EQUIVALENT_M = 12.0
INTERSECTION_WEIGHT_AT_ZERO = 0.25

# How many searches may run at once. Each makes up to about 20 router calls
# (review r1: 5 rounds of a route, its trace and a /locate, and the detour
# probe), and the API's sync workers (`WEB_CONCURRENCY` 7 in compose.yaml)
# outnumber each router's threads (`concurrency` 4 in valhalla/*.json): four
# concurrent calm plans saturate the standard router. So one search at a time
# in a process, and CALM_SEARCHES_PER_HOST across the API's processes on the
# host, by a lock file each (`CALM_SLOT_DIR`). A plan that finds no slot free
# is answered with the router's own route at once and says so
# (`limited: "busy"`), rather than queueing behind the others.
# The wider search (OWNER-DECISIONS 187, an exploration: "Make max calm even
# higher. Let's see what 150 would do."). The exclusion rounds' candidates are
# nested - each excludes what the last one rode - so above a rate of about 2 the
# same calm candidate wins and 90 and 100 plan the same route. The wider search
# adds candidates the nesting cannot reach: the router's route through a point
# off the straight line, either side of its middle, at these fractions of the
# straight-line span. Each is one route, its trace and its junctions (1 to 3 s
# on the live router), scored and guarded as every other candidate. Off unless
# the calm rate is at least WIDE_SEARCH_FROM_RATE (None: never), which is the
# owner's choice (docs/DEVELOPMENT.md, "The top of the slider: what 150 would
# do"); the measurements are there.
WIDE_SEARCH_FROM_RATE: float | None = None
WIDE_OFFSETS = (0.25, -0.25, 0.5, -0.5)
# Spans shorter than this have no room to go wide in.
WIDE_MIN_SPAN_M = 3000.0

CALM_SEARCHES_PER_PROCESS = 1
CALM_SEARCHES_PER_HOST = 3
CALM_SLOT_DIR = os.path.join(tempfile.gettempdir(), "routemaker-calm-search")
_process_slots = threading.BoundedSemaphore(CALM_SEARCHES_PER_PROCESS)


class _Unlocked:
    """The stand-in for a slot file where files cannot be locked."""

    def close(self) -> None:
        pass


def _host_slot():
    """An open, locked slot file, or None where every slot is taken. Where
    locking files is not possible at all (no `fcntl`, an unwritable directory)
    the per-process limit alone holds, and a stand-in is returned."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - not on the Linux hosts this runs on
        return _Unlocked()
    try:
        os.makedirs(CALM_SLOT_DIR, exist_ok=True)
    except OSError:
        return _Unlocked()
    for number in range(CALM_SEARCHES_PER_HOST):
        try:
            handle = open(os.path.join(CALM_SLOT_DIR, f"slot-{number}"), "a")  # noqa: SIM115
        except OSError:
            return _Unlocked()
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            continue
        return handle
    return None


@contextlib.contextmanager
def search_slot():
    """True inside while this plan holds a search slot, False where none is
    free (and then nothing is held)."""
    if not _process_slots.acquire(blocking=False):
        yield False
        return
    try:
        held = _host_slot()
        if held is None:
            yield False
            return
        try:
            yield True
        finally:
            held.close()
    finally:
        _process_slots.release()


def quiet_cost_per_m(costing: dict) -> float:
    """The router's cost, in seconds, of a metre of quiet-street riding at this
    request's speed."""
    options = costing.get("bicycle") or {}
    kmh = options.get("cycling_speed") or presets.VALHALLA_DEFAULT_SPEED_KMH.get(
        options.get("bicycle_type", "Hybrid"), 18.0
    )
    return QUIET_COST_FACTOR * 3.6 / kmh


def wide_search_for(rate: float) -> bool:
    """Whether a plan at this calm rate also asks for the wider candidates."""
    return WIDE_SEARCH_FROM_RATE is not None and rate >= WIDE_SEARCH_FROM_RATE


def wide_points(points: list[list[float]]) -> list[tuple[float, float]]:
    """The points off the straight line from the start to the end, either side
    of its middle (WIDE_OFFSETS of the span); none for a short span."""
    (lon_a, lat_a), (lon_b, lat_b) = points[0][:2], points[-1][:2]
    span = haversine(Point(lon_a, lat_a), Point(lon_b, lat_b))
    if span < WIDE_MIN_SPAN_M:
        return []
    mid_lon, mid_lat = (lon_a + lon_b) / 2, (lat_a + lat_b) / 2
    kx = 111_320.0 * math.cos(math.radians(mid_lat))
    ky = 110_540.0
    east, north = (lon_b - lon_a) * kx, (lat_b - lat_a) * ky
    length = math.hypot(east, north)
    # Left of the direction of travel.
    left_east, left_north = -north / length, east / length
    return [
        (mid_lon + left_east * span * f / kx, mid_lat + left_north * span * f / ky)
        for f in WIDE_OFFSETS
    ]


def intersection_weight(stress: int) -> float:
    """How much of the intersection cost counts at a slider position: a quarter
    at the traffic tolerant end, all of it from Default up."""
    return INTERSECTION_WEIGHT_AT_ZERO + (1 - INTERSECTION_WEIGHT_AT_ZERO) * min(
        1.0, stress / presets.STRESS_DEFAULT_AT
    )


@dataclass
class Context:
    """What the plan hands the search."""

    variant: str
    request: dict
    costing: dict
    when: str
    deadline: routing.Deadline
    traces: dict
    points: list[list[float]]
    roadway_only: bool
    with_facility: bool
    group: bool
    rate: float
    weight: float
    climb_weight: float
    quiet_cost: float
    analyses: dict = field(default_factory=dict)
    # Whether the wider search runs after the exclusion rounds (`wide_search_for`).
    wide: bool = False


@dataclass
class Analysis:
    """One candidate route, read."""

    length_m: float
    cost_s: float
    exposure_m: float
    climb_m: float
    pieces: list
    classes: list
    events: list | None
    # Metres along the route at which each via point is reached.
    via_m: list = field(default_factory=list)
    # The middle of each traced edge: (metres along, lon, lat, edge metres).
    marks: list = field(default_factory=list)

    def score(self, ctx: Context) -> float:
        """The router's cost plus the extra price (see the module docstring)."""
        penalty = model.penalty_m(self.events) if self.events else 0.0
        extra = ctx.rate * self.exposure_m + ctx.weight * penalty + ctx.climb_weight * self.climb_m
        return self.cost_s + ctx.quiet_cost * extra


def locator(variant: str, deadline: routing.Deadline):
    """`/locate` through the plan's own budgeted router call."""

    def locate(payload: dict) -> list[dict]:
        return routing._call(variant, "locate", payload, deadline)

    return locate


def events_of_raws(raws, ctx: Context, deadline: routing.Deadline) -> list | None:
    """The junction events of a route's raw junctions, or None where the roads
    or the router could not be asked."""
    try:
        return junctions.events_of(
            raws, ctx.when, ctx.with_facility, locator(ctx.variant, deadline), ctx.group
        )
    except routing.DeadlineExceeded:
        raise
    except Exception:  # noqa: BLE001 - a route is answered without its intersections
        logger.warning("the intersection events could not be read", exc_info=True)
        return None


def analyse(trip: dict, ctx: Context, deadline: routing.Deadline) -> Analysis | None:
    """A trip's length, exposure, climb and junction events; None where a leg
    cannot be traced. Remembered per plan, by the trip's shapes."""
    legs = trip.get("legs") or []
    key = tuple(leg.get("shape", "") for leg in legs)
    if key in ctx.analyses:
        return ctx.analyses[key]
    pieces: list = []
    raws: list = []
    marks: list = []
    offset = 0.0
    via_m: list[float] = []
    for number, leg in enumerate(legs):
        trace = routing._trace(ctx.variant, ctx.costing, leg.get("shape", ""), deadline, ctx.traces)
        if trace is None:
            return None
        made = routing.pieces_of_trace(trace)
        pieces.extend(made)
        shape = routing.decode_polyline6(leg.get("shape", ""))
        raws.extend(trace_junctions.junctions_of_trace(trace, shape, offset))
        marks.extend(trace_junctions.edge_midpoints(trace, shape, offset))
        offset += sum(piece.metres for piece in made)
        if number < len(legs) - 1:
            via_m.append(offset)
    classes = routing.classify(pieces, ctx.when, ctx.roadway_only)
    stress, _facility = routing.totals(zip(pieces, classes, strict=True))
    result = Analysis(
        length_m=float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0,
        cost_s=routing._router_cost(trip),
        exposure_m=stress["3"] + 2 * stress["4"] + 3 * stress["5"],
        climb_m=routing._climb_of(trip),
        pieces=pieces,
        classes=classes,
        events=events_of_raws(raws, ctx, deadline),
        via_m=via_m,
        marks=marks,
    )
    ctx.analyses[key] = result
    return result


def _clear_of_ends(along_m: float, total_m: float, vias: list[float]) -> bool:
    """Whether a point `along_m` metres along a route of `total_m` is far enough
    from its ends (and from where each via point is reached)."""
    if along_m < ENDPOINT_CLEARANCE_M or total_m - along_m < ENDPOINT_CLEARANCE_M:
        return False
    return all(abs(along_m - via) >= ENDPOINT_CLEARANCE_M for via in vias)


@dataclass(frozen=True)
class Target:
    """A point to exclude, and how bad the road under it is (3-5; a crossing's
    approach counts as 4)."""

    point: tuple[float, float]
    tier: int


def _marks(analysis: Analysis) -> list:
    """The edges' middles; where a reading has none (a route read before they
    were kept), each piece's own middle."""
    if analysis.marks:
        return analysis.marks
    marks, along = [], 0.0
    for piece in analysis.pieces:
        marks.append((along + piece.metres / 2, piece.lon, piece.lat, piece.metres))
        along += piece.metres
    return marks


def calm_targets(analysis: Analysis, ctx: Context, min_tier: int = 3) -> list[Target]:
    """Points along the route's stretches of LTS `min_tier` and worse, one to an
    edge: each the edge's interpolated middle, with the tier of the piece there."""
    kept: list[Target] = []
    total = analysis.length_m
    ends, along = [], 0.0
    for piece in analysis.pieces:
        along += piece.metres
        ends.append(along)
    if not ends:
        return []
    for at, lon, lat, metres in _marks(analysis):
        if metres < CALM_MIN_EDGE_M:
            continue
        tier, _kind = analysis.classes[min(bisect.bisect_left(ends, at), len(ends) - 1)]
        if tier not in ("3", "4", "5") or int(tier) < min_tier:
            continue
        point = (lon, lat)
        if kept and haversine(Point(*kept[-1].point), Point(*point)) < CALM_SAMPLE_M:
            continue
        if _clear_of_ends(at, total, analysis.via_m):
            kept.append(Target(point, int(tier)))
    if len(kept) > CALM_POINTS_PER_ROUND:
        step = len(kept) / CALM_POINTS_PER_ROUND
        kept = [kept[int(i * step)] for i in range(CALM_POINTS_PER_ROUND)]
    return kept


def crossing_targets(analysis: Analysis, ctx: Context) -> list[Target]:
    """The approaches to the worst junctions."""
    if ctx.group or not analysis.events:
        return []
    worst = sorted(
        (e for e in analysis.events if e.approach and e.cost_ft >= REFINE_MIN_EVENT_FT),
        key=lambda e: -e.cost_ft,
    )
    return [
        Target(e.approach, 4)
        for e in worst
        if _clear_of_ends(e.m, analysis.length_m, analysis.via_m)
    ][:CROSSING_POINTS_PER_ROUND]


def refine(trip: dict, ctx: Context) -> tuple[dict, dict]:
    """The best of the original route and the routes found by excluding what is
    worst about each in turn, and what the search did.

    The calm search goes down the tiers: the first round excludes the LTS 4 and
    Avoid stretches of the router's own route, later rounds every LTS 3 stretch
    of the candidate before, so the candidates are nested, each calmer and
    longer than the last, and the slider's rate picks among them. A round the
    router has no route for is asked again with only the LTS 4 stretches."""
    info = {
        "rate": ctx.rate,
        "rounds": 0,
        "excluded": 0,
        "limited": None,
        "original_m": None,
        "extra_distance_m": 0.0,
        "exposure_before_m": None,
        "exposure_after_m": None,
    }
    # The route the router gave is read inside the plan's own budget, exactly as
    # the answer would read it, and what it traced is remembered for the answer:
    # a trace that fails here is not asked for again (`routing._trace`). Only the
    # candidates are held to the search's shorter one.
    try:
        best = analyse(trip, ctx, ctx.deadline)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = "time"
        return trip, info
    if best is None:
        info["limited"] = "untraceable"
        return trip, info
    # The search's own time starts once the route is read: reading it is the
    # answer's work, done whether or not anything is searched.
    stop_at = min(routing.clock() + REFINE_BUDGET_S, ctx.deadline.at - REFINE_TRACE_RESERVE_S)
    first_exposure = best.exposure_m
    info["original_m"] = round(best.length_m, 1)
    info["exposure_before_m"] = round(best.exposure_m, 1)
    best_score = best.score(ctx)
    with search_slot() as free:
        if not free:
            info["limited"] = "busy"
            return trip, info
        best, best_trip = _search(trip, best, best_score, first_exposure, stop_at, ctx, info)
        if ctx.wide:
            best, best_trip = _wide(best, best_trip, first_exposure, stop_at, ctx, info)
    info["extra_distance_m"] = round(best.length_m - (info["original_m"] or 0.0), 1)
    info["exposure_after_m"] = round(best.exposure_m, 1)
    return best_trip, info


def _wide(best, best_trip, first_exposure, stop_at, ctx: Context, info: dict):
    """The wider candidates (WIDE_OFFSETS): the router's route through each
    point off the straight line, kept where it scores better and is not
    busier. `info["wide"]` says how many were asked and whether one was kept."""
    if len(ctx.points) != 2:
        return best, best_trip
    vias = wide_points(ctx.points)
    asked = taken = 0
    best_score = best.score(ctx)
    locations = ctx.request.get("locations") or []
    for lon, lat in vias:
        if stop_at - routing.clock() < REFINE_ROUND_MIN_S or len(locations) < 2:
            info["limited"] = info["limited"] or "time"
            break
        request = {
            k: v for k, v in ctx.request.items() if k not in ("alternates", "exclude_locations")
        }
        request["locations"] = [
            locations[0],
            {"lon": lon, "lat": lat, "type": "through"},
            locations[-1],
        ]
        round_deadline = routing.Deadline(
            stop_at, min(ctx.deadline.per_call_s, routing.ALTERNATES_TIMEOUT_S)
        )
        asked += 1
        try:
            answer = routing._call(ctx.variant, "route", request, round_deadline)
            candidate = answer.get("trip") or {}
            if not candidate.get("legs"):
                continue
            read = analyse(candidate, ctx, routing.Deadline(stop_at, ctx.deadline.per_call_s))
        except routing.RouterRefused:
            continue
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            info["limited"] = info["limited"] or "time"
            break
        if read is None or read.events is None:
            continue
        busier = read.exposure_m > first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M
        score = read.score(ctx)
        if score < best_score - IMPROVEMENT_EPS_S and not busier:
            best, best_trip, best_score = read, candidate, score
            taken += 1
    info["wide"] = {"asked": asked, "taken": taken > 0}
    return best, best_trip


def _search(trip, best, best_score, first_exposure, stop_at, ctx: Context, info: dict):
    """The rounds of exclusion and re-routing (see `refine`): the best reading
    and its trip."""
    current = best
    best_trip = trip
    rounds = REFINE_MAX_ROUNDS if ctx.rate > 0 else CROSSING_ONLY_ROUNDS
    excluded: list[Target] = []
    # Every exclusion list sent, so that none is sent twice.
    sent: set[tuple] = set()
    stale = 0
    for number in range(rounds):
        new = crossing_targets(current, ctx) if number < CROSSING_ONLY_ROUNDS else []
        if ctx.rate > 0:
            # LTS 4 and Avoid first, if the route has any; then everything busy.
            worst_first = number == 0 and any(c[0] in ("4", "5") for c in current.classes)
            new += calm_targets(current, ctx, 4 if worst_first else 3)
        have = {t.point for t in excluded}
        new = [t for t in dict.fromkeys(new) if t.point not in have]
        if not new:
            break
        # The router takes MAX_EXCLUDES at most: what does not fit is not
        # asked for (review r1: a list cut short at the limit could send the
        # same request again a round later).
        room = MAX_EXCLUDES - len(excluded)
        if room <= 0:
            info["limited"] = "excludes"
            break
        new = new[:room]
        if stop_at - routing.clock() < REFINE_ROUND_MIN_S:
            info["limited"] = "time"
            break
        round_deadline = routing.Deadline(
            stop_at, min(ctx.deadline.per_call_s, routing.ALTERNATES_TIMEOUT_S)
        )
        candidate, asked = None, excluded
        attempts = [excluded + new]
        worst = [t for t in new if t.tier >= 4]
        if worst and len(worst) < len(new):
            attempts.append(excluded + worst)
        attempts = [a for a in attempts if tuple(t.point for t in a) not in sent]
        if not attempts:
            break
        try:
            for asked in attempts:
                sent.add(tuple(t.point for t in asked))
                request = {k: v for k, v in ctx.request.items() if k != "alternates"}
                request["exclude_locations"] = [
                    {"lon": t.point[0], "lat": t.point[1]} for t in asked
                ]
                try:
                    answer = routing._call(ctx.variant, "route", request, round_deadline)
                except routing.RouterRefused:
                    # Every way out is excluded: ask again with less.
                    continue
                candidate = answer.get("trip") or {}
                if candidate.get("legs"):
                    break
                candidate = None
            if candidate is None:
                info["limited"] = "no_route"
                break
            current = analyse(candidate, ctx, routing.Deadline(stop_at, ctx.deadline.per_call_s))
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            info["limited"] = "time"
            break
        excluded = asked
        info["excluded"] = len(excluded)
        if current is None:
            info["limited"] = "untraceable"
            break
        info["rounds"] += 1
        score = current.score(ctx)
        busier = current.exposure_m > first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M
        # A candidate whose junctions could not be read (the database or the
        # router failing) would score as if it had none: it is not taken
        # (review r1), though the search may go on from it.
        unread = current.events is None
        if score < best_score - IMPROVEMENT_EPS_S and not busier and not unread:
            best, best_trip, best_score, stale = current, candidate, score, 0
        else:
            stale += 1
            if stale >= REFINE_PATIENCE:
                break
    return best, best_trip
