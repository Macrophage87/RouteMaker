"""Side paths and protected lanes beside busy roads (the owner, 2026-11-12: protected lanes
along roads like Old Georgetown Road "are fine for experienced cyclists, they might not be
LTS 1"): a bike way beside a named street, by its geometry and whatever it is called, takes
a level from that street (1.5 beside LTS 3 or 3.5, 2 beside LTS 4 or 4.5, 2.5 beside Avoid),
and more for what a rider following it crosses (our defaults, not measured;
docs/stress/side-paths.md)."""

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
        (5.0, Stress.LTS2, True),
    ],
)
def test_a_path_beside_a_busy_road_takes_a_level_from_it(road, tier, half):
    stepped = beside_busy_road_step(PATH, road)
    assert (stepped.tier, stepped.half) == (tier, half)
    words = "road rated Avoid" if road == 5.0 else f"road at LTS {road:g}"
    assert stepped.rule.startswith(f"{BESIDE_BUSY_ROAD_RULE} ({words})")


@pytest.mark.parametrize("road", [None, 1.0, 2.0, 2.5])
def test_a_path_beside_a_calm_street_or_none_stays_at_1(road):
    assert beside_busy_road_step(PATH, road) is PATH


def test_beside_a_road_at_2_5_only_the_crossings_count():
    """No step for the road itself, but a calm mile of crossings a mile is half a level, up
    to the road's own 2.5: so a lane does not fall from 3 to 1 where its street dips from 3
    to 2.5 (the audit's 17th St NW), and a two-way track with driveways on a collector can
    be 1.5 (the owner's Woodglen Drive)."""
    assert beside_busy_road_step(PATH, 2.5, crossing_ft_per_mile=5000.0) is PATH
    one = beside_busy_road_step(PATH, 2.5, crossing_ft_per_mile=6000.0)
    assert (one.tier, one.half) == (Stress.LTS1, True)
    many = beside_busy_road_step(PATH, 2.5, crossing_ft_per_mile=90000.0)
    assert (many.tier, many.half) == (Stress.LTS2, True)


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


def test_the_rebuild_rates_a_path_from_the_road_beside_it_named_or_not():
    """Beside a road is geometry, not the lack of a name (the audit, 2026-11-13: the lanes
    named "Old Georgetown Road (MDBR 187)", 140 ways and 6.0 mi, were never asked)."""
    ways = [
        (1, {"highway": "primary", "name": "Old Georgetown Road"}, ROAD),
        (2, {"highway": "cycleway"}, _east(ROAD, 10)),
        (3, {"highway": "cycleway", "name": "Old Georgetown Road (MDBR 187)"}, _east(ROAD, -10)),
        (4, {"highway": "cycleway", "name": "15th Street Cycle Track"}, _east(ROAD, 14)),
    ]
    beside = facility.side_streets(ways)
    assert set(beside) == {2, 3, 4}
    assert beside[2].name == "Old Georgetown Road bike lane"
    # A way with a name of its own is rated from the street, never renamed after it.
    assert beside[3].name == "" and beside[3].street == "Old Georgetown Road"
    assert facility.side_street_names(ways) == {2: "Old Georgetown Road bike lane"}
    stress = {1: StressResult(Stress.LTS4, "mixed traffic, 40 mph"), 2: PATH, 3: PATH, 4: PATH}
    assert apply_beside_busy_road(stress, beside) == 3
    for way in (2, 3, 4):
        assert (stress[way].tier, stress[way].half) == (Stress.LTS2, False)


def _north(points, metres):
    return [(lon, lat + metres / 111_000.0) for lon, lat in points]


