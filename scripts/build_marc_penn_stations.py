#!/usr/bin/env python3
"""Write the MARC Penn Line stations the public map shows, from the OSM extract.

Owner request (2026-09-27): the map shows the MARC Penn Line's stations "up to
Penn Station, but not more north" - Washington Union Station northward to
Baltimore Penn Station inclusive, and nothing past it. They come from
OpenStreetMap, which the map already credits (ODbL), and not from Maryland's
own MARC layer, which PLAN.md's Maryland terms (Region and data) bar until a waiver
exists.

The list is derived, never typed: the Penn Line's route_master
(network=MARC, ref=Penn, route_master=train) names its route variants; the
northbound variant from Washington Union Station with the most stops gives the
order; each stop position is resolved to the station that holds it through
its public_transport=stop_area relation; and the list is cut after
Baltimore Penn Station. Every other Penn variant, in both directions, is then
checked against it: a station any of them serves south of Baltimore Penn that
the chosen variant lacks stops the run, so a variant edited in OSM to call at a
new station cannot be silently missed.

Run from the repository root with the development venv (osmium is in
requirements-dev.txt):

    .venv311/bin/python scripts/build_marc_penn_stations.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It reads the extract only and writes
frontend/src/rail-data/marc-penn-stations.geojson (frontend/src/rail-data/README.md).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "src" / "rail-data" / "marc-penn-stations.geojson"

NETWORK = "MARC"
LINE_REF = "Penn"
SOUTH_END = "Washington Union Station"
NORTH_END = "Baltimore Penn Station"
STOP_ROLES = ("stop", "stop_entry_only", "stop_exit_only")


@dataclass
class OsmData:
    """The parts of an extract this reads: tagged rail nodes and relations."""

    # node id -> (tags, lon, lat), for nodes tagged railway=, public_transport=
    # or as an elevator
    nodes: dict[int, tuple[dict[str, str], float, float]] = field(default_factory=dict)
    # relation id -> (tags, [(type, ref, role)])
    relations: dict[int, tuple[dict[str, str], list[tuple[str, int, str]]]] = field(
        default_factory=dict
    )


class StationError(RuntimeError):
    pass


def read_extract(path: Path) -> OsmData:
    import osmium

    data = OsmData()

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if "railway" in n.tags or "public_transport" in n.tags or _is_elevator(n.tags):
                data.nodes[n.id] = (dict(n.tags), n.location.lon, n.location.lat)

        def relation(self, r):
            tags = dict(r.tags)
            if tags.get("public_transport") == "stop_area" or NETWORK in tags.get(
                "network", ""
            ).split(";"):
                data.relations[r.id] = (tags, [(m.type, m.ref, m.role) for m in r.members])

    Handler().apply_file(str(path))
    return data


def _is_elevator(tags) -> bool:
    return tags.get("highway") == "elevator" or tags.get("elevator") == "yes"


def _networks(tags: dict[str, str]) -> list[str]:
    return [n.strip() for n in tags.get("network", "").split(";") if n.strip()]


def _is_station_node(tags: dict[str, str]) -> bool:
    return tags.get("railway") == "station" or tags.get("public_transport") == "station"


def _line_routes(data: OsmData) -> list[int]:
    masters = [
        rid
        for rid, (tags, _) in data.relations.items()
        if tags.get("type") == "route_master"
        and tags.get("route_master") == "train"
        and NETWORK in _networks(tags)
        and tags.get("ref") == LINE_REF
    ]
    if len(masters) != 1:
        raise StationError(
            f"expected one {NETWORK} {LINE_REF} route_master, found {sorted(masters)}"
        )
    (master,) = masters
    routes = [
        ref
        for kind, ref, _ in data.relations[master][1]
        if kind == "r" and ref in data.relations and data.relations[ref][0].get("route") == "train"
    ]
    if not routes:
        raise StationError(f"route_master {master} has no route=train members in the extract")
    return routes


def _stop_areas_by_node(data: OsmData) -> dict[int, list[int]]:
    areas: dict[int, list[int]] = {}
    for rid, (tags, members) in sorted(data.relations.items()):
        if tags.get("public_transport") != "stop_area":
            continue
        for kind, ref, _ in members:
            if kind == "n":
                areas.setdefault(ref, []).append(rid)
    return areas


@dataclass(frozen=True)
class Station:
    key: str  # "relation/<stop_area id>", or "node/<stop id>" with no stop area
    name: str
    lon: float
    lat: float
    osm: str  # the object whose position is used


def _station_for_stop(data: OsmData, areas: dict[int, list[int]], stop: int) -> Station:
    candidates = areas.get(stop, [])
    # A stop position can sit in a bus or Metro stop area too; the MARC one wins.
    marc = [a for a in candidates if NETWORK in _networks(data.relations[a][0])]
    chosen = (marc or candidates or [None])[0]
    stop_tags, stop_lon, stop_lat = data.nodes.get(stop, ({}, None, None))
    if chosen is None:
        if stop_lon is None:
            raise StationError(f"stop node {stop} is not in the extract")
        return Station(
            f"node/{stop}", stop_tags.get("name", ""), stop_lon, stop_lat, f"node/{stop}"
        )
    area_tags, members = data.relations[chosen]
    station_nodes = [
        ref
        for kind, ref, _ in members
        if kind == "n" and ref in data.nodes and _is_station_node(data.nodes[ref][0])
    ]
    if station_nodes:
        node = station_nodes[0]
        tags, lon, lat = data.nodes[node]
        name = tags.get("name") or area_tags.get("name", "")
        return Station(f"relation/{chosen}", name, lon, lat, f"node/{node}")
    # No station node: the middle of the area's stop positions.
    stops = [ref for kind, ref, _ in members if kind == "n" and ref in data.nodes]
    if not stops:
        raise StationError(f"stop_area {chosen} has no nodes in the extract")
    lon = sum(data.nodes[s][1] for s in stops) / len(stops)
    lat = sum(data.nodes[s][2] for s in stops) / len(stops)
    name = area_tags.get("name") or stop_tags.get("name", "")
    return Station(f"relation/{chosen}", name, lon, lat, f"relation/{chosen}")


def _route_stations(data: OsmData, areas: dict[int, list[int]], route: int) -> list[Station]:
    stations: list[Station] = []
    for kind, ref, role in data.relations[route][1]:
        if kind == "n" and role in STOP_ROLES:
            station = _station_for_stop(data, areas, ref)
            if not stations or stations[-1].key != station.key:
                stations.append(station)
    return stations


def _south_of_north_end(stations: list[Station]) -> list[Station]:
    """The part of one variant's calls from SOUTH_END up to NORTH_END, either direction."""
    names = [s.name for s in stations]
    if NORTH_END not in names:
        return list(stations)  # a short working that never reaches it
    cut = names.index(NORTH_END)
    if SOUTH_END in names and names.index(SOUTH_END) > cut:
        return stations[cut:]  # southbound: from Baltimore Penn on
    return stations[: cut + 1]


