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
end to end, not alongside. Same-named ways that close into a short ring are
circles and loops, not divided roads (`small_loops`, review r1), and a partner
must be alongside at MIN_ALONGSIDE points. Memory on the region: 133 MiB for
56,352 candidates, 19 s.

A second, wider reading guards the District's two-way record (OWNER-DECISIONS
190 row C4, and 216, which makes it the routing direction): a block is the
whole road, so a two-way record must never make one carriageway two-way.
`carriageway_pairs` pairs a one-way with an opposite one-way of the same street
alongside it within C4_PAIR_M, and reads the street's name without the
District's quadrant (South Capitol Street is "Southwest" on one carriageway and
"Southeast" on the other, 12 m apart; E Street NW's carriageways are 57 to 65 m
apart and H Street NW's 52 m, past PAIR_M; combined correctness review). It is
not the stress reading: item 109's divided-road flag keeps PAIR_M and the
names as mapped.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

from .tags import ONEWAY_JUNCTIONS, is_oneway

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
# A same-named ring shorter than this round is a circle or loop, not a road.
LOOP_MAX_M = 1_000.0
# Sample points a partner must be alongside at (fewer on a way that short).
MIN_ALONGSIDE = 2


# The C4 guard's band: a carriageway pair further apart than PAIR_M, up to this
# (E Street NW at 57 to 65 m, South Capitol Street SW 910656606 and its SE
# carriageway 88 m apart at the Suitland Parkway junction). Wide on purpose: what
# the guard can get wrong is to leave a one-way OSM street one-way that the
# District records as two-way, which routes no one against traffic.
C4_PAIR_M = 100.0
# The C4 guard's road classes: the divided ones and residential boulevards.
C4_HIGHWAY = DIVIDED_HIGHWAY | {"residential"}
# The District's quadrants as OSM spells them at the end of a street's name.
QUADRANTS = (" Northwest", " Northeast", " Southwest", " Southeast", " NW", " NE", " SW", " SE")


def street_name(name: str) -> str:
    """A street's name without the District's quadrant: the one street either
    side of a quadrant line (South Capitol Street Southwest and Southeast)."""
    for quadrant in QUADRANTS:
        if name.endswith(quadrant):
            return name[: -len(quadrant)]
    return name


def _candidate(tags: dict[str, str], highways=DIVIDED_HIGHWAY) -> bool:
    """A one-way, named way of a divided class. Not a roundabout: it is one-way
    (OWNER-DECISIONS 228), and the far side of its ring, running the other way,
    is not a carriageway's other half, nor is a road's carriageway the ring's.
    Same-named rings were already left out (`small_loops`); 149 roundabout
    ways (2.6 mi [4.2 km]) of rings named for the road through them (Charles
    Town Pike, Dundalk Avenue) were flagged in the 2026-09-25 extract, so read
    two-way."""
    return (
        tags.get("highway") in highways
        and tags.get("junction") not in ONEWAY_JUNCTIONS
        and is_oneway(tags)
        and bool(tags.get("name"))
    )


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


def _length_m(coordinates) -> float:
    k = math.cos(math.radians(coordinates[0][1]))
    return sum(
        math.hypot((b[0] - a[0]) * k, b[1] - a[1]) * M_PER_DEG_LAT
        for a, b in zip(coordinates, coordinates[1:], strict=False)
    )


def _end(point) -> tuple[float, float]:
    return round(point[0], 7), round(point[1], 7)


