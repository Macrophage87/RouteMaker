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


def test_with_no_markers_only_a_known_trail_gets_a_line_from_its_mile_0():
    line = [(LON, 38.95), (LON, 38.90)]
    # No posts and no known mile 0: no mile is guessed.
    assert mod.orient(line, []) is None
    # A MILE_ZERO trail: from the end at its mile-0 point.
    oriented, start = mod.orient(line, [], (LON, 38.901))
    assert oriented[0] == (LON, 38.90) and start == 0
    # A piece of it far from mile 0 (past a long gap): no line, rather than a second mile 0.
    assert mod.orient([(LON, 38.95), (LON, 39.00)], [], (LON, 38.901)) is None


def test_the_mile_zero_table_matches_osm_names():
    for name in ("Capital Crescent Trail", "Metropolitan Branch Trail", "C&O Canal Towpath"):
        assert mod.trail_key(name) in mod.MILE_ZERO, name
    assert mod.trail_key("Washington & Old Dominion Trail") in mod.MILE_ZERO
    assert mod.trail_key("Mount Vernon Trail") not in mod.MILE_ZERO  # numbering not checked
    assert mod.trail_key("Custis Trail") not in mod.MILE_ZERO


def test_two_markers_set_the_way_and_the_start():
    # Posts count from the north end (the far one from the Capitol); mile 0 is 0.1 mi past it.
    line = [(LON, 38.90), (LON, 38.95)]
    north = 38.95
    one = mod.Marker("n1", LON, north - 0.9 * MILE_DEG, 1)
    two = mod.Marker("n2", LON, north - 1.9 * MILE_DEG, 2)
    oriented, start = mod.orient(line, [one, two])
    assert oriented[0] == (LON, 38.95)
    assert start == pytest.approx(0.1 * mod.METRES_PER_MILE, abs=5)


def test_posts_that_do_not_fit_the_line_count_as_none():
    line = [(LON, 38.90), (LON, 38.95)]
    # A road's posts: 70 and 72 a mile apart along the trail (2 miles a mile).
    road = [
        mod.Marker("n1", LON, 38.90 + 1 * MILE_DEG, 70),
        mod.Marker("n2", LON, 38.90 + 2 * MILE_DEG, 72),
    ]
    assert mod.orient(line, road) is None
    # Three posts, one of them a mile out of step.
    stray = [
        mod.Marker("n1", LON, 38.90 + 0.5 * MILE_DEG, 1),
        mod.Marker("n2", LON, 38.90 + 1.5 * MILE_DEG, 2),
        mod.Marker("n3", LON, 38.90 + 2.5 * MILE_DEG, 3),
        mod.Marker("n4", LON, 38.90 + 3.0 * MILE_DEG, 2.5),
    ]
    assert mod.orient(line, stray) is None
    # A known trail with posts that do not fit falls back to its mile 0.
    oriented, start = mod.orient(line, road, (LON, 38.90))
    assert oriented[0] == (LON, 38.90) and start == 0


def test_one_marker_sets_the_way_and_the_start_from_the_post():
    line = [(LON, 38.90), (LON, 38.95)]
    # Post 1, 0.9 mi from the north end: the line runs from there, and mile 0 is 0.1 mi past it.
    one = mod.Marker("n1", LON, 38.95 - 0.9 * MILE_DEG, 1)
    oriented, start = mod.orient(line, [one])
    assert oriented[0] == (LON, 38.95)
    assert start == pytest.approx(0.1 * mod.METRES_PER_MILE, abs=5)
    # With the trail's mile 0 known, the way comes from the table, the start from the post.
    post = mod.Marker("n2", LON, 38.90 + 1 * MILE_DEG, 12)
    oriented, start = mod.orient(line, [post], (LON, 38.80))
    assert oriented[0] == (LON, 38.90)
    assert start == pytest.approx(11 * mod.METRES_PER_MILE, abs=5)


