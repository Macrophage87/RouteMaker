"""What the rebuild and the backup leave behind, and what removes it.

Nothing pruned either: one dated tile directory per week and one dump per night,
kept forever, on the volume the rebuild's own disk gate measures. The gate is a
hard refusal, so the end state is a rebuild that declines every week with "grow
the volume" as the only remedy.

Every test here runs against real directories and real symlinks, because the
things that can go wrong - deleting the build being served, deleting the
rollback target, following a link into the directory it names - are all
filesystem behaviour rather than logic.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline.retention import (
    KEEP_BUILDS,
    prune_backups,
    prune_builds,
    prune_tile_builds,
    unique_build_id,
)

BUILDS = [
    "20260901T080000Z",
    "20260908T080000Z",
    "20260915T080000Z",
    "20260922T080000Z",
    "20260929T080000Z",
]


def variant_with_builds(root: Path, current: str | None = None, previous: str | None = None):
    """Five weekly builds and the two promotion symlinks, as a served variant
    directory looks after five rebuilds."""
    root.mkdir(parents=True)
    for build in BUILDS:
        (root / build / "tiles").mkdir(parents=True)
        (root / build / "tiles.tar").write_bytes(b"x" * 16)
    if current:
        os.symlink(current, root / "current")
    if previous:
        os.symlink(previous, root / "previous")
    return root


def names(root: Path) -> list[str]:
    return sorted(entry.name for entry in root.iterdir() if not entry.is_symlink())


def test_pruning_keeps_the_two_newest_builds(tmp_path) -> None:
    """The plan sizes the volume for two full sets: the one being served and the
    one a rollback would put back."""
    root = variant_with_builds(tmp_path / "standard", current=BUILDS[4], previous=BUILDS[3])

    removed = prune_builds(root, keep=KEEP_BUILDS)

    assert removed == BUILDS[:3]
    assert names(root) == BUILDS[3:]
    assert os.readlink(root / "current") == BUILDS[4]
    assert (root / "current" / "tiles.tar").is_file(), "the served build is intact"
    assert (root / "previous" / "tiles.tar").is_file(), "so is the rollback target"


def test_pruning_never_removes_what_a_symlink_points_at(tmp_path) -> None:
    """After a rollback, `current` is the *older* directory. A plain newest-N
    rule would delete the graph being served, which is the outage this module
    exists to avoid rather than a corner of it."""
    root = variant_with_builds(tmp_path / "standard", current=BUILDS[0], previous=BUILDS[4])

    removed = prune_builds(root, keep=KEEP_BUILDS)

    assert removed == BUILDS[1:3], "the two newest survive on age, the served one on its link"
    assert names(root) == [BUILDS[0], BUILDS[3], BUILDS[4]]
    assert (root / "current" / "tiles.tar").is_file()
    assert (root / "previous" / "tiles.tar").is_file()


def test_pruning_a_directory_that_was_never_promoted_keeps_the_newest(tmp_path) -> None:
    """A first rebuild that failed before promotion leaves builds and no links."""
    root = variant_with_builds(tmp_path / "standard")

    assert prune_builds(root, keep=2) == BUILDS[:3]
    assert names(root) == BUILDS[3:]


def test_pruning_touches_nothing_it_does_not_recognise(tmp_path) -> None:
    """It deletes trees, so it does so only where it is certain what it is
    looking at: a dated build directory and nothing else.

    The scratch directory is named to sort *ahead* of the surviving builds on
    purpose. Anything named after them is kept by the newest-N rule whatever the
    pattern says, so a test using such a name proves nothing about the pattern.
    """
    root = variant_with_builds(tmp_path / "standard", current=BUILDS[4], previous=BUILDS[3])
    scratch = root / f"{BUILDS[0]}.partial"
    scratch.mkdir()
    (root / "notes.txt").write_text("keep me")

    removed = prune_builds(root, keep=KEEP_BUILDS)

    assert removed == BUILDS[:3]
    assert scratch.is_dir(), "an interrupted build's scratch is not this task's to remove"
    assert (root / "notes.txt").read_text() == "keep me"


def test_pruning_an_absent_directory_is_not_an_error(tmp_path) -> None:
    """The rebuild calls this after a promotion; a variant that has never been
    built has no directory, and that is not a failure worth abandoning a rebuild
    over."""
    assert prune_builds(tmp_path / "never-built") == []
    assert prune_tile_builds(tmp_path / "no-tiles-at-all") == {}


def test_every_variant_under_the_tiles_root_is_pruned(tmp_path) -> None:
    """Read off the filesystem rather than from the variant enum, so a variant
    that has been renamed still has its old directory pruned rather than kept
    forever by the one mechanism that could remove it."""
    tiles = tmp_path / "tiles"
    variant_with_builds(tiles / "standard", current=BUILDS[4], previous=BUILDS[3])
    variant_with_builds(tiles / "retired-variant")

    removed = prune_tile_builds(tiles, keep=KEEP_BUILDS)

    assert removed == {"retired-variant": BUILDS[:3], "standard": BUILDS[:3]}
    assert names(tiles / "standard") == BUILDS[3:]
    assert names(tiles / "retired-variant") == BUILDS[3:]


# --- Backups ---------------------------------------------------------------------------


def test_backup_pruning_keeps_the_newest_by_name(tmp_path) -> None:
    """By name rather than by mtime: the name carries the instant the dump was
    started, and a restore, a copy or a volume snapshot rewrites mtime without
    changing which dump is the newest."""
    dumps = [f"routemaker-2026091{day}T070000Z.dump" for day in range(1, 6)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")
    (tmp_path / "notes.txt").write_text("not a dump")
    # Oldest content, newest name: mtime order is deliberately the reverse.
    for index, name in enumerate(reversed(dumps)):
        os.utime(tmp_path / name, (index, index))

    removed = prune_backups(tmp_path, keep=2)

    assert [path.name for path in removed] == dumps[:3]
    assert sorted(path.name for path in tmp_path.glob("*.dump")) == dumps[3:]
    assert (tmp_path / "notes.txt").exists(), "only the dumps this task wrote are pruned"


def test_backup_pruning_of_fewer_dumps_than_it_keeps_removes_nothing(tmp_path) -> None:
    (tmp_path / "routemaker-20260917T070000Z.dump").write_bytes(b"dump")
    assert prune_backups(tmp_path, keep=7) == []
    assert prune_backups(tmp_path / "absent", keep=7) == []


# --- Build ids -------------------------------------------------------------------------


def test_a_second_build_in_the_same_second_gets_its_own_id() -> None:
    """Build ids are second-resolution because they are directory names an
    operator reads. Two builds sharing one share a directory, so the second
    writes its tiles into the first's tree and `previous` ends up pointing at a
    mixture of the two."""
    now = datetime(2026, 9, 17, 8, 0, 0, tzinfo=UTC)

    first = unique_build_id(now, existing=[])
    assert first == "20260917T080000Z"

    second = unique_build_id(now, existing=[first])
    third = unique_build_id(now, existing=[first, second])
    assert len({first, second, third}) == 3
    assert sorted([third, first, second]) == [first, second, third], "and they still sort in order"


def test_a_build_id_sorts_after_every_earlier_second() -> None:
    """The pruning above is a sort by name, so a disambiguated id must not sort
    ahead of an older build."""
    earlier = unique_build_id(datetime(2026, 9, 17, 7, 59, 59, tzinfo=UTC))
    base = datetime(2026, 9, 17, 8, 0, 0, tzinfo=UTC)
    suffixed = unique_build_id(base, existing=[unique_build_id(base)])
    later = unique_build_id(datetime(2026, 9, 17, 8, 0, 1, tzinfo=UTC))

    assert sorted([later, suffixed, earlier]) == [earlier, suffixed, later]


def test_a_thousand_collisions_is_an_error_rather_than_a_silent_reuse() -> None:
    now = datetime(2026, 9, 17, 8, 0, 0, tzinfo=UTC)
    taken = ["20260917T080000Z"] + [f"20260917T080000Z-{n}" for n in range(1, 1000)]
    with pytest.raises(RuntimeError, match="already carry"):
        unique_build_id(now, existing=taken)


def test_the_build_ids_already_on_disk_are_read_across_every_variant(tmp_path) -> None:
    """What `unique_build_id` has to be handed to mean anything. Across all
    variants, because one build id is one rebuild and names a directory under
    every variant that rebuild wrote."""
    from pipeline.retention import taken_build_ids

    tiles = tmp_path / "tiles"
    variant_with_builds(tiles / "standard", current=BUILDS[4])
    (tiles / "ebike" / "20260930T080000Z").mkdir(parents=True)
    (tiles / "ebike" / "scratch").mkdir()

    assert taken_build_ids(tiles) == set(BUILDS) | {"20260930T080000Z"}
    assert taken_build_ids(tmp_path / "absent") == set()
    assert unique_build_id(datetime(2026, 9, 29, 8, 0, 0, tzinfo=UTC), taken_build_ids(tiles)) == (
        "20260929T080000Z-1"
    )
