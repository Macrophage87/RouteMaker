"""Agency street layers: parsing, aggregating and overlaying (routemaker.agency_roads).

Every fixture is a record shaped like the layer's real ones (fields and values
read off the data retrieved 2026-10-01), because the parsers are about the
layers' quirks: DC's empty inbound speed, totals-not-per-lane widths, and
Baltimore's `speed` field standing in for a limit.
"""

from __future__ import annotations

import json

import pytest

from routemaker import agency_roads as A
from routemaker.stress import Stress, classify


def dc(**overrides) -> dict:
    """A DC Roadway Block record: K St NW, 5 lanes, 20 mph, no bike lane."""
    record = {
        "ROUTENAME": "K ST NW",
        "TOTALTRAVELLANES": 5,
        "TOTALPARKINGLANES": 0,
        "TOTALTRAVELLANEWIDTH": 65,
        "TOTALPARKINGLANEWIDTH": 0,
        "TOTALTRAVELLANESINBOUND": 2,
        "TOTALTRAVELLANESOUTBOUND": 3,
        "TOTALTRAVELLANESBIDIRECTIONAL": 0,
        "SUMMARYDIRECTION": "BD",
        "BIKELANE_CONVENTIONAL": None,
        "BIKELANE_PROTECTED": None,
        "BIKELANE_BUFFERED": None,
        "BIKELANE_DUAL_PROTECTED": None,
        "BIKELANE_DUAL_BUFFERED": None,
        "BIKELANE_CONTRAFLOW": None,
        "TOTALBIKELANES": 0,
        "TOTALBIKELANEWIDTH": 0,
        "SPEEDLIMITS_IB": None,
        "SPEEDLIMITS_OB": 20,
        "AADT": None,
        "AADT_YEAR": None,
        "PCI_SCORE": 100,
        "FHWAFUNCTIONALCLASS": 3,
    }
    record.update(overrides)
    return record


def baltimore(**overrides) -> dict:
    record = {
        "feanme": "CHARLES",
        "featype": "ST",
        "dirpre": None,
        "dirsuf": None,
        "subtype": "STRPRD",
        "feat_status": "A",
        "drivable": "Y",
        "speed": 25,
        "fr_speed_limit": None,
        "to_speed_limit": None,
        "oneway": None,
        "lane_count": None,
        "sha_class": "MART",
    }
    record.update(overrides)
    return record


# -- DC parsing ---------------------------------------------------------------------


def test_the_posted_speed_is_read_from_whichever_direction_has_one() -> None:
    """`SPEEDLIMITS_IB` is empty on every block of the layer and the outbound
    field carries the limit, so reading only the inbound one would find no speed
    anywhere."""
    assert A.parse_dc_roadway_block(dc()).speed_mph == {"ob": 20}
    both = A.parse_dc_roadway_block(dc(SPEEDLIMITS_IB=25))
    assert both.speed_mph == {"ib": 25, "ob": 20}


@pytest.mark.parametrize("value", [0, 5, 9, 81, None, "", True])
def test_a_value_that_is_not_a_speed_limit_is_no_speed(value) -> None:
    """DC has blocks posted 0 and 5 mph; neither is a limit anyone signed."""
    assert A.parse_dc_roadway_block(dc(SPEEDLIMITS_OB=value)).speed_mph == {}


def test_a_posted_speed_at_the_bounds_is_kept() -> None:
    assert A.parse_dc_roadway_block(dc(SPEEDLIMITS_OB=10)).speed_mph == {"ob": 10}
    assert A.parse_dc_roadway_block(dc(SPEEDLIMITS_OB=80)).speed_mph == {"ob": 80}


def test_lanes_are_kept_by_direction() -> None:
    facts = A.parse_dc_roadway_block(dc())
    assert facts.lanes == {"ib": 2, "ob": 3}
    assert A.lanes_per_direction(facts) == 3


def test_reversible_lanes_are_lanes_in_the_peak_direction() -> None:
    """Connecticut Avenue NW at Cleveland Park: one lane each way and two that
    reverse, `TOTALTRAVELLANES` of 4. A rider meets three in the peak direction;
    reading only the directional counts called it a two-lane street."""
    facts = A.parse_dc_roadway_block(
        dc(
            TOTALTRAVELLANES=4,
            TOTALTRAVELLANESINBOUND=1,
            TOTALTRAVELLANESOUTBOUND=1,
            TOTALTRAVELLANESREVERSIBLE=2,
        )
    )
    assert facts.lanes == {"ib": 1, "ob": 1, "reversible": 2}
    assert A.lanes_per_direction(facts) == 3


def test_a_block_whose_directions_are_all_zero_has_only_its_total() -> None:
    """599 two-way blocks read 0 and 0 in every direction, and carry a total that
    does not say how it divides; nine read a total of 1."""
    unknown = dc(
        TOTALTRAVELLANESINBOUND=0, TOTALTRAVELLANESOUTBOUND=0, TOTALTRAVELLANESBIDIRECTIONAL=0
    )
    facts = A.parse_dc_roadway_block(unknown)
    assert facts.lanes == {"total": 5}
    assert A.lanes_per_direction(facts) == 2  # half of five, on a two-way street
    one_way = A.parse_dc_roadway_block(
        dc(
            TOTALTRAVELLANES=2,
            TOTALTRAVELLANESINBOUND=0,
            TOTALTRAVELLANESOUTBOUND=0,
            TOTALTRAVELLANESBIDIRECTIONAL=0,
            SUMMARYDIRECTION="IB",
        )
    )
    assert A.lanes_per_direction(one_way) == 2


