"""Conflation: attaching agency volume layers to OSM ways.

Written around the two geometries this region is full of and that plain buffer
overlap gets wrong, and - since the round-2 review - around data shaped like the
real thing. Every fixture here used to be built from the same coordinate list,
so the way and the agency feature shared vertices exactly. Real agency layers
never do, and the matcher's distance measure was vertex to vertex: the tests
passed on the one case the code got right and nothing exercised the rest.
"""

from __future__ import annotations

import pytest

from pipeline.conflation import (
    MAX_SEPARATION_M,
    MAX_SPAN_REUSE,
    AgencyFeature,
    _claim,
    _overlap_fraction,
    conflate,
)

# An east-west road at 38.90, and its northbound twin about 14 m away.
ROAD = [(-77.02, 38.9000), (-77.00, 38.9000)]
PARALLEL_CARRIAGEWAY = [(-77.02, 38.90013), (-77.00, 38.90013)]
CROSS_STREET = [(-77.010, 38.8990), (-77.010, 38.9010)]

# The same road as an agency would have drawn it: different vertices, a metre or
# two of survey noise, and no coordinate in common with the OSM way.
SURVEYED_ROAD = [
    (-77.0198, 38.90001),
    (-77.0150, 38.89999),
    (-77.0102, 38.90002),
    (-77.0051, 38.89998),
    (-77.0002, 38.90001),
]


def feature(fid: str, coords, aadt: int = 5000, source: str = "state") -> AgencyFeature:
    return AgencyFeature(feature_id=fid, coordinates=coords, aadt=aadt, source=source)


def shifted(coords, metres: float):
    """The same line moved north by roughly `metres`."""
    return [(lon, lat + metres / 111_320.0) for lon, lat in coords]


class TestOverlapMeasure:
    def test_a_coincident_line_with_its_own_vertices_still_matches(self) -> None:
        """The defect this file existed to catch and could not.

        The measure compared the shorter line's vertices against the longer
        line's *vertices*. An agency survey line and an OSM way describe the same
        road with entirely different vertices, so this pair - the same road twice
        - scored 0.0 and never matched. Every fixture reused one coordinate list,
        which is the only shape that hid it.
        """
        assert not set(map(tuple, ROAD)) & set(map(tuple, SURVEYED_ROAD))
        assert _overlap_fraction(ROAD, SURVEYED_ROAD, MAX_SEPARATION_M) == pytest.approx(1.0)

    def test_a_feature_overhanging_both_ends_still_matches_the_way(self) -> None:
        """An agency corridor runs past the block it covers. Measured to the
        nearest vertex, the way's middle was nowhere near one."""
        long_feature = [(-77.06, 38.9), (-76.96, 38.9)]
        assert _overlap_fraction(ROAD, long_feature, MAX_SEPARATION_M) == pytest.approx(1.0)

    def test_a_line_beyond_the_separation_limit_does_not_match(self) -> None:
        """Beyond this the features are not the same road, whatever their
        bearing - the discrimination the module exists for."""
        assert _overlap_fraction(ROAD, shifted(ROAD, 5.0), MAX_SEPARATION_M) == pytest.approx(1.0)
        assert _overlap_fraction(ROAD, shifted(ROAD, 60.0), MAX_SEPARATION_M) == 0.0

    def test_the_measure_does_not_depend_on_how_finely_a_line_is_drawn(self) -> None:
        """A two-vertex agency line and a forty-vertex OSM way describe the same
        road; sampling raw vertices weighs them differently."""
        dense = [(-77.02 + i * 0.0005, 38.9) for i in range(41)]
        assert _overlap_fraction(dense, SURVEYED_ROAD, MAX_SEPARATION_M) == pytest.approx(1.0)


