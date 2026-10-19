"""Which junction nodes an agency's signal list marks (`pipeline.agency_signals`).

DDOT lists every signal it runs; OSM misses some. The rebuild marks the junction
node at each listed signal OSM does not have, with the same mark the signalised
trail crossings use (`pipeline.signals.NODE_TAG`), which the transform turns into
`highway=traffic_signals` (tests/lua/test_remap.lua).
"""

from __future__ import annotations

import json
import math
import subprocess
import sys

import osmium
import pytest
from rebuild_fixtures import REPO

from pipeline import agency_signals
from pipeline.agency_signals import Signal
from pipeline.extract import Way

ORIGIN = (-77.0, 38.9)
M_PER_DEG_LAT = 111_320.0


def at(east_m: float, north_m: float) -> tuple[float, float]:
    """A point `east_m`, `north_m` metres from ORIGIN."""
    lon0, lat0 = ORIGIN
    return (
        lon0 + east_m / (M_PER_DEG_LAT * math.cos(math.radians(lat0))),
        lat0 + north_m / M_PER_DEG_LAT,
    )


def way(osm_id: int, tags: dict, nodes: dict[int, tuple[float, float]]) -> Way:
    """A way through `nodes` (id to metres east, north), every node located."""
    ids = list(nodes)
    return Way(
        osm_id=osm_id,
        tags=tags,
        node_ids=ids,
        coordinates=[at(*nodes[n]) for n in ids],
        located=list(range(len(ids))),
    )


def signal(east_m: float = 0, north_m: float = 0, kind: str = "signal", fid: str = "ddot:1"):
    lon, lat = at(east_m, north_m)
    return Signal(fid, "ddot", lon, lat, kind)


AVENUE = {"highway": "primary"}
STREET = {"highway": "residential"}


def crossroads() -> list[Way]:
    """An avenue east-west and a street north-south meeting at node 1 (the origin)."""
    return [
        way(10, AVENUE, {2: (-100, 0), 1: (0, 0), 3: (100, 0)}),
        way(11, STREET, {4: (0, -100), 1: (0, 0), 5: (0, 100)}),
    ]


def test_a_signal_osm_lacks_marks_the_junction_node() -> None:
    result = agency_signals.match([signal(5, 5)], crossroads(), {})
    assert result.nodes == {1}
    assert result.added == {"ddot": 1}


def test_a_t_junction_is_a_junction() -> None:
    ways = [
        way(10, AVENUE, {2: (-100, 0), 1: (0, 0), 3: (100, 0)}),
        way(11, STREET, {1: (0, 0), 5: (0, 100)}),
    ]
    assert agency_signals.match([signal()], ways, {}).nodes == {1}


def test_a_way_split_is_not_a_junction() -> None:
    """Two ways of one road meeting end to end make two arms, not a junction."""
    ways = [
        way(10, AVENUE, {2: (-100, 0), 1: (0, 0)}),
        way(11, AVENUE, {1: (0, 0), 3: (100, 0)}),
    ]
    result = agency_signals.match([signal()], ways, {})
    assert result.nodes == set()
    assert result.unmatched == {"ddot": 1}


def test_a_signal_osm_maps_on_a_stop_line_is_left_alone() -> None:
    """OSM's signal 25 m up an arm is this junction's: nothing is added."""
    osm = {99: at(-25, 0)}
    result = agency_signals.match([signal()], crossroads(), osm)
    assert result.nodes == set()
    assert result.already_in_osm == {"ddot": 1}


def test_a_signal_osm_maps_at_the_next_junction_is_not_this_ones() -> None:
    """Two junctions 26 m apart along the avenue (a diagonal's offset): OSM maps a
    signal only at the far one, so the agency's signal at the near one is added."""
    ways = [
        way(10, AVENUE, {2: (-100, 0), 1: (0, 0), 6: (26, 0), 3: (100, 0)}),
        way(11, STREET, {4: (0, -100), 1: (0, 0), 5: (0, 100)}),
        way(12, STREET, {7: (26, -100), 6: (26, 0), 8: (26, 100)}),
    ]
    result = agency_signals.match([signal()], ways, {99: at(26, 0)})
    assert result.nodes == {1}
    assert result.added == {"ddot": 1}


