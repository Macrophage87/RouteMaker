"""The military areas a road lies inside, for the stress map.

The owner, 2026-09-29: "Don't show roads that most typical people can't ride
on, such as within military bases, or the pentagon" (OWNER-DECISIONS 88).
Many of the roads inside a base carry no access tag - the Pentagon's
Connector Road, North Rotary Road and Boundary Drive are plain `tertiary` -
so a road is left off the map when it lies inside an area tagged
`landuse=military` or `military=*` (the Pentagon is `landuse=military` +
`military=base` + `access=private`, way 916068128; Joint Base Anacostia
Bolling, Joint Base Myer-Henderson Hall, Fort McNair, Joint Base Andrews,
the Washington Navy Yard are all so tagged). Routing is unaffected: Valhalla
reads the roads' own access tags.

The areas are read from the same source extract as the ways, with
pyosmium's area assembly (multipolygon relations and closed ways alike), and
kept as rings; a road is inside when at least half of its vertices fall in
an area's outer ring and not in one of its holes. Trail-class ways are not
tested: a trail along a base's edge (the Mount Vernon Trail past the
Pentagon, the Anacostia Riverwalk past Bolling) stays, and a private path
inside one is left out by its own access tag (`routemaker.facility.map_class`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import osmium

from routemaker.classes import TRAIL_CLASS_HIGHWAY

Ring = list[tuple[float, float]]
# (bbox, outer rings, inner rings)
Area = tuple[tuple[float, float, float, float], list[Ring], list[Ring]]

# `military` values that are an area a road may lie in; `military=no` is not.
NOT_AN_AREA = frozenset({"no"})

# The share of a road's vertices that must fall inside for it to count as inside.
INSIDE_FRACTION = 0.5


def is_military_area(tags) -> bool:
    return tags.get("landuse") == "military" or (
        tags.get("military") is not None and tags.get("military") not in NOT_AN_AREA
    )


class _Areas(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.areas: list[Area] = []

    def area(self, a) -> None:
        if not is_military_area(a.tags):
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
        self.areas.append(((min(xs), min(ys), max(xs), max(ys)), outers, inners))


def military_areas(pbf: str | Path) -> list[Area]:
    """Every military area in an extract, as rings of (lon, lat)."""
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


def roads_inside(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
    areas: Sequence[Area],
) -> set[int]:
    """The roads (not trail-class ways) at least INSIDE_FRACTION inside a military area."""
    if not areas:
        return set()
    found = set()
    for osm_id, tags, coords in ways:
        highway = tags.get("highway")
        if highway is None or highway in TRAIL_CLASS_HIGHWAY or not coords:
            continue
        inside = sum(1 for p in coords if any(_in_area(p, area) for area in areas))
        if inside >= INSIDE_FRACTION * len(coords):
            found.add(osm_id)
    return found
