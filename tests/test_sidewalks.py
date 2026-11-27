"""Sidewalks ridden as a last resort, and short footway links (routemaker.sidewalks).

The owner's report of 2026-10-20 on Redland Road, Derwood: a paved path ends on a
sidewalk about 120 ft (36 m) short of the road's side path, and the route could not
join them. The shapes below are that one and its neighbours, in metres east and north
of a point in Montgomery County. The price is checked in real tiles in
tests/test_tile_build_sidewalk_price.py.
"""

from __future__ import annotations

import math

from pipeline import trail_closures as tc
from pipeline.extract import Way
from routemaker import sidewalks as sw

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


def test_the_trail_that_stops_on_a_sidewalk_gets_a_link():
    found = sw.links(redland())
    assert set(found) == {3}
    assert round(found[3]) == 36, "the walk is the 120 ft to the side path, not the street"


def test_a_walk_longer_than_the_gap_is_no_link():
    assert sw.links(redland(gap=sw.GAP_M + 5)) == {}


def test_a_footway_too_long_to_open_is_left_closed():
    assert sw.links(redland(sidewalk_far=sw.WAY_MAX_M)) == {}


def test_a_sidewalk_any_bicycle_tag_speaks_for_is_not_touched():
    assert sw.links(redland({**SIDEWALK, "bicycle": "no"})) == {}
    assert sw.links(redland({**SIDEWALK, "bicycle": "yes"})) == {}, "already open: no gap"


def test_a_footway_barred_on_foot_or_indoors_is_no_link():
    assert sw.links(redland({**SIDEWALK, "foot": "no"})) == {}
    assert sw.links(redland({**SIDEWALK, "access": "private"})) == {}
    assert sw.links(redland({**SIDEWALK, "indoor": "yes"})) == {}


def test_an_informal_area_or_pedestrian_footway():
    assert sw.links(redland({**SIDEWALK, "informal": "yes"})) == {}, "175 m: too long to walk"
    assert sw.links(redland({**SIDEWALK, "area": "yes"})) == {}
    assert set(sw.links(redland({"highway": "pedestrian"}))) == {3}


def test_a_link_through_two_footways_opens_both():
    ways = [
        placed(50, TRAIL, [(0.0, 100.0), (0.0, 20.0)]),
        placed(51, {"highway": "footway"}, [(0.0, 20.0), (0.0, 10.0)]),
        placed(52, SIDEWALK, [(-50.0, 10.0), (0.0, 10.0), (30.0, 10.0), (50.0, 10.0)]),
        placed(53, SIDE_PATH, [(30.0, -100.0), (30.0, 10.0)]),
    ]
    found = sw.links(ways)
    assert set(found) == {51, 52}
    assert round(found[51]) == round(found[52]) == 40


def test_a_footway_edge_with_no_location_is_not_walked():
    osm_id, tags, nodes, coords = placed(3, SIDEWALK, [(0.0, 0.0), (36.0, 0.0), (175.0, 0.0)])
    ways = redland()
    ways[2] = (osm_id, tags, nodes, [None, *coords[1:]])
    assert sw.links(ways) == {}, "a clipped extract never guesses a link"


def test_a_closed_footway_is_never_a_link():
    assert sw.links(redland(), closed={3}) == {}


def test_a_trail_that_already_joins_a_bike_way_is_not_a_dead_end():
    ways = redland()
    ways.append(placed(5, SIDE_PATH, [(36.0, 0.0), (36.0, -50.0), (0.0, -50.0)]))
    assert sw.links(ways) == {}


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
    assert sw.links(ways) == {}


def test_a_street_that_ends_at_a_footway_to_a_trail_is_a_link():
    ways = [
        placed(20, {"highway": "residential"}, [(0.0, -100.0), (0.0, 0.0)]),
        placed(21, {"highway": "footway"}, [(0.0, 0.0), (0.0, 25.0)]),
        placed(22, TRAIL, [(-100.0, 25.0), (0.0, 25.0), (100.0, 25.0)]),
    ]
    assert set(sw.links(ways)) == {21}


def test_a_cul_de_sac_sidewalk_back_to_its_own_street_is_no_link():
    ways = [
        placed(30, {"highway": "residential"}, [(0.0, -100.0), (0.0, 0.0)]),
        placed(31, SIDEWALK, [(0.0, 0.0), (10.0, 0.0), (10.0, -30.0), (0.0, -30.0)]),
    ]
    assert sw.links(ways) == {}


def test_a_trail_that_stops_at_an_unmarked_crossing_is_walked_across():
    ways = [
        placed(40, TRAIL, [(0.0, 100.0), (0.0, 6.0)]),
        placed(
            41, {"highway": "footway", "footway": "crossing"}, [(0.0, 6.0), (0.0, 0.0), (0.0, -6.0)]
        ),
        placed(42, {"highway": "secondary"}, [(-100.0, 0.0), (0.0, 0.0), (100.0, 0.0)]),
    ]
    assert set(sw.links(ways)) == {41}


def test_the_bicycle_open_reading_follows_upstream():
    assert sw.bicycle_open({"highway": "residential"})
    assert sw.bicycle_open({"highway": "service", "service": "driveway"})
    assert not sw.bicycle_open({"highway": "residential", "access": "private"})
    assert sw.bicycle_open({"highway": "residential", "access": "private", "bicycle": "yes"})
    assert not sw.bicycle_open({"highway": "motorway"})
    assert not sw.bicycle_open({"highway": "steps"})
    assert not sw.bicycle_open({"highway": "footway"})
    assert sw.bicycle_open({"highway": "footway", "bicycle": "yes"})


def way(osm_id, tags, points):
    osm_id, tags, nodes, coords = placed(osm_id, tags, points)
    return Way(osm_id, tags, nodes, coords, list(range(len(nodes))))


def test_a_plain_footway_link_is_found_where_sidewalks_are_not_enough():
    """A footway that is no sidewalk is ridden only as a link."""
    ways = redland({"highway": "footway"})
    assert sw.rides(ways) == {3}
    ways = redland({"highway": "footway"}, gap=sw.GAP_M + 5)
    assert sw.rides(ways) == set()


