"""What the zoomed-out map leaves out of the bike network, and how it joins it up (`overview`).

The owner, 2026-10-23, of the city at zoom 12-13: "There's still a bunch of weird orphan
streets. If it doesn't connect to anything, don't include it." "Or try to see if you can make
a connection through <LTS3 roads." And of the suburbs: "There's also all these cul-de-sacs.
They aren't useful for transportation". So, after the popular corridors are set and tidied
(`pipeline.bikeshare_corridors.tidy`), each segment row gets an `overview` mark:

- OVERVIEW_LINK: a calm street (LTS 1-2, not a sidewalk) on the shortest way, no longer than
  LINK_MAX_M, from a piece of the bike network that joins nothing (ORPHAN_MIN_M) to the rest
  of it; and a short gap between two bike facilities (`bikeshare_corridors.tidy`). The map
  draws it with the network's main ways from zoom 12.
- OVERVIEW_ORPHAN: a piece of the bike network (a bike facility, a popular corridor, a named
  trail, a road closed to cars at set times, a long calm street: NETWORK_SQL) under
  ORPHAN_MIN_M in all that no such street joins to the rest. The map leaves it out until
  zoom 14.
- OVERVIEW_SPUR: a street that only leads to itself: a cul-de-sac, a dead end, or a tree of
  them, found by pruning the street graph's dead ends back for up to SPUR_MAX_M (so a long
  rural spur to a town stays). Sidewalks are left out of the graph (they would close every
  cul-de-sac into a loop); a path out of the end (a cut-through) keeps the street. The bike
  network itself is never pruned. The map leaves it out until zoom 14.

The work is done in boxes of BOX_DEG with a margin of MARGIN_DEG round each, wider than any
of the distances above, so a box sees everything that decides its rows; a row belongs to the
box its first point is in. Display only: routing reads none of it.
"""

from __future__ import annotations

import heapq
import logging
from collections import defaultdict

from .schema import (
    BIKE_POPULAR_COLUMN,
    CALM_ROAD_MAX_TIER,
    CALM_RUN_COLUMN,
    CAR_FREE_COLUMN,
    FACILITY_COLUMN,
    FACILITY_SHOWN_COLUMN,
    METRES_PER_MILE,
    MTB_ONLY_COLUMN,
    OVERVIEW_COLUMN,
    OVERVIEW_CONNECTOR,
    OVERVIEW_LINK,
    OVERVIEW_ORPHAN,
    OVERVIEW_SPUR,
    RIDE_ROAD_RUN_MI,
    ROADSIDE_COLUMN,
    STRAY_ZOOM_COLUMN,
    TRAIL_NAME_COLUMN,
    validate_schema_name,
)

logger = logging.getLogger(__name__)

ORPHAN_MIN_M = 800.0  # about half a mile
LINK_MAX_M = 400.0  # about a quarter mile
SPUR_MAX_M = 800.0
# The streets a link may use: LTS 1 and 2 ("<LTS3 roads").
LINK_MAX_TIER = CALM_ROAD_MAX_TIER

BOX_DEG = 0.05  # about 3.5 mi east-west, 3.4 mi north-south
MARGIN_DEG = 0.02  # about 1 mi, more than every distance above

# Vertex coordinates are matched at 1e-7 degrees (about 1 cm), OSM's own precision.
_GRID = 10_000_000

# The bike network as the zoomed-out map draws it (frontend/src/stressStyle.js, the city
# ladder): a bike facility, a popular corridor, a link, a named trail, a road closed to cars at
# set times, a long calm street.
NETWORK_SQL = (
    f"(COALESCE(s.{FACILITY_SHOWN_COLUMN}, s.{FACILITY_COLUMN}) <> 'none'"
    f" OR s.{BIKE_POPULAR_COLUMN} >= 1"
    f" OR s.{OVERVIEW_COLUMN} IN ({OVERVIEW_LINK}, {OVERVIEW_CONNECTOR})"
    f" OR s.{TRAIL_NAME_COLUMN} IS NOT NULL OR cardinality(s.{CAR_FREE_COLUMN}) > 0"
    f" OR (s.stress_tier <= {CALM_ROAD_MAX_TIER} AND NOT s.is_trail_class"
    f" AND COALESCE(s.{CALM_RUN_COLUMN}, 0) >= {round(RIDE_ROAD_RUN_MI * METRES_PER_MILE)}))"
)
# A sidewalk: a walkway beside a road with no bike facility.
SIDEWALK_SQL = (
    f"(s.is_trail_class AND COALESCE(s.{FACILITY_SHOWN_COLUMN}, s.{FACILITY_COLUMN}) = 'none'"
    f" AND COALESCE(s.{ROADSIDE_COLUMN}, false))"
)

