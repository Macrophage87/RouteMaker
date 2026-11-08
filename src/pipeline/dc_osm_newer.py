# ruff: noqa: E501 - table rows run long
"""The District ways OSM edited after DC's Roadway Block record, for the owner's call.

Hunt D6. In the District the record overrides OSM's posted speed, lanes and bike tags
(OWNER-DECISIONS 190) whatever the age of OSM's tagging. Letting a newer OSM edit win was held:
OSM's date is the whole way's last edit (`Way.edited`), not the tag's. The owner, 2026-11-08:
"We should build a flag in. If there's a newer OSM rating, then on a rebuild it should flag it
and I can make the call." So the record still wins, and each rebuild lists every District way
OSM last edited after the record's date (`agency_roads.DC_RECORD_AS_OF`) whose posted speed,
lanes per direction or bike lanes disagree with what the record applied (`newer_osm`), beside
the DC-against-OSM discrepancy report (`pipeline.discrepancies`, OWNER-DECISIONS 191):
`<DATA_ROOT>/rebuild/reports/dc-osm-newer-osm-edits.md` and `.csv`.

It is written in APPLY_OVERRIDES (`pipeline.run`), after the approved rows are read, so a way
the owner has decided is not asked about again:

- **tier set by an owner row**: the way carries an approved stress row (the suggested one, or
  any other: the owner has set its tier), listed under "Decided";
- **speed withheld**: the owner withheld the block's speed (`agency_blocks`, item 197), so the
  record's speed is not applied, the way no longer disagrees on it, and it is not listed;
- **kept DC's value**: the way is in `fixtures/dc_osm_kept.json` with the OSM edit date the owner
  saw (`load_kept`). It is listed again only once OSM edits the way after that date.

A decided way is counted and listed apart, never among the open ones.
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from routemaker.agency_roads import (
    DC_AGENCY,
    EVIDENCE_PLACEHOLDER,
    REASON_PLACEHOLDER,
    osm_side_ranks,
    placeholder_problem,
)
from routemaker.tags import lanes_per_direction, parse_maxspeed_mph

MD_NAME = "dc-osm-newer-osm-edits.md"
CSV_NAME = "dc-osm-newer-osm-edits.csv"
CSV_HEADER = (
    "status",
    "osm_way_id",
    "osm_url",
    "street",
    "osm_edited",
    "attributes",
    "dc_applies",
    "osm_says",
    "tier_with_dc",
    "tier_osm_only",
    "decided",
    "take_osm_with",
    "take_osm_override",
    "keep_dc_entry",
)
# The owner's "keep DC's value" answers, read by the rebuild from its image.
KEPT_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "dc_osm_kept.json"
# How a flagged row names what it compares.
SPEED, LANES, BIKE = "speed", "lanes", "bike facility"
KINDS = {1: "painted lane", 2: "buffered lane", 3: "protected lane"}
OPEN, TOOK_OSM, KEPT_DC = "open", "tier set by an owner row", "kept DC's value"
# What the suggested stress row does, said wherever it is suggested.
STRESS_ROW_SAYS = (
    "a stress row holds the way's tier at the one OSM's tags give; its lanes and bike-lane tags "
    "(what the road panel and the classifier's other readers see) stay DC's"
)


class KeptRefused(ValueError):
    """`fixtures/dc_osm_kept.json` is malformed."""


@dataclass(frozen=True)
class Kept:
    """One way the owner keeps DC's value on, against the OSM edit he saw."""

    osm_way_id: int
    osm_edited: date
    reason: str


