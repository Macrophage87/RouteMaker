"""The route's elevation profile, and a Mass Ride's grade-adjusted flow along it
(OWNER-DECISIONS 322, 323, 325, 328, 329, 332, 333, 394, 396; routemaker.profile,
routemaker.flow, the major junctions of routemaker.intersections, and
core.routing.route_profile).

Pure: no router, no database.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from core import junctions as core_junctions
from core import routing
from routemaker import climbs, flow, profile
from routemaker import intersections as m
from routemaker.intersections import Control, Junction, Movement, Road

STEP = 30.0
FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib"


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


def along(heights):
    """Samples every STEP metres from 0."""
    return list(zip([i * STEP for i in range(len(heights))], heights, strict=True))


def climb_of(*pieces, flat=4, base=10.0):
    """Flat, then a climb made of (intervals, grade) pieces, then flat: heights."""
    heights = [base] * flat
    at = base
    for intervals, grade in pieces:
        for _ in range(intervals):
            at += grade * STEP
            heights.append(at)
    return heights + [at] * flat


class TestSamples:
    def test_samples_are_laid_end_to_end_by_the_leg_lengths(self):
        legs = legs_of([0, 1, 2], [5, 6], length_each=60.0)
        got = profile.sample_positions(legs, STEP)
        assert [m_ for m_, _ in got] == [0, 30, 60, 60, 90]
        assert [h for _, h in got] == [0, 1, 2, 5, 6]

    def test_a_samples_distance_is_never_past_its_legs_end(self):
        legs = [profile.Leg(100.0, 50.0, [1, 2, 3])]
        assert [m_ for m_, _ in profile.sample_positions(legs, STEP)] == [100, 130, 150]

    def test_a_leg_with_no_elevation_is_a_gap_at_its_start_and_end(self):
        """Correctness review S3: nothing is read across a leg the router gave no heights."""
        legs = [
            profile.Leg(0.0, 120.0, [10.0] * 5),
            profile.Leg(120.0, 2000.0, []),
            profile.Leg(2120.0, 120.0, [130.0] * 5),
        ]
        got = profile.sample_positions(legs, STEP)
        assert (120.0, None) in got and (2120.0, None) in got
        assert [h for _, h in got].count(None) == 2


class TestGrades:
    def test_a_steady_climb_has_that_grade_everywhere(self):
        got = profile.grades(along(ramp(0.06, 10)))
        assert got == pytest.approx([0.06] * 10)

    def test_a_downhill_is_negative(self):
        assert profile.grades(along(ramp(-0.04, 6, 100))) == pytest.approx([-0.04] * 6)

    def test_a_one_cell_blip_is_smoothed_not_read_as_a_wall(self):
        heights = [10.0] * 9
        heights[4] = 13.0  # 3 m over one 30 m cell would be 10%
        got = profile.grades(along(heights))
        assert max(abs(g) for g in got) <= 0.0251

    def test_the_grade_is_read_over_two_samples_either_side(self):
        # A 3 m step between samples 4 and 5: the window of 120 m sees it at samples 3-6
        # only, at 3 m over 120 m; a window of one sample either side would read 5%.
        heights = [10.0] * 5 + [13.0] * 5
        got = profile.grades(along(heights))
        assert got[2] == pytest.approx(0.0)
        assert got[3] == pytest.approx(3 / 120)
        assert got[4] == pytest.approx(3 / 120)
        assert got[7] == pytest.approx(0.0)

    def test_no_grade_across_a_gap_or_from_a_lone_sample(self):
        samples = [(0.0, 5.0), (30.0, None), (60.0, 7.0), (90.0, 9.0)]
        got = profile.grades(samples)
        assert got[0] is None and got[1] is None
        assert got[2] == pytest.approx(2 / 30)

    def test_two_samples_at_one_place_have_no_grade_and_do_not_divide_by_zero(self):
        assert profile.grades([(60.0, 5.0), (60.0, 6.0)]) == [None, None]

    def test_bands_by_the_size_of_the_grade_either_way(self):
        got = [profile.band_of(g) for g in (0.0, 0.049, 0.05, 0.079, 0.08, -0.09, None)]
        assert got == [0, 0, 1, 1, 2, 2, 0]


class TestClimbs:
    def listed(self, heights, spans=()):
        samples = along(heights)
        return profile.climb_list(samples, profile.grades(samples), list(spans))

    def test_a_sustained_six_percent_climb_is_listed_with_its_figures(self):
        heights = [10.0] * 4 + ramp(0.06, 11, 10.0) + [20.0 + 0.6] * 4
        got = self.listed(heights, [{"from_m": 0, "to_m": 2000, "tier": 3}])
        assert len(got) == 1
        climb = got[0]
        assert climb.gain_m == pytest.approx(0.06 * 300, abs=0.5)
        assert climb.avg_grade == pytest.approx(0.06, abs=0.005)
        assert climb.max_grade >= 0.06 - 1e-9
        assert climb.tier == 3

    def test_a_gentle_long_slope_is_not_a_climb_worth_listing(self):
        assert self.listed(ramp(0.01, 50)) == []

    def test_a_gentle_climb_with_a_steep_pitch_is_listed_for_the_pitch(self):
        """2.5% on average, with a 6% pitch: kept, because it is steep somewhere (5%)."""
        got = self.listed(climb_of((16, 0.01625), (4, 0.06)))
        assert len(got) == 1
        assert got[0].avg_grade == pytest.approx(0.025, abs=0.001)
        assert got[0].max_grade == pytest.approx(0.06, abs=0.002)

    def test_a_gentle_climb_whose_pitch_stays_under_five_percent_is_not_listed(self):
        """2.5% on average, steepest 4%: neither half of the rule."""
        assert self.listed(climb_of((16, 0.02125), (4, 0.04))) == []
        assert self.listed(climb_of((20, 0.025))) == []

    def test_a_steady_climb_of_three_and_a_half_percent_is_listed_for_its_average(self):
        """No pitch reaches 5%, but it averages 3% or more."""
        got = self.listed(climb_of((20, 0.035)))
        assert len(got) == 1
        assert got[0].max_grade < profile.MIN_CLIMB_PEAK_GRADE

    def test_a_climbs_stress_is_the_highest_tier_it_rides(self):
        spans = [{"from_m": 0, "to_m": 300, "tier": 2}, {"from_m": 300, "to_m": 5000, "tier": 4}]
        got = self.listed(climb_of((20, 0.04)), spans)
        assert [c.tier for c in got] == [4]

    def test_the_runs_can_be_given_once_and_give_the_same_climbs(self):
        samples = along(climb_of((20, 0.04)))
        grade_at = profile.grades(samples)
        runs = climbs.runs(samples)
        assert profile.climb_list(samples, grade_at, (), runs) == profile.climb_list(
            samples, grade_at
        )

    def test_inside_is_the_samples_from_one_place_to_another_both_included(self):
        assert list(profile.inside([0, 30, 60, 60, 90, 120], 60, 90)) == [2, 3, 4]


class TestFlowFigures:
    """Each figure the module docstring, the dev report and 394 quote (mutation review,
    finding 3): FOLLOWUP-FLOW-CALIBRATION will change them, deliberately, here."""

    def test_a_lane_carries_about_ninety_nine_riders_a_minute_on_the_level(self):
        assert flow.level_riders_per_min(flow.LANE_WIDTH_M) == pytest.approx(98.9, abs=0.05)
        assert flow.level_riders_per_min(6.7) == pytest.approx(197.8, abs=0.05)

    def test_the_climb_factor_at_three_six_and_eight_percent(self):
        assert flow.speed_ratio(0.03, 1e3) == pytest.approx(1 / 1.24)
        assert flow.speed_ratio(0.06, 1e3) == pytest.approx(0.625)
        assert flow.speed_ratio(0.08, 1e3) == pytest.approx(1 / 1.84)

    def test_a_climb_of_one_percent_or_less_costs_nothing(self):
        assert flow.speed_ratio(0.01, 1e3) == 1.0
        assert flow.speed_ratio(0.0, 1e3) == 1.0
        assert flow.speed_ratio(-0.05, 1e3) == 1.0

    def test_the_climb_floor_is_thirty_percent_just_past_its_kink(self):
        # 1 / (1 + 12 (g - 1%)) reaches 0.3 at about 20.4%.
        assert flow.MIN_SPEED_RATIO == 0.3
        assert flow.speed_ratio(0.15, 1e3) == pytest.approx(1 / (1 + 12 * 0.14))
        assert flow.speed_ratio(0.22, 1e3) == pytest.approx(0.3)
        assert flow.speed_ratio(0.5, 1e3) == pytest.approx(0.3)

    def test_the_slowing_sets_in_linearly_over_the_first_150_m(self):
        full = flow.speed_ratio(0.06, 1e3)
        assert flow.speed_ratio(0.06, 0.0) == 1.0
        assert flow.speed_ratio(0.06, 75.0) == pytest.approx(1 - (1 - full) / 2)
        assert flow.speed_ratio(0.06, 37.5) == pytest.approx(1 - (1 - full) / 4)
        assert flow.speed_ratio(0.06, 150.0) == pytest.approx(full)
        assert flow.KICK_M == 150.0

    def test_the_descent_factor_and_its_floor(self):
        assert flow.spacing_ratio(-0.04) == 1.0
        assert flow.spacing_ratio(-0.03) == 1.0
        assert flow.spacing_ratio(-0.08) == pytest.approx(1 / 1.2)
        # 1 / (1 + 5 (g - 4%)) reaches 0.6 at about 17.3%.
        assert flow.spacing_ratio(-0.18) == pytest.approx(0.6)
        assert flow.spacing_ratio(-0.12) == pytest.approx(1 / 1.4)
        assert flow.spacing_ratio(-0.25) == flow.MIN_SPACING_RATIO == 0.6
        assert flow.spacing_ratio(0.08) == 1.0

    def test_the_grade_factor_is_the_two_together_and_one_where_unknown(self):
        assert flow.grade_factor(None) == 1.0
        assert flow.grade_factor(0.06, 1e3) == pytest.approx(0.625)
        assert flow.grade_factor(-0.08) == pytest.approx(1 / 1.2)
        assert flow.grade_factor(0.0, 0.0) == 1.0

    def test_riders_at_is_the_level_figure_times_the_grade_factor_unrounded(self):
        level = flow.level_riders_per_min(6.7)
        got = flow.riders_at(6.7, 0.06, 1e3)
        assert got == pytest.approx(level * 0.625)
        assert isinstance(got, float) and got != round(got)
        assert flow.riders_at(6.7, None) == level
        assert flow.adjusted_riders_per_min(6.7, 0.06, 1e3) == got

    def test_climbed_is_metres_from_the_foot_of_the_climb(self):
        runs = [climbs.Run(100.0, 400.0, 18.0), climbs.Run(500.0, 800.0, -12.0)]
        assert flow.climbed_at(160.0, runs) == 60.0
        assert flow.climbed_at(400.0, runs) == 300.0
        assert flow.climbed_at(50.0, runs) == 0.0
        # A descent is not a climb.
        assert flow.climbed_at(600.0, runs) == 0.0
        assert flow.climbed_along([0, 100, 160, 450, 600], runs) == [0, 0, 60, 0, 0]


class TestWidth:
    def test_width_follows_the_lanes_and_direction(self):
        assert flow.usable_width_m("2", "none", 2, False) == pytest.approx(4 * 3.35)
        assert flow.usable_width_m("2", "none", 2, True) == pytest.approx(2 * 3.35)
        assert flow.usable_width_m("2", "none", None, None) == pytest.approx(2 * 3.35)
        assert flow.usable_width_m("2", "none", 1, True) == pytest.approx(3.35)

    def test_a_path_is_ten_feet_whatever_its_lanes(self):
        assert flow.PATH_WIDTH_M == 3.0
        assert flow.usable_width_m("1", "path", 2, False) == 3.0

    def test_the_pipelines_int_tiers_are_taken_as_the_routers_text_keys_are(self):
        for tier in (1, 2, 3, 4):
            assert flow.usable_width_m(tier, "none", 2, False) == flow.usable_width_m(
                str(tier), "none", 2, False
            )
        assert flow.usable_width_m(None, None, 2, False) is None
        assert flow.usable_width_m("unknown", "unknown", None, None) is None
        assert flow.usable_width_m(0, "none", 2, False) is None
        assert flow.usable_width_m(True, "none", 2, False) is None

    def test_an_avoid_stretch_has_no_carrying_capacity(self):
        """OWNER-DECISIONS 325: "just marked avoid with no carrying capacity"."""
        assert flow.usable_width_m(5, "none", 3, False) is None
        assert flow.usable_width_m("5", "none", 3, False) is None
        assert flow.is_avoid(5) and flow.is_avoid("5")
        assert not flow.is_avoid(4) and not flow.is_avoid("unknown") and not flow.is_avoid(None)


class TestBands:
    def test_bands(self):
        got = [flow.band_index(v) for v in (0, 59, 60, 119, 120, 199, 200, 400)]
        assert got == [0, 0, 1, 1, 2, 2, 3, 3]

    def test_the_front_end_draws_the_same_bands_and_words(self):
        """One source for the edges and words (operations review NIT 6): the chart's
        FLOW_BANDS is held to `flow.BAND_EDGES` and `flow.BAND_WORDS`."""
        text = (FRONTEND / "profileChart.ts").read_text()
        block = text[text.index("export const FLOW_BANDS") :]
        block = block[: block.index("];")]
        froms = [int(x) for x in re.findall(r"\bfrom: (\d+)", block)]
        words = re.findall(r'\bword: "([^"]+)"', block)
        assert tuple(froms) == (0, *flow.BAND_EDGES)
        assert tuple(words) == flow.BAND_WORDS


class TestPerSample:
    def test_per_sample_riders_follow_width_and_grade_and_leave_unknown_none(self):
        heights = [10.0] * 6 + ramp(0.06, 10, 10.0) + [10 + 0.06 * 270] * 6
        samples = along(heights)
        grade_at = profile.grades(samples)
        total = samples[-1][0]
        stretches = [(420.0, 6.7), (total - 420.0, None)]
        adjusted, level = flow.per_sample(samples, grade_at, stretches)
        assert adjusted[0] == level[0] == pytest.approx(flow.level_riders_per_min(6.7))
        climbing = [a for (m_, _), a in zip(samples, adjusted, strict=True) if 300 < m_ < 400]
        assert climbing and max(climbing) < level[0]
        assert adjusted[-1] is None and level[-1] is None

    def test_a_sample_on_a_stretch_boundary_is_on_the_earlier_stretch(self):
        samples = along([10.0] * 5)  # 0, 30, 60, 90, 120
        adjusted, _level = flow.per_sample(samples, [0.0] * 5, [(60.0, 3.35), (60.0, 6.7)])
        one, two = flow.level_riders_per_min(3.35), flow.level_riders_per_min(6.7)
        assert adjusted == pytest.approx([one, one, one, two, two])
        assert flow.stretch_index([0, 60, 61, 500], [(60.0, 1.0), (60.0, 2.0)]) == [0, 0, 1, 1]
        assert flow.stretch_index([0, 10], []) == [None, None]

    def test_per_sample_takes_the_profiles_runs_when_given(self):
        samples = along(climb_of((20, 0.06)))
        grade_at = profile.grades(samples)
        stretches = [(1e4, 6.7)]
        runs = climbs.runs(samples)
        assert flow.per_sample(samples, grade_at, stretches, runs) == flow.per_sample(
            samples, grade_at, stretches
        )


class TestThin:
    def test_a_short_route_keeps_every_sample(self):
        assert profile.thin([1.0] * 50, [0.0] * 50) == list(range(50))

    def test_a_long_route_keeps_about_the_limit_its_steepest_lowest_and_gaps(self):
        n = 9000
        heights: list[float | None] = [10.0] * n
        grade_at: list[float | None] = [0.01] * n
        riders: list[float | None] = [190.0] * n
        heights[4321] = None
        grade_at[4321] = None
        grade_at[777] = 0.11
        riders[6001] = 41.0
        riders[8000] = None
        keep = profile.thin(heights, grade_at, riders)
        assert len(keep) <= profile.MAX_SAMPLES * 1.1
        assert keep == sorted(set(keep))
        assert keep[0] == 0 and keep[-1] == n - 1
        assert {777, 4321, 6001, 8000} <= set(keep)


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
        assert body["avoid"] is None and body["unchecked"] is None

    def test_a_route_with_no_elevation_has_no_profile(self):
        assert routing.route_profile([self.leg([])], []) is None
        assert routing.route_profile([self.leg([None, None])], []) is None

    def test_a_leg_with_no_elevation_invents_no_climb_across_it(self):
        """Correctness review S3: a 120 m jump across a 2 km leg with no heights would
        read as a 6% climb; the leg is a gap instead."""
        body = routing.route_profile(
            [self.leg([10.0] * 5), self.leg([], 2000.0), self.leg([130.0] * 5)], []
        )
        assert body["climbs"] == []
        assert body["m"][4:7] == [120, 120, 2120]
        assert body["elevation_m"][5] is None and body["elevation_m"][6] is None
        assert all(g is None or abs(g) < 1 for g in body["grade_pct"])

    def mass(self, heights, stretches, majors=()):
        return routing.route_profile([self.leg(heights)], [], stretches, list(majors))

    def test_a_mass_ride_has_riders_the_narrowest_point_and_each_climbs_capacity_drop(self):
        heights = [10.0] * 6 + ramp(0.06, 14, 10.0) + [10 + 0.06 * 390] * 6
        total = (len(heights) - 1) * STEP
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
        body = self.mass(heights, [(total, 6.7, None)], [major])
        assert len(body["riders_per_min"]) == len(heights)
        assert all(isinstance(r, int) for r in body["riders_per_min"])
        assert body["flow"]["typical_riders_per_min"] == round(flow.level_riders_per_min(6.7))
        assert body["flow"]["narrowest_riders_per_min"] < body["flow"]["typical_riders_per_min"]
        assert 0 < body["flow"]["narrowest_m"] < total
        climb = body["climbs"][0]
        assert climb["capacity_drop_pct"] > 20
        assert climb["min_riders_per_min"] == body["flow"]["narrowest_riders_per_min"]
        assert body["avoid"] == [] and body["unchecked"] == []
        assert body["crossings"] == [
            {
                "m": 450,
                "street": "14th Street",
                "severity": "orange",
                "control": "signal",
                "lanes": 4,
                "crossed_tier": 3,
                "kind": "flagged",
                "corkers_needed": True,
            }
        ]

    def test_the_typical_figure_is_the_median(self):
        # Three samples a stretch: 99, 99, 99 | 198, 198 | 297, 297 (by width): median 198.
        heights = [10.0] * 7
        stretches = [(75.0, 3.35, None), (60.0, 6.7, None), (100.0, 10.05, None)]
        body = self.mass(heights, stretches)
        assert body["riders_per_min"] == [99, 99, 99, 198, 198, 297, 297]
        assert body["flow"]["typical_riders_per_min"] == 198
        assert body["flow"]["narrowest_riders_per_min"] == 99
        assert body["flow"]["narrowest_m"] == 0

    def test_intersections_not_read_are_null_and_none_found_is_an_empty_list(self):
        """Correctness S2, spec SHOULD-FIX 2: "not checked" is never sent as "none"."""
        heights = [10.0] * 5
        assert (
            routing.route_profile([self.leg(heights)], [], [(200.0, 6.7, None)], None)["crossings"]
            is None
        )
        assert self.mass(heights, [(200.0, 6.7, None)], [])["crossings"] == []

    def test_an_avoid_stretch_carries_no_figure_and_is_said_as_avoid(self):
        """OWNER-DECISIONS 325."""
        heights = [10.0] * 7
        stretches = [(75.0, 6.7, None), (60.0, None, routing.STRETCH_AVOID), (100.0, 6.7, None)]
        body = self.mass(heights, stretches)
        assert body["riders_per_min"][3:5] == [None, None]
        assert body["avoid"] == [{"from_m": 90, "to_m": 120}]
        assert body["unchecked"] == []
        assert body["flow"]["narrowest_riders_per_min"] == 198

    def test_an_untraced_leg_is_unchecked(self):
        heights = [10.0] * 7
        stretches = [(75.0, 6.7, None), (200.0, None, routing.STRETCH_UNTRACED)]
        body = self.mass(heights, stretches, [])
        assert body["unchecked"] == [{"from_m": 90, "to_m": 180}]
        assert body["avoid"] == []

    def test_a_long_route_is_thinned_after_its_figures_are_worked_out(self):
        n = 7001  # 210 km
        heights = [100.0 + 20.0 * math.sin(i / 40.0) for i in range(n)]
        heights[3000:3011] = [heights[3000] + 0.09 * STEP * k for k in range(11)]
        heights[5000] = None
        total = (n - 1) * STEP
        stretches = [(150_000.0, 6.7, None), (60.0, 3.0, None), (total, 6.7, None)]
        body = self.mass(heights, stretches)
        full_samples = along(heights)
        full_grades = profile.grades(full_samples)
        assert len(body["m"]) <= profile.MAX_SAMPLES * 1.1
        assert body["m"][0] == 0 and body["m"][-1] == round(total)
        steepest = max(abs(g) for g in full_grades if g is not None)
        assert max(abs(g) for g in body["grade_pct"] if g is not None) == pytest.approx(
            steepest * 100, abs=0.05
        )
        assert body["flow"]["narrowest_m"] in body["m"]
        assert None in body["elevation_m"]
        assert len(body["climbs"]) == len(profile.climb_list(full_samples, full_grades))

    def test_two_legs_join_at_the_first_legs_end(self):
        a = self.leg([1.0, 2.0, 3.0], 60.0)
        b = self.leg([3.0, 4.0], 30.0)
        body = routing.route_profile([a, b], [])
        assert body["m"] == [0, 30, 60, 60, 90]


class TestFlowStretches:
    def test_lanes_and_one_way_reach_the_width_and_avoid_and_untraced_are_noted(self):
        class P:
            """A traced piece: only its metres are read here."""

            def __init__(self, metres):
                self.metres = metres

        classes = [
            routing.PieceClass("2", "none", None, 2, True),
            routing.PieceClass("2", "none", None, 2, False),
            routing.PieceClass("5", "none", None, 3, False),
            ("unknown", "unknown"),
        ]
        got = routing._flow_stretches(
            [(0, 4), 500.0], [P(100.0), P(100.0), P(50.0), P(25.0)], classes
        )
        assert got == [
            (100.0, pytest.approx(6.7), None),
            (100.0, pytest.approx(13.4), None),
            (50.0, None, routing.STRETCH_AVOID),
            (25.0, None, None),
            (500.0, None, routing.STRETCH_UNTRACED),
        ]


def road(name, lanes=2, tier=2, oneway=None):
    return Road(
        tier,
        speed_mph=25,
        lanes=lanes,
        oneway=oneway,
        names=frozenset({name.lower()}) if name else frozenset(),
        display=(name,) if name else (),
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
        "continues": True,
    }
    return Junction(**(base | fields))


class TestMajorJunctions:
    """OWNER-DECISIONS 396: major is a crossed or joined road of LTS 3 or higher, whatever
    the control, or a junction with a stress rating; no lane counting, no stop-sign rule."""

    def run(self, *junctions):
        events = m.assess_route(list(junctions), group=True)
        return m.major_crossings(list(junctions), events)

    def test_a_controlled_crossing_of_a_wide_quiet_street_is_not_major(self):
        assert self.run(junction(100.0, [road("Quiet Street", lanes=2, tier=2)])) == []
        for control in (Control.STOP, Control.ALL_STOP, Control.CROSS_STOP, Control.NONE):
            assert self.run(junction(100.0, [road("A Street", lanes=3, tier=2)], control)) == []

    def test_a_flagged_junction_is_major_with_its_marker_and_needs_corkers(self):
        majors = self.run(junction(100.0, [road("Mass Avenue", lanes=2, tier=4)]))
        assert len(majors) == 1
        assert majors[0].severity == "red" and majors[0].kind == m.MAJOR_FLAGGED
        assert majors[0].corkers_needed is True

    def test_a_signalised_right_onto_an_arterial_is_major_though_group_mode_flags_nothing(self):
        arterial = road("Wisconsin Avenue", lanes=2, tier=4)
        right = junction(
            100.0, [], Control.SIGNAL, movement=Movement.RIGHT, outgoing=arterial, continues=False
        )
        assert m.assess_route([right], group=True) == []
        majors = self.run(right)
        assert [(x.kind, x.crossed_tier, x.severity) for x in majors] == [
            (m.MAJOR_JOINING, 4, None)
        ]
        assert majors[0].corkers_needed is True
        assert majors[0].display == ("Wisconsin Avenue",)

    def test_riding_along_a_busy_road_past_a_busy_cross_street_is_major(self):
        avenue = road("Connecticut Avenue", lanes=2, tier=4)
        past = junction(
            100.0,
            [road("Albemarle Street", lanes=1, tier=3)],
            Control.CROSS_STOP,
            incoming=avenue,
            outgoing=avenue,
        )
        assert m.assess_route([past], group=True) == []
        majors = self.run(past)
        assert [(x.kind, x.crossed_tier) for x in majors] == [(m.MAJOR_CROSSING, 3)]
        # Corkers by the crossed road's tier (142), not the rider's own road's.
        assert majors[0].corkers_needed is True
        assert majors[0].display == ("Albemarle Street",)

    def test_riding_along_a_busy_road_past_a_quiet_side_street_is_not_major(self):
        avenue = road("Connecticut Avenue", tier=4)
        past = junction(100.0, [road("Quiet Street", tier=1)], incoming=avenue, outgoing=avenue)
        assert self.run(past) == []

    def test_straight_on_from_one_busy_road_into_the_next_is_not_joining(self):
        into = junction(
            100.0,
            [],
            Control.NONE,
            incoming=road("Old Road", tier=3),
            outgoing=road("New Road", tier=3),
            continues=False,
        )
        assert self.run(into) == []

    def test_a_left_from_a_one_way_busy_road_onto_another_busy_road_is_major(self):
        left = junction(
            100.0,
            [],
            Control.SIGNAL,
            movement=Movement.LEFT,
            incoming=road("I Street", tier=3, oneway=True),
            outgoing=road("17th Street", tier=3),
            continues=False,
        )
        majors = self.run(left)
        assert [x.kind for x in majors] == [m.MAJOR_JOINING]

    def test_one_junction_crossing_two_busy_streets_is_one_major_for_the_busier(self):
        both = junction(
            100.0,
            [road("A Street", tier=3), road("B Street", tier=4)],
            Control.CROSS_STOP,
            incoming=road("Main Avenue", tier=4),
            outgoing=road("Main Avenue", tier=4),
        )
        majors = self.run(both)
        assert len(majors) == 1
        assert majors[0].crossed_tier == 4 and majors[0].display == ("B Street",)

    def test_one_street_twice_within_a_junction_is_counted_once(self):
        avenue = road("Main Avenue", tier=4)
        majors = self.run(
            junction(100.0, [road("A Street", tier=3)], Control.CROSS_STOP, incoming=avenue),
            junction(120.0, [road("A Street", tier=3)], Control.CROSS_STOP, incoming=avenue),
        )
        assert len(majors) == 1

    def test_two_unnamed_carriageways_within_a_junction_are_counted_once(self):
        avenue = road("Main Avenue", tier=4)
        majors = self.run(
            junction(100.0, [road("", tier=3)], Control.CROSS_STOP, incoming=avenue),
            junction(130.0, [road("", tier=3)], Control.CROSS_STOP, incoming=avenue),
        )
        assert len(majors) == 1

    def test_a_flagged_junction_is_not_counted_again_for_its_busy_road(self):
        majors = self.run(junction(100.0, [road("Mass Avenue", tier=4)]))
        assert len(majors) == 1 and majors[0].kind == m.MAJOR_FLAGGED

    def test_results_are_in_route_order(self):
        majors = self.run(
            junction(900.0, [road("C Street", tier=3)]),
            junction(100.0, [road("A Street", tier=4)]),
            junction(500.0, [road("B Street", tier=4)]),
        )
        assert [x.m for x in majors] == [100.0, 500.0, 900.0]

    def test_corkers_follow_the_crossed_tier(self):
        def major(tier):
            return m.Major(0.0, 0.0, 0.0, frozenset(), (), "orange", Control.SIGNAL, None, tier)

        assert [major(t).corkers_needed for t in (None, 1, 2, 3, 4, 5)] == [
            False,
            False,
            False,
            True,
            True,
            True,
        ]

    def test_route_events_carry_the_majors(self):
        events = m.RouteEvents([], [])
        assert events.majors == [] and list(events) == []

    def test_a_failure_finding_majors_keeps_the_events_and_the_flagged_majors(self, monkeypatch):
        """Operations review SHOULD-FIX 1: a bug in the new code costs only the chart's
        extra crossings, never the planner's junction events."""
        built = [junction(100.0, [road("Mass Avenue", tier=4)])]
        events = m.assess_route(built, group=True)
        assert events

        def broken(*_args):
            raise RuntimeError("boom")

        monkeypatch.setattr(core_junctions, "major_crossings", broken)
        got = core_junctions.with_majors(built, events)
        assert list(got) == events
        assert got.majors == m.majors_of_events(events)
        assert len(got.majors) == 1
