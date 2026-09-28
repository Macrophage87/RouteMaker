"""The stress tile cache: a drawn tile is kept, and z10-13 are drawn ahead.

Revision round 2 (ops review, blocker): with no cache, every tile request drew
from the segment table, a cold z10 draw took seconds, and one address inside its
600 tiles a minute held every gunicorn worker for 50 s - routing and /healthz
with them. The tiles change only when a promotion replaces the live table, so
a drawn tile is good until then.

- Where: the `stress_tile_cache` table (`core.models.StressTileCache`), keyed on
  the tile's ETag (the live table's oid, its optional columns and the tile
  format) and z/x/y. A table rather than files under DATA_ROOT, because the api
  already reaches the database from every worker, a lookup is one indexed
  read, and a new file tree would need its own writer, volume and Caddy route.
  It is excluded from the nightly dump and refills itself.
- What is kept for good: z10-13 over the coverage box, drawn ahead by
  `predraw` after every promotion (the weekly rebuild calls it; so does
  `manage.py predraw_stress_tiles`), about 3,000 tiles and 34 MB on the first
  promoted build. These are the expensive ones: a z10 tile holds a whole
  city's segments.
- What is kept while there is room: a z14-16 tile the api draws on request,
  up to `MAX_BYTES` of them; past that the oldest go first.
- Stale rows (another table, another format) are deleted by `predraw` and by
  every eviction.
"""

from __future__ import annotations

import logging
import random
import time

from django.db import connection

logger = logging.getLogger(__name__)

# The zooms drawn ahead and kept for good.
PREDRAW_MAX_ZOOM = 13

# The byte budget for tiles drawn on request past PREDRAW_MAX_ZOOM. A z14 tile
# over downtown DC is about 125 KB and a suburban one a few KB; 256 MB holds
# every z14 tile in the box several times over.
MAX_BYTES = 256 * 1024 * 1024

# One insert in this many runs the eviction, so its scan is not paid per tile.
EVICT_EVERY = 64


def get(version: str, z: int, x: int, y: int) -> bytes | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT body FROM stress_tile_cache "
            "WHERE version = %s AND z = %s AND x = %s AND y = %s",
            [version, z, x, y],
        )
        row = cursor.fetchone()
    return None if row is None else bytes(row[0])


def put(version: str, z: int, x: int, y: int, body: bytes) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO stress_tile_cache (version, z, x, y, body, created_at) "
            "VALUES (%s, %s, %s, %s, %s, clock_timestamp()) "
            "ON CONFLICT (version, z, x, y) DO NOTHING",
            [version, z, x, y, body],
        )
    if z > PREDRAW_MAX_ZOOM and random.randrange(EVICT_EVERY) == 0:  # noqa: S311
        evict(version)


def evict(version: str, max_bytes: int = MAX_BYTES) -> int:
    """Delete stale rows, and the oldest on-request tiles past `max_bytes`."""
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM stress_tile_cache WHERE version <> %s", [version])
        stale = cursor.rowcount
        cursor.execute(
            """
            DELETE FROM stress_tile_cache WHERE id IN (
                SELECT id FROM (
                    SELECT id, sum(octet_length(body)) OVER (ORDER BY created_at DESC, id DESC)
                        AS kept
                    FROM stress_tile_cache WHERE version = %s AND z > %s
                ) AS t WHERE t.kept > %s
            )
            """,
            [version, PREDRAW_MAX_ZOOM, max_bytes],
        )
        return stale + cursor.rowcount


def _tiles_with_segments(table: str, max_zoom: int) -> dict[int, set[tuple[int, int]]]:
    """Every tile from z10 to `max_zoom` holding a segment's end, by zoom.

    Read once at `max_zoom` and halved for each zoom out. A tile that a segment
    only crosses is not listed; it is drawn on first request like any other.
    """
    n = 2**max_zoom
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH ends AS (
                SELECT ST_StartPoint(geometry) AS p FROM {table}
                UNION ALL SELECT ST_EndPoint(geometry) FROM {table}
            )
            SELECT DISTINCT
                floor((ST_X(p) + 180) / 360 * %(n)s)::int,
                floor((1 - ln(tan(radians(ST_Y(p))) + 1 / cos(radians(ST_Y(p)))) / pi()) / 2
                      * %(n)s)::int
            FROM ends
            """,
            {"n": n},
        )
        deepest = set(cursor.fetchall())
    from .stress_tiles import MIN_ZOOM

    tiles = {max_zoom: deepest}
    for z in range(max_zoom - 1, MIN_ZOOM - 1, -1):
        tiles[z] = {(x >> 1, y >> 1) for x, y in tiles[z + 1]}
    return tiles


def predraw(max_zoom: int = PREDRAW_MAX_ZOOM, budget_s: float = 1800.0) -> tuple[int, int]:
    """Draw every z10-`max_zoom` tile of the live table not yet cached.

    Returns (drawn, already cached). Stops, logging, when `budget_s` is spent;
    what it did not reach is drawn on first request. Each draw runs under
    `stress_tiles.PREDRAW_TIMEOUT_MS`, so a swap waiting for its lock behind
    one waits at most that long.
    """
    from . import stress_tiles

    oid, optional = stress_tiles.live_table()
    if oid is None:
        return 0, 0
    version = stress_tiles.etag_for(oid, optional)
    evict(version)
    deadline = time.monotonic() + budget_s
    drawn = cached = 0
    by_zoom = _tiles_with_segments(stress_tiles._table(), max_zoom)
    for z in sorted(by_zoom):
        for x, y in sorted(by_zoom[z]):
            if stress_tiles.outside_coverage(z, x, y):
                continue
            if get(version, z, x, y) is not None:
                cached += 1
                continue
            if time.monotonic() > deadline:
                logger.warning(
                    "stress tile pre-draw stopped at its %ss budget: %d drawn", budget_s, drawn
                )
                return drawn, cached
            try:
                drawn_oid, body = stress_tiles.render(
                    z, x, y, optional, timeout_ms=stress_tiles.PREDRAW_TIMEOUT_MS
                )
            except stress_tiles.DrawTimedOut:
                logger.warning("stress tile %d/%d/%d timed out in the pre-draw", z, x, y)
                continue
            if drawn_oid != oid:
                # A promotion landed mid-way; the next pre-draw is for that table.
                return drawn, cached
            put(version, z, x, y, body)
            drawn += 1
    return drawn, cached
