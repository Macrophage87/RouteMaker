"""Checkpoints for the weekly rebuild: what is kept when an attempt fails, and when
it may be used again.

Owner decision 459: "Why do we need to rerun everything when one fails. There
should be reasonable checkpoints." The design is in the owner's report folder,
`rmdata/demo/reports/REBUILD-CHECKPOINTS-design.md` (not in this repository); this
module is its mechanism and `pipeline.run` is where it is wired in.

Two checkpoints, and one rule for both.

- **Classification** (`<DATA_ROOT>/rebuild/checkpoint/classification.json`): the
  staging schema and the five variant extracts, which hold everything that
  CONFLATE_VOLUME through VALIDATE_SEGMENTS worked out and that otherwise lives
  only in the process.
- **Per graph** (`<build dir>/routemaker-graph.json`): one finished tile build.

The rule: **a checkpoint is a manifest that is written last, and it is reused
only if every input it depends on is measured again now and matches.** A file
that is missing, truncated, from another format version or from a different job
is not a checkpoint. A job id or a timestamp on its own is never enough, and
nothing here trusts a size without the hash beside it.

This module imports no Django model and reads no setting: the callers hand it
paths and values, which is what lets a test drive every branch with temporary
directories. The two database helpers take a connection from Django lazily.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import tiles
from .retention import BUILD_ID
from .variants import Variant

logger = logging.getLogger(__name__)

FORMAT = 1
CHECKPOINT_DIR = "checkpoint"
CLASSIFICATION_NAME = "classification.json"
TIMEOUT_RETRIES_NAME = "timeout-retries.json"
# At most this many pre-swap timeouts of one job are retried (OWNER-DECISIONS 459a's
# "let it increase", bounded): each retry gets a whole budget, and without a cap a job
# whose inputs keep moving could start fresh, checkpoint and time out again until
# Procrastinate's own five retries ran out.
MAX_TIMEOUT_RETRIES = 2
GRAPH_MANIFEST = "routemaker-graph.json"
BUILD_LOG = "build.log"
BUILD_CONFIG = "build-config.json"

# Every setting the pipeline reads, and what a change to it means for a
# checkpoint. A test (tests/test_rebuild_checkpoints.py) reads the pipeline's own
# source and fails on any name this table does not list, so a new setting that
# changes the map cannot slip past the fingerprint.
#
# classification  in the fingerprint; a change means the classification starts fresh
# validation      in a second fingerprint; a change re-runs only the VALIDATE_SEGMENTS
#                 checks that read the staging schema, which a resumed attempt can do
# graph           folded into each graph's own fingerprint (through the config
#                 it builds with, or the files it reads)
# ignored         changes nothing a checkpoint holds, on purpose (see the comment)
CLASSIFICATION = "classification"
VALIDATION = "validation"
GRAPH = "graph"
IGNORED = "ignored"

CHECKPOINT_SETTINGS: dict[str, str] = {
    # What is classified, and where the clip is.
    "COVERAGE_BBOX": CLASSIFICATION,
    "COVERAGE_POLYGON": CLASSIFICATION,
    "SEGMENT_SCHEMA_STAGING": CLASSIFICATION,
    "REBUILD_CROSSINGS_FIXTURE": CLASSIFICATION,
    "MASS_RIDE_DC_WIDE_LANE_FT": CLASSIFICATION,
    "MASS_RIDE_DC_WIDE_LANE_CAP_FT": CLASSIFICATION,
    "MASS_RIDE_DC_VERIFIED_REVERSIBLE_BLOCKS": CLASSIFICATION,
    "MASS_RIDE_DC_ENDED_REVERSIBLE_STREETS": CLASSIFICATION,
    # The VALIDATE_SEGMENTS checks that read the in-memory context (the reference
    # data, the military and secured ways). A resumed attempt has no context, so
    # it cannot re-run them: a change to their numbers means a fresh start.
    "REBUILD_SENTINEL_LTS4_STREET": CLASSIFICATION,
    "REBUILD_SENTINEL_LTS4_MIN_SHARE": CLASSIFICATION,
    "REBUILD_SENTINEL_LTS4_NORTH_OF_LAT": CLASSIFICATION,
    "REBUILD_SENTINEL_LTS4_NORTH_MIN_SHARE": CLASSIFICATION,
    "REBUILD_SENTINEL_STRETCHES": CLASSIFICATION,
    "REBUILD_SENTINEL_MILITARY_CLOSED_WAYS": CLASSIFICATION,
    "REBUILD_SENTINEL_MILITARY_MIN_CLOSED": CLASSIFICATION,
    "REBUILD_SENTINEL_SECURED_CLOSED_WAYS": CLASSIFICATION,
    "REBUILD_SENTINEL_SECURED_MIN_CLOSED": CLASSIFICATION,
    # The checks that read only the staging schema.
    "REBUILD_CALM_RUN_FLOORS": VALIDATION,
    "REBUILD_LONG_TRAIL_FLOORS": VALIDATION,
    "REBUILD_MASS_CAPACITY_MEDIAN_RANGE": VALIDATION,
    "REBUILD_SENTINEL_CALM_PATH_WAYS": VALIDATION,
    "REBUILD_SENTINEL_CALM_STREET_WAYS": VALIDATION,
    "REBUILD_SENTINEL_LONG_TRAIL_WAYS": VALIDATION,
    # Read by the tile build.
    "VALHALLA_CONFIG_DIR": GRAPH,
    "ELEVATION_DIR": GRAPH,
    # Not in any fingerprint:
    #  - the thread count does not change the graph (the owner changed it in the
    #    middle of job 8408), and the build config is fingerprinted without it;
    #  - the time budget, the disk gate and the volume paths decide whether and
    #    where a rebuild runs, not what it produces;
    #  - the extract's sha already covers where it came from, so its age rule, its
    #    URLs and its refresh switch change nothing a checkpoint holds (the
    #    switch forces a fresh start by itself, in `pipeline.run`);
    #  - VALIDATE_TILES always runs again, so its sentinel edges are not held;
    #  - the live and retired schema names and the upstream URLs are read by the
    #    swap and the reconcile, which no checkpoint skips.
    # Its content is digested (src, fixtures, lua, valhalla); the path is where it lives.
    "BASE_DIR": IGNORED,
    "REBUILD_TILE_CONCURRENCY": IGNORED,
    "REBUILD_TIMEOUT_S": IGNORED,
    "REBUILD_CHECKPOINTS": IGNORED,
    "REBUILD_MIN_FREE_BYTES": IGNORED,
    "DISK_GATE_FRACTION": IGNORED,
    "TILES_DIR": IGNORED,
    "SOURCE_EXTRACT_MAX_AGE": IGNORED,
    "SOURCE_EXTRACT_URLS": IGNORED,
    "SOURCE_EXTRACT_FORCE_REFRESH": IGNORED,
    "REBUILD_SENTINEL_STEEP_EDGE": IGNORED,
    "REBUILD_SENTINEL_DERIVED_EDGE": IGNORED,
    "REBUILD_SENTINEL_WEEKEND_EDGE": IGNORED,
    "SEGMENT_SCHEMA_LIVE": IGNORED,
    "SEGMENT_SCHEMA_RETIRED": IGNORED,
    "VALHALLA_UPSTREAMS": IGNORED,
}

SETTINGS_OF_KIND = {
    kind: tuple(sorted(name for name, k in CHECKPOINT_SETTINGS.items() if k == kind))
    for kind in (CLASSIFICATION, VALIDATION, GRAPH, IGNORED)
}


def settings_read_by(source_files: Iterable[Path]) -> set[str]:
    """Every setting name the given Python files read, found in their syntax trees.

    `_setting("NAME")` and `setting("NAME")` calls, `settings.NAME` attributes
    (the Django settings object, however it was imported) and
    `getattr(settings, "NAME")`. Read from the tree rather than by pattern so
    that a comment saying `settings.X` is not a read and a read in a docstring
    example is not either.
    """
    names: set[str] = set()
    for path in source_files:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                called = function.id if isinstance(function, ast.Name) else None
                if called in {"_setting", "setting"} and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        names.add(first.value)
                if (
                    called == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "settings"
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    names.add(node.args[1].value)
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "settings"
                and node.attr.isupper()
            ):
                names.add(node.attr)
    return names


class CheckpointRefused(RuntimeError):
    """A checkpoint operation was refused because it would touch something that is
    not a partial build of this rebuild. Terminal: a retry meets the same refusal."""


# --- Files: hashing and atomic writes ----------------------------------------

CHUNK = 8 * 1024 * 1024


def sha256_file(path: Path | str) -> str:
    """The file's SHA-256, read in chunks: the extracts are gigabytes and the host
    has little memory to spare."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Hasher:
    """`sha256_file` that remembers: one attempt hashes the merged extract once,
    not once per variant. Keyed on the path and the file's size and mtime, so a
    file that is rewritten in between is hashed again.

    `seconds` is the time spent reading files to hash them (memo hits cost
    nothing): the hashing comes out of the attempt's own budget, so the manifests
    record it."""

    hash_file: Callable[[Path], str] = sha256_file
    _memo: dict = field(default_factory=dict)
    seconds: float = 0.0

    def sha256(self, path: Path | str) -> str:
        path = Path(path)
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in self._memo:
            self._memo[key] = self.unmemoised(path)
        return self._memo[key]

    def unmemoised(self, path: Path | str) -> str:
        """Hash the file again whatever the memo holds, and count the time."""
        started = time.monotonic()
        try:
            return self.hash_file(Path(path))
        finally:
            self.seconds += time.monotonic() - started

    def facts(self, path: Path | str) -> dict:
        path = Path(path)
        stat = path.stat()
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": self.sha256(path)}


