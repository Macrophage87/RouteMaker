"""Walk-your-bike links into stations, and escalators closed (routemaker.station_links).

The owner's report of 2026-10-20 at Shady Grove: the footways to the street elevator
and the tunnel under the tracks carry no bicycle tag, so routes stopped short or went
round. The shapes are like that station's, in metres east and north of a point there.
"""

from __future__ import annotations

import math

from pipeline import trail_closures as tc
from pipeline.extract import Way
from routemaker import station_links as sl

LON0, LAT0 = -77.165, 39.120


def at(east: float, north: float) -> tuple[float, float]:
    lat = LAT0 + math.degrees(north / 6_371_008.8)
    lon = LON0 + math.degrees(east / (6_371_008.8 * math.cos(math.radians(LAT0))))
    return (lon, lat)


def placed(osm_id, tags, points):
    nodes = [int(e * 1000) * 1_000_000 + int(n * 1000) for e, n in points]
    return (osm_id, tags, nodes, [at(e, n) for e, n in points])


FOOTWAY = {"highway": "footway"}
TUNNEL = {"highway": "footway", "tunnel": "yes", "layer": "-1"}
SERVICE = {"highway": "service"}
BIKE_FOOTWAY = {"highway": "footway", "bicycle": "yes"}
ESCALATOR = {"highway": "steps", "conveying": "backward"}

ELEVATOR = at(0.0, 0.0)


def shady_grove(changes=None):
    """The elevator at (0, 0); footways from it run 60 m south to a service road; a tunnel
    from beside it runs 80 m east to footways open to bicycles; a sidewalk goes on west
    from the service road, 200 m, to a street."""
    ways = {
        1: placed(1, FOOTWAY, [(0.0, 0.0), (0.0, -30.0)]),
        2: placed(2, FOOTWAY, [(0.0, -30.0), (0.0, -60.0)]),
        3: placed(3, SERVICE, [(-100.0, -60.0), (0.0, -60.0), (100.0, -60.0)]),
        4: placed(4, TUNNEL, [(0.0, 0.0), (80.0, 0.0)]),
        5: placed(5, BIKE_FOOTWAY, [(80.0, 0.0), (80.0, 100.0)]),
        6: placed(6, FOOTWAY, [(-100.0, -60.0), (-300.0, -60.0)]),
        7: placed(7, {"highway": "residential"}, [(-300.0, -200.0), (-300.0, -60.0)]),
        8: placed(8, ESCALATOR, [(-5.0, 0.0), (0.0, 0.0)]),
    }
    ways.update(changes or {})
    return list(ways.values())


def test_the_footways_from_the_elevator_and_its_tunnel_open_at_a_walk():
    found = sl.links(shady_grove(), [ELEVATOR])
    assert set(found) == {1, 2, 4}
    assert round(found[1]) == 60 and round(found[4]) == 80


def test_a_walk_stops_at_the_first_bike_way_and_is_never_a_way_round():
    found = sl.links(shady_grove(), [ELEVATOR])
    assert 6 not in found, "the sidewalk past the service road is not a way in"


def test_a_way_in_on_a_sidewalk_opens_its_nearest_crossing_and_no_more():
    """An entrance on a sidewalk with a crossing to a street every 60 m: one walk."""
    ways = [
        placed(
            10 + i,
            {"highway": "footway", "footway": "sidewalk"},
            [(60.0 * i, 0.0), (60.0 * (i + 1), 0.0)],
        )
        for i in range(4)
    ]
    ways += [
        placed(
            20 + i,
            {"highway": "footway", "footway": "crossing"},
            [(60.0 * (i + 1), 0.0), (60.0 * (i + 1), -10.0)],
        )
        for i in range(4)
    ]
    ways += [placed(30, {"highway": "residential"}, [(60.0 * i, -10.0) for i in range(6)])]
    assert set(sl.links(ways, [at(0.0, 0.0)])) == {10, 20}


def test_the_tunnel_is_walked_even_when_a_road_is_nearer():
    nearer = placed(3, SERVICE, [(-100.0, -40.0), (0.0, -40.0)])
    found = sl.links(
        shady_grove({1: placed(1, FOOTWAY, [(0.0, 0.0), (0.0, -40.0)]), 3: nearer}), [ELEVATOR]
    )
    assert 4 in found and 1 in found
    assert sl.is_tunnel(TUNNEL) and sl.is_tunnel({"layer": "-1"}) and not sl.is_tunnel(FOOTWAY)


def test_no_way_in_near_means_no_link():
    assert sl.links(shady_grove(), [at(1000.0, 1000.0)]) == {}
    assert sl.links(shady_grove(), []) == {}


