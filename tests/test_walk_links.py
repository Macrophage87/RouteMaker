"""Short walk-your-bike links where a bike way stops at a sidewalk (routemaker.walk_links).

The owner's report of 2026-10-20 on Redland Road, Derwood: a paved path ends on a
sidewalk about 120 ft (36 m) short of the road's side path, and the route could not
join them. The shapes below are that one and its neighbours, in metres east and north
of a point in Montgomery County.
"""

from __future__ import annotations

import math

from pipeline import trail_closures as tc
from pipeline.extract import Way
from routemaker import walk_links as wl

LON0, LAT0 = -77.157, 39.123


def at(east: float, north: float) -> tuple[float, float]:
    lat = LAT0 + math.degrees(north / 6_371_008.8)
    lon = LON0 + math.degrees(east / (6_371_008.8 * math.cos(math.radians(LAT0))))
    return (lon, lat)


def placed(osm_id, tags, points):
    """(id, tags, node ids, coordinates): node ids are the points themselves, so ways
    that share a point share a node."""
    nodes = [int(e * 1000) * 1_000_000 + int(n * 1000) for e, n in points]
    return (osm_id, tags, nodes, [at(e, n) for e, n in points])


TRAIL = {"highway": "path", "bicycle": "designated", "surface": "asphalt"}
SIDE_PATH = {"highway": "cycleway", "bicycle": "designated"}
SIDEWALK = {"highway": "footway", "footway": "sidewalk"}


def redland(sidewalk_tags=SIDEWALK, gap=36.0, sidewalk_far=139.0):
    """A trail coming down from the north ends on a sidewalk `gap` metres from the
    side path the sidewalk starts on; the sidewalk runs on east to a street."""
    return [
        placed(1, TRAIL, [(gap, 200.0), (gap, 0.0)]),
        placed(2, SIDE_PATH, [(0.0, -200.0), (0.0, 0.0), (0.0, 200.0)]),
        placed(3, dict(sidewalk_tags), [(0.0, 0.0), (gap, 0.0), (gap + sidewalk_far, 0.0)]),
        placed(
            4, {"highway": "residential"}, [(gap + sidewalk_far, -100.0), (gap + sidewalk_far, 0.0)]
        ),
    ]


def test_the_trail_that_stops_on_a_sidewalk_gets_a_walk_link():
    found = wl.links(redland())
    assert set(found) == {3}
    assert round(found[3]) == 36, "the walk is the 120 ft to the side path, not the street"


def test_a_walk_longer_than_the_gap_is_no_link():
    assert wl.links(redland(gap=wl.GAP_M + 5)) == {}


def test_a_footway_too_long_to_open_is_left_closed():
    assert wl.links(redland(sidewalk_far=wl.WAY_MAX_M)) == {}


def test_a_sidewalk_any_bicycle_tag_speaks_for_is_not_touched():
    assert wl.links(redland({**SIDEWALK, "bicycle": "no"})) == {}
    assert wl.links(redland({**SIDEWALK, "bicycle": "yes"})) == {}, "already open: no gap"


def test_a_footway_barred_on_foot_or_indoors_is_no_link():
    assert wl.links(redland({**SIDEWALK, "foot": "no"})) == {}
    assert wl.links(redland({**SIDEWALK, "access": "private"})) == {}
    assert wl.links(redland({**SIDEWALK, "indoor": "yes"})) == {}


def test_an_informal_area_or_pedestrian_footway():
    assert wl.links(redland({**SIDEWALK, "informal": "yes"})) == {}
    assert wl.links(redland({**SIDEWALK, "area": "yes"})) == {}
    assert set(wl.links(redland({"highway": "pedestrian"}))) == {3}


def test_a_link_through_two_footways_opens_both():
    ways = [
        placed(50, TRAIL, [(0.0, 100.0), (0.0, 20.0)]),
        placed(51, {"highway": "footway"}, [(0.0, 20.0), (0.0, 10.0)]),
        placed(52, SIDEWALK, [(-50.0, 10.0), (0.0, 10.0), (30.0, 10.0), (50.0, 10.0)]),
        placed(53, SIDE_PATH, [(30.0, -100.0), (30.0, 10.0)]),
    ]
    found = wl.links(ways)
    assert set(found) == {51, 52}
    assert round(found[51]) == round(found[52]) == 40


