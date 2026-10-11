"""The water and restrooms layer's build step (scripts/build_water_restrooms.py).

Run against a small made-up extract: which OSM features count, which are left
out, and the file the front end reads.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_water_restrooms.py"

spec = importlib.util.spec_from_file_location("build_water_restrooms", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_water_restrooms"] = mod
spec.loader.exec_module(mod)

IN = (-77.0, 38.9)


def _kind(tags: dict[str, str]) -> tuple[str | None, str | None] | None:
    a = mod.classify("n1", tags, *IN)
    return (a.water, a.toilet) if a else None


@pytest.mark.parametrize(
    "tags, kind",
    [
        ({"amenity": "drinking_water"}, ("p", None)),
        # Marked undrinkable: still a source, for a rider with a filter.
        ({"amenity": "drinking_water", "drinking_water": "no"}, ("n", None)),
        ({"amenity": "water_point"}, ("p", None)),
        ({"amenity": "water_point", "drinking_water": "no"}, ("n", None)),
        # A tap, well or spring is drinkable only when marked so.
        ({"man_made": "water_tap"}, ("n", None)),
        ({"man_made": "water_tap", "drinking_water": "yes"}, ("p", None)),
        ({"man_made": "water_well", "drinking_water": "no"}, ("n", None)),
        ({"natural": "spring"}, ("n", None)),
        ({"natural": "spring", "drinking_water": "yes"}, ("p", None)),
        ({"amenity": "fountain"}, None),
        ({"amenity": "fountain", "drinking_water": "yes"}, ("p", None)),
        ({"amenity": "restaurant", "drinking_water": "yes"}, None),
        # Restrooms by how they flush.
        ({"amenity": "toilets"}, (None, "u")),
        ({"amenity": "toilets", "toilets:disposal": "flush"}, (None, "f")),
        ({"amenity": "toilets", "toilets:disposal": "chemical"}, (None, "b")),
        ({"amenity": "toilets", "toilets:disposal": "pitlatrine"}, (None, "b")),
        ({"amenity": "toilets", "toilets:disposal": "composting"}, (None, "b")),
        ({"amenity": "toilets", "portable": "yes"}, (None, "b")),
        ({"amenity": "toilets", "toilets:disposal": "flush;chemical"}, (None, "f")),
        ({"amenity": "toilets", "drinking_water": "yes"}, ("p", "u")),
        ({"amenity": "toilets", "drinking_water": "no"}, (None, "u")),
        # Public only, in use only.
        ({"amenity": "toilets", "access": "public"}, (None, "u")),
        ({"amenity": "toilets", "access": "permissive"}, (None, "u")),
        ({"amenity": "toilets", "access": "customers"}, None),
        ({"amenity": "toilets", "access": "private"}, None),
        ({"amenity": "drinking_water", "access": "no"}, None),
        ({"natural": "spring", "access": "private"}, None),
        ({"amenity": "toilets", "disused": "yes"}, None),
        ({"disused:amenity": "toilets"}, None),
        ({"amenity": "toilets", "abandoned": "yes"}, None),
        # Every basic disposal value, and access values that are public.
        ({"amenity": "toilets", "toilets:disposal": "bucket"}, (None, "b")),
        ({"amenity": "toilets", "toilets:disposal": "dry_toilet"}, (None, "b")),
        ({"amenity": "toilets", "toilets:disposal": "incineration"}, (None, "b")),
        ({"amenity": "toilets", "toilets:disposal": "flush ; chemical"}, (None, "f")),
        ({"amenity": "toilets", "access": "yes"}, (None, "u")),
        ({"amenity": "toilets", "access": "designated"}, (None, "u")),
        # More water sources.
        ({"amenity": "shelter", "drinking_water": "yes"}, ("p", None)),
        ({"amenity": "shelter"}, None),
        ({"man_made": "water_well"}, ("n", None)),
        ({"man_made": "water_tap", "drinking_water": "no"}, ("n", None)),
        # Historic springs are landmarks, not sources, unless marked drinkable.
        ({"natural": "spring", "historic": "yes"}, None),
        ({"natural": "spring", "historic": "spring"}, None),
        ({"natural": "spring", "historic": "memorial", "drinking_water": "no"}, None),
        ({"natural": "spring", "ruins": "yes"}, None),
        ({"natural": "spring", "historic": "no"}, ("n", None)),
        ({"natural": "spring", "historic": "yes", "drinking_water": "yes"}, ("p", None)),
        ({"amenity": "drinking_water", "natural": "spring", "historic": "yes"}, ("p", None)),
        ({"amenity": "water_point", "natural": "spring", "historic": "yes"}, ("p", None)),
        # A historic fountain that still runs is drinking water.
        ({"amenity": "drinking_water", "historic": "yes"}, ("p", None)),
    ],
)
def test_what_counts(tags, kind):
    assert _kind(tags) == kind


def test_outside_the_coverage_box_is_dropped():
    assert mod.classify("n1", {"amenity": "toilets"}, -80.0, 38.9) is None


def test_settings_box_matches():
    text = (REPO / "src" / "config" / "settings.py").read_text()
    assert f"COVERAGE_BBOX = {mod.COVERAGE_BBOX}" in text


def test_details_kept_and_cleaned():
    a = mod.classify(
        "n1",
        {
            "amenity": "drinking_water",
            "name": "  Mile  4\nfountain ",
            "fee": "no",
            "wheelchair": "maybe",
            "opening_hours": "Apr-Oct",
            "seasonal": "summer",
            "bottle": "yes",
        },
        -77.0000049,
        38.9123456,
    )
    assert (a.lon, a.lat) == (-77.0, 38.91235)
    assert a.name == "Mile 4 fountain"
    assert a.fee == "no"
    assert a.wheelchair is None
    assert a.hours == "Apr-Oct"
    assert a.seasonal == "summer"
    assert a.bottle is True
    # A bottle filler is said of drinking water only.
    assert mod.classify("n1", {"man_made": "water_tap", "bottle": "yes"}, *IN).bottle is False
    assert mod.classify("n1", {"amenity": "toilets", "seasonal": "no"}, *IN).seasonal is None
    # Values outside the few the front end knows are dropped, not passed on.
    odd = mod.classify("n1", {"amenity": "toilets", "fee": "donation", "wheelchair": "bad"}, *IN)
    assert (odd.fee, odd.wheelchair) == (None, None)
    kept = mod.classify("n1", {"amenity": "toilets", "fee": "yes", "wheelchair": "limited"}, *IN)
    assert (kept.fee, kept.wheelchair) == ("yes", "limited")


def test_document_is_short_and_sorted():
    doc = mod.document(
        [
            mod.Amenity("w5", -77.1, 38.8, None, "f", name="Comfort station"),
            mod.Amenity("n20", -77.2, 38.7, "p", None, bottle=True),
            mod.Amenity("n3", -77.3, 38.6, "p", "b", fee="yes"),
            mod.Amenity("throne-a", -77.0, 38.9, None, "f", op="Throne"),
            mod.Amenity("n4", -77.4, 38.5, None, "u", op="Throne"),
        ]
    )
    assert doc["source"] == "OpenStreetMap contributors, ODbL 1.0"
    assert doc["also"].startswith("Throne units: throne-restrooms.json")
    # OSM nodes, then ways, by number; the Throne list's units last.
    assert doc["points"] == [
        {"id": "n3", "x": -77.3, "y": 38.6, "w": "p", "t": "b", "fee": "yes"},
        {"id": "n4", "x": -77.4, "y": 38.5, "t": "u", "op": "Throne"},
        {"id": "n20", "x": -77.2, "y": 38.7, "w": "p", "b": 1},
        {"id": "w5", "x": -77.1, "y": 38.8, "t": "f", "n": "Comfort station"},
        {"id": "throne-a", "x": -77.0, "y": 38.9, "t": "f", "op": "Throne"},
    ]


OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
 <node id="1" version="1" lat="38.90" lon="-77.00">
  <tag k="amenity" v="drinking_water"/>
 </node>
 <node id="2" version="1" lat="38.91" lon="-77.01">
  <tag k="amenity" v="toilets"/><tag k="access" v="customers"/>
 </node>
 <node id="3" version="1" lat="38.92" lon="-77.02"/>
 <node id="4" version="1" lat="38.92" lon="-77.00"/>
 <node id="5" version="1" lat="38.94" lon="-77.00"/>
 <node id="6" version="1" lat="38.94" lon="-77.02"/>
 <node id="7" version="1" lat="38.95" lon="-77.03">
  <tag k="amenity" v="bench"/>
 </node>
 <node id="8" version="1" lat="38.96" lon="-77.04">
  <tag k="natural" v="spring"/>
 </node>
 <node id="9" version="1" lat="38.93" lon="-77.01">
  <tag k="amenity" v="toilets"/><tag k="opening_hours" v="dawn-dusk"/><tag k="fee" v="no"/>
 </node>
 <node id="11" version="1" lat="38.97" lon="-77.05">
  <tag k="natural" v="spring"/><tag k="historic" v="yes"/><tag k="name" v="Old Spring"/>
 </node>
 <way id="10" version="1">
  <nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/>
  <tag k="amenity" v="toilets"/><tag k="building" v="yes"/><tag k="name" v="Comfort station"/>
  <tag k="toilets:disposal" v="flush"/>
 </way>
</osm>
"""


