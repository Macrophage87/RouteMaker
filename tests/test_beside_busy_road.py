"""Side paths and protected lanes beside busy roads (the owner, 2026-11-12: protected lanes
along roads like Old Georgetown Road "are fine for experienced cyclists, they might not be
LTS 1"): an unnamed trail-class way beside a named street takes a level from that street,
1.5 beside LTS 3 or 3.5 and 2 beside LTS 4 or above (our defaults, not measured)."""

from __future__ import annotations

import pytest

from core import segment_info
from pipeline.run import apply_beside_busy_road
from routemaker import facility
from routemaker.stress import (
    BESIDE_BUSY_ROAD_RULE,
    Stress,
    StressAdjustment,
    StressResult,
    beside_busy_road_step,
    level_of,
)

PATH = StressResult(Stress.LTS1, "trail-class way (cycleway, open to bicycles)")
_LON_M = 1 / 86_700.0
ROAD = [(-77.1100, 39.0000), (-77.1100, 39.0040)]


def _east(points, metres):
    return [(lon + metres * _LON_M, lat) for lon, lat in points]


@pytest.mark.parametrize(
    ("road", "tier", "half"),
    [
        (3.0, Stress.LTS1, True),
        (3.5, Stress.LTS1, True),
        (4.0, Stress.LTS2, False),
        (4.5, Stress.LTS2, False),
        (5.0, Stress.LTS2, False),
    ],
)
def test_a_path_beside_a_busy_road_takes_a_level_from_it(road, tier, half):
    stepped = beside_busy_road_step(PATH, road)
    assert (stepped.tier, stepped.half) == (tier, half)
    assert stepped.rule.startswith(f"{BESIDE_BUSY_ROAD_RULE} (road at LTS {road:g})")


@pytest.mark.parametrize("road", [None, 1.0, 2.0, 2.5])
def test_a_path_beside_a_calm_street_or_none_stays_at_1(road):
    assert beside_busy_road_step(PATH, road) is PATH


def test_a_path_already_above_1_is_left_alone():
    gravel = StressResult(Stress.LTS2, "trail-class way (path, open to bicycles)")
    assert beside_busy_road_step(gravel, 4.0) is gravel
    half = StressResult(Stress.LTS1, "trail-class way (path)", half=True)
    assert beside_busy_road_step(half, 4.0) is half


def test_an_owner_row_on_the_path_stands():
    row = StressAdjustment(
        tier=Stress.LTS1,
        adjustment_id="test-row",
        computed_tier=Stress.LTS1,
        category="other",
        visibility="public",
        annotation_status="approved",
    )
    rated = StressResult(Stress.LTS1, "override: stress adjustment test-row", adjustment=row)
    assert beside_busy_road_step(rated, 4.0) is rated


def test_level_of_reads_an_owner_rows_half_step():
    row = StressAdjustment(
        tier=Stress.LTS3,
        adjustment_id="test-row",
        computed_tier=Stress.LTS4,
        category="other",
        visibility="public",
        annotation_status="approved",
        half=True,
    )
    assert level_of(StressResult(Stress.LTS3, "override", adjustment=row)) == 3.5
    assert level_of(StressResult(Stress.LTS3, "agency", half=True)) == 3.5
    assert level_of(StressResult(Stress.LTS4, "mixed traffic")) == 4.0


def test_the_rebuild_rates_an_unnamed_path_from_the_road_beside_it():
    ways = [
        (1, {"highway": "primary", "name": "Old Georgetown Road"}, ROAD),
        (2, {"highway": "cycleway"}, _east(ROAD, 10)),
        (3, {"highway": "cycleway", "name": "Bethesda Trolley Trail"}, _east(ROAD, -10)),
    ]
    beside = facility.side_streets(ways)
    assert set(beside) == {2}
    assert beside[2].name == "Old Georgetown Road bike lane"
    stress = {
        1: StressResult(Stress.LTS4, "mixed traffic, 40 mph"),
        2: PATH,
        3: PATH,
    }
    assert apply_beside_busy_road(stress, beside) == 1
    assert (stress[2].tier, stress[2].half) == (Stress.LTS2, False)
    # A named trail is its own route, never asked.
    assert stress[3] is PATH


