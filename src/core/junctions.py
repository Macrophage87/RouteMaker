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

Where the control is. OSM in the District and Maryland puts
`highway=traffic_signals` (and often `highway=stop`) on the stop-line nodes
7-30 m before the junction node, and the router flags the edge that ends there,
not the junction (review r2: of 95 junctions priced as having no signal, 49 had
a signal flag within 30 m). So `/locate` is asked again around the node with a
radius of `APPROACH_M`, and each road arm is walked out from the node along
edges of the same road for that far: a signal at a node it reaches is the
junction's (`_Approaches`), on a road's edge arriving there towards the
junction, or the node's own flag where no edge there is flagged. The walk stops
at a node a road of another name joins: that is another junction, and its
signal is not this one's (review r3, B1: a driveway 16 m from Colesville Rd's
signalized node, a left off 17th St SW 18 m past Constitution Ave), and nor is
a signal on a crosswalk alone that such a junction is nearer than this one
(hunt J2: K St's signalised crosswalk a few metres short of K St). A rider
arriving on a path (`TRAIL_USES`) is let past one, since a trail crossing
beside a road junction is crossed on its signal; one leaving a driveway or a
parking aisle is not (gate 1, B1). The rider's own approach is read from the
route's own edges before the junction (`RawJunction.back_edge_ids`), up to the
first that arrives at such a junction: a stop or yield sign there is the
rider's, a signal the junction's. A stop sign up a cross road is not read as
the cross traffic's: it may be another junction's, and reading it would price
the rider as having priority.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from django.conf import settings

from pipeline.schema import (
    ROAD_COST_COLUMNS,
    ROAD_TRAIT_COLUMNS,
    STRESS_HALF_COLUMN,
    UNSMOOTHED_TIER_COLUMN,
    validate_schema_name,
)
from routemaker import junction_delay
from routemaker.geo import Point, haversine
from routemaker.intersections import (
    Beacon,
    Control,
    Event,
    Junction,
    Movement,
    Rating,
    Road,
    RouteEvents,
    assess_route,
    beacon_at,
    beacons_near,
    class_edge,
    major_crossings,
    majors_of_events,
    rating_at,
    with_beacons,
    with_ratings,
)
from routemaker.trace_junctions import (
    APPROACH_M,
    NOT_A_ROAD_USES,
    PATH_USES,
    RawJunction,
    decode_polyline6,
)

from . import segment_info

logger = logging.getLogger(__name__)

# Junctions asked of /locate at once (the service's `max_locations` is 50).
LOCATE_BATCH = 50
# /locate's search radius for the node, metres. With none it answers the
# single closest edge pair, which at a node can be a service road's edge
# passing a fraction of a metre nearer than the node (measured: 1-4% of busy
# junctions); a metre brings every edge at the node.
LOCATE_RADIUS_M = 1
# And for the approaches, asked again for a node whose control is not already
# a signal: every edge with a point within APPROACH_M of it. Measured on the
# live router (2026-10-02, 50 junctions a batch): 0.1-0.3 s and 2.6 MB a
# batch, against 0.04-0.15 s and 0.5 MB at 1 m.
APPROACH_RADIUS_M = int(APPROACH_M)
# Two answers are the same point within this (degrees; /locate rounds to 1e-6).
SAME_POINT_DEG = 2.5e-6
# Edges of one way leaving the node within this many degrees of each other are
# one arm (the two directions of a two-way street).
ARM_HEADING_TOLERANCE_DEG = 30.0
# Valhalla's `use` for a slip lane and a ramp: the channel a car turns by,
# never a road the rider crosses (item 169: "Sliplanes should get a penalty too").
LINK_USES = frozenset({"turn_channel", "ramp"})
# The uses of a path a rider arrives on that walk past another road's junction
# up an arm (`_Approaches`): a trail crossing a few metres from a road junction
# is crossed on that junction's signal. A driveway, parking aisle or
# drive-through is not a path: a rider leaving one onto a road beside a
# signalized junction does not have its signal (gate 1, B1).
TRAIL_USES = (
    frozenset({"footway", "path", "cycleway", "pedestrian_crossing", "steps", "track"}) | PATH_USES
)
# The costings each node is asked with. `/locate` answers only the edges its costing may
# use: asked as a bicycle alone it leaves out every road closed to bicycles, so the George
# Washington Memorial Parkway (`bicycle=no`, 4 lanes at 45 mph) had no arm where Tulane Dr
# crosses it at grade, and the crossing cost nothing (the owner: "Why
# did the route have me go across a busy highway with no signal instead of continuing the
# trail"). Asked as a car as well, the two answers merged (`_merged`): the bicycle's has the
# rider's own path, the car's every road with traffic to cross, its signals and signs.
LOCATE_COSTINGS = ("bicycle", "auto")
# What `/locate` percent_along an edge reads at its two ends.
AT_START, AT_END = 0.001, 0.999

_ROADS_BY_WAY = """
SELECT j.idx, j.way, seg.tier, seg.aadt, seg.speed, seg.lanes, seg.oneway,
       seg.default_speed, seg.urban, seg.half, seg.car_free, seg.painted_lane
FROM unnest(%s::int[], %s::bigint[], %s::float8[], %s::float8[]) AS j(idx, way, lon, lat)
CROSS JOIN LATERAL (
    SELECT {tier} AS tier, s.volume_aadt AS aadt, {speed} AS speed,
           {lanes} AS lanes, {oneway} AS oneway,
           {default_speed} AS default_speed, {urban} AS urban, {half} AS half,
           {car_free} AS car_free, {painted_lane} AS painted_lane
    FROM {schema}.segment AS s
    WHERE s.osm_way_id = j.way
    ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(j.lon, j.lat), 4326)
    LIMIT 1
) AS seg
"""

# Each "has the live table these columns?" reads the one shared answer,
# `segment_info.live_columns` (review CH-1).


def has_half_column(schema: str) -> bool:
    """Whether the live segment table has the half-step column (`STRESS_HALF_COLUMN`)."""
    return segment_info.has_columns(schema, STRESS_HALF_COLUMN)


def has_trait_columns(schema: str) -> bool:
    """Whether the live segment table has the road-trait columns yet. They
    arrive with the first rebuild after the intersection model; until then the
    reasons name the tier alone."""
    return segment_info.has_columns(schema, *ROAD_TRAIT_COLUMNS)


def has_cost_columns(schema: str) -> bool:
    """Whether the live segment table has `road_default_speed_mph` and
    `road_urban` yet (the first rebuild after OWNER-DECISIONS 469). Until then
    the junction model falls back as `routemaker.intersections` says."""
    return segment_info.has_columns(schema, *ROAD_COST_COLUMNS)


def has_unsmoothed_tier(schema: str) -> bool:
    """Whether the live segment table has `stress_unsmoothed_tier` yet (the
    first rebuild after AADT smoothing)."""
    return segment_info.has_columns(schema, UNSMOOTHED_TIER_COLUMN)


def _decided(raw: RawJunction) -> bool:
    """Some other road meets the route at the junction, or the route changes road (a
    crossing way, a turn)."""
    return raw.has_cross_roads or raw.in_way != raw.out_way or raw.slip_lane


def wanted(raw: RawJunction) -> bool:
    """Whether a junction can matter: some other road meets the route there, or
    the route changes road (a crossing way, a turn), and a road of a class that
    can be busy is among them."""
    return raw.possibly_busy and _decided(raw)


# The road classes a junction is read for by its roads' tier, not their class
# (`busy_by_tier`): a residential street DC's Roadway Block or MDOT's AADT rates LTS 3 or
# worse on its own speed or volume is a busy road to cross, but the class gate
# (`trace_junctions.BUSY_CLASSES`) never read its crossings, which cost nothing and were
# never red (the 2026-11-08 hunt, H5; the gap the comment on BUSY_CLASSES owned).
TIER_READ_CLASSES = frozenset({"residential", "living_street"})
# The tier from which such a road makes its junction worth reading.
TIER_READ_MIN = 3
# How near the junction's node a segment of such a tier must run (degrees, about 2 m):
# the node is on the road's centre line, a parallel road is metres off it.
TIER_NEAR_DEG = 2.0e-5

_BUSY_BY_TIER = """
SELECT j.idx
FROM unnest(%s::int[], %s::float8[], %s::float8[]) AS j(idx, lon, lat)
WHERE EXISTS (
    SELECT 1 FROM {schema}.segment AS s
    WHERE ST_DWithin(s.geometry, ST_SetSRID(ST_MakePoint(j.lon, j.lat), 4326), %s)
      AND s.stress_tier >= %s
      AND NOT s.is_trail_class
)
"""


def tier_candidate(raw: RawJunction) -> bool:
    """A junction the class gate leaves out (`wanted`) where a road of a class in
    TIER_READ_CLASSES meets: read where the segment table rates one of its roads busy."""
    if raw.possibly_busy or not _decided(raw):
        return False
    return any(
        cls in TIER_READ_CLASSES for cls in (raw.in_class, raw.out_class, *raw.other_classes)
    )


def busy_by_tier(points: Sequence[tuple[int, float, float]]) -> set[int]:
    """Of (index, lon, lat), the indexes whose node a segment rated TIER_READ_MIN or worse
    runs through (one query for the route). A table that cannot be read reads none: the
    junctions are then left out, as before, and the plan answered all the same."""
    if not points:
        return set()
    from django.db import DatabaseError

    from .routing import plan_cursor

    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    arrays = [list(column) for column in zip(*points, strict=True)]
    try:
        with plan_cursor() as cursor:
            cursor.execute(
                _BUSY_BY_TIER.format(schema=schema), [*arrays, TIER_NEAR_DEG, TIER_READ_MIN]
            )
            return {int(row[0]) for row in cursor.fetchall()}
    except DatabaseError:
        logger.warning("the junctions' tiers could not be read", exc_info=True)
        return set()


# --- The road a side path runs beside ---------------------------------------------
#
# A rider on a side path or a protected lane mapped as its own way crosses each side
# street's mouth beside the main road, and has that road's right of way there: the side
# street's traffic stops for the main road and for the path alike. The junction model read
# the path as the quiet way it is, so with the side street's stop sign not on the map the
# rider was priced as the one who stops (720 to 800 ft a mouth, against 25 ft with the
# sign mapped; the audit of 2026-11-13, section 3.7). So for a junction the route rides
# straight through on a path, the busiest road within BESIDE_M of the node that runs
# within BESIDE_ANGLE_DEG of parallel to the rider, and is not one of the roads met at the
# node, is the road the path runs beside (`Junction.beside`, `intersections.has_priority`).
# The distance and the angle are `routemaker.facility`'s own for naming a side path's
# street (SIDE_STREET_M, SIDE_STREET_ANGLE); a default, unmeasured.
BESIDE_M = 20.0
BESIDE_ANGLE_DEG = 30.0
# BESIDE_M as degrees, as `TIER_NEAR_DEG` is (a degree of longitude is shorter here, so
# east to west it reaches about 16 m).
BESIDE_DEG = BESIDE_M / 111_000.0

_BESIDE_ROAD = """
SELECT j.idx, best.way
FROM unnest(%s::int[], %s::float8[], %s::float8[], %s::float8[]) AS j(idx, lon, lat, heading)
CROSS JOIN LATERAL (
    SELECT s.osm_way_id AS way
    FROM {schema}.segment AS s
    CROSS JOIN LATERAL (
        SELECT ST_LineLocatePoint(s.geometry, ST_SetSRID(ST_MakePoint(j.lon, j.lat), 4326)) AS f
    ) AS at
    CROSS JOIN LATERAL (
        SELECT degrees(ST_Azimuth(
            ST_LineInterpolatePoint(s.geometry, GREATEST(at.f - 0.05, 0)),
            ST_LineInterpolatePoint(s.geometry, LEAST(at.f + 0.05, 1))
        )) AS bearing
    ) AS along
    WHERE ST_DWithin(s.geometry, ST_SetSRID(ST_MakePoint(j.lon, j.lat), 4326), %s)
      AND NOT s.is_trail_class
      AND s.osm_way_id <> ALL(%s::bigint[])
      AND abs(mod((along.bearing - j.heading + 720 + 90)::numeric, 180) - 90) <= %s
    ORDER BY s.stress_tier DESC NULLS LAST,
             s.geometry <-> ST_SetSRID(ST_MakePoint(j.lon, j.lat), 4326)
    LIMIT 1
) AS best
"""


def rides_a_path_through(raw: RawJunction) -> bool:
    """The route arrives and leaves on a path, trail, cycletrack or sidewalk, straight on:
    a side path crossing a side street's mouth, where it has a road beside it."""
    return (
        raw.movement is Movement.STRAIGHT
        and raw.in_use in PATH_USES
        and raw.out_use in PATH_USES
        and raw.in_heading is not None
    )


def beside_roads(raws: Sequence[RawJunction], nodes: dict[int, Node]) -> dict[int, int]:
    """By junction position, the way of the road the rider's path runs beside there
    (`_BESIDE_ROAD`), one query for the route. A table that cannot be read reads none: the
    rider is then priced as before, and the plan answered all the same."""
    asked = [
        (position, raw.lon, raw.lat, float(raw.in_heading or 0.0))
        for position, raw in enumerate(raws)
        if rides_a_path_through(raw)
    ]
    if not asked:
        return {}
    from django.db import DatabaseError

    from .routing import plan_cursor

    met: set[int] = set()
    for position, _lon, _lat, _heading in asked:
        raw = raws[position]
        met |= {raw.in_way, raw.out_way}
        node = nodes.get(position)
        if node is not None:
            met |= {arm.way_id for arm in node.arms}
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    arrays = [list(column) for column in zip(*asked, strict=True)]
    try:
        with plan_cursor() as cursor:
            cursor.execute(
                _BESIDE_ROAD.format(schema=schema),
                [*arrays, BESIDE_DEG, sorted(met), BESIDE_ANGLE_DEG],
            )
            return {int(idx): int(way) for idx, way in cursor.fetchall()}
    except DatabaseError:
        logger.warning("the roads beside the route's paths could not be read", exc_info=True)
        return {}


def _rated(raw: RawJunction, ratings: Sequence[Rating]) -> bool:
    """A junction (another road meets the route, or it changes road) riders rated."""
    if not ratings or not (raw.has_cross_roads or raw.in_way != raw.out_way):
        return False
    return rating_at(raw.lon, raw.lat, ratings) is not None


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
    # A signal where its traffic arrives at the node, or up it within
    # APPROACH_M (`_Approaches`); a stop or yield sign where its traffic
    # arrives at the node.
    signal: bool = False
    stop: bool = False
    # The names as mapped ("MacArthur Boulevard"), for saying; `names` are the
    # lower-case keys for matching.
    display: tuple[str, ...] = field(default=(), compare=False)

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
    # The rider's own approach faces a stop or yield sign, or a signal, at the
    # node or on the route's own edges within APPROACH_M before it.
    in_stop: bool
    in_signal: bool
    # The bicycle lane on the rider's own edge, as the router has it ("none",
    # "shared", "dedicated", "separated").
    in_cycle_lane: str | None = None

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


# The fields of a verbose `/locate` answer this module reads (`node_from_locate`,
# `control_of`, `_Approaches`), by where they sit: each edge's own, its `edge` (the flags
# through `_flag`: the signal, stop and yield signs), its `edge_info` (the shape only for its
# two ends, `_edge_ends`), and each node's. `slim_locate` keeps these alone, so a plan holds
# about half the memory for each answer it keeps (`refine.locator`, audit S21); a field read
# here and not listed would read as missing, which tests/test_junctions.py guards.
LOCATE_EDGE_FIELDS = frozenset(
    {"edge_id", "percent_along", "heading", "correlated_lon", "correlated_lat", "edge", "edge_info"}
)
LOCATE_EDGE_EDGE_FIELDS = frozenset(
    {
        "access",
        "classification",
        "cycle_lane",
        "end_node",
        "forward",
        "stop_sign",
        "traffic_signal",
        "yield_sign",
    }
)
LOCATE_EDGE_INFO_FIELDS = frozenset({"names", "shape", "way_id"})
LOCATE_NODE_FIELDS = frozenset({"node_id", "lon", "lat", "traffic_signal"})


def slim_locate(answer):
    """One location's `/locate` answer with only the fields this module reads (the
    `LOCATE_*_FIELDS`), nested as the router gives them, and each edge's shape cut to its
    first and last points at the same precision. Anything not a dict is as it came."""
    if not isinstance(answer, dict):
        return answer
    out: dict = {}
    for key, slim, fields in (("edges", _slim_edge, None), ("nodes", None, LOCATE_NODE_FIELDS)):
        if key not in answer:
            continue
        items = answer[key]
        if isinstance(items, list):
            items = [slim(item) if slim is not None else _only(item, fields) for item in items]
        out[key] = items
    return out


def _only(item, fields: frozenset):
    return {k: v for k, v in item.items() if k in fields} if isinstance(item, dict) else item


def _slim_edge(entry):
    if not isinstance(entry, dict):
        return entry
    out = _only(entry, LOCATE_EDGE_FIELDS)
    if "edge" in out:
        out["edge"] = _only(out["edge"], LOCATE_EDGE_EDGE_FIELDS)
    if "edge_info" in out:
        info = _only(out["edge_info"], LOCATE_EDGE_INFO_FIELDS)
        if isinstance(info, dict) and isinstance(info.get("shape"), str):
            info["shape"] = _two_ends(info["shape"])
        out["edge_info"] = info
    return out


def _two_ends(shape: str) -> str:
    """An encoded shape (precision 6) cut to its first and last points, which decode to
    exactly the same two as the whole; as it came where it does not decode, or has fewer
    than three points."""
    try:
        points = decode_polyline6(shape)
    except (IndexError, TypeError, ValueError):
        return shape
    if len(points) < 3:
        return shape
    out = []
    lat = lon = 0
    for x, y in (points[0], points[-1]):
        new_lat, new_lon = round(y * 1e6), round(x * 1e6)
        for delta in (new_lat - lat, new_lon - lon):
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                out.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            out.append(chr(delta + 63))
        lat, lon = new_lat, new_lon
    return "".join(out)


def node_from_locate(
    answer: dict, raw: RawJunction, around: dict | None = None, approaches: bool = True
) -> Node | None:
    """The node the route passes, from `/locate`'s answer at its point: None
    where the answer does not have the route's own arriving edge, which means
    it found some other node (and nothing in it can be trusted for this one).

    `around` is the answer at the same point with a radius of APPROACH_M,
    which the approaches are walked in (`answer` itself where there is none).
    The node's own arms come from `answer`, asked with a 1 m radius: with a
    wider one the router may report an edge at the node by another point of it
    (measured at Rockville Pike and Edmonston Dr: the rider's own edge into
    the node, at 1.0 along it with a 1 m radius, came back at 0.0 along it,
    4.7 m away, with 30 m).

    With `approaches` false nothing up the approaches is read (the arms' walk
    and the route's own edges before the node), only what is at the node: a
    1 m answer cannot show which roads join a node up an arm, so whether that
    node is another junction (`_Approaches.foreign`) is read from `around`."""
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
    in_index = out_index = None
    for index, cluster in enumerate(clusters):
        first = cluster[0][3]
        classification = (first.get("edge") or {}).get("classification") or {}
        use = classification.get("use")
        names = frozenset(
            name.lower()
            for _w, _h, _i, e in cluster
            for name in (e.get("edge_info") or {}).get("names") or []
        )
        ids = frozenset(_value(e.get("edge_id")) for _w, _h, _i, e in cluster) - {None}
        display = tuple(
            dict.fromkeys(
                name.strip()
                for _w, _h, _i, e in cluster
                for name in (e.get("edge_info") or {}).get("names") or []
                if name and name.strip()
            )
        )
        arm = Arm(
            way_id=int(cluster[0][0] or 0),
            heading=cluster[0][1],
            into=any(i and _car(e) for _w, _h, i, e in cluster),
            out_of=any(not i and _car(e) for _w, _h, i, e in cluster),
            use=use,
            link=bool(classification.get("link")) or use in LINK_USES,
            names=names,
            display=display,
            edge_ids=ids,
            signal=any(i and _flag(e, "traffic_signal") for _w, _h, i, e in cluster),
            stop=any(
                i and (_flag(e, "stop_sign") or _flag(e, "yield_sign")) for _w, _h, i, e in cluster
            ),
        )
        arms.append(arm)
        if raw.in_edge_id in ids:
            in_index = index
        if raw.out_edge_id is not None and raw.out_edge_id in ids:
            out_index = index
    if in_index is None:
        return None
    # Each road arm's approach, and the rider's own, walked out to APPROACH_M:
    # a signal is the junction's whichever arm it is on, up to the next
    # junction of another road (review r3, B1). A rider arriving on a path
    # (TRAIL_USES) is let past one; one leaving a driveway or a parking aisle
    # is not (gate 1, B1).
    wide = answer if around is None else around
    walk = _Approaches(
        wide,
        (lon, lat),
        names=frozenset().union(*(a.names for a in arms)),
        strict=arms[in_index].use not in TRAIL_USES,
    )
    for index, cluster in enumerate(clusters):
        arm = arms[index]
        if (
            approaches
            and not arm.signal
            and (arm.is_road or index == in_index)
            and walk.signal(arm, cluster)
        ):
            arms[index] = replace(arm, signal=True)
    in_arm = arms[in_index]
    out_arm = arms[out_index] if out_index is not None else None
    if out_arm is None:
        out_arm = _nearest_arm(arms, raw.out_way, raw.out_heading, exclude=in_arm)
    # The route's own edges before the junction, within APPROACH_M of it, up
    # to a junction of another road the rider has already passed, whose signal
    # or sign is that junction's (review r3, B1: a left off 17th St SW 18 m
    # past the Constitution Ave signal).
    back = walk.back(raw.back_edge_ids) if approaches else []
    return Node(
        arms=tuple(arms),
        in_arm=in_arm,
        out_arm=out_arm,
        signal=any(n.get("traffic_signal") for n in here),
        in_stop=any(_flag(e, "stop_sign") or _flag(e, "yield_sign") for e in (mine, *back)),
        in_signal=in_arm.signal
        or any(_flag(e, "traffic_signal") for e in (mine, *back))
        or any(walk.node_signal(ends[1]) for ends in map(walk.ends, back) if ends),
        in_cycle_lane=(mine.get("edge") or {}).get("cycle_lane"),
    )


class _Approaches:
    """The edges of a `/locate` answer around a node N, for walking a road's
    approach out from it: each edge's two ends (from its shape, the right way
    round for its direction) and the nodes with a signal of their own.

    `names` are N's arms'. A node up an arm that a road of none of
    those names joins is another junction (review r3, B1: a driveway 16 m from
    Colesville Rd, whose signal is on Colesville Rd's own node), and the walk
    stops there without counting it. With `strict` false (the rider arrives on
    a path, TRAIL_USES) the walk goes past one."""

    def __init__(
        self,
        answer: dict,
        point: tuple[float, float],
        names: frozenset[str] = frozenset(),
        strict: bool = False,
    ) -> None:
        self.point = point
        self.edges = answer.get("edges") or []
        self.signal_nodes = [
            (n.get("lon"), n.get("lat"))
            for n in answer.get("nodes") or []
            if n.get("traffic_signal")
        ]
        self.names = names
        self.strict = strict
        self._ends: dict[int, tuple | None] = {}

    def ends(self, entry: dict) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """(begin, end) of a directed edge, or None where its shape is missing."""
        key = id(entry)
        if key not in self._ends:
            self._ends[key] = _edge_ends(entry)
        return self._ends[key]

    def node_signal(self, at: tuple[float, float]) -> bool:
        return any(_close(lon, lat, *at) for lon, lat in self.signal_nodes)

    def _metres(self, at: tuple[float, float]) -> float:
        return haversine(Point(*self.point), Point(*at))

    def _towards(self, ends: tuple[tuple[float, float], tuple[float, float]]) -> bool:
        """A directed edge travels towards N: it ends nearer N than it begins."""
        return self._metres(ends[0]) > self._metres(ends[1])

    def foreign(self, at: tuple[float, float]) -> bool:
        """Whether a road named other than all of N's arms joins `at`: a
        junction of its own, whose signal and signs are not N's. An unnamed
        road (a driveway) does not make one."""
        if not self.strict:
            return False
        for entry in self.edges:
            ends = self.ends(entry)
            if ends is None or not _is_road(entry):
                continue
            if not (_close(*ends[0], *at) or _close(*ends[1], *at)):
                continue
            info = entry.get("edge_info") or {}
            names = {name.lower() for name in info.get("names") or []}
            if names and not names & self.names:
                return True
        return False

    def back(self, edge_ids: Sequence[int]) -> list[dict]:
        """The route's own edges before N (nearest first, as `edge_ids` has
        them) up to the first one arriving at another junction: it and those
        before it are of the junction the rider has passed."""
        by_id: dict[int | None, dict] = {}
        for entry in self.edges:
            by_id.setdefault(_value(entry.get("edge_id")), entry)
        found = []
        for edge_id in edge_ids:
            entry = by_id.get(edge_id)
            if entry is None:
                continue
            ends = self.ends(entry)
            if ends is not None and self.foreign(ends[1]):
                break
            found.append(entry)
        return found

    def crosswalk(self, arm: Arm, at: tuple[float, float]) -> bool:
        """Whether `at` is a crosswalk on the arm's road and no more: a path or
        crossing way (`TRAIL_USES`) meets it there, and no road but the arm's
        own does. Its signal (OSM's `crossing=traffic_signals`, which the
        transform makes a `highway=traffic_signals` node, a HAWK's among them)
        is for the people crossing there, and is a road junction's only where
        that junction is the one it lies beside (`signal`)."""
        path = False
        for entry in self.edges:
            ends = self.ends(entry)
            if ends is None or not (_close(*ends[0], *at) or _close(*ends[1], *at)):
                continue
            if _is_road(entry):
                if not _of_road(arm, entry):
                    return False
            elif _use(entry) in TRAIL_USES:
                path = True
        return path

    def signal(self, arm: Arm, cluster: list) -> bool:
        """Whether a signal is on the arm within APPROACH_M of the node for
        traffic towards it: on a road edge travelling towards N that arrives at
        a node the arm reaches (the router flags the edge that ends at the
        signal's node, as `traffic_signals:direction` has it), or that node's
        own flag where no edge there is flagged. A signal on an edge
        travelling away from N is the next junction's (review r3, B1). The
        walk stops at another road's junction (`foreign`).

        A signal on a crosswalk alone (`crosswalk`) is N's only where no other
        road's junction up the arm lies nearer it than N does: K St's
        signalised crosswalk 17 m up Main St, 8 m short of K St's own node, is
        K St's, and a stop-controlled side street at N does not take it (hunt
        J2, 2026-11-08: the guard of review r3, B1 was passed by the
        crosswalk node a few metres short of the other junction's). The walk
        reads the other junction's node even a little past APPROACH_M for
        that, as far as the answer has its edges."""
        frontier = []
        for _w, _h, inbound, entry in cluster:
            ends = self.ends(entry)
            if ends is not None:
                frontier.append(ends[0] if inbound else ends[1])
        seen: list[tuple[float, float]] = []
        # Crosswalk signals met, and the other roads' junctions met.
        crosswalks: list[tuple[float, float]] = []
        others: list[tuple[float, float]] = []
        while frontier:
            at = frontier.pop()
            if any(_close(*at, *s) for s in seen):
                continue
            if self._metres(at) > APPROACH_M:
                # Not walked on, but another junction there still owns a
                # crosswalk nearer it than N.
                if self.foreign(at):
                    others.append(at)
                continue
            seen.append(at)
            if self.foreign(at):
                others.append(at)
                continue
            arriving = []
            for entry in self.edges:
                ends = self.ends(entry)
                if ends is None or not _close(*ends[1], *at) or not _is_road(entry):
                    continue
                arriving.append((entry, ends))
            flagged = [ends for entry, ends in arriving if _flag(entry, "traffic_signal")]
            # A road arriving here towards N with a signal: a signalized node,
            # on this road's stop line or at a junction a few metres up it.
            # Or the node's own flag, unless every edge flagged at it travels
            # away from N (a signal facing the other way only).
            if any(self._towards(ends) for ends in flagged) or (
                self.node_signal(at) and not flagged
            ):
                if not self.crosswalk(arm, at):
                    return True
                crosswalks.append(at)
            for entry, ends in arriving:
                # Further out along the arm's own road: an edge of it arriving
                # here from farther away.
                if _of_road(arm, entry) and self._towards(ends):
                    frontier.append(ends[0])
        return any(
            not any(haversine(Point(*at), Point(*other)) < self._metres(at) for other in others)
            for at in crosswalks
        )


def _edge_ends(entry: dict) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """A `/locate` edge's begin and end points: its way's shape, reversed for
    an edge that runs against the way's direction (`edge.forward` false)."""
    shape = (entry.get("edge_info") or {}).get("shape")
    if not shape:
        return None
    try:
        points = decode_polyline6(shape)
    except (IndexError, TypeError):
        return None
    if len(points) < 2:
        return None
    if (entry.get("edge") or {}).get("forward", True):
        return points[0], points[-1]
    return points[-1], points[0]


def _use(entry: dict) -> str | None:
    """A `/locate` edge's Valhalla `use`."""
    return ((entry.get("edge") or {}).get("classification") or {}).get("use")


def _is_road(entry: dict) -> bool:
    """A `/locate` edge of a road (not a footway, path or crossing way)."""
    return _use(entry) not in NOT_A_ROAD_USES


def _of_road(arm: Arm, entry: dict) -> bool:
    """An edge is of the arm's road: its way, or a name in common."""
    info = entry.get("edge_info") or {}
    names = {name.lower() for name in info.get("names") or []}
    return info.get("way_id") == arm.way_id or bool(names & arm.names)


def _car(edge: dict) -> bool:
    """Whether motor traffic drives the edge: cars, or buses alone. A road closed
    to cars but open to buses (`motor_vehicle=no` + `bus=yes`: Exchange Ave and
    Fayette St in Baltimore, Neabsco Stream Dr) is still a road a rider crosses
    (FOLLOWUP-BUS-ROADS; `routemaker.tags.open_to_buses`)."""
    access = (edge.get("edge") or {}).get("access") or {}
    return bool(access.get("car") or access.get("bus"))


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


# The router's bicycle lane values for a lane of the rider's own beside the
# traffic: painted, or kept apart from it.
BIKE_LANES = frozenset({"dedicated", "separated"})


def crossed_links(node: Node, raw: RawJunction) -> list[Arm]:
    """The slip lanes (turn channels and ramps) whose path the route crosses
    at the node (item 195: "Flag only when you cross it").

    A channel is crossed where the rider's movement crosses it as it would a
    road (`crossing_sides`): straight across a node with channel arms on both
    sides of the rider (a crosswalk or trail across the channel, or a road
    through it), or a left turn with a channel on the right of its path. And
    one case more: riding straight on in a bicycle lane of one's own (painted
    or separated) where a channel leaves the road on the rider's right, since
    the cars turning into it cross the lane - the right hook. Riding straight
    past a channel along the road in its traffic lane, past one merging in, or
    along the channel itself (the route's own way is the channel, priced as the
    turn it is) crosses none."""
    left, right = sides(node, raw)
    left = [a for a in left if a.is_link]
    right = [a for a in right if a.is_link]
    if raw.movement is Movement.STRAIGHT:
        if left and right:
            return left + right
        if node.in_cycle_lane in BIKE_LANES:
            return [a for a in right if a.out_of]
        return []
    if raw.movement is Movement.LEFT:
        return right
    return []


# --- Asking the router ----------------------------------------------------------


class ReadingCutShort(Exception):
    """A `/locate` batch failed with one of the caller's `cut_short` errors (the
    plan's clock ran out): the junctions read are only some of the route's, and a
    reading made of them would answer with junctions missing and no flag saying so
    (combined correctness review, S3). The caller discards the reading."""


def nodes_at(
    raws: Sequence[RawJunction],
    locate: Callable[[dict], list[dict]],
    cut_short: tuple[type[BaseException], ...] = (),
    beacons: Sequence[Beacon] = (),
) -> dict[int, Node]:
    """The node at each junction (by position in `raws`), asked of the router
    in batches. A junction whose answer lacks the route's own edge, or whose
    batch the router will not answer, has no entry: its crossings and its
    right of way are then unknown, and only what the route's own roads say is
    priced (a turn onto or off a busy road, as the stopped side).

    Asked twice: at the node (`LOCATE_RADIUS_M`), read for what is at the
    node alone, and, for each node found whose control there is not a signal,
    around it (`APPROACH_RADIUS_M`) for the signals and stop signs up its
    approaches (which only the wider answer shows to be this junction's or
    another's). Where the second answer is missing the node is read from what
    is at it.

    A node at a known flashing beacon (`beacons`) is asked around too, though its
    map says signal: its signal is the beacon's (`intersections.with_beacons`), and
    the stop signs up its arms are what control it (`control_of(signals=False)`).

    A batch that fails with one of `cut_short` (the clock) is not a batch the router
    will not answer: the reading is cut short, and `ReadingCutShort` is raised."""
    answers = _ask(raws, range(len(raws)), LOCATE_RADIUS_M, locate, cut_short)
    found: dict[int, Node] = {}
    for position, answer in answers.items():
        node = node_from_locate(answer, raws[position], approaches=False)
        if node is not None:
            found[position] = node
    unsure = [
        p
        for p in sorted(found)
        if control_of(found[p]) is not Control.SIGNAL
        or beacon_at(raws[p].lon, raws[p].lat, beacons) is not None
    ]
    for position, around in _ask(raws, unsure, APPROACH_RADIUS_M, locate, cut_short).items():
        node = node_from_locate(answers[position], raws[position], around)
        if node is not None:
            found[position] = node
    if raws and len(found) < len(raws):
        logger.info("intersection nodes: %d of %d matched", len(found), len(raws))
    return found


def _ask(
    raws: Sequence[RawJunction],
    positions: Sequence[int],
    radius: int,
    locate: Callable[[dict], list[dict]],
    cut_short: tuple[type[BaseException], ...] = (),
) -> dict[int, dict]:
    """`/locate`'s answer at each of `positions` in `raws`, in batches; a batch
    the router will not answer has none. A batch that fails with one of `cut_short`
    raises `ReadingCutShort`: the answers are then only some of them. The batches are
    asked at once on the router pool (`core.parallel`, review speed-2) and read in
    order, as they were asked one after another before."""
    from . import parallel

    positions = list(positions)
    found: dict[int, dict] = {}
    chunks = [
        positions[start : start + LOCATE_BATCH] for start in range(0, len(positions), LOCATE_BATCH)
    ]
    asked = [
        [
            parallel.submit(
                locate,
                {
                    "locations": [
                        {"lon": raws[p].lon, "lat": raws[p].lat, "radius": radius} for p in chunk
                    ],
                    "verbose": True,
                    "costing": costing,
                },
            )
            for costing in LOCATE_COSTINGS
        ]
        for chunk in chunks
    ]
    for number, (chunk, futures) in enumerate(zip(chunks, asked, strict=True)):
        answered: list[list] = []
        for costing, future in zip(LOCATE_COSTINGS, futures, strict=True):
            try:
                answered.append(future.result())
            except cut_short as error:
                # The batches after it are not read: those still queued on the pool are not
                # asked (audit R4; one already running ends at its own deadline).
                for later in (f for batch in asked[number:] for f in batch):
                    later.cancel()
                raise ReadingCutShort(
                    f"{len(found)} of {len(positions)} junctions read before {error}"
                ) from error
            except Exception as error:  # noqa: BLE001 - one batch failing is not the route failing
                # A warning, not a note (hunt S, low note): up to a batch of junctions is
                # then read without its node, so a red there may go unrated.
                logger.warning(
                    "intersection nodes unavailable for a %s batch of %d junctions: %s",
                    costing,
                    len(chunk),
                    error,
                )
                if costing == LOCATE_COSTINGS[0]:
                    # Without the rider's own edges nothing at the node can be read.
                    for other in futures[1:]:
                        other.cancel()
                    answered = []
                    break
                answered.append([])
        if not answered:
            continue
        for index, position in enumerate(chunk):
            items = [(a[index] if index < len(a) else None) or {} for a in answered]
            found[position] = _merged(items)
    return found


def _merged(answers: Sequence[dict]) -> dict:
    """One `/locate` answer for a point from its answers under each costing
    (`LOCATE_COSTINGS`): the first's, with the edges and nodes only the others have."""
    first = dict(answers[0])
    for key, ident in (("edges", "edge_id"), ("nodes", "node_id")):
        items = list(first.get(key) or [])
        seen = {_value(i.get(ident)) for i in items if isinstance(i, dict)}
        for other in answers[1:]:
            for item in other.get(key) or []:
                if not isinstance(item, dict):
                    continue
                value = _value(item.get(ident))
                if value is not None and value in seen:
                    continue
                seen.add(value)
                items.append(item)
        first[key] = items
    return first


def control_of(node: Node | None, signals: bool = True) -> Control:
    """Who has the right of way, from the node's arms: a signal at the node, on
    the rider's approach or on any other road's approach, at the node or up it
    within APPROACH_M (a signal for the cross traffic is a signalized junction,
    review r1 B2c; one on a stop line short of it is the junction's, review r2);
    else the stop and yield signs on the rider's approach (up to APPROACH_M
    before the node along the route) against those on the other roads' at the
    node. At the node only edges arriving are read: an edge leaving it carries
    the flags of its far end. Unknown where the node is. `signals` False reads the
    signs alone, for a junction whose mapped signal is a flashing beacon."""
    if node is None:
        return Control.NONE
    others = [a for a in node.others if a.is_road or a.is_link]
    ahead = [node.out_arm] if node.out_arm is not None and node.out_arm.is_road else []
    if signals and (node.signal or node.in_signal or any(a.signal for a in (*others, *ahead))):
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
    costs = has_cost_columns(schema)
    # The crossed road's tier before same-street AADT smoothing lowered its
    # link, where it did: the count bunched at the intersection is charged
    # here, and only here (OWNER-DECISIONS 303: "we don't want to double
    # count"). `volume_aadt` is the agency's count already. GREATEST skips null.
    link_tier = (
        f"GREATEST(s.stress_tier, s.{UNSMOOTHED_TIER_COLUMN})"
        if has_unsmoothed_tier(schema)
        else "s.stress_tier"
    )
    # A half step (461a): its costs are the midpoints (`intersections._table`). Not where
    # smoothing raised the junction's tier above the link's, nor on a road closed to cars.
    half = "false"
    if has_half_column(schema):
        half = f"(s.{STRESS_HALF_COLUMN} AND {link_tier} = s.stress_tier)"
        if with_facility:
            half = f"({half} AND NOT (%s = ANY(s.car_free_when)))"
    query = _ROADS_BY_WAY.format(
        schema=schema,
        tier=(
            f"CASE WHEN %s = ANY(s.car_free_when) THEN 1 ELSE {link_tier} END"
            if with_facility
            else link_tier
        ),
        half=half,
        # Closed to cars at the ride's time: no traffic to read it by (`intersections.by_traffic`).
        car_free="(%s = ANY(s.car_free_when))" if with_facility else "false",
        # A painted lane (`intersections.RIGHT_HOOK_FT`).
        painted_lane="(s.facility IN ('lane', 'protected'))" if with_facility else "false",
        speed="s.road_speed_mph" if traits else "NULL::smallint",
        lanes="s.road_lanes" if traits else "NULL::smallint",
        oneway="s.road_oneway" if traits else "NULL::boolean",
        default_speed="s.road_default_speed_mph" if costs else "NULL::smallint",
        urban="s.road_urban" if costs else "NULL::boolean",
    )
    arrays = [list(column) for column in zip(*wanted_ways, strict=True)]
    params = [
        *arrays,
        *([when] if with_facility else []),
        *([when] if "%s" in half else []),
        *([when] if with_facility else []),
    ]
    found: dict[tuple[int, int], Road] = {}
    from .routing import plan_cursor

    # Under the plan's statement timeout, where a plan is reading (review speed-9).
    with plan_cursor() as cursor:
        cursor.execute(query, params)
        for (
            idx,
            way_id,
            tier,
            aadt,
            speed,
            lanes,
            oneway,
            default,
            urban,
            half_step,
            car_free,
            painted_lane,
        ) in cursor.fetchall():
            found[(idx, way_id)] = Road(
                tier=int(tier) if tier is not None else None,
                speed_mph=float(speed) if speed is not None else None,
                lanes=int(lanes) if lanes is not None else None,
                oneway=oneway,
                aadt=int(aadt) if aadt is not None else None,
                default_speed_mph=float(default) if default is not None else None,
                urban=urban,
                half=half_step is True,
                car_free=car_free is True,
                painted_lane=painted_lane is True,
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
        display=tuple(dict.fromkeys(d for a in arms for d in a.display)),
        ways=frozenset(a.way_id for a in arms),
    )


def _same_road(a: Arm, b: Arm) -> bool:
    return a.way_id == b.way_id or bool(a.names & b.names)


def build_junctions(
    raws: Sequence[RawJunction],
    nodes: dict[int, Node],
    roads: dict[tuple[int, int], Road],
    beside: dict[int, int] | None = None,
) -> list[Junction]:
    """The model's junctions: each raw one with its roads and its control. `beside`: by
    position, the way of the road the rider's path runs beside (`beside_roads`)."""
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
            links = crossed_links(node, raw)
        in_arms = [node.in_arm] if node is not None else []
        out_arms = [node.out_arm] if node is not None and node.out_arm is not None else []
        continues = raw.movement is Movement.STRAIGHT and (
            raw.in_way == raw.out_way or bool(out_arms and in_arms[0].names & out_arms[0].names)
        )
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
                slip_lane=bool(links),
                marked_crossing=raw.marked_crossing,
                path_crossing=raw.path_crossing,
                approach=raw.approach,
                links=tuple(road(a, a.way_id, [a]) for a in links),
                located=node is not None,
                continues=continues,
                ring_movement=raw.ring_movement,
                class_edge=class_edge(
                    raw.in_class,
                    [
                        cls
                        for cls, (use, _one_way) in zip(raw.other_classes, raw.others, strict=False)
                        if use not in NOT_A_ROAD_USES
                    ],
                ),
                beside=roads.get((position, (beside or {}).get(position, 0))),
            )
        )
    return junctions


