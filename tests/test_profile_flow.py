"""The route's elevation profile, and a Mass Ride's grade-adjusted flow along it
(OWNER-DECISIONS 322, 323, 328, 329, 332, 333; routemaker.profile, routemaker.flow,
the major junctions of routemaker.intersections, and core.routing.route_profile).

Pure: no router, no database.
"""

from __future__ import annotations

import pytest

from core import routing
from routemaker import flow, profile
from routemaker import intersections as m
from routemaker.intersections import Control, Junction, Movement, Road

STEP = 30.0


def legs_of(*heights_lists, length_each=None):
    """Legs laid end to end, each sampled every STEP metres."""
    out = []
    at = 0.0
    for heights in heights_lists:
        length = length_each or (len(heights) - 1) * STEP
        out.append(profile.Leg(at, length, heights))
        at += length
    return out


def ramp(grade: float, samples: int, start: float = 10.0):
    return [start + grade * STEP * i for i in range(samples)]


class TestSamples:
    def test_samples_are_laid_end_to_end_by_the_leg_lengths(self):
        legs = legs_of([0, 1, 2], [5, 6], length_each=60.0)
        got = profile.sample_positions(legs, STEP)
        assert [m_ for m_, _ in got] == [0, 30, 60, 60, 90]
        assert [h for _, h in got] == [0, 1, 2, 5, 6]

    def test_a_samples_distance_is_never_past_its_legs_end(self):
        legs = [profile.Leg(100.0, 50.0, [1, 2, 3])]
        assert [m_ for m_, _ in profile.sample_positions(legs, STEP)] == [100, 130, 150]


class TestGrades:
    def test_a_steady_climb_has_that_grade_everywhere(self):
        samples = list(zip([i * STEP for i in range(10)], ramp(0.06, 10), strict=True))
        got = profile.grades(samples)
        assert got == pytest.approx([0.06] * 10)

    def test_a_downhill_is_negative(self):
        samples = list(zip([i * STEP for i in range(6)], ramp(-0.04, 6, 100), strict=True))
        assert profile.grades(samples) == pytest.approx([-0.04] * 6)

    def test_a_one_cell_blip_is_smoothed_not_read_as_a_wall(self):
        heights = [10.0] * 9
        heights[4] = 13.0  # 3 m over one 30 m cell would be 10%
        samples = list(zip([i * STEP for i in range(9)], heights, strict=True))
        got = profile.grades(samples)
        assert max(abs(g) for g in got) <= 0.0251

    def test_no_grade_across_a_gap_or_from_a_lone_sample(self):
        samples = [(0.0, 5.0), (30.0, None), (60.0, 7.0), (90.0, 9.0)]
        got = profile.grades(samples)
        assert got[0] is None and got[1] is None
        assert got[2] == pytest.approx(2 / 30)

    def test_bands_by_the_size_of_the_grade_either_way(self):
        assert [profile.band_of(g) for g in (0.0, 0.049, 0.05, 0.079, 0.08, -0.09, None)] == [
            0,
            0,
            1,
            1,
            2,
            2,
            0,
        ]


class TestClimbs:
    def test_a_sustained_six_percent_climb_is_listed_with_its_figures(self):
        heights = [10.0] * 4 + ramp(0.06, 11, 10.0) + [20.0 + 0.6] * 4
        samples = list(zip([i * STEP for i in range(len(heights))], heights, strict=True))
        got = profile.climb_list(
            samples, profile.grades(samples), [{"from_m": 0, "to_m": 2000, "tier": 3}]
        )
        assert len(got) == 1
        climb = got[0]
        assert climb.gain_m == pytest.approx(0.06 * 300, abs=0.5)
        assert climb.avg_grade == pytest.approx(0.06, abs=0.005)
        assert climb.max_grade >= 0.06 - 1e-9
        assert climb.tier == 3

    def test_a_gentle_long_slope_is_not_a_climb_worth_listing(self):
        samples = list(zip([i * STEP for i in range(50)], ramp(0.01, 50), strict=True))
        assert profile.climb_list(samples, profile.grades(samples)) == []


