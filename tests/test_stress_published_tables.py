"""The classifier against the published tables it is written from (2026-11-13).

Furth, "Level of Traffic Stress Criteria for Road Segments, version 2.2 (May, 2022)", and
Oregon DOT's Analysis Procedures Manual chapter 14 (07/2025), Exhibit 14-17. The cells are
typed here from the sources a second time, so a slip in `routemaker.stress` shows.
"""

from __future__ import annotations

import itertools

import pytest

from routemaker import stress
from routemaker.stress import (
    CLASS_COUNT,
    CLASS_COUNT_RULE,
    ESTIMATE_COUNT_RULE,
    NOTE_4_RULE,
    ROW_SINGLE,
    ROW_THREE_LANES,
    ROW_TWO_LANES,
    ROW_UNLANED,
    RURAL_MIN_RULE,
    VOLUME_GATES,
    class_count,
    classify,
    mixed_traffic_level,
    mixed_traffic_row,
    rural_road_level,
    rural_shoulder,
)
from routemaker.tags import cycleway_shoulder

SPEEDS = (20, 25, 30, 35, 40, 45, 55)


def level(tags, **kwargs) -> float:
    result = classify(tags, **kwargs)
    return int(result.tier) + (0.5 if result.half else 0)


# Furth v2.2, "Bikes in mixed traffic": (row, a count in the band) -> levels at SPEEDS.
FURTH_MIXED = {
    (ROW_UNLANED, 0): (1, 1, 2, 2, 3, 3, 3),
    (ROW_UNLANED, 750): (1, 1, 2, 2, 3, 3, 3),
    (ROW_UNLANED, 751): (1, 1, 2, 3, 3, 3, 3),
    (ROW_UNLANED, 1500): (1, 1, 2, 3, 3, 3, 3),
    (ROW_UNLANED, 1501): (2, 2, 2, 3, 3, 4, 4),
    (ROW_UNLANED, 3000): (2, 2, 2, 3, 3, 4, 4),
    (ROW_UNLANED, 3001): (2, 2, 3, 3, 4, 4, 4),
    (ROW_SINGLE, 1000): (1, 1, 2, 2, 3, 3, 3),
    (ROW_SINGLE, 1001): (2, 2, 2, 3, 3, 4, 4),
    (ROW_SINGLE, 1500): (2, 2, 2, 3, 3, 4, 4),
    (ROW_SINGLE, 1501): (2, 3, 3, 3, 4, 4, 4),
    (ROW_SINGLE, 30000): (2, 3, 3, 3, 4, 4, 4),
    (ROW_TWO_LANES, 8000): (3, 3, 3, 3, 4, 4, 4),
    (ROW_TWO_LANES, 8001): (3, 3, 4, 4, 4, 4, 4),
    (ROW_THREE_LANES, 100): (3, 3, 4, 4, 4, 4, 4),
}


@pytest.mark.parametrize(("row", "aadt"), FURTH_MIXED)
def test_the_mixed_traffic_table_is_furth_v22_cell_for_cell(row, aadt):
    got = tuple(int(mixed_traffic_level(mph, aadt, row)[0]) for mph in SPEEDS)
    assert got == FURTH_MIXED[(row, aadt)]


def test_no_cell_of_the_mixed_table_is_a_half_step_or_above_4():
    for _, bands in stress.MIXED_TRAFFIC_ROWS.values():
        for band in bands:
            assert set(band) <= {1, 2, 3, 4}


def test_a_busier_or_faster_road_is_never_calmer():
    for row, (_, bands) in stress.MIXED_TRAFFIC_ROWS.items():
        for band in bands:
            assert list(band) == sorted(band), row
        for calmer, busier in itertools.pairwise(bands):
            assert all(a <= b for a, b in zip(calmer, busier, strict=True)), row


