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
import re
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


def test_every_key_the_remap_writes_is_one_valhalla_reads() -> None:
    """The quality bar's supported-key list, read from the pinned source.

    Valhalla's tile schema is fixed and a key it does not read is dropped in
    silence - no error, no effect - which is why believing the list is not good
    enough. `bicycle:forward` and `bicycle:backward` are in it;
    `bicycle:forward:conditional` is not, and upstream's graph.lua carries a bare
    `TODO access:conditional` where it would be.
    """
    supported = {
        line.strip()
        for line in (REPO / "lua" / "vendor" / "supported_keys.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {"bicycle", "bicycle:forward", "bicycle:backward", "cycleway", "surface"} <= supported
    assert "bicycle:forward:conditional" not in supported
    assert "bicycle:conditional" not in supported

    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    written = set(re.findall(r'out\["([^"]+)"\]\s*=', source))
    written |= set(re.findall(r"\bout\.(\w+)\s*=", source))
    written |= set(re.findall(r'out_table\["([^"]+)"\]\s*=', source))
    # Keys built at runtime from a side, which the regexes above cannot see.
    written |= {"bicycle:forward", "bicycle:backward"}

    unsupported = {
        key
        for key in written
        # The rm: namespace is this project's own and is stripped by the entry
        # point before Valhalla sees it, which the entry-point suite asserts.
        if not key.startswith("rm:") and key not in supported
    }
    assert not unsupported, f"the remap writes keys Valhalla drops silently: {sorted(unsupported)}"


def test_the_supported_key_list_is_what_the_extractor_produces() -> None:
    """Regenerated and compared, so a re-vendor that changed the parser's key set
    fails here rather than leaving a stale list to be trusted."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "extract_valhalla_keys", REPO / "scripts" / "extract_valhalla_keys.py"
    )
    assert spec is not None and spec.loader is not None
    extractor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extractor)

    checked_in = [
        line
        for line in (REPO / "lua" / "vendor" / "supported_keys.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert checked_in == extractor.extract(
        (REPO / "lua" / "vendor" / "graph_upstream.lua").read_text()
    )


def _lua_driver(source: str) -> subprocess.CompletedProcess:
    """Run a snippet against the shipped entry point, as a separate process.

    Stderr is the point of these: the build-log check greps a real
    `valhalla_build_tiles` log, and what reaches that log is whatever the
    transform wrote to the process's stderr.
    """
    interpreter = _require(LUAJIT, "LuaJIT")
    return subprocess.run(
        [interpreter, "-e", source],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ROUTEMAKER_LUA_DIR": "lua"},
    )


def test_a_rule_violation_reaches_the_build_log_and_keeps_the_element() -> None:
    """`error()` inside an entry point does not stop a tile build.

    `LuaTagTransform::Transform` runs the entry point under lua_pcall and hands
    back an empty tag map when it fails, so the element is stripped of every tag
    and dropped while the build reports success - the opposite of what a guard
    written as `error()` claims. A violation has to be visible in the log and
    has to leave the element alone.
    """
    result = _lua_driver(
        'dofile("lua/graph.lua")\n'
        'local remap = require("routemaker_remap")\n'
        'remap.remap_way = function() return { highway = "motorway" } end\n'
        'local filter, out = ways_proc({ highway = "residential", name = "Ordinary" }, 2)\n'
        'io.stdout:write(tostring(filter), " ", tostring(out.highway), " ",\n'
        '  tostring(out.name), " ", tostring(out[remap.VIOLATION_TAG] ~= nil), "\\n")\n'
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0", "residential", "Ordinary", "true"]
    assert "ROUTEMAKER-VIOLATION" in result.stderr, "nothing a build log could be searched for"


def test_the_border_guard_does_not_delete_the_border_node() -> None:
    """The guard exists so a state crossing stays passable. Written as `error()`
    it deleted the crossing node instead, which is the one outcome its comment
    ruled out."""
    result = _lua_driver(
        'dofile("lua/graph.lua")\n'
        'local remap = require("routemaker_remap")\n'
        'remap.remap_node = function() return { bicycle = "no" } end\n'
        'local _, out = nodes_proc({ barrier = "border_control", name = "StateLine" }, 2)\n'
        'io.stdout:write(tostring(out.name), " ", tostring(out.border_control), " ",\n'
        '  tostring(out.bicycle), " ", tostring(out.access_mask), "\\n")\n'
    )
    assert result.returncode == 0, result.stderr
    name, border, bicycle, mask = result.stdout.split()
    assert name == "StateLine", "the node was blanked"
    assert border == "true", "upstream no longer sees a border control node"
    assert bicycle == "nil", "the denying change was applied rather than refused"
    assert int(mask) // 4 % 2 == 1, "bicycle access at the border was removed"
    assert "ROUTEMAKER-VIOLATION" in result.stderr


def test_the_violation_sentinel_is_not_a_key_valhalla_reads() -> None:
    """Deliberate: the sentinel marks an element for whoever is watching the
    transform and must not be able to become a fact about the graph."""
    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    match = re.search(r'M\.VIOLATION_TAG = "([^"]+)"', source)
    assert match, "the sentinel is no longer declared where the entry point and the tests read it"
    sentinel = match.group(1)
    supported = {
        line.strip()
        for line in (REPO / "lua" / "vendor" / "supported_keys.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert sentinel not in supported
    assert not sentinel.startswith("rm:"), "it would be stripped before anything could see it"


def test_neither_entry_point_guards_with_error() -> None:
    """A transform-time `error()` is a silent delete. The two load-time ones are
    a different thing: they run in LuaTagTransform's constructor, which does
    throw, and are the loud case."""
    source = (REPO / "lua" / "graph.lua").read_text()
    entry_points = source[source.index("function ways_proc") :]
    assert "error(" not in entry_points, "a guard inside an entry point deletes the element"
    assert "record_violation" in entry_points