def test_a_long_named_trail_is_not_a_side_path_where_it_passes_a_road():
    """The W&OD, Capital Crescent, Metropolitan Branch, Mount Vernon, Custis and Anacostia
    trails pass along, over and under roads; a piece beside one is still the trail. A trail
    named for itself is judged over every way of its name."""
    cross = [(-77.1150, 39.0020), (-77.1050, 39.0020)]
    for name in (
        "Washington & Old Dominion Trail",
        "Capital Crescent Trail",
        "Metropolitan Branch Trail",
        "Mount Vernon Trail",
        "Custis Trail",
        "Anacostia River Trail",
    ):
        ways = [
            (1, {"highway": "primary", "name": "Old Georgetown Road"}, ROAD),
            (5, {"highway": "trunk", "name": "Lee Highway"}, cross),
            # 0.28 mi beside the road, then 1.4 mi off on its own line.
            (2, {"highway": "cycleway", "name": name}, _east(ROAD, 12)),
            (3, {"highway": "cycleway", "name": name}, _east(_north(ROAD, 2600), 400)),
            (6, {"highway": "cycleway", "name": name}, _east(_north(ROAD, 5200), 400)),
            # Under the trunk road at a right angle: near it, never beside it.
            (4, {"highway": "cycleway", "name": name}, [(-77.1090, 39.0010), (-77.1090, 39.0030)]),
        ]
        assert facility.side_streets(ways) == {}, name


def test_a_named_path_that_is_a_side_path_from_end_to_end_is_one():
    ways = [
        (1, {"highway": "primary", "name": "Old Georgetown Road"}, ROAD),
        (2, {"highway": "cycleway", "name": "Bethesda Trolley Trail"}, _east(ROAD, 12)),
    ]
    assert set(facility.side_streets(ways)) == {2}


def test_an_unnamed_path_only_near_a_road_is_not_beside_it():
    ways = [
        (1, {"highway": "primary", "name": "Old Georgetown Road"}, ROAD),
        # 130 ft away: past the 66 ft reach.
        (2, {"highway": "cycleway"}, _east(ROAD, 40)),
        # Crossing it at a right angle.
        (3, {"highway": "cycleway"}, [(-77.1105, 39.0020), (-77.1095, 39.0020)]),
    ]
    assert facility.side_streets(ways) == {}


def test_the_names_other_code_reads_are_pinned():
    """PR #1242 (side-path routing price) sets `rm:beside_busy_road` where the rule starts
    with `BESIDE_BUSY_ROAD_RULE` and reads `side_streets[way].metres_by_way` in
    `run.weekend_car_free_beside`. Neither may change without that PR."""
    assert BESIDE_BUSY_ROAD_RULE == "path beside a busy road"
    for kwargs in ({}, {"crossing_ft_per_mile": 30000.0, "contraflow": True, "slip_lane": True}):
        assert beside_busy_road_step(PATH, 4.0, **kwargs).rule.startswith(BESIDE_BUSY_ROAD_RULE)
    assert facility.SideStreet._fields[:2] == ("name", "metres_by_way")
    found = facility.SideStreet("Beach Drive bike lane", {1: 900.0})
    assert found.metres_by_way == {1: 900.0}
    ways = [
        (1, {"highway": "primary", "name": "Old Georgetown Road"}, ROAD),
        (2, {"highway": "cycleway"}, _east(ROAD, 10)),
    ]
    (beside,) = facility.side_streets(ways).values()
    assert set(beside.metres_by_way) == {1} and beside.metres_by_way[1] > 400


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


MILE = 5280.0


def test_a_calm_mile_of_crossings_a_mile_adds_half_a_level():
    busy = beside_busy_road_step(PATH, 4.0, crossing_ft_per_mile=1.2 * MILE)
    assert (busy.tier, busy.half) == (Stress.LTS2, True)
    assert "crossings cost 6336 ft a mile" in busy.rule
    few = beside_busy_road_step(PATH, 4.0, crossing_ft_per_mile=0.4 * MILE)
    assert (few.tier, few.half) == (Stress.LTS2, False)
    # A slip lane is in the cost (1,000 ft), not a half level of its own any more.
    slip = beside_busy_road_step(PATH, 3.0, slip_lane=True)
    assert (slip.tier, slip.half) == (Stress.LTS1, True)
    # Beside a calm street, crossings alone do not step a path.
    assert beside_busy_road_step(PATH, 2.0, crossing_ft_per_mile=9 * MILE) is PATH


