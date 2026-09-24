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
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

import osmium
import pytest
from django.conf import settings
from django.db import connection
from rebuild_fixtures import (
    GIB,
    LUA_LOADED_LOG,
    PARALLEL_COUNT,
    REPO,
    FakeBinaries,
    box,
    build_named_bridge_extract,
    build_parallel_extract,
    build_toy_extract,
    fake_fetch,
    install_source_extract,
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
    """A deployment that already has this week's extract on disk.

    Both files, under the names FETCH_EXTRACT produces them under, so the
    freshness rule reuses them: these tests are about the stages after the
    extract, and the ones about the extract itself start from an empty
    directory.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        yield install_source_extract(root), root


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
    legality=(),
    crossings=(),
    skip: frozenset[Stage] = frozenset(),
    build_id: str | None = None,
    disk_usage=roomy_disk,
):
    """The weekly task's call, with the binaries stood in for."""
    reference = write_reference_data(
        root,
        urban=urban,
        sidepath=sidepath,
        volume=volume,
        legality=legality,
        crossings=crossings,
    )
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


# --- The source extract ---------------------------------------------------------


@pytest.fixture
def fresh_deployment(segment_schemas):
    """A box that has never run a rebuild: a data root with no extract in it.

    Which is the state the first rebuild used to fail in. FETCH_EXTRACT checked
    that `<DATA_ROOT>/extracts/source.osm.pbf` existed, nothing anywhere made
    that file, and no document said how to; the rebuild stopped at stage one
    with ReferenceDataMissing and the deployment could not proceed at all.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        yield root / "extracts" / "source.osm.pbf", root


def test_a_first_rebuild_downloads_merges_and_clips_its_own_extract(
    fresh_deployment, states
) -> None:
    """The whole of B-1, through the real stage: three Geofabrik downloads, one
    merge, one clip, both files kept, and the rebuild carries on to populate
    staging from what it produced."""
    source, root = fresh_deployment
    binaries = FakeBinaries()
    context, report = run_pipeline(source, root, binaries=binaries, skip=NOT_SWAPPED)

    assert report.completed, "the rebuild ran rather than stopping at stage one"
    downloads = binaries.commands("curl")
    assert [c[-1] for c in downloads] == [
        "https://download.geofabrik.de/north-america/us/district-of-columbia-latest.osm.pbf",
        "https://download.geofabrik.de/north-america/us/maryland-latest.osm.pbf",
        "https://download.geofabrik.de/north-america/us/virginia-latest.osm.pbf",
    ]
    osmium = binaries.commands("osmium")
    assert [c[1] for c in osmium] == ["merge", "extract"], "merged, then clipped"
    assert osmium[1][osmium[1].index("-s") + 1 : osmium[1].index("-s") + 4] == [
        "smart",
        "-S",
        "types=any",
    ], "PLAN:13's strategy, so boundary relations survive the clip"

    merged = root / "extracts" / "merged.osm.pbf"
    assert merged.is_file(), "the file valhalla_build_admins reads is kept"
    assert source.is_file(), "and the clip the rest of the rebuild reads"
    assert not list((root / "extracts").glob("*.part")), "nothing partial is left behind"
    assert count(settings.SEGMENT_SCHEMA_STAGING) == 5, "the extract it produced is the one it read"

    # The admin database is built from the merged file, which is the half of
    # PLAN:13 that was being read backwards: the clipped extract was handed to
    # valhalla_build_admins with a comment citing the plan as endorsing it.
    admins = binaries.commands("valhalla_build_admins")
    assert {c[-1] for c in admins} == {str(merged)}
    assert str(source) not in {c[-1] for c in admins}


def test_an_extract_from_earlier_in_the_week_is_not_downloaded_again(workspace, states) -> None:
    """1-2 GB per rebuild, and a rebuild is retried. The freshness rule is what
    makes a second run in the same week start at the tile build's speed rather
    than the network's."""
    source, root = workspace
    binaries = FakeBinaries()
    run_pipeline(source, root, binaries=binaries, skip=NOT_SWAPPED)

    assert binaries.commands("curl") == [], "a fresh extract is reused"
    assert binaries.commands("osmium") == []


def test_an_extract_older_than_the_limit_is_rebuilt(workspace, states) -> None:
    """The other half of the same rule, and the one that decides whether the
    weekly refresh refreshes anything: with no age check every rebuild after the
    first re-derived the whole map from one frozen snapshot."""
    source, root = workspace
    eight_days_ago = time.time() - 8 * 24 * 3600
    for name in ("source.osm.pbf", "merged.osm.pbf"):
        os.utime(root / name, (eight_days_ago, eight_days_ago))

    binaries = FakeBinaries()
    run_pipeline(source, root, binaries=binaries, skip=NOT_SWAPPED)

    assert len(binaries.commands("curl")) == 3, "the three states again"
    assert source.stat().st_mtime > eight_days_ago, "and this week's clip replaced it"


def test_a_partial_download_left_behind_is_never_read_as_the_extract(
    fresh_deployment, states
) -> None:
    """A killed container leaves a `.part` holding an unknown amount of a real
    extract. Nothing downstream can tell a truncated PBF from a small region -
    osmium reads what is there - so it is neither renamed into place nor
    resumed."""
    source, root = fresh_deployment
    (root / "extracts").mkdir(parents=True)
    partials = {
        root / "extracts" / "source.osm.pbf.part": b"half of last week's clip",
        root / "extracts" / "district-of-columbia-latest.osm.pbf.part": b"half of the District",
    }
    for path, content in partials.items():
        path.write_bytes(content)

    binaries = FakeBinaries()
    run_pipeline(source, root, binaries=binaries, skip=NOT_SWAPPED)

    assert len(binaries.commands("curl")) == 3, "the partial file is not a download"
    for path in partials:
        assert not path.exists(), f"{path.name} was left behind"
    assert source.read_bytes() != partials[root / "extracts" / "source.osm.pbf.part"]
    assert count(settings.SEGMENT_SCHEMA_STAGING) == 5, "a readable extract was built"


def test_the_disk_gate_refuses_before_the_extract_is_downloaded(fresh_deployment, states) -> None:
    """The gate runs before the download, not after it.

    The extract is the largest thing this rebuild puts on the data volume - the
    three state files, the merge, then the clip, all under <DATA_ROOT>/extracts,
    which is the volume the gate measures - so a gate that ran once the extract
    was on disk would be a gate on a volume the rebuild had already filled.
    With no extract to measure it is sized from `source.ESTIMATED_BYTES`.
    """
    from pipeline.tiles import DiskGateRefused

    source, root = fresh_deployment

    def nearly_full(path):
        return shutil._ntuple_diskusage(total=200 * GIB, used=170 * GIB, free=30 * GIB)

    binaries = FakeBinaries()
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=binaries, disk_usage=nearly_full)

    assert caught.value.stage is Stage.FETCH_EXTRACT
    assert isinstance(caught.value.cause, DiskGateRefused)
    assert binaries.commands("curl") == [], "nothing was downloaded onto a full volume"
    assert not (root / "extracts").exists() or not list((root / "extracts").iterdir())


def test_a_deployment_configured_for_an_extract_nothing_writes_is_refused(
    fresh_deployment, states
) -> None:
    """The stage produces `source.osm.pbf` beside the merged file, under that
    name. A REBUILD_SOURCE_PBF naming anything else is a deployment reading a
    file no stage writes, which is the failure this check still exists for -
    and it says what was produced instead rather than only what is missing."""
    _source, root = fresh_deployment
    elsewhere = root / "extracts" / "last-years.osm.pbf"

    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(elsewhere, root, skip=NOT_SWAPPED)

    assert caught.value.stage is Stage.FETCH_EXTRACT
    assert "source extract missing" in str(caught.value.cause)
    assert "source.osm.pbf" in str(caught.value.cause), "it names what was produced"


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
    # `>= 3` was exactly weak enough to let the classifier's 35 -> 45 mph
    # boundary mutation through: 35 mph is the LTS3/LTS4 boundary and the most
    # common arterial posting in the region, and a tier-3 reading here would be
    # the boundary having moved. Beginner's "zero top-tier distance" invariant
    # and the road-exposure report both key on LTS4, so the difference between
    # 3 and 4 is the difference between routing a beginner onto this road and
    # not.
    assert tiers[100] == 4, "a 35 mph secondary with no facility is top-tier stress"


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
    a tier that did not exist yet and the graph carried no stress at all.

    The value is asserted, not its presence. `rm:stress_tier` is what
    `lua/graph.lua` turns into the cycleway write and what every preset's
    use_roads dial is reasoned against, so a tier that is merely *there* is not
    the check: writing a constant 1 onto every way - the whole District read as
    a quiet residential street - left the earlier version of this test green.
    35 mph secondary with no facility is LTS4, and the difference between 3 and
    4 is the difference between routing a beginner onto this road and not.

    Checked on all three variant extracts, because each is written from its own
    per-way tag set and the tiles are built from all three.
    """
    from pipeline.extract import read_ways

    source, root = workspace
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    # The classifier's own answer for each way, from the run that just happened.
    expected = {way_id: str(int(stress.tier)) for way_id, stress in context.stress_by_way.items()}
    assert expected[100] == "4", "a 35 mph secondary with no facility is top-tier stress"
    assert expected[200] == "1", "and a trail is lowest"

    for variant in Variant:
        tags = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(variant))}
        for way_id, tier in sorted(expected.items()):
            if way_id not in tags:
                continue  # dropped from this variant; test_the_no_trail_... covers that
            assert tags[way_id].get("rm:stress_tier") == tier, (
                f"{variant.value}: way {way_id} carries "
                f"{tags[way_id].get('rm:stress_tier')!r}, not the classifier's {tier!r}"
            )
        assert len(set(tags[w].get("rm:stress_tier") for w in tags)) > 1, (
            f"{variant.value}: every way carries the same tier, which is not a classification"
        )

    tags = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(Variant.STANDARD))}
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
            "agency": "vdot",
            "year": 2025,
        }
    ]
    context, _ = run_pipeline(source, root, volume=volume, skip=NOT_SWAPPED)
    match = context.aadt_by_way.get(100)
    assert match is not None
    assert (match.aadt, match.source, match.agency, match.year) == (900, "state", "vdot", 2025)
    # The agency, not the precedence tier: "state" is how `conflate` ranked this
    # count against a locality's, and it is not who published it.
    assert context.stress_by_way[100].volume_source == "vdot"
    assert context.stress_by_way[100].volume_aadt == 900
    assert context.stress_by_way[100].volume_year == 2025


def test_the_agency_and_year_of_a_count_reach_the_segment_table(workspace, states) -> None:
    """Read back out of the staging schema, which is the published artefact.

    `volume_source` held the precedence *tier* - "locality" or "state" - which
    is the vocabulary `conflate` ranks two counts with and says nothing about
    who published the winner. So every state layer wrote the same string and a
    Maryland iMAP count was indistinguishable from a VDOT one in the only table
    the derivative is built from, while `write_segments` and `StressResult` both
    claimed the derivative could tell which segments a conditionally licensed
    source had touched. `Match.year` was dropped at the same assignment and the
    table had no column for the count either.

    Two agencies at two different tiers here, and a third agency at the *same*
    tier as one of them further down, because a column that merely happened to
    differ between a locality and a state would pass a one-agency test while
    still collapsing MDOT SHA onto VDOT.
    """
    source, root = workspace
    staging = settings.SEGMENT_SCHEMA_STAGING
    volume = [
        {
            "id": "ddot-1",
            "coordinates": [[-77.02, 38.90], [-76.98, 38.90]],
            "aadt": 9100,
            "source": "locality",
            "agency": "ddot",
            "year": 2024,
        },
        {
            "id": "mdot-sha-1",
            "coordinates": [[-77.045, 38.92], [-77.035, 38.92]],
            "aadt": 3300,
            "source": "state",
            "agency": "mdot-sha",
            "year": 2019,
        },
    ]
    run_pipeline(source, root, volume=volume, skip=NOT_SWAPPED)

    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT osm_way_id, volume_source, volume_aadt, volume_year
                FROM {staging}.segment WHERE volume_source IS NOT NULL
                ORDER BY osm_way_id"""
        )
        counted = cursor.fetchall()

    by_agency = {row[1]: row for row in counted}
    assert set(by_agency) == {"ddot", "mdot-sha"}, "the agency, not its precedence tier"
    assert by_agency["ddot"][0] == 100
    assert by_agency["ddot"][2:] == (9100, 2024)
    assert by_agency["mdot-sha"][2:] == (3300, 2019)
    # And nothing wrote a tier into the column the agency belongs in.
    assert not {"locality", "state", "osm"} & set(by_agency)


