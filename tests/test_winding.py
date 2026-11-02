"""Winding trails, priced like a busy street on the road-bike graph (`routemaker.winding`)."""

from __future__ import annotations

import math

from routemaker import winding

LAT = 39.0
M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT))


def _line(steps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """(lon, lat) points from (east, north) metre steps, starting at (-77.0, LAT)."""
    x = y = 0.0
    points = [(-77.0, LAT)]
    for dx, dy in steps:
        x, y = x + dx, y + dy
        points.append((-77.0 + x / M_PER_DEG_LON, LAT + y / M_PER_DEG_LAT))
    return points


def test_a_rail_trail_is_not_winding():
    straight = _line([(50.0, 0.0)] * 20)  # 1 km, no bends
    assert winding.deg_per_100m(straight) < 1
    assert not winding.is_winding(straight)


def test_a_creek_trail_that_zigzags_is_winding():
    # 30 degrees left then right every 25 m: 60 degrees of turning per 25 m after the first.
    a = math.radians(30)
    zig = _line([(25 * math.cos(a), 25 * math.sin(a) * (1 if i % 2 else -1)) for i in range(24)])
    assert winding.is_winding(zig)


def test_one_bend_at_the_end_of_a_short_connector_is_not_winding():
    # 60 m with one 45-degree bend: spread over MIN_SPAN_M, 22.5 degrees per 100 m.
    gentle = _line([(30.0, 0.0), (21.2, 21.2)])
    assert not winding.is_winding(gentle)


def test_a_long_way_is_measured_over_its_own_length():
    # 1 km with the same right-angle bend: 9 degrees per 100 m.
    long_way = _line([(500.0, 0.0), (0.0, 500.0)])
    assert abs(winding.deg_per_100m(long_way) - 9.0) < 0.1


def test_doubled_nodes_carry_no_heading():
    doubled = _line([(50.0, 0.0), (0.0, 0.0), (0.1, 0.1), (50.0, 0.0)] * 5)
    assert not winding.is_winding(doubled)


def test_too_short_to_measure():
    assert winding.deg_per_100m([(-77.0, LAT)]) == 0.0
    assert not winding.is_winding([])
