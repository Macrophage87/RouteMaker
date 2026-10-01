"""What is at each junction of a route (`core.junctions`): the roads from the
segment table, the right of way from the router's `/locate`, and the events the
model makes of them (OWNER-DECISIONS items 165 to 172).

The segment table is real, because the road query is a PostGIS one. The router
is replaced by the function the caller hands `controls_at`.
"""

from __future__ import annotations

import pytest
from django.db import connection

from core import junctions
from routemaker import intersections as model
from routemaker.intersections import Control, Movement, Road
from routemaker.trace_junctions import RawJunction

db = pytest.mark.django_db(transaction=True)

# A junction at the origin of a small grid: a quiet street (way 10) running east
# to west, a four-lane arterial (way 20) north to south, both through (0, 0).
LON, LAT = -77.0, 38.9


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
        # A sidepath that runs beside the arterial three metres from it.
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
        # Far away.
        (40, 0, 3, line((LON + 0.05, LAT), (LON + 0.051, LAT)), 35, 1, True, None),
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


def raw(**fields) -> RawJunction:
    base = {
        "m": 100.0,
        "lon": LON,
        "lat": LAT,
        "in_edge_id": 77,
        "in_way": 10,
        "out_way": 10,
        "movement": Movement.STRAIGHT,
        "in_use": "road",
        "out_use": "road",
        "others": (("road", False), ("road", False)),
        "in_class": "residential",
        "out_class": "residential",
        "other_classes": ("primary", "primary"),
    }
    return RawJunction(**(base | fields))


@db
class TestRoadsAt:
    def test_the_roads_that_meet_at_a_node_with_what_the_classifier_read(self, grid) -> None:
        found = junctions.roads_at([raw()], "weekend", with_facility=False)
        assert set(found[0]) == {10, 20, 30}
        assert found[0][20] == Road(tier=4, speed_mph=40.0, lanes=2, oneway=False, aadt=22000)
        assert found[0][10] == Road(tier=2, speed_mph=25.0, lanes=1, oneway=False)

    def test_a_road_far_from_the_node_is_not_there(self, grid) -> None:
        assert 40 not in junctions.roads_at([raw()], "weekend", False)[0]

    def test_a_junction_no_segment_touches_has_no_entry(self, grid) -> None:
        assert junctions.roads_at([raw(lon=LON + 1)], "weekend", False) == {}

    def test_one_row_per_road_not_per_segment(self, grid) -> None:
        # Way 20 has a segment each side of the node.
        found = junctions.roads_at([raw()], "weekend", False)[0]
        assert sorted(found) == [10, 20, 30]

    def test_each_junction_by_its_position(self, grid) -> None:
        found = junctions.roads_at([raw(lon=LON + 1), raw()], "weekend", False)
        assert list(found) == [1]

    def test_no_junctions_no_query(self, grid) -> None:
        assert junctions.roads_at([], "weekend", False) == {}

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
        found = junctions.roads_at([raw()], "weekend", False)
        assert found[0][20] == Road(tier=4)


@db
class TestFacilityTier:
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
        weekend = junctions.roads_at([raw()], "weekend", with_facility=True)
        weekday = junctions.roads_at([raw()], "weekday_rush", with_facility=True)
        assert weekend[0][20].tier == 1
        assert weekday[0][20].tier == 4