def test_an_osm_signal_beyond_the_approach_does_not_count() -> None:
    osm = {99: at(-60, 0)}
    assert agency_signals.match([signal()], crossroads(), osm).nodes == {1}


def test_every_node_of_a_divided_roads_junction_is_marked() -> None:
    """Two carriageways 14 m apart crossing a street: two junction nodes."""
    ways = [
        way(10, AVENUE, {2: (-100, 7), 1: (0, 7), 3: (100, 7)}),
        way(11, AVENUE, {6: (100, -7), 7: (0, -7), 8: (-100, -7)}),
        way(12, STREET, {4: (0, -100), 7: (0, -7), 1: (0, 7), 5: (0, 100)}),
    ]
    assert agency_signals.match([signal()], ways, {}).nodes == {1, 7}


def test_a_junction_beyond_reach_is_not_marked() -> None:
    result = agency_signals.match([signal(0, 40)], crossroads(), {})
    assert result.nodes == set()
    assert result.unmatched == {"ddot": 1}


@pytest.mark.parametrize("service", ["alley", "parking_aisle", "driveway", "drive-through"])
def test_an_alley_mouth_beside_the_signal_is_not_taken_for_it(service) -> None:
    ways = [
        *crossroads(),
        way(12, {"highway": "service", "service": service}, {6: (15, 0), 9: (15, 50)}),
        way(13, AVENUE, {3: (100, 0), 6: (15, 0)}),
    ]
    # Node 6 is on the avenue only as a split plus the alley: not a junction.
    ways[0] = way(10, AVENUE, {2: (-100, 0), 1: (0, 0), 6: (15, 0)})
    assert agency_signals.match([signal()], ways, {}).nodes == {1}


def test_a_signalised_entrance_road_is_a_junction() -> None:
    ways = [
        way(10, AVENUE, {2: (-100, 0), 1: (0, 0), 3: (100, 0)}),
        way(11, {"highway": "service"}, {1: (0, 0), 5: (0, 100)}),
    ]
    assert agency_signals.match([signal()], ways, {}).nodes == {1}


def test_a_hawk_marks_the_nearest_crosswalk_not_a_junction() -> None:
    crosswalk = {"highway": "footway", "footway": "crossing", "crossing": "marked"}
    ways = [
        way(10, AVENUE, {2: (-100, 0), 20: (-10, 0), 21: (10, 0), 3: (100, 0)}),
        way(11, crosswalk, {30: (-10, -10), 20: (-10, 0), 31: (-10, 10)}),
        way(12, crosswalk, {32: (10, -10), 21: (10, 0), 33: (10, 10)}),
    ]
    result = agency_signals.match([signal(-8, 0, kind="hawk")], ways, {})
    assert result.nodes == {20}


def test_the_report_has_a_row_per_signal() -> None:
    result = agency_signals.match(
        [signal(fid="ddot:a"), signal(0, 500, fid="ddot:b")], crossroads(), {}
    )
    rows = agency_signals.report_csv(result).splitlines()
    assert rows[0] == "signal_id,lon,lat,outcome,marked_osm_nodes"
    assert [row.split(",")[3] for row in rows[1:]] == ["added", "unmatched"]
    assert "1 added" in agency_signals.summary(result)


@pytest.mark.parametrize(
    "tags, expected",
    [
        ({"highway": "traffic_signals"}, True),
        ({"highway": "crossing", "crossing": "traffic_signals"}, True),
        ({"highway": "crossing", "crossing": "uncontrolled"}, False),
        ({"highway": "stop"}, False),
        ({}, False),
    ],
)
def test_what_osm_already_maps_as_a_signal(tags, expected) -> None:
    assert agency_signals.is_osm_signal(tags) is expected


def test_the_extracts_signals_are_read_inside_the_box(tmp_path) -> None:
    path = tmp_path / "toy.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, (lon, lat), tags in [
            (1, at(0, 0), {"highway": "traffic_signals"}),
            (2, at(10, 0), {"highway": "crossing", "crossing": "traffic_signals"}),
            (3, at(20, 0), {"highway": "stop"}),
            (4, (-76.0, 39.5), {"highway": "traffic_signals"}),
        ]:
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags=tags, version=1)
            )
    finally:
        writer.close()
    box = agency_signals.bounds([signal()], margin_m=100)
    assert set(agency_signals.read_osm_signals(path, box)) == {1, 2}


