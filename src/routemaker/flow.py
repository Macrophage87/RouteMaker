"""How many riders a mass ride carries past a point a minute, and what a hill does to it.

PLAN, Mass Ride, "The headline number: modelled throughput" (OWNER-DECISIONS 116-175):
the road's throughput is the flow at the compressed state of a pinch or a turn,

    riders a second = density x utilisation x usable width x pace

with 0.37 riders per square metre at 1.9 m/s (4.3 mph), a utilisation of 0.7 (a pack
bunches toward part of the road), and the width the road's lanes make. That is about
99 riders a minute for each 11 ft (3.35 m) lane.

Status (OWNER-DECISIONS 394): accepted as the working model; sources pending
FOLLOWUP-FLOW-CALIBRATION. The level figure rests on the owner's counts of three DC
Bike Party rides (item 173: indicative, good to about +-25%, item 175; not a formal
calibration). The grade factors below are not from a measurement: they are this
module's reading of 328(b)'s "documented constants". FOLLOWUP-FLOW-CALIBRATION checks
both against the literature and the owner's DC event videos, and records the sources
in docs/SOURCES.md.

OWNER-DECISIONS 328(b): the model is grade-adjusted. The headline is the level road's.
On a climb the group slows from its 6-8 mph, which lowers what a stretch carries; on a
steep descent riders need wider spacing, which lowers it too. Both are factors on the
level figure (`grade_factor`), from the grade at each sample of the route's profile.

Climbing. The pace falls to `1 / (1 + CLIMB_SLOWING x (grade - FREE_CLIMB_GRADE))` of
the level pace: 80% at 3%, 63% at 6%, 54% at 8%, and never under `MIN_SPEED_RATIO`.
(An illustration of the constant, not an observation: at 63%, a group riding 7 mph on
the level would ride about 4.5 mph up a 6% hill.) The slowing takes `KICK_M` of
climbing (the same 150 m `routemaker.climbs` gives a climb for free before it costs)
to set in, linearly, so a short ramp costs little and a long climb costs the whole
figure (PLAN: "a length factor (grade x length)"). Flow is conserved through a
slowdown, so a slower pace at the same density carries fewer riders, which is what the
factor is.

Descending. Past `BRAKE_GRADE` riders leave more room (they are braking, and a fall
spreads the group): the density falls to `1 / (1 + SPACING x (grade - BRAKE_GRADE))` of
the level one, 83% at 8%, and never under `MIN_SPACING_RATIO`. The pace is not raised.

Avoid (OWNER-DECISIONS 325): "If we've marked it avoid, It should be just marked avoid
with no carrying capacity." A tier-5 stretch has no width and no riders figure here; the
chart and its sentence say "Avoid" there, not a number.

The API (docs/DEVELOPMENT.md "The flow API"), for the route chart and the capacity map:

- `usable_width_m(tier, facility, lanes, oneway)`: the PHYSICAL width, metres, or None,
  ESTIMATED from the classifier's lanes in one direction (406). `tier` is the router's
  text key ("1"-"5", "unknown") or the pipeline's int (1-5, None). The real figure is the
  per-segment column `segment.mass_usable_width_m` (387 part 1), which
  `routemaker.massflow` writes at the rebuild (own side, parked cars out, DC first;
  404-407); the route chart reads that column where the table has it, so the chart and
  the capacity map agree, and this estimate only on an older table.
- `level_riders_per_min(width_m)`: the level figure, a float.
- `grade_factor(grade, climbed_m)`: the climb or descent factor, 0.3-1 (1 on the level).
- `riders_at(width_m, grade, climbed_m)`: the level figure times the grade factor, a
  float, unrounded. The grade is signed in the direction ridden and `climbed_m` is the
  metres into the sustained climb, so the grade factor applies along a route, at query
  time; a per-segment column holds the width, never a graded figure.
- `per_sample(...)`: a route's figures at each profile sample, from (metres, width)
  stretches.
- `BAND_EDGES`, `BAND_WORDS`, `band_index`: the 326/327 bands, the one source. The front
  end's copy (`frontend/src/lib/profileChart.ts` FLOW_BANDS) is held to them by
  `tests/test_profile_flow.py`.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence

from . import climbs

# The width a mass ride has for each travel lane, metres (11 ft), and the width of a
# shared path or trail, which is not lanes (about 10 ft).
LANE_WIDTH_M = 3.35
PATH_WIDTH_M = 3.0
# Through lanes a direction where the segment table does not have them: a street.
DEFAULT_LANES = 1
# The tier of a stretch marked Avoid (OWNER-DECISIONS 325: no carrying capacity).
AVOID_TIER = 5

# The compressed state (PLAN, item 173).
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

# OWNER-DECISIONS 326/327: the bands, in riders a minute, each from its edge up
# (inclusive). Under the first is a bottleneck.
BAND_EDGES = (60, 120, 200)
BAND_WORDS = ("bottleneck", "tight", "good", "wide open")


def band_index(riders_per_min: float) -> int:
    """0 bottleneck, 1 tight, 2 good, 3 wide open."""
    return sum(riders_per_min >= edge for edge in BAND_EDGES)


def tier_number(tier: int | str | None) -> int | None:
    """A tier as an int (1-5), from the router's text key or the pipeline's int; None
    where it is not rated ("unknown", None, or anything else)."""
    if isinstance(tier, bool):
        return None
    if isinstance(tier, int):
        return tier if 1 <= tier <= 5 else None
    if isinstance(tier, str) and tier.strip().isdigit():
        number = int(tier.strip())
        return number if 1 <= number <= 5 else None
    return None


def is_avoid(tier: int | str | None) -> bool:
    """Whether a stretch is marked Avoid (tier 5, OWNER-DECISIONS 325)."""
    return tier_number(tier) == AVOID_TIER


def usable_width_m(
    tier: int | str | None, facility: str | None, lanes: int | None, oneway: bool | None
) -> float | None:
    """The physical width a group has on a stretch, metres, ESTIMATED from the classifier's
    lanes; None where the stretch is unrated, or marked Avoid (325: no carrying capacity).

    The source of truth is the segment table's `mass_usable_width_m`
    (`routemaker.massflow.usable_width_m`, written by the rebuild: the ride's own direction,
    parked cars out, DC's Roadway Block first; OWNER-DECISIONS 404-407), which the capacity
    map colours by and the route chart reads (`core.routing._flow_stretches`). This estimate
    stands in only on a table built before that column.

    `tier` is the router's text key ("1"-"5", "unknown") or the pipeline's int. A road's
    travel lanes in one direction (OWNER-DECISIONS 406: "We should only plan on our own side
    of a two way street"; a one-way street's lanes are all one direction) at
    `LANE_WIDTH_M`, with `DEFAULT_LANES` where the segment table has none (`lanes` is
    through lanes a direction, so `oneway` does not change it). A path is `PATH_WIDTH_M`.
    Parking and painted bike lanes are not in it (the segment table does not carry them to
    here)."""
    number = tier_number(tier)
    if number is None or number == AVOID_TIER:
        return None
    if facility == "path":
        return PATH_WIDTH_M
    through = lanes if lanes else DEFAULT_LANES
    return through * LANE_WIDTH_M


def level_riders_per_min(width_m: float) -> float:
    """What a stretch of this width carries on the level, riders a minute."""
    return 60.0 * DENSITY_PER_M2 * UTILISATION * width_m * PACE_MS


def speed_ratio(grade: float, climbed_m: float) -> float:
    """The fraction of the level pace a group keeps on a climb of `grade`, `climbed_m`
    into it; 1 on the level, on a descent and at the foot of a climb, and the full
    slowing from `KICK_M` in, linearly between."""
    if grade <= FREE_CLIMB_GRADE:
        return 1.0
    full = max(1.0 / (1.0 + CLIMB_SLOWING * (grade - FREE_CLIMB_GRADE)), MIN_SPEED_RATIO)
    return 1.0 - (1.0 - full) * min(1.0, max(climbed_m, 0.0) / KICK_M)


def spacing_ratio(grade: float) -> float:
    """The fraction of the level density a group keeps on a descent of `grade`
    (negative is downhill); 1 unless the descent is steeper than `BRAKE_GRADE`."""
    if grade >= -BRAKE_GRADE:
        return 1.0
    return max(1.0 / (1.0 + SPACING * (-grade - BRAKE_GRADE)), MIN_SPACING_RATIO)


def grade_factor(grade: float | None, climbed_m: float = 0.0) -> float:
    """The climb and descent factors together (`speed_ratio` x `spacing_ratio`): what
    the grade leaves of the level figure. 1 where the grade is not known."""
    if grade is None:
        return 1.0
    return speed_ratio(grade, climbed_m) * spacing_ratio(grade)


def riders_at(width_m: float, grade: float | None, climbed_m: float = 0.0) -> float:
    """Riders a minute a stretch of `width_m` carries at `grade` (signed, in the
    direction ridden), `climbed_m` into a sustained climb: the level figure times
    `grade_factor`. Unrounded; the caller rounds for display."""
    return level_riders_per_min(width_m) * grade_factor(grade, climbed_m)


def adjusted_riders_per_min(width_m: float, grade: float | None, climbed_m: float) -> float:
    """The level figure times the climb and descent factors; the level figure where the
    grade is not known. The same as `riders_at`, under the name the first callers used."""
    return riders_at(width_m, grade, climbed_m)


def climbed_along(sample_m: Sequence[float], runs: Sequence[climbs.Run]) -> list[float]:
    """Metres into the sustained climb at each sample (0 where it is on none), for
    samples in route order: one pass with a pointer over the climbs, which are in route
    order too (`climbs.runs`) and do not overlap one another."""
    ups = [run for run in runs if run.rise_m > 0]
    out: list[float] = []
    at = 0
    for m in sample_m:
        while at < len(ups) and ups[at].end_m < m:
            at += 1
        run = ups[at] if at < len(ups) else None
        out.append(m - run.start_m if run is not None and run.start_m <= m else 0.0)
    return out


def climbed_at(m: float, runs: Sequence[climbs.Run]) -> float:
    """Metres into the sustained climb one position is on; 0 where it is on none."""
    return climbed_along([m], runs)[0]


def stretch_index(
    sample_m: Sequence[float], stretches: Sequence[tuple[float, ...]]
) -> list[int | None]:
    """Which stretch each sample lies on, by the stretches' summed metres (the first
    element of each); a sample on a boundary is on the earlier one, and one past the
    end on the last. None for every sample where there are no stretches."""
    if not stretches:
        return [None] * len(sample_m)
    ends: list[float] = []
    total = 0.0
    for stretch in stretches:
        total += stretch[0]
        ends.append(total)
    last = len(ends) - 1
    return [min(bisect.bisect_left(ends, m), last) for m in sample_m]


def per_sample(
    samples: Sequence[tuple[float, float | None]],
    grade_at: Sequence[float | None],
    stretches: Sequence[tuple[float, float | None]],
    runs: Sequence[climbs.Run] | None = None,
    where: Sequence[int | None] | None = None,
) -> tuple[list[float | None], list[float | None]]:
    """(riders a minute, the level figure) at each sample, unrounded floats, None where
    the width is not known (or the stretch is Avoid). `stretches` is (metres, physical
    width) in the order ridden, as the route is cut; `runs` the profile's
    `climbs.runs`, computed here when not given; `where` the stretch each sample is on,
    where the caller knows it (a pair of samples at a boundary, one on each side), else
    `stretch_index`."""
    if runs is None:
        runs = climbs.runs(list(samples))
    sample_m = [m for m, _h in samples]
    if where is None:
        where = stretch_index(sample_m, stretches)
    climbed = climbed_along(sample_m, runs)
    adjusted: list[float | None] = []
    level: list[float | None] = []
    for index, grade, into in zip(where, grade_at, climbed, strict=True):
        width = stretches[index][1] if index is not None else None
        if width is None:
            adjusted.append(None)
            level.append(None)
            continue
        level.append(level_riders_per_min(width))
        adjusted.append(riders_at(width, grade, into))
    return adjusted, level