def test_every_unmarked_sidewalk_and_crosswalk_is_ridden():
    lone = [
        placed(60, SIDEWALK, [(0.0, 0.0), (500.0, 0.0)]),
        placed(61, {"highway": "footway", "footway": "crossing"}, [(0.0, 0.0), (0.0, 10.0)]),
        placed(62, {"highway": "footway"}, [(0.0, 10.0), (0.0, 400.0)]),
        placed(63, {**SIDEWALK, "bicycle": "no"}, [(500.0, 0.0), (900.0, 0.0)]),
        placed(64, {**SIDEWALK, "bicycle": "dismount"}, [(900.0, 0.0), (950.0, 0.0)]),
        placed(65, {**SIDEWALK, "foot": "no"}, [(950.0, 0.0), (990.0, 0.0)]),
        placed(66, SIDEWALK, [(990.0, 0.0), (1200.0, 0.0)]),
    ]
    assert sw.rides(lone, closed={66}) == {60, 61}, "a plain footway, a bicycle tag, no feet"


def test_the_rebuild_rides_the_sidewalk_and_the_link():
    ways = [
        way(*placed_way[:2], points)
        for placed_way, points in (
            ((1, TRAIL), [(36.0, 200.0), (36.0, 0.0)]),
            ((2, SIDE_PATH), [(0.0, -200.0), (0.0, 0.0), (0.0, 200.0)]),
            ((3, SIDEWALK), [(0.0, 0.0), (36.0, 0.0), (175.0, 0.0)]),
            ((4, {"highway": "footway"}), [(36.0, 200.0), (60.0, 200.0)]),
        )
    ]
    result = tc.closures(ways, {}, [])
    tc.add_sidewalk_rides(result, ways)
    assert result.sidewalk_rides == {3}
    assert 3 not in result.walk_bike, "ridden, not walked"
    assert 3 not in result.reasons


def test_a_sidewalk_its_own_tags_close_is_not_ridden():
    """The mark reopens anything upstream would close, so a sidewalk closed by more than
    the missing bicycle tag is left as it is."""
    for extra in (
        {"vehicle": "no"},
        {"vehicle": "private"},
        {"access": "destination"},
        {"access": "delivery"},
        {"access": "no", "foot": "yes"},
        {"smoothness": "impassable"},
        {"impassable": "yes"},
    ):
        assert not sw.rideable({**SIDEWALK, **extra}), extra
    for extra in ({}, {"access": "yes"}, {"foot": "designated"}):
        assert sw.rideable({**SIDEWALK, **extra}), extra


def test_a_ridden_sidewalk_is_rated_lts_3_unless_the_owner_rated_it():
    from dataclasses import replace

    from pipeline.run import raise_ridden_sidewalks
    from routemaker.stress import Stress, StressResult

    plain = StressResult(tier=Stress(1), rule="trail-class way")
    owners = replace(plain, rule="override: stress adjustment 7", adjustment=object())
    busy = StressResult(tier=Stress(4), rule="formula")
    ratings = {1: plain, 2: owners, 3: busy}
    raise_ridden_sidewalks(ratings, {1, 2, 3, 4})
    assert int(ratings[1].tier) == sw.TIER and ratings[1].rule == sw.RULE
    assert ratings[2] is owners, "the owner's rating stands"
    assert ratings[3] is busy, "never lowered"


def test_a_sidewalk_beside_a_road_is_found_and_a_crosswalk_is_not():
    road = [at(0.0, 0.0), at(400.0, 0.0)]
    near = [at(20.0, 12.0), at(380.0, 12.0)]
    far = [at(20.0, 60.0), at(380.0, 60.0)]
    across = [at(200.0, -12.0), at(200.0, 12.0)]
    half_way = [at(-300.0, 12.0), at(100.0, 12.0)]
    found = sw.beside([(1, near), (2, far), (3, across), (4, half_way)], [(9, road)])
    assert found == {1}, "within 30 m and parallel along most of its length"
    assert sw.beside([(1, near)], []) == set()


def _stress(tier, half=False):
    from routemaker.stress import Stress, StressResult

    return StressResult(tier=Stress(tier), rule="formula", half=half)


def _owners_45():
    """An owner's override row rating the road 4.5: the half step is on the adjustment."""
    from dataclasses import replace
    from types import SimpleNamespace

    return replace(
        _stress(4), rule="override: stress adjustment 9", adjustment=SimpleNamespace(half=True)
    )


def test_only_sidewalks_beside_a_45_or_avoid_road_keep_the_lower_price():
    from pipeline.run import last_resort_sidewalks

    ways = [
        way(10, {"highway": "primary"}, [(0.0, 0.0), (400.0, 0.0)]),
        way(11, dict(SIDEWALK), [(20.0, 12.0), (380.0, 12.0)]),
        way(12, {"highway": "footway", "footway": "crossing"}, [(0.0, -12.0), (0.0, 12.0)]),
        way(13, dict(SIDEWALK), [(500.0, 0.0), (600.0, 0.0)]),
    ]
    ridden, links = {11, 12, 13}, {13}
    for rating, cheap in (
        (_stress(4), set()),
        (_stress(4, half=True), {11}),
        (_stress(5), {11}),
        (_stress(3), set()),
        (_owners_45(), {11}),
    ):
        last = last_resort_sidewalks(ways, {10: rating}, ridden, links)
        assert last == ridden - links - cheap, rating
    assert 13 not in last, "a link keeps its price"


def test_a_sidewalk_beside_a_fast_level_4_road_keeps_the_lower_price():
    """A 45 mph road rated 4 (most of Southwest Florida's level 4 miles): its sidewalk is a
    link. A 35 mph road rated 4, and one with no speed known, keep the last-resort price."""
    from dataclasses import replace

    from pipeline.run import last_resort_sidewalks

    ways = [
        way(10, {"highway": "primary"}, [(0.0, 0.0), (400.0, 0.0)]),
        way(11, dict(SIDEWALK), [(20.0, 12.0), (380.0, 12.0)]),
    ]
    for speed, cheap in ((45.0, {11}), (55.0, {11}), (35.0, set()), (None, set())):
        rating = replace(_stress(4), speed_mph=speed)
        assert last_resort_sidewalks(ways, {10: rating}, {11}, set()) == {11} - cheap, speed
    calm = replace(_stress(3), speed_mph=45.0)
    assert last_resort_sidewalks(ways, {10: calm}, {11}, set()) == {11}


