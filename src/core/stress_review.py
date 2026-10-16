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
- `sidepath`, `works_closure`, `rematch`: read from the rebuild's reports where they exist
  (`FILE_QUEUES`); a queue whose report is not there is listed as not wired.

A ruling (`rule`) is Accept (recorded only), Reject (a rebuild change: the level it had before,
or a road the build closed reopened; an industrial-area closure reopened) or Change LTS. A level
is the road panel's own change (`stress_edits.apply`): an approved owner override that outranks
the agencies and the formula, written to the live table at once, kept in the stress-edit history
and re-applied by the swap. A reopening is an approved access override, applied at the next
rebuild. Every ruling is audited and can be undone within the editor's undo window.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.db import connection, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from pipeline.schema import validate_schema_name
from routemaker import agency_lts
from routemaker.stress import NARROW_ROAD_RULE, NARROW_RURAL_ROAD_MPH

from . import audit, segment_info, stress_edits
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
        return agency_lts.PENDING_AGENCIES[key][0]
    if key in SOURCE_NAMES:
        return SOURCE_NAMES[key]
    return agency_lts.source_name(key)


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
    """One row a way: its level (the highest of its pieces), whether a bicycle is barred, and
    the rule, ratings, adjustment and formula tier of the piece that set the level. Takes the
    closed class as its first parameter."""
    columns = _columns(schema)
    step = _step_sql(columns)
    order = f"ORDER BY {step} DESC, ordinal"
    return f"""
        SELECT osm_way_id, max({step}) AS step, bool_or(map_class = %s) AS closed,
               (array_agg(stress_rule {order}))[1] AS rule,
               (array_agg({_or_null("stress_ratings", columns, "::text")} {order}))[1] AS ratings,
               (array_agg({_or_null("stress_adjustment_id", columns)} {order}))[1] AS adjustment,
               (array_agg({_or_null("stress_computed_tier", columns)} {order}))[1] AS computed
        FROM {schema}.segment {where} GROUP BY osm_way_id
    """


def _row(r) -> dict:
    return {
        "way": int(r[0]),
        "step": float(r[1]),
        "closed": bool(r[2]),
        "rule": r[3] or "",
        "ratings": json.loads(r[4]) if r[4] else None,
        "adjustment": r[5],
        "computed": r[6],
    }


def _way_rows(schema: str, where: str = "", params: Iterable = ()) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(_agg_sql(schema, where), [CLOSED_CLASS, *params])
        return [_row(r) for r in cursor.fetchall()]


def _facts(schema: str, ways: list[int]) -> dict[int, dict]:
    """Each way's name, length, count, lines and area (the police layer's authority, which is
    the county's in Maryland and Virginia, else the state's), in batches."""
    columns = _columns(schema)
    names = [c for c in ("trail_name", "sidepath_name", "mtb_name") if c in columns]
    name = f"max(COALESCE({', '.join(names)}))" if names else "NULL"
    aadt = "max(volume_aadt)" if "volume_aadt" in columns else "NULL"
    out: dict[int, dict] = {}
    for start in range(0, len(ways), CHUNK):
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                WITH w AS (
                    SELECT osm_way_id, {name} AS name,
                           sum(ST_Length(geometry::geography)) AS length_m, {aadt} AS aadt,
                           ST_Multi(ST_Collect(geometry ORDER BY ordinal)) AS geom
                    FROM {schema}.segment WHERE osm_way_id = ANY(%s) GROUP BY osm_way_id
                )
                SELECT w.osm_way_id, w.name, w.length_m, w.aadt, ST_AsText(w.geom),
                       COALESCE(
                         (SELECT j.name FROM jurisdiction j WHERE j.layer = 'police'
                            AND ST_Intersects(j.geometry, ST_PointOnSurface(w.geom))
                          ORDER BY j.name LIMIT 1),
                         (SELECT j.name FROM jurisdiction j WHERE j.layer = 'state'
                            AND ST_Intersects(j.geometry, ST_PointOnSurface(w.geom))
                          ORDER BY j.name LIMIT 1))
                FROM w
                """,
                [ways[start : start + CHUNK]],
            )
            for r in cursor.fetchall():
                out[int(r[0])] = {
                    "name": r[1] or "",
                    "length_m": float(r[2] or 0),
                    "aadt": int(r[3]) if r[3] is not None else None,
                    "geometry": GEOSGeometry(r[4], srid=4326) if r[4] else None,
                    "area": r[5] or "",
                }
    return out


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
    """A side of a rebuild change, for the item's card."""
    if row is None:
        return {}
    source = deciding_source(row)
    return {
        "rule": segment_info.rule_words(row["rule"]) if row["rule"] else "",
        "source": source,
        "source_name": source_name(source),
        "ratings": row.get("ratings"),
    }


