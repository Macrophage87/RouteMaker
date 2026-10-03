"""Conflating an agency's street blocks onto OSM ways (pipeline.conflation.conflate_blocks).

`conflate` attaches one count to one way and lets it be claimed once. A block
layer is a different problem: a posted speed describes every way along the block,
and OSM ways and blocks do not break in the same places. Geometry is in metres
from an origin so each case says what it means.
"""

from __future__ import annotations

import math
import random
from dataclasses import replace

import pytest

from pipeline.conflation import (
    MAX_SEPARATION_M,
    MIN_BLOCK_COVERAGE,
    MIN_BLOCK_PROBES,
    Match,
    RoadFeature,
    _probes_with_headings,
    block_count,
    conflate_blocks,
    road_facts_by_way,
)
from routemaker.agency_roads import DC_AGENCY, RoadFacts

ORIGIN_LON, ORIGIN_LAT = -77.02, 38.90
M_PER_DEG = 111_195.0


def pt(east: float, north: float) -> tuple[float, float]:
    return (
        ORIGIN_LON + east / (M_PER_DEG * math.cos(math.radians(ORIGIN_LAT))),
        ORIGIN_LAT + north / M_PER_DEG,
    )


def line(*points: tuple[float, float]) -> list[tuple[float, float]]:
    return [pt(*p) for p in points]


def block(
    block_id: str, coords, name: str | None = None, functional_class: str | None = None
) -> RoadFeature:
    return RoadFeature(
        block_id,
        coords,
        RoadFacts(agency=DC_AGENCY, name=name, functional_class=functional_class),
    )


def way(way_id: int, coords, trail: bool = False):
    return (way_id, coords, trail)


# Three blocks of 200 m end to end along an east-west street, and a way along all of it.
BLOCK_A = block("a", line((0, 0), (200, 0)), "K ST NW")
BLOCK_B = block("b", line((200, 0), (400, 0)), "K ST NW")
BLOCK_C = block("c", line((400, 0), (600, 0)), "K ST NW")
STREET = line((0, 0), (600, 0))


def test_a_way_along_one_block_takes_it_whole() -> None:
    result = conflate_blocks([way(1, line((0, 0), (200, 0)))], [BLOCK_A, BLOCK_B], {1: "K Street"})
    (share,) = result.matched[1]
    assert share.feature_id == "a"
    assert share.share == pytest.approx(1.0)
    assert result.coverage[1] == pytest.approx(1.0)
    assert result.unmatched_features == ["b"]


def test_a_way_along_several_blocks_takes_each_of_them() -> None:
    """The first version asked what fraction of the way lay near one block and
    found a third, and matched nothing along a road OSM draws as one way."""
    result = conflate_blocks([way(1, STREET)], [BLOCK_A, BLOCK_B, BLOCK_C])
    assert {s.feature_id for s in result.matched[1]} == {"a", "b", "c"}
    assert result.coverage[1] == pytest.approx(1.0, abs=0.05)
    assert result.unmatched_features == []
    assert sum(s.share for s in result.matched[1]) == pytest.approx(1.0, abs=0.05)


def test_a_cross_street_is_not_the_block_the_way_lies_along() -> None:
    cross = block("x", line((100, -100), (100, 100)), "9TH ST NW")
    result = conflate_blocks([way(1, line((0, 0), (200, 0)))], [BLOCK_A, cross])
    assert [s.feature_id for s in result.matched[1]] == ["a"]
    assert "x" in result.unmatched_features


def test_a_way_that_bends_is_matched_along_its_bends() -> None:
    """A single bearing for a long way that turns a corner matches neither leg;
    the heading is taken where the probe is."""
    corner = line((0, 0), (200, 0), (200, 200))
    blocks = [
        block("east", line((0, 0), (200, 0)), "K ST NW"),
        block("north", line((200, 0), (200, 200)), "K ST NW"),
    ]
    result = conflate_blocks([way(1, corner)], blocks, {1: "K Street Northwest"})
    assert {s.feature_id for s in result.matched[1]} == {"east", "north"}


