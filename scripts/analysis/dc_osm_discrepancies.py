#!/usr/bin/env python3
"""Where DC's Roadway Block and OSM disagree about a District way, for the owner to review.

    python scripts/analysis/dc_osm_discrepancies.py --dcbal out/dcbal.tsv \\
        --out reports/data-comparison

`dcbal.tsv` is `data_before_after.py`'s output, made from the same extract and roadway.json the
rebuild reads. Writes `dc-osm-discrepancies.md` and `dc-osm-discrepancies.csv`: the copy checked in
under reports/data-comparison/. Each rebuild writes its own to `<DATA_ROOT>/rebuild/reports/`
(OWNER-DECISIONS 191); both are `pipeline.discrepancies.write_report`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from pipeline import discrepancies  # noqa: E402

SOURCE = (
    "This copy is written from `dcbal.tsv` (`scripts/analysis/data_before_after.py`) with the "
    "before-after report; each rebuild writes its own to `<DATA_ROOT>/rebuild/reports/`."
)


def _json(raw: str) -> dict:
    return json.loads(raw) if raw else {}


def from_dcbal(r: dict) -> dict:
    """A `dcbal.tsv` row as `discrepancies.items` reads it."""
    return {
        "way": int(r["way"]),
        "street": r["name"] or "(unnamed)",
        "highway": r["highway"],
        "m": int(r["m"]),
        "blocks": r["blocks"],
        "tier0": int(r["tier0"]),
        "tier1": int(r["tier1"]),
        "disagree": r["disagree"],
        "agree": r["agree"],
        "osm": _json(r["tags"]),
        "after": _json(r["tags1"]),
        "facts": _json(r["facts"]),
        "sources": _json(r["sources"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dcbal", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    csv.field_size_limit(10**9)
    with args.dcbal.open() as handle:
        rows = [
            from_dcbal(r)
            for r in csv.DictReader(handle, delimiter="\t")
            if r["region"] == "dc" and r["state"] == "DC" and r["matched"] == "1"
        ]
    found = discrepancies.write_report(rows, args.out, SOURCE)
    print("discrepancies", len(found), discrepancies.counts(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
