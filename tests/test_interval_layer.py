"""The Intervals layer's build step (pipeline.interval_layer): what breaks an effort, the file."""

from __future__ import annotations

import json
import math

import pytest

from pipeline import interval_layer as il
from pipeline.climb_layer import SegmentLine

M_PER_DEG = 111_320.0
LAT0 = 39.0
KX = M_PER_DEG * math.cos(math.radians(LAT0))


def east(x_m: float, y_m: float = 0.0) -> tuple[float, float]:
    return (-77.0 + x_m / KX, LAT0 + y_m / M_PER_DEG)


def seg(key, *points_m, **kw) -> SegmentLine:
    return SegmentLine(key=(key, 0), coords=tuple(east(*p) for p in points_m), **kw)


def road(key, length_m=3000, step=100, **kw) -> SegmentLine:
    """A straight road east from x=0, a vertex every `step` metres."""
    return seg(key, *[(x, 0) for x in range(0, length_m + 1, step)], **kw)


class Ground:
    """Ground with `grade` (rise per metre east) from x0 to x1, flat elsewhere."""

    def __init__(self, grade=0.0, x0=0.0, x1=1e9):
        self.grade, self.x0, self.x1 = grade, x0, x1

    def at(self, lon, lat):
        x = (lon + 77.0) * KX
        return 100.0 + self.grade * (max(self.x0, min(x, self.x1)) - self.x0)


def found(segments, ground=None, facts=None, rule=il.JUNCTION_RULE):
    return il.find_all(segments, ground or Ground(), facts or il.ExtractFacts(), rule)


def spans(stretches):
    return sorted((round(s.length_m), s.both) for s in stretches)


class TestLengthAndGround:
    def test_a_long_flat_road_holds_both_ways(self):
        [s] = found([road(1)])
        assert s.both and round(s.length_m) == 3000 - 2 * il.PAD_M

    def test_a_short_road_is_not_a_stretch(self):
        assert found([road(1, length_m=1500)]) == []

    def test_a_climb_holds_one_way_only_uphill(self):
        [s] = found([road(1)], Ground(0.04))
        assert not s.both
        assert s.rise_m > 100  # ridden up, east
        assert s.line[0][0] < s.line[-1][0]

    def test_a_climb_drawn_the_other_way_still_goes_up(self):
        backwards = seg(1, *[(x, 0) for x in range(3000, -1, -100)])
        [s] = found([backwards], Ground(0.04))
        assert s.line[0][0] < s.line[-1][0] and s.rise_m > 100

    def test_a_gentle_drop_does_not_break_it(self):
        # 1.5% down, under the 2% the interval check breaks at.
        [s] = found([road(1)], Ground(-0.015))
        assert s.both

    def test_a_descent_in_the_middle_splits_one_way_only(self):
        # A 300 m drop at 5% between 2400 and 2700 m on a 5 km road: ridden west it is all
        # flat or up, one stretch; ridden east the drop splits it in two.
        out = found([road(1, length_m=5000)], Ground(-0.05, 2400, 2700))
        west = [s for s in out if s.line[0][0] > s.line[-1][0]]
        eastward = [s for s in out if s.line[0][0] < s.line[-1][0]]
        assert [round(s.length_m) for s in west] == [5000 - 2 * il.PAD_M] and west[0].rise_m > 0
        assert len(eastward) == 2 and all(s.length_m >= il.MIN_LENGTH_M for s in eastward)
        assert not any(s.both for s in out)

    def test_a_short_climb_counts_by_its_minutes(self):
        # The owner, 2026-11-17: "if it's a continuous uphill, you don't need as much distance".
        # 1.2 km at 5%: 1,040 m after the ends, about 3.4 minutes up at 18 mph; flat, too short.
        [s] = found([road(1, length_m=1200)], Ground(0.05))
        assert not s.both and s.rise_m > 0 and s.minutes >= il.MIN_EFFORT_MIN
        assert found([road(1, length_m=1200)]) == []

    def test_a_both_ways_part_too_quick_downhill_holds_uphill_only(self):
        # 1.6 km at 1.9% (under the 2% that breaks a descent): flat both ways, but only uphill takes
        # 3 minutes, so it is written once, one way, up.
        [s] = found([road(1, length_m=1600)], Ground(0.019))
        assert not s.both and s.rise_m > 0 and s.line[0][0] < s.line[-1][0]

    def test_minutes_follow_the_connector_s_slowing(self):
        mile = il.METRES_PER_MILE
        assert round(il.effort_minutes(mile, 0), 2) == round(60 / 18, 2)
        assert round(il.effort_minutes(mile, mile * 0.05), 2) == round(60 / (18 / 1.6), 2)
        assert il.effort_minutes(mile, -50) == il.effort_minutes(mile, 0)

    def test_lts4_is_never_part_of_one(self):
        assert found([road(1, tier=4)]) == []

    def test_lts3_is_marked_busy(self):
        [s] = found([road(1, tier=3)])
        assert s.entry()["b"] == 1

    def test_a_one_way_road_holds_its_own_way(self):
        [s] = found([road(1, oneway=True)])
        assert not s.both and s.line[0][0] < s.line[-1][0]


