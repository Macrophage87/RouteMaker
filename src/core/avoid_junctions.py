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
  `MATCH_RADIUS_M`, which takes out every edge there): one /route call. Where the
  search did not run (or stopped before a round: `searched` is what it did, not
  what was asked), the way round replaces the answer where the search's own reading
  prefers it (`judged_takes`: no more red crossings, no busier by the Traffic-wins
  guard, and a lower score, which prices the junctions' stress, each red and the 30
  minutes a pass; the router's cost alone priced none of the junction stress and so
  brought back the red crossing the red pass had gone round, the 2026-11-08 hunt, S3
  and P2), and its request keeps out what the passes before it did
  (`Context.red_excludes`, `Context.level_excludes`). A pass is read from the traces,
  so a bridge over or a tunnel under a junction is none (J6). On Mass Ride and Group
  Ride (307:
  "exclude Avoid junctions where an alternative exists") it replaces it when it
  takes on no LTS 4 (or Avoid road) the answer did not have and is at most
  `GROUP_EXTRA_MAX_M` (1 mi (1.6 km)) or `GROUP_EXTRA_SHARE` (25%) of the answer
  longer, whichever is more: a default open for the owner (the review of 351e65b),
  which reads both routes' stress (one trace a leg of each, remembered). A loop
  never swaps: its way back was made by a different way (`refine.make_loop`) and
  the way round is a plain route through the same points, so it is offered.
  Otherwise the answer keeps the junction, says so first, and offers the way round
  as `avoid_alternate`, however much longer (335), which the plan then answers in
  full: one trace a leg. So a plan through an Avoid junction costs 1 /route call
  plus a trace for each leg of the way round (and, on Mass Ride and Group Ride, a
  trace for each leg of the answer, where not already remembered).

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
# How much longer a way round may be for Mass Ride and Group Ride to take it in place
# of the answer: this much, or this share of the answer, whichever is more; and it may
# take on no LTS 4 (or Avoid road) beyond the answer's, past `GROUP_LTS4_SLACK_M` (the
# traces' rounding). A default the coordinator picked for the owner to confirm (the
# review of 351e65b); a way round outside it is offered beside the notice instead.
GROUP_EXTRA_MAX_M = 1609.344
GROUP_EXTRA_SHARE = 0.25
GROUP_LTS4_SLACK_M = 1.0
# The router's own limit on `exclude_locations` (`valhalla/*.json`).
MAX_EXCLUDES = 200


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


def graded_line(
    legs: Sequence[tuple[dict | None, list]], raws: Sequence = ()
) -> tuple[list, list[bool] | None, list]:
    """A route's line from its legs' traces, with each segment's grade separation and the
    route's own junction nodes, for `model.passages` (J6): (line, separated, nodes). `legs`
    are (trace or None, the leg's decoded shape) in order; a leg with no trace is its shape,
    at grade. `raws`: the route's junctions as read from the same traces
    (`trace_junctions.RawJunction`); those with a road crossing them are its nodes."""
    from routemaker import trace_junctions

    line: list = []
    flags: list[bool] = []
    known = False
    for trace, shape in legs:
        if trace is not None:
            here, separated = trace_junctions.separated_line(trace, shape)
        else:
            here, separated = list(shape), None
        if separated is None:
            separated = [False] * max(len(here) - 1, 0)
        else:
            known = True
        if line and here:
            here = here[1:]
        elif line:
            continue
        line.extend(here)
        flags.extend(separated)
    nodes = [(r.lon, r.lat) for r in raws if getattr(r, "has_cross_roads", False)]
    if not known or len(flags) != max(len(line) - 1, 0):
        return line, None, nodes
    return line, flags, nodes


def passages_of(
    trip: dict, junctions: Sequence[AvoidJunction], ctx=None, deadline=None
) -> list[Passage]:
    """Each pass of a trip through an Avoid junction, in route order. With the plan's
    `refine.Context` its legs are read from their traces (remembered in `ctx.traces`), so
    a route over or under a junction on a bridge or in a tunnel is not a pass (J6); where
    a leg cannot be traced its line is read as at grade."""
    if not junctions:
        return []
    if getattr(ctx, "traces", None) is None:
        return model.passages(trip_coordinates(trip), junctions)
    from routemaker import trace_junctions

    from . import routing

    legs: list[tuple[dict | None, list]] = []
    raws: list = []
    for leg in trip.get("legs") or []:
        shape = routing.decode_polyline6(leg.get("shape", ""))
        try:
            trace = routing._trace(
                ctx.variant, ctx.costing, leg.get("shape", ""), deadline or ctx.deadline,
                ctx.traces,
            )  # fmt: skip
        except (routing.DeadlineExceeded, routing.RouterUnavailable, routing.RouterRefused):
            trace = None
        legs.append((trace, shape))
        if trace is not None:
            raws.extend(trace_junctions.junctions_of_trace(trace, shape))
    line, separated, nodes = graded_line(legs, raws)
    return model.passages(line, junctions, separated=separated, nodes=nodes)


def exclusions(junctions: Sequence[AvoidJunction]) -> list[dict]:
    """The junctions as the router's `exclude_locations`: each point with a radius, so
    every edge at the junction is excluded, not only the nearest."""
    return [{"lon": j.lon, "lat": j.lat, "radius": int(model.MATCH_RADIUS_M)} for j in junctions]


