"""An opened GPX track snapped to the routable network (PLAN.md, Import: map matching), so the
plan can follow ways the router knows and rate and reroute them.

POST /api/match (core.api) sends the track's line here, already the part inside the coverage box
and simplified in the browser (frontend lib/gpxMatch.ts); one `/trace_attributes` call on the ride
type's own graph and costing, `shape_match: map_snap`, gives the matched line and each track
point's match (matched, interpolated or unmatched). Nothing is kept or logged: the answer is the
snapped line and the share of the track that matched, and the browser keeps the file itself
unchanged beside it.

Synchronous and bounded, like a route: at most `MAX_POINTS` points and `MAX_BYTES` of body, one
router call inside `BUDGET_S`, counted against the routing rate limit. PLAN's worker job with a
progress endpoint is for whole 100,000-point files; the browser sends at most the 5,000-vertex
line it already draws.
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
        "filters": {"attributes": ["shape", "matched.type"], "action": "include"},
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
        answer = routing._call(Variant.STANDARD.value, "trace_attributes", payload, deadline)
    line = routing.decode_polyline6(answer.get("shape") or "")
    if len(line) < 2:
        raise routing.RouterRefused(400, None, "no matched shape")
    kinds = [m.get("type") for m in answer.get("matched_points") or [] if isinstance(m, dict)]
    found = sum(1 for k in kinds if k in ("matched", "interpolated"))
    share = found / len(points) if kinds else 0.0
    return {
        "line": [[round(lon, 6), round(lat, 6)] for lon, lat in line],
        "matched_share": round(share, 3),
    }
