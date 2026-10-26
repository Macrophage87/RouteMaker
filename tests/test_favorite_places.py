"""Favorite places (Stephen 2026-10-26: "For signed in users, allow for favorite destinations"):
GET and POST /api/me/places, the list Go's Favorites chip shows after Home (Work first, once set).

Signed in only, with My Go's guards; kept on the account's My Go row, saved on their own so a My
Go save never clears them, rounded to about a metre, and gone with the account.
"""

from __future__ import annotations

import json
from itertools import count

import pytest
from django.test import Client
from django.utils import timezone

from core.api import FAVORITE_PLACES_MAX
from core.models import MyGo, Session, User

db = pytest.mark.django_db(transaction=True)

URL = "/api/me/places"
_ids = count(93000)
_clients = count(10)


def addr() -> dict:
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_clients) % 250}"}


def signed_in_client() -> tuple[Client, User, str]:
    user = User.objects.create(discord_user_id=next(_ids))
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    now = timezone.now()
    Session.objects.create(
        session_key=client.session.session_key,
        user=user,
        issued_epoch=user.session_epoch,
        created_at=now,
        last_seen_at=now,
    )
    read = client.get(URL, **addr())
    assert read.status_code == 200
    return client, user, client.cookies["csrftoken"].value


def post(client: Client, url: str, payload, csrf: str | None):
    extra = {"HTTP_X_CSRFTOKEN": csrf} if csrf else {}
    return client.post(
        url, data=json.dumps(payload), content_type="application/json", **extra, **addr()
    )


def place(lon: float, lat: float, label: str = "Market", **more) -> dict:
    return {"lon": lon, "lat": lat, "label": label, **more}


@db
class TestFavoritePlaces:
    def test_signed_out_is_401(self, client) -> None:
        assert client.get(URL, **addr()).status_code == 401
        assert post(client, URL, {"places": []}, None).status_code in (401, 403)

    def test_a_new_rider_has_none_and_a_read_makes_no_row(self) -> None:
        client, _user, _csrf = signed_in_client()
        assert client.get(URL, **addr()).json() == {"places": []}
        assert not MyGo.objects.exists()

    def test_the_list_is_saved_in_order_rounded_and_read_back(self) -> None:
        client, user, csrf = signed_in_client()
        r = post(
            client,
            URL,
            {
                "places": [
                    place(-77.0123456, 38.9012345, " Office ", work=True),
                    place(-77.05, 38.91),
                ]
            },
            csrf,
        )
        assert r.status_code == 200, r.content
        want = {
            "places": [
                {"lon": -77.01235, "lat": 38.90123, "label": "Office", "work": True},
                {"lon": -77.05, "lat": 38.91, "label": "Market", "work": False},
            ]
        }
        assert r.json() == want
        assert client.get(URL, **addr()).json() == want
        assert MyGo.objects.get(user=user).places[1] == {
            "lon": -77.05,
            "lat": 38.91,
            "label": "Market",
        }

    def test_a_my_go_save_keeps_the_places_and_a_places_save_keeps_home(self) -> None:
        client, user, csrf = signed_in_client()
        post(client, "/api/me/go", {"home": {"lon": -77.0, "lat": 38.9, "label": "Home"}}, csrf)
        post(client, URL, {"places": [place(-77.05, 38.91)]}, csrf)
        post(
            client,
            "/api/me/go",
            {"open_in": "go", "home": {"lon": -77.0, "lat": 38.9, "label": "Home"}},
            csrf,
        )
        row = MyGo.objects.get(user=user)
        assert len(row.places) == 1
        assert row.home_lon == -77.0 and row.open_in == "go"

    @pytest.mark.parametrize(
        "payload",
        [
            {"places": [place(-77.0, 38.9, work=True), place(-77.1, 38.9, work=True)]},
            {"places": [place(-77.0, 38.9), place(-77.000001, 38.9)]},
            {"places": [place(-90.0, 38.9)]},
            {"places": [place(-77.0, 38.9, label="  ")]},
            {"places": [place(-77.0, 38.9, label="x" * 121)]},
            {"places": [place(-77.0, 38.9, note="extra")]},
            {"places": [place(-77.0 - i / 100, 38.9) for i in range(FAVORITE_PLACES_MAX + 1)]},
            {"places": [{"lon": "-77", "lat": 38.9, "label": "A"}]},
        ],
        ids=[
            "two-works",
            "same-spot",
            "outside",
            "blank-name",
            "long-name",
            "extra-key",
            "too-many",
            "string-lon",
        ],
    )
    def test_a_list_that_does_not_make_sense_is_refused(self, payload) -> None:
        client, _user, csrf = signed_in_client()
        assert post(client, URL, payload, csrf).status_code == 400
        assert client.get(URL, **addr()).json() == {"places": []}

    def test_a_write_needs_the_csrf_token(self) -> None:
        client, _user, _csrf = signed_in_client()
        assert post(client, URL, {"places": [place(-77.0, 38.9)]}, None).status_code == 403

    def test_a_deleted_account_keeps_no_places(self) -> None:
        client, user, csrf = signed_in_client()
        post(client, URL, {"places": [place(-77.0, 38.9)]}, csrf)
        user.is_deleted = True
        user.save()
        assert not MyGo.objects.filter(user=user).exists()