def test_a_footway_edge_with_no_location_is_not_walked():
    osm_id, tags, nodes, coords = placed(3, SIDEWALK, [(0.0, 0.0), (36.0, 0.0), (175.0, 0.0)])
    ways = redland()
    ways[2] = (osm_id, tags, nodes, [None, *coords[1:]])
    assert wl.links(ways) == {}, "a clipped extract never guesses a link"


def test_a_closed_footway_is_never_a_link():
    assert wl.links(redland(), closed={3}) == {}


def test_a_trail_that_already_joins_a_bike_way_is_not_a_dead_end():
    ways = redland()
    ways.append(placed(5, SIDE_PATH, [(36.0, 0.0), (36.0, -50.0), (0.0, -50.0)]))
    assert wl.links(ways) == {}


def test_two_roads_joined_through_a_sidewalk_are_not_a_link():
    """Neither end is a trail: a parking lot that meets the street only through a
    sidewalk is a mapping gap, not a bike link."""
    ways = [
        placed(
            10, {"highway": "service", "service": "parking_aisle"}, [(20.0, 100.0), (20.0, 0.0)]
        ),
        placed(11, SIDEWALK, [(0.0, 0.0), (20.0, 0.0), (100.0, 0.0)]),
        placed(12, {"highway": "residential"}, [(0.0, -100.0), (0.0, 0.0), (0.0, 100.0)]),
    ]
    assert wl.links(ways) == {}


def test_a_street_that_ends_at_a_footway_to_a_trail_is_a_link():
    ways = [
        placed(20, {"highway": "residential"}, [(0.0, -100.0), (0.0, 0.0)]),
        placed(21, {"highway": "footway"}, [(0.0, 0.0), (0.0, 25.0)]),
        placed(22, TRAIL, [(-100.0, 25.0), (0.0, 25.0), (100.0, 25.0)]),
    ]
    assert set(wl.links(ways)) == {21}


def test_a_cul_de_sac_sidewalk_back_to_its_own_street_is_no_link():
    ways = [
        placed(30, {"highway": "residential"}, [(0.0, -100.0), (0.0, 0.0)]),
        placed(31, SIDEWALK, [(0.0, 0.0), (10.0, 0.0), (10.0, -30.0), (0.0, -30.0)]),
    ]
    assert wl.links(ways) == {}


def test_a_trail_that_stops_at_an_unmarked_crossing_is_walked_across():
    ways = [
        placed(40, TRAIL, [(0.0, 100.0), (0.0, 6.0)]),
        placed(
            41, {"highway": "footway", "footway": "crossing"}, [(0.0, 6.0), (0.0, 0.0), (0.0, -6.0)]
        ),
        placed(42, {"highway": "secondary"}, [(-100.0, 0.0), (0.0, 0.0), (100.0, 0.0)]),
    ]
    assert set(wl.links(ways)) == {41}


def test_the_bicycle_open_reading_follows_upstream():
    assert wl.bicycle_open({"highway": "residential"})
    assert wl.bicycle_open({"highway": "service", "service": "driveway"})
    assert not wl.bicycle_open({"highway": "residential", "access": "private"})
    assert wl.bicycle_open({"highway": "residential", "access": "private", "bicycle": "yes"})
    assert not wl.bicycle_open({"highway": "motorway"})
    assert not wl.bicycle_open({"highway": "steps"})
    assert not wl.bicycle_open({"highway": "footway"})
    assert wl.bicycle_open({"highway": "footway", "bicycle": "yes"})


def way(osm_id, tags, points):
    osm_id, tags, nodes, coords = placed(osm_id, tags, points)
    return Way(osm_id, tags, nodes, coords, list(range(len(nodes))))


def test_the_rebuild_flags_the_link_walk_your_bike():
    ways = [
        way(*placed_way[:2], points)
        for placed_way, points in (
            ((1, TRAIL), [(36.0, 200.0), (36.0, 0.0)]),
            ((2, SIDE_PATH), [(0.0, -200.0), (0.0, 0.0), (0.0, 200.0)]),
            ((3, SIDEWALK), [(0.0, 0.0), (36.0, 0.0), (175.0, 0.0)]),
        )
    ]
    result = tc.closures(ways, {}, [])
    tc.add_walk_links(result, ways)
    assert result.walk_links == {3}
    assert 3 in result.walk_bike, "the directions say walk your bike here"
    assert 3 not in result.reasons
