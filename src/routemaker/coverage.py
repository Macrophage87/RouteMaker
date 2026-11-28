"""The map's areas: where routes may be planned and the map is drawn.

The map was one box (`settings.COVERAGE_BBOX`, DC to Baltimore). It can now be
several (`settings.COVERAGE_AREAS`, by name), each its own island of roads: a
box spanning DC and Southwest Florida would take in everything between them, so
each area is kept as its own box and a point is covered when it is in any of
them. The first area is the home area, `COVERAGE_BBOX`, which the District's
and Maryland's own data (transit, closures, mass rides) is for.

A route never spans two areas: its points must all be in one
(`one_area`), and no road joins them anyway.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

Box = tuple[float, float, float, float]


def _settings():
    from django.conf import settings

    return settings


HOME = "dc-baltimore"


def areas() -> dict[str, Box]:
    """{name: (west, south, east, north)}, the home area first. The home area's box is
    always `COVERAGE_BBOX`, so a setting that moves it moves it here too."""
    found: dict[str, Box] = {HOME: tuple(_settings().COVERAGE_BBOX)}
    for name, box in (getattr(_settings(), "COVERAGE_AREAS", None) or {}).items():
        if name != HOME:
            found[name] = tuple(box)
    return found


def boxes() -> list[Box]:
    return list(areas().values())


def in_box(box: Sequence[float], lon: float, lat: float) -> bool:
    west, south, east, north = box
    return west <= lon <= east and south <= lat <= north


def area_of(lon: float, lat: float) -> str | None:
    """The name of the area the point is in, or None outside them all."""
    for name, box in areas().items():
        if in_box(box, lon, lat):
            return name
    return None


def box_of(lon: float, lat: float) -> Box | None:
    """The box of the area the point is in, or None outside them all."""
    name = area_of(lon, lat)
    return None if name is None else areas()[name]


def inside(lon: float, lat: float) -> bool:
    """Whether the point is in any of the map's areas."""
    return area_of(lon, lat) is not None


def one_area(points: Iterable[Sequence[float]]) -> str | None:
    """The one area every point is in, or None when a point is outside them all
    or the points are in two areas."""
    found: str | None = None
    for p in points:
        name = area_of(p[0], p[1])
        if name is None or (found is not None and name != found):
            return None
        found = name
    return found


def box_meeting(west: float, south: float, east: float, north: float) -> Box | None:
    """The box of the area the rectangle reaches into, or None when it reaches none.
    The areas are far apart, so a tile or a map view reaches at most one."""
    for box in areas().values():
        b_west, b_south, b_east, b_north = box
        if not (east < b_west or west > b_east or north < b_south or south > b_north):
            return box
    return None


def envelope(selected: Iterable[Box] | None = None) -> Box:
    """The one rectangle around the areas: only for a tool that takes a single box
    and whose answer is then checked against `inside`."""
    chosen = list(selected) if selected is not None else boxes()
    return (
        min(b[0] for b in chosen),
        min(b[1] for b in chosen),
        max(b[2] for b in chosen),
        max(b[3] for b in chosen),
    )


def polygon_geojson(selected: Iterable[Box] | None = None) -> str:
    """The areas as one GeoJSON MultiPolygon Feature, for the tools that clip to a
    polygon (`osmium extract --polygon`, `pmtiles extract --region`)."""
    chosen = list(selected) if selected is not None else boxes()
    rings = [[[[w, s], [e, s], [e, n], [w, n], [w, s]]] for (w, s, e, n) in chosen]
    return json.dumps(
        {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "MultiPolygon", "coordinates": rings},
        }
    )