def test_the_calibration_matches_the_old_twenty_points_a_mile():
    """Ten LTS 2 side streets a mile were 20 points, half a level; they still are. And 6.7
    unsignalled LTS 3 side streets a mile (also 20 points) come to within 1% of the step."""
    from routemaker.stress import CROSSING_FT_PER_HALF_STEP

    for count, level, highway in ((10, 2.0, "residential"), (20 / 3, 3.0, "secondary")):
        feet = count * facility.crossing_point_ft(level, highway)
        assert CROSSING_FT_PER_HALF_STEP <= feet == pytest.approx(5333.3, abs=0.1)
    # Nine LTS 2 side streets a mile are not yet a step, as before.
    assert 9 * facility.crossing_point_ft(2.0, "residential") < CROSSING_FT_PER_HALF_STEP


def test_a_crossing_point_costs_what_the_junction_model_says():
    from routemaker import intersections

    cost = facility.crossing_point_ft
    # Driveways and quiet streets, which the junction model does not price: its LTS 3
    # figure carried down in proportion, 267 ft a level.
    assert cost(1.5, "service") == 400.0
    assert cost(2.0, "residential") == pytest.approx(533.3, abs=0.1)
    assert cost(2.5, "tertiary") == pytest.approx(533.3, abs=0.1)
    # No signal: the stopped side's crossing, at the path-crossing half.
    assert cost(3.0, "secondary") == intersections.STOPPED_CROSSING_FT[3] / 2 == 800.0
    assert cost(4.0, "primary", speed_mph=35.0) == 2000.0
    # A signal counts: 150 ft across LTS 3, 600 ft across LTS 4.
    assert cost(3.0, "secondary", facility.SIGNAL_NODE) == 150.0
    assert cost(4.0, "primary", facility.SIGNAL_NODE) == 600.0
    # The side street's own stop sign counts: no wait for a gap, the turning conflict stays.
    assert cost(3.0, "secondary", facility.STOP_NODE) == pytest.approx(533.3, abs=0.1)
    assert cost(4.0, "primary", facility.STOP_NODE, 35.0) == pytest.approx(533.3, abs=0.1)
    # A slip lane: the junction model's 1,000 ft, 500 ft at a signal, whatever its level.
    assert cost(4.0, "primary_link") == intersections.SLIP_LANE_FT == 1000.0
    assert cost(4.0, "primary_link", facility.SIGNAL_NODE) == 500.0
    # Never falling as the crossed way gets busier.
    levels = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    costs = [cost(level, "residential") for level in levels]
    assert costs == sorted(costs)


def test_a_path_is_never_rated_above_the_road_beside_it():
    """Our clamp (2026-11-13), for the owner to confirm: the audit's 17th St NW lane was 4.5
    beside a roadway at 3."""
    worst = beside_busy_road_step(PATH, 3.0, crossing_ft_per_mile=50 * MILE)
    assert (worst.tier, worst.half) == (Stress.LTS3, False)
    assert "held at the level of the road beside it" in worst.rule
    half = beside_busy_road_step(PATH, 3.5, crossing_ft_per_mile=50 * MILE)
    assert (half.tier, half.half) == (Stress.LTS3, True)
    # The 4.5 cap stays (the owner: "no upper limit", "nothing is avoid").
    avoid = beside_busy_road_step(PATH, 5.0, crossing_ft_per_mile=50 * MILE)
    assert (avoid.tier, avoid.half) == (Stress.LTS4, True)
    four = beside_busy_road_step(PATH, 4.0, crossing_ft_per_mile=3.5 * MILE)
    assert (four.tier, four.half) == (Stress.LTS3, True)
    assert "held at" not in four.rule


