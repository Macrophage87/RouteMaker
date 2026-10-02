# ruff: noqa: E501 - table rows run long
"""Where DC's Roadway Block and OSM disagree about a District way, for the owner to review.

OWNER-DECISIONS 190 ("DC data takes priority over OSM. It's updated regularly.") and 191 ("DC roads
and especially bike infrastructure changes quite frequently, so it's likely OSM data is stale.
However, report the discrepancies when you see them."): the District's value is what the classifier
reads, except where a block cannot speak for one of its ways (`routemaker.agency_roads.overlay`) or
the owner has withheld it (item 197); those are "not applied", with the reason.

Each rebuild writes the report (`pipeline.run`'s classification stage, `write_report`) to
`<DATA_ROOT>/rebuild/reports/`, from the overlay it classified with. The copy checked in under
`reports/data-comparison/` is written by `scripts/analysis/dc_osm_discrepancies.py` from
`data_before_after.py`'s `dcbal.tsv`; both go through `items` and `write_report`, from rows of
the one shape (`row`).
"""

from __future__ import annotations

import csv
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

from routemaker.agency_roads import OWNER_OVERRIDE, WayFacts, osm_side_ranks
from routemaker.tags import is_oneway, lanes_per_direction, parse_maxspeed_mph

MI = 1609.344
FT_PER_M = 3.28084
# How many of the longest applied items each type lists; every item is in the CSV.
TOP = 25
# How many of the longest ways each not-applied reason names as examples.
EXAMPLES = 3
KINDS = {1: "painted lane", 2: "buffered lane", 3: "protected lane"}
TYPES = (
    ("presence", "Bike facility present or absent"),
    ("kind", "Facility kind (painted, buffered, protected)"),
    ("contraflow", "Contraflow lane"),
    ("oneway", "One-way"),
    ("lanes", "Through lanes per direction"),
    ("speed", "Posted speed"),
)
# The road classes a report row is never made for (`data_before_after.SKIP`).
NOT_ROADS = frozenset({"proposed", "construction", "platform", "corridor"})
# The tag keys a row keeps of the way's OSM tags and of what the classifier read.
REPORTED_KEYS = ("maxspeed", "lanes", "oneway", "cycleway", "parking")
# What the report says about where it came from.
REBUILD_SOURCE = (
    "Written by the rebuild, from the overlay it classified with, to `<DATA_ROOT>/rebuild/reports/`; "
    "the copy in reports/data-comparison/ is written from `dcbal.tsv` by "
    "`scripts/analysis/dc_osm_discrepancies.py`."
)
MD_NAME = "dc-osm-discrepancies.md"
CSV_NAME = "dc-osm-discrepancies.csv"
CSV_HEADER = (
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
)


def reported_tags(tags: Mapping[str, str]) -> dict[str, str]:
    """The tags a report row keeps: speed, lanes, one-way, cycleway, parking."""
    return {k: v for k, v in tags.items() if k.startswith(REPORTED_KEYS)}


def facts_summary(facts: WayFacts) -> dict:
    """What a row keeps of the blocks' facts (`dcbal.tsv`'s `facts` column)."""
    return {
        "speed": facts.speed_by_direction,
        "lanes": facts.lanes_by_direction,
        "lanes_fwd": facts.lanes_forward,
        "lanes_back": facts.lanes_backward,
        "one_way": facts.one_way,
        "oneway_fwd": facts.oneway_forward,
        "lanes_per_dir": facts.lanes_per_direction,
        "speed_mph": facts.speed_mph,
        "speed_withheld": facts.speed_withheld_mph,
        "contraflow": facts.contraflow,
        "bike_recorded": facts.bike_recorded,
        "bike": facts.bike,
        "bike_fwd": facts.bike_forward,
        "bike_back": facts.bike_backward,
        "bike_ft": facts.bike_width_ft,
        "parking": facts.parking_lanes,
        "aadt": facts.aadt,
    }


