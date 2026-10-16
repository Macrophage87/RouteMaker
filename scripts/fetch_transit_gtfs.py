#!/usr/bin/env python3
"""Download the region's static GTFS feeds on the host, once per data refresh.

TRANSIT-ASSIST. One zip per system in src/core/transitdata/systems.json: WMATA Metro and
Metrobus, MARC, Light RailLink, Metro SubwayLink and VRE (docs/SOURCES.md has each one's terms).
WMATA's feeds need a developer key (WMATA Transit Data Terms of Use,
<https://developer.wmata.com/license>; register at <https://developer.wmata.com/signup/>): it is
read from the environment variable the system names (`WMATA_API_KEY`) and sent only as WMATA's
`api_key` request header; it is never printed, logged or written. MDOT MTA's and VRE's feeds need
none.

    export WMATA_API_KEY=...   # in the shell, from the operator's own records
    python3 scripts/fetch_transit_gtfs.py --out-dir ~/rmdata/transit

writes each system's zip under the name systems.json gives it, and a README beside them with
the URL, size, sha256 and retrieval time of each. Then `scripts/build_transit_schedule.py`
compacts them into the file the API reads (docs/OPERATIONS.md, "Transit schedule"). The zips
are the agencies' data: they stay on the host and are never committed.

Standard library only, so it runs on the host without the virtualenv. The cloud proxy cannot
reach the agencies' servers, which is why this runs on the home PC.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

SYSTEMS = Path(__file__).resolve().parents[1] / "src" / "core" / "transitdata" / "systems.json"
USER_AGENT = "RouteMaker-data-fetch/1.0 (bike route planner)"
RETRIES = 3
REQUIRED = {"stops.txt", "trips.txt", "stop_times.txt", "routes.txt"}


def fetch(url: str, headers: dict[str, str]) -> bytes:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            request = urllib.request.Request(url, headers={**headers, "User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 - fixed https URLs
                return response.read()
        except Exception as error:  # noqa: BLE001 - retried, then raised
            last = error
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url}: {type(last).__name__}")  # the error text could echo a header


def main(argv: list[str] | None = None) -> int:
    systems = json.loads(SYSTEMS.read_text())["systems"]
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--only",
        choices=sorted(s["id"] for s in systems),
        action="append",
        help="fetch only this system (repeatable)",
    )
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Transit static GTFS",
        "",
        "| System | File | URL | Bytes | sha256 | Retrieved (UTC) |",
        "|---|---|---|---|---|---|",
    ]
    # The README's rows from earlier runs, by file: a feed not fetched this time (--only, a
    # failure) keeps the row that describes the zip still on disk.
    rows = readme_rows(args.out_dir / "README.md")
    failed = 0
    for system in systems:
        if args.only and system["id"] not in args.only:
            continue
        feed = system["feed"]
        headers = {}
        if feed.get("key_env"):
            key = os.environ.get(feed["key_env"], "").strip()
            if not key:
                print(
                    f"{system['id']}: set {feed['key_env']} in the shell first; skipped",
                    file=sys.stderr,
                )
                failed += 1
                continue
            headers[feed["key_header"]] = key
        try:
            body = fetch(feed["url"], headers)
        except RuntimeError as error:
            print(f"{system['id']}: {error}", file=sys.stderr)
            failed += 1
            continue
        target = args.out_dir / feed["file"]
        # Written beside the last good zip and checked there; only a zip that passes replaces
        # it, so an error page or a truncated body never takes its place (review pipeline-2).
        part = target.with_name(target.name + ".part")
        part.write_bytes(body)
        try:
            with zipfile.ZipFile(part) as found:
                missing = REQUIRED - set(found.namelist())
        except zipfile.BadZipFile:
            missing = None
        if missing is None or missing:
            part.unlink()
            kept = "; the last good copy is kept" if target.exists() else ""
            why = "not a zip (an error page?)" if missing is None else f"missing {sorted(missing)}"
            print(f"{feed['file']}: {why}{kept}; try again", file=sys.stderr)
            failed += 1
            continue
        os.replace(part, target)
        digest = hashlib.sha256(body).hexdigest()
        when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        rows[feed["file"]] = (
            f"| {system['name']} | `{feed['file']}` | {feed['url']} | {len(body):,}"
            f" | `{digest}` | {when} |"
        )
        print(f"{feed['file']}: {len(body):,} bytes, sha256 {digest}")
    order = [s["feed"]["file"] for s in systems]
    for file in sorted(rows, key=lambda f: (order.index(f) if f in order else len(order), f)):
        if (args.out_dir / file).exists():
            lines.append(rows[file])
    lines += [
        "",
        "Terms: docs/SOURCES.md, one entry per system. The agencies' data: kept on this host,",
        "never committed or published as a dataset.",
        "",
    ]
    (args.out_dir / "README.md").write_text("\n".join(lines))
    return 3 if failed else 0


def readme_rows(path: Path) -> dict[str, str]:
    """The table rows of an earlier README, by the file each names."""
    try:
        text = path.read_text()
    except OSError:
        return {}
    found = {}
    for line in text.splitlines():
        match = re.match(r"^\| [^|]* \| `([^`]+)` \|", line)
        if match:
            found[match.group(1)] = line
    return found


if __name__ == "__main__":
    sys.exit(main())
