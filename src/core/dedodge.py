"""FOLLOWUP-DEDODGE (OWNER-DECISIONS 272, 273): no weaving through side streets
beside a busier road unless it buys a meaningful length of calm.

The owner saw a route that "kept dodging back and forth into side streets along a
busier road. That would only make sense if it bought a meaningful distance of
calm." The test case is Konterra Drive (MD 206, Laurel, Prince George's County,
beside I-95): a Default, Trailmaxxing or Cargo ride north on it leaves it for
Virginia Manor Road and returns to it a quarter of a mile on, the side street no
calmer than the road (both LTS 3).

What this does, on every ride type, after the search has chosen the route and
before it is answered (`core.routing.plan`):

1. Detect (`find_dodges`). A dodge is a stretch of streets (nothing but streets:
   a trail, a crossing or a path is not one) that leaves a named road and rejoins
   the same corridor within `DODGE_MAX_M` (about a mile): the same road by name, or
   a road that runs on from it in the same direction within `PARALLEL_OFFSET_M` of
   its line (a road that changes name at a junction is one road).
2. Compare. The route between the dodge's two ends without the dodge's own streets
   (`/route` with each of them excluded, the plan's own request and variant
   otherwise) is read whole, junctions and all, beside the route as it was
   (`refine.analyse`).
3. Judge (`judge`). The stress a dodge avoids is the extra LTS 4, Avoid and red
   junction cost, plus the extra LTS 3 and orange junction cost, that the main road
   would carry: the two figures OWNER-DECISIONS 258-260 rank by (`Analysis.top_m`,
   `Analysis.second_m`). The dodge is kept if it avoids at least `MIN_AVOIDED_M` (a
   quarter of a mile), plus `TURN_CHARGE_M` for each turn it adds past the two that
   going off the road and back cannot do without (the turn load of item 254).
   Otherwise the main road's stretch is spliced in. Whatever that says, the route is
   never changed where it would carry more LTS 4, Avoid or red junction cost (the
   order of 258-262 and the hold of 250 are never broken), be longer (the target and
   ceiling of 267-271 only get easier), or be worse on the Hills slider's blended
   distance.

Planner only: no graph change, and the same variant and request as the plan's own,
so a Mass Ride or Group Ride (the no-trail variant, which has no contraflow) is
never offered a way the plan could not take. Every bound is hard: a time budget, at
most `MAX_CHECKS` re-routes, at most `MAX_EXCLUDES` exclusions to a request.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from routemaker import trace_junctions
from routemaker.geo import Point, bearing, bearing_delta, haversine

from . import refine, routing

logger = logging.getLogger(__name__)

# What a dodge must avoid to be kept (metres): a quarter of a mile of the higher
# stress, the tunable of OWNER-DECISIONS 272 ("about 0.25 mi").
MIN_AVOIDED_M = 0.25 * 1609.344
# What each turn past the two that every dodge has (off the road and back on) adds
# to what it must avoid (metres): the turn load of item 254, about 260 ft.
TURN_CHARGE_M = 80.0
BASE_TURNS = 2
# A turn is a change of heading of this many degrees where the street changes.
TURN_DEGREES = 40.0
# How far a dodge may go before it rejoins (metres): about a mile.
DODGE_MAX_M = 1609.344
# A road a dodge leaves and rejoins is at least this long on each side (metres), so
# a stub at an intersection is not a corridor.
MAIN_MIN_M = 30.0
# Two roads of different names are one corridor where the second runs on from the
# first within this many degrees, and this many metres of the first one's line.
PARALLEL_HEADING_DEG = 35.0
PARALLEL_OFFSET_M = 150.0
# The same road, rejoined, runs on in the direction it was left, within this.
SAME_ROAD_HEADING_DEG = 90.0
# The router's `use` of the streets a dodge is made of, and of the road it leaves.
# Anything else (a path, a crossing, steps, a ramp) is not a dodge.
STREET_USES = frozenset(
    {"road", "living_street", "service_road", "alley", "culdesac", "turn_channel", "driveway"}
)
MAIN_USES = frozenset({"road"})
# The most the top figure may rise (metres): the hold's own slack.
TOP_SLACK_M = refine.LTS4_SLACK_M
# The most the route may grow (metres): a metre's rounding.
LENGTH_SLACK_M = 1.0
# The router must place the replacement's ends this close to the dodge's (metres).
SNAP_M = 15.0
# Bounds: re-routes in all, exclusions to a request (the router's own limit is
# 200), seconds the pass may take and the least it is begun with, and a call's
# timeout.
MAX_CHECKS = 8
MAX_EXCLUDES = 40
BUDGET_S = 5.0
MIN_START_S = 3.0
CALL_TIMEOUT_S = 8.0
# An edge shorter than this has its middle within a couple of metres of a node, and
# an exclusion on a node takes out the cross street (`refine.CALM_MIN_EDGE_M`).
MIN_EXCLUDE_EDGE_M = refine.CALM_MIN_EDGE_M


# --- The route's edges ------------------------------------------------------


@dataclass(frozen=True)
class Edge:
    """One traced edge."""

    way_id: int
    names: frozenset
    metres: float
    use: str
    # Its first and last vertex, in the trace's shape.
    begin: int
    end: int
    heading_in: float | None
    heading_out: float | None


def normal(name: str) -> str:
    """A street name as compared: case and spacing do not tell roads apart."""
    return " ".join(name.lower().split())


def edges_of(trace: dict, shape: list) -> list[Edge]:
    """The traced edges in order (those `routing.pieces_of_trace` reads). `shape`
    is the trace's own (`trace_junctions.trace_shape`)."""
    to_metres = 1609.344 if trace.get("units") == "miles" else 1000.0
    out: list[Edge] = []
    for edge in trace.get("edges") or []:
        length = float(edge.get("length") or 0.0)
        begin, end = edge.get("begin_shape_index"), edge.get("end_shape_index")
        if length <= 0 or begin is None or end is None or end < begin or end >= len(shape):
            continue
        out.append(
            Edge(
                way_id=int(edge.get("way_id") or 0),
                names=frozenset(
                    normal(n) for n in edge.get("names") or () if isinstance(n, str) and n.strip()
                ),
                metres=length * to_metres,
                use=str(edge.get("use") or ""),
                begin=int(begin),
                end=int(end),
                heading_in=routing._heading(edge.get("begin_heading")),
                heading_out=routing._heading(edge.get("end_heading")),
            )
        )
    return out