def test_both_carriageways_of_a_divided_road_take_the_one_block() -> None:
    """A block is not claimed: a posted speed is both carriageways' speed."""
    centre = block("c", line((0, 0), (200, 0)), "CONNECTICUT AVE NW")
    north_way = way(1, line((0, 8), (200, 8)))
    south_way = way(2, line((200, -8), (0, -8)))
    result = conflate_blocks(
        [north_way, south_way], [centre], {1: "Connecticut Avenue", 2: "Connecticut Avenue"}
    )
    assert [s.feature_id for s in result.matched[1]] == ["c"]
    assert [s.feature_id for s in result.matched[2]] == ["c"]


def test_a_way_running_against_the_block_s_direction_still_lies_along_it() -> None:
    result = conflate_blocks([way(1, line((200, 0), (0, 0)))], [BLOCK_A])
    assert [s.feature_id for s in result.matched[1]] == ["a"]


def test_a_service_road_beside_a_street_takes_its_own_block() -> None:
    """Ten metres apart is inside the separation, so each probe goes to the
    nearer block rather than the first block that is near."""
    main = block("main", line((0, 0), (200, 0)), "K ST NW")
    alley = block("alley", line((0, 10), (200, 10)), "ALLEY")
    result = conflate_blocks(
        [way(1, line((0, 0), (200, 0))), way(2, line((0, 10), (200, 10)))],
        [main, alley],
        {1: "K Street Northwest", 2: None},
    )
    assert [s.feature_id for s in result.matched[1]] == ["main"]
    assert [s.feature_id for s in result.matched[2]] == ["alley"]


def test_a_street_name_that_agrees_outranks_a_nearer_block_that_does_not() -> None:
    near_wrong = block("wrong", line((0, 2), (200, 2)), "L ST NW")
    far_right = block("right", line((0, 9), (200, 9)), "K ST NW")
    result = conflate_blocks(
        [way(1, line((0, 0), (200, 0)))], [near_wrong, far_right], {1: "K Street Northwest"}
    )
    (share,) = result.matched[1]
    assert share.feature_id == "right"
    assert share.names_agree is True


def test_a_block_with_a_different_name_is_still_matched_when_it_is_the_only_one() -> None:
    """Names rank candidates; they do not veto the only block there is, because
    OSM and a city name the same road differently often enough."""
    odd = block("odd", line((0, 1), (200, 1)), "ROCK CREEK PKWY")
    result = conflate_blocks([way(1, line((0, 0), (200, 0)))], [odd], {1: "Beach Drive"})
    (share,) = result.matched[1]
    assert (share.feature_id, share.names_agree) == ("odd", False)


def test_an_unnamed_way_matches_on_geometry_and_names_nothing() -> None:
    result = conflate_blocks([way(1, line((0, 0), (200, 0)))], [BLOCK_A], {1: None})
    assert result.matched[1][0].names_agree is None


def test_a_trail_is_never_matched_to_a_roadway_block() -> None:
    """The Mount Vernon Trail runs beside the parkway and would take its speed."""
    result = conflate_blocks([way(1, line((0, 5), (200, 5)), trail=True)], [BLOCK_A])
    assert result.matched == {}
    assert result.unmatched_features == ["a"]


def test_a_way_beyond_the_separation_is_not_along_the_block() -> None:
    far = line((0, MAX_SEPARATION_M + 5), (200, MAX_SEPARATION_M + 5))
    assert conflate_blocks([way(1, far)], [BLOCK_A]).matched == {}
    near = line((0, MAX_SEPARATION_M - 5), (200, MAX_SEPARATION_M - 5))
    assert 1 in conflate_blocks([way(1, near)], [BLOCK_A]).matched