class TestFlow:
    def test_a_lane_carries_about_a_hundred_riders_a_minute_on_the_level(self):
        # PLAN: 0.37 x 0.7 x lane x 1.9 m/s, "about 100 riders a minute" per 11 ft lane.
        assert flow.level_riders_per_min(flow.LANE_WIDTH_M) == pytest.approx(98.9, abs=0.5)
        assert flow.level_riders_per_min(6.7) == pytest.approx(198, abs=2)

    def test_width_follows_the_lanes_and_direction(self):
        assert flow.usable_width_m("2", "none", 2, False) == pytest.approx(4 * 3.35)
        assert flow.usable_width_m("2", "none", 2, True) == pytest.approx(2 * 3.35)
        assert flow.usable_width_m("2", "none", None, None) == pytest.approx(2 * 3.35)
        assert flow.usable_width_m("1", "path", 1, None) == flow.PATH_WIDTH_M
        assert flow.usable_width_m("unknown", "unknown", None, None) is None

    def test_a_climb_slows_the_group_and_lowers_capacity(self):
        level = flow.level_riders_per_min(6.7)
        six = flow.adjusted_riders_per_min(6.7, 0.06, 1000.0)
        eight = flow.adjusted_riders_per_min(6.7, 0.08, 1000.0)
        assert six / level == pytest.approx(0.625, abs=0.01)
        assert eight < six < level
        # Never under the floor, however steep.
        assert flow.adjusted_riders_per_min(6.7, 0.3, 1000.0) / level == pytest.approx(
            flow.MIN_SPEED_RATIO
        )

    def test_a_short_ramp_costs_little_and_a_long_climb_the_whole_figure(self):
        assert flow.speed_ratio(0.08, 0.0) == 1.0
        assert (
            flow.speed_ratio(0.08, 30.0)
            > flow.speed_ratio(0.08, 90.0)
            > flow.speed_ratio(0.08, 600.0)
        )
        assert flow.speed_ratio(0.08, 150.0) == flow.speed_ratio(0.08, 5000.0)

    def test_a_steep_descent_needs_wider_spacing_but_a_gentle_one_does_not(self):
        assert flow.spacing_ratio(-0.03) == 1.0
        assert flow.spacing_ratio(-0.08) == pytest.approx(1 / 1.2, abs=0.01)
        assert flow.spacing_ratio(-0.5) == flow.MIN_SPACING_RATIO
        assert flow.adjusted_riders_per_min(6.7, -0.08, 0.0) < flow.level_riders_per_min(6.7)

    def test_the_level_and_a_slight_climb_are_the_headline_figure(self):
        level = flow.level_riders_per_min(6.7)
        assert flow.adjusted_riders_per_min(6.7, 0.0, 0.0) == level
        assert flow.adjusted_riders_per_min(6.7, 0.01, 500.0) == level
        assert flow.adjusted_riders_per_min(6.7, None, 0.0) == level

    def test_bands(self):
        assert [flow.band_index(v) for v in (0, 59, 60, 119, 120, 199, 200, 400)] == [
            0,
            0,
            1,
            1,
            2,
            2,
            3,
            3,
        ]

    def test_per_sample_riders_follow_width_and_grade_and_leave_unknown_none(self):
        heights = [10.0] * 6 + ramp(0.06, 10, 10.0) + [10 + 0.06 * 270] * 6
        samples = list(zip([i * STEP for i in range(len(heights))], heights, strict=True))
        grade_at = profile.grades(samples)
        total = samples[-1][0]
        stretches = [(420.0, 6.7), (total - 420.0, None)]
        adjusted, level = flow.per_sample(samples, grade_at, stretches)
        assert adjusted[0] == level[0] == round(flow.level_riders_per_min(6.7))
        climbing = [a for (m_, _), a in zip(samples, adjusted, strict=True) if 300 < m_ < 400]
        assert climbing and max(climbing) < level[0]
        assert adjusted[-1] is None and level[-1] is None