def load_kept(path: Path | str | None = None) -> dict[int, Kept]:
    """{way id: Kept} from the kept list: `{"version": 1, "kept": [{"osm_way_id": <id>,
    "osm_edited": "YYYY-MM-DD" (the date the list showed), "reason": <the owner's words>}]}`.
    A missing file keeps nothing."""
    source = Path(path or KEPT_PATH)
    if not source.exists():
        return {}
    try:
        document = json.loads(source.read_text())
    except ValueError as error:
        raise KeptRefused(f"{source.name} is not JSON: {error}") from error
    if not isinstance(document, dict) or document.get("version") != 1:
        raise KeptRefused(f"{source.name} is not a version 1 kept list")
    entries = document.get("kept", [])
    if not isinstance(entries, list):
        raise KeptRefused(f"{source.name}: kept must be a list")
    found: dict[int, Kept] = {}
    for index, entry in enumerate(entries):
        where = f"{source.name} kept[{index}]"
        if not isinstance(entry, dict):
            raise KeptRefused(f"{where} is not an object")
        way = entry.get("osm_way_id")
        if not isinstance(way, int) or isinstance(way, bool) or way <= 0:
            raise KeptRefused(f"{where}: osm_way_id must be a positive integer")
        if way in found:
            raise KeptRefused(f"{where}: way {way} appears twice")
        try:
            edited = date.fromisoformat(entry.get("osm_edited"))
        except (TypeError, ValueError) as error:
            raise KeptRefused(f"{where}: osm_edited must be the YYYY-MM-DD date listed") from error
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise KeptRefused(f"{where}: reason is required")
        problem = placeholder_problem("reason", reason)
        if problem:
            raise KeptRefused(f"{where}: {problem}")
        found[way] = Kept(way, edited, reason.strip())
    return found


def _bike_sides(tags: Mapping[str, str]) -> dict[str, int]:
    """The facility on each side of the way that has one ({side: rank})."""
    return {side: rank for side, rank in osm_side_ranks(tags).items() if rank}


def _sides_text(ranks: Mapping[str, int]) -> str:
    if not ranks:
        return "no bike lane"
    if set(ranks) == {"left", "right"} and ranks["left"] == ranks["right"]:
        return f"{KINDS[ranks['left']]} both sides"
    return ", ".join(f"{KINDS[rank]} ({side})" for side, rank in sorted(ranks.items()))


def _lanes_text(lanes: int) -> str:
    return f"{lanes} lane{'' if lanes == 1 else 's'} a direction"


def tier_text(tier: int, half: bool) -> str:
    return f"LTS {tier}.5" if half else f"LTS {tier}"


def take_osm_override(r: Mapping, kinds: list[str], fingerprint: dict | None) -> tuple[str, str]:
    """How the owner would take OSM's value on the way: (how, the entry).

    A posted speed alone is the owner's block correction (OWNER-DECISIONS 197): an
    `agency_blocks` entry for each of the way's blocks withholding the record's speed, so OSM's
    speed is what the classifier reads; the rebuild reads it from the image. Lanes and bike
    lanes have no such entry (`agency_roads.WITHHOLDABLE` is the speed alone, and a lane
    override only adds lanes), so the way's own stress row (fixtures/overrides/README.md,
    "Stress rows") holds the way at the tier OSM's tags give, half step kept, while its tags
    stay DC's. Where OSM's tier is the higher it is a floor (`at_least`), so a later record
    that makes the way worse still counts. The row carries the way's `fingerprint`
    (`rematch.fingerprint_of`), so it follows the way when OSM splits it (decision 282)."""
    keys = r.get("block_keys") or []
    if kinds == [SPEED] and keys:
        entries = [
            {
                "blockkey": key,
                "routename": routename,
                "withhold": ["speed"],
                "reason": REASON_PLACEHOLDER,
                "evidence": EVIDENCE_PLACEHOLDER,
            }
            for key, routename in keys
        ]
        return (
            "agency_blocks entries in a fixtures/overrides/ file: OSM's posted speed is then what "
            "the classifier reads (the rebuild reads the file; nothing to load)",
            json.dumps(entries),
        )
    tier0, half0 = r["tier0"], bool(r.get("tier0_half"))
    value: dict = {
        "tier": tier0,
        "adjustment_id": f"way-{r['way']}-osm-newer",
        "category": "other",
        "visibility": "hidden",
        "annotation_status": "approved",
        "display": "route_only",
    }
    if half0:
        value["half"] = True
    if (tier0, half0) > (r["tier1"], bool(r.get("tier1_half"))):
        value["at_least"] = True
    entry: dict = {
        "kind": "stress",
        "osm_way_id": r["way"],
        "value": value,
        "reason": REASON_PLACEHOLDER,
        "evidence": EVIDENCE_PLACEHOLDER,
    }
    if fingerprint is not None:
        entry["fingerprint"] = fingerprint
    return (
        f"a row in a fixtures/overrides/ file, loaded with manage.py load_access_overrides: "
        f"{STRESS_ROW_SAYS}",
        json.dumps(entry),
    )


