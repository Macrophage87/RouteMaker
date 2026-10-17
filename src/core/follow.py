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

import math

from routemaker.geo import Point, haversine

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
# The most breaks in a match joined by the router's own route: more, and the file is planned
# through its points instead (each join is a router call).
MAX_BRIDGES = 20
# What a `/trace_route` asks that a `/route` between two points does not.
TRACE_ONLY = frozenset({"shape", "shape_match", "trace_options"})


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


def request_for(line, points, plan_request: dict) -> dict:
    """The plan's request (`routing.plan`'s, its costing, elevation and directions) as a
    `/trace_route` of `line`, split into legs at the plan's points."""
    split, indices = split_line(line, points)
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


def _stretches(edges: list[dict]) -> list[dict]:
    """The runs of `edges` ridden against one-way traffic, by street, at least AGAINST_MIN_M."""
    stretches: list[dict] = []
    joined_on = False
    for edge in edges:
        if not _against(edge):
            joined_on = False
            continue
        names = [n for n in edge.get("names") or () if isinstance(n, str) and n.strip()]
        name = names[0] if names else None
        metres = float(edge.get("length") or 0.0) * 1000.0
        if joined_on and stretches[-1]["name"] == name:
            stretches[-1]["distance_m"] += metres
        else:
            stretches.append({"name": name, "distance_m": metres})
        joined_on = True
    return [
        {"name": s["name"], "distance_m": round(s["distance_m"], 1)}
        for s in stretches
        if s["distance_m"] >= AGAINST_MIN_M
    ]


def wrong_way(
    line, keep, trace_attributes, costing_options: dict
) -> tuple[set[int], list[dict]] | None:
    """Where `line` rides against one-way traffic, matched as ridden: the indexes of its
    points on such a way (never those in `keep`, the plan's points), to leave out of the
    match so the router goes round, and the stretches (`against_traffic`). None where the
    router could not say."""
    if len(line) < 2:
        return set(), []
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
                "matched.edge_index",
            ],
            "action": "include",
        },
    }
    try:
        answer = trace_attributes(payload)
    except (routing.RouterRefused, routing.RouterUnavailable, routing.DeadlineExceeded):
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
    return dropped, _stretches(edges)


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
