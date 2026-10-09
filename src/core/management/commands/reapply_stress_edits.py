"""`manage.py reapply_stress_edits` - re-apply the road panel's edits to the live table.

An instance admin's "Change LTS" updates the live segment table in place
(`core.stress_edits`). A promotion or a rollback re-applies the edits made after the
promoted table read its overrides, by itself, and logs (never raises) if it could not.
This is the operator's way to do it by hand, or to check what it would do: after a
promotion whose run row says the re-apply failed, after restoring a database, or to see
which edits a table has not yet got.

Dry by default, like `rollback_rebuild`: without `--confirm` it lists the edits it would
replay and writes nothing. It is idempotent: a row already in an edit's state is left alone.

    docker compose exec -T api python manage.py reapply_stress_edits --since 2026-10-09T00:00:00Z
    docker compose exec -T api python manage.py reapply_stress_edits --since all --confirm

`--since` is an ISO 8601 time (edits made after it) or `all`; without it, the time the live
table recorded when it was promoted (`LiveEditGeneration.overrides_read_at`), or every
edit where it recorded none.
"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

COMMAND = "reapply_stress_edits"


def parse_since(text: str | None):
    """(since, label): a time, or None for every edit; or None, None for the table's own."""
    if text is None:
        return "table", "since the live table read its overrides"
    if text == "all":
        return None, "every edit"
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise CommandError(f"--since is an ISO 8601 time or 'all', not {text!r}") from error
    if when.tzinfo is None:
        when = timezone.make_aware(when)
    return when, f"edits after {when.isoformat()}"


class Command(BaseCommand):
    help = (
        "Re-apply the road panel's stress edits to the live segment table (idempotent). "
        "Dry unless --confirm."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--since", help="An ISO 8601 time, or 'all'.")
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually write. Without it this lists the edits and writes nothing.",
        )

    def handle(self, *args, **options) -> None:
        from core import stress_edits
        from core.models import LiveEditGeneration, StressEdit

        since, label = parse_since(options["since"])
        if since == "table":
            oid = stress_edits.live_oid(stress_edits.live_schema())
            known = LiveEditGeneration.objects.filter(table_oid=oid).first() if oid else None
            since = known.overrides_read_at if known else None
        edits = (
            StressEdit.objects.all() if since is None else StressEdit.objects.filter(at__gt=since)
        )
        edits = edits.order_by("id")
        self.stdout.write(f"{edits.count()} edits ({label})")
        for edit in edits:
            self.stdout.write(
                f"  {edit.pk}: {edit.action} of way(s) {edit.osm_way_ids} at {edit.at.isoformat()}"
            )
        if not options["confirm"]:
            self.stdout.write("dry run: nothing written; pass --confirm to write")
            return
        changed = stress_edits.reapply_since(since)
        self.stdout.write(f"re-applied: {changed} rows changed")
