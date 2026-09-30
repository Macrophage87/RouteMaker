"""Divided roads: a one-way way that is one carriageway of a two-way road.

OSM maps a road with a median as two one-way ways, one each direction, usually
under the same name. Georgia Avenue in Montgomery County, most of Connecticut
Avenue and 16th Street NW are mapped so. OWNER-DECISIONS 109 rates a one-way
street lower than a two-way one ("1 Way is typically lower stress at similar
characteristics"), but a carriageway of a divided road is not a one-way street:
the traffic the other way is still there, across a median, and the rider meets
it at every junction. Read as one-way, the relief put 0.44 mi of Connecticut
Avenue's unposted two-lane carriageways at LTS 1 under the District's 20 mph,
and 0.31 mi more at LTS 2; read as the two-way road they are, they take the
LTS 3 floor.

A way is a carriageway here when it is one-way, of a road class that is
divided (DIVIDED_HIGHWAY), named, and another one-way way of the same name runs
the opposite direction alongside it: between MIN_LATERAL_M and PAIR_M to one
side, within a step along. A one-way couplet (two parallel one-way streets a
block apart) is further apart than that, and its two streets are almost always
named differently; a street that changes direction at a junction meets itself
end to end, not alongside.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

from .tags import is_oneway

DIVIDED_HIGHWAY = frozenset({"trunk", "primary", "secondary", "tertiary", "unclassified"})
# Median plus both carriageways' half widths: a wide median on a suburban
# arterial is 20-30 m. A District block is 100 m and more.
PAIR_M = 45.0
# Opposite direction: the cosine between the two directions of travel.
OPPOSITE_COS = -0.7
CELL_DEG = 0.001  # about 110 m north-south, 85 m east-west here
M_PER_DEG_LAT = 111_195.0
STEP_M = 20.0
MIN_LATERAL_M = 4.0


def _candidate(tags: dict[str, str]) -> bool:
    return tags.get("highway") in DIVIDED_HIGHWAY and is_oneway(tags) and bool(tags.get("name"))


def _steps(coordinates, reverse: bool):
    """(lon, lat, unit east, unit north) every STEP_M or less along the way,
    in the direction of travel. Densified, so two carriageways mapped with
    sparse vertices at different places along a straight still meet."""
    pts = list(coordinates)
    if reverse:
        pts.reverse()
    k = math.cos(math.radians(pts[0][1]))
    for a, b in zip(pts, pts[1:], strict=False):
        dx, dy = (b[0] - a[0]) * k, b[1] - a[1]
        norm = math.hypot(dx, dy)
        if norm == 0:
            continue
        n = max(1, math.ceil(norm * M_PER_DEG_LAT / STEP_M))
        for i in range(n):
            f = i / n
            yield a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, dx / norm, dy / norm


def carriageways(ways: Iterable) -> set[int]:
    """The ids of the ways (anything with osm_id, tags and coordinates) that
    are one carriageway of a divided road."""
    cells: dict[tuple, list] = defaultdict(list)
    candidates = []
    for way in ways:
        if len(way.coordinates) < 2 or not _candidate(way.tags):
            continue
        name = way.tags["name"]
        steps = list(_steps(way.coordinates, way.tags.get("oneway") == "-1"))
        candidates.append((way.osm_id, name, steps))
        for lon, lat, ux, uy in steps:
            key = (name, int(lon // CELL_DEG), int(lat // CELL_DEG))
            cells[key].append((way.osm_id, lon, lat, ux, uy))
    found: set[int] = set()
    for osm_id, name, steps in candidates:
        if _has_partner(osm_id, name, steps, cells):
            found.add(osm_id)
    return found


def _has_partner(osm_id, name, steps, cells) -> bool:
    for lon, lat, ux, uy in steps:
        k = math.cos(math.radians(lat))
        cx, cy = int(lon // CELL_DEG), int(lat // CELL_DEG)
        for ix in (cx - 1, cx, cx + 1):
            for iy in (cy - 1, cy, cy + 1):
                for other, olon, olat, ox, oy in cells.get((name, ix, iy), ()):
                    if other == osm_id or ux * ox + uy * oy > OPPOSITE_COS:
                        continue
                    ex = (olon - lon) * k * M_PER_DEG_LAT
                    ey = (olat - lat) * M_PER_DEG_LAT
                    # Alongside, not end to end: a street that is one-way north
                    # for a block and one-way south for the next meets itself
                    # head on at the junction, with no lateral offset.
                    lateral = abs(ex * uy - ey * ux)
                    along = abs(ex * ux + ey * uy)
                    if MIN_LATERAL_M <= lateral <= PAIR_M and along <= STEP_M:
                        return True
    return False
