"""The road network around a route, for the phone to search with no signal (off-grid riding; Stephen, 2026-11-12:
"the one mile would be a default, with a whole region pack an optional download").

Reads the live `offline_way` table (`pipeline.offline_network`), takes the ways within `CORRIDOR_M` of the route's
line, cuts them at the junctions among them, and answers in the format frontend lib/offlineRouter.ts reads (v1).
Map data for an area: nothing about the rider is kept or logged.
"""

from __future__ import annotations

from collections.abc import Sequence

from django.conf import settings
from django.db import connection

from pipeline.offline_network import OfflineWay, split_edges
from pipeline.schema import validate_schema_name

VERSION = 1
# Coordinates as whole millionths of a degree (lib/offlineRouter.ts GRAPH_DEG).
SCALE = 1_000_000
# About a mile either side of the line (Stephen, 2026-11-12: "the one mile would be a default").
CORRIDOR_M = 1609
# At most this many ways in one answer, nearest the line first, so a long ride through the city stays a download of a
# few MB at most. Our default, unmeasured.
MAX_WAYS = 40_000
# The line is simplified to about this (degrees, ~30 ft) before the search, so a long route's thousands of points do
# not slow the corridor query; a mile's width hides the difference.
SIMPLIFY_DEG = 0.0003
# At most this many points of the route's line are read from a request.
MAX_LINE_POINTS = 20_000


class NotBuilt(Exception):
    """The live map was built before the offline network existed: the next rebuild adds it."""


def _table(schema: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [f"{schema}.offline_way"])
        return bool(cursor.fetchone()[0])


def corridor_ways(line: Sequence[tuple[float, float]], width_m: float = CORRIDOR_M) -> list[OfflineWay]:
    """The ways within `width_m` of the line, nearest first, at most MAX_WAYS."""
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    if not _table(schema):
        raise NotBuilt
    wkt = "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in line) + ")"
    # A box first (degrees: a mile is under 0.03 degrees of longitude here), then the true distance in metres.
    pad = width_m / 111_195 / 0.75
    query = f"""
        WITH route AS (SELECT ST_Simplify(ST_GeomFromText(%s, 4326), %s) AS g)
        SELECT w.osm_way_id, w.node_ids, ST_AsText(w.geometry), w.level2, w.flags, w.direction, w.name
        FROM {schema}.offline_way AS w, route
        WHERE w.geometry && ST_Expand(route.g, %s)
          AND ST_DWithin(w.geometry::geography, route.g::geography, %s)
        ORDER BY ST_Distance(w.geometry::geography, route.g::geography)
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(query, [wkt, SIMPLIFY_DEG, pad, width_m, MAX_WAYS])
        rows = cursor.fetchall()
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
    """The network as lib/offlineRouter.ts reads it (v1): nodes, edges in groups of six, shapes and names."""
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
        shapes.append([v for lon, lat in inner for v in (round(lon * SCALE), round(lat * SCALE))] if inner else 0)
    return {"v": VERSION, "nodes": nodes, "edges": flat, "shapes": shapes, "names": names}


def corridor_graph(line: Sequence[tuple[float, float]], width_m: float = CORRIDOR_M) -> dict:
    """The network within `width_m` of the line. Raises NotBuilt before the first rebuild that writes it."""
    return graph_of(corridor_ways(line[:MAX_LINE_POINTS], width_m))
