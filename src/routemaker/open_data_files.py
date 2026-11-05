"""The public data download's files: a GeoPackage, CSV and GeoJSON, a README and the licence.

No database and no third-party library: a GeoPackage is an SQLite file with three metadata
tables and a geometry blob that is a short header in front of standard WKB (OGC GeoPackage
1.3, "Geometry Encoding"), so `sqlite3` writes it. `core.open_data_export` feeds the rows;
`routemaker.open_data` decides what they say. The spatial index is added afterwards by GDAL
where it is installed (`add_spatial_index`); without one, QGIS and ArcGIS still read the file.

Attribution lands where PLAN.md ("Licensing") puts it for each format: a header comment in
each CSV, a `licence` member in each GeoJSON, an `about` table in the GeoPackage, and the
README and LICENSE beside every file.
"""

from __future__ import annotations

import csv
import io
import json
import math
import shutil
import sqlite3
import struct
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import open_data

GPKG_APPLICATION_ID = 0x47504B47  # "GPKG"
GPKG_USER_VERSION = 10300  # 1.3.0
WGS84 = 4326

# WKB geometry type codes (2D).
_POINT, _LINESTRING, _MULTILINESTRING = 1, 2, 5
_TYPE_NAMES = {_POINT: "POINT", _LINESTRING: "LINESTRING", _MULTILINESTRING: "MULTILINESTRING"}


# --- WKB -----------------------------------------------------------------------------------


def point_wkb(lon: float, lat: float) -> bytes:
    return struct.pack("<BIdd", 1, _POINT, lon, lat)


def _coords(wkb: bytes, offset: int = 0) -> tuple[int, list[list[tuple[float, float]]], int]:
    """(type, parts of (x, y), next offset) for a 2D Point, LineString or MultiLineString."""
    order = "<" if wkb[offset] == 1 else ">"
    (kind,) = struct.unpack_from(order + "I", wkb, offset + 1)
    kind &= 0xFF  # an EWKB SRID flag or a Z flag is not expected; keep the base type
    offset += 5
    if kind == _POINT:
        x, y = struct.unpack_from(order + "dd", wkb, offset)
        return kind, [[(x, y)]], offset + 16
    if kind == _LINESTRING:
        (n,) = struct.unpack_from(order + "I", wkb, offset)
        offset += 4
        flat = struct.unpack_from(order + "d" * (2 * n), wkb, offset)
        return kind, [list(zip(flat[0::2], flat[1::2], strict=True))], offset + 16 * n
    if kind == _MULTILINESTRING:
        (n,) = struct.unpack_from(order + "I", wkb, offset)
        offset += 4
        parts: list[list[tuple[float, float]]] = []
        for _ in range(n):
            _k, sub, offset = _coords(wkb, offset)
            parts.extend(sub)
        return kind, parts, offset
    raise ValueError(f"unsupported WKB geometry type {kind}")


def parse_wkb(wkb: bytes) -> tuple[str, list[list[tuple[float, float]]]]:
    kind, parts, _ = _coords(bytes(wkb))
    return _TYPE_NAMES[kind], parts


