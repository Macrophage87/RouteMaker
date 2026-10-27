"""The extract's ways into rail stations and its platforms (`routemaker.station_links`)."""

from __future__ import annotations

from pathlib import Path

import osmium

from routemaker import station_links


def read_ways_in(pbf: str | Path) -> list[tuple[float, float]]:
    """Every rail station's ways in from the extract (`station_links.ways_in`): only the
    nodes the tag filter lets through are read in Python, as `agency_signals` reads signals."""
    entrances: list[tuple[float, float]] = []
    stations: list[tuple[float, float]] = []
    elevators: list[tuple[float, float]] = []
    processor = osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(
        osmium.filter.TagFilter(
            ("railway", "subway_entrance"),
            ("railway", "train_station_entrance"),
            ("railway", "station"),
            ("highway", "elevator"),
        )
    )
    for node in processor:
        if not node.location.valid():
            continue
        tags = {tag.k: tag.v for tag in node.tags}
        point = (node.location.lon, node.location.lat)
        if station_links.is_station(tags):
            stations.append(point)
        elif station_links.is_way_in(tags):
            entrances.append(point)
        elif tags.get("highway") == "elevator":
            elevators.append(point)
    return station_links.ways_in(entrances, stations, elevators)


def read_platform_nodes(pbf: str | Path) -> set[int]:
    """The node ids of every rail platform in service (`station_links.is_platform`), for
    `station_links.platform_walks`."""
    nodes: set[int] = set()
    processor = osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(
        osmium.filter.TagFilter(("railway", "platform"))
    )
    for way in processor:
        if station_links.is_platform({tag.k: tag.v for tag in way.tags}):
            nodes.update(node.ref for node in way.nodes)
    return nodes
