"""The road panel's "Change LTS": an instance admin's change of a road's traffic stress.

OWNER-DECISIONS 441g, 441h, 460 (HALF-STEP-EDITOR-plan.md, phase 1: whole steps 1 to 5).

An instance admin's change applies at once. `apply` does all of this in ONE transaction:

1. locks the way, and refuses with `Stale` when the live row is not what the editor
   opened with (`expected`);
2. writes the approved `Override` row (`source="panel"`) and marks the row it replaces
   *superseded* - never unapproved, because `load_access_overrides` re-approves an
   unapproved row that matches a file, so reloading an old file would silently undo the
   edit;
3. updates the live segment rows in place, with the same rules the rebuild applies
   (`pipeline.overrides`): a floor the classifier already meets changes nothing;
4. writes the `StressEdit` (what each row held before and after: the audit log
   deliberately keeps no copy of a row) and one audit entry;
5. bumps the live table's edit generation, which is in the tile ETag, and deletes only
   the cached tiles that cover the road, keeping the rest of the cache warm.

What waits for the next rebuild: Valhalla's edge costs, the z12-13 ride layer and the
Mass Ride capacity layers. RouteMaker's own ranking, the road panel and route
descriptions read the live table at route time and have it at once.

A rebuild or a rollback that was running when an admin edited would otherwise promote a
table without the edit: `after_promotion` and `after_rollback` re-apply the edits made
after the promoted table read its overrides.

Who: `Override.created_by`/`approved_by`, `StressEdit.actor` and the audit entry carry the
application's user id, never the Discord id. The private reason is on the override row and
is never in the segment table, the tiles, a route answer or a public panel; the public
surfaces still say "Owner override".
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from pipeline import overrides
from pipeline.schema import validate_schema_name
from routemaker.stress import ADJUSTMENT_CATEGORIES, ADJUSTMENT_DISPLAYS

from . import audit, segment_info, stress_tiles, tile_cache
from .models import AuditLogEntry, LiveEditGeneration, Override, StressEdit

logger = logging.getLogger(__name__)

# Phase 1 is whole steps. (Half steps are phase 2 and widen this and the value rules.)
STEPS = (1, 2, 3, 4, 5)
# OWNER-DECISIONS 460.8-11: "30-min Undo + full history". The history is the StressEdit
# table; the Undo button and the endpoint stop answering after this long, and a later
# reversal is a new change.
UNDO_WINDOW = timedelta(minutes=30)
REASON_MAX = 500
# One road piece in phase 1; the named stretch (phase 5) widens it.
MAX_WAYS = 1
EVIDENCE = "Instance admin's change in the road panel"
# The classifier's own rule text is not kept on a live row once an override has replaced it.
FLOOR_MET_RULE = "classifier (an owner override's floor was already met)"

TIER_COLUMN = "stress_tier"
RULE_COLUMN = "stress_rule"
ADJUSTMENT_COLUMNS = (
    "stress_adjustment_id",
    "stress_computed_tier",
    "stress_adjustment_direction",
    "stress_adjustment_category",
    "stress_adjustment_note",
    "stress_adjustment_display",
)
EDIT_COLUMNS = (TIER_COLUMN, RULE_COLUMN, *ADJUSTMENT_COLUMNS)

# pg_advisory_xact_lock key: one lock per way, so two edits of one road never interleave.
_LOCK_BASE = 0x5354_0000_0000_0000


class EditRefused(Exception):
    """The edit cannot be made; `status` is the HTTP answer for it."""

    status = 400
    code = "invalid"

    def __init__(self, message: str, field: str | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        if code:
            self.code = code


class Invalid(EditRefused):
    status = 400


class NotFound(EditRefused):
    status = 404
    code = "not_found"


class Stale(EditRefused):
    """The road changed since the editor opened (409)."""

    status = 409
    code = "stale"


@dataclass(frozen=True)
class Spec:
    """What the admin asked for."""

    tier: int
    at_least: bool
    category: str
    reason: str
    public_note: str | None = None
    display: str = "route_only"

    def value(self, adjustment_id: str) -> dict:
        """The override row's value (`pipeline.overrides.stress_value_problem` holds the rules)."""
        value = {
            "tier": self.tier,
            "adjustment_id": adjustment_id,
            "category": self.category,
            # A note makes the adjustment public, so its category and note are shown on a
            # click; with none the row says only that the tier was adjusted.
            "visibility": "public" if self.public_note else "hidden",
            # The owner (an instance admin) wrote it: no review step before it shows.
            "annotation_status": "approved",
            "display": self.display,
        }
        if self.public_note:
            value["public_note"] = self.public_note
        if self.at_least:
            value["at_least"] = True
        return value