def test_two_agencies_at_one_precedence_tier_stay_distinguishable(workspace, states) -> None:
    """The half a locality-versus-state case cannot reach. VDOT and MDOT SHA
    both rank at "state" - that is what the tier is for - so a segment table
    that recorded the tier lost the distinction PLAN:31-34 is about: Maryland's
    iMAP layer is conditionally licensed and Virginia's is not, and the
    published derivative has to be able to name the segments one of them
    influenced. Same tier, different agency, different row."""
    source, root = workspace
    staging = settings.SEGMENT_SCHEMA_STAGING
    volume = [
        {
            "id": "vdot-1",
            "coordinates": [[-77.02, 38.90], [-76.98, 38.90]],
            "aadt": 9100,
            "source": "state",
            "agency": "vdot",
            "year": 2024,
        },
        {
            "id": "mdot-sha-1",
            "coordinates": [[-77.045, 38.92], [-77.035, 38.92]],
            "aadt": 3300,
            "source": "state",
            "agency": "mdot-sha",
            "year": 2019,
        },
    ]
    run_pipeline(source, root, volume=volume, skip=NOT_SWAPPED)

    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT DISTINCT volume_source FROM {staging}.segment WHERE volume_source IS NOT NULL"
        )
        agencies = {row[0] for row in cursor.fetchall()}

    assert agencies == {"vdot", "mdot-sha"}


@pytest.mark.parametrize(
    ("road_id", "trail_id"),
    [(100, 200), (200, 100)],
    ids=["road-first", "trail-first"],
)
def test_a_trail_alongside_a_road_cannot_take_the_roads_count(
    tmp_path, segment_schemas, states, road_id, trail_id
) -> None:
    """Through the real `conflate_volume` handler, not `conflate()`.

    A motor-vehicle AADT is not an attribute of a shared-use path. With the
    Mount Vernon Trail 15 m from the GW Parkway - well inside
    `MAX_SEPARATION_M` - a trail left in the candidate set out-ranks the
    roadway whenever the survey line is drawn nearer the path than the
    centreline, and exclusivity then denies the count to the roadway too. So
    the count reaches neither way and the arterial is classified as if it were
    uncounted.

    `conflation.conflate` grew the trail-class flag and defaults it to False,
    so the fix was inert until this handler passed it. Asserted in both input
    orders because the ordering was the tie-break the previous defect turned
    on.
    """
    source = install_source_extract(
        tmp_path, build_parallel_extract, road_id=road_id, trail_id=trail_id
    )
    context, _ = run_pipeline(
        source,
        tmp_path,
        urban=(road_id, trail_id),
        volume=[{**PARALLEL_COUNT, "agency": "vdot"}],
        skip=NOT_SWAPPED,
    )

    matched = context.aadt_by_way.get(road_id)
    assert matched is not None and matched.aadt == 24000, "the count belongs to the road"
    assert trail_id not in context.aadt_by_way, "a path carries no motor traffic"
    assert context.stress_by_way[road_id].volume_source == "vdot"


def test_a_bridge_barred_to_bicycles_is_tagged_so_on_every_variant(workspace, states) -> None:
    """`resolve_bridge_bicycle_legality` existed and nothing called it, so the
    tag `graph.lua` reads (`derived.bridge_bicycle_legal`) was emitted by no
    stage at all and the remap's bicycle=no branch was unreachable in
    production.

    On every variant, because whether OSM's `bicycle` tag bars a bridge's
    roadway outright is a legal fact rather than a request-time dial. Read back
    from the written PBF, which is the only thing the tile build ever sees.
    """
    from pipeline.extract import read_ways

    source, root = workspace
    # Way 500 is the trunk bridge; way 100 the road the fixture says is legal.
    context, _ = run_pipeline(source, root, legality={500: False, 100: True}, skip=NOT_SWAPPED)

    for variant in Variant:
        tags = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(variant))}
        assert tags[500].get("rm:bridge_bicycle") == "no", variant.value
        assert tags[100].get("rm:bridge_bicycle") == "yes", variant.value
        assert "rm:bridge_bicycle" not in tags[300], "no opinion means no claim"


def test_the_shared_use_path_on_a_bridge_is_not_barred_by_the_roadways_row(
    tmp_path, segment_schemas, states
) -> None:
    """The crossings fixture's legality column describes the *roadway*, and
    nothing stopped it matching the path.

    A shared-use path on a bridge is mapped as a `highway=cycleway` way tagged
    `bridge=yes` and named after the structure - that is the ordinary OSM shape,
    and it is what the Woodrow Wilson path, the 14th Street path and the Key
    Bridge sidewalk all look like. `resolve_bridge_bicycle_legality` matched by
    name over any bridge-tagged way, so the path resolved False, `inject_tags`
    emitted `rm:bridge_bicycle=no` on it on every variant, and
    `routemaker_remap` turns that into `bicycle=no`: the only bicycle crossing
    of the Potomac at that point, deleted from all three graphs by a column that
    says nothing about it.

    Driven through the real pipeline and read back from the written PBF, which
    is the only thing the tile build ever sees.
    """
    from pipeline.extract import read_ways

    source = install_source_extract(
        tmp_path,
        build_named_bridge_extract,
        roadway_id=700,
        sidepath_id=701,
        name="Woodrow Wilson Memorial Bridge",
    )
    row = {
        "name": "Woodrow Wilson Bridge path",
        "osm_way_id": 0,
        "osm_names": ["Woodrow Wilson Memorial Bridge"],
        "roadway_bicycle_legal": False,
        "sidepath_only": True,
    }
    context, _ = run_pipeline(source, tmp_path, urban=(700, 701), crossings=[row], skip=NOT_SWAPPED)

    for variant in Variant:
        tags = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(variant))}
        if variant is Variant.NO_TRAIL:
            # Both ways are gone from this one, by the two separate rules that
            # each exist for it: the path because it is trail class, the roadway
            # because the row is `sidepath_only` and a mass ride cannot use it.
            assert 701 not in tags and 700 not in tags
            continue
        assert "rm:bridge_bicycle" not in tags[701], (
            f"the path was barred on the {variant.value} variant by the roadway's row"
        )
        # The roadway's own row still bites.
        assert tags[700].get("rm:bridge_bicycle") == "no", variant.value


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


class PerVariantLog(FakeBinaries):
    """A fake whose tile build logs the Lua line for one variant only.

    Which is the shape the joined-log check could not see: `.search` over the
    three variants' logs concatenated is satisfied by the first match, so two
    variants could have fallen back to Valhalla's compiled-in transform - and
    dropped every derived tag - with validation still passing.
    """

    def __init__(self, logged_for: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.logged_for = logged_for

    def __call__(self, command):
        command = list(command)
        if Path(command[0]).name == "valhalla_build_tiles":
            config = json.loads(Path(command[2]).read_text())
            variant = Path(config["mjolnir"]["tile_dir"]).parents[1].name
            self.log = LUA_LOADED_LOG if variant == self.logged_for else "tiles built, 0 errors"
        return super().__call__(command)


def test_a_variant_that_fell_back_is_caught_even_when_another_logged_the_script(
    workspace, states
) -> None:
    """Every variant is checked against its own build log."""
    source, root = workspace
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=PerVariantLog(logged_for="standard"), build_id="one")
    assert caught.value.stage is Stage.VALIDATE
    assert "built-in transform" in str(caught.value.cause)
    # And the message says which variant, since two of the three are fine.
    assert "no-trail" in str(caught.value.cause) or "ebike" in str(caught.value.cause)

    # The same fake with every variant logging the line passes, so the failure
    # above is the per-variant check and not the fake.
    run_pipeline(source, root, binaries=FakeBinaries(), skip=NOT_SWAPPED, build_id="all")


class PerVariantGrade(FakeBinaries):
    """A fake whose tiles report a real grade for every variant but one.

    The shape a "did elevation reach the tiles" check that took the *largest*
    grade across the variants could not see. Each variant is built by its own
    `valhalla_build_tiles` run against its own config, and the elevation
    directory is read per build, so one variant built without it is one graph
    where `use_hills` is inert, Mass Ride's grade cap has no max_grade to read
    and the Recovery and Mountain Goat invariants tie at zero - while the other
    two report 5.5 percent on the same edge and the answer looks fine.
    """

    def __init__(self, zero_for: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.zero_for = zero_for
        self.built_grade = self.grade

    def __call__(self, command):
        command = list(command)
        if Path(command[0]).name == "valhalla_service":
            config = json.loads(Path(command[1]).read_text())
            variant = Path(config["mjolnir"]["tile_dir"]).parents[1].name
            self.grade = 0.0 if variant == self.zero_for else self.built_grade
        return super().__call__(command)


def test_a_variant_built_without_elevation_is_caught_even_when_the_others_have_it(
    workspace, states
) -> None:
    """Every variant's build has to have baked elevation, so the check is the
    smallest grade any of them reports on the known steep edge rather than the
    largest. With the largest, two variants could have been built with no
    elevation directory at all and validation would still have passed on the
    third one's answer."""
    source, root = workspace
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=PerVariantGrade(zero_for="ebike"), build_id="flat")
    assert caught.value.stage is Stage.VALIDATE
    assert "elevation directory" in str(caught.value.cause)

    # The same fake with every variant reporting a grade passes, so the failure
    # above is the per-variant check and not the fake.
    run_pipeline(source, root, binaries=FakeBinaries(), skip=NOT_SWAPPED, build_id="hilly")


