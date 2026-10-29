"""Short links the trail rules close, reopened (routemaker.short_links).

The owner, 2026-10-28, after the Airpark Road connector to the Percheron Trail was found
closed to every ride type but Mountain Bike, chose "Ride paved/unknown, walk dirt". The
shapes below are in metres east and north of a point; a trail runs east-west at north 0 and
a street at north -gap, joined by the link. The remap's side is checked in
tests/lua/test_remap.lua and tests/lua/test_graph_entry.lua.
"""

from __future__ import annotations

import math

from pipeline import trail_closures as tc
from pipeline.extract import Way
from routemaker import short_links as sl
from routemaker import trailaccess

LON0, LAT0 = -77.1404, 39.1549

TRAIL = {"highway": "cycleway", "bicycle": "designated", "surface": "asphalt"}
STREET = {"highway": "residential", "name": "Bullard Circle"}
PARK_PATH = {"highway": "path"}
DIRT = {"highway": "path", "bicycle": "yes", "surface": "unpaved"}


def at(east: float, north: float) -> tuple[float, float]:
    lat = LAT0 + math.degrees(north / 6_371_008.8)
    lon = LON0 + math.degrees(east / (6_371_008.8 * math.cos(math.radians(LAT0))))
    return (lon, lat)


def placed(osm_id, tags, points):
    """(id, tags, node ids, coordinates): ways that share a point share a node."""
    nodes = [int(e * 1000) * 1_000_000 + int(n * 1000) for e, n in points]
    return (osm_id, tags, nodes, [at(e, n) for e, n in points])


def connector(link=PARK_PATH, gap=40.0, pieces=1, street=STREET, extra=()):
    """The trail (1) and the street (9), with `pieces` link ways (2, 3, ...) between them,
    leaving the trail mid-way: no dead end anywhere."""
    step = gap / pieces
    return [
        placed(1, dict(TRAIL), [(-300.0, 0.0), (0.0, 0.0), (300.0, 0.0)]),
        *(
            placed(2 + i, dict(link), [(0.0, -i * step), (0.0, -(i + 1) * step)])
            for i in range(pieces)
        ),
        placed(9, dict(street), [(-300.0, -gap), (0.0, -gap), (300.0, -gap)]),
        *extra,
    ]


def reasons_of(ways, park=True):
    return {
        osm_id: reason
        for osm_id, tags, _nodes, _coords in ways
        if (reason := trailaccess.verdict(tags, in_park=park)) is not None
    }


def links(ways, reasons=None):
    return sl.links(ways, reasons_of(ways) if reasons is None else reasons, tc.SHORT_LINK_REOPENS)


def test_an_untagged_park_path_off_a_street_is_ridden():
    ways = connector()
    assert reasons_of(ways) == {2: trailaccess.PARK_PATH}
    assert links(ways) == {2: False}


def test_the_airpark_shape_is_walked():
    # bicycle=yes + surface=unpaved is the mountain-bike class; two pieces, one a tunnel.
    ways = connector({**DIRT}, gap=60.0, pieces=2)
    assert reasons_of(ways) == {2: trailaccess.MTB, 3: trailaccess.MTB}
    assert links(ways) == {2: True, 3: True}


def test_a_worn_dirt_path_is_walked():
    assert links(connector({"highway": "path", "surface": "dirt"})) == {2: True}


def test_a_link_longer_than_the_cap_stays_closed():
    assert links(connector(gap=sl.CHAIN_MAX_M + 10, pieces=2)) == {}


def test_a_dead_end_stub_is_no_link():
    ways = connector(extra=[placed(5, dict(PARK_PATH), [(100.0, 0.0), (100.0, 30.0)])])
    assert 5 not in links(ways)


