"""The barriers on a route, and Cargo and Tandem planned around the impassable ones.

Backlog 2026-11-12 item 12 (area 07 items 1, 2 and 11), and OWNER-DECISIONS 345 (the owner,
2026-11-08, chose "Only impassable ones" for Tandem). Until now the router knew a barrier and
the rider did not: the remap makes every stile, kissing gate, turnstile, cycle barrier and
narrow bollard one kind of gate (lua/routemaker_remap.lua `remap_node`), Cargo and Tandem pay
900 s there "unless there is no other way" (`presets.CARGO_GATE_PENALTY_S`), and no sentence
named it. A 15-minute charge still loses to a long detour, so a tandem could be sent to a stile.

Two things here, with no map rebuild:

- `reading`: every barrier and flight of steps on a route's line, with what it is, its mapped
  width (or that none is mapped: "no barrier" must never read as "none mapped") and how far
  along the route it is. The list is a committed snapshot of the extract's barrier nodes
  (`geodata/barriers.json`, written by `scripts/barrier_census.py --json` on the build host,
  as the water and food snapshots are), so the graph's single "gate" does not have to be split.
- `settle`: on Cargo and Tandem (`PRESETS`), where the route answered crosses an impassable
  barrier (`impassable`), the plan's own request is asked again with that barrier excluded
  (`exclude_locations`, as Mountain Bike's level rounds steer off a harder trail), a few rounds,
  and the route crossing the fewest is kept. Where none clears them all the answer says so and
  names the barrier in the way (`limited: "no_way_round"`).

A barrier is matched to a route where the line passes through the barrier's node (within
MATCH_M) and along the barrier's own way beside it (within MATCH_M of one of its exclusion
points), so a route along a road past a trail's end, where the trail's bollard sits on the
shared node, is not said to cross it. The exclusion points are on the barrier's own way, a few
metres from it (on a trail's way where the barrier is on a trail), so excluding one closes that
way through the barrier and leaves the road beside it open.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from routemaker.geo import haversine_lonlat

logger = logging.getLogger(__name__)

BARRIERS_PATH = Path(__file__).resolve().parent / "geodata" / "barriers.json"

# The ride types planned around impassable barriers: Cargo and Tandem (OWNER-DECISIONS 345; the
# owner's 2026-11-08 gate ruling: "was intended just for Tandem, and possibly cargo too").
PRESETS = frozenset({"cargo", "tandem"})

# What a bicycle is lifted over or squeezed through (`M.HARD_BARRIERS` in the remap, and the
# full-height turnstile): impassable for a cargo bike or tandem whatever its width.
LIFTED = frozenset({"stile", "kissing_gate", "turnstile", "full-height_turnstile"})
# A gap narrower than this (metres) is impassable for a cargo bike or tandem: OWNER-DECISIONS
# 345's "gaps under 1.0 m". A cargo box is about 0.6-0.9 m across; the figure is the owner's
# list, not a measurement.
NARROW_M = 1.0
# Kinds whose mapped width is the gap a rider passes through.
GAPS = frozenset({"bollard", "cycle_barrier", "block", "motorcycle_barrier"})
# Kinds named as a gate.
GATES = frozenset({"gate", "swing_gate", "lift_gate", "sliding_gate", "wicket_gate", "chain"})
STEPS = "steps"

# Metres within which a line passes through a barrier's node. The shape carries the graph's own
# vertices to six decimals (about 0.1 m), so this is slack for rounding only. Our default.
MATCH_M = 1.5
# Metres from a barrier at which the route must also pass the barrier's exclusion point (its own
# way, beside it), so a route along a road past a trail's end is not counted. Our default.
ALONG_M = 3.0
# Rounds of asking again round impassable barriers. Our default, unmeasured; as many as
# Mountain Bike's level rounds would allow, fewer since each round names its barriers exactly.
ROUNDS = 4
# Valhalla's own limit is 200 `exclude_locations` (valhalla/*.json); a round adds at most this
# many, and the whole list is kept under EXCLUDE_CAP with the plan's other exclusions.
EXCLUDE_CAP = 150
# A barrier this close to one of the plan's own points is not excluded: the router must be able
# to leave and arrive. It is still named. Our default, unmeasured.
CLEARANCE_M = 25.0

# Grid cell for the lookup, in degrees (about 110 m of latitude, 85 m of longitude here).
_CELL = 0.001


@dataclass(frozen=True)
class Barrier:
    """One barrier node, or one flight of steps (kind `steps`, located at its middle)."""

    kind: str
    lon: float
    lat: float
    width_m: float | None
    # Points on the barrier's own way(s) beside it: matched against the line, and excluded.
    beside: tuple[tuple[float, float], ...]
    # A flight of steps' vertices; empty for a node barrier.
    line: tuple[tuple[float, float], ...] = ()


def impassable(barrier: Barrier) -> bool:
    """Whether a cargo bike or tandem cannot pass: lifted or squeezed through, steps, or a gap
    mapped narrower than NARROW_M (an unmapped width is not called impassable: it is named
    as unmapped instead)."""
    if barrier.kind in LIFTED or barrier.kind == STEPS:
        return True
    return barrier.width_m is not None and barrier.width_m < NARROW_M


def word(barrier: Barrier) -> str:
    """The group a barrier is counted in, for the route's one line (the front end words it):
    stile, kissing_gate, turnstile, steps, narrow_gap, bollard, cycle_barrier, gate or other."""
    if barrier.kind in LIFTED:
        return barrier.kind if barrier.kind != "full-height_turnstile" else "turnstile"
    if barrier.kind == STEPS:
        return STEPS
    if barrier.width_m is not None and barrier.width_m < NARROW_M:
        return "narrow_gap"
    if barrier.kind in ("bollard", "cycle_barrier"):
        return barrier.kind
    if barrier.kind in GATES:
        return "gate"
    return "other"


def width_unmapped(barrier: Barrier) -> bool:
    """A gap whose width no one has mapped: said as unmapped, never as clear."""
    return barrier.kind in GAPS and barrier.width_m is None


# -- the snapshot ----------------------------------------------------------------------------


def _cell(lon: float, lat: float) -> tuple[int, int]:
    return (math.floor(lon / _CELL), math.floor(lat / _CELL))


@dataclass
class Index:
    barriers: list[Barrier]
    nodes: dict[tuple[int, int], list[int]]
    steps: dict[tuple[int, int], list[tuple[int, int]]]  # cell -> (barrier index, vertex index)
    built: str | None

    @property
    def loaded(self) -> bool:
        return bool(self.barriers)


def index_of(data: dict) -> Index:
    """The lookup for a snapshot (`geodata/barriers.json`)."""
    barriers: list[Barrier] = []
    nodes: dict[tuple[int, int], list[int]] = {}
    steps: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for row in data.get("barriers") or []:
        lon, lat, kind, width, beside = row
        barriers.append(
            Barrier(
                kind=str(kind),
                lon=float(lon),
                lat=float(lat),
                width_m=None if width is None else float(width),
                beside=tuple((float(x), float(y)) for x, y in beside),
            )
        )
        nodes.setdefault(_cell(lon, lat), []).append(len(barriers) - 1)
    for line in data.get("steps") or []:
        vertices = tuple((float(x), float(y)) for x, y in line)
        if len(vertices) < 2:
            continue
        # The middle of the flight: its middle vertex, or its middle segment's midpoint.
        a, b = vertices[(len(vertices) - 1) // 2], vertices[len(vertices) // 2]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        first_mid = (
            (vertices[0][0] + vertices[1][0]) / 2,
            (vertices[0][1] + vertices[1][1]) / 2,
        )
        barriers.append(
            Barrier(
                kind=STEPS, lon=mid[0], lat=mid[1], width_m=None, beside=(first_mid,),
                line=vertices,
            )
        )  # fmt: skip
        for j, (x, y) in enumerate(vertices):
            steps.setdefault(_cell(x, y), []).append((len(barriers) - 1, j))
    return Index(barriers=barriers, nodes=nodes, steps=steps, built=data.get("built"))


@lru_cache(maxsize=1)
def snapshot() -> Index:
    """The committed snapshot, read once. An absent or empty file is an empty index, which the
    answer reports as `data: false` (never as "no barriers")."""
    try:
        data = json.loads(BARRIERS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("barriers: no snapshot at %s", BARRIERS_PATH)
        data = {}
    return index_of(data)


# -- matching a line -------------------------------------------------------------------------


def _near(index: dict, lon: float, lat: float) -> Iterable:
    cx, cy = _cell(lon, lat)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            yield from index.get((cx + dx, cy + dy), ())


def _to_segment_m(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Metres from p to the segment a-b, on a local flat projection (short segments only)."""
    k = math.cos(math.radians(p[1]))
    ax, ay = (a[0] - p[0]) * k, a[1] - p[1]
    bx, by = (b[0] - p[0]) * k, b[1] - p[1]
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / span))
    x, y = ax + t * dx, ay + t * dy
    return math.hypot(x, y) * 111_195.0


