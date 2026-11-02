"""How a walk is chosen among the router's ways, and the crossings it says (Stephen, 2026-11-02:
"Make sure to note crosswalks and prefer signalled crossings", "Add some penalty for more
dangerous crossings, especially sliplanes", "Signalled only against busy roads, similar to how
it's done by bike", "Also penalize walking along a road without a sidewalk, especially a busier
one").

Valhalla's pedestrian costing knows none of this: it charges a few seconds for crossing a
bigger road, never asks whether a signal stops its traffic, and prices a carriageway with no
sidewalk as it prices a sidewalk. So a walk asks the router for its other ways too
(`ALTERNATES`), traces each (`/trace_attributes`, one call a way), and takes the way whose
walking time plus these charges is least:

- A crossing of a busy road with no signal (`UNSIGNALLED_S`): a primary or secondary road
  (`BUSY_CLASSES`) costs two minutes, a trunk road or motorway (`SEVERE_CLASSES`) four, and a
  minute more where there is no crosswalk (`UNMARKED_S`). A quiet street is crossed anywhere
  for nothing, as a ride crosses one: a signal is sought only where the road is busy. The
  router names a crossed road's class alone (not its speed, lanes or count, which the bike
  junction model reads from the segment table), so the class is the busy test here.
- A slip lane crossed with no signal (`SLIP_LANE_S`): a minute more, whatever its class:
  turning traffic comes fast round it and seldom looks.
- Walking along a carriageway with no sidewalk mapped: each second on it costs
  `ROADSIDE_FACTORS` more by how busy the road is (`roadside_level`), a quarter more on a
  quiet street, as much again on a collector, three times more on a busy road.

A signal is the router's flag on the crossing's own nodes and edges, which a signalled
crosswalk carries (`highway=traffic_signals`, written onto `crossing=traffic_signals` nodes by
lua/routemaker_remap.lua). A crosswalk is a mapped crossing way (Valhalla's
`pedestrian_crossing`, from `footway=crossing`), marked or not.

Only the router's own ways are compared: where none of them passes the signal, the walk
crosses where the best of them does, and says so (`crossing_turns`). Where a trace fails or no
time is left, the router's first way is walked as it was, with no crossings said.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from routemaker.trace_junctions import CROSSING_USE, NOT_A_ROAD_USES, SLIP_LANE_USE

logger = logging.getLogger(__name__)

# How many other ways a walk asks the router for (Valhalla's `alternates`; the graphs' own
# `max_alternates` is 3).
ALTERNATES = 2

# What a walk's trace asks for.
TRACE_ATTRIBUTES = (
    "edge.length",
    "edge.use",
    "edge.road_class",
    "edge.sidewalk",
    "edge.speed_limit",
    "edge.lane_count",
    "edge.traffic_signal",
    "edge.names",
    "edge.begin_shape_index",
    "edge.end_shape_index",
    "node.traffic_signal",
    "node.intersecting_edge.use",
    "node.intersecting_edge.road_class",
    "node.intersecting_edge.driveability",
    "shape",
)

# Valhalla's uses that are not a carriageway: a walk on one is off the road.
WALKWAY_USES = frozenset(
    {
        "footway",
        "sidewalk",
        "path",
        "pedestrian",
        "cycleway",
        CROSSING_USE,
        "steps",
        "mountain_bike",
        "bridleway",
        "living_street",
        "elevator",
        "track",
    }
)

QUIET, MEDIUM, BUSY, SEVERE = 0, 1, 2, 3
SEVERE_CLASSES = frozenset({"motorway", "trunk"})
BUSY_CLASSES = frozenset({"primary", "secondary"})
MEDIUM_CLASSES = frozenset({"tertiary", "unclassified"})

UNSIGNALLED_S = {BUSY: 120.0, SEVERE: 240.0}
UNMARKED_S = 60.0
SLIP_LANE_S = 60.0
ROADSIDE_FACTORS = {QUIET: 0.25, MEDIUM: 1.0, BUSY: 3.0, SEVERE: 3.0}
# A road this fast (posted, km/h) or with this many lanes in the walk's direction is busy to
# walk along, whatever its class (`intersections.TRAFFIC_HEAVY_MPH`, 30 mph; two lanes a way,
# `TRAFFIC_MULTILANE_EACH_WAY`); from MEDIUM_KPH (25 mph) a collector.
BUSY_KPH = 48.0
MEDIUM_KPH = 40.0
BUSY_LANES = 2

# The crossings a walk says: at most this many (a walk is short).
MAX_CROSSINGS = 20


def roadside_level(edge: dict) -> int:
    """How busy a carriageway is to walk along with no sidewalk."""
    cls = str(edge.get("road_class") or "")
    if cls in SEVERE_CLASSES:
        return SEVERE
    speed = edge.get("speed_limit")
    speed = float(speed) if isinstance(speed, (int, float)) else 0.0
    lanes = edge.get("lane_count")
    lanes = int(lanes) if isinstance(lanes, (int, float)) else 1
    if cls in BUSY_CLASSES or speed >= BUSY_KPH or lanes >= BUSY_LANES:
        return BUSY
    if cls in MEDIUM_CLASSES or speed >= MEDIUM_KPH:
        return MEDIUM
    return QUIET


def crossing_level(classes: Sequence[str]) -> int:
    """How busy the roads crossed are, by the busiest one's class."""
    level = QUIET
    for cls in classes:
        if cls in SEVERE_CLASSES:
            return SEVERE
        if cls in BUSY_CLASSES:
            level = BUSY
        elif cls in MEDIUM_CLASSES and level < MEDIUM:
            level = MEDIUM
    return level


