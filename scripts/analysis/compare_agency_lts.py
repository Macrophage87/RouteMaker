#!/usr/bin/env python3
# ruff: noqa: E501 - report prose and table rows run long
"""Our tier against other agencies' bicycle stress layers, and Baltimore's facility records.

    python scripts/analysis/compare_agency_lts.py moco|arlington|alexandria|baltimore \\
        --datasets DIR --ways-dir DIR --state-polygons FILE --urban FILE --live-ways FILE --out DIR

Each subcommand reads one agency's layer as `scripts/fetch_agency_layer.py` stored it,
matches it to the OSM ways that lie along it (`pipeline.conflation.conflate_blocks`), classifies
those ways as the rebuild would (the same inputs `data_before_after.py` uses), and writes a
Markdown report: a confusion matrix in miles, the disagreement by OSM road class, and the
largest disagreements, grouped by street and by the pair of tiers.

Arlington's Bike Comfort Index and Alexandria's Transport Streets are for INTERNAL
comparison only (OWNER-DECISIONS 152, 153, 155): their reports name no value that could be
copied into a fixture, and are written outside the repository.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

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


def length_m(coords) -> float:
    return sum(haversine(Point(*a), Point(*b)) for a, b in zip(coords, coords[1:], strict=False))


def lines_of(geometry):
    if not geometry:
        return
    if geometry["type"] == "LineString":
        yield geometry["coordinates"]
    elif geometry["type"] == "MultiLineString":
        yield from geometry["coordinates"]


class Context:
    """The rebuild's classification inputs for one region's ways."""

    def __init__(self, args, region: str) -> None:
        polygons = {
            s: prep(shapely.wkb.loads(bytes.fromhex(h)))
            for s, h in json.loads(Path(args.state_polygons).read_text()).items()
        }
        self.polygons = polygons
        self.urban = set(json.loads(Path(args.urban).read_text()))
        self.aadt: dict[int, tuple[int, str | None, int | None]] = {}
        with Path(args.live_ways).open() as handle:
            for row in csv.DictReader(handle):
                if row["aadt"]:
                    self.aadt[int(row["osm_way_id"])] = (
                        int(row["aadt"]),
                        row.get("src") or None,
                        int(row["yr"]) if row.get("yr") else None,
                    )
        self.speeds = speed_corrections.load()
        self.ways: list[extract.Way] = []
        with (Path(args.ways_dir) / f"ways-{region}.jsonl").open() as handle:
            for line in handle:
                row = json.loads(line)
                self.ways.append(
                    extract.Way(
                        osm_id=row["id"],
                        tags=row["tags"],
                        node_ids=[],
                        coordinates=[tuple(c) for c in row["c"]],
                    )
                )
        self.by_id = {w.osm_id: w for w in self.ways}
        cands = [
            SimpleNamespace(
                osm_id=w.osm_id,
                tags={k: w.tags[k] for k in ("highway", "name", "oneway") if k in w.tags},
                coordinates=w.coordinates,
            )
            for w in self.ways
            if divided._candidate(dict(w.tags))
        ]
        self.divided = divided.carriageways(cands)
        _t, self.separate = facility.separate_pairs(
            (w.osm_id, w.tags, w.coordinates) for w in self.ways
        )

    def state_of(self, coords) -> str | None:
        lon, lat = coords[len(coords) // 2]
        point = sg.Point(lon, lat)
        rank = {"DC": 0, "VA": 1, "MD": 2}
        hits = [s for s, p in self.polygons.items() if p.covers(point)]
        return min(hits, key=lambda s: rank.get(s, 99)) if hits else None

    def is_road(self, way) -> bool:
        hw = way.tags.get("highway")
        return bool(hw) and hw not in SKIP and hw not in TRAIL_CLASS_HIGHWAY

    def classify(self, way, tags=None):
        tags = dict(way.tags) if tags is None else tags
        tags, _ = speed_corrections.corrected(tags, self.speeds.get(way.osm_id))
        aadt = self.aadt.get(way.osm_id)
        return classify(
            tags,
            aadt=aadt[0] if aadt else None,
            aadt_source=aadt[1] if aadt else None,
            aadt_year=aadt[2] if aadt else None,
            urban=way.osm_id in self.urban,
            jurisdiction=self.state_of(way.coordinates),
            divided=way.osm_id in self.divided,
            separate_facility=way.osm_id in self.separate,
        )


def match(ctx: Context, features: list[conflation.RoadFeature], only_state: str | None = None):
    ways = [w for w in ctx.ways if ctx.is_road(w) or True]
    entries = [(w.osm_id, w.coordinates, variants.is_trail_class(w.tags)) for w in ways]
    names = {w.osm_id: w.name for w in ways}
    required = {
        w.osm_id for w in ways if w.tags.get("highway") in agency_roads.NAME_REQUIRED_HIGHWAYS
    }
    vetoed = {
        w.osm_id for w in ways if w.tags.get("highway") not in agency_roads.NAME_FREE_HIGHWAYS
    }
    return conflation.conflate_blocks(
        entries, features, names, name_required=required, name_vetoed=vetoed
    )


def table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def matrix(pairs, row_labels, col_labels, row_name, col_name) -> str:
    """Miles by (our tier, their level)."""
    cells = defaultdict(float)
    for ours, theirs, miles in pairs:
        cells[(ours, theirs)] += miles
    rows = []
    for r in row_labels:
        total = sum(cells[(r, c)] for c in col_labels)
        rows.append(
            [f"{row_name} {r}"] + [f"{cells[(r, c)]:.1f}" for c in col_labels] + [f"{total:.1f}"]
        )
    totals = [sum(cells[(r, c)] for r in row_labels) for c in col_labels]
    rows.append(["total"] + [f"{t:.1f}" for t in totals] + [f"{sum(totals):.1f}"])
    return table(
        [f"miles: {row_name} (rows) / {col_name} (columns)"]
        + [str(c) for c in col_labels]
        + ["total"],
        rows,
    )


def disagreements(records, limit: int, theirs_label: str) -> str:
    """Group by (street, our tier, their level); rank by miles times the gap."""
    groups = defaultdict(
        lambda: {"miles": 0.0, "ways": [], "rules": Counter(), "classes": Counter()}
    )
    for r in records:
        if r["gap"] == 0:
            continue
        key = (r["name"] or "(unnamed)", r["ours"], r["theirs"])
        g = groups[key]
        g["miles"] += r["miles"]
        g["ways"].append(r["way"])
        g["rules"][r["rule"]] += r["miles"]
        g["classes"][r["highway"]] += r["miles"]
    ranked = sorted(groups.items(), key=lambda kv: -(kv[1]["miles"] * abs(kv[0][1] - kv[0][2])))
    rows = []
    for n, ((name, ours, theirs), g) in enumerate(ranked[:limit], 1):
        rule = g["rules"].most_common(1)[0][0]
        klass = g["classes"].most_common(1)[0][0]
        rows.append(
            [
                n,
                name,
                klass,
                f"{g['miles']:.2f}",
                f"LTS {ours}",
                f"{theirs_label} {theirs}",
                rule,
                ", ".join(map(str, g["ways"][:3])),
            ]
        )
    return table(
        ["#", "street", "OSM class", "miles", "ours", "theirs", "our rule", "example ways"], rows
    )


def by_class(records, theirs_label: str) -> str:
    stats = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for r in records:
        s = stats[r["highway"]]
        s[0] += r["miles"]
        s[1 + (0 if r["gap"] == 0 else (1 if r["gap"] > 0 else 2))] += r["miles"]
    rows = []
    for highway, (total, equal, higher, lower) in sorted(stats.items(), key=lambda kv: -kv[1][0])[
        :14
    ]:
        rows.append(
            [
                highway,
                f"{total:.1f}",
                f"{100 * equal / total:.0f}%",
                f"{100 * higher / total:.0f}%",
                f"{100 * lower / total:.0f}%",
            ]
        )
    return table(
        [
            "OSM class",
            "miles",
            "equal",
            f"ours higher than {theirs_label}",
            f"ours lower than {theirs_label}",
        ],
        rows,
    )


def street_name(*parts) -> str | None:
    text = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return text or None


def build_records(ctx, result, level_of, ours_of=None):
    """One record per matched road way: its tier, their level (the dominant block's)."""
    records = []
    for way_id, shares in result.matched.items():
        way = ctx.by_id[way_id]
        if not ctx.is_road(way):
            continue
        level = level_of(shares[0].feature_id)
        if level is None:
            continue
        ours = ctx.classify(way) if ours_of is None else ours_of(way)
        state = ctx.state_of(way.coordinates)
        records.append(
            {
                "way": way_id,
                "name": way.name,
                "highway": way.tags.get("highway"),
                "miles": length_m(way.coordinates) / MI,
                "ours": int(ours.tier),
                "rule": ours.rule,
                "theirs": level,
                "gap": int(ours.tier) - level
                if isinstance(level, int)
                else round(int(ours.tier) - level, 1),
                "state": state,
                "mixed": len({level_of(s.feature_id) for s in shares}) > 1,
                "share": shares[0].share,
            }
        )
    return records


# ---------------------------------------------------------------------------------------
# Montgomery Planning
# ---------------------------------------------------------------------------------------

MOCO_OFF_ROAD_BIKEWAYS = {"Sidepath", "Off-Street Trail", "Park Trail", "Stream Valley Park Trail"}


def moco(args, ctx: Context) -> None:
    layer = Path(args.datasets) / "moco-bicycle-lts" / "moco-bicycle-lts.geojson"
    features, level, kept, dropped = [], {}, Counter(), Counter()
    values = Counter()
    for feature in agency_roads.iter_features(layer):
        p = feature["properties"]
        values[p.get("LTS_EXIST")] += 1
        reason = None
        if p.get("STATUS") != "Existing":
            reason = "not existing"
        elif p.get("BIKEWAY") in MOCO_OFF_ROAD_BIKEWAYS:
            reason = "sidepath or trail record"
        elif str(p.get("STREET_CLASS") or "").startswith(("Other - Parking", "Other - Trail")):
            reason = "parking lot or trail"
        elif p.get("LTS_EXIST") in (None, 0.5, 99):
            reason = "no LTS (0.5 'None')"
        if reason:
            dropped[reason] += 1
            continue
        lts = p["LTS_EXIST"]
        lts = int(lts) if float(lts).is_integer() else float(lts)
        name = street_name(
            p.get("STREET_PREFIX"),
            p.get("STREET_NAME"),
            p.get("STREET_TYPE"),
            p.get("STREET_SUFFIX"),
        )
        for part, line in enumerate(lines_of(feature["geometry"])):
            fid = f"moco-{p['OBJECTID']}-{part}"
            features.append(
                conflation.RoadFeature(fid, line, agency_roads.RoadFacts(agency="moco", name=name))
            )
            level[fid] = lts
            kept[lts] += 1
    result = match(ctx, features)
    records = build_records(ctx, result, level.get)
    records = [r for r in records if r["state"] == "MD"]
    miles = sum(r["miles"] for r in records)
    labels = [1, 2, 2.5, 3, 4, 5]
    pairs = [(r["ours"], r["theirs"], r["miles"]) for r in records]
    exact = sum(r["miles"] for r in records if r["ours"] == r["theirs"])
    # Our whole tiers against MoCo's, 2.5 read as the half level it is: within half a level.
    near = sum(r["miles"] for r in records if abs(r["ours"] - r["theirs"]) <= 0.5)
    within1 = sum(r["miles"] for r in records if abs(r["ours"] - r["theirs"]) <= 1)
    higher = sum(r["miles"] for r in records if r["ours"] > r["theirs"])
    lower = sum(r["miles"] for r in records if r["ours"] < r["theirs"])

    out = [
        "# Our tier against Montgomery County Planning's Bicycle Level of Traffic Stress",
        "",
        'Source: Montgomery County Planning Department, "Bicycle Level of Traffic Stress" (ArcGIS item '
        "fb903d1ffbc84b219bdb47629bd02b82), retrieved 2026-10-01; attribution: Montgomery County Planning "
        "Department. Our tier is the integration branch's classifier (33ff4da) on the 2026-09-25 extract, "
        "before the Roadway Block and Baltimore conflations (neither touches Montgomery County).",
        "",
        "## Are LTS 3 and LTS 4 separate? (OWNER-DECISIONS 149)",
        "",
        "Yes. The layer's existing-condition field `LTS_EXIST` takes the values below on its "
        f'{sum(values.values()):,} records; 3 and 4 are separate levels, and so is 5 ("Very High"). '
        'It also has half levels: 0.5 ("None", not a road a bicycle is rated on) and 2.5 ("Moderate Low").',
        "",
        table(
            ["LTS_EXIST", "records"],
            [
                [k, f"{v:,}"]
                for k, v in sorted(values.items(), key=lambda kv: (kv[0] is None, kv[0]))
            ],
        ),
        "",
        f"Used: existing records of roads ({sum(kept.values()):,}); left out: "
        + ", ".join(f"{n:,} {why}" for why, n in dropped.most_common())
        + ". Sidepaths and trails are left out because they lie beside the road they follow and would "
        "take its probes; the road's own record is the one that rates the road.",
        "",
        "## Match",
        "",
        f"{len(records):,} OSM road ways in Maryland lie along a Montgomery record ({miles:,.0f} mi). "
        "A way along several records takes the level of the one it lies along most (`mixed` ways are "
        f"{100 * sum(r['miles'] for r in records if r['mixed']) / miles:.0f}% of the miles).",
        "",
        f"* Same level: {100 * exact / miles:.1f}% of miles; within half a level (2.5 against 2 or 3): "
        f"{100 * near / miles:.1f}%; within one level: {100 * within1 / miles:.1f}%.",
        f"* Ours higher than MoCo's: {100 * higher / miles:.1f}%; ours lower: {100 * lower / miles:.1f}%.",
        "",
        "## Confusion matrix",
        "",
        matrix(pairs, [1, 2, 3, 4, 5], labels, "our LTS", "MoCo LTS"),
        "",
        "## By OSM road class",
        "",
        by_class(records, "MoCo"),
        "",
        "## Top 50 disagreements",
        "",
        "Grouped by street and the pair of levels, ranked by miles times the gap. `our rule` is the "
        "classifier's reason for the most of the group's miles.",
        "",
        disagreements(records, 50, "MoCo LTS"),
        "",
    ]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "moco-lts-comparison.md").write_text("\n".join(out))

    # The proposed Avoid file: MoCo's LTS 5 roads, a bicycle may legally ride, that we rate below 5.
    five = [r for r in records if r["theirs"] == 5 and r["ours"] < 5 and r["share"] >= 0.5]
    rows, seen = [], set()
    for r in sorted(five, key=lambda r: r["way"]):
        way = ctx.by_id[r["way"]]
        if way.tags.get("highway") in ("motorway", "motorway_link") or r["way"] in seen:
            continue
        seen.add(r["way"])
        slug = "".join(c if c.isalnum() else "-" for c in (way.name or "unnamed").lower()).strip(
            "-"
        )
        slug = "-".join(part for part in slug.split("-") if part)[:40] or "unnamed"
        rows.append(
            {
                "kind": "stress",
                "osm_way_id": r["way"],
                "value": {
                    "tier": 5,
                    "adjustment_id": f"moco-lts5-{slug}",
                    "category": "other",
                    "visibility": "hidden",
                    "annotation_status": "proposed",
                    "display": "route_only",
                },
                "reason": (
                    "PROPOSED, not loaded. The owner, 2026-09-30 (OWNER-DECISIONS 149): the Montgomery "
                    'Planning layer\'s "LTS5, which we can mark as avoid".'
                ),
                "evidence": (
                    f"Montgomery County Planning, Bicycle Level of Traffic Stress (item "
                    f"fb903d1ffbc84b219bdb47629bd02b82), retrieved 2026-10-01: LTS_EXIST 5 along way "
                    f"{r['way']} ({way.name or 'unnamed'}, highway={way.tags.get('highway')}, "
                    f"{r['miles']:.2f} mi); our tier is {r['ours']} ({r['rule']})."
                ),
            }
        )
    proposed = Path(args.out) / "proposed"
    proposed.mkdir(parents=True, exist_ok=True)
    document = {
        "version": 1,
        "decided": None,
        "decided_by": "PROPOSED for the deployment owner; not approved, not loaded",
        "status": 'proposed (OWNER-DECISIONS 149: "LTS5 ... we can mark as avoid"); needs the owner\'s go before loading',
        "annotations": (
            f"{len(rows)} ways, {sum(r['miles'] for r in five if r['way'] in seen):.1f} mi, where the "
            "county's existing-condition LTS is 5 and ours is below 5. Tier 5 (Avoid), hidden, no public "
            "note, category other, annotation proposed. Motorways are left out (a bicycle may not ride them)."
        ),
        "rows": rows,
    }
    (proposed / "PROPOSED-moco-lts5-avoid.json").write_text(json.dumps(document, indent=1))
    print("moco", len(records), f"{miles:.0f} mi; proposed avoid rows {len(rows)}")


