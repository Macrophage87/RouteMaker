"""scripts/build_tides.py: NOAA's predicted low tides for the beach path (the owner,
2026-11-23), read from a stand-in for NOAA."""

from __future__ import annotations

import importlib.util
import sys
import urllib.parse
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_tides.py"
spec = importlib.util.spec_from_file_location("build_tides", SCRIPT)
tides = importlib.util.module_from_spec(spec)
sys.modules["build_tides"] = tides
spec.loader.exec_module(tides)


def noaa(url: str) -> dict:
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q["datum"] == "MLLW" and q["time_zone"] == "gmt" and q["interval"] == "hilo"
    return {
        "predictions": [
            {"t": "2026-12-23 10:34", "v": "-1.269", "type": "L"},
            {"t": "2026-12-23 17:37", "v": "2.15", "type": "H"},
            {"t": "2026-12-23 22:18", "v": "1.404", "type": "L"},
        ]
    }


def test_only_the_low_tides_are_kept_in_utc_minutes_and_tenths_of_a_foot() -> None:
    data = tides.build(date(2026, 12, 23), 2, fetch=noaa)
    naples = next(s for s in data["stations"] if s["id"] == "8725110")
    assert naples["lows"] == [[29967034, -13], [29967738, 14]]
    assert len(data["stations"]) == len(tides.STATIONS)


def test_a_long_span_is_asked_for_a_year_at_a_time() -> None:
    asked = []

    def counting(url: str) -> dict:
        asked.append(dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query)))
        return {"predictions": []}

    tides.build(date(2026, 11, 23), 400, fetch=counting)
    first = [q for q in asked if q["station"] == "8725110"]
    assert [(q["begin_date"], q["end_date"]) for q in first] == [
        ("20261123", "20271122"),
        ("20271123", "20271228"),
    ]


def test_an_error_from_noaa_stops_the_build() -> None:
    with pytest.raises(ValueError, match="without predictions"):
        tides.build(date(2026, 11, 23), 1, fetch=lambda url: {"error": {"message": "No data"}})


def test_every_station_is_in_the_southwest_florida_box() -> None:
    from django.conf import settings

    west, south, east, north = settings.SOUTHWEST_FLORIDA_BBOX
    for _, _, lon, lat in tides.STATIONS:
        assert west <= lon <= east and south <= lat <= north
