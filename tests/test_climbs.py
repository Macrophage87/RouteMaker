"""Sustained climbs and descents (routemaker.climbs).

The owner, 2026-09-28: "In many cases it's not just stepness but steepness and
length. 10% can be done for 100m of riding, people would just sprint before it.
If continued over kilometers, that becomes a hike-a-bike", and "I'd say a
descent over about 2-3% might actually want to be penalized. There's a point
where it's a fun downhill and a point where you're riding the breaks."
"""

from __future__ import annotations

import pytest

from routemaker import climbs
from routemaker.climbs import Run, climb_cost_s, descent_cost_s, grade_cost_s, runs


def ramp(
    length_m: float, grade: float, start_m: float = 0.0, start_e: float = 0.0, step: float = 30.0
):
    """A straight grade, sampled every `step` metres like a route's profile."""
    points = []
    d = 0.0
    while d < length_m:
        points.append((start_m + d, start_e + grade * d))
        d += step
    points.append((start_m + length_m, start_e + grade * length_m))
    return points


def join(*parts):
    out = list(parts[0])
    for part in parts[1:]:
        offset_d, offset_e = out[-1]
        base_d, base_e = part[0]
        out.extend((offset_d + d - base_d, offset_e + e - base_e) for d, e in part[1:])
    return out


class TestFindingRuns:
    def test_a_steady_climb_is_one_run(self) -> None:
        (run,) = runs(ramp(1000, 0.08))
        assert run.rise_m == pytest.approx(80)
        assert run.length_m == pytest.approx(1000)
        assert run.grade == pytest.approx(0.08)

    def test_the_same_road_the_other_way_is_a_descent(self) -> None:
        up = ramp(1000, 0.08)
        down = [(1000 - d, e) for d, e in reversed(up)]
        (run,) = runs(down)
        assert run.rise_m == pytest.approx(-80)

    def test_a_brief_dip_does_not_end_a_climb(self) -> None:
        profile = join(ramp(500, 0.06), ramp(60, -0.04), ramp(500, 0.06))
        (run,) = [r for r in runs(profile) if r.rise_m > 0]
        assert run.length_m == pytest.approx(1060)

    def test_a_real_descent_does_end_it(self) -> None:
        profile = join(ramp(500, 0.06), ramp(300, -0.05), ramp(500, 0.06))
        assert len([r for r in runs(profile) if r.rise_m > 0]) == 2

    def test_a_long_flat_ends_it(self) -> None:
        profile = join(ramp(500, 0.06), ramp(300, 0.0), ramp(500, 0.06))
        assert len([r for r in runs(profile) if r.rise_m > 0]) == 2

    def test_a_short_flat_does_not(self) -> None:
        profile = join(ramp(500, 0.06), ramp(90, 0.0), ramp(500, 0.06))
        assert len([r for r in runs(profile) if r.rise_m > 0]) == 1

    def test_noise_is_not_a_hill(self) -> None:
        profile = [(i * 30.0, 10.0 + (1.0 if i % 2 else 0.0)) for i in range(40)]
        assert runs(profile) == []

    def test_a_gap_in_the_elevation_splits_the_profile(self) -> None:
        profile = ramp(300, 0.05) + [(310.0, None)] + ramp(300, 0.05, start_m=320.0)
        assert len(runs(profile)) == 2


class TestWhatAClimbCosts:
    def test_a_short_kick_is_free_whatever_its_grade(self) -> None:
        assert climb_cost_s(Run(0, climbs.KICK_M, 15.0)) == 0.0

    def test_a_gentle_climb_is_free(self) -> None:
        assert climb_cost_s(Run(0, 2000, 2000 * climbs.CLIMB_FREE_GRADE)) == 0.0

    def test_a_kilometre_at_eight_percent_costs_about_walking_it(self) -> None:
        assert 300 < climb_cost_s(Run(0, 1000, 80)) < 420

    def test_steeper_costs_more_than_proportionally_per_metre_climbed(self) -> None:
        """A 10% pitch costs clearly more than twice a 5% pitch per metre of
        climb, over the same length."""
        five, ten = climb_cost_s(Run(0, 800, 40)), climb_cost_s(Run(0, 800, 80))
        assert ten / 80 > 3 * (five / 40)

    def test_longer_costs_more_than_proportionally(self) -> None:
        one, two = climb_cost_s(Run(0, 1000, 80)), climb_cost_s(Run(0, 2000, 160))
        assert two > 2 * one

    def test_a_descent_is_not_a_climb(self) -> None:
        assert climb_cost_s(Run(0, 1000, -80)) == 0.0


class TestWhatADescentCosts:
    def test_free_up_to_the_ride_types_brake_grade(self) -> None:
        assert descent_cost_s(Run(0, 1000, -50), brake_grade=0.05) == 0.0

    def test_charged_past_it(self) -> None:
        assert descent_cost_s(Run(0, 1000, -80), brake_grade=0.05) > 0

    def test_rising_faster_than_the_excess_grade(self) -> None:
        a = descent_cost_s(Run(0, 1000, -70), brake_grade=0.05)
        b = descent_cost_s(Run(0, 1000, -90), brake_grade=0.05)
        assert b > 2 * a

    def test_a_ride_type_with_no_brake_grade_never_pays(self) -> None:
        assert descent_cost_s(Run(0, 3000, -300), brake_grade=None) == 0.0

    def test_a_short_steep_drop_is_free(self) -> None:
        assert descent_cost_s(Run(0, climbs.KICK_M, -15), brake_grade=0.03) == 0.0

    def test_a_climb_is_not_a_descent(self) -> None:
        assert descent_cost_s(Run(0, 1000, 80), brake_grade=0.0) == 0.0


def test_a_profiles_cost_is_its_runs_both_ways() -> None:
    profile = join(ramp(1000, 0.08), ramp(200, 0.0), ramp(1000, -0.08))
    both = grade_cost_s(profile, brake_grade=0.03)
    assert both == pytest.approx(
        sum(climb_cost_s(r) if r.rise_m > 0 else descent_cost_s(r, 0.03) for r in runs(profile))
    )
    assert both > grade_cost_s(profile, brake_grade=None) > 0
