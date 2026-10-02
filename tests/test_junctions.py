"""What is at each junction of a route (`core.junctions`): the roads and the
right of way from the router's `/locate`, the stress of each road from the
segment table, and the events the model makes of them (OWNER-DECISIONS items
165 to 172, 185).

The `/locate` answers here are cut down from what the live standard router
returned on 2026-10-02 at the junctions the round-1 review named (Rockville
Pike past its turn channel, 16th St NW past an inbound-only merge, Blair Circle
with a signal on the merging approach), keeping the fields this module reads:
`edge_id`, `percent_along`, `heading`, `correlated_lon/lat`, and of `edge` its
`end_node`, `classification`, `access.car` and the stop, yield and signal
flags; of `edge_info` the `way_id` and `names`; and the node list.

The segment table is real, because the road query is a PostGIS one.
"""

from __future__ import annotations

import pytest
from django.db import connection

from core import junctions
from routemaker import intersections as model
from routemaker.intersections import Control, Movement, Road
from routemaker.trace_junctions import RawJunction

db = pytest.mark.django_db(transaction=True)

LON, LAT = -77.0, 38.9


def edge(
    edge_id,
    way,
    end_node,
    along,
    heading,
    *,
    car=True,
    use="road",
    link=False,
    names=(),
    signal=False,
    stop=False,
    yld=False,
    at=(LON, LAT),
    distance=0.0,
):
    """One `/locate` edge entry. `along` 1.0 is an edge arriving at the node
    (its end node is the node), 0.0 one leaving it."""
    return {
        "edge_id": {"value": edge_id},
        "percent_along": along,
        "heading": heading,
        "distance": distance,
        "correlated_lon": at[0],
        "correlated_lat": at[1],
        "edge": {
            "end_node": {"value": end_node},
            "classification": {"use": use, "link": link},
            "access": {"car": car},
            "traffic_signal": signal,
            "stop_sign": stop,
            "yield_sign": yld,
        },
        "edge_info": {"way_id": way, "names": list(names)},
    }


def node(node_id, signal=False, at=(LON, LAT)):
    return {"node_id": {"value": node_id}, "traffic_signal": signal, "lon": at[0], "lat": at[1]}


def answer(edges, nodes=()):
    return {"edges": list(edges), "nodes": list(nodes)}


def raw(**fields) -> RawJunction:
    base = {
        "m": 100.0,
        "lon": LON,
        "lat": LAT,
        "in_edge_id": 1,
        "in_way": 10,
        "out_way": 10,
        "movement": Movement.STRAIGHT,
        "in_use": "road",
        "out_use": "road",
        "others": (("road", False), ("road", False)),
        "in_class": "residential",
        "out_class": "residential",
        "other_classes": ("primary", "primary"),
        "out_edge_id": 2,
        "in_heading": 90.0,
        "out_heading": 90.0,
    }
    return RawJunction(**(base | fields))


# A quiet street (way 10) running west to east through the node N=100, and a
# two-way arterial (way 20) north to south through it.
N = 100


def crossroads(**flags):
    """The rider east along way 10 across way 20. `flags` puts stop or signal
    flags on the arriving edges: in=..., north=..., south=..."""
    f = {k: dict(v) for k, v in flags.items()}
    return answer(
        [
            edge(1, 10, N, 1.0, 90.0, **f.get("in", {})),  # arriving from the west
            edge(3, 10, 900, 0.0, 270.0),  # leaving west
            edge(2, 10, 901, 0.0, 90.0),  # leaving east (the route's way out)
            edge(4, 10, N, 1.0, 270.0, **f.get("east", {})),  # arriving from the east
            edge(5, 20, 902, 0.0, 0.0, names=["Main St"]),  # leaving north
            edge(6, 20, N, 1.0, 180.0, names=["Main St"], **f.get("north", {})),
            edge(7, 20, 903, 0.0, 180.0, names=["Main St"]),  # leaving south
            edge(8, 20, N, 1.0, 0.0, names=["Main St"], **f.get("south", {})),
        ],
        [node(N)],
    )


