"""The traffic-stress slider's rescale (OWNER-DECISIONS items 163 and 164).

"I'd actually like to see the slider for traffic stress to have a lot more
available penalty for higher LTS roads. There are times that I want to go for a
ride and I'm willing to add 10 or 20 miles to my trip just so it's more
relaxing." And: "The 10-20 miles is just an example, but the upper end could be
much greater than straight line distance, just warn people."

The old slider ran `use_roads` from 1.0 at 0 to 0.0 at 100, and the router's
price saturates there, so the last ten points changed almost nothing. The
rescale keeps every old position's route and makes room above it.
"""

from __future__ import annotations

import pytest

from core import presets


def old_use_roads(position: int) -> float:
    """The slider before the rescale: use_roads = 1 - stress / 100."""
    return round(1.0 - position / 100, 3)


class TestRescale:
    def test_the_old_default_sits_lower_and_plans_the_same_route(self) -> None:
        """Default was 90 (the owner's "90", 2026-09-27) and still is the same
        route: it is 70 now."""
        assert presets.DEFAULT_STRESS == presets.STRESS_DEFAULT_AT == 70
        assert presets.use_roads_for(presets.DEFAULT_STRESS) == old_use_roads(90) == 0.1

    def test_the_old_top_of_the_slider_sits_at_80(self) -> None:
        assert presets.STRESS_TODAYS_TOP == 80
        assert presets.use_roads_for(80) == old_use_roads(100) == 0.0

    def test_the_old_direct_end_is_unchanged(self) -> None:
        assert presets.use_roads_for(0) == 1.0

    @pytest.mark.parametrize("old", range(0, 101, 5))
    def test_every_old_position_has_a_new_one_with_its_route(self, old: int) -> None:
        """No route the old slider could plan is lost: some new position gives
        the same `use_roads` to within a rounding step."""
        wanted = old_use_roads(old)
        best = min(
            (abs(presets.use_roads_for(new) - wanted) for new in range(0, 81)),
        )
        assert best <= 0.007

    def test_use_roads_never_rises_with_stress(self) -> None:
        values = [presets.use_roads_for(s) for s in range(0, 101)]
        assert values == sorted(values, reverse=True)

    def test_use_roads_stays_at_zero_above_the_old_top(self) -> None:
        assert {presets.use_roads_for(s) for s in range(80, 101)} == {0.0}

    def test_the_slider_still_runs_zero_to_a_hundred(self) -> None:
        assert (presets.STRESS_MIN, presets.STRESS_MAX) == (0, 100)

    def test_presets_keep_their_routes(self) -> None:
        """Each ride type starts where it planned before: same `use_roads`
        (Group Ride, Gravel, Mountain Goat from 50 to 40 and Fast from 10 are
        within two points of theirs)."""
        was = {
            "default": 0.1,
            "trailmaxxing": 0.0,
            "ebike": 0.1,
            "mass-ride": 1.0,
        }
        for name, use_roads in was.items():
            assert presets.PRESETS[name].costing_options["use_roads"] == use_roads, name
        for name, old in {"group-ride": 50, "gravel": 50, "mountain-goat": 50, "fast": 10}.items():
            new = presets.PRESETS[name].costing_options["use_roads"]
            assert abs(new - old_use_roads(old)) < 0.07, name

    def test_cargo_keeps_its_two_starts(self) -> None:
        assert presets.CARGO_CARRYING_STRESS == {"cargo": presets.DEFAULT_STRESS, "people": 80}
        assert presets.use_roads_for(presets.CARGO_CARRYING_STRESS["people"]) == 0.0


class TestCalmRate:
    def test_nothing_up_to_the_old_top(self) -> None:
        assert {presets.calm_rate_for(s) for s in range(0, 81)} == {0.0}

    def test_it_rises_and_never_falls(self) -> None:
        rates = [presets.calm_rate_for(s) for s in range(80, 101)]
        assert rates == sorted(rates)
        assert rates[0] == 0.0 < rates[1]

    def test_it_ends_at_the_named_maximum(self) -> None:
        assert presets.calm_rate_for(100) == presets.CALM_RATE_MAX == 10.0
        assert presets.calm_rate_for(150) == presets.CALM_RATE_MAX

    def test_it_is_exponential_not_linear(self) -> None:
        """ "a steep (exponential) curve above Default" (item 163): each step up
        multiplies the rate, and the steps get longer."""
        rates = [presets.calm_rate_for(s) for s in (85, 90, 95, 100)]
        steps = [b - a for a, b in zip(rates, rates[1:], strict=False)]
        assert steps == sorted(steps)
        assert rates[1] / rates[0] > 2
        # Linear would put 90 at a half of the way: it is under a fifth.
        assert presets.calm_rate_for(90) < presets.CALM_RATE_MAX * 0.2

    def test_the_top_accepts_the_owners_ten_to_twenty_miles(self) -> None:
        """A 2 mi stretch of LTS 3 avoided at the top is worth a 20 mi detour."""
        assert 2 * presets.calm_rate_for(100) >= 10
        assert presets.calm_rate_for(100) * 3 >= 20

    def test_the_rate_is_in_the_costing_not_the_graph(self) -> None:
        """The slider reaches the router through `use_roads` only; the rate is
        the search's (`core.refine`), so one graph still serves every position."""
        options = presets.costing("default", stress=100)["bicycle"]
        assert options["use_roads"] == 0.0
        assert not any("calm" in key for key in options)


class TestTurnAndHillCostsStayActive:
    """The literature review: "keep turn and intersection costs active at every
    slider position" and "keep hill aversion strong at the relaxed end"."""

    @pytest.mark.parametrize("stress", [0, 40, 70, 80, 90, 100])
    def test_maneuver_and_hill_options_do_not_depend_on_the_stress(self, stress) -> None:
        base = presets.costing("default", stress=70)["bicycle"]
        moved = presets.costing("default", stress=stress)["bicycle"]
        for key in ("maneuver_penalty", "use_hills", "gate_cost", "gate_penalty", "bicycle_type"):
            assert moved[key] == base[key], key


class TestFrontEndAgrees:
    """The slider's positions are repeated in frontend/src/lib/dials.ts (so the
    sliders can sit at them before any route has come back); the two are held
    equal here, as `STARTS` is in tests/test_presets.py."""

    def constants(self) -> dict[str, float]:
        import re
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "dials.ts"
        ).read_text()
        found = {}
        for name in ("STRESS_DEFAULT_AT", "STRESS_TODAYS_TOP", "CALM_RATE_MAX", "CALM_CURVE"):
            match = re.search(rf"export const {name} = ([0-9.]+);", text)
            assert match, name
            found[name] = float(match.group(1))
        return found

    def test_the_constants_are_the_apis(self) -> None:
        found = self.constants()
        assert found["STRESS_DEFAULT_AT"] == presets.STRESS_DEFAULT_AT
        assert found["STRESS_TODAYS_TOP"] == presets.STRESS_TODAYS_TOP
        assert found["CALM_RATE_MAX"] == presets.CALM_RATE_MAX
        assert found["CALM_CURVE"] == presets.CALM_CURVE

    def test_the_rate_curve_is_the_apis(self) -> None:
        """The front end's `calmRate` at the positions its own test pins."""
        assert [presets.calm_rate_for(s) for s in (85, 90, 95, 100)] == [0.585, 1.824, 4.447, 10.0]
