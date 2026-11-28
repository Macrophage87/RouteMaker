#!/usr/bin/env python3
"""The beaches and beach paths on the map (the owner, 2026-11-23: "show the beaches as
bikeable areas"; the tide line as "a specific beach biking path").

Reads the project's extract the way the rebuild does (`pipeline.beaches`) and writes
frontend/src/beach-data/beaches.json: the beaches in the map areas whose beaches are
ridden (Southwest Florida), simplified, with their names, and the beach paths along the
tide line, each with its OSM way id so a route's pieces on it are known (lib/beaches.ts).

    PYTHONPATH=src python3 scripts/build_beaches.py --pbf <extract.osm.pbf>

Run it after every map rebuild, from the same extract (docs/OPERATIONS.md, "After every
map rebuild"). Needs osmium and shapely (the rebuild container has both).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/src/beach-data/beaches.json"
# About 2 m: the map is drawn from zoom 11, where a pixel is ~50 m.
SIMPLIFY_DEG = 0.00002
SIZE_BUDGET = 600_000

# The Southwest Florida box (settings.SOUTHWEST_FLORIDA_BBOX), the area whose beaches are ridden.
SOUTHWEST_FLORIDA_BBOX = (-82.75, 25.65, -80.70, 27.45)


def rounded(coords) -> list[list[float]]:
    return [[round(x, 5), round(y, 5)] for x, y in coords]


def polygons(shape) -> list:
    return list(getattr(shape, "geoms", [shape]))


def build(found) -> dict:
    from shapely.geometry import LineString

    features = []
    for beach in found.beaches:
        if beach.closed:
            continue
        for poly in polygons(beach.shape.simplify(SIMPLIFY_DEG, preserve_topology=True)):
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {"kind": "beach", "name": beach.name, "osm": beach.osm},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [rounded(poly.exterior.coords)]
                        + [rounded(ring.coords) for ring in poly.interiors],
                    },
                }
            )
    for path in found.paths:
        line = LineString(path.coordinates).simplify(SIMPLIFY_DEG)
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "path", "way": path.osm_id},
                "geometry": {"type": "LineString", "coordinates": rounded(line.coords)},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pbf", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT / "src"))
    from pipeline import beaches

    found = beaches.read(args.pbf, [SOUTHWEST_FLORIDA_BBOX])
    data = build(found)
    text = json.dumps(data, separators=(",", ":")) + "\n"
    if len(text) > SIZE_BUDGET:
        print(f"beaches.json is {len(text):,} bytes, over {SIZE_BUDGET:,}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(f"wrote {args.out}: {beaches.summary(found)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
