#!/usr/bin/env python3
"""Mutants on FOLLOWUP-DEDODGE: the quarter-mile threshold, the turn weighting, the
"same corridor" match, what a dodge is made of, the guards that keep the order, the
hold, the target and the ceiling, the splice, and the bounds.

OWNER-DECISIONS 272, 273. A mutation pass run against WHOLE test files, as
`scripts/mutants_longcalm.py` does: a mutant is killed when any test in the files named
for it fails. It works on a copy of the repository and runs each test file in a process of
its own, under a timeout:

    scripts/mutants_dedodge.py [--only NAME] [--list] [--check]

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

TD = ["tests/test_dedodge.py"]
TP = ["tests/test_dedodge_plan.py"]
DD = "src/core/dedodge.py"
RT = "src/core/routing.py"

# The longest a test file may take against a mutant.
TEST_TIMEOUT_S = 300
NL = "\n"

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- the threshold (272) -----------------------------------------------------
    (
        "threshold: half a mile",
        DD,
        "MIN_AVOIDED_M = 0.25 * 1609.344",
        "MIN_AVOIDED_M = 0.5 * 1609.344",
        TD,
    ),
    (
        "threshold: an eighth of a mile",
        DD,
        "MIN_AVOIDED_M = 0.25 * 1609.344",
        "MIN_AVOIDED_M = 0.125 * 1609.344",
        TD,
    ),
    (
        "threshold: nothing is enough",
        DD,
        "MIN_AVOIDED_M = 0.25 * 1609.344",
        "MIN_AVOIDED_M = 0.0",
        TD,
    ),
    (
        "threshold: exactly enough is not enough",
        DD,
        "    if avoided >= needed:",
        "    if avoided > needed:",
        TD,
    ),
    ("threshold: everything is kept", DD, "    if avoided >= needed:", "    if True:", TD),
    (
        "threshold: nothing is kept for its stress",
        DD,
        "    if avoided >= needed:",
        "    if False:",
        TD,
    ),
    # --- the turn weighting (254) ------------------------------------------------
    ("turns: no charge", DD, "TURN_CHARGE_M = 80.0", "TURN_CHARGE_M = 0.0", TD),
    ("turns: a heavy charge", DD, "TURN_CHARGE_M = 80.0", "TURN_CHARGE_M = 800.0", TD),
    (
        "turns: the charge lowers the bar",
        DD,
        "MIN_AVOIDED_M + TURN_CHARGE_M * max(0, turns_saved - BASE_TURNS)",
        "MIN_AVOIDED_M - TURN_CHARGE_M * max(0, turns_saved - BASE_TURNS)",
        TD,
    ),
    ("turns: the first turn is charged", DD, "BASE_TURNS = 2", "BASE_TURNS = 1", TD),
    ("turns: the third turn is not charged", DD, "BASE_TURNS = 2", "BASE_TURNS = 3", TD),
    (
        "turns: a main road with more turns lowers the bar",
        DD,
        "TURN_CHARGE_M * max(0, turns_saved - BASE_TURNS)",
        "TURN_CHARGE_M * (turns_saved - BASE_TURNS)",
        TD,
    ),
    (
        "turns: the turns are the dodge's less the direct's, reversed",
        DD,
        "    saved = turn_count(dodge.pieces) - turn_count(direct.pieces)",
        "    saved = turn_count(direct.pieces) - turn_count(dodge.pieces)",
        TD,
    ),
    ("turns: a turn is a slight bend", DD, "TURN_DEGREES = 40.0", "TURN_DEGREES = 5.0", TD),
    (
        "turns: a turn is a right angle and more",
        DD,
        "TURN_DEGREES = 40.0",
        "TURN_DEGREES = 100.0",
        TD,
    ),
    (
        "turns: a heading change of the threshold is not a turn",
        DD,
        "        elif bearing_delta(here.heading_out, there.heading_in) >= TURN_DEGREES:",
        "        elif bearing_delta(here.heading_out, there.heading_in) > TURN_DEGREES:",
        TD,
    ),
    (
        "turns: a split way is a turn",
        DD,
        "        if here.way_id == there.way_id:" + NL + "            continue" + NL,
        "",
        TD,
    ),
    (
        "turns: a bend in one street is a turn",
        DD,
        "        if {normal(n) for n in here.names} & {normal(n) for n in there.names}:"
        + NL
        + "            continue"
        + NL,
        "",
        TD,
    ),
    (
        "turns: without headings nothing is a turn",
        DD,
        "        if here.heading_out is None or there.heading_in is None:"
        + NL
        + "            turns += 1",
        "        if here.heading_out is None or there.heading_in is None:"
        + NL
        + "            turns += 0",
        TD,
    ),
    # --- the stress avoided (258-260) ----------------------------------------------
    (
        "avoided: the top figure does not count",
        DD,
        "    return max(0.0, direct.top_m - dodge.top_m) + max(0.0, direct.second_m - dodge.second_m)",
        "    return max(0.0, direct.second_m - dodge.second_m)",
        TD,
    ),
    (
        "avoided: the second figure does not count",
        DD,
        "    return max(0.0, direct.top_m - dodge.top_m) + max(0.0, direct.second_m - dodge.second_m)",
        "    return max(0.0, direct.top_m - dodge.top_m)",
        TD,
    ),
    (
        "avoided: a calmer main road counts as stress avoided",
        DD,
        "    return max(0.0, direct.top_m - dodge.top_m) + max(0.0, direct.second_m - dodge.second_m)",
        "    return abs(direct.top_m - dodge.top_m) + abs(direct.second_m - dodge.second_m)",
        TD,
    ),
    (
        "avoided: the other way about",
        DD,
        "    return max(0.0, direct.top_m - dodge.top_m) + max(0.0, direct.second_m - dodge.second_m)",
        "    return max(0.0, dodge.top_m - direct.top_m) + max(0.0, dodge.second_m - direct.second_m)",
        TD,
    ),
    # --- the order, the hold, the target and the ceiling (250, 258-262, 267-271) -------------
    (
        "order: the top figure may rise",
        DD,
        "    if direct.top_m > dodge.top_m + TOP_SLACK_M:" + NL + '        return keep("top")',
        "    if False:" + NL + '        return keep("top")',
        TD,
    ),
    (
        "order: a rise of the slack is refused",
        DD,
        "    if direct.top_m > dodge.top_m + TOP_SLACK_M:",
        "    if direct.top_m >= dodge.top_m + TOP_SLACK_M:",
        TD,
    ),
    (
        "order: any rise is refused",
        DD,
        "TOP_SLACK_M = refine.LTS4_SLACK_M",
        "TOP_SLACK_M = -1.0",
        TD,
    ),
    ("order: a wide slack", DD, "TOP_SLACK_M = refine.LTS4_SLACK_M", "TOP_SLACK_M = 100.0", TD),
    (
        "order: the top figure leaves out red junctions",
        DD,
        "    if direct.top_m > dodge.top_m + TOP_SLACK_M:",
        "    if direct.lts4_m > dodge.lts4_m + TOP_SLACK_M:",
        TD,
    ),
    (
        "ceiling: a longer route may replace it",
        DD,
        "    if extra < -LENGTH_SLACK_M:" + NL + '        return keep("longer")',
        "    if False:" + NL + '        return keep("longer")',
        TD,
    ),
    (
        "ceiling: a route no longer by the slack is refused",
        DD,
        "    if extra < -LENGTH_SLACK_M:",
        "    if extra <= 0:",
        TD,
    ),
    ("ceiling: a wide length slack", DD, "LENGTH_SLACK_M = 1.0", "LENGTH_SLACK_M = 100.0", TD),
    (
        "ceiling: the length is the dodge's less the direct's, reversed",
        DD,
        "    extra = traced_m(dodge) - traced_m(direct)",
        "    extra = traced_m(direct) - traced_m(dodge)",
        TD,
    ),
    (
        "hills: a steeper route may replace it",
        DD,
        "    if refine.level3(direct, ctx) > refine.level3(dodge, ctx) + LENGTH_SLACK_M:"
        + NL
        + '        return keep("hills")',
        "    if False:" + NL + '        return keep("hills")',
        TD,
    ),
    (
        "hills: the hills choice is read from the dodge's own",
        DD,
        "    if refine.level3(direct, ctx) > refine.level3(dodge, ctx) + LENGTH_SLACK_M:",
        "    if refine.level3(dodge, ctx) > refine.level3(direct, ctx) + LENGTH_SLACK_M:",
        TD,
    ),
    (
        "events: unread junctions are weighed anyway",
        DD,
        "    if (dodge.events is None) != (direct.events is None):"
        + NL
        + '        return keep("events")',
        "    if False:" + NL + '        return keep("events")',
        TD,
    ),
    # --- the same corridor ---------------------------------------------------------------
    (
        "corridor: any road is the same road",
        DD,
        "    if shared:" + NL + "        return NAME if turn <= SAME_ROAD_HEADING_DEG else None",
        "    if True:" + NL + "        return NAME if turn <= SAME_ROAD_HEADING_DEG else None",
        TD,
    ),
    (
        "corridor: the same road may come back the other way",
        DD,
        "SAME_ROAD_HEADING_DEG = 90.0",
        "SAME_ROAD_HEADING_DEG = 180.0",
        TD,
    ),
    (
        "corridor: the same road must run straight on",
        DD,
        "SAME_ROAD_HEADING_DEG = 90.0",
        "SAME_ROAD_HEADING_DEG = 10.0",
        TD,
    ),
    (
        "corridor: a rejoin behind is a rejoin",
        DD,
        "    if ahead <= 0:" + NL + "        return None",
        "    if False:" + NL + "        return None",
        TD,
    ),
    (
        "corridor: a rejoin level with the start is a rejoin",
        DD,
        "    if ahead <= 0:",
        "    if ahead < 0:",
        TD,
    ),
    (
        "corridor: a road on the line is any road",
        DD,
        "    return LINE if turn <= PARALLEL_HEADING_DEG and aside <= PARALLEL_OFFSET_M else None",
        "    return LINE",
        TD,
    ),
    (
        "corridor: the offset is a kilometre",
        DD,
        "PARALLEL_OFFSET_M = 150.0",
        "PARALLEL_OFFSET_M = 1000.0",
        TD,
    ),
    (
        "corridor: the offset is nothing",
        DD,
        "PARALLEL_OFFSET_M = 150.0",
        "PARALLEL_OFFSET_M = 0.0",
        TD,
    ),
    (
        "corridor: the heading is any",
        DD,
        "PARALLEL_HEADING_DEG = 35.0",
        "PARALLEL_HEADING_DEG = 120.0",
        TD,
    ),
    (
        "corridor: the heading is none",
        DD,
        "PARALLEL_HEADING_DEG = 35.0",
        "PARALLEL_HEADING_DEG = 1.0",
        TD,
    ),
    (
        "corridor: the offset is measured ahead, not aside",
        DD,
        "    return d * math.cos(angle), abs(d * math.sin(angle))",
        "    return d * math.sin(angle), abs(d * math.cos(angle))",
        TD,
    ),
    (
        "corridor: a road on the line is taken before the road itself",
        DD,
        "                    if kind == LINE and on_line is None:"
        + NL
        + "                        on_line = b",
        "                    if kind == LINE and on_line is None:"
        + NL
        + "                        hit = b"
        + NL
        + "                        break",
        TD,
    ),
    (
        "corridor: a road on the line is never taken",
        DD,
        "        hit = hit if hit is not None else on_line",
        "        hit = hit",
        TD,
    ),
    (
        "corridor: names are compared as typed",
        DD,
        '    return " ".join(name.lower().split())',
        "    return name",
        TD,
    ),
    (
        "corridor: two names are one road only if they are all the same",
        DD,
        "        if groups and edge.names and names[-1] & edge.names:",
        "        if groups and edge.names and names[-1] == edge.names:",
        TD,
    ),
    (
        "corridor: an unnamed street joins its neighbour",
        DD,
        "        if groups and edge.names and names[-1] & edge.names:",
        "        if groups and names[-1] == edge.names:",
        TD,
    ),
    (
        "corridor: without headings the name is not needed",
        DD,
        "        return NAME if shared else None",
        "        return NAME",
        TD,
    ),
    # --- what a dodge is made of -----------------------------------------------------------
    (
        "dodge: a mile is two",
        DD,
        "                if gone > DODGE_MAX_M:",
        "                if gone > 2 * DODGE_MAX_M:",
        TD,
    ),
    ("dodge: a mile is half", DD, "DODGE_MAX_M = 1609.344", "DODGE_MAX_M = 800.0", TD),
    ("dodge: a stub is a road", DD, "MAIN_MIN_M = 30.0", "MAIN_MIN_M = 0.0", TD),
    ("dodge: a road is a long one", DD, "MAIN_MIN_M = 30.0", "MAIN_MIN_M = 300.0", TD),
    (
        "dodge: a trail is a road",
        DD,
        "    return bool(stretch.names) and all(e.use in MAIN_USES for e in stretch.edges)",
        "    return bool(stretch.names)",
        TD,
    ),
    (
        "dodge: a road is a road if one edge is",
        DD,
        "    return bool(stretch.names) and all(e.use in MAIN_USES for e in stretch.edges)",
        "    return bool(stretch.names) and any(e.use in MAIN_USES for e in stretch.edges)",
        TD,
    ),
    (
        "dodge: a trail is a street",
        DD,
        "    return all(e.use in STREET_USES for e in stretch.edges)",
        "    return True",
        TD,
    ),
    (
        "dodge: a street is a street if one edge is",
        DD,
        "    return all(e.use in STREET_USES for e in stretch.edges)",
        "    return any(e.use in STREET_USES for e in stretch.edges)",
        TD,
    ),
    (
        "dodge: a service road is not a street",
        DD,
        '{"road", "living_street", "service_road", "alley", "culdesac", "turn_channel", "driveway"}',
        '{"road", "living_street", "alley", "culdesac", "turn_channel", "driveway"}',
        TD,
    ),
    (
        "dodge: a trail edge in a dodge is overlooked",
        DD,
        "        if all(is_streets(s) for s in off):",
        "        if True:",
        TD,
    ),
    (
        "dodge: the dodge is not measured",
        DD,
        "            found.append(Dodge(main, stretches[hit], off, sum(s.metres for s in off)))",
        "            found.append(Dodge(main, stretches[hit], off, 0.0))",
        TD,
    ),
    (
        "dodge: a dodge swallows the road it rejoins",
        DD,
        "        a = hit" + NL + "    return found",
        "        a = hit + 1" + NL + "    return found",
        TD,
    ),
    # --- the edges --------------------------------------------------------------------------
    (
        "edges: an edge of no length is kept",
        DD,
        "        if length <= 0 or begin is None or end is None or end < begin or end >= len(shape):",
        "        if begin is None or end is None or end < begin or end >= len(shape):",
        TD,
    ),
    (
        "edges: an edge past the shape is kept",
        DD,
        "or end < begin or end >= len(shape):",
        "or end < begin:",
        TD,
    ),
    (
        "edges: miles are kilometres",
        DD,
        '    to_metres = 1609.344 if trace.get("units") == "miles" else 1000.0',
        "    to_metres = 1000.0",
        TD,
    ),
    (
        "edges: the headings are swapped",
        DD,
        '                heading_in=routing._heading(edge.get("begin_heading")),',
        '                heading_in=routing._heading(edge.get("end_heading")),',
        TD,
    ),
    # --- the request ---------------------------------------------------------------------------
    (
        "request: the plan's alternates are asked for",
        DD,
        '    request = {k: v for k, v in ctx.request.items() if k not in ("alternates", "exclude_locations")}',
        '    request = {k: v for k, v in ctx.request.items() if k not in ("exclude_locations",)}',
        TD,
    ),
    (
        "request: the dodge is not excluded",
        DD,
        '    request["exclude_locations"] = [{"lon": lon, "lat": lat} for lon, lat in excludes]',
        '    request["exclude_locations"] = []',
        TD,
    ),
    (
        "request: a refusal facing the way it goes is final",
        DD,
        "    for headings in (True, False):",
        "    for headings in (True,):",
        TD,
    ),
    (
        "request: the ends have no heading",
        DD,
        "    if headings and out_edge.heading_out is not None:"
        + NL
        + '        here["heading"] = int(round(out_edge.heading_out)) % 360',
        "    if False:" + NL + '        here["heading"] = int(round(out_edge.heading_out)) % 360',
        TD,
    ),
    (
        "request: the far end has no heading",
        DD,
        "    if headings and in_edge.heading_in is not None:"
        + NL
        + '        there["heading"] = int(round(in_edge.heading_in)) % 360',
        "    if False:" + NL + '        there["heading"] = int(round(in_edge.heading_in)) % 360',
        TD,
    ),
    (
        "request: the ends are swapped",
        DD,
        '    request["locations"] = [here, there]',
        '    request["locations"] = [there, here]',
        TD,
    ),
    (
        "request: the router is the standard one",
        DD,
        '                ctx.variant, "route", _request(ctx, dodge, shape, excludes, headings), deadline',
        '                "standard", "route", _request(ctx, dodge, shape, excludes, headings), deadline',
        TD,
    ),
    ("exclusions: no bound", DD, "    return out[:MAX_EXCLUDES]", "    return out", TD),
    ("exclusions: a loose bound", DD, "MAX_EXCLUDES = 40", "MAX_EXCLUDES = 400", TD),
    (
        "exclusions: a short edge is excluded",
        DD,
        "MIN_EXCLUDE_EDGE_M = refine.CALM_MIN_EDGE_M",
        "MIN_EXCLUDE_EDGE_M = 0.0",
        TD,
    ),
    (
        "exclusions: no edge is long enough",
        DD,
        "MIN_EXCLUDE_EDGE_M = refine.CALM_MIN_EDGE_M",
        "MIN_EXCLUDE_EDGE_M = 1000.0",
        TD,
    ),
    (
        "exclusions: an edge is excluded at its start",
        DD,
        "        point = trace_junctions.midpoint_along(shape, edge.begin, edge.end)",
        "        point = shape[edge.begin]",
        TD,
    ),
    # --- the splice ------------------------------------------------------------------------------
    (
        "splice: the router's start may be anywhere",
        DD,
        "        haversine(Point(*sub_shape[0]), Point(*shape[out_edge.end])) > SNAP_M"
        + NL
        + "        or ",
        "        False" + NL + "        or ",
        TD,
    ),
    (
        "splice: the router's end may be anywhere",
        DD,
        "        or haversine(Point(*sub_shape[-1]), Point(*shape[in_edge.begin])) > SNAP_M",
        "        or False",
        TD,
    ),
    ("splice: a wide snap", DD, "SNAP_M = 15.0", "SNAP_M = 1500.0", TD),
    ("splice: no snap", DD, "SNAP_M = 15.0", "SNAP_M = 0.0", TD),
    (
        "splice: the road before is cut a vertex short",
        DD,
        "    points = [*shape[: out_edge.end], *sub_shape, *shape[in_edge.begin + 1 :]]",
        "    points = [*shape[: out_edge.end - 1], *sub_shape, *shape[in_edge.begin + 1 :]]",
        TD,
    ),
    (
        "splice: the road after repeats its first vertex",
        DD,
        "    points = [*shape[: out_edge.end], *sub_shape, *shape[in_edge.begin + 1 :]]",
        "    points = [*shape[: out_edge.end], *sub_shape, *shape[in_edge.begin :]]",
        TD,
    ),
    (
        "splice: the road before repeats its last vertex",
        DD,
        "    points = [*shape[: out_edge.end], *sub_shape, *shape[in_edge.begin + 1 :]]",
        "    points = [*shape[: out_edge.end + 1], *sub_shape, *shape[in_edge.begin + 1 :]]",
        TD,
    ),
    (
        "splice: the dodge's length is added",
        DD,
        '        summary["length"] = before["length"] - dodge.metres / 1000.0 + after["length"]',
        '        summary["length"] = before["length"] + dodge.metres / 1000.0 + after["length"]',
        TD,
    ),
    (
        "splice: the replacement's length is not added",
        DD,
        '        summary["length"] = before["length"] - dodge.metres / 1000.0 + after["length"]',
        '        summary["length"] = before["length"] - dodge.metres / 1000.0',
        TD,
    ),
    (
        "splice: the dodge's time is kept",
        DD,
        "            summary[key] = before[key] * (1.0 - share) + after[key]",
        "            summary[key] = before[key] + after[key]",
        TD,
    ),
    (
        "splice: the dodge's share of the leg is the whole",
        DD,
        "    share = dodge.metres / whole_m if whole_m > 0 else 0.0",
        "    share = 1.0",
        TD,
    ),
    (
        "splice: the elevation is the leg's alone",
        DD,
        '        new["elevation"] = [*heights[:k_out], *sub_heights, *heights[k_in:]]',
        '        new["elevation"] = heights',
        TD,
    ),
    (
        "splice: the elevation is cut at the wrong place",
        DD,
        "        k_in = round((start_m + dodge.metres) / interval_m)",
        "        k_in = round(start_m / interval_m)",
        TD,
    ),
    (
        "splice: a stale elevation is kept",
        DD,
        "    else:" + NL + '        new.pop("elevation", None)',
        "    else:" + NL + "        pass",
        TD,
    ),
    (
        "encode: the sign is lost",
        DD,
        "        for delta in (new_lat - lat, new_lon - lon):"
        + NL
        + "            delta = ~(delta << 1) if delta < 0 else delta << 1",
        "        for delta in (new_lat - lat, new_lon - lon):"
        + NL
        + "            delta = (delta << 1) if delta < 0 else delta << 1",
        TD,
    ),
    (
        "encode: the offset is wrong",
        DD,
        "            out.append(chr(delta + 63))",
        "            out.append(chr(delta + 62))",
        TD,
    ),
    (
        "encode: longitude first",
        DD,
        "        for delta in (new_lat - lat, new_lon - lon):",
        "        for delta in (new_lon - lon, new_lat - lat):",
        TD,
    ),
    # --- the pass and its bounds ----------------------------------------------------------------
    ("bounds: eighty checks", DD, "MAX_CHECKS = 8", "MAX_CHECKS = 80", TD),
    (
        "bounds: the last check is refused",
        DD,
        '        if info["checked"] >= MAX_CHECKS:',
        '        if info["checked"] >= MAX_CHECKS - 1:',
        TD,
    ),
    (
        "bounds: one check too many",
        DD,
        '        if info["checked"] >= MAX_CHECKS:',
        '        if info["checked"] > MAX_CHECKS:',
        TD,
    ),
    ("bounds: fifty seconds", DD, "BUDGET_S = 5.0", "BUDGET_S = 50.0", TD),
    (
        "bounds: the answer's own work is not kept back",
        DD,
        "    stop_at = min(ctx.deadline.at - refine.REFINE_TRACE_RESERVE_S, routing.clock() + budget_s)",
        "    stop_at = min(ctx.deadline.at, routing.clock() + budget_s)",
        TD,
    ),
    (
        "bounds: the budget is not a bound",
        DD,
        "    stop_at = min(ctx.deadline.at - refine.REFINE_TRACE_RESERVE_S, routing.clock() + budget_s)",
        "    stop_at = ctx.deadline.at - refine.REFINE_TRACE_RESERVE_S",
        TD,
    ),
    (
        "bounds: a pass is begun with no time",
        DD,
        "    if stop_at - routing.clock() < MIN_START_S:",
        "    if False:",
        TD,
    ),
    ("bounds: the least start is nothing", DD, "MIN_START_S = 3.0", "MIN_START_S = 0.0", TD),
    (
        "bounds: a call may take the plan's own time",
        DD,
        "    deadline = routing.Deadline(stop_at, min(ctx.deadline.per_call_s, CALL_TIMEOUT_S))",
        "    deadline = routing.Deadline(stop_at, CALL_TIMEOUT_S)",
        TD,
    ),
    (
        "bounds: a call may take the whole budget",
        DD,
        "CALL_TIMEOUT_S = 8.0",
        "CALL_TIMEOUT_S = 800.0",
        TD,
    ),
    (
        "bounds: the clock is not read between dodges",
        DD,
        "        if routing.clock() >= deadline.at:" + NL + '            info["limited"] = "time"',
        "        if False:" + NL + '            info["limited"] = "time"',
        TD,
    ),
    (
        "bounds: a leg's pass past the limit goes on",
        DD,
        '            if info["limited"]:' + NL + "                break",
        "            if False:" + NL + "                break",
        TD,
    ),
    (
        "bounds: a router that is down raises",
        DD,
        "    except (routing.DeadlineExceeded, routing.RouterUnavailable):"
        + NL
        + '        info["limited"] = info["limited"] or "time"',
        "    except routing.DeadlineExceeded:"
        + NL
        + '        info["limited"] = info["limited"] or "time"',
        TD,
    ),
    (
        "bounds: an unexpected failure raises",
        DD,
        "    except Exception:  # noqa: BLE001 - the route is answered as it was"
        + NL
        + '        logger.warning("the dodge pass failed", exc_info=True)',
        "    except ZeroDivisionError:  # noqa: BLE001"
        + NL
        + '        logger.warning("the dodge pass failed", exc_info=True)',
        TD,
    ),
    (
        "pass: a dodge looked at is looked at again",
        DD,
        "        seen.add(_key(dodge, shape))",
        "        pass",
        TD,
    ),
    (
        "pass: the dodges are counted again on every pass",
        DD,
        "        if not seen:" + NL + '            info["found"] += len(todo)',
        '        info["found"] += len(todo)',
        TD,
    ),
    (
        "pass: a dodge removed is not the route",
        DD,
        '            trip = refine._splice(trip, number, {"legs": [new_leg], "summary": new_leg["summary"]})',
        "            pass",
        TD,
    ),
    (
        "pass: the next dodge is judged against the route as it was",
        DD,
        "            current = direct" + NL,
        "            pass" + NL,
        TD,
    ),
    ("pass: every dodge is removed", DD, "        if verdict.remove:", "        if True:", TD),
    ("pass: no dodge is removed", DD, "        if verdict.remove:", "        if False:", TD),
    (
        "pass: a route that cannot be read keeps the dodge but removes it",
        DD,
        "        if direct is None:" + NL + '            item["action"] = "kept"',
        "        if direct is None:" + NL + '            item["action"] = "removed"',
        TD,
    ),
    (
        "pass: no route keeps the dodge but says removed",
        DD,
        "    if answer is None:" + NL + '        return None, "no_route"',
        "    if False:" + NL + '        return None, "no_route"',
        TD,
    ),
    ("pass: several legs answered are taken", DD, "    if len(legs) != 1:", "    if False:", TD),
    (
        "pass: the leg is read as the first",
        DD,
        '        leg = trip["legs"][number]' + NL + "        trace = routing._trace(",
        '        leg = trip["legs"][0]' + NL + "        trace = routing._trace(",
        TD,
    ),
    (
        "pass: only the first leg is looked at",
        DD,
        '        for number in range(len(trip.get("legs") or [])):',
        '        for number in range(min(1, len(trip.get("legs") or []))):',
        TD,
    ),
    (
        "pass: the dodge is looked for in the route given, not the leg as it now is",
        DD,
        "        todo = [d for d in find_dodges(edges, shape) if _key(d, shape) not in seen]",
        "        todo = [d for d in find_dodges(edges, shape) if _key(d, shape) not in seen][:1] if not seen else []",
        TD,
    ),
    # --- the plan --------------------------------------------------------------------------------
    (
        "plan: a loop is straightened too",
        RT,
        "    dodges = None" + NL + "    if not loop:",
        "    dodges = None" + NL + "    if True:",
        TP,
    ),
    (
        "plan: the pass is not run",
        RT,
        "        trip, dodges = dedodge.apply(trip, refine_context)",
        "        dodges = None",
        TP,
    ),
    (
        "plan: the answer does not say what was done",
        RT,
        "    body = _answer(trip, refined, dodges_of=dodges)",
        "    body = _answer(trip, refined)",
        TP,
    ),
    (
        "plan: a candidate keeps its dodges",
        RT,
        "                found, found_dodges = dedodge.apply(found, refine_context)",
        "                found_dodges = None",
        TP,
    ),
    (
        "plan: a candidate's loop is straightened too",
        RT,
        "            found_dodges = None" + NL + "            if not loop:",
        "            found_dodges = None" + NL + "            if True:",
        TP,
    ),
    (
        "plan: the extra distance is not lowered",
        RT,
        'refined["extra_distance_m"] = round(refined["extra_distance_m"] - dodges["saved_m"], 1)',
        'refined["extra_distance_m"] = round(refined["extra_distance_m"] + dodges["saved_m"], 1)',
        TP,
    ),
    (
        "plan: a target that fits is still flagged as not fitting",
        RT,
        '            and refined.get("fits")'
        + NL
        + "        ):"
        + NL
        + '            refined["limited"] = None',
        '            and refined.get("fits")' + NL + "        ):" + NL + "            pass",
        TP,
    ),
    (
        "pass: the metres saved are not counted",
        DD,
        '            info["saved_m"] = round(info["saved_m"] + verdict.extra_m, 1)',
        "            pass",
        TP,
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
    """Every mutant's text occurs exactly once in its file, and changes it."""
    bad = 0
    for name, rel, old, new, _tests in MUTANTS:
        count = (ROOT / rel).read_text().count(old)
        if count != 1 or old == new:
            print(
                f"BAD   {name}: occurs {count} times in {rel}"
                + (" (no change)" if old == new else "")
            )
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
            if original.count(old) != 1 or old == new:
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
