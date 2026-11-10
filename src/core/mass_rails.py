"""A Mass Ride never rides along street-running rails (OWNER-DECISIONS 289, routing hunt 4 R4-1).

The owner, 2026-10-03, amending 288: "Keep mass rides off H street". Item 288 prices a road
with rails in it as LTS 4 for every ride type (`routemaker.hazards`, `rm:hazard`), and a Mass
Ride plans at stress 0, where that price costs it almost nothing: it rode the H Street and
Benning Road NE streetcar rails for most of a mile. So on a Mass Ride the rail streets near
the ride are left out of every request the plan makes, as the roads a rider marks closed are
(`core.workzones.blocked_rings`): trimmed at their ends and cut where a way crosses them, so a
ride still crosses the rails, square on, at a cross street. Other ride types, Group Ride with
trails off included, share the no-trail graph and keep 288's LTS 4 price, so the ways are not
closed in the graph: this is the planner's alone, and needs no map rebuild.

A Mass Ride's start, stop or end on a rail street (the road the router would match it to has
rails) is moved to the nearest cross street, a little way along it, and the answer says so
(`moved_points`, reason "rail_street"). Where no route is found with the rails left out, the
plan is made again with them open (`routing.plan`), and the route marks and names the rails
it rides (`road_hazards`), as before.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence

from django.conf import settings

from pipeline.schema import HAZARD_COLUMN, validate_schema_name
from routemaker import hazards
from routemaker import workzones as rules
from routemaker.lang import t

from . import segment_info
from . import workzones as work_zones

logger = logging.getLogger(__name__)

PRESET = "mass-ride"

# How far beyond the box of the ride's points the rail streets are left out. Claude's default,
# not measured: a Mass Ride stays in the District, whose only street rails (the H Street and
# Benning Road NE line) are about 2.2 mi (3.6 km) long, and the way round them found in the
# hunt was 0.55 mi (0.9 km) longer.
RAILS_REACH_M = 3000.0
# A point is on a rail street where the nearest road to it, within this far, has rails: the
# router matches a stop to its nearest way. Claude's default, not measured.
NEAREST_ROAD_M = 200.0
# The nearest cross street is looked for this far along the rail street from the point.
# Claude's default, not measured: about three DC blocks.
CROSS_STREET_SEARCH_M = 400.0
# The moved point lies this far along the cross street from the rails, past the router's
# stop radius (`routing.STOP_RADIUS_M`, 15 m) and the strip the rails are left out by
# (`routemaker.workzones.HALF_WIDTH_M`, 6 m), so it is matched to the cross street and not to
# the rail street. Claude's default, not measured.
CROSS_STREET_OFFSET_M = 30.0

RAIL_STREET = "rail_street"
RAIL_STREET_NOTE = (
    "This point is on a street with streetcar rails in it, which a Mass Ride does not ride "
    "along. The route goes to the nearest cross street."
)

_EARTH_M = 111_320.0


def _has_rails(value: str | None) -> bool:
    return any(kind == hazards.RAILS for kind, _ in hazards.decode(value))


def _schema() -> str | None:
    try:
        schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    except (ValueError, AttributeError):
        return None
    if not segment_info.has_columns(schema, HAZARD_COLUMN):
        return None
    return schema


def _box(points: Sequence[Sequence[float]], reach_m: float) -> tuple[float, float, float, float]:
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    dlat = reach_m / _EARTH_M
    dlon = reach_m / (_EARTH_M * max(0.1, math.cos(math.radians(sum(lats) / len(lats)))))
    return min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat


def lines_near(points: Sequence[Sequence[float]], reach_m: float = RAILS_REACH_M) -> list:
    """The rail streets within `reach_m` of the box of `points`: each a line of (lon, lat), the
    map's segments with rails merged where they join. None where the table cannot say."""
    if not points:
        return []
    schema = _schema()
    if schema is None:
        return []
    from .routing import PlanCancelled, plan_cursor

    try:
        with plan_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT ST_AsGeoJSON(d.geom, 7) FROM (
                    SELECT (ST_Dump(ST_LineMerge(ST_Union(s.geometry)))).geom AS geom
                    FROM {schema}.segment AS s
                    WHERE s.geometry && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                      AND s.{HAZARD_COLUMN} LIKE %s
                ) AS d
                """,
                [*_box(points, reach_m), f"%{hazards.RAILS}%"],
            )
            rows = cursor.fetchall()
    except PlanCancelled:
        raise
    except Exception:  # noqa: BLE001 - the plan goes on with the rails priced, as before
        logger.warning("a Mass Ride's rail streets could not be read", exc_info=True)
        return []
    lines = []
    for (text,) in rows:
        for part in work_zones._line_parts(text):
            line = tuple((float(p[0]), float(p[1])) for p in part)
            if len(line) >= 2:
                lines.append(line)
    return lines


def rings(lines, keep_near: Sequence[Sequence[float]] = ()) -> list[list[list[float]]]:
    """The strips the router leaves out for the rail streets `lines`: each trimmed at its ends
    and cut where a way crosses it (`work_zones.crossings`), so a cross street is kept and the
    rails are crossed there; less the stretches near `keep_near` (a ride's re-plan from a rider
    on the rails, who must be able to set off). As many as fit the router's polygon limits."""
    lines = list(lines)
    if not lines:
        return []
    out: list[list[list[float]]] = []
    for line, cut in zip(lines, work_zones.crossings(lines), strict=True):
        own = rules.line_rings(line, rules.TRIM_M, points=keep_near, crossings=cut)
        if own and rules.over_budget(out + own):
            logger.info("a Mass Ride's rail streets past the router's polygon limits")
            break
        out.extend(own)
    return out


