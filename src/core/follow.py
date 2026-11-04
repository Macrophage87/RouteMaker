"""Following an opened file's line exactly (Stephen 2026-10-17: "it's still not possible to
add in a gpx identical route").

An opened GPX track used to be planned like any plan: a handful of points picked from it, the
router joining them by its own choice of way, and fitting rounds adding points where it left
the track (frontend lib/gpxPlan.ts). That follows the file closely, never exactly. With the
track's line sent as `follow` (POST /api/route), the plan's router call is a `/trace_route` of
that line instead (`shape_match: map_snap`, on the ride type's own graph and costing), so the
route is the file's own ways, rated, timed and described like any route. The plan's points
still split it into legs (`break_through`, as `routing.VIA_LOCATION_TYPE`), each at the vertex
of the line nearest to it, so the front end's stops and legs read as they do on a plan.

Where the file breaks the map's rules, the route keeps to them by default (Stephen
2026-10-17: "if imported and there are issues, the default is to not include it, but give a
manual mode option"): a stretch the file rides against one-way traffic is left out of the
match (`wrong_way`) and the router goes round it, each such stretch said (`against_traffic`);
a way closed to bicycles is not matched at all. With the manual mode asked for (`EXACT`: "when
the police close a road for a parade or procession") the file is followed as ridden, against
one-way traffic, through restricted turns and along ways closed to bicycles. Where the ride
type cannot ride the file at all (a trail on Mass Ride's no-trail graph, a way closed to
bicycles or not on the map) the matcher breaks the line into pieces; each gap is joined by the
router's own route between the pieces' ends (`joined`), and the page says how closely the
route follows the file (frontend lib/trackMatch.ts `fidelity`), as before. A line nothing of
which matches is refused, and the plan is made without it (`api._planned`).
"""

from __future__ import annotations

import bisect
import math

from routemaker.geo import Point, bearing_delta, bearing_lonlat, haversine

from . import routing

# The longest line followed: the browser's simplified line of the file (frontend
# lib/gpxPlan.ts REFERENCE_MAX_VERTICES), as POST /api/match.
MAX_POINTS = 5000
# The encoded line's longest text: 5,000 points at precision 6 take well under 64 KB.
MAX_CHARS = 64 * 1024
# How far from a point of the line the matcher looks for a way (as `map_match.SEARCH_RADIUS_M`:
# GPS under trees or between buildings is often 20 to 40 m out).
SEARCH_RADIUS_M = 50
# Valhalla's trace limit (valhalla/*.json, trace.max_distance).
MAX_DISTANCE_M = 200_000
# A matched line that starts or ends further than this from the file's own start or end is
# joined to it by the router's route.
END_GAP_M = 60.0


# The costing options a line is matched with to find where the file rides against one-way
# traffic (`wrong_way`): matched with the ride type's own, the matcher loops round such a
# one-way block by block rather than leave it.
IGNORED = {"ignore_oneways": True, "ignore_restrictions": True}
# The manual mode's (`routing.Dials.follow_exact`): the file followed as ridden, also along
# ways closed to bicycles and through closures.
EXACT = {**IGNORED, "ignore_access": True, "ignore_closures": True}
# A stretch against one-way traffic shorter than this is not said: a matched point a few
# metres past a corner, or a cut across a junction's corner.
AGAINST_MIN_M = 15.0
# A plan's point this close to the line goes on its first pass there (`split_line`), and one
# this close to a vertex of it takes that vertex.
NEAR_M = 25.0
SAME_M = 1.0
# A stretch against one-way traffic the route passes this close to all along is the other half
# of a divided road (`gone_round`): the two carriageways of most are 10 to 30 m apart, and
# the way round a wrong-way block is a block away.
DIVIDED_M = 40.0
# The most breaks in a match joined by the router's own route: more, and the file is planned
# through its points instead (each join is a router call).
MAX_BRIDGES = 20
# What a `/trace_route` asks that a `/route` between two points does not.
TRACE_ONLY = frozenset({"shape", "shape_match", "trace_options"})
# Corners the matcher must not cut (`clear_corners`; an owner report, "several phantom LTS4
# unnamed roads", on an opened file through 14th St SE / K St SE / 13th St SE). The
# matcher (Valhalla's meili, valhalla/*.json `meili.default.interpolation_distance`, 10 m)
# does not match a point of the line within that distance of the last one it matched: it
# only places it on the path between matched points, and that path is the SHORTEST by
# distance, whatever the ride type's costing prices (src/meili/routing.cc, 3.9.1: "Override
# cost portion to be distance"). A snapped or exported line has a vertex at every node of
# the graph, crosswalks' nodes on the road 5 to 10 m from a junction among them, so the
# corner's own vertex went unmatched and the path between the two crosswalk nodes either
# side of it was the crosswalks round the corner (OSM 1239622654 and 1239622635, rings of
# `footway=crossing`), a metre or so shorter than the road: four "Cross the road, heavy
# traffic (LTS 4)" pieces, drawn red, and a "Right, then left, then right" at two plain
# corners. MATCH_SKIP_M is that distance, CORNER_CLEAR_M the stretch before a corner cleared
# of other vertices (a margin over it), and CORNER_DEG the turn that makes a vertex a corner.
MATCH_SKIP_M = 10.0
CORNER_CLEAR_M = 12.0
CORNER_DEG = 30.0