class TestWhichRow:
    def test_a_local_street_reads_the_unlaned_row(self):
        for highway in ("residential", "unclassified", "living_street"):
            assert mixed_traffic_row({"highway": highway}, 1, False) == ROW_UNLANED

    def test_a_collector_or_arterial_reads_the_centerline_row(self):
        for highway in ("tertiary", "secondary", "primary", "trunk"):
            assert mixed_traffic_row({"highway": highway}, 1, False) == ROW_SINGLE

    def test_lane_markings_outrank_the_class(self):
        marked = {"highway": "residential", "lane_markings": "yes"}
        bare = {"highway": "tertiary", "lane_markings": "no"}
        assert mixed_traffic_row(marked, 1, False) == ROW_SINGLE
        assert mixed_traffic_row(bare, 1, False) == ROW_UNLANED

    def test_a_one_lane_one_way_reads_furths_wide_one_way_row(self):
        assert mixed_traffic_row({"highway": "residential"}, 1, True) == ROW_SINGLE

    def test_lanes_are_counted_each_way_one_way_or_not(self):
        assert mixed_traffic_row({"highway": "primary"}, 2, False) == ROW_TWO_LANES
        assert mixed_traffic_row({"highway": "residential"}, 2, True) == ROW_TWO_LANES
        assert mixed_traffic_row({"highway": "primary"}, 3, False) == ROW_THREE_LANES

    def test_a_two_lane_one_way_is_not_read_as_a_four_lane_street(self):
        # `lanes` on a one-way is its own lanes, not a two-way total.
        one_way = {"highway": "secondary", "oneway": "yes", "lanes": "2", "maxspeed": "25 mph"}
        two_way = {"highway": "secondary", "lanes": "4", "maxspeed": "25 mph"}
        assert level(one_way, aadt=10_000) == level(two_way, aadt=10_000) == 3

    def test_no_relief_for_a_one_way_at_the_same_lanes_and_count(self):
        one_way = {"highway": "secondary", "oneway": "yes", "lanes": "2", "maxspeed": "30 mph"}
        assert level(one_way, aadt=30_000) == 4


class TestARoadNobodyCounted:
    """An uncounted road reads the usual count of its class, setting and width through the
    same table as a counted one: no separate reading, no floor."""

    def test_the_estimates_rise_with_the_class_and_are_higher_in_town(self):
        order = ("residential", "unclassified", "tertiary", "secondary", "primary", "trunk")
        for setting in (0, 1):
            ones = [CLASS_COUNT[name][setting][0] for name in order]
            assert ones == sorted(ones)
        for name in order:
            (urban_one, urban_wide), (rural_one, rural_wide) = CLASS_COUNT[name]
            assert urban_one > rural_one
            assert urban_wide > urban_one
            assert rural_wide is None or rural_wide > rural_one

    def test_the_figure_is_by_class_setting_and_width(self):
        assert class_count({"highway": "secondary"}, 1, True) == 9_300
        assert class_count({"highway": "secondary"}, 2, True) == 14_000
        assert class_count({"highway": "secondary"}, 1, False) == 3_200
        assert class_count({"highway": "secondary_link"}, 1, False) == 3_200
        assert class_count({"highway": "service"}, 1, True) == 380
        # No measured wide figure: the one-lane figure of the class and setting.
        assert class_count({"highway": "tertiary"}, 2, False) == 1_300
        # A class in no table is read as a secondary.
        assert class_count({"highway": "busway"}, 1, True) == 9_300

    @pytest.mark.parametrize("state", ["DC", "VA", "WV", None])
    def test_a_residential_street_at_25_or_less_is_1(self, state):
        result = classify({"highway": "residential"}, jurisdiction=state)
        assert level({"highway": "residential"}, jurisdiction=state) == 1
        assert CLASS_COUNT_RULE in result.rule
        assert "traffic count" in result.assumed
        assert result.count_source == "class estimate"

    def test_a_residential_street_at_marylands_statutory_30_is_2(self):
        # Maryland's law says 30 on a residential street, and that is what is read.
        assert level({"highway": "residential"}, jurisdiction="MD") == 2
        assert level({"highway": "residential", "maxspeed": "30 mph"}) == 2
        assert level({"highway": "residential", "maxspeed": "25 mph"}, jurisdiction="MD") == 1

    def test_a_collector_at_25_is_3_by_the_centerline_row(self):
        assert level({"highway": "tertiary", "maxspeed": "25 mph"}) == 3

    def test_no_floor_a_count_moves_an_arterial_either_way_from_its_estimate(self):
        slow = {"highway": "secondary", "maxspeed": "20 mph"}
        assert level(slow) == 2 and "floor" not in classify(slow).rule
        assert level(slow, aadt=900) == 1
        assert level(slow, aadt=30_000) == 2

    def test_a_wide_road_with_no_count_reads_its_own_class_not_a_flat_8001(self):
        # Review r1, finding 4: "over 8,000" was measured on arterials and applied to all.
        arterial = {"highway": "primary", "lanes": "4", "maxspeed": "30 mph"}
        assert level(arterial) == 4
        assert level(arterial, aadt=7_000) == 3
        collector = {"highway": "tertiary", "lanes": "4", "maxspeed": "30 mph"}
        local = {"highway": "residential", "lanes": "2", "oneway": "yes", "maxspeed": "30 mph"}
        assert level(collector) == 3
        assert level(local) == 3

    def test_an_estimate_outranks_the_class_and_a_count_outranks_both(self):
        street = {"highway": "tertiary", "maxspeed": "25 mph"}
        assert level(street, estimated_aadt=500) == 1
        assert level(street, estimated_aadt=500, aadt=5_000) == 3
        assert classify(street, estimated_aadt=500).volume_aadt is None

    def test_an_estimate_is_called_an_estimate(self):
        street = {"highway": "secondary", "maxspeed": "20 mph"}
        result = classify(street, estimated_aadt=500)
        assert ESTIMATE_COUNT_RULE in result.rule and CLASS_COUNT_RULE not in result.rule
        assert result.count_source == "supplied estimate"
        assert "a supplied estimate for this road" in result.evidence
        counted = classify(street, estimated_aadt=500, aadt=5_000)
        assert counted.count_source is None and "no count" not in counted.rule

    def test_an_unpaved_rural_road_is_read_as_a_local_one(self):
        gravel = {"highway": "secondary", "surface": "gravel"}
        assert level({"highway": "secondary"}, urban=False) == 4
        assert level(gravel, urban=False) == 2
        assert level(gravel, urban=False, aadt=2_000) == 4
        # In town the class figure stands (review r1, finding 15).
        town = {"highway": "tertiary", "maxspeed": "30 mph"}
        assert level({**town, "surface": "gravel"}) == level(town)


