"""Reading and writing the OSM extract.

These run against real PBF files rather than fixtures shaped like one. The bug
that motivated the first test survived a full unit suite because every test built
the parallel lists by hand, in step, which is the one case the code got right.
"""

from __future__ import annotations

from pathlib import Path

import osmium
import pytest

from pipeline.extract import Way, read_ways, write_extract


def write_pbf(path: Path, nodes: list[tuple[int, float, float]], ways: list[tuple[int, list[int]]]):
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, lon, lat in nodes:
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        for way_id, refs in ways:
            writer.add_way(
                osmium.osm.mutable.Way(
                    id=way_id, nodes=refs, tags={"highway": "residential"}, version=1
                )
            )
    finally:
        writer.close()


def test_a_way_whose_nodes_are_partly_outside_the_clip_keeps_its_node_indices(tmp_path) -> None:
    """The defect that put border nodes in the wrong place.

    A clipped extract carries no location for nodes outside it. The coordinate
    list is therefore shorter than the node list, and an index into one is wrong
    for the other - but only on ways at the edge of the clip, so a suite built on
    whole ways never sees it. Here node 3 has no location: the located nodes are
    at node-list indices 0, 1 and 3, not 0, 1 and 2.
    """
    source = tmp_path / "clipped.osm.pbf"
    write_pbf(
        source,
        nodes=[(1, -77.0, 38.9), (2, -77.01, 38.9), (4, -77.03, 38.9)],
        ways=[(100, [1, 2, 3, 4])],
    )

    (way,) = read_ways(source)
    assert way.node_ids == [1, 2, 3, 4]
    assert len(way.coordinates) == 3
    assert way.located == [0, 1, 3]
    assert [index for index, _, _ in way.located_points()] == [0, 1, 3]


def test_a_whole_way_indexes_straight_through(tmp_path) -> None:
    source = tmp_path / "whole.osm.pbf"
    write_pbf(
        source,
        nodes=[(1, -77.0, 38.9), (2, -77.01, 38.9), (3, -77.02, 38.9)],
        ways=[(100, [1, 2, 3])],
    )

    (way,) = read_ways(source)
    assert way.located == [0, 1, 2]


def test_located_points_refuses_lists_that_have_come_apart() -> None:
    """Built together by read_ways. A caller that sets one without the other is
    reintroducing the defect, and should hear about it here rather than in the
    geometry of a tile."""
    way = Way(osm_id=1, tags={}, node_ids=[1, 2, 3], coordinates=[(0.0, 0.0), (1.0, 1.0)])
    with pytest.raises(ValueError, match="must stay in step"):
        way.located_points()


def test_minted_nodes_are_appended_after_every_source_node(tmp_path) -> None:
    """An OSM file is nodes, then ways, then relations, ascending by id within
    each block. valhalla_build_tiles rejects anything else outright."""
    from pipeline.borders import SYNTHETIC_NODE_ID_FLOOR

    source = tmp_path / "source.osm.pbf"
    destination = tmp_path / "written.osm.pbf"
    write_pbf(
        source,
        nodes=[(1, -77.0, 38.9), (2, -77.01, 38.9)],
        ways=[(100, [1, 2])],
    )
    minted = SYNTHETIC_NODE_ID_FLOOR
    write_extract(
        source,
        destination,
        way_tags={},
        new_nodes=[(minted, -77.005, 38.9, {"barrier": "border_control"})],
        way_node_ids={100: [1, minted, 2]},
    )

    seen: list[int] = []

    class Order(osmium.SimpleHandler):
        def node(self, n) -> None:  # noqa: N802
            seen.append(n.id)

    Order().apply_file(str(destination))
    assert seen == [1, 2, minted]


def test_a_minted_id_below_the_source_ids_is_refused(tmp_path) -> None:
    """Appending only keeps the block sorted while the reserved range stays above
    every id OSM has issued. If that stops being true the extract is silently
    unsorted and the tile build fails a stage later, with a message that says
    nothing about node ids."""
    source = tmp_path / "source.osm.pbf"
    write_pbf(source, nodes=[(500, -77.0, 38.9)], ways=[(100, [500])])

    with pytest.raises(ValueError, match="needs raising"):
        write_extract(
            source,
            tmp_path / "written.osm.pbf",
            way_tags={},
            new_nodes=[(499, -77.005, 38.9, {})],
            way_node_ids={},
        )


def test_the_segment_ordinal_is_a_function_of_position_and_nothing_else(tmp_path) -> None:
    """The segment key is (way id, ordinal), so an ordinal that moved would
    renumber segments week to week and orphan every anchor attached to them -
    comments, issues, closures, cue overrides, reviewer penalties.

    Stated by splitting the same way at two different widths and by clipping it:
    the ordinal of a piece depends on where it starts along the way, not on how
    many pieces there are or on what else the extract contains.
    """
    from pipeline.extract import Way, iter_segments

    coordinates = [(-77.0 + i * 0.001, 38.9) for i in range(10)]
    way = Way(osm_id=1, tags={"highway": "residential"}, node_ids=list(range(10)))
    way.coordinates = coordinates
    way.located = list(range(10))

    pieces = list(iter_segments(way, max_points=4))
    assert [ordinal for ordinal, _ in pieces] == [0, 1, 2]
    # Each piece starts where the previous one ended, so the geometry is covered
    # once and the ordinals are contiguous from zero.
    assert pieces[0][1][0] == coordinates[0]
    assert pieces[1][1][0] == pieces[0][1][-1]
    assert pieces[2][1][0] == pieces[1][1][-1]
    assert pieces[-1][1][-1] == coordinates[-1]


def test_the_ordinal_does_not_depend_on_the_rest_of_the_extract(tmp_path) -> None:
    """The same way, read from a file with more in it, numbers identically."""
    from pipeline.extract import iter_segments, read_ways

    lonely = tmp_path / "one.osm.pbf"
    crowded = tmp_path / "many.osm.pbf"
    target = [(1, [1, 2, 3])]
    nodes = [(1, -77.0, 38.9), (2, -77.001, 38.9), (3, -77.002, 38.9)]
    write_pbf(lonely, nodes=nodes, ways=target)
    write_pbf(
        crowded,
        nodes=[*nodes, (4, -76.9, 38.8), (5, -76.901, 38.8)],
        ways=[(50, [4, 5]), *target, (200, [4, 5])],
    )

    def ordinals(path):
        way = next(w for w in read_ways(path) if w.osm_id == 1)
        return [ordinal for ordinal, _ in iter_segments(way, max_points=2)]

    assert ordinals(lonely) == ordinals(crowded) == [0, 1]
