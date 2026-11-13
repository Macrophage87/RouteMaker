"""Stress classifier tests.

Written around the cases this region actually produces, and around the ordering
the plan fixes: speed, then facility, then volume, then surface.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from routemaker import facility
from routemaker.stress import (
    DEFAULT_LANES_PER_DIRECTION,
    DEFAULT_MAXSPEED_MPH_RURAL,
    DEFAULT_MAXSPEED_MPH_UNKNOWN_RURAL,
    DEFAULT_MAXSPEED_MPH_UNKNOWN_URBAN,
    DEFAULT_MAXSPEED_MPH_URBAN,
    FURTH_LANE_BESIDE_PARKING_M,
    PAINTED_CYCLEWAY,
    RIDEABLE_SHOULDER_M,
    SEPARATED_CYCLEWAY,
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
    def test_busy_slow_grid_is_not_high_stress(self) -> None:
        """A congested downtown grid at 25 is not LTS4 however many cars are on it."""
        result = classify(
            {"highway": "residential", "maxspeed": "25 mph", "lanes": "2"}, aadt=12_000
        )
        assert result.tier < Stress.LTS4


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


class TestConservativeDefaults:
    def test_missing_tags_are_recorded_as_assumed(self) -> None:
        """A tier derived from assumptions must be distinguishable from one derived
        from tags, because a reviewer comparing it against crash history needs to
        know which it is."""
        result = classify({"highway": "residential"})
        assert "maxspeed" in result.assumed
        assert "lanes" in result.assumed


class TestLanesPerDirection:
    def test_two_way_lanes_are_halved(self) -> None:
        """`lanes` counts both directions, so comparing it raw against a per-direction
        table reads every two-way street one class worse than it is."""
        assert lanes_per_direction({"lanes": "2"}) == 1

    def test_oneway_lanes_are_not_halved(self) -> None:
        assert lanes_per_direction({"lanes": "2", "oneway": "yes"}) == 2

    @pytest.mark.parametrize("junction", ["roundabout", "circular"])
    def test_a_roundabout_s_lanes_are_not_halved(self, junction) -> None:
        """OWNER-DECISIONS 228: a roundabout is one-way unless tagged `oneway=no`."""
        assert lanes_per_direction({"lanes": "2", "junction": junction}) == 2
        assert lanes_per_direction({"lanes": "2", "junction": junction, "oneway": "no"}) == 1

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

    def test_the_two_way_halving_is_floored_at_one_lane(self) -> None:
        """The other side of the same floor: `lanes=1` on a two-way street.

        A single-lane two-way street - an alley, a narrow residential block -
        halves to zero without it.
        """
        assert lanes_per_direction({"lanes": "1"}) == 1

    def test_the_one_way_branch_is_floored_at_one_lane_too(self) -> None:
        """The third of the three returns, so the floor is a property of the
        function rather than of two of its branches.

        `lanes=0` beside `oneway=yes` is what a mapper writes on a one-way
        stretch with no through lane of its own - a service road, a bus gate, a
        block tagged mid-survey - and zero lanes in the direction of travel is
        not an answer this function can give. Every reader downstream asks
        `lanes > 1` or `lanes <= 1`, so a zero is indistinguishable from one
        there and the floor is invisible from the tier; it is visible here,
        which is where the function's own contract is.
        """
        assert lanes_per_direction({"lanes": "0", "oneway": "yes"}) == 1
        assert lanes_per_direction({"lanes": "0"}) == 1, "and the two-way branch agrees"

    def test_a_road_and_its_mirror_image_take_the_same_tier(self) -> None:
        """Stated as the tier, because that is where it was visible: at 30 mph
        the mixed-traffic table turns on single lane against multilane, so the
        same road came out LTS3 with the three lanes tagged backward and LTS4
        with them tagged forward - one tier of difference decided by which side
        a mapper wrote first."""
        road = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "4"}
        forward = classify_rural({**road, "lanes:forward": "1", "lanes:backward": "3"})
        backward = classify_rural({**road, "lanes:forward": "3", "lanes:backward": "1"})
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

    def test_a_shoulder_never_raises_the_stress_of_the_road_it_is_on(self) -> None:
        """The bike-lane table reads an unmeasured door zone into a narrow lane,
        which is a statement about parked cars. A shoulder has none, so scoring
        it on that table may lower a tier and may never raise one."""
        bare = classify({"highway": "service"})
        assert bare.tier is Stress.LTS1
        quiet = classify({"highway": "service", "shoulder": "both", "shoulder:width": "2.0"})
        assert quiet.tier is Stress.LTS1

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

    @pytest.mark.parametrize(
        ("tags", "want"),
        [
            # OWNER-DECISIONS 376, C: a track with no surface is read as unpaved ...
            ({"highway": "track"}, True),
            ({"highway": "track", "tracktype": "grade2"}, True),
            ({"highway": "track", "tracktype": "grade5"}, True),
            ({"highway": "track", "tracktype": "unknown"}, True),
            # ... unless it is grade1 (paved or nearly so), which stays unknown.
            ({"highway": "track", "tracktype": "grade1"}, None),
            # An explicit surface always wins, either way.
            ({"highway": "track", "surface": "asphalt"}, False),
            ({"highway": "track", "tracktype": "grade1", "surface": "gravel"}, True),
            ({"highway": "track", "surface": "paved"}, False),
            # No other way is inferred: a path, a footway, a road with no surface is unknown.
            ({"highway": "path"}, None),
            ({"highway": "footway"}, None),
            # OWNER-DECISIONS 448: a built bike facility with no surface is paved
            ({"highway": "cycleway"}, False),
            ({"highway": "path", "bicycle": "designated"}, False),
            ({"highway": "footway", "bicycle": "designated"}, False),
            ({"highway": "path", "bicycle": "yes"}, None),
            ({"highway": "footway", "bicycle": "dismount"}, None),
            ({"highway": "cycleway", "surface": "gravel"}, True),
            ({"highway": "path", "bicycle": "designated", "surface": "dirt"}, True),
            ({"highway": "residential", "bicycle": "designated"}, None),
            ({"highway": "residential"}, None),
            ({"highway": "service", "tracktype": "grade3"}, None),
            ({}, None),
        ],
    )
    def test_a_track_with_no_surface_is_inferred_unpaved(self, tags, want) -> None:
        """Only the stored column and the map read it: the classifier's own speed cap
        keeps reading `is_unpaved`, so a track's tier does not move."""
        from routemaker.stress import inferred_unpaved

        assert inferred_unpaved(tags) is want

    def test_the_marvin_gaye_trail_cycleway_with_no_surface_is_paved(self) -> None:
        """OWNER-DECISIONS 448: 19 of the trail's 23 ways (438819447 among them) are
        `highway=cycleway` with no surface tag; they are stored paved, so the map does not
        draw them as the dashed surface-unknown trail. A park footway beside is still unknown."""
        from routemaker.stress import inferred_unpaved, is_unpaved

        marvin_gaye = {"highway": "cycleway", "name": "Marvin Gaye Trail"}
        assert inferred_unpaved(marvin_gaye) is False
        assert is_unpaved(marvin_gaye) is None, "the classifier's raw reading is unchanged"
        assert inferred_unpaved({"highway": "footway", "name": "Park Footpath"}) is None

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
        # Unclassified: the hierarchy of the tables themselves, below the class
        # floors (items 141, 176), which `TestTheFloorsAndAShoulder` holds.
        road = {"highway": "unclassified", "maxspeed": speed, "lanes": lanes}
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

    def test_a_motor_only_classification_is_top_tier_whatever_else_it_carries(self) -> None:
        assert classify({"highway": "motorway", "cycleway": "track"}).tier is Stress.LTS4

    def test_the_bump_never_climbs_past_top_tier(self) -> None:
        assert classify({"highway": "secondary", "maxspeed": "55 mph"}, aadt=90_000).tier is (
            Stress.LTS4
        )


