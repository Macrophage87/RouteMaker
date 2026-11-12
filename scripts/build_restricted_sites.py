#!/usr/bin/env python3
"""Write the closed sites the map shades and labels, and their gates, from the OSM extract.

The owner, 2026-11-12, of NASA Goddard's roads drawn white with nothing saying why: "For these
large closed campuses, let's put a label on them so people don't wonder why they can't go there.
Maybe put some shading on the areas that lack public access." And of a destination inside one:
"Is it better to just route them to the gate and they can figure it out themselves?", then
"That works for me."

The sites are the ones whose roads the rebuild already closes to bicycles
(`pipeline.restricted_areas`): the military areas and the secured federal compounds, read from
the same extract by the same area assembly. The Pentagon reservation (`PUBLIC_EDGE_AREAS`), whose
listed streets, walkways and memorial are public, is left out; the building itself is a military
area of its own and stays in.

One GeoJSON FeatureCollection, `frontend/src/restricted-data/restricted-sites.json`, holds:

- a Polygon or MultiPolygon per site, `{"site": id, "kind": "military" | "secured", "name": ...}`,
  simplified to SIMPLIFY_DEG; a site under MIN_SHADE_M2 is left out (our default: a recruiting
  office or an armory's yard is no campus anyone wonders about);
- a Point per labelled site, `{"site": id, "name": ...}`: a named site of LABEL_MIN_M2 or more
  (our default), at a point inside it (shapely's representative point);
- a Point per gate, `{"gate": id}`: where a road the rule closes meets a way open to bicycles (a
  shared node), so the place a route can reach and go no further. A site with no such road
  gate takes the meeting points of its closed paths instead;
- the same for each hand-drawn closed area in `fixtures/restricted-sites/` (`DRAWN`), kind
  "closed", labelled whatever its size;
- a MultiLineString per site, `{"open": id}`: the ways inside it that stay open (a public road
  the outline takes in, the Goddard Visitor Center's way in, a numbered road through a base),
  so a point near one is not moved to a gate (`routemaker.restricted_sites`).

The front end shades and labels the sites (`lib/restrictedSites.ts`); the router moves a trip
point inside a site, away from its open ways, to its nearest gate (`core.routing`). An owner's
access override that reopens a way inside a site is not read here: such a way counts as closed,
which can only add a gate. The map's sites change when this is run again, not at a rebuild.

    python3 scripts/build_restricted_sites.py --pbf <DATA_ROOT>/extracts/source.osm.pbf

Needs pyosmium and shapely (the project's virtualenv has both). ODbL 1.0: a produced work of the
extract, credited by the map's "© OpenStreetMap contributors (ODbL)".
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from pipeline import restricted_areas as ra  # noqa: E402

OUT = REPO / "frontend" / "src" / "restricted-data" / "restricted-sites.json"
# Closed areas OSM has no outline for, drawn by hand with their source (the owner, 2026-11-12, of
# Patuxent Research Refuge's closed area: "make sure the closed part is represented by the
# shaded area"): each file a FeatureCollection of Polygon or MultiPolygon features with `site`
# (a stable id), `name` and `source` (the page that says it is closed). Shaded and always
# labelled; no gates, so a trip point inside one is routed as before.
DRAWN = REPO / "fixtures" / "restricted-sites"

# Our defaults, unmeasured: shade a site of half a hectare or more; label a named one of a
# quarter of a square kilometre or more (Goddard's main campus is about 4 km2, the Rowley
# Training Center about 2).
MIN_SHADE_M2 = 5_000.0
LABEL_MIN_M2 = 250_000.0
# About 5 m (our default): the shading is a wash over the site, not its fence line.
SIMPLIFY_DEG = 0.00005
# Coordinates to 6 places (about 0.1 m), as the other map files.
PLACES = 6

M_PER_DEG = 111_320.0

# Military-tagged places the public goes to, left out of the shading and the gates (a trip there
# is routed as before): event venues whose doors are public, by OSM id. Found in the first full
# build's review, 2026-11-12.
PUBLIC_VENUES = {
    "w298594982": "D.C. Armory (event venue)",
    "w41965158": "the D.C. Armory's grounds",
    "w108841375": "Fifth Regiment Armory, Baltimore (event venue)",
    "w83502307": "Fifth Regiment Armory's building",
}
# Our default, unmeasured: a site with this share of its area inside a bigger site is the same
# place mapped twice (an old base name inside a joint base, an airfield inside its air station)
# and is left out, so the bigger one is shaded, labelled and gated once.
NESTED_SHARE = 0.9


def ring_m2(ring: Sequence[tuple[float, float]]) -> float:
    """A ring's area in square metres, by the shoelace on an equirectangular projection at the
    ring's latitude: close enough to rank sites by size."""
    if len(ring) < 3:
        return 0.0
    lat = sum(p[1] for p in ring) / len(ring)
    kx = M_PER_DEG * math.cos(math.radians(lat))
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        total += (x1 * kx) * (y2 * M_PER_DEG) - (x2 * kx) * (y1 * M_PER_DEG)
    return abs(total) / 2