_GRAPH = """
WITH cand AS (
    SELECT s.id, s.geometry, s.stress_tier AS tier, {network} AS net, {sidewalk} AS sidewalk,
           ST_X(ST_StartPoint(s.geometry)) >= %(west)s
           AND ST_X(ST_StartPoint(s.geometry)) < %(east)s
           AND ST_Y(ST_StartPoint(s.geometry)) >= %(south)s
           AND ST_Y(ST_StartPoint(s.geometry)) < %(north)s AS own
    FROM {schema}.segment AS s
    WHERE s.map_class = 'road' AND NOT s.{mtb}
      AND s.geometry && ST_MakeEnvelope(%(west)s - %(margin)s, %(south)s - %(margin)s,
                                        %(east)s + %(margin)s, %(north)s + %(margin)s, 4326)
),
pts AS (
    SELECT c.id, d.path[1] AS n, d.geom AS g,
           round(ST_X(d.geom) * {grid})::bigint AS kx,
           round(ST_Y(d.geom) * {grid})::bigint AS ky
    FROM cand AS c CROSS JOIN LATERAL ST_DumpPoints(c.geometry) AS d
),
shared AS (
    SELECT kx, ky FROM pts GROUP BY kx, ky HAVING count(DISTINCT id) > 1
),
steps AS (
    SELECT id, n, kx, ky,
           COALESCE(ST_DistanceSphere(lag(g) OVER w, g), 0) AS step,
           max(n) OVER (PARTITION BY id) AS last
    FROM pts
    WINDOW w AS (PARTITION BY id ORDER BY n)
),
along AS (
    SELECT *, sum(step) OVER (PARTITION BY id ORDER BY n) AS at_m FROM steps
)
SELECT a.id, a.kx, a.ky, a.at_m, c.tier, c.net, c.sidewalk, c.own
FROM along AS a JOIN cand AS c ON c.id = a.id
WHERE a.n = 1 OR a.n = a.last
   OR EXISTS (SELECT 1 FROM shared AS h WHERE h.kx = a.kx AND h.ky = a.ky)
ORDER BY a.id, a.n
"""


class Graph:
    """A box's rows cut into pieces at their junctions."""

    def __init__(self, rows) -> None:
        # piece: (row, node a, node b, metres)
        self.pieces: list[tuple[int, tuple[int, int], tuple[int, int], float]] = []
        self.tier: dict[int, int] = {}
        self.net: set[int] = set()
        self.sidewalk: set[int] = set()
        self.own: set[int] = set()
        last: tuple[int, tuple[int, int], float] | None = None
        for row, kx, ky, at_m, tier, net, sidewalk, own in rows:
            node = (kx, ky)
            if last is not None and last[0] == row and last[1] != node:
                self.pieces.append((row, last[1], node, float(at_m) - last[2]))
            last = (row, node, float(at_m))
            if row not in self.tier:
                self.tier[row] = tier
                if net:
                    self.net.add(row)
                if sidewalk:
                    self.sidewalk.add(row)
                if own:
                    self.own.add(row)


def _components(graph: Graph) -> list[tuple[set[int], set[tuple[int, int]], float]]:
    """The bike network's connected pieces: (rows, nodes, metres)."""
    parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for row, a, b, _ in graph.pieces:
        if row in graph.net:
            parent[find(a)] = find(b)
    rows: dict = defaultdict(set)
    nodes: dict = defaultdict(set)
    metres: dict = defaultdict(float)
    for row, a, b, m in graph.pieces:
        if row in graph.net:
            root = find(a)
            rows[root].add(row)
            nodes[root].update((a, b))
            metres[root] += m
    return [(rows[r], nodes[r], metres[r]) for r in rows]