def test_a_transform_rule_violation_in_the_parse_log_fails_the_build(workspace, states) -> None:
    """`lua/routemaker_remap.lua` and `lua/graph.lua` both say this stage greps
    the parse log for ROUTEMAKER-VIOLATION, and until now nothing did.

    The transform cannot refuse an element - lua_pcall failure returns an empty
    tag map, which deletes it - so a violated rule is a change dropped, a line
    on stderr, and a build that reports success. A graph built around a rule
    this project states it does not break was promoted with nobody told.
    """
    source, root = workspace
    violation = (
        "ROUTEMAKER-VIOLATION: the remap attempted to write 'highway', which is never permitted\n"
    )
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=FakeBinaries(violations=violation), build_id="bad")
    assert caught.value.stage is Stage.VALIDATE
    assert "ROUTEMAKER-VIOLATION" in str(caught.value.cause)
    assert "never permitted" in str(caught.value.cause), "the offending line is quoted"

    # Without the line the same rebuild passes, so the check is the violation
    # and not the stage.
    run_pipeline(source, root, binaries=FakeBinaries(), skip=NOT_SWAPPED, build_id="clean")


def test_the_violation_prefix_is_searched_on_the_streams_the_lua_writes_to(
    workspace, states
) -> None:
    """The remap writes its violations with `io.stderr:write`, while Valhalla's
    own lines go to stdout under `mjolnir.logging.type: std_out`. The build log
    has to be both streams or the check reads a log the violation is not in."""
    from pipeline.run import VIOLATION_LOG_PREFIX, assert_no_rule_violations
    from pipeline.tiles import CommandOutput

    assert VIOLATION_LOG_PREFIX == "ROUTEMAKER-VIOLATION"
    output = CommandOutput("Using LUA script: /conf/lua/graph.lua", f"{VIOLATION_LOG_PREFIX}: x")
    with pytest.raises(Exception, match=VIOLATION_LOG_PREFIX):
        assert_no_rule_violations(output.log, "standard")


def test_the_violation_report_says_and_more_only_when_there_is_more() -> None:
    """The boundary of the quote, which is the count that actually happens.

    A systematic violation writes one line per element and there is no sense
    putting a million in an exception, so five are quoted and the rest are
    counted. At exactly five there is no rest: `< REPORTED_VIOLATIONS` instead
    of `<=` appends "(and 0 more)" to a message that has already quoted every
    line there was, which sends an operator looking through a build log for
    lines that are all in front of them.
    """
    from pipeline.run import REPORTED_VIOLATIONS, VIOLATION_LOG_PREFIX, assert_no_rule_violations

    assert REPORTED_VIOLATIONS == 5

    def message_for(count: int) -> str:
        log = "\n".join(f"{VIOLATION_LOG_PREFIX}: way {n} wrote highway" for n in range(count))
        with pytest.raises(Exception) as caught:
            assert_no_rule_violations(log, "standard")
        return str(caught.value)

    exactly = message_for(REPORTED_VIOLATIONS)
    assert "more)" not in exactly, "every line is quoted, so there is nothing more to count"
    assert f"logged {REPORTED_VIOLATIONS} {VIOLATION_LOG_PREFIX} line(s)" in exactly
    assert "way 4 wrote highway" in exactly, "the fifth line is one of the quoted ones"

    assert "(and 1 more)" in message_for(REPORTED_VIOLATIONS + 1)
    assert "more)" not in message_for(REPORTED_VIOLATIONS - 1)


def test_a_build_that_leaves_no_admin_database_fails_the_build(workspace, states) -> None:
    """PLAN:13 commits to valhalla_build_admins and valhalla_build_timezones and
    nothing ran either. Both paths are retargeted into the dated build directory
    with every other tile path, and 3.5.1 warns and carries on without them
    (src/mjolnir/graphbuilder.cc:431-444), so the graph silently has no
    timezone and `date_time.type: 3` evaluates nothing."""
    source, root = workspace
    # Distinct build ids: the dated directory is named to the second, so two
    # rebuilds in the same second would share one and the second would find the
    # first's databases already sitting there.
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=FakeBinaries(admin="missing"), build_id="no-admin")
    assert caught.value.stage is Stage.VALIDATE
    assert "mjolnir.admin" in str(caught.value.cause)

    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=FakeBinaries(timezone="missing"), build_id="no-tz")
    assert "mjolnir.timezone" in str(caught.value.cause)


@pytest.mark.parametrize(
    ("kwargs", "named"),
    [
        ({"admin": "empty-file"}, "mjolnir.admin"),
        ({"timezone": "empty-file"}, "mjolnir.timezone"),
        ({"admin": "no-rows"}, "mjolnir.admin"),
        ({"timezone": "no-rows"}, "mjolnir.timezone"),
    ],
    ids=["admin-zero-bytes", "timezone-zero-bytes", "admin-no-admins", "timezone-no-tz-world"],
)
def test_a_database_that_is_there_but_holds_nothing_fails_the_build(
    workspace, states, kwargs, named
) -> None:
    """A file at the configured path is a weak claim, and both of these shapes
    read back as a graph with no admin or timezone information.

    Zero bytes is what `valhalla_build_timezones` leaves when the shell script
    the pipeline redirects dies partway: `>` has already created the file. An
    empty table is what an admin build over an extract carrying no boundary
    relations leaves - which is the direction building admins from the *clipped*
    extract tends in - a perfectly valid SQLite database with nothing in
    `admins`. So the check queries each database rather than weighing it.
    """
    source, root = workspace
    build_id = "-".join(f"{k}-{v}" for k, v in kwargs.items())
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=FakeBinaries(**kwargs), build_id=build_id)
    assert caught.value.stage is Stage.VALIDATE
    assert named in str(caught.value.cause)


def test_every_variant_gets_an_admin_and_a_timezone_database_where_its_config_says(
    workspace, states
) -> None:
    """And the timezone database is fetched once and copied, because it is a
    function of the world rather than of the extract."""
    source, root = workspace
    binaries = FakeBinaries()
    context, _ = run_pipeline(source, root, binaries=binaries, skip=NOT_SWAPPED)

    for variant, config_path in context.build_configs.items():
        config = json.loads(Path(config_path).read_text())
        for key in ("admin", "timezone"):
            path = Path(config["mjolnir"][key])
            assert path.is_file() and path.stat().st_size, f"{variant.value}: {key}"
            assert context.build_id in path.parts, (
                "written into the dated build, not the served one"
            )

    admins = binaries.commands("valhalla_build_admins")
    assert len(admins) == 1, (
        "the merged extract is parsed once per rebuild, not once per variant: the command's "
        "only inputs are the config and the merged PBF, so three runs wrote three identical "
        "databases"
    )
    # The merged extract, not the clipped one. PLAN:13 builds admin data from
    # the merged file before clipping, because the clip cuts boundary relations
    # at the coverage edge and an admin polygon with a false edge in it is a
    # country-crossing cost charged where no boundary is.
    merged = source.with_name("merged.osm.pbf")
    assert {c[-1] for c in admins} == {str(merged)}, "built from the merged extract"
    assert str(source) not in {c[-1] for c in admins}, "and not from the clipped one"

    downloads = [c for c in binaries.calls if c[0] == "sh"]
    copies = [c for c in binaries.calls if c[0] == "cp"]
    assert len(downloads) == 1, "a hundred megabytes, fetched once"
    # Two variants copy the timezone database and two copy the admin one, and
    # each copy is from the first variant's build directory into its own - which
    # is what the per-variant file assertions above have already read back.
    assert len(copies) == 4

    def named(variant, key):
        return json.loads(Path(context.build_configs[variant]).read_text())["mjolnir"][key]

    first, *rest = list(context.build_configs)
    assert sorted(c[1:] for c in copies) == sorted(
        [named(first, key), named(variant, key)]
        for variant in rest
        for key in ("admin", "timezone")
    ), "each of the other two variants copies the first variant's two databases into its own"
    assert admins[0][2] == str(context.build_configs[first]), "and the first is the one that built"


def test_a_lit_value_upstream_reads_as_lit_survives_the_whole_pipeline(workspace, states) -> None:
    """`lit=24/7` is a lit street. The derivation was `tags["lit"] == "yes"`,
    which called it - and `automatic`, `dusk-dawn` and `sunset-sunrise` - unlit,
    and then wrote `lit=no` over the way's own tag, so the graph disagreed with
    OSM in the one direction the "Prefer lit streets" preference reads.

    Checked where it takes effect, on both sides: the tag through the real
    transform under LuaJIT, which is the interpreter valhalla_build_tiles links
    against, and the segment column the preference reads.
    """
    from test_lua_remap import _lua_driver

    from pipeline.extract import read_ways

    source, root = workspace
    staging = settings.SEGMENT_SCHEMA_STAGING
    context, _ = run_pipeline(source, root, skip=NOT_SWAPPED)

    tags = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(Variant.STANDARD))}
    assert tags[100]["lit"] == "24/7", "the source tag is left alone"
    assert tags[100]["rm:lit"] == "yes"
    assert tags[200]["rm:lit"] == "no", "and `disused` is not lit"

    # Through lua/graph.lua and Valhalla's own transform, from the tags the
    # build would actually read out of this extract.
    entries = ", ".join(f"[{json.dumps(k)}] = {json.dumps(v)}" for k, v in tags[100].items())
    result = _lua_driver(
        'dofile("lua/graph.lua")\n'
        f"local kv = {{{entries}}}\n"
        f"local _, out = ways_proc(kv, {len(tags[100])})\n"
        'io.stdout:write(tostring(out.lit), "\\n")\n'
    )
    assert result.returncode == 0, result.stderr
    # Upstream's own `lit` table maps the value it is handed onto "true"/"false"
    # (lua/vendor/graph_upstream.lua:414-423, applied at :1480), and
    # src/mjolnir/pbfgraphparser.cc:1909 reads the result.
    assert result.stdout.strip() == "true"

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id, lit FROM {staging}.segment ORDER BY osm_way_id")
        lit = dict(cursor.fetchall())
    assert lit[100] is True, "the column the preference reads"
    assert lit[200] is False
    assert lit[300] is None, "an untagged way asserts nothing either way"


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


