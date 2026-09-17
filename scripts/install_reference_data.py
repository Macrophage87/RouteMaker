#!/usr/bin/env python3
"""Put the rebuild's reference data where `ReferenceData.load` reads it.

The weekly rebuild refuses to run without three files under
`<DATA_ROOT>/reference/`, because each one stood in for real data in an early
version and each produced a specific wrong map when empty:

    crossings.json     the Potomac and Anacostia crossings fixture, checked in
    urban-areas.json   OSM way ids inside a Census urban area
    volume.json        agency traffic counts, normalised to one AADT definition

Nothing populated the directory. The fixture was checked in and read by
nothing, and the other two had no producer at all. This installs the fixture
and, given the inputs, produces the other two:

    python scripts/install_reference_data.py --data-root /srv/routemaker/data \\
        --extract /srv/routemaker/data/extracts/source.osm.pbf \\
        --urban-areas tl_2024_us_uac20.geojson \\
        --volume vdot-aadt-2024.geojson --volume-source vdot --volume-year 2024

Run with only --data-root it installs the crossings and reports which of the
other two are still missing, exiting non-zero while any is. See
docs/DEVELOPMENT.md, "Reference data", for where each input comes from.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

CROSSINGS_FIXTURE = REPO / "fixtures" / "crossings" / "potomac-anacostia.json"
REQUIRED = ("crossings.json", "urban-areas.json", "volume.json")


def install_crossings(reference: Path) -> Path:
    destination = reference / "crossings.json"
    json.loads(CROSSINGS_FIXTURE.read_text())  # refuse to install a broken fixture
    shutil.copyfile(CROSSINGS_FIXTURE, destination)
    return destination


def _geometries(geojson: Path):
    from shapely.geometry import shape

    document = json.loads(geojson.read_text())
    features = document["features"] if document.get("type") == "FeatureCollection" else [document]
    for feature in features:
        geometry = feature.get("geometry") if "geometry" in feature else feature
        if geometry:
            yield shape(geometry), feature.get("properties") or {}


def urban_way_ids(extract: Path, urban_areas: Path) -> list[int]:
    """Ways whose geometry intersects any urban-area polygon.

    Intersection rather than containment, so a street that leaves the urban
    boundary is still graded against urban speeds: the alternative grades the
    last block of a District street as rural.
    """
    from shapely.geometry import LineString
    from shapely.strtree import STRtree

    from pipeline.extract import read_ways

    polygons = [geometry for geometry, _ in _geometries(urban_areas)]
    if not polygons:
        raise SystemExit(f"{urban_areas} holds no polygons")
    index = STRtree(polygons)
    ids = []
    for way in read_ways(extract):
        if len(way.coordinates) < 2:
            continue
        line = LineString(way.coordinates)
        if any(polygons[i].intersects(line) for i in index.query(line)):
            ids.append(way.osm_id)
    return sorted(ids)


def volume_rows(volume: Path, source: str, year: int | None, aadt_property: str) -> list[dict]:
    """Agency count lines in the shape `conflation.AgencyFeature` is built from.

    Bidirectional AADT is the one definition; an agency publishing directional
    counts has to be summed before it reaches here, which is why the property
    name is an argument rather than guessed.
    """
    rows = []
    for number, (geometry, properties) in enumerate(_geometries(volume)):
        value = properties.get(aadt_property)
        if value in (None, ""):
            continue
        lines = (
            [geometry]
            if geometry.geom_type == "LineString"
            else list(getattr(geometry, "geoms", []))
        )
        for part, line in enumerate(lines):
            if line.geom_type != "LineString":
                continue
            rows.append(
                {
                    "id": f"{source}-{properties.get('OBJECTID', number)}-{part}",
                    "coordinates": [[x, y] for x, y in line.coords],
                    "aadt": int(float(value)),
                    "source": source,
                    "year": year,
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data-root", type=Path, default=Path(os.environ.get("DATA_ROOT", REPO / "data"))
    )
    parser.add_argument("--extract", type=Path, help="the source OSM extract, for --urban-areas")
    parser.add_argument("--urban-areas", type=Path, help="Census urban-area polygons, GeoJSON")
    parser.add_argument("--volume", type=Path, help="agency count lines, GeoJSON")
    parser.add_argument("--volume-source", default="vdot")
    parser.add_argument("--volume-year", type=int)
    parser.add_argument("--aadt-property", default="AADT")
    args = parser.parse_args(argv)

    reference = args.data_root / "reference"
    reference.mkdir(parents=True, exist_ok=True)

    print(f"installed {install_crossings(reference)}")

    if args.urban_areas:
        if not args.extract:
            parser.error("--urban-areas needs --extract")
        ids = urban_way_ids(args.extract, args.urban_areas)
        (reference / "urban-areas.json").write_text(json.dumps(ids))
        print(f"wrote {reference / 'urban-areas.json'}: {len(ids)} urban ways")

    if args.volume:
        rows = volume_rows(args.volume, args.volume_source, args.volume_year, args.aadt_property)
        (reference / "volume.json").write_text(json.dumps(rows))
        print(f"wrote {reference / 'volume.json'}: {len(rows)} count lines")

    missing = [name for name in REQUIRED if not (reference / name).exists()]
    for name in missing:
        print(f"MISSING {reference / name}; the rebuild will refuse to run", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