class TestTheConstantsThePlanNames:
    """A flat table of values, because every rule above computes its boundary
    from the constant it is testing and so cannot see it move."""

    def test_the_rideable_shoulder_width(self) -> None:
        assert RIDEABLE_SHOULDER_M == 1.2

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


class TestThePinnedFurthWidths:
    """A flat table of `assert CONSTANT == <the published figure>`.

    The two bike-lane width criteria were written inline at the comparison that
    used them, and a reviewer replaced them with 2.1 and 0.7 - half and a third
    of Furth's figures - with the whole suite green. Nothing pinned them and
    nothing measured a road near either boundary, so a door-zone stripe and a
    usable lane scored the same.

    The right-hand sides below are typed in from the published feet: a lane
    alongside a parking lane is measured by its reach, the bike lane plus the
    parking lane, and is adequate at 15 ft (Mekuria, Furth & Nixon, MTI Report
    11-19, 2012, Table 2: 15 ft or more LTS 1, 14 to 14.5 ft LTS 2, 13.5 ft or
    less LTS 3; the same line in Furth's v2.0 and v2.2 tables). Review r1 found
    it at 13.5 ft, the top of the narrow bin. A lane with nothing parked beside
    it is measured on its own at 5.5 ft. They do not move when the constants
    do, which is what makes rescaling either one a failure here.
    """

    def test_the_beside_parking_criterion_is_furths(self) -> None:
        assert FURTH_LANE_BESIDE_PARKING_M == pytest.approx(4.572, abs=0.001)
        assert FURTH_LANE_BESIDE_PARKING_M == pytest.approx(15 * 0.3048, abs=0.001)


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

    # One-way, two lanes: the bike-lane table's multilane row, where the lane's
    # width decides between LTS 3 and LTS 2. On a two-way street with two lanes
    # each way the owner's RL-3 floor holds a painted lane at LTS 3 whatever
    # its width (`TestAPaintedLaneOnAWideTwoWayStreet`).
    ARTERIAL = {
        "highway": "primary",
        "maxspeed": "25 mph",
        "lanes": "2",
        "oneway": "yes",
        "cycleway": "lane",
        "parking:lane:both": "no",
    }

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
        result = classify_rural({**self.ARTERIAL, key: "2.0"})
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


