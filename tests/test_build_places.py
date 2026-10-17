"""The places to see build step (scripts/build_places.py).

Run against a small made-up extract: which OSM places count, in which
category, what is kept of each, and the file the front end reads.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_places.py"

spec = importlib.util.spec_from_file_location("build_places", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_places"] = mod
spec.loader.exec_module(mod)

IN = (-77.0, 38.9)


def _cat(tags: dict[str, str]) -> str | None:
    p = mod.classify("n1", {"name": "X", **tags}, *IN)
    return p.category if p else None


@pytest.mark.parametrize(
    "tags, category",
    [
        ({"tourism": "museum"}, "museum"),
        ({"tourism": "gallery"}, "museum"),
        ({"historic": "monument"}, "historic"),
        ({"historic": "memorial", "memorial": "statue"}, "historic"),
        ({"historic": "fort"}, "historic"),
        ({"historic": "battlefield"}, "historic"),
        ({"historic": "building", "tourism": "attraction"}, "historic"),
        ({"man_made": "lighthouse"}, "lighthouse"),
        ({"leisure": "garden"}, "garden"),
        ({"leisure": "garden", "garden:type": "botanical"}, "garden"),
        ({"leisure": "park", "garden:type": "arboretum"}, "garden"),
        ({"tourism": "viewpoint"}, "viewpoint"),
        ({"amenity": "marketplace"}, "market"),
        ({"shop": "farm"}, "market"),
        ({"tourism": "zoo"}, "zoo"),
        ({"tourism": "aquarium"}, "zoo"),
        ({"amenity": "nature_centre"}, "zoo"),
        ({"waterway": "waterfall"}, "nature"),
        ({"natural": "peak"}, "nature"),
        ({"highway": "path", "bridge": "covered"}, "bridge"),
        ({"man_made": "bridge", "historic": "yes"}, "bridge"),
        ({"craft": "brewery", "amenity": "pub"}, "drink"),
        ({"craft": "winery", "tasting": "yes"}, "drink"),
        ({"craft": "cider", "tourism": "attraction"}, "drink"),
        ({"shop": "wine", "craft": "winery"}, "drink"),
    ],
)
def test_each_category(tags, category):
    assert _cat(tags) == category


@pytest.mark.parametrize(
    "tags",
    [
        {"historic": "memorial", "memorial": "plaque"},
        {"historic": "memorial", "memorial": "bench"},
        {"historic": "building"},  # not an attraction
        {"leisure": "garden", "garden:type": "residential"},
        {"leisure": "garden", "garden:type": "community"},
        {"leisure": "garden", "access": "private"},
        {"tourism": "museum", "access": "no"},
        {"tourism": "museum", "disused": "yes"},
        {"man_made": "bridge"},  # nothing notable
        {"craft": "brewery"},  # production only: unclear public access is closed
        {"shop": "wine"},  # a wine shop, not a winery
        {"tourism": "hotel"},
    ],
)
def test_left_out(tags):
    assert _cat(tags) is None


def test_a_name_is_needed():
    assert mod.classify("n1", {"tourism": "viewpoint"}, *IN) is None
    assert mod.classify("n1", {"tourism": "viewpoint", "name": "  "}, *IN) is None


def test_outside_the_box_is_dropped():
    assert mod.classify("n1", {"tourism": "museum", "name": "Far"}, -80.0, 38.9) is None


def test_details_kept():
    p = mod.classify(
        "n1",
        {
            "tourism": "museum",
            "name": "  Rail   Museum ",
            "opening_hours": "We-Su 10:00-16:00",
            "contact:website": "https://rail.example",
        },
        *IN,
    )
    assert (p.name, p.hours, p.website) == (
        "Rail Museum",
        "We-Su 10:00-16:00",
        "https://rail.example",
    )


def test_a_covered_bridge_is_marked_and_named_as_the_bridge():
    """v0.8.0's Scenic layer draws the covered bridges by name (the owner, 2026-10-16: "How
    about including covered bridges")."""
    tags = {"highway": "tertiary", "bridge": "covered", "name": "Roddy Road"}
    p = mod.classify("w1", {**tags, "bridge:name": "Roddy Road Covered Bridge"}, *IN)
    assert (p.category, p.name, p.covered) == ("bridge", "Roddy Road Covered Bridge", True)
    assert mod.document([p])["points"][0]["cv"] == 1
    plain = mod.classify("w2", tags, *IN)
    assert (plain.name, plain.covered) == ("Roddy Road", True)
    notable = mod.classify("w3", {"man_made": "bridge", "historic": "yes", "name": "B"}, *IN)
    assert notable.covered is False and "cv" not in mod.document([notable])["points"][0]