def validate(spec: Spec) -> None:
    """Refuse a spec the value rules would refuse, naming the field."""
    if spec.tier not in STEPS:
        raise Invalid("The level is a whole step from 1 to 5.", "step")
    if spec.category not in ADJUSTMENT_CATEGORIES:
        raise Invalid("Choose the reason's category from the list.", "category")
    if spec.display not in ADJUSTMENT_DISPLAYS:
        raise Invalid("Choose where the note shows from the list.", "display")
    reason = spec.reason.strip() if isinstance(spec.reason, str) else ""
    if not reason:
        raise Invalid("A private reason is required.", "reason")
    if len(spec.reason) > REASON_MAX:
        raise Invalid(f"The private reason is at most {REASON_MAX} characters.", "reason")
    if spec.public_note is not None and spec.display not in ADJUSTMENT_DISPLAYS:
        raise Invalid("Choose where the note shows from the list.", "display")
    problem = overrides.stress_value_problem(spec.value("edit-1"))
    if problem:
        field_name = "public_note" if "public_note" in problem else None
        raise Invalid(problem[:1].upper() + problem[1:] + ".", field_name)


# --- The live table ------------------------------------------------------------------


def live_schema() -> str:
    return validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)


def live_oid(schema: str) -> int | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)::oid", [f"{schema}.segment"])
        row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def edit_columns(schema: str) -> list[str]:
    have = segment_info.live_columns(schema)
    if TIER_COLUMN not in have or RULE_COLUMN not in have:
        return []
    return [c for c in EDIT_COLUMNS if c in have]


def key_of(way_id: int, ordinal: int) -> str:
    return f"{way_id}:{ordinal}"


def read_rows(schema: str, columns: list[str], way_ids: list[int], *, lock: bool = False) -> dict:
    """{"way:ordinal": {column: value}} for the ways, in order."""
    names = ", ".join(columns)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT osm_way_id, ordinal, {names} FROM {schema}.segment "
            f"WHERE osm_way_id = ANY(%s) ORDER BY osm_way_id, ordinal"
            + (" FOR UPDATE" if lock else ""),
            [way_ids],
        )
        rows = cursor.fetchall()
    return {
        key_of(row[0], row[1]): {
            name: _plain(value) for name, value in zip(columns, row[2:], strict=True)
        }
        for row in rows
    }


def _plain(value):
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else value


def write_rows(schema: str, states: dict) -> int:
    """Set each row to its state where it differs; returns how many rows changed."""
    changed = 0
    columns = edit_columns(schema)
    with connection.cursor() as cursor:
        for key, state in states.items():
            way, ordinal = (int(part) for part in key.split(":"))
            use = [c for c in columns if c in state]
            if not use:
                continue
            assignments = ", ".join(f"{c} = %s" for c in use)
            differs = " OR ".join(f"{c} IS DISTINCT FROM %s" for c in use)
            values = [state[c] for c in use]
            cursor.execute(
                f"UPDATE {schema}.segment SET {assignments} "
                f"WHERE osm_way_id = %s AND ordinal = %s AND ({differs})",
                [*values, way, ordinal, *values],
            )
            changed += cursor.rowcount
    return changed


def _lock_ways(way_ids: list[int]) -> None:
    with connection.cursor() as cursor:
        for way in sorted(way_ids):
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_BASE + int(way)])


def _bbox(schema: str, way_ids: list[int]) -> tuple[float, float, float, float] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
            f"(SELECT ST_Extent(geometry) AS e FROM {schema}.segment WHERE osm_way_id = ANY(%s)) t",
            [way_ids],
        )
        row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return tuple(float(v) for v in row)  # type: ignore[return-value]


# --- What a row holds, and what an edit makes it hold --------------------------------


def is_adjusted(row: dict) -> bool:
    return row.get("stress_adjustment_id") is not None or str(
        row.get(RULE_COLUMN) or ""
    ).startswith("override:")


