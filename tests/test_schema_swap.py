"""Schema swap tests, run against real PostgreSQL.

The swap is the riskiest operation in the weekly rebuild: it takes an ACCESS
EXCLUSIVE lock on a live database while requests are in flight. These tests
exercise the parts that only a real engine has.

Every test below takes its schema names from the `segment_schemas` fixture
rather than writing `"live"` / `"staging"` as literals. That is the fix for
handoff item 18: with the names hardcoded, setting `ROUTEMAKER_LIVE_SCHEMA`
and `ROUTEMAKER_STAGING_SCHEMA` failed eleven of these tests, because the
fixture created schemas under the renamed names while the tests still read
and wrote `live` and `staging`.
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


# --- Schema-name injection guard (pipeline/schema.py) -----------------------
#
# validate_schema_name's comment used to say schema names "come from settings
# today", as if that made interpolating them into DDL safe by default. It does
# not: settings.SEGMENT_SCHEMA_LIVE and SEGMENT_SCHEMA_STAGING are themselves
# `os.environ.get(...)`, so the guard is what stands between whatever an
# operator's environment sets and arbitrary SQL running against production,
# not a defense against some hypothetical future change. Nothing called it
# with a hostile name before this.


def test_validate_schema_name_rejects_a_statement_terminator() -> None:
    from pipeline.schema import validate_schema_name

    with pytest.raises(ValueError):
        validate_schema_name("live; DROP SCHEMA public")


def test_validate_schema_name_rejects_uppercase() -> None:
    from pipeline.schema import validate_schema_name

    with pytest.raises(ValueError):
        validate_schema_name("Live")


def test_validate_schema_name_rejects_the_empty_string() -> None:
    from pipeline.schema import validate_schema_name

    with pytest.raises(ValueError):
        validate_schema_name("")


def test_validate_schema_name_accepts_an_ordinary_name() -> None:
    from pipeline.schema import validate_schema_name

    assert validate_schema_name("live_b") == "live_b"


# --- What the reset refuses to drop (pipeline/schema.py, config/settings.py) ---
#
# `reset_segment_schema` is the first thing FETCH_EXTRACT does, and the first
# thing it does is `DROP SCHEMA <staging> CASCADE`. The name comes from
# ROUTEMAKER_STAGING_SCHEMA by way of settings, unexamined: `writers.
# refuse_live_schema` guards the additive writers and nothing guarded this, and
# nothing anywhere asserted that staging and live are two different names. Set
# the variable to the live name - a typo, a copied `.env`, a second deployment
# sharing a host - and Tuesday morning's rebuild deletes the served graph before
# it has fetched a byte of OSM.


PROTECTED_SCHEMAS = ["the live schema", "the retired schema", "public"]


@pytest.mark.parametrize("which", PROTECTED_SCHEMAS)
def test_reset_refuses_a_staging_name_that_names_a_schema_it_must_never_drop(
    segment_schemas, settings, which
) -> None:
    """The misconfiguration in full: the staging setting carries a name that is
    already something else, and the rebuild's first stage is handed it.

    Three names are refused. The live schema is the served graph; the retired
    schema is what `rollback_rebuild` puts back, so dropping it turns one bad
    rebuild into an unrecoverable one; `public` carries every migrated table -
    users, sessions, memberships, the audit log - so a `DROP SCHEMA public
    CASCADE` here is the deployment rather than one week's segments.
    """
    from pipeline.schema import create_segment_schema, reset_segment_schema, schema_exists

    live, _staging = segment_schemas
    retired = settings.SEGMENT_SCHEMA_RETIRED
    create_segment_schema(retired)
    insert_segment(live, 4242)
    insert_segment(retired, 4243)

    settings.SEGMENT_SCHEMA_STAGING = {
        "the live schema": live,
        "the retired schema": retired,
        "public": "public",
    }[which]

    with pytest.raises(ValueError, match="refusing"):
        reset_segment_schema(settings.SEGMENT_SCHEMA_STAGING)

    assert row_count(live) == 1, "the served graph is still there"
    assert row_count(retired) == 1, "and so is the rollback target"
    assert schema_exists("public"), "and so is everything migrations own"


def test_reset_still_builds_an_ordinary_staging_schema(segment_schemas) -> None:
    """The refusal is a refusal of three names and not of the first stage."""
    from pipeline.schema import reset_segment_schema

    _live, staging = segment_schemas
    insert_segment(staging, 99)

    reset_segment_schema(staging)

    assert row_count(staging) == 0, "last week's rows are gone, the schema is not"


def test_reset_refuses_a_name_no_ddl_should_carry(segment_schemas) -> None:
    """`validate_schema_name`'s rule applies before the drop, not after it."""
    from pipeline.schema import reset_segment_schema

    with pytest.raises(ValueError):
        reset_segment_schema("staging; DROP SCHEMA public CASCADE")


