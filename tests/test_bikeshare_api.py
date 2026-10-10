"""POST /api/route with the Bikeshare ride type (FOLLOWUP-BIKESHARE, OWNER-DECISIONS 243-245).

Two fakes stand in for the outside: the routers (at `core.routing._transport`, answering
pedestrian and bicycle routes by straight lines) and the operator's feeds (the sampled
fixtures, through `core.gbfs.Gbfs`'s fetch). Nothing is fetched and nothing is saved.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_bikeshare import DUPONT, UNION
from test_gbfs import Clock, FakeNetwork, feed_wall
from test_route_api import (
    CONTRACT_KEYS,
    db,
    encode_polyline6,
    post,
    route_answer,
    trace_answer,
)

from core import bikeshare, gbfs, presets, routing
from routemaker.geo import Point, haversine

pytestmark = pytest.mark.usefixtures("weekday_clock")

FRONTEND_BIKESHARE = (
    Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "bikeshare.ts"
).read_text()


class Routers:
    """Valhalla's /route for a pedestrian (straight, 1.2 times) and a bicycle (straight, 1.3)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        self.calls.append((url, payload))
        endpoint = url.rsplit("/", 1)[1]
        points = [(p["lon"], p["lat"]) for p in payload.get("locations", [])]
        if endpoint == "trace_attributes":
            shape = routing.decode_polyline6(payload["encoded_polyline"])
            return trace_answer(shape, [(1, 0, len(shape) - 1, 0.5)])
        assert endpoint == "route"
        km = haversine(Point(*points[0]), Point(*points[1])) / 1000
        if payload["costing"] == "pedestrian":
            return {
                "trip": {
                    "legs": [
                        {
                            "shape": encode_polyline6(points),
                            "summary": {"length": km * 1.2, "time": km * 1.2 * 3600 / 4.8},
                        }
                    ],
                    "summary": {"length": km * 1.2, "time": km * 1.2 * 3600 / 4.8},
                }
            }
        return route_answer([(points, km * 1.3, [10.0, 12.0])])

    def rides(self) -> list[tuple[str, dict]]:
        return [
            (u, p) for u, p in self.calls if p.get("costing") == "bicycle" and u.endswith("/route")
        ]

    def walks(self) -> list[tuple[str, dict]]:
        return [(u, p) for u, p in self.calls if p.get("costing") == "pedestrian"]


@pytest.fixture
def world(monkeypatch, segment_schemas):
    routers = Routers()
    monkeypatch.setattr(routing, "_transport", routers)
    net = FakeNetwork()
    monkeypatch.setattr(gbfs, "client", gbfs.Gbfs(net, Clock(), wall=feed_wall))
    return routers, net


def body(bike: str | None = "classic", **extra) -> dict:
    out = {"points": [UNION, DUPONT], "preset": "bikeshare", **extra}
    if bike is not None:
        out["bike"] = bike
    return out


