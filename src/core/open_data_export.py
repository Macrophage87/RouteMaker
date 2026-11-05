"""Write the public data download from the live map tables (`manage.py export_open_data`).

Reads the live segment table and the bike-parking file, and nothing else: no ride, rider,
account, location or log table is named here, and a test holds that to be so. What each row
says, and what the licences keep out, is `routemaker.open_data`; the file formats are
`routemaker.open_data_files`. docs/OPERATIONS.md, "The open data download", is the procedure.

Out, in one folder named for the build date:

    routemaker-data-<date>/
        routemaker-data.gpkg        every layer
        csv/<layer>.csv             one per layer, geometry as WKT
        geojson/<layer>.geojson     every layer but roads
        README.md, LICENSE.md
        agency-comparison.json      our ratings against each agency's, miles (the docs' charts)
    routemaker-data-<date>-gpkg.zip, -csv.zip, -geojson.zip, SHA256SUMS

The zips are what goes on the GitHub data release (the owner, 2026-11-05: "GitHub
Releases"); uploading is the owner's step, after seeing the files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction

from routemaker import open_data
from routemaker import open_data_files as files

from .segment_info import ACCESS_WORDS

logger = logging.getLogger(__name__)

# The segment columns the road layer reads. A column a table from before it lacks is read
# as null (`_select`), so an older live table still exports.
ROAD_COLUMNS = (
    "osm_way_id",
    "ordinal",
    "stress_tier",
    "stress_half",
    "stress_rule",
    "stress_ratings",
    "stress_adjustment_id",
    "stress_adjustment_note",
    "stress_adjustment_display",
    "stress_computed_tier",
    "volume_source",
    "volume_aadt",
    "volume_year",
    "facility",
    "is_trail_class",
    "is_unpaved",
    "is_rough",
    "lit",
    "road_speed_mph",
    "road_lanes",
    "road_oneway",
    "bike_access_reason",
    "car_free_when",
    "map_class",
    "trail_name",
    "sidepath_name",
    "mtb_only",
    "mtb_level",
    "mtb_name",
    "walk_bike",
    "hazard",
    "scenic",
)


def _schema() -> str:
    return settings.SEGMENT_SCHEMA_LIVE


def live_columns(schema: str | None = None) -> frozenset[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'segment'",
            [schema or _schema()],
        )
        return frozenset(name for (name,) in cursor.fetchall())


def _select(columns: frozenset[str]) -> str:
    return ", ".join(
        (f"s.{name}" if name in columns else f"NULL AS {name}") for name in ROAD_COLUMNS
    )


def road_rows(
    schema: str | None = None, comparison: open_data.Comparison | None = None
) -> Iterator[tuple[dict, bytes]]:
    """Every segment of the live table as the road layer carries it, streamed; each added
    to `comparison` on the way past, where one is given."""
    schema = schema or _schema()
    columns = live_columns(schema)
    names = [*ROAD_COLUMNS, "length_m"]
    # Inside a transaction, so the server-side cursor is not declared WITH HOLD, which would
    # have PostgreSQL copy every row and its geometry before the first fetch.
    with transaction.atomic(), connection.chunked_cursor() as cursor:
        cursor.execute(
            f"SELECT {_select(columns)}, ST_Length(s.geometry::geography), "
            f"ST_AsBinary(s.geometry) FROM {schema}.segment s ORDER BY s.osm_way_id, s.ordinal"
        )
        while True:
            chunk = cursor.fetchmany(10_000)
            if not chunk:
                break
            for record in chunk:
                row = dict(zip(names, record[:-1], strict=True))
                if isinstance(row["stress_ratings"], str):
                    row["stress_ratings"] = json.loads(row["stress_ratings"])
                if comparison is not None:
                    comparison.add(row, row["length_m"] or 0.0)
                yield open_data.road_row(row, ACCESS_WORDS), bytes(record[-1])


def rating_rows(schema: str | None = None) -> Iterator[tuple[dict, bytes]]:
    """Each reviewed rating row, every way it covers collected into one feature."""
    schema = schema or _schema()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT stress_adjustment_id, max(stress_tier), bool_or(stress_half),
                       max(stress_computed_tier), max(stress_adjustment_direction),
                       max(stress_adjustment_category), max(stress_adjustment_note),
                       max(stress_adjustment_display),
                       max((stress_ratings->>'formula')::int),
                       bool_or((stress_ratings->>'formula_half')::boolean),
                       count(DISTINCT osm_way_id),
                       sum(ST_Length(geometry::geography)),
                       ST_AsBinary(ST_Multi(ST_Collect(geometry)))
                FROM {schema}.segment
                WHERE stress_adjustment_id IS NOT NULL
                GROUP BY stress_adjustment_id ORDER BY stress_adjustment_id"""
        )
        keys = (
            "row_id", "tier", "half", "computed_tier", "direction", "category", "note",
            "display", "formula", "formula_half", "ways", "length_m",
        )  # fmt: skip
        for record in cursor.fetchall():
            yield open_data.owner_row(dict(zip(keys, record[:-1], strict=True))), bytes(record[-1])


