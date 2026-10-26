"""Steep grades on a Mass Ride or a Novice and Nervous ride: marked on the map and priced.

The owner, 2026-10-26: "For mass rides put an elevation warning (orange marker) on any
incline in either direction above 5% grade and provide a penalty, above 8% this becomes a red
marker with an even steeper penalty. Have the warning marker indicate the direction of the
incline (uphill/downhill)" and "Do this for novice rides as well."

So, on those ride types only (`RIDE_TYPES`), a stretch of the route whose grade, read in the
riding direction, is past STEEP either way is a steep stretch, and past VERY_STEEP a very
steep one. The grade is the elevation chart's own (`routemaker.profile.grades`: across two
samples either side, about 120 m), so a marker and the chart agree. A stretch shorter than
MIN_LENGTH_M is left out, so a single steep driveway ramp or a noisy elevation sample does
not flood the map; a very steep part shorter than that stays in its steep stretch, and a
steep remnant shorter than that beside a very steep part joins it.

Each stretch costs the route choice its metres at STEEP_S_PER_M or VERY_STEEP_S_PER_M,
seconds of flat riding a metre, uphill or downhill alike: a hidden routing price on top of
the climb's own cost (`routemaker.hill_cost`) and the brake-riding descent cost
(`routemaker.climbs.descent_cost_s`), never a shown time. Pure: no database, no router.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from routemaker import profile as profile_rules

# The ride types that warn of and price steep grades.
RIDE_TYPES = frozenset({"mass-ride", "novice"})
# Grades past these, either way, rise over run.
STEEP = 0.05
VERY_STEEP = 0.08
# The shortest stretch marked or priced: about a city block (330 ft). The elevation samples
# are 30 m apart, so this is at least four of their gaps.
MIN_LENGTH_M = 100.0
# The price per metre of a stretch, in seconds of flat riding: a 200 m (660 ft) steep stretch
# costs 3 min 20 s, about 0.6 mi (1 km) of detour at a Novice pace; a very steep one four
# times that, 13 min 20 s.
STEEP_S_PER_M = 1.0
VERY_STEEP_S_PER_M = 4.0

UP, DOWN = "up", "down"
LEVEL_STEEP, LEVEL_VERY_STEEP = "steep", "very_steep"


@dataclass(frozen=True)
class Stretch:
    """One steep stretch, in metres along the profile, as the rider meets it."""

    from_m: float
    to_m: float
    direction: str
    level: str
    grade: float

    @property
    def length_m(self) -> float:
        return self.to_m - self.from_m


def _level(grade: float | None) -> int:
    if grade is None:
        return 0
    steep = abs(grade)
    return 2 if steep > VERY_STEEP else 1 if steep > STEEP else 0


def _runs(items: list[tuple[float, int]], at_least: int) -> list[tuple[int, int]]:
    """(first, last) indexes of the runs of `items` whose level is at least `at_least`."""
    out: list[tuple[int, int]] = []
    start = None
    for i, (_m, level) in enumerate(items):
        if level >= at_least and start is None:
            start = i
        elif level < at_least and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(items) - 1))
    return out


def stretches(profile: Sequence[tuple[float, float | None]]) -> list[Stretch]:
    """The profile's steep stretches (`core.routing.grade_profile`, or the chart's samples),
    in the order ridden."""
    samples = [(float(m), h) for m, h in profile]
    grade_at = profile_rules.grades(samples)
    # Runs of samples steep the same way, split at a gap in the heights.
    found: list[Stretch] = []
    run: list[int] = []
    sign = 0

    def close() -> None:
        if run:
            found.extend(_split(samples, grade_at, run, sign))

    for i, grade in enumerate(grade_at):
        level = _level(grade)
        this = 0 if not level or grade is None else (1 if grade > 0 else -1)
        if this and this == sign:
            run.append(i)
            continue
        close()
        run, sign = ([i], this) if this else ([], 0)
    close()
    return found


def _split(
    samples: list[tuple[float, float | None]],
    grade_at: list[float | None],
    run: list[int],
    sign: int,
) -> list[Stretch]:
    """One run of samples steep one way as its stretches: very steep parts of at least
    MIN_LENGTH_M, the rest steep; nothing where the run is shorter than MIN_LENGTH_M."""
    m = [samples[i][0] for i in run]
    if m[-1] - m[0] < MIN_LENGTH_M:
        return []
    direction = UP if sign > 0 else DOWN
    levels = [(m[k], _level(grade_at[i])) for k, i in enumerate(run)]
    red = [(a, b) for a, b in _runs(levels, 2) if m[b] - m[a] >= MIN_LENGTH_M]
    # The cut points: the run's ends and each very steep part's, with what lies between.
    parts: list[tuple[int, int, bool]] = []
    at = 0
    for a, b in red:
        if a > at:
            parts.append((at, a, False))
        parts.append((a, b, True))
        at = b
    if at < len(run) - 1:
        parts.append((at, len(run) - 1, False))
    # A steep remnant too short to mark joins the very steep part beside it.
    merged: list[list] = []
    for a, b, very in parts:
        short = not very and m[b] - m[a] < MIN_LENGTH_M
        if short and merged and merged[-1][2]:
            merged[-1][1] = b
            continue
        last = merged[-1] if merged else None
        if very and last and not last[2] and m[last[1]] - m[last[0]] < MIN_LENGTH_M:
            merged[-1] = [last[0], b, True]
            continue
        merged.append([a, b, very])
    out = []
    for a, b, very in merged:
        steepest = max(abs(grade_at[run[k]] or 0.0) for k in range(a, b + 1))
        if not very:
            # A very steep pitch too short to mark stays orange, said as at most 8%.
            steepest = min(steepest, VERY_STEEP)
        out.append(
            Stretch(
                from_m=m[a],
                to_m=m[b],
                direction=direction,
                level=LEVEL_VERY_STEEP if very else LEVEL_STEEP,
                grade=steepest,
            )
        )
    return out


def penalty_s(profile: Sequence[tuple[float, float | None]]) -> float:
    """What the profile's steep stretches cost the route choice, in seconds of flat riding."""
    return sum(
        s.length_m * (VERY_STEEP_S_PER_M if s.level == LEVEL_VERY_STEEP else STEEP_S_PER_M)
        for s in stretches(profile)
    )


def _feet(metres: float) -> str:
    return f"{round(metres * 3.28084 / 10) * 10:,} ft ({round(metres):,} m)"


def public(found: Sequence[Stretch]) -> list[dict]:
    """The stretches as the answer gives them: whole metres, the steepest grade as a whole
    percent, and one plain sentence."""
    out = []
    for s in found:
        pct = round(s.grade * 100)
        steep = "Very steep" if s.level == LEVEL_VERY_STEEP else "Steep"
        way = "uphill" if s.direction == UP else "downhill"
        out.append(
            {
                "from_m": round(s.from_m),
                "to_m": round(s.to_m),
                "direction": s.direction,
                "level": s.level,
                "grade_pct": pct,
                "text": f"{steep} {way}, up to {pct}%, for {_feet(s.length_m)}.",
            }
        )
    return out