def envelope(parts: Sequence[Sequence[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [x for part in parts for x, _ in part]
    ys = [y for part in parts for _, y in part]
    return min(xs), max(xs), min(ys), max(ys)


def gpkg_blob(wkb: bytes, srs_id: int = WGS84) -> bytes:
    """A GeoPackage geometry: "GP", version 0, flags (little-endian header, an [minx, maxx,
    miny, maxy] envelope), the SRS id, the envelope, then the WKB unchanged."""
    _kind, parts = parse_wkb(wkb)
    flags = 0b0000_0011
    return (
        b"GP"
        + bytes((0, flags))
        + struct.pack("<i", srs_id)
        + struct.pack("<4d", *envelope(parts))
        + bytes(wkb)
    )


def _fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def to_wkt(wkb: bytes) -> str:
    kind, parts = parse_wkb(wkb)

    def line(part):
        return ", ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in part)

    if kind == "POINT":
        x, y = parts[0][0]
        return f"POINT ({_fmt(x)} {_fmt(y)})"
    if kind == "LINESTRING":
        return f"LINESTRING ({line(parts[0])})"
    return "MULTILINESTRING (" + ", ".join(f"({line(p)})" for p in parts) + ")"


def to_geojson(wkb: bytes) -> dict:
    kind, parts = parse_wkb(wkb)

    def rounded(part):
        return [[round(x, 6), round(y, 6)] for x, y in part]

    if kind == "POINT":
        return {"type": "Point", "coordinates": rounded(parts[0])[0]}
    if kind == "LINESTRING":
        return {"type": "LineString", "coordinates": rounded(parts[0])}
    return {"type": "MultiLineString", "coordinates": [rounded(p) for p in parts]}


# --- GeoPackage ----------------------------------------------------------------------------

_GPKG_TYPES = {"INTEGER": "INTEGER", "REAL": "REAL", "TEXT": "TEXT", "BOOLEAN": "BOOLEAN"}


@dataclass
class _Layer:
    name: str
    geometry_type: str
    fields: tuple[tuple[str, str], ...]
    bounds: list[float] = field(default_factory=lambda: [math.inf, math.inf, -math.inf, -math.inf])
    count: int = 0


class GeoPackage:
    """Write-once GeoPackage: `layer(...)` then `add(...)` rows, then `close()`."""

    def __init__(self, path: Path) -> None:
        if path.exists():
            path.unlink()
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID}")
        self.db.execute(f"PRAGMA user_version = {GPKG_USER_VERSION}")
        self.db.executescript(
            """
            CREATE TABLE gpkg_spatial_ref_sys (
                srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY,
                organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
                definition TEXT NOT NULL, description TEXT);
            CREATE TABLE gpkg_contents (
                table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
                identifier TEXT UNIQUE, description TEXT DEFAULT '',
                last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER,
                CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)
                    REFERENCES gpkg_spatial_ref_sys(srs_id));
            CREATE TABLE gpkg_geometry_columns (
                table_name TEXT NOT NULL, column_name TEXT NOT NULL,
                geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
                z TINYINT NOT NULL, m TINYINT NOT NULL,
                CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
                CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
                CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
            """
        )
        self.db.executemany(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", None),
                ("Undefined geographic SRS", 0, "NONE", 0, "undefined", None),
                ("WGS 84 geodetic", WGS84, "EPSG", WGS84, _WGS84_WKT, "longitude/latitude"),
            ],
        )
        self.layers: dict[str, _Layer] = {}

    def layer(self, name: str, geometry_type: str, fields: tuple[tuple[str, str], ...],
              description: str) -> None:  # fmt: skip
        columns = ", ".join(f'"{n}" {_GPKG_TYPES[t]}' for n, t in fields)
        self.db.execute(
            f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT, '
            f"geom {geometry_type}, {columns})"
        )
        self.db.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) "
            "VALUES (?, 'features', ?, ?, ?)",
            (name, name, description, WGS84),
        )
        self.db.execute(
            "INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)",
            (name, geometry_type, WGS84),
        )
        self.layers[name] = _Layer(name, geometry_type, fields)

    def add(self, name: str, rows: Iterable[tuple[dict, bytes]]) -> int:
        layer = self.layers[name]
        names = [n for n, _ in layer.fields]
        sql = (
            f'INSERT INTO "{name}" (geom, {", ".join(chr(34) + n + chr(34) for n in names)}) '
            f"VALUES (?{', ?' * len(names)})"
        )
        batch: list[tuple] = []
        added = 0
        for values, wkb in rows:
            blob = gpkg_blob(wkb)
            minx, maxx, miny, maxy = struct.unpack_from("<4d", blob, 8)
            b = layer.bounds
            b[0], b[1], b[2], b[3] = (
                min(b[0], minx),
                min(b[1], miny),
                max(b[2], maxx),
                max(b[3], maxy),
            )
            batch.append((blob, *(_sql_value(values.get(n)) for n in names)))
            if len(batch) >= 5000:
                self.db.executemany(sql, batch)
                added += len(batch)
                batch.clear()
        if batch:
            self.db.executemany(sql, batch)
            added += len(batch)
        layer.count += added
        return added

    def about(self, rows: Sequence[tuple[str, str]]) -> None:
        """A table of plain text: the licence, the credits, what is linked and not included."""
        self.db.execute('CREATE TABLE "about" (fid INTEGER PRIMARY KEY, item TEXT, text TEXT)')
        self.db.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier, description) "
            "VALUES ('about', 'attributes', 'about', 'Licence, credits and sources')"
        )
        self.db.executemany('INSERT INTO "about" (item, text) VALUES (?, ?)', rows)

    def close(self) -> None:
        for layer in self.layers.values():
            if layer.count:
                self.db.execute(
                    "UPDATE gpkg_contents SET min_x = ?, min_y = ?, max_x = ?, max_y = ? "
                    "WHERE table_name = ?",
                    (*layer.bounds, layer.name),
                )
        self.db.commit()
        self.db.close()


