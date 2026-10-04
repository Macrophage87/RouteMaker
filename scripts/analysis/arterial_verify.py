#!/usr/bin/env python3
# ruff: noqa: E501 - report prose and table rows run long
"""Run the rebuild's own steps over the live extract, read only, and report what the
named corridors, the AADT smoothing and the override re-match do (OWNER-DECISIONS 282-286,
294-296).

    DJANGO_SETTINGS_MODULE=config.test_settings PGDATABASE=<a private database with PostGIS> \\
    python scripts/analysis/arterial_verify.py --pbf <DATA_ROOT>/extracts/source.osm.pbf \\
        --merged <DATA_ROOT>/extracts/merged.osm.pbf --reference <DATA_ROOT>/reference \\
        --out DIR [--live-rows-ref origin/main]

Nothing is written to the live database or to the data root: the extract and the reference
data are read, the only database use is the temporary table `states.way_states` makes in
the private database named by PGDATABASE, and the report goes to `--out`.

It reads the ways as the rebuild does, loads the reference data, conflates the counts and
classifies three times: as the code did before (no smoothing, no corridors), with smoothing,
and with smoothing and the corridors. It writes `smoothing.md` (km changed by region and
tier, the top streets), `north-capitol.md` (every way of the corridor against the owner's
targets), and `rematch.md` / `rematch.csv`: every override row the live database holds
(the fixtures as of `--live-rows-ref`, with the fingerprints of the working tree) run
through `pipeline.rematch.resolve` against this extract, then the working tree's rows
through the real APPLY_OVERRIDES stage.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

MI = 1609.344
TIER = {1: "LTS 1", 2: "LTS 2", 3: "LTS 3", 4: "LTS 4", 5: "Avoid"}

# The owner's targets for North Capitol (OWNER-DECISIONS 286, 295), as the ways the
# 2026-10-03 extract has, from ARTERIAL-CAL-r0 section 5.4 with its two fixes: way
# 468472149 is a side lane (4), and the first cluster's Avoid stops about 100 m short
# of where the study had it (the seven trimmed ways keep their rating, LTS 3). Way
# 930215092 is tagged lanes=2 but is the eastern outer side lane, 11 m off the
# axis, like 468472149; the study listed it as Avoid.
FIRST_THROUGH = [
    130772891, 920784194, 296374855, 50753931, 296374852, 516193840,
    516193841, 516193839, 130772888, 695842754,
]  # fmt: skip
FIRST_TRIMMED = [
    1306065346, 1355134125, 516193842, 1306065345, 1355134128, 1320069049, 397300798,
]  # fmt: skip
FIRST_SIDES = [
    397303406, 50228155, 918453671, 1280512687, 918340140, 468472150, 503077369,
    1112231796, 468472149, 362659445, 50228568, 930215092,
]  # fmt: skip
SECOND_THROUGH = [
    507273044, 130772889, 122080103, 122080102, 122080106, 122080105, 122080104,
    122079298, 122080107, 122079297, 122079299, 130772880, 122079300,
]  # fmt: skip
SECOND_SIDES = [1501632583, 50753962, 1501632581, 50753965, 422355425]
TARGETS = (
    {way: 5 for way in FIRST_THROUGH}
    | {way: 4 for way in FIRST_SIDES}
    | {way: 4 for way in SECOND_THROUGH}
    | {way: 3 for way in SECOND_SIDES}
)
FIRST_ST_NW_WAY = 483241819


def length_m(coords) -> float:
    from pipeline import conflation

    return conflation._length_m(coords)


def tiers_of(context) -> dict[int, tuple[int, str]]:
    return {way: (int(r.tier), r.rule) for way, r in context.stress_by_way.items()}


def region(way, state: str | None) -> str:
    lon, lat = way.coordinates[len(way.coordinates) // 2]
    if state == "MD" and lat >= 39.17 and lon >= -76.9:
        return "Baltimore"
    return {"DC": "DC", "VA": "Virginia", "MD": "Maryland"}.get(state or "", "other")


def changes(before, after, ways_by_id, states) -> tuple[dict, dict]:
    """km changed by (region, from, to), and by street."""
    by_tier: dict = defaultdict(float)
    by_street: dict = defaultdict(float)
    for way_id, (tier, _) in before.items():
        new = after.get(way_id, (tier, ""))[0]
        if new == tier:
            continue
        way = ways_by_id[way_id]
        km = length_m(way.coordinates) / 1000
        by_tier[(region(way, states.get(way_id)), tier, new)] += km
        by_street[(way.tags.get("name") or "(unnamed)", region(way, states.get(way_id)))] += km
    return by_tier, by_street


def table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def tier_rows(by_tier) -> list:
    return [
        (reg, TIER[a], TIER[b], f"{km:.2f}", f"{km * 1000 / MI:.2f}")
        for (reg, a, b), km in sorted(by_tier.items())
    ]


def live_rows(ref: str, fingerprints):
    """The override rows the live database holds: the fixtures as of `ref`."""
    from pipeline.overrides import Override

    names = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "--name-only", ref, "fixtures/overrides/"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    rows = []
    for name in names:
        if not name.endswith(".json") or "/2026-" not in name:
            continue
        text = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{ref}:{name}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for row in json.loads(text).get("rows", []):
            rows.append(
                Override(
                    kind=row["kind"],
                    osm_way_id=row["osm_way_id"],
                    value=row["value"],
                    reason=row["reason"],
                    fingerprint=fingerprints.get((row["kind"], row["osm_way_id"])),
                )
            )
    return rows


def tree_rows(fingerprints):
    from pipeline.overrides import Override

    rows = []
    for path in sorted((REPO / "fixtures" / "overrides").glob("2026-*.json")):
        for row in json.loads(path.read_text()).get("rows", []):
            rows.append(
                Override(
                    kind=row["kind"],
                    osm_way_id=row["osm_way_id"],
                    value=row["value"],
                    reason=row["reason"],
                    fingerprint=fingerprints.get((row["kind"], row["osm_way_id"])),
                )
            )
    return rows


def read_override_neighbourhood(pbf: str, rows, fingerprints) -> list:
    """The ways the override check needs that the road-only read left out: every way an
    override row names, and every way that lies near an override's fingerprint (where
    its re-match would look), read with a streaming location index, so memory stays
    small. Footways, paths and driveways are among them (232 access rows)."""
    import osmium

    from pipeline import rematch
    from pipeline.extract import Way

    ids = {row.osm_way_id for row in rows}
    cells = set()
    for fp in fingerprints.values():
        pts = rematch.parse_line(fp["line"])
        box = (
            min(p[0] for p in pts),
            min(p[1] for p in pts),
            max(p[0] for p in pts),
            max(p[1] for p in pts),
        )
        cells.update(rematch._cells(box, 20 / 111_000.0))
    processor = (
        osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    found = []
    for way in processor:
        coords = [(n.lon, n.lat) for n in way.nodes if n.location.valid()]
        if len(coords) < 2:
            continue
        near = way.id in ids or any(
            cell in cells for cell in rematch._cells(rematch._bbox(coords), 0.0)
        )
        if near:
            found.append(
                Way(
                    osm_id=way.id,
                    tags={t.k: t.v for t in way.tags},
                    node_ids=[],
                    coordinates=coords,
                )
            )
    return found


def run_overrides(context, handlers, rows_now, fingerprints, args, out) -> dict:
    """The override re-match: the live database's rows against this extract, then the
    working tree's rows through the real APPLY_OVERRIDES stage."""
    from collections import Counter

    from pipeline import rematch
    from pipeline.rebuild import Stage

    live = live_rows(args.live_rows_ref, fingerprints)
    extra = read_override_neighbourhood(args.pbf, [*live, *rows_now], fingerprints)
    for way in extra:
        if way.osm_id not in context.ways_by_id:
            context.ways.append(way)
            context.ways_by_id[way.osm_id] = way
    logging.info("override neighbourhood: %d more ways", len(extra))
    _, live_report = rematch.resolve(live, context.ways_by_id, fingerprints)
    (out / "rematch-live.md").write_text(live_report.to_markdown())
    (out / "rematch-live.csv").write_text(live_report.to_csv())
    kinds = Counter(row.kind for row in live)
    handlers[Stage.APPLY_OVERRIDES]()
    applied = context.override_report
    (out / "rematch-tree.md").write_text(applied.rematch_report.to_markdown())
    return {
        "live_rows": dict(kinds),
        "live_rematch": live_report.summary(),
        "tree_override_summary": applied.summary(),
        "harford": {
            way_id: [int(context.stress_by_way[way_id].tier), context.stress_by_way[way_id].rule]
            for way_id in (1562097553, 1562097555, 1562097556)
            if way_id in context.stress_by_way
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pbf", required=True)
    parser.add_argument("--merged")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--overrides-only",
        action="store_true",
        help="skip the classification: only the override re-match, on stub tiers",
    )
    parser.add_argument("--live-rows-ref", default="origin/main")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import django

    django.setup()
    from pipeline import extract, rematch, states
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, build_handlers
    from routemaker import corridors

    context = RebuildContext(
        source_pbf=Path(args.pbf),
        work_dir=out / "work",
        reference_dir=Path(args.reference),
        tiles_dir=out / "tiles",
        staging_schema="staging",
        elevation_dir=out / "elevation",
        config_dir=out / "config",
        coverage_bbox=(-78.0, 38.2, -76.02, 39.72),
        coverage_polygon=None,
        upstreams={},
        build_id="verify",
    )
    context.merged_pbf = Path(args.merged) if args.merged else None
    started = time.monotonic()
    # Roads only: the trails, steps and driveways cannot change what the corridors, the
    # smoothing or a road override do, and leaving them out halves the memory.
    roads = {
        "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
        "living_street", "road", "motorway_link", "trunk_link", "primary_link",
        "secondary_link", "tertiary_link",
    }  # fmt: skip
    context.ways = extract.read_ways(context.source_pbf, keep=lambda t: t.get("highway") in roads)
    context.ways_by_id = {way.osm_id: way for way in context.ways}
    logging.info("read %d road ways in %.0f s", len(context.ways), time.monotonic() - started)

    fingerprints = rematch.load_fingerprints()
    rows_now = tree_rows(fingerprints)
    handlers = build_handlers(context, load_overrides=lambda: rows_now)
    handlers[Stage.LOAD_REFERENCE_DATA]()
    if args.overrides_only:
        from routemaker.stress import Stress, StressResult

        context.stress_by_way = {w.osm_id: StressResult(Stress.LTS3, "stub") for w in context.ways}
        part = run_overrides(context, handlers, rows_now, fingerprints, args, out)
        (out / "overrides-summary.json").write_text(json.dumps(part, indent=2, default=str) + "\n")
        print(json.dumps(part, indent=2, default=str))
        return 0
    handlers[Stage.CONFLATE_VOLUME]()

    polygons = states.state_polygons(context.merged_pbf or context.source_pbf)
    way_state = states.way_states(context.ways, polygons)

    # 1. As the code classified before: no smoothing, no corridors.
    real_load = corridors.load
    corridors.load = lambda directory=None: []
    context.smooth_volume = False
    handlers[Stage.CLASSIFY_STRESS]()
    before = tiers_of(context)
    # 2. With smoothing and the corridors, as the stage runs them.
    corridors.load = real_load
    context.smooth_volume = True
    handlers[Stage.CLASSIFY_STRESS]()
    final = tiers_of(context)
    report = context.smoothing_report
    corridor_report = context.corridor_report
    logging.info("%s", corridor_report.summary())
    # With smoothing alone: the final tiers with each corridor-set way put back to
    # the tier it had when the corridor reached it.
    smoothed = dict(final)
    for hit in corridor_report.applied:
        smoothed[hit.way_id] = (hit.before, smoothed[hit.way_id][1])

    # --- Smoothing -------------------------------------------------------------
    by_tier, by_street = changes(before, smoothed, context.ways_by_id, way_state)
    totals: dict = defaultdict(float)
    for (reg, _a, _b), km in by_tier.items():
        totals[reg] += km
    first_before, first_after = before[FIRST_ST_NW_WAY], smoothed[FIRST_ST_NW_WAY]
    raw = context.aadt_raw_by_way.get(FIRST_ST_NW_WAY)
    smooth = context.aadt_by_way.get(FIRST_ST_NW_WAY)
    lines = [
        "# AADT smoothing: region-wide effect (read only, the 2026-10-03 extract)",
        "",
        f"{len(report.replaced)} of {report.counted_ways} counted ways had their count replaced by the "
        f"street's length-weighted median (400 m, same street, same state, at least 3 ways and 250 m). "
        f"{sum(totals.values()):.1f} km ({sum(totals.values()) * 1000 / MI:.1f} mi) of road changes tier: "
        + ", ".join(f"{r} {km:.1f} km" for r, km in sorted(totals.items()))
        + ".",
        "",
        "## 1st Street NW, way 483241819",
        "",
        f"AADT {raw.aadt if raw else None} raw, {smooth.aadt if smooth else None} smoothed; "
        f"tier {first_before[0]} ({first_before[1]}) before, {first_after[0]} ({first_after[1]}) after.",
        "",
        "## km changed by region and tier",
        "",
        table(["Region", "From", "To", "km", "mi"], tier_rows(by_tier)),
        "",
        "## Top 25 streets by km changed",
        "",
        table(
            ["Street", "Region", "km", "mi"],
            [
                (name, reg, f"{km:.2f}", f"{km * 1000 / MI:.2f}")
                for (name, reg), km in sorted(by_street.items(), key=lambda kv: -kv[1])[:25]
            ],
        ),
        "",
    ]
    (out / "smoothing.md").write_text("\n".join(lines))
    (out / "smoothing-ways.csv").write_text(
        "way,street,raw,smoothed,ways_in_window,window_m,tier_before,tier_after\n"
        + "\n".join(
            f"{s.way_id},{s.street},{s.raw},{s.smoothed},{s.ways},{s.length_m:.0f},"
            f"{before.get(s.way_id, ('', ''))[0]},{smoothed.get(s.way_id, ('', ''))[0]}"
            for s in report.replaced
        )
        + "\n"
    )

    # --- North Capitol ---------------------------------------------------------
    corridor_by_way = {a.way_id: a for a in corridor_report.applied}
    rows = []
    wrong = []
    for way_id in sorted(
        {*TARGETS, *FIRST_TRIMMED, *corridor_by_way},
        key=lambda w: context.ways_by_id[w].coordinates[0][1],
    ):
        way = context.ways_by_id.get(way_id)
        if way is None:
            wrong.append((way_id, "missing from the extract"))
            continue
        expected = TARGETS.get(way_id, smoothed[way_id][0])
        got = final[way_id][0]
        if got != expected:
            wrong.append((way_id, f"expected {expected}, got {got}"))
        rows.append(
            (
                way_id,
                f"{way.coordinates[0][1]:.5f}",
                way.tags.get("lanes", ""),
                int(length_m(way.coordinates)),
                smoothed[way_id][0],
                got,
                expected,
                "ok" if got == expected else "MISMATCH",
            )
        )
    lines = [
        "# North Capitol Street: named corridor against the owner's targets (OWNER-DECISIONS 286, 295)",
        "",
        corridor_report.summary() + ".",
        f"Mismatches: {len(wrong)}" + (f" {wrong}" if wrong else "") + ".",
        "",
        table(["Way", "Lat", "OSM lanes", "m", "Before corridor", "After", "Target", ""], rows),
        "",
    ]
    (out / "north-capitol.md").write_text("\n".join(lines))
    tier_counts = Counter(
        final[way][0]
        for way, hit in corridor_by_way.items()
        if hit.corridor == "north-capitol-st" and not hit.exempt
    )

    # --- Re-match ---
    rematch_part = run_overrides(context, handlers, rows_now, fingerprints, args, out)
    summary = {
        **rematch_part,
        "north_capitol_mismatches": wrong,
        "north_capitol_tiers": dict(tier_counts),
        "first_st_nw": {
            "before": first_before,
            "after": first_after,
            "raw": raw.aadt if raw else None,
            "smoothed": smooth.aadt if smooth else None,
        },
        "smoothing_replaced": len(report.replaced),
        "smoothing_km_by_region": dict(totals),
        "corridor": corridor_report.summary(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