class TestTheNode:
    def test_the_arms_and_which_is_the_riders(self) -> None:
        found = junctions.node_from_locate(crossroads(), raw())
        assert found is not None
        assert {(a.way_id, a.heading) for a in found.arms} == {
            (10, 270.0),
            (10, 90.0),
            (20, 0.0),
            (20, 180.0),
        }
        assert (found.in_arm.way_id, found.in_arm.heading) == (10, 270.0)
        assert (found.out_arm.way_id, found.out_arm.heading) == (10, 90.0)
        assert all(a.into and a.out_of for a in found.arms), "every arm is two-way"

    def test_an_answer_without_the_riders_edge_is_another_node(self) -> None:
        """Review r1, B2a: then nothing in it is this junction's."""
        assert junctions.node_from_locate(crossroads(), raw(in_edge_id=77)) is None
        assert junctions.node_from_locate({}, raw()) is None
        assert junctions.node_from_locate(crossroads(), raw(in_edge_id=None)) is None

    def test_the_riders_edge_must_arrive_at_the_node(self) -> None:
        """Found leaving a node, the in-edge is at its other end: not this node."""
        leaving = answer([edge(1, 10, 900, 0.0, 90.0)], [node(N)])
        assert junctions.node_from_locate(leaving, raw()) is None

    def test_a_node_on_two_levels_of_the_hierarchy_is_one_node(self) -> None:
        """Measured on Rockville Pike at Dodge St: the primary road's edges end at
        the level 0 node and the tertiary cross street's at the level 1 node, at
        one point, both listed by /locate."""
        level0, level1 = 1361068448456, 340074540657
        found = junctions.node_from_locate(
            answer(
                [
                    edge(1, 10, level0, 1.0, 132.0),
                    edge(2, 11, 905, 0.0, 132.3),
                    edge(5, 20, 906, 0.0, 29.4, names=["Dodge Street"]),
                    edge(6, 20, level1, 1.0, 209.4, names=["Dodge Street"], signal=True),
                    edge(7, 21, 907, 0.0, 205.1, names=["Richard Montgomery Drive"]),
                    edge(8, 21, level1, 1.0, 25.1, names=["Richard Montgomery Drive"]),
                ],
                [node(level0, signal=True), node(level1, signal=True)],
            ),
            raw(in_heading=132.0, out_heading=132.3, out_way=11),
        )
        assert {a.way_id for a in found.others} == {20, 21}
        assert next(a for a in found.others if a.way_id == 20).signal

    def test_a_neighbouring_node_inside_the_radius_is_not_this_one(self) -> None:
        """Measured at Blair Circle: with a 1 m radius /locate also listed a node
        4.6 m away and its arriving edges, one with a signal. They are not here."""
        near = (LON + 0.00004, LAT + 0.00003)
        found = junctions.node_from_locate(
            answer(
                [
                    edge(1, 10, N, 1.0, 90.0),
                    edge(2, 10, 901, 0.0, 90.0),
                    edge(9, 30, 555, 1.0, 88.5, signal=True, at=near, distance=4.6),
                    edge(10, 31, 555, 1.0, 1.2, at=near, distance=4.6),
                ],
                [node(N), node(555, at=near)],
            ),
            raw(),
        )
        assert {a.way_id for a in found.arms} == {10}
        assert junctions.control_of(found) is Control.NONE

    def test_a_one_way_arm_can_be_driven_one_way_only(self) -> None:
        found = junctions.node_from_locate(
            answer(
                [
                    edge(1, 10, N, 1.0, 0.0),
                    edge(2, 11, 901, 0.0, 13.3),
                    # Arriving only: a one-way merging in.
                    edge(9, 12, N, 1.0, 166.4),
                    # The reverse of the in-edge: two-way.
                    edge(3, 10, 900, 0.0, 180.0),
                ],
                [node(N)],
            ),
            raw(in_heading=0.0, out_heading=13.3, out_way=11),
        )
        merge = next(a for a in found.arms if a.way_id == 12)
        assert merge.into and not merge.out_of
        assert found.in_arm.into and found.in_arm.out_of

    def test_a_car_free_edge_drives_nothing(self) -> None:
        found = junctions.node_from_locate(
            answer(
                [
                    edge(1, 10, N, 1.0, 90.0),
                    edge(2, 10, 901, 0.0, 90.0),
                    edge(9, 40, 902, 0.0, 0.0, car=False, use="cycleway"),
                ],
                [node(N)],
            ),
            raw(),
        )
        path = next(a for a in found.arms if a.way_id == 40)
        assert not path.into and not path.out_of and not path.is_road

    def test_the_way_out_by_its_way_and_heading_when_its_edge_is_missing(self) -> None:
        found = junctions.node_from_locate(
            crossroads(), raw(out_edge_id=None, out_way=20, out_heading=5.0)
        )
        assert (found.out_arm.way_id, found.out_arm.heading) == (20, 0.0)


