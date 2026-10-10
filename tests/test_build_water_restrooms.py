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
        ]
    )
    assert doc["source"] == "OpenStreetMap contributors, ODbL 1.0"
    assert doc["points"] == [
        {"id": "n3", "x": -77.3, "y": 38.6, "w": "p", "t": "b", "fee": "yes"},
        {"id": "n20", "x": -77.2, "y": 38.7, "w": "p", "b": 1},
        {"id": "w5", "x": -77.1, "y": 38.8, "t": "f", "n": "Comfort station"},
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
 <way id="10" version="1">
  <nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/>
  <tag k="amenity" v="toilets"/><tag k="building" v="yes"/><tag k="name" v="Comfort station"/>
  <tag k="toilets:disposal" v="flush"/>
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
        {"id": "n1", "x": -77.0, "y": 38.9, "w": "p"},
        {"id": "n8", "x": -77.04, "y": 38.96, "w": "n"},
        # The building's mean corner, its first node counted once.
        {"id": "w10", "x": -77.01, "y": 38.93, "t": "f", "n": "Comfort station"},
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
