"""The same rules in every jurisdiction unless the law differs (the owner,
2026-10-31): West Virginia's speed law, and a state left out of the urban list."""

from __future__ import annotations

from pipeline.states import states_without_urban
from routemaker.stress import Stress, classify, rural_floor, statutory_default_mph


class TestWestVirginiaSpeedLaw:
    """W. Va. Code 17C-6-1(b): 25 in a business or residence district, 55 on
    open country highways - Virginia's figures."""

    def test_statutory_defaults(self):
        assert statutory_default_mph({}, "WV", urban=True, divided=False) == 25.0
        assert statutory_default_mph({}, "WV", urban=False, divided=False) == 55.0

    def test_no_separate_unpaved_figure(self):
        gravel = {"surface": "gravel"}
        assert statutory_default_mph(gravel, "WV", urban=False, divided=False) == 55.0

    # A town primary with a painted lane: read at 35 mph from the MD/VA/WV urban
    # table, not the generic urban table's 40 that WV took before.
    LANED_PRIMARY = {"highway": "primary", "cycleway": "lane"}

    def test_an_unposted_town_primary_reads_as_in_virginia(self):
        wv = classify(self.LANED_PRIMARY, urban=True, jurisdiction="WV")
        va = classify(self.LANED_PRIMARY, urban=True, jurisdiction="VA")
        unknown = classify(self.LANED_PRIMARY, urban=True, jurisdiction="PA")
        assert (wv.tier, wv.rule) == (va.tier, va.rule)
        assert "35 mph" in wv.rule and "40 mph" in unknown.rule

    def test_a_zone_tag_names_west_virginia(self):
        tags = {**self.LANED_PRIMARY, "maxspeed:type": "US-WV:urban"}
        wv = classify(self.LANED_PRIMARY, urban=True, jurisdiction="WV")
        assert classify(tags, urban=True).rule == wv.rule


class TestUrbanListCoversEveryState:
    def test_a_state_with_no_urban_way_is_named(self):
        state_of = {i: "MD" for i in range(1500)} | {i: "WV" for i in range(1500, 3000)}
        urban = frozenset(range(100))
        assert states_without_urban(state_of, urban) == ["WV"]

    def test_every_state_with_towns_passes(self):
        state_of = {i: "MD" for i in range(1500)} | {i: "WV" for i in range(1500, 3000)}
        urban = frozenset({1, 1501})
        assert states_without_urban(state_of, urban) == []

    def test_a_sliver_of_a_state_is_not_checked(self):
        state_of = {i: "MD" for i in range(1500)} | {i: "PA" for i in range(1500, 1600)}
        assert states_without_urban(state_of, frozenset({1})) == []


class TestOwnerRulesEverywhere:
    """The owner's rules read the same in every state (2026-10-31, Q1-Q4)."""

    def test_a_quiet_count_keeps_the_narrow_road_reading(self):
        lane = {"highway": "unclassified", "lane_markings": "no"}
        # The rural floor is applied by the rebuild after the classifier.
        counted = rural_floor(classify(lane, urban=False, aadt=300, jurisdiction="VA"), lane, False)
        uncounted = rural_floor(classify(lane, urban=False, jurisdiction="MD"), lane, False)
        assert counted.tier is uncounted.tier is Stress.LTS2
        assert "narrow rural road" in counted.rule

    def test_a_busy_count_still_outranks_it(self):
        lane = {"highway": "unclassified", "lane_markings": "no"}
        assert "narrow rural road" not in classify(lane, urban=False, aadt=4_000).rule

    def test_virginia_town_minor_roads_at_25(self):
        rule = classify({"highway": "tertiary"}, urban=True, jurisdiction="VA").rule
        assert "25 mph" in rule
        assert "30 mph" in classify({"highway": "tertiary"}, urban=True, jurisdiction="MD").rule

    def test_an_untagged_fast_multilane_highway_is_4_5(self):
        road = {"highway": "primary", "maxspeed": "55 mph", "lanes": "4"}
        for urban in (True, False):
            result = classify(road, urban=urban)
            assert (result.tier, result.half) == (Stress.LTS4, True)
            assert result.rule.startswith("multilane highway posted 55 mph")

    def test_a_two_lane_55_road_is_not_taken(self):
        road = {"highway": "primary", "maxspeed": "55 mph", "lanes": "2"}
        assert not classify(road, urban=False).half

    def test_a_divided_carriageway_counts_as_multilane(self):
        road = {"highway": "trunk", "maxspeed": "55 mph", "oneway": "yes", "lanes": "1"}
        assert classify(road, urban=False, divided=True).half

    def test_a_busy_two_lane_street_is_2_5(self):
        street = {"highway": "residential", "maxspeed": "25 mph"}
        busy = classify(street, aadt=6_000)
        assert (busy.tier, busy.half) == (Stress.LTS2, True)
        assert not classify(street, aadt=4_000).half

    def test_a_painted_lane_on_a_busy_street_is_at_least_2_5(self):
        street = {"highway": "residential", "maxspeed": "25 mph", "cycleway": "lane"}
        busy = classify(street, aadt=12_000)
        assert (busy.tier, busy.half) == (Stress.LTS2, True)
        assert not classify(street, aadt=6_000).half