# --- Dodges -----------------------------------------------------------------


@dataclass(frozen=True)
class Stretch:
    """Consecutive edges on one road: each shares a name with the one before."""

    edges: tuple
    names: frozenset
    metres: float

    @property
    def first(self) -> Edge:
        return self.edges[0]

    @property
    def last(self) -> Edge:
        return self.edges[-1]


def stretches_of(edges: list[Edge]) -> list[Stretch]:
    """The route's edges grouped into roads. An unnamed edge is a stretch of its own."""
    groups: list[list[Edge]] = []
    names: list[frozenset] = []
    for edge in edges:
        if groups and edge.names and names[-1] & edge.names:
            groups[-1].append(edge)
            names[-1] = names[-1] | edge.names
        else:
            groups.append([edge])
            names.append(edge.names)
    return [
        Stretch(tuple(group), name, sum(e.metres for e in group))
        for group, name in zip(groups, names, strict=True)
    ]


@dataclass(frozen=True)
class Dodge:
    """A leave-and-rejoin: the road's two stretches and the streets between them."""

    before: Stretch
    after: Stretch
    off: tuple
    metres: float

    @property
    def edges(self) -> list[Edge]:
        return [e for s in self.off for e in s.edges]

    @property
    def street(self) -> str:
        return sorted(self.before.names)[0] if self.before.names else ""


