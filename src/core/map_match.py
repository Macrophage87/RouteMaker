"""An opened GPX track snapped to the routable network (PLAN.md, Import: map matching), so the
plan can follow ways the router knows and rate and reroute them.

POST /api/match (core.api) sends the track's line here, already the part inside the coverage box
and simplified in the browser (frontend lib/gpxMatch.ts); one `/trace_attributes` call on the
ride type's own graph and costing, `shape_match: map_snap`, gives the matched line and each
track point's match (matched, interpolated or unmatched), and the crosswalk loops the matcher
snaps into it are put back on the road (`untangle`, one router `/route` each). Nothing is kept
or logged: the answer is the snapped line and the share of the track that matched, and the
browser keeps the file itself unchanged beside it.

Synchronous and bounded, like a route: at most `MAX_POINTS` points and `MAX_BYTES` of body, one
trace and at most MAX_UNTANGLED short routes inside `BUDGET_S`, counted against the routing rate
limit. PLAN's worker job with a progress endpoint is for whole 100,000-point files; the browser
sends at most the 5,000-vertex line it already draws.
"""

from __future__ import annotations

import math

from django.conf import settings

from pipeline.variants import Variant
from routemaker.geo import Point, haversine

from . import presets, routing

# The browser's simplified line of the file (frontend lib/gpxPlan.ts REFERENCE_MAX_VERTICES).
MAX_POINTS = 5000
# 5,000 [lon, lat] pairs at full precision are about 200 KB of JSON.
MAX_BYTES = 256 * 1024
BUDGET_S = 30.0
PER_CALL_S = 25.0
# How far from a track point the matcher looks for a way: GPS on a phone under trees or between
# buildings is often 20 to 40 m out (Valhalla's default is 50 m too).
SEARCH_RADIUS_M = 50
# Valhalla's trace limit (valhalla/*.json, trace.max_distance), checked here so a refusal is said
# in words rather than as the router's code.
MAX_DISTANCE_M = 200_000

# Crosswalk loops (`untangle`; Stephen 2026-11-01, "several phantom LTS4 unnamed roads", then
# "can you make that step?"). The matcher joins the points it matches by the shortest path by
# distance, whatever the costing prices (Valhalla 3.9.1, src/meili/routing.cc), so a track
# that waits at a corner, its GPS wandering a few metres, is snapped round and round the
# crosswalks there, and one that turns a corner can be snapped across them, a metre shorter
# than the road (OSM 1239622654, a ring of `footway=crossing` round 14th St SE and K St SE).
# Ridden crosswalks rate LTS 4 (routemaker.sidewalks), so each loop came out a red "Cross the
# road" piece. Each such tangle - crosswalk and sidewalk edges, with the scraps of road under
# SCRAP_M between them - that leaves a road and comes back to one, FOOT_MAX_M or less of
# crosswalk in all, is put back on the router's own way between the two road points, where
# that way is no more than DETOUR_SLACK_M longer than the tangle. Longer runs are kept: a
# track that really rides a sidewalk or crosses to a path rides it.
FOOT_USES = frozenset({"pedestrian_crossing", "sidewalk"})
# The ways a tangle leaves and comes back to: a road. A crosswalk between two trail edges is
# the trail crossing a street, ridden as mapped.
ROAD_USES = frozenset(
    {
        "road",
        "ramp",
        "turn_channel",
        "track",
        "driveway",
        "alley",
        "parking_aisle",
        "culdesac",
        "living_street",
        "service_road",
    }
)
SCRAP_M = 15.0
FOOT_MAX_M = 60.0
DETOUR_SLACK_M = 30.0
# The most router calls `untangle` makes for one track.
MAX_UNTANGLED = 20


class TrackProblem(ValueError):
    """The line sent is not one this endpoint matches; the message says why."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def checked_points(points) -> list[tuple[float, float]]:
    """The track's [lon, lat] points, or TrackProblem."""
    if not isinstance(points, list) or len(points) < 2:
        raise TrackProblem("Send the track as a list of at least two [longitude, latitude] points.")
    if len(points) > MAX_POINTS:
        raise TrackProblem(f"The track has more than {MAX_POINTS:,} points.")
    west, south, east, north = settings.COVERAGE_BBOX
    out: list[tuple[float, float]] = []
    for p in points:
        if not (isinstance(p, list) and len(p) == 2 and all(_finite(v) for v in p)):
            raise TrackProblem("Each point of the track is [longitude, latitude].")
        lon, lat = float(p[0]), float(p[1])
        if not (west <= lon <= east and south <= lat <= north):
            raise TrackProblem("The track has a point outside the area this map covers.")
        out.append((lon, lat))
    length = sum(haversine(Point(*a), Point(*b)) for a, b in zip(out, out[1:], strict=False))
    if length > MAX_DISTANCE_M:
        raise TrackProblem(
            "The track is longer than 124 mi (200 km), the most that can be snapped at once."
        )
    return out


