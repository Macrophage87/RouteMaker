"""A ride's loop from a start and a distance ("30 mile loop from here"; the improvement backlog of
2026-11-12, item 5, which Stephen approved: "Let's get the top 12"). Run has had one since
2026-11-02 (`core.run_plan.target_loop`); this is the same idea for the bike ride types that plan
loops, answered as two or three shapes to pick from rather than one route.

How the shapes are found, the implementation's defaults stated here so they can be argued with
(all of them our default, none measured):

- Shapes: an equilateral triangle from the start in each of `BEARINGS` (six, 60 degrees apart):
  out on the bearing to the first corner, across to the second, and home. Its sides are sized so
  the ride is about the target: first from `ROUTED_PER_STRAIGHT`, then from the median of what
  the triangles already ridden came back as, as Run's loop is sized.
- Each triangle is one `/route` on the ride type's own graph and costing (`stoporder.ride_graph`:
  its traffic and hills sliders, ride time, assist, trails off, the rider's speed), with the
  closures in force and the roads the rider marked closed left out (`stoporder.ride_exclusions`).
  This is the router's own way round, not the full plan's search: the figures on a shape are
  "about" until it is picked and planned (`api.route`, an ordinary loop through its corners).
- A triangle whose ride is outside `TOLERANCE` of the target is sized again from what it rode, up
  to `RESIZES` rounds, the nearest ones first.
- The shapes kept: those within `TOLERANCE`, else the nearest; at most `SHAPES`, each heading at
  least `APART_DEG` from the others (two triangles 60 degrees apart share a side), fewest
  out-and-back spurs first (`run_plan.self_overlap` over `refine.LOOP_OVERLAP_OK`), then the most
  quiet riding (LTS 1 and 2, read by tracing the kept shapes on the stress table as a plan is).
- A shape's corners are where its ride turns, on the road it rode (the leg ends of its route),
  so planning it again through them as via points keeps to the same roads.

Nothing is stored and nothing is logged with a point in it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from routemaker.geo import Point, haversine

from . import dedodge, geocode, parallel, presets, refine, routing, run_plan, stoporder

logger = logging.getLogger(__name__)

METRES_PER_MILE = 1609.344
# The loop's length: 3 mi to 100 mi (our default, unmeasured). A 100 mi triangle is about 77 mi
# of straight sides, inside a plan's span (`api.MAX_SPAN_M`) and its long-ride confirmation
# (`api.CONFIRM_SPAN_M`), so the picked shape plans as an ordinary loop.
TARGET_MIN_M = round(3 * METRES_PER_MILE)
TARGET_MAX_M = round(100 * METRES_PER_MILE)

BEARINGS = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)
ROUTED_PER_STRAIGHT = 1.3
# What one triangle's ride may be read as for its straight sides (Run's `run_plan.RATIO_RANGE` is
# 1.0 to 3.5; a ride's roads wind less than a run's paths: our default), and how far one resize
# may scale it (as Run's `run_plan.RESIZE_RANGE`).
RATIO_RANGE = (1.0, 3.0)
RESIZE_RANGE = (0.5, 2.0)
TOLERANCE = 0.12
RESIZES = 2
SHAPES = 3
# Two kept shapes' headings (the middle of their triangle) at least this far apart.
APART_DEG = 90.0
# The whole search's time, inside a plan's budget (`routing.PLAN_BUDGET_S` less its reserve),
# and the least left worth starting another round of calls with.
BUDGET_S = routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S
LOW_S = 3.0
# The shape drawn on the map: a point every this many metres at most.
DRAWN_STEP_M = 60.0


class NoLoop(Exception):
    """No loop could be found from this start (the router rode none of the triangles)."""


@dataclass
class Shape:
    """One triangle ridden: its corners, the router's line round it, and its figures."""

    bearing: float
    side_m: float
    corners: list[tuple[float, float]]
    line: list[tuple[float, float]]
    metres: float
    climb_m: float
    spur: float
    quiet_m: float | None = None
    busy_m: float | None = None
    # Each leg's own line (start to first corner, across, home), traced leg by leg as a plan's.
    legs: list[list[tuple[float, float]]] = field(default_factory=list)
    # The graph that answered (a twin that is down falls back, `stoporder._ask`): traced there.
    graph: str | None = None

    @property
    def heading(self) -> float:
        """The way the loop goes out: the middle of its triangle."""
        return (self.bearing + 30.0) % 360.0


