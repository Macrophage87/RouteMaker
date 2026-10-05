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

Border roads count as inside (420: "Border roads are inside DC"). The boundary is
simplified to about 30 ft and Western, Eastern and Southern Ave run along it, so a line
wholly within DC_EDGE_TOLERANCE_M of the District (the simplification's error plus a
road's half-width) is drawn whole; any other line is cut at the boundary itself, so a
Maryland or Virginia street that meets the line gets no stub. The drawn edge (the map's
grey mask) does not move. The planner's outside-DC notice uses the same tolerance
(frontend/src/lib/dcBoundary.ts, DC_EDGE_TOLERANCE_M; a test holds the two equal).

Which bands each zoom holds (421, 422: "Maybe focus on higher capacity roads at large
zooms", then "The focus option sounds good." and "Looks like a good start!"):
- z10-11: Wide open only (WIDE_OPEN_RPM and up), and only a block that is part of at
  least WIDE_RUN_MI of continuous Wide open road, so an isolated block that passes 200
  on a turn lane or a wide approach is not drawn as a speck;
- z12-13: Good and Wide open (GOOD_RPM and up);
- z14 on: every band.
A stretch marked Avoid (tier 5) is drawn at every zoom, whatever its capacity: it is a
warning, not a band. massStyle.js gives each band the same first zoom (`minzoom`), and
the legend says in words which bands show at the zoom the map is at.

The run is worked out here, at tile time, not in the pipeline: the capacity a band
reads is the tiles' own `rpm` (rounded down to ten, as the map's band edges are), the
District's Wide open road is small (about 74 mi, 120 km), and only the few z10-11 tiles
over the District need it, all drawn ahead after each promotion. So no column, no
schema change and no rebuild: a run is the total length of Wide open lines (clipped as
drawn) that touch end to end (`ST_ClusterDBSCAN` at distance 0), found over the whole
District for every tile, so a tile's edge never cuts a run short.

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
    METRES_PER_MILE,
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
# 2: the bands by zoom and the Wide open run (421, 422); border roads inside (420).
FORMAT_VERSION = 2

# The settings for which bands each zoom holds (421, 422). The band edges are massStyle.js's
# MASS_BANDS (`min`), and its `minzoom`s are these zooms; tests/test_mass_tiles.py holds
# them equal.
WIDE_OPEN_RPM = 200
GOOD_RPM = 120
GOOD_MIN_ZOOM = 12
EVERY_BAND_MIN_ZOOM = SEGMENTS_MIN_ZOOM
# At z10-11 a Wide open block shows only as part of this much continuous Wide open road
# (422, provisional: the owner may tune it after seeing it on the live map).
WIDE_RUN_MI = 0.5
WIDE_RUN_M = round(WIDE_RUN_MI * METRES_PER_MILE)

# How near the District a line may lie and still count as inside it (420). The boundary
# is simplified to 0.0001 degree (up to 11.1 m, 36 ft, off the true line) and snapped to a
# 1e-5 degree grid (0.6 m more); a road's half-width on top, taken as 10 m (33 ft), the
# half of a four-lane road with parking. Measured on the 2026-10-03 build: every vertex of
# Western, Eastern and Southern Ave that falls outside the simplified boundary is within
# 19.5 m (64 ft) of it.
DC_EDGE_TOLERANCE_M = 22
# The same in degrees, generously (a degree of longitude at the District is about 86.7 km),
# for the box a tile is tested against.
_EDGE_PAD_DEG = DC_EDGE_TOLERANCE_M / 80_000


def min_rpm_for(z: int) -> int | None:
    """The lowest riders per minute a tile at `z` holds, or None for every band (421)."""
    if z < GOOD_MIN_ZOOM:
        return WIDE_OPEN_RPM
    if z < EVERY_BAND_MIN_ZOOM:
        return GOOD_RPM
    return None


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


def _near_box() -> tuple[float, float, float, float]:
    """The District's box grown by the border tolerance (420)."""
    west, south, east, north = dc_boundary()[1]
    pad = _EDGE_PAD_DEG
    return west - pad, south - pad, east + pad, north + pad


def outside_dc(z: int, x: int, y: int) -> bool:
    """Whether the tile misses the District's box, grown by the border tolerance, altogether."""
    west, south, east, north = stress_tiles.tile_bounds(z, x, y)
    d_west, d_south, d_east, d_north = _near_box()
    return east < d_west or west > d_east or north < d_south or south > d_north


def tiles_over_dc(max_zoom: int = MAX_ZOOM) -> list[tuple[int, int, int]]:
    """Every tile from MIN_ZOOM to `max_zoom` that the District's box reaches, in zoom
    order: what the pre-draw draws."""
    west, south, east, north = _near_box()
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


# A line wholly inside the District, or wholly within the border tolerance of it (420), is
# kept as it is; any other line that reaches it is cut at the boundary itself, and only
# its lines are kept (an edge can leave a point). UTM 18N (EPSG:26918) is the District's
# own zone, for a buffer in metres.
_CLIPPED = (
    "CASE WHEN ST_CoveredBy(s.geometry, dc.near) THEN s.geometry "
    "ELSE ST_CollectionExtract(ST_Intersection(s.geometry, dc.g), 2) END"
)

_SQL = """
WITH bounds AS (SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS env),
dc AS (
    SELECT b.g, ST_Transform(ST_Buffer(ST_Transform(b.g, 26918), %(tolerance)s), 4326) AS near
    FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(dc)s), 4326) AS g) AS b
),
{runs}
picked AS (
    SELECT {columns}, {clipped} AS clipped
    FROM {table} AS s, dc
    WHERE s.geometry && ST_Transform(
              ST_TileEnvelope(%(z)s, %(x)s, %(y)s, margin => %(margin)s), 4326)
      AND ST_Intersects(s.geometry, dc.near)
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

# z10-11 (422): the Wide open lines of the whole District, clipped as drawn, joined into
# runs where they share a vertex (through junctions, 423; not a bridge over a road), and the
# ids of those in a run of at least WIDE_RUN_M.
_RUNS = """
wide AS (
    SELECT s.id, {clipped} AS clipped
    FROM {table} AS s, dc
    WHERE ST_Intersects(s.geometry, dc.near)
      AND {where}
      AND {rpm} >= %(wide_rpm)s
      AND s.stress_tier <> 5
),
clustered AS (
    -- Joined where they share a vertex (OSM's shared node), not wherever they touch: a
    -- bridge crosses the road under it with no node in common, and the two are not one
    -- run (REBUILD-BUNDLE correctness review, nit 5). A run goes on through a junction
    -- (OWNER-DECISIONS 423), which is a shared node.
    SELECT id, clipped, ST_ClusterDBSCAN(ST_Points(clipped), 0, 1) OVER () AS run
    FROM wide
    WHERE NOT ST_IsEmpty(clipped)
),
in_run AS (
    SELECT id FROM clustered
    WHERE run IN (
        SELECT run FROM clustered GROUP BY run
        HAVING sum(ST_Length(clipped::geography)) >= %(run_m)s
    )
),
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
    table = stress_tiles._table()
    banded = list(where)
    runs = ""
    min_rpm = min_rpm_for(z)
    if min_rpm == WIDE_OPEN_RPM:
        # Wide open in a long enough run, or Avoid (422).
        runs = _RUNS.format(
            clipped=_CLIPPED, table=table, where=" AND ".join(where), rpm=carried["rpm"]
        )
        banded.append("(s.stress_tier = 5 OR s.id IN (SELECT id FROM in_run))")
    elif min_rpm is not None:
        banded.append(f"(s.stress_tier = 5 OR {carried['rpm']} >= {min_rpm})")
    merged = z < SEGMENTS_MIN_ZOOM
    names = ", ".join(carried)
    return _SQL.format(
        table=table,
        runs=runs,
        clipped=_CLIPPED,
        columns=", ".join(f"{expression} AS {name}" for name, expression in carried.items()),
        names=names,
        where=" AND ".join(banded),
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
        "tolerance": DC_EDGE_TOLERANCE_M,
        "wide_rpm": WIDE_OPEN_RPM,
        "run_m": WIDE_RUN_M,
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
    format. `W/"mass-` and a ten-digit oid, `+fmw`, `-` and six hex digits, `-v2"`: 33
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