def test_a_block_with_no_lanes_at_all_has_none() -> None:
    none = dc(
        TOTALTRAVELLANES=0,
        TOTALTRAVELLANESINBOUND=0,
        TOTALTRAVELLANESOUTBOUND=0,
        TOTALTRAVELLANESBIDIRECTIONAL=0,
    )
    facts = A.parse_dc_roadway_block(none)
    assert facts.lanes == {}
    assert A.lanes_per_direction(facts) is None


def test_the_shared_turn_lane_is_not_a_through_lane() -> None:
    facts = A.parse_dc_roadway_block(
        dc(TOTALTRAVELLANESINBOUND=1, TOTALTRAVELLANESOUTBOUND=1, TOTALTRAVELLANESBIDIRECTIONAL=1)
    )
    assert A.lanes_per_direction(facts) == 1


def test_a_baltimore_lane_count_is_the_whole_street() -> None:
    facts = A.parse_baltimore_centerline(baltimore(lane_count=4))
    assert A.lanes_per_direction(facts) == 2
    one_way = A.parse_baltimore_centerline(baltimore(lane_count=2, oneway="FT"))
    assert A.lanes_per_direction(one_way) == 2


def test_a_summary_direction_says_whether_the_street_is_one_way() -> None:
    assert A.parse_dc_roadway_block(dc(SUMMARYDIRECTION="BD")).way == "both"
    assert A.parse_dc_roadway_block(dc(SUMMARYDIRECTION="IB")).way == "one"
    assert A.parse_dc_roadway_block(dc(SUMMARYDIRECTION="OB")).way == "one"
    # '??' is on 232 blocks and means nobody knows.
    assert A.parse_dc_roadway_block(dc(SUMMARYDIRECTION="??")).way is None


def test_bike_lane_widths_are_totals_and_become_per_lane() -> None:
    """Two five-foot lanes are recorded as ten feet."""
    facts = A.parse_dc_roadway_block(
        dc(BIKELANE_CONVENTIONAL="BD", TOTALBIKELANES=2, TOTALBIKELANEWIDTH=10)
    )
    assert facts.bike_width_ft == 5.0
    one = A.parse_dc_roadway_block(
        dc(BIKELANE_CONVENTIONAL="IB", TOTALBIKELANES=1, TOTALBIKELANEWIDTH=6)
    )
    assert one.bike_width_ft == 6.0


def test_a_bike_width_without_a_facility_is_not_kept() -> None:
    assert (
        A.parse_dc_roadway_block(dc(TOTALBIKELANES=1, TOTALBIKELANEWIDTH=5)).bike_width_ft is None
    )


def test_parking_and_lane_widths_are_per_lane() -> None:
    facts = A.parse_dc_roadway_block(
        dc(
            TOTALPARKINGLANES=2,
            TOTALPARKINGLANEWIDTH=16,
            TOTALTRAVELLANES=2,
            TOTALTRAVELLANEWIDTH=22,
        )
    )
    assert facts.parking_lanes == 2
    assert facts.parking_width_ft == 8.0
    assert facts.lane_width_ft == 11.0