def area_m2(area) -> float:
    _bbox, outers, inners = area
    return max(sum(ring_m2(r) for r in outers) - sum(ring_m2(r) for r in inners), 0.0)


def site_id(area) -> str:
    return getattr(area, "osm", "") or ""


def sites_of(areas: dict) -> list[tuple[str, object]]:
    """The (kind, area) pairs the map shades: military areas but the Pentagon reservation, and
    secured compounds; each OSM id once, the military kind first (a way inside both is the
    military rule's)."""
    out: list[tuple[str, object]] = []
    seen: set[str] = set()
    for kind in (ra.MILITARY, ra.SECURED):
        for area in areas.get(kind, ()):
            osm = site_id(area)
            if not osm or osm in seen or osm in ra.PUBLIC_EDGE_AREAS or osm in PUBLIC_VENUES:
                continue
            if area_m2(area) < MIN_SHADE_M2:
                continue
            seen.add(osm)
            out.append((kind, area))
    return drop_nested(out)


def _shape(area):
    from shapely.geometry import MultiPolygon, Polygon

    _bbox, outers, inners = area
    shape = MultiPolygon([Polygon(o) for o in outers if len(o) >= 4]).buffer(0)
    for inner in inners:
        if len(inner) >= 4:
            shape = shape.difference(Polygon(inner).buffer(0))
    return shape


def drop_nested(sites: list[tuple[str, object]]) -> list[tuple[str, object]]:
    """The sites but those mostly inside a bigger one (NESTED_SHARE)."""
    shapes = [_shape(area) for _kind, area in sites]
    sizes = [area_m2(area) for _kind, area in sites]
    keep = []
    for i, site in enumerate(sites):
        inner = shapes[i]
        nested = inner.area > 0 and any(
            sizes[j] > sizes[i] and shapes[j].intersection(inner).area >= NESTED_SHARE * inner.area
            for j in range(len(sites))
            if j != i
        )
        if not nested:
            keep.append(site)
    return keep


def _key(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] * 1e7), round(point[1] * 1e7))


def _site_of(point: tuple[float, float], sites: Sequence[tuple[str, object]]) -> str | None:
    """The shaded site a point is inside, or None: the smallest that holds it, so a parcel
    mapped inside a bigger site is its own."""
    holding = [area for _kind, area in sites if ra._in_area(point, area)]
    return site_id(min(holding, key=area_m2)) if holding else None


