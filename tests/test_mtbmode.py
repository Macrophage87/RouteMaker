"""The Mountain Bike ride type's pure rules (routemaker.mtbmode; docs/MTB-TOPO-PLAN.md, slice 6)."""

from __future__ import annotations

import pytest

from routemaker import mtbmode
from routemaker.mtbmode import Stretch

MILE = 1609.344


def road(metres: float, tier: int) -> Stretch:
    return Stretch(metres=metres, tier=tier, trail=False, singletrack=False, level=None)


def single(metres: float, level: int | None = 2) -> Stretch:
    return Stretch(metres=metres, tier=1, trail=True, singletrack=True, level=level)


def gravel(metres: float) -> Stretch:
    return Stretch(metres=metres, tier=1, trail=True, singletrack=False, level=None)


def test_the_owners_defaults() -> None:
    """The defaults approved on 2026-10-11 (plan file, "Stephen's answers")."""
    assert mtbmode.DEFAULT_MAX_LEVEL == 2
    assert mtbmode.LEVELS == (1, 2, 3, 4)
    assert mtbmode.UNRATED_LEVEL == 2
    assert mtbmode.TRAIL_WEIGHT == 0.5
    assert mtbmode.CONNECTOR_MAX_TIER == 2 and mtbmode.GAP_TIER == 3
    assert mtbmode.GAP_MAX_M == pytest.approx(0.5 * MILE)
    assert mtbmode.SINGLETRACK_SPEED_KMH == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("mtb_only", "level", "expected"),
    [(True, 3, 3), (True, None, 2), (False, None, None), (False, 4, 4), (True, 7, 2)],
)
def test_effective_level(mtb_only, level, expected) -> None:
    assert mtbmode.effective_level(mtb_only, level) == expected


def test_an_unrated_trail_is_over_a_level_1_choice_only() -> None:
    assert mtbmode.over_level(True, None, 1)
    assert not mtbmode.over_level(True, None, 2)
    # A road or an ordinary path is never over any level.
    assert not mtbmode.over_level(False, None, 1)


@pytest.mark.parametrize(("given", "held"), [(None, 2), (0, 1), (1, 1), (4, 4), (9, 4)])
def test_clamp_level(given, held) -> None:
    assert mtbmode.clamp_level(given) == held


@pytest.mark.parametrize(
    "tags",
    [
        {"bicycle:conditional": "no @ wet"},
        {"access:conditional": "no @ (wet)"},
        {"mtb:conditional": "no @ wet; yes @ (Sa,Su)"},
        {"vehicle:forward:conditional": "private @ (wet; Nov-Mar)"},
        {"bicycle:conditional": "yes @ (Sa,Su); dismount @ Wet"},
    ],
)
def test_a_wet_closure_is_read(tags) -> None:
    assert mtbmode.closed_when_wet(tags)


@pytest.mark.parametrize(
    "tags",
    [
        {},
        {"bicycle:conditional": "no @ (Nov-Mar)"},
        {"bicycle:conditional": "yes @ wet"},
        {"bicycle": "no", "note": "closed when wet"},
        {"bicycle:conditional": "no @ wetland_season"},
    ],
)
def test_no_wet_closure(tags) -> None:
    assert not mtbmode.closed_when_wet(tags)


def test_a_reading_counts_trail_singletrack_and_over_level() -> None:
    reading = mtbmode.read([road(500, 2), single(1000, 3), gravel(800), single(400, None)], 2)
    assert reading.length_m == 2700
    assert reading.trail_m == 2200
    assert reading.singletrack_m == 1400
    # Level 3 is over a level-2 choice; the unrated trail counts as 2.
    assert reading.over_level_m == 1000
    assert reading.weighted_m == pytest.approx(500 + 0.5 * 2200)


