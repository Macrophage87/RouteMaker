"""The independent review of the road formula (r1, 2026-11-13): each finding's failing input
as a test, and a test for each behaviour whose mutant the review found alive.

The rule the fixes share (the owner, 2026-11-13): missing data never LOWERS a level.
"""

from __future__ import annotations

import itertools

import pytest

from routemaker import agency_lts, stress
from routemaker.agency_lts import AgencyRating
from routemaker.stress import (
    LANE_TOO_NARROW_RULE,
    PARKING_NOT_MAPPED_RULE,
    RURAL_MIN_RULE,
    Stress,
    classify,
    default_speed,
    meets_width,
    mixed_traffic_level,
    rural_minimum_applies,
    rural_shoulder,
    rural_table_applies,
)

SPEEDS = (20, 25, 30, 35, 40, 45, 50, 55)
CLASSES = ("residential", "unclassified", "tertiary", "secondary", "primary", "trunk")


def level(tags, **kwargs) -> float:
    result = classify(tags, **kwargs)
    return int(result.tier) + (0.5 if result.half else 0)


# --- Finding 1: parking not mapped beside a painted lane -------------------------------


class TestParkingNotMapped:
    BIG = {"highway": "primary", "maxspeed": "45 mph", "lanes": "6"}

    def test_the_reviews_inputs(self):
        laned = {**self.BIG, "cycleway": "lane"}
        assert level(self.BIG, aadt=40_000) == 4
        assert level(laned, aadt=40_000) == 4
        assert level({**laned, "parking:both": "no"}, aadt=40_000) == 4
        fast = {"highway": "primary", "maxspeed": "50 mph", "lanes": "2", "cycleway": "lane"}
        assert level(fast, aadt=12_000) == 4
        assert level({**fast, "parking:both": "no"}, aadt=12_000) == 4

    def test_the_rule_and_the_evidence_say_parking_is_not_mapped(self):
        result = classify({**self.BIG, "cycleway": "lane"}, aadt=40_000)
        assert PARKING_NOT_MAPPED_RULE in result.rule
        assert "parking beside the lane (not mapped" in result.evidence
        mapped = classify({**self.BIG, "cycleway": "lane", "parking:both": "no"}, aadt=40_000)
        assert PARKING_NOT_MAPPED_RULE not in mapped.rule

    def test_unknown_parking_is_the_worse_of_the_two_tables_in_every_cell(self):
        for mph, lanes, width, oneway in itertools.product(
            (20, 25, 30, 35, 40, 45, 50), (1, 2, 3, 4), (None, 1.2, 1.5, 1.8, 2.4, 4.6), (0, 1)
        ):

            def read(parking, mph=mph, lanes=lanes, width=width, oneway=oneway):
                return stress._bike_lane_tier(mph, lanes, width, parking, oneway=bool(oneway))[0]

            assert read(None) == max(read(True), read(False)), (mph, lanes, width, oneway)

    def test_mapping_parking_either_way_never_raises_the_level(self):
        checked = lowered = 0
        for highway, mph, lanes, aadt, oneway, urban, width in itertools.product(
            CLASSES,
            SPEEDS,
            (1, 2, 3),
            (None, 500, 2_000, 9_000, 40_000),
            (False, True),
            (True, False),
            (None, "1.2", "1.8"),
        ):
            road = {
                "highway": highway,
                "maxspeed": f"{mph} mph",
                "lanes": str(lanes if oneway else 2 * lanes),
                "cycleway": "lane",
            }
            if oneway:
                road["oneway"] = "yes"
            if width:
                road["cycleway:width"] = width
            unknown = level(road, aadt=aadt, urban=urban)
            for parking in ("no", "lane"):
                mapped = level({**road, "parking:both": parking}, aadt=aadt, urban=urban)
                checked += 1
                lowered += mapped < unknown
                assert mapped <= unknown, (road, aadt, urban, parking, unknown, mapped)
        assert checked > 10_000 and lowered > 500


