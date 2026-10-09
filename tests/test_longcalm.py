"""FOLLOWUP-LONG-CALM (OWNER-DECISIONS 256-271): the top of the traffic slider
minimises stress towards the rider's target distance, and plans a long trip leg by leg.

The ordering (`refine.better`), the diminishing returns on extra distance (268,
`refine.worth_it`), the ceiling (`refine.too_long`, the search's handling of a route
past it), the target distance (271), the hold on the top figure, the leg splitting
(`core.legsplit`) and the long search (`refine.refine_long`), with the router and
the readings of its routes replaced as in test_refine.
"""

from __future__ import annotations

import dataclasses

import pytest
from test_refine import (
    BASE,
    World,
    analysis,
    context,
    event,
    trip_of,
)

from core import legsplit, presets, refine, routing, trailseek
from routemaker import intersections as model

FT = model.FEET_PER_METRE
AVERSE = presets.EXPOSURE_STRESS_AVERSE


def top_context(**kw) -> refine.Context:
    """The top of the slider: rate 10, ranked by `better`."""
    ctx = context(rate=10.0, maxcalm=True, **kw)
    return ctx


def with_(read: refine.Analysis, **fields) -> refine.Analysis:
    return dataclasses.replace(read, **fields)


def reading(lts4=0.0, lts3=0.0, red=(), orange=(), effort=None, length=10_000.0) -> refine.Analysis:
    """A reading with these figures: metres of LTS 4 and of LTS 3, the cost in feet
    of each red and orange junction, the effort-equivalent distance (the length where
    none is given: a flat route) and the length."""
    events = [event(1000.0 + 10 * i, cost) for i, cost in enumerate([*red, *orange])]
    return with_(
        analysis("r", events=events),
        lts4_m=lts4,
        lts3_m=lts3,
        effort_m=length if effort is None else effort,
        length_m=length,
    )


class TestTheFigures:
    def test_red_and_orange_junctions_are_told_apart_by_their_cost(self) -> None:
        # Red is from 2,900 ft since 468 (it was 2,000): 2,100 became 3,000.
        a = reading(red=[3000.0, 3000.0], orange=[1000.0, 1500.0])
        assert a.red_m == pytest.approx(6000.0 / FT)
        assert a.orange_m == pytest.approx(2500.0 / FT)

    def test_the_top_figure_is_lts4_and_avoid_plus_the_red_cost(self) -> None:
        a = reading(lts4=200.0, red=[3000.0])
        assert a.top_m == pytest.approx(200.0 + 3000.0 / FT)

    def test_the_second_figure_is_lts3_plus_the_orange_cost(self) -> None:
        a = reading(lts3=400.0, orange=[1000.0], red=[3000.0])
        assert a.second_m == pytest.approx(400.0 + 1000.0 / FT)

    def test_no_events_cost_nothing(self) -> None:
        a = with_(analysis("r", events=None), lts4_m=50.0)
        assert a.red_m == a.orange_m == 0.0 and a.top_m == 50.0

    def test_the_key_is_top_second_and_the_blended_distance(self) -> None:
        ctx = top_context()
        ctx.hills_weight = 0.5
        a = reading(lts4=10.0, lts3=20.0, effort=20_000.0, length=10_000.0)
        assert a.key(ctx) == (10.0, 20.0, 15_000.0)
        ctx.hills_weight = 0.0
        assert a.key(ctx) == (10.0, 20.0, 10_000.0)


class TestTheOrder:
    """OWNER-DECISIONS 256, 258, 259, 260, 261: within the ceiling, LTS 4 and
    Avoid plus red junctions first, then LTS 3 plus orange junctions, then the
    hills preference, then distance."""

    ctx = top_context()

    def test_less_lts4_beats_less_lts3(self) -> None:
        calm3 = reading(lts4=300.0, lts3=0.0)
        calm4 = reading(lts4=0.0, lts3=5000.0)
        assert refine.better(calm4, calm3, self.ctx)
        assert not refine.better(calm3, calm4, self.ctx)

    def test_one_fewer_red_junction_beats_less_lts3(self) -> None:
        """OWNER-DECISIONS 258: a red junction before LTS 3."""
        red = reading(lts3=0.0, red=[3000.0])
        none = reading(lts3=5000.0)
        assert refine.better(none, red, self.ctx)
        assert not refine.better(red, none, self.ctx)

    def test_a_red_junction_is_worth_its_own_cost_in_lts4(self) -> None:
        """OWNER-DECISIONS 259: trading 1,000 ft of LTS 4 to avoid a 3,000 ft
        red junction is accepted; 1,000 ft for a 500 ft one is not (it is
        not a red junction, and costs more)."""
        feet = 1000.0 / FT
        with_junction = reading(lts4=0.0, red=[3000.0])
        traded = reading(lts4=feet)
        assert refine.better(traded, with_junction, self.ctx)
        # And the other way about: 3,500 ft of LTS 4 is worth more than the junction.
        assert not refine.better(reading(lts4=3500.0 / FT), with_junction, self.ctx)

    def test_an_orange_junction_is_equivalent_to_the_same_cost_of_lts3(self) -> None:
        """OWNER-DECISIONS 260: a 1,000 ft-cost orange junction counts as 1,000 ft
        of LTS 3."""
        feet = 1000.0 / FT
        orange = reading(orange=[1000.0])
        lts3 = reading(lts3=feet)
        assert orange.second_m == pytest.approx(lts3.second_m)
        assert not refine.better(orange, lts3, self.ctx)
        assert not refine.better(lts3, orange, self.ctx)
        # A little more of either is worse past the tolerance, and only then.
        step = refine.MAXCALM_STEPS[1]
        assert refine.better(lts3, reading(orange=[1000.0 + 2 * step * FT]), self.ctx)
        assert refine.better(orange, reading(lts3=feet + 2 * step), self.ctx)

    def test_the_second_figure_decides_when_the_top_ties(self) -> None:
        a = reading(lts4=100.0, lts3=100.0)
        b = reading(lts4=100.0, lts3=900.0)
        assert refine.better(a, b, self.ctx) and not refine.better(b, a, self.ctx)

    def test_the_top_figure_is_a_tie_within_its_tolerance(self) -> None:
        """About 50 ft: a trivial gain at the top does not force a loss below it."""
        tol = refine.MAXCALM_STEPS[0]
        assert tol == pytest.approx(15.0) and 45 < tol * FT < 55
        base = reading(lts4=100.0, lts3=2000.0)
        small = reading(lts4=100.0 - tol, lts3=3000.0)
        assert not refine.better(small, base, self.ctx), "tie at the top, LTS 3 decides"
        assert refine.better(base, small, self.ctx)
        big = reading(lts4=100.0 - tol - 1.0, lts3=3000.0)
        assert refine.better(big, base, self.ctx), "past the tolerance the top decides"

    def test_each_levels_tolerance_is_exact(self) -> None:
        ctx = top_context()
        assert len(refine.MAXCALM_STEPS) == 3
        for level, step in enumerate(refine.MAXCALM_STEPS):
            figures = [dict(lts4=1000.0), dict(lts3=1000.0), dict(length=1e5)]
            name = list(figures[level])[0]
            base = reading(**figures[level])
            inside = reading(**{name: figures[level][name] - step})
            outside = reading(**{name: figures[level][name] - step - 1.0})
            assert not refine.better(inside, base, ctx), (level, "at the step is a tie")
            assert refine.better(outside, base, ctx), (level, "past the step is better")

    def test_distance_decides_last(self) -> None:
        short, long = reading(length=9_000.0), reading(length=12_000.0)
        assert refine.better(short, long, self.ctx)
        assert not refine.better(long, short, self.ctx)

    def test_below_the_top_the_score_decides(self) -> None:
        ctx = context(rate=2.0)
        cheap = with_(analysis("c", "1" * 40, cost_s=3000.0), lts4_m=900.0)
        dear = analysis("d", "1" * 40, cost_s=4000.0)
        assert refine.better(cheap, dear, ctx)
        assert not refine.better(dear, cheap, ctx)


class TestDiminishingReturns:
    """OWNER-DECISIONS 268: "Diminishing returns (Recommended)". Extra distance is
    taken only where it buys a meaningful stress cut: about 1 mi of LTS 3 saved per
    5 mi added, LTS 4 and Avoid at the level weights 2 and 3 (`WORTH_WEIGHTS`), a red
    junction's cost at the LTS 4 weight and an orange one's at the LTS 3 weight."""

    def test_the_constants(self) -> None:
        assert refine.WORTH_DEFAULT == 5.0
        assert refine.WORTH_OVER_TARGET == 2.5
        assert refine.WORTH_OVER_TARGET < refine.WORTH_DEFAULT, "stricter past the target"

    def test_the_stress_figure_uses_the_level_weights(self) -> None:
        assert refine.WORTH_WEIGHTS == presets.EXPOSURE_STANDARD
        assert (refine.WORTH_WEIGHTS.lts3, refine.WORTH_WEIGHTS.lts4) == (1.0, 2.0)
        assert refine.WORTH_WEIGHTS.avoid == 3.0
        read = with_(reading(lts3=500.0, lts4=300.0, red=[3000.0], orange=[1000.0]), avoid_m=100.0)
        want = 500.0 + 2.0 * 200.0 + 3.0 * 100.0 + 2.0 * 3000.0 / FT + 1000.0 / FT
        for exposure in (AVERSE, presets.EXPOSURE_STANDARD):
            ctx = top_context()
            ctx.exposure = exposure
            assert refine.stress_weight_m(read, ctx) == pytest.approx(want), exposure

    def test_a_mile_of_lts3_buys_five_miles_and_no_more(self) -> None:
        ctx = top_context()
        base = with_(reading(lts3=1609.0, length=10_000.0), exposure_m=1609.0)
        five = with_(reading(lts3=0.0, length=10_000.0 + 5 * 1609.0), exposure_m=0.0)
        six = with_(reading(lts3=0.0, length=10_000.0 + 6 * 1609.0), exposure_m=0.0)
        assert refine.worth_it(base, five, ctx) and refine.better(five, base, ctx)
        assert not refine.worth_it(base, six, ctx) and not refine.better(six, base, ctx)
        # And the shorter one replaces a calmer longer one whose miles were not worth it.
        assert refine.better(base, six, ctx)
        assert not refine.better(base, five, ctx)

    def test_lts4_counts_at_its_weight(self) -> None:
        """LTS 4 is two of LTS 3, Avoid three: 1 mi of LTS 4 buys up to 10 mi, on a
        stress-averse ride too."""
        ctx = top_context()
        ctx.exposure = AVERSE
        base = reading(lts4=1609.0, length=10_000.0)
        far = reading(length=10_000.0 + 9.9 * 1609.0)
        too_far = reading(length=10_000.0 + 10.1 * 1609.0)
        assert refine.better(far, base, ctx) and not refine.better(too_far, base, ctx)
        avoid = with_(base, avoid_m=1609.0)
        assert refine.better(reading(length=10_000.0 + 14.9 * 1609.0), avoid, ctx)
        assert not refine.better(reading(length=10_000.0 + 15.1 * 1609.0), avoid, ctx)

    def test_a_red_junction_counts_at_the_lts4_weight(self) -> None:
        ctx = top_context()
        ctx.exposure = AVERSE
        red = reading(red=[3000.0], length=10_000.0)
        # 2 x 3,000 ft is about 1,829 m of LTS 3: 9.1 km of extra riding.
        ok = reading(length=10_000.0 + 9_000.0)
        no = reading(length=10_000.0 + 9_200.0)
        assert refine.better(ok, red, ctx) and not refine.better(no, red, ctx)

    def test_an_orange_junction_counts_at_the_lts3_weight(self) -> None:
        ctx = top_context()
        orange = reading(orange=[1000.0], length=10_000.0)  # 304.8 m of LTS 3
        assert refine.better(reading(length=10_000.0 + 1500.0), orange, ctx)
        assert not refine.better(reading(length=10_000.0 + 1600.0), orange, ctx)

    def test_the_charge_is_on_the_distance_the_hills_slider_weighs(self) -> None:
        """A longer route that is less effort (Hills set to avoid) is not charged."""
        ctx = top_context()
        ctx.hills_weight = 1.0
        hilly = with_(reading(lts3=100.0, length=9_000.0, effort=30_000.0), exposure_m=100.0)
        flat = with_(reading(length=20_000.0, effort=20_000.0), exposure_m=0.0)
        assert refine.better(flat, hilly, ctx)
        ctx.hills_weight = 0.0
        assert not refine.better(flat, hilly, ctx)

    def test_the_rule_can_be_off(self) -> None:
        ctx = dataclasses.replace(top_context(), worth_rule=False)
        base = with_(reading(lts3=1609.0), exposure_m=1609.0)
        far = with_(reading(length=10_000.0 + 50 * 1609.0), exposure_m=0.0)
        assert refine.better(far, base, ctx)

    def test_below_the_top_the_rule_does_not_apply(self) -> None:
        ctx = context(rate=2.0)
        cheap = with_(analysis("c", "1" * 40, cost_s=3000.0), length_m=1e6)
        dear = analysis("d", "1" * 40, cost_s=4000.0)
        assert refine.better(cheap, dear, ctx)


