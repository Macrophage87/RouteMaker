"""The beach path, read from the extract (`routemaker.beaches`; the owner, 2026-11-23).

One pass over the extract with osmium's area assembly finds the beaches (`natural=beach`,
closed ways and multipolygons alike) and the coastline ways in a box; each coastline way's
longest stretch beside a beach becomes a sand path (`routemaker.beaches.longest_run`), and
the paths that end on a beach are carried on to it (`routemaker.beaches.access_joins`).

Only in the boxes it is given: the rebuild gives it the map areas where beaches are
ridden (Southwest Florida). Elsewhere a beach stays what it is.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import osmium
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid

from routemaker import beaches as rules

from .extract import Way

logger = logging.getLogger(__name__)

Box = tuple[float, float, float, float]

# The map areas whose beaches are ridden (the owner, 2026-11-23, of Southwest Florida).
BEACH_AREAS = ("southwest-florida",)


@dataclass
class Beach:
    osm: str
    name: str
    shape: object  # shapely (Multi)Polygon
    closed: bool  # closed to bicycles by its own tags


@dataclass
class BeachPaths:
    beaches: list[Beach] = field(default_factory=list)
    # The coastline ways that become paths, as `Way`s keeping the coastline's own
    # source tags (so `inject_tags` writes the path tags as a change).
    paths: list[Way] = field(default_factory=list)
    joins: list[rules.Join] = field(default_factory=list)
    beside_m: float = 0.0
    kept_m: float = 0.0


def _inside(box: Box, lon: float, lat: float) -> bool:
    return box[0] <= lon <= box[2] and box[1] <= lat <= box[3]


class _Reader(osmium.SimpleHandler):
    def __init__(self, boxes: Sequence[Box]) -> None:
        super().__init__()
        self.boxes = list(boxes)
        self.beaches: list[Beach] = []
        self.coast: list[tuple[int, dict[str, str], list[int], list[tuple[float, float]]]] = []

    def _in_a_box(self, points) -> bool:
        return any(_inside(box, lon, lat) for box in self.boxes for lon, lat in points)

    def way(self, w) -> None:  # noqa: N802 - osmium's callback name
        # A coastline way that is a highway already (a seawall promenade) is read as one.
        if w.tags.get("natural") != "coastline" or "highway" in w.tags:
            return
        ids, points = [], []
        for n in w.nodes:
            if n.location.valid():
                ids.append(n.ref)
                points.append((n.location.lon, n.location.lat))
        if len(points) >= 2 and self._in_a_box(points):
            self.coast.append((w.id, {t.k: t.v for t in w.tags}, ids, points))

    def area(self, a) -> None:  # noqa: N802
        if a.tags.get("natural") != "beach":
            return
        polygons = []
        for outer in a.outer_rings():
            ring = [(n.lon, n.lat) for n in outer]
            holes = [[(n.lon, n.lat) for n in inner] for inner in a.inner_rings(outer)]
            if len(ring) >= 4:
                polygons.append(Polygon(ring, [h for h in holes if len(h) >= 4]))
        points = [p for poly in polygons for p in poly.exterior.coords]
        if not polygons or not self._in_a_box(points):
            return
        shape = polygons[0] if len(polygons) == 1 else unary_union(polygons)
        if not shape.is_valid:
            shape = make_valid(shape)
        tags = {t.k: t.v for t in a.tags}
        self.beaches.append(
            Beach(
                osm=f"{'w' if a.from_way() else 'r'}{a.orig_id()}",
                name=tags.get("name") or "",
                shape=shape,
                closed=rules.closed_to_bicycles(tags),
            )
        )


def read(pbf: str | Path, boxes: Sequence[Box], ways: Sequence[Way] = ()) -> BeachPaths:
    """The beach paths in `boxes`, and the joins of `ways` (the extract's highways) to them."""
    out = BeachPaths()
    if not boxes:
        return out
    reader = _Reader(boxes)
    reader.apply_file(str(pbf), locations=True)
    out.beaches = reader.beaches
    # A stretch beside a beach closed to bicycles is not ridden: only the open beaches count.
    open_shapes = [b.shape for b in reader.beaches if not b.closed]
    tree = STRtree(open_shapes) if open_shapes else None
    tide_nodes: list[tuple[int, float, float]] = []
    taken = {way.osm_id for way in ways}
    for way_id, tags, ids, points in reader.coast:
        if tree is None or way_id in taken:
            continue
        flags = rules.beside_beach(points, tree)
        if not any(flags):
            continue
        out.beside_m += rules.runs_length_m(points, flags)
        run = rules.longest_run(points, flags)
        if run is None:
            continue
        node_ids = ids[run.start : run.stop + 1]
        coordinates = points[run.start : run.stop + 1]
        path = Way(osm_id=way_id, tags=dict(tags), node_ids=node_ids)
        path.tags.update(rules.BEACH_PATH_TAGS)
        path.coordinates = list(coordinates)
        path.located = list(range(len(node_ids)))
        out.paths.append(path)
        out.kept_m += run.length_m
        tide_nodes += [(n, lon, lat) for n, (lon, lat) in zip(node_ids, coordinates, strict=True)]
    ends = []
    for way in ways:
        if way.tags.get("highway") not in rules.ACCESS_HIGHWAYS or not way.coordinates:
            continue
        if not any(_inside(box, *way.coordinates[0]) or _inside(box, *way.coordinates[-1]) for box in boxes):
            continue
        located = way.located_points()
        first, last = located[0], located[-1]
        if first[0] == 0:
            ends.append((way.osm_id, True, way.node_ids[0], (first[1], first[2])))
        if last[0] == len(way.node_ids) - 1 and len(way.node_ids) > 1:
            ends.append((way.osm_id, False, way.node_ids[-1], (last[1], last[2])))
    out.joins = rules.access_joins(ends, open_shapes, tide_nodes)
    return out


def apply_joins(ways_by_id: dict[int, Way], joins: Sequence[rules.Join]) -> set[int]:
    """Carry each joined way on to its tide-line node, in its node list and its points.
    The ways changed, for `inject_tags` to write their node lists."""
    changed = set()
    for join in joins:
        way = ways_by_id.get(join.way_id)
        if way is None:
            continue
        if join.at_start:
            way.node_ids.insert(0, join.node_id)
            way.located = [0, *(i + 1 for i in way.located)]
            way.coordinates.insert(0, (join.lon, join.lat))
        else:
            way.node_ids.append(join.node_id)
            way.located.append(len(way.node_ids) - 1)
            way.coordinates.append((join.lon, join.lat))
        changed.add(join.way_id)
    return changed


def summary(found: BeachPaths) -> str:
    named = sum(1 for b in found.beaches if b.name)
    return (
        f"{len(found.beaches)} beaches ({named} named, "
        f"{sum(1 for b in found.beaches if b.closed)} closed to bicycles); "
        f"{len(found.paths)} beach paths, {found.kept_m / 1000:.1f} km of "
        f"{found.beside_m / 1000:.1f} km of coastline beside an open beach; "
        f"{len(found.joins)} beach accesses joined to them"
    )
