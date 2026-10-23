"""The well-known bike corridors the owner named, always drawn as the most popular class.

The owner, 2026-10-21: "Let's focus on the major cycling corridors, which are well known"
... "The major routes are rock creek trail, the CCT, the MBT, the Q and R street corridors,
Pennsylvania avenue, washington and old dominion trail, the mount vernon trail, etc." and
"K street too". The Capital Bikeshare model (`pipeline.bikeshare_corridors`) finds the
rest; these are community knowledge, which outranks a model (the project's source order),
and they reach past the docks (the W&OD, the Mount Vernon Trail's south end).

The list is `fixtures/bike-corridors/` (its README says the format). A way is matched by
name and place, never by id, so an OSM split or renumbering does not stop it applying.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from routemaker.facility import BIKE_LANE_WORDS, PROTECTED_BIKE_LANE_WORDS

logger = logging.getLogger(__name__)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "bike-corridors"

# What a way must be to count for a corridor that is its bike ways only.
BIKE_WAY_HIGHWAYS = frozenset({"cycleway", "path", "footway"})

# The class every way of a named corridor is drawn at (`bike_popular`).
MAJOR_CLASS = 3


@dataclass(frozen=True)
class Corridor:
    id: str
    names: tuple[re.Pattern, ...]
    box: tuple[float, float, float, float]
    # Only the bike ways along the street (its cycle track, by name or by the street it
    # runs beside), not the road itself.
    bike_ways_only: bool = False

    def holds(self, names: Iterable[str | None], point: tuple[float, float]) -> bool:
        return self.matched(names, point) is not None

    def matched(self, names: Iterable[str | None], point: tuple[float, float]) -> str | None:
        """The first of `names` the corridor holds at `point`, or None."""
        west, south, east, north = self.box
        lon, lat = point
        if not (west <= lon <= east and south <= lat <= north):
            return None
        for name in names:
            if name and any(pattern.fullmatch(name.strip()) for pattern in self.names):
                return name.strip()
        return None


def load(directory: Path = FIXTURE_DIR) -> tuple[Corridor, ...]:
    corridors = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("version") != 1:
            raise ValueError(f"{path}: version must be 1")
        for row in data["corridors"]:
            box = tuple(float(v) for v in row["box"])
            if len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError(f"{path}: {row['id']}: box must be [west, south, east, north]")
            corridors.append(
                Corridor(
                    id=row["id"],
                    names=tuple(re.compile(name, re.IGNORECASE) for name in row["names"]),
                    box=box,
                    bike_ways_only=bool(row.get("bike_ways_only", False)),
                )
            )
    return tuple(corridors)


def street_of(sidepath_name: str | None) -> str | None:
    """The street a bike lane beside it is named for ("K Street Northwest protected bike
    lane" -> "K Street Northwest"), or None."""
    if not sidepath_name:
        return None
    for words in (PROTECTED_BIKE_LANE_WORDS, BIKE_LANE_WORDS):
        if sidepath_name.endswith(" " + words):
            return sidepath_name[: -len(words) - 1]
    return None


def middle(coordinates: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    if not coordinates:
        return None
    return tuple(coordinates[len(coordinates) // 2])


def way_ids(
    ways: Iterable[tuple[int, Mapping[str, str], Sequence[tuple[float, float]]]],
    route_names: Mapping[int, str],
    sidepath_names: Mapping[int, str],
    corridors: Sequence[Corridor],
) -> tuple[dict[int, str], dict[str, int]]:
    """The ways in a named corridor, each with the name it matched by (its own, its route's
    or, for a bike way, its street's), and how many ways each corridor took (a corridor at
    0 is warned about: its name is spelt differently in OSM, or it moved)."""
    found: dict[int, str] = {}
    counts = {corridor.id: 0 for corridor in corridors}
    for osm_id, tags, coordinates in ways:
        point = middle(coordinates)
        if point is None:
            continue
        side = street_of(sidepath_names.get(osm_id))
        names = (tags.get("name"), route_names.get(osm_id), side)
        if not any(names):
            continue
        bike_way = side is not None or tags.get("highway") in BIKE_WAY_HIGHWAYS
        for corridor in corridors:
            if corridor.bike_ways_only and not bike_way:
                continue
            name = corridor.matched(names, point)
            if name is not None:
                found.setdefault(osm_id, name)
                counts[corridor.id] += 1
    missing = [name for name, count in counts.items() if count == 0]
    if missing:
        logger.warning(
            "major bike corridors that matched no way (fixtures/bike-corridors/), so they "
            "are not drawn as popular: %s",
            ", ".join(missing),
        )
    return found, counts


def apply(schema: str, ways: Mapping[int, str]) -> int:
    """Put the staging schema's rows of `ways` in MAJOR_CLASS, each named by its corridor
    name where it has no `trail_name` yet, so the map can label it (the owner, 2026-10-23,
    of the zoomed-out map: "the trails should be lableled at this zoom" ... "and the major
    corridors"; `core.stress_tiles.trail_name_rule`). Returns the rows set."""
    from django.db import connection

    from .schema import BIKE_POPULAR_COLUMN, TRAIL_NAME_COLUMN, validate_schema_name

    validate_schema_name(schema)
    if not ways:
        return 0
    ids = sorted(ways)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {schema}.segment AS s SET {BIKE_POPULAR_COLUMN} = %s, "
            f"{TRAIL_NAME_COLUMN} = COALESCE(s.{TRAIL_NAME_COLUMN}, v.name) "
            "FROM unnest(%s::bigint[], %s::text[]) AS v (id, name) WHERE s.osm_way_id = v.id",
            [MAJOR_CLASS, ids, [ways[i] for i in ids]],
        )
        return cursor.rowcount
