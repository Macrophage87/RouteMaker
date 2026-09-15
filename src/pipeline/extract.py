"""Reading and writing the OSM extract.

The pipeline's first and last contact with OSM data. Everything between - the
stress classifier, the jurisdiction tagger, the border-node inserter - works on
plain dicts and coordinate lists, so it can be tested without a PBF; this module
is the only place that knows what a PBF is.

Derived values are written back as `rm:*` tags, namespaced so they cannot
collide with a real OSM key, and stripped by the Lua transform before Valhalla
sees them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import osmium

DERIVED_PREFIX = "rm:"


@dataclass
class Way:
    """One way, with its tags and the coordinates of its nodes.

    `coordinates` is not parallel to `node_ids`. A clipped extract carries no
    location for nodes that fall outside it, so those nodes have no coordinate
    and the two lists differ in length on exactly the ways at the edge of the
    clip. `located` records which node each coordinate came from, so anything
    that needs to point back at the node list has an index that is right rather
    than one that happens to line up in the middle of the region.
    """

    osm_id: int
    tags: dict[str, str]
    node_ids: list[int]
    coordinates: list[tuple[float, float]] = field(default_factory=list)
    # Index into node_ids for each entry in coordinates, in the same order.
    located: list[int] = field(default_factory=list)

    @property
    def name(self) -> str | None:
        return self.tags.get("name")

    def located_points(self) -> list[tuple[int, float, float]]:
        """(node-list index, lon, lat) for every node whose location is known."""
        if len(self.located) != len(self.coordinates):
            raise ValueError(
                f"way {self.osm_id} has {len(self.coordinates)} coordinates but "
                f"{len(self.located)} node indices; they are built together and "
                "must stay in step"
            )
        return [
            (index, lon, lat)
            for index, (lon, lat) in zip(self.located, self.coordinates, strict=True)
        ]


class WayCollector(osmium.SimpleHandler):
    """Collects ways and the node locations they reference.

    Two passes rather than one: a PBF stores nodes before ways, but a way's
    node locations are only needed for ways that survive filtering, and holding
    every node in the extract costs more memory than the rebuild container has.
    So the first pass records which nodes are wanted and the second fills them.
    """

    def __init__(self, keep: Callable[[dict[str, str]], bool] | None = None) -> None:
        super().__init__()
        self.ways: list[Way] = []
        self.wanted_nodes: set[int] = set()
        self._keep = keep or (lambda tags: "highway" in tags)

    def way(self, w) -> None:  # noqa: N802 - osmium's callback name
        tags = {tag.k: tag.v for tag in w.tags}
        if not self._keep(tags):
            return
        node_ids = [n.ref for n in w.nodes]
        self.wanted_nodes.update(node_ids)
        self.ways.append(Way(osm_id=w.id, tags=tags, node_ids=node_ids))


class NodeLocator(osmium.SimpleHandler):
    """Second pass: the coordinates of the nodes the first pass asked for."""

    def __init__(self, wanted: set[int]) -> None:
        super().__init__()
        self._wanted = wanted
        self.locations: dict[int, tuple[float, float]] = {}

    def node(self, n) -> None:  # noqa: N802 - osmium's callback name
        if n.id in self._wanted:
            self.locations[n.id] = (n.location.lon, n.location.lat)


def read_ways(path: str | Path, keep: Callable[[dict[str, str]], bool] | None = None) -> list[Way]:
    """Every way the filter keeps, with its node coordinates attached."""
    collector = WayCollector(keep)
    collector.apply_file(str(path))

    locator = NodeLocator(collector.wanted_nodes)
    locator.apply_file(str(path))

    for way in collector.ways:
        located = [
            (index, locator.locations[node_id])
            for index, node_id in enumerate(way.node_ids)
            if node_id in locator.locations
        ]
        way.located = [index for index, _ in located]
        way.coordinates = [point for _, point in located]
    return collector.ways


def derived_tags(values: dict[str, object]) -> dict[str, str]:
    """Namespace derived values so they cannot collide with a real OSM key."""
    out = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "yes" if value else "no"
        out[f"{DERIVED_PREFIX}{key}"] = str(value)
    return out


def write_extract(
    source: str | Path,
    destination: str | Path,
    way_tags: dict[int, dict[str, str]],
    new_nodes: list[tuple[int, float, float, dict[str, str]]],
    way_node_ids: dict[int, list[int]],
    drop_ways: set[int] | None = None,
) -> None:
    """Write a new extract with derived tags, inserted nodes, and ways dropped.

    Way ids are never minted or altered here, which is what keeps the segment
    key, the trace join and anchor reconciliation pointing at the same things
    across rebuilds. Only tags and node lists change.

    The minted nodes are written after every source node and before the first
    way, which is the only position that produces a file valhalla_build_tiles
    will read. An OSM file is ordered nodes, then ways, then relations, and
    within a block by ascending id; the parser rejects anything else outright
    with "Detected unsorted input data" rather than sorting it. Writing them up
    front, as the first version did, put ids above every source id at the head of
    the node block.
    """
    drop_ways = drop_ways or set()
    writer = osmium.SimpleWriter(str(destination))
    try:

        class Copier(osmium.SimpleHandler):
            def __init__(self) -> None:
                super().__init__()
                self.flushed = False
                self.highest_source_node_id = 0

            def flush_new_nodes(self) -> None:
                """Append the minted nodes to the end of the node block."""
                if self.flushed:
                    return
                self.flushed = True
                for node_id, lon, lat, tags in sorted(new_nodes):
                    if node_id <= self.highest_source_node_id:
                        # Appending only keeps the block sorted while the
                        # reserved range stays above every id OSM has issued. If
                        # that ever stops being true the extract is silently
                        # unsorted, and the tile build fails a stage later with a
                        # message that says nothing about node ids.
                        raise ValueError(
                            f"minted node {node_id} is not above the highest source node id "
                            f"{self.highest_source_node_id}; the reserved range has been "
                            "overtaken and borders.SYNTHETIC_NODE_ID_FLOOR needs raising"
                        )
                    writer.add_node(
                        osmium.osm.mutable.Node(
                            id=node_id, location=(lon, lat), tags=tags, version=1
                        )
                    )

            def node(self, n) -> None:  # noqa: N802
                self.highest_source_node_id = max(self.highest_source_node_id, n.id)
                writer.add_node(n)

            def way(self, w) -> None:  # noqa: N802
                self.flush_new_nodes()
                if w.id in drop_ways:
                    return
                tags = {tag.k: tag.v for tag in w.tags}
                tags.update(way_tags.get(w.id, {}))
                nodes = way_node_ids.get(w.id) or [n.ref for n in w.nodes]
                writer.add_way(
                    osmium.osm.mutable.Way(id=w.id, nodes=nodes, tags=tags, version=w.version)
                )

            def relation(self, r) -> None:  # noqa: N802
                self.flush_new_nodes()
                writer.add_relation(r)

        copier = Copier()
        copier.apply_file(str(source))
        # An extract with no ways and no relations never reaches either flush
        # point. Unreachable for a real region and cheap to be right about.
        copier.flush_new_nodes()
    finally:
        writer.close()


def iter_segments(
    way: Way, max_points: int = 64
) -> Iterator[tuple[int, list[tuple[float, float]]]]:
    """Split a way's geometry into segment-sized pieces with their ordinals.

    The segment key is (way id, ordinal), so the ordinal has to be a function of
    position within the way and nothing else: anything that depended on the
    clip polygon or on neighbouring data would renumber segments week to week
    and orphan every anchor attached to them.
    """
    coordinates = way.coordinates
    if len(coordinates) < 2:
        return
    for ordinal, start in enumerate(range(0, len(coordinates) - 1, max_points - 1)):
        piece = coordinates[start : start + max_points]
        if len(piece) >= 2:
            yield ordinal, piece
