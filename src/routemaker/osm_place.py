"""A named way's line between two cross streets, from OpenStreetMap (v0.31.0).

What `scripts/park_alerts.py between` and the closure agent (`core.closure_agent`) share: each
cross street is looked up in Nominatim within the area, the pair of hits nearest each other
(at most `STREETS_APART_MAX_M` apart) is taken as the place, OpenStreetMap's own map call is
read round the two, and `park_alerts.stretch_between` draws the way from where it meets one
street to where it meets the other. The way may be a trail or a road: the drawing only follows
the ways whose name holds it. Where any step finds nothing the place is not clear, and nothing
is drawn.

No network here: `get_json(url)` is the caller's, so the tests pass saved answers.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable

from . import park_alerts as pa

NOMINATIM = "https://nominatim.openstreetmap.org/search?"
OSM_MAP = "https://api.openstreetmap.org/api/0.6/map.json?bbox="
# Two cross streets of one closure are at most this far apart (the same name elsewhere in the
# area is another street): our default.
STREETS_APART_MAX_M = 8000.0
# The map is read this far round the two streets, about 0.4 mi: our default.
MARGIN_DEG = 0.006

GetJson = Callable[[str], object]


class NotClear(ValueError):
    """The place could not be found on the map: nothing is drawn."""


def search(query: str, get_json: GetJson) -> list[tuple[float, float]]:
    params = {"q": query, "format": "json", "limit": "8"}
    found = get_json(NOMINATIM + urllib.parse.urlencode(params))
    return [(float(hit["lon"]), float(hit["lat"])) for hit in found or []]


def between(way: str, first: str, second: str, area: str, get_json: GetJson) -> list:
    """The way's line from `first` to `second` as [[lon, lat], ...]; NotClear where the place is
    not clear. A failed read raises the caller's error (OSError and the like)."""
    where = f", {area}" if area else ""
    hits = [search(street + where, get_json) for street in (first, second)]
    way_hits = search(way + where, get_json)

    def off_way(point) -> float:
        # How far the point is from the way's nearest search hit (0 where none was found).
        return min((pa._metres(point, t) for t in way_hits), default=0.0)

    # The pair of streets nearest each other and the way: the two of this one place.
    pairs = sorted(
        (pa._metres(a, b) + off_way(a) + off_way(b), pa._metres(a, b), a, b)
        for a in hits[0]
        for b in hits[1]
        if pa._metres(a, b) <= STREETS_APART_MAX_M
    )
    if not pairs:
        raise NotClear(f"{first} and {second}: not found near each other{where}")
    points = [pairs[0][2], pairs[0][3]]
    bbox = (
        min(p[0] for p in points) - MARGIN_DEG,
        min(p[1] for p in points) - MARGIN_DEG,
        max(p[0] for p in points) + MARGIN_DEG,
        max(p[1] for p in points) + MARGIN_DEG,
    )
    answer = get_json(OSM_MAP + ",".join(f"{v:.5f}" for v in bbox))
    elements = (answer.get("elements") or []) if isinstance(answer, dict) else []
    line = pa.stretch_between(elements, way, first, second)
    if line is None:
        raise NotClear(f"{way} between {first} and {second}: not clear on the map")
    return line


def length_m(line: list) -> float:
    return sum(pa._metres(a, b) for a, b in zip(line, line[1:], strict=False))


__all__ = ["NotClear", "STREETS_APART_MAX_M", "between", "length_m", "search"]
