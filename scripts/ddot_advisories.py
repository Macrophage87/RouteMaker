#!/usr/bin/env python3
"""Find DDOT's new project traffic advisories, and draw a closure's lines.

For `routemaker.ddot_advisories`.

DDOT posts each big project's closures as press releases on the project's ArcGIS Hub site, on a
page titled "Traffic Advisories" or "Construction Updates" (the owner, 2026-10-25: "They tend
to have fairly up to date closures"). There is no feed and no geometry, so the closures in
`src/core/geodata/ddot-advisories.json` are read by a person. This finds what to read:

    python scripts/ddot_advisories.py watch [--days 45]

searches ArcGIS Online for the District's Hub pages with those titles, and DDOT's Hub sites
themselves (a site's home often shows its newest advisory, and some sites' advisories pages are
not public: the Theodore Roosevelt Bridge's), changed in the last `--days` days (DC GIS's two
organisations, `ORGS`), reads each one's dated entries
(`ddot_advisories.page_entries`) and prints those whose link is not yet in the file's `seen`
list: the day, the project, the title, the advisory's link and the page's. Read each one; add
a closure for what it closes to bicycles; add its link to `seen` either way. It first prints a
`CHECK:` line for each hand-kept date due a look: a guessed last day (`end_estimated`) within
30 days, a file (this one or the Purple Line's) not updated in 45 days, and the deer schedules'
assumed season or last night coming up.

    python scripts/ddot_advisories.py lines WAY [WAY ...]

prints the OpenStreetMap ways' lines (OSM API, ODbL; rounded to 1e-5 degrees), ready for a
closure's `lines`.

Only public pages are read (no sign-in). docs/OPERATIONS.md, "DDOT project advisories".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from routemaker import ddot_advisories, deer_closures, purple_line  # noqa: E402

ARCGIS = "https://www.arcgis.com/sharing/rest"
OSM_API = "https://api.openstreetmap.org/api/0.6"
# DC GIS's ArcGIS Online organisations: DDOT's Hub sites are in the first, many of their pages
# in the second.
ORGS = ("neT9SoYxizqTHZPH", "UmGCPY8AKRzyOzJX")
TITLES = re.compile(r"advisor|construction update", re.I)
USER_AGENT = "RouteMaker-ddot-advisories"


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as answer:
        return answer.read()


def _json(url: str, **params) -> dict:
    return json.loads(_get(f"{url}?{urllib.parse.urlencode({**params, 'f': 'json'})}"))


def _search(q: str, since: date) -> list[dict]:
    """The items `q` finds, changed since `since`, newest first."""
    found, start = [], 1
    while start > 0:
        answer = _json(
            f"{ARCGIS}/search", q=q, num=100, start=start, sortField="modified", sortOrder="desc"
        )
        for item in answer.get("results") or []:
            if datetime.fromtimestamp(item["modified"] / 1000, UTC).date() < since:
                return found
            found.append(item)
        start = answer.get("nextStart") or -1
    return found


def pages(since: date) -> list[dict]:
    """The Hub pages titled as advisories or construction updates, and DDOT's Hub sites
    themselves (a site's home page often carries its newest advisory, and some sites' own
    advisories pages are not public), changed since `since`."""
    found = []
    for org in ORGS:
        q = f'orgid:{org} AND type:"Hub Page" AND (advisory OR advisories OR construction)'
        found += [i for i in _search(q, since) if TITLES.search(i.get("title") or "")]
        q = f'orgid:{org} AND type:"Hub Site Application"'
        found += [i for i in _search(q, since) if "ddot" in (i.get("url") or "").lower()]
    return found


def site_of(page: dict) -> tuple[str, str]:
    """The page's project name and its address on the project's site."""
    sites = (page.get("values") or {}).get("sites") or []
    if not sites:
        return "", ""
    site = _json(f"{ARCGIS}/content/items/{sites[0]['id']}")
    return sites[0].get("title") or site.get("title") or "", site.get("url") or ""


def reminders(today: date) -> list[str]:
    """The hand-kept closures' dates to check: a guessed last day close by, a file not read for
    a while (`ddot_advisories.reminders`), and the deer schedules' assumed season and end."""
    return [
        *ddot_advisories.check_due(today),
        *purple_line.check_due(today),
        *deer_closures.check_due(today),
    ]


def watch(days: int) -> int:
    for line in reminders(date.today()):
        print(f"CHECK: {line}")
    data = json.loads(ddot_advisories.GEODATA.read_text())
    seen = set(data.get("seen") or [])
    since = date.today() - timedelta(days=days)
    new = 0
    for item in pages(since):
        page = _json(f"{ARCGIS}/content/items/{item['id']}/data")
        if item.get("type") == "Hub Site Application":
            project, address = item.get("title") or "", item.get("url") or ""
        else:
            project, site = site_of(page)
            address = f"{site}/pages/{item['id']}" if site else ""
        for entry in ddot_advisories.unseen(ddot_advisories.page_entries(page), seen, since):
            new += 1
            day = entry.day.isoformat() if entry.day else "undated"
            print(f"{day} | {project} | {entry.title}")
            print(f"    advisory: {entry.link}\n    page: {address}")
        time.sleep(0.5)
    print(f"{new} new advisories since {since.isoformat()}", file=sys.stderr)
    return 0


def lines(ways: list[int]) -> int:
    out = []
    for way in ways:
        answer = json.loads(_get(f"{OSM_API}/way/{way}/full.json"))
        nodes = {e["id"]: e for e in answer["elements"] if e["type"] == "node"}
        (found,) = [e for e in answer["elements"] if e["type"] == "way"]
        out.append([[round(nodes[n]["lon"], 5), round(nodes[n]["lat"], 5)] for n in found["nodes"]])
        time.sleep(1)
    print(json.dumps({"ways": ways, "lines": out}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("watch", help="list advisories not yet read")
    w.add_argument("--days", type=int, default=45)
    ln = sub.add_parser("lines", help="print OSM ways' lines for a closure")
    ln.add_argument("ways", type=int, nargs="+")
    args = parser.parse_args()
    if args.command == "watch":
        return watch(args.days)
    return lines(args.ways)


if __name__ == "__main__":
    sys.exit(main())
