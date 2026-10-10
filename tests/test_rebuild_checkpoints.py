"""Rebuild checkpoints (owner decision 459): what a failed attempt keeps, and when the
job's next attempt may use it.

Design: rmdata/demo/reports/REBUILD-CHECKPOINTS-design.md (the owner's report folder).
The tests run the real handler set, stage by stage, with only the binaries stood in
for (as test_pipeline_end_to_end does), so a "failed attempt" is a real one that left
real files and a real staging schema, and a "resumed attempt" is the production code
finding them.

Each test names the item of the design's test plan it covers (T1 .. T10, T13).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import NamedTuple

import pytest
from django.conf import settings
from django.db import connection
from rebuild_fixtures import (
    FakeBinaries,
    build_long_trails_extract,
    build_toy_extract,
    fake_fetch,
    install_source_extract,
    roomy_disk,
    state_polygons,
    write_reference_data,
)

from pipeline import checkpoint, promotion, retention, schema, tiles
from pipeline import run as run_module
from pipeline.checkpoint import CheckpointRefused
from pipeline.rebuild import RebuildFailed, Stage, run_rebuild
from pipeline.run import CommandFailed, RebuildContext, ValidationFailed, build_handlers
from pipeline.variants import Variant

pytestmark = pytest.mark.django_db(transaction=True)

REPO = Path(__file__).resolve().parents[1]
JOB = 8408
FIRST = "20261001T000000Z"

NOT_SWAPPED = frozenset({Stage.SWAP, Stage.RECONCILE})
THROUGH_CLASSIFICATION = frozenset(
    {Stage.BUILD_TILES, Stage.VALIDATE_TILES, Stage.SWAP, Stage.RECONCILE}
)
ONLY_FETCH = frozenset(set(Stage) - {Stage.FETCH_EXTRACT})
ORDER = [variant.value for variant in Variant]


@pytest.fixture
def states():
    yield from state_polygons()


class Env(NamedTuple):
    source: Path
    root: Path
    reference: Path
    code_roots: dict

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def tiles(self) -> Path:
        return self.root / "tiles"

    def build_dir(self, variant: str, build_id: str = FIRST) -> Path:
        return self.tiles / variant / build_id


@pytest.fixture
def env(segment_schemas, states):
    """A deployment with this week's extract and reference data on disk, and four
    small directories standing in for the code the fingerprint digests (the real
    ones are the repository, which a test must not edit)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = install_source_extract(root / "extracts")
        reference = write_reference_data(root, urban=(100, 200, 300, 400, 500))
        code_roots = {}
        for name in ("src", "fixtures", "lua", "valhalla"):
            directory = root / "code" / name
            directory.mkdir(parents=True)
            (directory / "a.txt").write_text(f"{name} v1")
            code_roots[name] = directory
        yield Env(source, root, reference, code_roots)


class Outcome(NamedTuple):
    context: RebuildContext
    report: object
    error: RebuildFailed | None
    binaries: FakeBinaries


def attempt(
    env: Env,
    *,
    job_id: int | None = JOB,
    binaries: FakeBinaries | None = None,
    skip: frozenset = NOT_SWAPPED,
    build_id: str | None = FIRST,
    enabled: bool = True,
    force_fresh: bool = False,
    **context_args,
) -> Outcome:
    """One attempt of the weekly task: what `weekly_rebuild` does to build its
    context (`checkpoint.find_resumable`), then the real handlers, failure kept."""
    kept, resumable = checkpoint.find_resumable(
        env.work, job_id, enabled=enabled, force_fresh=force_fresh
    )
    args = {
        "source_pbf": env.source,
        "work_dir": env.work,
        "reference_dir": env.reference,
        "tiles_dir": env.tiles,
        "elevation_dir": env.root / "elevation",
        "job_id": job_id,
        "checkpoints": enabled,
        "resume": resumable,
        "code_roots": env.code_roots,
    }
    if resumable is not None:
        args["build_id"] = resumable["build_id"]
    elif build_id:
        args["build_id"] = build_id
    args.update(context_args)
    context = RebuildContext(**args)
    binaries = binaries or FakeBinaries()
    handlers = build_handlers(
        context, run=binaries, fetch_elevation=fake_fetch, disk_usage=roomy_disk
    )
    try:
        return Outcome(context, run_rebuild(handlers, skip=skip), None, binaries)
    except RebuildFailed as error:
        return Outcome(context, None, error, binaries)


class FailsAt(FakeBinaries):
    """A fake whose `valhalla_build_tiles` for one variant fails (`times` times)."""

    def __init__(self, variant: str, *, exception=None, times: int = 1, **kwargs) -> None:
        super().__init__(**kwargs)
        self.variant = variant
        self.exception = exception
        self.times = times

    def __call__(self, command):
        if Path(command[0]).name == "valhalla_build_tiles" and self.times > 0:
            config = json.loads(Path(command[2]).read_text())
            if Path(config["mjolnir"]["tile_dir"]).parents[1].name == self.variant:
                self.times -= 1
                self.calls.append(list(command))
                raise self.exception or CommandFailed(
                    list(command), 1, tiles.CommandOutput("", "boom\n")
                )
        return super().__call__(command)


def built(binaries: FakeBinaries) -> list[str]:
    """The variants a `valhalla_build_tiles` ran for, in order."""
    return [Path(c[2]).parent.parent.name for c in binaries.commands("valhalla_build_tiles")]


def first_attempt_fails_at(env: Env, variant: str = "offroad") -> Outcome:
    outcome = attempt(env, binaries=FailsAt(variant))
    assert outcome.error is not None and outcome.error.stage is Stage.BUILD_TILES
    return outcome


@pytest.fixture
def reset_calls(monkeypatch):
    """Every call to the staging reset, which only a fresh start makes."""
    calls: list[str] = []
    real = schema.reset_segment_schema

    def counting(name):
        calls.append(name)
        return real(name)

    monkeypatch.setattr(schema, "reset_segment_schema", counting)
    return calls


def staging_comment() -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = %s",
            [settings.SEGMENT_SCHEMA_STAGING],
        )
        row = cursor.fetchone()
    return row[0] if row else None


def sql(statement: str, params=()) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


# --- What an attempt writes -----------------------------------------------------------


def test_a_failed_tile_stage_leaves_a_classification_and_a_manifest_for_each_finished_graph(
    env,
) -> None:
    """T2/T3, the write side: the classification manifest names the build, the job, the
    variant extracts' sizes and hashes and the staging schema's token and counts; each
    finished graph has its log and a manifest written last; the unfinished graph has
    neither."""
    outcome = first_attempt_fails_at(env, "offroad")
    manifest = checkpoint.read_classification(env.work)
    assert manifest["job_id"] == JOB and manifest["build_id"] == FIRST
    assert set(manifest["variant_pbfs"]) == set(ORDER)
    for variant in Variant:
        facts = manifest["variant_pbfs"][variant.value]
        pbf = outcome.context.variant_pbf(variant)
        assert facts == {"size": pbf.stat().st_size, "sha256": checkpoint.sha256_file(pbf)}
    staging = manifest["staging"]
    assert staging["schema"] == settings.SEGMENT_SCHEMA_STAGING
    assert staging["segment_rows"] == 5 and staging["border_crossing_rows"] == 1
    assert staging_comment() == f"routemaker-checkpoint:{staging['token']}", "tied to the database"
    assert manifest["closure_probes"] == [], "the list is computed early and kept (none here)"

    assert manifest["hash_seconds"] >= 0
    for variant in ORDER[:-1]:
        directory = env.build_dir(variant)
        graph = json.loads((directory / checkpoint.GRAPH_MANIFEST).read_text())
        assert graph["variant"] == variant and graph["build_id"] == FIRST and graph["job_id"] == JOB
        assert graph["hash_seconds"] >= 0
        assert (directory / checkpoint.BUILD_LOG).read_text() == outcome.context.build_logs[
            Variant(variant)
        ]
        assert {"tiles.tar", "admin.sqlite", "tz_world.sqlite", "build.log"} <= set(
            graph["outputs"]
        )
        assert graph["fingerprint"]["variant_pbf_sha256"]
    assert not (env.build_dir("offroad") / checkpoint.GRAPH_MANIFEST).exists()
    assert outcome.context.checkpoints_written == 1 + 4


def test_the_checkpoint_is_written_last_and_atomically(tmp_path, monkeypatch) -> None:
    """T2: temp file, fsync, rename, directory fsync - in that order - and a crash
    before the rename leaves no manifest at all."""
    order: list[str] = []
    real_replace, real_fsync = os.replace, os.fsync
    monkeypatch.setattr(os, "replace", lambda a, b: (order.append("rename"), real_replace(a, b))[1])
    monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    target = tmp_path / "checkpoint" / "classification.json"
    checkpoint.atomic_write_json(target, {"format": 1, "a": 1})
    assert order == ["fsync", "rename", "fsync"], order
    assert checkpoint.read_json(target) == {"format": 1, "a": 1}

    def refuse(a, b):
        raise OSError("disk full")

    target.unlink()
    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        checkpoint.atomic_write_json(target, {"format": 1, "a": 2})
    assert not target.exists(), "no half-written manifest under the real name"
    assert checkpoint.read_json(target) is None


@pytest.mark.parametrize(
    "content",
    [
        '{"format": 1, "job_id": 8408, "build_',
        "",
        "[]",
        '{"format": 2, "job_id": 8408}',
        "not json",
    ],
)
def test_a_truncated_or_foreign_manifest_is_not_a_checkpoint(env, content, reset_calls) -> None:
    """T2: garbage where the manifest should be is read as no manifest, and the next
    attempt starts fresh (and says so)."""
    first_attempt_fails_at(env)
    checkpoint.classification_path(env.work).write_text(content)
    second = attempt(env, build_id="20261002T000000Z")
    assert second.error is None
    assert not second.context.resumed
    assert built(second.binaries) == ORDER, "everything is built again"
    assert len(reset_calls) == 2, "the staging schema was reset by the fresh start"


