#!/usr/bin/env python3
"""Mutants on the trail seek (`core.trailseek`) and its place in the search
(`core.refine`, `core.routing`).

FOLLOWUP-TRAIL-SEEK (OWNER-DECISIONS 194, 201). A mutation pass run against WHOLE
test files, as `scripts/mutants_intersections.py` does: a mutant is killed when
any test in the files named for it fails. It works on a copy of the repository
and runs each test file in a process of its own:

    scripts/mutants_trailseek.py [--only NAME] [--list] [--check]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"):
PGDATABASE should name a private database. Each line of MUTANTS is
(name, file, old text, new text, test files); `old` must occur exactly once.
Survivors are printed last and the exit status is the number of them.

Two mutants that were tried and are not in the list are equivalent, not survivors:
the networks' least length (`total += length / 2`, 300 m) and the `if not
line.starts` return in `find_corridors` are optimisations, since a network under
500 m cannot replace the 500 m a corridor needs and a route with no busy stretch
scores nothing above the least score.
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

SEEK = ["tests/test_trailseek.py"]
REFINE = ["tests/test_refine.py"]
PLAN = ["tests/test_route_intersections.py"]

TS = "src/core/trailseek.py"
RF = "src/core/refine.py"
RT = "src/core/routing.py"

NL = "\n"

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- the route line ----------------------------------------------------
    (
        "busy: weight ignored",
        TS,
        "before += (s - self.starts[i]) * self.weights[i]",
        "before += (s - self.starts[i]) * 1.0",
        SEEK,
    ),
    (
        "busy: part span from the wrong side",
        TS,
        "if i < len(self.starts) and s > self.starts[i]:",
        "if i < len(self.starts) and s < self.starts[i]:",
        SEEK,
    ),
    (
        "busy: spans not scaled",
        TS,
        "scale = self.length / traced_m if traced_m else 1.0",
        "scale = 1.0",
        SEEK,
    ),
    (
        "nearest: radius doubled",
        TS,
        "if d <= self.radius and (best is None or d < best[1]):",
        "if d <= 2 * self.radius and (best is None or d < best[1]):",
        SEEK,
    ),
    (
        "nearest: first not nearest",
        TS,
        "if d <= self.radius and (best is None or d < best[1]):",
        "if d <= self.radius and best is None:",
        SEEK,
    ),
    ("nearest: one cell only", TS, "for i in (cx - 1, cx, cx + 1):", "for i in (cx,):", SEEK),
    ("route: gaps not filled", TS, "for k in range(1, n):", "for k in range(1, 1):", SEEK),
    (
        "band: min and max swapped",
        TS,
        "return min(BAND_MAX_M, max(BAND_MIN_M, BAND_FRACTION * span_m))",
        "return max(BAND_MAX_M, min(BAND_MIN_M, BAND_FRACTION * span_m))",
        SEEK,
    ),
    (
        "cap: min for max",
        TS,
        "return max(DETOUR_CAP_MIN_M, DETOUR_CAP_SPAN * span_m)",
        "return min(DETOUR_CAP_MIN_M, DETOUR_CAP_SPAN * span_m)",
        SEEK,
    ),
    # --- the graph and the best corridor -------------------------------------
    (
        "networks: no limit",
        TS,
        "if total >= MIN_NETWORK_M][:MAX_NETWORKS]",
        "if total >= MIN_NETWORK_M]",
        SEEK,
    ),
    (
        "networks: shortest first",
        TS,
        "found.sort(key=lambda item: (-item[0], min(item[1])))",
        "found.sort(key=lambda item: (item[0], min(item[1])))",
        SEEK,
    ),
    (
        "graph: nodes not snapped",
        TS,
        "return round(lon / SNAP_DEG), round(lat / SNAP_DEG)",
        "return round(lon / (SNAP_DEG / 1000)), round(lat / (SNAP_DEG / 1000))",
        SEEK,
    ),
    (
        "entry: distance along ignored",
        TS,
        "label[node] = rate * line.busy_to(s) + DETOUR_WEIGHT * (s + c)",
        "label[node] = rate * line.busy_to(s) + DETOUR_WEIGHT * c",
        SEEK,
    ),
    (
        "exit: wrong side of the join",
        TS,
        "value = rate * line.busy_to(s_out) + DETOUR_WEIGHT * (s_out - c_out) - cost",
        "value = rate * line.busy_to(s_out) + DETOUR_WEIGHT * (s_out + c_out) - cost",
        SEEK,
    ),
    (
        "exit: exposure not counted",
        TS,
        "value = rate * line.busy_to(s_out) + DETOUR_WEIGHT * (s_out - c_out) - cost",
        "value = DETOUR_WEIGHT * (s_out - c_out) - cost",
        SEEK,
    ),
    ("replaced: no least", TS, "replaced >= MIN_REPLACED_M", "replaced >= 0", SEEK),
    ("cap: not applied", TS, "and detour <= cap_m", "and detour <= cap_m * 1000", SEEK),
    ("trail: length is free", TS, "moved = cost + DETOUR_WEIGHT * length", "moved = cost", SEEK),
    ("detour: negative kept", TS, "detour_m=max(0.0, detour),", "detour_m=detour,", SEEK),
    (
        "corridor: score not required",
        TS,
        "if best is not None and best.gain_m >= MIN_EXPOSURE_M and best.score >= MIN_SCORE_M:",
        "if best is not None and best.gain_m >= MIN_EXPOSURE_M:",
        SEEK,
    ),
    (
        "corridor: exposure not required",
        TS,
        "if best is not None and best.gain_m >= MIN_EXPOSURE_M and best.score >= MIN_SCORE_M:",
        "if best is not None and best.score >= MIN_SCORE_M:",
        SEEK,
    ),
    (
        "corridors: any span",
        TS,
        "if plane.span < SEEK_MIN_SPAN_M or len(route) < 2:",
        "if len(route) < 2:",
        SEEK,
    ),
    (
        "corridors: worst first",
        TS,
        "found.sort(key=lambda c: (-c.score, c.entry))",
        "found.sort(key=lambda c: (c.score, c.entry))",
        SEEK,
    ),
    # --- what is asked for ----------------------------------------------------
    (
        "overlap: no gap",
        TS,
        "return not (a.t_out + ORDER_GAP_M <= b.t_in or b.t_out + ORDER_GAP_M <= a.t_in)",
        "return not (a.t_out <= b.t_in or b.t_out <= a.t_in)",
        SEEK,
    ),
    (
        "propose: second overlaps",
        TS,
        "second = next((c for c in corridors[1:] if not overlaps(first, c)), None)",
        "second = next((c for c in corridors[1:] if overlaps(first, c)), None)",
        SEEK,
    ),
    ("propose: no limit", TS, "    return out[:limit]", "    return out", SEEK),
    (
        "propose: pair not in order",
        TS,
        "out.append(Proposal(tuple(sorted((first, second), key=lambda c: c.t_in))))",
        "out.append(Proposal((first, second)))",
        SEEK,
    ),
    (
        "vias: short trails inset",
        TS,
        "corridor.trail_m < 4 * VIA_INSET_M",
        "corridor.trail_m < 0",
        SEEK,
    ),
    (
        "vias: inset from the same end",
        TS,
        "return [_along(path, VIA_INSET_M), _along(path[::-1], VIA_INSET_M)]",
        "return [_along(path, VIA_INSET_M), _along(path, VIA_INSET_M)]",
        SEEK,
    ),
    ("vias: inset ignores the bend", TS, "f = (metres - walked) / d", "f = metres / d", SEEK),
    # --- the table ---------------------------------------------------------------
    (
        "table: lts 3 allowed",
        TS,
        '"AND (s.stress_tier <= 2 OR %s = ANY(s.car_free_when))"',
        '"AND (s.stress_tier <= 3 OR %s = ANY(s.car_free_when))"',
        SEEK,
    ),
    (
        "table: lanes are corridors",
        TS,
        "(s.facility IN ('path', 'protected') OR",
        "(s.facility IN ('path', 'protected', 'lane') OR",
        SEEK,
    ),
    (
        "table: gravel not left out",
        TS,
        'where += " AND s.is_unpaved IS NOT TRUE"',
        'where += " AND s.is_unpaved IS NOT FALSE"',
        SEEK,
    ),
    (
        "table: query reaches too far",
        TS,
        "degrees = width_m / 85_000.0",
        "degrees = width_m / 8_500.0",
        SEEK,
    ),
    (
        "band: ends not respected",
        TS,
        "beside = 0.0 <= plane.along(x, y) <= plane.span and abs(plane.across(x, y)) <= width_m",
        "beside = abs(plane.across(x, y)) <= width_m",
        SEEK,
    ),
    (
        "band: route not a guide",
        TS,
        "if beside or line.nearest(x, y) is not None:",
        "if beside:",
        SEEK,
    ),
    (
        "runs: from half the rate",
        TS,
        "SEEK_FROM_RATE = 10.0",
        "SEEK_FROM_RATE = 5.0",
        SEEK + REFINE,
    ),
    # --- in the search ---------------------------------------------------------------
    (
        "spans: tier 4 counts once",
        RF,
        'EXPOSURE_WEIGHTS = {"3": 1.0, "4": 2.0, "5": 3.0}',
        'EXPOSURE_WEIGHTS = {"3": 1.0, "4": 1.0, "5": 3.0}',
        REFINE,
    ),
    (
        "spans: half the edge",
        RF,
        "spans.append((along, along + piece.metres, weight))",
        "spans.append((along, along + piece.metres / 2, weight))",
        REFINE,
    ),
    ("spans: traced length lost", RF, "return spans, along or None", "return spans, None", REFINE),
    (
        "seek: runs without the flag",
        RF,
        "    if ctx.seek:" + NL + "        best, best_trip = _seek(",
        "    if not ctx.seek:" + NL + "        best, best_trip = _seek(",
        REFINE,
    ),
    (
        "seek: more than two points",
        RF,
        "if len(ctx.points) != 2 or len(locations) != 2:",
        "if len(locations) != 2:",
        REFINE,
    ),
    (
        "seek: any span",
        RF,
        "    if span < trailseek.SEEK_MIN_SPAN_M:" + NL + '        seek["limited"] = "span"',
        "    if False:" + NL + '        seek["limited"] = "span"',
        REFINE,
    ),
    (
        "seek: budget is the larger",
        RF,
        "stop_at = min(" + NL + "        routing.clock() + trailseek.SEEK_BUDGET_S,",
        "stop_at = max(" + NL + "        routing.clock() + trailseek.SEEK_BUDGET_S,",
        REFINE,
    ),
    (
        "seek: route not thinned",
        RF,
        "step = max(1, len(shape) // 400)",
        "step = max(1, len(shape) // 40000)",
        REFINE,
    ),
    ("seek: exclusions dropped", RF, "kept = list(ctx.kept_excludes)", "kept = []", REFINE),
    ("seek: no second ask without", RF, "if read is None and kept:", "if False:", REFINE),
    (
        "seek: exclusions not remembered",
        RF,
        "            ctx.kept_excludes = [t.point for t in excluded]",
        "            ctx.kept_excludes = []",
        REFINE,
    ),
    (
        "seek: busier is fine",
        RF,
        "        busier = read.exposure_m > first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M"
        + NL
        + "        score = read.score(ctx)"
        + NL
        + '        tried["score_gain_s"]',
        "        busier = False"
        + NL
        + "        score = read.score(ctx)"
        + NL
        + '        tried["score_gain_s"]',
        REFINE,
    ),
    (
        "seek: no margin",
        RF,
        "        elif score < best_score - IMPROVEMENT_EPS_S:"
        + NL
        + '            tried["outcome"] = "taken"',
        "        elif score < best_score:" + NL + '            tried["outcome"] = "taken"',
        REFINE,
    ),
    (
        "seek: unread is taken",
        RF,
        '            tried["outcome"] = "unread"' + NL + "            continue",
        '            tried["outcome"] = "unread"',
        REFINE,
    ),
    (
        "seek: best not updated",
        RF,
        "            best, best_trip, best_score = read, candidate, score"
        + NL
        + '            seek["taken"] = True',
        "            best, best_trip = read, candidate" + NL + '            seek["taken"] = True',
        REFINE,
    ),
    (
        "seek: no least per candidate",
        RF,
        "        if stop_at - routing.clock() < trailseek.SEEK_ROUND_MIN_S:"
        + NL
        + '            seek["limited"] = "time"'
        + NL
        + "            break",
        "        if False:"
        + NL
        + '            seek["limited"] = "time"'
        + NL
        + "            break",
        REFINE,
    ),
    (
        "through: type break",
        RF,
        '*({"lon": lon, "lat": lat, "type": "through"} for lon, lat in vias),',
        '*({"lon": lon, "lat": lat, "type": "break"} for lon, lat in vias),',
        REFINE,
    ),
    (
        "plan: seek never",
        RT,
        "seek=trailseek.seek_for(presets.calm_rate_for(stress_dial)),",
        "seek=False,",
        PLAN,
    ),
    (
        "plan: seek always",
        RT,
        "seek=trailseek.seek_for(presets.calm_rate_for(stress_dial)),",
        "seek=True,",
        PLAN,
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
