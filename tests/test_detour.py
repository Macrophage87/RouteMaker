"""The detour warning's tiers (OWNER-DECISIONS item 164) and the literature
review's guidance: silent within the larger of 1.25 times or +0.33 mi, a note up
to 1.5 times, a warning above, a strong warning above 2 times."""

from __future__ import annotations

import pytest

from routemaker import detour

MI = detour.METRES_PER_MILE


class TestLevel:
    @pytest.mark.parametrize(
        ("direct_mi", "route_mi", "expected"),
        [
            (10.0, 10.0, None),
            (10.0, 12.5, None),  # exactly 1.25 times
            (10.0, 12.51, detour.NOTE),
            (10.0, 15.0, detour.NOTE),  # exactly 1.5 times
            (10.0, 15.01, detour.WARNING),
            (10.0, 20.0, detour.WARNING),  # exactly twice
            (10.0, 20.01, detour.STRONG),
            (10.0, 28.0, detour.STRONG),  # the owner's "2.6x (+18 mi)"
        ],
    )
    def test_the_tiers(self, direct_mi, route_mi, expected) -> None:
        assert detour.level(route_mi * MI, direct_mi * MI) == expected

    def test_the_allowance_is_the_larger_of_the_ratio_and_a_third_of_a_mile(self) -> None:
        # A short ride: 1.25 times 0.4 mi is only +0.1 mi, so the +0.33 mi rules.
        assert detour.level(0.7 * MI, 0.4 * MI) is None
        assert detour.level(0.74 * MI, 0.4 * MI) == detour.WARNING
        # A long ride: +0.33 mi would be nothing, so the ratio rules.
        assert detour.level(25.0 * MI, 20.0 * MI) is None
        assert detour.level(25.1 * MI, 20.0 * MI) == detour.NOTE

    def test_there_is_no_cap(self) -> None:
        """ "the upper end could be much greater than straight line distance, just
        warn people": a route twenty times the direct one is still a route."""
        assert detour.level(200 * MI, 10 * MI) == detour.STRONG

    @pytest.mark.parametrize(("route", "direct"), [(0, 10), (10, 0), (-1, 5), (5, -1)])
    def test_nothing_to_compare_says_nothing(self, route, direct) -> None:
        assert detour.level(route, direct) is None


class TestStraightLineFallback:
    def test_only_the_old_rule_applies(self) -> None:
        assert detour.straight_line_level(10_000, 4_000) == detour.WARNING
        assert detour.straight_line_level(10_000, 5_001) is None  # not twice as long
        assert detour.straight_line_level(5_800, 2_900) is None  # twice, but under 3 km more
        assert detour.straight_line_level(6_000, 3_000) == detour.WARNING

    def test_never_stronger_than_a_warning(self) -> None:
        assert detour.straight_line_level(1_000_000, 10_000) == detour.WARNING


class TestBlock:
    def test_a_direct_route_block(self) -> None:
        block = detour.describe(28 * MI, 10 * MI, detour.DIRECT_ROUTE, avoided_m=5000)
        assert block == {
            "basis": "direct_route",
            "reference_m": round(10 * MI, 1),
            "ratio": 2.8,
            "extra_m": round(18 * MI, 1),
            "level": "strong",
            "avoided_m": 5000.0,
        }

    def test_a_straight_line_block_uses_the_fallback_rule(self) -> None:
        block = detour.describe(10_000, 4_000, detour.STRAIGHT_LINE)
        assert block["level"] == "warning" and block["avoided_m"] is None

    def test_a_zero_reference_has_no_ratio(self) -> None:
        assert detour.describe(100, 0, detour.DIRECT_ROUTE)["ratio"] is None
