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
    cycleway_provision,
    cycleway_sides,
    cycleway_values,
    cycleway_width_m,
    has_shoulder,
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