def _sql_value(value):
    if isinstance(value, bool):
        return int(value)
    return value


_WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,'
    'AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]]'
)


def add_spatial_index(path: Path, layers: Iterable[str]) -> list[str]:
    """An R-tree index on each layer, by GDAL's `ogrinfo` where it is installed (the api image
    has it). Returns the layers indexed; none where GDAL is missing or refuses."""
    ogrinfo = shutil.which("ogrinfo")
    if ogrinfo is None:
        return []
    done = []
    for name in layers:
        result = subprocess.run(
            [ogrinfo, "-q", str(path), "-sql", f"SELECT CreateSpatialIndex('{name}', 'geom')"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            done.append(name)
    return done


# --- CSV and GeoJSON -----------------------------------------------------------------------


def licence_line(layer: str) -> str:
    rack = {
        "racks_ddot": "DDOT Public Bike Racks, DC Open Data, CC BY 4.0",
        "racks_baltimore": "Baltimore City DOT, open under Baltimore City Code Art. 1 §9-1(h)",
    }.get(layer)
    if rack:
        return f"RouteMaker open data: {rack}. See README.md."
    return (
        "RouteMaker open data, ODbL 1.0 (" + open_data.ODBL_URL + "). "
        "© OpenStreetMap contributors and the sources in README.md."
    )


def _csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class CsvLayer:
    """One CSV: a `# licence` comment line, the header, then a row per feature with its
    geometry as WKT in the last column (`wkt`)."""

    def __init__(self, path: Path, layer: str, fields: tuple[tuple[str, str], ...]) -> None:
        self.file = path.open("w", newline="", encoding="utf-8")
        self.file.write("# " + licence_line(layer) + "\n")
        self.names = [n for n, _ in fields]
        self.writer = csv.writer(self.file)
        self.writer.writerow([*self.names, "wkt"])

    def add(self, rows: Iterable[tuple[dict, bytes]]) -> None:
        for values, wkb in rows:
            self.writer.writerow([*(_csv_value(values.get(n)) for n in self.names), to_wkt(wkb)])

    def close(self) -> None:
        self.file.close()


def write_geojson(path: Path, layer: str, rows: Iterable[tuple[dict, bytes]]) -> int:
    """A FeatureCollection with the licence in a top-level `licence` member (allowed by RFC
    7946 as a foreign member)."""
    count = 0
    with path.open("w", encoding="utf-8") as out:
        out.write('{"type":"FeatureCollection","licence":')
        out.write(json.dumps(licence_line(layer)))
        out.write(',"features":[\n')
        for values, wkb in rows:
            if count:
                out.write(",\n")
            feature = {"type": "Feature", "properties": values, "geometry": to_geojson(wkb)}
            out.write(json.dumps(feature, ensure_ascii=False, separators=(",", ":")))
            count += 1
        out.write("\n]}\n")
    return count


# --- README and LICENSE --------------------------------------------------------------------


def about_rows(built: str) -> list[tuple[str, str]]:
    rows = [
        ("built", built),
        ("licence", f"Open Database License 1.0 (ODbL), {open_data.ODBL_URL}"),
    ]
    rows += [("credit", credit) for credit in open_data.CREDITS]
    rows += [
        ("linked, not included", f"{name}: {url} ({why})")
        for name, url, why in open_data.LINKED_NOT_INCLUDED
    ]
    return rows


def readme(
    built: str,
    layers: dict[str, tuple[tuple[tuple[str, str], ...], int]],
    comparison: dict | None = None,
) -> str:
    """The README that travels with every file: what each layer and field is, the licence,
    the credits, and the sources linked rather than included."""
    out = io.StringIO()
    w = out.write
    w(f"# RouteMaker open data, {built}\n\n")
    w(
        "Traffic stress (LTS) ratings and bike facilities for every road and trail RouteMaker "
        "rates, from Washington, DC to Baltimore, with the reviewed rating rows, the long "
        "trails and bike parking. Coordinates are WGS 84 longitude/latitude (EPSG:4326). "
        "Distances are in miles, with kilometres beside them where it helps.\n\n"
    )
    w("## Files\n\n")
    w("- `routemaker-data.gpkg`: every layer in one GeoPackage (QGIS, ArcGIS Pro, GDAL).\n")
    w(
        "- `csv/<layer>.csv`: one CSV per layer, geometry as WKT in the `wkt` column. The "
        "first line is a licence comment starting with `#`: skip one line when importing.\n"
    )
    w(
        "- `geojson/<layer>.geojson`: every layer but `roads`, which is too large to be "
        "useful as GeoJSON (use the GeoPackage or the CSV).\n\n"
    )
    w("## Layers\n\n")
    for name, (fields, count) in layers.items():
        w(f"### {name} ({count:,} features)\n\n{open_data.LAYER_DESCRIPTIONS[name]}\n\n")
        w("| Field | Meaning |\n|---|---|\n")
        for field_name, _ in fields:
            w(f"| `{field_name}` | {open_data.FIELD_NOTES[field_name]} |\n")
        w("\n")
    if comparison:
        w("## How our ratings compare with each agency's\n\n")
        w(
            "Over the roads both rate: the agency's published level against RouteMaker's own "
            "(a reviewed row where there is one, else our formula). Miles, and the share of "
            "the miles both rate. Also in `agency-comparison.json`.\n\n"
        )
        for summary in comparison.values():
            w(f"### {summary['name']} ({summary['miles']:,} mi both rate)\n\n")
            w("| | Miles | Share |\n|---|---|---|\n")
            for key, label in open_data.COMPARE_BUCKETS:
                bucket = summary["buckets"][key]
                text = label.format(agency=summary["name"])
                w(f"| {text} | {bucket['miles']:,} | {bucket['percent']}% |\n")
            w("\n")
    w("## Licence\n\n")
    w(
        "This is a derivative of OpenStreetMap and is released under the Open Database "
        f"License 1.0 ({open_data.ODBL_URL}): you may share, adapt and build on it, as long "
        "as you credit the sources below and share what you derive from it under the same "
        "licence. The two Bike parking layers from DDOT and Baltimore City may also be used "
        "under their own terms (CC BY 4.0; Baltimore City Code Art. 1 §9-1(h)).\n\n"
    )
    w("## Credits\n\n")
    for credit in open_data.CREDITS:
        w(f"- {credit}\n")
    w("\n## Linked, not included\n\n")
    w(
        "We have no licence to pass these on as data, so they are linked instead. Every level "
        "here is RouteMaker's own; where we checked it against one of these, the row's "
        "`rated_by` or `why` says so, citing it (`md_count_linked` marks a Maryland count left "
        "out of `aadt`).\n\n"
    )
    for name, url, why in open_data.LINKED_NOT_INCLUDED:
        w(f"- **{name}**: <{url}>. {why}\n")
    w(
        "\n## No personal data\n\nNothing here comes from rides, riders or accounts: only the "
        "map's own tables and the public bike-parking file.\n"
    )
    return out.getvalue()


LICENSE_TEXT = (
    "RouteMaker open data is made available under the Open Database License 1.0:\n"
    f"{open_data.ODBL_URL}\n\n"
    "Any rights in individual contents of the database are licensed under the Database "
    "Contents License: https://opendatacommons.org/licenses/dbcl/1-0/\n\n"
    "Credits and the sources linked rather than included are in README.md.\n"
)


def built_stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%d")
