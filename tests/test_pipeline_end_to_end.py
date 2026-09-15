"""The pipeline, wired and run end to end.

Until this existed, every module in `pipeline/` was called only from its own
unit test: there was no OSM reader, no writer, no handler set, and the stage
ordering tests asserted an enum against itself. This runs a real PBF through
the real stages into a real staging schema.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import osmium
import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.db import connection

from pipeline.borders import SyntheticNodeIds

pytestmark = pytest.mark.django_db(transaction=True)


def build_toy_extract(path: Path) -> None:
    """A road crossing the District line, a trail, and a farm track."""
    writer = osmium.SimpleWriter(str(path))
    try:
        nodes = {
            1: (-77.02, 38.90),
            2: (-76.98, 38.90),  # crosses -77.00
            3: (-77.04, 38.91),
            4: (-77.03, 38.91),  # trail, inside DC
            5: (-77.045, 38.92),
            6: (-77.035, 38.92),  # track
        }
        for node_id, (lon, lat) in nodes.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=100,
                nodes=[1, 2],
                version=1,
                tags={"highway": "secondary", "maxspeed": "35 mph", "name": "Test Road"},
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=200, nodes=[3, 4], version=1, tags={"highway": "cycleway", "name": "Test Trail"}
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=300,
                nodes=[5, 6],
                version=1,
                tags={"highway": "track", "surface": "gravel", "tracktype": "grade2"},
            )
        )
        # A path e-bikes are barred from, and a bridge whose only bike provision
        # is a sidewalk.
        writer.add_way(
            osmium.osm.mutable.Way(
                id=400,
                nodes=[3, 4],
                version=1,
                tags={"highway": "path", "electric_bicycle": "no"},
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=500,
                nodes=[5, 6],
                version=1,
                tags={"highway": "trunk", "bridge": "yes", "name": "Sidepath Bridge"},
            )
        )
    finally:
        writer.close()


@pytest.fixture
def states():
    from core.models import Jurisdiction

    Jurisdiction.objects.all().delete()

    def box(west, east):
        return MultiPolygon(
            Polygon(((west, 38.85), (east, 38.85), (east, 38.95), (west, 38.95), (west, 38.85)))
        )

    Jurisdiction.objects.create(
        layer="police", name="MPD", state="DC", geometry=box(-77.10, -77.00)
    )
    Jurisdiction.objects.create(
        layer="police", name="Arlington", state="VA", geometry=box(-77.00, -76.90)
    )
    # The state layer the border inserter resolves against. Querying every layer
    # let a park polygon answer and made the result non-deterministic.
    Jurisdiction.objects.create(
        layer="state", name="District of Columbia", state="DC", geometry=box(-77.10, -77.00)
    )
    Jurisdiction.objects.create(
        layer="state", name="Virginia", state="VA", geometry=box(-77.00, -76.90)
    )
    yield
    Jurisdiction.objects.all().delete()


@pytest.fixture
def workspace(segment_schemas):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.osm.pbf"
        build_toy_extract(source)
        yield source, root


def write_reference_data(root: Path, *, urban=(), sidepath=(), volume=()) -> Path:
    """The reference inputs the rebuild refuses to run without."""
    directory = root / "reference"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "urban-areas.json").write_text(json.dumps(list(urban)))
    (directory / "crossings.json").write_text(
        json.dumps(
            [
                {"osm_way_id": way_id, "sidepath_only": True, "roadway_bicycle_legal": False}
                for way_id in sidepath
            ]
        )
    )
    (directory / "volume.json").write_text(json.dumps(list(volume)))
    return directory


def run_pipeline(
    source: Path,
    root: Path,
    *,
    grade: float = 0.08,
    log: str | None = None,
    derived: str | None = "yes",
    urban=(100, 200, 300, 400, 500),
    sidepath=(),
    volume=(),
):
    from pipeline.rebuild import Stage, run_rebuild
    from pipeline.run import RebuildContext, build_handlers

    reference = write_reference_data(root, urban=urban, sidepath=sidepath, volume=volume)
    context = RebuildContext(source_pbf=source, work_dir=root / "work", reference_dir=reference)
    default_log = "... Using LUA script: /conf/lua/graph.lua ..."
    handlers = build_handlers(
        context,
        run=lambda command: log if log is not None else default_log,
        sample_grade=lambda: grade,
        sample_derived_tag=lambda: derived,
    )
    report = run_rebuild(handlers, skip=frozenset({Stage.SWAP, Stage.RECONCILE}))
    return context, report


def test_a_full_rebuild_populates_the_staging_schema(workspace, states) -> None:
    source, root = workspace
    context, report = run_pipeline(source, root)

    assert report.completed, "stages must have run"
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM staging.segment")
        assert cursor.fetchone()[0] == 5, "one segment per way"
        cursor.execute("SELECT osm_way_id, stress_tier FROM staging.segment ORDER BY osm_way_id")
        tiers = dict(cursor.fetchall())

    assert tiers[200] == 1, "a trail is lowest stress"
    assert tiers[300] == 1, "a gravel farm track is a low-stress choice, not a hazard"
    assert tiers[100] >= 3, "a 35 mph secondary with no facility is high stress"


def test_the_border_node_reaches_the_crossings_table(workspace, states) -> None:
    """The node ids are reassigned each rebuild, so the table is what records
    what each one means."""
    from core.models import BorderCrossing

    source, root = workspace
    run_pipeline(source, root)

    crossings = list(BorderCrossing.objects.all())
    assert len(crossings) == 1
    assert {crossings[0].state_a, crossings[0].state_b} == {"DC", "VA"}
    assert crossings[0].osm_way_id == 100
    assert SyntheticNodeIds.is_synthetic(crossings[0].node_id)


def test_the_written_extract_carries_the_border_node_in_the_way(workspace, states) -> None:
    """Round-tripped through a real PBF: a minted node id has to survive the
    write, which nothing verified before."""
    from pipeline.extract import read_ways
    from pipeline.variants import Variant

    source, root = workspace
    context, _ = run_pipeline(source, root)

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
    from pipeline.variants import Variant

    source, root = workspace
    context, _ = run_pipeline(source, root)

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
    from pipeline.variants import Variant

    source, root = workspace
    context, _ = run_pipeline(source, root)

    ways = {w.osm_id for w in read_ways(context.variant_pbf(Variant.NO_TRAIL))}
    assert 200 not in ways, "a mass ride cannot use an eight-foot path"
    assert 100 in ways


def test_a_silent_lua_fallback_fails_the_build(workspace, states) -> None:
    """Valhalla logs nothing when it cannot load the configured script and uses
    its built-in transform instead, dropping every derived tag."""
    from pipeline.rebuild import RebuildFailed

    source, root = workspace
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, log="tiles built, 0 errors")
    assert caught.value.stage.value == "validate"
    assert "built-in transform" in str(caught.value.cause)


def test_the_wrong_lua_script_fails_the_build(workspace, states) -> None:
    from pipeline.rebuild import RebuildFailed

    source, root = workspace
    with pytest.raises(RebuildFailed):
        run_pipeline(source, root, log="Using LUA script: /usr/share/valhalla/graph.lua")


def test_a_tile_build_without_elevation_fails_the_build(workspace, states) -> None:
    """Caching the HGT data is not the same as using it: with no elevation
    directory every hills dial is inert and the grade cap has nothing to read."""
    from pipeline.rebuild import RebuildFailed

    source, root = workspace
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, grade=0.0)
    assert "elevation directory" in str(caught.value.cause)


def test_validation_failure_leaves_live_untouched(workspace, states) -> None:
    """Everything before the swap writes only to staging, so a failed rebuild
    must leave the served schema exactly as it was."""
    source, root = workspace
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO live.segment "
            "(osm_way_id, ordinal, geometry, stress_tier, stress_rule) VALUES "
            "(999, 0, ST_GeomFromText('LINESTRING(-77 38.9,-77.01 38.91)',4326), 2, 'old')"
        )

    from pipeline.rebuild import RebuildFailed

    with pytest.raises(RebuildFailed):
        run_pipeline(source, root, grade=0.0)

    with connection.cursor() as cursor:
        cursor.execute("SELECT osm_way_id FROM live.segment")
        assert cursor.fetchall() == [(999,)]


def test_writers_refuse_to_target_the_live_schema() -> None:
    from pipeline.writers import write_segments

    with pytest.raises(ValueError, match="never target the live schema"):
        write_segments("live", [])


def test_a_rebuild_without_reference_data_refuses_to_run(workspace, states) -> None:
    """Every one of these inputs had an empty default, so the rebuild ran to
    completion and produced a plausible wrong map: the District graded against
    rural speeds, no volume anywhere, the e-bike variant a copy of standard.
    Nothing raised. Failing here is the point."""
    from pipeline.rebuild import RebuildFailed, Stage, run_rebuild
    from pipeline.run import RebuildContext, build_handlers

    source, root = workspace
    context = RebuildContext(
        source_pbf=source, work_dir=root / "work", reference_dir=root / "absent"
    )
    handlers = build_handlers(
        context, run=lambda c: "", sample_grade=lambda: 0.1, sample_derived_tag=lambda: "yes"
    )
    with pytest.raises(RebuildFailed) as caught:
        run_rebuild(handlers, skip=frozenset({Stage.SWAP, Stage.RECONCILE}))
    assert caught.value.stage is Stage.LOAD_REFERENCE_DATA


def test_a_missing_handler_raises_rather_than_being_skipped() -> None:
    """Silently continuing made an omitted stage indistinguishable from a
    deliberate one: the report said the rebuild ran, and its segments simply had
    no jurisdiction on them."""
    from pipeline.rebuild import Stage, StageNotImplemented, run_rebuild

    with pytest.raises(StageNotImplemented, match="fetch_extract"):
        run_rebuild({}, skip=frozenset())
    assert Stage.FETCH_EXTRACT


def test_the_ebike_variant_is_not_a_copy_of_standard(workspace, states) -> None:
    """inject()'s result was computed and discarded, so the e-bike extract was
    byte-identical to standard and an e-bike route could run where e-bikes are
    barred - the app asserting a legality it has no basis for."""
    from pipeline.extract import read_ways
    from pipeline.variants import Variant

    source, root = workspace
    context, _ = run_pipeline(source, root)

    ebike = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(Variant.EBIKE))}
    standard = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(Variant.STANDARD))}
    assert ebike[400].get("bicycle") == "no", "an e-bike-barred way must be barred here"
    assert standard[400].get("bicycle") != "no", "and not on the standard variant"


def test_stress_reaches_the_extract_the_tiles_are_built_from(workspace, states) -> None:
    """Classification ran after the tiles were built, so the tag transform read
    a tier that did not exist yet and the graph carried no stress at all."""
    from pipeline.extract import read_ways
    from pipeline.variants import Variant

    source, root = workspace
    context, _ = run_pipeline(source, root)

    tags = {w.osm_id: w.tags for w in read_ways(context.variant_pbf(Variant.STANDARD))}
    assert tags[100].get("rm:stress_tier"), "every way must carry its tier"
    assert tags[200].get("rm:trail_class") == "yes"


def test_a_sidepath_only_bridge_is_dropped_from_the_no_trail_variant(workspace, states) -> None:
    """The id set was plumbed and never populated, and the lookup read a tag no
    real way carries - so the router could hand a thousand-person field a bridge
    sidewalk with no way off it mid-span."""
    from pipeline.extract import read_ways
    from pipeline.variants import Variant

    source, root = workspace
    context, _ = run_pipeline(source, root, sidepath=(500,))

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
    context, _ = run_pipeline(source, root, volume=volume)
    assert context.aadt_by_way.get(100) == (900, "state")
    assert context.stress_by_way[100].volume_source == "state"


def test_a_transform_that_loads_but_does_nothing_fails_the_build(workspace, states) -> None:
    """The log line proves a script was loaded; it does not prove the script did
    anything. Only reading a known edge back proves the derived tags survived."""
    from pipeline.rebuild import RebuildFailed

    source, root = workspace
    with pytest.raises(RebuildFailed) as caught:
        run_pipeline(source, root, derived=None)
    assert "produced nothing usable" in str(caught.value.cause)