# --- Findings 2 and 3: statutes are data; evidence says statute or class default -------


class TestSpeedLawIsData:
    def test_the_district_alley_is_15_and_every_other_street_20(self):
        alley = {"highway": "service", "service": "alley"}
        assert default_speed(alley, "DC", True, False) == (15.0, "statute")
        assert classify(alley, jurisdiction="DC").default_speed_mph == 15.0
        for highway in (*CLASSES, "service", "road"):
            assert default_speed({"highway": highway}, "DC", True, False) == (20.0, "statute")

    def test_marylands_residential_default_is_the_statutes_30(self):
        assert default_speed({"highway": "residential"}, "MD", True, False) == (30.0, "statute")
        assert default_speed({"highway": "residential"}, "MD", True, True) == (35.0, "statute")
        assert default_speed({"highway": "residential"}, "VA", True, False) == (25.0, "statute")

    def test_a_major_urban_road_reads_our_default_and_says_so(self):
        mph, source = default_speed({"highway": "primary"}, "VA", True, False)
        assert (mph, source) == (35.0, "class default")
        result = classify({"highway": "primary"}, jurisdiction="VA")
        assert "class default, our default" in result.evidence

    def test_the_evidence_says_statute_only_where_the_statute_supplied_the_speed(self):
        law = classify({"highway": "residential"}, jurisdiction="MD")
        assert "the statute's default" in law.evidence
        for tags, urban in (
            ({"highway": "service"}, True),
            ({"highway": "trunk"}, True),
            ({"highway": "road"}, True),
            ({"highway": "road"}, False),
        ):
            for state in ("MD", "VA", None):
                result = classify(tags, urban=urban, jurisdiction=state)
                if result.speed_source != "statute":
                    assert "statute" not in result.evidence, (tags, urban, state)

    def test_a_posted_road_has_no_speed_source(self):
        result = classify({"highway": "residential", "maxspeed": "25 mph"}, jurisdiction="MD")
        assert result.speed_source is None
        assert "the posted limit, not measured" in result.evidence

    def test_a_trail_is_not_said_to_have_a_posted_limit(self):
        assert classify({"highway": "cycleway"}).evidence == "not rated from road inputs"


# --- Findings 4 and 5: counts, estimates, no floor -------------------------------------


class TestCountsAreMonotonic:
    def test_the_reviews_one_way_local_streets(self):
        local = {"highway": "residential", "oneway": "yes", "lanes": "2"}
        assert level(local, jurisdiction="DC") == 3  # Furth's two-lane row, any count
        assert level({**local, "maxspeed": "25 mph"}, aadt=700) == 3
        assert level({**local, "maxspeed": "30 mph"}) == 3  # was 4 on a flat 8,001
        assert level({"highway": "tertiary", "lanes": "4", "maxspeed": "30 mph"}) == 3

    def test_more_traffic_never_lowers_a_level_counted_or_estimated(self):
        counts = (0, 300, 750, 751, 1_000, 1_001, 1_500, 1_501, 3_000, 3_001, 8_000, 8_001, 30_000)
        for highway, mph, lanes, urban, key in itertools.product(
            CLASSES, SPEEDS, ("2", "4", "6"), (True, False), ("aadt", "estimated_aadt")
        ):
            road = {"highway": highway, "maxspeed": f"{mph} mph", "lanes": lanes}
            levels = [level(road, urban=urban, **{key: n}) for n in counts]
            assert levels == sorted(levels), (road, urban, key, levels)

    def test_a_count_and_an_estimate_of_the_same_size_give_the_same_level(self):
        for highway, mph, n in itertools.product(CLASSES, SPEEDS, (300, 1_200, 5_000, 20_000)):
            road = {"highway": highway, "maxspeed": f"{mph} mph"}
            assert level(road, aadt=n) == level(road, estimated_aadt=n) or n >= 18_000


# --- Findings 6 to 9 and 12: rural roads ------------------------------------------------