@dataclass
class Search:
    """What the search tried, for the answer's note."""

    tried: int = 0
    resized: int = 0
    traced: int = 0
    # Triangles the router did not answer (down, or out of time), apart from those it refused.
    unanswered: int = 0
    ran_short: bool = False
    ratios: list[float] = field(default_factory=list)


# One /route: its answer, and the graph that gave it.
Ask = Callable[[dict, float], tuple[dict, str | None]]


def triangle(
    start: Sequence[float], bearing_deg: float, side_m: float
) -> list[tuple[float, float]]:
    """The loop's points: the start, two corners, and the start again."""
    return run_plan.triangle(start, bearing_deg, side_m)


def angle_between(a: float, b: float) -> float:
    gap = abs(a - b) % 360.0
    return min(gap, 360.0 - gap)


def thinned(line: Sequence[tuple[float, float]], step_m: float = DRAWN_STEP_M) -> list:
    """`line` with a point every `step_m` at most, its ends kept, to 5 places (about a metre)."""
    if len(line) < 3:
        return [[round(x, 5), round(y, 5)] for x, y in line]
    kept = [line[0]]
    since = 0.0
    for a, b in zip(line, line[1:], strict=False):
        since += haversine(Point(*a), Point(*b))
        if since >= step_m:
            kept.append(b)
            since = 0.0
    if kept[-1] != line[-1]:
        kept.append(line[-1])
    return [[round(x, 5), round(y, 5)] for x, y in kept]


def rank(shape: Shape, target_m: float) -> tuple:
    """A shape's place: near the target first (off it, the nearest), then fewest spurs, then the
    most quiet riding (unread counts as none), then the nearest."""
    off = abs(shape.metres - target_m) / target_m
    near = off <= TOLERANCE
    quiet = (shape.quiet_m or 0.0) / shape.metres if shape.metres > 0 else 0.0
    return (not near, 0.0 if near else off, shape.spur > refine.LOOP_OVERLAP_OK, -quiet, off)


def pick(shapes: Sequence[Shape], target_m: float, count: int = SHAPES) -> list[Shape]:
    """Up to `count` shapes, best first (`rank`), each heading `APART_DEG` from those kept. A
    shape off the target is kept only where none near it is, so a far one never sits under a
    near one as if it were as good."""
    ordered = sorted(shapes, key=lambda s: rank(s, target_m))
    kept: list[Shape] = []
    for shape in ordered:
        if kept and rank(shape, target_m)[0] and not rank(kept[0], target_m)[0]:
            break
        if all(angle_between(shape.heading, k.heading) >= APART_DEG for k in kept):
            kept.append(shape)
        if len(kept) == count:
            break
    return kept


class Router:
    """The ride's graph for one search, every call inside its budget. `ask(payload, cap_s)` is
    one /route and the graph that answered (tests give their own); `trace(shape, cap_s)` gives
    the shape's metres per stress key, or None where it cannot be read."""

    def __init__(
        self,
        until: float,
        ask: Ask,
        trace: Callable[[list, float], dict | None] | None = None,
    ) -> None:
        self.until = until
        self.ask = ask
        self.trace = trace

    def left(self) -> float:
        return self.until - routing.clock()

    def low(self) -> bool:
        return self.left() < LOW_S


def ridden(router: Router, start, bearing: float, side_m: float, payload_of) -> Shape | None:
    """One triangle on the router, or None where it rode none (a corner off the map or with no
    way to it)."""
    points = triangle(start, bearing, side_m)
    if not all(geocode.inside(lon, lat) for lon, lat in points[1:3]):
        return None
    try:
        answer, graph = router.ask(payload_of(points), max(router.left(), 0.1))
        trip = (answer or {}).get("trip") or {}
    except (routing.RouterRefused, routing.NoRoute):
        return None
    legs = trip.get("legs") or []
    if len(legs) != 3:
        return None
    parts = [routing.decode_polyline6(leg.get("shape", "")) for leg in legs]
    if any(len(part) < 2 for part in parts):
        return None
    line: list[tuple[float, float]] = []
    for part in parts:
        line.extend(part if not line else part[1:])
    metres = routing._trip_length_m(trip)
    if metres <= 0:
        return None
    return Shape(
        bearing=bearing,
        side_m=side_m,
        # Where each leg sets off: the start and the corners, on the road ridden.
        corners=[tuple(part[0]) for part in parts],
        line=line,
        legs=parts,
        metres=metres,
        climb_m=routing._climb_of(trip),
        spur=run_plan.self_overlap(line),
        graph=graph,
    )


