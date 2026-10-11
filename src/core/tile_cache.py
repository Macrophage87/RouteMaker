"""The stress tile cache: a drawn tile is kept, and every tile the map asks
for is drawn ahead.

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
- What is kept for good: every z10-14 tile over the coverage box, drawn ahead
  by `predraw` after every promotion (the weekly rebuild calls it; so does
  `manage.py predraw_stress_tiles`). The map asks for nothing past z14 (it
  draws z15-16 from the z14 tile), so once the pre-draw has run no tile the
  map asks for is drawn on request. The owner, 2026-09-28: "It takes a very
  long time to load those roads.", and where: "Zoomed in (street level)"
  (OWNER-DECISIONS 63) - a cold z14 tile took 1.4 s to draw, through the
  api's one draw slot, and a street-level screen 20-30 s.
- What is kept while there is room: a z15-16 tile the api draws on request,
  up to `MAX_BYTES` of them; past that the oldest go first.
- Stale rows (another table, another format) are deleted by `predraw` and by
  every eviction.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

# The zooms drawn ahead and kept for good: every one the map asks for
# (`STRESS_ZOOMS.max` in the front end's mapStyle.ts, which a test holds equal).
PREDRAW_MAX_ZOOM = 14

# The byte budget for tiles drawn on request past PREDRAW_MAX_ZOOM, which the
# map does not ask for.
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


def put(version: str, z: int, x: int, y: int, body: bytes, also_keep: tuple[str, ...] = ()) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO stress_tile_cache (version, z, x, y, body, created_at) "
            "VALUES (%s, %s, %s, %s, %s, clock_timestamp()) "
            "ON CONFLICT (version, z, x, y) DO NOTHING",
            [version, z, x, y, body],
        )
    if z > PREDRAW_MAX_ZOOM and random.randrange(EVICT_EVERY) == 0:  # noqa: S311
        evict(version, also_keep=also_keep)


def evict(version: str, max_bytes: int = MAX_BYTES, also_keep: tuple[str, ...] = ()) -> int:
    """Delete stale rows, and the oldest on-request tiles past `max_bytes`.

    "Stale" is every version but `version` and `also_keep` (the Mass Ride tiles' tag for
    the same table, core.mass_tiles, which shares this cache), which is right only while one
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
        cursor.execute(
            "DELETE FROM stress_tile_cache WHERE NOT version = ANY(%s)", [[version, *also_keep]]
        )
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


def covering_tiles(
    bbox: tuple[float, float, float, float], margin: int = 1
) -> list[tuple[int, int, int]]:
    """The (z, x, y) of every tile from MIN_ZOOM to MAX_ZOOM that a box reaches, with
    `margin` tiles more on every side: a feature near a tile's edge is drawn in the
    neighbour's buffer too."""
    from .stress_tiles import MAX_ZOOM, MIN_ZOOM

    west, south, east, north = bbox
    tiles = []
    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        x0, y0 = tile_index(west, north, z)
        x1, y1 = tile_index(east, south, z)
        last = 2**z - 1
        tiles.extend(
            (z, x, y)
            for x in range(max(0, x0 - margin), min(last, x1 + margin) + 1)
            for y in range(max(0, y0 - margin), min(last, y1 + margin) + 1)
        )
    return tiles


def rekey_after_edit(
    bbox: tuple[float, float, float, float] | None, versions: dict[str, str]
) -> int:
    """After a road-panel edit: delete the cached tiles that cover `bbox` under each old
    version, and re-key every other cached tile of it to the new one, so the cache stays
    warm and only the tiles the edit can have changed are drawn again. `versions` maps an
    old tag to its new tag (the stress tiles' and the Mass Ride tiles'). Returns how many
    tiles were deleted."""
    covering = covering_tiles(bbox) if bbox is not None else []
    zs = [t[0] for t in covering]
    xs = [t[1] for t in covering]
    ys = [t[2] for t in covering]
    deleted = 0
    with connection.cursor() as cursor:
        for old, new in versions.items():
            if covering:
                cursor.execute(
                    "DELETE FROM stress_tile_cache WHERE version = %s AND (z, x, y) IN "
                    "(SELECT * FROM unnest(%s::smallint[], %s::int[], %s::int[]))",
                    [old, zs, xs, ys],
                )
                deleted += cursor.rowcount
            # Nothing should be under the new tag yet; whatever is would be a stale draw.
            cursor.execute("DELETE FROM stress_tile_cache WHERE version = %s", [new])
            cursor.execute(
                "UPDATE stress_tile_cache SET version = %s WHERE version = %s", [new, old]
            )
    return deleted


def tile_index(lon: float, lat: float, z: int) -> tuple[int, int]:
    """The (x, y) of the z tile holding a point (Web Mercator, as the map)."""
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tiles_in_coverage(max_zoom: int) -> list[tuple[int, int, int]]:
    """Every tile from z10 to `max_zoom` that the coverage box reaches, in
    zoom order.

    Every one, not only those holding a segment's end: a long segment crosses
    tiles where it has no vertex, and a tile with nothing in it is drawn empty
    in a moment and then served from the cache rather than drawn on request.
    """
    from .stress_tiles import MIN_ZOOM, outside_coverage

    west, south, east, north = settings.COVERAGE_BBOX
    tiles = []
    for z in range(MIN_ZOOM, max_zoom + 1):
        x0, y0 = tile_index(west, north, z)
        x1, y1 = tile_index(east, south, z)
        tiles.extend(
            (z, x, y)
            for x in range(x0, x1 + 1)
            for y in range(y0, y1 + 1)
            if not outside_coverage(z, x, y)
        )
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


