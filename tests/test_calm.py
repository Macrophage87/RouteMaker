"""The rolling stress score, calm miles per mile (`routemaker.calm`; OWNER-DECISIONS 460.12,
461, 461a-e, 469b; docs/stress/stress-number.md section 4)."""

from __future__ import annotations

from dataclasses import dataclass, fields

import pytest

from core import presets, refine
from routemaker import calm

MILE = 1609.344
DEFAULT = calm.Pricing(use_roads=presets.use_roads_for(70), quiet_cost_s=2.2 * 3.6 / 18)


@dataclass
class Event:
    m: float
    cost_ft: float
    severity: str | None = None
    flagged: bool = False


def span(from_m: float, to_m: float, tier: int | None, facility: str | None = "none") -> dict:
    return {"from_m": from_m, "to_m": to_m, "tier": tier, "facility": facility}


class TestMultiplier:
    def test_default_matches_the_stress_number_table(self) -> None:
        # docs/stress/stress-number.md section 2: Default (70) LTS 3 2.88-5.79, LTS 4
        # 12.85-15.83; the middle of each range.
        assert calm.multiplier(3, "none", DEFAULT) == pytest.approx((2.88 + 5.79) / 2, abs=0.01)
        assert calm.multiplier(4, "none", DEFAULT) == pytest.approx((12.85 + 15.83) / 2, abs=0.01)

    def test_avoid_costs_lts_4_per_metre_below_the_top(self) -> None:
        assert calm.multiplier(5, "none", DEFAULT) == calm.multiplier(4, "none", DEFAULT)

    def test_fast_and_group_are_between_the_modelled_positions(self) -> None:
        fast = calm.Pricing(use_roads=presets.use_roads_for(10))
        group = calm.Pricing(use_roads=presets.use_roads_for(40))
        assert calm.multiplier(3, None, fast) == pytest.approx((1.22 + 1.36) / 2, abs=0.01)
        assert calm.multiplier(4, None, fast) == pytest.approx((2.11 + 2.34) / 2, abs=0.01)
        assert calm.multiplier(3, None, group) == pytest.approx((1.93 + 2.85) / 2, abs=0.01)
        assert calm.multiplier(4, None, group) == pytest.approx((5.38 + 6.25) / 2, abs=0.01)

    def test_at_zero_only_lts_4_costs_more(self) -> None:
        zero = calm.Pricing(use_roads=1.0)
        assert calm.multiplier(3, None, zero) == 1.0
        assert calm.multiplier(4, None, zero) == pytest.approx((1.37 + 1.52) / 2, abs=0.01)

    def test_lts_1_and_2_count_as_a_quiet_street_whatever_the_slider(self) -> None:
        for stress in (0, 40, 70, 90):
            pricing = calm.Pricing(use_roads=presets.use_roads_for(stress))
            assert calm.multiplier(1, "none", pricing) == 1.0
            assert calm.multiplier(2, "none", pricing) == 1.0

    def test_a_path_and_a_protected_lane_count_below_a_quiet_street(self) -> None:
        # stress-number.md section 2 notes: about 0.55 and 0.57 at Default.
        assert calm.multiplier(1, "path", DEFAULT) == pytest.approx(0.55, abs=0.02)
        assert calm.multiplier(2, "protected", DEFAULT) == pytest.approx(0.57, abs=0.02)
        lane = (1 + (0.9 + 0.05 * 0.1) * 1.2) / 2.2
        assert calm.multiplier(2, "lane", DEFAULT) == pytest.approx(lane, abs=0.001)

    def test_the_no_trail_graph_has_no_facility_classes_and_no_grading(self) -> None:
        no_trail = calm.Pricing(use_roads=presets.use_roads_for(70), no_trail=True)
        assert calm.multiplier(1, "path", no_trail) == 1.0
        assert calm.multiplier(4, None, no_trail) == calm.multiplier(3, None, no_trail)

    def test_above_80_the_calm_rate_adds_each_tiers_weight(self) -> None:
        at90 = calm.Pricing(
            use_roads=presets.use_roads_for(90),
            rate=presets.calm_rate_for(90),
            weights=(1.0, 2.0, 3.0),
        )
        # stress-number.md: slider at 90, standard weights, LTS 3 4.98-8.66, LTS 4 19.26-23.07.
        assert calm.multiplier(3, None, at90) == pytest.approx((4.98 + 8.66) / 2, abs=0.02)
        assert calm.multiplier(4, None, at90) == pytest.approx((19.26 + 23.07) / 2, abs=0.02)

    def test_the_top_of_the_slider_uses_the_worth_rule(self) -> None:
        top = calm.Pricing(use_roads=0.0, maxcalm=True)
        assert [calm.multiplier(t, None, top) for t in (3, 4, 5)] == [6.0, 11.0, 16.0]
        within = calm.Pricing(use_roads=0.0, maxcalm=True, target=True)
        assert [calm.multiplier(t, None, within) for t in (3, 4, 5)] == [11.0, 21.0, 31.0]

    def test_lts_2_stays_a_quiet_street_on_the_rides_that_weigh_it(self) -> None:
        """FOLLOWUP-LTS2-WEIGHT review: the chart shows traffic stress, not the ranking's
        LTS 2 preference, so an all-quiet route still reads about 1 (461d) on Trailmaxxing,
        Cargo with passengers and Riding with kids: the chart's pricing has no LTS 2 term."""
        assert "lts2" not in {f.name for f in fields(calm.Pricing)}
        for pricing in (
            calm.Pricing(use_roads=0.0, maxcalm=True),
            calm.Pricing(use_roads=0.0, rate=presets.calm_rate_for(90), weights=(1.0, 8.0, 16.0)),
        ):
            assert calm.multiplier(2, "none", pricing) == calm.multiplier(1, "none", pricing) == 1.0

    def test_the_worth_figures_are_refines_own(self) -> None:
        assert calm.WORTH_DEFAULT == refine.WORTH_DEFAULT
        assert calm.WORTH_UP_TO_TARGET == refine.WORTH_UP_TO_TARGET
        w = refine.WORTH_WEIGHTS
        assert calm.WORTH_WEIGHTS == {3: w.lts3, 4: w.lts4, 5: w.avoid}
        assert calm.QUIET_FACTOR == refine.QUIET_COST_FACTOR
        assert calm.AVOID_ENTRY_S == presets.AVOID_ENTRY_PENALTY_S

    def test_unrated_has_no_number(self) -> None:
        assert calm.multiplier(None, None, DEFAULT) is None

    def test_avoid_entry_is_quiet_metres_at_the_ride_speed(self) -> None:
        # stress-number.md section 2: 2.5 mi [4.1 km] at Default.
        assert calm.avoid_entry_m(DEFAULT) / MILE == pytest.approx(2.54, abs=0.01)

    def test_at_zero_there_is_no_lts_3_band_so_quiet_streets_never_read_as_lts_3(self) -> None:
        # Correctness review SF1: LTS 3 costs nothing extra at 0, so (1 + 1) / 2 would put a
        # quiet street on the LTS 3 edge.
        low, high = calm.bands(calm.Pricing(use_roads=1.0))
        assert low == high > 1.0

    def test_the_bands_are_read_from_representative_roads(self) -> None:
        # stress-number.md "Words as a guide": 2.0 and 11.3 for Default.
        low, high = calm.bands(DEFAULT)
        assert low == pytest.approx(2.01, abs=0.02)
        assert high == pytest.approx(11.26, abs=0.02)

    @pytest.mark.parametrize("stress", [10, 40, 70, 80, 90, 100])
    def test_each_tiers_typical_road_lands_in_its_own_band(self, stress) -> None:
        # Review S3: a 25 mph LTS 3 street is never said as "LTS 1 to 2 level".
        pricing = calm.Pricing(
            use_roads=presets.use_roads_for(stress),
            rate=presets.calm_rate_for(stress),
            maxcalm=stress == 100,
        )
        low, high = calm.bands(pricing)

        def m(road, tier):
            return calm.road_multiplier(tier, "none", road, pricing)[0]

        quiet = calm.QUIET_URBAN
        for road in (quiet, calm.QUIET_RURAL, calm.BAND_COLLECTOR):
            assert m(road, 2) < low
        for road in (calm.BAND_COLLECTOR, calm.BAND_ARTERIAL):
            assert low < m(road, 3) < high
        assert m(calm.BAND_GRADED, 4) > high
        busy_lts4 = calm.Road(road_class="primary", lanes=calm.GRADED_LANES, speed_limit_kph=64)
        assert m(busy_lts4, 4) > high

    def test_on_the_no_trail_graph_lts_4_is_its_busiest_roads(self) -> None:
        no_trail = calm.Pricing(use_roads=presets.use_roads_for(70), no_trail=True)
        low, high = calm.bands(no_trail)
        m = calm.road_multiplier(3, "none", calm.BAND_ARTERIAL, no_trail)[0]
        assert low < m < high
        assert calm.road_multiplier(4, "none", calm.BAND_TRUNK, no_trail)[0] > high


