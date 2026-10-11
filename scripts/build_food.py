#!/usr/bin/env python3
"""Write the places to eat that the planner's "Find food" search reads, from the OSM extract.

Owner requests (2026-10-11, FOOD-SEARCH in the v0.5.0 plan): "Is it possible to
use photon to search for things like cuisine types? Like if I wanted to search
for a midride crab restaurant or pizza place." Then: "Mostly let's do a map
search for it. People are willing to detour for good food." The search is
frontend/src/lib/food.ts; it matches a rider's words against each place's
name and cuisine, so the file keeps both. Built from the project's own extract,
not Photon: Photon cannot search along a route and the project's index may not
keep `cuisine`.

What counts, from the OSM wiki's tag definitions
(<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Drestaurant>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dfast_food>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dcafe>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dice_cream>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dpub>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dbiergarten>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dfood_court>,
<https://wiki.openstreetmap.org/wiki/Key:cuisine>, all read 2026-10-11):

- amenity=restaurant ("r"), fast_food ("f"), cafe ("c"), ice_cream ("i"),
  pub ("p"), biergarten ("b") and food_court ("fc"). A bar is left out: the
  wiki's amenity=bar is for drinks, and a bar that serves meals is usually
  tagged pub or restaurant.
- named only: a place with no `name` (nor `brand`) is dropped; a rider cannot
  find or check an unnamed place. `brand` stands in for a missing name (a
  chain's outlet mapped with its brand alone).
- open to the public: an `access` tag other than yes, public, permissive,
  designated or customers (a staff cafeteria is access=private) leaves it out;
  disused=yes and abandoned=yes too (lifecycle keys such as
  disused:amenity=restaurant never match). Places inside airports, military
  sites and prisons are left out, by the water layer's own rule and code
  (scripts/build_water_restrooms.py, "Not where the public can walk in").
- cuisine: the `cuisine` value split on ";" (and stray commas), each part
  lower-cased, trimmed, spaces made "_" (the wiki's form, "ice_cream"), and
  duplicates dropped, in the mapped order. Up to MAX_CUISINES parts are kept.
- opening_hours and website as mapped (website also from contact:website),
  whitespace squeezed; a website must start http:// or https://, or is left out.

Nodes, ways and multipolygon relations are read. A way or relation is placed at
the mean of its outer ring's nodes (the "centroid" of a building, close enough
for a map pin). Points outside the coverage box are dropped, and coordinates
are rounded to 5 decimals, about 3 ft (1 m).

One place, not two: a place mapped twice (a node inside its building way, say)
shows once. Two places of the same name (ignoring case) within SAME_PLACE_M,
about 200 ft (60 m), are one; the one with more details (cuisine, hours,
website) is kept, and the node on a tie, as the element mapped as the place
itself. Their cuisines are merged.

The file is one place per line with short keys (frontend/src/amenity-data/README.md).
The build prints its size: the front end fetches it the first time the rider
searches, so a file over SIZE_WARN_BYTES is worth a look (tiling it, or
dropping websites, are the next steps).

Run from the repository root with the development venv (osmium is in
requirements-dev.txt), with the v0.5.0 rebuild's extract:

    .venv311/bin/python scripts/build_food.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It writes frontend/src/amenity-data/food.json.
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
OUT = REPO / "frontend" / "src" / "amenity-data" / "food.json"
SOURCE = "OpenStreetMap contributors, ODbL 1.0"
COVERAGE_BBOX = water.COVERAGE_BBOX

KINDS = {
    "restaurant": "r",
    "fast_food": "f",
    "cafe": "c",
    "ice_cream": "i",
    "pub": "p",
    "biergarten": "b",
    "food_court": "fc",
}
OPEN_ACCESS = frozenset({"yes", "public", "permissive", "designated", "customers"})
MAX_CUISINES = 6
MAX_URL = 200
SIZE_WARN_BYTES = 3_000_000
SAME_PLACE_M = 60.0  # about 200 ft


@dataclass(frozen=True)
class Place:
    osm: str  # "n123", "w456" or "r789"
    lon: float
    lat: float
    kind: str  # a KINDS value
    name: str
    cuisine: tuple[str, ...] = ()
    hours: str | None = None
    website: str | None = None


def cuisines(value: str | None) -> tuple[str, ...]:
    """OSM's semicolon list as the search reads it: lower case, "_" for spaces, no repeats."""
    out: list[str] = []
    for part in (value or "").replace(",", ";").split(";"):
        c = "_".join(part.strip().lower().split())
        if c and c not in out:
            out.append(c)
    return tuple(out[:MAX_CUISINES])


def is_open_to_public(tags: dict[str, str]) -> bool:
    access = tags.get("access")
    if access is not None and access not in OPEN_ACCESS:
        return False
    return tags.get("disused") != "yes" and tags.get("abandoned") != "yes"