def fsync_path(path: Path | str) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) if Path(path).is_dir() else os.O_RDONLY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: Path | str, payload: Mapping) -> None:
    """Write `<path>.tmp`, fsync it, rename it onto `path`, fsync the directory.

    The rename is the commit. A crash before it leaves no `path` (or the previous
    one, whole); a crash after it leaves the new one, whole. There is no instant at
    which `path` is half a manifest.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        fsync_path(path.parent)
    except OSError:  # a directory that cannot be opened to sync (some platforms)
        logger.debug("could not fsync %s", path.parent, exc_info=True)


def read_json(path: Path | str) -> dict | None:
    """The manifest at `path`, or None for anything that is not one: absent, not
    JSON, not an object, or another format version."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return None
    return data


# The key a mapping whose keys are not all strings is written under. A NUL is in
# no setting's own string key, so a real mapping cannot collide with it.
_MAPPING_TAG = "\u0000mapping"


def _tagged_key(key) -> list:
    """A mapping key as a type-tagged, JSON-encodable value: `1` and `"1"` are two
    keys, and so are `("a", "b")` and `"('a', 'b')"`."""
    return [type(key).__name__, _normalise(key)]


def _normalise(value):
    """`value` as plain JSON that encodes the same way in every process.

    Recursive, because a setting can be any shape: `REBUILD_SENTINEL_MILITARY_MIN_CLOSED`
    is a dict with a tuple key, which `json.dumps` cannot take (its `default` hook is
    never called for a key, and a str and a tuple do not sort against each other).

    - A mapping whose keys are all strings stays an object (`sort_keys` orders it).
      Any other mapping becomes `{"\0mapping": [[tagged key, value], ...]}`, the
      pairs sorted by the canonical text of their keys.
    - A list or a tuple is a list of its items, each normalised.
    - A set is a list sorted by each item's canonical text (its iteration order is
      hash order, which differs from one process to the next).
    - A path, and anything else JSON has no form for, is its text.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if all(isinstance(key, str) for key in value):
            return {key: _normalise(item) for key, item in value.items()}
        pairs = [[_tagged_key(key), _normalise(item)] for key, item in value.items()]
        pairs.sort(key=lambda pair: _dump(pair[0]))
        return {_MAPPING_TAG: pairs}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalise(item) for item in value), key=_dump)
    return str(value)


def _dump(normalised) -> str:
    return json.dumps(normalised, sort_keys=True, separators=(",", ":"))


def canonical(value) -> str:
    """One text for `value`, the same in every process, whatever its shape."""
    return _dump(_normalise(value))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_digest(root: Path | str, hasher: Hasher | None = None) -> str:
    """One digest over every file under `root`: its relative path and its content.

    Bytecode and `__pycache__` are left out (they follow the source); everything
    else counts, so a changed fixture, Lua script or config is a changed digest.
    A missing root is its own digest, not an error: the caller decides whether
    that is a problem.
    """
    root = Path(root)
    if not root.is_dir():
        return "absent"
    hasher = hasher or Hasher()
    lines = []
    for current, directories, names in os.walk(root):
        directories[:] = sorted(d for d in directories if d != "__pycache__")
        for name in sorted(names):
            if name.endswith(".pyc"):
                continue
            path = Path(current) / name
            if path.is_symlink() and not path.exists():
                lines.append(f"{path.relative_to(root).as_posix()}\0dangling")
                continue
            lines.append(f"{path.relative_to(root).as_posix()}\0{hasher.sha256(path)}")
    return sha256_text("\n".join(lines))


# --- The classification fingerprint --------------------------------------------


def overrides_digest(rows: Iterable[Mapping]) -> str:
    """One digest over every approved override row: id, kind, way, value, reason and
    approval time, ordered by id.

    Not a count and a largest id: an edited `value`, or one row unapproved while
    another is approved, keeps both of those the same and changes the map.
    """
    ordered = sorted((dict(row) for row in rows), key=lambda row: row["id"])
    return sha256_text(canonical(ordered))


def reference_digest(
    reference_dir: Path | str, crossings_fixture: Path | str | None, hasher: Hasher | None = None
) -> str:
    """The installed reference data as (relative path, size, sha256) per file, and
    the checked-in crossings fixture's sha."""
    hasher = hasher or Hasher()
    root = Path(reference_dir)
    files = []
    if root.is_dir():
        for current, directories, names in os.walk(root):
            directories.sort()
            for name in sorted(names):
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() and not path.exists():
                    # As in `tree_digest`: a dangling link is part of the tree's
                    # shape, not a reason to fail the rebuild.
                    files.append([relative, None, "dangling"])
                    continue
                files.append([relative, path.stat().st_size, hasher.sha256(path)])
    fixture = None
    if crossings_fixture is not None and Path(crossings_fixture).is_file():
        fixture = hasher.sha256(crossings_fixture)
    return sha256_text(canonical({"files": files, "crossings_fixture": fixture}))