def test_the_disk_gate_refuses_on_free_space_a_huge_volume_makes_look_small(tmp_path) -> None:
    """Two clauses, and the percentage one alone is not a gate.

    A volume big enough makes any absolute shortfall disappear into the
    fraction: 2 GiB free on a 10 TiB filesystem is a build that cannot write
    its tiles, and `(used + required) / total` reads 1 percent. The free-space
    clause is what refuses it, and the fraction is what refuses the volume that
    has room today and would be at 90 percent tomorrow.
    """
    import shutil

    from rebuild_fixtures import GIB

    from pipeline.tiles import DiskGateRefused, check_disk_gate

    def huge_and_nearly_empty(path):
        return shutil._ntuple_diskusage(total=10_000 * GIB, used=100 * GIB, free=2 * GIB)

    with pytest.raises(DiskGateRefused) as refused:
        check_disk_gate(
            tmp_path / "tiles",
            source_bytes=0,
            minimum_free=8 * GIB,
            fraction=0.80,
            disk_usage=huge_and_nearly_empty,
        )
    assert "2.0 GiB free" in str(refused.value)
    assert "1%" in str(refused.value), "the fraction is nowhere near the gate"

    # And the same volume with the room it says it needs is allowed through.
    gate = check_disk_gate(
        tmp_path / "tiles",
        source_bytes=0,
        minimum_free=1 * GIB,
        fraction=0.80,
        disk_usage=huge_and_nearly_empty,
    )
    assert gate.required == 1 * GIB


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
        # The one grid skadi reads (sample.cc:27), not merely a plausible one:
        # a 1201-square tile passes this module's own writer and is then dropped
        # by the reader with a warning, which is a cell with no elevation.
        assert tile.stat().st_size == 3601 * 3601 * 2, "a valid HGT grid, not a short file"
    assert (root / "elevation" / "N38" / "N38W078.hgt") in expected, "the District's own cell"

    configured = json.loads((REPO / "valhalla" / "valhalla-standard.json").read_text())
    container_path = configured["additional_data"]["elevation"]
    compose = yaml.safe_load((REPO / "compose.yaml").read_text())
    mounts = dict(m.split(":")[1::-1] for m in compose["services"]["rebuild"]["volumes"])
    assert container_path.startswith("/data/")
    # The rebuild binds the five directories it writes rather than the whole
    # volume, so the mount that covers this path is the elevation one. Found by
    # longest prefix, which is how the container resolves it too.
    covering = max(
        (c for c in mounts if container_path == c or container_path.startswith(c + "/")),
        key=len,
        default=None,
    )
    assert covering, f"no mount in the rebuild container covers {container_path}: {mounts}"
    on_host = Path(mounts[covering] + container_path[len(covering) :])
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


def refusing_swap(*args, **kwargs):
    """`swap_schemas`, as it behaves when the rename cannot be made."""
    from pipeline.swap import SwapLockTimeout

    raise SwapLockTimeout("could not take the swap lock in 5 attempts")


def test_a_settings_write_that_fails_partway_repoints_no_row_at_all(
    workspace, states, monkeypatch
) -> None:
    """The repoint is one write per variant, and the third one failing used to
    leave the first two naming a build that nothing else in the deployment had
    promoted: no tile directory, no schema, and the rebuild's own error
    retryable, so the half-repoint repeated on every attempt. The rows are
    written in one transaction, and the undo has the before-state whether the
    repoint finished or not.
    """
    from core.models import ValhallaUpstream

    source, root = workspace
    run_pipeline(source, root, build_id="20260910T080000Z")

    real_save = ValhallaUpstream.save
    saves = 0

    def save_that_drops_on_the_third(self, *args, **kwargs):
        nonlocal saves
        saves += 1
        if saves == 3:
            raise RuntimeError("the connection dropped mid-repoint")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(ValhallaUpstream, "save", save_that_drops_on_the_third)
    build_toy_extract(source, changed=True)
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, build_id="20260917T080000Z")
    assert caught.value.stage is Stage.SWAP
    assert saves == 3, "the third variant's write is the one that failed"
    assert "the connection dropped mid-repoint" in str(caught.value.cause), (
        "the undo must report the failure it is undoing, not one of its own: with the "
        "before-state read only on the repoint's full success, the undo has nothing to "
        "work from and fails over the top of it"
    )

    rows = {row.variant: row for row in ValhallaUpstream.objects.all()}
    assert set(rows) == {"standard", "no-trail", "ebike"}
    for variant, row in rows.items():
        assert (row.build_id, row.previous_build_id) == ("20260910T080000Z", ""), variant
    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260910T080000Z"
        assert not (variant_dir / "previous").exists(), "the promotion was undone whole"
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5, "last week's graph is still served"


def test_a_repoint_that_dies_partway_leaves_no_row_half_written(
    workspace, states, monkeypatch
) -> None:
    """The transaction, on its own terms: a worker killed mid-repoint runs no
    undo at all.

    Procrastinate restarts a worker whose job died, and the rebuild's error is
    retryable, so the repoint is re-entered - against a settings table that
    nothing has repaired, because the process that would have repaired it is
    gone. Only the database can leave that table consistent, which is what
    writing every variant in one transaction is for. The undo is stubbed out
    here to stand in for the process not being there to run it.
    """
    from core.models import ValhallaUpstream
    from pipeline import promotion

    source, root = workspace
    run_pipeline(source, root, build_id="20260910T080000Z")

    real_save = ValhallaUpstream.save
    saves = 0

    def save_that_drops_on_the_third(self, *args, **kwargs):
        nonlocal saves
        saves += 1
        if saves == 3:
            raise RuntimeError("the worker was killed mid-repoint")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(ValhallaUpstream, "save", save_that_drops_on_the_third)
    monkeypatch.setattr(promotion, "restore_upstreams", lambda before: None)
    build_toy_extract(source, changed=True)
    with pytest.raises(RebuildFailed):
        run_pipeline(source, root, build_id="20260917T080000Z")

    for row in ValhallaUpstream.objects.all():
        assert (row.build_id, row.previous_build_id) == ("20260910T080000Z", ""), (
            f"{row.variant} names a build that no tile directory and no schema describes"
        )


def test_a_first_rebuild_whose_swap_fails_promotes_nothing(workspace, states, monkeypatch) -> None:
    """The undo on a first-ever rebuild, where there is no build to go back to.

    `demote` put `previous` back as `current`, and before the second rebuild
    ever runs there is no `previous` - so the undo did nothing at all and left
    `current` pointing at a build the schema swap never promoted, while the
    settings rows had been reset. The undo has to remove what the promotion
    created, not only move it back.
    """
    from core.models import ValhallaUpstream
    from pipeline import promotion

    source, root = workspace
    monkeypatch.setattr(promotion, "swap_schemas", refusing_swap)

    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, build_id="20260917T080000Z")
    assert caught.value.stage is Stage.SWAP

    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert not (variant_dir / "current").exists(), f"{variant.value} is serving a failed build"
        assert not (variant_dir / "current").is_symlink()
        assert not (variant_dir / "previous").exists()
        assert (variant_dir / "20260917T080000Z" / "tiles.tar").is_file(), "the build itself stays"
    assert ValhallaUpstream.objects.count() == 0, "no row was there before, so none is left"
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 0, "the empty live schema was not promoted over"


def test_an_undone_swap_leaves_the_row_naming_the_build_before_the_one_served(
    workspace, states, monkeypatch
) -> None:
    """The undo restores the whole row, not the build id alone.

    `restore_upstreams` wrote `previous_build_id=""` unconditionally, so after
    two good swaps and one undone one the row no longer named the build before
    the one it was serving - and that column is the only thing `rollback()`
    reads. Asserted by rolling back afterwards, which is what the column is
    for, and with the failed rebuild's staging schema still on the disk.
    """
    from core.models import ValhallaUpstream
    from pipeline import promotion
    from pipeline.promotion import rollback
    from pipeline.schema import schema_exists

    source, root = workspace
    run_pipeline(source, root, build_id="20260903T080000Z")
    build_toy_extract(source, changed=True)
    run_pipeline(source, root, build_id="20260910T080000Z")

    monkeypatch.setattr(promotion, "swap_schemas", refusing_swap)
    with pytest.raises(RebuildFailed):
        run_pipeline(source, root, build_id="20260917T080000Z")

    for row in ValhallaUpstream.objects.all():
        assert (row.build_id, row.previous_build_id) == (
            "20260910T080000Z",
            "20260903T080000Z",
        ), row.variant
        assert row.url == settings.VALHALLA_UPSTREAMS[row.variant]
    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260910T080000Z"
        assert os.readlink(variant_dir / "previous") == "20260903T080000Z"
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 4
    assert schema_exists(settings.SEGMENT_SCHEMA_STAGING), "the failed rebuild left its staging"

    # And the operator's rollback, which reads exactly what the undo restored,
    # works - over the staging schema the failed rebuild left behind, which the
    # rename needs the name of.
    rollback(root / "tiles")

    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5, "the build before the one served is back"
    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260903T080000Z"
        assert not (variant_dir / "previous").exists(), "there is nothing before it any more"
    row = ValhallaUpstream.objects.get(variant="ebike")
    assert (row.build_id, row.previous_build_id) == ("20260903T080000Z", "")


def test_rollback_after_the_first_ever_swap_is_refused(workspace, states) -> None:
    """There is no previous build after the first rebuild, and the schema the
    first swap retired is the empty one it created on its way past. Rolling
    back to it promoted that empty schema over the served graph - five segments
    to zero, every settings row blanked, the tiles left where they were - and
    reported nothing at all.
    """
    from core.models import ValhallaUpstream
    from pipeline.promotion import RollbackUnavailable, rollback
    from pipeline.schema import schema_exists

    source, root = workspace
    run_pipeline(source, root, build_id="20260917T080000Z")

    with pytest.raises(RollbackUnavailable) as caught:
        rollback(root / "tiles")
    assert "previous" in str(caught.value)

    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5, "the served graph must be untouched"
    assert schema_exists(settings.SEGMENT_SCHEMA_RETIRED), "and the schemas left as they were"
    for variant in Variant:
        assert os.readlink(root / "tiles" / variant.value / "current") == "20260917T080000Z"
    row = ValhallaUpstream.objects.get(variant="standard")
    assert (row.build_id, row.previous_build_id) == ("20260917T080000Z", "")


def test_rollback_after_a_rebuild_that_failed_at_the_swap_is_refused(
    workspace, states, monkeypatch
) -> None:
    """The undone swap left nothing to roll back to either, and the failed
    rebuild's staging schema is still holding the name the rename needs. The
    only gate was `schema_exists(retired)`, true forever after the first swap,
    so this died on a raw ProgrammingError from the middle of the rename.
    """
    from core.models import ValhallaUpstream
    from pipeline import promotion
    from pipeline.promotion import RollbackUnavailable, rollback

    source, root = workspace
    run_pipeline(source, root, build_id="20260910T080000Z")
    monkeypatch.setattr(promotion, "swap_schemas", refusing_swap)
    build_toy_extract(source, changed=True)
    with pytest.raises(RebuildFailed):
        run_pipeline(source, root, build_id="20260917T080000Z")

    with pytest.raises(RollbackUnavailable):
        rollback(root / "tiles")

    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5
    for variant in Variant:
        assert os.readlink(root / "tiles" / variant.value / "current") == "20260910T080000Z"
    assert ValhallaUpstream.objects.get(variant="ebike").build_id == "20260910T080000Z"


