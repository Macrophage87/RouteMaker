"""v0.8.0's Scenic layer: the designations in words (`routemaker.scenic`), the installer's
rows, the rebuild's matching (`pipeline.scenic_layer`), the tile flag and the road panel.

The owner, 2026-10-16: "Name in the road panel and have as a layer." and "Basically
looking for a scenic layer in general. Off by default. How about including covered
bridges". A designation never changes a way's stress.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from routemaker import scenic

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_reference_data.py"
LINE = [(-77.30 + i * 0.001, 39.20) for i in range(11)]


def _way(osm_id, coords, **tags):
    from pipeline.extract import Way

    return Way(osm_id, {"highway": "unclassified", **tags}, list(range(len(coords))), coords)


def _collection(*features) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def _feature(object_id, coordinates, **properties) -> dict:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id, **properties},
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


# --- the words -------------------------------------------------------------------------


def test_montgomery_classes_name_the_county():
    assert scenic.moco_label("Rustic Road") == "Rustic Road (Montgomery County)"
    assert scenic.moco_label(" exceptional rustic road ") == (
        "Exceptional Rustic Road (Montgomery County)"
    )
    assert scenic.moco_label("Proposed") is None
    assert scenic.moco_label(None) is None


def test_a_byway_is_named_once():
    assert scenic.byway_label("Mountain Maryland") == "Mountain Maryland Scenic Byway"
    assert scenic.byway_label("Falls Road Scenic Byway") == "Falls Road Scenic Byway"
    assert scenic.byway_label("Historic National Road  byway") == "Historic National Road byway"
    assert scenic.byway_label("  ") is None


def test_us_bicycle_routes_and_the_greenway_from_relations():
    usbr = {"type": "route", "route": "bicycle", "network": "ncn", "ref": "USBR 50"}
    assert scenic.route_label(2532740, usbr) == "USBR 50"
    assert scenic.route_label(1, {**usbr, "ref": "usbr11"}) == "USBR 11"
    # A regional route with a USBR-looking ref is not a US Bicycle Route.
    assert scenic.route_label(1, {**usbr, "network": "rcn"}) is None
    ecg = {"type": "route", "route": "bicycle", "network": "ncn", "name": "East Coast Greenway"}
    assert scenic.route_label(1774795, ecg) == "East Coast Greenway"
    section = {**ecg, "name": "East Coast Greenway (Maryland)"}
    assert scenic.route_label(99, section) == "East Coast Greenway"
    assert scenic.route_label(1774795, {**ecg, "type": "superroute"}) == "East Coast Greenway"
    # A hiking route of the same name, or an ordinary bike route, is not scenic here.
    assert scenic.route_label(5, {**ecg, "route": "hiking"}) is None
    assert scenic.route_label(5, {"type": "route", "route": "bicycle", "name": "Bike 7"}) is None


@pytest.mark.parametrize(
    ("tags", "number"),
    [
        # The USBR wiki's form.
        ({"network": "ncn", "cycle_network": "US:US", "ref": "USBR 50"}, 50),
        ({"network": "ncn", "ref": "USBR 1"}, 1),
        # A bare number on the national network (review, PR #138: the common US tagging).
        ({"network": "ncn", "cycle_network": "US:US", "ref": "50"}, 50),
        ({"network": "ncn", "cycle_network": "US", "ref": "11"}, 11),
        # The name alone.
        ({"network": "ncn", "cycle_network": "US", "name": "U.S. Bicycle Route 50"}, 50),
        ({"network": "ncn", "name": "US Bicycle Route 11 (Maryland)"}, 11),
        ({"cycle_network": "US:US", "name": "U.S. Bicycle Route 1"}, 1),
        # A state route's own number is not a USBR, nor a bare number off the network.
        ({"network": "rcn", "cycle_network": "US:MD", "ref": "50"}, None),
        ({"network": "ncn", "ref": "50"}, None),
        ({"network": "lcn", "name": "Bike Route 50"}, None),
        # The Greenway: national, no number.
        ({"network": "ncn", "cycle_network": "US", "name": "East Coast Greenway"}, None),
    ],
)
def test_each_us_bicycle_route_tagging(tags, number):
    assert scenic.usbr_number(tags) == number
    label = scenic.route_label(9, {"type": "route", "route": "bicycle", **tags})
    if number is not None:
        assert label == f"USBR {number}"


def test_the_greenway_is_never_a_usbr():
    ecg = {"type": "route", "route": "bicycle", "network": "ncn", "cycle_network": "US"}
    # Even a Greenway relation carrying a number reads as the Greenway.
    assert scenic.route_label(1774795, {**ecg, "ref": "1"}) == "East Coast Greenway"
    assert scenic.route_label(5, {**ecg, "name": "East Coast Greenway (DC)"}) == (
        "East Coast Greenway"
    )
    assert scenic.route_label(5, ecg) is None


def test_a_covered_bridge_says_its_name():
    assert (
        scenic.covered_bridge_label(
            {"bridge": "covered", "name": "Roddy Road", "bridge:name": "Roddy Road Covered Bridge"}
        )
        == "Roddy Road Covered Bridge"
    )
    assert scenic.covered_bridge_label({"bridge": "covered", "name": "Utica Mills Bridge"}) == (
        "Utica Mills Bridge"
    )
    # The road's own name is not the bridge's.
    assert scenic.covered_bridge_label({"bridge": "covered", "name": "Roddy Road"}) == (
        "Covered bridge"
    )
    # `covered=yes` is a roof over a way, not a covered bridge (the OSM wiki).
    assert scenic.covered_bridge_label({"bridge": "yes", "covered": "yes"}) is None


def test_the_phrase_is_ordered_and_says_each_once():
    assert (
        scenic.phrase(["USBR 50", "East Coast Greenway", None, "USBR 50"])
        == "East Coast Greenway · USBR 50"
    )
    assert (
        scenic.phrase(["USBR 11", "USBR 1", "Roddy Road Covered Bridge", "Catoctin Scenic Byway"])
        == "Catoctin Scenic Byway · USBR 1 · USBR 11 · Roddy Road Covered Bridge"
    )
    # A way along records of both kinds of rustic road says both (review, PR #138).
    assert (
        scenic.phrase([scenic.MOCO_RUSTIC, scenic.MOCO_EXCEPTIONAL])
        == "Exceptional Rustic Road (Montgomery County) · Rustic Road (Montgomery County)"
    )
    assert scenic.phrase([]) is None


def test_credits_name_who_designates_each():
    text = scenic.phrase([scenic.MOCO_RUSTIC, "Old Main Streets Scenic Byway", "USBR 50"])
    assert scenic.credits(text) == "Montgomery County Planning; MDOT SHA; OpenStreetMap"
    assert scenic.credits("East Coast Greenway · USBR 50") == "OpenStreetMap"
    assert scenic.credits(None) is None


# --- the installer ---------------------------------------------------------------------


def test_rustic_rows_keep_both_classes_and_drop_the_rest():
    document = _collection(
        _feature(1, LINE, CLASSLABEL2="Rustic Road", ROAD_NAME="Davis Mill Road"),
        _feature(2, LINE, CLASSLABEL2="Exceptional Rustic Road"),
        _feature(3, LINE, CLASSLABEL2="Something else"),
        {"type": "Feature", "properties": {"OBJECTID": 4, "CLASSLABEL2": "Rustic Road"}},
    )
    rows, dropped = scenic.rustic_rows(document)
    assert dropped == 2
    assert [(r["id"], r["label"], r["name"]) for r in rows] == [
        ("moco-rustic-1-0", scenic.MOCO_RUSTIC, "Davis Mill Road"),
        ("moco-rustic-2-0", scenic.MOCO_EXCEPTIONAL, None),
    ]
    assert rows[0]["source"] == scenic.MOCO_SOURCE
    assert rows[0]["coordinates"][0] == [-77.3, 39.2]


def test_byway_rows_split_multilines_and_carry_no_road_name():
    multi = {
        "type": "Feature",
        "properties": {"OBJECTID": 7, "BYWAY_NAME": "Mountain Maryland"},
        "geometry": {"type": "MultiLineString", "coordinates": [LINE[:5], LINE[5:]]},
    }
    rows, dropped = scenic.byway_rows(_collection(multi))
    assert dropped == 0
    assert [r["id"] for r in rows] == ["md-byways-7-0", "md-byways-7-1"]
    assert {r["label"] for r in rows} == {"Mountain Maryland Scenic Byway"}
    assert {r["name"] for r in rows} == {None}


def test_a_rustic_layer_with_no_road_name_is_refused():
    """The road name is the rustic roads' guard against a parallel street (review, PR #138)."""
    with pytest.raises(scenic.LayerUnreadable, match="--rustic-name-field"):
        scenic.rustic_rows(_collection(_feature(1, LINE, CLASSLABEL2="Rustic Road")))
    rows, _ = scenic.rustic_rows(
        _collection(_feature(1, LINE, CLASSLABEL2="Rustic Road", RDNM="Mill Road")), "RDNM"
    )
    assert rows[0]["name"] == "Mill Road"