class TestRolling:
    def test_the_worked_example(self) -> None:
        # stress-number.md section 4: 2 mi of LTS 2, one crossing at 1.0 mi of 3,300 ft.
        out = calm.score(
            [span(0, 2 * MILE, 2)],
            [Event(1 * MILE, 3300, "red", True)],
            DEFAULT,
            [0, 0.5 * MILE, 1 * MILE, 1.5 * MILE, 2 * MILE],
            window_m=MILE,
        )
        assert out["ratio"] == [1.0, 1.62, 1.62, 1.62, 1.0]
        assert out["total_calm_m"] / MILE == pytest.approx(2.625, abs=0.001)
        assert out["rated_m"] == round(2 * MILE)
        crossing = {"m": round(MILE), "calm_m": round(3300 * 0.3048)}
        assert out["points"] == [{**crossing, "kind": "junction", "severity": "red"}]

    def test_a_junction_raises_the_mile_around_it_not_beyond(self) -> None:
        out = calm.score(
            [span(0, 3 * MILE, 2)],
            [Event(1.5 * MILE, 1200)],
            DEFAULT,
            [0.9 * MILE, 1.1 * MILE, 2.1 * MILE],
            window_m=MILE,
        )
        assert out["ratio"][0] == 1.0
        assert out["ratio"][1] > 1.0
        assert out["ratio"][2] == 1.0
        # Unflagged: counted, but not sent as a point (no marker).
        assert out["points"] == []

    def test_the_window_is_cut_at_the_ends(self) -> None:
        # The first half mile is LTS 4, the rest LTS 2: at the start the window is the
        # first half mile only, so it reads LTS 4's figure, not half of it.
        out = calm.score(
            [span(0, 0.5 * MILE, 4), span(0.5 * MILE, 3 * MILE, 2)],
            [],
            DEFAULT,
            [0],
            window_m=MILE,
        )
        assert out["ratio"][0] == pytest.approx(calm.multiplier(4, "none", DEFAULT), abs=0.01)

    def test_a_crossing_heavy_lts_2_street_can_read_above_a_straight_lts_3_one(self) -> None:
        # 461e's own example, at Group (40): seven orange crossings in a mile of LTS 2.
        group = calm.Pricing(use_roads=presets.use_roads_for(40))
        busy = calm.score(
            [span(0, MILE, 2)],
            [Event(MILE * k / 8, 1200, "orange", True) for k in range(1, 8)],
            group,
            [MILE / 2],
            window_m=MILE,
        )
        straight = calm.score([span(0, MILE, 3)], [], group, [MILE / 2], window_m=MILE)
        assert busy["ratio"][0] > straight["ratio"][0]

    def test_unrated_counts_in_neither_and_an_all_unrated_window_has_none(self) -> None:
        out = calm.score(
            [span(0, MILE, 3), span(MILE, 4 * MILE, None, None)],
            [],
            DEFAULT,
            [0.75 * MILE, 3 * MILE],
            window_m=MILE,
        )
        assert out["ratio"][0] == pytest.approx(calm.multiplier(3, "none", DEFAULT), abs=0.01)
        assert out["ratio"][1] is None
        assert out["rated_m"] == round(MILE)

    def test_avoid_entry_counted_once_per_entry(self) -> None:
        spans = [span(0, 100, 2), span(100, 200, 5), span(200, 300, 5, "path"), span(300, 400, 2)]
        out = calm.score(spans, [], DEFAULT, [0])
        entries = [p for p in out["points"] if p["kind"] == "avoid_entry"]
        assert [p["m"] for p in entries] == [100]

    def test_junctions_not_read_are_said_so(self) -> None:
        out = calm.score([span(0, 1000, 2)], None, DEFAULT, [0])
        assert out["junctions_counted"] is False
        assert calm.score([span(0, 1000, 2)], [], DEFAULT, [0])["junctions_counted"] is True

    def test_steps_join_equal_neighbours(self) -> None:
        out = calm.score([span(0, 100, 1), span(100, 200, 2), span(200, 300, 3)], [], DEFAULT, [0])
        assert [(s["from_m"], s["to_m"], s["tier"]) for s in out["steps"]] == [
            (0, 100, 1),
            (100, 200, 2),
            (200, 300, 3),
        ]
        same = calm.score([span(0, 100, 2), span(100, 200, 2, "none")], [], DEFAULT, [0])
        assert len(same["steps"]) == 1

    def test_a_route_shorter_than_the_window_uses_its_whole_length(self) -> None:
        out = calm.score(
            [span(0, 200, 2), span(200, 400, 3)], [], DEFAULT, [0, 200, 400], window_m=MILE
        )
        assert len(set(out["ratio"])) == 1


