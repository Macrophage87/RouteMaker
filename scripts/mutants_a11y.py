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
    (
        "announcement drops the reds",
        SU,
        "[figures, detourSaid(route, points), redJunctionsSaid(route)]",
        "[figures, detourSaid(route, points)]",
        SUMMARY,
    ),
    (
        "announcement drops the detour",
        SU,
        "[figures, detourSaid(route, points), redJunctionsSaid(route)]",
        "[figures, redJunctionsSaid(route)]",
        SUMMARY,
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
        '      {status.kind === "loading" && <p className="loading">{announcement}</p>}\n      <div role="status" aria-live="polite" className="status-line">\n',
        '      <div role="status" aria-live="polite" className="status-line">\n      {status.kind === "loading" && <p className="loading">{announcement}</p>}\n',
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
    args = parser.parse_args()
    mutants = [m for m in MUTANTS if args.only is None or m[0] == args.only]
    if args.list:
        for name, *_ in mutants:
            print(name)
        return 0
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
