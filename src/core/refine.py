"""A search over the router's own routes: the calm detour and crossing avoidance.

Why a search and not a cost. Valhalla's bicycle costing (3.5.1 to 3.9.1) prices a road by
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
what the last one found. Before the rounds the router's own alternatives are
read and ranked with its first route the same way (OWNER-DECISIONS 435,
`_router_alternates`), and the rounds start from whichever ranks first.
The score is the router's own cost for the route
(its time with the stress, hill, turn and gate prices of the request) plus an
extra price, in the router's cost seconds, for what the router cannot see:

    router cost + QUIET COST x ( CALM RATE x (LTS 3 metres + 2 x LTS 4 + 3 x Avoid)
                               + INTERSECTION WEIGHT x (the junction events' cost in metres)
                               + HILL - ROUTER'S CLIMB CHARGE )
                 + 2.2 x 600 s x INTERSECTION WEIGHT x (red junctions)  (`RED_DETOUR_S`)

(The 1, 2 and 3 are the preset's `presets.Exposure`: Trailmaxxing and Cargo with
passengers weigh LTS 4 at 8 and Avoid at 16, and never take a route with more
LTS 4 and Avoid metres than the router's first, leg by leg or whole; OWNER-DECISIONS
250, `more_lts4`.)

On a ride that weighs LTS 2 (OWNER-DECISIONS 240), LTS 2 metres join the exposure
at that weight. Where the calm rate is 0 (80 on the slider and below, where Cargo
with passengers starts), the score adds instead LTS 2 metres x the ride's weight x
what a metre of LTS 3 adds in the router's own cost (`lts3_added_m`, about 4 quiet
metres at 80), so the weight still picks among the routes the router returns.

QUIET COST is what a metre of quiet-street riding costs the router at the
request's speed (`quiet_cost_per_m`: 2.2 times its time, measured on the live
router). The calm rate is `presets.calm_rate_for(stress)` (0 up to the old top
of the slider, then exponential): metres of quiet riding accepted per metre of
LTS 3 avoided, on top of the router's own price for it. The intersection weight
rises from 0.25 at the traffic tolerant end to 1 at Default (turn and
intersection costs stay active at every setting, as the literature review's
guardrail asks). HILL is what the route's climbing costs the rider in quiet metres
(`Analysis.hill_m`, `routemaker.hill_cost`; the owner, 2026-10-23, "always assume time
equivalent"): the extra time each climb takes, plus a steepness penalty on grades past the
rider's LT1 grade, which the hills slider sets (`Context.hills`: 1% at full avoid, 8% at the
detent, 15% at the far end). It takes the place of
the router's own climbing charge (`Analysis.router_climb_m`, at the request's `use_hills`),
as `routing.choose_by_hills` does.

Every metre in the stress figures (the exposure above, the LTS 4, LTS 3, LTS 2 and Avoid
metres the top of the slider and the worth rule read) is hill-weighted
(FOLLOWUP-GRADE-STRESS, OWNER-DECISIONS 409, `routemaker.grade_stress`; the owner,
2026-10-11: "Why not combine it all into a single stress metric? ... Multiply the two
together"): one figure, run x traffic weight x hill factor, the hill factor 1 + the hills
slider's coefficient (`Context.hill_coefficient`) x the window's extra effort on a climb of
3% or more, or on a descent past the ride type's brake grade, and 1 elsewhere. So uphill on
a busy road counts worse than downhill, the stress slider's rate still scales the traffic
part and the hills slider the hill part, and "fine with hills" multiplies everything by 1.
The hill's share of the exposure counts in the score at the calm rate where that is over
1 and one for one below it, so the hill counts at every slider position, Default's too;
a flat route scores as before. The LTS 4 hold compares the rated LTS 4 metres
(`lts4_by_leg`), so leaving out a hill never buys more LTS 4.
What the rider is shown (the LTS colours, the stress chart, the summary's LTS miles) is
the rated metres, unweighted.

Below the top of the slider there is no cap on the detour. The search stops
when a round finds nothing left to exclude, when two rounds in a row do not
improve the score, when the router has no route left (every way out is
excluded), or when the time runs out; `info["limited"]` says which, so the
answer can say a calm route was looked for and not found.

At the top of the slider (`presets.maxcalm_for`, OWNER-DECISIONS 256 and 257,
FOLLOWUP-LONG-CALM) the rate is gone. The search keeps every candidate within the
ceiling (`Context.ceiling_m`: 1.25 times the rider's target distance, OWNER-DECISIONS
271, or 1.6 times the router's own route where they set none, 268) and prefers the
one with the least stress, in this order: the "top" figure (metres of LTS 4 and Avoid
plus the cost of each very high stress junction, OWNER-DECISIONS 258 and 259), then
the "second" (metres of LTS 3 plus the cost of each higher stress junction, 260), then
the hills preference (262), then distance (`MAXCALM_STEPS`, `better`). Extra distance
has diminishing returns (268, `worth_it`): a longer candidate is taken only where the
stress it saves, in hill-weighted metres (so avoiding a busy climb counts), pays for the miles it
adds (`WORTH_DEFAULT`; past the rider's target
the stricter `WORTH_OVER_TARGET`, and up to the target `WORTH_UP_TO_TARGET`, half the
default's price, OWNER-DECISIONS 435; below the top the same rule holds at `worth_ratio`,
which rises with the slider). A candidate past the
ceiling is never taken, and the router's own price for the route, and any credit for
trail, do not come into it. A trip past the working span (`REFINE_MAX_SPAN_M`) is
planned leg by leg (`refine_long`).
"""

from __future__ import annotations

import bisect
import copy
import dataclasses
import logging
import math
from concurrent.futures import Future
from dataclasses import dataclass, field

from routemaker import avoid_junctions as avoid_model
from routemaker import (
    calm,
    climbs,
    effort,
    grade_stress,
    hill_cost,
    junction_delay,
    steep_grades,
    trace_junctions,
)
from routemaker import intersections as model
from routemaker.geo import Point, haversine

from . import junctions, legsplit, parallel, presets, route_hazards, routing, trailseek

logger = logging.getLogger(__name__)

# The most rounds of exclusion and re-routing, crossing avoidance alone's too (it runs
# for most plans, where the calm search runs only past the old top of the slider). More
# than one, each excluding the red crossings the last round's
# route took on top of those already excluded: a way round one unsignalised crossing of
# a busy road is often the next unsignalised crossing of the same road, and only a
# second or third round reaches a signal (PR #409's check, 2026-10-23, rush hour:
# Connecticut Avenue in Chevy Chase and Georgia Avenue in Wheaton each swapped one red
# crossing for the next one along and stopped there). Every round takes the red crossings
# of the route before it, at every calm rate, and crossing avoidance alone has as many
# rounds as the calm search (the PC's check of a NoMa to Twinbrook commute at Default,
# 2026-10-23: the third round still swapped a red for the next one, which a fourth
# excluded; above Default, crossings only in the first round kept a 16th St stop sign).
REFINE_MAX_ROUNDS = 5
CROSSING_ONLY_ROUNDS = REFINE_MAX_ROUNDS
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
# A route asked for through a corridor's entry and exit (or a wide point) can ride out
# along a way to one of them and back again the same way, where the router cannot pass
# the point in the order asked (Stephen, 2026-10-11: 0.5 mi down the trail by Island
# Creek and straight back). Such a candidate doubles back (`retrace_m`: the metres of a
# leg on an edge the same leg has already ridden, either way); one that does so by more
# than RETRACE_SLACK_M over the route it would replace is refused, and never offered.
RETRACE_SLACK_M = 50.0
# Two edges' middles within this many metres, of lengths within RETRACE_MATCH_M (or a
# tenth, the longer), are the one edge ridden twice.
RETRACE_MATCH_M = 2.0
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
# Valhalla's own `use_roads` where a request sets none.
VALHALLA_DEFAULT_USE_ROADS = 0.5
# PROPOSALS for the owner. The intersection weight at the traffic tolerant end.
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


def flat_speed_ms(costing: dict) -> float:
    """The request's flat riding speed, metres a second: its `cycling_speed`, else Valhalla's
    default for its bicycle type (`quiet_cost_per_m` reads the same)."""
    return QUIET_COST_FACTOR / quiet_cost_per_m(costing)


def use_hills_of(ctx: Context) -> float:
    """The request's `use_hills` (1.0, the detent's, where it sets none)."""
    return float((ctx.costing.get("bicycle") or {}).get("use_hills", 1.0))


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
    quiet_cost: float
    # The hills slider's seek half on Mountain Goat: how much of the effort a rider prefers
    # more of, the slider over 100 at the top of the stress slider (298(3)), else 0.
    hills_seek_weight: float = 0.0
    # The hills slider's position, which sets the rider's LT1 grade (`hill_cost.lt1_grade_for`:
    # 1% at full avoid, 8% at the detent, 15% at the far end): a climb costs its time at every
    # position and a steepness penalty past that grade (`Analysis.hill_m`; the owner,
    # 2026-10-23: "always assume time equivalent").
    hills: int = 0
    # The hill factor's coefficient (FOLLOWUP-GRADE-STRESS, OWNER-DECISIONS 409;
    # `grade_stress.coefficient_for` the hills slider: FACTOR at the detent, 0 at "fine with
    # hills"), and the ride type's brake grade, past which a descent counts in it
    # (`presets.BRAKE_GRADES`, OWNER-DECISIONS 56; None: none does). 0: every factor is 1.
    hill_coefficient: float = 0.0
    brake_grade: float | None = None
    # Whether bike lanes count as "none" in the breakdown (`routing.classify`): on
    # Mass Ride, which takes the roadway, not on every ride on the no-trail graph.
    lanes_as_roadway: bool = False
    # The rider's total system weight in kilograms (item 264), which the effort
    # reads (`routemaker.effort`).
    mass_kg: float = effort.MASS_KG
    analyses: dict = field(default_factory=dict)
    # The router's `/locate` answers already had in this plan, by (graph, lon, lat,
    # radius) (`locator`): the candidates are mostly detours of one route and share
    # most of its junctions, so each is asked once (review speed-1).
    located: dict = field(default_factory=dict)
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
    # `better`, not by the score, and none longer than `ceiling_m` metres is taken
    # (None: no limit, as below the top). `target_m` is the rider's target distance
    # (OWNER-DECISIONS 271; None: none set), up to which distance costs WORTH_UP_TO_TARGET
    # (435, "One rule") and past which it must buy stress at WORTH_OVER_TARGET; with
    # none, every extra metre must buy it at the slider's `worth_ratio` (268, 435:
    # WORTH_DEFAULT at the top). `worth_rule` off: no such price (a long
    # plan's legs, whose options are priced for the whole trip, `choose_options`).
    maxcalm: bool = False
    ceiling_m: float | None = None
    target_m: float | None = None
    worth_rule: bool = True
    # Where this search must end, whatever its budgets say (set for a leg of a
    # long plan: its share of the time), and how long the exclusion rounds and
    # the seek may take after the route is read.
    stop_at: float | None = None
    # The routes to offer the rider (OWNER-DECISIONS 265): (trip, reading), the
    # answer's own first, then up to ALT_MAX - 1 others (`pick_candidates`); set by
    # `refine` and `refine_long` where `options` is collected.
    candidates: list = field(default_factory=list)
    # The hold's reference they were picked against (`pick_candidates`), for picking
    # them again where the answer changes after the search (`dedodge.settle`).
    candidate_reference: list = field(default_factory=list)
    # A loop (OWNER-DECISIONS 266): the plan's last leg returns to its start, and
    # `loop_overlap` is the most of the way back that may be the way out (set by
    # `make_loop`; None: not a loop). No search candidate may share more of it.
    loop_overlap: float | None = None
    # How many routes the rider is offered at most, this one included (0: one).
    alternates: int = 0
    # Whether the search also asks the router for its own alternative routes and
    # ranks them with the rest (OWNER-DECISIONS 435, `_router_alternates`): set by the
    # plan wherever the calm search runs (above the old top of the slider).
    rank_alternates: bool = False
    # The router's routes for this very request where the plan already asked for its
    # alternatives (the hills slider's avoid half), its first route first, which the
    # search ranks instead of asking again; an empty list where that ask timed out (so
    # none is asked again); None: none asked yet.
    router_trips: list | None = None
    # The search's own ask for them, where the plan started it on the pool beside the
    # reading of its first route (`ask_alternates_early`); used only while the request
    # is still the one it asked.
    early_alternates: EarlyAlternates | None = None
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
    # The approved Avoid-rated junctions (`core.avoid_junctions.approved`, 307-310):
    # each pass costs a candidate AVOID_JUNCTION_PENALTY_S (308), and the first rounds
    # exclude them (`crossing_targets`).
    avoid: tuple = ()
    # The router's first route's `Analysis.avoid_junction_m` (set by `refine`), which the
    # Traffic-wins guard counts with its exposure (`_busier`).
    first_avoid_m: float = 0.0
    # The router's first route's `Analysis.red_m` (set by `refine`), which the guard
    # counts the same way: a way round a red crossing is not "busier" for the LTS 3 it
    # rides in place of it.
    first_red_m: float = 0.0
    # The approved rider ratings of junctions (`core.junction_suggestions.approved_ratings`,
    # OWNER-DECISIONS 232), which set a rated junction's cost and marker.
    junction_ratings: tuple = ()
    # The known flashing beacons at junctions the map has a signal at
    # (`core.flashing_signals.active`), priced with no signal.
    beacons: tuple = ()
    # A Mass Ride or a Novice and Nervous ride: steep grades either way are priced
    # (`routemaker.steep_grades`, the owner, 2026-10-26), in `Analysis.hill_m`.
    steep_grades: bool = False