class TestJunctions:
    def test_a_junction_counts_at_the_presets_intersection_weight(self) -> None:
        # 461d: "times its factors and the preset's intersection weight".
        group = calm.Pricing(use_roads=presets.use_roads_for(40), junction_weight=0.679)
        out = calm.score([span(0, 1000, 2)], [Event(500, 1000, "orange", True)], group, [500])
        assert out["total_calm_m"] == round(1000 + 1000 * 0.3048 * 0.679)
        assert refine.intersection_weight(40) == pytest.approx(0.679, abs=0.001)

    def test_at_the_top_the_worth_rule_prices_flagged_junctions_only(self) -> None:
        top = calm.Pricing(use_roads=0.0, maxcalm=True)
        events = [Event(100, 1000, "red", True), Event(200, 1000, "orange", True), Event(300, 500)]
        out = calm.score([span(0, 1000, 2)], events, top, [0])
        cost = 1000 * 0.3048
        assert out["total_calm_m"] == round(1000 + 5 * 2 * cost + 5 * 1 * cost)

    def test_a_junction_on_an_unrated_stretch_is_not_counted(self) -> None:
        # Correctness review SF2: (100 + 366) / 100 would draw a false spike.
        spans = [span(0, 100, 2), span(100, 1600, None, None)]
        out = calm.score(spans, [Event(800, 1200, "orange", True)], DEFAULT, [100], window_m=MILE)
        assert out["ratio"] == [1.0]
        assert out["points"] == []

    def test_only_flagged_junctions_and_avoid_entries_are_sent_as_points(self) -> None:
        spans = [span(0, 1000, 2), span(1000, 1100, 5), span(1100, 2000, 2)]
        events = [Event(300, 400), Event(600, 1300, "orange", True)]
        out = calm.score(spans, events, DEFAULT, [0])
        assert [(p["m"], p["kind"]) for p in out["points"]] == [
            (600, "junction"),
            (1000, "avoid_entry"),
        ]
        # The unflagged one still counts in the total.
        entry = calm.avoid_entry_m(DEFAULT)
        m5 = calm.multiplier(5, "none", DEFAULT)
        expected = 1900 + 100 * m5 + (400 + 1300) * 0.3048 + entry
        assert out["total_calm_m"] == pytest.approx(expected, abs=1)

    def test_avoid_after_a_gap_is_a_new_entry(self) -> None:
        steps = [calm.Step(0, 100, 14.0, 5), calm.Step(150, 200, 14.0, 5)]
        entries = [p for p in calm.points_of(steps, [], DEFAULT) if p.kind == "avoid_entry"]
        assert [p.m for p in entries] == [0, 150]


