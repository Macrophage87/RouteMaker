from __future__ import annotations

import math

import pytest

from routemaker.geo import EARTH_RADIUS_M, Point
from routemaker.shape import sharp_bends_per_mile, sinuosity


def line(*coords: tuple[float, float]) -> list[Point]:
    return [Point(lon, lat) for lon, lat in coords]


# A degree of latitude on `geo`'s sphere, so a bend can be built at a stated
# angle rather than found by trying coordinates.
DEGREE_OF_LATITUDE_M = math.pi * EARTH_RADIUS_M / 180.0


def bend_of(degrees: float, leg_m: float = 200.0) -> list[Point]:
    """Three points whose corner turns `degrees` from due north, to within the
    thousandth of a degree the sphere's convergence leaves over `leg_m`."""
    lon, lat = -77.0, 38.90
    corner_lat = lat + leg_m / DEGREE_OF_LATITUDE_M
    theta = math.radians(degrees)
    end_lat = corner_lat + leg_m * math.cos(theta) / DEGREE_OF_LATITUDE_M
    end_lon = lon + leg_m * math.sin(theta) / (
        DEGREE_OF_LATITUDE_M * math.cos(math.radians(corner_lat))
    )
    return [Point(lon, lat), Point(lon, corner_lat), Point(end_lon, end_lat)]


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


def test_a_bend_exactly_at_the_threshold_is_not_sharp() -> None:
    """The tie, and the default it is taken against.

    The comparison is `>`, so a bend of exactly the threshold is a bend the
    measure does not count - the same direction `turns` resolves its own tie in,
    which matters because the two measures are read side by side and a reader
    comparing them should not have to check which way each one rounds. Nothing
    pinned it: every bend in the file above is far from 60 degrees, so `>=`
    passed, and so did any threshold between about 20 and 80.
    """
    import inspect
    import math

    from routemaker.geo import bearing, bearing_delta
    from routemaker.shape import sharp_bends_per_mile as measure

    default = inspect.signature(measure).parameters["threshold_deg"].default
    assert default == 60.0

    corner = line((-77.0, 38.90), (-77.0, 38.902), (-76.997, 38.9035))
    delta = bearing_delta(bearing(corner[0], corner[1]), bearing(corner[1], corner[2]))
    assert measure(corner, threshold_deg=delta) == 0.0, "exactly at the threshold is not a bend"
    assert measure(corner, threshold_deg=math.nextafter(delta, 0.0)) > 0.0

    # And the default is pinned where it bites: two bends a fifth of a degree
    # apart, straddling 60, counted differently by the default alone.
    under, over = bend_of(59.9), bend_of(60.1)
    assert bearing_delta(bearing(under[0], under[1]), bearing(under[1], under[2])) < 60.0
    assert bearing_delta(bearing(over[0], over[1]), bearing(over[1], over[2])) > 60.0
    assert measure(under) == 0.0
    assert measure(over) > 0.0


def test_the_threshold_is_where_scoring_starts() -> None:
    """Pinned at the boundary rather than beside it.

    `test_short_stub_is_not_scored` uses a five metre stub, so the threshold
    could be raised a hundredfold - to 2.5 km, longer than most segments in the
    region - and every winding way in the city would silently score 1.0 with the
    suite green. The Group Ride winding-path penalty reads this number, so that
    mutation turns the penalty off.

    The two lines below are the same dog-leg at two scales: 20 m of it is noise
    between two junctions, 37 m of it is a way that really does turn a corner.
    """
    from routemaker.shape import MIN_MEANINGFUL_LENGTH_M

    assert MIN_MEANINGFUL_LENGTH_M == 25.0

    below = line((-77.0, 38.90000), (-77.0, 38.90010), (-77.00010, 38.90010))
    above = line((-77.0, 38.90000), (-77.0, 38.90018), (-77.00020, 38.90018))
    assert sinuosity(below) == 1.0, "under the threshold, the ratio means nothing"
    assert sinuosity(above) == pytest.approx(1.411, abs=0.01), "over it, the corner is real"