class TestParkingIsReadByPresenceAndSide:
    """Hunt 2, S2 and S3 (2026-11-08): `has_parking_lane` took every value under the
    `parking:*` prefixes and asked no side, so an attribute beside a `no` read as
    parking present, and parking across a one-way from its lane made the lane a
    door-zone lane: LTS 3 at 30 mph where the lane is LTS 2."""

    LANE = {
        "highway": "residential",
        "maxspeed": "30 mph",
        "cycleway:both": "lane",
        "cycleway:both:width": "1.8",
        "parking:both": "no",
    }

    @pytest.mark.parametrize(
        "extra",
        [
            {"parking:both:reason": "bike_lane"},
            {"parking:both:markings": "yes"},
            {"parking:both:fee": "no"},
            {"parking:left:zone": "A"},
        ],
    )
    def test_an_attribute_beside_a_no_is_not_parking(self, extra) -> None:
        assert has_parking_lane({"parking:both": "no", **extra}) is False
        # Before: LTS 3, "narrow or multilane at 30 mph".
        assert classify({**self.LANE, **extra}).tier is classify(self.LANE).tier is Stress.LTS2

    def test_an_orientation_alone_says_parking(self) -> None:
        assert has_parking_lane({"parking:right:orientation": "parallel"}) is True
        assert has_parking_lane({"parking:both:reason": "bike_lane"}) is None

    def test_the_current_scheme_speaks_before_the_older_one(self) -> None:
        assert has_parking_lane({"parking:both": "no", "parking:lane:both": "parallel"}) is False

    ONE_WAY = {
        "highway": "residential",
        "oneway": "yes",
        "maxspeed": "30 mph",
        "cycleway:left": "lane",
        "cycleway:left:width": "1.8",
        "parking:left": "no",
        "parking:right": "lane",
    }


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

    #
    # Except an `opposite*` value: on a one-way street it is the contraflow
    # rider's alone and the with-flow rider is scored (review RL-2), so a
    # one-sided key carrying one is put on a two-way street with the value on
    # both sides, each key form still read on its own side.
    @classmethod
    def way(
        cls, base: dict[str, str], key: str, value: str, width: str | None = None
    ) -> dict[str, str]:
        tagged = {**base, key: value}
        if width is not None:
            tagged[f"{key}:width"] = width
        if key in cls.ONE_SIDED_KEYS and value.startswith("opposite"):
            for side in cls.ONE_SIDED_KEYS:
                tagged[side] = value
                if width is not None:
                    tagged[f"{side}:width"] = width
        elif key in cls.ONE_SIDED_KEYS:
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
        assert classify_rural(street).tier is Stress.LTS3, "what the road is without the track"
        assert classify_rural({**street, "cycleway:left": "track"}).tier is Stress.LTS1


