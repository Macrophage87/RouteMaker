"""The calm roads of the z12-13 ride layer: continuous runs of LTS 1 and LTS 2 road that
end at a stressful junction (OWNER-DECISIONS 391, 402, 402a).

The owner, 2026-10-05: "For calm streets, I'm thinking more calm roads. Places someone
would likely want to ride for a while. In the cities that's just too dense." (402), and
"LTS2 counts. Suburban streets would rarely qualify because they tend to have a lot of
intersection stress rather than roadway stress." (402a). So a calm road's run is:

- made of named roads at LTS 1 or LTS 2 that the map draws (`map_class` road, not a trail,
  not a mountain-bike way: `trail_routes.is_calm_candidate`), whatever their class: a
  residential street counts as much as a rural road. An unnamed road has no run and does
  not join one (most unnamed LTS 1 roads are service roads, driveways, parking aisles and
  tracks: 12,832 of the 21,119 mi on the 2026-10-03 build);
- continuous: it follows the road straight on through each junction, across a change of
  name. Where only two calm roads meet (a way split for a tag change, a name that changes)
  it always goes on. At a junction of three or more it goes on along the road of its own
  name if that turns no more than `SAME_NAME_TURN_DEG`, else along the straightest one that
  turns no more than `STRAIGHT_ON_DEG`; the other roads there start runs of their own. A run
  is a line, not a network: a neighbourhood's grid of quiet streets is many short runs, not
  one long one;
- broken at every stressful junction: a node it shares with a road at LTS 3 or above
  (`BUSY_TIER`, Avoid included; the greater of the road's tier and its unsmoothed tier, as
  the junction model reads it), whether it crosses that road there or joins it. That is
  396's rule, under which a junction is major where "the crossed or joined road is rated
  LTS 3 or higher" or "the junction itself carries a stress rating": the route-time
  junction model (`routemaker.intersections`) gives a junction a rating of its own only
  where a road of `BUSY_TIER` or above is in it, so on the map's data the one test covers
  both. A bridge or an underpass shares no node with the road it passes and does not break
  a run.

The run's length is stored on each of its ways as `calm_run_m`; a way that a busy road
crosses in its middle is in two runs and keeps the longer. The z12-13 layer keeps a way whose
run is at least `pipeline.schema.RIDE_ROAD_RUN_MI` (`ride_layer_predicate`).

The junctions are read from the rows' shared vertices in SQL (OSM joins two roads at a shared
node, and the segment table keeps each way's nodes); the runs are put together here, in
Python (`runs_of`), from a list with one entry for each end of a row and each junction inside
one.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Iterable, Iterator
from typing import NamedTuple

from routemaker.intersections import BUSY_TIER

from .schema import (
    CALM_RUN_COLUMN,
    TRAIL_NAME_COLUMN,
    UNSMOOTHED_TIER_COLUMN,
    trails_predicate,
    validate_schema_name,
)

# How far a run may turn at a junction and still be the same run: along the road of its own
# name, a right angle and a little (a road that jogs, or turns a corner and keeps its name);
# along a road of another name, a gentle bend at most. PROPOSALS, measured with the length
# bar (docs/OPERATIONS.md, "The ride layer (z12-13)"). The bearings are on the ground
# (ST_Azimuth on geography), not in degrees of lon/lat, which at 39 N would put a turn up to
# about 13 degrees off (REBUILD-BUNDLE correctness review, nit 4).
SAME_NAME_TURN_DEG = 100.0
STRAIGHT_ON_DEG = 45.0

# Vertex coordinates are matched at 1e-7 degrees (about 1 cm), OSM's own precision: two rows
# share a vertex where they share an OSM node.
_GRID = 10_000_000

# The vertices the runs are put together from. Of the candidates (`calm_run_m` 0) that are
# named roads, not paths: each vertex that is an end of a row, is shared with another such
# row, or is shared with a busy road; in order along each row. Columns: the row, the node
# (numbered), the distance along the row to it, the bearings (degrees from north) from it back
# along the row and on along it (null past the row's ends), whether a busy road meets there,
# and the row's name (numbered).
_JUNCTIONS = """
WITH cand AS (
    SELECT id, geometry, dense_rank() OVER (ORDER BY {key}) AS name_id
    FROM {schema}.segment
    WHERE {calm} = 0 AND map_class = 'road' AND NOT is_trail_class AND NOT {trails}
      AND {key} IS NOT NULL
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
busy_pts AS (
    SELECT round(ST_X(d.geom) * {grid})::bigint AS kx,
           round(ST_Y(d.geom) * {grid})::bigint AS ky
    FROM {schema}.segment AS b CROSS JOIN LATERAL ST_DumpPoints(b.geometry) AS d
    WHERE b.map_class IN ('road', 'barred')
      AND GREATEST(b.stress_tier, COALESCE(b.{unsmoothed}, 0)) >= {busy_tier}
),
busy AS (
    SELECT DISTINCT kx, ky FROM busy_pts
),
steps AS (
    SELECT id, n, kx, ky, g,
           lag(g) OVER w AS prev, lead(g) OVER w AS next,
           COALESCE(ST_DistanceSphere(lag(g) OVER w, g), 0) AS step,
           max(n) OVER (PARTITION BY id) AS last
    FROM pts
    WINDOW w AS (PARTITION BY id ORDER BY n)
),
along AS (
    SELECT *, sum(step) OVER (PARTITION BY id ORDER BY n) AS at_m FROM steps
),
kept AS (
    SELECT a.id, a.n, a.kx, a.ky, a.at_m, a.g, a.prev, a.next, b.kx IS NOT NULL AS busy
    FROM along AS a
    LEFT JOIN busy AS b ON b.kx = a.kx AND b.ky = a.ky
    WHERE a.n = 1 OR a.n = a.last OR b.kx IS NOT NULL
       OR EXISTS (SELECT 1 FROM shared AS s WHERE s.kx = a.kx AND s.ky = a.ky)
)
SELECT k.id, dense_rank() OVER (ORDER BY k.kx, k.ky) AS node, k.at_m,
       degrees(ST_Azimuth(k.g::geography, k.prev::geography)) AS back,
       degrees(ST_Azimuth(k.g::geography, k.next::geography)) AS fwd,
       k.busy, c.name_id
FROM kept AS k JOIN cand AS c ON c.id = k.id
ORDER BY k.id, k.n
"""


def junctions_sql(schema: str) -> str:
    """The SELECT of the vertices the calm roads' runs are put together from."""
    from .trail_routes import NAME_KEY

    validate_schema_name(schema)
    return _JUNCTIONS.format(
        schema=schema,
        calm=CALM_RUN_COLUMN,
        key=NAME_KEY.format(name=TRAIL_NAME_COLUMN),
        trails=trails_predicate(True, True),
        unsmoothed=UNSMOOTHED_TIER_COLUMN,
        busy_tier=BUSY_TIER,
        grid=_GRID,
    )


class Junction(NamedTuple):
    """A vertex of a row where a run may start, end or go on (`_JUNCTIONS`'s columns)."""

    row: int
    node: int
    at_m: float
    back: float | None
    fwd: float | None
    busy: bool
    name: int


def turn_deg(a: float | None, b: float | None) -> float:
    """How far a rider turns at a junction coming in along the road that leaves it at
    bearing `a` and going out along bearing `b`: 0 straight on, 180 back the way they came.
    A missing bearing (two vertices in one place) is a full turn."""
    if a is None or b is None:
        return 180.0
    between = abs(a - b) % 360.0
    return 180.0 - min(between, 360.0 - between)


def pairs(ends: list[tuple[int, float | None, int]]) -> list[tuple[int, int]]:
    """Which of the run ends at one calm junction go on into which (`ends`: (piece end,
    bearing out, name)). Two ends always go on. Of three or more, the same-named pairs that
    turn no more than SAME_NAME_TURN_DEG first, then any pair that turns no more than
    STRAIGHT_ON_DEG, the least turn first; each end goes on into one other at most."""
    if len(ends) < 2:
        return []
    if len(ends) == 2:
        return [(ends[0][0], ends[1][0])]
    options = []
    for i, (end_a, bearing_a, name_a) in enumerate(ends):
        for end_b, bearing_b, name_b in ends[i + 1 :]:
            turn = turn_deg(bearing_a, bearing_b)
            same = name_a == name_b
            if (same and turn <= SAME_NAME_TURN_DEG) or turn <= STRAIGHT_ON_DEG:
                options.append((0 if same else 1, turn, end_a, end_b))
    options.sort()
    used: set[int] = set()
    chosen = []
    for _rank, _turn, end_a, end_b in options:
        if end_a in used or end_b in used:
            continue
        used.update((end_a, end_b))
        chosen.append((end_a, end_b))
    return chosen


def runs_of(junctions: Iterable[Junction]) -> dict[int, int]:
    """{row: the length in metres of the longest calm-road run it is in}, from the
    junctions in order along each row (`_JUNCTIONS`). A row is cut into pieces at its
    junctions; the pieces' ends meet at the nodes, where `pairs` says which go on into
    which, except at a busy node, where every run ends."""
    piece_row = array("q")
    piece_m = array("d")
    # Piece p's start is end 2p, its finish 2p + 1.
    at_node: dict[int, list[tuple[int, float | None, int]]] = {}
    busy_nodes: set[int] = set()
    previous: Junction | None = None
    for junction in junctions:
        if junction.busy:
            busy_nodes.add(junction.node)
        if previous is not None and previous.row == junction.row:
            piece = len(piece_m)
            piece_row.append(junction.row)
            piece_m.append(max(0.0, junction.at_m - previous.at_m))
            at_node.setdefault(previous.node, []).append((2 * piece, previous.fwd, previous.name))
            at_node.setdefault(junction.node, []).append(
                (2 * piece + 1, junction.back, junction.name)
            )
        previous = junction
    parent = list(range(len(piece_m)))

    def root(p: int) -> int:
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for node, ends in at_node.items():
        if node in busy_nodes:
            continue
        for end_a, end_b in pairs(ends):
            a, b = root(end_a // 2), root(end_b // 2)
            if a != b:
                parent[a] = b
    total: dict[int, float] = {}
    for p, length in enumerate(piece_m):
        r = root(p)
        total[r] = total.get(r, 0.0) + length
    runs: dict[int, int] = {}
    for p, row in enumerate(piece_row):
        # At least 1 m: 0 is what the rebuild writes for "not derived yet", and VALIDATE
        # refuses a build with a named candidate still at 0. A sub-metre piece that is a
        # run of its own (a 0.45 m two-point stub of a named trail, 2026-10-08) rounded
        # to 0 and failed a build whose derive had run to the end. Every floor that reads
        # the run is hundreds of metres or more, so 1 m filters out exactly as 0 did. The
        # paths' derive (`trail_routes._DERIVE_CALM_PATHS`) has the same floor.
        run = max(1, round(total[root(p)]))
        if run > runs.get(row, -1):
            runs[row] = run
    return runs


def _bearing(value) -> float | None:
    return None if value is None or math.isnan(value) else float(value)


# Junction rows fetched at a time: the region's are about 470,000 (2026-10-03 build), read
# through a server-side cursor so they are never all held at once.
FETCH_ROWS = 20_000


def iter_junctions(cursor, schema: str) -> Iterator[Junction]:
    """The junctions of the schema's calm-road candidates (`_JUNCTIONS`), on a cursor, a
    batch at a time."""
    cursor.execute(junctions_sql(schema))
    while rows := cursor.fetchmany(FETCH_ROWS):
        for row, node, at_m, back, fwd, busy, name in rows:
            yield Junction(row, node, float(at_m), _bearing(back), _bearing(fwd), bool(busy), name)


def derive(schema: str) -> int:
    """Set `calm_run_m` on the staging schema's named calm-road candidates (`runs_of`) and
    return the number of rows set. Every named candidate gets a run: its own ends are always
    among the junctions. Measured on a copy of the 2026-10-03 build: 34 s to read the
    junctions, 1 s to put the runs together, about 400 MB at the peak in a process of its
    own (docs/OPERATIONS.md, "The ride layer (z12-13)")."""
    from django.db import connection

    validate_schema_name(schema)
    with connection.chunked_cursor() as cursor:
        runs = runs_of(iter_junctions(cursor, schema))
    if not runs:
        return 0
    with connection.cursor() as cursor:
        rows = list(runs)
        cursor.execute(
            f"UPDATE {schema}.segment AS s SET {CALM_RUN_COLUMN} = v.run_m "
            "FROM unnest(%s::bigint[], %s::integer[]) AS v (id, run_m) WHERE s.id = v.id",
            [rows, [runs[row] for row in rows]],
        )
        return cursor.rowcount