def test_lts3_is_allowed_for_a_short_gap_only() -> None:
    short = mtbmode.read([single(1000), road(0.4 * MILE, 3), single(1000)], 2)
    assert short.long_lts3_m == 0
    long_ = mtbmode.read([single(1000), road(0.3 * MILE, 3), road(0.3 * MILE, 3), single(500)], 2)
    # The two LTS 3 pieces are one run of 0.6 mi: past the gap, its whole length counted.
    assert long_.long_lts3_m == pytest.approx(0.6 * MILE)
    # A run broken by a calmer road is two short gaps.
    broken = mtbmode.read([road(0.3 * MILE, 3), road(50, 2), road(0.3 * MILE, 3)], 2)
    assert broken.long_lts3_m == 0
    # A run at the end of the route is closed too.
    assert mtbmode.read([single(10), road(0.6 * MILE, 3)], 2).long_lts3_m > 0


def test_lts4_and_avoid_always_breach() -> None:
    reading = mtbmode.read([road(100, 4), road(30, 5), road(1000, 2)], 2)
    assert reading.lts4_m == 130 and reading.breach_m == 130


def test_over_level_ranks_first() -> None:
    easy_long = mtbmode.read([road(5000, 2), single(2000, 2)], 2)
    hard_short = mtbmode.read([single(1000, 4)], 2)
    assert mtbmode.better(easy_long, hard_short)
    assert not mtbmode.better(hard_short, easy_long)


def test_connector_rule_ranks_before_length_beyond_the_slack() -> None:
    calm = mtbmode.read([road(3000, 2), single(1000)], 2)
    busy = mtbmode.read([road(500, 4), single(1000)], 2)
    assert mtbmode.better(calm, busy)
    # 40 m of LTS 4 (a crossing) is within the slack: length decides.
    crossing = mtbmode.read([road(40, 4), single(1000)], 2)
    assert mtbmode.better(crossing, calm)


def test_trail_seeking_a_trail_mile_counts_half() -> None:
    """1.8 mi of trail beats 1.0 mi of road: weighted 0.9 mi against 1.0."""
    trail = mtbmode.read([single(1.8 * MILE)], 2)
    roads = mtbmode.read([road(1.0 * MILE, 1)], 2)
    assert mtbmode.better(trail, roads)
    # but not 2.2 mi of trail (1.1 weighted)
    assert not mtbmode.better(mtbmode.read([single(2.2 * MILE)], 2), roads)
    assert mtbmode.best([roads, trail]) == 1


def test_best_keeps_the_first_on_a_tie() -> None:
    same = mtbmode.read([road(1000, 1)], 2)
    assert mtbmode.best([same, same, same]) == 0


def test_the_time_on_singletrack() -> None:
    # 10 km of which 5 km singletrack; the router said 30 min (20 km/h): the trail half is
    # 30 min at 10 km/h, the road half keeps its 15 min.
    assert mtbmode.duration_s(1800, 10_000, 5_000) == pytest.approx(900 + 1800)
    # Never faster than the router: a trail it already times at 8 km/h keeps its time.
    assert mtbmode.duration_s(4500, 10_000, 10_000) == pytest.approx(4500)
    assert mtbmode.duration_s(1800, 10_000, 0) == 1800
    assert mtbmode.duration_s(1800, 0, 100) == 1800


def test_the_front_end_holds_the_same_numbers() -> None:
    """lib/mtbMode.ts and stressStyle.js repeat the level rules so the picker and the map can
    show them before a route comes back; they must say what the API does."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "frontend" / "src"
    mode = (src / "lib" / "mtbMode.ts").read_text()

    def number(name: str, text: str) -> float:
        found = re.search(rf"export const {name}(?:: \w+)? = (\d+(?:\.\d+)?);", text)
        assert found, name
        return float(found.group(1))

    assert number("DEFAULT_MTB_LEVEL", mode) == mtbmode.DEFAULT_MAX_LEVEL
    assert number("UNRATED_MTB_LEVEL", mode) == mtbmode.UNRATED_LEVEL
    assert number("SINGLETRACK_SPEED_KMH", mode) == mtbmode.SINGLETRACK_SPEED_KMH
    style = (src / "stressStyle.js").read_text()
    assert number("MTB_UNRATED_LEVEL", style) == mtbmode.UNRATED_LEVEL
