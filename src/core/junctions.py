"""What is at each junction of a route: the roads, from the segment table, and
who has the right of way, from the router.

The database half of `routemaker.intersections` (OWNER-DECISIONS items 165 to
172). `routemaker.trace_junctions` reads where the route passes a node; this
module finds the roads that meet there and the stop, yield and signal flags
Valhalla's tiles carry, so that the pure model has everything it prices. Both
are asked only for junctions where a busy road is involved, so a ride on
neighbourhood streets costs one query and no router call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from django.conf import settings
from django.db import connection

from pipeline.schema import ROAD_TRAIT_COLUMNS, validate_schema_name
from routemaker.intersections import Control, Event, Junction, Road, assess_route
from routemaker.trace_junctions import RawJunction

logger = logging.getLogger(__name__)

# How close to the node a segment must pass to be a road that meets there:
# 0.00004 degrees of latitude is 4.4 m, which is a carriageway's half width and
# a segment end's rounding, and misses the next junction on any real street.
JUNCTION_RADIUS_DEG = 0.00004

# Junctions asked of /locate at once (the service's `max_locations` is 50).
LOCATE_BATCH = 50

_ROADS_AT = """
SELECT j.idx, seg.osm_way_id, seg.tier, seg.aadt, seg.speed, seg.lanes, seg.oneway
FROM unnest(%s::int[], %s::float8[], %s::float8[]) AS j(idx, lon, lat)
CROSS JOIN LATERAL (
    SELECT DISTINCT ON (s.osm_way_id)
           s.osm_way_id, {tier} AS tier, s.volume_aadt AS aadt, {speed} AS speed,
           {lanes} AS lanes, {oneway} AS oneway
    FROM {schema}.segment AS s
    WHERE ST_DWithin(s.geometry, ST_SetSRID(ST_MakePoint(j.lon, j.lat), 4326), %s)
    ORDER BY s.osm_way_id, s.geometry <-> ST_SetSRID(ST_MakePoint(j.lon, j.lat), 4326)
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


def roads_at(
    raws: Sequence[RawJunction], when: str, with_facility: bool
) -> dict[int, dict[int, Road]]:
    """For each junction (by position in `raws`), the roads that meet there:
    {osm_way_id: Road}. The route's own ways are among them; the caller tells
    them apart. A junction no segment touches has no entry."""
    if not raws:
        return {}
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    traits = has_trait_columns(schema)
    query = _ROADS_AT.format(
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
    arrays = [
        list(range(len(raws))),
        [raw.lon for raw in raws],
        [raw.lat for raw in raws],
    ]
    # `{tier}`'s placeholder sits in the lateral subquery, after the arrays.
    params = [*arrays, *([when] if with_facility else []), JUNCTION_RADIUS_DEG]
    found: dict[int, dict[int, Road]] = {}
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        for idx, way_id, tier, aadt, speed, lanes, oneway in cursor.fetchall():
            found.setdefault(idx, {})[way_id] = Road(
                tier=int(tier) if tier is not None else None,
                speed_mph=float(speed) if speed is not None else None,
                lanes=int(lanes) if lanes is not None else None,
                oneway=oneway,
                aadt=int(aadt) if aadt is not None else None,
            )
    return found


def _flag(entry: dict, key: str) -> bool:
    return bool((entry.get("edge") or {}).get(key))


def control_from_locate(answer: dict, raw: RawJunction) -> Control:
    """Who has the right of way at a junction, from `/locate`'s answer for its
    node: the node's signal flag, and the stop and yield flags of the directed
    edge the route arrives on against those of the other roads' edges."""
    nodes = answer.get("nodes") or []
    edges = answer.get("edges") or []
    mine = [e for e in edges if (e.get("edge_id") or {}).get("value") == raw.in_edge_id]
    if (nodes and nodes[0].get("traffic_signal")) or any(_flag(e, "traffic_signal") for e in mine):
        return Control.SIGNAL
    route_stops = any(_flag(e, "stop_sign") or _flag(e, "yield_sign") for e in mine)
    ways = {raw.in_way, raw.out_way}
    cross_stops = any(
        (_flag(e, "stop_sign") or _flag(e, "yield_sign"))
        for e in edges
        if (e.get("edge_info") or {}).get("way_id") not in ways
    )
    if route_stops and cross_stops:
        return Control.ALL_STOP
    if route_stops:
        return Control.STOP
    if cross_stops:
        return Control.CROSS_STOP
    return Control.NONE


def controls_at(
    raws: Sequence[RawJunction],
    positions: Sequence[int],
    locate: Callable[[dict], list[dict]],
) -> dict[int, Control]:
    """The control at each of the junctions at `positions` in `raws`, asked of
    the router in batches. A batch the router will not answer leaves its
    junctions at `Control.NONE` ("no signal"): the cost is then the unsignalised
    one, which is the cautious reading, and the route is still answered."""
    controls: dict[int, Control] = {}
    for start in range(0, len(positions), LOCATE_BATCH):
        chunk = positions[start : start + LOCATE_BATCH]
        payload = {
            "locations": [{"lon": raws[p].lon, "lat": raws[p].lat} for p in chunk],
            "verbose": True,
            "costing": "bicycle",
        }
        try:
            answers = locate(payload)
        except Exception as error:  # noqa: BLE001 - one batch failing is not the route failing
            logger.info("intersection controls unavailable for a batch: %s", error)
            break
        for position, answer in zip(chunk, answers, strict=False):
            controls[position] = control_from_locate(answer, raws[position])
    return controls


def build_junctions(
    raws: Sequence[RawJunction],
    roads: dict[int, dict[int, Road]],
    controls: dict[int, Control],
) -> list[Junction]:
    """The model's junctions: each raw one with its roads and its control."""
    junctions = []
    unknown = Road(None)
    for position, raw in enumerate(raws):
        here = roads.get(position, {})
        # Only roads the router also has at the node: a way that merely passes
        # near it (a sidepath beside the carriageway it follows) is not crossed.
        nearby = sorted(
            (
                road
                for way, road in here.items()
                if way not in (raw.in_way, raw.out_way) and road.tier is not None
            ),
            key=lambda road: -(road.tier or 0),
        )
        crossed = tuple(nearby[: raw.cross_road_count])
        junctions.append(
            Junction(
                m=raw.m,
                lon=raw.lon,
                lat=raw.lat,
                movement=raw.movement,
                incoming=here.get(raw.in_way, unknown),
                outgoing=here.get(raw.out_way, unknown),
                crossed=crossed,
                control=controls.get(position, Control.NONE),
                slip_lane=raw.slip_lane,
                marked_crossing=raw.marked_crossing,
                approach=raw.approach,
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
    """The route's junction events, in route order: the segment table says what
    meets at each junction, the router who has the right of way at the busy ones,
    and `routemaker.intersections` what it costs. `group` is the Mass Ride
    reading (colour by the crossed road's tier)."""
    raws = [raw for raw in raws if wanted(raw)]
    roads = roads_at(raws, when, with_facility)
    first = build_junctions(raws, roads, {})
    positions = [i for i, junction in enumerate(first) if needs_control(junction)]
    controls = controls_at(raws, positions, locate)
    return assess_route(build_junctions(raws, roads, controls), group)


def needs_control(junction: Junction) -> bool:
    """A junction is asked of the router only where who has the right of way
    changes its cost: a crossing of a busy road, a turn onto or off one, a slip
    lane. A neighbourhood junction costs nothing whatever its signs say, and
    riding along a busy road past side streets costs the same whoever stops."""
    from routemaker.intersections import Movement

    j = junction
    return (
        any(road.busy for road in j.crossed)
        or (j.outgoing.busy and not j.incoming.busy)
        or (j.incoming.busy and j.movement is Movement.LEFT)
        or (j.slip_lane and (j.incoming.busy or j.outgoing.busy))
    )
