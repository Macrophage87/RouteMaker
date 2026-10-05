"""GET /tiles/mass/{z}/{x}/{y}.pbf: the Mass Ride map's capacity tiles.

The Mass Ride map colours roads by riders per minute (`rpm`, OWNER-DECISIONS 325-327,
387) and shows nothing else of the stress map: "Mass rides should mainly only show
capacity and federal land. Trails and PBLs aren't relevant here." (417, 417a). The
stress tiles cannot carry that at every zoom: at z12-13 they are the ride layer
(391), which holds only the long calm roads, and the owner asked for the busy roads'
capacity there too ("Busy roads should yes.", 415). So this is a tile set of its
own, which the front end reads only in Mass Ride mode (frontend/src/lib/mapStyle.ts,
`massSource`); the stress tiles and their z12-13 ride layer are unchanged.

What a tile holds: every public road with a capacity (the live table's
`mass_usable_width_m`, drawn as `rpm` exactly as the stress tiles draw it,
`stress_tiles.OPTIONAL_EXPRESSIONS["rpm"]`) with its `tier` (an Avoid stretch keeps
its own style, massStyle.js), and nothing else: no trail, no path, no alley. Only
inside the District of Columbia (418: "Grey out everywhere outside DC on that map too
as we don't support it yet."): each line is clipped to the District's boundary
(`DC_BOUNDARY_PATH`, OpenStreetMap's, written by scripts/build_dc_boundary.py), and a
tile that does not reach the District's box is empty. The map greys the rest out with
the same boundary.

Levels: z10-13 one feature per (tier, rpm), collected and simplified to the tile's
grid as the stress tiles' zoomed-out levels are; from z14 one feature per segment, as
the stress tiles' full level. The map asks for nothing past z14 (`STRESS_ZOOMS.max`),
so MAX_ZOOM is 14 and a deeper tile is empty.

On a table without the capacity column every tile is empty: the Mass Ride map then
shows no capacity. Caching is the stress tiles': the same `core.tile_cache` table,
keyed by this module's ETag (`W/"mass-..."`, never equal to a stress tag), every tile
over the District's box drawn ahead after each promotion (`tile_cache.predraw`), and
the same per-address limit and draw slots.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from django.db import OperationalError, connection, transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from pipeline.schema import (
    FACILITY_COLUMN,
    MAP_CLASS_COLUMN,
    MASS_WIDTH_COLUMN,
    MOTOR_ONLY_RULE,
    TRAIL_FACILITY,
)

from . import ratelimit, stress_tiles, tile_cache

LAYER = stress_tiles.LAYER
MIN_ZOOM = stress_tiles.MIN_ZOOM
# The deepest tile the map asks for (`STRESS_ZOOMS.max` in mapStyle.ts); z15-16 are drawn
# from the z14 tile, so this set has none of its own.
MAX_ZOOM = 14
# From here one feature per segment, as the stress tiles' full level.
SEGMENTS_MIN_ZOOM = stress_tiles.QUIET_STREETS_MIN_ZOOM

# Bumped whenever what a mass tile holds changes for the same table and boundary.
# 1: the first (OWNER-DECISIONS 415, 417, 418).
FORMAT_VERSION = 1

DC_BOUNDARY_PATH = Path(__file__).resolve().parent / "geodata" / "dc-boundary.geojson"


@lru_cache(maxsize=1)
def dc_boundary() -> tuple[str, tuple[float, float, float, float], str]:
    """(the District's geometry as GeoJSON text, its box (west, south, east, north),
    a short digest of the file, which the ETag carries so a new boundary is new tiles)."""
    raw = DC_BOUNDARY_PATH.read_bytes()
    geometry = json.loads(raw)["geometry"]
    xs: list[float] = []
    ys: list[float] = []
    for polygon in geometry["coordinates"]:
        for ring in polygon:
            xs.extend(p[0] for p in ring)
            ys.extend(p[1] for p in ring)
    box = (min(xs), min(ys), max(xs), max(ys))
    return json.dumps(geometry), box, hashlib.sha256(raw).hexdigest()[:6]


def outside_dc(z: int, x: int, y: int) -> bool:
    """Whether the tile misses the District's box altogether."""
    west, south, east, north = stress_tiles.tile_bounds(z, x, y)
    d_west, d_south, d_east, d_north = dc_boundary()[1]
    return east < d_west or west > d_east or north < d_south or south > d_north


