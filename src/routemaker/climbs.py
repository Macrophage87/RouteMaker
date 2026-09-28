"""Sustained climbs and descents along a route, and what each costs a rider.

The owner, 2026-09-28, asked about PLAN's "Steepest hill I'll accept" control:
"I'd probably have an increasing penalty for steeper hills instead." Then:
"In many cases it's not just stepness but steepness and length. 10% can be done
for 100m of riding, people would just sprint before it. If continued over
kilometers, that becomes a hike-a-bike". And of descents: "I'd say a descent
over about 2-3% might actually want to be penalized. There's a point where it's
a fun downhill and a point where you're riding the breaks." - with the
threshold depending on the ride type ("Depends on ride type").

Valhalla's own grade penalty (sif/bicyclecost.cc, `kAvoidHillsStrength`) is
per edge and per metre: it grows steeply with grade but cannot tell a 100 m
kick from a kilometre of the same grade, because each edge is priced alone. So
a route's elevation profile is read here as a sequence of *sustained* climbs and
descents - a run that keeps rising (or falling), allowing brief dips (or rises)
and short flats - and each is priced by its grade and its length together.

Everything here is direction-aware by construction: the profile is the route's,
in the order it is ridden, so the same street is a climb one way and a descent
the other. Profiles are (distance along the route in metres, elevation in
metres) pairs; a missing elevation (None) splits the profile.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# A climb survives a dip of this many metres and a flat of this many metres
# without ending: a sag in a long climb, or a cross street, is not the top.
# Three metres is above 1-arc-second DEM noise on a road (the elevation gain
# hysteresis in routemaker.measure is the same order), and 150 m of flat is a
# block or two.
DIP_M = 3.0
FLAT_M = 150.0
# Less gain (or drop) than this is not a hill at all.
MIN_RISE_M = 5.0

# The owner's "10% can be done for 100m of riding, people would just sprint
# before it": the first stretch of any climb is free, whatever its grade.
KICK_M = 150.0
# Grades up to this are ridden seated all day and cost nothing extra.
CLIMB_FREE_GRADE = 0.03
# The grade weight past a threshold: the excess, growing faster than the excess
# itself (it doubles at 3 points past the threshold), so that per metre climbed
# a 10% pitch costs 3.5 times a 5% one over the same length.
STEEPENING = 0.03
# What a climb costs, in seconds of riding, per metre past the kick and per
# unit of grade weight, before the length multiplier. Chosen so that 1 km at
# 8% - the owner's "continued over kilometers, that becomes a hike-a-bike" at
# its threshold - costs about what walking it would add (about 6 minutes over
# riding it: 4.5 km/h against 9 km/h, Valhalla's own speed at 8% for a hybrid):
# 1.7 * 850 * 0.05 * (1 + 0.05/0.03) * (1 + 850/1000) = 356 s.
CLIMB_S_PER_M = 1.7
# The length multiplier grows by one for every this many metres past the kick,
# so a climb costs more than twice as much when it is twice as long.
SUSTAIN_M = 1000.0

# Descents: free up to the ride type's threshold (`presets.Preset.brake_grade`);
# past it, the same weight as a climb's ("a point where you're riding the
# breaks").
DESCENT_S_PER_M = 1.7


@dataclass(frozen=True)
class Run:
    """One sustained climb (rise > 0) or descent (rise < 0)."""

    start_m: float
    end_m: float
    rise_m: float

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m

    @property
    def grade(self) -> float:
        return abs(self.rise_m) / self.length_m if self.length_m > 0 else 0.0


def _pieces(profile: Sequence[tuple[float, float | None]]) -> list[list[tuple[float, float]]]:
    pieces: list[list[tuple[float, float]]] = [[]]
    for distance, elevation in profile:
        if elevation is None:
            if pieces[-1]:
                pieces.append([])
            continue
        pieces[-1].append((float(distance), float(elevation)))
    return [p for p in pieces if len(p) >= 2]


def _climbs(points: list[tuple[float, float]], sign: float) -> list[Run]:
    """Sustained rises of `sign * elevation` along points."""
    runs: list[Run] = []
    n = len(points)
    i = 0
    while i < n - 1:
        start = peak = i
        j = i + 1
        while j < n:
            e = sign * points[j][1]
            if e > sign * points[peak][1]:
                peak = j
            elif peak == start and e <= sign * points[start][1]:
                # Still going down (or level) before any rise: the climb starts lower.
                start = peak = j
            elif sign * points[peak][1] - e > DIP_M or points[j][0] - points[peak][0] > FLAT_M:
                break
            j += 1
        rise = sign * (points[peak][1] - points[start][1])
        if peak > start and rise >= MIN_RISE_M:
            runs.append(Run(points[start][0], points[peak][0], sign * rise))
        i = max(peak, start + 1) if peak > start else j
    return runs


def runs(profile: Sequence[tuple[float, float | None]]) -> list[Run]:
    """The sustained climbs and descents of a profile, in the order ridden."""
    found: list[Run] = []
    for piece in _pieces(profile):
        found.extend(_climbs(piece, 1.0))
        found.extend(_climbs(piece, -1.0))
    return sorted(found, key=lambda run: run.start_m)


def _weight(excess: float) -> float:
    return excess * (1.0 + excess / STEEPENING) if excess > 0 else 0.0


def _sustained(length_m: float) -> float:
    """Metres past the kick, and the multiplier that grows with them."""
    past = max(0.0, length_m - KICK_M)
    return past * (1.0 + past / SUSTAIN_M)


def climb_cost_s(run: Run) -> float:
    """What a climb costs a rider, in seconds, past what Valhalla's time says."""
    if run.rise_m <= 0:
        return 0.0
    return CLIMB_S_PER_M * _weight(run.grade - CLIMB_FREE_GRADE) * _sustained(run.length_m)


def descent_cost_s(run: Run, brake_grade: float | None) -> float:
    """What riding the brakes down a descent costs, for a ride type whose
    descents are free up to `brake_grade` (None: never charged)."""
    if run.rise_m >= 0 or brake_grade is None:
        return 0.0
    return DESCENT_S_PER_M * _weight(run.grade - brake_grade) * _sustained(run.length_m)


def grade_cost_s(profile: Sequence[tuple[float, float | None]], brake_grade: float | None) -> float:
    """The whole profile's sustained climb and descent cost, in seconds."""
    return sum(
        climb_cost_s(run) if run.rise_m > 0 else descent_cost_s(run, brake_grade)
        for run in runs(profile)
    )
