"""Run (Stephen, 2026-11-02: "would run use any different routing?", then "Yes, make it in its own
thread"): a ride type on foot, planned on Walk's map and walked as Walk is (Valhalla's pedestrian
costing on the standard graph, priced by `walk_pricing`), with what a runner wants besides. The
implementation's defaults, stated here so they can be argued with:

- Pace: the rider's (`RouteIn.run_pace_kmh`, 4 to 10 mph), else `RUN_PACE_KMH` (6 mph, a 10:00
  mile). Valhalla's `walking_speed` is the pace on the flat; its grade model slows the climbs.
- Hills: the hills slider as on a ride (`presets.use_hills_for`, Valhalla's pedestrian
  `use_hills`): left avoids climbing, right does not mind it.
- Trails first: a second on a trail, a park path or a track (`walk_pricing.TRAIL_USES`, packed
  gravel and dirt alike) counts `TRAIL_WEIGHT` of a second on a street when the router's ways are
  compared, and tracks are welcome in the costing (`use_tracks`). The Capital Crescent, Rock
  Creek and the Mall's paths beat the street grid beside them where they are near as quick.
- Stop and go: every signalled crossing counts `SIGNAL_WAIT_S` waited `presets.wait_weight_for`
  times (3, as Road Bike's junction waits), so a run through fewer lights wins. Walk's own
  charges stay (a busy road crossed with no signal, a slip lane, a main road with no sidewalk).
  The time shown is the running time, as a walk's is.
- After dark (civil dusk to civil dawn, or the "Night" ride time): Valhalla's `use_lit`
  (`USE_LIT_AFTER_DARK`), an unlit way costs about twice its time. A way with no `lit` tag counts
  as unlit there, so this leans to lit ways rather than forbidding the rest.
- Loops: "Make it a loop" (or a run that ends where it starts) runs the way back with the way
  out's line avoided, as a ride's loop does (`core.refine.make_loop`'s rule: points along the way
  out excluded, thinned until the router has a way, the best way back that shares no more than
  `refine.LOOP_OVERLAP_OK` of the way out, else the one that shares least, else the way out
  run back). A loop from a start alone with a target distance (`target_loop`) tries triangles
  of that length in `TARGET_BEARINGS` directions and keeps the best near the target.

A run is answered as Walk's line is: one walk leg (`transit.Plan`, mode "run"), its turns said
turn by turn on foot.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from routemaker import deer_closures
from routemaker.geo import Point, haversine
from routemaker.ridetime import NIGHT

from . import presets, refine, routing, transit, walk_pricing, walk_turns

logger = logging.getLogger(__name__)

KMH_PER_MPH = 1.609344
# A 10:00 mile: an easy run's pace for most runners.
RUN_PACE_KMH = round(6 * KMH_PER_MPH, 1)
# The pace a rider may set (4 to 10 mph: a 15:00 mile to a 6:00 one).
RUN_PACE_MIN_KMH = round(4 * KMH_PER_MPH, 1)
RUN_PACE_MAX_KMH = round(10 * KMH_PER_MPH, 1)

# A second on a trail counts this much of a second on a street.
TRAIL_WEIGHT = 0.7
# What one signalled crossing is taken to cost a runner standing at it, before the weight
# (`routemaker.junction_delay.SIGNAL_DELAY_S`, a ride's own).
SIGNAL_WAIT_S = 15.0
# Valhalla's `use_lit` after dark: 0.5 makes an unlit way cost twice its time.
USE_LIT_AFTER_DARK = 0.5
# Valhalla's `use_tracks`: tracks are welcome (packed gravel and dirt are fine for a run).
USE_TRACKS = 0.75
USE_LIVING_STREETS = 0.6
# The router's other ways asked for a run's leg between two points (`max_alternates` is 3).
ALTERNATES = 3
# The most turns a run carries.
MAX_TURNS = 150
# Civil twilight: the sun this far below the horizon.
CIVIL_TWILIGHT_DEG = -6.0

# A loop from a start alone (`target_loop`): equilateral triangles from the start, of
# `TARGET_BEARINGS` first headings, sized so the run is about the target; a run within
# `TARGET_TOLERANCE` of it is near enough, and the best is sized again once where it is not.
TARGET_BEARINGS = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)
# How much longer a run on the map is than its straight lines (a first guess, corrected after).
ROUTED_PER_STRAIGHT = 1.3
TARGET_TOLERANCE = 0.12
# A target loop's run: 1 km to a 50 km ultra.
RUN_TARGET_MAX_M = 50_000

# A loop's way back: points along the way out this far apart are excluded, none within
# `LOOP_CLEAR_M` of either end (the way back must be able to leave and arrive).
LOOP_CLEAR_M = 200.0
# Two pieces of a run closer than this (metres) are on one way (`overlap_share`).
SAME_WAY_M = 15.0
SAMPLE_M = 20.0

# The most one router call of a run may take, and all of a run's calls together.
CALL_S = 6.0
BUDGET_S = 30.0


class NoRun(Exception):
    """No run could be planned between the points (the router found no way on foot)."""


class RouterDown(NoRun):
    """No run could be planned because the router answered none of the run's calls."""