@dataclass(frozen=True)
class Crossing:
    """One road (or a slip lane and its road, at one crosswalk) the walk crosses."""

    m: float  # metres along the walk
    point: tuple[float, float]
    level: int
    signal: bool
    marked: bool  # by a crosswalk (a mapped crossing way)
    slip: bool
    # The names of the ways the walk is on either side of it: never the road crossed.
    own: frozenset[str] = frozenset()

    @property
    def penalty_s(self) -> float:
        if self.signal:
            return 0.0
        out = UNSIGNALLED_S.get(self.level, 0.0)
        if self.level >= BUSY and not self.marked:
            out += UNMARKED_S
        if self.slip:
            out += SLIP_LANE_S
        return out

    @property
    def said(self) -> bool:
        """Said in the walk's directions: every crosswalk, and any busy road crossed."""
        return self.marked or self.level >= BUSY or self.slip

    @property
    def control(self) -> str:
        if self.signal:
            return "signal"
        return "crosswalk" if self.marked else "none"


@dataclass(frozen=True)
class Reading:
    """A traced way's charges."""

    roadside_s: float = 0.0
    crossings: tuple[Crossing, ...] = field(default_factory=tuple)

    @property
    def penalty_s(self) -> float:
        return self.roadside_s + sum(c.penalty_s for c in self.crossings)


def _decode(encoded: str) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []
    index = lat = lon = 0
    while index < len(encoded):
        for axis in (0, 1):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        coordinates.append((lon / 1e6, lat / 1e6))
    return coordinates


def _roads(edge: dict) -> list[dict]:
    """The roads (open to cars) at the node `edge` arrives at, other than the walk's own."""
    node = edge.get("end_node") or {}
    return [
        other
        for other in node.get("intersecting_edges") or []
        if other.get("use") not in NOT_A_ROAD_USES and other.get("driveability") is not None
    ]


def _signal(edge: dict) -> bool:
    return bool(edge.get("traffic_signal") or (edge.get("end_node") or {}).get("traffic_signal"))


def _walkway(edge: dict) -> bool:
    return str(edge.get("use") or "") in WALKWAY_USES