JURISDICTION_DIGEST_SQL = """
SELECT count(*),
       coalesce(md5(string_agg(
           id::text || '|' || layer || '|' || name || '|' || coalesce(state, '') || '|'
           || is_federal_enclave::text || '|' || md5(ST_AsEWKB(geometry)::text),
           ',' ORDER BY id)), '')
FROM jurisdiction
"""


def jurisdiction_digest() -> str:
    """The `jurisdiction` table as a count and an md5 over every row, geometry
    included. TAG_JURISDICTIONS reads it, and so does the state lookup that places
    the border nodes."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(JURISDICTION_DIGEST_SQL)
        count, digest = cursor.fetchone()
    return f"{count}:{digest}"


def approved_override_rows() -> list[dict]:
    """Every approved override row, by id, in the shape `overrides_digest` hashes."""
    from core.models import Override

    return [
        {
            "id": row.id,
            "kind": row.kind,
            "osm_way_id": row.osm_way_id,
            "value": row.value,
            "reason": row.reason,
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            # An undo of a road panel edit changes only which row is superseded.
            "superseded_by": row.superseded_by_id,
        }
        for row in Override.objects.filter(approved=True).order_by("id")
    ]


def settings_digest(values: Mapping[str, object]) -> str:
    return sha256_text(canonical({name: values[name] for name in sorted(values)}))


def packages_digest() -> str:
    """The Python packages installed beside the code, as sorted `name==version`
    lines: a rebuilt image that changed only a dependency (osmium, shapely and the
    rest of /opt/venv) changes this. Not covered: the system libraries (GEOS, PROJ,
    libspatialite) and the PostGIS server, which change with the image or the
    database container (docs/OPERATIONS.md, "Rebuild checkpoints")."""
    from importlib import metadata

    entries = sorted(
        {
            f"{(dist.metadata.get('Name') or '').lower()}=={dist.version}"
            for dist in metadata.distributions()
        }
    )
    return sha256_text("\n".join(entries))


def measure_classification_fingerprint(
    *,
    source_pbf: Path,
    merged_pbf: Path,
    code_roots: Mapping[str, Path],
    reference_dir: Path,
    crossings_fixture: Path | None,
    coverage_polygon: Path | None,
    classification_settings: Mapping[str, object],
    validation_settings: Mapping[str, object],
    override_rows: Iterable[Mapping],
    jurisdictions: str,
    smooth_volume: bool,
    hasher: Hasher,
    packages: str | None = None,
) -> dict:
    """Everything the classification depends on, measured now, as one flat mapping.

    Flat and keyed by input so that a mismatch can name what changed. The
    `validation` entry is separate from `inputs`: it decides whether the staging
    checks run again, not whether the classification is usable.
    """
    inputs = {
        "source_extract": hasher.facts(source_pbf),
        "merged_extract": hasher.facts(merged_pbf),
        "code": {name: tree_digest(root, hasher) for name, root in sorted(code_roots.items())},
        "packages": packages if packages is not None else packages_digest(),
        "overrides": overrides_digest(override_rows),
        "reference": reference_digest(reference_dir, crossings_fixture, hasher),
        "jurisdictions": jurisdictions,
        "coverage_polygon": (
            hasher.sha256(coverage_polygon)
            if coverage_polygon is not None and Path(coverage_polygon).is_file()
            else None
        ),
        "smooth_volume": bool(smooth_volume),
        "settings": settings_digest(classification_settings),
    }
    return {"inputs": inputs, "validation": settings_digest(validation_settings)}


def changed_inputs(recorded: Mapping, measured: Mapping) -> list[str]:
    """The names of the inputs that differ, for the log line that says why a
    checkpoint was not used."""
    names = []
    for key in sorted(set(recorded) | set(measured)):
        before, after = recorded.get(key), measured.get(key)
        if isinstance(before, Mapping) and isinstance(after, Mapping):
            names.extend(f"{key}.{inner}" for inner in changed_inputs(before, after))
        elif before != after:
            names.append(key)
    return names


# --- The classification manifest -----------------------------------------------


def checkpoint_dir(work_dir: Path | str) -> Path:
    return Path(work_dir) / CHECKPOINT_DIR


def classification_path(work_dir: Path | str) -> Path:
    return checkpoint_dir(work_dir) / CLASSIFICATION_NAME


def read_classification(work_dir: Path | str) -> dict | None:
    return read_json(classification_path(work_dir))


def find_resumable(
    work_dir: Path | str, job_id: int | None, *, enabled: bool = True, force_fresh: bool = False
) -> tuple[dict | None, dict | None]:
    """What the checkpoint directory holds for this attempt: `(kept, resumable)`.

    `kept` is any valid classification manifest, whichever job wrote it (a caller
    that only wants to know what is on disk). `resumable` is the same manifest when
    the rest of the rule allows using it - checkpoints on, no forced refresh of the extract, and
    the job id this attempt's own (a retry or an `unwedge_job` requeue keeps it; a
    new job never matches). Everything else is checked later, against the world as
    it is then, by `classification_problem`.
    """
    kept = read_classification(work_dir) if enabled else None
    if kept is None:
        return None, None
    same_job = job_id is not None and kept.get("job_id") == job_id
    usable = same_job and not force_fresh and isinstance(kept.get("build_id"), str)
    return kept, kept if usable else None


def discard_classification(work_dir: Path | str) -> bool:
    """Delete the manifest (and a stray temporary one). The checkpoint's first step
    on every path that stops using it: nothing is deleted before it, so a
    half-deleted checkpoint is never one that still looks whole."""
    removed = False
    for name in (CLASSIFICATION_NAME, CLASSIFICATION_NAME + ".tmp"):
        try:
            (checkpoint_dir(work_dir) / name).unlink()
            removed = removed or name == CLASSIFICATION_NAME
        except FileNotFoundError:
            continue
    return removed


def reset_checkpoints(work_dir: Path | str) -> bool:
    """Start fresh by hand: delete the checkpoint directory. The same switch an
    operator has by deleting the directory, as the extract's "delete the file to
    force it" convention."""
    directory = checkpoint_dir(work_dir)
    existed = directory.exists()
    shutil.rmtree(directory, ignore_errors=True)
    return existed