class TestObservedSpeed:
    STREET = {"highway": "secondary", "maxspeed": "25 mph", "lanes": "4"}

    def test_a_measured_travel_speed_is_read_in_place_of_the_limit(self):
        assert level(self.STREET, aadt=30_000) == 3
        assert level(self.STREET, aadt=30_000, observed_speed_mph=36.0) == 4

    def test_the_limit_is_still_what_the_result_reports(self):
        result = classify(self.STREET, aadt=30_000, observed_speed_mph=36.0)
        assert result.speed_mph == 25
        assert result.observed_speed_mph == 36.0

    def test_a_slower_measured_speed_lowers_the_level_too(self):
        fast = {"highway": "tertiary", "maxspeed": "40 mph"}
        assert level(fast, aadt=2_000) == 4
        assert level(fast, aadt=2_000, observed_speed_mph=28.0) == 3


# Furth v2.2, bike lanes not beside parking: (lanes each way, 6 ft or wider) -> levels at
# 25, 30, 35, 40, 45, 50 mph.
LANE_SPEEDS = (25, 30, 35, 40, 45, 50)
FURTH_LANES = {
    (1, True): (1, 1, 2, 3, 3, 3),
    (1, False): (2, 2, 2, 3, 3, 4),
    (2, True): (2, 2, 2, 3, 3, 3),
    (2, False): (2, 2, 2, 3, 4, 4),
    (3, True): (3, 3, 3, 4, 4, 4),
    (3, False): (3, 3, 3, 4, 4, 4),
}
# Beside parking: (lanes, reach of 15 ft or more) -> the same speeds.
FURTH_LANES_PARKING = {
    (1, True): (1, 2, 2, 3, 3, 3),
    (1, False): (2, 2, 3, 3, 3, 3),
    (2, True): (2, 3, 3, 3, 3, 3),
    (2, False): (3, 3, 3, 3, 3, 3),
    (3, True): (3, 3, 3, 3, 3, 3),
}