@db
class TestBikeshareAnswer:
    def test_a_plan_carries_the_contract_fields_and_the_bikeshare_object(
        self, client, world
    ) -> None:
        response = post(client, body())
        assert response.status_code == 200, response.content
        data = response.json()
        assert set(data) == CONTRACT_KEYS
        assert data["preset"] == "bikeshare"
        plan = data["bikeshare"]
        assert set(plan) == {
            "bike",
            "ending",
            "start",
            "end",
            "walk_start",
            "walk_end",
            "ride_m",
            "ride_s",
            "walk_m",
            "walk_s",
            "total_s",
            "availability",
            "endings",
            "pricing",
            "pricing_note",
            "steps",
            "summary",
            "notes",
            "credit",
        }
        assert plan["start"]["name"] == "Columbus Circle / Union Station"
        assert plan["walk_start"]["geometry"]["type"] == "LineString"
        assert plan["steps"][0]["text"].endswith("take a classic bike (12 available).")

    def test_an_ordinary_route_has_a_null_bikeshare(self, client, world) -> None:
        response = post(client, {"points": [UNION, DUPONT], "preset": "default"})
        assert response.status_code == 200
        assert response.json()["bikeshare"] is None
        assert gbfs.CREDIT not in response.json()["attribution"]

    def test_the_ride_leg_is_planned_between_the_docks_not_the_points(self, client, world) -> None:
        routers, _ = world
        data = post(client, body()).json()
        _url, ride = routers.rides()[0]
        locations = [[p["lon"], p["lat"]] for p in ride["locations"]]
        assert locations[0] == [
            data["bikeshare"]["start"]["lon"],
            data["bikeshare"]["start"]["lat"],
        ]
        assert locations[1] == [data["bikeshare"]["end"]["lon"], data["bikeshare"]["end"]["lat"]]
        assert locations[0] != UNION and locations[1] != DUPONT

    def test_the_walks_use_pedestrian_costing_on_the_standard_graph(self, client, world) -> None:
        routers, _ = world
        post(client, body())
        assert routers.walks()
        for url, payload in routers.walks():
            assert url.startswith(routing.settings.VALHALLA_UPSTREAMS["standard"])
            assert (
                payload["costing_options"]["pedestrian"]["walking_speed"]
                == bikeshare.WALK_SPEED_KMH
            )
            assert payload["directions_type"] == "none"

    def test_a_classic_is_hill_averse_heavy_and_slow(self, client, world) -> None:
        routers, _ = world
        data = post(client, body("classic")).json()
        url, ride = routers.rides()[0]
        options = ride["costing_options"]["bicycle"]
        assert url.startswith(routing.settings.VALHALLA_UPSTREAMS["standard"])
        assert options["cycling_speed"] == presets.BIKESHARE_CLASSIC_SPEED_KMH == 13.0
        assert options["use_hills"] == 0.4  # hills -60
        assert data["dials"]["hills"] == -60 and data["dials"]["assist"] is False
        assert data["dials"]["stress"] == presets.BIKESHARE_STRESS == 80  # calm by default

    def test_an_ebike_barely_minds_hills_and_rides_assisted_on_the_ebike_graph(
        self, client, world
    ) -> None:
        routers, _ = world
        data = post(client, body("ebike")).json()
        url, ride = routers.rides()[0]
        options = ride["costing_options"]["bicycle"]
        assert url.startswith(routing.settings.VALHALLA_UPSTREAMS["ebike"])
        assert options["cycling_speed"] == presets.BIKESHARE_EBIKE_SPEED_KMH == 20.0
        assert options["use_hills"] == 0.8  # hills -20
        assert data["dials"]["hills"] == -20 and data["dials"]["assist"] is True
        assert data["bikeshare"]["bike"] == "ebike"

    @pytest.mark.parametrize(("stress", "use_roads"), [(0, 1.0), (35, 0.55), (70, 0.1), (100, 0.0)])
    @pytest.mark.parametrize("bike", ["classic", "ebike"])
    def test_the_traffic_slider_moves_the_ride_leg(
        self, client, world, bike, stress, use_roads
    ) -> None:
        routers, _ = world
        assert post(client, body(bike, stress=stress)).status_code == 200
        assert routers.rides()[0][1]["costing_options"]["bicycle"]["use_roads"] == use_roads

    def test_the_bike_defaults_to_classic(self, client, world) -> None:
        data = post(client, body(None)).json()
        assert data["bikeshare"]["bike"] == "classic"

    def test_the_riders_sliders_still_apply_to_the_ride_leg(self, client, world) -> None:
        routers, _ = world
        data = post(client, body("ebike", stress=95, hills=-90)).json()
        assert data["dials"]["stress"] == 95 and data["dials"]["hills"] == -90

    def test_keep_to_roads_applies_to_the_ride_leg(self, client, world) -> None:
        """OWNER-DECISIONS 463b: one switch on every ride type, Bikeshare's too."""
        assert post(client, body("classic", trails_off=True)).json()["dials"]["trails_off"] is True
        assert post(client, body("classic")).json()["dials"]["trails_off"] is False

    def test_the_credit_is_in_the_plan_and_the_route_attribution(self, client, world) -> None:
        data = post(client, body()).json()
        assert data["bikeshare"]["credit"] == gbfs.CREDIT
        assert data["attribution"][-1] == gbfs.CREDIT

    def test_the_front_ends_credit_is_the_apis(self) -> None:
        found = re.search(r'BIKESHARE_CREDIT =\s*"([^"]+)"', FRONTEND_BIKESHARE)
        assert found and found.group(1) == gbfs.CREDIT

    def test_the_credit_names_the_operator_only_as_a_plain_source_note(self) -> None:
        assert gbfs.CREDIT == "Capital Bikeshare"
        # The operator is named nowhere else in what a rider is shown: the rest of the words say
        # "Bikeshare" or "the operator".
        for text in bikeshare.OUTSIDE_REASON_WORDS.values():
            text = text.replace(bikeshare.EBIKE_PAGE, "")  # the operator's own page, as a link
            assert "Capital" not in text and "Lyft" not in text
        for source in (Path(bikeshare.__file__).read_text(),):
            assert "Capital" not in source.replace("Capital Bikeshare Data", "")

    def test_a_plan_sets_no_cookie_and_sends_the_feeds_nothing_of_the_visitor(
        self, client, world
    ) -> None:
        _, net = world
        response = post(
            client, body(), HTTP_X_FORWARDED_FOR="203.0.113.9", HTTP_USER_AGENT="secret-agent"
        )
        assert response.status_code == 200
        assert not response.cookies
        assert net.calls and all("?" not in url for url in net.calls)
        assert set(net.calls) <= set(net.by_url) | {gbfs.DISCOVERY_URL}

    def test_the_operator_is_asked_once_for_many_plans(self, client, world) -> None:
        _, net = world
        for _ in range(3):
            assert post(client, body()).status_code == 200
        assert gbfs.client.refreshes == 1 and len(net.calls) == 6


