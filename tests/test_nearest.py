"""The nearest water, restroom or Metro station (owner, 2026-10-10): POST /api/nearest.

The router is replaced at its one network function (`core.routing._transport`), as
the route API's and Best order's tests do: what the endpoint asks the router for,
and how it answers with and without the router's distances.
"""

from __future__ import annotations

import json
import logging

import pytest
from test_route_api import FakeRouter

from core import nearest, presets, routing
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