def _line(lat0, n, step_deg=0.0005):
    return [(-77.11, lat0 + i * step_deg) for i in range(n)]


OGR = "path beside Old Georgetown Road"


def _side(*ids, name=OGR, **kwargs):
    return {i: facility.SideStreet(name, {1: 100.0}, **kwargs) for i in ids}


def test_crossings_are_summed_in_feet_over_the_run():
    ways = [
        # Two side-path ways joined at node 103.
        (10, {"highway": "cycleway"}, [100, 101, 102, 103], _line(39.0, 4)),
        (11, {"highway": "cycleway"}, [103, 104, 105, 106], _line(39.0015, 4)),
        # A driveway at 101 (400 ft), a street at 102 rated 3 by the rebuild (800 ft).
        (20, {"highway": "service", "service": "driveway"}, [101, 900], []),
        (21, {"highway": "residential"}, [102, 901], []),
        # A slip lane at 104 (1,000 ft), a tertiary at 105 the rebuild rates 2.5 (533 ft).
        (23, {"highway": "primary_link"}, [104, 903], []),
        (22, {"highway": "tertiary"}, [105, 902], []),
        # A footway at 106 is no crossing.
        (24, {"highway": "footway"}, [106, 904], []),
    ]
    found = facility.side_path_crossings(ways, _side(10, 11), {20: 1.5, 21: 3.0, 22: 2.5}.get)
    miles = facility._length_m(_line(39.0, 7)) / 1609.344
    assert found[10].ft_per_mile == pytest.approx((400 + 800 + 1000 + 533) / miles, rel=0.02)
    assert found[10].ft_per_mile == found[11].ft_per_mile
    assert (found[10].slip_lane, found[11].slip_lane) == (False, True)


def test_a_short_run_reads_no_rate():
    ways = [
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 3, 0.0002)),
        (20, {"highway": "service"}, [101, 900], []),
    ]
    assert facility.side_path_crossings(ways, _side(10))[10].ft_per_mile is None


def test_a_crossing_way_the_rider_rides_is_scored_and_joins_the_run():
    ways = [
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 3)),
        (11, {"highway": "cycleway"}, [200, 201, 202], _line(39.0015, 3)),
        # The crosswalk over a slip lane, its own way, from the end of one to the start of
        # the other.
        (30, {"highway": "footway", "footway": "crossing"}, [102, 300, 200], []),
        (23, {"highway": "primary_link"}, [300, 903], []),
    ]
    found = facility.side_path_crossings(ways, _side(10, 11))
    assert found[10].ft_per_mile == found[11].ft_per_mile > 0
    assert found[10].slip_lane and found[11].slip_lane


def test_the_crosswalk_over_the_paths_own_road_is_not_a_crossing():
    """The audit, 2026-11-13 (I5): a corner crosswalk over the main road starts at the
    path's corner node and was scored as the path crossing its own road; one over an LTS 4
    road added a whole half level to a 0.2 mi path with no real crossing."""
    ways = [
        (1, {"highway": "primary", "name": "Old Georgetown Road"}, [500, 300, 501], []),
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 5)),
        # From the path's end over the main road to the far corner, where the lane on the
        # other side of the same road begins: still not a crossing either lane rides.
        (30, {"highway": "footway", "footway": "crossing"}, [102, 300, 400], []),
        (12, {"highway": "cycleway"}, [400, 401, 402], _line(39.0, 5)),
    ]
    found = facility.side_path_crossings(ways, _side(10, 12), {1: 4.0}.get)
    assert found[10].ft_per_mile == 0.0 and found[12].ft_per_mile == 0.0
    # And the two sides of the road stay two runs.
    ways.append((20, {"highway": "service"}, [101, 900], []))
    found = facility.side_path_crossings(ways, _side(10, 12), {1: 4.0}.get)
    assert found[10].ft_per_mile > 0 and found[12].ft_per_mile == 0.0


