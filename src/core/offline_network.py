"""The road network around a route, for the phone to search with no signal (off-grid riding;
Stephen, 2026-11-12: "the one mile would be a default, with a whole region pack an optional
download").

Reads the live `offline_way` table (`pipeline.offline_network`), takes the ways within
`CORRIDOR_M` of the route's line, cuts them at the junctions among them, and answers in the format
frontend lib/offlineRouter.ts reads (v1). Map data for an area: nothing about the rider is kept or
logged.
"""

from __future__ import annotations

from collections.abc import Sequence

from django.conf import settings
from django.db import DatabaseError, connection, transaction

from pipeline.offline_network import AVOID_LEVEL2, OfflineWay, split_edges
from pipeline.schema import validate_schema_name
from routemaker import calm

from . import presets

VERSION = 1
# Coordinates as whole millionths of a degree (lib/offlineRouter.ts GRAPH_DEG).
SCALE = 1_000_000
# About a mile either side of the line (Stephen, 2026-11-12: "the one mile would be a default").
CORRIDOR_M = 1609
# At most this many ways in one answer, so a long ride through the city stays a download of a few MB
# at most. Our default, unmeasured.
MAX_WAYS = 40_000
# The line is simplified to about this (degrees, ~30 ft) before the search, so a long route's
# thousands of points do not slow the corridor query; a mile's width hides the difference.
SIMPLIFY_DEG = 0.0003
# At most this many points of the route's line are read from a request.
MAX_LINE_POINTS = 20_000
# The corridor's buffer is cut into pieces of at most this many vertices, so the GiST index finds
# the ways along a long or diagonal route rather than inside its whole bounding box.
SUBDIVIDE_VERTICES = 64
# The longest the corridor read may take before it is given up (the API answers 503). Our default,
# unmeasured.
TIMEOUT_MS = 5000


class NotBuilt(Exception):
    """The live map was built before the offline network existed: the next rebuild adds it."""


class TooSlow(Exception):
    """The corridor read ran past TIMEOUT_MS."""


def _table(schema: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [f"{schema}.offline_way"])
        return bool(cursor.fetchone()[0])


def corridor_ways(
    line: Sequence[tuple[float, float]], width_m: float = CORRIDOR_M
) -> list[OfflineWay]:
    """The ways within `width_m` of the line, at most MAX_WAYS, nearest first."""
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not _table(schema):
        raise NotBuilt
    wkt = "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in line) + ")"
    # The buffer in metres (geography), cut into small pieces that the geometry index can match one
    # by one; a way touching two pieces is taken once.
    query = f"""
        WITH route AS (SELECT ST_Simplify(ST_GeomFromText(%s, 4326), %s) AS g),
        pieces AS (
            SELECT ST_Subdivide(ST_Buffer(route.g::geography, %s)::geometry, %s) AS p FROM route
        ),
        near AS (
            SELECT DISTINCT w.osm_way_id
            FROM pieces JOIN {schema}.offline_way AS w ON ST_Intersects(w.geometry, pieces.p)
        )
        SELECT w.osm_way_id, w.node_ids, ST_AsText(w.geometry), w.level2, w.flags,
               w.direction, w.name
        FROM near JOIN {schema}.offline_way AS w USING (osm_way_id), route
        ORDER BY w.geometry <-> route.g
        LIMIT %s
    """
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [str(TIMEOUT_MS)])
            cursor.execute(query, [wkt, SIMPLIFY_DEG, width_m, SUBDIVIDE_VERTICES, MAX_WAYS])
            rows = cursor.fetchall()
    except DatabaseError as error:
        if "statement timeout" in str(error) or "canceling statement" in str(error):
            raise TooSlow from error
        raise
    return [
        OfflineWay(
            osm_id=int(way_id),
            node_ids=tuple(int(n) for n in node_ids),
            coordinates=_points(text),
            level2=int(level2),
            flags=int(flags),
            direction=int(direction),
            name=name,
        )
        for way_id, node_ids, text, level2, flags, direction, name in rows
    ]