def classifier_tier(row: dict) -> int | None:
    """The tier the classifier gave the way, or None when the row does not say.

    A way no override reached carries it as its tier. An adjusted way carries it only
    where the adjustment is public (`StressAdjustment.exposed`): a hidden adjustment's
    row says nothing of what it replaced, and nothing here guesses.
    """
    if not is_adjusted(row):
        return int(row[TIER_COLUMN])
    computed = row.get("stress_computed_tier")
    return int(computed) if computed is not None else None


def new_state(row: dict, spec: Spec, adjustment_id: str, base: int | None) -> dict:
    """What `row` holds once `spec` is applied (the rebuild's `apply_stress`, in place)."""
    state: dict = {}
    if spec.at_least and base is not None and base >= spec.tier:
        # A floor the way already meets: the classifier's tier stands and so does its rule,
        # where the row still has it.
        state[TIER_COLUMN] = base
        state[RULE_COLUMN] = FLOOR_MET_RULE if is_adjusted(row) else row[RULE_COLUMN]
        for column in ADJUSTMENT_COLUMNS:
            if column in row:
                state[column] = None
        return state
    state[TIER_COLUMN] = spec.tier
    state[RULE_COLUMN] = f"override: stress adjustment {adjustment_id}"
    shown = bool(spec.public_note)
    if base is None:
        direction = None
    elif spec.tier > base:
        direction = "up"
    elif spec.tier < base:
        direction = "down"
    else:
        direction = "same"
    wanted = {
        "stress_adjustment_id": adjustment_id,
        "stress_computed_tier": base if shown else None,
        "stress_adjustment_direction": direction if shown else None,
        "stress_adjustment_category": spec.category if shown else None,
        "stress_adjustment_note": spec.public_note if shown else None,
        "stress_adjustment_display": spec.display if shown else None,
    }
    for column in ADJUSTMENT_COLUMNS:
        if column in row:
            state[column] = wanted[column]
    return state


def token_for(rows: dict, live: Override | None) -> str:
    """An opaque stamp of the road's state: the editor sends it back, and a change in between
    (another admin's edit, a promotion that rebuilt the table) makes the edit stale."""
    material = json.dumps(
        [
            live.pk if live else 0,
            [[k, r.get(TIER_COLUMN), r.get(RULE_COLUMN)] for k, r in rows.items()],
        ],
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:20]


def _live_override(way_ids: list[int], *, lock: bool = False) -> Override | None:
    query = Override.objects.filter(
        kind=Override.Kind.STRESS, osm_way_id__in=way_ids, approved=True, superseded_by__isnull=True
    )
    if lock:
        query = query.select_for_update()
    return query.order_by("-id").first()


# --- The editor's starting state -----------------------------------------------------


def editor_state(actor, way_id: int, now: datetime | None = None) -> dict:
    """What the editor opens with for one way; raises NotFound for a way not in the data."""
    now = now or timezone.now()
    schema = live_schema()
    columns = edit_columns(schema)
    if live_oid(schema) is None or not columns:
        raise NotFound("There is no road data to change yet.")
    rows = read_rows(schema, columns, [way_id])
    if not rows:
        raise NotFound("That road is not in the data.")
    live = _live_override([way_id])
    first = next(iter(rows.values()))
    base = classifier_tier(first)
    current: dict = {
        "step": int(first[TIER_COLUMN]),
        "words": segment_info.TIER_WORDS.get(int(first[TIER_COLUMN]), ""),
        "source": "classifier",
        "at_least": False,
        "category": None,
        "public_note": None,
        "display": None,
        "private_reason": None,
        "when": None,
        "by": None,
    }
    if live is not None:
        value = live.value if isinstance(live.value, dict) else {}
        current.update(
            source=(
                "panel"
                if live.source == Override.Source.PANEL
                else "file"
                if live.source == Override.Source.FILE
                else "admin"
            ),
            at_least=value.get("at_least") is True,
            category=value.get("category"),
            public_note=value.get("public_note"),
            display=value.get("display"),
            private_reason=live.reason or None,
            when=(live.approved_at or None) and live.approved_at.isoformat(),
            by=(
                None
                if live.created_by_user_id is None
                else "you"
                if live.created_by_user_id == getattr(actor, "pk", None)
                else "another admin"
            ),
        )
    recent = (
        StressEdit.objects.filter(osm_way_ids__contains=[way_id], at__gte=now - UNDO_WINDOW)
        .order_by("-id")
        .first()
    )
    recent_out = None
    if recent is not None:
        recent_out = {
            "id": recent.pk,
            "action": recent.action,
            "at": recent.at.isoformat(),
            "can_undo": can_undo(recent, now),
        }
    return {
        "osm_way_id": way_id,
        "classifier_step": base,
        "can_raise_only": base is not None,
        "current": current,
        "expected": token_for(rows, live),
        "steps": [{"value": s, "words": segment_info.TIER_WORDS[s]} for s in STEPS],
        "categories": [
            {"id": k, "label": v} for k, v in segment_info.ADJUSTMENT_CATEGORIES.items()
        ],
        "reason_max": REASON_MAX,
        "note_max": overrides.PUBLIC_NOTE_MAX,
        "recent_edit": recent_out,
        "pieces": len(rows),
    }


