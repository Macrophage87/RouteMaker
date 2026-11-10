#!/usr/bin/env python3
"""Store a geometry/name fingerprint with every override row (OWNER-DECISIONS 282).

    python scripts/analysis/backfill_override_fingerprints.py \\
        --pbf <DATA_ROOT>/extracts/source.osm.pbf [--previous-ways ways.jsonl] [--write]

Reads the override files under `fixtures/overrides/` and the extract, read only,
and adds `"fingerprint": {name, highway, length_m, line}` (`pipeline.rematch`) to
each row whose way is in the extract. A row whose way is missing from the extract
is listed, and given a fingerprint only from `--previous-ways` (JSON lines of
`{"id", "tags" or "t", "c"}` from an earlier extract) where that has it. Dry
unless `--write`; a rewritten file keeps its own indent and changes nothing but
the added keys. Nothing is downloaded and nothing is written to a database.

`--ways-jsonl` reads the current ways from such a file instead of the PBF.

`--overrides fixtures/speed` and `--overrides fixtures/bike_lanes` fill the curated
speed limits' and bike lanes' rows the same way: with a fingerprint stored, the
rebuild follows an OSM split of such a way onto its new piece and does not spread
it over a merge (`rematch.resolve_keyed`; hunt D1, 2026-11-08).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from pipeline import rematch  # noqa: E402
from pipeline.overrides import file_rows, groups_text  # noqa: E402

OVERRIDES = REPO / "fixtures" / "overrides"


def indent_of(text: str) -> int:
    for line in text.splitlines()[1:3]:
        stripped = line.lstrip(" ")
        if stripped != line:
            return len(line) - len(stripped)
    return 2


def read_pbf(pbf: str, ids: set[int]) -> dict[int, tuple[dict, list]]:
    import osmium

    found: dict[int, tuple[dict, list]] = {}
    processor = (
        osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.IdFilter(ids))
    )
    for way in processor:
        coords = [(n.lon, n.lat) for n in way.nodes if n.location.valid()]
        found[way.id] = ({tag.k: tag.v for tag in way.tags}, coords)
    return found


def read_jsonl(path: str, ids: set[int]) -> dict[int, tuple[dict, list]]:
    found: dict[int, tuple[dict, list]] = {}
    with open(path) as handle:
        for line in handle:
            start = line.index(":") + 1
            way_id = int(line[start : line.index(",", start)])
            if way_id in ids:
                record = json.loads(line)
                found[way_id] = (record.get("tags") or record.get("t"), record.get("c"))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pbf")
    parser.add_argument("--ways-jsonl")
    parser.add_argument("--previous-ways")
    parser.add_argument("--overrides", default=str(OVERRIDES))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not args.pbf and not args.ways_jsonl:
        parser.error("give --pbf or --ways-jsonl")

    files = sorted(Path(args.overrides).glob("2026-*.json"))
    documents = {path: json.loads(path.read_text()) for path in files}
    ids = {row["osm_way_id"] for document in documents.values() for row in file_rows(document)}
    current = read_pbf(args.pbf, ids) if args.pbf else read_jsonl(args.ways_jsonl, ids)
    missing = sorted(ids - set(current))
    previous = read_jsonl(args.previous_ways, set(missing)) if args.previous_ways else {}

    added = unchanged = 0
    still_missing: list[tuple[str, int]] = []
    for path, document in documents.items():
        changed = False
        for row in [*document.get("rows", []), *group_rows(document)]:
            if "fingerprint" in row:
                unchanged += 1
                continue
            record = current.get(row["osm_way_id"]) or previous.get(row["osm_way_id"])
            if record is None or len(record[1]) < 2:
                still_missing.append((path.name, row["osm_way_id"]))
                continue
            row["fingerprint"] = rematch.fingerprint_of(*record)
            if "group" in row:
                # A compact group (`file_rows`) keeps its fingerprints by way id.
                row["group"].setdefault("fingerprints", {})[str(row["osm_way_id"])] = row[
                    "fingerprint"
                ]
            added += 1
            changed = True
        if changed and args.write:
            raw = path.read_text()
            if "groups" in document:
                if groups_text(json.loads(raw)) != raw:
                    raise SystemExit(f"{path.name}: would not round-trip as a groups file")
                path.write_text(groups_text(document))
                continue
            width = indent_of(raw)
            if json.dumps(json.loads(raw), indent=width) + "\n" != raw:
                raise SystemExit(f"{path.name}: would not round-trip at indent {width}")
            path.write_text(json.dumps(document, indent=width) + "\n")
    print(
        f"rows: {added} fingerprints {'written' if args.write else 'to write'}, "
        f"{unchanged} already had one, {len(missing)} ways missing from the extract "
        f"({len(missing) - len(still_missing)} recovered from --previous-ways)"
    )
    for name, way in still_missing:
        print(f"  no geometry for way {way} ({name})")
    return 0


def group_rows(document: dict) -> list[dict]:
    """One stand-in row per way of each of the file's `groups`, pointing back at its group."""
    rows = []
    for group in document.get("groups", []):
        prints = group.get("fingerprints", {})
        for way_id in group["ways"]:
            row = {"osm_way_id": way_id, "group": group}
            if str(way_id) in prints:
                row["fingerprint"] = prints[str(way_id)]
            rows.append(row)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