# --- T3: resume after the last graph failed -------------------------------------------


def test_a_resume_after_the_last_graph_failed_builds_only_that_graph(env, reset_calls) -> None:
    """T3: the fake sees `valhalla_build_tiles` for offroad only. The admin and timezone
    copies come from the reused standard directory, all five logs and configs are on the
    context, VALIDATE_TILES passes, and the build id is the first attempt's."""
    first_attempt_fails_at(env, "offroad")
    second = attempt(env, build_id=None)
    assert second.error is None
    context = second.context
    assert context.resumed and context.build_id == FIRST
    assert built(second.binaries) == ["offroad"]
    assert second.binaries.commands("valhalla_build_admins") == [], "the admin database is reused"
    copies = {(Path(c[1]), Path(c[2])) for c in second.binaries.commands("cp")}
    standard = env.build_dir("standard")
    offroad = env.build_dir("offroad")
    assert (standard / "admin.sqlite", offroad / "admin.sqlite") in copies
    assert (standard / "tz_world.sqlite", offroad / "tz_world.sqlite") in copies
    assert set(context.build_logs) == set(Variant) == set(context.build_configs)
    assert context.graphs_reused == ORDER[:-1] and context.graphs_built == ["offroad"]
    assert Stage.VALIDATE_TILES in second.report.completed
    assert len(reset_calls) == 1, "T6: a resume never resets the staging schema"
    for command in ("osmium", "curl"):
        assert second.binaries.commands(command) == [], "the extract is not produced again"
    assert "classification from" in context.checkpoint_summary()
    assert "reused: standard, no-trail, ebike, weekend; built: offroad" in (
        context.checkpoint_summary()
    )


def test_a_resumed_rebuild_can_go_on_to_swap(env) -> None:
    """The point of it: the resumed attempt finishes the job, and the checkpoint is
    gone once the swap has begun (T7)."""
    first_attempt_fails_at(env, "weekend")
    second = attempt(env, skip=frozenset(), build_id=None)
    assert second.error is None and second.report.succeeded
    assert built(second.binaries) == ["weekend", "offroad"]
    assert checkpoint.read_classification(env.work) is None
    for variant in ORDER:
        assert os.readlink(env.tiles / variant / "current") == FIRST


def test_a_new_thread_count_is_not_an_input(env, monkeypatch) -> None:
    """T1: the owner changed REBUILD_TILE_CONCURRENCY in the middle of job 8408. It
    invalidates neither checkpoint, and the graph built after it records its own."""
    first_attempt_fails_at(env, "offroad")
    monkeypatch.setattr(settings, "REBUILD_TILE_CONCURRENCY", 1)
    second = attempt(env, build_id=None)
    assert second.error is None and second.context.resumed
    assert built(second.binaries) == ["offroad"]
    config = json.loads((env.build_dir("offroad") / "build-config.json").read_text())
    assert config["mjolnir"]["concurrency"] == 1
    old = json.loads((env.build_dir("standard") / "build-config.json").read_text())
    assert old["mjolnir"]["concurrency"] == 2, "a reused graph keeps the count it was built with"


# --- T4: a damaged graph is rebuilt alone --------------------------------------------


@pytest.mark.parametrize("name", ["tiles.tar", "admin.sqlite", "tz_world.sqlite", "build.log"])
def test_a_graph_with_one_byte_flipped_is_rebuilt_and_only_that_one(env, name) -> None:
    """T4: reuse re-hashes the tile archive and the two databases (and the log)."""
    first_attempt_fails_at(env, "offroad")
    path = env.build_dir("ebike") / name
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    second = attempt(env, build_id=None)
    assert second.error is None
    assert built(second.binaries) == ["ebike", "offroad"]
    assert second.context.graphs_reused == ["standard", "no-trail", "weekend"]


def test_a_graph_with_a_different_size_is_rebuilt(env) -> None:
    first_attempt_fails_at(env, "offroad")
    path = env.build_dir("no-trail") / "tiles.tar"
    path.write_bytes(path.read_bytes() + b"x")
    second = attempt(env, build_id=None)
    assert built(second.binaries) == ["no-trail", "offroad"]


def test_a_missing_output_is_rebuilt(env) -> None:
    first_attempt_fails_at(env, "offroad")
    (env.build_dir("weekend") / "tz_world.sqlite").unlink()
    second = attempt(env, build_id=None)
    assert built(second.binaries) == ["weekend", "offroad"]


# --- T2: partial graphs ----------------------------------------------------------------


def test_a_graph_without_a_manifest_is_partial_and_is_deleted_and_rebuilt(env) -> None:
    """T2: the graph that was running when the attempt died has files but no manifest.
    It is removed (its own build-config.json would otherwise make
    `write_build_config` refuse) and built again, with the graphs after it."""
    first_attempt_fails_at(env, "ebike")
    partial = env.build_dir("ebike")
    assert partial.is_dir() and not (partial / checkpoint.GRAPH_MANIFEST).exists()
    (partial / "stray-from-the-dead-process").write_text("x")
    second = attempt(env, build_id=None)
    assert second.error is None
    assert built(second.binaries) == ["ebike", "weekend", "offroad"]
    assert not (partial / "stray-from-the-dead-process").exists()


def test_a_crash_between_the_outputs_and_the_manifest_leaves_a_partial_graph(
    env, monkeypatch
) -> None:
    """T2: all of the weekend graph's outputs are on disk and the process dies before
    the manifest rename: nothing is reused for it. (A death, not an error: an error
    while writing a manifest is bookkeeping, and the attempt carries on without it.)"""
    real = checkpoint.atomic_write_json
    state = {"armed": True}

    class Killed(BaseException):
        """What SIGKILL looks like from inside: nothing after it runs."""

    def dies_for_weekend(path, payload):
        if Path(path).name == checkpoint.GRAPH_MANIFEST and "weekend" in str(path):
            if state["armed"]:
                state["armed"] = False
                raise Killed("killed before the rename")
        return real(path, payload)

    monkeypatch.setattr(checkpoint, "atomic_write_json", dies_for_weekend)
    with pytest.raises(Killed):
        attempt(env)
    weekend = env.build_dir("weekend")
    assert (weekend / "tiles.tar").is_file() and not (weekend / checkpoint.GRAPH_MANIFEST).exists()
    second = attempt(env, build_id=None)
    assert second.error is None and second.context.resumed
    assert built(second.binaries) == ["weekend", "offroad"]


@pytest.mark.parametrize(
    "damage",
    [
        lambda m: "{" + json.dumps(m)[1:40],  # truncated
        lambda m: json.dumps({**m, "job_id": JOB + 1}),  # another job's
        lambda m: json.dumps({**m, "build_id": "20250101T000000Z"}),  # another build's
        lambda m: json.dumps({**m, "variant": "ebike"}),  # another variant's
        lambda m: json.dumps({**m, "format": 2}),
        lambda m: json.dumps({**m, "fingerprint": {**m["fingerprint"], "lua_sha256": "0" * 64}}),
        lambda m: json.dumps({**m, "outputs": {}}),
    ],
    ids=["truncated", "job", "build", "variant", "format", "fingerprint", "no-outputs"],
)
def test_a_graph_manifest_that_does_not_describe_the_graph_is_not_used(env, damage) -> None:
    first_attempt_fails_at(env, "offroad")
    path = env.build_dir("weekend") / checkpoint.GRAPH_MANIFEST
    path.write_text(damage(json.loads(path.read_text())))
    second = attempt(env, build_id=None)
    assert second.error is None
    assert built(second.binaries) == ["weekend", "offroad"]


def test_changed_lua_rebuilds_every_graph_and_keeps_the_classification(env, monkeypatch) -> None:
    """T1, the graph side: the Lua the build reads (the image's copy under BASE_DIR) is in
    every graph's fingerprint. The classification's own code digest is the injected
    one, which did not move."""
    base = env.root / "base"
    (base / "lua").mkdir(parents=True)
    (base / "lua" / "graph.lua").write_text("-- v1")
    monkeypatch.setattr(settings, "BASE_DIR", base)
    first_attempt_fails_at(env, "offroad")
    (base / "lua" / "graph.lua").write_text("-- v2")
    second = attempt(env, build_id=None)
    assert second.error is None and second.context.resumed
    assert built(second.binaries) == ORDER


def test_a_changed_elevation_tile_rebuilds_every_graph(env) -> None:
    first_attempt_fails_at(env, "offroad")
    tile = next((env.root / "elevation").rglob("*.hgt"))
    tile.write_bytes(tile.read_bytes() + b"\0\0")
    second = attempt(env, build_id=None)
    assert second.error is None and second.context.resumed
    assert built(second.binaries) == ORDER


def test_a_changed_valhalla_binary_rebuilds_every_graph(env, monkeypatch) -> None:
    first_attempt_fails_at(env, "offroad")  # no valhalla binary on PATH: "absent"
    binary = env.root / "valhalla_build_tiles"
    binary.write_bytes(b"v1")
    monkeypatch.setattr(
        checkpoint.shutil, "which", lambda name: str(binary) if "tiles" in name else None
    )
    second = attempt(env, build_id=None)
    assert second.error is None and second.context.resumed
    assert built(second.binaries) == ORDER


# --- T1: what invalidates the classification ---------------------------------------


def invalidated(env: Env, reset_calls, **kwargs) -> Outcome:
    """Run a classification, then change something, then look at the next attempt's
    FETCH_EXTRACT only: did it resume, or start fresh."""
    first = attempt(env, skip=THROUGH_CLASSIFICATION)
    assert first.error is None and checkpoint.read_classification(env.work) is not None
    return first


def change_extract(env: Env) -> None:
    install_source_extract(env.source.parent, changed=True)