@dataclass(frozen=True)
class Crossing:
    barrier: Barrier
    at_m: float  # metres along the line


def crossings(line: Sequence[Sequence[float]], index: Index | None = None) -> list[Crossing]:
    """Every barrier and flight of steps the line rides through, in order along it."""
    index = snapshot() if index is None else index
    if not index.loaded or len(line) < 2:
        return []
    found: dict[int, float] = {}
    along = 0.0
    previous_steps: dict[int, int] = {}
    for i, (lon, lat) in enumerate(line):
        if i:
            along += haversine_lonlat(line[i - 1], line[i])
        here = (lon, lat)
        for b in _near(index.nodes, lon, lat):
            if b in found:
                continue
            barrier = index.barriers[b]
            if haversine_lonlat(here, (barrier.lon, barrier.lat)) > MATCH_M:
                continue
            sides = [(line[j], line[j + 1]) for j in (i - 1, i) if 0 <= j < len(line) - 1]
            if any(_to_segment_m(p, a, z) <= ALONG_M for p in barrier.beside for a, z in sides):
                found[b] = along
        steps_here: dict[int, int] = {}
        for b, j in _near(index.steps, lon, lat):
            vertex = index.barriers[b].line[j]
            if haversine_lonlat(here, vertex) <= MATCH_M:
                steps_here[b] = j
        for b, j in steps_here.items():
            if b not in found and abs(previous_steps.get(b, -9) - j) == 1:
                found[b] = along
        previous_steps = steps_here
    return [
        Crossing(index.barriers[b], at) for b, at in sorted(found.items(), key=lambda item: item[1])
    ]