def test_the_rustic_layer_names_its_roads_in_localroadname():
    """Montgomery Planning's Rustic Roads layer as downloaded, 2026-10-17."""
    rows, _ = scenic.rustic_rows(
        _collection(_feature(1, LINE, CLASSLABEL2="Rustic Road", LOCALROADNAME="Mount Nebo Rd"))
    )
    assert rows[0]["name"] == "Mount Nebo Rd"


def test_a_byway_layer_with_no_name_field_is_refused():
    with pytest.raises(scenic.LayerUnreadable, match="--byway-name-field"):
        scenic.byway_rows(_collection(_feature(1, LINE, LABEL="Mountain Maryland")))
    rows, _ = scenic.byway_rows(_collection(_feature(1, LINE, LABEL="Catoctin")), "LABEL")
    assert rows[0]["label"] == "Catoctin Scenic Byway"


def test_the_installer_writes_what_the_rebuild_loads(tmp_path):
    from pipeline import scenic_layer

    rustic = tmp_path / "rustic.geojson"
    rustic.write_text(
        json.dumps(_collection(_feature(1, LINE, CLASSLABEL2="Rustic Road", NAME="Mill Road")))
    )
    byways = tmp_path / "byways.geojson"
    byways.write_text(json.dumps(_collection(_feature(1, LINE, BYWAY_NAME="Catoctin"))))
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--data-root",
            str(tmp_path / "data"),
            "--rustic-roads",
            str(rustic),
            "--scenic-byways",
            str(byways),
        ],
        capture_output=True,
        text=True,
    )
    assert "scenic.json: 2 scenic lines" in done.stdout, done.stderr
    features, labels = scenic_layer.load(tmp_path / "data" / "reference" / scenic_layer.FILE_NAME)
    assert len(features) == 2
    assert sorted(labels.values()) == ["Catoctin Scenic Byway", scenic.MOCO_RUSTIC]


