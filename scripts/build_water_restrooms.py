#!/usr/bin/env python3
"""Write the public water sources and restrooms the map shows, from the OSM extract.

Owner requests (2026-10-09): "OSM sometimes has public water fountains and
restrooms. That should be a layer, especially on trailmaxxing and gravel."
Then: "make sure there's a distinction for those who care about regular flush
restrooms; and port-a-potties and similar facilities. Also remote areas
sometimes contain nonpotable water sources. Mark them too but with a different
icon than potable water. People would carry filters." The layer is the map's
Water and restrooms switch (frontend/src/lib/waterRestrooms.ts).

What counts, from the OSM wiki's own tag definitions
(<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Ddrinking_water>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dwater_point>,
<https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dwater_tap>,
<https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dwater_well>,
<https://wiki.openstreetmap.org/wiki/Tag:natural%3Dspring>,
<https://wiki.openstreetmap.org/wiki/Key:drinking_water>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dtoilets>,
<https://wiki.openstreetmap.org/wiki/Key:toilets:disposal>,
<https://wiki.openstreetmap.org/wiki/Key:access>):

- drinking water ("p"): amenity=drinking_water and amenity=water_point, unless
  drinking_water=no; and drinking_water=yes on a tap, well, spring, fountain,
  shelter or restroom.
- untreated water ("n", filter or treat it first): a tap, well or spring that
  is not marked drinking_water=yes, so drinking_water=no and no tag at all
  alike, as the project treats unclear as closed. An amenity=drinking_water or
  amenity=water_point marked drinking_water=no is untreated too (both tags
  mean drinkable water on their own, so only an explicit "no" makes them
  untreated). Decorative fountains are left out unless marked drinkable.
- restrooms: amenity=toilets, by toilets:disposal: flush ("f"); a portable,
  pit, composting or other basic toilet ("b": chemical, pitlatrine, bucket,
  dry_toilet, incineration, composting, or portable=yes); or not mapped ("u").
- public only: no access tag, or access=yes, public, permissive or designated.
  Anything else (private, customers, permit, no, ...) is left out, as an unclear
  "maybe you can use it" is no help to a rider; this follows the project's
  rule that unclear access is closed.
- in use only: disused=yes and abandoned=yes are left out (lifecycle-prefixed
  keys such as disused:amenity never match in the first place).
- historic springs are left out: a natural=spring with historic=* (any value
  but "no", <https://wiki.openstreetmap.org/wiki/Key:historic>) or ruins=yes
  is a landmark, not a source, unless it is also marked drinking_water=yes,
  amenity=drinking_water or amenity=water_point (owner request, 2026-10-10:
  drop historic springs).

Nodes and ways are read (a restroom building is often a way); a way is placed
at the mean of its nodes. Points outside the coverage box are dropped, and
coordinates are rounded to 5 decimals, about 3 ft (1 m).

One restroom, not two (owner request, 2026-10-10): an amenity=toilets node
that lies inside a closed way tagged amenity=toilets or building=toilets is
merged into that way, so the map and the lists show one place. The merged
place keeps the way's id and position (the building is the place; the node is
the same restroom mapped again inside it) and the tags of both: for each key
the richer element's value wins, richer meaning more of the details the layer
shows (DETAIL_KEYS), the node on a tie as it is the element mapped as the
restroom itself; tags only one of them has are kept. Several nodes in one
building merge into it the same way. A building that is not public or not in
use (access, disused, abandoned) is left out with every node inside it, as
unclear access is closed; a node inside a public building that is not public
(a staff toilet, say) is left out on its own, and the building still shows.
A building=toilets way with no amenity=toilets and no public node inside stays
out, as before (it says nothing about public use). Areas mapped as relations
(multipolygons) are not read; restroom buildings are plain ways.

Not where the public can walk in (owner request, 2026-10-11: "leave out
restrooms inside places the public can't easily walk into"): a point inside an
area tagged aeroway=aerodrome or aeroway=terminal (airside), landuse=military
or military=* (a base; every value but "no" and "danger_area", as a danger
area is often open water or public land beside a range), or amenity=prison is
left out, water as well as restrooms. Areas are read as closed ways and as
multipolygon relations, holes respected
(<https://wiki.openstreetmap.org/wiki/Tag:aeroway%3Daerodrome>,
<https://wiki.openstreetmap.org/wiki/Tag:aeroway%3Dterminal>,
<https://wiki.openstreetmap.org/wiki/Key:military>,
<https://wiki.openstreetmap.org/wiki/Tag:landuse%3Dmilitary>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dprison>). The build prints
how many it left out, by kind.

Throne smart restrooms (owner request, 2026-10-11: "missing some restrooms
that were established by Throne Labs, which are often along major biking
routes"; "They are in Maryland and Virginia too"): OSM has few of them, so a
small hand list with a source for each unit,
frontend/src/amenity-data/throne-restrooms.json, is merged in. Only units with
status "open" are added ("unverified" and "opens soon" wait in the list). A
unit within 50 ft (15 m) of an OSM restroom, or within 500 ft (150 m) of an
OSM restroom already tagged as a Throne (operator, brand or name), is that
restroom: the OSM point stays, marked as a Throne. Otherwise the unit is added
as a flush restroom, free and wheelchair accessible, as Throne describes every
unit (<https://thronelabs.co/how-it-works>, read 2026-10-11), with the id
"throne-...". Every Throne point carries op "Throne", which the map turns into
how to open the door.

Run from the repository root with the development venv (osmium is in
requirements-dev.txt):

    .venv311/bin/python scripts/build_water_restrooms.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It reads the extract and the Throne list and writes
frontend/src/amenity-data/water-restrooms.json (frontend/src/amenity-data/README.md).

To refresh only the Throne units in the committed file, without an extract
(after the list changes; the OSM points are kept as they are):

    .venv311/bin/python scripts/build_water_restrooms.py --throne-only
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "src" / "amenity-data" / "water-restrooms.json"
THRONE_LIST = REPO / "frontend" / "src" / "amenity-data" / "throne-restrooms.json"
SOURCE = "OpenStreetMap contributors, ODbL 1.0"
SOURCE_THRONE = "Throne units: throne-restrooms.json, a hand list with a source for each"

# src/config/settings.py COVERAGE_BBOX (west, south, east, north); a test holds
# the two equal.
COVERAGE_BBOX = (-78.0, 38.2, -76.02, 39.72)

PUBLIC_ACCESS = frozenset({"yes", "public", "permissive", "designated"})
# Sources riders fill from; drinkable only when marked so.
SOURCES_MAN_MADE = frozenset({"water_tap", "water_well"})
SOURCES_NATURAL = frozenset({"spring"})
# Where drinking_water=yes means a rider can fill a bottle there.
DRINKABLE_HOSTS_AMENITY = frozenset({"fountain", "shelter", "toilets"})
BASIC_DISPOSAL = frozenset(
    {"chemical", "pitlatrine", "bucket", "dry_toilet", "incineration", "composting"}
)
# The details the layer shows or reads, counted to pick the richer element when
# a restroom node and its building are merged.
DETAIL_KEYS = frozenset(
    {
        "name",
        "access",
        "fee",
        "wheelchair",
        "opening_hours",
        "seasonal",
        "toilets:disposal",
        "portable",
        "drinking_water",
        "bottle",
    }
)
YES_NO = frozenset({"yes", "no"})
WHEELCHAIR = frozenset({"yes", "limited", "no"})
MAX_TEXT = 80

# Where the public cannot walk in; see the docstring.
SECURED_AEROWAY = frozenset({"aerodrome", "terminal"})
MILITARY_OPEN = frozenset({"no", "danger_area"})
# A Throne unit is an OSM restroom this close, or this close to one tagged as a Throne.
THRONE_SAME_M = 15.0  # 50 ft
THRONE_TAGGED_M = 150.0  # 500 ft
THRONE_STATUSES = frozenset({"open", "opens soon", "unverified"})
THRONE = "Throne"
M_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class Amenity:
    osm: str  # "n123" or "w456"
    lon: float
    lat: float
    water: str | None  # "p" drinking, "n" untreated
    toilet: str | None  # "f" flush, "b" basic, "u" not mapped
    name: str | None = None
    fee: str | None = None
    wheelchair: str | None = None
    hours: str | None = None
    seasonal: str | None = None
    bottle: bool = False
    op: str | None = None  # "Throne" for a Throne smart restroom


def is_historic_spring(tags: dict[str, str]) -> bool:
    """A spring mapped as a historic landmark and not marked drinkable."""
    if tags.get("natural") not in SOURCES_NATURAL or tags.get("drinking_water") == "yes":
        return False
    return tags.get("historic", "no") != "no" or tags.get("ruins") == "yes"


def water_of(tags: dict[str, str]) -> str | None:
    """'p' for drinking water, 'n' for an untreated source, None for neither."""
    amenity = tags.get("amenity")
    drinking = tags.get("drinking_water")
    if is_historic_spring(tags) and amenity not in ("drinking_water", "water_point"):
        return None
    source = (
        tags.get("man_made") in SOURCES_MAN_MADE
        or tags.get("natural") in SOURCES_NATURAL
        or amenity == "water_point"
    )
    if amenity == "drinking_water":
        return "n" if drinking == "no" else "p"
    if amenity == "water_point" and drinking != "no":
        return "p"
    if drinking == "yes" and (source or amenity in DRINKABLE_HOSTS_AMENITY):
        return "p"
    if source:
        return "n"
    return None


def toilet_of(tags: dict[str, str]) -> str | None:
    """'f' flush, 'b' portable or other basic toilet, 'u' type not mapped, None for no restroom."""
    if tags.get("amenity") != "toilets":
        return None
    disposal = tags.get("toilets:disposal", "")
    kinds = {d.strip() for d in disposal.split(";") if d.strip()}
    if "flush" in kinds:
        return "f"
    if kinds & BASIC_DISPOSAL or tags.get("portable") == "yes":
        return "b"
    return "u"


def is_public(tags: dict[str, str]) -> bool:
    access = tags.get("access")
    if access is not None and access not in PUBLIC_ACCESS:
        return False
    return tags.get("disused") != "yes" and tags.get("abandoned") != "yes"


def is_throne(tags: dict[str, str]) -> bool:
    """An OSM restroom mapped as a Throne unit (operator, brand or name)."""
    return (
        any("throne" in tags.get(k, "").lower() for k in ("operator", "brand", "name"))
        and tags.get("amenity") == "toilets"
    )


def secured_kind(tags: dict[str, str]) -> str | None:
    """'airport', 'military' or 'prison' for an area the public cannot walk into; else None."""
    if tags.get("aeroway") in SECURED_AEROWAY:
        return "airport"
    military = tags.get("military")
    if tags.get("landuse") == "military" or (military and military not in MILITARY_OPEN):
        return "military"
    if tags.get("amenity") == "prison":
        return "prison"
    return None


def _text(value: str | None) -> str | None:
    if not value:
        return None
    value = " ".join(value.split())
    return value[:MAX_TEXT] if value else None


def classify(osm: str, tags: dict[str, str], lon: float, lat: float) -> Amenity | None:
    """The point's amenity, or None when it is neither public water nor a public restroom."""
    water = water_of(tags)
    toilet = toilet_of(tags)
    if not (water or toilet) or not is_public(tags):
        return None
    west, south, east, north = COVERAGE_BBOX
    if not (west <= lon <= east and south <= lat <= north):
        return None
    fee = tags.get("fee")
    wheelchair = tags.get("wheelchair")
    seasonal = tags.get("seasonal")
    return Amenity(
        osm=osm,
        lon=round(lon, 5),
        lat=round(lat, 5),
        water=water,
        toilet=toilet,
        name=_text(tags.get("name")),
        fee=fee if fee in YES_NO else None,
        wheelchair=wheelchair if wheelchair in WHEELCHAIR else None,
        hours=_text(tags.get("opening_hours")),
        seasonal=None if seasonal in (None, "no") else _text(seasonal),
        bottle=water == "p" and tags.get("bottle") == "yes",
        op=THRONE if is_throne(tags) else None,
    )


