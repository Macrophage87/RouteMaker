#!/usr/bin/env python3
"""Write the places to see (points of interest) for Plan's "Places to see" tab and Go's Sights.

Owner request (2026-10-14, "Points of interest tab, and farm stands as food" in
the v0.7.0 plan): "Could a points of interest tab be planned as well. Let's
categorize by things like museums, lighthouses, gardens, farmers markets, etc."
Built from the project's own extract, like the water and food files, and read
by frontend/src/lib/places.ts.

Categories, from the OSM wiki's tag definitions
(<https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dmuseum>,
<https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dgallery>,
<https://wiki.openstreetmap.org/wiki/Key:historic>,
<https://wiki.openstreetmap.org/wiki/Key:memorial>,
<https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dlighthouse>,
<https://wiki.openstreetmap.org/wiki/Tag:leisure%3Dgarden>,
<https://wiki.openstreetmap.org/wiki/Key:garden:type>,
<https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dviewpoint>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dmarketplace>,
<https://wiki.openstreetmap.org/wiki/Tag:shop%3Dfarm>,
<https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dzoo>,
<https://wiki.openstreetmap.org/wiki/Tag:tourism%3Daquarium>,
<https://wiki.openstreetmap.org/wiki/Tag:waterway%3Dwaterfall>,
<https://wiki.openstreetmap.org/wiki/Tag:natural%3Dpeak>,
<https://wiki.openstreetmap.org/wiki/Key:bridge>,
<https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dbridge>,
<https://wiki.openstreetmap.org/wiki/Key:craft>,
<https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dwine_cellar>), each with
its code in the file:

- "museum": tourism=museum or tourism=gallery.
- "historic": historic=monument, memorial, castle, fort, ruins or
  battlefield; or historic=building with tourism=attraction. A memorial that
  is a plaque, a stolperstein, a bench or a blue plaque (memorial=*) is left
  out: there are thousands and they are not a ride's destination.
- "lighthouse": man_made=lighthouse.
- "garden": leisure=garden (not garden:type=residential, private or
  community, which are not open to visitors), and any garden:type=arboretum.
- "viewpoint": tourism=viewpoint.
- "market": amenity=marketplace and shop=farm (farmers markets and farm
  stands; also in the Food file, scripts/build_food.py).
- "zoo": tourism=zoo, tourism=aquarium, and amenity=nature_centre (in use in
  OSM for nature centres; the PC refresh checks its count on taginfo).
- "nature": waterway=waterfall, and natural=peak with a name.
- "bridge": bridge=covered on a named way, or man_made=bridge with a tourism
  or historic tag.
- "drink": craft=brewery, winery or cider where the public can taste (also
  tagged amenity=pub, bar, biergarten or restaurant, or tasting=yes, or
  tourism=attraction or wine_cellar), and shop=wine with craft=winery. A
  production site with none of those is left out: unclear access is closed.

Every place needs a name (an unnamed viewpoint or ruin is no help in a list).
Public only: an access tag other than yes, public, permissive, designated or
customers leaves it out, as do disused=yes and abandoned=yes; places inside
airports, military sites and prisons are left out by the water layer's rule
and code. A place mapped twice (a node in its building) is one: the same name
within SAME_PLACE_M, about 200 ft (60 m), keeps the element with more details,
the node on a tie. When tags fit two categories, the first in CATEGORIES wins.

Kept: name, category, opening_hours and website (or contact:website), as
the Food file keeps them. Nodes, ways and multipolygon relations are read; a
way or relation sits at its outer ring's mean. Coordinates are rounded to 5
decimals, about 3 ft (1 m).

Run from the repository root with the development venv (osmium is in
requirements-dev.txt), with the rebuild's extract:

    .venv311/bin/python scripts/build_places.py \\
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It writes frontend/src/amenity-data/places.json (frontend/src/amenity-data/README.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_water_restrooms as water  # noqa: E402  (shared box, text and secured-area rules)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "src" / "amenity-data" / "places.json"
SOURCE = "OpenStreetMap contributors, ODbL 1.0"
COVERAGE_BBOX = water.COVERAGE_BBOX

# In the order a tie is settled, with the words the build prints.
CATEGORIES = {
    "museum": "museums and galleries",
    "historic": "historic sites and monuments",
    "lighthouse": "lighthouses",
    "garden": "gardens and arboretums",
    "viewpoint": "viewpoints",
    "market": "farmers markets and farm stands",
    "zoo": "zoos, aquariums and nature centers",
    "nature": "waterfalls and peaks",
    "bridge": "covered and notable bridges",
    "drink": "breweries, wineries and cideries",
}
OPEN_ACCESS = frozenset({"yes", "public", "permissive", "designated", "customers"})
HISTORIC = frozenset({"monument", "memorial", "castle", "fort", "ruins", "battlefield"})
SMALL_MEMORIALS = frozenset({"plaque", "stolperstein", "bench", "blue_plaque"})
CLOSED_GARDENS = frozenset({"residential", "private", "community"})
CRAFTS = frozenset({"brewery", "winery", "cider"})
TASTING_AMENITY = frozenset({"pub", "bar", "biergarten", "restaurant"})
SAME_PLACE_M = 60.0  # about 200 ft
# Keys that can make a place; the extract's cheap first test.
KEYS = ("tourism", "historic", "man_made", "leisure", "amenity", "shop", "waterway", "natural",
        "bridge", "craft")  # fmt: skip


@dataclass(frozen=True)
class Place:
    osm: str
    lon: float
    lat: float
    category: str
    name: str
    hours: str | None = None
    website: str | None = None


def _historic(tags: dict[str, str]) -> bool:
    kind = tags.get("historic")
    if kind == "memorial" and tags.get("memorial") in SMALL_MEMORIALS:
        return False
    if kind in HISTORIC:
        return True
    return kind == "building" and tags.get("tourism") == "attraction"


def _garden(tags: dict[str, str]) -> bool:
    kind = tags.get("garden:type")
    if kind == "arboretum":
        return True
    return tags.get("leisure") == "garden" and kind not in CLOSED_GARDENS


def _drink(tags: dict[str, str]) -> bool:
    if tags.get("shop") == "wine" and tags.get("craft") == "winery":
        return True
    if tags.get("craft") not in CRAFTS:
        return False
    return (
        tags.get("amenity") in TASTING_AMENITY
        or tags.get("tasting") == "yes"
        or tags.get("tourism") in ("attraction", "wine_cellar")
    )


def category_of(tags: dict[str, str]) -> str | None:
    """The place's category (a CATEGORIES key), or None when it is none of them."""
    tourism = tags.get("tourism")
    if tourism in ("museum", "gallery"):
        return "museum"
    if _historic(tags):
        return "historic"
    if tags.get("man_made") == "lighthouse":
        return "lighthouse"
    if _garden(tags):
        return "garden"
    if tourism == "viewpoint":
        return "viewpoint"
    if tags.get("amenity") == "marketplace" or tags.get("shop") == "farm":
        return "market"
    if tourism in ("zoo", "aquarium") or tags.get("amenity") == "nature_centre":
        return "zoo"
    if tags.get("waterway") == "waterfall" or tags.get("natural") == "peak":
        return "nature"
    if tags.get("bridge") == "covered" or (
        tags.get("man_made") == "bridge" and ("tourism" in tags or "historic" in tags)
    ):
        return "bridge"
    if _drink(tags):
        return "drink"
    return None


