# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""Plan's manual mode (v0.9.1, Stephen 2026-10-19: "there should be in plan the ability to
have a 'manual mode' where you can just route directly"): the legs the rider drew are
straight lines between their points (`straight_legs`), the rest routed as asked."""

from __future__ import annotations

import pytest
from test_route_api import (  # noqa: F401 (fixtures)
    VERTICES,
    FakeRouter,
    post,
    route_answer,
    router,
    segments,
    trace_answer,
)

from core import routing
from routemaker.geo import Point, haversine

pytestmark = pytest.mark.usefixtures("weekday_clock")
db = pytest.mark.django_db(transaction=True)


def drawn_body(preset: str = "default", **extra) -> dict:
    """Three points, the second leg drawn."""
    return {
        "points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])],
        "preset": preset,
        "straight_legs": [1],
        **extra,
    }


def drawn_router(heights=None) -> FakeRouter:
    return FakeRouter(
        {
            "route": route_answer([(VERTICES[0:3], 1.3, [10.0, 20.0])]),
            "height": heights
            if heights is not None
            else (lambda payload: {"height": [25.0] * len(payload["shape"])}),
            "trace_attributes": lambda payload: trace_answer(
                routing.decode_polyline6(payload["encoded_polyline"]),
                [(101, 0, len(routing.decode_polyline6(payload["encoded_polyline"])) - 1, 1.0)],
            ),
        }
    )


def bike_routes(fake: FakeRouter) -> list[dict]:
    """The plan's own /route calls (not a walk to or from the route, `routing.walk_in`)."""
    return [p for url, p in fake.calls if url.endswith("/route") and p["costing"] == "bicycle"]


class TestStraightLeg:
    def test_a_drawn_leg_is_the_line_between_its_points_timed_at_the_pace(self) -> None:
        a, b = VERTICES[2], VERTICES[4]
        leg = routing.straight_leg(a, b, 18.0)
        km = haversine(Point(*a), Point(*b)) / 1000.0
        assert routing.decode_polyline6(leg["shape"]) == [a, b]
        assert leg["summary"]["length"] == pytest.approx(km)
        assert leg["summary"]["time"] == pytest.approx(km / 18.0 * 3600.0)
        assert leg["drawn"] is True and "elevation" not in leg
        assert [m["type"] for m in leg["maneuvers"]] == [1, 4]

    def test_heights_are_asked_every_interval_ends_included(self) -> None:
        a, b = VERTICES[0], VERTICES[1]
        samples = routing.samples_along(a, b, 30)
        metres = haversine(Point(*a), Point(*b))
        assert len(samples) == round(metres / 30) + 1
        assert samples[0] == a and samples[-1] == pytest.approx(b)


@db
class TestDrawnRoute:
    def test_the_drawn_leg_is_straight_and_the_others_routed(
        self, client, segments, router
    ) -> None:
        fake = router(drawn_router())
        response = post(client, drawn_body())
        assert response.status_code == 200, response.content
        body = response.json()
        # One /route, for the first leg alone, and no search beside it.
        routed = bike_routes(fake)
        assert len(routed) == 1
        assert [(loc["lon"], loc["lat"]) for loc in routed[0]["locations"]] == [
            VERTICES[0],
            VERTICES[2],
        ]
        assert "alternates" not in routed[0]
        assert body["geometry"]["coordinates"] == [
            list(VERTICES[0]),
            list(VERTICES[1]),
            list(VERTICES[2]),
            list(VERTICES[4]),
        ]
        assert body["leg_ends"] == [2, 3]
        assert body["drawn_legs"] == [1]
        assert body["detour"] is None and body["candidates"] is None
        # The drawn leg is not traced: its length is unknown stress.
        traced = [
            routing.decode_polyline6(p["encoded_polyline"])
            for url, p in fake.calls
            if url.endswith("/trace_attributes")
        ]
        assert [VERTICES[2], VERTICES[4]] not in traced
        drawn_m = haversine(Point(*VERTICES[2]), Point(*VERTICES[4]))
        assert body["stress_m"]["unknown"] >= drawn_m - 1.0
        assert body["distance_m"] == pytest.approx(1300.0 + drawn_m, abs=1.0)

    def test_every_leg_drawn_asks_the_router_for_heights_only(
        self, client, segments, router
    ) -> None:
        fake = router(drawn_router())
        body = post(client, drawn_body(straight_legs=[0, 1])).json()
        assert bike_routes(fake) == []
        assert fake.endpoints().count("height") == 2
        assert body["drawn_legs"] == [0, 1]
        assert body["geometry"]["coordinates"] == [
            list(VERTICES[0]),
            list(VERTICES[2]),
            list(VERTICES[4]),
        ]
        assert body["climb_m"] == 0

    def test_a_router_without_heights_still_draws_the_leg(self, client, segments, router) -> None:
        router(drawn_router(heights=routing.RouterRefused(400, 999, "no elevation")))
        response = post(client, drawn_body(straight_legs=[0, 1]))
        assert response.status_code == 200, response.content
        assert response.json()["drawn_legs"] == [0, 1]

    def test_runs_on_both_sides_of_a_drawn_leg_are_routed_apart(
        self, client, segments, router
    ) -> None:
        fake = router(drawn_router())
        points = [list(VERTICES[i]) for i in (0, 1, 2, 3)]
        post(client, {"points": points, "preset": "default", "straight_legs": [1]})
        routed = bike_routes(fake)
        assert [[(loc["lon"], loc["lat"]) for loc in p["locations"]] for p in routed] == [
            [VERTICES[0], VERTICES[1]],
            [VERTICES[2], VERTICES[3]],
        ]
        # Each run's own ends are stops.
        assert all(loc["type"] == "break" for p in routed for loc in p["locations"])

    def test_a_via_point_inside_a_run_keeps_its_type(self, client, segments, router) -> None:
        fake = router(drawn_router())
        points = [list(VERTICES[i]) for i in (0, 1, 2, 3)]
        post(
            client,
            {"points": points, "preset": "default", "straight_legs": [2], "via_points": [1]},
        )
        routed = bike_routes(fake)
        assert [loc["type"] for loc in routed[0]["locations"]] == [
            "break",
            routing.VIA_LOCATION_TYPE,
            "break",
        ]

    def test_without_drawn_legs_the_plan_is_as_before(self, client, segments, router) -> None:
        fake = router(drawn_router())
        body = post(client, drawn_body(straight_legs=[])).json()
        assert body["drawn_legs"] is None
        assert "height" not in fake.endpoints()

    def test_a_loop_is_planned_not_drawn(self, client, segments, router) -> None:
        router(drawn_router())
        body = post(client, drawn_body(loop=True)).json()
        assert body["drawn_legs"] is None

    @pytest.mark.parametrize("legs", [[2], [-1], [1, 1]])
    def test_a_leg_that_is_not_one_is_refused(self, client, segments, router, legs) -> None:
        router(drawn_router())
        assert post(client, drawn_body(straight_legs=legs)).status_code == 400
