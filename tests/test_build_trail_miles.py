"""The trail mile markers build step (scripts/build_trail_miles.py).

Run against made-up trails and a small made-up extract: which OSM nodes are
mile markers and what figure each posts, which ways are trails, how a trail's
line is found and which end is mile 0, and the file the front end reads.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_trail_miles.py"

spec = importlib.util.spec_from_file_location("build_trail_miles", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_trail_miles"] = mod
spec.loader.exec_module(mod)

MILE_DEG = mod.METRES_PER_MILE / 111_195  # a mile of latitude, in degrees
LON = -77.10


@pytest.mark.parametrize(
    "tags, mile",
    [
        ({"highway": "milestone", "distance": "3"}, 3),
        ({"highway": "milestone", "distance": "3.5 mi"}, 3.5),
        ({"highway": "milestone", "distance": "4.828 km"}, 3.0),
        ({"highway": "milestone", "distance": "1609 m"}, 1.0),
        ({"waterway": "milestone", "distance": "12"}, 12),
        ({"highway": "milestone", "name": "Mile 7"}, 7),
        ({"highway": "milestone", "inscription": "MP 8.5"}, 8.5),
        ({"tourism": "information", "name": "Mile Marker 4"}, 4),
        ({"ref": "MM 2"}, 2),
        ({"marker": "post", "name": "Milepost 6"}, 6),
    ],
)
def test_posted_figures(tags, mile):
    assert mod.posted_mile(tags) == mile


@pytest.mark.parametrize(
    "tags",
    [
        {"railway": "milestone", "railway:position": "12.3"},
        {"historic": "milestone", "name": "Mile 9"},  # an old road's stone
        {"highway": "milestone"},  # no figure
        {"highway": "bus_stop", "name": "Mile 3"},
        {"tourism": "information", "name": "Trail map"},
    ],
)
def test_not_markers(tags):
    assert mod.posted_mile(tags) is None


@pytest.mark.parametrize(
    "tags, trail",
    [
        ({"highway": "cycleway", "name": "Capital Crescent Trail"}, True),
        ({"highway": "path", "name": "C&O Canal Towpath"}, True),
        ({"highway": "track", "name": "Towpath"}, True),
        ({"highway": "footway", "name": "Rock Creek Trail", "bicycle": "designated"}, True),
        ({"highway": "footway", "name": "Valley Trail"}, False),
        ({"highway": "path", "name": "Billy Goat Trail", "bicycle": "no"}, False),
        ({"highway": "cycleway"}, False),
        ({"highway": "residential", "name": "Trail Road"}, False),
        ({"highway": "path", "name": "Plaza", "area": "yes"}, False),
    ],
)
def test_trails(tags, trail):
    assert mod.is_trail(tags) is trail


def _way(first_ref: int, lat0: float, lat1: float, steps: int = 20):
    return [(first_ref + i, LON, lat0 + (lat1 - lat0) * i / steps) for i in range(steps + 1)]


def test_one_line_through_ways_and_a_short_gap():
    # Two ways sharing a node, then a piece 100 m on (a street crossing).
    a = _way(1, 38.90, 38.92)
    b = [(21, LON, 38.92)] + _way(22, 38.9201, 38.94)[1:]
    gap = 100 / 111_195
    c = _way(100, 38.94 + gap, 38.96)
    lines = mod.trail_lines([a, b, c])
    assert len(lines) == 1
    assert mod.line_length(lines[0]) == pytest.approx(0.06 * 111_195, rel=0.01)


def test_pieces_far_apart_are_separate_lines():
    a = _way(1, 38.90, 38.92)
    far = _way(100, 38.95, 38.97)
    assert len(mod.trail_lines([a, far])) == 2


def test_with_no_markers_mile_0_is_the_end_nearer_the_capitol():
    line = [(LON, 38.95), (LON, 38.90)]
    oriented, start = mod.orient(line, [])
    assert oriented[0] == (LON, 38.90) and start == 0


def test_two_markers_set_the_way_and_the_start():
    # Posts count from the north end (the far one from the Capitol); mile 0 is 0.1 mi past it.
    line = [(LON, 38.90), (LON, 38.95)]
    north = 38.95
    one = mod.Marker("n1", LON, north - 0.9 * MILE_DEG, 1)
    two = mod.Marker("n2", LON, north - 1.9 * MILE_DEG, 2)
    oriented, start = mod.orient(line, [one, two])
    assert oriented[0] == (LON, 38.95)
    assert start == pytest.approx(0.1 * mod.METRES_PER_MILE, abs=5)


def test_one_marker_sets_the_way_only():
    line = [(LON, 38.90), (LON, 38.95)]
    one = mod.Marker("n1", LON, 38.95 - 1 * MILE_DEG, 1)
    oriented, start = mod.orient(line, [one])
    assert oriented[0] == (LON, 38.95) and start == 0


def test_build_keeps_markers_on_a_trail_and_drops_short_trails():
    ways = {
        "Long Trail": [_way(1, 38.90, 38.95)],
        "Short Trail": [_way(100, 38.90, 38.91)],
    }
    on = mod.Marker("n5", LON + 0.0001, 38.93, 2)  # about 9 m off the trail
    off = mod.Marker("n6", LON + 0.01, 38.93, 4)  # nearly half a mile off
    trails, markers, lost = mod.build([on, off], ways)
    assert [t.name for t in trails] == ["Long Trail"]
    assert [(m.osm, m.trail) for m in markers] == [("n5", "Long Trail")]
    assert lost == 1
    # The line is simplified: a straight trail is its two ends.
    assert len(trails[0].line) == 2


def _nodes() -> str:
    return "".join(
        f'<node id="{i}" version="1" lat="{38.90 + i * 0.0025:.5f}" lon="{LON}"/>\n'
        for i in range(0, 21)
    )


def _refs(first: int, last: int) -> str:
    return "".join(f'<nd ref="{i}"/>' for i in range(first, last + 1))


OSM = f"""<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
{_nodes()}
 <node id="50" version="1" lat="{38.95 - 1 * MILE_DEG:.5f}" lon="{LON}">
  <tag k="highway" v="milestone"/><tag k="distance" v="1"/>
 </node>
 <node id="51" version="1" lat="{38.95 - 2 * MILE_DEG:.5f}" lon="{LON + 0.0001}">
  <tag k="tourism" v="information"/><tag k="name" v="Mile 2"/>
 </node>
 <node id="52" version="1" lat="38.92" lon="-77.05">
  <tag k="railway" v="milestone"/><tag k="railway:position" v="3"/>
 </node>
 <node id="53" version="1" lat="38.92" lon="-77.05">
  <tag k="highway" v="milestone"/><tag k="distance" v="5"/>
 </node>
 <way id="10" version="1">
  {_refs(0, 10)}
  <tag k="highway" v="cycleway"/><tag k="name" v="Test Trail"/>
 </way>
 <way id="11" version="1">
  {_refs(10, 20)}
  <tag k="highway" v="cycleway"/><tag k="name" v="Test Trail"/>
 </way>
