"""The line comparison the shape tests lean on (tests/approx_points.py) must
still fail when a line is wrong, or every test using it passes vacuously."""

from __future__ import annotations

from approx_points import approx_points

LINE = [(-77.123456, 38.987654), (-77.0, 39.1)]


def test_a_line_within_one_polyline6_unit_is_equal() -> None:
    assert [(-77.1234565, 38.9876535), (-77.0, 39.1)] == approx_points(LINE)


def test_a_point_two_units_off_is_not() -> None:
    assert [(-77.123458, 38.987654), (-77.0, 39.1)] != approx_points(LINE)


def test_lists_and_tuples_compare_alike() -> None:
    assert [list(point) for point in LINE] == approx_points(LINE)


def test_a_missing_or_extra_point_is_not_equal() -> None:
    assert LINE[:1] != approx_points(LINE)
    assert [*LINE, (-76.5, 38.5)] != approx_points(LINE)


def test_a_wider_tolerance_can_be_asked_for() -> None:
    assert [(-77.123458, 38.987654), (-77.0, 39.1)] == approx_points(LINE, abs=2e-6 + 1e-9)


def test_something_that_is_not_a_line_is_not_equal() -> None:
    assert approx_points(LINE) != 5
