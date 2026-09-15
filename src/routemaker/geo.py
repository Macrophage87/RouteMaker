"""Spherical geometry on WGS84 coordinates.

Kept deliberately small and dependency-free: every measurement in `measure` is
built from these three functions, so the normative fixture definitions do not
depend on GEOS, PROJ, or a database being present.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# IUGG mean Earth radius. Valhalla and most OSM tooling use the same figure, so
# distances computed here and distances reported by the router agree to within
# rounding rather than drifting by a fixed factor.
EARTH_RADIUS_M = 6371008.8

METRES_PER_MILE = 1609.344
METRES_PER_FOOT = 0.3048


class Point(tuple):
    """A (lon, lat, ele) triple. Elevation is metres and may be None."""

    __slots__ = ()

    def __new__(cls, lon: float, lat: float, ele: float | None = None):
        return super().__new__(cls, (lon, lat, ele))

    @property
    def lon(self) -> float:
        return self[0]

    @property
    def lat(self) -> float:
        return self[1]

    @property
    def ele(self) -> float | None:
        return self[2]


def haversine(a: Point, b: Point) -> float:
    """Great-circle distance in metres between two points."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, h)))


def bearing(a: Point, b: Point) -> float:
    """Initial bearing from `a` to `b`, in degrees clockwise from north [0, 360)."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlon = math.radians(b.lon - a.lon)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def bearing_delta(b1: float, b2: float) -> float:
    """Smallest absolute angle between two bearings, in degrees [0, 180]."""
    return abs((b2 - b1 + 180.0) % 360.0 - 180.0)


def cumulative_distances(points: Sequence[Point]) -> list[float]:
    """Along-route distance in metres at each point, starting at 0."""
    out = [0.0]
    for a, b in zip(points, points[1:], strict=False):
        out.append(out[-1] + haversine(a, b))
    return out


def total_distance(points: Sequence[Point]) -> float:
    """Total along-route distance in metres."""
    return cumulative_distances(points)[-1] if len(points) > 1 else 0.0


def project_onto_segment(point: Point, a: Point, b: Point) -> tuple[float, float]:
    """Nearest point on segment a-b to `point`, as (distance_m, fraction).

    `fraction` is where along the segment the nearest point falls, clamped to
    [0, 1] so an endpoint answers for anything past the end.

    Worked in a local equirectangular frame scaled by the latitude rather than on
    the sphere. Over the tens of metres this is used for, the error is far below
    the survey error of the lines being compared, and the alternative - a
    great-circle cross-track formula - is both slower and wrong at a segment's
    endpoints, where it measures to the extended great circle rather than to the
    segment.
    """
    cos_lat = math.cos(math.radians((a.lat + b.lat) / 2.0))
    ax, ay = a.lon * cos_lat, a.lat
    bx, by = b.lon * cos_lat, b.lat
    px, py = point.lon * cos_lat, point.lat

    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return haversine(point, a), 0.0

    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = min(1.0, max(0.0, t))
    nearest = Point(a.lon + (b.lon - a.lon) * t, a.lat + (b.lat - a.lat) * t)
    return haversine(point, nearest), t


def distance_to_line(point: Point, line: Sequence[Point]) -> tuple[float, float]:
    """Nearest distance from `point` to a polyline, and how far along it that is.

    Returns (distance_m, fraction of the line's length). Distance to the *line*
    rather than to its nearest vertex: an agency survey line and an OSM way
    describe the same road with entirely different vertices, so a vertex-to-vertex
    measure reports a road as far from itself.
    """
    if len(line) < 2:
        return (haversine(point, line[0]), 0.0) if line else (float("inf"), 0.0)

    cumulative = cumulative_distances(line)
    total = cumulative[-1]
    best = (float("inf"), 0.0)
    for index, (a, b) in enumerate(zip(line, line[1:], strict=False)):
        distance, t = project_onto_segment(point, a, b)
        if distance < best[0]:
            along = cumulative[index] + (cumulative[index + 1] - cumulative[index]) * t
            best = (distance, along / total if total else 0.0)
    return best