@dataclass(frozen=True)
class RunAsk:
    """What a run is planned with."""

    pace_kmh: float = RUN_PACE_KMH
    hills: int = 0
    dark: bool = False
    loop: bool = False
    target_m: float | None = None


@dataclass
class Walked:
    """One leg run: its line, time, length, turns, reading and score."""

    shape: list[tuple[float, float]]
    seconds: float
    metres: float
    turns: list[dict]
    reading: walk_pricing.Reading | None
    score: float


@dataclass
class Run:
    """A whole run: its line, time and length, its turns, and how its loop was made."""

    shape: list[tuple[float, float]]
    seconds: float
    metres: float
    turns: list[dict]
    climb_m: float | None = None
    descent_m: float | None = None
    trail_m: float = 0.0
    signals: int = 0
    loop: dict | None = None
    notes: list[str] = field(default_factory=list)
    # The index in `shape` where each leg ends (the answer's `leg_ends`), and the router calls.
    leg_ends: list[int] = field(default_factory=list)
    calls: int = 0


def pace_of(kmh: float | None) -> float:
    """The pace a run is planned at: the rider's, held to the range, else `RUN_PACE_KMH`."""
    if kmh is None:
        return RUN_PACE_KMH
    return min(RUN_PACE_MAX_KMH, max(RUN_PACE_MIN_KMH, float(kmh)))


def is_dark(at: datetime, when: str | None = None) -> bool:
    """Whether a run at `at` is after civil dusk or before civil dawn in Washington, or is set
    for the night (`ridetime.NIGHT`)."""
    if when == NIGHT:
        return True
    moment = at if at.tzinfo is not None else at.replace(tzinfo=deer_closures.ZONE)
    local = moment.astimezone(deer_closures.ZONE)
    dawn, dusk = deer_closures.sun_times(local.date(), altitude_deg=CIVIL_TWILIGHT_DEG)
    return not (dawn <= moment <= dusk)


def costing_options(ask: RunAsk) -> dict:
    """Valhalla's pedestrian costing options for a run."""
    options = {
        "walking_speed": round(ask.pace_kmh, 1),
        "use_hills": presets.use_hills_for(ask.hills),
        "use_tracks": USE_TRACKS,
        "use_living_streets": USE_LIVING_STREETS,
    }
    if ask.dark:
        options["use_lit"] = USE_LIT_AFTER_DARK
    return {"pedestrian": options}


def weigh(seconds: float, reading: walk_pricing.Reading) -> float:
    """A way's score for a run (`walk_pricing.Weigh`): its time with its trail seconds counted
    at `TRAIL_WEIGHT`, Walk's charges, and its waits at signals weighted as Road Bike's."""
    per_m = seconds / reading.metres if reading.metres > 0 else 0.0
    trail_s = min(reading.trail_m, reading.metres) * per_m
    waits = SIGNAL_WAIT_S * presets.wait_weight_for(presets.RUN) * reading.signals
    return seconds - (1.0 - TRAIL_WEIGHT) * trail_s + reading.penalty_s + waits