class TestBikeLanes:
    @pytest.mark.parametrize(("lanes", "wide"), FURTH_LANES)
    def test_the_lane_table_is_furth_v22_cell_for_cell(self, lanes, wide):
        width = 1.9 if wide else 1.5
        got = tuple(int(stress._bike_lane_tier(mph, lanes, width, False)[0]) for mph in LANE_SPEEDS)
        assert got == FURTH_LANES[(lanes, wide)]

    @pytest.mark.parametrize(("lanes", "wide"), FURTH_LANES_PARKING)
    def test_the_beside_parking_table_is_furth_v22_cell_for_cell(self, lanes, wide):
        reach = 4.6 if wide else 4.0
        got = tuple(int(stress._bike_lane_tier(mph, lanes, reach, True)[0]) for mph in LANE_SPEEDS)
        assert got == FURTH_LANES_PARKING[(lanes, wide)]

    def test_six_feet_is_wide_and_under_it_is_not(self):
        assert stress.FURTH_LANE_ALONE_M == pytest.approx(1.8288)
        assert int(stress._bike_lane_tier(25, 1, 1.83, False)[0]) == 1
        # OSM maps a 6 ft lane as 1.8 m (review r1, finding 8).
        assert int(stress._bike_lane_tier(25, 1, 1.8, False)[0]) == 1
        assert int(stress._bike_lane_tier(25, 1, 1.7, False)[0]) == 2

    def test_note_4_a_lane_never_makes_a_street_worse(self):
        street = {"highway": "residential", "maxspeed": "25 mph"}
        laned = {**street, "cycleway:both": "lane"}
        assert level(street, aadt=1_000) == 1
        assert level(laned, aadt=1_000) == 1
        assert NOTE_4_RULE in classify(laned, aadt=1_000).rule

    def test_note_4_over_the_whole_grid(self):
        for highway, mph, lanes, aadt, urban in itertools.product(
            ("residential", "tertiary", "primary"),
            SPEEDS,
            (2, 4, 6),
            (None, 500, 2_000, 9_000, 30_000),
            (True, False),
        ):
            road = {"highway": highway, "maxspeed": f"{mph} mph", "lanes": str(lanes)}
            laned = {**road, "cycleway:both": "lane"}
            assert level(laned, aadt=aadt, urban=urban) <= level(road, aadt=aadt, urban=urban)

    def test_a_lane_at_20_mph_is_2_at_most_whatever_the_street_carries(self):
        street = {"highway": "primary", "maxspeed": "20 mph", "cycleway:both": "lane"}
        assert level(street, aadt=13_000) <= 2
        assert level(street, aadt=40_000) <= 2

    def test_a_lane_at_40_mph_is_3_with_no_special_rule(self):
        road = {"highway": "secondary", "maxspeed": "40 mph", "cycleway:both": "lane"}
        assert level(road, aadt=20_000) == 3

    def test_a_track_on_the_road_is_1_and_carries_the_roads_own_level(self):
        road = {"highway": "primary", "maxspeed": "40 mph", "cycleway:both": "track"}
        result = classify(road, aadt=20_000)
        assert level(road, aadt=20_000) == 1
        assert result.road_level == 4
        assert classify({"highway": "primary"}, aadt=20_000).road_level is None


# Oregon APM chapter 14, Exhibit 14-17: shoulder -> levels under 400, 400-1,500,
# 1,500-7,000, over 7,000 a day.
OREGON = {
    stress.SHOULDER_NONE: (2, 3, 4, 4),
    stress.SHOULDER_NARROW: (2, 3, 4, 4),
    stress.SHOULDER_UNKNOWN: (2, 3, 4, 4),
    stress.SHOULDER_RIDEABLE: (2, 2, 3, 4),
    stress.SHOULDER_WIDE: (2, 2, 2, 3),
}