def timeout_retries(work_dir: Path | str, job_id: int | None) -> int:
    """How many pre-swap timeouts of this job have been retried already. A record
    from another job counts as none; one that is there and cannot be read counts as
    the cap, so a broken file stops the retries rather than unbounding them."""
    path = checkpoint_dir(work_dir) / TIMEOUT_RETRIES_NAME
    if not path.exists():
        return 0
    data = read_json(path)
    if data is None or not isinstance(data.get("retries"), int):
        return MAX_TIMEOUT_RETRIES
    return data["retries"] if data.get("job_id") == job_id else 0


def record_timeout_retry(work_dir: Path | str, job_id: int | None) -> int:
    """Count one more retried timeout for this job, and return the new count."""
    retries = timeout_retries(work_dir, job_id) + 1
    atomic_write_json(
        checkpoint_dir(work_dir) / TIMEOUT_RETRIES_NAME,
        {"format": FORMAT, "job_id": job_id, "retries": retries},
    )
    return retries


def new_token() -> str:
    return uuid.uuid4().hex


def stamp_staging(schema: str, token: str) -> None:
    """Record the token as the staging schema's comment. The file is tied to the
    database by this: a staging schema that is dropped, rebuilt or renamed away has
    lost it."""
    from django.db import connection

    from .schema import validate_schema_name

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(f"COMMENT ON SCHEMA {schema} IS %s", [f"routemaker-checkpoint:{token}"])


