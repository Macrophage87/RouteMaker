"""The periodic tasks the worker actually runs.

Three versions of this file, three ways of not testing the worker. The first
asserted the cron strings and nothing else, while no task was registered. The
second asserted registration, and monkeypatched `run_rebuild` in the one test
meant to prove the rebuild was wired - stubbing out the one function that
would have noticed the handler set could not run. And both called the task
functions from inside pytest, where conftest had already set Django up, so a
worker that died on a missing schema and raised AppRegistryNotReady on every
job passed them all.

So: the rebuild task runs its real handler set with only the binaries stood
in for; a worker is started cold in a subprocess, as compose starts it, and
runs a deferred job; and the timeouts, retries and backup verification are
exercised rather than restated.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from procrastinate.jobs import Job
from rebuild_fixtures import (
    REPO,
    FakeBinaries,
    build_toy_extract,
    fake_fetch,
    state_polygons,
    write_reference_data,
)

from config.procrastinate import (
    BACKUP_KEEP,
    BACKUP_TIMEOUT_S,
    DEGRADED_GUILD_SWEEP_CRON,
    MEMBERSHIP_SWEEP_CRON,
    NIGHTLY_BACKUP_CRON,
    REBUILD_TIMEOUT_S,
    ROUTER_RESTART_NOTICE,
    SWEEP_TIMEOUT_S,
    WEEKLY_REBUILD_CRON,
    WORKER_HEARTBEAT_CRON,
    BackupTimedOut,
    RebuildAbandoned,
    app,
    verify_dump_listing,
)

REBUILD_ALERT_AFTER_S = 8 * 24 * 60 * 60


@pytest.fixture
def states():
    yield from state_polygons()


def registered() -> dict[str, str]:
    """Registered periodic tasks, as {task name: cron}."""
    return {
        name: periodic.cron
        for (name, _periodic_id), periodic in app.periodic_registry.periodic_tasks.items()
    }


def test_each_cron_constant_has_a_task_behind_it() -> None:
    """A schedule nothing is registered against is a comment."""
    assert registered() == {
        "weekly_rebuild": WEEKLY_REBUILD_CRON,
        "nightly_backup": NIGHTLY_BACKUP_CRON,
        "membership_sweep": MEMBERSHIP_SWEEP_CRON,
        "degraded_guild_sweep": DEGRADED_GUILD_SWEEP_CRON,
        "worker_heartbeat": WORKER_HEARTBEAT_CRON,
    }


def test_the_rebuild_cannot_run_twice_at_once() -> None:
    """Two concurrent rebuilds would write the same staging schema and the same
    tile directory."""
    rebuild = app.tasks["weekly_rebuild"]
    assert rebuild.queueing_lock == "weekly_rebuild"
    assert rebuild.queue == "rebuild", "a six-hour build must not sit in front of the sweep"


def test_the_maintenance_tasks_share_a_queue_away_from_the_rebuild() -> None:
    for name in ("nightly_backup", "membership_sweep", "degraded_guild_sweep", "worker_heartbeat"):
        assert app.tasks[name].queue == "maintenance"
        assert app.tasks[name].queueing_lock == name


# --- The rebuild task, with its real handlers -----------------------------------------


@pytest.fixture
def rebuild_environment(monkeypatch, tmp_path, segment_schemas):
    """What the weekly task finds on a deployed box, in a temporary directory,
    with only the binaries and the 3DEP download stood in for. The disk gate
    measures the real volume, so every host-sized input to it is neutralised:
    the floor, the download estimate the gate sizes a refresh from (four times
    2 GiB, more than a tmpfs /tmp holds - Ubuntu 26.04's default), and the
    fullness fraction, which otherwise refuses whenever the shared /tmp under
    tmp_path is past 80% used. The gate's own refusals are tested elsewhere."""
    source = tmp_path / "extracts" / "source.osm.pbf"
    source.parent.mkdir()
    build_toy_extract(source)
    write_reference_data(tmp_path, urban=(100, 200, 300, 400, 500))
    monkeypatch.setattr(settings, "REBUILD_SOURCE_PBF", source)
    monkeypatch.setattr(settings, "REBUILD_WORK_DIR", tmp_path / "rebuild")
    monkeypatch.setattr(settings, "REBUILD_REFERENCE_DIR", tmp_path / "reference")
    monkeypatch.setattr(settings, "TILES_DIR", tmp_path / "tiles")
    monkeypatch.setattr(settings, "ELEVATION_DIR", tmp_path / "elevation")
    monkeypatch.setattr(settings, "REBUILD_MIN_FREE_BYTES", 0)
    monkeypatch.setattr(settings, "DISK_GATE_FRACTION", 1.0)
    monkeypatch.setattr("pipeline.source.ESTIMATED_BYTES", source.stat().st_size)

    binaries = FakeBinaries()
    monkeypatch.setattr(
        "pipeline.run._run_command", lambda command, deadline=None, clock=None: binaries(command)
    )
    monkeypatch.setattr("pipeline.elevation.fetch_3dep", fake_fetch)
    return tmp_path, binaries


@pytest.mark.django_db(transaction=True)
def test_the_rebuild_task_runs_the_real_handler_set(rebuild_environment, states) -> None:
    """The registered callable, exactly as the worker calls it: no samplers
    injected, no handlers replaced, nothing skipped. Every stage runs, the
    swap promotes, and the run row records it."""
    from core.models import DriftReport, ScheduledRun, ValhallaUpstream

    root, binaries = rebuild_environment
    app.tasks["weekly_rebuild"].func(timestamp=0)

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert run.succeeded and run.finished_at is not None
    assert "14 stages completed" in run.detail
    # The promotion is not the end of the deployment's work and the row says so:
    # valhalla_service does not reload tiles at runtime, so the three routers go
    # on serving the build they started against until their containers restart,
    # and nothing in phase 1 restarts them.
    assert (
        "docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike" in run.detail
    ), f"the run that promoted a build must say what still has to happen: {run.detail}"

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {settings.SEGMENT_SCHEMA_LIVE}.segment")
        assert cursor.fetchone()[0] == 5
        cursor.execute(f"SELECT count(*) FROM {settings.SEGMENT_SCHEMA_LIVE}.border_crossing")
        assert cursor.fetchone()[0] == 1
    assert ValhallaUpstream.objects.count() == 3
    assert DriftReport.objects.count() == 1
    build_id = ValhallaUpstream.objects.get(variant="standard").build_id
    assert os.readlink(root / "tiles" / "standard" / "current") == build_id
    assert len(binaries.commands("valhalla_build_tiles")) == 3
    assert len(binaries.commands("valhalla_service")) == 4, "three grade reads and one tag read"
    assert (root / "elevation" / "N38" / "N38W078.hgt").is_file()


@pytest.mark.django_db(transaction=True)
def test_the_run_row_says_which_approved_overrides_were_in_force(
    rebuild_environment, states, caplog
) -> None:
    """The override report reaches the row an operator reads first, and the log.

    It was assigned every week and read by nothing, so a rebuild in which an
    approved correction matched no way in the new extract - an OSM edit split
    or renumbered the way - succeeded with a run row that said nothing about
    it. Two approved rows, one matching a toy-extract way and one matching
    none, and an unapproved row that must not count at all.
    """
    import logging
    import re

    from core.models import Override, ScheduledRun
    from pipeline.overrides import OverrideReport

    for way_id, approved in ((100, True), (424242, True), (200, False)):
        Override.objects.create(
            kind="stress",
            osm_way_id=way_id,
            value={"tier": 1, "reason": "field check"},
            reason="field check",
            evidence="surveyed",
            approved=approved,
        )

    with caplog.at_level(logging.INFO, logger="pipeline.run"):
        app.tasks["weekly_rebuild"].func(timestamp=0)

    expected = OverrideReport(stress=1, unmatched_way_ids=(424242,)).summary()
    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert run.succeeded
    assert expected in run.detail, run.detail
    assert expected in caplog.messages, "and the rebuild log carries the same line"
    # Read back from the row itself, not only compared with summary(): the one
    # override in force was a stress one, and the row must say so.
    read_back = {
        label: [int(n) for n in re.findall(rf"(\d+) {label}\b", run.detail)]
        for label in ("access", "stress", "jurisdiction", "approved rows matched no way")
    }
    assert read_back == {
        "access": [0],
        "stress": [1],
        "jurisdiction": [0],
        "approved rows matched no way": [1],
    }, run.detail


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_that_cannot_start_records_the_failure_and_is_not_retried(
    rebuild_environment, monkeypatch
) -> None:
    """The row is for the alert that notices nothing has succeeded lately.
    Whether this attempt failed is Procrastinate's question, so the error goes
    back to it - but as RebuildAbandoned, which the retry strategy does not
    retry, because a missing extract is the same on the fifth attempt."""
    from core.models import ScheduledRun

    root, _binaries = rebuild_environment
    monkeypatch.setattr(settings, "REBUILD_SOURCE_PBF", root / "absent.osm.pbf")

    with pytest.raises(RebuildAbandoned, match="source extract missing"):
        app.tasks["weekly_rebuild"].func(timestamp=0)

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert not run.succeeded
    assert "source extract missing" in run.detail


def job(attempts: int) -> Job:
    return Job(
        queue="rebuild",
        lock=None,
        queueing_lock="weekly_rebuild",
        task_name="weekly_rebuild",
        task_kwargs={},
        attempts=attempts,
    )


def test_jobs_are_retried_with_exponential_backoff_up_to_five_times() -> None:
    """The plan's rule, asserted as the schedule the strategy produces rather
    than as the constants it was built from. Procrastinate increments
    `attempts` after the retry decision (in finish_job and retry_job, never in
    fetch), so the first failure is judged at attempts=0 and the sixth at
    attempts=5: one run, five retries, each wait six times the last."""
    from pipeline.rebuild import RebuildFailed, Stage

    transient = RebuildFailed(Stage.FETCH_EXTRACT, OSError("connection reset"))
    for name in ("weekly_rebuild", "nightly_backup", "membership_sweep"):
        strategy = app.tasks[name].retry_strategy
        assert strategy is not None, f"{name} is never retried"
        waits = []
        for finished_runs in range(0, 8):
            asked_at = timezone.now()
            decision = strategy.get_retry_decision(exception=transient, job=job(finished_runs))
            if decision is None:
                break
            waits.append(round((decision.retry_at - asked_at).total_seconds()))
        assert waits == [6, 36, 216, 1296, 7776], f"{name}: {waits}"
        assert finished_runs == 5, f"{name}: retrying stopped after {finished_runs} runs, not 5"
        assert sum(waits) < 3 * 60 * 60, "every retry lands within the same morning"


def test_a_rebuild_abandoned_for_a_terminal_cause_is_not_retried() -> None:
    """Validation, missing reference data and the disk gate are the same on
    the fifth attempt as on the first; retrying them is thirty hours of CPU for
    the same alert."""
    strategy = app.tasks["weekly_rebuild"].retry_strategy
    abandoned = RebuildAbandoned("rebuild failed at stage validate: ...")
    assert strategy.get_retry_decision(exception=abandoned, job=job(0)) is None


VARIANTS = ("standard", "no-trail", "ebike")


def builds_on_disk(root, variant: str) -> list[str]:
    """The dated build directories under one variant, oldest first."""
    return sorted(
        entry.name for entry in (root / "tiles" / variant).iterdir() if not entry.is_symlink()
    )


def last_rebuild_detail():
    from core.models import ScheduledRun

    return ScheduledRun.objects.filter(task="weekly_rebuild").order_by("-started_at")[0].detail


@pytest.mark.django_db(transaction=True)
def test_the_rebuild_prunes_the_build_directories_it_has_retired(rebuild_environment) -> None:
    """One dated tile set per week, kept forever, on the volume whose disk gate
    refuses a rebuild that cannot fit two of them. Nothing removed them, so the
    gate's own remedy - "grow the volume" - was the only one left.

    Two rules, in one run each. A build no promotion symlink names is scratch
    and goes at the start of the next rebuild, before the gate is consulted;
    the two the symlinks do name - the served graph and the rollback target,
    which is what the plan sizes the volume for - survive whatever their age.
    """
    root, _binaries = rebuild_environment
    stale = ["20260901T080000Z", "20260908T080000Z", "20260915T080000Z"]
    for variant in VARIANTS:
        for build in stale:
            (root / "tiles" / variant / build / "tiles").mkdir(parents=True)

    app.tasks["weekly_rebuild"].func(timestamp=0)

    for variant in VARIANTS:
        remaining = builds_on_disk(root, variant)
        assert remaining == [os.readlink(root / "tiles" / variant / "current")], (
            f"{variant}: nothing but the build just promoted, since no symlink named the rest"
        )
    assert "pruned 9 old build directories" in last_rebuild_detail()

    app.tasks["weekly_rebuild"].func(timestamp=0)

    for variant in VARIANTS:
        variant_dir = root / "tiles" / variant
        remaining = builds_on_disk(root, variant)
        assert len(remaining) == 2, f"{variant}: two full sets, no more"
        assert os.readlink(variant_dir / "current") == remaining[-1]
        assert os.readlink(variant_dir / "previous") == remaining[0], "the rollback target stays"
    assert "pruned 0 old build directories" in last_rebuild_detail()


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_the_gate_would_refuse_prunes_before_the_gate_reads_the_volume(
    rebuild_environment, monkeypatch
) -> None:
    """The disk gate is terminal, and retention used to sit downstream of it.

    So the first week the volume was too full for a second tile set, the gate
    refused - and the only mechanism that could have freed the space ran after
    the gate, which means it never ran again. The refusal repeated every week
    with prunable builds sitting on the volume and "grow the volume" as the
    only remedy the operator was offered. The prune runs first now, and it is
    safe there by construction: it never removes what `current` or `previous`
    names.

    The gate here is stood in for by one that measures what is on the volume
    against a budget, because the real one measures the developer's own disk.
    """
    from pipeline import tiles

    root, _binaries = rebuild_environment
    a_set = 4096
    # Room for the two sets the volume is sized for and not a byte more, so the
    # three that are on it refuse the gate and the two the prune leaves do not.
    budget = 2 * len(VARIANTS) * a_set
    for variant in VARIANTS:
        for build in ("20260901T080000Z", "20260908T080000Z", "20260915T080000Z"):
            directory = root / "tiles" / variant / build
            directory.mkdir(parents=True)
            (directory / "tiles.tar").write_bytes(b"x" * a_set)

    def gate_with_a_budget(tiles_dir, source_bytes, minimum_free, fraction, disk_usage=None):
        used = tiles.directory_bytes(Path(tiles_dir))
        if used > budget:
            raise tiles.DiskGateRefused(
                f"a second tile set does not fit in the {budget} bytes this volume has; "
                "grow the volume, which is an online resize."
            )
        return tiles.DiskGate(budget, used, budget - used, 0, 0.0)

    monkeypatch.setattr("pipeline.tiles.check_disk_gate", gate_with_a_budget)

    app.tasks["weekly_rebuild"].func(timestamp=0)

    detail = last_rebuild_detail()
    assert "14 stages completed" in detail, detail
    assert "pruned 9 old build directories" in detail
    for variant in VARIANTS:
        assert builds_on_disk(root, variant) == [
            os.readlink(root / "tiles" / variant / "current")
        ], f"{variant}: the stale sets the gate was refusing over are gone"


@pytest.mark.django_db(transaction=True)
def test_only_the_newest_failed_builds_directory_survives_its_run(
    rebuild_environment, monkeypatch
) -> None:
    """A rebuild that dies after BUILD_TILES leaves a third tile set behind.

    Nothing removed it: the prune ran after `run_rebuild` returned, and a
    failure never returns - so the orphan sat beside the two full sets the
    volume is sized for until the *second* following success, and a second
    failed week put a fourth set there. The rule is written down in
    docs/OPERATIONS.md and pinned here: one failed build's directory survives,
    because there has to be something to look at, and the run after it takes
    that one back as it goes out.
    """
    from pipeline.rebuild import Stage
    from pipeline.retention import KEEP_BUILDS
    from pipeline.run import ValidationFailed

    root, _binaries = rebuild_environment

    app.tasks["weekly_rebuild"].func(timestamp=0)
    app.tasks["weekly_rebuild"].func(timestamp=0)
    served = {variant: builds_on_disk(root, variant) for variant in VARIANTS}
    assert all(len(builds) == KEEP_BUILDS for builds in served.values())

    from pipeline import run as pipeline_run

    checked = pipeline_run.assert_elevation_reached_the_tiles
    refusing = {"now": True}

    def refuse_validation(*read_back) -> None:
        if refusing["now"]:
            raise ValidationFailed("the elevation never reached the tiles")
        checked(*read_back)

    monkeypatch.setattr("pipeline.run.assert_elevation_reached_the_tiles", refuse_validation)

    with pytest.raises(RebuildAbandoned) as abandoned:
        app.tasks["weekly_rebuild"].func(timestamp=0)
    assert Stage.VALIDATE.value in str(abandoned.value)

    first_failure = {}
    for variant in VARIANTS:
        remaining = builds_on_disk(root, variant)
        assert len(remaining) == KEEP_BUILDS + 1, f"{variant}: {remaining}"
        assert remaining[:KEEP_BUILDS] == served[variant], "neither served set was touched"
        first_failure[variant] = remaining[-1]
        assert (root / "tiles" / variant / remaining[-1] / "tiles.tar").is_file(), (
            "the failed build's tiles are still there to look at"
        )
        assert os.readlink(root / "tiles" / variant / "current") == served[variant][-1]

    # A second failed week. The volume must not now be carrying four sets: the
    # week before's failed build has been looked at or it never will be.
    with pytest.raises(RebuildAbandoned):
        app.tasks["weekly_rebuild"].func(timestamp=0)

    for variant in VARIANTS:
        remaining = builds_on_disk(root, variant)
        assert len(remaining) == KEEP_BUILDS + 1, f"{variant}: {remaining}"
        assert first_failure[variant] not in remaining, "only the newest failure is kept"
        assert remaining[:KEEP_BUILDS] == served[variant]

    refusing["now"] = False
    app.tasks["weekly_rebuild"].func(timestamp=0)

    for variant in VARIANTS:
        remaining = builds_on_disk(root, variant)
        assert len(remaining) == KEEP_BUILDS, f"{variant}: {remaining}"
        assert os.readlink(root / "tiles" / variant / "current") == remaining[-1]
        assert os.readlink(root / "tiles" / variant / "previous") == remaining[0]


@pytest.mark.django_db(transaction=True)
def test_a_failure_after_the_swap_is_not_retried_and_the_retired_schema_survives(
    rebuild_environment, monkeypatch
) -> None:
    """A reconcile that fails is an ordinary error, and retrying it was fatal.

    The retry re-runs the whole rebuild including SWAP, and SWAP begins with
    `DROP SCHEMA live_old CASCADE` - the schema a rollback puts back. So a
    reconciliation that hit a database hiccup would have destroyed the
    rollback target on its way to reporting the same error five more times,
    over a deployment that was already serving the new build correctly.
    """
    from core.models import ScheduledRun
    from pipeline.schema import schema_exists

    _root, _binaries = rebuild_environment

    app.tasks["weekly_rebuild"].func(timestamp=0)
    assert schema_exists(settings.SEGMENT_SCHEMA_RETIRED)
    succeeded = ScheduledRun.objects.get(task="weekly_rebuild")
    assert ROUTER_RESTART_NOTICE in succeeded.detail

    def dropped_connection(*args, **kwargs):
        raise RuntimeError("the connection dropped while reading the retired schema")

    monkeypatch.setattr("pipeline.reconcile.drift_report", dropped_connection)
    with pytest.raises(RebuildAbandoned) as abandoned:
        app.tasks["weekly_rebuild"].func(timestamp=0)
    message = str(abandoned.value)
    assert "swap completed" in message
    assert settings.SEGMENT_SCHEMA_RETIRED in message
    # What the operator has to do, in the alert that is the only thing they see.
    # The message used to say "the new build is being served" and stop there,
    # which is false at the moment it is written: the schema rename is instant
    # and the tile directories are not, so the three routers are still serving
    # last week's graph against this week's segment rows until somebody restarts
    # them - and an operator told the new build is being served has no reason to.
    # The same sentence as the success detail, from the same constant, so the
    # two cannot drift apart.
    assert ROUTER_RESTART_NOTICE in message, (
        f"the abandoned rebuild must name the router restart: {message}"
    )
    assert "being served" not in message, (
        f"and must not say the new build is already being served: {message}"
    )
    assert "reconciliation by hand" in message, (
        f"the reconcile does not happen on its own either: {message}"
    )

    strategy = app.tasks["weekly_rebuild"].retry_strategy
    assert strategy.get_retry_decision(exception=abandoned.value, job=job(0)) is None, (
        "a retry would re-run the swap over a deployment that has already swapped"
    )
    assert schema_exists(settings.SEGMENT_SCHEMA_RETIRED), "the rollback target is still there"
    assert (
        not ScheduledRun.objects.filter(task="weekly_rebuild").order_by("-started_at")[0].succeeded
    )


def test_the_stages_after_the_swap_are_the_ones_after_it_and_not_the_swap_itself() -> None:
    """Enumerated from the stage order, with SWAP on the outside.

    A failure *at* SWAP is a rename that did not commit - the transaction rolled
    back, or the undo put the old build back - so the deployment is still on
    last week's build and a retry is exactly right. Counted among the stages
    after it, that failure would be abandoned with "the swap completed", which
    is false, and the next week's rebuild would be the first retry.
    """
    from config.procrastinate import stages_after_swap
    from pipeline.rebuild import Stage

    ordered = list(Stage)
    assert Stage.SWAP not in stages_after_swap()
    assert stages_after_swap() == frozenset(ordered[ordered.index(Stage.SWAP) + 1 :])
    assert stages_after_swap(), "there is a stage after the swap for this to be about"


@pytest.mark.django_db(transaction=True)
def test_a_failure_at_the_swap_itself_is_retried_rather_than_reported_as_swapped(
    rebuild_environment, monkeypatch
) -> None:
    """The other side of the post-swap rule, through the task body.

    A swap that raised before its renames committed leaves nothing renamed, so
    the retired schema a rollback needs is untouched and re-running the whole
    rebuild is safe. It has to come out as the ordinary retryable failure, and
    not as the abandonment that says the swap completed.
    """
    from pipeline.rebuild import RebuildFailed, Stage

    def refused(*args, **kwargs):
        raise RuntimeError("could not take the lock on the segment relation")

    monkeypatch.setattr("pipeline.promotion.perform_swap", refused)
    with pytest.raises(RebuildFailed) as failed:
        app.tasks["weekly_rebuild"].func(timestamp=0)
    assert not isinstance(failed.value, RebuildAbandoned), str(failed.value)
    assert failed.value.stage is Stage.SWAP
    assert "swap completed" not in str(failed.value)

    strategy = app.tasks["weekly_rebuild"].retry_strategy
    assert strategy.get_retry_decision(exception=failed.value, job=job(0)) is not None, (
        "a swap that did not happen is the one failure here a retry can fix"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["binary_killed", "no_budget_left"])
def test_a_rebuild_killed_by_its_own_deadline_is_abandoned_rather_than_retried(
    rebuild_environment, monkeypatch, kind
) -> None:
    """A rebuild that ran out of its own budget will not finish faster next time.

    Both shapes of that failure arrive from inside a stage rather than from the
    boundary check the task catches by name: `subprocess.TimeoutExpired` when a
    binary is killed at the deadline, `RebuildTimedOut` when the next one is
    started with nothing left. Neither was terminal, so both were retried five
    times - and a retry runs the whole rebuild again including SWAP, whose
    `DROP SCHEMA live_old` is what a rollback would have put back. The first
    timed-out rebuild would have destroyed its own rollback target, four more
    times, at six hours a go.
    """
    from core.models import ScheduledRun
    from pipeline.rebuild import RebuildTimedOut

    _root, binaries = rebuild_environment
    failure = (
        subprocess.TimeoutExpired(cmd=["valhalla_build_tiles"], timeout=REBUILD_TIMEOUT_S)
        if kind == "binary_killed"
        else RebuildTimedOut("no time left to run valhalla_build_tiles")
    )

    def wedged(command, deadline=None, clock=None):
        if command[0] == "valhalla_build_tiles":
            raise failure
        return binaries(command)

    monkeypatch.setattr("pipeline.run._run_command", wedged)

    with pytest.raises(RebuildAbandoned) as abandoned:
        app.tasks["weekly_rebuild"].func(timestamp=0)
    assert "build_tiles" in str(abandoned.value)

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert not run.succeeded
    assert "RebuildAbandoned" in run.detail

    strategy = app.tasks["weekly_rebuild"].retry_strategy
    assert strategy.get_retry_decision(exception=abandoned.value, job=job(0)) is None


@pytest.mark.django_db(transaction=True)
def test_a_budget_that_lapses_after_the_swap_names_the_swap_and_the_restart(
    rebuild_environment, monkeypatch
) -> None:
    """The boundary check at SWAP -> RECONCILE, which was the one silent door.

    `RebuildTimedOut` was caught by name and abandoned with "the time budget ran
    out" and nothing else, while the identical failure arriving from inside the
    reconcile handler - wrapped in `RebuildFailed`, which carries a stage - got
    the swap-completed message and the router-restart notice. So a rebuild whose
    budget lapsed one instant after the rename produced an alert that mentioned
    neither the completed swap nor the three routers still serving last week's
    graph, which is the whole of what the operator has to do about it.

    Executed here as the reviewer executed it: the swap runs for real and
    succeeds, so `live_old` exists, and the budget lapses before the reconcile.
    The clock is the patched part rather than the wall, because waiting out a
    real budget is the same test with six hours in it.
    """
    from core.models import ScheduledRun
    from pipeline import rebuild as rebuild_module
    from pipeline import run as run_module
    from pipeline.rebuild import Stage
    from pipeline.schema import schema_exists

    _root, _binaries = rebuild_environment
    swapped: list[bool] = []

    real_build_handlers = run_module.build_handlers

    def handlers_whose_swap_spends_the_last_of_the_budget(context, *args, **kwargs):
        handlers = dict(real_build_handlers(context, *args, **kwargs))
        swap = handlers[Stage.SWAP]

        def swap_then_run_out_of_time() -> None:
            swap()
            swapped.append(True)

        handlers[Stage.SWAP] = swap_then_run_out_of_time
        return handlers

    real_run_rebuild = rebuild_module.run_rebuild

    def run_rebuild_on_a_clock_that_stops_after_the_swap(handlers, **kwargs):
        deadline = kwargs["deadline"]
        kwargs["clock"] = lambda: deadline + 1 if swapped else 0.0
        return real_run_rebuild(handlers, **kwargs)

    monkeypatch.setattr(
        "pipeline.run.build_handlers", handlers_whose_swap_spends_the_last_of_the_budget
    )
    monkeypatch.setattr(
        "pipeline.rebuild.run_rebuild", run_rebuild_on_a_clock_that_stops_after_the_swap
    )

    with pytest.raises(RebuildAbandoned) as abandoned:
        app.tasks["weekly_rebuild"].func(timestamp=0)

    message = str(abandoned.value)
    assert swapped, "the probe is worthless unless the swap really ran"
    assert schema_exists(settings.SEGMENT_SCHEMA_RETIRED), "the swap completed"
    assert "time budget" in message, f"it is still a timeout: {message}"
    assert "reconcile" in message, f"and it names the stage it stopped before: {message}"
    assert "swap completed" in message, (
        f"the abandoned message must say the rename happened: {message}"
    )
    assert ROUTER_RESTART_NOTICE in message, (
        f"and must carry the router restart, as the other door does: {message}"
    )

    strategy = app.tasks["weekly_rebuild"].retry_strategy
    assert strategy.get_retry_decision(exception=abandoned.value, job=job(0)) is None, (
        "a retry would re-run the swap over a deployment that has already swapped"
    )
    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert not run.succeeded


@pytest.mark.django_db(transaction=True)
def test_a_swap_whose_undo_did_not_finish_is_abandoned_rather_than_retried(
    rebuild_environment, monkeypatch
) -> None:
    """The half-restored deployment, which was retryable and silent.

    A swap that fails and undoes itself cleanly is an ordinary retryable
    failure and should be: the deployment is back on the build it was serving,
    and the next attempt starts where the last one did. A swap whose *undo*
    could not finish is a different deployment - one variant on this week's
    tiles and two on last week's, or settings rows naming a build no tile
    directory describes - and it was classified identically. The stage is SWAP
    rather than after it, so the stage-after-swap branch did not cover it, and
    the cause was whatever ordinary error the swap had hit (a read-only volume
    raises `OSError`), so `terminal_causes` did not either. Five more rebuilds
    ran on top of it, at six hours a go.

    And the one sentence saying so - the note `_note_undo_failures` attaches -
    existed only in the container's log. `str(error)` does not include notes,
    so the run row, the operations page and the alert all said the swap had
    failed and said nothing about the deployment being half-restored.
    """
    from core.models import ScheduledRun
    from pipeline import promotion, tiles
    from pipeline.variants import Variant

    real_restore = tiles.restore_links

    def restore_that_fails_on_the_first_variant(tiles_dir, variant, state):
        if variant is Variant.STANDARD:
            raise OSError("the data volume is read-only")
        return real_restore(tiles_dir, variant, state)

    def swap_that_cannot_take_the_lock(*args, **kwargs):
        raise RuntimeError("could not take the swap lock")

    monkeypatch.setattr(promotion, "swap_schemas", swap_that_cannot_take_the_lock)
    monkeypatch.setattr(tiles, "restore_links", restore_that_fails_on_the_first_variant)

    with pytest.raises(RebuildAbandoned) as abandoned:
        app.tasks["weekly_rebuild"].func(timestamp=0)

    message = str(abandoned.value)
    assert "half-restored" in message, f"the alert has to say what state this left: {message}"
    assert "not retried" in message, message
    assert "standard's tile links" in message, f"and name what could not be put back: {message}"
    assert "could not take the swap lock" in message, (
        f"without losing what went wrong first: {message}"
    )

    strategy = app.tasks["weekly_rebuild"].retry_strategy
    assert strategy.get_retry_decision(exception=abandoned.value, job=job(0)) is None, (
        "a retry would promote over a deployment nothing has a consistent picture of"
    )

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert not run.succeeded
    # The note, on the row an operator reads after the fact rather than in a
    # log line they would have to have been watching.
    assert "the swap's undo could not restore" in run.detail, (
        f"the note never reached the run row: {run.detail}"
    )
    assert "standard's tile links" in run.detail, run.detail


def test_a_swap_undo_that_did_finish_leaves_the_rebuild_retryable() -> None:
    """The other side of it, and the reason this is not just "swaps are terminal".

    `SwapUndoIncomplete` is raised only when `restore_everything` reports
    something it could not put back. An undo that ran to the end leaves the
    deployment on the build it was serving, so the swap's own error goes back
    to Procrastinate as it did before and a transient one is retried.
    """
    from config.procrastinate import terminal_causes
    from pipeline.promotion import SwapUndoIncomplete

    assert SwapUndoIncomplete in terminal_causes(), (
        "an undo that did not complete is not something a retry can fix"
    )
    assert not issubclass(RuntimeError, SwapUndoIncomplete), (
        "and it is a class of its own, so an ordinary swap failure stays retryable"
    )

    from pipeline.rebuild import RebuildFailed, Stage

    strategy = app.tasks["weekly_rebuild"].retry_strategy
    ordinary = RebuildFailed(Stage.SWAP, RuntimeError("could not take the swap lock"))
    assert strategy.get_retry_decision(exception=ordinary, job=job(0)) is not None, (
        "a swap that undid itself is the transient failure retries exist for"
    )


def test_a_timeout_between_stages_carries_the_stage_it_stopped_before() -> None:
    """The attribute the classification turns on, asserted where it is set, so
    that removing it fails here rather than three hours into a swapped rebuild
    whose alert says nothing about the swap."""
    from pipeline.rebuild import RebuildTimedOut, Stage, run_rebuild

    handlers = {stage: (lambda: None) for stage in Stage}
    with pytest.raises(RebuildTimedOut) as timed_out:
        run_rebuild(handlers, deadline=0.0, clock=lambda: 1.0)

    assert timed_out.value.stage is Stage.FETCH_EXTRACT


# --- Single-flight, which the queueing lock only half provides ------------------------


@pytest.fixture
def no_jobs_left_over():
    """Empty the job table around a test that puts rows in it.

    Procrastinate's models are unmanaged, so the `flush` pytest-django runs
    between transactional tests does not touch them: a job left `doing` by one
    of these tests is still there for the next, where the pre-flight under test
    would refuse a rebuild that has every right to run.
    """
    from django.db import connection

    def empty() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "TRUNCATE procrastinate_periodic_defers, procrastinate_events, "
                "procrastinate_jobs RESTART IDENTITY CASCADE"
            )

    empty()
    yield
    empty()


