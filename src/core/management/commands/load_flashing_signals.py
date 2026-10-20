"""`manage.py load_flashing_signals` - load a file of flashing beacons the map has as signals.

Each row becomes an active `FlashingSignal` (`core.flashing_signals`): the junction model
prices a signalised junction within reach of it with no signal, from the next plan, with no
rebuild. Two kinds of file, both `{"version": 1, "source": ..., "rows": [{"id", "name",
"lon", "lat", "evidence"}]}`:

- `"source": "owner"`: the owner's own decisions, checked in under `fixtures/flashing-signals/`
  and reviewed like any other change. A load adds and updates rows; it never withdraws one.
- `"source": "mdot-sha"`: MDOT SHA's junction beacons, written by
  `scripts/install_reference_data.py --md-signals` as `<reference>/flashing-signals.json`
  (`pipeline.agency_signals.mdot_sha_beacons`). The file is the whole list, so a row of that
  source the file no longer has is withdrawn (the agency took the beacon out or made it a
  signal). Owner rows are never touched by it: community input outranks agency data.

A row an instance admin withdrew stays withdrawn whatever a later load says (a person
decided it), and the load says so. A row a load withdrew because the list no longer had it
is restored when a later list has it again. Attributed to the instance admin named by `--actor`, as
`load_access_overrides` is, and audited the same way: the id is checked to be an active
instance admin, not authenticated, and every entry says so. Dry unless `--confirm`.

The api image carries `src/` and neither `fixtures/` nor the reference files, so the file goes
in on standard input:

    docker compose exec -T api python manage.py load_flashing_signals - \\
        --actor <discord user id> < <DATA_ROOT>/reference/flashing-signals.json
    # read what it would do, then the same with --confirm
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

COMMAND = "load_flashing_signals"
ACTOR_NOTE = "actor named on the command line (--actor), not authenticated"
SOURCES = ("owner", "mdot-sha")
# A location moved by less than this is the same point (degrees, ~1 m).
SAME_POINT_DEG = 1e-5


def parse_file(text: str, label: str) -> tuple[str, list[dict]]:
    """The file's source and rows, validated, or CommandError naming what is wrong."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise CommandError(f"{label} is not JSON: {error}") from error
    if not isinstance(document, dict) or document.get("version") != 1:
        raise CommandError(f"{label} is not a version 1 flashing-signals file")
    source = document.get("source")
    if source not in SOURCES:
        raise CommandError(f"{label}: source must be one of {list(SOURCES)}, not {source!r}")
    rows = document.get("rows")
    if not isinstance(rows, list):
        raise CommandError(f"{label} has no rows list")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"{label} row {index}"
        if not isinstance(row, dict):
            raise CommandError(f"{where} is not an object")
        key = row.get("id")
        if not isinstance(key, str) or not key.strip() or len(key) > 80:
            raise CommandError(f"{where}: id must be a string of 1 to 80 characters")
        if key in seen:
            raise CommandError(f"{where}: id {key!r} appears twice in the file")
        seen.add(key)
        lon, lat = row.get("lon"), row.get("lat")
        for name, value, limit in (("lon", lon, 180), ("lat", lat, 90)):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or abs(value) > limit
            ):
                raise CommandError(f"{where}: {name} must be a number within +-{limit}")
        name = row.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise CommandError(f"{where}: name must be a string of 1 to 200 characters")
        if not isinstance(row.get("evidence", ""), str):
            raise CommandError(f"{where}: evidence must be a string")
    if source == "owner" and not rows:
        raise CommandError(f"{label} has no rows")
    return source, rows


def resolve_actor(discord_user_id: int, *, attempt: bool):
    """The instance admin the rows are attributed to, or CommandError (a refusal of a real
    account audited when it was an attempt to write, as `load_access_overrides` does)."""
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
                "flashingsignal",
                "",
                AuditLogEntry.Outcome.REFUSED,
                detail=(
                    f"{COMMAND} refused: the actor is not an active instance admin; {ACTOR_NOTE}"
                ),
            )
        raise CommandError(
            f"Discord id {discord_user_id} is not an active instance admin; a flashing beacon "
            "changes routing for every guild"
        )
    return user


def _same(existing, row: dict) -> bool:
    return (
        existing.name == row["name"]
        and existing.evidence == row.get("evidence", "")
        and abs(existing.location.x - row["lon"]) < SAME_POINT_DEG
        and abs(existing.location.y - row["lat"]) < SAME_POINT_DEG
    )


