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
import logging
import math
from dataclasses import dataclass, field

from django.db import connection

from pipeline.schema import PATH_RULES, SIDEPATH_RULES
from routemaker import intersections as model
from routemaker import trace_junctions
from routemaker.geo import Point, haversine

from . import junctions, presets, routing, trailseek

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

# How many searches run at once. Each makes up to about 20 router calls (review
# r1: 5 rounds of a route, its trace and the /locates, and the detour probe), one
# after another, and four at once saturate a router's threads (`concurrency` 4
# in valhalla/*.json). There is no limit of the search's own: it runs only
# inside an API routing request, which holds one of the deployment's
# `ROUTING_CONCURRENCY` slots (`core.ratelimit.ROUTING_IN_FLIGHT`, PostgreSQL
# advisory locks, 3 on compose's 7 workers), and a long ride - the only
# request with a pool of its own - never runs it (`routing._refine_limit`);
# the weekday trail check (`check_weekday_trails`) plans one route at a time. So
# at most `ROUTING_CONCURRENCY` searches run at once across the deployment,
# below the router's threads (review r2: the per-process and per-container lock
# files round 1 added could never all be taken, and were dropped).
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
    # Whether the trail seek runs after them (`trailseek.seek_for`), the segment
    # schema it reads, and whether the rider asked to avoid gravel.
    seek: bool = False
    schema: str = ""
    avoid_gravel: bool = False
    # The ways the exclusion search kept excluding for its best route, which the
    # seek keeps excluding (set by the search).
    kept_excludes: list = field(default_factory=list)
    # The trail credit (`presets.trail_credit_for`, OWNER-DECISIONS 202): metres
    # of quiet riding each metre of trail is worth in the score. 0 on every ride
    # type but Trailmaxxing.
    trail_credit: float = 0.0


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
    # Metres of trail (`trail_flags`) and, for each piece, whether it is one;
    # both only where the plan has a trail credit.
    trail_m: float = 0.0
    trail_pieces: list = field(default_factory=list)

    def score(self, ctx: Context) -> float:
        """The router's cost plus the extra price, less the trail credit (see
        the module docstring)."""
        penalty = model.penalty_m(self.events) if self.events else 0.0
        extra = (
            ctx.rate * self.exposure_m
            + ctx.weight * penalty
            + ctx.climb_weight * self.climb_m
            - ctx.trail_credit * self.trail_m
        )
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


# What counts as trail in the score's credit (OWNER-DECISIONS 202): the same
# predicate the seek reads its corridors by (`trailseek.corridor_segments`): a
# path or protected way, or a road closed to cars at the ride time (the
# facility is then "path"), at LTS 1 or 2.
TRAIL_KINDS = frozenset({"path", "protected"})
TRAIL_TIERS = frozenset({"1", "2"})


def trail_flags(pieces: list, classes: list, ctx: Context) -> list[bool]:
    """For each traced piece, whether it is trail. Before the facility column
    exists (the live table until its rebuild) the table's recorded rule says it,
    as `pipeline.schema.trails_predicate` does for the map."""
    if ctx.with_facility:
        return [kind in TRAIL_KINDS and tier in TRAIL_TIERS for tier, kind in classes]
    query = routing._STRESS_JOIN.format(
        schema=ctx.schema,
        tier="seg.stress_tier",
        facility="seg.stress_rule",
        columns="s.stress_rule",
    )
    rules = PATH_RULES | SIDEPATH_RULES
    arrays = [[p.way_id for p in pieces], [p.lon for p in pieces], [p.lat for p in pieces]]
    with connection.cursor() as cursor:
        cursor.execute(query, arrays)
        return [rule in rules and tier in (1, 2) for tier, rule in cursor.fetchall()]


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
    flags = trail_flags(pieces, classes, ctx) if ctx.trail_credit > 0 else []
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
        trail_m=sum(p.metres for p, on in zip(pieces, flags, strict=False) if on),
        trail_pieces=flags,
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
    original = best
    info["original_m"] = round(best.length_m, 1)
    info["exposure_before_m"] = round(best.exposure_m, 1)
    if ctx.trail_credit > 0:
        info["trail_credit"] = ctx.trail_credit
        info["trail_before_m"] = round(best.trail_m, 1)
    best_score = best.score(ctx)
    best, best_trip = _search(trip, best, best_score, first_exposure, stop_at, ctx, info)
    if ctx.wide:
        best, best_trip = _wide(best, best_trip, first_exposure, stop_at, ctx, info)
    if ctx.seek:
        best, best_trip = _seek(best, best_trip, first_exposure, ctx, info, original)
    info["extra_distance_m"] = round(best.length_m - (info["original_m"] or 0.0), 1)
    info["exposure_after_m"] = round(best.exposure_m, 1)
    if ctx.trail_credit > 0:
        info["trail_after_m"] = round(best.trail_m, 1)
    return best_trip, info