@dataclass(frozen=True)
class Element:
    """An OSM element as read, before it is classified."""

    osm: str
    tags: dict[str, str]
    lon: float
    lat: float
    ring: tuple[tuple[float, float], ...] = ()  # a closed way's corners


def is_toilet_building(tags: dict[str, str]) -> bool:
    return tags.get("amenity") == "toilets" or tags.get("building") == "toilets"


def _inside(lon: float, lat: float, ring: tuple[tuple[float, float], ...]) -> bool:
    """Even-odd ray test; a point on an edge may fall either way, which is fine here."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        (xi, yi), (xj, yj) = ring[i], ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _richness(e: Element) -> tuple[int, int]:
    # More layer details first; on a tie the node, mapped as the restroom itself.
    return (sum(k in DETAIL_KEYS for k in e.tags), e.osm.startswith("n"))


def merged_tags(members: list[Element]) -> dict[str, str] | None:
    """One restroom's tags from its building and the nodes inside, or None to leave it out.

    Per key the richest element's value wins; keys only one has are kept. A
    building that is not public or not in use takes the whole place out; a node
    inside that is not public is left out on its own (and a bare building=toilets
    left with no public node goes too).
    """
    if not all(is_public(m.tags) for m in members if not m.osm.startswith("n")):
        return None
    members = [m for m in members if not m.osm.startswith("n") or is_public(m.tags)]
    if not any(m.tags.get("amenity") == "toilets" for m in members):
        # A bare building=toilets whose only restroom node was not public.
        return None
    tags: dict[str, str] = {}
    for m in sorted(members, key=_richness, reverse=True):
        for k, v in m.tags.items():
            tags.setdefault(k, v)
    tags["amenity"] = "toilets"
    return tags


def merge_restrooms(nodes: list[Element], buildings: list[Element]) -> list[Element]:
    """Fold each amenity=toilets node inside a restroom building into that building.

    Returns the elements to classify: merged buildings, amenity=toilets
    buildings with no node inside, and the nodes no building holds. A
    building=toilets way with nothing inside is left out, as it was before.
    """
    inside: dict[str, list[Element]] = {b.osm: [] for b in buildings}
    loose: list[Element] = []
    boxes = [
        (
            b,
            min(x for x, _ in b.ring),
            min(y for _, y in b.ring),
            max(x for x, _ in b.ring),
            max(y for _, y in b.ring),
        )
        for b in buildings
        if len(b.ring) >= 3
    ]
    for n in nodes:
        home = next(
            (
                b
                for b, w, s, e, north in boxes
                if w <= n.lon <= e and s <= n.lat <= north and _inside(n.lon, n.lat, b.ring)
            ),
            None,
        )
        if home is None:
            loose.append(n)
        else:
            inside[home.osm].append(n)
    out: list[Element] = []
    for b in buildings:
        held = inside[b.osm]
        if not held:
            if b.tags.get("amenity") == "toilets":
                out.append(b)
            continue
        tags = merged_tags([b, *held])
        if tags is not None:
            out.append(Element(b.osm, tags, b.lon, b.lat, b.ring))
    return out + loose


# --- Where the public cannot walk in -----------------------------------------

Ring = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class SecuredArea:
    """One outer ring of an area the public cannot walk into, with its holes."""

    kind: str  # "airport", "military" or "prison"
    outer: Ring
    holes: tuple[Ring, ...] = ()

    def box(self) -> tuple[float, float, float, float]:
        xs = [x for x, _ in self.outer]
        ys = [y for _, y in self.outer]
        return (min(xs), min(ys), max(xs), max(ys))

    def holds(self, lon: float, lat: float) -> bool:
        return _inside(lon, lat, self.outer) and not any(_inside(lon, lat, h) for h in self.holes)


def leave_out_secured(
    elements: list[Element], areas: list[SecuredArea]
) -> tuple[list[Element], Counter]:
    """The elements outside every secured area, and how many were left out, by kind."""
    boxed = [(a, a.box()) for a in areas if len(a.outer) >= 3]
    kept: list[Element] = []
    left_out: Counter = Counter()
    for e in elements:
        kind = next(
            (
                a.kind
                for a, (w, s, east, n) in boxed
                if w <= e.lon <= east and s <= e.lat <= n and a.holds(e.lon, e.lat)
            ),
            None,
        )
        if kind is None:
            kept.append(e)
        else:
            left_out[kind] += 1
    return kept, left_out


# --- Throne smart restrooms --------------------------------------------------


def _metres(a_lon: float, a_lat: float, b_lon: float, b_lat: float) -> float:
    """Flat distance in metres; plenty at a few hundred metres."""
    kx = M_PER_DEG_LAT * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot((a_lon - b_lon) * kx, (a_lat - b_lat) * M_PER_DEG_LAT)


def load_throne(path: Path) -> list[dict]:
    """The hand list's units, checked: unique ids, a name, a place, a status, dated sources."""
    units = json.loads(path.read_text(encoding="utf-8"))["units"]
    seen: set[str] = set()
    for u in units:
        uid = u.get("id", "")
        if not uid.startswith("throne-") or uid in seen:
            raise ValueError(f"Throne unit id must be unique and start throne-: {uid!r}")
        seen.add(uid)
        if u.get("status") not in THRONE_STATUSES:
            raise ValueError(
                f"{uid}: status {u.get('status')!r} is not one of {sorted(THRONE_STATUSES)}"
            )
        if not u.get("name") or not u.get("jurisdiction"):
            raise ValueError(f"{uid}: needs a name and a jurisdiction")
        if not all(isinstance(u.get(k), (int, float)) for k in ("lat", "lon")):
            raise ValueError(f"{uid}: lat and lon must be numbers")
        sources = u.get("sources") or []
        if not sources or not all((s.get("url") or s.get("by")) and s.get("read") for s in sources):
            raise ValueError(
                f"{uid}: every source needs a url (or who saw it, 'by') and the date read"
            )
    return units


