"""The pipeline, wired and run end to end.

Until this existed, every module in `pipeline/` was called only from its own
unit test: there was no OSM reader, no writer, no handler set, and the stage
ordering tests asserted an enum against itself. This runs a real PBF through
the real stages into a real staging schema, and then through the real swap
into the live one.

Only the binaries are stood in for. The handler set is the production one,
built with nothing injected but the command runner, the 3DEP fetch and the
disk measurement - so the samplers that read the built tiles back, the dated
tile directory, the promotion, the settings table and the drift report all run
as the weekly task runs them.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import osmium
import pytest
from django.conf import settings
from django.db import connection
from rebuild_fixtures import (
    REPO,
    FakeBinaries,
    box,
    build_toy_extract,
    fake_fetch,
    roomy_disk,
    state_polygons,
    write_reference_data,
)

from pipeline.borders import SyntheticNodeIds
from pipeline.rebuild import RebuildFailed, Stage, run_rebuild
from pipeline.run import RebuildContext, build_handlers
from pipeline.variants import Variant

pytestmark = pytest.mark.django_db(transaction=True)

NOT_SWAPPED = frozenset({Stage.SWAP, Stage.RECONCILE})


@pytest.fixture
def states():
    yield from state_polygons()


@pytest.fixture
def workspace(segment_schemas):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.osm.pbf"
        build_toy_extract(source)
        yield source, root


def count(schema: str, table: str = "segment") -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {schema}.{table}")
        return cursor.fetchone()[0]


def run_pipeline(
    source: Path,
    root: Path,
    *,
    binaries: FakeBinaries | None = None,
    urban=(100, 200, 300, 400, 500),
    sidepath=(),
    volume=(),
    skip: frozenset[Stage] = frozenset(),
    build_id: str | None = None,
    disk_usage=roomy_disk,
):
    """The weekly task's call, with the binaries stood in for."""
    reference = write_reference_data(root, urban=urban, sidepath=sidepath, volume=volume)
    context = RebuildContext(
        source_pbf=source,
        work_dir=root / "work",
        reference_dir=reference,
        tiles_dir=root / "tiles",
        elevation_dir=root / "elevation",
        **({"build_id": build_id} if build_id else {}),
    )
    handlers = build_handlers(
        context,
        run=binaries or FakeBinaries(),
        fetch_elevation=fake_fetch,
        disk_usage=disk_usage,
    )
    report = run_rebuild(handlers, skip=skip)
    return context, report


# --- The pre-swap stages -------------------------------------------------------


def test_a_full_rebuild_populates_the_staging_schema(workspace, states) -> None:
    source, root = workspace
    _live, staging = settings.SEGMENT_SCHEMA_LIVE, settings.SEGMENT_SCHEMA_STAGING
    context, report = run_pipeline(source, root, skip=NOT_SWAPPED)

    assert report.completed, "stages must have run"
    assert count(staging) == 5, "one segment per way"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id, stress_tier FROM {staging}.segment ORDER BY osm_way_id")
        tiers = dict(cursor.fetchall())

    assert tiers[200] == 1, "a trail is lowest stress"
    assert tiers[300] == 1, "a gravel farm track is a low-stress choice, not a hazard"
    assert tiers[100] >= 3, "a 35 mph secondary with no facility is high stress"


def test_the_border_node_reaches_the_staged_crossings_table(workspace, states) -> None:
    """The node ids are reassigned each rebuild, so the table is what records
    what each one means - and before the swap it is in staging, not live."""
    source, root = workspace
    staging = settings.SEGMENT_SCHEMA_STAGING
    run_pipeline(source, root, skip=NOT_SWAPPED)

    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT node_id, osm_way_id, state_a, state_b FROM {staging}.border_crossing"
        )
        rows = cursor.fetchall()
    assert len(rows) == 1
    node_id, way_id, state_a, state_b = rows[0]
    assert {state_a, state_b} == {"DC", "VA"}
    assert way_id == 100
    assert SyntheticNodeIds.is_synthetic(node_id)
    assert count(settings.SEGMENT_SCHEMA_LIVE, "border_crossing") == 0, "live is not written"