class TestRouteProfile:
    def leg(self, heights, length_m=None):
        length_m = length_m or (len(heights) - 1) * STEP
        return {"summary": {"length": length_m / 1000.0}, "elevation": heights}

    def test_the_profile_has_one_entry_a_sample_and_the_climb(self):
        heights = [10.0] * 4 + ramp(0.06, 11, 10.0) + [10.6 + 18] * 4
        body = routing.route_profile([self.leg(heights)], [{"from_m": 0, "to_m": 800, "tier": 2}])
        n = len(heights)
        assert body["interval_m"] == routing.ELEVATION_INTERVAL_M
        assert len(body["m"]) == len(body["elevation_m"]) == len(body["grade_pct"]) == n
        assert body["m"][:3] == [0, 30, 60]
        assert len(body["climbs"]) == 1
        assert body["climbs"][0]["avg_grade_pct"] == pytest.approx(6.0, abs=0.6)
        assert body["climbs"][0]["tier"] == 2
        assert body["climbs"][0]["capacity_drop_pct"] is None
        assert body["riders_per_min"] is None and body["flow"] is None
        assert body["crossings"] is None

    def test_a_route_with_no_elevation_has_no_profile(self):
        assert routing.route_profile([self.leg([])], []) is None
        assert routing.route_profile([self.leg([None, None])], []) is None

    def test_a_mass_ride_has_riders_the_narrowest_point_and_each_climbs_capacity_drop(self):
        heights = [10.0] * 6 + ramp(0.06, 14, 10.0) + [10 + 0.06 * 390] * 6
        total = (len(heights) - 1) * STEP
        stretches = [(total, 6.7)]
        major = m.Major(
            450.0,
            -77.0,
            38.9,
            frozenset({"14th street"}),
            ("14th Street",),
            "orange",
            Control.SIGNAL,
            4,
            3,
        )
        body = routing.route_profile([self.leg(heights)], [], stretches, [major])
        assert len(body["riders_per_min"]) == len(heights)
        assert body["flow"]["typical_riders_per_min"] == round(flow.level_riders_per_min(6.7))
        assert body["flow"]["narrowest_riders_per_min"] < body["flow"]["typical_riders_per_min"]
        assert 0 < body["flow"]["narrowest_m"] < total
        climb = body["climbs"][0]
        assert climb["capacity_drop_pct"] > 20
        assert climb["min_riders_per_min"] == body["flow"]["narrowest_riders_per_min"]
        assert body["crossings"] == [
            {
                "m": 450,
                "street": "14th Street",
                "severity": "orange",
                "control": "signal",
                "lanes": 4,
                "crossed_tier": 3,
                "corkers_needed": True,
            }
        ]

    def test_two_legs_join_at_the_first_legs_end(self):
        a = self.leg([1.0, 2.0, 3.0], 60.0)
        b = self.leg([3.0, 4.0], 30.0)
        body = routing.route_profile([a, b], [])
        assert body["m"] == [0, 30, 60, 60, 90]


def road(name, lanes=2, tier=2, oneway=None):
    return Road(
        tier,
        speed_mph=25,
        lanes=lanes,
        oneway=oneway,
        names=frozenset({name.lower()}),
        display=(name,),
    )


def junction(at, crossed, control=Control.SIGNAL, **fields):
    base = {
        "m": at,
        "lon": -77.0,
        "lat": 38.9,
        "movement": Movement.STRAIGHT,
        "incoming": Road(1),
        "outgoing": Road(1),
        "crossed": tuple(crossed),
        "control": control,
    }
    return Junction(**(base | fields))


class TestMajorJunctions:
    def run(self, *junctions):
        events = m.assess_route(list(junctions), group=True)
        return m.major_crossings(list(junctions), events)

    def test_a_signalized_crossing_of_a_two_lane_street_is_major_with_no_corkers(self):
        majors = self.run(junction(100.0, [road("Quiet Street", lanes=1)]))
        assert [x.m for x in majors] == [100.0]
        assert majors[0].severity is None and majors[0].corkers_needed is False

    def test_a_stop_controlled_crossing_counts_and_an_uncontrolled_one_does_not(self):
        majors = self.run(
            junction(100.0, [road("A Street")], Control.STOP),
            junction(400.0, [road("B Street")], Control.NONE),
        )
        assert [x.m for x in majors] == [100.0]

    def test_a_one_lane_one_way_street_is_not_a_wide_street(self):
        assert self.run(junction(100.0, [road("Alley", lanes=1, oneway=True)])) == []

    def test_a_flagged_junction_is_major_with_its_marker_and_needs_corkers(self):
        majors = self.run(junction(100.0, [road("Mass Avenue", lanes=2, tier=4)]))
        assert len(majors) == 1
        assert majors[0].severity == "red"
        assert majors[0].corkers_needed is True

    def test_one_street_twice_within_a_junction_is_counted_once(self):
        majors = self.run(
            junction(100.0, [road("A Street")]),
            junction(120.0, [road("A Street")]),
        )
        assert len(majors) == 1

    def test_results_are_in_route_order(self):
        majors = self.run(
            junction(900.0, [road("C Street", tier=3)]),
            junction(100.0, [road("A Street")]),
            junction(500.0, [road("B Street", tier=4)]),
        )
        assert [x.m for x in majors] == [100.0, 500.0, 900.0]

    def test_events_of_carries_the_majors_on_a_mass_ride_only(self):
        events = m.RouteEvents([], [])
        assert events.majors == [] and list(events) == []