class LineProblem(ValueError):
    """The line sent is not one a plan follows; the message says why."""


def checked_line(
    encoded: str, bbox: tuple[float, float, float, float]
) -> list[tuple[float, float]]:
    """The line `encoded` (Valhalla's polyline at precision 6) as [(lon, lat), ...], or
    LineProblem."""
    try:
        line = routing.decode_polyline6(encoded)
    except (IndexError, ValueError, TypeError):
        raise LineProblem("follow is not a line encoded at precision 6") from None
    if len(line) < 2:
        raise LineProblem("follow has fewer than two points")
    if len(line) > MAX_POINTS:
        raise LineProblem(f"follow has more than {MAX_POINTS:,} points")
    west, south, east, north = bbox
    if not all(west <= lon <= east and south <= lat <= north for lon, lat in line):
        raise LineProblem("follow has a point outside the area this map covers")
    if line_m(line) > MAX_DISTANCE_M:
        raise LineProblem("follow is longer than 124 mi (200 km), the most that can be followed")
    return line


def line_m(line) -> float:
    return sum(haversine(Point(*a), Point(*b)) for a, b in zip(line, line[1:], strict=False))


def _projected(p, a, b) -> tuple[tuple[float, float], float]:
    """The point of the stretch a-b nearest `p`, and how far it is from `p` in metres (on a
    flat local plane, near enough over a stretch)."""
    k = math.cos(math.radians(p[1]))
    ax, ay = (a[0] - p[0]) * k, a[1] - p[1]
    dx, dy = (b[0] - a[0]) * k, b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
    q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return q, haversine(Point(*p), Point(*q))


def split_line(line, points) -> tuple[list, list[int]]:
    """The line with a vertex where each of the plan's points between its first and last
    lies on it, and those vertices' indices, in order along the line.

    Each point goes on the nearest stretch past the one before it; on a file that passes a
    place twice (an out-and-back), the first pass within NEAR_M of it, not a later one that
    happens to be a little nearer. A point within SAME_M of a vertex takes that vertex. A point
    that would repeat the one before, or sit on an end, is left out, and its leg joins the
    next."""
    out = [tuple(p) for p in line]
    indices: list[int] = []
    after = 0
    for p in points[1:-1]:
        here = (float(p[0]), float(p[1]))
        best = None
        for i in range(after, len(out) - 1):
            q, metres = _projected(here, out[i], out[i + 1])
            if best is None or metres < best[2]:
                best = (i, q, metres)
            elif best[2] <= NEAR_M and metres > best[2] + NEAR_M:
                break
        if best is None:
            continue
        i, q, _metres = best
        if haversine(Point(*q), Point(*out[i])) <= SAME_M:
            index = i
        elif haversine(Point(*q), Point(*out[i + 1])) <= SAME_M:
            index = i + 1
        else:
            out.insert(i + 1, q)
            index = i + 1
        if index <= (indices[-1] if indices else 0) or index >= len(out) - 1:
            continue
        indices.append(index)
        after = index
    return out, indices


