"""The raters' junction ratings (`JunctionRater`), read at plan time.

Every junction a bike rides through was rated in the 2026-11-19 junction run: per movement a
stress level and the seconds lost there. A route asks for the rated junctions within reach of
its nodes (`near`): one indexed query a reading, as the table holds some 600,000 rows. The
delay model scales a wait by the rated seconds over the median of the same control and
movement (`medians`), read once and kept until the table changes. Empty when nothing is
loaded or the table cannot be read: a plan is never refused for want of them.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from django.db import DatabaseError, connection
from django.db.models import Count, Max

from routemaker.intersections import RATER_MATCH_M, RATER_MOVES, RaterRating

logger = logging.getLogger(__name__)

# RATER_MATCH_M as degrees, with room (a degree of longitude is shorter than one of
# latitude: this covers it to about 60 N); `intersections.with_raters` checks the metres.
_REACH_DEG = 2 * RATER_MATCH_M / 100_000.0
# The most nodes one query sends; a long route's are asked in batches.
_BATCH = 2000

_lock = threading.Lock()
_memo: tuple[tuple, dict[tuple[str, str], float]] | None = None


def _version() -> tuple:
    from .models import JunctionRater

    seen = JunctionRater.objects.aggregate(n=Count("id"), last=Max("id"), at=Max("loaded_at"))
    return (seen["n"], seen["last"], seen["at"])


def _row(row) -> RaterRating:
    return RaterRating(
        row.location.x,
        row.location.y,
        (row.cross_stress, row.left_stress, row.along_stress),
        (row.cross_delay_s, row.left_delay_s, row.along_delay_s),
        row.control,
    )


def near(points: Sequence[tuple[float, float]]) -> tuple[RaterRating, ...]:
    """The rated junctions within reach of any of `points` (lon, lat)."""
    from django.contrib.gis.geos import MultiPoint, Point

    from .models import JunctionRater

    if not points:
        return ()
    found: dict[int, RaterRating] = {}
    try:
        for start in range(0, len(points), _BATCH):
            chunk = MultiPoint([Point(lon, lat) for lon, lat in points[start : start + _BATCH]])
            chunk.srid = 4326
            for row in JunctionRater.objects.filter(location__dwithin=(chunk, _REACH_DEG)):
                found[row.id] = _row(row)
    except DatabaseError:
        logger.warning("the junction ratings could not be read", exc_info=True)
        return ()
    return tuple(found.values())


def _read_medians() -> dict[tuple[str, str], float]:
    from .models import JunctionRater

    table = JunctionRater._meta.db_table
    out: dict[tuple[str, str], float] = {}
    with connection.cursor() as cursor:
        for move in RATER_MOVES:
            column = f"{move}_delay_s"
            cursor.execute(
                f"SELECT control, percentile_cont(0.5) WITHIN GROUP (ORDER BY {column}) "  # noqa: S608 - fixed names
                f"FROM {table} WHERE {column} IS NOT NULL GROUP BY control"
            )
            for control, median in cursor.fetchall():
                if median:
                    out[(control or "", move)] = float(median)
    return out


def medians() -> dict[tuple[str, str], float]:
    """The median rated seconds by (control, movement), for `junction_delay.rater_scaled`."""
    global _memo
    try:
        version = _version()
        with _lock:
            if _memo is not None and _memo[0] == version:
                return _memo[1]
        found = _read_medians()
    except DatabaseError:
        logger.warning("the junction rating medians could not be read", exc_info=True)
        return {}
    with _lock:
        _memo = (version, found)
    return found


def digest() -> str:
    """The table's version, for the route cache's key."""
    try:
        return repr(_version())
    except DatabaseError:
        return ""
