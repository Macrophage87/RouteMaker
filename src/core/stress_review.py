"""Review: an instance admin's queue of roads that need a ruling (the owner, 2026-10-16: "Add a
mode that will allow people with admin access the ability to look at these roads and make a
ruling"; "Basically we'd have 3 modes for people who have admin access go/plan/review"; "Review
should highlight the roads where there's discrepancies between formula, community, etc").

Each queue is a list of roads with a reason, precomputed into `ReviewItem` when a build is
installed (`import_cloud_build`'s dry run) or by `manage.py compute_review_queue`, because the
heaviest compares two whole segment tables:

- `rebuild`: the ways whose level or bicycle access differs between the build waiting in the
  staging schema and the live one (old and new level, the rule and the rating that decided each);
- `disagreement`: ways whose ratings disagree by at least a whole step: RouteMaker's formula, the
  local governments' ratings (DDOT, Montgomery Planning, MDOT SHA), an owner or community
  override, riders' open suggestions, and OSM's own tags where DDOT's data changed the tier (the
  rebuild's dc-osm-discrepancies report), and the agencies whose public use is pending
  (`agency_lts.PENDING_AGENCIES`: Arlington, Alexandria), read only here from an admin-only file
  outside the repository (`pending_ratings`): shown and counted in the spread, never deciding a
  level and never on a public surface;
- `narrow_rural`: ways the owner's narrow-rural-road rule read at 25 mph with no posted speed;
- `sidepath`, `works_closure`, `rematch`, `dc_no_bike`: read from the rebuild's reports where
  they exist (`FILE_QUEUES`); a queue whose report is not there is listed as not wired;
- `painted_lane`: the rebuild's RL-3 report, painted lanes on two-way roads with two or more
  lanes each way, DDOT's or Montgomery's level beside the formula's, and Arlington's from the
  pending file for comparison (`compute_painted_lane`).

A ruling (`rule`) is Accept (recorded only), Reject (a rebuild change: the level it had before,
or a road the build closed reopened; an industrial-area, golf course or farm track closure
reopened) or Change LTS. A level is the road panel's own change (`stress_edits.apply`): an
approved owner override that outranks the agencies and the formula, written to the live table at
once, kept in the stress-edit history and re-applied by the swap. A reopening is an approved
access override, applied at the next rebuild. Every ruling is audited and can be undone within
the editor's undo window.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.gis.db.models.functions import AsGeoJSON
from django.contrib.gis.geos import Polygon
from django.db import connection, transaction
from django.db.models import BooleanField, Count, Exists, ExpressionWrapper, F, OuterRef, Q
from django.utils import timezone

from pipeline.schema import validate_schema_name
from routemaker import agency_lts, bike_bans, sidewalks
from routemaker.stress import NARROW_ROAD_RULE, NARROW_RURAL_ROAD_MPH

from . import audit, road_names, segment_info, stress_changes, stress_edits
from .models import AuditLogEntry, Override, ReviewItem, ReviewRuling, StressSuggestion

logger = logging.getLogger(__name__)

Queue = ReviewItem.Queue
Decision = ReviewRuling.Decision

# Ratings this far apart (a whole step) or more are a disagreement.
DISAGREEMENT_MIN = 1.0
# Roads one batch ruling may cover, and one page may list.
BATCH_MAX = 200
PAGE_MAX = 100
MAP_MAX = 2000
CATEGORY = "other"
EVIDENCE = "Instance admin's ruling in Review (owner/instance admin)"
REASON_MAX = stress_edits.REASON_MAX
# A way a bicycle may not use (`routemaker.facility.map_class`; unclear access is closed there).
CLOSED_CLASS = "barred"
REOPEN_VALUE = {"bicycle": "yes"}
METRES_PER_MILE = 1609.344
# Ways read a batch at a time.
CHUNK = 5000


FORMULA = "formula"
SUGGESTIONS = "suggestions"
OSM = "osm"
SOURCE_NAMES = {
    FORMULA: "RouteMaker's formula",
    agency_lts.OWNER: "Owner override",
    agency_lts.COMMUNITY: "Community rating",
    SUGGESTIONS: "Riders' open suggestions",
    OSM: "OSM's tags alone (DDOT's data changed it)",
    "rural floor": "Rural road floor",
}


def source_name(key: str) -> str:
    if key in agency_lts.PENDING_AGENCIES:
        return agency_lts.review_name(key)
    if key in SOURCE_NAMES:
        return SOURCE_NAMES[key]
    return agency_lts.source_name(key)


def evidence_using(name: str) -> str:
    """A ruling that took one source's level ("Use" on the card): the evidence names it."""
    return f"Instance admin's ruling in Review, using {name}'s level (owner/instance admin)"


# --- Reading a segment table ----------------------------------------------------------------


def _table_exists(schema: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [f"{schema}.segment"])
        return cursor.fetchone()[0] is not None


def _columns(schema: str) -> frozenset[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT attname::text FROM pg_attribute WHERE attrelid = to_regclass(%s) "
            "AND attnum > 0 AND NOT attisdropped",
            [f"{schema}.segment"],
        )
        return frozenset(r[0] for r in cursor.fetchall())


def _step_sql(columns: frozenset[str]) -> str:
    half = "CASE WHEN stress_half THEN 0.5 ELSE 0 END" if "stress_half" in columns else "0"
    return f"(stress_tier + {half})"


def _or_null(column: str, columns: frozenset[str], cast: str = "") -> str:
    return f"{column}{cast}" if column in columns else "NULL"


def _agg_sql(schema: str, where: str = "") -> str:
    """One row a way: its level (the highest of its pieces), whether a bicycle is barred on any
    of them, and the rule, ratings, adjustment and formula tier of the piece that set the level.
    One sort of the table (DISTINCT ON, the piece with the highest level first), never an array
    of every piece. Takes the closed class as its first parameter."""
    columns = _columns(schema)
    step = _step_sql(columns)
    return f"""
        SELECT DISTINCT ON (osm_way_id) osm_way_id, {step} AS step,
               COALESCE(bool_or(map_class = %s) OVER (PARTITION BY osm_way_id), false) AS closed,
               stress_rule AS rule,
               {_or_null("stress_ratings", columns, "::text")} AS ratings,
               {_or_null("stress_adjustment_id", columns, "::text")} AS adjustment,
               {_or_null("stress_computed_tier", columns)} AS computed
        FROM {schema}.segment {where}
        ORDER BY osm_way_id, {step} DESC NULLS LAST, ordinal
    """


def _row(r) -> dict:
    return {
        "way": int(r[0]),
        "step": float(r[1]) if r[1] is not None else None,
        "closed": bool(r[2]),
        "rule": r[3] or "",
        "ratings": json.loads(r[4]) if r[4] else None,
        "adjustment": r[5],
        "computed": r[6],
    }


def _raw(row: dict | None) -> dict:
    """What an item keeps of a way's row for its card; the words are made when it is shown."""
    if row is None:
        return {}
    return {k: row.get(k) for k in ("rule", "ratings", "adjustment", "computed")}


def _digest(*parts) -> str:
    """The `inputs` digest of what a road was listed for."""
    text = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def _way_rows(schema: str, where: str = "", params: Iterable = ()) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(_agg_sql(schema, where), [CLOSED_CLASS, *params])
        return [_row(r) for r in cursor.fetchall()]


def _fill_facts(queue: str, schema: str, build_id: str = "") -> None:
    """Each listed way's name (where the queue gave none), length, count, lines and area,
    written in the database from `schema`: no way's lines pass through Python.

    The area is the county, from the one county lookup the import's stress change report uses
    (`stress_changes.county_table`, reference/counties.geojson), at the point on the road
    nearest its middle; "" where this host has no counties file. That report counts segments
    by whole tier, each placed by its own midpoint; Review counts ways (a way's level is its
    highest piece's, half steps included, and a change of bicycle access counts too), so a
    way across a county line is one road in one county here and its pieces in each there."""
    if not _table_exists(schema):
        return
    with stress_changes.county_table(_counties()):
        _write_facts(queue, schema, build_id)


_COUNTIES: dict[tuple, list] = {}


def _counties() -> list[tuple[str, str]]:
    """`stress_changes.reference_counties`, read once while the file is unchanged."""
    path = Path(settings.REBUILD_REFERENCE_DIR) / stress_changes.COUNTIES_FILE
    key = (str(path), path.stat().st_mtime_ns if path.is_file() else None)
    if key not in _COUNTIES:
        _COUNTIES.clear()
        _COUNTIES[key] = stress_changes.reference_counties()
    return _COUNTIES[key]


def _write_facts(queue: str, schema: str, build_id: str) -> None:
    """The facts made a batch of ways at a time (`CHUNK`) into a temporary table keyed on the
    way, then written to the queue's rows a batch at a time by that key.

    Never one `UPDATE review_item ... FROM (the segments' aggregate)`: the rows were inserted
    in this same transaction, so the planner holds no statistics for them, guesses one row, and
    may join by a nested loop that runs the whole aggregate again for every row. On the owner's
    PC (2026-10-19) a build of about 107,000 changed ways ran that join for over ten hours. Each
    statement here is bounded by a batch and every join is on an index (the temporary table's
    key, the segment table's `segment_way_idx`, review_item's `review_item_one_a_way`), so no
    plan can make it quadratic."""
    columns = _columns(schema)
    names = [c for c in ("trail_name", "sidepath_name", "mtb_name") if c in columns]
    name = f"max(COALESCE({', '.join(names)}))" if names else "NULL"
    aadt = "max(volume_aadt)" if "volume_aadt" in columns else "NULL"
    county = stress_changes.county_of("p.point")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT osm_way_id FROM review_item WHERE queue = %s AND build_id = %s "
            "ORDER BY osm_way_id",
            [queue, build_id],
        )
        ways = [int(r[0]) for r in cursor.fetchall()]
        cursor.execute("DROP TABLE IF EXISTS review_fact")
        cursor.execute(
            "CREATE TEMP TABLE review_fact (osm_way_id bigint PRIMARY KEY, name text, "
            "length_m float8, aadt integer, geom geometry, simple geometry, point geometry, "
            "area text)"
        )
        for start in range(0, len(ways), CHUNK):
            batch = ways[start : start + CHUNK]
            cursor.execute(
                f"""
                INSERT INTO review_fact
                SELECT f.osm_way_id, f.name, f.length_m, f.aadt, f.geom,
                       ST_Multi(ST_SimplifyPreserveTopology(f.geom, {LOW_TOLERANCE})),
                       p.point, COALESCE({county}, '')
                FROM (
                    SELECT osm_way_id, {name} AS name,
                           sum(ST_Length(geometry::geography)) AS length_m, {aadt} AS aadt,
                           ST_Multi(ST_Collect(geometry ORDER BY ordinal)) AS geom
                    FROM {schema}.segment
                    WHERE osm_way_id = ANY(%s::bigint[])
                    GROUP BY osm_way_id
                ) f,
                LATERAL (SELECT ST_ClosestPoint(f.geom, ST_Centroid(f.geom)) AS point) p
                """,
                [batch],
            )
            cursor.execute(
                """
                UPDATE review_item i
                SET name = CASE WHEN i.name = '' THEN COALESCE(f.name, '') ELSE i.name END,
                    length_m = COALESCE(f.length_m, 0), aadt = f.aadt, geometry = f.geom,
                    simple = f.simple, point = f.point, area = f.area
                FROM review_fact f
                WHERE i.queue = %s AND i.build_id = %s AND i.osm_way_id = f.osm_way_id
                  AND i.osm_way_id = ANY(%s::bigint[])
                """,
                [queue, build_id, batch],
            )
            cursor.execute("TRUNCATE review_fact")
            if len(ways) > CHUNK:
                logger.info(
                    "Review's %s list: facts for %d of %d ways",
                    queue,
                    min(start + CHUNK, len(ways)),
                    len(ways),
                )
        cursor.execute("DROP TABLE review_fact")
        # The queue's order (`page`): the size of the change or disagreement along the road,
        # times its traffic for a disagreement (per thousand cars a day, at least 1).
        cursor.execute(
            f"UPDATE review_item SET score = {SCORE_SQL.get(queue, 'length_m')} "
            "WHERE queue = %s AND build_id = %s",
            [queue, build_id],
        )


