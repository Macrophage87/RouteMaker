"""The major cities whose traffic signals take the cities' shorter waits
(`routemaker.junction_delay`).

The owner, 2026-11-08: "along stroads that you'd find in many of the suburbs, the light cycles
are a lot longer than what you'd find in DC", and of the longer suburban waits, "Not really
needed for DC" "or the major cities". The cities are the District, Baltimore City, the City of
Alexandria and Arlington County: a signal in any of them takes the cities' shorter waits and
is not weighted up in the ranking; a signal anywhere else is timed as a suburban one.

The District is OpenStreetMap's boundary (`core.mass_tiles.inside_dc`, border roads inside).
The other three are the US Census Bureau's 2023 cartographic boundary file of counties
(`cb_2023_us_county_500k`, GEOIDs 24510, 51510 and 51013; public domain), simplified to 0.0001
degrees (about 30 ft) and snapped to 1e-5 degrees, in `geodata/city-boundaries.geojson`
(docs/SOURCES.md). A point on a border road may fall either side; the city line runs mostly
along streams, rail lines and the river there, and a wait is a figure, not a promise.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CITY_BOUNDARIES_PATH = Path(__file__).resolve().parent / "geodata" / "city-boundaries.geojson"


@lru_cache(maxsize=1)
def _cities() -> tuple[tuple[tuple[float, float, float, float], list], ...]:
    """Each city's (box (west, south, east, north), polygons as rings of (lon, lat))."""
    data = json.loads(CITY_BOUNDARIES_PATH.read_bytes())
    out = []
    for feature in data["features"]:
        polygons = [
            [[(float(pt[0]), float(pt[1])) for pt in ring] for ring in polygon]
            for polygon in feature["geometry"]["coordinates"]
        ]
        points = [pt for polygon in polygons for ring in polygon for pt in ring]
        box = (
            min(x for x, _ in points),
            min(y for _, y in points),
            max(x for x, _ in points),
            max(y for _, y in points),
        )
        out.append((box, polygons))
    return tuple(out)


def city_names() -> tuple[str, ...]:
    """The names of the cities in the boundary file, for tests and the docs."""
    data = json.loads(CITY_BOUNDARIES_PATH.read_bytes())
    return tuple(feature["properties"]["name"] for feature in data["features"])


def in_major_city(lon: float, lat: float) -> bool:
    """Whether a point lies in the District, Baltimore City, Alexandria or Arlington."""
    from routemaker.cbd import in_polygons

    from .mass_tiles import inside_dc

    for (west, south, east, north), polygons in _cities():
        if west <= lon <= east and south <= lat <= north and in_polygons((lon, lat), polygons):
            return True
    return inside_dc(lon, lat)