class TestTheTargetDistance:
    """OWNER-DECISIONS 271: a target, not a maximum. Up to it, distance is free; past
    it, the extra must buy stress at the stricter WORTH_OVER_TARGET; never past the
    ceiling (1.25 times it)."""

    def ctx(self, target=20_000.0) -> refine.Context:
        return top_context(target_m=target, ceiling_m=presets.target_ceiling_m(target))

    def test_the_ceiling_is_1_25_times_the_target(self) -> None:
        assert presets.TARGET_CEILING_RATIO == 1.25
        assert presets.target_ceiling_m(80_000.0) == pytest.approx(100_000.0)
        assert refine.too_long(25_001.0, self.ctx()) and not refine.too_long(25_000.0, self.ctx())

    def test_below_the_target_distance_is_free(self) -> None:
        ctx = self.ctx()
        base = with_(reading(lts3=60.0, length=5_000.0), exposure_m=60.0)
        far = with_(reading(lts3=0.0, length=19_900.0), exposure_m=0.0)
        assert refine.distance_charge_m(5_000.0, 19_900.0, ctx) == 0.0
        assert refine.better(far, base, ctx)

    def test_past_the_target_the_bar_is_stricter(self) -> None:
        ctx = self.ctx()
        assert refine.distance_charge_m(19_000.0, 22_000.0, ctx) == pytest.approx(2000.0 / 2.5)
        assert refine.distance_charge_m(21_000.0, 22_000.0, ctx) == pytest.approx(1000.0 / 2.5)
        base = with_(reading(lts3=900.0, length=19_000.0), exposure_m=900.0)
        ok = with_(reading(length=22_000.0), exposure_m=0.0)  # 900 saved, 800 needed
        assert refine.better(ok, base, ctx)
        thin = reading(lts3=200.0, length=22_000.0)  # 700 saved
        assert not refine.better(thin, base, ctx)
        # The same miles with no target cost more (all 3 km at 1 in 5: 600) but no
        # more than 1 in 2.5 past it.
        assert refine.distance_charge_m(19_000.0, 22_000.0, top_context()) == pytest.approx(600.0)

    def test_past_the_ceiling_never(self) -> None:
        ctx = self.ctx()
        assert refine.too_long(26_000.0, ctx)

    def test_a_leg_is_charged_at_the_whole_trips_length(self) -> None:
        ctx = self.ctx()
        base = with_(reading(lts3=100.0, length=5_000.0), exposure_m=100.0)
        longer = with_(reading(length=8_000.0), exposure_m=0.0)
        assert refine.better(longer, base, ctx)  # 8 km, under the target
        assert not refine.better(longer, base, ctx, rest_m=15_000.0)  # 23 km: 3 km over

    def test_a_candidate_goes_no_further_past_the_target_than_the_answer(self) -> None:
        ctx = self.ctx()
        answer = reading(length=21_000.0)
        assert not refine.over_answer(reading(length=21_000.0), answer, ctx)
        assert not refine.over_answer(reading(length=20_000.0), answer, ctx)
        assert refine.over_answer(reading(length=21_600.0), answer, ctx)
        assert not refine.over_answer(reading(length=24_000.0), answer, top_context())
        under = reading(length=15_000.0)
        assert not refine.over_answer(reading(length=19_999.0), under, ctx)
        assert refine.over_answer(reading(length=20_600.0), under, ctx)


class TestTheHillsLevel:
    """OWNER-DECISIONS 262, 263: the third level is the effort-equivalent distance,
    blended with the actual distance by the Hills slider (261's lexicographic hills
    level is superseded)."""

    def avoid(self, weight: float = 1.0) -> refine.Context:
        ctx = top_context()
        ctx.hills_weight = weight
        return ctx

    flat = dict(length=12_000.0, effort=12_100.0)
    hilly = dict(length=9_000.0, effort=30_000.0)

    def test_with_hills_set_to_avoid_the_flatter_route_wins_even_if_longer(self) -> None:
        flat, hilly = reading(**self.flat), reading(**self.hilly)
        assert refine.better(flat, hilly, self.avoid())
        assert not refine.better(hilly, flat, self.avoid())

    def test_at_the_detent_the_shorter_actual_route_wins(self) -> None:
        flat, hilly = reading(**self.flat), reading(**self.hilly)
        detent = self.avoid(0.0)
        assert refine.better(hilly, flat, detent)
        assert not refine.better(flat, hilly, detent)

    def test_the_slider_blends_actual_and_effort_distance(self) -> None:
        flat, hilly = reading(**self.flat), reading(**self.hilly)
        ctx = self.avoid(0.25)
        assert refine.level3(flat, ctx) == pytest.approx(0.75 * 12_000 + 0.25 * 12_100)
        assert refine.level3(hilly, ctx) == pytest.approx(0.75 * 9_000 + 0.25 * 30_000)
        assert refine.better(flat, hilly, ctx)
        # A touch toward avoid still prefers the shorter route.
        assert refine.better(hilly, flat, self.avoid(0.05))

    def test_it_comes_after_the_second_figure(self) -> None:
        calm = reading(lts3=0.0, effort=90_000.0)
        flat = reading(lts3=500.0, effort=10_000.0)
        assert refine.better(calm, flat, self.avoid())

    def test_the_ceiling_is_in_actual_metres_not_effort_miles(self) -> None:
        ctx = top_context(ceiling_m=10_000.0)
        assert not refine.too_long(reading(**self.hilly).length_m, ctx)
        assert refine.too_long(reading(**self.flat).length_m, ctx)

    def test_the_seek_half_has_a_hook_for_more_effort_being_better(self) -> None:
        ctx = top_context()
        ctx.hills_seek_weight = 0.5
        # Between routes as long as each other, the one with far more effort wins with the hook,
        # and loses without it.
        hard = reading(length=10_000.0, effort=30_000.0)
        easy = reading(length=10_000.0, effort=10_000.0)
        assert refine.level3(hard, ctx) < refine.level3(easy, ctx)
        assert refine.better(hard, easy, ctx)
        assert not refine.better(hard, easy, top_context()), "without the hook the two tie"
        # Under a target the miles are free (268, 271): there the hook may take the longer one.
        under = top_context(target_m=20_000.0)
        under.hills_seek_weight = 0.5
        longer_hard = reading(length=12_000.0, effort=30_000.0)
        shorter_easy = reading(length=9_000.0, effort=9_000.0)
        assert refine.better(longer_hard, shorter_easy, under)

    def test_seeking_climbs_never_buys_miles_the_charge_has_no_seek_credit(self) -> None:
        """The release re-check's S1 probe: 20 km flat with 1 km of LTS 3, against
        40 km hilly (an effort of 60 km) with none. The charge for the 20 km added is the
        same with Hills at the detent and at full seek (4 km of LTS 3 to save, at 5 to 1),
        so the 1 km saved is not worth it either way (OWNER-DECISIONS 298(3))."""
        short = reading(length=20_000.0, effort=20_000.0, lts3=1_000.0)
        long_ = reading(length=40_000.0, effort=60_000.0)
        for seek in (0.0, 1.0):
            ctx = top_context()
            ctx.hills_seek_weight = seek
            charge = refine.distance_charge_m(
                short.length_m,
                long_.length_m,
                ctx,
                refine.charged_m(long_, ctx) - refine.charged_m(short, ctx),
            )
            assert charge == pytest.approx(4_000.0), seek
            assert not refine.worth_it(short, long_, ctx), seek
            assert not refine.better(long_, short, ctx), seek
        # The tiebreak itself still prefers the climb when seeking.
        seeking = top_context()
        seeking.hills_seek_weight = 1.0
        assert refine.level3(long_, seeking) < refine.level3(short, seeking)

    def read_trip(self, monkeypatch, effort_fn, ctx):
        monkeypatch.setattr(refine.effort, "effort_equivalent_m", effort_fn)
        monkeypatch.setattr(routing, "_trace", lambda *a, **k: {"shape": "x"})
        monkeypatch.setattr(
            routing, "pieces_of_trace", lambda trace: [routing.Piece(1, BASE[0], BASE[1], 100.0)]
        )
        monkeypatch.setattr(
            routing, "decode_polyline6", lambda s: [BASE, (BASE[0] + 0.01, BASE[1])]
        )
        monkeypatch.setattr(
            routing, "classify", lambda p, when, roadway_only=False: [("1", "none")]
        )
        monkeypatch.setattr(refine.trace_junctions, "junctions_of_trace", lambda *a: [])
        monkeypatch.setattr(refine.trace_junctions, "edge_midpoints", lambda *a: [])
        monkeypatch.setattr(refine, "events_of_raws", lambda raws, ctx, deadline: [])
        trip = {
            "legs": [{"shape": "x", "elevation": [10.0, 20.0], "summary": {"length": 0.1}}],
            "summary": {"length": 0.1, "time": 10.0, "cost": 1.0},
        }
        return refine.analyse(trip, ctx, ctx.deadline)

    def test_the_effort_is_read_from_the_elevation_profile_and_the_system_weight(
        self, monkeypatch
    ) -> None:
        seen = {}

        def effort(profile, length, mass):
            seen["args"] = (list(profile), length, mass)
            return 4321.0

        ctx = top_context()
        ctx.mass_kg = 120.0
        read = self.read_trip(monkeypatch, effort, ctx)
        assert read.effort_m == 4321.0
        profile, length, mass = seen["args"]
        assert profile[0] == (0.0, 10.0) and length == pytest.approx(100.0) and mass == 120.0

    def test_no_profile_is_the_actual_length(self, monkeypatch) -> None:
        read = self.read_trip(monkeypatch, lambda *a: None, top_context())
        assert read.effort_m == pytest.approx(100.0)


def held_reading(lts4: float = 0.0, red=()) -> refine.Analysis:
    """A route of an LTS 4 stretch `lts4` metres long (none if 0) and 1,000 m of
    quiet street, with a red junction of each cost in feet, 1,500 m along."""
    pieces, classes = [], []
    if lts4:
        pieces.append(routing.Piece(1, BASE[0], BASE[1], lts4))
        classes.append(("4", "none"))
    pieces.append(routing.Piece(1, BASE[0] + 1e-3, BASE[1], 1000.0))
    classes.append(("1", "none"))
    return refine.Analysis(
        length_m=lts4 + 1000.0,
        cost_s=1000.0,
        exposure_m=0.0,
        climb_m=0.0,
        pieces=pieces,
        classes=classes,
        events=[event(500.0 + 10 * i, cost) for i, cost in enumerate(red)],
        lts4_m=lts4,
    )