class TestControlFromLocate:
    """`/locate` at a node lists every directed edge there with the stop, yield
    and signal flags of the end it arrives at, and the node's own signal flag."""

    def answer(self, node_signal=False, edges=()) -> dict:
        return {
            "nodes": [{"traffic_signal": node_signal}],
            "edges": [
                {
                    "edge_id": {"value": edge_id},
                    "edge": {"stop_sign": stop, "yield_sign": yld, "traffic_signal": signal},
                    "edge_info": {"way_id": way},
                }
                for edge_id, way, stop, yld, signal in edges
            ],
        }

    def test_a_signal_at_the_node(self) -> None:
        assert junctions.control_from_locate(self.answer(node_signal=True), raw()) is Control.SIGNAL

    def test_a_signal_on_the_arrival_edge(self) -> None:
        answer = self.answer(edges=[(77, 10, False, False, True)])
        assert junctions.control_from_locate(answer, raw()) is Control.SIGNAL

    def test_a_stop_on_the_arrival_edge_is_the_riders(self) -> None:
        answer = self.answer(edges=[(77, 10, True, False, False), (78, 20, False, False, False)])
        assert junctions.control_from_locate(answer, raw()) is Control.STOP

    def test_a_yield_is_a_stop_for_this_purpose(self) -> None:
        answer = self.answer(edges=[(77, 10, False, True, False)])
        assert junctions.control_from_locate(answer, raw()) is Control.STOP

    def test_a_stop_on_the_cross_road_leaves_the_rider_free_flowing(self) -> None:
        answer = self.answer(edges=[(77, 10, False, False, False), (88, 20, True, False, False)])
        assert junctions.control_from_locate(answer, raw()) is Control.CROSS_STOP

    def test_stops_on_both_are_an_all_way_stop(self) -> None:
        answer = self.answer(edges=[(77, 10, True, False, False), (88, 20, True, False, False)])
        assert junctions.control_from_locate(answer, raw()) is Control.ALL_STOP

    def test_a_stop_flag_on_the_riders_other_edges_is_not_a_cross_stop(self) -> None:
        """Only the directed edge the route arrives on is the rider's; the way's
        other edges (the far side, the other direction) are not cross traffic."""
        answer = self.answer(edges=[(77, 10, False, False, False), (79, 10, True, False, False)])
        assert junctions.control_from_locate(answer, raw()) is Control.NONE

    def test_nothing_flagged_is_no_signal(self) -> None:
        assert junctions.control_from_locate(self.answer(), raw()) is Control.NONE
        assert junctions.control_from_locate({}, raw()) is Control.NONE


class TestControlsAt:
    def test_batches_and_positions(self) -> None:
        raws = [raw(lon=LON + i * 0.001) for i in range(120)]
        asked = []

        def locate(payload: dict) -> list[dict]:
            asked.append(payload)
            return [
                {"nodes": [{"traffic_signal": True}], "edges": []} for _ in payload["locations"]
            ]

        controls = junctions.controls_at(raws, list(range(0, 120, 2)), locate)
        assert [len(p["locations"]) for p in asked] == [50, 10]
        assert set(controls) == set(range(0, 120, 2))
        assert all(c is Control.SIGNAL for c in controls.values())
        assert all(p["verbose"] and p["costing"] == "bicycle" for p in asked)
        assert asked[0]["locations"][1] == {"lon": raws[2].lon, "lat": raws[2].lat}

    def test_a_batch_the_router_will_not_answer_is_no_signal_and_not_an_error(self) -> None:
        def locate(payload: dict):
            raise RuntimeError("down")

        assert junctions.controls_at([raw()], [0], locate) == {}

    def test_no_positions_no_call(self) -> None:
        def locate(payload: dict):
            raise AssertionError("asked")

        assert junctions.controls_at([raw()], [], locate) == {}


class TestBuild:
    def test_the_roads_other_than_the_routes_are_crossed(self) -> None:
        roads = {0: {10: Road(2), 20: Road(4, 40, 2)}}
        (built,) = junctions.build_junctions([raw()], roads, {0: Control.STOP})
        assert built.incoming == built.outgoing == Road(2)
        assert built.crossed == (Road(4, 40, 2),)
        assert built.control is Control.STOP

    def test_a_way_that_only_passes_near_is_not_crossed(self) -> None:
        """A sidepath three metres from the carriageway shares no node with it:
        the router has no road edge at the node, so nothing is crossed."""
        roads = {0: {10: Road(2), 30: Road(4)}}
        (built,) = junctions.build_junctions([raw(others=())], roads, {})
        assert built.crossed == ()

    def test_no_more_crossed_roads_than_the_router_has_edges_there(self) -> None:
        roads = {0: {10: Road(2), 20: Road(4), 21: Road(3), 22: Road(3)}}
        (built,) = junctions.build_junctions([raw(others=(("road", False),))], roads, {})
        assert built.crossed == (Road(4),), "the busiest, one edge"

    def test_unknown_roads_are_unknown_tiers(self) -> None:
        (built,) = junctions.build_junctions([raw()], {}, {})
        assert built.incoming == built.outgoing == Road(None)
        assert not built.incoming.busy

    def test_a_slip_lane_and_a_marked_crossing_carry_through(self) -> None:
        marked = raw(in_use="pedestrian_crossing", others=(("turn_channel", False),))
        (built,) = junctions.build_junctions([marked], {}, {})
        assert built.slip_lane and built.marked_crossing


