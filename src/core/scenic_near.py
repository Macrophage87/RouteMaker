"""The scenic roads near a point (v0.12.3; `routemaker.scenic`, `segment.scenic`).

The owner, 2026-10-25, of a towpath and rustic-roads ride: "The goal would be for a new user
to be able to make routes like this." A rider who asks an assistant for a ride "on rustic
roads" needs it to know which rustic roads are near: this lists them, each named road near
the point once, with its designations, its miles in reach, its stress mix and a point on it
to put a via point on, for the connector's `scenic_roads_near` tool (mcp/routemaker_mcp.py).

The ways come from the live segment table, the MAX_WAYS nearest designated ones; their names
from the router (`/locate`), one batched call, since the table keeps no names. Ways are
grouped by name, so two rustic roads meeting at a junction stay two rows and one road's
pieces (a gap in the designation, a stretch that is also a bike route) stay one. A
designation is a fact about the way, never a stress input.
"""

from __future__ import annotations

import logging
import math

from django.conf import settings
from django.db import OperationalError, connection, transaction

from pipeline.schema import SCENIC_COLUMN, validate_schema_name
from routemaker.scenic import SEPARATOR

from . import segment_info

logger = logging.getLogger(__name__)

METRES_PER_MILE = 1609.344
MAX_RADIUS_MI = 15.0
MAX_ROADS = 25
# The nearest designated ways read, each named by the router: enough for MAX_ROADS roads of
# a few ways each, few enough for one /locate call.
MAX_WAYS = 80
# A road with less than this in reach is left out (a bridge end, a corner clipped).
MIN_M = 150.0
# The read's own time limit: signed out and open to anyone, it must never hold a connection.
TIMEOUT_MS = 2000
# One /locate for every way's middle.
LOCATE_TIMEOUT_S = 6.0

_QUERY = """
WITH here AS (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS p)
SELECT s.osm_way_id,
       s.{column},
       s.stress_tier,
       ST_Length(s.geometry::geography) AS m,
       ST_AsText(ST_LineInterpolatePoint(s.geometry, 0.5)) AS mid,
       ST_AsText(ST_ClosestPoint(s.geometry, here.p)) AS nearest,
       ST_Distance(s.geometry::geography, here.p::geography) AS away_m
FROM {schema}.segment AS s, here
WHERE s.{column} IS NOT NULL
  AND (%(kind)s = '' OR s.{column} ILIKE '%%' || %(kind)s || '%%')
  AND s.geometry && ST_MakeEnvelope(
      %(lon)s - %(dlon)s, %(lat)s - %(dlat)s, %(lon)s + %(dlon)s, %(lat)s + %(dlat)s, 4326)
  AND ST_DWithin(s.geometry::geography, here.p::geography, %(radius_m)s)
ORDER BY away_m
LIMIT %(limit)s
"""


class TimedOut(Exception):
    """The read ran past TIMEOUT_MS."""


def _point(text: str) -> list[float]:
    lon, lat = text.removeprefix("POINT(").removesuffix(")").split()
    return [round(float(lon), 6), round(float(lat), 6)]


def names_of(ways: list[dict]) -> list[str | None]:
    """Each way's name from the router's edges of that way at its middle, one call for all;
    None where the router does not answer or names none."""
    from . import routing
    from .geocode import _ROUTE_REF

    if not ways:
        return []
    payload = {
        "locations": [
            {"lon": w["mid"][0], "lat": w["mid"][1], "radius": segment_info.LOCATE_RADIUS_M}
            for w in ways
        ],
        "costing": "bicycle",
        "verbose": True,
    }
    url = f"{settings.VALHALLA_UPSTREAMS['standard'].rstrip('/')}/locate"
    try:
        answer = routing._transport(url, payload, LOCATE_TIMEOUT_S)
    except (routing.RouterUnavailable, routing.RouterRefused):
        logger.warning("the scenic roads' names could not be read from the router")
        return [None] * len(ways)
    answer = answer if isinstance(answer, list) else []
    names: list[str | None] = []
    for way, location in zip(ways, answer + [None] * (len(ways) - len(answer)), strict=False):
        found = None
        for edge in (location or {}).get("edges") or []:
            info = edge.get("edge_info") or {}
            if info.get("way_id") != way["way"]:
                continue
            listed = [
                n.strip() for n in info.get("names") or [] if isinstance(n, str) and n.strip()
            ]
            if listed:
                found = next((n for n in listed if not _ROUTE_REF.match(n)), listed[0])
                break
        names.append(found)
    return names


