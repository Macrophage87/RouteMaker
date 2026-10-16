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
from routemaker import massflow
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


def test_reversible_lanes_count_in_each_direction_for_the_classifier(monkeypatch) -> None:
    """OWNER-DECISIONS 425: "Keep counting them, probably in each direction in most
    cases. These tend to be high stress commuter roads." A 16th St NW style block of one
    lane each way and two that reverse is three lanes in each direction for the
    classifier and the crossings, verified or not."""
    facts = A.parse_dc_roadway_block(
        dc(
            TOTALTRAVELLANES=4,
            TOTALTRAVELLANESINBOUND=1,
            TOTALTRAVELLANESOUTBOUND=1,
            TOTALTRAVELLANESREVERSIBLE=2,
            BLOCKKEY="unverified-block",
            ROUTENAME="16TH ST NW",
        )
    )
    assert facts.lanes == {"ib": 1, "ob": 1, "reversible": 2}
    assert not A.VERIFIED_REVERSIBLE_BLOCKS
    assert A.classifier_reversible(facts) == 2
    assert A.lanes_per_direction(facts) == 3
    assert A._directional_lanes(facts, "ib") == A._directional_lanes(facts, "ob") == 3
    # Canal Rd's shape: a block that records only reversible lanes.
    canal = A.parse_dc_roadway_block(
        dc(
            TOTALTRAVELLANES=3,
            TOTALTRAVELLANESINBOUND=0,
            TOTALTRAVELLANESOUTBOUND=0,
            TOTALTRAVELLANESREVERSIBLE=3,
            BLOCKKEY="canal-block",
            ROUTENAME="CANAL RD NW",
        )
    )
    assert A.lanes_per_direction(canal) == 3


def test_the_mass_ride_width_counts_reversible_lanes_only_on_a_verified_block(monkeypatch) -> None:
    """405 stands for the Mass Ride width (425 changed the classifier only): the layer's
    reversible count is stale where the operation ended, so the width counts none unless
    the block's BLOCKKEY is on the reviewed allowlist (empty)."""
    facts = A.parse_dc_roadway_block(
        dc(
            TOTALTRAVELLANESINBOUND=1,
            TOTALTRAVELLANESOUTBOUND=1,
            TOTALTRAVELLANESREVERSIBLE=2,
            BLOCKKEY="verified-block",
            ROUTENAME="16TH ST NW",
        )
    )
    assert A.counted_reversible(facts) == 0
    assert massflow.DC_RULES.reversible_lanes(facts) == 0
    monkeypatch.setattr(A, "VERIFIED_REVERSIBLE_BLOCKS", frozenset({facts.block_key}))
    assert A.counted_reversible(facts) == 2


def test_connecticut_avenue_s_reversible_lanes_never_count(monkeypatch) -> None:
    """405: "Conneticut Avenue Reversible lanes were removed in 2020." Even an
    allowlisted Connecticut Avenue NW block counts none."""
    facts = A.parse_dc_roadway_block(
        dc(
            TOTALTRAVELLANESINBOUND=1,
            TOTALTRAVELLANESOUTBOUND=1,
            TOTALTRAVELLANESREVERSIBLE=2,
            BLOCKKEY="ct-block",
            ROUTENAME="CONNECTICUT AVE NW",
        )
    )
    monkeypatch.setattr(A, "VERIFIED_REVERSIBLE_BLOCKS", frozenset({facts.block_key}))
    assert "CONNECTICUT AVE NW" in A.ENDED_REVERSIBLE_STREETS
    assert A.counted_reversible(facts) == 0
    # Nor for the classifier (425's exception: Connecticut follows 412's lane override).
    assert A.classifier_reversible(facts) == 0
    assert A.lanes_per_direction(facts) == 1


def test_the_classifier_and_the_mass_ride_width_share_the_reversible_lists() -> None:
    """One list for both readings (405): the settings the rebuild builds the Mass Ride
    rules from equal the classifier's."""
    from django.conf import settings

    from routemaker import massflow

    assert (
        frozenset(settings.MASS_RIDE_DC_VERIFIED_REVERSIBLE_BLOCKS) == A.VERIFIED_REVERSIBLE_BLOCKS
    )
    assert frozenset(settings.MASS_RIDE_DC_ENDED_REVERSIBLE_STREETS) == A.ENDED_REVERSIBLE_STREETS
    assert massflow.DC_RULES.ended_reversible_streets == A.ENDED_REVERSIBLE_STREETS


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


@pytest.mark.parametrize(("forward", "oneway"), [(True, "yes"), (False, "-1")])
def test_an_agency_one_way_is_believed_where_osm_says_nothing(forward, oneway) -> None:
    """And it is the routing graph's direction too (OWNER-DECISIONS 216)."""
    result = A.overlay(
        {"highway": "residential"}, way_facts(one_way=True, oneway_forward=forward), length_m=120.0
    )
    assert result.tags["oneway"] == oneway
    assert result.sources["oneway"] == A.DC_AGENCY
    assert result.routing == {"oneway": oneway}
    assert result.disagreements == ()


@pytest.mark.parametrize(
    ("facts_kwargs", "length_m", "reason"),
    [
        (
            {"lanes_by_direction": {"ib": 1, "ob": 0, "reversible": 1}, "oneway_forward": True},
            753.0,
            "reversible lanes",
        ),
        ({"oneway_forward": True}, 17.0, "junction stub"),
        ({}, 200.0, "direction unknown"),
    ],
)
def test_a_one_way_osm_does_not_tag_takes_row_b_s_exceptions(facts_kwargs, length_m, reason):
    """OWNER-DECISIONS 216: the record's one-way is the routing direction, so it
    is never written where the direction is a guess (the record does not say
    which way the traffic runs), on a junction stub, or on reversible lanes; the
    way stays as OSM leaves it, for the classifier and the graph alike."""
    result = A.overlay(
        {"highway": "residential"}, way_facts(one_way=True, **facts_kwargs), length_m=length_m
    )
    assert "oneway" not in result.tags
    assert result.sources["oneway"] == A.SOURCE_DEFAULT
    assert result.routing == {}
    assert result.disagreements == (f"oneway: agency one-way, OSM two-way, kept ({reason})",)


@pytest.mark.parametrize(
    ("tags", "context", "reason"),
    [
        ({"highway": "primary"}, {"divided": True}, "divided carriageway"),
        ({"highway": "primary"}, {"paired": True}, "carriageway pair"),
        ({"highway": "primary_link"}, {}, "slip road or freeway"),
        ({"highway": "motorway"}, {}, "slip road or freeway"),
        ({"highway": "trunk"}, {}, "slip road or freeway"),
        ({"highway": "primary", "junction": "roundabout"}, {}, "roundabout"),
    ],
)
def test_a_district_two_way_does_not_undo_a_carriageway_s_one_way(tags, context, reason) -> None:
    """OWNER-DECISIONS 190 rows C1-C3: the block is the whole road, so a divided
    road's carriageways, a slip road and a freeway stay one-way."""
    result = A.overlay(
        {**tags, "oneway": "yes"}, way_facts(one_way=False, two_way_throughout=True), **context
    )
    assert result.tags["oneway"] == "yes"
    assert result.sources["oneway"] == A.SOURCE_OSM
    assert result.disagreements == (f"oneway: agency two-way, OSM one-way, kept ({reason})",)
    assert result.precedence == ()
    assert result.routing == {}


def test_a_district_two_way_makes_a_plain_one_way_street_two_way() -> None:
    """OWNER-DECISIONS 190 row C4: "DC data takes priority over OSM"."""
    street = way_facts(one_way=False, two_way_throughout=True, names_agree=True)
    result = A.overlay({"highway": "residential", "oneway": "yes"}, street, length_m=120.0)
    assert result.tags["oneway"] == "no"
    assert result.sources["oneway"] == A.DC_AGENCY
    assert result.precedence == (A.ROW_TWO_WAY,)
    assert result.disagreements == ()
    # Rewritten, not removed: the graph's tags are laid over OSM's.
    assert result.routing == {"oneway": "no"}
    # Not where one of its blocks is one-way: the way runs on past the two-way one.
    blocks = [("a", facts(way="both"), True), ("b", facts(way="one", oneway_with=True), True)]
    mixed = A.overlay(
        {"highway": "residential", "oneway": "yes"}, A.aggregate(blocks, True), length_m=120.0
    )
    assert mixed.disagreements == (
        "oneway: agency two-way, OSM one-way, kept (one-way blocks along it)",
    )
    assert mixed.tags["oneway"] == "yes"
    assert mixed.precedence == ()
    # Nor a junction stub, nor a way whose name does not agree with the block's.
    stub = A.overlay({"highway": "residential", "oneway": "yes"}, street, length_m=25.0)
    assert stub.disagreements == ("oneway: agency two-way, OSM one-way, kept (junction stub)",)
    unnamed = A.overlay(
        {"highway": "residential", "oneway": "yes"},
        way_facts(one_way=False, two_way_throughout=True),
        length_m=120.0,
    )
    assert unnamed.disagreements == ("oneway: agency two-way, OSM one-way, kept (unnamed)",)