SQUARE = ((-77.02, 38.92), (-77.0, 38.92), (-77.0, 38.94), (-77.02, 38.94))


def _building(tags: dict[str, str]):
    return mod.Element("w10", tags, -77.01, 38.93, SQUARE)


def test_a_node_inside_a_restroom_building_merges_into_it():
    building = _building({"amenity": "toilets", "building": "yes", "name": "Comfort station"})
    node = mod.Element(
        "n5",
        {
            "amenity": "toilets",
            "toilets:disposal": "flush",
            "opening_hours": "06:00-22:00",
            "wheelchair": "yes",
            "fee": "no",
        },
        -77.005,
        38.935,
    )
    (merged,) = mod.merge_restrooms([node], [building])
    assert (merged.osm, merged.lon, merged.lat) == ("w10", -77.01, 38.93)
    a = mod.classify(merged.osm, merged.tags, merged.lon, merged.lat)
    assert (a.toilet, a.name, a.hours, a.wheelchair, a.fee) == (
        "f",
        "Comfort station",
        "06:00-22:00",
        "yes",
        "no",
    )


def test_the_richer_element_wins_a_conflict():
    rich = _building({"building": "toilets", "name": "Boathouse", "fee": "yes", "wheelchair": "no"})
    poor = mod.Element("n5", {"amenity": "toilets", "fee": "no"}, -77.01, 38.93)
    (merged,) = mod.merge_restrooms([poor], [rich])
    assert merged.tags["fee"] == "yes" and merged.tags["amenity"] == "toilets"
    # On a tie the node, mapped as the restroom itself, wins.
    tie = _building({"amenity": "toilets", "fee": "yes"})
    (merged,) = mod.merge_restrooms([poor], [tie])
    assert merged.tags["fee"] == "no"