def change_file(root_name: str):
    def change(env: Env) -> None:
        (env.code_roots[root_name] / "a.txt").write_text("changed")

    return change


def change_reference(env: Env) -> None:
    (env.reference / "urban-areas.json").write_text(json.dumps([100, 200, 300, 400, 500, 600]))


def change_jurisdiction(env: Env) -> None:
    from core.models import Jurisdiction

    Jurisdiction.objects.filter(layer="state", state="VA").update(name="Virginia, changed")


def move_jurisdiction_edge(env: Env) -> None:
    from django.contrib.gis.geos import MultiPolygon, Polygon

    from core.models import Jurisdiction

    row = Jurisdiction.objects.get(layer="state", state="VA")
    row.geometry = MultiPolygon(Polygon.from_bbox((-77.0, 38.0, -76.89, 39.0)))
    row.save()


def new_override(env: Env) -> None:
    make_override(987654321, {"bicycle": "no"})


def make_override(way: int, value: dict, *, approved: bool = True):
    from django.utils import timezone

    from core.models import Override

    return Override.objects.create(
        kind="access",
        osm_way_id=way,
        value=value,
        reason="test",
        evidence="test",
        approved=approved,
        approved_at=timezone.now() if approved else None,
    )


INPUT_CHANGES = {
    "extract": change_extract,
    "code-src": change_file("src"),
    "code-fixtures": change_file("fixtures"),
    "code-lua": change_file("lua"),
    "code-valhalla": change_file("valhalla"),
    "reference-file": change_reference,
    "jurisdiction-name": change_jurisdiction,
    "jurisdiction-geometry": move_jurisdiction_edge,
    "new-approved-override": new_override,
}


@pytest.mark.parametrize("name", sorted(INPUT_CHANGES))
def test_each_input_to_the_classification_invalidates_it(env, name, reset_calls) -> None:
    """T1: the extract's bytes, any file under src, fixtures, lua or valhalla, the
    reference data, a jurisdiction row, an approved override. The next attempt starts
    fresh: it resets the staging schema, takes a new build id, and says why."""
    invalidated(env, reset_calls)
    before = len(reset_calls)
    INPUT_CHANGES[name](env)
    second = attempt(env, skip=ONLY_FETCH, build_id="20261002T000000Z")
    assert second.error is None
    assert not second.context.resumed, name
    assert len(reset_calls) == before + 1, "a fresh start resets the staging schema"
    assert second.context.build_id != FIRST
    assert "not used" in second.context.resume_note
    assert checkpoint.read_classification(env.work) is None, "deleted first"


def test_an_override_edited_or_withdrawn_invalidates_it_though_the_count_does_not_change(
    env, reset_calls
) -> None:
    """T1: a count and a largest id would not see these."""
    row = make_override(987654321, {"bicycle": "no"})
    other = make_override(987654322, {"bicycle": "yes"}, approved=False)
    invalidated(env, reset_calls)
    # An edited value: same ids, same count.
    row.value = {"bicycle": "dismount"}
    row.save()
    assert not attempt(env, skip=ONLY_FETCH, build_id="20261002T000000Z").context.resumed

    invalidated(env, reset_calls)
    # One unapproved while another is approved: the count of approved rows is the same.
    row.approved, other.approved = False, True
    other.approved_at = row.approved_at
    row.save()
    other.save()
    assert not attempt(env, skip=ONLY_FETCH, build_id="20261003T000000Z").context.resumed


def test_an_unchanged_world_resumes(env, reset_calls) -> None:
    """The control for the whole group: the same checks, nothing changed."""
    invalidated(env, reset_calls)
    second = attempt(env, skip=ONLY_FETCH, build_id=None)
    assert second.error is None and second.context.resumed
    assert second.context.build_id == FIRST


# The classification settings, and how a test moves each. The four that the context
# carries its own value for (a test or a second deployment may point them elsewhere) are
# moved through the context; the rest through the settings.
CONTEXT_VALUED = {
    "COVERAGE_BBOX": lambda env: {"coverage_bbox": (-77.5, 38.5, -76.5, 39.5)},
    "COVERAGE_POLYGON": lambda env: {"coverage_polygon": write_polygon(env)},
    "SEGMENT_SCHEMA_STAGING": lambda env: {
        "staging_schema": settings.SEGMENT_SCHEMA_STAGING + "_c"
    },
    "REBUILD_CROSSINGS_FIXTURE": lambda env: {
        "checked_in_crossings": env.reference / "crossings.json"
    },
}
SETTING_VALUED = sorted(
    set(checkpoint.SETTINGS_OF_KIND[checkpoint.CLASSIFICATION]) - set(CONTEXT_VALUED)
)


def write_polygon(env: Env) -> Path:
    path = env.root / "coverage.geojson"
    path.write_text("{}")
    return path


def test_every_classification_setting_has_a_case_below() -> None:
    assert set(CONTEXT_VALUED) | set(SETTING_VALUED) == set(
        checkpoint.SETTINGS_OF_KIND[checkpoint.CLASSIFICATION]
    )
    assert set(CONTEXT_VALUED) <= set(checkpoint.SETTINGS_OF_KIND[checkpoint.CLASSIFICATION])


@pytest.mark.parametrize("name", sorted(CONTEXT_VALUED))
def test_a_classification_value_the_context_carries_invalidates_it(env, name, reset_calls) -> None:
    invalidated(env, reset_calls)
    moved = CONTEXT_VALUED[name](env)
    try:
        second = attempt(env, skip=ONLY_FETCH, build_id="20261002T000000Z", **moved)
        assert second.error is None
        assert not second.context.resumed, name
    finally:
        schema.drop_segment_schema(settings.SEGMENT_SCHEMA_STAGING + "_c")


@pytest.mark.parametrize("name", SETTING_VALUED)
def test_a_classification_setting_invalidates_it(env, name, reset_calls, monkeypatch) -> None:
    """T1: each setting the classification reads (the Mass Ride widths, the sentinel
    numbers of the checks that need the in-memory context)."""
    invalidated(env, reset_calls)
    monkeypatch.setattr(settings, name, "changed by the test")
    second = attempt(env, skip=ONLY_FETCH, build_id="20261002T000000Z")
    assert second.error is None
    assert not second.context.resumed, name


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REBUILD_TILE_CONCURRENCY", 1),
        ("REBUILD_MIN_FREE_BYTES", 12345),
        ("DISK_GATE_FRACTION", 0.5),
        ("SOURCE_EXTRACT_MAX_AGE", None),
        ("REBUILD_SENTINEL_STEEP_EDGE", ((0, 0), (1, 1))),
        ("SEGMENT_SCHEMA_LIVE", "live_elsewhere"),
    ],
)
def test_settings_that_change_nothing_a_checkpoint_holds_do_not_invalidate_it(
    env, name, value, reset_calls, monkeypatch
) -> None:
    """T1: on purpose, and named in the table as ignored."""
    assert checkpoint.CHECKPOINT_SETTINGS[name] == checkpoint.IGNORED
    invalidated(env, reset_calls)
    monkeypatch.setattr(settings, name, value)
    second = attempt(env, skip=ONLY_FETCH, build_id=None)
    assert second.error is None and second.context.resumed, name


def test_a_sentinel_number_for_a_staging_check_reruns_only_those_checks(env, monkeypatch) -> None:
    """T1: the floors of the checks that read the staging schema are not a reason to
    classify again. The classification is kept, those checks run against the new
    numbers, and the recorded numbers are updated so the next attempt does not."""
    first_attempt_fails_at(env, "offroad")
    before = checkpoint.read_classification(env.work)["fingerprint"]["validation"]
    ran = []
    real = run_module.assert_mass_capacity
    monkeypatch.setattr(
        run_module, "assert_mass_capacity", lambda *a, **k: (ran.append(1), real(*a, **k))[1]
    )
    monkeypatch.setattr(settings, "REBUILD_MASS_CAPACITY_MEDIAN_RANGE", (1, 100000))
    second = attempt(env, build_id=None)
    assert second.error is None
    assert second.context.resumed and second.context.revalidate_staging
    assert ran == [1], "VALIDATE_SEGMENTS ran its staging checks again"
    assert built(second.binaries) == ["offroad"]
    after = checkpoint.read_classification(env.work)["fingerprint"]["validation"]
    assert after != before

    ran.clear()
    third = attempt(env, build_id=None, skip=frozenset(set(Stage) - {Stage.FETCH_EXTRACT}))
    assert third.context.resumed and not third.context.revalidate_staging
    assert ran == []


def test_a_staging_check_that_fails_against_new_numbers_stops_the_resume_before_any_tile(
    env, monkeypatch
) -> None:
    first_attempt_fails_at(env, "offroad")
    monkeypatch.setattr(settings, "REBUILD_MASS_CAPACITY_MEDIAN_RANGE", (5000, 6000))
    second = attempt(env, build_id=None)
    assert second.error is not None and second.error.stage is Stage.VALIDATE_SEGMENTS
    assert isinstance(second.error.cause, ValidationFailed)
    assert built(second.binaries) == []


def test_every_setting_the_pipeline_reads_is_classified() -> None:
    """T1: a setting added to the pipeline must be put in the table (and so be in a
    fingerprint, or be marked as deliberately not in one) before this passes."""
    files = sorted((REPO / "src" / "pipeline").glob("*.py")) + sorted(
        (REPO / "src" / "routemaker").glob("*.py")
    )
    read = checkpoint.settings_read_by(files)
    assert {"REBUILD_TILE_CONCURRENCY", "SEGMENT_SCHEMA_STAGING", "COVERAGE_BBOX"} <= read, (
        "the scan found nothing: a vacuous pass"
    )
    unclassified = sorted(read - set(checkpoint.CHECKPOINT_SETTINGS))
    assert not unclassified, (
        f"classify these in pipeline.checkpoint.CHECKPOINT_SETTINGS: {unclassified}"
    )
    stale = sorted(name for name in checkpoint.CHECKPOINT_SETTINGS if not hasattr(settings, name))
    assert not stale, f"settings that no longer exist: {stale}"
    assert set(checkpoint.CHECKPOINT_SETTINGS.values()) <= {
        checkpoint.CLASSIFICATION,
        checkpoint.VALIDATION,
        checkpoint.GRAPH,
        checkpoint.IGNORED,
    }


