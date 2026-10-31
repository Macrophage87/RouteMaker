"""The owner's rules over DDOT's 2020 LTS (`routemaker.ddot_rules`; 2026-10-31, "I agree with
these"), on blocks the DC review read from the road panel (reports/dc-ratings-audit/)."""

from __future__ import annotations

import pytest

from routemaker import agency_lts, ddot_rules
from routemaker.agency_lts import AgencyRating
from routemaker.ddot_rules import Block
from routemaker.stress import Stress, StressResult


def level(**kw) -> float | None:
    found = ddot_rules.read_as(Block(**kw))
    return None if found is None else found[0]


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        # Busy roadways DDOT rated LTS 1 with the path or lane beside them.
        (dict(ddot=1, formula=3, aadt=45_334, lanes=4), 4.0),  # Arlington Memorial Bridge
        (dict(ddot=1, formula=3, aadt=22_066, lanes=4), 3.5),  # H St NW, 3rd to 4th
        (dict(ddot=1, formula=3, aadt=15_110, lanes=2), 3.0),  # Chain Bridge
        (dict(ddot=1, formula=3, aadt=9_715, lanes=4), 3.0),  # 15th St NW roadway
        # Counted streets too busy for LTS 1.
        (dict(ddot=1, formula=2, aadt=9_500, lanes=2), 2.5),  # L St SE by the bridge ramps
        (dict(ddot=1, formula=2, aadt=6_700, lanes=3), 2.5),  # New Jersey Ave NW, Mass to H
        (dict(ddot=1, formula=2, aadt=5_600, lanes=2), 2.0),  # 21st St NW, G to I
        # DDOT 2, formula 3 or 4.
        (dict(ddot=2, formula=3, aadt=14_400, lanes=2), 3.0),  # Sherman Ave NW
        (dict(ddot=2, formula=4, aadt=33_700, lanes=4), 3.5),  # Maine Ave SW roadway
        (dict(ddot=2, formula=3, aadt=5_500, lanes=2), 2.5),
        # DDOT above the formula, no lane: the owner's 1st Street rule by count.
        (dict(ddot=4, formula=2, aadt=7_520, lanes=2), 2.5),  # 1st St NW
        (dict(ddot=3, formula=2, aadt=3_942, lanes=1), 2.5),  # R St NW, unpainted
        (dict(ddot=3, formula=2, aadt=2_309, lanes=2), 2.0),  # Western Ave NW
        (dict(ddot=4, formula=2, aadt=9_226, lanes=2), 3.0),  # Stanton Rd SE
        # Arterials, DDOT 4 and formula 3.
        (dict(ddot=4, formula=3, aadt=11_700, lanes=4), 3.5),  # Minnesota Ave NE
        (dict(ddot=4, formula=3, aadt=6_890, lanes=4), 3.0),  # 11th St NW, F to L
        (dict(ddot=4, formula=3, aadt=16_500, lanes=2), 3.5),  # Columbia Rd NW
        (dict(ddot=4, formula=3, aadt=8_300, lanes=2), 3.0),  # Minnesota Ave SE
        # A counted quiet street, half a step calmer than DDOT's 2.
        (dict(ddot=2, formula=1, aadt=949, lanes=2), 1.5),  # Linnean Ave NW
        # Painted lanes, by the traffic beside them.
        (dict(ddot=4, formula=1, aadt=24_499, lanes=3, painted_lane=True), 3.5),  # Thomas Cir
        (dict(ddot=1, formula=2, aadt=15_552, lanes=2, painted_lane=True), 2.5),  # 12th St NW
        (dict(ddot=4, formula=2, aadt=12_871, lanes=4, painted_lane=True), 3.0),  # Maryland Ave NE
        (dict(ddot=3, formula=2, aadt=3_000, lanes=4, painted_lane=True), 2.5),  # E St NW
        (dict(ddot=1, formula=2, aadt=4_000, lanes=2, painted_lane=True), 2.0),  # Kansas Ave NW
    ],
)
def test_a_stale_ddot_level_reads_as_the_level_the_block_now_gives(block, expected) -> None:
    assert level(**block) == expected


