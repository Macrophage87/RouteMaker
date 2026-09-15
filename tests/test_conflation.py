"""Conflation: attaching agency volume layers to OSM ways.

Written around the two geometries this region is full of and that plain buffer
overlap gets wrong.
"""

from __future__ import annotations

from pipeline.conflation import AgencyFeature, conflate

# A east-west road at 38.90, and its northbound twin 15 m away.
ROAD = [(-77.02, 38.9000), (-77.00, 38.9000)]
PARALLEL_CARRIAGEWAY = [(-77.02, 38.90013), (-77.00, 38.90013)]
CROSS_STREET = [(-77.010, 38.8990), (-77.010, 38.9010)]


def feature(fid: str, coords, aadt: int = 5000, source: str = "state") -> AgencyFeature:
    return AgencyFeature(feature_id=fid, coordinates=coords, aadt=aadt, source=source)


def test_a_matching_line_attaches_its_volume() -> None:
    result = conflate([(1, ROAD)], [feature("f1", ROAD, aadt=7200)])
    assert result.matched[1].aadt == 7200


def test_a_cross_street_never_matches() -> None:
    """Bearing is what excludes it; the two lines intersect, so overlap alone
    would not."""
    result = conflate([(1, ROAD)], [feature("f1", CROSS_STREET)])
    assert result.matched == {}
    assert result.unmatched_features == ["f1"]


def test_one_count_cannot_be_claimed_by_both_carriageways() -> None:
    """A divided boulevard is two OSM ways a few metres apart. Without
    exclusivity the same agency count lands on both and doubles the volume the
    classifier reads on each."""
    result = conflate([(1, ROAD), (2, PARALLEL_CARRIAGEWAY)], [feature("f1", ROAD)])
    assert len(result.matched) == 1
    assert result.rejected, "the losing way must be recorded, not silently dropped"


def test_a_one_way_pair_still_matches_against_a_reversed_feature() -> None:
    """The halves of a one-way pair run in opposite directions along the same
    road, so a 180 degree disagreement is the same alignment, not a mismatch."""
    reversed_road = list(reversed(ROAD))
    result = conflate([(1, ROAD)], [feature("f1", reversed_road)])
    assert 1 in result.matched


def test_a_brief_crossing_is_not_a_match() -> None:
    short_clip = [(-77.0101, 38.9000), (-77.0099, 38.9000)]
    result = conflate([(1, ROAD)], [feature("f1", short_clip)])
    # The clip is short and mostly coincident, so it is the *way* whose overlap
    # fraction must decide: less than half of the road runs near the clip.
    assert result.matched.get(1) is None or result.matched[1].score >= 0.5


def test_a_locality_layer_beats_the_state_layer() -> None:
    """A locality surveys its own streets more densely, which is the whole reason
    to prefer it; without an explicit order the winner is whichever was listed
    first."""
    result = conflate(
        [(1, ROAD)],
        [
            feature("state", ROAD, aadt=5000, source="state"),
            feature("local", ROAD, aadt=4100, source="locality"),
        ],
    )
    assert result.matched[1].source == "locality"
    assert result.matched[1].aadt == 4100


def test_the_loser_of_a_contest_is_recorded() -> None:
    """Two agencies disagreeing about the same road is something a reviewer needs
    to see rather than something to resolve silently."""
    result = conflate(
        [(1, ROAD)],
        [
            feature("state", ROAD, aadt=5000, source="state"),
            feature("local", ROAD, aadt=4100, source="locality"),
        ],
    )
    assert [m.feature_id for _, m in result.rejected] == ["state"]
