"""The "Easy MTB trails" switch at plan time (the owner, 2026-11-08).

"allow trailmaxxing to use MTB trails too, some are definitely fine for that", "But it's opt
in there too. Make sure the MCP can use that too", "And default"; the design "Steer on
Gravel's graph": no new graph and no new router. A Default or Trailmaxxing ride with the
switch on routes on the off-road graph (`Variant.OFFROAD`, `presets.variant_for_ride`), where
the mountain-bike class and the rated singletrack up to level 1 are open, with its own
costing, so its calm ranking and stress rules hold as on any of its rides.

Easy is what the owner counted: "yes 0 1 and unknown are counted", "Unknown is typically grass
and dirt". A trail rated 0 or 1 on `mtb:scale` or `mtb:scale:imba`, or not rated at all, is
easy; one rated 2 or harder stays the Mountain Bike ride type's. The off-road graph keeps the
rated singletrack it opens to level 1 (`singletrack.OFFROAD_MAX_LEVEL`), but a mountain-bike
class way whose rating the singletrack rule does not read (`S2`, `0-2`) is open on it and is
not easy. Such a way carries no `segment.mtb_level` (that is written on closed singletrack
alone), but its kept `mtb:scale` and `mtb:scale:imba` are in `segment.trail_tags`, so its
level is read from them here (`singletrack.mtb_level`): no new column and no rebuild.

The harder trails are held off as `core.mtb` holds a rider's hardest level: where the route
answered rides one, points on it are excluded (`exclude_locations`) and the router asked
again, a few rounds, and the route with the least harder trail kept. Where none can be
cleared, the route is answered with `harder_m` set and the page says so.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from django.conf import settings
from django.db import connection

from pipeline.schema import (
    MTB_LEVEL_COLUMN,
    MTB_ONLY_COLUMN,
    TRAIL_TAGS_COLUMN,
    validate_schema_name,
)
from routemaker import mtbmode, singletrack

from . import mtb, presets, segment_info

logger = logging.getLogger(__name__)

# The ride types that offer the switch (the owner, 2026-11-08: Trailmaxxing, "And default").
PRESETS = presets.EASY_MTB_PRESETS
# The hardest level counted easy: 0 and 1 ("yes 0 1 and unknown are counted").
EASY_MAX_LEVEL = 1
ROUNDS = mtb.LEVEL_ROUNDS
# Metres of harder trail below which a route is taken to have none (as `core.mtb`).
TOLERANCE_M = 1.0


def level_of(mtb_only: bool, mtb_level: int | None, trail_tags: object) -> int | None:
    """A way's mountain-bike level for the switch: its `mtb_level` where the rebuild wrote one,
    else, on a mountain-bike-only way, the level its kept ratings name (`trail_tags`); None on
    an unrated trail, a trail rated 0, and every other way."""
    if mtb_level in mtbmode.LEVELS:
        return int(mtb_level)
    if mtb_only and isinstance(trail_tags, dict):
        return singletrack.mtb_level({k: str(v) for k, v in trail_tags.items()})
    return None


def is_easy(level: int | None) -> bool:
    return level is None or level <= EASY_MAX_LEVEL


def _tags(kept: object) -> object:
    """The kept tags as a dict: the driver may hand jsonb over as its text."""
    if isinstance(kept, str):
        try:
            return json.loads(kept)
        except ValueError:
            return None
    return kept


def way_levels(way_ids: Sequence[int]) -> dict[int, int | None]:
    """Each way's level for the switch (`level_of`), read from the live segment table."""
    ids = sorted({int(w) for w in way_ids if w})
    if not ids:
        return {}
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    has = segment_info.has_columns
    only = f"bool_or(s.{MTB_ONLY_COLUMN})" if has(schema, MTB_ONLY_COLUMN) else "false"
    level = f"max(s.{MTB_LEVEL_COLUMN})" if has(schema, MTB_LEVEL_COLUMN) else "NULL"
    tags = (
        f"(array_agg(s.{TRAIL_TAGS_COLUMN}) FILTER (WHERE s.{TRAIL_TAGS_COLUMN} IS NOT NULL))[1]"
        if has(schema, TRAIL_TAGS_COLUMN)
        else "NULL"
    )
    query = (
        f"SELECT s.osm_way_id, {only}, {level}, {tags} "
        f"FROM {schema}.segment AS s WHERE s.osm_way_id = ANY(%s::bigint[]) "
        "GROUP BY s.osm_way_id"
    )
    with connection.cursor() as cursor:
        cursor.execute(query, [ids])
        rows = cursor.fetchall()
    return {
        int(way): level_of(bool(mtb_only), lvl, _tags(kept)) for way, mtb_only, lvl, kept in rows
    }


