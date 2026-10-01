#!/usr/bin/env python3
"""Mutants on the intersection model, the calm search and the slider's rescale.

FOLLOWUP-INTERSECTIONS (2026-10-01). A mutation pass over the expressions this
work added, run against WHOLE test files (not the test that was written for the
line): a mutant is killed when any test in the files named for it fails. It
works on a copy of the repository so the tree being worked on is never edited:

    scripts/mutants_intersections.py [--only NAME] [--list]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"):
PGDATABASE should name a private database. Each line of MUTANTS is
(name, file, old text, new text, test files); `old` must occur exactly once.
Survivors are printed last and the exit status is the number of them.

Four mutants that were tried and are not in the list are equivalent, not
survivors: `use_roads_for` and `calm_rate_for` are continuous at the positions
the first pass moved (70, 80: both branches give the same value there), and
`rounds = REFINE_MAX_ROUNDS if ctx.rate > 0 else CROSSING_ONLY_ROUNDS` is
guarded twice (crossing targets are only taken in the first
`CROSSING_ONLY_ROUNDS`), so removing either guard alone changes nothing.
`slip lane beside a quiet street` (always pricing the slip lane) is masked: a
junction with no busy road is reset to the neighbourhood cost afterwards.
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

PURE = ["tests/test_intersections.py"]
TRACE = ["tests/test_trace_junctions.py"]
DETOUR = ["tests/test_detour.py"]
SLIDER = ["tests/test_calm_slider.py", "tests/test_presets.py"]
REFINE = ["tests/test_refine.py"]
JUNCTIONS = ["tests/test_junctions.py"]
ROUTE = ["tests/test_route_intersections.py"]

INTERSECTIONS = "src/routemaker/intersections.py"
T = "src/routemaker/trace_junctions.py"
D = "src/routemaker/detour.py"
P = "src/core/presets.py"
R = "src/core/refine.py"
J = "src/core/junctions.py"
G = "src/core/routing.py"

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- the model ---------------------------------------------------------
    (
        "straight edge inclusive",
        INTERSECTIONS,
        "if abs(turn) <= STRAIGHT_MAX_DEG:",
        "if abs(turn) < STRAIGHT_MAX_DEG:",
        PURE,
    ),
    (
        "left and right swapped",
        INTERSECTIONS,
        "return Movement.RIGHT if turn > 0 else Movement.LEFT",
        "return Movement.RIGHT if turn < 0 else Movement.LEFT",
        PURE,
    ),
    (
        "band edge inclusive",
        INTERSECTIONS,
        "        if value <= limit:\n            return factor",
        "        if value < limit:\n            return factor",
        PURE,
    ),
    (
        "rural from the free side too",
        INTERSECTIONS,
        "if stopped_side and road.speed_mph >= RURAL_SPEED_MPH:",
        "if road.speed_mph >= RURAL_SPEED_MPH:",
        PURE,
    ),
    (
        "rural edge",
        INTERSECTIONS,
        "road.speed_mph >= RURAL_SPEED_MPH",
        "road.speed_mph > RURAL_SPEED_MPH",
        PURE,
    ),
    (
        "signal costs the stopped price",
        INTERSECTIONS,
        "        return SIGNALISED_CROSSING_FT[tier]\n    if control is Control.ALL_STOP",
        "        return STOPPED_CROSSING_FT[tier]\n    if control is Control.ALL_STOP",
        PURE,
    ),
    (
        "cross stop is not priority",
        INTERSECTIONS,
        "    if control is Control.CROSS_STOP:\n        return PRIORITY_SIDE_FT\n",
        "    if False:\n        return PRIORITY_SIDE_FT\n",
        PURE,
    ),
    (
        "busier rider road priority edge",
        INTERSECTIONS,
        "rider_tier > (road.tier or 0)",
        "rider_tier >= (road.tier or 0)",
        PURE,
    ),
    (
        "merge counts the lane it is in",
        INTERSECTIONS,
        "MERGE_FT_PER_LANE * max(lanes - 1, 0)",
        "MERGE_FT_PER_LANE * max(lanes, 0)",
        PURE,
    ),
    (
        "merge cap is a floor",
        INTERSECTIONS,
        "return min(MERGE_FT_PER_LANE * max(lanes - 1, 0), BOX_TURN_CAP_FT)",
        "return max(MERGE_FT_PER_LANE * max(lanes - 1, 0), BOX_TURN_CAP_FT)",
        PURE,
    ),
    (
        "one-way has oncoming traffic",
        INTERSECTIONS,
        "oncoming = 0.0 if road.oneway else LEFT_ACROSS_ONCOMING_FT[_tier(road)]",
        "oncoming = LEFT_ACROSS_ONCOMING_FT[_tier(road)]",
        PURE,
    ),
    (
        "signal does not lower a left",
        INTERSECTIONS,
        "            oncoming *= SIGNALISED_LEFT_FACTOR\n",
        "            oncoming *= 1.0\n",
        PURE,
    ),
    (
        "right off a busy road costs a left",
        INTERSECTIONS,
        '            take(RIGHT_FROM_BUSY_FT, "right_from", j.incoming)',
        '            take(left_from_ft(j.incoming, j.control), "right_from", j.incoming)',
        PURE,
    ),
    (
        "onto a busy road ignores the movement",
        INTERSECTIONS,
        "        factor = MOVEMENT_FACTOR_ONTO[j.movement.value]",
        "        factor = 1.0",
        PURE,
    ),
    (
        "marked crossing not discounted",
        INTERSECTIONS,
        "                value *= MARKED_CROSSING_FACTOR",
        "                value *= 1.0",
        PURE,
    ),
    (
        "marked crossing discounts a signal",
        INTERSECTIONS,
        "if j.marked_crossing and j.control in {Control.NONE, Control.STOP}:",
        "if j.marked_crossing:",
        PURE,
    ),
    (
        "red edge",
        INTERSECTIONS,
        "    if cost_ft >= RED_MIN_FT:",
        "    if cost_ft > RED_MIN_FT:",
        PURE,
    ),
    (
        "orange edge",
        INTERSECTIONS,
        "    if cost_ft >= ORANGE_MIN_FT:",
        "    if cost_ft > ORANGE_MIN_FT:",
        PURE,
    ),
    (
        "merge edge",
        INTERSECTIONS,
        "if group and event.m - group[-1].m > MERGE_WITHIN_M:",
        "if group and event.m - group[-1].m >= MERGE_WITHIN_M:",
        PURE,
    ),
    (
        "merged share",
        INTERSECTIONS,
        "extra = sum(e.cost_ft for e in group if e is not worst) * MERGED_SHARE",
        "extra = sum(e.cost_ft for e in group if e is not worst)",
        PURE,
    ),
    (
        "merge keeps the colour",
        INTERSECTIONS,
        "            severity = severity_of(cost) or worst.severity",
        "            severity = worst.severity",
        PURE,
    ),
    (
        "group red from LTS 5 only",
        INTERSECTIONS,
        "severity = RED if (about.tier or 0) >= 4 else ORANGE",
        "severity = RED if (about.tier or 0) >= 5 else ORANGE",
        PURE,
    ),
    (
        "group flags a left across a one-way",
        INTERSECTIONS,
        '        if kind in {"left_from", "left_across"} and about.oneway:\n            return None\n',
        "",
        PURE,
    ),
    (
        "two-way lanes not doubled",
        INTERSECTIONS,
        "return road.lanes if road.oneway else road.lanes * 2",
        "return road.lanes",
        PURE,
    ),
    (
        "all-way stop is not a neighbourhood stop",
        INTERSECTIONS,
        "cost = NEIGHBOURHOOD_STOP_FT if j.control in {Control.STOP, Control.ALL_STOP} else 0.0",
        "cost = NEIGHBOURHOOD_STOP_FT if j.control is Control.STOP else 0.0",
        PURE,
    ),
    (
        "penalty in feet",
        INTERSECTIONS,
        "return sum(event.cost_ft for event in events) / FEET_PER_METRE",
        "return sum(event.cost_ft for event in events)",
        PURE,
    ),
    (
        "left from busy ignored when the next road is busy",
        INTERSECTIONS,
        "    if j.incoming.busy and j.movement is not Movement.STRAIGHT:",
        "    if j.incoming.busy and not j.outgoing.busy and j.movement is not Movement.STRAIGHT:",
        PURE,
    ),
    (
        "left across from a quiet street",
        INTERSECTIONS,
        "elif j.movement is Movement.LEFT and not j.incoming.busy and not j.outgoing.busy:",
        "elif j.movement is Movement.LEFT and not j.outgoing.busy:",
        PURE,
    ),
    # --- the trace ---------------------------------------------------------
    (
        "a continuation is a junction",
        T,
        "if in_way == out_way and not others:",
        "if in_way == out_way or not others:",
        TRACE,
    ),
    (
        "approach is the start",
        T,
        "approach = shape[(begin + end) // 2]",
        "approach = shape[begin]",
        TRACE,
    ),
    (
        "cross road counts footways",
        T,
        "if use not in NOT_A_ROAD_USES)",
        "if use in NOT_A_ROAD_USES)",
        TRACE,
    ),
    (
        "slip lane needs both",
        T,
        "return SLIP_LANE_USE in (self.in_use, self.out_use) or any(",
        "return SLIP_LANE_USE in (self.in_use, self.out_use) and any(",
        TRACE,
    ),
    (
        "units ignored",
        T,
        'to_metres = 1609.344 if trace.get("units") == "miles" else 1000.0',
        "to_metres = 1000.0",
        TRACE,
    ),
    (
        "distance before the edge",
        T,
        '        along += float(here.get("length") or 0.0) * to_metres\n        end = here.get("end_shape_index")',
        '        end = here.get("end_shape_index")',
        TRACE,
    ),
    (
        "one-way means both",
        T,
        'other.get("driveability") not in (None, "both")',
        'other.get("driveability") in (None, "both")',
        TRACE,
    ),
    # --- the detour --------------------------------------------------------
    (
        "allowance is the smaller",
        D,
        "if route_m <= max(direct_m * SILENT_RATIO, direct_m + SILENT_EXTRA_M):",
        "if route_m <= min(direct_m * SILENT_RATIO, direct_m + SILENT_EXTRA_M):",
        DETOUR,
    ),
    ("strong edge", D, "    if ratio > STRONG_RATIO:", "    if ratio >= STRONG_RATIO:", DETOUR),
    (
        "warning edge",
        D,
        "    if ratio > NOTE_MAX_RATIO:",
        "    if ratio >= NOTE_MAX_RATIO:",
        DETOUR,
    ),
    (
        "fallback needs either",
        D,
        "        and route_m - straight_m >= STRAIGHT_LINE_EXTRA_M",
        "        or route_m - straight_m >= STRAIGHT_LINE_EXTRA_M",
        DETOUR,
    ),
    # --- the slider --------------------------------------------------------
    ("old default position", P, "_OLD_DEFAULT_POSITION = 90", "_OLD_DEFAULT_POSITION = 85", SLIDER),
    ("calm is linear", P, "math.expm1(CALM_CURVE * t) / math.expm1(CALM_CURVE)", "t", SLIDER),
    (
        "calm not capped",
        P,
        "(min(stress, STRESS_MAX) - STRESS_TODAYS_TOP)",
        "(stress - STRESS_TODAYS_TOP)",
        SLIDER,
    ),
    # --- the search --------------------------------------------------------
    (
        "quiet cost dropped",
        R,
        "        return self.cost_s + ctx.quiet_cost * extra",
        "        return self.cost_s + extra",
        REFINE,
    ),
    (
        "intersections not weighed",
        R,
        "ctx.rate * self.exposure_m + ctx.weight * penalty + ctx.climb_weight * self.climb_m",
        "ctx.rate * self.exposure_m + ctx.climb_weight * self.climb_m",
        REFINE,
    ),
    (
        "climb not weighed",
        R,
        "ctx.rate * self.exposure_m + ctx.weight * penalty + ctx.climb_weight * self.climb_m",
        "ctx.rate * self.exposure_m + ctx.weight * penalty",
        REFINE,
    ),
    (
        "rate not weighed",
        R,
        "ctx.rate * self.exposure_m + ctx.weight * penalty + ctx.climb_weight * self.climb_m",
        "ctx.weight * penalty + ctx.climb_weight * self.climb_m",
        REFINE,
    ),
    (
        "weight unbounded",
        R,
        "        1.0, stress / presets.STRESS_DEFAULT_AT\n    )",
        "        2.0, stress / presets.STRESS_DEFAULT_AT\n    )",
        REFINE,
    ),
    (
        "weight floor",
        R,
        "INTERSECTION_WEIGHT_AT_ZERO = 0.25",
        "INTERSECTION_WEIGHT_AT_ZERO = 0.0",
        REFINE,
    ),
    (
        "start clearance",
        R,
        "    if along_m < ENDPOINT_CLEARANCE_M or total_m - along_m < ENDPOINT_CLEARANCE_M:\n        return False",
        "    if total_m - along_m < ENDPOINT_CLEARANCE_M:\n        return False",
        REFINE,
    ),
    (
        "end clearance",
        R,
        "    if along_m < ENDPOINT_CLEARANCE_M or total_m - along_m < ENDPOINT_CLEARANCE_M:\n        return False",
        "    if along_m < ENDPOINT_CLEARANCE_M:\n        return False",
        REFINE,
    ),
    (
        "vias not protected",
        R,
        "    return all(abs(along_m - via) >= ENDPOINT_CLEARANCE_M for via in vias)",
        "    return True",
        REFINE,
    ),
    (
        "improvement margin",
        R,
        "if score < best_score - IMPROVEMENT_EPS_S and not busier:",
        "if score < best_score and not busier:",
        REFINE,
    ),
    (
        "any improvement wins nothing",
        R,
        "if score < best_score - IMPROVEMENT_EPS_S and not busier:",
        "if score <= best_score + IMPROVEMENT_EPS_S and not busier:",
        REFINE,
    ),
    (
        "patience",
        R,
        "            if stale >= REFINE_PATIENCE:",
        "            if stale > REFINE_PATIENCE:",
        REFINE,
    ),
    (
        "reduced ask always",
        R,
        "        if worst and len(worst) < len(new):",
        "        if worst:",
        REFINE,
    ),
    (
        "min tier edge",
        R,
        'if tier not in ("3", "4", "5") or int(tier) < min_tier:',
        'if tier not in ("3", "4", "5") or int(tier) <= min_tier:',
        REFINE,
    ),
    (
        "group has crossing avoidance",
        R,
        "    if ctx.group or not analysis.events:",
        "    if not analysis.events:",
        REFINE,
    ),
    (
        "worst lts4 first only when asked",
        R,
        'worst_first = number == 0 and any(c[0] in ("4", "5") for c in current.classes)',
        "worst_first = False",
        REFINE,
    ),
    (
        "crossing rounds forever",
        R,
        "new = crossing_targets(current, ctx) if number < CROSSING_ONLY_ROUNDS else []",
        "new = crossing_targets(current, ctx)",
        REFINE,
    ),
    (
        "exclusions not capped",
        R,
        '                    {"lon": t.point[0], "lat": t.point[1]} for t in asked[:MAX_EXCLUDES]',
        '                    {"lon": t.point[0], "lat": t.point[1]} for t in asked',
        REFINE,
    ),
    (
        "alternates kept",
        R,
        'request = {k: v for k, v in ctx.request.items() if k != "alternates"}',
        "request = dict(ctx.request)",
        REFINE,
    ),
    (
        "busier routes allowed",
        R,
        "if score < best_score - IMPROVEMENT_EPS_S and not busier:",
        "if score < best_score - IMPROVEMENT_EPS_S:",
        REFINE,
    ),
    (
        "tolerance unscaled",
        R,
        "busier = current.exposure_m > first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M",
        "busier = current.exposure_m > first_exposure",
        REFINE,
    ),
    (
        "tolerance edge",
        R,
        "first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M",
        "first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M - 1",
        REFINE,
    ),
    # --- the roads and the controls (database) -----------------------------
    (
        "a stop on the riders other edges",
        J,
        'mine = [e for e in edges if (e.get("edge_id") or {}).get("value") == raw.in_edge_id]',
        "mine = list(edges)",
        JUNCTIONS,
    ),
    (
        "all-way is a stop",
        J,
        "    if route_stops and cross_stops:\n        return Control.ALL_STOP",
        "    if route_stops and cross_stops:\n        return Control.STOP",
        JUNCTIONS,
    ),
    (
        "signal on the node ignored",
        J,
        'if (nodes and nodes[0].get("traffic_signal")) or any(_flag(e, "traffic_signal") for e in mine):',
        'if any(_flag(e, "traffic_signal") for e in mine):',
        JUNCTIONS,
    ),
    (
        "yield is not a stop",
        J,
        'route_stops = any(_flag(e, "stop_sign") or _flag(e, "yield_sign") for e in mine)',
        'route_stops = any(_flag(e, "stop_sign") for e in mine)',
        JUNCTIONS,
    ),
    (
        "every nearby way is crossed",
        J,
        "crossed = tuple(nearby[: raw.cross_road_count])",
        "crossed = tuple(nearby)",
        JUNCTIONS,
    ),
    (
        "the quietest first",
        J,
        "            key=lambda road: -(road.tier or 0),",
        "            key=lambda road: (road.tier or 0),",
        JUNCTIONS,
    ),
    (
        "a left off a busy road needs no control",
        J,
        "        or (j.incoming.busy and j.movement is Movement.LEFT)\n",
        "",
        JUNCTIONS,
    ),
    (
        "junction radius",
        J,
        "JUNCTION_RADIUS_DEG = 0.00004",
        "JUNCTION_RADIUS_DEG = 0.004",
        JUNCTIONS,
    ),
    ("locate batch", J, "LOCATE_BATCH = 50", "LOCATE_BATCH = 500", JUNCTIONS),
    (
        "neighbourhood junctions wanted",
        J,
        "    return raw.possibly_busy and (",
        "    return (",
        JUNCTIONS,
    ),
    # --- the answer --------------------------------------------------------
    (
        "neighbourhood stops listed",
        G,
        "        for event in events\n        if event.flagged\n",
        "        for event in events\n",
        ROUTE,
    ),
    (
        "mass ride searches",
        G,
        '    if preset_name == "mass-ride":\n        return "mass_ride"',
        '    if False:\n        return "mass_ride"',
        ROUTE,
    ),
    (
        "span edge",
        G,
        "    if straight > refine.REFINE_MAX_SPAN_M:",
        "    if straight >= refine.REFINE_MAX_SPAN_M:",
        ROUTE,
    ),
    ("always probe the direct route", G, "        and asked_for_calm\n", "", ROUTE),
    (
        "probe from Default",
        G,
        "stress_dial > presets.STRESS_DEFAULT_AT or route_m",
        "stress_dial >= presets.STRESS_DEFAULT_AT or route_m",
        ROUTE,
    ),
]


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
            control = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
                cwd=copy,
                capture_output=True,
                text=True,
            )
            if control.returncode != 0:
                print("CONTROL FAILED for", tests)
                print(control.stdout[-1500:])
                print(control.stderr[-500:])
                return 1000
        for name, rel, old, new, tests in selected:
            target = copy / rel
            original = (ROOT / rel).read_text()
            if original.count(old) != 1:
                print(f"BAD   {name}: {old[:50]!r} occurs {original.count(old)} times in {rel}")
                survivors.append(name + " (bad mutant)")
                continue
            target.write_text(original.replace(old, new))
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
                cwd=copy,
                capture_output=True,
                text=True,
            )
            target.write_text(original)
            if result.returncode == 0:
                print(f"SURVIVED {name}  ({rel})")
                survivors.append(name)
            else:
                print(f"killed   {name}")
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
    args = parser.parse_args()
    if args.list:
        for mutant in MUTANTS:
            print(mutant[0])
        sys.exit(0)
    sys.exit(run(args.only))
