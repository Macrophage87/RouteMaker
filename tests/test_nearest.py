"""The nearest water, restroom or Metro station (owner, 2026-10-10): POST /api/nearest.

The router is replaced at its one network function (`core.routing._transport`), as
the route API's and Best order's tests do: what the endpoint asks the router for,
and how it answers with and without the router's distances.
"""

from __future__ import annotations

import json
import logging

import pytest
from test_ratelimit import in_one_window
from test_route_api import FakeRouter, db, hold_slots

from core import nearest, presets, ratelimit, routing
from routemaker.geo import Point, haversine

pytestmark = pytest.mark.usefixtures("weekday_clock")

PATH = "/api/nearest"

# The rider in Northwest DC, then three places east of them along the parallel.
HERE = [-77.05, 38.90]
PLACES = [[-77.03, 38.90], [-77.04, 38.90], [-77.02, 38.90]]


def row_answer(cells) -> dict:
    """One row of a matrix: (seconds, km) per place, or None for no way there."""
    return {
        "sources_to_targets": [
            [
                {"from_index": 0, "to_index": j}
                if cell is None
                else {"from_index": 0, "to_index": j, "time": cell[0], "distance": cell[1]}
                for j, cell in enumerate(cells)
            ]
        ]
    }


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def post(client, body):
    return client.post(PATH, data=json.dumps(body), content_type="application/json")


