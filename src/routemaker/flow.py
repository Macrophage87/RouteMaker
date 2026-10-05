"""How many riders a mass ride carries past a point a minute, and what a hill does to it.

PLAN, Mass Ride, "The headline number: modelled throughput" (OWNER-DECISIONS 116-175,
calibrated on the owner's measured counts of three DC Bike Party rides): the road's
throughput is the flow at the measured compressed state, a pinch or a turn,

    riders a second = density x utilisation x usable width x pace

with 0.37 riders per square metre at 1.9 m/s (4.3 mph), a utilisation of 0.7 (a pack
bunches toward part of the road), and the width the road's lanes make. That is about
100 riders a minute for each 11 ft (3.35 m) lane. These are indicative, good to about
+-25% (item 175), and every constant here is owner-confirmable.

OWNER-DECISIONS 328(b): the model is grade-adjusted. The headline is the level road's.
On a climb the group slows from its 6-8 mph, which lowers what a stretch carries; on a
steep descent riders need wider spacing, which lowers it too. Both are factors on the
level figure, from the grade at each sample of the route's profile, with the constants
below.

Climbing. The pace falls to `1 / (1 + CLIMB_SLOWING x (grade - FREE_CLIMB_GRADE))` of
the level pace: 80% at 3%, 63% at 6%, 54% at 8%, and never under `MIN_SPEED_RATIO`.
That reads the way a mixed group climbs: a pack of every fitness on a 6% hill rides
about 4.5 mph instead of 7. The slowing takes `KICK_M` of climbing (the same 150 m
`routemaker.climbs` gives a climb for free before it costs) to set in, so a short ramp
costs little and a long climb costs the whole figure (PLAN: "a length factor (grade x
length)"). Flow is conserved through a slowdown, so a slower pace at the same density
carries fewer riders, which is what the factor is.

Descending. Past `BRAKE_GRADE` riders leave more room (they are braking, and a fall
spreads the group): the density falls to `1 / (1 + SPACING x (grade - BRAKE_GRADE))` of
the level one, 83% at 8%, and never under `MIN_SPACING_RATIO`. The pace is not raised.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import climbs

# The width a mass ride has for each travel lane, metres (11 ft), and the width of a
# shared path or trail, which is not lanes.
LANE_WIDTH_M = 3.35
PATH_WIDTH_M = 3.0
# Through lanes a direction where the segment table does not have them: a street.
DEFAULT_LANES = 1

# The measured compressed state (PLAN, item 173).
DENSITY_PER_M2 = 0.37
UTILISATION = 0.7
PACE_MS = 1.9

# The grade adjustment (OWNER-DECISIONS 328(b)).
FREE_CLIMB_GRADE = 0.01
CLIMB_SLOWING = 12.0
MIN_SPEED_RATIO = 0.3
KICK_M = climbs.KICK_M
BRAKE_GRADE = 0.04
SPACING = 5.0
MIN_SPACING_RATIO = 0.6

# OWNER-DECISIONS 326: the bands, in riders a minute. Under the first is a bottleneck.
BAND_EDGES = (60, 120, 200)
BAND_WORDS = ("bottleneck", "tight", "good", "wide open")


def band_index(riders_per_min: float) -> int:
    """0 bottleneck, 1 tight, 2 good, 3 wide open."""
    return sum(riders_per_min >= edge for edge in BAND_EDGES)


def usable_width_m(
    tier: str | None, facility: str | None, lanes: int | None, oneway: bool | None
) -> float | None:
    """The width a group has on a stretch, metres; None where the stretch is unknown.

    A road's travel lanes (both directions of a two-way road: a mass ride takes the
    street) at `LANE_WIDTH_M`, with `DEFAULT_LANES` a direction where the segment table
    has none. A path is `PATH_WIDTH_M`. Parking and painted bike lanes are not in it
    (the segment table does not carry them to here, so the figure errs low)."""
    if tier is None or tier == "unknown":
        return None
    if facility == "path":
        return PATH_WIDTH_M
    through = lanes if lanes else DEFAULT_LANES
    return through * (1 if oneway else 2) * LANE_WIDTH_M


def level_riders_per_min(width_m: float) -> float:
    """What a stretch of this width carries on the level."""
    return 60.0 * DENSITY_PER_M2 * UTILISATION * width_m * PACE_MS


def speed_ratio(grade: float, climbed_m: float) -> float:
    """The fraction of the level pace a group keeps on a climb of `grade`, `climbed_m`
    into it; 1 on the level, on a descent and in the first stretch of a climb."""
    if grade <= FREE_CLIMB_GRADE:
        return 1.0
    full = max(1.0 / (1.0 + CLIMB_SLOWING * (grade - FREE_CLIMB_GRADE)), MIN_SPEED_RATIO)
    return 1.0 - (1.0 - full) * min(1.0, max(climbed_m, 0.0) / KICK_M)


def spacing_ratio(grade: float) -> float:
    """The fraction of the level density a group keeps on a descent of `grade`
    (negative is downhill); 1 unless the descent is steep."""
    if grade >= -BRAKE_GRADE:
        return 1.0
    return max(1.0 / (1.0 + SPACING * (-grade - BRAKE_GRADE)), MIN_SPACING_RATIO)


def adjusted_riders_per_min(width_m: float, grade: float | None, climbed_m: float) -> float:
    level = level_riders_per_min(width_m)
    if grade is None:
        return level
    return level * speed_ratio(grade, climbed_m) * spacing_ratio(grade)


def climbed_at(m: float, runs: Sequence[climbs.Run]) -> float:
    """Metres into the sustained climb the position is on; 0 where it is on none."""
    for run in runs:
        if run.rise_m > 0 and run.start_m <= m <= run.end_m:
            return m - run.start_m
    return 0.0


def per_sample(
    samples: Sequence[tuple[float, float | None]],
    grade_at: Sequence[float | None],
    stretches: Sequence[tuple[float, float | None]],
) -> tuple[list[int | None], list[int | None]]:
    """(riders a minute, the level figure) at each sample, None where the width is not
    known. `stretches` is (metres, width) in the order ridden, as the route is cut."""
    ends: list[float] = []
    at = 0.0
    for metres, _width in stretches:
        at += metres
        ends.append(at)
    runs = climbs.runs(list(samples))
    adjusted: list[int | None] = []
    level: list[int | None] = []
    index = 0
    for (m, _h), grade in zip(samples, grade_at, strict=True):
        while index < len(ends) - 1 and ends[index] < m:
            index += 1
        width = stretches[index][1] if stretches else None
        if width is None:
            adjusted.append(None)
            level.append(None)
            continue
        level.append(round(level_riders_per_min(width)))
        adjusted.append(round(adjusted_riders_per_min(width, grade, climbed_at(m, runs))))
    return adjusted, level
