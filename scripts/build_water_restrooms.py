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
- untreated water ("n", filter or treat it first): a tap, well, spring or water
  point that is not marked drinking_water=yes, so drinking_water=no and no tag
  at all alike, as the project treats unclear as closed. An
  amenity=drinking_water marked drinking_water=no is untreated too. Decorative
  fountains are left out unless marked drinkable.
- restrooms: amenity=toilets, by toilets:disposal: flush ("f"); a portable,
  pit, composting or other basic toilet ("b": chemical, pitlatrine, bucket,
  dry_toilet, incineration, composting, or portable=yes); or not mapped ("u").
- public only: no access tag, or access=yes, public, permissive or designated.
  Anything else (private, customers, permit, no, ...) is left out, as an unclear
  "maybe you can use it" is no help to a rider; this follows the project's
  rule that unclear access is closed.
- in use only: disused=yes and abandoned=yes are left out (lifecycle-prefixed
  keys such as disused:amenity never match in the first place).

Nodes and ways are read (a restroom building is often a way); a way is placed
at the mean of its nodes. Points outside the coverage box are dropped, and
coordinates are rounded to 5 decimals, about 3 ft (1 m).

Run from the repository root with the development venv (osmium is in
requirements-dev.txt):

    .venv311/bin/python scripts/build_water_restrooms.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It reads the extract only and writes
frontend/src/amenity-data/water-restrooms.json (frontend/src/amenity-data/README.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "src" / "amenity-data" / "water-restrooms.json"

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
YES_NO = frozenset({"yes", "no"})
WHEELCHAIR = frozenset({"yes", "limited", "no"})
MAX_TEXT = 80


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


def water_of(tags: dict[str, str]) -> str | None:
    """'p' for drinking water, 'n' for an untreated source, None for neither."""
    amenity = tags.get("amenity")
    drinking = tags.get("drinking_water")
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
    )


def read_extract(path: Path) -> list[Amenity]:
    import osmium

    found: list[Amenity] = []

    def wanted(tags: dict[str, str]) -> bool:
        return water_of(tags) is not None or toilet_of(tags) is not None

    def tagged(t) -> bool:
        return "amenity" in t or "man_made" in t or "natural" in t

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if not tagged(n.tags):
                return
            tags = dict(n.tags)
            if wanted(tags):
                a = classify(f"n{n.id}", tags, n.location.lon, n.location.lat)
                if a:
                    found.append(a)

        def way(self, w):
            if not tagged(w.tags):
                return
            tags = dict(w.tags)
            if not wanted(tags):
                return
            nodes = [nd for nd in w.nodes if nd.location.valid()]
            if not nodes:
                return
            # A closed way repeats its first node; count it once.
            if len(nodes) > 1 and nodes[0].ref == nodes[-1].ref:
                nodes = nodes[:-1]
            lon = sum(nd.location.lon for nd in nodes) / len(nodes)
            lat = sum(nd.location.lat for nd in nodes) / len(nodes)
            a = classify(f"w{w.id}", tags, lon, lat)
            if a:
                found.append(a)

    Handler().apply_file(str(path), locations=True)
    return found


def _sort_key(a: Amenity) -> tuple[str, int]:
    return (a.osm[0], int(a.osm[1:]))


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
        points.append(p)
    return {
        "source": "OpenStreetMap contributors, ODbL 1.0",
        "points": points,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pbf", type=Path, required=True, help="<DATA_ROOT>/extracts/source.osm.pbf"
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    amenities = read_extract(args.pbf)
    doc = document(amenities)
    # One point per line: small, and a refresh diffs point by point.
    lines = [json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in doc["points"]]
    text = (
        '{"source":'
        + json.dumps(doc["source"])
        + ',"points":[\n'
        + ",\n".join(lines)
        + ("\n" if lines else "")
        + "]}\n"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    count = lambda field, value: sum(getattr(a, field) == value for a in amenities)  # noqa: E731
    print(
        f"{len(amenities)} points: drinking water {count('water', 'p')}, "
        f"untreated water {count('water', 'n')}; restrooms flush {count('toilet', 'f')}, "
        f"basic {count('toilet', 'b')}, type not mapped {count('toilet', 'u')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