def tiles_over_dc(max_zoom: int = MAX_ZOOM) -> list[tuple[int, int, int]]:
    """Every tile from MIN_ZOOM to `max_zoom` that the District's box reaches, in zoom
    order: what the pre-draw draws."""
    west, south, east, north = dc_boundary()[1]
    tiles = []
    for z in range(MIN_ZOOM, max_zoom + 1):
        x0, y0 = tile_cache.tile_index(west, north, z)
        x1, y1 = tile_cache.tile_index(east, south, z)
        tiles.extend(
            (z, x, y)
            for x in range(x0, x1 + 1)
            for y in range(y0, y1 + 1)
            if not outside_dc(z, x, y)
        )
    return tiles


# A line wholly inside the District is kept as it is; one that crosses its edge is cut
# at it, and only its lines are kept (an edge can leave a point).
_SQL = """
WITH bounds AS (SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS env),
dc AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(dc)s), 4326) AS g),
picked AS (
    SELECT {columns},
           CASE WHEN ST_CoveredBy(s.geometry, dc.g) THEN s.geometry
                ELSE ST_CollectionExtract(ST_Intersection(s.geometry, dc.g), 2) END AS clipped
    FROM {table} AS s, dc
    WHERE s.geometry && ST_Transform(
              ST_TileEnvelope(%(z)s, %(x)s, %(y)s, margin => %(margin)s), 4326)
      AND ST_Intersects(s.geometry, dc.g)
      AND {where}
),
features AS (
    SELECT {names}, {geom} AS geom
    FROM picked, bounds
    WHERE NOT ST_IsEmpty(picked.clipped)
    {group_by}
)
SELECT '{table}'::regclass::oid,
       (SELECT ST_AsMVT(features.*, '{layer}', %(extent)s, 'geom') FROM features
        WHERE features.geom IS NOT NULL)
"""

_MERGED_GEOM = (
    "ST_AsMVTGeom(ST_Simplify(ST_Collect(ST_Transform(picked.clipped, 3857)), %(unit)s), "
    "bounds.env, %(extent)s, %(buffer)s, true)"
)
_SEGMENT_GEOM = (
    "ST_AsMVTGeom(ST_Transform(picked.clipped, 3857), bounds.env, %(extent)s, %(buffer)s, true)"
)


def tile_sql(z: int, optional: frozenset[str]) -> str:
    """The query for a tile at `z` on a table with the `optional` columns (which must
    include the capacity column)."""
    carried = {
        "tier": "s.stress_tier",
        "rpm": stress_tiles.OPTIONAL_EXPRESSIONS["rpm"],
    }
    where = [f"s.{MASS_WIDTH_COLUMN} IS NOT NULL", "s.is_trail_class IS NOT TRUE"]
    if FACILITY_COLUMN in optional:
        where.append(f"s.{FACILITY_COLUMN} IS DISTINCT FROM '{TRAIL_FACILITY}'")
    if MAP_CLASS_COLUMN in optional:
        where.append(f"s.{MAP_CLASS_COLUMN} = 'road'")
    else:
        where.append(f"NOT {MOTOR_ONLY_RULE}")
    merged = z < SEGMENTS_MIN_ZOOM
    names = ", ".join(carried)
    return _SQL.format(
        table=stress_tiles._table(),
        columns=", ".join(f"{expression} AS {name}" for name, expression in carried.items()),
        names=names,
        where=" AND ".join(where),
        geom=_MERGED_GEOM if merged else _SEGMENT_GEOM,
        group_by=f"GROUP BY {names}, bounds.env" if merged else "",
        layer=LAYER,
    )


