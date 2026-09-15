"""Stress classifier tests.

Written around the cases this region actually produces, and around the ordering
the plan fixes: speed, then facility, then volume, then surface.
"""

from __future__ import annotations

import pytest

from routemaker.stress import (
    UNPAVED_RURAL_DEFAULT_MPH,
    Stress,
    classify,
    is_rough,
    is_unpaved,
)
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
        """The door zone is the difference, which is why width is an input.

        Measured from the cycleway's own width tags. Falling back to the roadway
        `width` made a four-lane arterial lower stress the moment somebody
        surveyed its carriageway.
        """
        narrow = classify(
            {
                "highway": "tertiary",
                "maxspeed": "25 mph",
                "cycleway": "lane",
                "parking:right": "parallel",
                "cycleway:width": "1.2",
            }
        )
        wide = classify(
            {
                "highway": "tertiary",
                "maxspeed": "25 mph",
                "cycleway": "lane",
                "parking:right": "parallel",
                "cycleway:width": "5.0",
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
            {
                "highway": "tertiary",
                "maxspeed": "25 mph",
                "cycleway": "lane",
                "cycleway:width": "2.0",
            }
        )
        no_parking = classify(
            {
                "highway": "tertiary",
                "maxspeed": "25 mph",
                "cycleway": "lane",
                "cycleway:width": "2.0",
                "parking:both": "no",
            }
        )
        # Strictly greater, not >=. The earlier version used >=, which passes
        # whether the default reads parking as present or absent: flipping the
        # rule to its opposite left the whole suite green.
        assert untagged.tier > no_parking.tier
        assert (untagged.tier, no_parking.tier) == (Stress.LTS2, Stress.LTS1)

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


class TestRulesThatHadNoTest:
    """Six rules a reviewer mutated without any test noticing.

    Each has a comment in the classifier arguing for it and, until now, nothing
    asserting it. The quality bar names the stress classifier first among the
    unit-test targets, which is what made the gap worth recording rather than
    just closing.
    """

    def test_a_rideable_shoulder_drops_one_tier(self) -> None:
        """Shoulder credit matters most at speed: a 45 mph road with a wide paved
        shoulder is a different proposition from the same road with a rumble
        strip and a ditch, and on a rural group ride that is the most useful
        discrimination available."""
        bare = classify({"highway": "secondary", "maxspeed": "45 mph"})
        assert bare.tier is Stress.LTS4

        with_shoulder = classify(
            {
                "highway": "secondary",
                "maxspeed": "45 mph",
                "shoulder": "both",
                "shoulder:width": "1.8",
            }
        )
        assert with_shoulder.tier is Stress.LTS3
        assert "rideable shoulder" in with_shoulder.rule

    def test_a_shoulder_too_narrow_to_sit_in_earns_no_credit(self) -> None:
        """A six-inch shoulder is not a refuge."""
        narrow = classify(
            {
                "highway": "secondary",
                "maxspeed": "45 mph",
                "shoulder": "both",
                "shoulder:width": "0.4",
            }
        )
        assert narrow.tier is Stress.LTS4
        assert "rideable shoulder" not in narrow.rule

    def test_an_untagged_shoulder_width_earns_no_credit(self) -> None:
        """Read as narrow, and recorded as an assumption so a reviewer can see
        the tier rested on one."""
        unmeasured = classify({"highway": "secondary", "maxspeed": "45 mph", "shoulder": "both"})
        assert unmeasured.tier is Stress.LTS4
        assert "shoulder width" in unmeasured.assumed

    def test_a_shoulder_never_improves_a_way_that_is_already_lowest_stress(self) -> None:
        quiet = classify({"highway": "residential", "shoulder": "both", "shoulder:width": "2.0"})
        assert quiet.tier is Stress.LTS1

    def test_the_rural_speed_defaults_are_not_the_urban_ones(self) -> None:
        """The same `unclassified` tag covers a 25 mph District side street and a
        50 mph Loudoun through road. Assuming the urban figure everywhere put
        Snickersville Turnpike and Mountain Road at LTS1."""
        tags = {"highway": "unclassified"}
        assert classify(tags, urban=True).tier is Stress.LTS3
        assert classify(tags, urban=False).tier is Stress.LTS4
        assert "maxspeed" in classify(tags, urban=False).assumed

    def test_an_unpaved_rural_lane_is_clamped_below_the_lts4_boundary(self) -> None:
        """Virginia's statutory default on a highway that is not surface treated
        is 35, not 55. The roads the rural references ride - Hibbs Bridge,
        Featherbed, Mountain Road - are tagged unclassified or tertiary with
        surface=gravel, so the farm-track carve-out never reached them, and
        reading the boundary as exactly 35 painted every gravel road in Loudoun
        as an arterial.
        """
        paved = classify({"highway": "tertiary"}, urban=False)
        gravel = classify({"highway": "tertiary", "surface": "gravel"}, urban=False)
        assert paved.tier is Stress.LTS4
        assert gravel.tier < Stress.LTS4

    def test_the_clamp_does_not_apply_in_town(self) -> None:
        """An urban unpaved street is not a rural lane, and the statute it comes
        from is about rural highways."""
        assert UNPAVED_RURAL_DEFAULT_MPH < 35.0
        urban_gravel = classify({"highway": "tertiary", "surface": "gravel"}, urban=True)
        assert urban_gravel.tier is Stress.LTS3, "unchanged by the rural clamp"

    def test_cycleway_no_does_not_count_as_a_facility(self) -> None:
        """A tag asserting the *absence* of a facility is not a facility. Testing
        the raw value set let cycleway=no skip the volume modifier the rural
        position depends on."""
        quiet_road = {"highway": "unclassified", "maxspeed": "30 mph", "cycleway": "no"}
        result = classify(quiet_road, aadt=400, aadt_source="vdot")
        assert "low volume" in result.rule

        with_lane = classify({**quiet_road, "cycleway": "lane"}, aadt=400, aadt_source="vdot")
        assert "low volume" not in with_lane.rule, "a real facility does suppress it"

    def test_an_absent_surface_is_unknown_rather_than_paved(self) -> None:
        """The None-versus-False distinction the rural ranking keys on. Both are
        falsy, so `assert is_unpaved(tags)` cannot see it."""
        assert is_unpaved({}) is None
        assert is_unpaved({"surface": "asphalt"}) is False
        assert is_unpaved({"surface": "gravel"}) is True

    def test_an_unknown_bike_lane_width_is_read_as_narrow(self) -> None:
        """The conservative default, and the common case in this region's
        tagging."""
        unmeasured = classify({"highway": "tertiary", "maxspeed": "25 mph", "cycleway": "lane"})
        assert unmeasured.tier is Stress.LTS2
        assert "cycleway width" in unmeasured.assumed

        surveyed = classify(
            {
                "highway": "tertiary",
                "maxspeed": "25 mph",
                "cycleway": "lane",
                "cycleway:width": "2.0",
                "parking:lane:both": "no",
            }
        )
        assert surveyed.tier is Stress.LTS1

    def test_a_motorway_is_top_tier(self) -> None:
        assert classify({"highway": "motorway"}).tier is Stress.LTS4
        assert classify({"highway": "motorway"}).is_top_tier

    def test_the_volume_source_travels_onto_the_result(self) -> None:
        """A reviewer comparing a tier against crash history needs to know which
        agency's count produced it."""
        result = classify(
            {"highway": "unclassified", "maxspeed": "30 mph"}, aadt=400, aadt_source="vdot"
        )
        assert result.volume_source == "vdot"
        assert classify({"highway": "unclassified"}).volume_source is None