# --- Applying and undoing ------------------------------------------------------------


@dataclass
class EditResult:
    edit: StressEdit
    ways: list[dict] = field(default_factory=list)
    generation: int = 0


def _actor_fields(actor) -> dict:
    return {"actor": actor, "actor_user_id": getattr(actor, "pk", None)}


def _summary(before: dict, after: dict) -> str:
    parts = []
    for key in after:
        was = (before.get(key) or {}).get(TIER_COLUMN)
        now = after[key].get(TIER_COLUMN)
        parts.append(f"{key}: LTS {was} -> {now}")
    return "; ".join(parts[:8])[:1500]


def bump_generation(schema: str, ways: list[int]) -> int:
    """Bump the live table's edit generation and refresh the cached tiles over `ways`.

    Deletes only the cached tiles covering the ways (plus a tile's margin) at every zoom,
    for the stress tiles and the Mass Ride tiles that share the cache, and re-keys the rest
    to the new generation so the cache stays warm.
    """
    oid, optional, generation = stress_tiles.live_state()
    if oid is None:
        return 0
    from . import mass_tiles

    row, _ = LiveEditGeneration.objects.select_for_update().get_or_create(table_oid=oid)
    new = row.generation + 1
    versions = {
        stress_tiles.etag_for(oid, optional, row.generation): stress_tiles.etag_for(
            oid, optional, new
        ),
        mass_tiles.etag_for(oid, optional, row.generation): mass_tiles.etag_for(oid, optional, new),
    }
    row.generation = new
    row.updated_at = timezone.now()
    row.save(update_fields=["generation", "updated_at"])
    tile_cache.rekey_after_edit(_bbox(schema, ways), versions)
    return new