class TestTheHoldOnTheTopFigure:
    """OWNER-DECISIONS 250, amended by 259: refused only if the top figure (LTS 4 and
    Avoid plus red junction cost) is more than the router's first route's."""

    def held(self, first: refine.Analysis) -> refine.Context:
        ctx = top_context()
        ctx.exposure = AVERSE
        ctx.first_lts4 = refine.top_by_leg(first)
        return ctx

    def test_more_lts4_with_no_junction_gain_is_refused(self) -> None:
        ctx = self.held(held_reading(100.0))
        assert refine.more_lts4(held_reading(200.0), ctx.first_lts4, ctx)
        assert not refine.more_lts4(held_reading(100.0), ctx.first_lts4, ctx)
        assert not refine.more_lts4(held_reading(40.0), ctx.first_lts4, ctx)

    def test_lts4_traded_for_a_red_junction_is_allowed(self) -> None:
        ctx = self.held(held_reading(0.0, red=[3000.0]))
        assert not refine.more_lts4(held_reading(1000.0 / FT), ctx.first_lts4, ctx)
        assert refine.more_lts4(held_reading(3600.0 / FT), ctx.first_lts4, ctx)

    def test_a_red_junction_gained_counts_against_it(self) -> None:
        ctx = self.held(held_reading(100.0))
        assert refine.more_lts4(held_reading(100.0, red=[3500.0]), ctx.first_lts4, ctx)

    def test_an_orange_junction_does_not_count_in_it(self) -> None:
        ctx = self.held(held_reading(100.0))
        assert not refine.more_lts4(held_reading(100.0, red=[1500.0]), ctx.first_lts4, ctx)

    def test_one_metre_of_slack(self) -> None:
        ctx = self.held(held_reading(100.0))
        assert not refine.more_lts4(held_reading(101.0), ctx.first_lts4, ctx)
        assert refine.more_lts4(held_reading(101.1), ctx.first_lts4, ctx)

    def test_the_hold_is_not_on_other_rides(self) -> None:
        ctx = top_context()
        assert not refine.more_lts4(held_reading(900.0), [0.0], ctx)

    def test_each_legs_red_junctions_count_in_that_leg(self) -> None:
        a = held_reading(0.0)
        a.events = [event(150.0, 3000.0), event(850.0, 3200.0), event(300.0, 1000.0)]
        a.pieces = [
            routing.Piece(1, BASE[0], BASE[1], 500.0),
            routing.Piece(1, BASE[0], BASE[1], 500.0),
        ]
        a.classes = [("1", "none"), ("1", "none")]
        a.via_m = [500.0]
        legs = refine.top_by_leg(a)
        assert legs[0] == pytest.approx(3000.0 / FT) and legs[1] == pytest.approx(3200.0 / FT)

    def test_a_junction_at_the_very_end_belongs_to_the_last_leg(self) -> None:
        a = held_reading(0.0)
        a.events = [event(1000.0, 3000.0)]
        assert refine.top_by_leg(a) == [pytest.approx(3000.0 / FT)]


# --- The ceiling in the search ------------------------------------------------------

ORIG = "1" * 10 + "3" * 20 + "1" * 10


class TestTheCeilingInTheSearch:
    def test_too_long_is_past_the_limit_and_only_where_there_is_one(self) -> None:
        assert refine.too_long(5001.0, top_context(ceiling_m=5000.0))
        assert not refine.too_long(5000.0, top_context(ceiling_m=5000.0))
        assert not refine.too_long(1e9, top_context())

    def test_a_route_past_it_is_not_read_or_taken_and_halves_are_tried(self, monkeypatch) -> None:
        world = World(
            monkeypatch,
            {"o": analysis("o", ORIG)},
            [trip_of("long", 6.0), trip_of("long", 6.0), trip_of("long", 6.0)],
        )
        kept, info = refine.refine(trip_of("o", 4.0), top_context(ceiling_m=4500.0))
        assert kept["legs"][0]["shape"] == "o"
        # `ceiling`, not the no-fit answer's `target_distance` (correctness review S2).
        assert info["limited"] == "ceiling" and info["rounds"] == 0
        # Every target, then each half of it: three different sets.
        sets = [frozenset(world.excluded(i)) for i in range(3)]
        assert len(world.requests) == 3 and len(set(sets)) == 3
        assert sets[0] > sets[1] and sets[0] > sets[2] and not sets[1] & sets[2]

    def test_a_half_that_fits_is_taken(self, monkeypatch) -> None:
        calmer = analysis("h", "1" * 10 + "3" * 5 + "1" * 25)
        World(
            monkeypatch,
            {"o": analysis("o", ORIG), "h": calmer},
            [trip_of("long", 6.0), trip_of("h", 4.2)] + [trip_of("h", 4.2)] * 6,
        )
        kept, info = refine.refine(trip_of("o", 4.0), top_context(ceiling_m=4500.0))
        assert kept["legs"][0]["shape"] == "h"
        assert info["lts3_m_before"] == 2000.0 and info["lts3_m_after"] == 500.0

    def test_a_candidate_within_it_that_is_calmer_is_taken_and_a_longer_one_is_not(
        self, monkeypatch
    ) -> None:
        calm = analysis("c", "1" * 40)
        World(monkeypatch, {"o": analysis("o", ORIG), "c": calm}, [trip_of("c", 4.4)] * 3)
        kept, _info = refine.refine(trip_of("o", 4.0), top_context(ceiling_m=4500.0))
        assert kept["legs"][0]["shape"] == "c"
        World(monkeypatch, {"o": analysis("o", ORIG), "c": calm}, [trip_of("c", 4.6)] * 5)
        kept, info = refine.refine(trip_of("o", 4.0), top_context(ceiling_m=4500.0))
        assert kept["legs"][0]["shape"] == "o" and info["limited"] == "ceiling"

    def test_no_cap_below_the_top(self, monkeypatch) -> None:
        calm = analysis("c", "1" * 40, cost_s=3000.0)
        World(monkeypatch, {"o": analysis("o", ORIG), "c": calm}, [trip_of("c", 40.0)] * 3)
        kept, _info = refine.refine(trip_of("o", 4.0), context(rate=5.0))
        assert kept["legs"][0]["shape"] == "c"

    def test_at_the_top_the_routers_own_price_does_not_come_into_it(self, monkeypatch) -> None:
        """A route the router prices far dearer, but with less LTS 3, is taken."""
        calm = analysis("c", "1" * 40, cost_s=99_999.0)
        World(
            monkeypatch,
            {"o": analysis("o", ORIG, cost_s=100.0), "c": calm},
            [trip_of("c", 4.0)] * 3,
        )
        kept, _info = refine.refine(trip_of("o", 4.0), top_context())
        assert kept["legs"][0]["shape"] == "c"

    def test_a_trail_is_worth_no_more_than_a_quiet_street(self, monkeypatch) -> None:
        """OWNER-DECISIONS 257: a route over a path and one over quiet streets, the
        same on every figure, tie; the shorter wins."""
        path = analysis("p", "1" * 40)
        path.classes = [(tier, "path") for tier, _kind in path.classes]
        quiet = analysis("q", "1" * 40)
        quiet.length_m = 3900.0
        ctx = top_context()
        assert refine.better(quiet, path, ctx) and not refine.better(path, quiet, ctx)
        assert path.key(ctx) == with_(path, classes=quiet.classes).key(ctx)

    def test_a_hold_refusal_does_not_use_up_the_patience(self, monkeypatch) -> None:
        """GATE-corr SF2: a round the LTS 4 hold refuses says nothing about the
        next, so two of them in a row do not end the search."""
        ctx = context(rate=10.0)
        ctx.exposure = AVERSE
        orig = "1" * 10 + "4" + "3" * 9 + "1" * 20
        refused = [
            "1" * 20 + "44" + "3" * 8 + "1" * 10,
            "1" * 30 + "44" + "3" * 8,
            "1" * 5 + "44" + "3" * 3 + "1" * 30,
        ]
        analyses = {"o": _weighed(analysis("o", orig))}
        routes = []
        for number, tiers in enumerate(refused):
            analyses[f"r{number}"] = _weighed(analysis(f"r{number}", tiers))
            routes.append(trip_of(f"r{number}", 4.0))
        analyses["good"] = _weighed(analysis("good", "1" * 40))
        routes.append(trip_of("good", 4.2))
        World(monkeypatch, analyses, routes)
        kept, info = refine.refine(trip_of("o", 4.0), ctx)
        assert kept["legs"][0]["shape"] == "good"
        assert info["rounds"] == 4

    def test_ordinary_non_improving_rounds_still_end_it(self, monkeypatch) -> None:
        ctx = context(rate=10.0)
        same = [
            "1" * 20 + "3" * 5 + "1" * 15,
            "1" * 30 + "3" * 5 + "1" * 5,
            "1" * 6 + "3" * 3 + "1" * 31,
            "1" * 15 + "3" * 3 + "1" * 22,
        ]
        analyses = {"o": analysis("o", "1" * 10 + "3" * 5 + "1" * 25)}
        routes = []
        for number, tiers in enumerate(same):
            analyses[f"s{number}"] = analysis(f"s{number}", tiers, cost_s=9000.0)
            routes.append(trip_of(f"s{number}", 4.0))
        World(monkeypatch, analyses, routes)
        kept, info = refine.refine(trip_of("o", 4.0), ctx)
        assert kept["legs"][0]["shape"] == "o"
        assert info["rounds"] == refine.REFINE_PATIENCE


def _weighed(read: refine.Analysis) -> refine.Analysis:
    w = AVERSE.weights
    read.exposure_m = sum(
        p.metres * w.get(t, 0.0) for p, (t, _k) in zip(read.pieces, read.classes, strict=True)
    )
    return read


# --- Cutting a long trip into legs ---------------------------------------------------


class TestLegCounts:
    def test_a_leg_is_about_12_km_of_straight_line(self) -> None:
        assert legsplit.LEG_TARGET_SPAN_M == 12_000.0
        assert legsplit.leg_count(41_000.0) == 4
        assert legsplit.leg_count(12_000.0) == 1
        assert legsplit.leg_count(12_001.0) == 2
        assert legsplit.leg_count(0.0) == 1 and legsplit.leg_count(-5.0) == 1

    def test_the_target_is_a_parameter(self) -> None:
        assert legsplit.leg_count(10_000.0, 5_000.0) == 2
        assert legsplit.leg_count(10_000.0, 0.0) == 1


class TestBusyRuns:
    def test_adjacent_busy_pieces_are_one_run(self) -> None:
        runs = legsplit.busy_runs([100.0] * 6, [False, True, True, False, True, False])
        assert runs == [(100.0, 300.0), (400.0, 500.0)]

    def test_none_busy_is_none(self) -> None:
        assert legsplit.busy_runs([100.0, 100.0], [False, False]) == []

    def test_a_run_at_the_start_and_the_end(self) -> None:
        assert legsplit.busy_runs([50.0, 50.0, 50.0], [True, False, True]) == [
            (0.0, 50.0),
            (100.0, 150.0),
        ]