class TestWindowEdges:
    def test_a_gap_between_sections_is_unrated(self) -> None:
        out = calm.score([span(0, 100, 2), span(300, 400, 3)], [], DEFAULT, [200], window_m=100)
        assert out["ratio"] == [None]
        assert out["rated_m"] == 200

    def test_a_short_route_reads_its_whole_length_weighted(self) -> None:
        out = calm.score([span(0, 200, 2), span(200, 400, 3)], [], DEFAULT, [0], window_m=MILE)
        m3 = calm.multiplier(3, "none", DEFAULT)
        assert out["ratio"][0] == pytest.approx((200 + 200 * m3) / 400, abs=0.01)

    def test_the_peak_is_found_over_every_sample(self) -> None:
        spans = [span(0, 3000, 2), span(3000, 3100, 4), span(3100, 9000, 2)]
        samples = list(range(0, 9001, 30))
        i = calm.peak_index(spans, [], DEFAULT, samples, window_m=MILE)
        assert abs(samples[i] - 3050) <= MILE / 2


# docs/DEVELOPMENT.md "Graded stress": the five modelled roadways (class, lanes each way, speed
# in km/h as the graph stores it - Valhalla rounds 55 mph to 89 - and cycle lane; the "painted
# lane" row is upstream's reading of a painted lane, its dedicated class), and their LTS 3 /
# LTS 4 added cost at use_roads 1, 0.75, 0.5, 0.25, 0.10 and 0 (old positions 0 to 100).
USE_ROADS = (1.0, 0.75, 0.5, 0.25, 0.1, 0.0)
GRADED_TABLE = [
    (
        ("secondary", 1, 48, "none"),
        [(0, 1.14), (0.92, 4.64), (1.98, 10.21), (3.26, 20.22), (4.13, 28.38), (4.75, 34.82)],
    ),
    (
        ("primary", 2, 56, "none"),
        [(0, 1.05), (1.14, 4.62), (2.63, 10.42), (4.70, 21.06), (6.23, 29.80), (7.38, 36.74)],
    ),
    (
        ("primary", 2, 64, "dedicated"),
        [(0, 0.82), (1.26, 3.97), (3.00, 9.10), (5.51, 18.42), (7.39, 26.08), (8.82, 32.14)],
    ),
    (
        ("trunk", 3, 72, "none"),
        [(0, 0.91), (1.55, 4.63), (3.85, 10.88), (7.58, 22.74), (10.54, 32.62), (12.84, 40.52)],
    ),
    (
        ("primary", 2, 89, "none"),
        [(0, 0.81), (1.47, 4.18), (3.61, 9.77), (6.81, 20.12), (9.27, 28.68), (11.16, 35.48)],
    ),
]
URBAN = calm.MAX_RURAL_DENSITY + 1