def reading(line: Sequence[Sequence[float]], index: Index | None = None) -> dict:
    """What the answer says of a route's barriers (`barriers` on each route body).

    `data` is false where no snapshot is loaded: the front end then says nothing rather than
    "none". `counts` groups them by `word`; `unmapped_width` counts the bollards and cycle
    barriers whose gap is not mapped; `items` lists each, in order along the route."""
    index = snapshot() if index is None else index
    if not index.loaded:
        return {"data": False, "counts": {}, "impassable": 0, "unmapped_width": 0, "items": []}
    found = crossings(line, index)
    counts: dict[str, int] = {}
    for crossing in found:
        counts[word(crossing.barrier)] = counts.get(word(crossing.barrier), 0) + 1
    return {
        "data": True,
        "built": index.built,
        "counts": counts,
        "impassable": sum(impassable(c.barrier) for c in found),
        "unmapped_width": sum(width_unmapped(c.barrier) for c in found),
        "items": [
            {
                "kind": c.barrier.kind,
                "word": word(c.barrier),
                "lon": round(c.barrier.lon, 6),
                "lat": round(c.barrier.lat, 6),
                "width_m": c.barrier.width_m,
                "width_mapped": not width_unmapped(c.barrier),
                "impassable": impassable(c.barrier),
                "at_m": round(c.at_m, 1),
            }
            for c in found
        ],
    }


# -- planning round impassable barriers ------------------------------------------------------


def applies(preset_name: str) -> bool:
    return preset_name in PRESETS


def trip_line(trip: dict) -> list[tuple[float, float]]:
    from .routing import decode_polyline6

    line: list[tuple[float, float]] = []
    for leg in trip.get("legs") or []:
        shape = decode_polyline6(leg.get("shape", ""))
        line.extend(shape[1:] if line else shape)
    return line