def _ahead_and_aside(a: Point, heading: float, b: Point) -> tuple[float, float]:
    """Where `b` is from `a`, heading `heading`: (metres ahead, metres to the side)."""
    d = haversine(a, b)
    angle = math.radians(bearing_delta(heading, bearing(a, b)))
    return d * math.cos(angle), abs(d * math.sin(angle))


NAME = "name"
LINE = "line"


def corridor_kind(before: Stretch, after: Stretch, shape: list) -> str | None:
    """How `after` is the road `before` was, or runs on from it: NAME (the same name,
    going on within SAME_ROAD_HEADING_DEG of the way it was left), LINE (a different
    name on the line of the first road, within PARALLEL_OFFSET_M of it and
    PARALLEL_HEADING_DEG of its heading), or None. Both go forward, never back."""
    if not before.names or not after.names:
        return None
    shared = bool(before.names & after.names)
    out, came = before.last, after.first
    if out.heading_out is None or came.heading_in is None:
        return NAME if shared else None
    turn = bearing_delta(out.heading_out, came.heading_in)
    ahead, aside = _ahead_and_aside(
        Point(*shape[out.end]), out.heading_out, Point(*shape[came.begin])
    )
    if ahead <= 0:
        return None
    if shared:
        return NAME if turn <= SAME_ROAD_HEADING_DEG else None
    return LINE if turn <= PARALLEL_HEADING_DEG and aside <= PARALLEL_OFFSET_M else None


def same_corridor(before: Stretch, after: Stretch, shape: list) -> bool:
    return corridor_kind(before, after, shape) is not None


def is_road(stretch: Stretch) -> bool:
    """A named road, the kind a dodge leaves."""
    return bool(stretch.names) and all(e.use in MAIN_USES for e in stretch.edges)


def is_streets(stretch: Stretch) -> bool:
    """Streets only, as a dodge is made of."""
    return all(e.use in STREET_USES for e in stretch.edges)


def find_dodges(edges: list[Edge], shape: list) -> list[Dodge]:
    """Every leave-and-rejoin of a named road within DODGE_MAX_M, disjoint, in route
    order. The road is rejoined by name where it can be (the first time), else on
    its line by another name (the first time): a road that runs on beside the one
    left is not a rejoin where the first road comes back."""
    stretches = stretches_of(edges)
    found: list[Dodge] = []
    a = 0
    while a < len(stretches):
        main = stretches[a]
        hit = on_line = None
        if is_road(main) and main.metres >= MAIN_MIN_M:
            gone = 0.0
            for b in range(a + 1, len(stretches)):
                if gone > DODGE_MAX_M:
                    break
                there = stretches[b]
                if b > a + 1 and is_road(there) and there.metres >= MAIN_MIN_M:
                    kind = corridor_kind(main, there, shape)
                    if kind == NAME:
                        hit = b
                        break
                    if kind == LINE and on_line is None:
                        on_line = b
                gone += there.metres
        hit = hit if hit is not None else on_line
        if hit is None:
            a += 1
            continue
        off = tuple(stretches[a + 1 : hit])
        if all(is_streets(s) for s in off):
            found.append(Dodge(main, stretches[hit], off, sum(s.metres for s in off)))
        a = hit
    return found


# --- The turns --------------------------------------------------------------


def turn_count(pieces: list) -> int:
    """The turns on a route: where the way changes, no street name is shared, and
    the heading changes by TURN_DEGREES or more. A route read without headings
    counts each change of street."""
    turns = 0
    for here, there in zip(pieces, pieces[1:], strict=False):
        if here.way_id == there.way_id:
            continue
        if {normal(n) for n in here.names} & {normal(n) for n in there.names}:
            continue
        if here.heading_out is None or there.heading_in is None:
            turns += 1
        elif bearing_delta(here.heading_out, there.heading_in) >= TURN_DEGREES:
            turns += 1
    return turns


# --- The rule ---------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """Whether the main road replaces the dodge, and why."""

    remove: bool
    reason: str
    avoided_m: float
    needed_m: float
    turns_saved: int
    extra_m: float