def merge_throne(amenities: list[Amenity], units: list[dict]) -> tuple[list[Amenity], int, int]:
    """Mark or add the open Throne units: the points, how many were added and how many matched OSM.

    Units not "open" are skipped. A unit within THRONE_SAME_M of an OSM
    restroom, or within THRONE_TAGGED_M of one already tagged as a Throne, is
    that restroom (the nearest): the OSM point keeps its place and details and
    is marked op Throne. Otherwise the unit is added. Points from an earlier
    merge (ids "throne-...") are dropped first, so a rerun gives the same file.
    """
    out = [a for a in amenities if not a.osm.startswith("throne-")]
    west, south, east, north = COVERAGE_BBOX
    added = matched = 0
    for u in units:
        if u["status"] != "open":
            continue
        lon, lat = float(u["lon"]), float(u["lat"])
        if not (west <= lon <= east and south <= lat <= north):
            continue
        best: tuple[float, int] | None = None
        for i, a in enumerate(out):
            if a.toilet is None or a.osm.startswith("throne-"):
                continue
            d = _metres(lon, lat, a.lon, a.lat)
            reach = THRONE_TAGGED_M if a.op == THRONE else THRONE_SAME_M
            if d <= reach and (best is None or d < best[0]):
                best = (d, i)
        if best is not None:
            out[best[1]] = replace(out[best[1]], op=THRONE)
            matched += 1
            continue
        out.append(
            Amenity(
                osm=u["id"],
                lon=round(lon, 5),
                lat=round(lat, 5),
                water=None,
                toilet="f",
                name=_text(u["name"]),
                fee="no",
                wheelchair="yes",
                op=THRONE,
            )
        )
        added += 1
    return out, added, matched


