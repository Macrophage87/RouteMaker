"""Weekly rebuild staging."""

from __future__ import annotations

import pytest

from pipeline.rebuild import PRE_SWAP_STAGES, RebuildFailed, Stage, run_rebuild


def test_stages_run_in_order() -> None:
    seen: list[Stage] = []
    handlers = {stage: (lambda s=stage: seen.append(s)) for stage in Stage}
    report = run_rebuild(handlers)
    assert seen == list(Stage)
    assert report.succeeded


def test_failure_names_its_stage() -> None:
    """The alert says a rebuild has not completed; the answer has to be a stage
    rather than a log scrape."""

    def boom() -> None:
        raise ValueError("tile build ran out of memory")

    handlers = {Stage.FETCH_EXTRACT: lambda: None, Stage.BUILD_TILES: boom}
    with pytest.raises(RebuildFailed) as caught:
        run_rebuild(handlers)
    assert caught.value.stage is Stage.BUILD_TILES
    assert "build_tiles" in str(caught.value)


def test_failure_stops_before_later_stages() -> None:
    """A rebuild that validates badly must leave live exactly as it was."""
    ran: list[Stage] = []

    def boom() -> None:
        raise ValueError("reference route did not reproduce")

    handlers = {
        Stage.VALIDATE: boom,
        Stage.SWAP: lambda: ran.append(Stage.SWAP),
        Stage.RECONCILE: lambda: ran.append(Stage.RECONCILE),
    }
    with pytest.raises(RebuildFailed):
        run_rebuild(handlers)
    assert ran == [], "no stage after a failure may run"


def test_validation_precedes_the_swap() -> None:
    """Everything before the swap writes only to staging and a dated tile
    directory, so it is safe to abandon. Validating after the swap would not be."""
    assert Stage.VALIDATE in PRE_SWAP_STAGES
    assert Stage.SWAP not in PRE_SWAP_STAGES
    assert list(Stage).index(Stage.VALIDATE) == list(Stage).index(Stage.SWAP) - 1


def test_border_nodes_are_inserted_before_tiles_are_built() -> None:
    """Valhalla reads the barrier tag at tile build time; inserting afterwards
    would produce a graph with no border-control nodes in it."""
    order = list(Stage)
    assert order.index(Stage.INSERT_BORDER_NODES) < order.index(Stage.BUILD_TILES)