def _through(vias, stop_at, ctx: Context, excludes=(), leg: int = 0):
    """The router's route from the leg's start through `vias` (each a `through`
    location) to its end, read: (reading, trip), (None, None) where there is no
    route or it could not be read, or "time" where the budget or the router ran
    out. The reading's junctions may be None (the caller decides). `leg` is the
    plan's leg (the stretch between consecutive locations); the one leg is asked
    for alone."""
    locations = ctx.request.get("locations") or []
    request = {k: v for k, v in ctx.request.items() if k not in ("alternates", "exclude_locations")}
    if excludes:
        request["exclude_locations"] = [{"lon": lon, "lat": lat} for lon, lat in excludes]
    request["locations"] = [
        locations[leg],
        *({"lon": lon, "lat": lat, "type": "through"} for lon, lat in vias),
        locations[leg + 1],
    ]
    round_deadline = routing.Deadline(
        stop_at, min(ctx.deadline.per_call_s, routing.ALTERNATES_TIMEOUT_S)
    )
    try:
        answer = routing._call(ctx.variant, "route", request, round_deadline)
        candidate = answer.get("trip") or {}
        if not candidate.get("legs"):
            return None, None
        read = analyse(candidate, ctx, routing.Deadline(stop_at, ctx.deadline.per_call_s))
    except routing.RouterRefused:
        return None, None
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        return "time", None
    return read, candidate


# What a metre of each tier counts in the score (Analysis.exposure_m).
EXPOSURE_WEIGHTS = {"3": 1.0, "4": 2.0, "5": 3.0}

Spans = list[tuple[float, float, float]]


def route_spans(
    analysis: Analysis, lo: float = 0.0, hi: float | None = None
) -> tuple[Spans, Spans, float | None]:
    """The route's busy stretches and its trail stretches, each (from, to,
    weight) in traced metres from `lo` (the busy stretches weighted by
    EXPOSURE_WEIGHTS, the trail's 1), between `lo` and `hi` (the whole route by
    default), and the traced length between them (None for a route with no
    pieces)."""
    busy: Spans = []
    trail: Spans = []
    along = 0.0
    for number, (piece, (tier, _kind)) in enumerate(
        zip(analysis.pieces, analysis.classes, strict=False)
    ):
        a, b = along, along + piece.metres
        along = b
        if b <= lo or (hi is not None and a >= hi):
            continue
        a, b = max(a, lo), b if hi is None else min(b, hi)
        weight = EXPOSURE_WEIGHTS.get(tier, 0.0)
        if weight:
            busy.append((a - lo, b - lo, weight))
        if number < len(analysis.trail_pieces) and analysis.trail_pieces[number]:
            trail.append((a - lo, b - lo, 1.0))
    traced = (along if hi is None else min(hi, along)) - lo
    return busy, trail, (traced or None)


def exposure_spans(analysis: Analysis) -> tuple[Spans, float | None]:
    """The route's busy stretches as (from, to, weight) in traced metres, and
    its traced length (None for a route with no pieces)."""
    busy, _trail, traced = route_spans(analysis)
    return busy, traced


def leg_bounds(analysis: Analysis) -> list[tuple[float, float]]:
    """Where each leg of the route starts and ends, in traced metres."""
    total = sum(piece.metres for piece in analysis.pieces)
    edges = [0.0, *analysis.via_m, total]
    return list(zip(edges, edges[1:], strict=False))


