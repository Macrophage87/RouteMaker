"""Uphill on a busy road counts worse than downhill (FOLLOWUP-GRADE-STRESS, OWNER-DECISIONS
409): the multiplicative uphill stress term, "Hill distance * traffic-relative distance"
(the owner, 2026-10-10), in the calm search's ranking."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
import test_refine

from core import presets, refine, routing
from routemaker import effort, grade_stress


def ramp(length_m: float, grade: float, start_m: float = 0.0, step: float = 30.0):
    """(metres along, elevation) every `step` metres up a steady grade."""
    return [
        (start_m + i * step, 100.0 + grade * i * step) for i in range(int(length_m // step) + 1)
    ]


class TestTheWindows:
    def test_a_climb_past_the_grade_counts_its_extra_effort(self):
        windows = grade_stress.uphill_windows(ramp(1200, 0.05))
        assert windows, "a 5% climb counts"
        for start, end, extra in windows:
            assert end - start >= effort.WINDOW_M
            assert extra == pytest.approx(effort.effort_factor(0.05) - 1.0)

    def test_below_the_grade_and_downhill_nothing_counts(self):
        assert grade_stress.uphill_windows(ramp(1200, 0.02)) == []
        assert grade_stress.uphill_windows(ramp(1200, -0.08)) == []
        assert grade_stress.uphill_windows([]) == []

    def test_the_grade_where_it_starts_is_a_parameter(self):
        assert grade_stress.uphill_windows(ramp(1200, 0.02), grade_from=0.01)
        assert grade_stress.GRADE_FROM == 0.03

    def test_a_heavier_rider_pays_more_for_the_same_climb(self):
        light = grade_stress.uphill_windows(ramp(900, 0.06), mass_kg=60.0)[0][2]
        heavy = grade_stress.uphill_windows(ramp(900, 0.06), mass_kg=150.0)[0][2]
        assert heavy > light


class TestByTier:
    def test_each_window_is_shared_by_its_overlap(self):
        windows = [(0.0, 300.0, 2.0), (300.0, 600.0, 4.0)]
        stretches = [(0.0, 150.0, "2"), (150.0, 450.0, "4"), (450.0, 900.0, "3")]
        got = grade_stress.uphill_by_tier(windows, stretches)
        assert got == pytest.approx({"2": 300.0, "4": 150 * 2.0 + 150 * 4.0, "3": 150 * 4.0})

    def test_a_climb_past_the_traced_stretches_is_not_counted(self):
        assert grade_stress.uphill_by_tier([(1000.0, 1300.0, 3.0)], [(0.0, 900.0, "4")]) == {}


class TestTheTerm:
    """Multiplicative: the climb's extra effort times the traffic weight."""

    def test_quiet_streets_cost_nothing_extra(self):
        weights = presets.EXPOSURE_STANDARD.weights
        assert grade_stress.uphill_stress_m({"1": 500.0, "2": 500.0}, weights) == 0.0

    def test_it_scales_with_the_climb_and_with_the_traffic(self):
        weights = presets.EXPOSURE_STANDARD.weights
        lts3 = grade_stress.uphill_stress_m({"3": 1000.0}, weights)
        lts4 = grade_stress.uphill_stress_m({"4": 1000.0}, weights)
        avoid = grade_stress.uphill_stress_m({"5": 1000.0}, weights)
        assert lts3 == pytest.approx(grade_stress.FACTOR * 1000.0)
        assert lts4 == pytest.approx(2 * lts3) and avoid == pytest.approx(3 * lts3)
        assert grade_stress.uphill_stress_m({"4": 2000.0}, weights) == pytest.approx(2 * lts4)

    def test_the_stress_averse_rides_weigh_it_by_their_own_weights(self):
        averse = presets.EXPOSURE_STRESS_AVERSE.weights
        assert grade_stress.uphill_stress_m({"4": 1000.0}, averse) == pytest.approx(
            8 * grade_stress.FACTOR * 1000.0
        )

    def test_the_documented_example(self):
        """0.62 mi (1 km) at 4%: about 0.43 mi (690 m) on LTS 3, 0.86 mi (1,380 m) on LTS 4."""
        extra = (effort.effort_factor(0.04) - 1.0) * 1000.0
        weights = presets.EXPOSURE_STANDARD.weights
        assert grade_stress.uphill_stress_m({"3": extra}, weights) == pytest.approx(690, abs=15)
        assert grade_stress.uphill_stress_m({"4": extra}, weights) == pytest.approx(1380, abs=30)