class TestWantedAndNeedsControl:
    def test_a_junction_of_residential_streets_is_not_wanted(self) -> None:
        neighbourhood = raw(other_classes=("service_other", "residential"))
        assert not junctions.wanted(neighbourhood)

    def test_a_busy_class_road_is_wanted(self) -> None:
        assert junctions.wanted(raw())

    def test_only_a_junction_where_the_right_of_way_changes_the_cost_is_asked(self) -> None:
        from routemaker.intersections import Junction

        def j(**fields):
            base = dict(
                m=0, lon=0, lat=0, movement=Movement.STRAIGHT, incoming=Road(2), outgoing=Road(2)
            )
            return Junction(**(base | fields))

        busy = Road(4)
        assert junctions.needs_control(j(crossed=(busy,)))
        assert junctions.needs_control(j(outgoing=busy, movement=Movement.RIGHT))
        assert junctions.needs_control(j(incoming=busy, movement=Movement.LEFT))
        assert junctions.needs_control(j(incoming=busy, outgoing=busy, slip_lane=True))
        # Not along a busy road past a side street, a right off one, or a quiet junction.
        assert not junctions.needs_control(j(incoming=busy, outgoing=busy, crossed=(Road(2),)))
        assert not junctions.needs_control(j(incoming=busy, movement=Movement.RIGHT))
        assert not junctions.needs_control(j(crossed=(Road(2),)))


@db
class TestEvents:
    def test_a_crossing_of_the_arterial_from_the_quiet_street_is_a_flagged_event(
        self, grid
    ) -> None:
        def locate(payload: dict) -> list[dict]:
            return [
                {
                    "nodes": [{"traffic_signal": False}],
                    "edges": [
                        {
                            "edge_id": {"value": 77},
                            "edge": {"stop_sign": True},
                            "edge_info": {"way_id": 10},
                        }
                    ],
                }
                for _ in payload["locations"]
            ]

        (event,) = junctions.events_of([raw()], "weekend", False, locate)
        assert event.kind == "crossing"
        assert event.control is Control.STOP
        assert event.severity == model.RED
        assert event.crossed_tier == 4
        assert event.reason == "Crossing a 4-lane 40 mph (64 km/h) road, stop sign on your side"

    def test_a_signalled_crossing_is_cheap_and_not_flagged(self, grid) -> None:
        def locate(payload: dict) -> list[dict]:
            return [
                {"nodes": [{"traffic_signal": True}], "edges": []} for _ in payload["locations"]
            ]

        (event,) = junctions.events_of([raw()], "weekend", False, locate)
        assert event.control is Control.SIGNAL
        assert not event.flagged and event.cost_ft == model.SIGNALISED_CROSSING_FT[4]

    def test_a_route_through_quiet_streets_asks_the_router_nothing(self, segment_schemas) -> None:
        def locate(payload: dict):
            raise AssertionError("a neighbourhood junction does not ask")

        assert (
            junctions.events_of([raw(other_classes=("residential",))], "weekend", False, locate)
            == []
        )

    def test_the_mass_ride_reading_colours_by_tier(self, grid) -> None:
        def locate(payload: dict) -> list[dict]:
            return [
                {"nodes": [{"traffic_signal": True}], "edges": []} for _ in payload["locations"]
            ]

        (event,) = junctions.events_of([raw()], "weekend", False, locate, group=True)
        assert event.severity == model.RED and event.flagged