def ddot_feature(oid: int, status="Active", hawk=None, point=(-77.0, 38.9)) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": list(point)} if point else None,
        "properties": {"OBJECTID": oid, "GLOBALID": f"{{G{oid}}}", "STATUS": status, "HAWK": hawk},
    }


def test_ddot_rows_keep_running_signals_and_name_the_hawks() -> None:
    doc = {
        "features": [
            ddot_feature(1),
            ddot_feature(2, hawk="Yes"),
            ddot_feature(3, status="Removed"),
            ddot_feature(4, status="Proposed"),
            ddot_feature(5, point=None),
            ddot_feature(1),
        ]
    }
    rows, dropped = agency_signals.ddot_rows(doc)
    assert [(row["id"], row["kind"]) for row in rows] == [
        ("ddot:{G1}", "signal"),
        ("ddot:{G2}", "hawk"),
    ]
    assert dropped == {
        "STATUS Removed": 1,
        "STATUS Proposed": 1,
        "no point": 1,
        "no id or a repeated id": 1,
    }


def test_the_installer_writes_what_the_rebuild_loads(tmp_path) -> None:
    layer = tmp_path / "dc-traffic-signals.geojson"
    layer.write_text(
        json.dumps({"type": "FeatureCollection", "features": [ddot_feature(1), ddot_feature(2)]})
    )
    subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "install_reference_data.py"),
            "--data-root",
            str(tmp_path),
            "--dc-signals",
            str(layer),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    loaded = agency_signals.load(tmp_path / "reference" / agency_signals.FILE_NAME)
    assert [s.feature_id for s in loaded] == ["ddot:{G1}", "ddot:{G2}"]


def test_an_absent_list_is_no_signals(tmp_path, caplog) -> None:
    assert agency_signals.load(tmp_path / "signals.json") == ()
    assert "absent" in caplog.text


def test_an_unknown_source_is_refused(tmp_path) -> None:
    path = tmp_path / "signals.json"
    path.write_text(
        json.dumps([{"id": "x", "source": "nope", "lon": 0, "lat": 0, "kind": "signal"}])
    )
    with pytest.raises(agency_signals.SignalListInvalid):
        agency_signals.load(path)


def point_feature(props: dict, point=(-77.0, 38.9)) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(point)},
            "properties": props}  # fmt: skip


def test_mdot_sha_rows_keep_traffic_control_signals_only() -> None:
    doc = {
        "features": [
            point_feature({"OBJECTID": 1, "TCD_Type": "1", "OWNER_DESC": "County"}),
            point_feature(
                {"OBJECTID": 2, "TCD_Type": "2", "OWNER_DESC": "SHA - Signal Operations"}
            ),
            point_feature({"OBJECTID": 3, "TCD_Type": "1", "OWNER_DESC": "Proposed"}),
            point_feature({"OBJECTID": 4, "TCD_Type": "B", "OWNER_DESC": "County"}),
        ]
    }
    rows, dropped = agency_signals.mdot_sha_rows(doc)
    assert [row["id"] for row in rows] == ["mdot-sha:1"]
    assert dropped == {"device type 2": 1, "OWNER_DESC Proposed": 1, "device type B": 1}


def test_arlington_rows_keep_signalised_intersections_in_service() -> None:
    doc = {
        "features": [
            point_feature(
                {
                    "OBJECTID": 1,
                    "TrafficControlType": "Signalized",
                    "ActiveProjectStatus": "Completed",
                }
            ),  # fmt: skip
            point_feature({"OBJECTID": 2, "TrafficControlType": "Stop"}),
            point_feature(
                {"OBJECTID": 3, "TrafficControlType": "Signalized", "ActiveProjectStatus": "Design"}
            ),  # fmt: skip
            point_feature(
                {"OBJECTID": 4, "TrafficControlType": "Signalized", "RetiredDate": 1700000000000}
            ),  # fmt: skip
        ]
    }
    rows, dropped = agency_signals.arlington_rows(doc)
    assert [row["id"] for row in rows] == ["arlington:1"]
    assert dropped == {"control Stop": 1, "ActiveProjectStatus Design": 1, "retired": 1}


