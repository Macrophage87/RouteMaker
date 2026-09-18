"""Normative route measurements.

These are the definitions the fixtures README states and every per-modality
invariant in the Quality bar uses. They are pinned here rather than in a
one-off script so that the number a test asserts and the number the application
reports come from the same code.

Turn counts here are *geometric*. They are deliberately not the same quantity as
a routing engine's maneuver count, which suppresses maneuvers where the road
name continues and splits others. Any comparison between the two must compute
both sides the same way; see the Quality bar.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .geo import (
    EARTH_RADIUS_M,
    METRES_PER_FOOT,
    METRES_PER_MILE,
    Point,
    bearing,
    bearing_delta,
    cumulative_distances,
    haversine,
)

# Normative constants. Changing one changes what every invariant means, so they
# live here and the README quotes them rather than the other way round.
GAIN_HYSTERESIS_M = 3.0
TURN_MIN_SEGMENT_M = 5.0
TURN_MIN_BEARING_DEG = 40.0
REVISIT_PROXIMITY_M = 25.0
REVISIT_ALONG_ROUTE_M = 400.0
GRADE_MIN_RUN_M = 30.0

# Metres in a degree of latitude on `haversine`'s own sphere, which is the only
# sphere any distance in this module is measured on. The 111,320 m figure the
# grid used instead is 125 m more than this one gives, so every cell computed
# from it was 0.1 percent narrower in ground distance than it claimed - a
# shortfall on the axis that had no room for one.
DEGREE_OF_LATITUDE_M = math.pi * EARTH_RADIUS_M / 180.0

# A margin on the *longitude* axis of `revisits`' grid, and on that axis only.
#
# Not normative: it changes no definition, only how wide the index's cells are.
# The nine-cell scan is a correct shortcut for the pairwise definition exactly
# while a cell is at least `REVISIT_PROXIMITY_M` across in ground distance on
# both axes, and nothing in the cell size may be allowed to shave the longitude
# axis below that. Two approximations did. The cosine was the route's *mean*
# latitude's, so at the north end of a region-spanning route the local one is
# smaller and the cell there is narrower in ground distance than the mean says;
# and the degree of latitude was 111,320 m rather than the sphere's own
# `DEGREE_OF_LATITUDE_M`, which narrows both axes by a further 0.1 percent.
# Together they put a pair 24.93 m apart - inside the 25 m radius, and running
# purely east-west, which is the hardest case because a parallel street a block
# over is exactly that - marginally over one cell width apart at the northern
# edge of the coverage box, so it could land two cells apart and never be
# compared. That is the square-cell failure again, an order of magnitude
# smaller, and it is measurable: on a route whose bulk lies at 38.2 N with a
# stem to 39.5 N, a few tenths of a percent of east-west alignments lost the
# pair.
#
# Both are now fixed in the cell size itself rather than paid for out of the
# margin: the cosine is the route's smallest, so the cell is sized for the
# narrowest ground width anywhere on it, and the degree is the sphere's. What
# the margin is left covering is the ordinary floating-point edge, at a cost of
# a handful of extra haversines per cell. The brute-force equivalence test over
# every reference route is what says it is enough.
REVISIT_CELL_LON_MARGIN = 1.01

# Below this sample spacing the turn definition stops being reliable: a turn taken
# over fifteen metres splits into three sub-threshold steps and is not counted.
# Measured on the reference set, where the one trace sampled at 6.4 m reports a
# third of its true turn density while the other fourteen, sampled at 39 m and
# above, reproduce their recorded counts exactly.
TURN_MIN_TRACE_SPACING_M = 20.0


def elevation_gain(points: Sequence[Point], hysteresis: float = GAIN_HYSTERESIS_M) -> float:
    """Cumulative gain in metres, counting only moves larger than the hysteresis.

    A bare sum of positive differences turns GPS elevation noise into hundreds of
    feet of phantom climbing on a flat city ride, which is why the threshold
    exists and why it is part of the definition rather than a tuning knob.
    """
    eles = [p.ele for p in points if p.ele is not None]
    if len(eles) < 2:
        return 0.0
    gain = 0.0
    reference = eles[0]
    for ele in eles[1:]:
        if ele > reference + hysteresis:
            gain += ele - reference
            reference = ele
        elif ele < reference:
            # The reference tracks the running minimum with no threshold on the
            # way down. Applying the hysteresis symmetrically loses the bottom of
            # every dip and under-reports gain by 5 to 25 percent, which was
            # verified against all fifteen reference routes.
            reference = ele
    return gain


def _resampled_bearings(points: Sequence[Point], min_segment_m: float) -> list[tuple[int, float]]:
    """Bearings of consecutive segments at least `min_segment_m` long.

    Returns (index of segment end, bearing). Short segments are absorbed into the
    following one rather than dropped, so a dense trace and a sparse one over the
    same line yield the same turns.
    """
    out: list[tuple[int, float]] = []
    anchor = 0
    for i in range(1, len(points)):
        if haversine(points[anchor], points[i]) >= min_segment_m:
            out.append((i, bearing(points[anchor], points[i])))
            anchor = i
    return out


def turns(
    points: Sequence[Point],
    min_segment_m: float = TURN_MIN_SEGMENT_M,
    min_bearing_deg: float = TURN_MIN_BEARING_DEG,
) -> int:
    """Count bearing changes above the threshold between consecutive segments."""
    bearings = _resampled_bearings(points, min_segment_m)
    return sum(
        1
        for (_, b1), (_, b2) in zip(bearings, bearings[1:], strict=False)
        if bearing_delta(b1, b2) > min_bearing_deg
    )


def revisit_cell_degrees(
    points: Sequence[Point], proximity_m: float = REVISIT_PROXIMITY_M
) -> tuple[float, float]:
    """The size of `revisits`' grid cell over these points, (latitude, longitude).

    A function rather than four lines inside `revisits` because the property the
    nine-cell scan is a correct shortcut under is a property of the cell size
    and not of any route: a cell has to be at least `proximity_m` across in
    ground distance everywhere the route goes. Measured here, that is one
    assertion; inferred from `revisits`' output it needs a route contrived to
    land a pair exactly astride a cell boundary, which catches a cell that is
    too narrow by a whole percent and cannot see one that is too narrow by a
    tenth of one - the margin absorbs it, which is what the margin is for, and
    the absorbed tenth is then not there for anything else.
    """
    cell_lat = proximity_m / DEGREE_OF_LATITUDE_M  # degrees of latitude per proximity radius
    # The smallest cosine on the route, so the cell is sized for its narrowest
    # ground width rather than its average one. See `revisits`.
    min_cos = min(math.cos(math.radians(p.lat)) for p in points)
    return cell_lat, REVISIT_CELL_LON_MARGIN * cell_lat / max(min_cos, 0.01)


def revisits(
    points: Sequence[Point],
    proximity_m: float = REVISIT_PROXIMITY_M,
    along_route_m: float = REVISIT_ALONG_ROUTE_M,
) -> int:
    """Count places where the route comes back within `proximity_m` of its own line.

    Counted as occurrences rather than as point pairs: a stretch ridden twice
    produces one revisit, not one per sample. This check belongs to Mass Ride
    alone, because a field of hundreds meeting its own tail is a failure while an
    out-and-back group ride is ordinary.
    """
    cum = cumulative_distances(points)
    flagged = [False] * len(points)
    if not points:
        return 0

    # Bucket points into a lat/lon grid roughly `proximity_m` on a side and compare
    # only against the nine neighbouring cells. The pairwise form is O(n^2) and a
    # dense trace here runs to 7,538 points, which is 28 million comparisons for a
    # measurement that belongs in the stats block of every saved route.
    #
    # Two cell sizes, not one, and the second is the whole correctness of the
    # index. A degree of latitude is 111.195 km everywhere; a degree of
    # longitude is that times cos(latitude), which at this region's 38.9 N is
    # 0.778 of it. Dividing both axes by the latitude figure therefore made
    # every cell 22 percent *narrower* than `proximity_m` in ground distance, so
    # a pair 22.5 m apart on an east-west offset could sit two cells apart in x
    # and never be compared: the nine-cell scan silently stopped covering the
    # radius it is the index for. A parallel street a block over - which is what
    # a revisit on a city grid looks like - was the case it lost.
    #
    # The cosine is taken once for the whole route rather than per point: a
    # per-point cell size would put the same ground position in different cells
    # depending on which point asked. It is the route's *smallest* cosine, not
    # its mean. One cell size has to be wide enough in ground distance
    # everywhere the route goes, and a degree of longitude is narrowest at the
    # highest latitude, so the mean sized the cell for the middle of the route
    # and left its northern end short - which on a route whose bulk is in the
    # south is most of the way to a missed pair, and was measurably so. The
    # minimum is the only value that is safe at every point on the route, and it
    # is the conservative direction: too wide a cell costs comparisons, too
    # narrow a cell loses revisits.
    # See `REVISIT_CELL_LON_MARGIN` for the one percent on the longitude axis.
    cell_lat, cell_lon = revisit_cell_degrees(points, proximity_m)

    grid: dict[tuple[int, int], list[int]] = {}
    for i, p in enumerate(points):
        grid.setdefault((int(p.lat / cell_lat), int(p.lon / cell_lon)), []).append(i)

    for i, p in enumerate(points):
        gy, gx = int(p.lat / cell_lat), int(p.lon / cell_lon)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for j in grid.get((gy + dy, gx + dx), ()):
                    if j <= i or cum[j] - cum[i] <= along_route_m:
                        continue
                    if haversine(p, points[j]) < proximity_m:
                        flagged[i] = flagged[j] = True
    count = 0
    previous = False
    for now in flagged:
        if now and not previous:
            count += 1
        previous = now
    # Each revisit involves two stretches of line, the outbound and the return,
    # and both are flagged; reporting it once is what "revisits" means.
    return count // 2


def max_grade(points: Sequence[Point], min_run_m: float = GRADE_MIN_RUN_M) -> float:
    """Steepest grade as a fraction, over runs of at least `min_run_m`.

    The minimum run is what keeps a one-metre elevation wobble between two
    adjacent samples from reporting a 40 percent pitch.
    """
    steepest = 0.0
    anchor = 0
    for i in range(1, len(points)):
        run = haversine(points[anchor], points[i])
        if run < min_run_m:
            continue
        a, b = points[anchor], points[i]
        if a.ele is not None and b.ele is not None:
            steepest = max(steepest, abs(b.ele - a.ele) / run)
        anchor = i
    return steepest


def turn_count_is_reliable(points: Sequence[Point]) -> bool:
    """Whether this trace is sampled coarsely enough for `turns` to mean anything.

    Reported rather than silently corrected. Decimating a dense trace to the
    reliable range was tried and rejected: it fixes the dense trace and breaks the
    sparse ones, losing real turns on four of the five mass rides.
    """
    if len(points) < 2:
        return False
    cum = cumulative_distances(points)
    return (cum[-1] / (len(points) - 1)) >= TURN_MIN_TRACE_SPACING_M


@dataclass(frozen=True)
class RouteStats:
    """The measured properties of a route, in the units the README tables use."""

    distance_mi: float
    gain_ft: float
    max_grade_pct: float
    turns: int
    turns_per_mile: float
    revisits: int
    point_count: int
    mean_spacing_m: float
    turns_reliable: bool

    @classmethod
    def measure(cls, points: Sequence[Point]) -> RouteStats:
        cum = cumulative_distances(points)
        distance_m = cum[-1] if len(points) > 1 else 0.0
        distance_mi = distance_m / METRES_PER_MILE
        turn_count = turns(points)
        return cls(
            distance_mi=distance_mi,
            gain_ft=elevation_gain(points) / METRES_PER_FOOT,
            max_grade_pct=max_grade(points) * 100.0,
            turns=turn_count,
            turns_per_mile=turn_count / distance_mi if distance_mi else 0.0,
            revisits=revisits(points),
            point_count=len(points),
            mean_spacing_m=distance_m / (len(points) - 1) if len(points) > 1 else 0.0,
            turns_reliable=turn_count_is_reliable(points),
        )
