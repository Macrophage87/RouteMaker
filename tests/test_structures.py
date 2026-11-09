"""Bridges and tunnels read straight across in the Climbs layer's profiles
(`routemaker.structures`; hunt finding E3, 2026-11-08).

The ground model is bare earth (USGS 3DEP): a bridge's samples read the valley under its deck
and a tunnel's the hill over it, so a Cat 5 climb was found starting mid-deck. (The router's
own profile is already levelled by Valhalla, hunt findings E1 and E4.) Pure.
"""

from __future__ import annotations

import pytest

from routemaker import climb_categories, structures

STEP = 30.0
TOTAL_M = 3000.0
BRIDGE = (1365.0, 1635.0)  # 270 m in the middle


def dipped(dip_m: float, base: float = 60.0) -> list[float]:
    """3 km of level road at `base`, its middle 270 m a level bridge whose bare-earth ground
    dips V-shaped `dip_m` below it (a Rock Creek valley)."""
    mid, half = sum(BRIDGE) / 2, (BRIDGE[1] - BRIDGE[0]) / 2
    out = []
    for i in range(int(TOTAL_M / STEP) + 1):
        d = abs(i * STEP - mid)
        out.append(base - dip_m * (1 - d / half) if d < half else base)
    return out


class TestLevel:
    def test_samples_inside_a_span_lie_on_the_line_between_its_ends(self):
        along = [0.0, 30.0, 60.0, 90.0, 120.0]
        out = structures.level(along, [10.0, 0.0, -5.0, 0.0, 14.0], [(10.0, 100.0)])
        # Anchored at 0 m (10) and 120 m (14): straight between them.
        assert out == pytest.approx([10.0, 11.0, 12.0, 13.0, 14.0])

    def test_a_structure_at_the_profiles_end_is_held_level(self):
        out = structures.level([0.0, 30.0, 60.0], [10.0, 2.0, 1.0], [(20.0, 70.0)])
        assert out == [10.0, 10.0, 10.0]

    def test_a_dip_under_a_bridge_is_read_as_the_deck(self):
        along = [i * STEP for i in range(int(TOTAL_M / STEP) + 1)]
        assert structures.level(along, dipped(35), [BRIDGE]) == pytest.approx(dipped(0))

    def test_touching_spans_are_one(self):
        assert structures.merged([(30.0, 60.0), (0.0, 30.5), (100.0, 120.0)]) == [
            (0.0, 60.0),
            (100.0, 120.0),
        ]

    def test_osm_tags_say_which_ways_are_structures(self):
        assert structures.is_structure_tags({"bridge": "yes"})
        assert structures.is_structure_tags({"bridge": "viaduct"})
        assert structures.is_structure_tags({"tunnel": "yes"})
        assert not structures.is_structure_tags({"bridge": "no"})
        assert not structures.is_structure_tags({"highway": "residential"})


class TestClimbFinder:
    def test_a_bridge_dip_is_no_longer_the_foot_of_a_climb(self):
        # E3: level at 60 m, the bridge, then 1.2% for 1.2 km (14 m of real gain).
        heights = dipped(35)[: int(1800 / STEP)]
        heights += [60.0 + 0.012 * (i * STEP) for i in range(1, int(1200 / STEP) + 1)]
        along = [i * STEP for i in range(len(heights))]
        before = climb_categories.find_in_piece(list(zip(along, heights, strict=True)))
        assert before  # a Cat 5 starting mid-deck, before the fix
        flat = structures.level(along, heights, [BRIDGE])
        assert climb_categories.find_in_piece(list(zip(along, flat, strict=True))) == []