def _leg_trip(trip: dict, number: int) -> dict:
    """One leg of a trip as a trip of its own."""
    leg = (trip.get("legs") or [])[number]
    return {"legs": [leg], "summary": leg.get("summary") or {}}


# What a trip's summary adds up (the legs' own are summed the same way).
SUMMED = ("length", "time", "cost")


def _splice(trip: dict, number: int, leg_trip: dict) -> dict:
    """The trip with its `number`th leg replaced by the one leg of `leg_trip`."""
    legs = list(trip.get("legs") or [])
    old, new = legs[number], leg_trip["legs"][0]
    legs[number] = new
    summary = dict(trip.get("summary") or {})
    before, after = old.get("summary") or {}, new.get("summary") or {}
    for key in SUMMED:
        if key in summary and key in before and key in after:
            summary[key] = summary[key] - before[key] + after[key]
    return {**trip, "legs": legs, "summary": summary}


def _seek(best, best_trip, first_exposure, ctx: Context, info: dict, original=None):
    """The trail seek (`core.trailseek`), leg by leg (OWNER-DECISIONS 203): for
    each stretch between consecutive locations, the router's route through the
    entry and exit of the best corridors of trail and protected lane near the
    leg's line, each kept where it scores better and is not busier (the same
    score and the same Traffic-wins guard as every other candidate, the guard
    against the leg's own exposure as the router first gave it). A route is
    asked for one leg at a time, and a leg taken is spliced into the trip.

    The seek's whole budget is SEEK_BUDGET_S, past the search's; each leg that
    can run gets its share of what is left, by its straight-line span, and at
    least SEEK_LEG_MIN_S (a candidate's worth), what a leg leaves unused going to the next.
    `info["seek"]` says what was found and asked: `asked` counts the proposals
    asked for, `routes` the router's routes (a proposal asked again without the
    exclusions is two), and `whole_trip` what became of a plan with stops'
    spliced trip (`taken`, `busier`, `unread`; None where nothing was spliced)."""
    seek = info["seek"] = {
        "corridors": 0,
        "asked": 0,
        "routes": 0,
        "taken": False,
        "limited": None,
        "whole_trip": None,
        "tried": [],
        "legs": 0,
    }
    if ctx.roadway_only:
        # A ride on the no-trail graph (Group Ride with trails off): there are
        # no trails to seek, and through points would snap to the roads beside
        # them (review r1).
        seek["limited"] = "roadway_only"
        return best, best_trip
    locations = ctx.request.get("locations") or []
    count = len(locations) - 1
    legs = best_trip.get("legs") or []
    if count < 1 or len(ctx.points) != len(locations) or len(legs) != count:
        seek["limited"] = "points"
        return best, best_trip
    seek["legs"] = count
    spans = [
        haversine(Point(*ctx.points[k][:2]), Point(*ctx.points[k + 1][:2])) for k in range(count)
    ]
    runnable = [k for k in range(count) if spans[k] >= trailseek.SEEK_MIN_SPAN_M]
    if not runnable:
        seek["limited"] = "span"
        return best, best_trip
    stop_at = min(
        routing.clock() + trailseek.SEEK_BUDGET_S, ctx.deadline.at - REFINE_TRACE_RESERVE_S
    )
    if stop_at - routing.clock() < trailseek.SEEK_ROUND_MIN_S:
        seek["limited"] = "time"
        return best, best_trip
    # What the router first gave each leg: the guard's reference.
    first_legs = None
    if count > 1 and original is not None and len(original.via_m) == count - 1:
        first_legs = [
            sum(w * (b - a) for a, b, w in route_spans(original, lo, hi)[0])
            for lo, hi in leg_bounds(original)
        ]
    trip, taken = best_trip, False
    for turn, k in enumerate(runnable):
        now = routing.clock()
        left = stop_at - now
        if left < trailseek.SEEK_ROUND_MIN_S:
            seek["limited"] = "time"
            break
        share = left * spans[k] / sum(spans[j] for j in runnable[turn:])
        leg_stop = min(stop_at, now + max(share, trailseek.SEEK_LEG_MIN_S))
        if count == 1:
            leg_trip, incumbent, reference = trip, best, first_exposure
        else:
            leg_trip = _leg_trip(trip, k)
            try:
                incumbent = analyse(
                    leg_trip, ctx, routing.Deadline(leg_stop, ctx.deadline.per_call_s)
                )
            except (routing.DeadlineExceeded, routing.RouterUnavailable):
                seek["limited"] = "time"
                break
            if incumbent is None:
                continue
            reference = first_legs[k] if first_legs else incumbent.exposure_m
        got = _seek_leg(k, leg_trip, incumbent, reference, leg_stop, ctx, seek)
        if got is not None:
            seek["taken"] = taken = True
            if count == 1:
                best, trip = got
            else:
                trip = _splice(trip, k, got[1])
        if seek["limited"] in ("time", "table"):
            break
    if count > 1 and taken:
        # One reading of the whole route, which the answer reuses: the legs'
        # traces are remembered, the junctions read once.
        try:
            read = analyse(trip, ctx, ctx.deadline)
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            read = None
        if read is None or read.events is None:
            seek["taken"] = False
            seek["whole_trip"] = "unread"
            seek["limited"] = seek["limited"] or "unread"
            return best, best_trip
        # Traffic wins for the whole trip too (OWNER-DECISIONS 61, 188: "2% +
        # 164 ft" for the plan): each leg's allowance is its own, so n legs
        # could otherwise add n x 50 m between them (review r1).
        if read.exposure_m > _allowance(first_exposure):
            seek["taken"] = False
            # Its own key as well, so that a "time" from a later leg does not
            # hide it (review r2).
            seek["whole_trip"] = "busier"
            seek["limited"] = seek["limited"] or "busier"
            return best, best_trip
        seek["whole_trip"] = "taken"
        return read, trip
    return best, trip


