#!/usr/bin/env python3
"""Count what the farm-track rule (`pipeline.restricted_areas.track_closures`; owner report
2026-10-21) would close in an extract, read only.

    python scripts/analysis/track_closures_count.py --pbf <DATA_ROOT>/extracts/source.osm.pbf \\
        [--csv OUT.csv]

Reads the extract's tracks, its parks and protected areas, and its route relations, as the
rebuild does (without the owner's overrides or the area rules that judge a track first, so a
track inside a base, a quarry or a golf course counts here as the track rule's). Prints the
ways and miles closed and left open by reason, the closed miles in the Dickerson and
Barnesville box the owner reported, and the longest closed tracks; `--csv` writes every
judged track in the rebuild's report layout.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from pipeline import restricted_areas, route_relations  # noqa: E402
from pipeline.extract import read_ways  # noqa: E402

MILE_M = 1609.344
# The owner's screenshot, 2026-10-21: Dickerson, Barnesville, Comus, Sellman.
DICKERSON_BOX = (-77.50, 39.18, -77.33, 39.30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pbf", required=True)
    parser.add_argument("--csv")
    args = parser.parse_args()

    ways = read_ways(args.pbf, keep=lambda tags: tags.get("highway") == "track")
    areas = restricted_areas.restricted_areas(args.pbf)
    routes = route_relations.read_routes(args.pbf)
    placed = [(w.osm_id, w.tags, w.coordinates) for w in ways]
    found = restricted_areas.track_closures(
        placed,
        areas[restricted_areas.PARK],
        trail_routes={w for w, r in routes.items() if r.bicycle_route or r.hiking},
    )
    coords = {w.osm_id: w.coordinates for w in ways}

    print(f"tracks in the extract: {len(ways)} ({len(found)} judged by the rule)")
    by_why: Counter = Counter()
    metres: Counter = Counter()
    for m in found:
        by_why[m.why] += 1
        metres[m.why] += m.length_m
    for why, n in by_why.most_common():
        print(f"  {why}: {n} ways, {metres[why] / MILE_M:.1f} mi")

    west, south, east, north = DICKERSON_BOX

    def in_box(way_id: int) -> bool:
        pts = coords.get(way_id) or []
        if not pts:
            return False
        lon, lat = pts[len(pts) // 2]
        return west <= lon <= east and south <= lat <= north

    boxed = [m for m in found if in_box(m.way_id)]
    closed_box = [m for m in boxed if m.closed]
    print(
        f"Dickerson/Barnesville box: {len(closed_box)} of {len(boxed)} tracks closed "
        f"({sum(m.length_m for m in closed_box) / MILE_M:.1f} of "
        f"{sum(m.length_m for m in boxed) / MILE_M:.1f} mi)"
    )
    print("longest closed tracks:")
    for m in sorted((m for m in found if m.closed), key=lambda m: -m.length_m)[:15]:
        pts = coords[m.way_id]
        lon, lat = pts[len(pts) // 2]
        print(f"  way {m.way_id}: {m.length_m / MILE_M:.2f} mi at {lat:.5f},{lon:.5f} {m.tags}")
    if args.csv:
        Path(args.csv).write_text(restricted_areas.military_report_csv(found, "place"))
        print(f"wrote {args.csv}")


if __name__ == "__main__":
    main()
