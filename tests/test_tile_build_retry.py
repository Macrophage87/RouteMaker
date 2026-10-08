"""valhalla_build_tiles' thread count, and the one retry of an aborted build.

Valhalla 3.5.1 can abort a multi-threaded tile build with "double free or
corruption" (valhalla/valhalla#5005, fixed in 3.6.0): each build thread frees its
spatialite connections on exit through a libxml2 call that is not thread-safe.
It is a race, so the rebuild builds with fewer threads and runs an aborted
`valhalla_build_tiles` once more before failing. See docs/OPERATIONS.md, "Tile
build threads".
"""

from __future__ import annotations

import json
import logging
import signal
from pathlib import Path

import pytest

from pipeline import run as run_module
from pipeline import tiles
from pipeline.rebuild import RebuildTimedOut
from pipeline.run import CommandFailed, _run_command, _run_tile_command
from pipeline.variants import Variant

REPO = Path(__file__).resolve().parents[1]

BUILD_TILES = ["valhalla_build_tiles", "-c", "/data/tiles/weekend/b/build-config.json", "w.pbf"]
EXTRACT = ["valhalla_build_extract", "-c", "/data/tiles/weekend/b/build-config.json", "-v"]


def aborted(command) -> CommandFailed:
    return CommandFailed(
        command,
        -signal.SIGABRT,
        tiles.CommandOutput("Building 182 tiles with 4 threads...\n", "double free or corruption (fasttop)\n"),
    )


class Scripted:
    """A runner that fails the first `failures` calls with the given error."""

    def __init__(self, failures: int, error=aborted) -> None:
        self.failures = failures
        self.error = error
        self.calls: list[list[str]] = []

    def __call__(self, command):
        self.calls.append(list(command))
        if len(self.calls) <= self.failures:
            raise self.error(command)
        return tiles.CommandOutput("tiles built\n", "")


# --- The retry ---------------------------------------------------------------------


def test_an_aborted_tile_build_is_run_once_more_and_its_log_is_the_second_runs(caplog) -> None:
    run = Scripted(failures=1)
    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        output = _run_tile_command(run, BUILD_TILES)
    assert run.calls == [BUILD_TILES, BUILD_TILES]
    assert output.log == "tiles built\n"
    assert "retry 1 of 1" in caplog.text
    assert "weekend" in caplog.text, "the warning names the graph being rebuilt"


def test_a_second_abort_fails_as_before() -> None:
    run = Scripted(failures=2)
    with pytest.raises(CommandFailed) as caught:
        _run_tile_command(run, BUILD_TILES)
    assert caught.value.returncode == -signal.SIGABRT
    assert len(run.calls) == 2, "one retry, not a loop"


def test_an_ordinary_failure_is_not_retried() -> None:
    """A non-zero exit is a refusal (a bad Lua script, a missing file) that
    would say the same thing again; only the abort is the race."""

    def refused(command):
        return CommandFailed(command, 1, tiles.CommandOutput("", "bad input\n"))

    run = Scripted(failures=1, error=refused)
    with pytest.raises(CommandFailed):
        _run_tile_command(run, BUILD_TILES)
    assert len(run.calls) == 1


@pytest.mark.parametrize("returncode", [-signal.SIGSEGV, -signal.SIGKILL, 134])
def test_other_signals_are_not_retried(returncode) -> None:
    """SIGKILL is the OOM killer, which a rerun meets again; SIGSEGV is not the
    known race. 134 is what a shell reports for SIGABRT, and nothing here runs
    valhalla_build_tiles through a shell, so it is not read as one."""

    def killed(command):
        return CommandFailed(command, returncode, tiles.CommandOutput("", ""))

    run = Scripted(failures=1, error=killed)
    with pytest.raises(CommandFailed):
        _run_tile_command(run, BUILD_TILES)
    assert len(run.calls) == 1


@pytest.mark.parametrize(
    "command",
    [
        EXTRACT,
        ["valhalla_build_admins", "-c", "c.json", "merged.osm.pbf"],
        ["sh", "-c", "valhalla_build_tiles -c c.json w.pbf"],
    ],
)
def test_only_valhalla_build_tiles_itself_is_retried(command) -> None:
    run = Scripted(failures=1)
    with pytest.raises(CommandFailed):
        _run_tile_command(run, command)
    assert len(run.calls) == 1


def test_the_retry_gets_only_what_is_left_of_the_deadline(monkeypatch) -> None:
    """The retry goes through the same runner, so a rebuild whose budget ran
    out during the crashed build is abandoned rather than given a fresh one."""
    now = [0.0]

    def fake_subprocess_run(command, **kwargs):
        import subprocess

        now[0] = 100.0  # the crashed build used up the rest of the budget
        raise subprocess.CalledProcessError(-signal.SIGABRT, command, "", "double free\n")

    monkeypatch.setattr(run_module.subprocess, "run", fake_subprocess_run)

    def run(command):
        return _run_command(command, deadline=50.0, clock=lambda: now[0])

    with pytest.raises(RebuildTimedOut):
        _run_tile_command(run, BUILD_TILES)


def test_the_runner_reports_an_abort_as_minus_six(tmp_path) -> None:
    """What the retry keys on, from a real process: subprocess reports a child
    killed by a signal as the negative signal number."""
    script = tmp_path / "abort.sh"
    script.write_text("kill -ABRT $$\n")
    with pytest.raises(CommandFailed) as caught:
        _run_command(["sh", str(script)])
    assert caught.value.returncode == -signal.SIGABRT


# --- The thread count --------------------------------------------------------------


def test_the_build_config_carries_the_build_concurrency(tmp_path) -> None:
    path = tiles.write_build_config(
        REPO / "valhalla", tmp_path / "tiles", Variant.OFFROAD, "b1", concurrency=2
    )
    assert json.loads(path.read_text())["mjolnir"]["concurrency"] == 2


def test_without_one_the_serving_configs_count_is_left_alone(tmp_path) -> None:
    serving = json.loads((REPO / "valhalla" / "valhalla-weekend.json").read_text())
    _, config = tiles.build_config(REPO / "valhalla", tmp_path / "tiles", Variant.WEEKEND, "b1")
    assert config["mjolnir"]["concurrency"] == serving["mjolnir"]["concurrency"]


@pytest.mark.parametrize("concurrency", [0, -1])
def test_a_build_concurrency_below_one_is_refused(tmp_path, concurrency) -> None:
    """0 is not "unset", and neither it nor a negative is a thread count.
    Refused before the build directory is claimed."""
    with pytest.raises(ValueError, match="at least 1"):
        tiles.build_config(
            REPO / "valhalla", tmp_path / "tiles", Variant.WEEKEND, "b1", concurrency=concurrency
        )
    assert not (tmp_path / "tiles").exists()


def test_the_setting_is_a_whole_number_of_threads() -> None:
    from django.conf import settings

    assert isinstance(settings.REBUILD_TILE_CONCURRENCY, int)
    assert settings.REBUILD_TILE_CONCURRENCY >= 1


def test_compose_hands_the_setting_to_the_rebuild_service() -> None:
    import yaml

    compose = yaml.safe_load((REPO / "compose.yaml").read_text())
    environment = compose["services"]["rebuild"]["environment"]
    assert "REBUILD_TILE_CONCURRENCY" in environment
