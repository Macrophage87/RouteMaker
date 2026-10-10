"""Stops in any order (OWNER-DECISIONS 449): the order of a ride's stops that rides best.

The rider presses "Best order"; the page sends the ride as it would ask for a
route (`core.api.RouteIn`), and this answers the order to put the points in.
Nothing is planned here: the page reorders its points, which is an ordinary
edit it can undo, and asks for the route as it always does.

"Best" is the best any route is (the owner, 2026-10-10: "the same best as any
other route. It's adjusted by both traffic stress and elevation"): the order
whose legs cost least by the router's own cost, on the graph and with the
costing the ride itself would use: the riding time (in which a climb counts
through the router's grade-speed model) with the ride's stress penalties, and
below the hills slider's middle its hills penalty, priced in. Valhalla's
matrix (`sources_to_targets`) answers only times and distances, not that cost,
so the cost between each pair of points comes from the legs of ordinary
/route requests (`_leg_costs`), the same requests a plan makes, chained so
each leg is one pair the order may use.
They are the router's own route's costs, as a plan's route starts from;
what a plan then does to its legs (the calm search's re-ranking, and the hills
slider's weighing of long climbs among alternatives, which a ride with stops
does not get) runs only when the route is planned.

With more than `COST_MAX_STOPS` stops the pairs are too many to route one by
one inside the answer's time, and the order is by the matrix's riding times
along the same least-cost ways; a router that will not answer the legs falls
back to the matrix too, and one that answers neither (an older deployment
whose routers do not serve `sources_to_targets`, or one that is down) to
straight-line distance. The answer says which (`by`).
"""

from __future__ import annotations

import logging
import math

from routemaker import stoporder
from routemaker.geo import Point, haversine

from . import presets, routing

logger = logging.getLogger(__name__)

BY_ROUTE_COST = "route_cost"
BY_RIDING_TIME = "riding_time"
BY_STRAIGHT_LINE = "straight_line"

# The matrix gets this long at most, inside the request's budget: it is one
# call, far quicker than a route on the same points.
MATRIX_TIMEOUT_S = 20
ORDER_BUDGET_S = 25

# Up to this many stops the order is by the router's cost, from the legs of
# /route requests: k stops are k * (k + 1) pairs (from the start to each stop,
# between every two, and from each to the end), 110 at ten, asked as about
# k + 1 requests. Past it the matrix's riding times order them.
COST_MAX_STOPS = 10
# The legs get this long at most, leaving the matrix the rest of the budget.
COST_BUDGET_S = 12
# A /route request carries at most this many locations (the routers'
# service_limits.bicycle.max_locations, scripts/build_valhalla_configs.py).
ROUTE_MAX_LOCATIONS = 50
# ... and at most service_limits.bicycle.max_distance (500 km) of straight line
# between its locations in turn; this keeps well under it.
ROUTE_MAX_SPAN_M = 400_000

# Past this much straight line (the route API's CONFIRM_SPAN_M, 93 mi or 150 km),
# the order is by straight line and the router is not asked.
LONG_SPAN_M = 150_000


def free_stops(points: list, loop: bool) -> int:
    """How many of `points` the order may move: those between the start and the
    destination, or in a loop the rider chose, every point after the start."""
    if loop and not routing.is_round_trip(points):
        return max(0, len(points) - 1)
    return max(0, len(points) - 2)


def ride_graph(preset_name: str, dials: routing.Dials) -> tuple[str, dict]:
    """The router (variant) and costing the ride's own route would be asked on: the
    preset's and dials' stress, hills, time and assist, with /route's choice of a twin
    graph that is down or not promoted left to the standard one. Shared with
    `core.nearest`, whose riding distances are on the same graph."""
    preset = presets.PRESETS[preset_name]
    stress = (
        presets.stress_start(preset_name, dials.carrying) if dials.stress is None else dials.stress
    )
    hills = preset.hills if dials.hills is None else dials.hills
    when = dials.when or routing.default_when()
    assist = bool(dials.assist) and preset.assist_speed_kmh is not None
    variant = presets.variant_for_ride(preset_name, when, assist)
    if variant in routing.TWIN_VARIANTS and (
        routing._twin_down(variant) or not routing._is_promoted(variant)
    ):
        variant = routing.Variant.STANDARD.value
    costing = presets.costing(
        preset_name, stress, hills, assist=assist, avoid_gravel=bool(dials.avoid_gravel)
    )
    return variant, costing


