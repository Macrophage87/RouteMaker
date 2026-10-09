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


def _kind(tags: dict[str, str]) -> str | None:
    a = mod.classify("n1", tags, *IN)
    return a.kind if a else None


@pytest.mark.parametrize(
    "tags, kind",
    [
        ({"amenity": "drinking_water"}, "w"),
        ({"amenity": "drinking_water", "drinking_water": "no"}, None),
        ({"amenity": "water_point"}, "w"),
        ({"man_made": "water_tap"}, None),
        ({"man_made": "water_tap", "drinking_water": "yes"}, "w"),
        ({"amenity": "fountain"}, None),
        ({"amenity": "fountain", "drinking_water": "yes"}, "w"),
        ({"amenity": "toilets"}, "t"),
        ({"amenity": "toilets", "drinking_water": "yes"}, "wt"),
        ({"amenity": "toilets", "drinking_water": "no"}, "t"),
        ({"amenity": "restaurant", "drinking_water": "yes"}, None),
        ({"amenity": "toilets", "access": "public"}, "t"),
        ({"amenity": "toilets", "access": "permissive"}, "t"),
        ({"amenity": "toilets", "access": "customers"}, None),
        ({"amenity": "toilets", "access": "private"}, None),
        ({"amenity": "drinking_water", "access": "no"}, None),
        ({"amenity": "toilets", "disused": "yes"}, None),
        ({"disused:amenity": "toilets"}, None),
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
    assert mod.classify("n1", {"amenity": "toilets", "seasonal": "no"}, *IN).seasonal is None


def test_document_is_short_and_sorted():
    doc = mod.document(
        [
            mod.Amenity("w5", -77.1, 38.8, False, True, name="Comfort station"),
            mod.Amenity("n20", -77.2, 38.7, True, False, bottle=True),
            mod.Amenity("n3", -77.3, 38.6, True, True, fee="yes"),
        ]
    )
    assert doc["source"] == "OpenStreetMap contributors, ODbL 1.0"
    assert doc["points"] == [
        {"id": "n3", "x": -77.3, "y": 38.6, "k": "wt", "fee": "yes"},
        {"id": "n20", "x": -77.2, "y": 38.7, "k": "w", "b": 1},
        {"id": "w5", "x": -77.1, "y": 38.8, "k": "t", "n": "Comfort station"},
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
 <way id="10" version="1">
  <nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/>
  <tag k="amenity" v="toilets"/><tag k="building" v="yes"/><tag k="name" v="Comfort station"/>
 </way>
</osm>
"""


def test_reads_an_extract_and_writes_the_file(tmp_path):
    pytest.importorskip("osmium")
    src = tmp_path / "tiny.osm"
    src.write_text(OSM)
    out = tmp_path / "out" / "water-restrooms.json"
    assert mod.main(["--pbf", str(src), "--out", str(out)]) == 0
    text = out.read_text()
    doc = json.loads(text)
    assert doc["points"] == [
        {"id": "n1", "x": -77.0, "y": 38.9, "k": "w"},
        # The building's mean corner, its first node counted once.
        {"id": "w10", "x": -77.01, "y": 38.93, "k": "t", "n": "Comfort station"},
    ]
    assert text.count("\n") == 4  # one point per line


def test_bundled_file_is_well_formed():
    doc = json.loads(mod.OUT.read_text())
    assert doc["source"] == "OpenStreetMap contributors, ODbL 1.0"
    west, south, east, north = mod.COVERAGE_BBOX
    ids = [p["id"] for p in doc["points"]]
    assert len(ids) == len(set(ids))
    for p in doc["points"]:
        assert p["k"] in ("w", "t", "wt")
        assert west <= p["x"] <= east and south <= p["y"] <= north
