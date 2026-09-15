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
    AgencyFeature,
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
