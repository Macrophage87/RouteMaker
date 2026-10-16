"""Snapping an opened GPX track to the map's ways (PLAN.md, Import: map matching): POST /api/match.

The router is replaced at its one network function (`core.routing._transport`), as the route
API's and Nearest's tests do: what the endpoint asks the router for, its size limits, how it
answers when the matcher finds no way, and that it counts toward the routing minute.
"""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from test_nearest import client_slots
from test_ratelimit import in_one_window
from test_route_api import FakeRouter, db, encode_polyline6, hold_slots

from core import map_match, presets, ratelimit, routing

pytestmark = pytest.mark.usefixtures("weekday_clock")

PATH = "/api/match"
TRACK = [[-77.0365, 38.8977], [-77.0331, 38.8990], [-77.0300, 38.9010], [-77.0271, 38.9030]]
SNAPPED = [(-77.03652, 38.89771), (-77.03311, 38.89902), (-77.02705, 38.90301)]


def trace(kinds=("matched", "matched", "interpolated", "unmatched")) -> dict:
    return {
        "shape": encode_polyline6(SNAPPED),
        "matched_points": [{"type": k, "lon": 0, "lat": 0} for k in kinds],
    }


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def post(client, body, **extra):
    return client.post(PATH, data=json.dumps(body), content_type="application/json", **extra)


