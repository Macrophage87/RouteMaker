"""What is at each junction of a route: the roads that meet there and who has
the right of way, both from the router's `/locate`, and how busy each road is,
from the segment table.

The router half of `routemaker.intersections` (OWNER-DECISIONS items 165 to
172). `routemaker.trace_junctions` reads where the route passes a node; this
module asks `/locate` at each such node for the directed edges that meet there
(their way, heading, whether a car may drive them towards the node or away,
whether they are a turn channel or ramp, and the stop, yield and signal flags
of the edges that arrive) and the segment table for the stress of each way, so
that the pure model has everything it prices. Both are asked only for
junctions where a road of a class that can be busy is involved, so a ride on
neighbourhood streets costs one query and no router call.

Why the router's edges and not the roads near the node. Round 1 took the roads
within 4.4 m of the node from the segment table. Measured on the live router
(review r1, B1), that read a road's own turn channel, a one-way carriageway
merging into it and a ramp diverging from it as roads the rider crossed while
riding straight along it, and a junction on a bridge deck picked up the road
below. The router's edges at the node are exactly the roads that meet there,
and their headings say which side of the rider each lies on: a rider going
straight crosses a road only where it has an arm on both sides (a T-junction's
side road is not crossed by the rider on the through road), and a turn channel
or ramp is a slip lane (item 169), never a crossed road.

A node exists once per level of the router's hierarchy (a primary road's edges
end at its level 0 node, a tertiary cross street's at its level 1 node, at one
point), so the node is every node `/locate` lists at the in-edge's end point,
not the in-edge's end node alone.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from django.conf import settings
from django.db import connection

from pipeline.schema import ROAD_TRAIT_COLUMNS, validate_schema_name
from routemaker.intersections import (
    Control,
    Event,
    Junction,
    Movement,
    Road,
    assess_route,
)
from routemaker.trace_junctions import NOT_A_ROAD_USES, RawJunction

logger = logging.getLogger(__name__)

# Junctions asked of /locate at once (the service's `max_locations` is 50).
LOCATE_BATCH = 50
# /locate's search radius, metres. With none it answers the single closest
# edge pair, which at a node can be a service road's edge passing a fraction of
# a metre nearer than the node (measured: 1-4% of busy junctions); a metre
# brings every edge at the node.
LOCATE_RADIUS_M = 1
# Two answers are the same point within this (degrees; /locate rounds to 1e-6).
SAME_POINT_DEG = 2.5e-6
# Edges of one way leaving the node within this many degrees of each other are
# one arm (the two directions of a two-way street).
ARM_HEADING_TOLERANCE_DEG = 30.0
# Valhalla's `use` for a slip lane and a ramp: the channel a car turns by,
# never a road the rider crosses (item 169: "Sliplanes should get a penalty too").
LINK_USES = frozenset({"turn_channel", "ramp"})
# What `/locate` percent_along an edge reads at its two ends.
AT_START, AT_END = 0.001, 0.999

_ROADS_BY_WAY = """
SELECT j.idx, j.way, seg.tier, seg.aadt, seg.speed, seg.lanes, seg.oneway
FROM unnest(%s::int[], %s::bigint[], %s::float8[], %s::float8[]) AS j(idx, way, lon, lat)
CROSS JOIN LATERAL (
    SELECT {tier} AS tier, s.volume_aadt AS aadt, {speed} AS speed,
           {lanes} AS lanes, {oneway} AS oneway
    FROM {schema}.segment AS s
    WHERE s.osm_way_id = j.way
    ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(j.lon, j.lat), 4326)
    LIMIT 1
) AS seg
"""

_has_trait_columns_seen = False


def has_trait_columns(schema: str) -> bool:
    """Whether the live segment table has the road-trait columns yet. They
    arrive with the first rebuild after the intersection model; until then the
    reasons name the tier alone. Remembered once seen, as `core.routing` does
    for the facility columns."""
    global _has_trait_columns_seen
    if _has_trait_columns_seen:
        return True
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'segment' AND column_name = ANY(%s)",
            [schema, list(ROAD_TRAIT_COLUMNS)],
        )
        _has_trait_columns_seen = cursor.fetchone()[0] == len(ROAD_TRAIT_COLUMNS)
    return _has_trait_columns_seen


def wanted(raw: RawJunction) -> bool:
    """Whether a junction can matter: some other road meets the route there, or
    the route changes road (a crossing way, a turn), and a road of a class that
    can be busy is among them."""
    return raw.possibly_busy and (raw.has_cross_roads or raw.in_way != raw.out_way or raw.slip_lane)


# --- The node, from /locate -----------------------------------------------------


@dataclass(frozen=True)
class Arm:
    """One road leaving a node: the edges of one way that start or end there,
    pointing one way out of it."""

    way_id: int
    # Compass heading out of the node.
    heading: float
    # A car may drive along it towards the node / away from it.
    into: bool
    out_of: bool
    use: str | None
    link: bool
    names: frozenset[str]
    edge_ids: frozenset[int]
    # A signal, or a stop or yield sign, where its traffic arrives at the node.
    signal: bool = False
    stop: bool = False

    @property
    def is_road(self) -> bool:
        """A road a rider crosses: open to cars, not a path or a crossing, not a
        turn channel or ramp."""
        return (self.into or self.out_of) and not self.link and self.use not in NOT_A_ROAD_USES

    @property
    def is_link(self) -> bool:
        return self.link and (self.into or self.out_of)


@dataclass(frozen=True)
class Node:
    """The arms at the node a route passes, and its own signal flag."""

    arms: tuple[Arm, ...]
    in_arm: Arm
    out_arm: Arm | None
    signal: bool
    # The rider's own approach faces a stop or yield sign, or a signal.
    in_stop: bool
    in_signal: bool

    @property
    def others(self) -> tuple[Arm, ...]:
        return tuple(a for a in self.arms if a is not self.in_arm and a is not self.out_arm)


def _value(raw) -> int | None:
    if isinstance(raw, dict):
        raw = raw.get("value")
    return raw if isinstance(raw, int) else None


def _close(lon_a, lat_a, lon_b, lat_b) -> bool:
    try:
        return abs(lon_a - lon_b) <= SAME_POINT_DEG and abs(lat_a - lat_b) <= SAME_POINT_DEG
    except TypeError:
        return False


def _flag(entry: dict, key: str) -> bool:
    return bool((entry.get("edge") or {}).get(key))


def node_from_locate(answer: dict, raw: RawJunction) -> Node | None:
    """The node the route passes, from `/locate`'s answer at its point: None
    where the answer does not have the route's own arriving edge, which means
    it found some other node (and nothing in it can be trusted for this one)."""
    edges = answer.get("edges") or []
    arriving = [
        e
        for e in edges
        if _value(e.get("edge_id")) == raw.in_edge_id
        and float(e.get("percent_along") or 0.0) >= AT_END
    ]
    if raw.in_edge_id is None or not arriving:
        return None
    mine = arriving[0]
    lon, lat = mine.get("correlated_lon"), mine.get("correlated_lat")
    here = [n for n in answer.get("nodes") or [] if _close(n.get("lon"), n.get("lat"), lon, lat)]
    node_ids = {_value((mine.get("edge") or {}).get("end_node"))} | {
        _value(n.get("node_id")) for n in here
    }
    node_ids.discard(None)
    # (way, heading out of the node, inbound?, edge)
    at_node = []
    for e in edges:
        along = float(e.get("percent_along") or 0.0)
        heading = e.get("heading")
        if heading is None:
            continue
        inbound = along >= AT_END and _value((e.get("edge") or {}).get("end_node")) in node_ids
        outbound = along <= AT_START and _close(
            e.get("correlated_lon"), e.get("correlated_lat"), lon, lat
        )
        if not (inbound or outbound):
            continue
        out_heading = (float(heading) + 180.0) % 360.0 if inbound else float(heading)
        at_node.append(((e.get("edge_info") or {}).get("way_id"), out_heading, inbound, e))
    clusters: list[list] = []
    for item in at_node:
        for cluster in clusters:
            way, heading = cluster[0][0], cluster[0][1]
            if item[0] == way and _angle(item[1], heading) <= ARM_HEADING_TOLERANCE_DEG:
                cluster.append(item)
                break
        else:
            clusters.append([item])
    arms = []
    in_arm = out_arm = None
    for cluster in clusters:
        first = cluster[0][3]
        classification = (first.get("edge") or {}).get("classification") or {}
        use = classification.get("use")
        names = frozenset(
            name.lower()
            for _w, _h, _i, e in cluster
            for name in (e.get("edge_info") or {}).get("names") or []
        )
        ids = frozenset(_value(e.get("edge_id")) for _w, _h, _i, e in cluster) - {None}
        arm = Arm(
            way_id=int(cluster[0][0] or 0),
            heading=cluster[0][1],
            into=any(i and _car(e) for _w, _h, i, e in cluster),
            out_of=any(not i and _car(e) for _w, _h, i, e in cluster),
            use=use,
            link=bool(classification.get("link")) or use in LINK_USES,
            names=names,
            edge_ids=ids,
            signal=any(i and _flag(e, "traffic_signal") for _w, _h, i, e in cluster),
            stop=any(
                i and (_flag(e, "stop_sign") or _flag(e, "yield_sign")) for _w, _h, i, e in cluster
            ),
        )
        arms.append(arm)
        if raw.in_edge_id in ids:
            in_arm = arm
        if raw.out_edge_id is not None and raw.out_edge_id in ids:
            out_arm = arm
    if in_arm is None:
        return None
    if out_arm is None:
        out_arm = _nearest_arm(arms, raw.out_way, raw.out_heading, exclude=in_arm)
    return Node(
        arms=tuple(arms),
        in_arm=in_arm,
        out_arm=out_arm,
        signal=any(n.get("traffic_signal") for n in here),
        in_stop=_flag(mine, "stop_sign") or _flag(mine, "yield_sign"),
        in_signal=_flag(mine, "traffic_signal"),
    )


def _car(edge: dict) -> bool:
    return bool(((edge.get("edge") or {}).get("access") or {}).get("car"))


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _nearest_arm(arms, way, heading, exclude) -> Arm | None:
    candidates = [a for a in arms if a is not exclude and a.way_id == way]
    if not candidates:
        return None
    if heading is None:
        return candidates[0]
    return min(candidates, key=lambda a: _angle(a.heading, heading))


# --- Which side of the rider an arm lies on ------------------------------------


def _clockwise(origin: float, heading: float) -> float:
    return (heading - origin) % 360.0


def sides(node: Node, raw: RawJunction) -> tuple[list[Arm], list[Arm]]:
    """The other arms at the node on the rider's left and on their right.

    The rider's path through the node (in by the in-arm, out by the out-arm)
    splits the compass in two: the arms met going clockwise from the way out to
    the way in are on the right."""
    back = node.in_arm.heading
    out = node.out_arm.heading if node.out_arm is not None else raw.out_heading
    if out is None:
        out = (back + 180.0) % 360.0
    to_back = _clockwise(out, back)
    left, right = [], []
    for arm in node.others:
        angle = _clockwise(out, arm.heading)
        (right if 0.0 < angle < to_back else left).append(arm)
    return left, right


def crossing_sides(node: Node, raw: RawJunction) -> tuple[list[Arm], list[Arm]] | None:
    """The road arms the rider's movement crosses, as (one side, the other
    side), or None where it crosses no road.

    Straight on, a road is crossed only where roads leave the node on both
    sides of the rider (a road that continues straight through, or a one-way
    pair, in-only on one side and out-only on the other). A road on one side
    only is a side road joining the rider's: a T-junction, a one-way
    carriageway merging or diverging, which the rider on the through road does
    not cross. A left turn crosses the roads on the right of its path (the
    oncoming lanes and the far side's traffic); a right turn crosses none."""
    left, right = sides(node, raw)
    left = [a for a in left if a.is_road]
    right = [a for a in right if a.is_road]
    if raw.movement is Movement.STRAIGHT:
        return (left, right) if left and right else None
    if raw.movement is Movement.LEFT:
        return (right, []) if right else None
    return None


# --- Asking the router ----------------------------------------------------------


def nodes_at(
    raws: Sequence[RawJunction],
    locate: Callable[[dict], list[dict]],
) -> dict[int, Node]:
    """The node at each junction (by position in `raws`), asked of the router
    in batches. A junction whose answer lacks the route's own edge, or whose
    batch the router will not answer, has no entry: its crossings and its
    right of way are then unknown, and only what the route's own roads say is
    priced (a turn onto or off a busy road, as the stopped side)."""
    found: dict[int, Node] = {}
    for start in range(0, len(raws), LOCATE_BATCH):
        chunk = list(range(start, min(start + LOCATE_BATCH, len(raws))))
        payload = {
            "locations": [
                {"lon": raws[p].lon, "lat": raws[p].lat, "radius": LOCATE_RADIUS_M} for p in chunk
            ],
            "verbose": True,
            "costing": "bicycle",
        }
        try:
            answers = locate(payload)
        except Exception as error:  # noqa: BLE001 - one batch failing is not the route failing
            logger.info("intersection nodes unavailable for a batch: %s", error)
            continue
        for position, answer in zip(chunk, answers, strict=False):
            node = node_from_locate(answer or {}, raws[position])
            if node is not None:
                found[position] = node
    if raws and len(found) < len(raws):
        logger.info("intersection nodes: %d of %d matched", len(found), len(raws))
    return found


def control_of(node: Node | None) -> Control:
    """Who has the right of way, from the node's arms: a signal at the node, on
    the rider's approach or on any other road's approach (a signal for the
    cross traffic is a signalised junction, review r1 B2c); else the stop and
    yield signs on the rider's approach against those on the other roads'. Only
    edges arriving at this node are read: an edge leaving it carries the flags
    of its far end. Unknown where the node is."""
    if node is None:
        return Control.NONE
    others = [a for a in node.others if a.is_road or a.is_link]
    if node.signal or node.in_signal or any(a.signal for a in others):
        return Control.SIGNAL
    cross_stops = any(a.stop for a in others)
    if node.in_stop and cross_stops:
        return Control.ALL_STOP
    if node.in_stop:
        return Control.STOP
    if cross_stops:
        return Control.CROSS_STOP
    return Control.NONE


# --- The segment table ------------------------------------------------------------


def roads_by_way(
    wanted_ways: Sequence[tuple[int, int, float, float]], when: str, with_facility: bool
) -> dict[tuple[int, int], Road]:
    """For (junction position, way id, lon, lat), the segment of that way
    nearest the point: {(position, way): Road}. A way the table does not have
    has no entry."""
    if not wanted_ways:
        return {}
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    traits = has_trait_columns(schema)
    query = _ROADS_BY_WAY.format(
        schema=schema,
        tier=(
            "CASE WHEN %s = ANY(s.car_free_when) THEN 1 ELSE s.stress_tier END"
            if with_facility
            else "s.stress_tier"
        ),
        speed="s.road_speed_mph" if traits else "NULL::smallint",
        lanes="s.road_lanes" if traits else "NULL::smallint",
        oneway="s.road_oneway" if traits else "NULL::boolean",
    )
    arrays = [list(column) for column in zip(*wanted_ways, strict=True)]
    params = [*arrays, *([when] if with_facility else [])]
    found: dict[tuple[int, int], Road] = {}
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        for idx, way_id, tier, aadt, speed, lanes, oneway in cursor.fetchall():
            found[(idx, way_id)] = Road(
                tier=int(tier) if tier is not None else None,
                speed_mph=float(speed) if speed is not None else None,
                lanes=int(lanes) if lanes is not None else None,
                oneway=oneway,
                aadt=int(aadt) if aadt is not None else None,
            )
    return found


def _with_graph(road: Road, arms: Sequence[Arm]) -> Road:
    """A road as the segment table has it, with what the router's own arms say
    of it: one-way where no arm of it may be driven both towards and away from
    the node, and its names (a divided road's two carriageways share them,
    which is how the crossing counts once, `routemaker.intersections`)."""

    if not arms:
        return road
    names = frozenset().union(*(a.names for a in arms))
    oneway = not any(a.into and a.out_of for a in arms)
    return replace(
        road,
        oneway=oneway if road.oneway is None else road.oneway,
        names=names or frozenset({f"way {arms[0].way_id}"}),
    )


def _same_road(a: Arm, b: Arm) -> bool:
    return a.way_id == b.way_id or bool(a.names & b.names)


def build_junctions(
    raws: Sequence[RawJunction],
    nodes: dict[int, Node],
    roads: dict[tuple[int, int], Road],
) -> list[Junction]:
    """The model's junctions: each raw one with its roads and its control."""
    junctions = []
    unknown = Road(None)
    for position, raw in enumerate(raws):
        node = nodes.get(position)

        def road(arm: Arm | None, way: int, arms: Sequence[Arm] = ()) -> Road:
            found = roads.get((position, arm.way_id if arm else way), unknown)  # noqa: B023
            return _with_graph(found, arms)

        def tier(arm: Arm) -> int:
            return road(arm, arm.way_id).tier or 0

        crossed: tuple[Road, ...] = ()
        links: list[Arm] = []
        if node is not None:
            found = crossing_sides(node, raw)
            if found is not None:
                one, other = found
                # Each side's busiest road; going straight, the crossing is the
                # quieter of the two (a road that becomes a residential street
                # across the junction is crossed as the street it is there).
                chosen = max(one, key=tier)
                if other:
                    chosen = min(chosen, max(other, key=tier), key=tier)
                same = [a for a in (*one, *other) if _same_road(a, chosen)]
                crossed = (road(chosen, chosen.way_id, same),)
            links = [a for a in node.others if a.is_link]
        in_arms = [node.in_arm] if node is not None else []
        out_arms = [node.out_arm] if node is not None and node.out_arm is not None else []
        junctions.append(
            Junction(
                m=raw.m,
                lon=raw.lon,
                lat=raw.lat,
                movement=raw.movement,
                incoming=road(None, raw.in_way, in_arms),
                outgoing=road(None, raw.out_way, out_arms),
                crossed=crossed,
                control=control_of(node),
                slip_lane=raw.slip_lane or bool(links),
                marked_crossing=raw.marked_crossing,
                path_crossing=raw.path_crossing,
                approach=raw.approach,
                links=tuple(road(a, a.way_id, [a]) for a in links),
                located=node is not None,
            )
        )
    return junctions


def events_of(
    raws: Sequence[RawJunction],
    when: str,
    with_facility: bool,
    locate: Callable[[dict], list[dict]],
    group: bool = False,
) -> list[Event]:
    """The route's junction events, in route order: the router says what meets
    at each junction and who has the right of way, the segment table how busy
    each road is, and `routemaker.intersections` what it costs. `group` is the
    Mass Ride reading (colour by the crossed road's tier)."""
    raws = [raw for raw in raws if wanted(raw)]
    nodes = nodes_at(raws, locate)
    asked: dict[tuple[int, int], tuple[int, int, float, float]] = {}
    for position, raw in enumerate(raws):
        ways = {raw.in_way, raw.out_way}
        node = nodes.get(position)
        if node is not None:
            ways |= {a.way_id for a in node.arms}
        for way in ways:
            if way:
                asked[(position, way)] = (position, way, raw.lon, raw.lat)
    roads = roads_by_way(list(asked.values()), when, with_facility)
    return assess_route(build_junctions(raws, nodes, roads), group)