def test_a_sidewalk_beside_no_road_is_priced_as_a_connector():
    """Briggs Road, Glenmont (the owner's report): a walk tagged `footway=sidewalk`
    joins the two ends of the street, 124 m, with no road beside it; the last-resort price
    sent routes 0.7 mi round. A sidewalk beside a calm street keeps the last-resort price."""
    from pipeline.run import last_resort_sidewalks

    ways = [
        way(20, {"highway": "residential"}, [(-300.0, 0.0), (0.0, 0.0)]),
        way(21, dict(SIDEWALK), [(0.0, 0.0), (124.0, 0.0)]),
        way(22, {"highway": "residential"}, [(124.0, 0.0), (400.0, 0.0)]),
        way(23, dict(SIDEWALK), [(-280.0, 12.0), (-20.0, 12.0)]),
    ]
    last = last_resort_sidewalks(ways, {20: _stress(1), 22: _stress(1)}, {21, 23}, set())
    assert last == {23}


def test_a_short_walk_between_two_dead_ends_is_roadless():
    ways = [
        way(30, {"highway": "residential"}, [(-300.0, 0.0), (0.0, 0.0)]),
        way(31, dict(SIDEWALK), [(0.0, 0.0), (60.0, 0.0)]),
        way(32, {"highway": "residential"}, [(60.0, 0.0), (400.0, 0.0)]),
    ]
    from pipeline.run import last_resort_sidewalks

    assert last_resort_sidewalks(ways, {}, {31}, set()) == set()


def test_a_sidewalk_partly_along_an_lts_4_road_stays_last_resort():
    """Half along a busy road, then off on its own: not a connector."""
    from pipeline.run import last_resort_sidewalks

    ways = [
        way(40, {"highway": "primary"}, [(0.0, 0.0), (500.0, 0.0)]),
        way(41, dict(SIDEWALK), [(0.0, 40.0), (500.0, 40.0), (1000.0, 300.0)]),
    ]
    assert last_resort_sidewalks(ways, {40: _stress(4)}, {41}, set()) == {41}


def test_a_last_resort_sidewalk_is_rated_lts_4():
    from pipeline.run import raise_ridden_sidewalks

    ratings = {1: _stress(1), 2: _stress(1)}
    raise_ridden_sidewalks(ratings, {1, 2}, {2})
    assert int(ratings[1].tier) == sw.TIER
    assert int(ratings[2].tier) == sw.LAST_RESORT_TIER
    assert ratings[2].rule == sw.LAST_RESORT_RULE


# Glen Haven Park, Silver Spring (the owner reported: "Some paths that have short sidewalk
# connections aren't available for routing"): the park's paved path meets the streets beside
# it only through worn connectors, `highway=path` + `informal=yes`, 11 to 20 m long. In metres:
# the park path runs east along y=0; Glenhaven Drive ends 20 m west of its west end, and
# Huntley Avenue comes up from the south and stops 18 m short of its middle.
PARK_PATH = {"highway": "footway", "bicycle": "yes", "surface": "concrete"}
WORN = {"highway": "path", "informal": "yes", "surface": "grass"}


def glen_haven(worn=WORN, west_gap=20.0, make=placed):
    return [
        make(100, PARK_PATH, [(0.0, 0.0), (150.0, 0.0), (310.0, 0.0)]),
        make(101, {"highway": "residential"}, [(-west_gap - 200.0, 0.0), (-west_gap, 0.0)]),
        make(102, dict(worn), [(-west_gap, 0.0), (0.0, 0.0)]),
        make(103, {"highway": "residential"}, [(150.0, -200.0), (150.0, -18.0)]),
        make(104, dict(worn), [(150.0, -18.0), (150.0, -11.0)]),
        make(105, {**worn, "surface": "asphalt"}, [(150.0, -11.0), (150.0, 0.0)]),
        # The east end's open footway to Windham Lane: the path's one way in before.
        make(106, {"highway": "footway", "bicycle": "yes"}, [(310.0, 0.0), (318.0, 0.0)]),
        make(107, {"highway": "residential"}, [(318.0, 0.0), (318.0, -200.0)]),
    ]


WALKABLE = frozenset({102, 104, 105})


def test_a_short_informal_connector_is_a_link():
    assert sw.links(glen_haven()) == {}, "only the connectors the caller names"
    found = sw.links(glen_haven(), walkable=WALKABLE)
    assert set(found) == {102, 104, 105}
    assert round(found[102]) == 20 and round(found[104]) == round(found[105]) == 18


def test_an_informal_connector_is_walked_only_when_short():
    assert sw.links(glen_haven(west_gap=sw.INFORMAL_WAY_MAX_M + 5), walkable=WALKABLE).keys() == {
        104,
        105,
    }
    ways = glen_haven()
    # A long worn path, only 20 m of it the gap: opening it would open all of it.
    ways[2] = placed(102, WORN, [(-20.0, 0.0), (0.0, 0.0), (0.0, 80.0)])
    assert 102 not in sw.links(ways, walkable=WALKABLE)


def test_an_informal_connector_a_tag_closes_is_left_alone():
    for extra in ({"bicycle": "no"}, {"foot": "no"}, {"access": "private"}, {"area": "yes"}):
        assert not sw.is_informal_connector({**WORN, **extra}), extra
        ways = glen_haven({**WORN, **extra}, make=way)
        result = tc.closures(ways, {}, [])
        tc.add_sidewalk_rides(result, ways)
        assert not WALKABLE & result.walk_links, extra
    assert not sw.is_informal_connector({**WORN, "informal": "no"})
    assert sw.is_informal_connector({"highway": "footway", "informal": "yes"})


def test_the_rebuild_walks_the_informal_connectors_and_rides_nothing_new():
    ways = glen_haven(make=way)
    result = tc.closures(ways, {}, [])
    assert result.reasons[102] == "informal", "the trail rules close a worn path"
    tc.add_sidewalk_rides(result, ways)
    assert {102, 104, 105} <= result.walk_links
    assert {102, 104, 105} <= result.walk_bike, "walk your bike"
    assert not {102, 104, 105} & set(result.reasons)
    assert not {102, 104, 105} & (result.sidewalk_rides | result.sidewalk_links), "walked"


def test_an_informal_footway_upstream_closes_is_walked_too():
    ways = glen_haven({"highway": "footway", "informal": "yes"}, make=way)
    result = tc.closures(ways, {}, [])
    tc.add_sidewalk_rides(result, ways)
    assert {102, 104, 105} <= result.walk_links
    assert not {102, 104, 105} & result.sidewalk_rides


