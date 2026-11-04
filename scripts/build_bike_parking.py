#!/usr/bin/env python3
"""Write the bike racks Go offers near a spot, from DDOT's and BCDOT's racks and the OSM extract.

Owner requests (2026-11-01): "Is there anywhere to find bike parking location
data?", then "When people select a location in Go, by map press or by selecting
a location, show the nearby racks and offer them as a routing option." The
front end reads the file in lib/bikeParking.ts.

Three sources, the cities' first (the owner, 2026-10-11: "DC government data generally
wins over OSM for the same attribute"):

- **DC**: DDOT's **Public Bike Racks** on DC Open Data, ArcGIS item
  650302fe184a4ebf84ca355e6f31fa18, layer
  <https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_Bikes_Trails_WebMercator/MapServer/168>,
  licence CC BY 4.0 (the item's licence field and data.gov's record). The
  public racks DDOT has installed (4,862 on 2026-11-01), each with its number
  of racks (`NUMBERRACKS`, empty on some). Fetched with `--ddot` (the network).
- **Baltimore City**: the Baltimore City Department of Transportation's
  **Baltimore City Bike Racks and Scooter Parking Map**, web map
  b14d91d49b584dfdb1c6ca3713a30231, linked from BCDOT's Bike and Scooter
  Parking page
  (<https://www.baltimorecity.gov/transportation/our-work/bike-baltimore/bike-and-scooter-parking>).
  Owner request (2026-11-04): "Also, add in the bike racks from BCDOT". Three of
  its layers, fetched with `--baltimore` (the network):
  - **BCDOT Installed Bike Racks** (item 688603423f30439395c0956be800d9c5,
    BALTIMORE_RACKS): racks from the city's rack request program, Installed=Yes,
    with `Rack_Count`. The layer also holds the requesters' names, phones and
    emails: only OBJECTID, Installed and Rack_Count are ever asked for.
  - **Scooter Corrals** (item 25f5c095fd68418b814840f13f1c5989,
    BALTIMORE_CORRALS): only the corrals with bike racks (Rack_Count > 0); a
    striped scooter-only corral has nothing to lock a bike to.
  - **Bike Racks Additional**, a 2021 inventory of racks open to the public
    (city and private) kept inside the web map itself, with RACK_COUNT and
    COVERED.
  Licence: open, as Baltimore City data, by Baltimore City Code Art. 1
  §9-1(h) (<https://codes.baltimorecity.gov/us/md/cities/baltimore/code/1/9-1#(h)>;
  the owner, 2026-11-04: "Baltimore city data is public domain, just like DC.
  It's in the city code"); the layers' own licence fields are empty. Credit
  BCDOT. Only positions, rack counts and covered are kept. Installed racks win over corrals,
  and both over the 2021 inventory, within SAME_RACK_M.
- **Elsewhere**: OpenStreetMap's amenity=bicycle_parking
  (<https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dbicycle_parking>), read
  from the project's extract with `--pbf`, ODbL 1.0. Public only, by the rule
  build_water_restrooms.py uses (no access tag, or yes, public, permissive or
  designated; an unclear access is closed); in use (no disused=yes or
  abandoned=yes). Its capacity, covered=yes and its kind (bicycle_parking=*:
  lockers and a building are said so, as a rider may need a key or a pass)
  are kept. An OSM rack within SAME_RACK_M of a city's rack is the same rack and
  the city's is kept, unless OSM's is lockers or a bike room.

A source not asked for is kept from the file as it is: without `--pbf` the OSM
racks, so a refresh from the cloud does not drop them; without `--ddot` the
DDOT racks; without `--baltimore` Baltimore's. Points outside the coverage box are dropped;
coordinates are rounded to 5 decimals, about 3 ft (1 m).

The file, one point per line: {"id", "x" (lon), "y" (lat), and where known
"r" (racks, DDOT or BCDOT), "c" (capacity, OSM), "k" (OSM kind: "l" lockers, "b" a
building or room, "s" stands or not mapped), "cv" (1: covered), "n" (name)}.

    python3 scripts/build_bike_parking.py --ddot --baltimore
    python3 scripts/build_bike_parking.py --pbf <DATA_ROOT>/extracts/source.osm.pbf
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "src" / "amenity-data" / "bike-parking.json"

DDOT_LAYER = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/"
    "Transportation_Bikes_Trails_WebMercator/MapServer/168"
)
SOURCE_DDOT = "DC Open Data, DDOT Public Bike Racks (CC BY 4.0)"
SOURCE_BALTIMORE = (
    "Baltimore City Department of Transportation, bike racks and scooter corrals "
    "(open, Baltimore City Code Art. 1 §9-1(h))"
)
SOURCE_OSM = "OpenStreetMap contributors, ODbL 1.0"

# src/config/settings.py COVERAGE_BBOX (west, south, east, north), as
# build_water_restrooms.py has it.
COVERAGE_BBOX = (-78.05, 38.2, -76.02, 39.72)
PUBLIC_ACCESS = frozenset({"yes", "public", "permissive", "designated"})
# An OSM rack this close to a DDOT rack is the same one: about 80 ft.
SAME_RACK_M = 25.0
# Racks this close are one place to a rider (DDOT maps each rack of a row of racks as its own
# point, often 1 to 3 m apart): one point, their racks added up. About 50 ft.
ONE_PLACE_M = 15.0
PAGE = 1000

BALTIMORE_SERVICES = "https://services3.arcgis.com/ZTvQ9NuONePFYofE/arcgis/rest/services"
BALTIMORE_RACKS = f"{BALTIMORE_SERVICES}/BCDOT_Bike_Racks/FeatureServer/0"
BALTIMORE_CORRALS = f"{BALTIMORE_SERVICES}/Scooter_Corrals/FeatureServer/0"
BALTIMORE_MAP = (
    "https://www.arcgis.com/sharing/rest/content/items/b14d91d49b584dfdb1c6ca3713a30231/data?f=json"
)
BALTIMORE_INVENTORY = "Bike Racks Additional"
# Id prefixes: DDOT, then Baltimore's installed racks, corrals and 2021 inventory. OSM's are
# "n", "w" or "r" and a number.
DDOT = "dc"
BALTIMORE = ("bc", "bs", "ba")
CITY = (DDOT, *BALTIMORE)

LOCKERS = frozenset({"lockers"})
BUILDING = frozenset({"building", "shed"})


@dataclass(frozen=True)
class Rack:
    id: str
    lon: float
    lat: float
    racks: int | None = None
    capacity: int | None = None
    kind: str | None = None
    covered: bool = False
    name: str | None = None

    def point(self) -> dict:
        p: dict = {"id": self.id, "x": round(self.lon, 5), "y": round(self.lat, 5)}
        if self.racks:
            p["r"] = self.racks
        if self.capacity:
            p["c"] = self.capacity
        if self.kind and self.kind != "s":
            p["k"] = self.kind
        if self.covered:
            p["cv"] = 1
        if self.name:
            p["n"] = self.name
        return p


def inside(lon: float, lat: float) -> bool:
    west, south, east, north = COVERAGE_BBOX
    return west <= lon <= east and south <= lat <= north


def _int(value: object) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 10000 else None


def city(rack_id: str) -> str | None:
    """The city source's prefix of a rack id, or None for OSM's."""
    return rack_id[:2] if rack_id[:2] in CITY else None


def ddot_rack(feature: dict) -> Rack | None:
    """One DDOT feature (GeoJSON-like attributes and a lon/lat point) as a rack, or None."""
    attrs = feature.get("attributes") or {}
    geom = feature.get("geometry") or {}
    lon, lat = geom.get("x"), geom.get("y")
    oid = attrs.get("OBJECTID")
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or oid is None:
        return None
    if not inside(lon, lat):
        return None
    return Rack(id=f"dc{oid}", lon=lon, lat=lat, racks=_int(attrs.get("NUMBERRACKS")))


def osm_rack(osm: str, tags: dict[str, str], lon: float, lat: float) -> Rack | None:
    """An OSM element as a public rack in use, or None."""
    if tags.get("amenity") != "bicycle_parking":
        return None
    if tags.get("disused") == "yes" or tags.get("abandoned") == "yes":
        return None
    access = tags.get("access")
    if access is not None and access not in PUBLIC_ACCESS:
        return None
    if not inside(lon, lat):
        return None
    kind_tag = tags.get("bicycle_parking", "")
    kind = "l" if kind_tag in LOCKERS else "b" if kind_tag in BUILDING else "s"
    name = (tags.get("name") or "").strip() or None
    return Rack(
        id=osm,
        lon=lon,
        lat=lat,
        capacity=_int(tags.get("capacity")),
        kind=kind,
        covered=tags.get("covered") == "yes",
        name=name,
    )


def _point(feature: dict) -> tuple[float, float] | None:
    geom = feature.get("geometry") or {}
    lon, lat = geom.get("x"), geom.get("y")
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        return None
    return lon, lat


def baltimore_installed(feature: dict) -> Rack | None:
    """A BCDOT Installed Bike Racks feature (lon/lat) as a rack, if installed."""
    attrs = feature.get("attributes") or {}
    at, oid = _point(feature), attrs.get("OBJECTID")
    if at is None or oid is None or str(attrs.get("Installed", "")).strip().lower() != "yes":
        return None
    if not inside(*at):
        return None
    return Rack(id=f"bc{oid}", lon=at[0], lat=at[1], racks=_int(attrs.get("Rack_Count")))


def baltimore_corral(feature: dict) -> Rack | None:
    """A Scooter Corrals feature (lon/lat) as a rack, if it has bike racks."""
    attrs = feature.get("attributes") or {}
    at, fid, racks = _point(feature), attrs.get("FID"), _int(attrs.get("Rack_Count"))
    if at is None or fid is None or not racks or not inside(*at):
        return None
    return Rack(id=f"bs{fid}", lon=at[0], lat=at[1], racks=racks)


def web_mercator(x: float, y: float) -> tuple[float, float]:
    """EPSG:3857 metres to lon/lat."""
    r = 6378137.0
    return math.degrees(x / r), math.degrees(2 * math.atan(math.exp(y / r)) - math.pi / 2)


def baltimore_inventory(feature: dict) -> Rack | None:
    """A 2021 inventory feature (web Mercator, as the web map keeps it) as a rack."""
    attrs = feature.get("attributes") or {}
    at, fid = _point(feature), attrs.get("FID")
    if at is None or fid is None:
        return None
    lon, lat = web_mercator(*at)
    if not inside(lon, lat):
        return None
    return Rack(
        id=f"ba{fid}",
        lon=lon,
        lat=lat,
        racks=_int(attrs.get("RACK_COUNT")),
        covered=str(attrs.get("COVERED", "")).strip().upper() == "Y",
    )


def metres(a: Rack, b: Rack) -> float:
    # Equirectangular: exact enough at 25 m.
    k = math.cos(math.radians((a.lat + b.lat) / 2))
    dx = (a.lon - b.lon) * k * 111_320
    dy = (a.lat - b.lat) * 110_540
    return math.hypot(dx, dy)


def drop_same(osm: list[Rack], ddot: list[Rack], within: float = SAME_RACK_M) -> list[Rack]:
    """The racks of `osm` with none of `ddot` within `within` metres (the second list wins)."""
    cell = 0.001  # about 100 m: a grid so each OSM rack checks its neighbours only
    grid: dict[tuple[int, int], list[Rack]] = {}
    for r in ddot:
        grid.setdefault((int(r.lon / cell), int(r.lat / cell)), []).append(r)
    kept = []
    for r in osm:
        cx, cy = int(r.lon / cell), int(r.lat / cell)
        near = (
            d
            for gx in (cx - 1, cx, cx + 1)
            for gy in (cy - 1, cy, cy + 1)
            for d in grid.get((gx, gy), ())
        )
        if not any(metres(r, d) <= within for d in near):
            kept.append(r)
    return kept


def one_place(racks: list[Rack], within: float = ONE_PLACE_M) -> list[Rack]:
    """Racks within `within` metres of a group's first rack joined into one point, in id order.

    The point is the group's mean position; its racks and capacity are the sums of those known
    (a count is kept only when every rack in the group has one, so "Racks: 3" never undercounts
    a row where one rack's count is missing); covered only if all are; the first one's id,
    kind and name.
    """
    cell = 0.0005  # about 50 m
    groups: list[list[Rack]] = []
    grid: dict[tuple[int, int], list[int]] = {}
    for r in sorted(racks, key=lambda r: r.id):
        cx, cy = int(r.lon / cell), int(r.lat / cell)
        home = None
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for g in grid.get((gx, gy), ()):
                    if metres(r, groups[g][0]) <= within and (home is None or g < home):
                        home = g
        if home is None:
            home = len(groups)
            groups.append([])
            grid.setdefault((cx, cy), []).append(home)
        groups[home].append(r)
    out = []
    for g in groups:
        first = g[0]
        n = len(g)
        racks_known = all(r.racks for r in g)
        cap_known = all(r.capacity for r in g)
        out.append(
            Rack(
                id=first.id,
                lon=sum(r.lon for r in g) / n,
                lat=sum(r.lat for r in g) / n,
                racks=sum(r.racks or 0 for r in g) if racks_known else None,
                capacity=sum(r.capacity or 0 for r in g) if cap_known else None,
                kind=first.kind,
                covered=all(r.covered for r in g),
                name=first.name,
            )
        )
    return out


def from_point(p: dict) -> Rack:
    return Rack(
        id=p["id"],
        lon=p["x"],
        lat=p["y"],
        racks=p.get("r"),
        capacity=p.get("c"),
        kind=p.get("k", "s" if not city(p["id"]) else None),
        covered=p.get("cv") == 1,
        name=p.get("n"),
    )


def fetch_layer(layer: str, fields: str, order: str) -> list[dict]:
    """Every feature of an ArcGIS layer, a page of PAGE at a time, asked for in lon/lat."""
    features: list[dict] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "where": "1=1",
                "outFields": fields,
                "outSR": "4326",
                "orderByFields": order,
                "resultOffset": offset,
                "resultRecordCount": PAGE,
                "f": "json",
            }
        )
        with urllib.request.urlopen(f"{layer}/query?{query}", timeout=60) as response:
            doc = json.load(response)
        if "error" in doc:
            raise RuntimeError(f"{layer}: {doc['error']}")
        page = doc.get("features") or []
        features.extend(page)
        if not page or not doc.get("exceededTransferLimit"):
            break
        offset += len(page)
    return features


def fetch_ddot() -> list[Rack]:
    """Every DDOT rack, racks of one place joined."""
    features = fetch_layer(DDOT_LAYER, "OBJECTID,NUMBERRACKS", "OBJECTID")
    return one_place([r for r in (ddot_rack(f) for f in features) if r])


def inventory_features(web_map: dict) -> list[dict]:
    """The 2021 inventory's features, kept inside the web map as a feature collection."""
    for layer in web_map.get("operationalLayers") or []:
        if layer.get("title") == BALTIMORE_INVENTORY:
            for sub in (layer.get("featureCollection") or {}).get("layers") or []:
                sr = (sub.get("featureSet") or {}).get("spatialReference") or (
                    (sub.get("layerDefinition") or {}).get("extent") or {}
                ).get("spatialReference")
                if sr and (sr.get("latestWkid") or sr.get("wkid")) not in (3857, 102100):
                    raise RuntimeError(f"Baltimore inventory: not web Mercator ({sr})")
            return [
                f
                for sub in (layer.get("featureCollection") or {}).get("layers") or []
                for f in (sub.get("featureSet") or {}).get("features") or []
            ]
    raise RuntimeError(f"Baltimore web map: no layer {BALTIMORE_INVENTORY!r}")


def baltimore(installed: list[Rack], corrals: list[Rack], inventory: list[Rack]) -> list[Rack]:
    """Baltimore's racks, one place each: installed, then corrals, then the 2021 inventory."""
    kept = one_place(installed)
    kept += one_place(drop_same(corrals, kept))
    kept += one_place(drop_same(inventory, kept))
    return kept


def fetch_baltimore() -> list[Rack]:
    """Every BCDOT rack, from the three layers. Never the requesters' names or contacts."""
    installed = fetch_layer(BALTIMORE_RACKS, "OBJECTID,Installed,Rack_Count", "OBJECTID")
    corrals = fetch_layer(BALTIMORE_CORRALS, "FID,Rack_Count", "FID")
    with urllib.request.urlopen(BALTIMORE_MAP, timeout=60) as response:
        web_map = json.load(response)
    return baltimore(
        [r for r in (baltimore_installed(f) for f in installed) if r],
        [r for r in (baltimore_corral(f) for f in corrals) if r],
        [r for r in (baltimore_inventory(f) for f in inventory_features(web_map)) if r],
    )


def read_extract(path: Path) -> list[Rack]:
    import osmium

    found: list[Rack] = []

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if n.tags.get("amenity") != "bicycle_parking":
                return
            r = osm_rack(f"n{n.id}", dict(n.tags), n.location.lon, n.location.lat)
            if r:
                found.append(r)

        def way(self, w):
            if w.tags.get("amenity") != "bicycle_parking":
                return
            nodes = [nd for nd in w.nodes if nd.location.valid()]
            if not nodes:
                return
            if len(nodes) > 1 and nodes[0].ref == nodes[-1].ref:
                nodes = nodes[:-1]
            lon = sum(nd.location.lon for nd in nodes) / len(nodes)
            lat = sum(nd.location.lat for nd in nodes) / len(nodes)
            r = osm_rack(f"w{w.id}", dict(w.tags), lon, lat)
            if r:
                found.append(r)

    Handler().apply_file(str(path), locations=True)
    return one_place(found)


def document(ddot: list[Rack], osm: list[Rack], balt: list[Rack] | None = None) -> dict:
    balt = balt or []
    cities = sorted(ddot, key=lambda r: r.id) + sorted(balt, key=lambda r: r.id)
    # Lockers or a bike room are not the stands a city lists beside them: always kept.
    rooms = [r for r in osm if r.kind in ("l", "b")]
    stands = [r for r in osm if r.kind not in ("l", "b")]
    racks = cities + sorted(rooms + drop_same(stands, cities), key=lambda r: r.id)
    sources = (
        ([SOURCE_DDOT] if ddot else [])
        + ([SOURCE_BALTIMORE] if balt else [])
        + ([SOURCE_OSM] if osm else [])
    )
    return {"source": "; ".join(sources), "points": [r.point() for r in racks]}


def write_document(doc: dict, out: Path) -> None:
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
    out.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ddot", action="store_true", help="fetch DDOT's racks again (network)")
    parser.add_argument(
        "--baltimore", action="store_true", help="fetch BCDOT's racks again (network)"
    )
    parser.add_argument("--pbf", type=Path, help="<DATA_ROOT>/extracts/source.osm.pbf")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if not args.ddot and not args.baltimore and not args.pbf:
        parser.error("give --ddot, --baltimore, --pbf, or more than one")
    kept = []
    if args.out.exists():
        kept = [from_point(p) for p in json.loads(args.out.read_text(encoding="utf-8"))["points"]]
    ddot = fetch_ddot() if args.ddot else [r for r in kept if city(r.id) == DDOT]
    balt = fetch_baltimore() if args.baltimore else [r for r in kept if city(r.id) in BALTIMORE]
    osm = read_extract(args.pbf) if args.pbf else [r for r in kept if not city(r.id)]
    doc = document(ddot, osm, balt)
    write_document(doc, args.out)
    n_osm = len(doc["points"]) - len(ddot) - len(balt)
    print(
        f"{len(doc['points'])} racks: DDOT {len(ddot)}, Baltimore {len(balt)}, "
        f"OSM {n_osm} (of {len(osm)} before the cities' won)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
