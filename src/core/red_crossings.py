"""A very high stress (red) crossing still on the answer, where no crossing search ran on
the whole route: the way round, asked for and taken where it is better.

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
then reuses), and each red crossing clear of its ends and stops
(`refine.ENDPOINT_CLEARANCE_M`) is asked round, the worst first (`reds_of`). A red is
what the map draws red, and a trail crossing drawn orange only because no signal is mapped
whose cost is red-level (`refine.avoidance_severity`, the 2026-11-08 hunt, J1).

How each is asked round (the 2026-11-08 hunt, S1, P1 and R1/H4). The first version asked
once, from the plan's own request with every red excluded together. One red with no way
round (the approach to the only bridge) kept every red; and the plan's own request is not
the route answered: it has no climb the hill seek routed through (Mountain Goat), none of
Mountain Bike's exclusions of trails above the rider's level, none of the stops' fewer
repeats, and on a loop none of the way back `refine.make_loop` made (OWNER-DECISIONS 266:
a loop's way back is not merged into the way out), so the pass could not run on a loop at
all. Now:

1. Where the plan is plain (one leg, not a loop, no climb sought, no level exclusions), the
   whole plan is asked once with every red excluded, as before (`around_request`), with the
   request's own exclusions kept.
2. Then each red still on the route, worst first, is asked round alone: the stretch of the
   route from `WINDOWS_M` before it to as far after it (within its leg) is asked again with
   that red excluded (`window_request`, each end a break facing the way the route goes),
   and the answer spliced in its place (`splice_leg`). The rest of the route is untouched,
   so a loop keeps its way back, a seek its climb and the stops their legs. A wider window
   is tried where the narrow one finds no way round. A red with no way round is dropped
   and the next one tried.

Every ask excludes, besides the red, the request's own exclusions, Mountain Bike's level
exclusions (`refine.Context.level_excludes`) and the reds already ridden round. A way
round replaces the route where it has fewer red crossings, the search's own rule prefers
it (`refine.better`: the score, which prices each red at `RED_DETOUR_S` of quiet riding on
top of its cost, or the stress order at the top of the slider, with the worth-its-miles
rule), it is no busier by the Traffic-wins guard (each red counted at its cost,
`refine._busier`'s rule), at the top of the slider not past the ceiling where the route
was not, on a loop no more of the way back on the way out than the loop has
(`refine.loop_refused`), and on a climb seek not flatter (`CLIMB_KEPT`). Each red taken
round is added to `Context.red_excludes`, which the Avoid-junction pass asks with.

Bounded: at most `MAX_ASKS` router calls, inside the plan's clock keeping the answer's
reserve (`refine.late_deadline`); on a long Trailmaxxing plan the legs' searches leave it
`refine.LONG_RED_RESERVE_S` (S2). Never on a Mass Ride (its crossings are priced for the
group and its route held to the direct roadway), a followed line or Go's first route.
"""

from __future__ import annotations

import logging

from routemaker import intersections as model
from routemaker.geo import Point, bearing_lonlat, haversine, haversine_lonlat

from . import dedodge, refine, routing

logger = logging.getLogger(__name__)

# The least time (seconds) left before the answer's reserve to start: a route call and
# its reading.
MIN_START_S = 4.0
# And to ask round one more red.
MIN_ASK_S = 2.0
# The most red crossings excluded in one whole-plan ask (the first round): past this many
# the plan is a mess the one ask will not fix, and Valhalla's own limit on exclusions is 200.
MAX_REDS = 20
MAX_EXCLUDES = 200
# The most router calls the pass makes, all rounds together.
MAX_ASKS = 6
# How far before and after a red (metres along the route, within its leg) the stretch
# asked again around it runs: the narrow one first, the wide one where it found no way
# round. 2 km takes in a block or two of grid either side and the trail a crossing left
# (Belle Haven to the Tulane Dr crossing is under a kilometre); 5 km the next river or
# rail crossing over.
WINDOWS_M = (2000.0, 5000.0)
# The router must place the way round's ends this close to the stretch's (metres).
SNAP_M = 15.0
# On a climb seek a way round must keep at least this share of the route's climbing.
CLIMB_KEPT = 0.9