# --- the rebuild -----------------------------------------------------------------------


def test_an_absent_file_is_no_designation(tmp_path, caplog):
    from pipeline import scenic_layer

    assert scenic_layer.load(tmp_path / "scenic.json") == ((), {})
    assert "--rustic-roads" in caplog.text


def test_an_unknown_source_is_refused(tmp_path):
    from pipeline import scenic_layer

    path = tmp_path / "scenic.json"
    path.write_text(
        json.dumps([{"id": "x", "source": "va-byways", "label": "A", "coordinates": LINE}])
    )
    with pytest.raises(scenic_layer.ScenicLayerInvalid, match="va-byways"):
        scenic_layer.load(path)


def test_a_road_along_both_layers_takes_both(tmp_path):
    from pipeline import scenic_layer

    rows = [
        *scenic.rustic_rows(
            _collection(_feature(1, LINE, CLASSLABEL2="Rustic Road", ROAD_NAME="Davis Mill Road"))
        )[0],
        *scenic.byway_rows(_collection(_feature(1, LINE, BYWAY_NAME="Catoctin")))[0],
    ]
    path = tmp_path / "scenic.json"
    path.write_text(json.dumps(rows))
    features, labels = scenic_layer.load(path)
    along = _way(42, LINE, name="Davis Mill Road")
    elsewhere = _way(43, [(-77.0 + i * 0.001, 38.9) for i in range(11)])
    found = scenic_layer.labels_by_way([along, elsewhere], features, labels)
    assert found == {42: {scenic.MOCO_RUSTIC, "Catoctin Scenic Byway"}}
    # A trail along the same line is never a candidate (the street blocks' rule).
    assert scenic_layer.labels_by_way([along], features, labels, frozenset({42})) == {}


