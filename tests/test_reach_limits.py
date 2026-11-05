# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""Reach's share of the routing limits: a request the page has replaced stops and gives its
slot back (X-Plan-Id, as a plan's, `core.plan_cancel`); each isochrone call counts as one
routing request; and a router answer is kept briefly (`reach.KEEP_S`, under two minutes), so
a ring or Calm streets turned off and on again does not ask the router again."""

from __future__ import annotations

import json

import pytest
from django.db import connection
from test_reach import EAST, HERE, calls, isochrone_answer
from test_route_api import FakeRouter

from core import plan_cancel, ratelimit, reach, route_cache, routing

db = pytest.mark.django_db(transaction=True)
pytestmark = pytest.mark.usefixtures("weekday_clock")

PATH = "/api/reach"
CANCEL_PATH = "/api/route/cancel"
PLAN = "0123456789abcdef0123456789abcdef"
OTHER_PLAN = "fedcba9876543210fedcba9876543210"
FIVE = [[HERE[0] + 0.01 * i, HERE[1]] for i in range(5)]


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


@pytest.fixture(autouse=True)
def no_places(monkeypatch):
    monkeypatch.setattr(
        reach, "places", lambda: {"metro": [], "racks": [], "food": [], "sights": []}
    )


@pytest.fixture
def kept(settings, monkeypatch):
    """The routes cache on, as in a deployment, with a clock the test moves."""
    settings.ROUTE_CACHE_TTL_S = route_cache.TTL_S
    now = [1000.0]
    monkeypatch.setattr(route_cache, "_clock", lambda: now[0])
    # No sweep timers left behind by the test.
    monkeypatch.setattr(route_cache, "_later", lambda delay, run: None)
    route_cache.clear()
    yield now
    route_cache.clear()


def post(client, body, address="198.51.100.60", **headers):
    return client.post(
        PATH, data=json.dumps(body), content_type="application/json", REMOTE_ADDR=address,
        **headers,
    )  # fmt: skip


def cancel(client, plan: str, address: str):
    return client.post(
        CANCEL_PATH, data=json.dumps({"plan_id": plan}), content_type="application/json",
        REMOTE_ADDR=address,
    )  # fmt: skip


def routing_count(address: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT hits FROM rate_limit_window WHERE scope = %s AND client = %s",
            [ratelimit.ROUTING.scope, ratelimit.client_key(address)],
        )
        row = cursor.fetchone()
    return 0 if row is None else row[0]


@db
class TestAReplacedRequestStops:
    def test_a_cancelled_reach_request_answers_409_and_asks_the_router_nothing(
        self, client, router
    ) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        address = "198.51.100.61"
        assert cancel(client, PLAN, address).status_code == 204
        response = post(
            client, {"points": [HERE], "preset": "default"}, address, HTTP_X_PLAN_ID=PLAN
        )
        assert response.status_code == 409
        assert response.json()["code"] == "plan_cancelled"
        assert "Retry-After" not in response
        assert calls(fake) == []

    def test_a_request_cancelled_while_it_runs_stops_at_its_next_router_call(
        self, client, router, monkeypatch
    ) -> None:
        monkeypatch.setattr(plan_cancel, "POLL_S", 0.0)
        address = "198.51.100.62"

        def first_then_cancelled(payload: dict) -> dict:
            # The page moves on while the first isochrone is drawn.
            if len(calls(fake)) == 1:
                assert cancel(client, PLAN, address).status_code == 204
            return isochrone_answer(payload)

        fake = router(FakeRouter({"isochrone": first_then_cancelled}))
        response = post(
            client, {"points": FIVE, "preset": "default", "stress": 40, "calm": True}, address,
            HTTP_X_PLAN_ID=PLAN,
        )  # fmt: skip
        assert response.status_code == 409
        assert len(calls(fake)) == 1

    def test_a_replacing_reach_request_cancels_the_one_it_replaces(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        address = "198.51.100.63"
        body = {"points": [HERE], "preset": "default"}
        new = post(client, body, address, HTTP_X_PLAN_ID=OTHER_PLAN, HTTP_X_PLAN_REPLACES=PLAN)
        assert new.status_code == 200
        assert post(client, body, address, HTTP_X_PLAN_ID=PLAN).status_code == 409

    def test_another_clients_cancel_does_not_stop_the_request(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        cancel(client, PLAN, "198.51.100.64")
        response = post(
            client, {"points": [HERE], "preset": "default"}, "198.51.100.65", HTTP_X_PLAN_ID=PLAN
        )
        assert response.status_code == 200

    def test_the_schema_says_a_cancelled_request_answers_409(self) -> None:
        from core.api import api

        schema = api.get_openapi_schema()
        assert "CancelledOut" in json.dumps(schema["paths"]["/api/reach"]["post"]["responses"][409])


@db
class TestEachIsochroneCounts:
    def test_each_point_on_each_layer_counts_as_a_routing_request(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        address = "198.51.100.66"
        response = post(
            client, {"points": [HERE, EAST], "preset": "default", "stress": 40, "calm": True},
            address,
        )  # fmt: skip
        assert response.status_code == 200
        assert len(calls(fake)) == 4
        assert routing_count(address) == 4

    def test_one_point_one_layer_counts_once(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        address = "198.51.100.67"
        assert post(client, {"points": [HERE], "preset": "default"}, address).status_code == 200
        assert routing_count(address) == 1

    def test_rings_past_the_limit_are_refused_before_any_router_call(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        address = "198.51.100.68"
        ratelimit.hit(
            ratelimit.ROUTING, ratelimit.client_key(address), ratelimit.ROUTING.requests - 3
        )
        response = post(client, {"points": FIVE, "preset": "default"}, address)
        assert response.status_code == 429
        assert int(response["Retry-After"]) >= 1
        assert calls(fake) == []


@db
class TestKeptBriefly:
    def test_a_ring_turned_off_and_on_again_asks_the_router_nothing_more(
        self, client, router, kept
    ) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        address = "198.51.100.70"
        everything = {"points": [HERE], "preset": "default", "stress": 40, "calm": True}
        first = post(client, everything, address)
        assert first.status_code == 200
        assert len(calls(fake)) == 2
        for minutes in ([15, 30, 45], [15, 60], [30], [15, 30, 45, 60]):
            again = post(client, {**everything, "minutes": minutes}, address)
            assert again.status_code == 200, minutes
            rings = again.json()["groups"][0]["rings"]
            assert [r["minutes"] for r in rings] == minutes
            by_minute = {r["minutes"]: r for r in first.json()["groups"][0]["rings"]}
            assert [r["area_km2"] for r in rings] == [by_minute[m]["area_km2"] for m in minutes]
        assert len(calls(fake)) == 2
        # Answered from the cache, each counted once, as a request.
        assert routing_count(address) == 2 + 4

    def test_calm_streets_turned_on_asks_only_for_the_calm_layer(
        self, client, router, kept
    ) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        body = {"points": [HERE], "preset": "default", "stress": 40}
        post(client, {**body, "calm": False})
        post(client, {**body, "calm": True})
        own, calm = calls(fake)
        assert calm["costing_options"]["bicycle"]["use_roads"] == 0
        assert own["costing_options"]["bicycle"]["use_roads"] > 0

    def test_a_kept_answer_is_gone_within_two_minutes(self, client, router, kept) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        body = {"points": [HERE], "preset": "default"}
        post(client, body)
        assert reach.KEEP_S < 120
        kept[0] += reach.KEEP_S
        post(client, body)
        assert len(calls(fake)) == 2
        kept[0] += 1
        assert route_cache.size() == 1
        # Nothing is left in memory once its time is up, read or not.
        kept[0] += reach.KEEP_S
        route_cache._sweep()
        assert route_cache.size() == 0

    def test_another_point_or_setting_is_asked_afresh(self, client, router, kept) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        post(client, {"points": [HERE], "preset": "default"})
        post(client, {"points": [EAST], "preset": "default"})
        post(client, {"points": [HERE], "preset": "default", "direction": "to"})
        post(client, {"points": [HERE], "preset": "default", "stress": 10})
        assert len(calls(fake)) == 4

    def test_an_answer_cut_short_is_not_kept(self, client, router, kept) -> None:
        fake = router(FakeRouter({"isochrone": routing.RouterUnavailable("down")}))
        body = {"points": [HERE], "preset": "default"}
        assert post(client, body).status_code == 503
        fake.answers["isochrone"] = isochrone_answer
        assert post(client, body).status_code == 200
        assert post(client, body).status_code == 200
        assert len(calls(fake)) == 2
