"""The rebuild builds the segment indexes after its bulk insert (review 2026-10-29).

`reset_segment_schema` creates the staging table without them and WRITE_SEGMENTS
calls `create_segment_indexes` once the rows are in, so a multi-million-row insert
does not maintain eight indexes row by row. Every other schema (`swap_schemas`'
empty live one, the tests') is created with them, as before.
"""

from __future__ import annotations

import re

import pytest

from pipeline import schema


class Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql, params=None) -> None:
        self.statements.append(sql)


@pytest.fixture
def recorded(monkeypatch) -> list[str]:
    recorder = Recorder()
    monkeypatch.setattr(schema.connection, "cursor", lambda: recorder)
    return recorder.statements


def segment_indexes(statements: list[str]) -> list[str]:
    return re.findall(r"CREATE INDEX IF NOT EXISTS (segment_\w+) ON", "\n".join(statements))


def test_the_table_ddl_creates_no_segment_index() -> None:
    assert "ON {schema}.segment" not in schema.SEGMENT_DDL
    assert "CONSTRAINT segment_key UNIQUE" in schema.SEGMENT_DDL, "the key stays with the table"


def test_a_staging_reset_leaves_the_indexes_out(recorded, monkeypatch) -> None:
    monkeypatch.setattr(schema, "refuse_unswappable_schema", lambda name: None)
    schema.reset_segment_schema("staging")
    assert segment_indexes(recorded) == []


def test_an_ordinary_schema_gets_all_eight(recorded) -> None:
    schema.create_segment_schema("live")
    assert len(segment_indexes(recorded)) == 8
    assert not any(statement.startswith("ANALYZE") for statement in recorded)


def test_creating_them_after_the_load_also_analyzes(recorded) -> None:
    schema.create_segment_indexes("staging")
    assert len(segment_indexes(recorded)) == 8
    assert recorded[-1] == "ANALYZE staging.segment"
    # Every placeholder filled.
    assert "{" not in "\n".join(recorded)


def test_write_segments_creates_them_before_anything_updates_the_rows() -> None:
    import inspect

    from pipeline import run

    source = inspect.getsource(run.build_handlers)
    insert = source.index("writers.write_segments(context.staging_schema, rows)")
    assert source.index("create_segment_indexes(context.staging_schema)", insert) < source.index(
        "writers.mark_links(", insert
    )