@pytest.mark.parametrize(
    "block",
    [
        # Where they agree, nothing changes.
        dict(ddot=3, formula=3, aadt=8_000, lanes=2),
        # No count: no evidence either way, DDOT stands.
        dict(ddot=2, formula=1, aadt=None, lanes=2),
        dict(ddot=4, formula=2, aadt=None, lanes=2),
        dict(ddot=1, formula=3, aadt=None, lanes=4),
        # A quiet two-way street over 1,200 a day keeps DDOT's 2 (LTS 1 is for kids).
        dict(ddot=2, formula=1, aadt=2_461, lanes=2),
        # Big arterials keep DDOT's 4.
        dict(ddot=4, formula=3, aadt=18_000, lanes=4),  # 16th St NW, Upshur to Varnum
        dict(ddot=4, formula=3, aadt=11_000, lanes=6),  # M St SE
        dict(ddot=4, formula=3, aadt=22_000, lanes=2),  # Wisconsin Ave NW in Georgetown
        dict(ddot=4, formula=3, aadt=17_800, lanes=3),  # C St NE
        # A painted lane at R Street's traffic: the formula's own 2, by the facility set-aside.
        dict(ddot=3, formula=2, aadt=3_942, lanes=1, painted_lane=True),
        # A protected lane or path: the facility set-aside decides, not these rules.
        dict(ddot=1, formula=3, aadt=22_000, lanes=4, protected=True),
        # Avoid is never read otherwise.
        dict(ddot=5, formula=3, aadt=20_000, lanes=4),
    ],
)
def test_ddot_stands_where_the_review_found_no_clear_reason(block) -> None:
    assert ddot_rules.read_as(Block(**block)) is None


def test_a_struck_rule_leaves_ddot_as_it_is() -> None:
    block = Block(ddot=1, formula=3, aadt=45_334, lanes=4)
    assert ddot_rules.read_as(block, enabled=ddot_rules.ENABLED - {"busy-road-at-1"}) is None


def test_the_road_panel_says_why_ddot_was_read_otherwise() -> None:
    bridge = StressResult(Stress.LTS3, "four lanes", (), volume_aadt=45_334, lanes=2, oneway=False)
    result = agency_lts.apply(bridge, [AgencyRating("ddot", 1)])
    assert result.tier is Stress.LTS4
    (held,) = result.agency_ratings
    assert (held.level, held.read_as) == (1, 4.0)
    assert held.note == "read as LTS 4: a busy roadway DDOT rated with the path or lane beside it"
    assert "," not in held.note


def test_only_ddot_is_read_by_these_rules() -> None:
    county = StressResult(Stress.LTS3, "x", (), volume_aadt=45_334, lanes=2, oneway=False)
    result = agency_lts.apply(county, [AgencyRating("moco", 1)])
    assert result.tier is Stress.LTS1
    assert result.agency_ratings == (AgencyRating("moco", 1),)


def test_every_rule_has_words_without_commas() -> None:
    assert ddot_rules.ENABLED == frozenset(ddot_rules.RULE_WORDS)
    assert all("," not in words for words in ddot_rules.RULE_WORDS.values())


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        # Each threshold, on both sides.
        (dict(ddot=1, formula=3, aadt=30_000, lanes=4), 4.0),
        (dict(ddot=1, formula=3, aadt=29_999, lanes=4), 3.5),
        (dict(ddot=1, formula=3, aadt=15_000, lanes=3), 3.5),
        (dict(ddot=1, formula=3, aadt=14_999, lanes=3), 3.0),
        (dict(ddot=1, formula=3, aadt=15_000, lanes=2), 3.0),
        (dict(ddot=1, formula=3, aadt=6_000, lanes=2), 3.0),
        (dict(ddot=1, formula=3, aadt=5_999, lanes=2), 2.5),
        (dict(ddot=1, formula=2, aadt=9_000, lanes=2), 2.5),
        (dict(ddot=1, formula=2, aadt=8_999, lanes=2), 2.0),
        (dict(ddot=1, formula=2, aadt=6_000, lanes=3), 2.5),
        (dict(ddot=1, formula=2, aadt=5_999, lanes=3), 2.0),
        (dict(ddot=1, formula=2, aadt=3_000, lanes=2), 2.0),
        (dict(ddot=1, formula=2, aadt=2_999, lanes=2), None),
        (dict(ddot=2, formula=1, aadt=1_200, lanes=2), 1.5),
        (dict(ddot=2, formula=1, aadt=1_201, lanes=2), None),
        (dict(ddot=2, formula=3, aadt=10_000, lanes=4), 3.5),
        (dict(ddot=2, formula=3, aadt=9_999, lanes=4), 3.0),
        (dict(ddot=2, formula=3, aadt=8_000, lanes=2), 3.0),
        (dict(ddot=2, formula=3, aadt=7_999, lanes=2), 2.5),
        (dict(ddot=2, formula=3, aadt=4_500, lanes=2), 2.5),
        (dict(ddot=2, formula=3, aadt=4_499, lanes=2), None),
        (dict(ddot=3, formula=2, aadt=8_000, lanes=2), None),  # 3 is DDOT's own
        (dict(ddot=4, formula=2, aadt=8_000, lanes=2), 3.0),
        (dict(ddot=4, formula=2, aadt=7_999, lanes=2), 2.5),
        (dict(ddot=4, formula=2, aadt=3_000, lanes=2), 2.5),
        (dict(ddot=4, formula=2, aadt=2_999, lanes=2), 2.0),
        (dict(ddot=4, formula=3, aadt=10_000, lanes=6), None),
        (dict(ddot=4, formula=3, aadt=9_999, lanes=6), 3.0),
        (dict(ddot=4, formula=3, aadt=15_000, lanes=4), None),
        (dict(ddot=4, formula=3, aadt=14_999, lanes=4), 3.5),
        (dict(ddot=4, formula=3, aadt=8_000, lanes=4), 3.5),
        (dict(ddot=4, formula=3, aadt=7_999, lanes=4), 3.0),
        (dict(ddot=4, formula=3, aadt=20_000, lanes=2), None),
        (dict(ddot=4, formula=3, aadt=19_999, lanes=2), 3.5),
        (dict(ddot=4, formula=3, aadt=15_000, lanes=2), 3.5),
        (dict(ddot=4, formula=3, aadt=14_999, lanes=2), 3.0),
        (dict(ddot=4, formula=3, aadt=15_000, lanes=3), None),
        (dict(ddot=4, formula=1, aadt=9_000, lanes=3, painted_lane=True), 3.0),
        (dict(ddot=4, formula=1, aadt=8_999, lanes=3, painted_lane=True), 2.5),
        (dict(ddot=4, formula=1, aadt=15_000, lanes=3, painted_lane=True), 3.5),
        (dict(ddot=4, formula=1, aadt=9_000, lanes=2, painted_lane=True), 2.5),
        (dict(ddot=4, formula=1, aadt=8_999, lanes=2, painted_lane=True), 2.0),
    ],
)
def test_each_threshold_falls_where_the_table_puts_it(block, expected) -> None:
    assert level(**block) == expected