def test_a_block_that_only_touches_the_end_of_a_way_is_not_one_of_its_blocks() -> None:
    """A collinear block starting a few metres inside the way's end shares a
    probe or two with it; the way lies along the block it covers."""
    result = conflate_blocks(
        [way(1, line((0, 0), (200, 0)))],
        [
            block("whole", line((-5, 0), (205, 0)), "K ST NW"),
            block("next", line((195, 0), (400, 0))),
        ],
    )
    assert [s.feature_id for s in result.matched[1]] == ["whole"]


def test_a_way_the_blocks_do_not_cover_is_unmatched() -> None:
    """Half of it must be covered. A way of 200 m beside 60 m of block is not
    described by it."""
    short = block("short", line((0, 0), (60, 0)))
    assert conflate_blocks([way(1, line((0, 0), (200, 0)))], [short]).matched == {}
    assert MIN_BLOCK_COVERAGE == 0.5
    longer = block("longer", line((0, 0), (120, 0)))
    assert 1 in conflate_blocks([way(1, line((0, 0), (200, 0)))], [longer]).matched


def test_a_short_way_needs_both_its_probes_on_the_block() -> None:
    result = conflate_blocks([way(1, line((10, 0), (22, 0)))], [BLOCK_A])
    assert [s.feature_id for s in result.matched[1]] == ["a"]
    assert MIN_BLOCK_PROBES == 2


def test_a_degenerate_way_or_block_is_ignored() -> None:
    degenerate = RoadFeature("d", [pt(0, 0)], RoadFacts(agency=DC_AGENCY))
    result = conflate_blocks([way(1, [pt(0, 0)])], [degenerate, BLOCK_A])
    assert result.matched == {}


def test_no_features_matches_nothing() -> None:
    result = conflate_blocks([way(1, STREET)], [])
    assert result.matched == {} and result.unmatched_features == []


def test_the_result_does_not_depend_on_the_order_of_the_input() -> None:
    ways = [
        way(1, STREET),
        way(2, line((0, 6), (600, 6))),
        way(3, line((300, -200), (300, 200))),
    ]
    blocks = [
        BLOCK_A,
        BLOCK_B,
        BLOCK_C,
        block("d", line((0, 6), (600, 6)), "ALLEY"),
        block("e", line((300, -200), (300, 200)), "9TH ST NW"),
    ]
    names = {1: "K Street Northwest", 2: None, 3: "9th Street Northwest"}
    expected = conflate_blocks(ways, blocks, names)
    for seed in range(5):
        shuffled_ways, shuffled_blocks = ways[:], blocks[:]
        random.Random(seed).shuffle(shuffled_ways)
        random.Random(seed + 10).shuffle(shuffled_blocks)
        got = conflate_blocks(shuffled_ways, shuffled_blocks, names)
        assert got.matched == expected.matched
        assert sorted(got.unmatched_features) == sorted(expected.unmatched_features)


# -- the probes' headings -----------------------------------------------------------


def test_probes_are_spaced_and_carry_the_heading_of_their_segment() -> None:
    probes, headings = _probes_with_headings(line((0, 0), (100, 0), (100, 100)), 20.0)
    assert len(probes) == len(headings)
    assert headings[0] == pytest.approx(90.0, abs=0.5)  # east
    assert headings[-1] == pytest.approx(0.0, abs=0.5)  # north
    assert len(probes) >= 10


def test_a_tiny_segment_takes_its_heading_from_its_neighbours() -> None:
    """A one-metre segment in a curve points anywhere."""
    coords = line((0, 0), (50, 0), (50.5, 1.0), (100, 1.0))
    _probes, headings = _probes_with_headings(coords, 20.0)
    assert all(abs(h - 90.0) < 20.0 for h in headings), headings


# -- ways that must be named ----------------------------------------------------------


