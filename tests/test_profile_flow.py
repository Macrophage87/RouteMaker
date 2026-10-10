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
from routemaker import calm, climbs, flow, profile
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

    def test_the_groups_length_is_plans_worked_example(self):
        """PLAN, "The main control" (item 128): on a 22 ft road at 7 mph, 500 riders make
        about 1,560 ft (474 m) of group and 2,000 riders about 1.18 mi (1.9 km)."""
        road_m = 22 * 0.3048
        assert flow.CRUISE_PACE_MS == pytest.approx(3.129, abs=0.001)
        assert flow.group_length_m(500, road_m) == pytest.approx(474, abs=2)
        assert flow.group_length_m(500, road_m) * 3.28084 == pytest.approx(1560, abs=10)
        assert flow.group_length_m(2000, road_m) / 1609.344 == pytest.approx(1.18, abs=0.005)
        assert flow.GROUP_DEFAULT_WIDTH_M == pytest.approx(6.7)

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
    def test_width_is_the_rides_own_side(self):
        # OWNER-DECISIONS 406 ("We should only plan on our own side of a two way street"):
        # the estimate is the lanes in one direction, so a two-way street of 2 + 2 lanes is
        # 2 lanes (6.7 m), not the 4 (13.4 m) this test held before the rebuild bundle, and
        # a street with no lane count is one lane. `lanes` is already a direction's.
        assert flow.usable_width_m("2", "none", 2, False) == pytest.approx(2 * 3.35)
        assert flow.usable_width_m("2", "none", 2, True) == pytest.approx(2 * 3.35)
        assert flow.usable_width_m("2", "none", None, None) == pytest.approx(3.35)
        assert flow.usable_width_m("2", "none", 1, True) == pytest.approx(3.35)
        assert flow.usable_width_m("2", "none", 3, False) == pytest.approx(3 * 3.35)

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

    def test_a_path_marked_avoid_has_no_width_and_an_unknown_tier_none(self):
        """Mutation re-review NITs F13, F02, F04."""
        assert flow.usable_width_m(5, "path", None, None) is None
        assert flow.usable_width_m("5", "path", None, None) is None
        assert flow.usable_width_m(6, "none", 2, False) is None
        assert flow.usable_width_m("9", "none", 2, False) is None
        assert flow.tier_number(True) is None

    def test_the_grade_factor_starts_at_the_foot_of_the_climb_by_default(self):
        """Mutation re-review NIT F12."""
        assert flow.grade_factor(0.06) == flow.speed_ratio(0.06, 0.0) == 1.0
        assert flow.grade_factor(0.06, flow.KICK_M) < 1.0

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

    @staticmethod
    def peaked(n=6001, peak=3000):
        """A 180 km route of rolling hills with one sharp 150 m peak and a 2 m valley floor:
        the summit and the floor are where the grade is near 0."""
        heights = [60.0 + 15.0 * math.sin(i / 35.0) for i in range(n)]
        for k in range(-12, 13):
            heights[peak + k] = 150.0 - abs(k) * 7.0
        heights[1500] = 2.0
        return heights

    @pytest.mark.parametrize("mass", [False, True])
    def test_thinning_keeps_the_summit_and_the_valley_floor(self, mass):
        """Correctness re-review R2: the steepest sample a window keeps is never its
        summit; the summary's elevation range and the drawn peak need it."""
        heights = self.peaked()
        grade_at = profile.grades(along(heights))
        riders = [190.0] * len(heights) if mass else None
        keep = profile.thin(heights, grade_at, riders)
        kept = [heights[i] for i in keep]
        assert max(kept) == 150.0
        assert min(kept) == 2.0

    @pytest.mark.parametrize("mass", [False, True])
    def test_thinning_sends_close_to_the_limit_and_never_far_past_it(self, mass):
        """Operations re-review A and correctness R2: the window is sized from the picks
        made, so a long route sends close to the limit (it sent about half), and never
        more than one window's picks over it."""
        heights = self.peaked()
        grade_at = profile.grades(along(heights))
        riders = [190.0 - (i % 7) for i in range(len(heights))] if mass else None
        keep = profile.thin(heights, grade_at, riders)
        most = profile.WINDOW_PICKS_MASS if mass else profile.WINDOW_PICKS
        assert profile.MAX_SAMPLES * 0.85 <= len(keep) <= profile.MAX_SAMPLES + most + 2

    def test_a_window_full_of_picks_stays_within_a_windows_picks_of_the_limit(self):
        """Every pick in every window: a gap, an unknown riders figure, distinct steepest,
        highest, lowest and lowest-riders samples."""
        n = 9000
        heights: list[float | None] = [float((i * 37) % 101) for i in range(n)]
        for i in range(0, n, 11):
            heights[i] = None
        grade_at: list[float | None] = [((i * 53) % 17) / 100 for i in range(n)]
        riders: list[float | None] = [float((i * 29) % 97) + 1 for i in range(n)]
        for i in range(5, n, 13):
            riders[i] = None
        keep = profile.thin(heights, grade_at, riders)
        assert len(keep) <= profile.MAX_SAMPLES + profile.WINDOW_PICKS_MASS + 2

    @staticmethod
    def runs_of_riders(n, runs):
        """`n` riders figures at 200 with `runs` bottlenecks of four samples each, every
        one lowest in its middle (so a window's lowest pick is never a run's end)."""
        riders: list[float | None] = [200.0] * n
        for k in range(runs):
            start = 10 + 20 * k
            riders[start : start + 4] = [50.0, 20.0, 30.0, 55.0]
        return riders

    def test_the_bottleneck_ends_are_kept_up_to_a_quarter_of_the_limit(self, monkeypatch):
        """Mutation r4 NIT 6 (T09-T11): 10 run ends at a limit of 40 (a quarter) are all
        kept; 12 are more than a quarter, and none is."""
        monkeypatch.setattr(profile, "_window_picks", lambda h, *_a: {0, len(h) - 1})
        n = 400
        heights = [10.0] * n
        grades = [0.0] * n
        five = self.runs_of_riders(n, 5)
        ends = profile._bottleneck_ends(five)
        assert len(ends) == 10 == 40 // profile.BOTTLENECK_END_SHARE
        assert set(profile.thin(heights, grades, five, limit=40)) == ends | {0, n - 1}
        six = self.runs_of_riders(n, 6)
        assert len(profile._bottleneck_ends(six)) == 12
        assert profile.thin(heights, grades, six, limit=40) == [0, n - 1]

    def test_the_bottleneck_ends_are_kept_when_no_narrower_window_fits(self, monkeypatch):
        """Mutation r4 NIT 6 (T13): the first pass keeps the run ends too, for when the
        bisection accepts no narrower window."""
        first = {}

        def picks(h, _g, _r, window):
            first.setdefault("window", window)
            return {0, len(h) - 1} if window >= first["window"] else set(range(len(h)))

        monkeypatch.setattr(profile, "_window_picks", picks)
        n = 400
        riders = self.runs_of_riders(n, 5)
        keep = profile.thin([10.0] * n, [0.0] * n, riders, limit=40)
        assert set(keep) == profile._bottleneck_ends(riders) | {0, n - 1}


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

    def test_off_a_mass_ride_the_profile_carries_the_rolling_score(self):
        """460.12, 461d: one calm ratio a sample, from the sections and the junctions."""
        heights = [10.0] * 200
        spans = [
            {"from_m": 0, "to_m": 300, "tier": 3, "facility": "none"},
            {"from_m": 300, "to_m": 5970, "tier": 2, "facility": "none"},
        ]
        pricing = calm.Pricing(use_roads=0.1)
        body = routing.route_profile([self.leg(heights)], spans, calm_pricing=pricing, events=[])
        ratio = body["calm"]["ratio"]
        assert len(ratio) == len(body["m"])
        # Raised over the mile around the LTS 3 stretch only.
        assert ratio[0] > 1.0 and ratio[-1] == 1.0
        assert body["calm"]["junctions_counted"] is True
        assert body["calm"]["estimate"] is True
        assert routing.route_profile([self.leg(heights)], spans)["calm"] is None

    def test_with_the_traced_pieces_each_road_is_priced_by_its_own_cost(self):
        """stress-number.md section 4: each road at its own routing cost, so not an estimate."""
        heights = [10.0] * 200
        spans = [
            {"from_m": 0, "to_m": 300, "tier": 3, "facility": "none"},
            {"from_m": 300, "to_m": 5970, "tier": 2, "facility": "none"},
        ]
        busy = calm.Road(road_class="primary", lanes=2, speed_limit_kph=56)
        quiet = calm.Road(road_class="residential", density=20)
        pieces = [(300.0, 3, "none", busy), (5670.0, 2, "none", quiet)]
        pricing = calm.Pricing(use_roads=0.1)
        body = routing.route_profile(
            [self.leg(heights)], spans, calm_pricing=pricing, events=[], calm_pieces=pieces
        )
        assert body["calm"]["estimate"] is False
        first, second = body["calm"]["steps"]
        assert first["ratio"] == pytest.approx(
            calm.edge_factor(busy, 3, 0.1) / calm.quiet_factor(0.1, urban=False), abs=0.01
        )
        assert second["ratio"] == 1.0

    def test_a_long_route_keeps_the_peak_window_when_thinned(self, monkeypatch):
        """Correctness review nit: the most stressful mile survives thinning."""
        monkeypatch.setattr(profile, "MAX_SAMPLES", 50)
        n = 400
        spans = [
            {"from_m": 0, "to_m": 7000, "tier": 2, "facility": "none"},
            {"from_m": 7000, "to_m": 7030, "tier": 4, "facility": "none"},
            {"from_m": 7030, "to_m": (n - 1) * STEP, "tier": 2, "facility": "none"},
        ]
        monkeypatch.setattr(profile, "thin", lambda h, *_a, **_k: [0, len(h) - 1])
        body = routing.route_profile(
            [self.leg([10.0] * n)], spans, calm_pricing=calm.Pricing(use_roads=0.1)
        )
        assert len(body["m"]) == 3
        assert abs(body["m"][1] - 7015) <= routing.calm.WINDOW_M / 2

    def test_a_failed_score_costs_only_the_score(self, monkeypatch):
        def boom(*_a, **_k):
            raise ValueError("boom")

        monkeypatch.setattr(calm, "score", boom)
        body = routing.route_profile(
            [self.leg([10.0] * 10)], [], calm_pricing=calm.Pricing(use_roads=0.1)
        )
        assert body is not None and body["calm"] is None and len(body["m"]) == 10

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
        # Mutation re-review SHOULD-FIX 3: corkers follow the tier, not the marker. A busy
        # road crossed with no marker needs them; a flagged junction on an LTS 2 road not.
        busy = m.Major(
            500.0,
            -77.0,
            38.9,
            frozenset({"georgia avenue"}),
            ("Georgia Avenue",),
            None,
            Control.CROSS_STOP,
            2,
            3,
            m.MAJOR_CROSSING,
        )
        quiet = m.Major(
            520.0,
            -77.0,
            38.9,
            frozenset({"a street"}),
            ("A Street",),
            "orange",
            Control.SIGNAL,
            2,
            2,
        )
        body = self.mass(heights, [(total, 6.7, None)], [major, busy, quiet])
        assert [(c["m"], c["kind"], c["corkers_needed"]) for c in body["crossings"][1:]] == [
            (500, "crossing", True),
            (520, "flagged", False),
        ]
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
                "oneway": None,
                "divided": False,
            }
        ]

    def test_a_mass_ride_sends_what_the_group_length_is_read_from(self):
        """PLAN items 128, 139: the level figure at each sample, the cruising pace and the
        fallback road's figure, so the front end reads the group's length at each point."""
        heights = [10.0] * 12
        total = (len(heights) - 1) * STEP
        body = self.mass(heights, [(total / 2, 6.7, None), (total, None, None)], [])
        level = body["level_riders_per_min"]
        assert len(level) == len(body["m"]) == len(body["riders_per_min"])
        assert level[0] == round(flow.level_riders_per_min(6.7))
        assert level[-1] is None
        assert body["flow"]["cruise_pace_ms"] == round(flow.CRUISE_PACE_MS, 4)
        assert body["flow"]["default_level_riders_per_min"] == round(
            flow.level_riders_per_min(2 * flow.LANE_WIDTH_M), 2
        )

    def test_off_a_mass_ride_there_is_no_level_figure(self):
        heights = [10.0] * 6
        body = routing.route_profile([self.leg(heights)], [])
        assert body["level_riders_per_min"] is None

    def test_the_typical_figure_is_the_median(self):
        # The samples on the grid: 99, 99, 99 | 198, 198 | 297, 297 (by width): median 198.
        # A pair at each boundary (75 m, 135 m), one each side, does not weigh in it.
        heights = [10.0] * 7
        stretches = [(75.0, 3.35, None), (60.0, 6.7, None), (100.0, 10.05, None)]
        body = self.mass(heights, stretches)
        assert body["m"] == [0, 30, 60, 75, 75, 90, 120, 135, 135, 150, 180]
        assert body["riders_per_min"] == [99, 99, 99, 99, 198, 198, 198, 198, 297, 297, 297]
        assert body["elevation_m"] == [10.0] * 11
        assert body["flow"]["typical_riders_per_min"] == 198
        assert body["flow"]["narrowest_riders_per_min"] == 99
        assert body["flow"]["narrowest_m"] == 0

    def test_the_typical_figure_leaves_out_the_boundary_pairs(self):
        """Mutation r4 SHOULD-FIX 2 (F11, F16): a pair at each boundary would move the
        median. The grid: 297 at 0 to 90 m and 99 at 120 to 180 m (4 of 7): median 297.
        The boundary into the 99 at 100 m and a 10 m stretch of 198 at 130 m add their
        pairs; counted, either whole or by their later halves, the median would be 198."""
        heights = [10.0] * 7
        stretches = [
            (100.0, 10.05, None),
            (30.0, 3.35, None),
            (10.0, 6.7, None),
            (100.0, 3.35, None),
        ]
        body = self.mass(heights, stretches)
        assert body["m"] == [0, 30, 60, 90, 100, 100, 120, 130, 130, 140, 140, 150, 180]
        assert body["riders_per_min"] == [297] * 5 + [99, 99, 99, 198, 198] + [99] * 3
        assert body["flow"]["typical_riders_per_min"] == 297

    def test_the_typical_figure_counts_a_leg_with_no_heights(self):
        """Mutation r4 SHOULD-FIX 2 (F21): the samples every 30 m along a leg with no
        heights are on the grid, so its riders weigh in the typical figure: about 66 of
        them at 99 beside ten at 297."""
        legs = [self.leg([10.0] * 5), self.leg([], 2000.0), self.leg([10.0] * 5)]
        stretches = [(120.0, 10.05, None), (2000.0, 3.35, None), (120.0, 10.05, None)]
        body = routing.route_profile(legs, [], stretches, [])
        assert body["flow"]["typical_riders_per_min"] == 99
        assert body["flow"]["narrowest_riders_per_min"] == 99

    def test_a_boundary_between_samples_is_drawn_on_the_line_between_them(self):
        """Mutation r4 SHOULD-FIX 3 (F17-F20): a riders pair between two samples takes the
        height on the line between them and the nearer sample's grade; one on a sample
        takes that sample's; none beside a gap or off the ends."""
        samples = along([10.0, 11.8, 13.6, None, 17.2])
        grade_at = [0.01, 0.02, 0.03, 0.04, 0.05]
        sample_m = [m for m, _h in samples]

        def at(x):
            return routing._height_between(samples, grade_at, sample_m, x)

        height, grade = at(40.0)
        assert height == pytest.approx(12.4) and grade == 0.02
        height, grade = at(50.0)
        assert height == pytest.approx(13.0) and grade == 0.03
        assert at(30.0) == (11.8, 0.02)
        assert at(60.0) == (13.6, 0.03)
        assert at(0.0) == (10.0, 0.01)
        assert at(70.0) == (None, None)
        assert at(100.0) == (None, None)
        assert at(130.0) == (None, None)
        assert at(-5.0) == (None, None)

    def test_a_boundary_on_a_slope_carries_the_interpolated_height(self):
        """The same, end to end: a 6% ramp, a width change at 40 m."""
        heights = ramp(0.06, 7)
        body = self.mass(heights, [(40.0, 6.7, None), (140.0, 10.05, None)])
        at = body["m"].index(40)
        assert body["m"][at : at + 2] == [40, 40]
        assert body["elevation_m"][at : at + 2] == [pytest.approx(12.4)] * 2
        assert body["riders_per_min"][at + 1] > body["riders_per_min"][at]

    def test_a_range_starting_past_the_profiles_end_is_dropped(self):
        """Mutation r4 NIT 5 (S04): the traced metres may run past the samples; a range
        starting there is not sent as one that ends before it starts."""
        stretches = [(100.0, 6.7, None), (50.0, None, routing.STRETCH_AVOID)]
        assert routing._stretch_ranges(stretches, routing.STRETCH_AVOID, 80.0) == []
        assert routing._stretch_ranges(stretches, routing.STRETCH_AVOID, 120.0) == [
            {"from_m": 100, "to_m": 120}
        ]
        assert routing._stretch_ranges(stretches, routing.STRETCH_AVOID, 100.0) == []

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
        assert body["m"][3:9] == [75, 75, 90, 120, 135, 135]
        assert body["riders_per_min"][3:9] == [198, None, None, None, None, 198]
        # The stretch's own ends, not its first and last samples (correctness re-review R1).
        assert body["avoid"] == [{"from_m": 75, "to_m": 135}]
        assert body["unchecked"] == []
        assert body["flow"]["narrowest_riders_per_min"] == 198

    def test_an_avoid_stretch_between_two_samples_keeps_its_range(self):
        """Correctness re-review R1: a 20 m Avoid from 105 m to 125 m lies between the
        samples at 90 m and 120 m; it gave `avoid` 120-120, and one shorter still none."""
        heights = [10.0] * 7
        stretches = [
            (105.0, 6.7, None),
            (20.0, None, routing.STRETCH_AVOID),
            (110.0, 6.7, None),
        ]
        body = self.mass(heights, stretches)
        assert body["avoid"] == [{"from_m": 105, "to_m": 125}]
        at = body["m"].index(105)
        assert body["m"][at : at + 5] == [105, 105, 120, 125, 125]
        assert body["riders_per_min"][at : at + 5] == [198, None, None, None, 198]

    def test_a_short_bottleneck_between_two_samples_is_the_narrowest_point(self):
        heights = [10.0] * 7
        stretches = [(100.0, 6.7, None), (15.0, 1.5, None), (120.0, 6.7, None)]
        body = self.mass(heights, stretches)
        assert body["flow"]["narrowest_riders_per_min"] == round(flow.level_riders_per_min(1.5))
        assert body["flow"]["narrowest_m"] == 100
        assert body["flow"]["typical_riders_per_min"] == 198

    @staticmethod
    def bottleneck_runs(body):
        """The bottlenecks table's runs as the front end reads them (profileChart.ts
        bottleneckRows): from the first to the last known riders figure under 60."""
        runs, start, last, low = [], None, None, None
        for at, r in zip(body["m"], body["riders_per_min"], strict=True):
            if r is not None and r < flow.BAND_EDGES[0]:
                start = at if start is None else start
                last, low = at, r if low is None else min(low, r)
            elif start is not None:
                runs.append((start, last, low))
                start, low = None, None
        if start is not None:
            runs.append((start, last, low))
        return runs

    @pytest.mark.parametrize("seed", range(8))
    def test_thinning_a_long_mass_ride_keeps_each_bottlenecks_ends(self, seed, monkeypatch):
        """Correctness r3 N1: on a 150 km Mass Ride the boundary pairs were thinned away,
        so a 45 m bottleneck read as 14 m and a 250 m one as 165 m. Each run under 60
        riders a minute now keeps its first and last sample, so the table's lengths and
        lowest figures are the unthinned ones."""
        import random

        rng = random.Random(seed)
        total = 150_000.0
        n = round(total / STEP) + 1
        heights = [10.0 + 20.0 * math.sin(i / 40.0) + (i % 7) for i in range(n)]
        stretches, at = [], 0.0
        while at < total:
            wide = min(rng.uniform(400.0, 3000.0), total - at)
            stretches.append((wide, 6.7, None))
            at += wide
            if at >= total:
                break
            short = min(rng.choice([15.0, 45.0, rng.uniform(20.0, 400.0)]), total - at)
            riders = rng.uniform(30.0, 58.0)
            stretches.append((short, riders / flow.level_riders_per_min(1.0), None))
            at += short
        thinned = routing.route_profile([self.leg(heights, total)], [], stretches, [])
        assert len(thinned["m"]) < n, "the route was thinned"
        assert len(thinned["m"]) <= profile.MAX_SAMPLES + profile.WINDOW_PICKS_MASS + 2
        monkeypatch.setattr(profile, "thin", lambda h, *_a, **_k: list(range(len(h))))
        full = routing.route_profile([self.leg(heights, total)], [], stretches, [])
        assert len(full["m"]) > n
        expected = self.bottleneck_runs(full)
        assert len(expected) > 30
        assert self.bottleneck_runs(thinned) == expected

    def test_the_bottleneck_ends_are_each_runs_first_and_last_sample(self):
        riders = [100.0, 59.0, 40.0, 59.4, 59.6, 30.0, None, 20.0, 100.0, 10.0]
        # 59.6 is sent as 60, which is not a bottleneck; a gap ends a run too.
        assert profile._bottleneck_ends(riders) == {1, 3, 5, 7, 9}
        assert profile._bottleneck_ends(None) == set()

    def test_a_leg_with_no_elevation_keeps_its_avoid_and_its_riders(self):
        """Correctness re-review R1: a 2 km leg with no heights holding a 200 m Avoid and a
        900 m stretch at 59 riders a minute gave `avoid: []` and a line drawn straight
        from 207 to 59 across it."""
        narrow = 59 / flow.level_riders_per_min(1.0)
        legs = [self.leg([10.0] * 5), self.leg([], 2000.0), self.leg([10.0] * 5)]
        stretches = [
            (420.0, 6.7, None),
            (200.0, None, routing.STRETCH_AVOID),
            (900.0, narrow, None),
            (720.0, 6.7, None),
        ]
        body = routing.route_profile(legs, [], stretches, [])
        assert body["avoid"] == [{"from_m": 420, "to_m": 620}]
        assert body["flow"]["narrowest_riders_per_min"] == 59
        assert body["flow"]["narrowest_m"] == 620
        by_m = dict(zip(body["m"], body["riders_per_min"], strict=True))
        # A riders sample every 30 m along the leg, with no height.
        inside = [x for x in body["m"] if 120 < x < 2120]
        assert len(inside) >= 2000 // 30
        assert by_m[1020] == 59 and by_m[510] is None and by_m[300] == 198
        at = body["m"].index(1020)
        assert body["elevation_m"][at] is None
        assert body["climbs"] == []

    def test_an_untraced_leg_is_unchecked(self):
        heights = [10.0] * 7
        stretches = [(75.0, 6.7, None), (200.0, None, routing.STRETCH_UNTRACED)]
        body = self.mass(heights, stretches, [])
        # From the stretch's start, clipped to the profile's end.
        assert body["unchecked"] == [{"from_m": 75, "to_m": 180}]
        assert body["avoid"] == []

    def test_a_partial_list_of_majors_is_sent_as_incomplete(self):
        """Correctness re-review R3: the flagged junctions standing in for the majors are
        not shown as the full set."""
        heights = [10.0] * 5
        stretch = [(200.0, 6.7, None)]
        leg = [self.leg(heights)]
        assert routing.route_profile(leg, [], stretch, [], True)["crossings_complete"] is True
        assert routing.route_profile(leg, [], stretch, [], False)["crossings_complete"] is False
        assert routing.route_profile(leg, [], stretch, None, False)["crossings_complete"] is None
        assert routing.route_profile(leg, [])["crossings_complete"] is None

    def test_the_stretches_may_be_made_inside_the_profiles_guard(self):
        """Operations re-review B: a failure making the stretches costs only the chart."""

        def broken():
            raise RuntimeError("boom")

        heights = [10.0] * 5
        assert routing.route_profile([self.leg(heights)], [], broken, []) is None
        made = routing.route_profile([self.leg(heights)], [], lambda: [(200.0, 6.7, None)], [])
        assert made["riders_per_min"] == [198] * 5

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
        # The two-way piece is its own side's 2 lanes (406), as the one-way one is: 6.7 m
        # each (the two-way one was 13.4 m, both directions, before the rebuild bundle).
        assert got == [
            (100.0, pytest.approx(6.7), None),
            (100.0, pytest.approx(6.7), None),
            (50.0, None, routing.STRETCH_AVOID),
            (25.0, None, None),
            (500.0, None, routing.STRETCH_UNTRACED),
        ]

    def test_a_stretch_outside_dc_has_no_width_and_its_own_note(self):
        """OWNER-DECISIONS 427: no riders-per-minute figure for the parts of a Mass Ride
        outside DC (Rosslyn here); a border road, within the tolerance, is inside (420)."""

        class P:
            def __init__(self, metres, lon, lat):
                self.metres, self.lon, self.lat = metres, lon, lat

        classes = [routing.PieceClass("2", "none", None, 2, False, 6.0)] * 3
        pieces = [
            P(100.0, -77.0365, 38.8977),
            P(100.0, -77.0720, 38.8960),
            P(50.0, -77.0365, 38.8977),
        ]
        got = routing._flow_stretches([(0, 3)], pieces, classes, capacity=True)
        assert got == [
            (100.0, 6.0, None),
            (100.0, None, routing.STRETCH_OUTSIDE_DC),
            (50.0, 6.0, None),
        ]
        assert routing._stretch_ranges(got, routing.STRETCH_OUTSIDE_DC, 250.0) == [
            {"from_m": 100, "to_m": 200}
        ]

    def test_the_district_s_edge_has_the_border_tolerance(self):
        from core import mass_tiles

        assert mass_tiles.inside_dc(-77.0365, 38.8977)  # the White House
        assert not mass_tiles.inside_dc(-77.0720, 38.8960)  # Rosslyn, Virginia
        # A point just outside the drawn edge: inside within the tolerance, outside without it.
        ring = mass_tiles._dc_polygons()[0][0]
        (ax, ay), (bx, by) = ring[0], ring[1]
        mx, my = (ax + bx) / 2, (ay + by) / 2
        inside_near = [
            (mx + dx, my + dy)
            for dx, dy in ((0.00012, 0), (-0.00012, 0), (0, 0.00012), (0, -0.00012))
            if not mass_tiles.inside_dc(mx + dx, my + dy, tolerance_m=0)
        ]
        assert inside_near, "one of the four nudges lies outside the edge"
        lon, lat = inside_near[0]
        assert mass_tiles.inside_dc(lon, lat)  # about 10 to 13 m out: a border road

    def test_with_the_capacity_column_the_width_is_the_segments_own(self):
        """The chart reads the width the capacity map colours by (`mass_usable_width_m`,
        OWNER-DECISIONS 404, 406), never the lanes' estimate, so the two always agree; Avoid
        still has none (325), and a piece on no segment has none."""

        class P:
            def __init__(self, metres):
                self.metres = metres

        classes = [
            routing.PieceClass("2", "none", None, 2, False, 2.44),
            routing.PieceClass("1", "path", None, None, None, 2.5),
            routing.PieceClass("5", "none", None, 3, False, 9.0),
            routing.PieceClass("3", "none", None, 2, False),
            ("unknown", "unknown"),
        ]
        pieces = [P(100.0), P(80.0), P(50.0), P(40.0), P(25.0)]
        got = routing._flow_stretches([(0, 5)], pieces, classes, capacity=True)
        assert got == [
            (100.0, 2.44, None),
            (80.0, 2.5, None),
            (50.0, None, routing.STRETCH_AVOID),
            (40.0, None, None),
            (25.0, None, None),
        ]
        # The figure is the map's: the section's flat riders a minute come from the same width.
        assert classes[0].rpm == round(flow.level_riders_per_min(2.44))
        without = routing._flow_stretches([(0, 1)], pieces[:1], classes[:1])
        assert without == [(100.0, pytest.approx(6.7), None)], "an older table: the estimate"


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

    def test_going_on_along_ones_own_road_as_it_gets_busier_is_not_joining(self):
        """The rider's own road going on is not "joined" where its tier rises (as
        `cost_of` judges it: review r2, SHOULD_FIX 1)."""
        on = junction(
            100.0,
            [],
            Control.NONE,
            incoming=road("Main Street", tier=2),
            outgoing=road("Main Street", tier=3),
            continues=True,
        )
        assert self.run(on) == []

    def test_a_flagged_junction_is_one_major_though_its_event_is_about_another_road(self):
        """A left onto B Street (LTS 3) across A Street (LTS 4): the planner's event is
        the left onto B, the busiest road there is A; one junction, one major."""
        left = junction(
            100.0,
            [road("A Street", tier=4)],
            Control.SIGNAL,
            movement=Movement.LEFT,
            outgoing=road("B Street", tier=3),
            continues=False,
        )
        events = m.assess_route([left], group=True)
        assert [e.road_display for e in events] == [("B Street",)]
        majors = self.run(left)
        assert [(x.kind, x.display) for x in majors] == [(m.MAJOR_FLAGGED, ("B Street",))]

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

    def test_an_unflagged_busy_crossing_before_a_flagged_one_keeps_route_order(self):
        """Mutation re-review J24: the C and I keys and the table follow this order."""
        avenue = road("Connecticut Avenue", tier=4)
        past = junction(
            100.0,
            [road("Albemarle Street", tier=3)],
            Control.CROSS_STOP,
            incoming=avenue,
            outgoing=avenue,
        )
        flagged = junction(500.0, [road("Mass Avenue", tier=4)])
        majors = self.run(flagged, past)
        assert [(x.m, x.kind) for x in majors] == [
            (100.0, m.MAJOR_CROSSING),
            (500.0, m.MAJOR_FLAGGED),
        ]

    def test_a_second_node_of_one_junction_crossing_another_busy_road_is_not_a_second_major(
        self,
    ):
        """Mutation re-review J18: one junction gives one major (its busiest road counted,
        the rest of that node's roads are not looked at)."""
        avenue = road("Main Avenue", tier=4)
        first = junction(
            100.0, [road("A Street", tier=3)], Control.CROSS_STOP, incoming=avenue, outgoing=avenue
        )
        second = junction(
            120.0,
            [road("A Street", tier=3), road("B Street", tier=3)],
            Control.CROSS_STOP,
            incoming=avenue,
            outgoing=avenue,
        )
        assert len(self.run(first, second)) == 1

    def test_straight_from_a_quiet_road_into_a_busy_one_under_a_new_name_is_joining(self):
        """Mutation re-review J11: only straight on from one busy road into the next is
        not joining."""
        into = junction(
            100.0,
            [],
            Control.NONE,
            incoming=road("Quiet Street", tier=2),
            outgoing=road("New Road", tier=3),
            continues=False,
        )
        majors = self.run(into)
        assert [(x.kind, x.crossed_tier, x.corkers_needed) for x in majors] == [
            (m.MAJOR_JOINING, 3, True)
        ]

    def test_a_flagged_junction_just_ahead_on_the_same_street_hides_a_busy_crossing(self):
        """Mutation r4 SHOULD-FIX 4 (K02, K06): the 45 m window looks ahead as well as
        behind, and no further. Riding along Connecticut Avenue, a busy crossing of Mass
        Avenue at 100 m and a flagged junction on Mass Avenue 30 m ahead are one major;
        with the flagged one a kilometre on, they are two."""
        avenue = road("Connecticut Avenue", tier=4)

        def crossing():
            return junction(
                100.0,
                [road("Mass Avenue", tier=3)],
                Control.CROSS_STOP,
                incoming=avenue,
                outgoing=avenue,
            )

        near = self.run(crossing(), junction(130.0, [road("Mass Avenue", tier=4)]))
        assert [(x.m, x.kind) for x in near] == [(130.0, m.MAJOR_FLAGGED)]
        far = self.run(crossing(), junction(1000.0, [road("Mass Avenue", tier=4)]))
        assert [(x.m, x.kind) for x in far] == [
            (100.0, m.MAJOR_CROSSING),
            (1000.0, m.MAJOR_FLAGGED),
        ]

    def test_the_45_m_window_includes_both_its_ends(self):
        """Mutation r4 NIT 10 (K02-K04, K06): a major exactly MERGE_WITHIN_M behind or
        ahead counts; one just past either end, or far ahead, does not."""
        busy = road("Mass Avenue", tier=4)
        here = junction(100.0, [busy])

        def major(at):
            return m.Major(
                at, -77.0, 38.9, busy.names, ("Mass Avenue",), "orange", Control.SIGNAL, None, 4
            )

        within = m.MERGE_WITHIN_M
        for at in (100.0 - within, 100.0 + within, 130.0, 70.0):
            assert m._counted([major(at)], [at], here, busy) is True, at
        for at in (100.0 - within - 0.5, 100.0 + within + 0.5, 1000.0):
            assert m._counted([major(at)], [at], here, busy) is False, at

    def test_results_are_in_route_order(self):
        majors = self.run(
            junction(900.0, [road("C Street", tier=3)]),
            junction(100.0, [road("A Street", tier=4)]),
            junction(500.0, [road("B Street", tier=4)]),
        )
        assert [x.m for x in majors] == [100.0, 500.0, 900.0]

    def test_a_major_carries_whether_its_road_is_one_way(self):
        """PLAN item 139: a one-way cross street has one approach to hold (1 corker)."""
        one_way = self.run(
            junction(100.0, [road("I Street", lanes=3, tier=3, oneway=True)], Control.CROSS_STOP)
        )
        two_way = self.run(
            junction(100.0, [road("K Street", lanes=2, tier=3, oneway=False)], Control.CROSS_STOP)
        )
        unknown = self.run(junction(100.0, [road("L Street", lanes=2, tier=3)], Control.CROSS_STOP))
        assert [x.oneway for x in one_way + two_way + unknown] == [True, False, None]

    @staticmethod
    def carriageways(tier):
        """A divided road's two carriageways: one-way roads of ways of their own, one name."""
        name = frozenset({"new york avenue northwest"})
        north = Road(tier, lanes=3, oneway=True, names=name, ways=frozenset({1}))
        south = Road(tier, lanes=3, oneway=True, names=name, ways=frozenset({2}))
        return north, south

    def test_a_divided_road_merged_with_its_refuge_is_divided_not_one_way(self):
        """Re-check BLOCKING 1: the refuge merge (`_one_road`) keeps oneway True for the
        junction costs, but the major says divided, so the chart counts 2 corkers."""
        north, south = self.carriageways(4)
        majors = self.run(junction(100.0, [north]), junction(111.0, [south]))
        assert len(majors) == 1
        assert majors[0].kind == m.MAJOR_FLAGGED
        assert majors[0].oneway is True and majors[0].divided is True

    def test_a_divided_road_found_by_name_on_the_junction_path_is_divided(self):
        """The busy-road path (no flagged event for it): the far carriageway, within
        MERGE_WITHIN_M by name, is hidden by the near one's major, which becomes divided."""
        north, south = self.carriageways(3)
        junctions = [
            junction(100.0, [north], Control.CROSS_STOP),
            junction(111.0, [south], Control.CROSS_STOP),
        ]
        majors = m.major_crossings(junctions, [])
        assert len(majors) == 1
        assert majors[0].kind == m.MAJOR_CROSSING
        assert majors[0].oneway is True and majors[0].divided is True

    def test_a_single_one_way_street_or_a_two_way_pair_is_not_divided(self):
        one = self.run(junction(100.0, [road("I Street", tier=3, oneway=True)], Control.CROSS_STOP))
        assert [x.divided for x in one] == [False]
        two_way = Road(4, lanes=2, oneway=False, names=frozenset({"k street"}))
        pair = self.run(junction(100.0, [two_way]), junction(111.0, [two_way]))
        assert [x.divided for x in pair] == [False]

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
        # Correctness re-review R3: marked incomplete, so the chart says so.
        assert got.complete is False
        assert core_junctions.with_majors(built, events).complete is False
        monkeypatch.undo()
        assert core_junctions.with_majors(built, events).complete is True

    def test_an_unnamed_major_does_not_hide_a_named_busy_road_beside_it(self):
        """Correctness re-review NIT: an unnamed flagged junction (a path crossing) within
        45 m hid any busy road beside it, whatever its name."""
        unnamed = m.Major(100.0, -77.0, 38.9, frozenset(), (), "orange", Control.SIGNAL, None, 3)
        named = m.Major(
            100.0,
            -77.0,
            38.9,
            frozenset({"wisconsin avenue"}),
            ("Wisconsin Avenue",),
            None,
            Control.SIGNAL,
            None,
            4,
        )
        beside = junction(130.0, [road("Wisconsin Avenue", tier=4)])
        busy = road("Wisconsin Avenue", tier=4)
        assert m._counted([unnamed], [100.0], beside, busy) is False
        assert m._counted([named], [100.0], beside, busy) is True
        # An unnamed busy road beside a major is still its other carriageway.
        assert m._counted([named], [100.0], beside, road("", tier=4)) is True
        # Past 45 m nothing is counted twice by name.
        far = junction(150.0, [busy])
        assert m._counted([named], [100.0], far, busy) is False
