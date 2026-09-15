"""Run the Lua suites as part of the Python suite.

The remap is Lua because Valhalla's tag transform is Lua, and it is tested in
Lua for the same reason: a Python reimplementation would be testing a
translation rather than the file the tile build actually loads. Shelling out
keeps one suite and one CI signal.

The interpreter matters as much as the files. Valhalla 3.5.1's CMakeLists has
`pkg_check_modules(LuaJIT REQUIRED IMPORTED_TARGET luajit)`, so the transform
runs under LuaJIT - Lua 5.1 semantics plus the `bit` library, which upstream's
`nodes_proc` calls for `access_mask` and which stock Lua 5.2+ does not have.
Running these suites under lua5.4 would be running them under an interpreter
Valhalla cannot use.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Ordered by fidelity to what Valhalla links against, not by what is newest.
LUAJIT = shutil.which("luajit")
ANY_LUA = LUAJIT or shutil.which("lua5.1") or shutil.which("lua5.4") or shutil.which("lua")


def _require(interpreter: str | None, what: str) -> str:
    """Skip locally, fail in CI.

    A skip is the right answer on a laptop without LuaJIT and the wrong one in
    CI, where an image that lost the interpreter would report green with the
    whole Lua suite unrun.
    """
    if interpreter is None:
        if os.environ.get("CI"):
            pytest.fail(f"CI image has no {what}; the Lua suites did not run")
        pytest.skip(f"no {what} available")
    return interpreter


def _run(interpreter: str, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [interpreter, script],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ROUTEMAKER_LUA_DIR": "lua"},
    )


def test_remap_suite_passes() -> None:
    result = _run(_require(ANY_LUA, "Lua interpreter"), "tests/lua/test_remap.lua")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failures" in result.stdout


def test_entry_point_suite_passes_against_the_vendored_upstream() -> None:
    """The wrapper, the remap and Valhalla's own transform, end to end.

    Needs LuaJIT specifically: upstream's nodes_proc calls bit.bor.
    """
    result = _run(_require(LUAJIT, "LuaJIT"), "tests/lua/test_graph_entry.lua")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failures" in result.stdout


def test_the_lua_we_ship_stays_within_lua_51() -> None:
    """LuaJIT is Lua 5.1 with extensions. Syntax added in 5.2+ - integer division,
    the bitwise operators, goto - parses on a developer's lua5.4 and fails inside
    the container, where the failure surfaces as a silent fallback to Valhalla's
    compiled-in transform rather than as a crash.
    """
    for path in sorted((REPO / "lua").glob("*.lua")):
        source = path.read_text()
        for token in ("//", "goto ", "<<", ">>", "table.unpack", "math.type"):
            assert token not in source, f"{path.name} uses {token!r}, which LuaJIT does not accept"


def test_remap_declares_the_attributes_it_must_never_write() -> None:
    """highway and maxspeed set hierarchy, shortcuts, pruning and maneuver
    emission. A remap that wrote them could not serve use_roads 0 and use_roads 1
    from one graph."""
    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    assert "FORBIDDEN_KEYS" in source
    assert "highway = true" in source
    assert "maxspeed = true" in source


def test_the_vendored_upstream_is_pinned_and_present() -> None:
    """Checked in rather than fetched at build time, so the tags a tile build
    produces are a function of this repository and not of whichever image tag was
    pulled - and so the entry-point contract can be tested against the real file.
    """
    vendored = REPO / "lua" / "vendor" / "graph_upstream.lua"
    assert vendored.is_file()
    assert (REPO / "lua" / "vendor" / "VERSION").read_text().strip() == "3.5.1"
    source = vendored.read_text()
    # The contract the wrapper depends on: globals, and no module return. If a
    # future re-vendor changes this, the wrapper's global capture breaks and this
    # is where it should be noticed.
    assert "\nfunction ways_proc " in source
    assert "\nfunction nodes_proc " in source
    assert "\nfunction rels_proc " in source
    assert not source.rstrip().endswith("return M")
