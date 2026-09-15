"""The pipeline, wired and run end to end.

Until this existed, every module in `pipeline/` was called only from its own
unit test: there was no OSM reader, no writer, no handler set, and the stage
ordering tests asserted an enum against itself. This runs a real PBF through
the real stages into a real staging schema.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import osmium
import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.db import connection

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
    yield
    Jurisdiction.objects.all().delete()


@pytest.fixture
def workspace(segment_schemas):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.osm.pbf"
        build_toy_extract(source)
        yield source, root


def run_pipeline(source: Path, root: Path, *, grade: float = 0.08, log: str | None = None):
    from pipeline.rebuild import run_rebuild
    from pipeline.run import RebuildContext, build_handlers

    context = RebuildContext(source_pbf=source, work_dir=root / "work")
    default_log = "... Using LUA script: /conf/lua/graph.lua ..."
    handlers = build_handlers(
        context,
        run=lambda command: log if log is not None else default_log,
        sample_grade=lambda: grade,
    )
    report = run_rebuild(handlers)
    return context, report


def test_a_full_rebuild_populates_the_staging_schema(workspace, states) -> None:
    source, root = workspace
    context, report = run_pipeline(source, root)

    assert report.completed, "stages must have run"
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM staging.segment")
        assert cursor.fetchone()[0] == 3, "one segment per way"
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
    assert crossings[0].node_id < 0, "synthetic ids come from the reserved range"


def test_the_written_extract_carries_the_border_node_in_the_way(workspace, states) -> None:
    """Round-tripped through a real PBF: a negative node id has to survive the
    write, which nothing verified before."""
    from pipeline.extract import read_ways
    from pipeline.variants import Variant

    source, root = workspace
    context, _ = run_pipeline(source, root)

    ways = {w.osm_id: w for w in read_ways(context.variant_pbf(Variant.STANDARD))}
    assert any(node_id < 0 for node_id in ways[100].node_ids)
    assert 200 in ways, "the standard variant keeps trails"


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