@pytest.mark.django_db(transaction=True)
def test_the_task_refuses_to_start_while_another_rebuild_is_running(
    rebuild_environment, monkeypatch, no_jobs_left_over
) -> None:
    """The pre-flight inside the task, which protects the cron path too.

    Procrastinate's queueing-lock index is partial on `WHERE status = 'todo'`,
    so a Tuesday tick is deduplicated against a *queued* rebuild and not against
    a running one: a hand-fired rebuild still in flight on Tuesday morning is
    doubled by the tick rather than dropping it, and what serialises the two
    today is `--concurrency=1` on the rebuild service - one slot, not a refusal.
    Raise the slot count or add a second rebuild worker and two rebuilds write
    the same staging schema and the same dated tile directory.

    So the task refuses to start, and it refuses before the run row is opened:
    a duplicate that never ran must not write a failure row for the rebuild that
    is running perfectly well.
    """
    from django.db import connection

    from config.procrastinate import RebuildAlreadyRunning
    from core.models import ScheduledRun

    other = app.tasks["weekly_rebuild"].defer(timestamp=0)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = 'doing'::procrastinate_job_status "
            "WHERE id = %s",
            [other],
        )

    with pytest.raises(RebuildAlreadyRunning) as refused:
        app.tasks["weekly_rebuild"].func(timestamp=0)

    assert f"job {other}" in str(refused.value)
    assert not ScheduledRun.objects.filter(task="weekly_rebuild").exists(), (
        "a rebuild that never started must not write a run row for the one that did"
    )

    strategy = app.tasks["weekly_rebuild"].retry_strategy
    assert strategy.get_retry_decision(exception=refused.value, job=job(0)) is None, (
        "retrying is not the answer to another rebuild already running"
    )


