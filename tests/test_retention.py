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
    BUILD_ID_FORMAT,
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


def test_a_protected_build_survives_whatever_its_place_in_the_order(tmp_path) -> None:
    """The rebuild protects the build it has just written, by name.

    Not "the newest as well": `unique_build_id` hands out the first free
    suffix inside a second, so a directory this run wrote can sort *before* one
    a failed run left, and a newest-N rule would then keep the wrong one and
    delete the build that had just been made. Here the protected build is the
    oldest of the five and no symlink names it.
    """
    root = variant_with_builds(tmp_path / "standard", current=BUILDS[4], previous=BUILDS[3])

    removed = prune_builds(root, keep=0, protect=[BUILDS[0]])

    assert removed == BUILDS[1:3]
    assert names(root) == [BUILDS[0], BUILDS[3], BUILDS[4]]
    assert (root / BUILDS[0] / "tiles.tar").is_file(), "the run's own build is still there"


def test_a_protected_build_is_protected_under_every_variant(tmp_path) -> None:
    """One build id names one rebuild, which wrote a directory under each
    variant; protecting it under one of them only would be half a build."""
    from pipeline.retention import prune_tile_builds

    tiles = tmp_path / "tiles"
    for variant in ("standard", "no-trail", "ebike"):
        variant_with_builds(tiles / variant, current=BUILDS[4], previous=BUILDS[3])

    pruned = prune_tile_builds(tiles, keep=0, protect=[BUILDS[0]])

    assert {variant: removed for variant, removed in pruned.items()} == {
        variant: BUILDS[1:3] for variant in ("standard", "no-trail", "ebike")
    }
    for variant in ("standard", "no-trail", "ebike"):
        assert names(tiles / variant) == [BUILDS[0], BUILDS[3], BUILDS[4]]


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


def test_a_symlinked_variant_directory_is_not_walked(tmp_path) -> None:
    """A link under the tiles root names a directory somewhere else, and
    `is_dir()` is true through it. Left in, the prune walks into whatever the
    link points at and `rmtree`s dated directories out of it - an operator's
    hand-made `latest -> standard` alias makes the standard variant pruned
    twice in one pass, and a link to another volume's tiles deletes builds this
    task was never given.

    Only real variant directories are pruned, so the linked-to directory is
    untouched and the link itself is not a variant in the report.
    """
    tiles = tmp_path / "tiles"
    variant_with_builds(tiles / "standard", current=BUILDS[4], previous=BUILDS[3])
    elsewhere = variant_with_builds(tmp_path / "somewhere-else")
    os.symlink(elsewhere, tiles / "alias")

    removed = prune_tile_builds(tiles, keep=KEEP_BUILDS)

    assert removed == {"standard": BUILDS[:3]}, "the link is not a variant of its own"
    assert names(elsewhere) == BUILDS, "and nothing was deleted through it"


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


