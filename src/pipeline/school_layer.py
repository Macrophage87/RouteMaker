"""The school pieces, read from the extract (`routemaker.school_times`; the owner,
2026-11-26).

One pass over the extract with osmium's area assembly finds the schools' grounds
(`amenity=school`, closed ways and multipolygons alike); each is widened by
`school_times.FRONTAGE_M` so the street in front of it is on it too. A segment piece of a
minor road is a school piece where enough of it lies on one (`school_times.on_school`).
A school piece of a way the raters rated for school times (`school_times.load`) has that
level written to `segment.school_rush_level` (`pipeline.schema.SCHOOL_COLUMN`), read by the
planner's search alone, at school times (`core.route_schools`). Never a stress input: the
map and the graph keep the road's own level.

`python -m pipeline.school_layer EXTRACT.osm.pbf OUT.csv` lists the ways to rate: each way
with a school piece, the school beside it and where that is
(docs/stress/briefs/SCHOOL-TIMES-BRIEF.md).
"""

from __future__ import annotations

import csv
import logging
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import osmium
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid

from routemaker import school_times

from . import extract

logger = logging.getLogger(__name__)

M_PER_DEG = 111_320.0


@dataclass
class School:
    osm: str
    name: str
    shape: object  # shapely (Multi)Polygon, lon/lat


class _Reader(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.schools: list[School] = []

    def area(self, a) -> None:  # noqa: N802 - osmium's callback name
        tags = {t.k: t.v for t in a.tags}
        if not school_times.is_school(tags):
            return
        polygons = []
        for outer in a.outer_rings():
            ring = [(n.lon, n.lat) for n in outer]
            holes = [[(n.lon, n.lat) for n in inner] for inner in a.inner_rings(outer)]
            if len(ring) >= 4:
                polygons.append(Polygon(ring, [h for h in holes if len(h) >= 4]))
        if polygons:
            self.schools.append(
                School(
                    osm=f"{'way' if a.from_way() else 'relation'}/{a.orig_id()}",
                    name=tags.get("name") or "",
                    shape=polygons[0] if len(polygons) == 1 else unary_union(polygons),
                )
            )


def widened(shape, metres: float = school_times.FRONTAGE_M):
    """`shape` (lon/lat) widened by `metres` on every side, measured at its own latitude."""
    if not shape.is_valid:
        shape = make_valid(shape)
    scale = math.cos(math.radians(shape.centroid.y)) or 1.0
    flat = affinity.scale(shape, xfact=scale, yfact=1.0, origin=(0, 0))
    grown = flat.buffer(metres / M_PER_DEG)
    return affinity.scale(grown, xfact=1.0 / scale, yfact=1.0, origin=(0, 0))


def read_schools(pbf: str | Path) -> list[School]:
    """The schools' grounds of the extract."""
    reader = _Reader()
    reader.apply_file(str(pbf), locations=True)
    logger.info("school grounds: %d", len(reader.schools))
    return reader.schools


def tree_of(schools: Sequence[School]) -> STRtree | None:
    """The schools' grounds, each widened by the frontage, in a tree (in `schools`' order);
    None where there are none."""
    return STRtree([widened(school.shape) for school in schools]) if schools else None


def read(pbf: str | Path) -> STRtree | None:
    """The extract's schools' grounds, widened, in a tree (`tree_of`)."""
    return tree_of(read_schools(pbf))


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


CANDIDATE_COLUMNS = (
    "way_id",
    "name",
    "highway",
    "service",
    "school",
    "school_osm",
    "school_lat",
    "school_lon",
)


def candidates(ways: Sequence, schools: Sequence[School]) -> list[dict]:
    """A row for each way with a school piece, with the school it is beside (the nearest
    whose widened grounds it touches): what the raters are given."""
    tree = tree_of(schools)
    rows = []
    for way in ways:
        if not any(
            is_school_piece(way.tags, piece, tree) for _, piece in extract.iter_segments(way)
        ):
            continue
        line = LineString(way.coordinates)
        near = tree.query(line)
        school = min((schools[i] for i in near), key=lambda s: s.shape.distance(line))
        centre = school.shape.centroid
        rows.append(
            {
                "way_id": way.osm_id,
                "name": way.tags.get("name", ""),
                "highway": way.tags.get("highway", ""),
                "service": way.tags.get("service", ""),
                "school": school.name,
                "school_osm": school.osm,
                "school_lat": round(centre.y, 6),
                "school_lon": round(centre.x, 6),
            }
        )
    return rows


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m pipeline.school_layer EXTRACT.osm.pbf OUT.csv", file=sys.stderr)
        return 2
    pbf, out = argv
    schools = read_schools(pbf)
    ways = extract.read_ways(pbf, keep=school_times.is_minor_road)
    rows = candidates(ways, schools)
    with open(out, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} ways beside {len(schools)} schools written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
