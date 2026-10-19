"""The standard way beside a closure's detour, and the roads a rider marks closed (v0.8.2).

The owner, 2026-10-17: "There are several closures marked that aren't actually closed. We
should have both the standard route and the detour", and, of a road found closed with
nothing marked, a button that reroutes "without trying to put people back onto the closed
road". The network is a fake; the database is real."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_route_api import segments  # noqa: F401 - the live segment table, a fixture

from core import workzones
from core.models import BikeshareFeedCache
from routemaker import workzones as wz

db = pytest.mark.django_db(transaction=True)

LAT = 38.9
NORTH = LAT + 0.003  # about 330 m north of the route


@pytest.fixture(autouse=True)
def _fresh():
    workzones.forget()
    yield
    workzones.forget()


class TestPartingPoints:
    def test_where_the_line_leaves_the_standard_way(self) -> None:
        line = [(-77.05, LAT), (-77.04, LAT), (-77.03, LAT), (-77.02, LAT)]
        standard = [
            (-77.05, LAT),
            (-77.04, LAT),
            (-77.04, NORTH),
            (-77.03, NORTH),
            (-77.03, LAT),
            (-77.02, LAT),
        ]
        (at,) = workzones.parting_points(line, standard)
        # The last vertex still on it: -77.04, about 870 m from the start.
        assert 850 < at < 910

    def test_the_same_way_never_parts(self) -> None:
        line = [(-77.05, LAT), (-77.04, LAT), (-77.03, LAT)]
        assert workzones.parting_points(line, line) == []
        # A few metres off it, as the same road drawn twice, is not a detour.
        nudged = [(lon, lat + 0.0001) for lon, lat in line]
        assert workzones.parting_points(nudged, line) == []
        assert workzones.parting_points(line[:1], line) == []


class TestTheSplitEntry:
    def test_said_where_the_detour_parts_with_the_source_in_small_print(self) -> None:
        from test_route_api import route_answer

        until = datetime.now(UTC) + timedelta(days=30)
        side = ((-77.04, NORTH), (-77.03, NORTH))
        closed = wz.Zone("dc-1", "dc", wz.CLOSED, 0, side, "Oak Street", None, None, until)
        standard = [
            (-77.05, LAT),
            (-77.04, LAT),
            (-77.04, NORTH),
            (-77.03, NORTH),
            (-77.03, LAT),
            (-77.02, LAT),
        ]
        plan = wz.PlanZones(status={"dc": "current"}, excluded=[closed], affecting={"dc-1"})
        plan.through = route_answer([(standard, 2.0, [])])["trip"]
        line = [(-77.05, LAT), (-77.04, LAT), (-77.03, LAT), (-77.02, LAT)]
        body = {
            "geometry": {"type": "LineString", "coordinates": [list(p) for p in line]},
            "distance_m": 2595.0,
            "description": [{"kind": "stretch", "from_m": 0, "text": "Ride east."}],
            "description_overview": None,
        }
        out = workzones.with_work_zones(body, plan)
        (split,) = [e for e in out["description"] if e["kind"] == "workzone"]
        assert split["text"] == "Oak Street marked closed. Detour posted."
        assert split["severity"] == "red" and split["street"] == "Oak Street"
        assert split["citation"].startswith("Source: ")
        assert 800 < split["from_m"] < 950


def _store(zones) -> None:
    BikeshareFeedCache.objects.create(
        key=workzones.KEY,
        payload={"feeds": {"md": {"read_at": datetime.now(UTC).isoformat(),
                                  "zones": [z.to_json() for z in zones]}}},
        fetched_at=datetime.now(UTC),
    )  # fmt: skip


@db
@pytest.mark.usefixtures("weekday_clock", "segments")
def test_the_answer_carries_the_standard_way_through_a_closure_it_goes_round(
    client, monkeypatch
) -> None:
    """The router's route without the closure goes along it: that route is answered as
    `closure_through` beside the detour, and the detour says where it parts."""
    from test_route_api import VERTICES, FakeRouter, good_body, post, route_answer, trace_answer

    from core import routing

    until = datetime.now(UTC) + timedelta(days=30)
    side = ((-77.04, NORTH), (-77.03, NORTH))
    _store([wz.Zone("md-c", "md", wz.CLOSED, 0, side, "Side Road", None, None, until)])
    standard = [
        VERTICES[0],
        VERTICES[1],
        (-77.04, NORTH),
        (-77.03, NORTH),
        VERTICES[3],
        VERTICES[4],
    ]
    detour = route_answer([(VERTICES, 2.2, [10.0] * 5)])
    through = route_answer([(standard, 2.2, [10.0] * 6)])
    through["trip"]["summary"]["time"] = 150.0
    fake = FakeRouter(
        {
            # The plan's own requests leave the closure out; the delay's asks without it.
            "route": lambda payload: detour if payload.get("exclude_polygons") else through,
            "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.2)]),
        }
    )
    monkeypatch.setattr(routing, "_transport", fake)
    response = post(client, good_body())
    assert response.status_code == 200, response.content
    body = response.json()
    other = body["closure_through"]
    assert other is not None and other["closure_ids"] == ["md-c"]
    assert other["geometry"]["coordinates"][2] == [-77.04, NORTH]
    split = [e for e in body["description"] if e["kind"] == "workzone" and e["severity"] == "red"]
    assert [e["text"] for e in split] == ["Side Road marked closed. Detour posted."]


@db
@pytest.mark.usefixtures("weekday_clock", "segments")
def test_a_road_the_rider_marked_closed_stays_out_of_every_request(client, monkeypatch) -> None:
    """`blocked_lines` is left out as a closure is: in the request with no feeds, and kept
    out where the closures are let back in for want of a way round them."""
    from test_route_api import VERTICES, FakeRouter, good_body, post, route_answer, trace_answer

    from core import routing

    across = ((-77.04, 38.9), (-77.035, 38.9))  # under the route itself
    until = datetime.now(UTC) + timedelta(days=30)
    _store([wz.Zone("md-c", "md", wz.CLOSED, 0, across, "Main Road", None, None, until)])
    fake = FakeRouter(
        {
            "route": [routing.RouterRefused(400, 442, "No path could be found for input")]
            + [route_answer([(VERTICES, 2.2, [10.0] * 5)])] * 20,
            "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.2)]),
        }
    )
    sent: list[dict] = []

    def transport(url, payload, timeout):
        sent.append({"url": url, **json.loads(json.dumps(payload))})
        return fake(url, payload, timeout)

    monkeypatch.setattr(routing, "_transport", transport)
    blocked = [[-77.03, 38.905], [-77.03, 38.907]]
    response = post(client, {**good_body(), "blocked_lines": [blocked]})
    assert response.status_code == 200, response.content
    routes = [p for p in sent if p["url"].endswith("/route")]
    # The closure and the rider's road, then the rider's road alone.
    assert len(routes[0]["exclude_polygons"]) == 2
    assert len(routes[1]["exclude_polygons"]) == 1
    assert routes[1]["exclude_polygons"][0] == wz.line_ring(blocked)


@db
@pytest.mark.usefixtures("weekday_clock", "segments")
def test_ddots_permits_are_never_routed_round(client, monkeypatch) -> None:
    """v0.9.1: DDOT's permits are flagged, never routed round, with `closures_now` or not."""
    from test_route_api import VERTICES, FakeRouter, good_body, post, route_answer, trace_answer

    from core import routing

    until = datetime.now(UTC) + timedelta(days=30)
    side = ((-77.04, NORTH), (-77.03, NORTH))
    permit = wz.Zone("dc-p", "dc", wz.CLOSED, 0, side, "Side Road", None, None, until)
    BikeshareFeedCache.objects.create(
        key=workzones.KEY,
        payload={"feeds": {"dc": {"read_at": datetime.now(UTC).isoformat(),
                                  "zones": [permit.to_json()]}}},
        fetched_at=datetime.now(UTC),
    )  # fmt: skip
    fake = FakeRouter(
        {
            "route": lambda payload: route_answer([(VERTICES, 2.2, [10.0] * 5)]),
            "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.2)]),
        }
    )
    sent: list[dict] = []

    def transport(url, payload, timeout):
        sent.append({"url": url, **json.loads(json.dumps(payload))})
        return fake(url, payload, timeout)

    monkeypatch.setattr(routing, "_transport", transport)

    def first_route(body) -> dict:
        sent.clear()
        response = post(client, body)
        assert response.status_code == 200, response.content
        return next(p for p in sent if p["url"].endswith("/route"))

    planned = first_route(good_body())
    assert not planned.get("exclude_polygons"), "a permit is never routed round"
    go = first_route({**good_body(), "closures_now": True})
    assert not go.get("exclude_polygons")