def test_the_written_extract_carries_the_border_node_in_the_way(workspace, states) -> None:
    """Round-tripped through a real PBF: a minted node id has to survive the
    write, which nothing verified before."""
    from pipeline.extract import read_ways

    source, root = workspace
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    ways = {w.osm_id: w for w in read_ways(context.variant_pbf(Variant.STANDARD))}
    assert any(SyntheticNodeIds.is_synthetic(node_id) for node_id in ways[100].node_ids)
    assert 200 in ways, "the standard variant keeps trails"


def test_the_written_extract_keeps_its_node_block_sorted(workspace, states) -> None:
    """valhalla_build_tiles rejects an unsorted file outright.

    It reads node ids as unsigned and requires ascending order, so it aborts with
    "Detected unsorted input data" before writing a tile. The first version
    minted negative ids - which arrive as values near 2**64 - and wrote them
    ahead of the source nodes, so every tile build would have failed on the first
    block. Neither half was checked: the assertions were that the id was negative
    and that it came back out of the file again.
    """
    source, root = workspace
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    class Order(osmium.SimpleHandler):
        def __init__(self) -> None:
            super().__init__()
            self.node_ids: list[int] = []

        def node(self, n) -> None:  # noqa: N802
            self.node_ids.append(n.id)

    for variant in Variant:
        order = Order()
        order.apply_file(str(context.variant_pbf(variant)))
        assert order.node_ids == sorted(order.node_ids), f"{variant.value} node block is unsorted"
        minted = [i for i in order.node_ids if SyntheticNodeIds.is_synthetic(i)]
        source_ids = [i for i in order.node_ids if not SyntheticNodeIds.is_synthetic(i)]
        assert minted, f"{variant.value} carries no minted node"
        assert min(minted) > max(source_ids), "minted nodes must append, not interleave"


def test_the_no_trail_variant_drops_the_trail(workspace, states) -> None:
    from pipeline.extract import read_ways

    source, root = workspace
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    ways = {w.osm_id for w in read_ways(context.variant_pbf(Variant.NO_TRAIL))}
    assert 200 not in ways, "a mass ride cannot use an eight-foot path"
    assert 100 in ways


def test_the_ebike_variant_is_not_a_copy_of_standard(workspace, states) -> None:
    """inject()'s result was computed and discarded, so the e-bike extract was
    byte-identical to standard and an e-bike route could run where e-bikes are
    barred - the app asserting a legality it has no basis for."""
    from pipeline.extract import read_ways

    source, root = workspace
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    ebike = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(Variant.EBIKE))}
    standard = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(Variant.STANDARD))}
    assert ebike[400].get("bicycle") == "no", "an e-bike-barred way must be barred here"
    assert standard[400].get("bicycle") != "no", "and not on the standard variant"


def test_stress_reaches_the_extract_the_tiles_are_built_from(workspace, states) -> None:
    """Classification ran after the tiles were built, so the tag transform read
    a tier that did not exist yet and the graph carried no stress at all."""
    from pipeline.extract import read_ways

    source, root = workspace
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    tags = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(Variant.STANDARD))}
    assert tags[100].get("rm:stress_tier"), "every way must carry its tier"
    assert tags[200].get("rm:trail_class") == "yes"


def test_a_sidepath_only_bridge_is_dropped_from_the_no_trail_variant(workspace, states) -> None:
    """The id set was plumbed and never populated, and the lookup read a tag no
    real way carries - so the router could hand a thousand-person field a bridge
    sidewalk with no way off it mid-span."""
    from pipeline.extract import read_ways

    source, root = workspace
    context, _ = run_pipeline(source, root, sidepath=(500,), skip=NOT_SWAPPED)

    no_trail = {w.osm_id for w in read_ways(context.variant_pbf(Variant.NO_TRAIL))}
    standard = {w.osm_id for w in read_ways(context.variant_pbf(Variant.STANDARD))}
    assert 500 in standard
    assert 500 not in no_trail


def test_volume_reaches_the_classifier(workspace, states) -> None:
    """conflate() was called only from its own test, so aadt was None for every
    way and the input the plan spends pages on never reached the map."""
    source, root = workspace
    volume = [
        {
            "id": "count-1",
            "coordinates": [[-77.02, 38.90], [-76.98, 38.90]],
            "aadt": 900,
            "source": "state",
            "year": 2025,
        }
    ]
    context, _ = run_pipeline(source, root, volume=volume, skip=NOT_SWAPPED)
    assert context.aadt_by_way.get(100) == (900, "state")
    assert context.stress_by_way[100].volume_source == "state"