class TestRuralBySettingAndSpeed:
    def test_a_trunk_reads_the_rural_table_as_a_primary_does(self):
        for highway in ("primary", "trunk", "primary_link", "trunk_link"):
            road = {
                "highway": highway,
                "maxspeed": "55 mph",
                "lanes": "2",
                "shoulder": "both",
                "shoulder:width": "2.5",
            }
            assert [level(road, urban=False, aadt=n) for n in (300, 1_200, 5_000)] == [2, 2, 2]
            bare = {"highway": highway, "maxspeed": "55 mph", "lanes": "2"}
            assert level(bare, urban=False, aadt=300) == 2

    def test_what_is_not_a_road_through_the_country_is_left_out(self):
        for highway in ("service", "track", "living_street"):
            assert not rural_table_applies({"highway": highway}, False, 1, False)
        assert level({"highway": "track"}, urban=False) == 1

    def test_a_wider_road_is_not_the_two_lane_table(self):
        assert rural_table_applies({"highway": "primary"}, False, 1, False)
        assert not rural_table_applies({"highway": "primary"}, False, 2, False)
        wide = {"highway": "primary", "maxspeed": "50 mph", "lanes": "4"}
        result = classify(wide, urban=False, aadt=300)
        assert result.rule.startswith("mixed traffic") and result.tier is Stress.LTS4
        assert not result.rural_minimum

    def test_a_marked_lane_is_never_worse_than_a_shoulder_of_its_width(self):
        road = {"highway": "tertiary"}
        shoulder = {**road, "shoulder": "both", "shoulder:width": "1.8"}
        lane = {**road, "cycleway": "lane", "cycleway:width": "1.8", "parking:both": "no"}
        assert level(shoulder, urban=False, aadt=1_000) == 2
        assert level(lane, urban=False, aadt=1_000) == 2
        for mph, n, width in itertools.product(
            (None, 35, 45, 55), (300, 1_000, 5_000, 9_000), ("1.2", "1.5", "1.8", "2.4")
        ):
            base = dict(road) if mph is None else {**road, "maxspeed": f"{mph} mph"}
            strip = {**base, "shoulder": "both", "shoulder:width": width}
            marked = {**base, "cycleway": "lane", "cycleway:width": width, "parking:both": "no"}
            assert level(marked, urban=False, aadt=n) <= level(strip, urban=False, aadt=n)

    def test_a_lane_measured_on_one_side_only_is_an_unmeasured_lane(self):
        road = {"highway": "secondary", "maxspeed": "50 mph", "lanes": "2"}
        one = {**road, "cycleway:left": "lane", "cycleway:right": "lane"}
        assert stress.lane_width_m({**one, "cycleway:right:width": "2.0"}) is None
        assert stress.lane_width_m({**one, "cycleway:both:width": "2.0"}) == 2.0
        half = level({**one, "cycleway:right:width": "2.0"}, urban=False)
        assert half == level(one, urban=False)
        oneway = {**road, "oneway": "yes", "cycleway:right": "lane", "cycleway:right:width": "2.0"}
        assert stress.lane_width_m(oneway) == 2.0

    def test_six_feet_is_mapped_as_one_point_eight_metres(self):
        assert meets_width(1.8, 6) and not meets_width(1.7, 6)
        assert meets_width(1.2, 4) and not meets_width(1.1, 4)
        # 15 ft: a 5 ft lane and a 10 ft parking lane, each converted, meet it; 4.5 m does not.
        assert meets_width(1.52 + 3.05, 15) and not meets_width(4.5, 15)
        town = {
            "highway": "tertiary",
            "maxspeed": "30 mph",
            "cycleway": "lane",
            "parking:both": "no",
        }
        assert level({**town, "cycleway:width": "1.8"}, aadt=5_000) == 1
        assert level({**town, "cycleway:width": "1.7"}, aadt=5_000) == 2
        rural = {"highway": "secondary", "shoulder": "both"}
        assert rural_shoulder({**rural, "shoulder:width": "1.8"}) == stress.SHOULDER_WIDE
        assert rural_shoulder({**rural, "shoulder:width": "1.7"}) == stress.SHOULDER_RIDEABLE
        assert level({**rural, "shoulder:width": "1.8"}, urban=False, aadt=5_000) == 2
        assert level({**rural, "shoulder:width": "1.7"}, urban=False, aadt=5_000) == 3

    @pytest.mark.parametrize("highway", CLASSES)
    @pytest.mark.parametrize("state", ["MD", "VA", "WV", None])
    @pytest.mark.parametrize("sidewalk", [False, True])
    def test_a_sign_that_says_what_the_default_says_changes_nothing(self, highway, state, sidewalk):
        road = {"highway": highway}
        if sidewalk:
            road["sidewalk"] = "both"
        for urban in (True, False):
            unposted = classify(road, urban=urban, jurisdiction=state)
            mph = default_speed(road, state, urban, False)[0]
            posted = classify({**road, "maxspeed": f"{mph:g} mph"}, urban=urban, jurisdiction=state)
            assert (posted.tier, posted.half) == (unposted.tier, unposted.half), (urban, mph)

    def test_the_reviews_sign_cases(self):
        street = {"highway": "residential"}
        assert level(street, urban=False) == level({**street, "maxspeed": "25 mph"}, urban=False)
        lane = {"highway": "unclassified", "maxspeed": "25 mph"}
        assert level(lane, urban=False) == 2
        assert level({**lane, "sidewalk": "both"}, urban=False) == 1

    def test_built_up_stops_at_25(self):
        walked = {"highway": "tertiary", "sidewalk": "both"}
        assert not rural_table_applies(walked, False, 1, False, 25.0)
        assert rural_table_applies(walked, False, 1, False, 30.0)
        assert classify({**walked, "maxspeed": "30 mph"}, urban=False, aadt=800).rural_minimum
        assert not classify({**walked, "maxspeed": "25 mph"}, urban=False, aadt=800).rural_minimum

    def test_the_rural_minimum_holds_after_a_lane_or_a_shoulder(self):
        road = {"highway": "tertiary", "maxspeed": "30 mph"}
        lane = {**road, "cycleway": "lane", "cycleway:width": "2.0", "parking:both": "no"}
        strip = {**road, "shoulder": "both", "shoulder:width": "2.0"}
        assert level(lane, aadt=300) == 1 and level(strip, aadt=300) == 1  # in town
        for tags in (lane, strip):
            result = classify(tags, urban=False, aadt=300)
            assert result.tier is Stress.LTS2 and RURAL_MIN_RULE in result.rule

    def test_a_measured_speed_decides_which_rural_table_is_read(self):
        road = {"highway": "tertiary", "maxspeed": "35 mph"}
        assert level(road, urban=False, aadt=2_000) == 3
        fast = classify(road, urban=False, aadt=2_000, observed_speed_mph=50.0)
        assert fast.tier is Stress.LTS4 and fast.rule.startswith("rural road")
        slow = classify({"highway": "tertiary", "maxspeed": "50 mph"}, urban=False, aadt=2_000)
        assert slow.tier is Stress.LTS4


