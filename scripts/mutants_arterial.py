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
declares `cycleway*=separate`, which `has_separate_bikeway` already exempts. And
`DEFAULT_THROUGH_MAX_OFFSET_M` (7 to 12 m), which the fixture overrides with its own
`through_max_offset_m` of 7.0; the fixture's value is mutated instead.

The `r0:` mutants are the reviewer's of ARTERIAL review r0 (its `my_mutants.py`), each
threshold moved past its tested edge; the `SF1:`, `SF2:` and `SF4:` ones are the r1
revision's own.
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
JUNC = ["tests/test_junctions.py"]
WRITE = ["tests/test_writers.py"]

CO = "src/routemaker/corridors.py"
FX = "fixtures/corridors/2026-10-04-owner-north-capitol-underpasses.json"
SM = "src/pipeline/aadt_smoothing.py"
ST = "src/routemaker/streets.py"
RM = "src/pipeline/rematch.py"
OV = "src/pipeline/overrides.py"
RUN = "src/pipeline/run.py"
JN = "src/core/junctions.py"
WR = "src/pipeline/writers.py"

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
    ("smooth: equal counts reported", SM, "if median >= match.aadt:", "if median > match.aadt:", SMOOTH),
    ("smooth: raises allowed", SM, "if median >= match.aadt:", "if median == match.aadt:", SMOOTH + STAGE),
    ("smooth: lowers refused", SM, "if median >= match.aadt:", "if median <= match.aadt:", SMOOTH + STAGE),
    ("smooth: raw count lost", SM, "replace(match, aadt=median, raw_aadt=match.aadt)", "replace(match, aadt=median)", SMOOTH + STAGE),
    ("smooth: midpoint not half way", SM, "half, run = total / 2, 0.0", "half, run = total / 3, 0.0", SMOOTH),
    ("smooth: quiet gate off by one", SM, "(VOLUME_QUIET + 1, VOLUME_BUSY,", "(VOLUME_QUIET, VOLUME_BUSY,", SMOOTH),
    ("smooth: busy gate off by one", SM, "(VOLUME_QUIET + 1, VOLUME_BUSY,", "(VOLUME_QUIET + 1, VOLUME_BUSY + 1,", SMOOTH),
    ("smooth: urban two-way gate off by one", SM, "URBAN_TWO_WAY_BUSY_AADT + 1)", "URBAN_TWO_WAY_BUSY_AADT)", SMOOTH),
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
    ("rematch: parallel ways accepted", RM, "if overlap > min(PARALLEL_TOLERANCES * tolerance_m, PARALLEL_SHARE * shorter):", "if False:", REMATCH),
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
    # --- r0: the reviewer's boundary mutants ---------------------------------------
    ("r0: fixture through offset 7 -> 12 m", FX, '"through_max_offset_m": 7.0', '"through_max_offset_m": 12.0', CORR),
    ("r0: fixture through offset 7 -> 4 m", FX, '"through_max_offset_m": 7.0', '"through_max_offset_m": 4.0', CORR),
    ("r0: fixture side offset 20 -> 30 m", FX, '"side_max_offset_m": 20.0', '"side_max_offset_m": 30.0', CORR),
    ("r0: corridor bearing 40 -> 80 degrees", CO, "DEFAULT_MAX_BEARING_DEG = 40.0", "DEFAULT_MAX_BEARING_DEG = 80.0", CORR),
    ("r0: share in range 0.5 -> 0.3", CO, "MIN_SHARE_IN_RANGE = 0.5", "MIN_SHARE_IN_RANGE = 0.3", CORR),
    ("r0: path facility not exempt", CO, "if kind in (Facility.PROTECTED, Facility.PATH):", "if kind in (Facility.PROTECTED,):", CORR),
    ("r0: protected facility not exempt", CO, "if kind in (Facility.PROTECTED, Facility.PATH):", "if kind in (Facility.PATH,):", CORR),
    ("r0: smoothing replaces a higher median", SM, "if median >= match.aadt:", "if False:", SMOOTH),
    ("r0: smoothing least length 250 -> 100 m", SM, "MIN_LENGTH_M = 250.0", "MIN_LENGTH_M = 100.0", SMOOTH),
    ("r0: smoothing least ways 3 -> 4", SM, "MIN_WAYS = 3", "MIN_WAYS = 4", SMOOTH),
    ("r0: smoothing window 400 -> 300 m", SM, "WINDOW_M = 400.0", "WINDOW_M = 300.0", SMOOTH),
    ("r0: smoothing window 400 -> 500 m", SM, "WINDOW_M = 400.0", "WINDOW_M = 500.0", SMOOTH),
    ("r0: re-match tolerance 6 -> 9 m", RM, "TOLERANCE_M = 6.0", "TOLERANCE_M = 9.0", REMATCH),
    ("r0: re-match tolerance 6 -> 4 m", RM, "TOLERANCE_M = 6.0", "TOLERANCE_M = 4.0", REMATCH),
    ("r0: re-match contained 0.9 -> 0.6", RM, "MIN_CONTAINED = 0.9", "MIN_CONTAINED = 0.6", REMATCH),
    ("r0: re-match coverage 0.9 -> 0.6", RM, "MIN_COVERAGE = 0.9", "MIN_COVERAGE = 0.6", REMATCH),
    ("r0: re-match parallel 2.5 -> 10 tolerances", RM, "PARALLEL_TOLERANCES = 2.5", "PARALLEL_TOLERANCES = 10.0", REMATCH),
    ("r0: re-match neighbour 1.25 -> 3 tolerances", RM, "NEIGHBOUR_TOLERANCES = 1.25", "NEIGHBOUR_TOLERANCES = 3.0", REMATCH),
    ("r0: no-fingerprint row left out of the report", RM, '"no fingerprint is stored for this row; it cannot be re-matched",', '"",', REMATCH),
    ("r0: drifted reported as failed", RM, 'OUTCOME_DRIFTED = "drifted"', 'OUTCOME_DRIFTED = "failed"', REMATCH),
    # --- SF1: the junction keeps the raw count and the pre-smoothing tier ----------
    ("SF1: segment publishes the median", RUN, "volume_aadt=match.raw_aadt,", "volume_aadt=match.aadt,", STAGE),
    ("SF1: no pre-smoothing tier kept", RUN, "unsmoothed_tier=unsmoothed.tier if unsmoothed.tier > current.tier else None,", "unsmoothed_tier=None,", STAGE),
    ("SF1: pre-smoothing tier kept where it is no higher", RUN, "if unsmoothed.tier > current.tier else None,", "if unsmoothed.tier >= current.tier else None,", STAGE),
    ("SF1: writer drops the pre-smoothing tier", WR, '_tier_or_none(getattr(row["stress"], "unsmoothed_tier", None)),', "None,", WRITE),
    ("SF1: junction reads the link's tier only", JN, 'f"GREATEST(s.stress_tier, s.{UNSMOOTHED_TIER_COLUMN})"', '"s.stress_tier"', JUNC),
    ("SF1: corridor keeps a stale pre-smoothing tier", CO, "unsmoothed_tier=None,", "", STAGE),
    # --- SF2: re-match direction, length and short parallels -----------------------
    ("SF2: bearing not checked", RM, "if off > MAX_BEARING_DEG:", "if False:", REMATCH),
    ("SF2: bearing 30 -> 60 degrees", RM, "MAX_BEARING_DEG = 30.0", "MAX_BEARING_DEG = 60.0", REMATCH),
    ("SF2: bearing 30 -> 10 degrees", RM, "MAX_BEARING_DEG = 30.0", "MAX_BEARING_DEG = 10.0", REMATCH),
    ("SF2: length not checked", RM, "if not stored / MAX_LENGTH_RATIO <= total <= stored * MAX_LENGTH_RATIO:", "if False:", REMATCH),
    ("SF2: length ratio 1.25 -> 2", RM, "MAX_LENGTH_RATIO = 1.25", "MAX_LENGTH_RATIO = 2.0", REMATCH),
    ("SF2: no lower length bound", RM, "if not stored / MAX_LENGTH_RATIO <= total", "if not 0 <= total", REMATCH),
    ("SF2: parallel share 0.5 -> 1", RM, "PARALLEL_SHARE = 0.5", "PARALLEL_SHARE = 1.0", REMATCH),
    ("SF2: parallel threshold absolute only", RM, "min(PARALLEL_TOLERANCES * tolerance_m, PARALLEL_SHARE * shorter)", "PARALLEL_TOLERANCES * tolerance_m", REMATCH),
    ("SF2: longitude padded as latitude", RM, "return tolerance_m / (111_000.0 * math.cos(math.radians(lat)))", "return tolerance_m / 111_000.0", REMATCH),
    # --- SF4: reports and the corridor folder ----------------------------------------
    ("SF4: missing corridor folder read as none", CO, "if not folder.is_dir():", "if False:", CORR),
    ("SF4: smoothing report not where documented", RUN, 'SMOOTHING_REPORT_NAME = "aadt-smoothing.csv"', 'SMOOTHING_REPORT_NAME = "aadt-smoothing.txt"', STAGE),
    ("SF4: corridor report not where documented", RUN, 'CORRIDOR_REPORT_NAME = "named-corridors.md"', 'CORRIDOR_REPORT_NAME = "corridors.md"', STAGE),
    ("SF4: vetoed smoothing leaves last week's report", RUN, "context.smoothing_report or aadt_smoothing.SmoothingReport()", "context.smoothing_report", STAGE),
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
