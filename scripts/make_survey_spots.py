#!/usr/bin/env python3
"""Write the survey spot list from a re-rate's outputs (src/routemaker/survey.py).

A spot is one named road in one county whose low-confidence pieces the raters were unsure of by a
level or more, where the unsure range reaches 3 or calmer (a level routes use; a road busy at every
reading in its range is avoided either way). Groups of small streets and unnamed links are left
out: surveying them would not change routes. Florida is not in the re-rate, so not in the list.

Reads only the re-rate's files (final.json.gz, sonnet.json.gz, opus.json.gz, roads.json.gz,
rerate-by-way.csv.gz); writes fixtures/survey/spots.json. No ride data is read. A spot's point on
the map is worked out by the server from the map's own way geometry, so the list holds way ids,
not coordinates.

    python3 scripts/make_survey_spots.py --rerate <re-rate dir> [--out <spots.json>]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routemaker.survey import pick_questions  # noqa: E402

LOW = {"low", "l"}


def _num(x: object) -> float | None:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def build(rerate: Path) -> list[dict]:
    def load(name: str):
        with gzip.open(rerate / name, "rt") as fh:
            return json.load(fh)

    final = load("final.json.gz")
    first = load("sonnet.json.gz")
    roads = load("roads.json.gz")
    seg: dict[str, tuple[dict, dict]] = {}
    for r in roads:
        for s in r["segments"]:
            seg[s["id"]] = (r, s)
    ways: dict[str, list[tuple[int, float]]] = defaultdict(list)
    with gzip.open(rerate / "rerate-by-way.csv.gz", "rt") as fh:
        for row in csv.DictReader(fh):
            ways[row["segment"]].append((int(row["osm_way"]), float(row["miles"])))

    groups: dict[tuple[str, str, str], dict] = {}
    for sid, v in final.items():
        if v.get("confidence") not in LOW or sid not in seg:
            continue
        r, s = seg[sid]
        if not r.get("name"):
            continue
        g = groups.setdefault(
            (r["state"], r["county"], r["name"]),
            {
                "lo": 9.0,
                "hi": 0.0,
                "levels": [],
                "ways": [],
                "missing": [],
                "fac": set(),
                "why": (0.0, ""),
                "miles": 0.0,
            },
        )
        rng = v.get("range") or [v.get("level"), v.get("level")]
        lo, hi = _num(rng[0]), _num(rng[-1])
        if lo is not None and hi is not None:
            g["lo"], g["hi"] = min(g["lo"], lo), max(g["hi"], hi)
        if _num(v.get("level")) is not None:
            g["levels"].append(float(v["level"]))
        g["ways"] += ways[sid]
        g["missing"] += first.get(sid, {}).get("missing", [])
        g["fac"].add(s.get("bike_facility") or "")
        g["miles"] += s["miles"]
        if s["miles"] > g["why"][0]:
            g["why"] = (s["miles"], v.get("why", ""))

    spots = []
    for (state, county, name), g in groups.items():
        if not g["ways"] or not g["levels"] or g["lo"] > 3 or g["hi"] - g["lo"] < 1:
            continue
        longest = max(g["ways"], key=lambda w: w[1])[0]
        spots.append(
            {
                "id": f"s{longest}",
                "road": name,
                "state": state,
                "county": county,
                "miles": round(g["miles"], 2),
                "level": [min(g["levels"]), max(g["levels"])],
                "range": [g["lo"], g["hi"]],
                "why": g["why"][1],
                "questions": pick_questions(g["missing"], g["fac"], g["why"][1]),
                "point_way": longest,
                "ways": sorted({w for w, _ in g["ways"]}),
            }
        )
    spots.sort(key=lambda s: (-s["miles"], s["id"]))
    return spots


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rerate", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("fixtures/survey/spots.json"))
    a = ap.parse_args(argv)
    spots = build(a.rerate)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "about": (
            "Survey spots (src/routemaker/survey.py, scripts/make_survey_spots.py): named roads"
            " whose re-rate was a low-confidence call by a level or more, reaching 3 or calmer."
            " Generated; do not edit."
        ),
        "source": a.rerate.name,
        "spots": spots,
    }
    a.out.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    by_state: dict[str, int] = defaultdict(int)
    for s in spots:
        by_state[s["state"]] += 1
    print(f"{len(spots)} spots", dict(sorted(by_state.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
