"""The reference routes are the ground truth, so the measurements are asserted
against them rather than against hand-written expectations.

Distance, gain, and turn counts are reproduced exactly from the recorded tables.
Grade is not: see `test_grade_is_regenerated_not_reproduced` for why the recorded
grade column was replaced rather than matched.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from routemaker.geo import (
    EARTH_RADIUS_M,
    METRES_PER_MILE,
    Point,
    bearing,
    bearing_delta,
    cumulative_distances,
    haversine,
)
from routemaker.gpx import read_track_points
from routemaker.measure import (
    DEGREE_OF_LATITUDE_M,
    GRADE_MIN_RUN_M,
    REVISIT_ALONG_ROUTE_M,
    REVISIT_CELL_LON_MARGIN,
    REVISIT_PROXIMITY_M,
    TURN_MIN_BEARING_DEG,
    RouteStats,
    revisit_cell_degrees,
    revisits,
    turns,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "reference-routes"

# Recorded in fixtures/reference-routes/README.md. Distance in miles, gain in feet.
RECORDED = {
    "2025-05-dcbp-btr": (5.08, 63, 14),
    "2025-12-dcbp": (6.17, 113, 18),
    "2026-04-dcbp": (7.23, 133, 17),
    "2026-07-dcbp": (6.00, 164, 28),
    "group-blow-off-steam": (11.65, 661, 30),
    "group-crit-mass-2024-03": (12.31, 347, 34),
    "group-crit-mass-feb": (14.50, 511, 47),
    "group-crit-mass-jan": (13.77, 604, 33),
    "group-purple-line": (35.25, 985, 118),
    # 2361, not 2360: the measurement is 2360.89 ft and the README's table has
    # always said 2361. The one-foot disagreement was inside this file's own
    # `abs=1` tolerance, so neither number was wrong enough to fail and the two
    # sat there disagreeing. The README is the recorded table, so the README wins.
    "rural-group-loco-30": (30.12, 2361, None),  # sampled too densely to count turns
    "rural-group-tnl": (24.32, 2219, 26),
    "rural-group-two-bridges": (30.11, 2232, 30),
    "trail-annapolis-bwi": (75.73, 2333, 177),
    "trail-bethesda-loop": (31.63, 701, 92),
    "trail-brookside-gardens": (14.65, 746, 42),
}


def stats_for(name: str) -> RouteStats:
    return RouteStats.measure(read_track_points(FIXTURES / f"{name}.gpx"))


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_distance_matches_recorded(name: str) -> None:
    assert stats_for(name).distance_mi == pytest.approx(RECORDED[name][0], abs=0.005)


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_gain_matches_recorded(name: str) -> None:
    """The hysteresis is asymmetric: threshold on the way up, running minimum on
    the way down. A symmetric threshold under-reports every route in the set."""
    assert round(stats_for(name).gain_ft) == pytest.approx(RECORDED[name][1], abs=1)


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_turns_match_recorded_where_sampling_permits(name: str) -> None:
    expected = RECORDED[name][2]
    stats = stats_for(name)
    if expected is None:
        assert not stats.turns_reliable, "trace is now coarse enough to count turns"
        return
    assert stats.turns_reliable
    assert stats.turns == expected


# The max-grade column of the README's tables, per file, as `measure.max_grade`
# produces it. Two decimals against a table printed to one, so the pin is
# tighter than the rounding it has to agree with.
RECORDED_GRADE_PCT = {
    "2025-05-dcbp-btr": 6.24,
    "2025-12-dcbp": 6.30,
    "2026-04-dcbp": 4.41,
    "2026-07-dcbp": 4.79,
    "group-blow-off-steam": 10.89,
    "group-crit-mass-2024-03": 9.92,
    "group-crit-mass-feb": 8.50,
    "group-crit-mass-jan": 8.62,
    "group-purple-line": 10.35,
    "rural-group-loco-30": 16.91,
    "rural-group-tnl": 14.51,
    "rural-group-two-bridges": 18.99,
    "trail-annapolis-bwi": 11.29,
    "trail-bethesda-loop": 11.81,
    "trail-brookside-gardens": 8.34,
}

# The two directions of one loop. The README says so on other grounds - the
# bounding boxes and the start points coincide - and it is what makes the pair
# a check on the grade column rather than two more numbers in it.
SAME_LOOP_BOTH_WAYS = ("rural-group-loco-30", "rural-group-two-bridges")


def test_grade_is_regenerated_not_reproduced() -> None:
    """Why the recorded max-grade column is asserted differently from the rest.

    Distance, gain and turns above are reproduced from the tables the routes
    arrived with: the definition was recovered until the code agreed with the
    supplied numbers, and a disagreement there is a defect in the code. The
    grade column is not that. The supplied column could not be reproduced by any
    formulation of the measurement and was internally implausible - it recorded
    4.7 percent as the steepest pitch on a Loudoun loop that climbs 78 feet per
    mile, while recording 19.0 on the *same loop ridden the other way round*.
    Two directions of one loop cross the same hills, so the two figures are
    measurements of the same terrain and cannot be four times apart. So the
    column was regenerated from `measure.max_grade` rather than matched, and the
    README marks it provisional for a second reason as well: these files carry
    the GPX elevation they were recorded with, while the application derives
    elevation from 3DEP.

    What this test pins is therefore the regenerated column itself, per file,
    and the internal consistency that the supplied one failed. Without it the
    measurement had no test at all: `max_grade` is what PLAN's 6 percent Mass
    Ride grade cap is argued from - the four mass rides brief 4.4 to 6.3 percent
    pitches - and dropping the anchor advance from its loop moves every one of
    those figures to between 1.4 and 2.0, which would argue for a cap a third
    of the size against the same real routes.
    """
    measured = {name: stats_for(name).max_grade_pct for name in RECORDED_GRADE_PCT}

    ccw, cw = (measured[name] for name in SAME_LOOP_BOTH_WAYS)
    assert abs(ccw - cw) < 3.0, (
        "the same loop ridden both ways reports grades two points apart, not four times apart"
    )

    # And the mass rides, which are the evidence for the cap: brief pitches to
    # around 6 percent, and nothing that would let a lower cap through.
    mass_rides = [measured[name] for name in RECORDED_GRADE_PCT if name.endswith("dcbp")]
    mass_rides.append(measured["2025-05-dcbp-btr"])
    assert max(mass_rides) == pytest.approx(6.30, abs=0.01)
    assert min(mass_rides) == pytest.approx(4.41, abs=0.01)


@pytest.mark.parametrize("name", sorted(RECORDED_GRADE_PCT))
def test_max_grade_matches_the_regenerated_column(name: str) -> None:
    """Per file, because a single aggregate cannot say which route moved.

    The tolerance is a hundredth of a percentage point against a README printed
    to a tenth: the column is deterministic output of deterministic code over a
    checked-in file, so there is nothing here for a loose tolerance to absorb.
    """
    stats = stats_for(name)
    assert stats.max_grade_pct == pytest.approx(RECORDED_GRADE_PCT[name], abs=0.01)
    # And the README's own table, to the tenth it prints, so the pin above and
    # the document that quotes it cannot drift apart the way the distance and
    # gain columns once did.
    readme = (FIXTURES / "README.md").read_text()
    assert f"{stats.max_grade_pct:.1f}%" in readme, f"{name} is not the README's figure"


def test_the_minimum_run_is_thirty_metres() -> None:
    """Flat, because it is the whole of the definition and moves every figure in
    the column: at ten metres the Bethesda loop reports 12.3 percent against
    11.8, the Loudoun loop 52 against 16.9, and a one-metre elevation wobble
    between two adjacent samples starts reporting a 40 percent pitch."""
    assert GRADE_MIN_RUN_M == 30.0


def test_dense_trace_is_flagged_rather_than_silently_miscounted() -> None:
    """The one trace sampled at 6.4 m under-counts turns by roughly two thirds,
    because a turn taken over 15 m splits into three sub-threshold steps. The
    measurement reports that it cannot be trusted instead of returning the number."""
    stats = stats_for("rural-group-loco-30")
    assert stats.mean_spacing_m < 20.0
    assert not stats.turns_reliable
    assert stats.turns_per_mile < 0.5  # against ~1.0 for its two sibling rural loops


def test_a_bearing_change_exactly_at_the_threshold_is_not_a_turn() -> None:
    """The tie in `turns`, on the boundary rather than beside it.

    The comparison is `>`, so a corner of exactly `TURN_MIN_BEARING_DEG` is not
    counted. Nothing pinned it: the reference traces carry no corner within a
    degree of 40, so `>=` reproduced all fifteen recorded counts, and turn
    density is the measure the README's four-set comparison rests on and the one
    PLAN's mass-ride invariant is drawn against.

    Taken against the corner's own measured delta rather than against a
    coordinate pair chosen to land on 40.000, which the sphere's convergence
    will not do exactly: it is the same tie either way.
    """
    corner = [
        Point(-77.0, 38.9000),
        Point(-77.0, 38.9010),
        Point(-76.99923, 38.90192),
    ]
    delta = bearing_delta(bearing(corner[0], corner[1]), bearing(corner[1], corner[2]))
    assert 30.0 < delta < 50.0, "a corner in the range the threshold lives in"
    assert turns(corner, min_bearing_deg=delta) == 0
    assert turns(corner, min_bearing_deg=math.nextafter(delta, 0.0)) == 1
    assert TURN_MIN_BEARING_DEG == 40.0


def test_mass_rides_never_revisit_their_own_line() -> None:
    """The empirical basis for the self-crossing check, which belongs to Mass Ride
    alone: two of the five city group rides do revisit, so applying it wider would
    reject real routes."""
    for name in ("2025-05-dcbp-btr", "2025-12-dcbp", "2026-04-dcbp", "2026-07-dcbp"):
        assert stats_for(name).revisits == 0


# --- The revisit index ------------------------------------------------------
#
# `revisits` buckets points into a lat/lon grid and compares only the nine
# neighbouring cells, which is only a correct shortcut while a cell is at least
# `proximity_m` across on *both* axes. It was not: both axes were divided by
# 111,320 m, the length of a degree of latitude, so every cell was
# cos(38.9 deg) = 0.78 of `proximity_m` wide in ground distance and a pair on an
# east-west offset could sit two cells apart in x and never be compared. A
# parallel street a block over is what a revisit on a city grid looks like.

REVISIT_OFFSET_M = 22.5  # inside the 25 m proximity radius, outside a 0.78 cell
REVISIT_LEG_M = 500.0
REVISIT_SPACING_M = 25.0
DC_LAT = 38.9


def parallel_offset_route(base_lon: float, offset_m: float = REVISIT_OFFSET_M) -> list[Point]:
    """An out-and-back whose return leg is `offset_m` east of its outbound.

    At the default it is one revisit by the definition: the two legs run 22.5 m
    apart, which is inside the 25 m proximity radius, and the ends of the route
    are 1000 m apart along it, which is outside the 400 m along-route minimum.
    The separation is a parameter so the radius itself can be stated in metres
    rather than only as a fraction of the constant under test.
    """
    degrees_per_m_lat = 1.0 / 111_320.0
    degrees_per_m_lon = degrees_per_m_lat / math.cos(math.radians(DC_LAT))
    offset = offset_m * degrees_per_m_lon
    step = REVISIT_SPACING_M * degrees_per_m_lat
    count = int(REVISIT_LEG_M / REVISIT_SPACING_M) + 1

    north = [Point(base_lon, DC_LAT + i * step) for i in range(count)]
    south = [Point(base_lon + offset, DC_LAT + i * step) for i in reversed(range(count))]
    return north + south


@pytest.mark.parametrize("sample", range(20))
def test_a_parallel_return_leg_inside_the_radius_is_a_revisit(sample: int) -> None:
    """The case the square cell lost, swept across one cell width of alignment.

    Whether the square-cell index found this pair at all depended on where the
    route happened to fall against the grid's origin: a 22.5 m east-west offset
    is 1.16 old cells, so for roughly a sixth of base longitudes the two legs
    landed two cells apart in x and the nine-cell scan never compared them. The
    sweep is what makes that a test rather than a coin flip - the measurement
    may not depend on where in the world the route is.
    """
    cell = REVISIT_PROXIMITY_M / 111_320.0
    base_lon = -77.0 + sample * cell / 20.0
    assert revisits(parallel_offset_route(base_lon)) == 1


def test_the_proximity_radius_is_twenty_five_metres() -> None:
    """Flat, and then stated in metres rather than in itself.

    Every other case in this section reaches the radius through
    `REVISIT_PROXIMITY_M`: the offsets are written as fractions of it, the cell
    width is measured against it, and the brute-force definition takes it as a
    default. So the whole section moves with the constant and none of it says
    what the constant is - it would pass unchanged at 25 m, at 30 m, or at 100.

    The figure is the definition of a revisit, and a revisit is what Mass Ride
    refuses a route for. The District's blocks put parallel one-way pairs about
    27 m apart, so a route out on one and back on the other is two streets, not
    a route meeting its own line; at 30 m it becomes a revisit and an ordinary
    out-and-back through the grid is rejected for a crowding hazard that is not
    there.
    """
    assert REVISIT_PROXIMITY_M == 25.0

    a_block_over = parallel_offset_route(-77.0, offset_m=27.0)
    assert revisits(a_block_over) == 0, "27 m apart is a parallel street, not a revisit"
    assert revisits(a_block_over, proximity_m=30.0) == 1, "and the radius is what decides it"


def brute_force_revisits(
    points: list[Point],
    proximity_m: float = REVISIT_PROXIMITY_M,
    along_route_m: float = REVISIT_ALONG_ROUTE_M,
) -> int:
    """The definition, written out pairwise, with no index in it at all.

    This is what the grid is an optimisation of, so it is the only thing that
    can say whether the optimisation is one.
    """
    cum = cumulative_distances(points)
    flagged = [False] * len(points)
    for i, p in enumerate(points):
        for j in range(i + 1, len(points)):
            if cum[j] - cum[i] <= along_route_m:
                continue
            if haversine(p, points[j]) < proximity_m:
                flagged[i] = flagged[j] = True
    occurrences, previous = 0, False
    for now in flagged:
        if now and not previous:
            occurrences += 1
        previous = now
    return occurrences // 2


# `rural-group-loco-30` is excluded by its point count, not by its answer: at
# 7,538 points the pairwise form is 28 million haversines and runs for half a
# minute, which is not a price this suite pays on every run. The other fourteen
# cover 127 to 2,240 points and every revisit count the set contains.
BRUTE_FORCE_ROUTES = sorted(name for name in RECORDED if name != "rural-group-loco-30")


@pytest.mark.parametrize("name", BRUTE_FORCE_ROUTES)
def test_the_grid_index_agrees_with_the_pairwise_definition(name: str) -> None:
    """Every reference route, indexed and unindexed, on the real geometry.

    The synthetic case above pins the one failure a reviewer measured; this pins
    that the index has no others on any route this project has. A cell size that
    is wrong on either axis shows up here as a route whose count drops."""
    points = read_track_points(FIXTURES / f"{name}.gpx")
    assert revisits(points) == brute_force_revisits(points)


# --- The cell margin, at the coverage box's latitude extremes ----------------
#
# The square cell was the large failure; this is the small one it left behind.
# The cosine used to be the route's *mean* latitude's, so on a route spanning
# the region the cell at the northern end was narrower in ground distance than
# the mean said, and the 111,320 m the latitude axis divided by is 125 m more
# than `haversine`'s sphere gives a degree. Both shaved the longitude cell under
# `REVISIT_PROXIMITY_M`, which is the one thing the nine-cell scan needs to be a
# shortcut rather than a different measurement. The cell is now sized from the
# route's smallest cosine and the sphere's own degree; these cases are what say
# so, and they fail against either of the two figures it replaced.

COVERAGE_LAT_SOUTH = 38.2  # settings.COVERAGE_BBOX, the region this deployment clips to
COVERAGE_LAT_NORTH = 39.5
NEAR_RADIUS_OFFSET_M = 24.93  # inside the 25 m radius, and outside an unpadded cell

# Imported rather than restated: the grid divides by this and so does every
# route built here, so a test that carried its own copy would go on passing if
# the two stopped agreeing - which is half of what this section is about.
assert DEGREE_OF_LATITUDE_M == math.pi * EARTH_RADIUS_M / 180.0


def region_spanning_revisit_route(base_lon: float) -> list[Point]:
    """A route from the south of the coverage box to the north, with its one
    revisit at the northern extreme.

    The long stem is what puts the route's mean latitude in the middle of the
    region while the pair that has to be found sits at its edge - which is the
    whole of the case, and is why a short out-and-back like
    `parallel_offset_route` cannot show it: over 500 m the mean latitude and the
    local one are the same number.

    The revisit itself is the same shape as that one: a 500 m leg north and a
    500 m leg back `NEAR_RADIUS_OFFSET_M` to the east, so the two legs are inside
    the proximity radius and their ends are outside the along-route minimum.
    """
    east = NEAR_RADIUS_OFFSET_M / DEGREE_OF_LATITUDE_M / math.cos(math.radians(COVERAGE_LAT_NORTH))
    span = COVERAGE_LAT_NORTH - COVERAGE_LAT_SOUTH
    stem_points = 289  # the region's 1.3 degrees at roughly 500 m spacing
    top = COVERAGE_LAT_NORTH

    points = [
        Point(base_lon, COVERAGE_LAT_SOUTH + span * i / (stem_points - 1))
        for i in range(stem_points)
    ]
    step = REVISIT_SPACING_M / DEGREE_OF_LATITUDE_M
    count = int(REVISIT_LEG_M / REVISIT_SPACING_M) + 1
    points += [Point(base_lon, top + i * step) for i in range(1, count)]
    points += [Point(base_lon + east, top + i * step) for i in reversed(range(count))]
    return points


def test_the_pair_is_inside_the_radius_and_the_route_spans_the_region() -> None:
    """The premises of the case below, stated separately so a failure there says
    which half moved."""
    points = region_spanning_revisit_route(-77.0)
    outbound = next(p for p in points if p.lat > COVERAGE_LAT_NORTH)
    returning = next(p for p in reversed(points) if p.lat == outbound.lat)
    assert haversine(outbound, returning) == pytest.approx(NEAR_RADIUS_OFFSET_M, abs=0.01)
    assert haversine(outbound, returning) < REVISIT_PROXIMITY_M, "it is a revisit by the definition"
    mean_lat = sum(p.lat for p in points) / len(points)
    assert COVERAGE_LAT_NORTH - mean_lat > 0.5, "the pair is at the edge and the mean is not"


def test_a_pair_just_inside_the_radius_is_found_at_the_regions_northern_edge() -> None:
    """The alignment is chosen rather than swept, because this failure is small.

    The square cell missed roughly a sixth of alignments, which a twenty-sample
    sweep catches every time. What is left over is under one percent of a cell,
    so a sweep would find it only by luck: the west leg is placed a hair inside
    the top of a cell computed the way the unpadded index computed it, which is
    the alignment - and the only alignment - at which a pair 1.006 cells apart
    lands two cells apart. With the margin the pair is 0.996 cells apart and no
    alignment can do it.
    """
    unpadded_cell_lon = (REVISIT_PROXIMITY_M / 111_320.0) / math.cos(
        math.radians(
            sum(p.lat for p in region_spanning_revisit_route(-77.0))
            / len(region_spanning_revisit_route(-77.0))
        )
    )
    boundary = (math.floor(-77.0 / unpadded_cell_lon) + 1) * unpadded_cell_lon
    points = region_spanning_revisit_route(boundary - 1e-12)

    assert revisits(points) == 1
    assert revisits(points) == brute_force_revisits(points)


# --- The cell margin against a route whose bulk is in the south -------------
#
# The case above spans the region evenly, so its mean latitude sits near the
# middle of it. A real route need not: a ride around one town with a long spur
# north puts almost all of its points at one end and pulls the mean most of the
# way there, and the cosine the cell was sized from is then a southern one while
# the pair that has to be found is at the northern extreme. That is the shape
# the reviewer measured, and the shape that says why the cosine has to be the
# route's minimum rather than its mean: the mean is not a property of where the
# points are that have to be compared.

BULK_LAT = 38.2  # the southern end of the coverage box, where the ride is
BULK_POINTS = 600  # 15 km of it at the 25 m spacing these traces carry
STEM_POINTS = 289  # the spur north, at roughly 500 m


def bulk_south_revisit_route(base_lon: float) -> list[Point]:
    """A ride at the bottom of the coverage box with a spur to the top of it.

    600 points running east along 38.2 N, a spur north to 39.5 N, and the same
    500 m out-and-back at the top that `region_spanning_revisit_route` uses, its
    two legs `NEAR_RADIUS_OFFSET_M` apart and so inside the proximity radius.
    Nothing but the northernmost 81 points is anywhere near the pair; the rest
    is what the mean latitude is made of.
    """
    step = REVISIT_SPACING_M / DEGREE_OF_LATITUDE_M
    east_step = step / math.cos(math.radians(BULK_LAT))
    points = [Point(base_lon + i * east_step, BULK_LAT) for i in range(BULK_POINTS)]

    lon = base_lon + (BULK_POINTS - 1) * east_step
    span = COVERAGE_LAT_NORTH - BULK_LAT
    points += [Point(lon, BULK_LAT + span * i / (STEM_POINTS - 1)) for i in range(1, STEM_POINTS)]

    count = int(REVISIT_LEG_M / REVISIT_SPACING_M) + 1
    east = NEAR_RADIUS_OFFSET_M / DEGREE_OF_LATITUDE_M / math.cos(math.radians(COVERAGE_LAT_NORTH))
    points += [Point(lon, COVERAGE_LAT_NORTH + i * step) for i in range(1, count)]
    points += [Point(lon + east, COVERAGE_LAT_NORTH + i * step) for i in reversed(range(count))]
    return points


def test_the_bulk_south_routes_mean_latitude_is_nowhere_near_its_revisit() -> None:
    """The premise, stated separately so a failure below says which half moved.

    The mean sits within half a degree of the southern end while the pair to be
    found is at the northern one, and the pair is inside the radius by the
    definition.
    """
    points = bulk_south_revisit_route(-77.0)
    mean_lat = sum(p.lat for p in points) / len(points)
    assert mean_lat - BULK_LAT < 0.5
    assert COVERAGE_LAT_NORTH - mean_lat > 1.0

    outbound = next(p for p in points if p.lat > COVERAGE_LAT_NORTH)
    returning = next(p for p in reversed(points) if p.lat == outbound.lat)
    assert haversine(outbound, returning) == pytest.approx(NEAR_RADIUS_OFFSET_M, abs=0.01)
    assert haversine(outbound, returning) < REVISIT_PROXIMITY_M


def test_a_pair_at_the_top_of_a_bulk_south_route_is_found() -> None:
    """The alignment is chosen rather than swept, as above and for the reason
    above: on this route the failure is three tenths of a percent of a cell
    wide, so a sweep would find it only by luck.

    The west leg is placed a hair inside the top of a cell computed the way the
    mean-cosine index computed it - the one alignment at which a pair 1.003 of
    those cells apart lands two cells apart and is never compared. Sized from
    the route's minimum cosine and the sphere's own degree instead, the cell is
    25.25 m across in ground distance everywhere on the route and no alignment
    can do it.
    """
    probe = bulk_south_revisit_route(-77.0)
    mean_cosine_cell = (
        REVISIT_CELL_LON_MARGIN * REVISIT_PROXIMITY_M / DEGREE_OF_LATITUDE_M
    ) / math.cos(math.radians(sum(p.lat for p in probe) / len(probe)))
    offset = (
        (BULK_POINTS - 1)
        * REVISIT_SPACING_M
        / DEGREE_OF_LATITUDE_M
        / math.cos(math.radians(BULK_LAT))
    )
    boundary = (math.floor(-77.0 / mean_cosine_cell) + 1) * mean_cosine_cell
    points = bulk_south_revisit_route(boundary - 1e-12 - offset)

    assert revisits(points) == 1
    assert revisits(points) == brute_force_revisits(points)


@pytest.mark.parametrize(
    "points",
    [
        pytest.param(bulk_south_revisit_route(-77.0), id="bulk-south"),
        pytest.param(region_spanning_revisit_route(-77.0), id="region-spanning"),
        pytest.param(parallel_offset_route(-77.0), id="one-block"),
    ],
)
def test_the_cell_is_at_least_the_radius_across_at_every_latitude_on_the_route(points) -> None:
    """The property the nine-cell scan is a correct shortcut under, measured on
    the cell itself rather than inferred from a route that exposes it.

    A cell has to be at least `REVISIT_PROXIMITY_M` across in ground distance
    everywhere the route goes, and the margin has to be *left over* at the
    binding point rather than spent reaching it. Both axes are checked, because
    both were divided by a figure 125 m too large: the latitude axis directly,
    and the longitude axis through it.

    A route is the wrong instrument for this. Whether a pair lands two cells
    apart depends on where the route falls against the grid's origin, so a cell
    a whole percent too narrow shows up only at some alignments and a cell a
    tenth of a percent too narrow shows up at none - the margin absorbs it,
    correctly, and the absorbed tenth is then not available for anything else.
    That is how the two errors this replaces stacked.
    """
    cell_lat, cell_lon = revisit_cell_degrees(points, REVISIT_PROXIMITY_M)

    assert cell_lat * DEGREE_OF_LATITUDE_M == pytest.approx(REVISIT_PROXIMITY_M, abs=1e-6)

    widths = [
        cell_lon * DEGREE_OF_LATITUDE_M * math.cos(math.radians(point.lat))
        for point in (min(points, key=lambda p: p.lat), max(points, key=lambda p: p.lat))
    ]
    assert min(widths) >= REVISIT_PROXIMITY_M
    assert min(widths) == pytest.approx(REVISIT_CELL_LON_MARGIN * REVISIT_PROXIMITY_M, abs=0.01)


# --- The Purple Line's jurisdiction sequence --------------------------------
#
# The District's boundary is a ten-mile square laid out in 1791 and marked by
# four cornerstones, and all four of this route's District-line crossings are on
# the two Maryland sides of it. The square is a matter of record and needs no
# layer to reproduce, which is why the measurement is made here against these
# four points rather than against the jurisdiction polygons - those live in
# PostGIS and this file must run without a database.
#
# The retrocession of 1846 gave the Virginia third back, so the real boundary
# leaves the square along the Potomac. That does not touch this route: it stays
# north and east of the river throughout, and the sides it crosses are the ones
# the square and the boundary still share.
DC_CORNERSTONES = (
    (38.995548, -77.041931),  # north
    (38.893557, -76.909399),  # east
    (38.791636, -77.039154),  # south
    (38.893557, -77.119759),  # west
)

# Where the Montgomery / Prince George's line reaches the District boundary,
# as a band rather than a point. It meets Eastern Avenue somewhere in the
# Takoma-Chillum stretch; the exact spot is not something this repository can
# check with Overpass blocked, and it does not have to, because the route's two
# ends of its first excursion sit either side of the whole band. Community
# knowledge, medium confidence, and stated as the interval it is.
MONTGOMERY_PG_TRIPOINT_LON = (-77.02, -76.99)


def inside_dc(lat: float, lon: float) -> bool:
    """Ray casting against the 1791 square. Four vertices, no dependencies."""
    inside = False
    previous = len(DC_CORNERSTONES) - 1
    for current, (lat_c, lon_c) in enumerate(DC_CORNERSTONES):
        lat_p, lon_p = DC_CORNERSTONES[previous]
        if (lon_c > lon) != (lon_p > lon):
            edge_lat = (lon - lon_c) * (lat_p - lat_c) / (lon_p - lon_c) + lat_c
            if lat < edge_lat:
                inside = not inside
        previous = current
    return inside


def district_line_crossings(points: list[Point]) -> list[tuple[str, float, Point]]:
    """Every transition across the District line: direction, mile, and where."""
    cum = cumulative_distances(points)
    out: list[tuple[str, float, Point]] = []
    was_inside = inside_dc(points[0].lat, points[0].lon)
    for index, point in enumerate(points[1:], 1):
        now_inside = inside_dc(point.lat, point.lon)
        if now_inside != was_inside:
            out.append(("enter" if now_inside else "leave", cum[index] / METRES_PER_MILE, point))
            was_inside = now_inside
    return out


class TestThePurpleLineJurisdictionSequence:
    """The one reference route that leaves the District, measured rather than recalled.

    It has been recorded three ways and each was wrong in a different place: as
    staying inside the District, then as crossing "twice, out and back", then as
    four crossings into two counties with the re-entry at 18.90 attributed to
    Prince George's. The count is right at four; the attribution was not. The
    re-entry is on Eastern Avenue at Silver Spring, which is Montgomery County,
    so the route runs DC, Prince George's, Montgomery, DC, Montgomery, DC -
    **five** jurisdiction transitions, including one handover from Prince
    George's to Montgomery that happens entirely inside Maryland and crosses no
    District line at all.

    That last transition is the reason the two counts differ, and it is the one
    a permit application cares about: a ride that is in Prince George's when it
    leaves the District and in Montgomery when it returns has been in both, and
    a report that names the county it left into for the whole excursion names
    the wrong agency for half of it.
    """

    EXPECTED = [("leave", 8.84), ("enter", 18.89), ("leave", 20.25), ("enter", 28.16)]

    def points(self) -> list[Point]:
        return read_track_points(FIXTURES / "group-purple-line.gpx")

    def test_the_route_starts_and_ends_inside_the_district(self) -> None:
        points = self.points()
        assert inside_dc(points[0].lat, points[0].lon)
        assert inside_dc(points[-1].lat, points[-1].lon)

    def test_it_crosses_the_district_line_four_times(self) -> None:
        """Four, in this order, at these mileages. The mileages are measured
        against the 1791 square above and are pinned so the README's table and
        this measurement cannot drift apart again - the README carried 18.90 and
        20.20 against 18.89 and 20.25 here."""
        crossings = district_line_crossings(self.points())
        assert [direction for direction, _mile, _point in crossings] == [
            direction for direction, _mile in self.EXPECTED
        ]
        for (_direction, mile, _point), (_expected_direction, expected) in zip(
            crossings, self.EXPECTED, strict=True
        ):
            assert mile == pytest.approx(expected, abs=0.01)

    def test_the_first_excursion_leaves_into_one_county_and_returns_from_another(self) -> None:
        """Which is the whole of the five-transition claim.

        The Maryland side of the District's northeast boundary is Prince
        George's County from the east cornerstone up to where the county line
        meets Eastern Avenue, and Montgomery County from there to the north
        cornerstone. This route leaves at longitude -76.94, out past Cheverly,
        and returns at -77.03, in Silver Spring - one either side of the band
        the county line can be in, so the two ends are in different counties
        however the band is drawn, and the route handed over between them
        somewhere in Maryland.
        """
        leave, enter = district_line_crossings(self.points())[:2]
        westmost, eastmost = MONTGOMERY_PG_TRIPOINT_LON
        assert leave[2].lon > eastmost, "the exit is not unambiguously in Prince George's"
        assert enter[2].lon < westmost, "the re-entry is not unambiguously in Montgomery"

    def test_the_second_excursion_leaves_and_returns_in_montgomery(self) -> None:
        """The other side of the square: both ends are west of the north
        cornerstone's longitude, where the District's Maryland neighbour is
        Montgomery County along the whole side."""
        north_lon = DC_CORNERSTONES[0][1]
        for _direction, _mile, point in district_line_crossings(self.points())[2:]:
            assert point.lon < north_lon

    def test_five_transitions_not_four(self) -> None:
        """Stated as the number, because it is the number PLAN and the README
        carry and the one an organizer counts permits against."""
        crossings = district_line_crossings(self.points())
        leave, enter = crossings[0], crossings[1]
        counties_differ = leave[2].lon > MONTGOMERY_PG_TRIPOINT_LON[1] and (
            enter[2].lon < MONTGOMERY_PG_TRIPOINT_LON[0]
        )
        assert len(crossings) + (1 if counties_differ else 0) == 5