def test_a_way_clipping_an_authority_by_a_sliver_is_not_tagged_with_it(workspace, states) -> None:
    """assign_way returns every authority a way touches with the share inside
    each and says the caller decides. The caller did not decide: a road that
    clipped a park boundary by a metre was tagged with the park agency, and the
    permit list for a ride that never entered the park named it.

    The trail (way 200) runs from -77.04 to -77.03. One park covers its western
    2 percent, another its eastern 40 percent."""
    from core.models import Jurisdiction

    Jurisdiction.objects.create(
        layer="manager", name="Sliver Park", state="DC", geometry=box(-77.05, -77.0398)
    )
    Jurisdiction.objects.create(
        layer="manager", name="Big Park", state="DC", geometry=box(-77.034, -77.02)
    )
    source, root = workspace
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    tagged = set(context.ways_by_id[200].tags["_jurisdictions"].split(","))
    assert "Big Park" in tagged
    assert "Sliver Park" not in tagged
    assert "MPD" in tagged, "the dominant authority on every layer is always kept"


# --- Validation, and what a failed rebuild leaves behind ------------------------------


def test_a_silent_lua_fallback_fails_the_build(workspace, states) -> None:
    """Valhalla logs nothing when it cannot load the configured script and uses
    its built-in transform instead, dropping every derived tag."""
    source, root = workspace
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=FakeBinaries(log="tiles built, 0 errors"))
    assert caught.value.stage is Stage.VALIDATE
    assert "built-in transform" in str(caught.value.cause)


def test_the_wrong_lua_script_fails_the_build(workspace, states) -> None:
    source, root = workspace
    with pytest.raises(RebuildFailed):
        run_pipeline(
            source,
            root,
            binaries=FakeBinaries(log="Using LUA script: /usr/share/valhalla/graph.lua"),
        )


def test_a_tile_build_without_elevation_fails_the_build(workspace, states) -> None:
    """Caching the HGT data is not the same as using it: with no elevation
    directory every hills dial is inert and the grade cap has nothing to read."""
    source, root = workspace
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=FakeBinaries(grade=0.0))
    assert "elevation directory" in str(caught.value.cause)


def test_a_transform_that_loads_but_does_nothing_fails_the_build(workspace, states) -> None:
    """The log line proves a script was loaded; it does not prove the script did
    anything. Only reading a known edge back proves the derived tags survived:
    a plain street reporting no cycle lane is the transform having done
    nothing, whatever the log said."""
    source, root = workspace
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=FakeBinaries(cycle_lane="none"))
    assert "produced nothing usable" in str(caught.value.cause)


def test_validation_reads_every_variant_back_through_its_own_build_config(
    workspace, states
) -> None:
    """The samplers are not injected in production; they ask valhalla_service,
    in one-shot mode, against the build config of the dated directory each
    variant was just built into. If they read anything else - the serving
    config, a shared directory - they would be validating last week's graph."""
    source, root = workspace
    binaries = FakeBinaries()
    context, _ = run_pipeline(source, root, binaries=binaries, skip=NOT_SWAPPED)

    reads = binaries.commands("valhalla_service")
    read_configs = {Path(c[1]) for c in reads}
    assert read_configs == set(context.build_configs.values())
    assert len(read_configs) == 3, "every variant's build must be read back"
    for config_path in read_configs:
        assert context.build_id in config_path.parts, "the read targets the dated build"

    builds = binaries.commands("valhalla_build_tiles")
    assert {Path(c[2]) for c in builds} == read_configs, "read what was built"
    for c in builds:
        config = json.loads(Path(c[2]).read_text())
        assert config["mjolnir"]["graph_lua_name"] == "/conf/lua/graph.lua"
        assert config["additional_data"]["elevation"] == "/data/elevation"