def _middle(coords: Sequence[tuple[float, float]]) -> tuple[float, float]:
    return coords[len(coords) // 2]


# The other rules' areas, whose ways are no way in for the public even where their own tags say
# nothing: a cemetery's drives (destination-only, and no cut-through: OWNER-DECISIONS 98), a
# parking lot's aisles, a golf course's cart paths, a works site's roads.
NOT_A_WAY_IN = (ra.CEMETERY, ra.PARKING, ra.GOLF, ra.WORKS)
# Only these open a way to a bicycle where the way is a path (`highway` of the trail classes):
# an untagged footway is unclear, and unclear is closed.
PATH_OPEN = frozenset({"yes", "designated", "permissive"})


def way_in(tags) -> bool:
    """Whether an open way is one a rider can reach a gate by: a road its tags leave open, or a
    path signed open to bicycles."""
    if "highway" not in tags or not ra.open_to_bicycles(tags):
        return False
    return ra._road(tags) or tags.get("bicycle") in PATH_OPEN or tags.get("highway") == "cycleway"


def gates_and_open_ways(
    ways: Sequence, areas: dict, sites: Sequence[tuple[str, object]]
) -> tuple[dict[str, list[tuple[float, float]]], dict[str, list[list[tuple[float, float]]]]]:
    """Each site's gates and the open ways inside it. `ways` are `(osm_id, tags, coordinates)`,
    as the rebuild reads them; the closing is the rebuild's own (`military_closures`,
    `secured_closures`)."""
    military = ra.military_closures(ways, areas.get(ra.MILITARY, []))
    secured = ra.secured_closures(
        ways, areas.get(ra.SECURED, []), skip={m.way_id for m in military}
    )
    closed = {m.way_id for m in (*military, *secured) if m.closed}
    open_inside = {m.way_id for m in (*military, *secured) if not m.closed}
    elsewhere: set[int] = set()
    for kind in NOT_A_WAY_IN:
        elsewhere |= ra.ways_inside(ways, areas.get(kind, []), lambda _tags: True)
    by_id = {osm_id: (tags, coords) for osm_id, tags, coords in ways}
    open_vertices: set[tuple[int, int]] = set()
    for osm_id, tags, coords in ways:
        if osm_id in closed or osm_id in elsewhere or not way_in(tags):
            continue
        open_vertices.update(_key(p) for p in coords)
    road_gates: dict[str, dict[tuple[int, int], tuple[float, float]]] = {}
    path_gates: dict[str, dict[tuple[int, int], tuple[float, float]]] = {}
    for osm_id in sorted(closed):
        tags, coords = by_id[osm_id]
        # The site the closed way belongs to, by its middle: a way of a site left unshaded (too
        # small, the Pentagon reservation) gives no gate to a neighbour.
        site = _site_of(_middle(coords), sites)
        if site is None:
            continue
        target = road_gates if ra._road(tags) else path_gates
        for p in coords:
            k = _key(p)
            if k in open_vertices:
                target.setdefault(site, {})[k] = (p[0], p[1])
    gates: dict[str, list[tuple[float, float]]] = {}
    for _kind, area in sites:
        osm = site_id(area)
        found = road_gates.get(osm) or path_gates.get(osm) or {}
        if found:
            gates[osm] = [found[k] for k in sorted(found)]
    lines: dict[str, list[list[tuple[float, float]]]] = {}
    for osm_id in sorted(open_inside):
        tags, coords = by_id[osm_id]
        if len(coords) < 2:
            continue
        site = _site_of(_middle(coords), sites)
        if site is not None:
            lines.setdefault(site, []).append(list(coords))
    return gates, lines


def _round(p: Iterable[float]) -> list[float]:
    return [round(float(v), PLACES) for v in p]


def collection(areas: dict, ways: Sequence) -> dict:
    """The FeatureCollection the map and the router read (see the module's docstring)."""
    from shapely.geometry import LineString, MultiLineString, Polygon, mapping
    from shapely.ops import unary_union

    sites = sites_of(areas)
    gates, lines = gates_and_open_ways(ways, areas, sites)
    features: list[dict] = []
    for kind, area in sites:
        osm, name = site_id(area), getattr(area, "name", "") or ""
        _bbox, outers, inners = area
        polys = []
        for outer in outers:
            holes = [
                r for r in inners if Polygon(outer).contains(Polygon(r).representative_point())
            ]
            polys.append(Polygon(outer, holes).buffer(0))
        shape = unary_union(polys).simplify(SIMPLIFY_DEG, preserve_topology=True)
        if shape.is_empty:
            continue
        geometry = json.loads(json.dumps(mapping(shape)))
        geometry["coordinates"] = _round_nested(geometry["coordinates"])
        props = {"site": osm, "kind": kind}
        if name:
            props["name"] = name
        features.append({"type": "Feature", "properties": props, "geometry": geometry})
        if name and area_m2(area) >= LABEL_MIN_M2:
            spot = shape.representative_point()
            features.append(
                {
                    "type": "Feature",
                    "properties": {"site": osm, "name": name},
                    "geometry": {"type": "Point", "coordinates": _round((spot.x, spot.y))},
                }
            )
        for gate in gates.get(osm, []):
            features.append(
                {
                    "type": "Feature",
                    "properties": {"gate": osm},
                    "geometry": {"type": "Point", "coordinates": _round(gate)},
                }
            )
        if lines.get(osm):
            merged = MultiLineString([LineString(c) for c in lines[osm]]).simplify(
                SIMPLIFY_DEG, preserve_topology=False
            )
            parts = list(getattr(merged, "geoms", [merged]))
            features.append(
                {
                    "type": "Feature",
                    "properties": {"open": osm},
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": [[_round(p) for p in part.coords] for part in parts],
                    },
                }
            )
    features.extend(drawn_features(DRAWN))  # read at call time, so a test can point it elsewhere
    return {"type": "FeatureCollection", "features": features}