# --- The router -------------------------------------------------------------------------------

Call = Callable[[str, dict, float], object]


class Router:
    """The standard graph's router for one run, every call inside the run's budget. `call(action,
    payload, cap_s)` is the router (tests give their own); it raises the router's exceptions."""

    def __init__(self, until: float, call: Call | None = None) -> None:
        self.until = until
        self._call = call or _router_call
        self.calls = 0
        self.answered = 0

    def left(self) -> float:
        return self.until - routing.clock()

    def ask(self, action: str, payload: dict):
        """The router's answer, or None where it refused, could not be reached or no time is left
        (`walk_pricing.Ask`)."""
        left = self.left()
        if left <= 0.3:
            return None
        self.calls += 1
        try:
            answer = self._call(action, payload, min(left, CALL_S))
        except routing.RouterRefused as refused:
            # An answer, if not a way: the router is up.
            self.answered += 1
            logger.info("a run's %s was refused: %s", action, refused)
            return None
        except (routing.RouterUnavailable, routing.DeadlineExceeded) as error:
            logger.info("a run's %s was not answered: %s", action, error)
            return None
        self.answered += 1
        return answer


def _router_call(action: str, payload: dict, cap_s: float):
    deadline = routing.Deadline(routing.clock() + cap_s, cap_s)
    return routing._call("standard", action, payload, deadline)


def _payload(points: Sequence[Sequence[float]], ask: RunAsk, alternates: int) -> dict:
    payload = {
        "locations": [
            {
                "lon": float(p[0]),
                "lat": float(p[1]),
                "type": "break" if i in (0, len(points) - 1) else "through",
            }
            for i, p in enumerate(points)
        ],
        "costing": "pedestrian",
        "costing_options": costing_options(ask),
        "units": "kilometers",
    }
    # The maneuvers (turn by turn), kept off stairs where the rider asked (`walk_turns`).
    payload = walk_turns.directions(payload)
    if alternates:
        payload["alternates"] = alternates
    else:
        payload.pop("alternates", None)
    return payload


def run_leg(
    router: Router,
    points: Sequence[Sequence[float]],
    ask: RunAsk,
    exclude: Sequence[tuple[float, float]] = (),
    alternates: int = ALTERNATES,
    say_crossings: bool = True,
) -> Walked | None:
    """One leg of a run through `points` (its ends and any `through` points between), the best
    of the router's ways for a run (`weigh`), or None where the router has none."""
    if len(points) < 2:
        return None
    payload = _payload(points, ask, alternates if len(points) == 2 else 0)
    if exclude:
        payload["exclude_locations"] = [{"lon": lon, "lat": lat} for lon, lat in exclude]
    answer = router.ask("route", payload)
    if not isinstance(answer, dict):
        return None
    chosen = walk_pricing.choose(answer, router.ask, payload.get("costing_options"), weigh)
    if chosen is None:
        return None
    leg = chosen.leg
    shape = list(routing.decode_polyline6(leg.get("shape", "")))
    if len(shape) < 2:
        return None
    summary = leg.get("summary") or {}
    seconds = float(summary.get("time") or 0.0)
    metres = float(summary.get("length") or 0.0) * 1000.0
    crossings = walk_pricing.crossing_turns(chosen.crossings, router.ask) if say_crossings else []
    turns = walk_turns.turns_of(leg, shape, crossings, max_turns=MAX_TURNS)
    reading = chosen.reading
    score = weigh(seconds, reading) if reading is not None else seconds
    return Walked(shape, seconds, metres, turns, reading, score)


# --- Loops ------------------------------------------------------------------------------------


