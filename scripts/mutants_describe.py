#!/usr/bin/env python3
"""Mutants on the route description (OWNER-DECISIONS 220): `routemaker.describe`,
the pieces' names and headings in `core.routing`, and the API field.

A mutation pass run against WHOLE test files (not the test written for the
line): a mutant is killed when any test in the files named for it fails. It works
on a copy of the repository so the tree being worked on is never edited, and runs
each test file in a process of its own:

    scripts/mutants_describe.py [--only NAME] [--list] [--check]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"):
PGDATABASE should name a private database. Each line of MUTANTS is
(name, file, old text, new text, test files); `old` must occur exactly once.
Survivors are printed last and the exit status is the number of them.
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

D = "src/routemaker/describe.py"
R = "src/core/routing.py"
A = "src/core/api.py"
PURE = ["tests/test_describe.py"]
VIEW = ["tests/test_route_description.py"]
BOTH = PURE + VIEW

SAME = "    return a.tier == b.tier and a.facility == b.facility and _same_street(a, b)"
SAME = "    return a.tier == b.tier and a.facility == b.facility and _same_street(a, b)"
SORT = "options.sort(key=lambda n: (not _same_street(run, n), -n.metres, n is after))"
IFPATH = '    if facility == "path":\n        return PATH_WORDS'
TURNS = (
    '        if movement == "left":\n            lead = f"Left onto {street}"\n'
    '        elif movement == "right":\n            lead = f"Right onto {street}"'
)
TURNS_SWAPPED = (
    '        if movement == "right":\n            lead = f"Left onto {street}"\n'
    '        elif movement == "left":\n            lead = f"Right onto {street}"'
)
UNNAMED = '    return UNNAMED_PATH if run.facility in ("path", "protected") or run.path else "unnamed road"'
NEVER = 'NEVER_HIDDEN = frozenset({"3", "4", "5"})'
RANGE = '    return f"{_miles(start_m)} to {_miles(end_m)} mi ({_km(start_m)} to {_km(end_m)} km)"'
RANGE_DASH = '    return f"{_miles(start_m)}–{_miles(end_m)} mi ({_km(start_m)}–{_km(end_m)} km)"'
VIA_ENTRY = '                        (start, 0, i),\n                        _entry(\n                            "via"'
VIA_LATE = '                        (start, 2, i),\n                        _entry(\n                            "via"'
SCALE = "    scale = total_m / traced if total_m and total_m > 0 and traced > 0 else 1.0"
MATCHED = "        if found is not None:\n            used.add(found)\n"
SEV_FULL = "        text = _stretch_sentence(run, start, end, turn, continues)\n        severity = None\n        if turn is not None and turn.event is not None and turn.event.flagged:\n            severity = turn.event.severity"
SEV_OVER = "        continues = first > 0 and runs[first - 1].leg == runs[first].leg\n        severity = None\n        if turn is not None and turn.event is not None and turn.event.flagged:\n            severity = turn.event.severity"
CLASSES = "                            classes[i][0],\n                            classes[i][1],"
CLASSES_SWAPPED = (
    "                            classes[i][1],\n                            classes[i][0],"
)

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    (
        "tiny: 300 ft becomes 30 ft",
        D,
        "TINY_M = 300.0 / FEET_PER_METRE",
        "TINY_M = 30.0 / FEET_PER_METRE",
        PURE,
    ),
    (
        "tiny: 300 ft becomes 3000 ft",
        D,
        "TINY_M = 300.0 / FEET_PER_METRE",
        "TINY_M = 3000.0 / FEET_PER_METRE",
        PURE,
    ),
    ("never hidden: LTS 5 may fold", D, NEVER, 'NEVER_HIDDEN = frozenset({"3", "4"})', PURE),
    ("never hidden: LTS 4 may fold", D, NEVER, 'NEVER_HIDDEN = frozenset({"3", "5"})', PURE),
    ("never hidden: LTS 3 may fold", D, NEVER, 'NEVER_HIDDEN = frozenset({"4", "5"})', PURE),
    (
        "tiny: LTS 3+ folds into a calmer neighbour",
        D,
        "                options = [n for n in options if _rank(n) >= _rank(run)]",
        "                options = options",
        PURE,
    ),
    (
        "tiny: own street not preferred",
        D,
        SORT,
        "options.sort(key=lambda n: (-n.metres, n is after))",
        PURE,
    ),
    (
        "tiny: shorter neighbour chosen",
        D,
        SORT,
        "options.sort(key=lambda n: (not _same_street(run, n), n.metres, n is after))",
        PURE,
    ),
    (
        "tiny: the heading of a folded start is lost",
        D,
        "                target.first = run.first\n",
        "                pass\n",
        PURE,
    ),
    (
        "same street: two unnamed are different",
        D,
        "    if not a.names and not b.names:\n        return True",
        "    if not a.names and not b.names:\n        return False",
        PURE,
    ),
    (
        "merge: tier ignored",
        D,
        SAME,
        "    return a.facility == b.facility and _same_street(a, b)",
        PURE,
    ),
    (
        "merge: facility ignored",
        D,
        SAME,
        "    return a.tier == b.tier and _same_street(a, b)",
        PURE,
    ),
    (
        "label: first name always",
        D,
        "        if not _ROUTE_NUMBER.match(name.strip()):",
        "        if True:",
        PURE,
    ),
    (
        "readable: capitals not kept",
        D,
        "        words.append(word.upper() if word in _CAPITALS else word[:1].upper() + word[1:])",
        "        words.append(word[:1].upper() + word[1:])",
        PURE,
    ),
    (
        "severity words swapped",
        D,
        'SEVERITY_WORDS = {"orange": "Higher stress", "red": "Very high stress"}',
        'SEVERITY_WORDS = {"orange": "Very high stress", "red": "Higher stress"}',
        PURE,
    ),
    (
        "tier words: LTS 3",
        D,
        '    "3": "busy road (LTS 3)",',
        '    "3": "heavy traffic (LTS 3)",',
        PURE,
    ),
    ("tier words: a path is its tier", D, IFPATH, "    if False:\n        return PATH_WORDS", PURE),
    ("range: a dash for to", D, RANGE, RANGE_DASH, PURE),
    (
        "range: short stretches as a range",
        D,
        "    if end_m - start_m < SHORT_M:",
        "    if False:",
        PURE,
    ),
    ("match: a junction is never the turn's", D, "MATCH_M = 30.0", "MATCH_M = 0.0", PURE),
    ("match: any distance", D, "MATCH_M = 30.0", "MATCH_M = 100000.0", PURE),
    ("scale: distances left as traced", D, SCALE, "    scale = 1.0", PURE),
    (
        "via: numbered from 0",
        D,
        "                number = run.leg\n",
        "                number = run.leg - 1\n",
        PURE,
    ),
    ("turn: left and right swapped", D, TURNS, TURNS_SWAPPED, PURE),
    (
        "turn: heading in read from the wrong end",
        D,
        "    a = before.last.heading_out if before.last else None",
        "    a = before.last.heading_in if before.last else None",
        PURE,
    ),
    (
        "control: no signal mapped said of unflagged junctions",
        D,
        '    return ", no signal mapped" if flagged else ""',
        '    return ", no signal mapped"',
        PURE,
    ),
    (
        "junction: unflagged events listed",
        D,
        "        if index in used or not event.flagged:",
        "        if index in used:",
        PURE,
    ),
    ("junction: a turn's event also listed", D, MATCHED, "", PURE),
    (
        "junction: a turn's flagged severity dropped (full)",
        D,
        "        severity = None\n        if turn is not None and turn.event is not None and turn.event.flagged:\n            severity = turn.event.severity\n        entries.append(",
        "        severity = None\n        if False and turn.event is not None and turn.event.flagged:\n            severity = turn.event.severity\n        entries.append(",
        PURE,
    ),
    (
        "junction: a turn's flagged severity dropped (overview)",
        D,
        "        severity = None\n        if turn is not None and turn.event is not None and turn.event.flagged:\n            severity = turn.event.severity\n        overview.append(",
        "        severity = None\n        if False and turn.event is not None and turn.event.flagged:\n            severity = turn.event.severity\n        overview.append(",
        PURE,
    ),
    (
        "overview: a turn's flagged severity dropped",
        D,
        SEV_OVER,
        SEV_OVER.replace("if turn is not None and", "if False and"),
        PURE,
    ),
    (
        "name: placeholder way names said",
        D,
        '    names = sorted(n for n in event.road_names if not n.startswith("way "))',
        "    names = sorted(event.road_names)",
        PURE,
    ),
    ("name: an unnamed path is a road", D, UNNAMED, '    return "unnamed road"', PURE),
    (
        "name: a path use is not a path",
        D,
        UNNAMED,
        '    return UNNAMED_PATH if run.facility in ("path", "protected") else "unnamed road"',
        PURE,
    ),
    ("order: via after the stretch", D, VIA_ENTRY, VIA_LATE, PURE),
    (
        "pieces: names dropped",
        R,
        '            "names": names,\n',
        '            "names": (),\n',
        BOTH,
    ),
    (
        "pieces: heading in from the end",
        R,
        '            "heading_in": _heading(edge.get("begin_heading")),',
        '            "heading_in": _heading(edge.get("end_heading")),',
        BOTH,
    ),
    (
        "pieces: use dropped",
        R,
        '            "use": str(edge.get("use") or ""),',
        '            "use": "",',
        BOTH,
    ),
    ("trace: names not asked for", R, '                    "edge.names",\n', "", VIEW),
    ("plan: classes read the wrong way round", R, CLASSES, CLASSES_SWAPPED, VIEW),
    (
        "plan: a failure is raised",
        R,
        "    except Exception:  # noqa: BLE001 - a route is answered without its description",
        "    except KeyError:  # noqa: BLE001 - a route is answered without its description",
        VIEW,
    ),
    (
        "plan: the stated length unused",
        R,
        "        return describe.describe_both(legs, events, length or None)",
        "        return describe.describe_both(legs, events, None)",
        BOTH,
    ),
    (
        "plan: description not answered",
        R,
        '        "description": described_full,',
        '        "description": None,',
        VIEW,
    ),
    (
        "api: description required",
        A,
        "    description: list[DescriptionEntryOut] | None = None",
        "    description: list[DescriptionEntryOut] | None",
        VIEW,
    ),
    (
        "api: kinds",
        A,
        '    kind: Literal["stretch", "junction", "via"]',
        '    kind: Literal["stretch", "junction"]',
        VIEW,
    ),
    (
        "tiny: ties go to the later neighbour",
        D,
        SORT,
        "options.sort(key=lambda n: (not _same_street(run, n), -n.metres, n is not after))",
        PURE,
    ),
    (
        "continue: never said",
        D,
        "        continues = i > 0 and runs[i - 1].leg == run.leg",
        "        continues = False",
        PURE,
    ),
    (
        "crossed: the LTS 4 words",
        D,
        '    return {3: " (LTS 3)", 4: " (LTS 4)", 5: " (Avoid)"}.get(tier or 0, "")',
        '    return {3: " (LTS 3)", 4: " (LTS 3)", 5: " (Avoid)"}.get(tier or 0, "")',
        PURE,
    ),
    (
        "feet: not rounded to ten",
        D,
        "    return int(round(value, -1)) if value >= 100 else int(round(value))",
        "    return int(round(value))",
        PURE,
    ),
    (
        "control: a stop sign said as a signal",
        D,
        '    Control.STOP: " at a stop sign",',
        '    Control.STOP: " at a signal",',
        PURE,
    ),
    (
        "fold: another street's names taken",
        D,
        "                if _same_street(run, target):",
        "                if True:",
        PURE,
    ),
    ("join: another street's names taken", D, "    if _same_street(a, b):", "    if True:", PURE),
    (
        "atoms: tier ignored when joining pieces",
        D,
        "            and atom.tier == previous.tier",
        "            and True",
        PURE,
    ),
    (
        "atoms: facility ignored when joining pieces",
        D,
        "            and atom.facility == previous.facility",
        "            and True",
        PURE,
    ),
    (
        "atoms: names ignored when joining pieces",
        D,
        "            and atom.names == previous.names",
        "            and True",
        PURE,
    ),
    (
        "atoms: a path use of a later piece lost",
        D,
        "            run.path = run.path or atom.use in PATH_USES",
        "            pass",
        PURE,
    ),
]

JOIN = (
    '            ra.leg == rb.leg\n            and (ra.tier == "unknown") == (rb.tier == "unknown")'
)
CAND = "if metres(g) < OVERVIEW_M and not _flagged_turn(turns, g[0])"
AFTER = "if after is not None and joinable(group, after) and not _flagged_turn(turns, after[0]):"
PREF = "return (not same_kind, not same_street, -metres(o), o is after)"
THEN = '        listed = ", ".join(pieces[:-1]) + " and " + pieces[-1]'

MUTANTS += [
    (
        "overview: limit is an eighth of a mile",
        D,
        "OVERVIEW_M = METRES_PER_MILE / 4",
        "OVERVIEW_M = METRES_PER_MILE / 8",
        PURE,
    ),
    (
        "overview: limit is half a mile",
        D,
        "OVERVIEW_M = METRES_PER_MILE / 4",
        "OVERVIEW_M = METRES_PER_MILE / 2",
        PURE,
    ),
    (
        "overview: a stretch exactly at the limit is merged",
        D,
        "if metres(g) < OVERVIEW_M and",
        "if metres(g) <= OVERVIEW_M and",
        PURE,
    ),
    (
        "overview: LTS 3+ folds into a calmer neighbour",
        D,
        "                options = [o for o in options if rank(o) >= rank(group)]",
        "                options = options",
        PURE,
    ),
    (
        "overview: a stretch at a flagged junction may fold away",
        D,
        CAND,
        CAND.replace(" and not _flagged_turn(turns, g[0])", ""),
        PURE,
    ),
    (
        "overview: a stretch may fold in front of a flagged junction",
        D,
        AFTER,
        AFTER.replace(" and not _flagged_turn(turns, after[0])", ""),
        PURE,
    ),
    ("overview: merges across a stop", D, JOIN, JOIN.replace("ra.leg == rb.leg", "True"), PURE),
    (
        "overview: merges rated with unrated",
        D,
        JOIN,
        JOIN.replace(
            '            and (ra.tier == "unknown") == (rb.tier == "unknown")',
            "            and True",
        ),
        PURE,
    ),
    (
        "overview: tier is the first member's",
        D,
        "        tier=worst.tier,",
        "        tier=first.tier,",
        PURE,
    ),
    (
        "overview: tier is the last member's",
        D,
        "    worst = max(members, key=_rank)",
        "    worst = members[-1]",
        PURE,
    ),
    (
        "overview: facility kept where members differ",
        D,
        '        facility=first.facility if len(facilities) == 1 else "none",',
        "        facility=first.facility,",
        PURE,
    ),
    (
        "overview: same tier and facility not preferred",
        D,
        PREF,
        PREF.replace("not same_kind, ", ""),
        PURE,
    ),
    ("overview: own street not preferred", D, PREF, PREF.replace("not same_street, ", ""), PURE),
    (
        "overview: folded forwards when it could go back",
        D,
        PREF,
        PREF.replace("o is after", "o is not after"),
        PURE,
    ),
    (
        "overview: the street it begins on is listed again",
        D,
        "        if m.label and m.label != own and m.label not in (s for s, _m in streets):",
        "        if m.label and m.label not in (s for s, _m in streets):",
        PURE,
    ),
    (
        "overview: other streets listed twice",
        D,
        "        if m.label and m.label != own and m.label not in (s for s, _m in streets):",
        "        if m.label and m.label != own:",
        PURE,
    ),
    (
        "overview: three streets are not listed in full",
        D,
        "    for street, movement in streets[:MAX_NAMED_TURNS]:",
        "    for street, movement in streets[: MAX_NAMED_TURNS - 1]:",
        PURE,
    ),
    ("overview: two streets joined without and", D, THEN, THEN.replace('" and "', '", "'), PURE),
    (
        "overview: the count of more streets is off",
        D,
        "    more = len(streets) - MAX_NAMED_TURNS\n",
        "    more = len(streets) - MAX_NAMED_TURNS + 1\n",
        PURE,
    ),
    (
        "overview: ends at its first run",
        D,
        "        end = (starts[last] + runs[last].metres) * scale",
        "        end = (starts[first] + runs[first].metres) * scale",
        PURE,
    ),
    (
        "overview: turn read from its last run",
        D,
        "        turn = turns.get(first)\n        continues",
        "        turn = turns.get(last)\n        continues",
        PURE,
    ),
    (
        "overview: stops left out",
        D,
        "    short = sorted(overview + shared + short_only, key=lambda pair: pair[0])",
        "    short = sorted(overview + short_only, key=lambda pair: pair[0])",
        PURE,
    ),
    (
        "overview: describe answers the overview",
        D,
        "    return describe_both(legs, events, total_m)[0]",
        "    return describe_both(legs, events, total_m)[1]",
        PURE,
    ),
    (
        "overview: the unmerged sentence is not the full one",
        D,
        '    if len(members) == 1:\n        return first, ""',
        '    if len(members) == 1:\n        return first, ", then"',
        PURE,
    ),
    (
        "overview: widest candidate first",
        D,
        "        for _size, n in sorted(candidates):",
        "        for _size, n in sorted(candidates, reverse=True):",
        PURE,
    ),
    (
        "stops: still Via",
        D,
        'f"Stop {number} at {point_words(start)}."',
        'f"Via {number} at {point_words(start)}."',
        PURE,
    ),
    (
        "stops: said as a stop of the route",
        D,
        'f"Stop {number} at {point_words(start)}."',
        'f"Stop {number}: stop at {point_words(start)}."',
        PURE,
    ),
    (
        "plan: the overview not answered",
        R,
        '        "description_overview": described_overview,',
        '        "description_overview": None,',
        VIEW,
    ),
    (
        "plan: the two lists swapped",
        R,
        "    described_full, described_overview = described if described else (None, None)",
        "    described_overview, described_full = described if described else (None, None)",
        VIEW,
    ),
    (
        "api: the overview required",
        A,
        "    description_overview: list[DescriptionEntryOut] | None = None",
        "    description_overview: list[DescriptionEntryOut] | None",
        VIEW,
    ),
]

MUTANTS += [
    (
        "overview: a calm stretch merges with a busy one",
        D,
        "            # A calm stretch is never worded as busy, nor a busy one as calm.\n            and (rank(a) >= 3) == (rank(b) >= 3)\n",
        "",
        PURE,
    ),
]

MUTANTS += [
    (
        "overview: LTS 4 may fold into LTS 3",
        D,
        "            if rank(group) > 3:",
        "            if rank(group) > 4:",
        PURE,
    ),
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
