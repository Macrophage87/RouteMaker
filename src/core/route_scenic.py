"""The scenic designations a route rides (v0.12.3; `routemaker.scenic`).

The owner, 2026-10-25, after a towpath and rustic-roads ride the assistant connector could
build but not find: "The goal would be for a new user to be able to make routes like this."
The connector's answer lists the roads a route takes, and says which are Montgomery
County Rustic Roads, scenic byways, the East Coast Greenway or a US Bicycle Route; this
module finds those stretches, in metres along the traced route as the stress sections are
measured (`routing.stress_spans`), from `segment.scenic` (`pipeline.scenic_layer`).

A designation stays a fact about the way, never a stress input or a routing bonus.
"""

from __future__ import annotations

import logging

from django.conf import settings

from pipeline.schema import SCENIC_COLUMN, validate_schema_name

from . import segment_info
from .route_hazards import road_of

logger = logging.getLogger(__name__)

# Two stretches of one designation on one road this close are one (a bridge or a junction
# between them that the layer does not cover).
JOIN_GAP_M = 50.0

_SCENIC_JOIN = """
SELECT seg.{column}
FROM unnest(%s::bigint[], %s::float8[], %s::float8[])
     WITH ORDINALITY AS p(way_id, lon, lat, ordinality)
LEFT JOIN LATERAL (
    SELECT s.{column}
    FROM {schema}.segment AS s
    WHERE s.osm_way_id = p.way_id
    ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)
    LIMIT 1
) AS seg ON true
ORDER BY p.ordinality
"""


def designations_of(pieces: list) -> list[str | None]:
    """Each piece's scenic designations in words, in the pieces' order; all None where the
    live table has no scenic column (a table built before it) or the query fails."""
    if not pieces:
        return []
    none: list[str | None] = [None] * len(pieces)
    try:
        schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
        if not segment_info.has_columns(schema, SCENIC_COLUMN):
            return none
        from .routing import plan_cursor

        with plan_cursor() as cursor:
            cursor.execute(
                _SCENIC_JOIN.format(schema=schema, column=SCENIC_COLUMN),
                [
                    [p.way_id for p in pieces],
                    [p.lon for p in pieces],
                    [p.lat for p in pieces],
                ],
            )
            rows = cursor.fetchall()
    except Exception:  # noqa: BLE001 - a table that fails, or a plan out of time, says none
        logger.warning("the route's scenic roads could not be read", exc_info=True)
        return none
    return [(str(row[0]).strip() or None) if row[0] else None for row in rows]


def along(leg_runs: list, pieces: list, designations: list | None = None) -> list[dict]:
    """The scenic stretches the route rides, in riding order: {from_m, to_m, road,
    designation}. Consecutive pieces with one designation on one road are one entry."""
    designations = designations_of(pieces) if designations is None else designations
    if not any(designations):
        return []
    out: list[dict | None] = []
    at = 0.0
    for run in leg_runs:
        if not isinstance(run, tuple):
            at += float(run)
            out.append(None)  # a walk between: never joined across
            continue
        for i in range(run[0], run[1]):
            piece = pieces[i]
            start, at = at, at + piece.metres
            found = designations[i] if i < len(designations) else None
            if not found:
                continue
            road = road_of(piece)
            last = out[-1] if out else None
            if (
                last is not None
                and last["designation"] == found
                and last["road"] == road
                and start - last["to_m"] <= JOIN_GAP_M
            ):
                last["to_m"] = round(at)
                continue
            out.append(
                {"from_m": round(start), "to_m": round(at), "road": road, "designation": found}
            )
    return [entry for entry in out if entry is not None]
