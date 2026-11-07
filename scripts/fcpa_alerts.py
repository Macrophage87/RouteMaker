#!/usr/bin/env python3
"""Find the Fairfax County Park Authority's new park alerts, for `routemaker.fcpa`.

The Park Authority posts its trail and bridge closures only as words on its Park Alerts page
(https://www.fairfaxcounty.gov/parks/park-alerts), one list item a park, with no map. The owner,
2026-11-07, chose "Watch Park Alerts, you confirm": this lists what to read, and a closure goes
in `src/core/geodata/fcpa-closures.json` only after the owner confirms it.

    python scripts/fcpa_alerts.py watch [--mark]

reads the page and prints the items not yet in the file's `seen` list: the ones that name a
trail, a bridge or a path first, in full, then a count of the rest. It first prints a `CHECK:`
line for each hand-kept date due a look (`fcpa.check_due`). With `--mark`, once the new items are
read (and any confirmed closure entered), it adds every item now on the page to `seen` and sets
`updated` to today, so the next watch lists only what changed. An item whose words change is
listed again.

The lines for a closure come from `python scripts/ddot_advisories.py lines WAY ...`. Only the
public page is read (no sign-in). docs/OPERATIONS.md, "Fairfax park trail closures".
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from routemaker import fcpa  # noqa: E402

USER_AGENT = "RouteMaker-fcpa-alerts"


def fetch() -> str:
    request = urllib.request.Request(fcpa.PAGE, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as answer:
        return answer.read().decode("utf-8", "replace")


def watch(mark: bool) -> int:
    for line in fcpa.check_due(date.today()):
        print(f"CHECK: {line}")
    items = fcpa.alert_items(fetch())
    if not items:
        print("No items found on the Park Alerts page: has its layout changed?", file=sys.stderr)
        return 1
    data = json.loads(fcpa.GEODATA.read_text())
    seen = set(data.get("seen") or [])
    fresh = fcpa.unseen(items, seen)
    trail = [i for i in fresh if i.trail]
    for item in trail:
        print(f"{item.key} | {item.park or '(no park named)'}\n    {item.text}")
    print(
        f"{len(trail)} new trail items, {len(fresh) - len(trail)} other new items, "
        f"{len(items)} on the page",
        file=sys.stderr,
    )
    if mark:
        data["seen"] = sorted(seen | {i.key for i in items})
        data["updated"] = date.today().isoformat()
        fcpa.GEODATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        print(f"Marked {len(items)} items as read in {fcpa.GEODATA.name}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("watch", help="list park alerts not yet read")
    w.add_argument("--mark", action="store_true", help="then mark every item on the page read")
    args = parser.parse_args()
    return watch(args.mark)


if __name__ == "__main__":
    sys.exit(main())
