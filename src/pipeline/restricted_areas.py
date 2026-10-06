"""The areas a way lies inside that change how the stress map draws it, and how
a bicycle may route through it.

Four kinds, read from the same source extract as the ways with pyosmium's
area assembly (multipolygon relations and closed ways alike):

- `military` - `landuse=military` or `military=*`. The owner, 2026-09-29:
  "Don't show roads that most typical people can't ride on, such as within
  military bases, or the pentagon" (OWNER-DECISIONS 88). Many roads inside a
  base carry no access tag of their own (the Pentagon's Connector Road and
  North Rotary Road are plain `tertiary`); the Pentagon itself is
  `landuse=military` + `military=base` (way 916068128). Its roads - not its
  trail-class ways - are left off the map. And closed to bicycles, on every
  graph (`military_closures`, `rm:no_bicycle=military`): the owner reported a
  route through Joint Base Anacostia-Bolling on 2026-10-05, down the base's
  riverside roads and walkways, which carry no access tag of their own. Under
  the standing rule "err closed on bike access" (OWNER-DECISIONS 330) every
  road and path inside a military area is closed, but for a way whose own tags
  give the public a bicycle (`bicycle` yes/designated/permissive, or `access`
  yes/permissive with no bicycle tag) and a numbered public route (`ref`
  US/I/MD/VA/SR/CR/DC n, with no access tag against it: US 1 through Fort
  Belvoir, MD 198 at Fort Meade). Those stay open, are drawn, and are listed
  in the rebuild's `military-closures.csv` for the owner to check; an access
  override reopens anything else, with evidence. The installations in
  `PUBLIC_EDGE_AREAS` (the Pentagon reservation: "There are parts of the
  pentagon reservation you can bike to", the owner, 2026-10-05) close only
  their roads; their paths and walkways keep their own tags, and every one is
  listed. The building itself (`military=office`) is closed as any base is.
- `cemetery` - `landuse=cemetery` or `amenity=grave_yard`. The owner: "There's
  a lot of cemetary roads, such as arlington national cemetary. We shouldn't
  have these roads on here, even if some of them can be technically ridden. I
  don't want to encourage a cemetary cut through as it's disrespectful." (98).
  Every road and path inside one is left off the map, and routed only to or
  from a point inside it (destination-only, through `rm:cemetery`); a trail
  signed for bicycles (`bicycle=designated`) keeps its place.
- `parking` - `amenity=parking`, or `parking=surface` or `multi-storey`. The
  owner: "Also, no need to stripe through all the parking lots." (99). The
  unnamed service roads, footways and paths inside a lot are left off the map;
  routing is unchanged, since a lot can be a fair connector.

- `park` - `leisure=park` or `nature_reserve`, `boundary=national_park` or
  `protected_area`, or an operator that is the National Park Service. An
  untagged `highway=path` inside one is closed to bicycles, and kept outside
  (OWNER-DECISIONS 291(1); `routemaker.trailaccess`). Nothing is hidden or
  re-routed for it here: only `pipeline.trail_closures` reads this kind.

A way is inside when at least INSIDE_FRACTION of its vertices fall in one of
the kind's areas, outside that area's holes. So a road or a trail that only
borders an area - the Mount Vernon Trail by Arlington National Cemetery and
the Pentagon, a street past a parking lot - is not inside it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import osmium

from routemaker.classes import TRAIL_CLASS_HIGHWAY
from routemaker.facility import NO_PUBLIC_ACCESS, _length_m

Ring = list[tuple[float, float]]
# (bbox, outer rings, inner rings)
Area = tuple[tuple[float, float, float, float], list[Ring], list[Ring]]

MILITARY, CEMETERY, PARKING, PARK = "military", "cemetery", "parking", "park"
KINDS = (MILITARY, CEMETERY, PARKING, PARK)

# The share of a way's vertices that must fall inside for it to count as inside.
INSIDE_FRACTION = 0.5

# `military` values that are no area a road may lie in.
NOT_A_MILITARY_AREA = frozenset({"no"})
PARKING_VALUES = frozenset({"surface", "multi-storey"})
PARK_LEISURE = frozenset({"park", "nature_reserve"})
PARK_BOUNDARY = frozenset({"national_park", "protected_area"})

# The grid cell the areas are indexed by, in degrees (about 1.1 km).
CELL = 0.01


def area_kind(tags) -> str | None:
    """The kind of area a closed way or a multipolygon is, or None."""
    if tags.get("landuse") == "military" or (
        tags.get("military") is not None and tags.get("military") not in NOT_A_MILITARY_AREA
    ):
        return MILITARY
    if tags.get("landuse") == "cemetery" or tags.get("amenity") == "grave_yard":
        return CEMETERY
    if tags.get("amenity") == "parking" or tags.get("parking") in PARKING_VALUES:
        return PARKING
    if (
        tags.get("leisure") in PARK_LEISURE
        or tags.get("boundary") in PARK_BOUNDARY
        or (tags.get("operator") or "").startswith("National Park Service")
    ):
        return PARK
    return None


def is_military_area(tags) -> bool:
    return area_kind(tags) == MILITARY


class _NamedArea(tuple):
    """An `Area` that also knows its OSM name and id (`w123` or `r123`), for the
    report; it unpacks as the plain three-tuple everything else reads."""

    name: str = ""
    osm: str = ""


def named_area(area: Area, name: str = "", osm: str = "") -> _NamedArea:
    named = _NamedArea(area)
    named.name, named.osm = name, osm
    return named


class _Areas(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.areas: dict[str, list[Area]] = {kind: [] for kind in KINDS}

    def area(self, a) -> None:
        kind = area_kind(a.tags)
        if kind is None:
            return
        outers: list[Ring] = []
        inners: list[Ring] = []
        for outer in a.outer_rings():
            outers.append([(n.lon, n.lat) for n in outer])
            for inner in a.inner_rings(outer):
                inners.append([(n.lon, n.lat) for n in inner])
        points = [p for ring in outers for p in ring]
        if not points:
            return
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        area = ((min(xs), min(ys), max(xs), max(ys)), outers, inners)
        osm = f"{'w' if a.from_way() else 'r'}{a.orig_id()}"
        self.areas[kind].append(named_area(area, a.tags.get("name") or "", osm))


def restricted_areas(pbf: str | Path) -> dict[str, list[Area]]:
    """Every military, cemetery, parking and park area in an extract, by kind."""
    handler = _Areas()
    handler.apply_file(str(pbf), locations=True)
    return handler.areas


def _in_ring(point: tuple[float, float], ring: Ring) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=False):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _in_area(point: tuple[float, float], area: Area) -> bool:
    (west, south, east, north), outers, inners = area
    x, y = point
    if not (west <= x <= east and south <= y <= north):
        return False
    return any(_in_ring(point, r) for r in outers) and not any(_in_ring(point, r) for r in inners)


class _Index:
    """The areas by grid cell, so a point is tested against the few near it."""

    def __init__(self, areas: Sequence[Area]) -> None:
        self.cells: dict[tuple[int, int], list[Area]] = defaultdict(list)
        for area in areas:
            west, south, east, north = area[0]
            for gx in range(int(west // CELL), int(east // CELL) + 1):
                for gy in range(int(south // CELL), int(north // CELL) + 1):
                    self.cells[(gx, gy)].append(area)

    def contains(self, point: tuple[float, float]) -> bool:
        near = self.cells.get((int(point[0] // CELL), int(point[1] // CELL)), ())
        return any(_in_area(point, area) for area in near)

    def containing(self, point: tuple[float, float]) -> list[Area]:
        near = self.cells.get((int(point[0] // CELL), int(point[1] // CELL)), ())
        return [area for area in near if _in_area(point, area)]


def _inside(coords: Sequence[tuple[float, float]], index: _Index) -> bool:
    return bool(coords) and sum(1 for p in coords if index.contains(p)) >= INSIDE_FRACTION * len(
        coords
    )


def ways_inside(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
    areas: Sequence[Area],
    counts,
) -> set[int]:
    """The ways `counts(tags)` asks about that lie inside one of `areas`."""
    if not areas:
        return set()
    index = _Index(areas)
    return {
        osm_id
        for osm_id, tags, coords in ways
        if tags.get("highway") is not None and counts(tags) and _inside(coords, index)
    }


def _road(tags) -> bool:
    return tags.get("highway") not in TRAIL_CLASS_HIGHWAY


def _not_a_signed_trail(tags) -> bool:
    return tags.get("bicycle") != "designated"


def _lot_way(tags) -> bool:
    """A lot's own ways: its unnamed service roads, footways and paths. A named
    way inside a lot's outline - the Ellipse Road, Capitol Circle Drive (a
    car-free road, OWNER-DECISIONS 67) - is a street of its own and stays."""
    if tags.get("name") or tags.get("bicycle") == "designated":
        return False
    return tags.get("highway") in ("service", "footway", "path", "pedestrian", "steps")


def roads_inside(ways, areas: Sequence[Area]) -> set[int]:
    """The roads (not trail-class ways) inside a military area."""
    return ways_inside(ways, areas, _road)


def cemetery_ways(ways, areas: Sequence[Area]) -> set[int]:
    """Every road and path inside a cemetery, a trail signed for bicycles aside."""
    return ways_inside(ways, areas, _not_a_signed_trail)


def parking_ways(ways, areas: Sequence[Area]) -> set[int]:
    """A parking lot's own ways inside it."""
    return ways_inside(ways, areas, _lot_way)