def test_the_scan_sees_every_way_a_setting_is_read(tmp_path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from django.conf import settings\n"
        "def f(_setting):\n"
        "    a = _setting('ONE')\n"
        "    b = settings.TWO\n"
        "    c = getattr(settings, 'THREE')\n"
        "    # settings.COMMENTED = 1\n"
        "    '''settings.DOCSTRING'''\n"
        "    d = other.FOUR\n"
    )
    assert checkpoint.settings_read_by([sample]) == {"ONE", "TWO", "THREE"}


# --- T5: guards ------------------------------------------------------------------------


@pytest.mark.parametrize("link", ["current", "previous"])
def test_a_checkpoint_whose_build_is_promoted_is_not_resumed(env, link, reset_calls) -> None:
    """T5: whichever of the two links names it."""
    invalidated(env, reset_calls)
    variant_dir = env.tiles / "ebike"
    variant_dir.mkdir(parents=True, exist_ok=True)
    os.symlink(FIRST, variant_dir / link)
    second = attempt(env, skip=ONLY_FETCH, build_id="20261002T000000Z")
    assert not second.context.resumed
    assert "promoted" in second.context.resume_note


def prepared_tiles(tmp_path: Path, build_id: str = FIRST) -> Path:
    for variant in Variant:
        directory = tmp_path / variant.value / build_id
        directory.mkdir(parents=True)
        (directory / "tiles.tar").write_text("t")
    return tmp_path


def test_remove_partial_graph_removes_this_builds_directory_manifest_first(tmp_path) -> None:
    prepared_tiles(tmp_path)
    directory = tmp_path / "standard" / FIRST
    (directory / checkpoint.GRAPH_MANIFEST).write_text("{}")
    checkpoint.remove_partial_graph(tmp_path, Variant.STANDARD, FIRST, this_build=FIRST)
    assert not directory.exists()
    assert (tmp_path / "no-trail" / FIRST).is_dir(), "only that variant's"


@pytest.mark.parametrize("link", ["current", "previous"])
def test_remove_partial_graph_never_touches_a_promoted_directory(tmp_path, link) -> None:
    """T5, one guard: a directory any variant's current or previous names."""
    prepared_tiles(tmp_path)
    os.symlink(FIRST, tmp_path / "ebike" / link)
    with pytest.raises(CheckpointRefused, match="promoted"):
        checkpoint.remove_partial_graph(tmp_path, Variant.STANDARD, FIRST, this_build=FIRST)
    assert (tmp_path / "standard" / FIRST / "tiles.tar").is_file()


@pytest.mark.parametrize(
    "name", ["current", "../standard", "standard", "x" + FIRST, "", FIRST[:-1]]
)
def test_remove_partial_graph_refuses_a_name_that_is_not_a_build_id(tmp_path, name) -> None:
    """T5, another: only a name that matches the build-id pattern."""
    prepared_tiles(tmp_path)
    (tmp_path / "standard" / "current").mkdir()
    with pytest.raises(CheckpointRefused, match="not a build id"):
        checkpoint.remove_partial_graph(tmp_path, Variant.STANDARD, name, this_build=name)
    assert (tmp_path / "standard" / FIRST / "tiles.tar").is_file()
    assert (tmp_path / "standard" / "current").is_dir()


def test_remove_partial_graph_refuses_another_builds_directory(tmp_path) -> None:
    """T5, the third: a valid, unpromoted build id that is not this rebuild's."""
    other = "20250101T000000Z"
    prepared_tiles(tmp_path, other)
    with pytest.raises(CheckpointRefused, match="not this rebuild's"):
        checkpoint.remove_partial_graph(tmp_path, Variant.STANDARD, other, this_build=FIRST)
    assert (tmp_path / "standard" / other / "tiles.tar").is_file()


def test_remove_partial_graph_never_follows_a_symlink(tmp_path) -> None:
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "precious").write_text("x")
    (tmp_path / "standard").mkdir()
    os.symlink(real, tmp_path / "standard" / FIRST)
    with pytest.raises(CheckpointRefused, match="symlink"):
        checkpoint.remove_partial_graph(tmp_path, Variant.STANDARD, FIRST, this_build=FIRST)
    assert (real / "precious").is_file()


def test_the_rebuild_deletes_nothing_it_may_not_when_a_checkpoint_names_a_promoted_build(
    env,
) -> None:
    """T5 end to end: a resume that reached the graph stage with a promoted build id
    (the manifest said another, the links say this) cannot delete that build's graphs."""
    first_attempt_fails_at(env, "offroad")
    for variant in ORDER:
        os.symlink(FIRST, env.tiles / variant / "current")
    second = attempt(env, build_id=None)
    assert not second.context.resumed, "refused at the door"
    for variant in ORDER[:-1]:
        assert (env.build_dir(variant) / "tiles.tar").is_file(), "the promoted graph is intact"


@pytest.mark.parametrize("how", ["same-size", "longer", "missing"])
def test_a_variant_extract_that_is_not_the_one_recorded_means_a_fresh_start(
    env, how, reset_calls
) -> None:
    """T1/T6: the five variant extracts are what the graphs are built from; the
    checkpoint is used only if each still has its recorded size and SHA-256 (a flipped
    byte keeps the size)."""
    invalidated(env, reset_calls)
    path = env.work / "ebike.osm.pbf"
    if how == "missing":
        path.unlink()
    else:
        data = bytearray(path.read_bytes())
        if how == "same-size":
            data[-1] ^= 0xFF
        else:
            data += b"x"
        path.write_bytes(bytes(data))
    second = attempt(env, skip=ONLY_FETCH, build_id="20261002T000000Z")
    assert second.error is None
    assert not second.context.resumed
    assert "ebike" in second.context.resume_note


def test_the_classification_check_itself_refuses_another_jobs_manifest(tmp_path) -> None:
    """Defence in depth under `find_resumable`: whatever hands it a manifest, a job id
    that is not this attempt's is the first thing refused (before any hashing)."""

    def must_not_measure():
        raise AssertionError("measured before the cheap checks")

    manifest = {"format": 1, "job_id": 1, "build_id": FIRST}
    for job in (2, None):
        problem, _ = checkpoint.classification_problem(
            manifest,
            job_id=job,
            tiles_dir=tmp_path,
            measure_fingerprint=must_not_measure,
            variant_pbfs={},
            hasher=checkpoint.Hasher(),
        )
        assert problem and "job" in problem
    # A manifest that names no job does not match a caller that names none either.
    problem, _ = checkpoint.classification_problem(
        {"format": 1, "job_id": None, "build_id": FIRST},
        job_id=None,
        tiles_dir=tmp_path,
        measure_fingerprint=must_not_measure,
        variant_pbfs={},
        hasher=checkpoint.Hasher(),
    )
    assert problem and "job" in problem


# --- T6: staging -------------------------------------------------------------------------


def break_token(env: Env) -> None:
    sql(f"COMMENT ON SCHEMA {settings.SEGMENT_SCHEMA_STAGING} IS 'routemaker-checkpoint:other'")


def lose_a_segment(env: Env) -> None:
    sql(
        f"DELETE FROM {settings.SEGMENT_SCHEMA_STAGING}.segment WHERE ctid = "
        f"(SELECT ctid FROM {settings.SEGMENT_SCHEMA_STAGING}.segment LIMIT 1)"
    )


def lose_the_crossing(env: Env) -> None:
    sql(f"DELETE FROM {settings.SEGMENT_SCHEMA_STAGING}.border_crossing")


def drop_staging(env: Env) -> None:
    schema.drop_segment_schema(settings.SEGMENT_SCHEMA_STAGING)


def rolled_back_in(env: Env) -> None:
    """What a rollback does: the staging schema is renamed away to be the live one."""
    live = settings.SEGMENT_SCHEMA_LIVE
    schema.drop_segment_schema(live)
    sql(f"ALTER SCHEMA {settings.SEGMENT_SCHEMA_STAGING} RENAME TO {live}")


def recreated_empty(env: Env) -> None:
    schema.reset_segment_schema(settings.SEGMENT_SCHEMA_STAGING)


@pytest.mark.parametrize(
    "damage",
    [break_token, lose_a_segment, lose_the_crossing, drop_staging, rolled_back_in, recreated_empty],
    ids=lambda f: f.__name__,
)
def test_a_staging_schema_that_is_not_the_checkpoints_means_a_fresh_start(
    env, damage, reset_calls
) -> None:
    """T6: a token mismatch, changed counts, a missing schema, a schema renamed in by a
    rollback, or one recreated empty."""
    invalidated(env, reset_calls)
    before = len(reset_calls)
    damage(env)
    after_damage = len(reset_calls)
    second = attempt(env, skip=ONLY_FETCH, build_id="20261002T000000Z")
    assert second.error is None
    assert not second.context.resumed
    assert len(reset_calls) == after_damage + 1 and after_damage >= before


# --- T7: the swap ---------------------------------------------------------------------------


def test_the_swap_deletes_the_checkpoint_before_it_promotes_anything(env, monkeypatch) -> None:
    """T7."""
    first_attempt_fails_at(env, "offroad")
    seen = []
    real = promotion.perform_swap

    def spy(*args, **kwargs):
        seen.append(checkpoint.classification_path(env.work).exists())
        return real(*args, **kwargs)

    monkeypatch.setattr(promotion, "perform_swap", spy)
    second = attempt(env, skip=frozenset(), build_id=None)
    assert second.report.succeeded
    assert seen == [False], "gone when the swap began"
    assert checkpoint.read_classification(env.work) is None


