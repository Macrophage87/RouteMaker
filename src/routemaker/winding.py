"""Winding trails, which the road-bike graph prices like a busy street.

The owner, 2026-11-02, on the Road Bike ride type: "Road bikes would probably stay away from
trails with lots of direction changes, so that could be penalized too. For instance Sligo
Creek Trail". Valhalla prices a turn only where a route leaves one way for another
(`maneuver_penalty`), never the bends along one, so the bends are counted here and the road-bike
graph (`pipeline.variants.Variant.PAVED`) carries the result as `rm:winding`, which
lua/routemaker_remap.lua prices as the LTS 3 stress penalty on that graph alone.

The measure is how far the way turns, in degrees of heading change summed over its vertices,
per 100 m. Measured on OSM ways read from the OSM API on 2026-11-02 (paved trails): the Capital
Crescent Trail's rail bed turns 0 to 5 degrees per 100 m; Sligo Creek Trail 43 to 124 on its
bending stretches, under 31 on its straight pieces; Long Branch Trail 57 to 107; Rock Creek's
Western Ridge Trail 0 to 113. `WINDING_DEG_PER_100M` sits between the two kinds. A short way is
measured over at least `MIN_SPAN_M`, so one gentle bend (under 80 degrees) where a connector
meets a road does not make it winding. One right-angle bend on a way under 225 m does, on
purpose: Sligo Creek Trail's short bending pieces are just that (85 to 214 m at 43 to 52
degrees per 100 m), and leaving out each way's sharpest bend would let them through. Sinuosity (`routemaker.shape`) cannot tell them apart: Sligo Creek Trail's ways
come to 1.01 to 1.21, its bends swinging back and forth across a nearly straight line.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# Degrees of heading change per 100 m at and above which a trail is winding.
WINDING_DEG_PER_100M = 40.0
# The shortest span a way's turning is spread over (m).
MIN_SPAN_M = 200.0
# Steps shorter than this (m) carry no heading: two nodes almost on top of each other.
MIN_STEP_M = 0.5

_EARTH_M_PER_DEG_LAT = 110_540.0
_EARTH_M_PER_DEG_LON = 111_320.0


def _planar(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """(lon, lat) to metres on a local plane, which is close enough over one way."""
    lat0 = math.radians(points[0][1])
    return [
        (lon * _EARTH_M_PER_DEG_LON * math.cos(lat0), lat * _EARTH_M_PER_DEG_LAT)
        for lon, lat in points
    ]


def turning(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """The way's length (m) and the heading change summed over its vertices (degrees)."""
    if len(points) < 2:
        return 0.0, 0.0
    plane = _planar(points)
    length = 0.0
    headings: list[float] = []
    for a, b in zip(plane, plane[1:], strict=False):
        step = math.dist(a, b)
        length += step
        if step >= MIN_STEP_M:
            headings.append(math.atan2(b[1] - a[1], b[0] - a[0]))
    total = 0.0
    for h1, h2 in zip(headings, headings[1:], strict=False):
        total += abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
    return length, math.degrees(total)


def deg_per_100m(points: Sequence[tuple[float, float]]) -> float:
    """How much the way bends: degrees of heading change per 100 m, over at least MIN_SPAN_M."""
    length, degrees = turning(points)
    if length <= 0:
        return 0.0
    return degrees / max(length, MIN_SPAN_M) * 100.0


def is_winding(points: Sequence[tuple[float, float]]) -> bool:
    """Whether a trail bends enough that a road bike would ride round it: `WINDING_DEG_PER_100M`."""
    return deg_per_100m(points) >= WINDING_DEG_PER_100M
