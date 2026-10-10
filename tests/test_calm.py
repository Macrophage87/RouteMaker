"""The rolling stress score, calm miles per mile (`routemaker.calm`; OWNER-DECISIONS 460.12,
461, 461a-e, 469b; docs/stress/stress-number.md section 4)."""

from __future__ import annotations

from dataclasses import dataclass

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

    def test_the_bands_are_the_half_step_midpoints(self) -> None:
        # stress-number.md "Words as a guide": 2.65 and 9.3 for Default.
        low, high = calm.bands(DEFAULT)
        assert low == pytest.approx(2.67, abs=0.05)
        assert high == pytest.approx(9.3, abs=0.05)


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