def ask_matrix(variant: str, payload: dict, deadline) -> dict:
    """One matrix call, with /route's handling of a twin graph (`_ask`). Shared with
    `core.nearest`. Raises RouterUnavailable, RouterRefused or DeadlineExceeded."""
    answer, _ = _ask(variant, "sources_to_targets", payload, deadline)
    return answer


def _ask(variant: str, endpoint: str, payload: dict, deadline) -> tuple[dict, str]:
    """One router call, and the graph that answered it, with /route's handling of a
    twin graph (`routing.plan`): a weekend or off-road router gets at most
    `routing.WEEKEND_TIMEOUT_S`, and one that does not answer, or has no tiles
    (170/171), leaves the standard graph to answer and is remembered as down.
    Raises RouterUnavailable, RouterRefused or DeadlineExceeded."""
    if variant not in routing.TWIN_VARIANTS:
        return routing._call(variant, endpoint, payload, deadline), variant
    standard = routing.Variant.STANDARD.value
    twin = routing.Deadline(deadline.at, min(deadline.per_call_s, routing.WEEKEND_TIMEOUT_S))
    try:
        answer = routing._call(variant, endpoint, payload, twin)
    except routing.RouterUnavailable:
        routing._mark_twin(variant, False)
        return routing._call(standard, endpoint, payload, deadline), standard
    except routing.RouterRefused as refusal:
        if refusal.code not in routing.NO_EDGE_CODES:
            raise
        answer = routing._call(standard, endpoint, payload, deadline)
        routing._mark_twin(variant, False)
        return answer, standard
    routing._mark_twin(variant, True)
    return answer, variant


def _pairs_chains(n: int) -> list[list[int]]:
    """Chains of point indices whose consecutive pairs are every leg an order of
    points 0..n-1 (the ends fixed) may ride, each once: one walk from the start
    through every stop-to-stop pair (an Euler circuit of the stops, every two
    joined both ways) to the end, and a start-stop-end chain for each other stop."""
    stops = list(range(1, n - 1))
    if not stops:
        return [[0, n - 1]]
    # Hierholzer's walk over the complete directed graph of the stops.
    unused = {s: [t for t in reversed(stops) if t != s] for s in stops}
    walk, stack = [], [stops[0]]
    while stack:
        here = stack[-1]
        if unused[here]:
            stack.append(unused[here].pop())
        else:
            walk.append(stack.pop())
    walk.reverse()
    return [[0, *walk, n - 1]] + [[0, s, n - 1] for s in stops[1:]]


def _requests_of(chain: list[int], points: list) -> list[list[int]]:
    """A chain split into /route requests, each starting where the last ended, of
    at most ROUTE_MAX_LOCATIONS locations and ROUTE_MAX_SPAN_M of straight line
    between them in turn (the routers refuse a request past either)."""
    requests, current, span = [], [chain[0]], 0.0
    for nxt in chain[1:]:
        step = haversine(Point(*points[current[-1]]), Point(*points[nxt]))
        if len(current) >= ROUTE_MAX_LOCATIONS or (
            len(current) > 1 and span + step > ROUTE_MAX_SPAN_M
        ):
            requests.append(current)
            current, span = [current[-1]], 0.0
        current.append(nxt)
        span += step
    requests.append(current)
    return requests


