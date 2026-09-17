#!/usr/bin/env python3
"""Generate the three Valhalla service configs from upstream's own defaults.

Valhalla reads many keys with no default and throws at startup when one is
absent: valhalla_service alone reads httpd.service.listen, httpd.service.loopback,
httpd.service.interrupt, httpd.service.timeout_seconds and the three worker
proxies that way. The hand-written configs this replaces carried 35 keys against
upstream's 180, so every service would have died on its first read - one key per
restart, in a loop, behind `restart: unless-stopped`.

Rather than chase the list, the defaults come from the pinned upstream generator
in valhalla/vendor and RouteMaker's overrides are merged on top. Upstream's own
default set is the definition of complete, and it stays complete across an
upgrade: re-vendor, re-run, read the diff.

Run: python scripts/build_valhalla_configs.py
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "valhalla" / "vendor" / "valhalla_build_config.py"

# The variants differ in their extract, not in their behaviour: variant
# behaviour belongs in the tags, and nothing in these configs encodes any. But
# they cannot share a tile directory. valhalla_build_tiles has no tile-directory
# option on its command line - it reads mjolnir.tile_dir - so three configs
# naming one directory are three builds overwriting each other, and only the
# last variant's graph survives. Each variant therefore names its own
# directory, and the test asserts the three files differ in exactly that.
VARIANTS = ("standard", "no-trail", "ebike")

# Where a variant's served tiles live, as both the rebuild container and the
# serving container see them: DATA_ROOT is mounted at /data in the first and
# `${DATA_ROOT}/tiles/<variant>/current` at this same path in the second, so
# one path names one file in both. `current` is a symlink the rebuild replaces
# at promotion; the build itself writes to a dated sibling through a derived
# config (pipeline/tiles.py) and never to this path.
TILE_ROOT = "/data/tiles/{variant}/current"

# The elevation directory. Skadi reads it from the top-level additional_data
# key and nowhere else: valhalla_build_tiles' elevation builder is constructed
# from config.get_child("additional_data"), and there is no read of a
# mjolnir.additional_data in 3.5.1. An earlier version of this file set both and
# claimed both were needed, and its test asserted the one that is read by
# nothing. Baking weighted_grade at build time is what this key is for:
# without it, use_hills is inert on every preset that sets it and the Mass Ride
# grade cap has no max_grade to read.
ELEVATION_DIR = "/data/elevation"

OVERRIDES: dict = {
    "mjolnir": {
        # The key that matters most. An unrecognised or misplaced Lua key makes
        # Valhalla fall back silently to its compiled-in transform, dropping
        # every derived tag while routing merely looks slightly off. Verified
        # against the pinned source: valhalla_build_tiles passes
        # config.get_child("mjolnir") into every parse stage, and
        # PBFGraphParser's get_lua reads graph_lua_name from that subtree.
        "graph_lua_name": "/conf/lua/graph.lua",
        "hierarchy": True,
        "shortcuts": True,
        "concurrency": 4,
        "logging": {"type": "std_out", "color": False},
    },
    "additional_data": {"elevation": ELEVATION_DIR},
    "loki": {
        # trace_attributes is what the stats block comes from; without it every
        # route reports nothing.
        "actions": ["route", "trace_route", "trace_attributes", "locate", "status"],
        "service_defaults": {"radius": 0, "minimum_reachability": 50},
        "logging": {"type": "std_out", "color": False},
    },
    "thor": {"logging": {"type": "std_out", "color": False}},
    "odin": {"logging": {"type": "std_out", "color": False}},
    "service_limits": {
        "bicycle": {
            "max_distance": 500000.0,
            "max_locations": 50,
            "max_matrix_distance": 200000.0,
        },
        "max_exclude_locations": 200,
        # The default caps total perimeter at 10 km and rejects the whole request
        # past it rather than degrading, so a busy week of closures would start
        # failing requests silently.
        "max_exclude_polygons_length": 50000,
        # Layer 4 candidate generation uses per-leg alternates.
        "max_alternates": 3,
        "trace": {"max_shape": 32000, "max_distance": 200000.0},
    },
    "httpd": {
        "service": {
            "listen": "tcp://*:8002",
            "loopback": "ipc:///tmp/loopback",
            "interrupt": "ipc:///tmp/interrupt",
            # Upstream's default is -1, read into a uint32_t, which is no timeout
            # at all. Layer 4 issues a candidate set per request; one wedged
            # candidate holding a worker forever would take the latency bound
            # down with it, so a request that has not finished in half a minute
            # is abandoned instead.
            "timeout_seconds": 30,
        }
    },
}


def load_upstream_defaults() -> dict:
    """Upstream's default config, with its Optional-typed keys dropped.

    The generator represents a key with no default as an `Optional` instance and
    omits it from the output, which is what running it with no arguments
    produces. Importing rather than shelling out keeps the failure legible if a
    re-vendor changes its shape.
    """
    spec = importlib.util.spec_from_file_location("valhalla_build_config", VENDOR)
    if spec is None or spec.loader is None:  # pragma: no cover - vendored file is present
        raise RuntimeError(f"cannot load the vendored generator at {VENDOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def strip(node):
        if isinstance(node, dict):
            return {
                key: strip(value)
                for key, value in node.items()
                if not isinstance(value, module.Optional)
            }
        return node

    return strip(copy.deepcopy(module.config))


def merge(base: dict, overrides: dict) -> dict:
    """Recursive merge. An override replaces a leaf and extends a subtree."""
    out = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def variant_overrides(variant: str) -> dict:
    """The part of the config that is genuinely per variant: its tile paths."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    root = TILE_ROOT.format(variant=variant)
    return {
        "mjolnir": {
            "tile_dir": f"{root}/tiles",
            "tile_extract": f"{root}/tiles.tar",
            "admin": f"{root}/admin.sqlite",
            "timezone": f"{root}/tz_world.sqlite",
        }
    }


def build(variant: str) -> dict:
    return merge(merge(load_upstream_defaults(), OVERRIDES), variant_overrides(variant))


def render(config: dict) -> str:
    return json.dumps(config, indent=2, sort_keys=True) + "\n"


def main() -> int:
    for variant in VARIANTS:
        path = REPO / "valhalla" / f"valhalla-{variant}.json"
        path.write_text(render(build(variant)))
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
