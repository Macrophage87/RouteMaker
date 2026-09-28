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
from typing import NamedTuple

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
    """Delete stale rows, and the oldest on-request tiles past `max_bytes`.

    "Stale" is every version but `version`, which is right only while one
    version is being served. Two races make it wrong for a moment, and both
    only cost draws, never a wrong tile (a row is only ever read back under
    its own version): a request that drew from the old table just before a
    promotion and evicts in its `put` just after it deletes the new table's
    fresh rows (a 1-in-EVICT_EVERY chance per such request); and two api
    images with different FORMAT_VERSIONs serving side by side - a rolling
    deploy - delete each other's rows until the old one is gone. The next
    pre-draw, or first requests, fill them again.
    """
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


class Predrawn(NamedTuple):
    drawn: int
    cached: int
    # Tiles that ran past PREDRAW_TIMEOUT_MS and were skipped.
    timed_out: int = 0
    # Tiles not reached because the budget was spent.
    left: int = 0

    def summary(self) -> str:
        """For a run row: what was drawn, and what was not."""
        text = f"{self.drawn} drawn, {self.cached} already there"
        if self.timed_out:
            text += f", {self.timed_out} timed out"
        if self.left:
            text += f"; stopped at its time budget with {self.left} left"
        return text


# The pre-draw's default time budget, well past what a whole box takes (56 s on
# a quiet host, 135-216 s on a loaded one, with or without the overview index).
PREDRAW_BUDGET_S = 1800.0


def predraw(max_zoom: int = PREDRAW_MAX_ZOOM, budget_s: float = PREDRAW_BUDGET_S) -> Predrawn:
    """Draw every z10-`max_zoom` tile of the live table not yet cached.

    Stops when `budget_s` is spent, counting what it did not reach, which is
    drawn on first request instead. Each draw runs under
    `stress_tiles.PREDRAW_TIMEOUT_MS`; one that runs past it is skipped and
    counted, and the pre-draw goes on.
    """
    from . import stress_tiles

    oid, optional = stress_tiles.live_table()
    if oid is None:
        return Predrawn(0, 0)
    version = stress_tiles.etag_for(oid, optional)
    evict(version)
    deadline = time.monotonic() + budget_s
    by_zoom = _tiles_with_segments(stress_tiles._table(), max_zoom)
    tiles = [
        (z, x, y)
        for z in sorted(by_zoom)
        for x, y in sorted(by_zoom[z])
        if not stress_tiles.outside_coverage(z, x, y)
    ]
    drawn = cached = timed_out = 0
    for done, (z, x, y) in enumerate(tiles):
        if get(version, z, x, y) is not None:
            cached += 1
            continue
        if time.monotonic() > deadline:
            left = len(tiles) - done
            logger.warning(
                "stress tile pre-draw stopped at its %ss budget: %d drawn, %d left",
                budget_s,
                drawn,
                left,
            )
            return Predrawn(drawn, cached, timed_out, left)
        try:
            drawn_oid, body = stress_tiles.render(
                z, x, y, optional, timeout_ms=stress_tiles.PREDRAW_TIMEOUT_MS
            )
        except stress_tiles.DrawTimedOut:
            logger.warning("stress tile %d/%d/%d timed out in the pre-draw", z, x, y)
            timed_out += 1
            continue
        if drawn_oid != oid:
            # A promotion landed mid-way; the next pre-draw is for that table.
            return Predrawn(drawn, cached, timed_out, len(tiles) - done)
        put(version, z, x, y, body)
        drawn += 1
    return Predrawn(drawn, cached, timed_out)
