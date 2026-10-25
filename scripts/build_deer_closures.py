#!/usr/bin/env python3
"""Write the ways the deer-management closures cover (`core.deer_closures`).

Two agencies close parts of their parks at night, or for whole days, each winter to manage
the deer (the owner, 2026-10-25: "Put this notice in the park though for some routes"):

- **Rock Creek Park (NPS).** The record of determination names the car-free roads that "may
  also [be] closed to pedestrians, bicyclists and non-motorized recreation from 6:45 p.m. to
  4 a.m.": Bingham Drive, Sherrill Drive, Beach Drive from Broad Branch Road to Joyce Road,
  from Picnic Grove 10 to Wise Road, and from West Beach Drive to the Maryland line. They
  are named here by OpenStreetMap way (`ROCK_CREEK_WAYS`), read from the OSM API.
- **Montgomery Parks.** Its deer schedule closes whole parks ("Parks and Trails Closed"). A
  park's boundary is Montgomery Parks' own (the Park Units layer, `PARK_UNITS`), used only to
  choose OpenStreetMap's paths inside it; only those paths are written, so a public road
  through a park is never part of its closure. Black Hill's firearms hunts close its "10
  Mile Creek Segment" only, the park west of MD 121 (the archery list's "Day Use segment
  east of Rte. 121" is the other part).

    python scripts/build_deer_closures.py

writes `src/core/geodata/deer-closures.geojson`: one feature an area, its lines a
MultiLineString of OpenStreetMap geometry (ODbL; docs/SOURCES.md), simplified to about 16 ft
(5 m) and rounded to 1e-5 degrees. The OSM API is asked one tile at a time, a second apart.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "core" / "geodata" / "deer-closures.geojson"
OSM_API = "https://api.openstreetmap.org/api/0.6"
PARK_UNITS = (
    "https://services1.arcgis.com/HbzrdBZjOwNHp70P/ArcGIS/rest/services/"
    "ParkUnitsPlus_Py/FeatureServer/0/query"
)
USER_AGENT = "RouteMaker-deer-closures"

# Rock Creek Park's car-free stretches (OSM ways, read 2026-10-25).
ROCK_CREEK_WAYS = {
    # Beach Drive, Broad Branch Road to Joyce Road.
    "beach-south": (6056562, 640524608, 1109871669),
    # Beach Drive, Picnic Grove 10 to Wise Road.
    "beach-middle": (797700582,),
    # Beach Drive, West Beach Drive to the Maryland line.
    "beach-north": (435217297, 435217296, 435217299),
    "bingham": (6054324, 131520056, 1340623546, 1340623547, 1248259616, 1340623540, 1340623541),
    "sherrill": (6061851, 50866136, 50866146),
}

# Montgomery Parks' park codes (the Park Units layer's PARK_CODE) for each area of
# core.deer_closures.MOCO_PARKS.
MOCO_CODES = (
    "K01", "P55", "P56", "F06", "H02", "G08", "P35", "D57", "P37", "L07", "P39", "P40", "K08",
    "P61", "B75", "G12", "K03", "S15", "S20", "L14", "G09", "G07", "S12", "S21", "G06",
)  # fmt: skip
PATHS = frozenset({"path", "footway", "cycleway", "bridleway", "track", "pedestrian"})
TILE_DEG = 0.02
STEP_M = 10.0
MIN_RUN_M = 60.0
SIMPLIFY_M = 5.0


def _get(url: str, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as answer:
        return answer.read()


def _xy(lon, lat, lat0):
    k = math.pi / 180 * 6_371_008.8
    return lon * k * math.cos(math.radians(lat0)), lat * k


def _simplify(line, tolerance_m):
    if len(line) < 3:
        return line
    lat0 = line[0][1]
    pts = [_xy(*p, lat0) for p in line]

    def dist(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == dy == 0:
            return math.dist(p, a)
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.dist(p, (a[0] + t * dx, a[1] + t * dy))

    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        far, at = 0.0, None
        for k in range(i + 1, j):
            d = dist(pts[k], pts[i], pts[j])
            if d > far:
                far, at = d, k
        if at is not None and far > tolerance_m:
            keep[at] = True
            stack += [(i, at), (at, j)]
    return [p for p, k in zip(line, keep, strict=True) if k]


def _round(line):
    return [[round(lon, 5), round(lat, 5)] for lon, lat in line]


def _in_ring(p, ring):
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _in_polygons(p, polygons):
    return any(
        _in_ring(p, poly[0]) and not any(_in_ring(p, h) for h in poly[1:]) for poly in polygons
    )


def _densify(line):
    out = [line[0]]
    lat0 = line[0][1]
    for a, b in zip(line, line[1:], strict=False):
        n = max(1, int(math.dist(_xy(*a, lat0), _xy(*b, lat0)) // STEP_M))
        out += [
            (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1)
        ]
    return out


def _length_m(line):
    lat0 = line[0][1]
    return sum(
        math.dist(_xy(*a, lat0), _xy(*b, lat0)) for a, b in zip(line, line[1:], strict=False)
    )


def _runs_inside(line, inside):
    """The pieces of `line` whose points `inside` holds, each at least MIN_RUN_M long."""
    runs, run = [], []
    for p in _densify(line):
        if inside(p):
            run.append(p)
        else:
            if len(run) >= 2:
                runs.append(run)
            run = []
    if len(run) >= 2:
        runs.append(run)
    return [r for r in runs if _length_m(r) >= MIN_RUN_M]


def rock_creek() -> dict[str, list]:
    lines = {}
    for key, ways in ROCK_CREEK_WAYS.items():
        found = []
        for way in ways:
            root = ET.fromstring(_get(f"{OSM_API}/way/{way}/full"))
            nodes = {
                n.get("id"): (float(n.get("lon")), float(n.get("lat"))) for n in root.iter("node")
            }
            found.append([nodes[nd.get("ref")] for nd in root.find("way").iter("nd")])
            time.sleep(1)
        lines[key] = found
    return lines


def parks() -> dict[str, dict]:
    codes = ",".join(f"'{c}'" for c in MOCO_CODES)
    query = {
        "where": f"PARK_CODE IN ({codes})",
        "outFields": "PARK_NAME,PARK_CODE",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "geojson",
    }
    answer = json.loads(_get(PARK_UNITS, urllib.parse.urlencode(query).encode()))
    found: dict[str, dict] = {}
    for feature in answer["features"]:
        code = feature["properties"]["PARK_CODE"]
        g = feature["geometry"]
        polygons = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        polygons = [[[tuple(p) for p in ring] for ring in poly] for poly in polygons]
        found.setdefault(code, {"name": feature["properties"]["PARK_NAME"], "polygons": []})
        found[code]["polygons"] += polygons
    return found


def _tile(west, south, east, north):
    """The OSM API's map call, split in four where a tile holds too many nodes."""
    url = f"{OSM_API}/map?bbox={west},{south},{east},{north}"
    try:
        body = _get(url)
    except urllib.error.HTTPError as error:
        if error.code != 400:
            raise
        mx, my = (west + east) / 2, (south + north) / 2
        out = []
        for box in (
            (west, south, mx, my),
            (mx, south, east, my),
            (west, my, mx, north),
            (mx, my, east, north),
        ):
            out.append(_tile(*box))
        return "".join(out)
    time.sleep(1)
    return body.decode()


