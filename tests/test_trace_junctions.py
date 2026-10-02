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


def encode6(points) -> str:
    """Valhalla's polyline, precision 6 (the inverse of `decode_polyline6`)."""
    out = []
    last = (0, 0)
    for lon, lat in points:
        here = (round(lat * 1e6), round(lon * 1e6))
        for value, before in zip(here, last, strict=True):
            delta = value - before
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                out.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            out.append(chr(delta + 63))
        last = here
    return "".join(out)


def at_edge(found, edge_id):
    return next(j for j in found if j.in_edge_id == edge_id)


class TestBackEdges:
    """Review r2: a stop or signal on the stop line short of the junction is
    on the rider's own edge before the in-edge."""

    def test_the_riders_edges_within_the_approach_nearest_first(self) -> None:
        cross = ("road", "primary", "both")
        trace = {
            "edges": [
                edge(1, 0, 1, 0.010, 90, 90),
                edge(2, 1, 2, 0.010, 90, 90),
                edge(3, 2, 3, 0.010, 90, 90),
                with_others(edge(4, 3, 4, 0.012, 90, 90), cross),
                edge(5, 4, 5, 0.1, 90, 90),
            ],
            "units": "kilometers",
        }
        junction = at_edge(t.junctions_of_trace(trace, SHAPE), 1004)
        # 12 m of in-edge, then 10 m, then 10 m: the first two end within 30 m
        # of the node (12 and 22 m back), the third at 32 m.
        assert junction.back_edge_ids == (1003, 1002)
        assert t.APPROACH_M == 30.0

    def test_a_long_in_edge_has_none(self) -> None:
        cross = ("road", "primary", "both")
        trace = {
            "edges": [
                edge(1, 0, 1, 0.010, 90, 90),
                with_others(edge(2, 1, 2, 0.031, 90, 90), cross),
                edge(3, 2, 3, 0.1, 90, 90),
            ]
        }
        assert at_edge(t.junctions_of_trace(trace, SHAPE), 1002).back_edge_ids == ()

    def test_exactly_the_approach_still_counts(self) -> None:
        cross = ("road", "primary", "both")
        trace = {
            "edges": [
                edge(1, 0, 1, 0.010, 90, 90),
                with_others(edge(2, 1, 2, 0.030, 90, 90), cross),
                edge(3, 2, 3, 0.1, 90, 90),
            ]
        }
        assert at_edge(t.junctions_of_trace(trace, SHAPE), 1002).back_edge_ids == (1001,)

    def test_an_edge_without_an_id_is_skipped_but_counted(self) -> None:
        cross = ("road", "primary", "both")
        first = edge(1, 0, 1, 0.005, 90, 90)
        del first["id"]
        trace = {
            "edges": [
                edge(5, 0, 1, 0.005, 90, 90),
                first,
                with_others(edge(2, 1, 2, 0.010, 90, 90), cross),
                edge(3, 2, 3, 0.1, 90, 90),
            ]
        }
        assert at_edge(t.junctions_of_trace(trace, SHAPE), 1002).back_edge_ids == (1005,)


class TestTheTracesOwnShape:
    def test_indices_count_in_the_traces_shape_not_the_routes(self) -> None:
        """Measured on the live router: the trace drops repeated vertices of the
        shape it is given (927 given, 922 traced on Falls Church to the
        Capitol), so the route's shape indexed by the trace's indices drifts
        onto the wrong nodes."""
        given = [SHAPE[0], SHAPE[0], SHAPE[1], SHAPE[2], SHAPE[3], SHAPE[4]]
        traced = SHAPE[:5]
        first = with_others(edge(1, 0, 2, 0.1, 90, 90), ("road", "primary", "both"))
        trace = {"edges": [first, edge(1, 2, 4, 0.1, 90, 90)], "shape": encode6(traced)}
        (junction,) = t.junctions_of_trace(trace, given)
        assert (junction.lon, junction.lat) == pytest.approx(SHAPE[2])

    def test_without_a_shape_of_its_own_the_given_one(self) -> None:
        first = with_others(edge(1, 0, 2, 0.1, 90, 90), ("road", "primary", "both"))
        (junction,) = t.junctions_of_trace({"edges": [first, edge(1, 2, 4, 0.1, 90, 90)]}, SHAPE)
        assert (junction.lon, junction.lat) == SHAPE[2]

    def test_the_decoder_reads_the_encoder(self) -> None:
        points = [(-77.123456, 38.987654), (-77.0, 39.1), (-76.5, 38.5)]
        assert t.decode_polyline6(encode6(points)) == pytest.approx(points)


