"""Run the Lua remap's own test suite as part of the Python suite.

The remap is Lua because Valhalla's tag transform is Lua, and it is tested in
Lua for the same reason: a Python reimplementation would be testing a
translation rather than the file the tile build actually loads. Shelling out
keeps one suite and one CI signal.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LUA = shutil.which("lua5.4") or shutil.which("lua")


@pytest.mark.skipif(LUA is None, reason="no Lua interpreter available")
def test_remap_suite_passes() -> None:
    result = subprocess.run(
        [LUA, "tests/lua/test_remap.lua"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failures" in result.stdout


def test_remap_declares_the_attributes_it_must_never_write() -> None:
    """highway and maxspeed set hierarchy, shortcuts, pruning and maneuver
    emission. A remap that wrote them could not serve use_roads 0 and use_roads 1
    from one graph."""
    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    assert "FORBIDDEN_KEYS" in source
    assert "highway = true" in source
    assert "maxspeed = true" in source