def render(
    z: int,
    x: int,
    y: int,
    optional: frozenset[str] = frozenset(),
    timeout_ms: int | None = None,
) -> tuple[int, bytes]:
    """(the live table's oid, the tile's bytes), under a `timeout_ms` statement timeout
    (stress_tiles.DRAW_TIMEOUT_MS if none is given). Raises stress_tiles.DrawTimedOut."""
    if timeout_ms is None:
        timeout_ms = stress_tiles.DRAW_TIMEOUT_MS
    merged = z < SEGMENTS_MIN_ZOOM
    extent, buffer = 4096, (32 if merged else 64)
    params = {
        "z": z,
        "x": x,
        "y": y,
        "dc": dc_boundary()[0],
        "extent": extent,
        "buffer": buffer,
        "margin": buffer / extent,
        "unit": stress_tiles.WORLD_M / 2**z / extent,
    }
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [str(timeout_ms)])
            cursor.execute(tile_sql(z, optional), params)
            oid, tile = cursor.fetchone()
    except OperationalError as error:
        if getattr(error.__cause__, "sqlstate", None) == "57014":  # query_canceled
            raise stress_tiles.DrawTimedOut(
                f"mass tile {z}/{x}/{y} ran past {timeout_ms} ms"
            ) from error
        raise
    return oid, bytes(tile or b"")


# The columns that change what a mass tile holds, named by the stress tiles' letters.
TAG_COLUMNS = (FACILITY_COLUMN, MAP_CLASS_COLUMN, MASS_WIDTH_COLUMN)


def etag_for(oid: int, optional: frozenset[str] = frozenset()) -> str:
    """Weak, as the stress tiles' (stress_tiles.etag_for), and never equal to one: `mass-`,
    the table's oid, the letters of the columns it reads, the boundary's digest and this
    format. `W/"mass-` and a ten-digit oid, `+fmw`, `-` and six hex digits, `-v1"`: 33
    characters, under the cache's 64."""
    carried = "".join(stress_tiles.ETAG_LETTERS[c] for c in sorted(optional) if c in TAG_COLUMNS)
    digest = dc_boundary()[2]
    return f'W/"mass-{oid}{"+" + carried if carried else ""}-{digest}-v{FORMAT_VERSION}"'


@require_http_methods(["GET", "HEAD"])
@ratelimit.rate_limited(ratelimit.TILES)
def mass_tile(request, z: int, x: int, y: int) -> HttpResponse:
    if z > stress_tiles.MAX_ADDRESSABLE_ZOOM or x >= 2**z or y >= 2**z:
        response = JsonResponse({"error": "not a tile address"}, status=400)
        response["Cache-Control"] = "no-store"
        return response
    if not MIN_ZOOM <= z <= MAX_ZOOM or outside_dc(z, x, y):
        return stress_tiles._tile_response(b"")
    oid, optional = stress_tiles.live_table()
    if oid is None:
        response = JsonResponse({"error": "no stress data has been built yet"}, status=404)
        response["Cache-Control"] = "no-store"
        return response
    etag = etag_for(oid, optional)
    if MASS_WIDTH_COLUMN not in optional:
        # A table from before the capacity column: there is nothing to draw.
        return stress_tiles._tile_response(b"", etag=etag)
    if stress_tiles._matches(request, etag):
        return stress_tiles._tile_response(b"", status=304, etag=etag)
    cached = tile_cache.get(etag, z, x, y)
    if cached is not None:
        return stress_tiles._tile_response(cached, etag=etag)
    held, refusal = ratelimit.acquire(request, ratelimit.TILES_IN_FLIGHT)
    if refusal is not None:
        refusal["Cache-Control"] = "no-store"
        return refusal
    try:
        try:
            drawn_oid, body = render(z, x, y, optional)
        except stress_tiles.DrawTimedOut:
            response = JsonResponse(
                {"error": "This part of the Mass Ride map is taking too long; try again shortly."},
                status=503,
            )
            response["Retry-After"] = str(stress_tiles.RETRY_AFTER_S)
            response["Cache-Control"] = "no-store"
            return response
    finally:
        ratelimit.release(held)
    if drawn_oid == oid:
        tile_cache.put(etag, z, x, y, body)
    return stress_tiles._tile_response(body, etag=etag_for(drawn_oid, optional))