def shift_classes(classes: list, shift: int) -> list:
    """Each piece's class read `shift` levels up (`presets.Exposure.shift`, Novice and
    Nervous), for the search; the same list where there is no shift."""
    if shift <= 0:
        return classes
    out = []
    for cls in classes:
        tier, half = presets.shifted_tier(cls[0], getattr(cls, "half", False), shift)
        out.append(
            routing.PieceClass(
                tier,
                cls[1],
                getattr(cls, "unpaved", None),
                getattr(cls, "lanes", None),
                getattr(cls, "oneway", None),
                getattr(cls, "width_m", None),
                half,
            )
        )
    return out


def hazard_priced(classes: list, kinds: list) -> list:
    """Each piece on a known road hazard (`core.route_hazards`) read at LTS 4 at least, as
    the graph prices it (lua/routemaker_remap.lua `hazard_priced`; the owner, 2026-10-19:
    "Roads with hazards like this should get a major penalty"). A path is never priced, as
    the graph never prices a trail. The same list where no piece changes."""
    if not any(kinds):
        return classes
    out = []
    changed = False
    for cls, found in zip(classes, kinds, strict=False):
        if found and cls[1] != "path" and cls[0] in ("1", "2", "3"):
            changed = True
            cls = routing.PieceClass(
                "4",
                cls[1],
                getattr(cls, "unpaved", None),
                getattr(cls, "lanes", None),
                getattr(cls, "oneway", None),
                getattr(cls, "width_m", None),
                False,
            )
        out.append(cls)
    out.extend(classes[len(out) :])
    return out if changed else classes


@dataclass
class Analysis:
    """One candidate route, read."""

    length_m: float
    cost_s: float
    exposure_m: float
    climb_m: float
    pieces: list
    # The classes the search reads: on a ride that reads every road a level up
    # (`presets.Exposure.shift`, Novice and Nervous) the shifted ones, and the real ones in
    # `real_classes`, which the answer's summary and breakdown read (None: the same).
    classes: list
    events: list | None
    # Metres along the route at which each via point is reached.
    via_m: list = field(default_factory=list)
    # The middle of each traced edge: (metres along, lon, lat, edge metres).
    marks: list = field(default_factory=list)
    # The leg (stretch between the plan's own locations) each of `marks` is on, where
    # the reading kept it: a mark's metres along count every traced edge, `via_m` only
    # those `routing.pieces_of_trace` keeps, so the two can drift apart (`retrace_m`).
    mark_legs: list = field(default_factory=list)
    # Metres of LTS 4 and Avoid, and of LTS 3, as the classes say them, each times its
    # piece's hill factor (`hill`, OWNER-DECISIONS 409): so are `exposure_m` and the other
    # tier figures below. The rider is shown the rated metres (`routing.totals`), not these.
    lts4_m: float = 0.0
    lts3_m: float = 0.0
    # Of `lts4_m`, the metres of Avoid (the diminishing-returns weights tell them apart).
    avoid_m: float = 0.0
    # Of `lts4_m`, the metres of 4.5 (a half step above LTS 4, never Avoid: 441k), which the
    # worth rule counts at the midpoint of LTS 4's and Avoid's weights (461a).
    lts45_m: float = 0.0
    # Metres of LTS 2, and what one counts in metres of LTS 3 on this plan's ride
    # (`presets.Exposure.lts2`, FOLLOWUP-LTS2-WEIGHT: a quarter on Trailmaxxing and
    # Cargo with passengers, a half on Riding with kids, nothing elsewhere).
    lts2_m: float = 0.0
    lts2_weight: float = 0.0
    # The route's effort-equivalent distance, metres (`routemaker.effort`,
    # OWNER-DECISIONS 262, 263): its length weighted by the grade it rides, which
    # the Hills slider blends with the actual distance.
    effort_m: float = 0.0
    # Its passes through Avoid-rated junctions (`routemaker.avoid_junctions`, 307), and
    # their penalty as metres of quiet riding at the ride's speed (308: 30 minutes each,
    # as `routemaker.calm.avoid_entry_m` counts an Avoid road's entry charge).
    avoid_passages: list = field(default_factory=list)
    avoid_junction_m: float = 0.0
    # What the router's cost charged for its climbing, in metres of quiet riding, at the
    # request's `use_hills` (`climbs.router_climb_m`), which `score` takes off, and what the
    # climbing costs the rider in its place, in the same metres: its extra time and the
    # slider's share of its steepness penalty (`hill_cost.hill_cost_m`, the owner,
    # 2026-10-23: "always assume time equivalent").
    router_climb_m: float = 0.0
    hill_m: float = 0.0
    # Each piece's hill factor (`grade_stress.hill_factors`, FOLLOWUP-GRADE-STRESS,
    # OWNER-DECISIONS 409), in the order of `pieces`; empty: all 1.
    hill: list = field(default_factory=list)
    # `exposure_m` and `lts2_m` at a hill factor of 1 everywhere, the rated metres (set by
    # `analyse`; None: the same as the weighted figures, a reading made without hills).
    flat_exposure_m: float | None = None
    rated_lts2_m: float | None = None
    # See `classes`: the real classes where the search reads shifted ones, and the shift
    # (the junctions' colours are read as many levels up, `presets.shifted_severity`).
    real_classes: list | None = None
    shift: int = 0
    # The seconds its junctions cost the rider, which the router's own time leaves out
    # (`routemaker.junction_delay`, the owner, 2026-10-20: "Both", the time shown and the
    # route chosen): priced in `score` as that much quiet riding.
    junction_delay_s: float = 0.0
    # Each piece's known hazard kinds, in the order of `pieces` (`route_hazards.kinds_of`), as
    # the reading priced them; the answer says them from here (audit S16). None: not read.
    hazard_kinds: list | None = None
    # Its scenic designations and stress adjustments as the stress query read them, only for
    # the pieces that have one ({index in `pieces`: ...}, `routing.Classes`), for the answer
    # (audit S17). None: not read.
    scenic: dict | None = None
    adjustments: dict | None = None

    @property
    def rated_classes(self) -> list:
        """The classes as rated, never shifted: what the rider is shown."""
        return self.classes if self.real_classes is None else self.real_classes

    @property
    def rated_exposure_m(self) -> float:
        """`exposure_m` in rated metres, at a hill factor of 1: what the Traffic-wins guard
        compares (OWNER-DECISIONS 61, "Traffic wins" over hill avoidance; 409), so a route
        that leaves out a busy climb by riding more busy road is still busier."""
        return self.exposure_m if self.flat_exposure_m is None else self.flat_exposure_m

    @property
    def hill_exposure_m(self) -> float:
        """What the hill factor adds to `exposure_m` (409): the traffic weight x (hill
        factor - 1) x metres, at the ride's own exposure weights."""
        return 0.0 if self.flat_exposure_m is None else self.exposure_m - self.flat_exposure_m

    def score(self, ctx: Context) -> float:
        """The router's cost plus the extra price (see the module docstring), 30
        minutes for each pass through an Avoid-rated junction (308), `RED_DETOUR_S` of quiet
        riding for each red junction at the intersection weight, with the router's own
        climbing charge swapped for the rider's (`hill_m`, 2026-10-23). The hill's
        share of the exposure (`hill_exposure_m`, 409) counts at the calm rate where it is
        over 1 and one for one below it, so it counts at every slider position, Default's
        too (the owner's Connecticut Avenue climb); a flat route scores as it did."""
        penalty = model.penalty_m(self.events) if self.events else 0.0
        hill = self.hill_exposure_m
        extra = (
            ctx.rate * (self.exposure_m - hill)
            + max(ctx.rate, 1.0) * hill
            + ctx.weight * penalty
            + self.hill_m
            - self.router_climb_m
        )
        if ctx.rate == 0 and self.lts2_weight > 0:
            lts2 = self.lts2_m if self.rated_lts2_m is None else self.rated_lts2_m
            extra += self.lts2_weight * lts3_added_m(ctx) * lts2
        return (
            self.cost_s
            + ctx.quiet_cost * extra
            + avoid_model.penalty_s(self.avoid_passages)
            + QUIET_COST_FACTOR * self.junction_delay_s
            + QUIET_COST_FACTOR * RED_DETOUR_S * ctx.weight * red_count(self)
        )

    @property
    def red_m(self) -> float:
        """The very high stress (red) junctions' summed cost, as metres of quiet
        riding (the junction model's own cost, 2,000 to 4,500 ft each); with a shift,
        the orange ones too (`presets.shifted_severity`)."""
        return junction_cost_m(self.events, "red", self.shift)

    @property
    def orange_m(self) -> float:
        """The higher stress (orange) junctions' summed cost, in the same unit."""
        return junction_cost_m(self.events, "orange", self.shift)

    @property
    def top_m(self) -> float:
        """The top figure of the ranking and of the LTS 4 hold: metres of LTS 4 and
        Avoid, plus the cost of the red junctions (OWNER-DECISIONS 259: "weight Very
        Stressful and LTS4 equally", in the junction's own cost), and the penalty of each
        Avoid-rated junction it passes (307: "kept in the stress order's top level ...
        above red")."""
        return self.lts4_m + self.red_m + self.avoid_junction_m

    @property
    def second_m(self) -> float:
        """The second figure of the ranking (OWNER-DECISIONS 260: "Make LTS3 and
        orange crossing the same"): metres of LTS 3 plus the cost of the orange
        junctions, plus, on a ride that weighs LTS 2 (OWNER-DECISIONS 240 (A),
        FOLLOWUP-LTS2-WEIGHT), its metres of LTS 2 at that weight."""
        return self.lts3_m + self.orange_m + self.lts2_weight * self.lts2_m

    def key(self, ctx: Context) -> tuple[float, float, float]:
        """What the top of the slider ranks by, least first (OWNER-DECISIONS
        258-263): the top figure, the second figure, and the distance as the Hills
        slider blends it (`level3`). The metres in the two figures are hill-weighted."""
        return (self.top_m, self.second_m, level3(self, ctx))


def lts3_added_m(ctx: Context) -> float:
    """What a metre of LTS 3 adds in the router's own cost at this request's `use_roads`,
    in metres of quiet street: the graded-stress model's added cost (`calm.added_cost`,
    the middle of the five road types) over a quiet metre's (`QUIET_COST_FACTOR`), about
    4 at 80 on the slider. The score's LTS 2 term at a calm rate of 0 (FOLLOWUP-LTS2-WEIGHT
    review: Cargo with passengers starts at 80, where the rate is 0, so the weight never
    priced a route there) charges a metre of LTS 2 the ride's share of it, a quarter
    (OWNER-DECISIONS 240 (A)): about 1 quiet metre at 80. The router's requests are
    unchanged; only the choice among the routes it returns."""
    options = ctx.costing.get("bicycle") or {}
    lts3, _lts4 = calm.added_cost(options.get("use_roads", VALHALLA_DEFAULT_USE_ROADS))
    return lts3 / QUIET_COST_FACTOR


def level3(read: Analysis, ctx: Context) -> float:
    """The third level, least first: the distance with its climbing counted as the flat
    riding it is worth (`charged_m`; OWNER-DECISIONS 262's effort-equivalent distance, made
    the climb's time plus the slider's steepness penalty on 2026-10-23). On Mountain Goat
    more effort is better: `Context.hills_seek_weight` (the slider's position over 100 at
    the top of the stress slider, `routing.plan`) takes that share of the effort off, so
    between equally calm routes the one that climbs more ranks first; the stress levels
    above it and the target are unchanged (OWNER-DECISIONS 298(3), "Keep stress order +
    target (Recommended)"). The target distance is in actual metres, not these."""
    effort = read.effort_m or read.length_m
    return charged_m(read, ctx) - ctx.hills_seek_weight * effort + delay_m(read, ctx)