def test_alexandria_rows_name_the_hawk_layer() -> None:
    doc = {"features": [point_feature({"OBJECTID": 7})]}
    assert agency_signals.alexandria_rows(doc)[0][0]["kind"] == "signal"
    assert agency_signals.alexandria_rows(doc, kind="hawk")[0][0]["kind"] == "hawk"


def test_a_source_without_a_confirmed_licence_is_installed_but_not_read(tmp_path, caplog) -> None:
    unconfirmed = sorted(s for s, ok in agency_signals.LICENCE_CONFIRMED.items() if not ok)
    assert unconfirmed, "every source is confirmed: drop this test's premise"
    path = tmp_path / "signals.json"
    path.write_text(json.dumps([
        {"id": "ddot:1", "source": "ddot", "lon": 0, "lat": 0, "kind": "signal"},
        {"id": "x:1", "source": unconfirmed[0], "lon": 0, "lat": 0, "kind": "signal"},
    ]))  # fmt: skip
    assert [s.feature_id for s in agency_signals.load(path)] == ["ddot:1"]
    assert "licence not yet confirmed" in caplog.text


def test_field_names_are_read_in_any_case() -> None:
    """A hosted layer may name its fields `objectid`, `GlobalID`, `trafficcontroltype`."""
    doc = {
        "features": [
            point_feature({"objectid": 3, "TrafficControlType": "Signalized"}),
            point_feature({"GlobalID": "{X}", "trafficcontroltype": "Signalized"}),
        ]
    }
    rows, _dropped = agency_signals.arlington_rows(doc)
    assert [row["id"] for row in rows] == ["arlington:3", "arlington:{X}"]


def test_the_two_alexandria_layers_numbered_alike_do_not_clash(tmp_path) -> None:
    """Layer 9 and the HAWK layer both number from OBJECTID 1."""
    signals_file = tmp_path / "alexandria-signals.geojson"
    signals_file.write_text(json.dumps({"features": [point_feature({"OBJECTID": 1})]}))
    hawks = tmp_path / "alexandria-hawks.geojson"
    hawks.write_text(json.dumps({"features": [point_feature({"OBJECTID": 1})]}))
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "install_reference_data.py"),
         "--data-root", str(tmp_path), "--alexandria-signals", str(signals_file),
         "--alexandria-hawks", str(hawks)],
        check=False, capture_output=True, text=True,
    )  # fmt: skip
    assert done.returncode in (0, 1), done.stderr  # 1: the required files are missing
    rows = json.loads((tmp_path / "reference" / agency_signals.FILE_NAME).read_text())
    assert [row["id"] for row in rows] == ["alexandria:1", "alexandria-hawk:1"]


def test_node_tags_carry_the_mark_the_transform_reads() -> None:
    assert agency_signals.node_tags({11}) == {11: {"rm:agency_signal": "yes"}}
    remap = (REPO / "lua" / "routemaker_remap.lua").read_text()
    assert f'M.AGENCY_SIGNAL_MARK = "{agency_signals.NODE_TAG}"' in remap
    assert agency_signals.NODE_TAG.startswith("rm:")


def test_the_installer_writes_every_source_into_one_file(tmp_path) -> None:
    dc = tmp_path / "dc.geojson"
    dc.write_text(json.dumps({"features": [ddot_feature(1)]}))
    hawks = tmp_path / "alexandria-hawks.geojson"
    hawks.write_text(json.dumps({"features": [point_feature({"OBJECTID": 9})]}))
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "install_reference_data.py"),
         "--data-root", str(tmp_path), "--dc-signals", str(dc), "--alexandria-hawks", str(hawks)],
        check=False, capture_output=True, text=True,
    )  # fmt: skip
    assert "2 signals (1 HAWKs)" in done.stdout, done.stderr
    rows = json.loads((tmp_path / "reference" / agency_signals.FILE_NAME).read_text())
    assert [(row["id"], row["kind"]) for row in rows] == [
        ("ddot:{G1}", "signal"),
        ("alexandria-hawk:9", "hawk"),
    ]
