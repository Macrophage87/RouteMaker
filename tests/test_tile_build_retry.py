"""valhalla_build_tiles' thread count, and the retired abort retry.

Valhalla 3.5.1 could abort a multi-threaded tile build with "double free or
corruption" (valhalla/valhalla#5005, fixed in 3.6.0), so the rebuild built with
2 threads and ran an aborted `valhalla_build_tiles` once more. The pinned image is
3.9.1, and both guards are retired (FOLLOWUP-VALHALLA-36-LEFTOVERS, item 4): the
default is 4 threads and an abort fails the stage at once, like any other
failure, and the attempt resumes from its checkpoints. See docs/OPERATIONS.md,
"Tile build threads".
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import signal
from pathlib import Path

import pytest

from pipeline import run as run_module
from pipeline import tiles
from pipeline.run import CommandFailed, _run_command
from pipeline.variants import Variant

REPO = Path(__file__).resolve().parents[1]

BUILD_TILES = ["valhalla_build_tiles", "-c", "/data/tiles/weekend/b/build-config.json", "w.pbf"]
EXTRACT = ["valhalla_build_extract", "-c", "/data/tiles/weekend/b/build-config.json", "-v"]


# --- The retired retry ---------------------------------------------------------------


def test_the_abort_retry_is_retired() -> None:
    """An abort is no longer the known race, so nothing runs a crashed build again:
    the tile stage calls the runner once per command (FOLLOWUP-VALHALLA-36-LEFTOVERS,
    item 4). A refused Lua script also dies of SIGABRT (std::terminate), and a
    retry only ran it twice."""
    assert not hasattr(run_module, "_run_tile_command")
    assert not hasattr(run_module, "TILE_BUILD_ABORT_RETRIES")
    assert not hasattr(run_module, "RETRYABLE_TILE_SIGNALS")
    source = Path(run_module.__file__).read_text()
    assert "run(command).log for command in commands" in source


def test_an_abort_says_so_once(monkeypatch) -> None:
    def fake_subprocess_run(command, **kwargs):
        import subprocess

        raise subprocess.CalledProcessError(-signal.SIGABRT, command, "", "double free\n")

    calls = []
    monkeypatch.setattr(
        run_module.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or fake_subprocess_run(command),
    )
    with pytest.raises(CommandFailed) as caught:
        _run_command(BUILD_TILES)
    assert len(calls) == 1
    assert caught.value.returncode == -signal.SIGABRT
    assert "valhalla_build_tiles exited -6: " in str(caught.value)
    assert "retry" not in str(caught.value)


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


def test_a_build_config_never_writes_to_the_serving_configs(tmp_path) -> None:
    """The serving configs are checked in, and the routers read them; a build's thread
    count goes into the build's own copy only. Run on a copy of `valhalla/`, so a
    regression cannot rewrite the repository's files while the test runs."""
    config_dir = tmp_path / "valhalla"
    shutil.copytree(REPO / "valhalla", config_dir)
    before = {path.name: path.read_bytes() for path in config_dir.iterdir() if path.is_file()}
    for variant in Variant:
        tiles.write_build_config(config_dir, tmp_path / "tiles", variant, "b1", concurrency=2)
    after = {path.name: path.read_bytes() for path in config_dir.iterdir() if path.is_file()}
    assert after == before
    for variant in Variant:
        serving = json.loads(tiles.serving_config_path(config_dir, variant).read_text())
        assert serving["mjolnir"]["concurrency"] == 4


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


def load_settings_module(module_name: str):
    """Execute `config/settings.py` again under another name, as
    test_settings_security does, so `sys.modules` keeps the real one."""
    import config.settings as live

    spec = importlib.util.spec_from_file_location(module_name, live.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_setting_is_a_whole_number_of_threads() -> None:
    from django.conf import settings

    assert isinstance(settings.REBUILD_TILE_CONCURRENCY, int)
    assert settings.REBUILD_TILE_CONCURRENCY >= 1


@pytest.mark.parametrize(("value", "threads"), [(None, 4), ("", 4), ("  ", 4), ("3", 3), ("1", 1)])
def test_the_setting_defaults_to_four_threads(monkeypatch, value, threads) -> None:
    """Unset, and empty (what compose hands the rebuild service when .env sets
    nothing), are the documented default: exactly 4."""
    if value is None:
        monkeypatch.delenv("REBUILD_TILE_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("REBUILD_TILE_CONCURRENCY", value)
    module = load_settings_module("config_settings_tile_concurrency")
    assert module.REBUILD_TILE_CONCURRENCY == threads
    assert type(module.REBUILD_TILE_CONCURRENCY) is int


@pytest.mark.parametrize("value", ["0", "-1", "x", "2.5", "1e1"])
def test_the_setting_refuses_anything_but_a_whole_number_of_at_least_one(
    monkeypatch, value
) -> None:
    """Refused when the settings load, so the worker fails at start rather than
    BUILD_TILES failing hours in and the rebuild retrying it five times."""
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("REBUILD_TILE_CONCURRENCY", value)
    with pytest.raises(ImproperlyConfigured, match="REBUILD_TILE_CONCURRENCY must be a whole"):
        load_settings_module("config_settings_bad_tile_concurrency")


def test_compose_hands_the_setting_to_the_rebuild_service() -> None:
    import yaml

    compose = yaml.safe_load((REPO / "compose.yaml").read_text())
    environment = compose["services"]["rebuild"]["environment"]
    assert "REBUILD_TILE_CONCURRENCY" in environment
