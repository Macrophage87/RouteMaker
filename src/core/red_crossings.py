"""A very high stress (red) crossing still on the answer, where no crossing search ran on
the whole route: the way round, asked for once and taken where it is better.

The owner, 2026-11-08, of a Union Station to Mount Vernon ride that left the Mount Vernon
Trail at Belle Haven to cross the George Washington Parkway at grade at Tulane Dr, with no
signal: "That's been the chief complaint about my routing tool and I thought it was fixed.
It's taking people onto dangerous intersections." The crossing was priced and drawn red
(PR #1026), but nothing looked for a way round it:

- the crossing search (`core.refine.refine`) runs only on a plan whose points are within
  `refine.REFINE_MAX_SPAN_M` (30 km, 19 mi) of straight line, leg by leg added up, so a
  long or many-stop plan on any ride type but Trailmaxxing answered the router's own line
  with its red crossings drawn and not avoided (`routing._refine_limit`, "span");
- Trailmaxxing's long plans (`refine.refine_long`) search only the legs with busy road on
  them, so a leg whose only fault was a red crossing kept it.

So after the search, on every plan where it did not run over the whole route with at
least one round (`searched` false), the answer is read (`refine.analyse`, which the answer
then reuses), and where it has a red crossing clear of its ends and stops
(`refine.ENDPOINT_CLEARANCE_M`), the router is asked once for the same plan with every edge
at those junctions excluded (`exclude_locations` with `MATCH_RADIUS_M`, as the search's own
crossing rounds ask). The way round replaces the answer where it has fewer red crossings,
the search's own rule prefers it (`refine.better`: the score, which prices each red at
`RED_DETOUR_S` of quiet riding on top of its cost, or the stress order at the top of the
slider, with the worth-its-miles rule), it is no busier by the Traffic-wins guard (each
red counted at its cost, `refine._busier`'s rule) and, at the top of the slider, not past
the ceiling where the answer was not. One /route call and one reading; bounded by the
plan's own clock, keeping the answer's reserve (`refine.late_deadline`). Never on a Mass
Ride (its crossings are priced for the group and its route held to the direct roadway), a
loop, a followed line or Go's first route.
"""

from __future__ import annotations

import logging

from routemaker import avoid_junctions as avoid_model
from routemaker import intersections as model

from . import refine, routing

logger = logging.getLogger(__name__)

# The least time (seconds) left before the answer's reserve to start: a route call and
# its reading.
MIN_START_S = 4.0
# The most red crossings excluded in one ask: past this many the plan is a mess the one
# ask will not fix, and Valhalla's own limit on exclusions is 200.
MAX_REDS = 20


def reds_of(read: refine.Analysis) -> list:
    """The route's red crossings (as the map draws them) clear of its ends and stops."""
    return [
        e
        for e in read.events or ()
        if e.severity == model.RED and refine._clear_of_ends(e.m, read.length_m, read.via_m)
    ]


def around_request(request: dict, reds: list) -> dict:
    """The plan's request with every edge at each of `reds` excluded."""
    asked = {k: v for k, v in request.items() if k not in ("alternates", "exclude_locations")}
    asked["exclude_locations"] = [
        {"lon": e.lon, "lat": e.lat, "radius": int(avoid_model.MATCH_RADIUS_M)}
        for e in reds[:MAX_REDS]
    ]
    return asked


def takes(read: refine.Analysis, whole: refine.Analysis, ctx: refine.Context) -> bool:
    """Whether the way round (`read`) is to replace the answer (`whole`)."""
    if refine.red_count(read) >= refine.red_count(whole):
        return False
    busier = (
        read.rated_exposure_m + read.avoid_junction_m + read.red_m
        > refine._allowance(whole.rated_exposure_m) + whole.avoid_junction_m + whole.red_m
    )
    if busier:
        return False
    # Past the ceiling the search's own rounds refuse, at every rate (`Context.ceiling_m`).
    if refine.too_long(read.length_m, ctx) and not refine.too_long(whole.length_m, ctx):
        return False
    return refine.better(read, whole, ctx)


def restate(refined: dict | None, read: refine.Analysis, whole: refine.Analysis) -> None:
    """The search's figures (`calm_search`) as the route now answered has them, as
    `dedodge.settle` restates them after a dodge is taken out."""
    if refined is None:
        return
    if refined.get("extra_distance_m") is not None:
        refined["extra_distance_m"] = round(
            refined["extra_distance_m"] + read.length_m - whole.length_m, 1
        )
    for name, value in (
        ("exposure_after_m", read.exposure_m),
        ("lts4_m_after", read.lts4_m),
        ("lts3_m_after", read.lts3_m),
        ("lts4_after_m", refine.rated_lts4_m(read)),
        ("top_m_after", read.top_m),
    ):
        if name in refined:
            refined[name] = round(value, 1)


def settle(
    trip: dict, ctx: refine.Context, searched: bool, refined: dict | None = None
) -> tuple[dict, dict | None]:
    """The answer's trip, and what was done (None: nothing to do); on a swap the search's
    figures in `refined` are restated (`restate`). It does not raise for the router or the
    clock; an unexpected failure leaves the trip as it was. Run before the dodge pass, so
    a weave the way round takes on is taken out as any other (OWNER-DECISIONS 272, 273)."""
    if searched or ctx.group:
        return trip, None
    info: dict = {"reds": None, "decision": "kept", "limited": None, "reds_after": None}
    deadline = refine.late_deadline(ctx)
    if deadline.at - routing.clock() < MIN_START_S:
        info["limited"] = "time"
        return trip, info
    try:
        whole = refine.analyse(trip, ctx, deadline)
        if whole is None or whole.events is None:
            info["limited"] = "unread"
            return trip, info
        reds = reds_of(whole)
        info["reds"] = len(reds)
        if not reds:
            return trip, info
        try:
            asked = around_request(ctx.request, reds)
            answer = routing._call(ctx.variant, "route", asked, deadline)
        except routing.RouterRefused:
            info["limited"] = "no_route"
            return trip, info
        around = answer.get("trip") or {}
        if not around.get("legs"):
            info["limited"] = "no_route"
            return trip, info
        read = refine.analyse(around, ctx, deadline)
        if read is None or read.events is None:
            info["limited"] = "unread"
            return trip, info
        info["reds_after"] = refine.red_count(read)
        if takes(read, whole, ctx):
            info["decision"] = "avoided"
            restate(refined, read, whole)
            return around, info
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = "time"
    except routing.RouterRefused:
        info["limited"] = "unread"
    except Exception:  # noqa: BLE001 - the route is answered as it was
        logger.warning("the red crossing pass failed", exc_info=True)
        info["limited"] = "error"
    return trip, info
