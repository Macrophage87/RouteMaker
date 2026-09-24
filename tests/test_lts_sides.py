"""The LTS side model: one record per side of the road, then the worst direction.

Round 10's domain blocker was the worst-side rule applied across the two sides
and not within one. `_side_values` unioned the general keys (`cycleway`,
`cycleway:both`) with the side key and kept the best value, so the side key's
`no` was thrown away whenever a general key asserted a facility, and
`_shoulder_on_side` did the same. The cases below are the reviewer's own probes,
executed on the roads they were executed on, and they are asserted as
properties of those roads - the tier the bare road has, the tier the fully
provisioned road has - rather than as rule sentences.
"""

from __future__ import annotations

import pytest

from routemaker.stress import Stress, classify
from routemaker.tags import (
    ONEWAY_VALUES,
    cycleway_provision,
    cycleway_sides,
    cycleway_values,
    cycleway_width_m,
    has_shoulder,
    is_oneway,
    lanes_per_direction,
    shoulder_width_m,
)

OTHER = {"left": "right", "right": "left"}

# Round 9's 35 mph four-lane two-way secondary, which round 10 re-ran: LTS4 bare.
ARTERIAL = {"highway": "secondary", "maxspeed": "35 mph", "lanes": "4"}


class TestTheReviewersTable:
    """Round 10 B1, row by row, and each row on both sides of the road."""

    @pytest.mark.parametrize("side", ("left", "right"))
    @pytest.mark.parametrize(
        "general",
        (
            {"cycleway": "track"},
            {"cycleway:both": "track"},
            {"cycleway": "lane"},
            {"cycleway:both": "lane"},
        ),
        ids=("general-track", "both-track", "general-lane", "both-lane"),
    )
    def test_a_general_facility_with_one_side_saying_no_is_the_bare_road(
        self, general: dict[str, str], side: str
    ) -> None:
        """A side key saying `no` is the more specific tag, and the side has
        nothing. On a two-way street that side is a direction of travel, so the
        road is mixed traffic for that direction: LTS4 here, and top tier,
        which is what the Beginner invariant and the road-exposure report key
        on. The union read the general key's facility into that side and rated
        the track LTS1 and the lane LTS3."""
        bare = classify(ARTERIAL)
        assert bare.tier is Stress.LTS4
        # The general key alone is a facility on both sides and earns its table,
        # so the side key and nothing else is what the assertion below moves.
        assert classify({**ARTERIAL, **general}).tier < bare.tier
        result = classify({**ARTERIAL, **general, f"cycleway:{side}": "no"})
        assert result.tier is bare.tier
        assert result.is_top_tier

    @pytest.mark.parametrize("side", ("left", "right"))
    def test_the_row_wave_8_fixed_stays_fixed(self, side: str) -> None:
        """`cycleway:left=track` + `cycleway:right=no`, and its mirror."""
        tagged = {**ARTERIAL, f"cycleway:{OTHER[side]}": "track", f"cycleway:{side}": "no"}
        assert classify(tagged).tier is classify(ARTERIAL).tier

    @pytest.mark.parametrize("side", ("left", "right"))
    def test_a_general_shoulder_with_one_side_saying_no_is_the_bare_road(self, side: str) -> None:
        """The shoulder mirror: `shoulder=yes` + `shoulder:width=2.4` +
        `shoulder:right=no` rated LTS3, because the general `yes` was read into
        the right side and the general width with it."""
        shouldered = {**ARTERIAL, "shoulder": "yes", "shoulder:width": "2.4"}
        assert classify(shouldered).tier is Stress.LTS3
        tagged = {**shouldered, f"shoulder:{side}": "no"}
        assert has_shoulder(tagged) is False
        assert classify(tagged).tier is classify(ARTERIAL).tier

    @pytest.mark.parametrize("speed", ("25 mph", "30 mph"))
    @pytest.mark.parametrize("side", ("left", "right"))
    @pytest.mark.parametrize("general_key", ("cycleway", "cycleway:both"))
    def test_provisioning_the_second_side_is_never_a_penalty(
        self, speed: str, side: str, general_key: str
    ) -> None:
        """Row 67's headline, on round 9's own 25 and 30 mph roads with the
        general key: the one-sided lane is the bare road, and both sides
        provisioned can only be better."""
        road = {"highway": "secondary", "maxspeed": speed, "lanes": "2", "parking:both": "no"}
        lane = {general_key: "lane", f"{general_key}:width": "2.0"}
        one_side = classify({**road, **lane, f"cycleway:{side}": "no"})
        both_sides = classify({**road, **lane})
        assert one_side.tier is classify(road).tier
        assert both_sides.tier < one_side.tier


