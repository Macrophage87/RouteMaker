#!/usr/bin/env python3
"""Write the District of Columbia's boundary for the Mass Ride map (OWNER-DECISIONS 418, 418a).

Mass Ride planning covers the District only for now: the map greys out everything
outside it, draws no capacity colour there, and the planner warns when a Mass Ride's
route leaves it. The boundary is OpenStreetMap's: the `boundary=administrative`,
`admin_level=4`, `ISO3166-2=US-DC` relation in the regional extract the rebuild
already reads, joined into rings by the rebuild's own code (`pipeline.states`, which
gives every way its state from the same relation). Nothing is downloaded.

    python scripts/build_dc_boundary.py <extract>.osm.pbf

writes the same bytes to

    frontend/src/massride-data/dc-boundary.json   the map's mask and the route check
    src/core/geodata/dc-boundary.geojson             the Mass Ride tiles' clip (core.mass_tiles)

(tests/test_dc_boundary.py holds the two equal.) The polygon is simplified to
SIMPLIFY_DEGREES (about 30 ft, 10 m) with its topology kept and snapped to a
1e-5 degree grid (about 3 ft, 1 m). Credit: (c) OpenStreetMap contributors, ODbL
(docs/SOURCES.md). Needs osmium and shapely (the project's virtualenv has both).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from shapely import set_precision  # noqa: E402
from shapely.geometry import MultiPolygon, Polygon, mapping  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from pipeline.states import read_boundaries, read_nodes, rings  # noqa: E402

OUTPUTS = (
    REPO / "frontend/src/massride-data/dc-boundary.json",
    REPO / "src/core/geodata/dc-boundary.geojson",
)
STATE = "DC"
# About 10 m: well inside a street's width at the zooms the mask is seen at, and it
# keeps the file to a few hundred vertices (the river shore is most of them).
SIMPLIFY_DEGREES = 0.0001
GRID_DEGREES = 1e-5
CREDIT = "© OpenStreetMap contributors (ODbL)"


def dc_polygon(pbf: Path):
    boundaries = read_boundaries(pbf)
    if STATE not in boundaries:
        raise SystemExit(f"no admin_level=4 US-{STATE} relation in {pbf}")
    rows = boundaries[STATE]
    at = read_nodes(pbf, {n for _, ids in rows for n in ids})
    shapes: dict[str, list[Polygon]] = {"outer": [], "inner": []}
    for role in shapes:
        closed, dropped = rings([ids for r, ids in rows if (r == "inner") == (role == "inner")])
        if dropped:
            raise SystemExit(f"{dropped} {role} chain(s) of the District's boundary do not close")
        for ring in closed:
            shapes[role].append(Polygon([at[n] for n in ring]))
    geometry = unary_union(shapes["outer"]).buffer(0)
    for hole in shapes["inner"]:
        geometry = geometry.difference(hole)
    geometry = geometry.simplify(SIMPLIFY_DEGREES, preserve_topology=True)
    geometry = set_precision(geometry, GRID_DEGREES)
    if isinstance(geometry, Polygon):
        geometry = MultiPolygon([geometry])
    return geometry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pbf", type=Path, help="an OSM extract holding the District's boundary")
    args = parser.parse_args(argv)
    geometry = dc_polygon(args.pbf)
    feature = {
        "type": "Feature",
        "properties": {
            "name": "District of Columbia",
            "source": "OpenStreetMap, boundary relation ISO3166-2=US-DC (admin_level=4)",
            "credit": CREDIT,
        },
        "geometry": json.loads(json.dumps(mapping(geometry))),
    }
    text = json.dumps(feature, separators=(",", ":")) + "\n"
    for out in OUTPUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    vertices = sum(
        len(p.exterior.coords) + sum(len(i.coords) for i in p.interiors) for p in geometry.geoms
    )
    print(
        f"{len(geometry.geoms)} polygon(s), {vertices} vertices, {len(text)} bytes, "
        f"bounds {geometry.bounds}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
