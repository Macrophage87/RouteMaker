"""The public data download (the owner, 2026-11-05: "offer a link to download all of our data
in common formats that could be readable by gis"): what each row says, what the licences keep
out ("For anything we don't hava license on, just link to it."), and that the files open."""

from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest
from django.db import connection

from routemaker import open_data
from routemaker import open_data_files as files

ACCESS = {"bicycle_no": (False, "Closed: no bicycles")}


def seg(**overrides) -> dict:
    row = {
        "osm_way_id": 7,
        "ordinal": 0,
        "stress_tier": 3,
        "stress_half": False,
        "stress_rule": "mixed traffic, 30 mph",
        "stress_ratings": None,
        "stress_adjustment_id": None,
        "stress_adjustment_note": None,
        "stress_adjustment_display": None,
        "volume_source": None,
        "volume_aadt": None,
        "volume_year": None,
    }
    row.update(overrides)
    return row


def ratings(used, formula=2, formula_half=False, agencies=()):
    return {
        "used": used,
        "formula": formula,
        "formula_half": formula_half,
        "agencies": [{"agency": a, "level": lvl} for a, lvl in agencies],
    }


class TestRatedBy:
    def test_the_formula_stands_where_no_one_else_rated_the_way(self):
        out = open_data.road_row(seg(), ACCESS)
        assert (out["lts"], out["rated_by"], out["formula_lts"]) == (3.0, "formula", 3.0)

    def test_an_owner_row_wins_with_its_half_step(self):
        row = seg(
            stress_tier=2,
            stress_half=True,
            stress_adjustment_id="arl-bci-quiet-w1",
            stress_computed_tier=3,
        )
        out = open_data.road_row(row, ACCESS)
        assert (out["lts"], out["rated_by"], out["formula_lts"]) == (2.5, "owner (reviewed)", 3.0)

    def test_avoid_is_five(self):
        assert open_data.road_row(seg(stress_tier=5), ACCESS)["lts"] == 5.0
        assert open_data.level_text(5.0) == "Avoid"
        assert open_data.level_text(2.5) == "LTS 2.5"
        assert open_data.level_text(None) == ""

    def test_where_the_review_kept_marylands_level_it_says_so(self):
        """The owner, 2026-11-05: "if our methodology agrees with MD SHA, we state our
        methodology and that it's in agreement", and "I had the whole map reviewed"."""
        row = seg(
            stress_tier=2,
            stress_half=True,
            stress_ratings=ratings("mdot-sha", 2, True, agencies=[("mdot-sha", 2.5)]),
        )
        out = open_data.road_row(row, ACCESS)
        assert (out["lts"], out["rated_by"]) == (2.5, "reviewed; agrees with MDOT SHA")

    def test_the_map_level_stands_and_the_formula_is_shown_beside_it(self):
        rule = "agency rating: MDOT SHA LTS 4; SHA's record: urban; 2 lanes; 12000 cars a day"
        row = seg(
            stress_tier=4,
            stress_rule=rule,
            stress_ratings=ratings("mdot-sha", 3, agencies=[("mdot-sha", 4)]),
        )
        out = open_data.road_row(row, ACCESS)
        assert (out["lts"], out["formula_lts"]) == (4.0, 3.0)
        assert out["rated_by"] == "reviewed; agrees with MDOT SHA"
        # SHA's record (its level and counts) is not handed on in a column.
        assert out["rule"] is None
        assert "SHA" not in json.dumps({k: v for k, v in out.items() if k != "rated_by"})
        assert out["moco_lts"] is None and out["ddot_lts"] is None

    def test_where_a_reviewed_row_differs_the_agency_is_named(self):
        row = seg(
            stress_tier=2,
            stress_adjustment_id="md-review-1",
            stress_ratings=ratings("owner", 3, agencies=[("mdot-sha", 4)]),
        )
        assert open_data.road_row(row, ACCESS)["rated_by"] == "owner (reviewed); MDOT SHA differs"

    def test_an_owner_row_carries_the_map_level_and_the_formula(self):
        row = open_data.owner_row(
            {"row_id": "md-review-1", "tier": 2, "computed_tier": 4, "formula": 3,
             "formula_half": True}
        )  # fmt: skip
        assert (row["lts"], row["formula_lts"], row["rated_by"]) == (2.0, 3.5, "owner (reviewed)")

    def test_each_agency_is_named(self):
        row = seg(
            stress_tier=4,
            stress_ratings=ratings("moco", 4, agencies=[("moco", 4), ("mdot-sha", 3)]),
        )
        assert open_data.road_row(row, ACCESS)["rated_by"] == (
            "reviewed; agrees with Montgomery County Planning; MDOT SHA differs"
        )


