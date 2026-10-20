"""The Climbs layer's build step (pipeline.climb_layer): strokes, the ground, the file."""

from __future__ import annotations

import json
import math
from array import array
from pathlib import Path

import pytest

from pipeline import climb_layer as cl
from pipeline.climb_layer import SegmentLine

REPO = Path(__file__).resolve().parents[1]
BUNDLED = REPO / "frontend" / "src" / "climb-data" / "climbs.json"

M_PER_DEG = 111_320.0
LAT0 = 39.0
KX = M_PER_DEG * math.cos(math.radians(LAT0))


def east(x_m: float, y_m: float = 0.0) -> tuple[float, float]:
    """A point x_m east and y_m north of (-77, 39)."""
    return (-77.0 + x_m / KX, LAT0 + y_m / M_PER_DEG)


def seg(key, *points_m, **kw) -> SegmentLine:
    return SegmentLine(key=(key, 0), coords=tuple(east(*p) for p in points_m), **kw)


class Ramp:
    """Ground that rises `grade` going east from x=0 to x=top_m, then stays level."""

    def __init__(self, grade: float, top_m: float = 1e9) -> None:
        self.grade = grade
        self.top_m = top_m

    def at(self, lon: float, lat: float) -> float:
        x = (lon + 77.0) * KX
        return self.grade * max(0.0, min(x, self.top_m))


class TestStrokes:
    def test_a_straight_road_through_a_junction_is_one_stroke(self):
        segments = [
            seg(1, (0, 0), (500, 0)),
            seg(2, (500, 0), (1000, 0)),
            seg(3, (500, 0), (500, 400)),  # a cross street, at a right angle
        ]
        strokes = cl.strokes(segments)
        assert len(strokes) == 2
        through = max(strokes, key=lambda s: len(s.parts))
        assert sorted(i for i, _ in through.parts) == [0, 1]

    def test_a_sharp_turn_ends_the_stroke(self):
        segments = [seg(1, (0, 0), (500, 0)), seg(2, (500, 0), (450, 300))]
        assert len(cl.strokes(segments)) == 2

    def test_a_way_drawn_the_other_way_is_walked_backwards(self):
        segments = [seg(1, (0, 0), (500, 0)), seg(2, (1000, 0), (500, 0))]
        (stroke,) = cl.strokes(segments)
        directions = dict(stroke.parts)
        assert directions[0] != directions[1]
        assert len(stroke.coords) == 3

    def test_every_segment_is_in_exactly_one_stroke(self):
        segments = [
            seg(1, (0, 0), (500, 0)),
            seg(2, (500, 0), (500, 500)),
            seg(3, (500, 500), (0, 500)),
            seg(4, (0, 500), (0, 0)),  # a ring of right angles: four strokes
            seg(5, (500, 0), (1000, 0)),
        ]
        strokes = cl.strokes(segments)
        used = [i for s in strokes for i, _ in s.parts]
        assert sorted(used) == [0, 1, 2, 3, 4]

    def test_a_closed_ring_of_gentle_bends_is_walked_once(self):
        n = 12
        points = [
            (500 * math.cos(2 * math.pi * k / n), 500 * math.sin(2 * math.pi * k / n))
            for k in range(n)
        ]
        segments = [seg(k, points[k], points[(k + 1) % n]) for k in range(n)]
        strokes = cl.strokes(segments)
        assert sorted(i for s in strokes for i, _ in s.parts) == list(range(n))


