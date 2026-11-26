"""Streets behind a closed gate (the owner, 2026-11-25, of Southwest Florida: "There's also a
lot of roads that are in housing complexes only open to people who are residents or
guests").

OSM often tags only the entrance of a gated community: a gate node closed to the public
(`barrier=gate` or `lift_gate` with `access=private`, ...) or the entrance drive itself
(`access=private`), with the streets behind it
left untagged, so the router reads them as public and rides through. Here the streets are
read as the gate says: a group of streets that reaches the rest of the street network
only through closed gates is closed too. The owner, 2026-11-26: "Have them closed, like
with restricted areas in dc, but with a different color." So they close to bicycles on
every graph (`rm:no_bicycle=gated`, `pipeline.trail_closures`) and leave the stress map,
as a military base's roads do; the map shades the community in its own colour, and a
trip point inside one is routed to its gate (`scripts/build_restricted_sites.py`, kind
`gated`). An owner's override with a bicycle key reopens a street.

What counts as reaching the network: a through road (tertiary or above, or an
unclassified road) in the group. A public neighbourhood always holds one, or is joined to
one by a street with no gate; a gated community's own streets are residential and service
roads. A street OSM tags itself (any `access`, or a bicycle tag) keeps its own tags, and
paths and footways are not streets here: a footpath out of the community neither opens
its streets nor is closed by this rule.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

GATE_BARRIERS = frozenset({"gate", "lift_gate", "swing_gate", "sliding_gate", "entrance"})
CLOSED_VALUES = frozenset({"private", "no", "residents", "permit"})
# The keys a gate is closed by: the general one and the motor keys a community gate is
# usually tagged with.
GATE_KEYS = ("access", "motor_vehicle", "motorcar", "vehicle")
STREETS = frozenset({"residential", "service", "living_street", "unclassified", "road"})
THROUGH = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
    }
)
# The `rm:no_bicycle` reason of a street behind a closed gate.
NO_BICYCLE = "gated"


def is_closed_gate(tags: Mapping[str, str]) -> bool:
    """A gate node closed to the public: a gate barrier one of `GATE_KEYS` closes, and no
    bicycle grant on the gate itself."""
    if tags.get("barrier") not in GATE_BARRIERS:
        return False
    if tags.get("bicycle") in {"yes", "designated", "permissive"}:
        return False
    return any(tags.get(key) in CLOSED_VALUES for key in GATE_KEYS)


class _Sets:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def behind_gates(
    ways: Iterable[tuple[int, Mapping[str, str], Sequence[int]]], gates: set[int]
) -> set[int]:
    """The street ways (id, tags, node ids) that reach the network only through `gates`
    and carry no access or bicycle tag of their own: the ways to close."""
    streets = [
        (osm_id, tags, nodes)
        for osm_id, tags, nodes in ways
        if tags.get("highway") in STREETS | THROUGH and len(nodes) >= 2
    ]

    # A street OSM closes itself (the entrance drive tagged `access=private`) is a gate
    # along its whole length: nothing is joined along it, and what it touches is gated.
    def closes(tags: Mapping[str, str]) -> bool:
        return tags.get("access") in CLOSED_VALUES and tags.get("highway") in STREETS

    sets = _Sets()
    for _, tags, nodes in streets:
        if closes(tags):
            for n in nodes:
                sets.find(n)
            continue
        for a, b in zip(nodes, nodes[1:], strict=False):
            # A gate splits the street network: nothing is joined across it.
            if a not in gates and b not in gates:
                sets.union(a, b)
            else:
                sets.find(a), sets.find(b)
    public: set[int] = set()
    gated: set[int] = set()
    for _, tags, nodes in streets:
        roots = {sets.find(n) for n in nodes if n not in gates}
        if tags.get("highway") in THROUGH:
            public |= roots
        if closes(tags):
            gated |= {sets.find(n) for n in nodes if n not in gates}
        elif any(n in gates for n in nodes):
            gated |= roots
    closed: set[int] = set()
    for osm_id, tags, nodes in streets:
        if tags.get("highway") not in STREETS or tags.get("highway") in THROUGH:
            continue
        if "access" in tags or "bicycle" in tags:
            continue
        roots = {sets.find(n) for n in nodes if n not in gates}
        # Every part of the way lies behind a gate: a way that runs through the gate
        # itself, out to the public side, is left as it is.
        if roots and roots <= gated and not roots & public:
            closed.add(osm_id)
    return closed