def staging_state(schema: str) -> dict | None:
    """The staging schema's token and row counts, or None if it does not exist."""
    from django.db import connection

    from .schema import validate_schema_name

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = %s",
            [schema],
        )
        row = cursor.fetchone()
        if row is None:
            return None
        comment = row[0] or ""
        counts = {}
        for table in ("segment", "border_crossing"):
            cursor.execute("SELECT to_regclass(%s)", [f"{schema}.{table}"])
            if cursor.fetchone()[0] is None:
                counts[table] = None
                continue
            cursor.execute(f"SELECT count(*) FROM {schema}.{table}")
            counts[table] = cursor.fetchone()[0]
    prefix = "routemaker-checkpoint:"
    return {
        "token": comment[len(prefix) :] if comment.startswith(prefix) else None,
        "segment_rows": counts["segment"],
        "border_crossing_rows": counts["border_crossing"],
    }


def variant_pbf_facts(pbfs: Mapping[Variant, Path], hasher: Hasher) -> dict:
    return {
        variant.value: {
            "size": Path(path).stat().st_size,
            "sha256": hasher.sha256(path),
        }
        for variant, path in pbfs.items()
    }


def promoted_build_ids(tiles_dir: Path | str) -> set[str]:
    """Every build id any variant's `current` or `previous` link names. The served
    graph and the rollback target: nothing in this module may reuse or delete one."""
    names = set()
    for variant in Variant:
        for link in (tiles.CURRENT, tiles.PREVIOUS):
            path = Path(tiles_dir) / variant.value / link
            if path.is_symlink():
                names.add(os.path.basename(os.readlink(path)))
    return names