def _along(shape: Sequence[tuple[float, float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(shape, shape[1:], strict=False):
        out.append(out[-1] + haversine(Point(*a), Point(*b)))
    return out


def samples(
    shape: Sequence[tuple[float, float]], step_m: float
) -> list[tuple[float, float, float]]:
    """Points along `shape` every `step_m` (lon, lat, metres along), its first and last too."""
    if len(shape) < 2:
        return [(shape[0][0], shape[0][1], 0.0)] if shape else []
    along = _along(shape)
    out = []
    at = 0.0
    i = 0
    while at <= along[-1]:
        while i < len(along) - 2 and along[i + 1] < at:
            i += 1
        span = along[i + 1] - along[i]
        f = 0.0 if span <= 0 else (at - along[i]) / span
        a, b = shape[i], shape[i + 1]
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, at))
        at += step_m
    last = shape[-1]
    if not out or out[-1][2] < along[-1]:
        out.append((last[0], last[1], along[-1]))
    return out


class _Grid:
    """Points in cells about `SAME_WAY_M` wide, for nearness tests."""

    def __init__(self, points: Sequence[tuple[float, float, float]]) -> None:
        self.cells: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
        for p in points:
            self.cells.setdefault(self._cell(p[0], p[1]), []).append(p)

    @staticmethod
    def _cell(lon: float, lat: float) -> tuple[int, int]:
        # About 15 m a cell at Washington's latitude, either way.
        return int(math.floor(lat / 0.000135)), int(math.floor(lon / 0.000175))

    def near(self, lon: float, lat: float, keep: Callable[[tuple[float, float, float]], bool]):
        row, col = self._cell(lon, lat)
        here = Point(lon, lat)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for p in self.cells.get((row + dr, col + dc), ()):
                    if keep(p) and haversine(here, Point(p[0], p[1])) <= SAME_WAY_M:
                        return True
        return False


def overlap_share(
    way_out: Sequence[tuple[float, float]], way_back: Sequence[tuple[float, float]]
) -> float:
    """The share of the way back, by length, within `SAME_WAY_M` of the way out."""
    back = samples(way_back, SAMPLE_M)
    if len(back) < 2:
        return 0.0
    grid = _Grid(samples(way_out, SAMPLE_M))
    shared = sum(1 for lon, lat, _m in back if grid.near(lon, lat, lambda _p: True))
    return shared / len(back)


def self_overlap(shape: Sequence[tuple[float, float]]) -> float:
    """The share of a run, by length, that runs a way it also runs elsewhere (an out-and-back
    spur), at least `LOOP_CLEAR_M` along it from there."""
    points = samples(shape, SAMPLE_M)
    if len(points) < 3:
        return 0.0
    grid = _Grid(points)
    total = points[-1][2]
    shared = 0
    for lon, lat, m in points:
        # The start and finish are one place on a loop: not an overlap.
        if m < LOOP_CLEAR_M or total - m < LOOP_CLEAR_M:
            continue
        if grid.near(lon, lat, lambda p, m=m: abs(p[2] - m) > 4 * LOOP_CLEAR_M):
            shared += 1
    return shared / len(points)


def exclusions(shape: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Points along a way out for its way back to avoid: `refine.LOOP_SAMPLE_M` apart, none
    within `LOOP_CLEAR_M` of either end."""
    points = samples(shape, refine.LOOP_SAMPLE_M)
    if not points:
        return []
    total = points[-1][2]
    return [
        (round(lon, 6), round(lat, 6))
        for lon, lat, m in points
        if LOOP_CLEAR_M <= m <= total - LOOP_CLEAR_M
    ]


def way_back(
    router: Router, way_out: Sequence[tuple[float, float]], end, start, ask: RunAsk
) -> tuple[Walked | None, dict]:
    """A loop's way back from `end` to `start` by another way than `way_out`, as a ride's loop
    is made (`refine.make_loop`): the exclusions thinned (`refine.LOOP_THINNING`) until the
    router has a way, every one asked while time is left; the best for a run that shares no
    more than `refine.LOOP_OVERLAP_OK`, else the one that shares least. Returns it (None where
    nothing was found) and the answer's `loop` block."""
    info: dict = {
        "overlap_pct": None,
        "shared_m": None,
        "return_m": None,
        "excluded": 0,
        "tried": 0,
        "fallback": None,
    }
    points = exclusions(way_out)
    asks: list[list[tuple[float, float]]] = []
    for step in refine.LOOP_THINNING:
        chosen = points[::step][: refine.MAX_EXCLUDES]
        if chosen and chosen not in asks:
            asks.append(chosen)
    best: tuple[tuple, Walked, int, float] | None = None
    for chosen in asks:
        if router.left() < 2.0:
            info["fallback"] = info["fallback"] or "time"
            break
        info["tried"] += 1
        walked = run_leg(router, [end, start], ask, exclude=chosen, alternates=0)
        if walked is None:
            continue
        share = overlap_share(way_out, walked.shape)
        rank = (
            share > refine.LOOP_OVERLAP_OK,
            walked.score if share <= refine.LOOP_OVERLAP_OK else share,
        )
        if best is None or rank < best[0]:
            best = (rank, walked, len(chosen), share)
        if share <= refine.LOOP_OVERLAP_OK:
            # The densest ask that shares little is as different a way back as there is.
            break
    if best is None or best[3] >= refine.LOOP_OUT_AND_BACK:
        info["fallback"] = "out_and_back" if info["tried"] else info["fallback"] or "points"
        plain = run_leg(router, [end, start], ask)
        if plain is not None:
            info.update(_shares(overlap_share(way_out, plain.shape), plain.metres))
        return plain, info
    _rank, walked, excluded, share = best
    info.update(_shares(share, walked.metres), excluded=excluded)
    return walked, info


def _shares(share: float, metres: float) -> dict:
    return {
        "overlap_pct": round(100.0 * share, 1),
        "shared_m": round(share * metres, 1),
        "return_m": round(metres, 1),
    }


def _offset(point, bearing_deg: float, metres: float) -> tuple[float, float]:
    """The point `metres` from `point` on `bearing_deg` (a flat earth: a run is a few km)."""
    lon, lat = float(point[0]), float(point[1])
    b = math.radians(bearing_deg)
    dlat = metres * math.cos(b) / 111_320.0
    dlon = metres * math.sin(b) / (111_320.0 * math.cos(math.radians(lat)))
    return round(lon + dlon, 6), round(lat + dlat, 6)


def triangle(start, bearing_deg: float, side_m: float) -> list[tuple[float, float]]:
    """An equilateral loop from `start`: out on `bearing_deg`, across, and home."""
    first = _offset(start, bearing_deg, side_m)
    second = _offset(start, bearing_deg + 60.0, side_m)
    return [tuple(start), first, second, tuple(start)]


def target_loop(router: Router, start, ask: RunAsk) -> tuple[Walked | None, dict]:
    """A loop of about `ask.target_m` from `start` alone: a triangle in each of `TARGET_BEARINGS`,
    sized from `ROUTED_PER_STRAIGHT`; the one nearest the target (within `TARGET_TOLERANCE`
    first), then with the least run twice (`self_overlap`), then the best for a run. The best is
    sized once more where it is not within the tolerance."""
    assert ask.target_m is not None
    target = float(ask.target_m)
    side = target / (3.0 * ROUTED_PER_STRAIGHT)
    found: list[tuple[tuple, Walked, float, float]] = []

    def tried(bearing: float, side_m: float) -> None:
        walked = run_leg(
            router, triangle(start, bearing, side_m), ask, alternates=0, say_crossings=False
        )
        if walked is None or walked.metres <= 0:
            return
        off = abs(walked.metres - target) / target
        spur = self_overlap(walked.shape)
        rank = (
            off > TARGET_TOLERANCE,
            spur > refine.LOOP_OVERLAP_OK,
            walked.score / walked.metres,
            off,
        )
        found.append((rank, walked, bearing, side_m))

    for bearing in TARGET_BEARINGS:
        if router.left() < 2.0:
            break
        tried(bearing, side)
    if not found:
        return None, {"fallback": "points", "tried": 0}
    found.sort(key=lambda f: f[0])
    rank, walked, bearing, side_m = found[0]
    if rank[0] and router.left() >= 2.0:
        tried(bearing, side_m * target / walked.metres)
        found.sort(key=lambda f: f[0])
    _rank, walked, bearing, side_m = found[0]
    # Its crossings said, now it is chosen (one `/locate`).
    said = run_leg(router, triangle(start, bearing, side_m), ask, alternates=0)
    if said is not None and abs(said.metres - walked.metres) < 1.0:
        walked = said
    spur = self_overlap(walked.shape)
    return walked, {
        "overlap_pct": round(100.0 * spur, 1),
        "shared_m": round(spur * walked.metres, 1),
        "return_m": None,
        "excluded": 0,
        "tried": len(found),
        "fallback": None,
    }


# --- The plan ---------------------------------------------------------------------------------


def _joined(parts: Sequence[Walked]) -> Run:
    shape: list[tuple[float, float]] = []
    turns: list[dict] = []
    climb = descent = None
    trail = 0.0
    signals = 0
    ends: list[int] = []
    for part in parts:
        shape.extend(part.shape if not shape else part.shape[1:])
        ends.append(len(shape) - 1)
        turns.extend(part.turns)
        reading = part.reading
        if reading is not None:
            trail += reading.trail_m
            signals += reading.signals
            if reading.climb_m is not None:
                climb = (climb or 0.0) + reading.climb_m
                descent = (descent or 0.0) + (reading.descent_m or 0.0)
    return Run(
        shape,
        sum(p.seconds for p in parts),
        sum(p.metres for p in parts),
        turns[: MAX_TURNS * 2],
        climb,
        descent,
        round(trail, 1),
        signals,
        leg_ends=ends,
    )


def plan(points: Sequence[Sequence[float]], ask: RunAsk, router: Router) -> Run:
    """A run through `points`: leg by leg, each the best of the router's ways; a loop's way back
    by another way (`way_back`); a start alone with a target, a loop of about that length
    (`target_loop`). Raises NoRun where the router finds no way, RouterDown where it answered
    nothing."""
    try:
        run = _plan(points, ask, router)
    except NoRun as refusal:
        if router.answered == 0:
            raise RouterDown("The router is not answering; try again shortly.") from refusal
        raise
    run.calls = router.calls
    return run


def _plan(points: Sequence[Sequence[float]], ask: RunAsk, router: Router) -> Run:
    points = [tuple(float(c) for c in p[:2]) for p in points]
    if len(points) == 1:
        if not (ask.loop and ask.target_m):
            raise NoRun("A run from one point needs a loop and a target distance.")
        walked, info = target_loop(router, points[0], ask)
        if walked is None:
            raise NoRun("No loop could be found on foot from this start.")
        run = _joined([walked])
        run.loop = info
        return run
    round_trip = (
        len(points) >= 3 and haversine(Point(*points[0]), Point(*points[-1])) <= routing.LOOP_SAME_M
    )
    loop = ask.loop or round_trip
    if loop and not round_trip:
        # The rider's loop: out through every point, then home by another way.
        points = [*points, points[0]]
    out_points = points[:-1] if loop else points
    parts: list[Walked] = []
    for a, b in zip(out_points, out_points[1:], strict=False):
        walked = run_leg(router, [a, b], ask)
        if walked is None:
            raise NoRun("No way on foot could be found between two of the points.")
        parts.append(walked)
    info = None
    if loop:
        way_out = _joined(parts).shape
        back, info = way_back(router, way_out, out_points[-1], points[-1], ask)
        if back is None:
            raise NoRun("No way back on foot could be found to the start.")
        parts.append(back)
    run = _joined(parts)
    run.loop = info
    return run


def as_plan(run: Run, when: datetime) -> transit.Plan:
    """The run as a transit plan of one walk (mode "run"), as Walk's answer is."""
    leg = transit.Leg(
        transit.WALK,
        run.seconds,
        tuple(run.shape),
        turns=tuple(run.turns),
    )
    option = transit.Option(transit.WALK_ONLY, (leg,), walk=True)
    found = transit.Plan(presets.RUN, [option], transit.moments_of(when)[0], [], {})
    return replace(found, notes=list(run.notes)) if run.notes else found


def deadline_from(started: float) -> float:
    """When a run's router calls stop: `BUDGET_S` in, inside the request's budget."""
    return min(
        started + BUDGET_S,
        started + routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S,
    )