def test_settings_refuse_a_staging_schema_that_is_the_live_one(monkeypatch) -> None:
    """The other half, one layer earlier: a deployment configured this way does
    not start, rather than starting and destroying something on Tuesday.

    `config/settings.py` is executed again under a modified environment, the way
    tests/test_settings_security.py does it, because what is being tested is what
    happens at import time.
    """
    from django.conf import settings as live_settings
    from django.core.exceptions import ImproperlyConfigured
    from test_settings_security import load_settings_module

    monkeypatch.setenv("ROUTEMAKER_STAGING_SCHEMA", live_settings.SEGMENT_SCHEMA_LIVE)
    with pytest.raises(ImproperlyConfigured, match="distinct"):
        load_settings_module("config_settings_colliding_schemas")


def test_settings_refuse_a_staging_schema_that_is_the_retired_one(monkeypatch) -> None:
    """`<live>_old` is the rollback target, and it is derived rather than set,
    so this is the collision an operator is least likely to see coming."""
    from django.conf import settings as live_settings
    from django.core.exceptions import ImproperlyConfigured
    from test_settings_security import load_settings_module

    monkeypatch.setenv("ROUTEMAKER_STAGING_SCHEMA", f"{live_settings.SEGMENT_SCHEMA_LIVE}_old")
    with pytest.raises(ImproperlyConfigured, match="distinct"):
        load_settings_module("config_settings_retired_collision")


@pytest.mark.parametrize("variable", ["ROUTEMAKER_LIVE_SCHEMA", "ROUTEMAKER_STAGING_SCHEMA"])
def test_settings_refuse_public_as_either_schema(monkeypatch, variable) -> None:
    """Either variable set to `public` puts the swap's DROP over every migrated
    table in the deployment."""
    from django.core.exceptions import ImproperlyConfigured
    from test_settings_security import load_settings_module

    monkeypatch.setenv(variable, "public")
    with pytest.raises(ImproperlyConfigured, match="public"):
        load_settings_module(f"config_settings_public_{variable.lower()}")


def test_the_shipped_schema_names_are_three_distinct_non_public_names() -> None:
    """Against the settings this process is running under, not a re-executed
    copy: whatever the environment of this run is, it passed the check."""
    from django.conf import settings as live_settings

    names = [
        live_settings.SEGMENT_SCHEMA_LIVE,
        live_settings.SEGMENT_SCHEMA_STAGING,
        live_settings.SEGMENT_SCHEMA_RETIRED,
    ]
    assert len(set(names)) == 3
    assert "public" not in names


def test_swap_promotes_staging_and_retires_live(segment_schemas) -> None:
    from pipeline.schema import schema_exists
    from pipeline.swap import swap_schemas

    live, staging = segment_schemas
    insert_segment(live, 111)
    insert_segment(staging, 222)
    insert_segment(staging, 333)

    result = swap_schemas()

    assert row_count(live) == 2, "staging content should now be live"
    assert schema_exists(result.retired), "previous live must be kept for rollback"
    assert row_count(result.retired) == 1
    assert not schema_exists(staging)


def test_rollback_restores_the_previous_live(segment_schemas) -> None:
    from pipeline.swap import rollback_swap, swap_schemas

    live, staging = segment_schemas
    insert_segment(live, 111)
    insert_segment(staging, 222)
    insert_segment(staging, 333)

    swap_schemas()
    rollback_swap()

    assert row_count(live) == 1, "the original live content must come back"
    assert row_count(staging) == 2