def test_another_agency_s_two_way_never_undoes_osm_s_one_way() -> None:
    city = A.WayFacts(
        agency=A.BALTIMORE_AGENCY, blocks=("b",), one_way=False, two_way_throughout=True
    )
    result = A.overlay({"highway": "residential", "oneway": "yes"}, city, length_m=120.0)
    assert result.tags["oneway"] == "yes"
    assert result.sources["oneway"] == A.SOURCE_OSM
    assert result.routing == {}
    assert result.precedence == ()


@pytest.mark.parametrize("forward", [True, False])
def test_baltimore_s_one_way_is_never_used_and_is_reported(forward) -> None:
    """OWNER-DECISIONS 222: "Ignore it; keep OSM (Recommended)". The Baltimore
    one-way field is never used for stress or routing; the difference goes into
    the report. (Correctness review, blocker 1: W Cold Spring Ln 66418027 and
    Broening Hwy 54675215 were made one-way with 4 lanes a direction.)"""
    city = A.WayFacts(
        agency=A.BALTIMORE_AGENCY,
        blocks=("b",),
        one_way=True,
        oneway_forward=forward,
        lanes_per_direction=4,
    )
    tags = {"highway": "primary", "lanes": "4", "maxspeed": "30 mph"}
    result = A.overlay(tags, city, length_m=300.0)
    assert "oneway" not in result.tags
    assert result.tags["lanes"] == "4"
    assert "lanes:forward" not in result.tags
    assert result.sources["oneway"] == A.SOURCE_DEFAULT
    assert result.sources["lanes"] == A.SOURCE_OSM
    assert result.routing == {}
    assert result.disagreements == (
        "oneway: agency one-way, OSM two-way; not used (OWNER-DECISIONS 222)",
        "lanes: agency 4 a direction, OSM 2; not used (OWNER-DECISIONS 222)",
    )
    assert classify(result.tags, urban=True).oneway is False


def test_baltimore_s_lanes_are_never_used_but_its_speed_fills_a_gap() -> None:
    """OWNER-DECISIONS 223: "Baltimore is a gap-filler only: ... speed where OSM
    has none (184); one-way and lanes are never used (222)." The spec review:
    Baltimore's lane count overrode OSM's."""
    city = A.WayFacts(agency=A.BALTIMORE_AGENCY, blocks=("b",), lanes_per_direction=3, speed_mph=25)
    result = A.overlay({"highway": "secondary", "lanes": "2"}, city, length_m=300.0)
    assert result.tags["lanes"] == "2"
    assert result.tags["maxspeed"] == "25 mph"
    assert result.sources["maxspeed"] == A.BALTIMORE_AGENCY
    assert result.sources["lanes"] == A.SOURCE_OSM
    assert result.disagreements == (
        "lanes: agency 3 a direction, OSM 1; not used (OWNER-DECISIONS 222)",
    )
    agreeing = A.overlay({"highway": "secondary", "lanes": "6"}, city, length_m=300.0)
    assert agreeing.disagreements == ()
    unlaned = A.overlay({"highway": "secondary"}, city, length_m=300.0)
    assert "lanes" not in unlaned.tags
    assert unlaned.sources["lanes"] == A.SOURCE_DEFAULT
    # A Baltimore one-way the other way from OSM's is reported, never applied.
    against = A.WayFacts(
        agency=A.BALTIMORE_AGENCY, blocks=("b",), one_way=True, oneway_forward=False
    )
    reversed_ = A.overlay({"highway": "residential", "oneway": "yes"}, against, length_m=300.0)
    assert reversed_.tags["oneway"] == "yes"
    assert reversed_.routing == {}
    assert reversed_.disagreements == (
        "oneway: agency one-way the other way from OSM's; not used (OWNER-DECISIONS 222)",
    )


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
    # To the millimetre (review SF2): 1.52 m fell short of Furth's 15 ft reach
    # beside a 10 ft parking lane, where 5 ft meets it exactly.
    assert result.tags["cycleway:both:width"] == "1.524"


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
    # OSM's own one-way: nothing for the graph to take.
    assert result.routing == {}


@pytest.mark.parametrize("forward", [True, False])
def test_a_one_way_the_district_makes_keeps_its_contraflow_lane_for_routing(forward) -> None:
    """OWNER-DECISIONS 216 with 192: where the record makes a way one-way and
    flags a contraflow lane, the graph takes the lane as the reverse direction
    (which the standard graph rides and the no-trail graph closes)."""
    ahead, behind = ("ob", "ib") if forward else ("ib", "ob")
    result = A.overlay(
        {"highway": "residential", "oneway": "no"},
        way_facts(
            one_way=True,
            oneway_forward=forward,
            direction_known=True,
            bike_forward=A.BIKE_LANE,
            bike_backward=A.BIKE_LANE,
            bike={ahead: A.BIKE_LANE, behind: A.BIKE_LANE},
            contraflow=True,
        ),
        length_m=200.0,
    )
    oneway = "yes" if forward else "-1"
    assert result.routing == {
        "oneway": oneway,
        "oneway:bicycle": "no",
        "cycleway:left": "opposite_lane",
    }
    assert result.tags["oneway"] == oneway
    # And without the flag, no contraflow is routed.
    plain = A.overlay(
        {"highway": "residential", "oneway": "no"},
        way_facts(one_way=True, oneway_forward=forward),
        length_m=200.0,
    )
    assert plain.routing == {"oneway": oneway}


def test_a_district_record_of_no_facility_removes_osm_s_painted_lane() -> None:
    """OWNER-DECISIONS 190 row A: "including a record of no facility"."""
    result = A.overlay(
        {
            "highway": "primary",
            "cycleway": "lane",
            "cycleway:width": "1.5",
            "cycleway:left": "opposite_lane",
            "cycleway:right:buffer": "yes",
            "cycleway:right": "buffered_lane",
        },
        way_facts(),
    )
    assert not any(key.startswith("cycleway") for key in result.tags)
    assert result.sources["bike"] == A.DC_AGENCY
    assert result.precedence == (A.ROW_NO_FACILITY,)
    assert result.disagreements == ()


def test_a_district_record_of_no_facility_keeps_a_track_and_says_so() -> None:
    result = A.overlay(
        {"highway": "primary", "cycleway:right": "track", "cycleway:left": "lane"}, way_facts()
    )
    assert result.tags["cycleway:right"] == "track"
    assert "cycleway:left" not in result.tags
    assert result.disagreements == ("bike facility: OSM has a track, the agency records none",)


def test_no_facility_is_decided_per_block_not_on_the_weakest_block() -> None:
    """Review r2: the worst-block reading would erase a lane one of the way's own
    blocks records. The way keeps OSM's lane, and the report says so."""
    lane_block = facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_LANE})
    way = A.aggregate([("a", lane_block, True), ("b", facts(), True)])
    assert way.bike_forward == way.bike_backward == A.BIKE_NONE
    assert way.bike_recorded is True
    result = A.overlay({"highway": "primary", "cycleway:both": "lane"}, way)
    assert result.tags["cycleway:both"] == "lane"
    assert result.precedence == ()
    assert result.disagreements == ("bike facility: OSM has one, the agency records none",)


