"""The junctions of a traced route, read from Valhalla's `/trace_attributes`.

What `routemaker.intersections` needs from the router: where the route passes a
node, the compass headings it arrives and leaves on, which ways it comes from
and goes to, and what kind of edge each of the other roads at the node is
(Valhalla's own `use`: a `turn_channel` is a slip lane, a `pedestrian_crossing`
is a marked crossing). Nothing here touches the network or the database.

The extra attributes are asked for in `TRACE_ATTRIBUTES`; a trace that lacks
them (an older router, a test double) simply has no junctions, and the route is
answered without the intersection list rather than refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .intersections import Movement, movement_of

# What `core.routing.trace_leg` asks the router for besides the stress join's
# own four: `edge.id` is what ties a traced edge to `/locate`'s directed edge
# (and its stop, yield and signal flags).
TRACE_ATTRIBUTES = (
    "edge.id",
    "edge.use",
    "edge.road_class",
    "edge.begin_heading",
    "edge.end_heading",
    "node.intersecting_edge.begin_heading",
    "node.intersecting_edge.road_class",
    "node.intersecting_edge.use",
    "node.intersecting_edge.driveability",
)

# The road classes (Valhalla's, from OSM `highway`) on which a way can be LTS 3
# or worse. A junction none of whose roads is one of these is a neighbourhood
# junction and costs nothing, which spares the segment query most of a ride's
# nodes. A residential street rated LTS 3 on its own speed or volume is missed
# by this; the tier of the stretch still colours the route, only its crossings
# go unflagged (docs/DEVELOPMENT.md, "Intersection costs").
BUSY_CLASSES = frozenset({"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified"})

# Valhalla's `use` values this model reads. A slip lane is Valhalla's name for a
# channelised turn; both are drawn from OSM `highway=*_link` at an intersection.
SLIP_LANE_USE = "turn_channel"
CROSSING_USE = "pedestrian_crossing"
# Other roads at a node that are never a road a rider crosses.
NOT_A_ROAD_USES = frozenset(
    {
        "footway",
        "steps",
        "path",
        "cycleway",
        "track",
        "pedestrian_crossing",
        "driveway",
        "parking_aisle",
        "drive_through",
        "rest_area",
        "service_area",
    }
)


@dataclass(frozen=True)
class RawJunction:
    """One node of a traced route, before the segment table says what is there."""

    m: float
    lon: float
    lat: float
    in_edge_id: int | None
    in_way: int
    out_way: int
    movement: Movement
    in_use: str | None
    out_use: str | None
    # Valhalla's `use` of each other edge at the node, and whether a car may
    # drive it one way only (`driveability` is not "both").
    others: tuple[tuple[str | None, bool], ...] = field(default_factory=tuple)
    # Valhalla's road class of the way the route arrives on, of the one it leaves
    # on, and of each other road at the node.
    in_class: str | None = None
    out_class: str | None = None
    other_classes: tuple[str | None, ...] = field(default_factory=tuple)
    # A point on the edge the route arrives by (its middle vertex).
    approach: tuple[float, float] | None = None

    @property
    def slip_lane(self) -> bool:
        return SLIP_LANE_USE in (self.in_use, self.out_use) or any(
            use == SLIP_LANE_USE for use, _one_way in self.others
        )

    @property
    def cross_road_count(self) -> int:
        """How many of the other edges at the node are roads a rider crosses.
        A way that only passes near the node (a sidepath three metres from the
        carriageway it follows) shares no node with it and so has none here."""
        return sum(1 for use, _one_way in self.others if use not in NOT_A_ROAD_USES)

    @property
    def has_cross_roads(self) -> bool:
        return self.cross_road_count > 0

    @property
    def possibly_busy(self) -> bool:
        """Whether any road at the node is of a class that can be LTS 3 or worse."""
        return any(
            cls in BUSY_CLASSES for cls in (self.in_class, self.out_class, *self.other_classes)
        )

    @property
    def marked_crossing(self) -> bool:
        """The route crosses by a mapped crossing way (Valhalla's
        `pedestrian_crossing`: a trail crossing a road, a crosswalk)."""
        return CROSSING_USE in (self.in_use, self.out_use)


def edge_id_of(edge: dict) -> int | None:
    """The directed edge's GraphId value, however the router spells it."""
    raw = edge.get("id")
    if isinstance(raw, dict):
        raw = raw.get("value")
    return int(raw) if isinstance(raw, int) else None


def junctions_of_trace(
    trace: dict, shape: list[tuple[float, float]], offset_m: float = 0.0
) -> list[RawJunction]:
    """Every node the traced leg passes through where something is decided.

    `shape` is the leg's decoded shape (lon, lat), `offset_m` the metres the
    route has already gone. A node between two edges of the same way with no
    other road at it is a continuation and is left out, as is a node whose
    headings the router did not give."""
    edges = trace.get("edges") or []
    to_metres = 1609.344 if trace.get("units") == "miles" else 1000.0
    junctions: list[RawJunction] = []
    along = offset_m
    for here, there in zip(edges, edges[1:], strict=False):
        along += float(here.get("length") or 0.0) * to_metres
        end = here.get("end_shape_index")
        in_heading, out_heading = here.get("end_heading"), there.get("begin_heading")
        if end is None or end >= len(shape) or in_heading is None or out_heading is None:
            continue
        in_way, out_way = int(here.get("way_id") or 0), int(there.get("way_id") or 0)
        others = tuple(
            (other.get("use"), other.get("driveability") not in (None, "both"))
            for other in (here.get("end_node") or {}).get("intersecting_edges") or []
        )
        other_classes = tuple(
            other.get("road_class")
            for other in (here.get("end_node") or {}).get("intersecting_edges") or []
        )
        if in_way == out_way and not others:
            continue
        lon, lat = shape[end]
        begin = here.get("begin_shape_index")
        approach = shape[(begin + end) // 2] if begin is not None and begin <= end else None
        junctions.append(
            RawJunction(
                m=along,
                lon=lon,
                lat=lat,
                in_edge_id=edge_id_of(here),
                in_way=in_way,
                out_way=out_way,
                movement=movement_of(float(in_heading), float(out_heading)),
                in_use=here.get("use"),
                out_use=there.get("use"),
                others=others,
                in_class=here.get("road_class"),
                out_class=there.get("road_class"),
                other_classes=other_classes,
                approach=approach,
            )
        )
    return junctions
