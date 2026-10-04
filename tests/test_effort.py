"""Effort-equivalent distance (`routemaker.effort`, OWNER-DECISIONS 262-264)."""

from __future__ import annotations

import math

import pytest

from routemaker import effort

FT = 3.28084


def profile(grade: float, length_m: float = 3000.0, step: float = 30.0):
    """A straight climb (or descent) at this grade, sampled every 30 m as the router does."""
    n = int(length_m / step)
    return [(i * step, 100.0 + grade * i * step) for i in range(n + 1)]


class TestTheModel:
    def test_the_constants_are_the_owners_and_named(self) -> None:
        assert effort.MASS_KG == 90.0
        assert (effort.MASS_MIN_KG, effort.MASS_MAX_KG) == (25, 700)
        assert 0.003 <= effort.CRR <= 0.012 and 0.25 <= effort.CDA <= 0.6
        assert effort.SPEED_MS == pytest.approx(20 / 3.6)

    def test_the_flat_force_is_rolling_plus_drag(self) -> None:
        rolling = effort.CRR * 90.0 * effort.GRAVITY
        drag = 0.5 * effort.AIR_DENSITY * effort.CDA * effort.SPEED_MS**2
        assert effort.flat_force_n() == pytest.approx(rolling + drag)
        assert 10.0 < effort.flat_force_n() < 16.0

    def test_a_climb_adds_the_weight_component(self) -> None:
        grade = 0.08
        extra = effort.force_n(grade) - effort.flat_force_n()
        assert extra == pytest.approx(90.0 * effort.GRAVITY * math.sin(math.atan(grade)), rel=0.01)

    def test_the_flat_is_worth_its_length(self) -> None:
        assert effort.effort_factor(0.0) == 1.0
        assert effort.effort_equivalent_m(profile(0.0), 3000.0) == pytest.approx(3000.0)

    def test_an_8_percent_climb_is_worth_about_six_and_a_half_times_the_flat(self) -> None:
        assert 6.0 < effort.effort_factor(0.08) < 7.0

    def test_a_steeper_climb_is_worth_more(self) -> None:
        factors = [effort.effort_factor(g) for g in (0.0, 0.02, 0.04, 0.08, 0.12)]
        assert factors == sorted(factors) and len(set(factors)) == 5

    def test_a_500_ft_climb_at_8_percent_counts_more_than_the_same_distance_flat(self) -> None:
        length = 500 / FT / 0.08  # the run that climbs 500 ft at 8%
        climb = effort.effort_equivalent_m(profile(0.08, length), length)
        flat = effort.effort_equivalent_m(profile(0.0, length), length)
        assert climb > 5 * flat > 0
        assert flat == pytest.approx(length, rel=0.02)


class TestADescentIsFlooredAtTheFlat:
    def test_a_descent_costs_no_less_than_the_flat(self) -> None:
        for grade in (-0.02, -0.06, -0.12):
            assert effort.effort_factor(grade) == 1.0
        down = effort.effort_equivalent_m(profile(-0.08), 3000.0)
        assert down == pytest.approx(3000.0)

    def test_it_never_offsets_a_climb(self) -> None:
        up = profile(0.08, 1500.0)
        top = up[-1][1]
        down = [(1500.0 + i * 30.0, top - 0.08 * i * 30.0) for i in range(1, 51)]
        both = effort.effort_equivalent_m(up + down, 3000.0)
        climb_only = effort.effort_equivalent_m(up, 1500.0)
        assert both >= climb_only + 1500.0 * 0.99
        flat = effort.effort_equivalent_m(profile(0.0, 3000.0), 3000.0)
        assert both > flat


class TestTheProfile:
    def test_a_noisy_profile_is_read_over_a_window(self) -> None:
        """A 2 m error between neighbouring samples is a 7% grade; over the window the worst
        case is a 0.7% one, not the 7%."""
        noisy = [(i * 30.0, 100.0 + (2.0 if i % 2 else 0.0)) for i in range(101)]
        assert effort.effort_equivalent_m(noisy, 3000.0) < 3000.0 * 1.6
        sample_by_sample = sum(30.0 * effort.effort_factor(2.0 / 30.0) for _ in range(50))
        assert effort.effort_equivalent_m(noisy, 3000.0) < sample_by_sample

    def test_a_gap_between_legs_ends_the_run(self) -> None:
        a = [(0.0, 100.0), (150.0, 100.0), (180.0, None), (180.0, 500.0), (330.0, 500.0)]
        # No climb across the gap: 400 m of rise between legs is not ridden.
        assert effort.effort_equivalent_m(a, 330.0) == pytest.approx(330.0)

    def test_no_profile_is_none(self) -> None:
        assert effort.effort_equivalent_m([], 1000.0) is None
        assert effort.effort_equivalent_m([(0.0, None)], 1000.0) is None

    def test_what_the_profile_does_not_cover_counts_as_flat(self) -> None:
        assert effort.effort_equivalent_m(profile(0.0, 300.0), 1000.0) == pytest.approx(1000.0)