def test_a_direction_one_block_records_keeps_osm_s_lane_on_that_side() -> None:
    """Review r2 (11th Street SE): a lane both ways on one block and one way on
    the next wrote one side only, erasing OSM's lane that the first block records."""
    both = facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}, way="both")
    outbound = facts(bike={"ob": A.BIKE_LANE}, way="both")
    way = A.aggregate([("a", both, True), ("b", outbound, True)])
    assert (way.bike_forward, way.bike_backward) == (A.BIKE_LANE, A.BIKE_NONE)
    assert (way.bike_forward_most, way.bike_backward_most) == (A.BIKE_LANE, A.BIKE_LANE)
    kept = A.overlay({"highway": "tertiary", "cycleway:both": "lane"}, way).tags
    assert kept["cycleway:both"] == "lane"
    bare = A.overlay({"highway": "tertiary"}, way).tags
    assert bare["cycleway:right"] == "lane"
    assert "cycleway:left" not in bare


def test_another_agency_s_silence_leaves_osm_s_lane() -> None:
    city = A.WayFacts(agency=A.BALTIMORE_AGENCY, blocks=("b",))
    result = A.overlay({"highway": "primary", "cycleway:right": "lane"}, city)
    assert result.tags["cycleway:right"] == "lane"
    assert result.precedence == ()


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
    # The classifier counts reversible lanes, unverified too, in each direction (425).
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
    assert (
        A.overlay({"highway": "primary", "oneway": "yes"}, along, divided=True).tags["lanes"] == "1"
    )
    assert (
        A.overlay({"highway": "primary", "oneway": "-1"}, along, divided=True).tags["lanes"] == "3"
    )
    assert (
        A.overlay({"highway": "primary", "oneway": "yes"}, against, divided=True).tags["lanes"]
        == "3"
    )
    two_way = A.overlay({"highway": "primary"}, along).tags
    assert (two_way["lanes:forward"], two_way["lanes:backward"]) == ("1", "3")
    # Direction unknown: the busier direction, as before.
    unknown = A.aggregate([("a", block)])
    assert unknown.lanes_forward is None
    assert (
        A.overlay({"highway": "primary", "oneway": "yes"}, unknown, divided=True).tags["lanes"]
        == "3"
    )


def test_verified_reversible_lanes_count_in_both_directions_of_the_way(monkeypatch) -> None:
    block = facts(lanes={"ib": 1, "ob": 1, "reversible": 2}, block_key="k")
    way = A.aggregate([("a", block, True)])
    # OWNER-DECISIONS 425: verified or not, each direction counts them.
    assert (way.lanes_forward, way.lanes_backward) == (3, 3)
    monkeypatch.setattr(A, "VERIFIED_REVERSIBLE_BLOCKS", frozenset({"k"}))
    way = A.aggregate([("a", block, True)])
    assert (way.lanes_forward, way.lanes_backward) == (3, 3)
    ct = facts(lanes={"ib": 1, "ob": 1, "reversible": 2}, block_key="k", name="CONNECTICUT AVE NW")
    way = A.aggregate([("a", ct, True)])
    assert (way.lanes_forward, way.lanes_backward) == (1, 1), "Connecticut follows 412"


def test_a_carriageway_takes_its_own_direction_s_bike_lane() -> None:
    """Review r1: a carriageway took the other direction's lane, the lower-stress error."""
    block = facts(bike={"ib": A.BIKE_LANE}, way="both")
    eastbound = A.aggregate([("a", block, True)])  # outbound, no lane
    westbound = A.aggregate([("a", block, False)])  # inbound, the lane
    assert (eastbound.bike_forward, eastbound.bike_backward) == (A.BIKE_NONE, A.BIKE_LANE)
    east = A.overlay({"highway": "primary", "oneway": "yes"}, eastbound, divided=True).tags
    west = A.overlay({"highway": "primary", "oneway": "yes"}, westbound, divided=True).tags
    assert east.get("cycleway:right") is None
    assert west["cycleway:right"] == "lane"


def test_a_flagged_lane_against_a_one_way_s_traffic_is_a_contraflow_lane() -> None:
    """A lane against the traffic on a block DC flags `BIKELANE_CONTRAFLOW` is a
    contraflow lane, which opens the street to bicycles both ways and is no
    facility for the rider going with traffic."""
    from routemaker.tags import cycleway_values

    block = facts(bike={"ib": A.BIKE_LANE}, way="one", oneway_with=True, contraflow=True)
    way = A.aggregate([("a", block, True)])
    tags = A.overlay({"highway": "residential"}, way).tags
    assert tags["oneway"] == "yes"
    assert tags["cycleway:left"] == "opposite_lane"
    assert tags["oneway:bicycle"] == "no"
    assert "cycleway:right" not in tags
    assert not ({"lane", "track"} & cycleway_values(tags))


@pytest.mark.parametrize("label", ["ib", "ob"])
@pytest.mark.parametrize("along", [True, False])
def test_a_lone_lane_on_an_unflagged_one_way_block_is_the_with_flow_lane(label, along) -> None:
    """Review r2: on unflagged one-way blocks DC labels the lane against the
    traffic 200 times and with it 56, where OSM maps a with-flow lane; only the
    contraflow flag is a reliable signal. R Street NW, 4th Street SE and others
    lost their with-flow lane to an `opposite_lane`."""
    block = facts(bike={label: A.BIKE_LANE}, way="one", oneway_with=True)
    way = A.aggregate([("a", block, along)])
    tags = A.overlay({"highway": "residential"}, way).tags
    assert tags["oneway"] == ("yes" if along else "-1")
    assert tags["cycleway:right"] == "lane"
    assert "cycleway:left" not in tags
    assert "oneway:bicycle" not in tags


def test_a_one_way_with_lanes_both_ways_has_a_with_flow_and_a_contraflow_lane() -> None:
    """M25: both directions having a lane is a with-flow lane and a contraflow
    lane on a flagged one-way, the with-flow lane alone on an unflagged one, and
    a lane on each side on a two-way."""
    block = facts(
        bike={"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}, way="one", oneway_with=True, contraflow=True
    )
    way = A.aggregate([("a", block, True)])
    one_way = A.overlay({"highway": "residential", "oneway": "yes"}, way).tags
    assert one_way["cycleway:right"] == "lane"
    assert one_way["cycleway:left"] == "opposite_lane"
    unflagged = facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_BUFFERED}, way="one", oneway_with=True)
    plain = A.overlay({"highway": "residential"}, A.aggregate([("a", unflagged, True)])).tags
    assert plain["cycleway:right"] == "lane"
    assert plain["cycleway:right:buffer"] == "yes"
    assert "cycleway:left" not in plain
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
def test_baltimore_s_one_way_does_not_undo_explicit_osm_two_way_tagging(tags) -> None:
    """Review r1: Key Highway, mapped 3 and 2 lanes, was read as one-way. Outside
    the District a mapper's explicit two-way stands; it is counted (and since
    OWNER-DECISIONS 222 Baltimore's one-way is never used at all)."""
    city = A.WayFacts(agency=A.BALTIMORE_AGENCY, blocks=("b",), one_way=True, oneway_forward=True)
    result = A.overlay(tags, city, length_m=200.0)
    assert result.tags.get("oneway") == tags.get("oneway")
    assert result.sources["oneway"] == A.SOURCE_OSM
    assert result.routing == {}
    assert result.disagreements == (
        "oneway: agency one-way, OSM two-way; not used (OWNER-DECISIONS 222)",
    )


@pytest.mark.parametrize("forward", [True, False])
def test_a_district_one_way_overrides_explicit_osm_two_way_tagging(forward) -> None:
    """OWNER-DECISIONS 190 row B."""
    tags = {"highway": "secondary", "lanes:forward": "2", "lanes:backward": "1", "lanes": "3"}
    result = A.overlay(tags, way_facts(one_way=True, oneway_forward=forward), length_m=200.0)
    assert result.tags["oneway"] == ("yes" if forward else "-1")
    assert result.sources["oneway"] == A.DC_AGENCY
    assert result.precedence == (A.ROW_ONE_WAY,)
    # The routing graph's direction too (OWNER-DECISIONS 216).
    assert result.routing == {"oneway": "yes" if forward else "-1"}
    # The block records no lanes: the count OSM gives the traffic's direction.
    assert result.tags["lanes"] == ("2" if forward else "1")
    assert "lanes:forward" not in result.tags