def is_open_to_public(tags: dict[str, str]) -> bool:
    access = tags.get("access")
    if access is not None and access not in OPEN_ACCESS:
        return False
    return tags.get("disused") != "yes" and tags.get("abandoned") != "yes"


def classify(osm: str, tags: dict[str, str], lon: float, lat: float) -> Place | None:
    """The place to see, or None when it is not one the tab shows."""
    category = category_of(tags)
    if category is None or not is_open_to_public(tags):
        return None
    name = water._text(tags.get("name"))
    if not name:
        return None
    west, south, east, north = COVERAGE_BBOX
    if not (west <= lon <= east and south <= lat <= north):
        return None
    return Place(
        osm=osm,
        lon=round(lon, 5),
        lat=round(lat, 5),
        category=category,
        name=name,
        hours=water._text(tags.get("opening_hours")),
        website=water.website_of(tags),
    )


def _richness(p: Place) -> tuple[int, int]:
    return (bool(p.hours) + bool(p.website), p.osm.startswith("n"))


def merge_duplicates(places: list[Place]) -> list[Place]:
    """One place per name (and category) within SAME_PLACE_M; see the docstring."""
    kept: dict[tuple[str, str], list[Place]] = {}
    for p in sorted(places, key=_richness, reverse=True):
        group = kept.setdefault((p.name.casefold(), p.category), [])
        twin = next(
            (
                i
                for i, k in enumerate(group)
                if water._metres(p.lon, p.lat, k.lon, k.lat) <= SAME_PLACE_M
            ),
            None,
        )
        if twin is None:
            group.append(p)
        else:
            k = group[twin]
            group[twin] = Place(
                k.osm, k.lon, k.lat, k.category, k.name, k.hours or p.hours, k.website or p.website
            )
    return [p for group in kept.values() for p in group]


