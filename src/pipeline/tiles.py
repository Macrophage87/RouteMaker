"""The tile directories: where a build lands, how it is promoted, how it is read.

Layout, per variant, under TILES_DIR (which is /data/tiles inside both the
rebuild container and the serving containers, so one path means one file):

    <variant>/<build id>/tiles/        the tile directory valhalla_build_tiles wrote
    <variant>/<build id>/tiles.tar     the extract the service actually serves
    <variant>/<build id>/build-config.json
    <variant>/current -> <build id>    what the serving container mounts
    <variant>/previous -> <build id>   what rollback puts back

The checked-in serving configs name the `current` paths. A build cannot write
there - the serving container has it mounted read-only and, more to the point,
it is the graph being served - so the build stage derives a build config with
every `current` replaced by the dated directory, and promotion is one symlink
replaced atomically per variant. The old build is not deleted by promotion; it
is what `previous` points at, and the disk gate is what makes room for it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .variants import Variant

logger = logging.getLogger(__name__)

CURRENT = "current"
PREVIOUS = "previous"

# Config keys that name something inside the tile directory. Anything else in
# the config - the Lua script, the elevation directory - is shared between
# builds and is left as the checked-in config has it.
TILE_PATH_KEYS = (
    ("mjolnir", "tile_dir"),
    ("mjolnir", "tile_extract"),
    ("mjolnir", "admin"),
    ("mjolnir", "timezone"),
)


class TilePathsNotPerVariant(ValueError):
    """A serving config names a tile path outside its own variant's directory."""


def serving_config_path(config_dir: Path, variant: Variant) -> Path:
    return Path(config_dir) / f"valhalla-{variant.value}.json"


def current_dir(tiles_dir: Path, variant: Variant) -> Path:
    return Path(tiles_dir) / variant.value / CURRENT


def build_dir(tiles_dir: Path, variant: Variant, build_id: str) -> Path:
    return Path(tiles_dir) / variant.value / build_id


def build_config(
    config_dir: Path, tiles_dir: Path, variant: Variant, build_id: str
) -> tuple[Path, dict]:
    """The config a tile build runs with: the serving config, retargeted.

    Every tile path in the serving config must sit under this variant's
    `current` directory as the container sees it (`/data/tiles/<variant>/current`);
    each is rewritten to the same relative location under the dated build
    directory as this process sees it. The serving config's own container path
    and this process's path for the same directory differ only when the tests
    run outside a container, which is why the rewrite is by suffix rather than
    by prefix.
    """
    serving = json.loads(serving_config_path(config_dir, variant).read_text())
    container_current = f"/data/tiles/{variant.value}/{CURRENT}"
    destination = build_dir(tiles_dir, variant, build_id)

    config = json.loads(json.dumps(serving))
    for section, key in TILE_PATH_KEYS:
        value = config[section][key]
        if not value.startswith(container_current + "/"):
            raise TilePathsNotPerVariant(
                f"{variant.value}: {section}.{key} = {value!r} is not under {container_current}; "
                "a build writing there would overwrite another variant's graph"
            )
        config[section][key] = str(destination / value[len(container_current) + 1 :])

    path = destination / "build-config.json"
    return path, config