def reds_of(read: refine.Analysis) -> list:
    """The route's red crossings clear of its ends and stops, the worst first: as the map
    draws them, and the capped trail crossings that cost as much (`refine.avoidance_severity`)."""
    found = [
        e
        for e in read.events or ()
        if refine.avoidance_severity(e) == model.RED
        and refine._clear_of_ends(e.m, read.length_m, read.via_m)
    ]
    return sorted(found, key=lambda e: -e.cost_ft)


def exclusion(red) -> dict:
    """One red crossing as `exclude_locations` has it: every edge at its node
    (`refine.CROSSING_EXCLUDE_RADIUS_M`), never the sidepath or bridge a few metres off."""
    return {"lon": red.lon, "lat": red.lat, "radius": refine.CROSSING_EXCLUDE_RADIUS_M}


def kept_out(request: dict, ctx: refine.Context) -> list[dict]:
    """What every ask keeps out besides the reds it asks round: the request's own
    exclusions, Mountain Bike's level exclusions and the reds already ridden round."""
    return [
        *(request.get("exclude_locations") or []),
        *(ctx.level_excludes or []),
        *(ctx.red_excludes or []),
    ]


def _excludes(kept: list[dict], reds: list[dict]) -> list[dict]:
    """`kept` and `reds`, the reds always in, within the router's limit."""
    return kept[: max(0, MAX_EXCLUDES - len(reds))] + reds


def around_request(request: dict, reds: list, ctx: refine.Context | None = None) -> dict:
    """The plan's request with every edge at each of `reds` excluded, and what it and the
    passes before kept out (`kept_out`)."""
    asked = {k: v for k, v in request.items() if k not in ("alternates", "exclude_locations")}
    kept = (
        kept_out(request, ctx) if ctx is not None else list(request.get("exclude_locations") or [])
    )
    asked["exclude_locations"] = _excludes(kept, [exclusion(e) for e in reds[:MAX_REDS]])
    return asked


def plain(trip: dict, ctx: refine.Context, loop: bool) -> bool:
    """Whether the plan's own request is the route answered (the whole-plan ask may be
    made): one leg, not a loop, no climb sought, no level exclusions."""
    return (
        len(trip.get("legs") or []) == 1
        and not loop
        and not ctx.seek_climb
        and not ctx.level_excludes
    )


def _leg_at(read: refine.Analysis, m: float) -> int:
    """The leg `m` metres along the route is on."""
    number = 0
    for via in read.via_m:
        if m >= via:
            number += 1
    return number


def stretch(shape: list, red, window_m: float) -> tuple[int, int] | None:
    """The shape's vertices `window_m` before and after the one nearest the red (or the
    leg's ends, where nearer), or None where the leg has no vertex either side of it."""
    if len(shape) < 3:
        return None
    here = (red.lon, red.lat)
    k = min(range(len(shape)), key=lambda i: haversine_lonlat(shape[i], here))
    i, back = k, 0.0
    while i > 0 and back < window_m:
        back += haversine_lonlat(shape[i - 1], shape[i])
        i -= 1
    j, ahead = k, 0.0
    while j < len(shape) - 1 and ahead < window_m:
        ahead += haversine_lonlat(shape[j], shape[j + 1])
        j += 1
    if i >= k or j <= k:
        return None
    return i, j


def window_request(
    ctx: refine.Context, shape: list, i: int, j: int, excludes: list, headings: bool = True
) -> dict:
    """The plan's own request (its costing and options) for the route from vertex `i` of
    the leg's shape to vertex `j`, each end a break facing the way the route goes, with
    `excludes` excluded."""
    request = {
        k: v
        for k, v in ctx.request.items()
        if k not in ("alternates", "exclude_locations", "locations")
    }
    here = {"lon": shape[i][0], "lat": shape[i][1], "type": "break"}
    there = {"lon": shape[j][0], "lat": shape[j][1], "type": "break"}
    if headings:
        here["heading"] = int(round(bearing_lonlat(shape[i], shape[i + 1]))) % 360
        there["heading"] = int(round(bearing_lonlat(shape[j - 1], shape[j]))) % 360
    request["locations"] = [here, there]
    request["exclude_locations"] = excludes
    return request