# --- Finding 10: the narrow-road rule ----------------------------------------------------


class TestNarrowRoad:
    def test_an_uncounted_winding_minor_road_is_2_tertiary_or_unclassified(self):
        for highway in ("unclassified", "tertiary"):
            result = classify({"highway": highway}, urban=False, winding=True)
            assert result.tier is Stress.LTS2, highway
            assert result.speed_source == "narrow road rule"
        assert level({"highway": "tertiary"}, urban=False) == 3

    def test_the_rule_stops_at_the_quiet_count(self):
        # Above 1,500 a day the road is read at its default speed again: the rural table.
        road = {"highway": "unclassified"}
        assert level(road, urban=False, winding=True, aadt=1_500) == 2
        assert level(road, urban=False, winding=True, aadt=1_501) == level(
            road, urban=False, aadt=1_501
        )


# --- Finding 11: Furth's minimum widths ----------------------------------------------------


class TestLaneMinimums:
    STREET = {"highway": "tertiary", "maxspeed": "30 mph", "parking:both": "no"}

    def test_a_lane_under_four_feet_earns_no_lane_credit(self):
        bare = classify(self.STREET, aadt=5_000)
        thin = classify({**self.STREET, "cycleway": "lane", "cycleway:width": "0.9"}, aadt=5_000)
        assert bare.tier is thin.tier is Stress.LTS3
        assert LANE_TOO_NARROW_RULE in thin.rule
        four = classify({**self.STREET, "cycleway": "lane", "cycleway:width": "1.2"}, aadt=5_000)
        assert four.tier is Stress.LTS2 and LANE_TOO_NARROW_RULE not in four.rule

    def test_a_reach_under_twelve_feet_earns_none_either(self):
        parked = {"highway": "tertiary", "maxspeed": "25 mph", "parking:both": "lane"}
        lane = {**parked, "cycleway": "lane", "cycleway:width": "1.5"}
        short = classify(lane, aadt=5_000, parking_width_m=2.0)  # 11.5 ft
        assert LANE_TOO_NARROW_RULE in short.rule and short.tier is Stress.LTS3
        enough = classify(lane, aadt=5_000, parking_width_m=2.2)  # 12.1 ft
        assert enough.tier is Stress.LTS2

    def test_an_unmeasured_lane_keeps_the_narrow_row(self):
        lane = classify({**self.STREET, "cycleway": "lane"}, aadt=5_000)
        assert lane.tier is Stress.LTS2 and "cycleway width" in lane.assumed


