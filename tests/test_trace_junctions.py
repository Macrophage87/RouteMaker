"""The junctions of a traced route, read from `/trace_attributes`.

The shapes of the answers here are what the live standard router returned
(2026-10-01, `node.intersecting_edge.*` and `edge.id` among the attributes
`routemaker.trace_junctions.TRACE_ATTRIBUTES` asks for)."""

from __future__ import annotations

import pytest

from routemaker import trace_junctions as t
from routemaker.intersections import Movement

SHAPE = [(-77.0 + i * 0.001, 38.9) for i in range(8)]


def edge(way, begin, end, length_km, in_h, out_h, **fields):
    return {
        "way_id": way,
        "begin_shape_index": begin,
        "end_shape_index": end,
        "length": length_km,
        "begin_heading": in_h,
        "end_heading": out_h,
        "road_class": "residential",
        "use": "road",
        "id": {"value": 1000 + way},
        **fields,
    }


def with_others(edge_fields, *others):
    edge_fields["end_node"] = {
        "intersecting_edges": [
            {"use": use, "road_class": cls, "driveability": drive} for use, cls, drive in others
        ]
    }
    return edge_fields


class TestJunctions:
    def test_a_node_between_edges_of_one_way_with_no_other_road_is_not_a_junction(self) -> None:
        trace = {"edges": [edge(1, 0, 2, 0.1, 90, 90), edge(1, 2, 4, 0.1, 90, 90)]}
        assert t.junctions_of_trace(trace, SHAPE) == []

    def test_a_cross_road_makes_a_junction_with_where_and_how_far(self) -> None:
        first = with_others(edge(1, 0, 2, 0.1, 90, 90), ("road", "primary", "both"))
        trace = {"edges": [first, edge(1, 2, 4, 0.1, 90, 90)], "units": "kilometers"}
        (junction,) = t.junctions_of_trace(trace, SHAPE, offset_m=500.0)
        assert (junction.lon, junction.lat) == SHAPE[2]
        assert junction.m == pytest.approx(600.0)
        assert junction.movement is Movement.STRAIGHT
        assert junction.in_edge_id == 1001
        assert junction.cross_road_count == 1
        assert junction.possibly_busy
        # The edge's middle vertex: a place to exclude it from.
        assert junction.approach == SHAPE[1]

    def test_miles_are_read_as_miles(self) -> None:
        first = with_others(edge(1, 0, 2, 1.0, 90, 90), ("road", "primary", "both"))
        trace = {"edges": [first, edge(1, 2, 4, 0.1, 90, 90)], "units": "miles"}
        assert t.junctions_of_trace(trace, SHAPE)[0].m == pytest.approx(1609.344)

    @pytest.mark.parametrize(
        ("heading_in", "heading_out", "movement"),
        [(90, 180, Movement.RIGHT), (90, 0, Movement.LEFT), (90, 95, Movement.STRAIGHT)],
    )
    def test_the_turn_is_from_the_headings(self, heading_in, heading_out, movement) -> None:
        trace = {"edges": [edge(1, 0, 2, 0.1, 90, heading_in), edge(2, 2, 4, 0.1, heading_out, 0)]}
        (junction,) = t.junctions_of_trace(trace, SHAPE)
        assert junction.movement is movement
        assert (junction.in_way, junction.out_way) == (1, 2)

    def test_a_trace_without_headings_has_no_junctions(self) -> None:
        """An older router, or a test double: the route is answered without them."""
        bare = {
            "edges": [{"way_id": 1, "begin_shape_index": 0, "end_shape_index": 2, "length": 0.1}]
            * 2
        }
        assert t.junctions_of_trace(bare, SHAPE) == []

    def test_an_edge_past_the_shape_is_skipped(self) -> None:
        trace = {"edges": [edge(1, 0, 99, 0.1, 90, 90), edge(2, 99, 100, 0.1, 0, 0)]}
        assert t.junctions_of_trace(trace, SHAPE) == []


class TestWhatIsAtTheNode:
    def test_a_slip_lane_is_valhallas_turn_channel(self) -> None:
        first = with_others(edge(1, 0, 2, 0.1, 90, 90), ("turn_channel", "primary", "forward"))
        (junction,) = t.junctions_of_trace({"edges": [first, edge(1, 2, 4, 0.1, 90, 90)]}, SHAPE)
        assert junction.slip_lane
        # And a route that rides one.
        riding = edge(3, 2, 4, 0.1, 90, 90, use="turn_channel")
        (own,) = t.junctions_of_trace({"edges": [edge(1, 0, 2, 0.1, 90, 90), riding]}, SHAPE)
        assert own.slip_lane

    def test_footways_and_driveways_are_not_roads_a_rider_crosses(self) -> None:
        first = with_others(
            edge(1, 0, 2, 0.1, 90, 90),
            ("footway", "service_other", "none"),
            ("driveway", "service_other", "both"),
            ("pedestrian_crossing", "service_other", "none"),
        )
        (junction,) = t.junctions_of_trace({"edges": [first, edge(1, 2, 4, 0.1, 90, 90)]}, SHAPE)
        assert junction.cross_road_count == 0
        assert not junction.has_cross_roads

    def test_a_mapped_crossing_way_is_a_marked_crossing(self) -> None:
        crossing = edge(5, 0, 2, 0.02, 0, 0, use="pedestrian_crossing")
        onto = with_others(crossing, ("road", "primary", "both"), ("road", "primary", "both"))
        (junction,) = t.junctions_of_trace(
            {"edges": [onto, edge(6, 2, 4, 0.02, 0, 0, use="pedestrian_crossing")]}, SHAPE
        )
        assert junction.marked_crossing
        assert junction.cross_road_count == 2

    def test_one_way_cross_roads_are_those_a_car_may_not_drive_both_ways(self) -> None:
        first = with_others(edge(1, 0, 2, 0.1, 90, 90), ("road", "secondary", "forward"))
        (junction,) = t.junctions_of_trace({"edges": [first, edge(1, 2, 4, 0.1, 90, 90)]}, SHAPE)
        assert junction.others == (("road", True),)

    @pytest.mark.parametrize(
        ("classes", "busy"),
        [
            (("residential", "residential", ["service_other"]), False),
            (("residential", "residential", ["tertiary"]), True),
            (("primary", "residential", []), True),
            (("residential", "unclassified", []), True),
            (("residential", "residential", ["residential", "service_other"]), False),
        ],
    )
    def test_a_neighbourhood_junction_is_not_possibly_busy(self, classes, busy) -> None:
        in_class, out_class, others = classes
        junction = t.RawJunction(
            m=0,
            lon=0,
            lat=0,
            in_edge_id=None,
            in_way=1,
            out_way=2,
            movement=Movement.STRAIGHT,
            in_use="road",
            out_use="road",
            in_class=in_class,
            out_class=out_class,
            other_classes=tuple(others),
        )
        assert junction.possibly_busy is busy


class TestAttributes:
    def test_the_attributes_are_valhallas_names(self) -> None:
        for name in t.TRACE_ATTRIBUTES:
            assert name.startswith(("edge.", "node.intersecting_edge."))
        assert "edge.id" in t.TRACE_ATTRIBUTES
        assert "node.intersecting_edge.use" in t.TRACE_ATTRIBUTES
