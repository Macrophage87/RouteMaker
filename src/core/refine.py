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

(The 1, 2 and 3 are the preset's `presets.Exposure`: Trailmaxxing and Cargo with
passengers weigh LTS 4 at 8 and Avoid at 16, and never take a route with more
LTS 4 and Avoid metres than the router's first, leg by leg or whole; OWNER-DECISIONS
250, `more_lts4`.)

QUIET COST is what a metre of quiet-street riding costs the router at the
request's speed (`quiet_cost_per_m`: 2.2 times its time, measured on the live
router). The calm rate is `presets.calm_rate_for(stress)` (0 up to the old top
of the slider, then exponential): metres of quiet riding accepted per metre of
LTS 3 avoided, on top of the router's own price for it. The intersection weight
rises from 0.25 at the traffic tolerant end to 1 at Default (turn and
intersection costs stay active at every setting, as the literature review's
guardrail asks), and the climb weight is the hills slider's avoid half, so a
relaxed ride is not a zig-zag over a hill.

Below the top of the slider there is no cap on the detour. The search stops
when a round finds nothing left to exclude, when two rounds in a row do not
improve the score, when the router has no route left (every way out is
excluded), or when the time runs out; `info["limited"]` says which, so the
answer can say a calm route was looked for and not found.

At the top of the slider (`presets.maxcalm_for`, OWNER-DECISIONS 256 and 257,
FOLLOWUP-LONG-CALM) the rate is gone. The search keeps every candidate within the
rider's longest ride (`Context.max_m`; the default is `presets.default_max_m` of
the router's own route) and prefers the one with the least stress, in this order:
the "top" figure (metres of LTS 4 and Avoid plus the cost of each very high stress
junction, OWNER-DECISIONS 258 and 259), then the "second" (metres of LTS 3 plus the
cost of each higher stress junction, 260), then the hills preference (261), then
distance (`MAXCALM_STEPS`, `better`); a candidate longer than the longest ride is
never taken, and the router's own price for the route, and any credit for trail,
do not come into it. A trip past the working span (`REFINE_MAX_SPAN_M`) is planned leg by
leg (`refine_long`).
"""

from __future__ import annotations

import bisect
import dataclasses
import logging
import math
from dataclasses import dataclass, field

from routemaker import effort, trace_junctions
from routemaker import intersections as model
from routemaker.geo import Point, haversine

from . import junctions, legsplit, presets, routing, trailseek

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
# The most a plan with stops gives the trail seek's reading of one leg's own
# route (its trace and its junctions; measured 0.45 to 0.6 s warm), on top of
# the seek's budget rather than out of the leg's share (`_seek`; combined
# correctness review, SF1).
SEEK_LEG_READ_S = 2.0
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
    # The hills slider's avoid half as a weight, 0 at the detent and 1 at full
    # avoid (`level3`), and the hook of its seek half: how much of the effort a
    # rider prefers more of (0 today, where the search does not run while the
    # slider seeks; FOLLOWUP-HILLS-TOLERATE, 242, will set it).
    hills_weight: float = 0.0
    hills_seek_weight: float = 0.0
    # The rider's total system weight in kilograms (item 264), which the effort
    # reads (`routemaker.effort`).
    mass_kg: float = effort.MASS_KG
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
    # The top of the slider (`presets.maxcalm_for`): candidates are ranked by
    # `better`, not by the score, and none longer than `max_m` metres is taken
    # (None: no limit, as below the top).
    maxcalm: bool = False
    max_m: float | None = None
    # Where this search must end, whatever its budgets say (set for a leg of a
    # long plan: its share of the time), and how long the exclusion rounds and
    # the seek may take after the route is read.
    stop_at: float | None = None
    # The routes to offer the rider (OWNER-DECISIONS 265): (trip, reading), the
    # answer's own first, then up to ALT_MAX - 1 others (`pick_candidates`); set by
    # `refine` and `refine_long` where `options` is collected.
    candidates: list = field(default_factory=list)
    # A loop (OWNER-DECISIONS 266): the plan's last leg returns to its start, and
    # `loop_overlap` is the most of the way back that may be the way out (set by
    # `make_loop`; None: not a loop). No search candidate may share more of it.
    loop_overlap: float | None = None
    # How many routes the rider is offered at most, this one included (0: one).
    alternates: int = 0
    # Where the search keeps every candidate it read that the hold and the guards
    # allow, as (trip, reading), for a long plan to choose among across its legs
    # (`refine_long`); None: not kept.
    options: list | None = None
    search_budget_s: float = REFINE_BUDGET_S
    seek_budget_s: float = trailseek.SEEK_BUDGET_S
    # The preset's exposure weights and LTS 4 hold (`presets.exposure_for`,
    # OWNER-DECISIONS 250).
    exposure: presets.Exposure = presets.EXPOSURE_STANDARD
    # Each leg's LTS 4 and Avoid metres on the router's first route (set by
    # `refine`), which no candidate may exceed where the exposure holds them.
    first_lts4: list = field(default_factory=list)


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
    # Metres of LTS 4 and Avoid, and of LTS 3, as the classes say them.
    lts4_m: float = 0.0
    lts3_m: float = 0.0
    # The route's effort-equivalent distance, metres (`routemaker.effort`,
    # OWNER-DECISIONS 262, 263): its length weighted by the grade it rides, which
    # the Hills slider blends with the actual distance.
    effort_m: float = 0.0

    def score(self, ctx: Context) -> float:
        """The router's cost plus the extra price (see the module docstring)."""
        penalty = model.penalty_m(self.events) if self.events else 0.0
        extra = ctx.rate * self.exposure_m + ctx.weight * penalty + ctx.climb_weight * self.climb_m
        return self.cost_s + ctx.quiet_cost * extra

    @property
    def red_m(self) -> float:
        """The very high stress (red) junctions' summed cost, as metres of quiet
        riding (the junction model's own cost, 2,000 to 4,500 ft each)."""
        return junction_cost_m(self.events, "red")

    @property
    def orange_m(self) -> float:
        """The higher stress (orange) junctions' summed cost, in the same unit."""
        return junction_cost_m(self.events, "orange")

    @property
    def top_m(self) -> float:
        """The top figure of the ranking and of the LTS 4 hold: metres of LTS 4 and
        Avoid, plus the cost of the red junctions (OWNER-DECISIONS 259: "weight Very
        Stressful and LTS4 equally", in the junction's own cost)."""
        return self.lts4_m + self.red_m

    @property
    def second_m(self) -> float:
        """The second figure of the ranking (OWNER-DECISIONS 260: "Make LTS3 and
        orange crossing the same"): metres of LTS 3 plus the cost of the orange
        junctions."""
        return self.lts3_m + self.orange_m

    def key(self, ctx: Context) -> tuple[float, float, float]:
        """What the top of the slider ranks by, least first (OWNER-DECISIONS
        258-263): the top figure, the second figure, and the distance as the Hills
        slider blends it (`level3`)."""
        return (self.top_m, self.second_m, level3(self, ctx))


