#!/usr/bin/env python3
"""Refresh every snapshot built from the OSM extract, in one step, after each map rebuild.

Backlog item "Data that says how old it is" (2026-11-13): the places riders act on in the moment
(Find food, Places to see, water and restrooms, repair stands, racks, trail mile markers), the
restricted sites and their gates, and the barrier list Cargo and Tandem plan round are committed
files built from the extract by hand, and nothing in the rebuild refreshed them, so they drifted
weeks behind the map. This runs each builder against the rebuild's own extract, then writes
`frontend/src/amenity-data/as-of.json`, the dates Settings' About line shows ("Places and racks
from Nov 10, 2026"), and prints a short change report (each file's count before and after, how
many added and removed) for the rebuild's thread. It reads only the extract (and, with --cities,
DDOT's and BCDOT's rack layers); it writes only the files below, in this checkout. Check the
report, then commit the files: the front-end files reach riders with the next front-end build,
`barriers.json` and `restricted-sites.json` reach the router with the next api image (a hand
ship). docs/OPERATIONS.md, "Refreshing the places after a map rebuild".

Run on the build host with pyosmium (the builders need it), under the heavy-job lock: each
builder reads the whole extract in turn, one at a time.

    flock <the host's heavy.lock> .venv311/bin/python scripts/refresh_places.py \\
        --pbf <DATA_ROOT>/extracts/source.osm.pbf [--cities]

--cities fetches DDOT's and BCDOT's racks again (network); without it the racks the file already
holds from the cities are kept, with their old date. --extract-date names the extract's day when
the file's modified time is not it (a copy that lost its time); by default it is the day the file
was last written, which is the day the rebuild downloaded and clipped it (`pipeline.source`).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
AMENITY = REPO / "frontend" / "src" / "amenity-data"
AS_OF = AMENITY / "as-of.json"
BARRIERS = REPO / "src" / "core" / "geodata" / "barriers.json"

# A refreshed file with fewer than this share of the items it had is called out at the top of the
# report: a builder that read a truncated or wrong extract writes a small file, not an error. Our
# default, unmeasured (a real refresh moves a file by a few percent).
SHRINK_ALARM = 0.8


@dataclass(frozen=True)
class Snapshot:
    """One committed file and the builder that writes it."""

    name: str
    path: Path
    script: str
    # The builder's arguments after the script, given the extract and its date.
    args: Callable[[Path, str], list[str]]
    # The file's items as ids, or as positions where the file keeps no id.
    items: Callable[[dict], list[str]]


def _ids(key: str) -> Callable[[dict], list[str]]:
    return lambda doc: [str(p.get("id")) for p in doc.get(key, [])]


def _trail_items(doc: dict) -> list[str]:
    return [f"trail {t.get('n')} {t.get('s')}" for t in doc.get("trails", [])] + [
        str(m.get("id")) for m in doc.get("markers", [])
    ]


def _feature_items(doc: dict) -> list[str]:
    """A GeoJSON file's features by what each is (a site's or a gate's id, its kind and name)."""
    return [json.dumps(f.get("properties", {}), sort_keys=True) for f in doc.get("features", [])]


def _barrier_items(doc: dict) -> list[str]:
    return [f"{b[0]},{b[1]}" for b in doc.get("barriers", [])]


SNAPSHOTS: tuple[Snapshot, ...] = (
    Snapshot(
        "water-restrooms",
        AMENITY / "water-restrooms.json",
        "build_water_restrooms.py",
        lambda pbf, _: ["--pbf", str(pbf)],
        _ids("points"),
    ),
    Snapshot(
        "food",
        AMENITY / "food.json",
        "build_food.py",
        lambda pbf, _: ["--pbf", str(pbf)],
        _ids("points"),
    ),
    Snapshot(
        "places",
        AMENITY / "places.json",
        "build_places.py",
        lambda pbf, _: ["--pbf", str(pbf)],
        _ids("points"),
    ),
    Snapshot(
        "trail-miles",
        AMENITY / "trail-miles.json",
        "build_trail_miles.py",
        lambda pbf, _: ["--pbf", str(pbf)],
        _trail_items,
    ),
    Snapshot(
        "bike-parking",
        AMENITY / "bike-parking.json",
        "build_bike_parking.py",
        lambda pbf, _: ["--pbf", str(pbf)],
        _ids("points"),
    ),
    Snapshot(
        "restricted-sites",
        REPO / "frontend" / "src" / "restricted-data" / "restricted-sites.json",
        "build_restricted_sites.py",
        lambda pbf, _: ["--pbf", str(pbf)],
        _feature_items,
    ),
    Snapshot(
        "barriers",
        BARRIERS,
        "barrier_census.py",
        # Its coverage report goes in the home folder, for the rebuild's notes; never committed.
        lambda pbf, day: [
            "--pbf",
            str(pbf),
            "--json",
            str(BARRIERS),
            "--built",
            day,
            "--out",
            str(Path.home() / f"barrier-census-{day}.md"),
        ],
        _barrier_items,
    ),
)