def two_rebuilds(source: Path, root: Path) -> None:
    """Two weeks of rebuilds, which is the least a rollback needs behind it."""
    run_pipeline(source, root, build_id="20260910T080000Z")
    build_toy_extract(source, changed=True)
    run_pipeline(source, root, build_id="20260917T080000Z")


def test_an_undo_that_fails_on_one_variant_still_undoes_the_others(
    workspace, states, monkeypatch
) -> None:
    """The undo used to be one unguarded sequence, so the first step to raise
    skipped every step after it - the other two variants and the settings rows
    with them. That is the half-swapped deployment the undo exists to prevent,
    reached by the undo itself, and on a retryable error it would have been
    reached again on every attempt."""
    from core.models import ValhallaUpstream
    from pipeline import promotion, tiles

    source, root = workspace
    run_pipeline(source, root, build_id="20260910T080000Z")

    real_restore = tiles.restore_links

    def restore_that_fails_on_the_first_variant(tiles_dir, variant, state):
        if variant is Variant.STANDARD:
            raise OSError("the data volume is read-only")
        return real_restore(tiles_dir, variant, state)

    monkeypatch.setattr(promotion, "swap_schemas", refusing_swap)
    monkeypatch.setattr(tiles, "restore_links", restore_that_fails_on_the_first_variant)
    build_toy_extract(source, changed=True)
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, build_id="20260917T080000Z")
    assert "could not take the swap lock" in str(caught.value.cause), (
        "the swap's own failure is what the rebuild reports, not the undo's"
    )
    assert any("standard's tile links" in note for note in caught.value.cause.__notes__), (
        "what the undo could not put back is on the error an operator reads"
    )

    for variant in (Variant.NO_TRAIL, Variant.EBIKE):
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260910T080000Z", (
            f"{variant.value} was left on a build the swap never completed"
        )
        assert not (variant_dir / "previous").exists()
    for row in ValhallaUpstream.objects.all():
        assert (row.build_id, row.previous_build_id) == ("20260910T080000Z", ""), row.variant
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5, "last week's graph is still served"


def test_a_half_restored_swap_says_what_to_put_back(workspace, states, monkeypatch) -> None:
    """`SwapUndoIncomplete` is the one swap failure an operator repairs by hand,
    and the state to repair it to was held only by the undo: the repoint
    overwrites `previous_build_id` and `promote` overwrites `previous`. So the
    error carries every variant's links and row as the swap found them - here
    a third build over two, where both links and both row columns are set and
    none of them is the build that failed."""
    from pipeline import promotion, tiles
    from pipeline.promotion import SwapUndoIncomplete

    source, root = workspace
    two_rebuilds(source, root)

    real_restore = tiles.restore_links

    def restore_that_fails_on_the_first_variant(tiles_dir, variant, state):
        if variant is Variant.STANDARD:
            raise OSError("the data volume is read-only")
        return real_restore(tiles_dir, variant, state)

    monkeypatch.setattr(promotion, "swap_schemas", refusing_swap)
    monkeypatch.setattr(tiles, "restore_links", restore_that_fails_on_the_first_variant)
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, build_id="20260924T080000Z")

    undo = caught.value.cause
    assert isinstance(undo, SwapUndoIncomplete), type(undo)
    assert len(undo.before) == len(Variant)
    for variant, line in zip(Variant, undo.before, strict=True):
        assert line.startswith(variant.value), line
        # Which build is in which field, not how often each appears: the
        # runbook has the operator write these back one field at a time.
        assert described_fields(line) == {
            "current": "20260917T080000Z",
            "previous": "20260910T080000Z",
            "build_id": "20260917T080000Z",
            "previous_build_id": "20260910T080000Z",
        }, line
        assert "20260924T080000Z" not in line, f"the failed build is not the target: {line}"
        assert line in str(undo), "and it is on the message the run row records"
    # What the undo did put back agrees with what it says it found.
    variant_dir = root / "tiles" / Variant.EBIKE.value
    assert os.readlink(variant_dir / "current") == "20260917T080000Z"
    assert os.readlink(variant_dir / "previous") == "20260910T080000Z"


def described_fields(line: str) -> dict[str, str | None]:
    """The four fields of one `SwapUndoIncomplete.before` line, by name.

    A link or a row column that was not there reads as None, so a test can
    say which field holds which build without depending on the wording around
    them.
    """
    import re

    fields: dict[str, str | None] = {}
    for name, pattern in {
        "current": r"\bcurrent -> (\S+?),",
        "previous": r"\bprevious -> (\S+?),",
        "build_id": r"\bbuild_id=(\S+)",
        "previous_build_id": r"\bprevious_build_id=(\S+)",
    }.items():
        match = re.search(pattern, line)
        fields[name] = match.group(1) if match and match.group(1) != "no" else None
    return fields


def test_a_half_restored_first_swap_says_there_was_nothing_to_put_back(
    workspace, states, monkeypatch
) -> None:
    """Before the first-ever swap no variant has a link or a settings row, and
    the runbook reads that off these lines: remove the link, delete the row.
    Described as a row with empty build ids instead, the hand repair would
    leave a row naming no build for the API to read."""
    from core.models import ValhallaUpstream
    from pipeline import promotion, tiles
    from pipeline.promotion import SwapUndoIncomplete

    source, root = workspace
    real_restore = tiles.restore_links

    def restore_that_fails_on_the_first_variant(tiles_dir, variant, state):
        if variant is Variant.STANDARD:
            raise OSError("the data volume is read-only")
        return real_restore(tiles_dir, variant, state)

    monkeypatch.setattr(promotion, "swap_schemas", refusing_swap)
    monkeypatch.setattr(tiles, "restore_links", restore_that_fails_on_the_first_variant)
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, build_id="20260910T080000Z")

    undo = caught.value.cause
    assert isinstance(undo, SwapUndoIncomplete), type(undo)
    for variant, line in zip(Variant, undo.before, strict=True):
        assert line.startswith(variant.value), line
        assert described_fields(line) == dict.fromkeys(
            ("current", "previous", "build_id", "previous_build_id")
        ), line
        assert "no row" in line, f"the row that was not there is said not to be: {line}"
    assert ValhallaUpstream.objects.count() == 0, "and the undo deleted the rows it had written"


def test_a_promotion_that_dies_between_its_own_two_links_is_undone(
    workspace, states, monkeypatch
) -> None:
    """`promote` moves `previous` and then `current`, and a failure between
    them returns nothing - so the variant is in neither the promoted set nor
    the untouched one. An undo that walked the promoted set left that variant's
    `previous` naming the build still being served, which is the one piece of
    state claiming there is something to roll back to."""
    from pipeline import promotion, tiles

    source, root = workspace
    run_pipeline(source, root, build_id="20260910T080000Z")

    real_promote = tiles.promote

    def promote_that_dies_between_its_links(tiles_dir, variant, build_id):
        if variant is not Variant.NO_TRAIL:
            return real_promote(tiles_dir, variant, build_id)
        variant_dir = Path(tiles_dir) / variant.value
        before = tiles.promoted_build_id(tiles_dir, variant)
        tiles._replace_symlink(variant_dir / tiles.PREVIOUS, before)
        raise OSError("the volume filled between the two links")

    monkeypatch.setattr(promotion.tiles, "promote", promote_that_dies_between_its_links)
    build_toy_extract(source, changed=True)
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, build_id="20260917T080000Z")
    assert caught.value.stage is Stage.SWAP

    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260910T080000Z", variant.value
        assert not (variant_dir / "previous").exists(), (
            f"{variant.value} still claims there is a build to roll back to"
        )


def test_a_rollback_that_fails_partway_puts_the_deployment_back(
    workspace, states, monkeypatch
) -> None:
    """The emergency path had no undo at all.

    `rollback_swap` had already renamed the schemas when the per-variant loop
    began, so a `demote` that raised on the second variant left the schemas
    rolled back, one variant on last week's tiles and two on this week's, and
    one settings row rewritten - a state no rebuild and no rollback can reason
    about, reached by the one command whose purpose is to get out of one.
    """
    from core.models import ValhallaUpstream
    from pipeline import promotion, tiles
    from pipeline.schema import schema_exists

    source, root = workspace
    two_rebuilds(source, root)

    real_demote = tiles.demote

    def demote_that_fails_on_the_second_variant(tiles_dir, variant):
        if variant is Variant.NO_TRAIL:
            raise OSError("the data volume went read-only")
        return real_demote(tiles_dir, variant)

    monkeypatch.setattr(promotion.tiles, "demote", demote_that_fails_on_the_second_variant)

    with pytest.raises(OSError, match="read-only"):
        promotion.rollback(root / "tiles")

    assert count(settings.SEGMENT_SCHEMA_LIVE) == 4, "the newer graph is served again"
    assert schema_exists(settings.SEGMENT_SCHEMA_RETIRED), "and the rollback target is back"
    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260917T080000Z", variant.value
        assert os.readlink(variant_dir / "previous") == "20260910T080000Z", variant.value
    for row in ValhallaUpstream.objects.all():
        assert (row.build_id, row.previous_build_id) == (
            "20260917T080000Z",
            "20260910T080000Z",
        ), row.variant

    # And the deployment is one an operator can still act on: with the volume
    # writable again, the rollback the command was run for goes through.
    monkeypatch.setattr(promotion.tiles, "demote", real_demote)
    promotion.rollback(root / "tiles")
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5
    for variant in Variant:
        assert os.readlink(root / "tiles" / variant.value / "current") == "20260910T080000Z"


def refuse_rollback_row_writes(monkeypatch, on_call: int) -> list[dict]:
    """Make the rollback's `on_call`-th settings-row write raise (0: none do).

    The rollback's writes are the only `ValhallaUpstream` updates that blank
    `previous_build_id`; the undo's writes put a build id back, so they go
    through. Returns the list the rollback's writes are recorded in.
    """
    from django.db.models import QuerySet

    from core.models import ValhallaUpstream

    real_update = QuerySet.update
    calls = []

    def update(self, **kwargs):
        if self.model is ValhallaUpstream and kwargs.get("previous_build_id") == "":
            calls.append(kwargs)
            if len(calls) == on_call:
                raise RuntimeError("row write refused")
        return real_update(self, **kwargs)

    monkeypatch.setattr(QuerySet, "update", update)
    return calls


def test_a_rollback_refused_by_the_tiles_writes_no_row(workspace, states, monkeypatch) -> None:
    """The tiles move before the rows: the tile links are the step a mount
    refuses, and refused there the rollback has written nothing the API reads,
    so the rows never name last week's build even for the length of the undo."""
    from pipeline import promotion, tiles

    source, root = workspace
    two_rebuilds(source, root)
    row_writes = refuse_rollback_row_writes(monkeypatch, on_call=0)

    real_demote = tiles.demote

    def demote_that_fails_on_the_last_variant(tiles_dir, variant):
        if variant is list(Variant)[-1]:
            raise OSError("the data volume went read-only")
        return real_demote(tiles_dir, variant)

    monkeypatch.setattr(tiles, "demote", demote_that_fails_on_the_last_variant)
    with pytest.raises(OSError, match="went read-only"):
        promotion.rollback(root / "tiles")
    assert row_writes == [], f"the rows were rewritten before the tiles moved: {row_writes}"
    assert_served_as_the_second_rebuild_left_it(root)