def plan(source: str, rows: list[dict]) -> list[tuple[str, str, dict | None, object]]:
    """(action, id, row, existing) for each row of the file, and for each active row of an
    agency source the file no longer has."""
    from core.models import FlashingSignal

    existing = {r.source_id: r for r in FlashingSignal.objects.filter(source=source)}
    steps = []
    for row in rows:
        found = existing.get(row["id"])
        if found is None:
            steps.append(("create", row["id"], row, None))
        elif not found.active and found.withdrawn_by == "admin":
            steps.append(("withdrawn", row["id"], row, found))
        elif not found.active:
            steps.append(("restore", row["id"], row, found))
        elif _same(found, row):
            steps.append(("present", row["id"], row, found))
        else:
            steps.append(("update", row["id"], row, found))
    if source != "owner":
        listed = {row["id"] for row in rows}
        for key, found in sorted(existing.items()):
            if key not in listed and found.active:
                steps.append(("retire", key, None, found))
    return steps


class Command(BaseCommand):
    help = (
        "Load a file of flashing beacons the map has as traffic signals (the owner's, or MDOT "
        "SHA's as the installer writes it), audited to the instance admin named by --actor. "
        "Dry unless --confirm."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", help="The file, or - for standard input.")
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
        from django.contrib.gis.geos import Point

        from core.audit import record
        from core.models import AuditLogEntry, FlashingSignal

        path = options["path"]
        if path == "-":
            label, text = "<stdin>", sys.stdin.read()
        else:
            label, text = path, Path(path).read_text()
        source, rows = parse_file(text, label)
        actor = resolve_actor(options["actor"], attempt=options["confirm"])
        steps = plan(source, rows)
        counts: dict[str, int] = {}
        for action, key, row, _existing in steps:
            counts[action] = counts.get(action, 0) + 1
            if action != "present":
                name = row["name"] if row else _existing.name
                note = " (an admin withdrew it; left alone)" if action == "withdrawn" else ""
                self.stdout.write(f"{action}: {key} {name}{note}")
        self.stdout.write(
            f"{label}: {source}, " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items()))
            if counts
            else f"{label}: {source}, nothing to do"
        )
        if not options["confirm"]:
            self.stdout.write("dry run: nothing written; pass --confirm to write")
            return

        said = f"{COMMAND} from {label}; {ACTOR_NOTE}"
        with transaction.atomic():
            for action, key, row, existing in steps:
                if action in ("present", "withdrawn"):
                    continue
                if action == "retire":
                    existing.active = False
                    existing.withdrawn_at = timezone.now()
                    existing.withdrawn_by = "list"
                    existing.save(
                        update_fields=["active", "withdrawn_at", "withdrawn_by", "updated_at"]
                    )
                    record(
                        actor,
                        "withdraw",
                        "flashingsignal",
                        existing.pk,
                        AuditLogEntry.Outcome.ALLOWED,
                        detail=f"{key}: no longer in the {source} list; {said}",
                    )
                    continue
                point = Point(float(row["lon"]), float(row["lat"]), srid=4326)
                if action == "create":
                    made = FlashingSignal.objects.create(
                        source=source,
                        source_id=key,
                        name=row["name"],
                        location=point,
                        evidence=row.get("evidence", ""),
                    )
                    record(
                        actor,
                        "add",
                        "flashingsignal",
                        made.pk,
                        AuditLogEntry.Outcome.ALLOWED,
                        detail=f"{key}: {row['name']}; {said}",
                    )
                else:
                    existing.name = row["name"]
                    existing.location = point
                    existing.evidence = row.get("evidence", "")
                    fields = ["name", "location", "evidence", "updated_at"]
                    if action == "restore":
                        existing.active, existing.withdrawn_at, existing.withdrawn_by = (
                            True,
                            None,
                            "",
                        )
                        fields += ["active", "withdrawn_at", "withdrawn_by"]
                    existing.save(update_fields=fields)
                    record(
                        actor,
                        "restore" if action == "restore" else "change",
                        "flashingsignal",
                        existing.pk,
                        AuditLogEntry.Outcome.ALLOWED,
                        detail=f"{key}: {row['name']}; {said}",
                    )
        self.stdout.write("written")
