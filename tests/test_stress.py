"""Stress classifier tests.

Written around the cases this region actually produces, and around the ordering
the plan fixes: speed, then facility, then volume, then surface.
"""

from __future__ import annotations

import pytest

from routemaker.stress import (
    DEFAULT_LANES_PER_DIRECTION,
    DEFAULT_MAXSPEED_MPH_RURAL,
    DEFAULT_MAXSPEED_MPH_UNKNOWN_RURAL,
    DEFAULT_MAXSPEED_MPH_UNKNOWN_URBAN,
    DEFAULT_MAXSPEED_MPH_URBAN,
    FURTH_LANE_ALONE_M,
    FURTH_LANE_BESIDE_PARKING_M,
    PAINTED_CYCLEWAY,
    RIDEABLE_SHOULDER_M,
    SEPARATED_CYCLEWAY,
    UNPAVED_RURAL_DEFAULT_MPH,
    VOLUME_BUSY,
    VOLUME_QUIET,
    Stress,
    classify,
    is_rough,
    is_unpaved,
)
from routemaker.tags import (
    IMPLICIT_MAXSPEED_MPH,
    cycleway_values,
    cycleway_width_m,
    has_parking_lane,
    has_shoulder,
    lanes_per_direction,
    parse_maxspeed_mph,
    parse_width_m,
    shoulder_width_m,
)


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

    def test_cycleway_separate_rates_the_roadway_as_the_roadway_it_is(self) -> None:
        """`separate` is a pointer to another OSM way, not a facility on this one.

        Round 5's B1, on the two roads it was measured on. `cycleway=separate`
        says the cycle facility is mapped as its own way somewhere alongside;
        it says nothing whatever about the carriageway, and the separate way
        already carries its own trail-class LTS1 at the top of `classify`.
        Reading it here as a separated track rated a 45 mph six-lane primary
        LTS1 - level with a protected track, three tiers below the same road
        bare - and, because any cycleway value counts as a provision, shut the
        volume gate on it too.
        """
        arterial = {"highway": "primary", "maxspeed": "45 mph", "lanes": "6"}
        bare = classify(arterial)
        separate = classify({**arterial, "cycleway": "separate"})
        assert bare.tier is Stress.LTS4
        assert separate.tier is bare.tier, "the roadway is scored as the roadway it is"
        assert separate.is_top_tier

        # And the gate it also shut: a cycleway value counts as a provision, so
        # reading `separate` as one exempted the road from the volume modifier.
        quiet = {"highway": "unclassified", "maxspeed": "30 mph"}
        assert classify(quiet, aadt=900).tier is Stress.LTS2, "the low-volume relief"
        assert classify({**quiet, "cycleway": "separate"}, aadt=900).tier is Stress.LTS2

        # A 25 mph street, where the misreading is quieter but the same: LTS2
        # mixed traffic, not the LTS1 a real track alongside would earn.
        street = {"highway": "residential", "maxspeed": "25 mph"}
        assert classify({**street, "cycleway": "separate"}).tier is Stress.LTS2
        assert classify({**street, "cycleway": "track"}).tier is Stress.LTS1

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

    def test_the_wider_direction_decides_when_both_are_tagged(self) -> None:
        """The two keys are the two directions of one way, not a fallback chain.

        A way is scored once for both: one tier is stored per way and a rider
        uses it either way round, so the direction that carries three lanes is
        the one the tier has to answer for. Returning whichever key was read
        first read `lanes:forward=1, lanes:backward=3` as a single-lane street,
        which is the lower-stress reading of an unambiguous input.
        """
        assert lanes_per_direction({"lanes": "4", "lanes:forward": "1", "lanes:backward": "3"}) == 3
        assert lanes_per_direction({"lanes": "4", "lanes:forward": "3", "lanes:backward": "1"}) == 3

    def test_a_direction_tagged_with_no_lanes_still_has_one(self) -> None:
        """The floor under the directional read, which had nothing holding it.

        `lanes:backward=0` is ordinary OSM: it is how a mapper says a signed
        one-way carries nothing the other way, and it arrives beside a `lanes`
        count that does not agree with it. Without the floor the function
        returns zero lanes in the direction of travel, which is not a road -
        and every Furth comparison downstream is written as `lanes > 1` or
        `lanes <= 1`, so a zero reads as the *quietest* possible road and the
        classifier says so with no assumption recorded.

        The same floor is on both `lanes` branches below, where it is exercised
        by `lanes=1` on a two-way street (1 // 2 == 0). Only the directional
        branch had no case at all, so `max(1, max(directional))` could lose its
        `max(1, ...)` with the suite green.
        """
        assert lanes_per_direction({"lanes": "1", "oneway": "yes", "lanes:backward": "0"}) == 1
        assert lanes_per_direction({"lanes": "2", "lanes:forward": "0", "lanes:backward": "0"}) == 1
        # And the tier that follows from it: one lane per direction, not none.
        result = classify(
            {
                "highway": "residential",
                "maxspeed": "25 mph",
                "lanes": "2",
                "lanes:forward": "0",
                "lanes:backward": "0",
                "parking:both": "no",
            }
        )
        assert result.tier is Stress.LTS2
        assert "single lane" in result.rule, result.rule
        assert "lanes" not in result.assumed, "the count was tagged; it is the floor that applies"

    def test_the_two_way_halving_is_floored_at_one_lane(self) -> None:
        """The other side of the same floor: `lanes=1` on a two-way street.

        A single-lane two-way street - an alley, a narrow residential block -
        halves to zero without it.
        """
        assert lanes_per_direction({"lanes": "1"}) == 1

    def test_a_road_and_its_mirror_image_take_the_same_tier(self) -> None:
        """Stated as the tier, because that is where it was visible: at 30 mph
        the mixed-traffic table turns on single lane against multilane, so the
        same road came out LTS3 with the three lanes tagged backward and LTS4
        with them tagged forward - one tier of difference decided by which side
        a mapper wrote first."""
        road = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "4"}
        forward = classify({**road, "lanes:forward": "1", "lanes:backward": "3"})
        backward = classify({**road, "lanes:forward": "3", "lanes:backward": "1"})
        assert forward.tier is backward.tier is Stress.LTS4
        assert "single lane" not in forward.rule
        assert "single lane" not in backward.rule


class TestMaxspeedParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("30 mph", 30.0),
            ("50 km/h", 31.07),
            ("50 kph", 31.07),
            ("US:urban", 25.0),
            # A bare number is mph in this coverage area, not km/h. The OSM
            # convention says km/h; there are no km/h signs in the DC metro, so
            # reading it that way turned a mistagged 45 mph arterial into 28 mph
            # and LTS2, which is the lower-stress reading of an ambiguous tag.
            ("45", 45.0),
            ("50", 50.0),
        ],
    )
    def test_units(self, value: str, expected: float) -> None:
        assert parse_maxspeed_mph(value) == pytest.approx(expected, abs=0.05)

    def test_a_unitless_speed_is_recorded_as_an_assumption(self) -> None:
        """The number was surveyed; the unit was not, and the tier rests on the
        reading this deployment chose."""
        bare = classify({"highway": "secondary", "maxspeed": "45"})
        assert bare.tier is Stress.LTS4
        assert "maxspeed unit" in bare.assumed
        assert "maxspeed" not in bare.assumed, "the speed itself was not assumed"

        explicit = classify({"highway": "secondary", "maxspeed": "45 mph"})
        assert "maxspeed unit" not in explicit.assumed

    def test_unparseable_is_unknown_not_slow(self) -> None:
        assert parse_maxspeed_mph("signals") is None

    def test_the_two_implicit_values_that_bracket_the_region(self) -> None:
        """`US:rural` and `DC:urban`, pinned flat at the numbers rather than at
        each other or at a default.

        The parametrised table above carries `US:urban` only, so every other
        entry in `IMPLICIT_MAXSPEED_MPH` could take any value with the suite
        green. These two are the ends of the range this deployment reads, and
        they are the two where a wrong number moves a tier in the direction the
        module refuses: `US:rural` at 55 is what puts an unposted Loudoun
        through road in LTS4, and `DC:urban` at 20 is what a District street's
        LTS1 rests on - 25 there would push every unposted District residential
        street off the 20-mph-or-below row of the mixed-traffic table.
        """
        assert IMPLICIT_MAXSPEED_MPH["US:rural"] == 55.0
        assert IMPLICIT_MAXSPEED_MPH["DC:urban"] == 20.0
        assert parse_maxspeed_mph("US:rural") == 55.0
        assert parse_maxspeed_mph("DC:urban") == 20.0

    def test_an_implicit_value_is_not_an_assumption(self) -> None:
        """It is a posted speed stated in words, so nothing about it is guessed:
        `maxspeed` must not appear on the assumed list, and neither must
        `maxspeed unit` - the unit is part of the country code."""
        result = classify({"highway": "residential", "maxspeed": "DC:urban", "lanes": "2"})
        assert result.tier is Stress.LTS1
        assert result.assumed == ("parking",)


