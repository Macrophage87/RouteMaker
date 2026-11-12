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

An instance admin's change in the road panel (`core.stress_edits`) replaces the way's
approved stress row by *superseding* it - marking it, not unapproving it, because this
command re-approves an unapproved row that matches a file. So a row of a file that matches
a superseded row is reported as superseded and left alone (reloading an old file never
undoes an edit), and a stress row that disagrees with a live panel row is refused, naming
the edit.

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

Files load in any order. Each retirement is kept in the audit log with the date the
retiring file was `decided` - a deleted row's entry, or, where the row was not loaded
yet, an entry of its own - and a row of a file decided before that date, with the
retired kind, way and exact value, is reported as `retired` and left alone. So an older
file loaded after the newer one that withdraws some of its rows (the 2026-11-01 Maryland
review after the 2026-11-04 Baltimore City file) loads the rest, never undoes the newer
decision, and a second run is still a no-op.

The file may be read from standard input (`-`), because the api image carries
`src/` and not `fixtures/`:

    docker compose exec -T api python manage.py load_access_overrides - \\
        --actor <discord user id> --confirm < fixtures/overrides/<file>.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

COMMAND = "load_access_overrides"
# In every audit entry's detail: the attribution is a claim, not a sign-in.
ACTOR_NOTE = "actor named on the command line (--actor), not authenticated"
KINDS = frozenset({"access", "stress"})
# A retirement's audit entry starts with this, then `<way> <value as JSON>; kind <kind>;
# decided <YYYY-MM-DD>;` (`retirement_detail`), so a later load can find it (`retirements`).
RETIRED_PREFIX = "retired; way "
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_RETIRED_TAIL = re.compile(r"; kind (\w+); decided (\d{4}-\d{2}-\d{2});")


def decided_of(text: str) -> str | None:
    """The file's `decided` date (YYYY-MM-DD), or None where it has none."""
    decided = json.loads(text).get("decided")
    return decided if isinstance(decided, str) and _DATE.fullmatch(decided) else None


def value_key(kind: str, way_id: int, value: dict) -> tuple[str, int, str]:
    return (kind, int(way_id), json.dumps(value, sort_keys=True))


def retirement_detail(entry: dict, decided: str | None) -> str:
    """The start of a retirement's audit detail: the row withdrawn, and when (`retirements`)."""
    detail = f"{RETIRED_PREFIX}{entry['osm_way_id']} {json.dumps(entry['value'])}"
    if decided is not None:
        detail += f"; kind {entry['kind']}; decided {decided}"
    return detail


def retirements() -> dict[tuple[str, int, str], str]:
    """{(kind, way, value): the latest date a file decided to retire it}, from the audit log."""
    from core.models import AuditLogEntry

    found: dict[tuple[str, int, str], str] = {}
    decoder = json.JSONDecoder()
    for detail in AuditLogEntry.objects.filter(
        model="override", action__in=("delete", "retire"), detail__startswith=RETIRED_PREFIX
    ).values_list("detail", flat=True):
        way_text, _, rest = detail[len(RETIRED_PREFIX) :].partition(" ")
        try:
            value, end = decoder.raw_decode(rest)
        except ValueError:
            continue
        tail = _RETIRED_TAIL.match(rest, end)
        if not way_text.isdigit() or not isinstance(value, dict) or tail is None:
            # An entry written before retirements were dated: it decides nothing here.
            continue
        key = value_key(tail.group(1), int(way_text), value)
        found[key] = max(found.get(key, ""), tail.group(2))
    return found


def parse_file(text: str, label: str) -> list[dict]:
    """The file's rows, validated, or CommandError naming what is wrong."""
    from pipeline.overrides import ACCESS_KEYS, stress_value_problem
    from pipeline.rematch import fingerprint_problem
    from routemaker.agency_roads import placeholder_problem

    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise CommandError(f"{label} is not JSON: {error}") from error
    if not isinstance(document, dict) or document.get("version") != 1:
        raise CommandError(f"{label} is not a version 1 override file")
    from pipeline.overrides import file_rows

    groups = document.get("groups")
    if groups is not None:
        problem = groups_problem(groups)
        if problem:
            raise CommandError(f"{label}: {problem}")
    rows = document.get("rows")
    if groups:
        rows = file_rows(document)
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
            # A row suggested by the rebuild's newer-OSM list (`pipeline.dc_osm_newer`)
            # and copied in without the owner's words is refused, not loaded.
            problem = placeholder_problem(field, row[field])
            if problem:
                raise CommandError(f"{where}: {problem}")
        if "facts" in row:
            from pipeline.rated_facts import facts_problem

            problem = facts_problem(row["facts"])
            if problem:
                raise CommandError(f"{where}: {problem}")
        if "fingerprint" in row:
            # Not loaded into the row: the rebuild reads it from the image's copy of
            # this file (pipeline.rematch), but a malformed one is refused here too.
            problem = fingerprint_problem(row["fingerprint"])
            if problem:
                raise CommandError(f"{where}: {problem}")
    return rows


def groups_problem(groups: object) -> str | None:
    """Why a file's `groups` (the compact form, `pipeline.overrides.file_rows`) is malformed."""
    if not isinstance(groups, list):
        return "groups must be a list"
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            return f"group {index} is not an object"
        extra = set(group) - {
            "kind",
            "value",
            "reason",
            "evidence",
            "ways",
            "fingerprints",
            "facts",
        }
        if extra:
            return f"group {index} has no {sorted(extra)}"
        if "facts" in group:
            # The facts the group was rated from (`pipeline.rated_facts`): not loaded, read
            # by the rebuild from the image's copy of this file, but checked here.
            from pipeline.rated_facts import facts_problem

            problem = facts_problem(group["facts"])
            if problem:
                return f"group {index}: {problem}"
        ways = group.get("ways")
        if not isinstance(ways, list) or not ways:
            return f"group {index}: ways must be a non-empty list of way ids"
        prints = group.get("fingerprints", {})
        if not isinstance(prints, dict) or not set(prints) <= {str(w) for w in ways}:
            return f"group {index}: fingerprints map its own ways' ids (as text) to fingerprints"
    return None


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


