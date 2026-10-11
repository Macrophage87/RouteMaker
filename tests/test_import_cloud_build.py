"""`manage.py import_cloud_build`: a build made on the cloud box, swapped in here.

The swap is the real one (`pipeline.promotion.perform_swap`) against real schemas and
a real tiles directory: what the command adds is the pre-flight, and what has to hold
afterwards is that the deployment looks exactly as after a rebuild run on this host,
down to `rollback_rebuild` putting the previous build back.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from config.procrastinate import app

pytestmark = pytest.mark.django_db(transaction=True)

OLD = "20261006T080000Z"
NEW = "20261011T093012Z"
READ_AT = "20261004T070000Z"


@pytest.fixture(autouse=True)
def no_jobs_left_over(django_db_setup, django_db_blocker):
    """Procrastinate's tables are unmanaged, so pytest-django's flush leaves a job
    another file left behind; the in-flight refusal would read it as this test's."""

    def empty() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "TRUNCATE procrastinate_periodic_defers, procrastinate_events, "
                "procrastinate_jobs RESTART IDENTITY CASCADE"
            )

    with django_db_blocker.unblock():
        empty()
    yield
    with django_db_blocker.unblock():
        empty()


def insert_segment(schema: str, way_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""INSERT INTO {schema}.segment
                (osm_way_id, ordinal, geometry, stress_tier, stress_rule)
                VALUES (%s, 0, ST_GeomFromText('LINESTRING(-77 38.9, -77.01 38.91)', 4326),
                        2, 'test')""",
            [way_id],
        )


def count(schema: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {schema}.segment")
        return cursor.fetchone()[0]


@pytest.fixture
def deployment(segment_schemas, tmp_path, settings):
    """A host serving OLD on every graph, with NEW's tiles installed beside it and
    NEW's segments restored as the staging schema: the state import-result.sh
    leaves before it runs the command."""
    from core.models import ValhallaUpstream
    from pipeline import tiles
    from pipeline.variants import Variant

    settings.TILES_DIR = tmp_path
    for variant in Variant:
        for build in (OLD, NEW):
            (tmp_path / variant.value / build).mkdir(parents=True)
            (tmp_path / variant.value / build / "tiles.tar").write_bytes(b"tiles " + build.encode())
        tiles.promote(tmp_path, variant, OLD)
        ValhallaUpstream.objects.create(
            variant=variant.value, url=settings.VALHALLA_UPSTREAMS[variant.value], build_id=OLD
        )
    live, staging = segment_schemas
    insert_segment(live, 1)
    for way in (1, 2, 3):
        insert_segment(staging, way)
    return tmp_path


def run(*args: str) -> str:
    out = StringIO()
    call_command("import_cloud_build", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def serving(tiles_dir) -> set[str | None]:
    from pipeline import tiles
    from pipeline.variants import Variant

    return {tiles.promoted_build_id(tiles_dir, variant) for variant in Variant}


def test_the_dry_run_checks_and_changes_nothing(deployment) -> None:
    out = run(NEW, "--overrides-read-at", READ_AT)

    assert "dry run" in out
    assert f"standard: {OLD} -> {NEW}" in out
    assert serving(deployment) == {OLD}
    assert count("staging") == 3 and count("live") == 1


def test_a_confirmed_import_is_the_swap_a_rebuild_makes(deployment) -> None:
    from core.models import AuditLogEntry, DriftReport, ValhallaUpstream
    from pipeline import tiles
    from pipeline.variants import Variant

    out = run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    assert serving(deployment) == {NEW}
    assert {tiles.promoted_build_id(deployment, v, tiles.PREVIOUS) for v in Variant} == {OLD}
    assert count("live") == 3, "the box's table is the live one"
    assert count("live_old") == 1, "and this host's is retired, for a rollback"
    rows = ValhallaUpstream.objects.all()
    assert {(row.build_id, row.previous_build_id) for row in rows} == {(NEW, OLD)}
    audit = AuditLogEntry.objects.get(action="import_cloud_build")
    assert NEW in audit.detail and "2026-10-04T07:00:00+00:00" in audit.detail
    assert DriftReport.objects.filter(build_id=NEW).exists(), "RECONCILE ran, as in a rebuild"
    assert "docker compose restart" in out and "predraw_stress_tiles" in out


def test_rollback_rebuild_undoes_an_import(deployment) -> None:
    run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    call_command("rollback_rebuild", "--confirm", stdout=StringIO())

    assert serving(deployment) == {OLD}
    assert count("live") == 1


def test_a_swap_that_fails_is_undone_and_says_so(deployment, monkeypatch) -> None:
    def fails(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("pipeline.promotion.swap_schemas", fails)

    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    assert "undone" in str(refused.value) and "disk full" in str(refused.value)
    assert serving(deployment) == {OLD}
    assert count("staging") == 3, "the import can be tried again"


@pytest.mark.parametrize("confirm", [(), ("--confirm",)], ids=["dry", "confirm"])
@pytest.mark.parametrize("status", ["todo", "doing"])
def test_it_is_refused_while_a_rebuild_is_in_flight(deployment, status, confirm) -> None:
    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = %s::procrastinate_job_status WHERE id = %s",
            [status, job_id],
        )

    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", READ_AT, *confirm)

    assert f"job {job_id}" in str(refused.value)
    assert serving(deployment) == {OLD}


def test_a_graph_missing_from_the_import_refuses_the_whole_of_it(deployment) -> None:
    (deployment / "weekend" / NEW / "tiles.tar").unlink()

    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    assert f"weekend/{NEW}/tiles.tar" in str(refused.value)
    assert serving(deployment) == {OLD}


def test_a_build_already_served_is_refused(deployment) -> None:
    with pytest.raises(CommandError) as refused:
        run(OLD, "--overrides-read-at", READ_AT)

    assert f"already serving {OLD}" in str(refused.value)


def test_no_staging_schema_is_refused(deployment) -> None:
    from pipeline.schema import drop_segment_schema

    drop_segment_schema("staging")

    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    assert "no staging.segment table" in str(refused.value)
    assert serving(deployment) == {OLD}


def test_an_empty_staging_table_is_refused(deployment) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM staging.segment")

    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    assert "staging.segment is empty" in str(refused.value)


@pytest.mark.parametrize(
    "build_id", ["latest", "20261011T093012Z; drop schema live", "../20261011T093012Z"]
)
def test_a_build_id_no_rebuild_writes_is_refused(deployment, build_id) -> None:
    with pytest.raises(CommandError) as refused:
        run(build_id, "--overrides-read-at", READ_AT)

    assert "not a build id" in str(refused.value)


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("2026-10-04T07:00:00", "no time zone"),
        ("2999-01-01T00:00:00Z", "in the future"),
        ("29990101T000000Z", "in the future"),
        ("yesterday", "not a time"),
    ],
)
def test_a_read_at_that_is_not_a_past_utc_instant_is_refused(deployment, value, reason) -> None:
    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", value)

    assert reason in str(refused.value)


@pytest.mark.parametrize(
    "value", ["20261004T070000Z", "2026-10-04T07:00:00Z", "2026-10-04T03:00:00-04:00"]
)
def test_the_backups_name_and_iso_times_read_the_same(value) -> None:
    from datetime import UTC, datetime

    from core.management.commands.import_cloud_build import parse_read_at

    assert parse_read_at(value) == datetime(2026, 10, 4, 7, 0, tzinfo=UTC)


def test_where_the_swap_re_applies_panel_edits_it_is_given_the_backups_time(
    deployment, monkeypatch
) -> None:
    """From v0.4.0 (the stress editor) `perform_swap` re-applies the road panel's edits
    made after `overrides_read_at`; the box's copy of the database is the backup, so
    that is the backup's time. Before it there is no such parameter to pass."""
    from datetime import UTC, datetime

    from pipeline import promotion

    seen: dict = {}

    def perform_swap(tiles_dir, build_id, upstreams, overrides_read_at=None):
        seen["read_at"] = overrides_read_at
        return promotion.SwapOutcome(build_id=build_id)

    monkeypatch.setattr(promotion, "perform_swap", perform_swap)
    monkeypatch.setattr(
        "core.management.commands.import_cloud_build.reconcile.drift_report", lambda *a: None
    )

    out = run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    assert seen["read_at"] == datetime(2026, 10, 4, 7, 0, tzinfo=UTC)
    assert "re-applied" in out


def test_where_the_links_cannot_be_written_nothing_is_imported(deployment, monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.tiles.unwritable_link_dirs", lambda tiles_dir: ["standard: read-only"]
    )

    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    assert "cannot write the promotion links" in str(refused.value)
    assert serving(deployment) == {OLD}


def test_an_undo_that_did_not_finish_points_at_its_alert(deployment, monkeypatch) -> None:
    from pipeline import promotion

    def half_done(*args, **kwargs):
        raise promotion.SwapUndoIncomplete(
            RuntimeError("disk full"), ["standard still on the new build"]
        )

    monkeypatch.setattr(promotion, "perform_swap", half_done)

    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", READ_AT, "--confirm")

    assert "A SwapUndoIncomplete alert" in str(refused.value)
    assert "was undone" not in str(refused.value)


def approve_override(at: str) -> int:
    from datetime import datetime

    from core.models import Override

    return Override.objects.create(
        kind=Override.Kind.ACCESS,
        osm_way_id=42,
        value={"bicycle": "no"},
        reason="closed",
        evidence="test",
        approved=True,
        approved_at=datetime.fromisoformat(at),
    ).id


def test_an_override_approved_after_the_copy_refuses_the_swap(deployment) -> None:
    approve_override("2026-10-03T12:00:00+00:00")
    later = approve_override("2026-10-05T12:00:00+00:00")

    out = run(NEW, "--overrides-read-at", READ_AT)
    assert "1 access override(s) approved after 2026-10-04 07:00:00 UTC" in out
    assert f"ids {later})" in out and "--confirm alone will refuse" in out

    with pytest.raises(CommandError) as refused:
        run(NEW, "--overrides-read-at", READ_AT, "--confirm")
    assert "--accept-later-overrides" in str(refused.value)
    assert serving(deployment) == {OLD}

    run(NEW, "--overrides-read-at", READ_AT, "--accept-later-overrides", "--confirm")
    assert serving(deployment) == {NEW}
