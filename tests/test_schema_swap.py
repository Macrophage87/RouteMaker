"""Schema swap tests, run against real PostgreSQL.

The swap is the riskiest operation in the weekly rebuild: it takes an ACCESS
EXCLUSIVE lock on a live database while requests are in flight. These tests
exercise the parts that only a real engine has.
"""

from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db(transaction=True)


def row_count(schema: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {schema}.segment")
        return cursor.fetchone()[0]


def insert_segment(schema: str, way_id: int, tier: int = 2) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""INSERT INTO {schema}.segment
                (osm_way_id, ordinal, geometry, stress_tier, stress_rule)
                VALUES (%s, 0, ST_GeomFromText('LINESTRING(-77 38.9, -77.01 38.91)', 4326),
                        %s, 'test')""",
            [way_id, tier],
        )


def test_swap_promotes_staging_and_retires_live(segment_schemas) -> None:
    from pipeline.schema import schema_exists
    from pipeline.swap import swap_schemas

    insert_segment("live", 111)
    insert_segment("staging", 222)
    insert_segment("staging", 333)

    result = swap_schemas()

    assert row_count("live") == 2, "staging content should now be live"
    assert schema_exists(result.retired), "previous live must be kept for rollback"
    assert row_count(result.retired) == 1
    assert not schema_exists("staging")


def test_rollback_restores_the_previous_live(segment_schemas) -> None:
    from pipeline.swap import rollback_swap, swap_schemas

    insert_segment("live", 111)
    insert_segment("staging", 222)
    insert_segment("staging", 333)

    swap_schemas()
    rollback_swap()

    assert row_count("live") == 1, "the original live content must come back"
    assert row_count("staging") == 2


def test_rename_is_three_steps_not_one(segment_schemas) -> None:
    """`staging` cannot take the name `live` while `live` still holds it. A
    single-rename implementation raises 'schema already exists' here."""
    from pipeline.swap import swap_schemas

    insert_segment("live", 111)
    insert_segment("staging", 222)
    result = swap_schemas()
    assert result.retired == "live_old"
    assert result.attempts == 1


def test_lock_timeout_is_scoped_to_the_swap_transaction(segment_schemas) -> None:
    """SET LOCAL must not leak: a swap that left lock_timeout set on a pooled
    connection would arm a timeout on every later query that connection served."""
    from pipeline.swap import swap_schemas

    swap_schemas()
    with connection.cursor() as cursor:
        cursor.execute("SHOW lock_timeout")
        assert cursor.fetchone()[0] in ("0", "0ms")


def test_no_foreign_key_points_into_the_swapped_schema(segment_schemas) -> None:
    """A cross-schema constraint would make the rename impossible, so the rule is
    asserted rather than left to reviewer memory."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM pg_constraint c
            JOIN pg_class child ON child.oid = c.conrelid
            JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
            JOIN pg_class parent ON parent.oid = c.confrelid
            JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
            WHERE c.contype = 'f'
              AND parent_ns.nspname IN ('live', 'staging')
              AND child_ns.nspname NOT IN ('live', 'staging')
            """
        )
        assert cursor.fetchone()[0] == 0


def test_segment_table_is_not_created_by_migrate() -> None:
    """Segment is unmanaged on purpose: the pipeline owns its DDL. If a migration
    ever starts creating it, it will fight the swap."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename = 'segment'"
        )
        assert cursor.fetchone()[0] == 0
