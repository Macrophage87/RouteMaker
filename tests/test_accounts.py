"""Saved settings and saved routes (v0.7.0 plan, "Discord sign-in on, with saved settings and
routes"): GET and POST /api/me/settings, and /api/me/routes (list, save, read, rename, delete).

The rider's own and nobody else's: signed out is 401, a write needs the CSRF token a read sets,
a saved route keeps its line exactly as sent, there are at most 200 per account, another
account's route is not found, and both go with the account.
"""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone

from core import accounts
from core.models import AccountSettings, SavedRoute, Session, User

db = pytest.mark.django_db(transaction=True)
# A real planner answer (test_route_api's standard route): a kept answer is read as RouteOut.
ANSWER = json.loads((Path(__file__).parent / "data" / "route_answer.json").read_text())

_ids = count(93000)
_clients = count(10)

LINE = [[-77.03651, 38.89768, 12.5], [-77.03012, 38.90011, 14.0], [-77.02101, 38.90455, 16.25]]
INPUTS = {
    "hash": "#p=-77.03651,38.89768;-77.02101,38.90455&preset=default&v=2",
    "points": [[-77.03651, 38.89768], [-77.02101, 38.90455]],
    "preset": "default",
    "dials": {"stress": 70, "hills": 0},
}


def addr() -> dict:
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_clients) % 250}"}


def make_user(**fields) -> User:
    return User.objects.create(discord_user_id=next(_ids), **fields)


def signed_in(user: User | None = None) -> tuple[Client, User, str]:
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
    read = client.get("/api/me/settings", **addr())
    assert read.status_code == 200
    return client, user, client.cookies["csrftoken"].value


def send(client: Client, method: str, url: str, payload, csrf: str | None):
    extra = {"HTTP_X_CSRFTOKEN": csrf} if csrf else {}
    return getattr(client, method)(
        url, data=json.dumps(payload), content_type="application/json", **extra, **addr()
    )


def route_body(**changes) -> dict:
    return {
        "name": "Lincoln Memorial to Logan Circle",
        "source": "plan",
        "line": LINE,
        "distance_m": 1520.4,
        "inputs": INPUTS,
        "answer": {**ANSWER, "distance_m": 1520.4},
        **changes,
    }


@db
class TestSettings:
    def test_signed_out_is_401(self, client) -> None:
        assert client.get("/api/me/settings", **addr()).status_code == 401
        r = client.post("/api/me/settings", data="{}", content_type="application/json", **addr())
        assert r.status_code in (401, 403)

    def test_an_empty_account_has_none_and_a_save_is_read_back(self) -> None:
        client, user, csrf = signed_in()
        assert client.get("/api/me/settings", **addr()).json()["settings"] is None
        doc = {"v": 1, "plan": "#preset=group-ride&v=2&s=80", "topo": True, "climbs": False}
        r = send(client, "post", "/api/me/settings", {"settings": doc}, csrf)
        assert r.status_code == 200 and r.json()["settings"] == doc
        assert r["Cache-Control"] == "no-store"
        assert AccountSettings.objects.get(user=user).data == doc

    def test_last_write_wins(self) -> None:
        client, user, csrf = signed_in()
        send(client, "post", "/api/me/settings", {"settings": {"v": 1, "topo": True}}, csrf)
        send(client, "post", "/api/me/settings", {"settings": {"v": 1, "topo": False}}, csrf)
        assert AccountSettings.objects.get(user=user).data == {"v": 1, "topo": False}
        assert AccountSettings.objects.filter(user=user).count() == 1

    def test_a_write_needs_the_csrf_token(self) -> None:
        client, _user, _csrf = signed_in()
        r = send(client, "post", "/api/me/settings", {"settings": {"v": 1}}, None)
        assert r.status_code == 403

    @pytest.mark.parametrize(
        "doc",
        [
            [],
            {"home": {"lon": -77.0, "lat": 38.9}},
            {"v": 1, "plan": "#p=-77.0,38.9;-77.1,38.8&preset=default"},
            {"v": 1, "sections": {"a": {"b": {"c": {"d": 1}}}}},
            {"v": 1, "weight": {"total_kg": 80}},
            {"v": 1, "bikeshare": {"name": "x" * (accounts.SETTINGS_MAX_BYTES + 1)}},
        ],
    )
    def test_only_the_planner_s_own_settings_are_kept(self, doc) -> None:
        client, user, csrf = signed_in()
        r = send(client, "post", "/api/me/settings", {"settings": doc}, csrf)
        assert r.status_code == 400
        assert not AccountSettings.objects.filter(user=user).exists()


