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
from django.db.models import Max

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

    # A load replaces every row, so its rows' ids are all new: the highest id (read from the
    # primary key's index, not the table) says which load is in.
    return (JunctionRater.objects.aggregate(last=Max("id"))["last"],)


_NEAR_SQL = """
SELECT DISTINCT t.id, ST_X(t.location), ST_Y(t.location), t.control,
       t.cross_stress, t.left_stress, t.along_stress,
       t.cross_delay_s, t.left_delay_s, t.along_delay_s
FROM {table} AS t
JOIN unnest(%s::float8[], %s::float8[]) AS p(lon, lat)
  ON ST_DWithin(t.location, ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326), %s)
"""


def near(points: Sequence[tuple[float, float]]) -> tuple[RaterRating, ...]:
    """The rated junctions within reach of any of `points` (lon, lat): each point asks the
    location index on its own, so a long route reads only its own corridor."""
    from .models import JunctionRater

    if not points:
        return ()
    from .routing import plan_cursor

    sql = _NEAR_SQL.format(table=JunctionRater._meta.db_table)
    found: dict[int, RaterRating] = {}
    try:
        # The plan's own cursor: under its deadline, cancelled with it, and in a savepoint,
        # so a failed read leaves a caller's transaction usable (v0.29.0 release review).
        with plan_cursor() as cursor:
            for start in range(0, len(points), _BATCH):
                chunk = points[start : start + _BATCH]
                cursor.execute(sql, [[p[0] for p in chunk], [p[1] for p in chunk], _REACH_DEG])
                for row in cursor.fetchall():
                    found[row[0]] = RaterRating(
                        row[1], row[2], tuple(row[4:7]), tuple(row[7:10]), row[3] or ""
                    )
    except DatabaseError:
        logger.warning("the junction ratings could not be read", exc_info=True)
        return ()
    return tuple(found.values())


# The map's view at its closest zooms (GET /api/junctions/rated): about a mile across at most.
BOX_MAX_LON = 0.04
BOX_MAX_LAT = 0.03
BOX_LIMIT = 1500
# A junction is shown from this level up (routemaker.intersections.RATER_MARK_FROM); the
# map asks for every level only at its very closest zoom (the owner, 2026-11-20).
BOX_FROM = 3.0

_BOX_SQL = """
SELECT t.junction, AVG(ST_X(t.location)), AVG(ST_Y(t.location)),
       MAX(t.cross_stress), MAX(t.left_stress), MAX(t.along_stress),
       MAX(t.cross_delay_s), MAX(t.left_delay_s), MAX(t.along_delay_s)
FROM {table} AS t
WHERE t.location && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
  AND GREATEST(COALESCE(t.cross_stress, 0), COALESCE(t.left_stress, 0),
               COALESCE(t.along_stress, 0)) >= %s
GROUP BY t.junction
ORDER BY t.junction
LIMIT %s
"""


def parse_box(text: str) -> tuple[float, float, float, float]:
    """The view as west,south,east,north in degrees: in range, and zoomed in."""
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError("bbox is west,south,east,north")
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError as error:
        raise ValueError("bbox is four numbers") from error
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox is west,south,east,north, each in range, west before east")
    if east - west > BOX_MAX_LON or north - south > BOX_MAX_LAT:
        raise ValueError("zoom in: the view is too large to show rated junctions")
    return west, south, east, north


def box_rows(rows: Sequence[Sequence]) -> list[dict]:
    """The answer's junctions from the query's rows: one a junction, at the middle of its
    nodes, with its hardest movement's level (the dot's colour) and every movement that can
    be made there."""
    from routemaker.intersections import RATER_MOVES

    out = []
    for _junction, lon, lat, *rest in rows:
        moves = [
            {"move": name, "level": level, "wait_s": None if wait is None else round(wait)}
            for name, level, wait in zip(RATER_MOVES, rest[:3], rest[3:6], strict=True)
            if level is not None
        ]
        out.append(
            {
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "level": max(move["level"] for move in moves),
                "moves": moves,
            }
        )
    return out


def in_box(box: tuple[float, float, float, float], every: bool = False) -> list[dict]:
    """The junctions rated 3 or more in a map view, or every rated one with `every`, for the
    plain map's dots at its closest zooms (the owner, 2026-11-20: "Anything less than 3 only
    show at the very closest zoom level"). None could be read: none."""
    from django.db import connection

    from .models import JunctionRater

    sql = _BOX_SQL.format(table=JunctionRater._meta.db_table)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, [*box, 0.0 if every else BOX_FROM, BOX_LIMIT])
            return box_rows(cursor.fetchall())
    except DatabaseError:
        logger.warning("the junction ratings could not be read", exc_info=True)
        return []


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


def loaded() -> bool:
    """Whether any ratings are loaded: with none, a plan reads none (no query a candidate)."""
    try:
        return _version() != (None,)
    except DatabaseError:
        return False


def digest() -> str:
    """The table's version, for the route cache's key."""
    try:
        return repr(_version())
    except DatabaseError:
        return ""
