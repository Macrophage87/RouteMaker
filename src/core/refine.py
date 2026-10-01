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

import logging
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
# longer than half of it, so each gets one.
CALM_SAMPLE_M = 40.0
# Never exclude within this far along the route of its start or its end, nor of
# a via point: the router must be able to leave and arrive, and the way out of a
# trailhead or a cul-de-sac is often the one busy road. (Measured on the live
# router: a Bethesda start whose only exit was an LTS 4 road 150 m long made
# every calm round "no route" at the 120 m this was first.)
ENDPOINT_CLEARANCE_M = 500.0
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


def quiet_cost_per_m(costing: dict) -> float:
    """The router's cost, in seconds, of a metre of quiet-street riding at this
    request's speed."""
    options = costing.get("bicycle") or {}
    kmh = options.get("cycling_speed") or presets.VALHALLA_DEFAULT_SPEED_KMH.get(
        options.get("bicycle_type", "Hybrid"), 18.0
    )
    return QUIET_COST_FACTOR * 3.6 / kmh


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
    offset = 0.0
    via_m: list[float] = []
    for number, leg in enumerate(legs):
        trace = routing._trace(ctx.variant, ctx.costing, leg.get("shape", ""), deadline, ctx.traces)
        if trace is None:
            return None
        made = routing.pieces_of_trace(trace)
        pieces.extend(made)
        raws.extend(
            trace_junctions.junctions_of_trace(
                trace, routing.decode_polyline6(leg.get("shape", "")), offset
            )
        )
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


def calm_targets(analysis: Analysis, ctx: Context, min_tier: int = 3) -> list[Target]:
    """Points along the route's stretches of LTS `min_tier` and worse, one to an
    edge."""
    kept: list[Target] = []
    total = analysis.length_m
    along = 0.0
    for piece, (tier, _kind) in zip(analysis.pieces, analysis.classes, strict=True):
        along += piece.metres
        if tier not in ("3", "4", "5") or int(tier) < min_tier:
            continue
        point = (piece.lon, piece.lat)
        if kept and haversine(Point(*kept[-1].point), Point(*point)) < CALM_SAMPLE_M:
            continue
        if _clear_of_ends(along, total, analysis.via_m):
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
    started = routing.clock()
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
    stop_at = min(started + REFINE_BUDGET_S, ctx.deadline.at - REFINE_TRACE_RESERVE_S)
    # The route the router gave is read inside the plan's own budget, exactly as
    # the answer would read it, and what it traced is remembered for the answer:
    # a trace that fails here is not asked for again (`routing._trace`). Only the
    # candidates are held to the search's shorter one.
    try:
        best = current = analyse(trip, ctx, ctx.deadline)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = "time"
        return trip, info
    if best is None:
        info["limited"] = "untraceable"
        return trip, info
    best_trip = trip
    info["original_m"] = round(best.length_m, 1)
    info["exposure_before_m"] = round(best.exposure_m, 1)
    best_score = best.score(ctx)
    rounds = REFINE_MAX_ROUNDS if ctx.rate > 0 else CROSSING_ONLY_ROUNDS
    excluded: list[Target] = []
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
        try:
            for asked in attempts:
                request = {k: v for k, v in ctx.request.items() if k != "alternates"}
                request["exclude_locations"] = [
                    {"lon": t.point[0], "lat": t.point[1]} for t in asked[:MAX_EXCLUDES]
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
        excluded = asked[:MAX_EXCLUDES]
        if current is None:
            info["limited"] = "untraceable"
            break
        info["rounds"] += 1
        score = current.score(ctx)
        if score < best_score - IMPROVEMENT_EPS_S:
            best, best_trip, best_score, stale = current, candidate, score, 0
        else:
            stale += 1
            if stale >= REFINE_PATIENCE:
                break
    info["excluded"] = len(excluded)
    info["extra_distance_m"] = round(best.length_m - (info["original_m"] or 0.0), 1)
    info["exposure_after_m"] = round(best.exposure_m, 1)
    return best_trip, info
