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
PRESET_TESTS = ["tests/test_presets.py"]

TS = "src/core/trailseek.py"
RF = "src/core/refine.py"
RT = "src/core/routing.py"
PR = "src/core/presets.py"

NL = "\n"
# The longest a test file may take against a mutant (the slowest takes about 70 s).
TEST_TIMEOUT_S = 300

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- the route line ----------------------------------------------------
    (
        "busy: weight ignored",
        TS,
        "before += (s - starts[i]) * weights[i]",
        "before += (s - starts[i]) * 1.0",
        SEEK,
    ),
    (
        "busy: part span from the wrong side",
        TS,
        "if i < len(starts) and s > starts[i]:",
        "if i < len(starts) and s < starts[i]:",
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
        "rate * line.busy_to(s) + DETOUR_WEIGHT * (s + c) - credit * line.trail_to(s)",
        "rate * line.busy_to(s) + DETOUR_WEIGHT * c - credit * line.trail_to(s)",
        SEEK,
    ),
    (
        "exit: wrong side of the join",
        TS,
        "+ DETOUR_WEIGHT * (s_out - c_out)",
        "+ DETOUR_WEIGHT * (s_out + c_out)",
        SEEK,
    ),
    (
        "exit: exposure not counted",
        TS,
        "                    rate * line.busy_to(s_out)",
        "                    0.0 * line.busy_to(s_out)",
        SEEK,
    ),
    ("replaced: no least", TS, "replaced >= MIN_REPLACED_M", "replaced >= 0", SEEK),
    ("cap: not applied", TS, "and detour <= cap_m", "and detour <= cap_m * 1000", SEEK),
    ("trail: length is free", TS, "moved = cost + step_weight * length", "moved = cost", SEEK),
    ("detour: negative kept", TS, "detour_m=max(0.0, detour),", "detour_m=detour,", SEEK),
    (
        "corridor: score not required",
        TS,
        "if best is None or best.score < MIN_SCORE_M:",
        "if best is None:",
        SEEK,
    ),
    (
        "corridor: exposure not required",
        TS,
        "if best.gain_m >= MIN_EXPOSURE_M or (credit > 0 and best.trail_gain_m >= MIN_TRAIL_GAIN_M):",
        "if True:",
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
        '"AND s.stress_tier <= 2) OR %s = ANY(s.car_free_when))"',
        '"AND s.stress_tier <= 3) OR %s = ANY(s.car_free_when))"',
        SEEK,
    ),
    (
        "table: lanes are corridors",
        TS,
        "AND ((s.facility IN ('path', 'protected') \"",
        "AND ((s.facility IN ('path', 'protected', 'lane') \"",
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
        "table: the strips reach too far",
        TS,
        "reach = width_m + cell_m / 4",
        "reach = 3 * width_m + cell_m / 4",
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
        "busy.append((a - lo, b - lo, weight))",
        "busy.append((a - lo, b - lo - (b - a) / 2, weight))",
        REFINE,
    ),
    (
        "spans: traced length lost",
        RF,
        "return busy, trail, (traced or None)",
        "return busy, trail, None",
        REFINE,
    ),
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
        "if count < 1 or len(ctx.points) != len(locations) or len(legs) != count:",
        "if count < 1 or len(ctx.points) != len(locations):",
        REFINE,
    ),
    (
        "seek: any span",
        RF,
        "runnable = [k for k in range(count) if spans[k] >= trailseek.SEEK_MIN_SPAN_M]",
        "runnable = [k for k in range(count) if True]",
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
    ("seek: exclusions dropped", RF, "excluded = list(nearby)", "excluded = []", REFINE),
    ("seek: no second ask without", RF, "if read is None and excluded:", "if False:", REFINE),
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
        "            busier = read.exposure_m > _allowance(reference)",
        "            busier = False",
        REFINE,
    ),
    (
        "seek: no margin",
        RF,
        "            elif score < best_score - IMPROVEMENT_EPS_S:"
        + NL
        + '                tried["outcome"] = "taken"',
        "            elif score < best_score:" + NL + '                tried["outcome"] = "taken"',
        REFINE,
    ),
    (
        "seek: unread is taken",
        RF,
        '                tried["outcome"] = "unread"' + NL + "                continue",
        '                tried["outcome"] = "unread"',
        REFINE,
    ),
    (
        "seek: best not updated",
        RF,
        "            kept, best_score = (read, candidate), score",
        "            kept = (read, candidate)",
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
    # --- the trail credit (OWNER-DECISIONS 202) -------------------------------------
    (
        "credit: ignored in the score",
        RF,
        "            - ctx.trail_credit * self.trail_m",
        "            - 0.0 * self.trail_m",
        REFINE,
    ),
    (
        "credit: a penalty, not a credit",
        RF,
        "            - ctx.trail_credit * self.trail_m",
        "            + ctx.trail_credit * self.trail_m",
        REFINE,
    ),
    (
        "trail: a bicycle lane counts",
        RF,
        'TRAIL_KINDS = frozenset({"path", "protected"})',
        'TRAIL_KINDS = frozenset({"path", "protected", "lane"})',
        REFINE,
    ),
    (
        "trail: a protected lane does not",
        RF,
        'TRAIL_KINDS = frozenset({"path", "protected"})',
        'TRAIL_KINDS = frozenset({"path"})',
        REFINE,
    ),
    (
        "trail: LTS 3 counts",
        RF,
        'TRAIL_TIERS = frozenset({"1", "2"})',
        'TRAIL_TIERS = frozenset({"1", "2", "3"})',
        REFINE,
    ),
    (
        "trail: LTS 2 does not",
        RF,
        'TRAIL_TIERS = frozenset({"1", "2"})',
        'TRAIL_TIERS = frozenset({"1"})',
        REFINE,
    ),
    (
        "trail: looked for with no credit",
        RF,
        "flags = trail_flags(pieces, classes, ctx) if ctx.trail_credit > 0 else []",
        "flags = trail_flags(pieces, classes, ctx)",
        REFINE,
    ),
    (
        "trail: every piece counted",
        RF,
        "trail_m=sum(p.metres for p, on in zip(pieces, flags, strict=False) if on),",
        "trail_m=sum(p.metres for p, on in zip(pieces, flags, strict=False)),",
        REFINE,
    ),
    (
        "trail: rule fallback takes LTS 3",
        RF,
        "return [rule in rules and tier in (1, 2) for tier, rule in cursor.fetchall()]",
        "return [rule in rules and tier in (1, 2, 3) for tier, rule in cursor.fetchall()]",
        REFINE,
    ),
    (
        "trail: rule fallback takes any rule",
        RF,
        "return [rule in rules and tier in (1, 2) for tier, rule in cursor.fetchall()]",
        "return [rule is not None and tier in (1, 2) for tier, rule in cursor.fetchall()]",
        REFINE,
    ),
    (
        "credit: reported wrong",
        RF,
        'info["trail_credit"] = ctx.trail_credit',
        'info["trail_credit"] = 0.0',
        REFINE,
    ),
    (
        "credit: not reported after",
        RF,
        'info["trail_after_m"] = round(best.trail_m, 1)',
        'info["trail_after_m"] = info["trail_before_m"]',
        REFINE,
    ),
    (
        "corridor: credit not held under the weight",
        TS,
        "credit = min(max(credit, 0.0), DETOUR_WEIGHT * 0.95)",
        "credit = max(credit, 0.0)",
        SEEK,
    ),
    (
        "corridor: a negative credit",
        TS,
        "credit = min(max(credit, 0.0), DETOUR_WEIGHT * 0.95)",
        "credit = min(credit, DETOUR_WEIGHT * 0.95)",
        SEEK,
    ),
    (
        "corridor: the trail replaced is free",
        TS,
        "                    - credit * line.trail_to(s_out)",
        "                    - 0.0 * line.trail_to(s_out)",
        SEEK,
    ),
    (
        "corridor: entry trail not counted",
        TS,
        "rate * line.busy_to(s) + DETOUR_WEIGHT * (s + c) - credit * line.trail_to(s)",
        "rate * line.busy_to(s) + DETOUR_WEIGHT * (s + c)",
        SEEK,
    ),
    (
        "corridor: the credit is not on the trail",
        TS,
        "step_weight = DETOUR_WEIGHT - credit",
        "step_weight = DETOUR_WEIGHT",
        SEEK,
    ),
    (
        "corridor: no trail gain needed",
        TS,
        "(credit > 0 and best.trail_gain_m >= MIN_TRAIL_GAIN_M)",
        "(credit > 0)",
        SEEK,
    ),
    (
        "corridor: the gain is gross",
        TS,
        "trail_gain_m=trail[node] - (line.trail_to(s_out) - line.trail_to(s_in)),",
        "trail_gain_m=trail[node],",
        SEEK,
    ),
    (
        "corridor: a quiet route has none",
        TS,
        "if not line.starts and credit <= 0:",
        "if not line.starts:",
        SEEK,
    ),
    (
        "route line: trail spans dropped",
        TS,
        "self._cumulate(trail_spans, scale)",
        "self._cumulate((), scale)",
        SEEK,
    ),
    (
        "route line: trail spans not scaled",
        TS,
        "self._cumulate(trail_spans, scale)",
        "self._cumulate(trail_spans, 1.0)",
        SEEK,
    ),
    (
        "spans: the cut is not clipped",
        RF,
        "a, b = max(a, lo), b if hi is None else min(b, hi)",
        "a, b = a, b",
        REFINE,
    ),
    (
        "spans: trail kept off",
        RF,
        "if number < len(analysis.trail_pieces) and analysis.trail_pieces[number]:",
        "if False:",
        REFINE,
    ),
    (
        "plan: no credit",
        RT,
        "trail_credit=presets.trail_credit_for(preset_name, stress_dial),",
        "trail_credit=0.0,",
        PLAN,
    ),
    (
        "preset: everyone has the credit",
        PR,
        "credit = min(PRESETS[preset_name].trail_credit, TRAIL_CREDIT_MAX)",
        "credit = min(TRAIL_CREDIT, TRAIL_CREDIT_MAX)",
        PRESET_TESTS,
    ),
    (
        "preset: no fade with the slider",
        PR,
        "return round(credit * min(1.0, calm_rate_for(stress) / CALM_RATE_MAX), 4)",
        "return round(credit, 4)",
        PRESET_TESTS,
    ),
    (
        "preset: no cap",
        PR,
        "credit = min(PRESETS[preset_name].trail_credit, TRAIL_CREDIT_MAX)",
        "credit = PRESETS[preset_name].trail_credit",
        PRESET_TESTS,
    ),
    # --- leg by leg (OWNER-DECISIONS 203) ---------------------------------------------
    (
        "legs: the first location always starts",
        RF,
        "        locations[leg],",
        "        locations[0],",
        REFINE,
    ),
    (
        "legs: the last location always ends",
        RF,
        "        locations[leg + 1],",
        "        locations[-1],",
        REFINE,
    ),
    (
        "legs: budget not floored",
        RF,
        "leg_stop = min(stop_at, now + max(share, trailseek.SEEK_LEG_MIN_S))",
        "leg_stop = min(stop_at, now + share)",
        REFINE,
    ),
    (
        "legs: share over every leg",
        RF,
        "share = left * spans[k] / sum(spans[j] for j in runnable[turn:])",
        "share = left * spans[k] / sum(spans)",
        REFINE,
    ),
    (
        "legs: share by count, not span",
        RF,
        "share = left * spans[k] / sum(spans[j] for j in runnable[turn:])",
        "share = left / (len(runnable) - turn)",
        REFINE,
    ),
    (
        "legs: guard against the whole trip",
        RF,
        "reference = first_legs[k] if first_legs else incumbent.exposure_m",
        "reference = first_exposure",
        REFINE,
    ),
    (
        "legs: guard against what the search left",
        RF,
        "reference = first_legs[k] if first_legs else incumbent.exposure_m",
        "reference = incumbent.exposure_m",
        REFINE,
    ),
    (
        "legs: the splice adds the old leg",
        RF,
        "summary[key] = summary[key] - before[key] + after[key]",
        "summary[key] = summary[key] + before[key] + after[key]",
        REFINE,
    ),
    (
        "legs: the whole route need not be read",
        RF,
        "        if read is None or read.events is None:"
        + NL
        + '            seek["taken"] = False',
        "        if read is None:" + NL + '            seek["taken"] = False',
        REFINE,
    ),
    (
        "legs: the splice is not read",
        RF,
        "    if count > 1 and taken:",
        "    if False:",
        REFINE,
    ),
    (
        "legs: via points ignored",
        RF,
        "edges = [0.0, *analysis.via_m, total]",
        "edges = [0.0, total]",
        REFINE,
    ),
    (
        "legs: first reading's legs not used",
        RF,
        "if count > 1 and original is not None and len(original.via_m) == count - 1:",
        "if False:",
        REFINE,
    ),
    (
        "legs: a leg that is taken is not spliced",
        RF,
        "                trip = _splice(trip, k, got[1])",
        "                pass",
        REFINE,
    ),
    (
        "legs: a table that cannot be read is read again for the next leg",
        RF,
        '        if seek["limited"] == "table":',
        "        if False:",
        REFINE,
    ),
    # --- the combined correctness review, SF1: a leg's time is the leg's ------------
    (
        "legs: one leg's time ends the seek",
        RF,
        '        if seek["limited"] == "table":',
        '        if seek["limited"] in ("time", "table"):',
        REFINE,
    ),
    (
        "legs: the leg's reading is taken out of its share",
        RF,
        "                stop_at = min(hard_stop, stop_at + (routing.clock() - started))",
        "                pass",
        REFINE,
    ),
    (
        "legs: the leg's reading has no allowance of its own",
        RF,
        "                        min(hard_stop, started + SEEK_LEG_READ_S), ctx.deadline.per_call_s",
        "                        min(hard_stop, stop_at), ctx.deadline.per_call_s",
        REFINE,
    ),
    (
        "legs: an unread leg ends the seek",
        RF,
        '                seek["limited"] = "time"' + NL + "                continue",
        '                seek["limited"] = "time"' + NL + "                break",
        REFINE,
    ),
    (
        "legs: the readings may run into the answer's reserve",
        RF,
        "    hard_stop = ctx.deadline.at - REFINE_TRACE_RESERVE_S",
        "    hard_stop = ctx.deadline.at",
        REFINE,
    ),
    # --- review r1: hard bounds, the table read, the whole trip, the exclusions ------
    ("bounds: no step check", TS, "        _check_step(step_weight)" + NL, "", SEEK),
    (
        "bounds: a step of no cost passes",
        TS,
        "if not (math.isfinite(step_weight) and step_weight > 0):",
        "if not (math.isfinite(step_weight) and step_weight >= 0):",
        SEEK,
    ),
    (
        "bounds: a step past the walk's bound is not refused",
        TS,
        '            raise SeekError("the walk back along the trail is longer than its network")',
        "            pass",
        SEEK,
    ),
    (
        "bounds: no clock in the search",
        TS,
        "            if len(done) % CLOCK_EVERY == 0:"
        + NL
        + "                _check_time(stop_at, clock)",
        "            pass",
        SEEK,
    ),
    (
        "bounds: no clock between networks",
        TS,
        "        _check_time(stop_at, clock)" + NL + "        best = network.best_in(",
        "        best = network.best_in(",
        SEEK,
    ),
    (
        "bounds: the time is not up at the stop",
        TS,
        "if stop_at is not None and clock() >= stop_at:",
        "if stop_at is not None and clock() >= stop_at + 1e9:",
        SEEK,
    ),
    (
        "strips: the line is not sampled between its vertices",
        TS,
        "for k in range(1, n + 1)",
        "for k in range(n, n + 1)",
        SEEK,
    ),
    (
        "strips: a row's run is not split at a gap",
        TS,
        "if i is not None and i == previous + 1:",
        "if i is not None:",
        SEEK,
    ),
    (
        "table: no statement timeout",
        TS,
        """            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [timeout_ms])""",
        "            pass",
        SEEK,
    ),
    (
        "table: the caller's timeout is not put back",
        TS,
        """                cursor.execute("SELECT set_config('statement_timeout', %s, true)", [previous])""",
        "                pass",
        SEEK,
    ),
    (
        "table: a cancelled read is not out of time",
        TS,
        '== "57014":',
        '== "00000":',
        SEEK,
    ),
    (
        "table: the index's predicate not carried",
        TS,
        'f"({SEEK_INDEX_PREDICATE}) AND ((s.facility',
        'f"((s.facility',
        SEEK,
    ),
    (
        "table: the rebuild has no seek index",
        "src/pipeline/schema.py",
        "CREATE INDEX segment_seek_geom_idx ON {schema}.segment USING gist (geometry)"
        + NL
        + "    WHERE {seek};",
        "",
        SEEK,
    ),
    (
        "seek: the table read is given no timeout",
        RF,
        "            timeout_s=min(trailseek.TABLE_TIMEOUT_S, left),",
        "",
        REFINE,
    ),
    (
        "seek: no deadline before the table",
        RF,
        "    left = stop_at - routing.clock()" + NL + "    if left < trailseek.SEEK_ROUND_MIN_S:",
        "    left = stop_at - routing.clock()" + NL + "    if False:",
        REFINE,
    ),
    (
        "seek: no deadline before the corridors",
        RF,
        "    # there is no time to ask for."
        + NL
        + "    if stop_at - routing.clock() < trailseek.SEEK_ROUND_MIN_S:",
        "    # there is no time to ask for." + NL + "    if False:",
        REFINE,
    ),
    (
        "seek: the corridor search has no stop",
        RF,
        "            stop_at=stop_at - trailseek.SEEK_ROUND_MIN_S,",
        "            stop_at=None,",
        REFINE,
    ),
    (
        "seek: a failed corridor search is not reported",
        RF,
        '        seek["limited"] = "error"',
        '        seek["limited"] = None',
        REFINE,
    ),
    (
        "seek: the roadway-only graph is seeked",
        RF,
        "    if ctx.roadway_only:" + NL + "        # A ride on the no-trail graph",
        "    if False:" + NL + "        # A ride on the no-trail graph",
        REFINE,
    ),
    (
        "seek: the whole trip is not guarded",
        RF,
        "        if read.exposure_m > _allowance(first_exposure):",
        "        if False:",
        REFINE,
    ),
    (
        "seek: every kept exclusion is sent",
        RF,
        "    nearby = trailseek.points_in_band(ctx.kept_excludes, start, end, route, band)",
        "    nearby = list(ctx.kept_excludes)",
        REFINE,
    ),
    (
        "seek: never asked again when longer",
        RF,
        "            and read.length_m > _expected_m(incumbent, proposal)",
        "            and False",
        REFINE,
    ),
    (
        "seek: always asked again",
        RF,
        "            and read.length_m > _expected_m(incumbent, proposal)",
        "            and read.length_m > 0",
        REFINE,
    ),
    (
        "seek: asked again without the time",
        RF,
        "            and stop_at - routing.clock() >= trailseek.SEEK_ROUND_MIN_S"
        + NL
        + "        ):",
        NL + "        ):",
        REFINE,
    ),
    (
        "seek: the guard's slack dropped",
        RF,
        "    return exposure_m * (1 + EXPOSURE_TOLERANCE) + EXPOSURE_SLACK_M",
        "    return exposure_m * (1 + EXPOSURE_TOLERANCE)",
        REFINE,
    ),
    (
        "points: the band is the line's only",
        TS,
        "    return [segment[0] for segment in in_band([[p] for p in points], start, end, route, width_m)]",
        "    return [segment[0] for segment in in_band([[p] for p in points], start, end, [start], width_m)]",
        SEEK,
    ),
    (
        "bounds: no clamp and no step check (only the walk's bound is left)",
        TS,
        "credit = min(max(credit, 0.0), DETOUR_WEIGHT * 0.95)"
        + NL
        + "        step_weight = DETOUR_WEIGHT - credit"
        + NL
        + "        _check_step(step_weight)",
        "credit = max(credit, 0.0)" + NL + "        step_weight = DETOUR_WEIGHT - credit",
        SEEK,
    ),
    # --- review r2's survivors --------------------------------------------
    (
        "V01 strips: reach without the quarter cell",
        TS,
        "reach = width_m + cell_m / 4",
        "reach = width_m",
        SEEK,
    ),
    (
        "V03 strips: box east one cell short",
        TS,
        "lon0 + (previous + 1) * cell_m / kx,",
        "lon0 + previous * cell_m / kx,",
        SEEK,
    ),
    (
        "V05 strips: no cos(lat) on x",
        TS,
        "kx = 111_320.0 * math.cos(math.radians(lat0))",
        "kx = 111_320.0",
        SEEK,
    ),
    (
        "V07 table: timeout set session-wide",
        TS,
        "cursor.execute(\"SELECT set_config('statement_timeout', %s, true)\", [timeout_ms])",
        "cursor.execute(\"SELECT set_config('statement_timeout', %s, false)\", [timeout_ms])",
        SEEK,
    ),
    (
        "V08 table: restore set session-wide",
        TS,
        "cursor.execute(\"SELECT set_config('statement_timeout', %s, true)\", [previous])",
        "cursor.execute(\"SELECT set_config('statement_timeout', %s, false)\", [previous])",
        SEEK,
    ),
    (
        "V12 bounds: no clock in components",
        TS,
        "                if visited % CLOCK_EVERY == 0:"
        + NL
        + "                    _check_time(stop_at, clock)",
        "                if False:" + NL + "                    _check_time(stop_at, clock)",
        SEEK,
    ),
    (
        "V18 seek: whole-trip guard on best not first",
        RF,
        "if read.exposure_m > _allowance(first_exposure):",
        "if read.exposure_m > _allowance(best.exposure_m):",
        REFINE,
    ),
    (
        "V19 retry: expected ignores the detour",
        RF,
        "return (incumbent.length_m + proposal.detour_m) * (1 + SEEK_RETRY_OVER) + SEEK_RETRY_SLACK_M",
        "return incumbent.length_m * (1 + SEEK_RETRY_OVER) + SEEK_RETRY_SLACK_M",
        REFINE,
    ),
    (
        "seek: a whole trip past its allowance not recorded as busier",
        RF,
        '            seek["whole_trip"] = "busier"' + NL,
        "",
        REFINE,
    ),
    (
        "seek: a retry's route not counted",
        RF,
        "            answers.append((read, candidate, excluded, None))"
        + NL
        + '            seek["routes"] += 1',
        "            answers.append((read, candidate, excluded, None))",
        REFINE,
    ),
]


def _passes(copy: Path, tests: list[str]) -> bool:
    """Whether every test file passes, each in a process of its own (one test
    file per process: the lane's rule), stopping at the first that fails."""
    for test in tests:
        # A mutant can loop for ever (a negative edge in the corridor search): a
        # file that has not finished in TEST_TIMEOUT_S is a failure, and the
        # process is killed, which also bounds its memory.
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