def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    return lon * _EARTH_M * math.cos(math.radians(lat0)), lat * _EARTH_M


def point_along(
    line: Sequence[Sequence[float]], start: Sequence[float], offset_m: float
) -> list[float]:
    """The point `offset_m` along `line` from its nearest point to `start`, towards the end of
    the line farther from `start`; that end where the line is shorter."""
    lat0 = float(start[1])
    xy = [_xy(float(p[0]), float(p[1]), lat0) for p in line]
    s = _xy(float(start[0]), float(start[1]), lat0)
    cumulative = [0.0]
    for a, b in zip(xy, xy[1:], strict=False):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    total = cumulative[-1]
    best, at = math.inf, 0.0
    for i, (a, b) in enumerate(zip(xy, xy[1:], strict=False)):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        f = (
            0.0
            if length2 == 0
            else max(0.0, min(1.0, ((s[0] - a[0]) * dx + (s[1] - a[1]) * dy) / length2))
        )
        d = math.dist(s, (a[0] + f * dx, a[1] + f * dy))
        if d < best:
            best, at = d, cumulative[i] + f * math.dist(a, b)
    target = at + offset_m if total - at >= at else at - offset_m
    target = max(0.0, min(total, target))
    for i in range(1, len(cumulative)):
        if cumulative[i] >= target or i == len(cumulative) - 1:
            span = cumulative[i] - cumulative[i - 1]
            f = 0.0 if span == 0 else (target - cumulative[i - 1]) / span
            x = xy[i - 1][0] + f * (xy[i][0] - xy[i - 1][0])
            y = xy[i - 1][1] + f * (xy[i][1] - xy[i - 1][1])
            return [round(x / (_EARTH_M * math.cos(math.radians(lat0))), 6), round(y / _EARTH_M, 6)]
    return [float(line[0][0]), float(line[0][1])]


_ON_RAILS = """
SELECT s.{column}
FROM {schema}.segment AS s
WHERE s.map_class = 'road' AND NOT s.is_trail_class
  AND ST_DWithin(s.geometry::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
LIMIT 1
"""

_CROSS_STREET = """
WITH p AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g)
SELECT ST_AsGeoJSON(c.geometry, 7), ST_X(j.pt), ST_Y(j.pt)
FROM p
JOIN {schema}.segment AS r
  ON ST_DWithin(r.geometry::geography, p.g::geography, %s) AND r.{column} LIKE %s
JOIN {schema}.segment AS c
  ON c.geometry && r.geometry AND ST_Intersects(c.geometry, r.geometry)
CROSS JOIN LATERAL (SELECT ST_ClosestPoint(c.geometry, r.geometry) AS pt) AS j
WHERE c.map_class = 'road' AND NOT c.is_trail_class
  AND (c.{column} IS NULL OR c.{column} NOT LIKE %s)
ORDER BY ST_Distance(j.pt::geography, p.g::geography), c.id
LIMIT 1
"""


def move_off_rails(
    points: list[list[float]], skip: Sequence[int] = ()
) -> tuple[list[list[float]], list[dict]]:
    """A Mass Ride's points on a rail street moved to the nearest cross street,
    CROSS_STREET_OFFSET_M along it from the rails, with what the answer reports of each
    (`moved_points`, as `routing.move_zoo_points`). `skip` are the indices left where they are
    (a point already moved; a ride's re-plan's start, which is the rider). A point with no
    cross street found stays where it is."""
    out = [list(p) for p in points]
    moved: list[dict] = []
    schema = _schema()
    if schema is None or not points:
        return out, moved
    from .routing import PlanCancelled, plan_cursor

    like = f"%{hazards.RAILS}%"
    try:
        with plan_cursor() as cursor:
            for index, (lon, lat) in enumerate(points):
                if index in skip:
                    continue
                cursor.execute(
                    _ON_RAILS.format(schema=schema, column=HAZARD_COLUMN),
                    [lon, lat, NEAREST_ROAD_M, lon, lat],
                )
                row = cursor.fetchone()
                if row is None or not _has_rails(row[0]):
                    continue
                cursor.execute(
                    _CROSS_STREET.format(schema=schema, column=HAZARD_COLUMN),
                    [lon, lat, CROSS_STREET_SEARCH_M, like, like],
                )
                found = cursor.fetchone()
                if found is None:
                    continue
                (cross,) = work_zones._line_parts(found[0])[:1] or [None]
                if not cross or len(cross) < 2:
                    continue
                routed = point_along(cross, (found[1], found[2]), CROSS_STREET_OFFSET_M)
                out[index] = routed
                moved.append(
                    {
                        "index": index,
                        "asked": [round(lon, 6), round(lat, 6)],
                        "routed": routed,
                        "reason": RAIL_STREET,
                        "note": t(RAIL_STREET_NOTE),
                    }
                )
    except PlanCancelled:
        raise
    except Exception:  # noqa: BLE001 - the points stay where the rider put them
        logger.warning("a Mass Ride's points on rail streets could not be read", exc_info=True)
        return [list(p) for p in points], []
    return out, moved