class TestMatching:
    def test_a_matching_line_attaches_its_volume(self) -> None:
        result = conflate([(1, ROAD)], [feature("f1", SURVEYED_ROAD, aadt=7200)])
        assert result.matched[1].aadt == 7200

    def test_the_year_travels_with_the_count(self) -> None:
        """A 2011 count and a 2024 count are not the same evidence, and the
        classifier's confidence depends on which it is reading."""
        dated = AgencyFeature("f1", SURVEYED_ROAD, aadt=7200, source="state", year=2011)
        assert conflate([(1, ROAD)], [dated]).matched[1].year == 2011

    def test_a_cross_street_is_excluded_by_bearing_alone(self) -> None:
        """Stated with the overlap gate opened all the way, so bearing is the
        only thing left doing the work.

        The earlier version of this test claimed bearing was what excluded the
        cross street "because the two lines intersect, so overlap alone would
        not". That was false - their overlap is 0.0 - so deleting the bearing gate
        entirely left the suite green.
        """
        wide_open = {"min_overlap": 0.0, "max_separation_m": 5000.0}
        assert conflate([(1, ROAD)], [feature("f1", CROSS_STREET)], **wide_open).matched == {}

        # And with the bearing tolerance opened instead, it does match - which is
        # what proves the bearing gate is the thing refusing it.
        permissive = conflate(
            [(1, ROAD)], [feature("f1", CROSS_STREET)], bearing_tolerance_deg=90.0, **wide_open
        )
        assert 1 in permissive.matched

    def test_a_one_way_pair_still_matches_against_a_reversed_feature(self) -> None:
        """The halves of a one-way pair run in opposite directions along the same
        road, so a 180 degree disagreement is the same alignment."""
        result = conflate([(1, ROAD)], [feature("f1", list(reversed(SURVEYED_ROAD)))])
        assert 1 in result.matched

    def test_a_brief_stub_does_not_describe_a_long_road(self) -> None:
        """Asserted directly, and against the rule as it now reads.

        The earlier version allowed `matched.get(1) is None or score >= 0.5`. The
        right disjunct is guaranteed by the gate it was meant to be testing, so
        deleting that gate left it green - and the left disjunct held only
        because the distance measure was broken, not because the overlap rule
        refused it. Both are fixed, so this states the thing plainly: a
        twenty-metre agency stub lying on a two-kilometre road is not a count for
        that road.
        """
        short_clip = [(-77.0101, 38.9000), (-77.0099, 38.9000)]
        assert 1 not in conflate([(1, ROAD)], [feature("f1", short_clip)]).matched

    def test_a_corridor_running_past_a_short_block_still_describes_it(self) -> None:
        """The same rule in the other direction, which is why it is measured over
        the way rather than over the shorter of the two lines."""
        block = [(-77.0101, 38.9000), (-77.0099, 38.9000)]
        corridor = [(-77.06, 38.90002), (-76.96, 38.89998)]
        assert 1 in conflate([(1, block)], [feature("f1", corridor)]).matched


class TestExclusivity:
    def test_one_count_cannot_be_claimed_by_both_carriageways(self) -> None:
        """A divided boulevard is two OSM ways a few metres apart. Without
        exclusivity the same agency count lands on both and doubles the volume
        the classifier reads on each."""
        result = conflate([(1, ROAD), (2, PARALLEL_CARRIAGEWAY)], [feature("f1", SURVEYED_ROAD)])
        assert len(result.matched) == 1
        assert result.rejected, "the losing way must be recorded, not silently dropped"

    def test_a_corridor_count_reaches_every_block_along_it(self) -> None:
        """The other half of the rule, and the one the first version got wrong.

        OSM splits a road at every intersection, so an agency corridor covers a
        string of ways end to end. Consuming the whole feature on the first match
        gave the count to one block and left the rest of the arterial with no
        volume at all - which is most of it.
        """
        corridor = [(-77.06, 38.90002), (-76.96, 38.89998)]
        blocks = [
            (1, [(-77.06, 38.9), (-77.04, 38.9)]),
            (2, [(-77.04, 38.9), (-77.02, 38.9)]),
            (3, [(-77.02, 38.9), (-77.00, 38.9)]),
            (4, [(-77.00, 38.9), (-76.98, 38.9)]),
        ]
        result = conflate(blocks, [feature("corridor", corridor, aadt=18000)])
        assert set(result.matched) == {1, 2, 3, 4}
        assert {m.aadt for m in result.matched.values()} == {18000}

    def test_a_corridor_count_still_refuses_a_parallel_way(self) -> None:
        """Both rules at once: four blocks end to end all match, and a
        carriageway alongside one of them does not."""
        corridor = [(-77.06, 38.90002), (-76.96, 38.89998)]
        ways = [
            (1, [(-77.06, 38.9), (-77.04, 38.9)]),
            (2, [(-77.04, 38.9), (-77.02, 38.9)]),
            (3, shifted([(-77.04, 38.9), (-77.02, 38.9)], 14.0)),
        ]
        result = conflate(ways, [feature("corridor", corridor)])
        assert set(result.matched) == {1, 2}
        assert [way_id for way_id, _ in result.rejected] == [3]