def traced_m(read: refine.Analysis) -> float:
    return sum(p.metres for p in read.pieces)


def avoided_m(dodge: refine.Analysis, direct: refine.Analysis) -> float:
    """The higher-stress metres the dodge avoids: what the direct route has more of
    at the top figure (LTS 4, Avoid, red junction cost) plus at the second (LTS 3,
    orange junction cost). Never negative: a main road calmer than the side streets
    is avoided nothing."""
    return max(0.0, direct.top_m - dodge.top_m) + max(0.0, direct.second_m - dodge.second_m)


def needed_m(turns_saved: int) -> float:
    """What a dodge must avoid to be kept, given the turns the main road saves."""
    return MIN_AVOIDED_M + TURN_CHARGE_M * max(0, turns_saved - BASE_TURNS)


def judge(dodge: refine.Analysis, direct: refine.Analysis, ctx: refine.Context) -> Verdict:
    """Keep the dodge (`dodge`: the route as it was) or take the main road
    (`direct`: the route without it), each read whole."""
    saved = turn_count(dodge.pieces) - turn_count(direct.pieces)
    extra = traced_m(dodge) - traced_m(direct)
    avoided = avoided_m(dodge, direct)
    needed = needed_m(saved)

    def keep(reason: str) -> Verdict:
        return Verdict(False, reason, avoided, needed, saved, extra)

    # Junctions read for one and not the other cannot be weighed.
    if (dodge.events is None) != (direct.events is None):
        return keep("events")
    # The order is never broken: no more LTS 4, Avoid or red junction cost.
    if direct.top_m > dodge.top_m + TOP_SLACK_M:
        return keep("top")
    # Never longer than the route was: the target and the ceiling only get easier.
    if extra < -LENGTH_SLACK_M:
        return keep("longer")
    if refine.level3(direct, ctx) > refine.level3(dodge, ctx) + LENGTH_SLACK_M:
        return keep("hills")
    if avoided >= needed:
        return keep("stress")
    return Verdict(True, "no_stress_gain", avoided, needed, saved, extra)


# --- Splicing ---------------------------------------------------------------


def encode_polyline6(points: list) -> str:
    """Valhalla's shape encoding at precision 6 (the inverse of
    `routing.decode_polyline6`)."""
    out = []
    lat = lon = 0
    for x, y in points:
        new_lat, new_lon = round(y * 1e6), round(x * 1e6)
        for delta in (new_lat - lat, new_lon - lon):
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                out.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            out.append(chr(delta + 63))
        lat, lon = new_lat, new_lon
    return "".join(out)


def splice_leg(
    leg: dict, shape: list, edges: list[Edge], dodge: Dodge, sub: dict, interval_m: float
) -> dict | None:
    """The leg with the dodge cut out and `sub` (the router's leg between the
    dodge's two ends) in its place; None where the router's ends are not the
    dodge's. The leg's length, time and cost less the dodge's share of them, plus
    the replacement's; its elevation likewise by `interval_m`."""
    out_edge, in_edge = dodge.before.last, dodge.after.first
    sub_shape = routing.decode_polyline6(sub.get("shape", ""))
    if len(sub_shape) < 2:
        return None
    if (
        haversine(Point(*sub_shape[0]), Point(*shape[out_edge.end])) > SNAP_M
        or haversine(Point(*sub_shape[-1]), Point(*shape[in_edge.begin])) > SNAP_M
    ):
        return None
    points = [*shape[: out_edge.end], *sub_shape, *shape[in_edge.begin + 1 :]]
    before, after = leg.get("summary") or {}, sub.get("summary") or {}
    whole_m = sum(e.metres for e in edges)
    share = dodge.metres / whole_m if whole_m > 0 else 0.0
    summary = dict(before)
    if "length" in before and "length" in after:
        summary["length"] = before["length"] - dodge.metres / 1000.0 + after["length"]
    for key in ("time", "cost"):
        if key in before and key in after:
            summary[key] = before[key] * (1.0 - share) + after[key]
    new = {**leg, "shape": encode_polyline6(points), "summary": summary}
    heights, sub_heights = leg.get("elevation"), sub.get("elevation")
    if heights and sub_heights:
        start_m = sum(e.metres for e in edges if e.end <= out_edge.end)
        k_out = round(start_m / interval_m)
        k_in = round((start_m + dodge.metres) / interval_m)
        new["elevation"] = [*heights[:k_out], *sub_heights, *heights[k_in:]]
    else:
        new.pop("elevation", None)
    return new


