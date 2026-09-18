"""Stress classifier tests.

Written around the cases this region actually produces, and around the ordering
the plan fixes: speed, then facility, then volume, then surface.
"""

from __future__ import annotations

import pytest

from routemaker.stress import (
    DEFAULT_LANES_PER_DIRECTION,
    DEFAULT_MAXSPEED_MPH_RURAL,
    DEFAULT_MAXSPEED_MPH_URBAN,
    FURTH_LANE_ALONE_M,
    FURTH_LANE_BESIDE_PARKING_M,
    RIDEABLE_SHOULDER_M,
    UNPAVED_RURAL_DEFAULT_MPH,
    VOLUME_BUSY,
    VOLUME_QUIET,
    Stress,
    classify,
    is_rough,
    is_unpaved,
)
from routemaker.tags import (
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
    @pytest.mark.parametrize("width", ["1.4", "2.4", "4.5"])
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
        if painted <= bare:
            assert shoulder >= painted, "a shoulder outranking a bike lane is the inversion"
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
        as a shoulder of unknown width, so a surveyed shoulder earned nothing."""
        for side in ("both", "left", "right"):
            surveyed = {
                "highway": "secondary",
                "maxspeed": "35 mph",
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


class TestWidthParsing:
    """US widths are commonly tagged in feet, and the feet branch feeds the
    shoulder credit and the bike-lane door zone alike."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("8'", 2.4384), ("8ft", 2.4384), ("8 ft", 2.4384), ("2.4", 2.4), ("2.4 m", 2.4)],
    )
    def test_units(self, value: str, expected: float) -> None:
        assert parse_width_m(value) == pytest.approx(expected, abs=0.001)

    @pytest.mark.parametrize("value", [None, "", "wide", "ft"])
    def test_unreadable_is_unknown_rather_than_zero(self, value: str | None) -> None:
        assert parse_width_m(value) is None


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
        specific tag losing to the more general one, which is backwards."""
        assert has_shoulder({"shoulder": "no", "shoulder:right": "yes"}) is True
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
        road = {"highway": "secondary", "maxspeed": "35 mph"}
        refined = {"shoulder": "no", "shoulder:right": "yes", "shoulder:right:width": "2.4"}
        assert classify({**road, **refined}).tier is Stress.LTS3


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
        assert has_shoulder({"shoulder:right": "yes"}) is True
