"""The extract's ways into Metro and MARC stations (`routemaker.station_links`)."""

from __future__ import annotations

from pathlib import Path

import osmium

from routemaker import station_links


class _WaysIn(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.entrances: list[tuple[float, float]] = []
        self.stations: list[tuple[float, float]] = []
        self.elevators: list[tuple[float, float]] = []

    def node(self, n) -> None:  # noqa: N802 - osmium's callback name
        if not n.location.valid():
            return
        tags = {tag.k: tag.v for tag in n.tags}
        point = (n.location.lon, n.location.lat)
        if station_links.is_station(tags):
            self.stations.append(point)
        elif station_links.is_way_in(tags):
            self.entrances.append(point)
        elif tags.get("highway") == "elevator":
            self.elevators.append(point)


def read_ways_in(pbf: str | Path) -> list[tuple[float, float]]:
    """Every station's ways in from the extract (`station_links.ways_in`)."""
    handler = _WaysIn()
    handler.apply_file(str(pbf))
    return station_links.ways_in(handler.entrances, handler.stations, handler.elevators)