# --- Military areas closed to bicycles (owner report 2026-10-05; OWNER-DECISIONS 330) --

# The `rm:no_bicycle` reason of a way inside a military area.
MILITARY_NO_BICYCLE = "military"
# A way's own tags that give the public a bicycle there.
PUBLIC_BICYCLE = frozenset({"yes", "designated", "permissive"})
PUBLIC_ACCESS = frozenset({"yes", "permissive"})
# A numbered public road: Interstate, US, Maryland, Virginia (primary, and the
# State Route secondary system), county, District. Not a base's own numbers
# (Quantico's `MCB 1`).
PUBLIC_REF = re.compile(r"^(I|US|MD|VA|SR|CR|DC)[ -]?\d", re.IGNORECASE)
# Access keys any of which, at a closing value, keeps a numbered road closed.
ACCESS_KEYS = ("access", "vehicle", "bicycle", "motor_vehicle")
# Installations OSM shows public ways in (the area's OSM id, `w` way or `r`
# relation): only their roads are closed. The owner, 2026-10-05: "There are
# parts of the pentagon reservation you can bike to" - the Pentagon Memorial,
# the transit centre's bike parking, the links to the Mount Vernon Trail and
# the Route 110 trail. Its paths keep the tags OSM gives them, and every way in
# it is listed for the owner (REBUILD-BUNDLE-fix2).
PUBLIC_EDGE_AREAS = {"w916068128": "The Pentagon reservation"}