def test_a_swap_that_undid_itself_is_retried_without_rebuilding_anything(env, monkeypatch) -> None:
    """T7: the swap failed and put everything back. The same checkpoint is back (it
    describes the unpromoted staging schema again), so the retry reuses every graph and
    runs VALIDATE_TILES and the swap."""

    def refused(*args, **kwargs):
        assert not checkpoint.classification_path(env.work).exists()
        raise RuntimeError("the swap was refused and undone")

    real = promotion.perform_swap
    monkeypatch.setattr(promotion, "perform_swap", refused)
    first = attempt(env, skip=frozenset())
    assert first.error is not None and first.error.stage is Stage.SWAP
    assert checkpoint.read_classification(env.work)["build_id"] == FIRST, "put back"

    monkeypatch.setattr(promotion, "perform_swap", real)
    second = attempt(env, skip=frozenset(), build_id=None)
    assert second.error is None and second.report.succeeded
    assert second.context.resumed and second.context.build_id == FIRST
    assert built(second.binaries) == [], "no graph was built again"
    assert Stage.VALIDATE_TILES in second.report.completed
    assert second.context.graphs_reused == ORDER


def test_a_swap_whose_undo_did_not_finish_leaves_no_checkpoint(
    env, monkeypatch, reset_calls
) -> None:
    def broken(*args, **kwargs):
        raise promotion.SwapUndoIncomplete(RuntimeError("first"), ["a link"], "the state before")

    monkeypatch.setattr(promotion, "perform_swap", broken)
    first = attempt(env, skip=frozenset())
    assert first.error is not None and first.error.stage is Stage.SWAP
    assert checkpoint.read_classification(env.work) is None
    second = attempt(env, skip=ONLY_FETCH, build_id="20261002T000000Z")
    assert not second.context.resumed


def test_a_resumed_attempt_leaves_live_old_and_the_previous_links_as_they_were(env) -> None:
    """T7 (DB): two completed rebuilds give a live schema, a live_old and a `previous`
    link; a third job fails at the last graph and a fourth attempt resumes it up to the
    swap. Nothing in all that wrote live or live_old, or moved a link."""

    def count(name: str) -> int:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {name}.segment")
            return cursor.fetchone()[0]

    def snapshot() -> dict:
        return {
            "live": count(settings.SEGMENT_SCHEMA_LIVE),
            "live_old": count(settings.SEGMENT_SCHEMA_RETIRED),
            "links": {
                (variant, link): os.readlink(env.tiles / variant / link)
                for variant in ORDER
                for link in ("current", "previous")
                if (env.tiles / variant / link).is_symlink()
            },
        }

    one = attempt(env, job_id=1, skip=frozenset(), build_id="20260901T000000Z")
    assert one.report.succeeded
    # The second week's map differs, so its fingerprint does too.
    install_source_extract(env.source.parent, changed=True)
    two = attempt(env, job_id=2, skip=frozenset(), build_id="20260908T000000Z")
    assert two.report.succeeded
    before = snapshot()
    assert before["live_old"] == 5 and ("ebike", "previous") in before["links"]

    third = attempt(env, job_id=3, binaries=FailsAt("offroad"), build_id=FIRST)
    assert third.error is not None
    assert snapshot() == before
    fourth = attempt(env, job_id=3, build_id=None)
    assert fourth.error is None and fourth.context.resumed
    assert snapshot() == before


# --- T8: the prune ---------------------------------------------------------------------------


def test_the_prune_keeps_the_checkpointed_build_and_nothing_it_may_not(tmp_path) -> None:
    """T8: `protect` is what the pre-run and the final prune hand it."""
    older, newer, newest = "20260101T000000Z", "20260201T000000Z", "20260301T000000Z"
    for build in (older, newer, newest):
        prepared_tiles(tmp_path, build)
    os.symlink(newest, tmp_path / "standard" / "current")
    retention.prune_tile_builds(tmp_path, keep=0, protect=[older])
    for variant in Variant:
        assert (tmp_path / variant.value / older).is_dir(), "the checkpointed build survives"
        assert not (tmp_path / variant.value / newer).exists()
    assert (tmp_path / "standard" / newest).is_dir(), "and so does what `current` names"


# --- T9: the same job only ----------------------------------------------------------------------


def test_a_different_job_starts_fresh_and_deletes_the_old_checkpoint(env, reset_calls) -> None:
    """T9."""
    first_attempt_fails_at(env, "offroad")
    kept, resumable = checkpoint.find_resumable(env.work, JOB + 1)
    assert kept is not None and resumable is None
    second = attempt(env, job_id=JOB + 1, build_id="20261002T000000Z")
    assert second.error is None and not second.context.resumed
    assert built(second.binaries) == ORDER
    assert len(reset_calls) == 2
    assert checkpoint.read_classification(env.work)["job_id"] == JOB + 1


def test_deleting_the_checkpoint_directory_between_attempts_means_a_fresh_start(
    env, reset_calls
) -> None:
    """T9: the operator's switch - and the manifest is gone, so nothing is resumed
    even though the graph directories (with their manifests) are still there."""
    first_attempt_fails_at(env, "offroad")
    shutil.rmtree(checkpoint.checkpoint_dir(env.work))
    second = attempt(env, build_id="20261002T000000Z")
    assert second.error is None and not second.context.resumed
    assert built(second.binaries) == ORDER
    assert len(reset_calls) == 2


def test_a_missing_job_id_never_resumes(env) -> None:
    attempt(env, job_id=None, skip=THROUGH_CLASSIFICATION)
    kept, resumable = checkpoint.find_resumable(env.work, None)
    assert kept is not None and resumable is None


def test_checkpoints_off_writes_nothing_and_resumes_nothing(env) -> None:
    """REBUILD_CHECKPOINTS=0."""
    first = attempt(env, binaries=FailsAt("offroad"), enabled=False)
    assert first.error is not None
    assert not checkpoint.checkpoint_dir(env.work).exists()
    assert not list(env.tiles.rglob(checkpoint.GRAPH_MANIFEST))
    assert (env.build_dir("standard") / "build.log").read_text(), "the log is still kept"
    second = attempt(env, enabled=False, build_id="20261002T000000Z")
    assert second.error is None and not second.context.resumed
    assert built(second.binaries) == ORDER


def test_a_forced_extract_refresh_means_a_fresh_start(env) -> None:
    first_attempt_fails_at(env, "offroad")
    kept, resumable = checkpoint.find_resumable(env.work, JOB, force_fresh=True)
    assert kept is not None and resumable is None


def test_a_checkpoint_left_by_a_finished_job_is_cleared_by_the_next_one(env) -> None:
    attempt(env, skip=THROUGH_CLASSIFICATION)
    assert checkpoint.read_classification(env.work) is not None
    assert checkpoint.reset_checkpoints(env.work) is True
    assert checkpoint.read_classification(env.work) is None
    assert checkpoint.reset_checkpoints(env.work) is False


# --- T10: the stage order -----------------------------------------------------------------


def test_a_segment_failure_is_found_before_any_tile_is_built(
    tmp_path, segment_schemas, states, settings, monkeypatch
) -> None:
    """T10: job 8023's attempt 3 (`calm_run_m` 0 on the ride layer) failed after the
    whole tile stage, in attempt 3. It fails at VALIDATE_SEGMENTS now, before a
    `valhalla_build_tiles` has run, and it is a ValidationFailed, which is terminal."""
    from rebuild_fixtures import REGIONAL_ROUTE_ID

    from config.procrastinate import terminal_causes
    from pipeline import trail_routes

    settings.REBUILD_SENTINEL_CALM_PATH_WAYS = (REGIONAL_ROUTE_ID,)
    settings.REBUILD_SENTINEL_CALM_STREET_WAYS = ()
    settings.REBUILD_CALM_RUN_FLOORS = (1, 1)
    monkeypatch.setattr(trail_routes, "derive_calm_runs", lambda staging: (0, 0))
    source = install_source_extract(tmp_path / "extracts", build=build_long_trails_extract)
    environment = Env(
        source, tmp_path, write_reference_data(tmp_path, urban=(100, 200, 300, 400, 500)), {}
    )
    environment.code_roots.update({})
    outcome = attempt(environment, code_roots=_tmp_code_roots(tmp_path))
    assert outcome.error is not None
    assert outcome.error.stage is Stage.VALIDATE_SEGMENTS
    assert isinstance(outcome.error.cause, ValidationFailed)
    assert isinstance(outcome.error.cause, terminal_causes())
    assert outcome.binaries.commands("valhalla_build_tiles") == []
    assert not list((tmp_path / "tiles").rglob("build-config.json")), "no graph was started"
    assert checkpoint.read_classification(tmp_path / "work") is None, "nothing worth keeping"


def _tmp_code_roots(tmp_path: Path) -> dict:
    roots = {}
    for name in ("src", "fixtures", "lua", "valhalla"):
        directory = tmp_path / "code" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "a.txt").write_text(name)
        roots[name] = directory
    return roots