@pytest.mark.django_db(transaction=True)
def test_a_running_rebuild_does_not_refuse_itself(rebuild_environment, no_jobs_left_over) -> None:
    """The pre-flight excludes the job it is running under, which is the row
    Procrastinate has already set to `doing` before the task body is entered.
    Without the exclusion every rebuild the worker ever picks up refuses
    itself - the failure mode a count with no `exclude_id` has."""
    from django.db import connection
    from procrastinate.job_context import JobContext
    from procrastinate.jobs import Job

    from core.models import ScheduledRun

    job_id = app.tasks["weekly_rebuild"].defer(timestamp=0)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = 'doing'::procrastinate_job_status "
            "WHERE id = %s",
            [job_id],
        )

    context = JobContext(
        app=app,
        job=Job(
            id=job_id,
            queue="rebuild",
            lock=None,
            queueing_lock="weekly_rebuild",
            task_name="weekly_rebuild",
            task_kwargs={"timestamp": 0},
        ),
        start_timestamp=time.time(),
        abort_reason=lambda: None,
    )
    app.tasks["weekly_rebuild"].func(context, timestamp=0)

    assert ScheduledRun.objects.get(task="weekly_rebuild").succeeded


def test_both_deadline_failures_are_terminal_causes() -> None:
    """Named, so that removing either from the tuple fails here rather than
    three hours into a retried rebuild."""
    from config.procrastinate import terminal_causes
    from pipeline.rebuild import RebuildTimedOut

    assert RebuildTimedOut in terminal_causes()
    assert subprocess.TimeoutExpired in terminal_causes()