def test_several_nodes_in_one_building_are_one_place():
    building = _building({"building": "toilets"})
    nodes = [
        mod.Element("n5", {"amenity": "toilets", "male": "yes"}, -77.015, 38.93),
        mod.Element("n6", {"amenity": "toilets", "female": "yes"}, -77.005, 38.93),
    ]
    (merged,) = mod.merge_restrooms(nodes, [building])
    assert merged.osm == "w10" and merged.tags["male"] == merged.tags["female"] == "yes"


def test_a_node_outside_the_building_stays_its_own_place():
    building = _building({"amenity": "toilets", "building": "yes"})
    node = mod.Element("n5", {"amenity": "toilets"}, -77.03, 38.93)
    assert [e.osm for e in mod.merge_restrooms([node], [building])] == ["w10", "n5"]
    # A bare building=toilets with nothing inside says nothing of public use.
    bare = _building({"building": "toilets"})
    assert [e.osm for e in mod.merge_restrooms([node], [bare])] == ["n5"]


def test_a_building_that_is_not_public_is_left_out_with_what_is_inside():
    building = _building({"amenity": "toilets", "access": "customers"})
    node = mod.Element("n5", {"amenity": "toilets", "access": "yes"}, -77.01, 38.93)
    assert mod.merge_restrooms([node], [building]) == []


