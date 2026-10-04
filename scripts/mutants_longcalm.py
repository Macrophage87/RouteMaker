#!/usr/bin/env python3
"""Mutants on FOLLOWUP-LONG-CALM: the order the top of the slider ranks by, the target
distance and its ceiling, the diminishing returns on extra distance, the choice where no
route fits, the effort model, the legs a long plan is cut into and how it shares the
detour among them, the routes to choose from, the loop, and the hills choice's hold.

OWNER-DECISIONS 256-271. A mutation pass run against WHOLE test files, as
`scripts/mutants_trailseek.py` does: a mutant is killed when any test in the files named
for it fails. It works on a copy of the repository and runs each test file in a process of
its own, under a timeout:

    scripts/mutants_longcalm.py [--only NAME] [--list] [--check]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"): PGDATABASE
should name a private database. Each line of MUTANTS is (name, file, old text, new text,
test files); `old` must occur exactly once. Survivors are printed last and the exit status
is the number of them.

Release review (2026-10-04): the B1, SF2, S1-S3 and 298(2)/(3) mutants at the end.
Two seams are equivalent and not entries: X05 (a long plan keeping the break points
in `stops_m`: `stops_m` is read only by `intersections.number_groups`, which is Mass
Ride's alone, and a long calm plan is Trailmaxxing's alone) and X26 (`combine`
flattening the classes: it feeds only `pick_candidates`, and the answer re-reads every
candidate it offers).
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
RFT = ["tests/test_refine.py"]

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
    # --- the ceiling (256, 268, 271) ---------------------------------------------
    (
        "ceiling: a route exactly at it is too long",
        RF,
        "    return ctx.ceiling_m is not None and length_m > ctx.ceiling_m",
        "    return ctx.ceiling_m is not None and length_m >= ctx.ceiling_m",
        LC,
    ),
    (
        "ceiling: the halves of a round are not tried",
        RF,
        "            attempts.extend(excluded + half for half in _halves(new))",
        "            pass",
        LC,
    ),
    (
        "ceiling: a round past it is called no route",
        RF,
        '                info["limited"] = "ceiling" if over else "no_route"',
        '                info["limited"] = "no_route"',
        LC,
    ),
    (
        "ceiling: a hold refusal uses up the patience",
        RF,
        "        elif not held:",
        "        else:",
        LC,
    ),
    (
        "ceiling: the default is the smaller",
        PR,
        "    return max(first_m * DEFAULT_CEILING_RATIO, first_m + DEFAULT_CEILING_EXTRA_M)",
        "    return min(first_m * DEFAULT_CEILING_RATIO, first_m + DEFAULT_CEILING_EXTRA_M)",
        PS,
    ),
    (
        "ceiling: past a target it is the target itself",
        PR,
        "    return target_m * TARGET_CEILING_RATIO",
        "    return target_m",
        PS + LC,
    ),
    (
        "ceiling: past a target it is 1.5 times it",
        PR,
        "TARGET_CEILING_RATIO = 1.25",
        "TARGET_CEILING_RATIO = 1.5",
        PS,
    ),
    (
        "ceiling: the plan's is ten times the target",
        RT,
        "            presets.target_ceiling_m(target_m)\n            if target_m",
        "            target_m * 10\n            if target_m",
        AP,
    ),
    (
        "ceiling: a route past it is weighed against the one that fits",
        RT,
        "        (o for o in past if _trip_length_m(o[0]) <= ceiling_m), key=lambda o: _trip_length_m(o[0])",
        "        (o for o in past if _trip_length_m(o[0]) <= ceiling_m * 2), key=lambda o: _trip_length_m(o[0])",
        AP,
    ),
    (
        "ceiling: a candidate may go further past the target than the answer",
        RF,
        "    return read.length_m > max(ctx.target_m, answer.length_m) + 0.5",
        "    return False",
        LC,
    ),
    (
        "ceiling: the top is any position past the old top",
        PR,
        "    return calm_rate_for(stress) >= CALM_RATE_MAX",
        "    return calm_rate_for(stress) > 0",
        PS,
    ),
    (
        "target: a longer route than the target is let through in the fit",
        RT,
        "            if probe_m <= target_m:",
        "            if probe_m <= target_m * 2:",
        AP,
    ),
    (
        "target: the bisection stays at the rung",
        RT,
        "            middle = (over + fits) // 2",
        "            middle = fits",
        AP,
    ),
    # --- where no route fits the target (267) --------------------------------------
    (
        "no fit: the shortest within the ceiling is answered, not the least stressful",
        RT,
        "        if current is None or refine.calmer(got, current, ctx):",
        "        if current is None:",
        AP,
    ),
    (
        "no fit: none within the ceiling, the shortest is answered (298(2))",
        RT,
        "        within = sorted(past, key=lambda o: _trip_length_m(o[0]))",
        "        return min(past, key=lambda o: _trip_length_m(o[0]))",
        AP,
    ),
    (
        "no fit: the router's own route is kept",
        RT,
        "    if past:\n        # The router's own route is past the target",
        "    if False:\n        # The router's own route is past the target",
        AP,
    ),
    (
        "no fit: not flagged",
        RT,
        '                "limited": "target_distance",',
        '                "limited": None,',
        AP,
    ),
    (
        "no fit: an over-target route is taken when calmer, worth it or not",
        RT,
        "            if got is not None and refine.better(got, current, ctx):",
        "            if got is not None and refine.calmer(got, current, ctx):",
        AP,
    ),
    (
        "target: the overage is negative within the target",
        RT,
        "    over = None if target_m is None else round(max(final_m - target_m, 0.0), 1)",
        "    over = None if target_m is None else round(final_m - target_m, 1)",
        AP,
    ),
    (
        "target: always said to fit",
        RT,
        '        "fits": None if target_m is None else final_m <= target_m,',
        '        "fits": None if target_m is None else True,',
        AP,
    ),
    (
        "target: a candidate's overage is not said",
        RT,
        '            if maxcalm and target_m:\n                candidate["over_target_m"]',
        '            if False:\n                candidate["over_target_m"]',
        AP,
    ),
    # --- diminishing returns on extra distance (268, 271) ---------------------------
    (
        "worth: a mile of LTS 3 buys ten miles",
        RF,
        "WORTH_DEFAULT = 5.0",
        "WORTH_DEFAULT = 10.0",
        LC,
    ),
    (
        "worth: past the target the bar is no stricter",
        RF,
        "    return max(over, 0.0) / WORTH_OVER_TARGET",
        "    return max(over, 0.0) / WORTH_DEFAULT",
        LC,
    ),
    (
        "worth: with no target the stricter bar",
        RF,
        "        return max(added, 0.0) / WORTH_DEFAULT",
        "        return max(added, 0.0) / WORTH_OVER_TARGET",
        LC,
    ),
    (
        "worth: up to the target distance is charged",
        RF,
        "    over = to_m - max(from_m, ctx.target_m)",
        "    over = to_m - from_m",
        LC,
    ),
    (
        "worth: saving exactly the charge is not enough",
        RF,
        "    return stress_saved_m(shorter, longer, ctx) >= charge",
        "    return stress_saved_m(shorter, longer, ctx) > charge",
        LC,
    ),
    (
        "worth: a red junction counts at the LTS 3 weight",
        RF,
        "        + w.lts4 * read.red_m",
        "        + w.lts3 * read.red_m",
        LC,
    ),
    (
        "worth: an orange junction saves nothing",
        RF,
        "        + w.lts3 * read.orange_m",
        "",
        LC,
    ),
    (
        "worth: Avoid counts as LTS 4",
        RF,
        "        + w.avoid * read.avoid_m",
        "        + w.lts4 * read.avoid_m",
        LC,
    ),
    (
        "worth: the stress-averse rides' 1, 8, 16",
        RF,
        "WORTH_WEIGHTS = presets.EXPOSURE_STANDARD",
        "WORTH_WEIGHTS = presets.EXPOSURE_STRESS_AVERSE",
        LC,
    ),
    (
        "worth: the charge is on the actual miles whatever the Hills slider says",
        RF,
        "        level3(longer, ctx) - level3(shorter, ctx),\n    )",
        "        None,\n    )",
        LC,
    ),
    (
        "worth: a longer route need only be calmer",
        RF,
        "        return calmer(read, best, ctx) and worth_it(best, read, ctx, rest_m)",
        "        return calmer(read, best, ctx)",
        LC,
    ),
    (
        "worth: a shorter route never replaces a calmer longer one",
        RF,
        "    return calmer(best, read, ctx) and not worth_it(read, best, ctx, rest_m)",
        "    return False",
        LC,
    ),
    (
        "worth: the rule cannot be off",
        RF,
        "    if not ctx.worth_rule:\n        return True\n    charge",
        "    charge",
        LC,
    ),
    (
        "worth: a leg of a plan with stops is charged as if it were the trip",
        RF,
        "        rest_m = 0.0 if count == 1 else _trip_m(trip) - _trip_m(leg_trip)",
        "        rest_m = 0.0",
        RFT,
    ),
    (
        "worth: a spliced trip need not be worth its miles",
        RF,
        "        if ctx.maxcalm and read.length_m > best.length_m and not worth_it(best, read, ctx):",
        "        if False:",
        RFT,
    ),
    (
        "worth: a long plan's upgrades need not be worth their miles",
        RF,
        "                if charge > 0.0 and saved < charge:",
        "                if False:",
        LC,
    ),
    (
        "worth: a long plan's upgrade is charged at the leg's length",
        RF,
        "                charge = distance_charge_m(total, total + added, ctx, blended)",
        "                charge = distance_charge_m(now.length_m, now.length_m + added, ctx, blended)",
        LC,
    ),
    (
        "worth: a long plan's legs price distance on their own",
        RF,
        "            worth_rule=False,",
        "            worth_rule=True,",
        LC,
    ),
    (
        "worth: a loop's way back need not be worth its miles",
        RF,
        "        return better(whole, best[2], ctx)",
        "        return ranked < best[0]",
        LP,
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
        "legs: a leg may use only a share of the detour",
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
        "                if ceiling_m is not None and total + added > ceiling_m:\n                    continue\n",
        "",
        LC,
    ),
    (
        "legs: the chain keeps options no calmer than the one before",
        RF,
        "        if calmer(option[1], chain[-1][1], ctx):",
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
        "    long_calm = not loop and long_calm_for(preset_name, points, stress_dial, long_ride)",
        "    long_calm = long_calm_for(preset_name, points, stress_dial, long_ride)",
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
        "overlap: back to 60%",
        RF,
        "ALT_OVERLAP = 0.70",
        "ALT_OVERLAP = 0.60",
        LC,
    ),
    (
        "overlap: loosened to 80%",
        RF,
        "ALT_OVERLAP = 0.70",
        "ALT_OVERLAP = 0.80",
        LC,
    ),
    (
        "overlap: exactly the threshold is different",
        RF,
        "        if shared / min(mine, theirs) >= ALT_OVERLAP and mine - shared < ALT_DIFFERENT_M:",
        "        if shared / min(mine, theirs) > ALT_OVERLAP and mine - shared < ALT_DIFFERENT_M:",
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
    # --- the release review ---------------------------------------------------------------
    # B1: a multi-leg plan's per-leg seek candidates never offered as whole routes.
    (
        "B1 the leg's candidates pooled on a plan of several legs",
        RF,
        "            pooled=count == 1,",
        "            pooled=True,",
        ["tests/test_candidates_whole_route.py"],
    ),
    (
        "B1 pick_candidates takes another leg count",
        RF,
        '            len(trip.get("legs") or []) != legs'
        + NL
        + "            or read.events is None",
        "            read.events is None",
        ["tests/test_candidates_whole_route.py"],
    ),
    # SF2: LTS 4 never loses to extra LTS 3.
    (
        "SF2 the second level's loss subtracts again",
        RF,
        "        return top + max(second, 0.0)",
        "        return top + second",
        LC,
    ),
    (
        "SF2 the second level's gain is dropped",
        RF,
        "        return top + max(second, 0.0)",
        "        return top",
        LC,
    ),
    (
        "SF2 the top level's tie step ignored",
        RF,
        "    if worse.top_m - calmer_one.top_m > MAXCALM_STEPS[0]:",
        "    if worse.top_m - calmer_one.top_m > 0.0:",
        LC,
    ),
    (
        "SF2 choose_options nets the levels",
        RF,
        "                saved = stress_saved_m(now, chain[k][1], ctx)",
        "                saved = stress_weight_m(now, ctx) - stress_weight_m(chain[k][1], ctx)",
        LC,
    ),
    # 298(2): the calmest found where none is within the ceiling.
    (
        "S3 the past-target reads on the whole deadline",
        RT,
        "    late = refine.late_deadline(ctx)",
        "    late = ctx.deadline",
        AP,
    ),
    # 298(3): seeking hills keeps the stress order and the target.
    (
        "298(3) seeking skips the search again",
        RT,
        "    refine_limited = _refine_limit(preset_name, points, long_ride, climb_seek, deadline, long_calm)",
        "    refine_limited = _refine_limit(preset_name, points, long_ride, seeking, deadline, long_calm)",
        AP,
    ),
    (
        "298(3) the effort tiebreak does not invert",
        RT,
        "        hills_seek_weight=hills_dial / 100 if calm_seek else 0.0,",
        "        hills_seek_weight=0.0,",
        AP,
    ),
    (
        "298(3) the climb search among alternatives at the top",
        RT,
        "    if climb_seek or avoiding:",
        "    if seeking or avoiding:",
        AP,
    ),
    (
        "298(3) hills_seek not calm_first",
        RT,
        '    seek_limited = "calm_first" if calm_seek else None',
        "    seek_limited = None",
        AP,
    ),
    # S1: a long plan's candidates in the plan's legs.
    (
        "S1 candidates keep the search's legs",
        RT,
        "        groups = plan_groups" + NL,
        '        groups = ((refined or {}).get("long") or {}).get("stops")' + NL,
        AP,
    ),
    (
        "X06 long plan keeps the break legs' leg_ends",
        RT,
        "                leg_ends = [leg_ends[e - 1] for e in ends]" + NL,
        "",
        AP,
    ),
    # S2: the ceiling stop never says no route fits.
    (
        "S2 no_fit set where one fits",
        RT,
        '            refined["no_fit"] = bool(refined.get("no_fit"))',
        '            refined["no_fit"] = not refined["fits"]',
        AP + ["tests/test_dedodge_plan.py"],
    ),
    (
        "S2 the no-fit answer not flagged",
        RT,
        '                "limited": "target_distance",' + NL + '                "no_fit": True,',
        '                "limited": "target_distance",' + NL + '                "no_fit": False,',
        AP,
    ),
    # 337 and 338: the weight range is 25-450 kg, and a weight outside it the nearer limit.
    ("337 the range's floor back at 68", EFF, "MASS_MIN_KG = 25", "MASS_MIN_KG = 68", EF + AP),
    ("337 the range's ceiling back at 140", EFF, "MASS_MAX_KG = 450", "MASS_MAX_KG = 140", EF + AP),
    (
        "338 the clamp does nothing",
        EFF,
        "    return float(min(max(mass_kg, MASS_MIN_KG), MASS_MAX_KG))",
        "    return float(mass_kg)",
        EF + AP,
    ),
    (
        "338 the plan's weight unclamped",
        PR,
        "        return effort.clamp_mass_kg(chosen)",
        "        return float(chosen)",
        EF,
    ),
    (
        "338 the API echoes the weight sent",
        API,
        "        return int(effort.clamp_mass_kg(value))",
        "        return value",
        AP,
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