def _piece(metres):
    return SimpleNamespace(metres=metres)


def _trip(length_m: float, elevations: list[float]) -> dict:
    return {
        "legs": [{"summary": {"length": length_m / 1000.0}, "elevation": elevations}],
        "summary": {"length": length_m / 1000.0},
    }


class TestOnARoute:
    """The direction is the route's: the same street is a climb one way, free the other."""

    UP = [100.0 + 0.05 * 30 * i for i in range(41)]  # 1.2 km up at 5%

    def test_uphill_on_the_busy_stretch_counts(self):
        pieces = [_piece(600.0), _piece(600.0)]
        classes = [("1", "none"), ("4", "none")]
        got = refine.uphill_of(_trip(1200.0, self.UP), pieces, classes, effort.MASS_KG)
        assert got.get("4", 0.0) > 0 and got.get("1", 0.0) > 0
        assert got["4"] == pytest.approx(got["1"], rel=0.05)

    def test_the_same_street_downhill_counts_nothing(self):
        pieces = [_piece(600.0), _piece(600.0)]
        classes = [("4", "none"), ("1", "none")]
        down = list(reversed(self.UP))
        assert refine.uphill_of(_trip(1200.0, down), pieces, classes, effort.MASS_KG) == {}


def _read(cost_s=1000.0, uphill=None, lts4_m=0.0, lts3_m=0.0):
    return refine.Analysis(
        length_m=2000.0,
        cost_s=cost_s,
        exposure_m=0.0,
        climb_m=0.0,
        pieces=[],
        classes=[],
        events=None,
        lts4_m=lts4_m,
        lts3_m=lts3_m,
        uphill_m=uphill or {},
    )


def _ctx(weight=1.0, exposure=presets.EXPOSURE_STANDARD):
    return SimpleNamespace(
        rate=0.0,
        weight=1.0,
        climb_weight=0.0,
        quiet_cost=0.44,
        grade_stress_weight=weight,
        exposure=exposure,
        hills_weight=0.0,
        hills_seek_weight=0.0,
        # "Fine with hills" (FOLLOWUP-HILLS-TOLERATE, #73) off, where the score reads it.
        hills_tolerate_weight=0.0,
    )


class TestTheRanking:
    def test_the_score_adds_the_uphill_stress_in_quiet_metres(self):
        read = _read(uphill={"4": 1000.0})
        assert read.score(_ctx(0.0)) == pytest.approx(1000.0)
        assert read.score(_ctx(1.0)) == pytest.approx(
            1000.0 + 0.44 * grade_stress.FACTOR * 2 * 1000.0
        )
        assert read.score(_ctx(0.5)) == pytest.approx(
            1000.0 + 0.5 * 0.44 * grade_stress.FACTOR * 2 * 1000.0
        )

    def test_a_climb_on_a_busy_road_ranks_below_the_same_climb_on_a_quiet_one(self):
        busy, quiet = _read(uphill={"4": 1000.0}), _read(uphill={"1": 1000.0})
        assert busy.score(_ctx()) > quiet.score(_ctx()) == pytest.approx(1000.0)

    def test_at_the_top_the_climbing_joins_the_figure_it_is_ridden_on(self):
        read = _read(uphill={"4": 400.0, "3": 200.0, "1": 900.0}, lts4_m=100.0, lts3_m=50.0)
        top, second, _third = read.key(_ctx())
        assert top == pytest.approx(100.0 + grade_stress.FACTOR * 400.0)
        assert second == pytest.approx(50.0 + grade_stress.FACTOR * 200.0)
        assert read.top_m == 100.0 and read.second_m == 50.0, "the hold's figures unchanged"
        top0, second0, _ = read.key(_ctx(0.0))
        assert (top0, second0) == (100.0, 50.0)

    def test_the_weight_follows_the_stress_slider(self):
        assert refine.grade_stress_weight_for(0) == 0.0
        assert refine.grade_stress_weight_for(35) == pytest.approx(0.5)
        assert refine.grade_stress_weight_for(presets.STRESS_DEFAULT_AT) == 1.0
        assert refine.grade_stress_weight_for(100) == 1.0

    def test_a_long_plan_adds_its_legs_climbing(self):
        whole = refine.combine([_read(uphill={"4": 100.0}), _read(uphill={"4": 50.0, "3": 10.0})])
        assert whole.uphill_m == pytest.approx({"4": 150.0, "3": 10.0})