def test_a_long_informal_path_stays_closed():
    ways = glen_haven(west_gap=80.0, make=way)
    result = tc.closures(ways, {}, [])
    tc.add_sidewalk_rides(result, ways)
    assert result.reasons[102] == "informal"
    assert 102 not in result.walk_links


def test_a_connector_another_rule_closes_stays_closed():
    for kwargs, reason in (({"military": {102}}, "military"), ({"golf": {102}}, "golf")):
        ways = glen_haven(make=way)
        result = tc.closures(ways, {}, [], **kwargs)
        tc.add_sidewalk_rides(result, ways)
        assert 102 not in result.walk_links, reason
        assert reason in result.reasons[102]
    ways = glen_haven({**WORN, "sac_scale": "hiking"}, make=way)
    result = tc.closures(ways, {}, [])
    tc.add_sidewalk_rides(result, ways)
    assert result.reasons[102] == "sac_scale" and 102 not in result.walk_links


def test_an_informal_path_the_rules_leave_open_is_still_ridden():
    """On a national bicycle route the trail rules keep a worn path open: it is ridden
    already, and never made a walk."""
    from routemaker.trailaccess import WayRoutes

    ways = glen_haven(make=way)
    result = tc.closures(ways, {102: WayRoutes(bicycle_networks=frozenset({"ncn"}))}, [])
    assert 102 not in result.reasons
    tc.add_sidewalk_rides(result, ways)
    assert 102 not in result.walk_links and 102 not in result.walk_bike


FOOTWAY = {"highway": "footway"}
CROSSWALK = {"highway": "footway", "footway": "crossing"}


def glenmont(street=None, path_m=88.0, far=CROSSWALK):
    """Flack Street, Glenmont, as OSM has it (the owner, 2026-10-28): the street comes in
    from the west and ends 8 m past the node the paved path leaves from; the path runs
    east to a crosswalk over the garage road, which leads on to a sidewalk. The street's
    west end meets a cross street."""
    return [
        placed(70, street or {"highway": "residential"}, [(-300.0, 0.0), (0.0, 0.0), (8.0, 0.0)]),
        placed(71, FOOTWAY, [(0.0, 0.0), (0.0, 5.0), (path_m, 5.0)]),
        placed(72, far, [(path_m, 5.0), (path_m, -3.0), (path_m, -11.0)]),
        placed(73, {"highway": "service"}, [(path_m - 30.0, -3.0), (path_m, -3.0)]),
        placed(74, SIDEWALK, [(path_m, -11.0), (path_m + 40.0, -11.0)]),
        placed(76, {"highway": "residential"}, [(-300.0, -100.0), (-300.0, 0.0), (-300.0, 100.0)]),
    ]


def test_the_path_from_a_dead_end_street_to_a_crosswalk_is_a_cut_through():
    ways = glenmont()
    assert set(sw.cut_throughs(ways)) == {71}
    assert sw.links(ways) == {}, "no bike way dead-ends on it: not a link"
    assert 71 in sw.rides(ways)


def test_a_cut_through_is_at_most_500_ft():
    assert set(sw.cut_throughs(glenmont(path_m=sw.CUT_THROUGH_M - 10.0))) == {71}
    assert sw.cut_throughs(glenmont(path_m=sw.CUT_THROUGH_M + 10.0)) == {}


def test_a_service_road_is_no_dead_end_street_and_no_far_end():
    assert sw.cut_throughs(glenmont(street={"highway": "service"})) == {}
    ways = glenmont(far={"highway": "steps"})
    assert sw.cut_throughs(ways) == {}, "only the garage road meets it: a parking lot"
    # The footway itself ends on the garage road: still no far end.
    street, path = glenmont()[:2]
    garage = placed(73, {"highway": "service"}, [(58.0, 5.0), (88.0, 5.0), (88.0, -40.0)])
    assert sw.cut_throughs([street, path, garage]) == {}
    road = placed(73, {"highway": "residential"}, [(58.0, 5.0), (88.0, 5.0), (88.0, -40.0)])
    assert set(sw.cut_throughs([street, path, road])) == {71}, "a street there is a far end"


def test_a_street_that_ends_in_a_parking_aisle_is_no_dead_end():
    ways = glenmont()
    ways.append(placed(78, {"highway": "service"}, [(8.0, 0.0), (8.0, -50.0)]))
    assert sw.cut_throughs(ways) == {}


def test_a_loop_street_has_no_dead_end():
    """A street drawn as a closed way, its first and last node where the footway leaves."""
    loop = placed(
        100,
        {"highway": "residential"},
        [(0.0, 0.0), (20.0, 20.0), (40.0, 0.0), (20.0, -20.0), (0.0, 0.0)],
    )
    ways = [
        loop,
        placed(101, {"highway": "residential"}, [(40.0, 0.0), (140.0, 0.0)]),
        placed(102, FOOTWAY, [(0.0, 0.0), (-60.0, 0.0)]),
        placed(103, CROSSWALK, [(-60.0, -8.0), (-60.0, 0.0), (-60.0, 8.0)]),
    ]
    assert sw.cut_throughs(ways) == {}
    # The same street drawn open, ending where the footway leaves, is a dead end.
    ways[0] = placed(100, {"highway": "residential"}, [(40.0, 0.0), (20.0, 20.0), (0.0, 0.0)])
    assert set(sw.cut_throughs(ways)) == {102}


def test_a_footway_off_a_street_that_goes_on_is_no_cut_through():
    ways = glenmont()
    ways.append(placed(75, {"highway": "residential"}, [(8.0, 0.0), (8.0, -100.0)]))
    assert sw.cut_throughs(ways) == {}


def test_a_cut_through_to_another_street_and_a_closed_or_tagged_one():
    ways = [
        placed(80, {"highway": "residential"}, [(0.0, -100.0), (0.0, 0.0)]),
        placed(81, FOOTWAY, [(0.0, 0.0), (0.0, 60.0)]),
        placed(82, {"highway": "residential"}, [(-100.0, 60.0), (0.0, 60.0), (100.0, 60.0)]),
    ]
    assert set(sw.cut_throughs(ways)) == {81}
    assert sw.cut_throughs(ways, closed={81}) == {}
    for extra in ({"bicycle": "no"}, {"access": "private"}, {"informal": "yes"}):
        tagged = [ways[0], placed(81, {**FOOTWAY, **extra}, [(0.0, 0.0), (0.0, 60.0)]), ways[2]]
        assert sw.cut_throughs(tagged) == {}, extra


