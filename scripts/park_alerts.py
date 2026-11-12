#!/usr/bin/env python3
"""Find the park agencies' new trail alerts, and draw a C&O closure by milepost.

For `routemaker.park_alerts` (v0.26.0): NOVA Parks (the W&OD), NPS's C&O Canal conditions page
and Anne Arundel County's closings list. Each posts its trail closures only as words, so a
closure goes in `src/core/geodata/park-closures.json` only after a person reads it and the owner's
rule for these allows it (docs/OPERATIONS.md, "Park agency trail closures").

    python scripts/park_alerts.py watch [--agency nova|choh|aacounty] [--mark]

reads each agency's page and prints the items not yet in the file's `seen` list: the ones that
name a trail, towpath, bridge, path or detour first, in full, then the rest one line each. It
first prints a `CHECK:` line for each hand-kept date due a look (`park_alerts.check_due`). It
exits 1 where a page that answered gave no items at all (its layout has likely changed), after
reading the others. With `--mark`, once the new items are read (and any closure entered), it adds
every item now on the pages read to `seen` and sets `updated` to today.

    python scripts/park_alerts.py towpath FIRST_MILE [LAST_MILE]

prints the C&O towpath's lines between two mileposts (`park_alerts.towpath_lines`, from the trail
mile lines), ready for a closure's `lines`, and how much of the stretch they cover. Where they do
not cover it all, draw the rest from the OpenStreetMap ways (`python scripts/ddot_advisories.py
lines WAY ...`).

Only public pages are read (no sign-in).
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

from routemaker import park_alerts as pa  # noqa: E402

USER_AGENT = "RouteMaker-park-alerts"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as answer:
        return answer.read().decode("utf-8", "replace")


def items_of(agency: str, get=fetch) -> list[pa.Item]:
    """An agency's items as its page has them now."""
    if agency == pa.NOVA.key:
        found = []
        for url in pa.nova_links(get(pa.NOVA.page)):
            item = pa.nova_item(url, get(url))
            if item is not None:
                found.append(item)
        return found
    if agency == pa.CHOH.key:
        return pa.choh_items(get(pa.CHOH.page))
    return pa.aacounty_items(get(pa.AACOUNTY.page))


def _show(item: pa.Item) -> str:
    miles = f" [MP {item.miles[0]:g}-{item.miles[1]:g}]" if item.miles else ""
    return f"{item.key} | {item.place}{miles} | {item.link}\n    {item.text}"


def watch(agencies: list[str], mark: bool, get=fetch) -> int:
    for line in pa.check_due(date.today()):
        print(f"CHECK: {line}")
    data = json.loads(pa.GEODATA.read_text())
    seen = {k: set(v) for k, v in (data.get("seen") or {}).items()}
    status = 0
    read: dict[str, list[pa.Item]] = {}
    for agency in agencies:
        name = pa.AGENCIES[agency].name
        try:
            items = items_of(agency, get)
        except OSError as error:
            print(f"{name}: could not be read ({type(error).__name__})", file=sys.stderr)
            status = 1
            continue
        if not items and agency != pa.NOVA.key:
            # NOVA may have no alerts; the C&O page always lists places, Anne Arundel's list
            # has had entries at every read so far.
            print(f"{name}: no items found: has its page's layout changed?", file=sys.stderr)
            status = 1
            continue
        read[agency] = items
        fresh = pa.unseen(items, seen.get(agency, set()))
        trail = [i for i in fresh if i.trail]
        print(f"== {name}: {len(trail)} new trail items, {len(fresh) - len(trail)} other new")
        for item in trail:
            print(_show(item))
        for item in fresh[len(trail) :]:
            print(f"  (other) {item.key} | {item.place} | {item.text[:80]}")
    if mark and read:
        for agency, items in read.items():
            seen[agency] = seen.get(agency, set()) | {i.key for i in items}
        data["seen"] = {k: sorted(v) for k, v in sorted(seen.items())}
        data["updated"] = date.today().isoformat()
        pa.GEODATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        print(f"Marked the items of {', '.join(read)} as read", file=sys.stderr)
    return status


def towpath(first: float, last: float | None) -> int:
    last = first if last is None else last
    lines = pa.towpath_lines(first, last)
    asked = max(abs(last - first) * pa.MILE_M, 100.0)
    covered = sum(pa._metres(a, b) for line in lines for a, b in zip(line, line[1:], strict=False))
    print(json.dumps(lines))
    share = min(1.0, covered / asked)
    print(f"C&O MP {first:g} to {last:g}: the mile lines cover {share:.0%}", file=sys.stderr)
    if share < 0.95:
        print(
            "The rest has no mile line: draw it from the OpenStreetMap ways "
            "(scripts/ddot_advisories.py lines WAY ...)",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("watch", help="list park alerts not yet read")
    w.add_argument("--agency", choices=sorted(pa.AGENCIES), action="append")
    w.add_argument("--mark", action="store_true", help="then mark every item read")
    t = sub.add_parser("towpath", help="the C&O's lines between two mileposts")
    t.add_argument("first", type=float)
    t.add_argument("last", type=float, nargs="?")
    args = parser.parse_args()
    if args.command == "towpath":
        return towpath(args.first, args.last)
    return watch(args.agency or list(pa.AGENCIES), args.mark)


if __name__ == "__main__":
    sys.exit(main())