class TestSides:
    def test_a_crossroads_has_the_cross_road_on_both_sides(self) -> None:
        found = junctions.node_from_locate(crossroads(), raw())
        left, right = junctions.sides(found, raw())
        assert [a.heading for a in left] == [0.0]
        assert [a.heading for a in right] == [180.0]
        one, other = junctions.crossing_sides(found, raw())
        assert {a.way_id for a in one + other} == {20}

    def test_a_side_road_on_one_side_is_not_crossed(self) -> None:
        """A T-junction: the rider on the through road crosses nothing."""
        tee = answer(
            [
                edge(1, 10, N, 1.0, 90.0),
                edge(2, 10, 901, 0.0, 90.0),
                edge(5, 20, 902, 0.0, 180.0),
                edge(8, 20, N, 1.0, 0.0),
            ],
            [node(N)],
        )
        found = junctions.node_from_locate(tee, raw())
        assert junctions.crossing_sides(found, raw()) is None

    def test_a_left_turn_crosses_what_is_on_its_right(self) -> None:
        found = junctions.node_from_locate(
            crossroads(), raw(movement=Movement.LEFT, out_edge_id=5, out_way=20, out_heading=0.0)
        )
        one, other = junctions.crossing_sides(
            found, raw(movement=Movement.LEFT, out_edge_id=5, out_way=20, out_heading=0.0)
        )
        # Ahead (way 10 east) and the far side (way 20 south).
        assert {(a.way_id, a.heading) for a in one} == {(10, 90.0), (20, 180.0)}
        assert other == []

    def test_a_right_turn_crosses_nothing(self) -> None:
        right = raw(movement=Movement.RIGHT, out_edge_id=7, out_way=20, out_heading=180.0)
        found = junctions.node_from_locate(crossroads(), right)
        assert junctions.crossing_sides(found, right) is None

    def test_turn_channels_and_ramps_are_never_crossed_roads(self) -> None:
        """Review r1, B1: Rockville Pike past its turn channel (measured)."""
        pike = answer(
            [
                edge(1, 10, N, 1.0, 112.3, use="turn_channel", link=True),
                edge(2, 11, 901, 0.0, 124.7, names=["Rockville Pike"]),
                edge(9, 11, N, 1.0, 130.7, names=["Rockville Pike"]),
                edge(12, 13, 909, 0.0, 300.0, use="ramp", link=True),
                edge(13, 13, N, 1.0, 290.0, use="ramp", link=True),
            ],
            [node(N)],
        )
        at = raw(in_heading=112.3, out_heading=124.7, out_way=11)
        found = junctions.node_from_locate(pike, at)
        assert all(not a.is_road for a in found.others if a.way_id == 13)
        assert any(a.is_link for a in found.others)


class TestControl:
    def test_a_signal_at_the_node(self) -> None:
        found = junctions.node_from_locate(
            answer(crossroads()["edges"], [node(N, signal=True)]), raw()
        )
        assert junctions.control_of(found) is Control.SIGNAL

    def test_a_signal_on_the_riders_approach(self) -> None:
        found = junctions.node_from_locate(crossroads(**{"in": {"signal": True}}), raw())
        assert junctions.control_of(found) is Control.SIGNAL

    def test_a_signal_on_a_cross_approach_is_a_signal(self) -> None:
        """Review r1, B2c: Blair Circle, the signal on the merging approach."""
        found = junctions.node_from_locate(crossroads(north={"signal": True}), raw())
        assert junctions.control_of(found) is Control.SIGNAL

    def test_a_stop_on_the_riders_approach(self) -> None:
        found = junctions.node_from_locate(crossroads(**{"in": {"stop": True}}), raw())
        assert junctions.control_of(found) is Control.STOP
        yielding = junctions.node_from_locate(crossroads(**{"in": {"yld": True}}), raw())
        assert junctions.control_of(yielding) is Control.STOP

    def test_a_stop_for_the_cross_traffic(self) -> None:
        found = junctions.node_from_locate(crossroads(north={"stop": True}), raw())
        assert junctions.control_of(found) is Control.CROSS_STOP

    def test_stops_on_both(self) -> None:
        found = junctions.node_from_locate(
            crossroads(**{"in": {"stop": True}, "south": {"yld": True}}), raw()
        )
        assert junctions.control_of(found) is Control.ALL_STOP

    def test_oncoming_traffic_on_the_riders_road_is_not_cross_traffic(self) -> None:
        found = junctions.node_from_locate(crossroads(east={"stop": True}), raw())
        assert junctions.control_of(found) is Control.NONE

    def test_a_leaving_edges_flags_are_its_far_ends(self) -> None:
        """Review r1, B2b: an outbound edge's stop flag is at the next node."""
        base = crossroads()
        for e in base["edges"]:
            if e["percent_along"] == 0.0:
                e["edge"]["stop_sign"] = True
                e["edge"]["traffic_signal"] = True
        found = junctions.node_from_locate(base, raw())
        assert junctions.control_of(found) is Control.NONE

    def test_no_node_no_control(self) -> None:
        assert junctions.control_of(None) is Control.NONE