def test_a_link_between_two_service_roads_is_not_one():
    lot = {"highway": "service", "service": "parking_aisle"}
    ways = [
        placed(1, dict(lot), [(-30.0, 0.0), (0.0, 0.0)]),
        placed(2, dict(PARK_PATH), [(0.0, 0.0), (0.0, -20.0)]),
        placed(9, dict(lot), [(0.0, -20.0), (30.0, -20.0)]),
    ]
    assert links(ways) == {}


def test_other_closures_are_never_lifted():
    ways = connector()
    for reason in (trailaccess.PRIVATE, trailaccess.INFORMAL, "military", "singletrack", "golf"):
        assert links(ways, {2: reason}) == {}


def test_a_hiking_rating_beyond_t1_stays_closed():
    tags = {"highway": "path", "sac_scale": "mountain_hiking"}
    assert links(connector(tags), {2: trailaccess.SAC_SCALE}) == {}
    assert links(connector({"highway": "path", "sac_scale": "hiking"})) == {2: True}


def test_a_link_onto_a_closed_street_is_none():
    ways = connector()
    assert links(ways, {2: trailaccess.PARK_PATH, 9: "agency_prohibited"}) == {}


def test_a_dismount_way_keeps_its_own_rule():
    tags = {"highway": "path", "bicycle": "dismount", "surface": "dirt"}
    assert links(connector(tags), {2: trailaccess.MTB}) == {}


def as_ways(placed_ways):
    return [
        Way(osm_id, tags, list(nodes), list(coords), list(range(len(nodes))))
        for osm_id, tags, nodes, coords in placed_ways
    ]


def test_the_rebuild_lifts_the_reason_and_walks_dirt():
    result = tc.TrailClosures(reasons={2: trailaccess.MTB, 3: trailaccess.MTB})
    tc.add_short_links(result, as_ways(connector({**DIRT}, gap=60.0, pieces=2)))
    assert result.reasons == {}
    assert result.short_links == {2: True, 3: True}
    assert result.walk_bike == {2, 3}
    assert result.short_links_mtb == {2, 3}, "the off-road graphs keep riding them"


def test_the_rebuild_rides_a_park_path():
    result = tc.TrailClosures(reasons={2: trailaccess.PARK_PATH})
    tc.add_short_links(result, as_ways(connector()))
    assert result.reasons == {}
    assert result.short_links == {2: False}
    assert result.walk_bike == set()
    assert result.short_links_mtb == set()


def test_a_working_sites_closure_never_opens_what_its_own_tags_close():
    for tags in (
        {"highway": "path", "bicycle": "no", "surface": "dirt"},
        {"highway": "footway", "access": "private", "surface": "dirt"},
        {"highway": "track", "access": "private"},
        {"highway": "footway"},  # upstream closes it by class: the sidewalk rules' own
    ):
        assert links(connector(tags), {2: "works"}) == {}, tags


def test_a_works_or_track_link_open_by_its_tags_is_ridden():
    assert links(connector({"highway": "path"}), {2: "works"}) == {2: False}
    assert links(connector({"highway": "track", "surface": "gravel"}), {2: "track"}) == {2: False}
    assert links(connector({"highway": "track", "tracktype": "grade5"}), {2: "track"}) == {2: True}


def test_a_rough_path_is_walked():
    tags = {"highway": "path", "smoothness": "very_bad"}
    assert links(connector(tags), {2: trailaccess.PARK_PATH}) == {2: True}


def test_how_a_mapper_split_a_long_way_does_not_matter():
    # A 400 m dirt trail leaves the link's middle node: one way or four, the group is too
    # long, so the link stays closed.
    def ways(pieces):
        trail = (
            [
                placed(20 + i, dict(DIRT), [(i * 100.0, -20.0), ((i + 1) * 100.0, -20.0)])
                for i in range(pieces)
            ]
            if pieces > 1
            else [placed(20, dict(DIRT), [(0.0, -20.0), (400.0, -20.0)])]
        )
        return connector(DIRT, gap=40.0, pieces=2, extra=trail)

    assert links(ways(1)) == {}
    assert links(ways(4)) == {}