def road(**kw) -> calm.Road:
    return calm.Road(**kw)


class TestOwnCost:
    """Each road priced by its own routing cost (stress-number.md section 4; 461c)."""

    @pytest.mark.parametrize(("roadway", "added"), GRADED_TABLE)
    def test_the_costing_reproduces_the_graded_stress_table(self, roadway, added) -> None:
        cls, lanes, kph, lane = roadway
        plain = road(road_class=cls, lanes=lanes, speed_limit_kph=kph, cycle_lane=lane)
        graded = road(road_class=cls, lanes=calm.GRADED_LANES, speed_limit_kph=kph, cycle_lane=lane)
        for u, (lts3, lts4) in zip(USE_ROADS, added, strict=True):
            base = calm.edge_factor(plain, 1, u)
            assert calm.edge_factor(plain, 3, u) - base == pytest.approx(lts3, abs=0.01)
            assert calm.edge_factor(graded, 4, u) - base == pytest.approx(lts4, abs=0.01)

    def test_absolute_factors_worked_by_hand_from_bicyclecost(self) -> None:
        # Urban residential, 30 km/h default, u 0.1: speed penalty (0.75 - 1) x 0.925 + 1,
        # stress 1 x that, accommodation 1: 1 + 1 x (1 - 0.25 x 0.925).
        assert calm.edge_factor(road(road_class="residential", density=URBAN), 1, 0.1) == (
            pytest.approx(1 + 1 * (1 - 0.25 * 0.925), abs=1e-6)
        )
        # Rural residential, 35 km/h: 1 + (1 - 0.125 x 0.925).
        assert calm.edge_factor(road(road_class="residential"), 1, 0.1) == pytest.approx(
            1 + (1 - 0.125 * 0.925), abs=1e-6
        )
        # Secondary, 48 km/h tagged, u 0: road factor 2, class 0.1, speed 48/25 - 0.6 = 1.32;
        # at LTS 3 accommodation 1 + 3.
        sec = road(road_class="secondary", speed_limit_kph=48)
        assert calm.edge_factor(sec, 1, 0.0) == pytest.approx(1 + 1.2 * 1.32, abs=1e-6)
        assert calm.edge_factor(sec, 3, 0.0) == pytest.approx(1 + 4 * 1.2 * 1.32, abs=1e-6)
        # A separated cycleway, u 0.5: accommodation 0.8 x 0.5, stress 1.
        track = road(use="cycleway", road_class="service_other", cycle_lane="separated")
        assert calm.edge_factor(track, 1, 0.5) == pytest.approx(1.4, abs=1e-6)

    @pytest.mark.parametrize("stress", [0, 10, 40, 70, 80, 90])
    def test_an_all_quiet_route_reads_exactly_one(self, stress) -> None:
        # Review B1 and 461d ("1.0 = all calm riding"), urban and rural.
        pricing = calm.Pricing(
            use_roads=presets.use_roads_for(stress), rate=presets.calm_rate_for(stress)
        )
        for quiet in (calm.QUIET_URBAN, calm.QUIET_RURAL):
            pieces = [(3 * MILE, 2, "none", quiet)]
            out = calm.score([span(0, 3 * MILE, 2)], [], pricing, [0, 1.5 * MILE], pieces=pieces)
            assert out["ratio"] == [1.0, 1.0]
            assert out["total_calm_m"] == round(3 * MILE)

    def test_junctions_count_one_for_one_on_the_own_cost_scale(self) -> None:
        # Review R1 and 461d ("1,200 ft = about 0.23 calm mi"): a junction's cost is in feet
        # of quiet riding, so it counts one for one beside each road's own cost.
        pieces = [(1000.0, 2, "none", calm.QUIET_URBAN)]
        out = calm.score([span(0, 1000, 2)], [Event(500, 1000)], DEFAULT, [0], pieces=pieces)
        assert out["total_calm_m"] == round(1000 + 304.8)

    def test_a_path_counts_below_a_quiet_street(self) -> None:
        path = road(
            use="cycleway", road_class="service_other", cycle_lane="dedicated", density=URBAN
        )
        ratio, _ = calm.road_multiplier(1, "path", path, DEFAULT)
        assert ratio == pytest.approx(1.19 / calm.quiet_factor(DEFAULT.use_roads), abs=0.001)

    def test_a_faster_wider_lts_3_road_costs_more_than_a_slow_one(self) -> None:
        slow = road(road_class="tertiary", speed_limit_kph=40)
        fast = road(road_class="primary", lanes=3, speed_limit_kph=72)
        slow_ratio, _ = calm.road_multiplier(3, "none", slow, DEFAULT)
        fast_ratio, _ = calm.road_multiplier(3, "none", fast, DEFAULT)
        assert fast_ratio > 2 * slow_ratio

    def test_a_trail_class_way_never_carries_the_stress_mark(self) -> None:
        path = road(use="footway", road_class="service_other")
        assert calm.edge_factor(path, 3, 0.1) == calm.edge_factor(path, 1, 0.1)

    def test_above_80_the_calm_rate_is_added_to_the_roads_own_cost(self) -> None:
        at90 = calm.Pricing(
            use_roads=presets.use_roads_for(90), rate=presets.calm_rate_for(90), weights=(1, 2, 3)
        )
        r = road(road_class="secondary", lanes=calm.GRADED_LANES, speed_limit_kph=48)
        ratio, _ = calm.road_multiplier(4, "none", r, at90)
        own = calm.edge_factor(r, 4, at90.use_roads) / calm.quiet_factor(at90.use_roads, False)
        assert ratio == pytest.approx(own + at90.rate * 2, abs=1e-9)

    def test_at_the_top_lts_3_and_up_keep_the_worth_rules_price(self) -> None:
        top = calm.Pricing(use_roads=0.0, maxcalm=True)
        r = road(road_class="primary", lanes=2, speed_limit_kph=56)
        assert calm.road_multiplier(3, "none", r, top) == (6.0, True)

    def test_without_attributes_the_tiers_figure_stands_in(self) -> None:
        assert calm.road_multiplier(3, "none", None, DEFAULT) == (
            calm.multiplier(3, "none", DEFAULT),
            False,
        )
        assert calm.road_multiplier(None, None, None, DEFAULT) == (None, True)


