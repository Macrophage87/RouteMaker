"""The weekly rebuild, as an ordered set of stages.

Written as stages with explicit names because the operational questions asked of
it are all "where did it get to": the alert says a rebuild has not completed in
eight days, and the answer has to be a stage rather than a log scrape.

Nothing here runs the swap; `pipeline.run` supplies the handlers, and the swap
handler is `pipeline.promotion`. The rebuild builds into staging and a dated
tile directory, validates, and only then hands off; a rebuild that validates
badly must leave the live schema and the live tiles exactly as they were.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Stage(Enum):
    """Ordered. A failure is reported as the stage it stopped in.

    The order is load-bearing in two places. Everything derived has to be
    computed before the extract is written, because the tag transform reads it
    at tile build time and a value computed afterwards reaches the graph in no
    way at all - an earlier version classified stress after building tiles, so
    the tiles carried none. And the reference data loads first, because the
    stages after it produce a plausible, wrong map when it is absent rather than
    failing.

    Overrides sit where they do because the three kinds correct three different
    things and each has to land after the stage it corrects and before the stage
    that consumes it: access tags before the extract is written, a stress tier
    after classification, an authority after assignment. One position satisfies
    all three, which is why it is one stage rather than three.
    """

    FETCH_EXTRACT = "fetch_extract"
    LOAD_REFERENCE_DATA = "load_reference_data"
    # With the other inputs, before any derivation: the HGT tiles are cached,
    # but "cached" is checked every week rather than assumed, and a missing or
    # truncated tile fails here rather than after the whole classification has
    # run. The constraint that matters is that it precedes BUILD_TILES, which
    # is the only stage that reads the directory.
    ELEVATION = "elevation"
    CONFLATE_VOLUME = "conflate_volume"
    CLASSIFY_STRESS = "classify_stress"
    TAG_JURISDICTIONS = "tag_jurisdictions"
    APPLY_OVERRIDES = "apply_overrides"
    INSERT_BORDER_NODES = "insert_border_nodes"
    INJECT_TAGS = "inject_tags"
    BUILD_TILES = "build_tiles"
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


class StageNotImplemented(RuntimeError):
    """A stage has no handler and was not declared skipped."""


class RebuildTimedOut(RuntimeError):
    """The deadline passed. Raised before a stage starts, or inside one.

    It carries the stage when the between-stages check is what raised it, and
    that attribute is the whole of the fix for a real silence. The task body
    caught this class by name and abandoned the rebuild with nothing but "the
    time budget ran out", while the same failure arriving from inside a handler
    came wrapped in `RebuildFailed`, which does carry a stage - and the stage is
    what decides whether the swap has already happened. A budget that lapsed at
    the SWAP -> RECONCILE boundary therefore produced an alert that said the
    rebuild ran out of time and said nothing at all about the schema having been
    renamed underneath the running routers, which is the one thing the operator
    reading it has to act on.

    `_run_command` raises it from inside a stage with no stage of its own; the
    handler's own wrapping into `RebuildFailed` supplies it there.
    """

    def __init__(self, message: str, stage: Stage | None = None) -> None:
        super().__init__(message)
        self.stage = stage


def run_rebuild(
    handlers: dict[Stage, Callable[[], None]],
    skip: frozenset[Stage] = frozenset(),
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RebuildReport:
    """Run each stage in order, stopping at the first failure.

    A stage with no handler raises unless it is named in `skip`, and it raises
    *before the first stage runs* rather than when the gap is reached: the
    production handler set once covered eleven of thirteen stages, and the
    weekly job would have spent hours building tiles before discovering that
    nothing would swap them. Silently continuing past a missing handler is
    worse still - it made an omitted stage indistinguishable from a deliberate
    one, and the segments simply had no jurisdiction on them.

    `deadline` is a monotonic-clock instant. It is checked between stages, so a
    rebuild past its budget stops at the next boundary rather than starting the
    swap at hour seven; the binaries a stage runs are given the remaining time
    as their own subprocess timeout by the handler set.

    Stages before the swap are safe to abandon: they write only to staging and to
    a dated tile directory, so a failure leaves the live system untouched and the
    remedy is to drop staging and keep the old tiles. That is why validation sits
    immediately before the swap rather than after it.
    """
    missing = [stage for stage in Stage if stage not in skip and stage not in handlers]
    if missing:
        raise StageNotImplemented(
            "stages with no handler and not declared skipped: "
            + ", ".join(stage.value for stage in missing)
        )

    report = RebuildReport()
    for stage in Stage:
        if stage in skip:
            continue
        handler = handlers[stage]
        if deadline is not None and clock() >= deadline:
            report.failed_at = stage
            raise RebuildTimedOut(
                f"the rebuild's time budget ran out before {stage.value}", stage=stage
            )
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