def _item(queue: str, way: int, facts: dict | None, **fields) -> ReviewItem:
    facts = facts or {}
    length = facts.get("length_m", 0.0)
    return ReviewItem(
        queue=queue,
        osm_way_id=way,
        name=(fields.pop("name", "") or facts.get("name", ""))[:300],
        area=facts.get("area", ""),
        length_m=length,
        aadt=facts.get("aadt"),
        geometry=facts.get("geometry"),
        **fields,
    )


def _replace(queue: str, items: list[ReviewItem]) -> int:
    with transaction.atomic():
        ReviewItem.objects.filter(queue=queue).delete()
        ReviewItem.objects.bulk_create(items, batch_size=2000)
    return len(items)


# --- The queues -----------------------------------------------------------------------------


def change_kind(old: float, new: float, old_closed: bool, new_closed: bool) -> str:
    if new_closed and not old_closed:
        return "closed"
    if old_closed and not new_closed:
        return "reopened"
    return f"{old:g}-{new:g}"


def compute_rebuild(build_id: str, live: str, staging: str) -> int:
    """The rebuild's changes: every way in both tables whose level or bicycle access differs."""
    validate_schema_name(live)
    validate_schema_name(staging)
    if not (_table_exists(live) and _table_exists(staging)):
        return _replace(Queue.REBUILD, [])
    # Compared in the database: only the changed ways come back, never the two whole tables.
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT o.*, n.* FROM ({_agg_sql(live)}) o JOIN ({_agg_sql(staging)}) n "
            "ON o.osm_way_id = n.osm_way_id WHERE o.step <> n.step OR o.closed <> n.closed",
            [CLOSED_CLASS, CLOSED_CLASS],
        )
        changed = [(_row(r[:7]), _row(r[7:])) for r in cursor.fetchall()]
    facts = _facts(staging, [n["way"] for _o, n in changed])
    items = []
    for o, n in changed:
        kind = change_kind(o["step"], n["step"], o["closed"], n["closed"])
        weight = 4.0 if kind in ("closed", "reopened") else abs(n["step"] - o["step"])
        item = _item(
            Queue.REBUILD,
            n["way"],
            facts.get(n["way"]),
            build_id=build_id,
            kind=kind,
            old_step=o["step"],
            new_step=n["step"],
            old_closed=o["closed"],
            new_closed=n["closed"],
            details={"old": _state(o), "new": _state(n)},
            reason=kind_label(Queue.REBUILD, kind),
        )
        item.score = weight * item.length_m
        items.append(item)
    return _replace(Queue.REBUILD, items)


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
        out.append(
            {"key": key, "name": source_name(key), "level": float(level), "pending": is_pending}
        )

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
        add(agency, level, is_pending=True)
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
    schema: str, reports: Path | None = None, pending: dict[int, list] | None = None
) -> int:
    validate_schema_name(schema)
    if not _table_exists(schema):
        return _replace(Queue.DISAGREEMENT, [])
    columns = _columns(schema)
    suggested = _open_suggestions()
    osm = _osm_tiers(reports)
    pending = pending_ratings() if pending is None else pending
    named = sorted(set(suggested) | set(osm) | set(pending))
    held = [c for c in ("stress_ratings", "stress_adjustment_id") if c in columns]
    where = " OR ".join([f"{c} IS NOT NULL" for c in held] + ["osm_way_id = ANY(%s)"])
    found = []
    for row in _way_rows(schema, f"WHERE {where}", [named]):
        sources = rating_sources(
            row, suggested.get(row["way"]), osm.get(row["way"]), pending.get(row["way"], ())
        )
        told = disagreement(sources)
        if told is not None:
            found.append((row, sources, told))
    facts = _facts(schema, [row["way"] for row, _s, _t in found])
    items = []
    for row, sources, (spread, keys, said) in found:
        item = _item(
            Queue.DISAGREEMENT,
            row["way"],
            facts.get(row["way"]),
            kind="-".join(keys)[:40],
            new_step=row["step"],
            new_closed=row["closed"],
            spread=spread,
            sources=keys,
            details={"new": _state(row), "sources": sources},
            reason=said,
        )
        # Size of the disagreement times traffic: the count where there is one (per thousand
        # cars a day, at least 1), along the road's length.
        item.score = spread * item.length_m * max(1.0, (item.aadt or 0) / 1000)
        items.append(item)
    return _replace(Queue.DISAGREEMENT, items)