# The pre-draw's default time budget, an hour: far past what the whole box
# takes. Its 11,068 tiles, z10-14, took 89 s with two workers (155 s with one,
# 89 s with three, 97 s with four) on a copy of the promoted build at load 4-6
# (2026-09-28); z10-13 alone took 135-216 s on a host at load 10-27 before the
# zoomed-out tiles were cut to the trails. The rebuild cuts it further to what
# its own 8 h limit leaves (config.procrastinate), and the rebuild itself takes
# about 3.5 h of those.
PREDRAW_BUDGET_S = 3600.0


def predraw(
    max_zoom: int = PREDRAW_MAX_ZOOM,
    budget_s: float = PREDRAW_BUDGET_S,
    workers: int | None = None,
) -> Predrawn:
    """Draw every z10-`max_zoom` tile over the coverage box not yet cached, and then
    every Mass Ride tile over the District's box (core.mass_tiles, OWNER-DECISIONS 415):
    187 more at 2026-10-03's counts (z10 4, z11 6, z12 12, z13 35, z14 130), drawn only
    from a table with the capacity column.

    Stops when `budget_s` is spent, counting what it did not reach, which is
    drawn on first request instead. Each draw runs under
    `stress_tiles.PREDRAW_TIMEOUT_MS`; one that runs past it is skipped and
    counted, and the pre-draw goes on.

    `workers` tiles are drawn at once (settings.STRESS_PREDRAW_WORKERS if none
    is given), each on a database connection of its own. The pre-draw runs in
    the worker or a management command, never in gunicorn, so it holds none of
    the api's draw slots (`ratelimit.TILES_IN_FLIGHT`), which stay the owner's
    arithmetic for draws on request; what it takes is a database core per draw,
    which is what the setting bounds.
    """
    from pipeline.schema import MASS_WIDTH_COLUMN

    from . import mass_tiles, stress_tiles

    if workers is None:
        workers = settings.STRESS_PREDRAW_WORKERS
    workers = max(1, workers)
    oid, optional, generation = stress_tiles.live_state()
    if oid is None:
        return Predrawn(0, 0)
    version = stress_tiles.etag_for(oid, optional, generation)
    mass_version = mass_tiles.etag_for(oid, optional, generation)
    evict(version, also_keep=(mass_version,))
    deadline = time.monotonic() + budget_s
    # (draw, version, z, x, y): the stress tiles, then the Mass Ride tiles.
    tiles = [(stress_tiles.render, version, *t) for t in tiles_in_coverage(max_zoom)]
    if MASS_WIDTH_COLUMN in optional:
        tiles += [
            (mass_tiles.render, mass_version, *t)
            for t in mass_tiles.tiles_over_dc(min(max_zoom, mass_tiles.MAX_ZOOM))
        ]
    counts = {"drawn": 0, "cached": 0, "timed_out": 0, "reached": 0}
    lock = threading.Lock()
    stop = threading.Event()
    queue = iter(tiles)

    def take() -> tuple | None:
        with lock:
            if stop.is_set():
                return None
            if time.monotonic() > deadline:
                stop.set()
                return None
            tile = next(queue, None)
            if tile is not None:
                counts["reached"] += 1
            return tile

    def count(key: str, by: int = 1) -> None:
        with lock:
            counts[key] += by

    def draw_until_done() -> None:
        while (tile := take()) is not None:
            draw, tag, z, x, y = tile
            if get(tag, z, x, y) is not None:
                count("cached")
                continue
            try:
                drawn_oid, body = draw(
                    z, x, y, optional, timeout_ms=stress_tiles.PREDRAW_TIMEOUT_MS
                )
            except stress_tiles.DrawTimedOut:
                logger.warning("%s tile %d/%d/%d timed out in the pre-draw", tag, z, x, y)
                count("timed_out")
                continue
            if drawn_oid != oid:
                # A promotion landed mid-way; the next pre-draw is for that
                # table. This tile was not drawn for this one.
                count("reached", -1)
                stop.set()
                return
            put(tag, z, x, y, body)
            count("drawn")

    def on_its_own_connection() -> None:
        try:
            draw_until_done()
        finally:
            connection.close()

    if workers == 1:
        draw_until_done()
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="predraw") as pool:
            for future in [pool.submit(on_its_own_connection) for _ in range(workers)]:
                future.result()
    left = len(tiles) - counts["reached"]
    if left:
        logger.warning(
            "stress tile pre-draw stopped with %d drawn and %d left (budget %ss)",
            counts["drawn"],
            left,
            budget_s,
        )
    return Predrawn(counts["drawn"], counts["cached"], counts["timed_out"], left)