class TestTheSpeedDefaultForAnUnrecognisedHighwayClass:
    """`highway=road` is OSM for "a road, class unknown", and it is in neither
    default table.

    Both tables are `dict.get` calls with a literal fallback, and the rural
    fallback is the one that matters: outside an urban area an unknown class is
    read at 50 mph, which is the higher-stress reading and the only safe one for
    a way nobody has classified. Neither fallback was pinned, so either could be
    changed - or transposed with the other - with the suite green.
    """

    def test_the_two_fallbacks_are_the_numbers_they_are(self) -> None:
        assert DEFAULT_MAXSPEED_MPH_UNKNOWN_RURAL == 50.0
        assert DEFAULT_MAXSPEED_MPH_UNKNOWN_URBAN == 30.0
        assert "road" not in DEFAULT_MAXSPEED_MPH_RURAL, "it is the fallback being read"
        assert "road" not in DEFAULT_MAXSPEED_MPH_URBAN

    def test_an_unknown_class_outside_an_urban_area_is_read_at_fifty(self) -> None:
        """Through `classify`, on `highway=road` and `urban=False`.

        The mixed-traffic table cannot tell 50 from 35 - both are "35 mph or
        above" - so the reading is pinned on the bike-lane table as well, whose
        boundary is at 40: a painted lane of any width on this way is LTS4
        rather than the LTS3 a 35 mph way with the same lane would get.
        """
        result = classify({"highway": "road"}, urban=False)
        assert result.tier is Stress.LTS4
        assert "maxspeed" in result.assumed
        assert "mixed traffic, 35 mph or above" == result.rule

        with_lane = classify({"highway": "road", "cycleway": "lane"}, urban=False)
        assert with_lane.rule == "bike lane, 40 mph or above"
        posted_35 = classify({"highway": "road", "maxspeed": "35 mph", "cycleway": "lane"})
        assert posted_35.rule == "bike lane, 35 mph", "the boundary the reading clears"

    def test_inside_an_urban_area_the_same_class_is_read_at_thirty(self) -> None:
        """The other fallback, so that transposing the two fails here."""
        urban = classify({"highway": "road", "lanes": "2"}, urban=True)
        assert urban.tier is Stress.LTS3
        assert urban.rule == "mixed traffic, 30 mph, single lane"


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

    def test_a_rideable_shoulder_is_scored_on_the_bike_lane_table(self) -> None:
        """At 35 mph a rideable shoulder is the difference between LTS4 and LTS3,
        which is the discrimination a rural group ride most needs - and it comes
        from the bike-lane table, the same one a painted lane is scored on."""
        bare = classify({"highway": "secondary", "maxspeed": "35 mph"})
        assert bare.tier is Stress.LTS4

        with_shoulder = classify(
            {
                "highway": "secondary",
                "maxspeed": "35 mph",
                "shoulder": "both",
                "shoulder:width": "1.8",
            }
        )
        assert with_shoulder.tier is Stress.LTS3
        assert "paved shoulder" in with_shoulder.rule

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

    def test_a_shoulder_of_exactly_the_threshold_width_is_rideable(self) -> None:
        """The boundary, which is where a surveyed width most often lands: 1.2 m
        is the metric figure a shoulder is tagged with when somebody has
        measured it, so the tie is the common case rather than the corner one.

        `>` instead of `>=` moves every such road from LTS3 to LTS4 and the
        suite above stays green, because 1.8 and 0.4 are both away from the
        line. Named alongside the constant so the pair moves together.
        """
        assert RIDEABLE_SHOULDER_M == 1.2

        at_the_line = classify(
            {
                "highway": "secondary",
                "maxspeed": "35 mph",
                "shoulder": "both",
                "shoulder:width": str(RIDEABLE_SHOULDER_M),
            }
        )
        assert at_the_line.tier is Stress.LTS3
        assert "paved shoulder" in at_the_line.rule

        # And a hair under it is not, so the threshold is a threshold.
        just_under = classify(
            {
                "highway": "secondary",
                "maxspeed": "35 mph",
                "shoulder": "both",
                "shoulder:width": "1.19",
            }
        )
        assert just_under.tier is Stress.LTS4

    def test_an_untagged_shoulder_width_earns_no_credit(self) -> None:
        """Read as narrow, and recorded as an assumption so a reviewer can see
        the tier rested on one."""
        unmeasured = classify({"highway": "secondary", "maxspeed": "45 mph", "shoulder": "both"})
        assert unmeasured.tier is Stress.LTS4
        assert "shoulder width" in unmeasured.assumed

    def test_a_shoulder_never_raises_the_stress_of_the_road_it_is_on(self) -> None:
        """The bike-lane table reads an unmeasured door zone into a narrow lane,
        which is a statement about parked cars. A shoulder has none, so scoring
        it on that table may lower a tier and may never raise one."""
        bare = classify({"highway": "service"})
        assert bare.tier is Stress.LTS1
        quiet = classify({"highway": "service", "shoulder": "both", "shoulder:width": "2.0"})
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


