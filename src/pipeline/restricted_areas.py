"""The areas a way lies inside that change how the stress map draws it, and how
a bicycle may route through it.

Five kinds, read from the same source extract as the ways with pyosmium's
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
  the standing rule "err closed on bike access" (OWNER-DECISIONS 330), narrowed
  by 437, every road and path inside a military area is closed but a way an
  owner's override reopens, a numbered public route (`ref` US/I/MD/VA/SR/CR/DC
  n, with no access tag against it: US 1 through Fort Belvoir, MD 198 at Fort
  Meade), a way signed for bicycles (`bicycle=designated`) and, in the Pentagon
  reservation (`PUBLIC_EDGE_AREAS`), its listed streets and walkways (437.5).
  A way's own `access=yes` or `bicycle=yes` no longer opens it (437.1-437.3).
  Every way is listed in the rebuild's `military-closures.csv`. The building
  itself (`military=office`) is closed as any base is.
- `secured` - a secured federal compound that is not tagged military: one the
  curated `SECURED_AREAS` list names by its OSM id (the Secret Service's James J.
  Rowley Training Center, `office=government` and nothing else), or a government
  area (`landuse=government`, `office=government` or `government=*`, not a
  building) whose own `access` keeps the public out. The owner, 2026-10-06: "a
  secure secret service compound is also showing trails". Under the same rule
  "err closed on bike access" (OWNER-DECISIONS 330) its roads and paths are closed
  exactly as a military area's (`secured_closures`, `rm:no_bicycle=secured`), with
  the same exceptions: an owner's override, a numbered public road, a way signed
  for bicycles. Listed in the rebuild's `secured-closures.csv`. A way inside both
  kinds is the military rule's. A public campus (NIH's visitor-screened Bethesda
  campus aside, see `SECURED_AREAS`) is not caught: an `access=private` alone on a
  commercial or residential area (a gated subdivision, an office park) is no
  government area.
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
the kind's areas, outside that area's holes; for the military rule, at least
INSIDE_FRACTION of its length (`_Shapes`, OWNER-DECISIONS 437). So a road or a trail that only
borders an area - the Mount Vernon Trail by Arlington National Cemetery and
the Pentagon, a street past a parking lot - is not inside it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import osmium

from routemaker.classes import TRAIL_CLASS_HIGHWAY
from routemaker.facility import NO_PUBLIC_ACCESS, _length_m

Ring = list[tuple[float, float]]
# (bbox, outer rings, inner rings)
Area = tuple[tuple[float, float, float, float], list[Ring], list[Ring]]

MILITARY, CEMETERY, PARKING, PARK = "military", "cemetery", "parking", "park"
SECURED = "secured"
KINDS = (MILITARY, SECURED, CEMETERY, PARKING, PARK)

# The share of a way's vertices that must fall inside for it to count as inside.
INSIDE_FRACTION = 0.5

# `military` values that are no area a road may lie in.
NOT_A_MILITARY_AREA = frozenset({"no"})
PARKING_VALUES = frozenset({"surface", "multi-storey"})
PARK_LEISURE = frozenset({"park", "nature_reserve"})
PARK_BOUNDARY = frozenset({"national_park", "protected_area"})

# The grid cell the areas are indexed by, in degrees (about 1.1 km).
CELL = 0.01


def area_kind(tags, osm: str = "") -> str | None:
    """The kind of area a closed way or a multipolygon is, or None. `osm` is its OSM
    id (`w123` or `r123`), for the curated secured compounds (`SECURED_AREAS`)."""
    if tags.get("landuse") == "military" or (
        tags.get("military") is not None and tags.get("military") not in NOT_A_MILITARY_AREA
    ):
        return MILITARY
    if is_secured_area(tags, osm):
        return SECURED
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


# --- Secured federal compounds (owner report 2026-10-06; OWNER-DECISIONS 330) --

# Secured federal compounds OSM does not tag military, nor with an access tag of their
# own, by the area's OSM id (the 2026-10-03 extract; reports/SECURE-AREAS.md lists what
# each closes), with the name the rebuild files them under (stable if OSM renames
# one). Each is fenced, with guarded gates and no public way through.
#
# Keep this list short (OWNER-DECISIONS 446c, the owner: "There's a lot of secure
# buildings in the area. It's the ones that people might think have open pathways
# that we should worry about."): only a campus whose internal roads and paths would
# look open and routable on the map belongs here. A secure building, or a site with
# no inviting internal network, does not (446b: the Social Security Administration's
# Woodlawn campus and the wider White Oak Federal Research Center are not listed).
SECURED_AREAS = {
    # The owner, 2026-10-06: "a secure secret service compound is also showing
    # trails". The Secret Service's training centre off Powder Mill Rd, Beltsville/
    # Laurel: `office=government` and a name, nothing else (its fence is way
    # 140266648, mapped separately).
    "w437408534": "James J. Rowley Training Center",
    # NIH's main campus, Bethesda: a perimeter fence, every visitor screened at the
    # gate. `amenity=research_institute` only. The Bethesda Trolley Trail through it
    # is `bicycle=designated` and stays open; the sidewalks along Rockville Pike,
    # Cedar Ln and Old Georgetown Rd are outside the fence.
    "w42921793": "National Institutes of Health, Bethesda",
    # NIH's animal centre near Poolesville (`barrier=fence` on the outline itself).
    "w1328156254": "National Institutes of Health Animal Center",
    # The FDA's White Oak campus, Silver Spring: fenced, guarded gates;
    # `landuse=commercial` only. Not the wider Federal Research Center outline
    # (r13305997) round it.
    "r13305996": "FDA White Oak Campus",
    # NIST, Gaithersburg: guarded gates, visitors registered (`landuse=industrial`).
    "w47244898": "National Institute of Standards and Technology",
    # The Naval Academy's Yard, Annapolis (`amenity=university`): a Navy
    # installation, entered at guarded gates.
    "r20613247": "United States Naval Academy",
    # The Department of Homeland Security's Nebraska Avenue Complex, DC.
    "w67282583": "Nebraska Avenue Complex",
    # The White House grounds inside the fence (`landuse=government`): North and
    # South Drive, Jackson Place's court, the Treasury Annex tunnel. Lafayette Park,
    # the Ellipse and Pennsylvania Avenue are outside it.
    "w651696687": "The White House grounds",
    # The state prison complex at Jessup (OWNER-DECISIONS 446b, the owner: "Close the
    # Jessup prison"): the Maryland Department of Public Safety & Correctional Services'
    # outline (`landuse=commercial` only), holding the Correctional Institution for
    # Women, Brockbridge, Dorsey Run, the Pre-Release Unit and the old House of
    # Correction, and House of Correction Rd and Toulson Rd inside it. Brock Bridge Rd's
    # bridge, inside the outline, stays open (`SECURED_PUBLIC_WAYS`); Jessup Rd (MD 175)
    # is outside. Not the department's other outline, w736540664, which is at Sykesville.
    "w1000668306": "Jessup correctional complex",
    # The same department's land at Sykesville (`landuse=government` and a name only),
    # off Slacks Rd beside the Central Maryland Correctional Facility: its farm, service
    # and track roads (Beef Farm Rd among them). Closed under "err closed on bike access"
    # (OWNER-DECISIONS 330) while the owner's answer is pending (447: the orchestrator's
    # pick, "Sykesville land closed"). Slacks Rd, the county road through it, stays open
    # (`SECURED_PUBLIC_WAYS`).
    "w736540664": "Sykesville correctional land",
}
# Not listed, because a military outline already holds every way inside them (the
# military rule closes them): the National Security Agency (r16132525,
# `landuse=government`, inside Fort George G Meade), the FBI Academy (w1229063221,
# inside Marine Corps Base Quantico). CIA headquarters (w186034091), the Naval
# Observatory, Mount Weather, the NRO, NGA's sites, Liberty Crossing and the DIA are
# `landuse=military` themselves.

# Public roads a secured compound's outline takes in, by OSM way id (2026-10-03
# extract): open, listed for the owner. Goddard's outline (r4237285) reaches past
# its fence over Good Luck Rd and Soil Conservation Rd, the county roads to its
# visitor centre and Greenbelt Rd (the owner keeps them open, 446). The Jessup
# complex's (w1000668306) takes in Brock Bridge Rd's bridge, the county road through
# Jessup (446b). The Sykesville land's (w736540664) takes in Slacks Rd, the Carroll
# County road through it (447, owner to confirm). A way renumbered upstream closes
# (err closed).
SECURED_PUBLIC_WAYS = {
    521217842: "Good Luck Road",
    1413238483: "Good Luck Road",
    1413238484: "Good Luck Road",
    1413238485: "Good Luck Road",
    50935645: "Soil Conservation Road",
    1415647164: "Soil Conservation Road",
    78343985: "Brock Bridge Road (its bridge, Jessup)",
    11537133: "Slacks Road (Sykesville)",
    1021005795: "Slacks Road (Sykesville)",
    1021005796: "Slacks Road (its bridge, Sykesville)",
    110346455: "Slacks Road (its bridge, Sykesville)",
}
# The public way in to the Goddard Visitor Center (OWNER-DECISIONS 446, the owner: "For
# goddard, there's a visitor center, but other than that it's closed to the public"),
# by OSM way id (2026-10-03 extract): from Greenbelt Rd (MD 193) at Goddard Dr, ICESat
# Rd and its two turn lanes up to the gate, where ICESat Rd turns `access=private`; WMAP
# Rd to the centre's driveway loop; the aisles of its two `access=customers` lots; and
# the two short footways from the south lot to the centre's plaza. Everything else in
# Goddard stays closed, the Goddard Center Bikeway (1527307168, 1527307170, 1527307171)
# among it. Open only while the way's own tags do not close it; a way renumbered
# upstream closes (err closed, 330).
SECURED_VISITOR_WAYS = {
    108840488: "Greenbelt Rd turn lane into ICESat Rd",
    108840489: "Greenbelt Rd turn lane into ICESat Rd",
    406118615: "ICESat Road",
    708340400: "ICESat Road",
    521457474: "ICESat Road, to the gate",
    165477134: "WMAP Road",
    6095432: "Visitor Center driveway",
    165478931: "Visitor Center driveway",
    6106122: "Visitor Center driveway loop",
    6095437: "Visitor Center south lot aisle",
    6100947: "Visitor Center south lot aisle",
    1168519810: "Visitor Center north lot entrance",
    1338313092: "Visitor Center north lot aisle",
    1168519811: "Visitor Center north lot aisle",
    1171520445: "footway, south lot to the Visitor Center plaza",
    1171520552: "footway, south lot to the Visitor Center plaza",
}
# The values of a government area's own `access` that keep the public out:
# `routemaker.facility.NO_PUBLIC_ACCESS` (no, private, military, restricted, permit).
SECURED_ACCESS = NO_PUBLIC_ACCESS


def government_area(tags) -> bool:
    """A government site: `landuse=government`, `office=government` or a
    `government=*` (not `no`)."""
    return (
        tags.get("landuse") == "government"
        or tags.get("office") == "government"
        or tags.get("government") not in (None, "no")
    )


def is_secured_area(tags, osm: str = "") -> bool:
    """A secured federal compound: one `SECURED_AREAS` names, or a government area
    (not a building) whose own `access` keeps the public out (Goddard Space Flight
    Center: `government=aerospace access=private`). An `access=private` alone, on a
    gated subdivision, an office park or a private lot, is no government area and
    is not caught."""
    if osm and osm in SECURED_AREAS:
        return True
    if tags.get("building") is not None:
        return False
    return government_area(tags) and tags.get("access") in SECURED_ACCESS


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
        osm = f"{'w' if a.from_way() else 'r'}{a.orig_id()}"
        kind = area_kind(a.tags, osm)
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
        self.areas[kind].append(named_area(area, a.tags.get("name") or "", osm))


def restricted_areas(pbf: str | Path) -> dict[str, list[Area]]:
    """Every military, secured, cemetery, parking and park area in an extract, by
    kind."""
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


class _Shapes:
    """A kind's areas as shapely geometries, for the share of a way's *length*
    that lies inside them (the military rule; OWNER-DECISIONS 437: "measure
    inside a base by the share of a way's length inside the polygon ... not by
    vertices"). Counting vertices let a road that only follows a fence count as
    inside: Telegraph Rd 51806786 at Quantico has both of its vertices on the
    boundary and none of its length inside, and South Fern St 346101190 at the
    Pentagon is 13% inside. A stretch that runs along the boundary is not
    inside; holes (inner rings) are outside, as `_in_area` reads them."""

    def __init__(self, areas: Sequence[Area]) -> None:
        # Imported here: the api image imports pipeline modules but not this one's
        # military rule, and shapely is a pipeline-image package.
        import shapely
        from shapely.geometry import Polygon

        def polygonal(rings: Sequence[Ring]):
            parts = []
            for ring in rings:
                if len(ring) < 3:
                    continue
                valid = shapely.make_valid(Polygon(ring))
                parts.extend(
                    g
                    for g in shapely.get_parts(valid)
                    if g.geom_type in ("Polygon", "MultiPolygon")
                )
            return shapely.union_all(parts) if parts else None

        self._shapely = shapely
        self.areas: list[Area] = []
        geoms = []
        for area in areas:
            _, outers, inners = area
            geom = polygonal(outers)
            if geom is None or geom.is_empty:
                continue
            holes = polygonal(inners)
            if holes is not None and not holes.is_empty:
                geom = geom.difference(holes)
            shapely.prepare(geom)
            self.areas.append(area)
            geoms.append(geom)
        self.geoms = geoms
        self.tree = shapely.STRtree(geoms) if geoms else None

    def _inside_m(self, line, geom) -> float:
        if geom.contains_properly(line):
            return _length_m(list(line.coords))
        if not geom.intersects(line):
            return 0.0
        pieces = line.intersection(geom).difference(geom.boundary)
        return sum(
            _length_m(list(part.coords))
            for part in self._shapely.get_parts(pieces)
            if part.geom_type == "LineString"
        )

    def share(self, coords: Sequence[tuple[float, float]]) -> tuple[float, Area | None]:
        """(The share of the way's length inside any of the areas, the area that
        holds most of it.) A way of one point, or of no length, is inside if
        its point is."""
        shapely = self._shapely
        if self.tree is None or not coords:
            return 0.0, None
        total = _length_m(coords)
        if len(coords) < 2 or total <= 0:
            point = shapely.Point(coords[0])
            for i in self.tree.query(point):
                if self.geoms[i].contains_properly(point):
                    return 1.0, self.areas[i]
            return 0.0, None
        line = shapely.LineString(coords)
        best, best_m, inside = None, 0.0, []
        for i in self.tree.query(line):
            geom = self.geoms[i]
            metres = self._inside_m(line, geom)
            if metres <= 0:
                continue
            inside.append(geom)
            if metres > best_m:
                best, best_m = self.areas[i], metres
        if not inside:
            return 0.0, None
        if len(inside) > 1:
            # Overlapping areas (Bolling's old outline inside JBAB): the union, so
            # no stretch counts twice.
            best_m = self._inside_m(line, shapely.union_all(inside))
        return min(1.0, best_m / total), best


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


# --- Military areas closed to bicycles (owner report 2026-10-05; OWNER-DECISIONS 330,
# 437) --

# The `rm:no_bicycle` reason of a way inside a military area.
MILITARY_NO_BICYCLE = "military"
# A way's own tags that give the public a bicycle there (what the report says the
# tags meant). Inside a military area only `bicycle=designated`, a way signed for
# bicycles (the Anacostia Riverwalk past the Navy Yard, the Fairfax County Parkway
# Trail through Fort Belvoir), still keeps a way open (OWNER-DECISIONS 437.1: "only an
# explicit bicycle permission on the way itself"). `access=yes` or `permissive` alone
# no longer does (437.1, Fort Belvoir's main post and Fort Detrick: "These roads aren't
# open to the public, but could be used by people with access ... it's a better option
# to just disable this for all"), and nor does `bicycle=yes` or `permissive` (437.2,
# JBAB's sidewalks: "Same."; 437.3, APG's `access=private bicycle=yes` roads and
# Quantico's mountain-bike network: "Close.").
PUBLIC_BICYCLE = frozenset({"yes", "designated", "permissive"})
PUBLIC_ACCESS = frozenset({"yes", "permissive"})
SIGNED_FOR_BICYCLES = frozenset({"designated"})
# A numbered public road: Interstate, US, Maryland, Virginia (primary, and the
# State Route secondary system), county, District. Not a base's own numbers
# (Quantico's `MCB 1`).
PUBLIC_REF = re.compile(r"^(I|US|MD|VA|SR|CR|DC)[ -]?\d", re.IGNORECASE)
# Access keys any of which, at a closing value, keeps a numbered road closed.
ACCESS_KEYS = ("access", "vehicle", "bicycle", "motor_vehicle")
# The keys that can keep a *bicycle* off a way signed for bicycles. Not
# `motor_vehicle`: `bicycle=designated motor_vehicle=no` is an ordinary shared-use
# path (the Jeff Todd Way side path and the Fairfax County Parkway Trail at Fort
# Belvoir), the same keys `open_to_bicycles` reads outside a base.
BICYCLE_ACCESS_KEYS = ("access", "vehicle", "bicycle")
WHY_BASE_ONLY = "closed: signed for bicycles but inside the secured post (OWNER-DECISIONS 438.1)"
WHY_PENDING_REVIEW = (
    "closed: signed for bicycles inside a base; closed until the community confirms it is "
    "public (OWNER-DECISIONS 439)"
)
# Ways signed for bicycles that stay closed inside a base, by OSM way id (2026-10-03
# extract; REBUILD-BUNDLE-fix3-recheck), each with its reason; checked ahead of
# `signed_for_bicycles`. An approved override row still reopens one.
DESIGNATED_BASE_ONLY = {
    # OWNER-DECISIONS 438.1: "The bike paths that would only be open to those
    # authorized on base are the ones I want to leave out." A 21 m marked crossing
    # 547 m inside the main post that joins only Belvoir Rd (access=permissive, closed
    # by 437.1) and two footways.
    1322746319: WHY_BASE_ONLY,
    # OWNER-DECISIONS 439, on the borderline ways: "I don't ride much there, so I'll
    # wait for community input." Err closed (330) until there is evidence
    # (PLAN FOLLOWUP-BASE-COMMUNITY-REVIEW). A 2.2 km (1.38 mi) cycleway at Fort
    # Belvoir, 450 m in, that joins the Jeff Todd Way trail toward Woodlawn.
    704730666: WHY_PENDING_REVIEW,
    # The side path beside Russell Rd at MCB Quantico, 1.8 km in (0.34 mi).
    1117514150: WHY_PENDING_REVIEW,
    1117514151: WHY_PENDING_REVIEW,
    1117514152: WHY_PENDING_REVIEW,
    1117514153: WHY_PENDING_REVIEW,
    1117514154: WHY_PENDING_REVIEW,
}
# Installations OSM shows public ways in (the area's OSM id, `w` way or `r`
# relation). The owner, 2026-10-05: "There are parts of the pentagon reservation you
# can bike to"; OWNER-DECISIONS 437.5 ("Agree"): open South Fern St and S Eads St,
# keep North Rotary Rd closed, keep open only the walkways around the Pentagon
# Memorial, the transit centre and the trail links, and close the other interior
# walkways. So inside the reservation only `PENTAGON_OPEN_WAYS` (and a numbered
# road, VA 110) stay open.
PUBLIC_EDGE_AREAS = {"w916068128": "The Pentagon reservation"}
# OWNER-DECISIONS 437.5, by OSM way id (2026-10-03 extract; REBUILD-BUNDLE-fix3 lists
# them with their tags). A way renumbered upstream closes (err closed), and the
# rebuild names it (`pentagon_open_missing`).
PENTAGON_STREETS = {
    # South Fern Street. Its southern way, 346101190, is 89% outside the reservation
    # and is not judged here at all.
    44486932: "South Fern Street",
    345304597: "South Fern Street",
    346101170: "South Fern Street",
    1311964684: "South Fern Street",
    1311964685: "South Fern Street",
    # South Eads Street.
    8797265: "South Eads Street",
    345398628: "South Eads Street",
    732977786: "South Eads Street",
}
PENTAGON_WALKWAYS = {
    # Around the Pentagon Memorial: the bicycle=yes sidewalk and crossing on its west
    # side and the signed crossing to the 27 Trail. The memorial's own paths are
    # bicycle=no or pedestrian, and stay closed.
    433350216: "Pentagon Memorial, west sidewalk to the 27 Trail",
    1022785581: "Pentagon Memorial, west sidewalk",
    904635692: "Pentagon Memorial, crossing",
    1099367498: "Pentagon Memorial, 27 Trail crossing",
    # The transit centre: the walkways between the bus bays and the Metro entrance.
    438981665: "Transit centre walkway",
    438981666: "Transit centre walkway",
    1154847317: "Transit centre sidewalk",
    1154847318: "Transit centre walkway",
    1154847319: "Transit centre walkway",
    1154847320: "Transit centre walkway",
    # The trail links: the 27 Trail, the 9/11 National Memorial Trail, and the
    # bicycle=yes links between them and the Route 110 side.
    548580375: "27 Trail",
    1022785577: "9/11 National Memorial Trail",
    1022785578: "Trail link (9/11 National Memorial Trail)",
    639490277: "Trail link (27 Trail)",
    669611250: "Trail link, east sidewalk",
    1357847574: "Trail link, east sidewalk",
    1354339762: "Trail link, east sidewalk",
    1354339763: "Trail link, east crossing",
}
PENTAGON_OPEN_WAYS = {**PENTAGON_STREETS, **PENTAGON_WALKWAYS}

CLOSED, OPEN = "closed", "open"
WHY_OVERRIDE = "open: an approved access override reopens it (owner's evidence)"
WHY_SIGNED = "open: signed for bicycles (bicycle=designated)"
WHY_PUBLIC_ROUTE = "open: a numbered public road; owner to confirm"
WHY_EDGE_PATH = "open: the Pentagon's public streets and walkways (OWNER-DECISIONS 437.5)"
WHY_CLOSED = "closed: inside a military area"
WHY_TAGGED_OPEN = (
    "closed: inside a military area; its own access/bicycle tag no longer opens it "
    "(OWNER-DECISIONS 437)"
)
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
    # The share of the way's length inside the area (OWNER-DECISIONS 437).
    share: float = 1.0

    @property
    def closed(self) -> bool:
        return self.status == CLOSED


def _closing_access(tags, keys: Sequence[str] = ACCESS_KEYS) -> bool:
    return any(tags.get(key) in NO_PUBLIC_ACCESS for key in keys)


def public_permission(tags) -> bool:
    """The way's own tags give the public a bicycle. Inside a military area this
    no longer opens a way (437); it only names why a closed one is listed."""
    if tags.get("bicycle") in PUBLIC_BICYCLE:
        return True
    return tags.get("access") in PUBLIC_ACCESS and tags.get("bicycle") is None


def signed_for_bicycles(tags) -> bool:
    """`bicycle=designated`, with no `access`, `vehicle` or `bicycle` key against
    it: the one permission a way's own tags still carry inside a military area
    (OWNER-DECISIONS 437.1). `motor_vehicle=no` keeps cars off, not bicycles."""
    return tags.get("bicycle") in SIGNED_FOR_BICYCLES and not _closing_access(
        tags, BICYCLE_ACCESS_KEYS
    )


def public_route(tags) -> bool:
    """A numbered public road with no access tag that keeps anyone out. A ref that
    carries a public number beside a base's own (`SR 641;MCB 3`, two short pieces of
    Montezuma Ave at Quantico) counts: the public number is the state's road."""
    refs = [part.strip() for part in (tags.get("ref") or "").split(";")]
    if not any(PUBLIC_REF.match(ref) for ref in refs):
        return False
    return not _closing_access(tags)


