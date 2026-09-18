"""The swap, whole: tiles, the settings table, then the schema.

`swap.swap_schemas` is the rename and nothing else; its docstring says the
caller repoints the upstreams first and, until this module existed, there was
no caller. This is the caller. The order is the plan's:

1. Promote each variant's dated build to `current`, so the extract the serving
   container will load on its next start is the new one.
2. Repoint the settings table the API watches, one row per variant, recording
   the build now served and the one before it.
3. Rename staging into live.

so that the inconsistency window is a live segment table describing the older
graph rather than a graph nobody is serving. Anything failing after step 1
undoes the steps already taken, in reverse, before the error is re-raised: a
half-swapped deployment is the one state this module must never leave behind.

Which is what round 4 found this module both leaving and creating, so the undo
is now built out of state captured *before* the first write rather than out of
what each step happened to return:

- the repoint is one transaction, not a loop of saves, so a failure partway
  through it repoints no row at all. It used to leave the rows already written
  naming a build that no tile directory and no schema described - and the
  rebuild's error is retryable, so the half-repoint repeated on every attempt.
- the tile undo restores the links as they were found, including "there was no
  link at all", which is every variant's state before the second rebuild ever
  runs. `demote` moves `previous` back to `current` and there is no `previous`
  on a first rebuild, so the undo used to do nothing.
- the row undo restores the whole row. It used to write
  `previous_build_id=""`, so an undone swap left the row no longer naming the
  build before the one it was serving - the only thing `rollback` reads.
- `rollback` refuses unless there is a complete previous deployment to go back
  to. Its only gate was `rollback_swap`'s "a retired schema exists", which is
  true forever after the first swap, so a rollback after the first-ever swap
  promoted the empty schema that swap had created over the served graph, in
  silence.

Round 5 found the undo itself able to leave one, and the emergency path with
no undo at all:

- every step of the undo is attempted whatever the step before it did. One
  `restore_links` raising used to skip the other two variants and the settings
  rows, so the undo left the half-swapped deployment it exists to prevent. What
  it could not put back is attached to the error being re-raised rather than
  raised in place of it.
- `rollback` captures the links and the rows before it renames anything, and a
  failure partway through its per-variant loop restores them and re-swaps the
  schemas. Before that, a rollback that died on the second variant left one
  variant on last week's tiles and two on this week's, with the schemas already
  rolled back - a state reached by the one command whose purpose is to get out
  of one.

What this does not do, because no phase-1 component can: start the Valhalla
processes against the promoted extract or stop the old ones. valhalla_service
does not reload tiles at runtime, so after a promotion the serving containers
are restarted by the deploy host (`docker compose restart valhalla-<variant>`,
or the host hook that watches `current`). The settings row is what tells the
API which build a restarted container is serving.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from django.db import connection, transaction
from django.utils import timezone

from . import tiles
from .schema import schema_exists, validate_schema_name
from .swap import SwapResult, rollback_swap, swap_schemas
from .variants import Variant

logger = logging.getLogger(__name__)


@dataclass
class SwapOutcome:
    build_id: str
    promoted: dict[Variant, str | None] = field(default_factory=dict)
    schema: SwapResult | None = None


@dataclass(frozen=True)
class UpstreamState:
    """One variant's settings row as it stood before the swap wrote to it.

    `existed` is False for a variant with no row at all, which is every variant
    on a first rebuild. Restoring that state removes the row the repoint
    created, rather than leaving one behind naming no build.
    """

    existed: bool
    url: str
    build_id: str
    previous_build_id: str


class RollbackUnavailable(RuntimeError):
    """There is no complete previous deployment to roll back to."""


def upstream_states(upstreams: Mapping[str, str]) -> dict[str, UpstreamState]:
    """What every variant's row says now, read before anything is written.

    Read separately from the repoint, and before it, because the undo needs it
    whether the repoint finished, failed partway or never ran.
    """
    from core.models import ValhallaUpstream

    rows = {row.variant: row for row in ValhallaUpstream.objects.all()}
    states: dict[str, UpstreamState] = {}
    for variant in Variant:
        row = rows.get(variant.value)
        if row is None:
            states[variant.value] = UpstreamState(
                existed=False, url=upstreams[variant.value], build_id="", previous_build_id=""
            )
        else:
            states[variant.value] = UpstreamState(
                existed=True,
                url=row.url,
                build_id=row.build_id,
                previous_build_id=row.previous_build_id,
            )
    return states


def repoint_upstreams(build_id: str, upstreams: Mapping[str, str]) -> dict[str, UpstreamState]:
    """Write the served build onto every variant's row, all of them or none.

    Returns what each row said before, keyed by variant, so a rollback needs
    nothing else. The transaction is the point: one row per variant written in
    a bare loop meant that a failure on the third left the first two naming a
    build nothing else in the deployment had promoted, in the table the API
    watches, with the swap never made.
    """
    from core.models import ValhallaUpstream

    before = upstream_states(upstreams)
    with transaction.atomic():
        for variant in Variant:
            row, _created = ValhallaUpstream.objects.get_or_create(
                variant=variant.value, defaults={"url": upstreams[variant.value]}
            )
            row.previous_build_id = row.build_id
            row.build_id = build_id
            row.url = upstreams[variant.value]
            row.save(update_fields=["previous_build_id", "build_id", "url", "updated_at"])
    return before


def restore_upstreams(before: Mapping[str, UpstreamState]) -> None:
    """Put every row back exactly as `upstream_states` found it.

    The whole row, not the build id alone. Writing `previous_build_id=""` here
    corrupted the one column `rollback` reads: after two good swaps and one
    undone one, the row no longer named the build before the one it served.
    """
    from core.models import ValhallaUpstream

    with transaction.atomic():
        for variant, state in before.items():
            if not state.existed:
                ValhallaUpstream.objects.filter(variant=variant).delete()
                continue
            ValhallaUpstream.objects.filter(variant=variant).update(
                url=state.url,
                build_id=state.build_id,
                previous_build_id=state.previous_build_id,
                updated_at=timezone.now(),
            )


def restore_everything(
    tiles_dir: Path,
    links_before: Mapping[Variant, tiles.TileLinks],
    rows_before: Mapping[str, UpstreamState],
) -> list[str]:
    """Put the tile links and the settings rows back, every step of it.

    Returns what could not be restored, so the caller can say so on top of the
    failure it is already reporting rather than in place of it. Every variant
    the caller captured is put back, which has to be every variant there is: a
    `promote` that failed between its own two links returned nothing, so that
    variant is in neither the promoted set nor the untouched one, and its
    `previous` is the link that moved.

    Each step is attempted whatever the step before it did. Written as one
    unguarded sequence, the first `restore_links` to raise - a read-only
    volume, a link somebody had replaced with a directory - skipped the other
    two variants and the settings rows with them, which is the half-swapped
    deployment the undo exists to prevent, reached by the undo itself. A
    partial undo is worth having: two variants back on the served build is
    better than none, and the rows are what the API reads.
    """
    failures: list[str] = []
    for variant, state in links_before.items():
        try:
            tiles.restore_links(tiles_dir, variant, state)
        except Exception as error:  # noqa: BLE001 - collected, never swallowed
            failures.append(f"{variant.value}'s tile links ({error})")
            logger.exception("could not restore %s's tile links", variant.value)
    try:
        restore_upstreams(rows_before)
    except Exception as error:  # noqa: BLE001 - same
        failures.append(f"the settings rows ({error})")
        logger.exception("could not restore the settings rows")
    return failures


def _note_undo_failures(error: BaseException, failures: list[str], what: str) -> None:
    """Attach what the undo could not put back to the error being re-raised.

    The original error is what the caller classifies on - the rebuild's retry
    decision reads it, and `RebuildFailed` carries it - so it is raised as
    itself rather than replaced by a report about the undo. The note is how the
    operator finds out that this deployment needs a hand before the next
    attempt.
    """
    if not failures:
        return
    message = f"{what} could not restore " + "; ".join(failures)
    logger.error("%s", message)
    error.add_note(message)


def perform_swap(tiles_dir: Path, build_id: str, upstreams: Mapping[str, str]) -> SwapOutcome:
    """Promote, repoint, rename - and undo whatever was done if a later step fails."""
    outcome = SwapOutcome(build_id=build_id)
    links_before = {variant: tiles.links(tiles_dir, variant) for variant in Variant}
    rows_before = upstream_states(upstreams)
    try:
        for variant in Variant:
            outcome.promoted[variant] = tiles.promote(tiles_dir, variant, build_id)
        repoint_upstreams(build_id, upstreams)
        outcome.schema = swap_schemas()
    except Exception as error:
        logger.error("swap failed after promoting %s; undoing", list(outcome.promoted))
        # Every variant, not only the ones `promote` returned for: a promotion
        # that failed between its own two links is in neither set, and its
        # `previous` is the link that moved.
        _note_undo_failures(
            error, restore_everything(tiles_dir, links_before, rows_before), "the swap's undo"
        )
        raise
    return outcome


def _retired_holds_a_graph(retired: str) -> bool:
    """Whether the retired schema is a graph or the empty one a swap created.

    `swap_schemas` creates an empty live schema on a fresh deployment so that
    the first rename has something to move out of the way, and that empty
    schema is what the first swap retires. Rolling back to it is how a
    five-segment live table became a zero-segment one with nothing raised.
    """
    validate_schema_name(retired)
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [f"{retired}.segment"])
        if cursor.fetchone()[0] is None:
            return False
        # Whether there is a row, not how many: counting a retired graph is a
        # sequential scan over a few million rows to answer a question the
        # first one settles.
        cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {retired}.segment LIMIT 1)")
        return cursor.fetchone()[0]


def rollback_target(tiles_dir: Path) -> dict[Variant, str]:
    """The build each variant would go back to, or a refusal naming what is missing.

    `rollback_swap`'s own gate is that a retired schema exists, which is true
    forever after the first swap and says nothing about whether that schema,
    those tiles and those rows describe one deployment that was once served. So
    this checks all three parts of a previous build - the settings rows, the
    `previous` tile links, and a retired schema with a graph in it - and
    refuses before anything has been renamed or moved.
    """
    from django.conf import settings

    from core.models import ValhallaUpstream

    rows = {row.variant: row for row in ValhallaUpstream.objects.all()}
    target: dict[Variant, str] = {}
    missing: list[str] = []
    for variant in Variant:
        row = rows.get(variant.value)
        if row is None:
            missing.append(f"{variant.value} has no settings row")
            continue
        if not row.previous_build_id:
            missing.append(f"{variant.value}'s settings row names no previous build")
            continue
        link = tiles.promoted_build_id(tiles_dir, variant, tiles.PREVIOUS)
        if link is None:
            missing.append(f"{variant.value} has no previous tile directory")
            continue
        if link != row.previous_build_id:
            missing.append(
                f"{variant.value}'s previous tiles are {link} and its settings row "
                f"names {row.previous_build_id}"
            )
            continue
        target[variant] = row.previous_build_id

    retired = settings.SEGMENT_SCHEMA_RETIRED
    if not schema_exists(retired):
        missing.append(f"there is no {retired} schema")
    elif not _retired_holds_a_graph(retired):
        missing.append(f"{retired} holds no segments")

    if missing:
        raise RollbackUnavailable(
            "refusing to roll back: there is no previous build to go back to - "
            + "; ".join(missing)
        )
    return target


def rollback(tiles_dir: Path) -> None:
    """The operator's undo for a completed swap: the reverse of every step.

    Refuses unless every part of a previous deployment is there to go back to,
    and refuses before touching anything. Without that check its only gate was
    `rollback_swap`'s retired schema, so a rollback after the first-ever swap
    promoted that swap's empty schema over the served graph - live went from
    five segments to none, every settings row was blanked, the tiles were left
    where they were, and nothing was raised - while a rollback after a rebuild
    that failed at the swap died halfway through the rename.

    Runs the schema rename first of the three, because it is the step most
    likely to be refused by something this process cannot see, and being
    refused there leaves everything consistent.

    And it has the same undo the forward path has, built the same way, out of
    state captured before the first write. `rollback_target` pre-validates
    everything about the deployment that can be pre-validated - the rows, the
    links, the retired schema - but a symlink write on a full or read-only
    volume cannot be, and a rollback that died on the second variant left the
    schemas rolled back, one variant on last week's tiles and two on this
    week's, and one settings row rewritten: a deployment in a state no rollback
    and no rebuild can reason about, reached by the command whose whole purpose
    is to get out of one. So a failure in the loop puts the links and the rows
    back and re-swaps the schemas, which returns the deployment to the state
    the operator ran this from.
    """
    from django.conf import settings

    from core.models import ValhallaUpstream

    target = rollback_target(tiles_dir)
    links_before = {variant: tiles.links(tiles_dir, variant) for variant in Variant}
    rows_before = upstream_states(settings.VALHALLA_UPSTREAMS)
    rollback_swap()
    try:
        for variant in Variant:
            tiles.demote(tiles_dir, variant)
            ValhallaUpstream.objects.filter(variant=variant.value).update(
                build_id=target[variant], previous_build_id="", updated_at=timezone.now()
            )
    except Exception as error:
        logger.error("the rollback failed partway; putting the deployment back")
        failures = restore_everything(tiles_dir, links_before, rows_before)
        try:
            # The exact reverse of `rollback_swap`: it renamed live to staging
            # and the retired schema to live, and this renames live back to
            # retired and staging back to live. The deployment is serving the
            # build it was serving before the command was run.
            swap_schemas()
        except Exception as schema_error:  # noqa: BLE001 - collected, never swallowed
            failures.append(f"the schemas ({schema_error})")
            logger.exception("could not put the schemas back after a failed rollback")
        _note_undo_failures(error, failures, "the rollback's undo")
        raise
