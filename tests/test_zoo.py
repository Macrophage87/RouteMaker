"""The National Zoo closure and its destination-only spur (OWNER-DECISIONS 291(4))."""

from __future__ import annotations

from routemaker import zoo

INSIDE = (-77.0495, 38.9290)
OUTSIDE = (-77.0300, 38.9000)


def line(lon, lat):
    return [(lon, lat), (lon + 0.0001, lat + 0.0001)]


def test_a_footway_inside_is_closed_outside_is_not():
    tags = {"highway": "footway", "bicycle": "no"}
    assert zoo.closed_way(1, tags, line(*INSIDE))
    assert not zoo.closed_way(1, tags, line(*OUTSIDE))


def test_the_zoo_roads_are_closed():
    for highway in ("unclassified", "service", "pedestrian", "path"):
        assert zoo.closed_way(2, {"highway": highway}, line(*INSIDE)), highway


def test_public_streets_and_the_signed_cycleway_stay_open():
    for highway in ("primary", "secondary", "tertiary", "residential", "tertiary_link"):
        assert not zoo.closed_way(3, {"highway": highway}, line(*INSIDE)), highway
    trail = {"highway": "cycleway", "bicycle": "designated"}
    assert not zoo.closed_way(4, trail, line(*INSIDE))
    assert not zoo.closed_way(4, {"highway": "cycleway", "bicycle": "yes"}, line(*INSIDE))
    assert zoo.closed_way(4, {"highway": "cycleway"}, line(*INSIDE))


def test_the_spur_is_not_closed_and_is_named_by_id():
    spur = zoo.spur_ways()
    assert {50524918, 183192886, 1244165507} <= spur
    assert len(spur) == 7
    for way_id in spur:
        assert not zoo.closed_way(way_id, {"highway": "footway", "bicycle": "no"}, line(*INSIDE))


def test_a_destination_inside_goes_to_the_racks():
    assert zoo.redirect(*INSIDE) == zoo.racks()
    assert zoo.redirect(*OUTSIDE) is None
    assert zoo.contains(zoo.racks())


def test_the_fixture_names_the_racks_node():
    spec = zoo.access()["spur"]["racks"]
    assert spec["node"] == 9827008403
    assert "bicycle_parking" in spec["tags"]