def keep_dc_entry(way: int, edited: str) -> str:
    """The kept-list entry that answers "keep DC's value" for the edit listed."""
    return json.dumps({"osm_way_id": way, "osm_edited": edited, "reason": REASON_PLACEHOLDER})


def newer_osm(
    rows: Iterable[Mapping],
    as_of: date,
    *,
    decided: Mapping[int, str] | None = None,
    kept: Mapping[int, Kept] | None = None,
    fingerprint_of: Callable[[int], dict | None] | None = None,
) -> list[dict]:
    """The District ways OSM last edited after `as_of` (the record's date,
    `agency_roads.DC_RECORD_AS_OF`) whose OSM posted speed, lanes per direction or bike lanes
    disagree with what the record applied, one per way (`pipeline.discrepancies.row`s). The
    record still wins (OWNER-DECISIONS 190). A value the record did not apply (an item 190
    exception, a speed the owner withheld) is OSM's already and not listed; nor is a value OSM
    does not carry. `decided` is {way: what approved stress row it carries}, `kept` the
    owner's kept list: such a way is listed with its status, not as open. A kept way OSM has
    edited again since the date the owner saw is open again."""
    decided = decided or {}
    kept = kept or {}
    flagged = []
    for r in rows:
        edited = r.get("edited")
        if not edited or date.fromisoformat(edited) <= as_of:
            continue
        osm, after, sources = r["osm"], r["after"], r["sources"]
        kinds: list[str] = []
        dc_says: list[str] = []
        osm_says: list[str] = []
        if sources.get("maxspeed") == DC_AGENCY:
            mph = parse_maxspeed_mph(after.get("maxspeed"))
            osm_mph = parse_maxspeed_mph(osm.get("maxspeed"))
            if mph is not None and osm_mph is not None and round(mph) != round(osm_mph):
                kinds.append(SPEED)
                dc_says.append(f"{mph:g} mph")
                osm_says.append(f"{osm_mph:g} mph")
        if sources.get("lanes") == DC_AGENCY:
            lanes, osm_lanes = lanes_per_direction(after), lanes_per_direction(osm)
            if lanes is not None and osm_lanes is not None and lanes != osm_lanes:
                kinds.append(LANES)
                dc_says.append(_lanes_text(lanes))
                osm_says.append(_lanes_text(osm_lanes))
        if sources.get("bike") == DC_AGENCY:
            bike, osm_bike = _bike_sides(after), _bike_sides(osm)
            if bike != osm_bike:
                kinds.append(BIKE)
                dc_says.append(_sides_text(bike))
                osm_says.append(_sides_text(osm_bike))
        if not kinds:
            continue
        way = r["way"]
        status, note = OPEN, ""
        if way in decided:
            status, note = TOOK_OSM, decided[way]
        elif way in kept and date.fromisoformat(edited) <= kept[way].osm_edited:
            status, note = KEPT_DC, f"kept against the edit of {kept[way].osm_edited.isoformat()}"
        elif way in kept:
            note = (
                f"kept against the edit of {kept[way].osm_edited.isoformat()}; OSM edited it since"
            )
        how, entry = take_osm_override(r, kinds, fingerprint_of(way) if fingerprint_of else None)
        flagged.append(
            {
                "status": status,
                "way": way,
                "street": r["street"],
                "edited": edited,
                "kinds": kinds,
                "dc": "; ".join(dc_says),
                "osm": "; ".join(osm_says),
                "tier_dc": tier_text(r["tier1"], bool(r.get("tier1_half"))),
                "tier_osm": tier_text(r["tier0"], bool(r.get("tier0_half"))),
                "decided": note,
                "how": how,
                "override": entry,
                "keep": keep_dc_entry(way, edited),
            }
        )
    return sorted(flagged, key=lambda f: (f["street"], f["way"]))


def link(way: int) -> str:
    return f"[{way}](https://www.openstreetmap.org/way/{way})"