@pytest.mark.django_db
class TestNearest:
    def test_each_place_comes_back_with_its_riding_distance_in_the_order_sent(
        self, client, router
    ) -> None:
        fake = router(
            FakeRouter({"sources_to_targets": row_answer([(300, 2.5), (120, 1.0), (500, 3.75)])})
        )
        response = post(client, {"points": [HERE, *PLACES], "preset": "default"})
        assert response.status_code == 200
        assert response.json() == {
            "by": "riding",
            "places": [
                {"distance_m": 2500, "time_s": 300},
                {"distance_m": 1000, "time_s": 120},
                {"distance_m": 3750, "time_s": 500},
            ],
        }
        assert fake.endpoints() == ["sources_to_targets"]

    def test_one_row_from_the_rider_to_the_places_on_the_rides_own_graph_and_costing(
        self, client, router
    ) -> None:
        fake = router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * 3)}))
        body = {
            "points": [HERE, *PLACES],
            "preset": "cargo",
            "stress": 85,
            "hills": -40,
            "assist": True,
            "avoid_gravel": True,
            "when": "weekday_offpeak",
        }
        assert post(client, body).status_code == 200
        url, payload = fake.calls[0]
        assert url.startswith(routing.settings.VALHALLA_UPSTREAMS["ebike"])
        assert payload["sources"] == [{"lon": HERE[0], "lat": HERE[1]}]
        assert payload["targets"] == [{"lon": lon, "lat": lat} for lon, lat in PLACES]
        assert payload["costing"] == "bicycle"
        assert payload["costing_options"] == presets.costing(
            "cargo", 85, -40, assist=True, avoid_gravel=True
        )

    def test_the_graph_and_costing_are_best_orders(self, client, router) -> None:
        # The same ride asks Best order's matrix and this one on the same router and costing.
        fake = router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * 3)}))
        for body in (
            {"preset": "default", "stress": 90, "hills": 30, "when": "weekday_rush"},
            {"preset": "gravel", "hills": -60},
            {"preset": "group-ride", "when": "weekend"},
        ):
            assert post(client, {"points": [HERE, *PLACES], **body}).status_code == 200
            dials = routing.Dials(**{k: v for k, v in body.items() if k != "preset"})
            variant, costing = nearest.stoporder.ride_graph(body["preset"], dials)
            url, payload = fake.calls[-1]
            assert url == f"{routing.settings.VALHALLA_UPSTREAMS[variant]}/sources_to_targets"
            assert payload["costing_options"] == costing

    def test_a_place_the_router_cannot_reach_has_no_distance(self, client, router) -> None:
        router(FakeRouter({"sources_to_targets": row_answer([(300, 2.5), None, (500, 3.75)])}))
        body = post(client, {"points": [HERE, *PLACES], "preset": "default"}).json()
        assert body["by"] == "riding"
        assert body["places"][1] == {"distance_m": None, "time_s": None}
        assert body["places"][0]["distance_m"] == 2500

    @pytest.mark.parametrize(
        "answer",
        [
            routing.RouterRefused(400, 106, "Try any of: route"),
            routing.RouterUnavailable("down"),
            {"sources_to_targets": [[]]},
            {"sources_to_targets": []},
            {},
        ],
    )
    def test_without_the_routers_distances_it_answers_in_straight_lines(
        self, client, router, answer, caplog
    ) -> None:
        router(FakeRouter({"sources_to_targets": answer}))
        with caplog.at_level(logging.WARNING, logger="core.nearest"):
            body = post(client, {"points": [HERE, *PLACES], "preset": "default"}).json()
        assert body["by"] == "straight_line"
        expected = [round(haversine(Point(*HERE), Point(*p))) for p in PLACES]
        assert [p["distance_m"] for p in body["places"]] == expected
        assert all(p["time_s"] is None for p in body["places"])
        # The rider's position is never logged.
        assert "38.9" not in caplog.text and "-77.0" not in caplog.text

    def test_a_place_over_93_mi_away_is_measured_without_the_router(self, client, router) -> None:
        fake = router(FakeRouter({}))
        far = [-76.0300, 39.7100]  # north-east corner of the coverage, about 107 mi away
        body = post(client, {"points": [[-77.95, 38.25], far], "preset": "default"}).json()
        assert body["by"] == "straight_line"
        assert body["places"][0]["distance_m"] > nearest.LONG_SPAN_M
        assert fake.calls == []

    def test_places_far_apart_are_not_refused_as_a_ride_too_long(self, client, router) -> None:
        # The places are not ridden one to the next, so the route's span cap does not apply.
        far_apart = [[-77.90, 38.30], [-76.10, 39.65], [-77.90, 38.30], [-76.10, 39.65]]
        router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * 4)}))
        response = post(client, {"points": [HERE, *far_apart], "preset": "default"})
        assert response.status_code == 200

    def test_mass_ride_may_ask(self, client, router) -> None:
        router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * 3)}))
        response = post(client, {"points": [HERE, *PLACES], "preset": "mass-ride"})
        assert response.status_code == 200

    def test_the_rider_and_at_least_one_place_and_at_most_ten(self, client, router) -> None:
        router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * nearest.MAX_PLACES)}))
        assert post(client, {"points": [HERE], "preset": "default"}).status_code == 400
        eleven = [[HERE[0] + 0.001 * i, HERE[1]] for i in range(1, nearest.MAX_PLACES + 2)]
        assert post(client, {"points": [HERE, *eleven], "preset": "default"}).status_code == 400
        ten = eleven[: nearest.MAX_PLACES]
        assert post(client, {"points": [HERE, *ten], "preset": "default"}).status_code == 200

    def test_a_point_outside_the_coverage_is_refused(self, client, router) -> None:
        fake = router(FakeRouter({}))
        response = post(client, {"points": [HERE, [-80.0, 38.9]], "preset": "default"})
        assert response.status_code == 400
        assert "outside the area" in response.json()["error"]
        assert fake.calls == []

    def test_the_body_is_checked_as_a_route_requests_is(self, client, router) -> None:
        router(FakeRouter({}))
        bad = [
            {"points": [HERE, *PLACES], "preset": "nope"},
            {"points": [HERE, *PLACES], "preset": "default", "stress": 101},
            {"points": [HERE, *PLACES], "preset": "default", "extra": 1},
            {"points": [HERE, *PLACES], "preset": "mass-ride", "hills": 20},
        ]
        for body in bad:
            assert post(client, body).status_code == 400, body

    def test_only_json_is_read(self, client, router) -> None:
        router(FakeRouter({}))
        response = client.post(
            PATH,
            data=json.dumps({"points": [HERE, *PLACES], "preset": "default"}),
            content_type="text/plain",
        )
        assert response.status_code == 400

    def test_out_of_time_is_a_503_to_try_again(self, client, router, monkeypatch) -> None:
        def late(*args, **kwargs):
            raise routing.DeadlineExceeded()

        monkeypatch.setattr(nearest, "distances", late)
        response = post(client, {"points": [HERE, *PLACES], "preset": "default"})
        assert response.status_code == 503
        assert response["Retry-After"]