@db
class TestBikeshareDegrades:
    def test_with_the_availability_feed_down_the_plan_says_availability_is_unknown(
        self, client, monkeypatch, segment_schemas
    ) -> None:
        monkeypatch.setattr(routing, "_transport", Routers())
        monkeypatch.setattr(
            gbfs, "client", gbfs.Gbfs(FakeNetwork(fail={"station_status"}), Clock(), wall=feed_wall)
        )
        data = post(client, body()).json()
        plan = data["bikeshare"]
        assert plan["availability"] == "unknown"
        assert (
            plan["start"]["availability"] == "unknown" and plan["start"]["bikes_available"] is None
        )
        assert any("unknown" in n for n in plan["notes"])

    def test_with_no_station_list_it_is_a_503_with_its_own_code(
        self, client, monkeypatch, segment_schemas
    ) -> None:
        routers = Routers()
        monkeypatch.setattr(routing, "_transport", routers)
        net = FakeNetwork()
        net.down = True
        monkeypatch.setattr(gbfs, "client", gbfs.Gbfs(net, Clock(), wall=feed_wall))
        response = post(client, body())
        assert response.status_code == 503
        assert response.json()["code"] == "bikeshare_unavailable"
        assert response["Retry-After"]
        assert routers.calls == []  # nothing is routed without docks

    def test_no_dock_in_reach_is_a_422_with_its_own_code(self, client, world) -> None:
        response = post(client, {"points": [[-77.2, 39.0], [-77.19, 39.0]], "preset": "bikeshare"})
        assert response.status_code == 422
        assert response.json()["code"] == "no_bikeshare"
        assert "No dock within" in response.json()["error"]

    def test_an_ebike_asking_to_end_outside_a_dock_without_zone_data_ends_at_a_dock(
        self, client, world
    ) -> None:
        data = post(client, body("ebike", ending="outside_dock")).json()
        plan = data["bikeshare"]
        assert plan["ending"] == "dock"
        outside = next(e for e in plan["endings"] if e["kind"] == "outside_dock")
        assert not outside["offered"] and outside["reason"] == "no_zone_data"


@db
class TestBikeshareValidation:
    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"points": [UNION]}, "at least 2"),
            ({"points": [UNION, [-77.02, 38.9], DUPONT]}, "take a start and an end"),
            ({"bike": "tandem"}, "bike"),
            ({"ending": "anywhere"}, "ending"),
            (
                {"bike": "classic", "ending": "outside_dock"},
                "only an e-bike can end outside a dock",
            ),
            ({"assist": True}, "assist applies to the Cargo Bike"),
            ({"loop": True}, "does not plan loops"),
            ({"carrying": "cargo"}, "carrying applies to the Cargo Bike"),
        ],
    )
    def test_what_bikeshare_will_not_take(self, client, world, changes, message) -> None:
        response = post(client, {**body(), **changes})
        assert response.status_code == 400, response.content
        assert message in response.json()["error"]

    @pytest.mark.parametrize("preset", ["default", "ebike", "cargo", "mass-ride"])
    def test_bike_and_ending_belong_to_bikeshare_only(self, client, world, preset) -> None:
        for extra in ({"bike": "classic"}, {"ending": "dock"}):
            response = post(client, {"points": [UNION, DUPONT], "preset": preset, **extra})
            assert response.status_code == 400
            assert "Bikeshare ride type only" in response.json()["error"]

    def test_the_schema_describes_the_bikeshare_answer(self, client) -> None:
        schema = client.get("/api/openapi.json").json()
        assert "BikesharePlanOut" in schema["components"]["schemas"]
        route_in = schema["components"]["schemas"]["RouteIn"]["properties"]
        assert "bike" in route_in and "ending" in route_in
        assert "bikeshare" in schema["components"]["schemas"]["RouteOut"]["properties"]
