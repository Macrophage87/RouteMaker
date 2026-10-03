#!/usr/bin/env python3
"""Mutants on FOLLOWUP-LONG-CALM: the order the top of the slider ranks by, the longest
ride, the effort model, the legs a long plan is cut into and how it shares the longest
ride among them, the routes to choose from, the loop, and the hills choice's hold.

OWNER-DECISIONS 256-266. A mutation pass run against WHOLE test files, as
`scripts/mutants_trailseek.py` does: a mutant is killed when any test in the files named
for it fails. It works on a copy of the repository and runs each test file in a process of
its own, under a timeout:

    scripts/mutants_longcalm.py [--only NAME] [--list] [--check]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"): PGDATABASE
should name a private database. Each line of MUTANTS is (name, file, old text, new text,
test files); `old` must occur exactly once. Survivors are printed last and the exit status
is the number of them.
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

LC = ["tests/test_longcalm.py"]
EF = ["tests/test_effort.py"]
LP = ["tests/test_loop.py"]
AP = ["tests/test_longcalm_api.py"]
PS = ["tests/test_presets.py"]
HD = ["tests/test_route_dials.py"]

RF = "src/core/refine.py"
RT = "src/core/routing.py"
PR = "src/core/presets.py"
LS = "src/core/legsplit.py"
EFF = "src/routemaker/effort.py"
API = "src/core/api.py"

# The longest a test file may take against a mutant (test_route_dials takes about 150 s).
TEST_TIMEOUT_S = 300
NL = "\n"

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- the order (258-261) ----------------------------------------------------
    (
        "order: the top figure is LTS 4 alone",
        RF,
        "        return self.lts4_m + self.red_m",
        "        return self.lts4_m",
        LC,
    ),
    (
        "order: the second figure is LTS 3 alone",
        RF,
        "        return self.lts3_m + self.orange_m",
        "        return self.lts3_m",
        LC,
    ),
    (
        "order: the junction kinds are swapped",
        RF,
        "e.severity == severity) / model.FEET_PER_METRE",
        "e.severity != severity) / model.FEET_PER_METRE",
        LC,
    ),
    (
        "order: a gain at a level must beat its step by nothing",
        RF,
        "        if have - got > step:",
        "        if have - got > 0:",
        LC,
    ),
    (
        "order: a loss within the step at a level counts",
        RF,
        "        if got - have > step:",
        "        if got - have > 0:",
        LC,
    ),
    (
        "order: the tolerances are ten times",
        RF,
        "MAXCALM_STEPS = (15.0, 50.0, 50.0)",
        "MAXCALM_STEPS = (150.0, 500.0, 500.0)",
        LC,
    ),
    (
        "order: the Hills slider is not blended in",
        RF,
        "    return (1 - w) * read.length_m + w * effort - ctx.hills_seek_weight * effort",
        "    return read.length_m - ctx.hills_seek_weight * effort",
        LC,
    ),
    (
        "order: the Hills slider blends the length with itself",
        RF,
        "    return (1 - w) * read.length_m + w * effort - ctx.hills_seek_weight * effort",
        "    return (1 - w) * read.length_m + w * read.length_m - ctx.hills_seek_weight * effort",
        LC,
    ),
    ("order: the seek half's hook does nothing", RF, "- ctx.hills_seek_weight * effort", "", LC),
    # --- the longest ride (256) --------------------------------------------------
    (
        "longest: a route exactly the limit is too long",
        RF,
        "    return ctx.max_m is not None and length_m > ctx.max_m",
        "    return ctx.max_m is not None and length_m >= ctx.max_m",
        LC,
    ),
    (
        "longest: the halves of a round are not tried",
        RF,
        "            attempts.extend(excluded + half for half in _halves(new))",
        "            pass",
        LC,
    ),
    (
        "longest: a round past it is called no route",
        RF,
        '                info["limited"] = "max_distance" if over else "no_route"',
        '                info["limited"] = "no_route"',
        LC,
    ),
    (
        "longest: a hold refusal uses up the patience",
        RF,
        "        elif not held:",
        "        else:",
        LC,
    ),
    (
        "longest: the default is the smaller",
        PR,
        "    return max(first_m * DEFAULT_MAX_RATIO, first_m + DEFAULT_MAX_EXTRA_M)",
        "    return min(first_m * DEFAULT_MAX_RATIO, first_m + DEFAULT_MAX_EXTRA_M)",
        PS,
    ),
    (
        "longest: the top is any position past the old top",
        PR,
        "    return calm_rate_for(stress) >= CALM_RATE_MAX",
        "    return calm_rate_for(stress) > 0",
        PS,
    ),
    (
        "longest: a longer route than the limit is let through in the fit",
        RT,
        "            if probe_m <= rider_max_m:",
        "            if probe_m <= rider_max_m * 2:",
        AP,
    ),
    (
        "longest: the bisection stays at the rung",
        RT,
        "            middle = (over + fits) // 2",
        "            middle = fits",
        AP,
    ),
    # --- the hold on the top figure (250, 259) -----------------------------------
    (
        "hold: only the LTS 4 metres are held",
        RF,
        "    legs = top_by_leg(read)",
        "    legs = lts4_by_leg(read)",
        LC,
    ),
    (
        "hold: a leg's red junctions are not counted",
        RF,
        "                out[k] += event.cost_ft / model.FEET_PER_METRE",
        "                out[k] += 0.0",
        LC,
    ),
    (
        "hold (hills): the alternate's LTS 4 is not held",
        RT,
        "    return exposure.hold_lts4 and held[1] > reference[1] + refine.LTS4_SLACK_M",
        "    return False",
        HD,
    ),
    (
        "hold (hills): the hold is the wrong way",
        RT,
        "    return exposure.hold_lts4 and held[1] > reference[1] + refine.LTS4_SLACK_M",
        "    return exposure.hold_lts4 and held[1] < reference[1] + refine.LTS4_SLACK_M",
        HD,
    ),
    (
        "hold (hills): the plan's weights are not used for the choice",
        RT,
        "        own = _exposure(variant, costing, trips[0], when, deadline, traces, exposure)",
        "        own = _exposure(variant, costing, trips[0], when, deadline, traces)",
        HD,
    ),
    (
        "hold (hills): the middle route's weights are not used",
        RT,
        "        calmer = _exposure(variant, middle_costing, middle, when, step, traces, exposure)",
        "        calmer = _exposure(variant, middle_costing, middle, when, step, traces)",
        HD,
    ),
    (
        "hold (hills): the middle's LTS 4 is not held",
        RT,
        "    if own is None or calmer is None or own[0] <= calmer[0]:\n        return trip, False\n    if _hold_refuses(calmer, own, exposure):\n        return trip, False",
        "    if own is None or calmer is None or own[0] <= calmer[0]:\n        return trip, False",
        HD,
    ),
    # --- the effort model (262-264) ----------------------------------------------
    (
        "effort: a descent is not floored",
        EFF,
        "    return max(force_n(grade, mass_kg) / flat_force_n(mass_kg), 1.0)",
        "    return force_n(grade, mass_kg) / flat_force_n(mass_kg)",
        EF,
    ),
    (
        "effort: the climb does not scale with the mass",
        EFF,
        "        + mass_kg * GRAVITY * math.sin(angle)",
        "        + MASS_KG * GRAVITY * math.sin(angle)",
        EF,
    ),
    ("effort: the grade is read sample by sample", EFF, "WINDOW_M = 300.0", "WINDOW_M = 1.0", EF),
    # --- cutting a long trip into legs ---------------------------------------------
    (
        "legs: a trip is cut into one leg",
        RF,
        "        count = legsplit.leg_count(haversine(Point(*a), Point(*b)))",
        "        count = 1",
        LC,
    ),
    (
        "legs: the count rounds down",
        LS,
        "    return max(1, math.ceil(span_m / target_m))",
        "    return max(1, int(span_m // target_m))",
        LC,
    ),
    (
        "legs: a cut takes the nearest place, not the one with room",
        LS,
        "key=lambda c: (-room[c[0]], abs(c[0] - ideal), c[0])",
        "key=lambda c: (abs(c[0] - ideal), c[0])",
        LC,
    ),
    (
        "legs: a leg may use only a share of the longest ride",
        RF,
        "            cap = _trip_m(firsts[j]) + slack",
        "            cap = _trip_m(firsts[j]) + slack / len(legs)",
        LC,
    ),
    (
        "legs: the detour goes to the first leg searched",
        RF,
        "                ratio = gain / max(added, 1.0)",
        "                ratio = -float(j)",
        LC,
    ),
    (
        "legs: the legs with no choice do not count against the limit",
        RF,
        "    total = fixed_m + sum(chain[p][1].length_m for chain, p in zip(chains, pos, strict=True))",
        "    total = sum(chain[p][1].length_m for chain, p in zip(chains, pos, strict=True))",
        LC,
    ),
    (
        "legs: the limit is not kept when sharing",
        RF,
        "                if max_m is not None and total + added > max_m:\n                    continue\n",
        "",
        LC,
    ),
    (
        "legs: the chain keeps options no calmer than the one before",
        RF,
        "        if better(option[1], chain[-1][1], ctx):",
        "        if True:",
        LC,
    ),
    (
        "legs: a leg whose share is under a round is searched",
        RF,
        "        if share < LONG_LEG_MIN_S:",
        "        if False:",
        LC,
    ),
    (
        "legs: the whole is answered however it compares",
        RF,
        "    if not changed or worse or too_long(length, ctx):",
        "    if not changed:",
        LC,
    ),
    (
        "legs: a long plan is not a long plan if it is a loop",
        RT,
        "    long_calm = not loop and long_calm_for(preset_name, points, stress_dial, long_ride, seeking)",
        "    long_calm = long_calm_for(preset_name, points, stress_dial, long_ride, seeking)",
        AP,
    ),
    (
        "legs: a long plan keeps the ordinary budget",
        RT,
        "    if long_ride or long_calm:",
        "    if long_ride:",
        AP,
    ),
    ("legs: a long ride is a long calm plan too", RT, "        and not long_ride\n", "", AP),
    (
        "legs: the slot is taken for a loop too",
        API,
        "        if not loop and routing.long_calm_for(",
        "        if routing.long_calm_for(",
        AP,
    ),
    # --- the routes to choose from (265) ---------------------------------------------
    (
        "routes: a near-duplicate is offered",
        RF,
        "            or not distinct_from(read, [c[1] for c in chosen])",
        "",
        LC,
    ),
    (
        "routes: a far worse route is offered",
        RF,
        "            or read.top_m > answer[1].top_m + ALT_TOP_BAND_M",
        "",
        LC,
    ),
    (
        "routes: different needs both tests",
        RF,
        "        if shared / min(mine, theirs) >= ALT_OVERLAP and mine - shared < ALT_DIFFERENT_M:",
        "        if shared / min(mine, theirs) >= ALT_OVERLAP or mine - shared < ALT_DIFFERENT_M:",
        LC,
    ),
    (
        "routes: shared road is matched by nothing",
        RF,
        "    ways = {piece.way_id for piece in b.pieces if piece.way_id}",
        "    ways = set()",
        LC,
    ),
    (
        "routes: the asking goes on past a route that adds nothing",
        RF,
        "        if len(picked) == len(chosen):" + NL + "            break",
        "        if len(picked) == len(chosen):" + NL + "            continue",
        LC,
    ),
    (
        "routes: only the answer's roads are avoided",
        RF,
        "        for _trip, read in chosen:" + NL + "            total = _road_m(read)",
        "        for _trip, read in chosen[:1]:" + NL + "            total = _road_m(read)",
        LC,
    ),
    (
        "routes: there is no limit on the asks",
        RF,
        "    while len(chosen) < ctx.alternates and asked < ALT_ASKS:",
        "    while len(chosen) < ctx.alternates and asked < 99:",
        LC,
    ),
    # --- the loop (266) ---------------------------------------------------------------
    (
        "loop: the way out is excluded to its ends",
        RF,
        "        if metres < CALM_MIN_EDGE_M or not _clear_of_ends(at, total, out.via_m):",
        "        if metres < CALM_MIN_EDGE_M:",
        LP,
    ),
    (
        "loop: an out-and-back is taken as a loop",
        RF,
        "    if best is None or best[4] >= LOOP_OUT_AND_BACK:",
        "    if best is None:",
        LP,
    ),
    (
        "loop: the most stressful within the share is kept",
        RF,
        "        ranked = (share > LOOP_OVERLAP_OK, whole.key(ctx) if share <= LOOP_OVERLAP_OK else share)",
        "        ranked = (share > LOOP_OVERLAP_OK, share)",
        LP,
    ),
    (
        "loop: the way out counts from its end",
        RF,
        "        if along < cut - 1e-6:",
        "        if along <= cut + 1e-6:",
        LP,
    ),
    (
        "loop: the search may share what it likes",
        RF,
        "    return overlap_share(read) > max(ctx.loop_overlap, LOOP_OVERLAP_OK) + 0.005",
        "    return False",
        LP,
    ),
    (
        "loop: a loop is not closed on the start",
        RT,
        "    return [*points, points[0]]",
        "    return points",
        LP,
    ),
    (
        "loop: the way back is the whole route",
        RT,
        "    start, end = leg_runs[-1]",
        "    start, end = 0, leg_runs[-1][1]",
        LP,
    ),
]


def _passes(copy: Path, tests: list[str]) -> bool:
    """Whether every test file passes, each in a process of its own, stopping at the first
    that fails; a file that has not finished in TEST_TIMEOUT_S is a failure."""
    for test in tests:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-x",
                    "-p",
                    "no:cacheprovider",
                    "-o",
                    "addopts=",
                    test,
                ],
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
        # A control: the unmutated files must pass in the copy, or "killed" would only mean
        # the copy cannot run its tests.
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
