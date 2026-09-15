"""Border-control node insertion."""

from __future__ import annotations

import pytest

from pipeline.borders import (
    SYNTHETIC_NODE_ID_CEILING,
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


def test_crossing_is_found_and_located_on_the_line() -> None:
    nodes = list(
        find_state_crossings(42, [(-76.99, 38.9), (-77.01, 38.9)], state_at, SyntheticNodeIds())
    )
    assert len(nodes) == 1
    assert nodes[0].lon == pytest.approx(-77.0, abs=1e-5)
    assert {nodes[0].state_a, nodes[0].state_b} == {"DC", "VA"}


def test_way_id_is_never_altered() -> None:
    """Three mechanisms key on OSM way id. Splitting the way mints a new id for
    one half and silently breaks all of them."""
    nodes = list(
        find_state_crossings(42, [(-76.99, 38.9), (-77.01, 38.9)], state_at, SyntheticNodeIds())
    )
    assert all(node.osm_way_id == 42 for node in nodes)


def test_node_ids_are_inside_the_reserved_negative_range() -> None:
    """Real OSM node ids are positive, so a negative range cannot collide."""
    allocator = SyntheticNodeIds()
    ids = [allocator.allocate() for _ in range(3)]
    assert ids == [-1, -2, -3]
    assert all(SyntheticNodeIds.is_synthetic(i) for i in ids)
    assert not SyntheticNodeIds.is_synthetic(12345)


def test_allocator_refuses_to_leave_its_range() -> None:
    from pipeline.borders import SYNTHETIC_NODE_ID_FLOOR

    allocator = SyntheticNodeIds(start=SYNTHETIC_NODE_ID_FLOOR)
    allocator.allocate()
    with pytest.raises(NodeIdExhausted):
        allocator.allocate()


def test_allocator_rejects_a_start_outside_the_range() -> None:
    with pytest.raises(ValueError, match="reserved synthetic range"):
        SyntheticNodeIds(start=1)


def test_insertion_preserves_order_with_multiple_crossings() -> None:
    """Applied forwards, each insertion shifts every later index by one and the
    nodes land in the wrong places - a graph that routes almost correctly."""
    way = [10, 20, 30, 40]
    nodes = [
        BorderNode(-1, 0.0, 0.0, 42, insert_after=0, state_a="DC", state_b="VA"),
        BorderNode(-2, 0.0, 0.0, 42, insert_after=2, state_a="VA", state_b="DC"),
    ]
    assert insert_nodes_into_way(way, nodes) == [10, -1, 20, 30, -2, 40]


def test_vertex_outside_coverage_is_not_a_crossing() -> None:
    """A vertex in no known state is skipped rather than guessed at."""
    nodes = list(
        find_state_crossings(42, [(-76.99, 38.9), (-76.99, 37.0)], state_at, SyntheticNodeIds())
    )
    assert nodes == []


def test_border_node_denies_no_access() -> None:
    """The node exists to be charged for, not to refuse passage. A Lua mapping
    that added an access restriction here would make every crossing unroutable."""
    node = BorderNode(-1, 0.0, 0.0, 42, 0, "DC", "VA")
    assert node.tags == {"barrier": "border_control"}
    assert "bicycle" not in node.tags
    assert "access" not in node.tags


def test_ceiling_is_negative() -> None:
    assert SYNTHETIC_NODE_ID_CEILING < 0