class TestRoadRow:
    def test_maryland_counts_are_linked_and_others_kept(self):
        md = open_data.road_row(
            seg(volume_source="mdot-sha", volume_aadt=39141, volume_year=2024), ACCESS
        )
        assert (md["aadt"], md["aadt_year"], md["aadt_source"]) == (None, None, None)
        assert md["md_count_linked"] is True
        dc = open_data.road_row(
            seg(volume_source="ddot", volume_aadt=12000, volume_year=2024), ACCESS
        )
        assert (dc["aadt"], dc["aadt_year"], dc["aadt_source"]) == (12000, 2024, "ddot")
        assert dc["md_count_linked"] is False

    def test_open_agency_levels_are_carried(self):
        row = seg(stress_ratings=ratings("ddot", agencies=[("ddot", 2.5), ("moco", 3)]))
        out = open_data.road_row(row, ACCESS)
        assert (out["ddot_lts"], out["moco_lts"]) == (2.5, 3.0)

    def test_why_notes_go_out_as_written_with_their_citations(self):
        """The owner, 2026-11-05: agency data is cited "In our why's", "Same with arlington"."""
        note = "Arlington's Bike Comfort Index calls this street Most Comfortable; we rate 1.5"
        row = seg(
            stress_adjustment_id="arl-bci-quiet-w1",
            stress_adjustment_note=note,
            stress_adjustment_display="map",
        )
        assert open_data.road_row(row, ACCESS)["why"] == note

    def test_a_route_only_note_stays_with_the_route(self):
        row = seg(
            stress_adjustment_id="x",
            stress_adjustment_note="Fast traffic at the merge",
            stress_adjustment_display="route_only",
        )
        assert open_data.road_row(row, ACCESS)["why"] is None
        row["stress_adjustment_display"] = "map"
        assert open_data.road_row(row, ACCESS)["why"] == "Fast traffic at the merge"

    def test_maryland_byways_leave_the_scenic_text(self):
        row = seg(scenic="Rustic Road (Montgomery County) · Old Main Streets Scenic Byway")
        assert open_data.road_row(row, ACCESS)["scenic"] == "Rustic Road (Montgomery County)"
        assert (
            open_data.road_row(seg(scenic="Catoctin Mountain Scenic Byway"), ACCESS)["scenic"]
            is None
        )

    def test_access_in_words(self):
        assert open_data.road_row(seg(bike_access_reason="bicycle_no"), ACCESS)["bike_access"] == (
            "Closed: no bicycles"
        )

    def test_every_field_is_filled_and_documented(self):
        out = open_data.road_row(seg(), ACCESS)
        assert list(out) == [name for name, _ in open_data.ROAD_FIELDS]
        every = {
            name
            for fields in (
                open_data.ROAD_FIELDS,
                open_data.OWNER_ROW_FIELDS,
                open_data.TRAIL_FIELDS,
                *open_data.RACK_FIELDS.values(),
            )
            for name, _ in fields
        }
        assert every <= set(open_data.FIELD_NOTES)


def test_rating_rows():
    row = open_data.owner_row(
        {"row_id": "dc-review-1", "tier": 2, "half": True, "length_m": 1609.344, "ways": 2}
    )
    assert (row["lts"], row["rated_by"], row["length_mi"]) == (2.5, "owner (reviewed)", 1.0)
    md = open_data.owner_row({"row_id": "mdot-sha-1", "tier": 4, "formula": 3})
    assert (md["lts"], md["formula_lts"]) == (4.0, 3.0)


