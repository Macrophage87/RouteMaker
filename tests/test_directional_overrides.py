"""A directional access override against the crossings fixture, end to end.

The fixture's legality column is bidirectional, and its `true` half exists to
correct OSM's own `bicycle=no` on a bridge's roadway. An approved row that
overrules it in one direction - `bicycle:forward=no` - has said nothing about
the other, so the fixture keeps its say there. These run the production
APPLY_OVERRIDES and INJECT_TAGS handlers, read each variant extract back with
the real reader, and hand the way's tags to the shipped entry point under
LuaJIT over the vendored Valhalla transform, so what is asserted is the access
Valhalla would derive rather than the tags that lead to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rebuild_fixtures import write_reference_data
from test_lua_remap import _lua_driver

from pipeline.overrides import Override

BRIDGE = 300


def _write_bridge_extract(path: Path, **extra: str) -> None:
    """One fixture bridge whose OSM tagging bars bicycles on the roadway - the
    shape the fixture's `true` half exists to correct."""
    import osmium

    Path(path).unlink(missing_ok=True)  # osmium refuses to overwrite
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, (lon, lat) in {1: (-77.05, 38.88), 2: (-77.04, 38.88)}.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=BRIDGE,
                nodes=[1, 2],
                version=1,
                tags={
                    "highway": "secondary",
                    "bridge": "yes",
                    "layer": "1",
                    "name": "Probe Bridge",
                    **extra,
                },
            )
        )
    finally:
        writer.close()


def _extracts(tmp_path, rows, *, legal: bool, source_tags: dict[str, str]):
    """The variant extracts the two production stages leave on disk, and the
    context they ran in."""
    from pipeline.extract import read_ways
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, ReferenceData, build_handlers
    from pipeline.variants import Variant

    source_pbf = tmp_path / "source.osm.pbf"
    _write_bridge_extract(source_pbf, **source_tags)
    reference_dir = write_reference_data(tmp_path, legality={BRIDGE: legal})

    context = RebuildContext(
        source_pbf=source_pbf,
        work_dir=tmp_path / "work",
        reference_dir=reference_dir,
        tiles_dir=tmp_path / "tiles",
    )
    context.ways = read_ways(source_pbf)
    context.ways_by_id = {way.osm_id: way for way in context.ways}
    context.reference = ReferenceData.load(reference_dir, context.ways)

    handlers = build_handlers(context, load_overrides=lambda: rows)
    handlers[Stage.APPLY_OVERRIDES]()
    handlers[Stage.INJECT_TAGS]()

    by_variant = {
        variant: {way.osm_id: dict(way.tags) for way in read_ways(context.variant_pbf(variant))}
        for variant in Variant
    }
    return by_variant, context


def _lua_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _valhalla_access(tags: dict[str, str]) -> tuple[bool, bool]:
    """(bike_forward, bike_backward) as the shipped transform derives them."""
    table = ", ".join(f"[{_lua_string(k)}] = {_lua_string(v)}" for k, v in sorted(tags.items()))
    result = _lua_driver(
        'dofile("lua/graph.lua")\n'
        f"local filter, out = ways_proc({{ {table} }}, {len(tags)})\n"
        'io.stdout:write(tostring(filter), " ", tostring(out.bike_forward), " ",\n'
        '  tostring(out.bike_backward), "\\n")\n'
    )
    assert result.returncode == 0, result.stderr
    filter_value, forward, backward = result.stdout.split()
    assert filter_value == "0", f"upstream dropped the way: {tags}"
    assert {forward, backward} <= {"true", "false"}, result.stdout
    return forward == "true", backward == "true"