def level3(read: Analysis, ctx: Context) -> float:
    """The third level, least first (OWNER-DECISIONS 262: effort-equivalent
    distance in place of 261's lexicographic hills level): the actual distance and
    the effort-equivalent distance (`Analysis.effort_m`) blended by the Hills
    slider, (1 - w) x actual + w x effort, with w (`Context.hills_weight`) 0 at the
    detent, where it is the actual distance, and 1 at full avoid. Right of the
    detent more effort is better, which the search does not run for
    (`routing._refine_limit`, "seeking"); `Context.hills_seek_weight` is the hook
    FOLLOWUP-HILLS-TOLERATE (242) will use. The longest ride is in actual metres,
    not these."""
    w = ctx.hills_weight
    effort = read.effort_m or read.length_m
    return (1 - w) * read.length_m + w * effort - ctx.hills_seek_weight * effort


def junction_cost_m(events: list | None, severity: str) -> float:
    """The summed cost of the events of one severity, in metres."""
    if not events:
        return 0.0
    return sum(e.cost_ft for e in events if e.severity == severity) / model.FEET_PER_METRE


# How much better, at each level of `Analysis.key`, a candidate must be to count
# as better at that level, so that a trivial gain at a higher level does not force
# a large loss at a lower one; within the step at one level the next decides.
# The top figure: 15 m, about 50 ft (a trace's rounding and a driveway;
# OWNER-DECISIONS 258, "allow ties within about 50 ft of LTS 4"). The second: 50 m,
# about a block. The third: 50 m of distance, actual or effort-equivalent.
MAXCALM_STEPS = (15.0, 50.0, 50.0)


def better(read: Analysis, best: Analysis, ctx: Context) -> bool:
    """Whether `read` is to replace `best`: below the top of the slider, by the
    score (IMPROVEMENT_EPS_S); at the top, by `MAXCALM_STEPS` down `Analysis.key`
    (OWNER-DECISIONS 256: LTS 4 and Avoid first, then LTS 3, then the junctions,
    then distance)."""
    if not ctx.maxcalm:
        return read.score(ctx) < best.score(ctx) - IMPROVEMENT_EPS_S
    for step, got, have in zip(MAXCALM_STEPS, read.key(ctx), best.key(ctx), strict=True):
        if have - got > step:
            return True
        if got - have > step:
            return False
    return False


def too_long(length_m: float, ctx: Context) -> bool:
    """Whether a route of `length_m` is past the longest ride."""
    return ctx.max_m is not None and length_m > ctx.max_m


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


def analyse(
    trip: dict, ctx: Context, deadline: routing.Deadline, with_events: bool = True
) -> Analysis | None:
    """A trip's length, exposure, climb and junction events; None where a leg
    cannot be traced. Remembered per plan, by the trip's shapes. Without
    `with_events` (a reading of the stress alone, which is not remembered: its
    traces are) the events are None and no /locate is asked."""
    legs = trip.get("legs") or []
    key = tuple(leg.get("shape", "") for leg in legs)
    if with_events and key in ctx.analyses:
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
    weights = ctx.exposure.weights
    result = Analysis(
        length_m=float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0,
        cost_s=routing._router_cost(trip),
        exposure_m=sum(weights[tier] * stress[tier] for tier in weights),
        climb_m=routing._climb_of(trip),
        pieces=pieces,
        classes=classes,
        events=events_of_raws(raws, ctx, deadline) if with_events else None,
        via_m=via_m,
        marks=marks,
        lts4_m=stress["4"] + stress["5"],
        lts3_m=stress["3"],
        effort_m=effort.effort_equivalent_m(
            routing.grade_profile(trip),
            float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0,
            ctx.mass_kg,
        )
        or float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0,
    )
    if with_events:
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
    hard_stop = ctx.deadline.at - REFINE_TRACE_RESERVE_S
    if ctx.stop_at is not None:
        hard_stop = min(hard_stop, ctx.stop_at)
    stop_at = min(routing.clock() + ctx.search_budget_s, hard_stop)
    first_exposure = best.exposure_m
    original = best
    info["original_m"] = round(best.length_m, 1)
    info["exposure_before_m"] = round(best.exposure_m, 1)
    info["lts4_m_before"] = round(best.lts4_m, 1)
    info["lts3_m_before"] = round(best.lts3_m, 1)
    ctx.first_lts4 = top_by_leg(best)
    if ctx.options is not None:
        ctx.options.append((trip, best))
    info["top_m_before"] = round(best.top_m, 1)
    if ctx.exposure.hold_lts4:
        info["lts4_before_m"] = round(best.lts4_m, 1)
    best, best_trip = _search(trip, best, first_exposure, stop_at, ctx, info)
    if ctx.wide:
        best, best_trip = _wide(best, best_trip, first_exposure, stop_at, ctx, info)
    if ctx.seek:
        best, best_trip = _seek(best, best_trip, first_exposure, ctx, info, original)
    info["extra_distance_m"] = round(best.length_m - (info["original_m"] or 0.0), 1)
    info["exposure_after_m"] = round(best.exposure_m, 1)
    info["lts4_m_after"] = round(best.lts4_m, 1)
    info["lts3_m_after"] = round(best.lts3_m, 1)
    info["top_m_after"] = round(best.top_m, 1)
    if ctx.exposure.hold_lts4:
        info["lts4_after_m"] = round(best.lts4_m, 1)
    if ctx.options is not None and ctx.alternates:
        pool = [(best_trip, best)] + [o for o in ctx.options if o[0] is not best_trip]
        ctx.candidates = more_routes(
            pick_candidates(pool, ctx, ctx.first_lts4), ctx, ctx.first_lts4
        )
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


# What a metre of each tier counts in the score (Analysis.exposure_m) on every
# ride but the stress-averse ones (`presets.Exposure`, OWNER-DECISIONS 250).
EXPOSURE_WEIGHTS = presets.EXPOSURE_STANDARD.weights
# The tiers the LTS 4 hold counts (OWNER-DECISIONS 250): LTS 4 and Avoid.
LTS4_TIERS = frozenset({"4", "5"})
# Metres of LTS 4 a candidate may have over the router's first route before the
# hold refuses it: a trace's rounding, not a stretch of road.
LTS4_SLACK_M = 1.0

Spans = list[tuple[float, float, float]]


def top_by_leg(analysis: Analysis) -> list[float]:
    """Each leg's top figure: LTS 4 and Avoid metres plus the cost of the red
    junctions in it (`Analysis.top_m`), by traced metres (`leg_bounds`)."""
    bounds = leg_bounds(analysis)
    out = lts4_by_leg(analysis)
    for event in analysis.events or ():
        if event.severity != "red":
            continue
        for k, (lo, hi) in enumerate(bounds):
            if lo <= event.m < hi or (k == len(bounds) - 1 and event.m >= hi):
                out[k] += event.cost_ft / model.FEET_PER_METRE
                break
    return out