def website_of(tags: dict[str, str]) -> str | None:
    url = (tags.get("website") or tags.get("contact:website") or "").strip()
    if not url.lower().startswith(("http://", "https://")) or len(url) > MAX_URL or " " in url:
        return None
    return url


def classify(osm: str, tags: dict[str, str], lon: float, lat: float) -> Place | None:
    """The place to eat, or None when it is not one the search shows."""
    kind = KINDS.get(tags.get("amenity", ""))
    if kind is None or not is_open_to_public(tags):
        return None
    name = water._text(tags.get("name")) or water._text(tags.get("brand"))
    if not name:
        return None
    west, south, east, north = COVERAGE_BBOX
    if not (west <= lon <= east and south <= lat <= north):
        return None
    return Place(
        osm=osm,
        lon=round(lon, 5),
        lat=round(lat, 5),
        kind=kind,
        name=name,
        cuisine=cuisines(tags.get("cuisine")),
        hours=water._text(tags.get("opening_hours")),
        website=website_of(tags),
    )


def read_extract(path: Path) -> tuple[list[Place], Counter]:
    """The places in the extract, and how many secured areas left out, by kind."""
    import osmium

    elements: list[water.Element] = []
    secured: list[water.SecuredArea] = []

    def wanted(t) -> bool:
        return t.get("amenity") in KINDS

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
                nodes = nodes[:-1]  # a closed way repeats its first node
            if not nodes:
                return
            lon = sum(nd.location.lon for nd in nodes) / len(nodes)
            lat = sum(nd.location.lat for nd in nodes) / len(nodes)
            elements.append(water.Element(f"w{w.id}", dict(w.tags), lon, lat))

        def area(self, a):
            t = a.tags
            try:
                if not a.from_way() and wanted(t):
                    # A multipolygon place: the mean of its first outer ring.
                    for outer in a.outer_rings():
                        ring = [(n.lon, n.lat) for n in outer]
                        pts = ring[:-1] or ring  # a ring repeats its first node
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


def _richness(p: Place) -> tuple[int, int]:
    return (bool(p.cuisine) + bool(p.hours) + bool(p.website), p.osm.startswith("n"))


def merge_duplicates(places: list[Place]) -> list[Place]:
    """One place per name within SAME_PLACE_M; see the docstring."""
    by_name: dict[str, list[Place]] = {}
    for p in sorted(places, key=_richness, reverse=True):
        by_name.setdefault(p.name.casefold(), []).append(p)
    out: list[Place] = []
    for group in by_name.values():
        kept: list[Place] = []
        for p in group:
            i = next(
                (
                    i
                    for i, k in enumerate(kept)
                    if water._metres(p.lon, p.lat, k.lon, k.lat) <= SAME_PLACE_M
                ),
                None,
            )
            if i is None:
                kept.append(p)
            else:
                k = kept[i]
                merged = tuple(dict.fromkeys(k.cuisine + p.cuisine))[:MAX_CUISINES]
                kept[i] = Place(
                    k.osm,
                    k.lon,
                    k.lat,
                    k.kind,
                    k.name,
                    merged,
                    k.hours or p.hours,
                    k.website or p.website,
                )
        out.extend(kept)
    return out


def _sort_key(p: Place) -> tuple[str, int]:
    return (p.osm[0], int(p.osm[1:]))


def document(places: list[Place]) -> dict:
    """The file the front end reads: short keys, absent fields left out."""
    points = []
    for p in sorted(places, key=_sort_key):
        d: dict = {"id": p.osm, "x": p.lon, "y": p.lat, "k": p.kind, "n": p.name}
        if p.cuisine:
            d["c"] = ";".join(p.cuisine)
        if p.hours:
            d["h"] = p.hours
        if p.website:
            d["web"] = p.website
        points.append(d)
    return {"source": SOURCE, "points": points}


def write_document(doc: dict, out: Path) -> int:
    """Write the file, one place per line (a refresh diffs place by place); its size in bytes."""
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
    by_kind = Counter(p.kind for p in places)
    names = {v: k for k, v in KINDS.items()}
    kinds = ", ".join(f"{names[k]} {by_kind[k]}" for k in KINDS.values() if by_kind[k])
    with_cuisine = sum(bool(p.cuisine) for p in places)
    print(f"{len(places)} places ({kinds or 'none'}); {with_cuisine} with a cuisine")
    lo = ", ".join(f"{k} {n}" for k, n in sorted(left_out.items())) or "none"
    print(f"left out inside airports, military sites and prisons: {sum(left_out.values())} ({lo})")
    print(f"{args.out}: {size:,} bytes")
    if size > SIZE_WARN_BYTES:
        print(
            f"warning: over {SIZE_WARN_BYTES:,} bytes; "
            "the front end fetches all of it on the first search",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
