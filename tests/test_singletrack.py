"""Mountain-bike singletrack, which every current ride type avoids
(routemaker.singletrack; OWNER-DECISIONS 90, 91, 93, 111)."""

from __future__ import annotations

import pytest

from routemaker.singletrack import grade, is_singletrack

# The C&O Canal towpath, as OSM maps it either side of lock 21 (item 93).
TOWPATH_ABOVE_LOCK_21 = {
    "highway": "path",
    "bicycle": "designated",
    "surface": "dirt",
    "mtb:scale:imba": "0",
    "name": "Chesapeake and Ohio Canal Towpath",
}
TOWPATH_BELOW_LOCK_21 = {
    "highway": "cycleway",
    "surface": "fine_gravel",
    "name": "Chesapeake and Ohio Canal Towpath",
}


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "path", "mtb:scale": "1"},
        {"highway": "path", "mtb:scale": "2+"},
        {"highway": "path", "mtb:scale:imba": "1", "bicycle": "designated"},
        {"highway": "footway", "mtb:scale": "1", "bicycle": "yes"},
        {"highway": "bridleway", "mtb:scale:imba": "2"},
    ],
)
def test_a_rated_mtb_trail_is_singletrack(tags) -> None:
    assert is_singletrack(tags)


@pytest.mark.parametrize(
    "tags",
    [
        TOWPATH_ABOVE_LOCK_21,
        TOWPATH_BELOW_LOCK_21,
        # Gravel and dirt are not singletrack on their own (item 91).
        {"highway": "path", "surface": "dirt", "bicycle": "yes"},
        {"highway": "track", "surface": "gravel", "tracktype": "grade2"},
        # A track is double-track: gravel roads carry mtb:scale 1 and more.
        {"highway": "track", "mtb:scale": "3"},
        {"highway": "path", "surface": "ground", "sac_scale": "hiking"},
        {"highway": "cycleway", "surface": "compacted", "name": "Capital Crescent Trail"},
        {"highway": "path", "mtb:scale": "0"},
        {"highway": "path", "mtb:scale": "0+", "mtb:scale:imba": "0"},
        # A road is never singletrack, whatever a mapper rated it.
        {"highway": "unclassified", "mtb:scale": "1"},
        {"highway": "path", "mtb:scale": "unknown"},
    ],
)
def test_gravel_dirt_the_towpath_and_roads_are_not(tags) -> None:
    assert not is_singletrack(tags)


def test_grade_reads_the_leading_number() -> None:
    assert grade("2+") == 2
    assert grade("1-") == 1
    assert grade(" 3") == 3
    assert grade("0") == 0
    assert grade("none") is None
    assert grade(None) is None


@pytest.mark.parametrize(
    "surface", ["asphalt", "concrete", "paved", "paving_stones", "concrete:plates", "chipseal"]
)
def test_a_paved_trail_is_not_singletrack_whatever_its_rating(surface) -> None:
    """Upper Rock Creek Trail (way 1262786822): asphalt, bicycle=designated,
    carrying an mtb:scale - closed on every graph until the review (r1)."""
    tags = {"highway": "cycleway", "surface": surface, "mtb:scale": "1", "bicycle": "designated"}
    assert not is_singletrack(tags)
    assert is_singletrack({**tags, "surface": "dirt"})
    assert is_singletrack({k: v for k, v in tags.items() if k != "surface"})