def classification_problem(
    manifest: Mapping,
    *,
    job_id: int | None,
    tiles_dir: Path | str,
    measure_fingerprint: Callable[[], dict],
    variant_pbfs: Mapping[Variant, Path],
    hasher: Hasher,
    staging: Callable[[str], dict | None] = staging_state,
) -> tuple[str | None, bool]:
    """Why the classification checkpoint cannot be used, or None if it can.

    Returns `(problem, validation_changed)`. The checks run cheapest first and the
    first failure is the answer, so a checkpoint from another job never costs an
    extract hash. `validation_changed` is true when only the staging checks'
    numbers moved: the checkpoint stands, and those checks run again.
    """
    if job_id is None or manifest.get("job_id") != job_id:
        return (
            f"it was written by job {manifest.get('job_id')}, and this is job {job_id} "
            "(a checkpoint is resumed only inside the job that wrote it)",
            False,
        )
    build_id = manifest.get("build_id")
    if not isinstance(build_id, str) or not BUILD_ID.match(build_id):
        return f"its build id {build_id!r} is not a build id", False
    if build_id in promoted_build_ids(tiles_dir):
        return f"build {build_id} is a promoted build (current or previous)", False
    measured = measure_fingerprint()
    recorded = manifest.get("fingerprint") or {}
    differs = changed_inputs(recorded.get("inputs") or {}, measured["inputs"])
    if differs:
        return "these inputs changed since it was written: " + ", ".join(differs), False
    recorded_pbfs = manifest.get("variant_pbfs") or {}
    for variant, path in variant_pbfs.items():
        facts = recorded_pbfs.get(variant.value)
        if not isinstance(facts, Mapping):
            return f"it records no extract for the {variant.value} variant", False
        try:
            size = Path(path).stat().st_size
        except OSError:
            return f"the {variant.value} variant extract {path} is missing", False
        if size != facts.get("size") or hasher.sha256(path) != facts.get("sha256"):
            return f"the {variant.value} variant extract {path} changed", False
    recorded_staging = manifest.get("staging") or {}
    schema = recorded_staging.get("schema")
    state = staging(schema) if isinstance(schema, str) else None
    if state is None:
        return f"the staging schema {schema!r} does not exist", False
    if not recorded_staging.get("token") or state["token"] != recorded_staging["token"]:
        return f"the staging schema {schema} does not carry its token", False
    if state["segment_rows"] != recorded_staging.get("segment_rows") or state[
        "border_crossing_rows"
    ] != recorded_staging.get("border_crossing_rows"):
        return (
            f"the staging schema {schema} has {state['segment_rows']} segment rows and "
            f"{state['border_crossing_rows']} border crossings, and the checkpoint recorded "
            f"{recorded_staging.get('segment_rows')} and "
            f"{recorded_staging.get('border_crossing_rows')}",
            False,
        )
    return None, recorded.get("validation") != measured["validation"]


