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

Synthetic node ids come from a reserved negative range, which cannot collide
with real OSM node ids: OSM ids are positive, and negative ids are the
established convention for locally generated features.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

# Reserved range for nodes this pipeline mints. Anything at or below the ceiling
# is ours; real OSM node ids are positive and never appear here.
SYNTHETIC_NODE_ID_CEILING = -1
SYNTHETIC_NODE_ID_FLOOR = -(2**62)

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
    # Index in the way's node list *after* which this node is inserted.
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
    """Allocator for the reserved negative range.

    Deterministic within a rebuild and restarted each time, because the ids are
    not persistent identity: the crossings table records what each one means, and
    a rebuild reassigns them.
    """

    def __init__(self, start: int = SYNTHETIC_NODE_ID_CEILING) -> None:
        if not SYNTHETIC_NODE_ID_FLOOR <= start <= SYNTHETIC_NODE_ID_CEILING:
            raise ValueError("start must lie inside the reserved synthetic range")
        self._next = start

    def allocate(self) -> int:
        if self._next < SYNTHETIC_NODE_ID_FLOOR:
            raise NodeIdExhausted("reserved synthetic node id range exhausted")
        node_id = self._next
        self._next -= 1
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
        result.insert(node.insert_after + 1, node.node_id)
    return result


def find_state_crossings(
    way_id: int,
    coordinates: Sequence[tuple[float, float]],
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
    """
    from .jurisdiction import is_boundary_street

    if is_boundary_street(way_name):
        return

    for index, ((lon_a, lat_a), (lon_b, lat_b)) in enumerate(
        zip(coordinates, coordinates[1:], strict=False)
    ):
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
            insert_after=index,
            state_a=state_a,
            state_b=state_b,
        )