def test_the_rebuild_rides_a_cut_through_as_a_link():
    ways = [
        way(70, {"highway": "residential"}, [(-300.0, 0.0), (0.0, 0.0), (8.0, 0.0)]),
        way(71, FOOTWAY, [(0.0, 0.0), (0.0, 5.0), (88.0, 5.0)]),
        way(72, CROSSWALK, [(88.0, 5.0), (88.0, -3.0), (88.0, -11.0)]),
        way(73, {"highway": "service"}, [(58.0, -3.0), (88.0, -3.0)]),
    ]
    result = tc.closures(ways, {}, [])
    tc.add_sidewalk_rides(result, ways)
    assert {71, 72} <= result.sidewalk_rides
    assert 71 in result.sidewalk_links, "priced as a link, not a last-resort sidewalk"
    assert 71 not in result.walk_bike, "ridden, not walked"


def test_the_whole_walk_is_at_most_500_ft():
    """Two footways of 100 m each, each under the cap: 200 m in all is too far."""
    street = placed(90, {"highway": "residential"}, [(0.0, -100.0), (0.0, 0.0)])
    far = placed(93, {"highway": "residential"}, [(-100.0, 200.0), (0.0, 200.0), (100.0, 200.0)])
    first = placed(91, FOOTWAY, [(0.0, 0.0), (0.0, 100.0)])
    assert (
        sw.cut_throughs([street, first, placed(92, FOOTWAY, [(0.0, 100.0), (0.0, 200.0)]), far])
        == {}
    )
    near = placed(92, FOOTWAY, [(0.0, 100.0), (0.0, 140.0)])
    far = placed(93, {"highway": "residential"}, [(-100.0, 140.0), (0.0, 140.0), (100.0, 140.0)])
    assert set(sw.cut_throughs([street, first, near, far])) == {91, 92}


def test_a_path_to_a_door_nearer_the_end_does_not_hide_the_cut_through():
    ways = glenmont()
    street = [(-300.0, 0.0), (0.0, 0.0), (4.0, 0.0), (8.0, 0.0)]
    ways[0] = placed(70, {"highway": "residential"}, street)
    ways.append(placed(77, FOOTWAY, [(4.0, 0.0), (4.0, -10.0)]))
    assert set(sw.cut_throughs(ways)) == {71}


def test_a_dirt_or_hiking_footway_or_a_pedestrian_area_is_no_cut_through():
    for tags in (
        {**FOOTWAY, "surface": "ground"},
        {**FOOTWAY, "surface": "dirt"},
        {**FOOTWAY, "sac_scale": "hiking"},
        {**FOOTWAY, "trail_visibility": "bad"},
        {"highway": "pedestrian"},
    ):
        ways = glenmont()
        ways[1] = placed(71, tags, [(0.0, 0.0), (0.0, 5.0), (88.0, 5.0)])
        assert sw.cut_throughs(ways) == {}, tags
    ways = glenmont()
    ways[1] = placed(
        71, {**FOOTWAY, "surface": "paving_stones"}, [(0.0, 0.0), (0.0, 5.0), (88.0, 5.0)]
    )
    assert set(sw.cut_throughs(ways)) == {71}


def test_e_bikes_and_road_bikes_ride_no_sidewalk_but_walk_a_short_link() -> None:
    """The owner, 2026-11-14: "Novices might use them more and road bikes probably never.
    Ebikes are typically prohibited from sidewalks"."""
    from pipeline import variants
    from pipeline.run import sidewalk_derived

    ridden, last_resort, links = {1, 2, 3}, {1}, {3}

    def told(variant, way):
        return sidewalk_derived(variant, way, ridden, last_resort, links)

    assert told(variants.Variant.STANDARD, 1) == {"sidewalk": sw.LAST_RESORT}
    assert told(variants.Variant.STANDARD, 2) == {"sidewalk": True}
    assert told(variants.Variant.STANDARD, 3) == {"sidewalk": True}
    assert told(variants.Variant.NO_TRAIL, 3) == {}
    for variant in (
        variants.Variant.EBIKE,
        variants.Variant.PAVED,
        variants.Variant.PAVED_WEEKEND,
    ):
        assert told(variant, 1) == {}, "a sidewalk beside a calmer road: closed"
        assert told(variant, 2) == {}, "a sidewalk beside an Avoid road: closed"
        assert told(variant, 3) == {"link_walk": True}, "a short link is walked"
    assert told(variants.Variant.STANDARD, 9) == {}


# Little Falls Parkway at the Capital Crescent Trail (the owner, 2026-11-19: "It seemed to
# miss part of the bike lane next to little falls parkway"): the parkway's separated path
# ends at Arlington Road on a marked crosswalk with no bicycle tag that runs across the
# road to it. In metres: the path runs north up x=0 to y=100, the crosswalk crosses the
# road (along y=112) to a street on the far side.
CROSSWALK = {"highway": "footway", "footway": "crossing", "crossing": "marked"}


def little_falls(path=SIDE_PATH, far=None, crosswalk=CROSSWALK, length=24.0):
    return [
        placed(200, dict(path), [(0.0, 0.0), (0.0, 100.0)]),
        placed(201, dict(crosswalk), [(0.0, 100.0), (0.0, 112.0), (0.0, 100.0 + length)]),
        placed(202, {"highway": "secondary"}, [(-100.0, 112.0), (0.0, 112.0), (100.0, 112.0)]),
        placed(
            203,
            dict(far or {"highway": "tertiary"}),
            [(0.0, 100.0 + length), (0.0, 300.0)],
        ),
    ]


def test_a_crosswalk_carrying_a_trail_across_a_road_is_a_trail_crossing():
    assert sw.trail_crossings(little_falls()) == {201}
    assert sw.trail_crossings(little_falls(far=TRAIL)) == {201}, "path to path"


def test_a_crosswalk_no_trail_meets_is_not():
    assert sw.trail_crossings(little_falls(path={"highway": "residential"})) == set()
    assert sw.trail_crossings(little_falls(path=SIDEWALK)) == set(), "a sidewalk is not a trail"


