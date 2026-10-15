"""The read-only count tracer (scripts/analysis/trace_count.py).

The owner, 2026-10-12: West Old Baltimore Rd shows 4,201 along miles of road.
The tracer tells a long agency count line (the conflation following the
agency's own segment) from a count copied to a way no line is near.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest
from rebuild_fixtures import REPO

SCRIPT = REPO / "scripts" / "analysis" / "trace_count.py"

# A long state count line along an east-west road, a short one elsewhere with
# the same count, and an unrelated count near the first.
LONG = {
    "id": "sha-long",
    "aadt": 4201,
    "source": "state",
    "agency": "mdot-sha",
    "year": 2024,
    "coordinates": [[-77.40, 39.20], [-77.35, 39.20], [-77.30, 39.20]],
}
SHORT = {
    "id": "sha-short",
    "aadt": 4201,
    "source": "state",
    "agency": "mdot-sha",
    "year": 2023,
    "coordinates": [[-76.80, 39.00], [-76.799, 39.00]],
}
OTHER = {
    "id": "sha-other",
    "aadt": 950,
    "source": "state",
    "coordinates": [[-77.36, 39.21], [-77.35, 39.21]],
}


@pytest.fixture(scope="module")
def trace():
    spec = importlib.util.spec_from_file_location("trace_count", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def volume(tmp_path):
    path = tmp_path / "volume.json"
    path.write_text(json.dumps([LONG, SHORT, OTHER]))
    return path


def test_every_line_with_the_count_is_listed_longest_first(trace, volume) -> None:
    lines = trace.select(trace.load_volume(volume), aadt=4201)
    assert [line.feature_id for line in lines] == ["sha-long", "sha-short"]
    # 0.1 degree of longitude at 39.2 N is about 5.36 mi (8.6 km).
    assert 5.2 < lines[0].length_m / trace.M_PER_MI < 5.5


def test_near_a_point_keeps_only_the_lines_within_reach(trace, volume) -> None:
    lines = trace.select(trace.load_volume(volume), near=(-77.355, 39.205), radius_m=2000)
    assert {line.feature_id for line in lines} == {"sha-long", "sha-other"}


def test_a_way_along_the_line_is_told_from_one_far_from_it(trace, volume) -> None:
    lines = trace.select(trace.load_volume(volume), aadt=4201)
    rows = [
        # On the long line, 3 mi from its start: the agency's own segment.
        {"osm_way_id": "1", "name": "W Old Baltimore Rd", "volume_aadt": "4201",
         "wkt": "LINESTRING(-77.346 39.20001, -77.345 39.20001, -77.344 39.20001)"},
        # Half a mile north of every 4,201 line: what a copy by name would look like.
        {"osm_way_id": "2", "name": "W Old Baltimore Rd", "volume_aadt": "4201",
         "wkt": "MULTILINESTRING((-77.346 39.208, -77.345 39.208))"},
    ]  # fmt: skip
    checks = {c.osm_way_id: c for c in trace.check_ways(rows, lines)}
    assert checks[1].along_a_line and checks[1].nearest_feature == "sha-long"
    assert not checks[2].along_a_line
    assert 2600 < checks[2].gap_m * trace.FT_PER_M < 3000
    text = trace.report(lines, list(checks.values()))
    assert "1 lie beyond" in text
    assert "way 2 W Old Baltimore Rd: 0.55 mi (0.89 km), FAR from every line" in text
    assert "4,201 a day, mdot-sha (state), 2024, 5.3" in text


def test_the_command_line_reads_the_csv_and_prints_us_units_first(
    trace, volume, tmp_path, capsys
) -> None:
    segments = tmp_path / "ways.csv"
    segments.write_text(
        "osm_way_id,name,volume_aadt,volume_source,wkt\n"
        '7,W Old Baltimore Rd,4201,mdot-sha,"LINESTRING(-77.35 39.2, -77.349 39.2)"\n'
    )
    assert trace.main(["--volume", str(volume), "--aadt", "4201", "--segments", str(segments)]) == 0
    out = capsys.readouterr().out
    assert "2 agency count line(s)" in out
    assert "way 7 W Old Baltimore Rd: 0 ft (0 m), along sha-long" in out


def test_it_needs_something_to_trace(trace, volume) -> None:
    with pytest.raises(SystemExit):
        trace.main(["--volume", str(volume)])