class TestRuralRoads:
    ROAD = {"highway": "tertiary"}

    @pytest.mark.parametrize("shoulder", OREGON)
    def test_the_rural_table_is_oregons_cell_for_cell(self, shoulder):
        got = tuple(int(rural_road_level(n, shoulder)[0]) for n in (399, 1_500, 7_000, 7_001))
        assert got == OREGON[shoulder]

    def test_the_band_edges(self):
        assert rural_road_level(400, stress.SHOULDER_NONE)[0] == 3
        assert rural_road_level(1_501, stress.SHOULDER_NONE)[0] == 4

    def test_an_unposted_rural_road_is_rated_by_its_count(self):
        counts = (300, 1_000, 2_000, 4_741, 10_000)
        assert [level(self.ROAD, urban=False, aadt=n) for n in counts] == [2, 3, 4, 4, 4]

    def test_a_road_with_no_shoulder_tag_says_unknown_never_none(self):
        result = classify(self.ROAD, urban=False, aadt=1_000)
        assert "shoulder unknown" in result.rule
        assert "no shoulder" not in result.rule
        assert "shoulder" in result.assumed

    def test_shoulder_facts_come_from_osm(self):
        assert rural_shoulder({"highway": "tertiary"}) == stress.SHOULDER_UNKNOWN
        assert rural_shoulder({"highway": "tertiary", "shoulder": "no"}) == stress.SHOULDER_NONE
        assert rural_shoulder({"highway": "tertiary", "shoulder": "both"}) == (
            stress.SHOULDER_UNKNOWN
        )
        four = {"highway": "tertiary", "shoulder": "both", "shoulder:width": "1.3"}
        six = {"highway": "tertiary", "shoulder": "both", "shoulder:width": "1.9"}
        thin = {"highway": "tertiary", "shoulder": "both", "shoulder:width": "0.6"}
        assert rural_shoulder(four) == stress.SHOULDER_RIDEABLE
        assert rural_shoulder(six) == stress.SHOULDER_WIDE
        assert rural_shoulder(thin) == stress.SHOULDER_NARROW
        marked = {"highway": "tertiary", "cycleway:both": "shoulder"}
        assert rural_shoulder(marked) == stress.SHOULDER_RIDEABLE

    def test_cycleway_shoulder_needs_both_sides_of_a_two_way_road(self):
        assert cycleway_shoulder({"highway": "tertiary", "cycleway:both": "shoulder"})
        assert not cycleway_shoulder({"highway": "tertiary", "cycleway:right": "shoulder"})
        one_way = {"highway": "tertiary", "oneway": "yes", "cycleway:right": "shoulder"}
        assert cycleway_shoulder(one_way)

    def test_a_wide_shoulder_lowers_a_busy_road(self):
        wide = {**self.ROAD, "shoulder": "both", "shoulder:width": "2"}
        assert level(self.ROAD, urban=False, aadt=4_741) == 4
        assert level(wide, urban=False, aadt=4_741) == 2

    def test_an_uncounted_rural_road_gets_its_classs_band_not_a_flat_level(self):
        got = {
            highway: level({"highway": highway}, urban=False, jurisdiction="MD")
            for highway in ("unclassified", "tertiary", "secondary")
        }
        assert got == {"unclassified": 2, "tertiary": 3, "secondary": 4}

    def test_nothing_open_to_cars_at_the_statutory_rural_speed_rates_1(self):
        for highway, aadt in itertools.product(
            ("unclassified", "tertiary", "secondary", "primary", "trunk"),
            (None, 50, 300, 2_000),
        ):
            assert level({"highway": highway}, urban=False, aadt=aadt) >= 2

    def test_the_rural_minimum_says_so(self):
        lane = {"highway": "unclassified", "maxspeed": "25 mph"}
        result = classify(lane, urban=False, aadt=200)
        assert level(lane, urban=False, aadt=200) == 2
        assert RURAL_MIN_RULE in result.rule

    def test_a_town_street_posted_25_outside_the_urban_areas_may_be_1(self):
        street = {"highway": "residential", "maxspeed": "25 mph"}
        walked = {"highway": "tertiary", "maxspeed": "25 mph", "sidewalk": "both"}
        bare = {"highway": "tertiary", "maxspeed": "25 mph"}
        assert level(street, urban=False) == 1
        assert level(walked, urban=False, aadt=800) == 1
        assert level(bare, urban=False, aadt=800) == 2

    def test_a_lower_posted_limit_never_makes_the_same_rural_road_worse(self):
        for highway, aadt in itertools.product(
            ("unclassified", "tertiary", "secondary"), (None, 300, 1_000, 2_000, 5_000, 9_000)
        ):
            levels = [
                level({"highway": highway, "maxspeed": f"{mph} mph"}, urban=False, aadt=aadt)
                for mph in (30, 35, 40, 45, 50, 55)
            ]
            unposted = level({"highway": highway}, urban=False, aadt=aadt)
            assert levels == sorted(levels), (highway, aadt, levels)
            assert max(levels) <= unposted or levels[-1] == unposted

    def test_the_urban_line_moves_a_posted_counted_road_one_level_at_most(self):
        for highway, mph, aadt in itertools.product(
            ("unclassified", "tertiary", "secondary", "primary"),
            SPEEDS,
            (100, 300, 500, 1_000, 2_000, 5_000, 9_000, 30_000),
        ):
            road = {"highway": highway, "maxspeed": f"{mph} mph"}
            inside = level(road, urban=True, aadt=aadt)
            outside = level(road, urban=False, aadt=aadt)
            assert abs(inside - outside) <= 1, (road, aadt, inside, outside)