def _corners(line) -> list[int]:
    """The indexes of `line`'s vertices where it turns by CORNER_DEG or more (ends excluded),
    each judged from the nearest vertex at least SAME_M away on either side, so a vertex
    doubled at a corner (or a stray one beside it) does not hide the turn."""
    out: list[int] = []

    def apart(i: int, step: int) -> int | None:
        j = i + step
        while 0 <= j < len(line):
            if haversine(Point(*line[i]), Point(*line[j])) >= SAME_M:
                return j
            j += step
        return None

    for i in range(1, len(line) - 1):
        before, after = apart(i, -1), apart(i, 1)
        if before is None or after is None:
            continue
        a, b, c = line[before], line[i], line[after]
        if bearing_delta(bearing_lonlat(a, b), bearing_lonlat(b, c)) >= CORNER_DEG:
            out.append(i)
    return out


def clear_corners(line, keep) -> tuple[list, list[int]]:
    """`line` with the vertices within CORNER_CLEAR_M before each corner left out, so the
    matcher matches the corner itself (MATCH_SKIP_M) and the route turns there, on the road,
    not over the crosswalks round it; and the new indexes of the vertices in `keep` (the
    plan's points), which stay, as the ends and the corners do. Only vertices that are not
    corners themselves go. A plan's point inside the stretch stops it there (a leg ends at
    it). A line with no corner comes back as it was."""
    corners = _corners(line)
    if not corners:
        return list(line), sorted(keep)
    kept = set(keep) | set(corners) | {0, len(line) - 1}
    dropped: set[int] = set()
    for corner in corners:
        metres = 0.0
        i = corner - 1
        while i > 0:
            metres += haversine(Point(*line[i]), Point(*line[i + 1]))
            if metres > CORNER_CLEAR_M or i in kept:
                break
            dropped.add(i)
            i -= 1
    order = [i for i in range(len(line)) if i not in dropped]
    new = {old: n for n, old in enumerate(order)}
    return [line[i] for i in order], sorted(new[i] for i in keep)


def request_for(line, points, plan_request: dict) -> dict:
    """The plan's request (`routing.plan`'s, its costing, elevation and directions) as a
    `/trace_route` of `line`, split into legs at the plan's points, with each corner cleared
    for the matcher (`clear_corners`)."""
    split, indices = split_line(line, points)
    split, indices = clear_corners(split, indices)
    shape = [{"lon": lon, "lat": lat} for lon, lat in split]
    for index in indices:
        shape[index]["type"] = routing.VIA_LOCATION_TYPE
    asked = {
        key: value
        for key, value in plan_request.items()
        if key not in ("locations", "alternates", "exclude_polygons", "exclude_locations")
    }
    asked.update(
        shape=shape,
        shape_match="map_snap",
        trace_options={"search_radius": SEARCH_RADIUS_M},
    )
    return asked


def _encode(points) -> str:
    from .dedodge import encode_polyline6

    return encode_polyline6(points)


def _shape(leg: dict) -> list[tuple[float, float]]:
    return routing.decode_polyline6(leg.get("shape", ""))


def merge_legs(first: dict, second: dict, interval_m: float | None) -> dict:
    """One leg: `first` then `second`, the vertex they share once. Lengths, times and costs
    add; heights run on (a leg without any gets none for its length, every `interval_m`);
    `second`'s manoeuvres follow `first`'s, but for `first`'s arrival and `second`'s start."""
    a, b = _shape(first), _shape(second)
    joint = 1 if a and b and a[-1] == b[0] else 0
    shape = a + b[joint:]
    summary = dict(first.get("summary") or {})
    other = second.get("summary") or {}
    for key in ("length", "time", "cost"):
        if key in summary or key in other:
            summary[key] = float(summary.get(key, 0.0)) + float(other.get(key, 0.0))
    merged = {**first, "shape": _encode(shape), "summary": summary}
    heights_a, heights_b = first.get("elevation"), second.get("elevation")
    if heights_a or heights_b:

        def filled(leg: dict, heights) -> list:
            if heights:
                return list(heights)
            km = float((leg.get("summary") or {}).get("length", 0.0))
            return [None] * (max(1, round(km * 1000.0 / interval_m)) + 1 if interval_m else 0)

        ha, hb = filled(first, heights_a), filled(second, heights_b)
        merged["elevation"] = ha + hb[1:] if ha and hb else ha + hb
    offset = len(a) - joint
    moves = [m for m in first.get("maneuvers") or [] if m.get("type") not in (4, 5, 6)]
    for m in second.get("maneuvers") or []:
        if m.get("type") in (1, 2, 3):
            # `second`'s start: the ride goes on, so it is not said again mid-route.
            continue
        m = dict(m)
        for key in ("begin_shape_index", "end_shape_index"):
            if isinstance(m.get(key), int):
                m[key] += offset
        moves.append(m)
    if first.get("maneuvers") is not None or second.get("maneuvers") is not None:
        merged["maneuvers"] = moves
    return merged


