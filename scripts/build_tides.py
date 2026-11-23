#!/usr/bin/env python3
"""Low tides for the beach path (the owner, 2026-11-23: riding the beach "generally only
adviseable in low tide below the high tide lines"; "build it for the next map release").

Reads NOAA CO-OPS tide predictions (high and low times, MLLW datum, feet; US Government
work, public domain) for the Gulf-facing stations along the Southwest Florida beaches and
writes frontend/src/tide-data/tides.json: each station's place and its predicted LOW
tides from today for `--days` days. The front end loads it only when a route uses a
beach path (lib/tides.ts) and names the nearest station's low tides that day.

    python3 scripts/build_tides.py [--days 400] [--start YYYY-MM-DD]

Predictions are astronomical, so a year's file stays right; re-run it with every map
rebuild (docs/OPERATIONS.md, "After every map rebuild").
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
OUT = Path(__file__).resolve().parents[1] / "frontend/src/tide-data/tides.json"

# Stations on the open Gulf, beside the beaches (NOAA's station list, 2026-11-23); bay and
# river stations are left out, their tides run late against the beach's.
STATIONS: tuple[tuple[str, str, float, float], ...] = (
    ("8726034", "Siesta Key, Big Sarasota Pass", -82.565, 27.284),
    ("8725858", "Venice", -82.453, 27.072),
    ("8725577", "Port Boca Grande", -82.258, 26.720),
    ("8725383", "Captiva Island (outside)", -82.183, 26.478),
    ("8725351", "Estero Island", -81.918, 26.438),
    ("8725283", "Little Hickory Island", -81.855, 26.353),
    ("8725110", "Naples (outer coast)", -81.808, 26.132),
    ("8724967", "Marco Island, Caxambas Pass", -81.728, 25.908),
)

Fetch = Callable[[str], dict]


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "routemaker-tides"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def query(station: str, begin: date, end: date) -> str:
    return API + "?" + urllib.parse.urlencode(
        {
            "product": "predictions",
            "application": "routemaker",
            "begin_date": begin.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "datum": "MLLW",
            "station": station,
            "time_zone": "gmt",
            "interval": "hilo",
            "units": "english",
            "format": "json",
        }
    )


def lows(body: dict) -> list[list[int]]:
    """A NOAA hilo answer's low tides as [minutes since 1970 UTC, height in tenths of a foot]."""
    if "predictions" not in body:
        raise ValueError(f"NOAA answered without predictions: {body.get('error', body)}")
    out = []
    for row in body["predictions"]:
        if row.get("type") != "L":
            continue
        when = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        out.append([int(when.timestamp() // 60), round(float(row["v"]) * 10)])
    return out


def build(start: date, days: int, fetch: Fetch = fetch_json) -> dict:
    stations = []
    for station, name, lon, lat in STATIONS:
        found: list[list[int]] = []
        # NOAA serves at most a year of hilo predictions a request.
        begin = start
        end = start + timedelta(days=days)
        while begin < end:
            stop = min(begin + timedelta(days=364), end)
            found += lows(fetch(query(station, begin, stop)))
            begin = stop + timedelta(days=1)
        stations.append({"id": station, "name": name, "lon": lon, "lat": lat, "lows": found})
    return {
        "source": "NOAA CO-OPS tide predictions (public domain)",
        "datum": "MLLW",
        "units": "ft/10",
        "from": start.isoformat(),
        "to": (start + timedelta(days=days)).isoformat(),
        "stations": stations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    data = build(args.start or datetime.now(UTC).date(), args.days)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    counts = ", ".join(f"{s['id']} {len(s['lows'])}" for s in data["stations"])
    print(f"wrote {args.out}: low tides {counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
