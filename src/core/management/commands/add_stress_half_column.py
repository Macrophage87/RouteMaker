"""`manage.py add_stress_half_column` - let the live table hold half steps before a rebuild.

Half steps (OWNER-DECISIONS 441i-441l, 461a) live in the segment table's `stress_half`
column (`pipeline.schema.STRESS_HALF_COLUMN`). Every rebuild after this code creates the
table with it. A table promoted before has no such column: the road panel's editor then
offers whole steps and refuses a half step ("Half steps arrive with the next data update").
This adds the column to the live table in place, so half steps work at once, without waiting
for the weekly rebuild.

Dry by default: without `--confirm` it says what it would do and writes nothing. Idempotent:
on a table that has the column it does nothing.

    docker compose exec -T api python manage.py add_stress_half_column
    docker compose exec -T api python manage.py add_stress_half_column --confirm

It takes a brief ACCESS EXCLUSIVE lock on the live table: adding a column with a constant
default changes only the catalogue (PostgreSQL 11 and later), so the lock is held for
milliseconds once it is granted, but it waits behind any long query on the table (a tile
pre-draw). Run it when no pre-draw is running. The tile cache keys change with it (the
column is in the stress tiles' ETag letters), which is harmless: tiles are drawn afresh.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

COMMAND = "add_stress_half_column"

DDL = (
    "ALTER TABLE {schema}.segment ADD COLUMN IF NOT EXISTS stress_half boolean NOT NULL "
    "DEFAULT false CONSTRAINT segment_stress_half_tier CHECK (NOT stress_half OR stress_tier < 5)"
)


class Command(BaseCommand):
    help = "Add the half-step column to the live segment table in place. Dry unless --confirm."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually alter the table. Without it this says what it would do.",
        )

    def handle(self, *args, **options) -> None:
        from core import segment_info, stress_edits
        from pipeline.schema import STRESS_HALF_COLUMN

        schema = stress_edits.live_schema()
        if stress_edits.live_oid(schema) is None:
            raise CommandError(f"there is no live table ({schema}.segment) yet")
        segment_info.forget_columns()
        have = segment_info.live_columns(schema)
        if STRESS_HALF_COLUMN in have:
            self.stdout.write(f"{schema}.segment already has {STRESS_HALF_COLUMN}: nothing to do")
            return
        self.stdout.write(f"{schema}.segment has no {STRESS_HALF_COLUMN}; would run:")
        self.stdout.write("  " + DDL.format(schema=schema))
        if not options["confirm"]:
            self.stdout.write("dry run: nothing written; pass --confirm to write")
            return
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '10s'")
            cursor.execute(DDL.format(schema=schema))
        segment_info.forget_columns()
        self.stdout.write(f"added {STRESS_HALF_COLUMN} to {schema}.segment")