def test_a_rollback_whose_row_write_is_refused_renames_no_schema(
    workspace, states, monkeypatch
) -> None:
    """The other half of the order: the rows are written before the rename,
    not after. A row write refused after a committed rename left the schemas
    rolled back under restored tiles and rows - round 10's end state, reached
    from the other step - because the undo never renames a schema."""
    from pipeline import promotion

    source, root = workspace
    two_rebuilds(source, root)
    refuse_rollback_row_writes(monkeypatch, on_call=1)

    with pytest.raises(RuntimeError, match="row write refused"):
        promotion.rollback(root / "tiles")
    assert_served_as_the_second_rebuild_left_it(root)


def test_a_rollback_whose_undo_fails_says_what_it_could_not_put_back(
    workspace, states, monkeypatch
) -> None:
    """The rollback re-raises its own failure, so what its undo could not
    restore is attached to that error; without the note the operator reads a
    `demote` error and is not told a variant's links are still moved."""
    from pipeline import promotion, tiles

    source, root = workspace
    two_rebuilds(source, root)

    real_demote = tiles.demote

    def demote_that_fails_on_the_second_variant(tiles_dir, variant):
        if variant is Variant.NO_TRAIL:
            raise OSError("the data volume went read-only")
        return real_demote(tiles_dir, variant)

    def restore_that_fails_on_the_first_variant(tiles_dir, variant, state):
        if variant is Variant.STANDARD:
            raise OSError("the data volume is read-only")
        return real_restore(tiles_dir, variant, state)

    real_restore = tiles.restore_links
    monkeypatch.setattr(tiles, "demote", demote_that_fails_on_the_second_variant)
    monkeypatch.setattr(tiles, "restore_links", restore_that_fails_on_the_first_variant)

    with pytest.raises(OSError, match="went read-only") as caught:
        promotion.rollback(root / "tiles")
    notes = getattr(caught.value, "__notes__", [])
    assert any(Variant.STANDARD.value in note for note in notes), notes
    assert not any(Variant.EBIKE.value in note for note in notes), (
        f"a variant the undo did put back is not reported: {notes}"
    )
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 4, "no schema moved"


def test_a_rollback_rewrites_every_row_or_none(workspace, states, monkeypatch) -> None:
    """The rows are rewritten in one transaction. That matters when the undo
    cannot put rows back: a refusal on the second variant's row must not leave
    the first variant's row naming last week's build under this week's graph."""
    from core.models import ValhallaUpstream
    from pipeline import promotion

    source, root = workspace
    two_rebuilds(source, root)
    refuse_rollback_row_writes(monkeypatch, on_call=2)

    def restore_upstreams_that_fails(before):
        raise RuntimeError("the settings rows could not be restored")

    monkeypatch.setattr(promotion, "restore_upstreams", restore_upstreams_that_fails)

    with pytest.raises(RuntimeError, match="row write refused") as caught:
        promotion.rollback(root / "tiles")
    assert any("settings rows" in note for note in caught.value.__notes__)
    for row in ValhallaUpstream.objects.all():
        assert (row.build_id, row.previous_build_id) == (
            "20260917T080000Z",
            "20260910T080000Z",
        ), row.variant
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 4, "no schema moved"


def assert_served_as_the_second_rebuild_left_it(root: Path) -> None:
    """Every part of the deployment `two_rebuilds` leaves, read back.

    The newer graph live, the older one retired, no staging schema, every
    variant's `current` on the newer build with `previous` on the older, and
    every settings row saying the same. A rollback that refused or undid
    itself has to leave exactly this.
    """
    from core.models import ValhallaUpstream
    from pipeline.schema import schema_exists

    assert count(settings.SEGMENT_SCHEMA_LIVE) == 4, "the newer graph is live"
    assert count(settings.SEGMENT_SCHEMA_RETIRED) == 5, "the rollback target is retired"
    assert not schema_exists(settings.SEGMENT_SCHEMA_STAGING), "and nothing sits in staging"
    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260917T080000Z", variant.value
        assert os.readlink(variant_dir / "previous") == "20260910T080000Z", variant.value
    rows = {row.variant: row for row in ValhallaUpstream.objects.all()}
    assert set(rows) == {variant.value for variant in Variant}
    for variant, row in rows.items():
        assert (row.build_id, row.previous_build_id) == (
            "20260917T080000Z",
            "20260910T080000Z",
        ), variant


def a_reader():
    """A separate backend, standing in for the API process reading segments.

    Django's test connection is the one the rollback runs on, so a lock taken
    through it would conflict with nothing.
    """
    from psycopg2 import connect

    db = connection.settings_dict
    return connect(
        host=db["HOST"] or "127.0.0.1",
        port=db["PORT"] or 5432,
        dbname=db["NAME"],
        user=db["USER"],
        password=db["PASSWORD"],
    )


def quick_lock_attempts(monkeypatch) -> None:
    """Both renames, as `promotion` calls them, giving up in a fraction of a
    second instead of the thirty-odd the defaults take to lose to a reader."""
    import functools

    from pipeline import promotion, swap

    quick = {"lock_timeout_ms": 150, "attempts": 2, "backoff_s": 0.0}
    monkeypatch.setattr(promotion, "swap_schemas", functools.partial(swap.swap_schemas, **quick))
    monkeypatch.setattr(promotion, "rollback_swap", functools.partial(swap.rollback_swap, **quick))


def test_a_rollback_refused_by_the_tiles_renames_no_schema_even_with_a_reader(
    workspace, states, monkeypatch
) -> None:
    """Round 10's blocker, as the reviewer ran it.

    The tiles are read-only where `api` and `worker` mount them. `rollback` used
    to rename the schemas first, fail on the first `demote`, and then have to
    rename them back - taking ACCESS EXCLUSIVE on the segment table an ordinary
    API reader holds ACCESS SHARE on all day. The re-swap lost its attempts,
    raised, and left last week's rows live under this week's tiles with the
    served build's rows in `staging`. Here a reader takes its lock the moment
    the tiles refuse, which is the interleaving that produced it: nothing may
    need that lock to put the deployment back.
    """
    from pipeline import promotion, tiles

    source, root = workspace
    two_rebuilds(source, root)
    quick_lock_attempts(monkeypatch)

    holder = a_reader()
    real_demote = tiles.demote

    def demote_on_a_read_only_mount(tiles_dir, variant):
        if variant is Variant.NO_TRAIL:
            with holder.cursor() as cursor:
                cursor.execute(
                    f"LOCK TABLE {settings.SEGMENT_SCHEMA_LIVE}.segment IN ACCESS SHARE MODE"
                )
            raise OSError(30, "Read-only file system")
        return real_demote(tiles_dir, variant)

    monkeypatch.setattr(promotion.tiles, "demote", demote_on_a_read_only_mount)
    try:
        with pytest.raises(OSError, match="Read-only"):
            promotion.rollback(root / "tiles")
    finally:
        holder.rollback()
        holder.close()

    assert_served_as_the_second_rebuild_left_it(root)


def test_a_rollback_whose_rename_loses_to_a_reader_puts_the_tiles_and_rows_back(
    workspace, states, monkeypatch
) -> None:
    """The rename is the last step now, so it is the one a reader can still
    refuse - and by then the tiles and the rows have moved. Its refusal has to
    put both back: one transaction renamed nothing, so the links and the rows
    are the whole of the undo. Then, with the reader gone, the same rollback
    goes through, which is what an operator will do next."""
    from pipeline import promotion
    from pipeline.swap import SwapLockTimeout

    source, root = workspace
    two_rebuilds(source, root)
    quick_lock_attempts(monkeypatch)

    holder = a_reader()
    try:
        with holder.cursor() as cursor:
            cursor.execute(
                f"LOCK TABLE {settings.SEGMENT_SCHEMA_LIVE}.segment IN ACCESS SHARE MODE"
            )
        with pytest.raises(SwapLockTimeout):
            promotion.rollback(root / "tiles")
        assert_served_as_the_second_rebuild_left_it(root)
    finally:
        holder.rollback()
        holder.close()

    promotion.rollback(root / "tiles")
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5
    for variant in Variant:
        assert os.readlink(root / "tiles" / variant.value / "current") == "20260910T080000Z"


def test_a_rollback_inside_a_transaction_is_refused_before_anything_moves(
    workspace, states, monkeypatch
) -> None:
    """`rollback_swap` refuses an enclosing transaction, and it used to be the
    first thing `rollback` ran. It is the last now, so the refusal is made up
    front - otherwise the tiles and the rows would move and be put back for a
    refusal that was always going to happen."""
    from django.db import transaction

    from pipeline import promotion
    from pipeline.swap import SwapInsideTransaction

    source, root = workspace
    two_rebuilds(source, root)

    moved: list[Variant] = []
    real_demote = promotion.tiles.demote

    def watched_demote(tiles_dir, variant):
        moved.append(variant)
        return real_demote(tiles_dir, variant)

    monkeypatch.setattr(promotion.tiles, "demote", watched_demote)
    with pytest.raises(SwapInsideTransaction), transaction.atomic():
        promotion.rollback(root / "tiles")
    assert not moved, f"the tiles moved before the refusal: {moved}"
    assert_served_as_the_second_rebuild_left_it(root)


needs_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root writes through a read-only mode bit; the container proof covers a :ro mount",
)


class read_only:
    """One directory made unwritable for the length of a `with` block.

    Mode bits rather than a mount, which a test cannot make: the symlink call
    fails with the same `OSError` either way, and a real `:ro` bind is proved
    in the running stack instead (docs/OPERATIONS.md, "Rolling back a
    rebuild").
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Path:
        self.mode = self.path.stat().st_mode
        self.path.chmod(0o555)
        return self.path

    def __exit__(self, *exc) -> None:
        self.path.chmod(self.mode)


@needs_permissions
@pytest.mark.parametrize("variant", list(Variant), ids=lambda variant: variant.value)
@pytest.mark.parametrize("confirm", [False, True], ids=["dry-run", "confirm"])
def test_the_rollback_command_refuses_where_it_cannot_write_the_tiles(
    workspace, states, monkeypatch, variant, confirm
) -> None:
    """`api` and `worker` bind the tiles read-only, and in either the command
    used to get as far as the first `demote`. A deployment with a complete
    rollback target, so the directory it cannot write is the only reason to
    refuse; each variant in turn, because a probe of the first directory alone
    would miss a mount that is read-only for the last."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    source, root = workspace
    monkeypatch.setattr(settings, "TILES_DIR", root / "tiles")
    two_rebuilds(source, root)

    args = ["--confirm"] if confirm else []
    with read_only(root / "tiles" / variant.value) as blocked:
        with pytest.raises(CommandError) as refused:
            call_command("rollback_rebuild", *args)
    message = str(refused.value)
    assert str(blocked) in message, f"the refusal does not name the directory: {message}"
    assert "exec -T rebuild " in message, f"the refusal does not name where to run it: {message}"
    assert_served_as_the_second_rebuild_left_it(root)