BICYCLE_KEYS = ("bicycle", "bicycle:forward", "bicycle:backward")


def reopened_by_override(tags) -> bool:
    """The (override-written) tags give a bicycle a way through."""
    return any(tags.get(key) in PUBLIC_BICYCLE for key in BICYCLE_KEYS)


def _shown_tags(tags) -> str:
    keys = ("access", "bicycle", "foot", "motor_vehicle", "ref", "service", "footway")
    return " ".join(f"{k}={tags[k]}" for k in keys if tags.get(k) is not None)


def _label(area) -> str:
    return getattr(area, "name", "") or getattr(area, "osm", "") or "unnamed military area"


def military_closures(
    ways, areas: Sequence[Area], reopened: Collection[int] = frozenset()
) -> list[MilitaryWay]:
    """Every highway way inside a military area, closed or (with the reason) left
    open. `ways` are `(osm_id, tags, coordinates)`, the tags as the overrides left
    them; `reopened` are the ways an approved access override wrote a bicycle key
    on (the owner's evidence, OWNER-DECISIONS 330: reopen manually).

    A way is inside when at least INSIDE_FRACTION of its *length* is
    (OWNER-DECISIONS 437; `_Shapes`). Inside, only these stay open: an override's
    bicycle permission, a numbered public road, the Pentagon's listed streets and
    walkways (437.5), and a way signed for bicycles (`bicycle=designated`) unless
    `DESIGNATED_BASE_ONLY` lists it (438.1, 439). A way
    inside an ordinary area and the Pentagon reservation (the building) is judged
    by the ordinary rule."""
    if not areas:
        return []
    edge = [a for a in areas if getattr(a, "osm", "") in PUBLIC_EDGE_AREAS]
    ordinary = [a for a in areas if getattr(a, "osm", "") not in PUBLIC_EDGE_AREAS]
    strict = _Shapes(ordinary) if ordinary else None
    lenient = _Shapes(edge) if edge else None
    out: list[MilitaryWay] = []
    for osm_id, tags, coords in ways:
        highway = tags.get("highway")
        if highway is None or not coords:
            continue
        share, area = strict.share(coords) if strict is not None else (0.0, None)
        at_edge = False
        if share < INSIDE_FRACTION:
            share, area = lenient.share(coords) if lenient is not None else (0.0, None)
            if share < INSIDE_FRACTION:
                continue
            at_edge = True
        if osm_id in reopened and reopened_by_override(tags):
            status, why = OPEN, WHY_OVERRIDE
        elif public_route(tags):
            status, why = OPEN, WHY_PUBLIC_ROUTE
        elif at_edge and osm_id in PENTAGON_OPEN_WAYS:
            status, why = OPEN, WHY_EDGE_PATH
        elif osm_id in DESIGNATED_BASE_ONLY:
            status, why = CLOSED, DESIGNATED_BASE_ONLY[osm_id]
        elif signed_for_bicycles(tags):
            status, why = OPEN, WHY_SIGNED
        else:
            status, why = CLOSED, WHY_CLOSED
            if public_permission(tags):
                why = WHY_TAGGED_OPEN
            elif (
                highway not in TRAIL_CLASS_HIGHWAY
                and highway not in ("service", "track")
                and tags.get("name")
                and not _closing_access(tags)
            ):
                why = WHY_NAMED_ROAD
        out.append(
            MilitaryWay(
                osm_id,
                _label(area),
                highway,
                tags.get("name") or "",
                round(_length_m(coords), 1),
                status,
                why,
                _shown_tags(tags),
                round(share, 3),
            )
        )
    return out


