"""The Mountain Bike ride type at plan time (docs/MTB-TOPO-PLAN.md, slice 6).

The graph (`Variant.MTB`) opens every mountain-bike trail a bicycle may use, of every level.
What the rider chose, and what the owner's defaults of 2026-10-11 ask, is held here on the
router's own routes (`routemaker.mtbmode`):

- the rider's hardest level (1-4, default 2; an unrated mountain-bike trail counts as 2): a
  route on a harder trail is ranked below every route that is not, and where every route the
  router gave uses one, the harder trails are excluded (`exclude_locations`, as the calm
  search steers the router) and the router asked again, a few rounds;
- trail seeking: among the router's routes, the shortest with a trail mile at half a road mile;
- the rider's preferred level (the second pass, 1-4, default 2, never above the hardest): a
  trail mile at it counts less again, one a level away a little less (`mtbmode.trail_weight`),
  so among the router's routes the one nearest the preferred level wins; no graph change, no
  rebuild;
- connecting roads: a route with LTS 3 runs of 0.5 mi or more, or any LTS 4 or Avoid, below one
  without (beyond a little slack);
- the time shown at about 6 mph (10 km/h) on singletrack.

Where the harder trails cannot be cleared (the start is on one, or nothing else joins up), the
route is answered with `over_level_m` set, and the front end says so in words: the rider sees
it rather than being refused a ride.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from django.conf import settings
from django.db import connection

from pipeline.schema import MTB_LEVEL_COLUMN, MTB_ONLY_COLUMN, validate_schema_name
from routemaker import mtbmode
from routemaker.geo import Point, haversine

from . import presets, segment_info

logger = logging.getLogger(__name__)

PRESET = presets.MOUNTAIN_BIKE
# Rounds of exclusion and re-routing for the level rule, the points one round excludes, and
# how far apart the points are along a too-hard trail (metres).
LEVEL_ROUNDS = 3
POINTS_PER_ROUND = 60
SAMPLE_M = 40.0
# Never excluded within this far of a start, a stop or the end (straight line, metres): the
# router must be able to leave and arrive.
CLEARANCE_M = 300.0


def _has_column(schema: str, column: str) -> bool:
    return segment_info.has_columns(schema, column)


def way_traits(way_ids: Sequence[int]) -> dict[int, tuple[bool, int | None, bool]]:
    """(mtb_only, mtb_level, trail) for each way: whether it is a mountain-bike-only way, its
    level (None where unrated, or before the live table has the column), and whether it is
    trail for the seeking (mountain-bike-only, or an unpaved trail-class way)."""
    ids = sorted({int(w) for w in way_ids if w})
    if not ids:
        return {}
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    only = f"bool_or(s.{MTB_ONLY_COLUMN})" if _has_column(schema, MTB_ONLY_COLUMN) else "false"
    level = f"max(s.{MTB_LEVEL_COLUMN})" if _has_column(schema, MTB_LEVEL_COLUMN) else "NULL"
    query = (
        f"SELECT s.osm_way_id, {only}, {level}, "
        "bool_or(s.is_trail_class AND s.is_unpaved IS TRUE) "
        f"FROM {schema}.segment AS s WHERE s.osm_way_id = ANY(%s::bigint[]) "
        "GROUP BY s.osm_way_id"
    )
    with connection.cursor() as cursor:
        cursor.execute(query, [ids])
        rows = cursor.fetchall()
    return {
        int(way): (
            bool(mtb_only),
            int(lvl) if lvl is not None else None,
            bool(trail) or bool(mtb_only),
        )
        for way, mtb_only, lvl, trail in rows
    }


def stretches_of(pieces: list, classes: list, traits: dict) -> list[mtbmode.Stretch]:
    out = []
    for piece, cls in zip(pieces, classes, strict=True):
        mtb_only, level, trail = traits.get(piece.way_id, (False, None, False))
        tier = int(cls[0]) if str(cls[0]).isdigit() else None
        out.append(
            mtbmode.Stretch(
                metres=piece.metres,
                tier=tier,
                trail=trail,
                singletrack=mtb_only,
                level=mtbmode.effective_level(mtb_only, level),
            )
        )
    return out


def _pieces(trip: dict, variant: str, costing: dict, deadline, traces) -> list | None:
    from . import routing

    pieces: list = []
    for leg in trip.get("legs") or []:
        trace = routing._trace(variant, costing, leg.get("shape", ""), deadline, traces)
        if trace is None:
            return None
        pieces.extend(routing.pieces_of_trace(trace))
    return pieces


def reading_of(
    trip: dict,
    variant: str,
    costing: dict,
    when: str,
    deadline,
    traces,
    max_level: int,
    preferred_level: int | None = None,
) -> tuple[mtbmode.Reading, list, list[mtbmode.Stretch]] | None:
    """A route's reading, its pieces and its stretches; None where a leg cannot be traced."""
    from . import routing

    pieces = _pieces(trip, variant, costing, deadline, traces)
    if pieces is None:
        return None
    classes = routing.classify(pieces, when)
    stretches = stretches_of(pieces, classes, way_traits([p.way_id for p in pieces]))
    return mtbmode.read(stretches, max_level, preferred_level), pieces, stretches