@db
@pytest.mark.usefixtures("segments")
def test_blocked_lines_are_checked(client) -> None:
    from test_route_api import good_body, post

    assert post(client, {**good_body(), "blocked_lines": [[[-77.03, 38.9]]]}).status_code == 400
    many = [[[-77.03, 38.9], [-77.03, 38.91]]] * 11
    assert post(client, {**good_body(), "blocked_lines": many}).status_code == 400


class TestOnlyWhereAClosureIs:
    def test_a_route_that_differs_for_another_reason_says_nothing(self) -> None:
        line = [(-77.05, LAT), (-77.04, LAT), (-77.03, LAT), (-77.02, LAT)]
        standard = [
            (-77.05, LAT),
            (-77.04, LAT),
            (-77.04, NORTH),
            (-77.03, NORTH),
            (-77.03, LAT),
            (-77.02, LAT),
        ]
        assert workzones.closure_partings(line, standard, []) == []


class TestTheRidersRoadsComeFirst:
    def test_the_latest_fit_the_routers_limits(self) -> None:
        line = ((-77.03, 38.905), (-77.03, 38.906), (-77.029, 38.907))
        rings = workzones.blocked_rings([line] * 30)
        assert 0 < len(rings) < 30
        assert sum(len(r) for r in rings) <= wz.MAX_VERTICES

    def test_the_closures_fit_in_what_is_left(self) -> None:
        until = datetime.now(UTC) + timedelta(days=30)
        zones = [
            wz.Zone(
                f"md-{i}",
                "md",
                wz.CLOSED,
                0,
                ((-77.04, 38.9 + i / 1000), (-77.03, 38.9 + i / 1000)),
                "R",
                None,
                None,
                until,
            )
            for i in range(20)
        ]
        at = datetime.now(UTC)
        points = [(-77.05, 38.89), (-77.02, 38.93)]
        free = wz.for_plan(zones, at, points, {"md": "current"}, now=at)
        held = wz.for_plan(zones, at, points, {"md": "current"}, now=at, reserve=(0.0, 90))
        assert len(held.excluded) < len(free.excluded)
        assert sum(len(r) for r in held.exclude) <= wz.MAX_VERTICES - 90