def test_the_closure_probes_are_computed_before_the_tiles_and_survive_a_resume(env) -> None:
    """The VALIDATE_TILES closure read needs the probe list and no ways: a resumed
    attempt never loads them."""
    from rebuild_fixtures import (
        BESIDE_TRAIL_ID,
        CBD_CYCLE_TRACK_ID,
        CBD_SIDEWALK_ID,
        DIVIDED_NORTH_ID,
        DIVIDED_SOUTH_ID,
        ONE_WAY_ID,
        SEPARATE_ROAD_ID,
        SINGLETRACK_ID,
        TOWPATH_ABOVE_ID,
        TOWPATH_BELOW_ID,
        WEEKEND_CLOSED_ID,
        build_dials_extract,
    )

    install_source_extract(env.source.parent, build=build_dials_extract)
    urban = (
        WEEKEND_CLOSED_ID,
        SEPARATE_ROAD_ID,
        BESIDE_TRAIL_ID,
        CBD_SIDEWALK_ID,
        CBD_CYCLE_TRACK_ID,
        SINGLETRACK_ID,
        TOWPATH_ABOVE_ID,
        TOWPATH_BELOW_ID,
        DIVIDED_NORTH_ID,
        DIVIDED_SOUTH_ID,
        ONE_WAY_ID,
    )
    write_reference_data(env.root, urban=urban)
    first = first_attempt_fails_at(env, "offroad")
    assert [p.way_id for p in first.context.closure_probes] == [SINGLETRACK_ID]
    # The fake can only answer a locate for a graph it built itself.
    reused = FakeBinaries()
    reused.built_from.update(first.binaries.built_from)
    second = attempt(env, build_id=None, binaries=reused)
    assert second.error is None and second.context.resumed
    assert second.context.ways == [] and second.context.stress_by_way == {}
    assert second.context.singletracks == {SINGLETRACK_ID}
    recorded = [p.way_id for p in second.context.closure_probes]
    assert recorded == [p.way_id for p in first.context.closure_probes]
    reports = env.work / run_module.DISCREPANCY_REPORT_DIR
    assert (reports / run_module.SINGLETRACK_REPORT).read_text() == f"{SINGLETRACK_ID}\n"
    assert (
        (reports / run_module.CLOSURE_PROBES_REPORT)
        .read_text()
        .splitlines()[1]
        .startswith(f"{SINGLETRACK_ID},")
    )
    reads = [c for c in second.binaries.commands("valhalla_service") if c[2] == "locate"]
    assert len(reads) == len(Variant), "every graph, the reused ones too, was read back"


# --- Settings ---------------------------------------------------------------------------------


def load_settings_module(name: str):
    import importlib.util

    import config.settings as live

    spec = importlib.util.spec_from_file_location(name, live.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "seconds"),
    [(None, 28800), ("", 28800), ("  ", 28800), ("3600", 3600), ("60", 60), ("82800", 82800)],
)
def test_the_rebuild_budget_is_a_setting_that_defaults_to_eight_hours(
    monkeypatch, value, seconds
) -> None:
    if value is None:
        monkeypatch.delenv("REBUILD_TIMEOUT_S", raising=False)
    else:
        monkeypatch.setenv("REBUILD_TIMEOUT_S", value)
    module = load_settings_module("config_settings_timeout_ok")
    assert module.REBUILD_TIMEOUT_S == seconds and type(module.REBUILD_TIMEOUT_S) is int


@pytest.mark.parametrize("value", ["0", "59", "82801", "-1", "x", "8h", "2.5", "1e4"])
def test_a_rebuild_budget_outside_one_minute_to_twenty_three_hours_is_the_default_and_flagged(
    monkeypatch, value
) -> None:
    """23 hours is the backup-window rule (a scheduled 08:00 UTC rebuild must end before
    the 07:00 UTC backup). Review r2: the settings no longer refuse to load, which took
    the api, the worker and migrate down with a typo in a rebuild knob; every service
    gets the default and the value is kept for the rebuild to refuse."""
    monkeypatch.setenv("REBUILD_TIMEOUT_S", value)
    module = load_settings_module("config_settings_timeout_bad")
    assert module.REBUILD_TIMEOUT_S == module.REBUILD_TIMEOUT_DEFAULT_S
    assert module.REBUILD_TIMEOUT_INVALID == value


def test_a_valid_rebuild_budget_is_not_flagged(monkeypatch) -> None:
    monkeypatch.setenv("REBUILD_TIMEOUT_S", "36000")
    assert load_settings_module("config_settings_timeout_flag").REBUILD_TIMEOUT_INVALID is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("", True), ("1", True), ("true", True), ("0", False), ("off", False)],
)
def test_checkpoints_are_on_unless_switched_off(monkeypatch, value, expected) -> None:
    if value is None:
        monkeypatch.delenv("REBUILD_CHECKPOINTS", raising=False)
    else:
        monkeypatch.setenv("REBUILD_CHECKPOINTS", value)
    assert load_settings_module("config_settings_ckpt_ok").REBUILD_CHECKPOINTS is expected


@pytest.mark.parametrize("value", ["maybe", "2", "-1", "enabled", "on off", "0n"])
def test_a_checkpoint_switch_that_is_not_a_switch_is_refused(monkeypatch, value) -> None:
    """Strict, and only on the rebuild service (compose passes it nowhere else): a typo
    does not silently decide whether a failed attempt's work is kept."""
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("REBUILD_CHECKPOINTS", value)
    with pytest.raises(ImproperlyConfigured, match="REBUILD_CHECKPOINTS must be"):
        load_settings_module("config_settings_ckpt_bad")


@pytest.mark.parametrize("value", ["YES", " On ", "False", "NO"])
def test_the_checkpoint_switch_ignores_case_and_spaces(monkeypatch, value) -> None:
    monkeypatch.setenv("REBUILD_CHECKPOINTS", value)
    expected = value.strip().lower() in {"yes", "on"}
    assert load_settings_module("config_settings_ckpt_case").REBUILD_CHECKPOINTS is expected


def test_the_task_reads_its_budget_from_the_setting() -> None:
    from config import procrastinate

    assert procrastinate.REBUILD_TIMEOUT_S == settings.REBUILD_TIMEOUT_S


def test_compose_hands_both_settings_to_the_services_that_read_them() -> None:
    import yaml

    compose = yaml.safe_load((REPO / "compose.yaml").read_text())
    for service in ("api", "worker", "rebuild"):
        assert "REBUILD_TIMEOUT_S" in compose["services"][service]["environment"], service
    assert "REBUILD_CHECKPOINTS" in compose["services"]["rebuild"]["environment"]


# --- Unit: the pieces ---------------------------------------------------------------------------


def test_the_override_digest_sees_what_a_count_and_a_max_id_do_not() -> None:
    rows = [
        {"id": 1, "kind": "access", "osm_way_id": 5, "value": {"bicycle": "no"}, "reason": "r"},
        {"id": 2, "kind": "stress", "osm_way_id": 6, "value": {"tier": 3}, "reason": "r"},
    ]
    base = checkpoint.overrides_digest(rows)
    assert checkpoint.overrides_digest(reversed(rows)) == base, "ordered by id"
    edited = [dict(rows[0], value={"bicycle": "yes"}), rows[1]]
    assert checkpoint.overrides_digest(edited) != base
    swapped = [dict(rows[0], id=1), dict(rows[1], id=3)]
    assert checkpoint.overrides_digest(swapped) != base
    assert checkpoint.overrides_digest(rows[:1]) != base


def test_canonical_json_does_not_depend_on_set_order() -> None:
    assert checkpoint.canonical({"a": frozenset({"b", "a", "c"})}) == checkpoint.canonical(
        {"a": {"c", "b", "a"}}
    )