class TestNodesAt:
    def test_batches_of_fifty_with_a_radius(self) -> None:
        raws = [raw(lon=LON + i * 0.001) for i in range(120)]
        asked = []

        def locate(payload: dict) -> list[dict]:
            asked.append(payload)
            return [crossroads() for _ in payload["locations"]]

        found = junctions.nodes_at(raws, locate)
        assert [len(p["locations"]) for p in asked] == [50, 50, 20]
        assert all(p["verbose"] and p["costing"] == "bicycle" for p in asked)
        assert asked[0]["locations"][1] == {
            "lon": raws[1].lon,
            "lat": raws[1].lat,
            "radius": junctions.LOCATE_RADIUS_M,
        }
        assert sorted(found) == list(range(120))

    def test_a_batch_the_router_will_not_answer_leaves_its_junctions_unknown(self) -> None:
        calls = []

        def locate(payload: dict):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("down")
            return [crossroads() for _ in payload["locations"]]

        raws = [raw()] * 60
        found = junctions.nodes_at(raws, locate)
        assert sorted(found) == list(range(50, 60)), "the next batch is still asked"

    def test_no_junctions_no_call(self) -> None:
        def locate(payload: dict):
            raise AssertionError("asked")

        assert junctions.nodes_at([], locate) == {}


def line(*points) -> str:
    return "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in points) + ")"


@pytest.fixture
def grid(segment_schemas):
    live, _staging = segment_schemas
    rows = [
        # way, ordinal, tier, geometry, speed, lanes, oneway, aadt
        (10, 0, 2, line((LON - 0.002, LAT), (LON, LAT)), 25, 1, False, None),
        (10, 1, 2, line((LON, LAT), (LON + 0.002, LAT)), 25, 1, False, None),
        (20, 0, 4, line((LON, LAT - 0.002), (LON, LAT)), 40, 2, False, 22000),
        (20, 1, 4, line((LON, LAT), (LON, LAT + 0.002)), 40, 2, False, 22000),
        # A sidepath three metres from the arterial: no edge at the node.
        (
            30,
            0,
            1,
            line((LON + 0.00003, LAT - 0.002), (LON + 0.00003, LAT + 0.002)),
            None,
            None,
            None,
            None,
        ),
        # A road passing under the node on a different level, 1 m away.
        (
            50,
            0,
            4,
            line((LON - 0.002, LAT + 0.00001), (LON + 0.002, LAT + 0.00001)),
            55,
            3,
            False,
            60000,
        ),
    ]
    with connection.cursor() as cursor:
        for way, ordinal, tier, wkt, speed, lanes, oneway, aadt in rows:
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, road_speed_mph, road_lanes, road_oneway, volume_aadt) "
                "VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, 'test', %s, %s, %s, %s)",
                [way, ordinal, wkt, tier, speed, lanes, oneway, aadt],
            )
    junctions._has_trait_columns_seen = False
    return live


