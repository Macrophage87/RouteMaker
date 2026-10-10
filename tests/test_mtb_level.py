"""The mountain-bike difficulty level (routemaker.singletrack.mtb_level; OWNER-DECISIONS
456, 456a-c; docs/MTB-TOPO-PLAN.md, slice 2)."""

from __future__ import annotations

import pytest

from routemaker.singletrack import MTB_LEVELS, mtb_level, mtb_name, scale_grade


@pytest.mark.parametrize(
    ("value", "top", "expected"),
    [
        ("0", 6, 0),
        ("1", 6, 1),
        ("2+", 6, 2),
        ("1-", 6, 1),
        (" 3 ", 6, 3),
        ("S2", 6, 2),
        ("1-2", 6, 2),
        ("1;3", 6, 3),
        ("1.5", 6, 1),
        ("6", 6, 6),
        # Past the scale's top reads as the top (review of slice 2): never the unrated grey.
        ("7", 6, 6),
        ("5", 4, 4),
        ("4", 4, 4),
        ("2;9", 6, 6),
        ("yes", 6, None),
        ("", 6, None),
        (None, 6, None),
    ],
)
def test_scale_grade_reads_the_hardest_grade_on_the_scale(value, top, expected) -> None:
    assert scale_grade(value, top) == expected


@pytest.mark.parametrize(
    ("tags", "level"),
    [
        # mtb:scale S1-S3 to 1-3, S4-S6 to 4.
        ({"mtb:scale": "1"}, 1),
        ({"mtb:scale": "2"}, 2),
        ({"mtb:scale": "3"}, 3),
        ({"mtb:scale": "4"}, 4),
        ({"mtb:scale": "5"}, 4),
        ({"mtb:scale": "6"}, 4),
        # IMBA 1-4 are 1-4.
        ({"mtb:scale:imba": "1"}, 1),
        ({"mtb:scale:imba": "2"}, 2),
        ({"mtb:scale:imba": "3"}, 3),
        ({"mtb:scale:imba": "4"}, 4),
        # Signs and ranges.
        ({"mtb:scale": "2+"}, 2),
        ({"mtb:scale": "1-"}, 1),
        ({"mtb:scale": "2-3"}, 3),
        # The higher of the two scales.
        ({"mtb:scale": "1", "mtb:scale:imba": "3"}, 3),
        ({"mtb:scale": "5", "mtb:scale:imba": "2"}, 4),
        ({"mtb:scale": "2", "mtb:scale:imba": "garbage"}, 2),
        # Off the scale: the hardest level.
        ({"mtb:scale": "7"}, 4),
        ({"mtb:scale:imba": "5"}, 4),
        ({"mtb:scale": "9"}, 4),
        # 0 on one scale and 1 or more on the other is singletrack (456b): the other's level.
        ({"mtb:scale": "0", "mtb:scale:imba": "2"}, 2),
        ({"mtb:scale": "3", "mtb:scale:imba": "0"}, 3),
    ],
)
def test_the_level_is_the_higher_rating(tags, level) -> None:
    assert mtb_level({"highway": "path", **tags}) == level
    assert level in MTB_LEVELS


@pytest.mark.parametrize(
    "tags",
    [
        # 0 is the easiest grade, and a gravel trail, not an MTB level (456b): no level.
        {"mtb:scale": "0"},
        {"mtb:scale:imba": "0"},
        {"mtb:scale": "0", "mtb:scale:imba": "0"},
        {"mtb:scale": "0+"},
        # Unrated, or nothing on a scale.
        {},
        {"mtb:scale": "yes"},
        {"mtb:scale:uphill": "3"},
    ],
)
def test_no_level_for_zero_unrated_or_off_the_scale(tags) -> None:
    assert mtb_level({"highway": "path", **tags}) is None


# ---- the trail's name (the owner, 2026-10-10: "Also, for mountain bikes, try to make sure
# trail names are added in if they are available.") ---------------------------------------


@pytest.mark.parametrize(
    ("tags", "name"),
    [
        ({"name": "Rosaryville Trail"}, "Rosaryville Trail"),
        ({"name": "Rosaryville Trail", "ref": "RT", "mtb:name": "Rosie"}, "Rosaryville Trail"),
        # Falls back to `mtb:name`, then `ref` last: a bare ref ("12") could be read as a level.
        ({"ref": "12", "mtb:name": "Hard Way"}, "Hard Way"),
        ({"mtb:name": "Hard Way"}, "Hard Way"),
        ({"ref": "Loop 3"}, "Loop 3"),
        # Blank values do not count, and the name is trimmed.
        ({"name": "  ", "ref": "", "mtb:name": " Hard Way "}, "Hard Way"),
        ({"name": " Fairland Loop "}, "Fairland Loop"),
    ],
)
def test_the_name_is_name_then_ref_then_mtb_name(tags, name) -> None:
    assert mtb_name({"highway": "path", **tags}) == name


@pytest.mark.parametrize("tags", [{}, {"name": ""}, {"name": " ", "ref": " "}, {"alt_name": "X"}])
def test_no_name_when_none_is_mapped(tags) -> None:
    assert mtb_name({"highway": "path", **tags}) is None