class TestTheWorstSideIsTheOneScored:
    """One rule for both provisions: score the worst side a rider may be made
    to use.

    Presence and width had answered two different questions. `cycleway_values`
    and `has_shoulder` were a union over the four key forms - a facility
    anywhere on the way counted - while `cycleway_width_m` and
    `shoulder_width_m` took the minimum, the worst side. The two readings only
    coincide on a road tagged the same on both sides, and where they parted,
    *building the second half of a facility raised the road's stress*. Measured,
    all three on the same 25 mph two-way secondary with no parking (a tertiary in the tests
    below since the arterial floor, OWNER-DECISIONS 141):

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
        "highway": "tertiary",  # not an arterial: the floor (item 141) is not the point here
        "maxspeed": "25 mph",
        "lanes": "2",
        "parking:both": "no",
    }

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


# --- "Legal but avoid" (the owner's fifth category, 2026-09-27) --------------

AVOID_BASE = {"highway": "trunk", "expressway": "yes", "oneway": "yes", "lanes": "2"}


@pytest.mark.parametrize("posted", ["50 mph", "55 mph", "65 mph", "55"])
def test_a_fast_expressway_is_legal_but_avoid(posted):
    from routemaker.stress import Stress, classify

    result = classify({**AVOID_BASE, "maxspeed": posted})
    assert result.tier is Stress.AVOID
    assert "legal but avoid" in result.rule and "Furth" in result.rule
    assert result.is_top_tier


@pytest.mark.parametrize(
    "tags",
    [
        {**AVOID_BASE, "maxspeed": "45 mph"},
        {**AVOID_BASE},  # unposted: never assumed into the category
        {**AVOID_BASE, "expressway": "no", "maxspeed": "50 mph"},
        {"highway": "secondary", "expressway": "yes", "maxspeed": "55 mph"},
        {"highway": "motorway", "expressway": "yes", "maxspeed": "55 mph"},
    ],
)
def test_everything_else_keeps_its_furth_tier(tags):
    from routemaker.stress import Stress, _classify, classify

    result = classify(tags)
    assert result.tier is not Stress.AVOID
    assert result == _classify(tags)


def classify_rural(tags, *args, **kwargs):
    """`classify` outside an urban area, where Furth's multilane rule stands
    (OWNER-DECISIONS 87/101: inside one the lane count is not scored). The
    Furth-table tests read the table as Furth wrote it."""
    from routemaker.stress import classify

    return classify(tags, *args, **{"urban": False, **kwargs})


def _classify_rural(tags, *args, **kwargs):
    from routemaker.stress import _classify

    return _classify(tags, *args, **{"urban": False, **kwargs})


def test_the_category_sits_above_the_furth_scale():
    from routemaker.stress import Stress

    assert Stress.AVOID > Stress.LTS4
    assert int(Stress.AVOID) == 5


@pytest.mark.parametrize("highway", ["trunk", "trunk_link", "primary", "primary_link"])
def test_every_class_of_the_avoid_rule_takes_it(highway):
    """The ramps too (mutation review r1, S1): an expressway's link posted at
    50 is the same road to a bicycle."""
    from routemaker.stress import legal_but_avoid

    tags = {"highway": highway, "expressway": "yes", "maxspeed": "50 mph"}
    assert legal_but_avoid(tags) == "legal but avoid: expressway posted 50 mph"


# --- A rural expressway is LTS 4.5 (the owner, 2026-10-17) ----------------------
# "The rural road LTS 5s should be LTS4.5 they might be high stress, but there's
# often no way to avoid them."


def test_a_rural_expressway_is_lts4_and_a_half():
    from routemaker.stress import RURAL_EXPRESSWAY_PREFIX, Stress, legal_but_avoid

    tags = {**AVOID_BASE, "maxspeed": "55 mph"}
    result = classify_rural(tags)
    assert result.tier is Stress.LTS4 and result.half
    assert result.rule.startswith(f"{RURAL_EXPRESSWAY_PREFIX} 55 mph, often no way around")
    assert "Furth" in result.rule and "legal but avoid" not in result.rule
    assert legal_but_avoid(tags, urban=False) is None


def test_an_urban_expressway_is_still_avoid():
    from routemaker.stress import Stress, classify

    result = classify({**AVOID_BASE, "maxspeed": "55 mph"}, urban=True)
    assert result.tier is Stress.AVOID and not result.half
    assert result.rule.startswith("legal but avoid: expressway posted 55 mph")


def test_a_rural_motorway_open_to_bicycles_is_still_avoid():
    from routemaker.stress import MOTORWAY_AVOID_RULE, Stress

    result = classify_rural({"highway": "motorway", "maxspeed": "65 mph", "bicycle": "yes"})
    assert result.tier is Stress.AVOID and not result.half
    assert result.rule.startswith(MOTORWAY_AVOID_RULE)


def test_a_rural_expressway_with_its_side_path_is_still_avoid():
    from routemaker.stress import USE_SIDEPATH_RULE, Stress

    tags = {**AVOID_BASE, "maxspeed": "55 mph", "bicycle": "use_sidepath"}
    result = classify_rural(tags, side_path=True)
    assert result.tier is Stress.AVOID and not result.half
    assert result.rule.startswith(USE_SIDEPATH_RULE)


@pytest.mark.parametrize("tags", [{**AVOID_BASE, "maxspeed": "45 mph"}, {**AVOID_BASE}])
def test_a_slow_or_unposted_rural_expressway_keeps_its_furth_tier(tags):
    result = classify_rural(tags)
    assert not result.half and result == _classify_rural(tags)


# --- OWNER-DECISIONS 87 and 101: lane count in an urban area ------------------


class TestUrbanMultilane:
    """Inside an urban area a multi-lane street is read on the single-lane row;
    its speed and volume decide. Outside one, Furth's multilane rule stands."""

    street = {"highway": "unclassified", "maxspeed": "30 mph", "lanes": "2", "oneway": "yes"}

    def test_a_single_lane_street_is_unchanged(self) -> None:
        one = {**self.street, "lanes": "1"}
        assert classify(one, urban=True) == classify(one, urban=False)