class TestTheProvisionHierarchy:
    """A shoulder is weaker provision than a painted lane and may never rate safer.

    Round 3 found the classifier rating an eight-foot shoulder on a 55 mph
    eight-lane arterial LTS3 while the same road with a painted bike lane came
    out LTS4. `is_top_tier` is LTS4 only, and both Beginner's zero-top-tier
    invariant and the road-exposure report key on it, so the inversion routed
    Beginner onto Leesburg Pike and River Road and reported nothing.
    """

    LEESBURG_PIKE = {"highway": "primary", "maxspeed": "55 mph", "lanes": "8"}

    def test_a_shoulder_does_not_rescue_a_55_mph_eight_lane_arterial(self) -> None:
        bare = classify(self.LEESBURG_PIKE)
        shoulder = classify({**self.LEESBURG_PIKE, "shoulder": "both", "shoulder:width": "8'"})
        painted = classify({**self.LEESBURG_PIKE, "cycleway": "lane", "cycleway:width": "8'"})

        assert bare.tier is Stress.LTS4
        assert painted.tier is Stress.LTS4
        assert shoulder.tier is Stress.LTS4
        assert shoulder.is_top_tier, "what Beginner and the road-exposure report key on"

    def test_a_shoulder_does_not_rescue_a_multilane_road_at_30(self) -> None:
        """The lane-count half of the same inversion, below the 40 mph line.

        Both readings declare their parking absent, so the two provisions are
        measured against the same Furth width criterion and the only thing left
        between them is the lane count - which is what this test is about. See
        `test_a_shoulder_is_measured_against_furths_no_parking_width` for the
        one difference that is deliberately left in.
        """
        road = {"highway": "primary", "maxspeed": "30 mph", "lanes": "4", "parking:both": "no"}
        painted = classify({**road, "cycleway": "lane", "cycleway:width": "2.0"})
        shoulder = classify({**road, "shoulder": "both", "shoulder:width": "2.0"})
        assert shoulder.tier >= painted.tier

    @pytest.mark.parametrize("speed", ["15 mph", "20 mph", "25 mph", "30 mph", "35 mph", "45 mph"])
    @pytest.mark.parametrize("lanes", ["1", "2", "4", "8"])
    # 1.3 is the tie width: rideable (above `RIDEABLE_SHOULDER_M`) but below
    # Furth's narrowest criterion, so on a 25 mph single-lane road the table
    # returns exactly the tier mixed traffic already gave. See
    # `test_a_shoulder_that_ties_with_mixed_traffic_earns_nothing`.
    @pytest.mark.parametrize("width", ["1.3", "1.4", "2.4", "4.5"])
    @pytest.mark.parametrize("parking", [None, "no", "parallel"])
    @pytest.mark.parametrize("aadt", [None, 900, 1_500, 8_000, 12_000])
    def test_a_shoulder_never_rates_safer_than_the_same_road_with_a_bike_lane(
        self, speed: str, lanes: str, width: str, parking: str | None, aadt: int | None
    ) -> None:
        """The ordering property itself, asserted rather than spot-checked.

        Stated against the better of the two readings it sits between: the
        shoulder tier is never below the painted-lane tier for the same road and
        the same surveyed width, and never below the bare road either, so it
        cannot be used to claim provision that is not there.

        `aadt` is a parameter because round 4 found the inversion living in the
        branch this property did not reach. The volume modifier ran on any road
        with no *cycleway tag*, which a shouldered road does not have, so a
        shoulder took the bike-lane table's credit and the volume credit while a
        painted lane of the same width took only the first - and the property,
        run without a count on any road, could not see it. With the count in, the
        unfixed classifier fails this 26 times below `VOLUME_QUIET` and, through
        the adoption rule the fix also needed, 20 more times above `VOLUME_BUSY`.

        The painted lane it is compared against declares its parking absent
        **only where the road under test says nothing about parking**, and that
        one case is the only place the two provisions are read differently: on a
        road with no parking tags a shoulder is measured against Furth's
        no-parking width, because a parking lane cannot run beside one, while a
        bike lane there is measured, conservatively, against the wider
        criterion. Comparing the shoulder against *that* reading would not be
        comparing the same provision, it would be asserting that an unknown on
        one road governs the other; the one permitted consequence is pinned by
        name in `test_a_shoulder_is_measured_against_furths_no_parking_width`.

        Where the road *declares* its parking, present or absent, there is no
        unknown left to differ about and the comparison is against a painted
        lane on the same road, parking tag and all. Forcing `parking:both=no`
        onto the painted lane there was round 5's B2: it handed the bike lane
        the narrow-width relief on a road whose own tags deny it, so the
        property compared a shoulder beside a declared parking lane against a
        bike lane beside none, and could not see a 25 mph street with
        `parking:both=parallel` and a 2.4 m shoulder rating LTS1 against LTS2
        for the same width of paint.
        """
        road = {"highway": "secondary", "maxspeed": speed, "lanes": lanes}
        if parking is not None:
            road["parking:both"] = parking
        # The unknown-parking case, and only it, is compared against a lane that
        # declares its parking absent; see the docstring.
        painted_road = {**road, "parking:both": "no"} if parking is None else road

        bare = classify(road, aadt=aadt).tier
        painted = classify(
            {**painted_road, "cycleway": "lane", "cycleway:width": width}, aadt=aadt
        ).tier
        result = classify({**road, "shoulder": "both", "shoulder:width": width}, aadt=aadt)
        shoulder = result.tier

        assert shoulder >= min(bare, painted), (
            f"shoulder {shoulder!r} beats both bare {bare!r} and painted {painted!r}"
        )
        # And never worse than the same road with no shoulder at all. A strip of
        # asphalt at the edge of a road cannot make it more hostile than no
        # strip would, whether the strip earned the table or not - which is also
        # what catches `<` widened to `<=` at the adoption test, where a tie
        # takes the exemption from the volume gate without moving the tier.
        assert shoulder <= bare, f"a shoulder rated the road {shoulder!r}, worse than {bare!r}"
        if painted <= bare:
            assert shoulder >= painted, "a shoulder outranking a bike lane is the inversion"
        else:
            # The 280 of 1440 combinations the condition above excludes, given
            # their own assertion rather than passed over in silence.
            #
            # `painted > bare` is Furth's table rating a bike lane worse than no
            # provision at all - a lane narrower than his criterion is LTS2 at
            # any speed, while a calm street with nothing on it is LTS1 - and
            # the shoulder branch does not follow it there, because a shoulder
            # is floored against the bare road and a bike lane is not. That
            # floor is this module's own rule and not Furth's; it is an owner
            # decision, argued in the module docstring and pinned by name in
            # `test_a_bike_lane_is_scored_on_furths_table_without_the_shoulders_floor`.
            #
            # So the two provisions genuinely part here, and what has to hold is
            # the shape of the parting: the shoulder sits at the bare tier, the
            # bike lane exactly one tier above it, and never at the top tier
            # that Beginner's invariant and the road-exposure report key on.
            # Without these three the branch is an open door - the same gap the
            # volume modifier's inversion lived in through round 4.
            assert shoulder == bare, (
                f"the shoulder floor did not hold: shoulder {shoulder!r}, bare {bare!r}"
            )
            assert int(painted) == int(bare) + 1, (
                f"the bike lane parted from the bare road by more than one tier: "
                f"painted {painted!r}, bare {bare!r}"
            )
            assert painted is not Stress.LTS4, (
                f"the unfloored reading reached the top tier: {painted!r}"
            )
        # And the other direction, which is how the same gap read above
        # `VOLUME_BUSY`: MacArthur Boulevard at 35 mph with an 8 ft shoulder and
        # AADT 12,000 came out LTS4 - `is_top_tier`, a well-shouldered arterial
        # in Beginner's gap warning - where the bike-laned version came out LTS3,
        # because the shoulder took the table's credit and then the volume bump
        # the bike lane was exempt from. Where the shoulder earned the table, the
        # table is the whole of what it earned.
        if "paved shoulder" in result.rule:
            assert shoulder <= painted, (
                f"a credited shoulder {shoulder!r} rates worse than the bike lane {painted!r} "
                f"it was scored on the same table as: {result.rule}"
            )
        else:
            # The other side of "one provision earns one credit": a shoulder
            # that did not take the table earned nothing, so the road is scored
            # exactly as one with no shoulder at all, volume gate included. The
            # adoption test is `<`, and widening it to `<=` leaves the tier
            # where it is while flipping `shoulder_credited` - so the road keeps
            # the mixed-traffic tier and silently loses the volume modifier,
            # which is this assertion and not the one above.
            assert shoulder == bare, (
                f"an uncredited shoulder {shoulder!r} did not score as the bare road {bare!r}: "
                f"{result.rule}"
            )

    def test_a_shoulder_is_measured_against_furths_no_parking_width(self) -> None:
        """The one difference between the two provisions, pinned rather than
        left to be rediscovered as an inversion.

        Furth has two width criteria: a bike lane running alongside a parking
        lane is measured as the bike lane plus the parking lane, and a bike lane
        with nothing parked beside it is measured on its own. A shoulder is
        always the second case - a shoulder is the outermost strip of the
        carriageway, so there is nothing between it and the kerb to park in - and
        a bike lane on a road whose parking nobody has tagged is read as the
        first, because unknown parking is read as present.

        So on a road with untagged parking a surveyed shoulder can come out a
        tier below a painted lane of identical width. That is a difference in
        what is known about the two roads and not a difference in the credit the
        provision earns, and it is the whole reason the ordering property
        compares against a lane that declares its parking absent.

        Before this, the door-zone criterion was applied to shoulders too, which
        made the shoulder credit inert below 35 mph on very nearly every road it
        was written for: parking is untagged on essentially every rural road, so
        an eight-foot shoulder had to clear 4.1 m to count as anything but
        narrow.
        """
        road = {"highway": "secondary", "maxspeed": "30 mph"}
        surveyed = {"shoulder": "both", "shoulder:width": "2.4"}

        assert classify(road).tier is Stress.LTS3
        assert classify({**road, **surveyed}).tier is Stress.LTS2, (
            "an eight-foot shoulder on a 30 mph two-lane road is not a door zone"
        )
        # The same width of painted lane, on the same untagged road, stays at the
        # conservative reading - there may be a parking lane beside it.
        assert classify({**road, "cycleway": "lane", "cycleway:width": "2.4"}).tier is Stress.LTS3
        # Declare the parking absent and the two provisions agree exactly.
        declared = {**road, "parking:both": "no"}
        assert classify({**declared, **surveyed}).tier is Stress.LTS2
        assert (
            classify({**declared, "cycleway": "lane", "cycleway:width": "2.4"}).tier is Stress.LTS2
        )

    def test_a_shoulder_beside_declared_parking_is_measured_against_the_wider_width(
        self,
    ) -> None:
        """Round 5's B2, the other half of the width question.

        The no-parking width is earned by a road that says nothing about
        parking, because a parking lane cannot run beside a shoulder. A road
        that *declares* a parking lane has said its outermost strip is occupied,
        so the width tag on it measures the parking lane, the door zone beside
        it, or the two together - which is the quantity Furth's beside-parking
        criterion is written against. The credit is not denied, it is measured
        properly: a strip wide enough to hold a parked car and a rider still
        earns the table.

        Measured before the fix: this street came out LTS1, a tier below the
        same street with a painted lane of identical width, and the Lua remap
        then wrote `cycleway=track` onto a street that declares a parking lane.
        """
        street = {"highway": "residential", "maxspeed": "25 mph", "parking:both": "parallel"}
        shoulder = classify({**street, "shoulder": "both", "shoulder:width": "2.4"})
        painted = classify({**street, "cycleway": "lane", "cycleway:width": "2.4"})

        assert shoulder.tier is Stress.LTS2
        assert painted.tier is Stress.LTS2
        assert shoulder.tier == painted.tier, (
            "with the parking declared there is no unknown left for the two to differ about"
        )
        # Not denied outright: a strip that clears the beside-parking criterion
        # earns exactly what a bike lane of that width earns.
        wide = classify({**street, "shoulder": "both", "shoulder:width": "4.5"})
        assert wide.tier is Stress.LTS1
        assert "paved shoulder" in wide.rule

        # And the unknown-parking road keeps the wave-3 reading, unchanged.
        untagged = {"highway": "residential", "maxspeed": "25 mph"}
        assert classify({**untagged, "shoulder": "both", "shoulder:width": "2.4"}).tier is (
            Stress.LTS1
        )

    def test_a_bike_lane_is_scored_on_furths_table_without_the_shoulders_floor(self) -> None:
        """The asymmetry between the two provisions, pinned as a decision.

        A shoulder is floored against the bare road - it may never rate a road
        worse than the same road with no shoulder at all - and a bike lane is
        not. So on a calm street the ordering the module keeps in every other
        band reverses: a 20 mph two-lane residential street that declares its
        parking absent is LTS1 bare, LTS1 with a 1.3 m shoulder, and LTS2 with
        1.3 m of paint. No unknown separates these three roads; they are the
        same road read three ways.

        This is Furth followed rather than a defect. His table rates a lane
        narrower than his criterion LTS2 at every speed, and mixed traffic at
        20 mph on a single lane per direction is LTS1; the deviation from the
        published tables is the shoulder's floor, which wave 5 adopted
        deliberately, on the argument that a strip of asphalt at the edge of a
        quiet street cannot make it more hostile than no strip would. Paint is
        the case where that argument runs out: a narrow lane invites traffic
        past at the width it claims.

        So the floor stays on the weaker provision only, and this test is what
        an attempt to make the two symmetric has to argue with. Adding the same
        `if lane_tier < mixed_tier` floor to the painted-lane branch of
        `classify` fails the last assertion here. The divergence is bounded -
        one tier, and never into `is_top_tier`, which the ordering property
        asserts across all 1440 of its combinations - and it is recorded as an
        owner decision rather than closed.
        """
        street = {
            "highway": "residential",
            "maxspeed": "20 mph",
            "lanes": "2",
            "parking:both": "no",
        }
        bare = classify(street)
        shoulder = classify({**street, "shoulder": "both", "shoulder:width": "1.3"})
        painted = classify({**street, "cycleway": "lane", "cycleway:width": "1.3"})

        assert bare.tier is Stress.LTS1
        # The floor, not the table: 1.3 m is rideable but under Furth's
        # criterion, so the table would have said LTS2 here too and the shoulder
        # declined it. Declining it also means the shoulder earned no credit at
        # all, which is why the rule text is still the mixed-traffic one.
        assert shoulder.tier is Stress.LTS1
        assert "paved shoulder" not in shoulder.rule, shoulder.rule
        # And the bike lane, read on the same table with the same width and the
        # same declared parking, takes what Furth's table says.
        assert painted.tier is Stress.LTS2
        assert painted.rule == "bike lane, narrow at 25 mph or below", painted.rule
        assert painted.tier > shoulder.tier, (
            "the floor is what separates them here, and it is on the shoulder branch only"
        )
        assert not painted.is_top_tier

    def test_a_shoulder_that_ties_with_mixed_traffic_earns_nothing(self) -> None:
        """F_STR8: the adoption test is `<`, and `<=` is not the same rule.

        A 25 mph single-lane street is LTS2 in mixed traffic, and a shoulder
        1.3 m wide - rideable, but under Furth's narrowest criterion - is LTS2
        on the bike-lane table too. On a tie the tier does not move, so `<=`
        looks harmless; what it does is flip `shoulder_credited`, which flips
        `has_facility`, which takes the road out of the volume gate. The street
        then keeps LTS2 at AADT 900 where the same street with no shoulder at
        all comes down to LTS1, and keeps LTS2 at AADT 12,000 where the bare
        street goes up to LTS3 - a strip of asphalt that earned nothing buying
        an exemption in both directions.
        """
        street = {"highway": "residential", "maxspeed": "25 mph", "parking:both": "no"}
        tie = {**street, "shoulder": "both", "shoulder:width": "1.3"}

        # The tie itself: neither reading is better than the other.
        assert classify(street).tier is Stress.LTS2
        assert classify(tie).tier is Stress.LTS2
        assert "paved shoulder" not in classify(tie).rule, "a tie is not a credit"

        # So the road is scored exactly as one with no shoulder, gate included.
        for aadt in (900, 12_000):
            assert classify(tie, aadt=aadt).tier is classify(street, aadt=aadt).tier
        assert classify(street, aadt=900).tier is Stress.LTS1, "the relief the bare road gets"
        assert classify(street, aadt=12_000).tier is Stress.LTS3, "and the bump"

        # A shoulder that does beat mixed traffic still takes the table, which
        # is the rule `<` implements and the reason it is not `<=`.
        credited = classify({**street, "shoulder": "both", "shoulder:width": "2.0"})
        assert credited.tier is Stress.LTS1
        assert "paved shoulder" in credited.rule

    def test_a_shoulder_earns_the_bike_lane_table_or_the_volume_gate_never_both(self) -> None:
        """B1 stated on the two roads the reviewer measured.

        One provision earns one credit. The volume modifier is for roads with no
        provision of their own, and it asked about cycleway tags rather than
        about provision, so a rideable shoulder took the bike-lane table's credit
        *and* the volume credit while a painted lane took only the first.
        """
        quiet = {
            "highway": "secondary",
            "maxspeed": "30 mph",
            "lanes": "2",
            "parking:lane:both": "no",
        }
        shoulder = {"shoulder": "both", "shoulder:width": "8'"}
        lane = {"cycleway": "lane", "cycleway:width": "8'"}

        # 30 mph, one lane each way, 8 ft shoulder, AADT 900. It came out LTS1:
        # level with a separated track, and a tier better than the same road with
        # a painted bike lane.
        assert classify({**quiet, **shoulder}, aadt=900).tier is Stress.LTS2
        assert classify({**quiet, **lane}, aadt=900).tier is Stress.LTS2
        assert classify({**quiet, "cycleway": "track"}, aadt=900).tier is Stress.LTS1, (
            "a separated track is still the only LTS1 provision on this road"
        )

        # MacArthur Boulevard: 35 mph, 8 ft shoulder, AADT 12,000. It came out
        # LTS4 where the bike-laned version came out LTS3, which puts a
        # well-shouldered arterial into `is_top_tier`.
        busy = {**quiet, "maxspeed": "35 mph"}
        shouldered = classify({**busy, **shoulder}, aadt=12_000)
        assert shouldered.tier is Stress.LTS3
        assert not shouldered.is_top_tier
        assert classify({**busy, **lane}, aadt=12_000).tier is Stress.LTS3

    def test_a_shoulder_that_earns_nothing_is_scored_as_a_road_with_no_shoulder(self) -> None:
        """The subtler half of the same gap, and the reason the flag is set by
        the branch rather than by the tag.

        A shoulder that does not beat plain mixed traffic has earned no credit,
        so it cannot hold the volume gate shut either: a 20 mph street at AADT
        12,000 took the mixed-traffic LTS1, declined the table's LTS2, and then
        skipped the high-volume bump that the same street with no shoulder and
        the same street with a bike lane both took.
        """
        street = {"highway": "residential", "maxspeed": "20 mph", "lanes": "2"}
        narrow = {"shoulder": "both", "shoulder:width": "1.4"}
        bare = classify(street, aadt=12_000)
        shouldered = classify({**street, **narrow}, aadt=12_000)

        assert bare.tier is Stress.LTS2, "the high-volume bump"
        assert shouldered.tier is Stress.LTS2
        assert "high volume" in shouldered.rule
        # And the shoulder still never makes the street worse than having none.
        assert classify({**street, **narrow}).tier == classify(street).tier

    def test_a_shoulder_width_in_feet_is_read_as_feet(self) -> None:
        """US shoulder widths are commonly tagged in feet, and the feet branch of
        the width parser feeds this credit."""
        road = {"highway": "secondary", "maxspeed": "35 mph", "shoulder": "both"}
        assert classify({**road, "shoulder:width": "8'"}).tier is Stress.LTS3
        assert classify({**road, "shoulder:width": "8 ft"}).tier is Stress.LTS3
        # Three feet is 0.91 m, below the rideable threshold, so no credit.
        assert classify({**road, "shoulder:width": "3ft"}).tier is Stress.LTS4

    def test_every_shoulder_presence_key_has_a_width_key(self) -> None:
        """A way tagged `shoulder:right=yes` with `shoulder:right:width=2.4` read
        as a shoulder of unknown width, so a surveyed shoulder earned nothing.

        The street is one-way so that each key form is tested on a road where a
        shoulder on that side is the shoulder of the only direction of travel.
        On a two-way street a single side key is not the road's provision at all
        (`TestTheWorstSideIsTheOneScored`), which would hide whether its width
        key had been read; here the side under test is the only width tagged, so
        dropping its key from `SHOULDER_WIDTH_KEYS` still fails the case.
        """
        for side in ("both", "left", "right"):
            surveyed = {
                "highway": "secondary",
                "maxspeed": "35 mph",
                "oneway": "yes",
                f"shoulder:{side}": "yes",
                f"shoulder:{side}:width": "2.4",
            }
            result = classify(surveyed)
            assert result.tier is Stress.LTS3, f"shoulder:{side}:width was not read"
            assert "shoulder width" not in result.assumed

    def test_the_narrowest_surveyed_shoulder_is_the_one_that_counts(self) -> None:
        """The route uses whichever side it uses, and the tile build cannot know."""
        widths = {"shoulder:left:width": "2.4", "shoulder:right:width": "0.5"}
        assert shoulder_width_m(widths) == 0.5


