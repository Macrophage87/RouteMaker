"""The areas a way lies inside that change how the stress map draws it, and how
a bicycle may route through it.

Three kinds, read from the same source extract as the ways with pyosmium's
area assembly (multipolygon relations and closed ways alike):

- `military` - `landuse=military` or `military=*`. The owner, 2026-09-29:
  "Don't show roads that most typical people can't ride on, such as within
  military bases, or the pentagon" (OWNER-DECISIONS 88). Many roads inside a
  base carry no access tag of their own (the Pentagon's Connector Road and
  North Rotary Road are plain `tertiary`); the Pentagon itself is
  `landuse=military` + `military=base` (way 916068128). Its roads - not its
  trail-class ways - are left off the map.
- `cemetery` - `landuse=cemetery` or `amenity=grave_yard`. The owner: "There's
  a lot of cemetary roads, such as arlington national cemetary. We shouldn't
  have these roads on here, even if some of them can be technically ridden. I
  don't want to encourage a cemetary cut through as it's disrespectful." (98).
  Every road and path inside one is left off the map, and routed only to or
  from a point inside it (destination-only, through `rm:cemetery`); a trail
  signed for bicycles (`bicycle=designated`) keeps its place.
- `parking` - `amenity=parking`, or `parking=surface` or `multi-storey`. The
  owner: "Also, no need to stripe through all the parking lots." (99). The
  unnamed service roads, footways and paths inside a lot are left off the map;
  routing is unchanged, since a lot can be a fair connector.

A way is inside when at least INSIDE_FRACTION of its vertices fall in one of
the kind's areas, outside that area's holes. So a road or a trail that only
borders an area - the Mount Vernon Trail by Arlington National Cemetery and
the Pentagon, a street past a parking lot - is not inside it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

import osmium

from routemaker.classes import TRAIL_CLASS_HIGHWAY

Ring = list[tuple[float, float]]
# (bbox, outer rings, inner rings)
Area = tuple[tuple[float, float, float, float], list[Ring], list[Ring]]

MILITARY, CEMETERY, PARKING = "military", "cemetery", "parking"
KINDS = (MILITARY, CEMETERY, PARKING)

# The share of a way's vertices that must fall inside for it to count as inside.
INSIDE_FRACTION = 0.5

# `military` values that are no area a road may lie in.
NOT_A_MILITARY_AREA = frozenset({"no"})
PARKING_VALUES = frozenset({"surface", "multi-storey"})

# The grid cell the areas are indexed by, in degrees (about 1.1 km).
CELL = 0.01


def area_kind(tags) -> str | None:
    """The kind of area a closed way or a multipolygon is, or None."""
    if tags.get("landuse") == "military" or (
        tags.get("military") is not None and tags.get("military") not in NOT_A_MILITARY_AREA
    ):
        return MILITARY
    if tags.get("landuse") == "cemetery" or tags.get("amenity") == "grave_yard":
        return CEMETERY
    if tags.get("amenity") == "parking" or tags.get("parking") in PARKING_VALUES:
        return PARKING
    return None


def is_military_area(tags) -> bool:
    return area_kind(tags) == MILITARY


class _Areas(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.areas: dict[str, list[Area]] = {kind: [] for kind in KINDS}

    def area(self, a) -> None:
        kind = area_kind(a.tags)
        if kind is None:
            return
        outers: list[Ring] = []
        inners: list[Ring] = []
        for outer in a.outer_rings():
            outers.append([(n.lon, n.lat) for n in outer])
            for inner in a.inner_rings(outer):
                inners.append([(n.lon, n.lat) for n in inner])
        points = [p for ring in outers for p in ring]
        if not points:
            return
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        self.areas[kind].append(((min(xs), min(ys), max(xs), max(ys)), outers, inners))


def restricted_areas(pbf: str | Path) -> dict[str, list[Area]]:
    """Every military, cemetery and parking area in an extract, by kind."""
    handler = _Areas()
    handler.apply_file(str(pbf), locations=True)
    return handler.areas


def _in_ring(point: tuple[float, float], ring: Ring) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=False):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _in_area(point: tuple[float, float], area: Area) -> bool:
    (west, south, east, north), outers, inners = area
    x, y = point
    if not (west <= x <= east and south <= y <= north):
        return False
    return any(_in_ring(point, r) for r in outers) and not any(_in_ring(point, r) for r in inners)


class _Index:
    """The areas by grid cell, so a point is tested against the few near it."""

    def __init__(self, areas: Sequence[Area]) -> None:
        self.cells: dict[tuple[int, int], list[Area]] = defaultdict(list)
        for area in areas:
            west, south, east, north = area[0]
            for gx in range(int(west // CELL), int(east // CELL) + 1):
                for gy in range(int(south // CELL), int(north // CELL) + 1):
                    self.cells[(gx, gy)].append(area)

    def contains(self, point: tuple[float, float]) -> bool:
        near = self.cells.get((int(point[0] // CELL), int(point[1] // CELL)), ())
        return any(_in_area(point, area) for area in near)


def _inside(coords: Sequence[tuple[float, float]], index: _Index) -> bool:
    return bool(coords) and sum(1 for p in coords if index.contains(p)) >= INSIDE_FRACTION * len(
        coords
    )


def ways_inside(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
    areas: Sequence[Area],
    counts,
) -> set[int]:
    """The ways `counts(tags)` asks about that lie inside one of `areas`."""
    if not areas:
        return set()
    index = _Index(areas)
    return {
        osm_id
        for osm_id, tags, coords in ways
        if tags.get("highway") is not None and counts(tags) and _inside(coords, index)
    }


def _road(tags) -> bool:
    return tags.get("highway") not in TRAIL_CLASS_HIGHWAY


def _not_a_signed_trail(tags) -> bool:
    return tags.get("bicycle") != "designated"


def _lot_way(tags) -> bool:
    """A lot's own ways: its unnamed service roads, footways and paths. A named
    way inside a lot's outline - the Ellipse Road, Capitol Circle Drive (a
    car-free road, OWNER-DECISIONS 67) - is a street of its own and stays."""
    if tags.get("name") or tags.get("bicycle") == "designated":
        return False
    return tags.get("highway") in ("service", "footway", "path", "pedestrian", "steps")


def roads_inside(ways, areas: Sequence[Area]) -> set[int]:
    """The roads (not trail-class ways) inside a military area."""
    return ways_inside(ways, areas, _road)


def cemetery_ways(ways, areas: Sequence[Area]) -> set[int]:
    """Every road and path inside a cemetery, a trail signed for bicycles aside."""
    return ways_inside(ways, areas, _not_a_signed_trail)


def parking_ways(ways, areas: Sequence[Area]) -> set[int]:
    """A parking lot's own ways inside it."""
    return ways_inside(ways, areas, _lot_way)
