"""A posted speed tagged by direction or as a list (review 2026-10-29): the classifier read
only a plain `maxspeed`, so such a road took the class default as if unposted, while the
router read the directional keys."""

from __future__ import annotations

import pytest

from routemaker import speed_corrections
from routemaker.stress import RURAL_EXPRESSWAY_PREFIX, Stress, classify, legal_but_avoid
from routemaker.tags import posted_maxspeed

RESIDENTIAL = {"highway": "residential"}


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({}, None),
        ({"maxspeed": "25 mph"}, "25 mph"),
        ({"maxspeed": "25 mph;35 mph"}, "35 mph"),
        ({"maxspeed": "45;55"}, "55"),
        ({"maxspeed:forward": "30 mph"}, "30 mph"),
        ({"maxspeed:forward": "25 mph", "maxspeed:backward": "35 mph"}, "35 mph"),
        ({"maxspeed:backward": "25 mph;40 mph"}, "40 mph"),
        # A plain value wins: the District's street layer writes its speed there.
        ({"maxspeed": "25 mph", "maxspeed:forward": "35 mph"}, "25 mph"),
        # Unreadable values stay as they were: unposted.
        ({"maxspeed:forward": "signals"}, None),
        ({"maxspeed": "none"}, "none"),
    ],
)
def test_the_reader(tags: dict[str, str], expected: str | None) -> None:
    assert posted_maxspeed(tags) == expected


def test_a_directional_posting_in_the_district_is_read() -> None:
    """Measured before this: LTS 1, "20 mph or below" (the District default)."""
    tags = {**RESIDENTIAL, "maxspeed:forward": "30 mph", "maxspeed:backward": "30 mph"}
    directional = classify(tags, jurisdiction="DC")
    plain = classify({**RESIDENTIAL, "maxspeed": "30 mph"}, jurisdiction="DC")
    assert directional.tier == plain.tier
    assert directional.rule == plain.rule
    assert "maxspeed" not in directional.assumed


def test_a_list_is_read_as_its_highest_part() -> None:
    listed = classify({**RESIDENTIAL, "maxspeed": "25 mph;35 mph"}, jurisdiction="DC")
    assert listed.tier == classify({**RESIDENTIAL, "maxspeed": "35 mph"}).tier
    assert listed.tier is Stress.LTS4


def test_a_bare_number_in_a_list_still_records_the_unit() -> None:
    assert "maxspeed unit" in classify({**RESIDENTIAL, "maxspeed": "25;30"}).assumed


def test_a_rural_road_posted_by_list_is_not_the_narrow_road() -> None:
    """Measured before this: LTS 2, "narrow rural road" (the unposted 25 mph rule)."""
    road = {"highway": "tertiary", "maxspeed": "45;55", "lane_markings": "no"}
    result = classify(road, urban=False)
    assert "narrow rural road" not in result.rule
    assert result.tier >= Stress.LTS4


def test_the_expressway_rule_reads_the_directional_speed() -> None:
    road = {"highway": "trunk", "expressway": "yes", "maxspeed:forward": "55 mph"}
    assert legal_but_avoid(road, urban=True) is not None
    assert classify(road, urban=True).tier is Stress.AVOID
    assert classify(road, urban=False).rule.startswith(RURAL_EXPRESSWAY_PREFIX)


def test_a_curated_speed_never_overwrites_a_directional_posting() -> None:
    posted = {**RESIDENTIAL, "maxspeed:forward": "30 mph"}
    assert speed_corrections.corrected(posted, "25 mph") == (posted, False)
    listed = {**RESIDENTIAL, "maxspeed": "25 mph;30 mph"}
    assert speed_corrections.corrected(listed, "25 mph") == (listed, False)
    assert speed_corrections.corrected(RESIDENTIAL, "25 mph") == (
        {**RESIDENTIAL, "maxspeed": "25 mph"},
        True,
    )