def delay_m(read: Analysis, ctx: Context) -> float:
    """The route's junction delay (`Analysis.junction_delay_s`) as metres of quiet riding,
    the rate `score` prices it at, so the top of the slider weighs it too: between equally
    calm routes, the one with fewer stops ranks first."""
    if ctx.quiet_cost <= 0:
        return 0.0
    return QUIET_COST_FACTOR * read.junction_delay_s / ctx.quiet_cost


def charged_m(read: Analysis, ctx: Context) -> float:
    """The distance the 268 charge weighs (`distance_charge_m`'s `blended_m`): the actual
    distance plus what its climbing is worth in flat metres (`Analysis.hill_m`: the time it
    takes and the slider's share of its steepness penalty; the owner, 2026-10-23, "Below LT1
    you can basically downshift and chill, so it's essentially the same as a slightly longer
    flat piece"), as in `level3`, but without the seek half's credit for effort. Seeking
    climbs changes only the tiebreak, never how many miles a stress saving buys
    (OWNER-DECISIONS 298(3), "Seeking hills changes only the effort tiebreak"; the
    release re-check's S1: with the credit in, a longer, hillier route was charged
    nothing and any stress saving was worth it)."""
    return read.length_m + read.hill_m


def junction_cost_m(events: list | None, severity: str, shift: int = 0) -> float:
    """The summed cost of the events of one severity (read `shift` levels up), in metres."""
    if not events:
        return 0.0
    return (
        sum(e.cost_ft for e in events if presets.shifted_severity(e.severity, shift) == severity)
        / model.FEET_PER_METRE
    )


# How much better, at each level of `Analysis.key`, a candidate must be to count
# as better at that level, so that a trivial gain at a higher level does not force
# a large loss at a lower one; within the step at one level the next decides.
# The top figure: 15 m, about 50 ft (a trace's rounding and a driveway; a design
# choice under the strict order of OWNER-DECISIONS 258, not the owner's words). The
# second: 50 m, about a block, the dodge pass's tie step on every ride type (298(1)).
# The third: 50 m of distance, actual or effort-equivalent.
MAXCALM_STEPS = (15.0, 50.0, 50.0)


# Diminishing returns on extra distance (OWNER-DECISIONS 268, "Diminishing returns
# (Recommended)": "extra distance is taken only when it buys a meaningful stress cut.
# Roughly: at least 1 mi of LTS 3 saved per 5 mi added, LTS 4/Avoid and red junctions
# weighted higher"). A longer candidate replaces a shorter one only where the stress
# it saves (`stress_weight_m`: LTS 3-equivalent metres, LTS 4 and Avoid at the level
# weights of WORTH_WEIGHTS, a red junction's cost at the LTS 4 weight and an orange one's
# at the LTS 3 weight, 259 and 260) is at least the metres it adds divided by this:
# - WORTH_DEFAULT where the rider set no target: 5 metres added per metre saved;
# - WORTH_OVER_TARGET for the metres past the rider's target distance (271: "may
#   exceed it when that buys a meaningful stress cut"), a stricter bar: 2.5;
# - up to the rider's target, WORTH_UP_TO_TARGET, half the default's price (435, "One
#   rule"; free under 271 until then).
# Tunable; docs/DEVELOPMENT.md, "Long calm trips", has the measurements.
WORTH_DEFAULT = 5.0
WORTH_OVER_TARGET = 2.5
# One rule across the calm search (OWNER-DECISIONS 435, the owner's "One rule",
# 2026-10-10): every longer route must buy its miles with calm, below the top of the
# slider too, at a ratio that rises with the slider's calm rate from 1 just above the
# old top to WORTH_DEFAULT at the top (`worth_ratio`: about 1.2 at 85, 1.7 at 90, 2.8
# at 95); and under a target the miles up to it cost WORTH_UP_TO_TARGET metres per
# metre of LTS 3 saved, half the default's price, where 271 made them free.
WORTH_UP_TO_TARGET = 10.0
# The level weights the stress saved is counted at: the standard 1, 2 and 3 for LTS 3,
# LTS 4 and Avoid (`presets.EXPOSURE_STANDARD`), on every ride. Not the stress-averse
# rides' 1, 8 and 16 (item 250), which the ranking does not need (it puts LTS 4 first
# whatever the weight) and which here would let one red junction (8 x 3,000 ft, about
# 4.5 mi of LTS 3) buy 23 mi of extra riding: measured, Union Station to Penn kept its
# 73 mi default and went 12 mi past a 60 mi target with them (docs/DEVELOPMENT.md).
WORTH_WEIGHTS = presets.EXPOSURE_STANDARD


def stress_weight_m(read: Analysis, ctx: Context) -> float:
    """A route's stress as one figure for the diminishing-returns rule (268), in
    metres of LTS 3: its LTS 3, LTS 4 and Avoid metres at WORTH_WEIGHTS, plus its red
    junctions' cost at the LTS 4 weight and its orange junctions' cost at the LTS 3
    weight, on a ride that weighs LTS 2 (FOLLOWUP-LTS2-WEIGHT) its LTS 2 metres at
    that share of the LTS 3 weight: a quarter (a half on Riding with kids), so a mile
    of LTS 2 saved buys a quarter (a half) of what a mile of LTS 3 does, and each
    Avoid-rated junction's penalty in quiet metres, one for one (308: 30 minutes, as
    it is in the score). Its metres are hill-weighted (`Analysis.hill`, OWNER-DECISIONS 409;
    the owner's "Count it", 2026-10-11, on whether the hill counts when a longer route is
    worth its extra miles: "A longer route can win by avoiding a busy climb, so some plans
    get longer"), so a longer route can buy its miles by avoiding a busy climb."""
    return _top_weight_m(read) + _second_weight_m(read)


def _top_weight_m(read: Analysis) -> float:
    """The top figure's part of `stress_weight_m`: LTS 4, Avoid, red junctions and
    Avoid-rated junctions."""
    w = WORTH_WEIGHTS
    return (
        w.lts4 * (read.lts4_m - read.avoid_m)
        + w.avoid * read.avoid_m
        + (w.avoid - w.lts4) / 2 * read.lts45_m
        + w.lts4 * read.red_m
        + read.avoid_junction_m
    )


def _second_weight_m(read: Analysis) -> float:
    """The second figure's part of `stress_weight_m`: LTS 3 and orange junctions, and
    LTS 2 at the ride's weight where it has one (`Analysis.second_m`)."""
    return WORTH_WEIGHTS.lts3 * read.second_m


def stress_saved_m(worse: Analysis, calmer_one: Analysis, ctx: Context) -> float:
    """The stress (metres of LTS 3, `stress_weight_m`) `calmer_one` saves over `worse`
    for the diminishing-returns rule, counted at the highest level of `Analysis.key`
    that improves (combined spec review, SF2; OWNER-DECISIONS 287(1): "LTS 4 still
    ranks first in the stress order; these weights only govern how many extra miles a
    stress saving buys"). Where the top figure improves by more than its tie step, its
    saving pays on its own and a loss at the second level does not subtract from it
    (a gain there still adds), so LTS 4 never loses to extra LTS 3. Otherwise the two
    levels are netted at the 1/2/3 weights, as within one level they always were. Both
    are in hill-weighted metres (409 and the owner's "Count it", 2026-10-11), so avoiding
    a busy LTS 4 climb is a top-level saving.

    It errs the safe way (the release re-check's NT1, kept as it is): `Analysis.top_m`
    counts Avoid metres as LTS 4's, but `_top_weight_m` weighs them 3 to 2, so a route
    that trades LTS 4 for Avoid can rank calmer on `top_m` and still have a negative
    saving here (1000 m of LTS 4 against 900 m all Avoid: -700). Such a route is never
    worth any extra distance, which is right, since Avoid is worse."""
    top = _top_weight_m(worse) - _top_weight_m(calmer_one)
    second = _second_weight_m(worse) - _second_weight_m(calmer_one)
    if worse.top_m - calmer_one.top_m > MAXCALM_STEPS[0]:
        return top + max(second, 0.0)
    return top + second


def distance_charge_m(
    from_m: float, to_m: float, ctx: Context, blended_m: float | None = None
) -> float:
    """The stress (metres of LTS 3, `stress_weight_m`) a route must save to be
    `to_m` long rather than `from_m` (actual metres of the whole trip; 268, 271):
    - with a target, the actual metres up to it over WORTH_UP_TO_TARGET (435, "One
      rule") and those past it over WORTH_OVER_TARGET (the target is in actual
      miles, 262);
    - with none, the metres added over the slider's `worth_ratio`, as the Hills slider weighs
      them (`blended_m`, the difference in `level3`; `to_m - from_m` where it is
      not given), so a longer route that is less effort is not charged for it."""
    if ctx.target_m is None:
        added = to_m - from_m if blended_m is None else blended_m
        return max(added, 0.0) / worth_ratio(ctx)
    over = to_m - max(from_m, ctx.target_m)
    within = min(to_m, ctx.target_m) - from_m
    return max(over, 0.0) / WORTH_OVER_TARGET + max(within, 0.0) / WORTH_UP_TO_TARGET


def worth_ratio(ctx: Context) -> float:
    """Metres a route may add for each metre of LTS 3 (`stress_weight_m`) it saves, where
    the rider set no target (OWNER-DECISIONS 435, "One rule"): WORTH_DEFAULT at the top
    of the slider, and below it 1 + (WORTH_DEFAULT - 1) x the calm rate over its top."""
    if ctx.maxcalm:
        return WORTH_DEFAULT
    return 1.0 + (WORTH_DEFAULT - 1.0) * max(ctx.rate, 0.0) / presets.CALM_RATE_MAX


def worth_it(shorter: Analysis, longer: Analysis, ctx: Context, rest_m: float = 0.0) -> bool:
    """Whether `longer` saves enough stress over `shorter` for the distance it adds
    (`distance_charge_m`). `rest_m` is the rest of the trip where the two are one leg
    of it (the target is the whole trip's). Always, where the rule is off."""
    if not ctx.worth_rule or (not ctx.maxcalm and ctx.rate <= 0):
        # No calm search (crossing avoidance alone): no bar on distance but the score.
        return True
    charge = distance_charge_m(
        shorter.length_m + rest_m,
        longer.length_m + rest_m,
        ctx,
        charged_m(longer, ctx) - charged_m(shorter, ctx),
    )
    if charge <= 0.0:
        return True
    return stress_saved_m(shorter, longer, ctx) >= charge


def calmer(read: Analysis, best: Analysis, ctx: Context) -> bool:
    """Whether `read` ranks before `best` by `MAXCALM_STEPS` down `Analysis.key`
    (OWNER-DECISIONS 258-262)."""
    for step, got, have in zip(MAXCALM_STEPS, read.key(ctx), best.key(ctx), strict=True):
        if have - got > step:
            return True
        if got - have > step:
            return False
    return False


# Seconds of quiet riding each red junction counts for in the score, below the top of the
# slider, on top of its junction cost (the owner, 2026-10-23, of the unsignalised crossings
# of University Blvd and Connecticut Ave in Kensington at rush hour: "essentially
# impassable", and a rider would rather ride 10 minutes more). The junction cost alone
# weighed a red as an equal sum of orange ones: on the PC's check of a NoMa to Twinbrook
# commute at Default, a detour with one red where the router's route had two scored 606 s
# worse for its oranges and delay, and a red-free one 40 s worse off peak. Scaled by the
# intersection weight (`intersection_weight`): all of it from Default up, a quarter at the
# traffic tolerant end. A price, not a rule ahead of the score, so the order stays total and
# Avoid-rated junctions, LTS 3 and the oranges still count (review of PR #426). A red now
# scores about as much as a pass through an Avoid-rated junction (1,800 cost seconds, 308);
# the approved Avoid list is empty as shipped.
RED_DETOUR_S = 600.0


def red_count(read: Analysis) -> int:
    """The route's red junctions as the map draws them, never shifted: a ride that reads
    every road a level up does not make its oranges impassable."""
    return sum(1 for e in read.events or () if e.severity == model.RED)


