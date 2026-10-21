"""The popular bike corridors: Capital Bikeshare's dock-to-dock trips routed over the
segment table, and each street's share of them (`bike_trips`, `bike_popular`).

The owner, 2026-10-21: "Are there any good open source cycling heatmaps, those corridors
should be shown first", then "Actually, use the Cabi heatmap if you can, and make those
streets show more pronounced than other roads.", because the map's boldest lines today are
the busy roads, which "is basically showing where not to cycle"; and "Where it's out
further, we can mostly focus on the longer low-stress routes too."

Capital Bikeshare publishes each trip's docks, not its path
(`scripts/build_bikeshare_trips.py`, which writes the counts this reads). So the corridors
are modelled: every pair of docks with trips between them is routed over the drawn roads
and paths (`map_class` road, not a mountain-bike trail) by a plain bike cost, each piece's
length times TIER_COST of its tier (PATH_COST on a traffic-free path), both ways alike,
and every piece on the way takes the pair's trips a day. The cost leans away from busy
roads about as much as a typical bikeshare rider does, not as far as the planner's
routing: the corridors are where riders go, not where the planner would send them. A
segment row's `bike_trips` is the most trips a day any piece of it carries, rounded; its
`bike_popular` the class POPULAR_TRIPS_A_DAY puts that in (0 to 3), which the stress tiles
carry as `popular` and the map draws wider for (frontend/src/stressStyle.js).

Pieces are cut at every vertex two drawn ways share (OSM joins two roads at a shared node;
a bridge shares none with the road beneath it), as in `pipeline.calm_roads`. A dock is
placed at the nearest junction within SNAP_M; a dock with none (a new one past the
extract's edge) is left out with its trips, and the rebuild logs how many.

Optional, like the scenic layer: without `bikeshare-trips.json` in the reference
directory every row keeps `bike_popular` 0 and the map draws as it did, and the rebuild
logs that it is absent.
"""

from __future__ import annotations

import heapq
import json
import logging
import math
from array import array
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

from .schema import (
    BIKE_POPULAR_COLUMN,
    BIKE_TRIPS_COLUMN,
    FACILITY_COLUMN,
    MTB_ONLY_COLUMN,
    validate_schema_name,
)

logger = logging.getLogger(__name__)

FILE_NAME = "bikeshare-trips.json"

# The bike cost of a metre at each tier (1 to 5, Avoid), and on a traffic-free path.
# PROPOSALS: a rider takes a calm street over a busy one for a little extra distance and
# a trail for a little less, but bikeshare trips are short and direct, so the busy road
# still carries the trips where it is much the shorter way.
TIER_COST = {1: 1.0, 2: 1.15, 3: 1.5, 4: 2.2, 5: 4.0}
PATH_COST = 0.9

# How far (in metres; about 800 ft) a dock may be from the junction it is placed at.
SNAP_M = 250.0

# Trips a day a row needs for each class, highest first. PROPOSALS, to be measured on the
# first build with the file (the rebuild logs the miles in each class): about 11,900 trips
# a day over 870 docks (October 2025 to September 2026), half of them under 1 mi (1.5 km)
# as the crow flies.
POPULAR_TRIPS_A_DAY = ((3, 200.0), (2, 75.0), (1, 25.0))

# The docks' box is widened by this much (degrees, about 1.4 mi) for the graph, so a trip
# between two edge docks can still go round.
BOX_MARGIN_DEG = 0.02

# Vertex coordinates are matched at 1e-7 degrees (about 1 cm), OSM's own precision.
_GRID = 10_000_000

_PIECES = """
WITH cand AS (
    SELECT id, geometry,
           stress_tier AS tier, {facility} = 'path' AS path
    FROM {schema}.segment
    WHERE map_class = 'road' AND NOT {mtb}
      AND geometry && ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)
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
SELECT a.id, a.kx, a.ky, a.at_m, c.tier, c.path
FROM along AS a JOIN cand AS c ON c.id = a.id
WHERE a.n = 1 OR a.n = a.last
   OR EXISTS (SELECT 1 FROM shared AS s WHERE s.kx = a.kx AND s.ky = a.ky)
ORDER BY a.id, a.n
"""


def pieces_sql(schema: str) -> str:
    """The SELECT of the junctions along each drawn row in a box, in order along it."""
    validate_schema_name(schema)
    return _PIECES.format(schema=schema, facility=FACILITY_COLUMN, mtb=MTB_ONLY_COLUMN, grid=_GRID)


class Vertex(NamedTuple):
    """A junction or an end of a row (`_PIECES`'s columns)."""

    row: int
    kx: int
    ky: int
    at_m: float
    tier: int
    path: bool