@pytest.mark.parametrize(
    ("facts_kwargs", "length_m", "reason"),
    [
        # Clara Barton Parkway: one lane inbound and one reversible.
        (
            {"lanes_by_direction": {"ib": 1, "ob": 0, "reversible": 1}, "oneway_forward": True},
            753.0,
            "reversible lanes",
        ),
        ({"oneway_forward": True}, 17.0, "junction stub"),
        ({}, 200.0, "direction unknown"),
    ],
)
def test_the_district_s_one_way_exceptions(facts_kwargs, length_m, reason) -> None:
    result = A.overlay(
        {"highway": "primary", "oneway": "no"},
        way_facts(one_way=True, **facts_kwargs),
        length_m=length_m,
    )
    assert result.tags["oneway"] == "no"
    assert result.precedence == ()
    assert result.routing == {}
    assert result.disagreements == (f"oneway: agency one-way, OSM two-way, kept ({reason})",)


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
    bare = A.overlay({"highway": "primary", "oneway": "yes"}, eastbound, divided=True)
    assert not any(k.startswith("cycleway") for k in bare.tags)
    assert "oneway:bicycle" not in bare.tags
    mapped = A.overlay(
        {"highway": "primary", "oneway": "yes", "cycleway:right": "lane"}, eastbound, divided=True
    )
    assert mapped.tags["cycleway:right"] == "lane"
    assert mapped.sources["bike"] == A.SOURCE_OSM


# -- review r2 ----------------------------------------------------------------------


def _way(osm_id: int, tags: dict):
    from types import SimpleNamespace

    return SimpleNamespace(osm_id=osm_id, tags=tags)