class TestTheSystemWeight:
    """OWNER-DECISIONS 264: a heavier system pays more for a climb; the flat hardly."""

    def test_a_flat_route_is_worth_its_length_at_any_weight(self) -> None:
        for mass in (68.0, 90.0, 140.0):
            assert effort.effort_equivalent_m(profile(0.0), 3000.0, mass) == pytest.approx(3000.0)

    def test_a_hill_costs_more_effort_distance_when_heavier(self) -> None:
        light = effort.effort_equivalent_m(profile(0.06), 3000.0, 68.0)
        middle = effort.effort_equivalent_m(profile(0.06), 3000.0, 90.0)
        heavy = effort.effort_equivalent_m(profile(0.06), 3000.0, 140.0)
        assert light < middle < heavy

    def test_a_gentle_roll_hardly_depends_on_it(self) -> None:
        light = effort.effort_equivalent_m(profile(0.005), 3000.0, 68.0)
        heavy = effort.effort_equivalent_m(profile(0.005), 3000.0, 140.0)
        assert abs(heavy - light) / 3000.0 < 0.15

    def test_the_hilly_against_flat_gap_widens_with_the_weight(self) -> None:
        def gap(mass):
            hilly = effort.effort_equivalent_m(profile(0.05, 2000.0), 2000.0, mass)
            flat = effort.effort_equivalent_m(profile(0.0, 3000.0), 3000.0, mass)
            return hilly - flat

        assert gap(140.0) > gap(68.0)

    def test_the_default_is_90_and_passengers_default_heavier_inside_the_range(self) -> None:
        assert effort.MASS_KG == 90.0
        assert effort.MASS_MAX_KG > effort.PASSENGERS_MASS_KG > effort.MASS_KG > effort.MASS_MIN_KG


class TestTheWholeRange:
    """OWNER-DECISIONS 337, 338 and 352: the model is sensible from 25 to 700 kg (a 90 lb
    rider on a 16 lb bike is about 48 kg; a pedicab with two passengers is up to 700), and a
    weight outside is planned at the nearer limit."""

    @pytest.mark.parametrize("mass", [25.0, 48.0, 90.0, 450.0, 700.0])
    def test_the_flat_is_worth_its_length_and_the_forces_are_finite(self, mass) -> None:
        assert effort.flat_force_n(mass) > 0
        assert effort.effort_equivalent_m(profile(0.0), 3000.0, mass) == pytest.approx(3000.0)
        assert effort.effort_factor(-0.08, mass) == 1.0

    @pytest.mark.parametrize("mass", [25.0, 48.0, 90.0, 450.0, 700.0])
    def test_a_climb_costs_a_sensible_multiple_of_the_flat(self, mass) -> None:
        """An 8% climb is worth 2 to 15 flat metres a metre across the range: the drag,
        which does not scale with the mass, keeps a light system above 2 and a heavy one
        below 15 (no division problem at either end)."""
        factor = effort.effort_factor(0.08, mass)
        assert 2.0 < factor < 15.0

    def test_heavier_still_pays_more_for_a_climb(self) -> None:
        factors = [effort.effort_factor(0.06, m) for m in (25.0, 48.0, 90.0, 450.0, 700.0)]
        assert factors == sorted(factors) and len(set(factors)) == 5

    def test_the_heavy_end_saturates_without_a_jump(self) -> None:
        """352: up to 700 kg the factor keeps rising but flattens towards 1 + grade / CRR,
        so the heaviest setting is a heavier version of the next, not a different model:
        from 450 to 700 kg an 8% climb's factor rises by about 8%."""
        ceiling = 1 + 0.08 / effort.CRR
        f450, f700 = effort.effort_factor(0.08, 450.0), effort.effort_factor(0.08, 700.0)
        assert f450 < f700 < ceiling
        assert f700 / f450 == pytest.approx(1.08, abs=0.02)
        assert effort.effort_factor(0.08, 90.0) == pytest.approx(6.5, abs=0.1)

    @pytest.mark.parametrize(
        ("sent", "used"),
        [
            (10, 25.0),
            (25, 25.0),
            (48, 48.0),
            (90, 90.0),
            (450, 450.0),
            (500, 500.0),
            (700, 700.0),
            (800, 700.0),
        ],
    )
    def test_outside_the_range_the_nearer_limit(self, sent, used) -> None:
        assert effort.clamp_mass_kg(sent) == used

    def test_the_plans_weight_is_held_to_the_range(self) -> None:
        from core import presets

        assert presets.system_weight_for("trailmaxxing", None, 10) == 25.0
        assert presets.system_weight_for("trailmaxxing", None, 800) == 700.0
        assert presets.system_weight_for("trailmaxxing", None, 500) == 500.0
        assert presets.system_weight_for("trailmaxxing", None, 48) == 48.0