def pentagon_open_missing(found: Sequence[MilitaryWay]) -> list[int]:
    """The listed Pentagon ways (437.5) the rule did not find open in the
    reservation: renumbered or re-drawn upstream, so closed (err closed) until the
    list is updated. Warned about, by id."""
    seen = {m.way_id for m in found if m.why == WHY_EDGE_PATH}
    return sorted(set(PENTAGON_OPEN_WAYS) - seen)


# The `rm:no_bicycle` reason of a way inside a secured federal compound.
SECURED_NO_BICYCLE = "secured"
WHY_SECURED = "closed: inside a secured federal compound"
WHY_SECURED_PUBLIC_ROAD = (
    "open: a public road the compound's outline takes in (SECURED_PUBLIC_WAYS); owner to confirm"
)
WHY_SECURED_VISITOR = (
    "open: the public way in to the Goddard Visitor Center and its parking "
    "(SECURED_VISITOR_WAYS; OWNER-DECISIONS 446)"
)
WHY_SECURED_TAGGED_OPEN = (
    "closed: inside a secured federal compound; its own access/bicycle tag does not open it "
    "(OWNER-DECISIONS 437, as on a base)"
)


def _secured_label(area) -> str:
    osm = getattr(area, "osm", "")
    return SECURED_AREAS.get(osm) or getattr(area, "name", "") or osm or "unnamed secured area"


