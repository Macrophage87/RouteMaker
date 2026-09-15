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


def test_the_entry_point_delegates_to_a_vendored_upstream() -> None:
    """The behavioural half of this lives in tests/test_lua_remap.py, which runs
    lua/graph.lua under LuaJIT against the real vendored Valhalla transform.

    This half pins the arrangement that makes that possible. The earlier test
    here stubbed a module-shaped upstream into package.loaded and asserted the
    three globals existed afterwards, which passed while the shipped wrapper held
    `require`'s return value and called `upstream.ways_proc` on it. Upstream
    defines globals and returns nothing, so that value is the boolean `true` and
    every way of every tile build would have raised. A test that fabricates the
    interface it is meant to pin cannot fail - the same shape as the round-1 test
    that pinned OSRM's way_function.
    """
    repo = Path(__file__).resolve().parents[1]
    # Comment lines are dropped first: the file documents the bug below by name,
    # and a check that read the prose would fail on the explanation of the fix.
    source = "\n".join(
        line
        for line in (repo / "lua" / "graph.lua").read_text().splitlines()
        if not line.lstrip().startswith("--")
    )

    assert "package.loaded" not in source, "the entry point must not fabricate an upstream"
    # Captured from the globals the vendored chunk installs, not indexed off the
    # require() return value, which is a boolean.
    assert "local up_ways, up_nodes, up_rels = ways_proc, nodes_proc, rels_proc" in source
    # The bug shape: binding require()'s return value and indexing it.
    for proc in ("ways_proc", "nodes_proc", "rels_proc"):
        assert f"upstream.{proc}" not in source
    assert "local ok, upstream" not in source
    for name in ("ways_proc", "nodes_proc", "rels_proc"):
        assert f"function {name}(kv, nokeys)" in source


def test_the_entry_point_fails_loudly_without_the_vendored_upstream() -> None:
    """Silent fallback is the failure mode this guard exists for."""
    source = (Path(__file__).resolve().parents[1] / "lua" / "graph.lua").read_text()
    assert "error(" in source
    assert "vendor_valhalla_lua" in source


def test_the_entry_point_refuses_an_upstream_without_the_expected_globals() -> None:
    """A re-vendor that changed upstream's entry-point contract would otherwise
    capture three nils and fall over one way into the build, by which point the
    useful part of the message is long gone."""
    source = (Path(__file__).resolve().parents[1] / "lua" / "graph.lua").read_text()
    assert 'type(up_ways) ~= "function"' in source
    assert "did not define the *_proc globals" in source
