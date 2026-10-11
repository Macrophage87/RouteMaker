"""My Go (UI-CLEANUP, the owner's choice 2 of 2026-10-11): GET and POST /api/me/go, a signed-in
rider's own settings: the view the app opens in, the ride type Go uses, and Home
(core.models.MyGo).

Signed out is 401 (the front end keeps the same choices in the browser); a write needs the CSRF
token the read sets, a JSON body and a same-site request; Home is inside the map's area, rounded
to about a metre, and goes with the account.
"""

from __future__ import annotations

import json
from itertools import count

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

from core.models import MyGo, Session, User

db = pytest.mark.django_db(transaction=True)

URL = "/api/me/go"
_ids = count(91000)
_clients = count(10)


def addr() -> dict:
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_clients) % 250}"}


def make_user(**fields) -> User:
    return User.objects.create(discord_user_id=next(_ids), **fields)


def signed_in_client(user: User | None = None) -> tuple[Client, User, str]:
    user = user or make_user()
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


def save(client: Client, payload, csrf: str | None, **headers):
    extra = {"HTTP_X_CSRFTOKEN": csrf} if csrf else {}
    return client.post(
        URL, data=json.dumps(payload), content_type="application/json", **extra, **addr(), **headers
    )


@db
class TestRead:
    def test_signed_out_is_401_and_says_why(self, client) -> None:
        r = client.get(URL, **addr())
        assert r.status_code == 401
        assert r.json()["code"] == "signed_out"
        assert "Sign in" in r.json()["error"]

    def test_a_new_rider_has_the_defaults_and_gets_the_csrf_cookie(self) -> None:
        user = make_user()
        client = Client()
        client.force_login(user)
        now = timezone.now()
        Session.objects.create(
            session_key=client.session.session_key,
            user=user,
            issued_epoch=user.session_epoch,
            created_at=now,
            last_seen_at=now,
        )
        r = client.get(URL, **addr())
        assert r.status_code == 200
        assert r.json() == {"open_in": "", "ride": "", "home": None}
        assert "csrftoken" in r.cookies
        assert r["Cache-Control"] == "no-store" or "private" in r["Cache-Control"]
        assert not MyGo.objects.exists(), "a read makes no row"

    def test_a_cross_site_read_is_refused(self) -> None:
        client, _user, _csrf = signed_in_client()
        r = client.get(URL, HTTP_SEC_FETCH_SITE="cross-site", **addr())
        assert r.status_code == 403

    def test_a_banned_rider_is_signed_out(self) -> None:
        client, user, _csrf = signed_in_client()
        user.is_banned = True
        user.save()
        assert client.get(URL, **addr()).status_code == 401


@db
class TestSave:
    def test_the_whole_of_my_go_is_saved_and_read_back(self) -> None:
        client, user, csrf = signed_in_client()
        payload = {
            "open_in": "go",
            "ride": "cargo",
            "home": {"lon": -77.0365432, "lat": 38.8976789, "label": " Home "},
        }
        r = save(client, payload, csrf)
        assert r.status_code == 200, r.content
        assert r.json() == {
            "open_in": "go",
            "ride": "cargo",
            "home": {"lon": -77.03654, "lat": 38.89768, "label": "Home"},
        }
        row = MyGo.objects.get(user=user)
        assert (row.home_lon, row.home_lat) == (-77.03654, 38.89768), "rounded to about a metre"
        assert client.get(URL, **addr()).json() == r.json()

    def test_what_is_left_out_is_cleared(self) -> None:
        client, user, csrf = signed_in_client()
        save(client, {"open_in": "plan", "ride": "kids", "home": {"lon": -77.0, "lat": 38.9}}, csrf)
        r = save(client, {"open_in": "go"}, csrf)
        assert r.json() == {"open_in": "go", "ride": "", "home": None}
        assert MyGo.objects.filter(user=user).count() == 1

    def test_without_the_csrf_token_nothing_is_saved(self) -> None:
        client, user, _csrf = signed_in_client()
        r = save(client, {"open_in": "go"}, None)
        assert r.status_code == 403
        assert not MyGo.objects.filter(user=user).exists()

    def test_signed_out_is_401(self) -> None:
        client = Client()
        r = save(client, {"open_in": "go"}, None)
        assert r.status_code in (401, 403)
        assert not MyGo.objects.exists()

    def test_a_cross_site_write_is_refused(self) -> None:
        client, user, csrf = signed_in_client()
        r = save(client, {"open_in": "go"}, csrf, HTTP_SEC_FETCH_SITE="cross-site")
        assert r.status_code == 403
        assert not MyGo.objects.filter(user=user).exists()

    @pytest.mark.parametrize(
        "payload",
        [
            {"open_in": "sideways"},
            {"ride": "unicycle"},
            {"ride": "x" * 40},
            {"home": {"lon": 2.35, "lat": 48.85}},  # outside the map's area
            {"home": {"lon": "-77.0", "lat": 38.9}},  # a string, not a number
            {"home": {"lon": -77.0}},
            {"home": {"lon": -77.0, "lat": 38.9, "label": "x" * 121}},
            {"open_in": "go", "user": 1},  # nothing but My Go
            {"home": {"lon": -77.0, "lat": 38.9, "extra": True}},
        ],
    )
    def test_anything_else_is_400_and_saves_nothing(self, payload) -> None:
        client, user, csrf = signed_in_client()
        r = save(client, payload, csrf)
        assert r.status_code == 400, (payload, r.status_code, r.content)
        assert not MyGo.objects.filter(user=user).exists()

    def test_a_form_body_is_refused(self) -> None:
        client, user, csrf = signed_in_client()
        r = client.post(URL, data={"open_in": "go"}, HTTP_X_CSRFTOKEN=csrf, **addr())
        assert r.status_code in (400, 415)
        assert not MyGo.objects.filter(user=user).exists()

    def test_each_rider_has_their_own(self) -> None:
        a, user_a, csrf_a = signed_in_client()
        b, user_b, csrf_b = signed_in_client()
        save(a, {"open_in": "go", "ride": "cargo"}, csrf_a)
        save(b, {"open_in": "plan"}, csrf_b)
        assert a.get(URL, **addr()).json()["ride"] == "cargo"
        assert b.get(URL, **addr()).json() == {"open_in": "plan", "ride": "", "home": None}


@db
class TestTheRow:
    def test_home_is_both_numbers_or_neither(self) -> None:
        user = make_user()
        with pytest.raises(IntegrityError), transaction.atomic():
            MyGo.objects.create(user=user, home_lat=38.9, home_lon=None)

    def test_a_deleted_account_keeps_no_my_go(self) -> None:
        client, user, csrf = signed_in_client()
        save(client, {"open_in": "go", "home": {"lon": -77.0, "lat": 38.9, "label": "Home"}}, csrf)
        assert MyGo.objects.filter(user=user).exists()
        user.is_deleted = True
        user.save()
        assert not MyGo.objects.filter(user=user).exists()

    def test_the_row_goes_with_the_account(self) -> None:
        client, user, csrf = signed_in_client()
        save(client, {"open_in": "go"}, csrf)
        user.delete()
        assert not MyGo.objects.exists()
