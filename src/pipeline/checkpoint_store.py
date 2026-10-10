"""Checkpoints that outlive the machine: version 2 of the rebuild's checkpoints.

Owner decision 459c: the production rebuild runs on an AWS on-demand or spot
instance per rebuild (FOLLOWUP-CLOUD-REBUILD), and "for spot, checkpoints live on
durable storage and a reclaimed instance resumes on a new one", so resuming across
jobs and instances (the checkpoint design's version 2) becomes required. The plan
is docs/CLOUD-REBUILD-PLAN.md; what version 1 does is docs/OPERATIONS.md, "Rebuild
checkpoints", and `pipeline.checkpoint`.

Version 1 keeps a checkpoint on the rebuild's own disk and keys it on the
Procrastinate job id. This module adds three things, and wires none of them into
`pipeline.run` (that waits on the questions in the plan):

- **A run key.** A short name the launcher gives a rebuild and hands to every
  instance that works on it (`rebuild-20261013-8408`). It, not the job id or the
  host, is what a fresh machine looks a checkpoint up by.
- **A durable store** (`CheckpointStore`) with one implementation here,
  `LocalDirectoryStore`, a directory on a volume that survives the instance. An S3
  store implements the same six methods later; nothing here imports an AWS SDK.
- **Portable validation.** A checkpoint written on another machine is used only if
  its manifest is whole, names this run, is young enough, its fingerprint matches
  what is measured here **by content alone** (a restore from a snapshot or S3
  rewrites every mtime, which version 1 compares), and every file it lists hashes,
  after the download, to what the manifest says.

The rule is version 1's: a checkpoint is a manifest written last, and it is reused
only if every input it depends on is measured again and matches. In a store with
no rename, "written last" is an order: the files first, then the manifest, and
replacing or discarding a checkpoint deletes the manifest first.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import checkpoint
from .retention import BUILD_ID
from .variants import Variant

logger = logging.getLogger(__name__)

# The store's own format, recorded beside version 1's `format` in every manifest a
# store holds. A manifest of another store format is not a checkpoint.
STORE_FORMAT = 2

# A run key: lowercase letters, digits and hyphens, starting with a letter or a
# digit, at most 64 characters. Narrow on purpose: it becomes a path segment here
# and an object key prefix in S3, and it is typed by hand in a resume command.
RUN_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# One segment of a store key. No `..`, no empty segment, no leading slash: a key
# can never name something outside the store's root.
KEY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

RUNS = "runs"
MANIFEST = "manifest.json"
FILES = "files"
CLASSIFICATION = "classification"
GRAPHS = "graphs"

# Facts that describe where and when a file was written, not what it holds. A
# portable comparison leaves them out (the sha256 beside them covers the content).
NON_CONTENT_KEYS = frozenset({"mtime_ns"})

# How far in the future a checkpoint's publication time may be before it is
# refused: two machines' clocks disagree by a little, never by minutes.
CLOCK_SKEW_S = 300

# Endings a store keeps for its own half-written objects, which `list_keys` never
# lists; an output name may not end in one.
TEMPORARY_SUFFIXES = (".part", ".tmp")


class StoreError(RuntimeError):
    """The store refused or failed an operation (a bad key, an I/O error)."""


def validate_run_key(run_key: str) -> str:
    if not isinstance(run_key, str) or not RUN_KEY.match(run_key):
        raise StoreError(
            f"{run_key!r} is not a run key (lowercase letters, digits and hyphens, "
            "at most 64 characters)"
        )
    return run_key


def run_key_for_job(job_id: int, started: str) -> str:
    """The run key a launcher derives from the job it serves and the UTC day it
    started (`YYYYMMDD`): `rebuild-20261013-8408`. Only a default; any key that
    passes `validate_run_key` will do, as long as every instance of the run is
    handed the same one."""
    if not isinstance(job_id, int) or job_id < 0:
        raise StoreError(f"{job_id!r} is not a job id")
    if not re.fullmatch(r"\d{8}", started or ""):
        raise StoreError(f"{started!r} is not a UTC day (YYYYMMDD)")
    return validate_run_key(f"rebuild-{started}-{job_id}")


def validate_key(key: str) -> str:
    segments = key.split("/") if isinstance(key, str) else []
    if not segments or not all(KEY_SEGMENT.match(segment) for segment in segments):
        raise StoreError(f"{key!r} is not a store key")
    return key


# --- The store -------------------------------------------------------------------


class CheckpointStore(ABC):
    """Durable storage for checkpoints, keyed by `/`-separated keys.

    The contract an implementation must keep, and all this module relies on:

    - `put_file` and `put_json` are atomic per key: a reader sees the whole new
      object or the previous state, never part of one. (A local rename gives
      this; so does an S3 PUT.)
    - A `get` after a `put` or a `delete` of the same key that returned sees it
      (S3 has had this read-after-write consistency since 2020).
    - Nothing is atomic across keys. Ordering across keys is the caller's job,
      and this module does it: files first, the manifest last.
    - `get_json` returns None for an absent key and for one that is not a JSON
      object; it never raises for a missing or damaged manifest.
    """

    @abstractmethod
    def put_file(self, key: str, source: Path) -> None: ...

    @abstractmethod
    def get_file(self, key: str, destination: Path) -> bool:
        """Copy the object to `destination` (replacing it); False if absent."""

    @abstractmethod
    def put_json(self, key: str, payload: Mapping) -> None: ...

    @abstractmethod
    def get_json(self, key: str) -> dict | None: ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete one object; deleting an absent key is not an error."""

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]:
        """Every key under `prefix/`, sorted."""