def test_a_private_node_inside_a_public_building_is_left_out_alone():
    building = _building({"amenity": "toilets", "name": "Comfort station"})
    staff = mod.Element("n5", {"amenity": "toilets", "access": "private"}, -77.01, 38.93)
    merged = mod.merge_restrooms([staff], [building])
    assert [e.osm for e in merged] == ["w10"]
    assert merged[0].tags.get("access") is None
    # A bare building=toilets whose only node is private shows nothing.
    bare = _building({"building": "toilets"})
    assert mod.merge_restrooms([staff], [bare]) == []


def test_a_node_in_the_box_but_outside_a_concave_building_is_not_merged():
    # An L: the square with its north-east quarter cut away.
    ell = (
        (-77.02, 38.92),
        (-77.0, 38.92),
        (-77.0, 38.93),
        (-77.01, 38.93),
        (-77.01, 38.94),
        (-77.02, 38.94),
    )
    building = mod.Element("w10", {"amenity": "toilets"}, -77.013, 38.928, ell)
    notch = mod.Element("n5", {"amenity": "toilets"}, -77.005, 38.935)
    assert [e.osm for e in mod.merge_restrooms([notch], [building])] == ["w10", "n5"]
    inner = mod.Element("n6", {"amenity": "toilets"}, -77.015, 38.925)
    assert [e.osm for e in mod.merge_restrooms([inner], [building])] == ["w10"]


def test_reads_an_extract_and_writes_the_file(tmp_path):
    pytest.importorskip("osmium")
    src = tmp_path / "tiny.osm"
    src.write_text(OSM)
    out = tmp_path / "out" / "water-restrooms.json"
    empty = tmp_path / "throne.json"
    empty.write_text('{"units": []}')
    assert mod.main(["--pbf", str(src), "--out", str(out), "--throne", str(empty)]) == 0
    text = out.read_text()
    doc = json.loads(text)
    assert doc["points"] == [
        {"id": "n1", "x": -77.0, "y": 38.9, "w": "p"},
        {"id": "n8", "x": -77.04, "y": 38.96, "w": "n"},
        # The building's mean corner, its first node counted once.
        # Node 9 inside it is merged: one restroom, with the node's details.
        {
            "id": "w10",
            "x": -77.01,
            "y": 38.93,
            "t": "f",
            "n": "Comfort station",
            "fee": "no",
            "h": "dawn-dusk",
        },
    ]
    assert text.count("\n") == 5  # one point per line


def test_bundled_file_is_well_formed():
    doc = json.loads(mod.OUT.read_text())
    assert doc["source"] == "OpenStreetMap contributors, ODbL 1.0"
    west, south, east, north = mod.COVERAGE_BBOX
    ids = [p["id"] for p in doc["points"]]
    assert len(ids) == len(set(ids))
    for p in doc["points"]:
        assert p.get("w") in (None, "p", "n") and p.get("t") in (None, "f", "b", "u")
        assert "w" in p or "t" in p
        assert west <= p["x"] <= east and south <= p["y"] <= north
        assert p.get("op") in (None, "Throne")
        if p["id"].startswith("throne-"):
            assert p["op"] == "Throne" and p["t"] == "f"


# --- Where the public cannot walk in (owner request, 2026-10-11) ------------


@pytest.mark.parametrize(
    "tags, kind",
    [
        ({"aeroway": "aerodrome"}, "airport"),
        ({"aeroway": "terminal", "building": "yes"}, "airport"),
        ({"aeroway": "apron"}, None),
        ({"aeroway": "heliport"}, None),
        ({"landuse": "military"}, "military"),
        ({"military": "base"}, "military"),
        ({"military": "airfield"}, "military"),
        ({"military": "barracks"}, "military"),
        # A danger area is often open water or public land by a range.
        ({"military": "danger_area"}, None),
        ({"military": "no"}, None),
        ({"amenity": "prison"}, "prison"),
        ({"leisure": "park"}, None),
        ({"amenity": "toilets"}, None),
    ],
)
def test_secured_kind(tags, kind):
    assert mod.secured_kind(tags) == kind