def _read(schema: str, lon: float, lat: float, radius_m: float, kind: str) -> list[tuple]:
    params = {
        "lon": lon,
        "lat": lat,
        "dlat": radius_m / 111_320,
        "dlon": radius_m / (111_320 * math.cos(math.radians(lat))),
        "radius_m": radius_m,
        "kind": kind,
        "limit": MAX_WAYS,
    }
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            # Inside an outer transaction this block is a savepoint, whose release keeps a
            # local setting: put the caller's limit back, as routing.plan_cursor does.
            cursor.execute("SELECT current_setting('statement_timeout')")
            (before,) = cursor.fetchone()
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [str(TIMEOUT_MS)])
            cursor.execute(_QUERY.format(schema=schema, column=SCENIC_COLUMN), params)
            rows = cursor.fetchall()
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [before])
            return rows
    except OperationalError as error:
        if getattr(error.__cause__, "sqlstate", None) == "57014":  # query_canceled
            raise TimedOut(f"the scenic road read ran past {TIMEOUT_MS} ms") from error
        raise


def near(lon: float, lat: float, miles: float, kind: str = "") -> list[dict]:
    """The designated roads within `miles` (at most MAX_RADIUS_MI) of the point, nearest
    first: {road, designation, miles, lts_miles, lon_lat, nearest, away_mi}; only those whose
    designation holds `kind` ("rustic", "byway") where given. Empty where the live table has
    no scenic column (a table built before it). Raises TimedOut past TIMEOUT_MS."""
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not segment_info.has_columns(schema, SCENIC_COLUMN):
        return []
    radius_m = min(miles, MAX_RADIUS_MI) * METRES_PER_MILE
    ways = [
        {
            "way": way_id,
            "designations": [d.strip() for d in str(scenic).split(SEPARATOR.strip()) if d.strip()],
            "tier": tier,
            "m": m,
            "mid": _point(mid),
            "nearest": _point(nearest),
            "away_m": away_m,
        }
        for way_id, scenic, tier, m, mid, nearest, away_m in _read(
            schema, lon, lat, radius_m, kind.strip()
        )
    ]
    groups: dict[tuple, dict] = {}
    for way, name in zip(ways, names_of(ways), strict=True):
        # A named road is one row; an unnamed way is one with its designation's other
        # unnamed ways.
        key = ("name", name.casefold()) if name else ("unnamed", tuple(way["designations"]))
        group = groups.setdefault(
            key,
            {"road": name, "designations": [], "m": 0.0, "tiers": {}, "ways": []},
        )
        for designation in way["designations"]:
            if designation not in group["designations"]:
                group["designations"].append(designation)
        group["m"] += way["m"]
        label = "Avoid" if way["tier"] >= 5 else f"LTS {way['tier']}"
        group["tiers"][label] = group["tiers"].get(label, 0.0) + way["m"]
        group["ways"].append(way)
    rows = []
    for group in groups.values():
        if group["m"] < MIN_M:
            continue
        closest = min(group["ways"], key=lambda w: w["away_m"])
        longest = max(group["ways"], key=lambda w: w["m"])
        rows.append(
            {
                "road": group["road"],
                "designation": SEPARATOR.join(group["designations"]),
                "miles": round(group["m"] / METRES_PER_MILE, 1),
                "lts_miles": {
                    k: round(v / METRES_PER_MILE, 1)
                    for k, v in sorted(group["tiers"].items())
                    if v >= 0.05 * METRES_PER_MILE
                },
                "lon_lat": longest["mid"],
                "nearest": closest["nearest"],
                "away_mi": round(closest["away_m"] / METRES_PER_MILE, 1),
            }
        )
    rows.sort(key=lambda r: r["away_mi"])
    return rows[:MAX_ROADS]