def test_a_path_that_ends_by_joining_its_own_road_does_not_cross_it():
    ways = [
        (1, {"highway": "primary", "name": "Old Georgetown Rd"}, [500, 102, 501], []),
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 5)),
    ]
    assert facility.side_path_crossings(ways, _side(10), {1: 4.0}.get)[10].ft_per_mile == 0.0


def test_a_crossing_the_rider_does_not_ride_through_is_not_counted():
    ways = [
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 5)),
        # A crosswalk off the side of the path over a side street, with no side path of
        # this street beyond it.
        (30, {"highway": "footway", "footway": "crossing"}, [101, 300, 301], []),
        (21, {"highway": "secondary", "name": "Cedar Lane"}, [300, 901], []),
        # The street the path stops at: the end of the run, not ridden through.
        (22, {"highway": "secondary", "name": "Beech Avenue"}, [102, 902], []),
    ]
    assert facility.side_path_crossings(ways, _side(10))[10].ft_per_mile == 0.0
    # Carried on beyond the same node, it is ridden through.
    ways.append((11, {"highway": "cycleway"}, [102, 103, 104], _line(39.002, 5)))
    assert facility.side_path_crossings(ways, _side(10, 11))[10].ft_per_mile > 0


def test_a_street_crossed_in_two_halves_over_an_island_is_one_point():
    crossing = {"highway": "footway", "footway": "crossing"}
    ways = [
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 5)),
        (11, {"highway": "cycleway"}, [200, 201, 202], _line(39.003, 5)),
        (30, crossing, [102, 300, 301], []),
        (31, {"highway": "footway", "footway": "traffic_island"}, [301, 302], []),
        (32, crossing, [302, 303, 200], []),
        (21, {"highway": "secondary", "name": "Cedar Lane", "oneway": "yes"}, [300, 901], []),
        (22, {"highway": "secondary", "name": "Cedar Lane", "oneway": "yes"}, [303, 902], []),
    ]
    found = facility.side_path_crossings(ways, _side(10, 11), {21: 3.0, 22: 3.0}.get)
    miles = 2 * facility._length_m(_line(39.0, 5)) / 1609.344
    assert found[10].ft_per_mile == pytest.approx(800 / miles, rel=0.01)


def test_a_signal_or_the_side_streets_stop_sign_lowers_the_point():
    ways = [
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 5)),
        (21, {"highway": "secondary", "name": "Cedar Lane"}, [900, 101, 901], []),
    ]
    miles = facility._length_m(_line(39.0, 5)) / 1609.344

    def feet(control_at):
        found = facility.side_path_crossings(ways, _side(10), {21: 3.0}.get, control_at)
        return round(found[10].ft_per_mile * miles)

    assert feet(None) == 800
    assert feet({101: facility.SIGNAL_NODE}) == 150
    # The signal on the junction node next along the crossed street.
    assert feet({901: facility.SIGNAL_NODE}) == 150
    assert feet({900: facility.STOP_NODE}) == 533
    # A crossing way that says it has a signal.
    ways = [
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 3)),
        (11, {"highway": "cycleway"}, [200, 201, 202], _line(39.001, 3)),
        (
            30,
            {"highway": "cycleway", "cycleway": "crossing", "crossing": "traffic_signals"},
            [102, 300, 200],
            [],
        ),
        (21, {"highway": "primary", "name": "Cedar Lane"}, [300, 901], []),
    ]
    found = facility.side_path_crossings(ways, _side(10, 11), {21: 4.0}.get)
    assert round(found[10].ft_per_mile * miles) == 600
    # A way the rebuild has no level for is read as a quiet street.
    found = facility.side_path_crossings(ways, _side(10, 11))
    assert round(found[10].ft_per_mile * miles) == 150