def _seek_leg(k, leg_trip, incumbent, reference, stop_at, ctx: Context, seek: dict):
    """The seek on one leg: (reading, trip) of the leg if a candidate was kept,
    else None. `reference` is the leg's exposure as the router first gave it
    (the Traffic-wins guard's)."""
    start, end = ctx.points[k][:2], ctx.points[k + 1][:2]
    span = haversine(Point(*start), Point(*end))
    shape = [
        point
        for leg in leg_trip.get("legs") or []
        for point in routing.decode_polyline6(leg.get("shape", ""))
    ]
    step = max(1, len(shape) // 400)
    guide = [[tuple(start), tuple(end)]] + ([shape[::step] + [shape[-1]]] if shape else [])
    band = trailseek.band_m(span)
    # The leg's deadline before the table, and the table's own statement timeout
    # inside what the leg has (review r1).
    left = stop_at - routing.clock()
    if left < trailseek.SEEK_ROUND_MIN_S:
        seek["limited"] = "time"
        return None
    try:
        segments = trailseek.corridor_segments(
            ctx.schema,
            guide,
            band,
            ctx.with_facility,
            ctx.when,
            ctx.avoid_gravel,
            timeout_s=min(trailseek.TABLE_TIMEOUT_S, left),
        )
    except trailseek.SeekOutOfTime:
        logger.warning("the trail seek's table read ran past its time")
        seek["limited"] = "time"
        return None
    except Exception:  # noqa: BLE001 - a plan is answered without the seek
        logger.warning("the trail seek could not read the segment table", exc_info=True)
        seek["limited"] = "table"
        return None
    # And again before the corridor search: there is no use finding corridors
    # there is no time to ask for.
    if stop_at - routing.clock() < trailseek.SEEK_ROUND_MIN_S:
        seek["limited"] = "time"
        return None
    route = shape or [tuple(start)]
    segments = trailseek.in_band(segments, start, end, route, band)
    busy, trail, traced_m = route_spans(incumbent)
    try:
        corridors = trailseek.find_corridors(
            segments,
            start,
            end,
            shape,
            busy,
            traced_m,
            ctx.rate,
            ctx.trail_credit,
            trail,
            stop_at=stop_at - trailseek.SEEK_ROUND_MIN_S,
            clock=routing.clock,
        )
    except trailseek.SeekOutOfTime:
        seek["limited"] = "time"
        return None
    except trailseek.SeekError:
        logger.error("the trail seek's corridor search failed", exc_info=True)
        seek["limited"] = "error"
        return None
    seek["corridors"] += len(corridors)
    best_score = incumbent.score(ctx)
    # The exclusions the search kept for its best route, those in this leg's
    # band only (review r1: up to 150 were sent with every candidate, most of
    # them nowhere near the corridor).
    nearby = trailseek.points_in_band(ctx.kept_excludes, start, end, route, band)
    kept = None
    for proposal in trailseek.propose(corridors):
        if stop_at - routing.clock() < trailseek.SEEK_ROUND_MIN_S:
            seek["limited"] = "time"
            break
        seek["asked"] += 1
        # With the exclusions the best route so far was found under (so that the
        # way to a trail is as calm as the way the search found), then, if the
        # router has no route with them, without; and without them as well where
        # the route with them is much longer than the corridor's detour says.
        excluded = list(nearby)
        seek["routes"] += 1
        read, candidate = _through(proposal.vias, stop_at, ctx, excluded, k)
        answers = []
        if read is None and excluded:
            seek["routes"] += 1
            read, candidate = _through(proposal.vias, stop_at, ctx, (), k)
            excluded = []
        elif (
            excluded
            and isinstance(read, Analysis)
            and read.length_m > _expected_m(incumbent, proposal)
            and stop_at - routing.clock() >= trailseek.SEEK_ROUND_MIN_S
        ):
            answers.append((read, candidate, excluded, None))
            seek["routes"] += 1
            read, candidate = _through(proposal.vias, stop_at, ctx, (), k)
            excluded = []
            answers.append((read, candidate, excluded, "longer"))
        if not answers:
            answers.append((read, candidate, excluded, None))
        out_of_time = False
        for read, candidate, excluded, retry in answers:
            if read == "time":
                out_of_time = True
                continue
            tried = {
                "leg": k,
                "excluded": len(excluded),
                "corridors": len(proposal.corridors),
                "gain_m": round(proposal.gain_m),
                "detour_m": round(proposal.detour_m),
                "outcome": "no_route",
            }
            if retry:
                tried["retry"] = retry
            seek["tried"].append(tried)
            if read is None:
                continue
            tried["length_m"] = round(read.length_m)
            tried["exposure_m"] = round(read.exposure_m)
            if read.events is None:
                tried["outcome"] = "unread"
                continue
            busier = read.exposure_m > _allowance(reference)
            score = read.score(ctx)
            tried["score_gain_s"] = round(best_score - score, 1)
            if busier:
                tried["outcome"] = "busier"
            elif score < best_score - IMPROVEMENT_EPS_S:
                tried["outcome"] = "taken"
                kept, best_score = (read, candidate), score
            else:
                tried["outcome"] = "not_better"
        if out_of_time:
            seek["limited"] = "time"
            break
    return kept


def _allowance(exposure_m: float) -> float:
    """The most exposure a candidate may have against a reference's (the
    Traffic-wins guard: EXPOSURE_TOLERANCE and EXPOSURE_SLACK_M over it)."""
    return exposure_m * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M


# A seek candidate asked with the search's exclusions is asked again without
# them when it is longer than the leg and the corridor's detour by more than
# this share and this many metres (review r1: 145 to 150 exclusions sent the
# router round them).
SEEK_RETRY_OVER = 0.15
SEEK_RETRY_SLACK_M = 500.0


def _expected_m(incumbent: Analysis, proposal) -> float:
    """The length past which a candidate is much longer than its corridor says."""
    return (incumbent.length_m + proposal.detour_m) * (1 + SEEK_RETRY_OVER) + SEEK_RETRY_SLACK_M


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
    # Every exclusion set sent, so that none is sent twice (in any order).
    sent: set[frozenset] = set()
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
        attempts = [a for a in attempts if frozenset(t.point for t in a) not in sent]
        if not attempts:
            break
        try:
            for asked in attempts:
                sent.add(frozenset(t.point for t in asked))
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
            ctx.kept_excludes = [t.point for t in excluded]
        else:
            stale += 1
            if stale >= REFINE_PATIENCE:
                break
    return best, best_trip
