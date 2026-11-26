"""School times: a school's grounds and the streets in front of it, read busier while
pupils arrive (the owner, 2026-11-26: "Let's rate school zones higher during the common
times that people travel there. They tend to be high stress").

The case that started it: a commute at about 8 AM was routed round a school's bus loop
(Garden Gate and Middlevale Ln, Wheaton), which the map has at LTS 1 as a quiet drive;
at that hour it carries school buses and a queue of cars dropping children off. The
stress is the traffic of the hour, not the road: buses turning across it, cars stopping
and pulling out, doors opening, children crossing between them. (Crash records are not a
reason here: the project does not rate roads by them, 2026-11-13.)

So a piece of road counts as a school piece (`pipeline.school_layer`) where it lies on
the grounds of an OSM `amenity=school` area or within FRONTAGE_M of its edge, and is a
minor road (ROAD_CLASSES): a service road (the bus loop, the drop-off lane, the car
park's aisle) or a residential or unclassified street. A busier road is rated for its
own traffic already, and a path on the grounds keeps riders away from the buses.

At a school time (SCHOOL_WHENS) the planner's search reads a school piece at LTS 3 at
least (`priced`), as it reads a known hazard at LTS 4 (`core.refine`); the map, the
graph and the route's colours keep the road's own level. Outside school times nothing
changes.

The numbers are our defaults, not measured and not from a published source:

- SCHOOL_WHENS: weekday rush (Monday to Friday 07:00-10:00 and 16:00-19:00,
  `routemaker.ridetime`) is the ride setting that holds school arrival (about 7:30 to
  9). Afternoon dismissal (about 2:30 to 4) falls in weekday off-peak, which also holds
  the quiet middle of the day, so it is left out; ride times are four settings and no
  finer. Summer holidays and school closures are not known either: the bump holds on
  every weekday in rush hour.
- SCHOOL_TIER: LTS 3, the level of riding in mixed traffic that most riders avoid.
- FRONTAGE_M: 30 m, about a street's width past the edge of the grounds, so the street
  the drop-off queue stands on counts and the next block does not.
- ON_SCHOOL_M: a piece counts when at least this much of it, or half of it, is on the
  grounds or the frontage, so a street that only touches a corner of the grounds does
  not.
"""

from __future__ import annotations

from collections.abc import Mapping

from . import ridetime

SCHOOL_WHENS = frozenset({ridetime.WEEKDAY_RUSH})
SCHOOL_TIER = "3"
FRONTAGE_M = 30.0
ON_SCHOOL_M = 50.0
ROAD_CLASSES = frozenset({"service", "residential", "unclassified", "living_street"})


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


def raised_tier(tier: str, facility: str) -> str | None:
    """The tier a school piece is read at in school times, or None where it stays: a path
    never changes, nor a road at SCHOOL_TIER or above, nor one whose tier is unknown."""
    if facility == "path" or tier not in ("1", "2"):
        return None
    return SCHOOL_TIER