@db
class TestRoadsByWay:
    def test_each_way_at_its_junction_with_what_the_classifier_read(self, grid) -> None:
        found = junctions.roads_by_way(
            [(0, 20, LON, LAT), (0, 10, LON, LAT)], "weekend", with_facility=False
        )
        assert found[(0, 20)] == Road(tier=4, speed_mph=40.0, lanes=2, oneway=False, aadt=22000)
        assert found[(0, 10)] == Road(tier=2, speed_mph=25.0, lanes=1, oneway=False)

    def test_a_way_the_table_does_not_have_has_no_entry(self, grid) -> None:
        assert junctions.roads_by_way([(3, 999, LON, LAT)], "weekend", False) == {}

    def test_nothing_asked_no_query(self, grid) -> None:
        assert junctions.roads_by_way([], "weekend", False) == {}

    def test_the_segment_nearest_the_junction(self, segment_schemas) -> None:
        live, _staging = segment_schemas
        with connection.cursor() as cursor:
            for ordinal, tier, points in (
                (0, 3, ((LON, LAT), (LON + 0.001, LAT))),
                (1, 4, ((LON + 0.001, LAT), (LON + 0.01, LAT))),
            ):
                cursor.execute(
                    f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule) VALUES (20, %s, ST_GeomFromText(%s, 4326), %s, 'test')",
                    [ordinal, line(*points), tier],
                )
        junctions._has_trait_columns_seen = False
        assert junctions.roads_by_way([(0, 20, LON, LAT)], "weekend", False)[(0, 20)].tier == 3
        far = (LON + 0.009, LAT)
        assert junctions.roads_by_way([(0, 20, *far)], "weekend", False)[(0, 20)].tier == 4

    def test_a_table_before_the_traits_names_the_tier_alone(self, segment_schemas) -> None:
        live, _staging = segment_schemas
        with connection.cursor() as cursor:
            for column in ("road_speed_mph", "road_lanes", "road_oneway"):
                cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN {column}")
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (20, 0, ST_GeomFromText(%s, 4326), 4, 'test')",
                [line((LON, LAT - 0.002), (LON, LAT))],
            )
        junctions._has_trait_columns_seen = False
        assert not junctions.has_trait_columns(live)
        assert junctions.roads_by_way([(0, 20, LON, LAT)], "weekend", False)[(0, 20)] == Road(4)

    def test_a_road_closed_to_cars_at_the_ride_time_is_tier_one(self, segment_schemas) -> None:
        live, _staging = segment_schemas
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, car_free_when) VALUES (20, 0, ST_GeomFromText(%s, 4326), 4, 'test', "
                "ARRAY['weekend'])",
                [line((LON, LAT - 0.002), (LON, LAT))],
            )
        junctions._has_trait_columns_seen = False
        asked = [(0, 20, LON, LAT)]
        assert junctions.roads_by_way(asked, "weekend", with_facility=True)[(0, 20)].tier == 1
        assert junctions.roads_by_way(asked, "weekday_rush", with_facility=True)[(0, 20)].tier == 4


class TestBuild:
    roads = {(0, 10): Road(2), (0, 20): Road(4, 40, 2)}

    def built(self, locate_answer, junction=None, roads=None):
        junction = junction or raw()
        found = junctions.node_from_locate(locate_answer, junction)
        nodes = {0: found} if found is not None else {}
        (made,) = junctions.build_junctions(
            [junction], nodes, self.roads if roads is None else roads
        )
        return made

    def test_the_cross_road_with_its_names_and_both_ways(self) -> None:
        made = self.built(crossroads(**{"in": {"stop": True}}))
        assert made.incoming.tier == made.outgoing.tier == 2
        assert len(made.crossed) == 1
        crossed = made.crossed[0]
        assert (crossed.tier, crossed.speed_mph, crossed.lanes) == (4, 40, 2)
        assert crossed.names == frozenset({"main st"})
        assert crossed.oneway is False
        assert made.control is Control.STOP and made.located

    def test_a_one_way_pair_crossed_is_one_way(self) -> None:
        pair = answer(
            [
                edge(1, 10, N, 1.0, 90.0),
                edge(2, 10, 901, 0.0, 90.0),
                edge(6, 20, N, 1.0, 180.0, names=["Main St"]),  # arriving from the north
                edge(7, 20, 903, 0.0, 180.0, names=["Main St"]),  # leaving south
            ],
            [node(N)],
        )
        roads = {(0, 10): Road(2), (0, 20): Road(4)}
        made = self.built(pair, roads=roads)
        assert made.crossed[0].oneway is True

    def test_the_quieter_side_is_the_crossing(self) -> None:
        """A road that becomes a residential street across the junction."""
        roads = {(0, 10): Road(2), (0, 20): Road(4), (0, 21): Road(2)}
        mixed = crossroads()
        for e in mixed["edges"]:
            if e["edge_id"]["value"] in (7, 8):  # the south arm
                e["edge_info"]["way_id"] = 21
                e["edge_info"]["names"] = ["Side St"]
        made = self.built(mixed, roads=roads)
        assert made.crossed[0].tier == 2
        assert model.assess(made) is None

    def test_no_node_nothing_crossed_and_no_control(self) -> None:
        made = self.built({}, roads=self.roads)
        assert made.crossed == () and made.control is Control.NONE and not made.located
        assert made.incoming.tier == 2

    def test_unknown_ways_are_unknown_tiers(self) -> None:
        made = self.built(crossroads(), roads={})
        assert made.incoming.tier is None and not made.incoming.busy
        assert made.crossed[0].tier is None

    def test_a_link_at_the_node_is_a_slip_lane_with_its_road(self) -> None:
        pike = answer(
            [
                edge(1, 11, N, 1.0, 130.0, names=["Rockville Pike"]),
                edge(2, 11, 901, 0.0, 130.0, names=["Rockville Pike"]),
                edge(9, 13, N, 1.0, 112.0, use="turn_channel", link=True),
            ],
            [node(N)],
        )
        at = raw(in_way=11, out_way=11, in_heading=130.0, out_heading=130.0)
        made = self.built(pike, junction=at, roads={(0, 11): Road(4), (0, 13): Road(4)})
        assert made.slip_lane and made.crossed == ()
        assert made.links == (Road(4, oneway=True, names=frozenset({"way 13"})),)
        event = model.assess(made)
        assert event.kind == "slip_lane" and event.severity == model.ORANGE

    def test_a_marked_crossing_carries_through(self) -> None:
        made = self.built(crossroads(), junction=raw(in_use="pedestrian_crossing"))
        assert made.marked_crossing