def _link(graph: Graph, start: set[tuple[int, int]], targets: set[tuple[int, int]]):
    """The rows of the shortest way, no longer than LINK_MAX_M, along calm streets from
    `start` to any of `targets`; None where there is none."""
    adjacent: dict = defaultdict(list)
    for row, a, b, m in graph.pieces:
        if row in graph.sidewalk or graph.tier[row] > LINK_MAX_TIER:
            continue
        adjacent[a].append((b, m, row))
        adjacent[b].append((a, m, row))
    best = {node: 0.0 for node in start}
    came: dict = {}
    queue = [(0.0, node) for node in start]
    heapq.heapify(queue)
    while queue:
        d, node = heapq.heappop(queue)
        if d > best.get(node, float("inf")):
            continue
        if node in targets:
            rows = set()
            while node in came:
                node, row = came[node]
                rows.add(row)
            return rows
        for other, m, row in adjacent[node]:
            nd = d + m
            if nd <= LINK_MAX_M and nd < best.get(other, float("inf")):
                best[other] = nd
                came[other] = (node, row)
                heapq.heappush(queue, (nd, other))
    return None


def _spurs(graph: Graph, keep: set[int]) -> set[int]:
    """The rows pruned away as dead ends (SPUR_MAX_M), never one of `keep`."""
    adjacent: dict = defaultdict(set)
    pieces = [p for p in graph.pieces if p[0] not in graph.sidewalk and p[1] != p[2]]
    for i, (_, a, b, _) in enumerate(pieces):
        adjacent[a].add(i)
        adjacent[b].add(i)
    hang: dict = defaultdict(float)
    gone: set[int] = set()
    queue = [node for node, edges in adjacent.items() if len(edges) == 1]
    while queue:
        node = queue.pop()
        if len(adjacent[node]) != 1:
            continue
        i = next(iter(adjacent[node]))
        row, a, b, m = pieces[i]
        if row in keep or hang[node] + m > SPUR_MAX_M:
            continue
        other = b if a == node else a
        adjacent[node].discard(i)
        adjacent[other].discard(i)
        gone.add(i)
        hang[other] = max(hang[other], hang[node] + m)
        if len(adjacent[other]) == 1:
            queue.append(other)
    rows_left = {pieces[i][0] for i in range(len(pieces)) if i not in gone}
    return {pieces[i][0] for i in gone} - rows_left


def _graphs(cursor, schema: str, sql: str):
    """Each box's Graph (BOX_DEG, MARGIN_DEG) that has rows of its own."""
    cursor.execute(f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
                   f"(SELECT ST_Extent(geometry) AS e FROM {schema}.segment) AS t")  # fmt: skip
    west, south, east, north = cursor.fetchone()
    if west is None:
        return
    x = west
    while x <= east:
        y = south
        while y <= north:
            box = {"west": x, "south": y, "east": x + BOX_DEG, "north": y + BOX_DEG,
                   "margin": MARGIN_DEG}  # fmt: skip
            cursor.execute(sql, box)
            graph = Graph(cursor.fetchall())
            if graph.own:
                yield graph
            y += BOX_DEG
        x += BOX_DEG


def mark(schema: str) -> dict[str, int]:
    """Set `overview` (OVERVIEW_LINK, OVERVIEW_ORPHAN, OVERVIEW_SPUR) on the staging table.
    Returns the rows of each, for the log."""
    from django.db import connection

    from .writers import refuse_live_schema

    validate_schema_name(schema)
    refuse_live_schema(schema)
    sql = _GRAPH.format(
        schema=schema,
        network=NETWORK_SQL,
        sidewalk=SIDEWALK_SQL,
        mtb=MTB_ONLY_COLUMN,
        grid=_GRID,
    )
    links: set[int] = set()
    orphans: set[int] = set()
    spurs: set[int] = set()
    with connection.cursor() as cursor:
        for graph in _graphs(cursor, schema, sql):
            found = _box(graph)
            links |= found[0]
            orphans |= found[1]
            spurs |= found[2]
        spurs -= links | orphans
        for value, ids in (
            (OVERVIEW_LINK, links),
            (OVERVIEW_ORPHAN, orphans),
            (OVERVIEW_SPUR, spurs),
        ):
            cursor.execute(
                f"UPDATE {schema}.segment SET {OVERVIEW_COLUMN} = %s "
                f"WHERE id = ANY(%s::bigint[]) AND {OVERVIEW_COLUMN} = 0",
                [value, sorted(ids)],
            )
    return {"links": len(links), "orphans": len(orphans), "spurs": len(spurs)}


