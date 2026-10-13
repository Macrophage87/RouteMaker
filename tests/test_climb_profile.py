"""GET /api/climbs/{id}/profile: one climb's elevation profile for the map's climb card
(the owner, 2026-10-12: "click on a climb to see more about that climb, such as
elevation profile"). The climb comes from the Climbs layer's file and its heights from
the router, a stand-in for `_transport` here."""

from __future__ import annotations

import json

import pytest

from core import climbprofile, routing
from core import hillseek as hs

db = pytest.mark.django_db(transaction=True)

LINE = [[-77.0, 38.9], [-77.0, 38.905], [-77.0, 38.91]]
ROW = {"id": "abc123", "c": "4", "l": 1110, "r": 60, "g": 5.4, "x": -77.0, "y": 38.91, "line": LINE}


def trip(heights: list[float | None], km: float = 1.11) -> dict:
    return {"trip": {"legs": [{"summary": {"length": km}, "elevation": heights}]}}


@pytest.fixture
def climbs_file(tmp_path, monkeypatch):
    path = tmp_path / "climbs.json"
    path.write_text(json.dumps({"version": 1, "climbs": [ROW]}))
    monkeypatch.setattr(hs, "CLIMBS_FILE", path)
    climbprofile._kept.clear()
    yield path
    climbprofile._kept.clear()


class TestTheRequest:
    def test_foot_to_summit_through_the_climb_with_heights(self, climbs_file) -> None:
        climb = climbprofile.find("abc123")
        assert climb is not None
        request = climbprofile.request_for(climb)
        locations = request["locations"]
        assert locations[0] == {"lon": -77.0, "lat": 38.9, "type": "break"}
        assert locations[-1] == {"lon": -77.0, "lat": 38.91, "type": "break"}
        assert all(loc["type"] == "through" for loc in locations[1:-1])
        assert len(locations) - 2 == len(hs.via_points(climb))
        assert request["elevation_interval"] == routing.ELEVATION_INTERVAL_M
        assert request["costing_options"]["bicycle"]["use_roads"] == 1.0

    def test_an_unknown_id_is_none(self, climbs_file) -> None:
        assert climbprofile.find("nope") is None

    def test_no_file_is_unavailable(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(hs, "CLIMBS_FILE", tmp_path / "none.json")
        with pytest.raises(climbprofile.Unavailable):
            climbprofile.find("abc123")


class TestTheBody:
    def test_samples_grades_and_the_steepest(self, climbs_file) -> None:
        climb = climbprofile.find("abc123")
        heights = [10.0 + 2 * i for i in range(30)] + [70.0 + 5 * i for i in range(7)] + [100.0]
        body = climbprofile.body_of(climb, trip(heights)["trip"])
        assert body is not None
        assert body["m"][0] == 0
        assert len(body["m"]) == len(body["elevation_m"]) == len(body["grade_pct"])
        assert body["avg_grade_pct"] == 5.4
        assert body["length_m"] == 1110
        # 2 m every 30 m is 6.7%; 5 m every 30 m is 16.7%: the steepest is read across four samples.
        assert body["max_grade_pct"] == pytest.approx(16.7, abs=0.1)

    def test_no_heights_is_none(self, climbs_file) -> None:
        climb = climbprofile.find("abc123")
        assert climbprofile.body_of(climb, trip([])["trip"]) is None


class TestTheProfile:
    def test_asked_once_and_kept(self, climbs_file, monkeypatch) -> None:
        calls = []

        def transport(url, payload, timeout):
            calls.append(url)
            return trip([10.0, 12.0, 14.0, 16.0, 18.0])

        monkeypatch.setattr(routing, "_transport", transport)
        climb = climbprofile.find("abc123")
        first = climbprofile.profile(climb)
        again = climbprofile.profile(climb)
        assert first is not None and first == again
        assert len(calls) == 1
        assert calls[0].endswith("/route")

    def test_refused_on_the_standard_router_tries_offroad(self, climbs_file, monkeypatch) -> None:
        calls = []

        def transport(url, payload, timeout):
            calls.append(url)
            if len(calls) == 1:
                raise routing.RouterRefused(400, 442, "no path")
            return trip([10.0, 12.0, 14.0])

        monkeypatch.setattr(routing, "_transport", transport)
        assert climbprofile.profile(climbprofile.find("abc123")) is not None
        assert len(calls) == 2

    def test_a_router_down_is_unavailable_and_not_kept(self, climbs_file, monkeypatch) -> None:
        def dead(url, payload, timeout):
            raise routing.RouterUnavailable("down")

        monkeypatch.setattr(routing, "_transport", dead)
        with pytest.raises(climbprofile.Unavailable):
            climbprofile.profile(climbprofile.find("abc123"))
        assert climbprofile._kept == {}


@db
class TestTheEndpoint:
    def test_a_climbs_profile(self, client, climbs_file, monkeypatch) -> None:
        monkeypatch.setattr(routing, "_transport", lambda *a: trip([10.0, 12.0, 14.0, 17.0, 20.0]))
        response = client.get("/api/climbs/abc123/profile")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "abc123"
        assert body["category"] == "4"
        assert body["elevation_m"][0] == 10.0
        assert "public" in response["Cache-Control"]

    def test_an_unknown_climb_is_404(self, client, climbs_file, monkeypatch) -> None:
        monkeypatch.setattr(routing, "_transport", lambda *a: pytest.fail("no router call"))
        assert client.get("/api/climbs/nope/profile").status_code == 404
        assert client.get("/api/climbs/a-b/profile").status_code == 404

    def test_a_router_down_is_503(self, client, climbs_file, monkeypatch) -> None:
        def dead(url, payload, timeout):
            raise routing.RouterUnavailable("down")

        monkeypatch.setattr(routing, "_transport", dead)
        response = client.get("/api/climbs/abc123/profile")
        assert response.status_code == 503
        assert response["Retry-After"]