def better(read: Analysis, best: Analysis, ctx: Context, rest_m: float = 0.0) -> bool:
    """Whether `read` is to replace `best`: below the top of the slider, by the
    score (IMPROVEMENT_EPS_S), a longer route also worth its extra miles (`worth_it`,
    435 "One rule"); at the top, by `MAXCALM_STEPS` down `Analysis.key` (`calmer`), with
    diminishing returns on the distance (`worth_it`): a longer route must be calmer and
    worth its extra miles, and a shorter one replaces a calmer longer one whose extra miles
    were not worth it. `rest_m`: see `worth_it`."""
    if not ctx.maxcalm:
        # Below the top a longer route must also be worth its miles (OWNER-DECISIONS
        # 435, "One rule"; `worth_ratio`), wherever the calm search runs.
        if read.score(ctx) >= best.score(ctx) - IMPROVEMENT_EPS_S:
            return False
        return read.length_m <= best.length_m or worth_it(best, read, ctx, rest_m)
    if read.length_m > best.length_m:
        return calmer(read, best, ctx) and worth_it(best, read, ctx, rest_m)
    if calmer(read, best, ctx):
        return True
    return calmer(best, read, ctx) and not worth_it(read, best, ctx, rest_m)


def late_deadline(ctx: Context) -> routing.Deadline:
    """The deadline of a reading made late in the plan, after or outside the search
    (`dedodge.settle`, `refine_long`'s final reading, `routing._past_target`): the
    plan's, less REFINE_TRACE_RESERVE_S kept back for the answer's own traces and
    junctions (combined correctness review, S3). A reading the clock cuts short there
    raises DeadlineExceeded (`events_of_raws`) and is not remembered."""
    return routing.Deadline(ctx.deadline.at - REFINE_TRACE_RESERVE_S, ctx.deadline.per_call_s)


def too_long(length_m: float, ctx: Context) -> bool:
    """Whether a route of `length_m` is past the ceiling (`Context.ceiling_m`)."""
    return ctx.ceiling_m is not None and length_m > ctx.ceiling_m


def locator(variant: str, deadline: routing.Deadline, located: dict | None = None):
    """`/locate` through the plan's own budgeted router call. With `located` (the
    plan's `Context.located`), a place and radius already answered is not asked again:
    only the others are sent, and the answers come back in the order asked. A short
    answer from the router ends the list where it ended, as the router's would. Each
    answer is cut to the fields the junctions read (`junctions.slim_locate`, audit S21) on
    the thread that asked, before it is kept."""

    def ask(payload: dict) -> list[dict]:
        answers = routing._call(variant, "locate", payload, deadline)
        if not isinstance(answers, list):
            return answers
        return [junctions.slim_locate(answer) for answer in answers]

    def locate(payload: dict) -> list[dict]:
        if located is None:
            return ask(payload)
        keys = [
            (variant, round(p["lon"], 6), round(p["lat"], 6), p.get("radius"))
            for p in payload["locations"]
        ]
        unseen = [i for i, key in enumerate(keys) if key not in located]
        if unseen:
            asked = {**payload, "locations": [payload["locations"][i] for i in unseen]}
            answers = ask(asked)
            for i, answer in zip(unseen, answers, strict=False):
                located[keys[i]] = answer
        out = []
        for key in keys:
            if key not in located:
                break
            out.append(located[key])
        return out

    return locate


def events_of_raws(raws, ctx: Context, deadline: routing.Deadline) -> list | None:
    """The junction events of a route's raw junctions, or None where the roads
    or the router could not be asked. Where the clock cut the `/locate` batches off
    part way (`junctions.ReadingCutShort`) the reading is not made of the junctions
    read so far: DeadlineExceeded is raised, so it is neither used nor remembered
    (combined correctness review, S3)."""
    try:
        return junctions.events_of(
            raws,
            ctx.when,
            ctx.with_facility,
            locator(ctx.variant, deadline, ctx.located),
            ctx.group,
            cut_short=(routing.DeadlineExceeded,),
            ratings=ctx.junction_ratings,
            beacons=ctx.beacons,
        )
    except junctions.ReadingCutShort as error:
        raise routing.DeadlineExceeded(str(error)) from error
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
    # Every leg's trace at once (v0.7.0, "Faster routing" step 3), read in order below.
    routing.prefetch_traces(ctx.variant, ctx.costing, [trip], deadline, ctx.traces)
    pieces: list = []
    raws: list = []
    marks: list = []
    mark_legs: list = []
    offset = 0.0
    via_m: list[float] = []
    line: list = []
    for number, leg in enumerate(legs):
        trace = routing._trace(ctx.variant, ctx.costing, leg.get("shape", ""), deadline, ctx.traces)
        if trace is None:
            return None
        shape = routing.decode_polyline6(leg.get("shape", ""))
        # Each trace read once a plan, at its start, and shifted here (audit S19).
        made, read = routing.trace_reading(trace, shape, marks=True)
        pieces.extend(made)
        raws.extend(trace_junctions.junctions_along(read, offset))
        leg_marks = trace_junctions.marks_along(read, offset)
        marks.extend(leg_marks)
        mark_legs.extend([number] * len(leg_marks))
        line.extend(shape[1:] if line else shape)
        offset += sum(piece.metres for piece in made)
        if number < len(legs) - 1:
            via_m.append(offset)
    real_classes = routing.classify(pieces, ctx.when, ctx.lanes_as_roadway)
    shift = ctx.exposure.shift
    classes = shift_classes(real_classes, shift)
    # A known hazard ridden is searched as the graph prices it, LTS 4 (v0.10.0); the rider
    # is still shown its own rating (`rated_classes`).
    # The kinds as the stress query read them (audit S16), else in a query of their own.
    kinds = routing.hazards_read(real_classes, pieces)
    if kinds is None:
        kinds = route_hazards.kinds_of(pieces)
    priced = hazard_priced(classes, kinds)
    hazard_read = priced is not classes
    classes = priced
    avoid_passages = avoid_model.passages(line, ctx.avoid) if ctx.avoid else []
    # The stress figures in hill-weighted metres (409): each piece's metres times its factor.
    hill = hill_of(trip, pieces, ctx)
    hilled = [_Metres(piece.metres * f) for piece, f in zip(pieces, hill, strict=True)]
    stress, _facility = routing.totals(zip(hilled, classes, strict=True))
    halves = half_metres(hilled, classes)
    weights = ctx.exposure.weights
    result = Analysis(
        length_m=float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0,
        cost_s=routing._router_cost(trip),
        exposure_m=sum(weights[tier] * stress[tier] for tier in weights)
        + half_exposure_m(halves, weights),
        climb_m=routing._climb_of(trip),
        pieces=pieces,
        classes=classes,
        events=events_of_raws(raws, ctx, deadline) if with_events else None,
        via_m=via_m,
        marks=marks,
        mark_legs=mark_legs,
        **stress_totals(stress, halves),
        lts2_weight=ctx.exposure.lts2,
        effort_m=effort.effort_equivalent_m(
            routing.grade_profile(trip),
            float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0,
            ctx.mass_kg,
        )
        or float((trip.get("summary") or {}).get("length", 0.0)) * 1000.0,
        avoid_passages=avoid_passages,
        avoid_junction_m=(
            avoid_model.penalty_s(avoid_passages) / ctx.quiet_cost if ctx.quiet_cost > 0 else 0.0
        ),
        router_climb_m=climbs.router_climb_m(routing.grade_profile(trip), use_hills_of(ctx)),
        hill_m=hill_cost.hill_cost_m(
            routing.grade_profile(trip),
            ctx.mass_kg,
            flat_speed_ms(ctx.costing),
            ctx.hills,
        )
        + (
            steep_grades.penalty_s(routing.grade_profile(trip)) * flat_speed_ms(ctx.costing)
            if ctx.steep_grades
            else 0.0
        ),
        hill=hill,
        flat_exposure_m=flat_exposure_m(pieces, classes, weights),
        rated_lts2_m=stress_totals(*rated_metres(pieces, classes))["lts2_m"],
        real_classes=real_classes if shift or hazard_read else None,
        shift=shift,
        hazard_kinds=kinds,
        scenic=getattr(real_classes, "scenic", None),
        adjustments=getattr(real_classes, "adjustments", None),
        junction_delay_s=junction_delay.delay_s(
            raws,
            routing.stop_as_yield,
            lambda lon, lat: model.beacon_at(lon, lat, ctx.beacons) is not None,
        ),
    )
    if with_events:
        ctx.analyses[key] = result
    return result


@dataclass(frozen=True)
class _Metres:
    """A piece's metres as the stress figures count them (`analyse`)."""

    metres: float


def hill_of(trip: dict, pieces: list, ctx: Context) -> list[float]:
    """Each traced piece's hill factor (`grade_stress.hill_factors`, 409): the trip's
    elevation profile's counted windows (`routing.grade_profile`, climbs of GRADE_FROM and
    descents past the ride type's brake grade) against its pieces, in metres along the
    route, in the order ridden, at the hills slider's coefficient. All 1 at a coefficient of
    0 ("fine with hills")."""
    lengths = [piece.metres for piece in pieces]
    if ctx.hill_coefficient == 0:
        return [1.0] * len(lengths)
    windows = grade_stress.hill_windows(
        routing.grade_profile(trip), mass_kg=ctx.mass_kg, brake_grade=ctx.brake_grade
    )
    return grade_stress.hill_factors(windows, lengths, ctx.hill_coefficient)


def rated_metres(pieces, classes) -> tuple[dict, dict]:
    """The rated metres by tier, and of each half step (`half_metres`), unweighted."""
    stress, _facility = routing.totals(zip(pieces, classes, strict=True))
    return stress, half_metres(pieces, classes)


def flat_exposure_m(pieces, classes, weights: dict[str, float]) -> float:
    """`Analysis.exposure_m` at a hill factor of 1: the rated metres at the ride's weights."""
    stress, halves = rated_metres(pieces, classes)
    return sum(weights[tier] * stress[tier] for tier in weights) + half_exposure_m(halves, weights)


def stress_totals(stress: dict, halves: dict) -> dict[str, float]:
    """The LTS 2, LTS 3, LTS 4 and Avoid metres the worth rule and the LTS 4 hold read, half
    steps at the midpoints of the strict order's figures (461a; stress-number.md section 3):
    1.5 counts half a metre of LTS 2; 2.5 half of LTS 2 and half of LTS 3; 3.5 half of LTS 3
    and half of LTS 4; 4.5 a whole metre of LTS 4 (never Avoid, 441k), kept apart (`lts45_m`)
    for its midpoint weight. A half step's metres are in its lower level's `stress` figure."""
    return {
        "lts4_m": stress["4"] + stress["5"] + 0.5 * halves["3"],
        "lts3_m": stress["3"] + 0.5 * halves["2"] - 0.5 * halves["3"],
        "lts2_m": stress["2"] + 0.5 * halves["1"] - 0.5 * halves["2"],
        "avoid_m": stress["5"],
        "lts45_m": halves["4"],
    }


def half_metres(pieces, classes) -> dict[str, float]:
    """The metres of each half step, keyed by its lower level ("3" is 3.5)."""
    out = dict.fromkeys(("1", "2", "3", "4"), 0.0)
    for piece, cls in zip(pieces, classes, strict=False):
        if getattr(cls, "half", False) and cls[0] in out:
            out[cls[0]] += piece.metres
    return out


def half_weight(tier: str, weights: dict[str, float]) -> float:
    """A half step's weight: the midpoint of its two levels' (461a). LTS 1 and 2 weigh 0."""
    if tier not in ("1", "2", "3", "4"):
        return weights.get(tier, 0.0)
    return (weights.get(tier, 0.0) + weights.get(str(int(tier) + 1), 0.0)) / 2


def half_exposure_m(halves: dict[str, float], weights: dict[str, float]) -> float:
    """What the half steps add to `exposure_m` over their lower levels' weights."""
    return sum(m * (half_weight(t, weights) - weights.get(t, 0.0)) for t, m in halves.items())


def cautious_tier(cls) -> int | None:
    """A piece's level for an on/off rule (461a): a half step takes the cautious side, the
    level above, except that 4.5 is never Avoid (441k). None where it is not rated."""
    tier = cls[0]
    if tier not in ("1", "2", "3", "4", "5"):
        return None
    level = int(tier)
    if getattr(cls, "half", False) and level < 4:
        level += 1
    return level


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
    # Metres round the point the router excludes every edge within (`exclude_locations`'
    # `radius`); None for the router's default (the nearest edge). An Avoid-rated
    # junction's is `MATCH_RADIUS_M`, as `core.avoid_junctions.exclusions` asks.
    radius: int | None = None


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
        level = cautious_tier(analysis.classes[min(bisect.bisect_left(ends, at), len(ends) - 1)])
        if level is None or level < 3 or level < min_tier:
            continue
        point = (lon, lat)
        if kept and haversine(Point(*kept[-1].point), Point(*point)) < CALM_SAMPLE_M:
            continue
        if _clear_of_ends(at, total, analysis.via_m):
            kept.append(Target(point, level))
    if len(kept) > CALM_POINTS_PER_ROUND:
        step = len(kept) / CALM_POINTS_PER_ROUND
        kept = [kept[int(i * step)] for i in range(CALM_POINTS_PER_ROUND)]
    return kept


