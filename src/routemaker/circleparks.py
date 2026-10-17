"""Bicycles on the paths inside DC's circle parks.

The owner, 2026-10-17, on routes that never use the entrances into Dupont
Circle: "People still need to get into the circle. It's a common riding
destination.", "The CFR does not say that they are prohited. Also, dupont circle
is very much adjacent to a roadway", "In practice people bike through it and
it's never been enforced that way.", "Same with logan circle" and "In general
the circle parks are open to bikes in DC. This is an incredibly common activity
and doesn't have a clearly defined "no", so we should keep them open."

So the walkways inside the National Park Service's circle parks are open to
bicycles. OSM maps them as `highway=footway` with no bicycle tag, which
upstream's transform closes by class, so a route could neither enter a circle
nor end inside one. The rebuild writes `bicycle=yes` on the working tags of each
such way (as an approved access override would), so every graph, the map and
the route description read the same value.

Only where nothing else has spoken: a way with any bicycle tag (OSM's own
`no` or `dismount`, or an approved override) keeps it, and so does a way whose
`access` is anything but open. A sidewalk (`footway=sidewalk`, ...) is left to
the CBD rule (`routemaker.cbd`), a crossing to the street it crosses, steps and
cycleways to their own class, and a natural-surface path stays closed.

The polygons are the NPS parks named "... Circle" in DC GIS's National Parks
layer (NPS Map A, CC BY 4.0), as the federal-land overlay already carries them
(`fixtures/circle_parks/README.md`). A way is inside when the midpoint of its
length is, as for the CBD and the Zoo.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path

from .cbd import Polygon, in_polygons, is_sidewalk, load, midpoint
from .trailaccess import is_natural_surface

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "circle_parks"
POLYGON_FILE = FIXTURES / "circle-parks.geojson"

OPENED_HIGHWAY = frozenset({"footway", "path", "pedestrian"})
OPEN_ACCESS = frozenset({"yes", "permissive", "public", "designated", "official"})
# Not a walkway of the park: a crossing belongs to the street it crosses.
NOT_WALKWAY_FOOTWAY = frozenset({"crossing", "traffic_island", "access_aisle"})
BICYCLE = "yes"


@lru_cache(maxsize=1)
def polygons() -> list[Polygon]:
    return load(POLYGON_FILE)


def contains(point: tuple[float, float], areas: list[Polygon] | None = None) -> bool:
    return in_polygons(point, areas if areas is not None else polygons())


def opens(
    tags: dict[str, str],
    coords: Sequence[tuple[float, float]],
    areas: list[Polygon] | None = None,
) -> bool:
    """Whether this way is a circle-park walkway this rule opens to bicycles."""
    if not coords or tags.get("highway") not in OPENED_HIGHWAY:
        return False
    if tags.get("bicycle") is not None:
        return False
    access = tags.get("access")
    if access is not None and access not in OPEN_ACCESS:
        return False
    if is_sidewalk(tags) or tags.get("footway") in NOT_WALKWAY_FOOTWAY:
        return False
    if is_natural_surface(tags):
        return False
    return contains(midpoint(coords), areas)


def open_ways(ways: Iterable, areas: list[Polygon] | None = None) -> set[int]:
    """Write `bicycle=yes` on the working tags of every circle-park walkway the
    rule opens, and return their ids."""
    opened: set[int] = set()
    for way in ways:
        if opens(way.tags, way.coordinates, areas):
            way.tags["bicycle"] = BICYCLE
            opened.add(way.osm_id)
    return opened