def test_a_record_missing_a_key_is_refused_not_a_key_error(tmp_path):
    from pipeline import scenic_layer

    path = tmp_path / "scenic.json"
    path.write_text(json.dumps([{"id": "x", "source": "md-byways", "coordinates": LINE}]))
    with pytest.raises(scenic_layer.ScenicLayerInvalid, match="no label"):
        scenic_layer.load(path)


def test_a_byway_keeps_off_a_parallel_street_a_ramp_and_a_connector(tmp_path):
    """A byway record names no road, so the name veto cannot guard it (review, PR #138): a
    residential street about 10 m beside it, a ramp along it and a service road on it never
    take it, and a short connector that only touches its end does not either."""
    from pipeline import scenic_layer

    rows, _ = scenic.byway_rows(_collection(_feature(1, LINE, BYWAY_NAME="Catoctin")))
    path = tmp_path / "scenic.json"
    path.write_text(json.dumps(rows))
    features, labels = scenic_layer.load(path)
    beside = [(lon, lat + 0.00009) for lon, lat in LINE]  # about 33 ft (10 m) north
    byway = _way(1, LINE, highway="secondary", name="Hessong Bridge Road")
    parallel = _way(2, beside, highway="residential", name="Elm Street")
    ramp = _way(3, LINE[2:6], highway="secondary_link")
    service = _way(4, LINE[3:7], highway="service")
    # A road that runs on past the record's end: under BYWAY_MIN_COVERAGE of it is alongside.
    # (unclassified, so only the coverage bar keeps it off: it would match at the blocks' half).
    connector = _way(5, [*LINE[4:], *[(LINE[-1][0] + i * 0.001, 39.20) for i in range(1, 5)]])
    found = scenic_layer.labels_by_way(
        [byway, parallel, ramp, service, connector], features, labels
    )
    assert found == {1: {"Catoctin Scenic Byway"}}


def test_a_rustic_record_keeps_off_a_differently_named_parallel_street(tmp_path):
    from pipeline import scenic_layer

    rows, _ = scenic.rustic_rows(
        _collection(_feature(1, LINE, CLASSLABEL2="Rustic Road", ROAD_NAME="Mount Nebo Road"))
    )
    path = tmp_path / "scenic.json"
    path.write_text(json.dumps(rows))
    features, labels = scenic_layer.load(path)
    beside = [(lon, lat + 0.00009) for lon, lat in LINE]
    found = scenic_layer.labels_by_way(
        [_way(1, LINE, name="Mount Nebo Road"), _way(2, beside, name="Elm Street")],
        features,
        labels,
    )
    assert found == {1: {scenic.MOCO_RUSTIC}}


def test_a_section_relation_takes_its_parents_name_and_cycles_end():
    from pipeline.scenic_layer import route_labels

    found = route_labels(
        labels={1774795: "East Coast Greenway", 50: "USBR 50"},
        ways={1774795: [1], 7: [2], 8: [3], 50: [3]},
        children={1774795: [7], 7: [8], 8: [7]},
    )
    assert found == {
        1: {"East Coast Greenway"},
        2: {"East Coast Greenway"},
        3: {"East Coast Greenway", "USBR 50"},
    }


def test_the_routes_are_read_from_the_extract(tmp_path):
    from pipeline.scenic_layer import read_routes

    osm = tmp_path / "routes.osm"
    osm.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <relation id="1774795" version="1">
    <member type="relation" ref="10" role=""/>
    <tag k="type" v="superroute"/><tag k="route" v="bicycle"/>
    <tag k="name" v="East Coast Greenway"/><tag k="network" v="ncn"/>
  </relation>
  <relation id="10" version="1">
    <member type="way" ref="100" role=""/>
    <tag k="type" v="route"/><tag k="route" v="bicycle"/><tag k="name" v="MD section"/>
  </relation>
  <relation id="2532740" version="1">
    <member type="way" ref="100" role=""/><member type="way" ref="101" role=""/>
    <tag k="type" v="route"/><tag k="route" v="bicycle"/>
    <tag k="network" v="ncn"/><tag k="ref" v="USBR 50"/>
  </relation>
  <relation id="11" version="1">
    <member type="way" ref="103" role=""/>
    <tag k="type" v="route"/><tag k="route" v="bicycle"/>
    <tag k="network" v="ncn"/><tag k="cycle_network" v="US:US"/><tag k="ref" v="11"/>
  </relation>
  <relation id="3" version="1">
    <member type="way" ref="102" role=""/>
    <tag k="type" v="route"/><tag k="route" v="hiking"/><tag k="ref" v="USBR 50"/>
  </relation>