@pytest.mark.django_db
class TestNearestDetails:
    def test_distances_and_times_are_rounded_to_whole_metres_and_seconds(self, client, router):
        router(FakeRouter({"sources_to_targets": row_answer([(299.6, 1.2346), (0.4, 0.0004)])}))
        body = post(client, {"points": [HERE, *PLACES[:2]], "preset": "default"}).json()
        assert body["places"] == [
            {"distance_m": 1235, "time_s": 300},
            {"distance_m": 0, "time_s": 0},
        ]

    def test_a_cell_with_a_time_but_no_distance_is_no_way_there(self, client, router) -> None:
        answer = row_answer([(300, 2.5), (120, 1.0)])
        del answer["sources_to_targets"][0][1]["distance"]
        router(FakeRouter({"sources_to_targets": answer}))
        body = post(client, {"points": [HERE, *PLACES[:2]], "preset": "default"}).json()
        assert body["by"] == "riding"
        assert body["places"][1] == {"distance_m": None, "time_s": None}

    def test_when_no_place_can_be_reached_the_answer_is_in_straight_lines(self, client, router):
        router(FakeRouter({"sources_to_targets": row_answer([None, None, None])}))
        body = post(client, {"points": [HERE, *PLACES], "preset": "default"}).json()
        assert body["by"] == "straight_line"
        assert all(p["distance_m"] > 0 for p in body["places"])

    def test_one_place_over_93_mi_away_puts_every_place_in_straight_lines(self, client, router):
        fake = router(FakeRouter({}))
        start = [-77.95, 38.25]
        near = [-77.94, 38.25]
        far = [-76.03, 39.71]
        body = post(client, {"points": [start, near, far], "preset": "default"}).json()
        assert body["by"] == "straight_line"
        assert fake.calls == []

    def test_a_point_in_the_zoo_is_measured_from_its_bike_racks(self, client, router, monkeypatch):
        racks = [-77.0500, 38.9300]
        monkeypatch.setattr(
            routing.zoo, "redirect", lambda lon, lat: racks if lon == HERE[0] else None
        )
        fake = router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * 3)}))
        assert post(client, {"points": [HERE, *PLACES], "preset": "default"}).status_code == 200
        assert fake.calls[0][1]["sources"] == [{"lon": racks[0], "lat": racks[1]}]

    def test_cargo_with_people_is_asked_at_its_own_start(self, client, router) -> None:
        fake = router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * 3)}))
        body = {"points": [HERE, *PLACES], "preset": "cargo", "carrying": "people"}
        assert post(client, body).status_code == 200
        stress = presets.stress_start("cargo", "people")
        assert stress != presets.stress_start("cargo", None)
        preset = presets.PRESETS["cargo"]
        assert fake.calls[0][1]["costing_options"] == presets.costing("cargo", stress, preset.hills)

    def test_the_time_budget_runs_from_when_the_request_arrived(self, client, router, monkeypatch):
        seen = []
        real = nearest.distances

        def spy(points, preset, dials, started=None):
            seen.append(started)
            return real(points, preset, dials, started=started)

        monkeypatch.setattr(nearest, "distances", spy)
        router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * 3)}))
        assert post(client, {"points": [HERE, *PLACES], "preset": "default"}).status_code == 200
        assert seen and seen[0] is not None


@pytest.mark.django_db
class TestNearestLimits:
    def test_it_counts_toward_the_routing_minute(self, client, router) -> None:
        router(
            FakeRouter(
                {
                    "sources_to_targets": [row_answer([(1, 1)] * 3)]
                    * (2 * ratelimit.ROUTING.requests + 5)
                }
            )
        )

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"198.51.100.{30 + 100 * n}"}
            body = json.dumps({"points": [HERE, *PLACES], "preset": "default"})
            send = lambda: client.post(PATH, data=body, content_type="application/json", **headers)  # noqa: E731
            statuses = [send().status_code for _ in range(ratelimit.ROUTING.requests)]
            return statuses, send()

        statuses, refused = in_one_window(ratelimit.ROUTING.window_s, attempt)
        assert statuses == [200] * ratelimit.ROUTING.requests
        assert refused.status_code == 429


def client_slots(address: str):
    """Every routing slot of one client, as test_route_api.TestInFlight takes them."""
    limit = ratelimit.ROUTING_IN_FLIGHT
    key = ratelimit._client_lock_id(ratelimit.client_key(address))
    return [
        (ratelimit._LOCK_CLASS_CLIENT + limit.scope_id * 64 + slot, key)
        for slot in range(limit.per_client)
    ]


@db
class TestNearestSlots:
    def test_a_client_with_its_routing_slots_taken_is_429(self, client, router) -> None:
        router(FakeRouter({"sources_to_targets": row_answer([(1, 1)] * 3)}))
        other = hold_slots(client_slots("198.51.100.40"))
        try:
            refused = client.post(
                PATH,
                data=json.dumps({"points": [HERE, *PLACES], "preset": "default"}),
                content_type="application/json",
                HTTP_X_FORWARDED_FOR="198.51.100.40",
            )
        finally:
            other.close()
        assert refused.status_code == 429