# --- The per-graph manifest ----------------------------------------------------


def build_config_digest(config: Mapping, build_dir: Path | str) -> str:
    """The build config as the serving config and the settings define it, with
    what is not part of the graph taken out: `mjolnir.concurrency` (a thread count
    does not change the graph) and the build directory's own path (a rebuild's id
    is not an input)."""
    cleaned = json.loads(json.dumps(config))
    cleaned.get("mjolnir", {}).pop("concurrency", None)
    prefix = str(build_dir).rstrip("/") + "/"
    for section, key in tiles.TILE_PATH_KEYS:
        value = cleaned.get(section, {}).get(key)
        if isinstance(value, str) and value.startswith(prefix):
            cleaned[section][key] = value[len(prefix) :]
    return sha256_text(canonical(cleaned))


def elevation_digest(tile_paths: Iterable[Path | str]) -> str:
    entries = []
    for path in sorted(Path(p) for p in tile_paths):
        try:
            stat = path.stat()
        except OSError:
            entries.append([path.name, None, None])
            continue
        entries.append([path.name, stat.st_size, stat.st_mtime_ns])
    return sha256_text(canonical(entries))


GRAPH_BINARIES = ("valhalla_build_tiles", "valhalla_build_extract")


def binaries_digest(hasher: Hasher, which: Callable[[str], str | None] | None = None) -> str:
    which = which or shutil.which
    entries = {}
    for name in GRAPH_BINARIES:
        found = which(name)
        entries[name] = hasher.sha256(found) if found else "absent"
    return sha256_text(canonical(entries))


def graph_fingerprint(
    *,
    variant_pbf: Path,
    merged_pbf: Path,
    config: Mapping,
    build_dir: Path,
    lua_dirs: Sequence[Path],
    elevation_tiles: Iterable[Path],
    hasher: Hasher,
    which: Callable[[str], str | None] | None = None,
) -> dict:
    """What one graph's build is a function of: its extract's content, the merged
    extract the admin database is built from, the build config without its thread
    count, the Lua, the elevation tiles and the two Valhalla binaries."""
    return {
        "variant_pbf_sha256": hasher.sha256(variant_pbf),
        "merged_pbf_sha256": hasher.sha256(merged_pbf),
        "build_config_sha256": build_config_digest(config, build_dir),
        "lua_sha256": sha256_text(
            canonical([tree_digest(directory, hasher) for directory in lua_dirs])
        ),
        "elevation": elevation_digest(elevation_tiles),
        "valhalla_bin_sha256": binaries_digest(hasher, which),
    }


def graph_manifest_path(build_dir: Path | str) -> Path:
    return Path(build_dir) / GRAPH_MANIFEST


