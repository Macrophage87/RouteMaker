"""The road panel's street photo (core.street_photo), against a saved Mapillary Graph API answer
shaped as Mapillary documents it (tests/data/mapillary). No network: the fetch is a fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import street_photo

DATA = Path(__file__).parent / "data" / "mapillary"
LON, LAT = -77.0300, 38.9000
EAST_WEST = 90.0
SECRET = "MLY|test|0000"


def answer() -> dict:
    return json.loads((DATA / "images.json").read_text())


class Fake:
    def __init__(self, body: bytes | None = None, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.body = body if body is not None else (DATA / "images.json").read_bytes()
        self.fail = fail

    def __call__(self, url: str, headers: dict, _timeout: float) -> bytes:
        self.calls.append((url, headers))
        if self.fail:
            raise street_photo.Unavailable("HTTP 500")
        return self.body


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_newest_photo_near_the_road_facing_along_it_either_way() -> None:
    found = street_photo.choose(answer(), LON, LAT, EAST_WEST)
    # October 2023 facing west: the newer ones face across the road, are a panorama, are 80 m
    # off, or name a host that is not Mapillary's.
    assert found["viewer_url"] == "https://www.mapillary.com/app/?pKey=1002&focus=photo"
    assert found["date_words"] == "Photo from October 2023" and found["captured"] == "2023-10-01"
    assert found["image_url"].startswith("https://scontent-iad3-1.xx.fbcdn.net/")
    assert (found["credit"], found["licence"], found["creator"]) == (
        "Mapillary",
        "CC BY-SA",
        "rider42",
    )
    # A north-south road: the photo facing south is the one.
    assert street_photo.choose(answer(), LON, LAT, 0.0)["viewer_url"].endswith(
        "pKey=1003&focus=photo"
    )
    assert street_photo.choose({"data": []}, LON, LAT, EAST_WEST) is None
    assert street_photo.choose({"data": [{"id": "x"}, None]}, LON, LAT, None) is None


def test_facing_along_is_either_way_within_45_degrees() -> None:
    assert street_photo.facing_along(268.0, 90.0) and street_photo.facing_along(130.0, 90.0)
    assert not street_photo.facing_along(180.0, 90.0)
    assert street_photo.facing_along(180.0, None)
    assert street_photo.facing_along(5.0, 350.0)


def test_with_no_token_nothing_is_asked(settings) -> None:
    settings.MAPILLARY_ACCESS_TOKEN = ""
    fake = Fake()
    assert street_photo.StreetPhoto(fake, bearing=lambda *_: EAST_WEST).photo(LON, LAT, 5) is None
    assert fake.calls == []


def test_the_token_is_in_the_header_only_and_an_answer_is_kept_an_hour(settings) -> None:
    settings.MAPILLARY_ACCESS_TOKEN = SECRET
    fake, clock = Fake(), Clock()
    photos = street_photo.StreetPhoto(fake, clock, bearing=lambda *_: EAST_WEST)
    first = photos.photo(LON, LAT, 5)
    assert first["date_words"] == "Photo from October 2023"
    url, headers = fake.calls[0]
    assert headers["Authorization"] == f"OAuth {SECRET}"
    assert SECRET not in url and "access_token" not in url and "MLY" not in url
    assert url.startswith("https://graph.mapillary.com/images?") and "bbox=" in url
    assert SECRET not in json.dumps(first)
    clock.now += street_photo.CACHE_S - 1
    assert photos.photo(LON, LAT, 5) == first and len(fake.calls) == 1
    clock.now += 2
    photos.photo(LON, LAT, 5)
    assert len(fake.calls) == 2


def test_no_photo_is_said_and_no_answer_is_nothing(settings, caplog) -> None:
    settings.MAPILLARY_ACCESS_TOKEN = SECRET
    none = street_photo.StreetPhoto(Fake(b'{"data": []}'), bearing=lambda *_: None)
    assert none.photo(LON, LAT, 5) == {"found": False, "words": "No street photo here."}
    down = street_photo.StreetPhoto(Fake(fail=True), bearing=lambda *_: None)
    assert down.photo(LON, LAT, 5) is None
    assert SECRET not in caplog.text


@pytest.mark.django_db
class TestApi:
    def test_no_token_is_a_204(self, client) -> None:
        response = client.get("/api/street-photo", {"lon": LON, "lat": LAT, "way": 5})
        assert response.status_code == 204

    def test_a_photo_through_the_api(self, client, settings, monkeypatch) -> None:
        settings.MAPILLARY_ACCESS_TOKEN = SECRET
        monkeypatch.setattr(
            street_photo, "client", street_photo.StreetPhoto(Fake(), bearing=lambda *_: EAST_WEST)
        )
        response = client.get("/api/street-photo", {"lon": LON, "lat": LAT, "way": 5})
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["found"] and body["date_words"] == "Photo from October 2023"
        assert SECRET not in response.content.decode()
        refused = client.get(
            "/api/street-photo", {"lon": LON, "lat": LAT}, HTTP_SEC_FETCH_SITE="cross-site"
        )
        assert refused.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_the_roads_bearing_is_read_from_its_live_segment(segment_schemas) -> None:
    from test_segment_info_api import insert

    live, _staging = segment_schemas
    insert(live, 77, [(LON - 0.001, LAT), (LON + 0.001, LAT)])
    insert(live, 78, [(LON, LAT - 0.001), (LON, LAT + 0.001)])
    east_west = street_photo.road_bearing(77, LON, LAT)
    north_south = street_photo.road_bearing(78, LON, LAT)
    assert east_west == pytest.approx(90.0, abs=1.0)
    assert north_south == pytest.approx(0.0, abs=1.0)
    assert street_photo.road_bearing(79, LON, LAT) is None