def joined(answer: dict, line, route_between, interval_m: float | None) -> dict:
    """`answer` (a `/trace_route`'s) as one trip along `line`: where the matcher broke the
    line, the pieces after the first come as `alternates`; each gap between one piece's end
    and the next one's start, and the file's own start and end where the match begins or
    ends away from them, is joined by `route_between(a, b)` (the router's leg from a to b,
    or None where it has none, which leaves an end as it was and refuses a gap with
    `routing.RouterRefused`)."""
    pieces = [answer.get("trip") or {}] + [
        (alternate or {}).get("trip") or {} for alternate in answer.get("alternates") or []
    ]
    legs: list[dict] = []
    bridges = 0
    for piece in pieces:
        piece_legs = [leg for leg in piece.get("legs") or [] if len(_shape(leg)) >= 2]
        if not piece_legs:
            continue
        if legs:
            end, start = _shape(legs[-1])[-1], _shape(piece_legs[0])[0]
            if haversine(Point(*end), Point(*start)) > 1.0:
                bridges += 1
                if bridges > MAX_BRIDGES:
                    raise routing.RouterRefused(400, 442, "too many breaks in the match")
                bridge = route_between(end, start)
                if bridge is None:
                    raise routing.RouterRefused(400, 442, "no route across a break in the match")
                legs[-1] = merge_legs(legs[-1], bridge, interval_m)
            legs[-1] = merge_legs(legs[-1], piece_legs[0], interval_m)
            legs.extend(piece_legs[1:])
        else:
            legs.extend(piece_legs)
    if not legs:
        raise routing.RouterRefused(400, 442, "no matched shape")
    start, end = tuple(line[0]), tuple(line[-1])
    first_at, last_at = _shape(legs[0])[0], _shape(legs[-1])[-1]
    if haversine(Point(*start), Point(*first_at)) > END_GAP_M:
        lead = route_between(start, first_at)
        if lead is not None:
            legs[0] = merge_legs(lead, legs[0], interval_m)
    if haversine(Point(*last_at), Point(*end)) > END_GAP_M:
        tail = route_between(last_at, end)
        if tail is not None:
            legs[-1] = merge_legs(legs[-1], tail, interval_m)
    trip = dict(pieces[0])
    trip["legs"] = legs
    summary = dict(trip.get("summary") or {})
    for key in ("length", "time", "cost"):
        summary[key] = sum(float((leg.get("summary") or {}).get(key, 0.0)) for leg in legs)
    trip["summary"] = summary
    return {"trip": trip}


def without_ignored(costing_options: dict) -> dict:
    """`costing_options` with `EXACT` (and so `IGNORED`) taken out of every costing's options."""
    return {
        name: {k: v for k, v in options.items() if k not in EXACT}
        if isinstance(options, dict)
        else options
        for name, options in costing_options.items()
    }


def _against(edge: dict) -> bool:
    """Whether an edge was ridden against the one-way traffic of its way (by bicycle: a way
    whose bicycles may ride both ways, a contraflow lane, is `both`)."""
    allowed, forward = edge.get("traversability"), edge.get("forward")
    if not isinstance(forward, bool):
        return False
    return (allowed == "forward" and not forward) or (allowed == "backward" and forward)


def is_exact(costing_options: dict) -> bool:
    """Whether `costing_options` are the manual mode's (`EXACT`)."""
    return any(
        isinstance(options, dict) and options.get("ignore_oneways") is True
        for options in costing_options.values()
    )