# ---------------------------------------------------------------------------------------
# Arlington (internal)
# ---------------------------------------------------------------------------------------


def arlington(args, ctx: Context) -> None:
    layer = (
        Path(args.datasets)
        / "internal-only"
        / "arlington-bike-comfort-index"
        / "arlington-bike-comfort-index.geojson"
    )
    features, level, dropped, values = [], {}, Counter(), Counter()
    for feature in agency_roads.iter_features(layer):
        p = feature["properties"]
        values[p.get("LTS")] += 1
        text = str(p.get("LTS") or "")
        if p.get("Route_Type") == "Off Street Trail" or text in (
            "LTS 0",
            "Not Applicable",
            "Check",
            "",
        ):
            dropped[text or "none"] += 1
            continue
        lts = int(text.split()[1])
        for part, line in enumerate(lines_of(feature["geometry"])):
            fid = f"arl-{p['OBJECTID']}-{part}"
            features.append(
                conflation.RoadFeature(
                    fid, line, agency_roads.RoadFacts(agency="arlington", name=p.get("STNAME"))
                )
            )
            level[fid] = lts
    result = match(ctx, features)
    records = [r for r in build_records(ctx, result, level.get) if r["state"] == "VA"]
    miles = sum(r["miles"] for r in records)
    pairs = [(r["ours"], r["theirs"], r["miles"]) for r in records]
    exact = sum(r["miles"] for r in records if r["ours"] == r["theirs"])
    within1 = sum(r["miles"] for r in records if abs(r["ours"] - r["theirs"]) <= 1)
    out = [
        "# INTERNAL COMPARISON ONLY: our tier against Arlington's Bike Comfort Index LTS",
        "",
        'Arlington County, Virginia, Department of Environmental Services, "Bike Comfort Index" (ArcGIS item '
        "d0fe44f631c1460089a49ecaa1377fa9), retrieved 2026-10-01. Its licence field is only a pointer to the "
        "county's data disclaimer, so by the owner's decision (items 152, 155) it is consulted for research "
        "and nothing in it is copied into published output, tiles, routes or fixtures. Any correction is "
        "made through our own audited overrides, on the owner's decision.",
        "",
        "Its `LTS` field is compared directly with ours, no mapping. Values on its "
        f"{sum(values.values()):,} records: "
        + ", ".join(f"{k} {v:,}" for k, v in values.most_common())
        + ". Left out: "
        + ", ".join(f"{n:,} {why}" for why, n in dropped.most_common())
        + ".",
        "",
        f"{len(records):,} OSM road ways in Virginia lie along an Arlington road record ({miles:,.0f} mi). "
        f"Same level {100 * exact / miles:.1f}% of miles; within one level {100 * within1 / miles:.1f}%.",
        "",
        "## Confusion matrix",
        "",
        matrix(pairs, [1, 2, 3, 4, 5], [1, 2, 3, 4], "our LTS", "Arlington LTS"),
        "",
        "## By OSM road class",
        "",
        by_class(records, "Arlington"),
        "",
        "## Top 50 disagreements",
        "",
        disagreements(records, 50, "Arlington LTS"),
        "",
    ]
    out_dir = Path(args.out) / "internal"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "arlington-internal-comparison.md").write_text("\n".join(out))
    print("arlington", len(records), f"{miles:.0f} mi")


