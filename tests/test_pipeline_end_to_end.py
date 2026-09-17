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
    LUA_LOADED_LOG,
    PARALLEL_COUNT,
    REPO,
    FakeBinaries,
    box,
    build_named_bridge_extract,
    build_parallel_extract,
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
            "year": 2025,
        }
    ]
    context, _ = run_pipeline(source, root, volume=volume, skip=NOT_SWAPPED)
    assert context.aadt_by_way.get(100) == (900, "state")
    assert context.stress_by_way[100].volume_source == "state"


@pytest.mark.parametrize(
    ("road_id", "trail_id"),
    [(100, 200), (200, 100)],
    ids=["road-first", "trail-first"],
)
def test_a_trail_alongside_a_road_cannot_take_the_roads_count(
    tmp_path, states, road_id, trail_id
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
    source = tmp_path / "parallel.osm.pbf"
    build_parallel_extract(source, road_id=road_id, trail_id=trail_id)
    context, _ = run_pipeline(
        source, tmp_path, urban=(road_id, trail_id), volume=[PARALLEL_COUNT], skip=NOT_SWAPPED
    )

    assert context.aadt_by_way.get(road_id) == (24000, "state"), "the count belongs to the road"
    assert trail_id not in context.aadt_by_way, "a path carries no motor traffic"
    assert context.stress_by_way[road_id].volume_source == "state"


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
    tmp_path, states
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

    source = tmp_path / "bridge.osm.pbf"
    build_named_bridge_extract(
        source, roadway_id=700, sidepath_id=701, name="Woodrow Wilson Memorial Bridge"
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
        run_pipeline(source, root, binaries=FakeBinaries(build_admin=False), build_id="no-admin")
    assert caught.value.stage is Stage.VALIDATE
    assert "mjolnir.admin" in str(caught.value.cause)

    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, binaries=FakeBinaries(build_timezone=False), build_id="no-tz")
    assert "mjolnir.timezone" in str(caught.value.cause)


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
    assert len(admins) == 3, "one per variant, each through its own config"
    assert {c[-1] for c in admins} == {str(source)}, "built from the source extract"

    downloads = [c for c in binaries.calls if c[0] == "sh"]
    copies = [c for c in binaries.calls if c[0] == "cp"]
    assert len(downloads) == 1, "a hundred megabytes, fetched once"
    assert len(copies) == 2


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