SCORE_SQL = {
    Queue.REBUILD: (
        "(CASE WHEN kind IN ('closed', 'reopened') THEN 4 "
        "ELSE abs(COALESCE(new_step, 0) - COALESCE(old_step, 0)) END) * length_m"
    ),
    Queue.DISAGREEMENT: "COALESCE(spread, 0) * length_m * greatest(1, COALESCE(aadt, 0) / 1000.0)",
    Queue.PAINTED_LANE: "COALESCE(spread, 0) * length_m * greatest(1, COALESCE(aadt, 0) / 1000.0)",
}

# How far the region view's lines are simplified, in degrees (about 30 m), and how many places
# a map's coordinates keep: 5 (about a metre) simplified, 6 whole.
LOW_TOLERANCE = 0.0003
LOW_PLACES = 5
HIGH_PLACES = 6
NO_REPORT = "No report from this build"


def write_state(queue: str, build_id: str = "", note: str = "") -> None:
    """The queue's state row: when and for what build it was computed, and why it is empty
    where it is (`NO_REPORT`)."""
    from .models import ReviewQueueState

    ReviewQueueState.objects.update_or_create(
        queue=queue,
        defaults={"build_id": build_id, "computed_at": timezone.now(), "note": note},
    )


def deciding_source(row: dict) -> str:
    """Whose rating set the way's level: an override's owner, the agency, a floor, or the
    formula (`segment.stress_ratings`' `used`, else the rule)."""
    if row.get("adjustment"):
        return agency_lts.adjustment_source(row["adjustment"])
    held = row.get("ratings")
    if isinstance(held, dict) and held.get("used"):
        return str(held["used"])
    if str(row.get("rule") or "").startswith(agency_lts.AGENCY_RULE):
        for key, (name, _rank) in agency_lts.AGENCIES.items():
            if name in row["rule"]:
                return key
    return FORMULA


def _state(row: dict | None) -> dict:
    """A side of an item (before or after a rebuild, or now), for its card: the rule in words
    and who decided the level, made from the row the item keeps (`_raw`)."""
    if not row:
        return {}
    source = deciding_source(row)
    rule = row.get("rule") or ""
    return {
        "rule": segment_info.rule_words(rule) if rule else "",
        "source": source,
        "source_name": source_name(source),
        "ratings": row.get("ratings"),
    }


def _item(queue: str, way: int, **fields) -> ReviewItem:
    """An item; its name, length, count, lines and area are filled in by `_fill_facts`."""
    return ReviewItem(
        queue=queue, osm_way_id=way, name=(fields.pop("name", "") or "")[:300], **fields
    )


def _replace(
    queue: str,
    items: list[ReviewItem],
    schema: str | None,
    build_id: str = "",
    router: _Router | None = None,
) -> int:
    """The queue's rows replaced whole, their facts read from `schema`, and its map written;
    then, once that is committed, its stretches grouped (`group_stretches`: the router is asked
    outside any transaction)."""
    with transaction.atomic():
        ReviewItem.objects.filter(queue=queue).delete()
        ReviewItem.objects.bulk_create(items, batch_size=2000)
        if schema:
            _fill_facts(queue, schema)
        write_state(queue, build_id)
    if schema:
        group_stretches(queue, schema, router=router)
    return len(items)


# --- Stretches ------------------------------------------------------------------------------
#
# The owner, 2026-10-17: "Also, for review, merge stretches. Go at least from major intersection
# to major intersection". A stretch is the listed ways that join end to end, are one road (the
# same name, or both unnamed and of the same class) and have the same change for their list
# (`_change_key`); it ends at a major junction, where the road meets another of tertiary class
# or bigger (`MAJOR_CLASSES`, their links included) that is not the road itself. A side street
# or a driveway does not end it. Grouped when the queue is computed (`_replace`,
# `compute_rebuild`), from the segment table the queue was read from: which ways meet (their
# ends within `road_names.TOUCH_M`, as OSM ways share a node) is the table's; their names and
# classes are the router's (`segment_info.locate_edges`, as the road panel reads them), the
# table's name where it is silent. With no class known for a road at a junction, the stress
# editor's own reading of a busy junction stands (`stress_edits.STRETCH_BREAK_STEP`).

# The queues grouped into stretches: those whose rows are a way each of the whole map. The
# report lists (side paths, closures, overrides not re-matched) stay a row a way.
STRETCH_QUEUES = (Queue.REBUILD, Queue.DISAGREEMENT, Queue.NARROW_RURAL, Queue.PAINTED_LANE)
# Valhalla's classes of a major road (OSM tertiary or bigger; a link takes its road's class).
MAJOR_CLASSES = frozenset({"motorway", "trunk", "primary", "secondary", "tertiary"})
# The most ways one stretch holds (the stress editor's own stretch's), so one ruling on it is
# always one stress edit.
STRETCH_MAX_WAYS = stress_edits.MAX_STRETCH_WAYS
# The most time the router may take over every queue's names and classes, one deadline for all
# of `compute_all` (or for one queue computed alone): past it, the table's.
ROUTER_BUDGET_S = 600.0
_STRETCH_COSTINGS = ("auto", "bicycle", "pedestrian")


def _change_key(item: ReviewItem) -> tuple:
    """What two ways of a stretch share: the rebuild's old and new level and access; a
    disagreement's level now and every source's level; elsewhere the level now and the reason."""
    if item.queue == Queue.REBUILD:
        return (item.old_step, item.new_step, item.old_closed, item.new_closed)
    if item.queue == Queue.DISAGREEMENT:
        held = (item.details or {}).get("sources") or []
        levels = sorted(
            (str(s.get("key")), s.get("level"), bool(s.get("pending")))
            for s in held
            if isinstance(s, dict)
        )
        return (item.new_step, item.new_closed, tuple(levels))
    return (item.new_step, item.new_closed, item.kind, item.reason)


class _Router:
    """The router's name and class of the ways at a spot (`segment_info.locate_edges`), within
    one budget for the whole queue; silent from its first failure on."""

    def __init__(self, budget_s: float = ROUTER_BUDGET_S) -> None:
        self.silent = False
        # The deadline starts at the first question (`at`), not here: a list computed before
        # any is asked never spends the budget.
        self._budget_s = budget_s
        self._until: float | None = None
        self._seen: dict[tuple, dict[int, dict]] = {}
        self._asked: dict[tuple, set[str]] = {}

    def at(self, point: tuple[float, float], wanted: Iterable[int]) -> dict[int, dict]:
        """{way: {name, classification}} at `point`, asked of each costing in turn until every
        way of `wanted` is known."""
        spot = (round(point[0], 6), round(point[1], 6))
        found = self._seen.setdefault(spot, {})
        asked = self._asked.setdefault(spot, set())
        wanted = set(wanted)
        for costing in _STRETCH_COSTINGS:
            if wanted <= set(found) or self.silent:
                break
            if costing in asked:
                continue
            asked.add(costing)
            if self._until is None:
                self._until = time.monotonic() + self._budget_s
            elif time.monotonic() > self._until:
                self.silent = True
                break
            try:
                edges = segment_info.locate_edges(point[1], point[0], costing)
            except segment_info.RouterSilent:
                self.silent = True
                break
            for edge in edges:
                way = (edge.get("edge_info") or {}).get("way_id")
                if isinstance(way, int) and way not in found:
                    facts = segment_info.edge_facts([edge], way)
                    if facts:
                        found[way] = facts
        return found