class TestTrailExclusion:
    def test_a_parallel_trail_never_competes_for_a_motor_count(self) -> None:
        """Domain S3: with the Mount Vernon Trail 15 m from the GW Parkway -
        well inside max_separation_m - a trail must never be a *candidate* for
        a motor-vehicle AADT, in either extract order. Before this exclusion,
        whichever of the trail or the roadway happened to be listed first
        could win the corridor count on bearing and overlap alone, and span
        exclusivity then denied the count to the roadway blocks that lost."""
        corridor = [(-77.06, 38.90002), (-76.96, 38.89998)]
        road_1 = (1, [(-77.06, 38.9), (-77.04, 38.9)])
        road_2 = (2, [(-77.04, 38.9), (-77.02, 38.9)])
        trail = (3, shifted([(-77.06, 38.9), (-77.04, 38.9)], 15.0), True)

        for ways in ([road_1, road_2, trail], [trail, road_1, road_2]):
            result = conflate(list(ways), [feature("corridor", corridor, aadt=18000)])
            assert set(result.matched) == {1, 2}, ways
            assert 3 not in result.matched, "a trail must never take a motor-vehicle count"

    def test_exclusion_holds_even_when_the_trail_is_the_closer_line(self) -> None:
        """Distance-based tie-breaking is not what is supposed to be doing this
        job: a trail must be refused the count even in the (real-world
        plausible - a realigned road whose survey line was never updated)
        case where the trail happens to run closer to the surveyed line than
        the roadway does. Only the explicit exclusion catches this; the
        geometric tie-break alone would hand the count to the trail."""
        # The "count" is surveyed exactly on the trail's alignment - as close
        # to it as a line can be - while the road sits 15 m away, still well
        # inside max_separation_m.
        trail_line = [(-77.06, 38.90), (-77.04, 38.90)]
        surveyed_on_the_trail = feature("count", trail_line, aadt=9000)
        road = (1, shifted(trail_line, 15.0))
        trail = (2, trail_line, True)

        result = conflate([road, trail], [surveyed_on_the_trail])
        assert 1 in result.matched, "the roadway must still get the count"
        assert 2 not in result.matched, "the trail must never get it, however close it runs"

    def test_the_two_element_form_still_works_uninstructed(self) -> None:
        """A caller that has not been updated to pass the trail flag gets the
        old behaviour, not a crash - the fix is additive until the call site
        (run.py's conflate_volume) passes `variants.is_trail_class(way.tags)`
        as the third element."""
        result = conflate([(1, ROAD)], [feature("f1", SURVEYED_ROAD)])
        assert 1 in result.matched