def test_a_block_is_separate_once_any_way_on_it_is() -> None:
    """Blocker 1 of review r2 (Irving Street's pattern): OSM maps the protected
    lane as its own way beside one carriageway, which it marks
    `cycleway:right=separate`; the other carriageway, a 35 mph motor road, shares
    the block and was written a track and rated LTS 1."""
    protected = facts(bike={"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED}, way="both")
    east = A.aggregate([("irving", protected, True)])
    west = A.aggregate([("irving", protected, False)])
    tags = {
        1: {"highway": "primary", "oneway": "yes", "cycleway:right": "separate"},
        2: {"highway": "primary", "oneway": "yes", "maxspeed": "35 mph", "lanes": "2"},
    }
    separate, paired, _ = A.block_context({1: east, 2: west}, tags)
    assert separate == {1, 2}
    assert paired == {1, 2}
    motor = A.overlay(tags[2], west, separate_road=2 in separate, paired=True)
    assert not any(k.startswith("cycleway") for k in motor.tags)
    assert motor.agreements == ("bike facility: OSM maps it as a separate way",)
    assert classify(motor.tags, jurisdiction="DC").tier > Stress.LTS1
    # A way of its own beside the road (`separate_roads`) marks the block too.
    separate = A.block_context({2: west, 3: east}, {2: tags[2], 3: tags[2]}, {3}).separate
    assert separate == {2, 3}
    # And a block no separate way lies on is not.
    alone = A.block_context({2: west}, {2: tags[2]}).separate
    assert alone == frozenset()


def test_overlay_road_facts_wires_the_block_context() -> None:
    """The rebuild's wiring (`pipeline.conflation.overlay_road_facts`): the motor
    carriageway sharing a block with a separate-mapped one takes no track."""
    from pipeline.conflation import overlay_road_facts

    protected = facts(bike={"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED}, way="both")
    line = [(-77.0, 38.9), (-76.999, 38.9)]
    ways = [
        SimpleWay(1, {"highway": "primary", "oneway": "yes", "cycleway:right": "separate"}, line),
        SimpleWay(2, {"highway": "primary", "oneway": "yes", "maxspeed": "35 mph"}, line[::-1]),
        SimpleWay(3, {"highway": "primary", "maxspeed": "30 mph"}, line),
    ]
    by_way = {
        1: A.aggregate([("irving", protected, True)]),
        2: A.aggregate([("irving", protected, False)]),
        3: A.aggregate([("other", protected, True)]),
    }
    overlays = overlay_road_facts(ways, by_way)
    assert not any(k.startswith("cycleway") for k in overlays[2].tags)
    assert overlays[3].tags["cycleway:both"] == "track"


class SimpleWay:
    def __init__(self, osm_id, tags, coordinates) -> None:
        self.osm_id, self.tags, self.coordinates = osm_id, tags, coordinates


@pytest.mark.parametrize(
    "refusal",
    [
        {"bicycle": "no"},
        {"bicycle": "use_sidepath"},
        {"cycleway:both": "no"},
        {"cycleway": "no"},
        {"cycleway:left": "no"},
    ],
)
def test_a_protected_lane_is_never_written_where_osm_says_the_road_has_none(refusal) -> None:
    """Review r2: Arizona Avenue NW (`cycleway:both=no`) went from LTS 3 to 1 on a
    track; Irving Street's motor carriageway is `bicycle=no`."""
    protected = way_facts(bike={"ib": A.BIKE_PROTECTED, "ob": A.BIKE_PROTECTED})
    base = {"highway": "primary", "maxspeed": "30 mph", "lanes": "2"}
    result = A.overlay({**base, **refusal}, protected)
    assert not ({"track", "opposite_track"} & set(result.tags.values()))
    assert result.sources["bike"] in (A.SOURCE_OSM, A.SOURCE_DEFAULT)
    assert result.disagreements[-1].startswith("bike facility: agency protected lane")
    assert classify(result.tags, jurisdiction="DC").tier > Stress.LTS1
    # A painted lane is still the District's to record (OWNER-DECISIONS 190).
    lane = A.overlay({**base, **refusal}, way_facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}))
    assert lane.tags["cycleway:both"] == "lane"


def test_a_two_way_way_on_a_one_way_block_keeps_osm_s_lanes() -> None:
    """Review r2: New Jersey Avenue NW, OSM `oneway=no` and `lanes=2` on a one-way
    block, was written four lanes each way from the busier direction."""
    block = facts(lanes={"ib": 0, "ob": 4}, way="one", oneway_with=True)
    way = A.aggregate([("nj", block, True)])
    assert (way.lanes_forward, way.lanes_backward) == (4, None)
    stub = A.overlay({"highway": "secondary", "oneway": "no", "lanes": "2"}, way, length_m=17.0)
    assert stub.tags["oneway"] == "no"
    assert stub.tags["lanes"] == "2"
    assert "lanes:forward" not in stub.tags
    assert stub.sources["lanes"] == A.SOURCE_OSM
    # Followed as one-way (row B), it takes the one-way's own count.
    long = A.overlay({"highway": "secondary", "oneway": "no", "lanes": "2"}, way, length_m=200.0)
    assert (long.tags["oneway"], long.tags["lanes"]) == ("yes", "4")


def test_a_lane_beside_parking_needs_every_block_to_say_so() -> None:
    """M10: one block's lane beside parking does not lend its reach to the way."""
    lane = {"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}
    beside = facts(bike=lane, bike_beside_parking=("ib", "ob"), parking_width_ft=8.0)
    apart = facts(bike=lane, parking_width_ft=8.0)
    assert A.aggregate([("a", beside), ("b", apart)]).lane_beside_parking is False
    assert A.aggregate([("a", beside), ("b", beside)]).lane_beside_parking is True


def test_on_a_two_way_way_the_forward_lane_is_on_the_right() -> None:
    """M27: the way's own direction runs on its right-hand side."""
    block = facts(bike={"ob": A.BIKE_LANE, "ib": A.BIKE_BUFFERED}, way="both")
    along = A.overlay({"highway": "tertiary"}, A.aggregate([("a", block, True)])).tags
    assert along["cycleway:right"] == "lane"
    assert along["cycleway:left"] == "lane"
    assert along["cycleway:left:buffer"] == "yes"
    assert "cycleway:right:buffer" not in along
    against = A.overlay({"highway": "tertiary"}, A.aggregate([("a", block, False)])).tags
    assert against["cycleway:right:buffer"] == "yes"
    assert "cycleway:left:buffer" not in against


def test_the_way_s_forward_facility_is_its_weakest_block_s() -> None:
    """M28: a lane one block records and the next does not is no lane."""
    lane = facts(bike={"ob": A.BIKE_LANE}, way="both")
    way = A.aggregate([("a", lane, True), ("b", facts(way="both"), True)])
    assert way.bike_forward == A.BIKE_NONE
    assert way.bike_forward_most == A.BIKE_LANE
    tags = A.overlay({"highway": "tertiary"}, way).tags
    assert not any(k.startswith("cycleway") for k in tags)


def test_an_internal_only_layer_reached_through_a_symlink_is_refused(tmp_path) -> None:
    """M23: the guard resolves the path, so a link elsewhere into internal-only/
    is refused too."""
    hidden = tmp_path / "datasets" / "internal-only" / "x"
    hidden.mkdir(parents=True)
    (hidden / "x.geojson").write_text("{}")
    link = tmp_path / "elsewhere"
    link.symlink_to(hidden)
    with pytest.raises(A.InternalOnlySource):
        A.refuse_internal_only(link / "x.geojson")


def test_each_item_190_row_can_be_left_out_for_the_report() -> None:
    """`rows`: the before-after report measures each row's own tier effect by
    leaving it out; with none, the overlay is round 1's."""
    no_facility = A.overlay({"highway": "primary", "cycleway:right": "lane"}, way_facts(), rows=())
    assert no_facility.tags["cycleway:right"] == "lane"
    assert no_facility.disagreements == ("bike facility: OSM has one, the agency records none",)
    one_way = A.overlay(
        {"highway": "primary", "oneway": "no"},
        way_facts(one_way=True, oneway_forward=True),
        length_m=200.0,
        rows={A.ROW_NO_FACILITY, A.ROW_TWO_WAY},
    )
    assert one_way.tags["oneway"] == "no"
    assert one_way.disagreements == ("oneway: agency one-way, OSM two-way",)
    two_way = A.overlay(
        {"highway": "residential", "oneway": "yes"},
        way_facts(one_way=False, two_way_throughout=True, names_agree=True),
        length_m=200.0,
        rows={A.ROW_NO_FACILITY, A.ROW_ONE_WAY},
    )
    assert two_way.tags["oneway"] == "yes"
    assert two_way.precedence == ()


def test_a_separate_way_keeps_its_painted_lane_when_the_district_records_none() -> None:
    """Item 190's exception before row A: the facility OSM maps as its own way,
    and the way beside it, are left to OSM."""
    tags = {"highway": "primary", "cycleway:left": "separate", "cycleway:right": "lane"}
    assert A.overlay(tags, way_facts()).tags["cycleway:right"] == "lane"
    beside = A.overlay({"highway": "primary", "cycleway:right": "lane"}, way_facts(), True)
    assert beside.tags["cycleway:right"] == "lane"
    assert beside.precedence == ()


def test_carriageways_pair_only_when_their_traffic_runs_opposite_ways() -> None:
    """C2: two OSM one-way ways on one block are a pair only where their traffic
    runs opposite ways along it; `oneway=-1` turns a way's direction round."""
    block = facts(way="both")
    along = A.aggregate([("k", block, True)])
    against = A.aggregate([("k", block, False)])
    same = {1: {"oneway": "yes"}, 2: {"oneway": "yes"}}
    assert A.block_context({1: along, 2: along}, same)[1] == frozenset()
    # Drawn against the block but tagged -1: the same direction as way 1.
    reversed_tags = {1: {"oneway": "yes"}, 2: {"oneway": "-1"}}
    assert A.block_context({1: along, 2: against}, reversed_tags)[1] == frozenset()
    assert A.block_context({1: along, 2: against}, same)[1] == {1, 2}
    # A two-way way on the block is never paired.
    assert A.block_context({1: along, 2: against}, {1: {}, 2: {"oneway": "yes"}})[1] == frozenset()


def test_a_direction_one_block_records_keeps_osm_s_lane_on_its_own_side() -> None:
    """Review r2: the inbound direction has a lane on one block only; OSM's lane on
    the left (the inbound side of a way drawn outbound) stays, and nothing is
    put on the right from it."""
    both = facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}, way="both")
    outbound = facts(bike={"ob": A.BIKE_LANE}, way="both")
    way = A.aggregate([("a", both, True), ("b", outbound, True)])
    left = A.overlay({"highway": "tertiary", "cycleway:left": "lane"}, way).tags
    assert left["cycleway:both"] == "lane"
    right_only = A.overlay({"highway": "tertiary", "cycleway:right": "track"}, way).tags
    assert right_only["cycleway:right"] == "lane"
    assert "cycleway:left" not in right_only


def test_a_lane_each_block_records_the_way_s_direction_is_written() -> None:
    """The blocks label it differently (the way runs with one block and against
    the next), and the way's own direction has a lane on both."""
    first = facts(bike={"ob": A.BIKE_LANE}, way="both")
    second = facts(bike={"ib": A.BIKE_LANE}, way="both")
    way = A.aggregate([("a", first, True), ("b", second, False)])
    assert way.bike == {}
    assert (way.bike_forward, way.bike_backward) == (A.BIKE_LANE, A.BIKE_NONE)
    tags = A.overlay({"highway": "tertiary"}, way).tags
    assert tags["cycleway:right"] == "lane"


# -- review r3 ----------------------------------------------------------------------


@pytest.mark.parametrize("label", ["ib", "ob"])
@pytest.mark.parametrize("along", [True, False])
@pytest.mark.parametrize("oneway", ["yes", "-1"])
def test_a_flagged_lane_whose_traffic_direction_is_unknown_runs_against_osm_s(
    label, along, oneway
) -> None:
    """Review r3, should-fix 1: 58 of the 110 flagged blocks record no traffic
    direction. The flag says the lone lane is a contraflow lane, so it is put
    against OSM's one-way, whatever its label: Argonne Place NW 6054459, OSM
    `cycleway:left=opposite_lane`, was rewritten `cycleway:right=lane` (LTS 1 to 2)."""
    block = facts(bike={label: A.BIKE_LANE}, way="one", contraflow=True)
    osm_forward = oneway == "yes"
    way = A.aggregate([("argonne", block, along)], osm_forward=osm_forward)
    assert (way.bike_forward, way.bike_backward) == (
        (A.BIKE_NONE, A.BIKE_LANE) if osm_forward else (A.BIKE_LANE, A.BIKE_NONE)
    )
    tags = A.overlay(
        {"highway": "residential", "oneway": oneway, "cycleway:left": "opposite_lane"}, way
    ).tags
    assert tags["oneway"] == oneway
    assert tags["cycleway:left"] == "opposite_lane"
    assert tags["oneway:bicycle"] == "no"
    assert "cycleway:right" not in tags


def test_a_flagged_block_s_labels_stand_where_osm_has_no_one_way_or_two_lanes() -> None:
    """Only a lone lane on a one-way OSM way is placed by OSM's direction: with no
    OSM one-way there is nothing to place it by, and two lanes are one each way."""
    lone = facts(bike={"ib": A.BIKE_LANE}, way="one", contraflow=True)
    assert A.aggregate([("a", lone, True)]).bike_backward == A.BIKE_LANE
    assert A.aggregate([("a", lone, True)], osm_forward=None).bike_forward == A.BIKE_NONE
    both = facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_BUFFERED}, way="one", contraflow=True)
    way = A.aggregate([("a", both, True)], osm_forward=True)
    assert (way.bike_forward, way.bike_backward) == (A.BIKE_BUFFERED, A.BIKE_LANE)
    # A block whose direction DC records reads its own, not OSM's.
    known = facts(bike={"ob": A.BIKE_LANE}, way="one", oneway_with=False, contraflow=True)
    assert A.aggregate([("a", known, True)], osm_forward=True).bike_forward == A.BIKE_LANE
    # An unflagged block is not moved by OSM's direction, either way round.
    plain = facts(bike={"ib": A.BIKE_LANE}, way="one")
    assert A.aggregate([("a", plain, True)], osm_forward=True).bike_backward == A.BIKE_LANE
    ahead = facts(bike={"ob": A.BIKE_LANE}, way="one")
    assert A.aggregate([("a", ahead, True)], osm_forward=True).bike_forward == A.BIKE_LANE


def test_an_unflagged_lane_against_the_traffic_is_never_written_as_contraflow() -> None:
    """M6 of review r3: round 1 wrote a contraflow lane wherever the agency's street
    was one-way; only DC's flag makes one (review r2). An unflagged block with no
    recorded direction whose lane is labelled against the traffic writes none."""
    block = facts(bike={"ib": A.BIKE_LANE}, way="one")
    way = A.aggregate([("a", block, True)], osm_forward=True)
    assert way.one_way is True and way.contraflow is False
    assert way.bike_backward == A.BIKE_LANE
    tags = A.overlay({"highway": "residential", "oneway": "yes"}, way).tags
    assert "opposite_lane" not in tags.values()
    assert "oneway:bicycle" not in tags


