"""Climb names from roads and the hill each climb runs up (`pipeline.climb_names`; the
owner, 2026-10-19: "have them named, by a combination of road names and mountain names
(if named)")."""

from __future__ import annotations

import math

import pytest

from pipeline import climb_layer as cl
from pipeline import climb_names as names
from pipeline.climb_layer import SegmentLine
from pipeline.climb_names import Gazetteer, Landmark, Place

M_PER_DEG = 111_320.0
LAT0 = 39.0
KX = M_PER_DEG * math.cos(math.radians(LAT0))


def east(x_m: float, y_m: float = 0.0) -> tuple[float, float]:
    """A point x_m east and y_m north of (-77, 39)."""
    return (-77.0 + x_m / KX, LAT0 + y_m / M_PER_DEG)


class Ramp:
    """Ground rising `grade` going east from x=0 to x=top_m, then level."""

    def __init__(self, grade: float, top_m: float = 1e9) -> None:
        self.grade = grade
        self.top_m = top_m

    def at(self, lon: float, lat: float) -> float:
        x = (lon + 77.0) * KX
        return self.grade * max(0.0, min(x, self.top_m))


class TestRoads:
    def test_one_road(self):
        assert names.roads(["Snider Lane"] * 10) == ["Snider Lane"]

    def test_two_roads_in_the_order_ridden(self):
        assert names.roads(["Hollow Road"] * 4 + ["Ridge Road"] * 6) == [
            "Hollow Road",
            "Ridge Road",
        ]

    def test_a_short_road_does_not_name_it(self):
        assert names.roads(["Main Street"] * 2 + ["Ridge Road"] * 8) == ["Ridge Road"]

    def test_at_most_the_two_longest(self):
        ridden = ["A Road"] * 3 + ["B Road"] * 4 + ["C Road"] * 3
        # A and C tie on length; the first met of the tie is kept, in riding order.
        assert names.roads(ridden) == ["A Road", "B Road"]

    def test_unnamed_stretches_name_nothing(self):
        assert names.roads([None] * 8 + ["Ridge Road"] * 2) == []

    def test_the_same_road_in_another_case_is_one(self):
        assert names.roads(["Ridge Road"] * 5 + ["RIDGE ROAD"] * 5) == ["Ridge Road"]


class TestExtractTags:
    def test_way_name_is_its_name_else_its_first_ref(self):
        assert names.way_name({"name": "Foxville Road", "ref": "MD 77"}) == "Foxville Road"
        assert names.way_name({"ref": "MD 77;US 15"}) == "MD 77"
        assert names.way_name({"highway": "track"}) is None

    @pytest.mark.parametrize(
        ("tags", "kind"),
        [
            ({"natural": "peak", "name": "Sugarloaf Mountain"}, names.PEAK),
            ({"natural": "hill", "name": "Meridian Hill"}, names.PEAK),
            ({"natural": "saddle", "name": "Crampton Gap"}, names.SADDLE),
            ({"mountain_pass": "yes", "highway": "crossing", "name": "Turners Gap"}, names.SADDLE),
            ({"natural": "ridge", "name": "Catoctin Mountain"}, names.RIDGE),
            ({"natural": "peak"}, None),
            ({"natural": "wood", "name": "Big Woods"}, None),
        ],
    )
    def test_landmark_kind(self, tags, kind):
        assert names.landmark_kind(tags) == kind


def gazetteer(*landmarks: Landmark, places: tuple[Place, ...] = ()) -> Gazetteer:
    return Gazetteer(landmarks=list(landmarks), places=list(places))


class TestLandmark:
    """A climb from x=0 to x=1,200 m east, rising 6% (72 m)."""

    foot = east(0)
    summit = east(1200)

    def test_a_peak_just_past_the_summit_names_it(self):
        peak = Landmark("High Knob", names.PEAK, (east(1500),))
        ground = Ramp(0.06, top_m=1500)  # the peak is 18 m above the summit
        assert names.landmark(self.foot, self.summit, gazetteer(peak), ground) == peak

    def test_a_peak_out_of_reach_does_not(self):
        peak = Landmark("High Knob", names.PEAK, (east(2400),))
        assert names.landmark(self.foot, self.summit, gazetteer(peak), Ramp(0.06, 1200)) is None

    def test_a_peak_behind_the_foot_does_not(self):
        peak = Landmark("Low Knob", names.PEAK, (east(-300),))
        assert names.landmark(self.foot, self.summit, gazetteer(peak), Ramp(0.06, 1200)) is None

    def test_a_ramp_at_a_big_hills_foot_is_not_named_for_it(self):
        """72 m up toward a top 500 m above the foot: not half way up."""
        peak = Landmark("Big Mountain", names.PEAK, (east(1900),))

        class Steep(Ramp):
            def at(self, lon, lat):
                x = (lon + 77.0) * KX
                return 0.06 * min(x, 1200) + (500 - 72) * (x >= 1899)

        assert names.landmark(self.foot, self.summit, gazetteer(peak), Steep(0.06)) is None

    def test_a_gap_wins_over_a_nearer_peak_and_a_ridge(self):
        peak = Landmark("High Knob", names.PEAK, (east(1250),))
        gap = Landmark("Crampton Gap", names.SADDLE, (east(1280),))
        ridge = Landmark("South Mountain", names.RIDGE, (east(1200, -900), east(1200, 900)))
        found = names.landmark(
            self.foot, self.summit, gazetteer(peak, ridge, gap), Ramp(0.06, 1200)
        )
        assert found == gap

    def test_a_ridge_is_read_along_its_line(self):
        """A ridge drawn north-south with vertices far from the summit, its line passing over it."""
        ridge = Landmark("Catoctin Mountain", names.RIDGE, (east(1300, -4000), east(1300, 4000)))
        found = names.landmark(self.foot, self.summit, gazetteer(ridge), Ramp(0.06, 1300))
        assert found == ridge

    def test_without_ground_it_is_distance_alone(self):
        peak = Landmark("High Knob", names.PEAK, (east(1500),))
        assert names.landmark(self.foot, self.summit, gazetteer(peak), None) == peak