def compute_narrow_rural(schema: str) -> int:
    validate_schema_name(schema)
    if not _table_exists(schema):
        return _replace(Queue.NARROW_RURAL, [])
    rows = _way_rows(schema, "WHERE stress_rule LIKE %s", [f"%{NARROW_ROAD_RULE}%"])
    facts = _facts(schema, [r["way"] for r in rows])
    reason = (
        "Narrow rural road with no posted speed: read at "
        f"{segment_info.mph_and_kmh(NARROW_RURAL_ROAD_MPH)}"
    )
    items = []
    for row in rows:
        item = _item(
            Queue.NARROW_RURAL,
            row["way"],
            facts.get(row["way"]),
            kind=f"{row['step']:g}",
            new_step=row["step"],
            details={"new": _state(row)},
            reason=reason,
        )
        item.score = item.length_m
        items.append(item)
    return _replace(Queue.NARROW_RURAL, items)


@dataclass(frozen=True)
class FileQueue:
    """A queue read from a rebuild report: a CSV with a way id column."""

    queue: str
    file: str
    way_columns: tuple[str, ...]
    keep: Callable[[dict], bool]
    reason: Callable[[dict], str]
    closed: bool = False


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
    # laid out as `restricted_areas.military_report_csv`: a `status` of closed or open).
    FileQueue(
        Queue.WORKS_CLOSURE,
        "works-closures.csv",
        ("way_id", "osm_way_id"),
        lambda r: (r.get("status") or "closed") == "closed",
        lambda r: r.get("why") or r.get("reason") or "Closed inside an industrial area",
        closed=True,
    ),
    # Override rows the rebuild could not find their way again for (`pipeline.rematch`).
    FileQueue(
        Queue.REMATCH,
        "override-rematch.csv",
        ("old_way_id",),
        lambda r: r.get("outcome") == "failed",
        lambda r: f"A {r.get('kind') or ''} override did not re-match: {r.get('reason') or ''}",
    ),
)


def compute_file_queue(spec: FileQueue, schema: str, reports: Path | None) -> int | None:
    """The queue from its report, or None (left as it was) where the report is not there."""
    path = reports / spec.file if reports else None
    if path is None or not path.is_file():
        return None
    rows: dict[int, dict] = {}
    for row in _read_csv(path):
        if not spec.keep(row):
            continue
        for column in spec.way_columns:
            try:
                rows.setdefault(int(row[column]), row)
                break
            except (KeyError, TypeError, ValueError):
                continue
    facts = _facts(schema, sorted(rows)) if _table_exists(schema) else {}
    now = (
        {r["way"]: r for r in _way_rows(schema, "WHERE osm_way_id = ANY(%s)", [sorted(rows)])}
        if facts
        else {}
    )
    items = []
    for way, row in rows.items():
        current = now.get(way)
        item = _item(
            spec.queue,
            way,
            facts.get(way),
            name=row.get("name") or "",
            kind=(row.get("kind") or row.get("highway") or "")[:40],
            new_step=current["step"] if current else None,
            new_closed=spec.closed or bool(current and current["closed"]),
            details={"new": _state(current), "report": spec.file},
            reason=spec.reason(row)[:500],
        )
        item.score = item.length_m
        items.append(item)
    return _replace(spec.queue, items)