@db
class TestRoutes:
    def test_signed_out_is_401(self, client) -> None:
        assert client.get("/api/me/routes", **addr()).status_code == 401
        assert client.get("/api/me/routes/1", **addr()).status_code == 401

    def test_a_route_is_kept_verbatim_and_read_back(self) -> None:
        client, user, csrf = signed_in()
        r = send(client, "post", "/api/me/routes", route_body(), csrf)
        assert r.status_code == 201
        rid = r.json()["id"]
        listed = client.get("/api/me/routes", **addr()).json()
        assert listed["max"] == 200
        assert [x["name"] for x in listed["routes"]] == ["Lincoln Memorial to Logan Circle"]
        assert "line" not in listed["routes"][0]
        full = client.get(f"/api/me/routes/{rid}", **addr()).json()
        # The exact line, elevations and all: nothing is rounded or re-planned.
        assert full["line"] == LINE
        assert full["inputs"] == INPUTS
        assert full["answer"]["distance_m"] == 1520.4
        assert full["preset"] == "default"

    def test_a_gpx_line_is_kept_verbatim_without_an_answer(self) -> None:
        client, _user, csrf = signed_in()
        # A GPX track may run outside the map's area in part; it is kept as the file had it.
        line = [[-80.5, 40.0], *LINE]
        text = '<?xml version="1.0"?>\n<gpx version="1.1"><trk><trkseg/></trk></gpx>\n'
        body = route_body(source="gpx", line=line, answer=None, name="Mass Ride", gpx=text)
        r = send(client, "post", "/api/me/routes", body, csrf)
        assert r.status_code == 201
        full = client.get(f"/api/me/routes/{r.json()['id']}", **addr()).json()
        assert full["line"] == line and full["source"] == "gpx" and full["answer"] is None
        # The file's own text, byte for byte, for a verbatim export.
        assert full["gpx"] == text
        refused = send(client, "post", "/api/me/routes", route_body(source="gpx"), csrf)
        assert refused.status_code == 400

    @pytest.mark.parametrize(
        "changes",
        [
            {"name": ""},
            {"name": "x" * 121},
            {"line": [[-77.0, 38.9]]},
            {"line": [[-80.5, 40.0], [-80.6, 40.1]]},
            {"line": [[-77.0, "38.9"], [-77.1, 38.8]]},
            {"distance_m": 0},
            {"inputs": {"points": [[-77.0, 38.9]] * 26}},
            {"inputs": {"secret": 1}},
            {"source": "strava"},
        ],
    )
    def test_a_bad_save_is_refused(self, changes) -> None:
        client, user, csrf = signed_in()
        r = send(client, "post", "/api/me/routes", route_body(**changes), csrf)
        assert r.status_code == 400 and r.json()["error"]
        assert not SavedRoute.objects.filter(user=user).exists()

    def test_at_most_200_per_account(self) -> None:
        client, user, csrf = signed_in()
        SavedRoute.objects.bulk_create(
            SavedRoute(user=user, name=f"r{i}", line=LINE, distance_m=1.0, inputs={})
            for i in range(SavedRoute.MAX_PER_ACCOUNT)
        )
        r = send(client, "post", "/api/me/routes", route_body(), csrf)
        assert r.status_code == 409 and r.json()["code"] == "full"
        assert "200" in r.json()["error"]
        assert SavedRoute.objects.filter(user=user).count() == SavedRoute.MAX_PER_ACCOUNT

    def test_rename_and_delete(self) -> None:
        client, user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        r = send(client, "patch", f"/api/me/routes/{rid}", {"name": "  Commute  "}, csrf)
        assert r.status_code == 200 and r.json()["name"] == "Commute"
        assert SavedRoute.objects.get(pk=rid).line == LINE
        r = client.delete(f"/api/me/routes/{rid}", HTTP_X_CSRFTOKEN=csrf, **addr())
        assert r.status_code == 200
        assert not SavedRoute.objects.filter(user=user).exists()

    def test_another_account_s_route_is_not_found(self) -> None:
        owner, _u, csrf = signed_in()
        rid = send(owner, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        other, _o, other_csrf = signed_in()
        assert other.get(f"/api/me/routes/{rid}", **addr()).status_code == 404
        assert (
            send(other, "patch", f"/api/me/routes/{rid}", {"name": "x"}, other_csrf).status_code
            == 404
        )
        r = other.delete(f"/api/me/routes/{rid}", HTTP_X_CSRFTOKEN=other_csrf, **addr())
        assert r.status_code == 404
        assert other.get("/api/me/routes", **addr()).json()["routes"] == []
        assert SavedRoute.objects.filter(pk=rid).exists()


@db
def test_settings_and_routes_go_with_the_account() -> None:
    client, user, csrf = signed_in()
    send(client, "post", "/api/me/settings", {"settings": {"v": 1, "topo": True}}, csrf)
    send(client, "post", "/api/me/routes", route_body(), csrf)
    user.is_deleted = True
    user.save()
    assert not AccountSettings.objects.filter(user=user).exists()
    assert not SavedRoute.objects.filter(user=user).exists()