def _box(graph: Graph) -> tuple[set[int], set[int], set[int]]:
    """A box's links (any row), orphans and spurs (its own rows)."""
    components = _components(graph)
    joined = set().union(*(nodes for _, nodes, m in components if m >= ORPHAN_MIN_M))
    links: set[int] = set()
    orphans: set[int] = set()
    for rows, nodes, metres in components:
        if metres >= ORPHAN_MIN_M or not rows & graph.own:
            continue
        way = _link(graph, nodes, joined) if joined else None
        if way is None:
            orphans |= rows & graph.own
        else:
            links |= way - graph.net
    spurs = _spurs(graph, graph.net | links) & graph.own
    return links, orphans, spurs


STRAY_MIN_M = 1609.344  # a mile

# The zoomed-out levels' ways that join into pieces under STRAY_MIN_M.
_STRAYS = """
WITH drawn AS (
    SELECT s.id, s.geometry, ST_Length(s.geometry::geography) AS m
    FROM {schema}.segment AS s
    WHERE s.map_class = 'road' AND ({where})
), pieces AS (
    SELECT id, m, ST_ClusterDBSCAN(geometry, eps := %(touch)s, minpoints := 1) OVER () AS piece
    FROM drawn
), short AS (
    SELECT piece FROM pieces GROUP BY piece HAVING sum(m) < %(stray_min)s
)
UPDATE {schema}.segment AS s SET {column} = %(zoom)s
FROM pieces AS p JOIN short USING (piece)
WHERE s.id = p.id AND s.{column} = 0
"""


def mark_strays(schema: str) -> dict[int, int]:
    """Set `stray_zoom` (STRAY_ZOOM_COLUMN): a way the z11 tiles draw in a piece under
    STRAY_MIN_M is left out at z11 and below (11); else one the z7-10 tiles draw in such a
    piece is left out there (10). The owner, 2026-10-23, circling short bits at zoom 10-11:
    "These bits too". Returns the rows at each zoom, for the log."""
    from django.db import connection

    from core import stress_tiles

    from .bikeshare_corridors import TOUCH_DEG
    from .writers import refuse_live_schema

    validate_schema_name(schema)
    refuse_live_schema(schema)
    with connection.cursor() as cursor:
        optional = _columns(cursor, schema)
        stats = {}
        for zoom, level in ((11, stress_tiles.TRAILS_NEAR), (10, stress_tiles.TRAILS)):
            where, _ = stress_tiles.zoomed_out_where(level, optional)
            cursor.execute(
                _STRAYS.format(schema=schema, where=where, column=STRAY_ZOOM_COLUMN),
                {"touch": TOUCH_DEG, "stray_min": STRAY_MIN_M, "zoom": zoom},
            )
            stats[zoom] = cursor.rowcount
    return stats


# THE TRAILS JOINED UP ZOOMED OUT ("make connections across from the MBT to Rock Creek trail
# and to the anactostia riverwalk trail system. Include the minor trails and connections to
# them."). What the z11 tiles draw (`core.stress_tiles.zoomed_out_where`) and every off-road
# path (a minor trail) fall into connected pieces; from each piece the calmest way to the
# nearest other piece (CONNECT_COST, by tier; sidewalks left out) no costlier than
# CONNECT_MAX_M, or MAJOR_CONNECT_MAX_M between two pieces of a mile or more (STRAY_MIN_M), is
# marked OVERVIEW_CONNECTOR, and so is every minor trail in a piece that then reaches a mile.
CONNECT_COST = {1: 1.0, 2: 1.15, 3: 2.0, 4: 4.0}
CONNECT_MAX_M = 800.0
MAJOR_CONNECT_MAX_M = 3000.0

_MINOR_TRAIL_SQL = (
    f"(COALESCE(s.{FACILITY_SHOWN_COLUMN}, s.{FACILITY_COLUMN}) = 'path'"
    f" AND NOT s.{MTB_ONLY_COLUMN})"
)

_PIECES_OUT = """
WITH drawn AS (
    SELECT s.id, s.geometry, ST_Length(s.geometry::geography) AS m, ({where}) AS kept
    FROM {schema}.segment AS s
    WHERE s.map_class = 'road' AND (({where}) OR {minor})
), pieces AS (
    SELECT id, m, kept,
           ST_ClusterDBSCAN(geometry, eps := %(touch)s, minpoints := 1) OVER () AS piece
    FROM drawn
)
SELECT id, kept, piece, sum(m) OVER (PARTITION BY piece) FROM pieces
"""