def test_a_service_road_beside_a_street_does_not_take_its_block() -> None:
    """An unnamed service way - a parking aisle, a driveway - beside a street is
    not that street. Measured on Baltimore: 118 miles of such ways took 25 mph."""
    street = block("street", line((0, 0), (200, 0)), "K ST NW")
    aisle = way(1, line((0, 8), (200, 8)))
    assert 1 in conflate_blocks([aisle], [street]).matched
    assert conflate_blocks([aisle], [street], {1: None}, name_required={1}).matched == {}


def test_a_named_service_road_still_takes_the_block_that_names_it() -> None:
    street = block("wharf", line((0, 0), (200, 0)), "WHARF ST SW")
    result = conflate_blocks(
        [way(1, line((0, 3), (200, 3)))], [street], {1: "Wharf Street Southwest"}, name_required={1}
    )
    assert [s.feature_id for s in result.matched[1]] == ["wharf"]


def test_a_service_road_with_a_different_name_does_not_take_the_block() -> None:
    street = block("k", line((0, 0), (200, 0)), "K ST NW")
    result = conflate_blocks(
        [way(1, line((0, 3), (200, 3)))], [street], {1: "Parking Lot Road"}, name_required={1}
    )
    assert result.matched == {}


def test_a_way_not_in_the_required_set_is_unaffected() -> None:
    street = block("k", line((0, 0), (200, 0)), "K ST NW")
    result = conflate_blocks(
        [way(1, line((0, 3), (200, 3)))], [street], {1: None}, name_required={2}
    )
    assert 1 in result.matched


def test_a_short_connector_lying_along_a_matched_way_is_not_reported_unmatched() -> None:
    """A twelve-metre block between two long ones cannot win two probes of the
    way, but the way it lies along is matched, so it is not the agency's mileage
    that OSM lacks."""
    left = block("left", line((0, 0), (300, 0)), "K ST NW")
    stub = block("stub", line((300, 0), (312, 0)), "K ST NW")
    right = block("right", line((312, 0), (600, 0)), "K ST NW")
    result = conflate_blocks([way(1, line((0, 0), (600, 0)))], [left, stub, right])
    assert result.unmatched_features == []
    assert {s.feature_id for s in result.matched[1]} == {"left", "right"}


# -- the name veto -------------------------------------------------------------------


def test_a_frontage_road_is_not_the_arterial_beside_it() -> None:
    """36th Place NE, twelve metres from New York Avenue with its heading, took the
    avenue's speed, lanes and count. A different street's name vetoes the block."""
    avenue = block("avenue", line((0, 0), (200, 0)), "NEW YORK AVE NE")
    frontage = way(1, line((0, 12), (200, 12)))
    assert conflate_blocks([frontage], [avenue], {1: "36th Place Northeast"}).matched != {}
    vetoed = conflate_blocks([frontage], [avenue], {1: "36th Place Northeast"}, name_free=set())
    assert vetoed.matched == {}
    assert vetoed.unmatched_features == ["avenue"]


def test_the_veto_leaves_the_block_whose_name_agrees() -> None:
    avenue = block("avenue", line((0, 0), (200, 0)), "NEW YORK AVE NE")
    frontage = block("frontage", line((0, 12), (200, 12)), "36TH PL NE")
    result = conflate_blocks(
        [way(1, line((0, 12), (200, 12)))],
        [avenue, frontage],
        {1: "36th Place Northeast"},
        name_free=set(),
    )
    assert [s.feature_id for s in result.matched[1]] == ["frontage"]


def test_the_veto_does_not_reach_a_way_with_no_name_or_a_block_with_none() -> None:
    street = block("nameless", line((0, 0), (200, 0)), None)
    assert (
        1
        in conflate_blocks(
            [way(1, line((0, 3), (200, 3)))], [street], {1: "K Street"}, name_free=set()
        ).matched
    )
    named = block("k", line((0, 0), (200, 0)), "K ST NW")
    assert (
        1
        in conflate_blocks(
            [way(1, line((0, 3), (200, 3)))], [named], {1: None}, name_free=set()
        ).matched
    )