class TestGeometricTieBreak:
    def test_ties_are_broken_by_distance_not_input_order(self) -> None:
        """Same precedence, same overlap fraction (both fully within
        tolerance of the same agency line): the earlier ranking fell through
        to input order once precedence and overlap were exhausted, so
        reversing the `ways` list reversed the winner. The way that actually
        runs closer to the feature must win regardless of which is listed
        first."""
        near = ROAD
        far = shifted(ROAD, 5.0)
        agency = feature("f1", SURVEYED_ROAD)

        forward = conflate([(1, near), (2, far)], [agency])
        backward = conflate([(2, far), (1, near)], [agency])

        assert 1 in forward.matched and 2 not in forward.matched, forward
        assert 1 in backward.matched and 2 not in backward.matched, backward

    def test_a_three_way_tie_is_decided_by_id_not_by_input_order(self) -> None:
        """Geometry runs out, and then the key does too.

        Three ways lying on the same line - a carriageway split into equal
        pieces by a mapper, or the same survey line drawn over a pair plus its
        ramp - score identical overlap and identical mean distance, so
        precedence, overlap and distance are all exhausted and the stable sort
        fell through to the order `ways` arrived in. That order is whatever
        `read_ways` returns for the extract, so the same data clipped twice
        could hand the count to a different way and the segment table would
        disagree with itself between rebuilds for no reason a reviewer could
        see.

        The winner being way 1 is not the point - any of the three is as good -
        the point is that it is the same one both times.
        """
        agency = feature("f1", SURVEYED_ROAD)
        ways = [(1, ROAD), (2, list(ROAD)), (3, list(ROAD))]

        forward = conflate(ways, [agency])
        backward = conflate(list(reversed(ways)), [agency])

        assert list(forward.matched) == [1], forward
        assert list(backward.matched) == [1], backward
        assert len(forward.rejected) == len(backward.rejected) == 2


class TestSpanReuseThreshold:
    def test_max_span_reuse_pins_the_threshold(self) -> None:
        """0.25 exactly, not merely 'some fraction below 1'. Pinned at a
        divided-carriageway case sitting right on the boundary, plus a case
        that would pass a mutation to 0.99 but must not pass at 0.25."""
        assert MAX_SPAN_REUSE == 0.25

        at_threshold = {}
        assert _claim(at_threshold, "f", (0.0, 1.0)) is True
        # Reuses exactly 0.25 of the new span: allowed, the way a junction
        # shared by two blocks is meant to be.
        assert _claim(at_threshold, "f", (0.75, 1.75)) is True

        halfway = {}
        assert _claim(halfway, "f", (0.0, 1.0)) is True
        # Reuses half the new span - refused at 0.25, but would wrongly pass
        # if the threshold regressed to 0.99. This is the divided-carriageway
        # shape: two ways lying alongside each other rather than end to end.
        assert _claim(halfway, "f", (0.5, 1.5)) is False


class TestUnmatchedFeatures:
    def test_unmatched_features_are_named_not_just_counted(self) -> None:
        result = conflate([(1, ROAD)], [feature("far-away", shifted(ROAD, 60.0))])
        assert result.unmatched_features == ["far-away"]

    def test_the_unmatched_count_reaches_the_result(self) -> None:
        """`unmatched_features` must be derived from the actual match set, not
        hardcoded - a matching feature and a missing one together, so a stub
        that always returns [] or always returns every feature id both fail."""
        result = conflate(
            [(1, ROAD)],
            [feature("matches", SURVEYED_ROAD), feature("misses", shifted(ROAD, 60.0))],
        )
        assert result.unmatched_features == ["misses"]
        assert "matches" not in result.unmatched_features


class TestPrecedence:
    def test_a_locality_layer_beats_the_state_layer(self) -> None:
        """A locality surveys its own streets more densely, which is the whole
        reason to prefer it; without an explicit order the winner is whichever
        was listed first."""
        result = conflate(
            [(1, ROAD)],
            [
                feature("state", SURVEYED_ROAD, aadt=5000, source="state"),
                feature("local", SURVEYED_ROAD, aadt=4100, source="locality"),
            ],
        )
        assert result.matched[1].source == "locality"
        assert result.matched[1].aadt == 4100

    def test_the_loser_of_a_contest_is_recorded(self) -> None:
        """Two agencies disagreeing about the same road is something a reviewer
        needs to see rather than something to resolve silently."""
        result = conflate(
            [(1, ROAD)],
            [
                feature("state", SURVEYED_ROAD, aadt=5000, source="state"),
                feature("local", SURVEYED_ROAD, aadt=4100, source="locality"),
            ],
        )
        assert [m.feature_id for _, m in result.rejected] == ["state"]