class TestPrecedenceWithinASide:
    """Side-specific over `both` over the general key, one value per side."""

    @pytest.mark.parametrize(
        ("tags", "left", "right"),
        (
            ({"cycleway": "track", "cycleway:right": "no"}, "track", "no"),
            ({"cycleway": "track", "cycleway:both": "lane"}, "lane", "lane"),
            ({"cycleway:both": "lane", "cycleway:left": "track"}, "track", "lane"),
            ({"cycleway": "no", "cycleway:left": "lane"}, "lane", "no"),
            ({"cycleway": "lane", "cycleway:both": "no", "cycleway:right": "track"}, "no", "track"),
            ({"cycleway:right": "lane"}, None, "lane"),
            ({}, None, None),
        ),
    )
    def test_the_most_specific_key_answers_for_its_side(
        self, tags: dict[str, str], left: str | None, right: str | None
    ) -> None:
        sides = cycleway_sides(tags)
        assert (sides["left"].value, sides["right"].value) == (left, right)

    def test_a_side_saying_no_has_nothing_not_even_a_width(self) -> None:
        """A `no` side has no lane to be wide, so a general width does not
        become that side's measurement."""
        sides = cycleway_sides(
            {"cycleway": "lane", "cycleway:width": "2.0", "cycleway:right": "no"}
        )
        assert sides["left"].width_m == pytest.approx(2.0)
        assert sides["right"].width_m is None

    def test_a_side_refinement_of_a_general_no_is_a_one_sided_facility(self) -> None:
        """`cycleway=no` + `cycleway:left=track`: the left side has the track, and
        on a two-way street the right side's `no` is the road's provision."""
        tags = {**ARTERIAL, "cycleway": "no", "cycleway:left": "track"}
        assert cycleway_values(tags) == {"no"}
        assert classify(tags).tier is classify(ARTERIAL).tier
        assert classify({**tags, "oneway": "yes"}).tier is Stress.LTS1

    @pytest.mark.parametrize(
        ("tags", "left", "right"),
        (
            ({"shoulder": "yes", "shoulder:right": "no"}, True, False),
            ({"shoulder": "no", "shoulder:left": "yes"}, True, False),
            ({"shoulder:both": "no", "shoulder": "yes"}, False, False),
            ({"shoulder": "right"}, False, True),
            ({"shoulder": "left", "shoulder:width": "2.4"}, True, False),
            ({"shoulder:right:width": "2.4"}, None, True),
            ({"shoulder": "no", "shoulder:width": "2.4"}, True, True),
        ),
        ids=(
            "side-no-over-general-yes",
            "side-yes-over-general-no",
            "both-no-over-general-yes",
            "general-names-a-side",
            "general-width-belongs-to-the-named-side",
            "a-width-alone-is-presence",
            "same-level-width-beats-no",
        ),
    )
    def test_the_most_specific_shoulder_key_answers_for_its_side(
        self, tags: dict[str, str], left: bool | None, right: bool | None
    ) -> None:
        """Read through the one-way street, where either side answers for the
        way, and the two-way one, where both have to: the per-side answers are
        what those two readings are built from."""
        oneway = {**tags, "oneway": "yes"}
        spoke = left is not None or right is not None
        assert has_shoulder(oneway) is (bool(left or right) if spoke else None)
        assert has_shoulder(tags) is (bool(left and right) if spoke else None)

    def test_the_shoulder_width_fallback_does_not_reach_a_side_saying_no(self) -> None:
        """Round 10's residual: the width fallback read `shoulder:width` for a
        side tagged `no`. On a one-way street with a surveyed 2.4 m shoulder on
        the left and `shoulder:right=no`, a general 0.5 m width is the right
        side's no longer - that side has nothing - and the left side's own
        survey is the more specific one, so 0.5 m is nobody's width."""
        tags = {
            "oneway": "yes",
            "shoulder:width": "0.5",
            "shoulder:left": "yes",
            "shoulder:left:width": "2.4",
            "shoulder:right": "no",
        }
        assert shoulder_width_m(tags) == pytest.approx(2.4)