def test_a_command_that_exited_non_zero_is_not_a_terminal_cause() -> None:
    """The other half of the same list, and the one nothing pinned.

    `CommandFailed` is what a mirror that was briefly unreachable, a download
    that dropped mid-transfer and a tile build killed by the host all arrive
    as, which is the failure a retry is for; it stands where
    `subprocess.CalledProcessError` stood before it carried the reason. Added
    to the tuple it would look like tightening the list, and the effect would
    be that the first rebuild to lose a connection is abandoned until someone
    fires it by hand a week later. The class's own docstring says it is
    deliberately not here; this is what holds it to that.
    """
    from config.procrastinate import terminal_causes
    from pipeline.run import CommandFailed
    from pipeline.source import SourceExtractFailed

    assert CommandFailed not in terminal_causes()
    assert SourceExtractFailed not in terminal_causes(), (
        "and its caller in the extract stage, for the same reason"
    )


# --- Startability: a cold worker, as compose runs it ----------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_cold_worker_runs_a_deferred_job() -> None:
    """The worker process as compose starts it, in a subprocess with no Django
    set up by anything but the command itself, against this test's database:
    the schema has to be there from migrate, the app has to resolve, the task
    has to be registered, and the job has to reach the ORM without
    AppRegistryNotReady. The membership sweep is the job because it is the
    cheapest one that touches the database and writes a run row."""
    from procrastinate.contrib.django.models import ProcrastinateJob

    from core.models import ScheduledRun

    job_id = app.tasks["membership_sweep"].defer(timestamp=0)

    env = {
        **os.environ,
        "PGDATABASE": connection.settings_dict["NAME"],
        "DJANGO_SETTINGS_MODULE": "config.settings",
    }
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "procrastinate",
            "worker",
            "--one-shot",
            "--queues=maintenance",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]

    assert ProcrastinateJob.objects.get(id=job_id).status == "succeeded", result.stderr[-3000:]
    # `filter().first()` rather than `get()`: the worker runs its own periodic
    # deferrer before taking a job, and that deferrer queues any tick whose cron
    # boundary is inside the last ten minutes (procrastinate.periodic.MAX_DELAY).
    # The sweep's `0 */6 * * *` therefore produces a second run row whenever the
    # suite runs in the ten minutes after 00:00, 06:00, 12:00 or 18:00 UTC, and
    # `get()` raised MultipleObjectsReturned for four twenty-fourths of the day.
    # Both rows are this worker's, and what is being asserted is that the cold
    # process ran the job at all.
    run = ScheduledRun.objects.filter(task="membership_sweep").order_by("-started_at").first()
    assert run is not None and run.succeeded
    assert run.detail.startswith("purged ")


# --- Timeouts, enforced ---------------------------------------------------------------


def test_the_time_budgets_are_the_plans() -> None:
    assert REBUILD_TIMEOUT_S == 6 * 60 * 60
    assert SWEEP_TIMEOUT_S == 30 * 60


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_past_its_budget_is_abandoned_at_the_next_stage(
    rebuild_environment, monkeypatch
) -> None:
    from core.models import ScheduledRun

    monkeypatch.setattr("config.procrastinate.REBUILD_TIMEOUT_S", 0)
    with pytest.raises(RebuildAbandoned, match="time budget"):
        app.tasks["weekly_rebuild"].func(timestamp=0)
    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert not run.succeeded and "time budget" in run.detail


def test_a_binary_is_killed_when_the_budget_runs_out() -> None:
    """A wedged valhalla_build_tiles is killed by the rebuild's own deadline
    rather than left for the eight-day alarm."""
    from pipeline.run import _run_command

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_command(["sleep", "30"], deadline=time.monotonic() + 0.3)
    assert time.monotonic() - started < 5

    from pipeline.rebuild import RebuildTimedOut

    with pytest.raises(RebuildTimedOut):
        _run_command(["sleep", "30"], deadline=time.monotonic() - 1)


@pytest.mark.django_db
def test_a_sweep_past_its_budget_fails_the_job(monkeypatch) -> None:
    from core.models import ScheduledRun
    from core.runs import TaskTimedOut

    def slow_sweep(now=None):
        time.sleep(3)
        return 0, 0

    monkeypatch.setattr("core.membership.sweep_memberships", slow_sweep)
    monkeypatch.setattr("config.procrastinate.SWEEP_TIMEOUT_S", 0.2)

    started = time.monotonic()
    with pytest.raises(TaskTimedOut, match="membership_sweep exceeded"):
        app.tasks["membership_sweep"].func(timestamp=0)
    assert time.monotonic() - started < 2
    assert not ScheduledRun.objects.get(task="membership_sweep").succeeded


