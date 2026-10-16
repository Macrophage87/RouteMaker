"""A shared link's owner turns it off or makes a new one (core.shared_routes revoke, regenerate;
/api/me/shared-routes), and a shared link's preview for the apps that fetch it (core.share_preview:
GET /s/{id} and /s/{id}/preview.png).

Only the owner: signed out is 401, a write needs the CSRF token, another account's link is not
found and stays working. A turned-off link answers 410 with one plain line and no preview. The
preview's words never carry the route's name; its image hides Home when the route starts, ends or
stops there, and draws a route that only passes it in full.
"""

from __future__ import annotations

import json
import math
import secrets
import struct
import zlib
from itertools import count

import pytest
from django.test import Client
from django.utils import timezone

from core import share_preview, shared_routes
from core.models import MyGo, Session, SharedRoute, User

db = pytest.mark.django_db(transaction=True)

_ids = count(97000)
_clients = count(10)
CRAWLER = {"HTTP_USER_AGENT": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discord.com)"}
BROWSER = {
    "HTTP_USER_AGENT": "Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0 Safari/537.36",
    "HTTP_SEC_FETCH_MODE": "navigate",
}

# Home at the start; the route runs about 3 km north from it.
HOME = (-77.03651, 38.89768)
LINE = [[HOME[0], HOME[1] + i * 0.0003, 10.0 + i * 0.5] for i in range(100)]
INPUTS = {
    "hash": f"#p={HOME[0]},{HOME[1]};{LINE[-1][0]},{LINE[-1][1]}&preset=group-ride&v=2",
    "points": [list(HOME), LINE[-1][:2]],
    "preset": "group-ride",
    "dials": {"stress": 70, "hills": 0},
}


def addr() -> dict:
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_clients) % 250}"}


def make_user() -> User:
    return User.objects.create(discord_user_id=next(_ids))


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
    assert client.get("/api/me/shared-routes", **addr()).status_code == 200
    return client, user, client.cookies["csrftoken"].value


def share(client: Client, **changes) -> str:
    body = {
        "id": secrets.token_hex(16),
        "name": "Home to the office",
        "source": "gpx",
        "line": LINE,
        "distance_m": 3340.0,
        "inputs": INPUTS,
        "gpx": "<gpx/>",
        **changes,
    }
    r = client.post(
        "/api/shared-routes", data=json.dumps(body), content_type="application/json", **addr()
    )
    assert r.status_code == 201, r.content
    return body["id"]


def post(client: Client, url: str, csrf: str | None):
    extra = {"HTTP_X_CSRFTOKEN": csrf} if csrf else {}
    return client.post(url, data="{}", content_type="application/json", **extra, **addr())


@db
class TestRevokeAndRegenerate:
    def test_signed_in_share_is_listed_for_its_owner_with_its_link(self) -> None:
        client, user, _ = signed_in()
        rid = share(client)
        assert SharedRoute.objects.get(pk=rid).owner == user
        links = client.get("/api/me/shared-routes", **addr()).json()["links"]
        assert [x["id"] for x in links] == [rid]
        assert links[0]["link"].endswith(f"/s/{rid}#{INPUTS['hash'][1:]}&route={rid}")

    def test_signed_out_share_has_no_owner(self) -> None:
        rid = share(Client())
        assert SharedRoute.objects.get(pk=rid).owner is None

    def test_revoke_turns_the_link_off_and_says_so_plainly(self) -> None:
        client, _, csrf = signed_in()
        rid = share(client)
        assert post(client, f"/api/me/shared-routes/{rid}/revoke", csrf).status_code == 200
        r = Client().get(f"/api/shared-routes/{rid}", **addr())
        assert r.status_code == 410
        assert r.json()["error"] == "This link was turned off by its owner."
        assert r.json()["code"] == "revoked"
        row = SharedRoute.objects.get(pk=rid)
        assert row.line == [] and row.inputs == {} and row.gpx == "" and row.name == ""
        assert client.get("/api/me/shared-routes", **addr()).json()["links"] == []
        # A tombstone is never pruned, so the link keeps saying it was turned off.
        shared_routes.prune(timezone.now() + shared_routes.KEEP * 3)
        assert SharedRoute.objects.filter(pk=rid).exists()

    def test_regenerate_makes_a_new_link_for_the_same_route_and_turns_the_old_off(self) -> None:
        client, user, csrf = signed_in()
        rid = share(client, keep="forever")
        r = post(client, f"/api/me/shared-routes/{rid}/regenerate", csrf)
        assert r.status_code == 201
        new = r.json()
        assert new["id"] != rid and shared_routes.id_ok(new["id"])
        assert new["link"].endswith(f"/s/{new['id']}#{INPUTS['hash'][1:]}&route={new['id']}")
        fresh = SharedRoute.objects.get(pk=new["id"])
        assert fresh.line == LINE and fresh.keep == "forever" and fresh.owner == user
        assert Client().get(f"/api/shared-routes/{rid}", **addr()).status_code == 410
        assert Client().get(f"/api/shared-routes/{new['id']}", **addr()).status_code == 200

    def test_another_account_cannot_revoke_or_regenerate(self) -> None:
        owner, _, _ = signed_in()
        rid = share(owner)
        other, _, csrf = signed_in()
        assert post(other, f"/api/me/shared-routes/{rid}/revoke", csrf).status_code == 404
        assert post(other, f"/api/me/shared-routes/{rid}/regenerate", csrf).status_code == 404
        assert other.get("/api/me/shared-routes", **addr()).json()["links"] == []
        assert Client().get(f"/api/shared-routes/{rid}", **addr()).status_code == 200

    def test_signed_out_is_401_and_a_write_needs_the_csrf_token(self) -> None:
        client, _, _ = signed_in()
        rid = share(client)
        anon = Client(enforce_csrf_checks=True)
        assert anon.get("/api/me/shared-routes", **addr()).status_code == 401
        assert post(anon, f"/api/me/shared-routes/{rid}/revoke", None).status_code in (401, 403)
        assert post(client, f"/api/me/shared-routes/{rid}/revoke", None).status_code == 403
        assert SharedRoute.objects.get(pk=rid).revoked_at is None

    def test_a_signed_out_link_cannot_be_revoked_by_anyone(self) -> None:
        rid = share(Client())
        client, _, csrf = signed_in()
        assert post(client, f"/api/me/shared-routes/{rid}/revoke", csrf).status_code == 404