def read(trace: dict, seconds_per_m: float) -> Reading:
    """The charges of one traced walk (`TRACE_ATTRIBUTES`; lengths in kilometres), its time on
    foot at `seconds_per_m`."""
    edges = trace.get("edges") or []
    shape = _decode(trace["shape"]) if isinstance(trace.get("shape"), str) else []
    starts: list[float] = []
    along = 0.0
    for edge in edges:
        starts.append(along)
        along += float(edge.get("length") or 0.0) * 1000.0

    def node_point(index: int) -> tuple[float, float] | None:
        end = edges[index].get("end_shape_index")
        if isinstance(end, int) and 0 <= end < len(shape):
            return shape[end]
        return None

    roadside = 0.0
    for edge in edges:
        if _walkway(edge) or str(edge.get("sidewalk") or "none") in ("left", "right", "both"):
            continue
        if str(edge.get("use") or "") in ("driveway", "alley", "parking_aisle", "ferry"):
            continue
        metres = float(edge.get("length") or 0.0) * 1000.0
        roadside += metres * seconds_per_m * ROADSIDE_FACTORS[roadside_level(edge)]

    crossings: list[Crossing] = []
    taken: set[int] = set()  # node indices (the end of edges[i]) already in a crossing
    i = 0
    while i < len(edges):
        if edges[i].get("use") != CROSSING_USE:
            i += 1
            continue
        first = i
        while i + 1 < len(edges) and edges[i + 1].get("use") == CROSSING_USE:
            i += 1
        last = i
        nodes = [n for n in range(first - 1, last + 1) if 0 <= n < len(edges) - 1]
        roads = [road for n in nodes for road in _roads(edges[n])]
        taken.update(nodes)
        i += 1
        if not roads:
            continue
        signal = any(_signal(edges[n]) for n in range(max(first - 1, 0), last + 1))
        middle = first if first < last else max(first - 1, 0)
        point = node_point(middle) or node_point(first)
        if point is None:
            continue
        crossings.append(
            Crossing(
                m=starts[middle] + float(edges[middle].get("length") or 0.0) * 1000.0,
                point=point,
                level=crossing_level([str(r.get("road_class") or "") for r in roads]),
                signal=signal,
                marked=True,
                slip=any(r.get("use") == SLIP_LANE_USE for r in roads),
                own=_names(edges[max(first - 1, 0) : last + 2]),
            )
        )
    for n in range(len(edges) - 1):
        if n in taken:
            continue
        here, there = edges[n], edges[n + 1]
        roads = _roads(here)
        if not roads:
            continue
        if _walkway(here) and _walkway(there):
            pass  # a path or sidewalk across a road with no crossing mapped
        elif not _walkway(here) and not _walkway(there):
            # Along a carriageway, straight on past a side road: it crosses that road. A turn
            # off it is not read as a crossing (it may be onto the near side).
            if not _same_way(here, there):
                continue
        else:
            continue
        point = node_point(n)
        if point is None:
            continue
        crossings.append(
            Crossing(
                m=starts[n] + float(here.get("length") or 0.0) * 1000.0,
                point=point,
                level=crossing_level([str(r.get("road_class") or "") for r in roads]),
                signal=_signal(here),
                marked=False,
                slip=any(r.get("use") == SLIP_LANE_USE for r in roads),
                own=_names([here, there]),
            )
        )
    crossings.sort(key=lambda c: c.m)
    return Reading(round(roadside, 1), tuple(_merged(crossings)))


# Two crossings this close along the walk are one road's two halves (a divided road, a
# crosswalk split by an island): one crossing, priced and said once.
SAME_CROSSING_M = 30.0


def _merged(crossings: list[Crossing]) -> list[Crossing]:
    """`crossings` (in order along the walk) with each run of crossings within SAME_CROSSING_M
    of the one before made one: its busiest road, a signal where either half has one (a
    junction's signal is often mapped on one node), a crosswalk where either is. A slip lane
    is never merged with its road: each is crossed and said on its own."""
    out: list[Crossing] = []
    for crossing in crossings:
        last = out[-1] if out else None
        if (
            last is not None
            and crossing.m - last.m <= SAME_CROSSING_M
            and crossing.slip == last.slip
        ):
            out[-1] = Crossing(
                m=last.m,
                point=last.point,
                level=max(last.level, crossing.level),
                signal=last.signal or crossing.signal,
                marked=last.marked or crossing.marked,
                slip=last.slip,
                own=last.own | crossing.own,
            )
            continue
        out.append(crossing)
    return out


def _names(edges: Sequence[dict]) -> frozenset[str]:
    return frozenset(
        n for edge in edges for n in edge.get("names") or [] if isinstance(n, str) and n
    )


def _same_way(a: dict, b: dict) -> bool:
    names_a = {n for n in a.get("names") or [] if isinstance(n, str)}
    names_b = {n for n in b.get("names") or [] if isinstance(n, str)}
    if names_a or names_b:
        return bool(names_a & names_b)
    return a.get("road_class") == b.get("road_class")


Ask = Callable[[str, dict], object]