def test_a_place_mapped_twice_is_one():
    node = mod.Place("n5", -77.0, 38.9, "museum", "Rail Museum")
    way = mod.Place("w6", -77.0002, 38.9001, "museum", "rail museum", hours="Sa 10:00-16:00")
    far = mod.Place("n7", -77.0, 38.95, "museum", "Rail Museum")
    out = {p.osm: p for p in mod.merge_duplicates([node, way, far])}
    assert set(out) == {"w6", "n7"}


OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
 <node id="1" version="1" lat="38.90" lon="-77.00">
  <tag k="man_made" v="lighthouse"/><tag k="name" v="Point Light"/>
 </node>
 <node id="2" version="1" lat="38.91" lon="-77.00">
  <tag k="tourism" v="viewpoint"/>
 </node>
 <node id="3" version="1" lat="38.92" lon="-77.02"/>
 <node id="4" version="1" lat="38.92" lon="-77.00"/>
 <node id="5" version="1" lat="38.94" lon="-77.00"/>
 <node id="6" version="1" lat="38.94" lon="-77.02"/>
 <node id="7" version="1" lat="38.95" lon="-77.05">
  <tag k="tourism" v="museum"/><tag k="name" v="Base Museum"/>
 </node>
 <node id="11" version="1" lat="38.94" lon="-77.06"/>
 <node id="12" version="1" lat="38.94" lon="-77.04"/>
 <node id="13" version="1" lat="38.96" lon="-77.04"/>
 <node id="14" version="1" lat="38.96" lon="-77.06"/>
 <way id="10" version="1">
  <nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/>
  <tag k="leisure" v="garden"/><tag k="name" v="Rose Garden"/>
  <tag k="opening_hours" v="dawn-dusk"/>
 </way>
 <way id="20" version="1">
  <nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="11"/>
  <tag k="landuse" v="military"/>
 </way>
</osm>
"""


def test_reads_an_extract_and_writes_the_file(tmp_path, capsys):
    pytest.importorskip("osmium")
    src = tmp_path / "tiny.osm"
    src.write_text(OSM)
    out = tmp_path / "places.json"
    assert mod.main(["--pbf", str(src), "--out", str(out)]) == 0
    text = out.read_text()
    doc = json.loads(text)
    assert doc["source"] == "OpenStreetMap contributors, ODbL 1.0"
    # n2 is unnamed; n7 is inside the base.
    assert doc["points"] == [
        {"id": "n1", "x": -77.0, "y": 38.9, "k": "lighthouse", "n": "Point Light"},
        {"id": "w10", "x": -77.01, "y": 38.93, "k": "garden", "n": "Rose Garden", "h": "dawn-dusk"},
    ]
    said = capsys.readouterr().out
    assert "2 places (lighthouses 1, gardens and arboretums 1)" in said
    assert "left out inside airports, military sites and prisons: 1 (military 1)" in said


def test_bundled_file_is_well_formed():
    doc = json.loads(mod.OUT.read_text())
    assert doc["source"] == mod.SOURCE
    west, south, east, north = mod.COVERAGE_BBOX
    seen = set()
    for p in doc["points"]:
        assert p["id"][0] in "nwr" and p["id"][1:].isdigit() and p["id"] not in seen
        seen.add(p["id"])
        assert west <= p["x"] <= east and south <= p["y"] <= north
        assert p["k"] in mod.CATEGORIES and p["n"].strip()
        assert set(p) <= {"id", "x", "y", "k", "n", "h", "web", "cv"}