def from_document(doc: dict) -> list[Amenity]:
    """The points of a file this script wrote, back as Amenity (for --throne-only)."""
    return [
        Amenity(
            osm=p["id"],
            lon=p["x"],
            lat=p["y"],
            water=p.get("w"),
            toilet=p.get("t"),
            name=p.get("n"),
            fee=p.get("fee"),
            wheelchair=p.get("wc"),
            hours=p.get("h"),
            seasonal=p.get("s"),
            bottle=p.get("b") == 1,
            op=p.get("op"),
        )
        for p in doc["points"]
    ]


def read_extract(path: Path) -> tuple[list[Amenity], Counter]:
    """Public water and restrooms in the extract, and how many secured areas left out, by kind."""
    import osmium

    others: list[Element] = []
    toilet_nodes: list[Element] = []
    buildings: list[Element] = []
    secured: list[SecuredArea] = []

    def wanted(tags: dict[str, str]) -> bool:
        return water_of(tags) is not None or toilet_of(tags) is not None

    def tagged(t) -> bool:
        # Cheap first test; every other building is skipped without a copy of its tags.
        return "amenity" in t or "man_made" in t or "natural" in t or t.get("building") == "toilets"

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if not tagged(n.tags):
                return
            tags = dict(n.tags)
            if not wanted(tags):
                return
            e = Element(f"n{n.id}", tags, n.location.lon, n.location.lat)
            (toilet_nodes if tags.get("amenity") == "toilets" else others).append(e)

        def way(self, w):
            if not tagged(w.tags):
                return
            tags = dict(w.tags)
            building = is_toilet_building(tags)
            if not (building or wanted(tags)):
                return
            nodes = [nd for nd in w.nodes if nd.location.valid()]
            if not nodes:
                return
            # A closed way repeats its first node; count it once.
            closed = len(nodes) > 1 and nodes[0].ref == nodes[-1].ref
            if closed:
                nodes = nodes[:-1]
            lon = sum(nd.location.lon for nd in nodes) / len(nodes)
            lat = sum(nd.location.lat for nd in nodes) / len(nodes)
            ring = tuple((nd.location.lon, nd.location.lat) for nd in nodes) if closed else ()
            e = Element(f"w{w.id}", tags, lon, lat, ring)
            if building and closed:
                buildings.append(e)
            elif wanted(tags):
                others.append(e)

        def area(self, a):
            # Closed ways and multipolygon relations alike; osmium assembles both.
            t = a.tags
            if not ("aeroway" in t or "landuse" in t or "military" in t or "amenity" in t):
                return
            kind = secured_kind(dict(t))
            if kind is None:
                return
            try:
                for outer in a.outer_rings():
                    ring = tuple((n.lon, n.lat) for n in outer)
                    holes = tuple(
                        tuple((n.lon, n.lat) for n in inner) for inner in a.inner_rings(outer)
                    )
                    secured.append(SecuredArea(kind, ring, holes))
            except osmium.InvalidLocationError:
                return

    Handler().apply_file(str(path), locations=True)
    elements, left_out = leave_out_secured(
        others + merge_restrooms(toilet_nodes, buildings), secured
    )
    found: list[Amenity] = []
    for e in elements:
        a = classify(e.osm, e.tags, e.lon, e.lat)
        if a:
            found.append(a)
    return found, left_out


