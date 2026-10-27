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
from core.models import AccountSettings, SavedRoute, SavedRouteVersion, Session, User

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

    def test_favorite_ride_types_are_kept(self) -> None:
        client, user, csrf = signed_in()
        doc = {"v": 1, "favorites": ["cargo", "gravel"]}
        r = send(client, "post", "/api/me/settings", {"settings": doc}, csrf)
        assert r.status_code == 200
        assert AccountSettings.objects.get(user=user).data == doc

    def test_the_rider_and_bike_weight_is_kept(self) -> None:
        # The owner, 2026-10-19: "Weight should be retained for signed in users".
        client, user, csrf = signed_in()
        weight = {
            "name": "My weight",
            "totalKg": 93.4,
            "parts": {"riderKg": 78.4, "bikeKg": 15, "cargoKg": 0},
            "setAt": 1760000000000,
        }
        doc = {"v": 1, "weight": weight}
        r = send(client, "post", "/api/me/settings", {"settings": doc}, csrf)
        assert r.status_code == 200
        assert AccountSettings.objects.get(user=user).data == doc
        assert client.get("/api/me/settings").json()["settings"]["weight"] == weight

    def test_a_refused_weight_is_not_echoed(self) -> None:
        client, _user, csrf = signed_in()
        doc = {"v": 1, "weight": {"totalKg": 4321}}
        r = send(client, "post", "/api/me/settings", {"settings": doc}, csrf)
        assert r.status_code == 400
        assert "4321" not in r.content.decode()

    @pytest.mark.parametrize("speed", [18, None])
    def test_the_riding_speed_is_kept(self, speed) -> None:
        # The owner, 2026-10-27: fast riders "override the speed as an advanced feature".
        client, user, csrf = signed_in()
        doc = {"v": 1, "speed": speed}
        r = send(client, "post", "/api/me/settings", {"settings": doc}, csrf)
        assert r.status_code == 200
        assert AccountSettings.objects.get(user=user).data == doc

    @pytest.mark.parametrize("speed", [7, 31, 18.5, "18", True])
    def test_a_riding_speed_off_the_picker_is_refused(self, speed) -> None:
        client, _user, csrf = signed_in()
        r = send(client, "post", "/api/me/settings", {"settings": {"v": 1, "speed": speed}}, csrf)
        assert r.status_code == 400

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
            {"v": 1, "weight": 80},
            {"v": 1, "weight": {"totalKg": 10}},
            {"v": 1, "weight": {"totalKg": 701}},
            {"v": 1, "weight": {"totalKg": True}},
            {"v": 1, "weight": {"totalKg": 80, "parts": {"riderKg": 80}}},
            {"v": 1, "weight": {"totalKg": 80, "name": "x" * 500}},
            {"v": 1, "bikeshare": {"name": "x" * (accounts.SETTINGS_MAX_BYTES + 1)}},
            {"v": 1, "favorites": "cargo"},
            {"v": 1, "favorites": [{"id": "cargo"}]},
            {"v": 1, "favorites": ["cargo", "cargo"]},
            {"v": 1, "favorites": ["cargo"] * (accounts.FAVORITES_MAX + 1)},
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
        refused = send(
            client, "post", "/api/me/routes", route_body(source="gpx", gpx=text, answer=[1]), csrf
        )
        assert refused.status_code == 400

    def test_a_gpx_file_keeps_the_route_shown_for_it(self) -> None:
        # v0.9.0, "share the exact route": saved with the route shown for it, the file reopens
        # as that line (followed exactly here), not followed again.
        client, _user, csrf = signed_in()
        text = '<?xml version="1.0"?>\n<gpx version="1.1"><trk><trkseg/></trk></gpx>\n'
        body = route_body(source="gpx", name="Parade", gpx=text)
        body["answer"] = {**body["answer"], "follows_file": True, "follows_exactly": True}
        r = send(client, "post", "/api/me/routes", body, csrf)
        assert r.status_code == 201
        full = client.get(f"/api/me/routes/{r.json()['id']}", **addr()).json()
        assert full["gpx"] == text and full["answer"]["follows_exactly"] is True

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


# Saved-route versions: a route saved again with changes (`version_of`) keeps what it was, up to
# 20 per route, and the owner lists them and restores one; another account cannot.
MOVED = {
    **INPUTS,
    "points": [[-77.03651, 38.89768], [-77.0300, 38.9000], [-77.02101, 38.90455]],
}


def saved_again(client, csrf, rid: int, **changes):
    return send(client, "post", "/api/me/routes", route_body(version_of=rid, **changes), csrf)


