"""Shape measures: how winding a line is.

Sinuosity is what the Group Ride winding-path penalty is built on. It is stored
per segment at preprocessing time rather than computed per request, because the
layer 4 ranking compares candidates and needs the same number for a segment
every time it appears.
"""

from __future__ import annotations

from collections.abc import Sequence

from .geo import Point, bearing, bearing_delta, haversine

# Below this length sinuosity is noise: a five metre stub between two junctions
# can have any ratio at all and means nothing.
MIN_MEANINGFUL_LENGTH_M = 25.0


def sinuosity(points: Sequence[Point]) -> float:
    """Path length divided by straight-line distance between the endpoints.

    1.0 is a straight line and higher is more winding. A closed loop has no
    meaningful ratio - its endpoints coincide - so it returns infinity rather
    than dividing by zero, and callers score it by sharp bends per mile instead.
    """
    if len(points) < 2:
        return 1.0
    path = sum(haversine(a, b) for a, b in zip(points, points[1:], strict=False))
    if path < MIN_MEANINGFUL_LENGTH_M:
        return 1.0
    straight = haversine(points[0], points[-1])
    if straight == 0.0:
        return float("inf")
    return path / straight


def sharp_bends_per_mile(points: Sequence[Point], threshold_deg: float = 60.0) -> float:
    """Bends sharper than the threshold, per mile.

    The companion to sinuosity, and the measure that still works on a loop. A
    long sweeping curve and a series of tight corners can share a sinuosity
    ratio while riding nothing alike; this separates them.
    """
    from .geo import METRES_PER_MILE

    if len(points) < 3:
        return 0.0
    length = sum(haversine(a, b) for a, b in zip(points, points[1:], strict=False))
    if length == 0.0:
        return 0.0
    bends = 0
    previous = bearing(points[0], points[1])
    for a, b in zip(points[1:], points[2:], strict=False):
        current = bearing(a, b)
        if bearing_delta(previous, current) > threshold_deg:
            bends += 1
        previous = current
    return bends / (length / METRES_PER_MILE)