def test_riding_against_the_traffic_beside_doubles_the_unsignalled_points():
    """Wachtel and Lewiston 1994, Table 4: 4.5 times the risk on the sidewalk against the
    adjacent traffic. `CONTRAFLOW_FACTOR` 2.0 is our default, the low end of the range."""
    ways = [
        (10, {"highway": "cycleway"}, [100, 101, 102, 103], _line(39.0, 6)),
        (20, {"highway": "service"}, [101, 900], []),
        (21, {"highway": "secondary", "name": "Cedar Lane"}, [902, 102, 901], []),
    ]
    level, lit = {20: 1.5}.get, {102: "signal"}
    with_flow = facility.side_path_crossings(ways, _side(10), level, lit)[10]
    against = facility.side_path_crossings(ways, _side(10, contraflow=True), level, lit)[10]
    miles = facility._length_m(_line(39.0, 6)) / 1609.344
    assert round(with_flow.ft_per_mile * miles) == 400 + 150
    # The driveway doubles; the signalised crossing does not.
    assert round(against.ft_per_mile * miles) == 2 * 400 + 150
    assert facility.CONTRAFLOW_FACTOR == 2.0


def test_which_way_a_path_may_be_ridden_beside_its_road():
    """Traffic keeps right: a path east of a northbound-digitised two-way road has
    northbound traffic beside it."""
    road = {"highway": "primary", "name": "Old Georgetown Road"}
    east, west = _east(ROAD, 10), _east(ROAD, -10)

    def contraflow(tags, line, road_tags=road):
        ways = [(1, road_tags, ROAD), (2, {"highway": "cycleway", **tags}, line)]
        return facility.side_streets(ways)[2].contraflow

    # One-way with the lane beside it; against it; and on the other side of the road.
    assert not contraflow({"oneway": "yes"}, east)
    assert contraflow({"oneway": "yes"}, east[::-1])
    assert contraflow({"oneway": "yes"}, west)
    assert not contraflow({"oneway": "yes"}, west[::-1])
    assert not contraflow({"oneway": "-1"}, east[::-1])
    assert contraflow({"oneway:bicycle": "-1", "oneway": "yes"}, east)
    # A two-way path: one of its two directions always is.
    assert contraflow({"oneway": "no"}, east)
    assert contraflow({}, west)
    # Beside a one-way street the side does not matter, the street's direction does.
    one_way = {**road, "oneway": "yes"}
    assert not contraflow({"oneway": "yes"}, west, one_way)
    assert contraflow({"oneway": "yes"}, west[::-1], one_way)
    assert contraflow({"oneway": "yes"}, west, {**road, "oneway": "-1"})


def test_paths_beside_different_streets_are_never_one_run():
    side = {**_side(10), **_side(11, name="path beside Cedar Lane")}
    ways = [
        (10, {"highway": "cycleway"}, [100, 101, 102], _line(39.0, 5)),
        (11, {"highway": "cycleway"}, [102, 201, 202], _line(39.002, 5)),
        (20, {"highway": "service"}, [101, 900], []),
    ]
    found = facility.side_path_crossings(ways, side)
    assert found[10].ft_per_mile > 0
    assert not found[11].ft_per_mile


def test_a_way_with_no_nodes_is_read_as_no_crossings():
    found = facility.side_path_crossings([(10, {"highway": "cycleway"}, (), [])], _side(10))
    assert found[10] == facility.SidePathCrossings(None, False)


def test_the_road_panel_names_bad_crossings_slip_lanes_and_avoid_roads():
    rule = beside_busy_road_step(PATH, 4.0, crossing_ft_per_mile=2.2 * MILE, slip_lane=True).rule
    words = segment_info.rule_words(rule)
    assert "many or busy street and driveway crossings" in words
    assert "crosses a slip lane" in words
    avoid = segment_info.rule_words(beside_busy_road_step(PATH, 5.0).rule)
    assert avoid.startswith("Path beside a busy road (Avoid)")
    # A rule written by the build before this one still reads.
    old = f"{BESIDE_BUSY_ROAD_RULE} (road at LTS 4; crossings score 45 a mile), trail-class way"
    assert "many or busy street and driveway crossings" in segment_info.rule_words(old)


