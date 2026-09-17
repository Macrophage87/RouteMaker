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

from . import tiles
from .swap import SwapResult, rollback_swap, swap_schemas
from .variants import Variant

logger = logging.getLogger(__name__)


@dataclass
class SwapOutcome:
    build_id: str
    promoted: dict[Variant, str | None] = field(default_factory=dict)
    schema: SwapResult | None = None


def repoint_upstreams(build_id: str, upstreams: Mapping[str, str]) -> dict[str, str]:
    """Write the served build onto every variant's row. Returns what each row
    said before, keyed by variant, so a rollback needs nothing else."""
    from core.models import ValhallaUpstream

    before: dict[str, str] = {}
    for variant in Variant:
        row, _created = ValhallaUpstream.objects.get_or_create(
            variant=variant.value, defaults={"url": upstreams[variant.value]}
        )
        before[variant.value] = row.build_id
        row.previous_build_id = row.build_id
        row.build_id = build_id
        row.url = upstreams[variant.value]
        row.save(update_fields=["previous_build_id", "build_id", "url", "updated_at"])
    return before


def restore_upstreams(before: Mapping[str, str]) -> None:
    from core.models import ValhallaUpstream

    for variant, build_id in before.items():
        ValhallaUpstream.objects.filter(variant=variant).update(
            build_id=build_id, previous_build_id=""
        )


def perform_swap(tiles_dir: Path, build_id: str, upstreams: Mapping[str, str]) -> SwapOutcome:
    """Promote, repoint, rename - and undo whatever was done if a later step fails."""
    outcome = SwapOutcome(build_id=build_id)
    rows_before: dict[str, str] | None = None
    try:
        for variant in Variant:
            outcome.promoted[variant] = tiles.promote(tiles_dir, variant, build_id)
        rows_before = repoint_upstreams(build_id, upstreams)
        outcome.schema = swap_schemas()
    except Exception:
        logger.error("swap failed after promoting %s; undoing", list(outcome.promoted))
        for variant in outcome.promoted:
            tiles.demote(tiles_dir, variant)
        if rows_before is not None:
            restore_upstreams(rows_before)
        raise
    return outcome


def rollback(tiles_dir: Path) -> None:
    """The operator's undo for a completed swap: the reverse of every step.

    Runs the schema rename back first, because that is the step most likely
    to be refused (a rollback that already ran leaves no retired schema), and
    refusing before touching the tiles leaves everything consistent.
    """
    from core.models import ValhallaUpstream

    rollback_swap()
    for variant in Variant:
        tiles.demote(tiles_dir, variant)
        row = ValhallaUpstream.objects.filter(variant=variant.value).first()
        if row is not None:
            row.build_id, row.previous_build_id = row.previous_build_id, ""
            row.save(update_fields=["build_id", "previous_build_id", "updated_at"])