class TestClearOf:
    runs = [(1000.0, 2000.0), (5000.0, 5500.0)]

    def test_distance_to_the_nearest_run(self) -> None:
        assert legsplit.clear_of(500.0, self.runs) == 500.0
        assert legsplit.clear_of(2600.0, self.runs) == 600.0
        assert legsplit.clear_of(4000.0, self.runs) == 1000.0
        assert legsplit.clear_of(7000.0, self.runs) == 1500.0

    def test_inside_a_run_is_zero(self) -> None:
        assert legsplit.clear_of(1500.0, self.runs) == 0.0
        assert legsplit.clear_of(1000.0, self.runs) == 0.0

    def test_with_none_it_is_infinite(self) -> None:
        assert legsplit.clear_of(10.0, []) == float("inf")


def route_marks(length=40_000.0, step=200.0, edge=150.0):
    return [(at, BASE[0] + at * 1e-5, BASE[1], edge) for at in _frange(step / 2, length, step)]


def _frange(a, b, step):
    x = a
    while x < b:
        yield x
        x += step


class TestSplitPoints:
    def test_even_cuts_with_nothing_busy(self) -> None:
        cuts = legsplit.split_points(route_marks(), [], 0.0, 40_000.0, 4)
        assert all(abs(c[0] - 10_000.0 * (i + 1)) <= 100.0 for i, c in enumerate(cuts))
        assert len(cuts) == 3

    def test_one_leg_has_no_cuts(self) -> None:
        assert legsplit.split_points(route_marks(), [], 0.0, 10_000.0, 1) == []
        assert legsplit.split_points(route_marks(), [], 5.0, 5.0, 3) == []

    def test_a_cut_keeps_clear_of_busy_road(self) -> None:
        runs = [(9_000.0, 11_500.0)]
        cuts = legsplit.split_points(route_marks(), runs, 0.0, 40_000.0, 4)
        first = cuts[0][0]
        assert legsplit.clear_of(first, runs) >= legsplit.CLEAR_M
        # The nearest such place to the even split: 8,400 (1,600 away) beats 12,000 (2,000).
        assert first == pytest.approx(8_500.0, abs=100.0)

    def test_where_nothing_is_clear_the_most_room_is_taken(self) -> None:
        runs = [(6_000.0, 14_000.0)]
        cuts = legsplit.split_points(route_marks(), runs, 0.0, 40_000.0, 4)
        first = cuts[0][0]
        assert legsplit.clear_of(first, runs) < legsplit.CLEAR_M
        window = legsplit.WINDOW * 10_000.0
        best = max(
            legsplit.clear_of(a, runs) for a, *_ in route_marks() if abs(a - 10_000.0) <= window
        )
        assert legsplit.clear_of(first, runs) == pytest.approx(best)

    def test_cuts_are_on_edges_long_enough_and_not_near_the_ends(self) -> None:
        marks = [(500.0, 0.0, 0.0, 150.0), (10_000.0, 1.0, 1.0, 10.0), (10_200.0, 2.0, 2.0, 100.0)]
        (cut,) = legsplit.split_points(marks, [], 0.0, 20_000.0, 2)
        assert cut[1:] == (2.0, 2.0), "the short edge is not used"
        assert legsplit.split_points([(100.0, 0.0, 0.0, 99.0)], [], 0.0, 2000.0, 2) == []

    def test_fewer_cuts_than_asked_where_there_is_no_place(self) -> None:
        marks = [(10_000.0, 0.0, 0.0, 150.0)]
        cuts = legsplit.split_points(marks, [], 0.0, 30_000.0, 3)
        assert len(cuts) == 0 or len(cuts) == 1
        assert all(abs(c[0] - 10_000.0) < 1 for c in cuts)

    def test_cuts_are_in_order_and_apart(self) -> None:
        cuts = legsplit.split_points(route_marks(), [(9_000.0, 31_000.0)], 0.0, 40_000.0, 4)
        ats = [c[0] for c in cuts]
        assert ats == sorted(ats) and len(set(ats)) == len(ats)
        assert all(b - a >= legsplit.END_MARGIN_M for a, b in zip(ats, ats[1:], strict=False))

    def test_the_stretch_is_the_trips_leg_not_the_whole_route(self) -> None:
        cuts = legsplit.split_points(route_marks(), [], 20_000.0, 40_000.0, 2)
        assert len(cuts) == 1 and abs(cuts[0][0] - 30_000.0) <= 100.0


# --- The long search -----------------------------------------------------------------

LEN = 400  # pieces of 100 m: a 40 km route
EAST = 0.4  # degrees of longitude from the start to the end: about 34.6 km straight


def long_whole() -> refine.Analysis:
    """A 40 km route with a busy stretch (LTS 3) 12 to 14.5 km out."""
    return analysis("whole", "1" * 120 + "3" * 25 + "1" * (LEN - 145))


class LongWorld:
    """The router and the readings, for `refine_long`: `firsts` are each leg's own
    route (a summary length in km and the reading of it), `searches` what each leg's
    exclusion searches find, in order."""

    def __init__(self, monkeypatch, cuts, firsts: dict, searches: dict | None = None) -> None:
        self.cuts = cuts
        self.firsts = firsts
        self.searches = {k: list(v) for k, v in (searches or {}).items()}
        self.requests: list[dict] = []
        self.analysed: list[tuple[str, bool]] = []
        self.readings = {"whole": long_whole()}
        for name, (_km, read) in firsts.items():
            self.readings[name] = read
        for lst in self.searches.values():
            for name, _km, read in lst:
                self.readings[name] = read
        monkeypatch.setattr(refine, "analyse", self.analyse)
        monkeypatch.setattr(routing, "_call", self.call)

    def leg_of(self, location: dict) -> int:
        lons = [BASE[0], *self.cuts]
        return max(i for i, lon in enumerate(lons) if location["lon"] >= lon - 1e-9)

    def analyse(self, trip, ctx, deadline, with_events=True):
        name = trip["legs"][0]["shape"]
        self.analysed.append((name, with_events))
        if with_events:
            # As the real `analyse` remembers a reading per plan.
            ctx.analyses[tuple(leg["shape"] for leg in trip["legs"])] = self.readings[name]
        return self.readings[name]

    def call(self, variant, endpoint, payload, deadline):
        assert endpoint == "route"
        self.requests.append(payload)
        leg = self.leg_of(payload["locations"][0])
        if "exclude_locations" in payload:
            queue = self.searches.get(leg) or []
            if not queue:
                raise routing.RouterRefused(400, 171, "no route")
            name, km, _read = queue.pop(0)
            return {"trip": trip_of(name, km)}
        name, (km, _read) = list(self.firsts.items())[leg]
        return {"trip": trip_of(name, km)}


def long_context(**kw) -> refine.Context:
    ctx = context(rate=10.0, maxcalm=True, **kw)
    ctx.points = [[BASE[0], BASE[1]], [BASE[0] + EAST, BASE[1]]]
    ctx.request = {
        "locations": [
            {"lon": BASE[0], "lat": BASE[1], "type": "break"},
            {"lon": BASE[0] + EAST, "lat": BASE[1], "type": "break"},
        ],
        "costing": "bicycle",
        "elevation_interval": 30,
    }
    ctx.deadline = routing.Deadline(routing.clock() + 47, 45)
    return ctx


def cut_lons() -> list[float]:
    cuts = legsplit.split_points(
        refine._marks(long_whole()),
        legsplit.busy_runs([100.0] * LEN, refine._busy_flags(long_whole())),
        0.0,
        40_000.0,
        3,
    )
    return [c[1] for c in cuts]


def legs_world(monkeypatch, searches=None, lengths=(13.3, 13.3, 13.3)):
    cuts = cut_lons()
    firsts = {
        "L0": (lengths[0], analysis("L0", "1" * 133)),
        "L1": (lengths[1], analysis("L1", "1" * 20 + "4" + "3" * 10 + "1" * 102)),
        "L2": (lengths[2], analysis("L2", "1" * 30 + "3" * 20 + "1" * 83)),
    }
    world = LongWorld(monkeypatch, cuts, firsts, searches)
    world.readings["L1c"] = world.readings.get("L1c") or analysis("L1c", "1" * 133)
    return world


def whole_trip() -> dict:
    return {
        "legs": [{"shape": "whole"}],
        "summary": {"length": 40.0, "time": 8000.0, "cost": 9000.0, "min_lat": 1.0},
    }