def test_an_elevator_mapped_beside_its_footway_still_starts_a_walk():
    assert set(sl.links(shady_grove(), [at(10.0, 5.0)])) >= {1, 2, 4}


def test_a_walk_longer_than_the_limit_is_left_closed():
    long_tunnel = placed(4, TUNNEL, [(0.0, 0.0), (sl.WALK_MAX_M + 20.0, 0.0)])
    long_bike = placed(
        5, BIKE_FOOTWAY, [(sl.WALK_MAX_M + 20.0, 0.0), (sl.WALK_MAX_M + 20.0, 100.0)]
    )
    assert 4 not in sl.links(shady_grove({4: long_tunnel, 5: long_bike}), [ELEVATOR])


def test_tagged_closed_and_indoor_footways_stay_as_they_are():
    tagged = placed(4, {**TUNNEL, "bicycle": "no"}, [(0.0, 0.0), (80.0, 0.0)])
    assert 4 not in sl.links(shady_grove({4: tagged}), [ELEVATOR])
    indoor = placed(4, {**TUNNEL, "indoor": "yes"}, [(0.0, 0.0), (80.0, 0.0)])
    assert 4 not in sl.links(shady_grove({4: indoor}), [ELEVATOR])
    assert 4 not in sl.links(shady_grove(), [ELEVATOR], closed={4})


def test_steps_are_never_a_link_and_an_escalator_is():
    assert 8 not in sl.links(shady_grove(), [ELEVATOR])
    assert sl.is_escalator(ESCALATOR)
    assert not sl.is_escalator({"highway": "steps"})
    assert not sl.is_escalator({"highway": "steps", "conveying": "no"})


def test_ways_in_are_entrances_stations_and_elevators_near_a_station():
    station = at(0.0, 0.0)
    near, far = at(100.0, 0.0), at(2000.0, 0.0)
    assert sl.ways_in([at(5.0, 5.0)], [station], [near, far]) == [at(5.0, 5.0), near]
    assert sl.ways_in([], [station], [far]) == [station], "a station with no way in mapped"
    assert sl.is_way_in({"railway": "subway_entrance"})
    assert sl.is_way_in({"railway": "train_station_entrance"})
    assert sl.is_station({"railway": "station", "station": "subway"})
    assert not sl.is_station({"public_transport": "station", "bus": "yes"}), (
        "a bus station is not one"
    )
    assert not sl.is_way_in({"highway": "elevator"})


def way(osm_id, tags, nodes, coords):
    return Way(osm_id, tags, nodes, coords, list(range(len(nodes))))


def test_the_rebuild_opens_station_links_and_closes_the_escalator():
    ways = [way(*w) for w in shady_grove()]
    result = tc.closures(ways, {}, [])
    assert result.reasons.get(8) == sl.ESCALATOR
    tc.add_sidewalk_rides(result, ways)
    tc.add_station_links(result, ways, [ELEVATOR])
    assert {1, 2, 4} <= result.walk_links
    assert {1, 2, 4} <= result.walk_bike, "the directions say walk your bike here"
    assert not ({1, 2, 4} & set(result.reasons))
    assert not ({1, 2, 4} & result.sidewalk_rides), "walked, not ridden"


def test_the_tunnel_to_an_entrance_on_an_untagged_sidewalk_is_walked_through():
    """Shady Grove's: the tunnel's far end meets only a sidewalk with no bicycle tag, which
    reaches footways open to bicycles a few metres on; its near end is beside the elevator."""
    far_sidewalk = placed(5, FOOTWAY, [(80.0, 0.0), (84.0, 0.0)])
    bike = placed(9, BIKE_FOOTWAY, [(84.0, 0.0), (84.0, 100.0)])
    tunnel = placed(4, TUNNEL, [(-8.0, 0.0), (80.0, 0.0)])
    entrance = at(80.0, 0.0)
    found = sl.links(shady_grove({4: tunnel, 5: far_sidewalk, 9: bike}), [ELEVATOR, entrance])
    assert {1, 2, 4, 5} <= set(found)


def test_a_footway_too_long_to_open_is_walked_round():
    long_way = placed(2, FOOTWAY, [(0.0, -30.0), (sl.WAY_MAX_M, -30.0), (0.0, -60.0)])
    found = sl.links(shady_grove({2: long_way}), [ELEVATOR])
    assert 2 not in found and 4 in found


def test_a_way_in_on_a_footway_walks_from_itself():
    """Shady Grove's elevator is the first node of its footway; the footway's far end is
    within SEED_M of it, but the walk still starts at the elevator."""
    found = sl.links(
        shady_grove({1: placed(1, FOOTWAY, [(0.0, 0.0), (0.0, -20.0), (0.0, -30.0)])}), [ELEVATOR]
    )
    assert 1 in found