def events_of(
    raws: Sequence[RawJunction],
    when: str,
    with_facility: bool,
    locate: Callable[[dict], list[dict]],
    group: bool = False,
    cut_short: tuple[type[BaseException], ...] = (),
    ratings: Sequence[Rating] = (),
    beacons: Sequence[Beacon] = (),
    closure_when: str | None = None,
    given_way: dict | None = None,
) -> list[Event]:
    """The route's junction events, in route order: the router says what meets
    at each junction and who has the right of way, the segment table how busy
    each road is, and `routemaker.intersections` what it costs. `group` is the
    Mass Ride reading (colour by the crossed road's tier). `cut_short`: see
    `nodes_at`. `ratings`: the approved rider ratings of junctions
    (`core.junction_suggestions.approved_ratings`, OWNER-DECISIONS 232), which
    set a junction's cost and colour; a rated junction is read even where no road
    there can be busy ("the road is fine, but the intersection can be especially
    dangerous"). `beacons`: the known flashing beacons at junctions the map has a
    signal at (`core.flashing_signals.active`), priced with no signal.
    `closure_when`: the ride time timed closures are read in (`routing.car_free_reading`),
    `when` where not given. `when` itself always times the junction costs (rush hour, night,
    weekend). Hunt X1 (2026-11-08, unreleased) briefly passed one value for both, so off the
    weekend graphs a plan's junctions were priced with no ride time.
    `given_way`: a dict this fills, by (lon, lat, way in, way out), with the road the rider
    gives way to at each junction read (`junction_delay.road_given_way`), so the junction
    waits read a road's traffic as this model does, not its class alone; None where the
    rider crosses with the right of way (`junction_delay.has_right_of_way`), so no stop is
    timed where none is priced."""
    by_tier = busy_by_tier(
        [
            (position, raw.lon, raw.lat)
            for position, raw in enumerate(raws)
            if tier_candidate(raw) and not _rated(raw, ratings)
        ]
    )
    raws = [
        raw
        for position, raw in enumerate(raws)
        if wanted(raw) or position in by_tier or _rated(raw, ratings)
    ]
    beacons = beacons_near([(raw.lon, raw.lat) for raw in raws], beacons)
    nodes = nodes_at(raws, locate, cut_short, beacons)
    asked: dict[tuple[int, int], tuple[int, int, float, float]] = {}
    for position, raw in enumerate(raws):
        ways = {raw.in_way, raw.out_way}
        node = nodes.get(position)
        if node is not None:
            ways |= {a.way_id for a in node.arms}
        for way in ways:
            if way:
                asked[(position, way)] = (position, way, raw.lon, raw.lat)
    beside = beside_roads(raws, nodes)
    for position, way in beside.items():
        asked[(position, way)] = (position, way, raws[position].lon, raws[position].lat)
    closures = when if closure_when is None else closure_when
    roads = roads_by_way(list(asked.values()), closures, with_facility)
    built = build_junctions(raws, nodes, roads, beside)
    if given_way is not None:
        for raw, junction in zip(raws, built, strict=True):
            key = (raw.lon, raw.lat, raw.in_way, raw.out_way)
            road = junction_delay.road_given_way(junction)
            if junction_delay.has_right_of_way(junction):
                # None: the rider crosses with the right of way, and no stop is timed.
                given_way[key] = None
            elif road is not None:
                given_way[key] = road
    if beacons:
        signs = [control_of(nodes.get(position), signals=False) for position in range(len(raws))]
        built = with_beacons(built, beacons, signs)
    built = with_ratings(built, ratings)
    events = assess_route(built, group, when=when)
    if not group:
        return events
    return with_majors(built, events)


def with_majors(built: list[Junction], events: list[Event]) -> RouteEvents:
    """A Mass Ride's events with its major junctions beside them (OWNER-DECISIONS 333,
    396), which take in busy roads the planner does not flag. A failure in finding them
    costs only the chart's extra crossings: the flagged events stand in for them
    (`majors_of_events`), marked incomplete so the chart says the list may be missing
    some (correctness re-review R3), and the events themselves (the markers, the corker
    list, the description's junctions) are kept whatever happens (operations review,
    SHOULD-FIX 1)."""
    try:
        return RouteEvents(events, major_crossings(built, events))
    except Exception:  # noqa: BLE001 - the route's own junction events must survive
        logger.warning("the major junctions could not be found", exc_info=True)
        return RouteEvents(events, majors_of_events(events), complete=False)
