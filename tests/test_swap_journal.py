"""The swap journal: what a swap killed partway leaves to repair from (review 2026-10-29).

`perform_swap` writes every variant's links and settings row to the tiles directory
before it moves anything, marks the journal SWAPPED once the rename commits and
removes it after an undo that completed. These run the swap with the database
steps stubbed, so the tile links are real and nothing needs Postgres.
"""

from __future__ import annotations

import json
import os

import pytest

from pipeline import promotion, tiles
from pipeline.promotion import SWAPPED, SWAPPING, UpstreamState
from pipeline.variants import Variant

SERVED = "20261020T080000Z"
ROLLBACK = "20261013T080000Z"
NEW = "20261027T080000Z"


class Killed(BaseException):
    """Stands in for a SIGKILL: not an `Exception`, so no undo runs."""


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """Every variant serving SERVED with ROLLBACK as `previous`, NEW built, and the
    database half of the swap stubbed. Returns the tiles directory."""
    for variant in Variant:
        root = tmp_path / variant.value
        for build in (ROLLBACK, SERVED, NEW):
            (root / build).mkdir(parents=True)
            (root / build / "tiles.tar").write_bytes(b"")
        os.symlink(SERVED, root / "current")
        os.symlink(ROLLBACK, root / "previous")
    rows = {
        variant.value: UpstreamState(
            existed=True, url="http://router", build_id=SERVED, previous_build_id=ROLLBACK
        )
        for variant in Variant
    }
    monkeypatch.setattr(promotion, "upstream_states", lambda upstreams: dict(rows))
    monkeypatch.setattr(promotion, "repoint_upstreams", lambda build_id, upstreams: dict(rows))
    monkeypatch.setattr(promotion, "restore_upstreams", lambda before: None)
    monkeypatch.setattr(promotion, "swap_schemas", lambda: None)
    from core import segment_info, stress_edits

    monkeypatch.setattr(segment_info, "forget_columns", lambda: None)
    monkeypatch.setattr(stress_edits, "after_promotion", lambda read_at: 0)
    return tmp_path


def swap(tiles_dir, job_id=7):
    return promotion.perform_swap(tiles_dir, NEW, {}, job_id=job_id)


def test_a_committed_swap_records_the_job_that_made_it(deployment) -> None:
    swap(deployment)

    journal = promotion.read_swap_journal(deployment)
    assert journal["state"] == SWAPPED and journal["build_id"] == NEW
    assert promotion.swapped_job(deployment) == 7
    assert promotion.interrupted_swap(deployment) is None


def test_a_swap_killed_between_the_repoint_and_the_rename_leaves_its_journal(
    deployment, monkeypatch
) -> None:
    """The window the journal exists for: the links and rows name the new build,
    the rename never ran, and no undo ran either."""

    def killed() -> None:
        raise Killed

    monkeypatch.setattr(promotion, "swap_schemas", killed)
    with pytest.raises(Killed):
        swap(deployment)

    assert os.readlink(deployment / "standard" / "current") == NEW, "nothing was undone"
    journal = promotion.interrupted_swap(deployment)
    assert journal is not None and journal["state"] == SWAPPING and journal["job_id"] == 7
    assert journal["links"]["standard"] == {"current": SERVED, "previous": ROLLBACK}
    assert journal["rows"]["standard"]["previous_build_id"] == ROLLBACK
    # The rollback target is named although no link points at it any more.
    assert not any(os.readlink(deployment / v.value / "previous") == ROLLBACK for v in Variant)
    described = promotion.describe_interrupted_swap(journal)
    assert f"current -> {SERVED}, previous -> {ROLLBACK}" in described
    assert promotion.SWAP_JOURNAL in described


def test_a_swap_that_undoes_itself_removes_its_journal(deployment, monkeypatch) -> None:
    def refused() -> None:
        raise RuntimeError("lock not available")

    monkeypatch.setattr(promotion, "swap_schemas", refused)
    with pytest.raises(RuntimeError):
        swap(deployment)

    assert os.readlink(deployment / "standard" / "current") == SERVED
    assert promotion.read_swap_journal(deployment) is None


def test_an_undo_that_did_not_finish_keeps_its_journal(deployment, monkeypatch) -> None:
    def refused() -> None:
        raise RuntimeError("lock not available")

    def read_only(tiles_dir, variant, state) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(promotion, "swap_schemas", refused)
    monkeypatch.setattr(tiles, "restore_links", read_only)
    with pytest.raises(promotion.SwapUndoIncomplete):
        swap(deployment)

    assert promotion.interrupted_swap(deployment) is not None


def test_a_journal_that_cannot_be_read_counts_as_an_interrupted_swap(tmp_path) -> None:
    (tmp_path / promotion.SWAP_JOURNAL).write_text("{half a file", encoding="utf-8")

    journal = promotion.interrupted_swap(tmp_path)
    assert journal is not None and journal.get("unreadable")
    assert promotion.swapped_job(tmp_path) is None
    assert "could not be read" in promotion.describe_interrupted_swap(journal)


def test_no_journal_is_no_swap(tmp_path) -> None:
    assert promotion.read_swap_journal(tmp_path) is None
    assert promotion.read_swap_journal(tmp_path / "not-mounted") is None
    assert promotion.swapped_job(tmp_path) is None


def test_cleanup_after_an_interrupted_swap_deletes_no_build(deployment, monkeypatch) -> None:
    """After a `promote` that moved `previous` and then died, nothing links to the
    rollback target, and the after-run prune (keep=0) used to delete it."""
    from config.procrastinate import _prune_tile_builds

    def killed() -> None:
        raise Killed

    monkeypatch.setattr(promotion, "swap_schemas", killed)
    with pytest.raises(Killed):
        swap(deployment)

    assert _prune_tile_builds(deployment, 0, "after the run", protect=[NEW]) == 0
    for variant in Variant:
        assert (deployment / variant.value / ROLLBACK).is_dir(), variant.value


def test_cleanup_runs_as_before_once_the_swap_committed(deployment) -> None:
    swap(deployment)

    from config.procrastinate import _prune_tile_builds

    # current -> NEW and previous -> SERVED survive; the build before goes.
    assert _prune_tile_builds(deployment, 0, "after the run", protect=[NEW]) == len(Variant)
    assert not (deployment / "standard" / ROLLBACK).exists()


def test_the_journal_is_plain_json_an_operator_can_read(deployment, monkeypatch) -> None:
    def killed() -> None:
        raise Killed

    monkeypatch.setattr(promotion, "swap_schemas", killed)
    with pytest.raises(Killed):
        swap(deployment)

    raw = json.loads((deployment / promotion.SWAP_JOURNAL).read_text(encoding="utf-8"))
    assert len(raw["before"]) == len(Variant)