def test_rename_is_three_steps_not_one(segment_schemas) -> None:
    """`staging` cannot take the name `live` while `live` still holds it. A
    single-rename implementation raises 'schema already exists' here."""
    from pipeline.swap import swap_schemas

    live, staging = segment_schemas
    insert_segment(live, 111)
    insert_segment(staging, 222)
    result = swap_schemas()
    assert result.retired == f"{live}_old"
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

    _live, staging = segment_schemas
    drop_segment_schema(staging)
    with _pytest.raises(ProgrammingError):
        swap_schemas(attempts=1)
    # And specifically not the lock error.
    drop_segment_schema(staging)
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

    live, staging = segment_schemas
    drop_segment_schema(live)
    assert not schema_exists(live)
    insert_segment(staging, 222)
    swap_schemas()
    assert row_count(live) == 1


def test_no_foreign_key_points_into_the_swapped_schema(segment_schemas) -> None:
    """A cross-schema constraint would make the rename impossible, so the rule is
    asserted rather than left to reviewer memory."""
    live, staging = segment_schemas
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
              AND parent_ns.nspname IN (%s, %s)
              AND child_ns.nspname NOT IN (%s, %s)
            """,
            [live, staging, live, staging],
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

    live, _staging = segment_schemas
    insert_segment(live, 4242)
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


def test_the_swaps_defaults_are_the_ones_it_ships_with() -> None:
    """`perform_swap` calls `swap_schemas()` with no arguments, so these three
    constants are the production values rather than defaults something overrides.
    Pinned flat because each is a promise the plan makes: a lock timeout short
    enough that a blocked `DROP SCHEMA` gives up and retries rather than sitting
    on an access-exclusive lock while requests queue behind it, and a bounded
    retry with backoff behind it. At one attempt there is no retry at all, and
    at a hundred times the timeout the first attempt is the outage."""
    from pipeline import swap

    assert (swap.DEFAULT_LOCK_TIMEOUT_MS, swap.DEFAULT_ATTEMPTS, swap.DEFAULT_BACKOFF_S) == (
        3_000,
        5,
        2.0,
    )


def test_a_swap_does_not_take_the_application_schema_with_it(segment_schemas) -> None:
    """The consequence the ordering prevents, asserted end to end."""
    from core.models import User
    from pipeline.swap import swap_schemas

    # A row, because "the users table still resolves" was asserted as a count of
    # zero against a table nothing had ever written to: the same assertion passes
    # against an empty table, a table in the wrong schema and a table Django has
    # just created for the test.
    User.objects.create(discord_user_id=4242)

    live, staging = segment_schemas
    insert_segment(staging, 4242)
    swap_schemas()

    assert User.objects.count() == 1, "the users table must still resolve after a swap"
    assert User.objects.get().discord_user_id == 4242
    assert row_count(live) == 1


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

    live, _staging = segment_schemas
    holder = second_connection()
    try:
        with holder.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(f"LOCK TABLE {live}.segment IN ACCESS SHARE MODE")

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

    live, _staging = segment_schemas
    holder = second_connection()
    released = threading.Event()

    def hold_briefly() -> None:
        with holder.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(f"LOCK TABLE {live}.segment IN ACCESS SHARE MODE")
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

    live, _staging = segment_schemas
    swap_schemas()

    holder = second_connection()
    try:
        with holder.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(f"LOCK TABLE {live}.segment IN ACCESS SHARE MODE")

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


# --- F10: two consecutive swaps ---------------------------------------------
#
# Every test above calls swap_schemas() at most once per test, so the retired
# schema never exists yet when `DROP SCHEMA IF EXISTS {retired} CASCADE` runs:
# the statement is always a no-op, and a mutation that deleted it outright
# would still leave every test above green. Only a second swap, with staging
# refilled in between, makes the retired schema non-empty at the moment the
# drop runs.


def test_two_consecutive_swaps_actually_drop_the_retired_schema(segment_schemas) -> None:
    """The first swap's DROP SCHEMA ... CASCADE finds nothing to drop, because
    the retired name has never been used yet. The second swap's does: it has to
    remove the schema (and the rows in it) that the first swap's rename left
    behind, or the second swap's own rename fails outright with 'schema already
    exists' instead of quietly leaving stale data around.
    """
    from pipeline.schema import create_segment_schema
    from pipeline.swap import swap_schemas

    live, staging = segment_schemas
    insert_segment(live, 111)
    insert_segment(staging, 222)

    first = swap_schemas()
    assert row_count(first.retired) == 1  # the original live content: way 111

    # Refill staging for a second rebuild, the way a real weekly rebuild would.
    create_segment_schema(staging)
    insert_segment(staging, 444)

    second = swap_schemas()
    assert second.retired == first.retired, "the retired name is fixed, not incremented"
    assert row_count(live) == 1
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id FROM {live}.segment")
        assert cursor.fetchone()[0] == 444

    # The schema that held way 111 was dropped by the second swap's DROP
    # SCHEMA ... CASCADE, not merely renamed away a second time: it now holds
    # what used to be live (way 222), and 111 is gone everywhere.
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id FROM {second.retired}.segment")
        assert cursor.fetchone()[0] == 222
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT
                (SELECT count(*) FROM {live}.segment WHERE osm_way_id = 111) +
                (SELECT count(*) FROM {second.retired}.segment WHERE osm_way_id = 111)"""
        )
        assert cursor.fetchone()[0] == 0, "way 111 must not survive the second swap anywhere"


