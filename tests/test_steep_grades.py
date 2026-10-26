"""Steep grades on a Mass Ride or a Novice and Nervous ride (v0.12.5, `routemaker.steep_grades`).

The owner, 2026-10-26: an orange marker and a penalty past 5% either way, red and a steeper
penalty past 8%, each showing whether it runs uphill or downhill for the rider.
"""

from __future__ import annotations

import pytest

from core import routing
from routemaker import steep_grades

STEP_M = 30.0


def _profile(grades, start_m=50.0):
    """A profile at the router's 30 m spacing, each gap at its grade."""
    height = start_m
    out = [(0.0, height)]
    for i, grade in enumerate(grades):
        height += grade * STEP_M
        out.append(((i + 1) * STEP_M, height))
    return out


FLAT = [0.0] * 10


def test_a_long_steep_climb_is_one_orange_uphill_stretch():
    found = steep_grades.stretches(_profile(FLAT + [0.06] * 10 + FLAT))
    assert len(found) == 1
    (stretch,) = found
    assert (stretch.direction, stretch.level) == (steep_grades.UP, steep_grades.LEVEL_STEEP)
    assert stretch.length_m >= steep_grades.MIN_LENGTH_M
    assert stretch.grade == pytest.approx(0.06)


def test_a_steep_descent_is_downhill_and_past_eight_percent_is_red():
    (stretch,) = steep_grades.stretches(_profile(FLAT + [-0.10] * 10 + FLAT))
    assert stretch.direction == steep_grades.DOWN
    assert stretch.level == steep_grades.LEVEL_VERY_STEEP


def test_the_direction_is_the_riders():
    """The same hill ridden the other way is a descent."""
    climb = _profile(FLAT + [0.07] * 10 + FLAT)
    reverse = [(climb[-1][0] - m, h) for m, h in reversed(climb)]
    assert [s.direction for s in steep_grades.stretches(climb)] == [steep_grades.UP]
    assert [s.direction for s in steep_grades.stretches(reverse)] == [steep_grades.DOWN]


def test_a_short_bump_is_not_marked():
    """60 m at 7%: a driveway ramp or a noisy sample, under MIN_LENGTH_M."""
    assert steep_grades.stretches(_profile(FLAT + [0.07] * 2 + FLAT)) == []
    assert steep_grades.penalty_s(_profile(FLAT + [0.07] * 2 + FLAT)) == 0.0


def test_five_percent_itself_is_not_steep():
    assert steep_grades.stretches(_profile(FLAT + [0.05] * 10 + FLAT)) == []


def test_a_red_pitch_inside_an_orange_climb_is_split_out():
    found = steep_grades.stretches(_profile(FLAT + [0.06] * 8 + [0.12] * 8 + [0.06] * 8 + FLAT))
    assert [s.level for s in found] == [
        steep_grades.LEVEL_STEEP,
        steep_grades.LEVEL_VERY_STEEP,
        steep_grades.LEVEL_STEEP,
    ]
    assert all(s.direction == steep_grades.UP for s in found)
    assert found[1].grade == pytest.approx(0.12)


def test_a_gap_in_the_heights_ends_a_stretch():
    climb = _profile([0.06] * 3)
    profile = climb + [(climb[-1][0], None)] + [(m + climb[-1][0], h) for m, h in climb]
    assert steep_grades.stretches(profile) == []


def test_very_steep_costs_much_more_than_steep():
    steep = steep_grades.penalty_s(_profile(FLAT + [0.06] * 10 + FLAT))
    very = steep_grades.penalty_s(_profile(FLAT + [0.10] * 10 + FLAT))
    assert steep > 0
    assert very >= 3 * steep


def test_the_answer_says_each_in_words():
    (row,) = steep_grades.public(steep_grades.stretches(_profile(FLAT + [-0.10] * 10 + FLAT)))
    assert row["direction"] == "down"
    assert row["level"] == "very_steep"
    assert row["grade_pct"] == 10
    assert row["text"].startswith("Very steep downhill, up to 10%, for ")
    assert " ft (" in row["text"]


def _trip(grades):
    heights = [h for _m, h in _profile(grades)]
    length_km = STEP_M * len(grades) / 1000.0
    return {"legs": [{"elevation": heights, "summary": {"length": length_km}}], "summary": {}}


def _price(steep):
    return routing.HillPrice(
        mass_kg=90.0, flat_ms=5.0, hills=-60, use_hills=0.2, brake_grade=0.04, steep=steep
    )


def test_the_route_choice_prices_them_only_where_asked():
    trip = _trip(FLAT + [-0.10] * 10 + FLAT)
    without = routing.rider_hill_s(trip, _price(False), 1.0)
    priced = routing.rider_hill_s(trip, _price(True), 1.0)
    assert priced - without == pytest.approx(
        steep_grades.penalty_s(routing.grade_profile(trip)) * 5.0
    )


def test_only_mass_ride_and_novice():
    assert steep_grades.RIDE_TYPES == {"mass-ride", "novice"}
