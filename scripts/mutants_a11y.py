#!/usr/bin/env python3
"""Mutants on the front end's accessibility fixes (FIX-A11Y, 2026-10-02).

The combined a11y review of integrate-2 and OWNER-DECISIONS 220 (blind stokers
are a real audience). A mutation pass over what the fix added, run against
WHOLE test files: a mutant is killed when any test in the files named for it
fails. It works on a copy of frontend/ so the tree being worked on is never
edited, and runs the files with `node --test`:

    scripts/mutants_a11y.py NODE_MODULES_DIR [--only NAME] [--list]

Run it where Node 22 is (the node:22 image has python3 too). Each line of
MUTANTS is (name, file, old text, new text, test files); `old` must occur
exactly once. Survivors are printed last and the exit status is their number.
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

CARD = ["src/lib/junctionCard.test.ts"]
MARKERS = ["src/lib/intersectionMarkers.test.ts"]
SUMMARY = ["src/lib/summary.test.ts"]
SETTLE = ["src/lib/settle.test.ts"]
SKIP = ["src/lib/skipLink.test.ts"]
FIXES = ["src/a11yFixes.test.ts"]
STYLES = ["src/stylesAccessibility.test.ts", "src/a11yFixes.test.ts"]
DIALS = ["src/lib/dialsPanel.test.ts"]
TARGET = ["src/lib/targetDistance.test.ts"]
LOOP = ["src/lib/loop.test.ts"]
CANDS = ["src/lib/candidates.test.ts"]
LANES = ["src/lib/highStressLanes.test.ts"]
FEDERAL = ["src/lib/federalLand.test.ts"]

JC = "src/lib/junctionCard.ts"
IM = "src/lib/intersectionMarkers.ts"
SU = "src/lib/summary.ts"
SE = "src/lib/settle.ts"
SK = "src/lib/skipLink.ts"
CSS = "src/styles.css"
MV = "src/MapView.tsx"
DP = "src/DialsPanel.tsx"
APP = "src/App.tsx"
DPL = "src/lib/dialsPanel.ts"
DI = "src/lib/dials.ts"
CA = "src/lib/candidates.ts"
CP = "src/lib/candidatePicker.ts"
LO = "src/lib/loop.ts"
SW = "src/lib/highStressLanesSwitch.ts"
RD = "src/lib/routeDescription.ts"
FG = "src/lib/federalLegend.ts"
FD = "src/lib/federalLand.ts"

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- the junction card's focus ------------------------------------------
    ("list's card takes the focus", JC, 'return opener === "marker";', "return true;", CARD),
    (
        "focus back only when both",
        JC,
        "return focusWasInCard || focusOnBody ? opener : null;",
        "return focusWasInCard && focusOnBody ? opener : null;",
        CARD,
    ),
    (
        "focus back always",
        JC,
        "return focusWasInCard || focusOnBody ? opener : null;",
        "return opener;",
        CARD,
    ),
    ("Escape everywhere", JC, 'return cardOpen && focusAt !== "other";', "return cardOpen;", CARD),
    (
        "Escape with no card",
        JC,
        'return cardOpen && focusAt !== "other";',
        'return focusAt !== "other";',
        CARD,
    ),
    (
        "card name keeps the capital",
        JC,
        "${item.where.charAt(0).toLowerCase()}${item.where.slice(1)}",
        "${item.where}",
        CARD,
    ),
    (
        "group holding by its first only",
        JC,
        "group.members.some((member) => member.index === index)",
        "group.members[0].index === index",
        CARD,
    ),
    # --- the credits ---------------------------------------------------------
    (
        "credits collapse at the edge excluded",
        JC,
        "mapWidth > CREDITS_COLLAPSE_PX",
        "mapWidth >= CREDITS_COLLAPSE_PX",
        CARD,
    ),
    (
        "credits never collapse",
        JC,
        '  element.classList.remove("maplibregl-compact-show");\n',
        "",
        CARD,
    ),
    (
        "credits collapse when not shown",
        JC,
        ' || !element.classList.contains("maplibregl-compact-show")) return false;',
        ") return false;",
        CARD,
    ),
    (
        "credits added after the scales",
        MV,
        'map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: MAP_ATTRIBUTION }), "bottom-right");\n    collapseCredits',
        "collapseCredits",
        FIXES,
    ),
    ("no short credit", CSS, 'content: "© OpenStreetMap" / "";', 'content: "";', FIXES),
    # --- grouping ------------------------------------------------------------
    ("groups at the last zoom", IM, "  if (zoom >= maxZoom) return 0;\n", "", MARKERS),
    (
        "last zoom exclusive",
        IM,
        "const radius = zoom >= maxZoom ? 0",
        "const radius = zoom > maxZoom ? 0",
        MARKERS,
    ),
    (
        "no overlap groups above 14",
        IM,
        "zoom < GROUP_BELOW_ZOOM ? GROUP_RADIUS_PX : OVERLAP_RADIUS_PX",
        "zoom < GROUP_BELOW_ZOOM ? GROUP_RADIUS_PX : 0",
        MARKERS,
    ),
    (
        "overlap radius exclusive",
        IM,
        "Math.hypot(g.at.x - at.x, g.at.y - at.y) <= radius",
        "Math.hypot(g.at.x - at.x, g.at.y - at.y) < radius",
        MARKERS,
    ),
    (
        "focused marker not raised",
        CSS,
        ".junction-marker:focus,\n.junction-marker:hover {\n  z-index: 3;",
        ".junction-marker:focus,\n.junction-marker:hover {\n  z-index: auto;",
        FIXES,
    ),
    # --- words ---------------------------------------------------------------
    (
        "row says Higher alone",
        IM,
        'label: "Higher stress", short: "Higher stress"',
        'label: "Higher stress", short: "Higher"',
        MARKERS,
    ),
    # (The release review's stale_fe.py: long-calm appended the target and the loop note, and
    # the a11y review's N4 the other routes to choose from.)
    (
        "announcement drops the reds",
        SU,
        "[figures, detourSaid(route, points), redJunctionsSaid(route), targetSaid(route), loopNote(route), others]",
        "[figures, detourSaid(route, points), targetSaid(route), loopNote(route), others]",
        SUMMARY,
    ),
    (
        "announcement drops the detour",
        SU,
        "[figures, detourSaid(route, points), redJunctionsSaid(route), targetSaid(route), loopNote(route), others]",
        "[figures, redJunctionsSaid(route), targetSaid(route), loopNote(route), others]",
        SUMMARY,
    ),
    (
        "announcement drops the target",
        SU,
        "[figures, detourSaid(route, points), redJunctionsSaid(route), targetSaid(route), loopNote(route), others]",
        "[figures, detourSaid(route, points), redJunctionsSaid(route), loopNote(route), others]",
        SUMMARY + TARGET,
    ),
    (
        "announcement drops the loop note",
        SU,
        "[figures, detourSaid(route, points), redJunctionsSaid(route), targetSaid(route), loopNote(route), others]",
        "[figures, detourSaid(route, points), redJunctionsSaid(route), targetSaid(route), others]",
        SUMMARY + LOOP,
    ),
    (
        "announcement drops the other routes",
        SU,
        "[figures, detourSaid(route, points), redJunctionsSaid(route), targetSaid(route), loopNote(route), others]",
        "[figures, detourSaid(route, points), redJunctionsSaid(route), targetSaid(route), loopNote(route)]",
        SUMMARY + CANDS,
    ),
    (
        "reds counted as oranges",
        SU,
        '.filter((junction) => junction.severity === "red")',
        '.filter((junction) => junction.severity !== "red")',
        SUMMARY,
    ),
    ("one junction plural", SU, '${red === 1 ? "junction" : "junctions"}', "junctions", SUMMARY),
    ("strong said as a warning", SU, 'strong: "Strong warning"', 'strong: "Warning"', SUMMARY),
    (
        "ratio to one decimal always",
        SU,
        "${tier}: ${ratioText(ratio, found.level)} times",
        "${tier}: ${ratio.toFixed(1)} times",
        SUMMARY,
    ),
    (
        "straight line not said",
        SU,
        "  // The straight-line notice: its first sentence says it.\n  return",
        "  return null;\n  return",
        SUMMARY,
    ),
    (
        "calm note one long sentence",
        DPL,
        '(LTS 3) avoided. ` +\n    "Twice that for a heavy-traffic road (LTS 4). Three times',
        '(LTS 3) avoided, ` +\n    "twice that for a heavy-traffic road (LTS 4), and three times',
        DIALS,
    ),
    # --- settling ------------------------------------------------------------
    (
        "keys plan at every press",
        SE,
        "  later(action: () => void): void {\n    this.cancel();\n",
        "  later(action: () => void): void {\n",
        SETTLE,
    ),
    (
        "now keeps the pending one",
        SE,
        "  now(action: () => void): void {\n    this.cancel();\n",
        "  now(action: () => void): void {\n",
        SETTLE,
    ),
    (
        "clearing waits too",
        SE,
        'if (text === "") this.debounce.now(() => this.show(""));',
        'if (text === "") this.debounce.later(() => this.show(""));',
        SETTLE,
    ),
    (
        "keys plan at once",
        DP,
        "if (settle) keys.current.later(commitDraft);",
        "if (settle) keys.current.now(commitDraft);",
        FIXES,
    ),
    (
        "Planning said again",
        APP,
        '      {status.kind === "loading" && <p className="loading">{announcement}</p>}\n      {status.kind === "loading" && <progress className="planning" aria-label="Planning the route" />}\n      <div role="status" aria-live="polite" className="status-line">\n',
        '      {status.kind === "loading" && <progress className="planning" aria-label="Planning the route" />}\n      <div role="status" aria-live="polite" className="status-line">\n      {status.kind === "loading" && <p className="loading">{announcement}</p>}\n',
        FIXES,
    ),
    # --- the release's a11y review (SF1-SF6, N1-N10) and spec NITs -----------
    (
        "still planning said at once",
        APP,
        '{status.kind === "loading" && slow && <p className="loading">{stillPlanningSaid(preset, dials)}</p>}',
        '{status.kind === "loading" && <p className="loading">{stillPlanningSaid(preset, dials)}</p>}',
        FIXES,
    ),
    (
        "still planning after no wait",
        SU,
        "export const STILL_PLANNING_AFTER_MS = 3000;",
        "export const STILL_PLANNING_AFTER_MS = 0;",
        SUMMARY,
    ),
    (
        "still planning blames calm everywhere",
        SU,
        '  const calm = preset !== "mass-ride" && (dials?.stress ?? 0) > STRESS_TODAYS_TOP;',
        "  const calm = true;",
        SUMMARY,
    ),
    (
        "a choice said as planned",
        SU,
        '  const head = how.chosen ? `Route ${how.chosen.rank} of ${how.chosen.of} chosen: ` : "Route planned: ";',
        '  const head = "Route planned: ";',
        SUMMARY + CANDS,
    ),
    (
        "a choice said with the others",
        SU,
        "  const others = !how.chosen && how.others ? othersSaid(how.others) : null;",
        "  const others = how.others ? othersSaid(how.others) : null;",
        SUMMARY + CANDS,
    ),
    (
        "rank with no separator",
        CA,
        '  return rank === 1 && calmest ? "Route 1, the calmest:" : `Route ${rank}:`;',
        '  return rank === 1 && calmest ? "Route 1, the calmest" : `Route ${rank}`;',
        CANDS,
    ),
    (
        "Route 1 always the calmest",
        CA,
        '  return rank === 1 && calmest ? "Route 1, the calmest:" : `Route ${rank}:`;',
        '  return rank === 1 ? "Route 1, the calmest:" : `Route ${rank}:`;',
        CANDS,
    ),
    ("zero junctions said", CA, "  if (stats.red > 0) parts.push(", "  parts.push(", CANDS),
    (
        "zero busy road said",
        CA,
        "  if (stats.lts3M >= SAID_AS_ZERO_M) parts.push(",
        "  parts.push(",
        CANDS,
    ),
    (
        "radios described by the hint",
        CP,
        '          "aria-describedby": row.line ? `${id}-line-${index}` : undefined,',
        '          "aria-describedby": hintId,',
        CANDS,
    ),
    (
        "radios named by their whole label",
        CP,
        '          "aria-labelledby": `${id}-name-${index}`,\n',
        "",
        CANDS,
    ),
    (
        "fieldset not described by the hint",
        CP,
        '{ className: "candidates", "aria-describedby": hintId }',
        '{ className: "candidates" }',
        CANDS,
    ),
    (
        "hint mentions a target never set",
        CA,
        "  const first = target\n",
        "  const first = true\n",
        CANDS,
    ),
    (
        "the target rule loses its kilometres",
        DPL,
        "    rule: `Enter ${milesRange(TARGET_MIN_MILES, TARGET_MAX_MILES, TARGET_MIN_M, TARGET_MAX_M)}, or leave it empty.`,",
        "    rule: `Enter ${TARGET_MIN_MILES} to ${TARGET_MAX_MILES}, or leave it empty.`,",
        TARGET,
    ),
    (
        "the weight rule loses its kilograms",
        DPL,
        "    rule: `Enter ${poundsRange(lo, hi, SYSTEM_WEIGHT_MIN_KG, SYSTEM_WEIGHT_MAX_KG)}, or leave it empty.`,",
        "    rule: `Enter ${lo} to ${hi}, or leave it empty.`,",
        TARGET,
    ),
    (
        "weight to whole kilograms again",
        DPL,
        "  const kg = Math.round((Number(trimmed) / LB_PER_KG) * 10) / 10;",
        "  const kg = Math.round(Number(trimmed) / LB_PER_KG);",
        TARGET,
    ),
    (
        "the link's weight to whole kilograms",
        DI,
        "  const tenth = Math.round(kg * 10) / 10;",
        "  const tenth = Math.round(kg);",
        TARGET,
    ),
    (
        "weight sent in tenths",
        DI,
        "  if (weight !== undefined) fields.system_weight_kg = Math.round(weight);",
        "  if (weight !== undefined) fields.system_weight_kg = weight;",
        TARGET,
    ),
    (
        "target description with the detail again",
        DPL,
        "    hint,\n    how: TARGET_HOW,",
        "    hint: `${hint} ${TARGET_HOW}`,\n    how: TARGET_HOW,",
        TARGET,
    ),
    (
        "calm note with the order again",
        DPL,
        '    return "Calmest: finds the least stressful route towards your target distance, within a set limit. The route summary says how much longer it is.";',
        "    return `Calmest: finds the least stressful route towards your target distance, within a set limit. The route summary says how much longer it is. ${CALM_HOW}`;",
        DIALS,
    ),
    (
        "hills seek note at the top as below",
        DPL,
        "draft.stress >= STRESS_MAX ? SEEK_CALM_NOTE : SEEK_NOTE",
        "SEEK_NOTE",
        DIALS,
    ),
    (
        "no-fit keyed on limited",
        SU,
        "  if (search?.no_fit === true && target) {",
        '  if ((search?.no_fit === true || search?.limited === "target_distance") && target) {',
        TARGET,
    ),
    (
        "no-fit never past the ceiling",
        SU,
        "    const pastCeiling = ceiling !== null && length !== null && length > ceiling;",
        "    const pastCeiling = false;",
        TARGET,
    ),
    (
        "ceiling stop unsaid",
        SU,
        '  } else if (search?.limited === "ceiling") {',
        "  } else if (false) {",
        TARGET + SUMMARY,
    ),
    (
        "old target_distance blamed on busier roads",
        SU,
        '        search?.limited === "target_distance"\n          ? `It is ${formatDistance(over)} over your target.`',
        "        false\n          ? `It is ${formatDistance(over)} over your target.`",
        TARGET,
    ),
    (
        "nested brackets back",
        SU,
        "No route within your target distance of ${formatDistance(target)} was found.",
        "No route within your target distance (${formatDistance(target)}) was found.",
        TARGET,
    ),
    (
        "seek note: calm_first unsaid",
        SU,
        '    case "calm_first":\n',
        '    case "calm_first_never":\n',
        SUMMARY,
    ),
    (
        "the router's own route again",
        SU,
        "in a straight line, so this is the usual route for this ride type.`,",
        "in a straight line, so this is the router's own route.`,",
        SUMMARY,
    ),
    (
        "loop overlap in nested brackets",
        LO,
        "% of the way back, ${formatDistance(loop.shared_m)}, is on roads",
        "% of the way back (${formatDistance(loop.shared_m)}) is on roads",
        LOOP,
    ),
    (
        "lanes switch words for the map with no map",
        SW,
        "overlay ? HIGH_STRESS_LANES_HINT : HIGH_STRESS_LANES_NO_MAP_HINT",
        "HIGH_STRESS_LANES_HINT",
        LANES,
    ),
    (
        "lanes switch says LTS 4 and Avoid",
        SW,
        '"Painted lanes on heavy-traffic (LTS 4) and best-avoided roads are hidden on the map and in the route.',
        '"Painted lanes on LTS 4 and Avoid roads are hidden on the map and in the route.',
        LANES,
    ),
    (
        "lanes-hidden note always",
        RD,
        "  if (showHighStressLanes) return null;\n  const shown",
        "  const shown",
        LANES,
    ),
    (
        "lanes-hidden note never",
        RD,
        "  return shown.some((entry) => withoutHighStressLane(entry) !== entry) ? LANES_HIDDEN_NOTE : null;",
        "  return null;",
        LANES,
    ),
    (
        "federal status inserted with its text",
        FG,
        '    h("p", { className: "hint federal-status", role: "status" }, federalStatusText(on, status)),',
        '    federalStatusText(on, status) && h("p", { className: "hint federal-status", role: "status" }, federalStatusText(on, status)),',
        FEDERAL,
    ),
    (
        "federal points list dropped",
        FG,
        "    h(FederalPointsList, { found: points, count: pointCount, nameOf }),\n",
        "",
        FEDERAL,
    ),
    (
        "federal holes ignored",
        FD,
        " && !rings.slice(1).some((hole) => inRing(point, hole))",
        "",
        FEDERAL,
    ),
    (
        "federal least specific area",
        FD,
        "FEDERAL_KINDS.indexOf(feature.properties.kind) < FEDERAL_KINDS.indexOf(best.properties.kind)",
        "FEDERAL_KINDS.indexOf(feature.properties.kind) > FEDERAL_KINDS.indexOf(best.properties.kind)",
        FEDERAL,
    ),
    (
        "federal help promises again",
        FG,
        '  "manager; the list under the switch names the areas your points are on.";',
        '  "manager; callouts at each stop are coming, above.";',
        FEDERAL,
    ),
    (
        "toggle target 21 px again",
        CSS,
        "  /* A 24 px target (WCAG 2.5.8) without leaning on the spacing exception (the a11y review's N7). */\n  min-height: 24px;\n",
        "",
        FIXES,
    ),
    # --- the skip link -------------------------------------------------------
    ("skip link follows the hash", SK, "  event.preventDefault();\n", "", SKIP),
    ("skip link does not focus", SK, "  planner.focus();\n", "", SKIP),
    # --- the slider ----------------------------------------------------------
    (
        "slider words in its name",
        DP,
        '<span className="dial-now" aria-hidden="true">',
        '<span className="dial-now">',
        FIXES,
    ),
    (
        "note not the description",
        DP,
        "aria-describedby={view.note ? noteId : undefined}",
        "",
        FIXES,
    ),
    # --- the card in MapView ---------------------------------------------------
    ("MapLibre takes the focus", MV, "focusAfterOpen: false,", "focusAfterOpen: true,", FIXES),
    ("card has no role", MV, 'element.setAttribute("role", "dialog");', "", FIXES),
    (
        "marker title back",
        MV,
        '        element.setAttribute("aria-label", single ? first.label : groupLabel(group));\n',
        '        element.setAttribute("aria-label", single ? first.label : groupLabel(group));\n        element.title = single ? first.reason : groupLabel(group);\n',
        FIXES,
    ),
    # --- the rings -----------------------------------------------------------
    ("map ring amber", CSS, "--map-focus: #111827;", "--map-focus: #fbbf24;", FIXES),
    ("no inner ring", CSS, "  box-shadow: 0 0 0 2px var(--map-focus-inner);\n}", "}", FIXES),
    (
        "markers on --focus",
        CSS,
        ".junction-marker:focus-visible,\n.maplibregl-marker:focus-visible,",
        ".maplibregl-marker:focus-visible,",
        FIXES,
    ),
    ("forced single ring", CSS, "    box-shadow: 0 0 0 2px Canvas;\n", "", STYLES),
    (
        "forced Highlight ring",
        CSS,
        "    outline: 3px solid CanvasText;\n    outline-offset: 2px;",
        "    outline: 3px solid Highlight;\n    outline-offset: 2px;",
        STYLES,
    ),
    (
        "forced zoom ring outside",
        CSS,
        "    outline: 3px solid Highlight;\n    outline-offset: -3px;",
        "    outline: 3px solid Highlight;\n    outline-offset: 2px;",
        STYLES,
    ),
    ("rows do not wrap", CSS, "  grid-column: 2 / -1;\n", "", FIXES),
]


def run(files: list[str], cwd: Path) -> bool:
    """Whether every test in `files` passes."""
    result = subprocess.run(
        ["node", "--test", *files], cwd=cwd, capture_output=True, text=True, timeout=300
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("node_modules")
    parser.add_argument("--only")
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="only check that each old text occurs once"
    )
    args = parser.parse_args()
    mutants = [m for m in MUTANTS if args.only is None or m[0] == args.only]
    if args.list:
        for name, *_ in mutants:
            print(name)
        return 0
    if args.check:
        bad = [m[0] for m in mutants if (ROOT / "frontend" / m[1]).read_text().count(m[2]) != 1]
        for name in bad:
            print(f"STALE {name}")
        print(f"{len(mutants) - len(bad)} of {len(mutants)} apply")
        return len(bad)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "frontend"
        shutil.copytree(
            ROOT / "frontend", work, ignore=shutil.ignore_patterns("node_modules", "dist")
        )
        os.symlink(Path(args.node_modules).resolve(), work / "node_modules")
        every = sorted({f for m in mutants for f in m[4]})
        if not run(every, work):
            print("the tests fail before any mutant: fix them first", file=sys.stderr)
            return 100
        survivors = []
        for name, path, old, new, files in mutants:
            target = work / path
            text = target.read_text()
            count = text.count(old)
            if count != 1:
                print(f"STALE {name}: the old text occurs {count} times in {path}")
                survivors.append(f"{name} (stale)")
                continue
            target.write_text(text.replace(old, new))
            try:
                killed = not run(files, work)
            finally:
                target.write_text(text)
            print(f"{'killed  ' if killed else 'SURVIVED'} {name}")
            if not killed:
                survivors.append(name)
        print(f"\n{len(mutants) - len(survivors)}/{len(mutants)} killed")
        for name in survivors:
            print(f"  survivor: {name}")
        return len(survivors)


if __name__ == "__main__":
    sys.exit(main())
