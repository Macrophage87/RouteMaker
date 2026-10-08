"""Bicycles and the National Zoological Park.

OWNER-DECISIONS 278 and 291(4): "there's still some paths you can't bike on
included, like the paths at the zoo", then "Bikes can go into the zoo for a
little bit. Riding from the Harvard Street Entrance to the bike racks for
instance. I'm not sure if there's any other reason to ride further." So the
Zoo's polygon (OSM area 21022241, `fixtures/zoo/national-zoo.geojson`, beside
the CBD's) is closed to bicycles, `rm:no_bicycle=zoo`, and these stay:

- the public streets that run along and through its edge (Beach Drive,
  Connecticut Avenue, Adams Mill Road, Harvard Street: primary to residential);
- the Rock Creek Trail's edge pieces and the Zoo Loop Trail, `highway=cycleway`
  signed for bicycles (8 ways, 1.7 km);
- a short access spur from the Harvard Street NW entrance to the bike racks
  (`fixtures/zoo/zoo-access.json`), routable as a destination-only connector
  (`rm:destination_only=zoo`): a route may end on it and may not pass over it.

Nothing routes through the Zoo, and a destination inside it is moved to the
racks (`redirect`), so "a route to the Zoo ends at the racks".

A way is inside when the midpoint of its length is, as for the CBD
(`routemaker.cbd`), and the spur is named by way id: the Zoo's footways are
one OSM way each for hundreds of metres, and a way cannot be opened in part.

The policy itself, that the Zoo bars bicycles on its grounds, is the owner's
decision as stated; the Smithsonian's visitor rules were not fetched, and no
user-facing text cites them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from .cbd import Polygon, in_polygons, load, midpoint

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "zoo"
POLYGON_FILE = FIXTURES / "national-zoo.geojson"
ACCESS_FILE = FIXTURES / "zoo-access.json"

NO_BICYCLE = "zoo"
DESTINATION_ONLY = "zoo"


@lru_cache(maxsize=1)
def polygon() -> list[Polygon]:
    return load(POLYGON_FILE)


@lru_cache(maxsize=1)
def access() -> dict:
    return json.loads(ACCESS_FILE.read_text())


def spur_ways() -> frozenset[int]:
    """The ways of the destination-only spur from the Harvard Street entrance to the racks."""
    return frozenset(int(way["id"]) for way in access()["spur"]["ways"])


def racks() -> tuple[float, float]:
    """(lon, lat) of the bike racks the spur ends at."""
    spec = access()["spur"]["racks"]
    return float(spec["lon"]), float(spec["lat"])


def contains(point: tuple[float, float], polygons: list[Polygon] | None = None) -> bool:
    return in_polygons(point, polygons if polygons is not None else polygon())


def redirect(lon: float, lat: float) -> tuple[float, float] | None:
    """Where a trip point inside the Zoo is moved to (the racks), or None when
    it is outside: a route to the Zoo ends at the racks (OWNER-DECISIONS 291(4))."""
    return racks() if contains((lon, lat)) else None


def is_open_way(tags: dict[str, str]) -> bool:
    """A way inside the Zoo's outline that stays open: a public street, or a
    cycleway signed for bicycles."""
    spec = access()
    if tags.get("highway") in spec["open_highways"]:
        return True
    trail = spec["open_trail"]
    return tags.get("highway") == trail["highway"] and tags.get("bicycle") in trail["bicycle"]


def closed_way(
    osm_id: int,
    tags: dict[str, str],
    coords: Sequence[tuple[float, float]],
    polygons: list[Polygon] | None = None,
) -> bool:
    """Whether this way is inside the Zoo, closed to bicycles, and not the spur."""
    if not coords or not tags.get("highway") or osm_id in spur_ways():
        return False
    if not contains(midpoint(coords), polygons):
        return False
    return not is_open_way(tags)