# --- OWNER-DECISIONS 83, 84 and 101: a decent painted lane --------------------


class TestADecentLane:
    """MD 450 near Annapolis: 40 mph, two lanes one way, `cycleway:right=lane`
    and nothing more. The owner: "I'd probably say that's LTS3"."""

    md450 = {
        "highway": "primary",
        "maxspeed": "40 mph",
        "lanes": "2",
        "oneway": "yes",
        "cycleway:right": "lane",
    }

    @pytest.mark.parametrize(
        "extra",
        [
            {"cycleway:right": "buffered_lane"},
            {"cycleway:right:buffer": "yes"},
            {"cycleway:both:buffer": "0.5"},
            {"cycleway:buffer": "yes"},
        ],
    )
    def test_a_buffered_lane_is_decent_at_any_width(self, extra) -> None:
        narrow = {**self.md450, "cycleway:right:width": "1.2", **extra}
        assert classify(narrow).tier is Stress.LTS3

    def test_an_expressway_is_still_legal_but_avoid(self) -> None:
        road = {**self.md450, "highway": "trunk", "expressway": "yes", "maxspeed": "55 mph"}
        assert classify(road).tier is Stress.AVOID

    def test_below_forty_furths_table_is_unchanged(self) -> None:
        """Below 40 mph the table already gives a lane its credit; the rule
        never lowers a narrow lane at 30 or 35 (the door zone stands)."""
        for speed in ("25 mph", "30 mph", "35 mph"):
            road = {**self.md450, "maxspeed": speed, "cycleway:right:width": "1.0"}
            assert classify(road, urban=False) == classify(road, urban=False)
        assert classify({**self.md450, "maxspeed": "30 mph"}, urban=False).tier is Stress.LTS3
        assert classify({**self.md450, "maxspeed": "35 mph"}, urban=False).tier is Stress.LTS3


# --- OWNER-DECISIONS 108 and 112: statutory speed defaults -------------------


