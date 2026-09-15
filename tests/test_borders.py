"""Border-control node insertion."""

from __future__ import annotations

import pytest

from pipeline.borders import (
    SYNTHETIC_NODE_ID_CEILING,
    SYNTHETIC_NODE_ID_FLOOR,
    BorderNode,
    NodeIdExhausted,
    SyntheticNodeIds,
    find_state_crossings,
    insert_nodes_into_way,
)


# A toy border on the 77th meridian: DC to the east, VA to the west.
def state_at(lon: float, lat: float) -> str | None:
    if lat < 38.0:
        return None  # outside the clip polygon
    return "DC" if lon >= -77.0 else "VA"


def points(*coordinates: tuple[float, float]) -> list[tuple[int, float, float]]:
    """Consecutive located nodes, which is the ordinary case."""
    return [(index, lon, lat) for index, (lon, lat) in enumerate(coordinates)]


def test_crossing_is_found_and_located_on_the_line() -> None:
    nodes = list(
        find_state_crossings(
            42, points((-76.99, 38.9), (-77.01, 38.9)), state_at, SyntheticNodeIds()
        )
    )
    assert len(nodes) == 1
    assert nodes[0].lon == pytest.approx(-77.0, abs=1e-5)
    assert {nodes[0].state_a, nodes[0].state_b} == {"DC", "VA"}


def test_way_id_is_never_altered() -> None:
    """Three mechanisms key on OSM way id. Splitting the way mints a new id for
    one half and silently breaks all of them."""
    nodes = list(
        find_state_crossings(
            42, points((-76.99, 38.9), (-77.01, 38.9)), state_at, SyntheticNodeIds()
        )
    )
    assert all(node.osm_way_id == 42 for node in nodes)


def test_the_insertion_index_points_into_the_node_list_not_the_coordinate_list() -> None:
    """The one that produced a graph routing almost correctly.

    A clipped extract carries no location for nodes outside it, so a way's
    coordinate list is shorter than its node list. The index used to come from
    enumerating coordinates and was then applied to node ids, which are a
    different list on every way at the edge of the clip. Here nodes 0 and 1 have
    no location; the crossing between the nodes at indices 2 and 3 must be
    reported as index 2, not as index 0.
    """
    located = [(2, -76.99, 38.9), (3, -77.01, 38.9)]
    (node,) = find_state_crossings(42, located, state_at, SyntheticNodeIds())
    assert node.insert_after == 2

    way = [10, 20, 30, 40]
    assert insert_nodes_into_way(way, [node]) == [10, 20, 30, node.node_id, 40]


def test_a_gap_in_the_located_nodes_is_not_a_crossing() -> None:
    """Where the extract has a hole, where along it the border falls is unknown.

    Guessing would put a barrier node - and so an edge break - at an invented
    place, on exactly the ways the clip already cut.
    """
    across_a_gap = [(0, -76.99, 38.9), (4, -77.01, 38.9)]
    assert list(find_state_crossings(42, across_a_gap, state_at, SyntheticNodeIds())) == []


def test_an_index_past_the_end_of_the_way_is_refused() -> None:
    node = BorderNode(
        SYNTHETIC_NODE_ID_FLOOR, 0.0, 0.0, 42, insert_after=9, state_a="DC", state_b="VA"
    )
    with pytest.raises(IndexError, match="which has 4 nodes"):
        insert_nodes_into_way([10, 20, 30, 40], [node])


def test_node_ids_sit_above_every_id_osm_has_issued() -> None:
    """Not negative, which is the editor convention and what this used to use.

    valhalla_build_tiles reads node ids as unsigned, so a negative id arrives as
    a value near 2**64 and the parse aborts with "Detected unsorted input data"
    before a single tile is written. A reserved range above real ids appends to a
    sorted extract and stays sorted.
    """
    allocator = SyntheticNodeIds()
    ids = [allocator.allocate() for _ in range(3)]
    assert ids == [
        SYNTHETIC_NODE_ID_FLOOR,
        SYNTHETIC_NODE_ID_FLOOR + 1,
        SYNTHETIC_NODE_ID_FLOOR + 2,
    ]
    assert all(i > 0 for i in ids)
    # OSM's highest node id is around 1.3e10 and grows by roughly 2e9 a year.
    assert SYNTHETIC_NODE_ID_FLOOR > 100 * 10**9
    # Below the point where a JSON round trip would start losing precision.
    assert SYNTHETIC_NODE_ID_CEILING < 2**53
    assert all(SyntheticNodeIds.is_synthetic(i) for i in ids)
    assert not SyntheticNodeIds.is_synthetic(12345)
    assert not SyntheticNodeIds.is_synthetic(-1)


def test_allocator_refuses_to_leave_its_range() -> None:
    allocator = SyntheticNodeIds(start=SYNTHETIC_NODE_ID_CEILING)
    allocator.allocate()
    with pytest.raises(NodeIdExhausted):
        allocator.allocate()


def test_allocator_rejects_a_start_outside_the_range() -> None:
    with pytest.raises(ValueError, match="reserved synthetic range"):
        SyntheticNodeIds(start=1)
    with pytest.raises(ValueError, match="reserved synthetic range"):
        SyntheticNodeIds(start=-1)


def test_insertion_preserves_order_with_multiple_crossings() -> None:
    """Applied forwards, each insertion shifts every later index by one and the
    nodes land in the wrong places - a graph that routes almost correctly."""
    way = [10, 20, 30, 40]
    first, second = SYNTHETIC_NODE_ID_FLOOR, SYNTHETIC_NODE_ID_FLOOR + 1
    nodes = [
        BorderNode(first, 0.0, 0.0, 42, insert_after=0, state_a="DC", state_b="VA"),
        BorderNode(second, 0.0, 0.0, 42, insert_after=2, state_a="VA", state_b="DC"),
    ]
    assert insert_nodes_into_way(way, nodes) == [10, first, 20, 30, second, 40]


def test_vertex_outside_coverage_is_not_a_crossing() -> None:
    """A vertex in no known state is skipped rather than guessed at."""
    nodes = list(
        find_state_crossings(
            42, points((-76.99, 38.9), (-76.99, 37.0)), state_at, SyntheticNodeIds()
        )
    )
    assert nodes == []


def test_border_node_denies_no_access() -> None:
    """The node exists to be charged for, not to refuse passage. A Lua mapping
    that added an access restriction here would make every crossing unroutable."""
    node = BorderNode(SYNTHETIC_NODE_ID_FLOOR, 0.0, 0.0, 42, 0, "DC", "VA")
    assert node.tags == {"barrier": "border_control"}
    assert "bicycle" not in node.tags
    assert "access" not in node.tags