class TestWanted:
    def test_a_junction_of_residential_streets_is_not_wanted(self) -> None:
        assert not junctions.wanted(raw(other_classes=("service_other", "residential")))

    def test_a_busy_class_road_is_wanted(self) -> None:
        assert junctions.wanted(raw())


class TestEvents:
    """Review r1's examples, end to end through the router's answer."""

    def locate_with(self, built):
        def locate(payload: dict) -> list[dict]:
            return [built for _ in payload["locations"]]

        return locate

    @db
    def test_a_crossing_of_the_arterial_from_the_quiet_street(self, grid) -> None:
        (event,) = junctions.events_of(
            [raw()], "weekend", False, self.locate_with(crossroads(**{"in": {"stop": True}}))
        )
        assert event.kind == "crossing"
        assert event.control is Control.STOP
        assert event.severity == model.RED
        assert event.crossed_tier == 4
        assert event.reason == "Crossing a 4-lane 40 mph (64 km/h) road, stop sign on your side"

    @db
    def test_the_road_under_a_bridge_deck_is_not_crossed(self, grid) -> None:
        """Way 50 passes a metre from the node on another level; the router has
        no edge of it at the node, so it is not met."""
        (event,) = junctions.events_of([raw()], "weekend", False, self.locate_with(crossroads()))
        assert event.crossed_tier == 4 and "40 mph" in event.reason

    @db
    def test_a_signalled_crossing_is_cheap_and_not_flagged(self, grid) -> None:
        signalled = answer(crossroads()["edges"], [node(N, signal=True)])
        (event,) = junctions.events_of([raw()], "weekend", False, self.locate_with(signalled))
        assert event.control is Control.SIGNAL
        assert not event.flagged and event.cost_ft == model.SIGNALISED_CROSSING_FT[4]

    @db
    def test_riding_along_the_arterial_past_a_merge_is_not_a_crossing(self, grid) -> None:
        """Review r1, B1: 16th St NW past an inbound-only merge (measured)."""
        merge = answer(
            [
                edge(1, 20, N, 1.0, 0.0),
                edge(2, 20, 901, 0.0, 13.3),
                edge(3, 20, 900, 0.0, 180.0),
                edge(9, 10, N, 1.0, 166.4),
            ],
            [node(N)],
        )
        along = raw(in_way=20, out_way=20, in_heading=0.0, out_heading=13.3)
        assert junctions.events_of([along], "weekend", False, self.locate_with(merge)) == []

    @db
    def test_a_route_through_quiet_streets_asks_the_router_nothing(self, segment_schemas) -> None:
        def locate(payload: dict):
            raise AssertionError("a neighbourhood junction does not ask")

        quiet = raw(other_classes=("residential",))
        assert junctions.events_of([quiet], "weekend", False, locate) == []

    @db
    def test_the_mass_ride_reading_colours_by_tier(self, grid) -> None:
        signalled = answer(crossroads()["edges"], [node(N, signal=True)])
        (event,) = junctions.events_of(
            [raw()], "weekend", False, self.locate_with(signalled), group=True
        )
        assert event.severity == model.RED and event.flagged
