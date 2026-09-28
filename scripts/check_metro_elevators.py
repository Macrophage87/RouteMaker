#!/usr/bin/env python3
"""Compare the DC Metro elevator points with the elevators OpenStreetMap maps.

The map sends a rider who taps a Metro station to its elevator, the bike
entrance (owner, 2026-09-27), and the elevators come from Open Data DC's
"Metro Station Entrances (Regional)" layer (frontend/src/rail-data/). Most of that
layer was captured in 2016, so this lists where OSM disagrees with it rather
than merging the two: DC's point is the one the map uses wherever DC has one.

Listed:
- DC elevators with no OSM elevator of any kind within MATCH_M (moved,
  removed, or unmapped in OSM);
- OSM street elevators (highway=elevator on a railway=subway_entrance) with no
  DC elevator within MATCH_M - candidates DC is missing, flagged for review and
  not used;
- OSM's other elevators at the stations DC gives no elevator at all (surface
  and elevated stations, mostly), which are the likeliest real gaps, also
  flagged and not used;
- a count of OSM's other elevators near stations (mostly platform-to-mezzanine
  ones inside the station, which are not a way in from the street).

With --write it also writes frontend/src/rail-data/metro-osm-elevators.geojson:
the OSM elevators at the stations DC gives no elevator at all. The owner
chose (2026-09-28) to send riders to those where DC has none, and to the
nearest DC entrance where neither has one; DC's elevator stays first wherever
DC lists one.

Run from the repository root with the development venv:

    .venv311/bin/python scripts/check_metro_elevators.py \
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It reads the extract and the committed fixtures; without --write it writes nothing.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "frontend" / "src" / "rail-data"
FALLBACK_OUT = DATA / "metro-osm-elevators.geojson"
MATCH_M = 40.0
NEAR_STATION_M = 300.0


def _marc_module():
    spec = importlib.util.spec_from_file_location(
        "build_marc_penn_stations", Path(__file__).with_name("build_marc_penn_stations.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


def compare(stations, dc_elevators, osm_elevators, distance_m):
    """Where the two disagree.

    stations: [(name, (lon, lat))]; dc_elevators: [(label, (lon, lat))];
    osm_elevators: [(osm id, (lon, lat), street: bool)], street meaning it is
    also tagged railway=subway_entrance. Returns (dc_only, osm_only, near): the
    DC elevators with no OSM elevator of any kind within MATCH_M; the OSM
    elevators within NEAR_STATION_M of a station with no DC elevator within
    MATCH_M, as (osm id, station, point, street); and every OSM elevator near
    a station.
    """

    def nearest_station(point):
        name, where = min(stations, key=lambda s: distance_m(point, s[1]))
        return name, distance_m(point, where)

    near = []
    for osm, point, street in osm_elevators:
        name, d = nearest_station(point)
        if d <= NEAR_STATION_M:
            near.append((osm, name, point, street))
    dc_only = [
        (label, nearest_station(point)[0], point)
        for label, point in dc_elevators
        if not any(distance_m(point, o[2]) <= MATCH_M for o in near)
    ]
    osm_only = [o for o in near if not any(distance_m(o[2], p) <= MATCH_M for _, p in dc_elevators)]
    return dc_only, osm_only, near


def fallback_elevators(stations, dc_elevators, osm_elevators, distance_m):
    """The OSM elevators within NEAR_STATION_M of a station DC gives no elevator.

    stations: [(name, gis_id, (lon, lat))]; the other two as for compare().
    Each elevator, DC's and OSM's alike, goes to its nearest station; an OSM
    one is kept only when that station has no DC elevator. Returns
    [(osm id, name, gis_id, point, metres from the station)].
    """

    def nearest(point):
        return min(stations, key=lambda s: distance_m(point, s[2]))

    with_dc = {nearest(p)[1] for _, p in dc_elevators}
    kept = []
    for osm, point, _street in osm_elevators:
        name, gis_id, where = nearest(point)
        metres = distance_m(point, where)
        if metres <= NEAR_STATION_M and gis_id not in with_dc:
            kept.append((osm, name, gis_id, point, metres))
    return kept


def fallback_geojson(rows) -> dict:
    return {
        "type": "FeatureCollection",
        "source": "OpenStreetMap (ODbL); scripts/check_metro_elevators.py --write",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": {"station": name, "station_gis_id": gis_id, "osm": osm},
            }
            for osm, name, gis_id, (lon, lat), _ in rows
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pbf", type=Path, required=True, help="<DATA_ROOT>/extracts/source.osm.pbf"
    )
    parser.add_argument("--write", action="store_true", help=f"also write {FALLBACK_OUT.name}")
    args = parser.parse_args(argv)
    marc = _marc_module()

    def features(name):
        return json.loads((DATA / name).read_text(encoding="utf-8"))["features"]

    metro = features("metro-stations.geojson")
    stations = [(f["properties"]["NAME"], tuple(f["geometry"]["coordinates"])) for f in metro]
    dc = [
        (
            f"{f['properties']['NAME']} ({f['properties']['GIS_ID']})",
            tuple(f["geometry"]["coordinates"]),
        )
        for f in features("metro-entrances.geojson")
        if f["properties"]["DESCRIPTION"] == "Metro Station Elevator"
    ]
    data = marc.read_extract(args.pbf)
    osm = [
        (f"node/{node}", (lon, lat), tags.get("railway") == "subway_entrance")
        for node, (tags, lon, lat) in sorted(data.nodes.items())
        if marc._is_elevator(tags)
    ]
    dc_only, osm_only, near = compare(stations, dc, osm, marc.distance_m)

    def station_of(point):
        return min(stations, key=lambda s: marc.distance_m(point, s[1]))[0]

    with_dc = {station_of(p) for _, p in dc}
    print(f"DC elevators: {len(dc)}, at {len(with_dc)} of {len(stations)} stations")
    street = sum(1 for o in near if o[3])
    print(
        f"OSM elevators within {NEAR_STATION_M:.0f} m of a station: {len(near)},"
        f" {street} on a subway entrance"
    )
    print(f"\nDC elevators with no OSM elevator within {MATCH_M:.0f} m ({len(dc_only)}):")
    for label, station, (lon, lat) in dc_only:
        print(f"  {station}: {label} at {lat:.6f}, {lon:.6f}")
    groups = (
        ("on a subway entrance", [o for o in osm_only if o[3]]),
        (
            "not on a subway entrance, at a station DC gives no elevator",
            [o for o in osm_only if not o[3] and o[1] not in with_dc],
        ),
    )
    for title, rows in groups:
        print(f"\nOSM elevators {title}, no DC one within {MATCH_M:.0f} m ({len(rows)}); not used:")
        for osm_id, station, (lon, lat), _ in rows:
            print(f"  {station}: https://www.openstreetmap.org/{osm_id} at {lat:.6f}, {lon:.6f}")
    rest = [o for o in osm_only if not o[3] and o[1] in with_dc]
    print(
        f"\nOther OSM-only elevators, at stations DC gives elevators (mostly inside): {len(rest)}"
    )
    with_ids = [
        (f["properties"]["NAME"], f["properties"]["GIS_ID"], tuple(f["geometry"]["coordinates"]))
        for f in metro
    ]
    rows = fallback_elevators(with_ids, dc, osm, marc.distance_m)
    print(f"\nOSM elevators used where DC lists none ({len(rows)}):")
    for osm_id, name, _, _, metres in rows:
        print(f"  {name}: {osm_id}, {metres:.0f} m from the station point")
    if args.write:
        text = json.dumps(fallback_geojson(rows), indent=1, ensure_ascii=False) + "\n"
        FALLBACK_OUT.write_text(text, encoding="utf-8")
        print(f"wrote {FALLBACK_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
