# ruff: noqa: E501 - table rows run long
#!/usr/bin/env python3
"""Tiers for DC's and Baltimore's ways with and without the agency street layers.

Runs the rebuild's own steps (the volume conflation, the block conflation, the
overlay, `classify`) over the District's and Baltimore's ways read from the
source extract, twice: as the integration branch classifies them today, and with
DC's Roadway Block and Baltimore's street centerline conflated. Nothing is
loaded anywhere; the output is a table and the match statistics.

    python scripts/analysis/data_before_after.py \\
        --roadway reference/roadway.json --volume reference/volume.json \\
        --ways-dir DIR (ways-dc.jsonl, ways-baltimore.jsonl) \\
        --state-polygons state-polys.json --urban reference/urban-areas.json \\
        --live-ways live-ways.csv --out DIR

Writes `dcbal.tsv` (one row per road way) and `match-stats.json`. `tier1_noreach` is the
"after" tier with the parking lane's width left out of a painted lane's reach, so the effect of
`classify(parking_width_m=)` can be told apart from the rest of the layer's.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import shapely.geometry as sg  # noqa: E402
import shapely.wkb  # noqa: E402
from shapely.prepared import prep  # noqa: E402

from pipeline import conflation, extract, variants  # noqa: E402
from routemaker import agency_roads, divided, facility, speed_corrections  # noqa: E402
from routemaker.classes import TRAIL_CLASS_HIGHWAY  # noqa: E402
from routemaker.geo import Point, haversine  # noqa: E402
from routemaker.stress import classify  # noqa: E402

MI = 1609.344
SKIP = {"proposed", "construction", "platform", "corridor"}
# About 500 ft [150 m]: how near a street centerline an OSM way must be to count as in Baltimore.
CITY_NEAR_DEG = 0.0015


def length_m(coords) -> float:
    return sum(haversine(Point(*a), Point(*b)) for a, b in zip(coords, coords[1:], strict=False))


def load_ways(path: Path) -> list[extract.Way]:
    ways = []
    with path.open() as handle:
        for line in handle:
            row = json.loads(line)
            ways.append(
                extract.Way(
                    osm_id=row["id"],
                    tags=row["tags"],
                    node_ids=[],
                    coordinates=[tuple(c) for c in row["c"]],
                )
            )
    return ways


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roadway", type=Path, required=True)
    parser.add_argument("--volume", type=Path, required=True)
    parser.add_argument("--ways-dir", type=Path, required=True)
    parser.add_argument("--state-polygons", type=Path, required=True)
    parser.add_argument("--urban", type=Path, required=True)
    parser.add_argument("--live-ways", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()

    polygons = {
        state: shapely.wkb.loads(bytes.fromhex(hexwkb))
        for state, hexwkb in json.loads(args.state_polygons.read_text()).items()
    }
    prepared = {state: prep(polygon) for state, polygon in polygons.items()}
    rank = {"DC": 0, "VA": 1, "MD": 2}

    def state_of(coords) -> str | None:
        lon, lat = coords[len(coords) // 2]
        point = sg.Point(lon, lat)
        hits = [s for s, p in prepared.items() if p.covers(point)]
        return min(hits, key=lambda s: rank.get(s, 99)) if hits else None

    urban = set(json.loads(args.urban.read_text()))
    live_aadt: dict[int, int] = {}
    with args.live_ways.open() as handle:
        for row in csv.DictReader(handle):
            if row["aadt"]:
                live_aadt[int(row["osm_way_id"])] = int(row["aadt"])
    speeds = speed_corrections.load()

    blocks = tuple(
        conflation.RoadFeature(
            feature_id=row["id"],
            coordinates=[tuple(c) for c in row["coordinates"]],
            facts=agency_roads.RoadFacts.from_json(row["facts"]),
        )
        for row in json.loads(args.roadway.read_text())
    )
    block_by_id = {block.feature_id: block for block in blocks}
    print(f"{len(blocks)} blocks", flush=True)

    volume_rows = json.loads(args.volume.read_text())
    stats: dict[str, object] = {}
    rows = []
    for region in ("dc", "baltimore"):
        ways = load_ways(args.ways_dir / f"ways-{region}.jsonl")
        print(region, len(ways), "ways", flush=True)
        # The region's volume layer, as the rebuild would hold it, restricted to
        # the box so the exclusivity bookkeeping is the whole of it.
        west = min(c[0] for w in ways for c in w.coordinates)
        east = max(c[0] for w in ways for c in w.coordinates)
        south = min(c[1] for w in ways for c in w.coordinates)
        north = max(c[1] for w in ways for c in w.coordinates)
        volume = []
        for row in volume_rows:
            lon, lat = row["coordinates"][len(row["coordinates"]) // 2]
            if west <= lon <= east and south <= lat <= north:
                volume.append(
                    conflation.AgencyFeature(
                        feature_id=row["id"],
                        coordinates=[tuple(c) for c in row["coordinates"]],
                        aadt=int(row["aadt"]),
                        source=row["source"],
                        year=row.get("year"),
                        agency=row.get("agency"),
                    )
                )
        agency = agency_roads.DC_AGENCY if region == "dc" else agency_roads.BALTIMORE_AGENCY
        region_blocks = [b for b in blocks if b.facts.agency == agency]
        # Which ways are in the agency's own area: DC by its polygon; Baltimore by
        # lying within CITY_NEAR_DEG (about 150 m) of the city's street centerline,
        # since the bounding box takes in the county around it.
        from shapely.strtree import STRtree

        block_lines = [sg.LineString(b.coordinates) for b in region_blocks]
        block_tree = STRtree(block_lines)
        entries = [(w.osm_id, w.coordinates, variants.is_trail_class(w.tags)) for w in ways]
        before_match = conflation.conflate(entries, volume).matched
        after_match = dict(before_match)
        # The rebuild's own wiring (`pipeline.run`'s volume-conflation stage).
        agg, result = conflation.road_facts_by_way(ways, entries, region_blocks)
        print(
            region,
            "volume",
            len(volume),
            "blocks matched ways",
            len(result.matched),
            f"{time.monotonic() - started:.0f}s",
            flush=True,
        )

        cands = []
        for w in ways:
            t = dict(w.tags)
            if divided._candidate(t):
                from types import SimpleNamespace

                cands.append(
                    SimpleNamespace(
                        osm_id=w.osm_id,
                        tags={k: t[k] for k in ("highway", "name", "oneway") if k in t},
                        coordinates=w.coordinates,
                    )
                )
        div = divided.carriageways(cands)
        _trails, separate_roads = facility.separate_pairs(
            (w.osm_id, w.tags, w.coordinates) for w in ways
        )

        tags_of = {w.osm_id: w.tags for w in ways}
        # The rebuild's own overlay wiring (`pipeline.run`'s classification stage).
        overlays = conflation.overlay_road_facts(ways, agg, div, separate_roads)
        # The same with one OWNER-DECISIONS 190 row left out at a time, so the report can say
        # what each row does to the tiers on its own.
        without = {
            row: conflation.overlay_road_facts(
                ways, agg, div, separate_roads, rows=agency_roads.ROWS_190 - {row}
            )
            for row in sorted(agency_roads.ROWS_190)
        }
        counted = set(before_match)
        for way_id, facts in agg.items():
            # The block's count fills where no count layer reached the way, never on a ramp.
            filled = conflation.block_count(way_id, tags_of[way_id], facts, result, counted)
            if filled is not None:
                after_match[way_id] = filled

        check_live = Counter()
        for w in ways:
            hw = w.tags.get("highway")
            if hw in SKIP or hw in TRAIL_CLASS_HIGHWAY or hw is None:
                continue
            state = state_of(w.coordinates)
            if state is None or (region == "dc" and state != "DC"):
                continue
            mid = w.coordinates[len(w.coordinates) // 2]
            in_city = (
                1
                if region == "dc"
                else int(
                    len(
                        block_tree.query(sg.Point(mid), predicate="dwithin", distance=CITY_NEAR_DEG)
                    )
                    > 0
                )
            )
            tags0, _ = speed_corrections.corrected(dict(w.tags), speeds.get(w.osm_id))
            kw = dict(
                urban=w.osm_id in urban,
                jurisdiction=state,
                divided=w.osm_id in div,
                separate_facility=w.osm_id in separate_roads,
            )
            b = before_match.get(w.osm_id)
            if (b.aadt if b else None) != live_aadt.get(w.osm_id):
                check_live["aadt differs from the live table"] += 1
            before = classify(
                tags0,
                aadt=b.aadt if b else None,
                aadt_source=b.agency if b else None,
                aadt_year=b.year if b else None,
                **kw,
            )
            facts = agg.get(w.osm_id)
            a = after_match.get(w.osm_id)
            sources, disagree, agree, rows190, tags1 = {}, (), (), (), dict(tags0)
            if facts is not None:
                ov = overlays[w.osm_id]
                tags1, _ = speed_corrections.corrected(ov.tags, speeds.get(w.osm_id))
                sources = {**ov.sources, "aadt": agency_roads.aadt_source(a)}
                disagree, agree, rows190 = ov.disagreements, ov.agreements, ov.precedence
            after_kw = dict(
                aadt=a.aadt if a else None,
                aadt_source=a.agency if a else None,
                aadt_year=a.year if a else None,
                **kw,
            )
            reach = facts.parking_reach_m if facts is not None else None
            after = classify(tags1, parking_width_m=reach, **after_kw)
            # The same, without the parking lane added to the lane's reach.
            noreach = after if reach is None else classify(tags1, **after_kw)
            # Each item-190 row's own effect: the tier with that row left out, "row:tier".
            effects = []
            for row190 in rows190:
                tags_without, _ = speed_corrections.corrected(
                    without[row190][w.osm_id].tags, speeds.get(w.osm_id)
                )
                tier_without = classify(tags_without, parking_width_m=reach, **after_kw).tier
                effects.append(f"{row190}:{int(tier_without)}")
            rows.append(
                {
                    "way": w.osm_id,
                    "region": region,
                    "state": state,
                    "highway": hw,
                    "name": (w.tags.get("name") or "").replace("\t", " "),
                    "m": round(length_m(w.coordinates)),
                    "urban": int(w.osm_id in urban),
                    "in_area": in_city,
                    "matched": int(facts is not None),
                    "coverage": round(result.coverage.get(w.osm_id, 0.0), 2),
                    "tier0": int(before.tier),
                    "rule0": before.rule,
                    "tier1": int(after.tier),
                    "rule1": after.rule,
                    "tier1_noreach": int(noreach.tier),
                    "reach_ft": round(reach / agency_roads.METRES_PER_FOOT, 1) if reach else "",
                    "aadt0": b.aadt if b else "",
                    "aadt1": a.aadt if a else "",
                    "aadt1_agency": a.agency if a else "",
                    "speed0": tags0.get("maxspeed", ""),
                    "speed1": tags1.get("maxspeed", ""),
                    "assumed0": ",".join(before.assumed),
                    "assumed1": ",".join(after.assumed),
                    "sources": json.dumps(sources, sort_keys=True),
                    "blocks": ",".join(facts.blocks[:6]) if facts else "",
                    "n_blocks": len(facts.blocks) if facts else 0,
                    "names_agree": ""
                    if not facts or facts.names_agree is None
                    else int(facts.names_agree),
                    "disagree": "; ".join(disagree),
                    "agree": "; ".join(agree),
                    # The OWNER-DECISIONS 190 rows that overrode one of the way's tags.
                    "item190": ",".join(rows190),
                    "item190_without": ",".join(effects),
                    "divided": int(w.osm_id in div),
                    "tags": json.dumps(
                        {
                            k: v
                            for k, v in w.tags.items()
                            if k.startswith(("maxspeed", "lanes", "oneway", "cycleway", "parking"))
                        },
                        sort_keys=True,
                    ),
                    "tags1": json.dumps(
                        {
                            k: v
                            for k, v in tags1.items()
                            if k.startswith(("maxspeed", "lanes", "oneway", "cycleway", "parking"))
                        },
                        sort_keys=True,
                    ),
                    "facts": json.dumps(
                        {
                            "speed": facts.speed_by_direction,
                            "lanes": facts.lanes_by_direction,
                            "lanes_fwd": facts.lanes_forward,
                            "lanes_back": facts.lanes_backward,
                            "one_way": facts.one_way,
                            "oneway_fwd": facts.oneway_forward,
                            "lanes_per_dir": facts.lanes_per_direction,
                            "speed_mph": facts.speed_mph,
                            "contraflow": facts.contraflow,
                            "bike_recorded": facts.bike_recorded,
                            "bike": facts.bike,
                            "bike_fwd": facts.bike_forward,
                            "bike_back": facts.bike_backward,
                            "bike_ft": facts.bike_width_ft,
                            "parking": facts.parking_lanes,
                            "aadt": facts.aadt,
                        },
                        sort_keys=True,
                    )
                    if facts
                    else "",
                }
            )

        miles = sum(length_m(b.coordinates) for b in region_blocks) / MI
        unmatched = (
            sum(length_m(block_by_id[i].coordinates) for i in result.unmatched_features) / MI
        )
        stats[region] = {
            "blocks": len(region_blocks),
            "block_miles": round(miles, 1),
            "unmatched_blocks": len(result.unmatched_features),
            "unmatched_block_miles": round(unmatched, 1),
            "unmatched_block_names": Counter(
                block_by_id[i].facts.name for i in result.unmatched_features
            ).most_common(40),
            "ways_matched": len(result.matched),
            "volume_features": len(volume),
            "inventory_aadt_ways": sum(1 for m in after_match.values() if m.source == "inventory"),
            "blocks_with_aadt": sum(1 for b in region_blocks if b.facts.aadt),
            "blocks_with_lanes": sum(1 for b in region_blocks if b.facts.lanes),
            "blocks_one_way": sum(1 for b in region_blocks if b.facts.way == "one"),
            "blocks_two_way": sum(1 for b in region_blocks if b.facts.way == "both"),
            "live_check": dict(check_live),
        }
        print(
            region,
            json.dumps({k: v for k, v in stats[region].items() if k != "unmatched_block_names"}),
            flush=True,
        )

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "dcbal.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "match-stats.json").write_text(json.dumps(stats, indent=1, default=list))
    print("rows", len(rows), f"{time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
