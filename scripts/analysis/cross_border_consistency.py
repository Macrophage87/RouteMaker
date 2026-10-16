#!/usr/bin/env python3
"""Like roads rated alike on both sides of a border: where they are not.

    python scripts/analysis/cross_border_consistency.py --segments segments.csv \\
        --areas areas.geojson [--name-field name] [--within-mi 2] [--min-mi 0.5] \\
        [--min-gap 1] --out DIR

Read-only; it writes only to `--out`. The plan (v0.7.0) asks for a
cross-border consistency report: the stress rating comes from a different mix
of sources on each side of a county or state line (Montgomery County's LTS
layer, MDOT SHA, DDOT, the formula), so a road of the same build can read one
level calmer just over the line. This finds that, so the owner can decide
which side is wrong.

"Like roads" are segments with the same profile: road or trail, bike facility,
posted speed (in 5 mph steps), lane count and one-way. For every pair of
neighbouring areas, the segments within `--within-mi` of the other area are
grouped by profile, and each side's level is the length-weighted mean (a half
step counts as +0.5). A profile is flagged where both sides hold at least
`--min-mi` of it and the means differ by `--min-gap` levels or more.

Inputs, both made on the PC:

- `--segments`, a CSV from the live table (read-only):

      \\copy (SELECT osm_way_id, stress_tier AS tier, stress_half AS half,
              facility, road_speed_mph, road_lanes, road_oneway, is_trail_class,
              ST_AsText(geometry) AS wkt FROM segment) TO 'segments.csv' WITH CSV HEADER

- `--areas`, a GeoJSON FeatureCollection of polygons (counties, states, the
  District), each with its name in `--name-field`.

Writes `cross-border.md` and `cross-border.csv` to `--out`. US units first,
metric in brackets.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import shapely
import shapely.geometry as sg
import shapely.wkt

M_PER_MI = 1609.344
# Metres per degree, for a local flat projection: good to well under 1% across
# a few miles at these latitudes, which is all a distance to a border needs.
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_EQUATOR = 111_320.0
TRUE = {"t", "true", "1", "yes", "y"}


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE


def _int(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(float(value)) if value else None


@dataclass(frozen=True)
class Segment:
    osm_way_id: int
    level: float
    profile: tuple
    geometry: sg.base.BaseGeometry  # in local metres


@dataclass(frozen=True)
class Area:
    name: str
    geometry: sg.base.BaseGeometry  # in local metres


@dataclass(frozen=True)
class Finding:
    side_a: str
    side_b: str
    profile: tuple
    miles_a: float
    miles_b: float
    level_a: float
    level_b: float
    ways_a: tuple[int, ...]
    ways_b: tuple[int, ...]

    @property
    def gap(self) -> float:
        return abs(self.level_a - self.level_b)


def projector(lat0: float):
    scale = M_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat0))

    def to_metres(coords):
        return coords * [scale, M_PER_DEG_LAT]

    return lambda geometry: shapely.transform(geometry, to_metres)


def profile_of(row: dict) -> tuple:
    """What makes two segments "like roads": built and signed the same."""
    speed = _int(row.get("road_speed_mph"))
    return (
        "trail" if _bool(row.get("is_trail_class")) else "road",
        (row.get("facility") or "none").strip() or "none",
        None if speed is None else 5 * round(speed / 5),
        _int(row.get("road_lanes")),
        _bool(row.get("road_oneway")),
    )


def describe(profile: tuple) -> str:
    kind, facility, speed, lanes, oneway = profile
    parts = [kind, f"facility {facility}"]
    if speed is not None:
        parts.append(f"{speed} mph ({round(speed * 1.609344)} km/h)")
    if lanes is not None:
        parts.append(f"{lanes} lane{'s' if lanes != 1 else ''}")
    if oneway:
        parts.append("one-way")
    return ", ".join(parts)


def load_segments(rows: Iterable[dict], project) -> list[Segment]:
    segments = []
    for row in rows:
        tier = _int(row.get("tier"))
        if tier is None:
            continue
        level = tier + (0.5 if _bool(row.get("half")) and tier < 5 else 0.0)
        segments.append(
            Segment(
                osm_way_id=int(row["osm_way_id"]),
                level=level,
                profile=profile_of(row),
                geometry=project(shapely.wkt.loads(row["wkt"])),
            )
        )
    return segments


def load_areas(collection: dict, name_field: str, project) -> list[Area]:
    return [
        Area(
            name=str(feature["properties"][name_field]),
            geometry=project(sg.shape(feature["geometry"])),
        )
        for feature in collection["features"]
    ]


def compare(
    segments: Sequence[Segment],
    areas: Sequence[Area],
    within_m: float = 2 * M_PER_MI,
    min_m: float = 0.5 * M_PER_MI,
    min_gap: float = 1.0,
) -> list[Finding]:
    """Every (area pair, profile) where like roads differ by `min_gap` or more."""
    # Each segment's home is the area holding its midpoint.
    home: dict[int, str] = {}
    for index, segment in enumerate(segments):
        middle = segment.geometry.interpolate(0.5, normalized=True)
        for area in areas:
            if area.geometry.covers(middle):
                home[index] = area.name
                break
    # (a, b, profile) -> side -> [metres, metres x level, way ids]
    sums: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, []]))
    for index, segment in enumerate(segments):
        own = home.get(index)
        if own is None:
            continue
        middle = segment.geometry.interpolate(0.5, normalized=True)
        for other in areas:
            if other.name == own or other.geometry.distance(middle) > within_m:
                continue
            a, b = sorted((own, other.name))
            held = sums[(a, b, segment.profile)][own]
            held[0] += segment.geometry.length
            held[1] += segment.geometry.length * segment.level
            held[2].append(segment.osm_way_id)
    findings = []
    for (a, b, profile), sides in sums.items():
        if a not in sides or b not in sides:
            continue
        (len_a, sum_a, ways_a), (len_b, sum_b, ways_b) = sides[a], sides[b]
        if len_a < min_m or len_b < min_m:
            continue
        finding = Finding(
            side_a=a,
            side_b=b,
            profile=profile,
            miles_a=len_a / M_PER_MI,
            miles_b=len_b / M_PER_MI,
            level_a=sum_a / len_a,
            level_b=sum_b / len_b,
            ways_a=tuple(sorted(set(ways_a))),
            ways_b=tuple(sorted(set(ways_b))),
        )
        if finding.gap >= min_gap - 1e-9:
            findings.append(finding)
    return sorted(findings, key=lambda f: (-f.gap, -(f.miles_a + f.miles_b), f.side_a, f.side_b))


def _mi(miles: float) -> str:
    return f"{miles:.2f} mi ({miles * M_PER_MI / 1000:.2f} km)"


def markdown(findings: Sequence[Finding], within_mi: float, min_mi: float) -> str:
    lines = [
        "# Cross-border consistency",
        "",
        f"Like roads within {within_mi:g} mi ({within_mi * M_PER_MI / 1000:.1f} km) of a "
        f"border, with at least {min_mi:g} mi ({min_mi * M_PER_MI / 1000:.1f} km) on each "
        "side, whose length-weighted levels differ by a step or more.",
        "",
        f"{len(findings)} finding(s).",
        "",
    ]
    if findings:
        lines += [
            "| Border | Road profile | Side A | Side B | Gap | Ways A | Ways B |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for f in findings:
            lines.append(
                f"| {f.side_a} / {f.side_b} | {describe(f.profile)} "
                f"| LTS {f.level_a:.1f} over {_mi(f.miles_a)} "
                f"| LTS {f.level_b:.1f} over {_mi(f.miles_b)} "
                f"| {f.gap:.1f} | {_ways(f.ways_a)} | {_ways(f.ways_b)} |"
            )
    return "\n".join(lines) + "\n"


def _ways(ways: Sequence[int], limit: int = 5) -> str:
    shown = ", ".join(str(w) for w in ways[:limit])
    return shown + (f" and {len(ways) - limit} more" if len(ways) > limit else "")


CSV_FIELDS = (
    "side_a",
    "side_b",
    "profile",
    "level_a",
    "level_b",
    "gap",
    "miles_a",
    "km_a",
    "miles_b",
    "km_b",
    "ways_a",
    "ways_b",
)


def write_csv(findings: Sequence[Finding], path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_FIELDS)
        for f in findings:
            writer.writerow(
                [
                    f.side_a,
                    f.side_b,
                    describe(f.profile),
                    f"{f.level_a:.2f}",
                    f"{f.level_b:.2f}",
                    f"{f.gap:.2f}",
                    f"{f.miles_a:.3f}",
                    f"{f.miles_a * M_PER_MI / 1000:.3f}",
                    f"{f.miles_b:.3f}",
                    f"{f.miles_b * M_PER_MI / 1000:.3f}",
                    " ".join(str(w) for w in f.ways_a),
                    " ".join(str(w) for w in f.ways_b),
                ]
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--areas", type=Path, required=True)
    parser.add_argument("--name-field", default="name")
    parser.add_argument("--within-mi", type=float, default=2.0)
    parser.add_argument("--min-mi", type=float, default=0.5)
    parser.add_argument("--min-gap", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    collection = json.loads(args.areas.read_text())
    lat0 = sg.shape(collection["features"][0]["geometry"]).centroid.y
    project = projector(lat0)
    areas = load_areas(collection, args.name_field, project)
    with args.segments.open(newline="") as handle:
        segments = load_segments(csv.DictReader(handle), project)
    findings = compare(
        segments, areas, args.within_mi * M_PER_MI, args.min_mi * M_PER_MI, args.min_gap
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "cross-border.md").write_text(markdown(findings, args.within_mi, args.min_mi))
    write_csv(findings, args.out / "cross-border.csv")
    sys.stdout.write(f"{len(findings)} finding(s); wrote {args.out}/cross-border.md and .csv\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
