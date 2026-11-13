"""People, homes and jobs within half a mile of a road (`routemaker.setting`), for the road
panel's Setting line (the owner, 2026-11-13)."""

from __future__ import annotations

import gzip
import struct
import zipfile

import pytest

from routemaker import setting


def dbf(fields, records) -> bytes:
    """A minimal dBASE III table: (name, width) fields, string records."""
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(width for _, width in fields)
    out = bytearray(struct.pack("<BBBBIHH", 3, 120, 1, 1, len(records), header_len, record_len))
    out += bytes(20)
    for name, width in fields:
        out += name.encode().ljust(11, b"\0") + b"C" + bytes(4) + bytes([width, 0]) + bytes(14)
    out += b"\r"
    for record in records:
        out += b" " + b"".join(
            str(value).encode().ljust(width)
            for value, (_, width) in zip(record, fields, strict=True)
        )
    out += b"\x1a"
    return bytes(out)


FIELDS = [("GEOID20", 15), ("INTPTLAT20", 11), ("INTPTLON20", 12), ("POP20", 9), ("HOUSING20", 9)]


def test_reads_block_people_homes_and_points_from_a_tiger_zip(tmp_path):
    path = tmp_path / "tl_2020_11_tabblock20.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "tl_2020_11_tabblock20.dbf",
            dbf(FIELDS, [("110010001011000", "+38.9000000", "-077.0300000", "120", "60")]),
        )
        archive.writestr("tl_2020_11_tabblock20.shp", b"ignored")
    assert list(setting.block_rows(path)) == [("110010001011000", -77.03, 38.9, 120, 60)]


def test_a_deleted_dbf_record_is_skipped():
    data = bytearray(
        dbf(FIELDS, [("1", "+38.9", "-77.0", "1", "1"), ("2", "+38.9", "-77.0", "2", "2")])
    )
    header_len, record_len = struct.unpack("<HH", data[8:12])
    data[header_len] = ord("*")
    assert [row["GEOID20"] for row in setting.read_dbf(bytes(data))] == ["2"]


def test_reads_jobs_per_block_from_a_lodes_wac_file(tmp_path):
    path = tmp_path / "dc_wac_S000_JT00_2023.csv.gz"
    with gzip.open(path, "wt") as out:
        out.write("w_geocode,C000,CA01\n110010001011000,71,21\n110010001011001,5,1\n")
    assert setting.wac_jobs(path) == {"110010001011000": 71, "110010001011001": 5}


def test_counts_blocks_whose_point_lies_within_half_a_mile_of_the_way():
    # A way about 900 m long running east at 39 N; one degree of latitude is about 111 km.
    way = (7, [(-77.0, 39.0), (-76.99, 39.0)])
    near = (-76.995, 39.0 + 700 / 111_133, 100, 40, 10)  # 700 m north of the middle
    far = (-76.995, 39.0 + 900 / 111_133, 1_000, 400, 100)  # 900 m north: beyond
    out = setting.count_around([way], [near, far])
    people, homes, jobs, sq_mi = out[7]
    assert (people, homes, jobs) == (100, 40, 10)
    # A corridor: the half-mile circle plus the way's length times a mile.
    length_mi = 0.01 * 111_133 * 0.7771 / 1_609.344
    assert sq_mi == pytest.approx(setting.CIRCLE_SQ_MI + length_mi, rel=0.01)


def test_a_way_with_one_point_is_not_counted():
    assert setting.count_around([(1, [(-77.0, 39.0)])], [(-77.0, 39.0, 5, 5, 5)]) == {}


@pytest.mark.parametrize(
    ("people", "jobs", "expected"),
    [
        (10, 10, "remote"),
        (300, 100, "rural"),
        (2_000, 1_000, "suburban"),
        (3_000, 1_000, "urban"),
        (500, 25_000, "dense"),
    ],
)
def test_bands_by_people_and_jobs_a_square_mile(people, jobs, expected):
    assert setting.band(people, jobs, 1.0) == expected


def test_no_area_gives_no_band():
    assert setting.band(10, 10, 0) is None


@pytest.mark.parametrize(
    ("count", "said"),
    [
        (0, "under 10"),
        (9.6, "under 10"),
        (12, "about 12"),
        (3_249, "about 3,200"),
        (193_501, "about 190,000"),
    ],
)
def test_counts_are_said_to_two_figures(count, said):
    assert setting.about(count) == said


def test_panel_columns():
    assert setting.panel_columns(None) == dict.fromkeys(
        ("setting_people", "setting_homes", "setting_jobs", "setting_sq_mi")
    )
    assert setting.panel_columns([5, 2, 9, 0.8]) == {
        "setting_people": 5,
        "setting_homes": 2,
        "setting_jobs": 9,
        "setting_sq_mi": 0.8,
    }
