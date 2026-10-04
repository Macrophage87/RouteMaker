#!/usr/bin/env python3
"""Mutants on the federal-land overlay and its build step.

FOLLOWUP-FEDERAL-LAYER (owner items 236-239), the map part. A mutation pass run
against WHOLE test files, as `scripts/mutants_trailseek.py` does: a mutant is
killed when the tests named for it fail. It works on a copy of the repository
under $TMPDIR and removes it at the end:

    scripts/mutants_federal.py [--only NAME] [--list] [--check]
        --python PYTHON      the interpreter with pytest and shapely (the project's .venv311)
        --node-modules DIR   a frontend node_modules installed from the lockfile
        --node-image IMAGE   the node image (by digest); Docker runs the front end's tests offline

Each line of MUTANTS is (name, file, old text, new text, runner); `old` must
occur exactly once (--check verifies that). Survivors are printed last and the
exit status is the number of them.
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

FL = "frontend/src/lib/federalLand.ts"
LG = "frontend/src/lib/federalLegend.ts"
APP = "frontend/src/App.tsx"
VIEW = "frontend/src/MapView.tsx"
MS = "frontend/src/lib/mapStyle.ts"
PY = "scripts/build_federal_land.py"

# (name, file, old, new, runner): runner "ts" runs the front end test file, "py" the build step's.
MUTANTS: list[tuple[str, str, str, str, str]] = [
    # --- where it shows -------------------------------------------------
    ("shown: any ride type", FL, 'return preset === "mass-ride" && on;', "return on;", "ts"),
    (
        "shown: ignores the rider's switch",
        FL,
        'return preset === "mass-ride" && on;',
        'return preset === "mass-ride";',
        "ts",
    ),
    (
        "App: section for every ride type",
        APP,
        'preset === "mass-ride" && (\n            <FederalLandSection',
        "true && (\n            <FederalLandSection",
        "ts",
    ),
    (
        "App: map ignores the ride type",
        APP,
        "federalVisible={federalShown(preset, federalOn)}",
        "federalVisible={federalOn}",
        "ts",
    ),
    (
        "map: fetches while off",
        VIEW,
        "if (!visible || federalLoading) return;",
        "if (federalLoading) return;",
        "ts",
    ),
    # --- colour plus a cue ----------------------------------------------
    ("style: two kinds one colour", FL, 'colour: "#8b6f47"', 'colour: "#b45309"', "ts"),
    (
        "style: two kinds one pattern",
        FL,
        "ink: (x, y) => mod(x + y, 4) === 0,\n  },\n  reservation",
        "ink: (x, y) => mod(x - y, 4) === 0,\n  },\n  reservation",
        "ts",
    ),
    ("style: two kinds one dash", FL, "dash: [5, 2],", "dash: [3, 2],", "ts"),
    ("style: pattern solid", FL, "ink: (_x, y) => mod(y, 4) === 0,", "ink: () => true,", "ts"),
    ("layer: tint heavy", FL, '"fill-opacity": 0.1 }', '"fill-opacity": 0.9 }', "ts"),
    ("layer: pattern opaque", FL, '"fill-opacity": 0.45 }', '"fill-opacity": 1 }', "ts"),
    (
        "layer: outlines all solid",
        FL,
        '...(FEDERAL_STYLE[kind].dash.length > 0 ? { "line-dasharray": [...FEDERAL_STYLE[kind].dash] } : {}),',
        "",
        "ts",
    ),
    (
        "legend: cue not in words",
        LG,
        "`: ${FEDERAL_STYLE[kind].describe}, shaded with ${FEDERAL_STYLE[kind].cue}`",
        "`: ${FEDERAL_STYLE[kind].describe}`",
        "ts",
    ),
    (
        "legend: a kind with no data listed",
        LG,
        'FEDERAL_KINDS.filter((kind) => kind !== "federal")',
        "FEDERAL_KINDS",
        "ts",
    ),
    (
        "legend: shown while off",
        LG,
        '    on && status !== "unavailable" && h(FederalLegend),',
        '    status !== "unavailable" && h(FederalLegend),',
        "ts",
    ),
    (
        "legend: shown while unavailable",
        LG,
        '    on && status !== "unavailable" && h(FederalLegend),',
        "    on && h(FederalLegend),",
        "ts",
    ),
    # --- the data and the map -------------------------------------------
    ("parse: unknown kinds kept", FL, "!isKind(props.kind) || ", "", "ts"),
    ("load: a failed fetch parsed anyway", FL, "if (!response.ok) return null;\n", "", "ts"),
    ("add: added twice", FL, "  if (map.getSource(FEDERAL_SOURCE_ID)) return false;\n", "", "ts"),
    (
        "add: over the stress lines",
        FL,
        '(layers.find((l) => l.source === stressSourceId) ?? layers.find((l) => l.type === "symbol"))?.id',
        '(layers.find((l) => l.type === "symbol") ?? layers.find((l) => l.source === stressSourceId))?.id',
        "ts",
    ),
    (
        "add: always visible",
        FL,
        'const visibility = visible ? "visible" : "none";',
        'const visibility = "visible";',
        "ts",
    ),
    (
        "visibility: inverted",
        FL,
        'map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");',
        'map.setLayoutProperty(id, "visibility", visible ? "none" : "visible");',
        "ts",
    ),
    # --- the popup and the credit ---------------------------------------
    ("popup: note dropped", FL, "note: FEDERAL_NOTE }", 'note: "" }', "ts"),
    (
        "popup: note says the opposite",
        FL,
        "permit rules may differ (information",
        "permit rules are the same (information",
        "ts",
    ),
    ("popup: agency dropped", FL, "agency: props.agency ?? null", "agency: null", "ts"),
    (
        "credit: left off the map",
        "frontend/src/lib/credits.json",
        '</a>, adapted)"\n  },',
        '</a>)"\n  },',
        "ts",
    ),
    # --- the build step -------------------------------------------------
    (
        "build: nps over military",
        PY,
        'KINDS = ("capitol", "military", "nps", "reservation", "federal")',
        'KINDS = ("capitol", "nps", "military", "reservation", "federal")',
        "py",
    ),
    (
        "build: no clipping",
        PY,
        "                if touching:\n",
        "                if False:\n",
        "py",
    ),
    (
        "build: retired lots kept",
        PY,
        'if p.get("KILL_DT") or p.get("ISHISTORIC"):',
        "if False:",
        "py",
    ),
    (
        "build: GSA kept",
        PY,
        "            if GSA_OWNER.search(owner):",
        "            if False:",
        "py",
    ),
    ("build: slivers kept", PY, "MIN_AREA_M2 = 60.0", "MIN_AREA_M2 = 0.0", "py"),
    ("build: not simplified", PY, "SIMPLIFY_DEGREES = 0.00003", "SIMPLIFY_DEGREES = 0.0", "py"),
    (
        "build: generic names not numbered",
        PY,
        "if reserve and (base.lower() in NPS_GENERIC or",
        "if False and (base.lower() in NPS_GENERIC or",
        "py",
    ),
    (
        "build: unstated source claims the NPS",
        PY,
        'agency = NPS_AGENCY if _text(props.get("SOURCE")) == "NPS" else NPS_UNSTATED',
        "agency = NPS_AGENCY",
        "py",
    ),
    (
        "build: capitol agency wrong",
        PY,
        'CAPITOL_AGENCY = "Architect of the Capitol"',
        'CAPITOL_AGENCY = "National Park Service"',
        "py",
    ),
    (
        "build: kind not written",
        PY,
        'properties = {"kind": kind, "name": props["name"]}',
        'properties = {"kind": "nps", "name": props["name"]}',
        "py",
    ),
    (
        "build: military names an agency",
        PY,
        '        out["military"].append((shape(f["geometry"]), {"name": name}))',
        '        out["military"].append((shape(f["geometry"]), {"name": name, "agency": "Department of Defense"}))',
        "py",
    ),
]

TS_TEST = "src/lib/federalLand.test.ts"
PY_TEST = "tests/test_build_federal_land.py"


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


def run_tests(runner: str, work: Path, args: argparse.Namespace) -> bool:
    """True when the tests pass."""
    if runner == "py":
        cmd = [args.python, "-m", "pytest", PY_TEST, "-x", "-q", "-p", "no:cacheprovider"]
        return subprocess.run(cmd, cwd=work, capture_output=True, timeout=300).returncode == 0
    cmd = [
        "docker", "run", "--rm", "--network", "none", "--memory", "2500m", "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
        "-v", f"{work}:/w", "-v", f"{args.node_modules}:/w/frontend/node_modules:ro", "-w", "/w/frontend",
        args.node_image, "node", "--test", TS_TEST,
    ]  # fmt: skip
    return subprocess.run(cmd, capture_output=True, timeout=300).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--node-image", default="")
    args = parser.parse_args()
    chosen = [m for m in MUTANTS if not args.only or args.only in m[0]]
    if args.list:
        for name, file, _, _, runner in chosen:
            print(f"{runner}  {name}  ({file})")
        return 0
    for name, file, old, _, _ in chosen:
        count = (ROOT / file).read_text(encoding="utf-8").count(old)
        if count != 1:
            print(f"BAD   {name}: old text occurs {count} times in {file}", file=sys.stderr)
            return 99
    if args.check:
        print(f"{len(chosen)} mutants, each with its old text exactly once")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="mutants-federal-"))
    survivors: list[str] = []
    try:
        work = tmp / "repo"
        copy_tree(work)
        for runner in sorted({m[4] for m in chosen}):
            if not run_tests(runner, work, args):
                print(f"the unmutated {runner} tests fail; nothing to compare", file=sys.stderr)
                return 98
        for name, file, old, new, runner in chosen:
            path = work / file
            original = path.read_text(encoding="utf-8")
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            try:
                passed = run_tests(runner, work, args)
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
    return len(survivors)


if __name__ == "__main__":
    sys.exit(main())