class TestThePathsToTopTier:
    """Every route to LTS4, on the boundary rather than beside it.

    Three of the five survived mutation in round 3: `>= 35` moved to `>= 45`,
    30 mph multilane moved to LTS3, and the high-volume bump was deleted, all
    with the suite green. 35 mph is the most common arterial posting in this
    region, so the boundary is where the tests belong.
    """

    def test_thirty_five_is_the_mixed_traffic_boundary(self) -> None:
        assert classify({"highway": "secondary", "maxspeed": "35 mph"}).tier is Stress.LTS4
        assert classify({"highway": "secondary", "maxspeed": "34 mph"}).tier is Stress.LTS3

    def test_thirty_is_the_multilane_boundary(self) -> None:
        single = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "2"}
        multi = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "4"}
        assert classify(single).tier is Stress.LTS3
        assert classify(multi).tier is Stress.LTS4
        assert classify({**multi, "maxspeed": "29 mph"}).tier is Stress.LTS3

    def test_twenty_is_the_quiet_street_boundary(self) -> None:
        single = {"highway": "residential", "lanes": "2"}
        assert classify({**single, "maxspeed": "20 mph"}).tier is Stress.LTS1
        assert classify({**single, "maxspeed": "21 mph"}).tier is Stress.LTS2
        multi = {"highway": "residential", "lanes": "4"}
        assert classify({**multi, "maxspeed": "20 mph"}).tier is Stress.LTS2
        assert classify({**multi, "maxspeed": "21 mph"}).tier is Stress.LTS3

    def test_forty_is_the_bike_lane_boundary(self) -> None:
        lane = {"highway": "primary", "cycleway": "lane", "cycleway:width": "2.0"}
        assert classify({**lane, "maxspeed": "40 mph"}).tier is Stress.LTS4
        assert classify({**lane, "maxspeed": "39 mph"}).tier is Stress.LTS3

    def test_a_motor_only_classification_is_top_tier_whatever_else_it_carries(self) -> None:
        assert classify({"highway": "motorway", "cycleway": "track"}).tier is Stress.LTS4

    def test_the_high_volume_bump_sits_exactly_on_volume_busy(self) -> None:
        road = {"highway": "unclassified", "maxspeed": "25 mph", "lanes": "2"}
        assert classify(road).tier is Stress.LTS2
        assert classify(road, aadt=VOLUME_BUSY - 1).tier is Stress.LTS2
        on_the_line = classify(road, aadt=VOLUME_BUSY)
        assert on_the_line.tier is Stress.LTS3
        assert "high volume" in on_the_line.rule

    def test_the_bump_can_reach_top_tier(self) -> None:
        """The fifth path, and the one the e2e test's `>= 3` was too weak to see."""
        road = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "2"}
        assert classify(road).tier is Stress.LTS3
        assert classify(road, aadt=20_000).tier is Stress.LTS4
        assert classify(road, aadt=20_000).is_top_tier

    def test_the_bump_never_climbs_past_top_tier(self) -> None:
        assert classify({"highway": "secondary", "maxspeed": "55 mph"}, aadt=90_000).tier is (
            Stress.LTS4
        )

    def test_the_relief_sits_exactly_on_volume_quiet(self) -> None:
        road = {"highway": "unclassified", "maxspeed": "30 mph", "lanes": "2"}
        assert classify(road).tier is Stress.LTS3
        assert classify(road, aadt=VOLUME_QUIET).tier is Stress.LTS2
        assert classify(road, aadt=VOLUME_QUIET + 1).tier is Stress.LTS3


class TestTheConstantsThePlanNames:
    """A flat table of values, because every rule above computes its boundary
    from the constant it is testing and so cannot see it move."""

    def test_the_furth_volume_thresholds(self) -> None:
        assert VOLUME_QUIET == 1_500
        assert VOLUME_BUSY == 8_000

    def test_the_rideable_shoulder_width(self) -> None:
        assert RIDEABLE_SHOULDER_M == 1.2

    def test_the_unpaved_rural_default_is_below_the_lts4_boundary(self) -> None:
        assert UNPAVED_RURAL_DEFAULT_MPH == 30.0
        assert UNPAVED_RURAL_DEFAULT_MPH < 35.0

    def test_one_lane_per_direction_is_the_default(self) -> None:
        assert DEFAULT_LANES_PER_DIRECTION == 1

    @pytest.mark.parametrize(
        ("highway", "urban", "rural"),
        [
            ("residential", 25.0, 25.0),
            ("living_street", 15.0, 15.0),
            ("track", 15.0, 15.0),
            ("service", 20.0, 20.0),
            ("unclassified", 30.0, 50.0),
            ("tertiary", 30.0, 50.0),
            ("secondary", 35.0, 55.0),
            ("primary", 40.0, 55.0),
            ("trunk", 45.0, 55.0),
            ("trunk_link", 45.0, 55.0),
        ],
    )
    def test_the_default_speed_tables(self, highway: str, urban: float, rural: float) -> None:
        assert DEFAULT_MAXSPEED_MPH_URBAN[highway] == urban
        assert DEFAULT_MAXSPEED_MPH_RURAL[highway] == rural

    def test_trunk_is_in_both_tables(self) -> None:
        """US-1, US-50 and New York Avenue NE are trunk here. Falling through to
        the table default read them as 30 mph urban streets."""
        for table in (DEFAULT_MAXSPEED_MPH_URBAN, DEFAULT_MAXSPEED_MPH_RURAL):
            assert "trunk" in table and "trunk_link" in table
        assert classify({"highway": "trunk"}).tier is Stress.LTS4
        assert classify({"highway": "trunk"}, urban=False).tier is Stress.LTS4


class TestEvidenceIsNotOnlyAllowedToHurt:
    """A real count on a road with no posted speed.

    The relief was gated on `speed_mph <= 35`, which reads whichever speed is in
    hand - and on a rural road with nothing posted that is the assumed 50, which
    can never be <= 35. So a VDOT count could only ever raise a tier, never
    lower one, on exactly the roads the comment above it was written for.
    """

    SNICKERSVILLE = {"highway": "unclassified"}  # no maxspeed, western Loudoun

    def test_a_real_count_relieves_an_assumed_speed(self) -> None:
        assumed = classify(self.SNICKERSVILLE, urban=False)
        assert assumed.tier is Stress.LTS4
        assert "maxspeed" in assumed.assumed

        counted = classify(self.SNICKERSVILLE, aadt=900, aadt_source="vdot", urban=False)
        assert counted.tier is Stress.LTS3
        assert "low volume" in counted.rule
        assert counted.volume_source == "vdot"

    def test_a_posted_fast_road_is_not_relieved_by_a_low_count(self) -> None:
        """Speed outranks volume: a two-lane road posted at 50 is hostile at
        almost any count, and that is the one case the gate exists for."""
        posted = {"highway": "unclassified", "maxspeed": "50 mph"}
        assert classify(posted, aadt=900, aadt_source="vdot").tier is Stress.LTS4

    def test_a_posted_slow_road_is_still_relieved(self) -> None:
        posted = {"highway": "unclassified", "maxspeed": "35 mph"}
        assert classify(posted).tier is Stress.LTS4
        assert classify(posted, aadt=900, aadt_source="vdot").tier is Stress.LTS3

    def test_the_bump_applies_whatever_the_speed_was(self) -> None:
        """Deliberately ungated: it moves in the conservative direction, so an
        assumed speed cannot be laundered through it."""
        quiet_default = classify({"highway": "residential"})
        assert quiet_default.tier is Stress.LTS2
        assert classify({"highway": "residential"}, aadt=20_000).tier is Stress.LTS3


