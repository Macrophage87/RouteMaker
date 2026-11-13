"""The Virginia ratings review's formula changes (the owner, 2026-10-31: "Let's go with all
these"): the count-driven steps in `routemaker.stress.busy_road_steps`, the narrow-road rule
with a quiet count, and counts reaching a street that bends or runs past several count lines
(`pipeline.conflation._along_counts`). P2, the two-lane street at 5,000-7,999 a day, is the
busy-street half step the owner set for every state the same day
(tests/test_jurisdiction_rules.py)."""

from __future__ import annotations

from pipeline.conflation import AgencyFeature, conflate, share_with_carriageways
from routemaker.stress import (
    BUSY_RURAL_HIGHWAY_RULE,
    NARROW_ROAD_RULE,
    classify,
)

RESIDENTIAL = {"highway": "residential", "maxspeed": "25 mph"}


def level(result) -> float:
    return int(result.tier) + (0.5 if result.half else 0.0)


class TestBusyRuralHighway:
    TWO_LANE = {"highway": "primary", "maxspeed": "55 mph", "lanes": "2"}

    def test_a_two_lane_rural_primary_at_eighteen_thousand_is_four_and_a_half(self) -> None:
        result = classify(self.TWO_LANE, aadt=18_000, urban=False, jurisdiction="VA")
        assert level(result) == 4.5 and BUSY_RURAL_HIGHWAY_RULE in result.rule

    def test_maryland_reads_the_same(self) -> None:
        assert level(classify(self.TWO_LANE, aadt=20_000, urban=False, jurisdiction="MD")) == 4.5

    def test_below_eighteen_thousand_it_stays_four(self) -> None:
        assert level(classify(self.TWO_LANE, aadt=17_999, urban=False)) == 4

    def test_not_in_an_urban_area(self) -> None:
        assert level(classify(self.TWO_LANE, aadt=25_000, urban=True)) == 4

    def test_a_four_lane_road_is_not_a_two_lane_highway(self) -> None:
        # At 45 mph, under the multilane highway rule, so P7 itself decides.
        four = {**self.TWO_LANE, "lanes": "4", "maxspeed": "45 mph"}
        result = classify(four, aadt=25_000, urban=False)
        assert level(result) == 4 and BUSY_RURAL_HIGHWAY_RULE not in result.rule

    def test_a_secondary_road_is_not_a_rural_highway(self) -> None:
        secondary = {**self.TWO_LANE, "highway": "secondary"}
        assert level(classify(secondary, aadt=20_000, urban=False)) == 4

    def test_a_road_with_a_bike_lane_is_not_mixed_traffic(self) -> None:
        laned = {**self.TWO_LANE, "cycleway": "lane"}
        assert BUSY_RURAL_HIGHWAY_RULE not in classify(laned, aadt=20_000, urban=False).rule


class TestNarrowRoadWithAQuietCount:
    NARROW = {"highway": "unclassified", "lane_markings": "no"}

    def test_a_count_above_quiet_still_outranks_it(self) -> None:
        busy = classify(self.NARROW, aadt=1_501, aadt_source="vdot", urban=False)
        assert NARROW_ROAD_RULE not in busy.rule


# A street that runs east along a count line for 610 m, then turns north for 500 m: end
# to end it points north-east, 39 degrees off the line it follows.
BENT_STREET = [(-77.0200, 38.9000), (-77.0130, 38.9000), (-77.0130, 38.9045)]
LONG_LINE = [(-77.0250, 38.90001), (-77.0100, 38.90001)]


def feature(fid: str, coords, aadt: int, agency: str = "vdot") -> AgencyFeature:
    return AgencyFeature(fid, coords, aadt, "state", 2025, agency)


class TestCountsAlongAStreet:
    def test_a_street_that_bends_takes_the_count_it_runs_along(self) -> None:
        """The whole-line bearing gate refuses it (Falstaff Road, Fairfax, way 61242835)."""
        line = feature("f1", LONG_LINE, 320)
        assert conflate([(1, BENT_STREET)], [line], along_counts=False).matched == {}
        assert conflate([(1, BENT_STREET)], [line]).matched[1].aadt == 320

    def test_a_street_past_several_count_lines_takes_the_highest(self) -> None:
        """Each line covers under half of it (Victoria Road, way 8813727)."""
        street = [(-77.0200, 38.9000), (-77.0000, 38.9000)]
        lines = [
            feature("a", [(-77.0200, 38.90001), (-77.0130, 38.90001)], 160),
            feature("b", [(-77.0130, 38.90001), (-77.0065, 38.90001)], 480),
            feature("c", [(-77.0065, 38.90001), (-77.0000, 38.90001)], 390),
        ]
        assert conflate([(1, street)], lines, along_counts=False).matched == {}
        match = conflate([(1, street)], lines).matched[1]
        assert match.aadt == 480 and match.score > 0.9

    def test_a_street_alongside_one_that_took_the_count_still_does_not(self) -> None:
        """The other carriageway, or a frontage road, wants the same stretch."""
        street = [(-77.0250, 38.9000), (-77.0100, 38.9000)]
        beside = [(-77.0200, 38.90013), (-77.0130, 38.90013), (-77.0130, 38.9045)]
        line = feature("f1", LONG_LINE, 5_000)
        assert 2 in conflate([(2, beside)], [line]).matched, "alone, it would take it"
        result = conflate([(1, street), (2, beside)], [line])
        assert 1 in result.matched and 2 not in result.matched

    def test_the_other_carriageway_it_refuses_still_gets_its_share(self) -> None:
        """Both carriageways of a divided street bend the same way: one takes the count, the
        other is refused the claimed stretch, and is listed so it can share the count."""
        north = BENT_STREET
        south = [(lon, lat - 0.0001) for lon, lat in BENT_STREET]
        line = feature("f1", LONG_LINE, 9_000)
        result = conflate([(1, north), (2, south)], [line])
        assert 1 in result.matched and 2 not in result.matched
        assert 2 in {way for way, _match in result.rejected}
        names = {1: "Main Street", 2: "Main Street"}
        shared = share_with_carriageways(result, {1, 2}, names, ("vdot",))
        assert shared[2].aadt == 9_000

    def test_which_of_two_bent_streets_takes_it_does_not_hang_on_their_order(self) -> None:
        near = BENT_STREET
        far = [(lon, lat + 0.0001) for lon, lat in BENT_STREET]
        line = feature("f1", LONG_LINE, 900)
        one = conflate([(1, near), (2, far)], [line]).matched
        other = conflate([(2, far), (1, near)], [line]).matched
        assert set(one) == set(other) == {1}

    def test_only_vdot_counts_are_read_this_way(self) -> None:
        line = feature("f1", LONG_LINE, 320, agency="mdot")
        assert conflate([(1, BENT_STREET)], [line]).matched == {}

    def test_a_cross_street_takes_nothing(self) -> None:
        cross = [(-77.0100, 38.8990), (-77.0100, 38.9010)]
        line = feature("f1", [(-77.0200, 38.9000), (-77.0000, 38.9000)], 5_000)
        assert conflate([(1, cross)], [line]).matched == {}
