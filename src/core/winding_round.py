"""Winding trails for Group Ride and Fast, at plan time (hunt 4 P4-1).

Asked "Should Group Ride and Fast pay for winding trails the way Road Bike does?", the owner,
2026-11-09: "yes", and of the round 4 fixes: "Ok. Make sure they are included."

Road Bike pays through its own graphs: `rm:winding` (`routemaker.winding`) is written only on
`pipeline.variants.PAVED_GRAPHS`, where lua/routemaker_remap.lua prices a winding trail as the
LTS 3 stress penalty. Group Ride and Fast plan on the standard graph and its weekend twin, which
Default, Trailmaxxing, Cargo and the others share, so a price written there would charge them
all; and their calm rate is 0 (`presets.calm_rate_for`), so neither the calm search nor the
trail seek's `avoid_winding` runs for them. So the price is put on at plan time instead, with
no rebuild:

- the route the plan chose is read, and the trail-class ways on it that bend as a winding trail
  does (`routemaker.winding.is_winding` on the way's whole line, as `pipeline.run` decides
  `rm:winding`) are found in the segment table;
- where they come to WINDING_MIN_M or more, the plan's own request is asked again once with
  points along them excluded (`exclude_locations`, as Mountain Bike's level rounds steer off a
  harder trail);
- each route is scored as the search scores it (`refine.Analysis.score`) plus, for each metre of
  winding trail it rides, what a metre of LTS 3 adds in the router's own cost at this request's
  `use_roads` (`refine.lts3_added_m`), which is "read at LTS 3" as the road-bike graph reads it;
- the new route is taken where it scores better by more than `refine.IMPROVEMENT_EPS_S` and the
  level rounds' guard keeps it (`refine.level_round_kept`: no busier by the Traffic-wins rule,
  not past the ceiling, a loop's way back kept apart).

On the hunt's trip (Candy Cane City to Beach Drive at Kensington Estates, weekend) that is the
Rock Creek Trail's winding stretch read as an LTS 3 street against the car-free Beach Drive
beside it, which Road Bike already takes. WINDING_MIN_M, the one round and the point spacing are
Claude's defaults, not measured.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from routemaker import winding
from routemaker.geo import Point, haversine

from . import refine, routing, trailseek

logger = logging.getLogger(__name__)

# The ride types it runs on (the owner, 2026-11-09: "yes"). Road Bike pays in its own graphs.
PRESETS = frozenset({"group-ride", "fast"})
# The least winding trail (metres) on a route that is worth asking the router round:
# Claude's default, not measured. A few hundred metres of bends cost a road bike seconds.
WINDING_MIN_M = 400.0
# The points one ask excludes, how far apart along a winding trail (metres), and the clearance
# kept round the plan's own points (the router must be able to leave and arrive), as Mountain
# Bike's level rounds (`core.mtb`): Claude's defaults, not measured.
POINTS_PER_ROUND = 60
SAMPLE_M = 40.0
CLEARANCE_M = 300.0


def applies(preset_name: str) -> bool:
    """Whether a plan of this ride type pays for winding trails at plan time."""
    return preset_name in PRESETS


def winding_ways(schema: str, way_ids: Iterable[int]) -> set[int]:
    """The ways among `way_ids` that are trail class and wind (`routemaker.winding`), each
    measured on its whole line: its segments joined in order (`segment.ordinal`)."""
    from django.db import connection

    ids = sorted({int(w) for w in way_ids if w})
    if not ids:
        return set()
    query = (
        "SELECT s.osm_way_id, ST_AsText(s.geometry) "
        f"FROM {schema}.segment AS s "
        "WHERE s.osm_way_id = ANY(%s::bigint[]) AND s.is_trail_class "
        "ORDER BY s.osm_way_id, s.ordinal"
    )
    with connection.cursor() as cursor:
        cursor.execute(query, [ids])
        rows = cursor.fetchall()
    lines: dict[int, list[tuple[float, float]]] = {}
    for way, text in rows:
        points = trailseek._parse_line(text)
        line = lines.setdefault(int(way), [])
        line.extend(points[1:] if line and points and line[-1] == points[0] else points)
    return {way for way, line in lines.items() if winding.is_winding(line)}


def winding_m(read: refine.Analysis, ways: set[int]) -> float:
    """Metres of the route on the winding trails `ways`."""
    return sum(p.metres for p in read.pieces if p.way_id in ways)


def charge_s(metres: float, ctx: refine.Context) -> float:
    """The cost of `metres` of winding trail read at LTS 3: what a metre of LTS 3 adds in the
    router's own cost at this request's `use_roads` (`refine.lts3_added_m`), in quiet metres at
    the request's quiet cost."""
    return ctx.quiet_cost * refine.lts3_added_m(ctx) * metres


