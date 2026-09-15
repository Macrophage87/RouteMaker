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
