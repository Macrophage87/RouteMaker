"""One stress figure, traffic weight times hill (FOLLOWUP-GRADE-STRESS, OWNER-DECISIONS 409).

The owner, 2026-10-10: "Maybe make it multiplicitive? Hill distance * traffic-relative
distance." 2026-10-11: "Why not combine it all into a single stress metric? Basically you
calculate the uphill portion and then the traffic stress portion. Multiply the two
together." "The sliders control the various coefficients for each component." "So a fine
with hills will basically be multiplying everything by 1." "We wanted some stress for
extreme downhills."

Every stretch counts run x traffic weight x hill factor in the calm search's figures, and
every consumer (the score, the stress order, the worth rule, the LTS 4 hold, a long plan's
legs) reads that one figure: none adds the hill on its own, and none ignores it."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
import test_refine

from core import presets, refine, routing
from routemaker import effort, grade_stress, trace_junctions

COEF = grade_stress.FACTOR  # the hills slider's detent


def ramp(length_m: float, grade: float, start_m: float = 0.0, step: float = 30.0):
    """(metres along, elevation) every `step` metres up a steady grade."""
    return [
        (start_m + i * step, 100.0 + grade * i * step) for i in range(int(length_m // step) + 1)
    ]


def factor(grade: float, coefficient: float = COEF) -> float:
    """The hill factor of a steady climb at `grade`, worked out from the effort model."""
    return 1.0 + coefficient * (effort.effort_factor(grade) - 1.0)


class TestTheWindows:
    def test_a_climb_past_the_grade_counts_its_extra_effort(self):
        windows = grade_stress.hill_windows(ramp(1200, 0.05))
        assert windows, "a 5% climb counts"
        for start, end, extra in windows:
            assert end - start >= effort.WINDOW_M
            assert extra == pytest.approx(effort.effort_factor(0.05) - 1.0)

    def test_gentle_climbs_and_descents_count_nothing(self):
        assert grade_stress.hill_windows(ramp(1200, 0.02)) == []
        assert grade_stress.hill_windows(ramp(1200, -0.08)) == [], "no brake grade: none"
        assert grade_stress.hill_windows(ramp(1200, -0.02), brake_grade=0.03) == []
        assert grade_stress.hill_windows([]) == []

    def test_a_descent_past_the_brake_grade_counts_like_a_climb_as_steep_as_the_excess(self):
        windows = grade_stress.hill_windows(ramp(1200, -0.08), brake_grade=0.03)
        assert windows
        for _start, _end, extra in windows:
            assert extra == pytest.approx(effort.effort_factor(0.05) - 1.0)

    def test_the_grade_where_it_starts_is_a_parameter(self):
        assert grade_stress.hill_windows(ramp(1200, 0.02), grade_from=0.01)
        assert grade_stress.GRADE_FROM == 0.03 and grade_stress.FACTOR == 0.25

    def test_a_heavier_rider_pays_more_for_the_same_climb(self):
        light = grade_stress.hill_windows(ramp(900, 0.06), mass_kg=60.0)[0][2]
        heavy = grade_stress.hill_windows(ramp(900, 0.06), mass_kg=150.0)[0][2]
        assert heavy > light


class TestTheHillsSlidersCoefficient:
    def test_it_is_factor_at_the_detent_and_nothing_at_fine_with_hills(self):
        assert grade_stress.coefficient_for(0) == COEF
        assert grade_stress.coefficient_for(100) == 0.0
        assert grade_stress.coefficient_for(50) == pytest.approx(COEF / 2)

    def test_it_rises_in_proportion_toward_avoid(self):
        assert grade_stress.coefficient_for(-60) == pytest.approx(COEF * 1.6)
        assert grade_stress.coefficient_for(-100) == pytest.approx(2 * COEF)


class TestTheFactors:
    def test_each_window_is_shared_by_its_overlap(self):
        windows = [(0.0, 300.0, 2.0), (300.0, 600.0, 4.0)]
        got = grade_stress.hill_factors(windows, [150.0, 300.0, 450.0], 0.5)
        assert got == pytest.approx(
            [1 + 0.5 * 2.0, 1 + 0.5 * (150 * 2.0 + 150 * 4.0) / 300, 1 + 0.5 * 150 * 4.0 / 450]
        )

    def test_a_window_past_the_pieces_changes_nothing(self):
        assert grade_stress.hill_factors([(1000.0, 1300.0, 3.0)], [900.0], COEF) == [1.0]

    def test_fine_with_hills_is_exactly_one(self):
        assert grade_stress.hill_factors([(0.0, 300.0, 9.0)], [300.0, 50.0], 0.0) == [1.0, 1.0]


def _trip(length_m: float, elevations: list[float]) -> dict:
    return {
        "legs": [{"shape": "x", "summary": {"length": length_m / 1000.0}, "elevation": elevations}],
        "summary": {"length": length_m / 1000.0, "cost": 1000.0},
    }


def heights(length_m: float, grade: float) -> list[float]:
    """The router's samples, every ELEVATION_INTERVAL_M, along a steady grade."""
    step = routing.ELEVATION_INTERVAL_M
    return [100.0 + grade * step * i for i in range(int(length_m // step) + 1)]


def analysed(
    monkeypatch,
    tiers: list[tuple[float, str]],
    grade: float,
    coefficient: float = COEF,
    brake_grade: float | None = None,
    exposure: presets.Exposure = presets.EXPOSURE_STANDARD,
    rate: float = 10.0,
) -> refine.Analysis:
    """The real `refine.analyse` of a route of (metres, tier) stretches on a steady grade,
    the router and the traces stubbed."""
    pieces = [SimpleNamespace(metres=m) for m, _tier in tiers]
    classes = [routing.PieceClass(tier, "none") for _m, tier in tiers]
    monkeypatch.setattr(routing, "_trace", lambda *args: {})
    monkeypatch.setattr(routing, "pieces_of_trace", lambda trace: pieces)
    monkeypatch.setattr(routing, "classify", lambda *args: classes)
    monkeypatch.setattr(routing, "decode_polyline6", lambda shape: [])
    monkeypatch.setattr(trace_junctions, "junctions_of_trace", lambda *args: [])
    monkeypatch.setattr(trace_junctions, "edge_midpoints", lambda *args: [])
    ctx = test_refine.context(rate=rate)
    ctx.hill_coefficient, ctx.brake_grade, ctx.exposure = coefficient, brake_grade, exposure
    length = sum(m for m, _tier in tiers)
    read = refine.analyse(_trip(length, heights(length, grade)), ctx, ctx.deadline, False)
    assert read is not None
    return read


def figures(read: refine.Analysis) -> tuple:
    return (read.lts4_m, read.lts3_m, read.lts2_m, read.avoid_m, read.exposure_m, read.top_m)


class TestTheOneFigure:
    """0.62 mi (1 km) of LTS 4 up 6%: the PR's example."""

    def test_a_climb_multiplies_the_road_it_is_ridden_on(self, monkeypatch):
        up = analysed(monkeypatch, [(1000.0, "4")], 0.06)
        flat = analysed(monkeypatch, [(1000.0, "4")], 0.0)
        assert flat.lts4_m == pytest.approx(1000.0)
        assert up.lts4_m == pytest.approx(1000.0 * factor(0.06), rel=0.01)
        assert up.exposure_m == pytest.approx(2 * up.lts4_m)
        # The climb adds about 1.28 mi (2,060 m) of LTS 3 in the worth rule over the same
        # road on the flat; avoiding the whole climb saves about 2.52 mi (4,060 m).
        added = refine.stress_weight_m(up, None) - refine.stress_weight_m(flat, None)
        assert added == pytest.approx(2060, abs=40)
        assert refine.stress_weight_m(up, None) == pytest.approx(4060, abs=40)

    def test_quiet_streets_stay_free(self, monkeypatch):
        up = analysed(monkeypatch, [(500.0, "1"), (500.0, "2")], 0.06)
        assert up.exposure_m == 0.0 and up.lts4_m == up.lts3_m == 0.0

    def test_the_same_road_downhill_counts_as_flat(self, monkeypatch):
        down = analysed(monkeypatch, [(1000.0, "4")], -0.06, brake_grade=0.06)
        flat = analysed(monkeypatch, [(1000.0, "4")], 0.0, brake_grade=0.06)
        assert figures(down) == figures(flat)

    def test_fine_with_hills_multiplies_everything_by_one(self, monkeypatch):
        coefficient = grade_stress.coefficient_for(100)
        for grade, brake in ((0.08, None), (-0.10, 0.03)):
            hilly = analysed(monkeypatch, [(600.0, "4"), (400.0, "3")], grade, coefficient, brake)
            flat = analysed(monkeypatch, [(600.0, "4"), (400.0, "3")], 0.0, coefficient, brake)
            assert hilly.hill == [1.0, 1.0]
            assert figures(hilly) == figures(flat)

    def test_what_the_rider_is_shown_is_the_rated_metres(self, monkeypatch):
        up = analysed(monkeypatch, [(1000.0, "4")], 0.06)
        stress, _facility = routing.totals(zip(up.pieces, up.classes, strict=True))
        assert stress["4"] == 1000.0


class TestExtremeDownhills:
    """OWNER-DECISIONS 56, "We wanted some stress for extreme downhills": a descent steeper
    than the ride type's brake grade counts in the factor; a gentle one does not."""

    def test_a_steep_descent_on_lts4_counts_more_than_the_same_road_flat(self, monkeypatch):
        cargo = presets.BRAKE_GRADES["cargo"]
        down = analysed(monkeypatch, [(1000.0, "4")], -0.08, brake_grade=cargo)
        assert down.lts4_m == pytest.approx(1000.0 * factor(0.08 - cargo), rel=0.01)
        assert down.lts4_m > 1000.0

    def test_the_threshold_follows_the_ride_type(self, monkeypatch):
        assert presets.BRAKE_GRADES["cargo"] == 0.03
        cargo = analysed(monkeypatch, [(1000.0, "4")], -0.05, brake_grade=0.03)
        default = analysed(
            monkeypatch, [(1000.0, "4")], -0.05, brake_grade=presets.BRAKE_GRADES["default"]
        )
        goat = analysed(
            monkeypatch, [(1000.0, "4")], -0.12, brake_grade=presets.BRAKE_GRADES["mountain-goat"]
        )
        assert cargo.lts4_m > 1000.0
        assert default.lts4_m == pytest.approx(1000.0), "5% is gentle past 6%'s brake grade"
        assert goat.lts4_m == pytest.approx(1000.0), "a ride type without one: none"

    def test_a_gentle_descent_does_not(self, monkeypatch):
        gentle = analysed(monkeypatch, [(1000.0, "4")], -0.02, brake_grade=0.03)
        assert gentle.lts4_m == pytest.approx(1000.0) and gentle.hill == [1.0]


class TestEveryConsumerReadsTheOneFigure:
    """Each consumer is checked against the hill-weighted figure worked out on its own: one
    that also added the hill would count it twice, one that ignored it would read the flat."""

    @pytest.fixture
    def up(self, monkeypatch):
        return analysed(monkeypatch, [(1000.0, "4")], 0.06)

    def weighted(self) -> float:
        return 1000.0 * factor(0.06)

    def test_the_score(self, up):
        ctx = test_refine.context(rate=10.0)
        expected = up.cost_s + ctx.quiet_cost * ctx.rate * 2 * self.weighted()
        assert up.score(ctx) == pytest.approx(expected, rel=0.01)
        assert up.score(ctx) == pytest.approx(up.cost_s + ctx.quiet_cost * 10.0 * up.exposure_m)

    def test_the_stress_order(self, up):
        top, second, _third = up.key(test_refine.context(maxcalm=True))
        assert top == pytest.approx(self.weighted(), rel=0.01) and top == up.lts4_m
        assert second == 0.0

    def test_the_worth_rules_saving(self, up):
        quiet = dataclasses.replace(test_refine.analysis("q", "1" * 10), length_m=2000.0)
        saved = refine.stress_saved_m(up, quiet, test_refine.context(rate=10.0))
        assert saved == pytest.approx(2 * self.weighted(), rel=0.01)
        assert saved == pytest.approx(refine.stress_weight_m(up, None))

    def test_a_long_plans_legs(self, up, monkeypatch):
        flat = analysed(monkeypatch, [(1000.0, "4")], 0.0)
        whole = refine.combine([up, flat])
        assert whole.lts4_m == pytest.approx(up.lts4_m + 1000.0)
        assert whole.exposure_m == pytest.approx(up.exposure_m + flat.exposure_m)
        assert whole.hill_exposure_m == pytest.approx(up.hill_exposure_m)
        assert whole.hill == up.hill + flat.hill


class TestTheLts4HoldComparesRatedMetres:
    """On the rides with the hold (Kids, Cargo with passengers, Trailmaxxing; 250) it
    compares the rated LTS 4 metres, not hill-weighted ones, so leaving out a hill can never
    buy more LTS 4, and a climb never refuses a route with no more LTS 4 than the first."""

    def ctx(self) -> refine.Context:
        ctx = test_refine.context()
        ctx.exposure = presets.EXPOSURE_STRESS_AVERSE
        return ctx

    def test_its_figures_are_the_rated_metres(self, monkeypatch):
        up = analysed(monkeypatch, [(1000.0, "4")], 0.06, exposure=presets.EXPOSURE_STRESS_AVERSE)
        assert up.lts4_m > 1500.0
        assert refine.top_by_leg(up) == pytest.approx([1000.0])

    def test_leaving_out_a_hill_never_buys_more_lts4(self, monkeypatch):
        first = analysed(monkeypatch, [(1000.0, "4")], 0.06)
        more_flat = analysed(monkeypatch, [(1200.0, "4")], 0.0)
        assert more_flat.lts4_m < first.lts4_m, "less by the weighted figure"
        assert refine.more_lts4(more_flat, refine.top_by_leg(first), self.ctx())

    def test_a_climb_never_refuses_the_same_lts4(self, monkeypatch):
        first = analysed(monkeypatch, [(1000.0, "4")], 0.0)
        up = analysed(monkeypatch, [(1000.0, "4")], 0.06)
        assert not refine.more_lts4(up, refine.top_by_leg(first), self.ctx())


class TestTrafficWinsComparesRatedMetres:
    """OWNER-DECISIONS 61, "Traffic wins": hill avoidance never makes a route busier. The
    guard compares the rated exposure (`Analysis.rated_exposure_m`), so a route that leaves
    out a busy climb by riding more busy road is still refused (the review of #87)."""

    def test_two_km_of_flat_lts4_is_busier_than_one_km_up_a_hill(self, monkeypatch):
        climb = analysed(monkeypatch, [(1000.0, "4")], 0.06)
        flat = analysed(monkeypatch, [(2000.0, "4")], 0.0)
        assert flat.exposure_m < climb.exposure_m, "less by the hill-weighted figure"
        assert climb.rated_exposure_m == pytest.approx(2000.0)
        ctx = test_refine.context(rate=10.0)
        assert refine._busier(flat, climb.rated_exposure_m, ctx)
        assert not refine._busier(climb, flat.rated_exposure_m, ctx)


class TestTheHillCountsAtEverySliderPosition:
    """The owner's own case (409, Connecticut Avenue NW, at Default, 70 on the stress
    slider, where the calm rate is 0): the hill's share of the exposure counts in the score
    one for one where the rate is under 1, at the rate above it. A flat route scores as it
    did at every position, and "fine with hills" is exactly the flat."""

    POSITIONS = range(0, 101, 5)

    def ctx(self, stress: int, lts2: float = 0.0) -> refine.Context:
        ctx = test_refine.context(
            rate=presets.calm_rate_for(stress), weight=refine.intersection_weight(stress)
        )
        if lts2:
            ctx.exposure = dataclasses.replace(presets.EXPOSURE_STRESS_AVERSE, lts2=lts2)
        return ctx

    def test_the_climb_changes_the_ranking_at_default(self, monkeypatch):
        ctx = self.ctx(presets.STRESS_DEFAULT_AT)
        assert ctx.rate == 0.0
        up = analysed(monkeypatch, [(1000.0, "4")], 0.06)
        # The same road on the flat, 2 minutes dearer to the router.
        flat = dataclasses.replace(
            analysed(monkeypatch, [(1000.0, "4")], 0.0), cost_s=up.cost_s + 120.0
        )
        assert up.score(ctx) - up.cost_s == pytest.approx(ctx.quiet_cost * up.hill_exposure_m)
        assert up.hill_exposure_m == pytest.approx(2 * 1000.0 * (factor(0.06) - 1), rel=0.02)
        assert refine.better(flat, up, ctx), "the flat road wins at Default"
        unhilled = dataclasses.replace(up, exposure_m=flat.exposure_m, flat_exposure_m=None)
        assert not refine.better(flat, unhilled, ctx), "and would not without the hill"

    def test_above_a_rate_of_one_the_hill_scales_with_it(self, monkeypatch):
        up = analysed(monkeypatch, [(1000.0, "4")], 0.06)
        for stress in (90, 95, 100):
            ctx = self.ctx(stress)
            assert ctx.rate > 1
            assert up.score(ctx) - up.cost_s == pytest.approx(
                ctx.quiet_cost * ctx.rate * up.exposure_m
            )

    @pytest.mark.parametrize(
        ("lts2", "exposure_m"),
        # 300 m each of LTS 2, 3 and 4 and 100 m of LTS 1: 300 + 2 x 300 on the standard
        # weights; 0.25 x 300 + 300 + 8 x 300 on the stress-averse ones with LTS 2 weighed.
        [(0.0, 900.0), (presets.LTS2_WEIGHT, 2775.0)],
    )
    def test_a_flat_route_scores_as_before_at_every_position(self, monkeypatch, lts2, exposure_m):
        exposure = (
            dataclasses.replace(presets.EXPOSURE_STRESS_AVERSE, lts2=lts2)
            if lts2
            else presets.EXPOSURE_STANDARD
        )
        tiers = [(300.0, "2"), (300.0, "3"), (300.0, "4"), (100.0, "1")]
        flat = analysed(monkeypatch, tiers, 0.0, exposure=exposure)
        assert flat.exposure_m == pytest.approx(exposure_m) and flat.hill_exposure_m == 0.0
        for stress in self.POSITIONS:
            ctx = self.ctx(stress, lts2)
            # The score before the hill (release/v0.5.0): the router's cost plus the quiet
            # cost x (calm rate x exposure, and at a rate of 0 the LTS 2 term); no junctions,
            # no climb, no Avoid junctions in this reading.
            extra = ctx.rate * exposure_m
            if ctx.rate == 0 and lts2:
                extra += lts2 * refine.lts3_added_m(ctx) * 300.0
            assert flat.score(ctx) == pytest.approx(flat.cost_s + ctx.quiet_cost * extra), stress

    def test_lts2_climbing_counts_once_at_a_rate_of_zero(self, monkeypatch):
        # The score's LTS 2 term at a rate of 0 (FOLLOWUP-LTS2-WEIGHT) reads the rated
        # metres; the hill on LTS 2 comes in once, through the exposure's hill share.
        exposure = dataclasses.replace(presets.EXPOSURE_STRESS_AVERSE, lts2=presets.LTS2_WEIGHT)
        up = analysed(monkeypatch, [(1000.0, "2")], 0.06, exposure=exposure)
        ctx = self.ctx(presets.STRESS_DEFAULT_AT, presets.LTS2_WEIGHT)
        lts2_term = presets.LTS2_WEIGHT * refine.lts3_added_m(ctx) * 1000.0
        assert up.hill_exposure_m > 0
        assert up.score(ctx) - up.cost_s == pytest.approx(
            ctx.quiet_cost * (up.hill_exposure_m + lts2_term)
        )

    def test_fine_with_hills_is_the_flat_at_every_position(self, monkeypatch):
        tiers = [(600.0, "4"), (400.0, "2")]
        fine = grade_stress.coefficient_for(100)
        for grade, brake in ((0.08, None), (-0.10, 0.03)):
            hilly = analysed(monkeypatch, tiers, grade, fine, brake)
            flat = analysed(monkeypatch, tiers, 0.0, fine, brake)
            for stress in self.POSITIONS:
                ctx = self.ctx(stress)
                assert hilly.score(ctx) == flat.score(ctx), (grade, stress)


class TestTheSlidersSetTheirOwnCoefficients:
    """ "The sliders control the various coefficients for each component": the hills slider
    the hill factor's, the stress slider the traffic part's."""

    def test_the_hills_slider_moves_the_hill_part(self, monkeypatch):
        tiers = [(1000.0, "4")]
        averse, detent, fine = (
            analysed(monkeypatch, tiers, 0.06, grade_stress.coefficient_for(h))
            for h in (-60, 0, 50)
        )
        assert averse.lts4_m > detent.lts4_m > fine.lts4_m > 1000.0
        flats = [
            analysed(monkeypatch, tiers, 0.0, grade_stress.coefficient_for(h))
            for h in (-100, 0, 100)
        ]
        assert {figures(read) for read in flats} == {figures(flats[0])}

    def test_the_stress_slider_moves_the_traffic_part_and_not_the_hill(self, monkeypatch):
        low, high = (
            analysed(monkeypatch, [(1000.0, "4")], 0.06, rate=presets.calm_rate_for(s))
            for s in (90, 100)
        )
        assert low.hill == high.hill and figures(low) == figures(high)
        ctx_low = test_refine.context(rate=presets.calm_rate_for(90))
        ctx_high = test_refine.context(rate=presets.calm_rate_for(100))
        assert high.score(ctx_high) - high.cost_s == pytest.approx(
            (low.score(ctx_low) - low.cost_s) * ctx_high.rate / ctx_low.rate
        )


class TestTheWorthRuleCountsTheHill:
    """OWNER-DECISIONS 409 and 435: the owner's "Count it" (2026-10-11): "A longer route can
    win by avoiding a busy climb, so some plans get longer." The rule's ratios and targets
    are unchanged; the saving is in hill-weighted metres. Avoiding 0.62 mi (1 km) of LTS 4
    up 6% saves about 4,060 m of LTS 3: about 4.3 mi (6.9 km) of extra riding at 90 on the
    slider (1.7 to 1) and 12.6 mi (20.3 km) at 100 (5 to 1)."""

    def ctx(self, top: bool) -> refine.Context:
        if top:
            return test_refine.context(rate=10.0, maxcalm=True)
        return test_refine.context(rate=presets.calm_rate_for(90))

    def pair(self, monkeypatch, added_m: float, grade: float = 0.06):
        short = analysed(monkeypatch, [(1000.0, "4")], grade)
        long = dataclasses.replace(
            test_refine.analysis("l", "1" * 10), length_m=short.length_m + added_m
        )
        return short, long

    @pytest.mark.parametrize(
        ("top", "ok_m", "too_far_m"), [(False, 6500, 7500), (True, 19500, 21500)]
    )
    def test_avoiding_a_busy_climb_buys_its_miles(self, monkeypatch, top, ok_m, too_far_m):
        short, long = self.pair(monkeypatch, ok_m)
        assert refine.worth_it(short, long, self.ctx(top))
        short, long = self.pair(monkeypatch, too_far_m)
        assert not refine.worth_it(short, long, self.ctx(top))

    @pytest.mark.parametrize("top", [False, True])
    def test_the_climb_itself_buys_miles_the_flat_road_would_not(self, monkeypatch, top):
        # Over the flat road's 2,000 m, the climb adds about 2,060 m: 3.5 km (2.2 mi) at 90
        # and 10.3 km (6.4 mi) at 100. Past the flat road's own share, only the climb pays.
        ratio = refine.worth_ratio(self.ctx(top))
        extra = 2000.0 * ratio + 0.8 * 2060.0 * ratio
        flat, long = self.pair(monkeypatch, extra, grade=0.0)
        assert not refine.worth_it(flat, long, self.ctx(top))
        short, long = self.pair(monkeypatch, extra)
        assert refine.worth_it(short, long, self.ctx(top))

    def test_a_long_plan_spends_its_detour_round_a_busy_climb(self, monkeypatch):
        short, long = self.pair(monkeypatch, 6000.0)
        chain = [(None, short), (None, long)]
        assert refine.choose_options([chain], [short.length_m], None, self.ctx(True)) == [1]
