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


def test_migrations_land_in_public_even_when_live_exists(segment_schemas) -> None:
    """The search path must name public first.

    PostgreSQL creates an unqualified table in the first *existing* schema on the
    path, and Django migrations are never schema-qualified. With the live schema
    first, a deploy onto a box that had run one rebuild put every application
    table inside the schema the weekly swap renames away, and the swap after that
    dropped it with CASCADE - one deploy plus two rebuilds, and the users,
    sessions, memberships and django_migrations are gone.

    It was invisible on a fresh checkout because the live schema does not exist
    yet, so migrations landed in public and every test passed. This asserts the
    ordering directly rather than asserting that reads resolve, which they did
    either way.
    """
    from django.conf import settings

    path = settings.DATABASES["default"]["OPTIONS"]["options"]
    schemas = path.split("search_path=", 1)[1].split(",")
    assert schemas[0].strip() == "public", "public must be first on the search path"

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT schemaname FROM pg_tables
               WHERE tablename IN ('app_user', 'django_migrations', 'jurisdiction')"""
        )
        homes = {row[0] for row in cursor.fetchall()}
    assert homes == {"public"}, f"application tables must live in public, found {homes}"


def test_a_swap_does_not_take_the_application_schema_with_it(segment_schemas) -> None:
    """The consequence the ordering prevents, asserted end to end."""
    from pipeline.swap import swap_schemas

    insert_segment("staging", 4242)
    swap_schemas()

    from core.models import User

    assert User.objects.count() == 0, "the users table must still resolve after a swap"
    assert row_count("live") == 1


def second_connection():
    """A genuinely separate backend, for holding a conflicting lock.

    Django's test connection is the one the swap runs on, so a lock taken
    through it would be held by the same transaction and conflict with nothing.
    """
    import psycopg2

    settings = connection.settings_dict
    return psycopg2.connect(
        host=settings["HOST"] or "127.0.0.1",
        port=settings["PORT"] or 5432,
        dbname=settings["NAME"],
        user=settings["USER"],
        password=settings["PASSWORD"],
    )


def test_the_swap_takes_a_lock_that_conflicts_with_an_ordinary_reader(segment_schemas) -> None:
    """The lock the design depends on, asserted by contention rather than by
    reading the source.

    ACCESS SHARE - what a plain SELECT takes - conflicts with exactly one lock
    mode, ACCESS EXCLUSIVE. So a reader holding it must be able to stop the swap,
    and if it cannot, the swap is not taking the lock it claims to. Deleting the
    LOCK TABLE line leaves the renames untouched here: ALTER SCHEMA locks the
    schema object, not the table inside it.
    """
    import time

    from pipeline.swap import SwapLockTimeout, swap_schemas

    holder = second_connection()
    try:
        with holder.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute("LOCK TABLE live.segment IN ACCESS SHARE MODE")

        # A backstop on the *test's* session, so that a swap which sets no
        # lock_timeout of its own fails here rather than blocking until the
        # reader lets go - which, since the reader is released in the finally
        # below, would be never. It is three seconds against the swap's 200 ms,
        # so it never fires while the mechanism works.
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '3s'")

        try:
            started = time.monotonic()
            with pytest.raises(SwapLockTimeout):
                swap_schemas(lock_timeout_ms=200, attempts=1, backoff_s=0.0)
            assert time.monotonic() - started < 3.0
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = 0")
    finally:
        holder.rollback()
        holder.close()


def test_a_reader_that_lets_go_costs_the_swap_an_attempt_rather_than_the_rebuild(
    segment_schemas,
) -> None:
    """A slow reader is a retry, not a failed rebuild. Six hours of build work
    must not be discarded because one request held a table for a second."""
    import threading
    import time

    from pipeline.swap import swap_schemas

    holder = second_connection()
    released = threading.Event()

    def hold_briefly() -> None:
        with holder.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute("LOCK TABLE live.segment IN ACCESS SHARE MODE")
        time.sleep(0.6)
        holder.rollback()
        released.set()

    thread = threading.Thread(target=hold_briefly)
    thread.start()
    time.sleep(0.1)  # let the reader take its lock first
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '3s'")
        result = swap_schemas(lock_timeout_ms=150, attempts=10, backoff_s=0.1)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = 0")
        thread.join()
        holder.close()

    assert released.is_set()
    assert result.attempts > 1, "the contention cost nothing, so nothing was retried"


def test_the_rollback_path_takes_the_same_lock(segment_schemas) -> None:
    """Every argument for the lock applies to the rollback with more force, since
    it runs when something is already wrong."""
    import time

    from pipeline.swap import rollback_swap, swap_schemas

    swap_schemas()

    holder = second_connection()
    try:
        with holder.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute("LOCK TABLE live.segment IN ACCESS SHARE MODE")

        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '3s'")
        try:
            started = time.monotonic()
            with pytest.raises(Exception, match="lock|timeout|LockNotAvailable"):
                rollback_swap(lock_timeout_ms=200, attempts=1, backoff_s=0.0)
            assert time.monotonic() - started < 3.0
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = 0")
    finally:
        holder.rollback()
        holder.close()
