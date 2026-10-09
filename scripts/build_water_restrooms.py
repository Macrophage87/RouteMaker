#!/usr/bin/env python3
"""Write the public drinking water and restrooms the map shows, from the OSM extract.

Owner request (2026-10-09): "OSM sometimes has public water fountains and
restrooms. That should be a layer, especially on trailmaxxing and gravel."
The layer is the map's Water and restrooms switch (frontend/src/lib/waterRestrooms.ts).

What counts, from the OSM wiki's own tag definitions
(<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Ddrinking_water>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dwater_point>,
<https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dwater_tap>,
<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dtoilets>,
<https://wiki.openstreetmap.org/wiki/Key:drinking_water>,
<https://wiki.openstreetmap.org/wiki/Key:access>):

- water: amenity=drinking_water (unless drinking_water=no); amenity=water_point
  unless drinking_water=no; and drinking_water=yes on a tap, well, fountain,
  shelter or restroom, the features where riders can reach it.
- restroom: amenity=toilets.
- public only: no access tag, or access=yes, public, permissive or designated.
  Anything else (private, customers, permit, no, ...) is left out, as an unclear
  "maybe you can use it" is no help to a thirsty rider; this follows the
  project's rule that unclear access is closed.
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
# Where drinking_water=yes means a rider can fill a bottle there.
WATER_HOSTS_AMENITY = frozenset({"fountain", "shelter", "toilets", "water_point", "drinking_water"})
WATER_HOSTS_MAN_MADE = frozenset({"water_tap", "water_well"})
YES_NO = frozenset({"yes", "no"})
WHEELCHAIR = frozenset({"yes", "limited", "no"})
MAX_TEXT = 80


@dataclass(frozen=True)
class Amenity:
    osm: str  # "n123" or "w456"
    lon: float
    lat: float
    water: bool
    toilets: bool
    name: str | None = None
    fee: str | None = None
    wheelchair: str | None = None
    hours: str | None = None
    seasonal: str | None = None
    bottle: bool = False

    @property
    def kind(self) -> str:
        return ("w" if self.water else "") + ("t" if self.toilets else "")


def is_water(tags: dict[str, str]) -> bool:
    amenity = tags.get("amenity")
    drinking = tags.get("drinking_water")
    if drinking == "no":
        return False
    if amenity in ("drinking_water", "water_point"):
        return True
    return drinking == "yes" and (
        amenity in WATER_HOSTS_AMENITY or tags.get("man_made") in WATER_HOSTS_MAN_MADE
    )


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
    water = is_water(tags)
    toilets = tags.get("amenity") == "toilets"
    if not (water or toilets) or not is_public(tags):
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
        toilets=toilets,
        name=_text(tags.get("name")),
        fee=fee if fee in YES_NO else None,
        wheelchair=wheelchair if wheelchair in WHEELCHAIR else None,
        hours=_text(tags.get("opening_hours")),
        seasonal=None if seasonal in (None, "no") else _text(seasonal),
        bottle=water and tags.get("bottle") == "yes",
    )


def read_extract(path: Path) -> list[Amenity]:
    import osmium

    found: list[Amenity] = []

    def wanted(tags: dict[str, str]) -> bool:
        return (
            tags.get("amenity") in WATER_HOSTS_AMENITY
            or tags.get("man_made") in WATER_HOSTS_MAN_MADE
        )

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if "amenity" not in n.tags and "man_made" not in n.tags:
                return
            tags = dict(n.tags)
            if wanted(tags):
                a = classify(f"n{n.id}", tags, n.location.lon, n.location.lat)
                if a:
                    found.append(a)

        def way(self, w):
            if "amenity" not in w.tags and "man_made" not in w.tags:
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
        p: dict = {"id": a.osm, "x": a.lon, "y": a.lat, "k": a.kind}
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
    water = sum(a.water for a in amenities)
    toilets = sum(a.toilets for a in amenities)
    both = sum(a.water and a.toilets for a in amenities)
    print(f"{len(amenities)} points: {water} with water, {toilets} restrooms, {both} both")
    return 0


if __name__ == "__main__":
    sys.exit(main())