def secured_closures(
    ways,
    areas: Sequence[Area],
    reopened: Collection[int] = frozenset(),
    skip: Collection[int] = frozenset(),
) -> list[MilitaryWay]:
    """Every highway way inside a secured federal compound (`SECURED`), closed or
    (with the reason) left open, by the military rule (owner report 2026-10-06; "err
    closed on bike access", OWNER-DECISIONS 330): inside is at least INSIDE_FRACTION
    of the way's length, and only an override's bicycle permission, a numbered
    public road, a public road the outline takes in (`SECURED_PUBLIC_WAYS`), the
    public way in to the Goddard Visitor Center (`SECURED_VISITOR_WAYS`, 446) and a
    way signed for bicycles stay open (Powder Mill Rd runs outside the Rowley fence,
    and is not inside it). `skip` are the ways the military rule already
    judged (a way inside both kinds is the base's)."""
    if not areas:
        return []
    shapes = _Shapes(areas)
    out: list[MilitaryWay] = []
    for osm_id, tags, coords in ways:
        highway = tags.get("highway")
        if highway is None or not coords or osm_id in skip:
            continue
        share, area = shapes.share(coords)
        if share < INSIDE_FRACTION:
            continue
        if osm_id in reopened and reopened_by_override(tags):
            status, why = OPEN, WHY_OVERRIDE
        elif public_route(tags):
            status, why = OPEN, WHY_PUBLIC_ROUTE
        elif osm_id in SECURED_PUBLIC_WAYS and not _closing_access(tags):
            status, why = OPEN, WHY_SECURED_PUBLIC_ROAD
        elif osm_id in SECURED_VISITOR_WAYS and not _closing_access(tags):
            status, why = OPEN, WHY_SECURED_VISITOR
        elif signed_for_bicycles(tags):
            status, why = OPEN, WHY_SIGNED
        else:
            status, why = CLOSED, WHY_SECURED
            if public_permission(tags):
                why = WHY_SECURED_TAGGED_OPEN
            elif (
                highway not in TRAIL_CLASS_HIGHWAY
                and highway not in ("service", "track")
                and tags.get("name")
                and not _closing_access(tags)
            ):
                why = WHY_NAMED_ROAD
        out.append(
            MilitaryWay(
                osm_id,
                _secured_label(area),
                highway,
                tags.get("name") or "",
                round(_length_m(coords), 1),
                status,
                why,
                _shown_tags(tags),
                round(share, 3),
            )
        )
    return out