class TestTheLongSearch:
    def test_the_trip_is_cut_into_legs_at_points_on_its_route(self, monkeypatch) -> None:
        world = legs_world(monkeypatch)
        trip, info = refine.refine_long(whole_trip(), long_context(ceiling_m=45_000.0))
        asked = [r["locations"] for r in world.requests if "exclude_locations" not in r]
        assert len(asked) == 3
        assert asked[0][0]["lon"] == BASE[0] and asked[2][1]["lon"] == pytest.approx(BASE[0] + EAST)
        assert asked[0][1] == asked[1][0] and asked[1][1] == asked[2][0]
        for a, b in asked:
            assert a["type"] == b["type"] == "break"
        assert info["long"]["legs"] == 3 and info["long"]["stops"] == [3]
        # The busy stretch (12 to 14.5 km) is not where a leg ends.
        assert all(not 12_000 < (lon - BASE[0]) / 1e-5 < 14_500 for lon in cut_lons())

    def test_each_legs_route_is_read_for_its_stress_alone_first(self, monkeypatch) -> None:
        world = legs_world(monkeypatch)
        refine.refine_long(whole_trip(), long_context(ceiling_m=45_000.0))
        firsts = [a for a in world.analysed if a[0] in ("L0", "L1", "L2")][:3]
        assert firsts == [("L0", False), ("L1", False), ("L2", False)]
        assert world.analysed[0] == ("whole", False)

    def test_the_worst_leg_is_searched_first_and_a_calm_leg_not_at_all(self, monkeypatch) -> None:
        world = legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        # (the reading of a search's route is in world.readings)
        world.readings["L1c"] = analysis("L1c", "1" * 133)
        order = []
        real = refine.refine

        def spy(trip, ctx):
            order.append((trip["legs"][0]["shape"], ctx.ceiling_m))
            return real(trip, ctx)

        monkeypatch.setattr(refine, "refine", spy)
        trip, info = refine.refine_long(whole_trip(), long_context(ceiling_m=45_000.0))
        assert [name for name, _ in order] == ["L1", "L2"]
        assert info["long"]["searched"] == 2 and "L0" not in [n for n, _ in order]

    def test_each_leg_may_use_all_the_detour_the_whole_has(self, monkeypatch) -> None:
        legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        caps = []
        real = refine.refine

        def spy(trip, ctx):
            caps.append((round(ctx.ceiling_m), ctx.options is not None))
            return real(trip, ctx)

        monkeypatch.setattr(refine, "refine", spy)
        refine.refine_long(whole_trip(), long_context(ceiling_m=41_000.0))
        # Leg lengths 13.3 km each (39.9), 1.1 km to spare: any one leg may use it all,
        # and it is shared out afterwards (`choose_options`).
        assert caps == [(14_400, True), (14_400, True)]

    def test_a_legs_search_has_no_price_on_distance_of_its_own(self, monkeypatch) -> None:
        """OWNER-DECISIONS 268, 271: the target is the whole trip's, so the legs keep
        every option and the whole trip prices them (`choose_options`)."""
        legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        seen = []
        real = refine.refine

        def spy(trip, ctx):
            seen.append((ctx.worth_rule, ctx.target_m))
            return real(trip, ctx)

        monkeypatch.setattr(refine, "refine", spy)
        ctx = long_context(ceiling_m=50_000.0, target_m=40_000.0)
        refine.refine_long(whole_trip(), ctx)
        assert seen and all(got == (False, None) for got in seen)
        assert ctx.worth_rule is True and ctx.target_m == 40_000.0

    def test_the_detour_goes_where_it_buys_the_most(self, monkeypatch) -> None:
        # L1's search finds a route 0.6 km longer that clears its LTS 4 and LTS 3; L2's
        # finds one 0.6 km longer that clears 2,000 m of LTS 3. With 0.7 km to spare only
        # one can be taken: L1's buys the LTS 4, which counts first.
        def world(ceiling_m):
            w = legs_world(
                monkeypatch,
                {
                    1: [("L1c", 13.9, None)],
                    2: [("L2c", 13.9, None)],
                },
            )
            w.readings["L1c"] = with_(analysis("L1c", "1" * 133), length_m=13_900.0)
            w.readings["L2c"] = with_(analysis("L2c", "1" * 133), length_m=13_900.0)
            return refine.refine_long(whole_trip(), long_context(ceiling_m=ceiling_m))

        trip, _info = world(40_600.0)
        assert [leg["shape"] for leg in trip["legs"]] == ["L0", "L1c", "L2"]
        assert trip["summary"]["length"] * 1000.0 <= 40_600.0
        # With room for both, both are taken.
        trip, _info = world(41_100.0)
        assert [leg["shape"] for leg in trip["legs"]] == ["L0", "L1c", "L2c"]

    def test_the_whole_is_never_past_the_longest_ride(self, monkeypatch) -> None:
        legs_world(
            monkeypatch,
            {1: [("L1c", 13.5, None)], 2: [("L2c", 14.0, analysis("L2c", "1" * 133))]},
        )
        trip, info = refine.refine_long(whole_trip(), long_context(ceiling_m=41_000.0))
        length = sum(float(t) for t in [trip["summary"]["length"]]) * 1000.0
        assert length <= 41_000.0 and info["long"]["answered"] == "legs"
        assert length == pytest.approx(13_300 + 13_500 + 14_000)

    def test_a_search_route_past_a_legs_share_is_not_taken(self, monkeypatch) -> None:
        world = legs_world(
            monkeypatch,
            {
                1: [("L1c", 13.5, None)],
                2: [("L2c", 14.6, analysis("L2c", "1" * 133))] * 5,
            },
        )
        trip, info = refine.refine_long(whole_trip(), long_context(ceiling_m=41_000.0))
        shapes = [leg["shape"] for leg in trip["legs"]]
        assert shapes == ["L0", "L1c", "L2"]
        assert trip["summary"]["length"] * 1000.0 <= 41_000.0
        assert world.requests

    def test_the_legs_are_put_back_as_one_trip(self, monkeypatch) -> None:
        legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        trip, info = refine.refine_long(whole_trip(), long_context(ceiling_m=45_000.0))
        assert [leg["shape"] for leg in trip["legs"]] == ["L0", "L1c", "L2"]
        assert trip["summary"]["length"] == pytest.approx(13.3 + 13.5 + 13.3)
        assert trip["summary"]["time"] > 0 and trip["summary"]["min_lat"] == 1.0
        assert info["long"]["answered"] == "legs"
        assert info["extra_distance_m"] == pytest.approx(13_300 + 13_500 + 13_300 - 40_000)
        assert info["lts4_m_before"] == 0.0 or info["lts3_m_before"] == 2500.0

    def test_the_figures_are_the_wholes_before_and_the_legs_after(self, monkeypatch) -> None:
        legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        _trip, info = refine.refine_long(whole_trip(), long_context(ceiling_m=45_000.0))
        assert info["lts3_m_before"] == 2500.0
        assert (
            info["lts3_m_after"] == 2000.0 + 0.0
        )  # L2's 2,000 m stay, L1's 1,000 m and 100 m LTS 4 go
        assert info["lts4_m_before"] == 0.0 and info["lts4_m_after"] == 0.0

    def test_nothing_changed_answers_the_routers_own_route(self, monkeypatch) -> None:
        legs_world(monkeypatch, {})
        whole = whole_trip()
        trip, info = refine.refine_long(whole, long_context(ceiling_m=45_000.0))
        assert trip is whole and info["long"]["answered"] == "router"
        assert info["extra_distance_m"] == 0.0

    def test_legs_not_as_calm_as_the_whole_answer_the_whole(self, monkeypatch) -> None:
        world = legs_world(monkeypatch, {})
        world.readings["L1"] = analysis("L1", "4" * 20 + "1" * 113)
        whole = whole_trip()
        trip, info = refine.refine_long(whole, long_context(ceiling_m=45_000.0))
        assert trip is whole and info["long"]["answered"] == "router"

    def test_legs_one_of_which_is_worse_than_the_whole_are_not_answered(self, monkeypatch) -> None:
        """A leg's own first route with LTS 4 the whole route does not have: another leg's
        better search must not carry it into the answer."""
        world = legs_world(monkeypatch, {2: [("L2c", 13.5, None)]})
        world.readings["L1"] = analysis("L1", "4" * 20 + "1" * 113)
        world.readings["L2c"] = analysis("L2c", "1" * 133)
        whole = whole_trip()
        trip, info = refine.refine_long(whole, long_context(ceiling_m=45_000.0))
        assert trip is whole and info["long"]["answered"] == "router"
        assert info["lts4_m_after"] == info["lts4_m_before"]

    def test_a_leg_the_router_cannot_route_gives_the_wholes(self, monkeypatch) -> None:
        def refuse(variant, endpoint, payload, deadline):
            raise routing.RouterRefused(400, 171, "no")

        legs_world(monkeypatch)
        monkeypatch.setattr(routing, "_call", refuse)
        whole = whole_trip()
        trip, info = refine.refine_long(whole, long_context(ceiling_m=45_000.0))
        assert trip is whole and info["limited"] == "split"

    def test_too_little_time_to_start_leaves_the_route(self, monkeypatch) -> None:
        legs_world(monkeypatch)
        ctx = long_context(ceiling_m=45_000.0)
        ctx.deadline = routing.Deadline(routing.clock() + refine.LONG_MIN_START_S - 1, 45)
        whole = whole_trip()
        trip, info = refine.refine_long(whole, ctx)
        assert trip is whole and info["limited"] == "time" and "long" not in info

    def test_a_leg_the_time_does_not_reach_keeps_the_routers_route(self, monkeypatch) -> None:
        legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        ctx = long_context(ceiling_m=45_000.0)
        # 13 s from the start, less the 6 s kept for the whole's junctions: 7 s.
        ctx.deadline = routing.Deadline(routing.clock() + 13.0, 45)
        trip, info = refine.refine_long(whole_trip(), ctx)
        # The worst leg's share is under a round; the last has the whole of what is left.
        assert info["limited"] == "time" and info["long"]["skipped"] == 1
        assert info["long"]["searched"] == 1

    def test_the_time_is_shared_by_weight(self, monkeypatch) -> None:
        legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        shares = []
        real = refine.refine

        def spy(trip, ctx):
            shares.append(round(ctx.stop_at - routing.clock(), 1))
            return real(trip, ctx)

        monkeypatch.setattr(refine, "refine", spy)
        refine.refine_long(whole_trip(), long_context(ceiling_m=45_000.0))
        # About 41 s to share (47 less 6), L1's 1,800 of 3,800: 19.4 s.
        assert shares[0] == pytest.approx(41 * 1800 / 3800, abs=1.0)

    def test_two_stops_are_cut_separately(self, monkeypatch) -> None:
        world = legs_world(monkeypatch)
        ctx = long_context(ceiling_m=45_000.0)
        mid = BASE[0] + EAST / 2
        ctx.points = [ctx.points[0], [mid, BASE[1]], ctx.points[1]]
        ctx.request["locations"] = [
            ctx.request["locations"][0],
            {"lon": mid, "lat": BASE[1], "type": "break"},
            ctx.request["locations"][1],
        ]
        whole = whole_trip()
        whole_read = long_whole()
        whole_read.via_m = [20_000.0]
        world.readings["whole"] = whole_read
        refine.refine_long(whole, ctx)
        assert [r for r in world.requests if "exclude_locations" not in r]

    def test_the_hold_is_per_leg_and_the_top_figure(self, monkeypatch) -> None:
        legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        seen = []
        real = refine.refine

        def spy(trip, ctx):
            ctx.exposure = AVERSE
            out = real(trip, ctx)
            seen.append(list(ctx.first_lts4))
            return out

        monkeypatch.setattr(refine, "refine", spy)
        refine.refine_long(whole_trip(), long_context(ceiling_m=45_000.0))
        assert seen[0] == [100.0]


class TestTheMergedSeek:
    def test_counts_add_and_rows_are_named_by_leg(self) -> None:
        a = {
            "corridors": 2,
            "asked": 1,
            "routes": 2,
            "taken": False,
            "limited": None,
            "tried": [{"outcome": "x"}],
        }
        b = {
            "corridors": 1,
            "asked": 1,
            "routes": 1,
            "taken": True,
            "limited": "time",
            "tried": [{"outcome": "y"}],
        }
        merged = refine._merge_seek([(1, a), (3, b)])
        assert merged["corridors"] == 3 and merged["asked"] == 2 and merged["routes"] == 3
        assert merged["taken"] is True and merged["limited"] == "time"
        assert [r["leg"] for r in merged["tried"]] == [1, 3] and merged["legs"] == 2

    def test_none_ran_is_none(self) -> None:
        assert refine._merge_seek([]) is None


class TestJoinedTrip:
    def test_summaries_add_up_and_other_keys_are_the_originals(self) -> None:
        like = {"summary": {"length": 9.0, "time": 1.0, "cost": 2.0, "min_lon": 5.0}, "x": 1}
        a = {"legs": [{"shape": "a"}], "summary": {"length": 1.0, "time": 10.0, "cost": 20.0}}
        b = {"legs": [{"shape": "b"}], "summary": {"length": 2.0, "time": 5.0, "cost": 6.0}}
        out = refine._joined([a, b], like)
        assert out["summary"] == {"length": 3.0, "time": 15.0, "cost": 26.0, "min_lon": 5.0}
        assert [leg["shape"] for leg in out["legs"]] == ["a", "b"] and out["x"] == 1


class TestTheLegsOfTheAnswer:
    def test_a_plan_legs_runs_are_one_run_of_pieces(self) -> None:
        assert routing._joined_runs([(0, 5), (5, 9), (9, 12)], []) == (0, 12)

    def test_an_untraced_leg_makes_the_plan_leg_a_length(self) -> None:
        pieces = [routing.Piece(1, 0.0, 0.0, 100.0) for _ in range(5)]
        assert routing._joined_runs([(0, 3), 1500.0], pieces) == 1800.0
        assert routing._joined_runs([1000.0, 2000.0], pieces) == 3000.0


# --- Sharing the detour among the legs ------------------------------------------------


def option(name: str, tiers: str, km: float) -> tuple:
    return ({"legs": [{"shape": name}]}, with_(analysis(name, tiers), length_m=km * 1000.0))