def test_validation_failure_leaves_live_untouched(workspace, states) -> None:
    """Everything before the swap writes only to staging and the dated tile
    directory, so a failed rebuild must leave the served schema - segments and
    crossings both - the served tiles and the settings table exactly as they
    were. The crossings assertion is the one that would have caught the live
    table being rewritten at stage seven."""
    from core.models import ValhallaUpstream

    live = settings.SEGMENT_SCHEMA_LIVE
    source, root = workspace
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {live}.segment "
            "(osm_way_id, ordinal, geometry, stress_tier, stress_rule) VALUES "
            "(999, 0, ST_GeomFromText('LINESTRING(-77 38.9,-77.01 38.91)',4326), 2, 'old')"
        )
        cursor.execute(
            f"INSERT INTO {live}.border_crossing "
            "(node_id, location, osm_way_id, state_a, state_b) VALUES "
            "(4242, ST_SetSRID(ST_MakePoint(-77, 38.9), 4326), 999, 'DC', 'MD')"
        )
    ValhallaUpstream.objects.create(variant="standard", url="http://old:8002", build_id="old")
    current = root / "tiles" / "standard" / "current"
    current.parent.mkdir(parents=True)
    os.symlink("old", current)

    with pytest.raises(RebuildFailed):
        run_pipeline(source, root, binaries=FakeBinaries(grade=0.0))

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id FROM {live}.segment")
        assert cursor.fetchall() == [(999,)]
        cursor.execute(f"SELECT node_id, osm_way_id FROM {live}.border_crossing")
        assert cursor.fetchall() == [(4242, 999)], "the served graph's crossings must survive"
    assert os.readlink(current) == "old", "the served tiles must survive"
    assert ValhallaUpstream.objects.get(variant="standard").build_id == "old"


def test_the_disk_gate_refuses_before_anything_is_written(workspace, states) -> None:
    """A rebuild that cannot fit a second full tile set refuses to start rather
    than filling the volume partway through. Nothing is reset or written first:
    last week's staging rows are still there afterwards."""
    from rebuild_fixtures import GIB

    from pipeline.tiles import DiskGateRefused

    staging = settings.SEGMENT_SCHEMA_STAGING
    source, root = workspace
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {staging}.segment "
            "(osm_way_id, ordinal, geometry, stress_tier, stress_rule) VALUES "
            "(777, 0, ST_GeomFromText('LINESTRING(-77 38.9,-77.01 38.91)',4326), 2, 'old')"
        )

    def nearly_full(path):
        import shutil

        return shutil._ntuple_diskusage(total=200 * GIB, used=170 * GIB, free=30 * GIB)

    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, disk_usage=nearly_full)
    assert caught.value.stage is Stage.FETCH_EXTRACT
    assert isinstance(caught.value.cause, DiskGateRefused)
    assert "80%" in str(caught.value.cause)
    assert count(staging) == 1, "the gate runs before the staging schema is reset"


def test_elevation_tiles_land_where_the_configs_say_the_build_reads(workspace, states) -> None:
    """The stage writes HGT tiles into the elevation directory, in the reader's
    band layout, for every one-degree cell the coverage box touches. And that
    directory is the one the generated configs name, through the rebuild
    container's mount: settings derive it from DATA_ROOT, the container mounts
    DATA_ROOT at /data, and the config says /data/elevation."""
    import yaml

    from pipeline.elevation import tiles_covering

    source, root = workspace
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    expected = {root / "elevation" / t.path() for t in tiles_covering(*context.coverage_bbox)}
    assert expected, "the coverage box must touch at least one tile"
    assert set(context.elevation_tiles) == expected
    for tile in expected:
        assert tile.stat().st_size == 1201 * 1201 * 2, "a valid HGT grid, not a short file"
    assert (root / "elevation" / "N38" / "N38W078.hgt") in expected, "the District's own cell"

    configured = json.loads((REPO / "valhalla" / "valhalla-standard.json").read_text())
    container_path = configured["additional_data"]["elevation"]
    compose = yaml.safe_load((REPO / "compose.yaml").read_text())
    mounts = dict(m.split(":")[1::-1] for m in compose["services"]["rebuild"]["volumes"])
    host_root = mounts["/data"]
    assert host_root == "${DATA_ROOT}", "the rebuild mounts the whole data volume at /data"
    assert container_path.startswith("/data/")
    on_host = Path(host_root) / container_path[len("/data/") :]
    assert on_host == Path("${DATA_ROOT}") / settings.ELEVATION_DIR.relative_to(settings.DATA_ROOT)


# --- The swap and what follows it --------------------------------------------------