def _points(wkt: str) -> tuple[tuple[float, float], ...]:
    inner = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
    return tuple((float(x), float(y)) for x, y in (pair.split() for pair in inner.split(",")))


def graph_of(ways: Sequence[OfflineWay]) -> dict:
    """The network as lib/offlineRouter.ts reads it (v1): nodes, edges of six, shapes, names."""
    edges = split_edges(ways)
    index: dict[int, int] = {}
    nodes: list[int] = []
    names: list[str] = []
    name_at: dict[str, int] = {}
    flat: list[int] = []
    shapes: list[list[int] | int] = []

    def node(osm_id: int, point: tuple[float, float]) -> int:
        at = index.get(osm_id)
        if at is None:
            at = index[osm_id] = len(nodes) // 2
            nodes.extend((round(point[0] * SCALE), round(point[1] * SCALE)))
        return at

    for edge in edges:
        a = node(edge.a_node, edge.coordinates[0])
        b = node(edge.b_node, edge.coordinates[-1])
        if edge.name:
            if edge.name not in name_at:
                name_at[edge.name] = len(names)
                names.append(edge.name)
            name = name_at[edge.name]
        else:
            name = -1
        flat.extend((a, b, round(edge.length_m, 1), edge.level2, edge.flags, name))
        inner = edge.coordinates[1:-1]
        shapes.append(
            [v for lon, lat in inner for v in (round(lon * SCALE), round(lat * SCALE))]
            if inner
            else 0
        )
    return {"v": VERSION, "nodes": nodes, "edges": flat, "shapes": shapes, "names": names}


def corridor_graph(line: Sequence[tuple[float, float]], width_m: float = CORRIDOR_M) -> dict:
    """The network within `width_m` of the line. NotBuilt before a rebuild has written it;
    TooSlow past TIMEOUT_MS."""
    return graph_of(corridor_ways(line[:MAX_LINE_POINTS], width_m))


def level_factors(
    preset_name: str, stress: int | None = None, carrying: str | None = None
) -> list[float]:
    """By stress level times 2 (index 2 to 10; 0 and 1 unused), the multiple of a stretch's
    riding time the phone's search charges for it: the ride's own calm metres per metre
    (`routemaker.calm.multiplier`), the figure the route ranking and the rolling chart price each
    level at for this ride type and stress slider, so the offline way back prefers the levels the
    server's plan would. Facility classes are left out (the network does not carry them). An
    unknown ride type is priced as Default, and a load the ride type does not take as its own
    first."""
    if preset_name not in presets.PRESETS:
        preset_name = "default"
    own = presets.PRESETS[preset_name].carrying
    if carrying is not None and (own is None or carrying not in own):
        carrying = None
    dial = presets.stress_start(preset_name, carrying) if stress is None else int(stress)
    exposure = presets.exposure_for(preset_name, carrying)
    pricing = calm.Pricing(
        use_roads=presets.use_roads_for(dial),
        rate=presets.calm_rate_for(dial),
        weights=(exposure.lts3, exposure.lts4, exposure.avoid),
        maxcalm=presets.maxcalm_for(dial),
    )
    factors = [1.0, 1.0]
    for level2 in range(2, AVOID_LEVEL2 + 1):
        tier = 5 if level2 == AVOID_LEVEL2 else level2 // 2
        half = level2 != AVOID_LEVEL2 and level2 % 2 == 1
        value = calm.multiplier(tier, None, pricing, half)
        factors.append(round(max(value or 1.0, 1.0), 3))
    # Avoid costs at least twice LTS 4 offline: the server charges its entry on top of the level
    # (the alley mark and `quiet_cost_s`), which the network does not carry. Our default,
    # unmeasured.
    factors[AVOID_LEVEL2] = max(factors[AVOID_LEVEL2], round(2 * factors[8], 3))
    return factors