class TestRoughIsNotComfortable:
    """`is_rough` was computed beside the tier and never touched it.

    A grade5 dirt farm track classified LTS1 through the `track: 15.0` speed
    default - exactly the reading `classes.py` keeps `track` out of TRAIL_CLASS
    to prevent, reached by another route.
    """

    def test_a_rutted_farm_track_is_not_tolerable_to_a_child(self) -> None:
        rutted = classify({"highway": "track", "surface": "dirt", "tracktype": "grade5"})
        assert rutted.tier is Stress.LTS2
        assert "rough surface" in rutted.rule

    def test_a_maintained_gravel_track_still_moves_nothing(self) -> None:
        """Gravel here is a low-traffic choice rather than a hazard, which is the
        distinction the rural references rest on."""
        maintained = classify({"highway": "track", "surface": "gravel", "tracktype": "grade2"})
        assert maintained.tier is Stress.LTS1

    def test_the_floor_never_reaches_past_lts2(self) -> None:
        """Surface is not stress: it floors LTS1 and leaves every other tier."""
        road = {"highway": "secondary", "maxspeed": "35 mph", "surface": "dirt"}
        assert classify(road).tier is Stress.LTS4

    def test_a_trail_is_not_floored_by_its_surface(self) -> None:
        """A dirt singletrack is what a Trailmaxxing rider came for; the surface
        floor that belongs on it is Group Ride's ridability dial at layer 4."""
        assert classify({"highway": "path", "surface": "dirt", "smoothness": "very_bad"}).tier is (
            Stress.LTS1
        )

    @pytest.mark.parametrize(
        "tags",
        [
            {"surface": "dirt"},
            {"tracktype": "grade5"},
            {"smoothness": "very_horrible"},
        ],
        ids=["surface", "tracktype", "smoothness"],
    )
    def test_each_clause_of_is_rough_stands_on_its_own(self, tags: dict[str, str]) -> None:
        """All three clauses survived deletion: `surface` alone cannot tell a
        maintained gravel road that twenty people ride two abreast from a rutted
        farm track, which is the whole reason the other two are read."""
        assert is_rough(tags)
        assert not is_rough({k: "grade1" if k == "tracktype" else "asphalt" for k in tags})


FOOT = 0.3048

# The width grammar, as one table, asserted here and in `tests/lua/test_remap.lua`
# against the same cases. Two parsers read these same OSM tags off the same
# extract - this one for `shoulder:*:width` and `cycleway:*:width`, the Lua one
# for a bollard's `maxwidth` - and round 5 found them disagreeing on four of
# these forms, in the dangerous direction both ways: `"8 feet"` was 8.0 metres
# here, a twenty-six-foot shoulder that clears Furth's widest criterion on a tag
# that says nothing of the kind, while `"2.4m"`, `"1,5"` and `5'6"` were
# unreadable here and read correctly there.
WIDTH_CASES: list[tuple[str, float]] = [
    # Feet, in the four forms the OSM wiki carries.
    ("3'", 3 * FOOT),
    ("8'", 8 * FOOT),
    ("3 ft", 3 * FOOT),
    ("8ft", 8 * FOOT),
    ("3feet", 3 * FOOT),
    ("8 feet", 8 * FOOT),
    # Feet and inches, the wiki's own imperial example.
    ("5'6\"", 5 * FOOT + 6 * FOOT / 12),
    ("5'6", 5 * FOOT + 6 * FOOT / 12),
    # Metres, bare and with the unit, and with a comma decimal separator.
    ("1.2", 1.2),
    ("2.4", 2.4),
    ("2 m", 2.0),
    ("2.4 m", 2.4),
    ("2.4m", 2.4),
    ("1,2", 1.2),
    ("1,5", 1.5),
]

# Everything else is unknown, never a guess: the module rule.
WIDTH_UNREADABLE: list[str | None] = [None, "", "wide", "ft", "1,5,2", "~2", "8 metres", "-2"]


class TestWidthParsing:
    """US widths are commonly tagged in feet, and the feet branch feeds the
    shoulder credit and the bike-lane door zone alike."""

    @pytest.mark.parametrize(("value", "expected"), WIDTH_CASES)
    def test_units(self, value: str, expected: float) -> None:
        assert parse_width_m(value) == pytest.approx(expected, abs=0.001)

    @pytest.mark.parametrize("value", WIDTH_UNREADABLE)
    def test_unreadable_is_unknown_rather_than_zero(self, value: str | None) -> None:
        assert parse_width_m(value) is None

    def test_a_shoulder_in_feet_is_not_read_as_that_many_metres(self) -> None:
        """What the disagreement cost, at the classifier rather than the parser.

        `"8 feet"` read as 8.0 metres clears `FURTH_LANE_BESIDE_PARKING_M` twice
        over, so a 30 mph road with an eight-foot shoulder beside a declared
        parking lane came out a tier better than the same eight feet written
        `8'`. The two spellings are the same shoulder.
        """
        road = {"highway": "secondary", "maxspeed": "30 mph", "parking:both": "parallel"}
        spelled = classify({**road, "shoulder": "both", "shoulder:width": "8 feet"})
        ticked = classify({**road, "shoulder": "both", "shoulder:width": "8'"})
        assert spelled.tier is ticked.tier
        assert spelled.tier is Stress.LTS3


class TestThePinnedFurthWidths:
    """A flat table of `assert CONSTANT == <the published figure>`.

    The two bike-lane width criteria were written inline at the comparison that
    used them, and a reviewer replaced them with 2.1 and 0.7 - half and a third
    of Furth's figures - with the whole suite green. Nothing pinned them and
    nothing measured a road near either boundary, so a door-zone stripe and a
    usable lane scored the same.

    The right-hand sides below are typed in from Furth, "Level of Traffic Stress
    Criteria for Road Segments, version 2.0" (2017), bike-lane table, converted
    from the published feet: a lane alongside a parking lane is measured as the
    bike lane plus the parking lane at 13.5 ft, and a lane with nothing parked
    beside it is measured on its own at 5.5 ft. They do not move when the
    constants do, which is what makes rescaling either one a failure here.
    """

    def test_the_beside_parking_criterion_is_furths(self) -> None:
        assert FURTH_LANE_BESIDE_PARKING_M == 4.1
        assert FURTH_LANE_BESIDE_PARKING_M == pytest.approx(13.5 * 0.3048, abs=0.03)

    def test_the_lane_alone_criterion_is_furths(self) -> None:
        assert FURTH_LANE_ALONE_M == 1.7
        assert FURTH_LANE_ALONE_M == pytest.approx(5.5 * 0.3048, abs=0.03)

    def test_the_two_criteria_are_the_boundaries_the_classifier_reads(self) -> None:
        """Pinned at the boundary, not beside it: each constant is asserted to be
        the exact width at which the tier moves, so rescaling either one moves a
        tier here even if the flat assertions above were edited to match."""
        beside = {"highway": "tertiary", "maxspeed": "25 mph", "cycleway": "lane"}
        assert classify({**beside, "cycleway:width": str(FURTH_LANE_BESIDE_PARKING_M)}).tier is (
            Stress.LTS1
        )
        assert (
            classify({**beside, "cycleway:width": str(FURTH_LANE_BESIDE_PARKING_M - 0.01)}).tier
            is Stress.LTS2
        )

        alone = {**beside, "parking:both": "no"}
        assert classify({**alone, "cycleway:width": str(FURTH_LANE_ALONE_M)}).tier is Stress.LTS1
        assert (
            classify({**alone, "cycleway:width": str(FURTH_LANE_ALONE_M - 0.01)}).tier
            is Stress.LTS2
        )


class TestHasShoulder:
    """The presence keys are sides, not alternatives, and a surveyed width is
    itself evidence of presence."""

    def test_a_side_specific_yes_outranks_a_general_no(self) -> None:
        """`shoulder=no` read first and returned, so a way a mapper had refined
        with `shoulder:right=yes` came out with no shoulder at all - the more
        specific tag losing to the more general one, which is backwards.

        The refinement is read *within a side*: on a one-way street, where the
        right-hand side is the side of the only direction of travel, the way has
        a shoulder. On a two-way street the same tags say the left side has none
        - which is the answer for the way, because a shoulder a rider heading
        the other way cannot reach is not a shoulder for that rider. Both halves
        are asserted here: reordering the body so the general `no` decides turns
        the one-way case False, and dropping the worst-side rule turns the
        two-way case True.
        """
        refined = {"shoulder": "no", "shoulder:right": "yes"}
        assert has_shoulder({**refined, "oneway": "yes"}) is True
        assert has_shoulder(refined) is False
        assert has_shoulder({"shoulder": "no"}) is False
        assert has_shoulder({"shoulder": "no", "shoulder:left": "none"}) is False

    def test_a_surveyed_width_is_presence(self) -> None:
        """`shoulder:width=2.4` with no presence key is a mapper who measured the
        shoulder and did not separately assert that it exists. Reading that as
        untagged threw away the only measurement on the way - and it is the
        measurement, not the presence key, that the bike-lane table needs."""
        assert has_shoulder({"shoulder:width": "2.4"}) is True
        assert has_shoulder({}) is None

    def test_a_measured_shoulder_with_no_presence_key_earns_its_credit(self) -> None:
        """Through `classify`, over a full tag dict, which is the level it takes
        effect at: at 35 mph this is the difference between LTS4 and LTS3."""
        road = {"highway": "secondary", "maxspeed": "35 mph"}
        assert classify(road).tier is Stress.LTS4
        result = classify({**road, "shoulder:width": "2.4"})
        assert result.tier is Stress.LTS3
        assert "paved shoulder" in result.rule
        assert "shoulder width" not in result.assumed

    def test_a_refined_side_earns_its_credit_over_a_general_no(self) -> None:
        """Through `classify`, on the one-way street where the refined side is
        the side the only direction of travel uses. The two-way case is the
        companion below: there the unrefined side is the road's provision."""
        road = {"highway": "secondary", "maxspeed": "35 mph", "oneway": "yes"}
        refined = {"shoulder": "no", "shoulder:right": "yes", "shoulder:right:width": "2.4"}
        assert classify({**road, **refined}).tier is Stress.LTS3

    def test_a_refinement_on_one_side_of_a_two_way_street_earns_nothing(self) -> None:
        """The same tags without `oneway`: a rider heading the other way is on
        the left, which the general `shoulder=no` says has nothing, so the road
        is scored as the bare arterial it is for that direction."""
        road = {"highway": "secondary", "maxspeed": "35 mph"}
        refined = {"shoulder": "no", "shoulder:right": "yes", "shoulder:right:width": "2.4"}
        assert classify(road).tier is Stress.LTS4
        assert classify({**road, **refined}).tier is Stress.LTS4


