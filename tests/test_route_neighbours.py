"""Go's "More direct" and "Calmer" (the owner, 2026-10-16): the notches either side of the
rider's traffic setting (`presets.stress_notches`) and POST /api/route/neighbours, which plans
both as one request. The comparison with the rider's route and the words are the page's
(frontend lib/neighbours.ts)."""

from __future__ import annotations

import json

import pytest
from django.test import override_settings
from test_bikeshare_api import body as bikeshare_body
from test_bikeshare_api import world  # noqa: F401 - a fixture
from test_route_api import (  # noqa: F401 - fixtures
    VERTICES,
    hold_slots,
    our_advisory_locks,
    router,
    segments,
    standard_router,
)

from core import api, presets, ratelimit

pytestmark = pytest.mark.usefixtures("weekday_clock")
db = pytest.mark.django_db(transaction=True)

PATH = "/api/route/neighbours"


class TestNotches:
    def test_default_goes_one_band_each_way(self) -> None:
        assert presets.stress_notches("default", 70) == (40, 80)

    def test_a_position_between_notches_takes_the_notch_on_each_side(self) -> None:
        assert presets.stress_notches("default", 55) == (40, 70)
        assert presets.stress_notches("default", 97) == (90, 100)

    def test_the_most_tolerant_end_has_no_more_direct(self) -> None:
        assert presets.stress_notches("default", 0) == (None, 25)
        # Below the lowest notch counts as it: the calmer side is a real step up, not 10.
        assert presets.stress_notches("default", 5) == (None, 25)
        assert presets.stress_notches("default", 10) == (None, 25)

    def test_the_calmest_end_has_no_calmer(self) -> None:
        assert presets.stress_notches("trailmaxxing", 100) == (90, None)
        assert presets.stress_notches("default", 100) == (90, None)

    def test_novice_never_goes_more_direct_than_low_stress(self) -> None:
        assert presets.stress_notches(presets.NOVICE, 100) == (90, None)
        assert presets.stress_notches(presets.NOVICE, 90) == (80, 100)
        assert presets.stress_notches(presets.NOVICE, 80) == (None, 90)
        # A Novice rider who moved the slider lower is offered nothing more direct still.
        assert presets.stress_notches(presets.NOVICE, 40)[0] is None

    def test_fast_never_goes_calmer_than_direct(self) -> None:
        assert presets.stress_notches("fast", 10) == (None, 25)
        assert presets.stress_notches("fast", 25) == (10, None)
        assert presets.stress_notches("fast", 70) == (40, None)

    @pytest.mark.parametrize(
        "name", ["mass-ride", "rebalance", "bike-transit", "bikeshare-transit"]
    )
    def test_multimodal_trips_and_a_locked_slider_have_no_notches(self, name) -> None:
        assert presets.stress_notches(name, presets.stress_start(name)) == (None, None)

    def test_plain_bikeshare_has_notches(self) -> None:
        # The owner, 21:21: "You can put it on bikeshare, but the multimodal trips will have
        # way too many options".
        assert presets.stress_notches("bikeshare", presets.BIKESHARE_STRESS) == (70, 90)

    def test_every_notch_is_a_slider_step_inside_the_slider(self) -> None:
        for notch in presets.STRESS_NOTCHES:
            assert presets.STRESS_MIN <= notch <= presets.STRESS_MAX
            assert notch % 5 == 0


def post(client, body: dict):
    return client.post(PATH, data=json.dumps(body), content_type="application/json")


def body_for(preset: str = "default", **extra) -> dict:
    return {"points": [list(VERTICES[0]), list(VERTICES[-1])], "preset": preset, **extra}


def use_roads_sent(fake) -> list[float]:
    return sorted(
        {
            payload["costing_options"]["bicycle"]["use_roads"]
            for url, payload in fake.calls
            if url.endswith("/route")
        }
    )


@db
class TestEndpoint:
    def test_plans_both_notches_as_one_request(self, client, segments, router) -> None:  # noqa: F811
        fake = router(standard_router())
        response = post(client, body_for(stress=70))
        assert response.status_code == 200
        answer = response.json()
        assert answer["stress"] == 70
        assert [(o["kind"], o["stress"]) for o in answer["options"]] == [
            ("direct", 40),
            ("calmer", 80),
        ]
        for option in answer["options"]:
            assert option["route"]["geometry"]["type"] == "LineString"
            # A route alone: no routes to choose from looked for, never a first route.
            assert option["route"]["candidates"] is None
            assert option["route"]["provisional"] is False
        assert use_roads_sent(fake) == [presets.use_roads_for(80), presets.use_roads_for(40)]

    def test_the_riders_own_setting_is_not_planned_again(self, client, segments, router) -> None:  # noqa: F811
        fake = router(standard_router())
        post(client, body_for(stress=70))
        assert presets.use_roads_for(70) not in use_roads_sent(fake)

    def test_an_end_of_the_slider_has_one_option(self, client, segments, router) -> None:  # noqa: F811
        router(standard_router())
        answer = post(client, body_for(stress=0)).json()
        assert [(o["kind"], o["stress"]) for o in answer["options"]] == [("calmer", 25)]

    @pytest.mark.parametrize("preset", ["mass-ride", "bike-transit"])
    def test_no_options_and_no_router_call_where_none_are_offered(
        self,
        client,
        segments,  # noqa: F811
        router,  # noqa: F811
        preset,
    ) -> None:
        fake = router(standard_router())
        response = post(client, body_for(preset))
        assert response.status_code == 200
        assert response.json()["options"] == []
        assert fake.calls == []

    def test_a_notch_that_fails_is_left_out(
        self,
        client,
        segments,  # noqa: F811
        router,  # noqa: F811
        monkeypatch,
    ) -> None:
        router(standard_router())
        planned = api._planned

        def failing(body, *args):
            if body.stress == 80:
                raise RuntimeError("router down")
            return planned(body, *args)

        monkeypatch.setattr(api, "_planned", failing)
        answer = post(client, body_for(stress=70)).json()
        assert [o["kind"] for o in answer["options"]] == ["direct"]


