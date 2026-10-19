#!/usr/bin/env python3
"""Install the agency bicycle stress layers the rebuild reads (`pipeline.agency_ratings`).

    python scripts/install_agency_lts.py --datasets ~/rmdata/datasets \\
        --out ~/rmdata/reference/agency-lts.json moco ddot mdot-sha

Reads each named agency's layer as `scripts/fetch_agency_layer.py` stored it and
writes one row per usable record, `{"id", "agency", "level", "name",
"coordinates"}`, with the level on our scale. A layer under `internal-only/` is
refused (`agency_roads.refuse_internal_only`; OWNER-DECISIONS 152, 153, 155), and
an agency not in `routemaker.agency_lts.AGENCIES` has no parser here.

Montgomery County Planning's "Bicycle Level of Traffic Stress" (`LTS_EXIST`):
existing roads only. Sidepath and trail records, parking lots and trails, and
0.5 ("None", no rating) are left out, as in the comparison report
(reports/data-comparison/moco-lts-comparison.md).

DDOT's 2020 bicycle Level of Traffic Stress (downloaded as `ddot-lts-2020`): DDOT
rates District streets on the four-level Mekuria-Furth scale (Semler et al., "Low-Stress
Bicycle Network Mapping: The District of Columbia's Innovative Approach to Applying
Level of Traffic Stress", TRR 2662, 2017, doi:10.3141/2662-04), so 1 to 4 are taken as
they are. Which attribute holds the level is not recorded in this repository: the
reader takes the first of `DDOT_LEVEL_FIELDS` any record has, says which, and refuses
the layer, naming its fields, where none has any of them (`--ddot-field` names
another). 0, empty and null are no rating and are left out, and so is 100: 66 records
of the 2020 layer carry it, and the owner ruled, 2026-10-17, "DDOT 100 as not rated"
(those roads take the formula). Any other level that is not 1 to 5 is refused, never
guessed.

MDOT SHA's statewide Bicycle Level of Traffic Stress (2022; downloaded as `mdot-lts`):
the level is `LTS_ADJUSTED`, which MDOT's methodology calls the most important
attribute for most applications (the corrected score; `LTS_SCORE` is the preliminary
one), MDOT, "Bicycle Level of Traffic Stress (LTS) Metadata and Methodology"
(https://www.mdot.maryland.gov/OPCP/MDOT_LTS_Metadata_Methodology_Full.pdf). Its
values: 0 "to represent shared-use paths and similar facilities" (left out: a path, not
a road rating, as Montgomery's sidepaths are), 1 to 4 the Mekuria-Furth levels (taken
as they are), 5 "Bicycle access is prohibited by managing roadway agency" (taken as our
5; the rebuild reads MDOT's 5 as a ban and closes the road to bicycles,
`agency_lts.PROHIBITING_LEVELS`, the owner's ruling of 2026-10-19), 9 "missing data"
(left out). The layer carries a route id and no street name, so its
rows have no name.
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

# The layer files as `scripts/fetch_agency_layer.py` stored them: <slug>/<slug>.geojson.
SLUGS = {"moco": "moco-bicycle-lts", "ddot": "ddot-lts-2020", "mdot-sha": "mdot-lts"}

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


def layer_path(datasets: Path, agency: str) -> Path:
    """The agency's downloaded layer, refused under `internal-only/` or when absent."""
    slug = SLUGS[agency]
    path = agency_roads.refuse_internal_only(datasets / slug / f"{slug}.geojson")
    if not path.exists():
        raise SystemExit(
            f"{agency}: {path} is absent; download it with scripts/fetch_agency_layer.py "
            f'--slug {slug} (docs/OPERATIONS.md, "Agency stress ratings (agency-lts.json)")'
        )
    return path


def number(value) -> float | None:
    """A level as the layer gives it: 3, 3.0, "3" or "LTS 3"; None when empty."""
    if value is None:
        return None
    text = str(value).strip()
    if text.upper().startswith("LTS"):
        text = text[3:].strip(" _-")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise SystemExit(f"level {value!r} is not a number") from None


def feature_id(p: dict, index: int):
    for key in ("OBJECTID", "OBJECTID_1", "FID", "ID"):
        if p.get(key) is not None:
            return p[key]
    return f"n{index}"


def moco(datasets: Path, dropped: Counter):
    layer = layer_path(datasets, "moco")
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


# Where DDOT's level may be, in the order tried; the first the layer has is read.
DDOT_LEVEL_FIELDS = (
    "LTS",
    "LTS_2020",
    "LTS2020",
    "BIKE_LTS",
    "BIKELTS",
    "LTS_RATING",
    "LTS_LEVEL",
    "LEVEL_OF_TRAFFIC_STRESS",
)
DDOT_NAME_FIELDS = ("ST_NAME", "STREETNAME", "STREET_NAME", "FULLNAME", "ROUTENAME", "NAME")
# DDOT rates on Mekuria-Furth's four levels; a 5 is taken as Avoid like any agency's.
DDOT_LEVELS = {1.0: 1.0, 2.0: 2.0, 3.0: 3.0, 4.0: 4.0, 5.0: 5.0}
# Not a level: the owner's ruling (module docstring).
DDOT_NOT_RATED = 100.0