def test_inside_a_secured_area_is_left_out_but_not_in_its_hole():
    square = ((-77.1, 38.8), (-77.0, 38.8), (-77.0, 38.9), (-77.1, 38.9))
    hole = ((-77.06, 38.84), (-77.04, 38.84), (-77.04, 38.86), (-77.06, 38.86))
    area = mod.SecuredArea("airport", square, (hole,))
    inside = mod.Element("n1", {"amenity": "toilets"}, -77.09, 38.81)
    in_hole = mod.Element("n2", {"amenity": "toilets"}, -77.05, 38.85)
    outside = mod.Element("n3", {"amenity": "toilets"}, -77.2, 38.85)
    kept, left_out = mod.leave_out_secured([inside, in_hole, outside], [area])
    assert [e.osm for e in kept] == ["n2", "n3"]
    assert left_out == {"airport": 1}
    # No secured areas: everything stays.
    assert mod.leave_out_secured([inside], []) == ([inside], {})


SECURED_OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
 <node id="1" version="1" lat="38.80" lon="-77.10"/>
 <node id="2" version="1" lat="38.80" lon="-77.00"/>
 <node id="3" version="1" lat="38.90" lon="-77.00"/>
 <node id="4" version="1" lat="38.90" lon="-77.10"/>
 <node id="5" version="1" lat="38.84" lon="-77.06"/>
 <node id="6" version="1" lat="38.84" lon="-77.04"/>
 <node id="7" version="1" lat="38.86" lon="-77.04"/>
 <node id="8" version="1" lat="38.86" lon="-77.06"/>
 <node id="11" version="1" lat="39.00" lon="-76.80"/>
 <node id="12" version="1" lat="39.00" lon="-76.70"/>
 <node id="13" version="1" lat="39.10" lon="-76.70"/>
 <node id="14" version="1" lat="39.10" lon="-76.80"/>
 <node id="21" version="1" lat="38.60" lon="-76.80"/>
 <node id="22" version="1" lat="38.60" lon="-76.70"/>
 <node id="23" version="1" lat="38.70" lon="-76.70"/>
 <node id="24" version="1" lat="38.70" lon="-76.80"/>
 <node id="31" version="1" lat="39.30" lon="-76.80"/>
 <node id="32" version="1" lat="39.30" lon="-76.70"/>
 <node id="33" version="1" lat="39.40" lon="-76.70"/>
 <node id="34" version="1" lat="39.40" lon="-76.80"/>
 <node id="101" version="1" lat="38.81" lon="-77.09">
  <tag k="amenity" v="toilets"/><tag k="access" v="yes"/>
 </node>
 <node id="102" version="1" lat="38.85" lon="-77.05">
  <tag k="amenity" v="toilets"/>
 </node>
 <node id="103" version="1" lat="39.05" lon="-76.75">
  <tag k="amenity" v="toilets"/>
 </node>
 <node id="104" version="1" lat="38.65" lon="-76.75">
  <tag k="amenity" v="drinking_water"/>
 </node>
 <node id="105" version="1" lat="39.35" lon="-76.75">
  <tag k="amenity" v="toilets"/>
 </node>
 <node id="106" version="1" lat="38.95" lon="-77.20">
  <tag k="amenity" v="toilets"/>
 </node>
 <way id="1001" version="1">
  <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
 </way>
 <way id="1002" version="1">
  <nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/>
 </way>
 <relation id="5001" version="1">
  <member type="way" ref="1001" role="outer"/>
  <member type="way" ref="1002" role="inner"/>
  <tag k="type" v="multipolygon"/><tag k="aeroway" v="aerodrome"/><tag k="name" v="Test Airport"/>
 </relation>
 <way id="2001" version="1">
  <nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="11"/>
  <tag k="landuse" v="military"/>
 </way>
 <way id="2002" version="1">
  <nd ref="21"/><nd ref="22"/><nd ref="23"/><nd ref="24"/><nd ref="21"/>
  <tag k="amenity" v="prison"/>
 </way>
 <way id="2003" version="1">
  <nd ref="31"/><nd ref="32"/><nd ref="33"/><nd ref="34"/><nd ref="31"/>
  <tag k="military" v="danger_area"/>
 </way>