def test_tree_digest_follows_content_and_names_not_bytecode(tmp_path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1")
    base = checkpoint.tree_digest(tmp_path)
    (tmp_path / "pkg" / "__pycache__").mkdir()
    (tmp_path / "pkg" / "__pycache__" / "a.cpython.pyc").write_bytes(b"\0")
    (tmp_path / "pkg" / "b.pyc").write_bytes(b"\0")
    assert checkpoint.tree_digest(tmp_path) == base
    (tmp_path / "pkg" / "a.py").write_text("x = 2")
    assert checkpoint.tree_digest(tmp_path) != base
    assert checkpoint.tree_digest(tmp_path / "nope") == "absent"


def test_the_hasher_hashes_a_file_once_until_it_changes(tmp_path) -> None:
    calls = []
    hasher = checkpoint.Hasher(hash_file=lambda p: (calls.append(p), "h")[1])
    path = tmp_path / "f"
    path.write_text("a")
    hasher.sha256(path)
    hasher.sha256(path)
    assert len(calls) == 1
    path.write_text("bb")
    hasher.sha256(path)
    assert len(calls) == 2


def test_the_graph_fingerprint_leaves_out_the_thread_count_and_the_build_directory() -> None:
    config = {
        "mjolnir": {
            "concurrency": 4,
            "tile_dir": "/t/standard/B1/tiles",
            "tile_extract": "/t/standard/B1/tiles.tar",
            "admin": "/t/standard/B1/admin.sqlite",
            "timezone": "/t/standard/B1/tz_world.sqlite",
        }
    }
    moved = json.loads(json.dumps(config))
    moved["mjolnir"]["concurrency"] = 1
    for key in ("tile_dir", "tile_extract", "admin", "timezone"):
        moved["mjolnir"][key] = moved["mjolnir"][key].replace("/B1/", "/B2/")
    assert checkpoint.build_config_digest(
        config, "/t/standard/B1"
    ) == checkpoint.build_config_digest(moved, "/t/standard/B2")
    moved["mjolnir"]["use_admin_db"] = False
    assert checkpoint.build_config_digest(
        config, "/t/standard/B1"
    ) != checkpoint.build_config_digest(moved, "/t/standard/B2")


def test_a_toy_extract_builder_still_produces_distinct_bytes(tmp_path) -> None:
    """The invalidation tests rely on `changed=True` being a different file."""
    one, two = tmp_path / "1.pbf", tmp_path / "2.pbf"
    build_toy_extract(one)
    build_toy_extract(two, changed=True)
    assert checkpoint.sha256_file(one) != checkpoint.sha256_file(two)
    assert fake_fetch is not None and os is not None


# --- Review r2: the settings as production defines them --------------------------------------


def production_settings() -> dict:
    """Every classification and validation setting with the value production gives it,
    read from a fresh execution of `config.settings`: not `django.conf.settings`, which
    the autouse fixture in tests/conftest.py blanks for every test (and which is how the
    tuple key of `REBUILD_SENTINEL_MILITARY_MIN_CLOSED` reached production unencoded)."""
    module = load_settings_module("config_settings_production_values")
    names = (
        checkpoint.SETTINGS_OF_KIND[checkpoint.CLASSIFICATION]
        + checkpoint.SETTINGS_OF_KIND[checkpoint.VALIDATION]
    )
    return {name: getattr(module, name) for name in names}


def test_every_classification_and_validation_setting_digests_with_its_production_value() -> None:
    """Review r2, the blocker: every rebuild with checkpoints on failed at FETCH_EXTRACT,
    because `json.dumps` cannot encode a dict with a tuple key."""
    values = production_settings()
    military = values["REBUILD_SENTINEL_MILITARY_MIN_CLOSED"]
    assert any(not isinstance(key, str) for key in military), (
        "the shape that broke the digest is still in production, so this test still covers it"
    )
    assert military != settings.REBUILD_SENTINEL_MILITARY_MIN_CLOSED, (
        "read past the autouse fixture, not through it"
    )
    for name, value in values.items():
        one = checkpoint.settings_digest({name: value})
        assert one == checkpoint.settings_digest({name: value}), name
    for kind in (checkpoint.CLASSIFICATION, checkpoint.VALIDATION):
        subset = {name: values[name] for name in checkpoint.SETTINGS_OF_KIND[kind]}
        backwards = dict(reversed(list(subset.items())))
        assert checkpoint.settings_digest(subset) == checkpoint.settings_digest(backwards)


def test_the_start_fingerprint_is_measured_with_every_production_setting_in_place(
    env, monkeypatch
) -> None:
    """The same blocker through the production path: FETCH_EXTRACT measures the start
    fingerprint with the real values (the military floors' tuple key among them), and
    neither fails the stage nor turns the checkpoints off."""
    for name, value in production_settings().items():
        if name not in CONTEXT_VALUED:
            monkeypatch.setattr(settings, name, value)
    outcome = attempt(env, skip=ONLY_FETCH)
    assert outcome.error is None, outcome.error
    assert outcome.context.checkpoints, "the measurement did not fall back to no checkpoints"
    assert outcome.context.start_fingerprint["inputs"]["settings"]


def test_canonical_text_handles_any_mapping_key_and_tags_its_type() -> None:
    military = {"Fort Myer": 3, ("Bolling Air Force Base", "Joint Base Anacostia Bolling"): 2}
    text = checkpoint.canonical({"floors": military})
    reordered = dict(reversed(list(military.items())))
    assert checkpoint.canonical({"floors": reordered}) == text, "order-free"
    assert checkpoint.canonical({1: "a"}) != checkpoint.canonical({"1": "a"}), "1 is not '1'"
    assert checkpoint.canonical({("a", "b"): 1}) != checkpoint.canonical({"('a', 'b')": 1})
    assert checkpoint.canonical({"a": {2: {"x", "y"}}}) == checkpoint.canonical(
        {"a": {2: {"y", "x"}}}
    ), "nested, and a set inside a mapping inside a mapping"
    assert checkpoint.canonical({"p": Path("/data/x")}) == checkpoint.canonical({"p": "/data/x"})
    assert checkpoint.canonical([1, (2, 3)]) == checkpoint.canonical([1, [2, 3]])
    assert checkpoint.canonical({frozenset({1, 2}): 0}) == checkpoint.canonical(
        {frozenset({2, 1}): 0}
    )
    # The type tag is what keeps two keys that encode the same way apart.
    assert checkpoint.canonical({(1, 2): 0, 3: 0}) != checkpoint.canonical(
        {frozenset({1, 2}): 0, 3: 0}
    )
    assert checkpoint.canonical({Path("a"): 0, 1: 0}) != checkpoint.canonical({"a": 0, 1: 0})


# --- Review r2: checkpoints are best effort --------------------------------------------------


def test_a_classification_checkpoint_that_cannot_be_written_does_not_fail_the_rebuild(
    env, monkeypatch
) -> None:
    """A database hiccup while stamping the token: logged, checkpoints off for the rest of
    the attempt, and the rebuild goes on to build and validate every graph."""

    def hiccup(*args, **kwargs):
        raise RuntimeError("server closed the connection unexpectedly")

    monkeypatch.setattr(checkpoint, "stamp_staging", hiccup)
    outcome = attempt(env)
    assert outcome.error is None, outcome.error
    assert Stage.VALIDATE_TILES in outcome.report.completed
    assert not outcome.context.checkpoints
    assert checkpoint.read_classification(env.work) is None
    assert outcome.context.checkpoints_written == 0
    assert not any((env.build_dir(v) / checkpoint.GRAPH_MANIFEST).exists() for v in ORDER)
    assert all((env.build_dir(v) / checkpoint.BUILD_LOG).is_file() for v in ORDER)


def test_a_graph_manifest_that_cannot_be_written_does_not_fail_the_rebuild(
    env, monkeypatch
) -> None:
    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(checkpoint, "write_graph_manifest", full)
    outcome = attempt(env)
    assert outcome.error is None, outcome.error
    assert checkpoint.read_classification(env.work) is not None, "written before the tiles"
    assert outcome.context.checkpoints_written == 1
    assert not outcome.context.checkpoints


def test_inputs_that_cannot_be_measured_at_the_start_do_not_fail_the_rebuild(
    env, monkeypatch
) -> None:
    def hiccup():
        raise RuntimeError("could not read the jurisdiction table")

    monkeypatch.setattr(checkpoint, "jurisdiction_digest", hiccup)
    outcome = attempt(env)
    assert outcome.error is None, outcome.error
    assert outcome.context.start_fingerprint is None and not outcome.context.checkpoints
    assert checkpoint.read_classification(env.work) is None


def test_a_dangling_link_in_the_reference_data_is_part_of_its_digest(tmp_path) -> None:
    (tmp_path / "a.csv").write_text("x")
    clean = checkpoint.reference_digest(tmp_path, None)
    (tmp_path / "stale.csv").symlink_to(tmp_path / "gone.csv")
    dangling = checkpoint.reference_digest(tmp_path, None)
    assert dangling != clean


def test_a_resume_that_cannot_be_checked_starts_fresh_and_deletes_the_abandoned_build(
    env, monkeypatch, reset_calls
) -> None:
    first_attempt_fails_at(env, "offroad")
    assert env.build_dir("standard").is_dir()

    def hiccup():
        raise RuntimeError("could not read the jurisdiction table")

    monkeypatch.setattr(checkpoint, "jurisdiction_digest", hiccup)
    second = attempt(env, build_id=None)
    assert second.error is None, second.error
    assert not second.context.resumed and second.context.resume_refused
    assert "could not be checked" in second.context.resume_note
    assert built(second.binaries) == ORDER
    assert second.context.build_id != FIRST
    assert not any(env.build_dir(v).exists() for v in ORDER), (
        "the refused checkpoint's graphs were deleted before the fresh gate"
    )
    assert len(reset_calls) == 2


def test_a_graph_that_cannot_be_checked_is_built_again(env, monkeypatch) -> None:
    first_attempt_fails_at(env, "offroad")
    real = checkpoint.graph_problem

    def flaky(build_dir, **kwargs):
        if kwargs["variant"] is Variant.STANDARD:
            raise OSError(5, "Input/output error")
        return real(build_dir, **kwargs)

    monkeypatch.setattr(checkpoint, "graph_problem", flaky)
    second = attempt(env, build_id=None)
    assert second.error is None, second.error
    assert second.context.resumed
    assert built(second.binaries) == ["standard", "offroad"]


def test_the_guarded_delete_is_checked_against_the_adopted_manifests_build(
    env, monkeypatch
) -> None:
    """Nit 5 of review r2: `this_build` comes from the manifest the attempt adopted, a
    second source beside the context's own build id."""
    first_attempt_fails_at(env, "offroad")
    (env.build_dir("weekend") / checkpoint.GRAPH_MANIFEST).unlink()
    calls = []
    real = checkpoint.remove_partial_graph

    def spy(tiles_dir, variant, build_id, *, this_build):
        calls.append((variant.value, build_id, this_build))
        return real(tiles_dir, variant, build_id, this_build=this_build)

    monkeypatch.setattr(checkpoint, "remove_partial_graph", spy)
    second = attempt(env, build_id=None)
    assert second.error is None
    assert second.context.resumed_build_id == FIRST
    assert calls == [("weekend", FIRST, FIRST), ("offroad", FIRST, FIRST)]


# --- Review r2: the resume's disk gate, and the hashing ---------------------------------------


def test_a_resume_sizes_its_disk_gate_for_the_graphs_still_to_build(env, monkeypatch) -> None:
    first_attempt_fails_at(env, "weekend")
    asked = []
    real = tiles.check_resume_disk_gate

    def spy(tiles_dir, to_build, *args, **kwargs):
        asked.append([variant.value for variant in to_build])
        return real(tiles_dir, to_build, *args, **kwargs)

    monkeypatch.setattr(tiles, "check_resume_disk_gate", spy)
    second = attempt(env, build_id=None)
    assert second.error is None and second.context.resumed
    assert asked == [["weekend", "offroad"]]


def test_the_resume_gate_counts_only_what_is_left_to_build(tmp_path) -> None:
    from collections import namedtuple

    Usage = namedtuple("Usage", "total used free")
    tiles_dir = tmp_path / "tiles"
    for variant in Variant:
        directory = tiles_dir / variant.value / FIRST
        directory.mkdir(parents=True)
        (directory / "tiles.tar").write_bytes(b"x" * 1000)
        (tiles_dir / variant.value / "current").symlink_to(FIRST)
    disk = lambda path: Usage(total=100_000, used=50_000, free=50_000)  # noqa: E731
    gate = tiles.check_resume_disk_gate(tiles_dir, [Variant.OFFROAD], 500, 10**9, 0.8, disk)
    assert gate.required == 1000 + 500, "one served graph and the source once"
    whole = tiles.check_resume_disk_gate(tiles_dir, list(Variant), 500, 10**9, 0.8, disk)
    assert whole.required == 1000 * len(Variant) + 500
    tight = lambda path: Usage(total=100_000, used=78_000, free=22_000)  # noqa: E731
    assert tiles.check_resume_disk_gate(tiles_dir, [Variant.OFFROAD], 500, 10**9, 0.8, tight)
    with pytest.raises(tiles.DiskGateRefused, match="still has to build standard"):
        tiles.check_resume_disk_gate(tiles_dir, list(Variant), 500, 10**9, 0.8, tight)


def test_the_manifests_record_the_time_spent_hashing(env) -> None:
    outcome = first_attempt_fails_at(env, "offroad")
    assert checkpoint.read_classification(env.work)["hash_seconds"] >= 0
    graph = json.loads((env.build_dir("standard") / checkpoint.GRAPH_MANIFEST).read_text())
    assert graph["hash_seconds"] >= 0
    assert outcome.context.hasher.seconds > 0


def test_the_installed_packages_are_an_input(env, monkeypatch, reset_calls) -> None:
    """Nit 6 of review r2: an image rebuilt with only a dependency changed."""
    first_attempt_fails_at(env, "offroad")
    monkeypatch.setattr(checkpoint, "packages_digest", lambda: "another venv")
    second = attempt(env, build_id=None)
    assert not second.context.resumed
    assert "packages" in second.context.resume_note
    assert len(reset_calls) == 2


def test_the_package_digest_is_stable() -> None:
    digest = checkpoint.packages_digest()
    assert digest == checkpoint.packages_digest() and len(digest) == 64


def test_the_classification_is_released_only_when_asked(env) -> None:
    kept = attempt(env)
    assert kept.context.ways, "a test (and the default) keeps the whole context"
    released = attempt(
        env, job_id=JOB + 1, build_id="20261002T000000Z", release_after_classification=True
    )
    assert released.error is None, released.error
    context = released.context
    assert not context.ways and not context.stress_by_way and context.reference is None
    assert Stage.VALIDATE_TILES in released.report.completed, "nothing after needed them"


# --- Review r2: the timeout retry's bound ----------------------------------------------------


def test_the_timeout_retry_count_is_per_job_and_a_broken_record_is_the_cap(tmp_path) -> None:
    assert checkpoint.timeout_retries(tmp_path, 7) == 0
    assert checkpoint.record_timeout_retry(tmp_path, 7) == 1
    assert checkpoint.record_timeout_retry(tmp_path, 7) == 2
    assert checkpoint.timeout_retries(tmp_path, 7) == 2
    assert checkpoint.timeout_retries(tmp_path, 8) == 0, "another job starts from none"
    (checkpoint.checkpoint_dir(tmp_path) / checkpoint.TIMEOUT_RETRIES_NAME).write_text("{")
    assert checkpoint.timeout_retries(tmp_path, 7) == checkpoint.MAX_TIMEOUT_RETRIES


def test_a_commands_own_time_limit_is_not_the_budget_running_out() -> None:
    """Nit 4 of review r2: the closure gate's two-minute read is marked as its own."""
    import subprocess
    import time
    import types

    from config.procrastinate import is_budget_timeout, timed_out_with_progress

    progressed = types.SimpleNamespace(checkpoints_written=3, resume_refused=False)
    with pytest.raises(subprocess.TimeoutExpired) as own:
        run_module._run_command(["sleep", "5"], deadline=time.monotonic() + 3600, timeout=0.1)
    assert own.value.budget_exhausted is False
    assert not is_budget_timeout(own.value) and not timed_out_with_progress(own.value, progressed)
    with pytest.raises(subprocess.TimeoutExpired) as budget:
        run_module._run_command(["sleep", "5"], deadline=time.monotonic() + 0.1, timeout=120)
    assert budget.value.budget_exhausted is True
    assert timed_out_with_progress(budget.value, progressed)
    refused = types.SimpleNamespace(checkpoints_written=3, resume_refused=True)
    assert not timed_out_with_progress(budget.value, refused), (
        "an attempt whose resume was refused started fresh: what it wrote is not progress"
    )


# --- Review r3: tests that pin what r2's mutants showed was unpinned ---------------------------


def test_canonical_text_is_the_same_in_every_process() -> None:
    """Every attempt is a new process with its own hash seed; a set emitted in iteration
    order would make the fingerprint differ on each, and every resume would be refused."""
    import subprocess
    import sys

    code = (
        "from pipeline.checkpoint import canonical; "
        "print(canonical({'s': frozenset('abcdefghij'), 'm': {frozenset('xyzuvw'): 1, 2: 3}}))"
    )
    outputs = set()
    for seed in ("1", "2", "3"):
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO / "src",
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO / "src")},
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.add(result.stdout)
    assert len(outputs) == 1, outputs