# --- Finding 13: the rebuild's rural check reads the classifier's verdict ------------------


class TestRuralMinimumVerdict:
    def test_the_verdict_is_on_the_result(self):
        assert classify({"highway": "tertiary"}, urban=False).rural_minimum
        assert not classify({"highway": "tertiary"}, urban=True).rural_minimum
        town = {"highway": "residential", "maxspeed": "25 mph"}
        assert not classify(town, urban=False).rural_minimum
        track = {"highway": "secondary", "cycleway:both": "track"}
        assert not classify(track, urban=False).rural_minimum
        closed = {"highway": "tertiary", "motor_vehicle": "no", "bicycle": "yes"}
        assert not classify(closed, urban=False).rural_minimum
        private = {"highway": "tertiary", "motor_vehicle": "private"}
        assert classify(private, urban=False).rural_minimum

    def test_no_way_the_verdict_holds_is_below_2(self):
        for highway, mph, n, extra in itertools.product(
            (*CLASSES, "road"),
            (None, 20, 25, 30, 45),
            (None, 100, 5_000),
            (
                {},
                {"sidewalk": "both"},
                {"cycleway": "lane", "cycleway:width": "2"},
                {"surface": "gravel"},
            ),
        ):
            road = {"highway": highway, **extra}
            if mph:
                road["maxspeed"] = f"{mph} mph"
            for state in ("MD", "VA", None):
                result = classify(road, urban=False, aadt=n, jurisdiction=state)
                if result.rural_minimum:
                    assert result.tier >= Stress.LTS2, (road, n, state)
                elif result.tier is Stress.LTS1:
                    assert not rural_minimum_applies(road, state) or n is not None

    def test_the_tag_only_fallback_asks_the_classifier(self):
        assert rural_minimum_applies({"highway": "tertiary"})
        assert not rural_minimum_applies({"highway": "residential", "maxspeed": "25 mph"})
        assert not rural_minimum_applies({"highway": "residential"}, "VA")
        assert rural_minimum_applies({"highway": "residential"}, "MD")


# --- Finding 15 and the surviving mutants ---------------------------------------------------