</osm>
"""
    )
    assert read_routes(osm) == {
        100: {"East Coast Greenway", "USBR 50"},
        101: {"USBR 50"},
        103: {"USBR 11"},
    }


def test_the_words_combine_every_source():
    from pipeline.scenic_layer import scenic_by_way

    bridge = _way(5, LINE, bridge="covered", **{"bridge:name": "Jericho Covered Bridge"})
    towpath = _way(6, LINE)
    plain = _way(7, LINE)
    found = scenic_by_way(
        [bridge, towpath, plain],
        agency={5: {scenic.MOCO_RUSTIC}},
        routes={6: {"USBR 50", "East Coast Greenway"}},
    )
    assert found == {
        5: "Rustic Road (Montgomery County) · Jericho Covered Bridge",
        6: "East Coast Greenway · USBR 50",
    }


def test_a_designation_is_never_a_stress_input():
    """The classifier and the graph never read the scenic modules: a scenic road keeps its
    tier and gets no routing bonus (the brief: "Stress ratings MUST NOT change")."""
    for path in (
        REPO / "src" / "routemaker" / "stress.py",
        REPO / "src" / "routemaker" / "agency_lts.py",
        REPO / "src" / "pipeline" / "variants.py",
        REPO / "lua" / "routemaker_remap.lua",
        REPO / "lua" / "graph.lua",
    ):
        assert "scenic" not in path.read_text().casefold(), path


def test_a_covered_bridge_classifies_as_any_bridge():
    from routemaker.stress import classify

    tags = {"highway": "tertiary", "maxspeed": "30 mph", "lanes": "2"}
    plain = classify({**tags, "bridge": "yes"})
    covered = classify({**tags, "bridge": "covered", "bridge:name": "Roddy Road Covered Bridge"})
    assert (covered.tier, covered.rule) == (plain.tier, plain.rule)


# --- the tiles and the road panel ------------------------------------------------------


def test_the_tiles_carry_a_flag_not_the_words():
    from core import stress_tiles
    from pipeline.schema import SCENIC_COLUMN

    sql = stress_tiles.tile_sql(stress_tiles.FULL, frozenset({SCENIC_COLUMN}))
    assert f"CASE WHEN s.{SCENIC_COLUMN} IS NOT NULL THEN true END AS scenic" in sql
    assert "AS scenic" not in stress_tiles.tile_sql(stress_tiles.FULL)
    tag = stress_tiles.etag_for(1234567890, frozenset(stress_tiles.ETAG_LETTERS))
    assert len(tag) <= 64 - len("-e999999")
    assert len(set(stress_tiles.ETAG_LETTERS.values())) == len(stress_tiles.ETAG_LETTERS)


def _row(**extra) -> dict:
    return {
        "osm_way_id": 42,
        "stress_tier": 2,
        "stress_rule": "",
        "stress_assumed": [],
        "volume_source": None,
        "volume_aadt": None,
        "volume_year": None,
        "is_trail_class": False,
        "is_unpaved": False,
        "is_rough": False,
        "distance_m": 1.0,
        "on_lon": -77.3,
        "on_lat": 39.2,
        **extra,
    }


def test_the_road_panel_says_the_designations_in_words():
    from core import segment_info

    row = _row(scenic="East Coast Greenway · USBR 50")
    summary = segment_info.summary_rows(row, {}, True)
    assert {"id": "scenic", "label": "Scenic", "value": "East Coast Greenway · USBR 50"} in summary
    answer = segment_info.describe(row, {"name": "Clara Barton Parkway"})
    road = next(s for s in answer["sections"] if s["id"] == "road")
    assert {
        "label": "Scenic",
        "value": "East Coast Greenway · USBR 50",
        "source": "OpenStreetMap",
    } in road["rows"]


def test_no_designation_no_row():
    from core import segment_info

    for row in (_row(), _row(scenic=None), _row(scenic=" ")):
        assert all(r["id"] != "scenic" for r in segment_info.summary_rows(row, {}, True))
        assert segment_info.scenic_rows(row) == []
    assert "scenic" in segment_info.OPTIONAL_COLUMNS
