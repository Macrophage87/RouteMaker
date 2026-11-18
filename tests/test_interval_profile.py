"""GET /api/intervals/{id}/profile: one interval stretch's elevation profile for its hover
card (the owner, 2026-11-18: "Allow a mouseover with elevation profile as well, it should
also give distance and a rough estimate of interval time"). The stretch comes from the
Intervals layer's file and its heights from the router, a stand-in for `_transport` here."""

from __future__ import annotations

import json

import pytest

from core import intervalprofile, intervals_near, routing

db = pytest.mark.django_db(transaction=True)

LINE = [[-77.0, 38.9], [-77.0, 38.903], [-77.0, 38.906], [-77.0, 38.909], [-77.0, 38.912]]
ROW = {"id": "abc123", "l": 1330, "r": 60, "g": 4.5, "t": 4.2, "line": LINE, "n": "Klingle"}


def trip(heights: list[float | None], km: float = 1.33) -> dict:
    return {"trip": {"legs": [{"summary": {"length": km}, "elevation": heights}]}}


@pytest.fixture
def intervals_file(tmp_path, monkeypatch):
    path = tmp_path / "intervals.json"
    path.write_text(json.dumps({"version": 1, "built": "2026-11-18", "intervals": [ROW]}))
    monkeypatch.setattr(intervals_near, "INTERVALS_FILE", path)
    intervals_near._cache.clear()
    intervalprofile._kept.clear()
    yield path
    intervals_near._cache.clear()
    intervalprofile._kept.clear()


class TestTheRequest:
    def test_start_to_end_through_the_stretch_with_heights(self, intervals_file) -> None:
        stretch = intervalprofile.find("abc123")
        assert stretch is not None and stretch.minutes == 4.2
        locations = intervalprofile.request_for(stretch)["locations"]
        assert locations[0] == {"lon": -77.0, "lat": 38.9, "type": "break"}
        assert locations[-1] == {"lon": -77.0, "lat": 38.912, "type": "break"}
        assert len(locations) > 2 and all(loc["type"] == "through" for loc in locations[1:-1])

    def test_an_unknown_id_is_none_and_no_file_is_unavailable(
        self, intervals_file, tmp_path, monkeypatch
    ) -> None:
        assert intervalprofile.find("nope") is None
        monkeypatch.setattr(intervals_near, "INTERVALS_FILE", tmp_path / "none.json")
        with pytest.raises(intervalprofile.Unavailable):
            intervalprofile.find("abc123")


class TestTheProfile:
    def test_asked_once_and_kept(self, intervals_file, monkeypatch) -> None:
        calls = []

        def transport(url, payload, timeout):
            calls.append(url)
            return trip([10.0 + 2 * i for i in range(45)])

        monkeypatch.setattr(routing, "_transport", transport)
        stretch = intervalprofile.find("abc123")
        first = intervalprofile.profile(stretch)
        assert first == intervalprofile.profile(stretch) and len(calls) == 1
        assert first["minutes"] == 4.2 and first["length_m"] == 1330
        assert len(first["m"]) == len(first["elevation_m"]) == len(first["grade_pct"])

    def test_a_router_down_is_unavailable_and_not_kept(self, intervals_file, monkeypatch) -> None:
        def dead(url, payload, timeout):
            raise routing.RouterUnavailable("down")

        monkeypatch.setattr(routing, "_transport", dead)
        with pytest.raises(intervalprofile.Unavailable):
            intervalprofile.profile(intervalprofile.find("abc123"))
        assert intervalprofile._kept == {}


@db
class TestTheEndpoint:
    def test_a_stretch_s_profile(self, client, intervals_file, monkeypatch) -> None:
        monkeypatch.setattr(routing, "_transport", lambda *a: trip([10.0, 12.0, 14.0, 17.0]))
        response = client.get("/api/intervals/abc123/profile")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "abc123" and body["minutes"] == 4.2
        assert body["elevation_m"][0] == 10.0
        assert "public" in response["Cache-Control"]

    def test_an_unknown_stretch_is_404(self, client, intervals_file, monkeypatch) -> None:
        monkeypatch.setattr(routing, "_transport", lambda *a: pytest.fail("no router call"))
        assert client.get("/api/intervals/nope/profile").status_code == 404
        assert client.get("/api/intervals/a-b/profile").status_code == 404
