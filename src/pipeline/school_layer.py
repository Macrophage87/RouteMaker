"""The school pieces, read from the extract (`routemaker.school_times`; the owner,
2026-11-26).

One pass over the extract with osmium's area assembly finds the schools' grounds
(`amenity=school`, closed ways and multipolygons alike); each is widened by
`school_times.FRONTAGE_M` so the street in front of it is on it too. A segment piece of a
minor road is a school piece where enough of it lies on one (`school_times.on_school`).
Written to `segment.school` (`pipeline.schema.SCHOOL_COLUMN`) and read by the planner's
search alone, at school times (`core.route_schools`). Never a stress input: the map and
the graph keep the road's own level.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import osmium
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid

from routemaker import school_times

logger = logging.getLogger(__name__)

M_PER_DEG = 111_320.0


class _Reader(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.shapes: list = []

    def area(self, a) -> None:  # noqa: N802 - osmium's callback name
        if not school_times.is_school({t.k: t.v for t in a.tags}):
            return
        polygons = []
        for outer in a.outer_rings():
            ring = [(n.lon, n.lat) for n in outer]
            holes = [[(n.lon, n.lat) for n in inner] for inner in a.inner_rings(outer)]
            if len(ring) >= 4:
                polygons.append(Polygon(ring, [h for h in holes if len(h) >= 4]))
        if polygons:
            self.shapes.append(polygons[0] if len(polygons) == 1 else unary_union(polygons))


def widened(shape, metres: float = school_times.FRONTAGE_M):
    """`shape` (lon/lat) widened by `metres` on every side, measured at its own latitude."""
    if not shape.is_valid:
        shape = make_valid(shape)
    scale = math.cos(math.radians(shape.centroid.y)) or 1.0
    flat = affinity.scale(shape, xfact=scale, yfact=1.0, origin=(0, 0))
    grown = flat.buffer(metres / M_PER_DEG)
    return affinity.scale(grown, xfact=1.0 / scale, yfact=1.0, origin=(0, 0))


def read(pbf: str | Path) -> STRtree | None:
    """The schools' grounds of the extract, each widened by the frontage, in a tree; None
    where the extract has none."""
    reader = _Reader()
    reader.apply_file(str(pbf), locations=True)
    logger.info("school grounds: %d", len(reader.shapes))
    if not reader.shapes:
        return None
    return STRtree([widened(shape) for shape in reader.shapes])


def piece_metres(piece: Sequence[tuple[float, float]]) -> float:
    """A piece's length in metres (flat, at each step's own latitude)."""
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(piece, piece[1:], strict=False):
        dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2)) * M_PER_DEG
        dy = (lat2 - lat1) * M_PER_DEG
        total += math.hypot(dx, dy)
    return total


def is_school_piece(
    tags: Mapping[str, str], piece: Sequence[tuple[float, float]], tree: STRtree | None
) -> bool:
    """Whether a segment piece of a way with `tags` is a school piece."""
    if tree is None or len(piece) < 2 or not school_times.is_minor_road(tags):
        return False
    line = LineString(piece)
    if line.length == 0:
        return False
    on = 0.0
    for index in tree.query(line):
        on += line.intersection(tree.geometries[index]).length
    share = min(on / line.length, 1.0)
    metres = piece_metres(piece)
    return school_times.on_school(metres, share * metres)