class LocalDirectoryStore(CheckpointStore):
    """A store in a directory: on a volume that outlives the instance (an EBS
    volume moved to the replacement), or on the rebuild's own disk for tests and
    for a host that is not replaced. Every write goes to a temporary file in the
    same directory, is fsynced and renamed into place, and the directory fsynced,
    as `checkpoint.atomic_write_json` does."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*validate_key(key).split("/"))

    def put_file(self, key: str, source: Path) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".part")
        try:
            shutil.copyfile(source, temporary)
            checkpoint.fsync_path(temporary)
            os.replace(temporary, target)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise StoreError(f"could not store {key}: {error}") from error
        self._sync_dir(target.parent)

    def get_file(self, key: str, destination: Path) -> bool:
        source = self._path(key)
        if not source.is_file():
            return False
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        try:
            shutil.copyfile(source, temporary)
            checkpoint.fsync_path(temporary)
            os.replace(temporary, destination)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise StoreError(f"could not fetch {key}: {error}") from error
        self._sync_dir(destination.parent)
        return True

    def put_json(self, key: str, payload: Mapping) -> None:
        try:
            checkpoint.atomic_write_json(self._path(key), payload)
        except OSError as error:
            raise StoreError(f"could not store {key}: {error}") from error

    def get_json(self, key: str) -> dict | None:
        try:
            data = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise StoreError(f"could not delete {key}: {error}") from error
        self._sync_dir(path.parent)

    def list_keys(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.is_dir():
            return []
        keys = []
        for current, directories, names in os.walk(base):
            directories.sort()
            for name in names:
                if name.endswith(TEMPORARY_SUFFIXES):
                    continue
                keys.append((Path(current) / name).relative_to(self.root).as_posix())
        return sorted(keys)

    @staticmethod
    def _sync_dir(directory: Path) -> None:
        try:
            checkpoint.fsync_path(directory)
        except OSError:
            logger.debug("could not fsync %s", directory, exc_info=True)


# --- Where a run's checkpoints live in a store -------------------------------------


def run_prefix(run_key: str) -> str:
    return f"{RUNS}/{validate_run_key(run_key)}"


def classification_prefix(run_key: str) -> str:
    return f"{run_prefix(run_key)}/{CLASSIFICATION}"


def graph_prefix(run_key: str, variant: Variant) -> str:
    return f"{run_prefix(run_key)}/{GRAPHS}/{variant.value}"


def list_runs(store: CheckpointStore) -> list[str]:
    """The run keys that hold anything, for an operator deciding what to resume or
    delete."""
    runs = set()
    for key in store.list_keys(RUNS):
        parts = key.split("/")
        if len(parts) > 1 and RUN_KEY.match(parts[1]):
            runs.add(parts[1])
    return sorted(runs)


def discard_run(store: CheckpointStore, run_key: str) -> int:
    """Delete everything a run holds, every manifest first: from the first delete
    on, nothing of the run looks like a whole checkpoint. Returns the number of
    objects deleted.

    A republish under the same prefix that names fewer outputs leaves the older
    files in the store; they are never restored (`restore_checkpoint` fetches only
    what the manifest lists) and are swept here, or by the store's own lifecycle
    rule. Half-written objects (`.part`, `.tmp`) are not listed and so not deleted
    here either; the lifecycle rule sweeps those too."""
    keys = store.list_keys(run_prefix(run_key))
    manifests = [key for key in keys if key.endswith("/" + MANIFEST)]
    for key in manifests:
        store.delete(key)
    for key in keys:
        if key not in manifests:
            store.delete(key)
    return len(keys)


# --- Content-only fingerprints ------------------------------------------------------


def content_only(fingerprint):
    """The fingerprint with every non-content fact (`mtime_ns`) taken out, at any
    depth. Version 1's classification fingerprint records each extract's size,
    mtime and sha256; a copy restored on another machine has a new mtime and the
    same bytes, and must match."""
    if isinstance(fingerprint, Mapping):
        return {
            key: content_only(value)
            for key, value in fingerprint.items()
            if key not in NON_CONTENT_KEYS
        }
    if isinstance(fingerprint, list):
        return [content_only(item) for item in fingerprint]
    return fingerprint


def elevation_content_digest(tile_paths: Iterable[Path | str], hasher: checkpoint.Hasher) -> str:
    """The elevation tiles by name, size and sha256. Version 1's
    `checkpoint.elevation_digest` uses names, sizes and mtimes, which a restore
    rewrites; a portable graph fingerprint uses this instead (and pays for reading
    the tiles once per attempt: the hasher remembers)."""
    entries = []
    for path in sorted(Path(p) for p in tile_paths):
        try:
            size = path.stat().st_size
        except OSError:
            entries.append([path.name, None, None])
            continue
        entries.append([path.name, size, hasher.sha256(path)])
    return checkpoint.sha256_text(checkpoint.canonical(entries))


def portable_graph_fingerprint(
    fingerprint: Mapping, elevation_tiles: Iterable[Path | str], hasher: checkpoint.Hasher
) -> dict:
    """`checkpoint.graph_fingerprint`'s result with its elevation entry measured
    by content. Everything else in it is content already (sha256s, and the build
    config with the build directory's path taken out)."""
    portable = content_only(dict(fingerprint))
    portable["elevation"] = elevation_content_digest(elevation_tiles, hasher)
    return portable


# --- Publishing and restoring one checkpoint ----------------------------------------


def publish_checkpoint(
    store: CheckpointStore,
    prefix: str,
    manifest: Mapping,
    outputs: Mapping[str, Path],
    *,
    fingerprint: Mapping,
    run_key: str,
    hasher: checkpoint.Hasher,
    now: float | None = None,
) -> dict:
    """Copy one checkpoint into the store: the old manifest deleted first, then
    every output, then the manifest, last.

    `manifest` is the version 1 manifest (classification or graph) as written on
    the local disk. Its fingerprint is **replaced** by `fingerprint`, the portable
    one the caller measured: for a graph, `portable_graph_fingerprint` (version 1's
    `elevation` entry hashes the tiles' mtimes, which `content_only` cannot take
    out); for a classification, version 1's own (its only non-content facts are
    the extracts' `mtime_ns`). The stored fingerprint is also passed through
    `content_only`. The stored copy adds the run key, the store format, the time it
    was published and each output's size and sha256 under `files`.

    An output that is missing, or whose name is not a store key segment or ends in
    `.part` or `.tmp` (endings a store keeps for half-written objects), is an error
    (StoreError) raised before anything in the store is touched.

    Returns the manifest as stored.
    """
    validate_run_key(run_key)
    for name in outputs:
        if "/" in str(name) or name.endswith(TEMPORARY_SUFFIXES):
            raise StoreError(f"not publishing {prefix}: {name!r} is not an output name")
        validate_key(name)
    missing = sorted(name for name, path in outputs.items() if not Path(path).is_file())
    if missing:
        raise StoreError(f"not publishing {prefix}: {', '.join(missing)} not written")
    manifest_key = f"{prefix}/{MANIFEST}"
    store.delete(manifest_key)
    files = {}
    for name, path in sorted(outputs.items()):
        files[name] = {"size": Path(path).stat().st_size, "sha256": hasher.sha256(path)}
        store.put_file(f"{prefix}/{FILES}/{name}", Path(path))
    stored = dict(manifest)
    stored["fingerprint"] = content_only(dict(fingerprint))
    stored.update(
        {
            "store_format": STORE_FORMAT,
            "run_key": run_key,
            "published_at": round(time.time() if now is None else now, 3),
            "files": files,
        }
    )
    store.put_json(manifest_key, stored)
    return stored


@dataclass
class Restored:
    """What `restore_checkpoint` did. `manifest` is set only when every file it
    lists is in place and hashes to what it records; otherwise `problem` says why."""

    manifest: dict | None = None
    problem: str | None = None
    downloaded: list[str] = field(default_factory=list)
    already_local: list[str] = field(default_factory=list)


def restore_checkpoint(
    store: CheckpointStore,
    prefix: str,
    destinations: Mapping[str, Path],
    *,
    hasher: checkpoint.Hasher,
) -> Restored:
    """Bring one checkpoint's files from the store to the local paths named in
    `destinations`, and check every one.

    The manifest is read first, and only files it lists are fetched. A local file
    that already has the recorded size and sha256 is kept (a resumed instance that
    still has its disk downloads nothing); any other is downloaded beside its
    destination, hashed, and renamed into place only if it matches. Local files are
    hashed again in full, whatever the hasher remembers (as version 1's outputs
    check). The manifest must list exactly the files in `destinations`. Any
    mismatch, a file listed on one side only, one the store does not have, or an
    error fetching or placing one, means no checkpoint: `problem` says which, and
    nothing that did not verify is left at a destination.
    """
    manifest = store.get_json(f"{prefix}/{MANIFEST}")
    if manifest is None:
        return Restored(problem="the store holds no manifest for it")
    if manifest.get("store_format") != STORE_FORMAT or manifest.get("format") != checkpoint.FORMAT:
        return Restored(
            problem=f"its manifest is store format {manifest.get('store_format')!r}, "
            f"local format {manifest.get('format')!r}"
        )
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        return Restored(problem="its manifest lists no files")
    unlisted = sorted(set(destinations) - set(files))
    if unlisted:
        return Restored(problem=f"its manifest does not list {', '.join(unlisted)}")
    result = Restored()
    for name, facts in sorted(files.items()):
        if not isinstance(facts, Mapping) or name not in destinations:
            return Restored(problem=f"its manifest lists {name!r}, which has no place here")
        destination = Path(destinations[name])
        if _matches(destination, facts, hasher):
            result.already_local.append(name)
            continue
        incoming = destination.with_name(destination.name + ".restore")
        try:
            if not store.get_file(f"{prefix}/{FILES}/{name}", incoming):
                return Restored(problem=f"the store does not have its {name}")
            if not _matches(incoming, facts, hasher):
                return Restored(problem=f"its {name} does not hash to what the manifest records")
            os.replace(incoming, destination)
        except (StoreError, OSError) as error:
            return Restored(problem=f"its {name} could not be restored: {error}")
        finally:
            incoming.unlink(missing_ok=True)
        result.downloaded.append(name)
    result.manifest = manifest
    return result


def _matches(path: Path, facts: Mapping, hasher: checkpoint.Hasher) -> bool:
    """The file has the recorded size and, read again in full, the recorded sha256."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size != facts.get("size"):
        return False
    return hasher.unmemoised(path) == facts.get("sha256")


# --- Is a checkpoint from elsewhere still this run's? --------------------------------


def portable_problem(
    manifest: Mapping,
    *,
    run_key: str,
    measured_fingerprint: Mapping,
    tiles_dir: Path | str,
    max_age_s: float,
    now: float | None = None,
    variant: Variant | None = None,
    build_id: str | None = None,
) -> str | None:
    """Why a checkpoint from the store cannot be used by this attempt, or None.

    Cheapest first, and the first failure is the answer:

    1. it is this store format and the local format, and names this run key (a
       run never picks up another run's checkpoint by accident: resuming a
       different run is the caller naming that run's key);
    2. its build id is a build id, is not what any variant's `current` or
       `previous` names here, and is `build_id` when the caller has one (a graph
       is reused only for the build its classification names); for a graph, its
       variant is `variant`;
    3. it was published no more than `max_age_s` seconds ago, and not more than
       `CLOCK_SKEW_S` (five minutes) in the future (a week-old checkpoint describes
       a week-old map; a future one means a clock is wrong);
    4. its fingerprint, by content alone, equals `measured_fingerprint` measured
       now on this machine (also compared by content alone); for a classification,
       only its `inputs` (a changed `validation` entry means the staging checks run
       again, as in version 1, and is the caller's to compare).

    The files themselves are checked by `restore_checkpoint`; the staging schema,
    for a classification, by `checkpoint.classification_problem`'s own checks once
    the caller has it.
    """
    if manifest.get("store_format") != STORE_FORMAT or manifest.get("format") != checkpoint.FORMAT:
        return "it is not a checkpoint of this format"
    if manifest.get("run_key") != run_key:
        return (
            f"it belongs to run {manifest.get('run_key')!r}, and this is run {run_key!r} "
            "(to resume another run, name its key)"
        )
    found_build = manifest.get("build_id")
    if not isinstance(found_build, str) or not BUILD_ID.match(found_build):
        return f"its build id {found_build!r} is not a build id"
    if found_build in checkpoint.promoted_build_ids(tiles_dir):
        return f"build {found_build} is a promoted build here (current or previous)"
    if build_id is not None and found_build != build_id:
        return f"it is for build {found_build}, and this run's build is {build_id}"
    if variant is not None and manifest.get("variant") != variant.value:
        return f"it is for the {manifest.get('variant')} graph, not {variant.value}"
    published = manifest.get("published_at")
    now = time.time() if now is None else now
    if not isinstance(published, (int, float)) or isinstance(published, bool):
        return "it records no publication time"
    if published > now + CLOCK_SKEW_S:
        return "it was published in the future (a clock is wrong)"
    if now - published > max_age_s:
        hours = (now - published) / 3600
        return f"it was published {hours:.1f} hours ago, past the {max_age_s / 3600:.1f} hour limit"
    recorded = content_only(manifest.get("fingerprint") or {})
    measured = content_only(dict(measured_fingerprint))
    if "inputs" in measured:
        # A classification fingerprint: as in version 1, only `inputs` decides;
        # its `validation` entry re-runs the staging checks, which the caller does.
        recorded, measured = recorded.get("inputs") or {}, measured["inputs"]
    differs = checkpoint.changed_inputs(recorded, measured)
    if differs:
        return "these inputs changed since it was written: " + ", ".join(differs)
    return None
