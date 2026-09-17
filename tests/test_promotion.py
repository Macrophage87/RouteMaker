"""Migration 0005, backwards.

0005 is the migration that moved `border_crossing` out of `public` and into the
schema the weekly swap promotes: it marks the model unmanaged and drops the
managed table, because an orphan in `public` would shadow the promoted copy
forever. Its `reverse_sql` is what a release rollback runs, and the plan
requires every migration to be reversible into the previous release, so what it
recreates has to be the table 0001 created - not an approximation of it.
"""

from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = "0004_audit_log"
AFTER = "0005_swap_settings_and_staged_crossings"


def public_indexes(table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = %s",
            [table],
        )
        return dict(cursor.fetchall())


def migrate_core(target: str) -> None:
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([("core", target)])


def test_reversing_0005_recreates_the_crossings_table_it_dropped(segment_schemas) -> None:
    """Including the GiST index on `location`, which 0001 created and the
    reverse did not: `route_crossings` and every other spatial predicate over
    the table would have fallen back to a sequential scan on a rolled-back
    release, and a later `makemigrations` would have seen no drift to report.
    """
    from core.models import BorderCrossing

    editor = connection.schema_editor()
    spatial_index = editor._create_index_name(BorderCrossing._meta.db_table, ["location"], "_id")

    try:
        migrate_core(BEFORE)
        indexes = public_indexes("border_crossing")
        assert spatial_index in indexes, (
            f"the reverse must recreate the spatial index 0001 made; found {sorted(indexes)}"
        )
        assert "USING gist (location)" in indexes[spatial_index]
        assert any("osm_way_id" in definition for definition in indexes.values())
        assert any("node_id" in definition for definition in indexes.values())
    finally:
        migrate_core(AFTER)

    assert public_indexes("border_crossing") == {}, "and forwards drops it again"
