"""The way round a red (very high stress) crossing on a plan the crossing search did not
cover (`core.red_crossings`), with the router and the route's reading replaced.

The owner, 2026-11-08, of a long Mount Vernon ride that crossed the GW Parkway at grade at
Tulane Dr with no signal, drawn red and not avoided: "It's taking people onto dangerous
intersections."
"""

from __future__ import annotations

import pytest
from test_refine import analysis, context, event, trip_of

from core import red_crossings, refine, routing
from routemaker import avoid_junctions as avoid_model

# A red crossing 2 km into a 4 km route, clear of both ends.
RED = event(2000.0, cost_ft=3300.0)


class Router:
    """One /route answer, and the readings by shape."""

    def __init__(self, monkeypatch, readings: dict, answer) -> None:
        self.readings = readings
        self.answer = answer
        self.asked: list[dict] = []
        monkeypatch.setattr(
            refine, "analyse", lambda trip, ctx, deadline: self.readings[trip["legs"][0]["shape"]]
        )
        monkeypatch.setattr(routing, "_call", self.call)

    def call(self, variant, endpoint, payload, deadline):
        assert endpoint == "route"
        self.asked.append(payload)
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"trip": self.answer}


def test_a_long_plans_red_crossing_is_ridden_round(monkeypatch):
    # Before: a plan the crossing search skipped (past its span) kept the red crossing.
    # After: the router is asked round it, and the way round, 300 m longer and calm, is taken.
    ctx = context()
    router = Router(
        monkeypatch,
        {
            "through": analysis("through", events=[RED]),
            "round": analysis("round", tiers="1" * 43, cost_s=4100.0),
        },
        trip_of("round", 4.3),
    )
    trip, info = red_crossings.settle(trip_of("through", 4.0), ctx, searched=False)
    assert trip["legs"][0]["shape"] == "round"
    assert info["decision"] == "avoided"
    assert info["reds"] == 1 and info["reds_after"] == 0
    (asked,) = router.asked
    assert asked["exclude_locations"] == [
        {"lon": RED.lon, "lat": RED.lat, "radius": int(avoid_model.MATCH_RADIUS_M)}
    ]
    assert "alternates" not in asked


def test_a_plan_the_search_covered_is_left_alone(monkeypatch):
    router = Router(monkeypatch, {"through": analysis("through", events=[RED])}, None)
    trip = trip_of("through", 4.0)
    assert red_crossings.settle(trip, context(), searched=True) == (trip, None)
    assert router.asked == []


def test_a_mass_ride_keeps_its_crossings(monkeypatch):
    router = Router(monkeypatch, {"through": analysis("through", events=[RED])}, None)
    trip = trip_of("through", 4.0)
    assert red_crossings.settle(trip, context(group=True), searched=False) == (trip, None)
    assert router.asked == []


def test_no_red_crossing_asks_nothing(monkeypatch):
    router = Router(monkeypatch, {"through": analysis("through")}, None)
    trip, info = red_crossings.settle(trip_of("through", 4.0), context(), searched=False)
    assert trip["legs"][0]["shape"] == "through"
    assert info["reds"] == 0 and router.asked == []


def test_a_red_crossing_at_the_start_is_not_asked_round(monkeypatch):
    # Within ENDPOINT_CLEARANCE_M of the start: the rider's own start, not a way to avoid.
    near = event(200.0)
    router = Router(monkeypatch, {"through": analysis("through", events=[near])}, None)
    trip, info = red_crossings.settle(trip_of("through", 4.0), context(), searched=False)
    assert info["reds"] == 0 and router.asked == []


def test_a_way_round_onto_a_busy_road_is_refused(monkeypatch):
    # The way round trades the crossing for 2 km of LTS 4: the Traffic-wins guard keeps it.
    Router(
        monkeypatch,
        {
            "through": analysis("through", events=[RED]),
            "round": analysis("round", tiers="1" * 20 + "4" * 20, cost_s=4000.0),
        },
        trip_of("round", 4.0),
    )
    trip, info = red_crossings.settle(trip_of("through", 4.0), context(), searched=False)
    assert trip["legs"][0]["shape"] == "through"
    assert info["decision"] == "kept" and info["reds_after"] == 0


def test_a_way_round_with_as_many_reds_is_refused(monkeypatch):
    Router(
        monkeypatch,
        {
            "through": analysis("through", events=[RED]),
            "round": analysis("round", tiers="1" * 41, events=[event(2500.0)]),
        },
        trip_of("round", 4.1),
    )
    trip, info = red_crossings.settle(trip_of("through", 4.0), context(), searched=False)
    assert trip["legs"][0]["shape"] == "through" and info["decision"] == "kept"


@pytest.mark.parametrize(
    "failure, limited",
    [
        (routing.RouterRefused(400, 442, "no path"), "no_route"),
        (routing.DeadlineExceeded(), "time"),
        (routing.RouterUnavailable("down"), "time"),
    ],
)
def test_the_router_failing_keeps_the_route(monkeypatch, failure, limited):
    Router(monkeypatch, {"through": analysis("through", events=[RED])}, failure)
    trip, info = red_crossings.settle(trip_of("through", 4.0), context(), searched=False)
    assert trip["legs"][0]["shape"] == "through" and info["limited"] == limited


def test_no_time_left_asks_nothing(monkeypatch):
    router = Router(monkeypatch, {"through": analysis("through", events=[RED])}, None)
    ctx = context()
    ctx.deadline = routing.Deadline(routing.clock() + refine.REFINE_TRACE_RESERVE_S + 1, 30)
    trip, info = red_crossings.settle(trip_of("through", 4.0), ctx, searched=False)
    assert info["limited"] == "time" and router.asked == []
