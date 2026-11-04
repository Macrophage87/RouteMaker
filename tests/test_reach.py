"""Reach (Stephen, 2026-11-04): POST /api/reach, where a rider can be in 15, 30, 45 and 60 min.

The router is replaced at its one network function (`core.routing._transport`), as the
nearest-place tests do: what each isochrone call asks for (graph, costing, contours, reverse),
how several points combine, the calm layer, the places counted inside a ring and the refusals.
"""

from __future__ import annotations

import json

import pytest
from test_route_api import FakeRouter, db  # noqa: F401  (db: the fixture the route tests use)

from core import presets, reach, routing

pytestmark = pytest.mark.usefixtures("weekday_clock")

PATH = "/api/reach"

# Northwest DC, and a second point 0.02 degrees east (about a mile).
HERE = [-77.05, 38.90]
EAST = [-77.03, 38.90]


def square(lon: float, lat: float, half: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half, lat - half],
                [lon + half, lat - half],
                [lon + half, lat + half],
                [lon - half, lat + half],
                [lon - half, lat - half],
            ]
        ],
    }


def isochrone_answer(payload: dict) -> dict:
    """Squares about the location, 0.002 degrees across per minute of each contour."""
    location = payload["locations"][0]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"contour": c["time"], "metric": "time"},
                "geometry": square(location["lon"], location["lat"], 0.001 * c["time"]),
            }
            for c in payload["contours"]
        ],
    }


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


@pytest.fixture
def no_places(monkeypatch):
    monkeypatch.setattr(
        reach, "places", lambda: {"metro": [], "racks": [], "food": [], "sights": []}
    )


def post(client, body):
    return client.post(PATH, data=json.dumps(body), content_type="application/json")


def calls(fake: FakeRouter) -> list[dict]:
    return [payload for url, payload in fake.calls if url.endswith("/isochrone")]


