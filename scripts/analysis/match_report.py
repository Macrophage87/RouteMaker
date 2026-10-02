#!/usr/bin/env python3
# ruff: noqa: E501 - table rows run long
"""The conflation match statistics and how often the agency and OSM disagree.

    python scripts/analysis/match_report.py --dcbal out/dcbal.tsv --stats out/match-stats.json \\
        --out reports/roadway-block-match.md

For DC (Roadway Block) and Baltimore (street centerline): the match rate against the agency's
blocks and against OSM's ways, the unmatched agency miles, how the matched values compare with
OSM's own tags, and how many ways lie along several blocks.
"""

from __future__ import annotations

import argparse
import csv
import json
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
PUBLIC_STREETS = {
    "residential",
    "tertiary",
    "secondary",
    "primary",
    "trunk",
    "unclassified",
    "living_street",
    "motorway",
    "motorway_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
    "trunk_link",
}


def table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def pct(a: float, b: float) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def region_section(
    rows: list[dict], stats: dict, label: str, agency_lanes: bool, baltimore: bool = False
) -> list[str]:
    area = [r for r in rows if r["in_area"] == "1"]
    miles = lambda rs: sum(int(r["m"]) for r in rs) / MI  # noqa: E731
    matched = [r for r in area if r["matched"] == "1"]
    streets = [r for r in area if r["highway"] in PUBLIC_STREETS]
    streets_matched = [r for r in streets if r["matched"] == "1"]
    out = [
        f"## {label}",
        "",
        f"**Agency side.** {stats['blocks']:,} blocks, {stats['block_miles']:,.1f} mi. "
        f"{stats['blocks'] - stats['unmatched_blocks']:,} lie along a matched OSM way "
        f"({pct(stats['blocks'] - stats['unmatched_blocks'], stats['blocks'])} of blocks); "
        f"**{stats['unmatched_block_miles']:,.1f} mi in {stats['unmatched_blocks']:,} blocks are unmatched** "
        f"({pct(stats['unmatched_block_miles'], stats['block_miles'])} of the miles): "
        + ", ".join(f"{name} ({n})" for name, n in stats["unmatched_block_names"][:12])
        + ".",
        "",
        f"**OSM side.** {len(area):,} road ways ({miles(area):,.0f} mi) in the area; {len(matched):,} matched "
        f"({miles(matched):,.0f} mi, {pct(miles(matched), miles(area))}). Public street classes only "
        f"(residential through primary, trunk, links, motorway): {len(streets_matched):,} of {len(streets):,} ways, "
        f"{miles(streets_matched):,.0f} of {miles(streets):,.0f} mi, **{pct(miles(streets_matched), miles(streets))}**. "
        "The rest is mostly `service` ways (parking aisles, driveways, alleys), which a street layer does not describe "
        "and which match only where a block's name agrees.",
        "",
    ]
    by_class = defaultdict(lambda: [0.0, 0.0])
    for r in area:
        c = by_class[r["highway"]]
        c[0] += int(r["m"]) / MI
        if r["matched"] == "1":
            c[1] += int(r["m"]) / MI
    out.append(
        table(
            ["OSM class", "miles", "matched", "rate"],
            [
                [k, f"{v[0]:,.1f}", f"{v[1]:,.1f}", pct(v[1], v[0])]
                for k, v in sorted(by_class.items(), key=lambda kv: -kv[1][0])[:12]
            ],
        )
    )
    out.append("")

    names = Counter(r["names_agree"] for r in matched)
    out.append(
        f"Street names: of the matched ways, {names['1']:,} agree with their block's name, {names['0']:,} disagree "
        f"(geometry only), {names['']:,} have no name to compare ({pct(names['1'], len(matched))} agree)."
    )
    counts = Counter()
    for r in matched:
        n = int(r.get("n_blocks") or 0)
        counts["1" if n == 1 else "2-3" if n <= 3 else "4-10" if n <= 10 else "more than 10"] += 1
    out.append("")
    out.append(
        "Blocks per matched way: "
        + ", ".join(f"{k} {counts[k]:,}" for k in ("1", "2-3", "4-10", "more than 10"))
        + ". A way along several blocks takes the most stressful of their values (one tier is stored per way)."
    )
    out.append("")

    # -- how the agency's values compare with OSM's
    speed_differs = Counter()
    speed_miles = defaultdict(float)
    speed_pairs = defaultdict(float)
    lanes_differs = Counter()
    lanes_miles = defaultdict(float)
    bike = Counter()
    bike_miles = defaultdict(float)
    parking = Counter()
    parking_miles = defaultdict(float)
    oneway = Counter()
    oneway_miles = defaultdict(float)
    for r in matched:
        osm = json.loads(r["tags"]) if r["tags"] else {}
        facts = json.loads(r["facts"]) if r["facts"] else {}
        m = int(r["m"]) / MI
        agency_speed = max(facts.get("speed", {}).values(), default=None)
        osm_speed = parse_maxspeed_mph(osm.get("maxspeed"))
        if agency_speed is not None:
            key = (
                "agency posts it, OSM unposted"
                if osm_speed is None
                else "same speed"
                if round(osm_speed) == agency_speed
                else "OSM differs"
            )
            speed_differs[key] += 1
            speed_miles[key] += m
            if key == "OSM differs":
                speed_pairs[(f"{round(osm_speed)} mph", f"{agency_speed} mph")] += m
        else:
            speed_differs["agency has no speed"] += 1
            speed_miles["agency has no speed"] += m
        a_lanes = None
        lanes_by = facts.get("lanes", {})
        if lanes_by:
            from routemaker.agency_roads import RoadFacts
            from routemaker.agency_roads import lanes_per_direction as agency_lanes_fn

            a_lanes = agency_lanes_fn(
                RoadFacts(agency="x", lanes=lanes_by, way="one" if facts.get("one_way") else "both")
            )
        o_lanes = lanes_per_direction(osm)
        if a_lanes is not None:
            key = (
                "agency has lanes, OSM none"
                if o_lanes is None
                else "same"
                if o_lanes == a_lanes
                else "agency more"
                if a_lanes > o_lanes
                else "agency fewer"
            )
            lanes_differs[key] += 1
            lanes_miles[key] += m
        if facts.get("one_way") is not None:
            o_one = is_oneway(osm)
            key = (
                "agree one-way"
                if facts["one_way"] and o_one
                else "agree two-way"
                if not facts["one_way"] and not o_one
                else "agency one-way, OSM not"
                if facts["one_way"]
                else "agency two-way, OSM one-way"
            )
            oneway[key] += 1
            oneway_miles[key] += m
        if agency_lanes:
            o_bike = bool(
                cycleway_values(osm)
                & {"lane", "track", "opposite_lane", "opposite_track", "buffered_lane"}
            )
            a_bike = bool(facts.get("bike"))
            key = (
                "both"
                if o_bike and a_bike
                else "agency only"
                if a_bike
                else "OSM only"
                if o_bike
                else "neither"
            )
            bike[key] += 1
            bike_miles[key] += m
            o_park = has_parking_lane(osm)
            a_park = facts.get("parking")
            if a_park is not None:
                key = (
                    "OSM silent"
                    if o_park is None
                    else "agree"
                    if (o_park and a_park > 0) or (not o_park and a_park == 0)
                    else "disagree"
                )
                parking[key] += 1
                parking_miles[key] += m

    def rows(counter, miles_by):
        total = sum(counter.values())
        return [
            [k, f"{v:,}", f"{miles_by[k]:,.1f}", pct(v, total)]
            for k, v in sorted(counter.items(), key=lambda kv: -kv[1])
        ]

    out += [
        "### Posted speed: agency against OSM `maxspeed` (matched ways)",
        "",
        table(["", "ways", "miles", "share"], rows(speed_differs, speed_miles)),
        "",
    ]
    if speed_pairs:
        used = (
            "OSM's posted speed is kept and the city's fills only where OSM has none, "
            "OWNER-DECISIONS 184"
            if baltimore
            else "the agency's is used, OWNER-DECISIONS 151"
        )
        out += [
            f"Where OSM's posted speed and the agency's differ ({used}), the most common pairs:",
            "",
            table(
                ["OSM maxspeed", "agency", "miles"],
                [
                    [a, b, f"{m:,.1f}"]
                    for (a, b), m in sorted(speed_pairs.items(), key=lambda kv: -kv[1])[:8]
                ],
            ),
            "",
        ]
    if lanes_differs:
        caveat = (
            [
                f"Baltimore's `lane_count` is filled on only {stats.get('blocks_with_lanes', 0):,} of the "
                f"{stats['blocks']:,} centerline blocks installed, so this table covers "
                f"{sum(lanes_differs.values()):,} ways and its shares say nothing about the city's streets "
                "at large.",
                "",
            ]
            if baltimore
            else []
        )
        out += [
            "### Lanes per direction: agency against OSM",
            "",
            *caveat,
            table(["", "ways", "miles", "share"], rows(lanes_differs, lanes_miles)),
            "",
        ]
    if oneway:
        caveat = (
            [
                "The centerline marks one-way streets only (`oneway` FT or TF) and says nothing of a "
                f"two-way street ({stats.get('blocks_one_way', 0):,} one-way blocks, "
                f"{stats.get('blocks_two_way', 0):,} marked two-way), so the shares below are of the ways "
                "along a one-way record, not of all matched ways. Where OSM tags a way two-way in so many "
                "words (`oneway=no`, or lanes counted each way) the city's one-way is not applied and is "
                "counted as a disagreement.",
                "",
            ]
            if baltimore
            else [
                "DC's record takes priority over OSM's (OWNER-DECISIONS 190): a DC one-way is applied "
                "where OSM tags the way two-way in so many words, except on a reversible-lane block, a "
                "junction stub under 30 m [100 ft] or where the direction is not known; a DC two-way is "
                "applied over an OSM one-way except on a carriageway of a divided road or of a pair "
                "sharing the block, a slip road, a freeway or trunk road, a roundabout, a stub or an "
                "unnamed way. What is kept is counted as a disagreement (before-after.md has the table).",
                "",
            ]
        )
        out += [
            "### One-way streets",
            "",
            *caveat,
            table(["", "ways", "miles", "share"], rows(oneway, oneway_miles)),
            "",
        ]
    if agency_lanes:
        separate = [r for r in matched if "separate way" in (r.get("agree") or "")]
        out += [
            "### Bike lane or track: agency against OSM",
            "",
            f"Where OSM maps the way's bike facility as a way of its own (`cycleway*=separate`, or a "
            f"separately mapped facility beside it), on the way itself or on another way matched to one of "
            f"its blocks (review r2), the agency's facility is that way and is never written onto the road: "
            f"{len(separate):,} matched ways ({miles(separate):,.1f} mi), counted as agreement. Nor is a "
            f"protected lane written where OSM says `bicycle=no`, `use_sidepath` or `cycleway*=no`. A lane "
            f"is a contraflow lane only where DC flags it (`BIKELANE_CONTRAFLOW`), and where DC records no "
            f"facility on any block of a way, OSM's painted lane is removed (OWNER-DECISIONS 190).",
            "",
            table(["", "ways", "miles", "share"], rows(bike, bike_miles)),
            "",
        ]
        out += [
            "### Parking: agency against OSM",
            "",
            table(["", "ways", "miles", "share"], rows(parking, parking_miles)),
            "",
        ]

    # -- the tier effect
    changed = [r for r in matched if r["tier0"] != r["tier1"]]
    out += [
        f"Tier effect: {len(changed):,} of the {len(matched):,} matched ways ({miles(changed):,.1f} of {miles(matched):,.1f} mi) change tier.",
        "",
    ]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dcbal", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.dcbal.open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    stats = json.loads(args.stats.read_text())
    out = [
        "# Conflation of DC's Roadway Block and Baltimore's street centerline onto OSM ways",
        "",
        "Match statistics on the source extract of 2026-09-25, from `scripts/analysis/data_before_after.py` "
        "(the rebuild's own conflation, `pipeline.conflation.road_facts_by_way`). A block is matched when it "
        "lies along a matched OSM way, by geometry (within 66 ft [20 m], heading agreeing locally) and street "
        "name; a way is matched when its blocks cover half of it. A block naming a different street vetoes "
        "every way but a freeway's (motorway and trunk and their links), and a service or track way needs "
        "an agreeing name.",
        "",
    ]
    out += region_section(
        [r for r in rows if r["region"] == "dc"],
        stats["dc"],
        "DC: Roadway Block (DDOT, CC BY 4.0)",
        True,
    )
    out += region_section(
        [r for r in rows if r["region"] == "baltimore"],
        stats["baltimore"],
        "Baltimore: street centerline (Open Baltimore)",
        False,
        baltimore=True,
    )
    out += [
        "## AADT",
        "",
        f"Roadway Block AADT (2020) is on {stats['dc']['blocks_with_aadt']:,} blocks. A matched way takes the busiest of its "
        f"blocks' counts where no count layer reached it, and never on a slip road: "
        f"{stats['dc']['inventory_aadt_ways']:,} ways do. DDOT's own 2024 counts (the volume layer) are the "
        "newer survey and are never replaced. `segment.attr_sources` names the count the classifier read.",
        "",
    ]
    args.out.write_text("\n".join(out))
    print("written", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
