"""The weekly rebuild, as an ordered set of stages.

Written as stages with explicit names because the operational questions asked of
it are all "where did it get to": the alert says a rebuild has not completed in
eight days, and the answer has to be a stage rather than a log scrape.

Nothing here runs the swap. The rebuild builds into staging, validates against
the reference routes, and only then hands off; a rebuild that validates badly
must leave the live schema and the live tiles exactly as they were.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Stage(Enum):
    """Ordered. A failure is reported as the stage it stopped in."""

    FETCH_EXTRACT = "fetch_extract"
    INJECT_TAGS = "inject_tags"
    INSERT_BORDER_NODES = "insert_border_nodes"
    BUILD_TILES = "build_tiles"
    CLASSIFY_STRESS = "classify_stress"
    TAG_JURISDICTIONS = "tag_jurisdictions"
    WRITE_SEGMENTS = "write_segments"
    VALIDATE = "validate"
    SWAP = "swap"
    RECONCILE = "reconcile"


class RebuildFailed(RuntimeError):
    def __init__(self, stage: Stage, cause: Exception) -> None:
        super().__init__(f"rebuild failed at stage {stage.value}: {cause}")
        self.stage = stage
        self.cause = cause


@dataclass
class RebuildReport:
    completed: list[Stage] = field(default_factory=list)
    failed_at: Stage | None = None

    @property
    def succeeded(self) -> bool:
        return self.failed_at is None and Stage.RECONCILE in self.completed


def run_rebuild(handlers: dict[Stage, Callable[[], None]]) -> RebuildReport:
    """Run each stage in order, stopping at the first failure.

    Stages before the swap are safe to abandon: they write only to staging and to
    a dated tile directory, so a failure leaves the live system untouched and the
    remedy is to drop staging and keep the old tiles. That is why validation sits
    immediately before the swap rather than after it.
    """
    report = RebuildReport()
    for stage in Stage:
        handler = handlers.get(stage)
        if handler is None:
            continue
        try:
            handler()
        except Exception as error:  # noqa: BLE001 - wrapped and re-raised
            report.failed_at = stage
            logger.error("rebuild failed at stage %s", stage.value, exc_info=error)
            raise RebuildFailed(stage, error) from error
        report.completed.append(stage)
    return report


def stages_before(stage: Stage) -> list[Stage]:
    """Stages that run before the given one, in order."""
    ordered = list(Stage)
    return ordered[: ordered.index(stage)]


PRE_SWAP_STAGES = tuple(stages_before(Stage.SWAP))