class TestClimbsOnAStroke:
    def stroke(self, segments):
        (stroke,) = cl.strokes(segments)
        return stroke

    def test_a_climb_is_found_in_the_uphill_direction_with_its_summit_at_the_top(self):
        segments = [seg(1, (0, 0), (1200, 0))]
        found = cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.06))
        assert len(found) == 1
        entry = found[0].entry()
        assert entry["c"] == "5" and entry["g"] == 6.0 and entry["r"] == 72
        assert entry["l"] == pytest.approx(1200, abs=1)
        assert [entry["x"], entry["y"]] == pytest.approx(list(east(1200)), abs=1e-5)
        assert entry["line"][0] == pytest.approx(list(east(0)), abs=1e-5)

    def test_drawn_westward_the_climb_still_runs_east(self):
        segments = [seg(1, (1200, 0), (0, 0))]
        (found,) = cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.06))
        assert found.line[-1] == pytest.approx(east(1200), abs=1e-6)

    def test_a_one_way_against_the_climb_drops_it(self):
        segments = [seg(1, (1200, 0), (0, 0), oneway=True)]
        assert cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.06)) == []

    def test_a_one_way_with_the_climb_keeps_it(self):
        segments = [seg(1, (0, 0), (1200, 0), oneway=True)]
        assert len(cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.06))) == 1

    def test_one_way_is_read_per_segment_across_the_stroke(self):
        segments = [seg(1, (0, 0), (600, 0)), seg(2, (1200, 0), (600, 0), oneway=True)]
        assert cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.06)) == []

    def test_unpaved_and_trail_name_are_carried_when_most_of_it_is(self):
        segments = [
            seg(1, (0, 0), (900, 0), unpaved=True, trail_name="Example Trail"),
            seg(2, (900, 0), (1200, 0), unpaved=False),
        ]
        (found,) = cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.06))
        entry = found.entry()
        assert entry["u"] == 1 and entry["n"] == "Example Trail"

    def test_the_surface_class_is_what_most_of_it_is_ridden_on(self):
        """The owner, 2026-10-19: "color the climbs by surface: road, gravel, mtb, etc" and
        "a different color for traffic free paved climbs"."""

        def entry(**kw):
            segments = [seg(1, (0, 0), (900, 0), **kw), seg(2, (900, 0), (1200, 0))]
            (found,) = cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.06))
            return found.entry()

        assert "s" not in entry()
        assert entry(trail=True)["s"] == "p"
        assert entry(trail=True, unpaved=True)["s"] == "g"
        assert entry(trail=True, unpaved=True, mtb=True)["s"] == "m"

    def test_a_climb_mostly_on_lts_3_or_higher_roads_is_marked_busy(self):
        """The owner, 2026-10-19: "optionally (default on) hide climbs on LTS 3+ roads"."""

        def entry(first, second=None, **kw):
            segments = [
                seg(1, (0, 0), (900, 0), tier=first, **kw),
                seg(2, (900, 0), (1200, 0), tier=second),
            ]
            (found,) = cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.06))
            return found.entry()

        assert entry(3)["b"] == 1
        assert "b" not in entry(2, 4)
        # A path is never a busy road, whatever its tier.
        assert "b" not in entry(3, trail=True)

    def test_the_summit_is_where_the_ground_stops_rising(self):
        segments = [seg(1, (0, 0), (3000, 0))]
        (found,) = cl.climbs_on_stroke(self.stroke(segments), segments, Ramp(0.05, top_m=1500))
        assert found.climb.end_m == pytest.approx(1500, abs=31)

    def test_no_ground_no_climb(self):
        class Nothing:
            def at(self, lon, lat):
                return None

        segments = [seg(1, (0, 0), (1200, 0))]
        assert cl.climbs_on_stroke(self.stroke(segments), segments, Nothing()) == []


class TestHgt:
    def test_bilinear_between_posts_and_void_is_none(self, tmp_path):
        side = cl.HGT_1ARCSEC_SIDE
        data = array("h", [0]) * (side * side)
        # Row 0 is the north edge. Posts (row 3600 - 1, col 0..1) near the south-west corner.
        data[(side - 1) * side + 0] = 100
        data[(side - 1) * side + 1] = 200
        data[(side - 2) * side + 0] = 100
        data[(side - 2) * side + 1] = 200
        data[0] = -32768
        import sys

        if sys.byteorder == "little":
            data.byteswap()
        (tmp_path / "N38").mkdir()
        (tmp_path / "N38" / "N38W077.hgt").write_bytes(data.tobytes())
        ground = cl.HgtElevation(tmp_path)
        half = 0.5 / 3600
        assert ground.at(-77.0 + half, 38.0) == pytest.approx(150)
        assert ground.at(-77.0, 38.0) == pytest.approx(100)
        assert ground.at(-77.0, 39.0) is None  # the void post, north-west corner
        assert ground.at(-80.5, 38.5) is None  # no tile there

    def test_a_tile_of_the_wrong_size_is_no_ground(self, tmp_path):
        (tmp_path / "N38").mkdir()
        (tmp_path / "N38" / "N38W077.hgt").write_bytes(b"\0" * (1201 * 1201 * 2))
        assert cl.HgtElevation(tmp_path).at(-76.5, 38.5) is None


class TestFile:
    def test_document_counts_and_round_trips(self, tmp_path):
        segments = [seg(1, (0, 0), (1200, 0)), seg(2, (0, 1000), (2000, 1000))]
        found = cl.find_all(segments, Ramp(0.06))
        doc = cl.document(found)
        assert doc["version"] == cl.FORMAT_VERSION
        assert doc["counts"] == {"HC": 0, "1": 0, "2": 0, "3": 0, "4": 1, "5": 1}
        # Biggest first.
        assert [c["c"] for c in doc["climbs"]] == ["4", "5"]
        out = tmp_path / "climbs.json"
        cl.write(out, doc)
        assert json.loads(out.read_text()) == doc
        assert not (tmp_path / "climbs.json.part").exists()

    def test_simplify_keeps_the_ends_and_drops_a_straight_middle(self):
        line = [east(x) for x in range(0, 1001, 30)]
        assert cl._simplify(line, 5.0) == [line[0], line[-1]]
        bent = [east(0), east(500, 50), east(1000)]
        assert cl._simplify(bent, 5.0) == bent


def test_bundled_file_is_well_formed():
    doc = json.loads(BUNDLED.read_text())
    assert doc["version"] == cl.FORMAT_VERSION
    assert isinstance(doc["climbs"], list)
    ids = [c["id"] for c in doc["climbs"]]
    assert len(ids) == len(set(ids))
    for c in doc["climbs"]:
        assert c["c"] in ("5", "4", "3", "2", "1", "HC")
        # The gain is rounded in the file, so a score just over 4,000 may show as 40 m.
        assert c["l"] >= 500 and c["g"] >= 1.0 and c["r"] >= 40
        assert len(c["line"]) >= 2 and [c["x"], c["y"]] == c["line"][-1]
        assert "n" not in c or (isinstance(c["n"], str) and c["n"].strip())
