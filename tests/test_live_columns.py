"""The one shared answer to "has the live segment table this column?" (review CH-1, speed-11).

`segment_info.live_columns` keeps the live table's columns for COLUMN_RECHECK_S, both the
ones it has and the ones it lacks, and every check in routing, junctions and Mountain Bike
reads it. A rollback puts an older table, without a newer column, under the live name from
another process: the checks follow within the recheck, without an api restart.
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


@db
def test_a_rollback_to_a_table_without_a_column_is_seen_without_a_restart(
    segment_schemas, clock
) -> None:
    live, _staging = segment_schemas
    checks = (
        lambda: routing._has_half_column(live),
        lambda: junctions.has_half_column(live),
        lambda: segment_info.has_columns(live, STRESS_HALF_COLUMN),
    )
    assert all(check() for check in checks)
    # The older build goes live (as `rollback_swap` renames it back) without the column.
    drop(live, STRESS_HALF_COLUMN)
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
    assert len(queries) == 0
    clock[0] += segment_info.COLUMN_RECHECK_S
    with CaptureQueriesContext(connection) as queries:
        mtb._has_column(live, MTB_LEVEL_COLUMN)
    assert len(queries) == 1


@db
def test_forgetting_reads_the_table_again_at_once(segment_schemas, clock) -> None:
    live, _staging = segment_schemas
    assert routing._has_walk_column(live)
    drop(live, "walk_bike")
    assert routing._has_walk_column(live), "kept within the recheck"
    segment_info.forget_columns()
    assert not routing._has_walk_column(live)