def backend_count() -> int:
    """Backends this database is serving, read from the server rather than
    inferred from Django's own bookkeeping."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        return cursor.fetchone()[0]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("blocked_in", ["python", "the database"])
def test_an_abandoned_task_gives_its_connection_back(blocked_in) -> None:
    """The deadline abandoned the thread and the thread kept the connection.

    Django's connections are per-thread, so the `finally` that closes one runs
    on the thread that owns it - and that `finally` does not run while the body
    is still going. A sweep abandoned at its deadline therefore sat on a backend
    for as long as it kept running, every five minutes, up to six copies
    resident; the proof was pytest failing to drop its own test database
    afterwards because it was "being accessed by other users".

    Both ways of being stuck are exercised, because they need different
    remedies: a statement in flight has to be cancelled before the thread can
    unwind, and a body blocked in Python has nothing to cancel and needs the
    socket closed under it.
    """
    import threading

    from core.runs import TaskTimedOut, run_with_deadline

    opened = threading.Event()
    before = backend_count()

    def hog() -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            opened.set()
            if blocked_in == "the database":
                cursor.execute("SELECT pg_sleep(30)")
        time.sleep(30)

    with pytest.raises(TaskTimedOut):
        run_with_deadline(hog, 1.0, "hog")
    assert opened.is_set(), "the abandoned body really did open a connection"

    deadline = time.monotonic() + 10
    while backend_count() > before and time.monotonic() < deadline:
        time.sleep(0.1)
    assert backend_count() <= before, "the abandoned thread is still holding a backend"


def finished_thread():
    """A thread that has already run, so `join` returns at once."""
    import threading

    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    return thread


class StubConnection:
    """What `_release_abandoned_connection` reads off a raw psycopg connection."""

    def __init__(self, status) -> None:
        from types import SimpleNamespace

        self.closed = False
        self.closes = 0
        self.cancels = 0
        self.pgconn = SimpleNamespace(transaction_status=status)

    def cancel(self) -> None:
        self.cancels += 1

    def close(self) -> None:
        self.closes += 1
        self.closed = True


@pytest.mark.parametrize("status_name", ["ACTIVE", "IDLE", "INTRANS"])
def test_an_abandoned_connection_is_only_closed_when_libpq_is_not_using_it(
    status_name, caplog
) -> None:
    """`close()` is PQfinish, and psycopg 3.3.5 calls it without the
    connection's lock.

    So closing a connection whose thread is still inside libpq - between
    PQsendQuery and PQgetResult, which is exactly where a thread blocked on a
    statement sits - frees a PGconn another thread is reading, and takes the
    worker down to reclaim one backend. The grace before the close is half a
    second, which is a guess about how long a cancelled statement takes to
    raise rather than a guarantee, so the close is gated on the connection
    being idle and the leak that gate accepts is logged by name.
    """
    import logging
    from types import SimpleNamespace

    from psycopg import pq

    from core.runs import _release_abandoned_connection

    raw = StubConnection(getattr(pq.TransactionStatus, status_name))
    with caplog.at_level(logging.WARNING, logger="core.runs"):
        _release_abandoned_connection(SimpleNamespace(connection=raw), finished_thread(), "sweep")

    assert raw.cancels == 1, "the cancel is safe from another thread and always runs"
    if status_name == "ACTIVE":
        assert raw.closes == 0, "PQfinish under a thread that is inside libpq is a segfault"
        assert "leaving the abandoned sweep connection open" in caplog.text
        assert "One backend stays held" in caplog.text, "the leak is named, not hidden"
    else:
        assert raw.closes == 1, "an idle connection is the caller's to give back"


def test_the_abandon_grace_is_half_a_second() -> None:
    """Named, because the docstring above reasons from the figure and nothing
    asserted it.

    Only ever paid on the timeout path, so it costs nothing in the ordinary
    case - but it is bounded on both sides. Long enough for a cancelled
    statement to raise and a `finally` to run; short enough that a worker
    already past its budget is not held for another turn of the schedule by
    every abandoned task in the queue.
    """
    from core.runs import ABANDON_GRACE_S

    assert ABANDON_GRACE_S == 0.5


def test_a_run_row_is_kept_for_thirty_days() -> None:
    """The figure the plan retains request logs for, and the only thing between
    a table nothing pruned and 105,000 rows a year from the five-minute tasks
    alone.

    Flat, in seconds and as a `timedelta`: the pruning tests all derive their
    ancient timestamps from this constant, so they hold for any value it takes -
    including one small enough to delete the history the morning after a bad
    week is read from.
    """
    from core.runs import JOB_ROW_RETENTION_S, RUN_ROW_RETENTION_S

    assert RUN_ROW_RETENTION_S == 30 * 24 * 60 * 60
    assert timedelta(seconds=RUN_ROW_RETENTION_S) == timedelta(days=30)
    assert JOB_ROW_RETENTION_S == RUN_ROW_RETENTION_S, "same reasoning, same number"


def test_an_unreadable_connection_is_left_to_the_thread_that_owns_it() -> None:
    """Anything that is not a psycopg connection with a live PGconn behind it
    is not something to call PQfinish on from another thread on a guess: a
    leaked backend is recoverable and a segfaulted worker is not."""
    from types import SimpleNamespace

    from core.runs import _release_abandoned_connection

    class NoPgconn(StubConnection):
        def __init__(self) -> None:
            super().__init__(None)
            del self.pgconn

    raw = NoPgconn()
    _release_abandoned_connection(SimpleNamespace(connection=raw), finished_thread(), "sweep")
    assert raw.closes == 0


# --- The degraded-guild mark, and the sweep it rides beside ---------------------------


@pytest.mark.django_db
class TestTheDegradedGuildSweep:
    """`mark_degraded_guilds` was the transition `should_mark_degraded` and
    `degraded_window` were written for and never had - two correct predicates
    called from nowhere, so `ConfiguredGuild.state` was written by nothing and
    no guild could ever leave `active`.

    Registering it is not enough, because it fails closed on silence. On a
    deployment whose bot has not been built - which is this one - it would mark
    every guild degraded on its first tick and lapse the deployment's standing
    72 hours later, for an outage that never happened. So the gate is part of
    the wiring and is tested with it.
    """

    def guild(self, guild_id: int = 900):
        from core.models import ConfiguredGuild

        return ConfiguredGuild.objects.create(guild_id=guild_id, name="Club")

    def heartbeat(self, age: timedelta):
        from core.models import ScheduledRun
        from core.revocation import GATEWAY_HEARTBEAT_TASK

        now = timezone.now()
        return ScheduledRun.objects.create(
            task=GATEWAY_HEARTBEAT_TASK,
            started_at=now - age,
            finished_at=now - age,
            succeeded=True,
        )

    def run_task(self):
        from core.models import ScheduledRun

        app.tasks["degraded_guild_sweep"].func(timestamp=0)
        return ScheduledRun.objects.filter(task="degraded_guild_sweep").latest("started_at")

    def test_the_schedule_is_inside_the_bound_it_enforces(self) -> None:
        """Derived from the cron rather than restated beside it: the mark is
        bounded by GATEWAY_ALERT_AFTER, and a guild marked an hour late carries
        an hour of stale grants the plan's single 72-hour number does not allow
        for. The six-hourly sweep is not this schedule."""
        from croniter import croniter

        from core.revocation import GATEWAY_ALERT_AFTER

        base = timezone.now()

        def interval(cron: str) -> timedelta:
            iterator = croniter(cron, base)
            first = iterator.get_next(type(base))
            return iterator.get_next(type(base)) - first

        assert interval(DEGRADED_GUILD_SWEEP_CRON) <= GATEWAY_ALERT_AFTER
        assert interval(DEGRADED_GUILD_SWEEP_CRON) < interval(MEMBERSHIP_SWEEP_CRON)

    def test_no_guild_is_touched_until_the_gateway_has_ever_reported(self) -> None:
        """Nothing writes the heartbeat on this deployment, so an ungated task
        would revoke every guild's standing on a five-minute schedule."""
        guild = self.guild()
        run = self.run_task()

        guild.refresh_from_db()
        assert guild.state == "active", "a bot that was never built is not a bot that went silent"
        assert guild.standing_valid_until is None
        assert "waiting for the gateway" in run.detail

    def test_a_gateway_silent_past_the_bound_marks_guilds_degraded(self) -> None:
        """Once the heartbeat exists at all, silence is the outage the window
        is for, and the window runs from the alert rather than from now."""
        from core.revocation import DEGRADED_WINDOW, GATEWAY_ALERT_AFTER

        guild = self.guild()
        beat = self.heartbeat(timedelta(hours=2))
        run = self.run_task()

        guild.refresh_from_db()
        assert guild.state == "degraded"
        expected = beat.started_at + GATEWAY_ALERT_AFTER + DEGRADED_WINDOW
        assert abs(guild.standing_valid_until - expected) < timedelta(seconds=1)
        assert "marked 1 guilds degraded" in run.detail

    def test_a_fresh_heartbeat_marks_nothing(self) -> None:
        guild = self.guild()
        self.heartbeat(timedelta(seconds=30))
        run = self.run_task()

        guild.refresh_from_db()
        assert guild.state == "active"
        assert "marked 0 guilds degraded" in run.detail

    def test_it_is_not_retried_because_the_next_tick_is_the_retry(self) -> None:
        """A retry schedule would hold the queueing lock across several ticks
        of a five-minute bound, which is the opposite of what the bound wants."""
        assert app.tasks["degraded_guild_sweep"].retry_strategy is None

    def test_a_due_removal_is_applied_here_with_no_heartbeat_ever_recorded(self) -> None:
        """The plan's hour, measured.

        PLAN.md:212 puts a delay of "an hour" on removing a peer, and the only
        thing applying one was the six-hourly membership sweep - so the delay was
        really one to seven hours, depending on when in the cycle the removal was
        asked for, and the removed admin kept every power for the difference.
        This is the five-minute task, so the delay is now the hour plus at most
        five minutes.

        With no gateway heartbeat, which is the state of this deployment and of
        every deployment until the bot exists. The removal half must run outside
        that gate: behind it, the five-minute path would apply nothing here and
        the six-hour figure would stand unchanged with a test that looked green.
        """
        from core.models import (
            PendingInstanceAdminRemoval,
            ScheduledRun,
            User,
            schedule_instance_admin_removal,
        )
        from core.revocation import gateway_has_ever_reported

        assert not gateway_has_ever_reported(), "the gate is closed, which is the point"

        requester = User.objects.create(discord_user_id=94100, is_instance_admin=True)
        doomed = User.objects.create(discord_user_id=94101, is_instance_admin=True)
        not_yet = User.objects.create(discord_user_id=94102, is_instance_admin=True)
        # Due six minutes ago: one tick of this task past its effective time.
        schedule_instance_admin_removal(
            doomed,
            actor=requester,
            now=timezone.now() - settings.INSTANCE_ADMIN_REMOVAL_DELAY - timedelta(minutes=6),
        )
        schedule_instance_admin_removal(not_yet, actor=requester, now=timezone.now())

        run = self.run_task()

        doomed.refresh_from_db()
        not_yet.refresh_from_db()
        assert not doomed.is_instance_admin, (
            "six minutes past due and still holding every power the role carries"
        )
        assert not_yet.is_instance_admin, "still inside its window, so still cancellable"
        assert not PendingInstanceAdminRemoval.objects.filter(user=doomed).exists()
        assert "waiting for the gateway" in run.detail, "the marking half is still held"
        assert "applied 1 due instance-admin removals" in run.detail
        assert ScheduledRun.objects.get(task="degraded_guild_sweep").succeeded


@pytest.mark.django_db(transaction=True)
def test_the_membership_sweep_also_drops_dead_session_rows() -> None:
    """`sweep_sessions` had no caller: rows for banned and deleted accounts,
    and rows whose Django session had already gone, sat in the table naming who
    was signed in and when for someone who asked to be forgotten. The middleware
    only ever reaches a row when a request carries the matching cookie, so an
    orphan is never looked at again and never deleted.

    Also the detail string. "purged N never-signed-in rows" stopped being true
    when the purge started counting rows dropped for deleted and tombstoned
    accounts, which go on sight rather than after thirty days.

    `transaction=True` because both sweeps run inside `run_with_deadline`, on
    their own thread and their own connection, which is where the task's time
    budget is enforced - a rolled-back test transaction is invisible to them.
    """
    from core.models import ScheduledRun, Session, User

    now = timezone.now()
    user = User.objects.create(discord_user_id=77)
    # No Django session row was ever created for this key, so it is orphaned.
    Session.objects.create(
        session_key="orphan",
        user=user,
        issued_epoch=user.session_epoch,
        created_at=now,
        last_seen_at=now,
    )

    app.tasks["membership_sweep"].func(timestamp=0)

    assert not Session.objects.filter(session_key="orphan").exists()
    detail = ScheduledRun.objects.get(task="membership_sweep").detail
    assert "1 session rows" in detail
    assert "never-signed-in rows" not in detail.replace("forgotten and never-signed-in rows", "")
    assert "forgotten and never-signed-in rows" in detail


@pytest.mark.django_db(transaction=True)
def test_the_membership_sweep_applies_due_instance_admin_removals() -> None:
    """The delay PLAN.md:212 puts on removing a peer is only a delay if
    something applies it once it has elapsed. `apply_due_instance_admin_removals`
    was written as a plain callable for the sweep to call; this is the call.
    A removal still inside its window is left alone, so the cancel the plan
    promises is still possible after a sweep."""
    from core.models import ScheduledRun, User, schedule_instance_admin_removal

    now = timezone.now()
    requester = User.objects.create(discord_user_id=91, is_instance_admin=True)
    due = User.objects.create(discord_user_id=92, is_instance_admin=True)
    early = User.objects.create(discord_user_id=93, is_instance_admin=True)
    schedule_instance_admin_removal(
        due, actor=requester, now=now - settings.INSTANCE_ADMIN_REMOVAL_DELAY - timedelta(seconds=1)
    )
    schedule_instance_admin_removal(early, actor=requester, now=now)

    app.tasks["membership_sweep"].func(timestamp=0)

    due.refresh_from_db()
    early.refresh_from_db()
    assert not due.is_instance_admin, "its delay had run out before the sweep"
    assert early.is_instance_admin, "its delay had not, so it is still cancellable"
    assert (
        "applied 1 due instance-admin removals"
        in ScheduledRun.objects.get(task="membership_sweep").detail
    )


