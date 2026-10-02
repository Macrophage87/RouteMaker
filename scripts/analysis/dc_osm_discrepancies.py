#!/usr/bin/env python3
# ruff: noqa: E501 - table rows run long
"""Where DC's Roadway Block and OSM disagree about a District way, for the owner to review.

    python scripts/analysis/dc_osm_discrepancies.py --dcbal out/dcbal.tsv \\
        --out reports/data-comparison

`dcbal.tsv` is `data_before_after.py`'s output, made from the same extract and roadway.json the
rebuild reads, so this is regenerated with the before-after report after each rebuild
(docs/DEVELOPMENT.md, "Agency street layers"). Writes `dc-osm-discrepancies.md` and
`dc-osm-discrepancies.csv`.

OWNER-DECISIONS 190 ("DC data takes priority over OSM. It's updated regularly.") and 191 ("DC roads
and especially bike infrastructure changes quite frequently, so it's likely OSM data is stale.
However, report the discrepancies when you see them."): the District's value is what the classifier
reads, except where a block cannot speak for one of its ways (`routemaker.agency_roads.overlay`);
those are listed as "not applied" with the reason.
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

from routemaker.agency_roads import osm_side_ranks  # noqa: E402
from routemaker.tags import is_oneway, lanes_per_direction, parse_maxspeed_mph  # noqa: E402

MI = 1609.344
FT_PER_M = 3.28084
TOP = 25
KINDS = {1: "painted lane", 2: "buffered lane", 3: "protected lane"}
TYPES = (
    ("presence", "Bike facility present or absent"),
    ("kind", "Facility kind (painted, buffered, protected)"),
    ("contraflow", "Contraflow lane"),
    ("oneway", "One-way"),
    ("lanes", "Through lanes per direction"),
    ("speed", "Posted speed"),
)


def _json(raw: str) -> dict:
    return json.loads(raw) if raw else {}


def _rank(tags: dict) -> int:
    return max(osm_side_ranks(tags).values(), default=0)


def _osm_bike(tags: dict) -> str:
    found = [
        f"{k}={v}"
        for k, v in sorted(tags.items())
        if k.startswith("cycleway") and not k.endswith(("width", "buffer"))
    ]
    return ", ".join(found) or "no cycleway tag"


def _dc_bike(facts: dict) -> str:
    by_label = facts.get("bike") or {}
    if by_label:
        return ", ".join(
            f"{KINDS.get(rank, rank)} ({label.upper()})" for label, rank in sorted(by_label.items())
        )
    if facts.get("bike_recorded"):
        return "a lane on some of the way's blocks only"
    return "none recorded"


def _separate(tags: dict) -> bool:
    return any(v == "separate" for k, v in tags.items() if k.startswith("cycleway"))


def _contraflow(tags: dict) -> bool:
    return any(str(v).startswith("opposite") for k, v in tags.items() if k.startswith("cycleway"))


def _reason(disagree: str, agree: str, kind: str, own_separate: bool = False) -> str:
    """Why the District's value was not applied (OWNER-DECISIONS 190's exceptions)."""
    if kind in ("presence", "kind", "contraflow"):
        if own_separate:
            return "separate: OSM maps a facility as its own way beside the road; DC records none"
        if "separate way" in agree:
            return "separate: OSM maps the facility as its own way beside the road or its other carriageway"
        if "OSM says none on the road" in disagree:
            return "OSM says bicycle=no, use_sidepath or cycleway=no"
        if "OSM has a track" in disagree:
            return "OSM's track on the road kept"
        if "OSM has one, the agency records none" in disagree:
            return "DC's blocks differ along the way (a lane on some)"
        return "carriageway: the other direction's lane, or no contraflow flag"
    if kind == "oneway":
        for part in disagree.split("; "):
            if part.startswith("oneway:") and "kept (" in part:
                return part.split("kept (", 1)[1].rstrip(")")
        return "outside the rule"
    if kind == "lanes":
        if "one direction of a two-way way" in disagree:
            return "DC records one direction of a two-way way"
        return "slip road: its own lanes"
    return "not applied"


def items(rows):
    """One record per (way, type) where the District and OSM disagree."""
    for r in rows:
        osm, after, facts = _json(r["tags"]), _json(r["tags1"]), _json(r["facts"])
        sources = _json(r["sources"])
        base = {
            "way": int(r["way"]),
            "street": r["name"] or "(unnamed)",
            "highway": r["highway"],
            "m": int(r["m"]),
            "blocks": r["blocks"],
            "tier0": int(r["tier0"]),
            "tier1": int(r["tier1"]),
            "disagree": r["disagree"],
            "agree": r["agree"],
        }
        osm_rank, after_rank = _rank(osm), _rank(after)
        dc_rank = max(
            [
                *(facts.get("bike") or {}).values(),
                facts.get("bike_fwd") or 0,
                facts.get("bike_back") or 0,
            ]
        )
        dc_has = bool(facts.get("bike_recorded") or dc_rank)
        # A way OSM itself marks `cycleway*=separate` records the facility, as a way of its own:
        # that agrees with the District and is not listed.
        own_separate = _separate(osm)
        if (osm_rank > 0 or own_separate) != dc_has:
            yield {
                **base,
                "type": "presence",
                "osm": _osm_bike(osm),
                "dc": _dc_bike(facts),
                "applied": (after_rank > 0 or _separate(after)) == dc_has,
                "own_separate": own_separate,
            }
        elif osm_rank and dc_rank and osm_rank != dc_rank:
            yield {
                **base,
                "type": "kind",
                "osm": f"{KINDS[osm_rank]} ({_osm_bike(osm)})",
                "dc": _dc_bike(facts),
                "applied": after_rank == dc_rank,
            }
        dc_contra = bool(facts.get("contraflow"))
        if _contraflow(osm) != dc_contra and (dc_contra or dc_has):
            yield {
                **base,
                "type": "contraflow",
                "osm": _osm_bike(osm),
                "dc": "contraflow lane flagged" if dc_contra else "no contraflow flag",
                "applied": _contraflow(after) == dc_contra,
            }
        one_way = facts.get("one_way")
        if one_way is not None and one_way != is_oneway(osm):
            osm_value = osm.get("oneway") or (
                "lanes counted each way" if "lanes:forward" in osm else "not tagged (two-way)"
            )
            yield {
                **base,
                "type": "oneway",
                "osm": f"oneway={osm_value}" if "oneway" in osm else osm_value,
                "dc": "one-way" if one_way else "two-way",
                "applied": is_oneway(after) == one_way,
            }
        osm_lanes = lanes_per_direction(osm)
        if sources.get("lanes") == "dc-roadway-block":
            dc_lanes, applied = lanes_per_direction(after), True
        else:
            dc_lanes, applied = facts.get("lanes_per_dir"), False
        if osm_lanes is not None and dc_lanes is not None and osm_lanes != dc_lanes:
            yield {
                **base,
                "type": "lanes",
                "osm": f"{osm_lanes} a direction",
                "dc": f"{dc_lanes} a direction",
                "applied": applied,
            }
        osm_speed, dc_speed = parse_maxspeed_mph(osm.get("maxspeed")), facts.get("speed_mph")
        if osm_speed is not None and dc_speed is not None and round(osm_speed) != dc_speed:
            yield {
                **base,
                "type": "speed",
                "osm": f"{osm_speed:g} mph",
                "dc": f"{dc_speed} mph",
                "applied": parse_maxspeed_mph(after.get("maxspeed")) == dc_speed,
            }


def link(way: int) -> str:
    return f"[{way}](https://www.openstreetmap.org/way/{way})"


def tier_text(item: dict) -> str:
    if not item["applied"]:
        return f"LTS {item['tier1']} (not applied)"
    if item["tier0"] == item["tier1"]:
        return f"LTS {item['tier1']} (no change)"
    return f"LTS {item['tier0']} to {item['tier1']}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dcbal", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    csv.field_size_limit(10**9)
    with args.dcbal.open() as handle:
        rows = [
            r
            for r in csv.DictReader(handle, delimiter="\t")
            if r["region"] == "dc" and r["state"] == "DC" and r["matched"] == "1"
        ]
    found = list(items(rows))
    for item in found:
        item["reason"] = (
            ""
            if item["applied"]
            else _reason(
                item["disagree"], item["agree"], item["type"], item.get("own_separate", False)
            )
        )
    by_type = defaultdict(list)
    for item in found:
        by_type[item["type"]].append(item)

    def miles(group) -> float:
        return sum(i["m"] for i in group) / MI

    out = [
        "# DC Roadway Block against OSM: where they disagree",
        "",
        "For the owner's review (OWNER-DECISIONS 191: \"DC roads and especially bike infrastructure changes "
        "quite frequently, so it's likely OSM data is stale. However, report the discrepancies when you see "
        "them.\"). Every District road way a Roadway Block was matched to, where the block's record and the "
        "way's OSM tags say different things. The District's value is what the classifier reads "
        "(OWNER-DECISIONS 190) except where a block, which describes the whole road, cannot speak for one of "
        "its ways; those are listed as **not applied**, with the reason. Regenerated from `dcbal.tsv` "
        "(`scripts/analysis/data_before_after.py`) with the before-after report after each rebuild; every row "
        "is in `dc-osm-discrepancies.csv`.",
        "",
        "Nothing here is for importing into OSM: the Roadway Block is CC BY 4.0, and copying its values into "
        "OSM (ODbL) would need a licence waiver from the District.",
        "",
        f"{len(rows):,} matched District ways ({miles([{'m': int(r['m'])} for r in rows]):,.0f} mi). A way can "
        "appear under several types. Tiers are the way's tier with OSM's tags alone and with the District's "
        "record applied (all of it, not only this attribute). Where OSM has no value (no `maxspeed`, no `lanes`) "
        "the District's fills it, and that is not counted here.",
        "",
        "| type | ways | miles | applied: ways | applied: miles | not applied: ways | not applied: miles | applied, tier changed: ways |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, label in TYPES:
        group = by_type.get(key, [])
        applied = [i for i in group if i["applied"]]
        kept = [i for i in group if not i["applied"]]
        moved = [i for i in applied if i["tier0"] != i["tier1"]]
        out.append(
            f"| {label} | {len(group):,} | {miles(group):,.1f} | {len(applied):,} | {miles(applied):,.1f} | "
            f"{len(kept):,} | {miles(kept):,.1f} | {len(moved):,} |"
        )
    out += ["", "## Not applied (OWNER-DECISIONS 190 exceptions)", ""]
    reasons = Counter()
    reason_miles = Counter()
    for item in found:
        if not item["applied"]:
            reasons[(item["type"], item["reason"])] += 1
            reason_miles[(item["type"], item["reason"])] += item["m"] / MI
    out += ["| type | reason | ways | miles |", "| --- | --- | --- | --- |"]
    out += [
        f"| {dict(TYPES)[t]} | {reason} | {n:,} | {reason_miles[(t, reason)]:,.1f} |"
        for (t, reason), n in sorted(reasons.items(), key=lambda kv: -kv[1])
    ]
    out.append("")
    header = "| street | OSM way | DC block | length | OSM | DC | tier | applied |"
    for key, label in TYPES:
        group = sorted(by_type.get(key, []), key=lambda i: (-i["m"], i["way"]))
        for applied_label, chosen in (
            ("applied", [i for i in group if i["applied"]]),
            ("not applied", [i for i in group if not i["applied"]]),
        ):
            if not chosen:
                continue
            out += [
                f"## {label}: {applied_label}, the {min(TOP, len(chosen))} longest of {len(chosen):,}",
                "",
                header,
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            for i in chosen[:TOP]:
                blocks = i["blocks"].split(",")
                block = blocks[0] + (f" (+{len(blocks) - 1})" if len(blocks) > 1 else "")
                feet = i["m"] * FT_PER_M
                length = (
                    f"{feet:,.0f} ft [{i['m']:,} m]"
                    if feet < 1000
                    else f"{i['m'] / MI:.2f} mi [{i['m']:,} m]"
                )
                status = "yes" if i["applied"] else f"no: {i['reason']}"
                out.append(
                    f"| {i['street']} | {link(i['way'])} | {block} | {length} | {i['osm']} | {i['dc']} | {tier_text(i)} | {status} |"
                )
            out.append("")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "dc-osm-discrepancies.md").write_text("\n".join(out))
    with (args.out / "dc-osm-discrepancies.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "type",
                "osm_way_id",
                "osm_url",
                "street",
                "highway",
                "miles",
                "dc_blocks",
                "osm_value",
                "dc_value",
                "applied",
                "not_applied_reason",
                "tier_osm_only",
                "tier_with_dc",
            ]
        )
        for i in sorted(found, key=lambda i: (i["type"], -i["m"], i["way"])):
            writer.writerow(
                [
                    i["type"],
                    i["way"],
                    f"https://www.openstreetmap.org/way/{i['way']}",
                    i["street"],
                    i["highway"],
                    f"{i['m'] / MI:.3f}",
                    i["blocks"],
                    i["osm"],
                    i["dc"],
                    int(i["applied"]),
                    i["reason"],
                    i["tier0"],
                    i["tier1"],
                ]
            )
    print("discrepancies", len(found), dict(Counter(i["type"] for i in found)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