# --- One level for one facility however it is mapped (the audit, 2026-11-13, I7) -----------


def _rated(tier, rule, half=False):
    return StressResult(tier, rule, half=half)


def test_a_track_tagged_on_the_road_goes_through_the_same_rule():
    """`cycleway=track` on the road was a flat LTS 1 at any speed; a separately mapped lane
    beside the same road is 2 or more."""
    road = {
        "highway": "primary",
        "name": "Old Georgetown Road",
        "maxspeed": "40 mph",
        "oneway": "yes",
    }
    track = (1, {**road, "cycleway:right": "track"}, ROAD)
    posts = (2, {**road, "cycleway:right": "lane", "cycleway:right:separation": "flex_post"}, ROAD)
    paint = (3, {**road, "cycleway:right": "lane"}, ROAD)
    tracks = facility.on_road_tracks([track, posts, paint])
    assert set(tracks) == {1, 2}
    assert tracks[1].road_sides == ("right",) and not tracks[1].posts and tracks[2].posts
    assert not tracks[1].contraflow
    assert "cycleway:right" not in facility.without_bike_facility(track[1])
    stress = {
        1: _rated(Stress.LTS1, "separated track alongside"),
        2: _rated(Stress.LTS3, "bike lane, 40 mph"),
    }
    assert apply_beside_busy_road(stress, tracks, None, {1: 4.0, 2: 4.0}) == 2
    assert level_of(stress[1]) == level_of(stress[2]) == 2.0
    assert stress[1].rule.startswith(BESIDE_BUSY_ROAD_RULE)


def test_an_on_road_lane_is_left_alone_without_its_roads_level_or_under_a_row():
    tracks = {1: facility.SideStreet("", {1: 500.0}, "Old Georgetown Road", road_sides=("right",))}
    flat = _rated(Stress.LTS1, "separated track alongside")
    stress = {1: flat}
    assert apply_beside_busy_road(stress, tracks, None, {}) == 0
    # On a calm street a track stays at 1.
    assert apply_beside_busy_road(stress, tracks, None, {1: 2.0}) == 0
    assert stress[1] is flat
    # A lane behind posts is never rated above its painted-lane level.
    posts = {1: tracks[1]._replace(posts=True)}
    stress = {1: _rated(Stress.LTS2, "bike lane, 30 mph")}
    crossings = {1: facility.SidePathCrossings(50 * MILE, False)}
    apply_beside_busy_road(stress, posts, crossings, {1: 4.0})
    assert level_of(stress[1]) == 2.0


def test_a_track_meets_the_side_streets_on_its_own_side_only():
    here = [(-77.11, 39.0 + i * 0.001) for i in range(4)]
    road = {
        "highway": "primary",
        "name": "Old Georgetown Road",
        "oneway": "yes",
        "cycleway:right": "track",
    }
    ways = [
        (1, road, [100, 101, 102, 103], here),
        # A street ending on the east (right) side at 101, one on the west at 102.
        (21, {"highway": "residential"}, [101, 900], [here[1], (-77.109, 39.001)]),
        (22, {"highway": "residential"}, [102, 901], [here[2], (-77.111, 39.002)]),
    ]
    tracks = facility.on_road_tracks([(w[0], w[1], w[3]) for w in ways])
    found = facility.side_path_crossings(ways, tracks)
    miles = facility._length_m(here) / 1609.344
    assert round(found[1].ft_per_mile * miles) == 533
    both = {1: tracks[1]._replace(road_sides=("left", "right"))}
    assert round(facility.side_path_crossings(ways, both)[1].ft_per_mile * miles) == 1067


# --- Sidewalks: a tag that opens one never makes it worse (the audit, I8) -------------------


