"""Stress classifier tests.

Written around the cases this region actually produces, and around the ordering
the plan fixes: speed, then facility, then volume, then surface.
"""

from __future__ import annotations

import pytest

from routemaker.stress import Stress, classify, is_rough, is_unpaved
from routemaker.tags import lanes_per_direction, parse_maxspeed_mph


class TestSpeedOutranksVolume:
    def test_quiet_fast_road_stays_high_stress(self) -> None:
        """A two-lane road posted at 50 with no shoulder is hostile at any volume:
        what makes it so is the speed differential, not the traffic count."""
        result = classify({"highway": "secondary", "maxspeed": "50 mph"}, aadt=300)
        assert result.tier is Stress.LTS4

    def test_busy_slow_grid_is_not_high_stress(self) -> None:
        """A congested downtown grid at 25 is not LTS4 however many cars are on it."""
        result = classify(
            {"highway": "residential", "maxspeed": "25 mph", "lanes": "2"}, aadt=12_000
        )
        assert result.tier < Stress.LTS4

    def test_volume_modifies_only_two_lane_roads(self) -> None:
        """Furth applies volume as a modifier on two-lane roads, so a multilane
        arterial's tier must not move when a count is attached."""
        tags = {"highway": "primary", "maxspeed": "30 mph", "lanes": "4"}
        assert classify(tags).tier == classify(tags, aadt=200).tier


class TestFacility:
    def test_separated_track_is_lowest_stress(self) -> None:
        result = classify({"highway": "primary", "maxspeed": "40 mph", "cycleway": "track"})
        assert result.tier is Stress.LTS1

    def test_narrow_lane_beside_parking_is_worse_than_wide_lane(self) -> None:
        """The door zone is the difference, which is why width is an input."""
        narrow = classify(
            {
                "highway": "tertiary",
                "maxspeed": "25 mph",
                "cycleway": "lane",
                "parking:right": "parallel",
                "width": "3.0",
            }
        )
        wide = classify(
            {
                "highway": "tertiary",
                "maxspeed": "25 mph",
                "cycleway": "lane",
                "parking:right": "parallel",
                "width": "5.0",
            }
        )
        assert narrow.tier > wide.tier

    def test_bike_lane_does_not_rescue_a_fast_road(self) -> None:
        """A painted lane at 40 mph is still LTS4: paint is not separation."""
        result = classify({"highway": "primary", "maxspeed": "45 mph", "cycleway": "lane"})
        assert result.tier is Stress.LTS4


class TestConservativeDefaults:
    def test_missing_tags_are_recorded_as_assumed(self) -> None:
        """A tier derived from assumptions must be distinguishable from one derived
        from tags, because a reviewer comparing it against crash history needs to
        know which it is."""
        result = classify({"highway": "residential"})
        assert "maxspeed" in result.assumed
        assert "lanes" in result.assumed

    def test_unknown_parking_is_read_as_present(self) -> None:
        """Absence of a parking tag is not evidence that parking is absent, and the
        higher-stress reading is the one with the door zone in it."""
        untagged = classify(
            {"highway": "tertiary", "maxspeed": "25 mph", "cycleway": "lane", "width": "2.0"}
        )
        no_parking = classify(
            {
                "highway": "tertiary",
                "maxspeed": "25 mph",
                "cycleway": "lane",
                "width": "2.0",
                "parking:both": "no",
            }
        )
        assert untagged.tier >= no_parking.tier

    def test_fully_tagged_way_assumes_nothing(self) -> None:
        result = classify(
            {"highway": "residential", "maxspeed": "25 mph", "lanes": "2", "parking:both": "no"}
        )
        assert result.assumed == ()


class TestLanesPerDirection:
    def test_two_way_lanes_are_halved(self) -> None:
        """`lanes` counts both directions, so comparing it raw against a per-direction
        table reads every two-way street one class worse than it is."""
        assert lanes_per_direction({"lanes": "2"}) == 1

    def test_oneway_lanes_are_not_halved(self) -> None:
        assert lanes_per_direction({"lanes": "2", "oneway": "yes"}) == 2

    def test_explicit_directional_tag_wins(self) -> None:
        assert lanes_per_direction({"lanes": "5", "lanes:forward": "3"}) == 3


class TestMaxspeedParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("30 mph", 30.0), ("50", 31.07), ("50 km/h", 31.07), ("US:urban", 25.0)],
    )
    def test_units(self, value: str, expected: float) -> None:
        assert parse_maxspeed_mph(value) == pytest.approx(expected, abs=0.05)

    def test_unparseable_is_unknown_not_slow(self) -> None:
        assert parse_maxspeed_mph("signals") is None


class TestSurfaceIsNotStress:
    def test_maintained_gravel_is_not_rough(self) -> None:
        """Rural gravel here is a low-traffic choice rather than a hazard, so it must
        not be classified as stress; that distinction is why Group Ride can use it."""
        tags = {"highway": "unclassified", "surface": "gravel", "tracktype": "grade2"}
        assert is_unpaved(tags)
        assert not is_rough(tags)

    def test_rutted_track_is_rough(self) -> None:
        """What separates a road twenty people can ride two abreast from one that
        sheds half the group is tracktype and smoothness, not surface."""
        assert is_rough({"highway": "track", "surface": "dirt", "tracktype": "grade5"})

    def test_surface_never_sets_the_tier(self) -> None:
        paved = classify({"highway": "unclassified", "maxspeed": "25 mph", "surface": "asphalt"})
        gravel = classify({"highway": "unclassified", "maxspeed": "25 mph", "surface": "gravel"})
        assert paved.tier == gravel.tier


class TestTopTier:
    def test_top_tier_is_what_beginner_keys_on(self) -> None:
        """Beginner asserts zero top-tier distance, and the road-exposure report
        breaks exposure down by it, so the flag has to mean one thing."""
        assert classify({"highway": "primary", "maxspeed": "45 mph"}).is_top_tier
        assert not classify({"highway": "cycleway"}).is_top_tier