def test_every_count_break_is_a_volume_gate():
    assert set(VOLUME_GATES) == {400, 751, 1_001, 1_501, 3_001, 7_001, 8_001, 18_000}


US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
    "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
PLACE_WORDS = (
    "DDOT", "MDOT", "VDOT", "Montgomery", "Aspen", "Connecticut", "Arlington", "Fairfax",
    "Loudoun", "Maryland", "Virginia", "District of Columbia", "Washington", "Baltimore",
    "Pennsylvania", "moco", "ddot", "mdot",
)  # fmt: skip


def _strings_in_function_bodies(module) -> list[tuple[str, str]]:
    """(function, string) for every string constant inside a function of `module`, its
    docstrings left out: the module's logic, as against its data tables and comments."""
    import ast
    import inspect

    found = []
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        docstring = ast.get_docstring(node, clean=False)
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if child.value != docstring:
                    found.append((node.name, child.value))
    return found


def test_no_logic_names_a_place():
    # The portability test: no function in the classifier holds a state code or the name
    # of a jurisdiction, agency or road. Local things are data (`SPEED_LAW`, `CLASS_COUNT`)
    # the functions read by key.
    strings = _strings_in_function_bodies(stress)
    assert len(strings) > 100, "the walk found the module's strings"
    for function, text in strings:
        assert text not in US_STATE_CODES, (function, text)
        for word in PLACE_WORDS:
            assert word not in text, (function, text)


def test_the_place_test_would_see_a_state_code(monkeypatch):
    import types

    planted = types.ModuleType("planted")
    source = 'def f(zone):\n    "Doc naming MD is fine."\n    return zone == "MD"\n'
    monkeypatch.setattr("inspect.getsource", lambda module: source)
    assert _strings_in_function_bodies(planted) == [("f", "MD")]


def test_a_new_state_is_a_data_entry_only(monkeypatch):
    # Pennsylvania, with made-up figures: one entry, no code.
    law = stress.SpeedLaw("a made-up statute", district=(22.0, 22.0), elsewhere=(47.0, 47.0))
    monkeypatch.setitem(stress.SPEED_LAW, "PA", law)
    street = classify({"highway": "residential"}, jurisdiction="PA")
    assert street.default_speed_mph == 22.0 and street.speed_source == "statute"
    assert street.rule.startswith("mixed traffic, 20 mph or below")
    road = classify({"highway": "tertiary"}, jurisdiction="PA", urban=False)
    assert road.default_speed_mph == 47.0 and road.speed_source == "statute"
    assert stress.statutory_default_mph({}, "PA", urban=True, divided=False) == 22.0


def test_a_state_with_no_entry_reads_class_defaults_and_says_so():
    result = classify({"highway": "residential"}, jurisdiction="PA")
    assert result.speed_source == "class default"
    assert "class default, our default" in result.evidence
    assert "statute" not in result.evidence


def test_every_speed_law_entry_cites_its_statute():
    for code, law in stress.SPEED_LAW.items():
        assert code in US_STATE_CODES
        assert law.citation.strip()


