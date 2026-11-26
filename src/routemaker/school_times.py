"""School times: a school's grounds and the streets in front of it, read busier while
pupils arrive (the owner, 2026-11-26: "Let's rate school zones higher during the common
times that people travel there. They tend to be high stress").

The case that started it: a commute at about 8 AM was routed round a school's bus loop
(Garden Gate and Middlevale Ln, Wheaton), which the map has at LTS 1 as a quiet drive;
at that hour it carries school buses and a queue of cars dropping children off. The
stress is the traffic of the hour, not the road: buses turning across it, cars stopping
and pulling out, doors opening, children crossing between them. (A single road's crash
records are not used, being too few to rate one road by; studies of school zones as a
type of road may be cited: the owner, 2026-11-26.)

So a piece of road counts as a school piece (`pipeline.school_layer`) where it lies on
the grounds of an OSM `amenity=school` area or within FRONTAGE_M of its edge, and is a
minor road (ROAD_CLASSES): a service road (the bus loop, the drop-off lane, the car
park's aisle) or a residential or unclassified street. A busier road is rated for its
own traffic already, and a path on the grounds keeps riders away from the buses.

Each such road is rated a second time, for school times only, by the raters
(docs/stress/briefs/SCHOOL-TIMES-BRIEF.md; the owner, 2026-11-26: "rerate each area near
a school zone only during peak hours with the agent information that this area is near a
school, give the school location and ask how busy you'd expect the road to be then").
Their levels are kept in RUSH_LEVELS_FILE, a way a row, and written beside the school
pieces at the rebuild. At a school time (SCHOOL_WHENS) the planner's search reads a
school piece at its rush-hour level where that is higher than its own (`raised`), as it
reads a known hazard at LTS 4 (`core.refine`); the map, the graph and the route's colours
keep the road's own level. A road with no rush-hour rating, and every road outside
school times, is unchanged: there is no flat bump.

The numbers below are our defaults, not measured and not from a published source:

- SCHOOL_WHENS: weekday rush (Monday to Friday 07:00-10:00 and 16:00-19:00,
  `routemaker.ridetime`) is the ride setting that holds school arrival (about 7:30 to
  9). Afternoon dismissal (about 2:30 to 4) falls in weekday off-peak, which also holds
  the quiet middle of the day, so it is left out; ride times are four settings and no
  finer. Summer holidays and school closures are not known either.
- FRONTAGE_M: 30 m, about a street's width past the edge of the grounds, so the street
  the drop-off queue stands on counts and the next block does not.
- ON_SCHOOL_M: a piece counts when at least this much of it, or half of it, is on the
  grounds or the frontage, so a street that only touches a corner of the grounds does
  not.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path

from . import ridetime

SCHOOL_WHENS = frozenset({ridetime.WEEKDAY_RUSH})
FRONTAGE_M = 30.0
ON_SCHOOL_M = 50.0
ROAD_CLASSES = frozenset({"service", "residential", "unclassified", "living_street"})
LEVELS = (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)
RUSH_LEVELS_FILE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "school-times" / "rush-levels.csv"
)


class RushLevelsRefused(ValueError):
    """A rush-hour ratings file the rebuild will not read."""


def load(path: Path | str | None = None) -> dict[int, float]:
    """The raters' school-time levels by OSM way id (columns `way_id`, `level`, `why`).
    No file: no ratings yet, and nothing changes."""
    path = Path(path or RUSH_LEVELS_FILE)
    if not path.is_file():
        return {}
    levels: dict[int, float] = {}
    with path.open(newline="") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            try:
                way_id, level = int(row["way_id"]), float(row["level"])
            except (KeyError, TypeError, ValueError) as error:
                raise RushLevelsRefused(f"{path.name} line {line}: {error}") from error
            if level not in LEVELS:
                raise RushLevelsRefused(f"{path.name} line {line}: level {level} is not a level")
            if not (row.get("why") or "").strip():
                raise RushLevelsRefused(f"{path.name} line {line}: a rating needs its why")
            if way_id in levels:
                raise RushLevelsRefused(f"{path.name} line {line}: way {way_id} twice")
            levels[way_id] = level
    return levels


def is_school(tags: Mapping[str, str]) -> bool:
    """Whether an OSM area is a school's grounds."""
    return tags.get("amenity") == "school"


def is_minor_road(tags: Mapping[str, str]) -> bool:
    """Whether a way is a road a school piece can be on (ROAD_CLASSES)."""
    return tags.get("highway") in ROAD_CLASSES


def at_school_time(when: str | None) -> bool:
    """Whether a ride at `when` is in school times."""
    return when in SCHOOL_WHENS


def on_school(piece_m: float, on_m: float) -> bool:
    """Whether a piece `piece_m` long with `on_m` of it on the grounds or the frontage
    counts as a school piece."""
    return piece_m > 0 and (on_m >= ON_SCHOOL_M or on_m >= piece_m / 2)


def raised(
    tier: str, half: bool, facility: str, rush_level: float | None
) -> tuple[str, bool] | None:
    """The (tier, half step) a school piece is read at in school times, or None where it
    stays: no rush-hour rating, a path, a tier that is not known, or a rating no higher
    than the road's own level. Never lowers a road."""
    if rush_level is None or facility == "path" or tier not in ("1", "2", "3", "4", "5"):
        return None
    if rush_level <= int(tier) + (0.5 if half else 0.0):
        return None
    whole = int(rush_level)
    return str(whole), rush_level - whole >= 0.5
