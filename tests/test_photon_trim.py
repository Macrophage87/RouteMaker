"""scripts/photon_trim.py: the US Photon dump, cut to the coverage box.

The dump's line shapes here are the real ones, copied in miniature from the
head of photon-dump-usa-1.0-latest.jsonl.zst (2026-09-21): a header, a
`CountryInfo` line, then one `Place` line per place with `centroid` [lon, lat].
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import photon_trim  # noqa: E402

BBOX = tuple(settings.COVERAGE_BBOX)

HEADER = (
    b'{"type":"NominatimDumpFile","content":{"version":"0.1.0","generator":"photon",'
    b'"database_version":"1.0.0-4","data_timestamp":"2026-09-19T23:03:26.000+00:00",'
    b'"features":{"sorted_by_country":true,"has_addresslines":false}}}\n'
)
COUNTRY = (
    b'{"type":"CountryInfo","content":[{"country_code":"us","name":{"name":"United States"}}]}\n'
)


def place(*centroids, name="Somewhere") -> bytes:
    content = [
        {
            "place_id": str(i),
            "object_type": "N",
            "object_id": i,
            "osm_key": "tourism",
            "osm_value": "attraction",
            "name": {"name": name},
            "country_code": "us",
            "centroid": list(c),
            "bbox": [c[0], c[1], c[0], c[1]],
            "geometry": {"type": "Point", "coordinates": list(c)},
        }
        for i, c in enumerate(centroids)
    ]
    return json.dumps({"type": "Place", "content": content}, separators=(",", ":")).encode() + b"\n"


LINCOLN = (-77.0502, 38.8893)
PURCELLVILLE = (-77.7147, 39.1368)
BALTIMORE = (-76.6158, 39.3072)
HONOLULU = (-157.8583, 21.3069)
PHILADELPHIA = (-75.1652, 39.9526)


def run(lines):
    counts = photon_trim.Counts()
    return list(photon_trim.trim(lines, BBOX, counts)), counts


def test_places_in_the_region_are_kept_and_the_rest_dropped() -> None:
    lines = [place(LINCOLN), place(HONOLULU), place(PURCELLVILLE), place(PHILADELPHIA)]
    kept, counts = run(lines)
    assert kept == [lines[0], lines[2]]
    assert counts.kept == 2


def test_the_header_and_country_lines_pass_unchanged_and_in_order() -> None:
    kept, counts = run([HEADER, COUNTRY, place(HONOLULU), place(BALTIMORE)])
    assert kept[:2] == [HEADER, COUNTRY]
    assert counts.passed == 2


def test_a_kept_line_is_byte_for_byte_the_original() -> None:
    line = place(LINCOLN, name='Quote " and, comma [bracket]')
    assert run([line])[0] == [line]


@pytest.mark.parametrize(
    "corner",
    [(BBOX[0], BBOX[1]), (BBOX[2], BBOX[3]), (BBOX[0], BBOX[3]), (BBOX[2], BBOX[1])],
)
def test_the_box_edges_are_inside(corner) -> None:
    assert len(run([place(corner)])[0]) == 1


@pytest.mark.parametrize(
    "just_outside",
    [
        (BBOX[0] - 1e-6, 39.0),
        (BBOX[2] + 1e-6, 39.0),
        (-77.0, BBOX[1] - 1e-6),
        (-77.0, BBOX[3] + 1e-6),
    ],
)
def test_just_outside_each_edge_is_dropped(just_outside) -> None:
    assert run([place(just_outside)])[0] == []


def test_a_line_with_any_centroid_inside_is_kept() -> None:
    assert len(run([place(HONOLULU, BALTIMORE)])[0]) == 1


def test_a_place_with_no_readable_centroid_is_dropped_and_counted() -> None:
    broken = b'{"type":"Place","content":[{"name":{"name":"x"},"centroid":["a","b"]}]}\n'
    missing = b'{"type":"Place","content":[{"name":{"name":"y"}}]}\n'
    kept, counts = run([broken, missing])
    assert kept == []
    assert counts.unreadable == 2


def test_a_non_place_line_mentioning_place_is_not_taken_for_one() -> None:
    line = b'{"type":"CountryInfo","content":[{"extra":{"type":"Place"},"name":{"name":"x"}}]}\n'
    assert run([line])[0] == [line]


def test_blank_lines_are_dropped() -> None:
    assert run([b"\n", b"  \n"])[0] == []


@pytest.mark.parametrize("bad", ["1,2,3", "-77,39,-78,40", "-78,40,-77,39", "a,b,c,d"])
def test_a_box_that_is_not_one_is_refused(bad) -> None:
    with pytest.raises((SystemExit, ValueError)):
        photon_trim.main([f"--bbox={bad}", "-"])


def test_the_command_reads_stdin_and_writes_what_it_keeps(tmp_path) -> None:
    dump = tmp_path / "dump.jsonl"
    dump.write_bytes(HEADER + place(LINCOLN) + place(HONOLULU))
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "photon_trim.py"),
            "-",
            "--bbox=" + ",".join(map(str, BBOX)),
        ],
        stdin=dump.open("rb"),
        capture_output=True,
        check=True,
    )
    assert done.stdout == HEADER + place(LINCOLN)
    assert b"kept 1" in done.stderr


def test_the_import_script_trims_to_the_coverage_box() -> None:
    """scripts/import_photon.sh hands photon_trim the box; it must be the
    settings' box, or the index covers somewhere the map does not."""
    script = (ROOT / "scripts" / "import_photon.sh").read_text()
    (value,) = re.findall(r'^BBOX="([^"]+)"', script, flags=re.MULTILINE)
    assert tuple(float(x) for x in value.split(",")) == BBOX


