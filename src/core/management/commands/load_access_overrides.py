"""`manage.py load_access_overrides` - load a reviewed file of access overrides.

An access correction reaches the graph only as an approved `Override` row
(PLAN's audited path; `pipeline.overrides.load_approved` reads nothing else).
Some corrections are decided outside the admin - the owner answering a question
about a bridge approach - and typing them into the admin one way at a time
loses the decision's wording and date. So they are checked in as a versioned
file under `fixtures/overrides/`, reviewed like any other change, and loaded by
this command, which writes what the admin path writes: the row, and an
`AuditLogEntry` for adding it and for approving it, attributed to the instance
admin who ran the command.

Dry by default, like `rollback_rebuild`: without `--confirm` it prints what it
would do and writes nothing. Idempotent: a row already present and approved
with the same kind, way and value is left alone and audited as nothing, so a
second run is a no-op; one present but unapproved is approved. It refuses the
whole file, before writing anything, if any row is malformed, writes a key an
access override may not write, or disagrees with an approved row already on the
same way - two approved rows answering one way differently would be applied in
id order, which is not a decision anybody made.

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


def parse_file(text: str, label: str) -> list[dict]:
    """The file's rows, validated, or CommandError naming what is wrong."""
    from pipeline.overrides import ACCESS_KEYS

    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise CommandError(f"{label} is not JSON: {error}") from error
    if not isinstance(document, dict) or document.get("version") != 1:
        raise CommandError(f"{label} is not a version 1 override file")
    rows = document.get("rows")
    if not isinstance(rows, list) or not rows:
        raise CommandError(f"{label} has no rows")

    seen: set[int] = set()
    for index, row in enumerate(rows):
        where = f"{label} row {index}"
        if not isinstance(row, dict):
            raise CommandError(f"{where} is not an object")
        if row.get("kind") != "access":
            raise CommandError(f"{where}: kind must be 'access', not {row.get('kind')!r}")
        way_id = row.get("osm_way_id")
        if not isinstance(way_id, int) or isinstance(way_id, bool) or way_id <= 0:
            raise CommandError(f"{where}: osm_way_id must be a positive integer")
        if way_id in seen:
            raise CommandError(f"{where}: way {way_id} appears twice in the file")
        seen.add(way_id)
        value = row.get("value")
        if not isinstance(value, dict) or not value:
            raise CommandError(f"{where}: value must be a non-empty object of tags")
        for key, tag in value.items():
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
    return rows


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
                detail=f"{COMMAND} refused: the actor is not an active instance admin",
            )
        raise CommandError(
            f"Discord id {discord_user_id} is not an active instance admin; approving an "
            "override changes routing for every guild"
        )
    return user


def plan(rows: list[dict]) -> list[tuple[str, dict, object]]:
    """(action, file row, existing row or None) per file row; refuses conflicts.

    `create` - no matching row; `approve` - a matching unapproved row exists;
    `present` - a matching approved row exists, nothing to do.
    """
    from core.models import Override

    steps = []
    for row in rows:
        same_way = list(
            Override.objects.filter(kind="access", osm_way_id=row["osm_way_id"]).order_by("id")
        )
        match = next((o for o in same_way if o.value == row["value"]), None)
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
        "Load a reviewed, versioned file of bicycle access overrides as approved Override "
        "rows, audited to the instance admin named by --actor. Dry unless --confirm."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", help="The override file, or - for standard input.")
        parser.add_argument(
            "--actor",
            type=int,
            required=True,
            help="Discord user id of the instance admin the rows are attributed to.",
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
        actor = resolve_actor(options["actor"], attempt=options["confirm"])
        steps = plan(rows)

        for action, row, existing in steps:
            target = f" (override {existing.pk})" if existing else ""
            self.stdout.write(f"{action}: way {row['osm_way_id']} {row['value']}{target}")
        if not options["confirm"]:
            self.stdout.write("dry run: nothing written; pass --confirm to write")
            return

        source = f"{COMMAND} from {label}"
        with transaction.atomic():
            for action, row, existing in steps:
                if action == "present":
                    continue
                now = timezone.now()
                if action == "create":
                    existing = Override.objects.create(
                        kind="access",
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
                else:
                    existing.approved = True
                    existing.approved_at = now
                    existing.save(update_fields=["approved", "approved_at"])
                record(
                    actor,
                    "approve",
                    "override",
                    existing.pk,
                    AuditLogEntry.Outcome.ALLOWED,
                    detail=f"approved; way {row['osm_way_id']}; {source}",
                )
        written = sum(1 for action, _, _ in steps if action != "present")
        self.stdout.write(f"wrote {written} of {len(steps)} rows; the rest were already approved")