def test_a_part_file_is_neither_pruned_nor_counted_as_a_kept_dump(tmp_path) -> None:
    """The half of the staging name that lives here rather than in the backup.

    `perform_backup` writes `<name>.dump.part` and renames it only once the
    archive has been read back, so a part file is either in flight or the
    wreckage of a failed run. Either way it is not a backup, and counting it as
    one is not a cosmetic error: it sorts newest - the part file carries the
    current instant - so with `keep=2` it would take a kept slot and a real dump
    would be deleted to make room for an archive no restore may use.
    """
    dumps = [f"routemaker-2026091{day}T070000Z.dump" for day in range(1, 4)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")
    # Newest by name, which is the position that does the damage.
    part = tmp_path / "routemaker-20260914T070000Z.dump.part"
    part.write_bytes(b"half a dump")

    removed = prune_backups(tmp_path, keep=2)

    assert [path.name for path in removed] == dumps[:1], (
        "two real dumps are kept and the oldest goes; the part file is not one of the three"
    )
    assert sorted(entry.name for entry in tmp_path.iterdir()) == sorted([*dumps[1:], part.name])
    assert part.exists(), (
        "and this one is left where it is: it is newer than every kept dump, which is the "
        "shape of the dump being written right now. An abandoned one, older than the newest "
        "kept dump, is reclaimed - see test_a_part_file_left_by_a_sigkill_is_reclaimed"
    )


def test_the_newest_real_dump_survives_a_part_file_taking_the_last_kept_slot(tmp_path) -> None:
    """The property stated when the part file was excluded, asserted as a
    property rather than as one arithmetic outcome.

    The part file carries the current instant, so it sorts newest of all - which
    means that if it is counted as a dump it takes the slot the newest finished
    dump would have had, and at the tightest retention that is the *only* slot.
    The restore-worthy archive is deleted and what remains is a half-written
    file. So: whatever else prune_backups does, the newest name matching a
    finished dump is still on disk afterwards.
    """
    dumps = [f"routemaker-2026091{day}T070000Z.dump" for day in range(1, 4)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")
    part = tmp_path / "routemaker-20260915T070000Z.dump.part"
    part.write_bytes(b"half a dump")

    prune_backups(tmp_path, keep=1)

    assert (tmp_path / dumps[-1]).exists(), "the newest finished dump is the one that is kept"
    assert sorted(path.name for path in tmp_path.glob("*.dump")) == [dumps[-1]]
    assert part.exists(), "and the part file was never a candidate either way"


@pytest.mark.parametrize("count", range(1, 8))
def test_backup_pruning_of_no_more_dumps_than_it_keeps_removes_nothing(tmp_path, count) -> None:
    """Every count up to `keep`, not one.

    With a single dump the clamp on `len(dumps) - keep` is invisible: the slice
    `dumps[:-6]` of a one-element list is empty either way. From four dumps
    under `keep=7` it is not - `dumps[:-3]` is the oldest - so an unclamped
    subtraction deletes the oldest dump from a deployment that has not yet
    written a week of them, which is the week a restore is most likely to need
    it.
    """
    dumps = [f"routemaker-202609{day:02d}T070000Z.dump" for day in range(10, 10 + count)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")

    assert prune_backups(tmp_path, keep=7) == []
    assert sorted(path.name for path in tmp_path.glob("*.dump")) == dumps


def test_backup_pruning_of_an_absent_directory_removes_nothing(tmp_path) -> None:
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


def test_new_build_id_skips_a_directory_that_already_exists(settings, tmp_path) -> None:
    """`run.new_build_id` is what the rebuild names its dated directory with,
    and it is second-resolution. Two fires in one second used to name the same
    directory; `write_build_config` now refuses the second, but a refused
    rebuild is a failed rebuild, and disambiguating is not."""
    from pipeline import run

    settings.TILES_DIR = tmp_path
    now = datetime(2026, 9, 17, 8, 0, 0, tzinfo=UTC)
    first = run.new_build_id(now)
    (tmp_path / "standard" / first).mkdir(parents=True)

    second = run.new_build_id(now)

    assert first == "20260917T080000Z"
    assert second != first
    assert second.startswith("20260917T080000Z")


def test_a_build_id_is_chosen_against_the_root_the_build_will_be_written_into(
    settings, tmp_path
) -> None:
    """The context carries its own tiles root, and a rebuild that reads the id
    off one directory and writes the build into another is choosing against the
    wrong set of names: the collision this exists to prevent is two builds in
    the *build's* root, not in the setting's.
    """
    from pipeline import run

    settings.TILES_DIR = tmp_path / "somewhere-else"
    real_root = tmp_path / "tiles"
    now = datetime(2026, 9, 17, 8, 0, 0, tzinfo=UTC)
    (real_root / "standard" / "20260917T080000Z").mkdir(parents=True)

    assert run.new_build_id(now, tiles_dir=real_root) == "20260917T080000Z-1"
    assert run.new_build_id(now) == "20260917T080000Z", "the setting's root knows nothing of it"

    # And the context chooses its own, against its own root: a directory
    # already carrying this second's id under `real_root` has to push it to a
    # suffix, while the same directory under the setting's root would not be
    # seen at all.
    this_second = datetime.now(UTC).strftime(BUILD_ID_FORMAT)
    (real_root / "standard" / this_second).mkdir(parents=True, exist_ok=True)
    context = run.RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
        tiles_dir=real_root,
    )
    assert context.build_id != this_second, (
        "the context's own root is what its build id is chosen against"
    )


def test_a_part_file_left_by_a_sigkill_is_reclaimed(tmp_path) -> None:
    """The one thing on the data volume nothing ever removed.

    `perform_backup` writes `<name>.dump.part` and its own `finally` removes it
    on every path its process lives through - a failed dump, a rejected
    listing, the thirty-minute timeout. The path it cannot cover is the one the
    staging name exists for: a SIGKILL, from `docker compose down`, a host
    reboot or the OOM killer. That leaves a full-sized archive under a name
    `prune_backups` matched none of, on the volume the rebuild's disk gate
    measures and the dumps share with PGDATA - and it stayed there for ever,
    one per kill, until the gate refused a rebuild with "grow the volume".
    """
    dumps = [f"routemaker-2026091{day}T070000Z.dump" for day in range(1, 5)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")
    abandoned = tmp_path / "routemaker-20260910T070000Z.dump.part"
    abandoned.write_bytes(b"half a dump")

    removed = prune_backups(tmp_path, keep=2)

    assert not abandoned.exists(), "a part file older than every kept dump is wreckage"
    assert [path.name for path in removed] == dumps[:2], (
        "the part file is not a dump and is not counted into the dumps that were pruned"
    )
    assert sorted(entry.name for entry in tmp_path.iterdir()) == dumps[2:]


def test_a_part_file_newer_than_every_kept_dump_is_the_one_being_written(tmp_path) -> None:
    """The rule is "older than the newest kept dump" rather than an age, and
    this is why. `prune_backups` runs from `nightly_backup`, in the same task
    as the dump; a part file whose instant is newer than every kept dump is the
    archive being written right now, and deleting it would be retention
    reaching into a live write.
    """
    dumps = [f"routemaker-2026091{day}T070000Z.dump" for day in range(1, 4)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")
    in_flight = tmp_path / "routemaker-20260914T070000Z.dump.part"
    in_flight.write_bytes(b"half a dump")

    prune_backups(tmp_path, keep=2)

    assert in_flight.exists()


def test_the_first_dump_in_flight_is_left_alone_with_nothing_to_compare_against(tmp_path) -> None:
    """With no kept dump there is no instant to measure a part file against,
    and the only part file that can exist beside no dump at all is the first
    one, in flight. Nothing is removed, which is the same answer the rule above
    gives seen from the other side.
    """
    first = tmp_path / "routemaker-20260911T070000Z.dump.part"
    first.write_bytes(b"half a dump")

    assert prune_backups(tmp_path, keep=7) == []
    assert first.exists()


def test_only_the_part_files_this_task_wrote_are_reclaimed(tmp_path) -> None:
    """Same rule as the dumps themselves: this module deletes files, and it
    does so only where it is certain what it is looking at."""
    (tmp_path / "routemaker-20260912T070000Z.dump").write_bytes(b"dump")
    others = ["notes.txt.part", "somebody-elses.dump.part", "routemaker-nonsense.dump.part"]
    for name in others:
        (tmp_path / name).write_bytes(b"not ours")

    prune_backups(tmp_path, keep=7)

    assert sorted(
        entry.name
        for entry in tmp_path.iterdir()
        if entry.name != "routemaker-20260912T070000Z.dump"
    ) == sorted(others)


def test_a_part_file_is_measured_against_the_dumps_that_survive_the_prune(tmp_path) -> None:
    """ "Older than the newest dump still being kept" means the dumps that are
    still there when this returns, not every dump the directory started with.

    The two agree on every call that keeps at least one dump - the newest kept
    dump is the newest dump - and they part company where retention keeps none.
    Measured against the dumps on the way in, a part file older than an archive
    this very call has just deleted reads as wreckage; measured against what
    survives, there is no kept dump to compare it against at all, which is the
    case the rule declines to act on.
    """
    dumps = [f"routemaker-2026091{day}T070000Z.dump" for day in range(1, 4)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")
    part = tmp_path / "routemaker-20260910T070000Z.dump.part"
    part.write_bytes(b"half a dump")

    removed = prune_backups(tmp_path, keep=0)

    assert [path.name for path in removed] == dumps, "keeping none means keeping none"
    assert part.exists(), (
        "with every dump gone there is no kept instant to measure the part file against, "
        "and the part file was compared against a dump this call had already deleted"
    )


def test_a_part_file_at_the_newest_kept_instant_is_left_alone(tmp_path) -> None:
    """The boundary of "older than", which is the live write seen at its own
    instant: `perform_backup` writes `<name>.dump.part` and renames it to
    `<name>.dump`, so a part file carrying the same instant as a kept dump is
    that dump's own staging file, still open. Removing it is retention reaching
    into the write it is running beside.
    """
    dumps = [f"routemaker-2026091{day}T070000Z.dump" for day in range(1, 4)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")
    alongside = tmp_path / "routemaker-20260913T070000Z.dump.part"
    alongside.write_bytes(b"half a dump")

    prune_backups(tmp_path, keep=2)

    assert alongside.exists(), (
        "a part file at the same instant as the newest kept dump was reclaimed; the rule "
        "is strictly older, and equal is the archive being written right now"
    )


def test_a_part_file_older_than_the_newest_kept_dump_goes_even_beside_older_ones(
    tmp_path,
) -> None:
    """Newest kept, not oldest kept. The comparison is against the last of the
    sorted list; read off the front it is the oldest surviving dump, and every
    part file abandoned since then - which is every one a SIGKILL can have left
    while the retention window still had room - is measured as if it were in
    flight and kept for ever.
    """
    dumps = [f"routemaker-2026091{day}T070000Z.dump" for day in range(1, 5)]
    for name in dumps:
        (tmp_path / name).write_bytes(b"dump")
    abandoned = tmp_path / "routemaker-20260913T060000Z.dump.part"
    abandoned.write_bytes(b"half a dump")

    prune_backups(tmp_path, keep=3)

    assert not abandoned.exists(), (
        "a part file older than the newest kept dump - but newer than the oldest - "
        "survived; it is wreckage, and it is a full-sized archive"
    )


def test_a_directory_shaped_like_a_part_file_is_not_unlinked(tmp_path) -> None:
    """This module deletes things, and it does so only where it is certain what
    it is looking at. `unlink` on a directory raises, out of `nightly_backup`,
    after the dump has already been written and proved - so the backup that
    succeeded is reported as a failure, and the next night's run hits the same
    directory again.
    """
    for day in range(1, 4):
        (tmp_path / f"routemaker-2026091{day}T070000Z.dump").write_bytes(b"dump")
    impostor = tmp_path / "routemaker-20260910T070000Z.dump.part"
    impostor.mkdir()
    (impostor / "inside").write_bytes(b"not a dump")

    prune_backups(tmp_path, keep=2)

    assert impostor.is_dir(), "the directory was removed rather than left alone"
    assert (impostor / "inside").exists()