def test_a_name_free_way_keeps_a_mismatched_name() -> None:
    """An interstate is OSM's 'Anacostia Freeway' and DC's 'INTERSTATE 295'."""
    interstate = block("i295", line((0, 0), (200, 0)), "INTERSTATE 295 I BN", "1")
    result = conflate_blocks(
        [way(1, line((0, 8), (200, 8)))], [interstate], {1: "Anacostia Freeway"}, name_free={1}
    )
    assert result.matched[1][0].names_agree is False


def test_a_block_crossing_the_way_beyond_the_block_it_lies_along_is_not_one_of_its_blocks() -> None:
    """Where the way runs past the end of its block, a cross street is the nearest
    block for the probes beside it. It is not a block the way lies along: the
    heading says it crosses."""
    along = block("along", line((0, 0), (100, 0)), "K ST NW")
    cross = block("cross", line((150, -100), (150, 100)), "9TH ST NW")
    result = conflate_blocks([way(1, line((0, 0), (200, 0)))], [along, cross])
    assert [s.feature_id for s in result.matched[1]] == ["along"]
    assert "cross" in result.unmatched_features


def test_a_way_s_blocks_are_listed_most_covering_first() -> None:
    short = block("z-short", line((200, 0), (300, 0)), "K ST NW")
    long = block("a-long", line((0, 0), (200, 0)), "K ST NW")
    result = conflate_blocks([way(1, line((0, 0), (300, 0)))], [short, long])
    assert [s.feature_id for s in result.matched[1]] == ["a-long", "z-short"]
    shares = [s.share for s in result.matched[1]]
    assert shares == sorted(shares, reverse=True)


def test_a_long_block_beside_a_short_way_is_matched_by_it() -> None:
    """The way is forty metres of a four-hundred-metre block: the block lies along
    the way, though the way is a tenth of the block."""
    result = conflate_blocks(
        [way(1, line((100, 0), (140, 0)))], [block("long", line((0, 0), (400, 0)), "K ST NW")]
    )
    assert [s.feature_id for s in result.matched[1]] == ["long"]
    assert result.unmatched_features == []


def test_a_block_that_only_touches_the_end_of_a_matched_way_is_unmatched() -> None:
    """It wins a probe at the way's end, and nothing of it lies along the way."""
    along = block("along", line((0, 0), (190, 0)), "K ST NW")
    beyond = block("beyond", line((190, 0), (600, 0)), "K ST NW")
    result = conflate_blocks([way(1, line((0, 0), (200, 0)))], [along, beyond])
    assert [s.feature_id for s in result.matched[1]] == ["along"]
    assert result.unmatched_features == ["beyond"]


# -- review r1 ------------------------------------------------------------------------


def test_a_share_says_whether_the_way_runs_with_the_block_s_line() -> None:
    """DC's outbound is the block's digitising direction (review r1), so the
    matcher records which way along the block each way is drawn."""
    with_line = conflate_blocks([way(1, line((0, 3), (200, 3)))], [BLOCK_A], {})
    against = conflate_blocks([way(1, line((200, 3), (0, 3)))], [BLOCK_A], {})
    assert with_line.matched[1][0].along is True
    assert against.matched[1][0].along is False


def test_a_block_naming_another_street_is_dropped_where_one_that_agrees_is_kept() -> None:
    """A way free of the veto, or one whose cross street won a few probes, keeps
    only the blocks of its own name once one of them agrees (review r1: North
    Capitol Street took Clermont Drive's block beside its own)."""
    own = block("own", line((0, 0), (120, 0)), "NORTH CAPITOL ST")
    other = block("other", line((120, 2), (200, 2)), "CLERMONT DR NE")
    result = conflate_blocks(
        [way(1, line((0, 3), (200, 3)))], [own, other], {1: "North Capitol Street"}, name_free={1}
    )
    assert [share.feature_id for share in result.matched[1]] == ["own"]
    assert all(share.names_agree is True for share in result.matched[1])


