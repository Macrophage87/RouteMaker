#!/usr/bin/env python3
"""Where a traffic count on the map came from: the agency lines that carry it.

    python scripts/analysis/trace_count.py --volume DATA/reference/volume.json \\
        --aadt 4201 [--near -77.36,39.21 --radius-mi 3] [--segments FILE.csv]

Read-only. The owner, 2026-10-12: West Old Baltimore Rd shows 4,201 vehicles a
day along stretches no counter is near, as if the count were copied along the
road by its name. Nothing in the rebuild copies a count by name:
`pipeline.conflation.conflate` attaches an agency line only to the OSM ways
that lie along it (bearing, separation, overlap), `pipeline.aadt_smoothing`
only lowers a count to its street's median, and
`share_with_carriageways` reaches only the other half of a divided road. So a
count that runs on for miles most likely runs on in the agency's own data: one
long count line (MDOT SHA publishes a segment per count station, often miles
long) that the conflation followed faithfully.

This script answers that on the PC, from the installed `volume.json` the
rebuild read:

- every agency line with the given AADT (or near the given point), with its
  length, its two ends, its publisher, its year and its feature id;
- with `--segments`, each way that took the count, and how far it lies from the
  nearest of those lines. A way within the conflation's reach of a line that
  long is the agency's segment, not a copy. A way far from every line would be
  the copying bug, and worth a report with its way id.

The `--segments` CSV comes from the live table (read-only):

    \\copy (SELECT osm_way_id, name, volume_aadt, volume_source,
            ST_AsText(geom) AS wkt FROM segment WHERE volume_aadt = 4201)
          TO 'count-ways.csv' WITH CSV HEADER

US units first, metric in brackets.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from routemaker.geo import Point, haversine  # noqa: E402

M_PER_MI = 1609.344
FT_PER_M = 3.28084
# `pipeline.conflation.MAX_SEPARATION_M`: beyond this a line and a way are not
# the same road, so a way this far from every carrying line did not get the
# count from conflation's geometry.
REACH_M = 20.0


@dataclass(frozen=True)
class CountLine:
    feature_id: str
    aadt: int
    agency: str | None
    source: str
    year: int | None
    coordinates: tuple[tuple[float, float], ...]

    @property
    def length_m(self) -> float:
        return sum(
            haversine(Point(lon=a[0], lat=a[1]), Point(lon=b[0], lat=b[1]))
            for a, b in zip(self.coordinates, self.coordinates[1:], strict=False)
        )


def load_volume(path: Path) -> list[CountLine]:
    return [
        CountLine(
            feature_id=str(row["id"]),
            aadt=int(row["aadt"]),
            agency=row.get("agency"),
            source=row["source"],
            year=row.get("year"),
            coordinates=tuple((float(c[0]), float(c[1])) for c in row["coordinates"]),
        )
        for row in json.loads(path.read_text())
    ]


def _to_xy(lon: float, lat: float, origin: tuple[float, float]) -> tuple[float, float]:
    """Metres east and north of `origin`: plenty for distances of a few miles."""
    north = haversine(Point(lon=origin[0], lat=origin[1]), Point(lon=origin[0], lat=lat))
    east = haversine(Point(lon=origin[0], lat=lat), Point(lon=lon, lat=lat))
    return (east if lon >= origin[0] else -east, north if lat >= origin[1] else -north)


def distance_to_line_m(point: tuple[float, float], line: Sequence[tuple[float, float]]) -> float:
    """Shortest distance in metres from a lon/lat point to a lon/lat polyline."""
    px, py = 0.0, 0.0
    xy = [_to_xy(lon, lat, point) for lon, lat in line]
    if len(xy) == 1:
        return (xy[0][0] ** 2 + xy[0][1] ** 2) ** 0.5
    best = float("inf")
    for (ax, ay), (bx, by) in zip(xy, xy[1:], strict=False):
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        t = 0.0 if span == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span))
        cx, cy = ax + t * dx, ay + t * dy
        best = min(best, ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5)
    return best


def select(
    lines: Iterable[CountLine],
    aadt: int | None = None,
    near: tuple[float, float] | None = None,
    radius_m: float = 3 * M_PER_MI,
) -> list[CountLine]:
    """The lines with this AADT, and/or within `radius_m` of `near`."""
    chosen = []
    for line in lines:
        if aadt is not None and line.aadt != aadt:
            continue
        if near is not None and distance_to_line_m(near, line.coordinates) > radius_m:
            continue
        chosen.append(line)
    return sorted(chosen, key=lambda line: (-line.length_m, line.feature_id))


def parse_wkt_linestring(wkt: str) -> list[tuple[float, float]]:
    """The vertices of a LINESTRING or MULTILINESTRING, in order."""
    body = wkt[wkt.index("(") :].replace("(", " ").replace(")", " ")
    points = []
    for pair in body.split(","):
        parts = pair.split()
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    return points


@dataclass(frozen=True)
class WayCheck:
    osm_way_id: int
    name: str
    volume_aadt: int | None
    nearest_feature: str | None
    gap_m: float

    @property
    def along_a_line(self) -> bool:
        return self.gap_m <= REACH_M


def check_ways(rows: Iterable[dict], lines: Sequence[CountLine]) -> list[WayCheck]:
    """How far each way's midpoint vertex lies from the nearest carrying line."""
    checks = []
    for row in rows:
        vertices = parse_wkt_linestring(row["wkt"])
        middle = vertices[len(vertices) // 2]
        nearest, gap = None, float("inf")
        for line in lines:
            d = distance_to_line_m(middle, line.coordinates)
            if d < gap:
                nearest, gap = line.feature_id, d
        aadt = row.get("volume_aadt")
        checks.append(
            WayCheck(
                osm_way_id=int(row["osm_way_id"]),
                name=row.get("name") or "",
                volume_aadt=int(aadt) if aadt not in (None, "") else None,
                nearest_feature=nearest,
                gap_m=gap,
            )
        )
    return checks


def _mi(metres: float) -> str:
    return f"{metres / M_PER_MI:.2f} mi ({metres / 1000:.2f} km)"


def _ft(metres: float) -> str:
    if metres == float("inf"):
        return "no line"
    if metres >= M_PER_MI / 4:
        return _mi(metres)
    return f"{metres * FT_PER_M:,.0f} ft ({metres:,.0f} m)"


def report(lines: Sequence[CountLine], checks: Sequence[WayCheck] = ()) -> str:
    out = [f"{len(lines)} agency count line(s)", ""]
    for line in lines:
        start, end = line.coordinates[0], line.coordinates[-1]
        out.append(
            f"- {line.feature_id}: {line.aadt:,} a day, {line.agency or 'agency unknown'} "
            f"({line.source}), {line.year or 'year unknown'}, {_mi(line.length_m)}, "
            f"from {start[1]:.5f}, {start[0]:.5f} to {end[1]:.5f}, {end[0]:.5f}"
        )
    if checks:
        far = [c for c in checks if not c.along_a_line]
        out += [
            "",
            f"{len(checks)} way(s) carry the count; {len(far)} lie beyond "
            f"{_ft(REACH_M)} of every line above",
            "",
        ]
        for c in sorted(checks, key=lambda c: (c.along_a_line, -c.gap_m)):
            verdict = "along " + str(c.nearest_feature) if c.along_a_line else "FAR from every line"
            out.append(f"- way {c.osm_way_id} {c.name}: {_ft(c.gap_m)}, {verdict}")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--volume", type=Path, required=True, help="the installed volume.json")
    parser.add_argument("--aadt", type=int, help="the count to trace, e.g. 4201")
    parser.add_argument("--near", help="lon,lat: lines within --radius-mi of this point")
    parser.add_argument("--radius-mi", type=float, default=3.0)
    parser.add_argument("--segments", type=Path, help="CSV of the ways that carry the count")
    args = parser.parse_args(argv)
    if args.aadt is None and args.near is None:
        parser.error("give --aadt, --near or both")
    near = tuple(float(v) for v in args.near.split(",")) if args.near else None
    lines = select(load_volume(args.volume), args.aadt, near, args.radius_mi * M_PER_MI)
    checks: list[WayCheck] = []
    if args.segments:
        with args.segments.open(newline="") as handle:
            checks = check_ways(csv.DictReader(handle), lines)
    sys.stdout.write(report(lines, checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