# ---------------------------------------------------------------------------------------
# Alexandria (internal for Transport Streets; Bike Lane Routes is CC0)
# ---------------------------------------------------------------------------------------


def alexandria(args, ctx: Context) -> None:
    streets = (
        Path(args.datasets)
        / "internal-only"
        / "alexandria-transport-streets"
        / "alexandria-transport-streets.geojson"
    )
    features, info = [], {}
    for feature in agency_roads.iter_features(streets):
        p = feature["properties"]
        if p.get("MTFCC") in (
            "PARKING LOT ROAD",
            "ALLEY",
            "WALKWAY/PEDESTRIAN TRAIL",
            "PRIVATE ROAD FOR SERVICE VEHICLES",
        ):
            continue
        if p.get("SEG_TYPE") in ("DRIVEWAY",):
            continue
        speed = p.get("SPEED_LIMIT")
        speed = (
            speed
            if isinstance(speed, int)
            and agency_roads.MIN_POSTED_MPH <= speed <= agency_roads.MAX_POSTED_MPH
            else None
        )
        for part, line in enumerate(lines_of(feature["geometry"])):
            fid = f"alx-{p['OBJECTID']}-{part}"
            features.append(
                conflation.RoadFeature(
                    fid, line, agency_roads.RoadFacts(agency="alexandria", name=p.get("FULL_NAME"))
                )
            )
            info[fid] = {"speed": speed, "oneway": p.get("ONEWAY") in ("FROM_TO", "TO_FROM")}
    result = match(ctx, features)
    records = []
    total = 0.0
    speed_rows = Counter()
    for way_id, shares in result.matched.items():
        way = ctx.by_id[way_id]
        if not ctx.is_road(way) or ctx.state_of(way.coordinates) != "VA":
            continue
        speeds = [info[s.feature_id]["speed"] for s in shares if info[s.feature_id]["speed"]]
        one = [info[s.feature_id]["oneway"] for s in shares]
        facts = agency_roads.WayFacts(
            agency="alexandria",
            blocks=tuple(s.feature_id for s in shares),
            speed_mph=max(speeds) if speeds else None,
            one_way=all(one) if one else None,
        )
        ours = ctx.classify(way)
        overlaid = agency_roads.overlay(dict(way.tags), facts)
        theirs = ctx.classify(way, overlaid.tags)
        miles = length_m(way.coordinates) / MI
        total += miles
        osm_speed = way.tags.get("maxspeed", "")
        if facts.speed_mph and f"{facts.speed_mph} mph" != osm_speed:
            speed_rows[(osm_speed or "(unposted)", f"{facts.speed_mph} mph")] += miles
        records.append(
            {
                "way": way_id,
                "name": way.name,
                "highway": way.tags.get("highway"),
                "miles": miles,
                "ours": int(ours.tier),
                "rule": ours.rule,
                "theirs": int(theirs.tier),
                "gap": int(ours.tier) - int(theirs.tier),
                "alx_speed": facts.speed_mph,
                "osm_speed": osm_speed,
                "alx_rule": theirs.rule,
            }
        )
    pairs = [(r["ours"], r["theirs"], r["miles"]) for r in records]
    exact = sum(r["miles"] for r in records if r["gap"] == 0)
    # Group for the top list
    groups = defaultdict(
        lambda: {
            "miles": 0.0,
            "ways": [],
            "rule": Counter(),
            "arule": Counter(),
            "osm": Counter(),
            "alx": Counter(),
            "cls": Counter(),
        }
    )
    for r in records:
        if r["gap"] == 0:
            continue
        g = groups[(r["name"] or "(unnamed)", r["ours"], r["theirs"])]
        g["miles"] += r["miles"]
        g["ways"].append(r["way"])
        g["rule"][r["rule"]] += r["miles"]
        g["arule"][r["alx_rule"]] += r["miles"]
        g["osm"][r["osm_speed"] or "(unposted)"] += r["miles"]
        g["alx"][r["alx_speed"]] += r["miles"]
        g["cls"][r["highway"]] += r["miles"]
    ranked = sorted(groups.items(), key=lambda kv: -(kv[1]["miles"] * abs(kv[0][1] - kv[0][2])))
    rows = []
    for n, ((name, ours, theirs), g) in enumerate(ranked[:50], 1):
        rows.append(
            [
                n,
                name,
                g["cls"].most_common(1)[0][0],
                f"{g['miles']:.2f}",
                f"LTS {ours}",
                f"LTS {theirs}",
                g["osm"].most_common(1)[0][0],
                f"{g['alx'].most_common(1)[0][0]} mph" if g["alx"].most_common(1)[0][0] else "-",
                g["rule"].most_common(1)[0][0],
                ", ".join(map(str, g["ways"][:3])),
            ]
        )
    out = [
        "# INTERNAL COMPARISON ONLY: our tier against Alexandria's Transport Streets speed and one-way",
        "",
        'City of Alexandria, VA GIS, "Transport Streets" (ArcGIS item dccf9eda6b6c443b8133abf2542854b1), '
        'retrieved 2026-10-01. Its licence field says only "City of Alexandria, VA GIS", so by the owner\'s '
        "decision (items 153, 155) it is consulted for research and nothing in it is copied into published "
        "output or fixtures. Its fields (checked first): `SPEED_LIMIT` and `ONEWAY` are filled; `LANES` is "
        "empty on all 5,677 records, and the layer carries no LTS.",
        "",
        "So the comparison is of the tier the classifier gives a way with OSM's own tags (ours) against the "
        "tier it gives the same way with Alexandria's posted speed and one-way direction in place of "
        "OSM's and the default (theirs), everything else equal. That isolates what the speeds change.",
        "",
        f"{len(records):,} OSM road ways in Virginia lie along an Alexandria street record ({total:,.0f} mi). "
        f"The tier is the same on {100 * exact / total:.1f}% of the miles.",
        "",
        "## Confusion matrix (ours against the tier with Alexandria's speed and one-way)",
        "",
        matrix(pairs, [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], "our LTS", "with Alexandria's speed LTS"),
        "",
        "## Where Alexandria's posted speed differs from the OSM speed (miles)",
        "",
        table(
            ["OSM maxspeed", "Alexandria", "miles"],
            [[a, b, f"{m:.1f}"] for (a, b), m in speed_rows.most_common(15)],
        ),
        "",
        "## By OSM road class",
        "",
        by_class([dict(r, gap=r["gap"]) for r in records], "Alexandria-speed tier"),
        "",
        "## Top 50 disagreements",
        "",
        table(
            [
                "#",
                "street",
                "OSM class",
                "miles",
                "ours",
                "with Alexandria's speed",
                "OSM speed",
                "Alexandria speed",
                "our rule",
                "example ways",
            ],
            rows,
        ),
        "",
    ]
    out_dir = Path(args.out) / "internal"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "alexandria-internal-comparison.md").write_text("\n".join(out))
    print("alexandria transport streets", len(records), f"{total:.0f} mi")

    # -- Bike Lane Routes (CC0): OSM ways that lack a lane the city records
    lanes_layer = (
        Path(args.datasets) / "alexandria-bike-lane-routes" / "alexandria-bike-lane-routes.geojson"
    )
    lane_features, lane_kind, kinds = [], {}, Counter()
    for feature in agency_roads.iter_features(lanes_layer):
        p = feature["properties"]
        kind = p.get("BikeLaneTy")
        kinds[kind] += 1
        if kind not in ("Route Bike Lanes", "Route Climbing Lanes", "Route Shared Lane"):
            continue
        for part, line in enumerate(lines_of(feature["geometry"])):
            fid = f"alxbl-{p['FID']}-{part}"
            lane_features.append(
                conflation.RoadFeature(
                    fid,
                    line,
                    agency_roads.RoadFacts(agency="alexandria-bike", name=p.get("RouteName")),
                )
            )
            lane_kind[fid] = kind
    lane_result = match(ctx, lane_features)
    missing = defaultdict(lambda: {"miles": 0.0, "ways": []})
    present = 0.0
    for way_id, shares in lane_result.matched.items():
        way = ctx.by_id[way_id]
        if not ctx.is_road(way) or ctx.state_of(way.coordinates) != "VA":
            continue
        kind = lane_kind[shares[0].feature_id]
        has = any(
            v in ("lane", "track", "opposite_lane", "buffered_lane", "shared_lane", "share_busway")
            for k, v in way.tags.items()
            if k.startswith("cycleway") and not k.endswith(("width", "buffer"))
        )
        miles = length_m(way.coordinates) / MI
        if has:
            present += miles
            continue
        m = missing[(way.name or "(unnamed)", kind)]
        m["miles"] += miles
        m["ways"].append(way_id)
    lane_rows = [
        [name, kind, f"{m['miles']:.2f}", len(m["ways"]), ", ".join(map(str, m["ways"][:4]))]
        for (name, kind), m in sorted(missing.items(), key=lambda kv: -kv[1]["miles"])[:60]
    ]
    out = [
        "# Alexandria Bike Lane Routes against OSM's bike lanes",
        "",
        'City of Alexandria, VA GIS, "Bike Lane Routes" (ArcGIS item 74341781de91444a8f03620efc5c0514), '
        "licence cc0, retrieved 2026-10-01. Record types: "
        + ", ".join(f"{k} {v}" for k, v in kinds.most_common())
        + ".",
        "",
        f"OSM road ways that lie along a city lane, shared-lane or climbing-lane route: those that already "
        f"carry a `cycleway` lane, track or shared-lane tag total {present:.1f} mi; those that carry none, "
        f"and so are candidates for a missed facility, are below (grouped by street and record type; "
        f"`Route Shared Lane` is a sharrow, which the classifier does not credit).",
        "",
        table(["street", "city record", "miles", "ways", "example ways"], lane_rows),
        "",
    ]
    (Path(args.out) / "alexandria-bike-lanes-check.md").write_text("\n".join(out))
    print("alexandria bike lanes: present", f"{present:.1f}", "missing groups", len(missing))


