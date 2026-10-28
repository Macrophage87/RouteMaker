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