def write_graph_manifest(
    build_dir: Path,
    *,
    variant: Variant,
    build_id: str,
    job_id: int | None,
    fingerprint: Mapping,
    outputs: Mapping[str, Path],
    concurrency_used,
    seconds: float,
    hasher: Hasher,
    hash_seconds: float = 0.0,
) -> bool:
    """Write the graph's manifest, last. Returns False, writing nothing, when an
    output a rebuild needs is not there: such a graph stays partial, and the next
    attempt builds it again."""
    missing = [name for name, path in outputs.items() if not Path(path).is_file()]
    if missing:
        logger.warning(
            "no checkpoint for the %s graph: %s not written", variant.value, ", ".join(missing)
        )
        return False
    recorded = {}
    hashing_from = hasher.seconds
    for name, path in sorted(outputs.items()):
        fsync_path(path)
        recorded[name] = {"size": Path(path).stat().st_size, "sha256": hasher.sha256(path)}
    hashed = hasher.seconds - hashing_from + hash_seconds
    atomic_write_json(
        graph_manifest_path(build_dir),
        {
            "format": FORMAT,
            "variant": variant.value,
            "build_id": build_id,
            "job_id": job_id,
            "fingerprint": dict(fingerprint),
            "outputs": recorded,
            "concurrency_used": concurrency_used,
            "seconds": round(seconds, 1),
            # The fingerprint's and the outputs' hashing, which the attempt's budget
            # pays for on top of the build.
            "hash_seconds": round(hashed, 1),
        },
    )
    return True


def graph_problem(
    build_dir: Path,
    *,
    variant: Variant,
    build_id: str,
    job_id: int | None,
    fingerprint: Mapping,
    outputs: Mapping[str, Path],
    hasher: Hasher,
) -> str | None:
    """Why the graph in `build_dir` cannot be reused, or None if it can.

    A graph with no valid manifest is partial. A graph whose manifest is valid but
    whose inputs changed, or whose outputs no longer hash to what was recorded, is
    stale; the tile archive and the two databases are read in full and hashed
    again, because a size alone does not catch a flipped byte.
    """
    manifest = read_json(graph_manifest_path(build_dir))
    if manifest is None:
        return "it has no valid manifest (a partial build)"
    if manifest.get("variant") != variant.value or manifest.get("build_id") != build_id:
        return f"its manifest is for {manifest.get('variant')} {manifest.get('build_id')}"
    if job_id is None or manifest.get("job_id") != job_id:
        return f"its manifest was written by job {manifest.get('job_id')}"
    differs = changed_inputs(manifest.get("fingerprint") or {}, dict(fingerprint))
    if differs:
        return "these inputs changed: " + ", ".join(differs)
    recorded = manifest.get("outputs") or {}
    for name, path in sorted(outputs.items()):
        facts = recorded.get(name)
        if not isinstance(facts, Mapping):
            return f"its manifest records no {name}"
        try:
            size = Path(path).stat().st_size
        except OSError:
            return f"{name} is missing"
        if size != facts.get("size"):
            return f"{name} has a different size"
        if hasher.unmemoised(path) != facts.get("sha256"):
            return f"{name} does not hash to what was recorded"
    return None


def remove_partial_graph(
    tiles_dir: Path | str, variant: Variant, build_id: str, *, this_build: str
) -> None:
    """Delete one variant's directory for this rebuild's own build id, manifest
    first. Guarded three ways, and each guard refuses rather than skips:

    - the name must be a build id, and it must be *this* rebuild's: `this_build`
      is the build the caller's checkpoint manifest names, passed separately from
      the build id to delete, so a context whose build id drifted from its
      checkpoint is refused rather than trusted;
    - never a directory any variant's `current` or `previous` points at;
    - never a symlink, and only a directory directly under that variant.
    """
    if not isinstance(build_id, str) or not BUILD_ID.match(build_id):
        raise CheckpointRefused(f"{build_id!r} is not a build id; nothing was removed")
    if build_id != this_build:
        raise CheckpointRefused(
            f"{build_id} is not this rebuild's build ({this_build}); nothing was removed"
        )
    if build_id in promoted_build_ids(tiles_dir):
        raise CheckpointRefused(
            f"{build_id} is a promoted build (current or previous); nothing was removed"
        )
    target = Path(tiles_dir) / variant.value / build_id
    if target.is_symlink():
        raise CheckpointRefused(f"{target} is a symlink; nothing was removed")
    if not target.is_dir():
        return
    try:
        graph_manifest_path(target).unlink()
    except FileNotFoundError:
        pass
    shutil.rmtree(target)
    logger.info("removed the partial or stale %s graph %s", variant.value, target)