def row(
    *,
    way: int,
    name: str | None,
    highway: str,
    length_m: float,
    blocks: Iterable[str],
    tier0: int,
    tier1: int,
    disagreements: Iterable[str],
    agreements: Iterable[str],
    osm: Mapping[str, str],
    after: Mapping[str, str],
    facts: Mapping,
    sources: Mapping[str, str],
) -> dict:
    """One matched District way, as `items` reads it."""
    return {
        "way": int(way),
        "street": (name or "").replace("\t", " ") or "(unnamed)",
        "highway": highway,
        "m": round(length_m),
        "blocks": ",".join(list(blocks)[:6]),
        "tier0": int(tier0),
        "tier1": int(tier1),
        "disagree": "; ".join(disagreements),
        "agree": "; ".join(agreements),
        "osm": reported_tags(osm),
        "after": reported_tags(after),
        "facts": dict(facts),
        "sources": dict(sources),
    }


def _rank(tags: Mapping[str, str]) -> int:
    return max(osm_side_ranks(tags).values(), default=0)


def _osm_bike(tags: Mapping[str, str]) -> str:
    found = [
        f"{k}={v}"
        for k, v in sorted(tags.items())
        if k.startswith("cycleway") and not k.endswith(("width", "buffer"))
    ]
    return ", ".join(found) or "no cycleway tag"


def _dc_bike(facts: Mapping) -> str:
    by_label = facts.get("bike") or {}
    if by_label:
        return ", ".join(
            f"{KINDS.get(rank, rank)} ({label.upper()})" for label, rank in sorted(by_label.items())
        )
    if facts.get("bike_recorded"):
        return "a lane on some of the way's blocks only"
    return "none recorded"


def _separate(tags: Mapping[str, str]) -> bool:
    return any(v == "separate" for k, v in tags.items() if k.startswith("cycleway"))


def _contraflow(tags: Mapping[str, str]) -> bool:
    return any(str(v).startswith("opposite") for k, v in tags.items() if k.startswith("cycleway"))


def reason(disagree: str, agree: str, kind: str, own_separate: bool = False) -> str:
    """Why the District's value was not applied (OWNER-DECISIONS 190's exceptions, 197)."""
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
        if "side lane beside a two-way carriageway" in disagree:
            return "side lane beside a two-way carriageway"
        return "slip road: its own lanes"
    if kind == "speed" and f"({OWNER_OVERRIDE})" in disagree:
        return OWNER_OVERRIDE
    return "not applied"