def write_build_config(config_dir: Path, tiles_dir: Path, variant: Variant, build_id: str) -> Path:
    path, config = build_config(config_dir, tiles_dir, variant, build_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    Path(config["mjolnir"]["tile_dir"]).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    return path


def tile_build_commands(config_path: Path, pbf: Path) -> list[list[str]]:
    """The binaries a variant's build runs, in order.

    valhalla_build_tiles writes the tile directory; valhalla_build_extract packs
    it into the tar the service reads (tile_extract), which is what the serving
    config names. Neither has been run in this environment.
    """
    return [
        ["valhalla_build_tiles", "-c", str(config_path), str(pbf)],
        ["valhalla_build_extract", "-c", str(config_path), "-v"],
    ]


# --- Promotion ----------------------------------------------------------------


def _replace_symlink(link: Path, target: str) -> None:
    """Point `link` at `target` atomically.

    A bind mount of a path that does not exist yet makes Docker create an empty
    directory there, so on a first deploy `current` may be a real, empty
    directory rather than a symlink. That is removed; anything else in the way
    is not ours and is an error.
    """
    if link.is_dir() and not link.is_symlink():
        if any(link.iterdir()):
            raise FileExistsError(f"{link} is a non-empty directory, not a promotion symlink")
        link.rmdir()
    staging = link.with_name(link.name + ".new")
    if staging.is_symlink() or staging.exists():
        staging.unlink()
    os.symlink(target, staging)
    os.replace(staging, link)


def promoted_build_id(tiles_dir: Path, variant: Variant, link: str = CURRENT) -> str | None:
    path = Path(tiles_dir) / variant.value / link
    if not path.is_symlink():
        return None
    return os.readlink(path)


def promote(tiles_dir: Path, variant: Variant, build_id: str) -> str | None:
    """Make a dated build the served one. Returns the build it replaced."""
    variant_dir = Path(tiles_dir) / variant.value
    target = variant_dir / build_id
    if not (target / "tiles.tar").is_file():
        raise FileNotFoundError(f"{target} holds no tiles.tar; nothing to promote")
    before = promoted_build_id(tiles_dir, variant)
    if before is not None:
        _replace_symlink(variant_dir / PREVIOUS, before)
    _replace_symlink(variant_dir / CURRENT, build_id)
    return before


def demote(tiles_dir: Path, variant: Variant) -> str | None:
    """Put `previous` back as `current`. Returns the build now served."""
    variant_dir = Path(tiles_dir) / variant.value
    previous = promoted_build_id(tiles_dir, variant, PREVIOUS)
    if previous is None:
        return None
    _replace_symlink(variant_dir / CURRENT, previous)
    return previous


# --- Reading a build back -------------------------------------------------------


def trace_attributes_request(edge: Sequence[Sequence[float]], attributes: Sequence[str]) -> dict:
    """A map-snapped trace along one known edge, asking for named attributes."""
    return {
        "shape": [{"lon": lon, "lat": lat} for lon, lat in edge],
        "costing": "bicycle",
        "shape_match": "map_snap",
        "filters": {"attributes": list(attributes), "action": "include"},
    }


def trace_attributes(
    run: Callable[[Sequence[str]], str], config_path: Path, request: dict
) -> list[dict]:
    """Ask valhalla_service, in one-shot mode, what the built tiles say.

    `valhalla_service <config> <action> <json>` answers a single request and
    exits without starting the HTTP server, which is what lets validation read
    a build before anything serves it and without a second container. The
    output is the response JSON; the build's own log lines, if any, precede it,
    so the parse starts at the first brace.

    NOT EXECUTED AGAINST A REAL BUILD: no Valhalla binary exists in this
    environment. The one-shot invocation form and the attribute names are from
    the 3.5.1 documentation; the first real rebuild is what confirms them.
    """
    output = run(["valhalla_service", str(config_path), "trace_attributes", json.dumps(request)])
    start = output.find("{")
    if start < 0:
        raise ValueError("valhalla_service returned no JSON")
    return json.loads(output[start:]).get("edges", [])


def sample_grade(
    run: Callable[[Sequence[str]], str], config_path: Path, steep_edge: Sequence[Sequence[float]]
) -> float:
    """The largest weighted grade along the known steep edge, in percent."""
    edges = trace_attributes(
        run,
        config_path,
        trace_attributes_request(steep_edge, ["edge.weighted_grade", "edge.max_upward_grade"]),
    )
    grades = [abs(float(e.get("weighted_grade") or 0.0)) for e in edges]
    grades += [abs(float(e.get("max_upward_grade") or 0.0)) for e in edges]
    return max(grades, default=0.0)


def sample_cycle_lane(
    run: Callable[[Sequence[str]], str], config_path: Path, edge: Sequence[Sequence[float]]
) -> str | None:
    """What the tiles say about the cycle lane on a known tier-1 street.

    The remap writes cycleway=track onto a tier-1 way that has no cycleway tag
    of its own, and Valhalla stores that as a separated cycle lane. A residential
    street with no facility in OSM therefore reads back "separated" only if this
    project's transform ran and its derived tags survived into the graph.
    """
    edges = trace_attributes(
        run, config_path, trace_attributes_request(edge, ["edge.cycle_lane", "edge.way_id"])
    )
    lanes = [e.get("cycle_lane") for e in edges if e.get("cycle_lane")]
    return lanes[0] if lanes else None


# --- The disk gate ---------------------------------------------------------------


@dataclass(frozen=True)
class DiskGate:
    total: int
    used: int
    free: int
    required: int
    fraction_after: float


class DiskGateRefused(RuntimeError):
    """A second full tile set would not fit; the rebuild does not start."""


def directory_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:  # pragma: no cover - a file vanishing mid-walk
                continue
    return total


def current_set_bytes(tiles_dir: Path) -> int:
    """The size of the tile set being served, across every variant."""
    total = 0
    for variant in Variant:
        build_id = promoted_build_id(tiles_dir, variant)
        if build_id is not None:
            total += directory_bytes(build_dir(tiles_dir, variant, build_id))
    return total


def check_disk_gate(
    tiles_dir: Path,
    source_bytes: int,
    minimum_free: int,
    fraction: float,
    disk_usage: Callable[[str], os.statvfs_result | shutil._ntuple_diskusage] = shutil.disk_usage,
) -> DiskGate:
    """Refuse a rebuild that cannot fit a second full set on the data volume.

    A second set is the served tiles again, plus the three variant extracts the
    build writes from the source, plus the source once more for scratch. With
    no served set yet there is nothing to measure, so the configured floor
    stands in until the first build has been sized. The gate is the plan's
    80 percent alert made hard: the build may not take the volume past it.
    """
    tiles_dir = Path(tiles_dir)
    tiles_dir.mkdir(parents=True, exist_ok=True)
    usage = disk_usage(str(tiles_dir))
    required = max(current_set_bytes(tiles_dir) + 4 * source_bytes, minimum_free)
    fraction_after = (usage.used + required) / usage.total if usage.total else 1.0
    gate = DiskGate(usage.total, usage.used, usage.free, required, fraction_after)
    if usage.free < required or fraction_after > fraction:
        raise DiskGateRefused(
            f"a second tile set needs {required / 1024**3:.1f} GiB; the data volume has "
            f"{usage.free / 1024**3:.1f} GiB free and would be {fraction_after:.0%} full, "
            f"over the {fraction:.0%} gate. Grow the volume, which is an online resize."
        )
    return gate