def _stretches(edges: list[dict], shape=None) -> list[dict]:
    """The runs of `edges` ridden against one-way traffic, by street, at least AGAINST_MIN_M;
    with `shape` (the match's line), each with the middle of every edge in it (`at`)."""
    stretches: list[dict] = []
    joined_on = False
    for edge in edges:
        if not _against(edge):
            joined_on = False
            continue
        names = [n for n in edge.get("names") or () if isinstance(n, str) and n.strip()]
        name = names[0] if names else None
        metres = float(edge.get("length") or 0.0) * 1000.0
        if not (joined_on and stretches[-1]["name"] == name):
            stretches.append({"name": name, "distance_m": 0.0, "at": []})
        stretches[-1]["distance_m"] += metres
        begin, end = edge.get("begin_shape_index"), edge.get("end_shape_index")
        if (
            shape
            and isinstance(begin, int)
            and isinstance(end, int)
            and 0 <= begin <= end < len(shape)
        ):
            stretches[-1]["at"].append(_middle(shape[begin : end + 1]))
        joined_on = True
    return [
        {"name": s["name"], "distance_m": round(s["distance_m"], 1)}
        | ({"at": s["at"]} if shape is not None else {})
        for s in stretches
        if s["distance_m"] >= AGAINST_MIN_M
    ]


def _middle(points) -> tuple[float, float]:
    """The point halfway along `points` (a line)."""
    steps = [haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False)]
    half = sum(steps) / 2.0
    for (a, b), step in zip(zip(points, points[1:], strict=False), steps, strict=True):
        if step >= half and step > 0:
            t = half / step
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        half -= step
    return tuple(points[0])


def gone_round(stretches: list[dict], route_line) -> list[dict]:
    """Of `stretches` (`wrong_way`'s), those the route really leaves: one whose every edge
    the route passes within DIVIDED_M of is the file's GPS on the other half of a divided road
    (the matcher, one-ways ignored, may take either), not a stretch ridden wrong way."""
    route = list(route_line)

    def near(p) -> bool:
        return any(
            _projected(p, a, b)[1] <= DIVIDED_M for a, b in zip(route, route[1:], strict=False)
        )

    return [
        {"name": s["name"], "distance_m": s["distance_m"]}
        for s in stretches
        if not s.get("at") or not all(near(p) for p in s["at"])
    ]


def as_ridden(line, trace_attributes, costing_options: dict) -> dict | None:
    """`line` matched as ridden, one-way traffic and turn restrictions ignored (`IGNORED`):
    the router's `/trace_attributes` answer, which `wrong_way` and `crosswalk_cuts` read.
    None where the router refused the line; a router that does not answer is raised, as the
    trace after it would be."""
    payload = {
        "encoded_polyline": _encode(line),
        "costing": "bicycle",
        "costing_options": {
            name: {**options, **IGNORED} if isinstance(options, dict) else options
            for name, options in (costing_options or {"bicycle": {}}).items()
        },
        "units": "kilometers",
        "shape_match": "map_snap",
        "trace_options": {"search_radius": SEARCH_RADIUS_M},
        "filters": {
            "attributes": [
                "edge.length",
                "edge.names",
                "edge.traversability",
                "edge.forward",
                # What `crosswalk_cuts` reads (map_match.FOOT_USES, ROAD_USES).
                "edge.use",
                "edge.begin_shape_index",
                "edge.end_shape_index",
                "matched.edge_index",
                # The match's line, for each stretch's points (`at`, `gone_round`): with an
                # include filter the router leaves out any field not named (audit R3).
                "shape",
            ],
            "action": "include",
        },
    }
    try:
        return trace_attributes(payload)
    except routing.RouterRefused:
        return None


def wrong_way(
    line, keep, trace_attributes, costing_options: dict, *, answer: dict | None = None
) -> tuple[set[int], list[dict]] | None:
    """Where `line` rides against one-way traffic, matched as ridden (`as_ridden`, or its
    `answer` where it is given): the indexes of its points on such a way (never those in
    `keep`, the plan's points), to leave out of the match so the router goes round, and the
    stretches (`against_traffic`), each with the middle of every edge in it (`at`, for
    `gone_round`). None where the router refused the line; a router that does not answer is
    raised, as the trace after it would be."""
    if len(line) < 2:
        return set(), []
    if answer is None:
        answer = as_ridden(line, trace_attributes, costing_options)
        if answer is None:
            return None
    edges = answer.get("edges") or []
    against = {i for i, edge in enumerate(edges) if _against(edge)}
    if not against:
        return set(), []
    dropped = {
        i
        for i, point in enumerate(answer.get("matched_points") or [])
        if i not in keep and (point or {}).get("edge_index") in against
    }
    shape = routing.decode_polyline6(answer.get("shape") or "")
    return dropped, _stretches(edges, shape)


