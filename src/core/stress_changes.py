"""Where a new build's stress tiers differ from the live one's, by county.

The owner, 2026-10-16: after each rebuild lands in staging, report where stress
ratings changed, with "totals by county", before staging is promoted
(plans/v0.7.0-review-fixes.md, "Every rebuild: stress change report"). The
`jurisdiction` table cannot answer that: it is filled by hand in the admin's
Jurisdiction page, its layers are state, police, right of way and park manager
(no county), and on the owner's PC it was empty at the v0.7.0 staging import. So
the counties come from a file of their own, `<DATA_ROOT>/reference/counties.geojson`
(Census TIGER county polygons, written by `scripts/install_reference_data.py
--counties`), and without it the report gives the region's totals and says how to
install it.

Read-only. Segments are paired by (`osm_way_id`, `ordinal`); a way only one of the
two tables has is not a change of tier and is not counted. A segment is placed in
the county that holds its midpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.db import connection

COUNTIES_FILE = "counties.geojson"
METRES_PER_MILE = 1609.344
# Census state FIPS codes to postal codes, for the states the coverage reaches.
STATE_FIPS = {"10": "DE", "11": "DC", "24": "MD", "42": "PA", "51": "VA", "54": "WV"}
NO_COUNTY = "(no county)"
INSTALL_COUNTIES = (
    "python scripts/install_reference_data.py --data-root <DATA_ROOT> "
    "--counties tl_2024_us_county.geojson"
)


@dataclass(frozen=True)
class Change:
    county: str
    old: int
    new: int
    segments: int
    miles: float


def county_name(properties: dict) -> str:
    """'Montgomery County, MD' from a TIGER feature's properties."""
    name = properties.get("NAMELSAD") or properties.get("NAME") or properties.get("name") or "?"
    state = properties.get("STUSPS") or STATE_FIPS.get(str(properties.get("STATEFP", "")))
    return f"{name}, {state}" if state else name


def load_counties(path: Path) -> list[tuple[str, str]]:
    """(name, GeoJSON geometry) per county in the file; empty where there is none."""
    if not path.is_file():
        return []
    document = json.loads(path.read_text())
    features = document.get("features", []) if isinstance(document, dict) else []
    return [
        (county_name(feature.get("properties") or {}), json.dumps(feature["geometry"]))
        for feature in features
        if feature.get("geometry")
    ]


def changes(live: str, staging: str, counties: list[tuple[str, str]]) -> list[Change]:
    """Every (county, old tier, new tier) with a segment that moved, largest first."""
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS stress_change_county")
        cursor.execute("CREATE TEMP TABLE stress_change_county (name text, geom geometry)")
        for name, geometry in counties:
            cursor.execute(
                "INSERT INTO stress_change_county VALUES "
                "(%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))",
                [name, geometry],
            )
        cursor.execute("CREATE INDEX ON stress_change_county USING gist (geom)")
        cursor.execute(
            f"""
            WITH moved AS (
                SELECT l.stress_tier AS old, s.stress_tier AS new,
                       ST_Length(s.geometry::geography) AS metres,
                       ST_LineInterpolatePoint(s.geometry, 0.5) AS mid
                FROM {staging}.segment s
                JOIN {live}.segment l USING (osm_way_id, ordinal)
                WHERE s.stress_tier <> l.stress_tier
            )
            SELECT coalesce(
                       (SELECT c.name FROM stress_change_county c
                        WHERE ST_Intersects(c.geom, moved.mid) ORDER BY c.name LIMIT 1),
                       %s) AS county,
                   old, new, count(*), coalesce(sum(metres), 0)
            FROM moved
            GROUP BY 1, 2, 3
            ORDER BY 5 DESC, 1, 2, 3
            """,
            [NO_COUNTY],
        )
        rows = cursor.fetchall()
        cursor.execute("DROP TABLE IF EXISTS stress_change_county")
    return [
        Change(county, old, new, segments, metres / METRES_PER_MILE)
        for county, old, new, segments, metres in rows
    ]


def summary(found: list[Change], with_counties: bool) -> list[str]:
    """The report's lines: the region's totals by change, then each county's."""
    lines = []
    total = sum(c.segments for c in found)
    miles = sum(c.miles for c in found)
    lines.append(f"stress changes, live -> staging: {total} segments, {miles:,.0f} mi")
    by_change: dict[tuple[int, int], list[float]] = {}
    for c in found:
        row = by_change.setdefault((c.old, c.new), [0, 0.0])
        row[0] += c.segments
        row[1] += c.miles
    for (old, new), (segments, mi) in sorted(by_change.items(), key=lambda kv: -kv[1][1]):
        lines.append(f"  LTS {old} -> {new}: {segments} segments, {mi:,.1f} mi")
    if not with_counties:
        lines.append(
            f"  no county totals: there is no reference/{COUNTIES_FILE}; install it with "
            f"{INSTALL_COUNTIES}"
        )
        return lines
    by_county: dict[str, list] = {}
    for c in found:
        by_county.setdefault(c.county, []).append(c)
    lines.append("by county:")
    for county, rows in sorted(by_county.items(), key=lambda kv: -sum(c.miles for c in kv[1])):
        parts = ", ".join(
            f"{c.old}->{c.new} {c.segments} ({c.miles:,.1f} mi)"
            for c in sorted(rows, key=lambda c: -c.miles)
        )
        lines.append(
            f"  {county}: {sum(c.segments for c in rows)} segments, "
            f"{sum(c.miles for c in rows):,.1f} mi; {parts}"
        )
    return lines


def report(live: str, staging: str, reference_dir: Path) -> list[str]:
    counties = load_counties(Path(reference_dir) / COUNTIES_FILE)
    return summary(changes(live, staging, counties), bool(counties))