CLOSED, OPEN = "closed", "open"
WHY_PERMITTED = "open: the way's own tags give the public a bicycle"
WHY_PUBLIC_ROUTE = "open: a numbered public road; owner to confirm"
WHY_EDGE_PATH = "open: a path in an installation with public parts, as OSM tags it"
WHY_CLOSED = "closed: inside a military area"
WHY_NAMED_ROAD = "closed: a named road with no access tag; owner to check whether it is public"


@dataclass(frozen=True)
class MilitaryWay:
    """A way inside a military area, and what the rule did with it."""

    way_id: int
    installation: str
    highway: str
    name: str
    length_m: float
    status: str
    why: str
    tags: str = ""

    @property
    def closed(self) -> bool:
        return self.status == CLOSED


def public_permission(tags) -> bool:
    """The way's own tags give the public a bicycle."""
    if tags.get("bicycle") in PUBLIC_BICYCLE:
        return True
    return tags.get("access") in PUBLIC_ACCESS and tags.get("bicycle") is None


def public_route(tags) -> bool:
    """A numbered public road with no access tag that keeps anyone out."""
    refs = [part.strip() for part in (tags.get("ref") or "").split(";")]
    if not any(PUBLIC_REF.match(ref) for ref in refs):
        return False
    return not any(tags.get(key) in NO_PUBLIC_ACCESS for key in ACCESS_KEYS)