def crosswalk_cuts(answer: dict, keep) -> list[dict]:
    """Where the line itself goes round a corner on its crosswalks (Stephen 2026-11-04, "There
    are still phantom red intersections", a residential four-way stop with a ladder crosswalk
    on each arm). `clear_corners` keeps the matcher from cutting a corner the line turns on
    the road; a line that already rides the crosswalks round it (a file made from such a
    route, or a GPS track cutting the corner) was followed onto them, a red "Cross the road"
    piece. Each crosswalk tangle of the match as ridden (`answer`, `as_ridden`'s;
    `map_match._tangles`) is taken with the scraps of road under map_match.SCRAP_M either side
    of it, so the way back on the road starts and ends at the junction rather than a few
    metres past it. Each cut gives the line's points to replace (those between `after` and
    `before`; never round a plan's point in `keep`), the road points either side of it on the
    match's line (`a`, `b`) and its length in metres (`metres`), for the router's own way
    between them (`uncut`). An opened file snapped to the map (POST /api/match) is
    untangled there already."""
    from . import map_match

    edges = answer.get("edges") or []
    matched = [(point or {}).get("edge_index") for point in answer.get("matched_points") or []]
    shape = routing.decode_polyline6(answer.get("shape") or "")
    if not edges or not matched or not shape:
        return []

    def edge_m(i: int) -> float:
        length = (edges[i] or {}).get("length")
        return float(length) * 1000.0 if isinstance(length, (int, float)) else 0.0

    def road(i: int) -> bool:
        return (edges[i] or {}).get("use") in map_match.ROAD_USES

    def road_scrap(i: int) -> bool:
        length = (edges[i] or {}).get("length")
        return (
            road(i)
            and isinstance(length, (int, float))
            and float(length) * 1000.0 < map_match.SCRAP_M
        )

    positions = [i for i, e in enumerate(matched) if isinstance(e, int)]
    order = [matched[i] for i in positions]
    if order != sorted(order):
        return []
    out: list[dict] = []
    for first, last in map_match._tangles(edges):
        metres = sum(edge_m(i) for i in range(first, last + 1))
        # A scrap of road between the tangle and the junction it turns at belongs to it: under
        # map_match.SCRAP_M on each side in all.
        taken = 0.0
        while (
            first - 2 >= 0
            and road_scrap(first - 1)
            and road(first - 2)
            and taken + edge_m(first - 1) < map_match.SCRAP_M
        ):
            first -= 1
            taken += edge_m(first)
        metres += taken
        taken = 0.0
        while (
            last + 2 < len(edges)
            and road_scrap(last + 1)
            and road(last + 2)
            and taken + edge_m(last + 1) < map_match.SCRAP_M
        ):
            last += 1
            taken += edge_m(last)
        metres += taken
        begin = (edges[first] or {}).get("begin_shape_index")
        end = (edges[last] or {}).get("end_shape_index")
        if not (isinstance(begin, int) and isinstance(end, int) and 0 <= begin < end < len(shape)):
            continue
        # The matched points' edges run in order along the line (checked below for those between).
        b_i = bisect.bisect_left(order, first)
        a_i = bisect.bisect_right(order, last)
        if b_i == 0 or a_i >= len(order):
            continue
        after, before = positions[b_i - 1], positions[a_i]
        inside = range(after + 1, before)
        if after >= before or any(i in keep for i in inside):
            continue
        if any(isinstance(matched[i], int) and not first <= matched[i] <= last for i in inside):
            continue
        if out and after < out[-1]["before"]:
            continue
        out.append(
            {
                "after": after,
                "before": before,
                "a": tuple(shape[begin]),
                "b": tuple(shape[end]),
                "metres": metres,
            }
        )
    return out


