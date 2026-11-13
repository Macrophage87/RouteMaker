"""Signalised trail crossings, carried to the router's signal flag.

FOLLOWUP-SIGNAL-DERIVE (PLAN.md, Routing model, "Known gaps"). Valhalla's parser
sets a node's traffic-signal flag from `highway=traffic_signals` on the node and
nothing else (src/mjolnir/pbfgraphparser.cc at 3.9.1, the node loop). OSM also
maps a signalised crossing two other ways the router never read:

- on the crossing node, `highway=crossing` with `crossing=traffic_signals` (or
  `crossing:signals=yes`), the scheme OSM moved to for crossings;
- on the crossing way alone (`footway=crossing`, `cycleway=crossing` or
  `path=crossing`, tagged `crossing=traffic_signals`), with nothing on the node
  where it meets the road.

So a signalised trail crossing away from a signalised road junction read "no
signal mapped" in the junction model and was priced as a marked crosswalk
(`routemaker.intersections.MARKED_YIELD_SHARE`), not as a signal. The
first form is read in the tag transform (`remap_node`, lua/routemaker_remap.lua),
which sees the node's own tags. The second needs the way and the road together,
which the transform never sees at once, so this module finds the nodes at the
rebuild and marks them `rm:crossing_signal=yes` in every variant's extract
(`pipeline.extract.write_extract`'s `node_tags`); the transform turns the mark into
`highway=traffic_signals` where the node says nothing else about its control.

A beacon that flashes (`crossing=uncontrolled` with `flashing_lights`, an RRFB)
is not a signal: drivers are not stopped by a red, and it stays a marked crossing.
A pedestrian hybrid beacon (HAWK) shows drivers a red and is mapped as
`crossing=traffic_signals`, so it is one.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping

from routemaker.classes import MOTOR_ONLY_HIGHWAY, TRAIL_CLASS_HIGHWAY

# The derived tag, in the `rm:` namespace lua/graph.lua strips.
NODE_TAG = "rm:crossing_signal"

CROSSING_KEYS = ("footway", "cycleway", "path")
# `crossing` values that say there is no signal (OSM's wiki: `uncontrolled` and
# `unmarked` crossings have no traffic signals), whatever `crossing:signals` says. A
# contradiction is not a signal: unclear is read as the crossing with no signal.
# `marked` and `zebra` describe the paint and go with `crossing:signals=yes`.
NOT_SIGNALISED = frozenset({"uncontrolled", "unmarked", "no", "informal"})

# The ways a crossing way crosses: roads, not trails, and not motorways (a crossing
# of one is a mapping error). Service roads and busways included: a signalised
# crossing of a busy entrance road, or of a busway, is one.
NOT_A_ROAD = (
    frozenset(TRAIL_CLASS_HIGHWAY)
    | frozenset(MOTOR_ONLY_HIGHWAY)
    | frozenset({"steps", "corridor", "platform", "construction", "proposed", "raceway"})
)


def is_signalised(tags: Mapping[str, str]) -> bool:
    """Whether a crossing's tags (a node's or a way's) say it has a signal:
    `crossing=traffic_signals`, or `crossing:signals=yes` with no `crossing`
    value that says otherwise."""
    crossing = tags.get("crossing")
    if crossing == "traffic_signals":
        return tags.get("crossing:signals") != "no"
    return tags.get("crossing:signals") == "yes" and crossing not in NOT_SIGNALISED


def is_crossing_way(tags: Mapping[str, str]) -> bool:
    """A trail-class way mapped as the crossing of a road."""
    return tags.get("highway") in TRAIL_CLASS_HIGHWAY and any(
        tags.get(key) == "crossing" for key in CROSSING_KEYS
    )


def is_road(tags: Mapping[str, str]) -> bool:
    highway = tags.get("highway")
    return highway is not None and highway not in NOT_A_ROAD


def signal_nodes(ways: Iterable) -> frozenset[int]:
    """The nodes where a signalised crossing way meets a road: each node of the
    crossing way that a road way also passes through. `ways` are the rebuild's
    `extract.Way`s (`tags`, `node_ids`)."""
    ways = list(ways)
    crossing_nodes: set[int] = set()
    for way in ways:
        if is_crossing_way(way.tags) and is_signalised(way.tags):
            crossing_nodes.update(way.node_ids)
    if not crossing_nodes:
        return frozenset()
    road_nodes: set[int] = set()
    for way in ways:
        if is_road(way.tags):
            road_nodes.update(node for node in way.node_ids if node in crossing_nodes)
    return frozenset(road_nodes)


def node_tags(nodes: Iterable[int]) -> dict[int, dict[str, str]]:
    """The extract's node tags for `signal_nodes`."""
    return {node: {NODE_TAG: "yes"} for node in nodes}


# --- Beg buttons (the owner, 2026-11-08) ----------------------------------------------
#
# "They aren't very common in DC, but they are definitely frustrating elsewhere." OSM tags a
# signal a rider or walker must call with a push button `button_operated=yes`, on the
# crossing node or on the crossing way. The router carries no such flag, so the rebuild
# marks the trail-class ways that say it themselves, the crossing ways through a node that
# does, and the paths or sidewalks that end at one (`segment.button_operated`), and the
# junction-delay model reads a signal the route reaches on one as needing its button
# (`routemaker.junction_delay.signal_wait`, `core.routing.button_ways`). A road through
# such a node is not marked: a rider on the road waits for the road's green.
BUTTON_KEY = "button_operated"


def says_button(tags: Mapping[str, str]) -> bool:
    """Whether a node's or a way's tags say its signal is called with a push button."""
    return tags.get(BUTTON_KEY) == "yes"


def button_ways(ways: Iterable, button_nodes: Collection[int] = ()) -> frozenset[int]:
    """The trail-class ways (`extract.Way`s: `osm_id`, `tags`, `node_ids`) that are tagged
    `button_operated=yes`, that are a crossing way (`is_crossing_way`) through a node in
    `button_nodes`, or that end at one (a sidepath or trail split at the crossing).

    The column marks a whole way, so a long trail or sidepath that only passes through a
    button node is not marked: a multi-km cycleway crossing one road at a tagged node read
    every signal along it as a beg button, 2 km on included (the 2026-11-08 hunt, J2-3: a
    District secondary signal ranked 120 s in place of 15 s, with "Light may need a button
    press" where there is no button)."""
    nodes = frozenset(button_nodes)

    def through_button(way) -> bool:
        if not nodes or not way.node_ids:
            return False
        if is_crossing_way(way.tags):
            return any(node in nodes for node in way.node_ids)
        return way.node_ids[0] in nodes or way.node_ids[-1] in nodes

    return frozenset(
        way.osm_id
        for way in ways
        if way.tags.get("highway") in TRAIL_CLASS_HIGHWAY
        and (says_button(way.tags) or through_button(way))
    )