def small_loops(ways, name_of=None) -> set[int]:
    """Same-named one-way ways that close on each other into a ring under
    LOOP_MAX_M round: a circle (Ward, Tenley, Blair Circles) or a one-way loop
    road (Americana Circle), whose two sides face each other across the ring
    without being a divided road (review r1). A short split round a traffic
    island closes the same way and is no divided arterial either."""
    name_of = name_of or (lambda tags: tags["name"])
    parent: dict[int, int] = {}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ends: dict[tuple, list[int]] = defaultdict(list)
    length: dict[int, float] = {}
    for way in ways:
        parent[way.osm_id] = way.osm_id
        length[way.osm_id] = _length_m(way.coordinates)
        for point in (way.coordinates[0], way.coordinates[-1]):
            ends[(name_of(way.tags), *_end(point))].append(way.osm_id)
    for ids in ends.values():
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])
    members: dict[int, list[int]] = defaultdict(list)
    for osm_id in parent:
        members[find(osm_id)].append(osm_id)
    closed_ends: dict[int, bool] = defaultdict(lambda: True)
    for ids in ends.values():
        # A ring uses every end exactly twice; a dangling end opens it.
        closed_ends[find(ids[0])] &= len(ids) == 2
    loops: set[int] = set()
    for root, ids in members.items():
        if closed_ends[root] and sum(length[i] for i in ids) <= LOOP_MAX_M:
            loops.update(ids)
    return loops


def carriageways(ways: Iterable) -> set[int]:
    """The ids of the ways (anything with osm_id, tags and coordinates) that
    are one carriageway of a divided road."""
    return _paired(ways, DIVIDED_HIGHWAY, lambda tags: tags["name"], PAIR_M)


def carriageway_pairs(ways: Iterable, names: Iterable[str] | None = None) -> set[int]:
    """The ways that are one of a pair of opposite one-way carriageways of one
    street, read widely for the C4 guard (the module docstring): C4_HIGHWAY,
    the name without its quadrant (`street_name`), up to C4_PAIR_M apart.
    `names`, where given, limits the search to those streets, which is what the
    guard needs and a fraction of the region's one-ways."""
    wanted = None if names is None else {street_name(name) for name in names}

    def name_of(tags):
        return street_name(tags["name"])

    if wanted is not None:
        ways = [w for w in ways if w.tags.get("name") and name_of(w.tags) in wanted]
    return _paired(ways, C4_HIGHWAY, name_of, C4_PAIR_M)


def _paired(ways: Iterable, highways, name_of, pair_m: float) -> set[int]:
    candidates = [w for w in ways if len(w.coordinates) >= 2 and _candidate(w.tags, highways)]
    loops = small_loops(candidates, name_of)
    candidates = [w for w in candidates if w.osm_id not in loops]
    cells: dict[tuple, list] = defaultdict(list)
    for way in candidates:
        name = name_of(way.tags)
        for lon, lat, ux, uy in _steps(way.coordinates, way.tags.get("oneway") == "-1"):
            key = (name, int(lon // CELL_DEG), int(lat // CELL_DEG))
            cells[key].append((way.osm_id, lon, lat, ux, uy))
    found: set[int] = set()
    for way in candidates:
        steps = _steps(way.coordinates, way.tags.get("oneway") == "-1")
        if _has_partner(way.osm_id, name_of(way.tags), steps, cells, pair_m):
            found.add(way.osm_id)
    return found


def _has_partner(osm_id, name, steps, cells, pair_m: float = PAIR_M) -> bool:
    """Alongside an opposite same-named way at MIN_ALONGSIDE sample points, or
    at every point of a way too short to have that many."""
    steps = list(steps)
    need = min(MIN_ALONGSIDE, len(steps))
    hits = 0
    for lon, lat, ux, uy in steps:
        if _alongside(osm_id, name, lon, lat, ux, uy, cells, pair_m):
            hits += 1
            if hits >= need:
                return True
    return False


def _alongside(osm_id, name, lon, lat, ux, uy, cells, pair_m: float = PAIR_M) -> bool:
    k = math.cos(math.radians(lat))
    cx, cy = int(lon // CELL_DEG), int(lat // CELL_DEG)
    # The cells within the band each way: one for PAIR_M, more for a wider band.
    rx = max(1, math.ceil(pair_m / (CELL_DEG * M_PER_DEG_LAT * k)))
    ry = max(1, math.ceil(pair_m / (CELL_DEG * M_PER_DEG_LAT)))
    for ix in range(cx - rx, cx + rx + 1):
        for iy in range(cy - ry, cy + ry + 1):
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
                if MIN_LATERAL_M <= lateral <= pair_m and along <= STEP_M:
                    return True
    return False
