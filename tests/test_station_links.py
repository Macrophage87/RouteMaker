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
    assert sl.ways_in([at(5.0, 5.0)], [station], [near, far]) == [at(5.0, 5.0), station, near]
    assert sl.is_way_in({"railway": "subway_entrance"})
    assert sl.is_way_in({"railway": "train_station_entrance"})
    assert sl.is_station({"public_transport": "station"})
    assert not sl.is_way_in({"highway": "elevator"})


def way(osm_id, tags, nodes, coords):
    return Way(osm_id, tags, nodes, coords, list(range(len(nodes))))


def test_the_rebuild_opens_station_links_and_closes_the_escalator():
    ways = [way(*w) for w in shady_grove()]
    result = tc.closures(ways, {}, [])
    assert result.reasons.get(8) == sl.ESCALATOR
    tc.add_walk_links(result, ways)
    tc.add_station_links(result, ways, [ELEVATOR])
    assert {1, 2, 4} <= result.walk_links
    assert {1, 2, 4} <= result.walk_bike, "the directions say walk your bike here"
    assert not ({1, 2, 4} & set(result.reasons))