class TestSpeedDefaults:
    """DC: 20 mph on every street without a posted limit, 15 in alleys. MD and
    VA urban areas: 25 / 30 / 35 by class. Elsewhere the class tables stand."""

    @pytest.mark.parametrize(
        "highway", ["residential", "tertiary", "primary", "trunk", "unclassified"]
    )
    def test_an_unposted_dc_way_is_read_at_20(self, highway) -> None:
        result = classify({"highway": highway}, urban=True, jurisdiction="DC")
        assert result.rule.startswith("mixed traffic, 20 mph or below")
        assert "maxspeed" in result.assumed

    def test_a_zone_tag_names_the_default(self) -> None:
        road = {"highway": "primary", "maxspeed:type": "US-DC:urban"}
        assert classify(road, urban=True).rule.startswith("mixed traffic, 20 mph or below")
        road = {"highway": "residential", "source:maxspeed": "US-MD:urban"}
        assert classify(road, urban=True).rule.startswith("mixed traffic, 25 mph")

    @pytest.mark.parametrize(
        ("highway", "speed"),
        [
            ("residential", "25"),
            ("unclassified", "30"),
            ("tertiary", "30"),
            ("secondary", "35"),
            ("primary", "35"),
        ],
    )
    @pytest.mark.parametrize("state", ["MD", "VA", "WV"])
    def test_maryland_and_virginia_urban_defaults(self, highway, speed, state) -> None:
        # Virginia's and West Virginia's minor roads at their law's 25 (the owner,
        # 2026-10-31); Maryland keeps MDOT's 30.
        if state != "MD" and highway in ("unclassified", "tertiary"):
            speed = "25"
        rule = classify({"highway": highway}, urban=True, jurisdiction=state).rule
        assert f"{speed} mph" in rule or (speed == "35" and "35 mph or above" in rule)

    @pytest.mark.parametrize("highway", ["secondary", "tertiary", "residential"])
    @pytest.mark.parametrize("state", ["MD", "VA"])
    def test_rural_roads_keep_the_statutory_default(self, highway, state) -> None:
        road = {"highway": highway}
        known = classify(road, urban=False, jurisdiction=state)
        assert replace(known, default_speed_mph=None) == replace(
            classify(road, urban=False), default_speed_mph=None
        )

    @pytest.mark.parametrize(
        ("state", "urban", "divided", "tags", "mph"),
        [
            ("DC", True, False, {"highway": "primary"}, 20.0),
            ("DC", True, False, {"highway": "service", "service": "alley"}, 15.0),
            ("MD", True, False, {"highway": "primary"}, 30.0),
            ("MD", True, True, {"highway": "primary"}, 35.0),
            ("MD", False, False, {"highway": "secondary"}, 50.0),
            ("MD", False, True, {"highway": "trunk"}, 55.0),
            ("VA", True, False, {"highway": "secondary"}, 25.0),
            ("VA", False, False, {"highway": "secondary"}, 55.0),
            ("VA", False, False, {"highway": "tertiary", "surface": "gravel"}, 35.0),
            ("VA", True, False, {"highway": "tertiary", "surface": "gravel"}, 25.0),
            (None, False, False, {"highway": "secondary"}, 55.0),
        ],
    )
    def test_the_junction_model_gets_the_statutory_default(
        self, state, urban, divided, tags, mph
    ) -> None:
        """OWNER-DECISIONS 469, 469a: MD Transportation 21-801.1 and Code of
        Virginia 46.2-870 to 878; where the state is unknown, the classifier's own
        assumption."""
        result = classify(tags, urban=urban, jurisdiction=state, divided=divided)
        assert result.default_speed_mph == mph

    def test_a_posted_road_has_no_default(self) -> None:
        road = {"highway": "secondary", "maxspeed": "40 mph"}
        assert classify(road, urban=True, jurisdiction="MD").default_speed_mph is None

    def test_outside_a_known_state_nothing_changes(self) -> None:
        road = {"highway": "primary"}
        assert classify(road, urban=True, jurisdiction=None) == classify(road, urban=True)
        assert classify(road, urban=True, jurisdiction="PA") == classify(road, urban=True)


# --- OWNER-DECISIONS 109: one-way and two-way city streets --------------------


class TestOneWayAndTwoWay:
    """Connecticut Avenue NW: "definitely 3, and possibly 4". A two-way
    multi-lane city street is LTS 3 at least, 4 from 30 mph over 8,000 a day;
    a one-way with up to two lanes is read on the single-lane row."""

    connecticut = {"highway": "primary", "maxspeed": "25 mph", "lanes": "6", "oneway": "no"}

    def test_unposted_in_dc_it_is_still_lts3(self) -> None:
        road = {k: v for k, v in self.connecticut.items() if k != "maxspeed"}
        assert classify(road, urban=True, jurisdiction="DC").tier is Stress.LTS3

    def test_outside_urban_areas_furths_multilane_rule_stands(self) -> None:
        assert classify(self.connecticut, urban=False).tier is Stress.LTS3
        road = {**self.connecticut, "maxspeed": "30 mph"}
        assert classify(road, urban=False).tier is Stress.LTS4


# --- OWNER-DECISIONS 141: arterials, and v2.2's middle volume band ----------


class TestArterialFloor:
    """ "Make arterials LTS 3 or greater unless there s bike infrastructure."
    A trunk, primary or secondary road or its link is LTS 3 at least without a
    painted, buffered or protected lane or a separately mapped facility."""

    @pytest.mark.parametrize(
        "highway",
        ["trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"],
    )
    def test_an_unposted_district_arterial_is_lts3_not_lts1(self, highway) -> None:
        result = classify({"highway": highway, "lanes": "2"}, jurisdiction="DC")
        assert result.tier is Stress.LTS3
        assert result.rule.endswith(", arterial floor")

    @pytest.mark.parametrize("highway", ["unclassified", "residential", "service"])
    def test_other_classes_keep_the_district_default(self, highway) -> None:
        assert classify({"highway": highway}, jurisdiction="DC").tier is Stress.LTS1

    @pytest.mark.parametrize(
        "facility",
        [
            {"cycleway:both": "lane"},
            {"cycleway:both": "lane", "cycleway:both:buffer": "yes"},
            {"cycleway:both": "track"},
        ],
    )
    def test_bike_infrastructure_lifts_the_floor(self, facility) -> None:
        road = {"highway": "secondary", "lanes": "2", **facility}
        assert classify(road, jurisdiction="DC").tier < Stress.LTS3

    def test_a_lane_on_one_side_of_a_two_way_arterial_is_not_its_provision(self) -> None:
        road = {"highway": "secondary", "lanes": "2", "cycleway:left": "lane"}
        assert classify(road, jurisdiction="DC").tier is Stress.LTS3

    def test_the_floor_never_lowers_a_tier(self) -> None:
        road = {"highway": "primary", "maxspeed": "45 mph"}
        assert classify(road).tier is Stress.LTS4

    def test_everywhere_not_only_in_the_district(self) -> None:
        road = {"highway": "secondary", "maxspeed": "20 mph", "lanes": "2"}
        for state in ("MD", "VA", None):
            assert classify(road, jurisdiction=state).tier is Stress.LTS3