def test_a_few_metres_along_a_busier_way_do_not_set_the_level():
    found = facility.SideStreet("Old Georgetown Road bike lane", {1: 950.0, 4: 50.0})
    stress = {
        1: StressResult(Stress.LTS3, "mixed traffic, 30 mph"),
        4: StressResult(Stress.LTS4, "mixed traffic, 40 mph"),
        2: PATH,
    }
    apply_beside_busy_road(stress, {2: found})
    assert (stress[2].tier, stress[2].half) == (Stress.LTS1, True)


def test_the_road_panel_says_why_in_words():
    words = segment_info.rule_words(
        f"{BESIDE_BUSY_ROAD_RULE} (road at LTS 4), trail-class way (cycleway, open to bicycles)"
    )
    assert words.startswith("Path beside a busy road (LTS 4)")


# --- What a side path crosses (the owner, 2026-11-12: "If there are lots of intersections,
# especially sliplanes it could get an even larger bump") -----------------------------------


def test_bad_crossings_or_a_slip_lane_add_half_a_level():
    busy = beside_busy_road_step(PATH, 4.0, crossing_score=24.0)
    assert (busy.tier, busy.half) == (Stress.LTS2, True)
    assert "crossings score 24 a mile" in busy.rule
    slip = beside_busy_road_step(PATH, 3.0, slip_lane=True)
    assert (slip.tier, slip.half) == (Stress.LTS2, False)
    assert "crosses a slip lane" in slip.rule
    few = beside_busy_road_step(PATH, 4.0, crossing_score=8.0)
    assert (few.tier, few.half) == (Stress.LTS2, False)
    # No cap of its own (the owner: "no upper limit"), but nothing is Avoid: 4.5 at most.
    worse = beside_busy_road_step(PATH, 4.0, crossing_score=61.0, slip_lane=True)
    assert (worse.tier, worse.half) == (Stress.LTS4, False)
    worst = beside_busy_road_step(PATH, 4.0, crossing_score=500.0, slip_lane=True)
    assert (worst.tier, worst.half) == (Stress.LTS4, True)
    # Beside a calm street, crossings alone do not step a path.
    assert beside_busy_road_step(PATH, 2.0, crossing_score=90.0, slip_lane=True) is PATH


def _line(lat0, n, step_deg=0.0005):
    return [(-77.11, lat0 + i * step_deg) for i in range(n)]


def test_crossings_are_weighted_by_how_bad_they_are_over_the_run():
    side = {
        10: facility.SideStreet("path beside Old Georgetown Road", {1: 100.0}),
        11: facility.SideStreet("path beside Old Georgetown Road", {1: 100.0}),
    }
    ways = [
        # Two side-path ways joined at node 103.
        (10, {"highway": "cycleway"}, [100, 101, 102, 103], _line(39.0, 4)),
        (11, {"highway": "cycleway"}, [103, 104, 105, 106], _line(39.0015, 4)),
        # A driveway at 101 (class weight 1.5), a street at 102 rated 3 by the rebuild.
        (20, {"highway": "service", "service": "driveway"}, [101, 900], []),
        (21, {"highway": "residential"}, [102, 901], []),
        # A slip lane at 104 (class weight 4 + 2), a tertiary at 105 (2.5).
        (23, {"highway": "primary_link"}, [104, 903], []),
        (22, {"highway": "tertiary"}, [105, 902], []),
        # A footway at 106 is no crossing.
        (24, {"highway": "footway"}, [106, 904], []),
    ]
    found = facility.side_path_crossings(ways, side, {21: 3.0}.get)
    miles = facility._length_m(_line(39.0, 7)) / 1609.344
    assert found[10].score_per_mile == pytest.approx((1.5 + 3.0 + 6.0 + 2.5) / miles, rel=0.02)
    assert found[10].score_per_mile == found[11].score_per_mile
    assert (found[10].slip_lane, found[11].slip_lane) == (False, True)


def test_a_short_run_reads_no_rate():
    side = {10: facility.SideStreet("path beside Old Georgetown Road", {1: 50.0})}
    ways = [
        (10, {"highway": "cycleway"}, [100, 101], _line(39.0, 2)),
        (20, {"highway": "service"}, [101, 900], []),
    ]
    assert facility.side_path_crossings(ways, side)[10].score_per_mile is None
