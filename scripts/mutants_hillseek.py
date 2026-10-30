#!/usr/bin/env python3
"""Mutants on the hill seek (`core.hillseek`) and its place in the plan
(`core.routing`).

FOLLOWUP-HILL-SEEK (OWNER-DECISIONS 205). A mutation pass run against WHOLE test
files, as `scripts/mutants_trailseek.py` does: a mutant is killed when any test in
the files named for it fails. It works on a copy of the repository and runs each
test file in a process of its own:

    scripts/mutants_hillseek.py [--only NAME] [--list] [--check]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"):
PGDATABASE should name a private database (the plan's tests are database tests).
Each line of MUTANTS is (name, file, old text, new text, test files); `old` must
occur exactly once. Survivors are printed last and the exit status is the number of
them.

Two mutants that were tried and are not in the list are equivalent, not survivors:

- the ranking's height gained put before its category (`preference`): the category
  is the height gained in bands (the score is 100 times the net gain,
  `routemaker.climb_categories`), so the two orders differ only where the file's
  rounding puts a climb on the wrong side of a band;
- `first_near`'s "not behind the last point" test dropped (`ridden`): the walk
  already starts at the segment the last point was found on, and a climb read
  backwards within one long segment comes out with no length and fails the 0.8 to
  1.3 test.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SEEK = ["tests/test_hillseek.py"]
PLAN = ["tests/test_route_dials.py"]

HS = "src/core/hillseek.py"
RT = "src/core/routing.py"

# The longest a test file may take against a mutant.
TEST_TIMEOUT_S = 300

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- the file ----------------------------------------------------------
    (
        "parse: another format read",
        HS,
        'if not isinstance(doc, dict) or doc.get("version") != FORMAT_VERSION:',
        "if not isinstance(doc, dict):",
        SEEK,
    ),
    (
        "parse: an unknown category kept",
        HS,
        "if len(line) >= 2 and climb.category in CATEGORY_RANK and climb.length_m > 0:",
        "if len(line) >= 2 and climb.length_m > 0:",
        SEEK,
    ),
    (
        "parse: a one-point line kept",
        HS,
        "if len(line) >= 2 and climb.category",
        "if len(line) >= 1 and climb.category",
        SEEK,
    ),
    (
        "parse: unpaved ignored",
        HS,
        'unpaved=bool(row.get("u")),',
        "unpaved=False,",
        SEEK,
    ),
    (
        "load: never read again",
        HS,
        "if cached is not None and cached[0] == key:",
        "if cached is not None:",
        SEEK,
    ),
    # --- the corridor ------------------------------------------------------
    (
        "estimate: no circuity",
        HS,
        "return CIRCUITY * way + sum(c.length_m for c in climbs)",
        "return way + sum(c.length_m for c in climbs)",
        SEEK,
    ),
    (
        "estimate: the climbs left out",
        HS,
        "return CIRCUITY * way + sum(c.length_m for c in climbs)",
        "return CIRCUITY * way",
        SEEK,
    ),
    (
        "estimate: the way on from the foot",
        HS,
        "        at = climb.summit\n",
        "        at = climb.foot\n",
        SEEK,
    ),
    (
        "preference: the longer first",
        HS,
        "return (-climb.rank, -climb.gain_m, estimate_m(start, end, (climb,)))",
        "return (-climb.rank, -climb.gain_m, -estimate_m(start, end, (climb,)))",
        SEEK,
    ),
    (
        "corridor: the budget ignored",
        HS,
        "if not (avoid_gravel and c.unpaved) and estimate_m(start, end, (c,)) <= budget_m",
        "if not (avoid_gravel and c.unpaved)",
        SEEK,
    ),
    (
        "corridor: gravel kept",
        HS,
        "if not (avoid_gravel and c.unpaved) and estimate_m",
        "if estimate_m",
        SEEK,
    ),
    # --- the proposals -----------------------------------------------------
    (
        "apart: either end",
        HS,
        "return _metres(a.foot, b.foot) >= PAIR_GAP_M and _metres",
        "return _metres(a.foot, b.foot) >= PAIR_GAP_M or _metres",
        SEEK,
    ),
    (
        "ordered: as given",
        HS,
        "if estimate_m(start, end, (b, a)) < estimate_m(start, end, (a, b)):",
        "if False:",
        SEEK,
    ),
    (
        "propose: a pair past the budget",
        HS,
        "if estimate_m(start, end, pair) <= budget_m:",
        "if True:",
        SEEK,
    ),
    (
        "propose: no pair",
        HS,
        "            out.append(pair)\n            break",
        "            break",
        SEEK,
    ),
    (
        "propose: the next not apart",
        HS,
        "if all(apart(climb, c) for c in asked):",
        "if True:",
        SEEK,
    ),
    (
        "propose: the pair's partner asked for again",
        HS,
        "asked = [climb for proposal in out for climb in proposal]",
        "asked = [first]",
        SEEK,
    ),
    (
        "propose: one more than the limit",
        HS,
        "return out[:limit]",
        "return out[: limit + 1]",
        SEEK,
    ),
    # --- the via points ----------------------------------------------------
    (
        "vias: no inset",
        HS,
        "inset = min(VIA_INSET_M, total / 4)",
        "inset = 0.0",
        SEEK,
    ),
    (
        "vias: no middle point",
        HS,
        "max(2, math.ceil(inner / VIA_SPACING_M))",
        "max(1, math.ceil(inner / VIA_SPACING_M))",
        SEEK,
    ),
    (
        "vias: no cap",
        HS,
        "steps = min(MAX_VIAS - 1, max(",
        "steps = min(100, max(",
        SEEK,
    ),
    (
        "vias: summit to foot",
        HS,
        "for k in range(steps + 1)]",
        "for k in range(steps, -1, -1)]",
        SEEK,
    ),
    # --- along a route -----------------------------------------------------
    (
        "ridden: the reach doubled",
        HS,
        "        if away > tolerance_m:\n            return None",
        "        if away > 2 * tolerance_m:\n            return None",
        SEEK,
    ),
    (
        "ridden: the length not held",
        HS,
        "if not (RIDDEN_MIN * climb.length_m <= length <= RIDDEN_MAX * climb.length_m):",
        "if False:",
        SEEK,
    ),
    (
        "ridden: no walk back from the summit",
        HS,
        "            start = hit\n        length = along - start[1]",
        "            pass\n        length = along - start[1]",
        SEEK,
    ),
    (
        "ridden: part of it counts",
        HS,
        "        if len(hits) < len(points):\n            continue",
        "        if not hits:\n            continue",
        SEEK,
    ),
    (
        "ridden: not in route order",
        HS,
        "return sorted(out, key=lambda r: r.start_m)",
        "return out",
        SEEK,
    ),
    (
        "naming: every climb",
        HS,
        "+ _metres(c.summit, end) <= reach",
        "+ _metres(c.summit, end) <= reach or True",
        SEEK,
    ),
    # --- in words ----------------------------------------------------------
    (
        "words: HC said as a number",
        HS,
        'if climb.category == "HC"',
        "if False",
        SEEK,
    ),
    (
        "words: a mile said as miles",
        HS,
        'mi = t("{n} mile", n=f"{miles:.1f}") if one else t("{n} miles", n=f"{miles:.1f}")',
        'mi = t("{n} miles", n=f"{miles:.1f}")',
        SEEK,
    ),
    (
        "words: the summit not scaled",
        HS,
        "summit=point_words(item.summit_m * scale),",
        "summit=point_words(item.summit_m),",
        SEEK,
    ),
    (
        "entry: not scaled",
        HS,
        "at, to = item.start_m * scale, item.summit_m * scale",
        "at, to = item.start_m, item.summit_m",
        SEEK,
    ),
    (
        "entries: after the stretch that starts there",
        HS,
        'while pending and pending[0]["from_m"] <= item["from_m"]:',
        'while pending and pending[0]["from_m"] < item["from_m"]:',
        SEEK,
    ),
    # --- the seek ----------------------------------------------------------
    (
        "seek: no file runs",
        HS,
        '    if climbs is None:\n        out.limited = "no_climbs"',
        "    if climbs is None:\n        climbs = ()",
        SEEK,
    ),
    (
        "seek: a climb already ridden asked for",
        HS,
        "fresh = [c for c in out.near if c.id not in taken]",
        "fresh = list(out.near)",
        SEEK,
    ),
    (
        "seek: the time not looked at",
        HS,
        "if left() < ROUND_MIN_S:",
        "if False:",
        SEEK,
    ),
    (
        "seek: out of time carries on",
        HS,
        '            out.limited = "time"\n            break\n        if trip',
        '            out.limited = "time"\n            continue\n        if trip',
        SEEK,
    ),
    (
        "seek: a route with no legs kept",
        HS,
        'if trip and trip.get("legs"):',
        "if trip:",
        SEEK,
    ),
    # --- the plan ----------------------------------------------------------
    (
        "plan: the points not through",
        RT,
        '*({"lon": lon, "lat": lat, "type": "through"} for lon, lat in vias),\n            locations[-1],',
        '*({"lon": lon, "lat": lat, "type": "break"} for lon, lat in vias),\n            locations[-1],',
        SEEK,
    ),
    (
        "plan: no reserve for the traces",
        RT,
        "stop_at = min(clock() + hillseek.SEEK_BUDGET_S, deadline.at - hillseek.TRACE_RESERVE_S)",
        "stop_at = min(clock() + hillseek.SEEK_BUDGET_S, deadline.at)",
        SEEK,
    ),
    (
        "plan: a refusal ends the seek",
        RT,
        "        except RouterRefused:\n            return None\n        except (DeadlineExceeded, RouterUnavailable) as error:\n            raise hillseek.OutOfTime",
        '        except RouterRefused:\n            raise hillseek.OutOfTime("refused")\n        except (DeadlineExceeded, RouterUnavailable) as error:\n            raise hillseek.OutOfTime',
        SEEK,
    ),
    (
        "plan: the budget not the dial's",
        RT,
        "_trip_length_m(trips[0]) * ratio,",
        "_trip_length_m(trips[0]) * 1.5,",
        SEEK,
    ),
    (
        "plan: a round trip seeks",
        RT,
        "round_trip = loop or haversine(Point(*points[0]), Point(*points[-1])) <= LOOP_SAME_M",
        "round_trip = loop",
        PLAN,
    ),
    (
        "plan: the seek's routes not compared",
        RT,
        "trips = trips + sought.trips",
        "trips = trips",
        PLAN,
    ),
    (
        "plan: the climbs not named",
        RT,
        "climbs_ridden = hillseek.ridden(coordinates, pool)",
        "climbs_ridden = []",
        PLAN,
    ),
    (
        "plan: sought not said",
        RT,
        '"sought": item.climb.id in asked_ids',
        '"sought": False',
        PLAN,
    ),
    (
        "plan: no description entries",
        RT,
        "described_full = hillseek.with_entries(described_full, climb_entries)",
        "described_full = described_full",
        PLAN,
    ),
    (
        "plan: the seek's work not said",
        RT,
        '"climb_seek": None if sought is None else sought.info(),',
        '"climb_seek": None,',
        PLAN,
    ),
]


def _passes(copy: Path, tests: list[str]) -> bool:
    """Whether every test file passes, each in a process of its own, stopping at the
    first that fails."""
    for test in tests:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", test],
                cwd=copy,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return False
        if result.returncode != 0:
            return False
    return True


def check() -> int:
    """Every mutant's text occurs exactly once in its file."""
    bad = 0
    for name, rel, old, _new, _tests in MUTANTS:
        count = (ROOT / rel).read_text().count(old)
        if count != 1:
            print(f"BAD   {name}: occurs {count} times in {rel}")
            bad += 1
    print(f"{len(MUTANTS) - bad} of {len(MUTANTS)} mutants apply")
    return bad