def test_a_trail_crossing_may_run_on_past_the_road_to_a_sidewalk():
    """Little Falls' own crosswalk runs from the path across both carriageways to the far
    sidewalk: the road it crosses is the bicycle-open way it reaches."""
    assert sw.trail_crossings(little_falls(far=SIDEWALK)) == {201}


def test_a_crosswalk_a_trail_alone_meets_is_not():
    ways = little_falls(far=SIDEWALK)
    ways[2] = placed(202, SIDEWALK, [(-100.0, 112.0), (0.0, 112.0), (100.0, 112.0)])
    assert sw.trail_crossings(ways) == set(), "nothing but the trail is ridden there"


def test_a_trail_crossing_is_short_untagged_and_open():
    assert sw.trail_crossings(little_falls(length=sw.GAP_M + 5)) == set()
    tagged = {**CROSSWALK, "bicycle": "no"}
    assert sw.trail_crossings(little_falls(crosswalk=tagged)) == set()
    assert sw.trail_crossings(little_falls(), closed={201}) == set()


def test_the_rebuild_prices_a_trail_crossing_as_a_link_not_a_last_resort():
    from pipeline.run import last_resort_sidewalks

    ways = [
        way(*w[:2], [(e, n) for e, n in pts])
        for w, pts in (
            ((200, SIDE_PATH), [(0.0, 0.0), (0.0, 100.0)]),
            ((201, CROSSWALK), [(0.0, 100.0), (0.0, 112.0), (0.0, 124.0)]),
            ((202, {"highway": "secondary"}), [(-100.0, 112.0), (0.0, 112.0), (100.0, 112.0)]),
            ((203, {"highway": "tertiary"}), [(0.0, 124.0), (0.0, 300.0)]),
            ((204, CROSSWALK), [(50.0, 100.0), (50.0, 124.0)]),
            ((205, SIDEWALK), [(50.0, 60.0), (50.0, 100.0)]),
            ((206, {"highway": "tertiary"}), [(50.0, 124.0), (50.0, 300.0)]),
        )
    ]
    result = tc.closures(ways, {}, [])
    tc.add_sidewalk_rides(result, ways)
    assert 201 in result.sidewalk_links
    assert 204 not in result.sidewalk_links, "a sidewalk's crosswalk"
    last = last_resort_sidewalks(ways, {}, result.sidewalk_rides, result.sidewalk_links)
    assert 201 not in last
    assert 204 in last


def test_a_crosswalk_that_only_crosses_a_cycle_track_is_not():
    """A pedestrian's crosswalk over a road and the cycle track beside it: the track meets
    it in the middle, not at an end."""
    ways = [
        placed(210, SIDEWALK, [(-50.0, 0.0), (0.0, 0.0)]),
        placed(211, CROSSWALK, [(0.0, 0.0), (0.0, 5.0), (0.0, 15.0), (0.0, 20.0)]),
        placed(212, SIDE_PATH, [(-100.0, 5.0), (0.0, 5.0), (100.0, 5.0)]),
        placed(213, {"highway": "secondary"}, [(-100.0, 15.0), (0.0, 15.0), (100.0, 15.0)]),
        placed(214, SIDEWALK, [(0.0, 20.0), (50.0, 20.0)]),
    ]
    assert sw.trail_crossings(ways) == set()


def test_a_trail_that_runs_on_past_its_crosswalk_is_found_where_links_is_not():
    """Little Falls' own case: the crosswalk leaves the path partway along (the path runs
    on), so the path is no dead end and `links` passes it by."""
    ways = little_falls()
    ways[0] = placed(200, SIDE_PATH, [(0.0, 0.0), (0.0, 100.0), (-60.0, 160.0)])
    assert 201 not in sw.links(ways)
    assert sw.trail_crossings(ways) == {201}


# --- Gap links (the owner, 2026-11-20) ----------------------------------------------------
#
# "Do a search for places that could match this and open them. This happens a lot." The
# shape is the one found by the Bethesda Trolley Trail (OSM 39941547): a cycleway that runs
# on, and a 35 m footway with no bicycle tag from it to a service road, the only join between
# them for hundreds of metres.


def spur(footway=None, far_join=None, length=35.0):
    """A north-south cycleway and a north-south service road `length` metres east of it,
    both running on, joined by a footway; `far_join` adds a street joining the two that
    many metres north."""
    north = [(0.0, far_join)] if far_join is not None else []
    ways = [
        placed(1, SIDE_PATH, [(0.0, -300.0), (0.0, 0.0), *north, (0.0, 300.0)]),
        placed(
            2,
            {"highway": "service"},
            [(length, -300.0), (length, 0.0), *[(length, n) for _e, n in north], (length, 300.0)],
        ),
        placed(3, footway or {"highway": "footway"}, [(0.0, 0.0), (length, 0.0)]),
    ]
    if far_join is not None:
        ways.append(placed(4, {"highway": "residential"}, [(0.0, far_join), (length, far_join)]))
    return ways


def test_a_short_footway_that_is_the_only_join_between_a_trail_and_a_road_is_a_gap_link():
    assert sw.gap_links(spur()) == {3}
    # Sidewalks and crosswalks close a gap as well; a bicycle tag is left alone.
    assert sw.gap_links(spur({"highway": "footway", "footway": "sidewalk"})) == {3}
    assert sw.gap_links(spur({"highway": "footway", "bicycle": "no"})) == set()
    # The trail runs on past the footway, so `links` (a dead end only) does not find it.
    assert 3 not in sw.links(spur())


def test_a_gap_the_network_joins_nearby_is_left_alone():
    # A street joins the two 100 m on: 100 + 35 + 100 m round, under GAP_DETOUR_M.
    assert sw.gap_links(spur(far_join=100.0)) == set()
    # 200 m on: 435 m round, over it.
    assert sw.gap_links(spur(far_join=200.0)) == {3}


def test_a_gap_link_is_short_needs_a_trail_and_is_never_closed():
    assert sw.gap_links(spur(length=sw.GAP_M + 5)) == set()
    roads = [
        (w, {"highway": "residential"}, n, c) if w == 1 else (w, t, n, c) for w, t, n, c in spur()
    ]
    assert sw.gap_links(roads) == set(), "a parking lot to a street is no gap link"
    assert sw.gap_links(spur(), closed={3}) == set()


