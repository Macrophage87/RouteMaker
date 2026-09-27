"""The MARC Penn Line stations taken from OSM, and the Metro elevator cross-check.

scripts/build_marc_penn_stations.py writes frontend/src/rail-data/marc-penn-stations.geojson
from the extract; scripts/check_metro_elevators.py lists where OSM and DC's
elevator layer disagree. Both are run against small made-up extracts here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "frontend" / "src" / "rail-data" / "marc-penn-stations.geojson"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


marc = _load("build_marc_penn_stations")
elevators = _load("check_metro_elevators")

# A line along a meridian, 0.01 degrees (about 1.1 km) between stations, south
# to north: Union Station, two stops, Baltimore Penn, then two past it.
LINE = ["Washington Union Station", "Alpha", "Bravo", "Baltimore Penn Station", "Charlie", "Delta"]


def _world(extra_south_call: str | None = None) -> marc.OsmData:
    data = marc.OsmData()
    for i, name in enumerate(LINE):
        station, stop = 1000 + i, 2000 + i
        lat = 38.9 + 0.01 * i
        data.nodes[station] = ({"railway": "station", "name": name}, -77.0, lat)
        # The stop position is on the track, a little east of the station node.
        data.nodes[stop] = ({"public_transport": "stop_position", "name": name}, -76.999, lat)
        data.relations[3000 + i] = (
            {"public_transport": "stop_area", "network": "MARC", "name": f"{name} (area)"},
            [("n", stop, "stop"), ("n", station, "")],
        )
    # The same stop position is also in a bus stop area, listed first.
    data.relations[2999] = (
        {"public_transport": "stop_area", "network": "Bus", "name": "Alpha bus"},
        [("n", 2001, "stop")],
    )
    north = [("n", 2000 + i, "stop") for i in range(len(LINE))]
    south = list(reversed(north))
    short = [("n", 2000, "stop"), ("n", 2003, "stop")]
    if extra_south_call:
        data.nodes[2100] = (
            {"public_transport": "stop_position", "name": extra_south_call},
            -76.99,
            38.905,
        )
        south.insert(-1, ("n", 2100, "stop"))
    common = {"type": "route", "route": "train", "network": "MARC", "ref": "Penn"}
    data.relations[1] = (common | {"from": "Washington Union Station"}, north)
    data.relations[2] = (common | {"from": "Delta"}, south)
    data.relations[3] = (common | {"from": "Washington Union Station"}, short)
    data.relations[9] = (
        {"type": "route_master", "route_master": "train", "network": "MARC", "ref": "Penn"},
        [("r", 1, ""), ("r", 2, ""), ("r", 3, "")],
    )
    # Another line's master, which must not be read.
    data.relations[10] = (
        {"type": "route_master", "route_master": "train", "network": "MARC", "ref": "Camden"},
        [("r", 1, "")],
    )
    return data


def test_the_line_runs_from_union_station_to_baltimore_penn_and_no_further() -> None:
    stations, route = marc.penn_stations(_world())
    assert route == 1, "the northbound variant with the most calls"
    assert [s.name for s in stations] == LINE[:4]


def test_a_station_is_placed_at_its_station_node_not_its_stop_position() -> None:
    stations, _ = marc.penn_stations(_world())
    assert [s.osm for s in stations] == [f"node/{1000 + i}" for i in range(4)]
    assert all(s.lon == -77.0 for s in stations)


def test_the_marc_stop_area_wins_over_another_networks() -> None:
    stations, _ = marc.penn_stations(_world())
    assert stations[1].key == "relation/3001"


def test_a_stop_area_with_no_station_node_is_placed_amid_its_stops() -> None:
    data = _world()
    tags, members = data.relations[3002]
    data.relations[3002] = (tags, [m for m in members if m[1] != 1002])
    stations, _ = marc.penn_stations(data)
    assert stations[2].osm == "relation/3002"
    assert stations[2].name == "Bravo (area)"
    assert (stations[2].lon, stations[2].lat) == (-76.999, pytest.approx(38.92))


def test_a_variant_calling_south_of_baltimore_where_the_chosen_one_does_not_stops_the_run() -> None:
    with pytest.raises(marc.StationError, match="Echo"):
        marc.penn_stations(_world(extra_south_call="Echo"))


def test_no_route_master_or_two_stop_the_run() -> None:
    data = _world()
    del data.relations[9]
    with pytest.raises(marc.StationError, match="route_master"):
        marc.penn_stations(data)
    data = _world()
    data.relations[11] = data.relations[9]
    with pytest.raises(marc.StationError, match="route_master"):
        marc.penn_stations(data)


def test_elevators_and_entrances_go_to_their_station_within_reach() -> None:
    data = _world()
    stations, _ = marc.penn_stations(data)
    # About 50 m north of Alpha's station node: Alpha's elevator.
    data.nodes[5001] = ({"highway": "elevator"}, -77.0, 38.91045)
    # A Metro street elevator beside Alpha: the DC layer's, not taken.
    data.nodes[5002] = ({"highway": "elevator", "railway": "subway_entrance"}, -77.0, 38.9101)
    # 150 m away: too far for an elevator, near enough for an entrance.
    data.nodes[5003] = ({"highway": "elevator"}, -77.0, 38.92135)
    data.nodes[5004] = ({"railway": "train_station_entrance"}, -77.0, 38.92135)
    # Far from every station, but a member of Union Station's stop area.
    data.nodes[5005] = ({"elevator": "yes", "railway": "platform_edge"}, -77.01, 38.9)
    tags, members = data.relations[3000]
    data.relations[3000] = (tags, [*members, ("n", 5005, "")])
    found = {e.osm: (e.station, e.kind) for e in marc.station_entrances(data, stations)}
    assert found == {
        "node/5001": (1, "elevator"),
        "node/5004": (2, "entrance"),
        "node/5005": (0, "elevator"),
    }


def test_the_geojson_numbers_stations_in_line_order_and_ties_entrances_to_them() -> None:
    data = _world()
    stations, route = marc.penn_stations(data)
    data.nodes[5001] = ({"highway": "elevator"}, -77.0, 38.91045)
    doc = marc.geojson(stations, marc.station_entrances(data, stations), route, "#BDBADC")
    kinds = [f["properties"]["kind"] for f in doc["features"]]
    assert kinds == ["station"] * 4 + ["elevator"]
    assert [f["properties"]["order"] for f in doc["features"][:4]] == [0, 1, 2, 3]
    assert doc["features"][4]["properties"]["station"] == 1
    assert str(route) in doc["source"] and "OpenStreetMap" in doc["source"]
    assert doc["colour"] == "#BDBADC"


def test_the_extract_reader_keeps_rail_nodes_elevators_and_marc_relations(tmp_path) -> None:
    import osmium

    path = tmp_path / "tiny.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    node = osmium.osm.mutable.Node
    writer.add_node(node(id=1, location=(-77, 38.9), tags={"railway": "station"}, version=1))
    writer.add_node(node(id=2, location=(-77, 38.9), tags={"highway": "elevator"}, version=1))
    writer.add_node(node(id=3, location=(-77, 38.9), tags={"amenity": "cafe"}, version=1))
    relation = osmium.osm.mutable.Relation
    writer.add_relation(
        relation(id=1, members=[("n", 1, "")], tags={"network": "Amtrak;MARC"}, version=1)
    )
    writer.add_relation(
        relation(id=2, members=[("n", 1, "")], tags={"public_transport": "stop_area"}, version=1)
    )
    writer.add_relation(
        relation(id=3, members=[("n", 1, "")], tags={"network": "WMATA"}, version=1)
    )
    writer.close()
    data = marc.read_extract(path)
    assert sorted(data.nodes) == [1, 2]
    assert sorted(data.relations) == [1, 2]


def test_the_committed_fixture_is_the_line_as_far_as_baltimore_penn() -> None:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stations = [f for f in doc["features"] if f["properties"]["kind"] == "station"]
    names = [f["properties"]["name"] for f in stations]
    assert doc["colour"].startswith("#"), "the route relation's own colour= tag"
    assert names[0] == "Washington Union Station"
    assert names[-1] == "Baltimore Penn Station"
    assert [f["properties"]["order"] for f in stations] == list(range(len(stations)))
    for past in ("Martin State Airport", "Edgewood", "Aberdeen", "Perryville"):
        assert past not in names
    # Northward all the way: each station is north of the one before it.
    lats = [f["geometry"]["coordinates"][1] for f in stations]
    assert lats == sorted(lats)
    for f in doc["features"]:
        if f["properties"]["kind"] != "station":
            assert 0 <= f["properties"]["station"] < len(stations)


def _metres(a, b):
    return marc.distance_m(a, b)


def test_the_elevator_check_lists_each_side_s_unmatched_elevators() -> None:
    stations = [("A", (-77.0, 38.9)), ("B", (-77.0, 38.95))]
    dc = [("A1", (-77.0, 38.9002)), ("A2", (-77.0, 38.9010))]
    osm = [
        ("node/1", (-77.0, 38.90021), True),  # A1, 1 m off: agrees
        ("node/2", (-77.0, 38.8990), True),  # a street elevator DC lacks
        ("node/3", (-77.0, 38.9500), False),  # at B, which DC gives none
        ("node/4", (-77.0, 38.9300), True),  # 2 km from both: ignored
    ]
    dc_only, osm_only, near = elevators.compare(stations, dc, osm, _metres)
    assert [d[0] for d in dc_only] == ["A2"]
    assert [(o[0], o[1], o[3]) for o in osm_only] == [("node/2", "A", True), ("node/3", "B", False)]
    assert [o[0] for o in near] == ["node/1", "node/2", "node/3"]


def test_distance_is_about_right_at_this_latitude() -> None:
    # 0.001 degrees of latitude is 110.5 m; of longitude at 38.9 N, 86.6 m.
    assert marc.distance_m((-77.0, 38.9), (-77.0, 38.901)) == pytest.approx(110.5, rel=0.01)
    assert marc.distance_m((-77.0, 38.9), (-77.001, 38.9)) == pytest.approx(86.6, rel=0.01)