class TestMidVolume:
    """v2.2 at 20 mph and below: LTS 1 only under VOLUME_QUIET, LTS 2 up to
    VOLUME_BUSY, a tier more from there."""

    street = {"highway": "unclassified", "lanes": "2"}

    def test_the_middle_band_is_lts2(self) -> None:
        assert classify(self.street, aadt=1_500, jurisdiction="DC").tier is Stress.LTS1
        mid = classify(self.street, aadt=1_501, jurisdiction="DC")
        assert mid.tier is Stress.LTS2
        assert mid.rule.endswith(", mid volume")
        assert classify(self.street, aadt=7_999, jurisdiction="DC").tier is Stress.LTS2
        assert classify(self.street, aadt=8_000, jurisdiction="DC").tier is Stress.LTS2
        assert "high volume" in classify(self.street, aadt=8_000, jurisdiction="DC").rule

    def test_not_above_20_mph(self) -> None:
        road = {**self.street, "maxspeed": "25 mph"}
        assert classify(road, aadt=5_000).tier is Stress.LTS2
        assert "mid volume" not in classify(road, aadt=5_000).rule

    def test_it_does_not_stack_on_a_tier_already_raised(self) -> None:
        rough = {**self.street, "surface": "dirt", "smoothness": "very_bad"}
        assert classify(rough, aadt=5_000, jurisdiction="DC").tier is Stress.LTS2


class TestTheFloorsAndAShoulder:
    """The class floors (items 141, 176) and a shoulder: a rideable shoulder is
    bike infrastructure (item 145: "Yes, count it") whether or not the table
    credited it, and reads as a lane of its width - never worse than the same
    road with that lane, never better (review r2)."""

    def test_the_review_case(self) -> None:
        road = {"highway": "secondary", "lanes": "2"}
        shoulder = classify(
            {**road, "shoulder": "both", "shoulder:width": "2.0"}, jurisdiction="DC"
        )
        lane = classify(
            {**road, "cycleway:both": "lane", "cycleway:width": "2.0"}, jurisdiction="DC"
        )
        assert shoulder.tier <= lane.tier
        assert "arterial floor" not in shoulder.rule

    @pytest.mark.parametrize("highway", ["secondary", "tertiary"])
    @pytest.mark.parametrize(
        "speed", ["15 mph", "20 mph", "25 mph", "30 mph", "35 mph", "40 mph", "45 mph"]
    )
    @pytest.mark.parametrize("width", ["1.3", "1.4", "2.4", "4.5"])
    @pytest.mark.parametrize("parking", ["no", "parallel"])
    def test_a_shoulder_never_rates_worse_than_the_lane(self, highway, speed, width, parking):
        road = {"highway": highway, "maxspeed": speed, "lanes": "2", "parking:both": parking}
        shoulder = classify({**road, "shoulder": "both", "shoulder:width": width}).tier
        lane = classify({**road, "cycleway:both": "lane", "cycleway:width": width}).tier
        bare = classify(road).tier
        # Read as a lane of its width: the same tier, on the same table.
        assert shoulder == lane, (shoulder, lane)
        assert shoulder <= bare

    def test_an_unrideable_shoulder_is_no_provision(self) -> None:
        road = {"highway": "secondary", "lanes": "2", "shoulder": "both", "shoulder:width": "0.5"}
        assert classify(road, jurisdiction="DC").rule.endswith(", arterial floor")


