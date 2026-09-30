"""No sidewalk riding in the District's Central Business District.

OWNER-DECISIONS 104: bicycle riding on sidewalks is not allowed inside DC's
Central Business District, except on the federal areas inside it, and "There
shouldn't be sidewalk riding here." So a sidewalk inside the CBD and outside
those areas is barred to bicycles in every graph (`rm:no_bicycle`, written by
the rebuild; `lua/routemaker_remap.lua` turns it into `bicycle=no`).

The boundary is DDOT's own, "DDOT Central Business District" on Open Data DC
(fixtures/cbd/README.md has its source, licence and retrieval). The exempt
areas are the National Mall, the Washington Monument Grounds and President's
Park from OpenStreetMap, and the Capitol grounds, which OSM does not map as an
area, hand-drawn from the streets around them (fixtures/cbd/federal-exempt.geojson).

A sidewalk is a way mapped as one (`footway`, `path` or `cycleway` =
`sidewalk`), and only where it is not signed for bicycles: a way tagged
`bicycle=designated` is a bike path or cycle track, whatever else it says, and
roads are never touched. A way is inside when the midpoint of its length is.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "cbd"
CBD_FILE = FIXTURES / "dc-central-business-district.geojson"
EXEMPT_FILE = FIXTURES / "federal-exempt.geojson"

SIDEWALK_KEYS = ("footway", "path", "cycleway")
SIDEWALK_HIGHWAY = frozenset({"footway", "path", "cycleway"})
NO_BICYCLE = "cbd_sidewalk"

Ring = list[tuple[float, float]]
Polygon = list[Ring]  # outer ring, then holes


def _polygons(geometry: dict) -> list[Polygon]:
    if geometry["type"] == "Polygon":
        parts = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        parts = geometry["coordinates"]
    else:
        raise ValueError(f"not a polygon: {geometry['type']}")
    return [[[(float(x), float(y)) for x, y, *_ in ring] for ring in part] for part in parts]


def load(path: Path) -> list[Polygon]:
    data = json.loads(Path(path).read_text())
    return [p for feature in data["features"] for p in _polygons(feature["geometry"])]


@lru_cache(maxsize=1)
def areas() -> tuple[list[Polygon], list[Polygon]]:
    """The CBD and the exempt federal areas, read once."""
    return load(CBD_FILE), load(EXEMPT_FILE)


def _in_ring(point: tuple[float, float], ring: Ring) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def in_polygons(point: tuple[float, float], polygons: list[Polygon]) -> bool:
    return any(
        _in_ring(point, polygon[0]) and not any(_in_ring(point, hole) for hole in polygon[1:])
        for polygon in polygons
    )


def midpoint(coords: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """The point halfway along a line, by length (planar, fine at this scale)."""
    if len(coords) == 1:
        return coords[0]
    scale = math.cos(math.radians(coords[0][1]))
    steps = [
        math.hypot((b[0] - a[0]) * scale, b[1] - a[1])
        for a, b in zip(coords, coords[1:], strict=False)
    ]
    half = sum(steps) / 2
    for (a, b), step in zip(zip(coords, coords[1:], strict=False), steps, strict=True):
        if step > 0 and half <= step:
            t = half / step
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        half -= step
    return coords[-1]


def is_sidewalk(tags: dict[str, str]) -> bool:
    """A sidewalk a bicycle is not signed onto (see the module docstring)."""
    if tags.get("highway") not in SIDEWALK_HIGHWAY or tags.get("bicycle") == "designated":
        return False
    return any(tags.get(key) == "sidewalk" for key in SIDEWALK_KEYS)


def barred_sidewalk(
    tags: dict[str, str],
    coords: Sequence[tuple[float, float]],
    polygons: tuple[list[Polygon], list[Polygon]] | None = None,
) -> bool:
    """Whether this way is a CBD sidewalk bicycles may not ride."""
    if not coords or not is_sidewalk(tags):
        return False
    cbd, exempt = polygons or areas()
    point = midpoint(coords)
    return in_polygons(point, cbd) and not in_polygons(point, exempt)