class TestTheFrontier:
    ctx = top_context()

    def test_each_option_on_it_is_calmer_and_longer_than_the_one_before(self) -> None:
        first = option("f", "1" * 10 + "3" * 20 + "1" * 10, 4.0)
        middle = option("m", "1" * 10 + "3" * 10 + "1" * 20, 4.5)
        calm = option("c", "1" * 40, 5.5)
        waste = option(
            "w", "1" * 10 + "3" * 15 + "1" * 15, 6.0
        )  # longer, not calmer than the middle
        chain = refine.frontier([first, calm, waste, middle], self.ctx)
        assert [o[0]["legs"][0]["shape"] for o in chain] == ["f", "m", "c"]

    def test_an_option_no_better_than_the_first_is_left_out(self) -> None:
        first = option("f", "1" * 40, 4.0)
        worse = option("w", "1" * 10 + "3" * 5 + "1" * 25, 4.2)
        assert [o[0]["legs"][0]["shape"] for o in refine.frontier([first, worse], self.ctx)] == [
            "f"
        ]

    def test_a_shorter_route_as_calm_replaces_the_first(self) -> None:
        first = option("f", "1" * 10 + "3" * 20 + "1" * 10, 4.5)
        shorter = option("s", "1" * 10 + "3" * 10 + "1" * 20, 4.0)
        chain = refine.frontier([first, shorter], self.ctx)
        assert [o[0]["legs"][0]["shape"] for o in chain] == ["s"]

    def test_an_upgrade_not_worth_its_miles_stays_on_it(self) -> None:
        """Whether it is worth them is the whole trip's to say (`choose_options`)."""
        first = option("f", "1" * 10 + "3" * 2 + "1" * 28, 4.0)
        dear = option("d", "1" * 40, 9.0)  # 5 km for 200 m of LTS 3
        chain = refine.frontier([first, dear], self.ctx)
        assert [o[0]["legs"][0]["shape"] for o in chain] == ["f", "d"]


class TestChoosingOptions:
    ctx = top_context()

    def chains(self):
        a = refine.frontier(
            [
                option("a0", "1" * 10 + "3" * 20 + "1" * 10, 10.0),
                option("a1", "1" * 10 + "3" * 16 + "1" * 14, 11.0),  # +1 km for -400 m
            ],
            self.ctx,
        )
        b = refine.frontier(
            [
                option("b0", "1" * 10 + "3" * 20 + "1" * 10, 10.0),
                option("b1", "1" * 10 + "3" * 12 + "1" * 18, 11.0),  # +1 km for -800 m
            ],
            self.ctx,
        )
        return [a, b]

    def test_the_metres_go_where_they_buy_the_most(self) -> None:
        picked = refine.choose_options(self.chains(), [10_000.0, 10_000.0], 21_000.0, self.ctx)
        assert picked == [0, 1]

    def test_with_room_for_both_both_are_taken(self) -> None:
        assert refine.choose_options(self.chains(), [10_000.0, 10_000.0], 22_000.0, self.ctx) == [
            1,
            1,
        ]

    def test_with_no_room_nothing_changes(self) -> None:
        assert refine.choose_options(self.chains(), [10_000.0, 10_000.0], 20_500.0, self.ctx) == [
            0,
            0,
        ]

    def test_with_no_limit_the_calmest_is_taken(self) -> None:
        assert refine.choose_options(self.chains(), [10_000.0, 10_000.0], None, self.ctx) == [1, 1]

    def test_seeking_climbs_buys_no_miles_here_either(self) -> None:
        """The re-check S1 probe as a one-leg chain (the mutation re-check's SF1): 20 km flat
        with 1 km of LTS 3 against 40 km hilly (effort 60 km) with none, Hills at full seek and
        no target. The even-out step charges the 20 km added as at the detent, so the 1 km saved
        does not pay for it."""
        ctx = top_context()
        ctx.hills_seek_weight = 1.0
        short = reading(length=20_000.0, effort=20_000.0, lts3=1_000.0)
        long_ = reading(length=40_000.0, effort=60_000.0)
        chain = [({"legs": [{"shape": "s"}]}, short), ({"legs": [{"shape": "l"}]}, long_)]
        assert refine.choose_options([chain], [20_000.0], None, ctx) == [0]

    def test_a_free_upgrade_is_taken_though_it_saves_no_stress(self) -> None:
        """The `charge > 0.0` guard (the mutation re-check's N4): under a target the miles
        are free (268, 271), so an option that ranks better on the blended distance (much
        flatter, with Hills set to avoid) is taken though it carries 10 m more LTS 3."""
        ctx = top_context(target_m=20_000.0)
        ctx.hills_weight = 1.0
        hilly = reading(length=10_000.0, effort=30_000.0, lts3=100.0)
        flat = reading(length=11_000.0, effort=11_000.0, lts3=110.0)
        assert refine.stress_saved_m(hilly, flat, ctx) < 0, "the premise: no stress saved"
        chain = [({"legs": [{"shape": "h"}]}, hilly), ({"legs": [{"shape": "f"}]}, flat)]
        assert refine.choose_options([chain], [10_000.0], None, ctx) == [1]

    def test_the_total_is_never_past_the_limit(self) -> None:
        chains = self.chains()
        for limit in (20_000.0, 20_999.0, 21_000.0, 21_999.0, 22_000.0):
            picked = refine.choose_options(chains, [10_000.0, 10_000.0], limit, self.ctx)
            total = sum(c[p][1].length_m for c, p in zip(chains, picked, strict=True))
            assert total <= limit, limit

    def test_lts4_is_bought_before_lts3(self) -> None:
        lts3 = refine.frontier(
            [option("x0", "1" * 10 + "3" * 20 + "1" * 10, 10.0), option("x1", "1" * 40, 11.0)],
            self.ctx,
        )
        lts4 = refine.frontier(
            [option("y0", "1" * 10 + "4" * 2 + "1" * 28, 10.0), option("y1", "1" * 40, 11.0)],
            self.ctx,
        )
        # 1 km of detour either clears 2,000 m of LTS 3 or 200 m of LTS 4: the LTS 4.
        assert refine.choose_options([lts3, lts4], [10_000.0, 10_000.0], 21_000.0, self.ctx) == [
            0,
            1,
        ]

    def test_a_shorter_start_is_free(self) -> None:
        chain = refine.frontier(
            [
                option("f", "1" * 10 + "3" * 20 + "1" * 10, 10.0),
                option("s", "1" * 10 + "3" * 10 + "1" * 20, 9.5),
            ],
            self.ctx,
        )
        assert refine.choose_options([chain], [10_000.0], 10_000.0, self.ctx) == [0]
        assert chain[0][1].length_m == 9500.0

    def dear(self):
        """A leg whose upgrade adds 2 km for 300 m of LTS 3: under 1 in 5 (400 m
        needed), over 1 in 2.5 only where none of it is past a target."""
        return refine.frontier(
            [
                option("d0", "1" * 10 + "3" * 3 + "1" * 27, 10.0),
                option("d1", "1" * 40, 12.0),
            ],
            self.ctx,
        )

    def test_an_upgrade_not_worth_its_miles_is_not_taken(self) -> None:
        """OWNER-DECISIONS 268: about 1 mi of LTS 3 saved per 5 mi added."""
        assert refine.choose_options([self.dear()], [10_000.0], 16_000.0, self.ctx) == [0]
        # The same upgrade at 1 in 5 or better is taken.
        worth = refine.frontier(
            [option("w0", "1" * 10 + "3" * 4 + "1" * 26, 10.0), option("w1", "1" * 40, 12.0)],
            self.ctx,
        )
        assert refine.choose_options([worth], [10_000.0], 16_000.0, self.ctx) == [1]

    def test_under_the_target_the_miles_are_free(self) -> None:
        ctx = top_context(target_m=12_000.0, ceiling_m=15_000.0)
        assert refine.choose_options([self.dear()], [10_000.0], 15_000.0, ctx) == [1]

    def test_past_the_target_the_bar_is_stricter(self) -> None:
        # 1 km past an 11 km target needs 400 m: 300 m is not enough.
        ctx = top_context(target_m=11_000.0, ceiling_m=13_750.0)
        assert refine.choose_options([self.dear()], [10_000.0], 13_750.0, ctx) == [0]
        # Half a kilometre past it needs 200 m: 300 m is.
        ctx = top_context(target_m=11_500.0, ceiling_m=14_375.0)
        assert refine.choose_options([self.dear()], [10_000.0], 14_375.0, ctx) == [1]

    def test_the_charge_is_at_the_whole_trips_length(self) -> None:
        # With a 10 km fixed leg the same upgrade is 2 km past a 20 km target.
        ctx = top_context(target_m=20_000.0, ceiling_m=25_000.0)
        assert refine.choose_options([self.dear()], [10_000.0], 25_000.0, ctx, 10_000.0) == [0]
        assert refine.choose_options([self.dear()], [10_000.0], 25_000.0, ctx, 8_000.0) == [1]

    def test_the_legs_with_no_choice_count_against_the_limit(self) -> None:
        # 10 km of fixed leg: 21,000 less 10,000 leaves 11,000 for two 10 km legs: no room.
        chains = self.chains()
        assert refine.choose_options(
            chains, [10_000.0, 10_000.0], 31_000.0, self.ctx, 10_000.0
        ) == [0, 1]
        assert refine.choose_options(
            chains, [10_000.0, 10_000.0], 30_500.0, self.ctx, 10_000.0
        ) == [0, 0]


# --- Routes to choose from (OWNER-DECISIONS 265) -------------------------------------------


def road(name: str, ways: list[int], tiers: str | None = None, km: float | None = None):
    """A candidate: a route over these ways, 1,000 m each, with tiers one letter a way."""
    tiers = tiers or "1" * len(ways)
    pieces = [routing.Piece(w, BASE[0] + i * 1e-3, BASE[1], 1000.0) for i, w in enumerate(ways)]
    classes = [(t, "none") for t in tiers]
    read = refine.Analysis(
        length_m=1000.0 * len(ways) if km is None else km * 1000.0,
        cost_s=1.0,
        exposure_m=0.0,
        climb_m=0.0,
        pieces=pieces,
        classes=classes,
        events=[],
        lts4_m=1000.0 * sum(t in "45" for t in tiers),
        lts3_m=1000.0 * tiers.count("3"),
    )
    return ({"legs": [{"shape": name}]}, read)


def names(chosen) -> list[str]:
    return [trip["legs"][0]["shape"] for trip, _read in chosen]


def alt_context(**kw) -> refine.Context:
    ctx = top_context(**kw)
    ctx.alternates = refine.ALT_MAX
    return ctx


class TestDifferentRoutes:
    """A route is only added if it is meaningfully different from every one chosen."""

    def test_the_threshold_is_70_percent_of_the_road_or_5_miles_different(self) -> None:
        """OWNER-DECISIONS 269, "Loosen a little (Recommended)": 70%, from 60%."""
        assert refine.ALT_OVERLAP == 0.70
        assert refine.ALT_DIFFERENT_M == pytest.approx(5 * 1609.344, rel=0.01)
        assert refine.ALT_MAX == 4

    def test_the_shared_road_is_matched_by_way(self) -> None:
        a = road("a", [1, 2, 3, 4])[1]
        b = road("b", [3, 4, 5, 6])[1]
        assert refine.shared_m(a, b) == 2000.0 and refine.shared_m(b, a) == 2000.0
        assert refine.shared_m(a, road("c", [9, 8])[1]) == 0.0

    def test_a_route_over_the_same_road_is_not_different(self) -> None:
        a = road("a", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])[1]
        near = road("n", [1, 2, 3, 4, 5, 6, 7, 8, 11, 12])[1]  # 80% shared, 2 km different
        assert not refine.distinct_from(near, [a])

    def test_a_route_over_less_than_70_percent_of_it_is_different(self) -> None:
        a = road("a", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])[1]
        far = road("f", [1, 2, 3, 4, 5, 11, 12, 13, 14, 15])[1]  # 50% shared
        assert refine.distinct_from(far, [a])
        sixty = road("s", [1, 2, 3, 4, 5, 6, 11, 12, 13, 14])[1]  # 60% shared: now different
        assert refine.distinct_from(sixty, [a])
        edge = road("e", [1, 2, 3, 4, 5, 6, 7, 11, 12, 13])[1]  # exactly 70% shared
        assert not refine.distinct_from(edge, [a])

    def test_a_different_corridor_over_a_stretch_counts_on_a_long_route(self) -> None:
        """70% of a 58 mi route is never different: 5 mi of different road is."""
        ways = list(range(1, 61))
        a = road("a", ways)[1]
        swap = road("s", ways[:20] + list(range(100, 109)) + ways[29:])[1]  # 9 km different
        assert refine.shared_m(swap, a) / 60_000.0 > 0.8
        assert refine.distinct_from(swap, [a])
        small = road("t", ways[:20] + list(range(100, 104)) + ways[24:])[1]  # 4 km different
        assert not refine.distinct_from(small, [a])

    def test_it_must_differ_from_every_one_already_chosen(self) -> None:
        a = road("a", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])[1]
        b = road("b", [1, 2, 3, 4, 5, 11, 12, 13, 14, 15])[1]
        c = road("c", [1, 2, 3, 4, 5, 11, 12, 13, 14, 16])[1]  # different from a, not from b
        assert refine.distinct_from(c, [a]) and not refine.distinct_from(c, [a, b])

    def test_an_empty_route_is_never_different(self) -> None:
        empty = road("e", [])[1]
        assert not refine.distinct_from(empty, [road("a", [1, 2])[1]])