# Kensington's MARC station (the owner, 2026-10-27: "the handicap ramp at the Kensington
# rail station was marked as a bike path"), in metres from the north platform's end: the
# ramp from the street down to the north platform, the crossing over the tracks between
# the platforms, a 4 m walkway off the south platform to the station building's walkways,
# a walkway along the building and on into the parking lot, and a shared-use path nearby.
PLATFORM = {"railway": "platform", "public_transport": "platform", "train": "yes"}
RAMP = {"highway": "footway", "bicycle": "yes", "surface": "concrete"}
TRACK_CROSSING = {"highway": "footway", "footway": "crossing", "bicycle": "yes"}


def kensington(changes=None):
    ways = {
        20: placed(20, PLATFORM, [(0.0, 0.0), (-60.0, 0.0)]),
        21: placed(21, PLATFORM, [(0.0, -10.0), (-60.0, -10.0)]),
        1: placed(1, RAMP, [(0.0, 0.0), (-40.0, 30.0), (-60.0, 40.0)]),
        2: placed(2, TRACK_CROSSING, [(0.0, -10.0), (0.0, 0.0)]),
        3: placed(3, RAMP, [(0.0, -10.0), (0.0, -14.0)]),
        4: placed(4, RAMP, [(0.0, -14.0), (20.0, -14.0)]),
        # Begins 20 m from the platform, past PLATFORM_REACH_M: the parking lot's.
        5: placed(5, RAMP, [(20.0, -14.0), (30.0, -14.0)]),
        6: placed(6, {"highway": "residential"}, [(-60.0, 40.0), (-200.0, 40.0)]),
        7: placed(7, {"highway": "footway", "bicycle": "designated"}, [(0.0, 0.0), (0.0, 80.0)]),
        8: placed(8, {**RAMP, "name": "Station Trail"}, [(-60.0, 0.0), (-60.0, -80.0)]),
    }
    ways.update(changes or {})
    return list(ways.values())


def platform_nodes(ways):
    return {node for _id, tags, nodes, _coords in ways if sl.is_platform(tags) for node in nodes}


def test_the_ramp_and_walkways_at_a_platform_are_walked():
    ways = kensington()
    assert sl.platform_walks(ways, platform_nodes(ways)) == {1, 2, 3, 4}


def test_a_signed_or_named_trail_at_a_platform_stays_a_path():
    ways = kensington()
    found = sl.platform_walks(ways, platform_nodes(ways))
    assert 7 not in found, "bicycle=designated"
    assert 8 not in found, "a named trail"
    assert 5 not in found, "begins past the platform's reach"


def test_a_long_walkway_or_a_closed_one_is_left_alone():
    long_ramp = placed(1, RAMP, [(0.0, 0.0), (-sl.WAY_MAX_M, 0.0), (0.0, 40.0)])
    ways = kensington({1: long_ramp})
    assert 1 not in sl.platform_walks(ways, platform_nodes(ways))
    ways = kensington()
    assert 3 not in sl.platform_walks(ways, platform_nodes(ways), closed={3})


def test_no_platform_nothing_walked():
    assert sl.platform_walks(kensington(), set()) == set()


def test_only_a_rail_platform_in_service_counts():
    assert sl.is_platform(PLATFORM)
    assert sl.is_platform({"railway": "platform", "light_rail": "yes"})
    assert not sl.is_platform({"public_transport": "platform", "bus": "yes"}), "a bus stop"
    assert not sl.is_platform({"railway": "platform"}), "a park's miniature railway"
    assert not sl.is_platform({**PLATFORM, "disused": "yes"}), "a disused line's"


def test_permissive_paths_are_walked_but_not_cycleways():
    ways = kensington(
        {
            3: placed(
                3, {"highway": "path", "bicycle": "permissive"}, [(0.0, -10.0), (0.0, -14.0)]
            ),
            1: placed(1, {"highway": "cycleway"}, [(0.0, 0.0), (-40.0, 30.0), (-60.0, 40.0)]),
        }
    )
    found = sl.platform_walks(ways, platform_nodes(ways))
    assert 3 in found and 1 not in found


def test_the_rebuild_walks_the_platform_walkways():
    ways = [way(*w) for w in kensington()]
    result = tc.closures(ways, {}, [])
    tc.add_sidewalk_rides(result, ways)
    tc.add_platform_walks(result, ways, platform_nodes(kensington()))
    assert result.platform_walks == {1, 2, 3, 4}
    assert {1, 2, 3, 4} <= result.walk_bike, "the directions say walk your bike here"
    assert not ({1, 2, 3, 4} & result.sidewalk_rides), "walked, not ridden"
