"""Assigning ways to authorities, and reading crossings off a route.

Three layers, not one, because the body that issues a permit is frequently not a
police agency: the W&OD is NOVA Parks, the Capital Crescent and Sligo Creek are
M-NCPPC, the towpath and the Mount Vernon Trail are the Park Service as land
manager, and public space in the District is DDOT. Scoping this to police while
calling its purpose permitting would leave out the permit issuer.

Nothing here says what any authority requires. It reports which ones a route
touches and in what order; the info cards carry the rest, under their own
not-legal-advice line.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.gis.geos import LineString
from django.db import connection

from .crossings import Crossing

# Ways whose centreline *is* the boundary. Treated as District with both
# authorities flagged, rather than flickering between them along their length.
BOUNDARY_STREETS = frozenset({"Western Avenue", "Eastern Avenue", "Southern Avenue"})


@dataclass(frozen=True)
class LayerAssignment:
    layer: str
    authority: str
    fraction: float


def assign_way(geometry: LineString) -> list[LayerAssignment]:
    """Which authority covers this way, per layer, by share of its length.

    A way can straddle a boundary, so this returns every authority it touches
    with the fraction of the way inside each rather than picking a winner. The
    caller decides what to do with a way that is 3 percent inside a park.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT j.layer,
                   j.name,
                   ST_Length(ST_Intersection(%s::geometry, j.geometry)::geography)
                     / NULLIF(ST_Length(%s::geometry::geography), 0) AS fraction
            FROM jurisdiction j
            WHERE ST_Intersects(%s::geometry, j.geometry)
            ORDER BY j.layer, fraction DESC
            """,
            [geometry.ewkb, geometry.ewkb, geometry.ewkb],
        )
        return [
            LayerAssignment(layer=row[0], authority=row[1], fraction=row[2] or 0.0)
            for row in cursor.fetchall()
        ]


def route_crossings(geometry: LineString, layer: str) -> list[Crossing]:
    """Ordered stretches of the route inside each authority on one layer.

    Ordered along the route rather than grouped by authority, because a crossing
    list is read while riding it: re-entering the District after a mile in
    Maryland is a second crossing, not a footnote on the first.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH parts AS (
                SELECT j.name,
                       j.is_federal_enclave,
                       (ST_Dump(ST_Intersection(%s::geometry, j.geometry))).geom AS piece
                FROM jurisdiction j
                WHERE j.layer = %s AND ST_Intersects(%s::geometry, j.geometry)
            )
            SELECT name,
                   is_federal_enclave,
                   ST_LineLocatePoint(%s::geometry, ST_StartPoint(piece)) AS t_start,
                   ST_LineLocatePoint(%s::geometry, ST_EndPoint(piece)) AS t_end,
                   ST_Length(piece::geography) AS piece_m
            FROM parts
            WHERE GeometryType(piece) = 'LINESTRING' AND ST_NPoints(piece) > 1
            """,
            [geometry.ewkb, layer, geometry.ewkb, geometry.ewkb, geometry.ewkb],
        )
        rows = cursor.fetchall()

    total_m = _length_m(geometry)
    crossings = []
    for name, is_enclave, t_start, t_end, _piece_m in rows:
        start, end = sorted((t_start or 0.0, t_end or 0.0))
        crossings.append(
            Crossing(
                layer=layer,
                authority=name,
                start_m=start * total_m,
                end_m=end * total_m,
                is_federal_enclave=bool(is_enclave),
            )
        )
    return sorted(crossings, key=lambda c: c.start_m)


def _length_m(geometry: LineString) -> float:
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_Length(%s::geometry::geography)", [geometry.ewkb])
        return cursor.fetchone()[0] or 0.0


def is_boundary_street(name: str | None) -> bool:
    """Whether a way's centreline is itself the District line.

    Not surfaced in UI copy as a legal statement; it decides how the way is
    tagged, and the crossing list notes both authorities.
    """
    return name in BOUNDARY_STREETS