def test_racks_split_by_source_and_keep_no_other_field():
    layers = open_data.rack_rows(
        [
            {"id": "dc123", "x": -77.0, "y": 38.9, "r": 2},
            {"id": "bc9", "x": -76.6, "y": 39.3, "r": 1, "cv": 1},
            {"id": "n555", "x": -77.1, "y": 38.95, "c": 8, "k": "l", "n": "Garage"},
            {"id": "zz1", "x": 0, "y": 0},
        ]
    )
    assert [f for f, *_ in layers["racks_ddot"]] == [{"ddot_id": "123", "racks": 2}]
    assert [f for f, *_ in layers["racks_baltimore"]] == [
        {"bcdot_id": "bc9", "racks": 1, "covered": True}
    ]
    osm = layers["racks_osm"][0][0]
    assert osm == {
        "osm_type": "node",
        "osm_id": 555,
        "capacity": 8,
        "kind": "lockers",
        "covered": False,
        "name": "Garage",
    }


def test_the_readme_links_every_source_left_out_and_names_no_server():
    text = files.readme("2026-11-05", {"roads": (open_data.ROAD_FIELDS, 3)})
    for name, url, _why in open_data.LINKED_NOT_INCLUDED:
        assert url in text and name in text
    assert "ODbL" in text and "OpenStreetMap" in text
    assert not re.search(r"routemakerdc|amazonaws", text, re.IGNORECASE)


def test_agency_comparison_against_the_map_level():
    """The owner, 2026-11-05: "Also put comparison charts for each if the agencies in the
    documentation"; the map's level is the reviewed one ("I had the whole map reviewed")."""
    cmp = open_data.Comparison()
    # The review kept MDOT SHA's 4: the same.
    cmp.add(
        seg(stress_tier=4, stress_ratings=ratings("mdot-sha", 3, agencies=[("mdot-sha", 4)])),
        1609.344,
    )
    # Montgomery's 5 is our 4.5; the map 4.5 too: the same.
    cmp.add(
        seg(stress_tier=4, stress_half=True,
            stress_ratings=ratings("moco", 4, True, agencies=[("moco", 5)])),
        1609.344,
    )  # fmt: skip
    # An owner row at 1 against DDOT's 3: DDOT two levels higher.
    cmp.add(
        seg(stress_tier=1, stress_adjustment_id="dc-review-1",
            stress_ratings=ratings("owner", 2, agencies=[("ddot", 3)])),
        3218.688,
    )  # fmt: skip
    # MDOT's 5 is a ban, not a level; a hidden way is not compared.
    cmp.add(seg(stress_ratings=ratings("mdot-sha", 4, agencies=[("mdot-sha", 5)])), 1609.344)
    cmp.add(seg(map_class="hidden", stress_ratings=ratings("ddot", 1, agencies=[("ddot", 4)])), 1e6)
    out = cmp.summary()
    assert out["mdot-sha"]["buckets"]["same"] == {"miles": 1.0, "percent": 100.0}
    assert out["moco"]["buckets"]["same"]["miles"] == 1.0
    assert out["ddot"]["buckets"]["agency_much_higher"]["miles"] == 2.0
    assert out["ddot"]["miles"] == 2.0
    assert out["mdot-sha"]["name"] == "MDOT SHA"
    assert "arlington" not in out  # not read this run


def test_arlington_comfort_reads_as_levels_one_to_four():
    """The owner, 2026-11-05: "For arlington go for comfort rating, assuming that LTS1 is
    "most comfortable" to LTS4 being "Not Recommended"". Unrated streets are not compared."""
    cmp = open_data.Comparison()
    cmp.add_arlington("Most Comfortable", seg(stress_tier=1, stress_half=True), 1609.344)
    cmp.add_arlington("Not Recommended", seg(stress_tier=4), 1609.344)
    cmp.add_arlington("Comfortable", seg(stress_tier=4), 1609.344)
    cmp.add_arlington("Background", seg(stress_tier=2), 1e6)
    cmp.add_arlington("Trail", seg(stress_tier=1), 1e6)
    out = cmp.summary()["arlington"]
    assert out["name"] == "Arlington County (Bike Comfort Index)"
    assert out["miles"] == 3.0
    assert out["buckets"]["ours_higher"]["miles"] == 1.0
    assert out["buckets"]["same"]["miles"] == 1.0
    assert out["buckets"]["ours_much_higher"]["miles"] == 1.0


