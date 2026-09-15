from __future__ import annotations

import pytest

from routemaker.geo import Point
from routemaker.shape import sharp_bends_per_mile, sinuosity


def line(*coords: tuple[float, float]) -> list[Point]:
    return [Point(lon, lat) for lon, lat in coords]


def test_straight_line_is_one() -> None:
    assert sinuosity(line((-77.0, 38.90), (-77.0, 38.91), (-77.0, 38.92))) == pytest.approx(
        1.0, abs=1e-6
    )


def test_detour_exceeds_one() -> None:
    direct = line((-77.0, 38.90), (-77.0, 38.92))
    around = line((-77.0, 38.90), (-77.01, 38.91), (-77.0, 38.92))
    assert sinuosity(around) > sinuosity(direct)


def test_closed_loop_has_no_ratio() -> None:
    """Endpoints coincide, so the ratio is undefined rather than enormous. Loops
    are scored by bends per mile instead, which is why that measure exists."""
    loop = line((-77.0, 38.90), (-77.01, 38.90), (-77.01, 38.91), (-77.0, 38.90))
    assert sinuosity(loop) == float("inf")


def test_short_stub_is_not_scored() -> None:
    """A five metre stub between two junctions can take any ratio at all."""
    stub = line((-77.0, 38.9000), (-77.00002, 38.90002))
    assert sinuosity(stub) == 1.0


def test_bends_separate_a_sweep_from_a_zigzag() -> None:
    """A long curve and a series of tight corners can share a sinuosity ratio
    while riding nothing alike."""
    sweep = line((-77.0, 38.90), (-77.002, 38.902), (-77.005, 38.903), (-77.008, 38.9035))
    zigzag = line((-77.0, 38.90), (-77.002, 38.902), (-77.004, 38.900), (-77.006, 38.902))
    assert sharp_bends_per_mile(zigzag) > sharp_bends_per_mile(sweep)