def secured_missing(areas: Sequence[Area]) -> list[str]:
    """The curated compounds (`SECURED_AREAS`) the extract has no area for: deleted
    or renumbered upstream, so not closed until the list is updated. Warned about;
    VALIDATE_SEGMENTS's floors refuse the build."""
    seen = {getattr(area, "osm", "") for area in areas}
    return sorted(set(SECURED_AREAS) - seen)


# Ways a bicycle may ride outside a base, for `through_networks`' entry points.
CLOSED_CLASSES = frozenset({"motorway", "motorway_link", "construction", "proposed"})


def open_to_bicycles(tags) -> bool:
    """A way outside every base a bicycle may ride, by its own tags."""
    if tags.get("highway") in CLOSED_CLASSES:
        return False
    return not any(tags.get(key) in NO_PUBLIC_ACCESS for key in ("access", "bicycle", "vehicle"))


# The reasons a way inside a base may stay open and still meet the outside network
# at two or more points (`through_networks`): a numbered public road, a way signed
# for bicycles, an owner override, the Pentagon's listed ways, a secured compound's
# listed public roads and the Goddard Visitor Center's way in (446: ICESat Rd meets
# Greenbelt Rd at three points, its own end and two turn lanes).
THROUGH_EXCEPTIONS = frozenset(
    {
        WHY_PUBLIC_ROUTE,
        WHY_SIGNED,
        WHY_OVERRIDE,
        WHY_EDGE_PATH,
        WHY_SECURED_PUBLIC_ROAD,
        WHY_SECURED_VISITOR,
    }
)


