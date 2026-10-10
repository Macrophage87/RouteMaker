"""The nearest water, restroom or Metro station by bike: how far each of a few places is.

The rider asks the planner for the nearest public water, restroom or Metro station
(owner, 2026-10-10: "Have the option to route to the nearest public water source,
restroom, or metro stop. Let people choose the three closest."). The page knows the
places (the water and restrooms layer and the Metro stations it already bundles),
picks the few nearest in straight lines, and sends them here with the ride's own
preset and dials; this answers how far each is to ride, so the page can offer the
three nearest by bike rather than as the crow flies. Nothing is planned here: the
rider picks one and the page plans the route as after any edit.

The distances are the router's own (Valhalla's `sources_to_targets`, one row: from
the rider to each place) on the graph and with the costing the ride's route would
use (`stoporder.ride_graph`), so a calm ride's distances are along the calm ways it
would take. A router that does not answer the matrix does not stop the answer: it
falls back to straight-line distance, and says so (`by`), as Best order does.

Only the variant and the router's error are logged, never the points: the rider's
position is a route request's, kept no longer (OWNER-DECISIONS 395).
"""

from __future__ import annotations

import logging

from routemaker.geo import Point, haversine

from . import routing, stoporder

logger = logging.getLogger(__name__)

BY_RIDING = "riding"
BY_STRAIGHT_LINE = "straight_line"

# At most this many places a request: the page sends the nearest few in straight
# lines (`NEAREST_CANDIDATES` in frontend/src/lib/nearest.ts) and keeps the best
# three by bike. One row of ten is far under the routers' `max_matrix_location_pairs`.
MAX_PLACES = 10

# The same budget as Best order's (`stoporder`): one matrix call, quicker than a route.
MATRIX_TIMEOUT_S = stoporder.MATRIX_TIMEOUT_S
NEAREST_BUDGET_S = stoporder.ORDER_BUDGET_S

# A place further than this in a straight line (Best order's long-ride line, 93 mi
# or 150 km) is not asked of the router: the answer is by straight line, as Best
# order's is for a ride that long.
LONG_SPAN_M = stoporder.LONG_SPAN_M


def _row(variant: str, origin: list, places: list, costing: dict, deadline) -> list | None:
    """(seconds, metres) from `origin` to each place, None for a place the router
    could not reach; None for the whole row if the router gave no matrix."""
    payload = {
        "sources": [{"lon": origin[0], "lat": origin[1]}],
        "targets": [{"lon": lon, "lat": lat} for lon, lat in places],
        "costing": "bicycle",
        "costing_options": costing,
        "units": "kilometers",
    }
    try:
        answer = stoporder.ask_matrix(variant, payload, deadline)
    except (routing.RouterUnavailable, routing.RouterRefused, routing.DeadlineExceeded) as error:
        logger.warning("the %s router gave no distances to the nearest places: %s", variant, error)
        return None
    rows = answer.get("sources_to_targets")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], list):
        logger.warning("the %s router's distances had the wrong shape", variant)
        return None
    row = rows[0]
    if len(row) != len(places):
        logger.warning("the %s router's distances had the wrong shape", variant)
        return None
    out = []
    for cell in row:
        time = cell.get("time") if isinstance(cell, dict) else None
        km = cell.get("distance") if isinstance(cell, dict) else None
        if isinstance(time, int | float) and isinstance(km, int | float):
            out.append((round(time), round(km * 1000)))
        else:
            out.append(None)
    return out


def distances(points: list, preset_name: str, dials: routing.Dials, started: float | None = None):
    """How far each place is from the rider, as the API's body.

    `points` is the rider's position first, then the places. `places` has one entry
    per place, in the order sent: `distance_m` and `time_s` by bike on the ride's
    own graph and settings, or both None where the router found no way there; by
    straight line, `distance_m` is the straight line and `time_s` is None.
    """
    if started is None:
        started = routing.clock()
    deadline = routing.Deadline(
        started + NEAREST_BUDGET_S - routing.ANSWER_RESERVE_S, MATRIX_TIMEOUT_S
    )
    moved, _ = routing.move_zoo_points(points)
    origin, places = moved[0], moved[1:]
    straight = [round(haversine(Point(*origin), Point(*place))) for place in places]
    row = None
    if max(straight) <= LONG_SPAN_M:
        variant, costing = stoporder.ride_graph(preset_name, dials)
        row = _row(variant, origin, places, costing, deadline)
    if row is not None and all(cell is None for cell in row):
        # No place reachable at all: the rider is most likely on a piece of the graph
        # the router cannot leave (a snap to an island). Straight lines still offer
        # something to ride towards, and the page says how they were measured.
        logger.warning("the router reached none of the nearest places")
        row = None
    if row is None:
        return {
            "by": BY_STRAIGHT_LINE,
            "places": [{"distance_m": m, "time_s": None} for m in straight],
        }
    return {
        "by": BY_RIDING,
        "places": [
            {"distance_m": None, "time_s": None}
            if cell is None
            else {"distance_m": cell[1], "time_s": cell[0]}
            for cell in row
        ],
    }