def test_the_full_rebuild_swaps_and_reconciles(workspace, states) -> None:
    """The production call shape, every stage: build, validate, promote the
    tiles, repoint the settings table, rename the schema, report drift."""
    from core.models import BorderCrossing, DriftReport, Segment, ValhallaUpstream

    live = settings.SEGMENT_SCHEMA_LIVE
    source, root = workspace
    context, report = run_pipeline(source, root, build_id="20260917T080000Z")

    assert report.succeeded
    assert report.completed == list(Stage)

    # The schema, through the ORM: the unmanaged models resolve through the
    # search path to what was just promoted.
    assert count(live) == 5 and Segment.objects.count() == 5
    assert count(live, "border_crossing") == 1 and BorderCrossing.objects.count() == 1
    assert count(settings.SEGMENT_SCHEMA_RETIRED) == 0, "the empty first live was retired"

    # The tiles: each variant's `current` points at this build's dated directory,
    # and that directory holds the extract the serving config names.
    for variant in Variant:
        current = root / "tiles" / variant.value / "current"
        assert os.readlink(current) == "20260917T080000Z"
        assert (current / "tiles.tar").is_file()
        assert not (root / "tiles" / variant.value / "previous").exists(), "nothing to retire"

    # The settings table the API watches: one row per variant, at the compose
    # service's URL, naming the build now served.
    rows = {row.variant: row for row in ValhallaUpstream.objects.all()}
    assert set(rows) == {"standard", "no-trail", "ebike"}
    for variant, row in rows.items():
        assert row.build_id == "20260917T080000Z"
        assert row.url == settings.VALHALLA_UPSTREAMS[variant]
        assert row.previous_build_id == ""

    # The drift report, against the retired schema.
    drift = DriftReport.objects.get()
    assert drift.build_id == "20260917T080000Z"
    assert (drift.segments_before, drift.segments_after) == (0, 5)
    assert (drift.segments_lost, drift.segments_added, drift.segments_regraded) == (0, 5, 0)
    assert drift.unresolved_anchors is None, "anchors are phase 2; zero would be a claim"


def test_the_second_rebuild_retires_the_first_and_reports_what_changed(workspace, states) -> None:
    """Next week's map has lost the farm track and re-signed the road. The
    drift report says so, the retired schema is last week's, `previous` is
    last week's tiles, and the settings row remembers the build it replaced."""
    from core.models import DriftReport, ValhallaUpstream

    source, root = workspace
    run_pipeline(source, root, build_id="20260910T080000Z")
    build_toy_extract(source, changed=True)
    context, report = run_pipeline(source, root, build_id="20260917T080000Z")

    assert report.succeeded
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 4
    assert count(settings.SEGMENT_SCHEMA_RETIRED) == 5

    drift = DriftReport.objects.get(build_id="20260917T080000Z")
    assert (drift.segments_before, drift.segments_after) == (5, 4)
    assert drift.segments_lost == 1, "the farm track"
    assert drift.segments_added == 0
    assert drift.segments_regraded == 1, "the road, 35 mph secondary to 20 mph residential"
    assert (drift.crossings_before, drift.crossings_after) == (1, 1)

    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260917T080000Z"
        assert os.readlink(variant_dir / "previous") == "20260910T080000Z"
        assert (variant_dir / "20260910T080000Z" / "tiles.tar").is_file(), "kept for rollback"
    row = ValhallaUpstream.objects.get(variant="standard")
    assert (row.build_id, row.previous_build_id) == ("20260917T080000Z", "20260910T080000Z")


def test_a_swap_that_fails_after_promoting_undoes_the_promotion(
    workspace, states, monkeypatch
) -> None:
    """The order is tiles, settings table, schema. If the rename fails, the
    first two are undone before the error leaves, because a deployment whose
    settings table names a build its schema does not describe is the one state
    the swap must never leave behind."""
    from core.models import ValhallaUpstream
    from pipeline import promotion
    from pipeline.swap import SwapLockTimeout

    source, root = workspace
    run_pipeline(source, root, build_id="20260910T080000Z")

    def rename_refused(*args, **kwargs):
        raise SwapLockTimeout("could not take the swap lock in 5 attempts")

    monkeypatch.setattr(promotion, "swap_schemas", rename_refused)
    build_toy_extract(source, changed=True)
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, build_id="20260917T080000Z")
    assert caught.value.stage is Stage.SWAP

    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5, "last week's graph is still served"
    for variant in Variant:
        assert os.readlink(root / "tiles" / variant.value / "current") == "20260910T080000Z"
    row = ValhallaUpstream.objects.get(variant="standard")
    assert row.build_id == "20260910T080000Z"