# --- The pass ---------------------------------------------------------------


def _request(
    ctx: refine.Context, dodge: Dodge, shape: list, excludes: list, headings: bool = True
) -> dict:
    """The plan's own request for the route from the dodge's start to its end, the
    dodge's streets excluded, each end facing the way the route goes (`headings`)."""
    out_edge, in_edge = dodge.before.last, dodge.after.first
    request = {k: v for k, v in ctx.request.items() if k not in ("alternates", "exclude_locations")}
    here = {"lon": shape[out_edge.end][0], "lat": shape[out_edge.end][1], "type": "break"}
    there = {"lon": shape[in_edge.begin][0], "lat": shape[in_edge.begin][1], "type": "break"}
    if headings and out_edge.heading_out is not None:
        here["heading"] = int(round(out_edge.heading_out)) % 360
    if headings and in_edge.heading_in is not None:
        there["heading"] = int(round(in_edge.heading_in)) % 360
    request["locations"] = [here, there]
    request["exclude_locations"] = [{"lon": lon, "lat": lat} for lon, lat in excludes]
    return request


def excludes_of(dodge: Dodge, shape: list) -> list[tuple[float, float]]:
    """The middle of each of the dodge's streets (every edge long enough to have
    one clear of its nodes), at most MAX_EXCLUDES."""
    out = []
    for edge in dodge.edges:
        if edge.metres < MIN_EXCLUDE_EDGE_M:
            continue
        point = trace_junctions.midpoint_along(shape, edge.begin, edge.end)
        if point is not None:
            out.append(point)
    return out[:MAX_EXCLUDES]


def empty_info() -> dict:
    return {
        "found": 0,
        "removed": 0,
        "kept": 0,
        "checked": 0,
        "saved_m": 0.0,
        "limited": None,
        "items": [],
    }


def apply(trip: dict, ctx: refine.Context, budget_s: float = BUDGET_S) -> tuple[dict, dict]:
    """The trip with every dodge that does not buy MIN_AVOIDED_M of calm replaced by
    the main road, and what was found: `{found, removed, kept, checked, saved_m,
    limited, items}` (`saved_m`: the metres the replacements took off the route),
    `limited` naming what stopped the pass short (`time`, `checks`) or None. The
    trip as it was where nothing is replaced. It does not raise for the router or
    the clock; an unexpected failure leaves the trip as it was."""
    info = empty_info()
    stop_at = min(ctx.deadline.at - refine.REFINE_TRACE_RESERVE_S, routing.clock() + budget_s)
    if stop_at - routing.clock() < MIN_START_S:
        info["limited"] = "time"
        return trip, info
    deadline = routing.Deadline(stop_at, min(ctx.deadline.per_call_s, CALL_TIMEOUT_S))
    try:
        for number in range(len(trip.get("legs") or [])):
            trip = _leg(trip, number, ctx, deadline, info)
            if info["limited"]:
                break
    except (routing.DeadlineExceeded, routing.RouterUnavailable):
        info["limited"] = info["limited"] or "time"
    except Exception:  # noqa: BLE001 - the route is answered as it was
        logger.warning("the dodge pass failed", exc_info=True)
    return trip, info


def _key(dodge: Dodge, shape: list) -> tuple:
    at = shape[dodge.before.last.end]
    return (round(at[0], 5), round(at[1], 5))