def penn_stations(data: OsmData) -> tuple[list[Station], int]:
    """Union Station to Baltimore Penn inclusive, in line order; and the variant it came from."""
    areas = _stop_areas_by_node(data)
    routes = _line_routes(data)
    by_route = {r: _route_stations(data, areas, r) for r in routes}
    northbound = [r for r in routes if by_route[r] and by_route[r][0].name == SOUTH_END]
    if not northbound:
        raise StationError(f"no {LINE_REF} Line variant starts at {SOUTH_END}")
    chosen = max(northbound, key=lambda r: (len(by_route[r]), -r))
    stations = by_route[chosen]
    names = [s.name for s in stations]
    if NORTH_END not in names:
        raise StationError(f"route {chosen} does not call at {NORTH_END}")
    stations = stations[: names.index(NORTH_END) + 1]
    keys = {s.key for s in stations}
    for route, calls in sorted(by_route.items()):
        missing = [s.name for s in _south_of_north_end(calls) if s.key not in keys]
        if missing:
            raise StationError(f"route {route} calls at {missing}, which route {chosen} does not")
    if len(keys) != len(stations):
        raise StationError(f"route {chosen} calls at a station twice: {names}")
    return stations, chosen


# How far from a MARC station an untagged-to-it elevator or entrance is still
# taken as the station's. Elevators are inside or beside the station building;
# a station entrance can be across a car park. Elevators tagged as a subway
# entrance are the Metro's, which the DC entrances layer covers.
ELEVATOR_RADIUS_M = 100.0
ENTRANCE_RADIUS_M = 200.0


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Equirectangular metres between two (lon, lat) points; exact enough at station scale."""
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * math.cos(lat) * 111_320.0, (a[1] - b[1]) * 110_540.0)


@dataclass(frozen=True)
class Entrance:
    station: int  # index into the station list
    kind: str  # "elevator" or "entrance"
    lon: float
    lat: float
    osm: str


def _entrance_kind(tags: dict[str, str]) -> str | None:
    if tags.get("railway") == "subway_entrance":
        return None
    if _is_elevator(tags):
        return "elevator"
    if tags.get("railway") == "train_station_entrance":
        return "entrance"
    return None


def station_entrances(data: OsmData, stations: list[Station]) -> list[Entrance]:
    """The elevators and entrances OSM has at or beside each station, each given to one station."""
    members: dict[int, int] = {}
    for index, station in enumerate(stations):
        if station.key.startswith("relation/"):
            for kind, ref, _ in data.relations[int(station.key.split("/")[1])][1]:
                if kind == "n":
                    members.setdefault(ref, index)
    found: list[Entrance] = []
    for node, (tags, lon, lat) in sorted(data.nodes.items()):
        kind = _entrance_kind(tags)
        if kind is None:
            continue
        distances = [distance_m((lon, lat), (s.lon, s.lat)) for s in stations]
        nearest = min(range(len(stations)), key=lambda i: distances[i])
        radius = ELEVATOR_RADIUS_M if kind == "elevator" else ENTRANCE_RADIUS_M
        if node in members:
            found.append(Entrance(members[node], kind, lon, lat, f"node/{node}"))
        elif distances[nearest] <= radius:
            found.append(Entrance(nearest, kind, lon, lat, f"node/{node}"))
    return found


def _point(lon: float, lat: float) -> dict:
    return {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}


def geojson(
    stations: list[Station], entrances: list[Entrance], route: int, colour: str | None
) -> dict:
    """The fixture. `colour` is the route's own colour= tag, the colour the map draws it in."""
    return {
        "type": "FeatureCollection",
        "source": (
            f"OpenStreetMap (ODbL), MARC {LINE_REF} Line route relation {route}; "
            "scripts/build_marc_penn_stations.py"
        ),
        "colour": colour,
        "features": [
            {
                "type": "Feature",
                "geometry": _point(s.lon, s.lat),
                "properties": {"kind": "station", "name": s.name, "order": i, "osm": s.osm},
            }
            for i, s in enumerate(stations)
        ]
        + [
            {
                "type": "Feature",
                "geometry": _point(e.lon, e.lat),
                "properties": {"kind": e.kind, "station": e.station, "osm": e.osm},
            }
            for e in entrances
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pbf", type=Path, required=True, help="<DATA_ROOT>/extracts/source.osm.pbf"
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    data = read_extract(args.pbf)
    stations, route = penn_stations(data)
    entrances = station_entrances(data, stations)
    colour = data.relations[route][0].get("colour")
    doc = geojson(stations, entrances, route, colour)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    args.out.write_text(text, encoding="utf-8")
    for i, s in enumerate(stations):
        own = ", ".join(f"{e.kind} {e.osm}" for e in entrances if e.station == i) or "none tagged"
        print(f"{i:2d} {s.name} ({s.lat:.5f}, {s.lon:.5f}) {s.osm}; elevators/entrances: {own}")
    print(f"{len(stations)} stations (route {route}), {len(entrances)} elevators/entrances")
    return 0


if __name__ == "__main__":
    sys.exit(main())
