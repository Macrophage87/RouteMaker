"""State polygons from the rebuild's own extract, and each way's state.

OWNER-DECISIONS 108 and 112 give an unposted way its state's statutory speed
default, which needs to know the state. That was read from the `jurisdiction`
table's state layer, which a fresh deployment does not have until an instance
admin enters it - and live had none (review r1, B1: `select count(*) from
jurisdiction` is 0), so every way would have fallen back to the old class
tables in silence. The owner, 2026-09-30 (OWNER-DECISIONS 137): "From our OSM
data (Recommended)".

So each rebuild derives the states itself, from the `boundary=administrative`,
`admin_level=4` relations in the merged extract it is building from - the
unclipped one, whose relations are complete (`pipeline.source`: the clip
truncates a relation at the region's edge). Nothing is downloaded and the
`jurisdiction` table is not written: it stays the admin's, for the authority
layers it was made for, and the rebuild's answer is a function of the extract
alone, like everything else it computes.

A relation is named by its `ISO3166-2` tag (`US-DC` -> `DC`). Its member ways
are joined end to end into rings; an outer ring that does not close is
dropped and reported (a relation cut by an extract), and an inner ring is a
hole. Three passes over the file, keeping only the members' nodes, so memory
is the boundaries' and not the region's.

`way_states` places each way by its middle vertex in PostGIS, through a temp
table filled in chunks, and a vertex on a shared boundary goes to the state
listed first in STATE_PRIORITY - Maryland or Virginia before the District, the
reading with the higher default, which is this project's rule for an
ambiguous input. It logs the count per state and the time, and refuses when a
required state is missing: a rebuild that would read every District street at
the old table is not one to publish.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

logger = logging.getLogger(__name__)

# The states the coverage needs, whose absence refuses the rebuild.
REQUIRED_STATES = ("DC", "MD", "VA")
# Which state a point on a shared boundary goes to: the higher default first.
STATE_PRIORITY = ("MD", "VA", "WV", "PA", "DE", "DC")
CHUNK = 50_000


class StatesMissing(RuntimeError):
    """A required state's polygon is not in the extract, or placed no way."""


def _state_code(tags) -> str | None:
    iso = tags.get("ISO3166-2") or ""
    if iso.upper().startswith("US-") and len(iso) == 5:
        return iso[3:].upper()
    return None


def read_boundaries(pbf) -> dict[str, list[tuple[str, list[int]]]]:
    """{state: [(role, node ids of one member way)]}, from the extract."""
    import osmium

    members: dict[str, list[tuple[str, int]]] = defaultdict(list)

    class Relations(osmium.SimpleHandler):
        def relation(self, r):
            tags = r.tags
            if tags.get("boundary") != "administrative" or tags.get("admin_level") != "4":
                return
            state = _state_code(tags)
            if state is None:
                return
            for m in r.members:
                if m.type == "w":
                    members[state].append((m.role or "outer", m.ref))

    Relations().apply_file(str(pbf))
    wanted = {ref for rows in members.values() for _, ref in rows}
    refs: dict[int, list[int]] = {}

    class Ways(osmium.SimpleHandler):
        def way(self, w):
            if w.id in wanted:
                refs[w.id] = [n.ref for n in w.nodes]

    Ways().apply_file(str(pbf))
    return {
        state: [(role, refs[ref]) for role, ref in rows if ref in refs]
        for state, rows in members.items()
    }


def read_nodes(pbf, node_ids: set[int]) -> dict[int, tuple[float, float]]:
    import osmium

    at: dict[int, tuple[float, float]] = {}

    class Nodes(osmium.SimpleHandler):
        def node(self, n):
            if n.id in node_ids:
                at[n.id] = (n.location.lon, n.location.lat)

    Nodes().apply_file(str(pbf))
    return at


def rings(ways: Iterable[list[int]]) -> tuple[list[list[int]], int]:
    """Member ways joined end to end: (closed rings, open chains dropped)."""
    pending = [list(w) for w in ways if len(w) >= 2]
    closed: list[list[int]] = []
    dropped = 0
    while pending:
        ring = pending.pop()
        while ring[0] != ring[-1]:
            for i, w in enumerate(pending):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[-2::-1]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = w[:0:-1] + ring
                else:
                    continue
                pending.pop(i)
                break
            else:
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            closed.append(ring)
        else:
            dropped += 1
    return closed, dropped