def stretches_of(pieces: list, levels: dict[int, int | None]) -> list[mtbmode.Stretch]:
    """One stretch a piece, its level set only where the trail is not easy, so the level
    rounds' points (`mtb.exclusion_points`, at `EASY_MAX_LEVEL`) fall on harder trails."""
    out = []
    for piece in pieces:
        level = levels.get(piece.way_id)
        hard = None if is_easy(level) else level
        out.append(
            mtbmode.Stretch(
                metres=piece.metres,
                tier=None,
                trail=False,
                singletrack=hard is not None,
                level=hard,
            )
        )
    return out


def harder_m(stretches: Sequence[mtbmode.Stretch]) -> float:
    return sum(s.metres for s in stretches if s.level is not None and s.level > EASY_MAX_LEVEL)


def reading_of(
    trip: dict, variant: str, costing: dict, deadline, traces
) -> tuple[float, list, list[mtbmode.Stretch]] | None:
    """A route's metres on harder trails, its pieces and its stretches; None where a leg
    cannot be traced."""
    pieces = mtb._pieces(trip, variant, costing, deadline, traces)
    if pieces is None:
        return None
    stretches = stretches_of(pieces, way_levels([p.way_id for p in pieces]))
    return harder_m(stretches), pieces, stretches


def settle(
    trip: dict,
    request: dict,
    variant: str,
    costing: dict,
    deadline,
    traces: dict,
    points: list,
    level_excludes: list | None = None,
    keeps=None,
) -> tuple[dict, dict]:
    """The route an Easy MTB trails plan answers, and what the answer says of it (`easy_mtb`).

    `level_excludes`, where given, has the exclusions the answered route was asked with added
    to it, so the passes after this one (the red pass, the Avoid-junction pass) keep the
    harder trails out as Mountain Bike's do (`refine.Context.level_excludes`).

    `keeps`, where given (`refine.level_round_keeps`: `trip` is not the plan's own request
    answered, but the calm search's, a loop's way back or the target fit), says whether a
    round's route may replace it; the rounds re-ask the plan's request, so on harder metres
    alone they threw that work away (the third routing hunt, C3-1)."""
    from . import routing

    info: dict = {"max_level": EASY_MAX_LEVEL, "rounds": 0, "harder_m": None, "limited": None}
    try:
        best = reading_of(trip, variant, costing, deadline, traces)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = "time"
        return trip, info
    if best is None:
        info["limited"] = "untraced"
        return trip, info
    best_trip = trip
    current = best
    excludes: list[tuple[float, float]] = []
    best_excludes: list[tuple[float, float]] = []
    base = {k: v for k, v in request.items() if k not in ("alternates", "exclude_locations")}
    while current[0] > TOLERANCE_M and info["rounds"] < ROUNDS:
        more = mtb.exclusion_points(current[1], current[2], EASY_MAX_LEVEL, points)
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
            found = reading_of(again, variant, costing, deadline, traces)
        except routing.RouterRefused:
            info["limited"] = "no_way_round"
            break
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            info["limited"] = "time"
            break
        if found is None:
            break
        current = found
        if found[0] < best[0] and (keeps is None or keeps(again)):
            best_trip, best = again, found
            best_excludes = list(excludes)
    if level_excludes is not None:
        level_excludes.extend({"lon": x, "lat": y} for x, y in best_excludes)
    info["harder_m"] = round(best[0], 1)
    if best[0] > TOLERANCE_M and info["limited"] is None:
        info["limited"] = "no_way_round"
    if best[0] <= TOLERANCE_M and info["limited"] == "no_way_round":
        info["limited"] = None
    return best_trip, info


def reread(trip: dict, variant: str, costing: dict, deadline, traces) -> dict | None:
    """One route's own reading, for a route answered beside or after `settle`'s (a candidate,
    the way round an Avoid-rated junction, the answer once the later passes changed it), so a
    harder trail is never shown without its notice. None where it cannot be read."""
    from . import routing

    try:
        found = reading_of(trip, variant, costing, deadline, traces)
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        return None
    if found is None:
        return None
    return {
        "max_level": EASY_MAX_LEVEL,
        "rounds": 0,
        "harder_m": round(found[0], 1),
        "limited": "no_way_round" if found[0] > TOLERANCE_M else None,
    }


def no_graph() -> dict:
    """What the answer says where the off-road router is not being served: the ride was
    planned on the standard graph, as Gravel's is, where no mountain-bike trail is open."""
    return {
        "max_level": EASY_MAX_LEVEL,
        "rounds": 0,
        "harder_m": None,
        "limited": "no_offroad_graph",
    }