# --- Files ---------------------------------------------------------------------------------

LINE = struct.pack("<BII4d", 1, 2, 2, -77.0, 38.9, -76.99, 38.91)


def test_wkb_to_wkt_and_geojson():
    assert files.to_wkt(LINE) == "LINESTRING (-77 38.9, -76.99 38.91)"
    assert files.to_geojson(files.point_wkb(-77.0, 38.9)) == {
        "type": "Point",
        "coordinates": [-77.0, 38.9],
    }
    multi = struct.pack("<BII", 1, 5, 1) + LINE
    assert files.to_wkt(multi) == "MULTILINESTRING ((-77 38.9, -76.99 38.91))"


def test_a_geopackage_that_gdal_and_sqlite_both_read(tmp_path: Path):
    path = tmp_path / "t.gpkg"
    gpkg = files.GeoPackage(path)
    gpkg.layer("roads", "LINESTRING", (("osm_way_id", "INTEGER"), ("trail", "BOOLEAN")), "Roads")
    assert gpkg.add("roads", [({"osm_way_id": 7, "trail": True}, LINE)]) == 1
    gpkg.about(files.about_rows("2026-11-05"))
    gpkg.close()
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA application_id").fetchone()[0] == files.GPKG_APPLICATION_ID
    blob, way, trail = db.execute("SELECT geom, osm_way_id, trail FROM roads").fetchone()
    assert blob[:2] == b"GP" and (way, trail) == (7, 1)
    assert blob[40:] == LINE  # 8-byte header and a 32-byte envelope, then the WKB as given
    extent = db.execute("SELECT min_x, max_y FROM gpkg_contents WHERE table_name='roads'")
    assert extent.fetchone() == (-77.0, 38.91)
    assert db.execute("SELECT count(*) FROM about WHERE item = 'licence'").fetchone()[0] == 1
    db.close()
    if shutil.which("ogrinfo"):
        assert files.add_spatial_index(path, ["roads"]) == ["roads"]
        info = subprocess.run(
            ["ogrinfo", "-ro", "-so", str(path), "roads"], capture_output=True, text=True
        )
        assert info.returncode == 0, info.stderr
        assert "Feature Count: 1" in info.stdout
        assert "EPSG" in info.stdout and "4326" in info.stdout


# --- The export, against a live table ------------------------------------------------------

db = pytest.mark.django_db(transaction=True)


def _insert(schema: str, way: int, **cols) -> None:
    base = {"stress_tier": 3, "stress_rule": "mixed traffic"}
    base.update(cols)
    names = ", ".join(base)
    marks = ", ".join(["%s"] * len(base))
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, {names}) VALUES "
            f"(%s, 0, ST_SetSRID(ST_MakeLine(ST_MakePoint(-77, 38.9), ST_MakePoint(-76.99, "
            f"38.9 + %s * 0.001)), 4326), {marks})",
            [way, way, *base.values()],
        )


