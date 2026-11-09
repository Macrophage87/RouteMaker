"""Mountain-bike singletrack, which every current ride type avoids
(routemaker.singletrack; OWNER-DECISIONS 90, 91, 93, 111)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from routemaker import singletrack
from routemaker.singletrack import grade, is_singletrack, mtb_scale_words

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


# The same cases as frontend/src/lib/featureHover.test.ts, which says them in the hover card.
@pytest.mark.parametrize(
    ("tags", "words"),
    [
        ({"mtb:scale": "2"}, "S2"),
        ({"mtb:scale:imba": "1"}, "IMBA 1"),
        ({"mtb:scale": "1", "mtb:scale:imba": "1"}, "S1 and IMBA 1 (rated on both scales)"),
        ({"mtb:scale": "2", "mtb:scale:imba": "3"}, "IMBA 3 (also rated S2, easier)"),
        ({"mtb:scale": "5", "mtb:scale:imba": "4"}, "S5 and IMBA 4 (rated on both scales)"),
        ({"mtb:scale": "1-2"}, "S2"),
        ({"mtb:scale": "2+", "mtb:scale:imba": "0"}, "S2 (also rated IMBA 0, easier)"),
        ({"mtb:scale": "steep"}, None),
        ({"surface": "dirt"}, None),
        (None, None),
    ],
)
def test_mtb_scale_words_say_which_scale_set_the_level(tags, words) -> None:
    """The owner, 2026-10-28: "say which rating type triggered the rating and if they are
    rated on both scales say that"."""
    assert mtb_scale_words(tags) == words


@pytest.mark.parametrize(
    "tags",
    [
        {
            "highway": "cycleway",
            "bicycle": "designated",
            "surface": "fine_gravel",
            "mtb:scale": "1",
        },
        {"highway": "path", "bicycle": "designated", "surface": "compacted", "mtb:scale": "1"},
        {"highway": "cycleway", "surface": "gravel", "mtb:scale:imba": "1"},
    ],
)
def test_an_easy_rating_on_a_built_gravel_trail_is_not_singletrack(tags) -> None:
    """The hunt of 2026-11-08 (A4): a crushed-stone rail-trail rated 1 was closed as
    singletrack on every standard graph. Before: is_singletrack True."""
    assert not is_singletrack(tags)


@pytest.mark.parametrize(
    "tags",
    [
        # Harder than easy is still singletrack, gravel or not.
        {"highway": "cycleway", "bicycle": "designated", "surface": "gravel", "mtb:scale": "2"},
        # Not built for bicycles: a rated gravel footpath is still read by its rating.
        {"highway": "path", "surface": "gravel", "mtb:scale": "1"},
        # Dirt is not gravel.
        {"highway": "path", "bicycle": "designated", "surface": "dirt", "mtb:scale": "1"},
    ],
)
def test_the_gravel_exception_is_narrow(tags) -> None:
    assert is_singletrack(tags)


def test_the_gravel_exception_reads_the_uphill_rating_as_the_lua_rule_does() -> None:
    """Terrain hunt 2, T2: `mtb:scale=1` with `mtb:scale:uphill=2` on a gravel cycleway.
    Before: not singletrack (open on every graph), while the Lua rule
    (`strip_easy_gravel_ratings`, which reads `mtb:scale:uphill`) kept the rating for the
    parser, which priced the trail as the gravel class. After: singletrack, as the Lua rule
    reads it (a 2 on any rating it reads is technical ground)."""
    trail = {"highway": "cycleway", "surface": "gravel", "mtb:scale": "1"}
    assert not is_singletrack(trail)
    assert not is_singletrack({**trail, "mtb:scale:uphill": "1"})
    assert is_singletrack({**trail, "mtb:scale:uphill": "2"})
    # The Lua rule's keys are among the ones read here (lua/routemaker_remap.lua).
    lua = Path(__file__).resolve().parents[1] / "lua" / "routemaker_remap.lua"
    keys = re.search(r"M\.SURFACE_RATING_KEYS = \{([^}]*)\}", lua.read_text()).group(1)
    assert set(re.findall(r'"([^"]+)"', keys)) <= set(singletrack.EASY_GRAVEL_KEYS)
