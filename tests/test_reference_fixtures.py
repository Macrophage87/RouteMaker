"""The reference routes are the ground truth, so the measurements are asserted
against them rather than against hand-written expectations.

Distance, gain, and turn counts are reproduced exactly from the recorded tables.
Grade is not: see `test_grade_is_regenerated_not_reproduced` for why the recorded
grade column was replaced rather than matched.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from routemaker.geo import Point, cumulative_distances, haversine
from routemaker.gpx import read_track_points
from routemaker.measure import (
    REVISIT_ALONG_ROUTE_M,
    REVISIT_PROXIMITY_M,
    RouteStats,
    revisits,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "reference-routes"

# Recorded in fixtures/reference-routes/README.md. Distance in miles, gain in feet.
RECORDED = {
    "2025-05-dcbp-btr": (5.08, 63, 14),
    "2025-12-dcbp": (6.17, 113, 18),
    "2026-04-dcbp": (7.23, 133, 17),
    "2026-07-dcbp": (6.00, 164, 28),
    "group-blow-off-steam": (11.65, 661, 30),
    "group-crit-mass-2024-03": (12.31, 347, 34),
    "group-crit-mass-feb": (14.50, 511, 47),
    "group-crit-mass-jan": (13.77, 604, 33),
    "group-purple-line": (35.25, 985, 118),
    # 2361, not 2360: the measurement is 2360.89 ft and the README's table has
    # always said 2361. The one-foot disagreement was inside this file's own
    # `abs=1` tolerance, so neither number was wrong enough to fail and the two
    # sat there disagreeing. The README is the recorded table, so the README wins.
    "rural-group-loco-30": (30.12, 2361, None),  # sampled too densely to count turns
    "rural-group-tnl": (24.32, 2219, 26),
    "rural-group-two-bridges": (30.11, 2232, 30),
    "trail-annapolis-bwi": (75.73, 2333, 177),
    "trail-bethesda-loop": (31.63, 701, 92),
    "trail-brookside-gardens": (14.65, 746, 42),
}


def stats_for(name: str) -> RouteStats:
    return RouteStats.measure(read_track_points(FIXTURES / f"{name}.gpx"))


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_distance_matches_recorded(name: str) -> None:
    assert stats_for(name).distance_mi == pytest.approx(RECORDED[name][0], abs=0.005)


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_gain_matches_recorded(name: str) -> None:
    """The hysteresis is asymmetric: threshold on the way up, running minimum on
    the way down. A symmetric threshold under-reports every route in the set."""
    assert round(stats_for(name).gain_ft) == pytest.approx(RECORDED[name][1], abs=1)


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_turns_match_recorded_where_sampling_permits(name: str) -> None:
    expected = RECORDED[name][2]
    stats = stats_for(name)
    if expected is None:
        assert not stats.turns_reliable, "trace is now coarse enough to count turns"
        return
    assert stats.turns_reliable
    assert stats.turns == expected


def test_dense_trace_is_flagged_rather_than_silently_miscounted() -> None:
    """The one trace sampled at 6.4 m under-counts turns by roughly two thirds,
    because a turn taken over 15 m splits into three sub-threshold steps. The
    measurement reports that it cannot be trusted instead of returning the number."""
    stats = stats_for("rural-group-loco-30")
    assert stats.mean_spacing_m < 20.0
    assert not stats.turns_reliable
    assert stats.turns_per_mile < 0.5  # against ~1.0 for its two sibling rural loops


def test_mass_rides_never_revisit_their_own_line() -> None:
    """The empirical basis for the self-crossing check, which belongs to Mass Ride
    alone: two of the five city group rides do revisit, so applying it wider would
    reject real routes."""
    for name in ("2025-05-dcbp-btr", "2025-12-dcbp", "2026-04-dcbp", "2026-07-dcbp"):
        assert stats_for(name).revisits == 0


# --- The revisit index ------------------------------------------------------
#
# `revisits` buckets points into a lat/lon grid and compares only the nine
# neighbouring cells, which is only a correct shortcut while a cell is at least
# `proximity_m` across on *both* axes. It was not: both axes were divided by
# 111,320 m, the length of a degree of latitude, so every cell was
# cos(38.9 deg) = 0.78 of `proximity_m` wide in ground distance and a pair on an
# east-west offset could sit two cells apart in x and never be compared. A
# parallel street a block over is what a revisit on a city grid looks like.

REVISIT_OFFSET_M = 22.5  # inside the 25 m proximity radius, outside a 0.78 cell
REVISIT_LEG_M = 500.0
REVISIT_SPACING_M = 25.0
DC_LAT = 38.9


def parallel_offset_route(base_lon: float) -> list[Point]:
    """An out-and-back whose return leg is `REVISIT_OFFSET_M` east of its outbound.

    One revisit by the definition: the two legs run 22.5 m apart, which is inside
    the 25 m proximity radius, and the ends of the route are 1000 m apart along
    it, which is outside the 400 m along-route minimum.
    """
    degrees_per_m_lat = 1.0 / 111_320.0
    degrees_per_m_lon = degrees_per_m_lat / math.cos(math.radians(DC_LAT))
    offset = REVISIT_OFFSET_M * degrees_per_m_lon
    step = REVISIT_SPACING_M * degrees_per_m_lat
    count = int(REVISIT_LEG_M / REVISIT_SPACING_M) + 1

    north = [Point(base_lon, DC_LAT + i * step) for i in range(count)]
    south = [Point(base_lon + offset, DC_LAT + i * step) for i in reversed(range(count))]
    return north + south


@pytest.mark.parametrize("sample", range(20))
def test_a_parallel_return_leg_inside_the_radius_is_a_revisit(sample: int) -> None:
    """The case the square cell lost, swept across one cell width of alignment.

    Whether the square-cell index found this pair at all depended on where the
    route happened to fall against the grid's origin: a 22.5 m east-west offset
    is 1.16 old cells, so for roughly a sixth of base longitudes the two legs
    landed two cells apart in x and the nine-cell scan never compared them. The
    sweep is what makes that a test rather than a coin flip - the measurement
    may not depend on where in the world the route is.
    """
    cell = REVISIT_PROXIMITY_M / 111_320.0
    base_lon = -77.0 + sample * cell / 20.0
    assert revisits(parallel_offset_route(base_lon)) == 1


def brute_force_revisits(
    points: list[Point],
    proximity_m: float = REVISIT_PROXIMITY_M,
    along_route_m: float = REVISIT_ALONG_ROUTE_M,
) -> int:
    """The definition, written out pairwise, with no index in it at all.

    This is what the grid is an optimisation of, so it is the only thing that
    can say whether the optimisation is one.
    """
    cum = cumulative_distances(points)
    flagged = [False] * len(points)
    for i, p in enumerate(points):
        for j in range(i + 1, len(points)):
            if cum[j] - cum[i] <= along_route_m:
                continue
            if haversine(p, points[j]) < proximity_m:
                flagged[i] = flagged[j] = True
    occurrences, previous = 0, False
    for now in flagged:
        if now and not previous:
            occurrences += 1
        previous = now
    return occurrences // 2


# `rural-group-loco-30` is excluded by its point count, not by its answer: at
# 7,538 points the pairwise form is 28 million haversines and runs for half a
# minute, which is not a price this suite pays on every run. The other fourteen
# cover 127 to 2,240 points and every revisit count the set contains.
BRUTE_FORCE_ROUTES = sorted(name for name in RECORDED if name != "rural-group-loco-30")


@pytest.mark.parametrize("name", BRUTE_FORCE_ROUTES)
def test_the_grid_index_agrees_with_the_pairwise_definition(name: str) -> None:
    """Every reference route, indexed and unindexed, on the real geometry.

    The synthetic case above pins the one failure a reviewer measured; this pins
    that the index has no others on any route this project has. A cell size that
    is wrong on either axis shows up here as a route whose count drops."""
    points = read_track_points(FIXTURES / f"{name}.gpx")
    assert revisits(points) == brute_force_revisits(points)