def _sort_key(a: Amenity) -> tuple[int, str, int, str]:
    # OSM nodes, then ways, by number; then the Throne list's units by id.
    if a.osm[:1] in ("n", "w") and a.osm[1:].isdigit():
        return (0, a.osm[0], int(a.osm[1:]), "")
    return (1, "", 0, a.osm)


def document(amenities: list[Amenity]) -> dict:
    """The file the front end reads: short keys, absent fields left out."""
    points = []
    for a in sorted(amenities, key=_sort_key):
        p: dict = {"id": a.osm, "x": a.lon, "y": a.lat}
        if a.water:
            p["w"] = a.water
        if a.toilet:
            p["t"] = a.toilet
        if a.name:
            p["n"] = a.name
        if a.fee:
            p["fee"] = a.fee
        if a.wheelchair:
            p["wc"] = a.wheelchair
        if a.hours:
            p["h"] = a.hours
        if a.seasonal:
            p["s"] = a.seasonal
        if a.bottle:
            p["b"] = 1
        if a.op:
            p["op"] = a.op
        points.append(p)
    return {"source": SOURCE, "also": SOURCE_THRONE, "points": points}


def write_document(doc: dict, out: Path) -> None:
    # One point per line: small, and a refresh diffs point by point.
    lines = [json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in doc["points"]]
    text = (
        '{"source":'
        + json.dumps(doc["source"])
        + ',"also":'
        + json.dumps(doc["also"])
        + ',"points":[\n'
        + ",\n".join(lines)
        + ("\n" if lines else "")
        + "]}\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pbf", type=Path, help="<DATA_ROOT>/extracts/source.osm.pbf")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--throne", type=Path, default=THRONE_LIST, help="the Throne hand list")
    parser.add_argument(
        "--throne-only",
        action="store_true",
        help="no extract: merge the Throne list again into --out, keeping its OSM points",
    )
    args = parser.parse_args(argv)
    if args.throne_only == bool(args.pbf):
        parser.error(
            "give --pbf, or --throne-only (and no --pbf) to refresh the Throne units alone"
        )
    units = load_throne(args.throne)
    left_out: Counter = Counter()
    if args.throne_only:
        # The file cannot tell a point's own Throne tags from an earlier match, so
        # every OSM point is unmarked and matched again (within THRONE_SAME_M).
        osm_points = [
            replace(a, op=None)
            for a in from_document(json.loads(args.out.read_text(encoding="utf-8")))
        ]
    else:
        osm_points, left_out = read_extract(args.pbf)
    amenities, added, matched = merge_throne(osm_points, units)
    write_document(document(amenities), args.out)
    count = lambda field, value: sum(getattr(a, field) == value for a in amenities)  # noqa: E731
    print(
        f"{len(amenities)} points: drinking water {count('water', 'p')}, "
        f"untreated water {count('water', 'n')}; restrooms flush {count('toilet', 'f')}, "
        f"basic {count('toilet', 'b')}, type not mapped {count('toilet', 'u')}"
    )
    waiting = sum(u["status"] != "open" for u in units)
    print(
        f"Throne: {added} added from the list, {matched} matched to OSM restrooms; "
        f"{waiting} in the list not open or not confirmed, left off the map"
    )
    if not args.throne_only:
        kinds = ", ".join(f"{k} {n}" for k, n in sorted(left_out.items())) or "none"
        print(
            f"left out inside airports, military sites and prisons: "
            f"{sum(left_out.values())} ({kinds})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
