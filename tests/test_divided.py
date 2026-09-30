"""Divided-road carriageways (routemaker.divided): OWNER-DECISIONS 109's one-way
relief is for one-way streets, not for one side of a road with a median."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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


def test_the_approved_45_m_is_the_limit() -> None:
    """Item 132 approved "within about 45 m": 40 m apart is a divided road,
    50 m is not."""
    forty = [(x + LON_20M, y) for x, y in SOUTH]
    fifty = [(x + LON_20M * 1.5, y) for x, y in SOUTH]
    assert divided.carriageways([way(1, NORTH), way(2, forty)]) == {1, 2}
    assert divided.carriageways([way(1, NORTH), way(2, fifty)]) == set()


@pytest.mark.parametrize("highway", ["trunk", "primary", "secondary", "tertiary", "unclassified"])
def test_every_divided_class_is_read(highway) -> None:
    pair = [way(1, NORTH, highway=highway), way(2, SOUTH, highway=highway)]
    assert divided.carriageways(pair) == {1, 2}


def ring(radius_m, lon0=-77.03, lat0=39.00, n=24):
    """A circle, counter-clockwise, as two one-way halves joined end to end."""
    import math

    pts = [
        (
            lon0 + radius_m * math.cos(2 * math.pi * i / n) / 86_700,
            lat0 + radius_m * math.sin(2 * math.pi * i / n) / 111_195,
        )
        for i in range(n + 1)
    ]
    pts[-1] = pts[0]
    half = n // 2
    return pts[: half + 1], pts[half:]


def test_a_small_same_named_circle_is_not_a_divided_road() -> None:
    """Ward, Tenley and Blair Circles, and a one-way loop road: the two halves
    face each other across the ring (review r1)."""
    first, second = ring(20)
    circle = [way(1, first, name="Ward Circle"), way(2, second, name="Ward Circle")]
    assert divided.carriageways(circle) == set()
    whole = way(3, first + second[1:], name="Blair Circle")
    assert divided.carriageways([whole]) == set()


def test_a_short_pair_that_does_not_close_is_still_divided() -> None:
    """Only a closed ring is a loop: 300 m of median, not joined at the ends."""
    north = [(-77.03, 39.000), (-77.03, 39.0027)]
    south = [(-77.03 + LON_20M, 39.0027), (-77.03 + LON_20M, 39.000)]
    assert divided.carriageways([way(1, north), way(2, south)]) == {1, 2}


def test_a_long_pair_joined_at_both_ends_is_still_divided() -> None:
    """A median over 1 km: the carriageways close a ring too, but a long one."""
    north = [(-77.03, 39.00), (-77.03, 39.01)]
    south = [
        (-77.03, 39.01),
        (-77.03 + LON_20M, 39.009),
        (-77.03 + LON_20M, 39.001),
        (-77.03, 39.00),
    ]
    assert divided.carriageways([way(1, north), way(2, south)]) == {1, 2}
    short_north = [(-77.03, 39.000), (-77.03, 39.003)]
    short_south = [
        (-77.03, 39.003),
        (-77.03 + LON_20M, 39.0025),
        (-77.03 + LON_20M, 39.0005),
        (-77.03, 39.000),
    ]
    assert divided.carriageways([way(1, short_north), way(2, short_south)]) == set()
