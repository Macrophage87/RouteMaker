"""Closed sites and their gates: where a trip point inside one is routed to.

The owner, 2026-11-12, of a destination inside a secure site such as NASA Goddard, where staff
may go but the public may not: "Is it better to just route them to the gate and they can figure
it out themselves?", then "That works for me." The rebuild closes every road and path inside a
military area or a secured federal compound to bicycles (`pipeline.restricted_areas`), so the
router could not end a route on one: a route to a point deep inside stopped at whatever open
road was nearest, which may be a fence line with no way in, and the not-public end note
(`core.routing.NOT_PUBLIC_NOTE`), which speaks of the road a route ends on, never fired there.

Now a trip point inside a site (`scripts/build_restricted_sites.py`'s file, which the map shades
too) is moved to the site's nearest gate - where a road the rule closes meets a way open to
bicycles - and the answer says so (`core.routing.move_restricted_points`). Not moved: a point
within OPEN_NEAR_M of a way inside the site that stays open (the Goddard Visitor Center's way in,
a public road the outline takes in, a numbered road through a base), which the route reaches as
it is; and a point in a site with no gate found, which is routed as before.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .cbd import Polygon, _polygons, in_polygons

SITES_FILE = (
    Path(__file__).resolve().parents[2] / "frontend/src/restricted-data/restricted-sites.json"
)

# Our default, unmeasured: a point this close to an open way inside the site is near enough to
# a public way in to be routed as it is (about 330 ft).
OPEN_NEAR_M = 100.0

M_PER_DEG = 111_320.0


@dataclass(frozen=True)
class Site:
    site: str
    name: str
    polygons: tuple
    box: tuple[float, float, float, float]
    gates: tuple[tuple[float, float], ...]
    open_lines: tuple[tuple[tuple[float, float], ...], ...]


def _box(polygons) -> tuple[float, float, float, float]:
    xs = [x for p in polygons for x, _ in p[0]]
    ys = [y for p in polygons for _, y in p[0]]
    return (min(xs), min(ys), max(xs), max(ys))


def parse(data: dict) -> tuple[Site, ...]:
    """The sites of a FeatureCollection as the build step writes it."""
    shapes: dict[str, list[Polygon]] = {}
    names: dict[str, str] = {}
    gates: dict[str, list[tuple[float, float]]] = {}
    lines: dict[str, list[tuple[tuple[float, float], ...]]] = {}
    for feature in data.get("features", ()):
        props, geometry = feature.get("properties") or {}, feature.get("geometry") or {}
        if "kind" in props and geometry.get("type") in ("Polygon", "MultiPolygon"):
            shapes.setdefault(props["site"], []).extend(_polygons(geometry))
            names[props["site"]] = props.get("name", "")
        elif "gate" in props and geometry.get("type") == "Point":
            lon, lat = geometry["coordinates"][:2]
            gates.setdefault(props["gate"], []).append((float(lon), float(lat)))
        elif "open" in props and geometry.get("type") == "MultiLineString":
            for part in geometry["coordinates"]:
                lines.setdefault(props["open"], []).append(
                    tuple((float(x), float(y)) for x, y, *_ in part)
                )
    return tuple(
        Site(
            site=site,
            name=names.get(site, ""),
            polygons=tuple(polygons),
            box=_box(polygons),
            gates=tuple(gates.get(site, ())),
            open_lines=tuple(lines.get(site, ())),
        )
        for site, polygons in shapes.items()
        if polygons
    )


@lru_cache(maxsize=1)
def sites() -> tuple[Site, ...]:
    """The sites, read once; none where the file is missing or empty (the routing is then as
    before)."""
    try:
        return parse(json.loads(SITES_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return ()


def site_at(lon: float, lat: float, found: tuple[Site, ...] | None = None) -> Site | None:
    """The site a point is inside, or None."""
    for site in sites() if found is None else found:
        west, south, east, north = site.box
        if (
            west <= lon <= east
            and south <= lat <= north
            and in_polygons((lon, lat), list(site.polygons))
        ):
            return site
    return None


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * k, a[1] - b[1]) * M_PER_DEG


def _to_segment_m(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    k = math.cos(math.radians(p[1]))
    ax, ay, bx, by = (a[0] - p[0]) * k, a[1] - p[1], (b[0] - p[0]) * k, b[1] - p[1]
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / span))
    return math.hypot(ax + t * dx, ay + t * dy) * M_PER_DEG


def near_open_way(site: Site, point: tuple[float, float], within_m: float = OPEN_NEAR_M) -> bool:
    """Whether a point is within `within_m` of a way inside the site that stays open."""
    return any(
        _to_segment_m(point, a, b) <= within_m
        for line in site.open_lines
        for a, b in zip(line, line[1:], strict=False)
    )


def redirect(
    lon: float, lat: float, found: tuple[Site, ...] | None = None
) -> tuple[Site, tuple[float, float]] | None:
    """The site a trip point is inside and the gate it is moved to, or None where it is not
    moved (outside every site, near an open way inside one, or in a site with no gate)."""
    site = site_at(lon, lat, found)
    if site is None or not site.gates or near_open_way(site, (lon, lat)):
        return None
    gate = min(site.gates, key=lambda g: _metres((lon, lat), g))
    return site, gate