def test_the_import_script_names_only_the_approved_dump() -> None:
    """The owner approved one download (PLAN.md:65, amendment of 2026-09-27);
    the script fetches nothing itself and says which file it expects."""
    script = (ROOT / "scripts" / "import_photon.sh").read_text()
    assert "photon-dump-usa-1.0-latest.jsonl.zst" in script
    assert not re.search(r"^\s*(curl|wget)\b", script, flags=re.MULTILINE)


def script() -> str:
    return (ROOT / "scripts" / "import_photon.sh").read_text()


def test_the_import_reaches_no_network() -> None:
    """The import has the dump already; with no network nothing in the image
    can fetch a planet index behind its back."""
    assert re.search(r"^\s*--network none \\$", script(), flags=re.MULTILINE)


def test_the_import_refuses_any_file_but_a_photon_10_dump() -> None:
    patterns = re.findall(r"^(\S+)\) ;;$", script(), flags=re.MULTILINE)
    assert patterns == ["photon-dump-*-1.0-*.jsonl.zst"]
    assert re.search(r"^\*\)$", script(), flags=re.MULTILINE), "anything else falls to the refusal"


def test_the_dump_is_checked_against_its_md5_and_a_missing_md5_stops_it() -> None:
    body = script()
    assert 'md5sum -c "$(basename "$dump").md5"' in body
    missing = body[body.index('if [ -f "$dump.md5" ]; then') :]
    missing = missing[missing.index("else") : missing.index("fi")]
    assert re.search(r"exit [1-9]", missing), "a dump with no .md5 is not imported unchecked"


def test_an_existing_index_directory_is_never_built_over() -> None:
    body = script()
    guard = body[body.index('if [ -e "$index" ]; then') :]
    assert "exit 73" in guard[: guard.index("\nfi\n")]


def test_the_import_runs_in_the_serving_limit_with_no_swap() -> None:
    body = script()
    assert "--memory 3g --memory-swap 3g" in body


def test_names_are_imported_in_the_languages_the_api_allows() -> None:
    (value,) = re.findall(r'^LANGUAGES="([^"]+)"', script(), flags=re.MULTILINE)
    assert tuple(value.split(",")) == tuple(settings.PHOTON_LANGUAGES)
    assert "-languages $LANGUAGES" in script()


def test_it_streams_rather_than_reading_the_dump_whole() -> None:
    """A 5 GB compressed dump cannot be read into memory; trim is lazy."""
    consumed = []

    def lines():
        for line in (HEADER, place(LINCOLN), place(HONOLULU)):
            consumed.append(line)
            yield line

    first = next(photon_trim.trim(lines(), BBOX))
    assert first == HEADER
    assert len(consumed) == 1