</osm>
"""


def test_reads_an_extract_and_writes_the_file(tmp_path, capsys):
    pytest.importorskip("osmium")
    src = tmp_path / "tiny.osm"
    src.write_text(OSM)
    out = tmp_path / "trail-miles.json"
    assert mod.main(["--pbf", str(src), "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert doc["source"] == "OpenStreetMap contributors, ODbL 1.0"
    [trail] = doc["trails"]
    assert trail["n"] == "Test Trail"
    # The posts count from the north end: the line starts there, at about mile 0.
    assert trail["l"][0] == [LON, 38.95] and abs(trail["s"]) < 20
    assert [(m["id"], m["t"], m["m"]) for m in doc["markers"]] == [
        ("n50", "Test Trail", 1),
        ("n51", "Test Trail", 2),
    ]
    said = capsys.readouterr().out
    assert "2 mile markers on 1 trails (Test Trail 2)" in said
    assert "left out, not on a named trail: 1" in said


def test_bundled_file_is_well_formed():
    doc = json.loads(mod.OUT.read_text())
    assert doc["source"] == mod.SOURCE
    west, south, east, north = mod.COVERAGE_BBOX
    for t in doc["trails"]:
        assert set(t) == {"n", "s", "l"} and t["n"].strip() and isinstance(t["s"], int)
        assert len(t["l"]) >= 2
    seen = set()
    for m in doc["markers"]:
        assert set(m) == {"id", "x", "y", "t", "m"}
        assert m["id"][0] == "n" and m["id"][1:].isdigit() and m["id"] not in seen
        seen.add(m["id"])
        assert west <= m["x"] <= east and south <= m["y"] <= north
        assert m["t"].strip() and m["m"] >= 0