@pytest.mark.parametrize(
    "block",
    [
        # DDOT 3 under a formula 4: no rule was proposed, the formula's 4 stands
        # (Connecticut Ave NW is the owner's LTS 4).
        dict(ddot=3, formula=4, aadt=20_000, lanes=4),
        # DDOT 2 under a formula half step calmer: not a stale DDOT 3 or 4.
        dict(ddot=2, formula=1.5, aadt=9_000, lanes=2),
        # A painted lane at DDOT's own calmer level: nothing to say.
        dict(ddot=2, formula=3, aadt=4_000, lanes=2, painted_lane=True),
    ],
)
def test_no_rule_reads_a_block_the_review_did_not_propose(block) -> None:
    assert ddot_rules.read_as(Block(**block)) is None


def test_a_struck_painted_lane_rule_falls_back_to_the_older_painted_lane_level() -> None:
    thomas_circle = StressResult(
        Stress.LTS1, "painted lane", (), volume_aadt=24_499, lanes=3, oneway=True
    )
    struck = ddot_rules.ENABLED - {"painted-lane"}
    from unittest import mock

    with mock.patch.object(ddot_rules, "ENABLED", struck):
        result = agency_lts.apply(
            thomas_circle,
            [AgencyRating("ddot", 4)],
            facility_mapped=True,
            painted_lane=True,
        )
    assert (int(result.tier), result.half) == (2, True)


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        # A busy street the formula reads 2.5 (5,000 to 7,999 a day): the 1st Street NW case.
        (dict(ddot=4, formula=2.5, aadt=7_520, lanes=2), 2.5),
        (dict(ddot=3, formula=2.5, aadt=6_000, lanes=2), 2.5),
        (dict(ddot=1, formula=2.5, aadt=6_000, lanes=2), 2.5),
        (dict(ddot=2, formula=2.5, aadt=6_000, lanes=2), 2.5),
        # DDOT 4 over an arterial the formula reads 3.5: by count, never below the formula.
        (dict(ddot=4, formula=3.5, aadt=6_890, lanes=4), 3.5),
        # DDOT 1 under a formula 3.5: as at 3, a bridge at 45,000 a day reads 4.
        (dict(ddot=1, formula=3.5, aadt=45_000, lanes=4), 4.0),
        (dict(ddot=1, formula=3.5, aadt=5_000, lanes=2), 3.5),
    ],
)
def test_a_formula_half_step_reads_ddot_by_its_whole_levels_rule(block, expected) -> None:
    assert level(**block) == expected


def test_a_busier_street_never_reads_calmer_than_a_quieter_one() -> None:
    quieter = level(ddot=1, formula=2, aadt=4_000, lanes=2)
    busier = level(ddot=1, formula=2.5, aadt=7_520, lanes=2)
    assert quieter == 2.0 and busier == 2.5
