"""Divided-road carriageways (routemaker.divided): OWNER-DECISIONS 109's one-way
relief is for one-way streets, not for one side of a road with a median."""

from __future__ import annotations

from types import SimpleNamespace

from routemaker import divided

# About 20 m of latitude and longitude here.
LAT_20M = 20 / 111_195
LON_20M = 20 / 86_700


def way(osm_id, coords, **tags):
    tags = {"highway": "primary", "name": "Georgia Avenue", "oneway": "yes", **tags}
    return SimpleNamespace(osm_id=osm_id, tags=tags, coordinates=coords)


NORTH = [(-77.03, 39.00), (-77.03, 39.01)]  # 1.1 km, two vertices only
SOUTH = [(-77.03 + LON_20M, 39.01), (-77.03 + LON_20M, 39.00)]


def test_two_opposite_carriageways_of_one_name_are_divided() -> None:
    assert divided.carriageways([way(1, NORTH), way(2, SOUTH)]) == {1, 2}


def test_a_minus_one_way_is_read_in_its_direction() -> None:
    reversed_south = list(reversed(SOUTH))
    assert divided.carriageways([way(1, NORTH), way(2, reversed_south, oneway="-1")]) == {1, 2}
    assert divided.carriageways([way(1, NORTH), way(2, reversed_south)]) == set()


def test_same_direction_or_other_name_or_two_way_is_not() -> None:
    assert divided.carriageways([way(1, NORTH), way(2, list(reversed(SOUTH)))]) == set()
    assert divided.carriageways([way(1, NORTH), way(2, SOUTH, name="Colesville Road")]) == set()
    assert divided.carriageways([way(1, NORTH), way(2, SOUTH, oneway="no")]) == set()
    assert divided.carriageways([way(1, NORTH), way(2, SOUTH, highway="residential")]) == set()
    assert divided.carriageways([way(1, NORTH, name=""), way(2, SOUTH, name="")]) == set()


def test_a_couplet_a_block_apart_is_not() -> None:
    far = [(x + 5 * LON_20M, y) for x, y in SOUTH]  # 100 m east
    assert divided.carriageways([way(1, NORTH), way(2, far)]) == set()


def test_a_street_that_changes_direction_at_a_junction_is_not() -> None:
    # One-way north for a block, then one-way south: head on at the junction.
    first = [(-77.03, 39.00), (-77.03, 39.001)]
    second = [(-77.03, 39.002), (-77.03, 39.001)]
    assert divided.carriageways([way(1, first), way(2, second)]) == set()
    # Short last segments bring the two ends within a step: still head on.
    first = [(-77.03, 39.000), (-77.03, 39.00095), (-77.03, 39.001)]
    second = [(-77.03, 39.002), (-77.03, 39.00105), (-77.03, 39.001)]
    assert divided.carriageways([way(1, first), way(2, second)]) == set()


def test_a_jogged_junction_is_not() -> None:
    # The street carries on 10 m to the east, one-way the other way, beyond
    # the junction: beside it, but not alongside.
    first = [(-77.03, 39.000), (-77.03, 39.001)]
    second = [(-77.03 + LON_20M / 2, 39.0015), (-77.03 + LON_20M / 2, 39.00115)]
    assert divided.carriageways([way(1, first), way(2, second)]) == set()


def test_a_narrow_median_still_counts() -> None:
    near = [(x - LON_20M + LON_20M / 4, y) for x, y in SOUTH]  # 5 m apart
    assert divided.carriageways([way(1, NORTH), way(2, near)]) == {1, 2}