class TestTheSharedClassSets:
    """`classes.py`'s two frozensets, member by member and as a whole.

    Both are read by name and never enumerated, so dropping a member was free:
    removing `motorway_link` made an on-ramp LTS3 and `is_top_tier` False -
    admissible to Beginner, whose invariant is zero top-tier distance - and
    removing `steps` made a staircase fall through to the mixed-traffic table at
    the 30 mph urban default, scoring a flight of stairs as a road.

    The membership is pinned against a literal list as well as parametrised over
    it, because a test parametrised over the frozenset itself cannot catch a
    drop: the member that disappears takes its own test case with it.
    """

    # Typed in here, read from nothing.
    TRAIL_CLASS = ("cycleway", "footway", "path", "pedestrian", "bridleway", "steps")
    ALWAYS_TOP_TIER = ("motorway", "motorway_link")

    def test_the_trail_class_set_is_exactly_these(self) -> None:
        from routemaker.classes import TRAIL_CLASS_HIGHWAY

        assert TRAIL_CLASS_HIGHWAY == frozenset(self.TRAIL_CLASS)
        # `track` is deliberately absent: an unpaved vehicle way is not a trail,
        # and including it would rate a grade5 farm track comfortable for a child.
        assert "track" not in TRAIL_CLASS_HIGHWAY

    def test_the_always_top_tier_set_is_exactly_these(self) -> None:
        from routemaker.classes import ALWAYS_TOP_TIER_HIGHWAY

        assert ALWAYS_TOP_TIER_HIGHWAY == frozenset(self.ALWAYS_TOP_TIER)
        # `trunk` is deliberately absent: US-1, US-50 and New York Avenue NE are
        # trunk here and are routinely bicycle-legal, so a blanket rule would be
        # a derived access determination. They reach LTS4 on speed and lanes.
        assert "trunk" not in ALWAYS_TOP_TIER_HIGHWAY

    def test_the_tile_build_and_the_classifier_agree_on_trail_class(self) -> None:
        """Two modules each declared a trail-class set once, disagreed about
        `track`, and rated a farm track a comfortable trail in one and a roadway
        in the other. `variants` still declares its own; it has to stay equal to
        the shared one, and B2's roadway/sidepath guard reads the copy."""
        from pipeline.variants import TRAIL_CLASS_HIGHWAY as VARIANTS_SET
        from routemaker.classes import TRAIL_CLASS_HIGHWAY

        assert VARIANTS_SET == TRAIL_CLASS_HIGHWAY

    @pytest.mark.parametrize("highway", TRAIL_CLASS)
    def test_every_trail_class_member_classifies_as_a_trail(self, highway: str) -> None:
        result = classify({"highway": highway, "maxspeed": "45 mph", "lanes": "4"})
        assert result.tier is Stress.LTS1, f"{highway} fell through to the roadway tables"
        assert "trail-class way" in result.rule
        assert not result.is_top_tier

    @pytest.mark.parametrize("highway", ALWAYS_TOP_TIER)
    def test_every_always_top_tier_member_is_top_tier(self, highway: str) -> None:
        """Whatever else it carries - an on-ramp tagged `cycleway=track` by a
        mapper describing the trail that crosses it is still an on-ramp."""
        result = classify({"highway": highway, "cycleway": "track", "maxspeed": "25 mph"})
        assert result.tier is Stress.LTS4, f"{highway} was scored on its tags"
        assert result.is_top_tier
        assert "motor-only classification" in result.rule


class TestTheCyclewayWidthIsTheCyclewaysOwn:
    """The roadway's `width` is not the bike lane's width.

    The comment at the read has said so since round 3 and nothing asserted it:
    putting `tags.get("width")` back at the front of the chain - the exact bug
    the comment describes - left the suite green. It makes a four-lane arterial
    *lower* stress the moment someone surveys its carriageway, which is
    backwards, and it is the more common tag of the two in this region.
    """

    ARTERIAL = {
        "highway": "primary",
        "maxspeed": "25 mph",
        "lanes": "4",
        "cycleway": "lane",
        "parking:lane:both": "no",
    }

    def test_a_surveyed_carriageway_does_not_widen_the_bike_lane(self) -> None:
        surveyed_roadway = classify({**self.ARTERIAL, "width": "12"})
        assert surveyed_roadway.tier is Stress.LTS3, "the roadway's width was read as the lane's"
        assert "cycleway width" in surveyed_roadway.assumed
        # And the way it is meant to work: the cycleway's own width, which on
        # this road is the difference between LTS3 and LTS2.
        assert classify({**self.ARTERIAL, "cycleway:width": "2.0"}).tier is Stress.LTS2

    def test_a_surveyed_carriageway_changes_nothing_at_all(self) -> None:
        """Not merely "does not help": `width` is not an input to this table in
        either direction, so adding it moves no tier and clears no assumption."""
        for width in ("12", "3", "0.5"):
            assert classify({**self.ARTERIAL, "width": width}) == classify(self.ARTERIAL)

    @pytest.mark.parametrize(
        "key",
        ["cycleway:width", "cycleway:both:width", "cycleway:left:width", "cycleway:right:width"],
    )
    def test_every_cycleway_width_key_is_read(self, key: str) -> None:
        result = classify({**self.ARTERIAL, key: "2.0"})
        assert result.tier is Stress.LTS2, f"{key} was not read"
        assert "cycleway width" not in result.assumed


class TestTheNarrowestCyclewayWidthIsTheOneThatCounts:
    """`shoulder_width_m`'s rule, applied to the painted lane's four width keys.

    The four keys were a fallback chain walked until one of them answered, so
    the first key present decided. They are not alternatives: `cycleway:left`
    and `cycleway:right` are the two sides of one road, the way carries one
    tier, and the tile build does not know which side a route will use - which
    is the reason `shoulder_width_m` takes the minimum and is written at it.
    """

    # A 25 mph residential street with a painted lane and no parking, which is
    # where Furth's 1.7 m no-parking criterion is the difference between LTS1
    # and LTS2 - the pair of tiers the reviewer measured this on.
    STREET = {
        "highway": "residential",
        "maxspeed": "25 mph",
        "lanes": "2",
        "cycleway": "lane",
        "parking:both": "no",
    }

    def test_two_sides_are_read_as_the_narrower(self) -> None:
        assert cycleway_width_m({"cycleway:left:width": "2.0", "cycleway:right:width": "1.2"}) == (
            pytest.approx(1.2)
        )
        assert cycleway_width_m({"cycleway:right:width": "1.2", "cycleway:left:width": "2.0"}) == (
            pytest.approx(1.2)
        )

    def test_surveying_the_wider_side_does_not_lower_the_stress(self) -> None:
        """The measured case. A road whose right-hand lane is 1.2 m is LTS2; it
        was LTS1 and "adequate" the moment somebody also surveyed a 2.0 m lane
        on the left, because the left key was read first - so a measurement of
        the side the rider may not be on improved the tier of the side they may.
        """
        narrow_side_only = classify({**self.STREET, "cycleway:right:width": "1.2"})
        assert narrow_side_only.tier is Stress.LTS2
        both_sides = classify(
            {**self.STREET, "cycleway:left:width": "2.0", "cycleway:right:width": "1.2"}
        )
        assert both_sides.tier is narrow_side_only.tier
        assert both_sides.rule == narrow_side_only.rule

    def test_no_key_outranks_another(self) -> None:
        """The precedence, pinned: there is none. `cycleway:width` and
        `cycleway:both:width` each state the width of the lane on *each* side,
        so they enter the comparison as themselves rather than at the head of a
        chain, and the narrowest surveyed width is the answer whatever key
        carries it. Reversing the order of the keys must change nothing.
        """
        assert cycleway_width_m({"cycleway:width": "2.0", "cycleway:right:width": "1.2"}) == (
            pytest.approx(1.2)
        )
        assert cycleway_width_m({"cycleway:both:width": "2.0", "cycleway:left:width": "1.2"}) == (
            pytest.approx(1.2)
        )
        assert cycleway_width_m({"cycleway:right:width": "2.0", "cycleway:width": "1.2"}) == (
            pytest.approx(1.2)
        )

    def test_one_surveyed_side_is_still_a_surveyed_width(self) -> None:
        """The minimum is over the keys that are present, not over the four:
        reading an absent side as zero would make every one-sided lane narrow
        and put `cycleway width` back on the assumed list."""
        assert cycleway_width_m({"cycleway:left:width": "2.0"}) == pytest.approx(2.0)
        assert cycleway_width_m({}) is None
        result = classify({**self.STREET, "cycleway:left:width": "2.0"})
        assert result.tier is Stress.LTS1
        assert "cycleway width" not in result.assumed


class TestParkingAbsence:
    """Every value that says parking is absent, and every one that says it is not.

    Narrowing the absent set to {"no", "none", "separate"} left the suite green,
    and `no_parking`, `no_stopping` and `no_standing` are the values the District
    uses most. Reading them as parking *present* flips the bike-lane width
    criterion from Furth's 1.7 m to his 4.1 m - so a surveyed six-foot lane on a
    signed no-parking street reads as a door zone - and, worse, removes
    "parking" from the assumed list, so the result claims the input was measured
    while reading it backwards.
    """

    ABSENT = ("no", "none", "separate", "no_parking", "no_stopping", "no_standing")
    PRESENT = ("parallel", "diagonal", "perpendicular", "marked", "on_street", "half_on_kerb")

    @pytest.mark.parametrize("value", ABSENT)
    def test_values_that_say_parking_is_absent(self, value: str) -> None:
        assert has_parking_lane({"parking:lane:both": value}) is False

    @pytest.mark.parametrize("value", PRESENT)
    def test_values_that_say_parking_is_present(self, value: str) -> None:
        assert has_parking_lane({"parking:lane:both": value}) is True

    def test_nothing_at_all_is_unknown_rather_than_absent(self) -> None:
        """Absence of a `parking:*` tag is not evidence that parking is absent,
        which is why the classifier records it as an assumption."""
        assert has_parking_lane({}) is None
        assert "parking" in classify({"highway": "residential"}).assumed

    @pytest.mark.parametrize("value", ABSENT)
    def test_absence_reaches_the_bike_lane_table(self, value: str) -> None:
        """Through `classify` over a full tag dict, which is the level it takes
        effect at: a six-foot lane on a 25 mph street is LTS1 with no parking
        beside it and LTS2 if the door zone is read in."""
        street = {"highway": "tertiary", "maxspeed": "25 mph", "cycleway": "lane"}
        surveyed = {"cycleway:width": "1.8", "parking:lane:both": value}
        result = classify({**street, **surveyed})
        assert result.tier is Stress.LTS1, f"{value} was not read as parking absent"
        assert "parking" not in result.assumed, f"{value} was read but not recorded as measured"


