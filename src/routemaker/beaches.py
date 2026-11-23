"""The beach path: riding a beach along its high-tide line (the owner, 2026-11-23, of
Southwest Florida: "you can ride your bike on the beach here, but generally only
adviseable in low tide below the high tide lines"; "The tide line might work as a linear
path"; "we'd have that as a specific beach biking path").

OSM's coastline (`natural=coastline`) is drawn at mean high water, so where it runs beside
a beach (`natural=beach`) it is the tide line. A coastline way's longest stretch beside a
beach becomes a path in the graph: the way keeps its own id (way ids are never minted,
`pipeline.extract.write_extract`), its node list is cut to that stretch, and it is tagged
a sand path open to bicycles. Paths that end on the beach (the beach accesses) are carried
on to the nearest point of it, so the tide line joins the street network. A beach whose
own tags close it to bicycles (`bicycle=no`, `access=no` or `private`) gives no path.

Plain functions of points and shapes; `pipeline.beaches` reads them from the extract.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from shapely.geometry import Point
from shapely.prepared import prep
from shapely.strtree import STRtree

M_PER_DEG = 111_320.0
# How far a coastline node may be from a beach's outline and still be on the beach: the
# two are drawn by different hands, and a beach's sea edge is often a node or two off the
# coastline (measured 2026-11-23: 3,683 of 10,895 beach nodes are the coastline's own).
NEAR_BEACH_M = 20.0
# A stretch shorter than this is a seawall gap or a corner, not a beach to ride.
MIN_PATH_M = 100.0
# How far a path that ends on the beach is carried to the tide line: across the sand of
# a wide beach, not across a bay.
JOIN_M = 150.0
# How close a path's end must be to a beach to count as a beach access.
ACCESS_END_M = 15.0
# Only the ways a rider walks or rides onto the sand: a service road or a flight of steps
# carried across a beach would bring its own tags with it.
ACCESS_HIGHWAYS = frozenset({"footway", "path", "cycleway", "pedestrian"})

# The tags a tide-line way carries in the graph. `surface=sand` is loose ground to the
# router and the surface setting (lua `valhalla_surface`: gravel), so a ride that keeps to
# pavement leaves it. The map and the route notes know it by its way id
# (scripts/build_beaches.py).
BEACH_PATH_TAGS = {
    "highway": "path",
    "surface": "sand",
    "bicycle": "yes",
    "foot": "yes",
}


def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Ground distance between two lon/lat points, flat-earth (short spans)."""
    scale = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * scale, a[1] - b[1]) * M_PER_DEG


def closed_to_bicycles(tags: dict[str, str]) -> bool:
    return tags.get("bicycle") == "no" or tags.get("access") in {"no", "private"}


@dataclass(frozen=True)
class Run:
    """A coastline way's stretch beside a beach: indices into its located points."""

    start: int
    stop: int  # inclusive
    length_m: float


def beside_beach(
    points: Sequence[tuple[float, float]], beaches: Sequence, near_m: float = NEAR_BEACH_M
) -> list[bool]:
    """For each point, whether it lies within `near_m` of one of the beach shapes."""
    if not beaches or not points:
        return [False] * len(points)
    tree = beaches if isinstance(beaches, STRtree) else STRtree(list(beaches))
    found = tree.query([Point(lon, lat) for lon, lat in points], predicate="dwithin", distance=near_m / M_PER_DEG)
    out = [False] * len(points)
    for index in set(found[0].tolist()):
        out[int(index)] = True
    return out


def longest_run(
    points: Sequence[tuple[float, float]], flags: Sequence[bool], min_m: float = MIN_PATH_M
) -> Run | None:
    """The longest stretch of consecutive points all beside a beach, if one is at least
    `min_m` long. One per way: a way is one line, so a coastline way that passes two
    beaches gives the longer one (the build log says how much is left out)."""
    best: Run | None = None
    start = None
    length = 0.0
    for i, flag in enumerate([*flags, False]):
        if flag and i < len(points):
            if start is None:
                start, length = i, 0.0
            else:
                length += metres(points[i - 1], points[i])
            continue
        if start is not None and i - 1 > start and (best is None or length > best.length_m):
            best = Run(start, i - 1, length)
        start = None
    return best if best is not None and best.length_m >= min_m else None


def runs_length_m(points: Sequence[tuple[float, float]], flags: Sequence[bool]) -> float:
    """The length of every stretch beside a beach, for the build log's what-was-left-out."""
    return sum(
        metres(points[i - 1], points[i])
        for i in range(1, len(points))
        if flags[i - 1] and flags[i]
    )


@dataclass(frozen=True)
class Join:
    """Carry way `way_id` on from its first (`at_start`) or last node to `node_id`."""

    way_id: int
    at_start: bool
    node_id: int
    lon: float
    lat: float


def access_joins(
    ends: Iterable[tuple[int, bool, int, tuple[float, float]]],
    beaches: Sequence,
    tide_nodes: Sequence[tuple[int, float, float]],
    tide_node_ids: set[int] | None = None,
    end_m: float = ACCESS_END_M,
    join_m: float = JOIN_M,
) -> list[Join]:
    """The beach accesses carried on to the tide line. `ends` is (way id, whether it is the
    way's first node, that node's id, its lon/lat) for each end of each candidate path;
    `tide_nodes` the beach paths' nodes. An end already on the tide line is left as it is."""
    if not tide_nodes or not beaches:
        return []
    near = [prep(b.buffer(end_m / M_PER_DEG)) for b in beaches]
    tree = STRtree(list(beaches))
    points = [Point(lon, lat) for _, lon, lat in tide_nodes]
    tide_tree = STRtree(points)
    tide_ids = tide_node_ids if tide_node_ids is not None else {n for n, _, _ in tide_nodes}
    joins = []
    for way_id, at_start, node_id, (lon, lat) in ends:
        if node_id in tide_ids:
            continue
        p = Point(lon, lat)
        if not any(near[i].contains(p) for i in tree.query(p.buffer(end_m / M_PER_DEG))):
            continue
        nearest = tide_tree.nearest(p)
        target_id, tlon, tlat = tide_nodes[int(nearest)]
        if metres((lon, lat), (tlon, tlat)) <= join_m:
            joins.append(Join(way_id, at_start, target_id, tlon, tlat))
    return joins
