"""Avoid-rated junctions at plan time (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS 307-310, 335).

The approved list is read from `AvoidJunction` at request time, so a row an
instance admin approves changes the next plan: no rebuild, no restart.

How the 30-minute penalty (308) reaches routing. Valhalla prices an Avoid road
through the graph (its tier-5 ways are the graph's alleys and pay
`alley_penalty`, `presets.AVOID_ENTRY_PENALTY_S`, on entry), which a rebuild
writes. A junction has no such hook: the bicycle costing has no per-node charge a
request can set, and marking the nodes in the graph would need a rebuild for
every change to the list. So the penalty is applied on whole routes, in the
router's own unit (cost seconds), in two places that need no rebuild:

- The calm search (`core.refine`) adds `AVOID_JUNCTION_PENALTY_S` for each pass to
  a candidate's score (`Analysis.score`; at the top of the slider its quiet-metre
  equivalent joins the top figure, as an Avoid road's entry charge does in
  `routemaker.calm`), and its first rounds exclude the junction, so the search
  finds the way round and takes it wherever it is worth 30 minutes.
- Every plan, after the search or where it does not run (`settle`): where the
  answer still passes one, the router is asked once more with the junction
  excluded (`exclude_locations`, the junction's point with a radius of
  `MATCH_RADIUS_M`, which takes out every edge there). Where the search did not
  run, the way round replaces the answer when its cost is less than the answer's
  plus 30 minutes for each pass; on Mass Ride and Group Ride it replaces it
  whenever it exists (307: "exclude Avoid junctions where an alternative
  exists"). Otherwise the answer keeps the junction, says so first, and offers the
  way round as `avoid_alternate`, however much longer (335).

Where the search ran, its own guards ("Traffic wins": never a busier route, the
LTS 4 hold) stand: a way round they refused is offered, not imposed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from django.db import DatabaseError
from django.db.models import F
from django.utils import timezone

from routemaker import avoid_junctions as model
from routemaker.avoid_junctions import AvoidJunction, Passage

from .models import AvoidJunction as AvoidJunctionRow

logger = logging.getLogger(__name__)

# The rides that never take an Avoid junction where there is a way round (307).
GROUP_PRESETS = frozenset({"mass-ride", "group-ride"})
# The least time (seconds) left in the plan's budget to ask for the way round: one
# route call. Less than that and the answer keeps the junction and says so.
ALTERNATE_MIN_S = 4.0


def approved() -> tuple[AvoidJunction, ...]:
    """The approved Avoid junctions. Empty when there are none (as shipped) or when the
    table cannot be read: a plan is never refused for want of them."""
    try:
        rows = AvoidJunctionRow.objects.filter(approved=True).only(
            "id", "name", "reason", "location"
        )
        return tuple(
            AvoidJunction(row.id, row.name, row.reason, row.location.x, row.location.y)
            for row in rows
        )
    except DatabaseError:
        logger.warning("the Avoid junction list could not be read", exc_info=True)
        return ()


def trip_coordinates(trip: dict) -> list[tuple[float, float]]:
    """A trip's line, its legs joined, as (lon, lat)."""
    from .routing import decode_polyline6

    coordinates: list[tuple[float, float]] = []
    for leg in trip.get("legs") or []:
        shape = decode_polyline6(leg.get("shape", ""))
        coordinates.extend(shape[1:] if coordinates else shape)
    return coordinates


def passages_of(trip: dict, junctions: Sequence[AvoidJunction]) -> list[Passage]:
    """Each pass of a trip through an Avoid junction, in route order."""
    if not junctions:
        return []
    return model.passages(trip_coordinates(trip), junctions)


def exclusions(junctions: Sequence[AvoidJunction]) -> list[dict]:
    """The junctions as the router's `exclude_locations`: each point with a radius, so
    every edge at the junction is excluded, not only the nearest."""
    return [{"lon": j.lon, "lat": j.lat, "radius": int(model.MATCH_RADIUS_M)} for j in junctions]


def around_request(request: dict, junctions: Sequence[AvoidJunction]) -> dict:
    """The plan's request with the junctions excluded as well as whatever it excluded
    already, and without alternatives."""
    out = {k: v for k, v in request.items() if k != "alternates"}
    out["exclude_locations"] = list(request.get("exclude_locations") or []) + exclusions(junctions)
    return out


def record(found: Sequence[Passage]) -> None:
    """Count the plan on each junction its answer passes (335's admin view). A counter
    and a date only. A failure is logged and the plan answered all the same."""
    ids = sorted({p.junction.id for p in found})
    if not ids:
        return
    try:
        AvoidJunctionRow.objects.filter(id__in=ids).update(
            plans_through=F("plans_through") + 1, last_planned_through_at=timezone.now()
        )
    except DatabaseError:
        logger.warning("the Avoid junction counts could not be written", exc_info=True)


def _junctions_of(found: Sequence[Passage]) -> list[AvoidJunction]:
    seen: list[AvoidJunction] = []
    for passage in found:
        if passage.junction not in seen:
            seen.append(passage.junction)
    return seen


def settle(
    trip: dict,
    request: dict,
    variant: str,
    preset_name: str,
    deadline,
    junctions: Sequence[AvoidJunction],
    searched: bool,
) -> tuple[dict, dict | None, dict | None]:
    """The answer's trip, what was done about Avoid junctions (None: the route passes
    none), and the way round to offer (a trip, or None).

    `searched`: the calm search ran and weighed the penalty already (see the module's
    docstring)."""
    from . import routing

    found = passages_of(trip, junctions)
    if not found:
        return trip, None, None
    passed = _junctions_of(found)
    info: dict = {
        "passed": len(found),
        "penalty_s": int(model.penalty_s(found)),
        "decision": "kept",
        "alternate": None,
        "avoided": 0,
    }
    if deadline.at - routing.clock() < ALTERNATE_MIN_S:
        info["alternate"] = "time"
        return trip, info, None
    try:
        answer = routing._call(variant, "route", around_request(request, passed), deadline)
        around = answer.get("trip") or {}
    except routing.RouterRefused:
        around = {}
    except (routing.RouterUnavailable, routing.DeadlineExceeded):
        info["alternate"] = "time"
        return trip, info, None
    if not around.get("legs"):
        info["alternate"] = "no_route"
        return trip, info, None
    left = passages_of(around, junctions)
    if len(left) >= len(found):
        # The exclusion did not take it round (the junction's point is off the
        # graph's node, or there is no other way): nothing better to offer.
        info["alternate"] = "no_route"
        return trip, info, None
    info["alternate"] = "found"
    swap = False
    if preset_name in GROUP_PRESETS:
        swap = True
    elif not searched:
        swap = routing._router_cost(around) + model.penalty_s(left) < routing._router_cost(
            trip
        ) + model.penalty_s(found)
    if swap:
        info["decision"] = "avoided"
        info["avoided"] = len(found) - len(left)
        info["passed"] = len(left)
        info["penalty_s"] = int(model.penalty_s(left))
        info["alternate"] = None
        return around, info, None
    return trip, info, around


def rows(found: Sequence[Passage], scale: float = 1.0) -> list[dict]:
    """The answer's `avoid_junctions`: each pass, in route order."""
    return [
        {
            "id": p.junction.id,
            "name": p.junction.name,
            "reason": p.junction.reason,
            "lon": round(p.junction.lon, 6),
            "lat": round(p.junction.lat, 6),
            "m": round(p.m * scale),
            "label": model.label(p.junction),
        }
        for p in found
    ]