class TestTheCalmSearchRanksTheRoutersAlternatives:
    """OWNER-DECISIONS 435's ranking of the router's own alternatives, with 409 in it: of
    two routes alike in cost and stress, the one that climbs its busy stretch loses to the
    one that climbs on a quiet street; without the uphill stress the router's first stays."""

    BUSY = "1" * 10 + "3" * 20 + "1" * 10

    def plan(self, monkeypatch, weight: float) -> str:
        up_busy = dataclasses.replace(test_refine.analysis("o", self.BUSY), uphill_m={"3": 2000.0})
        up_quiet = dataclasses.replace(
            test_refine.analysis("a", self.BUSY, shift=200), uphill_m={"1": 2000.0}
        )
        test_refine.AlternatesWorld(
            monkeypatch,
            {"o": up_busy, "a": up_quiet},
            [routing.RouterRefused(400, 442, "")] * 2,
            [test_refine.trip_of("a", 4.0)],
        )
        ctx = test_refine.TestRouterAlternates().ctx()
        ctx.grade_stress_weight = weight
        kept, _info = refine.refine(test_refine.trip_of("o", 4.0), ctx)
        return kept["legs"][0]["shape"]

    def test_uphill_on_the_busy_road_loses(self, monkeypatch):
        assert self.plan(monkeypatch, 1.0) == "a"

    def test_without_it_the_routers_first_route_stays(self, monkeypatch):
        assert self.plan(monkeypatch, 0.0) == "o"