def _paths(polygons):
    xs = [p[0] for poly in polygons for p in poly[0]]
    ys = [p[1] for poly in polygons for p in poly[0]]
    nodes, ways = {}, {}
    lon = min(xs)
    while lon < max(xs):
        lat = min(ys)
        while lat < max(ys):
            box = (lon, lat, min(lon + TILE_DEG, max(xs)), min(lat + TILE_DEG, max(ys)))
            for doc in _split_docs(_tile(*box)):
                root = ET.fromstring(doc)
                for n in root.iter("node"):
                    nodes[n.get("id")] = (float(n.get("lon")), float(n.get("lat")))
                for w in root.iter("way"):
                    tags = {t.get("k"): t.get("v") for t in w.iter("tag")}
                    ways[w.get("id")] = (tags, [nd.get("ref") for nd in w.iter("nd")])
            lat += TILE_DEG
        lon += TILE_DEG
    return nodes, ways


def _split_docs(text):
    parts = text.split("<?xml")
    return ["<?xml" + p for p in parts if p.strip()]


def _md121(nodes, ways):
    """MD 121's line, as (lat, lon) pairs sorted by latitude."""
    pts = []
    for tags, refs in ways.values():
        if "MD 121" in (tags.get("ref") or "").split(";"):
            pts += [nodes[r] for r in refs if r in nodes]
    return sorted((lat, lon) for lon, lat in pts)


def _west_of(line):
    def west(p):
        lon, lat = p
        nearest = min(line, key=lambda q: abs(q[0] - lat))
        return lon < nearest[1]

    return west


def moco() -> dict[str, list]:
    out = {}
    for code, park in sorted(parks().items()):
        nodes, ways = _paths(park["polygons"])
        inside = lambda p, polys=park["polygons"]: _in_polygons(p, polys)  # noqa: E731
        if code == "G07":
            west = _west_of(_md121(nodes, ways))
            inside = lambda p, polys=park["polygons"], west=west: (  # noqa: E731
                _in_polygons(p, polys) and west(p)
            )
        lines = []
        for tags, refs in ways.values():
            if tags.get("highway") not in PATHS or tags.get("footway") in ("sidewalk", "crossing"):
                continue
            if tags.get("access") in ("private", "no"):
                continue
            line = [nodes[r] for r in refs if r in nodes]
            if len(line) >= 2:
                lines += _runs_inside(line, inside)
        out[code] = lines
        print(code, park["name"], len(lines), "lines")
    return out


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    features = []
    rocr = [line for lines in rock_creek().values() for line in lines]
    for key, lines in {"rocr-deer": rocr, **{f"moco-{c}": v for c, v in moco().items()}}.items():
        simple = [_round(_simplify(line, SIMPLIFY_M)) for line in lines]
        if not simple:
            continue  # no path inside the park: nothing to ride, so no notice
        features.append(
            {
                "type": "Feature",
                "properties": {"area": key},
                "geometry": {"type": "MultiLineString", "coordinates": simple},
            }
        )
    OUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
        + "\n"
    )
    print("wrote", OUT)


if __name__ == "__main__":
    main()