def _stretch_ends(schema: str, ways: list[int]) -> list[tuple[int, int, float, float]]:
    """(way, way, lon, lat): two listed ways whose ends meet, and where. One short transaction,
    for its temporary table of the ends."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS review_stretch_end")
        cursor.execute(
            f"""
            CREATE TEMP TABLE review_stretch_end ON COMMIT DROP AS
            SELECT * FROM (
                SELECT DISTINCT ON (osm_way_id) osm_way_id AS way, ST_StartPoint(geometry) AS p
                FROM {schema}.segment WHERE osm_way_id = ANY(%s) ORDER BY osm_way_id, ordinal
            ) first_piece
            UNION ALL
            SELECT * FROM (
                SELECT DISTINCT ON (osm_way_id) osm_way_id AS way, ST_EndPoint(geometry) AS p
                FROM {schema}.segment WHERE osm_way_id = ANY(%s)
                ORDER BY osm_way_id, ordinal DESC
            ) last_piece
            """,
            [ways, ways],
        )
        cursor.execute("CREATE INDEX ON review_stretch_end USING gist (p)")
        cursor.execute("ANALYZE review_stretch_end")
        cursor.execute(
            """
            SELECT x.way, y.way, ST_X(x.p), ST_Y(x.p)
            FROM review_stretch_end x JOIN review_stretch_end y
              ON x.way < y.way AND x.p && ST_Expand(y.p, 0.0001)
             AND ST_DWithin(x.p::geography, y.p::geography, %s)
            """,
            [road_names.TOUCH_M],
        )
        found = [(int(a), int(b), float(x), float(y)) for a, b, x, y in cursor.fetchall()]
        cursor.execute("DROP TABLE IF EXISTS review_stretch_end")
    return found


def _meeting(schema: str, points: list[tuple[float, float]]) -> list[dict[int, tuple]]:
    """For each point, the ways of the table that touch it: {way: (level, the table's name)},
    the level the junction model reads (`road_names.touching`)."""
    columns = _columns(schema)
    unsmoothed = (
        "COALESCE(s.stress_unsmoothed_tier, 0)" if "stress_unsmoothed_tier" in columns else "0"
    )
    half = "s.stress_half IS TRUE" if "stress_half" in columns else "false"
    names = [f"s.{c}" for c in ("trail_name", "sidepath_name", "mtb_name") if c in columns]
    name = f"max(COALESCE({', '.join(names)}))" if names else "NULL"
    out: list[dict[int, tuple]] = [{} for _ in points]
    if not points:
        return out
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT c.n, s.osm_way_id,
                   max(GREATEST(s.stress_tier, {unsmoothed})
                       + CASE WHEN {half} THEN 0.5 ELSE 0 END),
                   {name}
            FROM unnest(%s::float8[], %s::float8[]) WITH ORDINALITY AS c(x, y, n)
            JOIN {schema}.segment s
              ON s.geometry && ST_Expand(ST_SetSRID(ST_MakePoint(c.x, c.y), 4326), 0.0001)
             AND ST_DWithin(s.geometry::geography,
                            ST_SetSRID(ST_MakePoint(c.x, c.y), 4326)::geography, %s)
            GROUP BY c.n, s.osm_way_id
            """,
            [[p[0] for p in points], [p[1] for p in points], road_names.TOUCH_M],
        )
        for n, way, level, table_name in cursor.fetchall():
            out[int(n) - 1][int(way)] = (float(level or 0), (table_name or "").strip())
    return out


def _joins_here(
    a: int, b: int, meeting: dict[int, tuple], facts: dict[int, dict], listed: dict[int, str]
) -> tuple[bool, str]:
    """Whether ways `a` and `b`, meeting at a point, are one stretch there, and the road's name:
    one road (the same name, or both unnamed and of one class) at a junction with no major road
    but itself."""

    def name(way: int) -> str:
        said = (facts.get(way) or {}).get("name")
        if said:
            return said
        return (meeting.get(way, (0, ""))[1] or listed.get(way, "")).strip()

    def kind(way: int) -> str:
        return str((facts.get(way) or {}).get("classification") or "")

    road = road_names.key(name(a))
    if road or road_names.key(name(b)):
        if road != road_names.key(name(b)):
            return False, ""
    elif not kind(a) or kind(a) != kind(b):
        return False, ""
    for way, (level, _table_name) in meeting.items():
        if way in (a, b) or (road and road_names.key(name(way)) == road):
            continue
        if kind(way):
            if kind(way) in MAJOR_CLASSES:
                return False, ""
        elif level >= stress_edits.STRETCH_BREAK_STEP:
            return False, ""
    return True, name(a)


def group_stretches(
    queue: str, schema: str, build_id: str = "", *, router: _Router | None = None
) -> int:
    """Group the queue's ways into stretches (above), each listed as one row: its lead (the
    longest way) carries the stretch's ways, length, score and lines, and every way of it its
    `stretch`. Where the router names a road the queue had no name for, the name is kept.
    Returns how many stretches of two ways or more there are.

    Called on the queue's committed rows. The reading and the router's answers are outside any
    transaction (`_plan_stretches`); the writing is one short transaction after them, made only
    while the queue still holds the rows planned (a computation since then is left alone)."""
    if queue not in STRETCH_QUEUES or not _table_exists(schema):
        return 0
    router = router or _Router()
    plan = _plan_stretches(queue, schema, build_id, router)
    if plan is None:
        return 0
    computed, renamed, stretches = plan
    with transaction.atomic():
        now = list(
            ReviewItem.objects.select_for_update()
            .filter(queue=queue, build_id=build_id)
            .values_list("osm_way_id", "computed_at")
        )
        if sorted(now) != computed:
            logger.info("Review's %s list was computed again meanwhile; not grouped", queue)
            return 0
        _write_stretches(queue, build_id, renamed, stretches)
    if router.silent:
        logger.info("Review's %s stretches: the router was silent; the table's names", queue)
    return len(stretches)


def _plan_stretches(queue: str, schema: str, build_id: str, router: _Router):
    """(the rows planned for, {way alone: its router name}, [(lead, ways, name)]), or None for
    a queue with no rows: read and asked of the router outside any transaction."""
    rows = {
        i.osm_way_id: i
        for i in ReviewItem.objects.filter(queue=queue, build_id=build_id).only(
            "osm_way_id",
            "queue",
            "name",
            "kind",
            "reason",
            "old_step",
            "new_step",
            "old_closed",
            "new_closed",
            "details",
            "length_m",
            "point",
            "computed_at",
        )
    }
    if not rows:
        return None
    computed = sorted((w, i.computed_at) for w, i in rows.items())
    pairs = [
        (a, b, (x, y))
        for a, b, x, y in _stretch_ends(schema, sorted(rows))
        if _change_key(rows[a]) == _change_key(rows[b])
    ]
    points = sorted({p for _a, _b, p in pairs})
    meetings = dict(zip(points, _meeting(schema, points), strict=True))
    listed = {w: i.name for w, i in rows.items()}
    named: dict[int, str] = {}
    parent = {w: w for w in rows}
    size = dict.fromkeys(rows, 1)

    def root(way: int) -> int:
        while parent[way] != way:
            parent[way] = parent[parent[way]]
            way = parent[way]
        return way

    for a, b, point in sorted(pairs):
        ra, rb = root(a), root(b)
        if ra == rb or size[ra] + size[rb] > STRETCH_MAX_WAYS:
            continue
        meeting = meetings[point]
        facts = router.at(point, set(meeting) | {a, b})
        joined, road = _joins_here(a, b, meeting, facts, listed)
        if not joined:
            continue
        if road:
            named.setdefault(a, road)
            named.setdefault(b, road)
        parent[rb] = ra
        size[ra] += size[rb]
    groups: dict[int, list[int]] = {}
    for way in rows:
        groups.setdefault(root(way), []).append(way)
    renamed: dict[int, str] = {}
    stretches: list[tuple[int, list[int], str]] = []
    for ways in groups.values():
        lead = max(ways, key=lambda w: (rows[w].length_m, -w))
        name = rows[lead].name or named.get(lead, "")
        if not name:
            name = next((named[w] for w in sorted(ways) if w in named), "")
        if len(ways) >= 2:
            stretches.append((lead, sorted(ways), name))
            continue
        if not name and rows[lead].point is not None:
            # A road alone: its name from the router at its own point.
            x, y = rows[lead].point.coords
            name = (router.at((x, y), [lead]).get(lead) or {}).get("name") or ""
        if name and not rows[lead].name:
            renamed[lead] = name
    return computed, renamed, stretches


def _write_stretches(
    queue: str, build_id: str, renamed: dict[int, str], stretches: list[tuple[int, list[int], str]]
) -> None:
    with connection.cursor() as cursor:
        for lead, name in renamed.items():
            cursor.execute(
                "UPDATE review_item SET name = %s "
                "WHERE queue = %s AND build_id = %s AND osm_way_id = %s",
                [name[:300], queue, build_id, lead],
            )
        for lead, ways, name in stretches:
            cursor.execute(
                "UPDATE review_item SET stretch = %s "
                "WHERE queue = %s AND build_id = %s AND osm_way_id = ANY(%s)",
                [lead, queue, build_id, ways],
            )
            cursor.execute(
                """
                UPDATE review_item l
                SET ways = %s::jsonb, length_m = a.length_m, score = a.score,
                    aadt = a.aadt, geometry = a.geometry, simple = a.simple,
                    name = CASE WHEN l.name = '' THEN %s ELSE l.name END
                FROM (
                    SELECT sum(length_m) AS length_m, sum(score) AS score,
                           max(aadt) AS aadt,
                           (SELECT ST_Multi(ST_Collect(g.geom)) FROM review_item m,
                                   ST_Dump(m.geometry) g
                            WHERE m.queue = %s AND m.build_id = %s AND m.stretch = %s)
                               AS geometry,
                           (SELECT ST_Multi(ST_Collect(g.geom)) FROM review_item m,
                                   ST_Dump(m.simple) g
                            WHERE m.queue = %s AND m.build_id = %s AND m.stretch = %s)
                               AS simple
                    FROM review_item
                    WHERE queue = %s AND build_id = %s AND stretch = %s
                ) a
                WHERE l.queue = %s AND l.build_id = %s AND l.osm_way_id = %s
                """,
                [
                    json.dumps(ways),
                    name[:300],
                    *(queue, build_id, lead) * 4,
                ],
            )


def _listed_rows():
    """The rows a list shows: a way alone, or a stretch's lead."""
    return Q(stretch__isnull=True) | Q(stretch=F("osm_way_id"))


# --- The queues -----------------------------------------------------------------------------


def change_kind(old: float, new: float, old_closed: bool, new_closed: bool) -> str:
    if new_closed and not old_closed:
        return "closed"
    if old_closed and not new_closed:
        return "reopened"
    return f"{old:g}-{new:g}"


# The ridden sidewalks' and crosswalks' rules (`routemaker.sidewalks`): their level follows the
# road beside them, so a level change of theirs is no road's change and stays out of the
# rebuild's list (the owner, 2026-10-22: the first build with the rule listed 240,260 of them).
SIDEWALK_RULES = (sidewalks.RULE, sidewalks.LAST_RESORT_RULE)


def compute_rebuild(
    build_id: str, live: str, staging: str, *, router: _Router | None = None
) -> int:
    """The rebuild's changes: every way in both tables whose level or bicycle access differs,
    less the ridden sidewalks and crosswalks whose only change is their level (`SIDEWALK_RULES`).
    """
    validate_schema_name(live)
    validate_schema_name(staging)
    if not (_table_exists(live) and _table_exists(staging)):
        return _replace(Queue.REBUILD, [], None, build_id)

    def side(alias: str) -> str:
        return (
            f"jsonb_build_object('rule', {alias}.rule, 'ratings', {alias}.ratings::jsonb, "
            f"'adjustment', {alias}.adjustment, 'computed', {alias}.computed)"
        )

    # Compared and written in the database, a row a changed way as the two tables are read
    # (`INSERT ... SELECT`): neither table, nor any way's lines, passes through Python. The
    # words (the change, the rules, who decided) are made when an item is shown.
    with transaction.atomic():
        ReviewItem.objects.filter(queue=Queue.REBUILD).delete()
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO review_item (
                    queue, build_id, osm_way_id, name, area, reason, kind, old_step, new_step,
                    old_closed, new_closed, details, sources, spread, length_m, aadt, score,
                    inputs, ways, computed_at)
                SELECT %s, %s, n.osm_way_id, '', '', '',
                       CASE WHEN n.closed AND NOT o.closed THEN 'closed'
                            WHEN o.closed AND NOT n.closed THEN 'reopened'
                            ELSE COALESCE(o.step::float8::text, '') || '-'
                                 || COALESCE(n.step::float8::text, '') END,
                       o.step, n.step, o.closed, n.closed,
                       jsonb_build_object('old', {side("o")}, 'new', {side("n")}),
                       '[]'::jsonb, NULL, 0, NULL, 0, '', '[]'::jsonb, %s
                FROM ({_agg_sql(live)}) o JOIN ({_agg_sql(staging)}) n
                  ON o.osm_way_id = n.osm_way_id
                WHERE (o.step IS DISTINCT FROM n.step OR o.closed IS DISTINCT FROM n.closed)
                  AND NOT (n.rule IN (%s, %s) AND o.closed IS NOT DISTINCT FROM n.closed)
                """,
                [
                    Queue.REBUILD.value,
                    build_id,
                    timezone.now(),
                    CLOSED_CLASS,
                    CLOSED_CLASS,
                    *SIDEWALK_RULES,
                ],
            )
            count = cursor.rowcount
        _fill_facts(Queue.REBUILD, staging, build_id)
        write_state(Queue.REBUILD, build_id)
    group_stretches(Queue.REBUILD, staging, build_id, router=router)
    return count


def rating_sources(
    row: dict,
    suggested: float | None = None,
    osm: float | None = None,
    pending: Iterable[tuple[str, float]] = (),
) -> list[dict]:
    """Every rating the way holds, each {key, name, level, pending}: the road panel's own
    (`segment.stress_ratings`, as `segment_info.rating_rows` reads it), the open suggestions,
    OSM's, and the pending agencies' (counted in the spread, never deciding a level)."""
    held = row.get("ratings") if isinstance(row.get("ratings"), dict) else {}
    out: list[dict] = []

    def add(key: str, level, is_pending: bool = False) -> None:
        if level is None or any(s["key"] == key for s in out):
            return
        # An agency's level as the map uses it (Montgomery's 5 is our 4.5), so the spread and
        # "Use this level" compare like with like; its own level stays in the name.
        raw = float(level)
        level = float(agency_lts.map_level(key, raw))
        name = source_name(key) + (f" (rated LTS {raw:g})" if level != raw else "")
        out.append({"key": key, "name": name, "level": level, "pending": is_pending})

    adjusted = bool(row.get("adjustment")) or str(row.get("rule") or "").startswith("override:")
    formula = held.get("formula")
    if formula is None:
        formula = row.get("computed")
    if (
        formula is None
        and not adjusted
        and not str(row.get("rule") or "").startswith(agency_lts.AGENCY_RULE)
    ):
        formula = row.get("step")
    add(FORMULA, formula)
    for rating in held.get("agencies") or []:
        add(str(rating.get("agency")), rating.get("level"))
    override = held.get("override")
    if isinstance(override, dict):
        add(str(override.get("source")), override.get("level"))
    elif row.get("adjustment"):
        add(agency_lts.adjustment_source(row["adjustment"]), row.get("step"))
    add(SUGGESTIONS, suggested)
    add(OSM, osm)
    for agency, level in pending:
        add(agency, level, is_pending=not agency_lts.public_use_confirmed(agency))
    return out


def disagreement(sources: list[dict]) -> tuple[float, list[str], str] | None:
    """(spread, the sources at either end, a sentence) where the deciding ratings are a whole
    step apart or more, else None."""
    deciding = sources
    if len(deciding) < 2:
        return None
    high = max(s["level"] for s in deciding)
    low = min(s["level"] for s in deciding)
    if high - low < DISAGREEMENT_MIN:
        return None
    tops = [s for s in deciding if s["level"] == high]
    bottoms = [s for s in deciding if s["level"] == low]
    keys = sorted({s["key"] for s in tops + bottoms})
    said = (
        f"{' and '.join(s['name'] for s in tops)}: {level_words(high)}; "
        f"{' and '.join(s['name'] for s in bottoms)}: {level_words(low)}"
    )
    return high - low, keys, said


def _open_suggestions() -> dict[int, float]:
    """The highest level open road suggestions give each way."""
    out: dict[int, float] = {}
    for way, tier, half in StressSuggestion.objects.filter(
        kind=StressSuggestion.Kind.ROAD,
        status__in=[StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT],
    ).values_list("osm_way_id", "tier", "half"):
        step = tier + (0.5 if half and tier < 5 else 0)
        out[way] = max(out.get(way, 0), step)
    return out


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _osm_tiers(reports: Path | None) -> dict[int, float]:
    """OSM's own tier where DDOT's data changed it (the rebuild's dc-osm-discrepancies.csv)."""
    from pipeline.discrepancies import CSV_NAME

    path = reports / CSV_NAME if reports else None
    if path is None or not path.is_file():
        return {}
    out: dict[int, float] = {}
    for row in _read_csv(path):
        try:
            way = int(row["osm_way_id"])
            osm, dc = float(row["tier_osm_only"]), float(row["tier_with_dc"])
        except (KeyError, TypeError, ValueError):
            continue
        if osm != dc:
            out[way] = osm
    return out


def pending_dir() -> Path:
    """Where the owner keeps the pending agencies' files: outside the repository."""
    return Path(settings.REVIEW_PENDING_DIR)


def pending_ratings(directory: Path | None = None) -> dict[int, list[tuple[str, float]]]:
    """The pending agencies' levels by way (`agency_lts.PENDING_AGENCIES`), from
    `<directory>/<agency>-ratings.csv` (columns osm_way_id, level) where the owner has put one.
    Nothing else reads these files, so they reach no public surface."""
    directory = directory or pending_dir()
    out: dict[int, list[tuple[str, float]]] = {}
    for agency in agency_lts.PENDING_AGENCIES:
        path = directory / f"{agency}-ratings.csv"
        if not path.is_file():
            continue
        for row in _read_csv(path):
            try:
                way, level = int(row["osm_way_id"]), float(row["level"])
            except (KeyError, TypeError, ValueError):
                continue
            if agency_lts.level_problem(level) is None:
                out.setdefault(way, []).append((agency, level))
    return out


def compute_disagreements(
    schema: str,
    reports: Path | None = None,
    pending: dict[int, list] | None = None,
    *,
    build_id: str = "",
    router: _Router | None = None,
) -> int:
    validate_schema_name(schema)
    if not _table_exists(schema):
        return _replace(Queue.DISAGREEMENT, [], None, build_id)
    columns = _columns(schema)
    suggested = _open_suggestions()
    osm = _osm_tiers(reports)
    pending = pending_ratings() if pending is None else pending
    named = sorted(set(suggested) | set(osm) | set(pending))
    held = [c for c in ("stress_ratings", "stress_adjustment_id") if c in columns]
    where = " OR ".join([f"{c} IS NOT NULL" for c in held] + ["osm_way_id = ANY(%s)"])
    items = []
    for row in _way_rows(schema, f"WHERE {where}", [named]):
        sources = rating_sources(
            row, suggested.get(row["way"]), osm.get(row["way"]), pending.get(row["way"], ())
        )
        told = disagreement(sources)
        if told is None:
            continue
        spread, keys, said = told
        items.append(
            _item(
                Queue.DISAGREEMENT,
                row["way"],
                kind="-".join(keys)[:40],
                new_step=row["step"],
                new_closed=row["closed"],
                spread=spread,
                sources=keys,
                details={"new": _raw(row), "sources": sources},
                reason=said,
                inputs=_digest(row["step"], row["closed"], _raw(row), sources),
            )
        )
    return _replace(Queue.DISAGREEMENT, items, schema, build_id, router)


def compute_narrow_rural(schema: str, *, build_id: str = "", router: _Router | None = None) -> int:
    validate_schema_name(schema)
    if not _table_exists(schema):
        return _replace(Queue.NARROW_RURAL, [], None, build_id)
    rows = _way_rows(schema, "WHERE stress_rule LIKE %s", [f"%{NARROW_ROAD_RULE}%"])
    reason = (
        "Narrow rural road with no posted speed: read at "
        f"{segment_info.mph_and_kmh(NARROW_RURAL_ROAD_MPH)}"
    )
    items = [
        _item(
            Queue.NARROW_RURAL,
            row["way"],
            kind=f"{row['step']:g}" if row["step"] is not None else "",
            new_step=row["step"],
            new_closed=row["closed"],
            details={"new": _raw(row)},
            reason=reason,
            inputs=_digest(row["step"], row["closed"], _raw(row)),
        )
        for row in rows
    ]
    return _replace(Queue.NARROW_RURAL, items, schema, build_id, router)


@dataclass(frozen=True)
class FileQueue:
    """A queue read from a rebuild report: a CSV with a way id column."""

    queue: str
    file: str
    way_columns: tuple[str, ...]
    keep: Callable[[dict], bool]
    reason: Callable[[dict], str]
    closed: bool = False
    # More reports read into the same queue, laid out as `file` is (the golf courses' closures
    # beside the working sites'); the queue is unwired only when none of them is there.
    also: tuple[str, ...] = ()


FILE_QUEUES = (
    # The RL-1 rebuild's report of roads tagged to use a side path where none is mapped.
    FileQueue(
        Queue.SIDEPATH,
        "use-sidepath-no-path.csv",
        ("osm_way_id", "way_id"),
        lambda r: True,
        lambda r: r.get("reason") or r.get("why") or "Tagged to use a side path; none is mapped",
    ),
    # Footways and residential streets closed inside industrial areas (the works rule's report,
    # laid out as `restricted_areas.military_report_csv`: a `status` of closed or open), and a
    # golf course's cart paths and drives (the golf rule's, laid out the same; owner report
    # 2026-10-21), and the farm and forest tracks closed as likely private (the track rule's,
    # the same day), where a public trail or road the rule missed is reopened.
    FileQueue(
        Queue.WORKS_CLOSURE,
        "works-closures.csv",
        ("way_id", "osm_way_id"),
        lambda r: (r.get("status") or "closed") == "closed",
        lambda r: r.get("why") or r.get("reason") or "Closed inside an industrial area",
        closed=True,
        also=("golf-closures.csv", "track-closures.csv"),
    ),
    # Override rows the rebuild could not find their way again for (`pipeline.rematch`).
    FileQueue(
        Queue.REMATCH,
        "override-rematch.csv",
        ("old_way_id",),
        lambda r: r.get("outcome") == "failed",
        lambda r: f"A {r.get('kind') or ''} override did not re-match: {r.get('reason') or ''}",
    ),
    # The ways in the District a bicycle is kept off (`routemaker.bike_bans`; the owner,
    # 2026-10-17: "Add to the review map places you think that bikes are not allowed in DC").
    FileQueue(
        Queue.DC_NO_BIKE,
        bike_bans.REPORT_NAME,
        ("way_id",),
        lambda r: (r.get("status") or "closed") == "closed",
        lambda r: r.get("why") or r.get("reason") or "Closed to bicycles",
        closed=True,
    ),
)


def compute_file_queue(
    spec: FileQueue, schema: str, reports: Path | None, build_id: str = ""
) -> int | None:
    """The queue from its report, or None where this build has no such report: its rows are
    then cleared and its state says so (`NO_REPORT`), so an older build's list is never shown
    as this one's."""
    paths = [reports / name for name in (spec.file, *spec.also)] if reports else []
    paths = [path for path in paths if path.is_file()]
    if not paths:
        with transaction.atomic():
            ReviewItem.objects.filter(queue=spec.queue).delete()
            write_state(spec.queue, build_id, note=NO_REPORT)
        return None
    rows: dict[int, dict] = {}
    files: dict[int, str] = {}
    for path in paths:
        for row in _read_csv(path):
            if not spec.keep(row):
                continue
            for column in spec.way_columns:
                try:
                    way = int(row[column])
                except (KeyError, TypeError, ValueError):
                    continue
                if way not in rows:
                    rows[way], files[way] = row, path.name
                break
    present = _table_exists(schema)
    now = (
        {r["way"]: r for r in _way_rows(schema, "WHERE osm_way_id = ANY(%s)", [sorted(rows)])}
        if present
        else {}
    )
    items = []
    for way, row in rows.items():
        current = now.get(way)
        reason = spec.reason(row)[:500]
        items.append(
            _item(
                spec.queue,
                way,
                name=row.get("name") or "",
                kind=(row.get("kind") or row.get("highway") or "")[:40],
                new_step=current["step"] if current else None,
                new_closed=spec.closed or bool(current and current["closed"]),
                details={"new": _raw(current), "report": files[way]},
                reason=reason,
                inputs=_digest(reason, current and current["step"], _raw(current)),
            )
        )
    _replace(spec.queue, items, schema if present else None, build_id)
    return len(items)


def painted_lane_levels(
    row: dict, pending: Iterable[tuple[str, float]] = ()
) -> tuple[str, float, float] | None:
    """(agency, its level, the formula's) for one row of the rebuild's RL-3 report: DDOT's or
    Montgomery's level from the report, else a pending agency's (Arlington's) from Review's own
    admin-only file; None where neither rates the road."""
    try:
        formula = float(row["formula_level"])
    except (KeyError, TypeError, ValueError):
        return None
    agency = row.get("agency") or ""
    try:
        if agency in agency_lts.AGENCIES:
            return agency, float(agency_lts.map_level(agency, float(row["agency_level"]))), formula
    except (KeyError, TypeError, ValueError):
        return None
    for key, level in pending:
        return key, level, formula
    return None


def compute_painted_lane(
    schema: str,
    reports: Path | None,
    pending: dict[int, list] | None = None,
    *,
    build_id: str = "",
    router: _Router | None = None,
) -> int | None:
    """The RL-3 list (the owner, 2026-10-16): each painted lane on a two-way road with two or
    more lanes each way that DDOT or Montgomery rates, from the rebuild's report
    (`agency_lts.PAINTED_LANE_REPORT_NAME`), with the agency's level beside the formula's; and,
    for comparison only, the report's Virginia roads Arlington rates in the pending agencies'
    admin-only file (`pending_ratings`), read here and nowhere else, never deciding a level.
    None where the build has no report, as `compute_file_queue`."""
    validate_schema_name(schema)
    queue = Queue.PAINTED_LANE
    path = reports / agency_lts.PAINTED_LANE_REPORT_NAME if reports else None
    if path is None or not path.is_file():
        with transaction.atomic():
            ReviewItem.objects.filter(queue=queue).delete()
            write_state(queue, build_id, note=NO_REPORT)
        return None
    pending = pending_ratings() if pending is None else pending
    listed: dict[int, tuple[dict, tuple[str, float, float]]] = {}
    for row in _read_csv(path):
        try:
            way = int(row["way_id"])
        except (KeyError, TypeError, ValueError):
            continue
        local = row.get("scope") != agency_lts.PAINTED_LANE_COMPARISON
        levels = painted_lane_levels(row, () if local else pending.get(way, ()))
        if levels is not None:
            listed.setdefault(way, (row, levels))
    present = _table_exists(schema)
    now = (
        {r["way"]: r for r in _way_rows(schema, "WHERE osm_way_id = ANY(%s)", [sorted(listed)])}
        if present
        else {}
    )
    items = []
    for way, (row, (agency, level, formula)) in listed.items():
        current = now.get(way)
        reason = (
            f"{source_name(agency)}: {level_words(level)}; {source_name(FORMULA)}: "
            f"{level_words(formula)} (a painted lane, two or more lanes each way)"
        )
        items.append(
            _item(
                queue,
                way,
                name=row.get("name") or "",
                kind=agency[:40],
                new_step=current["step"] if current else None,
                new_closed=bool(current and current["closed"]),
                spread=abs(level - formula),
                sources=[agency, FORMULA],
                details={"new": _raw(current), "report": agency_lts.PAINTED_LANE_REPORT_NAME},
                reason=reason[:500],
                inputs=_digest(reason, current and current["step"], _raw(current)),
            )
        )
    _replace(queue, items, schema if present else None, build_id, router)
    return len(items)


def compute_all(build_id: str, live: str, staging: str | None, reports: Path | None) -> dict:
    """Every queue, against the build waiting in `staging` where there is one (what will be
    served), else the live table. {queue: count, or None where its report is not there}."""
    schema = staging if staging and _table_exists(staging) else live
    # One deadline for the router's names and classes over every list's stretches.
    router = _Router()
    counts: dict[str, int | None] = {}
    counts[Queue.REBUILD] = (
        compute_rebuild(build_id, live, staging, router=router) if staging else None
    )
    counts[Queue.DISAGREEMENT] = compute_disagreements(
        schema, reports, build_id=build_id, router=router
    )
    counts[Queue.NARROW_RURAL] = compute_narrow_rural(schema, build_id=build_id, router=router)
    for spec in FILE_QUEUES:
        counts[spec.queue] = compute_file_queue(spec, schema, reports, build_id)
    counts[Queue.PAINTED_LANE] = compute_painted_lane(
        schema, reports, build_id=build_id, router=router
    )
    return counts


# --- Words ----------------------------------------------------------------------------------


def level_words(step: float | None, closed: bool = False) -> str:
    if closed:
        return "Closed to bicycles"
    if step is None:
        return "Not in the map"
    tier = int(step)
    return segment_info.tier_text(tier, step != tier)


def level_label(step: float) -> str:
    return "Avoid" if step >= 5 else f"LTS {step:g}"


def kind_label(queue: str, kind: str) -> str:
    if queue == Queue.REBUILD:
        if kind == "closed":
            return "Newly closed to bicycles"
        if kind == "reopened":
            return "Reopened to bicycles"
        old, _sep, new = kind.partition("-")
        try:
            return f"{level_label(float(old))} to {level_label(float(new))}"
        except ValueError:
            return kind
    if queue == Queue.DISAGREEMENT:
        return " and ".join(source_name(k) for k in kind.split("-") if k)
    if queue == Queue.PAINTED_LANE and kind:
        return f"{source_name(kind)} against the formula"
    if queue == Queue.NARROW_RURAL:
        try:
            return f"Now {level_label(float(kind))}"
        except ValueError:
            return kind
    return kind or "All"


def length_text(metres: float) -> str:
    return f"{metres / METRES_PER_MILE:.2f} mi ({metres / 1000:.2f} km)"


# --- Rulings --------------------------------------------------------------------------------


def is_closure(item: ReviewItem) -> bool:
    return item.queue in (Queue.WORKS_CLOSURE, Queue.DC_NO_BIKE) or (
        item.queue == Queue.REBUILD and item.new_closed and not item.old_closed
    )


def actions(item: ReviewItem) -> list[str]:
    """What a ruling on the item may be."""
    allowed = [Decision.ACCEPT.value]
    if is_closure(item) or (
        item.queue == Queue.REBUILD and item.old_step is not None and not item.old_closed
    ):
        allowed.append(Decision.REJECT.value)
    if item.geometry is not None and not is_closure(item):
        allowed.append(Decision.SET.value)
    return allowed


def state_of(queue: str):
    from .models import ReviewQueueState

    return ReviewQueueState.objects.filter(queue=queue).first()


def current_build(queue: str) -> str:
    """The build a queue was last computed for: its state row's, else its newest item's."""
    state = state_of(queue)
    if state is not None:
        return state.build_id
    latest = ReviewItem.objects.filter(queue=queue).order_by("-computed_at").first()
    return latest.build_id if latest else ""


def _rulings(queue: str):
    return ReviewRuling.objects.filter(queue=queue, undone_at__isnull=True)


def _standing(rulings, queue: str, inputs):
    """The rulings that still stand: of this build for the rebuild's changes; elsewhere a
    level or a reopening always, and an Accept only while the road is listed for the same
    inputs (a later build that changes them lists it again)."""
    if queue == Queue.REBUILD:
        return rulings
    return rulings.filter(~Q(decision=Decision.ACCEPT) | Q(inputs=inputs))


def _ruled_filter(queue: str):
    """An Exists() for an item that has a standing ruling (`_standing`)."""
    rulings = _rulings(queue).filter(osm_way_id=OuterRef("osm_way_id"))
    if queue == Queue.REBUILD:
        rulings = rulings.filter(build_id=OuterRef("build_id"))
    return Exists(_standing(rulings, queue, OuterRef("inputs")))


def _stretch_ruled(queue: str):
    """For a listed row: it has a standing ruling, and so has every other way of its stretch."""
    open_ways = (
        ReviewItem.objects.filter(
            queue=queue, build_id=OuterRef("build_id"), stretch=OuterRef("osm_way_id")
        )
        .exclude(osm_way_id=OuterRef("osm_way_id"))
        .filter(~_ruled_filter(queue))
    )
    return ExpressionWrapper(_ruled_filter(queue) & ~Exists(open_ways), output_field=BooleanField())


def items_of(
    queue: str,
    *,
    kind: str = "",
    source: str = "",
    area: str = "",
    build: str | None = None,
    listed: bool = True,
):
    """A list's items now (the rebuild's: of `build`, else its current build, read here): its
    rows (a way alone or a stretch's lead) where `listed`, else every way."""
    query = ReviewItem.objects.filter(queue=queue)
    if queue == Queue.REBUILD:
        query = query.filter(build_id=current_build(queue) if build is None else build)
    if kind:
        query = query.filter(kind=kind)
    if source:
        query = query.filter(sources__contains=[source])
    if area:
        query = query.filter(area=area)
    if not listed:
        return query.annotate(ruled=_ruled_filter(queue))
    return query.filter(_listed_rows()).annotate(ruled=_stretch_ruled(queue))


def _row_of(way: int) -> Q:
    """The listed row that holds `way`: its own, or its stretch's lead."""
    return Q(osm_way_id=way) | Q(ways__contains=[way])


def queue_summary() -> list[dict]:
    """Each queue: how many roads, how many have a ruling, its filters (with their counts), and
    whether it is wired, every count made in the database."""
    from .models import ReviewQueueState

    states = {s.queue: s for s in ReviewQueueState.objects.all()}
    out = []
    for queue, label in Queue.choices:
        query = items_of(queue)
        counts = query.aggregate(total=Count("id"), reviewed=Count("id", filter=Q(ruled=True)))
        plain = query.order_by()
        kinds = plain.values_list("kind").annotate(n=Count("id")).order_by("-n", "kind")
        areas = plain.exclude(area="").values_list("area").annotate(n=Count("id")).order_by("area")
        sources: list[tuple[str, int]] = []
        if queue == Queue.DISAGREEMENT:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT s, count(*) FROM review_item, jsonb_array_elements_text(sources) s "
                    "WHERE queue = %s AND (stretch IS NULL OR stretch = osm_way_id) "
                    "GROUP BY s ORDER BY s",
                    [queue],
                )
                sources = cursor.fetchall()
        state = states.get(queue)
        note = state.note if state is not None else ""
        total = counts["total"] or 0
        out.append(
            {
                "queue": queue,
                "label": label,
                "build_id": current_build(queue) if queue == Queue.REBUILD else "",
                "computed_for": state.build_id if state is not None else "",
                "computed_at": state.computed_at.isoformat() if state is not None else None,
                "note": note,
                "total": total,
                "reviewed": counts["reviewed"] or 0,
                "wired": not note
                and (total > 0 or queue in (Queue.REBUILD, Queue.DISAGREEMENT, Queue.NARROW_RURAL)),
                "kinds": [{"kind": k, "label": kind_label(queue, k), "count": n} for k, n in kinds],
                "areas": [{"area": a, "count": n} for a, n in areas],
                "sources": [{"source": s, "label": source_name(s), "count": n} for s, n in sources],
            }
        )
    # The learned model's gap list (the roads it rates far from the formula) is to be one more
    # queue here, computed like the others into ReviewItem; nothing of it exists yet.
    return out


def latest_rulings(
    queue: str, ways: list[int], build_id: str = "", inputs: dict[int, str] | None = None
) -> dict[int, ReviewRuling]:
    """Each way's newest standing ruling (`_standing`; `inputs` is each item's)."""
    query = _rulings(queue).filter(osm_way_id__in=ways)
    if queue == Queue.REBUILD:
        query = query.filter(build_id=build_id)
    out: dict[int, ReviewRuling] = {}
    for ruling in query.order_by("at", "id"):
        if (
            queue != Queue.REBUILD
            and ruling.decision == Decision.ACCEPT
            and inputs is not None
            and ruling.inputs != inputs.get(ruling.osm_way_id)
        ):
            continue
        out[ruling.osm_way_id] = ruling
    return out


def ruling_out(ruling: ReviewRuling, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    return {
        "id": ruling.pk,
        "queue": ruling.queue,
        "osm_way_id": ruling.osm_way_id,
        "stretch": ruling.stretch,
        "decision": ruling.decision,
        "step": ruling.step,
        "reason": ruling.reason,
        "at": ruling.at.isoformat(),
        "undone": ruling.undone_at is not None,
        "can_undo": ruling.undone_at is None and now - ruling.at <= stress_edits.UNDO_WINDOW,
        "summary": ruling_words(ruling),
    }


def ruling_words(ruling: ReviewRuling) -> str:
    if ruling.decision == Decision.ACCEPT:
        return "Accepted"
    if ruling.access_override_id:
        return "Reopened to bicycles at the next rebuild"
    step = ruling.step if ruling.step is not None else 0
    return f"{'Kept' if ruling.decision == Decision.REJECT else 'Set to'} {level_label(step)}"


def item_out(item: ReviewItem, ruling: ReviewRuling | None = None, name: str | None = None) -> dict:
    details = item.details or {}
    old, new = _state(details.get("old")), _state(details.get("new"))
    geometry = json.loads(item.geometry.geojson) if item.geometry is not None else None
    return {
        "queue": item.queue,
        "osm_way_id": item.osm_way_id,
        "name": name or item.name or "",
        "area": item.area,
        "reason": item.reason or kind_label(item.queue, item.kind),
        "kind": item.kind,
        "kind_label": kind_label(item.queue, item.kind),
        "old_step": item.old_step,
        "new_step": item.new_step,
        "old_words": level_words(item.old_step, item.old_closed)
        if item.queue == Queue.REBUILD
        else None,
        "new_words": level_words(item.new_step, item.new_closed),
        "old_closed": item.old_closed,
        "new_closed": item.new_closed,
        "old_rule": old.get("rule"),
        "new_rule": new.get("rule"),
        "old_source": old.get("source_name"),
        "new_source": new.get("source_name"),
        "sources": details.get("sources") or [],
        "ratings": segment_info.rating_rows({"stress_ratings": new.get("ratings")}),
        "spread": item.spread,
        "length_m": round(item.length_m, 1),
        "length": length_text(item.length_m),
        # A stretch's ways, in way order, or the one way alone.
        "ways": list(item.ways or [item.osm_way_id]),
        "pieces": len(item.ways or [item.osm_way_id]),
        "aadt": item.aadt,
        "bbox": list(item.geometry.extent) if item.geometry is not None else None,
        "geometry": geometry,
        "point": list(item.point.coords)
        if item.point is not None
        else list(item.geometry.point_on_surface.coords)
        if item.geometry is not None
        else None,
        "actions": actions(item),
        "ruling": ruling_out(ruling) if ruling else None,
    }


def page(
    queue: str, *, kind="", source="", area="", open_only=True, number=1, size=25, way=None
) -> dict:
    size = max(1, min(int(size), PAGE_MAX))
    number = max(1, int(number))
    query = items_of(queue, kind=kind, source=source, area=area)
    if way is not None:
        query = query.filter(_row_of(way))
    if open_only:
        query = query.filter(ruled=False)
    total = query.count()
    rows = list(query.order_by("-score", "osm_way_id")[(number - 1) * size : number * size])
    build = current_build(queue) if queue == Queue.REBUILD else ""
    ruled = latest_rulings(
        queue, [r.osm_way_id for r in rows], build, {r.osm_way_id: r.inputs for r in rows}
    )
    return {
        "queue": queue,
        "build_id": build,
        "page": number,
        "per_page": size,
        "total": total,
        # A stretch only partly ruled is open: its lead's ruling is not the stretch's.
        "items": [item_out(r, ruled.get(r.osm_way_id) if r.ruled else None) for r in rows],
    }


# Review's map (`map_view`): a view's roads, never a whole list. Up to `MAP_CAP` roads a request,
# each list drawn given a fair share of it (its scores mean different things, so one list never
# pushes another's roads off), the largest of each first; below `CLUSTER_ZOOM` the roads near one
# another are one badge with their count (a square grid of `CELL_PX` screen pixels, in Web
# Mercator), and only a road alone in its cell is drawn as a line, so a badge never lies over its
# own roads. Below `HIGH_ZOOM` the lines are the simplified ones. A view is at most
# `MAX_VIEW_SCREENS` wide screens across (`view_refusal`).
MAP_CAP = 2000
CLUSTER_ZOOM = 10
HIGH_ZOOM = 13
CELL_PX = 64
# MapLibre's world is 512 pixels wide at zoom 0; Web Mercator's, this many metres.
TILE_PX = 512
WORLD_M = 40075016.686
MAX_VIEW_SCREENS = 4
SCREEN_PX = 1920


def view_refusal(west: float, south: float, east: float, north: float, zoom: float) -> str:
    """Why a view cannot be drawn ("" when it can): west past east or south past north (the
    page's map never sends one across the date line), or wider than `MAX_VIEW_SCREENS` wide
    screens at its zoom."""
    if west > east or south > north:
        return "The view's west is past its east, or its south past its north."
    if east - west > MAX_VIEW_SCREENS * SCREEN_PX * 360 / (TILE_PX * 2**zoom):
        return "That view is too wide for its zoom."
    return ""


def fair_shares(counts: dict[str, int], cap: int) -> dict[str, int]:
    """How many of each list's roads are drawn: an even share of `cap` each, a list with fewer
    passing what it leaves to the others."""
    shares: dict[str, int] = {}
    left = cap
    pending = sorted(counts, key=lambda q: counts[q])
    while pending:
        queue = pending.pop(0)
        shares[queue] = min(counts[queue], left // (len(pending) + 1))
        left -= shares[queue]
    return shares


def map_size(item: ReviewItem) -> float:
    """The size of a road's change or disagreement (a closure counts 4)."""
    if item.new_closed and not item.old_closed:
        return 4.0
    if item.spread is not None:
        return item.spread
    return abs((item.new_step or 0) - (item.old_step or 0))


def _listed(queues: list[str], build: str) -> tuple[str, list]:
    """SQL (and its parameters) for the items the lists hold now: `build`'s (the current one)
    for the rebuild's changes."""
    parts, params = [], []
    others = [q for q in queues if q != Queue.REBUILD]
    if Queue.REBUILD in queues:
        parts.append("(queue = %s AND build_id = %s)")
        params += [Queue.REBUILD.value, build]
    if others:
        parts.append("(queue = ANY(%s) AND build_id = '')")
        params.append(others)
    return "(" + " OR ".join(parts or ["false"]) + ")", params


def map_view(queues: list[str], bbox: tuple[float, float, float, float], zoom: float) -> dict:
    """The roads of `queues` in the box, for Review's map: {lines (GeoJSON, each road's way,
    list, size and whether it has a standing ruling), dots (a point a road below a street's
    zoom), badges (a point a cell with its count, far out), truncated (more roads were in view
    than drawn)}. Read from each item's own simplified line and point, both made when the list
    was computed; the rebuild's current build is read once."""
    queues = [q for q in Queue.values if q in queues]
    west, south, east, north = bbox
    box = Polygon.from_bbox(bbox)
    box.srid = 4326
    build = current_build(Queue.REBUILD) if Queue.REBUILD in queues else ""
    badges: list[dict] = []
    alone: dict[str, set[int]] | None = None
    if zoom < CLUSTER_ZOOM and queues:
        # A square cell of CELL_PX screen pixels, in Web Mercator metres.
        cell = WORLD_M / (TILE_PX * 2 ** max(zoom, 0)) * CELL_PX
        where, params = _listed(queues, build)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*), ST_X(ST_Centroid(ST_Collect(point))),
                       ST_Y(ST_Centroid(ST_Collect(point))), min(queue), min(osm_way_id)
                FROM review_item
                WHERE {where} AND (stretch IS NULL OR stretch = osm_way_id)
                  AND point && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                GROUP BY ST_SnapToGrid(ST_Transform(point, 3857), %s)
                """,
                [*params, west, south, east, north, cell],
            )
            rows = cursor.fetchall()
        alone = {}
        for n, x, y, queue, way in rows:
            if n == 1:
                alone.setdefault(queue, set()).add(int(way))
            else:
                badges.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [round(x, 5), round(y, 5)]},
                        "properties": {"count": int(n)},
                    }
                )
    field = "geometry" if zoom >= HIGH_ZOOM else "simple"
    places = HIGH_PLACES if zoom >= HIGH_ZOOM else LOW_PLACES
    found: dict[str, list[ReviewItem]] = {}
    for queue in queues:
        query = items_of(queue, build=build).filter(**{f"{field}__bboverlaps": box})
        if alone is not None:
            query = query.filter(osm_way_id__in=sorted(alone.get(queue, ())))
        found[queue] = list(
            query.annotate(lines=AsGeoJSON(field, precision=places))
            .only(
                "osm_way_id",
                "queue",
                "score",
                "spread",
                "new_step",
                "old_step",
                "new_closed",
                "old_closed",
                "point",
            )
            .order_by("-score", "osm_way_id")[: MAP_CAP + 1]
        )
    shares = fair_shares({q: len(items) for q, items in found.items()}, MAP_CAP)
    # Each list's share, the largest first, in Review's order of the lists.
    drawn = [item for queue in queues for item in found[queue][: shares[queue]]]
    lines = [
        {
            "type": "Feature",
            "geometry": json.loads(item.lines),
            "properties": {
                "way": item.osm_way_id,
                "queue": item.queue,
                "size": map_size(item),
                "ruled": bool(item.ruled),
            },
        }
        for item in drawn
        if item.lines
    ]
    # Below a street's zoom, a dot a road as well, so a short one is never less than a dot.
    dots = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(c, LOW_PLACES) for c in item.point.coords],
            },
            "properties": {"way": item.osm_way_id, "queue": item.queue, "ruled": bool(item.ruled)},
        }
        for item in drawn
        if zoom < HIGH_ZOOM and item.lines and item.point is not None
    ]
    return {
        "zoom": zoom,
        "detail": "high" if zoom >= HIGH_ZOOM else "low",
        "truncated": any(len(found[q]) > shares[q] for q in queues),
        "lines": {"type": "FeatureCollection", "features": lines},
        "badges": {"type": "FeatureCollection", "features": badges},
        "dots": {"type": "FeatureCollection", "features": dots},
    }


def next_road(
    lists: list[str],
    queue: str,
    way: int | None,
    *,
    direction: int = 1,
    open_only: bool = True,
    wrap: bool = True,
) -> dict | None:
    """The road after (or before, `direction` -1) `way` in its list's order (`page`'s: largest
    first), with no ruling yet unless not `open_only`; past the list's end, the next of `lists`
    in Review's order, and round to the start when `wrap`. {queue, osm_way_id}, or None."""
    lists = [q for q in Queue.values if q in lists] or ([queue] if queue in Queue.values else [])
    if not lists:
        return None
    start = lists.index(queue) if queue in lists else 0
    current = items_of(queue).filter(_row_of(way)).first() if way is not None else None
    order = ("-score", "osm_way_id") if direction > 0 else ("score", "-osm_way_id")
    rounds = len(lists) + 1 if wrap else 1
    for step in range(rounds):
        name = lists[(start + step * (1 if direction > 0 else -1)) % len(lists)]
        query = items_of(name)
        if open_only:
            query = query.filter(ruled=False)
        if current is not None and name == current.queue:
            query = query.exclude(osm_way_id=current.osm_way_id)
            if step == 0:
                s, w = current.score, current.osm_way_id
                query = query.filter(
                    Q(score__lt=s) | Q(score=s, osm_way_id__gt=w)
                    if direction > 0
                    else Q(score__gt=s) | Q(score=s, osm_way_id__lt=w)
                )
        found = query.order_by(*order).values_list("osm_way_id", flat=True).first()
        if found is not None:
            return {"queue": name, "osm_way_id": found}
    return None


def unruled_rebuild_changes() -> tuple[int, int, str]:
    """(changed roads with no ruling yet, changed roads, build) for the swap's report."""
    query = items_of(Queue.REBUILD, listed=False)
    total = query.count()
    return query.filter(ruled=False).count(), total, current_build(Queue.REBUILD)


def default_reason(now: datetime) -> str:
    """The private reason a ruling's override carries when the admin gives none: never a copy of
    any source's value (a pending agency's least of all)."""
    return f"Admin review, {now:%b %Y}"


def _reason(text: str | None) -> str:
    text = (text or "").strip()
    if len(text) > REASON_MAX:
        raise stress_edits.Invalid(f"The reason is at most {REASON_MAX} characters.", "reason")
    return text


def _reopen(actor, way: int, reason: str, now: datetime) -> Override:
    """A closed road reopened: an approved access override whose source (`Override.Source.REVIEW`)
    says it is a Review ruling's, applied at the next rebuild."""
    return Override.objects.create(
        kind=Override.Kind.ACCESS,
        osm_way_id=way,
        value=dict(REOPEN_VALUE),
        reason=reason,
        evidence=EVIDENCE,
        approved=True,
        approved_at=now,
        source=Override.Source.REVIEW,
        created_by=actor,
        created_by_user_id=getattr(actor, "pk", None),
        approved_by=actor,
        approved_by_user_id=getattr(actor, "pk", None),
    )


def _record(actor, item: ReviewItem, decision: str, target, reason: str, now, edit, access):
    ruling = ReviewRuling.objects.create(
        queue=item.queue,
        build_id=item.build_id,
        osm_way_id=item.osm_way_id,
        decision=decision,
        step=target,
        reason=reason,
        at=now,
        actor=actor,
        actor_user_id=getattr(actor, "pk", None),
        edit=edit,
        access_override=access,
        inputs=item.inputs,
        stretch=item.stretch,
    )
    audit.record(
        actor,
        "review_ruling",
        "review_ruling",
        ruling.pk,
        AuditLogEntry.Outcome.ALLOWED,
        detail=(
            f"{item.queue} {item.build_id} way {item.osm_way_id}: {ruling_words(ruling)}"
            + (f"; stretch {item.stretch}" if item.stretch else "")
            + (f"; edit {edit.pk}" if edit else "")
            + (f"; access override {access.pk}" if access else "")
        )[:2000],
    )
    return ruling


def _set_levels(
    actor,
    items: list[ReviewItem],
    decision: str,
    target: float,
    reason: str,
    now: datetime,
    evidence: str = EVIDENCE,
) -> tuple[list[ReviewRuling], list[dict]]:
    """One level for many roads: one stress edit (`stress_edits.apply`, as a batch), so one
    generation of the tiles and one undo for them all, and a ruling a road sharing it."""
    tier, half = stress_edits.split_step(target)
    spec = stress_edits.Spec(
        tier=tier,
        half=half,
        at_least=False,
        category=CATEGORY,
        reason=reason or default_reason(now),
    )
    schema = stress_edits.live_schema()
    columns = stress_edits.edit_columns(schema)
    ways = [i.osm_way_id for i in items]
    rows = stress_edits.read_rows(schema, columns, ways) if columns else {}
    present = {int(k.split(":")[0]) for k in rows}
    refused = [
        {"osm_way_id": i.osm_way_id, "error": "That road is not in the map being served."}
        for i in items
        if i.osm_way_id not in present
    ]
    items = [i for i in items if i.osm_way_id in present]
    if not items:
        return [], refused
    ways = [i.osm_way_id for i in items]
    expected = stress_edits.token_of(rows, ways)
    try:
        with transaction.atomic():
            edit = stress_edits.apply(
                actor, ways, spec, expected, now=now, evidence=evidence, batch=True
            ).edit
            made = [_record(actor, i, decision, target, reason, now, edit, None) for i in items]
    except stress_edits.EditRefused as refusal:
        return [], refused + [{"osm_way_id": w, "error": refusal.message} for w in ways]
    return made, refused


def rule(
    actor,
    queue: str,
    way_ids: list[int],
    decision: str,
    *,
    step: float | None = None,
    reason: str | None = None,
    source: str | None = None,
    now: datetime | None = None,
) -> tuple[list[ReviewRuling], list[dict]]:
    """Rule on one road or a batch. Returns (the rulings made, the roads refused with why).

    A batch's levels are one stress edit a level (Change LTS: one; a rebuild's Reject: one for
    each level the roads had before), so a batch is one change of the tiles and one undo; a
    level over more than `stress_edits.MAX_BATCH_WAYS` ways (a batch of long stretches) is
    several, a stretch never split (`_edit_chunks`).
    `source`: Change LTS on one road to the level one of its listed sources holds (not a
    pending agency's), named in the edit's evidence."""
    if queue not in Queue.values:
        raise stress_edits.Invalid("There is no such review queue.", "queue")
    if decision not in Decision.values:
        raise stress_edits.Invalid("Choose Accept, Reject or Change LTS.", "decision")
    ways = list(dict.fromkeys(int(w) for w in way_ids))
    if not ways or len(ways) > BATCH_MAX:
        raise stress_edits.Invalid(f"Rule on 1 to {BATCH_MAX} roads at a time.", "osm_way_ids")
    if decision == Decision.SET:
        stress_edits.split_step(step)
    text = _reason(reason)
    now = now or timezone.now()
    asked = {i.osm_way_id: i for i in items_of(queue, listed=False).filter(osm_way_id__in=ways)}
    evidence = EVIDENCE
    if source:
        evidence = _evidence_of(source, decision, step, [asked.get(w) for w in ways])
    ways, items = _with_stretches(queue, ways, asked)
    made: list[ReviewRuling] = []
    refused: list[dict] = []
    levels: dict[float, list[ReviewItem]] = {}
    for way in ways:
        item = items.get(way)
        if item is None:
            refused.append({"osm_way_id": way, "error": "That road is not in this queue."})
        elif decision not in actions(item):
            refused.append(
                {"osm_way_id": way, "error": "That ruling is not offered for this road."}
            )
        elif decision == Decision.ACCEPT:
            with transaction.atomic():
                made.append(_record(actor, item, decision, None, text, now, None, None))
        elif decision == Decision.REJECT and is_closure(item):
            with transaction.atomic():
                access = _reopen(actor, way, text or default_reason(now), now)
                made.append(_record(actor, item, decision, None, text, now, None, access))
        else:
            target = item.old_step if decision == Decision.REJECT else float(step)
            levels.setdefault(target, []).append(item)
    for target, group in levels.items():
        for chunk in _edit_chunks(group):
            done, failed = _set_levels(actor, chunk, decision, target, text, now, evidence)
            made += done
            refused += failed
    order = {w: n for n, w in enumerate(ways)}
    made.sort(key=lambda r: order[r.osm_way_id])
    return made, refused


def _with_stretches(
    queue: str, ways: list[int], asked: dict[int, ReviewItem]
) -> tuple[list[int], dict[int, ReviewItem]]:
    """The ways asked for with every other way of their stretches, each stretch's lead first
    then its ways in order, and their items: a ruling on a stretch is a ruling on each way."""
    leads = sorted({i.stretch for i in asked.values() if i.stretch is not None})
    if not leads:
        return ways, asked
    items = dict(asked)
    for item in items_of(queue, listed=False).filter(stretch__in=leads):
        items.setdefault(item.osm_way_id, item)
    members: dict[int, list[int]] = {}
    for way, item in sorted(items.items()):
        if item.stretch is not None:
            members.setdefault(item.stretch, []).append(way)
    out: list[int] = []
    for way in ways:
        item = asked.get(way)
        group = [way]
        if item is not None and item.stretch is not None:
            lead = item.stretch
            group = [lead] + [w for w in members.get(lead, []) if w != lead]
            if way not in group:
                group.insert(0, way)
        out += [w for w in group if w not in out]
    return out, items


def _edit_chunks(group: list[ReviewItem]) -> list[list[ReviewItem]]:
    """One level's roads in stress edits of at most `stress_edits.MAX_BATCH_WAYS` ways (a batch of
    long stretches can be more), a stretch never split between two (it holds at most
    `STRETCH_MAX_WAYS`), so Undo on a stretch undoes its one edit."""
    by_road: dict[int, list[ReviewItem]] = {}
    for item in group:
        by_road.setdefault(item.stretch or item.osm_way_id, []).append(item)
    chunks: list[list[ReviewItem]] = [[]]
    for road in by_road.values():
        if chunks[-1] and len(chunks[-1]) + len(road) > stress_edits.MAX_BATCH_WAYS:
            chunks.append([])
        chunks[-1].extend(road)
    return [c for c in chunks if c]


def _evidence_of(source: str, decision: str, step, items: list) -> str:
    """The evidence for a ruling that took `source`'s level, or Invalid where the one road
    listed does not hold that level from that source (or holds it only as a pending agency's)."""
    item = items[0] if len(items) == 1 else None
    if decision == Decision.SET and item is not None:
        for row in (item.details or {}).get("sources") or []:
            if (
                isinstance(row, dict)
                and row.get("key") == source
                and not row.get("pending")
                and row.get("level") == float(step)
            ):
                return evidence_using(str(row.get("name") or source_name(source)))
    raise stress_edits.Invalid("That level is not one this road's sources hold.", "source")


def undo(actor, ruling_id: int, *, now: datetime | None = None) -> tuple[ReviewRuling, int | None]:
    """Undo a ruling within the editor's undo window, with every ruling of the same request (a
    stretch's ways, a batch's roads): its stress changes by the editor's own undo, one a stress
    edit the request took, its reopenings by withdrawing the access rows' approval."""
    now = now or timezone.now()
    with transaction.atomic():
        ruling = ReviewRuling.objects.select_for_update().filter(pk=ruling_id).first()
        if ruling is None:
            raise stress_edits.NotFound("There is no such ruling.")
        if ruling.undone_at is not None:
            raise stress_edits.Stale("That ruling has already been undone.", None, "already_undone")
        if now - ruling.at > stress_edits.UNDO_WINDOW:
            raise stress_edits.Stale(
                "That ruling is older than 30 minutes, so it can no longer be undone here. "
                "Make a new ruling instead.",
                None,
                "too_old",
            )
        # Every ruling of the same request (one admin, one moment: `rule` stamps them all
        # with one time): a stretch's ways, a batch's roads, and every stress edit it took (a
        # level over more than `stress_edits.MAX_BATCH_WAYS` ways is several, `_edit_chunks`).
        same = Q(edit_id=ruling.edit_id) if ruling.edit_id else Q(pk=ruling.pk)
        if ruling.actor_user_id is not None:
            same |= Q(
                queue=ruling.queue,
                build_id=ruling.build_id,
                at=ruling.at,
                actor_user_id=ruling.actor_user_id,
            )
        elif ruling.stretch is not None:
            same |= Q(
                queue=ruling.queue, build_id=ruling.build_id, stretch=ruling.stretch, at=ruling.at
            )
        together = [ruling] + list(
            ReviewRuling.objects.select_for_update()
            .filter(same, undone_at__isnull=True)
            .exclude(pk=ruling.pk)
            .order_by("id")
        )
        generation = None
        for edit in dict.fromkeys(one.edit_id for one in together if one.edit_id):
            generation = stress_edits.undo(actor, edit, now=now).generation
        access = [one.access_override_id for one in together if one.access_override_id]
        if access:
            Override.objects.filter(pk__in=access).update(
                approved=False, approved_at=None, approved_by=None, approved_by_user_id=None
            )
        for one in together:
            one.undone_at = now
            one.undone_by = actor
            one.save(update_fields=["undone_at", "undone_by"])
        others = len(together) - 1
        audit.record(
            actor,
            "review_ruling_undo",
            "review_ruling",
            ruling.pk,
            AuditLogEntry.Outcome.ALLOWED,
            detail=f"{ruling.queue} way {ruling.osm_way_id}: {ruling_words(ruling)} undone"
            + (f", with {others} more of the same batch" if others else ""),
        )
    return ruling, generation


def _facts_of(schema: str, way: int) -> list[dict]:
    """The road panel's own rows for a way as `schema` holds it: level and rule, speed, lanes
    and count with their sources, facility."""
    if not _table_exists(schema):
        return []
    columns = _columns(schema)
    step = _step_sql(columns)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT * FROM {schema}.segment WHERE osm_way_id = %s "
            f"ORDER BY {step} DESC NULLS LAST, ordinal LIMIT 1",
            [way],
        )
        found = cursor.fetchone()
        names = [d[0] for d in cursor.description]
    if found is None:
        return []
    row = dict(zip(names, found, strict=True))
    return (
        segment_info.stress_rows(row)
        + segment_info.traffic_rows(row)
        + segment_info.riding_rows(row)
    )


