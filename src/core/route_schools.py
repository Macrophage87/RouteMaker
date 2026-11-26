"""The school pieces a route rides, and the search's reading of them at school times
(`routemaker.school_times`; the owner, 2026-11-26: "Let's rate school zones higher during
the common times that people travel there").

At a school time the calm search (`core.refine`) reads a school piece at the raters'
rush-hour level where that is higher than its own, so it looks for a way round a busy bus
loop or drop-off street at arrival time as it would round any road at that level. The
rider is still shown the road's own level, and nothing changes at other times or on a road
not rated for school times.
"""

from __future__ import annotations

import logging

from django.conf import settings

from pipeline.schema import SCHOOL_COLUMN, validate_schema_name
from routemaker import school_times

from . import segment_info
from .route_hazards import _HAZARD_JOIN

logger = logging.getLogger(__name__)


def levels_of(pieces: list) -> list[float | None]:
    """Each piece's rush-hour level, in the pieces' order (None: not a rated school piece);
    all None where the live table has no such column (a table built before it) or the query
    fails."""
    none: list[float | None] = [None] * len(pieces)
    if not pieces:
        return none
    try:
        schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
        if not segment_info.has_columns(schema, SCHOOL_COLUMN):
            return none
        from .routing import plan_cursor

        with plan_cursor() as cursor:
            cursor.execute(
                _HAZARD_JOIN.format(schema=schema, column=SCHOOL_COLUMN),
                [
                    [p.way_id for p in pieces],
                    [p.lon for p in pieces],
                    [p.lat for p in pieces],
                ],
            )
            rows = cursor.fetchall()
    except Exception:  # noqa: BLE001 - a table that fails, or a plan out of time, says none
        logger.warning("the route's school pieces could not be read", exc_info=True)
        return none
    return [None if row[0] is None else float(row[0]) for row in rows]


def school_priced(classes: list, levels: list[float | None]) -> list:
    """Each school piece read at its rush-hour level where that is higher
    (`school_times.raised`). The same list where no piece changes."""
    if not any(level is not None for level in levels):
        return classes
    from .routing import PieceClass

    out = []
    changed = False
    for cls, level in zip(classes, levels, strict=False):
        lifted = school_times.raised(cls[0], getattr(cls, "half", False), cls[1], level)
        if lifted is not None:
            changed = True
            cls = PieceClass(
                lifted[0],
                cls[1],
                getattr(cls, "unpaved", None),
                getattr(cls, "lanes", None),
                getattr(cls, "oneway", None),
                getattr(cls, "width_m", None),
                lifted[1],
            )
        out.append(cls)
    out.extend(classes[len(out) :])
    return out if changed else classes


def priced_at(classes: list, pieces: list, when: str | None) -> list:
    """`classes` as the search reads them at the ride time `when`: the rated school pieces
    raised at a school time (`school_times.SCHOOL_WHENS`); the same list at any other time."""
    if not school_times.at_school_time(when):
        return classes
    return school_priced(classes, levels_of(pieces))