</osm>
"""


def test_an_extract_leaves_out_airports_bases_and_prisons(tmp_path, capsys):
    pytest.importorskip("osmium")
    src = tmp_path / "secured.osm"
    src.write_text(SECURED_OSM)
    found, left_out = mod.read_extract(src)
    # 101 is in the airport relation (even marked access=yes: airside);
    # 102 is in the relation's hole; 103 on the base; 104 (water) in the prison;
    # 105 in a danger area, which stays; 106 is outside everything.
    assert sorted(a.osm for a in found) == ["n102", "n105", "n106"]
    assert left_out == {"airport": 1, "military": 1, "prison": 1}
    empty = tmp_path / "throne.json"
    empty.write_text('{"units": []}')
    out = tmp_path / "out.json"
    assert mod.main(["--pbf", str(src), "--out", str(out), "--throne", str(empty)]) == 0
    assert (
        "left out inside airports, military sites and prisons: 3 (airport 1, military 1, prison 1)"
        in capsys.readouterr().out
    )


# --- Throne smart restrooms (owner request, 2026-10-11) ----------------------


def _unit(uid="throne-x", status="open", lon=-77.0, lat=38.9, **extra):
    u = {
        "id": uid,
        "name": "Throne, Test Plaza",
        "lat": lat,
        "lon": lon,
        "jurisdiction": "DC",
        "status": status,
        "sources": [{"url": "https://example.org/a", "read": "2026-10-11"}],
    }
    u.update(extra)
    return u


M_LAT = 1 / 111_320  # one metre north, in degrees


def test_a_unit_far_from_osm_restrooms_is_added_as_a_free_accessible_flush_restroom():
    points, added, matched = mod.merge_throne([], [_unit()])
    assert (added, matched) == (1, 0)
    (p,) = points
    assert (p.osm, p.toilet, p.fee, p.wheelchair, p.op, p.name) == (
        "throne-x",
        "f",
        "no",
        "yes",
        "Throne",
        "Throne, Test Plaza",
    )


def test_a_unit_within_50_ft_of_an_osm_restroom_is_that_restroom():
    osm = mod.Amenity("n7", -77.0, 38.9 + 14 * M_LAT, None, "u", name="Plaza toilet")
    points, added, matched = mod.merge_throne([osm], [_unit()])
    assert (added, matched) == (0, 1)
    assert points == [
        mod.Amenity("n7", -77.0, 38.9 + 14 * M_LAT, None, "u", name="Plaza toilet", op="Throne")
    ]
    # Just past 50 ft (15 m): a separate restroom, so both show.
    far = mod.Amenity("n7", -77.0, 38.9 + 16 * M_LAT, None, "u")
    points, added, matched = mod.merge_throne([far], [_unit()])
    assert (added, matched) == (1, 0) and [p.osm for p in points] == ["n7", "throne-x"]
    # Water alone is not a restroom to match.
    tap = mod.Amenity("n8", -77.0, 38.9, "p", None)
    assert mod.merge_throne([tap], [_unit()])[1] == 1


def test_an_osm_restroom_tagged_as_a_throne_matches_from_further():
    tagged = mod.classify(
        "n9", {"amenity": "toilets", "operator": "Throne Labs"}, -77.0, 38.9 + 120 * M_LAT
    )
    assert tagged.op == "Throne"
    points, added, matched = mod.merge_throne([tagged], [_unit()])
    assert (added, matched) == (0, 1) and points[0].osm == "n9"
    beyond = replace_lat(tagged, 38.9 + 160 * M_LAT)
    assert mod.merge_throne([beyond], [_unit()])[1:] == (1, 0)


def replace_lat(a, lat):
    import dataclasses

    return dataclasses.replace(a, lat=lat)


def test_only_open_units_are_added_and_a_rerun_is_the_same():
    units = [
        _unit("throne-a"),
        _unit("throne-b", "unverified", lon=-77.1),
        _unit("throne-c", "opens soon", lon=-77.2),
    ]
    once, added, _ = mod.merge_throne([], units)
    assert added == 1 and [p.osm for p in once] == ["throne-a"]
    twice, added, _ = mod.merge_throne(once, units)
    assert twice == once and added == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "x-1"},
        {"status": "closed"},
        {"name": ""},
        {"jurisdiction": ""},
        {"lat": "38.9"},
        {"sources": []},
        {"sources": [{"url": "https://example.org"}]},
        {"sources": [{"read": "2026-10-11"}]},
    ],
)
def test_the_list_is_checked(tmp_path, bad):
    path = tmp_path / "throne.json"
    path.write_text(json.dumps({"units": [_unit(**bad)]}))
    with pytest.raises(ValueError):
        mod.load_throne(path)
    path.write_text(json.dumps({"units": [_unit(), _unit()]}))
    with pytest.raises(ValueError, match="unique"):
        mod.load_throne(path)


def test_the_bundled_list_is_valid_sourced_and_in_the_box():
    units = mod.load_throne(mod.THRONE_LIST)
    west, south, east, north = mod.COVERAGE_BBOX
    for u in units:
        assert west <= u["lon"] <= east and south <= u["lat"] <= north, u["id"]
        assert u.get("placement"), u["id"]
        for s in u["sources"]:
            assert s.get("by") or s["url"].startswith("https://"), u["id"]
            assert "google" not in s.get("url", "").lower(), u["id"]
    # DC, Maryland and Virginia all have units (the owner: "They are in Maryland and Virginia too").
    assert {u["jurisdiction"][:2] for u in units} == {"DC", "MD", "VA"}


def test_the_bundled_file_has_every_open_unit():
    doc = json.loads(mod.OUT.read_text())
    throne = [p for p in doc["points"] if p.get("op") == "Throne"]
    open_units = [u for u in mod.load_throne(mod.THRONE_LIST) if u["status"] == "open"]
    assert len(throne) == len(open_units)
    shut = {u["id"] for u in mod.load_throne(mod.THRONE_LIST) if u["status"] != "open"}
    assert not shut & {p["id"] for p in doc["points"]}


def test_throne_only_refreshes_the_units_and_keeps_the_osm_points(tmp_path):
    out = tmp_path / "w.json"
    mod.write_document(
        mod.document(
            [
                mod.Amenity("n1", -77.3, 38.6, "p", None),
                mod.Amenity("n2", -77.0, 38.9 + 5 * M_LAT, None, "f", op="Throne"),
                mod.Amenity("throne-old", -77.2, 38.7, None, "f", op="Throne"),
            ]
        ),
        out,
    )
    units = tmp_path / "throne.json"
    units.write_text(json.dumps({"units": [_unit("throne-near"), _unit("throne-new", lon=-76.5)]}))
    assert mod.main(["--throne-only", "--out", str(out), "--throne", str(units)]) == 0
    doc = json.loads(out.read_text())
    assert doc["points"] == [
        {"id": "n1", "x": -77.3, "y": 38.6, "w": "p"},
        {"id": "n2", "x": -77.0, "y": 38.9 + 5 * M_LAT, "t": "f", "op": "Throne"},
        {
            "id": "throne-new",
            "x": -76.5,
            "y": 38.9,
            "t": "f",
            "n": "Throne, Test Plaza",
            "fee": "no",
            "wc": "yes",
            "op": "Throne",
        },
    ]
    with pytest.raises(SystemExit):
        mod.main(["--out", str(out)])
    with pytest.raises(SystemExit):
        mod.main(["--throne-only", "--pbf", "x.pbf", "--out", str(out)])