def lts4_by_leg(analysis: Analysis) -> list[float]:
    """Each leg's LTS 4 and Avoid metres, in traced metres (`leg_bounds`)."""
    bounds = leg_bounds(analysis)
    out = [0.0] * len(bounds)
    along = 0.0
    for piece, (tier, _kind) in zip(analysis.pieces, analysis.classes, strict=False):
        a, b = along, along + piece.metres
        along = b
        if tier not in LTS4_TIERS:
            continue
        for k, (lo, hi) in enumerate(bounds):
            out[k] += max(0.0, min(b, hi) - max(a, lo))
    return out


def more_lts4(read: Analysis, reference: list[float], ctx: Context) -> bool:
    """Whether the LTS 4 hold refuses a candidate (OWNER-DECISIONS 250, amended by
    259): on a stress-averse ride, a larger top figure (LTS 4 and Avoid metres plus
    the cost of the red junctions, `Analysis.top_m`) than `reference` (the router's
    first route's, a leg's each) for the whole of it, or for any leg where it has
    the reference's legs. So LTS 4 may be traded for a red junction's worth, never
    for nothing. Never on another ride."""
    if not ctx.exposure.hold_lts4 or not reference:
        return False
    legs = top_by_leg(read)
    if sum(legs) > sum(reference) + LTS4_SLACK_M:
        return True
    if len(legs) != len(reference):
        return False
    return any(got > first + LTS4_SLACK_M for got, first in zip(legs, reference, strict=True))


def route_spans(
    analysis: Analysis,
    lo: float = 0.0,
    hi: float | None = None,
    weights: dict[str, float] | None = None,
) -> tuple[Spans, float | None]:
    """The route's busy stretches as (from, to, weight) in traced metres from
    `lo` (weighted by `weights`, the plan's exposure weights, EXPOSURE_WEIGHTS by
    default), between `lo` and `hi` (the whole route by default), and the traced
    length between them (None for a route with no pieces)."""
    weights = EXPOSURE_WEIGHTS if weights is None else weights
    busy: Spans = []
    along = 0.0
    for piece, (tier, _kind) in zip(analysis.pieces, analysis.classes, strict=False):
        a, b = along, along + piece.metres
        along = b
        if b <= lo or (hi is not None and a >= hi):
            continue
        a, b = max(a, lo), b if hi is None else min(b, hi)
        weight = weights.get(tier, 0.0)
        if weight:
            busy.append((a - lo, b - lo, weight))
    traced = (along if hi is None else min(hi, along)) - lo
    return busy, (traced or None)


def exposure_spans(analysis: Analysis) -> tuple[Spans, float | None]:
    """The route's busy stretches as (from, to, weight) in traced metres, and
    its traced length (None for a route with no pieces)."""
    return route_spans(analysis)


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
    On a plan with stops each leg's own route is read first, on an allowance of
    its own (SEEK_LEG_READ_S) that the budget is extended by, and a leg that runs
    out of its share ("time") leaves the rest to the legs after it.
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
    hard_stop = ctx.deadline.at - REFINE_TRACE_RESERVE_S
    if ctx.stop_at is not None:
        hard_stop = min(hard_stop, ctx.stop_at)
    stop_at = min(routing.clock() + ctx.seek_budget_s, hard_stop)
    if stop_at - routing.clock() < trailseek.SEEK_ROUND_MIN_S:
        seek["limited"] = "time"
        return best, best_trip
    # What the router first gave each leg: the guard's reference.
    first_legs = None
    if count > 1 and original is not None and len(original.via_m) == count - 1:
        first_legs = [
            sum(w * (b - a) for a, b, w in route_spans(original, lo, hi, ctx.exposure.weights)[0])
            for lo, hi in leg_bounds(original)
        ]
    trip, taken = best_trip, False
    # The latest the seek may run to at all is `hard_stop`, whatever the legs'
    # readings take.
    for turn, k in enumerate(runnable):
        before = stop_at - routing.clock()
        if before < trailseek.SEEK_ROUND_MIN_S:
            seek["limited"] = "time"
            break
        if count == 1:
            leg_trip, incumbent, reference = trip, best, first_exposure
            reference_lts4 = list(ctx.first_lts4)
        else:
            # The leg's own route, read with its junctions, on an allowance of
            # its own (combined correctness review, SF1): the reading is what
            # the leg is measured against, not one of its candidates, so it is
            # not taken out of the leg's share. Measured 0.45 to 0.6 s, which
            # left a leg given SEEK_LEG_MIN_S under SEEK_ROUND_MIN_S once it
            # had read its table, every time.
            leg_trip = _leg_trip(trip, k)
            started = routing.clock()
            try:
                incumbent = analyse(
                    leg_trip,
                    ctx,
                    routing.Deadline(
                        min(hard_stop, started + SEEK_LEG_READ_S), ctx.deadline.per_call_s
                    ),
                )
            except (routing.DeadlineExceeded, routing.RouterUnavailable):
                # This leg could not be read in its allowance; a later one may.
                seek["limited"] = "time"
                continue
            finally:
                stop_at = min(hard_stop, stop_at + (routing.clock() - started))
            if incumbent is None:
                continue
            reference = first_legs[k] if first_legs else incumbent.exposure_m
            reference_lts4 = (
                [ctx.first_lts4[k]]
                if len(ctx.first_lts4) == count
                else [sum(top_by_leg(incumbent))]
            )
        now = routing.clock()
        left = stop_at - now
        if left < trailseek.SEEK_ROUND_MIN_S:
            seek["limited"] = "time"
            break
        share = left * spans[k] / sum(spans[j] for j in runnable[turn:])
        leg_stop = min(stop_at, now + max(share, trailseek.SEEK_LEG_MIN_S))
        room = None if ctx.max_m is None else ctx.max_m - _trip_m(trip)
        got = _seek_leg(
            k, leg_trip, incumbent, reference, leg_stop, ctx, seek, reference_lts4, room
        )
        if got is not None:
            seek["taken"] = taken = True
            if count == 1:
                best, trip = got
            else:
                trip = _splice(trip, k, got[1])
        # A leg that ran out of its own share leaves the rest of the budget to
        # the legs after it (SF1: leg 0's "time" ended the loop, so the longer
        # leg 1 of Bethesda - Silver Spring - College Park was never tried); a
        # table that cannot be read cannot be read for any leg.
        if seek["limited"] == "table":
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
        # A loop's way back stays a different way (OWNER-DECISIONS 266).
        if loop_refused(read, ctx):
            seek["taken"] = False
            seek["whole_trip"] = "overlap"
            seek["limited"] = seek["limited"] or "overlap"
            return best, best_trip
        # And never past the longest ride.
        if too_long(read.length_m, ctx):
            seek["taken"] = False
            seek["whole_trip"] = "too_long"
            seek["limited"] = seek["limited"] or "too_long"
            return best, best_trip
        # And never more LTS 4 than the router's first route (item 250).
        if more_lts4(read, ctx.first_lts4, ctx):
            seek["taken"] = False
            seek["whole_trip"] = "more_lts4"
            seek["limited"] = seek["limited"] or "more_lts4"
            return best, best_trip
        seek["whole_trip"] = "taken"
        return read, trip
    return best, trip