class TestAWidthBelongsToItsSide:
    """Round 10 SF-3: widths were side-blind while values were side-aware."""

    ROAD = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "2", "parking:both": "no"}

    @pytest.mark.parametrize("track_side", ("left", "right"))
    def test_a_tracks_width_never_rates_the_painted_lane_opposite(self, track_side: str) -> None:
        """A 2.0 m track on one side and an unsurveyed painted lane on the
        other: the lane is the road's provision, and its width is unknown."""
        lane_side = OTHER[track_side]
        painted = {f"cycleway:{track_side}": "track", f"cycleway:{lane_side}": "lane"}
        with_track_width = {**painted, f"cycleway:{track_side}:width": "2.0"}
        assert cycleway_width_m({**self.ROAD, **with_track_width}) is None
        result = classify({**self.ROAD, **with_track_width})
        assert result == classify({**self.ROAD, **painted})
        assert "cycleway width" in result.assumed

    def test_the_same_through_the_general_key(self) -> None:
        """`cycleway=lane` + `cycleway:left=track` + `cycleway:left:width`: the
        right side's lane comes from the general key and so does its width."""
        tags = {**self.ROAD, "cycleway": "lane", "cycleway:left": "track"}
        assert cycleway_width_m({**tags, "cycleway:left:width": "2.0"}) is None
        assert cycleway_width_m({**tags, "cycleway:width": "1.2"}) == pytest.approx(1.2)

    def test_a_side_width_refines_the_general_width_for_that_side_only(self) -> None:
        """`cycleway:both:width=2.0` + `cycleway:right:width=1.2`: the left lane
        is 2.0 and the right 1.2, and the narrower side is the road's."""
        tags = {
            "cycleway:both": "lane",
            "cycleway:both:width": "2.0",
            "cycleway:right:width": "1.2",
        }
        sides = cycleway_sides(tags)
        assert sides["left"].width_m == pytest.approx(2.0)
        assert sides["right"].width_m == pytest.approx(1.2)
        assert cycleway_provision(tags).width_m == pytest.approx(1.2)

    def test_on_a_one_way_street_the_width_is_the_facilitys_side(self) -> None:
        """One direction, one facility on the left: a width surveyed on the
        right, where there is no lane, is not the lane's."""
        tags = {
            **self.ROAD,
            "oneway": "yes",
            "cycleway:left": "lane",
            "cycleway:left:width": "2.0",
            "cycleway:right:width": "1.2",
        }
        assert cycleway_width_m(tags) == pytest.approx(2.0)
        assert classify(tags).tier is Stress.LTS2

    def test_a_narrower_second_lane_on_a_one_way_street_takes_nothing_away(self) -> None:
        """Found by the grid in `test_lts_side_grid.py`: one rider has both
        sides of a one-way street, so adding a 1.2 m lane beside a 2.0 m one
        read the pair as 1.2 m and raised the tier. Within a direction the
        rider has the wider; across the directions of a two-way street the
        narrower still decides."""
        lane = {**self.ROAD, "cycleway:left": "lane", "cycleway:left:width": "2.0"}
        second = {"cycleway:right": "lane", "cycleway:right:width": "1.2"}
        oneway = {**lane, "oneway": "yes"}
        assert classify({**oneway, **second}).tier is classify(oneway).tier
        assert cycleway_width_m({**oneway, **second}) == pytest.approx(2.0)
        assert cycleway_width_m({**lane, **second}) == pytest.approx(1.2)

    def test_a_narrower_second_shoulder_on_a_one_way_street_takes_nothing_away(self) -> None:
        shoulder = {**self.ROAD, "oneway": "yes", "shoulder:left:width": "2.4"}
        second = {**shoulder, "shoulder:right:width": "1.3"}
        assert shoulder_width_m(second) == pytest.approx(2.4)
        assert classify(second).tier is classify(shoulder).tier
        two_way = {**self.ROAD, "shoulder:left:width": "2.4", "shoulder:right:width": "1.3"}
        assert shoulder_width_m(two_way) == pytest.approx(1.3)


