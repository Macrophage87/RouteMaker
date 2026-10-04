#!/usr/bin/env python3
"""Mutants on the named corridors (`routemaker.corridors` and its fixture), the AADT
smoothing (`pipeline.aadt_smoothing`) and the override re-match (`pipeline.rematch`).

FOLLOWUP-ARTERIAL-CALIBRATION and FOLLOWUP-OVERRIDE-REMATCH (OWNER-DECISIONS 282,
286, 294-296). A mutation pass run against WHOLE test files, as
`scripts/mutants_trailseek.py` does: a mutant is killed when any test in the files
named for it fails. It works on a copy of the repository and runs each test file in a
process of its own:

    scripts/mutants_arterial.py [--only NAME] [--list] [--check]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"):
PGDATABASE should name a private database. Each line of MUTANTS is
(name, file, old text, new text, test files); `old` must occur exactly once.
Survivors are printed last and the exit status is the number of them.

Not in the list, because equivalent: the `way_id in separate_roads` exemption in
`corridors.exemption`. `facility.separate_pairs` only finds a road that itself
declares `cycleway*=separate`, which `has_separate_bikeway` already exempts.
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

CORR = ["tests/test_corridors.py"]
SMOOTH = ["tests/test_aadt_smoothing.py"]
REMATCH = ["tests/test_override_rematch.py"]
STAGE = ["tests/test_arterial_stage.py"]

CO = "src/routemaker/corridors.py"
FX = "fixtures/corridors/2026-10-04-owner-north-capitol-underpasses.json"
SM = "src/pipeline/aadt_smoothing.py"
ST = "src/routemaker/streets.py"
RM = "src/pipeline/rematch.py"
OV = "src/pipeline/overrides.py"
RUN = "src/pipeline/run.py"

TEST_TIMEOUT_S = 300

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- corridors: roles and ranges -----------------------------------------
    ("role: everything is through", CO, "if placement.mean_offset <= corridor.through_max_offset_m:", "if True:", CORR),
    ("role: nothing is too far out", CO, "if placement.mean_offset <= corridor.side_max_offset_m:", "if True:", CORR),
    ("role: bearing not checked", CO, "if placement.bearing_off_deg > corridor.max_bearing_deg:", "if False:", CORR),
    ("role: bearing sign matters", CO, "cosine = abs(chord[0] * axis_dir[0] + chord[1] * axis_dir[1]) / (", "cosine = (chord[0] * axis_dir[0] + chord[1] * axis_dir[1]) / (", CORR),
    ("entry: any overlap takes the way", CO, "if inside / len(placement.samples) >= MIN_SHARE_IN_RANGE:", "if inside > 0:", CORR),
    ("entry: almost all of the way needed", CO, "MIN_SHARE_IN_RANGE = 0.5", "MIN_SHARE_IN_RANGE = 0.95", CORR),
    ("entry: role not compared", CO, "        if entry.role != role:\n            continue\n", "", CORR),
    ("apply: street name ignored", CO, "if key not in corridor.streets:", "if False:", CORR),
    ("apply: unmatched entry not reported", CO, "if (corridor.id, entry.id) not in seen:", "if False:", CORR),
    ("apply: rule keeps the old text", CO, 'rule=f"named corridor: {corridor.id}, {entry.id}",', "rule=current.rule,", CORR),
    ("apply: unrated way gets a tier", CO, "            if current is None:\n                report.skipped_unclassified.append(way.osm_id)\n                break\n", "", CORR),
    # --- corridors: exemptions ---------------------------------------------------
    ("exempt: exempt way still lifted", CO, "after = before if why else entry.tier", "after = entry.tier", CORR),
    ("exempt: protected/path facility", CO, "if kind in (Facility.PROTECTED, Facility.PATH):", "if False:", CORR),
    ("exempt: separate bikeway", CO, "if has_separate_bikeway(dict(tags)):", "if False:", CORR),
    ("exempt: trail class", CO, 'if tags.get("highway") in TRAIL_CLASS_HIGHWAY:', "if False:", CORR),
    ("exempt: classifier's tags ignored", RUN, "tags_of=context.class_tags_by_way,", "tags_of=None,", STAGE),
    # --- corridors: the file ---------------------------------------------------------
    ("parse: overlapping entries allowed", CO, "if next_lo < prev_hi:", "if False:", CORR),
    ("parse: tier above 5 allowed", CO, "or not 1 <= tier <= 5:", "or not 1 <= tier <= 6:", CORR),
    ("parse: reason optional", CO, "    if not isinstance(value, str) or not value.strip():\n        raise CorridorRefused(f\"{where}: {what} is required\")", "    if not isinstance(value, str):\n        raise CorridorRefused(f\"{where}: {what} is required\")", CORR),
    ("fixture: first underpass is LTS 4", FX, '"tier": 5,', '"tier": 4,', CORR),
    ("fixture: first underpass sides Avoid", FX, '"tier": 4,\n          "reason": "The owner (286): \\"The side', '"tier": 5,\n          "reason": "The owner (286): \\"The side', CORR),
    ("fixture: second underpass sides LTS 4", FX, '"tier": 3,', '"tier": 4,', CORR),
    ("fixture: the 100 m trim is lost", FX, "[569, 977]", "[569, 1077]", CORR),
    ("fixture: first underpass starts 40 m early", FX, "[569, 977]", "[529, 977]", CORR),
    ("fixture: second underpass starts 40 m early", FX, "[1484, 2109]", "[1440, 2109]", CORR),
    ("fixture: second underpass ends early", FX, "[1484, 2109]", "[1484, 1900]", CORR),
    ("street: quadrant kept in the name", ST, "        if key.endswith(suffix):", "        if False:", CORR + SMOOTH),
    # --- smoothing ---------------------------------------------------------------------
    ("smooth: window doubled", SM, "<= window_m**2", "<= (2 * window_m) ** 2", SMOOTH),
    ("smooth: window halved", SM, "<= window_m**2", "<= (window_m / 2) ** 2", SMOOTH),
    ("smooth: two ways are enough", SM, "if len(near) < min_ways or total < min_length_m:", "if len(near) < 2 or total < min_length_m:", SMOOTH),
    ("smooth: no least length", SM, "if len(near) < min_ways or total < min_length_m:", "if len(near) < min_ways:", SMOOTH),
    ("smooth: median counted by ways", SM, "        run += weight\n        if run >= half:", "        run += 1\n        if run >= half:", SMOOTH),
    ("smooth: jurisdictions mixed", SM, "group = (key, lookup(way.osm_id))", "group = (key, None)", SMOOTH + STAGE),
    ("smooth: driveways vote", SM, 'EXCLUDED_HIGHWAY = TRAIL_CLASS_HIGHWAY | {"service"}', "EXCLUDED_HIGHWAY = TRAIL_CLASS_HIGHWAY", SMOOTH),
    ("smooth: trails vote", SM, 'EXCLUDED_HIGHWAY = TRAIL_CLASS_HIGHWAY | {"service"}', 'EXCLUDED_HIGHWAY = {"service"}', SMOOTH),
    ("smooth: unchanged counts reported", SM, "        if median == match.aadt:\n            continue\n", "", SMOOTH),
    ("smooth: raw count lost", SM, "replace(match, aadt=median, raw_aadt=match.aadt)", "replace(match, aadt=median)", SMOOTH + STAGE),
    ("smooth: midpoint not half way", SM, "half, run = total / 2, 0.0", "half, run = total / 3, 0.0", SMOOTH),
    ("smooth: quiet gate off by one", SM, "(VOLUME_QUIET + 1, VOLUME_BUSY)", "(VOLUME_QUIET, VOLUME_BUSY)", SMOOTH),
    ("smooth: busy gate off by one", SM, "(VOLUME_QUIET + 1, VOLUME_BUSY)", "(VOLUME_QUIET + 1, VOLUME_BUSY + 1)", SMOOTH),
    ("smooth: stage ignores the veto", RUN, "        if context.smooth_volume:\n", "        if True:\n", STAGE),
    ("smooth: stage marks every replaced way", RUN, "if aadt_smoothing.crosses_volume_gate(item.raw, item.smoothed)", "if True", STAGE),
    ("smooth: stage smooths before the states", RUN, "context.ways, context.aadt_by_way, state_of.get", "context.ways, context.aadt_by_way, lambda _: None", STAGE),
    # --- re-match ----------------------------------------------------------------------
    ("rematch: tolerance far too wide", RM, "TOLERANCE_M = 6.0", "TOLERANCE_M = 60.0", REMATCH),
    ("rematch: tolerance far too tight", RM, "TOLERANCE_M = 6.0", "TOLERANCE_M = 0.5", REMATCH),
    ("rematch: candidates need not lie along it", RM, "MIN_CONTAINED = 0.9", "MIN_CONTAINED = 0.0", REMATCH),
    ("rematch: coverage not needed", RM, "if covered / len(target_samples) < MIN_COVERAGE:", "if False:", REMATCH),
    ("rematch: street name ignored", RM, "if street_key(way.tags.get(\"name\")) != want_name:", "if False:", REMATCH),
    ("rematch: highway class ignored", RM, 'if (way.tags.get("highway") or None) != want_highway:', "if False:", REMATCH),
    ("rematch: merged longer way accepted", RM, "elif near * SAMPLE_M > NEIGHBOUR_TOLERANCES * tolerance_m:", "elif False:", REMATCH),
    ("rematch: parallel ways accepted", RM, "if overlap * SAMPLE_M > PARALLEL_TOLERANCES * tolerance_m:", "if False:", REMATCH),
    ("rematch: neighbours need no tolerance", RM, "NEIGHBOUR_TOLERANCES = 1.25", "NEIGHBOUR_TOLERANCES = 0.0", REMATCH),
    ("rematch: collision with a different row ignored", RM, "if other is not None and other.value != row.value:", "if False:", REMATCH),
    ("rematch: rival missing rows ignored", RM, "if any(missing[i].value != row.value for i in rivals):", "if False:", REMATCH),
    ("rematch: covered rows duplicated", RM, "if (row.kind, way_id) not in present)", "if True)", REMATCH),
    ("rematch: drift not looked for", RM, "if way is not None and fp is not None and not still_matches(fp, way, tolerance_m):", "if False:", REMATCH),
    ("rematch: duplicate targets emitted", RM, "            if key not in emitted:", "            if True:", REMATCH),
    ("rematch: a failed row is dropped", RM, "        if index is None or index not in resolved:\n            out.append(row)\n            continue", "        if index is None or index not in resolved:\n            continue", REMATCH),
    ("rematch: simplification keeps nothing", RM, "SIMPLIFY_M = 1.0", "SIMPLIFY_M = 1000.0", REMATCH),
    ("rematch: superseded entries not read", RM, '*document.get("superseded", [])', "", REMATCH),
    ("rematch: stored fingerprint not attached", OV, "fingerprint=fingerprints.get((row.kind, row.osm_way_id)),", "fingerprint=None,", REMATCH),
    ("rematch: stage does not re-match", RUN, "rows, rematch_report = rematch.resolve(rows, context.ways_by_id)", "rows, rematch_report = rows, rematch.RematchReport()", REMATCH),
    ("rematch: stage writes no report", RUN, "        write_rematch_report(rematch_report)\n", "", REMATCH),
    ("rematch: failures not counted", RUN, "rematch_failed=len(rematch_report.failed),", "rematch_failed=0,", REMATCH),
]  # fmt: skip


def _passes(copy: Path, tests: list[str]) -> bool:
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