def run(names: list[str] | None) -> int:
    survivors: list[str] = []
    selected = [m for m in MUTANTS if not names or m[0] in names]
    with tempfile.TemporaryDirectory(prefix="mutants-") as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(
            ROOT,
            copy,
            ignore=shutil.ignore_patterns(".git", "node_modules", "dist", "__pycache__", ".venv*"),
        )
        # A control: the unmutated files must pass in the copy, or "killed" would
        # only mean the copy cannot run its tests.
        for tests in sorted({tuple(m[4]) for m in selected}):
            if not _passes(copy, list(tests)):
                print("CONTROL FAILED for", tests)
                return 1000
        for name, rel, old, new, tests in selected:
            target = copy / rel
            original = (ROOT / rel).read_text()
            if original.count(old) != 1:
                print(f"BAD   {name}: {old[:50]!r} occurs {original.count(old)} times in {rel}")
                survivors.append(name + " (bad mutant)")
                continue
            target.write_text(original.replace(old, new))
            killed = not _passes(copy, tests)
            target.write_text(original)
            if killed:
                print(f"killed   {name}", flush=True)
            else:
                print(f"SURVIVED {name}  ({rel})", flush=True)
                survivors.append(name)
    print(
        f"\n{len(selected) - len(survivors)} killed, {len(survivors)} survived of {len(selected)}"
    )
    for name in survivors:
        print("  survivor:", name)
    return len(survivors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", action="append", help="run just this mutant (repeatable)")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", action="store_true", help="only check that every mutant applies")
    args = parser.parse_args()
    if args.check:
        sys.exit(check())
    if args.list:
        for mutant in MUTANTS:
            print(mutant[0])
        sys.exit(0)
    sys.exit(run(args.only))
