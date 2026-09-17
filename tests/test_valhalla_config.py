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
    max_grade to read.

    The key Valhalla reads is the top-level `additional_data.elevation`: the
    elevation builder is constructed from config.get_child("additional_data"),
    and nothing in 3.5.1 reads a `mjolnir.additional_data`. The earlier version
    of this test asserted the one under mjolnir - a key read by nothing - and
    the generator wrote both and claimed both were needed.
    """
    assert config["additional_data"]["elevation"] == "/data/elevation"
    assert "additional_data" not in config["mjolnir"], (
        "a key read by nothing invites the assumption"
    )


def test_each_variant_names_its_own_tile_directory() -> None:
    """valhalla_build_tiles has no tile-directory option: the directory comes
    from mjolnir.tile_dir and nowhere else. Three configs naming one directory
    were three builds overwriting each other, so only the last variant's graph
    survived - the no-trail and e-bike variants existed on disk for the
    duration of a build and never afterwards. The earlier test compared each
    file to the generator's output for that variant, which the generator
    ignored, so it could not fail.
    """
    configs = {p.stem.removeprefix("valhalla-"): json.loads(p.read_text()) for p in CONFIGS}
    texts = {p.stem: p.read_text() for p in CONFIGS}
    for a in texts:
        for b in texts:
            if a < b:
                assert texts[a] != texts[b], f"{a} and {b} are byte-identical"

    for key in ("tile_dir", "tile_extract", "admin", "timezone"):
        values = {variant: c["mjolnir"][key] for variant, c in configs.items()}
        assert len(set(values.values())) == 3, f"{key} is shared: {values}"
        for variant, value in values.items():
            assert value.startswith(f"/data/tiles/{variant}/current/"), (
                f"{variant}: {key} = {value} is not under its own variant's directory"
            )


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


def test_worker_counts_come_from_the_command_line_not_the_config(config: dict) -> None:
    """These configs used to carry loki_workers, thor_workers and odin_workers,
    and this test used to assert them.

    valhalla_service reads no such keys. Its worker count is argv[2], falling
    back to std::thread::hardware_concurrency() - which inside a two-core limit
    would start one worker per core of the whole host. The setting that actually
    decides this is the compose command, so that is what is asserted.
    """
    import re

    for key in ("loki_workers", "thor_workers", "odin_workers"):
        assert key not in config, f"{key} is read by nothing and invites the old assumption"

    compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text()
    commands = re.findall(r'command: \["valhalla_service", "([^"]+)", "(\d+)"\]', compose)
    assert len(commands) == 3, "each variant needs a command; the image has no CMD of its own"
    for config_path, workers in commands:
        assert config_path.startswith("/conf/valhalla-")
        assert int(workers) >= 2, "a single worker serialises the candidate set"


def test_every_variant_service_is_given_a_command() -> None:
    """The upstream image declares neither ENTRYPOINT nor CMD. Without a command
    the container runs the base image's shell, exits, and - with restart:
    unless-stopped - restarts forever while answering nothing."""
    compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text()
    # Comments are dropped first: the file explains this by naming the variable.
    settings = "\n".join(line for line in compose.splitlines() if not line.lstrip().startswith("#"))
    assert "VALHALLA_CONFIG" not in settings, "the image reads no such variable"
    assert settings.count('"valhalla_service"') == 3


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


def test_the_configs_are_what_the_generator_produces() -> None:
    """Generated from upstream's pinned defaults, not hand-written.

    The hand-written versions carried 35 keys against upstream's 180, and
    valhalla_service reads several of the missing ones with no default -
    httpd.service.loopback, httpd.service.timeout_seconds, and the three worker
    proxies among them - so every service would have thrown on startup. The
    earlier tests here asserted the handful of keys someone had thought of,
    which is why a config that could not start a service passed them all.

    Regenerating and comparing means an upgrade is a re-vendor and a diff, and a
    hand edit fails here rather than diverging quietly.
    """
    import importlib.util

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_valhalla_configs", repo / "scripts" / "build_valhalla_configs.py"
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    for path in CONFIGS:
        variant = path.stem.removeprefix("valhalla-")
        assert path.read_text() == builder.render(builder.build(variant)), (
            f"{path.name} is not what scripts/build_valhalla_configs.py produces; "
            "edit the overrides in the script and re-run it"
        )


def test_the_config_covers_every_key_upstream_defines() -> None:
    """Upstream's own default set is the definition of complete.

    Valhalla reads many keys with no default and throws one at a time, so a
    missing key is a restart loop with a property_tree exception rather than a
    message about configuration.
    """
    import importlib.util

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_valhalla_configs", repo / "scripts" / "build_valhalla_configs.py"
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    def leaves(node: dict, path: str = "") -> set[str]:
        found = set()
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            found |= leaves(value, here) if isinstance(value, dict) else {here}
        return found

    upstream = leaves(builder.load_upstream_defaults())
    assert len(upstream) > 150, "the vendored generator produced almost nothing"
    for path in CONFIGS:
        missing = upstream - leaves(json.loads(path.read_text()))
        assert not missing, f"{path.name} is missing {sorted(missing)}"


def test_the_vendored_generator_is_pinned_to_the_image_tag() -> None:
    """A config generated from one version and served by another is how a key
    silently stops being read."""
    repo = Path(__file__).resolve().parents[1]
    pinned = (repo / "valhalla" / "vendor" / "VERSION").read_text().strip()
    compose = (repo / "compose.yaml").read_text()
    assert f"ghcr.io/valhalla/valhalla:{pinned}" in compose
    assert (repo / "lua" / "vendor" / "VERSION").read_text().strip() == pinned


def mounts_of(service: dict) -> dict[str, str]:
    """{container path: host path} for a service's bind mounts."""
    out = {}
    for volume in service.get("volumes") or []:
        host, container = volume.split(":")[:2]
        out[container] = host
    return out