def through_networks(
    found: Sequence[MilitaryWay],
    node_ids: Mapping[int, Sequence[int]],
    outside_open: Collection[int],
    exceptions: Collection[str] = THROUGH_EXCEPTIONS,
) -> list[tuple[list[int], list[int]]]:
    """The open networks inside a base a route could pass *through*: each
    connected set of open in-base ways that holds a way open for a reason other
    than `exceptions` and meets `outside_open` (bicycle-open ways outside every
    base) at two or more nodes, as `(way ids, entry nodes)`. Empty is the pass
    (OWNER-DECISIONS 437: the Fort Belvoir and Fort Detrick networks that joined the
    public streets at 21 and more points)."""
    inside = {m.way_id: m for m in found}
    open_in = {m.way_id for m in found if not m.closed}
    by_node: dict[int, list[int]] = defaultdict(list)
    for way_id, nodes in node_ids.items():
        if way_id in open_in or (way_id in outside_open and way_id not in inside):
            for node in set(nodes):
                by_node[node].append(way_id)
    parent = {w: w for w in open_in}

    def find(w: int) -> int:
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w

    for ways_here in by_node.values():
        here = [w for w in ways_here if w in open_in]
        for other in here[1:]:
            parent[find(other)] = find(here[0])
    members: dict[int, list[int]] = defaultdict(list)
    for w in open_in:
        members[find(w)].append(w)
    entries: dict[int, set[int]] = defaultdict(set)
    for node, ways_here in by_node.items():
        here = [w for w in ways_here if w in open_in]
        if here and any(w not in open_in for w in ways_here):
            entries[find(here[0])].add(node)
    out = []
    for root, ways_in in members.items():
        if len(entries[root]) < 2:
            continue
        if all(inside[w].why in exceptions for w in ways_in):
            continue
        out.append((sorted(ways_in), sorted(entries[root])))
    return sorted(out)