class TestTheWorthRuleCountsTheUphillStress:
    """OWNER-DECISIONS 409 and 435: the owner's "Count it" (2026-10-11), asked whether the
    uphill stress counts when deciding a longer route is worth its extra miles: "A longer
    route can win by avoiding a busy climb, so some plans get longer." The stress saving
    the worth rule weighs takes the uphill stress, at the rule's own weights; its ratios
    and its targets are unchanged."""

    # A climb of 2,000 extra effort-equivalent metres: on LTS 4 it counts
    # FACTOR x 2 (the LTS 4 weight) x 2,000 = 1,000 m of LTS 3 in the worth rule.
    CLIMB = 2000.0

    def ctx(self, top: bool, weight: float = 1.0) -> refine.Context:
        if top:
            ctx = test_refine.context(rate=10.0, maxcalm=True)
        else:
            ctx = test_refine.context(rate=presets.calm_rate_for(90))
        ctx.grade_stress_weight = weight
        return ctx

    def pair(self, climbed: dict, added_m: float = 1000.0, lts2_weight: float = 0.0):
        """The router's route, 4 km (2.5 mi) up a climb ridden on `climbed`'s tiers, and a
        longer one round it on quiet streets, `added_m` longer and as cheap to the router."""
        short = dataclasses.replace(
            test_refine.analysis("s", "1" * 40), uphill_m=climbed, lts2_weight=lts2_weight
        )
        long = dataclasses.replace(
            test_refine.analysis("l", "1" * 40),
            length_m=short.length_m + added_m,
            uphill_m={"1": self.CLIMB},
            lts2_weight=lts2_weight,
        )
        return short, long

    def test_the_saving_is_in_the_rules_units(self):
        short, long = self.pair({"4": self.CLIMB})
        ctx = self.ctx(top=False)
        assert refine.stress_saved_m(short, long, ctx) == pytest.approx(
            grade_stress.FACTOR * refine.WORTH_WEIGHTS.lts4 * self.CLIMB
        )
        avoid, _ = self.pair({"5": self.CLIMB})
        lts3, _ = self.pair({"3": self.CLIMB})
        assert refine.stress_saved_m(avoid, long, ctx) == pytest.approx(1500.0)
        assert refine.stress_saved_m(lts3, long, ctx) == pytest.approx(500.0)

    @pytest.mark.parametrize("top", [False, True])
    def test_a_longer_route_round_a_busy_climb_is_worth_its_miles(self, top):
        # 1 km more for 1,000 m of LTS 3 saved: within 1.7 to 1 at 90 and 5 to 1 at the top.
        # Before the owner's "Count it" the saving was nothing and the router's route stayed.
        short, long = self.pair({"4": self.CLIMB})
        assert refine.worth_it(short, long, self.ctx(top))
        assert refine.better(long, short, self.ctx(top))

    @pytest.mark.parametrize("top", [False, True])
    def test_the_rules_ratio_still_bounds_the_miles(self, top):
        # 10 km (6.2 mi) more for the same climb is past either ratio.
        short, long = self.pair({"4": self.CLIMB}, added_m=10_000.0)
        assert not refine.worth_it(short, long, self.ctx(top))
        assert not refine.better(long, short, self.ctx(top))

    @pytest.mark.parametrize("top", [False, True])
    def test_round_a_quiet_climb_gains_nothing(self, top):
        # LTS 1 has no traffic weight, nor LTS 2 on a ride that does not weigh it.
        for climbed in ({"1": self.CLIMB}, {"2": self.CLIMB}):
            short, long = self.pair(climbed)
            assert refine.stress_saved_m(short, long, self.ctx(top)) == 0.0
            assert not refine.worth_it(short, long, self.ctx(top))
            assert not refine.better(long, short, self.ctx(top))

    def test_lts2_climbing_counts_where_the_ride_weighs_it(self):
        short, long = self.pair({"2": self.CLIMB}, lts2_weight=presets.LTS2_WEIGHT)
        assert refine.stress_saved_m(short, long, self.ctx(top=False)) == pytest.approx(
            grade_stress.FACTOR * presets.LTS2_WEIGHT * self.CLIMB
        )

    def test_without_the_sliders_weight_it_counts_nothing(self):
        # The traffic tolerant end (`grade_stress_weight_for`), as in the score.
        short, long = self.pair({"4": self.CLIMB})
        assert refine.stress_saved_m(short, long, self.ctx(top=True, weight=0.0)) == 0.0
        assert not refine.worth_it(short, long, self.ctx(top=True, weight=0.0))

    def test_a_long_plan_spends_its_detour_round_a_busy_climb(self):
        # `choose_options` weighs an upgrade with the same saving (a long plan's legs).
        short, long = self.pair({"4": self.CLIMB})
        ctx = self.ctx(top=True)
        chain = [(None, short), (None, long)]
        assert refine.choose_options([chain], [short.length_m], None, ctx) == [1]

    def test_a_busy_climb_avoided_is_a_top_level_saving(self):
        # The climb on LTS 4 is in the top figure of `Analysis.key`, so avoiding it pays on
        # its own and the LTS 3 the longer route adds does not net against it (SF2, 287(1)).
        short, long = self.pair({"4": self.CLIMB})
        long = dataclasses.replace(long, lts3_m=900.0)
        ctx = self.ctx(top=True)
        assert refine.stress_saved_m(short, long, ctx) == pytest.approx(1000.0)
        assert refine.better(long, short, ctx)