@pytest.mark.django_db
class TestMatch:
    def test_the_track_comes_back_snapped_with_its_matched_share(self, client, router) -> None:
        fake = router(FakeRouter({"trace_attributes": trace()}))
        response = post(client, {"points": TRACK, "preset": "default"})
        assert response.status_code == 200
        assert response.json() == {"line": [list(p) for p in SNAPPED], "matched_share": 0.75}
        assert fake.endpoints() == ["trace_attributes"]
        url, payload = fake.calls[0]
        # On the ride type's own graph and costing, by map snap, with the track as sent.
        assert payload["shape_match"] == "map_snap"
        assert payload["costing_options"] == presets.costing("default")
        assert payload["shape"][0] == {"lon": TRACK[0][0], "lat": TRACK[0][1]}
        assert len(payload["shape"]) == len(TRACK)
        assert "matched.type" in payload["filters"]["attributes"]

    def test_a_track_the_matcher_cannot_follow_is_said_in_words(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": routing.RouterRefused(400, 444, "no path")}))
        response = post(client, {"points": TRACK, "preset": "default"})
        assert response.status_code == 422
        assert "No street or path along the track" in response.json()["error"]

    def test_a_twin_graph_not_answering_falls_back_to_the_standard_graph(
        self, client, router
    ) -> None:
        fake = router(
            FakeRouter({"trace_attributes": [routing.RouterUnavailable("down"), trace()]})
        )
        response = post(client, {"points": TRACK, "preset": "gravel"})
        assert response.status_code == 200
        urls = [url for url, _ in fake.calls]
        assert urls[0].startswith(settings.VALHALLA_UPSTREAMS["offroad"])
        assert urls[1].startswith(settings.VALHALLA_UPSTREAMS["standard"])

    def test_keep_to_roads_and_assist_snap_on_the_ride_s_own_graph(self, client, router) -> None:
        fake = router(FakeRouter({"trace_attributes": lambda _payload: trace()}))
        # "Keep to roads, not trails" snaps to the no-trail graph, never onto a trail; it does
        # not fall back to a graph with trails either.
        assert (
            post(client, {"points": TRACK, "preset": "gravel", "trails_off": True}).status_code
            == 200
        )
        assert fake.calls[-1][0].startswith(settings.VALHALLA_UPSTREAMS["no-trail"])
        assert post(client, {"points": TRACK, "preset": "cargo", "assist": True}).status_code == 200
        url, payload = fake.calls[-1]
        assert url.startswith(settings.VALHALLA_UPSTREAMS["ebike"])
        assert payload["costing_options"] == presets.costing("cargo", assist=True)
        # Assist on a ride type without it is the ride type's own graph.
        assert (
            post(client, {"points": TRACK, "preset": "default", "assist": True}).status_code == 200
        )
        assert fake.calls[-1][0].startswith(settings.VALHALLA_UPSTREAMS["standard"])
        refused = post(client, {"points": TRACK, "preset": "default", "trails_off": "yes"})
        assert refused.status_code == 400

    def test_a_shape_with_a_jump_comes_back_as_the_matcher_gave_it(self, client, router) -> None:
        # map_snap across a gap in the track: two matched runs in one shape, joined by a jump.
        jumped = [*SNAPPED[:2], (-77.0100, 38.9100), (-77.0095, 38.9104)]
        router(
            FakeRouter(
                {
                    "trace_attributes": {
                        "shape": encode_polyline6(jumped),
                        "matched_points": [{"type": "matched"}] * 2
                        + [{"type": "unmatched"}, {"type": "matched"}],
                    }
                }
            )
        )
        response = post(client, {"points": TRACK, "preset": "default"})
        assert response.status_code == 200
        assert response.json() == {"line": [list(p) for p in jumped], "matched_share": 0.75}

    def test_an_all_unmatched_answer_is_a_share_of_none(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": trace(("unmatched",) * 4)}))
        response = post(client, {"points": TRACK, "preset": "default"})
        # The browser does not use a snap below half (lib/gpxMatch.ts MATCH_MIN_SHARE).
        assert response.status_code == 200 and response.json()["matched_share"] == 0.0
        router(FakeRouter({"trace_attributes": {"shape": "", "matched_points": []}}))
        assert post(client, {"points": TRACK, "preset": "default"}).status_code == 422

    def test_a_body_longer_than_it_declares_is_refused(self, client, router) -> None:
        fake = router(FakeRouter({"trace_attributes": trace()}))
        body = json.dumps({"points": TRACK, "preset": "default", "pad": "x" * map_match.MAX_BYTES})
        response = client.post(
            PATH, data=body, content_type="application/json", CONTENT_LENGTH="10"
        )
        assert response.status_code == 400
        assert fake.calls == []

    def test_a_router_that_does_not_answer_is_503(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": routing.RouterUnavailable("down")}))
        response = post(client, {"points": TRACK, "preset": "default"})
        assert response.status_code == 503 and response["Retry-After"]

    @pytest.mark.parametrize(
        "body",
        [
            {"points": TRACK[:1], "preset": "default"},
            {"points": [[-77.0, "38.9"], [-77.1, 38.9]], "preset": "default"},
            {"points": [[-80.5, 40.0], [-80.6, 40.1]], "preset": "default"},
            {"points": TRACK, "preset": "strava"},
            {"points": TRACK, "preset": "default", "name": "Thursday ride"},
            {"points": [[-77.0, 38.9 + i * 1e-6] for i in range(map_match.MAX_POINTS + 1)]},
            # Past the router's trace limit of 124 mi (200 km).
            {"points": [[-77.4, 38.6], [-76.6, 39.3], [-77.4, 38.6], [-76.6, 39.3]]},
        ],
    )
    def test_a_bad_track_is_refused_before_the_router_is_asked(self, client, router, body) -> None:
        fake = router(FakeRouter({"trace_attributes": trace()}))
        response = post(client, body)
        assert response.status_code == 400 and response.json()["error"]
        assert fake.calls == []

    def test_a_body_past_the_byte_cap_is_refused(self, client, router) -> None:
        fake = router(FakeRouter({"trace_attributes": trace()}))
        body = json.dumps({"points": TRACK, "preset": "default", "pad": "x" * map_match.MAX_BYTES})
        response = client.post(PATH, data=body, content_type="application/json")
        assert response.status_code == 400
        assert fake.calls == []

    def test_it_needs_a_json_body(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": trace()}))
        response = client.post(PATH, data="points", content_type="text/plain")
        assert response.status_code == 400

    def test_it_counts_toward_the_routing_minute(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": lambda _payload: trace()}))

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"198.51.100.{31 + 100 * n}"}
            body = {"points": TRACK, "preset": "default"}
            statuses = [
                post(client, body, **headers).status_code for _ in range(ratelimit.ROUTING.requests)
            ]
            return statuses, post(client, body, **headers)

        statuses, refused = in_one_window(ratelimit.ROUTING.window_s, attempt)
        assert statuses == [200] * ratelimit.ROUTING.requests
        assert refused.status_code == 429


@db
def test_a_client_with_its_routing_slots_taken_is_429(client, router) -> None:
    router(FakeRouter({"trace_attributes": trace()}))
    other = hold_slots(client_slots("198.51.100.41"))
    try:
        refused = post(
            client, {"points": TRACK, "preset": "default"}, HTTP_X_FORWARDED_FOR="198.51.100.41"
        )
    finally:
        other.close()
    assert refused.status_code == 429


def test_it_is_in_the_openapi_schema(client) -> None:
    operation = client.get("/api/openapi.json").json()["paths"][PATH]["post"]
    assert {"200", "400", "422", "429", "503"} <= set(operation["responses"])