# --- The backup ------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_backup_excludes_the_sessions_and_the_membership_cache(monkeypatch, tmp_path) -> None:
    """A real pg_dump of this test's database, read back with pg_restore --list
    the way the task reads it. The membership cache is excluded because who
    organizes with whom is the sensitive part; the sessions because a dump that
    sits on disk for months must not carry live ones. The reviewer's own check
    was `pg_restore --list | grep app_session`, and it found the table."""
    from config.procrastinate import perform_backup
    from core.models import ScheduledRun

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")

    destination = perform_backup()
    assert destination.parent == tmp_path / "backups"
    assert destination.suffix == ".dump"

    listing = subprocess.run(
        ["pg_restore", "--list", str(destination)], capture_output=True, text=True, check=True
    ).stdout
    data_entries = [line for line in listing.splitlines() if "TABLE DATA" in line]
    assert any("app_user" in line for line in data_entries), "the dump carries the users"
    assert not any("app_session" in line for line in data_entries)
    assert not any("cached_membership" in line for line in data_entries)
    # And the tombstones stay in. They are the only record that a ban happened
    # at all - the account row is gone by then - so a dump without them restores
    # a deployment on which every banned Discord id may sign up again. The
    # tombstone is an HMAC keyed with a secret that is not in the dump, which is
    # what makes keeping it safe to keep; excluding it would trade a privacy
    # gain it does not make for the loss of the ban list.
    assert any("ban_tombstone" in line for line in data_entries), (
        "the ban list must survive a restore"
    )

    app.tasks["nightly_backup"].func(timestamp=0)
    assert ScheduledRun.objects.get(task="nightly_backup").succeeded


@pytest.mark.django_db(transaction=True)
def test_the_runbooks_restore_is_clean_into_an_empty_database_and_fails_into_a_full_one(
    monkeypatch, tmp_path
) -> None:
    """What the restore runbook's step 3 rests on, measured with its own commands.

    Into a database the compose stack's image initialised - postgis,
    postgis_topology, fuzzystrmatch and postgis_tiger_geocoder created on first
    boot, which is what an empty PGDATA gives - a dump of a database the image
    initialised, restored straight in, fails on the tiger, tiger_data and
    topology schemas and exits 1 (3 errors on postgis/postgis:16-3.4). Dropped
    and created from template0 first, as the runbook now does, the same dump
    goes in with no error and exit 0. Into one that already holds the tables
    and rows - here, the same restore a second time - errors are counted, the
    rest of the archive is applied around them, and the exit is 1. The
    database here is initialised the way the image's
    /docker-entrypoint-initdb.d/10_postgis.sh does it, and the dump is taken by
    perform_backup() itself, from such a database.
    """
    import shutil

    from config.procrastinate import perform_backup

    for binary in ("pg_restore", "createdb", "dropdb", "psql"):
        if shutil.which(binary) is None:
            pytest.skip(f"{binary} is not installed")

    database = settings.DATABASES["default"]
    source, target = f"{database['NAME']}_rsrc", f"{database['NAME']}_restore"
    env = {
        **os.environ,
        "PGHOST": str(database["HOST"]),
        "PGPORT": str(database["PORT"]),
        "PGUSER": str(database["USER"]),
        "PGPASSWORD": str(database["PASSWORD"]),
    }

    def run(*argv: str, stdin=None) -> subprocess.CompletedProcess:
        return subprocess.run(argv, stdin=stdin, capture_output=True, env=env)

    def image_initialised(name: str) -> None:
        run("dropdb", "--if-exists", name)
        assert run("createdb", name).returncode == 0
        for extension in IMAGE_INIT_EXTENSIONS:
            made = run(
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                name,
                "-c",
                f"CREATE EXTENSION IF NOT EXISTS {extension}",
            )
            assert made.returncode == 0, made.stderr.decode()

    def restore(dump: Path, name: str) -> subprocess.CompletedProcess:
        with dump.open("rb") as archive:
            return run("pg_restore", "--no-owner", "-d", name, stdin=archive)

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "app")
    app_dump = perform_backup()
    try:
        image_initialised(source)
        seeded = restore(app_dump, source)
        assert seeded.returncode == 0, seeded.stderr.decode()
        with monkeypatch.context() as scoped:
            scoped.setattr(settings, "BACKUP_DIR", tmp_path / "image")
            scoped.setattr(settings, "DATABASES", {"default": {**database, "NAME": source}})
            dump = perform_backup()

        image_initialised(target)
        straight_in = restore(dump, target)
        errors = straight_in.stderr.decode()
        assert straight_in.returncode == 1, (straight_in.returncode, errors)
        assert "already exists" in errors, errors

        # The runbook's step 3: dropdb, createdb -T template0, then the restore.
        assert run("dropdb", target).returncode == 0
        assert run("createdb", "-T", "template0", target).returncode == 0
        into_empty = restore(dump, target)
        assert into_empty.returncode == 0, into_empty.stderr.decode()
        assert b"error" not in into_empty.stderr.lower(), into_empty.stderr.decode()
        listed = run(
            "psql",
            "-At",
            "-d",
            target,
            "-c",
            "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension",
        )
        assert set(listed.stdout.decode().strip().split(",")) >= set(IMAGE_INIT_EXTENSIONS), (
            listed.stdout.decode()
        )

        into_full = restore(dump, target)
        errors = into_full.stderr.decode()
        assert into_full.returncode == 1, (into_full.returncode, errors)
        assert "errors ignored on restore" in errors, errors
    finally:
        run("dropdb", "--if-exists", target)
        run("dropdb", "--if-exists", source)


# What postgis/postgis:16-3.4's first boot creates in POSTGRES_DB
# (/docker-entrypoint-initdb.d/10_postgis.sh, read from the image).
IMAGE_INIT_EXTENSIONS = ("postgis", "postgis_topology", "fuzzystrmatch", "postgis_tiger_geocoder")


@pytest.mark.django_db(transaction=True)
def test_the_task_itself_refuses_a_dump_whose_listing_leaks(monkeypatch, tmp_path) -> None:
    """Verification is production behaviour, not a test-side check: handed a
    table of contents that carries session data, perform_backup raises and
    the run row records a failure rather than a success."""
    from config.procrastinate import BackupVerificationFailed, perform_backup

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")

    def leaking_listing(archive, env, timeout=None):
        assert archive.exists(), "the dump is written before it is verified"
        return "1; 0 1 TABLE DATA public app_user r\n2; 0 2 TABLE DATA public app_session r\n"

    with pytest.raises(BackupVerificationFailed, match="app_session"):
        perform_backup(read_listing=leaking_listing)
    assert left_behind(tmp_path / "backups") == [], (
        "a dump the verification rejected must not be left under the name a restore trusts, "
        "least of all this one: the listing says it carries the rows the exclusion exists for"
    )


def left_behind(directory) -> list[str]:
    """Everything in the backup directory, whatever it is called.

    Not `glob("*.dump")`: the point of the part file is that a failed dump is
    not named like a kept one, and a check that only looks for `.dump` would
    pass just as happily on a directory full of abandoned part files.
    """
    return sorted(entry.name for entry in directory.iterdir()) if directory.is_dir() else []


@pytest.mark.django_db(transaction=True)
def test_a_verified_dump_is_the_only_thing_the_successful_path_leaves(
    monkeypatch, tmp_path
) -> None:
    """One file, under the ordinary name, with no part file beside it."""
    from config.procrastinate import perform_backup

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")

    destination = perform_backup()

    assert left_behind(tmp_path / "backups") == [destination.name]
    assert destination.name.endswith(".dump") and destination.is_file()


@pytest.mark.django_db(transaction=True)
def test_the_archive_carries_the_part_name_until_the_verification_has_passed(
    monkeypatch, tmp_path
) -> None:
    """Where the staging name matters, which is while the dump is unverified.

    Every other test here looks at the directory once the task has finished, and
    at that point a backup written straight to its final name is indistinguishable
    from one renamed into it: `part = destination` passes all of them. This looks
    from inside the window - `verify_dump_listing` is reached with the archive
    written and not yet accepted - and that is the whole of the promise the
    restore procedure rests on. Under the final name from the start, an operator
    restoring "last night's" during the nightly job's own half-minute picks up a
    half-written archive, and `prune_backups` counts it as one of the kept dumps
    and drops a good one to make room.
    """
    from django.utils import timezone

    from config.procrastinate import perform_backup

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")
    now = timezone.now()
    final = tmp_path / "backups" / f"routemaker-{now:%Y%m%dT%H%M%SZ}.dump"
    part = final.with_name(final.name + ".part")
    seen: dict[str, object] = {}

    def verify(listing):
        seen["reached"] = True
        seen["under the final name"] = final.exists()
        seen["under the part name"] = part.exists()
        seen["everything there"] = left_behind(tmp_path / "backups")
        return ["public.app_user"]

    monkeypatch.setattr("config.procrastinate.verify_dump_listing", verify)

    destination = perform_backup(now=now)

    assert seen["reached"], "the verification is what the rename waits for"
    assert seen["under the final name"] is False, (
        "an unverified archive must not sit under the name a restore trusts, "
        f"but the directory held {seen['everything there']}"
    )
    assert seen["under the part name"] is True
    assert seen["everything there"] == [part.name], "and nothing else beside it"
    # And afterwards, the rename has happened and the part name is gone.
    assert destination == final
    assert left_behind(tmp_path / "backups") == [final.name]


@pytest.mark.django_db(transaction=True)
def test_a_dump_that_exits_non_zero_leaves_nothing_on_the_volume(monkeypatch, tmp_path) -> None:
    """The failure that is not a timeout, against the real `pg_dump`.

    Only the timeout path cleaned up after itself, so a dump that merely exited
    non-zero - a wrong database name, no permission, a full volume - left
    `routemaker-<instant>.dump` behind: the newest by name, and therefore the
    one an operator restoring last night's backup picks up. Here the database
    does not exist, which is `pg_dump` connecting and failing after it has
    already created the archive file.
    """
    import subprocess as sp

    from config.procrastinate import perform_backup

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", "routemaker_no_such_database")

    with pytest.raises(sp.CalledProcessError):
        perform_backup()

    assert left_behind(tmp_path / "backups") == []


@pytest.mark.django_db(transaction=True)
def test_a_dump_the_verification_rejects_leaves_nothing_on_the_volume(
    monkeypatch, tmp_path
) -> None:
    """The archive is real and whole; what fails is the check that it is what
    was asked for. It must not survive under a name the restore procedure
    trusts - the archive a verification rejects is exactly the one that may
    carry what the exclusion exists to keep off the disk."""
    from config.procrastinate import BackupVerificationFailed, perform_backup

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")

    def refuse(listing):
        raise BackupVerificationFailed("the archive carries data it must exclude: ['public.x']")

    monkeypatch.setattr("config.procrastinate.verify_dump_listing", refuse)

    with pytest.raises(BackupVerificationFailed):
        perform_backup()

    assert left_behind(tmp_path / "backups") == []


def under_a_watchdog(call, seconds: float):
    """Run `call` on its own thread and fail if it is still running after
    `seconds`. Returns the exception it raised, or None.

    The watchdog is the point rather than a nicety: every test here that
    asserts a job is bounded is testing a call that, unbounded, does not fail -
    it waits. Asserting the elapsed time after the call returns cannot notice
    a call that never returns, so a budget removed from the code would hang the
    suite rather than fail it, which reads as an infrastructure problem.
    """
    import threading

    outcome: dict[str, BaseException] = {}

    def body() -> None:
        try:
            call()
        except BaseException as error:  # noqa: BLE001 - handed back to the caller
            outcome["error"] = error

    thread = threading.Thread(target=body, name="watchdog", daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), (
        f"still running after {seconds:.0f}s: whatever bounds this is not bounding it"
    )
    return outcome.get("error")