def test_a_forward_direction_one_block_records_keeps_osm_s_lane_on_its_right() -> None:
    """M24 of review r3: the forward branch of `_keep_osm_where_blocks_differ`. One
    block records a lane in the way's direction and the next does not; OSM's
    lane on the right-hand side stays."""
    both = facts(bike={"ib": A.BIKE_LANE, "ob": A.BIKE_LANE}, way="both")
    inbound = facts(bike={"ib": A.BIKE_LANE}, way="both")
    way = A.aggregate([("a", both, True), ("b", inbound, True)])
    assert (way.bike_forward, way.bike_forward_most, way.bike_backward) == (
        A.BIKE_NONE,
        A.BIKE_LANE,
        A.BIKE_LANE,
    )
    tags = A.overlay({"highway": "tertiary", "cycleway:right": "lane"}, way).tags
    assert tags["cycleway:both"] == "lane"
    # OSM's lane on the left is the other direction's: nothing is put on the right.
    left_only = A.overlay({"highway": "tertiary", "cycleway:left": "track"}, way).tags
    assert left_only["cycleway:left"] == "lane"
    assert "cycleway:right" not in left_only


def test_brg_is_bridge() -> None:
    """M19 of review r3: DC's "FRANCIS SCOTT KEY BRG NW" is OSM's "Francis Scott
    Key Bridge", word for word."""
    assert A.name_tokens("FRANCIS SCOTT KEY BRG NW") == A.name_tokens("Francis Scott Key Bridge")
    assert A.names_agree("KEY BRG", "Key Bridge Approach Road") is True


def test_a_block_that_gives_only_a_total_gives_it_both_ways() -> None:
    """M30 of review r3: a block with no per-direction lanes gives its
    per-direction reading in both of the way's directions."""
    block = facts(lanes={"total": 4}, way="both")
    way = A.aggregate([("a", block, True)])
    assert (way.lanes_forward, way.lanes_backward) == (2, 2)
    one_way = A.aggregate([("a", facts(lanes={"total": 3}, way="one"), False)])
    assert (one_way.lanes_forward, one_way.lanes_backward) == (3, 3)


def _street(osm_id: int, tags: dict, length_m: float, reverse: bool = False) -> SimpleWay:
    """A way of `length_m` along an east-west block at 38.9 N."""
    east = length_m / (111_195.0 * 0.7782)
    line = [(-77.0, 38.9), (-77.0 + east, 38.9)]
    return SimpleWay(osm_id, tags, line[::-1] if reverse else line)


def test_overlay_road_facts_passes_the_pair_and_the_length() -> None:
    """M28 and M29 of review r3: `overlay_road_facts` decides C2 (a carriageway
    pair) and the stub exception from what it passes; dropping either made the
    742 pair ways and the stubs two-way with no test failing."""
    from pipeline.conflation import overlay_road_facts

    two_way = facts(way="both", lanes={"ib": 2, "ob": 2})
    named = {"highway": "secondary", "name": "K Street", "oneway": "yes"}
    ways = [_street(1, named, 200.0), _street(2, named, 200.0, reverse=True)]
    by_way = {
        1: A.aggregate([("k", two_way, True)], names=True),
        2: A.aggregate([("k", two_way, False)], names=True),
    }
    overlays = overlay_road_facts(ways, by_way)
    for way_id in (1, 2):
        assert overlays[way_id].tags["oneway"] == "yes"
        assert overlays[way_id].disagreements[0].endswith("kept (carriageway pair)")
    # A stub: one way alone on its block, at 30 m.
    stub = overlay_road_facts([_street(3, named, 30.0)], {3: by_way[1]})
    assert stub[3].tags["oneway"] == "yes"
    assert stub[3].disagreements[0].endswith("kept (junction stub)")
    street = overlay_road_facts([_street(4, named, 200.0)], {4: by_way[1]})
    assert street[4].tags["oneway"] == "no"
    assert street[4].precedence == (A.ROW_TWO_WAY,)


@pytest.mark.parametrize(
    ("length_m", "stub"), [(29.0, True), (30.0, True), (30.2, True), (30.6, False), (31.0, False)]
)
def test_the_stub_threshold_is_inclusive_to_the_metre(length_m, stub) -> None:
    """Review r3: New Jersey Avenue NW 1508260473, listed at 30 m (30.2 m
    measured), was overridden one-way as "not below" 30 m."""
    assert A.is_junction_stub(length_m) is stub
    one_way = A.overlay(
        {"highway": "tertiary", "oneway": "no"},
        way_facts(one_way=True, oneway_forward=True),
        length_m=length_m,
    )
    assert (one_way.tags["oneway"] == "no") is stub
    two_way = A.overlay(
        {"highway": "residential", "oneway": "yes"},
        way_facts(one_way=False, two_way_throughout=True, names_agree=True),
        length_m=length_m,
    )
    assert (two_way.tags["oneway"] == "yes") is stub
    assert A.is_junction_stub(None) is False


def test_a_one_way_side_lane_beside_the_two_way_main_road_stays_one_way() -> None:
    """Review r3: K Street NW 924793627 is the one-way north service lane of K
    Street, 12 m from the two-way centre, alone on its side of the block; C4 made
    it two-way with two lanes each way (LTS 1 to 3)."""
    from pipeline.conflation import overlay_road_facts

    block = facts(way="both", lanes={"ib": 2, "ob": 2}, speed_mph={"ob": 20})
    lane_tags = {"highway": "tertiary", "name": "K Street Northwest", "oneway": "yes", "lanes": "1"}
    centre_tags = {"highway": "trunk", "name": "K Street Northwest", "lanes": "4"}
    lane = A.aggregate([("k", block, True)], names=True)
    centre = A.aggregate([("k", block, True)], names=True)
    context = A.block_context({1: lane, 2: centre}, {1: lane_tags, 2: centre_tags})
    assert context.side_lane == {1}
    assert context.paired == frozenset()
    kept = A.overlay(lane_tags, lane, side_lane=True, length_m=112.0)
    assert kept.tags["oneway"] == "yes"
    assert kept.tags["lanes"] == "1"  # the block's lanes are the main road's
    assert kept.disagreements[1] == "lanes: a side lane beside a two-way carriageway, OSM kept"
    assert kept.disagreements[0].endswith("kept (side lane beside a two-way carriageway)")
    overlays = overlay_road_facts(
        [_street(1, lane_tags, 112.0), _street(2, centre_tags, 112.0)], {1: lane, 2: centre}
    )
    assert overlays[1].tags["oneway"] == "yes"
    assert overlays[1].precedence == ()


@pytest.mark.parametrize(
    "other",
    [
        {"highway": "trunk", "oneway": "yes"},  # a one-way carriageway is not the two-way main road
        {"highway": "service"},  # a driveway or an aisle along the block
        {"highway": "trunk_link"},  # a slip road
        # The same class: a road dividing partway along its block (808 of the
        # 855 ways a class-blind reading caught).
        {"highway": "tertiary"},
        {"highway": "residential"},  # a quieter class
        {"highway": "construction"},  # no class to rank
    ],
)
def test_only_a_busier_two_way_main_road_makes_a_one_way_a_side_lane(other) -> None:
    block = facts(way="both")
    along = A.aggregate([("k", block, True)])
    one_way = {"highway": "tertiary", "oneway": "yes"}
    assert A.block_context({1: along, 2: along}, {1: one_way, 2: other}).side_lane == frozenset()
    for main in ({"highway": "trunk"}, {"highway": "secondary"}):
        assert A.block_context({1: along, 2: along}, {1: one_way, 2: main}).side_lane == {1}
    # A service lane beside a residential street, too; an unranked one-way never.
    service = {"highway": "service", "oneway": "yes"}
    street = {"highway": "residential"}
    assert A.block_context({1: along, 2: along}, {1: service, 2: street}).side_lane == {1}
    odd = {"highway": "busway", "oneway": "yes"}
    assert A.block_context({1: along, 2: along}, {1: odd, 2: street}).side_lane == frozenset()
    # A two-way way is never a side lane, whatever its class.
    quiet = {"highway": "residential"}
    trunk = {"highway": "trunk"}
    assert A.block_context({1: along, 2: along}, {1: quiet, 2: trunk}).side_lane == frozenset()
    # The busiest main road on the block decides, whatever order the ways come in.
    three = {1: along, 2: along, 3: along}
    assert A.block_context(three, {1: one_way, 2: trunk, 3: street}).side_lane == {1}
    assert A.block_context(three, {1: one_way, 2: street, 3: trunk}).side_lane == {1}


