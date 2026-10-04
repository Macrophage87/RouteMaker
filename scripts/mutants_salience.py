#!/usr/bin/env python3
"""Mutants on STRESS-SALIENCE and its seams with the rest of the release.

FOLLOWUP-STRESS-SALIENCE (owner items 274-293), the unpaved brown ramp (302) and
the credits (301), with the release review's seam mutants: the high-stress lane
switch on the map (F01-F06), and the description's lanes-hidden and unpaved
surface seams in the API (X19-X31). The salience developer's 46 ad hoc mutants
(r0's 11 and r1's, under /home/steph/rmdata/tmp) are committed here so the next
merge is checked. A mutation pass run against WHOLE test files, as
`scripts/mutants_federal.py` does: a mutant is killed when the tests named for it
fail. It works on a copy of the repository under $TMPDIR and removes it at the end:

    scripts/mutants_salience.py [--only NAME] [--list] [--check] [--runner ts|py]
        --python PYTHON      the interpreter with pytest (the project's .venv311)
        --node-modules DIR   a frontend node_modules installed from the lockfile
        --node-image IMAGE   the node image (by digest); Docker runs the front end's tests offline

Each line of MUTANTS is (name, file, old text, new text, runner, tests); `old`
must occur exactly once (--check verifies that, EQUIVALENT's too). "ts" runs the
named front-end test files (the whole suite by default) with node --test in the
image; "py" runs the named pytest files (the Python tests need a PGDATABASE, as
the other mutant scripts do). Survivors are printed last and the exit status is
the number of them. EQUIVALENT lists the mutants that cannot be killed, each with
why; they are checked to apply and are not run.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SS = "frontend/src/stressStyle.js"
APP = "frontend/src/App.tsx"
MG = "frontend/src/lib/mapGlue.ts"
MV = "frontend/src/MapView.tsx"
FL = "frontend/src/lib/federalLand.ts"
FB = "frontend/src/lib/facilityBar.ts"
RD = "frontend/src/lib/routeDescription.ts"
FBX = "frontend/src/FacilityBreakdown.tsx"
RDX = "frontend/src/RouteDescription.tsx"
SW = "frontend/src/lib/highStressLanesSwitch.ts"
LEG = "frontend/src/lib/stressLegend.ts"
RC = "frontend/src/lib/routeColours.ts"
MS = "frontend/src/lib/mapStyle.ts"
D = "src/routemaker/describe.py"
G = "src/core/routing.py"
R = "src/core/refine.py"

TS = ["src/**/*.test.mjs", "src/**/*.test.ts"]
DESCRIBE = ["tests/test_describe.py"]
PYALL = [
    "tests/test_describe.py",
    "tests/test_route_description.py",
    "tests/test_stress.py",
    "tests/test_longcalm.py",
    "tests/test_longcalm_api.py",
    "tests/test_route_api.py",
]

LANE_CUT = '["<", ["to-number", ["get", "tier"], 0], HIGH_STRESS_LANE_MIN_TIER]'

# (name, file, old, new, runner, tests)
MUTANTS: list[tuple[str, str, str, str, str, list[str]]] = [
    # --- r0: the high-stress lane switch (OWNER-DECISIONS 275) ----------------------
    (
        "M1 threshold 4->5",
        SS,
        "HIGH_STRESS_LANE_MIN_TIER = 4;",
        "HIGH_STRESS_LANE_MIN_TIER = 5;",
        "ts",
        TS,
    ),
    (
        "M2 threshold 4->3",
        SS,
        "HIGH_STRESS_LANE_MIN_TIER = 4;",
        "HIGH_STRESS_LANE_MIN_TIER = 3;",
        "ts",
        TS,
    ),
    (
        "M3 default off->on",
        SS,
        "let highStressLanes = storedHighStressLanes() === true;",
        "let highStressLanes = storedHighStressLanes() !== false;",
        "ts",
        TS,
    ),
    ("M4 overlay < to <=", SS, LANE_CUT, LANE_CUT.replace('["<"', '["<="'), "ts", TS),
    (
        "M5 bar >= to >",
        FB,
        "span.tier >= HIGH_STRESS_LANE_MIN_TIER",
        "span.tier > HIGH_STRESS_LANE_MIN_TIER",
        "ts",
        TS,
    ),
    (
        "M6 description < to <=",
        RD,
        "entry.tier < HIGH_STRESS_LANE_MIN_TIER",
        "entry.tier <= HIGH_STRESS_LANE_MIN_TIER",
        "ts",
        TS,
    ),
    (
        "M7 bar default off->on",
        FB,
        "showHighStressLanes = false,",
        "showHighStressLanes = true,",
        "ts",
        TS,
    ),
    (
        "M8 description default flips",
        RD,
        "  showHighStressLanes: boolean = highStressLanesOn(),\n): DescriptionEntry[] | null {",
        "  showHighStressLanes: boolean = !highStressLanesOn(),\n): DescriptionEntry[] | null {",
        "ts",
        TS,
    ),
    (
        "M9 filter ignores the switch",
        SS,
        'facility.facility === "lane" && !showHighLanes',
        'facility.facility === "lane" && false',
        "ts",
        TS,
    ),
    ("M10 overlay filter hides every tier", SS, "HIGH_STRESS_LANE_MIN_TIER]);", "0]);", "ts", TS),
    (
        "M11 protected hidden too",
        SS,
        'facility.facility === "lane" && !showHighLanes',
        'facility.facility !== "path" && !showHighLanes',
        "ts",
        TS,
    ),
    # --- r1: harshness (292) --------------------------------------------------------
    (
        "H1 LTS 3 casing back to #2b1a05",
        SS,
        '3: { color: "#bf730b", casing: "#45290a" },',
        '3: { color: "#bf730b", casing: "#2b1a05" },',
        "ts",
        TS,
    ),
    (
        "H2 LTS 3 dash back to [2, 1]",
        SS,
        'short: "LTS 3", dash: [2, 0.4],',
        'short: "LTS 3", dash: [2, 1],',
        "ts",
        TS,
    ),
    (
        "H3 strong pushes LTS 3 casing to black",
        SS,
        "casing: strongerCasing(colours.casing, busy)",
        "casing: strongerCasing(colours.casing, shape.tier === 5)",
        "ts",
        TS,
    ),
    (
        "H4 twotone LTS 4 casing back to #d42020",
        SS,
        '4: { color: "#f28c28", casing: "#c81e1e" },',
        '4: { color: "#f28c28", casing: "#d42020" },',
        "ts",
        TS,
    ),
    (
        "H5 Avoid gaps thinned",
        SS,
        "dash: [5, 1, 0.5, 1], width: 6.5",
        "dash: [5, 0.25, 0.5, 0.25], width: 6.5",
        "ts",
        TS,
    ),
    (
        "H6 LTS 3 gap 0.5",
        SS,
        'short: "LTS 3", dash: [2, 0.4],',
        'short: "LTS 3", dash: [2, 0.5],',
        "ts",
        TS,
    ),
    (
        "H7 gapHarshness counts dashes not gaps",
        SS,
        "tier.dash.filter((_, i) => i % 2 === 1)",
        "tier.dash.filter((_, i) => i % 2 === 0)",
        "ts",
        TS,
    ),
    (
        "H8 cvd LTS 3 casing black",
        SS,
        '3: { color: "#cd4b0a", casing: "#0a1a2f" },',
        '3: { color: "#cd4b0a", casing: "#000000" },',
        "ts",
        TS,
    ),
    # --- r1: unpaved trails' rails (290) ---------------------------------------------
    (
        "U1 no unpaved filter on path",
        SS,
        'if (facility.facility === "path") filter.push(["!=", ["get", "unpaved"], true]);',
        "",
        "ts",
        TS,
    ),
    (
        "U2 != becomes ==",
        SS,
        'filter.push(["!=", ["get", "unpaved"], true]);',
        'filter.push(["==", ["get", "unpaved"], true]);',
        "ts",
        TS,
    ),
    (
        "U3 filter on every facility",
        SS,
        'if (facility.facility === "path") filter.push(["!=", ["get", "unpaved"], true]);',
        'filter.push(["!=", ["get", "unpaved"], true]);',
        "ts",
        TS,
    ),
    (
        "U4 filter reads trail not unpaved",
        SS,
        'filter.push(["!=", ["get", "unpaved"], true]);',
        'filter.push(["!=", ["get", "trail"], true]);',
        "ts",
        TS,
    ),
    (
        "U5 unknown surface dropped too",
        SS,
        'filter.push(["!=", ["get", "unpaved"], true]);',
        'filter.push(["==", ["get", "unpaved"], false]);',
        "ts",
        TS,
    ),
    (
        "U6 path rail back to 4",
        SS,
        'color: "#4c1d95", rail: 2.5, dash: null',
        'color: "#4c1d95", rail: 4, dash: null',
        "ts",
        TS,
    ),
    # (U7 and U7b were App.tsx's legend words; the legend is lib/stressLegend.ts now.)
    (
        "U7 legend loses the unpaved-trail line",
        LEG,
        "An unpaved trail has no edge lines, only the dotted center line. ",
        "",
        "ts",
        TS,
    ),
    (
        "U7b Unpaved entry loses its line",
        LEG,
        "dotted center line. An unpaved trail has no edge lines, which a paved path has.",
        "dotted center line.",
        "ts",
        TS,
    ),
    # --- r1: the painted rail with the switch on (SF6) -------------------------------
    (
        "P1 strongRail 1.5 -> 1",
        SS,
        "rail: 1, strongRail: 1.5,",
        "rail: 1, strongRail: 1,",
        "ts",
        TS,
    ),
    (
        "P2 railWidth ignores strong",
        SS,
        "return strong && facility.strongRail ? facility.strongRail : facility.rail;",
        "return facility.rail;",
        "ts",
        TS,
    ),
    (
        "P3 tiers never strong",
        SS,
        "casingExtra: STRONG_CASING_EXTRA_PX, strong: true }",
        "casingExtra: STRONG_CASING_EXTRA_PX, strong: false }",
        "ts",
        TS,
    ),
    (
        "P4 map width drops tier.strong",
        SS,
        "facilityWidth(facility, tier.width, tier.casingExtra, tier.strong)]);",
        "facilityWidth(facility, tier.width, tier.casingExtra)]);",
        "ts",
        TS,
    ),
    ("P5 strongRail 2.5", SS, "rail: 1, strongRail: 1.5,", "rail: 1, strongRail: 2.5,", "ts", TS),
    (
        "P6 legend drops base.strong",
        SS,
        "facilityWidth(facility, base.width, base.casingExtra, base.strong)])),",
        "facilityWidth(facility, base.width, base.casingExtra)])),",
        "ts",
        TS,
    ),
    (
        "P7 default painted rail 1.5",
        SS,
        "rail: 1, strongRail: 1.5,",
        "rail: 1.5, strongRail: 1.5,",
        "ts",
        TS,
    ),
    (
        "P8 fallback width drops strong",
        SS,
        "facilityWidth(facility, tiers[0].width, tiers[0].casingExtra, tiers[0].strong)];",
        "facilityWidth(facility, tiers[0].width, tiers[0].casingExtra)];",
        "ts",
        TS,
    ),
    # --- r1: the phrase both languages share ------------------------------------------
    (
        "C1 FACILITY_WORDS lane reworded",
        D,
        '"lane": "painted bike lane"}',
        '"lane": "painted lane"}',
        "py",
        DESCRIBE,
    ),
    (
        "C2 front end phrase reworded",
        RD,
        'export const PAINTED_LANE_WORDS = ", painted bike lane";',
        'export const PAINTED_LANE_WORDS = ", painted lane";',
        "py",
        DESCRIBE,
    ),
    (
        "C3 backend tiers only Avoid",
        D,
        'HIGH_STRESS_LANE_TIERS = frozenset({"4", "5"})',
        'HIGH_STRESS_LANE_TIERS = frozenset({"5"})',
        "py",
        DESCRIBE,
    ),
    (
        "C4 front end threshold 4 -> 3 (seen by the API's test)",
        SS,
        "export const HIGH_STRESS_LANE_MIN_TIER = 4;",
        "export const HIGH_STRESS_LANE_MIN_TIER = 3;",
        "py",
        DESCRIBE,
    ),
    (
        "C5 tier_words joiner",
        D,
        'return f"{words}, {extra}" if extra else words',
        'return f"{words}; {extra}" if extra else words',
        "py",
        DESCRIBE,
    ),
    # --- r1: the description's surface and lanes-hidden (SF3, SF5) ---------------------
    (
        "B1 merge check ignores members",
        D,
        "if any(m.tier not in HIGH_STRESS_LANE_TIERS for m in (members or [run])):",
        "if any(m.tier not in HIGH_STRESS_LANE_TIERS for m in [run]):",
        "py",
        DESCRIBE,
    ),
    (
        "B2 unpaved threshold a third",
        D,
        "if run.unpaved_m >= run.metres / 2:",
        "if run.unpaved_m >= run.metres / 3:",
        "py",
        DESCRIBE,
    ),
    (
        "B3 surface not said in text",
        D,
        '        words = f"{words}, {surface}"',
        "        words = words",
        "py",
        DESCRIBE,
    ),
    (
        "B4 join drops unpaved metres",
        D,
        "    a.unpaved_m += b.unpaved_m",
        "    pass",
        "py",
        DESCRIBE,
    ),
    (
        "B4b absorb drops unpaved metres",
        D,
        "                target.unpaved_m += run.unpaved_m",
        "                pass",
        "py",
        DESCRIBE,
    ),
    (
        "B4c runs_of drops unpaved metres",
        D,
        "            run.unpaved_m += atom.metres if atom.unpaved else 0.0",
        "            pass",
        "py",
        DESCRIBE,
    ),
    (
        "B5 overview merge drops unpaved",
        D,
        "unpaved_m=sum(m.unpaved_m for m in members),",
        "unpaved_m=0.0,",
        "py",
        DESCRIBE,
    ),
    (
        "B6 client ignores text_lanes_hidden",
        RD,
        'return typeof entry.text_lanes_hidden === "string" ? { ...entry, facility: null, text: entry.text_lanes_hidden } : entry;',
        "return entry;",
        "ts",
        TS,
    ),
    # The switch is shown with or without the stress map now (the a11y review's SF4).
    (
        "B7 switch not drawn",
        APP,
        '            <HighStressLanesSwitch on={showHighLanes} onChange={(on) => setHighStressLanes(on)} overlay={stress === "available"} />\n',
        "",
        "ts",
        TS,
    ),
    (
        "B7b switch back inside the overlay block",
        APP,
        '            <HighStressLanesSwitch on={showHighLanes} onChange={(on) => setHighStressLanes(on)} overlay={stress === "available"} />\n            {stress === "available" && (\n              <>\n',
        '            {stress === "available" && (\n              <>\n            <HighStressLanesSwitch on={showHighLanes} onChange={(on) => setHighStressLanes(on)} overlay={stress === "available"} />\n',
        "ts",
        TS,
    ),
    (
        "B7c no-map words never used",
        SW,
        "overlay ? HIGH_STRESS_LANES_HINT : HIGH_STRESS_LANES_NO_MAP_HINT",
        "HIGH_STRESS_LANES_HINT",
        "ts",
        TS,
    ),
    (
        "S1 hint back to 300 characters",
        SW,
        'Protected lanes and paths always show.";',
        'Protected lanes and paths always show. Turn this on to draw them on the map and count them in the route bike facilities and description, as before. Kept in this browser.";',
        "ts",
        TS,
    ),
    # --- the release review's seams: the lane switch on the map (F01-F06) ------------
    (
        "F01 ride-time change ignores the lane switch",
        MG,
        "  const filters = stressFilters(when);\n  for (const [id, filter]",
        "  const filters = stressFilters(when, false);\n  for (const [id, filter]",
        "ts",
        TS,
    ),
    (
        "F02 lane switch handler runs only before load",
        MG,
        "  if (!map || !loaded) return;\n  setStressWhen(map, when);",
        "  if (!map || loaded) return;\n  setStressWhen(map, when);",
        "ts",
        TS,
    ),
    (
        "F02b MapView's subscription forgets the switch",
        MV,
        "subscribeHighStressLanes(() => onLaneSwitch(mapRef.current, loaded.current, callbacks.current.when)),",
        "subscribeHighStressLanes(() => {}),",
        "ts",
        TS,
    ),
    (
        "F03 lane cut replaces the ride-time part",
        SS,
        f'    if (facility.facility === "lane" && !showHighLanes) filter.push({LANE_CUT});',
        f'    if (facility.facility === "lane" && !showHighLanes) filter.splice(1, 1, {LANE_CUT});',
        "ts",
        TS,
    ),
    (
        "F04 lane cut on the ride-time tier",
        SS,
        LANE_CUT,
        '["<", ["to-number", tierAt(when), 0], HIGH_STRESS_LANE_MIN_TIER]',
        "ts",
        TS,
    ),
    (
        "F05 federal layers above the stress overlay",
        FL,
        'return (layers.find((l) => l.source === stressSourceId) ?? layers.find((l) => l.type === "symbol"))?.id;',
        'return layers.find((l) => l.type === "symbol")?.id;',
        "ts",
        TS,
    ),
    (
        "F06 initial overlay ignores the stored lane switch",
        SS,
        "    ...facilityLayers(sourceId, when),\n",
        "    ...facilityLayers(sourceId, when, false),\n",
        "ts",
        TS,
    ),
    # --- the release review's seams: the description in the API (X19-X31) -----------
    (
        "X19 overview hidden ignores the members",
        D,
        "hidden = _lanes_hidden(run, runs[first : last + 1])",
        "hidden = _lanes_hidden(run)",
        "py",
        PYALL,
    ),
    (
        "X20 overview hidden skips the first member",
        D,
        "hidden = _lanes_hidden(run, runs[first : last + 1])",
        "hidden = _lanes_hidden(run, runs[first + 1 : last + 1])",
        "py",
        PYALL,
    ),
    (
        "X21 lanes hidden when all members high, not any",
        D,
        "    if any(m.tier not in HIGH_STRESS_LANE_TIERS for m in (members or [run])):",
        "    if all(m.tier not in HIGH_STRESS_LANE_TIERS for m in (members or [run])):",
        "py",
        PYALL,
    ),
    (
        "X22 overview hidden text loses its then-clause",
        D,
        "_stretch_sentence(hidden, start, end, turn, continues, then)",
        "_stretch_sentence(hidden, start, end, turn, continues)",
        "py",
        PYALL,
    ),
    (
        "X23 full stretch hidden never null",
        D,
        "_stretch_sentence(hidden, start, end, turn, continues) if hidden else None",
        "_stretch_sentence(hidden or run, start, end, turn, continues)",
        "py",
        PYALL,
    ),
    (
        "X24 PieceClass drops unpaved",
        G,
        "        pair.unpaved = unpaved\n",
        "        pair.unpaved = None\n",
        "py",
        PYALL,
    ),
    (
        "X25 description atoms lose unpaved",
        G,
        '                            getattr(classes[i], "unpaved", None),',
        "                            None,",
        "py",
        PYALL,
    ),
    (
        "X28 join drops the follower's unpaved",
        D,
        "    a.metres += b.metres\n    a.unpaved_m += b.unpaved_m\n",
        "    a.metres += b.metres\n",
        "py",
        PYALL,
    ),
    (
        "X29 tiny stretch's unpaved lost forward",
        D,
        "                target.unpaved_m += run.unpaved_m\n",
        "",
        "py",
        PYALL,
    ),
    (
        "X30 overview group's unpaved is the first's",
        D,
        "        unpaved_m=sum(m.unpaved_m for m in members),",
        "        unpaved_m=first.unpaved_m,",
        "py",
        PYALL,
    ),
    (
        "X31 no-trail variant drops the surface",
        G,
        '            if roadway_only and kind in ROADWAY_ONLY_AS_NONE:\n                kind = "none"\n',
        '            if roadway_only and kind in ROADWAY_ONLY_AS_NONE:\n                kind = "none"\n            if roadway_only:\n                unpaved = None\n',
        "py",
        PYALL,
    ),
    # --- the legend (moved out of App.tsx; SF5 swatch length, N2 plain words) ---------
    (
        "L1 legend swatch back to 40 px",
        SS,
        "export const LEGEND_SWATCH_PX = 64;",
        "export const LEGEND_SWATCH_PX = 40;",
        "ts",
        TS,
    ),
    (
        "L2 legend tier swatch drops its dash",
        LEG,
        "    line(6, tier.color, widths.line, dashPx(tier.dash, widths.line)),",
        "    line(6, tier.color, widths.line),",
        "ts",
        TS,
    ),
    (
        "L3 legend tier swatch casing is the line's width",
        LEG,
        "    line(6, tier.casing, widths.casing),\n    line(6, tier.color",
        "    line(6, tier.casing, widths.line),\n    line(6, tier.color",
        "ts",
        TS,
    ),
    (
        "L4 legend says what LTS is no more",
        LEG,
        '    h("p", { className: "hint lts-means" }, LTS_MEANS),',
        "    null,",
        "ts",
        TS,
    ),
    (
        "L5 facility legend ignores the switch",
        LEG,
        '(showHighLanes ? "shown, because the switch above is on."',
        '(false ? "shown, because the switch above is on."',
        "ts",
        TS,
    ),
    (
        "L6 facility legend lists every rail",
        LEG,
        "FACILITIES.filter((facility) => facilities.has(facility.facility)).map(",
        "FACILITIES.map(",
        "ts",
        TS,
    ),
    # --- SF5: cvd Avoid's own casing ---------------------------------------------------
    (
        "A1 cvd Avoid on white again",
        SS,
        '5: { color: "#08081e", casing: "#f0e442" },',
        '5: { color: "#08081e", casing: "#ffffff" },',
        "ts",
        TS,
    ),
    (
        "A2 cvd Avoid on LTS 3's orange",
        SS,
        '5: { color: "#08081e", casing: "#f0e442" },',
        '5: { color: "#08081e", casing: "#cd4b0a" },',
        "ts",
        TS,
    ),
    # --- 302: unpaved in one brown ramp ----------------------------------------------
    (
        "W1 unpaved line keeps the stress colour",
        SS,
        "...linePaint(byUnpaved(tier.unpavedColor, tier.color), tier.width",
        "...linePaint(tier.color, tier.width",
        "ts",
        TS,
    ),
    (
        "W2 unpaved casing is the paved one",
        SS,
        "  const full = byUnpaved(tier.unpavedCasing, tier.casing);",
        "  const full = tier.casing;",
        "ts",
        TS,
    ),
    (
        "W3 unpaved dots in the paved casing",
        SS,
        '      "line-color": tier.unpavedCasing,\n      "line-width": unpavedWidth(tier),',
        '      "line-color": tier.casing,\n      "line-width": unpavedWidth(tier),',
        "ts",
        TS,
    ),
    (
        "W4 ramp out of order (LTS 3 and 4 swapped)",
        SS,
        '    3: { color: "#8c5e2e", casing: "#f6ead2" },\n    4: { color: "#5e3a17", casing: "#f6ead2" },',
        '    3: { color: "#5e3a17", casing: "#f6ead2" },\n    4: { color: "#8c5e2e", casing: "#f6ead2" },',
        "ts",
        TS,
    ),
    (
        "W5 LTS 1 tan as the amber",
        SS,
        '    1: { color: "#d9b98c", casing: "#3b2410" },',
        '    1: { color: "#c27a1a", casing: "#3b2410" },',
        "ts",
        TS,
    ),
    (
        "W6 LTS 2 brown on a light casing",
        SS,
        '    2: { color: "#b58a55", casing: "#3b2410" },',
        '    2: { color: "#b58a55", casing: "#f6ead2" },',
        "ts",
        TS,
    ),
    (
        "W7 cvd ramp is the stress colours",
        SS,
        '    1: { color: "#e0c68a", casing: "#2a200c" },',
        '    1: { color: "#d2eafc", casing: "#2a200c" },',
        "ts",
        TS,
    ),
    (
        "W8 strong leaves the calm unpaved casing",
        SS,
        "      unpavedCasing: strong ? strongerCasing(unpaved.casing, busy) : unpaved.casing,",
        "      unpavedCasing: unpaved.casing,",
        "ts",
        TS,
    ),
    (
        "W9 route ignores the surface",
        RC,
        "  if (span.unpaved === true) {",
        "  if (false) {",
        "ts",
        TS,
    ),
    (
        "W10 unpaved trail on the route is violet",
        RC,
        '    const tier = span.tier ?? (span.facility === "path" ? 1 : null);',
        '    const tier = span.facility === "path" ? null : span.tier;',
        "ts",
        TS,
    ),
    (
        "W11 route unpaved mark on every section",
        MG,
        '    filter: ["==", ["get", "unpaved"], true],\n    layout: { "line-join": "round" as const },',
        '    filter: ["has", "key"],\n    layout: { "line-join": "round" as const },',
        "ts",
        TS,
    ),
    (
        "W12 route unpaved mark never dimmed",
        MG,
        '  map.setPaintProperty(ROUTE_UNPAVED_LAYER_ID, "line-opacity", paint.sectionOpacity);\n',
        "",
        "ts",
        TS,
    ),
    (
        "W13 route section halo paved",
        RC,
        "      halo: tier.unpavedCasing,",
        "      halo: tier.color,",
        "ts",
        TS,
    ),
    (
        "W14 legend ramp one brown",
        LEG,
        "        seg(i, tier.unpavedColor, widths.line),",
        "        seg(i, tiers[0].unpavedColor, widths.line),",
        "ts",
        TS,
    ),
    # --- 301: the sources cited --------------------------------------------------------
    (
        "K1 the other sources not cited",
        MS,
        "  ...FEDERAL_CREDITS,\n  ...SOURCE_CREDITS,\n];",
        "  ...FEDERAL_CREDITS,\n];",
        "ts",
        TS,
    ),
    (
        "K2 elevation not cited",
        MS,
        '  "Elevation and climb: U.S. Geological Survey 3D Elevation Program (3DEP)",\n',
        "",
        "ts",
        TS,
    ),
]

# Mutants that cannot be killed, with why. Checked to apply (so they go stale loudly), not run.
EQUIVALENT: list[tuple[str, str, str, str, str]] = [
    (
        "X05 long plan's stops keep the break points",
        G,
        "                stops_m = [stops_m[f] for f in first]\n",
        "",
        "stops_m is read only by intersections.number_groups, which runs for Mass Ride alone, and a long calm plan is Trailmaxxing's alone, so the break points never reach it",
    ),
    (
        "X26 long-calm joined reading flattens classes",
        R,
        "        classes=[c for r in reads for c in r.classes],",
        "        classes=[(c[0], c[1]) for r in reads for c in r.classes],",
        "combine() feeds only pick_candidates, and the answer and each candidate are read again from their own trip before anything uses their classes' surface",
    ),
    (
        "X27 PieceClass copy loses unpaved",
        G,
        "        return (self[0], self[1], self.unpaved)",
        "        return (self[0], self[1])",
        "pickle restores the instance __dict__ after __getnewargs__, so unpaved comes back either way (salience r1's R3)",
    ),
]


def copy_tree(dest: Path) -> None:
    files = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for name in files:
        src = ROOT / name
        if src.is_file():
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    (dest / "frontend" / "node_modules").mkdir(exist_ok=True)


def run_tests(runner: str, tests: list[str], work: Path, args: argparse.Namespace) -> bool:
    """True when the tests pass."""
    if runner == "py":
        for test in tests:
            cmd = [args.python, "-m", "pytest", test, "-x", "-q", "-p", "no:cacheprovider"]
            if subprocess.run(cmd, cwd=work, capture_output=True, timeout=1800).returncode != 0:
                return False
        return True
    cmd = [
        "docker", "run", "--rm", "--network", "none", "--memory", "2500m", "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
        "-v", f"{work}:/w", "-v", f"{args.node_modules}:/w/frontend/node_modules:ro", "-w", "/w/frontend",
        args.node_image, "node", "--test", *tests,
    ]  # fmt: skip
    return (
        subprocess.run(cmd, capture_output=True, timeout=900, stdin=subprocess.DEVNULL).returncode
        == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--runner", choices=["ts", "py"])
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--node-image", default="")
    args = parser.parse_args()
    chosen = [
        m
        for m in MUTANTS
        if (not args.only or args.only in m[0]) and (not args.runner or m[4] == args.runner)
    ]
    if args.list:
        for name, file, _, _, runner, _ in chosen:
            print(f"{runner}  {name}  ({file})")
        for name, file, _, _, why in EQUIVALENT:
            print(f"--  {name}  ({file}): equivalent, {why}")
        return 0
    bad = 0
    for name, file, old, *_ in [*chosen, *EQUIVALENT]:
        count = (ROOT / file).read_text(encoding="utf-8").count(old)
        if count != 1:
            print(f"BAD   {name}: old text occurs {count} times in {file}", file=sys.stderr)
            bad += 1
    if bad:
        return 99
    if args.check:
        print(
            f"{len(chosen)} mutants and {len(EQUIVALENT)} equivalent ones, each with its old text exactly once"
        )
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="mutants-salience-"))
    survivors: list[str] = []
    try:
        work = tmp / "repo"
        copy_tree(work)
        for key in sorted({(m[4], tuple(m[5])) for m in chosen}):
            if not run_tests(key[0], list(key[1]), work, args):
                print(
                    f"the unmutated {key[0]} tests fail ({' '.join(key[1])}); nothing to compare",
                    file=sys.stderr,
                )
                return 98
        for name, file, old, new, runner, tests in chosen:
            path = work / file
            original = path.read_text(encoding="utf-8")
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            try:
                passed = run_tests(runner, tests, work, args)
            except subprocess.TimeoutExpired:
                passed = False
            finally:
                path.write_text(original, encoding="utf-8")
            print(f"{'SURVIVED' if passed else 'killed  '} {name}", flush=True)
            if passed:
                survivors.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(
        f"\n{len(chosen) - len(survivors)} of {len(chosen)} killed; survivors: {survivors or 'none'}"
    )
    for name, _, _, _, why in EQUIVALENT:
        print(f"  equivalent, not run: {name}: {why}")
    return len(survivors)


if __name__ == "__main__":
    sys.exit(main())