def test_deadlock_is_classified_as_a_lock_error() -> None:
    """55P03 (lock_not_available) is not the only SQLSTATE contention raises.
    40P01 (deadlock_detected) is a lock error too - the swap and the rollback
    both retry on it rather than raising it as a terminal failure - and losing
    it from LOCK_SQLSTATES would silently reclassify a deadlocked swap as one
    that should not be retried.
    """
    from pipeline.swap import _is_lock_error

    class FakeDeadlock(Exception):
        sqlstate = "40P01"

    class FakeSyntaxError(Exception):
        sqlstate = "42601"

    assert _is_lock_error(FakeDeadlock())
    assert not _is_lock_error(FakeSyntaxError())


# --- The rollback's own guards ----------------------------------------------
#
# Round 4: every guard the forward path has, the rollback lacked - and it is the
# path that runs when something has already gone wrong.


def test_rollback_refuses_to_run_inside_a_transaction(segment_schemas) -> None:
    """The same refusal as the forward swap, for the same reason: a rename that
    commits or rolls back with an enclosing transaction's work is not something
    to do quietly. `swap_schemas` has refused since round 2; `rollback_swap`
    took the plan's requirement as applying to the forward path only."""
    from django.db import transaction

    from pipeline.swap import SwapInsideTransaction, rollback_swap, swap_schemas

    swap_schemas()
    with pytest.raises(SwapInsideTransaction), transaction.atomic():
        rollback_swap()


def test_a_rollback_that_cannot_take_its_lock_is_classified_as_a_timeout(segment_schemas) -> None:
    """`swap_schemas` raises SwapLockTimeout when its attempts run out; the
    rollback re-raised the raw psycopg error, so the operator's undo reported
    contention as an unclassified database failure - in the one path where
    knowing it is worth retrying matters most."""
    from pipeline.swap import SwapLockTimeout, rollback_swap, swap_schemas

    live, _staging = segment_schemas
    swap_schemas()
    holder = second_connection()
    try:
        with holder.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(f"LOCK TABLE {live}.segment IN ACCESS SHARE MODE")
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '5s'")
        try:
            with pytest.raises(SwapLockTimeout):
                rollback_swap(lock_timeout_ms=150, attempts=2, backoff_s=0.0)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = 0")
    finally:
        holder.rollback()
        holder.close()


def test_rollback_drops_the_staging_schema_a_failed_rebuild_left_behind(segment_schemas) -> None:
    """A rebuild that fails at the swap leaves its staging schema on the disk,
    and the rollback's first rename needs that name. It used to raise a raw
    `schema "staging" already exists` from the middle of the rename - after the
    operator had decided to roll back and with nothing else having moved. The
    leftover is the failed rebuild's, so it is dropped."""
    from pipeline.schema import create_segment_schema
    from pipeline.swap import rollback_swap, swap_schemas

    live, staging = segment_schemas
    insert_segment(live, 111)
    insert_segment(staging, 222)
    swap_schemas()

    # The next rebuild builds into staging again and then fails at the swap.
    create_segment_schema(staging)
    insert_segment(staging, 333)

    rollback_swap()

    assert row_count(live) == 1, "the build before the one served is back"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id FROM {live}.segment")
        assert cursor.fetchone()[0] == 111
    assert row_count(staging) == 1, "staging holds what was live, not the abandoned rebuild"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id FROM {staging}.segment")
        assert cursor.fetchone()[0] == 222
