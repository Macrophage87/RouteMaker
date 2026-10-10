"""Road names and the roads that meet at a way's ends (HALF-STEP-EDITOR phases 4 and 5).

The live segment table keeps a name (`trail_name`) only on a way the zoomed-out map or the
calm-road layer may draw (`pipeline.run`): a busy road has none there. The road panel reads a
way's name from the router (`segment_info.router_facts`, Valhalla's `/locate`), and so does
this: the router's name first, the table's where the router is silent or does not know the
way. Which ways meet, and at what level, is always the table's (their ends within
`TOUCH_M`, as OSM ways share a node).

Used by the rider suggestions' poll (the road and its cross streets, `core.suggestions`) and
by the stress editor's named stretch (`core.stress_edits.named_stretch`).
"""

from __future__ import annotations

from django.db import connection

from . import segment_info

# Two ways meet where their ends are this close (OSM ways share a node).
TOUCH_M = 2.0
# The most the router may take over all its answers for one question (a stretch, a poll's
# cross streets): past it the router is treated as silent and the table's names stand.
NAMES_BUDGET_S = 3.0
_COSTINGS = ("bicycle", "auto", "pedestrian")


def key(name: str | None) -> str:
    """A name as two ways must share it: case and outer spaces aside."""
    return " ".join((name or "").split()).lower()


def ends(schema: str, way_ids: list[int]) -> dict[int, list[tuple[float, float]]]:
    """Each way's two ends, (lon, lat): the start of its first row and the end of its last."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT osm_way_id,
                   ST_X(ST_StartPoint((array_agg(geometry ORDER BY ordinal))[1])),
                   ST_Y(ST_StartPoint((array_agg(geometry ORDER BY ordinal))[1])),
                   ST_X(ST_EndPoint((array_agg(geometry ORDER BY ordinal DESC))[1])),
                   ST_Y(ST_EndPoint((array_agg(geometry ORDER BY ordinal DESC))[1]))
            FROM {schema}.segment WHERE osm_way_id = ANY(%s) GROUP BY osm_way_id
            """,
            [list(way_ids)],
        )
        return {int(r[0]): [(r[1], r[2]), (r[3], r[4])] for r in cursor.fetchall()}


def touching(schema: str, point: tuple[float, float]) -> list[dict]:
    """The drawn road rows at `point`: way, the table's name, and the level the junction model
    reads (the higher of the tier and the unsmoothed tier, plus a half step), one per way."""
    columns = segment_info.live_columns(schema)
    unsmoothed = (
        "COALESCE(stress_unsmoothed_tier, 0)" if "stress_unsmoothed_tier" in columns else "0"
    )
    half = "stress_half IS TRUE" if "stress_half" in columns else "false"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT osm_way_id, max(trail_name),
                   max(GREATEST(stress_tier, {unsmoothed}) + CASE WHEN {half} THEN 0.5 ELSE 0 END)
            FROM {schema}.segment
            WHERE map_class = 'road'
              AND geometry && ST_Expand(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 0.0001)
              AND ST_DWithin(geometry::geography,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            GROUP BY osm_way_id
            """,
            [point[0], point[1], point[0], point[1], TOUCH_M],
        )
        return [
            {"way": int(r[0]), "table_name": r[1], "level": float(r[2] or 0)}
            for r in cursor.fetchall()
        ]


class Names:
    """The router's names of the ways at a spot, asked once a spot and costing."""

    def __init__(self, budget_s: float = NAMES_BUDGET_S) -> None:
        from . import routing

        self._seen: dict[tuple, dict[int, str]] = {}
        self.silent = False
        self._deadline = routing.Deadline(at=routing.clock() + budget_s, per_call_s=budget_s)

    def _out_of_time(self) -> bool:
        from . import routing

        return self._deadline.at - routing.clock() <= 0

    def _at(self, point: tuple[float, float], costing: str) -> dict[int, str]:
        spot = (round(point[0], 6), round(point[1], 6), costing)
        if spot in self._seen:
            return self._seen[spot]
        found: dict[int, str] = {}
        if not self.silent and self._out_of_time():
            self.silent = True
        if not self.silent:
            try:
                edges = segment_info.locate_edges(point[1], point[0], costing)
            except segment_info.RouterSilent:
                self.silent = True
                edges = []
            for edge in edges:
                way = (edge.get("edge_info") or {}).get("way_id")
                if isinstance(way, int) and way not in found:
                    facts = segment_info.edge_facts([edge], way)
                    if facts and facts.get("name"):
                        found[way] = facts["name"]
        self._seen[spot] = found
        return found

    def name(self, way: int, point: tuple[float, float], table_name: str | None = None) -> str:
        """The way's name at `point`: the router's (bicycle, then car, then foot), else the
        table's, else ""."""
        for costing in _COSTINGS:
            found = self._at(point, costing).get(way)
            if found:
                return found
            if self.silent:
                break
        return (table_name or "").strip()


def table_name(schema: str, way_id: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT trail_name FROM {schema}.segment WHERE osm_way_id = %s "
            "ORDER BY ordinal LIMIT 1",
            [way_id],
        )
        row = cursor.fetchone()
    return ((row[0] if row else None) or "").strip()


def name_of(schema: str, way_id: int, names: Names | None = None) -> str:
    """The way's own name, asked of the router at its ends, else the table's."""
    names = names or Names()
    fallback = table_name(schema, way_id)
    for point in ends(schema, [way_id]).get(way_id, []):
        found = names.name(way_id, point)
        if found:
            return found
    return fallback