def priced_score(read: refine.Analysis, ways: set[int], ctx: refine.Context) -> float:
    """The search's score with the winding trail on the route read at LTS 3."""
    return read.score(ctx) + charge_s(winding_m(read, ways), ctx)


def exclusion_points(
    read: refine.Analysis, ways: set[int], points: list
) -> list[tuple[float, float]]:
    """Points on the winding trails, about SAMPLE_M apart along them, clear of the plan's own
    points by CLEARANCE_M; at most POINTS_PER_ROUND."""
    out: list[tuple[float, float]] = []
    since = SAMPLE_M
    for piece in read.pieces:
        if piece.way_id not in ways:
            since = SAMPLE_M
            continue
        since += piece.metres
        if since < SAMPLE_M:
            continue
        here = Point(piece.lon, piece.lat)
        if any(haversine(here, Point(p[0], p[1])) < CLEARANCE_M for p in points):
            continue
        out.append((piece.lon, piece.lat))
        since = 0.0
        if len(out) >= POINTS_PER_ROUND:
            break
    return out


def settle(trip: dict, ctx: refine.Context, keeps=None) -> tuple[dict, dict]:
    """The route a Group Ride or Fast plan answers with its winding trails priced, and what
    was done (logged, and `winding` on the answer).

    `keeps`: as for the level rounds (`refine.level_round_keeps`), where `trip` is not the
    plan's own request answered (a loop's way back, the calm search, the fewer repeats), a
    further test the round's route must pass to replace it."""
    info: dict = {"winding_m": 0.0, "asked": False, "taken": False, "limited": None}
    deadline = refine.late_deadline(ctx)
    try:
        read = refine.analyse(trip, ctx, deadline)
        if read is None:
            info["limited"] = "untraced"
            return trip, info
        ways = winding_ways(ctx.schema, (p.way_id for p in read.pieces))
        metres = winding_m(read, ways)
        info["winding_m"] = round(metres, 1)
        if metres < WINDING_MIN_M:
            return trip, info
        more = exclusion_points(read, ways, ctx.points)
        if not more:
            info["limited"] = "no_way_round"
            return trip, info
        base = {k: v for k, v in ctx.request.items() if k != "alternates"}
        excludes = [
            *(base.get("exclude_locations") or []),
            *(ctx.level_excludes or []),
            *({"lon": x, "lat": y} for x, y in more),
        ]
        info["asked"] = True
        answer, _timed_out = routing._route(
            ctx.variant, {**base, "exclude_locations": excludes}, deadline
        )
        again = answer.get("trip") or {}
        found = refine.analyse(again, ctx, deadline) if again.get("legs") else None
    except routing.PlanCancelled:
        # A newer plan replaced this one (a DeadlineExceeded too): the plan ends here.
        raise
    except routing.RouterRefused:
        info["limited"] = "no_way_round"
        return trip, info
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = "time"
        return trip, info
    except Exception:  # noqa: BLE001 - a plan is answered without the round
        logger.warning("the winding-trail round could not run", exc_info=True)
        info["limited"] = "table"
        return trip, info
    if found is None:
        info["limited"] = info["limited"] or "untraced"
        return trip, info
    # The new route's own winding trail (it may ride another) is priced too.
    try:
        found_ways = ways | winding_ways(ctx.schema, (p.way_id for p in found.pieces))
    except Exception:  # noqa: BLE001 - as above
        logger.warning("the winding-trail round could not run", exc_info=True)
        info["limited"] = "table"
        return trip, info
    if (
        priced_score(found, found_ways, ctx)
        < priced_score(read, found_ways, ctx) - refine.IMPROVEMENT_EPS_S
        and refine.level_round_kept(found, read, ctx)
        and (keeps is None or keeps(again))
    ):
        info["taken"] = True
        info["winding_m"] = round(winding_m(found, found_ways), 1)
        # The later ways round (the red pass, the Avoid-junction pass) keep off them too.
        ctx.level_excludes.extend({"lon": x, "lat": y} for x, y in more)
        return again, info
    return trip, info
