"""The Find food search's build step (scripts/build_food.py).

Run against a small made-up extract: which OSM places count, what is kept of
each, and the file the front end reads.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_food.py"

spec = importlib.util.spec_from_file_location("build_food", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_food"] = mod
spec.loader.exec_module(mod)

IN = (-77.0, 38.9)


def _place(tags: dict[str, str]):
    return mod.classify("n1", tags, *IN)


@pytest.mark.parametrize(
    "amenity, kind",
    [
        ("restaurant", "r"),
        ("fast_food", "f"),
        ("cafe", "c"),
        ("ice_cream", "i"),
        ("pub", "p"),
        ("biergarten", "b"),
        ("food_court", "fc"),
    ],
)
def test_each_kind_counts(amenity, kind):
    assert _place({"amenity": amenity, "name": "X"}).kind == kind


@pytest.mark.parametrize(
    "tags",
    [
        {"amenity": "bar", "name": "Drinks only"},
        {"amenity": "restaurant"},  # unnamed
        {"amenity": "restaurant", "name": "   "},
        {"amenity": "restaurant", "name": "Staff canteen", "access": "private"},
        {"amenity": "cafe", "name": "Closed", "access": "no"},
        {"amenity": "restaurant", "name": "Gone", "disused": "yes"},
        {"amenity": "restaurant", "name": "Gone", "abandoned": "yes"},
        {"disused:amenity": "restaurant", "name": "Gone"},
        {"shop": "bakery", "name": "Not an amenity"},
    ],
)
def test_left_out(tags):
    assert _place(tags) is None


def test_customers_access_and_brand_for_a_missing_name():
    assert _place({"amenity": "restaurant", "name": "Diner", "access": "customers"}) is not None
    assert _place({"amenity": "fast_food", "brand": "Chain"}).name == "Chain"


def test_outside_the_coverage_box_is_dropped():
    assert mod.classify("n1", {"amenity": "cafe", "name": "Far"}, -80.0, 38.9) is None


def test_settings_box_matches_the_water_layer():
    assert mod.COVERAGE_BBOX == (-78.05, 38.2, -76.02, 39.72)


@pytest.mark.parametrize(
    "value, out",
    [
        ("pizza", ("pizza",)),
        ("Seafood;Crab", ("seafood", "crab")),
        (" seafood ; crab ;; seafood ", ("seafood", "crab")),
        ("ice cream", ("ice_cream",)),
        ("burger,american", ("burger", "american")),
        ("a;b;c;d;e;f;g;h", ("a", "b", "c", "d", "e", "f")),
        ("", ()),
        (None, ()),
    ],
)
def test_cuisine_normalised(value, out):
    assert mod.cuisines(value) == out


def test_details_kept_and_cleaned():
    p = _place(
        {
            "amenity": "restaurant",
            "name": "  Crab   Shack ",
            "cuisine": "Seafood;crab",
            "opening_hours": "Mo-Su  11:00-22:00",
            "contact:website": "https://example.org/crab",
        }
    )
    assert (p.name, p.cuisine, p.hours, p.website) == (
        "Crab Shack",
        ("seafood", "crab"),
        "Mo-Su 11:00-22:00",
        "https://example.org/crab",
    )
    assert p.lon == -77.0 and p.lat == 38.9


@pytest.mark.parametrize(
    "url, kept",
    [
        ("https://a.example", True),
        ("http://a.example", True),
        ("www.a.example", False),
        ("javascript:alert(1)", False),
        ("https://a.example/" + "x" * 300, False),
        ("https://a example", False),
    ],
)
def test_website_only_when_a_web_address(url, kept):
    p = _place({"amenity": "cafe", "name": "C", "website": url})
    assert (p.website is not None) == kept


def test_a_place_mapped_twice_is_one():
    node = mod.Place("n5", -77.0, 38.9, "r", "Pizza Place", ("pizza",))
    way = mod.Place(
        "w9", -77.0003, 38.9002, "r", "pizza place", (), "Mo-Su 11:00-23:00", "https://p.example"
    )
    far = mod.Place("n6", -77.01, 38.9, "r", "Pizza Place", ("pizza",))
    other = mod.Place("n7", -77.0, 38.9, "c", "Coffee", ("coffee_shop",))
    out = {p.osm: p for p in mod.merge_duplicates([node, way, far, other])}
    # The way has more details (hours and website) so it is kept, with the node's cuisine.
    assert sorted(out) == ["n6", "n7", "w9"]
    assert out["w9"].cuisine == ("pizza",)
    assert out["w9"].hours == "Mo-Su 11:00-23:00"


def test_node_wins_a_tie():
    node = mod.Place("n5", -77.0, 38.9, "r", "A", ("pizza",))
    way = mod.Place("w9", -77.0001, 38.9, "r", "A", ("italian",))
    [kept] = mod.merge_duplicates([way, node])
    assert kept.osm == "n5" and kept.cuisine == ("pizza", "italian")


OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
 <node id="1" version="1" lat="38.90" lon="-77.00">
  <tag k="amenity" v="restaurant"/><tag k="name" v="Crab House"/>
  <tag k="cuisine" v="seafood;crab"/><tag k="website" v="https://crab.example"/>
 </node>
 <node id="2" version="1" lat="38.91" lon="-77.00">
  <tag k="amenity" v="fast_food"/>
 </node>
 <node id="3" version="1" lat="38.92" lon="-77.00"/>
 <node id="4" version="1" lat="38.92" lon="-76.99"/>
 <node id="5" version="1" lat="38.93" lon="-76.99"/>
 <node id="6" version="1" lat="38.93" lon="-77.00"/>
 <node id="7" version="1" lat="38.95" lon="-77.05">
  <tag k="amenity" v="cafe"/><tag k="name" v="Airside Coffee"/>
 </node>
 <node id="11" version="1" lat="38.94" lon="-77.06"/>
 <node id="12" version="1" lat="38.94" lon="-77.04"/>
 <node id="13" version="1" lat="38.96" lon="-77.04"/>
 <node id="14" version="1" lat="38.96" lon="-77.06"/>
 <node id="21" version="1" lat="38.80" lon="-77.10"/>
 <node id="22" version="1" lat="38.80" lon="-77.08"/>
 <node id="23" version="1" lat="38.82" lon="-77.08"/>
 <node id="24" version="1" lat="38.82" lon="-77.10"/>
 <node id="25" version="1" lat="38.81" lon="-77.09">
  <tag k="amenity" v="ice_cream"/><tag k="name" v="Pier Scoops"/>
 </node>
 <way id="10" version="1">
  <nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/>
  <tag k="amenity" v="pub"/><tag k="name" v="The Pub"/>
  <tag k="opening_hours" v="Mo-Su 12:00-02:00"/>
 </way>
 <way id="20" version="1">
  <nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="11"/>
  <tag k="aeroway" v="aerodrome"/>
 </way>
 <way id="30" version="1">
  <nd ref="21"/><nd ref="22"/><nd ref="23"/><nd ref="24"/>
 </way>
 <way id="31" version="1">
  <nd ref="24"/><nd ref="21"/>
 </way>
 <relation id="40" version="1">
  <member type="way" ref="30" role="outer"/>
  <member type="way" ref="31" role="outer"/>
  <tag k="type" v="multipolygon"/><tag k="amenity" v="restaurant"/>
  <tag k="name" v="Market Hall"/><tag k="cuisine" v="american"/>
 </relation>
</osm>
"""


