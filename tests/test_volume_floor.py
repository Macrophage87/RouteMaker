"""`volume.json` needs a full install's worth of counts (review 2026-10-29).

An empty or misprojected file used to load without complaint, and conflation then
matched nothing, so every road rated as if it had no traffic count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.run import ReferenceDataMissing, check_volume_rows

PATH = Path("/data/reference/volume.json")


def rows(count: int, lon: float = -77.0, lat: float = 38.9) -> list[dict]:
    return [{"id": str(n), "coordinates": [[lon, lat], [lon + 0.001, lat]]} for n in range(count)]


def test_a_full_file_passes() -> None:
    check_volume_rows(rows(5), 5, PATH)


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(ReferenceDataMissing, match="has 0 traffic counts"):
        check_volume_rows([], 5, PATH)


def test_counts_written_in_metres_are_refused() -> None:
    with pytest.raises(ReferenceDataMissing, match="of 5 rows"):
        check_volume_rows(rows(5, lon=325_000.0, lat=4_306_000.0), 5, PATH)


def test_rows_without_coordinates_do_not_count() -> None:
    with pytest.raises(ReferenceDataMissing):
        check_volume_rows([*rows(4), {"id": "x"}, {"id": "y", "coordinates": []}], 5, PATH)


def test_a_floor_of_zero_checks_nothing() -> None:
    check_volume_rows([], 0, PATH)


def test_the_weekly_task_passes_the_setting() -> None:
    import inspect

    from config import procrastinate

    assert "min_volume_rows=settings.REBUILD_VOLUME_MIN_ROWS" in inspect.getsource(procrastinate)