def drawn_features(folder: Path = DRAWN) -> list[dict]:
    """The hand-drawn closed areas (`DRAWN`): a shaded polygon and a label each."""
    from shapely.geometry import shape as to_shape

    out: list[dict] = []
    for path in sorted(folder.glob("*.geojson")) if folder.is_dir() else ():
        for feature in json.loads(path.read_text(encoding="utf-8")).get("features", ()):
            props = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            if geometry.get("type") not in ("Polygon", "MultiPolygon") or not props.get("site"):
                raise ValueError(f"{path.name}: each feature needs a polygon and a `site` id")
            site, name = str(props["site"]), str(props.get("name") or "")
            out.append(
                {
                    "type": "Feature",
                    "properties": {
                        "site": site,
                        "kind": "closed",
                        **({"name": name} if name else {}),
                    },
                    "geometry": {
                        "type": geometry["type"],
                        "coordinates": _round_nested(geometry["coordinates"]),
                    },
                }
            )
            if name:
                spot = to_shape(geometry).representative_point()
                out.append(
                    {
                        "type": "Feature",
                        "properties": {"site": site, "name": name},
                        "geometry": {"type": "Point", "coordinates": _round((spot.x, spot.y))},
                    }
                )
    return out


def _round_nested(value):
    if value and isinstance(value[0], (int, float)):
        return _round(value)
    return [_round_nested(v) for v in value]


# The read's grid (about 1 km) and its pad round each site's box (about 200 m): ours, sized so a
# gate where a road leaves the outline is read.
CELL = 0.01


def site_cells(boxes: Sequence[tuple]) -> set[tuple[int, int]]:
    """The grid cells (CELL degrees) the sites' boxes cover, padded about 200 m."""
    pad = 0.002
    cells: set[tuple[int, int]] = set()
    for w, s, e, n in boxes:
        for i in range(math.floor((w - pad) / CELL), math.floor((e + pad) / CELL) + 1):
            for j in range(math.floor((s - pad) / CELL), math.floor((n + pad) / CELL) + 1):
                cells.add((i, j))
    return cells


def near_sites(coords: Sequence[tuple[float, float]], cells: set[tuple[int, int]]) -> bool:
    """Whether any vertex falls in a site's cell (`site_cells`)."""
    return any((math.floor(x / CELL), math.floor(y / CELL)) in cells for x, y in coords)


def read_ways(pbf: str, cells: set[tuple[int, int]]) -> list:
    """The highway ways near a site (`near_sites`), as `(osm_id, tags, coordinates)`: only
    those, so the PC holds a few thousand ways, not the region's."""
    import osmium

    out: list = []

    class Handler(osmium.SimpleHandler):
        def way(self, w):
            if "highway" not in w.tags:
                return
            coords = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
            if len(coords) >= 2 and near_sites(coords, cells):
                out.append((w.id, dict(w.tags), coords))

    Handler().apply_file(pbf, locations=True)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--pbf", required=True, help="the project's OSM extract")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    areas = ra.restricted_areas(args.pbf)
    ways = read_ways(args.pbf, site_cells([area[0] for _kind, area in sites_of(areas)]))
    found = collection(areas, ways)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(found, separators=(",", ":")) + "\n", encoding="utf-8")
    kinds = [f["properties"] for f in found["features"]]
    print(
        f"{sum(1 for p in kinds if 'kind' in p)} sites, "
        f"{sum(1 for p in kinds if 'name' in p and 'kind' not in p)} labels, "
        f"{sum(1 for p in kinds if 'gate' in p)} gates -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