def plan(
    rows: list[dict],
    retiring: frozenset = frozenset(),
    retired: dict | None = None,
    decided: str | None = None,
) -> list[tuple[str, dict, object]]:
    """(action, file row, existing row or None) per file row; refuses conflicts.

    Rows whose primary key is in `retiring` (the file withdraws them) are not
    consulted. `retired` - a file decided after this one (`decided`) retired the row's
    kind, way and exact value (`retirements`): left alone, with that date in place of the
    existing row; `create` - no matching row; `approve` - a matching unapproved row exists;
    `present` - a matching approved row exists, nothing to do; `update` - a
    stress row approved with the same tier and other adjustment fields, which
    the file's replace (the tier is the decision; the fields explain it);
    `superseded` - a matching row that a later road-panel edit replaced
    (`core.stress_edits`): reported and left alone, so reloading an old file can never
    undo an edit. A stress row that disagrees with a live road-panel row is refused,
    naming the edit, as two disagreeing approved rows are.
    """
    from core.models import Override

    steps = []
    retired = retired or {}
    for row in rows:
        when = retired.get(value_key(row["kind"], row["osm_way_id"], row["value"]))
        if decided is not None and when is not None and when > decided:
            steps.append(("retired", row, when))
            continue
        every = [
            o
            for o in Override.objects.filter(
                kind=row["kind"], osm_way_id=row["osm_way_id"]
            ).order_by("id")
            if o.pk not in retiring
        ]
        # A superseded row is inert and is never consulted as a live one.
        same_way = [o for o in every if o.superseded_by_id is None]
        replaced = [o for o in every if o.superseded_by_id is not None]
        match = next((o for o in same_way if o.value == row["value"]), None)
        if row["kind"] == "stress" and match is None:
            gone = next((o for o in replaced if o.value == row["value"]), None)
            if gone is not None:
                steps.append(("superseded", row, gone))
                continue
            panel = next((o for o in same_way if o.approved and o.source == "panel"), None)
            if panel is not None:
                raise CommandError(
                    f"way {row['osm_way_id']} was changed in the road panel (override "
                    f"{panel.pk}, {panel.approved_at:%Y-%m-%d}, writing {panel.value}), which "
                    f"disagrees with {row['value']}; make the change in the road panel, or "
                    "resolve it in the admin first"
                )
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
        decided = decided_of(text)
        if not rows and not retired:
            self.stdout.write(
                f"{label} has no rows to load: its agency_blocks are read by the rebuild "
                "from the image"
            )
            return
        actor = resolve_actor(options["actor"], attempt=options["confirm"])
        retire_steps = plan_retired(retired)
        retiring = frozenset(o.pk for action, _, o in retire_steps if action == "retire")
        known = retirements()
        steps = plan(rows, retiring, known, decided)

        for action, row, existing in [*retire_steps, *steps]:
            if action == "retired":
                self.stdout.write(
                    f"retired: way {row['osm_way_id']} {row['value']} (retired by a later "
                    f"file, decided {existing}; left alone)"
                )
                continue
            target = f" (override {existing.pk})" if existing else ""
            if action == "superseded":
                successor = existing.superseded_by
                when = existing.superseded_at or (successor.approved_at if successor else None)
                target = (
                    f" (override {existing.pk}, superseded by panel edit "
                    f"{getattr(successor, 'pk', '?')}"
                    + (f" on {when:%Y-%m-%d}" if when else "")
                    + "; left alone)"
                )
            self.stdout.write(f"{action}: way {row['osm_way_id']} {row['value']}{target}")
        if not options["confirm"]:
            self.stdout.write("dry run: nothing written; pass --confirm to write")
            return

        source = f"{COMMAND} from {label}; {ACTOR_NOTE}"
        with transaction.atomic():
            for action, entry, existing in retire_steps:
                if action != "retire":
                    key = value_key(entry["kind"], entry["osm_way_id"], entry["value"])
                    if decided is not None and known.get(key, "") < decided:
                        # Not loaded yet: kept on record, so the older file that carries the
                        # row leaves it alone whenever it is loaded (`retirements`).
                        record(
                            actor,
                            "retire",
                            "override",
                            "",
                            AuditLogEntry.Outcome.ALLOWED,
                            detail=(
                                f"{retirement_detail(entry, decided)}; not loaded, so an older "
                                f"file's row is left alone; {entry['reason']}; {source}"
                            ),
                        )
                        known[key] = decided
                    continue
                pk = existing.pk
                existing.delete()
                record(
                    actor,
                    "delete",
                    "override",
                    pk,
                    AuditLogEntry.Outcome.ALLOWED,
                    detail=f"{retirement_detail(entry, decided)}; {entry['reason']}; {source}",
                )
            for action, row, existing in steps:
                if action in ("present", "superseded", "retired"):
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
        written = sum(
            1 for action, _, _ in steps if action not in ("present", "superseded", "retired")
        )
        gone = sum(1 for action, _, _ in retire_steps if action == "retire")
        if retire_steps:
            self.stdout.write(f"retired {gone} rows")
        self.stdout.write(f"wrote {written} of {len(steps)} rows; the rest were already approved")