def road_detail(way: int, queue: str = "") -> dict:
    """The facts behind a road's rating as the live table holds them, and for a rebuild's change
    as the build waiting in staging holds them too (`new_facts`), and its history: the stress
    edits, override rows and rulings on it, newest first."""
    from .models import StressEdit

    facts = _facts_of(stress_edits.live_schema(), way)
    new_facts: list[dict] = []
    if queue == Queue.REBUILD:
        staging = settings.SEGMENT_SCHEMA_STAGING
        validate_schema_name(staging)
        new_facts = _facts_of(staging, way)
    history: list[dict] = []
    for edit in StressEdit.objects.filter(osm_way_ids__contains=[way]).order_by("-at")[:20]:
        history.append(
            {
                "at": edit.at.isoformat(),
                "what": f"Stress {edit.get_action_display().lower()} in the road panel or Review",
            }
        )
    for row in Override.objects.filter(osm_way_id=way).order_by("-id")[:20]:
        state = (
            "superseded" if row.superseded_by_id else "approved" if row.approved else "not approved"
        )
        value = row.value if isinstance(row.value, dict) else {}
        level = value.get("tier")
        if level:
            step = float(level) + (0.5 if value.get("half") else 0)
            level = agency_lts.row_level(value.get("adjustment_id"), step)
        what = f"{row.get_kind_display()} override ({row.get_source_display()}), {state}" + (
            f": {level_label(level)}" if level else ""
        )
        # A row never approved has no date of its own; it sorts last.
        history.append({"at": row.approved_at.isoformat() if row.approved_at else "", "what": what})
    for ruling in ReviewRuling.objects.filter(osm_way_id=way).order_by("-at")[:20]:
        what = f"Review ({ruling.get_queue_display()}): {ruling_words(ruling)}"
        history.append(
            {"at": ruling.at.isoformat(), "what": what + (" (undone)" if ruling.undone_at else "")}
        )
    history.sort(key=lambda h: h["at"], reverse=True)
    return {"osm_way_id": way, "facts": facts, "new_facts": new_facts, "history": history}


def recent_rulings(queue: str | None = None, limit: int = 50) -> list[dict]:
    query = ReviewRuling.objects.all()
    if queue:
        query = query.filter(queue=queue)
    now = timezone.now()
    return [ruling_out(r, now) for r in query.order_by("-at", "-id")[:limit]]


def reports_dir(path: str | None, *, own: bool = False) -> Path | None:
    """The build's reports: `path` (relative to the rebuild's work directory, or absolute). With
    no path, the work directory's own reports only where `own` says the build is this
    computer's (`compute_review_queue` after a rebuild here): a cloud build's import never
    reads this computer's reports as the build's."""
    base = Path(settings.REBUILD_WORK_DIR)
    if path:
        found = Path(path) if Path(path).is_absolute() else base / path
    elif own:
        found = base / "reports"
    else:
        return None
    return found if found.is_dir() else None