class TestNoShoulderTagsMeanNoShoulder:
    """`has_shoulder` answers three ways and all three matter.

    Returning a bare `True` left the suite green: every road in the region then
    has a shoulder of unknown width, which earns no credit but does put
    "shoulder width" on the assumed list of every result the classifier
    produces, so a reviewer reading provenance sees a measurement that was never
    taken on a road that has nothing to measure.
    """

    def test_an_untagged_road_has_no_shoulder_and_claims_no_measurement(self) -> None:
        assert has_shoulder({}) is None
        result = classify({"highway": "secondary", "maxspeed": "35 mph"})
        assert "shoulder width" not in result.assumed
        assert "paved shoulder" not in result.rule

    def test_a_road_tagged_without_one_has_none(self) -> None:
        assert has_shoulder({"shoulder": "no"}) is False
        assert has_shoulder({"shoulder": "none"}) is False
        assert has_shoulder({"shoulder:both": "no"}) is False

    def test_a_road_tagged_with_one_has_one(self) -> None:
        assert has_shoulder({"shoulder": "both"}) is True
        # A side key answers for a one-way street, where that side is the side
        # of the only direction of travel. On a two-way street it is one
        # direction's shoulder and the other direction has none, which is False
        # and not None: the way has spoken about shoulders.
        assert has_shoulder({"shoulder:right": "yes", "oneway": "yes"}) is True
        assert has_shoulder({"shoulder:right": "yes"}) is False

    def test_a_surveyed_width_beats_a_shoulder_no_on_the_same_way(self) -> None:
        """The contradictory pair, and the one deliberate lower-stress reading
        in this module, so it is pinned rather than left to the docstring.

        `shoulder=no` with a `shoulder:width` is two tags that disagree, and the
        width is the survey: somebody went and measured a shoulder, which is not
        a thing done to a road that has none, while `shoulder=no` is what a
        mapper leaves behind after refining the way. The body reads every
        presence key *and* the width before answering; reordering it so the
        presence keys decide first turns this into `False` and throws the only
        measurement on the way away - and leaves `has_shoulder` disagreeing with
        `shoulder_width_m`, which reads the width whatever the presence keys
        say, so the classifier would see a road with no shoulder and a shoulder
        width.
        """
        contradictory = {"shoulder": "no", "shoulder:width": "2.4"}
        assert has_shoulder(contradictory) is True
        assert shoulder_width_m(contradictory) == pytest.approx(2.4)
        # And it is bounded: the width still has to clear the rideable
        # criterion before `stress` credits anything for it.
        road = {"highway": "secondary", "maxspeed": "35 mph"}
        assert classify({**road, **contradictory}).tier is Stress.LTS3
        narrow = {"shoulder": "no", "shoulder:width": str(RIDEABLE_SHOULDER_M - 0.01)}
        assert has_shoulder(narrow) is True
        assert classify({**road, **narrow}).tier is Stress.LTS4

    def test_shoulder_no_on_its_own_is_still_no_shoulder(self) -> None:
        """The other half, so the pin above cannot be satisfied by a bare
        `True`: without a width there is nothing to believe over the tag."""
        assert has_shoulder({"shoulder": "no"}) is False
        assert has_shoulder({"shoulder": "no", "shoulder:right": "no"}) is False


class TestTheCyclewayValueSets:
    """`SEPARATED_CYCLEWAY` and `PAINTED_CYCLEWAY`, member by member and as a whole.

    The same shape as `TestTheSharedClassSets`, and for the same reason: both
    sets are read by name and never enumerated, so dropping a member was free.
    A reviewer removed `opposite_track` - the value a contraflow cycle track on
    a one-way street carries, which is most of the District's protected network
    downtown - and the suite stayed green, because the value appeared nowhere in
    it. The membership is pinned against a literal list *and* parametrised over
    it: a test parametrised over the frozenset itself cannot catch a drop,
    because the member that disappears takes its own case with it.
    """

    # Typed in here, read from nothing.
    SEPARATED = ("track", "opposite_track")
    PAINTED = ("lane", "opposite_lane", "buffered_lane")

    # And the four tag forms a value can arrive in, typed in the same way and
    # for the same reason. `cycleway_values` reads a key list that nothing
    # enumerated: dropping `cycleway:left` and `cycleway:right` from it left the
    # whole suite green, because every case here wrote the bare `cycleway` key.
    # A side key is not an exotic spelling - it is what a mapper writes the
    # moment a street has a facility on one side only, which is most of the
    # District's network, and losing it takes a 25 mph one-way secondary with
    # `cycleway:left=track` from LTS1 to LTS3.
    KEYS = ("cycleway", "cycleway:both", "cycleway:left", "cycleway:right")

    # `cycleway` and `cycleway:both` speak for both sides of a road; the other
    # two speak for one side each, and on a two-way street one side is one
    # direction of travel, so a facility tagged there is not the road's
    # provision at all - which is `TestTheWorstSideIsTheOneScored`'s subject and
    # would make the cases below pass for the wrong reason. The cases below ask
    # only whether each key form is read and what each *value* means, so the
    # one-sided forms are put on a one-way street, where the tagged side is the
    # side of the only trip anyone makes on the way. That is also the shape the
    # value `opposite_lane` exists for.
    ONE_SIDED_KEYS = ("cycleway:left", "cycleway:right")

    @classmethod
    def way(cls, base: dict[str, str], key: str, value: str) -> dict[str, str]:
        tagged = {**base, key: value}
        if key in cls.ONE_SIDED_KEYS:
            tagged["oneway"] = "yes"
        return tagged

    def test_the_key_forms_are_exactly_these(self) -> None:
        """Pinned against the literal list, the way `SEPARATED` and `PAINTED`
        are: a key dropped from `cycleway_values` takes its own case with it if
        the test reads the key list from the code.

        On a one-way street, where the side a facility is tagged on is the side
        of the only direction of travel, so all four forms answer alike and the
        case is about whether the key is read at all. What each form means on a
        *two-way* street - where the sides are the two directions - is
        `TestTheWorstSideIsTheOneScored`.
        """
        for key in self.KEYS:
            assert cycleway_values({key: "track", "oneway": "yes"}) == {"track"}
        # And nothing else is read: `cycleway:left:width` is a width, not a
        # facility value, and `sidewalk` is not a cycleway.
        assert cycleway_values({"cycleway:left:width": "2.0", "sidewalk": "both"}) == set()

    def test_the_separated_set_is_exactly_these(self) -> None:
        assert SEPARATED_CYCLEWAY == frozenset(self.SEPARATED)
        # `separate` is deliberately absent, and its absence is the rule these
        # sets encode: the value says the facility is mapped as its own OSM way,
        # so it is a pointer to another object and describes nothing about this
        # carriageway. `tags.has_parking_lane` reads the identical idiom the
        # same way.
        assert "separate" not in SEPARATED_CYCLEWAY

    def test_the_painted_set_is_exactly_these(self) -> None:
        assert PAINTED_CYCLEWAY == frozenset(self.PAINTED)
        # `left` and `right` are key suffixes (`cycleway:left=lane`), never
        # values, and `cycleway_values` yields only values.
        assert not ({"left", "right", "separate"} & PAINTED_CYCLEWAY)

    def test_the_two_sets_are_disjoint(self) -> None:
        """The facility step tests them in order, so a value in both would be
        read as separated and its painted reading would be unreachable."""
        assert not (SEPARATED_CYCLEWAY & PAINTED_CYCLEWAY)

    @pytest.mark.parametrize("key", KEYS)
    @pytest.mark.parametrize("value", SEPARATED)
    def test_every_separated_member_rates_a_fast_arterial_lts1(self, value: str, key: str) -> None:
        """What separation means: a protected track is LTS1 at any speed the
        roadway carries, which is the whole of the distinction from paint.

        Every value in every key form, because the value set and the key list
        are two separate lists that both go unenumerated: a track on the left
        side of a road is a track.
        """
        arterial = {"highway": "primary", "maxspeed": "45 mph", "lanes": "6"}
        assert classify(arterial).tier is Stress.LTS4
        result = classify(self.way(arterial, key, value))
        assert result.tier is Stress.LTS1, f"{key}={value} did not read as separation"
        assert "separated track" in result.rule

    @pytest.mark.parametrize("key", KEYS)
    @pytest.mark.parametrize("value", PAINTED)
    def test_every_painted_member_takes_the_bike_lane_table(self, value: str, key: str) -> None:
        """Paint is not separation: the bike-lane table still rates 45 mph LTS4,
        and a wide lane on a quiet street LTS1, which mixed traffic would not.

        The width is tagged on the matching key form - `cycleway:left=lane` with
        `cycleway:left:width` - which is how a mapper writes a one-sided lane.
        """
        street = {"highway": "residential", "maxspeed": "25 mph", "parking:both": "no"}
        result = classify({**self.way(street, key, value), f"{key}:width": "2.0"})
        assert result.tier is Stress.LTS1, f"{key}={value} did not read as a painted lane"
        assert "bike lane" in result.rule
        fast = {"highway": "primary", "maxspeed": "45 mph"}
        assert classify(self.way(fast, key, value)).tier is Stress.LTS4

    @pytest.mark.parametrize("key", KEYS)
    @pytest.mark.parametrize("value", SEPARATED + PAINTED)
    def test_every_member_counts_as_a_provision_at_the_volume_gate(
        self, value: str, key: str
    ) -> None:
        """One provision earns one credit, and the gate reads the same sets the
        facility step does. A member missing from either is a road that takes
        the table's credit and the volume credit both."""
        quiet = {"highway": "unclassified", "maxspeed": "30 mph"}
        assert classify(quiet, aadt=900).tier is Stress.LTS2, "the relief this road gets bare"
        with_facility = classify(self.way(quiet, key, value), aadt=900)
        assert "low volume" not in with_facility.rule, f"{key}={value} took the volume credit"

    def test_a_one_sided_track_on_a_slow_secondary_is_lts1(self) -> None:
        """The measured case, stated on its own: a 25 mph one-way secondary with
        `cycleway:left=track` is LTS1, and went to LTS3 under the mutation that
        dropped the two side keys from `cycleway_values`. It is the ordinary
        shape of a contraflow or one-sided protected lane downtown.
        """
        street = {"highway": "secondary", "maxspeed": "25 mph", "oneway": "yes", "lanes": "2"}
        assert classify(street).tier is Stress.LTS3, "what the road is without the track"
        assert classify({**street, "cycleway:left": "track"}).tier is Stress.LTS1


