"""`manage.py load_access_overrides` - load a reviewed file of access overrides.

An access correction reaches the graph only as an approved `Override` row
(PLAN's audited path; `pipeline.overrides.load_approved` reads nothing else).
Some corrections are decided outside the admin - the owner answering a question
about a bridge approach - and typing them into the admin one way at a time
loses the decision's wording and date. So they are checked in as a versioned
file under `fixtures/overrides/`, reviewed like any other change, and loaded by
this command, which writes what the admin path writes: the row, and an
`AuditLogEntry` for adding it and for approving it, attributed to the instance
admin named by `--actor`.

`--actor` is named on the command line and not authenticated. The command
checks that the id belongs to an active instance admin; nothing checks that the
person at the shell is that admin, and anyone who can run this can already
write the database. `run_rebuild_now` and `rollback_rebuild` record no actor for
the same reason; this command records the named one, because an approval is a
decision somebody is answerable for, and says in every entry's `detail` that
the name was given rather than proven (`ACTOR_NOTE`).

Dry by default, like `rollback_rebuild`: without `--confirm` it prints what it
would do and writes nothing. Idempotent: a row already present and approved
with the same kind, way and value is left alone and audited as nothing, so a
second run is a no-op; one present but unapproved is approved, and its reason
and evidence become the file's - the decision being loaded is why it is
approved - with the proposal's own text kept in the audit entry. It refuses the
whole file, before writing anything, if any row is malformed, writes a key an
access override may not write, or disagrees with an approved row already on the
same way - two approved rows answering one way differently would be applied in
id order, which is not a decision anybody made.

Two kinds are loaded. `access` rows write access keys (`ACCESS_KEYS`), among
them `motor_vehicle`, for a road the owner knows is closed to cars for good. `stress`
rows write a tier, 1 to 5, the tier the rebuild gives the way after
classification (`pipeline.overrides.apply_stress`) - the owner's curated tiers of
2026-09-27, "legal but avoid" (5) among them - and the adjustment it makes: a
stable `adjustment_id` shared by the ways of one stretch, a `category`, a
`visibility` (`public` or `hidden`), an `annotation_status` (`proposed` until
the owner approves the category and note) and an optional rider-facing
`public_note` (`pipeline.overrides.stress_value_problem` has the rules). Rows
sharing an adjustment id must agree on everything but the way. A stress row
already approved with the same tier and different adjustment fields is
updated in place (`update`, audited as a change); a different tier is a
conflict. `load_overrides` is the same command under the name that says so.

A row may carry a `fingerprint` of its way (`pipeline.rematch`), checked here and kept in
the file: the database row does not hold it, and the rebuild reads it from the image's
copy of the file, to re-match the row if OSM splits or merges the way.

A file may also `retire` rows a later decision withdraws: a top-level list of
`{"kind", "osm_way_id", "value", "reason"}`, the row as it was loaded and the
decision that withdraws it. Each approved or proposed row of that kind, way and
exact value is deleted (audited as a delete, with the file's reason), before the
file's own rows are planned, so a row that replaces it on the same way is not
refused as a conflict. One already gone is `absent`, so a second run is a no-op.
A row whose value differs is left alone: only what the file names is withdrawn.
A file may retire rows and load none.

The file may be read from standard input (`-`), because the api image carries
`src/` and not `fixtures/`:

    docker compose exec -T api python manage.py load_access_overrides - \\
        --actor <discord user id> --confirm < fixtures/overrides/<file>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

COMMAND = "load_access_overrides"
# In every audit entry's detail: the attribution is a claim, not a sign-in.
ACTOR_NOTE = "actor named on the command line (--actor), not authenticated"
KINDS = frozenset({"access", "stress"})


def parse_file(text: str, label: str) -> list[dict]:
    """The file's rows, validated, or CommandError naming what is wrong."""
    from pipeline.overrides import ACCESS_KEYS, stress_value_problem
    from pipeline.rematch import fingerprint_problem

    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise CommandError(f"{label} is not JSON: {error}") from error
    if not isinstance(document, dict) or document.get("version") != 1:
        raise CommandError(f"{label} is not a version 1 override file")
    rows = document.get("rows")
    if rows == [] and document.get("agency_blocks"):
        # A file of block corrections only (OWNER-DECISIONS 197): the rebuild
        # reads its `agency_blocks` from the image, and there is nothing to load
        # (fixtures/overrides/README.md). Accepted so every file in the directory
        # can be passed to this command, as docs/OPERATIONS.md has it.
        return []
    if rows == [] and document.get("retire"):
        # A file that only withdraws rows (OWNER-DECISIONS 433's MoCo rows).
        return []
    if not isinstance(rows, list) or not rows:
        raise CommandError(f"{label} has no rows")

    seen: set[int] = set()
    adjustments: dict[str, tuple[int, dict]] = {}
    for index, row in enumerate(rows):
        where = f"{label} row {index}"
        if not isinstance(row, dict):
            raise CommandError(f"{where} is not an object")
        kind = row.get("kind")
        if kind not in KINDS:
            raise CommandError(f"{where}: kind must be one of {sorted(KINDS)}, not {kind!r}")
        way_id = row.get("osm_way_id")
        if not isinstance(way_id, int) or isinstance(way_id, bool) or way_id <= 0:
            raise CommandError(f"{where}: osm_way_id must be a positive integer")
        if (kind, way_id) in seen:
            raise CommandError(f"{where}: way {way_id} appears twice in the file")
        seen.add((kind, way_id))
        value = row.get("value")
        if not isinstance(value, dict) or not value:
            raise CommandError(f"{where}: value must be a non-empty object")
        if kind == "stress":
            problem = stress_value_problem(value)
            if problem:
                raise CommandError(f"{where}: {problem}")
            shared = {k: v for k, v in value.items()}
            first = adjustments.setdefault(value["adjustment_id"], (index, shared))
            if first[1] != shared:
                raise CommandError(
                    f"{where}: adjustment {value['adjustment_id']!r} is also row {first[0]}, "
                    "and the ways of one adjustment share its tier, category, visibility, "
                    "annotation status and note"
                )
        for key, tag in value.items() if kind == "access" else ():
            if key not in ACCESS_KEYS:
                raise CommandError(
                    f"{where}: writes {key!r}, which is not an access key; "
                    f"permitted keys are {sorted(ACCESS_KEYS)}"
                )
            if not isinstance(tag, str) or not tag:
                raise CommandError(f"{where}: {key} must be a non-empty string")
        for field in ("reason", "evidence"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise CommandError(f"{where}: {field} is required")
        if "fingerprint" in row:
            # Not loaded into the row: the rebuild reads it from the image's copy of
            # this file (pipeline.rematch), but a malformed one is refused here too.
            problem = fingerprint_problem(row["fingerprint"])
            if problem:
                raise CommandError(f"{where}: {problem}")
    return rows


def parse_retired(text: str, label: str) -> list[dict]:
    """The file's `retire` entries, validated (the module docstring), or CommandError."""
    document = json.loads(text)
    entries = document.get("retire", [])
    if not isinstance(entries, list):
        raise CommandError(f"{label}: retire must be a list")
    seen: set[tuple[str, int]] = set()
    for index, entry in enumerate(entries):
        where = f"{label} retire {index}"
        if not isinstance(entry, dict):
            raise CommandError(f"{where} is not an object")
        if entry.get("kind") not in KINDS:
            raise CommandError(f"{where}: kind must be one of {sorted(KINDS)}")
        way_id = entry.get("osm_way_id")
        if not isinstance(way_id, int) or isinstance(way_id, bool) or way_id <= 0:
            raise CommandError(f"{where}: osm_way_id must be a positive integer")
        if (entry["kind"], way_id) in seen:
            raise CommandError(f"{where}: way {way_id} is retired twice")
        seen.add((entry["kind"], way_id))
        if not isinstance(entry.get("value"), dict) or not entry["value"]:
            raise CommandError(f"{where}: value must be the retired row's value")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            raise CommandError(f"{where}: reason (the decision that withdraws it) is required")
    return entries


def plan_retired(entries: list[dict]) -> list[tuple[str, dict, object]]:
    """(`retire`, entry, row) for each row the entry names, or (`absent`, entry, None)."""
    from core.models import Override

    steps = []
    for entry in entries:
        found = list(
            Override.objects.filter(kind=entry["kind"], osm_way_id=entry["osm_way_id"]).order_by(
                "id"
            )
        )
        matches = [o for o in found if o.value == entry["value"]]
        if not matches:
            steps.append(("absent", entry, None))
        steps.extend(("retire", entry, o) for o in matches)
    return steps


def resolve_actor(discord_user_id: int, *, attempt: bool):
    """The instance admin the rows are attributed to, or CommandError.

    A refusal of a real account is audited when it was an attempt to write
    (`--confirm`), as the admin audits a refused POST and not a page view; a dry
    run writes nothing at all, refused or not. An id that names nobody has no
    one to attribute a row to.
    """
    from core.audit import record
    from core.models import AuditLogEntry, User

    user = User.objects.filter(discord_user_id=discord_user_id).first()
    if user is None:
        raise CommandError(f"no account has Discord id {discord_user_id}")
    if not (user.is_instance_admin and user.is_active):
        if attempt:
            record(
                user,
                COMMAND,
                "override",
                "",
                AuditLogEntry.Outcome.REFUSED,
                detail=(
                    f"{COMMAND} refused: the actor is not an active instance admin; {ACTOR_NOTE}"
                ),
            )
        raise CommandError(
            f"Discord id {discord_user_id} is not an active instance admin; approving an "
            "override changes routing for every guild"
        )
    return user


def plan(rows: list[dict], retiring: frozenset = frozenset()) -> list[tuple[str, dict, object]]:
    """(action, file row, existing row or None) per file row; refuses conflicts.

    Rows whose primary key is in `retiring` (the file withdraws them) are not
    consulted. `create` - no matching row; `approve` - a matching unapproved row exists;
    `present` - a matching approved row exists, nothing to do; `update` - a
    stress row approved with the same tier and other adjustment fields, which
    the file's replace (the tier is the decision; the fields explain it).
    """
    from core.models import Override

    steps = []
    for row in rows:
        same_way = [
            o
            for o in Override.objects.filter(
                kind=row["kind"], osm_way_id=row["osm_way_id"]
            ).order_by("id")
            if o.pk not in retiring
        ]
        match = next((o for o in same_way if o.value == row["value"]), None)
        if row["kind"] == "stress":
            approved = [o for o in same_way if o.approved]
            other_tier = [o for o in approved if o.value.get("tier") != row["value"]["tier"]]
            if other_tier:
                raise CommandError(
                    f"way {row['osm_way_id']} already has approved override "
                    f"{other_tier[0].pk} writing {other_tier[0].value}, which disagrees with "
                    f"{row['value']}; resolve it in the admin first"
                )
            if match is None and approved:
                steps.append(("update", row, approved[0]))
                continue
        conflicting = [
            o
            for o in same_way
            if o.approved
            and o.value != row["value"]
            and any(o.value.get(key) not in (None, tag) for key, tag in row["value"].items())
        ]
        if conflicting:
            raise CommandError(
                f"way {row['osm_way_id']} already has approved override "
                f"{conflicting[0].pk} writing {conflicting[0].value}, which disagrees with "
                f"{row['value']}; resolve it in the admin first"
            )
        if match is None:
            steps.append(("create", row, None))
        elif not match.approved:
            steps.append(("approve", row, match))
        else:
            steps.append(("present", row, match))
    return steps


class Command(BaseCommand):
    help = (
        "Load a reviewed, versioned file of access or stress overrides as approved Override "
        "rows, audited to the instance admin named by --actor. Dry unless --confirm."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", help="The override file, or - for standard input.")
        parser.add_argument(
            "--actor",
            type=int,
            required=True,
            help=(
                "Discord user id of the instance admin the rows are attributed to. Checked "
                "to be an active instance admin, not authenticated; the audit entries say so."
            ),
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually write. Without it this prints what would happen and writes nothing.",
        )

    def handle(self, *args, **options) -> None:
        from core.audit import record
        from core.models import AuditLogEntry, Override

        path = options["path"]
        if path == "-":
            label, text = "<stdin>", sys.stdin.read()
        else:
            label, text = path, Path(path).read_text()
        rows = parse_file(text, label)
        retired = parse_retired(text, label)
        if not rows and not retired:
            self.stdout.write(
                f"{label} has no rows to load: its agency_blocks are read by the rebuild "
                "from the image"
            )
            return
        actor = resolve_actor(options["actor"], attempt=options["confirm"])
        retire_steps = plan_retired(retired)
        retiring = frozenset(o.pk for action, _, o in retire_steps if action == "retire")
        steps = plan(rows, retiring)

        for action, row, existing in [*retire_steps, *steps]:
            target = f" (override {existing.pk})" if existing else ""
            self.stdout.write(f"{action}: way {row['osm_way_id']} {row['value']}{target}")
        if not options["confirm"]:
            self.stdout.write("dry run: nothing written; pass --confirm to write")
            return

        source = f"{COMMAND} from {label}; {ACTOR_NOTE}"
        with transaction.atomic():
            for action, entry, existing in retire_steps:
                if action != "retire":
                    continue
                pk = existing.pk
                existing.delete()
                record(
                    actor,
                    "delete",
                    "override",
                    pk,
                    AuditLogEntry.Outcome.ALLOWED,
                    detail=(
                        f"retired; way {entry['osm_way_id']} {json.dumps(entry['value'])}; "
                        f"{entry['reason']}; {source}"
                    ),
                )
            for action, row, existing in steps:
                if action == "present":
                    continue
                now = timezone.now()
                if action == "update":
                    before = existing.value
                    existing.value = row["value"]
                    existing.reason = row["reason"]
                    existing.evidence = row["evidence"]
                    existing.save(update_fields=["value", "reason", "evidence"])
                    record(
                        actor,
                        "change",
                        "override",
                        existing.pk,
                        AuditLogEntry.Outcome.ALLOWED,
                        detail=(
                            f"value, reason, evidence; way {row['osm_way_id']} "
                            f"{json.dumps(before)} -> {json.dumps(row['value'])}; the tier "
                            f"unchanged; {source}"
                        ),
                    )
                    continue
                if action == "create":
                    existing = Override.objects.create(
                        kind=row["kind"],
                        osm_way_id=row["osm_way_id"],
                        value=row["value"],
                        reason=row["reason"],
                        evidence=row["evidence"],
                        approved=True,
                        approved_at=now,
                    )
                    record(
                        actor,
                        "add",
                        "override",
                        existing.pk,
                        AuditLogEntry.Outcome.ALLOWED,
                        detail=(
                            f"kind, osm_way_id, value, reason, evidence; way "
                            f"{row['osm_way_id']} {json.dumps(row['value'])}; {source}"
                        ),
                    )
                    replaced = ""
                else:
                    # The proposal's text is kept here, since the row's own
                    # reason and evidence now say why it was approved.
                    replaced = (
                        f"; reason and evidence replaced by the file's, were: reason "
                        f"{json.dumps(existing.reason)}, evidence {json.dumps(existing.evidence)}"
                    )
                    existing.approved = True
                    existing.approved_at = now
                    existing.reason = row["reason"]
                    existing.evidence = row["evidence"]
                    existing.save(update_fields=["approved", "approved_at", "reason", "evidence"])
                record(
                    actor,
                    "approve",
                    "override",
                    existing.pk,
                    AuditLogEntry.Outcome.ALLOWED,
                    detail=f"approved; way {row['osm_way_id']}; {source}{replaced}",
                )
        written = sum(1 for action, _, _ in steps if action != "present")
        gone = sum(1 for action, _, _ in retire_steps if action == "retire")
        if retire_steps:
            self.stdout.write(f"retired {gone} rows")
        self.stdout.write(f"wrote {written} of {len(steps)} rows; the rest were already approved")
