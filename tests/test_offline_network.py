"""The road network a phone searches with no signal (pipeline.offline_network; off-grid riding, 2026-11-12)."""

from __future__ import annotations

from pipeline.offline_network import (
    AVOID_LEVEL2,
    EDGE_ONEWAY,
    EDGE_UNPAVED,
    EDGE_WALK,
    OfflineWay,
    bicycle_direction,
    level2_of,
    offline_way,
    split_edges,
)


def test_bicycle_direction_reads_oneway_contraflow_and_its_own_tag():
    assert bicycle_direction({}) == 0
    assert bicycle_direction({"oneway": "yes"}) == 1
    assert bicycle_direction({"oneway": "-1"}) == -1
    assert bicycle_direction({"oneway": "yes", "oneway:bicycle": "no"}) == 0
    assert bicycle_direction({"oneway": "yes", "cycleway": "opposite_lane"}) == 0
    assert bicycle_direction({"oneway": "yes", "cycleway:left": "opposite_track"}) == 0
    assert bicycle_direction({"junction": "roundabout"}) == 1
    assert bicycle_direction({"junction": "roundabout", "oneway": "no"}) == 0
    assert bicycle_direction({"oneway:bicycle": "-1"}) == -1


def test_levels_are_doubled_with_half_steps_and_avoid_at_ten():
    assert level2_of(1, False) == 2
    assert level2_of(3, True) == 7
    assert level2_of(4, True) == 9
    assert level2_of(5, False) == AVOID_LEVEL2
    assert level2_of(5, True) == AVOID_LEVEL2


def _way(**kw):
    base = dict(
        osm_id=1,
        tags={"highway": "residential", "name": "A Street"},
        node_ids=[10, 11, 12],
        located=[0, 1, 2],
        coordinates=[(-77.0, 38.9), (-77.001, 38.9), (-77.002, 38.9)],
        tier=2,
        half=False,
        access_reason=None,
        walk_bike=False,
        unpaved=False,
        mtb_only=False,
    )
    base.update(kw)
    return offline_way(
        base.pop("osm_id"),
        base.pop("tags"),
        base.pop("node_ids"),
        base.pop("located"),
        base.pop("coordinates"),
        **base,
    )


def test_closed_and_singletrack_ways_are_left_out():
    assert _way() is not None
    assert _way(access_reason="private") is None
    assert _way(access_reason="motorway") is None
    assert _way(access_reason="override_open") is not None
    assert _way(access_reason="bicycle_use_sidepath") is not None
    assert _way(mtb_only=True) is None
    assert _way(tags={"name": "No highway"}) is None
    assert _way(coordinates=[(-77.0, 38.9)], located=[0], node_ids=[10]) is None


def test_flags_and_located_nodes():
    way = _way(walk_bike=True, unpaved=True, node_ids=[9, 10, 11, 12], located=[1, 2, 3])
    assert way.flags == EDGE_WALK | EDGE_UNPAVED
    assert way.node_ids == (10, 11, 12)
    assert _way(tags={"highway": "steps"}).flags & EDGE_WALK


def _ow(osm_id, nodes, direction=0, name=None):
    return OfflineWay(
        osm_id=osm_id,
        node_ids=tuple(nodes),
        coordinates=tuple((-77.0 + n * 0.001, 38.9) for n in nodes),
        level2=2,
        flags=0,
        direction=direction,
        name=name,
    )


def test_ways_are_cut_at_shared_nodes_only():
    # Way 1 runs 1-2-3-4; way 2 meets it at 3. Node 2 is no junction.
    edges = split_edges([_ow(1, [1, 2, 3, 4]), _ow(2, [3, 7])])
    pairs = sorted((e.a_node, e.b_node) for e in edges)
    assert pairs == [(1, 3), (3, 4), (3, 7)]
    first = next(e for e in edges if (e.a_node, e.b_node) == (1, 3))
    assert len(first.coordinates) == 3
    assert 150 < first.length_m < 200


def test_one_way_against_the_way_is_turned_round():
    (edge,) = split_edges([_ow(1, [1, 2], direction=-1)])
    assert (edge.a_node, edge.b_node) == (2, 1)
    assert edge.flags & EDGE_ONEWAY
    (both,) = split_edges([_ow(1, [1, 2])])
    assert not both.flags & EDGE_ONEWAY


def test_a_loop_way_keeps_its_ring():
    edges = split_edges([_ow(1, [1, 2, 3, 1])])
    assert len(edges) == 1
    assert edges[0].a_node == edges[0].b_node == 1