def avoid_targets(analysis: Analysis, ctx: Context) -> list[Target]:
    """The Avoid-rated junctions the route passes (307), each its own point: an
    exclusion on a junction's node takes out every edge there, which is the way
    round. Not near the route's ends, where the router must leave and arrive."""
    return [
        Target((p.junction.lon, p.junction.lat), 5, int(avoid_model.MATCH_RADIUS_M))
        for p in analysis.avoid_passages
        if _clear_of_ends(p.m, analysis.length_m, analysis.via_m)
    ]


def _exclusion(lon: float, lat: float, ctx: Context, radius: int | None = None) -> dict:
    """One `exclude_locations` entry: an Avoid-rated junction's point (from a Target or a
    kept point) with `MATCH_RADIUS_M`, so every edge at it goes, else the point alone."""
    if radius is None and any(j.lon == lon and j.lat == lat for j in ctx.avoid):
        radius = int(avoid_model.MATCH_RADIUS_M)
    out: dict = {"lon": lon, "lat": lat}
    if radius:
        out["radius"] = radius
    return out


def crossing_targets(analysis: Analysis, ctx: Context) -> list[Target]:
    """The Avoid-rated junctions the route passes, then the worst junctions: for each,
    the approach (a point on the edge the route arrives by) and the junction itself, every
    edge within `avoid_junctions.MATCH_RADIUS_M` of it, so that the next round cannot
    come at the same crossing by another street (review of PR #421)."""
    avoid = avoid_targets(analysis, ctx)
    if ctx.group or not analysis.events:
        return avoid
    worst = sorted(
        (e for e in analysis.events if e.approach and e.cost_ft >= REFINE_MIN_EVENT_FT),
        key=lambda e: -e.cost_ft,
    )
    chosen = [e for e in worst if _clear_of_ends(e.m, analysis.length_m, analysis.via_m)][
        :CROSSING_POINTS_PER_ROUND
    ]
    return avoid + [
        target
        for e in chosen
        for target in (
            Target(e.approach, 4),
            Target((e.lon, e.lat), 4, int(avoid_model.MATCH_RADIUS_M)),
        )
    ]