class TestGradedAndEdits:
    """Review S2: the graph grades at a rebuild, a stress edit changes the live tier now."""

    GRADED = calm.Road(road_class="primary", lanes=calm.GRADED_LANES, speed_limit_kph=56)
    PLAIN = calm.Road(road_class="primary", lanes=2, speed_limit_kph=56)

    def test_an_lts_4_road_edited_to_2_keeps_the_graphs_cost_and_is_an_estimate(self) -> None:
        ratio, own = calm.road_multiplier(2, "none", self.GRADED, DEFAULT)
        assert own is False
        # The graded edge carries the stress mark whatever the live tier says.
        assert calm.edge_factor(self.GRADED, 2, 0.1) == calm.edge_factor(self.GRADED, 4, 0.1)
        assert ratio == pytest.approx(calm.road_multiplier(4, "none", self.GRADED, DEFAULT)[0])
        pieces = [(1000.0, 2, "none", self.GRADED)]
        out = calm.score([span(0, 1000, 2)], [], DEFAULT, [0], pieces=pieces)
        assert out["estimate"] is True

    def test_an_lts_2_road_edited_to_4_is_an_estimate(self) -> None:
        _ratio, own = calm.road_multiplier(4, "none", self.PLAIN, DEFAULT)
        assert own is False
        pieces = [(1000.0, 4, "none", self.PLAIN)]
        out = calm.score([span(0, 1000, 4)], [], DEFAULT, [0], pieces=pieces)
        assert out["estimate"] is True

    def test_where_they_agree_it_is_not(self) -> None:
        assert calm.road_multiplier(4, "none", self.GRADED, DEFAULT)[1] is True
        assert calm.road_multiplier(3, "none", self.PLAIN, DEFAULT)[1] is True
        no_trail = calm.Pricing(use_roads=0.1, no_trail=True)
        assert calm.road_multiplier(4, "none", self.PLAIN, no_trail)[1] is True