def test_with_no_name_free_set_nothing_is_vetoed() -> None:
    avenue = block("avenue", line((0, 0), (200, 0)), "NEW YORK AVE NE")
    result = conflate_blocks([way(1, line((0, 12), (200, 12)))], [avenue], {1: "36th Place"})
    assert 1 in result.matched


class _Way:
    def __init__(self, osm_id: int, tags: dict, coordinates) -> None:
        self.osm_id, self.tags, self.coordinates = osm_id, tags, coordinates
        self.name = tags.get("name")


def _facts_for(*ways: _Way, blocks) -> dict:
    entries = [(w.osm_id, w.coordinates, False) for w in ways]
    facts, _ = road_facts_by_way(ways, entries, blocks)
    return facts


def test_the_rebuild_s_matching_rules_are_wired_by_class() -> None:
    """`road_facts_by_way` is the one place the rules meet the classes: an
    unnamed service way does not take the street beside it, a residential or a
    primary way is vetoed by a block naming another street, and a motorway is
    not (review r1: primary and secondary ways were free of the veto)."""
    avenue = RoadFeature(
        "avenue",
        line((0, 0), (200, 0)),
        RoadFacts(agency=DC_AGENCY, name="NEW YORK AVE NE", functional_class="3"),
    )
    interstate = RoadFeature(
        "i295",
        line((0, 0), (200, 0)),
        RoadFacts(agency=DC_AGENCY, name="INTERSTATE 295", functional_class="1"),
    )
    beside = line((0, 8), (200, 8))
    assert _facts_for(_Way(1, {"highway": "service"}, beside), blocks=[avenue]) == {}
    for highway in ("residential", "primary", "secondary"):
        named = _Way(2, {"highway": highway, "name": "36th Place Northeast"}, beside)
        assert _facts_for(named, blocks=[avenue]) == {}, highway
    freeway = _Way(3, {"highway": "motorway", "name": "Anacostia Freeway"}, beside)
    assert 3 in _facts_for(freeway, blocks=[interstate])
    # Review r2: a freeway-class way takes a differently named block only where
    # the block is itself a freeway.
    assert _facts_for(freeway, blocks=[avenue]) == {}
    # A named service way still takes its own street's block.
    own = _Way(4, {"highway": "service", "name": "New York Avenue Northeast"}, beside)
    assert 4 in _facts_for(own, blocks=[avenue])


def test_the_way_s_direction_reaches_its_facts() -> None:
    """A one-way carriageway drawn against a block takes the block's inbound lanes."""
    block_facts = RoadFacts(agency=DC_AGENCY, name="K ST NW", lanes={"ib": 3, "ob": 1})
    street = RoadFeature("k", line((0, 0), (200, 0)), block_facts)
    eastbound = _Way(1, {"highway": "primary", "name": "K Street"}, line((0, 3), (200, 3)))
    westbound = _Way(2, {"highway": "primary", "name": "K Street"}, line((200, -3), (0, -3)))
    facts = _facts_for(eastbound, westbound, blocks=[street])
    assert (facts[1].lanes_forward, facts[1].lanes_backward) == (1, 3)
    assert (facts[2].lanes_forward, facts[2].lanes_backward) == (3, 1)


def _match_result(way_id: int, block_id: str):
    return conflate_blocks(
        [way(way_id, line((0, 3), (200, 3)))], [block(block_id, line((0, 0), (200, 0)))], {}
    )