@db
def test_the_export_end_to_end(segment_schemas, tmp_path: Path):
    from core import open_data_export

    live, _staging = segment_schemas
    _insert(live, 1)
    _insert(live, 2, volume_source="mdot-sha", volume_aadt=39141, volume_year=2024,
            stress_tier=4)  # fmt: skip
    _insert(live, 3, stress_tier=1, stress_half=True, stress_adjustment_id="arl-bci-quiet-w3",
            stress_computed_tier=2, stress_adjustment_direction="down",
            stress_adjustment_note="Arlington's Bike Comfort Index calls it Most Comfortable",
            stress_adjustment_display="map", trail_name="Custis Trail")  # fmt: skip
    racks = tmp_path / "racks.json"
    racks.write_text(json.dumps({"points": [{"id": "dc1", "x": -77.0, "y": 38.9, "r": 3}]}))
    out = tmp_path / "out"

    # Way 1 (LTS 3 on the map) runs along two short Arlington pieces, both "Comfortable"
    # (read as 2), neither covering 60% of it alone; one "Not Recommended" piece is shorter.
    def piece(x0, x1):
        y = lambda x: 38.9 + (x + 77) * 0.1  # noqa: E731 (on way 1's line)
        return json.dumps({"type": "LineString", "coordinates": [[x0, y(x0)], [x1, y(x1)]]})

    arlington = [
        ("Comfortable", piece(-77.0, -76.9955)),
        ("Comfortable", piece(-76.9955, -76.992)),
        ("Not Recommended", piece(-76.992, -76.99)),
    ]

    result = open_data_export.export(out, "2026-11-05", racks, arlington=arlington)

    assert result.counts == {
        "roads": 3,
        "rating_rows": 1,
        "trails": 1,
        "racks_ddot": 1,
        "racks_baltimore": 0,
        "racks_osm": 0,
    }
    folder = out / "routemaker-data-2026-11-05"
    text = (folder / "csv" / "roads.csv").read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    assert first.startswith("# RouteMaker open data, ODbL 1.0")
    header, *body = list(csv.reader(rest.splitlines()))
    by_way = {r[0]: dict(zip(header, r, strict=True)) for r in body}
    assert by_way["2"]["lts"] == "4.0" and by_way["2"]["aadt"] == ""
    assert by_way["2"]["md_count_linked"] == "true"
    assert by_way["3"]["why"] == "Arlington's Bike Comfort Index calls it Most Comfortable"
    assert "39141" not in (folder / "csv" / "roads.csv").read_text()
    assert not (folder / "geojson" / "roads.geojson").exists()
    trails = json.loads((folder / "geojson" / "trails.geojson").read_text())
    assert trails["features"][0]["properties"]["name"] == "Custis Trail"
    assert "ODbL" in trails["licence"]
    gpkg = sqlite3.connect(folder / "routemaker-data.gpkg")
    assert gpkg.execute("SELECT count(*) FROM roads").fetchone()[0] == 3
    gpkg.close()
    names = {z.name for z in result.zips}
    assert names == {f"routemaker-data-2026-11-05-{k}.zip" for k in ("gpkg", "csv", "geojson")}
    with zipfile.ZipFile(out / "routemaker-data-2026-11-05-csv.zip") as archive:
        assert "routemaker-data-2026-11-05/README.md" in archive.namelist()
    compared = json.loads((folder / "agency-comparison.json").read_text())
    assert set(compared["agencies"]) == {"moco", "ddot", "mdot-sha", "arlington"}
    arl = compared["agencies"]["arlington"]
    assert arl["buckets"]["ours_higher"]["percent"] == 100.0  # way 1 only, not 2 or 3
    assert "How our ratings compare" in (folder / "README.md").read_text()
    sums = (out / "routemaker-data-2026-11-05-SHA256SUMS").read_text().splitlines()
    assert len(sums) == 3


def test_the_export_reads_only_the_map():
    """No ride, rider, account, location or log table is named in the export (the project's
    privacy rule: nothing identifying is published)."""
    source = (Path(__file__).parents[1] / "src/core/open_data_export.py").read_text()
    tables = set(re.findall(r"FROM\s+\{?([\w.]+)\}?", source))
    # arlington_comfort is the temp table of Arlington's lines; nearby, a CTE over segment.
    allowed = {"schema", "schema}.segment", "information_schema.columns", "arlington_comfort",
               "nearby"}  # fmt: skip
    assert tables <= allowed, tables
    assert not re.search(r"\b(ride|rider|user|account|presence|access_log)s?\b\.", source)


def test_arlington_errors_never_give_a_partial_count(monkeypatch):
    """ArcGIS answers a failure with a 200 and an "error" member, or with a broken page: the
    export then leaves Arlington out (the command catches OSError) rather than count part."""
    import io
    import urllib.request

    from core import open_data_export

    pages = iter(
        [
            {"features": [{"properties": {"MapCode": "Comfortable"},
                           "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}],
             "exceededTransferLimit": True},
            {"error": {"code": 500, "message": "busy"}},
        ]
    )  # fmt: skip

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: Reply(json.dumps(next(pages)).encode())
    )
    with pytest.raises(OSError):
        open_data_export.fetch_arlington()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Reply(b"<html>"))
    with pytest.raises(OSError):
        open_data_export.fetch_arlington()