class TestMutantsTheReviewFoundAlive:
    def test_a_carriageway_of_a_divided_road_is_scored_two_way(self):
        way = {"highway": "residential", "oneway": "yes", "lanes": "1", "maxspeed": "35 mph"}
        street = classify(way, aadt=900)
        carriageway = classify(way, aadt=900, divided=True)
        assert "single lane" in street.rule and street.tier is Stress.LTS2
        assert "unlaned" in carriageway.rule and carriageway.tier is Stress.LTS3
        assert (carriageway.oneway, carriageway.graph_oneway) == (False, True)

    LANE = {
        "highway": "tertiary",
        "maxspeed": "25 mph",
        "cycleway": "lane",
        "cycleway:width": "1.52",
    }

    def test_an_agencys_parking_width_is_added_to_the_lanes_reach(self):
        parked = {**self.LANE, "parking:both": "lane"}
        # 5 ft and 10 ft, each converted to metres: exactly Furth's 15 ft, inside the tolerance.
        assert level(parked, aadt=5_000, parking_width_m=3.05) == 1
        assert level(parked, aadt=5_000) == 2
        assert level(parked, aadt=5_000, parking_width_m=2.9) == 2

    def test_parking_is_read_on_the_lanes_own_side(self):
        street = {
            "highway": "tertiary",
            "maxspeed": "25 mph",
            "oneway": "yes",
            "lanes": "1",
            "cycleway:left": "lane",
            "cycleway:left:width": "1.9",
            "parking:left": "no",
            "parking:right": "lane",
        }
        assert level(street, aadt=5_000) == 1
        assert level({**street, "parking:left": "lane"}, aadt=5_000) == 2

    def test_the_speed_columns_include_their_top_edge(self):
        assert mixed_traffic_level(23.5, 2_000)[0] == mixed_traffic_level(20, 2_000)[0] == 2
        assert mixed_traffic_level(23.6, 2_000)[0] == mixed_traffic_level(25, 2_000)[0] == 3
        unlaned = stress.ROW_UNLANED
        assert mixed_traffic_level(28.5, 100, unlaned)[0] == 1
        assert mixed_traffic_level(28.6, 100, unlaned)[0] == 2
        assert stress._bike_lane_tier(28.5, 1, 4.6, True)[0] == 1
        assert stress._bike_lane_tier(28.6, 1, 4.6, True)[0] == 2

    def test_a_wide_one_way_beside_parking_reads_furths_one_way_row(self):
        # "1-way multilane", reach 15 ft or more: LTS 2 at 25 mph whatever the lane count.
        assert stress._bike_lane_tier(25, 3, 4.6, True, oneway=True)[0] == 2
        assert stress._bike_lane_tier(25, 3, 4.6, True, oneway=False)[0] == 3

    def test_a_speed_list_is_read_as_its_highest_part(self):
        listed = classify({"highway": "tertiary", "maxspeed": "25 mph;40 mph"}, aadt=2_000)
        assert (
            listed.tier is classify({"highway": "tertiary", "maxspeed": "40 mph"}, aadt=2_000).tier
        )
        assert listed.tier is Stress.LTS4

    @pytest.mark.parametrize("agency", sorted(agency_lts.AGENCIES))
    @pytest.mark.parametrize("rated", [1, 2, 2.5, 3, 4, 5])
    @pytest.mark.parametrize("facility", [False, True])
    def test_no_agency_rating_moves_a_level(self, agency, rated, facility):
        assert agency in agency_lts.COMPARISON_ONLY
        for tags, count in (
            ({"highway": "residential"}, None),
            ({"highway": "secondary", "maxspeed": "35 mph", "lanes": "4"}, 20_000),
            ({"highway": "tertiary", "cycleway": "lane"}, 6_000),
            ({"highway": "primary", "maxspeed": "45 mph"}, None),
        ):
            formula = classify(tags, aadt=count)
            result = agency_lts.apply(
                formula,
                [AgencyRating(agency, rated)],
                facility_mapped=facility,
                painted_lane=facility,
            )
            assert (result.tier, result.half) == (formula.tier, formula.half), (tags, result.rule)
            assert result.agency_ratings, "the rating is still recorded"
