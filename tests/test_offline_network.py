"""The road network a phone searches with no signal (pipeline.offline_network, 2026-11-12)."""

from __future__ import annotations

import json
import math

import pytest

from core import offline_network, ratelimit
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


def test_level_factors_rise_with_stress_and_follow_the_ride_type(settings):
    from core.offline_network import level_factors

    calm = level_factors("novice")
    fast = level_factors("fast")
    assert len(calm) == 11
    assert calm[2] == 1.0
    assert calm[2] <= calm[6] < calm[8] < calm[10]
    assert calm[10] >= 2 * calm[8]
    # A calmer ride type prices LTS 3 higher than a fast one.
    assert calm[6] > fast[6]
    # An unknown ride type is priced as Default.
    assert level_factors("no-such-type") == level_factors("default")


# --- POST /api/offline/network: a real route's line, and load protection ------------------------

api_db = pytest.mark.django_db(transaction=True)


def _line(points: int, east_m: float = 30_000) -> list[list[float]]:
    """`points` points running `east_m` east across DC, six decimals as the phone sends."""
    k = 111_195 * math.cos(math.radians(38.9))
    return [[round(-77.05 + (i * east_m / (points - 1)) / k, 6), 38.9] for i in range(points)]


def _post(client, line, **headers):
    return client.post(
        "/api/offline/network",
        data=json.dumps({"line": line, "preset": "default"}),
        content_type="application/json",
        **headers,
    )


@api_db
def test_a_real_routes_line_is_taken(client) -> None:
    """1,500 points, what the phone sends at most, is about 35 KB: over the 8 KB every other
    JSON endpoint takes, so it was refused (400) before the endpoint took a body of its own
    size and every rider went without a way back (the v0.26.0 release review)."""
    line = _line(1500)
    assert len(json.dumps({"line": line})) > 8 * 1024
    answer = _post(client, line, HTTP_X_FORWARDED_FOR="198.51.100.70")
    # No map built in the test database: not built, never refused for its size.
    assert answer.status_code in (200, 503), answer.content
    assert answer.status_code == 200 or answer.json()["error"] in ("not_built", "too_slow")


@api_db
def test_a_line_too_long_or_too_many_points_is_refused(client) -> None:
    too_far = _line(50, east_m=offline_network.MAX_LINE_M + 10_000)
    assert _post(client, too_far, HTTP_X_FORWARDED_FOR="198.51.100.71").status_code == 400
    too_many = _line(offline_network.MAX_LINE_POINTS + 1)
    assert _post(client, too_many, HTTP_X_FORWARDED_FOR="198.51.100.72").status_code == 400


@api_db
def test_one_fetch_at_a_time_per_client_from_the_tile_pool(client) -> None:
    """Load protection: one fetch per client and no more at once than the tile pool's slots,
    so a burst never holds more workers than the pools already allow. Before, a client's
    burst inside the per-minute limit ran every fetch at once."""
    from test_route_api import hold_slots

    limit = ratelimit.OFFLINE_NETWORK_IN_FLIGHT
    assert limit.total_class == ratelimit.TILES_IN_FLIGHT.total_class
    key = ratelimit._client_lock_id(ratelimit.client_key("198.51.100.73"))
    mine = hold_slots([(ratelimit._LOCK_CLASS_CLIENT + limit.scope_id * 64, key)])
    try:
        refused = _post(client, _line(10), HTTP_X_FORWARDED_FOR="198.51.100.73")
        other = _post(client, _line(10), HTTP_X_FORWARDED_FOR="198.51.100.74")
    finally:
        mine.close()
    assert refused.status_code == 429 and int(refused["Retry-After"]) >= 1
    assert other.status_code != 429
    pool = hold_slots([(limit.total_class, s) for s in range(limit.total)])
    try:
        full = _post(client, _line(10), HTTP_X_FORWARDED_FOR="198.51.100.75")
    finally:
        pool.close()
    assert full.status_code == 503 and int(full["Retry-After"]) >= 1