class TestSparseAndRichData:
    """One formula: it answers from the minimum, and evidence only refines the same inputs."""

    @pytest.mark.parametrize(
        "highway", ["residential", "unclassified", "tertiary", "secondary", "primary", "trunk"]
    )
    @pytest.mark.parametrize("urban", [True, False])
    def test_the_minimum_gives_a_level_and_a_reason(self, highway, urban):
        result = classify({"highway": highway}, urban=urban)
        assert 1 <= level({"highway": highway}, urban=urban) <= 4.5
        assert result.rule
        assert result.evidence.startswith("estimated: ")
        assert "traffic" in result.evidence and "travel speed" in result.evidence

    def test_no_jurisdiction_is_needed(self):
        assert classify({"highway": "tertiary"}, jurisdiction=None).rule

    def test_richer_evidence_shortens_the_estimated_list(self):
        sparse = classify({"highway": "tertiary"}, urban=False)
        rich = classify(
            {"highway": "tertiary", "maxspeed": "45 mph", "lanes": "2", "shoulder": "no"},
            urban=False,
            aadt=900,
            observed_speed_mph=47.0,
        )
        assert rich.evidence == "every input measured or mapped"
        assert len(sparse.evidence) > len(rich.evidence)

    def test_a_posted_limit_alone_is_still_called_an_estimate_of_travel_speed(self):
        result = classify({"highway": "tertiary", "maxspeed": "30 mph", "lanes": "2"}, aadt=900)
        assert result.evidence == "estimated: travel speed (the posted limit, not measured)"

    def test_evidence_arrives_as_arguments_never_as_a_place(self):
        import inspect

        parameters = set(inspect.signature(classify).parameters)
        assert {
            "aadt",
            "estimated_aadt",
            "observed_speed_mph",
            "urban",
            "jurisdiction",
        } <= parameters
        # The only use of the jurisdiction is choosing the law's default speed table.
        source = inspect.getsource(stress._classify)
        assert source.count("jurisdiction") == source.count("speed_zone(tags, jurisdiction)") + 1


def test_the_smoothing_sees_every_published_break_and_nothing_else():
    from pipeline.aadt_smoothing import crosses_volume_gate

    for gate in VOLUME_GATES:
        assert crosses_volume_gate(gate, gate - 1), gate
        assert not crosses_volume_gate(gate - 1, gate - 2), gate
    # The local steps the classifier had until 2026-11-13 move nothing now.
    for retired in (5_000, 9_000, 12_000, 20_000):
        assert not crosses_volume_gate(retired, retired - 1)
    assert crosses_volume_gate(1_001, 1_000) and crosses_volume_gate(8_001, 8_000)
    assert crosses_volume_gate(400, 399) and crosses_volume_gate(7_001, 7_000)


class TestCapsStillHold:
    ROAD = {"highway": "secondary"}  # rural, unposted, uncounted: 4 by the rural table

    def test_a_road_closed_to_cars_is_1_at_most(self):
        closed = {**self.ROAD, "motor_vehicle": "no", "bicycle": "yes"}
        assert level(self.ROAD, urban=False) == 4
        assert level(closed, urban=False) == 1
        assert stress.MOTOR_RESTRICTED_RULE in classify(closed, urban=False).rule

    def test_a_road_for_residents_only_is_2_at_most(self):
        private = {**self.ROAD, "motor_vehicle": "private"}
        assert level(private, urban=False) == 2
        assert "motor_vehicle=private" in classify(private, urban=False).rule

    def test_a_posted_limit_over_30_raises_the_cap_one_level(self):
        fast = {**self.ROAD, "motor_vehicle": "private", "maxspeed": "50 mph"}
        assert level(fast, urban=False) == 3
        assert "posted 50 mph" in classify(fast, urban=False).rule

    def test_a_count_switches_the_cap_off(self):
        private = {**self.ROAD, "motor_vehicle": "private"}
        assert level(private, urban=False, aadt=2_000) == 4

    def test_a_rough_surface_is_never_1(self):
        street = {"highway": "residential", "surface": "dirt"}
        assert level(street) == 2
        assert "rough surface" in classify(street).rule
