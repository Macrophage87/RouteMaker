"""Trail seek: a candidate generator that goes looking for low-stress corridors.

Why. The calm search (`core.refine`) steers the router with `exclude_locations`
and each round excludes what the last one rode, so its candidates are nested:
from the calm rate of about 2 up, the same few routes win, and "90" and "100"
plan the same line (docs/DEVELOPMENT.md, "The top of the slider: what 150 would
do"). The wider search, through points off the straight line at fixed offsets
(`core.refine.wide_points`), did not help either: it asked for routes through
places nobody wants to ride. OWNER-DECISIONS 194, FOLLOWUP-TRAIL-SEEK: "a
candidate generator that seeks out trails and protected lanes near the line".

What it does. From the segment table it reads the traffic-free paths and
trails, the protected facilities and the car-free roads (LTS 1 or 2, facility
`path` or `protected`) in a band around the straight line from the start to the
end and around the router's best route so far. It joins them into a graph. A
corridor is a run of that graph that leaves the route at one point and returns
to it at a later one: it replaces the stretch of the route between them. Its
worth is what the replaced stretch costs in the refine score's own terms less
what the trail adds:

    score = RATE x (busy exposure metres of the replaced stretch)
            - DETOUR_WEIGHT x (detour metres)
    detour = (way to the entry) + trail + (way from the exit) - (stretch replaced)

where the exposure is the score's (LTS 3 metres, LTS 4 twice, Avoid three
times) and RATE is the calm rate: metres of detour accepted per metre of LTS 3
avoided. Both ends being points on the route makes the score a sum of a part
for the entry and a part for the exit, so one Dijkstra over the trail graph,
from every point near the route at once, finds the best entry, trail and exit
together. A route with nothing busy on it has nothing to replace and no
corridor.

The best corridor, the best two that do not overlap along the route (ridden in
order), and the best one that is a different trail from the first are proposed,
as the entry and exit points of each: the router is asked for the route through
them as `through` locations. This module only proposes. `core.refine` asks the
router, reads each route and scores it with the same score as every other
candidate, so the junction costs, the climb price and the Traffic-wins guard
(OWNER-DECISIONS 61, 188) still decide what is kept.

The geometry is pure (no database, no router) so that it can be tested alone;
`corridor_segments` is the one place that reads the table.
"""

from __future__ import annotations

import bisect
import heapq
import math
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from django.db import OperationalError, connection, transaction

from pipeline.schema import SEEK_INDEX_PREDICATE, trails_predicate