def test_a_block_s_count_fills_only_where_no_count_reached_the_way_and_never_a_ramp() -> None:
    from routemaker.agency_roads import aggregate

    result = _match_result(1, "a")
    facts = aggregate([("a", RoadFacts(agency=DC_AGENCY, aadt=9000, aadt_year=2020))])
    filled = block_count(1, {"highway": "primary"}, facts, result, counted=set())
    assert isinstance(filled, Match)
    assert (filled.aadt, filled.year, filled.agency, filled.source) == (
        9000,
        2020,
        DC_AGENCY,
        "inventory",
    )
    assert block_count(1, {"highway": "primary"}, facts, result, counted={1}) is None
    assert block_count(1, {"highway": "primary_link"}, facts, result, counted=set()) is None
    no_count = aggregate([("a", RoadFacts(agency=DC_AGENCY))])
    assert block_count(1, {"highway": "primary"}, no_count, result, counted=set()) is None


# -- review r2 ------------------------------------------------------------------------


@pytest.mark.parametrize("functional_class", [None, "3", "4", "7", "MART", "PART", "LOC"])
def test_a_trunk_road_does_not_take_the_arterial_it_runs_into(functional_class) -> None:
    """Canal Road NW (a trunk) took M Street NW's block and went from 35 to 20 mph."""
    m_street = block("m", line((0, 0), (200, 0)), "M ST NW", functional_class)
    result = conflate_blocks(
        [way(1, line((0, 4), (200, 4)))], [m_street], {1: "Canal Road Northwest"}, name_free={1}
    )
    assert result.matched == {}


@pytest.mark.parametrize("functional_class", ["1", "2", "INT", "FWY"])
def test_a_freeway_block_still_matches_a_differently_named_freeway(functional_class) -> None:
    freeway = block("f", line((0, 0), (200, 0)), "INTERSTATE 395", functional_class)
    result = conflate_blocks(
        [way(1, line((0, 4), (200, 4)))], [freeway], {1: "3rd Street Tunnel"}, name_free={1}
    )
    assert result.matched[1][0].feature_id == "f"


def test_a_name_that_agrees_needs_no_freeway_class() -> None:
    bridge = block("key", line((0, 0), (200, 0)), "FRANCIS SCOTT KEY BRG NW", "3")
    result = conflate_blocks(
        [way(1, line((0, 4), (200, 4)))], [bridge], {1: "Francis Scott Key Bridge"}, name_free={1}
    )
    assert result.matched[1][0].names_agree is True


def test_a_layer_that_classes_no_road_keeps_name_free_matching() -> None:
    """Montgomery's stress records and a city's facility lines carry no road class:
    a freeway still takes a differently named one, as before review r2."""
    record = RoadFeature(
        "moco", line((0, 0), (200, 0)), RoadFacts(agency="montgomery-lts", name="RT 29")
    )
    result = conflate_blocks(
        [way(1, line((0, 4), (200, 4)))], [record], {1: "Columbia Pike"}, name_free={1}
    )
    assert result.matched[1][0].feature_id == "moco"


# -- review r3 ------------------------------------------------------------------------


def test_a_proposed_road_takes_no_block() -> None:
    """Review r3: `highway=proposed` ways (17th Street NE 1075230957, I Street NE
    1248940124) took blocks; a road on a plan is not the street."""
    street = block("k", line((0, 0), (200, 0)), "K ST NW")
    along = line((0, 3), (200, 3))
    proposed = _Way(1, {"highway": "proposed", "proposed": "residential", "name": "K St"}, along)
    built = _Way(2, {"highway": "residential", "name": "K St"}, along)
    facts = _facts_for(proposed, built, blocks=[street])
    assert set(facts) == {2}


@pytest.mark.parametrize(("oneway", "lane"), [("yes", "backward"), ("-1", "forward")])
def test_the_way_s_osm_direction_places_a_flagged_lane(oneway, lane) -> None:
    """Review r3, should-fix 1, through the rebuild's wiring: a flagged block with
    no recorded direction puts its lone lane against OSM's one-way."""
    flagged = RoadFeature(
        "t",
        line((0, 0), (200, 0)),
        RoadFacts(agency=DC_AGENCY, name="T ST NW", way="one", bike={"ob": 1}, contraflow=True),
    )
    t_street = _Way(
        1, {"highway": "residential", "name": "T Street", "oneway": oneway}, line((0, 3), (200, 3))
    )
    facts = _facts_for(t_street, blocks=[flagged])[1]
    assert (facts.bike_forward, facts.bike_backward) == ((0, 1) if lane == "backward" else (1, 0))