def around_request(request: dict, junctions: Sequence[AvoidJunction], ctx=None) -> dict:
    """The plan's request with the junctions excluded as well as whatever it excluded
    already, and without alternatives. With the plan's `refine.Context`, also what the
    passes before this one kept out (`Context.level_excludes`: Mountain Bike's trails
    above the rider's level; `Context.red_excludes`: the red crossings the red pass went
    round), so the way round never brings back a red crossing the red pass took out (the
    2026-11-08 hunt, P2)."""
    out = {k: v for k, v in request.items() if k != "alternates"}
    kept = list(request.get("exclude_locations") or [])
    if ctx is not None:
        kept += list(getattr(ctx, "level_excludes", None) or [])
        kept += list(getattr(ctx, "red_excludes", None) or [])
    # The router's limit on exclusions is 200: the junctions themselves always go in.
    mine = exclusions(junctions)
    out["exclude_locations"] = kept[: max(0, MAX_EXCLUDES - len(mine))] + mine
    return out


def judged_takes(trip: dict, around: dict, ctx, deadline) -> bool | None:
    """Whether the way round replaces the answer where the search did not weigh it, read
    as the search reads a route (`refine.analyse`): never with more red crossings than the
    answer (`refine.red_count`, which counts a capped trail crossing at its cost), never
    busier by the Traffic-wins guard (its LTS 3, 4 and Avoid exposure and its red and Avoid
    junction cost), and only where its score (`Analysis.score`: the router's cost plus the
    junctions' stress and the 30 minutes a pass) is the lower. The
    router's cost alone, as before, prices no junction stress, and the red pass's route is
    dearer by it by construction, so a way round back through the red it avoided won almost
    every time (the 2026-11-08 hunt, S3 and P2). None where either cannot be read."""
    from . import refine, routing

    try:
        before = refine.analyse(trip, ctx, deadline)
        after = refine.analyse(around, ctx, deadline)
    except (routing.DeadlineExceeded, routing.RouterUnavailable, routing.RouterRefused):
        return None
    if before is None or after is None or before.events is None or after.events is None:
        return None
    if refine.red_count(after) > refine.red_count(before):
        return False
    busier = (
        after.rated_exposure_m + after.avoid_junction_m + after.red_m
        > refine._allowance(before.rated_exposure_m) + before.avoid_junction_m + before.red_m
    )
    if busier:
        return False
    return after.score(ctx) < before.score(ctx)


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


def group_takes(trip: dict, around: dict, ctx, deadline) -> bool:
    """Whether Mass Ride or Group Ride takes the way round in place of the answer: no
    LTS 4 (or Avoid road) beyond the answer's, and no more than GROUP_EXTRA_MAX_M or
    GROUP_EXTRA_SHARE longer, whichever is more. Where either route's stress cannot be
    read (no context, no time, untraceable) it does not: the way round is offered."""
    from . import refine, routing

    length = routing._trip_length_m(trip)
    extra = routing._trip_length_m(around) - length
    if extra > max(GROUP_EXTRA_MAX_M, GROUP_EXTRA_SHARE * length):
        return False
    if ctx is None:
        return False
    try:
        before = refine.analyse(trip, ctx, deadline, with_events=False)
        after = refine.analyse(around, ctx, deadline, with_events=False)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        return False
    if before is None or after is None:
        return False
    # The rated LTS 4 metres, as the LTS 4 hold reads them (409): not hill-weighted.
    return refine.rated_lts4_m(after) <= refine.rated_lts4_m(before) + GROUP_LTS4_SLACK_M


def settle(
    trip: dict,
    request: dict,
    variant: str,
    preset_name: str,
    deadline,
    junctions: Sequence[AvoidJunction],
    searched: bool,
    ctx=None,
    loop: bool = False,
) -> tuple[dict, dict | None, dict | None]:
    """The answer's trip, what was done about Avoid junctions (None: the route passes
    none), and the way round to offer (a trip, or None).

    `searched`: the calm search ran at least one round and was not cut short, so it
    weighed the penalty already (see the module's docstring). `ctx`: the plan's
    `refine.Context`, for reading the stress of both routes on Mass Ride and Group
    Ride. `loop`: the plan is a loop, which keeps its route and is offered the way
    round."""
    from . import routing

    found = passages_of(trip, junctions, ctx, deadline)
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
        answer = routing._call(variant, "route", around_request(request, passed, ctx), deadline)
        around = answer.get("trip") or {}
    except routing.RouterRefused:
        around = {}
    except (routing.RouterUnavailable, routing.DeadlineExceeded):
        info["alternate"] = "time"
        return trip, info, None
    if not around.get("legs"):
        info["alternate"] = "no_route"
        return trip, info, None
    left = passages_of(around, junctions, ctx, deadline)
    if len(left) >= len(found):
        # The exclusion did not take it round (the junction's point is off the
        # graph's node, or there is no other way): nothing better to offer.
        info["alternate"] = "no_route"
        return trip, info, None
    info["alternate"] = "found"
    swap = False
    if loop:
        swap = False
    elif preset_name in GROUP_PRESETS:
        swap = group_takes(trip, around, ctx, deadline)
    elif not searched:
        # Judged as the search judges a route, junction stress and reds and all, where the
        # plan's context can read both (S3, P2); the router's cost only without one.
        judged = judged_takes(trip, around, ctx, deadline) if ctx is not None else None
        if judged is not None:
            swap = judged
        elif ctx is None:
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