def png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


def png_pixels(png: bytes) -> tuple[int, int, bytes]:
    width, height = png_size(png)
    data, at = b"", 8
    while at < len(png):
        (length,) = struct.unpack(">I", png[at : at + 4])
        if png[at + 4 : at + 8] == b"IDAT":
            data += png[at + 8 : at + 8 + length]
        at += 12 + length
    raw = zlib.decompress(data)
    rows = [raw[y * (width * 3 + 1) + 1 : (y + 1) * (width * 3 + 1)] for y in range(height)]
    return width, height, b"".join(rows)


@db
class TestPreview:
    def set_home(self, user: User, home=HOME) -> None:
        MyGo.objects.update_or_create(
            user=user, defaults={"home_lon": home[0], "home_lat": home[1], "home_label": "Elm St"}
        )

    def test_a_browser_goes_on_to_the_page(self) -> None:
        rid = share(Client())
        r = Client().get(f"/s/{rid}", **BROWSER, **addr())
        assert r.status_code == 302 and r["Location"] == f"/?route={rid}"

    def test_a_fetcher_gets_the_title_description_and_image_without_names(self) -> None:
        client, user, _ = signed_in()
        self.set_home(user)
        rid = share(client, source="plan", gpx="", answer=None)
        r = Client().get(f"/s/{rid}", **CRAWLER, **addr())
        assert r.status_code == 200
        page = r.content.decode()
        assert '<meta property="og:title" content="Group Ride, 2.1 mi (3.3 km)">' in page
        climb = share_preview.climb_of(SharedRoute.objects.get(pk=rid))
        assert climb == pytest.approx(48.0)
        assert (
            '<meta property="og:description" content="2.1 mi (3.3 km) with 157 ft (48 m) of'
            ' climbing. Planned with RouteMaker.">'
        ) in page
        assert 'property="og:image" content="http://testserver/s/' in page
        assert "summary_large_image" in page
        for word in ("Home", "office", "Elm"):
            assert word not in page

    def test_words(self) -> None:
        row = SharedRoute(source="plan", distance_m=120.0, inputs={"preset": "default"}, line=[])
        assert share_preview.title(row) == "Bike ride, 390 ft (120 m)"
        assert share_preview.description(row) == "390 ft (120 m). Planned with RouteMaker."
        row = SharedRoute(
            source="plan",
            distance_m=20000.0,
            inputs={"preset": "ebike"},
            answer={"climb_m": 376.0},
            line=[],
        )
        assert share_preview.title(row) == "E-bike, 12.4 mi (20.0 km)"
        assert share_preview.stats_line(row) == "12.4 mi (20.0 km) · 1,234 ft (376 m) climb"

    def test_the_image_is_1200_by_630_and_cached(self) -> None:
        rid = share(Client())
        r = Client().get(f"/s/{rid}/preview.png", **CRAWLER, **addr())
        assert r.status_code == 200 and r["Content-Type"] == "image/png"
        assert png_size(r.content) == (1200, 630)
        row = SharedRoute.objects.get(pk=rid)
        assert bytes(row.preview_png) == r.content and row.preview_key

    def test_home_is_cut_when_the_route_starts_there(self) -> None:
        user = make_user()
        self.set_home(user)
        zone = share_preview.home_zone(HOME, share_preview.zone_jitter(user.pk))
        centre, radius = zone
        shift = share_preview._haversine(HOME, centre)
        assert 60 <= shift <= 150 and radius >= 322 + shift
        drawn = share_preview.drawn_route(LINE, INPUTS["points"], zone)
        assert drawn["start"] is None and drawn["finish"] is not None
        for piece in drawn["pieces"]:
            for p in piece:
                assert share_preview._haversine(HOME, p) >= 322 - 0.5
        # A route that only passes Home is drawn whole.
        passing = [[HOME[0] - 0.02 + i * 0.0004, HOME[1]] for i in range(100)]
        whole = share_preview.drawn_route(passing, [passing[0], passing[-1]], zone)
        assert len(whole["pieces"]) == 1 and len(whole["pieces"][0]) == len(passing)
        assert whole["start"] is not None and whole["finish"] is not None

    def test_the_circle_moves_per_account_and_not_with_the_row(self) -> None:
        assert share_preview.zone_jitter(1) == share_preview.zone_jitter(1)
        assert share_preview.zone_jitter(1) != share_preview.zone_jitter(2)

    def test_the_drawn_image_leaves_home_blank(self) -> None:
        client, user, _ = signed_in()
        self.set_home(user)
        rid = share(client)
        png = Client().get(f"/s/{rid}/preview.png", **CRAWLER, **addr()).content
        width, height, px = png_pixels(png)
        # The line and the finish's pin are drawn; the start's pin, at Home, is not.

        def count(colour) -> int:
            return sum(
                1
                for i in range(0, share_preview.MAP_H * width * 3, 3)
                if sum(abs(px[i + k] - colour[k]) for k in range(3)) < 30
            )

        assert count(share_preview.LINE_COLOUR) > 1000
        assert count(share_preview.FINISH_COLOUR) > 100
        assert count(share_preview.START_COLOUR) == 0
        # And a new Home draws it again.
        key = SharedRoute.objects.get(pk=rid).preview_key
        self.set_home(user, (HOME[0] + 0.01, HOME[1]))
        Client().get(f"/s/{rid}/preview.png", **CRAWLER, **addr())
        assert SharedRoute.objects.get(pk=rid).preview_key != key

    def test_a_signed_out_route_from_home_on_the_device_has_no_image(self) -> None:
        rid = share(Client(), preview_image=False)
        page = Client().get(f"/s/{rid}", **CRAWLER, **addr()).content.decode()
        assert "og:title" in page and "og:image" not in page
        assert Client().get(f"/s/{rid}/preview.png", **CRAWLER, **addr()).status_code == 404

    def test_a_revoked_link_has_no_preview(self) -> None:
        client, _, csrf = signed_in()
        rid = share(client)
        Client().get(f"/s/{rid}/preview.png", **CRAWLER, **addr())
        post(client, f"/api/me/shared-routes/{rid}/revoke", csrf)
        r = Client().get(f"/s/{rid}", **CRAWLER, **addr())
        assert r.status_code == 410
        assert "og:" not in r.content.decode()
        assert "turned off by its owner" in r.content.decode()
        assert Client().get(f"/s/{rid}/preview.png", **CRAWLER, **addr()).status_code == 410
        assert SharedRoute.objects.get(pk=rid).preview_png is None

    def test_an_expired_or_unknown_link_has_no_preview(self) -> None:
        rid = share(Client())
        SharedRoute.objects.filter(pk=rid).update(
            last_opened_at=timezone.now() - shared_routes.KEEP * 2
        )
        r = Client().get(f"/s/{rid}", **CRAWLER, **addr())
        assert r.status_code == 404 and "og:" not in r.content.decode()
        assert Client().get(f"/s/{'0' * 32}", **CRAWLER, **addr()).status_code == 404
        assert Client().get("/s/nonsense/preview.png", **CRAWLER, **addr()).status_code == 404

    def test_no_hostname_is_written_into_the_page(self) -> None:
        rid = share(Client())
        r = Client().get(f"/s/{rid}", HTTP_HOST="localhost", **CRAWLER, **addr())
        assert f"http://localhost/s/{rid}" in r.content.decode()

    def test_too_little_left_after_cutting_home_draws_nothing(self) -> None:
        short = [[HOME[0], HOME[1] + i * 0.0003] for i in range(5)]
        zone = share_preview.home_zone(HOME, (0.0, 0.0))
        assert share_preview.drawn_route(short, [short[0], short[-1]], zone) is None
        assert math.isclose(share_preview.HOME_TRIM_M, 322.0)