def refine(trip: dict, ctx: Context) -> tuple[dict, dict]:
    """The best of the original route, the router's own alternatives (where
    `Context.rank_alternates` asks for them) and the routes found by excluding what is
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
    # The Traffic-wins guard's reference, in rated metres (61, 409: `rated_exposure_m`).
    first_exposure = best.rated_exposure_m
    ctx.first_avoid_m = best.avoid_junction_m
    ctx.first_red_m = best.red_m
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
        info["lts4_before_m"] = round(rated_lts4_m(best), 1)
    best, best_trip = _router_alternates(trip, best, first_exposure, stop_at, ctx, info)
    best, best_trip = _search(best_trip, best, first_exposure, stop_at, ctx, info)
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
        info["lts4_after_m"] = round(rated_lts4_m(best), 1)
    if ctx.options is not None and ctx.alternates:
        pool = [(best_trip, best)] + [o for o in ctx.options if o[0] is not best_trip]
        ctx.candidate_reference = list(ctx.first_lts4)
        ctx.candidates = more_routes(
            pick_candidates(pool, ctx, ctx.first_lts4), ctx, ctx.first_lts4
        )
    return best_trip, info


# The router's own alternative routes (OWNER-DECISIONS 435, "Yes, rank alternatives by
# our own stress measures"): the calm search asks for them once, before its rounds,
# and every one is read and ranked with the router's first route and the search's
# detours by the same rule (`better`: the score below the top of the slider, the
# stress order and the worth of the extra miles at it) and the same guards. The
# rounds then start from whichever ranks first. Valhalla gives alternatives only
# between two locations, and `max_alternates` is 3 (valhalla/valhalla-*.json).
ROUTER_ALTERNATES = 3
# The ask and its readings stop this long before the search's own end, so that at
# least one exclusion round is always left the time to run (the rounds were the
# whole calm search before 435): a round's least and a second over, so an ask that
# times out at its own end still leaves one (re-check, correctness); and the ask is
# not started with less than ALTERNATES_MIN_S left before that. Loops never ask:
# their request has three locations or more.
ALTERNATES_ROUND_RESERVE_S = REFINE_ROUND_MIN_S + 1.0
ALTERNATES_MIN_S = 1.0
# The time allowed for the reading of the first route when the plan starts the ask
# beside it (`ask_alternates_early`): the ask runs on the router no longer than the
# search, starting after that reading, could wait for it, so that an answer it would
# never wait for does not keep a router slot (review of S2b).
EARLY_ALTERNATES_READ_S = 2.0


@dataclass
class EarlyAlternates:
    """The search's ask for the router's alternatives, started by the plan on the pool
    while its first route is read (`ask_alternates_early`): the variant and request
    asked (a copy, so later changes to the plan's own do not reach it) and the pending
    answer."""

    variant: str
    request: dict
    future: Future


def _alternates_request(request: dict) -> dict:
    """The search's ask for alternatives: the request without its work-zone points
    (`exclude_locations`), with ROUTER_ALTERNATES."""
    asked = {k: v for k, v in request.items() if k != "exclude_locations"}
    asked["alternates"] = ROUTER_ALTERNATES
    return asked


def _alternates_limit(variant: str, deadline: routing.Deadline) -> float:
    limit = min(deadline.per_call_s, routing.ALTERNATES_TIMEOUT_S)
    if variant in routing.TWIN_VARIANTS:
        limit = min(limit, routing.WEEKEND_TIMEOUT_S)
    return limit


def ask_alternates_early(
    variant: str, request: dict, deadline: routing.Deadline
) -> EarlyAlternates | None:
    """Start the search's ask for alternatives (`_router_alternates`) on the pool now,
    beside the reading of the first route, which it does not depend on (S2 of the
    v0.13.0 routing audit). Only where the pool is on: inline it would make the first
    route wait. None where it is off or there is no time for the ask. The ask runs
    no longer than the search could wait for it (EARLY_ALTERNATES_READ_S), the search
    waits for it no longer than it would have for its own ask, and asks again as
    before where the request has changed since."""
    if not parallel.enabled():
        return None
    search_stop = min(
        deadline.at - REFINE_TRACE_RESERVE_S,
        routing.clock() + REFINE_BUDGET_S + EARLY_ALTERNATES_READ_S,
    )
    alt_stop = search_stop - ALTERNATES_ROUND_RESERVE_S
    if alt_stop - routing.clock() < ALTERNATES_MIN_S:
        return None
    asked = copy.deepcopy(_alternates_request(request))
    future = parallel.submit(
        routing._call,
        variant,
        "route",
        copy.deepcopy(asked),
        routing.Deadline(alt_stop, _alternates_limit(variant, deadline)),
    )
    return EarlyAlternates(variant, asked, future)


def _router_alternates(trip, best, first_exposure, stop_at, ctx: Context, info: dict):
    """The best of the router's first route and its alternatives, read and ranked as
    every other candidate (see ROUTER_ALTERNATES), and its trip. The plan's own
    alternatives are used where it already asked for them with this request
    (`Context.router_trips`), and none are asked for again where that ask timed out.
    `info["alternates"]` says how many routes other than this one the router gave,
    how many could be read and passed the guards, whether one was taken, and
    `limited` (`time`: the ask or a reading ran out of its time; null otherwise); it
    is absent where they were not asked for (`Context.rank_alternates` off, a plan
    with stops or a loop, or no time for it)."""
    locations = ctx.request.get("locations") or []
    if not ctx.rank_alternates or len(locations) != 2:
        return best, trip
    alt_stop = stop_at - ALTERNATES_ROUND_RESERVE_S
    given = ctx.router_trips
    if given is None and alt_stop - routing.clock() < ALTERNATES_MIN_S:
        return best, trip
    found = {"given": 0, "ranked": 0, "taken": False, "limited": None}
    info["alternates"] = found
    if given == []:
        # The plan's own ask for them timed out (`routing._route`): not asked again.
        found["limited"] = "time"
    if given is None:
        request = _alternates_request(ctx.request)
        early = ctx.early_alternates
        if early is not None and (early.variant != ctx.variant or early.request != request):
            # The request changed after the plan asked (the target fitting): asked again.
            early.future.cancel()
            early = None
        started = routing.clock()
        try:
            if early is not None:
                # Waited for no longer than the search's own ask would have run.
                # Read as every other pooled call is (`routing.await_future`), so a cancel of
                # the plan is seen while it waits, not seconds later (review of S7).
                answer = routing.await_future(early.future, timeout=max(alt_stop - started, 0.0))
            else:
                answer = routing._call(
                    ctx.variant,
                    "route",
                    request,
                    routing.Deadline(alt_stop, _alternates_limit(ctx.variant, ctx.deadline)),
                )
        except routing.PlanCancelled:
            # A DeadlineExceeded, but not a slow router: the plan ends here (review of S7).
            raise
        except routing.RouterRefused:
            return best, trip
        except (routing.DeadlineExceeded, routing.RouterUnavailable, TimeoutError) as error:
            logger.warning(
                "the %s router did not answer the calm search's ask for alternatives in"
                " %.1f s (%s); searching without them",
                ctx.variant,
                routing.clock() - started,
                type(error).__name__,
            )
            found["limited"] = "time"
            return best, trip
        given = [answer.get("trip") or {}] + [
            (alternate or {}).get("trip") or {} for alternate in answer.get("alternates") or []
        ]
    own = tuple(leg.get("shape", "") for leg in trip.get("legs") or [])
    best_trip = trip
    # The router's routes are traced together (v0.7.0, "Faster routing" step 3), each then
    # read in turn below as before.
    routing.prefetch_traces(
        ctx.variant,
        ctx.costing,
        [
            candidate
            for candidate in given
            if (candidate.get("legs") or [])
            and tuple(leg.get("shape", "") for leg in candidate["legs"]) != own
            and not too_long(_trip_m(candidate), ctx)
        ],
        routing.Deadline(alt_stop, ctx.deadline.per_call_s),
        ctx.traces,
    )
    for candidate in given:
        legs = candidate.get("legs") or []
        # The route the search starts from is not an alternative to itself.
        if not legs or tuple(leg.get("shape", "") for leg in legs) == own:
            continue
        found["given"] += 1
        if too_long(_trip_m(candidate), ctx):
            continue
        if alt_stop - routing.clock() <= 0:
            found["limited"] = "time"
            break
        try:
            read = analyse(candidate, ctx, routing.Deadline(alt_stop, ctx.deadline.per_call_s))
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            found["limited"] = "time"
            break
        # The guards every candidate meets: not busier than the router's first route
        # (Traffic wins), the LTS 4 hold, and junctions that could be read.
        if read is None or read.events is None:
            continue
        if _busier(read, first_exposure, ctx) or more_lts4(read, ctx.first_lts4, ctx):
            continue
        found["ranked"] += 1
        if ctx.options is not None:
            ctx.options.append((candidate, read))
        if better(read, best, ctx):
            best, best_trip = read, candidate
            found["taken"] = True
    return best, best_trip


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
        request["exclude_locations"] = [_exclusion(lon, lat, ctx) for lon, lat in excludes]
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
    junctions in it (`Analysis.top_m`, but with the rated LTS 4 metres, `lts4_by_leg`),
    by traced metres (`leg_bounds`)."""
    bounds = leg_bounds(analysis)
    out = lts4_by_leg(analysis)
    for event in analysis.events or ():
        if presets.shifted_severity(event.severity, analysis.shift) != "red":
            continue
        for k, (lo, hi) in enumerate(bounds):
            if lo <= event.m < hi or (k == len(bounds) - 1 and event.m >= hi):
                out[k] += event.cost_ft / model.FEET_PER_METRE
                break
    return out


def lts4_by_leg(analysis: Analysis) -> list[float]:
    """Each leg's LTS 4 and Avoid metres, in traced metres (`leg_bounds`): the rated metres,
    not hill-weighted (409), so the LTS 4 hold never lets a candidate buy more LTS 4 by
    leaving out a hill."""
    bounds = leg_bounds(analysis)
    out = [0.0] * len(bounds)
    along = 0.0
    for piece, cls in zip(analysis.pieces, analysis.classes, strict=False):
        tier = cls[0]
        a, b = along, along + piece.metres
        along = b
        # 3.5 counts half a metre (461a: the midpoint of LTS 3's 0 and LTS 4's 1).
        half = getattr(cls, "half", False)
        share = 1.0 if tier in LTS4_TIERS else 0.5 if tier == "3" and half else 0.0
        if not share:
            continue
        for k, (lo, hi) in enumerate(bounds):
            out[k] += share * max(0.0, min(b, hi) - max(a, lo))
    return out


def rated_lts4_m(analysis: Analysis) -> float:
    """The route's rated LTS 4 and Avoid metres, not hill-weighted (`lts4_by_leg`): the LTS 4
    hold's figure, and the answer's `lts4_before_m` and `lts4_after_m`."""
    return sum(lts4_by_leg(analysis))


def more_lts4(read: Analysis, reference: list[float], ctx: Context) -> bool:
    """Whether the LTS 4 hold refuses a candidate (OWNER-DECISIONS 250, amended by
    259): on a stress-averse ride, a larger top figure (LTS 4 and Avoid metres plus
    the cost of the red junctions, `Analysis.top_m`) than `reference` (the router's
    first route's, a leg's each) for the whole of it, or for any leg where it has
    the reference's legs. So LTS 4 may be traded for a red junction's worth, never
    for nothing, and never for leaving out a hill: the LTS 4 metres are the rated ones,
    not hill-weighted (409, `lts4_by_leg`). Never on another ride."""
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
    for piece, cls in zip(analysis.pieces, analysis.classes, strict=False):
        tier = cls[0]
        a, b = along, along + piece.metres
        along = b
        if b <= lo or (hi is not None and a >= hi):
            continue
        a, b = max(a, lo), b if hi is None else min(b, hi)
        half = getattr(cls, "half", False)
        weight = half_weight(tier, weights) if half else weights.get(tier, 0.0)
        if weight:
            busy.append((a - lo, b - lo, weight))
    traced = (along if hi is None else min(hi, along)) - lo
    return busy, (traced or None)


def seek_weights(exposure: presets.Exposure) -> dict[str, float]:
    """The busy road the trail seek looks to replace (`_seek_corridors`): the plan's
    exposure weights for LTS 3 and worse only. LTS 2's weight (FOLLOWUP-LTS2-WEIGHT) is
    left out, so a stretch of LTS 2 never starts a trail seek or its router calls; the
    seek's guards still read the whole exposure, LTS 2 included."""
    return {tier: w for tier, w in exposure.weights.items() if tier != "2"}


def exposure_spans(analysis: Analysis) -> tuple[Spans, float | None]:
    """The route's busy stretches as (from, to, weight) in traced metres, and
    its traced length (None for a route with no pieces)."""
    return route_spans(analysis)


def leg_bounds(analysis: Analysis) -> list[tuple[float, float]]:
    """Where each leg of the route starts and ends, in traced metres."""
    total = sum(piece.metres for piece in analysis.pieces)
    edges = [0.0, *analysis.via_m, total]
    return list(zip(edges, edges[1:], strict=False))


def retrace_m(analysis: Analysis) -> float:
    """The metres of the route on an edge the same leg has already ridden, in either
    direction: an out-and-back along a way to a through point and back. Edges are
    matched by their middles (`_marks`), so the way out and the way back of one edge
    are the one edge. A leg is the stretch between the plan's own locations: a stop
    the rider placed down a dead end is theirs to ride out to and back from."""
    marks = _marks(analysis)
    legs = analysis.mark_legs if len(analysis.mark_legs) == len(marks) else None
    bounds = leg_bounds(analysis)
    cell = RETRACE_MATCH_M
    seen: dict[tuple[int, int, int], list[tuple[float, float, float]]] = {}
    total = 0.0
    leg = 0
    for number, (along, lon, lat, metres) in enumerate(marks):
        if legs is not None:
            leg = legs[number]
        else:
            while leg < len(bounds) - 1 and along >= bounds[leg][1]:
                leg += 1
        x = lon * 111_320.0 * math.cos(math.radians(lat))
        y = lat * 110_540.0
        cx, cy = math.floor(x / cell), math.floor(y / cell)
        again = any(
            math.hypot(x - ox, y - oy) <= RETRACE_MATCH_M
            and abs(metres - om) <= max(RETRACE_MATCH_M, 0.1 * max(metres, om))
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for ox, oy, om in seen.get((leg, cx + dx, cy + dy), ())
        )
        if again:
            total += metres
        else:
            seen.setdefault((leg, cx, cy), []).append((x, y, metres))
    return total


def doubles_back(read: Analysis, reference_m: float) -> bool:
    """Whether a candidate rides back over its own way more than RETRACE_SLACK_M past
    `reference_m`, the `retrace_m` of the route it would replace."""
    return retrace_m(read) > reference_m + RETRACE_SLACK_M


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
        # A ride on the no-trail graph (Mass Ride, or any ride with trails off): there are
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
            reference = first_legs[k] if first_legs else incumbent.rated_exposure_m
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
        room = None if ctx.ceiling_m is None else ctx.ceiling_m - _trip_m(trip)
        rest_m = 0.0 if count == 1 else _trip_m(trip) - _trip_m(leg_trip)
        got = _seek_leg(
            k,
            leg_trip,
            incumbent,
            reference,
            leg_stop,
            ctx,
            seek,
            reference_lts4,
            room,
            rest_m,
            pooled=count == 1,
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
        if read.rated_exposure_m > _allowance(first_exposure):
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
        # And never past the ceiling.
        if too_long(read.length_m, ctx):
            seek["taken"] = False
            seek["whole_trip"] = "too_long"
            seek["limited"] = seek["limited"] or "too_long"
            return best, best_trip
        # And the extra miles worth the stress they save (OWNER-DECISIONS 268, 271).
        if read.length_m > best.length_m and not worth_it(best, read, ctx):
            seek["taken"] = False
            seek["whole_trip"] = "not_worth"
            seek["limited"] = seek["limited"] or "not_worth"
            return best, best_trip
        # And never more LTS 4 than the router's first route (item 250).
        if more_lts4(read, ctx.first_lts4, ctx):
            seek["taken"] = False
            seek["whole_trip"] = "more_lts4"
            seek["limited"] = seek["limited"] or "more_lts4"
            return best, best_trip
        # The spliced trip, read whole, is now the search's best and so the answer the
        # routes to choose from are picked against; a leg of it alone is never
        # pooled (B1, `pooled`).
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
    rest_m: float = 0.0,
    pooled: bool = True,
):
    """The seek on one leg: (reading, trip) of the leg if a candidate was kept,
    else None. `reference` is the leg's exposure as the router first gave it
    (the Traffic-wins guard's), and `reference_lts4` its LTS 4 and Avoid metres
    then, as a one-item list (the LTS 4 hold's, OWNER-DECISIONS 250). `room_m` is
    how many metres longer than the incumbent a candidate may be before the trip
    is past the ceiling (None: no limit), and `rest_m` the length of the rest of the
    trip (the diminishing-returns rule is the whole trip's, `worth_it`).
    `pooled`: whether the candidates read are kept in `Context.options` for the
    routes to choose from. Only where the leg is the whole trip: on a plan with
    more than one leg (a loop, stops) a leg's candidate is one leg of the trip, and
    is never offered as a whole route (combined correctness review, B1)."""
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
    busy, traced_m = route_spans(incumbent, weights=seek_weights(ctx.exposure))
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
    # Held to the leg's own route, not to the best candidate so far, so that each one
    # taken cannot raise the bar by another RETRACE_SLACK_M.
    incumbent_retrace_m = retrace_m(incumbent)
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
            busier = read.rated_exposure_m > _allowance(reference)
            tried["lts4_m"] = round(read.lts4_m)
            tried["lts3_m"] = round(read.lts3_m)
            if not ctx.maxcalm:
                tried["score_gain_s"] = round(current.score(ctx) - read.score(ctx), 1)
            if busier:
                tried["outcome"] = "busier"
            elif more_lts4(read, list(reference_lts4), ctx):
                tried["outcome"] = "more_lts4"
            elif doubles_back(read, incumbent_retrace_m):
                tried["outcome"] = "doubles_back"
            elif room_m is not None and read.length_m - incumbent.length_m > room_m:
                tried["outcome"] = "too_long"
            elif better(read, current, ctx, rest_m):
                tried["outcome"] = "taken"
                kept, current = (read, candidate), read
                if pooled and ctx.options is not None:
                    ctx.options.append((candidate, read))
            else:
                tried["outcome"] = "not_better"
                if pooled and ctx.options is not None:
                    ctx.options.append((candidate, read))
        if out_of_time:
            seek["limited"] = "time"
            break
    return kept


def _allowance(exposure_m: float) -> float:
    """The most exposure a candidate may have against a reference's (the
    Traffic-wins guard: EXPOSURE_TOLERANCE and EXPOSURE_SLACK_M over it)."""
    return exposure_m * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M


def _busier(read: Analysis, first_exposure: float, ctx: Context) -> bool:
    """The Traffic-wins guard against the router's first route, with each pass through
    an Avoid-rated junction counted as exposure at its penalty's quiet metres
    (`Analysis.avoid_junction_m`), and each red junction at its own cost in quiet metres
    (`Analysis.red_m`), on both sides: a way round an Avoid junction is not "busier" for
    the LTS 3 it takes on in place of it (308: the route uses one only where there is no
    reasonable alternative), nor is a way round a red crossing. The owner, 2026-10-23, of
    an unsignalised crossing of Connecticut Ave at Decatur Ave, Kensington, at rush hour:
    "essentially impassable". The search excluded it and the router found the way by the
    Plyers Mill Rd signal (about 0.3 mi (0.5 km) longer, 0.2 mi (0.3 km) more LTS 3 and
    no red junction), which this guard refused for its LTS 3 alone. A red junction counts
    one for one, as an Avoid-rated one does: a metre of its cost is a metre of LTS 3, and
    buys half a metre of LTS 4 at the standard weights (LTS 4 weighs 2; 8 on a stress-averse
    ride), so the guard still refuses 0.6 mi (1 km) of LTS 4 for one 4,500 ft (1,372 m) red
    crossing. With no Avoid or red junction on either it is
    the plain guard. The guard's tolerance (`_allowance`) is on the exposure alone: the
    first route's junctions are added at their cost, not scaled up with it. The
    exposure is the rated metres' (`Analysis.rated_exposure_m`, 409): hill avoidance never
    makes a route busier (61), so leaving out a busy climb does not excuse more busy road."""
    return (
        read.rated_exposure_m + read.avoid_junction_m + read.red_m
        > _allowance(first_exposure) + ctx.first_avoid_m + ctx.first_red_m
    )


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
    # The route the wide search starts from, held fixed as the guards above hold
    # `first_exposure`: each point taken cannot raise the bar.
    start_retrace_m = retrace_m(best)
    locations = ctx.request.get("locations") or []

    def wide_request(lon: float, lat: float) -> dict:
        request = {
            k: v for k, v in ctx.request.items() if k not in ("alternates", "exclude_locations")
        }
        request["locations"] = [
            locations[0],
            {"lon": lon, "lat": lat, "type": "through"},
            locations[-1],
        ]
        return request

    round_deadline = routing.Deadline(
        stop_at, min(ctx.deadline.per_call_s, routing.ALTERNATES_TIMEOUT_S)
    )
    # The wide routes do not depend on each other: asked together, and their traces
    # after them, on the pool (v0.7.0, "Faster routing" step 3); each is then read in
    # turn below, as before. Nothing is started without the time for one round.
    asking = None
    if (
        parallel.enabled()
        and len(vias) > 1
        and len(locations) >= 2
        and stop_at - routing.clock() >= REFINE_ROUND_MIN_S
    ):
        asking = [
            parallel.submit(
                routing._call, ctx.variant, "route", wide_request(lon, lat), round_deadline
            )
            for lon, lat in vias
        ]
        answered = []
        for future in asking:
            try:
                answered.append(routing.await_future(future).get("trip") or {})
            except routing.PlanCancelled:
                # Cancelled while waiting (`core.plan_cancel`): the loop below gives way.
                break
            except Exception:  # noqa: BLE001 - read again, and handled, in the loop below
                continue
        routing.prefetch_traces(
            ctx.variant,
            ctx.costing,
            answered,
            routing.Deadline(stop_at, ctx.deadline.per_call_s),
            ctx.traces,
        )
    for number, (lon, lat) in enumerate(vias):
        if stop_at - routing.clock() < REFINE_ROUND_MIN_S or len(locations) < 2:
            info["limited"] = info["limited"] or "time"
            break
        asked += 1
        try:
            if asking is not None:
                answer = routing.await_future(asking[number])
            else:
                answer = routing._call(ctx.variant, "route", wide_request(lon, lat), round_deadline)
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
        busier = _busier(read, first_exposure, ctx)
        busier = busier or more_lts4(read, ctx.first_lts4, ctx) or too_long(read.length_m, ctx)
        busier = busier or doubles_back(read, start_retrace_m)
        if better(read, best, ctx) and not busier:
            best, best_trip = read, candidate
            taken += 1
    info["wide"] = {"asked": asked, "taken": taken > 0}
    return best, best_trip


def _halves(targets: list[Target]) -> list[list[Target]]:
    """The first and the second half of a list of targets, for a round whose
    whole set sent the route past the ceiling."""
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
        # A plan the rider has replaced (`core.plan_cancel`) ends here, between rounds,
        # rather than reading each round's routes only to find every call refused.
        routing.check_cancel(poll=False)
        # A crossing-only search past its first round is an answer as good as it was
        # with that round alone (before CROSSING_ONLY_ROUNDS was more than one): a later
        # round that cannot run or fails leaves `limited` unset, so the answer is cached
        # and says nothing.
        said = ctx.rate > 0 or number == 0
        new = crossing_targets(current, ctx)
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
            # A later crossing round the time does not reach, with a red still on the best
            # route, is said too, so the answer is not kept as if it were the search's
            # whole (the PC's check, 2026-10-23: a cold first plan stopped after two rounds
            # with both Kensington reds).
            if said or red_count(best):
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
        if ctx.ceiling_m is not None:
            # A set that sends the route past the ceiling is tried again with
            # less (each half of it).
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
                    _exclusion(t.point[0], t.point[1], ctx, t.radius) for t in asked
                ]
                try:
                    answer = routing._call(ctx.variant, "route", request, round_deadline)
                except routing.RouterRefused:
                    # Every way out is excluded: ask again with less.
                    continue
                candidate = answer.get("trip") or {}
                if candidate.get("legs"):
                    if too_long(_trip_m(candidate), ctx):
                        # Not read: it is past the ceiling, however calm.
                        over = True
                        candidate = None
                        continue
                    break
                candidate = None
            if candidate is None:
                # `ceiling`: the routes found were past the ceiling, which says
                # nothing of whether one is within the target (combined correctness
                # review, S2: it is not the no-fit answer's `target_distance`).
                if said:
                    info["limited"] = "ceiling" if over else "no_route"
                break
            current = analyse(candidate, ctx, routing.Deadline(stop_at, ctx.deadline.per_call_s))
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            if said:
                info["limited"] = "time"
            break
        excluded = asked
        info["excluded"] = len(excluded)
        if current is None:
            if said:
                info["limited"] = "untraceable"
            break
        info["rounds"] += 1
        busier = _busier(current, first_exposure, ctx)
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
            # A crossing-only round that was not better is often one that found the next
            # red crossing along the same road: the next round, excluding both, is the
            # one that can reach a signal, so the crossing rounds all run; so do the calm
            # rounds while the best route still has a red (the PC's check, 2026-10-23: at
            # 90 the search gave up two rounds in with a 16th St NW stop sign).
            if stale >= REFINE_PATIENCE and ctx.rate > 0 and not red_count(best):
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
    # A half step on the cautious side (461a): 2.5 is busy.
    return [(cautious_tier(cls) or 0) >= 3 for cls in analysis.classes]


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
    to fewer (LOOP_THINNING) to none, every one asked; the whole loop within the
    ceiling; the least stressful of those that share no more than LOOP_OVERLAP_OK of the
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
        if best is None or _loop_before(ranked, whole, best, ctx):
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