@needs_permissions
def test_rollback_itself_refuses_where_it_cannot_write_the_tiles(workspace, states) -> None:
    """The same refusal from the function, for a caller that is not the
    command - a shell, the acceptance checklist. Nothing moves, so nothing has
    to be put back and no undo note is attached."""
    from pipeline.promotion import TilesNotWritable, rollback

    source, root = workspace
    two_rebuilds(source, root)

    with read_only(root / "tiles" / Variant.EBIKE.value):
        with pytest.raises(TilesNotWritable) as refused:
            rollback(root / "tiles")
    assert not getattr(refused.value, "__notes__", None), refused.value.__notes__
    assert_served_as_the_second_rebuild_left_it(root)


def test_the_write_probe_leaves_nothing_behind(workspace, states, monkeypatch) -> None:
    """A dry run in `rebuild` writes and removes one link per variant; what the
    tile directories hold afterwards is exactly what they held before."""
    from io import StringIO

    from django.core.management import call_command

    source, root = workspace
    monkeypatch.setattr(settings, "TILES_DIR", root / "tiles")
    two_rebuilds(source, root)
    before = {path: sorted(path.iterdir()) for path in (root / "tiles").iterdir()}

    call_command("rollback_rebuild", stdout=StringIO())

    after = {path: sorted(path.iterdir()) for path in (root / "tiles").iterdir()}
    assert after == before


def test_the_rollback_command_is_dry_until_it_is_confirmed(workspace, states, monkeypatch) -> None:
    """`promotion.rollback` had no caller: the one procedure the plan names for
    a bad promotion could only be run by importing the module in a shell. It is
    dry by default because it is destructive in the direction nobody wants
    twice - it retires the graph being served."""
    from io import StringIO

    from django.core.management import call_command

    from core.models import ValhallaUpstream

    source, root = workspace
    monkeypatch.setattr(settings, "TILES_DIR", root / "tiles")
    two_rebuilds(source, root)

    out = StringIO()
    call_command("rollback_rebuild", stdout=out)
    printed = out.getvalue()

    assert "standard: would go back to build 20260910T080000Z" in printed
    assert "dry run: nothing was changed" in printed
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 4, "the newer graph is still being served"
    assert ValhallaUpstream.objects.get(variant="ebike").build_id == "20260917T080000Z"

    out = StringIO()
    call_command("rollback_rebuild", "--confirm", stdout=out)
    printed = out.getvalue()

    assert "ebike: serving build 20260910T080000Z" in printed
    assert "docker compose restart valhalla-standard" in printed, (
        "the routers do not reload tiles, so the rollback is not finished without a restart"
    )
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5
    for variant in Variant:
        assert os.readlink(root / "tiles" / variant.value / "current") == "20260910T080000Z"
    assert ValhallaUpstream.objects.get(variant="ebike").build_id == "20260910T080000Z"


