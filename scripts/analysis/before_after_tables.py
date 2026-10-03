#!/usr/bin/env python3
# ruff: noqa: E501 - table rows run long
"""The before/after tier tables with DC's Roadway Block and Baltimore's centerline conflated.

    python scripts/analysis/before_after_tables.py --dcbal out/dcbal.tsv \\
        --region-baseline new4.tsv --out out/before-after.md

`dcbal.tsv` is `data_before_after.py`'s output (DC and Baltimore ways, tier with and without the
layers). `new4.tsv` is the region-wide classification of the same extract at the head the
conflation branches from (id, tier, rule, urban, metres, state, highway, name, lon, lat), which
supplies every way outside DC and Baltimore, unchanged by this work.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from routemaker.tags import (  # noqa: E402
    cycleway_values,
    has_parking_lane,
    is_oneway,
    lanes_per_direction,
    parse_maxspeed_mph,
)

MI = 1609.344
TIERS = [1, 2, 3, 4, 5]

DC_EXAMPLES = {
    "4th Street Northeast": r"^4th Street Northeast$",
    "6th Street Northeast": r"^6th Street Northeast$",
    "22nd Street Northwest": r"^22nd Street Northwest$",
    "Connecticut Avenue Northwest": r"^Connecticut Avenue Northwest$",
    "16th Street Northwest": r"^16th Street Northwest$",
    "K Street Northwest": r"^K Street Northwest$",
    "Minnesota Avenue Southeast": r"^Minnesota Avenue (Southeast|Northeast)$",
    "MacArthur Boulevard Northwest": r"^MacArthur Boulevard Northwest$",
    "Kenilworth Avenue Northeast": r"^Kenilworth Avenue Northeast$",
}
BALTIMORE_EXAMPLES = {
    "Charles Street": r"^(North |South )?Charles Street$",
    "St Paul Street": r"^(North |South )?Saint Paul Street$|^(North |South )?St\.? Paul Street$",
    "North Avenue": r"^(East |West )?North Avenue$",
    "Maryland Avenue": r"^(North |South )?Maryland Avenue$",
    "Fort Avenue": r"^(East |West )?Fort Avenue$",
    "Key Highway": r"^(East |West )?Key Highway$",
    "Pratt Street": r"^(East |West )?Pratt Street$",
    "Eastern Avenue": r"^(East |West )?Eastern Avenue$",
    "Falls Road": r"^(North |South )?Falls Road$",
    "Roland Avenue": r"^Roland Avenue$",
    "Greenmount Avenue": r"^(North |South )?Greenmount Avenue$",
    "Boston Street": r"^(East |West )?Boston Street$",
    "Guilford Avenue": r"^(North |South )?Guilford Avenue$",
    "Druid Park Lake Drive": r"^Druid Park (Lake )?Drive$",
}
ARBORETUM_BOX = (-76.985, 38.900, -76.955, 38.925)


def pct(a: float, b: float) -> str:
    return f"{100 * a / b:4.1f}%" if b else "-"


def tier_table(label_rows: list[tuple[str, dict[int, float], dict[int, float]]]) -> str:
    out = [
        "| area | total mi | " + " | ".join(f"LTS {t} before -> after" for t in TIERS) + " |",
        "|" + "|".join(" --- " for _ in range(2 + len(TIERS))) + "|",
    ]
    for label, before, after in label_rows:
        total = sum(before.values())
        cells = [
            f"{before.get(t, 0):,.1f} ({pct(before.get(t, 0), total)}) -> {after.get(t, 0):,.1f} ({pct(after.get(t, 0), total)}), {after.get(t, 0) - before.get(t, 0):+,.1f}"
            for t in TIERS
        ]
        out.append(f"| {label} | {total:,.0f} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def tag_view(raw: str) -> dict[str, str]:
    return json.loads(raw) if raw else {}


def causes(row) -> list[str]:
    """What the agency layer changed about this way, from its tags before and after."""
    before, after = tag_view(row["tags"]), tag_view(row["tags1"])
    out = []
    # Speed as the classifier reads it: the posted value, or "assumed".
    b_speed, a_speed = (
        parse_maxspeed_mph(before.get("maxspeed")),
        parse_maxspeed_mph(after.get("maxspeed")),
    )
    if b_speed != a_speed:
        out.append("speed")
    b_lanes, a_lanes = lanes_per_direction(before), lanes_per_direction(after)
    if (b_lanes or 1) != (a_lanes or 1):
        out.append("lanes")
    if is_oneway(before) != is_oneway(after):
        out.append("one-way")
    if sorted(cycleway_values(before)) != sorted(cycleway_values(after)):
        out.append("bike facility")
    elif {k: v for k, v in before.items() if k.startswith("cycleway") and k.endswith("width")} != {
        k: v for k, v in after.items() if k.startswith("cycleway") and k.endswith("width")
    }:
        out.append("bike-lane width")
    if has_parking_lane(before) != has_parking_lane(after):
        out.append("parking")
    if row["aadt0"] != row["aadt1"]:
        out.append("count")
    return out or ["none (tags the same)"]


def baltimore_not_used(dcbal) -> list[str]:
    """OWNER-DECISIONS 222 ("differences go into a report"): where Baltimore's
    centerline records a one-way or a lane count that differs from OSM's and is
    not used, by kind, with the longest ways."""
    marker = "not used (OWNER-DECISIONS 222)"
    kinds: dict[str, list[dict]] = defaultdict(list)
    for r in dcbal:
        if r["region"] != "baltimore":
            continue
        for part in r["disagree"].split("; "):
            if part.startswith(("oneway:", "lanes:")) and f"{part}; {marker}" in r["disagree"]:
                # The lane counts differ way by way; the one-way's kind is the text.
                kinds[
                    part if part.startswith("oneway:") else "lanes: agency and OSM differ"
                ].append(r)
    out = [
        "## Baltimore's one-way and lanes, not used (OWNER-DECISIONS 222)",
        "",
        'The owner, 2026-10-02: "Ignore it; keep OSM (Recommended)", and "Baltimore\'s data doesn\'t '
        "seem nearly as complete as DC\" (223). The centerline's one-way and lane count are never used, "
        "for stress or routing; where they differ from OSM's the way keeps OSM's. Baltimore fills a "
        "missing posted speed only (184).",
        "",
        "| the centerline records, differently from OSM | ways | miles | longest |",
        "| --- | --- | --- | --- |",
    ]
    for kind, rows in sorted(kinds.items()):
        rows.sort(key=lambda r: -int(r["m"]))
        longest = ", ".join(f"{r['name'] or '(unnamed)'} {r['way']}" for r in rows[:4])
        miles = sum(int(r["m"]) for r in rows) / 1609.344
        out.append(f"| {kind} | {len(rows)} | {miles:,.1f} | {longest} |")
    if not kinds:
        out.append("| (none) | 0 | 0.0 | |")
    return [*out, ""]


def load_rows(path: Path):
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dcbal", type=Path, required=True)
    parser.add_argument("--region-baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    dcbal = load_rows(args.dcbal)
    by_id = {int(r["way"]): r for r in dcbal}
    baseline = {}
    with args.region_baseline.open() as handle:
        for line in handle:
            f = line.rstrip("\n").split("\t")
            baseline[int(f[0])] = f

    # -- Region-wide
    states = ["DC", "MD", "VA"]
    before: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    after: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    mismatch = 0
    changed_region_ways = 0
    for way_id, f in baseline.items():
        miles = float(f[4]) / MI
        t0 = int(f[1])
        t1 = t0
        state = f[5]
        row = by_id.get(way_id)
        if row is not None:
            # DC and Baltimore ways: both tiers from the same run, which agrees with the
            # baseline wherever nothing else differs; any mismatch is counted.
            if int(row["tier0"]) != t0:
                mismatch += 1
            t0 = int(row["tier0"])
            t1 = int(row["tier1"])
            if t0 != t1:
                changed_region_ways += 1
        for key in ("Region", state if state in states else "no state"):
            before[key][t0] += miles
            after[key][t1] += miles
    # Baltimore City (the part of the box near the city's street centerline)
    for row in dcbal:
        if row["region"] == "baltimore" and row["in_area"] == "1":
            miles = int(row["m"]) / MI
            before["Baltimore City (within about 500 ft [150 m] of its centerline)"][
                int(row["tier0"])
            ] += miles
            after["Baltimore City (within about 500 ft [150 m] of its centerline)"][
                int(row["tier1"])
            ] += miles
    for row in dcbal:
        if row["region"] == "dc" and row["matched"] == "1":
            miles = int(row["m"]) / MI
            before["DC ways a Roadway Block was matched to"][int(row["tier0"])] += miles
            after["DC ways a Roadway Block was matched to"][int(row["tier1"])] += miles

    order = [
        "Region",
        "DC",
        "MD",
        "VA",
        "no state",
        "DC ways a Roadway Block was matched to",
        "Baltimore City (within about 500 ft [150 m] of its centerline)",
    ]
    out = [
        "# Before and after: DC Roadway Block and Baltimore street centerline conflated",
        "",
        "Before: this branch's classifier on the 2026-09-25 extract without the agency layers, as the "
        "earlier calibration tables were made (classification only: the loaded stress and access rows, and "
        "the 2026-10-01 MoCo and Baltimore override files, are overrides applied at the rebuild and are in "
        "neither column). After: the same classifier with the agency layers conflated "
        "(`pipeline.conflation.road_facts_by_way`, `overlay_road_facts`) and the Roadway Block's AADT "
        "filling where no count layer reached the way. In the District the record takes priority over "
        "OSM's own tags (OWNER-DECISIONS 190, below), except where a block cannot speak for one way: the "
        "overlay never writes a bike facility OSM maps as its own way onto the road (nor onto another way "
        "of the same block, review r2), nor a protected lane where OSM says `bicycle=no`, `use_sidepath` "
        "or `cycleway*=no`; it gives each carriageway its own direction's lanes and bike lane, keeps a "
        "slip road's own lanes, reads a lane as contraflow only where DC flags it, and takes Baltimore's "
        "speed only where OSM has none (OWNER-DECISIONS 184); a painted lane's reach "
        "beside parking is the lane plus the parking lane only where DC records the lane beside parking, "
        "against Furth's 15 ft [4.6 m]. Only DC's and Baltimore's ways can change; every other way is the "
        "baseline's. Road ways only (proposed, construction, platform and corridor ways and trail-class "
        "ways are not classified here). Miles.",
        "",
        f"The two runs agree on the baseline tier of all but {mismatch:,} of the {len(by_id):,} DC and Baltimore ways "
        "(the baseline did not know a separately mapped bike facility the way the rebuild's own pairing does).",
        "",
        "## Region-wide",
        "",
        tier_table([(label, before[label], after[label]) for label in order if label in before]),
        "",
    ]

    # -- What moved, and why
    moved = defaultdict(lambda: [0, 0.0])
    direction = defaultdict(lambda: [0.0, 0.0])
    for row in dcbal:
        if row["tier0"] == row["tier1"] or (row["region"] == "baltimore" and row["in_area"] != "1"):
            continue
        key = (row["region"], " + ".join(causes(row)))
        miles = int(row["m"]) / MI
        moved[key][0] += 1
        moved[key][1] += miles
        up = int(row["tier1"]) > int(row["tier0"])
        direction[key][0 if up else 1] += miles
    out += [
        "## What moved, by what the layer changed",
        "",
        "Ways whose tier changed, by the inputs the layer changed on them (from the tags the classifier read before and after).",
        "",
        "| area | the layer changed | ways | miles | higher stress | lower stress |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for (region, cause), (ways, miles) in sorted(moved.items(), key=lambda kv: -kv[1][1])[:24]:
        up, down = direction[(region, cause)]
        out.append(f"| {region} | {cause} | {ways:,} | {miles:,.1f} | {up:,.1f} | {down:,.1f} |")
    out.append("")

    # -- OWNER-DECISIONS 190, row by row (review r2's table)
    labels = {
        "A": "A. DC records no facility on any block: OSM's painted lane removed",
        "B": "B. DC one-way over OSM's explicit two-way",
        "C4": "C4. DC two-way over OSM's one-way on a plain street",
    }
    applied = defaultdict(list)
    for row in dcbal:
        if row["region"] != "dc" or row["state"] != "DC":
            continue
        without = dict(
            item.split(":") for item in row.get("item190_without", "").split(",") if item
        )
        for name in filter(None, row.get("item190", "").split(",")):
            applied[name].append((row, int(without.get(name, row["tier1"]))))
    out += [
        "## OWNER-DECISIONS 190: DC data takes priority over OSM",
        "",
        'The owner, 2026-10-02: "DC data takes priority over OSM. It\'s updated regularly." Where the '
        "round-1 rules left OSM standing in the District, the record now wins, except where a block, "
        "which describes the whole road, cannot speak for one of its ways (review r2's scoping). The "
        "tier effect of each row is measured on its own: the tier with the row against the same run "
        "with only that row left out.",
        "",
        "| row | ways | miles | tier changes | with the row: lower stress | higher stress | by movement |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name in ("A", "B", "C4"):
        found = applied.get(name, [])
        ways = len(found)
        miles = sum(int(r["m"]) for r, _ in found) / MI
        moves = Counter((t, int(r["tier1"])) for r, t in found if t != int(r["tier1"]))
        down = sum(n for (a, b), n in moves.items() if b < a)
        up = sum(n for (a, b), n in moves.items() if b > a)
        detail = ", ".join(f"LTS {a} to {b}: {n}" for (a, b), n in sorted(moves.items())) or "none"
        out.append(
            f"| {labels[name]} | {ways:,} | {miles:,.1f} | {sum(moves.values()):,} ways "
            f"({sum(int(r['m']) for r, t in found if t != int(r['tier1'])) / MI:,.1f} mi) | {down:,} | {up:,} | {detail} |"
        )
    kept = defaultdict(lambda: [0, 0.0])
    for row in dcbal:
        if row["region"] != "dc" or row["state"] != "DC":
            continue
        for found in filter(None, row["disagree"].split("; ")):
            if found.startswith("oneway:") or found.startswith(("bike facility", "lanes:")):
                kept[found][0] += 1
                kept[found][1] += int(row["m"]) / MI
    out += [
        "",
        "Where OSM still stands in the District, and why (rows C1-C3, D and E of the review, and the "
        "exceptions to A and B):",
        "",
        "| what is kept | ways | miles |",
        "| --- | --- | --- |",
    ]
    out += [
        f"| {found} | {n:,} | {m:,.1f} |"
        for found, (n, m) in sorted(kept.items(), key=lambda kv: -kv[1][0])
    ]
    agreed = [
        r
        for r in dcbal
        if r["region"] == "dc" and r["state"] == "DC" and "separate way" in r["agree"]
    ]
    links = [
        r
        for r in dcbal
        if r["region"] == "dc"
        and r["state"] == "DC"
        and r["matched"] == "1"
        and r["highway"].endswith("_link")
    ]
    out += [
        f"| E. bike facility OSM maps as its own way (on the way or on another way of its block), counted as agreement | {len(agreed):,} | {sum(int(r['m']) for r in agreed) / MI:,.1f} |",
        f"| D. slip roads: their own lanes, no block count | {len(links):,} | {sum(int(r['m']) for r in links) / MI:,.1f} |",
        "",
    ]

    # -- The parking reach on its own (review r1: separate it from the rest)
    reach_moves = Counter()
    reach_ways = 0
    for row in dcbal:
        if row.get("tier1_noreach", row["tier1"]) == row["tier1"]:
            continue
        reach_ways += 1
        reach_moves[(int(row["tier1_noreach"]), int(row["tier1"]))] += int(row["m"]) / MI
    with_reach = sum(1 for row in dcbal if row.get("reach_ft"))
    out += [
        "## The parking reach on its own (`classify(parking_width_m=)`)",
        "",
        f"The one change outside the data plumbing: where DC records a painted lane beside a parking "
        f"lane (`BIKELANE_PARKINGLANE_ADJACENT`), the parking lane's width is added to the lane's for "
        f"Furth's reach, adequate at 15 ft [4.6 m] (MTI 11-19, Table 2). It applies on {with_reach:,} "
        f"ways and changes the tier of {reach_ways:,} of them "
        f'({sum(reach_moves.values()):,.1f} mi), against the same "after" with the lane measured on its '
        "own. Every other change in this report is the layer's data. The criterion itself moved from "
        "13.5 ft to Furth's 15 ft in the same change; no way in the extract carries a lane or shoulder "
        "width between the two [4.1 to 4.57 m], so no OSM-only way outside DC and Baltimore moves and the "
        "region baseline stands.",
        "",
        "| without the reach | with it | miles |",
        "| --- | --- | --- |",
    ]
    out += [
        f"| LTS {a} | LTS {b} | {m:,.1f} |"
        for (a, b), m in sorted(reach_moves.items(), key=lambda kv: -kv[1])
    ]
    out.append("")

    # -- By tier movement, per area
    for region, label in (("dc", "DC"), ("baltimore", "Baltimore City")):
        moves = Counter()
        for row in dcbal:
            if row["region"] != region or row["tier0"] == row["tier1"] or row["in_area"] != "1":
                continue
            moves[(int(row["tier0"]), int(row["tier1"]))] += int(row["m"]) / MI
        out += [
            f"### {label}: miles by tier movement",
            "",
            "| from | to | miles |",
            "| --- | --- | --- |",
        ]
        out += [
            f"| LTS {a} | LTS {b} | {m:,.1f} |"
            for (a, b), m in sorted(moves.items(), key=lambda kv: -kv[1])
        ]
        out.append("")

    # -- Examples
    def example(label: str, rows: list[dict]) -> list[str]:
        b, a = defaultdict(float), defaultdict(float)
        groups = defaultdict(lambda: {"miles": 0.0, "ex": None, "ways": 0})
        total = 0.0
        for row in rows:
            miles = int(row["m"]) / MI
            total += miles
            b[int(row["tier0"])] += miles
            a[int(row["tier1"])] += miles
            key = (row["tier0"], row["tier1"], row["rule0"], row["rule1"], row["matched"])
            g = groups[key]
            g["miles"] += miles
            g["ways"] += 1
            g["ex"] = g["ex"] or row
        lines = [f"### {label}: {total:.2f} mi, {len(rows)} ways", ""]
        lines.append(
            "before "
            + ", ".join(f"LTS {t} {b[t]:.2f}" for t in sorted(b))
            + " | after "
            + ", ".join(f"LTS {t} {a[t]:.2f}" for t in sorted(a))
        )
        lines.append("")
        lines += [
            "| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for (t0, t1, r0, r1, matched), g in sorted(groups.items(), key=lambda kv: -kv[1]["miles"])[
            :6
        ]:
            ex = g["ex"]
            mark = f"{t0} -> {t1}" if t0 != t1 else f"{t0} (same)"
            facts = ex["facts"] if matched == "1" else "not matched"
            lines.append(
                f"| {g['miles']:.2f} | {g['ways']} | LTS {mark} | {r0} | {r1} | `{ex['tags']}` | `{ex['tags1']}` | `{facts}` |"
            )
        lines.append("")
        return lines

    out += [
        "## The owner's example roads (DC)",
        "",
        "16th Street NW and Connecticut Avenue NW stay at LTS 4 where the Roadway Block's lanes and counts "
        'put them there (OWNER-DECISIONS 179, "Keep LTS 4 (Recommended)"). Two readings behind that, '
        "recorded for the owner: DC's lane totals include bus lanes (`BUSLANE_*` on 16th Street), which "
        "are counted as travel lanes, the conservative reading; and Connecticut Avenue's reversible lanes "
        "are assumed to be operating, so they count as lanes in the peak direction (1 + 1 + 2 reversible "
        "is 3 a direction).",
        "",
    ]
    for label, pattern in DC_EXAMPLES.items():
        rows = [r for r in dcbal if r["region"] == "dc" and re.match(pattern, r["name"])]
        out += example(label, rows) if rows else [f"### {label}: no ways found", ""]
    # The Arboretum
    arboretum = []
    for r in dcbal:
        if r["region"] != "dc":
            continue
        f = baseline.get(int(r["way"]))
        if not f:
            continue
        lon, lat = float(f[8]), float(f[9])
        in_box = (
            ARBORETUM_BOX[0] <= lon <= ARBORETUM_BOX[2]
            and ARBORETUM_BOX[1] <= lat <= ARBORETUM_BOX[3]
        )
        if in_box and (r["highway"] == "service" or r["name"].endswith(("Road", "Drive", "Rd"))):
            arboretum.append(r)
    out += ["### The US National Arboretum's internal roads", ""]
    out += example("Arboretum (roads and service ways in the grounds)", arboretum)

    out += baltimore_not_used(dcbal)
    out += ["## Baltimore examples", ""]
    in_city = [r for r in dcbal if r["region"] == "baltimore" and r["in_area"] == "1"]
    for label, pattern in BALTIMORE_EXAMPLES.items():
        rows = [r for r in in_city if re.match(pattern, r["name"])]
        if rows:
            out += example(label, rows)
    args.out.write_text("\n".join(out))
    print(
        "written",
        args.out,
        "changed region ways",
        changed_region_ways,
        "baseline mismatches",
        mismatch,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
