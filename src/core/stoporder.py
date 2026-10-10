"""Stops in any order (OWNER-DECISIONS 449): the order of a ride's stops that rides least.

The rider presses "Best order"; the page sends the ride as it would ask for a
route (`core.api.RouteIn`), and this answers the order to put the points in.
Nothing is planned here: the page reorders its points, which is an ordinary
edit it can undo, and asks for the route as it always does.

The costs are the router's riding times between every pair of points
(Valhalla's `sources_to_targets`) on the graph and with the costing the ride
itself would use, so a calm ride's times are along the calm ways it would take.
They are the router's own route's times, not the calm search's or the hills
slider's choice among alternatives, which run only when the route is planned;
the order is the best for the router's route between each pair, which is what
the rider's route is built from.

A router that does not answer the matrix (an older deployment whose routers do
not serve `sources_to_targets`, or one that is down) does not stop the order:
it falls back to straight-line distance between the points, and the answer
says so (`by`).
"""

from __future__ import annotations

import logging
import math

from routemaker import stoporder
from routemaker.geo import Point, haversine

from . import presets, routing

logger = logging.getLogger(__name__)

BY_RIDING_TIME = "riding_time"
BY_STRAIGHT_LINE = "straight_line"

# The matrix gets this long at most, inside the request's budget: it is one
# call, far quicker than a route on the same points.
MATRIX_TIMEOUT_S = 20
ORDER_BUDGET_S = 25


def free_stops(points: list, loop: bool) -> int:
    """How many of `points` the order may move: those between the start and the
    destination, or in a loop the rider chose, every point after the start."""
    if loop and not routing.is_round_trip(points):
        return max(0, len(points) - 1)
    return max(0, len(points) - 2)


def _matrix(variant: str, request_points: list, costing: dict, deadline) -> list | None:
    """The riding times (seconds) and distances (metres) between every pair, or
    None if the router would not give them."""
    locations = [{"lon": lon, "lat": lat} for lon, lat in request_points]
    payload = {
        "sources": locations,
        "targets": locations,
        "costing": "bicycle",
        "costing_options": costing,
        "units": "kilometers",
    }
    try:
        answer = routing._call(variant, "sources_to_targets", payload, deadline)
    except (routing.RouterUnavailable, routing.RouterRefused) as error:
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
    chose it: the router's riding times, straight-line distance when the router
    gave none, or None when there was nothing to choose (fewer than two stops).
    `before_s`/`after_s` are the riding times of the rider's order and the new
    one, and `before_m`/`after_m` their lengths (along the router's routes, or
    in straight lines), None where unknown or where a leg could not be joined.
    """
    if started is None:
        started = routing.clock()
    deadline = routing.Deadline(
        started + ORDER_BUDGET_S - routing.ANSWER_RESERVE_S, MATRIX_TIMEOUT_S
    )
    moved, _ = routing.move_zoo_points(points)
    loop = routing.loop_wanted(moved, dials.loop, preset_name)
    request_points = routing.loop_points(moved, loop)
    appended = len(request_points) > len(points)
    if free_stops(moved, loop) < 2:
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

    matrix = _matrix(variant, request_points, costing, deadline)
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