def ddot(datasets: Path, dropped: Counter, field: str | None = None):
    # The District's layer is small; read whole so the level field is chosen from every
    # record's attributes, not the first record's alone.
    features = list(agency_roads.iter_features(layer_path(datasets, "ddot")))
    if field is None:
        fields = set().union(*((f["properties"] or {}).keys() for f in features))
        found = [k for k in DDOT_LEVEL_FIELDS if k in fields]
        if not found:
            raise SystemExit(
                "ddot: the layer has none of the level fields "
                + ", ".join(DDOT_LEVEL_FIELDS)
                + "; its fields are "
                + ", ".join(sorted(fields))
                + ". Name the level's field with --ddot-field"
            )
        field = found[0]
        print(f"ddot: level read from {field}")
    for index, feature in enumerate(features):
        p = feature["properties"] or {}
        level = number(p.get(field))
        if level in (None, 0):
            dropped["ddot: no rating (0 or empty)"] += 1
            continue
        if level == DDOT_NOT_RATED:
            dropped["ddot: not rated (100)"] += 1
            continue
        if level not in DDOT_LEVELS:
            raise SystemExit(
                f"ddot: record {feature_id(p, index)}: {field} {level:g} is not 1 to 5"
            )
        name = next((str(p[k]).strip() for k in DDOT_NAME_FIELDS if p.get(k)), None)
        for part, line in enumerate(lines_of(feature["geometry"])):
            yield row("ddot", feature_id(p, index), part, DDOT_LEVELS[level], name, line)


# MDOT SHA's LTS_ADJUSTED, on our scale (the module's docstring has the citations).
MDOT_LEVEL_FIELD = "LTS_ADJUSTED"
MDOT_LEVELS = {1.0: 1.0, 2.0: 2.0, 3.0: 3.0, 4.0: 4.0, 5.0: 5.0}
MDOT_NOT_RATED = {0.0: "mdot-sha: shared-use path (0)", 9.0: "mdot-sha: missing data (9)"}


def mdot_sha(datasets: Path, dropped: Counter):
    for index, feature in enumerate(agency_roads.iter_features(layer_path(datasets, "mdot-sha"))):
        p = feature["properties"] or {}
        if MDOT_LEVEL_FIELD not in p:
            raise SystemExit(
                f"mdot-sha: the layer has no {MDOT_LEVEL_FIELD}; its fields are "
                + ", ".join(sorted(p))
            )
        level = number(p.get(MDOT_LEVEL_FIELD))
        if level is None:
            dropped["mdot-sha: no adjusted score"] += 1
            continue
        if level in MDOT_NOT_RATED:
            dropped[MDOT_NOT_RATED[level]] += 1
            continue
        if level not in MDOT_LEVELS:
            raise SystemExit(
                f"mdot-sha: record {feature_id(p, index)}: {MDOT_LEVEL_FIELD} {level:g} is not "
                "0 to 5 or 9"
            )
        for part, line in enumerate(lines_of(feature["geometry"])):
            yield row("mdot-sha", feature_id(p, index), part, MDOT_LEVELS[level], None, line)


def row(agency: str, fid, part: int, level: float, name: str | None, line) -> dict:
    return {
        "id": f"{agency}-{fid}-{part}",
        "agency": agency,
        "level": float(level),
        "name": name,
        "coordinates": [[round(c[0], 7), round(c[1], 7)] for c in line],
    }


PARSERS = {"moco": moco, "ddot": ddot, "mdot-sha": mdot_sha}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("agencies", nargs="+", choices=sorted(AGENCIES))
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--ddot-field",
        default=None,
        help="the DDOT layer's level field, where it is none of DDOT_LEVEL_FIELDS",
    )
    args = parser.parse_args()
    rows, dropped = [], Counter()
    for agency in args.agencies:
        if agency not in PARSERS:
            parser.error(f"{agency}: no parser yet; its layer's format is not known")
        extra = {"field": args.ddot_field} if agency == "ddot" else {}
        found = list(PARSERS[agency](args.datasets, dropped, **extra))
        if not found:
            # The rebuild refuses a file with an approved agency missing
            # (`pipeline.agency_ratings.load`), so an empty reader is refused here first.
            raise SystemExit(f"{agency}: no usable record in its layer; nothing was written")
        for row in found:
            problem = level_problem(row["level"])
            if problem:
                raise SystemExit(f"{row['id']}: {problem}")
        rows += found
        print(f"{agency}: {len(found)} records")
    for reason, count in sorted(dropped.items()):
        print(f"  left out, {reason}: {count}")
    missing = sorted(set(AGENCIES) - set(args.agencies))
    if missing:
        print(
            "note: no "
            + ", ".join(missing)
            + " in this file; the rebuild refuses it unless REBUILD_ALLOW_NO_AGENCY_LTS=1"
        )
    args.out.write_text(json.dumps(rows))
    print(f"wrote {args.out} ({len(rows)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