def _cell(text: str) -> str:
    return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\n') else text


def military_report_csv(found: Sequence[MilitaryWay], place: str = "installation") -> str:
    """`<DATA_ROOT>/rebuild/reports/military-closures.csv`: every way the rule
    looked at, so the owner can see what is closed and what was left open. The
    secured compounds' `secured-closures.csv` is the same, its `place` column
    `facility`."""
    lines = [f"way_id,{place},highway,name,length_m,status,why,tags"]
    for m in sorted(found, key=lambda m: (m.installation, m.status, m.way_id)):
        fields = [str(m.way_id), m.installation, m.highway, m.name, f"{m.length_m:.1f}"]
        lines.append(",".join(_cell(f) for f in [*fields, m.status, m.why, m.tags]))
    return "\n".join(lines) + "\n"


def military_summary(found: Sequence[MilitaryWay], what: str = "military areas") -> str:
    """One log line: closed and left-open ways and miles, the biggest installations."""
    closed = [m for m in found if m.closed]
    opened = [m for m in found if not m.closed]
    by_site: Counter = Counter()
    for m in closed:
        by_site[m.installation] += m.length_m
    top = ", ".join(f"{site} {metres / 1609.344:.1f} mi" for site, metres in by_site.most_common(6))
    return (
        f"{what}: {len(closed)} ways closed to bicycles "
        f"({sum(m.length_m for m in closed) / 1609.344:.1f} mi), {len(opened)} left open "
        f"({sum(m.length_m for m in opened) / 1609.344:.1f} mi, listed for the owner); "
        f"most closed: {top or 'none'}"
    )