def _shown_tags(tags) -> str:
    keys = ("access", "bicycle", "foot", "motor_vehicle", "ref", "service", "footway")
    return " ".join(f"{k}={tags[k]}" for k in keys if tags.get(k) is not None)


def _installation(coords, index: _Index) -> str:
    names = Counter(
        getattr(area, "name", "") or getattr(area, "osm", "") or "unnamed military area"
        for p in coords
        for area in index.containing(p)
    )
    return names.most_common(1)[0][0] if names else ""


def military_closures(ways, areas: Sequence[Area]) -> list[MilitaryWay]:
    """Every highway way inside a military area, closed or (with the reason) left
    open. `ways` are `(osm_id, tags, coordinates)`. A way inside an ordinary area
    and a public-edge one (the Pentagon building inside its reservation) is judged
    by the ordinary rule."""
    if not areas:
        return []
    edge = [a for a in areas if getattr(a, "osm", "") in PUBLIC_EDGE_AREAS]
    ordinary = [a for a in areas if getattr(a, "osm", "") not in PUBLIC_EDGE_AREAS]
    strict = _Index(ordinary) if ordinary else None
    lenient = _Index(edge) if edge else None
    out: list[MilitaryWay] = []
    for osm_id, tags, coords in ways:
        highway = tags.get("highway")
        if highway is None or not coords:
            continue
        if strict is not None and _inside(coords, strict):
            index, kept_by_edge = strict, False
        elif lenient is not None and _inside(coords, lenient):
            index, kept_by_edge = lenient, highway in TRAIL_CLASS_HIGHWAY
        else:
            continue
        if public_permission(tags):
            status, why = OPEN, WHY_PERMITTED
        elif public_route(tags):
            status, why = OPEN, WHY_PUBLIC_ROUTE
        elif kept_by_edge:
            status, why = OPEN, WHY_EDGE_PATH
        else:
            status, why = CLOSED, WHY_CLOSED
            if (
                highway not in TRAIL_CLASS_HIGHWAY
                and highway not in ("service", "track")
                and tags.get("name")
                and not any(tags.get(key) in NO_PUBLIC_ACCESS for key in ACCESS_KEYS)
            ):
                why = WHY_NAMED_ROAD
        out.append(
            MilitaryWay(
                osm_id,
                _installation(coords, index),
                highway,
                tags.get("name") or "",
                round(_length_m(coords), 1),
                status,
                why,
                _shown_tags(tags),
            )
        )
    return out


def _cell(text: str) -> str:
    return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\n') else text


def military_report_csv(found: Sequence[MilitaryWay]) -> str:
    """`<DATA_ROOT>/rebuild/reports/military-closures.csv`: every way the rule
    looked at, so the owner can see what is closed and what was left open."""
    lines = ["way_id,installation,highway,name,length_m,status,why,tags"]
    for m in sorted(found, key=lambda m: (m.installation, m.status, m.way_id)):
        fields = [str(m.way_id), m.installation, m.highway, m.name, f"{m.length_m:.1f}"]
        lines.append(",".join(_cell(f) for f in [*fields, m.status, m.why, m.tags]))
    return "\n".join(lines) + "\n"


def military_summary(found: Sequence[MilitaryWay]) -> str:
    """One log line: closed and left-open ways and miles, the biggest installations."""
    closed = [m for m in found if m.closed]
    opened = [m for m in found if not m.closed]
    by_site: Counter = Counter()
    for m in closed:
        by_site[m.installation] += m.length_m
    top = ", ".join(f"{site} {metres / 1609.344:.1f} mi" for site, metres in by_site.most_common(6))
    return (
        f"military areas: {len(closed)} ways closed to bicycles "
        f"({sum(m.length_m for m in closed) / 1609.344:.1f} mi), {len(opened)} left open "
        f"({sum(m.length_m for m in opened) / 1609.344:.1f} mi, listed for the owner); "
        f"most closed: {top or 'none'}"
    )