@pytest.mark.django_db
@pytest.mark.usefixtures("no_places")
class TestRings:
    def test_four_rings_15_to_60_minutes_by_default_smallest_first(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        response = post(client, {"points": [HERE], "preset": "default"})
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["minutes"] == [15, 30, 45, 60]
        (group,) = body["groups"]
        assert [r["minutes"] for r in group["rings"]] == [15, 30, 45, 60]
        areas = [r["area_sq_mi"] for r in group["rings"]]
        assert areas == sorted(areas) and areas[0] > 0
        assert group["rings"][0]["geometry"]["type"] == "Polygon"
        (payload,) = calls(fake)
        assert payload["contours"] == [{"time": 15}, {"time": 30}, {"time": 45}, {"time": 60}]
        assert payload["polygons"] is True
        assert "reverse" not in payload

    def test_rings_ride_the_ride_types_own_graph_and_traffic_setting(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        post(client, {"points": [HERE], "preset": "default", "stress": 10})
        (payload,) = calls(fake)
        assert payload["costing"] == "bicycle"
        assert payload["costing_options"]["bicycle"]["use_roads"] == presets.use_roads_for(10)

    def test_a_lower_traffic_tolerance_asks_for_calmer_ways(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        post(client, {"points": [HERE], "preset": "default", "stress": 10})
        post(client, {"points": [HERE], "preset": "default", "stress": 70})
        direct, calm = calls(fake)
        assert (
            calm["costing_options"]["bicycle"]["use_roads"]
            < direct["costing_options"]["bicycle"]["use_roads"]
        )

    def test_above_low_stress_the_rings_are_low_stresss_and_say_so(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        body = post(client, {"points": [HERE], "preset": "default", "stress": 100}).json()
        assert body["stress_used"] == presets.STRESS_TODAYS_TOP
        (payload,) = calls(fake)
        assert payload["costing_options"]["bicycle"]["use_roads"] == 0

    @pytest.mark.parametrize(
        "preset",
        sorted(set(presets.PRESETS) - reach.NOT_YET - reach.ON_FOOT - {presets.BIKESHARE}),
    )
    def test_every_bike_ride_type_has_rings(self, client, router, preset) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        response = post(client, {"points": [HERE], "preset": preset})
        assert response.status_code == 200, response.content
        assert response.json()["preset"] == preset
        assert calls(fake)[0]["costing"] == "bicycle"

    def test_walk_and_run_go_on_foot(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        post(client, {"points": [HERE], "preset": "walk"})
        post(client, {"points": [HERE], "preset": "run", "run_pace_kmh": 12.0})
        walk, run = calls(fake)
        assert walk["costing"] == "pedestrian" and run["costing"] == "pedestrian"
        assert run["costing_options"]["pedestrian"]["walking_speed"] == 12.0
        assert walk["costing_options"]["pedestrian"]["walking_speed"] < 6

    def test_bikeshare_rides_as_a_plain_bike(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        body = post(client, {"points": [HERE], "preset": "bikeshare"}).json()
        assert body["preset"] == "default"

    def test_the_transit_ride_types_have_no_rings_yet(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        response = post(client, {"points": [HERE], "preset": "bike-transit"})
        assert response.status_code in (400, 422)
        assert calls(fake) == []

    def test_to_is_the_routers_reverse_isochrone(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        body = post(client, {"points": [HERE], "preset": "default", "direction": "to"}).json()
        assert body["direction"] == "to"
        assert calls(fake)[0]["reverse"] is True

    def test_minutes_are_held_to_5_to_60(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        assert post(
            client, {"points": [HERE], "preset": "default", "minutes": [90]}
        ).status_code in (
            400,
            422,
        )
        body = post(client, {"points": [HERE], "preset": "default", "minutes": [20, 10]}).json()
        assert body["minutes"] == [10, 20]

    def test_mass_rides_locked_slider_is_held(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        response = post(client, {"points": [HERE], "preset": "mass-ride", "stress": 90})
        assert response.status_code in (400, 422)


@pytest.mark.django_db
@pytest.mark.usefixtures("no_places")
class TestSeveralPoints:
    def test_any_is_one_set_of_rings_covering_both(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        # 5 min squares are 0.01 degrees across, 0.02 apart: the union is twice one.
        one = post(client, {"points": [HERE], "preset": "default", "minutes": [5]}).json()
        both = post(client, {"points": [HERE, EAST], "preset": "default", "minutes": [5]}).json()
        assert len(calls(fake)) == 3
        (group,) = both["groups"]
        assert group["point"] is None
        assert group["rings"][0]["area_sq_mi"] == pytest.approx(
            2 * one["groups"][0]["rings"][0]["area_sq_mi"], rel=0.02
        )

    def test_all_is_where_every_point_reaches(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        body = post(client, {"points": [HERE, EAST], "preset": "default", "combine": "all"}).json()
        rings = body["groups"][0]["rings"]
        # 15 min squares are 0.03 degrees across, 0.02 apart: they overlap; and 5 min ones not.
        assert rings[0]["area_sq_mi"] > 0
        smaller = post(
            client,
            {"points": [HERE, EAST], "preset": "default", "combine": "all", "minutes": [5]},
        ).json()
        assert smaller["groups"][0]["rings"][0]["geometry"] is None
        assert smaller["groups"][0]["rings"][0]["area_sq_mi"] == 0

    def test_each_is_a_set_of_rings_per_point(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        body = post(client, {"points": [HERE, EAST], "preset": "default", "combine": "each"}).json()
        assert [g["point"] for g in body["groups"]] == [0, 1]

    def test_at_most_five_points(self, client, router) -> None:
        router(FakeRouter({"isochrone": isochrone_answer}))
        response = post(client, {"points": [HERE] * 6, "preset": "default"})
        assert response.status_code in (400, 422)

    def test_a_point_off_the_map_is_left_out_and_named(self, client, router) -> None:
        def answer(payload):
            if payload["locations"][0]["lon"] == EAST[0]:
                return routing.RouterRefused(400, 171, "No suitable edges near location")
            return isochrone_answer(payload)

        router(FakeRouter({"isochrone": answer}))
        body = post(client, {"points": [HERE, EAST], "preset": "default"}).json()
        assert body["unplaced"] == [1]
        assert len(body["groups"]) == 1

    def test_no_point_on_the_map_is_a_sentence_to_say(self, client, router) -> None:
        router(FakeRouter({"isochrone": routing.RouterRefused(400, 171, "No suitable edges")}))
        response = post(client, {"points": [HERE], "preset": "default"})
        assert response.status_code == 422
        assert "ride type" in response.json()["error"]


@pytest.mark.django_db
@pytest.mark.usefixtures("no_places")
class TestCalm:
    def test_calm_is_the_same_rings_at_low_stress(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        body = post(
            client, {"points": [HERE], "preset": "default", "stress": 40, "calm": True}
        ).json()
        assert body["calm"]["stress"] == presets.STRESS_TODAYS_TOP
        own, calm = calls(fake)
        assert calm["costing_options"]["bicycle"]["use_roads"] == 0
        assert own["costing_options"]["bicycle"]["use_roads"] > 0

    def test_no_calm_layer_where_it_would_say_nothing(self, client, router) -> None:
        fake = router(FakeRouter({"isochrone": isochrone_answer}))
        for body in (
            {"points": [HERE], "preset": "default", "stress": 90, "calm": True},
            {"points": [HERE], "preset": "mass-ride", "calm": True},
            {"points": [HERE], "preset": "walk", "calm": True},
            {"points": [HERE, EAST], "preset": "default", "combine": "each", "calm": True},
        ):
            assert post(client, body).json()["calm"] is None, body
        assert len(calls(fake)) == 1 + 1 + 1 + 2

    def test_the_answer_says_whether_calm_streets_can_show_anything(self, client, router) -> None:
        """The page hides Calm streets where it would draw nothing, so it is never a dead box."""
        router(FakeRouter({"isochrone": isochrone_answer}))
        for body, offered in (
            ({"points": [HERE], "preset": "default", "stress": 40, "calm": False}, True),
            ({"points": [HERE], "preset": "default", "stress": 90, "calm": True}, False),
            ({"points": [HERE], "preset": "mass-ride", "calm": True}, False),
            ({"points": [HERE], "preset": "walk", "calm": True}, False),
        ):
            assert post(client, body).json()["calm_offered"] is offered, body


@pytest.mark.django_db
def test_places_inside_each_ring_are_counted(client, router, monkeypatch) -> None:
    near = (HERE[0] + 0.005, HERE[1], "Near")
    far = (HERE[0] + 0.04, HERE[1], "Far")
    away = (HERE[0] + 1, HERE[1], "Away")
    monkeypatch.setattr(
        reach,
        "places",
        lambda: {"metro": [far, near, away], "racks": [near], "food": [], "sights": [far]},
    )
    router(FakeRouter({"isochrone": isochrone_answer}))
    body = post(client, {"points": [HERE], "preset": "default", "minutes": [15, 60]}).json()
    small, large = body["groups"][0]["rings"]
    assert small["places"] == {"metro": 1, "racks": 1, "food": 0, "sights": 0}
    assert large["places"] == {"metro": 2, "racks": 1, "food": 0, "sights": 1}
    assert body["groups"][0]["metro_stations"] == ["Near", "Far"]


def test_the_place_files_are_read() -> None:
    reach.places.cache_clear()
    found = reach.places()
    assert len(found["metro"]) > 50
    assert all(len(found[kind]) > 100 for kind in ("racks", "food", "sights"))


def test_area_is_in_ground_units() -> None:
    from django.contrib.gis.geos import GEOSGeometry

    # 0.01 degrees square at 38.9 N: 1,113 m x 866 m of ground, about 0.372 sq mi.
    geom = GEOSGeometry(json.dumps(square(-77.0, 38.9, 0.005)), srid=4326)
    assert reach.area_sq_m(geom) / reach.SQ_M_PER_SQ_MI == pytest.approx(0.372, rel=0.01)


def test_a_ring_that_crosses_itself_is_fixed_to_areas_only(caplog) -> None:
    """Valhalla's simplifying can cross a ring over itself. Before: the fixed shape could be a
    collection with lines in it, which the overlap and the GeoJSON could not take (a 500), and
    asking `.valid` first logged GEOS's reason with a coordinate of the rider's place in it."""
    import logging

    caplog.set_level(logging.DEBUG)
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [[-77.0, 38.9], [-76.99, 38.91], [-76.99, 38.9], [-77.0, 38.91], [-77.0, 38.9]]
        ],
    }
    answer = {"features": [{"geometry": bowtie, "properties": {"contour": 15}}]}
    (ring,) = reach._rings_from(answer, [15])
    assert ring.geom_type in ("Polygon", "MultiPolygon") and ring.valid and not ring.empty
    assert "38.9" not in caplog.text and "-77" not in caplog.text
