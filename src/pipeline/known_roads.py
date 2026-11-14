"""Roads the owner has called, read back at VALIDATE_SEGMENTS (backlog 2026-11-12, stress
ratings item 5).

The owner has named the level of many roads he rides ("Most of Conn Ave is LTS4",
"Darnestown makes sense at 4.5", "Aspen Street ... Probably a 2.5"). Most of those calls live in
override rows, and an override row is matched to its way by id and fingerprint. When OSM
splits or redraws a way the row can stop reaching it, and the road quietly takes the
formula's level again: Peach Tree Rd went from 2 to 4 that way. This check reads each
called road back from the built table by where it is, not by way id, so a road that no
longer carries the owner's level is listed before the build is promoted, as the Connecticut
Ave sentinel's is (`pipeline.lts_sentinels`). Since 2026-11-13 a gap is listed for the raters,
not refused (`REBUILD_OWNER_CALLS_REFUSE`; the owner: "Ignore my own calls"); a stretch whose
rows are gone still refuses the build.

The roads are in `fixtures/known-roads/known-roads.json`, one entry per stretch:

- `road` and `where`: the stretch in words (shown in the refusal).
- `level`: the owner's level, 1 to 4.5 in half steps, 5 for Avoid.
- `at_least`: true when the owner gave a floor ("at least an LTS3"); the stretch holds
  at that level or above.
- `min_share`: the share of the stretch's length that must carry the level.
- `decision`: where the owner said it (an OWNER-DECISIONS number or a dated quote).
- `line`: the stretch's centre line, "lon,lat lon,lat ...", WGS 84; a stretch in several
  pieces (a divided road, a road with a gap) separates them with " | ".

A segment row belongs to a stretch when it is drawn as a road (`map_class` 'road', not
a trail-class way, so a side path beside it never counts) and most of it lies within
`NEAR_M` of the line. Cross streets touch the line only at their ends, so they fall
short of `ROW_INSIDE_SHARE`. The stretch also has to be found: if the rows near the line
add up to less than `FOUND_SHARE` of the line's length, the road has moved, been
renamed or lost its rows, and that is reported as well.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from django.db import connection

from .schema import validate_schema_name

# How far from the stretch's line a row may lie, metres: a carriageway of a divided
# road is about 10 m off the centre line drawn between them.
NEAR_M = 15.0
# The share of a row's length that must be inside that band for the row to count.
ROW_INSIDE_SHARE = 0.6
# The share of the line's length the counted rows must cover for the stretch to be
# found at all (a divided road's two carriageways cover it twice).
FOUND_SHARE = 0.5

_SQL = """
WITH line AS (
    SELECT ST_SetSRID(ST_GeomFromText(%s), 4326) AS geom
), band AS (
    SELECT ST_Buffer(geom::geography, %s)::geometry AS geom, geom AS line FROM line
), rows AS (
    SELECT ST_Length(s.geometry::geography) AS len,
           -- A grid size (1e-9 degrees, about 0.1 mm) snap-rounds the overlay: without it
           -- GEOS 3.9, in the pinned postgis/postgis:16-3.4 image, returns an empty line for a
           -- row lying exactly on the stretch's line, so the stretch read 0 m.
           ST_Length(ST_Intersection(s.geometry, band.geom, 1e-9)::geography) AS inside,
           s.stress_tier + CASE WHEN s.stress_half THEN 0.5 ELSE 0 END AS level
    FROM {schema}.segment AS s, band
    WHERE s.map_class = 'road' AND NOT s.is_trail_class
      AND ST_Intersects(s.geometry, band.geom)
)
SELECT COALESCE(sum(len), 0),
       COALESCE(sum(len) FILTER (WHERE {held}), 0),
       (SELECT ST_Length(geom::geography) FROM line)