def _leg(trip: dict, number: int, ctx: refine.Context, deadline, info: dict) -> dict:
    """One leg's dodges, the last first; a replacement changes what comes after it
    and leaves what comes before. Each pass reads the leg as it now is."""
    seen: set = set()
    current = None
    while True:
        leg = trip["legs"][number]
        trace = routing._trace(ctx.variant, ctx.costing, leg.get("shape", ""), deadline, ctx.traces)
        if trace is None:
            return trip
        shape = trace_junctions.trace_shape(trace, routing.decode_polyline6(leg.get("shape", "")))
        edges = edges_of(trace, shape)
        todo = [d for d in find_dodges(edges, shape) if _key(d, shape) not in seen]
        if not seen:
            info["found"] += len(todo)
        if not todo:
            return trip
        dodge = todo[-1]
        seen.add(_key(dodge, shape))
        item = _item(dodge, shape)
        info["items"].append(item)
        if info["checked"] >= MAX_CHECKS:
            info["limited"] = "checks"
            item["action"] = "unchecked"
            return trip
        if routing.clock() >= deadline.at:
            info["limited"] = "time"
            item["action"] = "unchecked"
            return trip
        if current is None:
            current = refine.analyse(refine._leg_trip(trip, number), ctx, deadline)
            if current is None:
                item["action"] = "unchecked"
                return trip
        info["checked"] += 1
        new_leg, why = _alternative(ctx, deadline, leg, shape, edges, dodge)
        direct = (
            refine.analyse({"legs": [new_leg], "summary": new_leg["summary"]}, ctx, deadline)
            if new_leg is not None
            else None
        )
        if direct is None:
            item["action"] = "kept"
            item["reason"] = why or "untraceable"
            info["kept"] += 1
            continue
        verdict = judge(current, direct, ctx)
        item.update(
            reason=verdict.reason,
            avoided_m=round(verdict.avoided_m, 1),
            needed_m=round(verdict.needed_m, 1),
            turns_saved=verdict.turns_saved,
            extra_m=round(verdict.extra_m, 1),
        )
        if verdict.remove:
            trip = refine._splice(trip, number, {"legs": [new_leg], "summary": new_leg["summary"]})
            current = direct
            item["action"] = "removed"
            info["removed"] += 1
            info["saved_m"] = round(info["saved_m"] + verdict.extra_m, 1)
        else:
            item["action"] = "kept"
            info["kept"] += 1


def _alternative(ctx, deadline, leg, shape, edges, dodge) -> tuple[dict | None, str | None]:
    """The leg with the dodge's streets excluded, spliced, or (None, why)."""
    excludes = excludes_of(dodge, shape)
    if not excludes:
        return None, "no_exclusion"
    answer = None
    # Facing the way the route goes, and, where the router finds no path so (a heading
    # at a junction it cannot leave that way; 5 of 28 dodges on the twelve trips),
    # without: the replacement is read whole and judged all the same.
    for headings in (True, False):
        try:
            answer = routing._call(
                ctx.variant, "route", _request(ctx, dodge, shape, excludes, headings), deadline
            )
            break
        except routing.RouterRefused:
            continue
    if answer is None:
        return None, "no_route"
    trip = answer.get("trip") or {}
    legs = trip.get("legs") or []
    if len(legs) != 1:
        return None, "no_route"
    sub = {**legs[0], "summary": legs[0].get("summary") or trip.get("summary") or {}}
    new = splice_leg(leg, shape, edges, dodge, sub, routing.ELEVATION_INTERVAL_M)
    return (new, None) if new is not None else (None, "no_splice")


def _item(dodge: Dodge, shape: list) -> dict:
    at = shape[dodge.before.last.end]
    return {
        "street": dodge.street,
        "via": sorted({n for s in dodge.off for n in s.names})[:3],
        "lon": round(at[0], 6),
        "lat": round(at[1], 6),
        "length_m": round(dodge.metres, 1),
        "action": None,
        "reason": None,
        "avoided_m": None,
        "needed_m": None,
        "turns_saved": None,
        "extra_m": None,
    }