# (source tags beyond the bridge, fixture legality, the approved row's value,
#  expected (bike_forward, bike_backward), whether the fixture's tag survives).
CASES = {
    # The reviewer's probe: the row bars one direction of a bridge the fixture
    # opens over OSM's own bar. Withheld wholesale this gave (False, False).
    "forward-only row keeps the grant backward": (
        {"bicycle": "no"},
        True,
        [{"bicycle:forward": "no"}],
        (False, True),
        True,
    ),
    "backward-only row keeps the grant forward": (
        {"bicycle": "no"},
        True,
        [{"bicycle:backward": "no"}],
        (True, False),
        True,
    ),
    # The fixture's `false` half survives in the other direction too: a row
    # opening one direction of a bridge the fixture bars has not opened both.
    "forward-only opening keeps the fixture's bar backward": (
        {},
        False,
        [{"bicycle:forward": "yes"}],
        (True, False),
        True,
    ),
    "plain bicycle row supersedes both directions": (
        {"bicycle": "no"},
        True,
        [{"bicycle": "no"}],
        (False, False),
        False,
    ),
    "plain bicycle opening supersedes the fixture's bar both ways": (
        {},
        False,
        [{"bicycle": "yes"}],
        (True, True),
        False,
    ),
    "a row writing both directions supersedes both": (
        {"bicycle": "no"},
        True,
        [{"bicycle:forward": "no", "bicycle:backward": "yes"}],
        (False, True),
        False,
    ),
    "two rows, one per direction, supersede both": (
        {},
        False,
        [{"bicycle:forward": "yes"}, {"bicycle:backward": "yes"}],
        (True, True),
        False,
    ),
    # A one-way bridge: the row bars the contraflow direction, which the oneway
    # already bars, and the fixture's grant still opens the direction of travel.
    "oneway, backward-only row keeps the grant forward": (
        {"bicycle": "no", "oneway": "yes"},
        True,
        [{"bicycle:backward": "no"}],
        (True, False),
        True,
    ),
    "oneway, forward-only row bars the only direction": (
        {"bicycle": "no", "oneway": "yes"},
        True,
        [{"bicycle:forward": "no"}],
        (False, False),
        True,
    ),
    # The row opens contraflow on a one-way bridge the fixture opens: both.
    "oneway, backward opening keeps the grant forward": (
        {"bicycle": "no", "oneway": "yes"},
        True,
        [{"bicycle:backward": "yes"}],
        (True, True),
        True,
    ),
}


@pytest.mark.django_db
@pytest.mark.parametrize("case", list(CASES))
def test_a_directional_override_keeps_the_fixture_in_the_other_direction(tmp_path, case) -> None:
    from pipeline.variants import Variant

    source_tags, legal, values, expected, fixture_survives = CASES[case]
    rows = [Override("access", BRIDGE, value) for value in values]
    by_variant, context = _extracts(tmp_path, rows, legal=legal, source_tags=source_tags)

    assert set(by_variant) == set(Variant)
    for variant, ways in by_variant.items():
        tags = ways[BRIDGE]
        # What Valhalla derives first, so the probe fails on the access it
        # would serve rather than on the tag that leads to it.
        assert _valhalla_access(tags) == expected, (
            f"{variant.value}: Valhalla derives the wrong bicycle access from {tags}"
        )
        carried = "rm:bridge_bicycle" in tags
        assert carried is fixture_survives, (
            f"{variant.value}: the fixture's legality {'is' if carried else 'is not'} "
            f"handed to the transform: {tags}"
        )
        for value in values:
            for key, written in value.items():
                assert tags.get(key) == written, f"{variant.value}: the approved row is lost"

    report = context.override_report
    assert report.fixture_rows_superseded == 1, "the overruled fixture row is reported"


@pytest.mark.django_db
def test_the_info_line_names_the_direction_overruled(tmp_path, caplog) -> None:
    """An operator reading the rebuild log can tell a one-direction overrule
    from a wholesale one, since only the second withholds the fixture's row."""
    import logging

    with caplog.at_level(logging.INFO, logger="pipeline.run"):
        _extracts(
            tmp_path,
            [Override("access", BRIDGE, {"bicycle:backward": "no"})],
            legal=True,
            source_tags={"bicycle": "no"},
        )
    lines = [r.getMessage() for r in caplog.records if "crossings fixture" in r.getMessage()]
    assert len(lines) == 1, lines
    assert str(BRIDGE) in lines[0]
    assert "backward" in lines[0] and "forward" not in lines[0].replace("backward", ""), lines[0]