FROM rows
WHERE len > 0 AND inside >= %s * len
"""


@dataclass(frozen=True)
class KnownRoad:
    """One stretch the owner gave a level (see the module's docstring)."""

    road: str
    where: str
    level: float
    at_least: bool
    min_share: float
    decision: str
    line: tuple[tuple[tuple[float, float], ...], ...]

    @classmethod
    def of(cls, entry: dict) -> KnownRoad:
        parts = tuple(
            tuple(
                (float(lon), float(lat)) for lon, lat in (pair.split(",") for pair in part.split())
            )
            for part in str(entry["line"]).split("|")
        )
        level = float(entry["level"])
        if level * 2 != int(level * 2) or not 1 <= level <= 5:
            raise ValueError(f"{entry['road']}: level {level} is not 1 to 5 in half steps")
        if not parts or any(len(part) < 2 for part in parts):
            raise ValueError(f"{entry['road']}: each piece of a line needs two points")
        return cls(
            road=str(entry["road"]),
            where=str(entry.get("where", "")),
            level=level,
            at_least=bool(entry.get("at_least", False)),
            min_share=float(entry["min_share"]),
            decision=str(entry["decision"]),
            line=parts,
        )

    @property
    def wkt(self) -> str:
        return (
            "MULTILINESTRING ("
            + ", ".join(
                "(" + ", ".join(f"{lon} {lat}" for lon, lat in part) + ")" for part in self.line
            )
            + ")"
        )

    @property
    def name(self) -> str:
        return f"{self.road} ({self.where})" if self.where else self.road

    @property
    def wanted(self) -> str:
        return f"{_level(self.level)} or higher" if self.at_least else _level(self.level)


@dataclass(frozen=True)
class KnownRoadTiers:
    """The stretch's rows read back: all of them, those at the owner's level, and the
    length of the stretch's own line, metres."""

    road: KnownRoad
    total_m: float
    held_m: float
    line_m: float

    @property
    def share(self) -> float:
        return self.held_m / self.total_m if self.total_m else 0.0


def _level(level: float) -> str:
    return "Avoid" if level >= 5 else f"LTS {level:g}"


def _mi(metres: float) -> str:
    return f"{metres / 1609.344:.2f} mi ({metres / 1000:.2f} km)"


def load(path: Path | str) -> list[KnownRoad]:
    """The fixture's stretches; an empty path is no stretches (the test suite's)."""
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [KnownRoad.of(entry) for entry in data["roads"]]


def read(schema: str, road: KnownRoad) -> KnownRoadTiers:
    """Read the stretch's rows back from the built table."""
    schema = validate_schema_name(schema)
    held = "level >= %s" if road.at_least else "level = %s"
    sql = _SQL.format(schema=schema, held=held)
    with connection.cursor() as cursor:
        cursor.execute(sql, [road.wkt, NEAR_M, road.level, ROW_INSIDE_SHARE])
        total, at_level, line = (float(value or 0) for value in cursor.fetchone())
    return KnownRoadTiers(road, total, at_level, line)


def unread(tiers: KnownRoadTiers) -> bool:
    """Too few road rows lie along the stretch's line to check it at all: the road moved,
    was renamed or lost its rows. Refuses the build whatever `REBUILD_OWNER_CALLS_REFUSE`."""
    return tiers.total_m < FOUND_SHARE * tiers.line_m


def problems(tiers: KnownRoadTiers) -> list[str]:
    """What is wrong with the stretch, in words; empty when it holds."""
    road = tiers.road
    if unread(tiers):
        return [
            f"{road.name}: only {_mi(tiers.total_m)} of road rows lie along its "
            f"{_mi(tiers.line_m)} line, so the owner's {road.wanted} ({road.decision}) "
            "could not be checked; the road moved, was renamed or lost its rows: redraw "
            "its line in fixtures/known-roads/known-roads.json"
        ]
    if tiers.share < road.min_share:
        return [
            f"{road.name}: only {tiers.share:.0%} ({_mi(tiers.held_m)} of "
            f"{_mi(tiers.total_m)}) is at {road.wanted}, under {road.min_share:.0%}; the "
            f"owner called it {road.wanted} ({road.decision}). An override row that no "
            "longer reaches its way (rematch) is the usual cause"
        ]
    return []


def check(schema: str, roads: Sequence[KnownRoad]) -> tuple[list[str], list[KnownRoadTiers]]:
    """Every stretch read back: the problems found and what was read."""
    found: list[str] = []
    read_back: list[KnownRoadTiers] = []
    for road in roads:
        tiers = read(schema, road)
        read_back.append(tiers)
        found.extend(problems(tiers))
    return found, read_back