def test_reads_an_extract_and_writes_the_file(tmp_path, capsys):
    pytest.importorskip("osmium")
    src = tmp_path / "tiny.osm"
    src.write_text(OSM)
    out = tmp_path / "out" / "food.json"
    assert mod.main(["--pbf", str(src), "--out", str(out)]) == 0
    text = out.read_text()
    doc = json.loads(text)
    assert doc["source"] == "OpenStreetMap contributors, ODbL 1.0"
    ids = [p["id"] for p in doc["points"]]
    # n2 is unnamed, n7 is inside the airport; the relation is placed at its ring's mean.
    assert ids == ["n1", "n25", "r40", "w10"]
    by = {p["id"]: p for p in doc["points"]}
    assert by["n1"] == {
        "id": "n1",
        "x": -77.0,
        "y": 38.9,
        "k": "r",
        "n": "Crab House",
        "c": "seafood;crab",
        "web": "https://crab.example",
    }
    # The pub's building: the mean corner, its first node counted once.
    assert by["w10"] == {
        "id": "w10",
        "x": -76.995,
        "y": 38.925,
        "k": "p",
        "n": "The Pub",
        "h": "Mo-Su 12:00-02:00",
    }
    assert by["r40"]["n"] == "Market Hall" and by["r40"]["x"] == -77.09 and by["r40"]["y"] == 38.81
    assert text.count("\n") == len(ids) + 2  # the header line, one place per line, the close
    said = capsys.readouterr().out
    assert "4 places (restaurant 2, ice_cream 1, pub 1); 2 with a cuisine" in said
    assert "left out inside airports, military sites and prisons: 1 (airport 1)" in said
    assert f"{out}: {len(text.encode()):,} bytes" in said


def test_bundled_file_is_well_formed():
    doc = json.loads(mod.OUT.read_text())
    assert doc["source"] == mod.SOURCE
    west, south, east, north = mod.COVERAGE_BBOX
    seen = set()
    for p in doc["points"]:
        assert p["id"][0] in "nwr" and p["id"][1:].isdigit() and p["id"] not in seen
        seen.add(p["id"])
        assert west <= p["x"] <= east and south <= p["y"] <= north
        assert p["k"] in mod.KINDS.values() and p["n"].strip()
        assert set(p) <= {"id", "x", "y", "k", "n", "c", "h", "web"}