def splice_leg(leg: dict, shape: list, i: int, j: int, sub: dict, interval_m: float) -> dict | None:
    """The leg with its shape from vertex `i` to vertex `j` replaced by `sub` (the router's
    leg between those two points); None where the router's ends are not those. Its length,
    time and cost less the stretch's share of them plus the replacement's, its elevation
    likewise by `interval_m` (as `dedodge.splice_leg`)."""
    sub_shape = routing.decode_polyline6(sub.get("shape", ""))
    if len(sub_shape) < 2:
        return None
    if (
        haversine(Point(*sub_shape[0]), Point(*shape[i])) > SNAP_M
        or haversine(Point(*sub_shape[-1]), Point(*shape[j])) > SNAP_M
    ):
        return None
    steps = [haversine_lonlat(a, b) for a, b in zip(shape, shape[1:], strict=False)]
    whole_m = sum(steps)
    start_m, cut_m = sum(steps[:i]), sum(steps[i:j])
    points = [*shape[:i], *sub_shape, *shape[j + 1 :]]
    before, after = leg.get("summary") or {}, sub.get("summary") or {}
    share = cut_m / whole_m if whole_m > 0 else 0.0
    summary = dict(before)
    if "length" in before and "length" in after:
        summary["length"] = before["length"] * (1.0 - share) + after["length"]
    for key in ("time", "cost"):
        if key in before and key in after:
            summary[key] = before[key] * (1.0 - share) + after[key]
    new = {**leg, "shape": dedodge.encode_polyline6(points), "summary": summary}
    heights, sub_heights = leg.get("elevation"), sub.get("elevation")
    if heights:
        k_out = round(start_m / interval_m)
        k_in = round((start_m + cut_m) / interval_m)
        if not sub_heights:
            sub_heights = dedodge._between(heights, k_out, k_in, after.get("length"), interval_m)
        new["elevation"] = [*heights[:k_out], *sub_heights, *heights[k_in + 1 :]]
    return new


def takes(
    read: refine.Analysis, whole: refine.Analysis, ctx: refine.Context, loop: bool = False
) -> bool:
    """Whether the way round (`read`) is to replace the route (`whole`)."""
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
    # A loop's way back is not merged into its way out (OWNER-DECISIONS 266).
    if loop and refine.loop_refused(read, ctx):
        return False
    # A climb the rider sought is not traded for a flatter way round (P1).
    if ctx.seek_climb and read.climb_m < CLIMB_KEPT * whole.climb_m:
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


def _key(red) -> tuple:
    return (round(red.lon, 5), round(red.lat, 5))


class _Out(Exception):
    """The pass's asks or time are spent."""


def _ask(ctx: refine.Context, request: dict, deadline, info: dict) -> dict | None:
    """One /route answer's trip within the pass's bounds, or None where the router finds
    no route (`no_route` counted)."""
    if info["asks"] >= MAX_ASKS:
        info["limited"] = info["limited"] or "asks"
        raise _Out
    if deadline.at - routing.clock() < MIN_ASK_S:
        info["limited"] = "time"
        raise _Out
    info["asks"] += 1
    try:
        answer = routing._call(ctx.variant, "route", request, deadline)
    except routing.RouterRefused:
        info["no_route"] += 1
        return None
    trip = answer.get("trip") or {}
    if not trip.get("legs"):
        info["no_route"] += 1
        return None
    return trip


def _read(trip: dict, ctx: refine.Context, deadline, info: dict) -> refine.Analysis | None:
    read = refine.analyse(trip, ctx, deadline)
    if read is None or read.events is None:
        info["unread"] += 1
        return None
    return read