class TestTheWorstSideIsTheOneScored:
    """One rule for both provisions: score the worst side a rider may be made
    to use.

    Presence and width had answered two different questions. `cycleway_values`
    and `has_shoulder` were a union over the four key forms - a facility
    anywhere on the way counted - while `cycleway_width_m` and
    `shoulder_width_m` took the minimum, the worst side. The two readings only
    coincide on a road tagged the same on both sides, and where they parted,
    *building the second half of a facility raised the road's stress*. Measured,
    all three on the same 25 mph two-way secondary with no parking:

      - `cycleway:left=lane` at 2.0 m with `cycleway:right=no`: LTS1
      - `cycleway:both=lane` at 2.0 m and 1.2 m: LTS2
      - nothing at all: LTS2

    and the shoulder mirrors it at 30 mph (one 2.4 m side LTS2, 2.4 m and 1.3 m
    LTS3, bare LTS3). Worst of all, `cycleway:left=track` with
    `cycleway:right=no` on a 35 mph four-lane two-way secondary came out LTS1,
    three tiers below the bare road: the union kept the `track` and discarded
    the `no`.

    The rule now: on a two-way street each side is a direction of travel and one
    tier is stored per way, so a side with no facility - the key absent, or
    present and saying `no` - makes the way's provision that side's. A one-sided
    lane on a two-way street is mixed traffic for the rider heading the other
    way. Where both sides carry a facility the narrower is the width. On a
    one-way street there is one direction and one side in use, so either side
    answers for the way, which is what keeps the District's contraflow lanes
    reading as the facilities they are.
    """

    # The three cases the reviewer executed, on the roads they were executed on.
    STREET = {
        "highway": "secondary",
        "maxspeed": "25 mph",
        "lanes": "2",
        "parking:both": "no",
    }

    def test_a_lane_on_one_side_of_a_two_way_street_is_not_the_roads_provision(self) -> None:
        bare = classify(self.STREET)
        one_side = classify({**self.STREET, "cycleway:left": "lane", "cycleway:left:width": "2.0"})
        declared = classify(
            {
                **self.STREET,
                "cycleway:left": "lane",
                "cycleway:left:width": "2.0",
                "cycleway:right": "no",
            }
        )
        both_sides = classify(
            {
                **self.STREET,
                "cycleway:both": "lane",
                "cycleway:left:width": "2.0",
                "cycleway:right:width": "1.2",
            }
        )

        assert bare.tier is Stress.LTS2
        # It was LTS1 - better than the same street with lanes on both sides.
        assert one_side.tier is bare.tier
        assert one_side.rule == bare.rule, "a one-sided lane is mixed traffic the other way"
        # And saying so out loud changes nothing: an absent side and a side
        # tagged `no` are the same road. The union discarded the `no` outright.
        assert declared.tier is bare.tier
        # Provisioning the second side never raises the tier.
        assert both_sides.tier <= one_side.tier

    def test_a_shoulder_on_one_side_of_a_two_way_street_is_not_the_roads_provision(self) -> None:
        """The shoulder mirror of the case above, at 30 mph where Furth's
        no-parking width criterion separates the tiers."""
        road = {**self.STREET, "maxspeed": "30 mph"}
        bare = classify(road)
        one_side = classify({**road, "shoulder:left": "yes", "shoulder:left:width": "2.4"})
        both_sides = classify(
            {
                **road,
                "shoulder:both": "yes",
                "shoulder:left:width": "2.4",
                "shoulder:right:width": "1.3",
            }
        )

        assert bare.tier is Stress.LTS3
        # It was LTS2 - a tier better than the same road shouldered both sides.
        assert one_side.tier is bare.tier
        assert "paved shoulder" not in one_side.rule
        assert "shoulder width" not in one_side.assumed
        assert both_sides.tier <= one_side.tier

    def test_a_one_sided_track_does_not_rate_a_fast_arterial_lts1(self) -> None:
        """The worst of the three: three tiers, on the most common arterial
        posting in this region."""
        arterial = {"highway": "secondary", "maxspeed": "35 mph", "lanes": "4"}
        tagged = {**arterial, "cycleway:left": "track", "cycleway:right": "no"}
        assert classify(arterial).tier is Stress.LTS4
        assert classify(tagged).tier is Stress.LTS4
        # The same tags on a one-way street are a real protected track, because
        # there is no second direction to strand.
        assert classify({**tagged, "oneway": "yes"}).tier is Stress.LTS1

    def test_a_side_tagged_no_is_the_answer_for_the_way(self) -> None:
        """At the function, so the discarded value is visible rather than
        inferred from a tier: the weaker side's values are what comes back."""
        assert cycleway_values({"cycleway:left": "lane", "cycleway:right": "no"}) == {"no"}
        assert cycleway_values({"cycleway:left": "track"}) == set()
        assert cycleway_values({"cycleway:left": "track", "cycleway:right": "lane"}) == {"lane"}
        assert cycleway_values({"cycleway:both": "lane"}) == {"lane"}
        assert cycleway_values({"cycleway": "track"}) == {"track"}

    # The space the existing parametrised cases cover, as roads: every
    # mixed-traffic speed band, single and multilane, quiet and fast.
    ROADS = (
        {"highway": "residential", "maxspeed": "20 mph", "lanes": "2"},
        {"highway": "residential", "maxspeed": "20 mph", "lanes": "4"},
        {"highway": "secondary", "maxspeed": "25 mph", "lanes": "2"},
        {"highway": "secondary", "maxspeed": "30 mph", "lanes": "2"},
        {"highway": "secondary", "maxspeed": "30 mph", "lanes": "4"},
        {"highway": "secondary", "maxspeed": "35 mph", "lanes": "4"},
        {"highway": "primary", "maxspeed": "45 mph", "lanes": "6"},
        {"highway": "unclassified", "maxspeed": "30 mph"},
    )
    # Widths that clear Furth's no-parking criterion, so the facility is one the
    # road genuinely benefits from. A *narrow* lane is excluded deliberately and
    # only from the second half of the property: Furth's table rates a lane
    # narrower than his criterion LTS2 where calm mixed traffic is LTS1, this
    # module keeps that reading on the bike-lane branch with no floor under it
    # (an owner decision, pinned by
    # `test_a_bike_lane_is_scored_on_furths_table_without_the_shoulders_floor`),
    # so on a 20 mph street two narrow lanes really are a tier worse than none.
    ADEQUATE = "2.0"

    @pytest.mark.parametrize("road", ROADS)
    @pytest.mark.parametrize("value", ("track", "opposite_track", "lane", "buffered_lane"))
    @pytest.mark.parametrize("aadt", (None, 900, 12_000))
    def test_the_second_side_never_raises_the_tier(
        self, road: dict[str, str], value: str, aadt: int | None
    ) -> None:
        """The property, over the whole space and at every volume the gate
        reads: a facility on one side of a two-way street scores exactly as the
        bare road, and completing it can only help.

        The first half is the rule. The second is what the union broke: it was
        false at four points in this space before the fix, every one of them a
        road whose one-sided tagging beat its two-sided tagging.
        """
        base = {**road, "parking:both": "no"}
        one_side = {**base, "cycleway:left": value, "cycleway:left:width": self.ADEQUATE}
        both_sides = {
            **base,
            "cycleway:both": value,
            "cycleway:left:width": self.ADEQUATE,
            "cycleway:right:width": self.ADEQUATE,
        }

        bare_tier = classify(base, aadt=aadt).tier
        one_tier = classify(one_side, aadt=aadt).tier
        assert one_tier is bare_tier, "a one-sided facility is not a two-way road's provision"
        assert classify(both_sides, aadt=aadt).tier <= one_tier

    @pytest.mark.parametrize("road", ROADS)
    @pytest.mark.parametrize("width", ("2.4", "1.3"))
    def test_a_one_sided_shoulder_scores_as_no_shoulder(
        self, road: dict[str, str], width: str
    ) -> None:
        """The same property for the other provision, at a rideable width and at
        one below Furth's criterion. The shoulder branch carries this module's
        floor, so completing the shoulder can never raise the tier at either
        width."""
        base = {**road, "parking:both": "no"}
        one_side = {**base, "shoulder:right": "yes", "shoulder:right:width": width}
        both_sides = {**base, "shoulder:both": "yes", "shoulder:width": width}

        bare = classify(base)
        assert classify(one_side).tier is bare.tier
        assert classify(one_side).rule == bare.rule
        assert classify(both_sides).tier <= bare.tier

    def test_a_one_way_street_still_reads_the_side_it_has(self) -> None:
        """The regression the rule must not take with it. A contraflow lane on a
        one-way street is tagged on one side by definition - it is the whole of
        what `opposite_lane` and `opposite_track` mean, and most of the
        District's downtown protected network - and there is no second direction
        of travel to strand, so the one-sided reading is the correct one."""
        oneway = {"highway": "secondary", "maxspeed": "25 mph", "oneway": "yes", "lanes": "2"}
        assert classify(oneway).tier is Stress.LTS3
        assert classify({**oneway, "cycleway:left": "opposite_track"}).tier is Stress.LTS1
        single = {**oneway, "lanes": "1", "parking:both": "no"}
        assert classify(single).tier is Stress.LTS2
        contraflow = classify(
            {**single, "cycleway:left": "opposite_lane", "cycleway:left:width": "2.0"}
        )
        assert contraflow.tier is Stress.LTS1
        assert "bike lane" in contraflow.rule
        # `oneway=-1` is the same street drawn the other way round.
        assert classify({**oneway, "oneway": "-1", "cycleway:right": "track"}).tier is Stress.LTS1
        # And a one-way street with a shoulder on the side it has.
        shouldered = {**oneway, "maxspeed": "35 mph", "shoulder:right": "yes"}
        assert classify({**shouldered, "shoulder:right:width": "2.4"}).tier is Stress.LTS3