def match(
    points: list[tuple[float, float]],
    preset_name: str,
    started: float | None = None,
    trails_off: bool = False,
    assist: bool = False,
):
    """The snapped line and the share of `points` that matched a way.

    On the graph the ride itself routes on (`presets.variant_for_ride`, as `routing.plan`
    chooses it): "Keep to roads, not trails" snaps to the no-trail graph, electric assist to the
    e-bike one. Raises routing.RouterRefused when the matcher finds no way along the track,
    routing.RouterUnavailable or routing.DeadlineExceeded, and KeyError for an unknown preset.
    """
    assist = assist and presets.PRESETS[preset_name].assist_speed_kmh is not None
    variant = presets.variant_for_ride(preset_name, routing.default_when(), assist, trails_off)
    payload = {
        "shape": [{"lon": lon, "lat": lat} for lon, lat in points],
        "costing": "bicycle",
        "costing_options": presets.costing(preset_name, assist=assist),
        "shape_match": "map_snap",
        "trace_options": {"search_radius": SEARCH_RADIUS_M},
        "filters": {
            "attributes": [
                "shape",
                "matched.type",
                # What `untangle` reads.
                "edge.use",
                "edge.length",
                "edge.begin_shape_index",
                "edge.end_shape_index",
            ],
            "action": "include",
        },
    }
    begun = routing.clock() if started is None else started
    deadline = routing.Deadline(begun + BUDGET_S, PER_CALL_S)
    try:
        answer = routing._call(variant, "trace_attributes", payload, deadline)
    except routing.RouterUnavailable:
        # A twin graph (weekend, off-road, mountain bike) not answering: the standard graph it
        # was built from has the same ways to snap to, near enough.
        if variant not in routing.TWIN_VARIANTS:
            raise
        variant = Variant.STANDARD.value
        answer = routing._call(variant, "trace_attributes", payload, deadline)
    line = routing.decode_polyline6(answer.get("shape") or "")
    if len(line) < 2:
        raise routing.RouterRefused(400, None, "no matched shape")
    bridge = {
        "costing": "bicycle",
        "costing_options": payload["costing_options"],
        "directions_type": "none",
    }

    def route_between(a, b) -> list | None:
        asked = {
            **bridge,
            "locations": [
                {"lon": a[0], "lat": a[1], "type": "break", "radius": 1},
                {"lon": b[0], "lat": b[1], "type": "break", "radius": 1},
            ],
        }
        try:
            legs = (routing._call(variant, "route", asked, deadline).get("trip") or {}).get(
                "legs"
            ) or []
        except (routing.RouterRefused, routing.RouterUnavailable, routing.DeadlineExceeded):
            return None
        if len(legs) != 1:
            return None
        return routing.decode_polyline6(legs[0].get("shape") or "") or None

    line = untangle(line, answer.get("edges") or [], route_between)
    kinds = [m.get("type") for m in answer.get("matched_points") or [] if isinstance(m, dict)]
    found = sum(1 for k in kinds if k in ("matched", "interpolated"))
    share = found / len(points) if kinds else 0.0
    return {
        "line": [[round(lon, 6), round(lat, 6)] for lon, lat in line],
        "matched_share": round(share, 3),
    }


def _metres(points) -> float:
    return sum(haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False))


def _tangles(edges: list[dict]) -> list[tuple[int, int]]:
    """The (first, last) edge indexes of each crosswalk tangle in `edges` (see FOOT_USES): a
    run of crosswalk and sidewalk edges, scraps of other ways under SCRAP_M between them taken
    in, with a road (ROAD_USES) before it and after it, and FOOT_MAX_M or less of crosswalk
    in all. An edge with no length is taken as too long to be a tangle."""
    foot = [(edge or {}).get("use") in FOOT_USES for edge in edges]
    metres = [
        float(length) * 1000.0
        if isinstance((length := (edge or {}).get("length")), (int, float))
        else math.inf
        for edge in edges
    ]
    road = [(edge or {}).get("use") in ROAD_USES for edge in edges]
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(edges):
        if not foot[i]:
            i += 1
            continue
        first = last = i
        j = i + 1
        while j < len(edges):
            if foot[j]:
                last = j
                j += 1
                continue
            # A scrap of road between two crosswalks belongs to the tangle.
            k, scrap = j, 0.0
            while k < len(edges) and not foot[k] and scrap + metres[k] < SCRAP_M:
                scrap += metres[k]
                k += 1
            if k < len(edges) and foot[k] and k > j:
                j = k
                continue
            break
        walked = sum(
            m for m, f in zip(metres[first : last + 1], foot[first : last + 1], strict=True) if f
        )
        if first > 0 and last < len(edges) - 1 and road[first - 1] and road[last + 1]:
            if walked <= FOOT_MAX_M:
                out.append((first, last))
        i = last + 1
    return out


def untangle(line: list, edges: list[dict], route_between) -> list:
    """`line` (the match's) with each crosswalk tangle (`_tangles`) put back on the router's
    way between the road points either side of it, `route_between(a, b)` giving that way's
    line (or None, which keeps the tangle); a tangle that comes back to the point it left is
    cut out. A tangle whose shape indexes are missing, outside the line or not after the last
    one's is left as it is; at most MAX_UNTANGLED routes are asked for."""
    pieces = []
    after = 0
    asked = 0
    for first, last in _tangles(edges):
        begin = edges[first].get("begin_shape_index")
        end = edges[last].get("end_shape_index")
        if not (
            isinstance(begin, int) and isinstance(end, int) and after <= begin < end < len(line)
        ):
            continue
        a, b = tuple(line[begin]), tuple(line[end])
        tangle = _metres(line[begin : end + 1])
        if haversine(Point(*a), Point(*b)) < 1.0:
            pieces.append((begin, end, [a]))
            after = end
            continue
        if asked >= MAX_UNTANGLED:
            continue
        asked += 1
        way = route_between(a, b)
        if not way or _metres(way) > tangle + DETOUR_SLACK_M:
            continue
        pieces.append((begin, end, [a, *[tuple(p) for p in way[1:-1]], b]))
        after = end
    out = [tuple(p) for p in line]
    for begin, end, way in reversed(pieces):
        out[begin : end + 1] = way
    return out