def _round(trip, red, ctx: refine.Context, whole, deadline, info: dict, loop: bool = False):
    """The trip with `red` ridden round by a window of its leg, and its reading, or
    (None, None) where no window finds a way round."""
    number = _leg_at(whole, red.m)
    legs = trip.get("legs") or []
    if number >= len(legs):
        return None, None
    leg = legs[number]
    shape = routing.decode_polyline6(leg.get("shape", ""))
    excludes = _excludes(kept_out(ctx.request, ctx), [exclusion(red)])
    tried: set = set()
    for window_m in WINDOWS_M:
        bounds = stretch(shape, red, window_m)
        if bounds is None or bounds in tried:
            continue
        tried.add(bounds)
        i, j = bounds
        sub = None
        # Facing the way the route goes, and without where the router finds no path so.
        for headings in (True, False):
            sub = _ask(ctx, window_request(ctx, shape, i, j, excludes, headings), deadline, info)
            if sub is not None:
                break
        if sub is None or len(sub.get("legs") or []) != 1:
            continue
        sub_leg = {
            **sub["legs"][0],
            "summary": sub["legs"][0].get("summary") or sub.get("summary") or {},
        }
        new_leg = splice_leg(leg, shape, i, j, sub_leg, routing.ELEVATION_INTERVAL_M)
        if new_leg is None:
            continue
        candidate = refine._splice(trip, number, {"legs": [new_leg], "summary": new_leg["summary"]})
        read = _read(candidate, ctx, deadline, info)
        if read is not None and takes(read, whole, ctx, loop):
            return candidate, read
    return None, None


def settle(
    trip: dict,
    ctx: refine.Context,
    searched: bool,
    refined: dict | None = None,
    loop: bool = False,
) -> tuple[dict, dict | None]:
    """The answer's trip, and what was done (None: nothing to do); on a swap the search's
    figures in `refined` are restated (`restate`). `loop`: the plan is a loop, whose way
    back is kept (each red is ridden round by its own stretch). It does not raise for the
    router or the clock; an unexpected failure leaves the trip as the rounds left it. Run
    before the dodge pass, so a weave the way round takes on is taken out as any other
    (OWNER-DECISIONS 272, 273)."""
    if searched or ctx.group:
        return trip, None
    info: dict = {
        "reds": None,
        "decision": "kept",
        "avoided": 0,
        "no_way_round": 0,
        "asks": 0,
        "no_route": 0,
        "unread": 0,
        "limited": None,
        "reds_after": None,
    }
    deadline = refine.late_deadline(ctx)
    if deadline.at - routing.clock() < MIN_START_S:
        info["limited"] = "time"
        return trip, info
    first = None
    whole = None
    try:
        first = whole = refine.analyse(trip, ctx, deadline)
        if whole is None or whole.events is None:
            info["limited"] = "unread"
            return trip, info
        reds = reds_of(whole)
        info["reds"] = len(reds)
        if not reds:
            return trip, info
        # 1. The whole plan, every red excluded, where its request is the route answered.
        if plain(trip, ctx, loop):
            around = _ask(ctx, around_request(ctx.request, reds, ctx), deadline, info)
            read = _read(around, ctx, deadline, info) if around is not None else None
            if read is not None and takes(read, whole, ctx):
                ctx.red_excludes.extend(exclusion(e) for e in reds[:MAX_REDS])
                trip, whole = around, read
                info["avoided"] = max(1, refine.red_count(first) - refine.red_count(read))
        # 2. Each red still on it, the worst first, by its own stretch; one with no way
        # round is dropped and the next tried.
        tried: set = set()
        while True:
            left = [e for e in reds_of(whole) if _key(e) not in tried]
            if not left:
                break
            red = left[0]
            tried.add(_key(red))
            new_trip, read = _round(trip, red, ctx, whole, deadline, info, loop)
            if new_trip is None:
                info["no_way_round"] += 1
                continue
            ctx.red_excludes.append(exclusion(red))
            info["avoided"] += max(1, refine.red_count(whole) - refine.red_count(read))
            trip, whole = new_trip, read
    except _Out:
        pass
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = "time"
    except routing.RouterRefused:
        info["limited"] = "unread"
    except Exception:  # noqa: BLE001 - the route is answered as the rounds left it
        logger.warning("the red crossing pass failed", exc_info=True)
        info["limited"] = "error"
    if whole is not None and first is not None and whole is not first:
        info["decision"] = "avoided"
        restate(refined, whole, first)
    if whole is not None and whole.events is not None:
        info["reds_after"] = refine.red_count(whole)
    if info["limited"] is None and not info["avoided"] and info["asks"]:
        if info["no_route"] == info["asks"]:
            # Every ask found no route at all.
            info["limited"] = "no_route"
    return trip, info
