#!/usr/bin/env python3
"""Install the agency bicycle stress layers the rebuild reads (`pipeline.agency_ratings`).

    python scripts/install_agency_lts.py --datasets ~/rmdata/datasets \\
        --out ~/rmdata/reference/agency-lts.json moco [mdot-sha ...]

Reads each named agency's layer as `scripts/fetch_agency_layer.py` stored it and
writes one row per usable record, `{"id", "agency", "level", "name",
"coordinates"}`, with the level on our scale. A layer under `internal-only/` is
refused (`agency_roads.refuse_internal_only`; OWNER-DECISIONS 152, 153, 155), and
an agency not in `routemaker.agency_lts.AGENCIES` has no parser here.

Montgomery County Planning's "Bicycle Level of Traffic Stress" (`LTS_EXIST`):
existing roads only. Sidepath and trail records, parking lots and trails, and
0.5 ("None", no rating) are left out, as in the comparison report
(reports/data-comparison/moco-lts-comparison.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from routemaker import agency_roads  # noqa: E402
from routemaker.agency_lts import AGENCIES, level_problem  # noqa: E402

MOCO_OFF_ROAD_BIKEWAYS = {"Sidepath", "Off-Street Trail", "Park Trail", "Stream Valley Park Trail"}


def lines_of(geometry):
    if not geometry:
        return
    if geometry["type"] == "LineString":
        yield geometry["coordinates"]
    elif geometry["type"] == "MultiLineString":
        yield from geometry["coordinates"]


def street_name(*parts) -> str | None:
    text = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return text or None


def moco(datasets: Path, dropped: Counter):
    layer = agency_roads.refuse_internal_only(
        datasets / "moco-bicycle-lts" / "moco-bicycle-lts.geojson"
    )
    for feature in agency_roads.iter_features(layer):
        p = feature["properties"]
        if p.get("STATUS") != "Existing":
            dropped["moco: not existing"] += 1
            continue
        if p.get("BIKEWAY") in MOCO_OFF_ROAD_BIKEWAYS:
            dropped["moco: sidepath or trail record"] += 1
            continue
        if str(p.get("STREET_CLASS") or "").startswith(("Other - Parking", "Other - Trail")):
            dropped["moco: parking lot or trail"] += 1
            continue
        if p.get("LTS_EXIST") in (None, 0.5, 99):
            dropped["moco: no rating (0.5 'None')"] += 1
            continue
        name = street_name(
            *(p.get(k) for k in ("STREET_PREFIX", "STREET_NAME", "STREET_TYPE", "STREET_SUFFIX"))
        )
        for part, line in enumerate(lines_of(feature["geometry"])):
            yield {
                "id": f"moco-{p['OBJECTID']}-{part}",
                "agency": "moco",
                "level": float(p["LTS_EXIST"]),
                "name": name,
                "coordinates": [[round(c[0], 7), round(c[1], 7)] for c in line],
            }


PARSERS = {"moco": moco}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("agencies", nargs="+", choices=sorted(AGENCIES))
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows, dropped = [], Counter()
    for agency in args.agencies:
        if agency not in PARSERS:
            parser.error(f"{agency}: no parser yet; its layer's format is not known")
        found = list(PARSERS[agency](args.datasets, dropped))
        for row in found:
            problem = level_problem(row["level"])
            if problem:
                raise SystemExit(f"{row['id']}: {problem}")
        rows += found
        print(f"{agency}: {len(found)} records")
    for reason, count in sorted(dropped.items()):
        print(f"  left out, {reason}: {count}")
    args.out.write_text(json.dumps(rows))
    print(f"wrote {args.out} ({len(rows)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