def _leg_costs(
    variant: str, request_points: list, costing: dict, when: str, deadline
) -> tuple[tuple[list, list, list] | None, str]:
    """The router's cost, riding time (seconds) and length (metres) of the route
    between every pair of points an order may ride, from the legs of /route
    requests as a plan asks them, or None if the router would not give them all
    (a pair it cannot join refuses its whole request, and the matrix, which can
    say so pair by pair, takes over); and the graph the matrix should ask next.

    Every cost is from one graph: a weekend or off-road router that stops
    answering part way leaves the standard graph to answer them all again. One
    still silent when the legs' time runs out is not remembered as down (it had
    less than its own limit), but the matrix asks the standard graph. Only the
    variant and the router's error are logged, never the points."""
    n = len(request_points)
    cost = [[None] * n for _ in range(n)]
    times = [[None] * n for _ in range(n)]
    metres = [[None] * n for _ in range(n)]
    asked, filled = variant, False
    for chain in _pairs_chains(n):
        for indices in _requests_of(chain, request_points):
            payload = {
                "locations": [
                    {"lon": request_points[i][0], "lat": request_points[i][1], "type": "break"}
                    for i in indices
                ],
                "costing": "bicycle",
                "costing_options": costing,
                "date_time": {"type": 3, "value": routing.planning_time(when=when)},
                "directions_type": "none",
                "units": "kilometers",
            }
            try:
                answer, answered = _ask(variant, "route", payload, deadline)
            except routing.DeadlineExceeded as error:
                logger.warning("the %s router gave no leg costs: %s", variant, error)
                return None, routing.Variant.STANDARD.value
            except (routing.RouterUnavailable, routing.RouterRefused) as error:
                logger.warning("the %s router gave no leg costs: %s", variant, error)
                return None, variant
            if answered != variant:
                if filled and variant == asked and asked in routing.TWIN_VARIANTS:
                    # The twin went down part way: ask the standard graph for every leg.
                    return _leg_costs(answered, request_points, costing, when, deadline)
                variant = answered
            legs = (answer.get("trip") or {}).get("legs")
            if not isinstance(legs, list) or len(legs) != len(indices) - 1:
                logger.warning("the %s router's legs had the wrong shape", variant)
                return None, variant
            for a, b, leg in zip(indices, indices[1:], legs, strict=False):
                summary = leg.get("summary") if isinstance(leg, dict) else None
                values = [(summary or {}).get(key) for key in ("cost", "time", "length")]
                if not all(isinstance(v, int | float) for v in values):
                    # An older router without a leg's cost: the matrix orders by time.
                    logger.warning("the %s router's legs carried no cost", variant)
                    return None, variant
                filled = True
                cost[a][b], times[a][b], metres[a][b] = (
                    float(values[0]),
                    float(values[1]),
                    float(values[2]) * 1000.0,
                )
    return (cost, times, metres), variant


def _matrix(variant: str, request_points: list, costing: dict, deadline) -> list | None:
    """The riding times (seconds) and distances (metres) between every pair, or
    None if the router would not give them. Only the variant and the router's
    error are logged, never the points."""
    locations = [{"lon": lon, "lat": lat} for lon, lat in request_points]
    payload = {
        "sources": locations,
        "targets": locations,
        "costing": "bicycle",
        "costing_options": costing,
        "units": "kilometers",
    }
    try:
        answer, _ = _ask(variant, "sources_to_targets", payload, deadline)
    except (routing.RouterUnavailable, routing.RouterRefused, routing.DeadlineExceeded) as error:
        # Out of time too: the straight-line order needs no router, so it is still answered.
        logger.warning("the %s router gave no riding-time matrix: %s", variant, error)
        return None
    rows = answer.get("sources_to_targets")
    n = len(request_points)
    if not isinstance(rows, list) or len(rows) != n:
        logger.warning("the %s router's matrix had the wrong shape", variant)
        return None
    times, metres = [], []
    for row in rows:
        if not isinstance(row, list) or len(row) != n:
            logger.warning("the %s router's matrix had the wrong shape", variant)
            return None
        times.append([cell.get("time") if isinstance(cell, dict) else None for cell in row])
        metres.append(
            [
                cell["distance"] * 1000.0
                if isinstance(cell, dict) and isinstance(cell.get("distance"), int | float)
                else None
                for cell in row
            ]
        )
    return [times, metres]


def _straight(request_points: list) -> list[list[float]]:
    return [[haversine(Point(*a), Point(*b)) for b in request_points] for a in request_points]


