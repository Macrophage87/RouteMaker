"""A Mass Ride never rides along street-running rails (OWNER-DECISIONS 289; routing hunt 4, R4-1).

The owner, 2026-10-03, amending 288: "Keep mass rides off H street". The rail streets near a
Mass Ride are left out of its requests, cut where a way crosses them so the rails are still
crossed; a point on one goes to the nearest cross street, and the answer says so. Other ride
types keep 288's LTS 4 price. The streets here are drawn after H Street NE and Benning Road
NE, not read from the map; the network is a fake and the database is real."""

from __future__ import annotations

import json
import math

import pytest
from django.db import connection
from test_route_api import segments  # noqa: F401 - the live segment table, a fixture

from core import mass_rails, routing

db = pytest.mark.django_db
pytestmark = pytest.mark.usefixtures("weekday_clock")

H_LAT = 38.9002
# The cross streets of the rail street, west to east (lon): 10th, 11th, 12th and 13th St NE.
CROSS_LONS = (-76.9960, -76.9932, -76.9905, -76.9870)
WEST, EAST = -76.9990, -76.9850
# Benning Road NE, on from H Street's east end.
BENNING = [(EAST, H_LAT), (-76.9750, 38.8990), (-76.9680, 38.8960)]
BENNING_CROSS_LON = -76.9800  # 15th St NE

# The hunt's trips: the H Street one ends on H Street NE near 13th St; the Benning Road one
# has neither end on a rail street.
H_STREET_TRIP = [[-77.0335, 38.899], [-76.9878, H_LAT]]
BENNING_TRIP = [[-77.0065, 38.8975], [-76.968, 38.894]]


def _insert(cursor, schema, way, ordinal, line, hazard=None) -> None:
    wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
    cursor.execute(
        f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
        "stress_rule, hazard) VALUES (%s, %s, ST_GeomFromText(%s, 4326), 2, 'test', %s)",
        [way, ordinal, wkt, hazard],
    )


def _benning_cut() -> tuple[float, float]:
    (x1, y1), (x2, y2) = BENNING[0], BENNING[1]
    return (BENNING_CROSS_LON, y1 + (y2 - y1) * (BENNING_CROSS_LON - x1) / (x2 - x1))


@pytest.fixture
def rail_streets(segments):  # noqa: F811 - the fixture, imported above
    """H Street NE with rails, split at its cross streets; the cross streets, each a block
    north and a block south of it, without; Benning Road NE with rails, and 15th St across."""
    stops = [WEST, *CROSS_LONS, EAST]
    with connection.cursor() as cursor:
        for ordinal, (a, b) in enumerate(zip(stops, stops[1:], strict=False)):
            _insert(cursor, segments, 900, ordinal, [(a, H_LAT), (b, H_LAT)], "rails")
        for n, lon in enumerate(CROSS_LONS):
            _insert(cursor, segments, 910 + n, 0, [(lon, H_LAT), (lon, H_LAT + 0.0012)])
            _insert(cursor, segments, 920 + n, 0, [(lon, H_LAT), (lon, H_LAT - 0.0012)])
        cut = _benning_cut()
        _insert(cursor, segments, 930, 0, [BENNING[0], cut], "rails")
        _insert(cursor, segments, 930, 1, [cut, BENNING[1]], "rails")
        _insert(cursor, segments, 930, 2, BENNING[1:], "rails")
        _insert(cursor, segments, 940, 0, [cut, (cut[0], cut[1] + 0.0012)])
        _insert(cursor, segments, 941, 0, [cut, (cut[0], cut[1] - 0.0012)])
    return segments


def _inside(point, ring) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _covered(point, rings) -> bool:
    return any(_inside(point, ring) for ring in rings)


def _plan(client, monkeypatch, points, preset="mass-ride", refuse_rails=False, **extra):
    from test_route_api import VERTICES, FakeRouter, post, route_answer, trace_answer

    def route(payload):
        if refuse_rails and payload.get("exclude_polygons"):
            return routing.RouterRefused(400, 442, "No path could be found for input")
        return route_answer([(VERTICES, 2.2, [10.0] * 5)])

    fake = FakeRouter(
        {
            "route": route,
            "locate": [],
            "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.2)]),
        }
    )
    sent: list[dict] = []

    def transport(url, payload, timeout):
        sent.append({"url": url, **json.loads(json.dumps(payload))})
        return fake(url, payload, timeout)

    monkeypatch.setattr(routing, "_transport", transport)
    response = post(client, {"points": points, "preset": preset, **extra})
    assert response.status_code == 200, response.content
    return response.json(), [p for p in sent if p["url"].endswith("/route")]