def apply(
    actor,
    way_ids: list[int],
    spec: Spec,
    expected: str,
    *,
    now: datetime | None = None,
) -> EditResult:
    """Make the change, at once. Raises EditRefused (Invalid, NotFound or Stale)."""
    way_ids = sorted(set(int(w) for w in way_ids))
    if not way_ids or len(way_ids) > MAX_WAYS:
        raise Invalid(f"Change {MAX_WAYS} road piece at a time.", "osm_way_ids")
    validate(spec)
    now = now or timezone.now()
    schema = live_schema()
    try:
        with transaction.atomic():
            _lock_ways(way_ids)
            columns = edit_columns(schema)
            oid = live_oid(schema)
            if oid is None or not columns:
                raise NotFound("There is no road data to change yet.")
            rows = read_rows(schema, columns, way_ids, lock=True)
            if not {int(k.split(":")[0]) for k in rows} >= set(way_ids):
                raise NotFound("That road is not in the data.")
            live = _live_override(way_ids, lock=True)
            if token_for(rows, live) != expected:
                raise Stale(
                    "Someone changed this road since you opened it. Reopen it to see the change."
                )

            bases = {k: classifier_tier(r) for k, r in rows.items()}
            if spec.at_least and any(b is None for b in bases.values()):
                raise Invalid(
                    "Only raise it is not available here: an earlier override hides the level "
                    "the classifier gave this road. Set an exact level instead.",
                    "at_least",
                    "classifier_hidden",
                )

            # The new row, inert until the old one is out of the way (one live row a way).
            row = Override.objects.create(
                kind=Override.Kind.STRESS,
                osm_way_id=way_ids[0],
                value={},
                reason=spec.reason.strip(),
                evidence=EVIDENCE,
                approved=False,
                source=Override.Source.PANEL,
                created_by=actor,
                created_by_user_id=getattr(actor, "pk", None),
            )
            adjustment_id = f"edit-{row.pk}"
            row.value = spec.value(adjustment_id)
            row.save(update_fields=["value"])
            if live is not None:
                Override.objects.filter(pk=live.pk).update(superseded_by=row, superseded_at=now)
            row.approved = True
            row.approved_at = now
            row.approved_by = actor
            row.approved_by_user_id = getattr(actor, "pk", None)
            row.save(
                update_fields=["approved", "approved_at", "approved_by", "approved_by_user_id"]
            )

            after = {k: new_state(r, spec, adjustment_id, bases[k]) for k, r in rows.items()}
            before = {k: {c: r.get(c) for c in after[k]} for k, r in rows.items()}
            write_rows(schema, after)
            now_rows = read_rows(schema, columns, way_ids)
            ways = []
            for way in way_ids:
                keys = [k for k in rows if k.startswith(f"{way}:")]
                changed = any(
                    {c: rows[k].get(c) for c in after[k]}
                    != {c: now_rows[k].get(c) for c in after[k]}
                    for k in keys
                )
                ways.append(
                    {
                        "osm_way_id": way,
                        "step": int(now_rows[keys[0]][TIER_COLUMN]),
                        "changed": changed,
                    }
                )
            generation = bump_generation(schema, way_ids)
            edit = StressEdit.objects.create(
                at=now,
                action=StressEdit.Action.SET,
                override=row,
                replaced=live,
                osm_way_ids=way_ids,
                before=before,
                after={k: {c: now_rows[k].get(c) for c in after[k]} for k in rows},
                applied_to=oid,
                generation=generation,
                **_actor_fields(actor),
            )
            audit.record(
                actor,
                "stress_edit",
                "override",
                row.pk,
                AuditLogEntry.Outcome.ALLOWED,
                detail=f"edit {edit.pk}, generation {generation}; {_summary(before, after)}",
            )
    except IntegrityError as error:
        # Another request made a live row for this way between our read and our write.
        raise Stale(
            "Someone changed this road since you opened it. Reopen it to see the change."
        ) from error
    return EditResult(edit=edit, ways=ways, generation=generation)


def can_undo(edit: StressEdit, now: datetime) -> bool:
    """Whether `edit` can be undone now: a change, within the window, not yet undone, and
    no later edit has touched its ways."""
    if edit.action != StressEdit.Action.SET or now - edit.at > UNDO_WINDOW:
        return False
    if StressEdit.objects.filter(undoes=edit).exists():
        return False
    return not _later_touching(edit)


def _later_touching(edit: StressEdit) -> bool:
    for later in StressEdit.objects.filter(pk__gt=edit.pk):
        if set(later.osm_way_ids) & set(edit.osm_way_ids):
            return True
    return False


