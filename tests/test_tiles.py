"""The tile directories: dated builds, promotion, and the disk gate."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from pipeline import tiles
from pipeline.variants import Variant

REPO = Path(__file__).resolve().parents[1]
GIB = 1024**3


def test_the_build_config_retargets_every_tile_path_to_the_dated_directory(tmp_path) -> None:
    """The serving config names the graph being served, which is mounted
    read-only and is not where a build may write. The build config is the same
    file with each tile path moved under the dated directory, and nothing else
    changed."""
    path, config = tiles.build_config(
        REPO / "valhalla", tmp_path / "tiles", Variant.NO_TRAIL, "20260917T080000Z"
    )
    build = tmp_path / "tiles" / "no-trail" / "20260917T080000Z"
    assert path == build / "build-config.json"
    assert config["mjolnir"]["tile_dir"] == str(build / "tiles")
    assert config["mjolnir"]["tile_extract"] == str(build / "tiles.tar")
    assert config["mjolnir"]["admin"] == str(build / "admin.sqlite")
    assert config["mjolnir"]["timezone"] == str(build / "tz_world.sqlite")

    serving = json.loads((REPO / "valhalla" / "valhalla-no-trail.json").read_text())
    for section in serving:
        if section == "mjolnir":
            continue
        assert config[section] == serving[section], f"{section} must be untouched"
    assert config["mjolnir"]["graph_lua_name"] == serving["mjolnir"]["graph_lua_name"]


def test_a_config_whose_tile_paths_are_not_its_own_variants_is_refused(tmp_path) -> None:
    """Three configs naming one directory are three builds overwriting each
    other, and only the last variant's graph survives. The retarget refuses to
    proceed from such a config rather than building somewhere shared."""
    shared = tmp_path / "conf"
    shared.mkdir()
    config = json.loads((REPO / "valhalla" / "valhalla-ebike.json").read_text())
    config["mjolnir"]["tile_dir"] = "/data/valhalla"
    (shared / "valhalla-ebike.json").write_text(json.dumps(config))
    with pytest.raises(tiles.TilePathsNotPerVariant, match="another variant"):
        tiles.build_config(shared, tmp_path / "tiles", Variant.EBIKE, "b1")


def make_build(root: Path, variant: Variant, build_id: str) -> Path:
    build = root / variant.value / build_id
    build.mkdir(parents=True)
    (build / "tiles.tar").write_bytes(b"tar")
    return build


def test_promotion_replaces_current_atomically_and_keeps_the_previous(tmp_path) -> None:
    make_build(tmp_path, Variant.STANDARD, "b1")
    make_build(tmp_path, Variant.STANDARD, "b2")

    assert tiles.promote(tmp_path, Variant.STANDARD, "b1") is None
    assert os.readlink(tmp_path / "standard" / "current") == "b1"
    assert not (tmp_path / "standard" / "previous").exists()

    assert tiles.promote(tmp_path, Variant.STANDARD, "b2") == "b1"
    assert os.readlink(tmp_path / "standard" / "current") == "b2"
    assert os.readlink(tmp_path / "standard" / "previous") == "b1"
    assert not (tmp_path / "standard" / "current.new").exists(), "the temporary link is gone"

    assert tiles.demote(tmp_path, Variant.STANDARD) == "b1"
    assert os.readlink(tmp_path / "standard" / "current") == "b1"


def test_a_build_without_an_extract_cannot_be_promoted(tmp_path) -> None:
    (tmp_path / "ebike" / "b1").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="tiles.tar"):
        tiles.promote(tmp_path, Variant.EBIKE, "b1")


def test_the_empty_directory_docker_creates_for_a_missing_mount_is_replaced(tmp_path) -> None:
    """A bind mount of a path that does not exist yet makes Docker create an
    empty directory there, so on a first deploy `current` is a real directory.
    Promotion has to get past that; a non-empty one is not ours to remove."""
    make_build(tmp_path, Variant.STANDARD, "b1")
    (tmp_path / "standard" / "current").mkdir()
    tiles.promote(tmp_path, Variant.STANDARD, "b1")
    assert os.readlink(tmp_path / "standard" / "current") == "b1"

    make_build(tmp_path, Variant.EBIKE, "b1")
    (tmp_path / "ebike" / "current").mkdir()
    (tmp_path / "ebike" / "current" / "something").write_text("x")
    with pytest.raises(FileExistsError):
        tiles.promote(tmp_path, Variant.EBIKE, "b1")


def usage(total: int, used: int):
    return lambda path: shutil._ntuple_diskusage(total=total, used=used, free=total - used)


def test_the_gate_sizes_a_second_set_from_the_served_one(tmp_path) -> None:
    """Two full sets: the served tiles again, plus the variant extracts the
    build writes from the source and the source once more for scratch."""
    for variant in Variant:
        build = make_build(tmp_path, variant, "b1")
        (build / "tiles.tar").write_bytes(b"\0" * (3 * GIB // 1024))  # 3 MiB each
        tiles.promote(tmp_path, variant, "b1")
    served = tiles.current_set_bytes(tmp_path)
    assert served == 3 * 3 * GIB // 1024

    gate = tiles.check_disk_gate(
        tmp_path,
        source_bytes=GIB,
        minimum_free=0,
        fraction=0.8,
        disk_usage=usage(100 * GIB, 10 * GIB),
    )
    assert gate.required == served + 4 * GIB
    assert gate.fraction_after == pytest.approx((10 * GIB + served + 4 * GIB) / (100 * GIB))


def test_the_floor_applies_until_a_first_set_has_been_measured(tmp_path) -> None:
    gate = tiles.check_disk_gate(
        tmp_path,
        source_bytes=GIB,
        minimum_free=20 * GIB,
        fraction=0.8,
        disk_usage=usage(100 * GIB, 10 * GIB),
    )
    assert gate.required == 20 * GIB


def test_the_gate_is_the_eighty_percent_alert_made_hard(tmp_path) -> None:
    """Enough free space in absolute terms, but the build would take the volume
    past the alert threshold: refused, with the remedy named."""
    with pytest.raises(tiles.DiskGateRefused, match="online resize"):
        tiles.check_disk_gate(
            tmp_path,
            source_bytes=GIB,
            minimum_free=20 * GIB,
            fraction=0.8,
            disk_usage=usage(100 * GIB, 65 * GIB),
        )
    # And refused outright when the set simply does not fit.
    with pytest.raises(tiles.DiskGateRefused):
        tiles.check_disk_gate(
            tmp_path,
            source_bytes=GIB,
            minimum_free=20 * GIB,
            fraction=1.0,
            disk_usage=usage(100 * GIB, 90 * GIB),
        )
    # Passes when both hold.
    tiles.check_disk_gate(
        tmp_path,
        source_bytes=GIB,
        minimum_free=20 * GIB,
        fraction=0.8,
        disk_usage=usage(100 * GIB, 50 * GIB),
    )


def test_trace_attributes_is_asked_in_one_shot_mode_and_parsed_past_the_log(tmp_path) -> None:
    """valhalla_service <config> <action> <json> answers one request without
    starting the server; its own log lines precede the JSON on stdout."""
    seen = []

    def run(command):
        seen.append(list(command))
        return "2026/09/17 [INFO] Tile extract successfully loaded\n" + json.dumps(
            {"edges": [{"weighted_grade": -4.5, "cycle_lane": "separated", "way_id": 100}]}
        )

    config = tmp_path / "build-config.json"
    edge = ((-77.10, 38.93), (-77.11, 38.94))
    assert tiles.sample_grade(run, config, edge) == 4.5
    assert tiles.sample_cycle_lane(run, config, edge) == "separated"

    for command in seen:
        assert command[:3] == ["valhalla_service", str(config), "trace_attributes"]
        request = json.loads(command[3])
        assert request["shape_match"] == "map_snap"
        assert request["costing"] == "bicycle"
        assert request["shape"] == [{"lon": -77.10, "lat": 38.93}, {"lon": -77.11, "lat": 38.94}]
    assert "edge.weighted_grade" in json.loads(seen[0][3])["filters"]["attributes"]
    assert "edge.cycle_lane" in json.loads(seen[1][3])["filters"]["attributes"]


def test_an_edge_with_no_grade_reads_as_zero_not_as_missing(tmp_path) -> None:
    """The validation compares against zero; a graph built without elevation
    reports no grade key at all, which must read as zero and fail, not as an
    exception in the sampler."""

    def run(command):
        return json.dumps({"edges": [{"way_id": 100}]})

    assert tiles.sample_grade(run, tmp_path / "c.json", ((0, 0), (1, 1))) == 0.0
    assert tiles.sample_cycle_lane(run, tmp_path / "c.json", ((0, 0), (1, 1))) is None
