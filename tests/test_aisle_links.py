"""Parking aisles and driveways where a trail ends (routemaker.aisle_links).

The owner's report of 2026-10-26 on Beach Drive at the Maryland line: the Rock Creek
Trail starts in a small lot, joined to Beach Drive only by two parking aisles of about
60 ft (18 m) together, and a ride north stayed on the road beside the trail. The shapes
below are that one, in metres east and north of a point by the lot. The remap's side is
checked in tests/lua/test_remap.lua and tests/lua/test_graph_entry.lua.
"""

from __future__ import annotations

import math

from pipeline import trail_closures as tc
from pipeline.extract import Way
from routemaker import aisle_links as al

LON0, LAT0 = -77.0532, 38.9864


def at(east: float, north: float) -> tuple[float, float]:
    lat = LAT0 + math.degrees(north / 6_371_008.8)
    lon = LON0 + math.degrees(east / (6_371_008.8 * math.cos(math.radians(LAT0))))
    return (lon, lat)


def placed(osm_id, tags, points):
    """(id, tags, node ids, coordinates): node ids are the points themselves, so ways
    that share a point share a node."""
    nodes = [int(e * 1000) * 1_000_000 + int(n * 1000) for e, n in points]
    return (osm_id, tags, nodes, [at(e, n) for e, n in points])


TRAIL = {"highway": "cycleway", "bicycle": "designated", "foot": "designated"}
AISLE = {"highway": "service", "service": "parking_aisle"}
ROAD = {"highway": "pedestrian", "bicycle": "designated", "motor_vehicle": "no"}


def beach_drive(aisle_tags=AISLE, gap=13.0, trail_tags=TRAIL, extra=(), road=ROAD):
    """The trail runs west from its end at (0, 0); two aisles lead `gap` metres south
    to Beach Drive, which runs east-west."""
    return [
        placed(1, dict(trail_tags), [(0.0, 0.0), (-300.0, 20.0)]),
        placed(2, dict(aisle_tags), [(0.0, 0.0), (4.0, -gap / 2)]),
        placed(3, dict(aisle_tags), [(4.0, -gap / 2), (6.0, -gap)]),
        placed(4, dict(road), [(-300.0, -gap), (6.0, -gap), (300.0, -gap)]),
        *extra,
    ]


def test_the_trail_that_starts_in_a_parking_lot_gets_its_aisles():
    assert al.links(beach_drive()) == {2, 3}


def test_a_gap_longer_than_the_cap_is_no_link():
    assert al.links(beach_drive(gap=al.GAP_M + 10)) == set()


def test_an_aisle_that_already_grants_bicycles_is_left_to_the_remap():
    # #197's own rule routes it; a bicycle tag also makes it no candidate here.
    assert al.links(beach_drive({**AISLE, "bicycle": "yes"})) == set()


def test_a_private_lot_keeps_its_flag():
    for restriction in ({"access": "private"}, {"access": "customers"}, {"vehicle": "private"}):
        assert al.links(beach_drive({**AISLE, **restriction})) == set(), restriction


def test_a_trail_that_is_no_dead_end_is_not_linked():
    # Another bicycle-open way meets the trail's end: it is joined already.
    side_path = placed(5, TRAIL, [(0.0, 0.0), (50.0, 0.0)])
    assert al.links(beach_drive(extra=(side_path,))) == set()


def test_a_road_that_ends_in_a_lot_is_not_a_trail():
    # A street that ends in a parking lot is how most lots are reached: not a link.
    street = {"highway": "residential"}
    assert al.links(beach_drive(trail_tags=street)) == set()


def test_a_closed_trail_is_not_linked():
    assert al.links(beach_drive(), closed={1}) == set()


def test_a_street_counts_as_the_way_reached():
    assert al.links(beach_drive(road={"highway": "residential"})) == {2, 3}


def test_a_long_aisle_is_never_opened():
    # The gap is short, but the second aisle runs on far past the road: the remap would
    # change the whole way.
    ways = beach_drive()
    ways[2] = placed(3, dict(AISLE), [(4.0, -6.5), (6.0, -13.0), (6.0, -13.0 - al.WAY_MAX_M)])
    assert al.links(ways) == set()
    ways[2] = placed(3, dict(AISLE), [(4.0, -6.5), (6.0, -13.0), (6.0, -13.0 - al.WAY_MAX_M / 2)])
    assert al.links(ways) == {2, 3}, "the same shape within the cap is a link"


def test_driveways_and_drive_throughs_are_not():
    # Most private driveways carry no access tag.
    for service in ("driveway", "drive-through"):
        assert al.links(beach_drive({**AISLE, "service": service})) == set(), service


def test_a_closed_aisle_or_an_area_is_not_a_link():
    assert al.links(beach_drive(), closed={2}) == set()
    assert al.links(beach_drive({**AISLE, "area": "yes"})) == set()
    assert al.links(beach_drive({**AISLE, "bicycle:conditional": "no @ (Sa-Su)"})) == set()


def test_the_rebuild_finds_them_after_the_closures():
    ways = [
        Way(osm_id, tags, list(nodes), list(coords), list(range(len(nodes))))
        for osm_id, tags, nodes, coords in beach_drive()
    ]
    result = tc.TrailClosures()
    tc.add_aisle_links(result, ways)
    assert result.aisle_links == {2, 3}
    closed = tc.TrailClosures(reasons={4: "military"})
    tc.add_aisle_links(closed, ways)
    assert closed.aisle_links == set(), "never a link onto a way a rule closes"