def compute_all(build_id: str, live: str, staging: str | None, reports: Path | None) -> dict:
    """Every queue, against the build waiting in `staging` where there is one (what will be
    served), else the live table. {queue: count, or None where its report is not there}."""
    schema = staging if staging and _table_exists(staging) else live
    counts: dict[str, int | None] = {}
    counts[Queue.REBUILD] = compute_rebuild(build_id, live, staging) if staging else None
    counts[Queue.DISAGREEMENT] = compute_disagreements(schema, reports)
    counts[Queue.NARROW_RURAL] = compute_narrow_rural(schema)
    for spec in FILE_QUEUES:
        counts[spec.queue] = compute_file_queue(spec, schema, reports)
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
    return item.queue == Queue.WORKS_CLOSURE or (
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


def current_build(queue: str) -> str:
    latest = ReviewItem.objects.filter(queue=queue).order_by("-computed_at").first()
    return latest.build_id if latest else ""


def _rulings(queue: str):
    return ReviewRuling.objects.filter(queue=queue, undone_at__isnull=True)


def _ruled_filter(queue: str):
    """An Exists() for an item that has a standing ruling: of this build for the rebuild's
    changes, of any time for the other queues."""
    rulings = _rulings(queue).filter(osm_way_id=OuterRef("osm_way_id"))
    if queue == Queue.REBUILD:
        rulings = rulings.filter(build_id=OuterRef("build_id"))
    return Exists(rulings)


def items_of(queue: str, *, kind: str = "", source: str = "", area: str = ""):
    query = ReviewItem.objects.filter(queue=queue)
    if queue == Queue.REBUILD:
        query = query.filter(build_id=current_build(queue))
    if kind:
        query = query.filter(kind=kind)
    if source:
        query = query.filter(sources__contains=[source])
    if area:
        query = query.filter(area=area)
    return query.annotate(ruled=_ruled_filter(queue))


def queue_summary() -> list[dict]:
    """Each queue: how many roads, how many have a ruling, its filters, and whether it is wired."""
    out = []
    for queue, label in Queue.choices:
        query = items_of(queue)
        kinds: dict[str, int] = {}
        areas: dict[str, int] = {}
        sources: dict[str, int] = {}
        total = reviewed = 0
        for kind, area, keys, ruled in query.values_list("kind", "area", "sources", "ruled"):
            total += 1
            reviewed += bool(ruled)
            kinds[kind] = kinds.get(kind, 0) + 1
            if area:
                areas[area] = areas.get(area, 0) + 1
            for key in keys or []:
                sources[key] = sources.get(key, 0) + 1
        out.append(
            {
                "queue": queue,
                "label": label,
                "build_id": current_build(queue) if queue == Queue.REBUILD else "",
                "total": total,
                "reviewed": reviewed,
                "wired": total > 0
                or queue in (Queue.REBUILD, Queue.DISAGREEMENT, Queue.NARROW_RURAL),
                "kinds": [
                    {"kind": k, "label": kind_label(queue, k), "count": n}
                    for k, n in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))
                ],
                "areas": [{"area": a, "count": n} for a, n in sorted(areas.items())],
                "sources": [
                    {"source": s, "label": source_name(s), "count": n}
                    for s, n in sorted(sources.items())
                ],
            }
        )
    return out


def latest_rulings(queue: str, ways: list[int], build_id: str = "") -> dict[int, ReviewRuling]:
    query = _rulings(queue).filter(osm_way_id__in=ways)
    if queue == Queue.REBUILD:
        query = query.filter(build_id=build_id)
    out: dict[int, ReviewRuling] = {}
    for ruling in query.order_by("at", "id"):
        out[ruling.osm_way_id] = ruling
    return out


