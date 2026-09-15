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

import re
from dataclasses import dataclass

from django.contrib.gis.geos import LineString
from django.db import connection

from routemaker.geo import Point, haversine

from .crossings import Crossing

# Ways whose centreline *is* the boundary. Treated as District with both
# authorities flagged, rather than flickering between them along their length.
BOUNDARY_STREETS = frozenset({"western avenue", "eastern avenue", "southern avenue"})

# OSM names these with a quadrant on the District side and without one on the
# Maryland side, so an exact match fires on roughly half the length of each
# street and not the other half - which is worse than not firing at all, because
# the border inserter then fragments only part of the way and the crossing
# report shows entries into Montgomery County for a ride that never left the
# curb.
_QUADRANT = re.compile(
    r"\s+(?:north|south)?(?:east|west)$|\s+(?:nw|ne|sw|se|n|s|e|w)$",
    re.IGNORECASE,
)


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


def route_crossings(geometry: LineString, layer: str, step_m: float = 25.0) -> list[Crossing]:
    """Ordered stretches of the route inside each authority on one layer.

    Walked sequentially rather than derived by locating intersection pieces on
    the line. `ST_LineLocatePoint` returns the position of the point on the route
    *nearest* its argument, which is ambiguous the moment a route visits the same
    area twice, and the earlier implementation built on it produced, on a real
    25 km route through one 900 m park: five crossings instead of two, two of
    them spanning 20 and 22 km of a park the route barely clipped; a single
    867 m crossing for an out-and-back that passed through twice, halving the
    jurisdiction mileage that goes on a permit application; and a spurious
    5 km crossing on a loop that started inside the polygon, because normalising
    a wrap-around piece by sorting its endpoints turns 0.79 to 0.0 into 0.0 to
    0.79.

    Walking the route in order is unambiguous for all three shapes, because
    position along the route is the thing being iterated rather than something
    recovered afterwards. Lengths are geodesic; the earlier version multiplied a
    fraction measured in degrees by a length measured in metres, which on a route
    mixing north-south and east-west legs misplaced crossings by about four
    percent - larger than the collapse threshold it fed.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH route AS (SELECT ST_Segmentize(%s::geometry::geography, %s)::geometry AS g),
            vertices AS (
                SELECT (dp).path[1] AS idx, (dp).geom AS point
                FROM route, ST_DumpPoints(route.g) AS dp
            )
            SELECT v.idx,
                   ST_X(v.point),
                   ST_Y(v.point),
                   j.name,
                   j.is_federal_enclave
            FROM vertices v
            LEFT JOIN jurisdiction j
              ON j.layer = %s AND ST_Intersects(j.geometry, v.point)
            ORDER BY v.idx, j.is_federal_enclave DESC NULLS LAST, j.name
            """,
            [geometry.ewkb, step_m, layer],
        )
        rows = cursor.fetchall()

    if not rows:
        return []

    # One vertex can sit in more than one polygon on the same layer where
    # boundaries touch. The query orders them, so the first row per vertex is
    # deterministic: without the ORDER BY, which row arrived first was whatever
    # the plan produced, and two runs over the same route could name different
    # authorities along a shared edge. Federal enclaves sort first, because where
    # one overlaps another polygon it is the enclave that changes the permit
    # question.
    per_vertex: dict[int, tuple[float, float, str | None, bool]] = {}
    for idx, lon, lat, name, enclave in rows:
        if idx not in per_vertex or (name is not None and per_vertex[idx][2] is None):
            per_vertex[idx] = (lon, lat, name, bool(enclave))

    ordered = [per_vertex[idx] for idx in sorted(per_vertex)]

    crossings: list[Crossing] = []
    travelled = 0.0
    run_start = 0.0
    current: str | None = None
    current_enclave = False

    for position, (lon, lat, name, enclave) in enumerate(ordered):
        if position > 0:
            previous = ordered[position - 1]
            travelled += haversine(Point(previous[0], previous[1]), Point(lon, lat))
        if name != current:
            if current is not None:
                crossings.append(
                    Crossing(
                        layer=layer,
                        authority=current,
                        start_m=run_start,
                        end_m=travelled,
                        is_federal_enclave=current_enclave,
                    )
                )
            current, current_enclave, run_start = name, enclave, travelled

    if current is not None:
        crossings.append(
            Crossing(
                layer=layer,
                authority=current,
                start_m=run_start,
                end_m=travelled,
                is_federal_enclave=current_enclave,
            )
        )
    return crossings


def _length_m(geometry: LineString) -> float:
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_Length(%s::geometry::geography)", [geometry.ewkb])
        return cursor.fetchone()[0] or 0.0


def is_boundary_street(name: str | None) -> bool:
    """Whether a way's centreline is itself the District line.

    Normalised before matching: "Western Avenue Northwest" and "Western Avenue"
    are the same street, and OSM carries both spellings along its length. Not
    surfaced in UI copy as a legal statement; it decides how the way is tagged,
    and the crossing list notes both authorities.
    """
    if not name:
        return False
    return _QUADRANT.sub("", name.strip()).casefold() in BOUNDARY_STREETS