def search(
    router: Router, start, target_m: float, payload_of, count: int = SHAPES
) -> tuple[list[Shape], Search]:
    """The shapes for a loop of about `target_m` from `start` (the module's rules). Raises NoLoop
    where the router rode none, RouterUnavailable where it answered none."""
    note = Search()
    found: dict[float, Shape] = {}  # each bearing's latest ride
    every: list[Shape] = []

    def side_for() -> float:
        ratios = sorted(note.ratios)
        ratio = ratios[len(ratios) // 2] if ratios else ROUTED_PER_STRAIGHT
        return target_m / (3.0 * ratio)

    def ride_all(asks: list[tuple[float, float]]) -> None:
        futures = [
            parallel.submit(ridden, router, start, bearing, side, payload_of)
            for bearing, side in asks
        ]
        for future in futures:
            note.tried += 1
            try:
                # Read so that a cancelled request stops here (`routing.await_future`).
                shape = routing.await_future(future)
            except routing.PlanCancelled:
                raise
            except (routing.RouterUnavailable, routing.DeadlineExceeded):
                note.unanswered += 1
                shape = None
            except Exception:  # noqa: BLE001 - one triangle's failure is no shape, not no loop
                logger.info("bike loop: a triangle could not be ridden", exc_info=True)
                shape = None
            if shape is None:
                continue
            low, high = RATIO_RANGE
            note.ratios.append(min(max(shape.metres / (3.0 * shape.side_m), low), high))
            found[shape.bearing] = shape
            every.append(shape)

    first = side_for()
    ride_all([(bearing, first) for bearing in BEARINGS])
    if not every:
        if note.unanswered == note.tried:
            raise routing.RouterUnavailable("the router answered none of the loop's triangles")
        raise NoLoop("No loop could be found from this start.")
    for _ in range(RESIZES):
        if router.low():
            note.ran_short = True
            break
        off = [
            shape for shape in found.values() if abs(shape.metres - target_m) / target_m > TOLERANCE
        ]
        if not off:
            break
        resize: list[tuple[float, float]] = []
        for shape in sorted(off, key=lambda s: abs(s.metres - target_m)):
            low, high = RESIZE_RANGE
            size = shape.side_m * min(max(target_m / shape.metres, low), high)
            if abs(size - shape.side_m) >= 1.0:
                resize.append((shape.bearing, size))
        if not resize:
            break
        note.resized += len(resize)
        ride_all(resize)
    kept = pick(every, target_m, count)
    if router.trace is not None:
        # The quiet riding of the shapes kept (the figure each shape shows), and their order
        # again with it: a quieter one may come first.
        candidates = kept
        traced = [
            (shape, parallel.submit(router.trace, shape, max(router.left(), 0.1)))
            for shape in candidates
            if not router.low()
        ]
        if len(traced) < len(candidates):
            note.ran_short = True
        for shape, future in traced:
            try:
                metres = routing.await_future(future)
            except routing.PlanCancelled:
                raise
            except Exception:  # noqa: BLE001 - unread is no figure, not no loop
                logger.info("bike loop: a shape could not be traced", exc_info=True)
                metres = None
            if not metres:
                continue
            note.traced += 1
            shape.quiet_m = metres.get("1", 0.0) + metres.get("2", 0.0)
            shape.busy_m = metres.get("3", 0.0) + metres.get("4", 0.0) + metres.get("5", 0.0)
        kept = pick(candidates, target_m, count)
    return kept, note


def shape_out(shape: Shape, target_m: float) -> dict:
    """One shape as the answer gives it: the points to plan it through (the start, its two
    corners and the start again, the corners via points) and its figures."""
    start, first, second = shape.corners[:3]
    points = [list(start), list(first), list(second), list(start)]
    quiet = (
        None
        if shape.quiet_m is None or shape.metres <= 0
        else round(100.0 * shape.quiet_m / shape.metres)
    )
    return {
        "points": [[round(x, 6), round(y, 6)] for x, y in points],
        "via_points": [1, 2],
        "heading_deg": round(shape.heading),
        "distance_m": round(shape.metres, 1),
        "climb_m": round(shape.climb_m, 1),
        "quiet_pct": quiet,
        "busy_m": None if shape.busy_m is None else round(shape.busy_m, 1),
        "near_target": abs(shape.metres - target_m) / target_m <= TOLERANCE,
        "spur_pct": round(100.0 * shape.spur),
        "geometry": {"type": "LineString", "coordinates": thinned(shape.line)},
    }


# --- On the real router -----------------------------------------------------------------------


def _payload_of(costing: dict, when: str, exclude: list) -> Callable[[list], dict]:
    def payload(points: list) -> dict:
        body = {
            "locations": [
                {
                    "lon": float(lon),
                    "lat": float(lat),
                    "type": "break" if i in (0, len(points) - 1) else "through",
                    "radius": routing.STOP_RADIUS_M,
                }
                for i, (lon, lat) in enumerate(points)
            ],
            "costing": "bicycle",
            "costing_options": costing,
            "elevation_interval": routing.ELEVATION_INTERVAL_M,
            "date_time": {"type": 3, "value": routing.planning_time(when=when)},
            "directions_type": "none",
            "units": "kilometers",
        }
        if exclude:
            body["exclude_polygons"] = [[list(p) for p in ring] for ring in exclude]
        return body

    return payload


def loop_shapes(
    start: Sequence[float],
    target_m: float,
    preset_name: str,
    dials: routing.Dials,
    started: float | None = None,
) -> dict:
    """The answer of POST /api/route/loop-shapes: up to `SHAPES` shapes for a loop of about
    `target_m` from `start` on `preset_name` with `dials`. Raises NoLoop where none is found."""
    began = routing.clock() if started is None else started
    until = began + BUDGET_S
    variant, costing = stoporder.ride_graph(preset_name, dials)
    when = dials.when or routing.default_when()
    # The closures as far out as the loop can reach: half its length from the start.
    exclude = stoporder.ride_exclusions([list(start)], dials, reach_m=target_m / 2.0)

    def deadline_for(cap_s: float, graph: str | None = None) -> routing.Deadline:
        per_call = min(cap_s, routing.ROUTER_TIMEOUT_S)
        if graph in routing.TWIN_VARIANTS:
            per_call = min(per_call, routing.WEEKEND_TIMEOUT_S)
        return routing.Deadline(routing.clock() + per_call, per_call)

    def ask(payload: dict, cap_s: float) -> tuple[dict, str]:
        return stoporder._ask(variant, "route", payload, deadline_for(cap_s))

    def trace(shape: Shape, cap_s: float) -> dict | None:
        graph = shape.graph or variant
        deadline = deadline_for(cap_s, graph)
        pieces: list = []
        for leg in shape.legs:
            traced = routing.trace_leg(graph, costing, dedodge.encode_polyline6(leg), deadline)
            if traced is None:
                return None
            pieces.extend(routing.pieces_of_trace(traced))
        # Read on the graph it was routed on, as `routing.busy_and_waits` reads a candidate
        # ride (hunt X1: outside a plan, a timed closure read as a tier-1 path), and with the
        # segment table's reads held to the search's budget (`routing.plan_cursor`).
        graph_token = routing._routed_graph.set(graph)
        ends_token = routing._plan_ends.set(until + routing.ANSWER_RESERVE_S)
        try:
            stress, _facility = routing.breakdown(pieces, when)
        finally:
            routing._plan_ends.reset(ends_token)
            routing._routed_graph.reset(graph_token)
        return stress

    router = Router(until, ask, trace)
    shapes, note = search(router, start, target_m, _payload_of(costing, when, exclude))
    return {
        "target_distance_m": round(target_m, 1),
        "preset": preset_name,
        "shapes": [shape_out(shape, target_m) for shape in shapes],
        "tried": note.tried,
        "ran_short": note.ran_short,
    }


def offered(preset_name: str) -> bool:
    """Whether a ride type plans a loop from a start and a distance here: every bike ride type
    that plans loops (our default), not Mass Ride (one route by design), Bikeshare, Rebalance
    Ride or the transit ride types (a start and an end), nor Run, whose loop is its own
    (`run_plan.target_loop`)."""
    return (
        preset_name in presets.PRESETS
        and preset_name not in presets.BIKESHARE_PRESETS
        and preset_name not in presets.TRANSIT_PRESETS
        and preset_name not in (presets.RUN, "mass-ride")
    )
