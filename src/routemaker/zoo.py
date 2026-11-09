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
  signed for bicycles (8 ways, 1.7 km). The test is broad enough that an OSM
  retag of a piece does not cut the trail at the Zoo (hunt A5, 2026-11-08): a
  cycleway or path with `bicycle=designated` or `yes` (OSM draws a shared-use
  path either way), or a trail-class way carrying a through trail's name
  (`through_trails` in the fixture) that its own tags do not bar bicycles from,
  so a bare `highway=cycleway name=Rock Creek Trail` stays open too;
- a short access spur from the Harvard Street NW entrance to the bike racks
  (`fixtures/zoo/zoo-access.json`), routable as a destination-only connector
  (`rm:destination_only=zoo`): a route may end on it and may not pass over it.

Nothing routes through the Zoo, and a destination inside it is moved to the
racks (`redirect`), so "a route to the Zoo ends at the racks".

A way is inside when the midpoint of its length is, as for the CBD
(`routemaker.cbd`), and the spur is named by way id: the Zoo's footways are
one OSM way each for hundreds of metres, and a way cannot be opened in part.

The rebuild checks the rule against the extract (`check`, run by
`pipeline.run.assert_zoo_rule` in VALIDATE_SEGMENTS): every spur way is still
there, a piece of the Rock Creek Trail inside the outline is open, and at least
`open_trail_floor` trail ways inside it are. A renumbered spur way or a retagged
or renamed trail fails the rebuild rather than silently ending "route to the Zoo"
short of the racks or cutting the Rock Creek Trail.

The policy itself, that the Zoo bars bicycles on its grounds, is the owner's
decision as stated; the Smithsonian's visitor rules were not fetched, and no
user-facing text cites them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path

from .cbd import Polygon, in_polygons, load, midpoint

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "zoo"
POLYGON_FILE = FIXTURES / "national-zoo.geojson"
ACCESS_FILE = FIXTURES / "zoo-access.json"

NO_BICYCLE = "zoo"
ROCK_CREEK_TRAIL = "Rock Creek Trail"
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


def through_trail(tags: dict[str, str]) -> bool:
    """A trail-class way named for one of the through trails the Zoo keeps open
    (the Rock Creek Trail, the Zoo Loop Trail), whatever else it is tagged."""
    trail = access()["open_trail"]
    return tags.get("highway") in trail["named_highways"] and tags.get("name") in set(
        trail["through_trails"]
    )


def is_open_way(tags: dict[str, str]) -> bool:
    """A way inside the Zoo's outline that stays open: a public street, a
    cycleway or path signed for bicycles, or a through trail by name that its own
    tags do not bar bicycles from (`through_trail`)."""
    spec = access()
    if tags.get("highway") in spec["open_highways"]:
        return True
    trail = spec["open_trail"]
    if tags.get("highway") in trail["highways"] and tags.get("bicycle") in trail["bicycle"]:
        return True
    return through_trail(tags) and not any(
        tags.get(key) in trail["barring"] for key in ("access", "bicycle")
    )


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


@lru_cache(maxsize=1)
def _box() -> tuple[float, float, float, float]:
    xs = [x for p in polygon() for x, _ in p[0]]
    ys = [y for p in polygon() for _, y in p[0]]
    return min(xs), min(ys), max(xs), max(ys)


def inside(coords: Sequence[tuple[float, float]]) -> bool:
    """The way's midpoint is inside the Zoo (cheaply false for a way nowhere near it)."""
    if not coords:
        return False
    west, south, east, north = _box()
    if not any(west <= x <= east and south <= y <= north for x, y in coords):
        return False
    return contains(midpoint(coords))


def check(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
    no_bicycle: Mapping[int, str],
) -> list[str]:
    """What is wrong with the Zoo rule on this extract, as sentences (empty when
    nothing is, or when the extract has no way inside the Zoo: a test's, or a
    region without it). A spur way the extract no longer has (renumbered upstream,
    so the route to the racks ends short or fails); no piece of the Rock Creek
    Trail inside the outline open (renamed or retagged upstream past what
    `is_open_way` reads); fewer open trail-class ways inside it, the spur aside, than the fixture's
    `open_trail_floor` (the trail or the Zoo Loop Trail lost a piece the same way)."""
    present: set[int] = set()
    within = []
    for osm_id, tags, coords in ways:
        present.add(osm_id)
        if tags.get("highway") and inside(coords):
            within.append((osm_id, tags))
    if not within:
        return []
    problems = []
    gone = sorted(spur_ways() - present)
    if gone:
        problems.append(
            f"Zoo spur ways {gone} are not in the extract (renumbered upstream?): refresh "
            "fixtures/zoo/zoo-access.json, or a route to the Zoo ends short of the racks"
        )
    trail = access()["open_trail"]
    open_trail = [
        (osm_id, tags)
        for osm_id, tags in within
        if tags.get("highway") in trail["named_highways"]
        and no_bicycle.get(osm_id) is None
        and osm_id not in spur_ways()
    ]
    if not any(tags.get("name") == ROCK_CREEK_TRAIL for _osm_id, tags in open_trail):
        problems.append(
            "no piece of the Rock Creek Trail inside the Zoo is open: it was renamed or "
            "retagged upstream, so the trail is cut at the Zoo (routemaker.zoo.is_open_way)"
        )
    floor = int(trail["open_trail_floor"])
    if len(open_trail) < floor:
        problems.append(
            f"{len(open_trail)} open trail ways inside the Zoo, fewer than its floor of {floor} "
            "(fixtures/zoo/zoo-access.json open_trail_floor): a Rock Creek Trail or Zoo Loop "
            "Trail piece was retagged upstream and closed by the Zoo rule"
        )
    return problems
