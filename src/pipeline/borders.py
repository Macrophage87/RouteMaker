"""Inserting border-control nodes where a way crosses a state line.

Valhalla has no notion of a state crossing, but it does break an edge at any node
carrying a barrier tag, and `barrier=border_control` produces a border-control
node type that the existing `country_crossing_cost` and `country_crossing_penalty`
request options act on. That turns a state-crossing dial into a per-request
option with no engine fork.

The way is never split. Three mechanisms key on OSM way id - the segment table's
(way id, ordinal) key, the trace_attributes stats join on edge.way_id, and
post-swap anchor reconciliation - and a split mints a new id for one half,
silently breaking all three. Derived ids would also drift week to week as the
clip polygon moved. So the node goes into the existing way's node list at the
intersection point and the way keeps its identity.

Synthetic node ids come from a reserved *positive* range above every id OSM has
issued. Negative ids are the established convention for locally generated
features in editors, and the first version used them - but `valhalla_build_tiles`
reads node ids as unsigned, so a negative id arrives as a value near 2**64 and
the parse aborts with "Detected unsorted input data" before a single tile is
written. The reserved range sits above real ids instead, so the synthetic nodes
append to a sorted extract and stay sorted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

# Reserved range for nodes this pipeline mints. Chosen to sit above every node id
# OSM has issued - the highest is around 1.3e10, which is 2**33.6 - with room for
# decades of growth before the floor is approached, and far below the 2**53 where
# a JSON round trip would start losing precision.
SYNTHETIC_NODE_ID_FLOOR = 2**40
SYNTHETIC_NODE_ID_CEILING = 2**41 - 1

BORDER_CONTROL_TAGS = {"barrier": "border_control"}


class NodeIdExhausted(RuntimeError):
    """The reserved synthetic range ran out, which should be unreachable."""


@dataclass(frozen=True)
class BorderNode:
    """A node to insert, and the two states it separates."""

    node_id: int
    lon: float
    lat: float
    osm_way_id: int
    # Index into the way's *node id* list, after which this node is inserted.
    #
    # It used to be an index into the way's coordinate list, which is not the
    # same list: read_ways drops nodes whose location the clipped extract does
    # not carry, so on any way with a node outside the clip the two drift and the
    # border node lands somewhere else entirely. Callers now supply node-list
    # indices with the coordinates, so the two cannot come apart.
    insert_after: int
    state_a: str
    state_b: str

    @property
    def tags(self) -> dict[str, str]:
        """What the way's node carries. Bicycle access is never denied here: the
        node exists to be charged for, not to be refused, and the Lua mapping is
        verified not to add an access restriction at it."""
        return dict(BORDER_CONTROL_TAGS)


class SyntheticNodeIds:
    """Allocator for the reserved range.

    Deterministic within a rebuild and restarted each time, because the ids are
    not persistent identity: the crossings table records what each one means, and
    a rebuild reassigns them.
    """

    def __init__(self, start: int = SYNTHETIC_NODE_ID_FLOOR) -> None:
        if not SYNTHETIC_NODE_ID_FLOOR <= start <= SYNTHETIC_NODE_ID_CEILING:
            raise ValueError("start must lie inside the reserved synthetic range")
        self._next = start

    def allocate(self) -> int:
        if self._next > SYNTHETIC_NODE_ID_CEILING:
            raise NodeIdExhausted("reserved synthetic node id range exhausted")
        node_id = self._next
        self._next += 1
        return node_id

    @staticmethod
    def is_synthetic(node_id: int) -> bool:
        return SYNTHETIC_NODE_ID_FLOOR <= node_id <= SYNTHETIC_NODE_ID_CEILING


def insert_nodes_into_way(node_ids: Sequence[int], nodes: Sequence[BorderNode]) -> list[int]:
    """Return the way's node list with border nodes inserted, way id untouched.

    Insertions are applied from the end backwards so that earlier indices stay
    valid; doing it forwards shifts every later insertion point by one and puts
    the nodes in the wrong places, which is the kind of bug that produces a graph
    that routes almost correctly.
    """
    result = list(node_ids)
    for node in sorted(nodes, key=lambda n: n.insert_after, reverse=True):
        if not 0 <= node.insert_after < len(node_ids):
            raise IndexError(
                f"border node {node.node_id} wants to follow index {node.insert_after} "
                f"of way {node.osm_way_id}, which has {len(node_ids)} nodes"
            )
        result.insert(node.insert_after + 1, node.node_id)
    return result


def find_state_crossings(
    way_id: int,
    points: Sequence[tuple[int, float, float]],
    state_at: Callable[[float, float], str | None],
    allocator: SyntheticNodeIds,
    way_name: str | None = None,
) -> Iterator[BorderNode]:
    """Yield a border node wherever consecutive vertices sit in different states.

    Boundary streets are skipped entirely. Western, Eastern and Southern Avenue
    *are* the District line: the OSM centreline and the boundary polygon weave
    across each other, so a naive pass mints a string of border nodes along one
    street. Valhalla breaks an edge at every barrier node, so the way would
    fragment into dozens of stubs, inflating the maneuver list, corrupting the
    way-id trace join, and reporting twenty entries into Maryland for a ride that
    never left the curb.

    The crossing point is approximated by bisection between the two vertices
    rather than by an exact polygon intersection, which keeps this independent of
    the geometry backend and is accurate to well under a metre after a dozen
    steps. A vertex in no known state - offshore, or outside the clip polygon -
    is not a crossing and is skipped rather than guessed at.

    Each point is (index into the way's node id list, lon, lat), rather than a
    bare coordinate. The index has to travel with the coordinate: a clipped
    extract carries no location for nodes outside it, so a way's coordinate list
    is shorter than its node list and an index into one is wrong for the other.
    """
    from .jurisdiction import is_boundary_street

    if is_boundary_street(way_name):
        return

    for (index_a, lon_a, lat_a), (index_b, lon_b, lat_b) in zip(points, points[1:], strict=False):
        # Non-adjacent indices mean the extract carries no location for the nodes
        # between these two, which is how a clip cuts a way. Where the geometry
        # has a hole, where along it the border falls is not known, and guessing
        # would put a barrier node - and an edge break - at an invented place.
        if index_b != index_a + 1:
            continue

        state_a = state_at(lon_a, lat_a)
        state_b = state_at(lon_b, lat_b)
        if state_a is None or state_b is None or state_a == state_b:
            continue

        low, high = 0.0, 1.0
        for _ in range(24):
            mid = (low + high) / 2
            lon = lon_a + (lon_b - lon_a) * mid
            lat = lat_a + (lat_b - lat_a) * mid
            if state_at(lon, lat) == state_a:
                low = mid
            else:
                high = mid
        crossing_t = (low + high) / 2
        yield BorderNode(
            node_id=allocator.allocate(),
            lon=lon_a + (lon_b - lon_a) * crossing_t,
            lat=lat_a + (lat_b - lat_a) * crossing_t,
            osm_way_id=way_id,
            insert_after=index_a,
            state_a=state_a,
            state_b=state_b,
        )
