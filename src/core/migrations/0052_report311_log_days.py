# The 311 log keeps the day, not the time of day (core.report_log; Stephen, 2026-10-29: the log
# keeps the date, not the time of day). Each kept entry's `at`, `changed` and `reported` are cut
# to their day in Washington, and an id that began with the time it was made to its random part,
# as core.report_log.dated and the page (lib/report311Log.ts parseEntry) do with every copy; the
# row's `updated_at` becomes that day too. The spot is kept: crews need it to find the pothole.
#
# The column keeps its name, so the api of the release before still reads and writes it between
# migrate and the api's recreation, or after a rollback of the images: Postgres casts the time it
# writes to the day. Going back makes the column a time again (midnight of each day) and leaves the
# entries as days: the times are gone for good (docs/OPERATIONS.md: take a backup first). The page
# of the release before reads a bare day as midnight UTC, the evening before in Washington, so the
# API serves each day as noon in Washington (core.report_log.served), which it shows as the right
# day; this release's page reads only the day.

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.db import migrations, models

DAY_ZONE = ZoneInfo("America/New_York")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMED_ID = re.compile(r"^[0-9a-z]{8}-([0-9a-z]{1,8})$")


def _day(value):
    if not isinstance(value, str) or DAY.match(value):
        return value
    try:
        found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    found = found if found.tzinfo is not None else found.replace(tzinfo=UTC)
    return found.astimezone(DAY_ZONE).date().isoformat()


def _dated(entry):
    if not isinstance(entry, dict):
        return entry
    out = dict(entry)
    for key in ("at", "changed", "reported"):
        if key in out:
            out[key] = _day(out[key])
    timed = TIMED_ID.match(out.get("id") or "") if isinstance(out.get("id"), str) else None
    if timed:
        out["id"] = timed.group(1)
    return out


def to_days(apps, schema_editor):
    Report311Log = apps.get_model("core", "Report311Log")
    for row in Report311Log.objects.iterator():
        entries = [_dated(e) for e in row.entries or []]
        if entries != row.entries:
            Report311Log.objects.filter(pk=row.pk).update(entries=entries)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0051_connector_draft_grant"),
    ]

    operations = [
        migrations.RunPython(to_days, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    [
                        "ALTER TABLE report311_log ALTER COLUMN updated_at TYPE date"
                        " USING (updated_at AT TIME ZONE 'America/New_York')::date,"
                        " ALTER COLUMN updated_at DROP NOT NULL"
                    ],
                    [
                        "UPDATE report311_log SET updated_at = CURRENT_DATE"
                        " WHERE updated_at IS NULL",
                        "ALTER TABLE report311_log ALTER COLUMN updated_at"
                        " TYPE timestamp with time zone"
                        " USING (updated_at::timestamp AT TIME ZONE 'America/New_York'),"
                        " ALTER COLUMN updated_at SET NOT NULL",
                    ],
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="report311log",
                    name="updated_at",
                    field=models.DateField(blank=True, null=True),
                ),
            ],
        ),
    ]
