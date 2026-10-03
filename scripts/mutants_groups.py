#!/usr/bin/env python3
"""Mutants on a Mass Ride's groups of signalised crossings (OWNER-DECISIONS 233, 234, 235):
the group reading in `routemaker.intersections`, its wording in `routemaker.describe` and
the rows `core.routing` sends.

A mutation pass run against WHOLE test files (not the test written for the line): a mutant
is killed when any test in the files named for it fails. It works on a copy of the
repository so the tree being worked on is never edited, and runs each test file in a
process of its own:

    scripts/mutants_groups.py [--only NAME] [--list] [--check]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"): PGDATABASE
should name a private database. Each line of MUTANTS is (name, file, old text, new text,
test files); `old` must occur exactly once. Survivors are printed last and the exit status
is the number of them.

Not mutated, because the mutant is equivalent: `assess_route`'s `if group` before
`number_groups`, since `groupable` also asks for `Event.group_severity`, which only the group
reading sets (that other guard has its own mutant).
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

INTERSECTIONS = "src/routemaker/intersections.py"
DESCRIBE = "src/routemaker/describe.py"
ROUTING = "src/core/routing.py"
TESTS = ["tests/test_crossing_groups.py"]

GROUPED = 'GROUPED_KINDS = frozenset({"crossing", "left_across"})'
SIGNAL = "        and event.control is Control.SIGNAL\n"
SEVERITY = "        return _worst(e.severity for e in self.members) or ORANGE"
RUN_OF = "        if len(run) >= 2:\n            number += 1"

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    ("window: a quarter mile becomes 2.5 miles", INTERSECTIONS, "GROUP_WITHIN_M = 402.0", "GROUP_WITHIN_M = 4020.0", TESTS),
    ("window: a quarter mile becomes 130 ft", INTERSECTIONS, "GROUP_WITHIN_M = 402.0", "GROUP_WITHIN_M = 40.2", TESTS),
    ("window: the limit itself breaks the run", INTERSECTIONS, "events[run[-1]].m > GROUP_WITHIN_M:", "events[run[-1]].m >= GROUP_WITHIN_M:", TESTS),
    ("window: measured from the first member, not the one before", INTERSECTIONS, "events[run[-1]].m > GROUP_WITHIN_M", "events[run[0]].m > GROUP_WITHIN_M", TESTS),
    ("window: a gap never breaks a run", INTERSECTIONS, "        if run and event.m - events[run[-1]].m > GROUP_WITHIN_M:\n            close()\n", "", TESTS),
    ("run: a run of one is a group", INTERSECTIONS, RUN_OF, RUN_OF.replace(">= 2", ">= 1"), TESTS),
    ("run: it takes three to make a group", INTERSECTIONS, RUN_OF, RUN_OF.replace(">= 2", ">= 3"), TESTS),
    ("run: an unsignalised flagged crossing does not break it", INTERSECTIONS, "        if not groupable(event):\n            close()\n            continue", "        if not groupable(event):\n            continue", TESTS),
    ("run: an unflagged event breaks it", INTERSECTIONS, "        if not event.flagged:\n            continue\n        if not groupable", "        if not event.flagged:\n            close()\n            continue\n        if not groupable", TESTS),
    ("member: a stop or yield sign joins as a signal", INTERSECTIONS, SIGNAL, SIGNAL.replace("is Control.SIGNAL", "is not Control.NONE"), TESTS),
    ("member: only a crossing with no signal joins", INTERSECTIONS, SIGNAL, SIGNAL.replace("is Control.SIGNAL", "is Control.NONE"), TESTS),
    ("member: a left across a busy road does not join", INTERSECTIONS, GROUPED, 'GROUPED_KINDS = frozenset({"crossing"})', TESTS),
    ("member: a left turn onto a busy road joins", INTERSECTIONS, GROUPED, 'GROUPED_KINDS = frozenset({"crossing", "left_across", "left_onto"})', TESTS),
    ("member: a left off a busy road joins", INTERSECTIONS, GROUPED, 'GROUPED_KINDS = frozenset({"crossing", "left_across", "left_from"})', TESTS),
    ("member: an event that is not a Mass Ride's joins", INTERSECTIONS, "        event.group_severity\n        and event.flagged", "        event.flagged", TESTS),
    ("numbering: every group is group 1", INTERSECTIONS, "numbered[i] = replace(numbered[i], group=number)", "numbered[i] = replace(numbered[i], group=1)", TESTS),
    ("numbering: counts by two", INTERSECTIONS, "            number += 1\n            for i in run:", "            number += 2\n            for i in run:", TESTS),
    ("group: the severity is the first member's", INTERSECTIONS, SEVERITY, "        return self.members[0].severity or ORANGE", TESTS),
    ("group: the severity is always orange", INTERSECTIONS, SEVERITY, "        return ORANGE", TESTS),
    ("group: LTS 4 does not count", INTERSECTIONS, "GROUP_LTS4_TIER = 4", "GROUP_LTS4_TIER = 5", TESTS),
    ("group: an Avoid road does not count as LTS 4", INTERSECTIONS, "(e.crossed_tier or 0) >= GROUP_LTS4_TIER", "(e.crossed_tier or 0) == GROUP_LTS4_TIER", TESTS),
    ("group: they come out last first", INTERSECTIONS, "for n in sorted(found)]", "for n in sorted(found, reverse=True)]", TESTS),
    ("words: three streets become two", DESCRIBE, "MAX_NAMED_STREETS = 3", "MAX_NAMED_STREETS = 2", TESTS),
    ("words: three streets become four", DESCRIBE, "MAX_NAMED_STREETS = 3", "MAX_NAMED_STREETS = 4", TESTS),
    ("words: 'and N more' loses its count", DESCRIBE, 'listed = ", ".join(shown) + f" and {more} more"', 'listed = ", ".join(shown) + " and more"', TESTS),
    ("words: a street crossed twice is named twice", DESCRIBE, "        if name and name.lower() not in seen:", "        if name:", TESTS),
    ("words: no LTS 4 still says it", DESCRIBE, '    if lts4 <= 0:\n        return ""', '    if lts4 < 0:\n        return ""', TESTS),
    ("words: all LTS 4 is said as a number", DESCRIBE, 'return ", all of LTS 4 roads" if lts4 == count', 'return ", all of LTS 4 roads" if lts4 == count + 1', TESTS),
    ("words: the severity word is singular", DESCRIBE, "({SEVERITY_WORDS[group.severity]} junctions).", "({SEVERITY_WORDS[group.severity]} junction).", TESTS),
    ("words: the severity is left off", DESCRIBE, 'f"{group_words(group, start_m, end_m)} ({SEVERITY_WORDS[group.severity]} junctions)."', 'f"{group_words(group, start_m, end_m)}."', TESTS),
    ("description: every member is an entry", DESCRIBE, "            if event.group in said:\n                continue\n", "", TESTS),
    ("description: the span runs backwards", DESCRIBE, "from_at, to_at = group.from_m * scale, group.to_m * scale", "from_at, to_at = group.to_m * scale, group.from_m * scale", TESTS),
    ("description: the entry's severity is the first member's", DESCRIBE, "                        severity=group.severity,\n                        group={", "                        severity=event.severity,\n                        group={", TESTS),
    ("description: the count is one short", DESCRIBE, '"count": group.count,', '"count": group.count - 1,', TESTS),
    ("description: the LTS 4 count is the member count", DESCRIBE, '"lts4": group.lts4,', '"lts4": group.count,', TESTS),
    ("description: every entry has a group", DESCRIBE, '        "group": None,\n        "text": text,', '        "group": {},\n        "text": text,', TESTS),
    ("api: a row never says its group", ROUTING, '"group": event.group,', '"group": None,', TESTS),
    ("api: members index every event, not the flagged", ROUTING, "    flagged = [event for event in events if event.flagged]\n    rows = []", "    flagged = list(events)\n    rows = []", TESTS),
    ("api: more counts every street", ROUTING, '"more": max(len(streets) - describe.MAX_NAMED_STREETS, 0),\n                "severity"', '"more": len(streets),\n                "severity"', TESTS),
    ("api: the group's phrase says its severity", ROUTING, '"text": describe.group_words(group, group.from_m, group.to_m),', '"text": describe.group_sentence(group, group.from_m, group.to_m),', TESTS),
    ("api: the span ends at the first crossing", ROUTING, '"to_m": round(group.to_m),', '"to_m": round(group.from_m),', TESTS),
]


def _passes(copy: Path, tests: list[str]) -> bool:
    """Whether every test file passes, each in a process of its own (one test
    file per process: the lane's rule), stopping at the first that fails."""
    for test in tests:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", test],
            cwd=copy,
            capture_output=True,
            text=True,
        )
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
    print(f"\n{len(selected) - len(survivors)} killed, {len(survivors)} survived of {len(selected)}")
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