@db
class TestBikeshare:
    def test_options_keep_the_riders_docks_and_vary_only_the_ride(self, client, world) -> None:  # noqa: F811
        own = client.post(
            "/api/route", data=json.dumps(bikeshare_body()), content_type="application/json"
        ).json()["bikeshare"]
        docks = {
            "pickup_station": own["start"]["station_id"],
            "dropoff_station": own["end"]["station_id"],
        }
        response = post(client, bikeshare_body(**docks))
        assert response.status_code == 200, response.content
        options = response.json()["options"]
        assert [(o["kind"], o["stress"]) for o in options] == [("direct", 70), ("calmer", 90)]
        for option in options:
            plan = option["route"]["bikeshare"]
            assert plan["start"]["station_id"] == docks["pickup_station"]
            assert plan["end"]["station_id"] == docks["dropoff_station"]

    def test_no_options_without_the_riders_docks(self, client, world) -> None:  # noqa: F811
        routers, _ = world
        response = post(client, bikeshare_body())
        assert response.status_code == 200
        assert response.json()["options"] == []
        assert routers.calls == []


def test_it_is_limited_by_routing_count_and_its_own_slots() -> None:
    limits = [
        d.limits
        for _prefix, routes in api.api._routers
        for path, view in routes.path_operations.items()
        if path == "/route/neighbours"
        for op in view.operations
        for d in getattr(op, "_run_decorators", [])
        if getattr(d, "limits", None) is not None
    ]
    assert sorted(map(repr, limits)) == sorted(
        map(repr, [ratelimit.ROUTING, ratelimit.NEIGHBOURS_IN_FLIGHT])
    )
    # Routing's own deployment slots, with clients of its own and room left for plans.
    neighbours = ratelimit.NEIGHBOURS_IN_FLIGHT
    assert neighbours.total_class == ratelimit.ROUTING_IN_FLIGHT.total_class
    assert neighbours.per_client == 1
    assert neighbours.leave_free == ratelimit.ROOM_FOR_OTHERS


def routing_slots(total: int):
    return [(ratelimit.ROUTING_IN_FLIGHT.total_class, s) for s in range(total)]


def neighbours_client_slot(address: str):
    key = ratelimit._client_lock_id(ratelimit.client_key(address))
    return (ratelimit._LOCK_CLASS_CLIENT + ratelimit.NEIGHBOURS_IN_FLIGHT.scope_id * 64, key)


@db
class TestNeverInTheWay:
    def test_it_counts_as_two_routing_requests(self, client, segments, router) -> None:  # noqa: F811
        from core.models import RateLimitWindow

        router(standard_router())
        post(client, body_for(stress=70))
        assert list(RateLimitWindow.objects.values_list("scope", "hits")) == [
            (ratelimit.ROUTING.scope, api.NEIGHBOURS_COST)
        ]

    @override_settings(ROUTING_CONCURRENCY=3)
    def test_a_plan_while_the_options_hold_their_slot_is_planned(
        self,
        client,
        segments,  # noqa: F811
        router,  # noqa: F811
    ) -> None:
        """The review's blocker: on the default pool of three, a rider's re-plan or ride
        re-route sent while their options compute is answered, not refused."""
        router(standard_router())
        address = "198.51.100.70"
        # The options in flight: their client slot and routing's last slot, as they take it.
        other = hold_slots([neighbours_client_slot(address), routing_slots(3)[-1]])
        try:
            response = client.post(
                "/api/route",
                data=json.dumps(body_for(stress=70)),
                content_type="application/json",
                HTTP_X_FORWARDED_FOR=address,
            )
        finally:
            other.close()
        assert response.status_code == 200

    @override_settings(ROUTING_CONCURRENCY=3)
    def test_refused_at_once_while_any_plan_runs_on_the_default_pool(
        self,
        client,
        segments,  # noqa: F811
        router,  # noqa: F811
    ) -> None:
        fake = router(standard_router())
        other = hold_slots(routing_slots(3)[:1])
        try:
            response = post(client, body_for(stress=70))
        finally:
            other.close()
        assert response.status_code == 503
        assert int(response["Retry-After"]) >= 1
        assert fake.calls == []
        assert our_advisory_locks() == 0, "a refused request holds nothing"

    @override_settings(ROUTING_CONCURRENCY=3)
    def test_one_at_a_time_per_client(self, client, segments, router) -> None:  # noqa: F811
        router(standard_router())
        address = "198.51.100.71"
        other = hold_slots([neighbours_client_slot(address)])
        try:
            response = client.post(
                PATH,
                data=json.dumps(body_for(stress=70)),
                content_type="application/json",
                HTTP_X_FORWARDED_FOR=address,
            )
        finally:
            other.close()
        assert response.status_code == 429

    def test_the_slots_are_released(self, client, segments, router) -> None:  # noqa: F811
        router(standard_router())
        assert post(client, body_for(stress=70)).status_code == 200
        assert our_advisory_locks() == 0