# The calm rate (metres of detour accepted per metre of LTS 3 avoided) from
# which a plan also seeks trails: the rate at the slider's old top, 100.
SEEK_FROM_RATE = 10.0
# Spans (metres of straight line) the search runs on. Under this there is no room
# for a corridor; over it `core.refine` has its own span limit.
SEEK_MIN_SPAN_M = 2_000.0
# How far from the straight line, and from the router's route, a trail is looked
# for: a fraction of the span, between these (metres).
BAND_FRACTION = 0.15
BAND_MIN_M = 1_500.0
BAND_MAX_M = 4_000.0
# The most segments one query returns (a 20 mi band of the Washington region is
# a few thousand).
MAX_SEGMENTS = 30_000
# A trail is entered or left from the route within this far of it (metres): the
# way from the route to the trail is a few blocks, ridden as the router likes.
JOIN_M = 200.0
# A corridor must replace this much of the route (metres), save this much
# exposure (metres of LTS 3, with LTS 4 twice and Avoid three times) and score
# at least this (metres of detour).
MIN_REPLACED_M = 500.0
MIN_EXPOSURE_M = 150.0
MIN_SCORE_M = 300.0
# With a trail credit (OWNER-DECISIONS 202) a corridor need not replace anything
# busy: it must put this many more metres of trail on the route than the stretch
# it replaces had.
MIN_TRAIL_GAIN_M = 400.0
# A metre of detour costs this many metres of the score; what a metre of busy
# road is worth against it is the calm rate's.
DETOUR_WEIGHT = 1.0
# No corridor may add more than this much detour (metres): the larger of a
# floor and a share of the span. The owner's "10 or 20 miles" (item 163) is a
# long way; the cap keeps the search to corridors worth asking about.
DETOUR_CAP_MIN_M = 6_000.0
DETOUR_CAP_SPAN = 1.0
# Networks smaller than this (metres of trail) are not corridors; only the
# largest this many are searched.
MIN_NETWORK_M = 300.0
MAX_NETWORKS = 24
# The via points sit this far along the trail from its entry and exit (metres),
# so that the router snaps to the trail and not to the road that crosses it at
# the trail's end.
VIA_INSET_M = 25.0
# Two corridors ridden in order must be at least this far apart along the route.
ORDER_GAP_M = 200.0
# The most candidates a plan asks the router for.
SEEK_MAX_CANDIDATES = 3
# The seek's own budget (seconds), on top of the exclusion search's.
SEEK_BUDGET_S = 6
# The least a candidate is started with (seconds): a route through the points, its
# trace and the junctions' joins. Less than the exclusion rounds' own, which
# also read their cross streets from a /locate.
SEEK_ROUND_MIN_S = 2.0
# What a leg is given at the least when the plan has stops (OWNER-DECISIONS 203):
# a candidate's worth and a margin, so that the time a leg has is not under the
# least a candidate starts with by the time it has read its table.
SEEK_LEG_MIN_S = SEEK_ROUND_MIN_S + 0.5
# Nodes this close together are one node (degrees, about 1 m).
SNAP_DEG = 1e-5
# The route is looked up every this many metres.
ROUTE_STEP_M = 25.0
# The table is read a strip at a time (review r1: one ST_DWithin on the whole
# guide scans its bounding box, which on a diagonal 20 mi trip is four times the
# band): the band is cut into cells this tall and wide (metres), and each row's
# run of cells the band reaches is one index scan of its own.
TABLE_CELL_M = 1_000.0
# The longest the table read may take (seconds; a statement timeout): measured
# 0.2 to 0.3 s warm and 1.5 s cold on the live table (docs/DEVELOPMENT.md).
TABLE_TIMEOUT_S = 2.5
# How often (in nodes settled) the corridor search looks at the clock.
CLOCK_EVERY = 1024

LonLat = tuple[float, float]
Node = tuple[int, int]


class SeekError(RuntimeError):
    """The corridor search reached a state it cannot be in (a step that costs
    nothing, a parent chain longer than the network): a bug, raised rather than
    looped on (review r1: a regression of the credit's clamp looped for ever and
    froze the host)."""


class SeekOutOfTime(Exception):
    """The leg's time ran out inside the table read or the corridor search."""


def _check_step(step_weight: float) -> None:
    """A step along a trail must cost something finite: with a step of no cost
    or less the search's parent chain can close on itself."""
    if not (math.isfinite(step_weight) and step_weight > 0):
        raise SeekError(f"a trail step must cost something, not {step_weight!r}")


def _check_time(stop_at: float | None, clock: Callable[[], float]) -> None:
    if stop_at is not None and clock() >= stop_at:
        raise SeekOutOfTime("the trail seek ran out of time")


def seek_for(rate: float) -> bool:
    """Whether a plan at this calm rate also seeks trails."""
    return rate >= SEEK_FROM_RATE


@dataclass(frozen=True)
class Corridor:
    """One run of trail worth riding: where to enter it and where to leave it."""

    entry: LonLat
    exit: LonLat
    # Trail metres from the entry to the exit.
    trail_m: float
    # The exposure (weighted metres) of the stretch of route it replaces.
    gain_m: float
    detour_m: float
    score: float
    # Metres along the route of the entry's and the exit's nearest points.
    t_in: float
    t_out: float
    # The trail's vertices from the entry to the exit.
    path: tuple[LonLat, ...] = ()
    # Trail metres more than the stretch of route it replaces has (with a credit).
    trail_gain_m: float = 0.0