def test_a_gap_link_reads_the_open_ways_coordinates_through_locate():
    ways = spur()
    bare = [(w, t, n, c if w == 3 else ()) for w, t, n, c in ways]
    assert sw.gap_links(bare, locate=lambda index: ways[index][3]) == {3}


def test_a_shortcut_across_one_trails_bend_is_no_gap_link():
    # A trail bends round in a U (two 200 m legs 40 m apart, joined 40 m round the bottom
    # by itself); a 40 m footway across the top meets only that one trail.
    ways = [
        placed(1, TRAIL, [(0.0, 0.0), (0.0, -200.0), (40.0, -200.0), (40.0, 0.0)]),
        placed(3, {"highway": "footway"}, [(0.0, 0.0), (40.0, 0.0)]),
    ]
    assert sw.gap_links(ways) == set()


def test_a_link_another_rule_opened_counts_as_a_nearby_join():
    # Two parallel connectors 20 m apart: once one is open, the other is no gap.
    ways = [
        placed(1, SIDE_PATH, [(0.0, -300.0), (0.0, 0.0), (0.0, 20.0), (0.0, 300.0)]),
        placed(
            2, {"highway": "service"}, [(35.0, -300.0), (35.0, 0.0), (35.0, 20.0), (35.0, 300.0)]
        ),
        placed(3, {"highway": "footway"}, [(0.0, 0.0), (35.0, 0.0)]),
        placed(6, {"highway": "footway"}, [(0.0, 20.0), (35.0, 20.0)]),
    ]
    assert sw.gap_links(ways) == {3, 6}
    assert sw.gap_links(ways, also_open={6}) == set()


def test_a_footway_with_one_end_at_a_trail_junction_and_the_other_loose_is_no_gap_link():
    ways = [
        placed(1, SIDE_PATH, [(0.0, -300.0), (0.0, 0.0)]),
        placed(2, SIDE_PATH, [(0.0, 0.0), (0.0, 300.0)]),
        placed(3, {"highway": "footway"}, [(0.0, 0.0), (35.0, 0.0)]),
    ]
    assert sw.gap_links(ways) == set()


# Delaware Ave NE between C and D Streets on the Capitol grounds (OSM, 2026-11-22): the
# avenue closed to public driving (297226539), its west walk open to bicycles (297230913), and a
# street the public drives (D Street NE, 911292852) the walk meets end on.
_DELAWARE = [(-77.00805, 38.89237), (-77.00771, 38.8936), (-77.00727, 38.89452)]
_WEST_WALK = [(-77.00771, 38.89369), (-77.00753, 38.89420), (-77.00735, 38.8947)]
_D_STREET = [(-77.00874, 38.8948), (-77.00718, 38.8948)]
_CLOSED_TAGS = {"highway": "residential", "access": "permissive", "motor_vehicle": "no"}
_WALK_TAGS = {"highway": "footway", "footway": "sidewalk", "bicycle": "yes"}


def _placed(osm_id, tags, coords):
    return (osm_id, tags, list(range(osm_id * 10, osm_id * 10 + len(coords))), coords)


def test_a_bicycle_open_sidewalk_of_a_street_closed_to_public_driving_is_priced_as_a_path():
    ways = [
        _placed(1, _CLOSED_TAGS, _DELAWARE),
        _placed(2, _WALK_TAGS, _WEST_WALK),
        _placed(3, {"highway": "tertiary", "name": "D Street Northeast"}, _D_STREET),
    ]
    assert sw.no_public_traffic_sidewalks(ways) == {2}


def test_a_sidewalk_beside_a_street_the_public_drives_keeps_the_sidewalk_price():
    driven = {"highway": "residential"}
    assert (
        sw.no_public_traffic_sidewalks(
            [_placed(1, driven, _DELAWARE), _placed(2, _WALK_TAGS, _WEST_WALK)]
        )
        == set()
    )
    # Beside a closed street and one the public drives (a split road): still a sidewalk.
    shifted = [(lon + 0.0001, lat) for lon, lat in _WEST_WALK]
    ways = [
        _placed(1, _CLOSED_TAGS, _DELAWARE),
        _placed(3, driven, shifted),
        _placed(2, _WALK_TAGS, _WEST_WALK),
    ]
    assert sw.no_public_traffic_sidewalks(ways) == set()


def test_a_bus_street_or_a_sidewalk_no_bicycle_tag_opens_is_left_alone():
    bus = {**_CLOSED_TAGS, "bus": "yes"}
    assert (
        sw.no_public_traffic_sidewalks(
            [_placed(1, bus, _DELAWARE), _placed(2, _WALK_TAGS, _WEST_WALK)]
        )
        == set()
    )
    untagged = {"highway": "footway", "footway": "sidewalk"}
    assert (
        sw.no_public_traffic_sidewalks(
            [_placed(1, _CLOSED_TAGS, _DELAWARE), _placed(2, untagged, _WEST_WALK)]
        )
        == set()
    )


def test_the_most_specific_motor_key_decides_whether_the_public_drives():
    def found(street):
        return sw.no_public_traffic_sidewalks(
            [_placed(1, street, _DELAWARE), _placed(2, _WALK_TAGS, _WEST_WALK)]
        )

    assert found({"highway": "service", "vehicle": "no", "motor_vehicle": "yes"}) == set()
    assert found({"highway": "service", "access": "no", "motorcar": "designated"}) == set()
    assert found({"highway": "service", "access": "yes", "motor_vehicle": "no"}) == {2}
    assert found({"highway": "service", "motor_vehicle": "no;destination"}) == {2}
    assert found({"highway": "pedestrian"}) == {2}


def test_a_footway_joining_two_streets_is_drawn_as_a_street_link():
    """Briggs Road, Glenmont (the owner's report): a walk joining the two ends of the street
    is drawn; one off a single street node, or ending at a parking lot, is not."""
    ways = [
        (1, {"highway": "residential"}, [10, 11]),
        (2, dict(SIDEWALK), [11, 12]),
        (3, {"highway": "residential"}, [12, 13]),
        # A walk in two pieces from a street to a parking lot's service road.
        (4, {"highway": "footway", "bicycle": "yes"}, [13, 20]),
        (5, {"highway": "footway", "bicycle": "yes"}, [20, 21]),
        (6, {"highway": "service"}, [21, 22]),
        # A walk from a street to a closed street.
        (7, {"highway": "footway", "bicycle": "yes"}, [10, 30]),
        (8, {"highway": "residential", "access": "private"}, [30, 31]),
    ]
    assert sw.street_links(ways, {2, 4, 5, 7}) == {2}
    assert sw.street_links(ways, set()) == set()