def locking_connection():
    """A second backend, for holding a lock `pg_dump` has to wait behind.

    Django's test connection is the one the test itself runs on, so a lock taken
    through it would be held by the transaction the test is already in and block
    nothing that matters.
    """
    import psycopg

    settings_dict = connection.settings_dict
    return psycopg.connect(
        host=settings_dict["HOST"] or "127.0.0.1",
        port=settings_dict["PORT"] or 5432,
        dbname=settings_dict["NAME"],
        user=settings_dict["USER"],
        password=settings_dict["PASSWORD"],
    )


@pytest.mark.django_db(transaction=True)
def test_a_backup_past_its_budget_is_killed_and_recorded_as_failed(monkeypatch, tmp_path) -> None:
    """`pg_dump` had no timeout at all, and the maintenance worker is one slot.

    A dump blocked on a lock therefore held that slot for as long as the process
    lived, while every five-minute degraded-guild tick under it was dropped -
    Procrastinate skips a periodic job whose predecessor is still queued or
    locked. The block here is the real one: `pg_dump` takes ACCESS SHARE on
    every table it dumps, and another backend holding ACCESS EXCLUSIVE on one of
    them stops it dead, exactly as a stuck `DROP TABLE` or a wedged migration
    would.
    """
    from core.models import ScheduledRun

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr("config.procrastinate.BACKUP_TIMEOUT_S", 2)

    blocker = locking_connection()
    try:
        blocker.execute("LOCK TABLE app_user IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        # Under a watchdog, because the thing being tested is a bound on how
        # long something takes: without the budget this call does not fail, it
        # waits on the lock for as long as the lock is held, and a test that
        # asserts an elapsed time after the fact hangs forever instead of
        # failing when the budget is taken away.
        error = under_a_watchdog(lambda: app.tasks["nightly_backup"].func(timestamp=0), seconds=30)
        assert isinstance(error, BackupTimedOut), error
        assert "budget" in str(error)
        assert time.monotonic() - started < 30, "the dump was killed, not waited out"
    finally:
        blocker.rollback()
        blocker.close()

    run = ScheduledRun.objects.get(task="nightly_backup")
    assert not run.succeeded
    assert "BackupTimedOut" in run.detail
    assert list((tmp_path / "backups").glob("*.dump")) == [], (
        "a half-written archive must not be left where the next restore would find it"
    )


def test_a_timed_out_backup_is_not_retried_but_an_ordinary_failure_is() -> None:
    """Retried, a thirty-minute timeout would hold the single-slot maintenance
    queue for two and a half hours more - the starvation the budget exists to
    end. The nightly schedule is the retry."""
    from config.procrastinate import BackupVerificationFailed

    strategy = app.tasks["nightly_backup"].retry_strategy
    backup_job = Job(
        queue="maintenance",
        lock=None,
        queueing_lock="nightly_backup",
        task_name="nightly_backup",
        task_kwargs={},
        attempts=0,
    )
    assert strategy.get_retry_decision(exception=BackupTimedOut("budget"), job=backup_job) is None
    assert (
        strategy.get_retry_decision(
            exception=BackupVerificationFailed("no table data"), job=backup_job
        )
        is not None
    ), "a dump that failed for any other reason is still worth another go tonight"


def test_the_backup_budget_is_the_maintenance_queues_bound() -> None:
    """It is not the dump's own convenience: it is how long one job may hold the
    single slot every other maintenance task queues behind. The membership sweep
    already bounds that slot at thirty minutes, so the queue's worst case is
    unchanged by the backup existing."""
    assert BACKUP_TIMEOUT_S == 30 * 60
    assert BACKUP_TIMEOUT_S <= SWEEP_TIMEOUT_S


@pytest.mark.django_db(transaction=True)
def test_the_backup_prunes_all_but_the_newest_dumps(monkeypatch, tmp_path) -> None:
    """Dumps are local-only and land on the volume the rebuild's disk gate
    measures, so an unbounded series of them ends as a rebuild that refuses
    every week with "grow the volume" as the only remedy."""
    from core.models import ScheduledRun

    backups = tmp_path / "backups"
    backups.mkdir()
    monkeypatch.setattr(settings, "BACKUP_DIR", backups)
    older = [f"routemaker-2026010{day}T000000Z.dump" for day in range(1, 10)]
    for name in older:
        (backups / name).write_bytes(b"old")

    app.tasks["nightly_backup"].func(timestamp=0)

    remaining = sorted(path.name for path in backups.glob("*.dump"))
    assert len(remaining) == BACKUP_KEEP
    assert remaining[-1] not in older, "tonight's dump is the newest one kept"
    assert remaining[:-1] == older[-(BACKUP_KEEP - 1) :], "the oldest dumps are the ones that go"
    assert f"pruned {len(older) - BACKUP_KEEP + 1} old dumps" in (
        ScheduledRun.objects.get(task="nightly_backup").detail
    )


@pytest.mark.django_db(transaction=True)
def test_the_backup_also_prunes_the_run_and_job_history(monkeypatch, tmp_path) -> None:
    """The row pruning rides on the backup rather than on a schedule of its own,
    which means the only thing standing between it and never running is this
    call. Asserted as rows that were there before the task and are not there
    after it, because a detail string can be written by hand."""
    from core.models import ScheduledRun
    from core.runs import JOB_ROW_RETENTION_S, RUN_ROW_RETENTION_S

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path / "backups")

    now = timezone.now()
    ancient = now - timedelta(seconds=RUN_ROW_RETENTION_S * 2)
    doomed_run = ScheduledRun.objects.create(
        task="membership_sweep", started_at=ancient, finished_at=ancient, succeeded=True
    )
    kept_run = ScheduledRun.objects.create(
        task="membership_sweep",
        started_at=ancient + timedelta(days=1),
        finished_at=ancient + timedelta(days=1),
        succeeded=True,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO procrastinate_jobs
                (queue_name, task_name, priority, args, status, attempts, abort_requested)
            VALUES ('maintenance', 'membership_sweep', 0, '{}'::jsonb,
                    'succeeded'::procrastinate_job_status, 1, false)
            RETURNING id
            """
        )
        doomed_job = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, 'succeeded', %s)",
            [doomed_job, now - timedelta(seconds=JOB_ROW_RETENTION_S * 2)],
        )

    app.tasks["nightly_backup"].func(timestamp=0)

    assert not ScheduledRun.objects.filter(id=doomed_run.id).exists(), (
        "a run row past its retention is still there, so nothing pruned it"
    )
    assert ScheduledRun.objects.filter(id=kept_run.id).exists(), "the newest success per task stays"
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM procrastinate_jobs WHERE id = %s", [doomed_job])
        assert cursor.fetchone()[0] == 0, "a finished job past its retention was not pruned"
    detail = ScheduledRun.objects.filter(task="nightly_backup").order_by("-started_at")[0].detail
    assert "1 run rows, 1 finished job rows" in detail


def test_the_local_dump_retention_is_a_week() -> None:
    """Long enough that corruption noticed over a weekend still has a local copy
    to restore from; short enough that the volume carries gigabytes rather than a
    year of them. The plan's remote 30-day retention is a separate, unbuilt
    thing."""
    assert BACKUP_KEEP == 7


@pytest.mark.django_db(transaction=True)
def test_the_heartbeat_task_writes_a_row_that_the_alert_reads() -> None:
    """The plan's worker health check. A stalled worker stops writing every
    other alert row too, but their windows are 26 and 12 hours, so without this
    a dead worker takes half a day to notice."""
    from core.models import ScheduledRun
    from core.runs import stale_tasks

    now = timezone.now()
    # A deployment old enough for the heartbeat's ten-minute window to have
    # passed: a task that has never run is stale from the deployment's first
    # run row, not from `up` (core.runs.stale_task_details).
    ScheduledRun.objects.create(
        task="nightly_backup", started_at=now - timedelta(days=2), finished_at=now, succeeded=True
    )
    assert "worker_heartbeat" in stale_tasks(now)

    app.tasks["worker_heartbeat"].func(timestamp=0)

    run = ScheduledRun.objects.get(task="worker_heartbeat")
    assert run.succeeded and run.finished_at is not None
    assert str(os.getpid()) in run.detail
    assert "worker_heartbeat" not in stale_tasks(now)


def test_the_heartbeat_is_not_retried_because_the_next_tick_is_the_retry() -> None:
    assert app.tasks["worker_heartbeat"].retry_strategy is None


def test_the_verification_refuses_a_dump_that_carries_what_it_must_not() -> None:
    from config.procrastinate import BackupVerificationFailed

    good = (
        "1234; 0 5678 TABLE DATA public app_user routemaker\n"
        "1235; 0 5679 TABLE DATA public jurisdiction routemaker\n"
    )
    assert verify_dump_listing(good) == ["public.app_user", "public.jurisdiction"]
    with pytest.raises(BackupVerificationFailed, match="app_session"):
        verify_dump_listing(good + "1236; 0 5680 TABLE DATA public app_session routemaker\n")
    with pytest.raises(BackupVerificationFailed, match="no table data"):
        verify_dump_listing("1; 0 0 ENCODING - ENCODING\n")


# --- Alerting --------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_alert_reads_the_absence_of_a_recent_success() -> None:
    """A rebuild that stopped being scheduled emits no error at all, so an alert
    built on errors stays silent through exactly the outage it exists for."""
    from core.models import ScheduledRun
    from core.runs import STALE_AFTER, stale_tasks

    now = timezone.now()
    # A deployment that has been up long enough for every window to have
    # passed. Without a row this database is a stack that came up a moment ago,
    # where nothing is late yet - see `test_a_fresh_deployment_has_nothing_to
    # _alert_about` in tests/test_operations.py.
    ScheduledRun.objects.create(
        task="weekly_rebuild",
        started_at=now - timedelta(days=90),
        finished_at=now - timedelta(days=90),
        succeeded=False,
    )
    assert set(stale_tasks(now)) == set(STALE_AFTER)

    for task in STALE_AFTER:
        ScheduledRun.objects.create(
            task=task, started_at=now - timedelta(minutes=1), finished_at=now, succeeded=True
        )
    assert stale_tasks(now) == []

    # A failure is not a success, and neither is an old one.
    ScheduledRun.objects.filter(task="weekly_rebuild").update(succeeded=False)
    assert stale_tasks(now) == ["weekly_rebuild"]


@pytest.mark.django_db
def test_a_success_older_than_its_own_window_is_stale() -> None:
    """The window itself, one task at a time, on both sides of its edge.

    The suite only ever pinned the rebuild's window. Every other number in
    `STALE_AFTER` could be multiplied by ten - a backup alert at 260 hours, a
    membership sweep at 500 - and nothing failed, because no test ever wrote a
    success old enough to matter. Nor did anything exercise the second half of
    the staleness predicate: with `(now - started_at) >= window` deleted, a task
    that succeeded once a year ago read as healthy forever and every test still
    passed.
    """
    from core.models import ScheduledRun
    from core.runs import STALE_AFTER, stale_tasks

    now = timezone.now()
    for task, window in STALE_AFTER.items():
        ScheduledRun.objects.filter(task=task).delete()
        inside = ScheduledRun.objects.create(
            task=task,
            started_at=now - timedelta(seconds=window - 60),
            finished_at=now,
            succeeded=True,
        )
        assert task not in stale_tasks(now), f"{task} is not stale a minute inside its window"

        inside.started_at = now - timedelta(seconds=window + 60)
        inside.save(update_fields=["started_at"])
        assert task in stale_tasks(now), f"{task} is stale a minute past its window"


def test_every_alert_window_is_pinned() -> None:
    """Flat, because every one of these is a promise made elsewhere.

    The rebuild's eight days and the backup's 26 hours are the plan's own alert
    numbers; the membership sweep's twelve hours is two missed six-hourly runs;
    the two five-minute tasks are windowed at six missed ticks, since
    Procrastinate drops a periodic tick whose predecessor still holds the queue
    and a single drop is ordinary; and the heartbeat is the plan's "worker
    heartbeat silent for 10 minutes", which is two missed ticks of its own
    five-minute schedule.
    """
    from core.runs import STALE_AFTER

    assert STALE_AFTER == {
        "weekly_rebuild": 8 * 24 * 60 * 60,
        "nightly_backup": 26 * 60 * 60,
        "membership_sweep": 12 * 60 * 60,
        "degraded_guild_sweep": 30 * 60,
        "worker_heartbeat": 10 * 60,
    }


def test_rebuild_timeout_is_shorter_than_its_alert_window() -> None:
    """A hung rebuild should be caught by its own timeout, not left for the
    weekly 'nothing completed' alarm to notice eight days later."""
    from core.runs import STALE_AFTER

    assert REBUILD_TIMEOUT_S < STALE_AFTER["weekly_rebuild"]
    assert STALE_AFTER["weekly_rebuild"] == REBUILD_ALERT_AFTER_S


def test_each_alert_window_is_wider_than_its_schedule() -> None:
    """Otherwise the alert fires on its own cadence rather than on a failure.

    Derived from the cron expressions rather than restated, which is what the
    earlier version of this test got wrong: it compared a constant against
    another constant three lines above it in the same file.
    """
    from croniter import croniter

    from core.runs import STALE_AFTER

    crons = {
        "weekly_rebuild": WEEKLY_REBUILD_CRON,
        "nightly_backup": NIGHTLY_BACKUP_CRON,
        "membership_sweep": MEMBERSHIP_SWEEP_CRON,
        "degraded_guild_sweep": DEGRADED_GUILD_SWEEP_CRON,
        "worker_heartbeat": WORKER_HEARTBEAT_CRON,
    }
    assert set(crons) == set(STALE_AFTER), "every scheduled task is watched, and the reverse"
    base = timezone.now()
    for task, cron in crons.items():
        iterator = croniter(cron, base)
        first = iterator.get_next(type(base))
        second = iterator.get_next(type(base))
        interval = (second - first).total_seconds()
        assert STALE_AFTER[task] > interval, f"{task} alerts on its own schedule"


def test_rebuild_is_scheduled_off_peak() -> None:
    """It takes half the cores and widens the latency alerts while it runs."""
    minute, hour, dom, month, dow = WEEKLY_REBUILD_CRON.split()
    assert minute == "0"
    assert 6 <= int(hour) <= 10, "08:00 UTC is early morning locally"

    # The day was discarded, which is the field that decides whether this is a
    # weekly rebuild at all: `* * *` here is the same off-peak hour every single
    # day, seven 1-2 GB downloads and seven full tile builds a week, and the
    # assertions above hold throughout. Tuesday specifically, so a rebuild that
    # goes wrong has the working week in front of it rather than a weekend.
    assert dow == "2", "Tuesday"
    assert (dom, month) == ("*", "*"), "every week, not a day of the month"
    assert WEEKLY_REBUILD_CRON == "0 8 * * 2"


def test_the_weekly_rebuild_fires_once_a_week_on_a_tuesday() -> None:
    """The schedule read the way procrastinate reads it, rather than as five
    strings: a cron whose day field stopped naming a day would still have a
    minute of 0 and an hour of 8."""
    from datetime import UTC, datetime

    from croniter import croniter

    fires = []
    iterator = croniter(WEEKLY_REBUILD_CRON, datetime(2026, 9, 1, tzinfo=UTC))
    for _ in range(4):
        fires.append(iterator.get_next(datetime))

    assert [fire.weekday() for fire in fires] == [1, 1, 1, 1], "Tuesday, every time"
    assert {(fire.hour, fire.minute) for fire in fires} == {(8, 0)}
    assert [(second - first).days for first, second in zip(fires, fires[1:], strict=False)] == [
        7,
        7,
        7,
    ], "once a week, not once a day"


@pytest.mark.django_db(transaction=True)
def test_the_task_does_not_refuse_itself_behind_a_job_that_is_merely_queued(
    rebuild_environment, no_jobs_left_over
) -> None:
    """The in-task pre-flight reads `doing` and only `doing`, and widening it to
    `todo` as well would make the Tuesday tick refuse itself.

    Procrastinate defers the periodic job and *then* a worker picks it up, so
    on the rebuild queue's single slot a tick fired while another rebuild is
    queued sits `todo` behind it - and with `todo` in the pre-flight's statuses
    every such rebuild would raise `RebuildAlreadyRunning` on a queue where
    nothing is running at all. The queued job is not a second rebuild writing
    the same staging schema; it is this one, waiting.

    `run_rebuild_now` is the caller that does refuse on `todo`, and correctly:
    it is about to add a *second* row, which the queueing lock would then
    collide with on the running job's retry.
    """
    from django.db import connection

    from core.models import ScheduledRun

    queued = app.tasks["weekly_rebuild"].defer(timestamp=0)
    with connection.cursor() as cursor:
        cursor.execute("SELECT status FROM procrastinate_jobs WHERE id = %s", [queued])
        assert cursor.fetchone()[0] == "todo"

    # It runs rather than refusing. The environment fixture stands the binaries
    # in, so this is the real handler set reaching a real run row.
    app.tasks["weekly_rebuild"].func(timestamp=0)

    run = ScheduledRun.objects.get(task="weekly_rebuild")
    assert run.succeeded, (
        "a rebuild queued behind this one is not another rebuild running; refusing here "
        "would make every tick that lands on a busy single-slot queue fail"
    )


def test_a_refused_rebuild_is_aborted_rather_than_failed() -> None:
    """What the refusal costs on the alert surfaces, which was thirty days.

    A task body that raises anything ordinary is finished `failed` by the
    worker, and `failed` is what `failed_job_count` counts and what the
    operations page lists. So a Tuesday tick that correctly declined to start a
    second rebuild left a red operations page and a non-zero `check_operations`
    until `prune_job_rows` removed the row a month later - for a deployment
    where nothing had gone wrong and with nothing an operator could do about it.

    `procrastinate.exceptions.JobAborted` is the status Procrastinate finishes
    a job with when the body raises it (`Worker._process_job`), and it is a
    terminal status neither alert counts. The retry decision comes with it: the
    worker computes none at all for an aborted job, so "not retried" stops
    depending on the retry strategy's exception list.
    """
    from procrastinate.exceptions import JobAborted

    from config.procrastinate import RebuildAlreadyRunning
    from core.runs import TERMINAL_JOB_STATUSES

    assert issubclass(RebuildAlreadyRunning, JobAborted)
    assert "aborted" in TERMINAL_JOB_STATUSES, "so the row is still pruned on the same schedule"
    assert "aborted" != "failed"


@pytest.mark.django_db(transaction=True)
def test_a_refused_rebuild_is_on_neither_alert_surface(
    rebuild_environment, monkeypatch, no_jobs_left_over
) -> None:
    """The same thing seen from the surfaces, with the status written the way
    the worker writes it."""
    from django.db import connection

    from config.procrastinate import RebuildAlreadyRunning
    from core.runs import failed_job_count, wedged_jobs

    other = app.tasks["weekly_rebuild"].defer(timestamp=0)
    with connection.cursor() as cursor:
        # Before the second deferral: the queueing lock's index is partial on
        # `WHERE status = 'todo'`, so two rebuilds can only coexist once the
        # first has left that state - which is the whole reason the in-task
        # check has to read `doing` itself.
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = 'doing'::procrastinate_job_status "
            "WHERE id = %s",
            [other],
        )
    refused_id = app.tasks["weekly_rebuild"].defer(timestamp=1)
    with pytest.raises(RebuildAlreadyRunning):
        app.tasks["weekly_rebuild"].func(timestamp=0)

    # The status the worker would write for a body that raised JobAborted.
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = 'aborted'::procrastinate_job_status "
            "WHERE id = %s",
            [refused_id],
        )

    assert failed_job_count() == 0, (
        "a refusal is not a failure, and it used to page for the thirty days the job row is kept"
    )
    assert [entry["id"] for entry in wedged_jobs()] == [], "and it is not wedged either"


@pytest.mark.django_db(transaction=True)
def test_a_failing_dump_still_prunes_the_row_tables(tmp_path, monkeypatch) -> None:
    """The prunes moved into a `finally`, and the reason is the shape of the
    failure they were downstream of.

    `prune_run_rows` and `prune_job_rows` are the only things that bound
    `scheduled_run` and `procrastinate_jobs`, and both ran after `pg_dump` had
    written and verified its archive. A dump that fails - a lock, a full
    volume, the thirty-minute timeout - therefore switched off the two
    mechanisms that reclaim space, and left them off for as many nights as it
    kept failing: the one failure mode that fills a volume also stopped the
    tidying.
    """
    from django.db import connection

    from config import procrastinate as worker
    from core.models import ScheduledRun
    from core.runs import RUN_ROW_RETENTION_S

    monkeypatch.setattr(settings, "BACKUP_DIR", tmp_path)
    old = timezone.now() - timedelta(seconds=RUN_ROW_RETENTION_S + 86_400)
    for index in range(3):
        ScheduledRun.objects.create(
            task="nightly_backup",
            started_at=old - timedelta(seconds=index),
            finished_at=old,
            succeeded=True,
        )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO procrastinate_jobs
                (queue_name, task_name, priority, args, status, attempts, abort_requested)
            VALUES ('maintenance', 'nightly_backup', 0, '{}'::jsonb, 'succeeded', 1, false)
            RETURNING id
            """
        )
        stale_job = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, 'succeeded', %s)",
            [stale_job, old],
        )

    def dump_that_fails():
        raise RuntimeError("pg_dump: error: connection to server was lost")

    monkeypatch.setattr(worker, "perform_backup", dump_that_fails)

    with pytest.raises(RuntimeError):
        app.tasks["nightly_backup"].func(timestamp=0)

    assert ScheduledRun.objects.filter(started_at__lt=old + timedelta(seconds=1)).count() == 1, (
        "the newest row per task is kept by design; the rest of the aged ones go, and they "
        "used to survive every night the dump failed"
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM procrastinate_jobs WHERE id = %s", [stale_job])
        assert cursor.fetchone()[0] == 0, "the finished job row past its retention goes too"