@dataclass(frozen=True)
class Proposal:
    """A set of corridors, ridden in order, and the via points that ask for them."""

    corridors: tuple[Corridor, ...]

    @property
    def vias(self) -> list[LonLat]:
        out: list[LonLat] = []
        for corridor in self.corridors:
            out.extend(via_points(corridor))
        return out

    @property
    def gain_m(self) -> float:
        return sum(c.gain_m for c in self.corridors)

    @property
    def detour_m(self) -> float:
        return sum(c.detour_m for c in self.corridors)


class Plane:
    """Metres east and north of the start, and along and across the line from
    the start to the end."""

    def __init__(self, start: Sequence[float], end: Sequence[float]) -> None:
        self.lon0, self.lat0 = float(start[0]), float(start[1])
        self.ky = 110_540.0
        self.kx = 111_320.0 * math.cos(math.radians((self.lat0 + float(end[1])) / 2))
        self.ex, self.ey = self.xy(end[0], end[1])
        self.span = math.hypot(self.ex, self.ey)
        self.ux, self.uy = (self.ex / self.span, self.ey / self.span) if self.span else (1.0, 0.0)

    def xy(self, lon: float, lat: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky

    def lonlat(self, x: float, y: float) -> LonLat:
        return self.lon0 + x / self.kx, self.lat0 + y / self.ky

    def along(self, x: float, y: float) -> float:
        return x * self.ux + y * self.uy

    def across(self, x: float, y: float) -> float:
        return -x * self.uy + y * self.ux


class RouteLine:
    """The router's route as a line with a distance along it and the exposure
    (weighted metres of busy road) up to each distance.

    `spans` are (from, to, weight) in metres along the traced route, whose total
    length is `traced_m` (the line's own length is scaled to it). `trail_spans`
    are the stretches of trail, the same way, which `trail_to` counts."""

    def __init__(
        self,
        xy: Sequence[tuple[float, float]],
        spans: Iterable[tuple[float, float, float]] = (),
        traced_m: float | None = None,
        radius: float = JOIN_M,
        trail_spans: Iterable[tuple[float, float, float]] = (),
    ) -> None:
        self.radius = radius
        self.cell = max(50.0, radius)
        along = [0.0]
        for a, b in zip(xy, xy[1:], strict=False):
            along.append(along[-1] + math.dist(a, b))
        self.length = along[-1] if xy else 0.0
        scale = self.length / traced_m if traced_m else 1.0
        # Exposure up to the end of each span, and the spans, in the line's metres.
        self.starts, self.ends, self.weights, self.cum = self._cumulate(spans, scale)
        self.t_starts, self.t_ends, self.t_weights, self.t_cum = self._cumulate(trail_spans, scale)
        self.cells: dict[tuple[int, int], list[tuple[float, float, float]]] = defaultdict(list)
        step = max(ROUTE_STEP_M, radius / 8)
        for i, point in enumerate(xy):
            if i:
                d = along[i] - along[i - 1]
                n = int(d / step)
                for k in range(1, n):
                    f = k / n
                    previous = xy[i - 1]
                    self._add(
                        previous[0] + (point[0] - previous[0]) * f,
                        previous[1] + (point[1] - previous[1]) * f,
                        along[i - 1] + d * f,
                    )
            self._add(point[0], point[1], along[i])
        self._nearest: dict[tuple[float, float], tuple[float, float] | None] = {}

    @staticmethod
    def _cumulate(spans, scale: float):
        """The spans in the line's metres, in order and not overlapping, with the
        weighted metres up to the end of each."""
        starts: list[float] = []
        ends: list[float] = []
        weights: list[float] = []
        cum: list[float] = []
        total = 0.0
        for lo, hi, weight in sorted(spans):
            lo, hi = max(lo * scale, ends[-1] if ends else 0.0), hi * scale
            if hi <= lo or weight <= 0:
                continue
            starts.append(lo)
            ends.append(hi)
            weights.append(weight)
            total += (hi - lo) * weight
            cum.append(total)
        return starts, ends, weights, cum

    def _add(self, x: float, y: float, s: float) -> None:
        self.cells[(int(x // self.cell), int(y // self.cell))].append((x, y, s))

    @staticmethod
    def _to(starts, ends, weights, cum, s: float) -> float:
        i = bisect.bisect_right(ends, s)
        before = cum[i - 1] if i else 0.0
        if i < len(starts) and s > starts[i]:
            before += (s - starts[i]) * weights[i]
        return before

    def busy_to(self, s: float) -> float:
        """The exposure (weighted metres) from the start to `s` metres along."""
        return self._to(self.starts, self.ends, self.weights, self.cum, s)

    def trail_to(self, s: float) -> float:
        """The metres of trail from the start to `s` metres along."""
        return self._to(self.t_starts, self.t_ends, self.t_weights, self.t_cum, s)

    def nearest(self, x: float, y: float) -> tuple[float, float] | None:
        """(metres along the route, metres away) of the route's nearest point
        within the join distance, or None."""
        key = (x, y)
        if key in self._nearest:
            return self._nearest[key]
        cx, cy = int(x // self.cell), int(y // self.cell)
        best: tuple[float, float] | None = None
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for px, py, s in self.cells.get((i, j), ()):
                    d = math.hypot(px - x, py - y)
                    if d <= self.radius and (best is None or d < best[1]):
                        best = (s, d)
        self._nearest[key] = best
        return best


def band_m(span_m: float) -> float:
    """How far from the line a trail is looked for."""
    return min(BAND_MAX_M, max(BAND_MIN_M, BAND_FRACTION * span_m))


def detour_cap_m(span_m: float) -> float:
    return max(DETOUR_CAP_MIN_M, DETOUR_CAP_SPAN * span_m)


def _snap(lon: float, lat: float) -> Node:
    return round(lon / SNAP_DEG), round(lat / SNAP_DEG)


class Network:
    """The trail segments as a graph: nodes at the snapped vertices, an edge
    between each pair of consecutive vertices."""

    def __init__(self, segments: Iterable[Sequence[LonLat]], plane: Plane) -> None:
        self.plane = plane
        self.xy: dict[Node, tuple[float, float]] = {}
        self.adj: dict[Node, list[tuple[Node, float]]] = defaultdict(list)
        for line in segments:
            keys = []
            for lon, lat in line:
                key = _snap(lon, lat)
                if key not in self.xy:
                    self.xy[key] = plane.xy(lon, lat)
                keys.append(key)
            for a, b in zip(keys, keys[1:], strict=False):
                if a == b:
                    continue
                length = math.dist(self.xy[a], self.xy[b])
                self.adj[a].append((b, length))
                self.adj[b].append((a, length))

    def components(
        self, stop_at: float | None = None, clock: Callable[[], float] = time.monotonic
    ) -> list[list[Node]]:
        """The connected networks long enough to be corridors, the longest first
        (by metres of trail), at most MAX_NETWORKS."""
        seen: set[Node] = set()
        found: list[tuple[float, list[Node]]] = []
        visited = 0
        for start in sorted(self.adj):
            if start in seen:
                continue
            stack, nodes, total = [start], [], 0.0
            seen.add(start)
            while stack:
                node = stack.pop()
                nodes.append(node)
                visited += 1
                if visited % CLOCK_EVERY == 0:
                    _check_time(stop_at, clock)
                for other, length in self.adj[node]:
                    total += length / 2
                    if other not in seen:
                        seen.add(other)
                        stack.append(other)
            found.append((total, nodes))
        found.sort(key=lambda item: (-item[0], min(item[1])))
        return [nodes for total, nodes in found if total >= MIN_NETWORK_M][:MAX_NETWORKS]

    def best_in(
        self,
        nodes: list[Node],
        line: RouteLine,
        rate: float,
        cap_m: float,
        credit: float = 0.0,
        stop_at: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> Corridor | None:
        """The best corridor in one network, entry and exit both free.

        With the entry at `s_in` metres along the route and `c_in` from it, the
        exit at `s_out` and `c_out`, and `d` of trail between, the score is

            rate x (busy(s_out) - busy(s_in)) - W x (c_in + d + c_out - (s_out - s_in))
            + credit x (d - (trail(s_out) - trail(s_in)))

        (W is DETOUR_WEIGHT, `credit` the trail credit, OWNER-DECISIONS 202: a
        metre of trail is worth that many metres of detour, and the route's own
        trail the corridor replaces is lost), a part for the entry, a part for
        the exit and (W - credit) x d, so the best is the node pair of greatest
        exit value less entry cost less (W - credit) x d: one Dijkstra from every
        node near the route at once, each starting at its entry cost. The credit
        is held below W, so that no step costs less than nothing.

        Hard bounds, whatever the inputs (review r1): a step that does not cost
        something finite and positive is refused (SeekError), the walk back
        from the exit is at most the network's node count, and the clock is
        read every CLOCK_EVERY nodes against `stop_at` (SeekOutOfTime)."""
        credit = min(max(credit, 0.0), DETOUR_WEIGHT * 0.95)
        step_weight = DETOUR_WEIGHT - credit
        _check_step(step_weight)
        label: dict[Node, float] = {}
        origin: dict[Node, Node] = {}
        trail: dict[Node, float] = {}
        parent: dict[Node, Node] = {}
        joins: dict[Node, tuple[float, float]] = {}
        heap: list[tuple[float, Node]] = []
        for node in nodes:
            hit = line.nearest(*self.xy[node])
            if hit is None:
                continue
            s, c = hit
            joins[node] = hit
            label[node] = (
                rate * line.busy_to(s) + DETOUR_WEIGHT * (s + c) - credit * line.trail_to(s)
            )
            origin[node], trail[node] = node, 0.0
            heap.append((label[node], node))
        heapq.heapify(heap)
        best: tuple[float, Node] | None = None
        done: set[Node] = set()
        while heap:
            cost, node = heapq.heappop(heap)
            if node in done:
                continue
            done.add(node)
            if len(done) % CLOCK_EVERY == 0:
                _check_time(stop_at, clock)
            hit = joins.get(node) or line.nearest(*self.xy[node])
            if hit is not None:
                s_out, c_out = hit
                s_in, c_in = joins[origin[node]]
                replaced = s_out - s_in
                detour = c_in + trail[node] + c_out - replaced
                value = (
                    rate * line.busy_to(s_out)
                    + DETOUR_WEIGHT * (s_out - c_out)
                    - credit * line.trail_to(s_out)
                    - cost
                )
                if (
                    replaced >= MIN_REPLACED_M
                    and detour <= cap_m
                    and (best is None or value > best[0])
                ):
                    best = (value, node)
            for other, length in self.adj[node]:
                moved = cost + step_weight * length
                if moved < label.get(other, math.inf):
                    label[other] = moved
                    origin[other] = origin[node]
                    trail[other] = trail[node] + length
                    parent[other] = node
                    heapq.heappush(heap, (moved, other))
        if best is None:
            return None
        value, node = best
        entry = origin[node]
        path = [node]
        # A chain of parents is at most as long as the network: past that it is
        # a cycle, which only a step of no cost could make.
        for _ in range(len(nodes)):
            if path[-1] == entry:
                break
            path.append(parent[path[-1]])
        if path[-1] != entry:
            raise SeekError("the walk back along the trail is longer than its network")
        path.reverse()
        (s_in, c_in), (s_out, c_out) = joins[entry], line.nearest(*self.xy[node])  # type: ignore[misc]
        detour = c_in + trail[node] + c_out - (s_out - s_in)
        return Corridor(
            entry=self.plane.lonlat(*self.xy[entry]),
            exit=self.plane.lonlat(*self.xy[node]),
            trail_m=trail[node],
            gain_m=line.busy_to(s_out) - line.busy_to(s_in),
            detour_m=max(0.0, detour),
            score=value,
            t_in=s_in,
            t_out=s_out,
            path=tuple(self.plane.lonlat(*self.xy[n]) for n in path),
            trail_gain_m=trail[node] - (line.trail_to(s_out) - line.trail_to(s_in)),
        )


def find_corridors(
    segments: Iterable[Sequence[LonLat]],
    start: Sequence[float],
    end: Sequence[float],
    route: Sequence[LonLat],
    spans: Iterable[tuple[float, float, float]],
    traced_m: float | None,
    rate: float,
    credit: float = 0.0,
    trail_spans: Iterable[tuple[float, float, float]] = (),
    stop_at: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[Corridor]:
    """The best corridor of each trail network within reach, best first. Only
    corridors that score MIN_SCORE_M and save MIN_EXPOSURE_M are kept - or, with
    a trail credit (OWNER-DECISIONS 202), put MIN_TRAIL_GAIN_M more trail on the
    route than the stretch they replace, which is how a route with nothing busy
    on it still finds a trail. Past `stop_at` (by `clock`) it raises
    SeekOutOfTime."""
    plane = Plane(start, end)
    if plane.span < SEEK_MIN_SPAN_M or len(route) < 2:
        return []
    line = RouteLine(
        [plane.xy(lon, lat) for lon, lat in route], spans, traced_m, trail_spans=trail_spans
    )
    if not line.starts and credit <= 0:
        return []
    network = Network(segments, plane)
    cap = detour_cap_m(plane.span)
    found: list[Corridor] = []
    for nodes in network.components(stop_at, clock):
        _check_time(stop_at, clock)
        best = network.best_in(nodes, line, rate, cap, credit, stop_at, clock)
        if best is None or best.score < MIN_SCORE_M:
            continue
        if best.gain_m >= MIN_EXPOSURE_M or (credit > 0 and best.trail_gain_m >= MIN_TRAIL_GAIN_M):
            found.append(best)
    found.sort(key=lambda c: (-c.score, c.entry))
    return found


def overlaps(a: Corridor, b: Corridor) -> bool:
    """Whether two corridors replace the same stretch of the route, or are too
    close to be ridden one after the other."""
    return not (a.t_out + ORDER_GAP_M <= b.t_in or b.t_out + ORDER_GAP_M <= a.t_in)


def propose(corridors: Sequence[Corridor], limit: int = SEEK_MAX_CANDIDATES) -> list[Proposal]:
    """What to ask the router for, best bet first:

    - the best corridor with the best one beside it along the route (ridden in
      order), if there is one;
    - the best corridor alone;
    - the best corridor that is a different trail from the first (it overlaps it
      along the route), if there is one.
    """
    if not corridors:
        return []
    first = corridors[0]
    second = next((c for c in corridors[1:] if not overlaps(first, c)), None)
    other = next((c for c in corridors[1:] if overlaps(first, c)), None)
    out: list[Proposal] = []
    if second is not None:
        out.append(Proposal(tuple(sorted((first, second), key=lambda c: c.t_in))))
    out.append(Proposal((first,)))
    if other is not None:
        out.append(Proposal((other,)))
    return out[:limit]


def via_points(corridor: Corridor) -> list[LonLat]:
    """A corridor's entry and exit, each a little way along the trail."""
    path = list(corridor.path)
    if len(path) < 2 or corridor.trail_m < 4 * VIA_INSET_M:
        return [corridor.entry, corridor.exit]
    return [_along(path, VIA_INSET_M), _along(path[::-1], VIA_INSET_M)]


def _along(path: list[LonLat], metres: float) -> LonLat:
    """The point `metres` along a path."""
    walked = 0.0
    for a, b in zip(path, path[1:], strict=False):
        mid_lat = math.radians((a[1] + b[1]) / 2)
        d = math.hypot((b[0] - a[0]) * 111_320.0 * math.cos(mid_lat), (b[1] - a[1]) * 110_540.0)
        if d > 0 and walked + d >= metres:
            f = (metres - walked) / d
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        walked += d
    return path[-1]


def _parse_line(text: str) -> list[LonLat]:
    inner = text[text.index("(") + 1 : text.rindex(")")]
    return [(float(a), float(b)) for a, b in (pair.split() for pair in inner.split(","))]


def band_cells(
    guide: Sequence[Sequence[Sequence[float]]], width_m: float, cell_m: float = TABLE_CELL_M
) -> list[tuple[float, float, float, float]]:
    """The boxes (west, south, east, north in degrees) the table is read by: a
    grid of `cell_m` cells, each kept where it comes within `width_m` of a
    guide line, and each row's run of kept cells joined into one strip. Every
    point within `width_m` of a guide is inside a strip; the strips reach at
    most about a cell further (`in_band` cuts the band to metres)."""
    points = [tuple(p[:2]) for line in guide for p in line]
    if not points:
        return []
    lon0, lat0 = float(points[0][0]), float(points[0][1])
    ky = 110_540.0
    kx = 111_320.0 * math.cos(math.radians(lat0))
    # The guide sampled every half cell: a point within `width_m` of a line is
    # within `width_m` and a quarter cell of a sample.
    samples: list[tuple[float, float]] = []
    for line in guide:
        xy = [((p[0] - lon0) * kx, (p[1] - lat0) * ky) for p in line]
        samples.extend(xy[:1])
        for a, b in zip(xy, xy[1:], strict=False):
            n = max(1, math.ceil(math.dist(a, b) / (cell_m / 2)))
            samples.extend(
                (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                for k in range(1, n + 1)
            )
    reach = width_m + cell_m / 4
    cells: set[tuple[int, int]] = set()
    span = math.ceil(reach / cell_m)
    for x, y in samples:
        ci, cj = math.floor(x / cell_m), math.floor(y / cell_m)
        for i in range(ci - span, ci + span + 1):
            for j in range(cj - span, cj + span + 1):
                # The cell's nearest point to the sample.
                nx = min(max(x, i * cell_m), (i + 1) * cell_m)
                ny = min(max(y, j * cell_m), (j + 1) * cell_m)
                if math.hypot(nx - x, ny - y) <= reach:
                    cells.add((i, j))
    rows: dict[int, list[int]] = defaultdict(list)
    for i, j in cells:
        rows[j].append(i)
    boxes = []
    for j in sorted(rows):
        run = sorted(rows[j])
        first = previous = run[0]
        for i in [*run[1:], None]:
            if i is not None and i == previous + 1:
                previous = i
                continue
            boxes.append(
                (
                    lon0 + first * cell_m / kx,
                    lat0 + j * cell_m / ky,
                    lon0 + (previous + 1) * cell_m / kx,
                    lat0 + (j + 1) * cell_m / ky,
                )
            )
            if i is not None:
                first = previous = i
    return boxes


def corridor_segments(
    schema: str,
    guide: Sequence[Sequence[Sequence[float]]],
    width_m: float,
    has_facility: bool,
    when: str,
    avoid_unpaved: bool = False,
    timeout_s: float = TABLE_TIMEOUT_S,
) -> list[list[LonLat]]:
    """The low-stress trail segments within `width_m` of the guide lines (the
    straight line and the router's route), as lists of (lon, lat).

    The map's own trail rule (`pipeline.schema.trails_predicate`) says which ways
    are paths and trails. With the facility column the protected ways are in as
    well (a cycle track on the roadway is no trail but is as good a corridor),
    and the roads closed to cars at this ride time. LTS 1 and 2 only.

    The band is read strip by strip (`band_cells`), each strip one scan of the
    geometry index, so the scan reads the band and not the guide's bounding
    box. With the facility column the query carries the seek index's own
    predicate (`pipeline.schema.SEEK_INDEX_PREDICATE`, `segment_seek_geom_idx`),
    which the planner can then prove; without it the trail rule is the
    overview index's. It runs under a statement timeout of `timeout_s`; one that
    runs past it raises SeekOutOfTime."""
    query = corridor_query(schema, guide, width_m, has_facility, when, avoid_unpaved)
    if query is None:
        return []
    sql, params = query
    timeout_ms = str(max(1, math.ceil(timeout_s * 1000)))
    outer = connection.in_atomic_block
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            previous = None
            if outer:
                # Inside a caller's transaction the setting would outlive this read.
                cursor.execute("SELECT current_setting('statement_timeout')")
                previous = cursor.fetchone()[0]
            # Local to this transaction, as the tiles' (`core.stress_tiles.render`).
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [timeout_ms])
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            if previous is not None:
                cursor.execute("SELECT set_config('statement_timeout', %s, true)", [previous])
    except OperationalError as error:
        if getattr(error.__cause__, "sqlstate", None) == "57014":  # query_canceled
            raise SeekOutOfTime(f"the trail table read ran past {timeout_ms} ms") from error
        raise
    return [_parse_line(row[0]) for row in rows]


def corridor_query(
    schema: str,
    guide: Sequence[Sequence[Sequence[float]]],
    width_m: float,
    has_facility: bool,
    when: str,
    avoid_unpaved: bool = False,
) -> tuple[str, list] | None:
    """`corridor_segments`' query and its parameters (None where there is no
    guide to read around)."""
    if not guide:
        return None
    boxes = band_cells(guide, width_m)
    if not boxes:
        return None
    params: list = []
    if has_facility:
        where = (
            f"({SEEK_INDEX_PREDICATE}) AND ((s.facility IN ('path', 'protected') "
            "AND s.stress_tier <= 2) OR %s = ANY(s.car_free_when))"
        )
        params.append(when)
    else:
        rule = trails_predicate(False).replace("stress_rule", "s.stress_rule")
        where = f"{rule} AND s.stress_tier <= 2"
    if avoid_unpaved:
        where += " AND s.is_unpaved IS NOT TRUE"
    # One index scan a strip (the lateral join), each segment once.
    sql = (
        "SELECT ST_AsText(seg.geometry) FROM ("
        "SELECT DISTINCT ON (seg.id) seg.geometry "
        "FROM unnest(%s::float8[], %s::float8[], %s::float8[], %s::float8[]) "
        "AS box(west, south, east, north) "
        f"CROSS JOIN LATERAL (SELECT s.id, s.geometry FROM {schema}.segment AS s "
        "WHERE s.geometry && ST_MakeEnvelope(box.west, box.south, box.east, box.north, 4326) "
        f"AND {where}) AS seg"
        ") AS seg LIMIT %s"
    )
    columns = [list(column) for column in zip(*boxes, strict=True)]
    return sql, [*columns, *params, MAX_SEGMENTS]


def in_band(
    segments: Iterable[list[LonLat]],
    start: Sequence[float],
    end: Sequence[float],
    route: Sequence[LonLat],
    width_m: float,
) -> list[list[LonLat]]:
    """The segments with a vertex within `width_m` of the straight line or of the
    route, in metres."""
    plane = Plane(start, end)
    line = RouteLine([plane.xy(lon, lat) for lon, lat in route], radius=width_m)
    kept = []
    for segment in segments:
        for lon, lat in segment:
            x, y = plane.xy(lon, lat)
            beside = 0.0 <= plane.along(x, y) <= plane.span and abs(plane.across(x, y)) <= width_m
            if beside or line.nearest(x, y) is not None:
                kept.append(segment)
                break
    return kept


def points_in_band(
    points: Iterable[LonLat],
    start: Sequence[float],
    end: Sequence[float],
    route: Sequence[LonLat],
    width_m: float,
) -> list[LonLat]:
    """The points within `width_m` of the straight line or of the route (the
    leg's band), in order."""
    return [segment[0] for segment in in_band([[p] for p in points], start, end, route, width_m)]