class TestRoadSpeed:
    def test_a_tagged_speed_stands_and_rough_pavement_lowers_it(self) -> None:
        assert calm.road_speed_kph(road(road_class="primary", speed_limit_kph=56)) == 56
        rough = road(road_class="primary", speed_limit_kph=56, surface="paved_rough")
        assert calm.road_speed_kph(rough) == 46
        slow_rough = road(road_class="tertiary", speed_limit_kph=40, surface="gravel")
        assert calm.road_speed_kph(slow_rough) == 35

    def test_an_untagged_road_takes_its_class_default_urban_or_rural(self) -> None:
        assert calm.road_speed_kph(road(road_class="secondary")) == 60
        assert calm.road_speed_kph(road(road_class="secondary", density=URBAN)) == 49
        assert calm.road_speed_kph(road(road_class="residential")) == 35
        assert calm.road_speed_kph(road(road_class="residential", density=URBAN)) == 30
        circle = road(road_class="secondary", density=URBAN, roundabout=True)
        assert calm.road_speed_kph(circle) == 25
        drive = road(use="driveway", road_class="service_other", density=URBAN)
        assert calm.road_speed_kph(drive) == 10
        rough = road(road_class="tertiary", density=URBAN, surface="dirt")
        assert calm.road_speed_kph(rough) == 20

    def test_untagged_links(self) -> None:
        # A ramp off a primary: 75 x 0.85 rural, x 0.8 urban; a turn channel x 1.25.
        assert calm.road_speed_kph(road(use="ramp", road_class="primary")) == 64
        assert calm.road_speed_kph(road(use="ramp", road_class="primary", density=URBAN)) == 60
        assert calm.road_speed_kph(road(use="turn_channel", road_class="tertiary")) == 63

    def test_a_graded_edge_is_at_the_graphs_top_speed_as_a_tagged_one(self) -> None:
        # Review N1: the graded speed is a tagged one, so the tagged speed's adjustments apply.
        assert calm.road_speed_kph(road(road_class="residential", lanes=15)) == 140
        rough = road(road_class="residential", lanes=15, surface="paved_rough")
        assert calm.road_speed_kph(rough) == 130
        channel = road(use="turn_channel", road_class="primary", lanes=15)
        assert calm.road_speed_kph(channel) == 175


class TestRoadOfEdge:
    def test_an_edge_with_attributes(self) -> None:
        edge = {
            "use": "road",
            "road_class": "primary",
            "lane_count": 2,
            "cycle_lane": "shared",
            "shoulder": False,
            "truck_route": True,
            "bicycle_network": 2,
            "speed_limit": 30,
            "density": 12,
            "roundabout": False,
            "surface": "paved_smooth",
        }
        got = calm.road_of_edge(edge, miles=True)
        assert got is not None
        assert got.lanes == 2 and got.cycle_lane == "shared" and got.truck_route
        assert got.bike_network is True
        assert got.speed_limit_kph == pytest.approx(48.28, abs=0.01)
        assert calm.road_of_edge({**edge, "speed_limit": "unlimited"}).speed_limit_kph is None

    def test_an_edge_without_them_has_none(self) -> None:
        assert calm.road_of_edge({"way_id": 1, "length": 0.1}) is None