def test_the_guarded_delete_uses_the_adopted_manifests_build_not_the_contexts(
    env, monkeypatch
) -> None:
    """Review r2 nit 5, M11: on a resume `context.build_id` equals the manifest's, so the
    spy test cannot tell the two sources apart. Make them differ: the delete must be
    refused against the manifest's build, and the other build's directory must survive."""
    drift = "20261002T000000Z"
    first_attempt_fails_at(env, "offroad")
    (env.build_dir("weekend") / checkpoint.GRAPH_MANIFEST).unlink()
    other = env.build_dir("weekend", drift)
    other.mkdir(parents=True)
    (other / "tiles.tar").write_text("someone else's")
    seen = []
    real_handlers = build_handlers
    real_problem = checkpoint.graph_problem

    def capture(context, **kwargs):
        seen.append(context)
        return real_handlers(context, **kwargs)

    def drifting(build_dir, **kwargs):
        problem = real_problem(build_dir, **kwargs)
        if kwargs["variant"] is Variant.WEEKEND:
            seen[0].build_id = drift
        return problem

    monkeypatch.setitem(globals(), "build_handlers", capture)
    monkeypatch.setattr(checkpoint, "graph_problem", drifting)
    second = attempt(env, build_id=None)
    assert second.error is not None and isinstance(second.error.cause, CheckpointRefused)
    assert "is not this rebuild's build" in str(second.error.cause)
    assert (other / "tiles.tar").is_file(), "another build's directory was deleted"


def test_the_resume_gate_sizes_a_variant_with_no_served_graph_at_its_share_of_the_floor(
    tmp_path,
) -> None:
    from collections import namedtuple

    Usage = namedtuple("Usage", "total used free")
    disk = lambda path: Usage(total=10**12, used=1000, free=10**12 - 1000)  # noqa: E731
    gate = tiles.check_resume_disk_gate(
        tmp_path / "tiles", [Variant.OFFROAD], 500, 10**9, 0.8, disk
    )
    assert gate.required == 10**9 // len(Variant) + 500


def test_the_resume_gate_refuses_when_less_is_free_than_is_needed_at_a_low_percent_full(
    tmp_path,
) -> None:
    """Reserved blocks make `used + free < total`: the volume is 11% full by the gate's
    own arithmetic and still has less free than the build needs."""
    from collections import namedtuple

    Usage = namedtuple("Usage", "total used free")
    tiles_dir = tmp_path / "tiles"
    (tiles_dir / "offroad" / FIRST).mkdir(parents=True)
    (tiles_dir / "offroad" / FIRST / "tiles.tar").write_bytes(b"x" * 1000)
    (tiles_dir / "offroad" / "current").symlink_to(FIRST)
    scarce = lambda path: Usage(total=100_000, used=10_000, free=1_000)  # noqa: E731
    with pytest.raises(tiles.DiskGateRefused, match="still has to build offroad"):
        tiles.check_resume_disk_gate(tiles_dir, [Variant.OFFROAD], 500, 10**9, 0.8, scarce)


@pytest.mark.parametrize("failing", ["graph_fingerprint", "elevation_digest", "binaries_digest"])
def test_a_graph_fingerprint_that_cannot_be_measured_does_not_fail_the_rebuild(
    env, monkeypatch, failing
) -> None:
    """M19: fingerprinting a graph is bookkeeping; the rebuild builds and validates
    every graph and writes no graph manifest."""

    def hiccup(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(checkpoint, failing, hiccup)
    outcome = attempt(env)
    assert outcome.error is None, outcome.error
    assert Stage.VALIDATE_TILES in outcome.report.completed
    assert not outcome.context.checkpoints
    assert built(outcome.binaries) == ORDER
    assert not any((env.build_dir(v) / checkpoint.GRAPH_MANIFEST).exists() for v in ORDER)


def test_a_build_log_that_cannot_be_written_does_not_fail_the_rebuild(env, monkeypatch) -> None:
    real = Path.write_text

    def full(self, *args, **kwargs):
        if self.name == checkpoint.BUILD_LOG:
            raise OSError(28, "No space left on device")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", full)
    outcome = attempt(env)
    assert outcome.error is None, outcome.error
    assert Stage.VALIDATE_TILES in outcome.report.completed
    assert not outcome.context.checkpoints
    assert not any((env.build_dir(v) / checkpoint.BUILD_LOG).exists() for v in ORDER)


def test_new_validation_numbers_that_cannot_be_recorded_do_not_fail_the_resume(
    env, monkeypatch
) -> None:
    first_attempt_fails_at(env, "offroad")
    monkeypatch.setattr(settings, "REBUILD_MASS_CAPACITY_MEDIAN_RANGE", (1, 100000))

    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(checkpoint, "atomic_write_json", full)
    second = attempt(env, build_id=None)
    assert second.error is None, second.error
    assert second.context.resumed and second.context.revalidate_staging
    assert not second.context.checkpoints
    assert Stage.VALIDATE_TILES in second.report.completed
