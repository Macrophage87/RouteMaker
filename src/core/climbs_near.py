"""The categorised climbs near a point (v0.12.3; the Climbs layer's file, `core.hillseek`).

The owner, 2026-10-25, of hill repeats for intervals: "steep climbs can be great for
intervals as you can easily get back to start without much effort and you don't need as
much distance", and of a search for them before there is a route: "Yep, add that". The
connector's `climbs_near` tool (mcp/routemaker_mcp.py) asks this for the climbs within reach
of a point, each with its foot and summit for a plan up it, so an assistant can find a hill
to ride up for each effort and back down to recover.

Read from the Climbs layer's file (every Cat 5 to HC climb on the routable network,
`pipeline.climb_layer`); nothing here reads the database or the router.
"""

from __future__ import annotations

import math

from . import hillseek

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084
MAX_RADIUS_MI = 15.0
MAX_CLIMBS = 25
SURFACES = {"p": "path", "g": "gravel", "m": "mountain-bike trail"}


class Unavailable(Exception):
    """This host has no Climbs layer file."""


def _away_m(point: tuple[float, float], line) -> float:
    """The metres from `point` to the line's nearest vertex (the file keeps a vertex every
    few hundred metres at most, near enough to rank by)."""
    lon, lat = point
    k = math.cos(math.radians(lat))
    best = min((a - lon) ** 2 * k * k + (b - lat) ** 2 for a, b in line)
    return math.sqrt(best) * 111_320


def near(lon: float, lat: float, miles: float, min_grade: float = 0.0) -> list[dict]:
    """The climbs within `miles` (at most MAX_RADIUS_MI) of the point, nearest first, at
    least `min_grade` % on average: {id, name, category, miles, gain_ft, grade_pct, foot,
    summit, through (points up it, for a plan that rides it), surface, busy, away_mi}.
    Raises Unavailable without the file."""
    climbs = hillseek.load()
    if climbs is None:
        raise Unavailable("there is no climbs file")
    reach_m = min(miles, MAX_RADIUS_MI) * METRES_PER_MILE
    # A quick box first: a degree of latitude is 111 km.
    dlat = reach_m / 111_320
    dlon = dlat / max(0.1, math.cos(math.radians(lat)))
    found = []
    for climb in climbs:
        if climb.grade_pct < min_grade:
            continue
        if not any(abs(a - lon) <= dlon and abs(b - lat) <= dlat for a, b in climb.line):
            continue
        away = _away_m((lon, lat), climb.line)
        if away <= reach_m:
            found.append((away, climb))
    found.sort(key=lambda pair: pair[0])
    return [
        {
            "id": climb.id,
            "name": climb.name,
            "category": climb.category,
            "miles": round(climb.length_m / METRES_PER_MILE, 2),
            "gain_ft": round(climb.gain_m * FEET_PER_METRE),
            "grade_pct": climb.grade_pct,
            "foot": list(climb.foot),
            "summit": list(climb.summit),
            "through": [[round(a, 6), round(b, 6)] for a, b in hillseek.via_points(climb)[1:-1]],
            "surface": SURFACES.get(climb.surface, "road"),
            "busy": climb.busy,
            "away_mi": round(away / METRES_PER_MILE, 1),
        }
        for away, climb in found[:MAX_CLIMBS]
    ]