class TestBreaks:
    def test_a_signal_splits_it(self):
        facts = il.ExtractFacts(stops={il.node_key(east(2000)): "signal"})
        out = found([road(1, length_m=5000)], facts=facts)
        assert spans(out) == [(2000 - 2 * il.PAD_M, True), (3000 - 2 * il.PAD_M, True)]

    def test_a_bollard_is_ridden_through_and_counted(self):
        # The owner, 2026-11-18: "Mark bollards on the interval card and have it noted".
        facts = il.ExtractFacts(stops={il.node_key(east(1500)): il.BOLLARD})
        [s] = found([road(1)], facts=facts)
        assert s.both and s.bollards == 1 and s.entry()["k"] == 1
        assert il.node_stop({"barrier": "bollard"}) == il.BOLLARD
        assert il.node_stop({"barrier": "gate"}) == "barrier"

    def test_a_quiet_cross_street_does_not(self):
        cross = seg(2, (1500, -300), (1500, 0), (1500, 300), tier=1)
        assert spans(found([road(1, tier=1), cross])) == [(3000 - 2 * il.PAD_M, True)]

    def test_a_busy_cross_road_does(self):
        cross = seg(2, (2000, -300), (2000, 0), (2000, 300), tier=3)
        out = found([road(1, length_m=5000, tier=1), cross])
        assert len(out) == 2

    def test_a_cross_street_s_stop_sign_on_the_junction_node_is_not_the_through_road_s(self):
        cross = seg(2, (2000, -300), (2000, 0), (2000, 300), tier=1)
        stop = {il.node_key(east(2000)): "stop sign"}
        busier = found([road(1, length_m=5000, tier=2), cross], facts=il.ExtractFacts(stops=stop))
        assert len(busier) == 1
        same = found([road(1, length_m=5000, tier=1), cross], facts=il.ExtractFacts(stops=stop))
        assert len(same) == 2  # unclear who stops: it breaks
        all_way = {il.node_key(east(2000)): il.ALL_WAY}
        assert (
            len(
                found([road(1, length_m=5000, tier=2), cross], facts=il.ExtractFacts(stops=all_way))
            )
            == 2
        )

    def test_a_one_way_part_drawn_backwards_inside_a_stroke_holds_the_stroke_s_other_way(self):
        # Three parts west to east; the middle one is a one-way drawn west, so only westward holds.
        parts = [
            seg(1, *[(x, 0) for x in range(0, 1001, 100)]),
            seg(2, *[(x, 0) for x in range(2000, 999, -100)], oneway=True),
            seg(3, *[(x, 0) for x in range(2000, 3001, 100)]),
        ]
        [s] = found(parts)
        assert not s.both and s.line[0][0] > s.line[-1][0]

    def test_a_crossing_road_in_two_pieces_ending_at_the_junction_still_crosses(self):
        north = seg(2, (2000, 0), (2000, 300), tier=3)
        south = seg(3, (2000, -300), (2000, 0), tier=3)
        assert len(found([road(1, length_m=5000, tier=1), north, south])) == 2

    def test_a_busy_road_joining_from_one_side_does_not(self):
        side = seg(2, (1500, 0), (1500, 300), tier=3)
        assert spans(found([road(1, tier=1), side])) == [(3000 - 2 * il.PAD_M, True)]

    def test_every_junction_breaks_under_the_strict_rule(self):
        side = seg(2, (1500, 0), (1500, 300), tier=1)
        out = found([road(1, tier=1), side], rule="every")
        assert out == []  # 1500 - 80 either side is under a mile

    def test_a_driveway_never_breaks_it(self):
        drive = seg(2, (1500, 0), (1500, 50), tier=1)
        facts = il.ExtractFacts(minor={2})
        assert spans(found([road(1, tier=1), drive], facts=facts, rule="every")) == [
            (3000 - 2 * il.PAD_M, True)
        ]

    def test_a_path_meeting_any_road_breaks(self):
        trail = road(1, length_m=5000, trail=True)
        street = seg(2, (2000, -300), (2000, 0), (2000, 300), tier=1)
        assert len(found([trail, street])) == 2

    def test_a_sharp_bend_breaks_it(self):
        # East 2 km, then a hairpin back north-west for 2 km: one way, a 135 degree bend.
        line = [(x, 0) for x in range(0, 2001, 100)] + [
            (2000 - k * 70.7, k * 70.7) for k in range(1, 29)
        ]
        out = found([seg(1, *line)])
        assert len(out) == 2

    def test_a_gentle_bend_does_not(self):
        line = [(x, 0) for x in range(0, 1501, 100)] + [
            (1500 + k * 96.6, k * 25.9) for k in range(1, 17)
        ]
        assert len(found([seg(1, *line)])) == 1

    def test_a_windy_path_is_left_out_and_a_windy_road_is_not(self):
        # The owner, 2026-11-18: "You spend so much time turning here that you can't go at full
        # speed." A zigzag of 50 degree bends every 40 m, each gentler than a sharp turn.
        wiggle = [(k * 36.3, (k % 2) * 16.9) for k in range(0, 111)]
        assert found([seg(1, *wiggle, trail=True)]) == []
        assert len(found([seg(1, *wiggle, tier=1)])) == 1
        straight = found([road(1, length_m=4000, trail=True)])
        assert len(straight) == 1 and straight[0].surface == il.PATH
        assert straight[0].tight_turning_per_km == 0.0

    def test_a_climb_may_wind_more(self):
        # "With some flexibility on uphill stretches too": slower up a 5% climb, 1.6 times, so
        # 2.56 times the bends.
        flat = il.Stretch(line=[], length_m=1000, rise_m=0, both=False, surface=il.PATH)
        climb = il.Stretch(line=[], length_m=1000, rise_m=50, both=False, surface=il.PATH)
        assert flat.windy_limit == il.WINDY_PATH_DEG_PER_KM
        assert climb.windy_limit == pytest.approx(il.WINDY_PATH_DEG_PER_KM * 2.56)

    def test_a_long_gentle_curve_is_not_windy(self):
        # "a gentle turn isn't an issue, its a cluster of short sharp ones": a quarter circle of
        # 600 m radius turns 90 degrees in 940 m, never 30 degrees in 30 m.
        arc = [
            east(600 * math.sin(math.radians(a)), 600 - 600 * math.cos(math.radians(a)))
            for a in range(0, 91, 2)
        ]
        assert il.tight_turning_per_km(arc, 942) == 0.0
        # A right angle in one corner, then straight: one tight bend of 90 degrees in 200 m.
        corner = [east(0, 0), east(100, 0), east(100, 100)]
        assert il.tight_turning_per_km(corner, 200) == pytest.approx(450, abs=1)

    def test_a_roundabout_is_never_ridden(self):
        facts = il.ExtractFacts(roundabouts={1})
        assert found([road(1)], facts=facts) == []