def read_items(snapshot: Snapshot) -> list[str]:
    if not snapshot.path.is_file():
        return []
    return snapshot.items(json.loads(snapshot.path.read_text(encoding="utf-8")))


def change_line(name: str, before: Sequence[str], after: Sequence[str]) -> str:
    """`food: 15,663 -> 15,702 (+120, -81)`, and a warning when the file shrank past the alarm."""
    old, new = set(before), set(after)
    line = f"{name}: {len(before):,} -> {len(after):,} (+{len(new - old):,}, -{len(old - new):,})"
    if before and len(after) < SHRINK_ALARM * len(before):
        line += f"  CHECK: under {SHRINK_ALARM:.0%} of before; do not commit until it is explained"
    return line


def extract_day(pbf: Path, given: str | None) -> str:
    if given:
        return date.fromisoformat(given).isoformat()
    return datetime.fromtimestamp(pbf.stat().st_mtime, UTC).date().isoformat()


def read_as_of(path: Path = AS_OF) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def as_of_document(previous: dict, day: str, cities: str | None) -> dict:
    """The dates file: every snapshot's extract day, and the day the cities' racks were fetched."""
    return {
        "note": (
            "Written by scripts/refresh_places.py: the day of the OpenStreetMap extract each "
            "snapshot was built from, and the day DDOT's and BCDOT's racks were last fetched."
        ),
        "extract": {s.name: day for s in SNAPSHOTS},
        "cities": cities or previous.get("cities", ""),
    }


def write_as_of(doc: dict, path: Path = AS_OF) -> None:
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def run_builder(python: str, snapshot: Snapshot, pbf: Path, day: str, extra: list[str]) -> None:
    command = [python, str(SCRIPTS / snapshot.script), *snapshot.args(pbf, day), *extra]
    print(f"refresh: {snapshot.name}: {' '.join(command[1:])}", flush=True)
    subprocess.run(command, check=True, cwd=REPO)


def main(argv: list[str] | None = None, run: Callable[..., None] = run_builder) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pbf", type=Path, required=True, help="<DATA_ROOT>/extracts/source.osm.pbf"
    )
    parser.add_argument(
        "--cities", action="store_true", help="fetch DDOT's and BCDOT's racks again (network)"
    )
    parser.add_argument("--extract-date", help="the extract's day, YYYY-MM-DD (default: its mtime)")
    parser.add_argument("--python", default=sys.executable, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.pbf.is_file():
        parser.error(f"no extract at {args.pbf}")
    day = extract_day(args.pbf, args.extract_date)

    lines = []
    done: list[Path] = []
    for snapshot in SNAPSHOTS:
        before = read_items(snapshot)
        extra = ["--ddot", "--baltimore"] if snapshot.name == "bike-parking" and args.cities else []
        try:
            run(args.python, snapshot, args.pbf, day, extra)
        except subprocess.CalledProcessError:
            # Its own file may be half written too, so it is named with the ones already done.
            changed = " ".join(os.path.relpath(p, REPO) for p in [*done, snapshot.path])
            print(
                f"refresh: {snapshot.name} failed; as-of.json not written. "
                f"Put back: git restore {changed}"
            )
            raise
        done.append(snapshot.path)
        lines.append(change_line(snapshot.name, before, read_items(snapshot)))

    today = datetime.now(UTC).date().isoformat()
    write_as_of(as_of_document(read_as_of(AS_OF), day, today if args.cities else None), AS_OF)
    print(f"\nRefreshed from the {day} extract" + (", racks fetched today" if args.cities else ""))
    for line in lines:
        print(f"- {line}")
    print("Check the counts, then commit the files and frontend/src/amenity-data/as-of.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
