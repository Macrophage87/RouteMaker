"""Checkpoints that outlive the machine (owner decision 459c; docs/CLOUD-REBUILD-PLAN.md):
the run key, the durable store and the validation of a checkpoint written elsewhere.

No database and no binaries: the module takes paths, mappings and a store, so a
"fresh machine" here is a second temporary directory with copies whose mtimes differ.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pipeline import checkpoint, checkpoint_store
from pipeline.checkpoint_store import (
    CheckpointStore,
    LocalDirectoryStore,
    StoreError,
    content_only,
    portable_problem,
    publish_checkpoint,
    restore_checkpoint,
)
from pipeline.variants import Variant

RUN = "rebuild-20261013-8408"
BUILD = "20261013T080000Z"
NOW = 1_800_000_000.0
DAY = 24 * 3600


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def graph_files(directory: Path) -> dict[str, Path]:
    return {
        "tiles.tar": write(directory / "tiles.tar", b"tiles" * 1000),
        "admin.sqlite": write(directory / "admin.sqlite", b"admin"),
        "build.log": write(directory / "build.log", b"built\n"),
    }


def graph_manifest(fingerprint: dict) -> dict:
    return {
        "format": checkpoint.FORMAT,
        "variant": Variant.STANDARD.value,
        "build_id": BUILD,
        "job_id": 8408,
        "fingerprint": fingerprint,
    }


FINGERPRINT = {
    "variant_pbf_sha256": "a" * 64,
    "merged_pbf_sha256": "b" * 64,
    "build_config_sha256": "c" * 64,
    "elevation": "d" * 64,
}


@pytest.fixture
def store(tmp_path) -> LocalDirectoryStore:
    return LocalDirectoryStore(tmp_path / "durable")


def published(store, tmp_path, fingerprint=FINGERPRINT, now=NOW) -> dict:
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    return publish_checkpoint(
        store,
        prefix,
        # The local manifest's own (version 1) fingerprint is replaced by the
        # portable one the caller passes.
        graph_manifest({**fingerprint, "elevation": "v1 names, sizes and mtimes"}),
        graph_files(tmp_path / "first-machine"),
        fingerprint=fingerprint,
        run_key=RUN,
        hasher=checkpoint.Hasher(),
        now=now,
    )


# --- Keys ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["", "Rebuild-1", "-x", "a/b", "a..b/../c", "x" * 65, "rebuild 1", None, "é"]
)
def test_a_run_key_is_narrow(key):
    with pytest.raises(StoreError):
        checkpoint_store.validate_run_key(key)


def test_the_default_run_key_names_the_day_and_the_job():
    assert checkpoint_store.run_key_for_job(8408, "20261013") == RUN
    for job, day in [(-1, "20261013"), ("8408", "20261013"), (8408, "2026-10-13"), (8408, "")]:
        with pytest.raises(StoreError):
            checkpoint_store.run_key_for_job(job, day)


@pytest.mark.parametrize("key", ["../x", "/abs", "a//b", "a/../b", "a/.hidden", ""])
def test_a_store_key_cannot_leave_the_store(store, tmp_path, key):
    source = write(tmp_path / "f", b"x")
    with pytest.raises(StoreError):
        store.put_file(key, source)
    with pytest.raises(StoreError):
        store.get_json(key)


def test_the_local_store_is_a_checkpoint_store(store):
    assert isinstance(store, CheckpointStore)


# --- The local store ----------------------------------------------------------------


def test_local_store_round_trip(store, tmp_path):
    source = write(tmp_path / "in.bin", b"payload")
    store.put_file("runs/r/files/in.bin", source)
    store.put_json("runs/r/manifest.json", {"format": 1})
    assert store.get_json("runs/r/manifest.json") == {"format": 1}
    out = tmp_path / "out" / "in.bin"
    assert store.get_file("runs/r/files/in.bin", out)
    assert out.read_bytes() == b"payload"
    assert store.list_keys("runs/r") == ["runs/r/files/in.bin", "runs/r/manifest.json"]
    assert not store.get_file("runs/r/files/absent", tmp_path / "absent")
    assert not (tmp_path / "absent").exists()
    store.delete("runs/r/manifest.json")
    store.delete("runs/r/manifest.json")  # absent is not an error
    assert store.get_json("runs/r/manifest.json") is None


def test_local_store_reads_a_damaged_manifest_as_none(store):
    path = store.root / "runs" / "r" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"format": 1, "trunc', encoding="utf-8")
    assert store.get_json("runs/r/manifest.json") is None
    path.write_text("[1, 2]", encoding="utf-8")
    assert store.get_json("runs/r/manifest.json") is None


def test_local_store_lists_no_half_written_file(store):
    write(store.root / "runs" / "r" / "files" / "tiles.tar.part", b"half")
    write(store.root / "runs" / "r" / "manifest.json.tmp", b"{}")
    assert store.list_keys("runs/r") == []
    assert store.list_keys("runs/nothing") == []


# --- Publishing -----------------------------------------------------------------------


def test_publish_writes_the_files_then_the_manifest(tmp_path):
    order = []

    class Recording(LocalDirectoryStore):
        def put_file(self, key, source):
            order.append(("file", key))
            super().put_file(key, source)

        def put_json(self, key, payload):
            order.append(("manifest", key))
            super().put_json(key, payload)

        def delete(self, key):
            order.append(("delete", key))
            super().delete(key)

    stored = published(Recording(tmp_path / "durable"), tmp_path)
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    assert order[0] == ("delete", f"{prefix}/manifest.json")
    assert order[-1] == ("manifest", f"{prefix}/manifest.json")
    assert sorted(key for kind, key in order if kind == "file") == [
        f"{prefix}/files/admin.sqlite",
        f"{prefix}/files/build.log",
        f"{prefix}/files/tiles.tar",
    ]
    assert stored["run_key"] == RUN
    assert stored["store_format"] == checkpoint_store.STORE_FORMAT
    assert stored["published_at"] == NOW
    assert set(stored["files"]) == {"tiles.tar", "admin.sqlite", "build.log"}
    assert stored["files"]["tiles.tar"]["size"] == 5000


def test_publish_keeps_the_fingerprint_by_content_only(store, tmp_path):
    fingerprint = {
        "inputs": {"source_extract": {"size": 3, "mtime_ns": 123, "sha256": "e" * 64}},
        "validation": "v",
    }
    stored = published(store, tmp_path, fingerprint=fingerprint)
    assert stored["fingerprint"] == {
        "inputs": {"source_extract": {"size": 3, "sha256": "e" * 64}},
        "validation": "v",
    }


def test_publish_refuses_a_checkpoint_missing_a_file(store, tmp_path):
    files = graph_files(tmp_path / "m")
    files["tz_world.sqlite"] = tmp_path / "m" / "tz_world.sqlite"
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    with pytest.raises(StoreError, match="tz_world.sqlite not written"):
        publish_checkpoint(
            store,
            prefix,
            graph_manifest(FINGERPRINT),
            files,
            fingerprint=FINGERPRINT,
            run_key=RUN,
            hasher=checkpoint.Hasher(),
        )
    assert store.list_keys(prefix) == []


def test_a_failed_republish_leaves_no_manifest(tmp_path):
    """Replacing a checkpoint deletes its manifest first: a publish that dies part way
    through leaves the old files and no manifest, never an old manifest over new files."""

    class FailsOnTiles(LocalDirectoryStore):
        fail = False

        def put_file(self, key, source):
            if self.fail and key.endswith("tiles.tar"):
                raise StoreError("disk full")
            super().put_file(key, source)

    store = FailsOnTiles(tmp_path / "durable")
    published(store, tmp_path)
    store.fail = True
    with pytest.raises(StoreError):
        published(store, tmp_path)
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    assert store.get_json(f"{prefix}/manifest.json") is None


# --- Restoring on a fresh machine ---------------------------------------------------


def destinations(directory: Path) -> dict[str, Path]:
    return {name: directory / name for name in ("tiles.tar", "admin.sqlite", "build.log")}


def test_a_fresh_machine_restores_and_verifies_every_file(store, tmp_path):
    published(store, tmp_path)
    fresh = tmp_path / "second-machine"
    restored = restore_checkpoint(
        store,
        checkpoint_store.graph_prefix(RUN, Variant.STANDARD),
        destinations(fresh),
        hasher=checkpoint.Hasher(),
    )
    assert restored.problem is None
    assert restored.manifest["build_id"] == BUILD
    assert sorted(restored.downloaded) == ["admin.sqlite", "build.log", "tiles.tar"]
    assert (fresh / "tiles.tar").read_bytes() == b"tiles" * 1000
    assert not list(fresh.glob("*.restore"))


def test_a_machine_that_kept_its_disk_downloads_nothing(store, tmp_path):
    published(store, tmp_path)
    restored = restore_checkpoint(
        store,
        checkpoint_store.graph_prefix(RUN, Variant.STANDARD),
        destinations(tmp_path / "first-machine"),
        hasher=checkpoint.Hasher(),
    )
    assert restored.problem is None
    assert restored.downloaded == []
    assert sorted(restored.already_local) == ["admin.sqlite", "build.log", "tiles.tar"]


def test_a_stale_local_file_is_replaced_by_the_stored_one(store, tmp_path):
    published(store, tmp_path)
    fresh = tmp_path / "second-machine"
    write(fresh / "tiles.tar", b"an older build")
    restored = restore_checkpoint(
        store,
        checkpoint_store.graph_prefix(RUN, Variant.STANDARD),
        destinations(fresh),
        hasher=checkpoint.Hasher(),
    )
    assert restored.problem is None
    assert "tiles.tar" in restored.downloaded
    assert (fresh / "tiles.tar").read_bytes() == b"tiles" * 1000


def test_a_damaged_stored_file_is_not_a_checkpoint(store, tmp_path):
    published(store, tmp_path)
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    stored_tar = store.root.joinpath(*f"{prefix}/files/tiles.tar".split("/"))
    data = bytearray(stored_tar.read_bytes())
    data[10] ^= 0xFF  # same size, one flipped byte
    stored_tar.write_bytes(bytes(data))
    fresh = tmp_path / "second-machine"
    restored = restore_checkpoint(store, prefix, destinations(fresh), hasher=checkpoint.Hasher())
    assert restored.manifest is None
    assert restored.problem == "its tiles.tar does not hash to what the manifest records"
    assert not (fresh / "tiles.tar").exists()
    assert not list(fresh.glob("*.restore"))


def test_a_damaged_local_file_is_downloaded_again(store, tmp_path):
    """Same size, same mtime, one flipped byte: the hash decides, read again in full
    even though the hasher has seen the file."""
    published(store, tmp_path)
    local = tmp_path / "first-machine"
    tar = local / "tiles.tar"
    hasher = checkpoint.Hasher()
    hasher.sha256(tar)  # remembered before the damage
    stat = tar.stat()
    data = bytearray(tar.read_bytes())
    data[10] ^= 0xFF
    tar.write_bytes(bytes(data))
    os.utime(tar, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    restored = restore_checkpoint(
        store,
        checkpoint_store.graph_prefix(RUN, Variant.STANDARD),
        destinations(local),
        hasher=hasher,
    )
    assert restored.problem is None
    assert restored.downloaded == ["tiles.tar"]
    assert tar.read_bytes() == b"tiles" * 1000


def test_a_manifest_listing_fewer_files_than_wanted_is_not_a_checkpoint(store, tmp_path):
    published(store, tmp_path)
    places = destinations(tmp_path / "x")
    places["tz_world.sqlite"] = tmp_path / "x" / "tz_world.sqlite"
    restored = restore_checkpoint(
        store,
        checkpoint_store.graph_prefix(RUN, Variant.STANDARD),
        places,
        hasher=checkpoint.Hasher(),
    )
    assert restored.manifest is None
    assert restored.problem == "its manifest does not list tz_world.sqlite"


def test_a_failed_fetch_is_a_problem_not_an_exception(tmp_path):
    class Broken(LocalDirectoryStore):
        def get_file(self, key, destination):
            raise StoreError("connection reset")

    store = Broken(tmp_path / "durable")
    published(store, tmp_path)
    fresh = tmp_path / "second-machine"
    restored = restore_checkpoint(
        store,
        checkpoint_store.graph_prefix(RUN, Variant.STANDARD),
        destinations(fresh),
        hasher=checkpoint.Hasher(),
    )
    assert restored.manifest is None
    assert "could not be restored: connection reset" in restored.problem
    assert not fresh.exists() or not list(fresh.iterdir())


@pytest.mark.parametrize("name", ["tiles.tar.part", "build.log.tmp", "a/b", "..x", ""])
def test_publish_refuses_an_output_name_a_store_would_hide(store, tmp_path, name):
    files = {name: write(tmp_path / "m" / "f", b"x")}
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    store.put_json(f"{prefix}/manifest.json", {"format": 1})
    with pytest.raises(StoreError):
        publish_checkpoint(
            store,
            prefix,
            graph_manifest(FINGERPRINT),
            files,
            fingerprint=FINGERPRINT,
            run_key=RUN,
            hasher=checkpoint.Hasher(),
        )
    # Refused before anything in the store was touched.
    assert store.get_json(f"{prefix}/manifest.json") == {"format": 1}


def test_a_file_missing_from_the_store_is_not_a_checkpoint(store, tmp_path):
    published(store, tmp_path)
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    store.delete(f"{prefix}/files/admin.sqlite")
    restored = restore_checkpoint(
        store, prefix, destinations(tmp_path / "x"), hasher=checkpoint.Hasher()
    )
    assert restored.problem == "the store does not have its admin.sqlite"


def test_a_manifest_listing_a_file_with_no_place_is_not_a_checkpoint(store, tmp_path):
    published(store, tmp_path)
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    places = destinations(tmp_path / "x")
    del places["build.log"]
    restored = restore_checkpoint(store, prefix, places, hasher=checkpoint.Hasher())
    assert restored.problem == "its manifest lists 'build.log', which has no place here"


@pytest.mark.parametrize(
    "change",
    [
        {"store_format": 1},
        {"format": checkpoint.FORMAT + 1},
        {"files": {}},
        {"files": None},
    ],
)
def test_restore_refuses_a_manifest_of_another_shape(store, tmp_path, change):
    stored = published(store, tmp_path)
    prefix = checkpoint_store.graph_prefix(RUN, Variant.STANDARD)
    store.put_json(f"{prefix}/manifest.json", {**stored, **change})
    restored = restore_checkpoint(
        store, prefix, destinations(tmp_path / "x"), hasher=checkpoint.Hasher()
    )
    assert restored.manifest is None and restored.problem


def test_restore_with_no_manifest(store, tmp_path):
    restored = restore_checkpoint(
        store,
        checkpoint_store.graph_prefix(RUN, Variant.STANDARD),
        destinations(tmp_path / "x"),
        hasher=checkpoint.Hasher(),
    )
    assert restored.problem == "the store holds no manifest for it"


# --- Is it still this run's? --------------------------------------------------------


def problem(manifest, tiles_dir, **overrides):
    arguments = {
        "run_key": RUN,
        "measured_fingerprint": FINGERPRINT,
        "tiles_dir": tiles_dir,
        "max_age_s": 2 * DAY,
        "now": NOW + 3600,
        "variant": Variant.STANDARD,
        "build_id": BUILD,
    }
    arguments.update(overrides)
    return portable_problem(manifest, **arguments)


def graph_inputs(root: Path) -> list[Path]:
    """One machine's inputs for the standard graph under `root`, the same bytes on
    every machine. Returns the elevation tiles."""
    write(root / "rebuild" / "standard.osm.pbf", b"variant extract")
    write(root / "extracts" / "merged.osm.pbf", b"merged extract")
    write(root / "lua" / "graph.lua", b"-- the transform")
    return [
        write(root / "elevation" / "N38W077.hgt", b"height one"),
        write(root / "elevation" / "N39W077.hgt", b"height two"),
    ]


def measure_graph(root: Path, tiles: list[Path], *, concurrency: int) -> tuple[dict, dict]:
    """What a machine measures for the standard graph: version 1's fingerprint, and
    the portable one."""
    hasher = checkpoint.Hasher()
    build_dir = root / "tiles" / "standard" / BUILD
    v1 = checkpoint.graph_fingerprint(
        variant_pbf=root / "rebuild" / "standard.osm.pbf",
        merged_pbf=root / "extracts" / "merged.osm.pbf",
        config={"mjolnir": {"concurrency": concurrency, "tile_dir": str(build_dir / "tiles")}},
        build_dir=build_dir,
        lua_dirs=[root / "lua"],
        elevation_tiles=tiles,
        hasher=hasher,
        which=lambda name: None,
    )
    return v1, checkpoint_store.portable_graph_fingerprint(v1, tiles, hasher)


def test_a_graph_checkpoint_resumes_on_a_fresh_machine(store, tmp_path):
    """A real graph fingerprint published on one machine, and measured again on another
    whose files have the same bytes and new mtimes, matches."""
    first_tiles = graph_inputs(tmp_path / "one")
    first_v1, first = measure_graph(tmp_path / "one", first_tiles, concurrency=2)
    manifest = publish_checkpoint(
        store,
        checkpoint_store.graph_prefix(RUN, Variant.STANDARD),
        graph_manifest(first_v1),
        graph_files(tmp_path / "one" / "out"),
        fingerprint=first,
        run_key=RUN,
        hasher=checkpoint.Hasher(),
        now=NOW,
    )
    assert manifest["fingerprint"] == first
    tiles = graph_inputs(tmp_path / "two")
    for tile in tiles:
        os.utime(tile, (NOW, NOW))
    second_v1, second = measure_graph(tmp_path / "two", tiles, concurrency=4)
    # Version 1's elevation entry follows the mtimes, so on its own it would refuse.
    assert second_v1["elevation"] != first_v1["elevation"]
    assert problem(manifest, tmp_path / "tiles", measured_fingerprint=second) is None
    tiles[0].write_bytes(b"height ONE")
    _, changed = measure_graph(tmp_path / "two", tiles, concurrency=4)
    assert problem(manifest, tmp_path / "tiles", measured_fingerprint=changed) == (
        "these inputs changed since it was written: elevation"
    )


def test_another_run_is_never_picked_up_by_accident(store, tmp_path):
    found = problem(published(store, tmp_path), tmp_path / "tiles", run_key="rebuild-20261020-8501")
    assert "belongs to run 'rebuild-20261013-8408'" in found


def test_an_old_checkpoint_is_refused(store, tmp_path):
    manifest = published(store, tmp_path)
    found = problem(manifest, tmp_path / "tiles", now=NOW + 3 * DAY)
    assert "past the 48.0 hour limit" in found
    assert "in the future" in problem(manifest, tmp_path / "tiles", now=NOW - 3600)


def test_a_promoted_build_is_never_resumed(store, tmp_path):
    tiles_dir = tmp_path / "tiles"
    (tiles_dir / "standard" / BUILD).mkdir(parents=True)
    os.symlink(BUILD, tiles_dir / "standard" / "current")
    assert "promoted build" in problem(published(store, tmp_path), tiles_dir)


def test_the_build_and_the_variant_must_be_this_runs(store, tmp_path):
    manifest = published(store, tmp_path)
    assert "this run's build is 20261014T080000Z" in problem(
        manifest, tmp_path / "tiles", build_id="20261014T080000Z"
    )
    assert "not offroad" in problem(manifest, tmp_path / "tiles", variant=Variant.OFFROAD)
    assert "not a build id" in problem({**manifest, "build_id": "../x"}, tmp_path / "tiles")


def test_a_changed_input_is_named(store, tmp_path):
    measured = {**FINGERPRINT, "build_config_sha256": "f" * 64}
    found = problem(published(store, tmp_path), tmp_path / "tiles", measured_fingerprint=measured)
    assert found == "these inputs changed since it was written: build_config_sha256"


def test_new_mtimes_are_not_a_changed_input(store, tmp_path):
    """The point of version 2: the same bytes restored with new mtimes still match."""
    recorded = {
        "inputs": {
            "source_extract": {"size": 3, "mtime_ns": 111, "sha256": "e" * 64},
            "code": {"src": "s"},
        },
        "validation": "v1",
    }
    manifest = published(store, tmp_path, fingerprint=recorded)
    measured = json.loads(json.dumps(recorded))
    measured["inputs"]["source_extract"]["mtime_ns"] = 999
    measured["validation"] = "v2"  # the staging checks re-run; not a refusal
    assert problem(manifest, tmp_path / "tiles", measured_fingerprint=measured) is None
    measured["inputs"]["source_extract"]["sha256"] = "0" * 64
    assert problem(manifest, tmp_path / "tiles", measured_fingerprint=measured) == (
        "these inputs changed since it was written: source_extract.sha256"
    )


def test_content_only_reaches_every_depth():
    assert content_only({"a": [{"mtime_ns": 1, "size": 2}], "mtime_ns": 3}) == {"a": [{"size": 2}]}


def test_the_portable_elevation_digest_ignores_mtimes(tmp_path):
    tile = write(tmp_path / "N38W077.hgt", b"height")
    fingerprint = {**FINGERPRINT}
    before = checkpoint_store.portable_graph_fingerprint(fingerprint, [tile], checkpoint.Hasher())
    os.utime(tile, (1, 1))
    after = checkpoint_store.portable_graph_fingerprint(fingerprint, [tile], checkpoint.Hasher())
    assert before == after
    assert before["elevation"] != FINGERPRINT["elevation"]
    # Version 1's digest follows the mtime, which a restore rewrites.
    v1_before = checkpoint.elevation_digest([tile])
    os.utime(tile, (2, 2))
    assert checkpoint.elevation_digest([tile]) != v1_before
    tile.write_bytes(b"HEIGHT")
    changed = checkpoint_store.portable_graph_fingerprint(fingerprint, [tile], checkpoint.Hasher())
    assert changed["elevation"] != before["elevation"]


# --- Runs -----------------------------------------------------------------------------


def test_runs_are_listed_and_discarded_manifests_first(tmp_path):
    deleted = []

    class Recording(LocalDirectoryStore):
        def delete(self, key):
            deleted.append(key)
            super().delete(key)

    store = Recording(tmp_path / "durable")
    published(store, tmp_path)
    store.put_json(f"{checkpoint_store.classification_prefix(RUN)}/manifest.json", {"format": 1})
    store.put_json("runs/rebuild-20261020-8501/classification/manifest.json", {"format": 1})
    assert checkpoint_store.list_runs(store) == [RUN, "rebuild-20261020-8501"]
    deleted.clear()
    assert checkpoint_store.discard_run(store, RUN) == 5
    manifests = [key for key in deleted if key.endswith("/manifest.json")]
    assert deleted[: len(manifests)] == manifests and len(manifests) == 2
    assert checkpoint_store.list_runs(store) == ["rebuild-20261020-8501"]