def test_roadless_sidewalks_feed_the_last_resort_rule():
    from pipeline.run import last_resort_sidewalks, roadless_sidewalks

    ways = [
        way(20, {"highway": "residential"}, [(-300.0, 0.0), (0.0, 0.0)]),
        way(21, dict(SIDEWALK), [(0.0, 0.0), (124.0, 0.0)]),
        way(22, {"highway": "residential"}, [(124.0, 0.0), (400.0, 0.0)]),
        way(23, dict(SIDEWALK), [(-280.0, 12.0), (-20.0, 12.0)]),
    ]
    roadless = roadless_sidewalks(ways, {21, 23}, set())
    assert roadless == {21}
    assert last_resort_sidewalks(ways, {}, {21, 23}, set(), roadless) == {23}


# The rater brief, 2026-11-26 ("Sidewalks where the law lets bikes ride them"): a sidewalk a
# rater rates below LTS 3 is the side path it is, priced as a path; a rater's level 4, a
# formula's rating, or no row at all leaves the sidewalk's price as it was.
def test_a_sidewalk_a_rater_rates_a_side_path_is_priced_as_a_path():
    from dataclasses import replace

    from pipeline import variants
    from pipeline.run import rated_sidepath_sidewalks, sidewalk_derived

    def rater(tier, half=False):
        return replace(
            _stress(tier, half), rule="override: stress adjustment 1", adjustment=object()
        )

    ratings = {
        1: rater(1, half=True),
        2: rater(2),
        3: rater(4),
        4: _stress(1),
        6: rater(2),
        7: rater(2),
        8: rater(5),
    }
    ways = [way(i, dict(SIDEWALK), [(0.0, 0.0), (0.0, 50.0)]) for i in (1, 2, 3, 4, 5, 6, 8)]
    ways.append(way(7, dict(CROSSWALK), [(0.0, 0.0), (0.0, 12.0)]))
    found = rated_sidepath_sidewalks(ways, ratings, {1, 2, 3, 4, 5, 7, 8})
    assert found == {1, 2}, "only ridden sidewalks, not a crosswalk, a rater rates below 3"
    assert sidewalk_derived(variants.Variant.STANDARD, 1, {1, 3}, {1, 3}, set(), found) == {
        "sidewalk": sw.SIDEPATH
    }
    assert sidewalk_derived(variants.Variant.STANDARD, 3, {1, 3}, {1, 3}, set(), found) == {
        "sidewalk": sw.LAST_RESORT
    }
    assert sidewalk_derived(variants.Variant.EBIKE, 1, {1}, set(), set(), found) == {}


# Ashburn Village Boulevard at Red Rum Drive (the owner: "Weird routing here"):
# the side path runs on past the corner, and a 4 m footway with no tags joins it to the
# signalized crosswalk over the road. In metres: the side path runs north up x=0, the join
# goes east from (0, 50) to (4, 50), and the crosswalk runs on east across the road at x=20.
PLAIN = {"highway": "footway"}


def ashburn(join=PLAIN, join_m=4.0, crosswalk=CROSSWALK, path=SIDE_PATH):
    return [
        placed(300, dict(path), [(0.0, 0.0), (0.0, 50.0), (0.0, 200.0)]),
        placed(301, dict(join), [(0.0, 50.0), (join_m, 50.0)]),
        placed(302, dict(crosswalk), [(join_m, 50.0), (20.0, 50.0), (80.0, 50.0)]),
        placed(303, {"highway": "secondary"}, [(20.0, -100.0), (20.0, 50.0), (20.0, 200.0)]),
    ]


def test_a_trails_short_join_to_a_crosswalk_is_a_stub():
    assert sw.stubs(ashburn()) == {301}
    assert sw.links(ashburn()) == {}, "the side path runs on: no dead end"
    assert sw.trail_crossings(ashburn()) == set(), "the crosswalk is longer than a link"


def test_a_stub_is_short_untagged_open_and_joins_a_trail_to_something_ridden():
    assert sw.stubs(ashburn(join_m=sw.STUB_M + 2)) == set(), "too long for a join"
    assert sw.stubs(ashburn(join={**PLAIN, "bicycle": "no"})) == set()
    assert sw.stubs(ashburn(), closed={301}) == set()
    assert sw.stubs(ashburn(path={"highway": "residential"})) == set(), "no trail at an end"
    assert sw.stubs(ashburn(crosswalk={**CROSSWALK, "bicycle": "no"})) == set(), (
        "nothing ridden beyond"
    )
    assert sw.stubs(ashburn(join=SIDEWALK)) == set(), "a sidewalk is ridden already"


def test_a_stub_never_joins_a_trail_to_a_road_or_driveway():
    for far in ({"highway": "service", "service": "driveway"}, {"highway": "secondary"}):
        ways = ashburn()
        ways[2] = placed(302, far, [(4.0, 50.0), (4.0, 100.0)])
        assert sw.stubs(ways) == set(), far


def test_a_stub_may_meet_a_sidewalk_part_way_along():
    ways = ashburn()
    ways[2] = placed(302, SIDEWALK, [(4.0, 0.0), (4.0, 50.0), (4.0, 100.0)])
    assert sw.stubs(ways) == {301}


def test_the_rebuild_rides_a_stub_as_a_link():
    ways = [
        way(osm_id, tags, [(e, n) for e, n in pts])
        for osm_id, tags, pts in (
            (300, SIDE_PATH, [(0.0, 0.0), (0.0, 50.0), (0.0, 200.0)]),
            (301, PLAIN, [(0.0, 50.0), (4.0, 50.0)]),
            (302, CROSSWALK, [(4.0, 50.0), (20.0, 50.0), (80.0, 50.0)]),
            (303, {"highway": "secondary"}, [(20.0, -100.0), (20.0, 50.0), (20.0, 200.0)]),
        )
    ]
    result = tc.closures(ways, {}, [])
    tc.add_sidewalk_rides(result, ways)
    assert 301 in result.sidewalk_links
