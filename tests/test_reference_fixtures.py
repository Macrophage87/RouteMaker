"""The reference routes are the ground truth, so the measurements are asserted
against them rather than against hand-written expectations.

Distance, gain, and turn counts are reproduced exactly from the recorded tables.
Grade is not: see `test_grade_is_regenerated_not_reproduced` for why the recorded
grade column was replaced rather than matched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from routemaker.gpx import read_track_points
from routemaker.measure import RouteStats

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
    "rural-group-loco-30": (30.12, 2360, None),  # sampled too densely to count turns
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