def _loop_before(ranked: tuple, whole: Analysis, best: tuple, ctx: Context) -> bool:
    """Whether a way back (`ranked`, `whole`) is to be kept over `best`'s: one that
    shares no more than LOOP_OVERLAP_OK before one that shares more; among those, at
    the top of the slider, `better` (the stress order with diminishing returns on the
    whole loop's distance, OWNER-DECISIONS 268 and 271), else the least stress by
    `Analysis.key`; among the others, the least shared."""
    if ranked[0] != best[0][0]:
        return ranked[0] < best[0][0]
    if not ranked[0] and ctx.maxcalm:
        return better(whole, best[2], ctx)
    return ranked < best[0]


def _pct(shared: float, back: float) -> float | None:
    return round(100.0 * shared / back, 1) if back > 0 else None


# --- Fewer repeats ------------------------------------------------------------------------
#
# The owner, 2026-10-18: "Put a slight penalty on repeats. For instance, I'd probably not do
# a mile on a LTS4 road to avoid it, but I perfer to not repeat in most cases." A leg that
# rides a way an earlier leg of the plan already rode (the loop's way back is `make_loop`'s;
# this is every leg's, a stop's too) is asked for again with points along its repeated
# stretch excluded, and the new leg is kept where it is no busier and the distance it adds is
# at most REPEAT_WEIGHT of the repeated metres it saves: a repeated metre counts as 1.5 of
# a fresh one, so a repeat of a mile is worth up to half a mile more of equally calm riding,
# and never a metre more of LTS 4, Avoid or a red junction, nor more LTS 3 or orange
# junctions than the second level's tie step (`MAXCALM_STEPS`). The search after it
# (`refine`, `refine_long`) does not price repeats, so a calmer route it finds may
# repeat. Not on a Mass Ride (its route keeps its own rules) and not near a leg's ends:
# the last REPEAT_STOP_M of a leg into a stop and the first of the leg out of it are how
# the rider reaches it.
REPEAT_WEIGHT = 0.5
# Below this many metres repeated on a leg nothing is asked.
REPEAT_MIN_M = 300.0
REPEAT_STOP_M = 100.0
# The exclusions' thinning at each ask, and the time the whole step may take (seconds).
REPEAT_THINNING = (1, 3)
REPEAT_BUDGET_S = 8.0


def repeated_by_leg(read: Analysis) -> list[float]:
    """Each leg's metres on a way an earlier leg rides, but for the first and last
    REPEAT_STOP_M of the leg."""
    bounds = leg_bounds(read)
    out = [0.0] * len(bounds)
    ridden: set[int] = set()
    along, leg = 0.0, 0
    mine: set[int] = set()
    for piece in read.pieces:
        middle = along + piece.metres / 2
        while leg < len(bounds) - 1 and middle >= bounds[leg][1]:
            ridden |= mine
            mine = set()
            leg += 1
        start, end = bounds[leg]
        if (
            piece.way_id
            and piece.way_id in ridden
            and start + REPEAT_STOP_M <= middle <= end - REPEAT_STOP_M
        ):
            out[leg] += piece.metres
        if piece.way_id:
            mine.add(piece.way_id)
        along += piece.metres
    return out


def repeat_charged_m(read: Analysis, ctx: Context) -> float:
    """`level3` with each repeated metre (`repeated_by_leg`) counted REPEAT_WEIGHT more."""
    return level3(read, ctx) + REPEAT_WEIGHT * sum(repeated_by_leg(read))


def fewer_repeats_better(read: Analysis, best: Analysis, ctx: Context) -> bool:
    """Whether `read` repeats less than `best` at a price the rider takes: not a metre
    more of LTS 4, Avoid or a red junction (`LTS4_SLACK_M`), no more LTS 3 than the
    tie step, no out-and-back of its own, and shorter once its repeats are charged."""
    if read.top_m > best.top_m + LTS4_SLACK_M or read.second_m > best.second_m + MAXCALM_STEPS[1]:
        return False
    if doubles_back(read, retrace_m(best)):
        # Out and back within a leg is a repeat too.
        return False
    return repeat_charged_m(read, ctx) < repeat_charged_m(best, ctx) - 1.0


def _repeat_points(read: Analysis, leg: int) -> list[tuple[float, float]]:
    """Points along `leg`'s repeated stretch, LOOP_SAMPLE_M apart, none within
    ENDPOINT_CLEARANCE_M of the leg's ends."""
    bounds = leg_bounds(read)
    start, end = bounds[leg]
    ridden: set[int] = set()
    along = 0.0
    for piece in read.pieces:
        if along + piece.metres / 2 >= start:
            break
        if piece.way_id:
            ridden.add(piece.way_id)
        along += piece.metres
    points: list[tuple[float, float]] = []
    along = 0.0
    for piece in read.pieces:
        middle = along + piece.metres / 2
        along += piece.metres
        if not start + ENDPOINT_CLEARANCE_M <= middle <= end - ENDPOINT_CLEARANCE_M:
            continue
        if piece.way_id not in ridden or piece.metres < CALM_MIN_EDGE_M:
            continue
        if points and haversine(Point(*points[-1]), Point(piece.lon, piece.lat)) < LOOP_SAMPLE_M:
            continue
        points.append((piece.lon, piece.lat))
    return points[:MAX_EXCLUDES]


def fewer_repeats(trip: dict, ctx: Context) -> tuple[dict, dict]:
    """The plan with each leg that repeats an earlier one's ways asked for again
    (`fewer_repeats_better`), first leg to last, within REPEAT_BUDGET_S. Returns (trip,
    info): `repeated_m` before and after, `tried` (routes asked for) and `changed` (legs
    replaced)."""
    info: dict = {"repeated_m": None, "was_m": None, "tried": 0, "changed": 0}
    legs = trip.get("legs") or []
    locations = ctx.request.get("locations") or []
    if ctx.group or len(legs) < 2 or len(locations) != len(legs) + 1:
        return trip, info
    try:
        best = analyse(trip, ctx, ctx.deadline)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        return trip, info
    if best is None or best.events is None:
        return trip, info
    info["was_m"] = info["repeated_m"] = round(sum(repeated_by_leg(best)), 1)
    stop_at = min(routing.clock() + REPEAT_BUDGET_S, ctx.deadline.at - REFINE_TRACE_RESERVE_S)
    # A loop's way back is `make_loop`'s, already asked for.
    last = len(legs) - 1 if ctx.loop_overlap is not None else len(legs)
    for leg in range(1, last):
        if repeated_by_leg(best)[leg] < REPEAT_MIN_M:
            continue
        points = _repeat_points(best, leg)
        if not points:
            continue
        for step in REPEAT_THINNING:
            if stop_at - routing.clock() < REFINE_ROUND_MIN_S:
                break
            info["tried"] += 1
            read, leg_trip = _through((), stop_at, ctx, points[::step], leg)
            if read == "time":
                break
            if read is None:
                continue
            joined = _splice(
                trip, leg, {"legs": leg_trip["legs"], "summary": leg_trip.get("summary") or {}}
            )
            if too_long(_trip_m(joined), ctx):
                continue
            whole = analyse(joined, ctx, routing.Deadline(stop_at, ctx.deadline.per_call_s))
            if whole is None or whole.events is None or loop_refused(whole, ctx):
                continue
            if fewer_repeats_better(whole, best, ctx):
                trip, best = joined, whole
                info["changed"] += 1
                break
    info["repeated_m"] = round(sum(repeated_by_leg(best)), 1)
    return trip, info


# The routes offered (OWNER-DECISIONS 265: "return up to 3-4 candidate routes, not one,
# so the rider can pick the one they like"). There is no score for scenery: the rider
# judges that from the map. A candidate must be within the ceiling (and, where the rider
# set a target, no further past it than the answer, OWNER-DECISIONS 271), pass the hold,
# and be no worse than the answer by more than these bands (a near-tie on stress, where
# the variety matters): the top figure by ALT_TOP_BAND_M (about 500 ft) and the second
# by ALT_SECOND_BAND_M (about 0.5 mi); OWNER-DECISIONS 287(4), "Loosen a bit
# (Recommended)", from 45 m and 300 m, so that more genuine alternates show, each with
# its stats. It must also be meaningfully different from
# every candidate already chosen: it shares less than ALT_OVERLAP of the shorter one's
# road by matched way length (OWNER-DECISIONS 269, "Loosen a little (Recommended)": 70%,
# from 60%), or differs from it by at least ALT_DIFFERENT_M of road (a different
# corridor over a stretch: 70% of a 58 mi route is never different).
ALT_MAX = 4
ALT_OVERLAP = 0.70
ALT_DIFFERENT_M = 8_000.0
ALT_TOP_BAND_M = 150.0
ALT_SECOND_BAND_M = 800.0


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


def over_answer(read: Analysis, answer: Analysis, ctx: Context) -> bool:
    """Whether a candidate goes further past the rider's target distance than the
    answer does (OWNER-DECISIONS 271: past the target only where it buys stress,
    which a near-tie with the answer does not)."""
    if ctx.target_m is None:
        return False
    return read.length_m > max(ctx.target_m, answer.length_m) + 0.5


