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
        "    if node.signal or node.in_signal or any(a.signal for a in others):",
        "    if node.signal or node.in_signal:",
        JUNCTIONS,
    ),
    (
        "node signal ignored",
        J,
        "    if node.signal or node.in_signal or any(a.signal for a in others):",
        "    if node.in_signal or any(a.signal for a in others):",
        JUNCTIONS,
    ),
    (
        "riders signal ignored",
        J,
        "    if node.signal or node.in_signal or any(a.signal for a in others):",
        "    if node.signal or any(a.signal for a in others):",
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
        '        in_stop=_flag(mine, "stop_sign") or _flag(mine, "yield_sign"),',
        '        in_stop=_flag(mine, "stop_sign"),',
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
        "trail words never",
        INTERSECTIONS,
        "MARKED_CROSSING_NONE_WORDS if marked and control is Control.NONE else CONTROL_WORDS[control]",
        "CONTROL_WORDS[control]",
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
        "host slots ignored",
        R,
        "        if held is None:\n            yield False\n            return\n",
        "",
        REFINE,
    ),
    (
        "busy not said",
        R,
        '            info["limited"] = "busy"',
        '            info["limited"] = None',
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
        "        if read is None or read.events is None:",
        "        if read is None:",
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