class Trips(NamedTuple):
    """The installed counts: docks (lon, lat), pairs (i, j, trips) and the days covered."""

    docks: list[tuple[float, float]]
    pairs: list[tuple[int, int, int]]
    days: int


def load(path: Path) -> Trips | None:
    """The trip counts, or None (with a warning) where they are not installed."""
    if not path.exists():
        logger.warning(
            "%s is absent, so no popular bike corridor is derived: every street keeps "
            "bike_popular 0 and the map draws as before. Write it with "
            "scripts/build_bikeshare_trips.py and install it with "
            "scripts/install_reference_data.py --bikeshare-trips",
            path,
        )
        return None
    data = json.loads(path.read_text())
    docks = [(float(lon), float(lat)) for _id, lon, lat in data["stations"]]
    pairs = [(int(i), int(j), int(trips)) for i, j, trips in data["pairs"]]
    days = int(data["days"])
    if days <= 0:
        raise ValueError(f"{path}: days must be positive, not {days}")
    for i, j, _ in pairs:
        if not (0 <= i < len(docks) and 0 <= j < len(docks)):
            raise ValueError(f"{path}: pair ({i}, {j}) names a dock not in stations")
    return Trips(docks, pairs, days)


def box(docks: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    """(west, south, east, north) of the docks, widened by BOX_MARGIN_DEG."""
    lons = [lon for lon, _ in docks]
    lats = [lat for _, lat in docks]
    return (
        min(lons) - BOX_MARGIN_DEG,
        min(lats) - BOX_MARGIN_DEG,
        max(lons) + BOX_MARGIN_DEG,
        max(lats) + BOX_MARGIN_DEG,
    )


class Graph:
    """The pieces between junctions as an undirected graph (CSR adjacency)."""

    def __init__(self, vertices: Iterable[Vertex]):
        node_of: dict[tuple[int, int], int] = {}
        self.xy: list[tuple[int, int]] = []
        self.piece_row = array("q")
        self.piece_cost = array("d")
        ends_a = array("q")
        ends_b = array("q")
        previous: Vertex | None = None
        previous_node = -1
        for vertex in vertices:
            key = (vertex.kx, vertex.ky)
            node = node_of.get(key)
            if node is None:
                node = node_of[key] = len(self.xy)
                self.xy.append(key)
            if previous is not None and previous.row == vertex.row and node != previous_node:
                length = max(0.0, vertex.at_m - previous.at_m)
                rate = PATH_COST if vertex.path else TIER_COST.get(vertex.tier, TIER_COST[5])
                self.piece_row.append(vertex.row)
                self.piece_cost.append(length * rate)
                ends_a.append(previous_node)
                ends_b.append(node)
            previous, previous_node = vertex, node
        count = len(self.xy)
        degree = [0] * (count + 1)
        for a, b in zip(ends_a, ends_b, strict=True):
            degree[a] += 1
            degree[b] += 1
        self.start = array("q", [0] * (count + 1))
        for node in range(count):
            self.start[node + 1] = self.start[node] + degree[node]
        fill = list(self.start[:count])
        self.to = array("q", [0] * self.start[count])
        self.edge_piece = array("q", [0] * self.start[count])
        for piece, (a, b) in enumerate(zip(ends_a, ends_b, strict=True)):
            for here, there in ((a, b), (b, a)):
                self.to[fill[here]] = there
                self.edge_piece[fill[here]] = piece
                fill[here] += 1
        # The nodes by grid cell, for placing the docks.
        self._cell = max(1, round(SNAP_M / 111_320 * _GRID))
        self._cells: dict[tuple[int, int], list[int]] = {}
        for node, (kx, ky) in enumerate(self.xy):
            self._cells.setdefault((kx // self._cell, ky // self._cell), []).append(node)

    def nearest(self, lon: float, lat: float) -> int | None:
        """The node nearest (lon, lat) within SNAP_M, or None."""
        kx, ky = round(lon * _GRID), round(lat * _GRID)
        cx, cy = kx // self._cell, ky // self._cell
        squash = math.cos(math.radians(lat))
        best, best_m = None, SNAP_M
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for node in self._cells.get((cx + dx, cy + dy), ()):
                    nx, ny = self.xy[node]
                    metres = math.hypot((nx - kx) * squash, ny - ky) / _GRID * 111_320
                    if metres <= best_m:
                        best, best_m = node, metres
        return best

    def spread(self, origin: int, loads: dict[int, float], piece_trips: array) -> int:
        """Route from `origin` to every node in `loads` by least cost, and add each
        node's load to every piece on its way. Returns the loads it could not reach."""
        left = set(loads) - {origin}
        if not left:
            return 0
        dist = {origin: 0.0}
        pred: dict[int, tuple[int, int]] = {}
        settled: list[int] = []
        done: set[int] = set()
        heap = [(0.0, origin)]
        start, to, edge_piece, cost = self.start, self.to, self.edge_piece, self.piece_cost
        while heap and left:
            d, node = heapq.heappop(heap)
            if node in done:
                continue
            done.add(node)
            settled.append(node)
            left.discard(node)
            for k in range(start[node], start[node + 1]):
                there = to[k]
                if there in done:
                    continue
                nd = d + cost[edge_piece[k]]
                if nd < dist.get(there, math.inf):
                    dist[there] = nd
                    pred[there] = (edge_piece[k], node)
                    heapq.heappush(heap, (nd, there))
        # Each settled node's load (its own trips and every load beyond it) goes onto the
        # piece it was reached by, and on to the node it was reached from.
        carried = {node: load for node, load in loads.items() if node in done}
        for node in reversed(settled):
            load = carried.get(node)
            if not load or node == origin:
                continue
            piece, back = pred[node]
            piece_trips[piece] += load
            carried[back] = carried.get(back, 0.0) + load
        return len(left)


def corridor_trips(vertices: Iterable[Vertex], trips: Trips) -> tuple[dict[int, float], dict]:
    """{row: the most trips a day any piece of it carries}, and counts for the log."""
    graph = Graph(vertices)
    place = [graph.nearest(lon, lat) for lon, lat in trips.docks]
    by_origin: dict[int, dict[int, float]] = {}
    unplaced = 0.0
    for i, j, count in trips.pairs:
        a, b = place[i], place[j]
        a_day = count / trips.days
        if a is None or b is None:
            unplaced += a_day
            continue
        if a == b:
            continue
        # Route each pair once, from the lower node.
        a, b = min(a, b), max(a, b)
        loads = by_origin.setdefault(a, {})
        loads[b] = loads.get(b, 0.0) + a_day
    piece_trips = array("d", [0.0] * len(graph.piece_cost))
    unreached = 0
    for origin, loads in by_origin.items():
        unreached += graph.spread(origin, loads, piece_trips)
    rows: dict[int, float] = {}
    for piece, value in enumerate(piece_trips):
        if value > 0:
            row = graph.piece_row[piece]
            if value > rows.get(row, 0.0):
                rows[row] = value
    stats = {
        "docks": len(trips.docks),
        "docks placed": sum(node is not None for node in place),
        "trips a day": round(sum(c for _, _, c in trips.pairs) / trips.days),
        "trips a day at unplaced docks": round(unplaced),
        "pairs no route reached": unreached,
        "origins routed": len(by_origin),
        "nodes": len(graph.xy),
        "pieces": len(graph.piece_cost),
    }
    return rows, stats


def popular_class(trips_a_day: float) -> int:
    """0 to 3 by POPULAR_TRIPS_A_DAY."""
    for level, floor in POPULAR_TRIPS_A_DAY:
        if trips_a_day >= floor:
            return level
    return 0


def derive(schema: str, path: Path) -> dict:
    """Set `bike_trips` and `bike_popular` on the staging schema's rows the corridors
    reach, from the installed counts at `path`; a row a named corridor already put in a
    higher class (`pipeline.major_corridors`) keeps it. Returns counts for the log (empty when
    the file is absent)."""
    from django.db import connection

    validate_schema_name(schema)
    trips = load(path)
    if trips is None or not trips.pairs:
        return {}
    west, south, east, north = box(trips.docks)
    with connection.chunked_cursor() as cursor:
        cursor.execute(
            pieces_sql(schema), {"west": west, "south": south, "east": east, "north": north}
        )

        def vertices():
            while batch := cursor.fetchmany(20_000):
                for row, kx, ky, at_m, tier, is_path in batch:
                    yield Vertex(row, kx, ky, float(at_m), int(tier), bool(is_path))

        rows, stats = corridor_trips(vertices(), trips)
    if rows:
        ids = list(rows)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {schema}.segment AS s SET {BIKE_TRIPS_COLUMN} = v.trips, "
                f"{BIKE_POPULAR_COLUMN} = GREATEST(s.{BIKE_POPULAR_COLUMN}, v.popular) "
                "FROM unnest(%s::bigint[], %s::integer[], %s::smallint[]) "
                "AS v (id, trips, popular) WHERE s.id = v.id",
                [
                    ids,
                    [round(rows[row]) for row in ids],
                    [popular_class(rows[row]) for row in ids],
                ],
            )
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {BIKE_POPULAR_COLUMN}, round(sum(ST_Length(geometry::geography)) "
            f"/ 1609.344) FROM {schema}.segment WHERE {BIKE_POPULAR_COLUMN} > 0 "
            "GROUP BY 1 ORDER BY 1"
        )
        stats["miles by class"] = {int(level): int(mi) for level, mi in cursor.fetchall()}
    stats["rows with trips"] = len(rows)
    return stats