def undo(actor, edit_id: int, *, now: datetime | None = None) -> EditResult:
    """Put an edit's `before` state back. Any instance admin may, within UNDO_WINDOW."""
    now = now or timezone.now()
    schema = live_schema()
    with transaction.atomic():
        try:
            edit = StressEdit.objects.select_for_update().get(pk=edit_id)
        except StressEdit.DoesNotExist as error:
            raise NotFound("There is no such change.") from error
        if edit.action != StressEdit.Action.SET:
            raise Invalid("Only a change can be undone.", None, "not_a_change")
        way_ids = [int(w) for w in edit.osm_way_ids]
        _lock_ways(way_ids)
        if StressEdit.objects.filter(undoes=edit).exists():
            raise Stale("That change has already been undone.", None, "already_undone")
        if now - edit.at > UNDO_WINDOW:
            raise Stale(
                "That change is older than 30 minutes, so it can no longer be undone here. "
                "Make a new change instead.",
                None,
                "too_old",
            )
        if _later_touching(edit):
            raise Stale(
                "This road has been changed since. Reopen it and make a new change instead.",
                None,
                "later_edit",
            )
        columns = edit_columns(schema)
        oid = live_oid(schema)
        if oid is None or not columns:
            raise NotFound("There is no road data to change yet.")
        rows = read_rows(schema, columns, way_ids, lock=True)
        held = {
            k: {c: rows[k].get(c) for c in edit.after.get(k, {})} for k in rows if k in edit.after
        }
        if held != edit.after:
            # The table was rebuilt with other values (or edited by hand) since.
            raise Stale(
                "The road data has been updated since this change, so it cannot be undone here. "
                "Make a new change instead.",
                None,
                "table_changed",
            )
        new_row = edit.override
        old_row = edit.replaced
        reinstated = None
        if new_row is not None:
            if old_row is not None and old_row.superseded_by_id == new_row.pk:
                Override.objects.filter(pk=new_row.pk).update(
                    superseded_by=old_row, superseded_at=now
                )
                Override.objects.filter(pk=old_row.pk).update(
                    superseded_by=None, superseded_at=None
                )
                reinstated = old_row
            else:
                Override.objects.filter(pk=new_row.pk).update(approved=False)
        write_rows(schema, edit.before)
        now_rows = read_rows(schema, columns, way_ids)
        generation = bump_generation(schema, way_ids)
        undone = StressEdit.objects.create(
            at=now,
            action=StressEdit.Action.UNDO,
            override=reinstated,
            replaced=new_row,
            undoes=edit,
            osm_way_ids=way_ids,
            before=edit.after,
            after={
                k: {c: now_rows[k].get(c) for c in edit.before.get(k, {})}
                for k in now_rows
                if k in edit.before
            },
            applied_to=oid,
            generation=generation,
            **_actor_fields(actor),
        )
        audit.record(
            actor,
            "stress_edit_undo",
            "override",
            new_row.pk if new_row else "",
            AuditLogEntry.Outcome.ALLOWED,
            detail=f"edit {edit.pk} undone by {undone.pk}, generation {generation}; "
            f"{_summary(edit.after, undone.after)}",
        )
    ways = [
        {
            "osm_way_id": w,
            "step": int(next(r[TIER_COLUMN] for k, r in now_rows.items() if k.startswith(f"{w}:"))),
            "changed": True,
        }
        for w in way_ids
    ]
    return EditResult(edit=undone, ways=ways, generation=generation)


# --- Promotions and rollbacks --------------------------------------------------------


def reapply_since(since: datetime | None) -> int:
    """Re-apply the edits made after `since` (every edit when None) to the live table.

    In order, from each edit's `after`, so a change and a later undo of it both replay and the
    way ends where it should. Idempotent: a row already in the edit's state is left alone, so
    running it twice does nothing the second time. Returns the number of rows it changed.
    """
    schema = live_schema()
    oid = live_oid(schema)
    if oid is None or not edit_columns(schema):
        return 0
    edits = StressEdit.objects.all() if since is None else StressEdit.objects.filter(at__gt=since)
    changed_ways: set[int] = set()
    total = 0
    with transaction.atomic():
        for edit in edits.order_by("id"):
            _lock_ways([int(w) for w in edit.osm_way_ids])
            changed = write_rows(schema, edit.after)
            if changed:
                total += changed
                changed_ways.update(int(w) for w in edit.osm_way_ids)
                if oid not in edit.reapplied_to and oid != edit.applied_to:
                    StressEdit.objects.filter(pk=edit.pk).update(
                        reapplied_to=[*edit.reapplied_to, oid]
                    )
        if changed_ways:
            bump_generation(schema, sorted(changed_ways))
    return total


def after_promotion(overrides_read_at: datetime | None) -> int:
    """The swap has made a rebuilt table live: note when it read its overrides, and re-apply
    the edits made since. Never raises into the promotion: an edit not re-applied now is still
    an approved override row, and the next rebuild reads it."""
    try:
        schema = live_schema()
        oid = live_oid(schema)
        if oid is None:
            return 0
        row, _ = LiveEditGeneration.objects.get_or_create(table_oid=oid)
        LiveEditGeneration.objects.filter(pk=row.pk).update(overrides_read_at=overrides_read_at)
        if overrides_read_at is None:
            return 0
        return reapply_since(overrides_read_at)
    except Exception:  # noqa: BLE001 - the promotion stands whatever this does
        logger.exception("could not re-apply the road panel's edits after the promotion")
        return -1


def after_rollback() -> int:
    """A rollback has made an older table live again: re-apply every edit made after it read
    its overrides (all of them where it never recorded when)."""
    try:
        schema = live_schema()
        oid = live_oid(schema)
        if oid is None:
            return 0
        known = LiveEditGeneration.objects.filter(table_oid=oid).first()
        return reapply_since(known.overrides_read_at if known else None)
    except Exception:  # noqa: BLE001 - the rollback stands whatever this does
        logger.exception("could not re-apply the road panel's edits after the rollback")
        return -1