class TestPickingCandidates:
    ctx = alt_context(ceiling_m=20_000.0)

    def pool(self, *extra):
        return [road("main", [1, 2, 3, 4, 5, 6, 7, 8]), *extra]

    def test_a_trip_with_one_obvious_corridor_returns_a_single_route(self) -> None:
        pool = self.pool(
            road("dup1", [1, 2, 3, 4, 5, 6, 7, 9]), road("dup2", [1, 2, 3, 4, 5, 6, 10, 11])
        )
        assert names(refine.pick_candidates(pool, self.ctx, [0.0])) == ["main"]
        assert names(refine.pick_candidates(self.pool(), self.ctx, [0.0])) == ["main"]
        assert refine.pick_candidates([], self.ctx, [0.0]) == []

    def test_different_corridors_are_added_in_the_stress_order(self) -> None:
        pool = self.pool(
            road("calmer-b", [11, 12, 13, 14, 15, 16, 17, 18]),
            road("calm-c", [21, 22, 23, 24, 25, 26, 27, 28]),
        )
        # (all tier 1; ties are ordered by distance, and equal here, so by position)
        got = refine.pick_candidates(pool, self.ctx, [0.0])
        assert names(got) == ["main", "calmer-b", "calm-c"]

    def test_the_candidates_are_ranked_by_the_stress_order_after_the_answer(self) -> None:
        main = road("main", [1, 2, 3, 4, 5, 6, 7, 8], "1" * 8)
        slightly = road("b", [11, 12, 13, 14, 15, 16, 17, 18], "1" * 7 + "3")  # 1 km of LTS 3
        flat = road("c", [21, 22, 23, 24, 25, 26, 27, 28], "1" * 8, km=7.5)  # shorter, same stress
        slightly[1].lts3_m = 250.0  # within the band, so it is offered, after the shorter one
        got = refine.pick_candidates([main, slightly, flat], self.ctx, [0.0])
        assert names(got) == ["main", "c", "b"]

    def test_each_is_within_the_longest_ride(self) -> None:
        pool = self.pool(road("long", [11, 12, 13, 14, 15, 16, 17, 18], km=20.5))
        assert names(refine.pick_candidates(pool, self.ctx, [0.0])) == ["main"]
        ok = self.pool(road("fits", [11, 12, 13, 14, 15, 16, 17, 18], km=20.0))
        assert names(refine.pick_candidates(ok, self.ctx, [0.0])) == ["main", "fits"]

    def test_each_passes_the_hold_on_the_top_figure(self) -> None:
        ctx = alt_context(ceiling_m=20_000.0)
        ctx.exposure = AVERSE
        main = road("main", [1, 2, 3, 4, 5, 6, 7, 8], "1" * 6 + "44")
        more = road("more", [11, 12, 13, 14, 15, 16, 17, 18], "1" * 5 + "444")
        same = road("same", [21, 22, 23, 24, 25, 26, 27, 28], "1" * 6 + "44")
        reference = refine.top_by_leg(main[1])
        got = refine.pick_candidates([main, more, same], ctx, reference)
        assert names(got) == ["main", "same"]

    def test_each_is_a_near_tie_with_the_answer_on_stress(self) -> None:
        main = road("main", [1, 2, 3, 4, 5, 6, 7, 8], "1" * 8)
        worse4 = road("w4", [11, 12, 13, 14, 15, 16, 17, 18], "1" * 7 + "4")  # 1 km of LTS 4
        worse3 = road("w3", [21, 22, 23, 24, 25, 26, 27, 28], "1" * 5 + "333")  # 3 km of LTS 3
        near3 = road(
            "n3", [31, 32, 33, 34, 35, 36, 37, 38], "1" * 7 + "3"
        )  # 1 km: within 800 m? no
        got = refine.pick_candidates([main, worse4, worse3, near3], self.ctx, [0.0])
        assert names(got) == ["main"]
        assert refine.ALT_TOP_BAND_M == 150.0 and refine.ALT_SECOND_BAND_M == 800.0

    def test_the_near_tie_bands_are_500_ft_and_half_a_mile(self) -> None:
        """OWNER-DECISIONS 287(4), "Loosen a bit (Recommended)": the top figure within
        about 150 m (500 ft) of the answer's, the second within about 800 m (0.5 mi), from
        45 m and 300 m, so that more genuine alternates show."""
        main = road("main", [1, 2, 3, 4, 5, 6, 7, 8], "1" * 8)

        def other(**fields):
            trip, read = road("b", [11, 12, 13, 14, 15, 16, 17, 18], "1" * 8)
            return trip, with_(read, **fields)

        for fields, offered in (
            ({"lts4_m": 150.0}, True),
            ({"lts4_m": 151.0}, False),
            ({"lts4_m": 100.0}, True),
            ({"lts3_m": 800.0}, True),
            ({"lts3_m": 801.0}, False),
            ({"lts3_m": 500.0}, True),
        ):
            got = refine.pick_candidates([main, other(**fields)], self.ctx, [0.0])
            assert (names(got) == ["main", "b"]) is offered, fields

    def test_a_route_whose_junctions_could_not_be_read_is_not_offered(self) -> None:
        unread = road("u", [11, 12, 13, 14, 15, 16, 17, 18])
        unread[1].events = None
        assert names(refine.pick_candidates(self.pool(unread), self.ctx, [0.0])) == ["main"]

    def test_at_most_four_in_all(self) -> None:
        extras = [road(f"x{i}", list(range(100 * i, 100 * i + 8))) for i in range(1, 8)]
        got = refine.pick_candidates(self.pool(*extras), self.ctx, [0.0])
        assert len(got) == refine.ALT_MAX == 4 and got[0][0]["legs"][0]["shape"] == "main"

    def test_without_a_request_for_more_it_is_the_answer_alone(self) -> None:
        ctx = top_context(ceiling_m=20_000.0)
        pool = self.pool(road("b", [11, 12, 13, 14, 15, 16, 17, 18]))
        assert names(refine.pick_candidates(pool, ctx, [0.0])) == ["main"]

    def test_the_answer_is_always_first_whatever_it_ranks(self) -> None:
        main = road("main", [1, 2, 3, 4, 5, 6, 7, 8], "1" * 7 + "3")
        better = road("better", [11, 12, 13, 14, 15, 16, 17, 18], "1" * 8)
        assert names(refine.pick_candidates([main, better], self.ctx, [0.0]))[0] == "main"


class TestCombiningLegs:
    def test_the_figures_add_and_the_pieces_follow_in_order(self) -> None:
        a = road("a", [1, 2], "13")[1]
        b = road("b", [3, 4, 5], "441")[1]
        whole = refine.combine([a, b])
        assert whole.length_m == 5000.0 and whole.lts3_m == 1000.0 and whole.lts4_m == 2000.0
        assert [p.way_id for p in whole.pieces] == [1, 2, 3, 4, 5]
        assert whole.via_m == [2000.0] and len(whole.classes) == 5

    def test_a_leg_without_junctions_adds_none(self) -> None:
        a = road("a", [1, 2])[1]
        a.events = None
        b = road("b", [3])[1]
        b.events = [event(100.0, 3000.0)]
        assert len(refine.combine([a, b]).events) == 1


class TestTheSearchOffersCandidates:
    def test_a_search_with_options_picks_candidates_from_what_it_read(self, monkeypatch) -> None:
        ctx = alt_context(ceiling_m=9_000.0)
        ctx.options = []
        orig = analysis("o", ORIG)
        calm = analysis("c", "1" * 40)
        World(monkeypatch, {"o": orig, "c": calm}, [trip_of("c", 4.2)] * 4)
        kept, _info = refine.refine(trip_of("o", 4.0), ctx)
        assert kept["legs"][0]["shape"] == "c"
        # The answer first; the first route is the same road as `c` here (every piece
        # is way 1 in these readings), so it is not offered as different.
        assert ctx.candidates[0][0]["legs"][0]["shape"] == "c"
        assert len(ctx.candidates) == 1
        # The hold they were picked by, for picking them again after the dodge pass.
        assert ctx.candidate_reference == ctx.first_lts4

    def test_no_options_no_candidates(self, monkeypatch) -> None:
        ctx = alt_context()
        World(monkeypatch, {"o": analysis("o", ORIG)}, [trip_of("o", 4.0)] * 2)
        refine.refine(trip_of("o", 4.0), ctx)
        assert ctx.candidates == []

    def test_the_first_route_is_an_option(self, monkeypatch) -> None:
        ctx = alt_context(ceiling_m=9_000.0)
        ctx.options = []
        World(monkeypatch, {"o": analysis("o", ORIG)}, [trip_of("o", 4.0)] * 2)
        refine.refine(trip_of("o", 4.0), ctx)
        assert ctx.options and ctx.options[0][0]["legs"][0]["shape"] == "o"


class TestALongPlanOffersCandidates:
    def test_a_swapped_leg_is_a_candidate_when_it_is_a_different_corridor(
        self, monkeypatch
    ) -> None:
        world = legs_world(
            monkeypatch,
            {
                1: [("L1c", 13.5, None), ("L1d", 13.6, None)],
                2: [],
            },
        )

        # Two different calm routes over leg 1, over different ways.
        def over(name, base):
            read = analysis(name, "1" * 133)
            read.pieces = [
                routing.Piece(base + i, p.lon, p.lat, p.metres) for i, p in enumerate(read.pieces)
            ]
            return with_(read, length_m=float(name[-1] == "c" and 13_500 or 13_600))

        world.readings["L1c"] = over("L1c", 1000)
        world.readings["L1d"] = over("L1d", 5000)
        ctx = long_context(ceiling_m=45_000.0)
        ctx.alternates = refine.ALT_MAX
        trip, _info = refine.refine_long(whole_trip(), ctx)
        shapes = [[leg["shape"] for leg in t["legs"]] for t, _r in ctx.candidates]
        assert shapes[0] == ["L0", "L1c", "L2"] or shapes[0] == ["L0", "L1d", "L2"]
        assert len(ctx.candidates) <= refine.ALT_MAX
        for candidate_trip, read in ctx.candidates:
            assert read.length_m <= 45_000.0
            assert len(candidate_trip["legs"]) == 3
        assert len(ctx.candidate_reference) == 1, "the whole plan's top figure"

    def test_a_plan_with_no_alternates_asked_has_none(self, monkeypatch) -> None:
        legs_world(monkeypatch, {1: [("L1c", 13.5, None)], 2: []})
        ctx = long_context(ceiling_m=45_000.0)
        refine.refine_long(whole_trip(), ctx)
        assert ctx.candidates == []


