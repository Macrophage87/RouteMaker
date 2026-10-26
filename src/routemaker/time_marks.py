"""Where along a route its time is spent, for a ride's arrival times.

The owner, 2026-10-26, on the ride's arrival times (front end lib/arrival.ts): "Does on ride
ETA also consider elevation?" then "yes. make sure intersection waits are considered too".
A route's time (`duration_s`) is the router's, whose bicycle costing slows the rider on a
climb and speeds them on a descent, plus the junctions' waits (`routemaker.junction_delay`).
Spread evenly over the line, a climb near the end made the times early until it came. The
marks keep where the time falls: the router's own time at each maneuver (its edges' grade
adjusted seconds), and each junction run's wait at its place.

Each mark is [fraction of the route's length, seconds from the start], in order, the seconds
never falling. A wait is a step: the mark before it at the same fraction, then the one after.
The front end scales them to `duration_s` (a walked stretch, Mountain bike's singletrack
pace) and reads the seconds between two places on the line from them. Pure: no router, no
database.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from routemaker.geo import Point, haversine

# Kept small: about two marks a junction and one a maneuver, rounded.
FRACTION_PLACES = 5
SECONDS_PLACES = 1


def _along(coordinates: Sequence[tuple[float, float]]) -> list[float]:
    """Metres along the line at each vertex."""
    along = [0.0]
    for a, b in zip(coordinates, coordinates[1:], strict=False):
        along.append(along[-1] + haversine(Point(*a), Point(*b)))
    return along


def router_marks(
    legs: Sequence[dict], coordinates: Sequence[tuple[float, float]], leg_ends: Sequence[int]
) -> list[tuple[float, float]] | None:
    """The router's seconds at each maneuver's start and each leg's end, as (fraction of the
    line's length, seconds). A leg with no maneuver times is its summary time spread over it.
    None where the line has no length or the router no time."""
    along = _along(coordinates)
    total_m = along[-1] if along else 0.0
    if total_m <= 0 or len(leg_ends) != len(legs):
        return None
    marks: list[tuple[float, float]] = [(0.0, 0.0)]
    seconds = 0.0
    for k, leg in enumerate(legs):
        base = leg_ends[k - 1] if k else 0
        end = leg_ends[k]
        maneuvers = leg.get("maneuvers") or []
        timed = [m for m in maneuvers if float(m.get("time") or 0.0) > 0]
        if timed:
            for maneuver in maneuvers:
                index = min(end, base + int(maneuver.get("begin_shape_index") or 0))
                marks.append((along[index] / total_m, seconds))
                seconds += float(maneuver.get("time") or 0.0)
        else:
            seconds += float((leg.get("summary") or {}).get("time") or 0.0)
        marks.append((along[end] / total_m, seconds))
    if seconds <= 0:
        return None
    return marks


def _at(marks: Sequence[tuple[float, float]], fraction: float) -> float:
    """The seconds at `fraction`, between the marks either side."""
    for (f0, s0), (f1, s1) in zip(marks, marks[1:], strict=False):
        if f0 <= fraction <= f1:
            return s0 if f1 <= f0 else s0 + (s1 - s0) * (fraction - f0) / (f1 - f0)
    return marks[-1][1]


def time_marks(
    router: Sequence[tuple[float, float]] | None,
    waits: Iterable[tuple[float, float]],
    traced_m: float,
) -> list[list[float]] | None:
    """The route's marks: the router's (`router_marks`) with each junction run's wait
    (`junction_delay.delay_runs`: metres along the traced length, seconds) added as a step
    at its place. None without the router's."""
    if not router:
        return None
    steps = sorted(
        (min(1.0, max(0.0, m / traced_m)), s) for m, s in waits if s > 0 and traced_m > 0
    )
    out: list[tuple[float, float]] = []
    added = 0.0
    k = 0
    for f, s in router:
        # The waits before this mark, each a step at its own place.
        while k < len(steps) and steps[k][0] < f:
            at, wait = steps[k]
            out.append((at, _at(router, at) + added))
            added += wait
            out.append((at, _at(router, at) + added))
            k += 1
        out.append((f, s + added))
    for at, wait in steps[k:]:
        out.append((at, router[-1][1] + added))
        added += wait
        out.append((at, router[-1][1] + added))
    rounded: list[list[float]] = []
    for f, s in out:
        mark = [round(f, FRACTION_PLACES), round(s, SECONDS_PLACES)]
        # A repeat says nothing; seconds never fall (rounding aside).
        if rounded and mark == rounded[-1]:
            continue
        if rounded and mark[1] < rounded[-1][1]:
            mark[1] = rounded[-1][1]
        rounded.append(mark)
    return rounded
