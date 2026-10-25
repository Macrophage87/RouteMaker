"""The scenic roads near a point (v0.12.3; `routemaker.scenic`, `segment.scenic`).

The owner, 2026-10-25, of a towpath and rustic-roads ride: "The goal would be for a new user
to be able to make routes like this." A rider who asks an assistant for a ride "on rustic
roads" needs it to know which rustic roads are near: this lists them, each designated road
near the point once, with its miles in reach, its stress mix and a point on it to put a via
point on, for the connector's `scenic_roads_near` tool (mcp/routemaker_mcp.py).

The ways come from the live segment table; their names from the router (`/locate`), one
batched call, since the table keeps no names. A designation is a fact about the way, never
a stress input.
"""

from __future__ import annotations

import logging

from django.conf import settings

from pipeline.schema import SCENIC_COLUMN, validate_schema_name

from . import segment_info

logger = logging.getLogger(__name__)

METRES_PER_MILE = 1609.344
MAX_RADIUS_MI = 15.0
MAX_ROADS = 25
# Pieces of one designation this close (degrees, about 60 m) are one road.
CLUSTER_EPS_DEG = 0.0006
# A road with less than this in reach is left out (a bridge end, a corner clipped).
MIN_M = 150.0

_QUERY = """
WITH here AS (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS p),
near AS (
    SELECT s.osm_way_id, s.{column} AS designation, s.stress_tier AS tier, s.geometry,
           ST_Length(s.geometry::geography) AS m
    FROM {schema}.segment AS s, here
    WHERE s.{column} IS NOT NULL
      AND s.geometry && ST_Expand(here.p, %(deg)s)
      AND ST_DWithin(s.geometry::geography, here.p::geography, %(radius_m)s)
),
grouped AS (
    SELECT *, ST_ClusterDBSCAN(geometry, %(eps)s, 1) OVER (PARTITION BY designation) AS cid
    FROM near
)
SELECT g.designation,
       sum(g.m) AS m,
       array_agg(g.tier ORDER BY g.tier) AS tiers,
       array_agg(g.m ORDER BY g.tier) AS tier_m,
       (array_agg(g.osm_way_id ORDER BY g.m DESC))[1] AS way_id,
       ST_AsText((array_agg(ST_LineInterpolatePoint(g.geometry, 0.5) ORDER BY g.m DESC))[1])
           AS mid,
       ST_AsText(ST_ClosestPoint(ST_Collect(g.geometry), (SELECT p FROM here))) AS nearest,
       min(ST_Distance(g.geometry::geography, (SELECT p FROM here)::geography)) AS away_m
FROM grouped AS g
GROUP BY g.designation, g.cid
HAVING sum(g.m) >= %(min_m)s
ORDER BY away_m
LIMIT %(limit)s
"""


def _point(text: str) -> list[float]:
    lon, lat = text.removeprefix("POINT(").removesuffix(")").split()
    return [round(float(lon), 6), round(float(lat), 6)]


def _names(rows: list[dict]) -> list[str | None]:
    """Each road's name from the router's edges at its middle, one call for all; None where
    the router does not answer or names none."""
    from . import routing
    from .geocode import _ROUTE_REF

    if not rows:
        return []
    payload = {
        "locations": [
            {"lon": r["lon_lat"][0], "lat": r["lon_lat"][1], "radius": segment_info.LOCATE_RADIUS_M}
            for r in rows
        ],
        "costing": "bicycle",
        "verbose": True,
    }
    url = f"{settings.VALHALLA_UPSTREAMS['standard'].rstrip('/')}/locate"
    try:
        answer = routing._transport(url, payload, segment_info.LOCATE_TIMEOUT_S)
    except (routing.RouterUnavailable, routing.RouterRefused):
        logger.warning("the scenic roads' names could not be read from the router")
        return [None] * len(rows)
    names: list[str | None] = []
    for row, location in zip(rows, answer if isinstance(answer, list) else [], strict=False):
        found = None
        edges = (location or {}).get("edges") or []
        for edge in sorted(
            edges, key=lambda e: (e.get("edge_info") or {}).get("way_id") != row["_way"]
        ):
            info = edge.get("edge_info") or {}
            listed = [
                n.strip() for n in info.get("names") or [] if isinstance(n, str) and n.strip()
            ]
            if listed:
                found = next((n for n in listed if not _ROUTE_REF.match(n)), listed[0])
                break
        names.append(found)
    return names + [None] * (len(rows) - len(names))


def near(lon: float, lat: float, miles: float) -> list[dict]:
    """The designated roads within `miles` (at most MAX_RADIUS_MI) of the point, nearest
    first: {road, designation, miles, lts_miles, lon_lat, nearest, away_mi}. Empty where the
    live table has no scenic column (a table built before it)."""
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not segment_info.has_columns(schema, SCENIC_COLUMN):
        return []
    radius_m = min(miles, MAX_RADIUS_MI) * METRES_PER_MILE
    from .routing import plan_cursor

    with plan_cursor() as cursor:
        cursor.execute(
            _QUERY.format(schema=schema, column=SCENIC_COLUMN),
            {
                "lon": lon,
                "lat": lat,
                # The bounding box in degrees, wide enough at this latitude (1 degree of
                # longitude is about 0.77 of one of latitude at 39.5 N).
                "deg": radius_m / 111_000 / 0.75,
                "radius_m": radius_m,
                "eps": CLUSTER_EPS_DEG,
                "min_m": MIN_M,
                "limit": MAX_ROADS,
            },
        )
        found = cursor.fetchall()
    rows = []
    for designation, metres, tiers, tier_m, way_id, mid, nearest, away_m in found:
        by_tier: dict[str, float] = {}
        for tier, m in zip(tiers, tier_m, strict=True):
            key = "Avoid" if tier >= 5 else f"LTS {tier}"
            by_tier[key] = by_tier.get(key, 0.0) + m
        rows.append(
            {
                "designation": designation,
                "miles": round(metres / METRES_PER_MILE, 1),
                "lts_miles": {
                    k: round(v / METRES_PER_MILE, 1)
                    for k, v in sorted(by_tier.items())
                    if v >= 0.05 * METRES_PER_MILE
                },
                "lon_lat": _point(mid),
                "nearest": _point(nearest),
                "away_mi": round(away_m / METRES_PER_MILE, 1),
                "_way": way_id,
            }
        )
    for row, name in zip(rows, _names(rows), strict=True):
        row["road"] = name
        del row["_way"]
    return rows