class TestCollectorFloor:
    """OWNER-DECISIONS 176: "At least LTS 2 (Recommended)". A collector
    (tertiary, or its link) without bike infrastructure is LTS 2 at least, and
    a count may push it higher."""

    def test_a_count_still_pushes_it_higher(self) -> None:
        road = {"highway": "tertiary", "lanes": "2"}
        assert classify(road, aadt=12_000, jurisdiction="DC").tier is Stress.LTS2
        busy = {**road, "maxspeed": "25 mph"}
        assert classify(busy, aadt=12_000, jurisdiction="DC").tier is Stress.LTS3

    def test_not_an_arterial_floor_and_not_other_classes(self) -> None:
        assert classify({"highway": "tertiary"}, jurisdiction="DC").tier is not Stress.LTS3
        for highway in ("unclassified", "residential"):
            assert classify({"highway": highway}, jurisdiction="DC").tier is Stress.LTS1


class TestParkingWidthBesideABikeLane:
    """An agency's parking-lane width (agency_roads; DC's Roadway Block): Furth
    measures a lane beside parking by its reach, the lane plus the parking lane,
    adequate at 15 ft (MTI 11-19, Table 2)."""

    LANE = {
        "highway": "residential",
        "maxspeed": "25 mph",
        "cycleway:both": "lane",
        "parking:both": "parallel",
    }

    def tier(self, width_m: float, parking_width_m: float | None, **extra) -> int:
        tags = {**self.LANE, "cycleway:both:width": str(width_m), **extra}
        return int(classify(tags, parking_width_m=parking_width_m).tier)

    def test_a_seven_foot_lane_beside_eight_feet_of_parking_is_adequate(self) -> None:
        # 2.14 m + 2.44 m = 4.58 m (15 ft), Furth's adequate reach.
        assert self.tier(2.14, 2.44) == 1

    def test_a_wider_parking_lane_never_makes_a_lane_worse(self) -> None:
        narrow = self.tier(1.83, 0.5)
        wide = self.tier(1.83, 2.44)
        assert wide <= narrow


# The 8 Baltimore City watershed fire roads that stopped the v0.16.0 rebuild (2026-10-31): the
# off-road-path rule made them LTS 1 while the floor check read `motorcar=private` as open to
# cars. The owner picked "Exempt car-free roads from floor".
WATERSHED_FIRE_ROAD = {
    "highway": "track",
    "tracktype": "grade4",
    "surface": "dirt",
    "motor_vehicle": "no",
    "motorcar": "private",
}


class TestATwoWayFacilityOnOneSide:
    """Hunt 3, stress 1: `cycleway:<side>:oneway=no` on a two-way road serves both
    directions, so it is the way's facility, not mixed traffic."""

    road = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "2"}

    @pytest.mark.parametrize("side", ["left", "right"])
    def test_a_two_way_track_on_one_side_is_a_track(self, side) -> None:
        tags = {**self.road, f"cycleway:{side}": "track", f"cycleway:{side}:oneway": "no"}
        result = classify(tags)
        assert result.tier is Stress.LTS1
        assert result.rule == "separated track alongside"
        assert facility.facility(tags) is facility.Facility.PROTECTED

    def test_a_one_way_track_on_one_side_is_still_one_directions(self) -> None:
        tags = {**self.road, "cycleway:right": "track"}
        assert classify(tags).tier is Stress.LTS3
        assert classify({**tags, "cycleway:right:oneway": "yes"}).tier is Stress.LTS3

    def test_the_oneway_is_read_at_the_key_the_value_came_from(self) -> None:
        """A bare `cycleway:oneway=no` qualifies only the bare key."""
        tags = {**self.road, "cycleway:right": "track", "cycleway:oneway": "no"}
        assert classify(tags).tier is Stress.LTS3


# --- The District's quiet residential streets and counted two-lane arterials (2026-11-13) ---


# A turn bay is not a through lane (the owner, 2026-11-13, of K Street NE: "It's one lane each
# way with the occasional turning lane").
@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (
            {
                "lanes:forward": "2",
                "lanes:backward": "1",
                "turn:lanes:forward": "left|through;right",
            },
            1,
        ),
        (
            {
                "lanes:forward": "2",
                "lanes:backward": "1",
                "turn:lanes:forward": "through|through;right",
            },
            2,
        ),
        ({"lanes:forward": "2", "lanes:backward": "1", "turn:lanes:forward": "|right"}, 1),
        # A list of another length is about other lanes: the count stands.
        (
            {
                "lanes:forward": "2",
                "lanes:backward": "1",
                "turn:lanes:forward": "left|through|right",
            },
            2,
        ),
        ({"lanes:forward": "2", "lanes:backward": "1"}, 2),
        ({"lanes": "4", "lanes:forward": "2", "turn:lanes:forward": "left|through"}, 2),
    ],
)
def test_a_turn_only_lane_osm_maps_is_not_a_through_lane(tags, expected):
    from routemaker.tags import lanes_per_direction

    assert lanes_per_direction({"highway": "tertiary", **tags}) == expected