def test_a_side_lane_on_one_of_its_blocks_is_a_side_lane() -> None:
    """G1 of the gate review: Lincoln Memorial Circle 1093448958 and 1103289386
    lie along several blocks, the busier two-way circle on some of them; a rule
    asking for a main road on every block made them two-way, LTS 2 to 3."""
    lane = {"highway": "service", "oneway": "yes"}
    circle = {"highway": "primary"}
    side = A.aggregate([("k", facts(way="both"), True), ("m", facts(way="both"), True)])
    main = A.aggregate([("k", facts(way="both"), True)])
    alone = A.aggregate([("m", facts(way="both"), True)])
    context = A.block_context({1: side, 2: main, 3: alone}, {1: lane, 2: circle, 3: lane})
    assert context.side_lane == {1}


def _metres(*points: tuple[float, float]) -> list[tuple[float, float]]:
    """A line from (east, north) offsets in metres from (-77.0, 38.9)."""
    return [(-77.0 + x / (111_195.0 * 0.7782), 38.9 + y / 111_195.0) for x, y in points]


def test_a_roundabout_is_not_a_two_way_main_road() -> None:
    """Gate review, should-fix 2: a roundabout is one-way without a `oneway` tag;
    the primary roundabouts 589905413 and 695842750 made Bryant Street NE and 13th
    Street NE side lanes."""
    along = A.aggregate([("k", facts(way="both"), True)])
    street = {"highway": "residential", "oneway": "yes"}
    for junction in ("roundabout", "circular"):
        roundabout = {"highway": "primary", "junction": junction}
        assert A._main_rank(roundabout) is None
        context = A.block_context({1: along, 2: along}, {1: street, 2: roundabout})
        assert context.side_lane == frozenset()
    # One mapped two-way in so many words is a two-way road.
    two_way = {"highway": "primary", "junction": "roundabout", "oneway": "no"}
    assert A.block_context({1: along, 2: along}, {1: street, 2: two_way}).side_lane == {1}


def test_a_one_way_carrying_the_main_road_on_from_its_end_is_not_a_side_lane() -> None:
    """Gate review, should-fix 2: Cedar Avenue 555136043 is a 26 m one-way from
    Cedar Street NW's end node into Maryland, not beside it; as a side lane it
    kept OSM's four lanes, LTS 2 to 3. A side lane runs alongside its main road:
    it shares no end node with it, or at least MIN_SIDE_LANE_BESIDE_M of it runs
    beside it short of its ends (Lincoln Memorial Circle's service ways leave the
    circle at its end node and run 27 m and 59 m beside it)."""
    along = A.aggregate([("k", facts(way="both"), True)])
    lane = {"highway": "residential", "oneway": "yes"}
    main = {"highway": "tertiary"}
    road = _metres((0, 0), (100, 0))
    cases = {
        "carries on from the end": (_metres((100, 0), (126, 0)), False),
        "turns off at the end": (_metres((100, 0), (100, 30)), False),
        "starts at the end and carries on": (_metres((126, 0), (100, 0)), False),
        "beside, touching neither end": (_metres((10, 12), (90, 12)), True),
        # Delaware Avenue NE's service ways: on the block, touching neither end.
        "touching neither end, past it": (_metres((110, 12), (140, 12)), True),
        "leaves the end and runs back beside it": (_metres((100, 0), (90, 10), (60, 10)), True),
        "leaves the end, too little beside it": (_metres((100, 0), (95, 8), (85, 8)), False),
        "beside it, but too far": (_metres((100, 0), (100, 30), (20, 30)), False),
    }
    for name, (line, side) in cases.items():
        context = A.block_context(
            {1: along, 2: along}, {1: lane, 2: main}, coordinates_by_way={1: line, 2: road}
        )
        assert (context.side_lane == {1}) is side, name
    # Ending on one main road of the block, it must run beside one of them.
    other = _metres((-50, 15), (200, 15))
    three = {1: along, 2: along, 3: along}
    three_tags = {1: lane, 2: main, 3: main}
    context = A.block_context(
        three, three_tags, coordinates_by_way={1: _metres((100, 0), (100, -30)), 2: road, 3: other}
    )
    assert context.side_lane == frozenset()
    context = A.block_context(
        three,
        three_tags,
        coordinates_by_way={1: _metres((100, 0), (100, 10), (40, 10)), 2: road, 3: other},
    )
    assert context.side_lane == {1}
    # Ending on a two-way street of its own class is a street carrying on, not
    # the busier main road's end.
    street = _metres((140, 12), (200, 12))
    context = A.block_context(
        three,
        {1: lane, 2: main, 3: {"highway": "residential"}},
        coordinates_by_way={1: _metres((110, 12), (140, 12)), 2: road, 3: street},
    )
    assert context.side_lane == {1}
    # Without the lines, the class alone decides, as before.
    assert A.block_context({1: along, 2: along}, {1: lane, 2: main}).side_lane == {1}
    assert A._beside_m(_metres((0, 5), (50, 5)), _metres((0, 0))) == 0.0


def test_the_rebuild_s_wiring_passes_the_lines() -> None:
    """`overlay_road_facts` hands `block_context` the ways' lines, so the end-on
    continuation is told apart where the rebuild reads it: Cedar Avenue takes
    the block's one lane each way, not OSM's four."""
    from pipeline.conflation import overlay_road_facts

    block = facts(way="both", lanes={"ib": 1, "ob": 1}, speed_mph={"ob": 25})
    cedar = A.aggregate([("k", block, True)], names=True)
    lane = {"highway": "residential", "name": "Cedar Avenue", "oneway": "yes", "lanes": "4"}
    main = {"highway": "tertiary", "name": "Cedar Street Northwest", "lanes": "4"}
    ways = [
        SimpleWay(1, lane, _metres((100, 0), (126, 0))),
        SimpleWay(2, main, _metres((0, 0), (100, 0))),
    ]
    overlays = overlay_road_facts(ways, {1: cedar, 2: cedar})
    assert overlays[1].tags["lanes"] == "1"
    beside = [SimpleWay(1, lane, _metres((10, 12), (90, 12))), ways[1]]
    assert overlay_road_facts(beside, {1: cedar, 2: cedar})[1].tags["lanes"] == "4"


def test_the_overlay_reads_a_roundabout_as_one_way() -> None:
    """Gate review: the overlay wrote two lanes each way onto the primary
    roundabout 589905413, which OSM maps without a `oneway` tag."""
    roundabout = {"highway": "primary", "junction": "roundabout", "lanes": "2"}
    two_way = way_facts(
        one_way=False,
        two_way_throughout=True,
        names_agree=True,
        lanes_per_direction=2,
        lanes_forward=2,
        lanes_backward=2,
        direction_known=True,
    )
    result = A.overlay(roundabout, two_way, length_m=80.0)
    assert result.tags["lanes"] == "2"
    assert "lanes:forward" not in result.tags and "lanes:backward" not in result.tags
    # OSM's implied one-way, said for the classifier, so the two lanes are read
    # as one direction's and not halved.
    assert result.tags["oneway"] == "yes"
    assert (
        classify(result.tags, jurisdiction="DC").tier
        == classify({**roundabout, "oneway": "yes"}, jurisdiction="DC").tier
    )
    assert result.sources["oneway"] == A.SOURCE_OSM
    assert result.disagreements[0] == "oneway: agency two-way, OSM one-way, kept (roundabout)"
    # A one-way record against the way's digitising does not reverse it.
    against = way_facts(one_way=True, oneway_forward=False)
    assert A.overlay(roundabout, against, length_m=80.0).tags["oneway"] == "yes"
    assert "oneway" not in roundabout
    # A roundabout OSM maps two-way in so many words is read as two-way.
    mapped = A.overlay({**roundabout, "oneway": "no"}, two_way, length_m=80.0)
    assert (mapped.tags["lanes:forward"], mapped.tags["lanes:backward"]) == ("2", "2")