def _connect_box(graph: Graph, piece_of: dict[int, int], metres: dict[int, float], joined):
    """The rows of the calmest ways from each piece with rows of the box's own to its nearest
    other piece (and, for a piece of a mile or more, its nearest such piece)."""
    adjacent: dict = defaultdict(list)
    node_piece: dict = {}
    for row, a, b, m in graph.pieces:
        piece = piece_of.get(row)
        if piece is not None:
            node_piece[a] = node_piece[b] = piece
            adjacent[a].append((b, 0.0, row))
            adjacent[b].append((a, 0.0, row))
            continue
        cost = CONNECT_COST.get(graph.tier[row])
        if row in graph.sidewalk or cost is None:
            continue
        adjacent[a].append((b, m * cost, row))
        adjacent[b].append((a, m * cost, row))
    nodes_of: dict = defaultdict(list)
    for node, piece in node_piece.items():
        nodes_of[piece].append(node)
    found: set[int] = set()
    for piece in {piece_of[row] for row in graph.own if row in piece_of}:
        searches = [(CONNECT_MAX_M, False)]
        if metres[joined(piece)] >= STRAY_MIN_M:
            searches.append((MAJOR_CONNECT_MAX_M, True))
        for limit, major in searches:
            best = dict.fromkeys(nodes_of[piece], 0.0)
            came: dict = {}
            queue = [(0.0, n) for n in nodes_of[piece]]
            heapq.heapify(queue)
            while queue:
                d, node = heapq.heappop(queue)
                if d > best.get(node, float("inf")):
                    continue
                other = node_piece.get(node)
                if other is not None and joined(other) != joined(piece):
                    if major and metres[joined(other)] < STRAY_MIN_M:
                        continue
                    while node in came:
                        node, row = came[node]
                        if row not in piece_of:
                            found.add(row)
                    joined(piece, other)
                    break
                for nxt, cost, row in adjacent[node]:
                    nd = d + cost
                    if nd <= limit and nd < best.get(nxt, float("inf")):
                        best[nxt] = nd
                        came[nxt] = (node, row)
                        heapq.heappush(queue, (nd, nxt))
    return found


def connect(schema: str) -> dict[str, int]:
    """Mark OVERVIEW_CONNECTOR on the staging table (see above). Returns the rows marked."""
    from django.db import connection

    from core import stress_tiles

    from .bikeshare_corridors import TOUCH_DEG
    from .writers import refuse_live_schema

    validate_schema_name(schema)
    refuse_live_schema(schema)
    with connection.cursor() as cursor:
        optional = _columns(cursor, schema)
        where, _ = stress_tiles.zoomed_out_where(stress_tiles.TRAILS_NEAR, optional)
        cursor.execute(
            _PIECES_OUT.format(schema=schema, where=where, minor=_MINOR_TRAIL_SQL),
            {"touch": TOUCH_DEG},
        )
        piece_of: dict[int, int] = {}
        metres: dict[int, float] = {}
        minor: dict[int, int] = {}
        for row, kept, piece, piece_m in cursor.fetchall():
            piece_of[row] = piece
            metres[piece] = float(piece_m)
            if not kept:
                minor[row] = piece
        parent: dict[int, int] = {}

        def joined(a: int, b: int | None = None) -> int:
            while parent.setdefault(a, a) != a:
                a = parent[a]
            if b is not None:
                root = joined(b)
                if root != a:
                    parent[root] = a
                    metres[a] = metres[a] + metres[root]
            return a

        sql = _GRAPH.format(
            schema=schema,
            network=NETWORK_SQL,
            sidewalk=SIDEWALK_SQL,
            mtb=MTB_ONLY_COLUMN,
            grid=_GRID,
        )
        ways: set[int] = set()
        for graph in _graphs(cursor, schema, sql):
            ways |= _connect_box(graph, piece_of, metres, joined)
        trails = {row for row, piece in minor.items() if metres[joined(piece)] >= STRAY_MIN_M}
        cursor.execute(
            f"UPDATE {schema}.segment SET {OVERVIEW_COLUMN} = {OVERVIEW_CONNECTOR} "
            f"WHERE id = ANY(%s::bigint[])",
            [sorted(ways | trails)],
        )
    return {"connecting ways": len(ways), "minor trails": len(trails)}


def _columns(cursor, schema: str) -> frozenset[str]:
    cursor.execute(
        "SELECT array_agg(column_name::text) FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = 'segment'",
        [schema],
    )
    return frozenset(cursor.fetchone()[0] or ())