def exclusion_points(
    pieces: list, stretches: Sequence[mtbmode.Stretch], max_level: int, points: list
) -> list[tuple[float, float]]:
    """Points on the too-hard trails, about SAMPLE_M apart along them, away from the plan's
    own points; at most POINTS_PER_ROUND."""
    out: list[tuple[float, float]] = []
    since = SAMPLE_M
    for piece, stretch in zip(pieces, stretches, strict=True):
        if stretch.level is None or stretch.level <= max_level:
            since = SAMPLE_M
            continue
        since += piece.metres
        if since < SAMPLE_M:
            continue
        here = Point(piece.lon, piece.lat)
        if any(haversine(here, Point(*p)) < CLEARANCE_M for p in points):
            continue
        out.append((piece.lon, piece.lat))
        since = 0.0
        if len(out) >= POINTS_PER_ROUND:
            break
    return out


def settle(
    trips: list[dict],
    trip: dict,
    request: dict,
    variant: str,
    costing: dict,
    when: str,
    deadline,
    traces: dict,
    max_level: int | None,
    points: list,
    preferred_level: int | None = None,
) -> tuple[dict, dict]:
    """The route a Mountain Bike plan answers, and what the answer says of it (`mtb`)."""
    from . import routing

    level = mtbmode.clamp_level(max_level)
    preferred = mtbmode.preferred_level(preferred_level, level)
    info: dict = {
        "max_level": level,
        "preferred_level": preferred,
        "candidates": 0,
        "rounds": 0,
        "limited": None,
    }
    candidates = [trip] + [t for t in trips[1:] if t is not trip and t.get("legs")]
    readings: list = []
    kept: list[dict] = []
    try:
        for candidate in candidates:
            found = reading_of(
                candidate,
                variant,
                costing,
                when,
                deadline,
                traces,
                level,
                preferred_level=preferred,
            )
            if found is not None:
                readings.append(found)
                kept.append(candidate)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = "time"
    if not readings:
        info["limited"] = info["limited"] or "untraced"
        return trip, info
    info["candidates"] = len(readings)
    chosen = mtbmode.best([r[0] for r in readings])
    best_trip, best = kept[chosen], readings[chosen]
    excludes: list[tuple[float, float]] = []
    base = {k: v for k, v in request.items() if k not in ("alternates", "exclude_locations")}
    # The route the next round's points come from: the last one the router gave, so each
    # round clears what the one before it found (the exclusions accumulate).
    current = best
    while current[0].over_level_m > 1.0 and info["rounds"] < LEVEL_ROUNDS:
        more = exclusion_points(current[1], current[2], level, points)
        if not more:
            info["limited"] = "no_way_round"
            break
        excludes = (excludes + more)[-150:]
        info["rounds"] += 1
        try:
            answer, _timed_out = routing._route(
                variant,
                {**base, "exclude_locations": [{"lon": x, "lat": y} for x, y in excludes]},
                deadline,
            )
            again = answer.get("trip") or {}
            found = reading_of(
                again, variant, costing, when, deadline, traces, level, preferred_level=preferred
            )
        except routing.RouterRefused:
            info["limited"] = "no_way_round"
            break
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            info["limited"] = "time"
            break
        if found is None:
            break
        current = found
        if mtbmode.better(found[0], best[0]):
            best_trip, best = again, found
    reading = best[0]
    info.update(figures(reading))
    if reading.over_level_m <= 1.0 and info["limited"] == "no_way_round":
        info["limited"] = None
    return best_trip, info


def figures(reading: mtbmode.Reading) -> dict:
    """What the answer's `mtb` says of one route's reading."""
    return {
        "trail_m": round(reading.trail_m, 1),
        "singletrack_m": round(reading.singletrack_m, 1),
        "over_level_m": round(reading.over_level_m, 1),
        "long_lts3_m": round(reading.long_lts3_m, 1),
        "lts4_m": round(reading.lts4_m, 1),
        "easier_m": round(reading.easier_m, 1),
        "harder_m": round(reading.harder_m, 1),
        "trail_weight": mtbmode.TRAIL_WEIGHT,
        "level_step": mtbmode.LEVEL_STEP,
        "level_reach": mtbmode.LEVEL_REACH,
        "singletrack_speed_kmh": mtbmode.SINGLETRACK_SPEED_KMH,
    }


def reread(
    trip: dict,
    variant: str,
    costing: dict,
    when: str,
    deadline,
    traces,
    max_level: int | None,
    preferred_level: int | None = None,
) -> dict | None:
    """One route's own reading, for a route answered beside or after `settle`'s: the way
    round an Avoid-rated junction, a candidate the rider may pick, or the answer once the
    later passes have changed it. Every route a Mountain Bike plan offers says in words how
    much of it is above the rider's level, so a harder trail is never shown without its
    warning. None where a leg cannot be traced or the budget is gone (its traces are
    usually remembered from the passes that made it)."""
    from . import routing

    level = mtbmode.clamp_level(max_level)
    preferred = mtbmode.preferred_level(preferred_level, level)
    try:
        found = reading_of(
            trip, variant, costing, when, deadline, traces, level, preferred_level=preferred
        )
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        return None
    if found is None:
        return None
    return {
        "max_level": level,
        "preferred_level": preferred,
        "limited": None,
        **figures(found[0]),
    }