class TestOnlyTheseOnewayValuesMakeAWayOneWay:
    """Round 10 test quality: widening `is_oneway` to any `oneway` value left the
    suite green, and `oneway=no` then read as one-way - so the side rule fell
    back to the one-way union on exactly the streets that state they are
    two-way."""

    ONE_WAY = ("yes", "1", "-1", "true")
    TWO_WAY = ("no", "false", "0", "reversible", "alternating", "")

    def test_the_set_is_exactly_these(self) -> None:
        assert frozenset(self.ONE_WAY) == ONEWAY_VALUES

    @pytest.mark.parametrize("value", ONE_WAY)
    def test_one_way(self, value: str) -> None:
        assert is_oneway({"oneway": value}) is True

    @pytest.mark.parametrize("value", TWO_WAY)
    def test_two_way(self, value: str) -> None:
        assert is_oneway({"oneway": value}) is False
        assert is_oneway({}) is False

    @pytest.mark.parametrize("value", TWO_WAY)
    def test_a_street_that_says_it_is_two_way_is_scored_on_both_sides(self, value: str) -> None:
        """Through `classify`: a one-sided track on a street tagged two-way is
        the bare road, and so is its lane count."""
        tagged = {**ARTERIAL, "oneway": value, "cycleway:left": "track", "cycleway:right": "no"}
        assert classify(tagged).tier is classify(ARTERIAL).tier
        assert lanes_per_direction({"lanes": "4", "oneway": value}) == 2

    @pytest.mark.parametrize("value", ONE_WAY)
    def test_a_one_way_street_is_scored_on_the_side_it_has(self, value: str) -> None:
        tagged = {**ARTERIAL, "oneway": value, "cycleway:left": "track", "cycleway:right": "no"}
        assert classify(tagged).tier is Stress.LTS1
        assert lanes_per_direction({"lanes": "4", "oneway": value}) == 4


class TestAContraflowOnlyFacilityIsNotTheWithFlowRiders:
    """Round 10 SF-2: the one-way carve-out was keyed on `oneway` alone, so
    `oneway:bicycle=no` with `cycleway:left=opposite_lane` took the union though
    the rider travelling with the traffic has no facility."""

    STREET = {
        "highway": "secondary",
        "maxspeed": "25 mph",
        "lanes": "1",
        "oneway": "yes",
        "parking:both": "no",
    }

    @pytest.mark.parametrize("oneway", ("yes", "-1"))
    @pytest.mark.parametrize(
        "key", ("cycleway", "cycleway:both", "cycleway:left", "cycleway:right")
    )
    @pytest.mark.parametrize("value", ("opposite_lane", "opposite_track"))
    def test_the_carve_out_declines_for_a_contraflow_only_facility(
        self, value: str, key: str, oneway: str
    ) -> None:
        street = {**self.STREET, "oneway": oneway}
        facility = {key: value, f"{key}:width": "2.0"}
        # Without `oneway:bicycle=no` the carve-out stands - the District's
        # contraflow tagging, pinned in `test_stress.py` - and the facility is
        # the road's.
        assert classify({**street, **facility}).tier is Stress.LTS1
        both_ways = classify({**street, **facility, "oneway:bicycle": "no"})
        assert both_ways == classify({**street, "oneway:bicycle": "no"})

    @pytest.mark.parametrize("with_flow", ("lane", "track"))
    def test_a_with_flow_facility_beside_the_contraflow_one_is_the_roads(
        self, with_flow: str
    ) -> None:
        """The with-flow rider's own facility is what the road is scored on."""
        tags = {
            **self.STREET,
            "oneway:bicycle": "no",
            "cycleway:left": "opposite_track",
            "cycleway:right": with_flow,
            "cycleway:right:width": "2.0",
        }
        assert cycleway_values(tags) == {with_flow}
        alone = {**self.STREET, "cycleway:right": with_flow, "cycleway:right:width": "2.0"}
        assert classify(tags) == classify(alone)

    @pytest.mark.parametrize("value", ("yes", "-1", "dismount"))
    def test_only_oneway_bicycle_no_brings_the_second_direction_back(self, value: str) -> None:
        tags = {**self.STREET, "oneway:bicycle": value, "cycleway:left": "opposite_lane"}
        assert cycleway_values(tags) == {"opposite_lane"}

    def test_a_two_way_street_is_unaffected(self) -> None:
        """`oneway:bicycle=no` on a street that is two-way already changes
        nothing: each side is a direction there either way."""
        road = {**self.STREET, "oneway": "no"}
        tagged = {**road, "cycleway:both": "opposite_lane", "cycleway:both:width": "2.0"}
        assert classify({**tagged, "oneway:bicycle": "no"}) == classify(tagged)
        assert classify(tagged).tier is Stress.LTS1