class TestApproachAndMiddles:
    def test_the_approach_is_half_way_along_the_edge_not_a_vertex(self) -> None:
        """Review r1, SHOULD_FIX 1: on a two-vertex edge the middle vertex was the
        upstream node, and an exclusion there took out every edge at it."""
        first = with_others(edge(1, 0, 1, 0.1, 90, 90), ("road", "primary", "both"))
        (junction,) = t.junctions_of_trace({"edges": [first, edge(1, 1, 2, 0.1, 90, 90)]}, SHAPE)
        lon, lat = junction.approach
        assert lon == pytest.approx((SHAPE[0][0] + SHAPE[1][0]) / 2)
        assert lat == pytest.approx(SHAPE[0][1])
        assert junction.approach not in SHAPE

    def test_the_middle_by_ground_distance(self) -> None:
        bent = [(0.0, 0.0), (0.003, 0.0), (0.004, 0.0)]
        lon, _lat = t.midpoint_along(bent, 0, 2)
        assert lon == pytest.approx(0.002, abs=1e-6)

    def test_no_length_no_middle(self) -> None:
        assert t.midpoint_along(SHAPE, 2, 2) is None
        assert t.midpoint_along([(0.0, 0.0), (0.0, 0.0)], 0, 1) is None
        assert t.midpoint_along(SHAPE, 3, 99) is None

    def test_the_out_edge_and_the_headings_are_kept(self) -> None:
        first = with_others(edge(1, 0, 2, 0.1, 80, 85), ("road", "primary", "both"))
        (junction,) = t.junctions_of_trace({"edges": [first, edge(2, 2, 4, 0.1, 95, 90)]}, SHAPE)
        assert junction.out_edge_id == 1002
        assert (junction.in_heading, junction.out_heading) == (85.0, 95.0)

    def test_every_edges_middle_with_how_far_along_it_is(self) -> None:
        trace = {"edges": [edge(1, 0, 2, 0.2, 90, 90), edge(2, 2, 3, 0.1, 90, 90)]}
        marks = t.edge_midpoints(trace, SHAPE, offset_m=1000.0)
        assert [round(m[0]) for m in marks] == [1100, 1250]
        assert marks[0][1:3] == pytest.approx(SHAPE[1])
        assert marks[1][3] == pytest.approx(100.0)

    def test_an_edge_with_no_shape_has_no_middle_but_keeps_its_length(self) -> None:
        trace = {"edges": [edge(1, 2, 2, 0.2, 90, 90), edge(2, 2, 3, 0.1, 90, 90)]}
        marks = t.edge_midpoints(trace, SHAPE)
        assert [round(m[0]) for m in marks] == [250]


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

    @pytest.mark.parametrize(
        ("in_use", "out_use", "path"),
        [
            ("cycleway", "cycleway", True),
            ("road", "footway", True),
            ("sidewalk", "road", True),
            ("path", "path", True),
            ("road", "road", False),
            ("pedestrian_crossing", "road", False),
        ],
    )
    def test_a_route_on_a_path_crosses_as_a_trail(self, in_use, out_use, path) -> None:
        crossing = with_others(edge(1, 0, 2, 0.1, 90, 90, use=in_use), ("road", "primary", "both"))
        (junction,) = t.junctions_of_trace(
            {"edges": [crossing, edge(2, 2, 4, 0.1, 90, 90, use=out_use)]}, SHAPE
        )
        assert junction.path_crossing is path

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