class TestAskingForAnotherWay:
    """Where the search read nothing different enough, the router is asked for a route that
    avoids the roads of those chosen (`refine.more_routes`)."""

    def main(self):
        return road("main", [1, 2, 3, 4, 5, 6, 7, 8])

    def world(self, monkeypatch, replies, **readings):
        analyses = {"main": self.main()[1], **{k: v[1] for k, v in readings.items()}}
        return World(monkeypatch, analyses, replies)

    def test_the_roads_chosen_are_excluded_and_a_different_near_tie_is_added(
        self, monkeypatch
    ) -> None:
        world = self.world(
            monkeypatch,
            [trip_of("alt", 8.0), routing.RouterRefused(400, 442, "no path")],
            alt=road("alt", list(range(11, 19))),
        )
        ctx = alt_context(ceiling_m=20_000.0)
        got = refine.more_routes([self.main()], ctx, [0.0])
        assert names(got) == ["main", "alt"]
        first = world.requests[0]
        assert "alternates" not in first
        main_lons = {p.lon for p in self.main()[1].pieces}
        asked = [p["lon"] for p in first["exclude_locations"]]
        assert asked and all(lon in main_lons for lon in asked), "points on the route chosen"
        assert len(world.requests) == 2

    def test_each_ask_excludes_the_roads_of_every_route_chosen_so_far(self, monkeypatch) -> None:
        world = self.world(
            monkeypatch,
            [trip_of("b", 8.0), trip_of("c", 8.0), trip_of("d", 8.0)],
            b=road("b", list(range(11, 19))),
            c=road("c", list(range(21, 29))),
            d=road("d", list(range(31, 39))),
        )
        got = refine.more_routes([self.main()], alt_context(ceiling_m=20_000.0), [0.0])
        assert names(got) == ["main", "b", "c", "d"], "at most the four of ALT_MAX"
        sizes = [len(r["exclude_locations"]) for r in world.requests]
        assert sizes[0] < sizes[1] < sizes[2] and len(world.requests) == refine.ALT_ASKS == 3
        assert sizes[1] == pytest.approx(2 * sizes[0], abs=1) and sizes[2] == pytest.approx(
            3 * sizes[0], abs=1
        )

    def test_it_asks_no_more_than_ALT_ASKS_times_however_many_routes_are_wanted(
        self, monkeypatch
    ) -> None:
        replies = [trip_of(name, 8.0) for name in "bcdefg"]
        world = self.world(
            monkeypatch,
            replies,
            **{
                name: road(name, list(range(10 * i + 10, 10 * i + 18)))
                for i, name in enumerate("bcdefg", start=1)
            },
        )
        ctx = alt_context(ceiling_m=20_000.0)
        ctx.alternates = 8
        got = refine.more_routes([self.main()], ctx, [0.0])
        assert len(world.requests) == refine.ALT_ASKS == 3 and len(got) == 4

    def test_a_route_that_is_not_a_near_tie_ends_the_asking(self, monkeypatch) -> None:
        busy = road("busy", list(range(11, 19)), "1" * 5 + "444")
        world = self.world(monkeypatch, [trip_of("busy", 8.0), trip_of("busy", 8.0)], busy=busy)
        got = refine.more_routes([self.main()], alt_context(ceiling_m=20_000.0), [0.0])
        assert names(got) == ["main"] and len(world.requests) == 1

    def test_a_route_that_is_the_same_road_ends_it(self, monkeypatch) -> None:
        world = self.world(
            monkeypatch, [trip_of("same", 8.0)] * 3, same=road("same", [1, 2, 3, 4, 5, 6, 7, 9])
        )
        got = refine.more_routes([self.main()], alt_context(ceiling_m=20_000.0), [0.0])
        assert names(got) == ["main"] and len(world.requests) == 1

    def test_a_route_past_the_longest_ride_ends_it(self, monkeypatch) -> None:
        world = self.world(monkeypatch, [trip_of("far", 9.0)], far=road("far", list(range(11, 19))))
        got = refine.more_routes([self.main()], alt_context(ceiling_m=8_500.0), [0.0])
        assert names(got) == ["main"] and len(world.requests) == 1

    def test_a_refusal_or_an_unreachable_router_ends_it(self, monkeypatch) -> None:
        world = self.world(monkeypatch, [routing.RouterRefused(400, 442, "no path")])
        assert names(refine.more_routes([self.main()], alt_context(), [0.0])) == ["main"]
        assert len(world.requests) == 1
        self.world(monkeypatch, [routing.RouterUnavailable("down")])
        assert names(refine.more_routes([self.main()], alt_context(), [0.0])) == ["main"]

    def test_with_no_time_it_asks_nothing(self, monkeypatch) -> None:
        world = self.world(monkeypatch, [trip_of("alt", 8.0)], alt=road("alt", list(range(11, 19))))
        ctx = alt_context(ceiling_m=20_000.0)
        ctx.deadline = routing.Deadline(routing.clock() + refine.REFINE_TRACE_RESERVE_S + 1.0, 35)
        assert names(refine.more_routes([self.main()], ctx, [0.0])) == ["main"]
        assert world.requests == []

    def test_it_is_only_for_a_plan_that_offers_more_than_one(self, monkeypatch) -> None:
        world = self.world(monkeypatch, [trip_of("alt", 8.0)], alt=road("alt", list(range(11, 19))))
        assert names(refine.more_routes([self.main()], top_context(ceiling_m=20_000.0), [0.0])) == [
            "main"
        ]
        assert world.requests == []

    def test_a_route_with_no_junction_reading_is_not_offered(self, monkeypatch) -> None:
        unread = road("unread", list(range(11, 19)))
        unread[1].events = None
        world = self.world(monkeypatch, [trip_of("unread", 8.0)], unread=unread)
        got = refine.more_routes([self.main()], alt_context(ceiling_m=20_000.0), [0.0])
        assert names(got) == ["main"] and len(world.requests) == 1

    def test_the_search_asks_after_it_when_it_found_nothing_different(self, monkeypatch) -> None:
        ctx = alt_context(ceiling_m=9_000.0)
        ctx.options = []
        world = World(
            monkeypatch,
            {"o": analysis("o", ORIG), "x": road("x", list(range(101, 141)))[1]},
            [trip_of("o", 4.0)] * 3 + [trip_of("x", 4.2)],
        )
        refine.refine(trip_of("o", 4.0), ctx)
        assert any(r.get("exclude_locations") for r in world.requests), (
            "the last ask is `more_routes`"
        )
        assert refine.ALT_BUDGET_S > 0 and refine.ALT_SAMPLE_M == 150.0


class TestTheSeekLegsOwnDeadline:
    """A leg with less than a candidate's worth of time left reads no table and asks nothing
    (the check `_seek` makes before it does not cover a leg given a share of its own)."""

    def test_a_leg_with_under_a_round_left_does_not_read_its_table(self, monkeypatch) -> None:
        def table(*args, **kwargs):
            raise AssertionError("the table was read")

        monkeypatch.setattr(trailseek, "corridor_segments", table)
        ctx = context(rate=10.0)
        seek = {"limited": None, "corridors": 0, "asked": 0, "routes": 0, "tried": []}
        stop_at = routing.clock() + trailseek.SEEK_ROUND_MIN_S - 0.5
        got = refine._seek_leg(0, {"legs": []}, analysis("o"), 0.0, stop_at, ctx, seek)
        assert got is None and seek["limited"] == "time"

    def test_a_leg_with_a_round_left_reads_it(self, monkeypatch) -> None:
        read = []
        monkeypatch.setattr(trailseek, "corridor_segments", lambda *a, **k: read.append(1) or [])
        ctx = context(rate=10.0)
        seek = {"limited": None, "corridors": 0, "asked": 0, "routes": 0, "tried": []}
        stop_at = routing.clock() + trailseek.SEEK_ROUND_MIN_S + 5.0
        refine._seek_leg(0, {"legs": []}, analysis("o"), 0.0, stop_at, ctx, seek)
        assert read == [1]


class TestLTS4NeverLosesToExtraLTS3:
    """Combined spec review, SF2 (OWNER-DECISIONS 287(1): "LTS 4 still ranks first in the
    stress order; these weights only govern how many extra miles a stress saving buys").
    The diminishing-returns rule charges the distance against the highest level that
    improves: an LTS 4 saving pays for its miles on its own, and the LTS 3 a route adds
    does not net it away. Within a level, the 1/2/3 weights still set the trade."""

    ctx = top_context()
    # The reviewer's probe: 10 km with 200 m of LTS 4; 12 km with none and 600 m of LTS 3.
    lts4 = reading(lts4=200.0, length=10_000.0)
    lts3 = reading(lts3=600.0, length=12_000.0)

    def test_the_reviewers_probe(self) -> None:
        assert refine.calmer(self.lts3, self.lts4, self.ctx)
        assert refine.better(self.lts3, self.lts4, self.ctx)
        assert not refine.better(self.lts4, self.lts3, self.ctx)

    def test_the_saving_is_the_top_levels_alone(self) -> None:
        # 2 x 200 m of LTS 4 saved; the 600 m of LTS 3 added does not subtract.
        assert refine.stress_saved_m(self.lts4, self.lts3, self.ctx) == pytest.approx(400.0)
        # A gain at the second level still adds.
        both = reading(length=12_000.0)
        assert refine.stress_saved_m(self.lts4, both, self.ctx) == pytest.approx(400.0)
        more3 = reading(lts4=200.0, lts3=300.0, length=10_000.0)
        assert refine.stress_saved_m(more3, both, self.ctx) == pytest.approx(700.0)

    def test_within_a_level_the_weights_still_net(self) -> None:
        """The top figure tied (within its step): LTS 3 nets at weight 1 as before."""
        a = reading(lts4=5.0, lts3=1000.0, length=10_000.0)
        b = reading(lts4=0.0, lts3=800.0, length=11_000.0)
        assert refine.stress_saved_m(a, b, self.ctx) == pytest.approx(10.0 + 200.0)
        # Within the top step a second-level loss still subtracts.
        c = reading(lts4=0.0, lts3=1600.0, length=11_000.0)
        assert refine.stress_saved_m(a, c, self.ctx) == pytest.approx(10.0 - 600.0)
        # Exactly the step (15 m) is still within it: netted (the mutation re-check's N3).
        edge = reading(lts4=15.0, lts3=1000.0, length=10_000.0)
        assert refine.stress_saved_m(edge, c, self.ctx) == pytest.approx(30.0 - 600.0)
        # 1,000 m added at 1 in 5 asks 200 m: 210 m pays; 1,100 m added does not.
        assert refine.better(b, a, self.ctx)
        assert not refine.better(with_(b, length_m=11_100.0), a, self.ctx)

    def test_the_miles_still_count(self) -> None:
        """Past what the LTS 4 saving buys (400 m pays 2 km at 1 in 5), the shorter stays."""
        far = with_(self.lts3, length_m=12_100.0, effort_m=12_100.0)
        assert not refine.better(far, self.lts4, self.ctx)
        assert refine.better(self.lts4, far, self.ctx)

    def test_a_long_plan_shares_its_detour_out_by_the_same_rule(self) -> None:
        """`choose_options`: the leg's LTS 4-free option is taken over its LTS 4 first."""
        near = with_(self.lts3, length_m=11_900.0, effort_m=11_900.0)
        chain = [({"legs": [{"shape": "first"}]}, self.lts4), ({"legs": [{"shape": "x"}]}, near)]
        assert refine.choose_options([chain], [10_000.0], None, self.ctx) == [1]

    def test_a_loops_way_back_by_the_same_rule(self) -> None:
        best = ((False, 0.0), None, self.lts4)
        assert refine._loop_before((False, 0.0), self.lts3, best, self.ctx)
