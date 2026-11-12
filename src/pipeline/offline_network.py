"""The road network a phone searches with no signal (off-grid riding; Stephen, 2026-11-12: "the one
mile would be a
default, with a whole region pack an optional download").

Each rebuild writes every way a bicycle may ride to `{schema}.offline_way` (`offline_way`,
streamed in batches by
`pipeline.writers.write_offline_ways`, so nothing region-wide is held in memory): its located OSM
node ids, its line,
stress level (times 2, so 3.5 is 7 and Avoid is 10), whether it is one-way for a bicycle, walked
or unpaved, and its
name. The API reads the ways around a route and cuts them at the junctions among them
(`split_edges`, over a mile's
corridor only; `core.offline_network`), and the phone searches that (frontend lib/offlineRouter.ts).

It is a simpler network than the router's: no turn restrictions, junction costs or graph
variants. It answers "a way
back to the line" with no signal, which the app labels approximate; the server's routing is
unchanged.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from routemaker.tags import ONEWAY_JUNCTIONS

# Edge flags, as frontend lib/offlineRouter.ts reads them.
EDGE_ONEWAY = 1
EDGE_WALK = 2
EDGE_UNPAVED = 4

# The stress level times 2 the network carries for Avoid (tier 5).
AVOID_LEVEL2 = 10

# Access reasons (`routemaker.facility.bike_access_reason`) that leave a way open to a bicycle.
OPEN_REASONS = frozenset({None, "override_open", "bicycle_use_sidepath"})

_EARTH_M = 6_371_008.8


@dataclass(frozen=True)
class OfflineWay:
    """One way as the network takes it: its located nodes and points, in the way's order."""

    osm_id: int
    node_ids: tuple[int, ...]
    coordinates: tuple[tuple[float, float], ...]
    level2: int
    flags: int
    # 1: one-way along the way's order; -1: one-way against it; 0: both ways.
    direction: int
    name: str | None


@dataclass(frozen=True)
class OfflineEdge:
    """A stretch between two junctions (or a way's end), ridden from `a_node` if one-way."""

    a_node: int
    b_node: int
    coordinates: tuple[tuple[float, float], ...]
    length_m: float
    level2: int
    flags: int
    name: str | None


def bicycle_direction(tags: Mapping[str, str]) -> int:
    """1 where a bicycle may ride only along the way's order, -1 only against it, 0 either way.

    `oneway:bicycle` wins; a contraflow cycle lane (`cycleway=opposite*`, or a side's
    `cycleway:*=opposite_lane`)
    opens the other way; otherwise `oneway` (with -1 reversed) and roundabouts as
    `routemaker.tags.is_oneway` reads
    them."""
    own = tags.get("oneway:bicycle")
    if own == "no":
        return 0
    if own in ("yes", "1", "true"):
        return 1
    if own == "-1":
        return -1
    for key in ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both"):
        if (tags.get(key) or "").startswith("opposite"):
            return 0
    oneway = tags.get("oneway")
    if oneway == "-1":
        return -1
    if oneway in ("yes", "1", "true"):
        return 1
    if tags.get("junction") in ONEWAY_JUNCTIONS and oneway != "no":
        return 1
    return 0


def level2_of(tier: int, half: bool) -> int:
    """The stress level times 2: tier 1 is 2, a half step 3.5 is 7, Avoid (tier 5) is 10."""
    tier = max(1, min(int(tier), 5))
    if tier == 5:
        return AVOID_LEVEL2
    return tier * 2 + (1 if half and tier <= 4 else 0)


def offline_way(
    osm_id: int,
    tags: Mapping[str, str],
    node_ids: Sequence[int],
    located: Sequence[int],
    coordinates: Sequence[tuple[float, float]],
    *,
    tier: int,
    half: bool,
    access_reason: str | None,
    walk_bike: bool,
    unpaved: bool | None,
    mtb_only: bool,
) -> OfflineWay | None:
    """The way as the network takes it, or None where a bicycle may not ride it (an access reason
    that closes it, a
    singletrack trail kept for mountain biking, which the way back never sends a rider onto) or
    it has under two
    located nodes."""
    if access_reason not in OPEN_REASONS or mtb_only or not tags.get("highway"):
        return None
    if len(coordinates) < 2 or len(located) != len(coordinates):
        return None
    flags = 0
    if walk_bike or tags.get("bicycle") == "dismount" or tags.get("highway") == "steps":
        flags |= EDGE_WALK
    if unpaved:
        flags |= EDGE_UNPAVED
    direction = bicycle_direction(tags)
    name = tags.get("name") or None
    return OfflineWay(
        osm_id=osm_id,
        node_ids=tuple(node_ids[i] for i in located),
        coordinates=tuple((float(lon), float(lat)) for lon, lat in coordinates),
        level2=level2_of(tier, half),
        flags=flags,
        direction=direction,
        name=name,
    )


def length_m(points: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(points, points[1:], strict=False):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = p2 - p1
        dl = math.radians(lon2 - lon1)
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * _EARTH_M * math.asin(min(1.0, math.sqrt(h)))
    return total


def split_edges(ways: Iterable[OfflineWay]) -> list[OfflineEdge]:
    """Every way cut at its junctions: a node that two or more ways share, or that a way passes
    twice, and each way's
    ends. A one-way edge runs the way it may be ridden (its `a_node` first)."""
    ways = list(ways)
    uses: Counter[int] = Counter()
    for way in ways:
        uses.update(way.node_ids)
    edges: list[OfflineEdge] = []
    for way in ways:
        last = len(way.node_ids) - 1
        start = 0
        for i in range(1, last + 1):
            if i != last and uses[way.node_ids[i]] < 2:
                continue
            points = way.coordinates[start : i + 1]
            a, b = way.node_ids[start], way.node_ids[i]
            flags = way.flags | (EDGE_ONEWAY if way.direction else 0)
            if way.direction < 0:
                points = tuple(reversed(points))
                a, b = b, a
            if a != b or len(points) > 2:
                edges.append(
                    OfflineEdge(a, b, tuple(points), length_m(points), way.level2, flags, way.name)
                )
            start = i
    return edges
