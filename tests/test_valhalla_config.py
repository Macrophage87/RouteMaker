"""Valhalla configuration.

The one that matters most is the Lua key. An unrecognised or misplaced
configuration key makes Valhalla fall back silently to its compiled-in graph.lua,
dropping every derived tag while routing merely looks slightly off. The key was
verified against the Valhalla source: valhalla_build_tiles passes
config.get_child("mjolnir") into every parse stage and PBFGraphParser's get_lua
reads graph_lua_name from that subtree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CONFIGS = sorted((Path(__file__).resolve().parents[1] / "valhalla").glob("*.json"))


@pytest.fixture(params=CONFIGS, ids=lambda p: p.stem)
def config(request) -> dict:
    return json.loads(request.param.read_text())


def test_there_is_a_config_per_tile_variant() -> None:
    assert {p.stem for p in CONFIGS} == {
        "valhalla-standard",
        "valhalla-no-trail",
        "valhalla-ebike",
    }


def test_lua_key_is_a_direct_child_of_mjolnir(config: dict) -> None:
    """Not nested under mjolnir.logging. A misplaced key fails silently."""
    assert "graph_lua_name" in config["mjolnir"]
    assert "graph_lua_name" not in config["mjolnir"].get("logging", {})


def test_elevation_directory_is_configured(config: dict) -> None:
    """Caching HGT tiles is not the same as using them. Without the elevation
    directory at tile build, weighted_grade is never baked onto edges, use_hills
    is inert on every preset that sets it, and the Mass Ride grade cap has no
    max_grade to read."""
    assert config["mjolnir"]["additional_data"]["elevation"]


def test_exclude_polygon_limit_is_raised_above_the_default(config: dict) -> None:
    """The default caps total perimeter at 10 km and rejects the whole request
    past it rather than degrading, so a busy week of closures would start
    failing requests silently."""
    assert config["service_limits"]["max_exclude_polygons_length"] > 10_000


def test_alternates_are_available(config: dict) -> None:
    """Layer 4 candidate generation uses per-leg alternates."""
    assert config["service_limits"]["max_alternates"] >= 2


def test_trace_actions_are_enabled(config: dict) -> None:
    """The stats block comes from trace_attributes; without it every route
    reports nothing."""
    actions = config["loki"]["actions"]
    assert "trace_attributes" in actions
    assert "trace_route" in actions


def test_worker_counts_are_explicit(config: dict) -> None:
    """A single thor worker serialises the candidate set, which the latency bound
    assumes is issued concurrently."""
    assert config["thor_workers"] >= 2
    assert config["loki_workers"] >= 1
    assert config["odin_workers"] >= 1


def test_graph_lua_name_points_at_a_file_this_repository_ships(config: dict) -> None:
    """The configs previously named /conf/graph.lua, which existed nowhere: not in
    the repository, not in any mount. Valhalla would have fallen back to its
    compiled-in transform and dropped every derived tag without reporting an
    error. The earlier test checked only the key's position in the config tree,
    so it passed against a path pointing at empty space.
    """
    import re

    repo = Path(__file__).resolve().parents[1]
    configured = config["mjolnir"]["graph_lua_name"]

    mounts = {}
    for line in (repo / "compose.yaml").read_text().splitlines():
        match = re.search(r"- \./([\w/.-]+):(/[\w/.-]+):ro", line.strip())
        if match:
            mounts[match.group(2)] = match.group(1)

    for container_dir, host_dir in sorted(mounts.items(), key=lambda kv: -len(kv[0])):
        if configured.startswith(container_dir + "/"):
            on_disk = repo / host_dir / configured[len(container_dir) + 1 :]
            assert on_disk.is_file(), f"{configured} resolves to {on_disk}, which is absent"
            return
    raise AssertionError(f"{configured} is not covered by any compose mount")


def test_the_entry_point_defines_the_globals_valhalla_actually_calls() -> None:
    """LuaTagTransform checks for ways_proc, nodes_proc and rels_proc by name at
    construction and throws if any is missing. An earlier version of this file
    defined way_function and node_function - OSRM's entry points - so Valhalla
    would have refused to load it, and the earlier version of this test asserted
    those two names, pinning the bug in place.
    """
    import shutil
    import subprocess

    lua = shutil.which("lua5.4") or shutil.which("lua")
    if lua is None:  # pragma: no cover - CI installs it
        pytest.skip("no Lua interpreter available")

    repo = Path(__file__).resolve().parents[1]
    # Loading without the vendored upstream must fail loudly rather than quietly
    # transform nothing, so the check runs against a stub upstream.
    script = (
        'package.path = "lua/?.lua;" .. package.path; '
        'package.loaded["graph_upstream"] = {ways_proc=function() end, '
        "nodes_proc=function() end, rels_proc=function() end}; "
        'dofile("lua/graph.lua"); '
        'assert(type(ways_proc) == "function", "ways_proc missing"); '
        'assert(type(nodes_proc) == "function", "nodes_proc missing"); '
        'assert(type(rels_proc) == "function", "rels_proc missing")'
    )
    result = subprocess.run(
        [lua, "-e", script], cwd=repo, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_entry_point_fails_loudly_without_the_vendored_upstream() -> None:
    """Silent fallback is the failure mode this guard exists for."""
    source = (Path(__file__).resolve().parents[1] / "lua" / "graph.lua").read_text()
    assert "error(" in source
    assert "vendor_valhalla_lua" in source
