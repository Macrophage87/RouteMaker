#!/usr/bin/env python3
"""Merge the fetched federal-land layers into the Mass Ride map overlay's one file.

The overlay (frontend/src/lib/federalLand.ts, PLAN.md FOLLOWUP-FEDERAL-LAYER,
owner items 236-239) shades the areas under federal control so a mass ride can
see where federal permit rules may apply. This reads the raw GeoJSON the
downloader wrote (scripts/fetch_agency_layer.py, records in
fixtures/datasets/README.md) and writes ONE simplified FeatureCollection of
polygons, each with

    kind    nps | reservation | federal | military | capitol
    name    what the popup calls the area
    agency  the managing agency where the source names one, else absent

Where kinds overlap, the more specific one wins and the other is clipped
around it (capitol over military over nps over reservation over federal), so
the map shades each patch once and the legend's kinds do not blur. GSA office
buildings are left out (owner item 238): the optional federal-land input, when
one is given, drops lots whose owner names GSA.

    python scripts/build_federal_land.py \
        --nps  <datasets>/federal/dc-national-parks/dc-national-parks.geojson \
        --reservations <datasets>/federal/dc-reservations/dc-reservations.geojson \
        --military <datasets>/federal/dc-military-bases/dc-military-bases.geojson \
        --capitol fixtures/cbd/architect-of-the-capitol.geojson

writes frontend/src/federal-data/federal-land.json (GeoJSON, named .json so the
edge serves and compresses it as JSON), which the front end
bundles as a hashed asset (served under /assets/ with the rest, so no edge or
deploy change). Needs shapely (the project's virtualenv has it).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import shapely
from shapely import STRtree
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

KINDS = ("capitol", "military", "nps", "reservation", "federal")
"""Highest priority first: a patch belongs to the first kind that holds it."""

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "frontend/src/federal-data/federal-land.json"

# About 3 m of latitude, in degrees: well under a street's width at the zoom the
# overlay is drawn at, and enough to take the source's survey vertices out.
SIMPLIFY_DEGREES = 0.00003
# Coordinates to 1e-5 degrees (about 1 m); the file's size is mostly digits.
GRID_DEGREES = 1e-5
# Where two shapes were clipped against each other the new corners fall off the
# grid; they are rounded to 1e-6 (about 0.1 m) to keep the digits down.
CLIP_GRID_DEGREES = 1e-6
# Slivers smaller than this many square metres are dropped after clipping (the
# edges of a lot against a street the source drew a little differently).
MIN_AREA_M2 = 60.0
_M_PER_DEG_LAT = 111_320.0

NPS_GENERIC = {"triangle", "center parking", "curb parking", "park", "parkway", "parking"}
NPS_AGENCY = "National Park Service"
NPS_UNSTATED = "National Park Service or another federal agency (NPS Map A)"
RESERVATION_AGENCY = "National Park Service (most U.S. Reservations)"
CAPITOL_NAME = "U.S. Capitol grounds"
CAPITOL_AGENCY = "Architect of the Capitol"
GSA_OWNER = re.compile(r"\bGSA\b|GENERAL SERVICES ADMIN", re.IGNORECASE)


def _load(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        raise SystemExit(f"{path}: not a FeatureCollection")
    return [f for f in data["features"] if f.get("geometry")]


def _text(value: object) -> str:
    return " ".join(str(value).split()) if value not in (None, "") else ""


def _area_m2(geom: BaseGeometry) -> float:
    """Planar area in square metres, good to a percent or two across DC."""
    lat = geom.centroid.y if not geom.is_empty else 38.9
    return geom.area * _M_PER_DEG_LAT**2 * math.cos(math.radians(lat))


def _polygons(geom: BaseGeometry) -> list[BaseGeometry]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for g in geom.geoms for p in _polygons(g)]
    return []


def _clean(geom: BaseGeometry) -> BaseGeometry:
    return unary_union(_polygons(make_valid(geom))) if not geom.is_empty else geom


def _prepare(geom: BaseGeometry) -> BaseGeometry:
    """A source shape, valid, simplified and snapped to the grid."""
    geom = _clean(geom)
    if geom.is_empty:
        return geom
    return _clean(
        shapely.set_precision(geom.simplify(SIMPLIFY_DEGREES, preserve_topology=True), GRID_DEGREES)
    )


def nps_name(props: dict) -> tuple[str, str]:
    """The name and agency for one NPS Map A polygon."""
    base = _text(props.get("NAME")) or _text(props.get("LABEL"))
    reserve = _text(props.get("RESERVE")).lstrip("0")
    if not base:
        base = "National Park Service land"
    if reserve and (base.lower() in NPS_GENERIC or base == "National Park Service land"):
        base = f"{base} (Reservation {reserve})"
    agency = NPS_AGENCY if _text(props.get("SOURCE")) == "NPS" else NPS_UNSTATED
    return base, agency


def collect(args: argparse.Namespace) -> dict[str, list[tuple[BaseGeometry, dict]]]:
    """Each kind's (geometry, properties) pairs, before any clipping."""
    out: dict[str, list[tuple[BaseGeometry, dict]]] = {k: [] for k in KINDS}
    for f in _load(args.nps):
        name, agency = nps_name(f["properties"])
        out["nps"].append((shape(f["geometry"]), {"name": name, "agency": agency}))
    for f in _load(args.reservations):
        p = f["properties"]
        if p.get("KILL_DT") or p.get("ISHISTORIC"):
            continue  # a retired reservation lot
        res = _text(p.get("RES")).lstrip("0")
        name = f"U.S. Reservation {res}" if res else "U.S. Reservation"
        out["reservation"].append(
            (shape(f["geometry"]), {"name": name, "agency": RESERVATION_AGENCY})
        )
    for f in _load(args.military):
        name = _text(f["properties"].get("NAME")) or "Military installation"
        # The layer names no agency, so the popup names none rather than guess.
        out["military"].append((shape(f["geometry"]), {"name": name}))
    for f in _load(args.capitol):
        out["capitol"].append(
            (shape(f["geometry"]), {"name": CAPITOL_NAME, "agency": CAPITOL_AGENCY})
        )
    if args.federal:
        for f in _load(args.federal):
            p = f["properties"]
            owner = _text(p.get("OWNERNAME"))
            if GSA_OWNER.search(owner):
                continue  # item 238: GSA office buildings are not wanted
            label = _text(p.get("PREMISEADD")) or "Federal land"
            out["federal"].append(
                (shape(f["geometry"]), {"name": label, "agency": owner.title() or None})
            )
    return out


