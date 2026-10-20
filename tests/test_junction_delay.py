"""The time a rider loses at junctions (`routemaker.junction_delay`)."""

from __future__ import annotations

import pytest

from routemaker import junction_delay as d
from routemaker import trace_junctions as t
from routemaker.intersections import Movement

SHAPE = [(-77.0 + i * 0.001, 38.9) for i in range(12)]


def junction(
    *others: tuple[str, str],
    m: float = 100.0,
    movement: Movement = Movement.STRAIGHT,
    in_class: str = "residential",
    out_class: str = "residential",
    in_use: str = "road",
    out_use: str = "road",
    in_way: int = 1,
    out_way: int = 1,
    signal: bool = False,
) -> t.RawJunction:
    """A junction with the other edges at the node as (use, road class) pairs."""
    return t.RawJunction(
        m=m,
        lon=-77.0,
        lat=38.9,
        in_edge_id=None,
        in_way=in_way,
        out_way=out_way,
        movement=movement,
        in_use=in_use,
        out_use=out_use,
        others=tuple((use, False) for use, _cls in others),
        in_class=in_class,
        out_class=out_class,
        other_classes=tuple(cls for _use, cls in others),
        signal=signal,
    )


CROSS_STREET = (("road", "residential"), ("road", "residential"))


class TestOneJunction:
    def test_a_neighbourhood_crossing_is_a_full_stop(self) -> None:
        assert d.delay_at(junction(*CROSS_STREET)) == d.STOP_DELAY_S

    def test_in_the_district_it_is_a_slow_and_roll(self) -> None:
        assert d.delay_at(junction(*CROSS_STREET), rolls=True) == d.YIELD_DELAY_S

    def test_crossing_a_busier_road_is_a_full_stop_in_the_district_too(self) -> None:
        busy = (("road", "tertiary"), ("road", "tertiary"))
        assert d.delay_at(junction(*busy), rolls=True) == d.STOP_DELAY_S

    def test_a_signal_is_the_signal_wait(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        assert d.delay_at(junction(*busy, signal=True)) == d.SIGNAL_DELAY_S

    def test_the_rider_on_the_busier_road_does_not_stop(self) -> None:
        assert d.delay_at(junction(*CROSS_STREET, in_class="tertiary", out_class="tertiary")) == 0

    def test_a_side_road_from_one_side_does_not_stop_the_rider(self) -> None:
        assert d.delay_at(junction(("road", "residential"))) == 0

    def test_a_street_split_into_two_ways_with_nothing_crossing_is_free(self) -> None:
        assert d.delay_at(junction(in_way=1, out_way=2)) == 0

    def test_driveways_and_alleys_cost_nothing(self) -> None:
        others = (("driveway", "service_other"), ("road", "service_other"))
        assert d.delay_at(junction(*others)) == 0

    def test_a_trail_crossing_a_road_gives_way(self) -> None:
        trail = {"in_use": "cycleway", "out_use": "cycleway"}
        trail |= {"in_class": "service_other", "out_class": "service_other"}
        assert d.delay_at(junction(*CROSS_STREET, **trail)) == d.STOP_DELAY_S

    def test_a_trail_meeting_another_trail_is_free(self) -> None:
        trail = {"in_use": "cycleway", "out_use": "cycleway"}
        trail |= {"in_class": "service_other", "out_class": "service_other"}
        assert d.delay_at(junction(("cycleway", "service_other"), **trail)) == 0

    def test_a_trail_coming_out_onto_a_street_gives_way(self) -> None:
        out = {"in_use": "cycleway", "in_class": "service_other"}
        assert d.delay_at(junction(movement=Movement.RIGHT, out_way=2, **out)) == d.STOP_DELAY_S

    def test_turning_onto_a_busier_road_gives_way(self) -> None:
        turn = {"movement": Movement.LEFT, "out_way": 2, "out_class": "secondary"}
        assert d.delay_at(junction(("road", "secondary"), **turn)) == d.STOP_DELAY_S

    def test_turning_off_onto_a_quieter_street_is_free(self) -> None:
        turn = {"movement": Movement.RIGHT, "out_way": 2, "in_class": "secondary"}
        assert d.delay_at(junction(("road", "secondary"), **turn)) == 0


class TestWholeRoute:
    def test_junctions_add_up(self) -> None:
        stops = [junction(*CROSS_STREET, m=100.0 * i) for i in range(1, 6)]
        assert d.delay_s(stops) == pytest.approx(5 * d.STOP_DELAY_S)

    def test_a_divided_road_is_crossed_as_one_stop_at_its_dearest(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        near = [junction(*busy, m=100.0), junction(*busy, m=118.0, signal=True)]
        assert d.delay_s(near) == d.SIGNAL_DELAY_S

    def test_the_district_test_is_asked_at_each_junction(self) -> None:
        stops = [junction(*CROSS_STREET, m=100.0), junction(*CROSS_STREET, m=300.0)]
        asked = []

        def rolls(lon: float, lat: float) -> bool:
            asked.append((lon, lat))
            return len(asked) == 1

        assert d.delay_s(stops, rolls) == d.YIELD_DELAY_S + d.STOP_DELAY_S

    def test_no_junctions_no_delay(self) -> None:
        assert d.delay_s([]) == 0


def edge(way, begin, end, length_km, **fields):
    return {
        "way_id": way,
        "begin_shape_index": begin,
        "end_shape_index": end,
        "length": length_km,
        "begin_heading": 90,
        "end_heading": 90,
        "road_class": "residential",
        "use": "road",
        **fields,
    }


class TestSignalFromTheTrace:
    def test_a_signal_on_the_node(self) -> None:
        first = edge(1, 0, 2, 0.1)
        first["end_node"] = {
            "traffic_signal": True,
            "intersecting_edges": [{"use": "road", "road_class": "primary"}],
        }
        (found,) = t.junctions_of_trace({"edges": [first, edge(1, 2, 4, 0.1)]}, SHAPE)
        assert found.signal

    def test_a_signal_on_the_stop_line_before_the_junction(self) -> None:
        approach = edge(1, 0, 2, 0.1, traffic_signal=True)
        last = edge(1, 2, 3, 0.012)
        last["end_node"] = {"intersecting_edges": [{"use": "road", "road_class": "primary"}]}
        trace = {"edges": [approach, last, edge(1, 3, 5, 0.1)]}
        (found,) = t.junctions_of_trace(trace, SHAPE)
        assert found.signal

    def test_a_signal_a_block_back_is_not_this_junctions(self) -> None:
        approach = edge(1, 0, 2, 0.1, traffic_signal=True)
        last = edge(1, 2, 3, 0.1)
        last["end_node"] = {"intersecting_edges": [{"use": "road", "road_class": "primary"}]}
        trace = {"edges": [approach, last, edge(1, 3, 5, 0.1)]}
        (found,) = t.junctions_of_trace(trace, SHAPE)
        assert not found.signal