def order(points: list, preset_name: str, dials: routing.Dials, started: float | None = None):
    """The best order for `points` on `preset_name` with `dials`, as the API's body.

    `order` lists the indices of the rider's points in the new order, every
    point once, the start first and (but in a loop the rider chose) the
    destination last; `changed` says whether that is a new order. `by` is what
    chose it: the router's cost (`route_cost`, what any route is chosen by), its
    riding times (`riding_time`, past COST_MAX_STOPS or when it gave no leg
    costs), straight-line distance when it gave neither, or None when there was
    nothing to choose (fewer than two stops).
    `before_s`/`after_s` are the riding times of the rider's order and the new
    one, and `before_m`/`after_m` their lengths (along the router's routes, or
    in straight lines), None where unknown or where a leg could not be joined.
    """
    if started is None:
        started = routing.clock()
    deadline = routing.Deadline(
        started + ORDER_BUDGET_S - routing.ANSWER_RESERVE_S, MATRIX_TIMEOUT_S
    )
    # Whether the ride is a loop, and whether it already ends on its start, is read
    # from the rider's own points, as the page reads it (`fitsOrder`); the router is
    # asked about the points it would route, a Zoo point moved to the racks.
    moved, _ = routing.move_zoo_points(points)
    loop = routing.loop_wanted(points, dials.loop, preset_name)
    appended = loop and not routing.is_round_trip(points)
    request_points = [*moved, moved[0]] if appended else moved
    if free_stops(points, loop) < 2:
        # Nothing to choose: the start and destination are fixed.
        return {
            "order": list(range(len(points))),
            "changed": False,
            "exact": True,
            "by": None,
            "before_s": None,
            "after_s": None,
            "before_m": None,
            "after_m": None,
        }

    variant, costing = ride_graph(preset_name, dials)
    when = dials.when or routing.default_when()

    # A long ride is ordered by straight line without asking the router: a matrix
    # of 26 points over that span holds a router's workers well past the answer's
    # time limit, and a long /route is limited to one at a time for that reason.
    long_ride = routing.straight_span_m(request_points) > LONG_SPAN_M
    legs = None
    if not long_ride and len(request_points) - 2 <= COST_MAX_STOPS:
        legs_by = routing.Deadline(min(deadline.at, started + COST_BUDGET_S), deadline.per_call_s)
        legs, variant = _leg_costs(variant, request_points, costing, when, legs_by)
    if legs is not None:
        cost, times, metres = legs
        chosen = stoporder.best_order(cost)
        own = list(range(len(request_points)))
        body = {
            "by": BY_ROUTE_COST,
            "before_s": _finite(stoporder.total(times, own)),
            "after_s": _finite(stoporder.total(times, chosen.order)),
            "before_m": _finite(stoporder.total(metres, own)),
            "after_m": _finite(stoporder.total(metres, chosen.order)),
        }
        new = chosen.order[:-1] if appended else chosen.order
        return {"order": new, "changed": chosen.changed, "exact": chosen.exact} | body
    matrix = None if long_ride else _matrix(variant, request_points, costing, deadline)
    if matrix is not None:
        times, metres = matrix
        chosen = stoporder.best_order(times)
        body = {
            "by": BY_RIDING_TIME,
            "before_s": _finite(chosen.before),
            "after_s": _finite(chosen.after),
            "before_m": _finite(stoporder.total(metres, list(range(len(request_points))))),
            "after_m": _finite(stoporder.total(metres, chosen.order)),
        }
    else:
        chosen = stoporder.best_order(_straight(request_points))
        body = {
            "by": BY_STRAIGHT_LINE,
            "before_s": None,
            "after_s": None,
            "before_m": _finite(chosen.before),
            "after_m": _finite(chosen.after),
        }
    new = chosen.order[:-1] if appended else chosen.order
    return {"order": new, "changed": chosen.changed, "exact": chosen.exact} | body


def _finite(value: float | None) -> int | None:
    if value is None or value == math.inf:
        return None
    return round(value)
