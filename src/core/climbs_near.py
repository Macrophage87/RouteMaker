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
# An effort's speed up a climb: pace / (1 + CLIMB_SLOWING x grade %), the connector's own
# rough fit (mcp/routemaker_mcp.py, `climb_minutes`): 18 mph on the flat is about 11 at 5%.
CLIMB_SLOWING = 0.12
SURFACES = {"p": "path", "g": "gravel", "m": "mountain-bike trail"}


class Unavailable(Exception):
    """This host has no Climbs layer file."""


def _away_m(point: tuple[float, float], line) -> float:
    """The metres from `point` to the line (to its nearest segment, on a local plane)."""
    lon, lat = point
    k = math.cos(math.radians(lat))
    xy = [((a - lon) * k, b - lat) for a, b in line]
    best = min(x * x + y * y for x, y in xy)
    for (x0, y0), (x1, y1) in zip(xy, xy[1:], strict=False):
        dx, dy = x1 - x0, y1 - y0
        length = dx * dx + dy * dy
        if length <= 0:
            continue
        t = max(0.0, min(1.0, -(x0 * dx + y0 * dy) / length))
        best = min(best, (x0 + t * dx) ** 2 + (y0 + t * dy) ** 2)
    return math.sqrt(best) * 111_320


def _surface(climb: hillseek.Climb) -> str:
    # A file built before 2026-10-19 has no `s`: its `u` still says unpaved.
    if climb.surface in SURFACES:
        return SURFACES[climb.surface]
    return "gravel" if climb.unpaved else "road"


def near(
    lon: float,
    lat: float,
    miles: float,
    min_grade: float = 0.0,
    on_minutes: float = 0.0,
    pace_mph: float = 18.0,
    paved_only: bool = False,
    quiet_only: bool = False,
    steepest: bool = False,
) -> list[dict]:
    """The climbs within `miles` (at most MAX_RADIUS_MI) of the point, at least `min_grade` %
    on average and long enough for an effort of `on_minutes` up it at `pace_mph` on the flat
    (slower up the grade), paved only or off busy roads only where asked; nearest
    first, or steepest first: {id, name, category, miles, gain_ft, grade_pct, foot, summit,
    through (points up it, for a plan that rides it), surface, busy, away_mi}. `busy` is null
    where the file predates it (no climb in it is marked). Raises Unavailable without the
    file. Every filter applies before the MAX_CLIMBS cut."""
    climbs = hillseek.load()
    if climbs is None:
        raise Unavailable("there is no climbs file")
    busy_known = any(climb.busy for climb in climbs)
    reach_m = min(miles, MAX_RADIUS_MI) * METRES_PER_MILE
    # A quick box first (a degree of latitude is 111 km), wide by the longest segment a
    # line in the file has, so a climb passing by between two far vertices is kept.
    dlat = (reach_m + 5_000) / 111_320
    dlon = dlat / max(0.1, math.cos(math.radians(lat)))
    found = []
    for climb in climbs:
        if climb.grade_pct < min_grade:
            continue
        if on_minutes:
            speed = pace_mph / (1 + CLIMB_SLOWING * max(0.0, climb.grade_pct))
            if climb.length_m / METRES_PER_MILE / speed * 60 < on_minutes:
                continue
        if paved_only and _surface(climb) not in ("road", "path"):
            continue
        if quiet_only and climb.busy:
            continue
        if not any(abs(a - lon) <= dlon and abs(b - lat) <= dlat for a, b in climb.line):
            continue
        away = _away_m((lon, lat), climb.line)
        if away <= reach_m:
            found.append((away, climb))
    if steepest:
        found.sort(key=lambda pair: (-pair[1].grade_pct, pair[0]))
    else:
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
            "through": [[round(a, 6), round(b, 6)] for a, b in hillseek.via_points(climb)],
            "surface": _surface(climb),
            "busy": climb.busy if busy_known else None,
            "away_mi": round(away / METRES_PER_MILE, 1),
        }
        for away, climb in found[:MAX_CLIMBS]
    ]