# ---------------------------------------------------------------------------------------
# Baltimore facilities
# ---------------------------------------------------------------------------------------

BALTIMORE_EXPECTED = {
    "Bike Lane": "lane",
    "Buffered Bike Lane": "lane",
    "Separated Bike Lane": "track",
    "Contraflow Bike Lane": "opposite_lane",
    "Shared Lane Markings": "shared_lane",
    "Shared Bus-Bike Lane": "share_busway",
    "Bike Boulevard": "route",
    "Signed Bike Route": "route",
    "Path or Sidepath": "path",
}
LANE_VALUES = {"lane", "opposite_lane", "buffered_lane"}
TRACK_VALUES = {"track", "opposite_track"}


def osm_cycleway_values(tags) -> set[str]:
    return {
        v
        for k, v in tags.items()
        if k.startswith("cycleway") and not k.endswith(("width", "buffer", "separate"))
    }


def baltimore(args, ctx: Context) -> None:
    base = Path(args.datasets)
    facilities = base / "baltimore-bike-facilities" / "baltimore-bike-facilities.geojson"
    trails = base / "baltimore-multiuse-trails" / "baltimore-multiuse-trails.geojson"

    fac_features, fac_kind, counts = [], {}, Counter()
    for feature in agency_roads.iter_features(facilities):
        p = feature["properties"]
        if p.get("STATUS1") != 4:
            continue
        kind = p["FAC_TYPE1"]
        kind2 = p.get("FAC_TYPE2")
        for part, line in enumerate(lines_of(feature["geometry"])):
            fid = f"balfac-{p['OBJECTID']}-{part}"
            fac_features.append(
                conflation.RoadFeature(
                    fid,
                    line,
                    agency_roads.RoadFacts(agency="baltimore-facility", name=p.get("ST_NAME")),
                )
            )
            # FAC_SIDE: 2 is a facility on both sides of the street, 1 on one.
            fac_kind[fid] = (kind, kind2, p.get("ST_NAME"), p.get("OBJECTID"), p.get("FAC_SIDE"))
            counts[kind] += length_m(line) / MI

    # Road facilities: match against the OSM *road* ways.
    result = match(
        ctx, [f for f in fac_features if fac_kind[f.feature_id][0] != "Path or Sidepath"]
    )
    candidates, present = [], defaultdict(float)
    for way_id, shares in result.matched.items():
        way = ctx.by_id[way_id]
        if not ctx.is_road(way):
            continue
        kind, kind2, street, oid, side = fac_kind[shares[0].feature_id]
        if way.tags.get("highway") in ("motorway", "motorway_link"):
            continue  # a bicycle may not ride it; the match is a neighbouring ramp
        expected = BALTIMORE_EXPECTED[kind]
        have = osm_cycleway_values(way.tags)
        miles = length_m(way.coordinates) / MI
        ok = (
            (expected == "lane" and have & (LANE_VALUES | TRACK_VALUES))
            or (
                expected == "track"
                and (
                    have & TRACK_VALUES
                    or any(v == "separate" for k, v in way.tags.items() if k.startswith("cycleway"))
                )
            )
            or (
                expected == "opposite_lane"
                and have & {"opposite_lane", "opposite_track", "lane", "track"}
            )
            or (
                expected in ("shared_lane", "share_busway")
                and have & {"shared_lane", "share_busway", "lane", "track"}
            )
            or expected == "route"
        )
        if ok:
            present[kind] += miles
            continue
        candidates.append(
            {
                "way": way_id,
                "street": street or way.name or "(unnamed)",
                "osm_name": way.name,
                "kind": kind,
                "expected": expected,
                "have": ",".join(sorted(have)) or "none",
                "highway": way.tags.get("highway"),
                "miles": miles,
                "tier": int(ctx.classify(way).tier),
                "rule": ctx.classify(way).rule,
                "oid": oid,
                "side": side,
            }
        )

    # Paths and sidepaths, and the multiuse trails: match against trail-class OSM ways too.
    path_features = [f for f in fac_features if fac_kind[f.feature_id][0] == "Path or Sidepath"]
    trail_features, trail_info = [], {}
    for feature in agency_roads.iter_features(trails):
        p = feature["properties"]
        for part, line in enumerate(lines_of(feature["geometry"])):
            fid = f"baltrail-{p['OBJECTID']}-{part}"
            trail_features.append(
                conflation.RoadFeature(
                    fid,
                    line,
                    agency_roads.RoadFacts(agency="baltimore-trail", name=p.get("trailName")),
                )
            )
            trail_info[fid] = (p.get("trailName"), p.get("surfaceType"), p.get("bikeFacility"))

    def trail_candidates(features, label_of):
        """OSM ways of any class near the line, matched with trails allowed."""
        entries = [(w.osm_id, w.coordinates, False) for w in ctx.ways]
        res = conflation.conflate_blocks(entries, features, None)
        out = []
        for way_id, shares in res.matched.items():
            way = ctx.by_id[way_id]
            out.append((way, shares, label_of(shares[0].feature_id)))
        return out, res

    def bicycle_ok(tags) -> bool:
        return tags.get("bicycle") in ("yes", "designated", "permissive") or tags.get(
            "highway"
        ) in ("cycleway",)

    access_rows = []
    missing_paths = []
    for label, features, label_of in (
        ("Path or Sidepath", path_features, lambda f: fac_kind[f][2] or "(unnamed)"),
        ("Multiuse trail", trail_features, lambda f: trail_info[f][0] or "(unnamed)"),
    ):
        found, res = trail_candidates(features, label_of)
        by_feature_cover = defaultdict(float)
        for way, shares, street in found:
            hw = way.tags.get("highway")
            miles = length_m(way.coordinates) / MI
            if hw in (
                "footway",
                "path",
                "pedestrian",
                "steps",
                "cycleway",
                "track",
                "service",
            ) and way.tags.get("access") not in ("no", "private"):
                for s in shares:
                    by_feature_cover[s.feature_id] += s.share
                # A way the city's line lies along for most of its length, long enough to be a
                # stretch of path (not a curb ramp or a stair landing), that OSM says nothing
                # about for bicycles: a mapper's `no` or `dismount` is a decision, left alone.
                if (
                    hw in ("footway", "path", "pedestrian")
                    and not bicycle_ok(way.tags)
                    and way.tags.get("bicycle") not in ("no", "dismount")
                    and way.tags.get("footway")
                    not in ("crossing", "access_aisle", "traffic_island")
                    and shares[0].share >= 0.8
                    and miles * MI >= 15.0
                ):
                    access_rows.append(
                        {
                            "way": way.osm_id,
                            "street": street,
                            "label": label,
                            "highway": hw,
                            "bicycle": way.tags.get("bicycle", "(no tag)"),
                            "footway": way.tags.get("footway", ""),
                            "miles": miles,
                        }
                    )
        for feature in features:
            if by_feature_cover.get(feature.feature_id, 0) < 0.5:
                missing_paths.append(
                    {
                        "label": label,
                        "street": label_of(feature.feature_id),
                        "miles": length_m(feature.coordinates) / MI,
                        "id": feature.feature_id,
                    }
                )

    # Which OSM roads' tiers would change if the city's facility were tagged.
    proposals = []
    for c in candidates:
        if c["expected"] not in ("lane", "track", "opposite_lane"):
            continue
        way = ctx.by_id[c["way"]]
        tags = dict(way.tags)
        value = "track" if c["expected"] == "track" else "lane"
        # On both sides where the city records both (FAC_SIDE 2), else on one: on a
        # two-way street a facility on one side earns nothing, on a one-way it does.
        side = "both" if c["side"] == 2 else "right"
        if c["expected"] == "opposite_lane":
            tags["cycleway:left"] = "opposite_lane"
        else:
            tags[f"cycleway:{side}"] = value
        if c["kind"] == "Buffered Bike Lane":
            tags[f"cycleway:{side}:buffer"] = "yes"
        new = ctx.classify(way, tags)
        c["tier_with"] = int(new.tier)
        c["rule_with"] = new.rule
        if int(new.tier) < c["tier"]:
            proposals.append(c)

    out = [
        "# Baltimore: the city's bike facilities and trails against OSM",
        "",
        "Sources, all open-licensed by Baltimore City Code Art. 1 s.9-1(h) (OWNER-DECISIONS 159), credit "
        '"City of Baltimore, Open Baltimore": DOT BMC Bike Facilities (item dbef46a0caf948debba8516f0d95fe4c; '
        f"{sum(counts.values()):.0f} mi of existing facilities, `STATUS1` 4) and Multiuse Trails (item "
        "34260bfb3df74d3994e0c73fde47630b; proposed trails, `mainSpur` of Future Alignment, were excluded at "
        "the query). Retrieved 2026-10-01.",
        "",
        "## Facilities the city records on roads, and what OSM has on the matched way",
        "",
        table(
            ["city facility type", "city miles", "OSM way already tagged", "candidates (miles)"],
            [
                [
                    k,
                    f"{counts[k]:.1f}",
                    "(a separate way; checked below)"
                    if k == "Path or Sidepath"
                    else f"{present.get(k, 0):.1f} mi",
                    f"{sum(c['miles'] for c in candidates if c['kind'] == k):.1f}",
                ]
                for k in sorted(counts, key=lambda k: -counts[k])
            ],
        ),
        "",
        "A *candidate* is an OSM road way lying along a city facility whose own tags carry no cycleway of the "
        "kind the city records (a lane for a bike lane, buffered lane or contraflow lane; a track or a "
        "`cycleway=separate` for a separated lane). `Signed Bike Route` and `Bike Boulevard` are routes, "
        "which OSM carries on relations and the classifier does not credit, so they are not candidates. "
        "`Path or Sidepath` is a separate way and is checked below.",
        "",
        "### Roads whose bike lane or track OSM lacks (top 60 by miles)",
        "",
        table(
            [
                "street",
                "city facility",
                "OSM class",
                "OSM cycleway",
                "miles",
                "our tier",
                "tier with the facility",
                "ways",
            ],
            [
                [
                    street,
                    kind,
                    klass,
                    have,
                    f"{miles:.2f}",
                    f"LTS {tier}",
                    f"LTS {tier_with}" if tier_with is not None else "-",
                    ", ".join(map(str, ways[:3])),
                ]
                for (street, kind, klass, have, tier, tier_with), (miles, ways) in sorted(
                    (
                        (
                            key,
                            (sum(c["miles"] for c in group), [c["way"] for c in group]),
                        )
                        for key, group in _group(candidates).items()
                    ),
                    key=lambda kv: -kv[1][0],
                )[:60]
            ],
        ),
        "",
        f"{len(candidates)} OSM ways ({sum(c['miles'] for c in candidates):.1f} mi) in all; "
        f"{len(proposals)} of them ({sum(c['miles'] for c in proposals):.1f} mi) would be rated lower "
        "with the facility tagged, and are in the proposed override file.",
        "",
        "## Paths, sidepaths and multiuse trails",
        "",
        f"City path and trail lines with no OSM way along at least half of them (candidate missing paths): "
        f"{len(missing_paths)} lines, {sum(m['miles'] for m in missing_paths):.1f} mi.",
        "",
        table(
            ["layer", "street or trail", "miles"],
            [
                [m["label"], m["street"], f"{m['miles']:.2f}"]
                for m in sorted(missing_paths, key=lambda m: -m["miles"])[:40]
            ],
        ),
        "",
        f"OSM footways and paths that lie along a city path or trail and carry no bicycle permission "
        f"(`bicycle` is not yes, designated or permissive, and not a mapper's `no` or `dismount`), lying along "
        f"the city line for at least 80% of their length and at least 15 m long: {len({a['way'] for a in access_rows})} ways, "
        f"{sum(a['miles'] for a in {a['way']: a for a in access_rows}.values()):.1f} mi. The Veirs Mill case "
        "(OWNER-DECISIONS 115) was this: a paved sidepath mapped as a sidewalk. They are in the proposed file "
        "as `bicycle=designated` access rows.",
        "",
        table(
            ["street or trail", "city layer", "OSM class", "OSM bicycle", "miles", "way"],
            [
                [
                    a["street"],
                    a["label"],
                    a["highway"] + (f" ({a['footway']})" if a["footway"] else ""),
                    a["bicycle"],
                    f"{a['miles']:.2f}",
                    a["way"],
                ]
                for a in sorted(
                    {a["way"]: a for a in access_rows}.values(), key=lambda a: -a["miles"]
                )[:40]
            ],
        ),
        "",
    ]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "baltimore-facility-candidates.md").write_text("\n".join(out))
    with (out_dir / "baltimore-facility-candidates.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "osm_way_id",
                "street",
                "city_facility",
                "osm_highway",
                "osm_cycleway",
                "miles",
                "tier",
                "tier_with_facility",
                "rule",
            ]
        )
        for c in sorted(candidates, key=lambda c: (c["street"], c["way"])):
            writer.writerow(
                [
                    c["way"],
                    c["street"],
                    c["kind"],
                    c["highway"],
                    c["have"],
                    f"{c['miles']:.3f}",
                    c["tier"],
                    c.get("tier_with", ""),
                    c["rule"],
                ]
            )

    # The proposed override file: stress rows for the roads, access rows for the sidepaths.
    rows = []
    for c in sorted(proposals, key=lambda c: c["way"]):
        slug = "-".join(
            part
            for part in "".join(ch if ch.isalnum() else "-" for ch in c["street"].lower()).split(
                "-"
            )
            if part
        )[:40]
        rows.append(
            {
                "kind": "stress",
                "osm_way_id": c["way"],
                "value": {
                    "tier": c["tier_with"],
                    "adjustment_id": f"baltimore-{c['expected']}-{slug or 'unnamed'}-lts{c['tier_with']}"[
                        :64
                    ],
                    "category": "other",
                    "visibility": "hidden",
                    "annotation_status": "proposed",
                    "display": "route_only",
                },
                "reason": (
                    "PROPOSED, not loaded. The City of Baltimore's DOT records a "
                    f"{c['kind'].lower()} on this street that OSM does not carry; the tier is what the classifier "
                    "gives with the facility tagged. The durable fix is the OSM edit."
                ),
                "evidence": (
                    f"Open Baltimore, DOT BMC Bike Facilities (item dbef46a0caf948debba8516f0d95fe4c), retrieved "
                    f"2026-10-01: {c['kind']} on {c['street']} (record {c['oid']}); OSM way {c['way']} "
                    f"(highway={c['highway']}, cycleway {c['have']}), {c['miles']:.2f} mi; tier now {c['tier']}."
                ),
            }
        )
    access = []
    for a in sorted({a["way"]: a for a in access_rows}.values(), key=lambda a: a["way"]):
        access.append(
            {
                "kind": "access",
                "osm_way_id": a["way"],
                "value": {"bicycle": "designated"},
                "reason": (
                    "PROPOSED, not loaded. The City of Baltimore records a path or multiuse trail along this way "
                    "and OSM tags it without bicycle access; the same correction as the Veirs Mill sidepath."
                ),
                "evidence": (
                    f"Open Baltimore ({a['label']}): {a['street']}; OSM way {a['way']} highway={a['highway']}, "
                    f"bicycle={a['bicycle']}, {a['miles']:.2f} mi."
                ),
            }
        )
    proposed = out_dir / "proposed"
    proposed.mkdir(exist_ok=True)
    (proposed / "PROPOSED-baltimore-facilities.json").write_text(
        json.dumps(
            {
                "version": 1,
                "decided": None,
                "decided_by": "PROPOSED for the deployment owner; not approved, not loaded",
                "status": "proposed; needs the owner's go before loading. OSM edits upstream are the durable fix.",
                "annotations": (
                    f"{len(rows)} stress rows (roads whose city bike lane or track OSM lacks, tier from the "
                    f"classifier with the facility tagged, hidden, no public note) and {len(access)} access rows "
                    "(bicycle=designated on footways and paths the city records as paths or trails)."
                ),
                "rows": rows + access,
            },
            indent=1,
        )
    )
    print(
        "baltimore candidates",
        len(candidates),
        "proposals",
        len(proposals),
        "access",
        len(access),
        "missing paths",
        len(missing_paths),
    )


def _group(candidates):
    groups = defaultdict(list)
    for c in candidates:
        groups[
            (c["street"], c["kind"], c["highway"], c["have"], c["tier"], c.get("tier_with"))
        ].append(c)
    return groups


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", choices=["moco", "arlington", "alexandria", "baltimore"])
    parser.add_argument("--datasets", required=True)
    parser.add_argument("--ways-dir", required=True)
    parser.add_argument("--state-polygons", required=True)
    parser.add_argument("--urban", required=True)
    parser.add_argument("--live-ways", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    ctx = Context(args, args.dataset)
    print("context", len(ctx.ways), "ways", f"{time.monotonic() - started:.0f}s", flush=True)
    {"moco": moco, "arlington": arlington, "alexandria": alexandria, "baltimore": baltimore}[
        args.dataset
    ](args, ctx)
    print(f"{time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
