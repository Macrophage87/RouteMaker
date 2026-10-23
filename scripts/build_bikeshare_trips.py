#!/usr/bin/env python3
"""Write `bikeshare-trips.json`, the dock-to-dock trip counts the rebuild routes into the
popular bike corridors (`pipeline.bikeshare_corridors`).

The owner, 2026-10-21, of the zoomed-out map: "Are there any good open source cycling
heatmaps, those corridors should be shown first", then "Actually, use the Cabi heatmap if
you can, and make those streets show more pronounced than other roads.", because what the
map draws boldest today "is basically showing where not to cycle".

The source is Capital Bikeshare's monthly trip history
(<https://capitalbikeshare.com/system-data>, files at
<https://s3.amazonaws.com/capitalbikeshare-data/index.html>), published by Lyft Bikes and
Scooters under the Capital Bikeshare Data License Agreement, the same agreement as Divvy's
(<https://divvybikes.com/data-license-agreement>): a licence to "analyze, copy, modify,
distribute in your product or service and use the Data for any lawful purpose", which
forbids publishing the Data "as a stand-alone dataset" and implying Lyft's endorsement. So
the trip files and this script's output stay out of the repository and out of every public
file: the map carries only each street's corridor class, routed from them.

A trip file holds a trip's docks and their coordinates, never the path ridden. What this
writes, over the months asked for:

- each dock (`stations`: id, longitude, latitude), at the median of the coordinates its
  trips report;
- each pair of docks a trip ran between, either way round (`pairs`: the two docks' indexes
  and the trips), counting only trips between two different docks (a round trip from one
  dock says nothing about a street) and only pairs with at least MIN_PAIR_TRIPS trips over
  the whole period, which drops the one-off trips and any pair a single rider could be
  picked out by;
- `days`, the days the months cover, so the rebuild reads trips a day.

A dockless e-bike trip with no dock at an end is left out: its coordinates are rounded to
two decimals (about 0.7 mi), too coarse to route.

Usage: scripts/build_bikeshare_trips.py --months 202510-202609 --out bikeshare-trips.json
(downloads each month's zip; `--cache DIR` keeps them). Install the file with
`scripts/install_reference_data.py --bikeshare-trips FILE`.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import statistics
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

BUCKET = "https://s3.amazonaws.com/capitalbikeshare-data"
FILE_NAME = "bikeshare-trips.json"
# Trips a pair of docks needs over the whole period to be kept: about one a month a year.
MIN_PAIR_TRIPS = 12


def months_between(spec: str) -> list[str]:
    """`202510-202609` -> ["202510", ..., "202609"]."""
    first, _, last = spec.partition("-")
    last = last or first
    year, month = int(first[:4]), int(first[4:])
    out = []
    while f"{year:04d}{month:02d}" <= last:
        out.append(f"{year:04d}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def month_zip(month: str, cache: Path | None) -> bytes:
    name = f"{month}-capitalbikeshare-tripdata.zip"
    if cache is not None and (cache / name).exists():
        return (cache / name).read_bytes()
    with urllib.request.urlopen(f"{BUCKET}/{name}", timeout=300) as response:
        data = response.read()
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / name).write_bytes(data)
    return data


def trip_rows(data: bytes):
    """The rows of a month's trip CSV (the zip's one CSV outside __MACOSX)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.namelist():
            if member.endswith(".csv") and not member.startswith("__MACOSX"):
                with archive.open(member) as raw:
                    yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def aggregate(rows, min_pair_trips: int = MIN_PAIR_TRIPS):
    """(stations, pairs) from trip rows: [(id, lon, lat)], [(i, j, trips)] with i < j."""
    pairs: Counter[tuple[str, str]] = Counter()
    seen: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for row in rows:
        start, end = (
            (row.get("start_station_id") or "").strip(),
            (row.get("end_station_id") or "").strip(),
        )
        if not start or not end or start == end:
            continue
        for station, lon, lat in (
            (start, row.get("start_lng"), row.get("start_lat")),
            (end, row.get("end_lng"), row.get("end_lat")),
        ):
            try:
                lons, lats = seen[station]
                # A sample is enough for the median; a busy dock reports thousands.
                if len(lons) < 200:
                    lons.append(float(lon))
                    lats.append(float(lat))
            except (TypeError, ValueError):
                pass
        pairs[(start, end) if start < end else (end, start)] += 1
    kept = {pair: trips for pair, trips in pairs.items() if trips >= min_pair_trips}
    used = sorted({station for pair in kept for station in pair if seen[station][0]})
    index = {station: i for i, station in enumerate(used)}
    stations = [
        (
            station,
            round(statistics.median(seen[station][0]), 6),
            round(statistics.median(seen[station][1]), 6),
        )
        for station in used
    ]
    out = sorted(
        (index[a], index[b], trips) for (a, b), trips in kept.items() if a in index and b in index
    )
    return stations, out


def days_in(months: list[str]) -> int:
    return sum(calendar.monthrange(int(m[:4]), int(m[4:]))[1] for m in months)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--months", required=True, help="YYYYMM-YYYYMM, inclusive")
    parser.add_argument("--out", type=Path, default=Path(FILE_NAME))
    parser.add_argument("--cache", type=Path, default=None, help="keep the monthly zips here")
    parser.add_argument("--min-pair-trips", type=int, default=MIN_PAIR_TRIPS)
    args = parser.parse_args(argv)
    months = months_between(args.months)

    def rows():
        for month in months:
            print(f"reading {month}", file=sys.stderr)
            yield from trip_rows(month_zip(month, args.cache))

    stations, pairs = aggregate(rows(), args.min_pair_trips)
    args.out.write_text(
        json.dumps(
            {
                "source": "Capital Bikeshare trip history (Lyft Bikes and Scooters), "
                "Capital Bikeshare Data License Agreement",
                "months": [months[0], months[-1]],
                "days": days_in(months),
                "min_pair_trips": args.min_pair_trips,
                "stations": stations,
                "pairs": pairs,
            },
            separators=(",", ":"),
        )
    )
    total = sum(trips for _, _, trips in pairs)
    print(
        f"{len(stations)} docks, {len(pairs)} pairs, {total} trips "
        f"({total / days_in(months):.0f} a day) -> {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
