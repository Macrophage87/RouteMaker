"""What the weekly rebuild and the nightly backup leave behind, and when it goes.

Both of them write to the data volume every time they run and neither one ever
removed anything: one dated tile directory per week and one dump per night, kept
forever, on the volume the rebuild's own disk gate measures. The gate is a hard
refusal - a rebuild that cannot fit two full tile sets does not start - so the
end state of "keep everything" is not a full disk with a warning on it, it is a
rebuild that refuses every week with "grow the volume" as the only remedy
available to the operator. Retention is what keeps the gate a gate.

The rule for tiles is the plan's own sizing: the volume carries two full sets,
the one being served and the one a rollback would put back. So two dated builds
survive here, and the two symlinks are consulted rather than assumed - whatever
`current` and `previous` point at is kept whatever its age, because those are
the served graph and the rollback target and deleting either is the outage this
module exists to avoid.

Nothing here reads the database or Django settings: it takes the directory it is
pointed at. That is what lets the rebuild call it between stages and the backup
call it from the worker, and what lets a test hand it a temporary directory.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .tiles import CURRENT, PREVIOUS

logger = logging.getLogger(__name__)

# Two full sets, which is what the plan sizes the data volume for: the set being
# served and the set a rollback would put back. A third is scratch that no
# procedure in the plan reads.
KEEP_BUILDS = 2

# A dated build directory, as `new_build_id` writes it, optionally with the
# disambiguating suffix `unique_build_id` adds for a second build inside the
# same second. Anything else under a variant directory is left alone: this
# module deletes trees, and it does so only where it is certain what it is
# looking at.
BUILD_ID = re.compile(r"^\d{8}T\d{6}Z(-\d+)?$")

BUILD_ID_FORMAT = "%Y%m%dT%H%M%SZ"

# The dumps `perform_backup` writes, by name.
DUMP_NAME = re.compile(r"^routemaker-\d{8}T\d{6}Z\.dump$")


def unique_build_id(now: datetime, existing: object = ()) -> str:
    """A build id that is not already taken.

    Build ids are second-resolution because they are directory names an operator
    reads, and second resolution is enough for a weekly job right up until it is
    not: a rebuild deferred twice in the same second, a retry landing inside the
    same second as its first attempt, a test that fires two builds in a row. Two
    builds sharing an id share a directory, so the second writes tiles into the
    first's tree and `previous` ends up pointing at a mixture of the two - and
    that mixture is the rollback target.

    So the second one takes a suffix. It keeps the same sort order as the plain
    id (the suffix sorts after the bare form for the same second, and every
    later second sorts after both), which is what the pruning below relies on.
    """
    taken = {str(name) for name in existing}
    base = now.strftime(BUILD_ID_FORMAT)
    if base not in taken:
        return base
    for suffix in range(1, 1000):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"a thousand builds already carry the id {base}")


def taken_build_ids(tiles_dir: Path | str) -> set[str]:
    """Every build id that already has a directory under any variant.

    What `unique_build_id` needs to be handed to mean anything. Across all
    variants rather than one, because a build id names one rebuild and the same
    id is the directory name under every variant it writes.
    """
    root = Path(tiles_dir)
    if not root.is_dir():
        return set()
    return {
        entry.name
        for variant in root.iterdir()
        if variant.is_dir() and not variant.is_symlink()
        for entry in variant.iterdir()
        if entry.is_dir() and not entry.is_symlink() and BUILD_ID.match(entry.name)
    }


def prune_builds(
    variant_root: Path | str, keep: int = KEEP_BUILDS, protect: Iterable[str] = ()
) -> list[str]:
    """Remove all but the newest `keep` dated builds under one variant.

    What `current` and `previous` point at is never removed, whatever its age
    and whatever `keep` is. That is not a refinement of the newest-N rule, it
    replaces it where the two disagree: a rollback that has just put last week's
    build back makes `current` the *older* directory, and a newest-N rule would
    delete the graph being served on the next rebuild.

    `protect` names build ids kept for a reason of the caller's own. The
    rebuild names the build it has just written, which no symlink points at
    when the run failed - and which is not always the newest directory either,
    because `unique_build_id` hands out the first free suffix inside a second
    and a freed one can be handed out again. "Keep the newest as well" was the
    first form of that rule and it kept the wrong directory the moment a
    suffix was reused.

    Returns the build ids removed, oldest first, so a caller can record them.
    """
    root = Path(variant_root)
    if not root.is_dir():
        return []

    protected = {target for target in (_link_target(root, CURRENT), _link_target(root, PREVIOUS))}
    protected |= set(protect)
    builds = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and not entry.is_symlink() and BUILD_ID.match(entry.name)
    )
    keepable = set(builds[len(builds) - max(keep, 0) :]) if keep > 0 else set()
    removed = []
    for build in builds:
        if build in keepable or build in protected:
            continue
        shutil.rmtree(root / build)
        removed.append(build)
    if removed:
        logger.info("pruned %d old build directories under %s: %s", len(removed), root, removed)
    return removed


def prune_tile_builds(
    tiles_dir: Path | str, keep: int = KEEP_BUILDS, protect: Iterable[str] = ()
) -> dict[str, list[str]]:
    """`prune_builds` for every variant directory under the tiles root.

    Variants are read off the filesystem rather than from the variant enum, so a
    variant that has been renamed or retired still has its old directory pruned
    instead of being kept forever by the one mechanism that could remove it.
    """
    root = Path(tiles_dir)
    if not root.is_dir():
        return {}
    protect = set(protect)
    return {
        variant.name: prune_builds(variant, keep=keep, protect=protect)
        for variant in sorted(root.iterdir())
        if variant.is_dir() and not variant.is_symlink()
    }


def prune_backups(backup_dir: Path | str, keep: int) -> list[Path]:
    """Keep the newest `keep` dumps and remove the rest, newest by name.

    By name rather than by mtime: the name carries the UTC instant the dump was
    started, which is the thing being retained, and it survives a restore, a
    copy, and a volume snapshot being brought back - all of which rewrite mtime
    and none of which should change which dump is the newest. Files that are not
    dumps this task wrote are not touched.
    """
    directory = Path(backup_dir)
    if not directory.is_dir():
        return []
    dumps = sorted(
        (entry for entry in directory.iterdir() if entry.is_file() and DUMP_NAME.match(entry.name)),
        key=lambda entry: entry.name,
    )
    doomed = dumps[: max(len(dumps) - max(keep, 0), 0)]
    for dump in doomed:
        dump.unlink()
    if doomed:
        logger.info("pruned %d old dumps from %s", len(doomed), directory)
    return doomed


def _link_target(root: Path, link: str) -> str | None:
    """The build id a promotion symlink names, or None if there is no link.

    `promote` writes the target as a bare build id, so the link's own text is
    the id. It is read with `readlink` rather than `resolve` so that a dangling
    link - a `previous` whose directory a previous version of this code removed
    - still protects the name rather than raising.
    """
    path = root / link
    if not path.is_symlink():
        return None
    return os.path.basename(os.readlink(path))