def test_the_owner_s_withheld_blocks_are_read_by_default() -> None:
    """OWNER-DECISIONS 197: the matcher reads the checked-in `agency_blocks`
    (fixtures/overrides/2026-10-02-owner-canal-whitehurst.json) unless told
    otherwise, so the rebuild and the reports withhold the same speeds."""
    # By DC's BLOCKKEY, whatever row number the installed id was built from
    # (gate review, should-fix 1).
    canal = RoadFeature(
        "dc-1234567-0",
        line((0, 0), (200, 0)),
        RoadFacts(
            agency=DC_AGENCY,
            name="CANAL RD NW",
            speed_mph={"ob": 20},
            way="both",
            block_key="4f9821f03241db278696e8732dc5c2a7",
        ),
    )
    road = _Way(1, {"highway": "trunk", "name": "Canal Road Northwest"}, line((0, 3), (200, 3)))
    entries = [(1, road.coordinates, False)]
    held, _ = road_facts_by_way([road], entries, [canal])
    assert (held[1].speed_mph, held[1].speed_withheld_mph) == (None, 20)
    applied, _ = road_facts_by_way([road], entries, [canal], withheld={})
    assert (applied[1].speed_mph, applied[1].speed_withheld_mph) == (20, None)
    keyless = RoadFeature(canal.feature_id, canal.coordinates, replace(canal.facts, block_key=None))
    applied, _ = road_facts_by_way([road], entries, [keyless])
    assert (applied[1].speed_mph, applied[1].speed_withheld_mph) == (20, None)


def test_row_c4_never_makes_a_carriageway_of_the_review_two_way() -> None:
    """The combined correctness review: a District two-way record made South
    Capitol Street SW 910656491, 910656606 and 1122669898, E Street NW 6056366
    and H Street NW 50511181 two-way, though each is one carriageway of a road
    whose other carriageway lies 12 to 88 m away (past `routemaker.divided`'s
    45 m, or under another quadrant's name). With OWNER-DECISIONS 216 that is the
    routing graph's direction, so the overlay's wiring guards row C4 with the
    wider pairing: OSM's one-way stays, for the classifier and the graph."""
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from pipeline.conflation import overlay_road_facts
    from routemaker.agency_roads import WayFacts

    data = json.loads((Path(__file__).parent / "data" / "c4_carriageways.json").read_text())
    ways = [
        SimpleNamespace(
            osm_id=w["id"], tags=w["tags"], coordinates=[tuple(c) for c in w["coordinates"]]
        )
        for w in data["ways"]
    ]
    two_way = WayFacts(
        agency=DC_AGENCY, blocks=("b",), one_way=False, two_way_throughout=True, names_agree=True
    )
    facts = {way_id: replace(two_way, blocks=(f"b{way_id}",)) for way_id in data["review"]}
    overlays = overlay_road_facts(ways, facts)
    for way_id in data["review"]:
        overlay = overlays[way_id]
        assert overlay.tags["oneway"] == "yes", way_id
        assert overlay.routing == {}, way_id
        assert overlay.disagreements == (
            "oneway: agency two-way, OSM one-way, kept (divided carriageway)",
        ), way_id
    # The control: a plain one-way street of the fixture that is no carriageway
    # (20th Street NW) is made two-way by the same record.
    (couplet,) = [w for w in data["couplet"] if w != 130889760]
    plain = overlay_road_facts(ways, {couplet: two_way})[couplet]
    assert plain.tags["oneway"] == "no"
    assert plain.routing == {"oneway": "no"}
