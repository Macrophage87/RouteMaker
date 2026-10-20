"""A dirt trail the rider is on, or put a point on, on a ride type that does not plan on them.

The owner, 2026-10-20, after a re-route turned him back off a dirt trail at Lake Needwood:
"Don't plan on the route, but if you enter it or mark a waypoint in it, it will continue to
route through." and "Connecting trails too".

The mountain-bike class of dirt trail (`routemaker.trailaccess`, reason `mtb`) is closed on
the standard graphs and open on the off-road graph Gravel and Mountain Goat ride. A plan on a
standard-graph ride type whose start, stop, via or end lies on one (`touched`) is planned on
the off-road graph instead, with the ride type's own costing. The dirt trail it is on is then
ridden, and the trails joined to it along the way: a run of the route on dirt trails one after
another counts as one run, kept when any of it is a trail touched. A run on a dirt trail no
point touches is one the plan found for itself, which the ride type does not do: it is left out
(`stray_lines`) and the plan made again (`core.routing.plan`).

Rated singletrack (reason `singletrack`) is not this class and stays closed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from django.conf import settings
from django.db import connection

from pipeline.schema import validate_schema_name

from . import segment_info

# The reason the rebuild writes on the mountain-bike class (`routemaker.trailaccess.MTB`).
REASON = "mtb"
# How near a point lies to a trail to be on it: the router's own snap for a stop
# (`core.routing.STOP_RADIUS_M`).
TOUCH_M = 15.0
# The line a stray run is left out by: this long, at the middle of the run's longest stretch,
# so the strip round it (`routemaker.workzones.line_ring`) crosses the trail and little else.
BLOCK_LINE_M = 2.0


def _reason_known(schema: str) -> bool:
    return segment_info.has_columns(schema, "bike_access_reason")


def touched(points: Sequence[Sequence[float]]) -> frozenset[int]:
    """The dirt trails (their way ids) within TOUCH_M of any of `points` ([lon, lat])."""
    if not points:
        return frozenset()
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not _reason_known(schema):
        return frozenset()
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    sql = f"""
        SELECT DISTINCT s.osm_way_id
        FROM unnest(%s::float8[], %s::float8[]) AS p(lon, lat)
        JOIN {schema}.segment AS s
          ON s.bike_access_reason = %s
         AND ST_DWithin(
               s.geometry::geography,
               ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)::geography,
               %s
             )
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [lons, lats, REASON, TOUCH_M])
        return frozenset(int(row[0]) for row in cursor.fetchall())


def dirt_ways(way_ids: Sequence[int]) -> frozenset[int]:
    """Which of `way_ids` are dirt trails."""
    ids = sorted({int(w) for w in way_ids if w})
    if not ids:
        return frozenset()
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not _reason_known(schema):
        return frozenset()
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT DISTINCT osm_way_id FROM {schema}.segment "
            "WHERE osm_way_id = ANY(%s) AND bike_access_reason = %s",
            [ids, REASON],
        )
        return frozenset(int(row[0]) for row in cursor.fetchall())


def runs(way_ids: Sequence[int], dirt: frozenset[int]) -> list[tuple[int, int]]:
    """The runs (start, end) of consecutive pieces on dirt trails, in the order ridden."""
    found: list[tuple[int, int]] = []
    start: int | None = None
    for i, way in enumerate(way_ids):
        if way in dirt:
            if start is None:
                start = i
        elif start is not None:
            found.append((start, i))
            start = None
    if start is not None:
        found.append((start, len(way_ids)))
    return found


def strays(
    way_ids: Sequence[int], dirt: frozenset[int], kept: frozenset[int]
) -> list[tuple[int, int]]:
    """The runs on dirt trails none of whose trails is in `kept` (the trails touched)."""
    return [(a, b) for a, b in runs(way_ids, dirt) if not any(w in kept for w in way_ids[a:b])]


def block_line(lon: float, lat: float, bearing: float) -> tuple[tuple[float, float], ...]:
    """BLOCK_LINE_M along `bearing` (degrees) centred on (lon, lat)."""
    half = BLOCK_LINE_M / 2
    north = math.cos(math.radians(bearing)) * half / 110_540.0
    east = math.sin(math.radians(bearing)) * half / (111_320.0 * math.cos(math.radians(lat)))
    return (
        (round(lon - east, 7), round(lat - north, 7)),
        (round(lon + east, 7), round(lat + north, 7)),
    )


def stray_lines(
    pieces: Sequence, dirt: frozenset[int], kept: frozenset[int]
) -> list[tuple[tuple[float, float], ...]]:
    """A short line across each stray run of `pieces` (`core.routing.Piece`: way_id, lon and
    lat at its middle, metres, bearing), to leave it out by: at the middle of its longest
    stretch, along it."""
    ways = [p.way_id for p in pieces]
    lines: list[tuple[tuple[float, float], ...]] = []
    for a, b in strays(ways, dirt, kept):
        longest = max(pieces[a:b], key=lambda p: p.metres)
        if longest.metres < BLOCK_LINE_M * 2 or longest.bearing is None:
            continue
        lines.append(block_line(longest.lon, longest.lat, longest.bearing))
    return lines