def trail_rows(schema: str | None = None) -> Iterator[tuple[dict, bytes]]:
    """The named long trails, one feature a name."""
    schema = schema or _schema()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT trail_name, sum(ST_Length(geometry::geography)),
                       sum(CASE WHEN is_unpaved THEN ST_Length(geometry::geography) ELSE 0 END)
                           / NULLIF(sum(ST_Length(geometry::geography)), 0),
                       count(DISTINCT osm_way_id),
                       ST_AsBinary(ST_Multi(ST_LineMerge(ST_Collect(geometry))))
                FROM {schema}.segment
                WHERE trail_name IS NOT NULL
                GROUP BY trail_name ORDER BY trail_name"""
        )
        for name, length_m, unpaved, ways, wkb in cursor.fetchall():
            row = {"name": name, "length_m": length_m, "unpaved_share": unpaved, "ways": ways}
            yield open_data.trail_row(row), bytes(wkb)


# A segment counts as on an Arlington comfort line where at least this share of it lies
# within this many metres of the line (cross streets touch only a few metres of it).
ARLINGTON_BUFFER_M = 12
ARLINGTON_SHARE = 0.6


def fetch_arlington(url: str = open_data.ARLINGTON_BCI_URL) -> list[tuple[str, str]]:
    """Arlington's comfort lines as (map code, GeoJSON geometry), read from the county's
    service for the comparison only; nothing of it is written to the download."""
    out: list[tuple[str, str]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "where": "MapCode IN ({})".format(
                    ", ".join(f"'{code}'" for code in open_data.ARLINGTON_COMFORT)
                ),
                "outFields": "MapCode",
                "outSR": 4326,
                "f": "geojson",
                "resultOffset": offset,
                "resultRecordCount": 2000,
            }
        )
        request = urllib.request.Request(
            f"{url}/query?{query}", headers={"User-Agent": "RouteMaker open data export"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (fixed https URL)
            page = json.load(response)
        features = page.get("features") or []
        for feature in features:
            code = (feature.get("properties") or {}).get("MapCode")
            if code in open_data.ARLINGTON_COMFORT and feature.get("geometry"):
                out.append((code, json.dumps(feature["geometry"])))
        if not features or not (
            page.get("exceededTransferLimit")
            or page.get("properties", {}).get("exceededTransferLimit")
        ):
            return out
        offset += len(features)


def arlington_comparison(
    lines: list[tuple[str, str]], comparison: open_data.Comparison, schema: str | None = None
) -> int:
    """Add each live segment that runs along one of Arlington's comfort lines to the
    comparison, against the line it runs along most. Returns the segments matched."""
    schema = schema or _schema()
    if not lines:
        return 0
    matched = 0
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE arlington_comfort (code text, g geometry) ON COMMIT DROP")
        cursor.executemany(
            "INSERT INTO arlington_comfort VALUES "
            "(%s, ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 26918))",
            lines,
        )
        cursor.execute("CREATE INDEX ON arlington_comfort USING gist (g)")
        cursor.execute("ANALYZE arlington_comfort")
        cursor.execute(
            f"""WITH area AS (
                    SELECT ST_Transform(ST_SetSRID(ST_Extent(g), 26918), 4326) AS box
                    FROM arlington_comfort),
                nearby AS (
                    SELECT seg.stress_tier, seg.stress_half, seg.map_class,
                           ST_Length(seg.geometry::geography) AS length_m,
                           ST_Transform(seg.geometry, 26918) AS g
                    FROM {schema}.segment seg, area
                    WHERE seg.geometry && area.box)
                SELECT s.stress_tier, s.stress_half, s.map_class, s.length_m, best.code
                FROM nearby s CROSS JOIN LATERAL (
                    SELECT a.code,
                           ST_Length(ST_Intersection(s.g, ST_Buffer(a.g, %s))) AS along
                    FROM arlington_comfort a
                    WHERE ST_DWithin(s.g, a.g, %s)
                    ORDER BY along DESC LIMIT 1) best
                WHERE best.along >= %s * ST_Length(s.g)""",
            [ARLINGTON_BUFFER_M, ARLINGTON_BUFFER_M, ARLINGTON_SHARE],
        )
        for tier, half, map_class, length_m, code in cursor.fetchall():
            row = {"stress_tier": tier, "stress_half": half, "map_class": map_class}
            comparison.add_arlington(code, row, length_m or 0.0)
            matched += 1
    return matched


def rack_points(path: Path) -> dict[str, list[tuple[dict, bytes]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        layer: [(fields, files.point_wkb(lon, lat)) for fields, lon, lat in points]
        for layer, points in open_data.rack_rows(data.get("points", ())).items()
    }


@dataclass
class Result:
    folder: Path
    counts: dict[str, int] = field(default_factory=dict)
    indexed: list[str] = field(default_factory=list)
    zips: list[Path] = field(default_factory=list)
    comparison: dict = field(default_factory=dict)

    def summary(self) -> str:
        counts = ", ".join(f"{name} {count:,}" for name, count in self.counts.items())
        index = "spatial index added" if self.indexed else "no spatial index (GDAL not found)"
        return f"{self.folder}: {counts}; {index}; {len(self.zips)} zips"


def export(
    out_dir: Path,
    built: str,
    racks: Path | None,
    schema: str | None = None,
    arlington: list[tuple[str, str]] | None = None,
) -> Result:
    """Write the download for `built` (a date) under `out_dir`. `arlington` is Arlington's
    comfort lines (`fetch_arlington`), for the comparison only; None leaves it out."""
    folder = out_dir / f"routemaker-data-{built}"
    (folder / "csv").mkdir(parents=True, exist_ok=True)
    (folder / "geojson").mkdir(exist_ok=True)
    result = Result(folder)
    comparison = open_data.Comparison()
    gpkg = files.GeoPackage(folder / "routemaker-data.gpkg")

    layers: list[tuple[str, str, tuple, object]] = [
        ("roads", "LINESTRING", open_data.ROAD_FIELDS, lambda: road_rows(schema, comparison)),
        ("rating_rows", "MULTILINESTRING", open_data.OWNER_ROW_FIELDS, lambda: rating_rows(schema)),
        ("trails", "MULTILINESTRING", open_data.TRAIL_FIELDS, lambda: trail_rows(schema)),
    ]
    if racks is not None and racks.exists():
        points = rack_points(racks)
        for name in open_data.RACK_LAYERS:
            layers.append(
                (name, "POINT", open_data.RACK_FIELDS[name], lambda name=name: iter(points[name]))
            )
    elif racks is not None:
        logger.warning("no bike-parking file at %s: the rack layers are left out", racks)

    for name, geometry, fields, source in layers:
        gpkg.layer(name, geometry, fields, open_data.LAYER_DESCRIPTIONS[name])
        table = files.CsvLayer(folder / "csv" / f"{name}.csv", name, fields)
        rows = []

        def tee(rows_in, table=table, keep=name != "roads", rows=rows):
            for item in rows_in:
                table.add((item,))
                if keep:
                    rows.append(item)
                yield item

        result.counts[name] = gpkg.add(name, tee(source()))
        table.close()
        if name != "roads":
            files.write_geojson(folder / "geojson" / f"{name}.geojson", name, rows)
    gpkg.about(files.about_rows(built))
    gpkg.close()
    result.indexed = files.add_spatial_index(gpkg.path, [n for n, *_ in layers])

    if arlington:
        arlington_comparison(arlington, comparison, schema)
    result.comparison = comparison.summary()
    (folder / "agency-comparison.json").write_text(
        json.dumps({"built": built, "agencies": result.comparison}, indent=1) + "\n",
        encoding="utf-8",
    )
    layer_fields = {name: (fields, result.counts[name]) for name, _g, fields, _s in layers}
    (folder / "README.md").write_text(
        files.readme(built, layer_fields, result.comparison), encoding="utf-8"
    )
    (folder / "LICENSE.md").write_text(files.LICENSE_TEXT, encoding="utf-8")

    common = [folder / "README.md", folder / "LICENSE.md", folder / "agency-comparison.json"]
    bundles = {
        "gpkg": [folder / "routemaker-data.gpkg"],
        "csv": sorted((folder / "csv").glob("*.csv")),
        "geojson": sorted((folder / "geojson").glob("*.geojson")),
    }
    for kind, members in bundles.items():
        target = out_dir / f"routemaker-data-{built}-{kind}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for member in [*members, *common]:
                archive.write(member, member.relative_to(out_dir))
        result.zips.append(target)
    sums = "".join(f"{_sha256(z)}  {z.name}\n" for z in result.zips)
    (out_dir / f"routemaker-data-{built}-SHA256SUMS").write_text(sums, encoding="utf-8")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