def uncut(
    shape: list[dict], cuts: list[dict], route_between, dropped=frozenset()
) -> list[dict] | None:
    """`shape` (a `/trace_route`'s, `request_for`'s), its points in `dropped` (`wrong_way`'s)
    left out, with each of `crosswalk_cuts`' `cuts` put back on the road: its points replaced
    by the router's way from `a` to `b` (`route_between(a, b)`, a leg or None), where that way
    is no more than map_match.DETOUR_SLACK_M longer than the tangle, and a tangle that comes
    back to the point it left cut out; then each corner cleared again (`clear_corners`), the
    plan's points (`routing.VIA_LOCATION_TYPE`) kept. None where no cut was made; at most
    map_match.MAX_UNTANGLED routes are asked for."""
    from . import map_match

    pieces: list[tuple[int, int, list]] = []
    asked = 0
    for cut in cuts:
        a, b = cut["a"], cut["b"]
        if haversine(Point(*a), Point(*b)) < SAME_M:
            pieces.append((cut["after"], cut["before"], []))
            continue
        if asked >= map_match.MAX_UNTANGLED:
            continue
        asked += 1
        leg = route_between(a, b)
        way = _shape(leg) if leg else []
        if len(way) < 2 or map_match._metres(way) > cut["metres"] + map_match.DETOUR_SLACK_M:
            continue
        pieces.append((cut["after"], cut["before"], [{"lon": lon, "lat": lat} for lon, lat in way]))
    if not pieces:
        return None
    out: list = [None if i in dropped else p for i, p in enumerate(shape)]
    for after, before, way in reversed(pieces):
        out[after + 1 : before] = [{**p, "_way": True} for p in way]
    out = [p for p in out if p is not None]
    # The way's ends where they are the points either side already: not twice.
    out = [
        p
        for i, p in enumerate(out)
        if not (
            p.get("_way")
            and any(
                0 <= j < len(out)
                and not out[j].get("_way")
                and haversine(Point(p["lon"], p["lat"]), Point(out[j]["lon"], out[j]["lat"]))
                < SAME_M
                for j in (i - 1, i + 1)
            )
        )
    ]
    # The corners cleared again only round the ways put in (`clear_corners` keeps every
    # other point): the rest of the line was cleared before (`request_for`).
    near = set()
    for i, p in enumerate(out):
        if p.get("_way"):
            near.add(i)
            metres, j = 0.0, i - 1
            while j >= 0 and not out[j].get("_way"):
                metres += haversine(
                    Point(out[j]["lon"], out[j]["lat"]), Point(out[j + 1]["lon"], out[j + 1]["lat"])
                )
                if metres > CORNER_CLEAR_M:
                    break
                near.add(j)
                j -= 1
    vias = {i for i, p in enumerate(out) if p.get("type") == routing.VIA_LOCATION_TYPE}
    fixed = (set(range(len(out))) - near) | vias
    line, kept = clear_corners([(p["lon"], p["lat"]) for p in out], fixed)
    via_at = set()
    for old, new in zip(sorted(fixed), kept, strict=True):
        if old in vias:
            via_at.add(new)
    cleared = [{"lon": lon, "lat": lat} for lon, lat in line]
    for i in via_at:
        cleared[i]["type"] = routing.VIA_LOCATION_TYPE
    return cleared


def against_traffic(line, trace_attributes, costing_options: dict) -> list[dict] | None:
    """The stretches of `line` (the followed route's) ridden against one-way traffic, in
    order: each street's name (null where it has none) and its length in metres, at least
    AGAINST_MIN_M. `trace_attributes(payload)` asks the router; None where it could not say."""
    if len(line) < 2:
        return []
    payload = {
        "encoded_polyline": _encode(line),
        "costing": "bicycle",
        "costing_options": costing_options,
        "units": "kilometers",
        "filters": {
            "attributes": ["edge.length", "edge.names", "edge.traversability", "edge.forward"],
            "action": "include",
        },
    }
    # As `routing.trace_leg`: by edge walk, and by map snap where the walk is refused.
    for match in ("edge_walk", "map_snap"):
        try:
            edges = trace_attributes({**payload, "shape_match": match}).get("edges") or []
            break
        except routing.RouterRefused:
            continue
        except (routing.RouterUnavailable, routing.DeadlineExceeded):
            return None
    else:
        return None
    return _stretches(edges)
