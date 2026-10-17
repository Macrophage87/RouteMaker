"""The walk to a route end the bike route cannot reach (owner 2026-10-17: "we should let
them route there, but switch to walk mode. You're almost always able to portage your
bike.")."""

from __future__ import annotations

import pytest

from core import routing
from core.dedodge import encode_polyline6

RIDE = [[-77.0440, 38.9100], [-77.0436, 38.9096]]
# The MLK Memorial's plaza, about 1,100 ft (340 m) from where a ride along the line ends.
ASKED_END = [-77.0436, 38.9066]


def deadline() -> routing.Deadline:
    return routing.Deadline(routing.clock() + 30, 10)


@pytest.fixture
def router(monkeypatch):
    calls: list[dict] = []

    def install(length_km: float = 0.34):
        def fake_call(variant, action, payload, _deadline):
            calls.append({"variant": variant, "action": action, "payload": payload})
            shape = [(p["lon"], p["lat"]) for p in payload["locations"]]
            return {
                "trip": {
                    "legs": [
                        {
                            "shape": encode_polyline6(shape),
                            "summary": {"length": length_km, "time": 255.0},
                        }
                    ]
                }
            }

        monkeypatch.setattr(routing, "_call", fake_call)
        return calls

    return install


def test_an_end_near_the_ride_needs_no_walk(router) -> None:
    calls = router()
    assert routing.walk_in(RIDE[0], RIDE[-1], RIDE, deadline()) is None
    assert calls == []


def test_an_end_the_ride_stops_short_of_gets_a_walk_on_foot(router) -> None:
    calls = router()
    walk = routing.walk_in(RIDE[0], ASKED_END, RIDE, deadline())
    assert walk["start"] is None
    end = walk["end"]
    assert end["to"] == "your destination"
    assert end["distance_m"] == 340.0
    assert end["geometry"]["coordinates"][0] == RIDE[-1]
    assert end["geometry"]["coordinates"][-1] == ASKED_END
    assert calls[0]["payload"]["costing"] == "pedestrian"
    assert calls[0]["variant"] == routing.Variant.STANDARD.value


def test_a_start_off_the_ride_walks_to_the_route(router) -> None:
    router()
    walk = routing.walk_in(ASKED_END, None, list(reversed(RIDE)), deadline())
    assert walk["end"] is None
    assert walk["start"]["to"] == "the route"
    assert walk["start"]["geometry"]["coordinates"][0] == ASKED_END


def test_a_walk_longer_than_the_most_is_left_out(router) -> None:
    router(length_km=routing.WALK_IN_MAX_M / 1000 + 0.1)
    assert routing.walk_in(RIDE[0], ASKED_END, RIDE, deadline()) is None


def test_a_point_the_planner_moved_gets_no_walk(router) -> None:
    calls = router()
    assert routing.walk_in(None, None, RIDE, deadline()) is None
    assert calls == []


def test_a_walk_the_router_refuses_is_left_out(monkeypatch) -> None:
    def refuse(*_args):
        raise routing.RouterRefused(400, 442, "No path could be found for input")

    monkeypatch.setattr(routing, "_call", refuse)
    assert routing.walk_in(RIDE[0], ASKED_END, RIDE, deadline()) is None


def test_no_walk_is_asked_once_the_time_is_spent(router) -> None:
    calls = router()
    spent = routing.Deadline(routing.clock(), 10)
    assert routing.walk_in(RIDE[0], ASKED_END, RIDE, spent) is None
    assert calls == []
