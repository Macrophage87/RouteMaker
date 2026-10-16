"""The one shared answer to "has the live segment table this column?" (review CH-1, speed-11).

`segment_info.live_columns` keeps the live table's columns by its oid, and for
COLUMN_RECHECK_S, both the ones it has and the ones it lacks, and every check in routing,
junctions and Mountain Bike reads it. A rollback puts an older table, without a newer
column, under the live name from another process: the checks follow at once, without an api
restart; a column dropped or added in place, within the recheck.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core import junctions, mtb, routing, segment_info
from pipeline.schema import MTB_LEVEL_COLUMN, STRESS_HALF_COLUMN

db = pytest.mark.django_db(transaction=True)


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(segment_info.time, "monotonic", lambda: now[0])
    return now


def drop(schema: str, column: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {schema}.segment DROP COLUMN {column}")


def column_reads(queries) -> list:
    """The queries that read the table's columns, not just its oid."""
    return [q for q in queries if "pg_attribute" in q["sql"]]


@db
def test_another_table_under_the_live_name_is_seen_at_once(segment_schemas, clock) -> None:
    live, _staging = segment_schemas
    assert routing._has_half_column(live) and junctions.has_half_column(live)
    # A rollback's rename: an older build, without the column, is live now. The clock
    # has not moved: the oid alone says it is another table.
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {live}.segment RENAME TO segment_newer")
        cursor.execute(f"CREATE TABLE {live}.segment (LIKE {live}.segment_newer)")
    drop(live, STRESS_HALF_COLUMN)
    assert not routing._has_half_column(live)
    assert not junctions.has_half_column(live)


@db
def test_a_column_dropped_in_place_is_seen_within_the_recheck(segment_schemas, clock) -> None:
    live, _staging = segment_schemas
    checks = (
        lambda: routing._has_half_column(live),
        lambda: junctions.has_half_column(live),
        lambda: segment_info.has_columns(live, STRESS_HALF_COLUMN),
    )
    assert all(check() for check in checks)
    # Dropped in place, the table keeps its oid.
    drop(live, STRESS_HALF_COLUMN)
    assert all(check() for check in checks), "kept within the recheck"
    clock[0] += segment_info.COLUMN_RECHECK_S
    assert not any(check() for check in checks)


@db
def test_a_missing_column_is_not_asked_about_on_every_reading(segment_schemas, clock) -> None:
    live, _staging = segment_schemas
    drop(live, MTB_LEVEL_COLUMN)
    assert not mtb._has_column(live, MTB_LEVEL_COLUMN)
    with CaptureQueriesContext(connection) as queries:
        for _ in range(20):
            assert not mtb._has_column(live, MTB_LEVEL_COLUMN)
            assert routing._has_half_column(live)
            assert junctions.has_trait_columns(live)
    assert column_reads(queries) == []
    clock[0] += segment_info.COLUMN_RECHECK_S
    with CaptureQueriesContext(connection) as queries:
        mtb._has_column(live, MTB_LEVEL_COLUMN)
    assert len(column_reads(queries)) == 1


@db
def test_forgetting_reads_the_table_again_at_once(segment_schemas, clock) -> None:
    live, _staging = segment_schemas
    assert routing._has_walk_column(live)
    drop(live, "walk_bike")
    assert routing._has_walk_column(live), "kept within the recheck"
    segment_info.forget_columns()
    assert not routing._has_walk_column(live)