def state_polygons(pbf) -> dict[str, object]:
    """{state: GEOS MultiPolygon (SRID 4326)} from the extract's boundaries."""
    from django.contrib.gis.geos import MultiPolygon, Polygon

    started = time.monotonic()
    boundaries = read_boundaries(pbf)
    at = read_nodes(pbf, {n for rows in boundaries.values() for _, ids in rows for n in ids})
    out: dict[str, object] = {}
    for state, rows in sorted(boundaries.items()):
        shapes = {}
        for role in ("outer", "inner"):
            ids = [ids for r, ids in rows if (r == "inner") == (role == "inner")]
            closed, dropped = rings(ids)
            if dropped:
                logger.warning(
                    "state %s: %d %s chain(s) do not close and were dropped", state, dropped, role
                )
            polys = []
            for ring in closed:
                coords = [at[n] for n in ring if n in at]
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    polys.append(Polygon(coords, srid=4326))
            shapes[role] = polys
        if not shapes["outer"]:
            logger.warning("state %s: no closed outer ring; not placed", state)
            continue
        geometry = MultiPolygon(shapes["outer"], srid=4326).buffer(0)
        for hole in shapes["inner"]:
            geometry = geometry.difference(hole)
        if geometry.geom_type == "Polygon":
            geometry = MultiPolygon(geometry, srid=4326)
        geometry.srid = 4326
        out[state] = geometry
    logger.info(
        "state polygons from %s: %s in %.1f s",
        pbf,
        ", ".join(sorted(out)) or "none",
        time.monotonic() - started,
    )
    return out


def way_states(
    ways: Sequence, polygons: dict, required: Sequence[str] | None = None
) -> dict[int, str]:
    """Each way's state by its middle vertex; refuses a missing required state
    (`required`, REQUIRED_STATES when not given)."""
    from django.db import connection

    required = REQUIRED_STATES if required is None else required
    missing = [s for s in required if s not in polygons]
    if missing:
        raise StatesMissing(
            f"no state polygon for {', '.join(missing)} in the extract's admin_level=4 "
            "boundaries; the District's and the states' speed defaults (OWNER-DECISIONS 108, "
            "112) cannot be applied, so the rebuild stops here"
        )
    started = time.monotonic()
    rank = {s: i for i, s in enumerate(STATE_PRIORITY)}
    result: dict[int, str] = {}
    points = [
        (way.osm_id, *way.coordinates[len(way.coordinates) // 2]) for way in ways if way.coordinates
    ]
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS rm_states")
        cursor.execute("CREATE TEMP TABLE rm_states (state text, rank int, geom geometry)")
        try:
            for state, geometry in polygons.items():
                cursor.execute(
                    "INSERT INTO rm_states VALUES (%s, %s, ST_GeomFromEWKB(%s))",
                    [state, rank.get(state, len(rank)), bytes(geometry.ewkb)],
                )
            cursor.execute("CREATE INDEX ON rm_states USING gist (geom)")
            for start in range(0, len(points), CHUNK):
                chunk = points[start : start + CHUNK]
                cursor.execute(
                    """SELECT DISTINCT ON (p.id) p.id, s.state
                       FROM unnest(%s::bigint[], %s::float8[], %s::float8[]) AS p(id, lon, lat)
                       JOIN rm_states AS s
                         ON ST_Covers(s.geom, ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326))
                       ORDER BY p.id, s.rank""",
                    [[p[0] for p in chunk], [p[1] for p in chunk], [p[2] for p in chunk]],
                )
                result.update(cursor.fetchall())
        finally:
            cursor.execute("DROP TABLE IF EXISTS rm_states")
    counts = Counter(result.values())
    logger.info(
        "way states: %s; %d of %d ways outside every state; %.1f s",
        ", ".join(f"{s} {n:,}" for s, n in sorted(counts.items())) or "none",
        len(points) - len(result),
        len(points),
        time.monotonic() - started,
    )
    empty = [s for s in required if not counts.get(s)]
    if empty:
        raise StatesMissing(
            f"no way placed in {', '.join(empty)}: its polygon is in the extract but holds no "
            "way, which is a broken boundary, not a region without roads"
        )
    return result