def test_sidewalk_levels_never_run_backwards_with_the_bicycle_tag():
    """Beside one LTS 4 road a sidewalk was 1 with `bicycle=yes`, 2 or more with
    `designated`, and 4 with no tag. Now yes and designated go through one rule, and neither
    is ever above the untagged sidewalk's last-resort level."""
    from routemaker import sidewalks

    walk = {"highway": "footway", "footway": "sidewalk"}
    ways = [
        (1, {"highway": "primary", "name": "Redland Road"}, ROAD),
        (2, {**walk, "bicycle": "yes"}, _east(ROAD, 10)),
        (3, {**walk, "bicycle": "designated"}, _east(ROAD, -10)),
        (4, walk, _east(ROAD, 14)),
    ]
    beside = facility.side_streets(ways)
    assert set(beside) == {2, 3}
    assert beside[2].sidewalk and beside[3].sidewalk
    # The merely-open sidewalk is rated, not renamed.
    assert beside[2].name == "" and beside[3].name == "sidewalk beside Redland Road"
    for road, untagged in ((2.5, 4), (3.0, 4), (4.0, 4), (4.5, 3), (5.0, 3)):
        assert untagged == (sidewalks.TIER if road >= 4.5 else sidewalks.LAST_RESORT_TIER)
        for cost in (0.0, 2 * MILE, 50 * MILE):
            stress = {1: _rated(Stress(int(road)), "road", half=road % 1 == 0.5), 2: PATH, 3: PATH}
            crossings = {way: facility.SidePathCrossings(cost, False) for way in (2, 3)}
            apply_beside_busy_road(stress, beside, crossings)
            yes, designated = level_of(stress[2]), level_of(stress[3])
            assert 1.0 <= designated == yes <= untagged, (road, cost)


def test_an_owner_row_on_the_street_sets_the_paths_level():
    row = StressAdjustment(
        tier=Stress.LTS3,
        adjustment_id="test-row",
        computed_tier=Stress.LTS4,
        category="other",
        visibility="public",
        annotation_status="approved",
        half=True,
    )
    stress = {
        1: StressResult(Stress.LTS3, "override: stress adjustment test-row", adjustment=row),
        2: PATH,
    }
    apply_beside_busy_road(stress, {2: facility.SideStreet("x bike lane", {1: 100.0})})
    assert (stress[2].tier, stress[2].half) == (Stress.LTS1, True)


# --- Order (v0.26.0 review): the step reads street levels only once they are final ----------


class _Way:
    def __init__(self, osm_id, tags, coordinates, node_ids=()):
        self.osm_id, self.tags, self.coordinates, self.node_ids = (
            osm_id,
            tags,
            coordinates,
            node_ids,
        )


def test_a_road_closed_to_cars_for_good_never_lifts_the_path_beside_it():
    from pipeline.run import car_free_tier_1, rate_side_paths

    road = _Way(1, {"highway": "residential", "name": "Beach Drive", "motor_vehicle": "no"}, ROAD)
    path = _Way(2, {"highway": "cycleway"}, _east(ROAD, 10))
    stress = {1: StressResult(Stress.LTS3, "mixed traffic, 30 mph"), 2: PATH}
    # In the rebuild's order: the car-free correction first, then the side paths.
    assert car_free_tier_1(road, stress)
    side_streets, moved = rate_side_paths([road, path], stress)
    assert set(side_streets) == {2}
    assert moved == 0
    assert stress[2] is PATH


def test_the_rebuild_rates_side_paths_after_the_car_free_and_sidewalk_corrections():
    import inspect

    from pipeline import run

    source = inspect.getsource(run)
    body = source[source.index("    def classify_facilities() -> None:") :]
    body = body[: body.index("\n    def ", 10)]
    step = body.index("rate_side_paths(")
    assert body.index("raise_ridden_sidewalks(") < step
    assert body.index("car_free_tier_1(way, context.stress_by_way)") < step
    overrides = source[source.index("    def apply_overrides() -> None:") :]
    overrides = overrides[: overrides.index("\n    def ", 10)]
    assert "rate_side_paths" not in overrides and "apply_beside_busy_road" not in overrides