def host_path_for(container_path: str, mounts: dict[str, str]) -> str | None:
    """Where a container path lands on the host, or None if no mount covers it."""
    for container_dir, host_dir in sorted(mounts.items(), key=lambda kv: -len(kv[0])):
        if container_path == container_dir or container_path.startswith(container_dir + "/"):
            return host_dir + container_path[len(container_dir) :]
    return None


def configured_paths(config: dict) -> dict[str, str]:
    return {
        "mjolnir.tile_dir": config["mjolnir"]["tile_dir"],
        "mjolnir.tile_extract": config["mjolnir"]["tile_extract"],
        "mjolnir.admin": config["mjolnir"]["admin"],
        "mjolnir.timezone": config["mjolnir"]["timezone"],
        "mjolnir.graph_lua_name": config["mjolnir"]["graph_lua_name"],
        "additional_data.elevation": config["additional_data"]["elevation"],
    }


def test_every_configured_path_is_mounted_for_the_service_that_uses_it() -> None:
    """A reviewer walked every path in the generated configs against the compose
    mounts and found three covered by nothing: the rebuild service mounted
    /tiles and /extracts, which no config named, so tiles landed on ephemeral
    container storage and vanished with it, and the Lua script and elevation
    directory it needed at build time existed in no mount at all.

    Two services use each variant's config: the rebuild, which builds from it,
    and that variant's valhalla_service, which serves from it. Every path has
    to resolve to a mount in both.
    """
    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parents[1] / "compose.yaml").read_text())
    services = compose["services"]
    for path in CONFIGS:
        variant = path.stem.removeprefix("valhalla-")
        config = json.loads(path.read_text())
        for service_name in ("rebuild", f"valhalla-{variant}"):
            mounts = mounts_of(services[service_name])
            uncovered = {
                key: value
                for key, value in configured_paths(config).items()
                if host_path_for(value, mounts) is None
            }
            assert not uncovered, f"{service_name} has no mount for {uncovered}"


def test_the_build_writes_where_the_serving_container_reads() -> None:
    """The same container path in the rebuild and in a serving container has to
    be the same host file, or the build writes a graph nothing serves. The
    rebuild mounts the whole data volume; each server mounts its variant's
    `current` directory at the identical container path."""
    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parents[1] / "compose.yaml").read_text())
    services = compose["services"]
    assert services["rebuild"]["environment"]["DATA_ROOT"] == "/data"
    rebuild = mounts_of(services["rebuild"])
    assert rebuild.get("/data") == "${DATA_ROOT}"

    for path in CONFIGS:
        variant = path.stem.removeprefix("valhalla-")
        config = json.loads(path.read_text())
        serving = mounts_of(services[f"valhalla-{variant}"])
        for key, value in configured_paths(config).items():
            if key == "mjolnir.graph_lua_name":
                continue  # the same checked-in file in both; test_graph_lua_name... covers it
            assert host_path_for(value, rebuild) == host_path_for(value, serving), (
                f"{variant}: {key} = {value} is a different host file for the build and the server"
            )
        tile_extract = config["mjolnir"]["tile_extract"]
        assert (
            host_path_for(tile_extract, serving)
            == f"${{DATA_ROOT}}/tiles/{variant}/current/tiles.tar"
        )