class TestScoreFromPieces:
    QUIET = calm.QUIET_URBAN
    BUSY = calm.Road(road_class="primary", lanes=2, speed_limit_kph=56, density=URBAN)

    def test_every_piece_priced_by_its_own_cost_is_not_an_estimate(self) -> None:
        pieces = [(800.0, 2, "none", self.QUIET), (800.0, 3, "none", self.BUSY)]
        out = calm.score([span(0, 800, 2), span(800, 1600, 3)], [], DEFAULT, [0], pieces=pieces)
        assert out["estimate"] is False
        busy, _ = calm.road_multiplier(3, "none", self.BUSY, DEFAULT)
        assert [s["ratio"] for s in out["steps"]] == [1.0, round(busy, 2)]
        assert out["total_calm_m"] == pytest.approx(800 + 800 * busy, abs=2)

    def test_a_piece_with_no_attributes_makes_it_an_estimate(self) -> None:
        pieces = [(800.0, 2, "none", self.QUIET), (800.0, 3, "none", None)]
        out = calm.score([span(0, 1600, 2)], [], DEFAULT, [0], pieces=pieces)
        assert out["estimate"] is True
        assert calm.score([span(0, 1600, 2)], [], DEFAULT, [0])["estimate"] is True

    def test_a_folded_piece_is_rated_and_graded_as_its_section(self) -> None:
        # A short busy road folded into a quiet section counts at its own cost as the
        # section's tier: no stress mark, as the map colours it.
        pieces = [(950.0, 2, "none", self.QUIET), (8.0, 3, "none", self.BUSY)]
        out = calm.score([span(0, 958, 2)], [], DEFAULT, [500], pieces=pieces)
        busy, _ = calm.road_multiplier(2, "none", self.BUSY, DEFAULT)
        mean = (950 + 8 * busy) / 958
        assert out["steps"][0]["ratio"] == pytest.approx(mean, abs=0.01)
        assert out["ratio"] == [pytest.approx(mean, abs=0.01)]
        assert out["estimate"] is False

    def test_a_tiny_rated_piece_in_an_unrated_section_is_no_island(self) -> None:
        # Review S1's case: sections 2 / None / 2, a 5 m LTS 2 piece at 2000 m inside the
        # unrated one, and a 1,200 ft orange junction there.
        pieces = [
            (1000.0, 2, "none", self.QUIET),
            (1000.0, None, None, None),
            (5.0, 2, "none", self.QUIET),
            (995.0, None, None, None),
            (1000.0, 2, "none", self.QUIET),
        ]
        spans = [span(0, 1000, 2), span(1000, 3000, None, None), span(3000, 4000, 2)]
        events = [Event(2002, 1200, "orange", True)]
        samples = list(range(0, 4001, 30))
        out = calm.score(spans, events, DEFAULT, samples, pieces=pieces)
        assert out["points"] == []
        assert out["rated_m"] == 2000
        assert max(r for r in out["ratio"] if r is not None) == pytest.approx(1.0)
        i = calm.peak_index(spans, events, DEFAULT, samples, pieces=pieces)
        assert out["ratio"][i] == pytest.approx(1.0)

    def test_a_folded_avoid_piece_adds_no_entry_charge(self) -> None:
        pieces = [(500.0, 2, "none", self.QUIET), (6.0, 5, "none", self.BUSY)]
        pieces.append((494.0, 2, "none", self.QUIET))
        out = calm.score([span(0, 1000, 2)], [], DEFAULT, [0], pieces=pieces)
        assert [p for p in out["points"] if p["kind"] == "avoid_entry"] == []

    def test_unrated_pieces_count_in_neither_and_their_junctions_not_at_all(self) -> None:
        pieces = [(100.0, 2, "none", self.QUIET), (1500.0, None, None, None)]
        spans = [span(0, 100, 2), span(100, 1600, None, None)]
        out = calm.score(spans, [Event(800, 1200, "orange", True)], DEFAULT, [0], pieces=pieces)
        assert out["rated_m"] == 100
        assert out["points"] == []