def _metres(a, b) -> float:
    return math.hypot(
        (a[0] - b[0]) * 111_320.0 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111_320.0
    )


@db
@pytest.mark.usefixtures("rail_streets")
class TestMassRideKeepsOffTheRails:
    def test_the_h_street_trip_leaves_h_street_out_and_still_crosses_it(
        self, client, monkeypatch
    ) -> None:
        body, routes = _plan(client, monkeypatch, H_STREET_TRIP, ride_size=500)
        rings = routes[0].get("exclude_polygons") or []
        # Every block of H Street NE is left out...
        for a, b in zip(CROSS_LONS, CROSS_LONS[1:], strict=False):
            assert _covered(((a + b) / 2, H_LAT), rings)
        # ...and every cross street is kept where it crosses the rails.
        for lon in CROSS_LONS[:-1]:
            assert not _covered((lon, H_LAT), rings)
            assert not _covered((lon, H_LAT + 0.0003), rings)
            assert not _covered((lon, H_LAT - 0.0003), rings)

    def test_an_end_on_h_street_goes_to_the_nearest_cross_street_and_says_so(
        self, client, monkeypatch
    ) -> None:
        body, routes = _plan(client, monkeypatch, H_STREET_TRIP, ride_size=500)
        (moved,) = body["moved_points"]
        assert moved["index"] == 1 and moved["reason"] == "rail_street"
        assert moved["asked"] == H_STREET_TRIP[1]
        assert "cross street" in moved["note"]
        # 13th St NE, the nearer cross street, CROSS_STREET_OFFSET_M along it from the rails.
        routed = moved["routed"]
        assert routed[0] == pytest.approx(CROSS_LONS[-1], abs=1e-6)
        assert _metres(routed, (CROSS_LONS[-1], H_LAT)) == pytest.approx(
            mass_rails.CROSS_STREET_OFFSET_M, abs=1.0
        )
        assert not _covered(routed, routes[0]["exclude_polygons"])
        last = routes[0]["locations"][-1]
        assert [last["lon"], last["lat"]] == routed
        # The start, on no rail street, stays where it was put.
        first = routes[0]["locations"][0]
        assert [first["lon"], first["lat"]] == H_STREET_TRIP[0]

    def test_the_benning_road_trip_leaves_benning_road_out(self, client, monkeypatch) -> None:
        body, routes = _plan(client, monkeypatch, BENNING_TRIP, ride_size=1000, when="weekend")
        rings = routes[0].get("exclude_polygons") or []
        for a, b in zip(BENNING, BENNING[1:], strict=False):
            for f in (0.3, 0.7):  # either side of 15th St NE on the first stretch
                assert _covered((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])), rings)
        # 15th St NE is kept where it crosses Benning Road.
        assert not _covered(_benning_cut(), rings)
        assert body["moved_points"] == []

    def test_no_route_without_the_rails_plans_with_them_open(self, client, monkeypatch) -> None:
        body, routes = _plan(client, monkeypatch, BENNING_TRIP, ride_size=1000, refuse_rails=True)
        assert routes[0].get("exclude_polygons")
        assert not routes[-1].get("exclude_polygons")
        assert body["geometry"]["coordinates"]


@db
@pytest.mark.usefixtures("rail_streets")
def test_group_ride_with_trails_off_keeps_the_rails_at_their_lts_4_price(
    client, monkeypatch
) -> None:
    """Item 288 for every other ride type: the rails are priced, never left out, and no point
    is moved."""
    body, routes = _plan(client, monkeypatch, H_STREET_TRIP, preset="group-ride", trails_off=True)
    assert not any(r.get("exclude_polygons") for r in routes)
    assert body["moved_points"] == []


def test_a_point_along_a_line_goes_away_from_the_near_end() -> None:
    line = [(-76.987, H_LAT), (-76.987, H_LAT + 0.0012)]
    routed = mass_rails.point_along(line, (-76.987, H_LAT), 30.0)
    assert _metres(routed, (-76.987, H_LAT)) == pytest.approx(30.0, abs=0.5)
    # From the far end, back towards the near one.
    routed = mass_rails.point_along(line, line[1], 30.0)
    assert _metres(routed, line[1]) == pytest.approx(30.0, abs=0.5)
    # A line shorter than the offset: its far end.
    short = [(-76.987, H_LAT), (-76.987, H_LAT + 0.0001)]
    assert mass_rails.point_along(short, short[0], 30.0) == [-76.987, H_LAT + 0.0001]