@db
class TestRouteVersions:
    def test_saving_again_with_changes_keeps_the_previous_version(self) -> None:
        client, user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        line = [*LINE, [-77.019, 38.905]]
        r = saved_again(client, csrf, rid, line=line, distance_m=1700.0, inputs=MOVED)
        assert r.status_code == 200 and r.json()["versioned"] is True and r.json()["id"] == rid
        # Still one saved route: a version is not counted toward the 200.
        assert SavedRoute.objects.filter(user=user).count() == 1
        assert client.get(f"/api/me/routes/{rid}", **addr()).json()["line"] == line
        versions = client.get(f"/api/me/routes/{rid}/versions", **addr()).json()
        assert versions["max"] == 20
        listed = versions["versions"]
        assert [v["distance_m"] for v in listed] == [1700.0, 1520.4]
        assert listed[0]["id"] is None and listed[0]["change"] == "Stop added"
        assert listed[1]["change"] == "First saved"
        assert SavedRouteVersion.objects.get(route_id=rid).line == LINE

    def test_saving_again_unchanged_keeps_no_version(self) -> None:
        client, _user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        r = saved_again(client, csrf, rid)
        assert r.status_code == 200 and r.json()["versioned"] is False
        assert not SavedRouteVersion.objects.filter(route_id=rid).exists()

    def test_restoring_makes_a_new_latest_version(self) -> None:
        client, _user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        saved_again(client, csrf, rid, line=LINE[:2], distance_m=900.0, inputs=MOVED)
        first = client.get(f"/api/me/routes/{rid}/versions", **addr()).json()["versions"][1]
        r = send(client, "post", f"/api/me/routes/{rid}/versions/{first['id']}/restore", {}, csrf)
        assert r.status_code == 200
        assert r.json()["line"] == LINE and r.json()["distance_m"] == 1520.4
        listed = client.get(f"/api/me/routes/{rid}/versions", **addr()).json()["versions"]
        # The restored one is the latest; the one it replaced and the original both stay.
        assert [v["distance_m"] for v in listed] == [1520.4, 900.0, 1520.4]
        assert listed[0]["change"] == "Stop removed"

    def test_at_most_20_versions_per_route_the_oldest_going_first(self) -> None:
        client, _user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        for i in range(SavedRouteVersion.MAX_PER_ROUTE + 3):
            assert saved_again(client, csrf, rid, distance_m=2000.0 + i).json()["versioned"]
        kept = SavedRouteVersion.objects.filter(route_id=rid)
        assert kept.count() == SavedRouteVersion.MAX_PER_ROUTE
        assert 1520.4 not in set(kept.values_list("distance_m", flat=True))
        listed = client.get(f"/api/me/routes/{rid}/versions", **addr()).json()["versions"]
        assert len(listed) == SavedRouteVersion.MAX_PER_ROUTE + 1
        assert listed[0]["change"] == "Line changed"
        # Older versions went past the cap, so the oldest kept is not the first save.
        assert listed[-1]["change"] == ""

    def test_the_200_route_cap_is_unchanged_and_saving_again_passes_it(self) -> None:
        client, user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        SavedRoute.objects.bulk_create(
            SavedRoute(user=user, name=f"r{i}", line=LINE, distance_m=1.0, inputs={})
            for i in range(SavedRoute.MAX_PER_ACCOUNT - 1)
        )
        assert send(client, "post", "/api/me/routes", route_body(), csrf).status_code == 409
        assert saved_again(client, csrf, rid, distance_m=99.0).status_code == 200

    def test_another_account_cannot_see_save_over_or_restore_versions(self) -> None:
        owner, _u, csrf = signed_in()
        rid = send(owner, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        saved_again(owner, csrf, rid, distance_m=1700.0, inputs=MOVED)
        vid = SavedRouteVersion.objects.get(route_id=rid).pk
        other, _o, other_csrf = signed_in()
        assert other.get(f"/api/me/routes/{rid}/versions", **addr()).status_code == 404
        r = send(other, "post", f"/api/me/routes/{rid}/versions/{vid}/restore", {}, other_csrf)
        assert r.status_code == 404
        assert saved_again(other, other_csrf, rid, distance_m=5.0).status_code == 404
        # The other account's own route cannot reach the owner's version either.
        mine = send(other, "post", "/api/me/routes", route_body(), other_csrf).json()["id"]
        r = send(other, "post", f"/api/me/routes/{mine}/versions/{vid}/restore", {}, other_csrf)
        assert r.status_code == 404
        assert SavedRoute.objects.get(pk=rid).distance_m == 1700.0

    def test_signed_out_and_without_csrf_is_refused(self, client) -> None:
        assert client.get("/api/me/routes/1/versions", **addr()).status_code == 401
        owner, _u, csrf = signed_in()
        rid = send(owner, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        saved_again(owner, csrf, rid, distance_m=1700.0)
        vid = SavedRouteVersion.objects.get(route_id=rid).pk
        r = send(owner, "post", f"/api/me/routes/{rid}/versions/{vid}/restore", {}, None)
        assert r.status_code == 403

    def test_an_unchanged_file_is_kept_once_and_restored_whole(self) -> None:
        client, _user, csrf = signed_in()
        text = '<?xml version="1.0"?>\n<gpx version="1.1"><trk><trkseg/></trk></gpx>\n'
        other = text.replace("trkseg/", "trkseg></trkseg")
        body = {"source": "gpx", "answer": None, "gpx": text}
        rid = send(client, "post", "/api/me/routes", route_body(**body), csrf).json()["id"]
        # The same file, another plan (a snapped line, say): the version keeps no copy of it.
        saved_again(client, csrf, rid, **body, inputs=MOVED)
        first = SavedRouteVersion.objects.get(route_id=rid)
        assert first.gpx == "" and first.gpx_same_as_next and first.size_bytes > 0
        # Another file: that version keeps its own.
        saved_again(client, csrf, rid, **{**body, "gpx": other}, distance_m=99.0)
        second = SavedRouteVersion.objects.filter(route_id=rid).latest("replaced_at")
        assert second.gpx == text and not second.gpx_same_as_next
        r = send(client, "post", f"/api/me/routes/{rid}/versions/{first.pk}/restore", {}, csrf)
        assert r.status_code == 200 and r.json()["gpx"] == text
        r = send(client, "post", f"/api/me/routes/{rid}/versions/{second.pk}/restore", {}, csrf)
        assert r.json()["gpx"] == text

    def test_an_account_s_versions_are_capped_in_bytes_oldest_first(self, monkeypatch) -> None:
        client, _user, csrf = signed_in()
        a = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        b = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        saved_again(client, csrf, a, distance_m=2000.0)
        size = SavedRouteVersion.objects.get(route_id=a).size_bytes
        monkeypatch.setattr(SavedRouteVersion, "MAX_BYTES_PER_ACCOUNT", size * 2)
        saved_again(client, csrf, b, distance_m=3000.0)
        saved_again(client, csrf, b, distance_m=4000.0)
        # Three versions of the same size past a cap of two: the account's oldest, route a's, went.
        assert not SavedRouteVersion.objects.filter(route_id=a).exists()
        assert SavedRouteVersion.objects.filter(route_id=b).count() == 2

    def test_versions_go_with_the_route(self) -> None:
        client, _user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        saved_again(client, csrf, rid, distance_m=1700.0)
        client.delete(f"/api/me/routes/{rid}", HTTP_X_CSRFTOKEN=csrf, **addr())
        assert not SavedRouteVersion.objects.filter(route_id=rid).exists()


@pytest.mark.parametrize(
    ("older", "newer", "said"),
    [
        ({"preset": "default"}, {"preset": "group-ride"}, "Ride type changed"),
        ({"points": [[0, 0], [1, 1]]}, {"points": [[0, 1], [1, 1]]}, "Start moved"),
        ({"points": [[0, 0], [1, 1]]}, {"points": [[0, 0], [1, 2]]}, "End moved"),
        ({"points": [[0, 0], [5, 5], [1, 1]]}, {"points": [[0, 0], [1, 1]]}, "Stop removed"),
        ({"dials": {"stress": 1}}, {"dials": {"stress": 2}}, "Settings changed"),
        (
            {"preset": "a", "points": [[0, 0], [1, 1]]},
            {"preset": "b", "points": [[0, 0], [2, 2], [3, 3], [1, 1]]},
            "Ride type changed, stops added",
        ),
    ],
)
def test_change_phrase(older, newer, said) -> None:
    a = {"source": "plan", "distance_m": 10.0, "inputs": older}
    b = {"source": "plan", "distance_m": 10.0, "inputs": newer}
    assert accounts.change_phrase(a, b) == said


def test_change_phrase_of_a_source_or_line_change() -> None:
    a = {"source": "plan", "distance_m": 10.0, "inputs": {}}
    assert accounts.change_phrase(a, {**a, "source": "gpx"}) == "From a GPX file"
    assert accounts.change_phrase(a, {**a, "distance_m": 50.0}) == "Line changed"
    assert accounts.change_phrase(a, dict(a)) == "Same plan"