def test_road_mileposts_beside_a_trail_are_left_out():
    ways = {"Custis Trail": [_way(1, 38.90, 38.95)]}
    road = [(500 + i, LON + 0.0002, 38.90 + i * 0.0025) for i in range(21)]  # 17 m east
    # I-66's post on the road's shoulder, 3 m from the road and 14 m from the trail.
    interstate = mod.Marker("n1", LON + 0.00016, 38.92, 71)
    # The trail's own post, on the trail's west side.
    trail = mod.Marker("n2", LON - 0.00003, 38.93, 2)
    _, markers, lost = mod.build([interstate, trail], ways, [road])
    assert [m.osm for m in markers] == ["n2"]
    assert lost["road"] == 1


def test_a_trail_split_by_a_long_gap_never_restarts_at_mile_0():
    # Two pieces 2 km apart; mile 0 at the south end of the first; posts 6 and 7 on the second.
    first = _way(1, 38.90, 38.94)
    second = _way(100, 38.96, 39.00)
    six = mod.Marker("n6", LON, 38.97, 6)
    seven = mod.Marker("n7", LON, 38.97 + MILE_DEG, 7)
    name = "Capital Crescent Trail"
    zero = mod.MILE_ZERO[mod.trail_key(name)]
    try:
        mod.MILE_ZERO[mod.trail_key(name)] = (LON, 38.90)
        trails, _, _ = mod.build([six, seven], {name: [first, second]})
        miles = {}
        for t in trails:
            data = {"line": t.line, "s": t.start_m}
            # The mile each piece reports at a point on it.
            for lat in (38.92, 38.98):
                off, along = mod.project(list(data["line"]), (LON, lat))
                if off < 30:
                    miles[lat] = round((data["s"] + along) / mod.METRES_PER_MILE, 1)
        assert miles[38.92] == pytest.approx(0.02 * 111_195 / mod.METRES_PER_MILE, abs=0.1)
        # The second piece's miles come from its own posts, not from a new mile 0.
        sixth = 6 + (0.01 / MILE_DEG)
        assert miles[38.98] == pytest.approx(sixth, abs=0.1)
        # Without the posts, the second piece gets no line at all.
        trails, _, _ = mod.build([], {name: [first, second]})
        assert len(trails) == 1 and trails[0].line[0] == (LON, 38.90)
    finally:
        mod.MILE_ZERO[mod.trail_key(name)] = zero


def test_lines_only_from_ways_a_bike_is_meant_for():
    assert mod.is_line_way({"highway": "cycleway", "name": "X"})
    assert mod.is_line_way({"highway": "path", "name": "X", "bicycle": "designated"})
    assert mod.is_line_way({"highway": "path", "name": "X", "bicycle": "yes"})
    assert not mod.is_line_way({"highway": "path", "name": "Park Loop"})
    assert not mod.is_line_way({"highway": "footway", "name": "X", "bicycle": "permissive"})
    assert mod.is_line_way({"highway": "track", "name": "C&O Canal Towpath"})


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
    assert lost["trail"] == 1
    # The line is simplified: a straight trail is its two ends.
    assert len(trails[0].line) == 2
    # Lines come only from `line_ways` when given; markers from every trail way.
    trails, markers, _ = mod.build([on], ways, line_ways={})
    assert trails == [] and [m.osm for m in markers] == ["n5"]


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
 <node id="54" version="1" lat="38.93" lon="{LON + 0.00016}">
  <tag k="highway" v="milestone"/><tag k="distance" v="71"/>
 </node>
 <node id="60" version="1" lat="38.90" lon="{LON + 0.0002}"/>
 <node id="61" version="1" lat="38.95" lon="{LON + 0.0002}"/>
 <way id="30" version="1">
  <nd ref="60"/><nd ref="61"/>
  <tag k="highway" v="primary"/><tag k="ref" v="VA 7"/>
 </way>
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
    # The road's post 71, on the primary road's shoulder beside the trail.
    assert "left out, nearer a main road than the trail: 1" in said


def test_over_the_size_budget_the_build_fails_and_writes_nothing(tmp_path, capsys):
    pytest.importorskip("osmium")
    src = tmp_path / "tiny.osm"
    src.write_text(OSM)
    out = tmp_path / "trail-miles.json"
    assert mod.main(["--pbf", str(src), "--out", str(out), "--budget", "100"]) == 1
    assert not out.exists()
    assert "over 100; nothing written" in capsys.readouterr().err


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