def build(layers: dict[str, list[tuple[BaseGeometry, dict]]]) -> dict:
    features: list[dict] = []
    # What higher kinds already hold, as the shapes themselves with an index:
    # clipping against only the ones a piece touches, not one big union, which
    # is the difference between seconds and minutes.
    taken: list[BaseGeometry] = []
    index: STRtree | None = None
    for kind in KINDS:
        # Simplify and snap every piece first, then clip the simplified shapes
        # against each other, so a patch is shaded once in the file as drawn
        # (clipping the raw shapes and simplifying after lets two neighbours
        # drift over each other).
        pieces = [(_prepare(g), props) for g, props in layers[kind]]
        pieces = [(g, p) for g, p in pieces if not g.is_empty]
        for geom, props in pieces:
            if index is not None:
                touching = [taken[i] for i in index.query(geom, predicate="intersects")]
                if touching:
                    geom = _clean(geom.difference(unary_union(touching)))
            if geom.is_empty:
                continue
            geom = _clean(shapely.set_precision(geom, CLIP_GRID_DEGREES))
            keep = [p for p in _polygons(geom) if _area_m2(p) >= MIN_AREA_M2]
            if not keep:
                continue
            geom = keep[0] if len(keep) == 1 else shapely.MultiPolygon(keep)
            properties = {"kind": kind, "name": props["name"]}
            if props.get("agency"):
                properties["agency"] = props["agency"]
            features.append(
                {"type": "Feature", "properties": properties, "geometry": mapping(geom)}
            )
        taken.extend(g for g, _ in pieces)
        index = STRtree(taken)
    features.sort(key=lambda f: (KINDS.index(f["properties"]["kind"]), f["properties"]["name"]))
    return {"type": "FeatureCollection", "features": features}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--nps", required=True, type=Path)
    parser.add_argument("--reservations", required=True, type=Path)
    parser.add_argument("--military", required=True, type=Path)
    parser.add_argument("--capitol", required=True, type=Path)
    parser.add_argument(
        "--federal", type=Path, help="optional Federal Land (RPTA) layer; not downloaded yet"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    collection = build(collect(args))
    counts = {k: sum(f["properties"]["kind"] == k for f in collection["features"]) for k in KINDS}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(collection, separators=(",", ":"), ensure_ascii=False) + "\n"
    args.out.write_text(text, encoding="utf-8")
    print(f"{args.out}: {len(collection['features'])} areas {counts}, {len(text.encode()):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
