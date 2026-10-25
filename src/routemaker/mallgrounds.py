"""Bicycles on the walks of the Washington Monument grounds and Constitution Gardens.

The owner, 2026-10-25, on the Washington Monument grounds, where only the loops
round the Monument showed as open: "I noticed that there's several parts here that
aren't listed, they are available for bicycling", and on Constitution Gardens and the
Vietnam Veterans Memorial: "Some parts here are closed, such as the memorial itself,
but not the path to it."

National Mall and Memorial Parks' compendium (36 CFR 4.30, section i,
<https://home.nps.gov/nama/learn/management/superintendent-s-compendium.htm>, read
2026-10-25) lets bicycles on "sidewalk routes adjacent to roadways, and multi-use
trails", bars them from "the steps, colonnades, or within the chambers of ... the
Washington Monument", and says "Bicyclists must walk their bicycles through the
memorials". It names no prohibition on the grounds' other walks; opening them is the
owner's call, as for the circle parks (`routemaker.circleparks`) and the Capitol
grounds (`routemaker.capitolgrounds`).

OSM maps the grounds' walks as `highway=footway` with no bicycle tag, which upstream's
transform closes by class; only the walks OSM tags `bicycle=yes` (the Monument's loops,
the Elm Walks) were open. The rebuild writes `bicycle=yes` on the working tags of each
such walk inside the grounds, and on each crossing that touches one, by the Capitol
grounds' rule (`capitolgrounds.opens`: not sidewalks, steps, natural surfaces,
passages, or a way any bicycle, vehicle or closed access key speaks for).

The memorials themselves stay closed, and so do the Tidal Basin's walks ("Bicyclists
must walk their bicycles through the memorials and along Tidal Basin walks"): a walk
whose midpoint is inside fixtures/mall_grounds/walk-only.geojson (the Monument's plaza,
the Vietnam Veterans Memorial's wall, The Three Soldiers, the Vietnam Women's Memorial,
the 56 Signers' island and a 25 m band along the Tidal Basin's shore) is not opened, so a
route reaches a memorial by its paths and the rider walks in. A walk that runs into one
(any vertex but its ends inside) stays closed too. The grounds are
fixtures/mall_grounds/grounds.geojson: the Washington Monument Grounds and Constitution
Gardens with the Vietnam Veterans Memorial's grounds, from OpenStreetMap. A way is
inside when the midpoint of its length is.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path

from . import capitolgrounds, circleparks
from .cbd import Polygon, in_polygons, load, midpoint

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mall_grounds"
GROUNDS_FILE = FIXTURES / "grounds.geojson"
WALK_ONLY_FILE = FIXTURES / "walk-only.geojson"

Areas = tuple[list[Polygon], list[Polygon]]  # the grounds, then the walk-only places in them


@lru_cache(maxsize=1)
def polygons() -> Areas:
    return load(GROUNDS_FILE), load(WALK_ONLY_FILE)


def contains(point: tuple[float, float], areas: Areas | None = None) -> bool:
    """Whether the point is on the grounds and not in a walk-only place."""
    grounds, walk_only = areas if areas is not None else polygons()
    return in_polygons(point, grounds) and not in_polygons(point, walk_only)


def opens(
    tags: dict[str, str],
    coords: Sequence[tuple[float, float]],
    areas: Areas | None = None,
) -> bool:
    """Whether this way is a walk of the grounds this rule opens to bicycles: the
    Capitol grounds' kind of walk, on these grounds, outside the walk-only places."""
    grounds, walk_only = areas if areas is not None else polygons()
    if not capitolgrounds.opens(tags, coords, grounds):
        return False
    return not enters(coords, walk_only)


def enters(coords: Sequence[tuple[float, float]], walk_only: list[Polygon]) -> bool:
    """Whether the way goes into a walk-only place: its midpoint or any vertex but its
    two ends is inside one, so a long walk whose midpoint lies outside the wall's
    polygon still stays closed, while a path that only ends at a memorial's edge opens."""
    points = [midpoint(coords), *coords[1:-1]]
    return any(in_polygons(point, walk_only) for point in points)


def open_ways(ways: Iterable, areas: Areas | None = None) -> set[int]:
    """Write `bicycle=yes` on every walk of the grounds the rule opens, and on every
    crossing that touches one, and return their ids."""
    return circleparks.open_ways(ways, areas if areas is not None else polygons(), rule=opens)