def read_extract(path: Path) -> tuple[list[Place], Counter]:
    """The places in the extract, and how many secured areas left out, by kind."""
    import osmium

    elements: list[water.Element] = []
    secured: list[water.SecuredArea] = []

    def wanted(t) -> bool:
        if not any(k in t for k in KEYS):
            return False
        return category_of(dict(t)) is not None

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if wanted(n.tags):
                elements.append(
                    water.Element(f"n{n.id}", dict(n.tags), n.location.lon, n.location.lat)
                )

        def way(self, w):
            if not wanted(w.tags):
                return
            nodes = [nd for nd in w.nodes if nd.location.valid()]
            if len(nodes) > 1 and nodes[0].ref == nodes[-1].ref:
                nodes = nodes[:-1]
            if not nodes:
                return
            lon = sum(nd.location.lon for nd in nodes) / len(nodes)
            lat = sum(nd.location.lat for nd in nodes) / len(nodes)
            elements.append(water.Element(f"w{w.id}", dict(w.tags), lon, lat))

        def area(self, a):
            t = a.tags
            try:
                if not a.from_way() and wanted(t):
                    for outer in a.outer_rings():
                        ring = [(n.lon, n.lat) for n in outer]
                        pts = ring[:-1] or ring
                        lon = sum(x for x, _ in pts) / len(pts)
                        lat = sum(y for _, y in pts) / len(pts)
                        elements.append(water.Element(f"r{a.orig_id()}", dict(t), lon, lat))
                        break
                    return
                if not ("aeroway" in t or "landuse" in t or "military" in t or "amenity" in t):
                    return
                kind = water.secured_kind(dict(t))
                if kind is None:
                    return
                for outer in a.outer_rings():
                    ring = tuple((n.lon, n.lat) for n in outer)
                    holes = tuple(
                        tuple((n.lon, n.lat) for n in inner) for inner in a.inner_rings(outer)
                    )
                    secured.append(water.SecuredArea(kind, ring, holes))
            except osmium.InvalidLocationError:
                return

    Handler().apply_file(str(path), locations=True)
    kept, left_out = water.leave_out_secured(elements, secured)
    found = [p for e in kept if (p := classify(e.osm, e.tags, e.lon, e.lat))]
    return merge_duplicates(found), left_out


def _sort_key(p: Place) -> tuple[str, int]:
    return (p.osm[0], int(p.osm[1:]))


def document(places: list[Place]) -> dict:
    """The file the front end reads: short keys, absent fields left out."""
    points = []
    for p in sorted(places, key=_sort_key):
        d: dict = {"id": p.osm, "x": p.lon, "y": p.lat, "k": p.category, "n": p.name}
        if p.hours:
            d["h"] = p.hours
        if p.website:
            d["web"] = p.website
        points.append(d)
    return {"source": SOURCE, "points": points}


def write_document(doc: dict, out: Path) -> int:
    """Write the file, one place per line; its size in bytes."""
    lines = [json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in doc["points"]]
    text = (
        '{"source":'
        + json.dumps(doc["source"])
        + ',"points":[\n'
        + ",\n".join(lines)
        + ("\n" if lines else "")
        + "]}\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    out.write_bytes(data)
    return len(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pbf", type=Path, required=True, help="<DATA_ROOT>/extracts/source.osm.pbf"
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    places, left_out = read_extract(args.pbf)
    size = write_document(document(places), args.out)
    by = Counter(p.category for p in places)
    kinds = ", ".join(f"{words} {by[k]}" for k, words in CATEGORIES.items() if by[k])
    print(f"{len(places)} places ({kinds or 'none'})")
    lo = ", ".join(f"{k} {n}" for k, n in sorted(left_out.items())) or "none"
    print(f"left out inside airports, military sites and prisons: {sum(left_out.values())} ({lo})")
    print(f"{args.out}: {size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