def test_rollback_puts_the_previous_build_back_everywhere(workspace, states) -> None:
    """The operator's undo: schema, tiles and settings table, together."""
    from core.models import ValhallaUpstream
    from pipeline.promotion import rollback

    source, root = workspace
    run_pipeline(source, root, build_id="20260910T080000Z")
    build_toy_extract(source, changed=True)
    run_pipeline(source, root, build_id="20260917T080000Z")
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 4

    rollback(root / "tiles")

    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5
    for variant in Variant:
        assert os.readlink(root / "tiles" / variant.value / "current") == "20260910T080000Z"
    assert ValhallaUpstream.objects.get(variant="ebike").build_id == "20260910T080000Z"


@pytest.fixture
def renamed_schemas(monkeypatch):
    """A deployment whose schema names come from the environment."""
    from pipeline.schema import create_segment_schema, drop_segment_schema

    names = ("live_x", "staging_x", "live_x_old", "live", "staging", "live_old")
    monkeypatch.setattr(settings, "SEGMENT_SCHEMA_LIVE", "live_x")
    monkeypatch.setattr(settings, "SEGMENT_SCHEMA_STAGING", "staging_x")
    monkeypatch.setattr(settings, "SEGMENT_SCHEMA_RETIRED", "live_x_old")
    for name in names:
        drop_segment_schema(name)
    create_segment_schema("live_x")
    create_segment_schema("staging_x")
    yield
    for name in names:
        drop_segment_schema(name)


def test_the_rebuild_writes_to_the_configured_staging_schema(renamed_schemas, states) -> None:
    """With ROUTEMAKER_*_SCHEMA set, the rebuild wrote its rows into a literal
    "staging" while the swap promoted settings.SEGMENT_SCHEMA_STAGING - an
    empty schema - so the live table was silently emptied. Every schema name
    the rebuild uses has to be the configured one."""
    from pipeline.schema import schema_exists

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.osm.pbf"
        build_toy_extract(source)
        context, report = run_pipeline(source, root)

    assert report.succeeded
    assert context.staging_schema == "staging_x"
    assert count("live_x") == 5, "the promoted schema carries this build's rows"
    assert count("live_x", "border_crossing") == 1
    assert not schema_exists("staging"), "nothing touched the literal name"
    assert not schema_exists("live")


# --- The handler set itself ----------------------------------------------------------


def test_the_production_handler_set_covers_every_stage(tmp_path) -> None:
    """The weekly task calls build_handlers(context) with nothing injected.
    That shape once returned eleven handlers for thirteen stages, so the job
    raised StageNotImplemented on every fire - after building the tiles."""
    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
    )
    handlers = build_handlers(context)
    assert set(handlers) | frozenset() == set(Stage)


def test_a_rebuild_without_reference_data_refuses_to_run(workspace, states) -> None:
    """Every one of these inputs had an empty default, so the rebuild ran to
    completion and produced a plausible wrong map: the District graded against
    rural speeds, no volume anywhere, the e-bike variant a copy of standard.
    Nothing raised. Failing here is the point."""
    source, root = workspace
    context = RebuildContext(
        source_pbf=source,
        work_dir=root / "work",
        reference_dir=root / "absent",
        tiles_dir=root / "tiles",
        elevation_dir=root / "elevation",
    )
    handlers = build_handlers(
        context, run=FakeBinaries(), fetch_elevation=fake_fetch, disk_usage=roomy_disk
    )
    with pytest.raises(RebuildFailed) as caught:
        run_rebuild(handlers)
    assert caught.value.stage is Stage.LOAD_REFERENCE_DATA


def test_a_missing_handler_is_refused_before_any_stage_runs() -> None:
    """Silently continuing made an omitted stage indistinguishable from a
    deliberate one. Raising when the gap is reached was better and still not
    right: the gap was the swap, after hours of building."""
    from pipeline.rebuild import StageNotImplemented

    ran: list[Stage] = []
    with pytest.raises(StageNotImplemented, match="swap"):
        run_rebuild({Stage.FETCH_EXTRACT: lambda: ran.append(Stage.FETCH_EXTRACT)})
    assert ran == [], "nothing runs until every stage is accounted for"