def test_the_rollback_command_refuses_on_a_deployment_with_nothing_behind_it(
    workspace, monkeypatch
) -> None:
    """A fresh database, which is the state an operator is most likely to try
    this in by mistake. It exits non-zero with the refusal on it rather than
    promoting the empty schema the first swap creates."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    _source, root = workspace
    monkeypatch.setattr(settings, "TILES_DIR", root / "tiles")

    with pytest.raises(CommandError) as refused:
        call_command("rollback_rebuild")
    assert "refusing to roll back" in str(refused.value)
    assert "has no settings row" in str(refused.value)


# --- `rollback_target`, one clause at a time ----------------------------------------
#
# All four preconditions are read before anything is renamed or moved, and each
# one is the only thing standing between some half-built deployment and a
# rollback that promotes it. The two refusal tests above are satisfied by
# whichever clause fires first, so each clause gets a test that satisfies the
# other three.


def test_rollback_is_refused_when_a_settings_row_names_no_previous_build(workspace, states) -> None:
    """The row is the only record of which build was being served before this
    one. Without it there is nothing to repoint the upstreams to, and the
    rollback would have blanked them."""
    from core.models import ValhallaUpstream
    from pipeline.promotion import RollbackUnavailable, rollback_target

    source, root = workspace
    two_rebuilds(source, root)

    ValhallaUpstream.objects.filter(variant="ebike").update(previous_build_id="")

    with pytest.raises(RollbackUnavailable, match="ebike's settings row names no previous build"):
        rollback_target(root / "tiles")


def test_rollback_is_refused_when_the_tiles_and_the_row_disagree(workspace, states) -> None:
    """`previous` and `previous_build_id` name the same build on a deployment
    that swapped cleanly. When they disagree, one of them is from a rebuild
    that did not finish, and a rollback would put a graph and an extract from
    different weeks together."""
    from pipeline import tiles
    from pipeline.promotion import RollbackUnavailable, rollback_target

    source, root = workspace
    two_rebuilds(source, root)

    tiles._replace_symlink(root / "tiles" / "ebike" / "previous", "20260101T080000Z")

    with pytest.raises(RollbackUnavailable, match="ebike's previous tiles are 20260101T080000Z"):
        rollback_target(root / "tiles")


def test_rollback_is_refused_when_the_retired_schema_holds_no_segments(workspace, states) -> None:
    """A retired schema exists forever after the first swap, and an empty one
    is what the first swap retires: `swap_schemas` creates an empty live schema
    on a fresh deployment so the first rename has something to move out of the
    way. Promoting that over the served graph took a five-segment live table to
    zero with nothing raised."""
    from pipeline.promotion import RollbackUnavailable, rollback_target

    source, root = workspace
    two_rebuilds(source, root)
    rollback_target(root / "tiles")  # everything else about this deployment is fine

    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {settings.SEGMENT_SCHEMA_RETIRED}.segment CASCADE")

    with pytest.raises(RollbackUnavailable, match="holds no segments"):
        rollback_target(root / "tiles")


def test_a_rebuild_cannot_build_into_a_build_id_already_on_disk(workspace, states) -> None:
    """Build ids are second-resolution, and two fires inside one second wrote
    the second build into the directory the first one had already promoted -
    the graph being served - ending with `current` and `previous` both pointing
    at it. The second build refuses before it writes anything.
    """
    from core.models import ValhallaUpstream

    source, root = workspace
    run_pipeline(source, root, build_id="20260917T080000Z")

    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, build_id="20260917T080000Z")
    assert caught.value.stage is Stage.BUILD_TILES
    assert "20260917T080000Z" in str(caught.value.cause)

    for variant in Variant:
        variant_dir = root / "tiles" / variant.value
        assert os.readlink(variant_dir / "current") == "20260917T080000Z"
        assert not (variant_dir / "previous").exists(), "the served build is not its own previous"
    assert count(settings.SEGMENT_SCHEMA_LIVE) == 5
    assert ValhallaUpstream.objects.get(variant="standard").build_id == "20260917T080000Z"


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
        context, report = run_pipeline(install_source_extract(root), root)

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


def test_the_command_runner_hands_back_both_streams_kept_apart() -> None:
    """Run for real, against a shell, because this is the one function in the
    pipeline that nothing can fake for itself.

    `valhalla_service` in one-shot mode forces its logging to stderr and writes
    the response to stdout (src/valhalla_service.cc:42-44), so a runner that
    returned `CommandOutput(stdout, "")` would throw away every line the build
    log is read for - "Using LUA script:", and the transform's own
    ROUTEMAKER-VIOLATION lines, which `io.stderr:write` puts on stderr while
    Valhalla's go to stdout. The Lua-fallback check and the violation check are
    both read off `.log`, which is the two concatenated, so dropping stderr
    silently disarms the violation guard while every test that fakes the runner
    keeps passing.
    """
    from pipeline.run import _run_command

    output = _run_command(["sh", "-c", "echo out; echo err 1>&2"])

    assert output.stdout == "out\n"
    assert output.stderr == "err\n", "the stream the transform's refusals arrive on"
    assert output.log == "out\nerr\n", "and the log is both, in that order"


def test_a_command_that_exits_non_zero_reports_what_it_said(caplog, tmp_path) -> None:
    """The other half of the runner, and the one every first rebuild meets.

    `subprocess.run(check=True)` raises a `CalledProcessError` whose message is
    the argv and the exit status; it carries the captured streams on the
    exception object and nothing read them. So a curl that got a 404, an
    `osmium merge` that could not detect a file format, a gdalwarp that could
    not read an HGT, and a `valhalla_build_tiles` that died six hours in were
    all reported as a command and a number - while the tool's own account of
    why it stopped sat in an attribute on the exception and was collected.

    Run against a real shell for the same reason the test above is: this is the
    one function nothing can fake for itself.
    """
    from pipeline.run import CommandFailed, _run_command

    # The script is a file rather than `sh -c <text>` so that what it prints is
    # nowhere in the argv: the argv is in the message already, and a test whose
    # expected line is quoted there passes against a runner that reports only
    # the command it ran, which is the defect being fixed.
    script = tmp_path / "failing-command.sh"
    script.write_text(
        "echo 'reading /data/extracts/merged.osm.pbf.part'\n"
        "echo 'Could not detect file format for filename' 1>&2\n"
        "exit 3\n"
    )

    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        with pytest.raises(CommandFailed) as caught:
            _run_command(["sh", str(script)])

    message = str(caught.value)
    assert str(script) in message, "the argv is still reported"
    assert "Could not detect file format for filename" in message, (
        "the reason the command gave is what the message is for"
    )
    assert "merged.osm.pbf.part" in message, "and stdout, for the binaries that diagnose there"
    assert "exited 3" in message, "with the exit status, which is a different fact"
    assert caught.value.returncode == 3
    # And an operator watching the rebuild's log at the moment it failed sees
    # the same thing, rather than having to wait for the job row.
    assert "Could not detect file format for filename" in caplog.text
    assert [r.levelname for r in caplog.records] == ["WARNING"]


def test_a_failed_commands_output_is_quoted_from_the_end_and_bounded(caplog, tmp_path) -> None:
    """A tail, because `valhalla_build_tiles` writes progress for six hours and
    this text goes into an exception, a log record and the job row - and because
    what says why a command stopped is the last thing it wrote."""
    from pipeline.run import COMMAND_OUTPUT_TAIL_LINES, CommandFailed, _run_command

    script = tmp_path / "chatty-command.sh"
    script.write_text("seq 1 500 1>&2\necho 'the reason it stopped' 1>&2\nexit 1\n")

    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        with pytest.raises(CommandFailed) as caught:
            _run_command(["sh", str(script)])

    message = str(caught.value)
    assert "the reason it stopped" in message, "the end of the stream is the part kept"
    assert "\n1\n" not in message, "and the beginning of 500 progress lines is not"
    quoted = [line for line in message.splitlines() if line.strip().isdigit()]
    assert len(quoted) == COMMAND_OUTPUT_TAIL_LINES - 1, (
        "the quote is bounded by the constant that says why it is bounded"
    )
    # And the constant itself, because everything above holds for any value of
    # it. What is being rescued is the diagnosis a tool prints just before it
    # stops - osmium's "Could not detect file format for filename", curl's "The
    # requested URL returned error: 404", the merge's multiple-version warning -
    # and each of those is a line or two with a little context around it. Three
    # would cut the context off; a hundred would put a screen of progress in
    # front of every reader of an exception, a log record and a job row.
    assert COMMAND_OUTPUT_TAIL_LINES == 20


def test_the_lua_check_reads_the_script_out_of_the_config_the_build_was_given(tmp_path) -> None:
    """N-3: `mjolnir.graph_lua_name` in the config handed to
    `valhalla_build_tiles` is the instruction Valhalla was given, so it is what
    its log has to be held to.

    Against a constant in `pipeline/run.py`, the path lived in two files - here
    and in `scripts/build_valhalla_configs.py` - and the pair that had to agree
    were never compared. A generator retargeted at another script would then
    produce builds that loaded exactly what they were told to and failed
    validation against a path nothing had used since.
    """
    from pipeline.run import ValidationFailed, assert_lua_script_was_loaded

    log = "... Using LUA script: /conf/lua/graph.lua ..."
    config = tmp_path / "valhalla.json"

    config.write_text(json.dumps({"mjolnir": {"graph_lua_name": "/conf/lua/elsewhere.lua"}}))
    with pytest.raises(ValidationFailed) as caught:
        assert_lua_script_was_loaded(log, config, "standard")
    assert "/conf/lua/elsewhere.lua" in str(caught.value), "the message names what was asked for"

    # The same log against a config that names that script passes, so the
    # failure above is the comparison and not the log.
    config.write_text(json.dumps({"mjolnir": {"graph_lua_name": "/conf/lua/graph.lua"}}))
    assert_lua_script_was_loaded(log, config, "standard")


def test_the_lua_check_refuses_a_config_that_names_no_script(tmp_path) -> None:
    """A build config with no `mjolnir.graph_lua_name` was never told which
    transform to load, so there is no question to ask of its log and the answer
    is not "it passed"."""
    from pipeline.run import ValidationFailed, assert_lua_script_was_loaded

    config = tmp_path / "valhalla.json"
    config.write_text(json.dumps({"mjolnir": {"tile_dir": "/data/tiles/standard/x"}}))
    with pytest.raises(ValidationFailed, match="graph_lua_name"):
        assert_lua_script_was_loaded("Using LUA script: /conf/lua/graph.lua", config, "standard")


def test_validate_refuses_when_a_variant_produced_no_build_log(tmp_path) -> None:
    """The guard before the guards. Every per-variant check reads
    `context.build_logs[variant]`, so a variant that produced no log at all is a
    variant nothing is asked about - and iterating the logs that are there would
    have passed a rebuild in which only one variant was ever built.
    """
    from pipeline.run import ValidationFailed

    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
        tiles_dir=tmp_path / "tiles",
    )
    handlers = build_handlers(
        context, run=FakeBinaries(), fetch_elevation=fake_fetch, disk_usage=roomy_disk
    )
    context.build_logs = {
        Variant.STANDARD: LUA_LOADED_LOG,
        Variant.NO_TRAIL: LUA_LOADED_LOG,
    }

    with pytest.raises(ValidationFailed) as caught:
        handlers[Stage.VALIDATE]()

    assert "not every variant produced a build log" in str(caught.value)
    assert "'no-trail', 'standard'" in str(caught.value), "it says which it has"


def test_validate_refuses_when_a_variant_has_no_build_config(workspace, states) -> None:
    """The same guard, one field over. The elevation check reads back every
    variant's build through that variant's own config, and it iterated the
    configs that were there - so a rebuild in which two variants never got a
    config was a rebuild in which the grade of one graph stood in for three,
    and the two unchecked ones could have been built with no elevation at all.

    Run against a real, completed build so every other VALIDATE check has its
    artefacts; the only thing taken away is the other two configs.
    """
    from pipeline.run import ValidationFailed, _least_grade_across_variants

    source, root = workspace
    binaries = FakeBinaries()
    context, _ = run_pipeline(source, root, binaries=binaries, skip=NOT_SWAPPED)
    assert set(context.build_configs) == set(Variant), "the build really produced all three"

    context.build_configs = {Variant.STANDARD: context.build_configs[Variant.STANDARD]}
    handlers = build_handlers(
        context, run=binaries, fetch_elevation=fake_fetch, disk_usage=roomy_disk
    )

    with pytest.raises(ValidationFailed) as caught:
        handlers[Stage.VALIDATE]()
    # The guard's own words, not merely "a ValidationFailed came out". Skipped
    # rather than raised, the loop simply passes over the two variants it
    # cannot check and the elevation read-back below raises a few lines later,
    # which is a message about grades on a rebuild whose transform was never
    # checked at all - so a test satisfied by any refusal mentioning a build
    # config is satisfied by the guard not being there.
    message = str(caught.value)
    assert "produced a build log and no build config" in message
    assert Variant.NO_TRAIL.value in message, "and it names the variant it stopped on"

    # And the elevation read-back refuses on its own account, not only because
    # the admin-database check happens to run first and notice the same gap.
    # Left to `min()` over whatever configs were present, two variants built
    # with no elevation at all would have been validated by the third's grade.
    with pytest.raises(ValidationFailed, match="not every variant has a build config"):
        _least_grade_across_variants(context, binaries)


def test_a_missing_handler_is_refused_before_any_stage_runs() -> None:
    """Silently continuing made an omitted stage indistinguishable from a
    deliberate one. Raising when the gap is reached was better and still not
    right: the gap was the swap, after hours of building."""
    from pipeline.rebuild import StageNotImplemented

    ran: list[Stage] = []
    with pytest.raises(StageNotImplemented, match="swap"):
        run_rebuild({Stage.FETCH_EXTRACT: lambda: ran.append(Stage.FETCH_EXTRACT)})
    assert ran == [], "nothing runs until every stage is accounted for"


# --- The e-bike bar against the crossings fixture --------------------------------

EBIKE_BARRED_BRIDGE = 800
ORDINARY_BRIDGE = 801
RESTRICTED_BRIDGE = 802


def _write_ebike_bridge_extract(path: Path) -> None:
    """Two bike-legal bridge roadways, one of which bars electric bicycles.

    `electric_bicycle=no` on a roadway is what the e-bike variant is built from:
    `variants.inject` writes `bicycle=no` onto those ways, because Valhalla's
    bicycle costing is what reads the bicycle tag and there is no e-bike access
    mask to write to. The other two are controls: the same structure with no
    e-bike restriction, and one tagged `electric_bicycle=private`, which
    restricts who may ride rather than what may - the variant does not bar it,
    so nothing may be withheld on it either. A suppression that is not scoped to
    the bar shows up as the fixture's row going missing on one of them.
    """
    Path(path).unlink(missing_ok=True)  # osmium refuses to overwrite
    writer = osmium.SimpleWriter(str(path))
    try:
        nodes = {
            1: (-77.045, 38.905),
            2: (-77.030, 38.905),
            3: (-77.045, 38.9060),
            4: (-77.030, 38.9060),
            5: (-77.045, 38.9070),
            6: (-77.030, 38.9070),
        }
        for node_id, (lon, lat) in nodes.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=EBIKE_BARRED_BRIDGE,
                nodes=[1, 2],
                version=1,
                tags={
                    "highway": "trunk",
                    "bridge": "yes",
                    "name": "E-bike Barred Bridge",
                    "electric_bicycle": "no",
                },
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=ORDINARY_BRIDGE,
                nodes=[3, 4],
                version=1,
                tags={"highway": "trunk", "bridge": "yes", "name": "Ordinary Bridge"},
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=RESTRICTED_BRIDGE,
                nodes=[5, 6],
                version=1,
                tags={
                    "highway": "trunk",
                    "bridge": "yes",
                    "name": "Restricted Bridge",
                    "electric_bicycle": "private",
                },
            )
        )
    finally:
        writer.close()


def test_the_ebike_bar_is_not_granted_back_by_the_crossings_fixture(
    tmp_path, segment_schemas, states
) -> None:
    """The e-bike variant's own decision, and the one class of way the transform
    is allowed to widen.

    The variant bars this bridge by writing `bicycle=no`. The transform then
    reads the fixture's `rm:bridge_bicycle=yes` over the same extract, sees a
    roadway whose `bicycle=no` looks exactly like OSM's own tagging on a barred
    bridge, and grants `bicycle=yes` back: the variant's whole decision reverted.

    Declined here rather than in the Lua, and only here, because this loop knows
    which variant it is writing and the transform cannot: one script serves all
    three extracts, so the guard it can write reads the `electric_bicycle` tag
    and therefore declines the fixture's row on the standard and no-trail
    variants too, where no e-bike rule applies and the row should stand. Read
    back from the written PBFs, which are the only thing the tile build sees.
    """
    from pipeline.extract import read_ways

    source = install_source_extract(tmp_path, _write_ebike_bridge_extract)
    context, _ = run_pipeline(
        source,
        tmp_path,
        urban=(EBIKE_BARRED_BRIDGE, ORDINARY_BRIDGE, RESTRICTED_BRIDGE),
        legality={EBIKE_BARRED_BRIDGE: True, ORDINARY_BRIDGE: True, RESTRICTED_BRIDGE: True},
        skip=NOT_SWAPPED,
    )

    for variant in Variant:
        tags = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(variant))}
        for control in (ORDINARY_BRIDGE, RESTRICTED_BRIDGE):
            assert tags[control].get("rm:bridge_bicycle") == "yes", (
                f"the {variant.value} variant lost a legality row on way {control}, which "
                "the e-bike bar does not cover"
            )
            assert "bicycle" not in tags[control], f"and nothing bars way {control}"
        if variant is Variant.EBIKE:
            assert "rm:bridge_bicycle" not in tags[EBIKE_BARRED_BRIDGE], (
                "the transform is handed the fixture's grant over the e-bike bar"
            )
            assert tags[EBIKE_BARRED_BRIDGE]["bicycle"] == "no", "and the bar itself is there"
        else:
            assert tags[EBIKE_BARRED_BRIDGE].get("rm:bridge_bicycle") == "yes", (
                f"the {variant.value} variant, where no e-bike rule applies, lost the "
                "fixture's row to a way tagged for a restriction it does not enforce"
            )
            assert "bicycle" not in tags[EBIKE_BARRED_BRIDGE], "and nothing bars it here"