def test_no_parking_is_zero_lanes_not_unknown() -> None:
    assert A.parse_dc_roadway_block(dc(TOTALPARKINGLANES=0)).parking_lanes == 0
    assert A.parse_dc_roadway_block(dc(TOTALPARKINGLANES=None)).parking_lanes is None


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"BIKELANE_CONVENTIONAL": "BD"}, {"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}),
        ({"BIKELANE_CONVENTIONAL": "IB"}, {"ib": A.BIKE_LANE}),
        ({"BIKELANE_BUFFERED": "OB"}, {"ob": A.BIKE_BUFFERED}),
        ({"BIKELANE_PROTECTED": "BD"}, {"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED}),
        # A dual (two-way) facility serves both directions whichever side names it.
        ({"BIKELANE_DUAL_PROTECTED": "IB"}, {"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED}),
        ({"BIKELANE_DUAL_BUFFERED": "OB"}, {"ib": A.BIKE_BUFFERED, "ob": A.BIKE_BUFFERED}),
        # The best facility in each direction wins.
        (
            {"BIKELANE_CONVENTIONAL": "BD", "BIKELANE_PROTECTED": "IB"},
            {"ib": A.BIKE_PROTECTED, "ob": A.BIKE_LANE},
        ),
        ({"BIKELANE_CONVENTIONAL": "XX"}, {}),
        ({}, {}),
    ],
)
def test_bike_flags_become_a_rank_in_each_direction(flags, expected) -> None:
    assert A.parse_dc_roadway_block(dc(**flags)).bike == expected


def test_a_contraflow_lane_is_flagged_and_is_not_a_lane_in_both_directions() -> None:
    facts = A.parse_dc_roadway_block(dc(BIKELANE_CONTRAFLOW="IB"))
    assert facts.contraflow is True
    assert facts.bike == {}


def test_the_count_and_its_year_are_kept() -> None:
    facts = A.parse_dc_roadway_block(dc(AADT=11011, AADT_YEAR=2020))
    assert (facts.aadt, facts.aadt_year) == (11011, 2020)
    assert A.parse_dc_roadway_block(dc(AADT=0)).aadt is None


# -- Baltimore parsing --------------------------------------------------------------


def test_the_centerline_speed_field_is_the_limit_and_says_where_it_came_from() -> None:
    facts = A.parse_baltimore_centerline(baltimore())
    assert facts.speed_mph == {"centerline": 25}
    assert facts.agency == A.BALTIMORE_AGENCY


def test_posted_from_and_to_limits_outrank_the_speed_field() -> None:
    facts = A.parse_baltimore_centerline(baltimore(fr_speed_limit=30, to_speed_limit=30))
    assert facts.speed_mph == {"from": 30, "to": 30}


def test_a_zero_posted_limit_is_not_a_limit() -> None:
    """The 19 populated `fr_speed_limit` values are all 0."""
    facts = A.parse_baltimore_centerline(baltimore(fr_speed_limit=0, to_speed_limit=0))
    assert facts.speed_mph == {"centerline": 25}


def test_an_alley_is_given_no_speed() -> None:
    """The layer's `speed` is 1 on 11,892 alleys and 15 on 289 more; an alley is
    not a street whose speed describes riding on it."""
    alley = A.parse_baltimore_centerline(baltimore(subtype="STRALY", speed=15))
    assert alley.alley is True
    assert alley.speed_mph == {}


def test_a_speed_of_one_is_not_a_speed() -> None:
    assert A.parse_baltimore_centerline(baltimore(speed=1)).speed_mph == {}


def test_a_centerline_that_is_not_active_or_not_drivable_is_dropped() -> None:
    assert A.parse_baltimore_centerline(baltimore(feat_status="P")) is None
    assert A.parse_baltimore_centerline(baltimore(drivable="N")) is None


@pytest.mark.parametrize(("value", "expected"), [("FT", "one"), ("TF", "one"), (None, None)])
def test_the_centerline_one_way_flag(value, expected) -> None:
    assert A.parse_baltimore_centerline(baltimore(oneway=value)).way == expected


def test_the_street_name_is_assembled_from_its_parts() -> None:
    facts = A.parse_baltimore_centerline(
        baltimore(dirpre="N", feanme="CHARLES", featype="ST", dirsuf=None)
    )
    assert facts.name == "N CHARLES ST"


# -- the json round trip ------------------------------------------------------------


def test_facts_round_trip_through_json_and_leave_out_what_is_absent() -> None:
    facts = A.parse_dc_roadway_block(
        dc(
            BIKELANE_PROTECTED="BD",
            TOTALBIKELANES=2,
            TOTALBIKELANEWIDTH=12,
            AADT=500,
            AADT_YEAR=2020,
        )
    )
    row = facts.to_json()
    assert "alley" not in row and "contraflow" not in row and "pci_score" in row
    assert A.RoadFacts.from_json(json.loads(json.dumps(row))) == facts


def test_unknown_keys_in_a_stored_row_are_ignored() -> None:
    row = A.parse_dc_roadway_block(dc()).to_json() | {"a_field_added_later": 1}
    assert A.RoadFacts.from_json(row).agency == A.DC_AGENCY


# -- streaming ----------------------------------------------------------------------


def test_features_are_read_one_at_a_time_across_chunk_boundaries(tmp_path) -> None:
    features = [
        {"type": "Feature", "properties": {"n": n, "text": "x" * (n * 7)}, "geometry": None}
        for n in range(40)
    ]
    path = tmp_path / "layer.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    # A chunk smaller than a feature makes every feature span a boundary.
    got = list(A.iter_features(path, chunk_bytes=64))
    assert [f["properties"]["n"] for f in got] == list(range(40))


def test_an_empty_collection_has_no_features(tmp_path) -> None:
    path = tmp_path / "empty.geojson"
    path.write_text('{"type":"FeatureCollection","features":[]}')
    assert list(A.iter_features(path)) == []


def test_a_file_with_no_features_key_yields_nothing(tmp_path) -> None:
    path = tmp_path / "other.json"
    path.write_text('{"type":"Feature"}')
    assert list(A.iter_features(path)) == []


# -- names --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("4th Street Northeast", "4TH ST NE", True),
        ("Connecticut Avenue Northwest", "CONNECTICUT AVE NW", True),
        ("Connecticut Avenue", "CONNECTICUT AVE NW", True),
        ("K Street Northwest", "L ST NW", False),
        ("Martin Luther King Jr Avenue Southeast", "MARTIN LUTHER KING JR AVE SE", True),
        # OSM spells the suffix out.
        ("Martin Luther King Junior Avenue Southeast", "MARTIN LUTHER KING JR AVE SE", True),
        ("Rock Creek Parkway", "ROCK CREEK AND POTOMAC PKWY NW", True),
        ("4th Street Northeast", "6TH ST NE", False),
        # Street types that are not abbreviations are type words all the same.
        ("Hunters Way", "HUNTERS BEND", True),
        ("Fox Pike", "FOX TURNPIKE", True),
        (None, "K ST NW", None),
        ("K Street", None, None),
        ("", "K ST NW", None),
        # Only a street type and a quadrant: nothing identifies it.
        ("Street Northwest", "K ST NW", None),
        # Review r1: a single-letter street is named by its letter, and a
        # compass word before the street type is the street's name.
        ("E Street Northwest", "E ST NW", True),
        ("E Street", "N ST NW", False),
        ("W Place Northwest", "W PL NW", True),
        ("North Avenue", "NORTH AVE", True),
        ("North Charles Street", "CHARLES ST", True),
        ("East Capitol Street", "E ST NE", False),
        # Plurals are the same street.
        ("East Meadow Court", "EAST MEADOWS CT", True),
    ],
)
def test_two_street_names_agree_when_their_identifying_words_do(a, b, expected) -> None:
    assert A.names_agree(a, b) is expected


# -- aggregating --------------------------------------------------------------------


def facts(**kwargs) -> A.RoadFacts:
    return A.RoadFacts(agency=A.DC_AGENCY, **kwargs)


def test_a_way_along_several_blocks_takes_the_most_stressful_speed_and_lanes() -> None:
    way = A.aggregate(
        [
            ("a", facts(speed_mph={"ob": 20}, lanes={"ib": 1, "ob": 1})),
            ("b", facts(speed_mph={"ob": 30}, lanes={"ib": 2, "ob": 3})),
        ]
    )
    assert way.speed_mph == 30
    assert way.lanes_per_direction == 3
    assert way.speed_by_direction == {"ob": 30}
    assert way.blocks == ("a", "b")


def test_the_shared_centre_lane_is_not_a_through_lane() -> None:
    way = A.aggregate([("a", facts(lanes={"ib": 1, "ob": 1, "bidirectional": 1}))])
    assert way.lanes_per_direction == 1


def test_a_way_with_no_speed_in_any_block_has_none() -> None:
    assert A.aggregate([("a", facts())]).speed_mph is None
    assert A.aggregate([("a", facts())]).lanes_per_direction is None


def test_a_way_is_one_way_only_if_every_block_that_says_so_is() -> None:
    assert A.aggregate([("a", facts(way="one")), ("b", facts(way="one"))]).one_way is True
    assert A.aggregate([("a", facts(way="one")), ("b", facts(way="both"))]).one_way is False
    # A block that does not say does not vote.
    assert A.aggregate([("a", facts(way="one")), ("b", facts())]).one_way is True
    assert A.aggregate([("a", facts())]).one_way is None


def test_the_facility_is_the_weakest_across_the_blocks() -> None:
    """One tier is stored per way, so a lane that stops mid-way is not a lane."""
    both = {"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED}
    lane = {"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}
    assert A.aggregate([("a", facts(bike=both)), ("b", facts(bike=lane))]).bike == lane
    assert A.aggregate([("a", facts(bike=both)), ("b", facts())]).bike == {}
    one_side = {"ib": A.BIKE_LANE}
    assert A.aggregate([("a", facts(bike=both)), ("b", facts(bike=one_side))]).bike == one_side


def test_the_narrowest_lane_and_the_busiest_count_describe_the_way() -> None:
    way = A.aggregate(
        [
            ("a", facts(bike_width_ft=5.0, aadt=900, aadt_year=2020, parking_lanes=0)),
            ("b", facts(bike_width_ft=4.0, aadt=4000, aadt_year=2019, parking_lanes=2)),
        ]
    )
    assert way.bike_width_ft == 4.0
    assert (way.aadt, way.aadt_year) == (4000, 2019)
    assert way.parking_lanes == 2


def test_a_way_with_no_blocks_is_refused() -> None:
    with pytest.raises(ValueError):
        A.aggregate([])


def test_a_contraflow_lane_counts_only_if_every_block_has_it() -> None:
    assert A.aggregate([("a", facts(contraflow=True)), ("b", facts())]).contraflow is False
    assert A.aggregate([("a", facts(contraflow=True))]).contraflow is True


# -- the overlay --------------------------------------------------------------------


def way_facts(**kwargs) -> A.WayFacts:
    return A.WayFacts(agency=A.DC_AGENCY, blocks=("b1",), **kwargs)


def test_a_posted_speed_takes_precedence_over_the_way_s_own_tag() -> None:
    result = A.overlay({"highway": "residential", "maxspeed": "35 mph"}, way_facts(speed_mph=25))
    assert result.tags["maxspeed"] == "25 mph"
    assert result.sources["maxspeed"] == A.DC_AGENCY


def test_with_no_agency_speed_the_way_s_own_stands_and_the_source_says_so() -> None:
    kept = A.overlay({"highway": "residential", "maxspeed": "35 mph"}, way_facts())
    assert kept.tags["maxspeed"] == "35 mph"
    assert kept.sources["maxspeed"] == A.SOURCE_OSM
    assumed = A.overlay({"highway": "residential"}, way_facts())
    assert "maxspeed" not in assumed.tags
    assert assumed.sources["maxspeed"] == A.SOURCE_DEFAULT


def test_the_overlay_does_not_change_the_tags_it_was_given() -> None:
    original = {"highway": "residential", "maxspeed": "35 mph"}
    A.overlay(original, way_facts(speed_mph=25, lanes_per_direction=2, parking_lanes=2))
    assert original == {"highway": "residential", "maxspeed": "35 mph"}


def test_lanes_on_a_two_way_road_are_written_per_direction() -> None:
    """The classifier reads the larger of `lanes:forward` and `lanes:backward`;
    writing `lanes` would be halved for a two-way road."""
    result = A.overlay(
        {"highway": "primary", "lanes": "2", "lanes:forward": "1"},
        way_facts(lanes_per_direction=3),
    )
    assert result.tags["lanes:forward"] == result.tags["lanes:backward"] == "3"
    assert "lanes" not in result.tags
    assert result.sources["lanes"] == A.DC_AGENCY


def test_lanes_on_a_one_way_road_are_the_whole_count() -> None:
    result = A.overlay({"highway": "primary", "oneway": "yes"}, way_facts(lanes_per_direction=2))
    assert result.tags["lanes"] == "2"
    assert "lanes:forward" not in result.tags


def test_the_agency_s_lanes_reach_the_classifier_as_lanes_per_direction() -> None:
    from routemaker.tags import lanes_per_direction

    two_way = A.overlay({"highway": "primary"}, way_facts(lanes_per_direction=3)).tags
    one_way = A.overlay({"highway": "primary", "oneway": "yes"}, way_facts(lanes_per_direction=3))
    assert lanes_per_direction(two_way) == 3
    assert lanes_per_direction(one_way.tags) == 3


def test_an_agency_one_way_is_believed_where_osm_says_nothing() -> None:
    result = A.overlay({"highway": "residential"}, way_facts(one_way=True))
    assert result.tags["oneway"] == "yes"
    assert result.sources["oneway"] == A.DC_AGENCY


def test_an_agency_two_way_does_not_undo_an_osm_one_way() -> None:
    """A divided road's carriageways are one-way ways on a two-way block."""
    result = A.overlay({"highway": "primary", "oneway": "yes"}, way_facts(one_way=False))
    assert result.tags["oneway"] == "yes"
    assert result.sources["oneway"] == A.SOURCE_OSM
    assert result.disagreements == ("oneway: agency two-way, OSM one-way",)


def test_a_reversed_osm_one_way_is_still_one_way() -> None:
    result = A.overlay({"highway": "residential", "oneway": "-1"}, way_facts(one_way=True))
    assert result.tags["oneway"] == "-1"
    assert result.sources["oneway"] == A.SOURCE_OSM


def test_a_protected_lane_replaces_the_way_s_cycleway_tags() -> None:
    result = A.overlay(
        {"highway": "primary", "cycleway:right": "lane", "cycleway:right:width": "1.0"},
        way_facts(bike={"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED}, bike_width_ft=8.0),
    )
    assert result.tags["cycleway:both"] == "track"
    assert not any(key.startswith("cycleway:right") for key in result.tags)
    assert result.sources["bike"] == A.DC_AGENCY


def test_a_buffered_lane_is_a_lane_with_a_buffer_and_the_agency_s_width() -> None:
    result = A.overlay(
        {"highway": "primary"},
        way_facts(bike={"ib": A.BIKE_BUFFERED, "ob": A.BIKE_BUFFERED}, bike_width_ft=5.0),
    )
    assert result.tags["cycleway:both"] == "lane"
    assert result.tags["cycleway:both:buffer"] == "yes"
    assert result.tags["cycleway:both:width"] == "1.52"


def test_a_conventional_lane_in_one_direction_is_a_lane_on_one_side() -> None:
    result = A.overlay({"highway": "primary"}, way_facts(bike={"ib": A.BIKE_LANE}))
    assert result.tags["cycleway:right"] == "lane"
    assert "cycleway:both" not in result.tags


def test_the_weaker_direction_sets_a_both_sides_facility() -> None:
    result = A.overlay(
        {"highway": "primary"},
        way_facts(bike={"ib": A.BIKE_PROTECTED, "ob": A.BIKE_LANE}),
    )
    assert result.tags["cycleway:both"] == "lane"


def test_a_contraflow_lane_is_an_opposite_lane_on_the_other_side() -> None:
    result = A.overlay(
        {"highway": "residential", "oneway": "yes"},
        way_facts(bike={"ib": A.BIKE_LANE}, contraflow=True),
    )
    assert result.tags["cycleway:left"] == "opposite_lane"


def test_an_agency_with_no_facility_leaves_osm_s_lane_and_reports_the_disagreement() -> None:
    """Its absence is not evidence a lane painted since the layer was cut is gone."""
    result = A.overlay({"highway": "primary", "cycleway:right": "lane"}, way_facts())
    assert result.tags["cycleway:right"] == "lane"
    assert result.sources["bike"] == A.SOURCE_OSM
    assert result.disagreements == ("bike facility: OSM has one, the agency records none",)


def test_a_cycleway_that_is_not_a_facility_is_not_a_disagreement() -> None:
    result = A.overlay({"highway": "primary", "cycleway:right": "no"}, way_facts())
    assert result.disagreements == ()


def test_parking_is_replaced_by_the_agency_s_count() -> None:
    none = A.overlay({"highway": "residential", "parking:both": "lane"}, way_facts(parking_lanes=0))
    assert none.tags["parking:both"] == "no"
    one = A.overlay({"highway": "residential"}, way_facts(parking_lanes=1))
    assert (one.tags["parking:right"], one.tags["parking:left"]) == ("parallel", "no")
    two = A.overlay({"highway": "residential", "parking:left": "no"}, way_facts(parking_lanes=2))
    assert two.tags["parking:both"] == "parallel"
    assert "parking:left" not in two.tags


def test_a_layer_with_no_bike_facility_field_does_not_touch_the_way_s() -> None:
    baltimore_facts = A.WayFacts(
        agency=A.BALTIMORE_AGENCY, blocks=("b",), speed_mph=25, bike={"ib": A.BIKE_LANE}
    )
    result = A.overlay({"highway": "primary", "cycleway:right": "track"}, baltimore_facts)
    assert result.tags["cycleway:right"] == "track"
    assert "bike" not in result.sources


def test_the_count_is_sourced_to_the_count_actually_used_not_the_block() -> None:
    """Review r1: the overlay named the block's agency wherever the block had a
    count, while the classifier read DDOT's. The overlay says nothing about the
    count now; the caller names the `Match` it used."""
    from pipeline.conflation import Match

    assert "aadt" not in A.overlay({"highway": "primary"}, way_facts(aadt=500)).sources
    ddot = Match(1, "f", 9000, "ddot", 2024, 1.0, "ddot")
    block = Match(1, "b", 500, "inventory", 2020, 1.0, A.DC_AGENCY)
    assert A.aadt_source(ddot) == "ddot"
    assert A.aadt_source(block) == A.DC_AGENCY
    assert A.aadt_source(None) == "none"


# -- the overlay, through the classifier --------------------------------------------


def test_a_posted_speed_replaces_the_district_default_and_moves_the_tier() -> None:
    """An unposted District residential street is read at 20 mph; the block says
    30, and a 30 mph street with a lane each way is LTS 3, not 1."""
    base = {"highway": "residential"}
    assert classify(base, jurisdiction="DC").tier <= Stress.LTS2
    overlaid = A.overlay(base, way_facts(speed_mph=30)).tags
    result = classify(overlaid, jurisdiction="DC")
    assert result.tier >= Stress.LTS3
    assert "maxspeed" not in result.assumed


def test_a_surveyed_protected_track_makes_a_busy_road_low_stress() -> None:
    base = {"highway": "primary", "maxspeed": "30 mph"}
    protected = A.overlay(
        base, way_facts(bike={"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED})
    ).tags
    assert classify(protected, jurisdiction="DC").tier is Stress.LTS1
    assert classify(base, jurisdiction="DC").tier > Stress.LTS1


def test_no_parking_widens_what_a_lane_can_earn() -> None:
    """Furth.s lane-beside-parking reach is 15 ft and without parking 5.5 ft:
    a five-foot... lane on a street the agency says has no parking is judged on the
    narrower criterion."""
    base = {"highway": "tertiary", "maxspeed": "25 mph"}
    lane = {"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}
    with_parking = A.overlay(base, way_facts(bike=lane, bike_width_ft=6.0, parking_lanes=2)).tags
    no_parking = A.overlay(base, way_facts(bike=lane, bike_width_ft=6.0, parking_lanes=0)).tags
    assert (
        classify(no_parking, jurisdiction="DC").tier
        <= classify(with_parking, jurisdiction="DC").tier
    )


def test_a_block_with_only_reversible_or_only_shared_lanes_keeps_them() -> None:
    reversible = A.parse_dc_roadway_block(
        dc(
            TOTALTRAVELLANES=2,
            TOTALTRAVELLANESINBOUND=0,
            TOTALTRAVELLANESOUTBOUND=0,
            TOTALTRAVELLANESBIDIRECTIONAL=0,
            TOTALTRAVELLANESREVERSIBLE=2,
        )
    )
    assert reversible.lanes == {"ib": 0, "ob": 0, "reversible": 2}
    assert A.lanes_per_direction(reversible) == 2
    shared = A.parse_dc_roadway_block(
        dc(
            TOTALTRAVELLANES=1,
            TOTALTRAVELLANESINBOUND=0,
            TOTALTRAVELLANESOUTBOUND=0,
            TOTALTRAVELLANESBIDIRECTIONAL=1,
        )
    )
    assert shared.lanes == {"ib": 0, "ob": 0, "bidirectional": 1}
    # A centre turn lane alone is no through lane.
    assert A.lanes_per_direction(shared) is None


# -- review r1 ----------------------------------------------------------------------


def test_the_way_s_speed_is_the_highest_of_any_direction_label() -> None:
    """M11: the way is scored on its fastest posted direction, never the slowest."""
    way = A.aggregate([("a", facts(speed_mph={"ib": 25, "ob": 35}))])
    assert way.speed_mph == 35


def test_the_narrowest_parking_lane_describes_the_way() -> None:
    """M16 / review r1: one 9 ft block must not lift a way whose others are 8 ft."""
    way = A.aggregate(
        [
            ("a", facts(parking_width_ft=8.0)),
            ("b", facts(parking_width_ft=9.0)),
            ("c", facts(parking_width_ft=8.0)),
        ]
    )
    assert way.parking_width_ft == 8.0


def test_the_parking_reach_is_added_only_where_the_agency_puts_the_lane_beside_parking() -> None:
    """DC's `BIKELANE_PARKINGLANE_ADJACENT`: a lane the agency does not record
    beside parking is measured on its own, the narrower reading. M36: the width
    reaches the classifier in metres."""
    lane = {"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}
    beside = A.aggregate(
        [("a", facts(bike=lane, bike_beside_parking=("ib", "ob"), parking_width_ft=8.0))]
    )
    assert beside.lane_beside_parking is True
    assert beside.parking_reach_m == pytest.approx(8.0 * 0.3048)
    half = A.aggregate([("a", facts(bike=lane, bike_beside_parking=("ib",), parking_width_ft=8.0))])
    assert half.parking_reach_m is None
    unrecorded = A.aggregate([("a", facts(bike=lane, parking_width_ft=8.0))])
    assert unrecorded.parking_reach_m is None
    no_width = A.aggregate([("a", facts(bike=lane, bike_beside_parking=("ib", "ob")))])
    assert no_width.parking_reach_m is None
    protected = A.aggregate([("a", facts(bike={"ib": A.BIKE_PROTECTED}, parking_width_ft=8.0))])
    assert protected.parking_reach_m is None


def test_the_parking_adjacent_field_is_read_by_direction() -> None:
    parsed = A.parse_dc_roadway_block(
        dc(BIKELANE_CONVENTIONAL="BD", BIKELANE_PARKINGLANE_ADJACENT="BD", TOTALBIKELANES=2)
    )
    assert parsed.bike_beside_parking == ("ib", "ob")
    one = A.parse_dc_roadway_block(
        dc(BIKELANE_CONVENTIONAL="IB", BIKELANE_PARKINGLANE_ADJACENT="BD", TOTALBIKELANES=1)
    )
    assert one.bike_beside_parking == ("ib",)
    assert A.parse_dc_roadway_block(dc()).bike_beside_parking == ()
    assert A.RoadFacts.from_json(json.loads(json.dumps(parsed.to_json()))) == parsed


def test_a_one_way_block_says_which_way_its_traffic_runs() -> None:
    assert A.parse_dc_roadway_block(dc(SUMMARYDIRECTION="OB")).oneway_with is True
    assert A.parse_dc_roadway_block(dc(SUMMARYDIRECTION="IB")).oneway_with is False
    assert A.parse_dc_roadway_block(dc(SUMMARYDIRECTION="BD")).oneway_with is None
    assert A.parse_baltimore_centerline(baltimore(oneway="FT")).oneway_with is True
    assert A.parse_baltimore_centerline(baltimore(oneway="TF")).oneway_with is False


def test_a_carriageway_takes_its_own_direction_s_lanes() -> None:
    """Review r1: a one-way carriageway on a two-way block took the larger
    direction's lanes. Outbound is the block's line, so a way drawn along it
    goes outbound."""
    block = facts(lanes={"ib": 3, "ob": 1}, way="both")
    along = A.aggregate([("a", block, True)])
    against = A.aggregate([("a", block, False)])
    assert (along.lanes_forward, along.lanes_backward) == (1, 3)
    assert (against.lanes_forward, against.lanes_backward) == (3, 1)
    assert A.overlay({"highway": "primary", "oneway": "yes"}, along).tags["lanes"] == "1"
    assert A.overlay({"highway": "primary", "oneway": "-1"}, along).tags["lanes"] == "3"
    assert A.overlay({"highway": "primary", "oneway": "yes"}, against).tags["lanes"] == "3"
    two_way = A.overlay({"highway": "primary"}, along).tags
    assert (two_way["lanes:forward"], two_way["lanes:backward"]) == ("1", "3")
    # Direction unknown: the busier direction, as before.
    unknown = A.aggregate([("a", block)])
    assert unknown.lanes_forward is None
    assert A.overlay({"highway": "primary", "oneway": "yes"}, unknown).tags["lanes"] == "3"


def test_reversible_lanes_count_in_both_directions_of_the_way() -> None:
    way = A.aggregate([("a", facts(lanes={"ib": 1, "ob": 1, "reversible": 2}), True)])
    assert (way.lanes_forward, way.lanes_backward) == (3, 3)


def test_a_carriageway_takes_its_own_direction_s_bike_lane() -> None:
    """Review r1: a carriageway took the other direction's lane, the lower-stress error."""
    block = facts(bike={"ib": A.BIKE_LANE}, way="both")
    eastbound = A.aggregate([("a", block, True)])  # outbound, no lane
    westbound = A.aggregate([("a", block, False)])  # inbound, the lane
    assert (eastbound.bike_forward, eastbound.bike_backward) == (A.BIKE_NONE, A.BIKE_LANE)
    east = A.overlay({"highway": "primary", "oneway": "yes"}, eastbound).tags
    west = A.overlay({"highway": "primary", "oneway": "yes"}, westbound).tags
    assert east.get("cycleway:right") is None
    assert west["cycleway:right"] == "lane"


def test_a_lane_against_a_one_way_s_traffic_is_a_contraflow_lane() -> None:
    """6th St NE (review r1): an inbound lane on an outbound one-way block was
    written as a with-flow lane. It is a contraflow lane, which opens the street
    to bicycles both ways and is no facility for the rider going with traffic."""
    from routemaker.tags import cycleway_values

    block = facts(bike={"ib": A.BIKE_LANE}, way="one", oneway_with=True)
    way = A.aggregate([("a", block, True)])
    tags = A.overlay({"highway": "residential"}, way).tags
    assert tags["oneway"] == "yes"
    assert tags["cycleway:left"] == "opposite_lane"
    assert tags["oneway:bicycle"] == "no"
    assert "cycleway:right" not in tags
    assert not ({"lane", "track"} & cycleway_values(tags))


def test_a_one_way_with_lanes_both_ways_has_a_with_flow_and_a_contraflow_lane() -> None:
    """M25: both directions having a lane is a with-flow lane and a contraflow
    lane on a one-way, and a lane on each side on a two-way."""
    block = facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}, way="one", oneway_with=True)
    way = A.aggregate([("a", block, True)])
    one_way = A.overlay({"highway": "residential", "oneway": "yes"}, way).tags
    assert one_way["cycleway:right"] == "lane"
    assert one_way["cycleway:left"] == "opposite_lane"
    two_way_block = facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}, way="both")
    two_way = A.overlay({"highway": "residential"}, A.aggregate([("a", two_way_block, True)])).tags
    assert two_way["cycleway:both"] == "lane"
    assert "opposite_lane" not in two_way.values()
    assert "oneway:bicycle" not in two_way


def test_an_agency_one_way_runs_the_way_its_traffic_runs() -> None:
    block = facts(way="one", oneway_with=True)
    along = A.overlay({"highway": "residential"}, A.aggregate([("a", block, True)]))
    against = A.overlay({"highway": "residential"}, A.aggregate([("a", block, False)]))
    assert along.tags["oneway"] == "yes"
    assert against.tags["oneway"] == "-1"


def test_an_agency_two_way_never_makes_an_untagged_way_one_way() -> None:
    """M17."""
    result = A.overlay({"highway": "residential"}, way_facts(one_way=False))
    assert "oneway" not in result.tags
    assert result.sources["oneway"] == A.SOURCE_DEFAULT
    assert result.disagreements == ()


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "primary", "oneway": "no"},
        {"highway": "primary", "lanes:forward": "3", "lanes:backward": "2"},
    ],
)
def test_an_agency_one_way_does_not_undo_explicit_osm_two_way_tagging(tags) -> None:
    """Review r1: Key Highway, mapped 3 and 2 lanes, was read as one-way. A
    mapper said two-way in so many words; it is counted as a disagreement."""
    result = A.overlay(tags, way_facts(one_way=True))
    assert result.tags.get("oneway") == tags.get("oneway")
    assert result.sources["oneway"] == A.SOURCE_OSM
    assert result.disagreements == ("oneway: agency one-way, OSM two-way",)


def test_a_bike_facility_osm_maps_as_its_own_way_is_never_written_onto_the_road() -> None:
    """Blocker 1 of review r1: 15th Street NW went from LTS 3 to 1 when the
    agency's protected lane, mapped in OSM as a separate way, was written onto
    the carriageway. It is counted as agreement and the road keeps its tags."""
    protected = way_facts(bike={"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED})
    tags = {"highway": "primary", "maxspeed": "30 mph", "lanes": "4", "cycleway:left": "separate"}
    result = A.overlay(tags, protected)
    assert result.tags["cycleway:left"] == "separate"
    facility_values = {v for k, v in result.tags.items() if k.startswith("cycleway")}
    assert not ({"track", "lane"} & facility_values)
    assert result.sources["bike"] == A.SOURCE_OSM
    assert result.agreements == ("bike facility: OSM maps it as a separate way",)
    assert result.disagreements == ()
    for key in ("cycleway", "cycleway:both", "cycleway:right"):
        kept = A.overlay({"highway": "primary", key: "separate"}, protected)
        assert kept.tags[key] == "separate"
    beside = A.overlay({"highway": "primary", "maxspeed": "30 mph"}, protected, separate_road=True)
    assert not any(k.startswith("cycleway") for k in beside.tags)
    assert classify(beside.tags, jurisdiction="DC").tier > Stress.LTS1


def test_baltimore_s_speed_fills_only_where_osm_has_none() -> None:
    """OWNER-DECISIONS 184: "Fill gaps only (Recommended)"."""
    city = A.WayFacts(agency=A.BALTIMORE_AGENCY, blocks=("b",), speed_mph=25)
    posted = A.overlay({"highway": "primary", "maxspeed": "30 mph"}, city)
    assert posted.tags["maxspeed"] == "30 mph"
    assert posted.sources["maxspeed"] == A.SOURCE_OSM
    assert posted.disagreements == ("maxspeed: agency and OSM differ, OSM's posted speed kept",)
    gap = A.overlay({"highway": "primary"}, city)
    assert gap.tags["maxspeed"] == "25 mph"
    assert gap.sources["maxspeed"] == A.BALTIMORE_AGENCY
    same = A.overlay({"highway": "primary", "maxspeed": "25 mph"}, city)
    assert same.disagreements == ()


def test_a_slip_road_keeps_its_own_lanes() -> None:
    """Review r1: a one-lane ramp took its parent's block and read as 2 to 4 lanes."""
    ramp = A.overlay({"highway": "primary_link", "lanes": "1"}, way_facts(lanes_per_direction=3))
    assert ramp.tags["lanes"] == "1"
    assert ramp.sources["lanes"] == A.SOURCE_OSM
    assert A.block_count_applies({"highway": "primary_link"}) is False
    assert A.block_count_applies({"highway": "primary"}) is True


def test_an_internal_only_layer_is_refused(tmp_path) -> None:
    """OWNER-DECISIONS 155: the internal-comparison layers never reach the rebuild."""
    inside = tmp_path / "datasets" / "internal-only" / "x" / "x.geojson"
    with pytest.raises(A.InternalOnlySource):
        A.refuse_internal_only(inside)
    assert A.refuse_internal_only(tmp_path / "datasets" / "dc" / "dc.geojson")


def test_a_reversed_one_way_takes_the_lane_running_its_way() -> None:
    """`oneway=-1`: the way's traffic runs against its own digitising, so the lane
    the block records in that direction is the with-flow lane, not a contraflow one."""
    block = facts(bike={"ib": A.BIKE_LANE})
    way = A.aggregate([("a", block, True)])  # the lane runs inbound, against the way
    tags = A.overlay({"highway": "residential", "oneway": "-1"}, way).tags
    assert tags["cycleway:right"] == "lane"
    assert "cycleway:left" not in tags
    assert "oneway:bicycle" not in tags


def test_a_divided_road_s_carriageway_takes_nothing_from_the_other_carriageway() -> None:
    """Review r1: a one-way carriageway on a two-way block took the other direction's
    lane. That lane is the other carriageway's, not a contraflow lane on this one, and
    an OSM lane on this carriageway is left alone (the agency's silence about it is
    not evidence it is gone)."""
    block = facts(bike={"ib": A.BIKE_LANE}, way="both")
    eastbound = A.aggregate([("a", block, True)])
    bare = A.overlay({"highway": "primary", "oneway": "yes"}, eastbound)
    assert not any(k.startswith("cycleway") for k in bare.tags)
    assert "oneway:bicycle" not in bare.tags
    mapped = A.overlay({"highway": "primary", "oneway": "yes", "cycleway:right": "lane"}, eastbound)
    assert mapped.tags["cycleway:right"] == "lane"
    assert mapped.sources["bike"] == A.SOURCE_OSM
