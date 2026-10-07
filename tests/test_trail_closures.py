"""The rebuild-side orchestration of the NO-BIKE-PATHS closures."""

from __future__ import annotations

from pipeline import trail_closures as tc
from pipeline.extract import Way
from routemaker.trailaccess import WayRoutes
from routemaker.zoo import spur_ways

# Inside the Zoo outline and outside it.
ZOO = (-77.0495, 38.9290)
ELSEWHERE = (-77.20, 38.80)


def way(osm_id, tags, origin=ELSEWHERE, nodes=None, length_deg=0.0005):
    lon, lat = origin
    coords = [(lon, lat), (lon + length_deg, lat)]
    return Way(osm_id, tags, nodes or [osm_id * 10, osm_id * 10 + 1], coords, [0, 1])


def run(ways, routes=None, parks=()):
    return tc.closures(ways, routes or {}, list(parks))


def test_each_rule_gives_its_reason_and_the_rest_are_left_alone():
    ways = [
        way(1, {"highway": "path", "surface": "dirt"}),
        way(2, {"highway": "path", "access": "private"}),
        way(3, {"highway": "path", "surface": "asphalt"}),
        way(4, {"highway": "path", "bicycle": "yes", "surface": "dirt"}),
        way(5, {"highway": "cycleway", "surface": "dirt"}),
        way(6, {"highway": "path", "surface": "dirt", "mtb:scale": "2"}),
    ]
    result = run(ways)
    assert result.reasons == {
        1: "natural_surface",
        2: "private",
        4: "mtb",
        6: "singletrack",
    }
    assert result.mtb_only() == {4, 6}, "a future MTB mode rides both"


def test_an_override_that_reopens_a_mountain_bike_trail_opens_it_and_ends_mtb_only():
    mtb = {"highway": "path", "bicycle": "yes", "surface": "dirt"}
    # Way 7's override wrote bicycle=yes; way 8 carries the same tags from OSM, with
    # no override, and stays closed as the mountain-bike class.
    result = tc.closures([way(7, dict(mtb)), way(8, dict(mtb))], {}, [], reopened={7})
    assert 7 not in result.reasons, "the owner reopened it: open, and drawn to ride"
    assert result.reasons == {8: "mtb"}
    assert result.mtb_only() == {8}


def test_hiking_routes_and_national_bicycle_routes_come_from_the_relations():
    ways = [way(10, {"highway": "path"}), way(11, {"highway": "path", "surface": "dirt"})]
    routes = {
        10: WayRoutes(hiking=True),
        11: WayRoutes(bicycle_networks=frozenset({"ncn"})),
    }
    assert run(ways, routes).reasons == {10: "hiking_route"}


def test_the_zoo_is_closed_except_its_spur_the_streets_and_the_cycleway():
    spur = sorted(spur_ways())[0]
    ways = [
        way(20, {"highway": "footway", "bicycle": "no"}, ZOO),
        way(21, {"highway": "service"}, ZOO),
        way(22, {"highway": "tertiary"}, ZOO),
        way(23, {"highway": "cycleway", "bicycle": "designated"}, ZOO),
        way(spur, {"highway": "footway", "bicycle": "no"}, ZOO),
    ]
    result = run(ways)
    assert result.reasons == {20: "zoo", 21: "zoo"}
    assert result.destination_only == {spur}


def test_a_zoo_way_is_closed_whatever_it_would_otherwise_be():
    result = run([way(30, {"highway": "path", "surface": "dirt", "mtb:scale": "3"}, ZOO)])
    assert result.reasons == {30: "zoo"}


def test_parks_close_plain_paths_only_inside():
    inside = way(40, {"highway": "path"}, (-77.5, 39.5))
    outside = way(41, {"highway": "path"}, (-77.1, 39.1))
    park = (
        (-77.6, 39.4, -77.4, 39.6),
        [[(-77.6, 39.4), (-77.4, 39.4), (-77.4, 39.6), (-77.6, 39.6)]],
        [],
    )
    result = run([inside, outside], parks=[park])
    assert result.reasons == {40: "park_path"}


def test_short_dismount_connectors_stay_flagged_and_long_ones_close():
    dismount = {"highway": "footway", "bicycle": "dismount"}
    short = way(50, dismount, length_deg=0.0005)  # about 40 m
    long_ = way(51, dismount, nodes=[900, 901], length_deg=0.004)  # about 350 m
    result = run([short, long_])
    assert result.walk_bike == {50}
    assert result.reasons == {51: "dismount"}


def test_the_offroad_graph_keeps_only_the_mtb_class_open():
    assert tc.OFFROAD_KEEPS == {"mtb"}
    assert tc.MTB_ONLY == {"mtb", "singletrack"}
    assert "zoo" not in tc.OFFROAD_KEEPS and "private" not in tc.OFFROAD_KEEPS


def test_park_rules_hook_is_empty_until_a_compendium_is_read():
    assert dict(tc.PARK_RULES) == {}