def items(rows: Iterable[Mapping]) -> Iterator[dict]:
    """One record per (way, type) where the District and OSM disagree."""
    for r in rows:
        osm, after, facts, sources = r["osm"], r["after"], r["facts"], r["sources"]
        base = {
            key: r[key]
            for key in (
                "way",
                "street",
                "highway",
                "m",
                "blocks",
                "tier0",
                "tier1",
                "disagree",
                "agree",
            )
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
        osm_speed = parse_maxspeed_mph(osm.get("maxspeed"))
        dc_speed = facts.get("speed_mph")
        if dc_speed is None:
            # Withheld by the owner (item 197): still listed, as not applied.
            dc_speed = facts.get("speed_withheld")
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


def length_text(metres: int) -> str:
    """US units first: feet under 1,000 ft, miles from there."""
    feet = metres * FT_PER_M
    if feet < 1000:
        return f"{feet:,.0f} ft [{metres:,} m]"
    return f"{metres / MI:.2f} mi [{metres:,} m]"


def tier_text(item: Mapping) -> str:
    if not item["applied"]:
        return f"LTS {item['tier1']} (not applied)"
    if item["tier0"] == item["tier1"]:
        return f"LTS {item['tier1']} (no change)"
    return f"LTS {item['tier0']} to {item['tier1']}"


def _miles(group) -> float:
    return sum(i["m"] for i in group) / MI


def _listing(chosen: list[dict]) -> list[str]:
    out = [
        "| street | OSM way | DC block | length | OSM | DC | tier | applied |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i in chosen:
        blocks = i["blocks"].split(",")
        block = blocks[0] + (f" (+{len(blocks) - 1})" if len(blocks) > 1 else "")
        status = "yes" if i["applied"] else f"no: {i['reason']}"
        out.append(
            f"| {i['street']} | {link(i['way'])} | {block} | {length_text(i['m'])} | {i['osm']} | {i['dc']} | {tier_text(i)} | {status} |"
        )
    return out


def markdown(rows: list[Mapping], found: list[dict], source: str) -> str:
    """The report for the owner: the totals by type, the not-applied items
    summarised by reason (every one is in the CSV), every owner override, and
    the longest applied items of each type."""
    by_type = defaultdict(list)
    for item in found:
        by_type[item["type"]].append(item)
    out = [
        "# DC Roadway Block against OSM: where they disagree",
        "",
        "For the owner's review (OWNER-DECISIONS 191: \"DC roads and especially bike infrastructure changes "
        "quite frequently, so it's likely OSM data is stale. However, report the discrepancies when you see "
        "them.\"). Every District road way a Roadway Block was matched to, where the block's record and the "
        "way's OSM tags say different things. The District's value is what the classifier reads "
        "(OWNER-DECISIONS 190) except where a block, which describes the whole road, cannot speak for one of "
        "its ways, or the owner has withheld it (an owner override, item 197); those are **not applied**, "
        f"summarised below by reason. {source} Every item, applied or not, is a row of `{CSV_NAME}`.",
        "",
        "Nothing here is for importing into OSM: the Roadway Block is CC BY 4.0, and copying its values into "
        "OSM (ODbL) would need a licence waiver from the District.",
        "",
        f"{len(rows):,} matched District ways ({_miles(rows):,.0f} mi). A way can appear under several types. "
        "Tiers are the way's tier with OSM's tags alone and with the District's record applied (all of it, "
        "not only this attribute). Where OSM has no value (no `maxspeed`, no `lanes`) the District's fills "
        "it, and that is not counted here.",
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
            f"| {label} | {len(group):,} | {_miles(group):,.1f} | {len(applied):,} | {_miles(applied):,.1f} | "
            f"{len(kept):,} | {_miles(kept):,.1f} | {len(moved):,} |"
        )
    out += [
        "",
        "## Not applied, by reason",
        "",
        "Most are the exceptions OWNER-DECISIONS 190 keeps for modelling: a block describes the whole road, "
        "so its two-way record says nothing about one carriageway of a divided road or one of a pair of "
        "one-way ways, and so on. They are summarised here rather than listed; the examples are the longest "
        f"ways of each, and `{CSV_NAME}` has every one.",
        "",
        "| type | reason | ways | miles | longest |",
        "| --- | --- | --- | --- | --- |",
    ]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in found:
        if not item["applied"]:
            groups[(item["type"], item["reason"])].append(item)
    labels = dict(TYPES)
    for (kind, why), group in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        longest = sorted(group, key=lambda i: (-i["m"], i["way"]))[:EXAMPLES]
        examples = ", ".join(f"{i['street']} {link(i['way'])}" for i in longest)
        out.append(
            f"| {labels[kind]} | {why} | {len(group):,} | {_miles(group):,.1f} | {examples} |"
        )
    overrides = sorted(
        (i for i in found if not i["applied"] and i["reason"] == OWNER_OVERRIDE),
        key=lambda i: (i["street"], -i["m"], i["way"]),
    )
    out += [
        "",
        f"## Owner overrides: every one, {len(overrides):,}",
        "",
        "The District's value withheld by the owner (OWNER-DECISIONS 197; `agency_blocks` in "
        "fixtures/overrides/), so OSM's stands. Listed in full, as the owner asked.",
        "",
    ]
    out += _listing(overrides) if overrides else ["None."]
    out.append("")
    for key, label in TYPES:
        group = sorted(
            (i for i in by_type.get(key, []) if i["applied"]), key=lambda i: (-i["m"], i["way"])
        )
        if not group:
            continue
        out += [f"## {label}: applied, the {min(TOP, len(group))} longest of {len(group):,}", ""]
        out += _listing(group[:TOP])
        out.append("")
    return "\n".join(out)


def _write(path: Path, write) -> None:
    """Written beside and renamed over, so a reader never sees half a report."""
    partial = path.with_name(f".{path.name}.partial")
    with partial.open("w", newline="") as handle:
        write(handle)
    os.replace(partial, path)


def write_report(rows: list[Mapping], out_dir: Path, source: str) -> list[dict]:
    """Write `MD_NAME` and `CSV_NAME` into `out_dir` from `row`s; the items found."""
    found = list(items(rows))
    for item in found:
        item["reason"] = (
            ""
            if item["applied"]
            else reason(
                item["disagree"], item["agree"], item["type"], item.get("own_separate", False)
            )
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    text = markdown(rows, found, source)
    _write(out_dir / MD_NAME, lambda handle: handle.write(text))

    def table(handle) -> None:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_HEADER)
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

    _write(out_dir / CSV_NAME, table)
    return found


def counts(found: Iterable[Mapping]) -> dict[str, int]:
    return dict(Counter(i["type"] for i in found))
