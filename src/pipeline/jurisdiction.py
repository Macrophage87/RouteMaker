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

# And the street type, which OSM abbreviates at least as often as it spells out.
# "Eastern Ave NE" and "Western Ave" are the same two streets as "Eastern Avenue
# Northeast" and "Western Avenue", and both spellings run along each of them:
# the quadrant normaliser alone left the abbreviated halves unmatched, which is
# the same partial firing it was written to prevent, one step further in. The
# border inserter then fragmented the abbreviated stretches of a boundary street
# and the crossing report showed entries into Montgomery County for a ride that
# never left the curb.
_STREET_TYPE = re.compile(r"\s+(?:ave|av)\.?$", re.IGNORECASE)


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


# How close a vertex must come to a second authority on the same layer before
# both are taken to apply. A boundary street's centreline *is* the line, so its
# vertices sit within centimetres of both polygons along the whole street, while
# a route merely crossing a boundary is that close for one step. Measured on the
# geography, so it is metres rather than degrees.
SHARED_BOUNDARY_TOLERANCE_M = 2.0

# Degrees-per-metre at this region's latitude is about 1/86_500 in the
# longitude direction (111_320 m/deg at the equator, times cos(~39 degrees));
# 1/80_000 pads that generously in both directions rather than tuning it
# exactly, because this value only has to be an overestimate - the precise
# geography check right after it is what decides the match.
_METRES_TO_DEGREES = 1 / 80_000.0

# How far a shared stretch has to run before it is reported as one. Every
# ordinary boundary crossing has one vertex within the tolerance of both sides,
# so without this every crossing grows a metre-long "both authorities" run in
# front of it and an out-and-back through one county reports four entries instead
# of two. A boundary street runs for blocks; a transition is a step or less.
MIN_SHARED_RUN_M = 50.0


def route_crossings(
    geometry: LineString,
    layer: str,
    step_m: float = 25.0,
    shared_tolerance_m: float = SHARED_BOUNDARY_TOLERANCE_M,
) -> list[Crossing]:
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

    The join is filtered twice, not once. `ST_DWithin(j.geometry::geography, ...)`
    alone is precise but casts every row's geometry to geography inline, which
    is a computed expression the GiST index on `jurisdiction.geometry` does not
    cover - so Postgres has no choice but a sequential scan per vertex.
    Measured on a synthetic 20,000-polygon jurisdiction table against a
    1,025-vertex segmentized route (this function's own query shape): 171.5
    seconds. Prefiltering with a plain-geometry `ST_DWithin`, in degrees rather
    than metres, *is* index-assisted - Postgres rewrites it internally into
    `geometry && ST_Expand(...)`, a bounding-box test the GiST index answers
    directly - and cuts the same query to 26 ms, about 6,500 times faster. The
    degree tolerance overestimates on purpose (see `_METRES_TO_DEGREES`); the
    geography check right after it still decides the real match, so the
    prefilter only has to avoid excluding anything, not be exact.
    """
    prefilter_deg = shared_tolerance_m * _METRES_TO_DEGREES
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
              ON j.layer = %s
             AND ST_DWithin(j.geometry, v.point, %s)
             AND ST_DWithin(j.geometry::geography, v.point::geography, %s)
            ORDER BY v.idx, j.is_federal_enclave DESC NULLS LAST, j.name
            """,
            [geometry.ewkb, step_m, layer, prefilter_deg, shared_tolerance_m],
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
    # Every authority within the tolerance is kept, not just the winner, and the
    # run boundary is drawn on that whole set rather than on the first of them.
    #
    # On a shared edge, which of two polygons a vertex is "in" flips with the
    # floating-point accident of each coordinate, so keying runs on the winner
    # alone turned a straight line down one boundary into five crossings that
    # alternated between the two counties - the same fragmentation the border
    # inserter's boundary-street carve-out exists to prevent, arriving by a
    # different route. The *pair* is stable along that street even though the
    # winner is not.
    #
    # This is also what gives `Crossing.also_authority` a producer at all. It was
    # a documented field written by nothing, so a ride down Eastern Avenue -
    # which really does involve Prince George's County - was reported as DC end
    # to end.
    per_vertex: dict[int, tuple[float, float, tuple[str, ...], bool]] = {}
    for idx, lon, lat, name, enclave in rows:
        existing = per_vertex.get(idx)
        names = existing[2] if existing else ()
        if name is not None and name not in names:
            names = (*names, name)
        per_vertex[idx] = (lon, lat, names, bool(enclave) or bool(existing and existing[3]))

    ordered = [per_vertex[idx] for idx in sorted(per_vertex)]

    runs: list[list] = []  # [names, start_m, end_m, enclave]
    travelled = 0.0
    current: tuple[str, ...] = ()

    for position, (lon, lat, names, enclave) in enumerate(ordered):
        if position > 0:
            previous = ordered[position - 1]
            travelled += haversine(Point(previous[0], previous[1]), Point(lon, lat))
        if names != current:
            current = names
            runs.append([names, travelled, travelled, enclave])
        elif runs:
            runs[-1][2] = travelled
            runs[-1][3] = runs[-1][3] or enclave
    if runs:
        runs[-1][2] = travelled

    return [
        Crossing(
            layer=layer,
            authority=names[0],
            start_m=start,
            end_m=end,
            is_federal_enclave=enclave,
            # Singular, because two is the case that occurs: a centreline lies
            # between two polygons. Where a third somehow applies, the ordering
            # is the query's, so which two are named is at least deterministic.
            also_authority=names[1] if len(names) > 1 else None,
        )
        for names, start, end, enclave in _absorb_transitions(runs)
        # A vertex in no polygon on this layer is a gap in coverage, not an
        # authority called nothing.
        if names
    ]


def _absorb_transitions(runs: list[list]) -> list[list]:
    """Fold a momentary shared stretch into the neighbour it belongs to.

    Every boundary crossing puts one vertex within the tolerance of both sides,
    so without this each one grows a metre-long "both authorities" run in front
    of it: an out-and-back through one county reports four entries rather than
    two, and the jurisdiction mileage on a permit application is wrong in both
    directions. A stretch that runs for blocks is a boundary street and stays.
    """
    kept: list[list] = []
    for index, run in enumerate(runs):
        names, start, end, _enclave = run
        if len(names) > 1 and end - start < MIN_SHARED_RUN_M:
            # Merge into whichever neighbour shares an authority with it, the
            # following one first: a transition belongs to what the route is
            # entering rather than to what it is leaving.
            following = runs[index + 1] if index + 1 < len(runs) else None
            if following is not None and set(following[0]) & set(names):
                following[1] = start
                continue
            if kept and set(kept[-1][0]) & set(names):
                kept[-1][2] = end
                continue
        if kept and kept[-1][0] == names:
            kept[-1][2] = end
            continue
        kept.append(run)
    return kept


def _length_m(geometry: LineString) -> float:
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_Length(%s::geometry::geography)", [geometry.ewkb])
        return cursor.fetchone()[0] or 0.0


def is_boundary_street(name: str | None) -> bool:
    """Whether a way's centreline is itself the District line.

    Normalised before matching, in both of the ways OSM varies here: "Western
    Avenue Northwest", "Western Avenue", "Western Ave NW" and "Western Ave" are
    one street, and every one of those spellings is carried somewhere along it.
    Not surfaced in UI copy as a legal statement; it decides how the way is
    tagged, and the crossing list notes both authorities.
    """
    if not name:
        return False
    normalised = _STREET_TYPE.sub(" Avenue", _QUADRANT.sub("", name.strip()))
    return normalised.casefold() in BOUNDARY_STREETS
