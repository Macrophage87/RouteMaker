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

Only where nothing else has spoken: a way with any bicycle key (OSM's own `no`
or `dismount`, an approved override, a direction or a condition) keeps it, and
so does a way with a `vehicle` key or an `access` that is anything but open.
Steps and cycleways keep their own class, and a natural-surface path stays
closed. The sidewalk round a circle's edge is the park's own and opens with its
paths; the CBD's sidewalk rule does not reach National Park Service land
(`routemaker.cbd`). A crossing that touches an opened walkway opens too, so the
walkways meet the street.

The polygons are the NPS parks named "... Circle" in DC GIS's National Parks
layer (NPS Map A, CC BY 4.0), as the federal-land overlay already carries them
(`fixtures/circle_parks/README.md`). A way is inside when the midpoint of its
length is, as for the CBD and the Zoo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from functools import lru_cache
from pathlib import Path

from .cbd import Polygon, in_polygons, load, midpoint
from .trailaccess import is_natural_surface

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "circle_parks"
POLYGON_FILE = FIXTURES / "circle-parks.geojson"

OPENED_HIGHWAY = frozenset({"footway", "path", "pedestrian"})
OPEN_ACCESS = frozenset({"yes", "permissive", "public", "designated", "official"})
# Not one of the park's walkways (a crossing belongs to the street it crosses), but
# opened where it touches one, so the walkways reach the street (`open_ways`).
LINK_FOOTWAY = frozenset({"crossing", "traffic_island"})
BICYCLE = "yes"


@lru_cache(maxsize=1)
def polygons() -> list[Polygon]:
    return load(POLYGON_FILE)


def contains(point: tuple[float, float], areas: list[Polygon] | None = None) -> bool:
    return in_polygons(point, areas if areas is not None else polygons())


def unspoken(tags: dict[str, str]) -> bool:
    """Whether nothing on the way says anything about a bicycle on it, or closes it:
    no `bicycle` key of any kind (`bicycle:forward`, `bicycle:conditional`, ...), no
    `vehicle` or closed `access`, and not a natural surface."""
    if any(key == "bicycle" or key.startswith("bicycle:") for key in tags):
        return False
    if tags.get("vehicle") is not None:
        return False
    access = tags.get("access")
    if access is not None and access not in OPEN_ACCESS:
        return False
    return not is_natural_surface(tags)


def opens(
    tags: dict[str, str],
    coords: Sequence[tuple[float, float]],
    areas: list[Polygon] | None = None,
) -> bool:
    """Whether this way is a circle-park walkway this rule opens to bicycles: the
    park's paths, plazas and the sidewalk round its edge, which is the park's own."""
    if not coords or tags.get("highway") not in OPENED_HIGHWAY:
        return False
    if tags.get("footway") in LINK_FOOTWAY or tags.get("footway") == "access_aisle":
        return False
    return unspoken(tags) and contains(midpoint(coords), areas)


def is_link(tags: dict[str, str]) -> bool:
    """A crossing or traffic island, opened only where it touches an opened walkway."""
    return (
        tags.get("highway") == "footway" and tags.get("footway") in LINK_FOOTWAY and unspoken(tags)
    )


def open_ways(
    ways: Iterable,
    areas: list[Polygon] | None = None,
    rule: Callable[..., bool] | None = None,
) -> set[int]:
    """Write `bicycle=yes` on the working tags of every circle-park walkway the rule
    opens, and of every crossing that touches one (so the walkways meet the street
    instead of being an island the router cannot reach), and return their ids.
    `rule` replaces `opens` for another area's walkways (`routemaker.capitolgrounds`)."""
    rule = rule or opens
    # Only walkways are read past their tags: the rest of the region's ways never are.
    ways = [way for way in ways if way.tags.get("highway") in OPENED_HIGHWAY]
    opened: set[int] = set()
    nodes: set[int] = set()
    for way in ways:
        if rule(way.tags, way.coordinates, areas):
            opened.add(way.osm_id)
            nodes.update(way.node_ids)
    links = {
        way.osm_id
        for way in ways
        if way.osm_id not in opened and is_link(way.tags) and nodes.intersection(way.node_ids)
    }
    for way in ways:
        if way.osm_id in opened or way.osm_id in links:
            way.tags["bicycle"] = BICYCLE
    return opened | links
