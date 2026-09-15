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
    """SET LOCAL must not leak onto the connection: a swap that left it armed
    would put a timeout on every later query that connection served.

    Asserted on the same session the swap used. An earlier version of this test
    ran after the swap closed its connection, so it read a fresh session's
    default and could not fail - changing SET LOCAL to SET left it green.
    """
    from pipeline.swap import swap_schemas

    with connection.cursor() as cursor:
        cursor.execute("SET lock_timeout = '7s'")
    swap_schemas()
    with connection.cursor() as cursor:
        cursor.execute("SHOW lock_timeout")
        assert cursor.fetchone()[0] == "7s", "the swap overwrote the session setting"


def test_a_non_lock_failure_is_raised_as_itself(segment_schemas) -> None:
    """Relabelling every terminal error as a lock timeout told an operator
    reading the alert for a missing schema that the swap could not get a lock."""
    import pytest as _pytest
    from django.db.utils import ProgrammingError

    from pipeline.schema import drop_segment_schema
    from pipeline.swap import SwapLockTimeout, swap_schemas

    drop_segment_schema("staging")
    with _pytest.raises(ProgrammingError):
        swap_schemas(attempts=1)
    # And specifically not the lock error.
    drop_segment_schema("staging")
    try:
        swap_schemas(attempts=2, backoff_s=0)
    except SwapLockTimeout:  # pragma: no cover - the failure this guards against
        raise AssertionError("a missing schema was reported as lock contention") from None
    except ProgrammingError:
        pass


def test_rollback_without_a_retired_schema_is_refused_clearly(segment_schemas) -> None:
    import pytest as _pytest

    from pipeline.swap import SwapRollbackUnavailable, rollback_swap

    with _pytest.raises(SwapRollbackUnavailable):
        rollback_swap()


def test_swap_refuses_to_run_inside_a_transaction(segment_schemas) -> None:
    """Closing or committing a connection mid-transaction would silently discard
    the caller's work; the earlier version did exactly that."""
    import pytest as _pytest
    from django.db import transaction

    from pipeline.swap import SwapInsideTransaction, swap_schemas

    with _pytest.raises(SwapInsideTransaction), transaction.atomic():
        swap_schemas()


def test_first_swap_on_a_fresh_deployment_succeeds(segment_schemas) -> None:
    """With staging present and live absent, the rename raised and no fresh
    deployment could ever complete its first rebuild."""
    from pipeline.schema import drop_segment_schema, schema_exists
    from pipeline.swap import swap_schemas

    drop_segment_schema("live")
    assert not schema_exists("live")
    insert_segment("staging", 222)
    swap_schemas()
    assert row_count("live") == 1


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


def test_the_unmanaged_segment_model_is_readable_through_the_orm(segment_schemas) -> None:
    """The search path has to name the live schema, or the unmanaged Segment
    model resolves to a bare `segment` that exists nowhere on the path and is
    unreadable in every environment. Nothing caught this before, because every
    other database test reaches these tables through schema-qualified raw SQL.
    """
    from core.models import Segment

    insert_segment("live", 4242)
    assert Segment.objects.count() == 1
    assert Segment.objects.first().osm_way_id == 4242


def test_the_search_path_also_covers_the_migrated_schema(segment_schemas) -> None:
    """The pipeline queries `jurisdiction` unqualified and it lives in public, so
    a path naming only the live schema breaks the jurisdiction tagger instead."""
    from core.models import Jurisdiction

    assert Jurisdiction.objects.count() >= 0  # resolves rather than raising