def pick_candidates(pool: list, ctx: Context, reference: list[float]) -> list:
    """The answer and up to `ctx.alternates` - 1 others from `pool`, a list of
    (trip, reading) whose first is the answer: each within the ceiling (and no further
    past the rider's target than the answer, `over_answer`), the hold (against
    `reference`, the first route's top figure by leg), a near-tie with the answer on
    stress, and meaningfully different from those already chosen, in the order of
    `Analysis.key`."""
    if not pool:
        return []
    answer = pool[0]
    chosen = [answer]
    limit = max(ctx.alternates, 1)
    legs = len(answer[0].get("legs") or [])
    for trip, read in sorted(pool[1:], key=lambda o: o[1].key(ctx)):
        if len(chosen) >= limit:
            break
        if (
            # A whole route only: as many legs as the answer, so never one leg of
            # a loop or of a plan with stops (combined correctness review, B1).
            len(trip.get("legs") or []) != legs
            or read.events is None
            or too_long(read.length_m, ctx)
            or over_answer(read, answer[1], ctx)
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
# (a near-tie on stress, within the ceiling, the hold, meaningfully different). A
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


def _joined_passages(reads: list[Analysis], starts: list[float]) -> list:
    """The legs' Avoid-junction passes (307) as the whole route's, in metres along the
    whole. A junction within `MATCH_RADIUS_M` of a joint (a via point, or where a long
    plan cut its legs) is passed by the end of one leg and the start of the next; the
    whole route's line passes it once (`avoid_model.passages`), so it counts once here:
    the next leg's first pass is dropped where it is the same junction as the leg
    before's last pass and both are within `LEAVE_RADIUS_M` of the joint."""
    found: list = []
    for read, start in zip(reads, starts, strict=True):
        for p in read.avoid_passages:
            at = p.m + start
            last = found[-1] if found else None
            if (
                last is not None
                and last.junction.id == p.junction.id
                and last.m < start
                and start - last.m <= avoid_model.LEAVE_RADIUS_M
                and p.m <= avoid_model.LEAVE_RADIUS_M
            ):
                continue
            found.append(avoid_model.Passage(p.junction, at))
    return found


def combine(reads: list[Analysis]) -> Analysis:
    """The readings of a route's legs as the reading of the whole: the figures added,
    the pieces and junctions in order (a leg read without its junctions has none)."""
    via, along = [], 0.0
    for read in reads[:-1]:
        along += _road_m(read)
        via.append(along)
    passages = _joined_passages(reads, [0.0, *via])
    # Each pass costs the same quiet metres (`analyse`), so the whole's figure is the
    # passes counted once each times one pass's.
    unit_m = next(
        (r.avoid_junction_m / len(r.avoid_passages) for r in reads if r.avoid_passages), 0.0
    )
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
        avoid_m=sum(r.avoid_m for r in reads),
        lts45_m=sum(r.lts45_m for r in reads),
        lts2_m=sum(r.lts2_m for r in reads),
        lts2_weight=max((r.lts2_weight for r in reads), default=0.0),
        effort_m=sum(r.effort_m for r in reads),
        avoid_passages=passages,
        avoid_junction_m=unit_m * len(passages),
        router_climb_m=sum(r.router_climb_m for r in reads),
        hill_m=sum(r.hill_m for r in reads),
        hill=[f for r in reads for f in (r.hill or [1.0] * len(r.pieces))],
        flat_exposure_m=sum(
            r.exposure_m if r.flat_exposure_m is None else r.flat_exposure_m for r in reads
        ),
        rated_lts2_m=sum(r.lts2_m if r.rated_lts2_m is None else r.rated_lts2_m for r in reads),
        real_classes=(
            [c for r in reads for c in r.rated_classes]
            if any(r.real_classes is not None for r in reads)
            else None
        ),
        shift=max((r.shift for r in reads), default=0),
        junction_delay_s=sum(r.junction_delay_s for r in reads),
    )


# What a metre of each level of `Analysis.key` is worth when a long plan shares the
# detour out among its legs (`choose_options`): the levels in order of magnitude, so a
# metre of the top figure is worth a thousand of the second. This orders the upgrades;
# whether one is worth its miles at all is the diminishing-returns rule
# (`stress_weight_m`, `distance_charge_m`).
CHOICE_WEIGHTS = (1000.0, 1.0, 0.01)


def frontier(options: list, ctx: Context) -> list:
    """The options a leg offers, as a chain from the shortest to the longest in which
    each is `calmer` than the one before: the first route and every candidate calmer
    than it, with those no calmer than a shorter one left out. Each is (trip, reading).
    Whether an upgrade is worth its miles is the whole trip's to say (`choose_options`)."""
    first = options[0]
    valid = [first] + [o for o in options[1:] if calmer(o[1], first[1], ctx)]
    valid.sort(key=lambda o: o[1].length_m)
    chain = [valid[0]]
    for option in valid[1:]:
        if calmer(option[1], chain[-1][1], ctx):
            chain.append(option)
    return chain


def _benefit(a: Analysis, b: Analysis, ctx: Context) -> float:
    """What `b` gains over `a` in the order of `Analysis.key`, weighted by CHOICE_WEIGHTS."""
    return sum(w * (x - y) for w, x, y in zip(CHOICE_WEIGHTS, a.key(ctx), b.key(ctx), strict=True))


def choose_options(
    chains: list, firsts_m: list[float], ceiling_m: float | None, ctx: Context, fixed_m: float = 0.0
) -> list:
    """The index in each leg's chain to answer, so that the legs together are within
    `ceiling_m` (None: no limit) and as calm as the extra miles are worth. Each leg starts
    at its first route (or the shortest option that beats it, which costs nothing), and
    the metres of detour then go where they buy the most, by the benefit of each upgrade
    per metre it adds: the best leg's, then the next, until what is left buys nothing.
    An upgrade is taken only where the stress it saves pays for its miles at the whole
    trip's length (`distance_charge_m`, OWNER-DECISIONS 268 and 271). `fixed_m` is the
    length of the legs that offer no choice, which count against the limit."""
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
                if ceiling_m is not None and total + added > ceiling_m:
                    continue
                gain = _benefit(now, chain[k][1], ctx)
                if gain <= 0:
                    continue
                saved = stress_saved_m(now, chain[k][1], ctx)
                blended = charged_m(chain[k][1], ctx) - charged_m(now, ctx)
                charge = distance_charge_m(total, total + added, ctx, blended)
                if charge > 0.0 and saved < charge:
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
            first_tops[j] if first_tops[j] is not None else rated_lts4_m(reads[j])
            for j in range(len(reads))
        )
    ]
    ctx.candidate_reference = reference
    return pick_candidates(pool, ctx, reference)


def refine_long(trip: dict, ctx: Context) -> tuple[dict, dict]:
    """The search on a trip past the working span, leg by leg.

    The router's own route (`trip`) is read for its stress and cut into legs
    (`long_legs`); each leg's own route is asked for and read; the legs with
    busy road to avoid are searched one at a time, the worst first (LTS 4 and
    Avoid, then LTS 3), each with its share of the time left, by its weight, and
    the legs the time does not reach keep the router's route. Each leg's search may
    use all the detour the ceiling leaves the whole (it keeps every candidate it
    reads, with no price on distance of its own), and the detour is then shared out
    where it buys the most and is worth its miles for the whole trip
    (`choose_options`), so that the whole is never past the ceiling and no leg
    spends metres another could use better. The legs are put back
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
        info["lts4_before_m"] = round(rated_lts4_m(whole), 1)
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
    leg_requests = [{**base_request, "locations": [leg["a"], leg["b"]]} for leg in legs]
    route_deadline = routing.Deadline(
        hard_stop, min(ctx.deadline.per_call_s, routing.ALTERNATES_TIMEOUT_S)
    )
    # The legs' routes do not depend on each other: asked together on the pool, and
    # their traces after them up to the first leg that failed (v0.7.0, "Faster routing"
    # step 3); each is then read in leg order below, as before, its failure too.
    asking = None
    if parallel.enabled() and len(legs) > 1:
        asking = [
            parallel.submit(routing._call, ctx.variant, "route", request, route_deadline)
            for request in leg_requests
        ]
        answered = []
        for future in asking:
            try:
                answered.append(routing.await_future(future).get("trip") or {})
            except Exception:  # noqa: BLE001 - read again, and handled, in the loop below
                break
        routing.prefetch_traces(
            ctx.variant,
            ctx.costing,
            answered,
            routing.Deadline(hard_stop, ctx.deadline.per_call_s),
            ctx.traces,
        )
    try:
        for number, request in enumerate(leg_requests):
            try:
                if asking is not None:
                    answer = routing.await_future(asking[number])
                else:
                    answer = routing._call(ctx.variant, "route", request, route_deadline)
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
    finally:
        if asking is not None:
            # A leg that failed ends the search: the legs after it, not yet read, are not
            # asked for (those still queued on the pool are cancelled; one already running
            # ends at its own deadline, never waited for), so they do not hold the router's
            # slots after the plan has answered (audit R4).
            for future in asking[len(firsts) + 1 :]:
                future.cancel()
    results = list(firsts)
    finals = list(reads)
    infos: list[dict | None] = [None] * len(legs)
    caps: list[float | None] = [None] * len(legs)
    offered: list[list | None] = [None] * len(legs)
    first_tops: list[float | None] = [None] * len(legs)
    # The detour the ceiling leaves the whole, which each leg may use on its own.
    slack = 0.0
    if ctx.ceiling_m is not None:
        slack = max(ctx.ceiling_m - sum(_trip_m(t) for t in firsts), 0.0)
    # A leg's Avoid-rated junctions (307) count with its LTS 4, at their penalty's quiet
    # metres (`Analysis.avoid_junction_m`): a leg through one is searched, and first.
    weights = [LONG_LTS4_PRIORITY * (r.lts4_m + r.avoid_junction_m) + r.lts3_m for r in reads]
    order = sorted(
        (j for j in range(len(legs)) if weights[j] > 0),
        key=lambda j: (-(reads[j].lts4_m + reads[j].avoid_junction_m), -reads[j].lts3_m, j),
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
        if ctx.ceiling_m is not None:
            cap = _trip_m(firsts[j]) + slack
        sub = dataclasses.replace(
            ctx,
            request={**base_request, "locations": [legs[j]["a"], legs[j]["b"]]},
            points=[_point_of(legs[j]["a"]), _point_of(legs[j]["b"])],
            first_lts4=[],
            kept_excludes=[],
            ceiling_m=cap,
            target_m=None,
            worth_rule=False,
            options=[],
            alternates=0,
            # Not on a long plan's legs: each has only its share of the time, and the
            # router's alternatives roughly double a long leg's route
            # (`routing.SEEK_MAX_SPAN_M`'s measurements).
            rank_alternates=False,
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
    # The detour shared out among the legs that were searched.
    searched = [j for j in range(len(legs)) if offered[j]]
    chains = [frontier(offered[j], ctx) for j in searched]
    fixed_m = sum(_trip_m(firsts[j]) for j in range(len(legs)) if j not in searched)
    chosen = (
        choose_options(chains, [_trip_m(firsts[j]) for j in searched], ctx.ceiling_m, ctx, fixed_m)
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
    # together is not as calm as it (or is past the ceiling).
    # LTS 4 a leg took on to avoid a red junction (the hold allows it,
    # OWNER-DECISIONS 259) is not counted against the whole.
    traded = sum(max(0.0, f.lts4_m - r.lts4_m) for f, r in zip(finals, reads, strict=True))
    lts4 -= traded
    # The Avoid-rated junctions (307) count with the LTS 4, as they do in each leg's
    # weight: a leg that goes round one, on LTS 3, is not "worse" for it.
    # The legs' passes are counted as the whole route's (`combine`): a junction at a
    # joint, which both legs beside it pass, counts once, as it does in `whole`.
    top = lts4 + combine(finals).avoid_junction_m
    whole_top = whole.lts4_m + whole.avoid_junction_m
    worse = top > whole_top + MAXCALM_STEPS[0] or (
        top > whole_top - MAXCALM_STEPS[0] and lts3 > whole.lts3_m + MAXCALM_STEPS[1]
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
        # The hold's figure on the route kept, in rated metres (409).
        info["lts4_after_m"] = round(sum(rated_lts4_m(a) for a in finals), 1)
    # One reading of the whole route, which the answer reuses: the legs' traces
    # are remembered, the junctions read once across the joints. Inside the late
    # deadline, and not kept where the clock cut it short (S3): the answer then
    # reads the junctions itself, in its reserve.
    try:
        analyse(joined, ctx, late_deadline(ctx))
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        pass
    return joined, info
