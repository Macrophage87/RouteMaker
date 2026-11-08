"""A dirt trail the rider is on, or put a point on, on a ride type that does not plan on them.

The owner, 2026-10-20, after a re-route turned him back off a dirt trail at Lake Needwood:
"Don't plan on the route, but if you enter it or mark a waypoint in it, it will continue to
route through." and "Connecting trails too". And 2026-10-21: "intentionally going on dirt means
that any connecting trail is fine too. I wouldn't use that as a start for routing unless
"opted-in", mainly because it's weather and drainage dependent. If someone goes onto a dirt
trail, any reroutes should include dirt."

The mountain-bike class of dirt trail (`routemaker.trailaccess`, reason `mtb`) is closed on
the standard graphs and open on the off-road graph Gravel and Mountain Goat ride. A plan on a
standard-graph ride type (the standard graph, its weekend twin, or the e-bike graph:
`core.routing.TRAIL_TOUCH_VARIANTS`) whose stop, via or end lies on one (`touched`) is planned
on the off-road graph instead, with the ride type's own costing. Its start is not enough: the
rider did not choose the trail by standing on it. A ride's re-plan is different: there the
start is the rider, and a rider on a dirt trail, or who has been on one this ride, opted in, so
the re-plan may ride any dirt trail (`core.routing._plan`'s `any_dirt`). On it means riding
along it: with the rider's heading, the trail under the fix must run that way (`followed`); a
fix merely near one, or with no heading, opens that trail and the trails joined to it, as a stop
does. The dirt trail it is on is then ridden, and the trails joined to it along the way: a run
of the route on dirt trails one after another counts as one run, kept when any of it is a trail
touched. A run on a dirt trail no
point touches is one the plan found for itself, which the ride type does not do: it is left out
(`stray_rings`) and the plan made again (`core.routing.plan`).

Rated singletrack the off-road graph opens (green) is never touched this way, and a run on it is
always a stray: it stays closed to these ride types.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from django.conf import settings

from pipeline.schema import validate_schema_name

from . import segment_info

# The reason the rebuild writes on the mountain-bike class (`routemaker.trailaccess.MTB`): the
# dirt trails a point can touch.
REASON = "mtb"
# The ways the off-road graph opens that the standard one closes: the class, and the green
# singletrack (`routemaker.singletrack.NO_BICYCLE`), which no point opens.
OFF_ROAD_REASONS = (REASON, "singletrack")
# How near a point lies to a trail to be on it: the router's own snap for a stop
# (`core.routing.STOP_RADIUS_M`).
TOUCH_M = 15.0
# The degrees of latitude TOUCH_M is at most, for the index's box round each point.
TOUCH_DEG = 0.0003
# Trails one after another along the route with less than this of other ways between them (a
# paved bridge, a road crossed) are one run (the owner: "Connecting trails too").
JOIN_GAP_M = 30.0
# The strip a stray run is left out by: this long along the trail, at the middle of the run's
# longest stretch, and this wide across it, so it cuts the trail and little else.
BLOCK_ALONG_M = 2.0
BLOCK_ACROSS_M = 3.0


def _reason_known(schema: str) -> bool:
    return segment_info.has_columns(schema, "bike_access_reason")


def _cursor():
    from .routing import plan_cursor

    return plan_cursor()


def touched(
    points: Sequence[Sequence[float]], reasons: Sequence[str] = (REASON,)
) -> tuple[frozenset[int], ...]:
    """The dirt trails (their way ids) within TOUCH_M of each of `points` ([lon, lat]), in
    their order. `reasons`: the closures counted, the mountain-bike class alone unless asked
    (Ride's "End mountain biking" asks for the rated singletrack too)."""
    none = tuple(frozenset() for _ in points)
    if not points:
        return none
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not _reason_known(schema):
        return none
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    # The box first, so the geometry index answers; the distance then on the few found.
    sql = f"""
        WITH p AS (
            SELECT ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g, i
            FROM unnest(%s::float8[], %s::float8[]) WITH ORDINALITY AS u(lon, lat, i)
        )
        SELECT DISTINCT p.i, s.osm_way_id
        FROM p
        JOIN {schema}.segment AS s
          ON s.geometry && ST_Expand(p.g, %s)
         AND s.bike_access_reason = ANY(%s)
         AND ST_DWithin(s.geometry::geography, p.g::geography, %s)
    """
    with _cursor() as cursor:
        cursor.execute(
            sql,
            [
                lons,
                lats,
                TOUCH_DEG / math.cos(math.radians(max(map(abs, lats)))),
                list(reasons),
                TOUCH_M,
            ],
        )
        rows = cursor.fetchall()
    found: list[set[int]] = [set() for _ in points]
    for index, way in rows:
        found[int(index) - 1].add(int(way))
    return tuple(frozenset(ways) for ways in found)


# A ride's re-plan from a fix near a dirt trail (`followed`): the rider is on it where it runs
# within FOLLOW_DEG of the rider's heading, either way along it, over the FOLLOW_SPAN_M of it
# either side of the nearest point. A trail that crosses the way the rider is going, or a path
# beside the road that turns off it, is not one the rider is on (hunt V5).
FOLLOW_DEG = 45.0
FOLLOW_SPAN_M = 10.0


def followed(point: Sequence[float], heading: float, ways: frozenset[int]) -> frozenset[int]:
    """Which of the dirt trails `ways` (within TOUCH_M of `point`, [lon, lat]) run the way
    `heading` (degrees clockwise from north) goes, or its reverse, at the point: the ones a
    rider there with that heading is riding along, not across. A trail whose direction there
    cannot be measured (a piece too short) counts as followed."""
    if not ways:
        return frozenset()
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    lon, lat = float(point[0]), float(point[1])
    sql = f"""
        WITH p AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g)
        SELECT s.osm_way_id, degrees(ST_Azimuth(
            ST_LineInterpolatePoint(s.geometry, greatest(at.f - at.d, 0.0))::geography,
            ST_LineInterpolatePoint(s.geometry, least(at.f + at.d, 1.0))::geography))
        FROM p
        JOIN {schema}.segment AS s
          ON s.geometry && ST_Expand(p.g, %s)
         AND s.osm_way_id = ANY(%s)
         AND GeometryType(s.geometry) = 'LINESTRING'
         AND ST_DWithin(s.geometry::geography, p.g::geography, %s)
        CROSS JOIN LATERAL (
            SELECT ST_LineLocatePoint(s.geometry, p.g) AS f,
                   %s / greatest(ST_Length(s.geometry::geography), 1.0) AS d
        ) AS at
    """
    with _cursor() as cursor:
        cursor.execute(
            sql,
            [
                lon,
                lat,
                TOUCH_DEG / math.cos(math.radians(abs(lat))),
                sorted(int(w) for w in ways),
                TOUCH_M,
                FOLLOW_SPAN_M,
            ],
        )
        rows = cursor.fetchall()
    kept: set[int] = set()
    for way, azimuth in rows:
        if azimuth is None or along_heading(float(azimuth), heading):
            kept.add(int(way))
    return frozenset(kept)


def along_heading(bearing: float, heading: float) -> bool:
    """Whether a way running at `bearing` runs within FOLLOW_DEG of `heading` or of its
    reverse (degrees)."""
    off = abs((bearing - heading) % 180.0)
    return min(off, 180.0 - off) <= FOLLOW_DEG


# A stretch the rider marked closed is on a dirt trail where at least CLOSED_ON_POINTS of the
# points at CLOSED_SAMPLES of its length lie within TOUCH_M of one: a road that only crosses a
# trail has one point near it at most, and a bending trail keeps most of them near.
CLOSED_SAMPLES = (0.25, 0.5, 0.75)
CLOSED_ON_POINTS = 2


def closed_on_dirt(lines: Sequence[Sequence[Sequence[float]]]) -> bool:
    """Whether a stretch the rider marked closed on this ride (Ride's Road closed, [lon, lat]
    lines) is on a dirt trail (CLOSED_SAMPLES, CLOSED_ON_POINTS). The owner, 2026-10-21:
    "If you ride a dirt trail outside of mtb or gravel and it's marked as road closed, assume
    that means bad riding conditions until it's opted back in": the ride's re-plans then ride
    no dirt trail at all (`core.routing._plan`)."""
    lines = [line for line in lines if len(line) >= 2]
    if not lines:
        return False
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not _reason_known(schema):
        return False
    wkts = [
        "LINESTRING(" + ", ".join(f"{float(p[0])} {float(p[1])}" for p in line) + ")"
        for line in lines
    ]
    sql = f"""
        WITH m AS (
            SELECT u.i, ST_LineInterpolatePoint(ST_GeomFromText(u.w, 4326), f) AS g
            FROM unnest(%s::text[]) WITH ORDINALITY AS u(w, i)
            CROSS JOIN unnest(%s::float8[]) AS f
        ), near AS (
            SELECT m.i FROM m
            WHERE EXISTS (
                SELECT 1 FROM {schema}.segment AS s
                WHERE s.geometry && ST_Expand(m.g, %s)
                  AND s.bike_access_reason = %s
                  AND ST_DWithin(s.geometry::geography, m.g::geography, %s)
            )
        )
        SELECT EXISTS (SELECT 1 FROM near GROUP BY i HAVING count(*) >= %s)
    """
    with _cursor() as cursor:
        cursor.execute(
            sql,
            [wkts, list(CLOSED_SAMPLES), TOUCH_DEG, REASON, TOUCH_M, CLOSED_ON_POINTS],
        )
        return bool(cursor.fetchone()[0])


def off_road_ways(way_ids: Sequence[int]) -> dict[int, str]:
    """Which of `way_ids` the standard graph closes and the off-road graph opens, each with
    its reason (REASON, or `singletrack`)."""
    ids = sorted({int(w) for w in way_ids if w})
    if not ids:
        return {}
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not _reason_known(schema):
        return {}
    with _cursor() as cursor:
        cursor.execute(
            f"SELECT DISTINCT osm_way_id, bike_access_reason FROM {schema}.segment "
            "WHERE osm_way_id = ANY(%s) AND bike_access_reason = ANY(%s)",
            [ids, list(OFF_ROAD_REASONS)],
        )
        return {int(way): reason for way, reason in cursor.fetchall()}


def rides_dirt(pieces: Sequence, ways: dict[int, str]) -> bool:
    """Whether `pieces` ride a dirt trail (REASON) at all."""
    return any(ways.get(p.way_id) == REASON for p in pieces)


def runs(
    way_ids: Sequence[int], metres: Sequence[float], dirt: frozenset[int]
) -> list[tuple[int, int]]:
    """The runs (start, end) of pieces on dirt trails, in the order ridden: trails one after
    another, with less than JOIN_GAP_M of other ways between two, are one run."""
    found: list[tuple[int, int]] = []
    for i, way in enumerate(way_ids):
        if way not in dirt:
            continue
        if found:
            start, end = found[-1]
            if sum(metres[end:i]) < JOIN_GAP_M:
                found[-1] = (start, i + 1)
                continue
        found.append((i, i + 1))
    return found


def strays(
    way_ids: Sequence[int],
    metres: Sequence[float],
    dirt: frozenset[int],
    kept: frozenset[int],
) -> list[tuple[int, int]]:
    """The runs on dirt trails none of whose trails is in `kept` (the trails touched)."""
    return [
        (a, b) for a, b in runs(way_ids, metres, dirt) if not any(w in kept for w in way_ids[a:b])
    ]


def block_ring(lon: float, lat: float, bearing: float) -> list[list[float]]:
    """The strip BLOCK_ALONG_M along `bearing` (degrees) and BLOCK_ACROSS_M across it, centred
    on (lon, lat): a closed ring of [lon, lat] for the router's `exclude_polygons`."""
    m_lat = 110_540.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    along = math.radians(bearing)
    ax, ay = math.sin(along) * BLOCK_ALONG_M / 2, math.cos(along) * BLOCK_ALONG_M / 2
    cx, cy = math.cos(along) * BLOCK_ACROSS_M / 2, -math.sin(along) * BLOCK_ACROSS_M / 2
    corners = [(-ax - cx, -ay - cy), (ax - cx, ay - cy), (ax + cx, ay + cy), (-ax + cx, -ay + cy)]
    ring = [[round(lon + x / m_lon, 7), round(lat + y / m_lat, 7)] for x, y in corners]
    return [*ring, ring[0]]


def stray_rings(
    pieces: Sequence, ways: dict[int, str], kept: frozenset[int], any_dirt: bool = False
) -> list[list[list[float]]]:
    """A strip across each stray run of `pieces` (`core.routing.Piece`: way_id, lon and lat at
    its middle, metres, heading), to leave it out by: at the middle of its longest stretch on a
    dirt trail, along it. A run on dirt trails (REASON) is a stray where none of it is `kept`,
    and never with `any_dirt`; a run on singletrack is too, but for the singletrack in `kept`
    itself (Ride's "End mountain biking" from on one: that trail alone, never one joined to it,
    so the way off takes no harder trail)."""
    ids = [p.way_id for p in pieces]
    metres = [p.metres for p in pieces]
    dirt = frozenset(w for w, reason in ways.items() if reason == REASON)
    singletrack = frozenset(ways) - dirt
    found = [] if any_dirt else strays(ids, metres, dirt, kept)
    found += runs(ids, metres, singletrack - kept)
    rings: list[list[list[float]]] = []
    for a, b in found:
        on_dirt = [p for p in pieces[a:b] if p.way_id in ways]
        longest = max(on_dirt, key=lambda p: (_bearing(p) is not None, p.metres))
        rings.append(block_ring(longest.lon, longest.lat, _bearing(longest) or 0.0))
    return rings


def _bearing(piece) -> float | None:
    """The way a piece runs, degrees: its own bearing where it has one, else the heading its
    edge begins on (None from a trace without headings)."""
    bearing = getattr(piece, "bearing", None)
    return bearing if bearing is not None else piece.heading_in
