# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""v0.7.0 routing UX on the server: the Novice and Nervous ride type (in Riding with kids'
place) and via points that only shape the route (v0.7.0 plan, "Novice and Nervous ride
type" and "Via points vs stops").

The router is the fake of tests/test_route_api.py, so these see exactly what is sent to
Valhalla and what the answer says."""

from __future__ import annotations

import pytest
from test_my_go import save, signed_in_client
from test_route_api import (  # noqa: F401 (fixtures)
    VERTICES,
    good_body,
    post,
    router,
    segments,
    standard_router,
)

from core import presets, routing
from core.models import MyGo

pytestmark = pytest.mark.usefixtures("weekday_clock")

db = pytest.mark.django_db(transaction=True)


def three_points() -> list[list[float]]:
    return [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])]


@db
class TestNoviceAndNervous:
    def test_an_old_riding_with_kids_link_plans_as_novice_and_nervous(
        self, client, segments, router
    ) -> None:
        fake = router(standard_router())
        response = post(client, good_body("kids"))
        assert response.status_code == 200, response.content
        assert response.json()["preset"] == "novice"
        assert fake.calls[0][1]["costing_options"] == presets.costing("novice")

    def test_the_answer_says_how_much_busy_road_is_left_and_offers_transit(
        self, client, segments, router
    ) -> None:
        """The standard world rides 900 m of LTS 3 and 400 m of LTS 4: real LTS 3 and worse
        is left, so transit and bikeshare are offered beside the bike route (item 4)."""
        router(standard_router())
        body = post(client, good_body("novice")).json()
        note = body["novice"]
        assert note["busy_m"] == pytest.approx(1300.0)
        assert note["transit"] is True
        assert note["busiest"]["level"] in (3, 4)
        # The summary reads the real levels, not the shifted ones (item 6).
        assert body["stress_m"]["3"] == pytest.approx(900.0)
        assert body["stress_m"]["4"] == pytest.approx(400.0)

    def test_other_ride_types_have_no_novice_block(self, client, segments, router) -> None:
        router(standard_router())
        assert post(client, good_body("default")).json()["novice"] is None

    def test_novice_legs_are_for_the_transit_ride_types_only(self, client, router) -> None:
        fake = router(standard_router())
        response = post(client, {**good_body("default"), "novice_legs": True})
        assert response.status_code == 400
        assert fake.calls == []

    def test_my_go_keeps_an_old_kids_ride_as_novice(self) -> None:
        client, user, csrf = signed_in_client()
        r = save(client, {"open_in": "go", "ride": "kids"}, csrf)
        assert r.status_code == 200, r.content
        assert r.json()["ride"] == "novice"
        assert MyGo.objects.get(user=user).ride == "novice"


class TestNoviceNote:
    def test_a_quiet_route_offers_nothing(self) -> None:
        note = routing.novice_note({"1": 3000.0, "2": 500.0, "3": 40.0}, {}, None)
        assert note["transit"] is False
        assert note["busy_m"] == 40.0

    def test_a_route_held_at_the_ceiling_offers_transit(self) -> None:
        note = routing.novice_note({"1": 3000.0}, {"limited": "ceiling"}, None)
        assert note["over_ceiling"] is True
        assert note["transit"] is True

    def test_the_busiest_stretch_is_the_longest_named_run_of_lts3_or_worse(self) -> None:
        def piece(name: str, metres: float) -> routing.Piece:
            return routing.Piece(1, -77.0, 38.9, metres, names=(name,) if name else ())

        pieces = [piece("Quiet St", 500), piece("16th St", 300), piece("16th St", 200)]
        pieces += [piece("Calm Ave", 100), piece("Georgia Ave", 400)]
        classes = [("1", "none"), ("3", "none"), ("4", "none"), ("2", "none"), ("3", "none")]
        assert routing.busiest_stretch(pieces, classes) == {
            "name": "16th St",
            "metres": 500.0,
            "level": 4,
        }
        assert routing.busiest_stretch(pieces[:1], classes[:1]) is None


@db
class TestViaPoints:
    def test_a_via_point_is_passed_without_a_stop(self, client, segments, router) -> None:
        fake = router(standard_router())
        response = post(client, {"points": three_points(), "preset": "default", "via_points": [1]})
        assert response.status_code == 200, response.content
        types = [loc["type"] for loc in fake.calls[0][1]["locations"]]
        assert types == ["break", routing.VIA_LOCATION_TYPE, "break"]

    def test_without_via_points_every_point_is_a_stop(self, client, segments, router) -> None:
        fake = router(standard_router())
        post(client, {"points": three_points(), "preset": "default"})
        assert [loc["type"] for loc in fake.calls[0][1]["locations"]] == ["break"] * 3

    @pytest.mark.parametrize("vias", [[0], [2], [1, 1], [5]])
    def test_the_ends_and_unknown_points_cannot_be_via_points(self, client, router, vias) -> None:
        fake = router(standard_router())
        body = {"points": three_points(), "preset": "default", "via_points": vias}
        assert post(client, body).status_code == 400
        assert fake.calls == []


class TestLocationType:
    def test_only_a_middle_point_named_a_via_is_one(self) -> None:
        assert routing.location_type(0, 3, (0,)) == "break"
        assert routing.location_type(1, 3, (1,)) == routing.VIA_LOCATION_TYPE
        assert routing.location_type(1, 3, ()) == "break"
        assert routing.location_type(2, 3, (2,)) == "break"
        # Valhalla's through types: no U-turn at the point.
        assert routing.VIA_LOCATION_TYPE in ("through", "break_through")