def ruling_out(ruling: ReviewRuling, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    return {
        "id": ruling.pk,
        "queue": ruling.queue,
        "osm_way_id": ruling.osm_way_id,
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
    old, new = details.get("old") or {}, details.get("new") or {}
    geometry = json.loads(item.geometry.geojson) if item.geometry is not None else None
    return {
        "queue": item.queue,
        "osm_way_id": item.osm_way_id,
        "name": name or item.name or "",
        "area": item.area,
        "reason": item.reason,
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
        "aadt": item.aadt,
        "bbox": list(item.geometry.extent) if item.geometry is not None else None,
        "geometry": geometry,
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
        query = query.filter(osm_way_id=way)
    if open_only:
        query = query.filter(ruled=False)
    total = query.count()
    rows = list(query.order_by("-score", "osm_way_id")[(number - 1) * size : number * size])
    build = current_build(queue) if queue == Queue.REBUILD else ""
    ruled = latest_rulings(queue, [r.osm_way_id for r in rows], build)
    return {
        "queue": queue,
        "build_id": build,
        "page": number,
        "per_page": size,
        "total": total,
        "items": [item_out(r, ruled.get(r.osm_way_id)) for r in rows],
    }


def map_features(queue: str, bbox: tuple[float, float, float, float], **filters) -> dict:
    """The queue's roads in a box, for Review's overlay, coloured by `spread` (or the change)."""
    box = Polygon.from_bbox(bbox)
    box.srid = 4326
    query = items_of(queue, **filters).filter(geometry__bboverlaps=box).order_by("-score")[:MAP_MAX]
    features = []
    for item in query:
        if item.geometry is None:
            continue
        size = (
            item.spread
            if item.spread is not None
            else abs((item.new_step or 0) - (item.old_step or 0))
        )
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(item.geometry.geojson),
                "properties": {
                    "way": item.osm_way_id,
                    "size": 4.0 if item.new_closed and not item.old_closed else size,
                    "ruled": bool(item.ruled),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def unruled_rebuild_changes() -> tuple[int, int, str]:
    """(changed roads with no ruling yet, changed roads, build) for the swap's report."""
    query = items_of(Queue.REBUILD)
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
    return Override.objects.create(
        kind=Override.Kind.ACCESS,
        osm_way_id=way,
        value=dict(REOPEN_VALUE),
        reason=reason,
        evidence=EVIDENCE,
        approved=True,
        approved_at=now,
        source=Override.Source.ADMIN,
        created_by=actor,
        created_by_user_id=getattr(actor, "pk", None),
        approved_by=actor,
        approved_by_user_id=getattr(actor, "pk", None),
    )


def _rule_one(
    actor, item: ReviewItem, decision: str, step, reason: str, now: datetime
) -> ReviewRuling:
    if decision not in actions(item):
        raise stress_edits.Invalid("That ruling is not offered for this road.", "decision")
    edit = access = None
    target: float | None = None
    with transaction.atomic():
        if decision == Decision.REJECT and is_closure(item):
            access = _reopen(actor, item.osm_way_id, reason or default_reason(now), now)
        elif decision != Decision.ACCEPT:
            target = item.old_step if decision == Decision.REJECT else step
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
            rows = stress_edits.read_rows(schema, columns, [item.osm_way_id]) if columns else {}
            if not rows:
                raise stress_edits.NotFound("That road is not in the map being served.")
            expected = stress_edits.token_of(rows, [item.osm_way_id])
            edit = stress_edits.apply(
                actor, [item.osm_way_id], spec, expected, now=now, evidence=EVIDENCE
            ).edit
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
        )
        audit.record(
            actor,
            "review_ruling",
            "review_ruling",
            ruling.pk,
            AuditLogEntry.Outcome.ALLOWED,
            detail=(
                f"{item.queue} {item.build_id} way {item.osm_way_id}: {ruling_words(ruling)}"
                + (f"; edit {edit.pk}" if edit else "")
                + (f"; access override {access.pk}" if access else "")
            )[:2000],
        )
    return ruling


def rule(
    actor,
    queue: str,
    way_ids: list[int],
    decision: str,
    *,
    step: float | None = None,
    reason: str | None = None,
    now: datetime | None = None,
) -> tuple[list[ReviewRuling], list[dict]]:
    """Rule on one road or a batch. Returns (the rulings made, the roads refused with why)."""
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
    items = {i.osm_way_id: i for i in items_of(queue).filter(osm_way_id__in=ways)}
    made: list[ReviewRuling] = []
    refused: list[dict] = []
    for way in ways:
        item = items.get(way)
        if item is None:
            refused.append({"osm_way_id": way, "error": "That road is not in this queue."})
            continue
        try:
            made.append(_rule_one(actor, item, decision, step, text, now or timezone.now()))
        except stress_edits.EditRefused as refusal:
            refused.append({"osm_way_id": way, "error": refusal.message})
    return made, refused


def undo(actor, ruling_id: int, *, now: datetime | None = None) -> tuple[ReviewRuling, int | None]:
    """Undo a ruling within the editor's undo window: its stress change by the editor's own
    undo, its reopening by withdrawing the access row's approval."""
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
        generation = None
        if ruling.edit_id:
            generation = stress_edits.undo(actor, ruling.edit_id, now=now).generation
        if ruling.access_override_id:
            Override.objects.filter(pk=ruling.access_override_id).update(approved=False)
        ruling.undone_at = now
        ruling.undone_by = actor
        ruling.save(update_fields=["undone_at", "undone_by"])
        audit.record(
            actor,
            "review_ruling_undo",
            "review_ruling",
            ruling.pk,
            AuditLogEntry.Outcome.ALLOWED,
            detail=f"{ruling.queue} way {ruling.osm_way_id}: {ruling_words(ruling)} undone",
        )
    return ruling, generation


def road_detail(way: int) -> dict:
    """The facts behind a road's rating as the live table holds them (the road panel's own rows:
    level and rule, speed, lanes and count with their sources, facility), and its history: the
    stress edits, override rows and rulings on it, newest first."""
    from .models import StressEdit

    schema = stress_edits.live_schema()
    facts: list[dict] = []
    if _table_exists(schema):
        columns = _columns(schema)
        step = _step_sql(columns)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {schema}.segment WHERE osm_way_id = %s "
                f"ORDER BY {step} DESC, ordinal LIMIT 1",
                [way],
            )
            found = cursor.fetchone()
            names = [d[0] for d in cursor.description]
        if found is not None:
            row = dict(zip(names, found, strict=True))
            facts = (
                segment_info.stress_rows(row)
                + segment_info.traffic_rows(row)
                + segment_info.riding_rows(row)
            )
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
        what = f"{row.get_kind_display()} override ({row.get_source_display()}), {state}" + (
            f": {level_label(float(level) + (0.5 if value.get('half') else 0))}" if level else ""
        )
        # A row never approved has no date of its own; it sorts last.
        history.append({"at": row.approved_at.isoformat() if row.approved_at else "", "what": what})
    for ruling in ReviewRuling.objects.filter(osm_way_id=way).order_by("-at")[:20]:
        what = f"Review ({ruling.get_queue_display()}): {ruling_words(ruling)}"
        history.append(
            {"at": ruling.at.isoformat(), "what": what + (" (undone)" if ruling.undone_at else "")}
        )
    history.sort(key=lambda h: h["at"], reverse=True)
    return {"osm_way_id": way, "facts": facts, "history": history}


def recent_rulings(queue: str | None = None, limit: int = 50) -> list[dict]:
    query = ReviewRuling.objects.all()
    if queue:
        query = query.filter(queue=queue)
    now = timezone.now()
    return [ruling_out(r, now) for r in query.order_by("-at", "-id")[:limit]]


def reports_dir(path: str | None) -> Path | None:
    """The rebuild's reports: `path` (relative to the rebuild's work directory), else its own."""
    base = Path(settings.REBUILD_WORK_DIR)
    if path:
        found = Path(path) if Path(path).is_absolute() else base / path
    else:
        found = base / "reports"
    return found if found.is_dir() else None