class TestClimbName:
    hill = Landmark("Catoctin Mountain", names.RIDGE, (east(0),))
    gap = Landmark("Crampton Gap", names.SADDLE, (east(0),))

    def test_roads_up_the_hill(self):
        assert (
            names.climb_name(["Foxville Road"], self.hill) == "Foxville Road up Catoctin Mountain"
        )

    def test_roads_to_a_gap(self):
        assert names.climb_name(["Gapland Road"], self.gap) == "Gapland Road to Crampton Gap"

    def test_two_roads(self):
        assert names.climb_name(["Hollow Road", "Ridge Road"], None) == "Hollow Road to Ridge Road"

    def test_the_hill_is_left_off_a_road_that_has_it(self):
        hill = Landmark("Sugarloaf Mountain", names.PEAK, (east(0),))
        assert names.climb_name(["Sugarloaf Mountain Road"], hill) == "Sugarloaf Mountain Road"

    def test_no_road_the_hill(self):
        hill = Landmark("Sugarloaf Mountain", names.PEAK, (east(0),))
        assert names.climb_name([], hill) == "Sugarloaf Mountain climb"

    def test_no_road_no_hill_the_place(self):
        assert names.climb_name([], None, Place("Thurmont", east(0))) == "Climb near Thurmont"

    def test_nothing_no_name(self):
        assert names.climb_name([], None, None) is None


def test_nearest_place_within_reach():
    near = Place("Thurmont", east(800))
    far = Place("Emmitsburg", east(2000))
    away = Place("Hagerstown", east(9000))
    found = names.nearest_place(east(0), gazetteer(places=(far, near, away)))
    assert found == near
    assert names.nearest_place(east(0), gazetteer(places=(away,))) is None


class TestOnTheLayer:
    def test_a_climb_is_named_from_its_osm_road_and_hill(self):
        segments = [
            SegmentLine(key=(11, 0), coords=(east(0), east(600))),
            SegmentLine(key=(12, 0), coords=(east(600), east(1200))),
        ]
        segments = cl.with_names(segments, {11: "Foxville Road", 12: "Foxville Road"})
        ground = Ramp(0.06, 1200)
        found = cl.find_all(segments, ground)
        assert [f.name for f in found] == ["Foxville Road"]
        hill = Landmark("Catoctin Mountain", names.PEAK, (east(1300),))
        cl.name_all(found, gazetteer(hill), ground)
        assert found[0].entry()["n"] == "Foxville Road up Catoctin Mountain"

    def test_an_osm_name_comes_before_the_rebuilds_own(self):
        (segment,) = cl.with_names(
            [SegmentLine(key=(5, 0), coords=(east(0), east(10)), name="Sidepath")],
            {5: "Ridge Road"},
        )
        assert segment.name == "Ridge Road"

    def test_an_unnamed_climb_is_named_for_the_place_at_its_foot(self):
        segments = [SegmentLine(key=(1, 0), coords=(east(0), east(1200)))]
        ground = Ramp(0.06, 1200)
        found = cl.find_all(segments, ground)
        cl.name_all(found, gazetteer(places=(Place("Thurmont", east(-500)),)), ground)
        assert found[0].entry()["n"] == "Climb near Thurmont"


def test_read_extract(tmp_path):
    osmium = pytest.importorskip("osmium")
    from osmium.osm.mutable import Node, Way

    path = tmp_path / "small.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    try:
        writer.add_node(Node(id=1, location=east(0)))
        writer.add_node(Node(id=2, location=east(1200)))
        writer.add_node(
            Node(id=3, location=east(1300), tags={"natural": "peak", "name": "High Knob"})
        )
        writer.add_node(Node(id=4, location=east(-500), tags={"place": "town", "name": "Thurmont"}))
        writer.add_node(Node(id=5, location=east(1250, -1000)))
        writer.add_node(Node(id=6, location=east(1250, 1000)))
        writer.add_node(Node(id=7, location=east(50), tags={"natural": "peak"}))
        writer.add_way(
            Way(
                id=10,
                nodes=[1, 2],
                tags={"highway": "secondary", "name": "Foxville Road", "ref": "MD 77"},
            )
        )
        writer.add_way(Way(id=11, nodes=[1, 2], tags={"highway": "primary", "ref": "US 15;MD 806"}))
        writer.add_way(
            Way(id=12, nodes=[1, 2], tags={"highway": "residential", "name": "Not Asked"})
        )
        writer.add_way(
            Way(id=13, nodes=[5, 6], tags={"natural": "ridge", "name": "Catoctin Mountain"})
        )
    finally:
        writer.close()
    found = names.read_extract(path, {10, 11, 99})
    assert found.ways == {10: "Foxville Road", 11: "US 15"}
    assert [p.name for p in found.places] == ["Thurmont"]
    by_name = {lm.name: lm for lm in found.landmarks}
    assert set(by_name) == {"High Knob", "Catoctin Mountain"}
    assert by_name["Catoctin Mountain"].kind == names.RIDGE
    ridge = [c for point in by_name["Catoctin Mountain"].points for c in point]
    assert ridge == pytest.approx([*east(1250, -1000), *east(1250, 1000)], abs=1e-6)
