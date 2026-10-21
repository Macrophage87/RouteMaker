"""Bicycles on the paths of the US Capitol grounds and the Senate Parks.

The owner, 2026-10-21, on a plan from Union Station to the Capitol's West Front that
found no route: "The paths on the capitol complex are legal for use and are common
routes." The Capitol Police Board's US Capitol Grounds Traffic Regulations set no
prohibition on riding a bicycle on the grounds' walks: "There shall be no prohibition
against any person riding a bicycle on a sidewalk so long as that person does not
create a hazard." (<https://www.uscp.gov/sites/evo-subsites/www.uscp.gov/files/documents/Capitol%20Police%20Board%20US%20Capitol%20Grounds%20Traffic%20Regulations%20-%20For%20Public%20Release.pdf>,
cited by the owner 2026-10-17, OWNER-DECISIONS 113: "The capitol grounds are a very
good place to ride and avoid some major roads").

OSM maps most of the grounds' walks as `highway=footway` with no bicycle tag, which
upstream's transform closes by class: the lawns' paths, the Senate Parks' and Union
Square's were closed, so a route could neither cross the grounds nor end on them, and
the few walks OSM does tag `bicycle=yes` were islands. The rebuild writes `bicycle=yes`
on the working tags of each such way, as `routemaker.circleparks` does for DC's circle
parks, and on each crossing that touches one so the walks meet the street.

The area is the Architect of the Capitol's jurisdiction from Open Data DC
(fixtures/cbd/architect-of-the-capitol.geojson, already the CBD rule's exemption): the
Capitol grounds, the Senate Parks north to Union Station's plaza and the buildings round
them. A way is inside when the midpoint of its length is.

Not opened: a way any bicycle, vehicle or closed access key speaks for (OSM's
`access=private` courtyards and corridors stay closed), steps, natural surfaces, and
roadside sidewalks (`footway=sidewalk`). The sidewalks are open already, at the
sidewalk rule's price (`routemaker.sidewalks`; the CBD's ban does not reach the grounds,
`routemaker.cbd`), so a route keeps the street beside them where the street is calm.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import lru_cache

from . import circleparks
from .cbd import AOC_FILE, Polygon, in_polygons, load, midpoint


@lru_cache(maxsize=1)
def polygons() -> list[Polygon]:
    return load(AOC_FILE)


def contains(point: tuple[float, float], areas: list[Polygon] | None = None) -> bool:
    return in_polygons(point, areas if areas is not None else polygons())


def opens(
    tags: dict[str, str],
    coords: Sequence[tuple[float, float]],
    areas: list[Polygon] | None = None,
) -> bool:
    """Whether this way is a walk of the Capitol grounds this rule opens to bicycles:
    its paths and plazas, not the sidewalks beside its streets."""
    if not coords or tags.get("highway") not in circleparks.OPENED_HIGHWAY:
        return False
    if tags.get("footway") in circleparks.LINK_FOOTWAY or tags.get("footway") in (
        "sidewalk",
        "access_aisle",
    ):
        return False
    return circleparks.unspoken(tags) and contains(midpoint(coords), areas)


def open_ways(ways: Iterable, areas: list[Polygon] | None = None) -> set[int]:
    """Write `bicycle=yes` on every walk of the grounds the rule opens, and on every
    crossing that touches one, and return their ids."""
    return circleparks.open_ways(ways, areas if areas is not None else polygons(), rule=opens)
