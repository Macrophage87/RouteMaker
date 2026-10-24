"""A kept line checked against the closures in force now (v0.7.0 plan, "GPX export as close to
identical as possible, closure warning first", with its correction): POST /api/closures/check.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from core import workzones
from routemaker import workzones as wz

# A straight east-west line about 1.7 km long in Washington, and a closure along its middle.
LINE = [[-77.0400 + i * 0.002, 38.9000] for i in range(11)]
ALONG = tuple((-77.0350 + i * 0.001, 38.9000) for i in range(6))
ACROSS = ((-77.0300, 38.8950), (-77.0300, 38.9050))
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def zone(zone_id, kind, line, end=None, start=None):
    return wz.Zone(zone_id, "md", kind, 0, line, "Main Street", None, start, end)


@pytest.fixture
def zones(monkeypatch):
    def use(*found):
        snap = workzones.Snapshot(tuple(found), {"md": workzones.CURRENT})
        monkeypatch.setattr(workzones, "snapshot", lambda now=None: snap)

    return use


def test_a_closure_along_the_line_is_named_with_its_stretch(zones) -> None:
    zones(zone("md-1", wz.CLOSED, ALONG, end=NOW + timedelta(days=30)))
    found = workzones.closures_on(LINE, NOW)
    assert [c["id"] for c in found["closures"]] == ["md-1"]
    c = found["closures"][0]
    assert 300 < c["from_m"] < c["to_m"] < 1000
    assert c["text"].startswith("Main Street, from ")
    assert " mi (" in c["text"] and "until Nov 14, 2026" in c["text"]
    assert found["unchecked"] is None


def test_a_penalty_a_crossing_and_an_ended_closure_are_not_closures(zones) -> None:
    zones(
        zone("md-p", wz.PENALTY, ALONG),
        zone("md-x", wz.CLOSED, ACROSS),
        zone("md-e", wz.CLOSED, ALONG, end=NOW - timedelta(hours=1)),
        zone("md-f", wz.CLOSED, ALONG, start=NOW + timedelta(days=1)),
    )
    assert workzones.closures_on(LINE, NOW)["closures"] == []


def test_every_lane_closed_counts_as_a_closure(zones) -> None:
    zones(zone("md-u", wz.UNKNOWN, ALONG))
    assert [c["kind"] for c in workzones.closures_on(LINE, NOW)["closures"]] == [wz.UNKNOWN]


@pytest.mark.django_db
def test_the_endpoint(client, zones) -> None:
    zones(zone("md-1", wz.CLOSED, ALONG))
    headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.11"}
    r = client.post(
        "/api/closures/check",
        data=json.dumps({"line": LINE}),
        content_type="application/json",
        **headers,
    )
    assert r.status_code == 200 and len(r.json()["closures"]) == 1
    bad = client.post(
        "/api/closures/check",
        data=json.dumps({"line": [[-77.0, 38.9]]}),
        content_type="application/json",
        **headers,
    )
    assert bad.status_code == 400


@pytest.mark.parametrize(
    "a,b,meets",
    [
        ((-77.10, 38.90), (-76.90, 38.90), True),  # both ends outside, the middle crosses the view
        ((-77.01, 38.90), (-77.30, 38.90), True),  # one end inside
        ((-77.10, 38.80), (-76.90, 38.80), False),  # passes south of the view
        ((-77.10, 38.95), (-77.04, 38.85), False),  # runs west of the view
        ((-77.00, 38.90), (-77.00, 38.90), True),  # a point in the view
    ],
)
def test_a_closure_shows_where_its_line_crosses_the_view(a, b, meets) -> None:
    # The v0.12.0 end review: a closure fed as only its two ends was dropped from a view zoomed
    # in on its middle, as no point of its line was in it.
    assert workzones._meets_box(a, b, (-77.02, 38.88, -76.98, 38.92)) is meets