def test_osm_forward_is_none_on_a_way_osm_has_two_way() -> None:
    """G5 of the gate review: a flagged contraflow block with no recorded
    direction on a way OSM has two-way keeps its lane's label (Pomeroy Road SE
    6051305); only an OSM one-way places it against the traffic."""
    for tags in ({"highway": "residential"}, {"oneway": "no"}, {"oneway": "reversible"}):
        assert A.osm_forward(tags) is None
    assert A.osm_forward({"oneway": "yes"}) is True
    assert A.osm_forward({"oneway": "-1"}) is False
    flagged = facts(way="one", contraflow=True, bike={"ob": A.BIKE_LANE})
    placed = {True: (A.BIKE_LANE, A.BIKE_NONE), False: (A.BIKE_NONE, A.BIKE_LANE)}
    for along, expected in placed.items():
        two_way = A.aggregate(
            [("p", flagged, along)], osm_forward=A.osm_forward({"highway": "residential"})
        )
        assert (two_way.bike_forward, two_way.bike_backward) == expected


def test_a_withheld_block_s_speed_is_not_applied_and_osm_s_stands() -> None:
    """OWNER-DECISIONS 197: DC's 20 mph on Canal Road NW and the Whitehurst Freeway
    is withheld; OSM's posted 35 mph stands, and the report says owner override."""
    canal = facts(speed_mph={"ob": 20}, lanes={"ib": 2, "ob": 2}, way="both")
    other = facts(speed_mph={"ob": 25}, way="both")
    held = {"canal": frozenset({"speed"})}
    way = A.aggregate([("canal", canal, True)], withheld=held)
    assert (way.speed_mph, way.speed_withheld_mph) == (None, 20)
    assert way.lanes_per_direction == 2  # only the speed is withheld
    result = A.overlay({"highway": "trunk", "maxspeed": "35 mph"}, way)
    assert result.tags["maxspeed"] == "35 mph"
    assert result.sources["maxspeed"] == A.SOURCE_OSM
    assert result.disagreements == (
        "maxspeed: agency 20 mph withheld by the owner, OSM kept (owner override)",
    )
    assert classify(result.tags, jurisdiction="DC").tier == Stress.LTS4
    # A block that is not withheld still speaks for the way.
    mixed = A.aggregate([("canal", canal, True), ("m", other, True)], withheld=held)
    assert (mixed.speed_mph, mixed.speed_withheld_mph) == (25, 20)
    assert A.aggregate([("canal", canal, True)]).speed_mph == 20


def _override_file(tmp_path, entries, name="x.json"):
    (tmp_path / name).write_text(json.dumps({"version": 1, "rows": [], "agency_blocks": entries}))


_ENTRY = {
    "blockkey": "k1",
    "routename": "CANAL RD NW",
    "withhold": ["speed"],
    "reason": "r",
    "evidence": "e",
}


def test_the_withheld_blocks_are_read_from_the_override_files(tmp_path) -> None:
    _override_file(tmp_path, [_ENTRY])
    (tmp_path / "rows-only.json").write_text(json.dumps({"version": 1, "rows": []}))
    assert A.withheld_blocks(tmp_path) == {
        "k1": A.WithheldBlock("CANAL RD NW", frozenset({"speed"}))
    }
    assert A.withheld_blocks(tmp_path / "nothing-here") == {}


def test_one_block_named_two_ways_is_refused(tmp_path) -> None:
    _override_file(tmp_path, [_ENTRY], name="a.json")
    _override_file(tmp_path, [{**_ENTRY, "routename": " canal  rd nw"}], name="b.json")
    assert A.withheld_blocks(tmp_path)["k1"].routename == " canal  rd nw"
    _override_file(tmp_path, [{**_ENTRY, "routename": "M ST NW"}], name="b.json")
    with pytest.raises(A.WithheldBlockRefused, match="named 'M ST NW' here"):
        A.withheld_blocks(tmp_path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"blockkey": ""}, "blockkey must be"),
        ({"blockkey": " "}, "blockkey must be"),
        ({"blockkey": 4633425}, "blockkey must be"),
        ({"block": "dc-4633425-0", "blockkey": None}, "blockkey must be"),
        ({"routename": ""}, "routename is required"),
        ({"routename": None}, "routename is required"),
        ({"withhold": []}, "withhold must"),
        ({"withhold": ["lanes"]}, "withhold must"),
        ({"withhold": "speed"}, "withhold must"),
        ({"reason": " "}, "reason is required"),
        ({"evidence": None}, "evidence is required"),
    ],
)
def test_a_malformed_withheld_block_is_refused(tmp_path, change, message) -> None:
    _override_file(tmp_path, [{**_ENTRY, **change}])
    with pytest.raises(A.WithheldBlockRefused, match=message):
        A.withheld_blocks(tmp_path)
    (tmp_path / "x.json").write_text(json.dumps({"version": 1, "agency_blocks": {}}))
    with pytest.raises(A.WithheldBlockRefused, match="must be a list"):
        A.withheld_blocks(tmp_path)


def test_the_owner_s_canal_road_and_whitehurst_file() -> None:
    """OWNER-DECISIONS 197, quoted verbatim; both blocks' speed withheld, nothing
    else; nothing for the loader to load."""
    path = A.OVERRIDES_DIR / "2026-10-02-owner-canal-whitehurst.json"
    document = json.loads(path.read_text())
    assert document["version"] == 1 and document["rows"] == []
    assert (
        "DC records of 20 mph on Canal Rd NW (block dc-4633425-0) and the Whitehurst Fwy "
        '(dc-4636053-0), owner 2026-10-02: "Override: keep LTS 4 (Recommended)". A stress '
        "override holds them at the OSM speeds and LTS 4, and they stay listed in the "
        "discrepancy report."
    ) in document["annotations"]
    held = A.withheld_blocks()
    # Gate review, should-fix 1: named by DC's BLOCKKEY, not the OBJECTID the
    # installed ids are built from.
    assert held == {
        "4f9821f03241db278696e8732dc5c2a7": A.WithheldBlock("CANAL RD NW", frozenset({"speed"})),
        "c90df9cc9a2d75261e727d355a32dd3a": A.WithheldBlock(
            "WHITEHURST FWY NW", frozenset({"speed"})
        ),
    }
    assert "block id is stable" not in document["annotations"]
    assert "OBJECTID" in document["annotations"] and "BLOCKKEY" in document["annotations"]
    for entry in document["agency_blocks"]:
        assert '"Override: keep LTS 4 (Recommended)"' in entry["reason"]


def test_the_withheld_blocks_are_found_by_the_layer_s_key() -> None:
    """Gate review, should-fix 1: the installed id is built from DC's OBJECTID, the
    ArcGIS row number; the owner's correction names the block by BLOCKKEY, so a
    republished layer that renumbers its rows still finds it, and a block whose
    street is another, or that is not installed, withholds nothing and is named
    for the rebuild's warning."""
    held = {
        "k-canal": A.WithheldBlock("CANAL RD NW", frozenset({"speed"})),
        "k-gone": A.WithheldBlock("WHITEHURST FWY NW", frozenset({"speed"})),
        "k-moved": A.WithheldBlock("M ST NW", frozenset({"speed"})),
    }
    canal = A.RoadFacts(agency=A.DC_AGENCY, name="Canal Rd  NW", block_key="k-canal")
    other = A.RoadFacts(agency=A.DC_AGENCY, name="K ST NW", block_key="k-moved")
    keyless = A.RoadFacts(agency=A.DC_AGENCY, name="CANAL RD NW")
    found = A.resolve_withheld(
        held,
        [("dc-9999999-0", canal), ("dc-9999999-1", canal), ("dc-2-0", other), ("dc-3-0", keyless)],
    )
    assert found.by_block == {
        "dc-9999999-0": frozenset({"speed"}),
        "dc-9999999-1": frozenset({"speed"}),
    }
    assert found.unmatched == (
        "block k-gone (WHITEHURST FWY NW) is not among the installed agency street blocks",
        "block k-moved is K ST NW in the installed blocks, not M ST NW",
    )
    assert A.resolve_withheld({}, [("dc-1-0", canal)]) == A.WithheldResolution({}, ())


def test_the_dc_parser_keeps_the_block_s_key() -> None:
    facts = A.parse_dc_roadway_block({"ROUTENAME": "CANAL RD NW", "BLOCKKEY": " 4f98 "})
    assert facts.block_key == "4f98"
    assert A.RoadFacts.from_json(facts.to_json()).block_key == "4f98"
    assert A.parse_dc_roadway_block({"ROUTENAME": "CANAL RD NW"}).block_key is None
    assert A.parse_dc_roadway_block({"BLOCKKEY": ""}).block_key is None