def markdown(flagged: list[dict], matched: int, dated: int, as_of: date) -> str:
    open_ = [f for f in flagged if f["status"] == OPEN]
    done = [f for f in flagged if f["status"] != OPEN]
    out = [
        "# DC ways OSM edited after the record: for the owner's call",
        "",
        f"District ways OSM last edited after {as_of.isoformat()}, the date of the installed "
        "Roadway Block record (its retrieval date, docs/SOURCES.md), where OSM's posted speed, "
        "lanes per direction or bike lanes disagree with what the record applied. DC's value is "
        "the one the map uses (OWNER-DECISIONS 190): OSM's date is the whole way's last edit, not "
        "the tag's. The owner, 2026-11-08: \"If there's a newer OSM rating, then on a rebuild it "
        'should flag it and I can make the call." docs/OPERATIONS.md, "The DC-against-OSM '
        f'discrepancy report", has the steps; every row is also in `{CSV_NAME}`, with the entries '
        f"in full. {dated:,} of {matched:,} matched District ways carry an OSM edit date in this "
        "extract.",
        "",
        "To take OSM's value, check in the row's override with the owner's words as its reason and "
        "what was seen on the spot as its evidence (the loaders refuse the placeholders). For a "
        f"posted speed alone it is the block's `agency_blocks` entry; otherwise {STRESS_ROW_SAYS}. "
        "To keep DC's value, add the row's kept entry to `fixtures/dc_osm_kept.json` with the "
        "owner's reason: the way is not asked about again until OSM edits it after that date.",
        "",
        f"## Open: {len(open_):,}",
        "",
    ]
    if open_:
        out += [
            "| street | OSM way | OSM edited | DC applies | OSM says | tier with DC | tier with OSM's tags | note |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        out += [
            f"| {f['street']} | {link(f['way'])} | {f['edited']} | {f['dc']} | {f['osm']} | "
            f"{f['tier_dc']} | {f['tier_osm']} | {f['decided']} |"
            for f in open_
        ]
    else:
        out.append("None.")
    out += ["", f"## Decided: {len(done):,}", ""]
    if done:
        out += [
            "| street | OSM way | OSM edited | DC applies | OSM says | decision |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        out += [
            f"| {f['street']} | {link(f['way'])} | {f['edited']} | {f['dc']} | {f['osm']} | "
            f"{f['status']}: {f['decided']} |"
            for f in done
        ]
    else:
        out.append("None.")
    out.append("")
    return "\n".join(out)


def _write(path: Path, write) -> None:
    """Written beside and renamed over, so a reader never sees half a report."""
    partial = path.with_name(f".{path.name}.partial")
    with partial.open("w", newline="") as handle:
        write(handle)
    os.replace(partial, path)


def write_report(
    flagged: list[dict], out_dir: Path, *, matched: int, dated: int, as_of: date
) -> None:
    """Write `MD_NAME` and `CSV_NAME` into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    text = markdown(flagged, matched, dated, as_of)
    _write(out_dir / MD_NAME, lambda handle: handle.write(text))

    def table(handle) -> None:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        for f in sorted(flagged, key=lambda f: (f["status"] != OPEN, f["street"], f["way"])):
            writer.writerow(
                [
                    f["status"],
                    f["way"],
                    f"https://www.openstreetmap.org/way/{f['way']}",
                    f["street"],
                    f["edited"],
                    "; ".join(f["kinds"]),
                    f["dc"],
                    f["osm"],
                    f["tier_dc"],
                    f["tier_osm"],
                    f["decided"],
                    f["how"],
                    f["override"],
                    f["keep"],
                ]
            )

    _write(out_dir / CSV_NAME, table)


def decided_ways(rows: Iterable) -> dict[int, str]:
    """{way: the approved stress row it carries} from the approved override rows
    (`pipeline.overrides.Override`, after re-matching)."""
    out: dict[int, str] = {}
    for row in rows:
        if row.kind != "stress" or not isinstance(row.value, dict):
            continue
        value = row.value
        tier = tier_text(int(value.get("tier", 0)), bool(value.get("half")))
        floor = " or above" if value.get("at_least") else ""
        out[row.osm_way_id] = (
            f"approved stress row {value.get('adjustment_id') or f'way-{row.osm_way_id}'}, "
            f"{tier}{floor}"
        )
    return out
