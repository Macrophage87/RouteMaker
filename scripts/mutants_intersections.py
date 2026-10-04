#!/usr/bin/env python3
"""Mutants on the intersection model, the calm search and the slider's rescale.

FOLLOWUP-INTERSECTIONS (2026-10-01). A mutation pass over the expressions this
work added, run against WHOLE test files (not the test that was written for the
line): a mutant is killed when any test in the files named for it fails. It
works on a copy of the repository so the tree being worked on is never edited,
and runs each test file in a process of its own:

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

Round 2 (review r2) adds the mutants of the approach walk, the back edges, the
shared control, the same-road continuation, the refuge and the crossed slip
lanes, and the review's M03; its M25 went with the lock files it mutated, and
`trail words never` with the second wording ("signal not mapped") it mutated.
`approach: limit exclusive` (`>` to `>=` at 30 m) was not added: the shapes are
rounded to 1e-6 degrees, so no test can stand exactly on the line.

Round 3 (review r3) adds the mutants of the walk's stop at another road's
junction, the signal's direction, the back edges' cut at a junction passed, the
first pass read without the approaches, the jog rule in the shared control, the
reviewer's R16 (a turn between ways of one name "continues") and the slip-lane
words, and retargets the round-2 mutants whose lines it rewrote. Round 2's
`shared: any road` is dropped as equivalent now: with no name in common,
`_one_junction` finds no crossed road among the shared ones and never shares.
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
        "    return trail and junction.control in {Control.NONE, Control.STOP}",
        "    return trail",
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
        "extra = sum(e.cost_ft for e in ones if e is not worst) * MERGED_SHARE",
        "extra = sum(e.cost_ft for e in ones if e is not worst)",
        PURE,
    ),
    (
        "merge keeps the colour",
        INTERSECTIONS,
        "        severity = _at_most(severity_of(cost), worst.max_severity)",
        "        severity = severity_of(cost)",
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
        '                approach=midpoint_along(shape, here.get("begin_shape_index"), end),',
        '                approach=shape[here.get("begin_shape_index")],',
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
        '    to_metres = 1609.344 if trace.get("units") == "miles" else 1000.0\n    junctions: list',
        "    to_metres = 1000.0\n    junctions: list",
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
        # The score is one term a line since the trail credit (trail-seek merge).
        "            + ctx.weight * penalty\n",
        "",
        REFINE,
    ),
    (
        "climb not weighed",
        R,
        "            + ctx.climb_weight * self.climb_m\n",
        "",
        REFINE,
    ),
    (
        "rate not weighed",
        R,
        "            ctx.rate * self.exposure_m\n            + ctx.weight * penalty\n",
        "            ctx.weight * penalty\n",
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
        "if score < best_score - IMPROVEMENT_EPS_S and not busier and not unread:",
        "if score < best_score and not busier and not unread:",
        REFINE,
    ),
    (
        "any improvement wins nothing",
        R,
        "if score < best_score - IMPROVEMENT_EPS_S and not busier and not unread:",
        "if score <= best_score + IMPROVEMENT_EPS_S and not busier and not unread:",
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
        "alternates kept",
        R,
        'request = {k: v for k, v in ctx.request.items() if k != "alternates"}',
        "request = dict(ctx.request)",
        REFINE,
    ),
    (
        "busier routes allowed",
        R,
        "if score < best_score - IMPROVEMENT_EPS_S and not busier and not unread:",
        "if score < best_score - IMPROVEMENT_EPS_S and not unread:",
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
        "busier = current.exposure_m > first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M\n",
        "busier = current.exposure_m > first_exposure * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M - 1\n",
        REFINE,
    ),
    # --- the node, from /locate (round 1: B1, B2) ----------------------------
    (
        "in-edge need not arrive",
        J,
        '        and float(e.get("percent_along") or 0.0) >= AT_END\n',
        "",
        JUNCTIONS,
    ),
    (
        "the in-edge's own node only",
        J,
        'node_ids = {_value((mine.get("edge") or {}).get("end_node"))} | {\n        _value(n.get("node_id")) for n in here\n    }',
        'node_ids = {_value((mine.get("edge") or {}).get("end_node"))}',
        JUNCTIONS,
    ),
    (
        "nodes not placed",
        J,
        '    here = [n for n in answer.get("nodes") or [] if _close(n.get("lon"), n.get("lat"), lon, lat)]',
        '    here = list(answer.get("nodes") or [])',
        JUNCTIONS,
    ),
    (
        "leaving edges not placed",
        J,
        "        outbound = along <= AT_START and _close(",
        "        outbound = along <= AT_START or _close(",
        JUNCTIONS,
    ),
    (
        "arriving from any node",
        J,
        '        inbound = along >= AT_END and _value((e.get("edge") or {}).get("end_node")) in node_ids',
        "        inbound = along >= AT_END",
        JUNCTIONS,
    ),
    (
        "links are roads",
        J,
        "        return (self.into or self.out_of) and not self.link and self.use",
        "        return (self.into or self.out_of) and self.use",
        JUNCTIONS,
    ),
    (
        "car-free arms are roads",
        J,
        "        return (self.into or self.out_of) and not self.link and self.use",
        "        return not self.link and self.use",
        JUNCTIONS,
    ),
    (
        "one side is a crossing",
        J,
        "        return (left, right) if left and right else None",
        "        return (left, right) if left or right else None",
        JUNCTIONS,
    ),
    (
        "a left crosses its left",
        J,
        "        return (right, []) if right else None",
        "        return (left, []) if left else None",
        JUNCTIONS,
    ),
    (
        "a right turn crosses",
        J,
        "    if raw.movement is Movement.LEFT:\n        return (right, []) if right else None",
        "    if raw.movement is not Movement.STRAIGHT:\n        return (right, []) if right else None",
        JUNCTIONS,
    ),
    (
        "sides swapped",
        J,
        "        (right if 0.0 < angle < to_back else left).append(arm)",
        "        (left if 0.0 < angle < to_back else right).append(arm)",
        JUNCTIONS,
    ),
    (
        "the busier side is crossed",
        J,
        "                    chosen = min(chosen, max(other, key=tier), key=tier)",
        "                    chosen = max(chosen, max(other, key=tier), key=tier)",
        JUNCTIONS,
    ),
    (
        "cross-approach signal ignored",
        J,
        "    if node.signal or node.in_signal or any(a.signal for a in (*others, *ahead)):",
        "    if node.signal or node.in_signal:",
        JUNCTIONS,
    ),
    (
        "node signal ignored",
        J,
        "    if node.signal or node.in_signal or any(a.signal for a in (*others, *ahead)):",
        "    if node.in_signal or any(a.signal for a in (*others, *ahead)):",
        JUNCTIONS,
    ),
    (
        "riders signal ignored",
        J,
        "    if node.signal or node.in_signal or any(a.signal for a in (*others, *ahead)):",
        "    if node.signal or any(a.signal for a in (*others, *ahead)):",
        JUNCTIONS,
    ),
    (
        "all-way is a stop",
        J,
        "    if node.in_stop and cross_stops:\n        return Control.ALL_STOP",
        "    if node.in_stop and cross_stops:\n        return Control.STOP",
        JUNCTIONS,
    ),
    (
        "oncoming is cross traffic",
        J,
        "    others = [a for a in node.others if a.is_road or a.is_link]",
        "    others = [a for a in node.arms if a is not node.in_arm and (a.is_road or a.is_link)]",
        JUNCTIONS,
    ),
    (
        "yield is not a stop",
        J,
        '                i and (_flag(e, "stop_sign") or _flag(e, "yield_sign"))',
        '                i and _flag(e, "stop_sign")',
        JUNCTIONS,
    ),
    (
        "riders yield is not a stop",
        J,
        '        in_stop=any(_flag(e, "stop_sign") or _flag(e, "yield_sign") for e in (mine, *back)),',
        '        in_stop=any(_flag(e, "stop_sign") for e in (mine, *back)),',
        JUNCTIONS,
    ),
    (
        "graph one-way ignored",
        J,
        "    oneway = not any(a.into and a.out_of for a in arms)",
        "    oneway = False",
        JUNCTIONS,
    ),
    ("no radius", J, "LOCATE_RADIUS_M = 1", "LOCATE_RADIUS_M = 0", JUNCTIONS),
    (
        "a failed batch ends the asking",
        J,
        '            logger.info("intersection nodes unavailable for a batch: %s", error)\n            continue',
        '            logger.info("intersection nodes unavailable for a batch: %s", error)\n            break',
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
    (
        "path crossing dropped",
        J,
        "                path_crossing=raw.path_crossing,\n",
        "",
        JUNCTIONS,
    ),
    (
        "links dropped",
        J,
        "                links=tuple(road(a, a.way_id, [a]) for a in links),\n",
        "",
        JUNCTIONS,
    ),
    (
        "same road by way only",
        J,
        "    return a.way_id == b.way_id or bool(a.names & b.names)",
        "    return a.way_id == b.way_id",
        JUNCTIONS,
    ),
    # --- the trace (round 1: B2a, SHOULD_FIX 1) --------------------------------
    (
        "the route's shape indexed",
        T,
        "    shape = trace_shape(trace, shape)\n    edges = trace.get",
        "    edges = trace.get",
        TRACE,
    ),
    (
        "approach on a vertex",
        T,
        '                approach=midpoint_along(shape, here.get("begin_shape_index"), end),',
        '                approach=shape[(here.get("begin_shape_index") + end) // 2],',
        TRACE,
    ),
    (
        "middle not interpolated",
        T,
        "            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)",
        "            return a",
        TRACE,
    ),
    (
        "no out edge",
        T,
        "                out_edge_id=edge_id_of(there),",
        "                out_edge_id=None,",
        TRACE,
    ),
    (
        "a cycleway is not a path",
        T,
        '    {"cycleway", "footway", "path",',
        '    {"footway", "path",',
        TRACE,
    ),
    # --- the classifier's traits (SHOULD_FIX 7) ---------------------------------
    (
        "assumed speed kept",
        "src/routemaker/stress.py",
        '        speed_mph=None if "maxspeed" in assumed else speed_mph,',
        "        speed_mph=speed_mph,",
        ["tests/test_road_traits.py"],
    ),
    (
        "assumed lanes kept",
        "src/routemaker/stress.py",
        '        lanes=None if "lanes" in assumed else lanes,',
        "        lanes=lanes,",
        ["tests/test_road_traits.py"],
    ),
    # --- round 1: the model (B3, items 185, 186, the review's survivors) -------
    ("straight to 60", INTERSECTIONS, "STRAIGHT_MAX_DEG = 35.0", "STRAIGHT_MAX_DEG = 60.0", PURE),
    (
        "rural on a left off",
        INTERSECTIONS,
        "        oncoming *= scale(road, stopped_side=False)",
        "        oncoming *= scale(road, stopped_side=True)",
        PURE,
    ),
    (
        "straight off a busy road priced",
        INTERSECTIONS,
        "    if j.incoming.busy and j.movement is not Movement.STRAIGHT:",
        "    if j.incoming.busy:",
        PURE,
    ),
    (
        "trail at no signal only",
        INTERSECTIONS,
        "    return trail and junction.control in {Control.NONE, Control.STOP}",
        "    return trail and junction.control in {Control.NONE}",
        PURE,
    ),
    (
        "a path is not a trail",
        INTERSECTIONS,
        "    trail = junction.marked_crossing or junction.path_crossing",
        "    trail = junction.marked_crossing",
        PURE,
    ),
    (
        "along strict",
        INTERSECTIONS,
        '"along" if j.incoming.busy and value <= PRIORITY_SIDE_FT else "crossing"',
        '"along" if j.incoming.busy and value < PRIORITY_SIDE_FT else "crossing"',
        PURE,
    ),
    (
        "left across onto a busy road",
        INTERSECTIONS,
        "        elif j.movement is Movement.LEFT and not j.incoming.busy and not j.outgoing.busy:",
        "        elif j.movement is Movement.LEFT and not j.incoming.busy:",
        PURE,
    ),
    (
        "the quietest slip lane road",
        INTERSECTIONS,
        "        busiest = max(roads, key=lambda r: r.tier or 0) if roads else None",
        "        busiest = min(roads, key=lambda r: r.tier or 0) if roads else None",
        PURE,
    ),
    (
        "slip lane links ignored",
        INTERSECTIONS,
        "        roads = [r for r in (j.incoming, j.outgoing, *j.crossed, *j.links) if r.busy]",
        "        roads = [r for r in (j.incoming, j.outgoing, *j.crossed) if r.busy]",
        PURE,
    ),
    (
        "merge anchored on the first",
        INTERSECTIONS,
        "        if group and event.m - group[-1].m > MERGE_WITHIN_M:",
        "        if group and event.m - group[0].m > MERGE_WITHIN_M:",
        PURE,
    ),
    (
        "onto from busy: busier only",
        INTERSECTIONS,
        "        and ((j.outgoing.tier or 0) > (j.incoming.tier or 0) or j.control is Control.STOP)",
        "        and ((j.outgoing.tier or 0) > (j.incoming.tier or 0))",
        PURE,
    ),
    (
        "onto from busy: stop only",
        INTERSECTIONS,
        "        and ((j.outgoing.tier or 0) > (j.incoming.tier or 0) or j.control is Control.STOP)",
        "        and (j.control is Control.STOP)",
        PURE,
    ),
    (
        "onto from busy: equal is busier",
        INTERSECTIONS,
        "        and ((j.outgoing.tier or 0) > (j.incoming.tier or 0) or j.control is Control.STOP)",
        "        and ((j.outgoing.tier or 0) >= (j.incoming.tier or 0) or j.control is Control.STOP)",
        PURE,
    ),
    (
        "onto from busy straight on",
        INTERSECTIONS,
        "        and j.movement is not Movement.STRAIGHT\n        and ((j.outgoing",
        "        and ((j.outgoing",
        PURE,
    ),
    (
        "onto uncapped",
        INTERSECTIONS,
        "        take(min(base * factor, MAX_CROSSING_FT),",
        "        take(base * factor,",
        PURE,
    ),
    (
        "left across uncapped",
        INTERSECTIONS,
        '            take(min(value, MAX_CROSSING_FT), "left_across", road)',
        '            take(value, "left_across", road)',
        PURE,
    ),
    (
        "no box cap at a signal",
        INTERSECTIONS,
        "    if control is Control.SIGNAL:\n        total = min(total, BOX_TURN_CAP_FT)\n",
        "",
        PURE,
    ),
    (
        "box cap everywhere",
        INTERSECTIONS,
        "    if control is Control.SIGNAL:\n        total = min(total, BOX_TURN_CAP_FT)\n",
        "    total = min(total, BOX_TURN_CAP_FT)\n",
        PURE,
    ),
    (
        "no trail cap",
        INTERSECTIONS,
        "    cap = MARKED_CROSSING_MAX_SEVERITY if marked else None",
        "    cap = None",
        PURE,
    ),
    (
        "no refuge credit",
        INTERSECTIONS,
        "    cost = worst.cost_ft * MEDIAN_REFUGE_FACTOR",
        "    cost = worst.cost_ft",
        PURE,
    ),
    (
        "never one road",
        INTERSECTIONS,
        "                if event.road_names & same[0].road_names:",
        "                if False:",
        PURE,
    ),
    (
        "M03: merged colour is the costliest event's",
        INTERSECTIONS,
        "        severity = _worst(e.severity for e in ones)",
        "        severity = worst.severity",
        PURE,
    ),
    (
        "a merge raises the colour",
        INTERSECTIONS,
        "        severity = _worst(e.severity for e in ones)",
        "        severity = severity_of(cost)",
        PURE,
    ),
    (
        "tier words unused",
        INTERSECTIONS,
        "    if not parts and road.tier in TIER_NOUNS:",
        "    if False:",
        PURE,
    ),
    (
        "always a",
        INTERSECTIONS,
        '    return "an" if text[:1] in "aeiou8"',
        '    return "a" if text[:1] in "aeiou8"',
        PURE,
    ),
    # --- round 1: the search (SHOULD_FIX 2, 3, 4; item 187) -----------------
    (
        "unread junctions taken",
        R,
        "        if score < best_score - IMPROVEMENT_EPS_S and not busier and not unread:",
        "        if score < best_score - IMPROVEMENT_EPS_S and not busier:",
        REFINE,
    ),
    (
        "no room kept",
        R,
        "        room = MAX_EXCLUDES - len(excluded)",
        "        room = MAX_EXCLUDES",
        REFINE,
    ),
    ("the list overflows", R, "        new = new[:room]\n", "", REFINE),
    (
        "sent twice",
        R,
        "        attempts = [a for a in attempts if frozenset(t.point for t in a) not in sent]\n",
        "",
        REFINE,
    ),
    (
        "short edges sampled",
        R,
        "        if metres < CALM_MIN_EDGE_M:\n            continue\n",
        "",
        REFINE,
    ),
    (
        "wide busier taken",
        R,
        "        if score < best_score - IMPROVEMENT_EPS_S and not busier:\n            best, best_trip, best_score = read, candidate, score",
        "        if score < best_score - IMPROVEMENT_EPS_S:\n            best, best_trip, best_score = read, candidate, score",
        REFINE,
    ),
    (
        "wide via breaks",
        R,
        '            {"lon": lon, "lat": lat, "type": "through"},',
        '            {"lon": lon, "lat": lat, "type": "break"},',
        REFINE,
    ),
    (
        "wide sides flipped",
        R,
        "    left_east, left_north = -north / length, east / length",
        "    left_east, left_north = north / length, -east / length",
        REFINE,
    ),
    (
        "wide on by default",
        R,
        "WIDE_SEARCH_FROM_RATE: float | None = None",
        "WIDE_SEARCH_FROM_RATE: float | None = 0.0",
        REFINE,
    ),
    (
        "wide margin",
        R,
        "        if score < best_score - IMPROVEMENT_EPS_S and not busier:\n            best, best_trip, best_score = read, candidate, score",
        "        if score < best_score and not busier:\n            best, best_trip, best_score = read, candidate, score",
        REFINE,
    ),
    (
        "wide unread taken",
        R,
        # The wide search's own check; the seek's whole-trip check is the same line.
        "        if read is None or read.events is None:\n            continue\n",
        "        if read is None:\n            continue\n",
        REFINE,
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
    # --- review r2: the approaches, shared control, continuing, refuge, slips --
    (
        "approach: no walk",
        J,
        "            and walk.signal(arm, cluster)\n        ):",
        "            and False\n        ):",
        JUNCTIONS,
    ),
    (
        "approach: riders own arm not walked",
        J,
        "            and (arm.is_road or index == in_index)\n",
        "            and arm.is_road\n",
        JUNCTIONS,
    ),
    (
        "approach: links walked too",
        J,
        "            and (arm.is_road or index == in_index)\n",
        "            and True\n",
        JUNCTIONS,
    ),
    (
        "approach: no distance limit",
        J,
        "            if self._metres(at) > APPROACH_M or any(_close(*at, *s) for s in seen):",
        "            if any(_close(*at, *s) for s in seen):",
        JUNCTIONS,
    ),
    (
        "approach: signal node not read",
        J,
        "            if self.node_signal(at) and not flagged:\n                return True",
        "            if False:\n                return True",
        JUNCTIONS,
    ),
    (
        "approach: footways read",
        J,
        "                if ends is None or not _close(*ends[1], *at) or not _is_road(entry):",
        "                if ends is None or not _close(*ends[1], *at):",
        JUNCTIONS,
    ),
    (
        "approach: flagged edge ignored",
        J,
        "            if any(self._towards(ends) for ends in flagged):\n                return True",
        "            if False:\n                return True",
        JUNCTIONS,
    ),
    (
        "approach: walks any road",
        J,
        "                if _of_road(arm, entry) and self._towards(ends):",
        "                if self._towards(ends):",
        JUNCTIONS,
    ),
    (
        "approach: stops at the first node",
        J,
        "                if _of_road(arm, entry) and self._towards(ends):",
        "                if False:",
        JUNCTIONS,
    ),
    (
        "approach: starts at the node",
        J,
        "                frontier.append(ends[0] if inbound else ends[1])",
        "                frontier.append(ends[1] if inbound else ends[0])",
        JUNCTIONS,
    ),
    (
        "approach: direction ignored",
        J,
        '    if (entry.get("edge") or {}).get("forward", True):',
        "    if True:",
        JUNCTIONS,
    ),
    (
        "approach: names not the road",
        J,
        '    return info.get("way_id") == arm.way_id or bool(names & arm.names)',
        '    return info.get("way_id") == arm.way_id',
        JUNCTIONS,
    ),
    (
        "approach: back edges not stops",
        J,
        '        in_stop=any(_flag(e, "stop_sign") or _flag(e, "yield_sign") for e in (mine, *back)),',
        '        in_stop=any(_flag(e, "stop_sign") or _flag(e, "yield_sign") for e in (mine,)),',
        JUNCTIONS,
    ),
    (
        "approach: back edges not signals",
        J,
        '        or any(_flag(e, "traffic_signal") for e in (mine, *back))',
        '        or any(_flag(e, "traffic_signal") for e in (mine,))',
        JUNCTIONS,
    ),
    (
        "approach: oncoming signal ignored",
        J,
        "    ahead = [node.out_arm] if node.out_arm is not None and node.out_arm.is_road else []",
        "    ahead = []",
        JUNCTIONS,
    ),
    (
        "approach: asked again at a signal too",
        J,
        "    unsure = [p for p in sorted(found) if control_of(found[p]) is not Control.SIGNAL]",
        "    unsure = sorted(found)",
        JUNCTIONS,
    ),
    (
        "approach: never asked again",
        J,
        "    unsure = [p for p in sorted(found) if control_of(found[p]) is not Control.SIGNAL]",
        "    unsure = []",
        JUNCTIONS,
    ),
    (
        "back edges: no limit",
        T,
        "        if gone > APPROACH_M:\n            break",
        "        if False:\n            break",
        TRACE,
    ),
    (
        "back edges: limit exclusive",
        T,
        "        if gone > APPROACH_M:",
        "        if gone >= APPROACH_M:",
        TRACE,
    ),
    (
        "back edges: in-edge not counted",
        T,
        '    gone = float(edges[index].get("length") or 0.0) * to_metres',
        "    gone = 0.0",
        TRACE,
    ),
    (
        "back edges: lengths not added",
        T,
        '        gone += float(edges[back].get("length") or 0.0) * to_metres',
        "        gone += 0.0",
        TRACE,
    ),
    (
        "shared: no sharing",
        INTERSECTIONS,
        "    events = (assess(junction, group) for junction in share_controls(junctions))",
        "    events = (assess(junction, group) for junction in junctions)",
        PURE,
    ),
    (
        "shared: stop signs shared",
        INTERSECTIONS,
        "_CONTROL_STRENGTH = {Control.SIGNAL: 2, Control.ALL_STOP: 1}",
        "_CONTROL_STRENGTH = {Control.SIGNAL: 2, Control.ALL_STOP: 1, Control.STOP: 1}",
        PURE,
    ),
    (
        "shared: all-way stop beats a signal",
        INTERSECTIONS,
        "_CONTROL_STRENGTH = {Control.SIGNAL: 2, Control.ALL_STOP: 1}",
        "_CONTROL_STRENGTH = {Control.SIGNAL: 1, Control.ALL_STOP: 2}",
        PURE,
    ),
    (
        "shared: the road ridden along counts",
        INTERSECTIONS,
        "    if junction.movement is not Movement.STRAIGHT:\n        names |= junction.incoming.names",
        "    if True:\n        names |= junction.incoming.names",
        PURE,
    ),
    (
        "shared: the turn's own road not counted",
        INTERSECTIONS,
        "    if junction.movement is not Movement.STRAIGHT:\n        names |= junction.incoming.names",
        "    if False:\n        names |= junction.incoming.names",
        PURE,
    ),
    (
        "shared: distance exclusive",
        INTERSECTIONS,
        "    while 0 <= k < len(order) and abs(junctions[order[k]].m - m) <= MERGE_WITHIN_M:",
        "    while 0 <= k < len(order) and abs(junctions[order[k]].m - m) < MERGE_WITHIN_M:",
        PURE,
    ),
    (
        "shared: no distance",
        INTERSECTIONS,
        "    while 0 <= k < len(order) and abs(junctions[order[k]].m - m) <= MERGE_WITHIN_M:",
        "    while 0 <= k < len(order):",
        PURE,
    ),
    (
        "continuing: joins anyway",
        INTERSECTIONS,
        "    if j.outgoing.busy and not j.continues and (not j.incoming.busy or turning_from_busy_onto):",
        "    if j.outgoing.busy and (not j.incoming.busy or turning_from_busy_onto):",
        PURE,
    ),
    (
        "continuing: way alone",
        J,
        "            raw.in_way == raw.out_way or bool(out_arms and in_arms[0].names & out_arms[0].names)",
        "            raw.in_way == raw.out_way",
        JUNCTIONS,
    ),
    (
        "continuing: names alone",
        J,
        "            raw.in_way == raw.out_way or bool(out_arms and in_arms[0].names & out_arms[0].names)",
        "            bool(out_arms and in_arms[0].names & out_arms[0].names)",
        JUNCTIONS,
    ),
    (
        "refuge: any two events",
        INTERSECTIONS,
        '    crossings = [e for e in events if e.kind == "crossing"]',
        "    crossings = list(events)",
        PURE,
    ),
    (
        "refuge: not one-way too",
        INTERSECTIONS,
        "    if not all(e.road_oneway and e.road_ways for e in crossings):",
        "    if not all(e.road_ways for e in crossings):",
        PURE,
    ),
    (
        "refuge: ways unknown taken",
        INTERSECTIONS,
        "    if not all(e.road_oneway and e.road_ways for e in crossings):",
        "    if not all(e.road_oneway for e in crossings):",
        PURE,
    ),
    (
        "refuge: the same way twice",
        INTERSECTIONS,
        "        if seen & event.road_ways:\n            return False",
        "        if False:\n            return False",
        PURE,
    ),
    (
        "refuge: always",
        INTERSECTIONS,
        "    if not _divided(crossings):\n        return [worst, *rest]",
        "    if False:\n        return [worst, *rest]",
        PURE,
    ),
    (
        "refuge: a lone crossing counted twice",
        INTERSECTIONS,
        "    if len(crossings) < 2:\n        return events",
        "    if len(crossings) < 1:\n        return events",
        PURE,
    ),
    (
        "slips: straight past is crossed",
        J,
        "        if left and right:\n            return left + right",
        "        if left or right:\n            return left + right",
        JUNCTIONS,
    ),
    (
        "slips: bike lane ignored",
        J,
        "        if node.in_cycle_lane in BIKE_LANES:",
        "        if False:",
        JUNCTIONS,
    ),
    (
        "slips: merging channel crossed",
        J,
        "            return [a for a in right if a.out_of]",
        "            return right",
        JUNCTIONS,
    ),
    (
        "slips: shared lane is a bike lane",
        J,
        'BIKE_LANES = frozenset({"dedicated", "separated"})',
        'BIKE_LANES = frozenset({"dedicated", "separated", "shared"})',
        JUNCTIONS,
    ),
    (
        "slips: left crosses none",
        J,
        "    if raw.movement is Movement.LEFT:\n        return right\n    return []",
        "    return []",
        JUNCTIONS,
    ),
    (
        "slips: any channel at the node",
        J,
        "                slip_lane=bool(links),",
        "                slip_lane=raw.slip_lane or bool(links),",
        JUNCTIONS,
    ),
    # --- review r3: another junction's signal, the jog, R16 ---------------------
    (
        "r3 walk: other roads' junctions walked",
        J,
        "            if self.foreign(at):\n                continue",
        "            if False:\n                continue",
        JUNCTIONS,
    ),
    (
        "r3 walk: read in the first pass",
        J,
        "            approaches\n            and not arm.signal",
        "            True\n            and not arm.signal",
        JUNCTIONS,
    ),
    (
        "r3 first pass reads the approaches",
        J,
        "        node = node_from_locate(answer, raws[position], approaches=False)",
        "        node = node_from_locate(answer, raws[position])",
        JUNCTIONS,
    ),
    (
        "r3 back edges read in the first pass",
        J,
        "    back = walk.back(raw.back_edge_ids) if approaches else []",
        "    back = walk.back(raw.back_edge_ids)",
        JUNCTIONS,
    ),
    (
        "r3 foreign: paths held too",
        J,
        "        strict=arms[in_index].use not in TRAIL_USES,",
        "        strict=True,",
        JUNCTIONS,
    ),
    (
        "r3 foreign: never held",
        J,
        "        strict=arms[in_index].use not in TRAIL_USES,",
        "        strict=False,",
        JUNCTIONS,
    ),
    (
        "r3 foreign: unnamed roads count",
        J,
        "            if names and not names & self.names:",
        "            if not names & self.names:",
        JUNCTIONS,
    ),
    (
        "r3 foreign: any named road",
        J,
        "            if names and not names & self.names:",
        "            if names:",
        JUNCTIONS,
    ),
    (
        "r3 foreign: paths count",
        J,
        "            if ends is None or not _is_road(entry):\n                continue\n            if not (_close",
        "            if ends is None:\n                continue\n            if not (_close",
        JUNCTIONS,
    ),
    (
        "r3 foreign: arriving edges only",
        J,
        "            if not (_close(*ends[0], *at) or _close(*ends[1], *at)):",
        "            if not _close(*ends[1], *at):",
        JUNCTIONS,
    ),
    (
        "r3 direction: a flag either way",
        J,
        "            if any(self._towards(ends) for ends in flagged):",
        "            if flagged:",
        JUNCTIONS,
    ),
    (
        "r3 direction: node flag whatever the edges",
        J,
        "            if self.node_signal(at) and not flagged:",
        "            if self.node_signal(at):",
        JUNCTIONS,
    ),
    (
        "r3 back: not cut at a passed junction",
        J,
        "            if ends is not None and self.foreign(ends[1]):\n                break",
        "            if False:\n                break",
        JUNCTIONS,
    ),
    (
        "r3 back: only the passed edge skipped",
        J,
        "                break\n            found.append(entry)",
        "                continue\n            found.append(entry)",
        JUNCTIONS,
    ),
    (
        "r3 shared: riding along the road shares",
        INTERSECTIONS,
        "    return bool((shared - out.names) & crossed)",
        "    return bool(shared & crossed)",
        PURE,
    ),
    (
        "r3 shared: turned onto and off shares",
        INTERSECTIONS,
        "    return bool((shared - out.names) & crossed)",
        "    return bool(shared - out.names)",
        PURE,
    ),
    (
        "r3 shared: any road between",
        INTERSECTIONS,
        "    if not (out == into or out.names & into.names):\n        return False",
        "    if False:\n        return False",
        PURE,
    ),
    (
        "r3 shared: unnamed roads between differ",
        INTERSECTIONS,
        "    if not (out == into or out.names & into.names):",
        "    if not (out.names & into.names):",
        PURE,
    ),
    (
        "r3 shared: only the later one's crossing",
        INTERSECTIONS,
        "frozenset().union(*_crossings(earlier), *_crossings(later))",
        "frozenset().union(*_crossings(later))",
        PURE,
    ),
    (
        "r3 shared: only the earlier one's crossing",
        INTERSECTIONS,
        "frozenset().union(*_crossings(earlier), *_crossings(later))",
        "frozenset().union(*_crossings(earlier))",
        PURE,
    ),
    (
        "r3 shared: earlier and later swapped",
        INTERSECTIONS,
        "            earlier, later = (other, junction) if other.m <= junction.m else (junction, other)",
        "            earlier, later = (junction, other)",
        PURE,
    ),
    (
        "r3 continuing: turns continue too (R16)",
        J,
        "        continues = raw.movement is Movement.STRAIGHT and (",
        "        continues = (",
        JUNCTIONS,
    ),
    (
        "r3 slip words",
        INTERSECTIONS,
        '    "slip_lane": "Crossing a slip lane off",',
        '    "slip_lane": "Slip lane beside",',
        PURE,
    ),
    (
        "carriageway ways not kept",
        J,
        "        ways=frozenset(a.way_id for a in arms),\n    )",
        "        ways=frozenset(),\n    )",
        JUNCTIONS,
    ),
    # --- FINAL-FIX: the graph's direction for the junction model (correctness
    # re-check B1), Mass Ride keeps one-way (OWNER-DECISIONS 246), and the
    # mutation re-check's TG1 and TG2. The rebuild's writer and `routing_tags`
    # are covered by the end-to-end helper, run by hand (FINALFIX-dev-r0).
    (
        "B1: road_oneway is the relief reading again",
        "src/routemaker/stress.py",
        "        graph_oneway=is_oneway(tags),\n",
        "        graph_oneway=oneway,\n",
        ["tests/test_road_traits.py"],
    ),
    (
        "B1: an override loses the graph's direction",
        "src/pipeline/overrides.py",
        '            graph_oneway=getattr(current, "graph_oneway", None),\n',
        "",
        ["tests/test_road_traits.py"],
    ),
    (
        "B1: a car-free road loses the graph's direction",
        "src/pipeline/run.py",
        "        graph_oneway=current.graph_oneway,\n",
        "",
        ["tests/test_overrides.py"],
    ),
    (
        "246: every graph keeps OSM's one-way",
        "src/pipeline/variants.py",
        '    if variant is not Variant.NO_TRAIL or routed.get("oneway") != "no":',
        '    if routed.get("oneway") != "no":',
        ["tests/test_variants.py", "tests/test_lua_remap.py"],
    ),
    (
        "246: the no-trail graph takes DC's two-way",
        "src/pipeline/variants.py",
        '    if variant is not Variant.NO_TRAIL or routed.get("oneway") != "no":\n        return routed\n    if not is_motor_oneway(tags):\n        return routed\n    return',
        "    return routed\n    return",
        ["tests/test_variants.py", "tests/test_lua_remap.py"],
    ),
    (
        "246: OSM's two-way is kept one-way too",
        "src/pipeline/variants.py",
        "    if not is_motor_oneway(tags):\n        return routed\n",
        "",
        ["tests/test_variants.py"],
    ),
    (
        "246: the whole record is dropped, not its direction",
        "src/pipeline/variants.py",
        '    return {key: value for key, value in routed.items() if key != "oneway"}',
        "    return {}",
        ["tests/test_variants.py"],
    ),
    (
        "TG1: an odd oneway value on a roundabout reads two-way",
        "src/routemaker/tags.py",
        '    return tags.get("junction") in ONEWAY_JUNCTIONS and tags.get("oneway") != "no"',
        '    return tags.get("junction") in ONEWAY_JUNCTIONS and tags.get("oneway") is None',
        ["tests/test_road_traits.py"],
    ),
    (
        "TG2: the router's arms win over the segment table",
        "src/core/junctions.py",
        "        oneway=oneway if road.oneway is None else road.oneway,",
        "        oneway=oneway,",
        JUNCTIONS,
    ),
    (
        "TG2: the table wins even where it has nothing",
        "src/core/junctions.py",
        "        oneway=oneway if road.oneway is None else road.oneway,",
        "        oneway=road.oneway,",
        JUNCTIONS,
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