@dataclass(frozen=True)
class Chosen:
    """The walk taken: the router's leg, and the crossings it says (`crossing_turns`)."""

    leg: dict
    crossings: tuple[Crossing, ...] = ()
    # The charges that chose it, for the log and the tests: (way's index, seconds) a way.
    scores: tuple[tuple[int, float], ...] = ()


def trace_payload(leg: dict, costing_options: dict | None) -> dict:
    return {
        "encoded_polyline": leg.get("shape", ""),
        "shape_match": "walk_or_snap",
        "costing": "pedestrian",
        "costing_options": costing_options or {},
        "filters": {"attributes": list(TRACE_ATTRIBUTES), "action": "include"},
        "units": "kilometers",
    }


def _legs(answer: dict) -> list[dict]:
    out = []
    for trip in [answer.get("trip") or {}] + [
        (alt or {}).get("trip") or {} for alt in answer.get("alternates") or []
    ]:
        legs = trip.get("legs") or []
        if len(legs) == 1 and isinstance(legs[0].get("shape"), str):
            out.append(legs[0])
    return out


def choose(answer: dict, ask: Ask, costing_options: dict | None = None) -> Chosen | None:
    """The router's way (of `answer`'s, with its `alternates`) whose walking time and charges
    are least, with its crossings. `ask(action, payload)` asks the router and gives its
    answer, or None where it cannot (refused, out of time). None where `answer` has no leg."""
    legs = _legs(answer)
    if not legs:
        return None
    best: tuple[float, int, Reading] | None = None
    scores: list[tuple[int, float]] = []
    for index, leg in enumerate(legs):
        trace = ask("trace_attributes", trace_payload(leg, costing_options))
        if not isinstance(trace, dict) or not trace.get("edges"):
            if index == 0:
                return Chosen(legs[0])
            continue
        summary = leg.get("summary") or {}
        seconds = float(summary.get("time") or 0.0)
        metres = float(summary.get("length") or 0.0) * 1000.0
        try:
            reading = read(trace, seconds / metres if metres > 0 else 0.75)
        except (TypeError, ValueError, KeyError, IndexError) as error:
            logger.info("a walk's trace could not be read: %s", error)
            if index == 0:
                return Chosen(legs[0])
            continue
        score = seconds + reading.penalty_s
        scores.append((index, round(score, 1)))
        if best is None or score < best[0]:
            best = (score, index, reading)
    assert best is not None
    _score, index, reading = best
    return Chosen(legs[index], reading.crossings, tuple(scores))


def crossing_turns(crossings: Sequence[Crossing], ask: Ask) -> list[dict]:
    """The crossings a walk says (`Crossing.said`), as its turns carry them: {"movement":
    "cross", "street" (the road crossed, by `/locate` on the cars' graph; None where it has no
    name or none is found), "point", "control" ("signal", "crosswalk" or "none"), "busy",
    "slip"}."""
    said = [c for c in crossings if c.said][:MAX_CROSSINGS]
    if not said:
        return []
    names: list[str | None] = [None] * len(said)
    answer = ask(
        "locate",
        {
            "locations": [{"lon": c.point[0], "lat": c.point[1], "radius": 12} for c in said],
            "costing": "auto",
            "verbose": True,
        },
    )
    if isinstance(answer, list):
        for i, found in enumerate(answer[: len(said)]):
            names[i] = _road_name(found, said[i].own)
    return [
        {
            "movement": "cross",
            "street": names[i],
            "point": [round(c.point[0], 6), round(c.point[1], 6)],
            "control": c.control,
            "busy": c.level >= BUSY,
            "slip": c.slip,
        }
        for i, c in enumerate(said)
    ]


def _road_name(found, own: frozenset[str] = frozenset()) -> str | None:
    """The name of the nearest road in one `/locate` answer that is not one the walk is on
    (`own`): the road crossed."""
    if not isinstance(found, dict):
        return None
    edges = [e for e in found.get("edges") or [] if isinstance(e, dict)]
    edges.sort(key=lambda e: float(e.get("distance") or 0.0))
    for entry in edges:
        classification = (entry.get("edge") or {}).get("classification") or {}
        if classification.get("use") not in (None, "road", SLIP_LANE_USE):
            continue
        names = [
            n for n in (entry.get("edge_info") or {}).get("names") or [] if isinstance(n, str) and n
        ]
        if names and not own.intersection(names):
            return names[0]
    return None