def blocking(line: Sequence[Sequence[float]], index: Index | None = None) -> list[Barrier]:
    return [c.barrier for c in crossings(line, index) if impassable(c.barrier)]


def exclusion_points(
    found: Sequence[Barrier], points: Sequence[Sequence[float]]
) -> tuple[list[tuple[float, float]], list[Barrier]]:
    """The points that close each barrier's way through it, and the barriers left in because
    they are within CLEARANCE_M of one of the plan's own points."""
    out: list[tuple[float, float]] = []
    kept: list[Barrier] = []
    for barrier in found:
        here = (barrier.lon, barrier.lat)
        if any(haversine_lonlat(here, (p[0], p[1])) < CLEARANCE_M for p in points):
            kept.append(barrier)
            continue
        out.extend(barrier.beside)
    return out, kept


def settle(
    trip: dict,
    request: dict,
    variant: str,
    deadline,
    points: Sequence[Sequence[float]],
    level_excludes: list | None = None,
    keeps: Callable[[dict], bool] | None = None,
    index: Index | None = None,
) -> tuple[dict, dict]:
    """The route a Cargo or Tandem plan answers, and what the answer says of the rounds
    (`barrier_round`). As `easy_mtb.settle`: `level_excludes` takes the exclusions the answered
    route was asked with, so the passes after this one keep the barriers out; `keeps` says
    whether a round's route may replace a route the calm search chose."""
    from . import routing

    index = snapshot() if index is None else index
    info: dict = {"rounds": 0, "impassable": 0, "limited": None, "in_the_way": []}
    if not index.loaded:
        info["limited"] = "no_data"
        return trip, info
    best_trip = trip
    best = blocking(trip_line(trip), index)
    current = best
    excludes: list[tuple[float, float]] = []
    best_excludes: list[tuple[float, float]] = []
    others = [e for e in (request.get("exclude_locations") or []) if isinstance(e, dict)]
    base = {k: v for k, v in request.items() if k not in ("alternates", "exclude_locations")}
    at_stop: list[Barrier] = []
    while current and info["rounds"] < ROUNDS:
        more, kept = exclusion_points(current, points)
        at_stop.extend(b for b in kept if b not in at_stop)
        more = [p for p in more if p not in excludes]
        if not more:
            break
        excludes = (excludes + more)[-EXCLUDE_CAP:]
        info["rounds"] += 1
        asked = others[: max(0, 200 - len(excludes))] + [{"lon": x, "lat": y} for x, y in excludes]
        try:
            answer, _timed_out = routing._route(
                variant, {**base, "exclude_locations": asked}, deadline
            )
        except routing.RouterRefused:
            info["limited"] = "no_way_round"
            break
        except (routing.DeadlineExceeded, routing.RouterUnavailable):
            info["limited"] = "time"
            break
        again = answer.get("trip") or {}
        current = blocking(trip_line(again), index)
        if len(current) < len(best) and (keeps is None or keeps(again)):
            best_trip, best = again, current
            best_excludes = list(excludes)
    if level_excludes is not None:
        level_excludes.extend({"lon": x, "lat": y} for x, y in best_excludes)
    info["impassable"] = len(best)
    if best and info["limited"] is None:
        info["limited"] = "at_stop" if all(b in at_stop for b in best) else "no_way_round"
    info["in_the_way"] = [
        {"kind": b.kind, "word": word(b), "lon": round(b.lon, 6), "lat": round(b.lat, 6)}
        for b in best
    ]
    logger.info("barrier round: %s", {k: v for k, v in info.items() if k != "in_the_way"})
    return best_trip, info


def reread(trip: dict, info: dict, index: Index | None = None) -> None:
    """`info` brought up to date with the route answered, where a pass after `settle` changed
    it: the impassable barriers on it now, the reason kept where some remain."""
    index = snapshot() if index is None else index
    if not index.loaded:
        return
    best = blocking(trip_line(trip), index)
    info["impassable"] = len(best)
    info["in_the_way"] = [
        {"kind": b.kind, "word": word(b), "lon": round(b.lon, 6), "lat": round(b.lat, 6)}
        for b in best
    ]
    if not best:
        info["limited"] = None
    elif info.get("limited") is None:
        info["limited"] = "no_way_round"