class TestNodeTags:
    def test_stops(self):
        assert il.node_stop({"highway": "traffic_signals"}) == "signal"
        assert il.node_stop({"highway": "stop"}) == "stop sign"
        assert il.node_stop({"highway": "crossing", "crossing": "traffic_signals"}) == "signal"
        assert il.node_stop({"railway": "level_crossing"}) == "railway crossing"
        assert il.node_stop({"barrier": "gate"}) == "barrier"

    def test_not_stops(self):
        assert il.node_stop({"highway": "crossing", "crossing": "unmarked"}) is None
        assert il.node_stop({"barrier": "kerb"}) is None
        assert il.node_stop({"traffic_calming": "hump"}) is None

    def test_minor_ways(self):
        assert il.way_minor({"highway": "service", "service": "driveway"})
        assert il.way_minor({"highway": "footway"})
        assert not il.way_minor({"highway": "residential"})


class TestFile:
    def test_entry_and_document(self, tmp_path):
        out = found([road(1, trail=True, name="Capital Crescent Trail")], Ground(0.03))
        doc = il.document(out)
        [entry] = doc["intervals"]
        assert entry["l"] == 2840 and entry["r"] == 85 and entry["g"] == 3.0
        assert entry["s"] == "p" and entry["n"] == "Capital Crescent Trail" and "w" not in entry
        assert entry["t"] == round(il.effort_minutes(2840, 85), 1)
        assert doc["counts"] == {"both_ways": 0, "one_way": 1}
        path = tmp_path / "intervals.json"
        il.write(path, doc)
        assert json.loads(path.read_text())["intervals"] == [entry]

    def test_the_bundled_file_reads(self):
        from pathlib import Path

        bundled = (
            Path(__file__).resolve().parents[1]
            / "frontend"
            / "src"
            / "interval-data"
            / "intervals.json"
        )
        doc = json.loads(bundled.read_text())
        assert doc["version"] == il.FORMAT_VERSION and isinstance(doc["intervals"], list)