def _trip_m(trip: dict) -> float:
    """A trip's length in metres, from its summary."""
    return float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0


def _seek_leg(
    k,
    leg_trip,
    incumbent,
    reference,
    stop_at,
    ctx: Context,
    seek: dict,
    reference_lts4=(),
    room_m: float | None = None,
):
    """The seek on one leg: (reading, trip) of the leg if a candidate was kept,
    else None. `reference` is the leg's exposure as the router first gave it
    (the Traffic-wins guard's), and `reference_lts4` its LTS 4 and Avoid metres
    then, as a one-item list (the LTS 4 hold's, OWNER-DECISIONS 250). `room_m` is
    how many metres longer than the incumbent a candidate may be before the trip
    is past the longest ride (None: no limit)."""
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
    busy, traced_m = route_spans(incumbent, weights=ctx.exposure.weights)
    try:
        corridors = trailseek.find_corridors(
            segments,
            start,
            end,
            shape,
            busy,
            traced_m,
            ctx.rate,
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
    current = incumbent
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
            tried["lts4_m"] = round(read.lts4_m)
            tried["lts3_m"] = round(read.lts3_m)
            if not ctx.maxcalm:
                tried["score_gain_s"] = round(current.score(ctx) - read.score(ctx), 1)
            if busier:
                tried["outcome"] = "busier"
            elif more_lts4(read, list(reference_lts4), ctx):
                tried["outcome"] = "more_lts4"
            elif room_m is not None and read.length_m - incumbent.length_m > room_m:
                tried["outcome"] = "too_long"
            elif better(read, current, ctx):
                tried["outcome"] = "taken"
                kept, current = (read, candidate), read
                if ctx.options is not None:
                    ctx.options.append((candidate, read))
            else:
                tried["outcome"] = "not_better"
                if ctx.options is not None:
                    ctx.options.append((candidate, read))
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
        busier = busier or more_lts4(read, ctx.first_lts4, ctx) or too_long(read.length_m, ctx)
        if better(read, best, ctx) and not busier:
            best, best_trip = read, candidate
            taken += 1
    info["wide"] = {"asked": asked, "taken": taken > 0}
    return best, best_trip


def _halves(targets: list[Target]) -> list[list[Target]]:
    """The first and the second half of a list of targets, for a round whose
    whole set sent the route past the longest ride."""
    if len(targets) < 4:
        return []
    middle = len(targets) // 2
    return [targets[:middle], targets[middle:]]


def _search(trip, best, first_exposure, stop_at, ctx: Context, info: dict):
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
        if ctx.max_m is not None:
            # A set that sends the route past the longest ride is tried again
            # with less (each half of it).
            attempts.extend(excluded + half for half in _halves(new))
        attempts = [a for a in attempts if frozenset(t.point for t in a) not in sent]
        if not attempts:
            break
        over = False
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
                    if too_long(_trip_m(candidate), ctx):
                        # Not read: it is past the longest ride, however calm.
                        over = True
                        candidate = None
                        continue
                    break
                candidate = None
            if candidate is None:
                info["limited"] = "max_distance" if over else "no_route"
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
        busier = current.exposure_m > first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M
        # Never more LTS 4 than the router's first route on a stress-averse ride
        # (OWNER-DECISIONS 250), however much calmer the rest of it scores. A
        # round the hold refuses does not count against the search's patience
        # (GATE-corr SF2: it said nothing about whether the next round would
        # improve).
        held = more_lts4(current, ctx.first_lts4, ctx)
        # A loop's way back stays a different way (OWNER-DECISIONS 266).
        busier = busier or loop_refused(current, ctx)
        # A candidate whose junctions could not be read (the database or the
        # router failing) would score as if it had none: it is not taken
        # (review r1), though the search may go on from it.
        unread = current.events is None
        if ctx.options is not None and not (busier or held or unread):
            ctx.options.append((candidate, current))
        if better(current, best, ctx) and not (busier or held) and not unread:
            best, best_trip, stale = current, candidate, 0
            ctx.kept_excludes = [t.point for t in excluded]
        elif not held:
            stale += 1
            if stale >= REFINE_PATIENCE:
                break
    return best, best_trip


# --- A long trip, leg by leg (OWNER-DECISIONS 256, FOLLOWUP-LONG-CALM) ----------------

# The least time (seconds) a long plan must have left, after the router's own
# route, to be cut into legs at all; and what is kept back from the plan's budget
# for the whole route's junctions, read once at the end.
LONG_MIN_START_S = 12.0
LONG_FINAL_RESERVE_S = REFINE_TRACE_RESERVE_S
# A leg's share of its time that goes to the exclusion rounds; the rest is the
# seek's.
LONG_SEARCH_SHARE = 0.7
# A leg is searched only if its time share is at least this (seconds): a round
# and the reading of its route.
LONG_LEG_MIN_S = REFINE_ROUND_MIN_S + 1.0
# What a leg's weight counts a metre of LTS 4 or Avoid as, against a metre of
# LTS 3 (the order the search ranks by, in a weight).
LONG_LTS4_PRIORITY = 8.0


def _busy_flags(analysis: Analysis) -> list[bool]:
    return [tier in ("3", "4", "5") for tier, _kind in analysis.classes]


def long_legs(whole: Analysis, ctx: Context) -> list[dict]:
    """The legs a long trip is searched in: each stretch between the plan's own
    locations cut into pieces of about `legsplit.LEG_TARGET_SPAN_M` of straight
    line, at points on the router's own route (`legsplit.split_points`). Each is
    {"a", "b": locations, "user": the plan's leg}."""
    locations = ctx.request.get("locations") or []
    bounds = leg_bounds(whole)
    marks = _marks(whole)
    runs = legsplit.busy_runs([p.metres for p in whole.pieces], _busy_flags(whole))
    legs: list[dict] = []
    for k in range(len(locations) - 1):
        a, b = ctx.points[k][:2], ctx.points[k + 1][:2]
        count = legsplit.leg_count(haversine(Point(*a), Point(*b)))
        lo, hi = bounds[k] if k < len(bounds) else (0.0, 0.0)
        cuts = legsplit.split_points(marks, runs, lo, hi, count)
        stops = [locations[k]] + [
            {"lon": lon, "lat": lat, "type": "break"} for _at, lon, lat in cuts
        ]
        stops.append(locations[k + 1])
        legs.extend({"a": x, "b": y, "user": k} for x, y in zip(stops, stops[1:], strict=False))
    return legs


def _joined(trips: list[dict], like: dict) -> dict:
    """The legs' trips as one trip: each trip's legs, in order, with the
    summary's sums added up (the other keys are `like`'s, the router's own)."""
    summary = dict(like.get("summary") or {})
    for key in SUMMED:
        summary[key] = sum(float((t.get("summary") or {}).get(key, 0.0)) for t in trips)
    return {**like, "legs": [leg for t in trips for leg in t.get("legs") or []], "summary": summary}


def _merge_seek(seeks: list[tuple[int, dict]]) -> dict | None:
    """The legs' seek reports as one: the counts added, the rows named by leg."""
    if not seeks:
        return None
    out: dict = {
        "corridors": 0,
        "asked": 0,
        "routes": 0,
        "taken": False,
        "limited": None,
        "whole_trip": None,
        "tried": [],
        "legs": len(seeks),
    }
    for number, seek in seeks:
        for key in ("corridors", "asked", "routes"):
            out[key] += seek.get(key) or 0
        out["taken"] = out["taken"] or bool(seek.get("taken"))
        out["limited"] = out["limited"] or seek.get("limited")
        out["tried"].extend({**row, "leg": number} for row in seek.get("tried") or [])
    return out


def _point_of(location: dict) -> list[float]:
    return [location["lon"], location["lat"]]


# --- A loop (OWNER-DECISIONS 266) --------------------------------------------------------
#
# "Turn an out-and-back into a loop": the way back is asked for with the way out's
# edges excluded (`exclude_locations` at points along it, thinned until the router
# has a route: the overlap is preferred away, not forced, so a loop may still use the
# one bridge or the one access trail there is). The overlap is the metres of the way
# back on a way the way out also rides, over the way back's metres.
LOOP_OVERLAP_OK = 0.30
# At or past this share the way back is the way out: the answer says it is an
# out-and-back and keeps the router's own route.
LOOP_OUT_AND_BACK = 0.90
# Points are put along the way out this far apart (metres), and none within the
# search's endpoint clearance of its ends or a via point (a loop must be able to
# leave and arrive).
LOOP_SAMPLE_M = 120.0
# The thinning of the exclusions at each attempt (every n-th point), and the time the
# whole step may take (seconds).
LOOP_THINNING = (1, 2, 4, 8)
LOOP_BUDGET_S = 14.0


def return_overlap(read: Analysis) -> tuple[float, float]:
    """(metres of the last leg on a way the legs before it ride, metres of the last
    leg): what a loop's way back shares with its way out."""
    bounds = leg_bounds(read)
    if len(bounds) < 2:
        return 0.0, 0.0
    cut = bounds[-1][0]
    along = 0.0
    out_ways: set[int] = set()
    back = []
    for piece in read.pieces:
        if along < cut - 1e-6:
            if piece.way_id:
                out_ways.add(piece.way_id)
        else:
            back.append(piece)
        along += piece.metres
    shared = sum(p.metres for p in back if p.way_id in out_ways)
    return shared, sum(p.metres for p in back)


def overlap_share(read: Analysis) -> float:
    shared, back = return_overlap(read)
    return shared / back if back > 0 else 0.0


def loop_refused(read: Analysis, ctx: Context) -> bool:
    """Whether a candidate shares more of the way back with the way out than the loop
    has (or than LOOP_OVERLAP_OK, if the loop has less)."""
    if ctx.loop_overlap is None:
        return False
    return overlap_share(read) > max(ctx.loop_overlap, LOOP_OVERLAP_OK) + 0.005


def make_loop(trip: dict, ctx: Context) -> tuple[dict, dict]:
    """The plan's way back by a different way (OWNER-DECISIONS 266): the last leg of
    `trip` asked for again with points along the way out excluded, from all of them
    to fewer (LOOP_THINNING) to none, every one asked; the whole within the longest
    ride; the least stressful of those that share no more than LOOP_OVERLAP_OK of the
    way out, else the one that shares the least. Where the way back is the way out whatever is
    excluded (LOOP_OUT_AND_BACK) the router's own route stays, `fallback` says so.

    Returns (trip, info) with `info`: `overlap_pct` and `shared_m` of the trip
    returned, `return_m`, `excluded` (how many points), `tried` (routes asked for) and
    `fallback` (None, or "out_and_back", or why nothing was tried)."""
    info: dict = {
        "overlap_pct": None,
        "shared_m": None,
        "return_m": None,
        "excluded": 0,
        "tried": 0,
        "fallback": None,
    }
    legs = trip.get("legs") or []
    locations = ctx.request.get("locations") or []
    if len(legs) < 2 or len(locations) != len(legs) + 1:
        info["fallback"] = "points"
        return trip, info
    k = len(legs) - 1
    try:
        first = analyse(trip, ctx, ctx.deadline)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["fallback"] = "time"
        return trip, info
    if first is None:
        info["fallback"] = "untraceable"
        return trip, info
    shared0, back0 = return_overlap(first)
    info.update(
        shared_m=round(shared0, 1), return_m=round(back0, 1), overlap_pct=_pct(shared0, back0)
    )
    out_trip = {"legs": legs[:k], "summary": trip.get("summary") or {}}
    try:
        out = analyse(out_trip, ctx, ctx.deadline, with_events=False)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["fallback"] = "time"
        return trip, info
    if out is None:
        info["fallback"] = "untraceable"
        return trip, info
    total = sum(p.metres for p in out.pieces)
    points: list[tuple[float, float]] = []
    for at, lon, lat, metres in _marks(out):
        if metres < CALM_MIN_EDGE_M or not _clear_of_ends(at, total, out.via_m):
            continue
        if points and haversine(Point(*points[-1]), Point(lon, lat)) < LOOP_SAMPLE_M:
            continue
        points.append((lon, lat))
    stop_at = min(routing.clock() + LOOP_BUDGET_S, ctx.deadline.at - REFINE_TRACE_RESERVE_S)
    best: tuple[tuple, dict, Analysis, int, float] | None = None
    seen: set[frozenset] = set()
    for step in LOOP_THINNING:
        chosen = points[::step][:MAX_EXCLUDES]
        key = frozenset(chosen)
        if not chosen or key in seen:
            continue
        seen.add(key)
        if stop_at - routing.clock() < REFINE_ROUND_MIN_S:
            break
        info["tried"] += 1
        read, back_trip = _through((), stop_at, ctx, chosen, k)
        if read == "time":
            break
        if read is None or read.events is None:
            continue
        joined = _splice(
            trip, k, {"legs": back_trip["legs"], "summary": back_trip.get("summary") or {}}
        )
        if too_long(_trip_m(joined), ctx):
            continue
        whole = analyse(joined, ctx, routing.Deadline(stop_at, ctx.deadline.per_call_s))
        if whole is None or whole.events is None:
            continue
        shared, back = return_overlap(whole)
        share = shared / back if back > 0 else 1.0
        ranked = (share > LOOP_OVERLAP_OK, whole.key(ctx) if share <= LOOP_OVERLAP_OK else share)
        if best is None or ranked < best[0]:
            best = (ranked, joined, whole, len(chosen), share)
    if best is None or best[4] >= LOOP_OUT_AND_BACK:
        info["fallback"] = "out_and_back"
        return trip, info
    _ranked, joined, whole, excluded, share = best
    if share >= overlap_share(first) and overlap_share(first) < LOOP_OUT_AND_BACK:
        # Nothing the router gave shares less than its own route's way back did.
        return trip, info
    shared, back = return_overlap(whole)
    info.update(
        shared_m=round(shared, 1),
        return_m=round(back, 1),
        overlap_pct=_pct(shared, back),
        excluded=excluded,
    )
    return joined, info


def _pct(shared: float, back: float) -> float | None:
    return round(100.0 * shared / back, 1) if back > 0 else None


# The routes offered (OWNER-DECISIONS 265: "return up to 3-4 candidate routes, not one,
# so the rider can pick the one they like"). There is no score for scenery: the rider
# judges that from the map. A candidate must be within the longest ride, pass the hold,
# and be no worse than the answer by more than these bands (a near-tie on stress, where
# the variety matters): the top figure by ALT_TOP_BAND_M (about 150 ft) and the second
# by ALT_SECOND_BAND_M (about 1,000 ft). It must also be meaningfully different from
# every candidate already chosen: it shares less than ALT_OVERLAP of the shorter one's
# road by matched way length, or differs from it by at least ALT_DIFFERENT_M of road
# (a different corridor over a stretch: 60% of a 58 mi route is never different).
ALT_MAX = 4
ALT_OVERLAP = 0.60
ALT_DIFFERENT_M = 8_000.0
ALT_TOP_BAND_M = 45.0
ALT_SECOND_BAND_M = 300.0


def _road_m(read: Analysis) -> float:
    return sum(piece.metres for piece in read.pieces)


def shared_m(a: Analysis, b: Analysis) -> float:
    """The metres of `a`'s road on a way `b` also rides (matched by way, per piece)."""
    ways = {piece.way_id for piece in b.pieces if piece.way_id}
    return sum(piece.metres for piece in a.pieces if piece.way_id in ways)


def distinct_from(read: Analysis, chosen: list[Analysis]) -> bool:
    """Whether a route is meaningfully different from each of the chosen ones."""
    for other in chosen:
        mine, theirs = _road_m(read), _road_m(other)
        if mine <= 0 or theirs <= 0:
            return False
        shared = shared_m(read, other)
        if shared / min(mine, theirs) >= ALT_OVERLAP and mine - shared < ALT_DIFFERENT_M:
            return False
    return True


def pick_candidates(pool: list, ctx: Context, reference: list[float]) -> list:
    """The answer and up to `ctx.alternates` - 1 others from `pool`, a list of
    (trip, reading) whose first is the answer: each within the longest ride and the
    hold (against `reference`, the first route's top figure by leg), a near-tie with
    the answer on stress, and meaningfully different from those already chosen, in the
    order of `Analysis.key`."""
    if not pool:
        return []
    answer = pool[0]
    chosen = [answer]
    limit = max(ctx.alternates, 1)
    for trip, read in sorted(pool[1:], key=lambda o: o[1].key(ctx)):
        if len(chosen) >= limit:
            break
        if (
            read.events is None
            or too_long(read.length_m, ctx)
            or more_lts4(read, reference, ctx)
            or read.top_m > answer[1].top_m + ALT_TOP_BAND_M
            or read.second_m > answer[1].second_m + ALT_SECOND_BAND_M
            or not distinct_from(read, [c[1] for c in chosen])
        ):
            continue
        chosen.append((trip, read))
    return chosen


# Where the search found no other route worth offering, the router is asked for one
# that avoids the roads of those already chosen (the loop's way back uses the same
# device): the points along the chosen routes are excluded, every ALT_SAMPLE_M, none
# within the search's endpoint clearance of an end or a stop, at most ALT_ASKS times
# and ALT_BUDGET_S seconds, and a route is kept only if `pick_candidates` would pick it
# (a near-tie on stress, within the longest ride, the hold, meaningfully different). A
# route that fails the near-tie ends the asking: avoiding more only makes it busier.
ALT_ASKS = 3
ALT_BUDGET_S = 9.0
ALT_SAMPLE_M = 150.0


def more_routes(chosen: list, ctx: Context, reference: list[float]) -> list:
    """`chosen` (a list of (trip, reading), the answer first) with the routes the router
    gives when the roads of those already chosen are excluded, as above."""
    if len(chosen) >= ctx.alternates:
        return chosen
    stop_at = min(routing.clock() + ALT_BUDGET_S, ctx.deadline.at - REFINE_TRACE_RESERVE_S)
    base = {k: v for k, v in ctx.request.items() if k not in ("alternates", "exclude_locations")}
    asked = 0
    while len(chosen) < ctx.alternates and asked < ALT_ASKS:
        if stop_at - routing.clock() < REFINE_ROUND_MIN_S:
            break
        points: list[tuple[float, float]] = []
        for _trip, read in chosen:
            total = _road_m(read)
            for at, lon, lat, metres in _marks(read):
                if metres < CALM_MIN_EDGE_M or not _clear_of_ends(at, total, read.via_m):
                    continue
                if points and haversine(Point(*points[-1]), Point(lon, lat)) < ALT_SAMPLE_M:
                    continue
                points.append((lon, lat))
        points = points[:: max(1, math.ceil(len(points) / MAX_EXCLUDES))]
        if not points:
            break
        asked += 1
        request = {**base, "exclude_locations": [{"lon": lon, "lat": lat} for lon, lat in points]}
        try:
            answer = routing._call(
                ctx.variant,
                "route",
                request,
                routing.Deadline(
                    stop_at, min(ctx.deadline.per_call_s, routing.ALTERNATES_TIMEOUT_S)
                ),
            )
            found = answer.get("trip") or {}
            if not found.get("legs") or too_long(_trip_m(found), ctx):
                break
            read = analyse(found, ctx, routing.Deadline(stop_at, ctx.deadline.per_call_s))
        except routing.RouterRefused:
            break
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            break
        if read is None or read.events is None:
            break
        picked = pick_candidates([*chosen, (found, read)], ctx, reference)
        if len(picked) == len(chosen):
            break
        chosen = picked
    return chosen


def combine(reads: list[Analysis]) -> Analysis:
    """The readings of a route's legs as the reading of the whole: the figures added,
    the pieces and junctions in order (a leg read without its junctions has none)."""
    via, along = [], 0.0
    for read in reads[:-1]:
        along += _road_m(read)
        via.append(along)
    return Analysis(
        length_m=sum(r.length_m for r in reads),
        cost_s=sum(r.cost_s for r in reads),
        exposure_m=sum(r.exposure_m for r in reads),
        climb_m=sum(r.climb_m for r in reads),
        pieces=[p for r in reads for p in r.pieces],
        classes=[c for r in reads for c in r.classes],
        events=[e for r in reads for e in (r.events or [])],
        via_m=via,
        lts4_m=sum(r.lts4_m for r in reads),
        lts3_m=sum(r.lts3_m for r in reads),
        effort_m=sum(r.effort_m for r in reads),
    )


# What a metre of each level of `Analysis.key` is worth when a long plan shares the
# longest ride out among its legs (`choose_options`): the levels in order of
# magnitude, so a metre of the top figure is worth a thousand of the second.
CHOICE_WEIGHTS = (1000.0, 1.0, 0.01)


def frontier(options: list, ctx: Context) -> list:
    """The options a leg offers, as a chain from the shortest to the longest in which
    each is `better` than the one before: the first route and every candidate better
    than it, with those no calmer than a shorter one left out. Each is (trip, reading)."""
    first = options[0]
    valid = [first] + [o for o in options[1:] if better(o[1], first[1], ctx)]
    valid.sort(key=lambda o: o[1].length_m)
    chain = [valid[0]]
    for option in valid[1:]:
        if better(option[1], chain[-1][1], ctx):
            chain.append(option)
    return chain


def _benefit(a: Analysis, b: Analysis, ctx: Context) -> float:
    """What `b` gains over `a` in the order of `Analysis.key`, weighted by CHOICE_WEIGHTS."""
    return sum(w * (x - y) for w, x, y in zip(CHOICE_WEIGHTS, a.key(ctx), b.key(ctx), strict=True))


def choose_options(
    chains: list, firsts_m: list[float], max_m: float | None, ctx: Context, fixed_m: float = 0.0
) -> list:
    """The index in each leg's chain to answer, so that the legs together are within
    `max_m` (None: no limit) and as calm as the longest ride allows. Each leg starts at
    its first route (or the shortest option that beats it, which costs nothing), and the
    metres of detour then go where they buy the most, by the benefit of each upgrade
    per metre it adds: the best leg's, then the next, until what is left buys nothing.
    `fixed_m` is the length of the legs that offer no choice, which count against the limit."""
    pos = []
    for chain, first_m in zip(chains, firsts_m, strict=True):
        shorter = [i for i, o in enumerate(chain) if o[1].length_m <= first_m + 0.5]
        pos.append(shorter[-1] if shorter else 0)
    total = fixed_m + sum(chain[p][1].length_m for chain, p in zip(chains, pos, strict=True))
    while True:
        best: tuple[float, int, int] | None = None
        for j, chain in enumerate(chains):
            now = chain[pos[j]][1]
            for k in range(pos[j] + 1, len(chain)):
                added = chain[k][1].length_m - now.length_m
                if max_m is not None and total + added > max_m:
                    continue
                gain = _benefit(now, chain[k][1], ctx)
                if gain <= 0:
                    continue
                ratio = gain / max(added, 1.0)
                if best is None or ratio > best[0]:
                    best = (ratio, j, k)
        if best is None:
            return pos
        _ratio, j, k = best
        total += chains[j][k][1].length_m - chains[j][pos[j]][1].length_m
        pos[j] = k


def _long_candidates(
    ctx, trip, joined, results, finals, reads, offered, first_tops, searched, chosen, chains
) -> list:
    """The routes a long plan offers (OWNER-DECISIONS 265): the answer, and the answer
    with one leg's route swapped for another the search read (a different corridor over
    that leg), picked by `pick_candidates` on the readings added up. The ones picked are
    read in full by the plan."""
    pool = [(joined, combine(finals))]
    chosen_at = dict(zip(searched, chosen, strict=True))
    for j in searched:
        keep = chains[searched.index(j)][chosen_at[j]]
        for option_trip, option_read in offered[j] or []:
            if option_trip is keep[0] or option_trip is results[j]:
                continue
            trips = list(results)
            reads_now = list(finals)
            trips[j], reads_now[j] = option_trip, option_read
            pool.append((_joined(trips, trip), combine(reads_now)))
    reference = [
        sum(
            first_tops[j] if first_tops[j] is not None else reads[j].lts4_m
            for j in range(len(reads))
        )
    ]
    return pick_candidates(pool, ctx, reference)


def refine_long(trip: dict, ctx: Context) -> tuple[dict, dict]:
    """The search on a trip past the working span, leg by leg.

    The router's own route (`trip`) is read for its stress and cut into legs
    (`long_legs`); each leg's own route is asked for and read; the legs with
    busy road to avoid are searched one at a time, the worst first (LTS 4 and
    Avoid, then LTS 3), each with its share of the time left, by its weight, and
    the legs the time does not reach keep the router's route. Each leg's search may
    use all the detour the longest ride leaves the whole (it keeps every
    candidate it reads), and the detour is then shared out where it buys the
    most (`choose_options`), so that the whole is never past the longest ride and
    no leg spends metres another could use better. The legs are put back
    together as one trip. If the whole is not as calm as the router's own route
    (LTS 4 and Avoid first, then LTS 3), or nothing changed, the router's own
    route is answered. `info["long"]` says what each leg did."""
    info: dict = {
        "rate": ctx.rate,
        "rounds": 0,
        "excluded": 0,
        "limited": None,
        "original_m": None,
        "extra_distance_m": 0.0,
        "exposure_before_m": None,
        "exposure_after_m": None,
    }
    started = routing.clock()
    if ctx.deadline.at - started < LONG_MIN_START_S:
        info["limited"] = "time"
        return trip, info
    try:
        whole = analyse(trip, ctx, ctx.deadline, with_events=False)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = "time"
        return trip, info
    if whole is None:
        info["limited"] = "untraceable"
        return trip, info
    info["original_m"] = round(whole.length_m, 1)
    info["exposure_before_m"] = round(whole.exposure_m, 1)
    info["lts4_m_before"] = round(whole.lts4_m, 1)
    info["lts3_m_before"] = round(whole.lts3_m, 1)
    if ctx.exposure.hold_lts4:
        info["lts4_before_m"] = round(whole.lts4_m, 1)
    legs = long_legs(whole, ctx)
    long = info["long"] = {
        "legs": len(legs),
        "searched": 0,
        "skipped": 0,
        "stops": [sum(1 for leg in legs if leg["user"] == k) for k in range(len(ctx.points) - 1)],
    }
    hard_stop = ctx.deadline.at - LONG_FINAL_RESERVE_S
    base_request = {
        k: v for k, v in ctx.request.items() if k not in ("alternates", "exclude_locations")
    }
    # Each leg's own route, asked for and read (the stress alone: the junctions
    # are read for the legs that are searched).
    firsts: list[dict] = []
    reads: list[Analysis] = []
    for leg in legs:
        request = {**base_request, "locations": [leg["a"], leg["b"]]}
        try:
            answer = routing._call(
                ctx.variant,
                "route",
                request,
                routing.Deadline(
                    hard_stop, min(ctx.deadline.per_call_s, routing.ALTERNATES_TIMEOUT_S)
                ),
            )
            leg_trip = answer.get("trip") or {}
            read = None
            if leg_trip.get("legs"):
                read = analyse(
                    leg_trip, ctx, routing.Deadline(hard_stop, ctx.deadline.per_call_s), False
                )
        except routing.RouterRefused:
            read = None
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            info["limited"] = "time"
            return trip, info
        if read is None:
            info["limited"] = "split"
            return trip, info
        firsts.append(leg_trip)
        reads.append(read)
    results = list(firsts)
    finals = list(reads)
    infos: list[dict | None] = [None] * len(legs)
    caps: list[float | None] = [None] * len(legs)
    offered: list[list | None] = [None] * len(legs)
    first_tops: list[float | None] = [None] * len(legs)
    # The detour the longest ride leaves the whole, which each leg may use on its own.
    slack = 0.0
    if ctx.max_m is not None:
        slack = max(ctx.max_m - sum(_trip_m(t) for t in firsts), 0.0)
    weights = [LONG_LTS4_PRIORITY * r.lts4_m + r.lts3_m for r in reads]
    order = sorted(
        (j for j in range(len(legs)) if weights[j] > 0),
        key=lambda j: (-reads[j].lts4_m, -reads[j].lts3_m, j),
    )
    limited: str | None = None
    for turn, j in enumerate(order):
        now = routing.clock()
        rest = sum(weights[i] for i in order[turn:])
        share = (hard_stop - now) * weights[j] / rest
        if share < LONG_LEG_MIN_S:
            long["skipped"] += 1
            limited = "time"
            continue
        cap = None
        if ctx.max_m is not None:
            cap = _trip_m(firsts[j]) + slack
        sub = dataclasses.replace(
            ctx,
            request={**base_request, "locations": [legs[j]["a"], legs[j]["b"]]},
            points=[_point_of(legs[j]["a"]), _point_of(legs[j]["b"])],
            first_lts4=[],
            kept_excludes=[],
            max_m=cap,
            options=[],
            alternates=0,
            stop_at=now + share,
            search_budget_s=share * LONG_SEARCH_SHARE,
            seek_budget_s=share * (1 - LONG_SEARCH_SHARE),
        )
        caps[j] = cap
        _got, leg_info = refine(firsts[j], sub)
        infos[j] = leg_info
        offered[j] = sub.options
        first_tops[j] = sum(sub.first_lts4) if sub.first_lts4 else None
        long["searched"] += 1
    # The longest ride shared out among the legs that were searched.
    searched = [j for j in range(len(legs)) if offered[j]]
    chains = [frontier(offered[j], ctx) for j in searched]
    fixed_m = sum(_trip_m(firsts[j]) for j in range(len(legs)) if j not in searched)
    chosen = (
        choose_options(chains, [_trip_m(firsts[j]) for j in searched], ctx.max_m, ctx, fixed_m)
        if searched
        else []
    )
    # (the other legs' lengths count against it)
    for j, chain, at in zip(searched, chains, chosen, strict=True):
        if chain[at][0] is not firsts[j]:
            results[j], finals[j] = chain[at]
    for leg_info in infos:
        if leg_info is None:
            continue
        info["rounds"] += leg_info["rounds"]
        info["excluded"] = max(info["excluded"], leg_info["excluded"])
        limited = "time" if leg_info["limited"] == "time" else (limited or leg_info["limited"])
    info["limited"] = limited
    long["per_leg"] = [
        {
            "leg": j,
            "m": round(_trip_m(results[j])),
            "first_m": round(_trip_m(firsts[j])),
            "lts4_m": [round(reads[j].lts4_m), round(finals[j].lts4_m)],
            "lts3_m": [round(reads[j].lts3_m), round(finals[j].lts3_m)],
            "searched": infos[j] is not None,
            "cap_m": None if caps[j] is None else round(caps[j]),
            "options": len(offered[j]) if offered[j] else 0,
            "limited": infos[j]["limited"] if infos[j] else None,
            "rounds": infos[j]["rounds"] if infos[j] else 0,
        }
        for j in range(len(legs))
    ]
    info["seek"] = _merge_seek([(j, i["seek"]) for j, i in enumerate(infos) if i and i.get("seek")])
    changed = any(results[j] is not firsts[j] for j in range(len(legs)))
    lts4 = sum(a.lts4_m for a in finals)
    lts3 = sum(a.lts3_m for a in finals)
    length = sum(_trip_m(t) for t in results)
    # The router's own route is answered if nothing changed, or if what is put
    # together is not as calm as it (or is past the longest ride).
    # LTS 4 a leg took on to avoid a red junction (the hold allows it,
    # OWNER-DECISIONS 259) is not counted against the whole.
    traded = sum(max(0.0, f.lts4_m - r.lts4_m) for f, r in zip(finals, reads, strict=True))
    lts4 -= traded
    worse = lts4 > whole.lts4_m + MAXCALM_STEPS[0] or (
        lts4 > whole.lts4_m - MAXCALM_STEPS[0] and lts3 > whole.lts3_m + MAXCALM_STEPS[1]
    )
    lts4 += traded
    if not changed or worse or too_long(length, ctx):
        long["answered"] = "router"
        info["lts4_m_after"] = info["lts4_m_before"]
        info["lts3_m_after"] = info["lts3_m_before"]
        info["exposure_after_m"] = info["exposure_before_m"]
        if ctx.exposure.hold_lts4:
            info["lts4_after_m"] = info["lts4_before_m"]
        if info["seek"]:
            info["seek"] = {**info["seek"], "taken": False}
        return trip, info
    long["answered"] = "legs"
    joined = _joined(results, trip)
    if ctx.alternates > 1:
        ctx.candidates = _long_candidates(
            ctx, trip, joined, results, finals, reads, offered, first_tops, searched, chosen, chains
        )
    info["extra_distance_m"] = round(length - whole.length_m, 1)
    info["exposure_after_m"] = round(sum(a.exposure_m for a in finals), 1)
    info["lts4_m_after"] = round(lts4, 1)
    info["lts3_m_after"] = round(lts3, 1)
    if ctx.exposure.hold_lts4:
        info["lts4_after_m"] = round(lts4, 1)
    # One reading of the whole route, which the answer reuses: the legs' traces
    # are remembered, the junctions read once across the joints.
    try:
        analyse(joined, ctx, ctx.deadline)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        pass
    return joined, info
