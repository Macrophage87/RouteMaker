"""The site's own MCP connector (core.connector; the owner, 2026-10-19: "Build it, v0.10.0"): an
assistant app registers, the rider allows it on the site's page, the app trades the code for
tokens, and /mcp plans routes and adds them to that rider's My routes, and does nothing else."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse

import pytest
from django.test import Client
from test_accounts import addr, make_user, send, signed_in
from test_mcp_server import encode_polyline, straight_answer
from test_route_api import VERTICES, router, segments, standard_router

from core import connector
from core.models import (
    AuditLogEntry,
    ConnectorClient,
    ConnectorDraft,
    ConnectorGrant,
    MyGo,
    RoutePost,
    SavedRoute,
    SharedRoute,
)

db = pytest.mark.django_db(transaction=True)

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
# The route API's planner stand-in, used by name below.
FIXTURES = (router, segments)


def register(redirect=REDIRECT, **extra):
    return Client().post(
        "/oauth/register",
        data=json.dumps({"client_name": "Claude", "redirect_uris": [redirect], **extra}),
        content_type="application/json",
        **addr(),
    )


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def authorize_params(client_id, challenge, **changes) -> dict:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st4te",
        "scope": "routes",
        **changes,
    }


def allow(user=None, answer="allow"):
    """Register, sign in, open the consent page and answer it: (rider's client, user, the
    redirect's query, the client id, the verifier)."""
    client_id = register().json()["client_id"]
    verifier, challenge = pkce()
    browser, user, csrf = signed_in(user)
    params = authorize_params(client_id, challenge)
    page = browser.get("/oauth/authorize", params, **addr())
    assert page.status_code == 200, page.content
    answered = browser.post(
        "/oauth/authorize",
        {**params, "answer": answer, "csrfmiddlewaretoken": csrf},
        HTTP_X_CSRFTOKEN=csrf,
        **addr(),
    )
    assert answered.status_code == 302, answered.content
    location = urllib.parse.urlsplit(answered["Location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == REDIRECT
    return browser, user, dict(urllib.parse.parse_qsl(location.query)), client_id, verifier


def a_grant(user) -> ConnectorGrant:
    """A grant made directly, for the draft store's own tests."""
    app = ConnectorClient.objects.create(
        client_id=f"rmc_{secrets.token_hex(4)}", name="x", redirect_uris=[REDIRECT]
    )
    return ConnectorGrant.objects.create(
        user=user, client=app, redirect_uri=REDIRECT, code_challenge="x"
    )


def trade(**form):
    return Client().post("/oauth/token", form, **addr())


def tokens_for(user=None):
    _browser, user, query, client_id, verifier = allow(user)
    r = trade(
        grant_type="authorization_code",
        code=query["code"],
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=verifier,
    )
    assert r.status_code == 200, r.content
    return user, r.json(), client_id


def mcp(token, method, params=None, msg_id=1):
    message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if msg_id is not None:
        message["id"] = msg_id
    extra = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return Client().post(
        "/mcp", data=json.dumps(message), content_type="application/json", **extra, **addr()
    )


def call(token, name, arguments):
    r = mcp(token, "tools/call", {"name": name, "arguments": arguments})
    assert r.status_code == 200, r.content
    return r.json()["result"]


@pytest.fixture
def planner(monkeypatch):
    """The planner stands in for Valhalla: a straight line through the points."""
    sent = []

    def route(self, body):
        sent.append(body)
        return straight_answer(body)

    monkeypatch.setattr(connector.InProcessApi, "route", route)
    return sent


@db
class TestSignIn:
    def test_discovery_names_the_endpoints(self) -> None:
        resource = Client().get("/.well-known/oauth-protected-resource", **addr()).json()
        assert resource["resource"].endswith("/mcp")
        server = Client().get("/.well-known/oauth-authorization-server", **addr()).json()
        assert server["authorization_endpoint"].endswith("/oauth/authorize")
        assert server["code_challenge_methods_supported"] == ["S256"]
        assert server["registration_endpoint"].endswith("/oauth/register")

    def test_registration_takes_https_or_localhost_only(self) -> None:
        assert register().status_code == 201
        assert register("http://localhost:33418/callback").status_code == 201
        assert register("http://evil.example/cb").status_code == 400
        assert register("javascript:alert(1)").status_code == 400
        assert register("https://user:pw@claude.ai/cb").status_code == 400

    def test_signed_out_goes_to_the_site_s_sign_in_and_back(self) -> None:
        client_id = register().json()["client_id"]
        _verifier, challenge = pkce()
        r = Client().get("/oauth/authorize", authorize_params(client_id, challenge), **addr())
        assert r.status_code == 302
        target = urllib.parse.urlsplit(r["Location"])
        assert target.path == "/auth/login"
        back = urllib.parse.parse_qs(target.query)["next"][0]
        assert back.startswith("/oauth/authorize?") and client_id in back

    def test_the_page_says_what_it_allows_and_cannot_be_framed(self) -> None:
        client_id = register().json()["client_id"]
        _verifier, challenge = pkce()
        browser, _user, _csrf = signed_in()
        page = browser.get("/oauth/authorize", authorize_params(client_id, challenge), **addr())
        text = page.content.decode()
        assert "Allow Claude to plan routes?" in text and "add routes to your My routes" in text
        assert "can't read your saved routes" in text and "claude.ai" in text
        assert "frame-ancestors 'none'" in page["Content-Security-Policy"]
        assert "form-action 'self' https://claude.ai" in page["Content-Security-Policy"]

    def test_an_unregistered_return_address_is_never_sent_anything(self) -> None:
        client_id = register().json()["client_id"]
        _verifier, challenge = pkce()
        browser, _user, _csrf = signed_in()
        params = authorize_params(client_id, challenge, redirect_uri="https://evil.example/cb")
        r = browser.get("/oauth/authorize", params, **addr())
        assert r.status_code == 400 and "Location" not in r

    def test_pkce_is_required(self) -> None:
        client_id = register().json()["client_id"]
        browser, _user, _csrf = signed_in()
        params = authorize_params(client_id, "x" * 43, code_challenge_method="plain")
        r = browser.get("/oauth/authorize", params, **addr())
        assert r.status_code == 400 and "Location" not in r and b"PKCE" in r.content

    def test_the_consent_needs_the_csrf_token(self) -> None:
        client_id = register().json()["client_id"]
        _verifier, challenge = pkce()
        browser, user, _csrf = signed_in()
        params = authorize_params(client_id, challenge)
        r = browser.post("/oauth/authorize", {**params, "answer": "allow"}, **addr())
        assert r.status_code == 403
        assert not ConnectorGrant.objects.filter(user=user).exists()

    def test_don_t_allow_sends_access_denied(self) -> None:
        _browser, user, query, _client_id, _verifier = allow(answer="deny")
        assert query == {"error": "access_denied", "state": "st4te"}
        assert not ConnectorGrant.objects.filter(user=user).exists()

    def test_the_code_works_once_with_its_verifier_and_only_digests_are_kept(self) -> None:
        _browser, user, query, client_id, verifier = allow()
        assert query["state"] == "st4te" and query["iss"]
        form = {
            "grant_type": "authorization_code",
            "code": query["code"],
            "redirect_uri": REDIRECT,
            "client_id": client_id,
        }
        r = trade(**form, code_verifier=verifier)
        assert r.status_code == 200 and r["Cache-Control"] == "no-store"
        tokens = r.json()
        assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600
        row = ConnectorGrant.objects.get(user=user)
        stored = json.dumps([row.access_digest, row.refresh_digest, row.spent_code_digest])
        assert tokens["access_token"] not in stored and query["code"] not in stored
        again = trade(**form, code_verifier=verifier)
        assert again.status_code == 400 and again.json()["error"] == "invalid_grant"

    def test_a_refresh_token_is_replaced_each_time(self) -> None:
        _user, tokens, client_id = tokens_for()
        first = trade(
            grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id
        )
        assert first.status_code == 200
        assert mcp(tokens["access_token"], "ping").status_code == 401
        assert mcp(first.json()["access_token"], "ping").status_code == 200
        second = trade(
            grant_type="refresh_token",
            refresh_token=first.json()["refresh_token"],
            client_id=client_id,
        )
        assert second.status_code == 200

    def test_another_app_cannot_use_the_code(self) -> None:
        _browser, _user, query, _client_id, verifier = allow()
        other = register(client_name="Other app").json()["client_id"]
        r = trade(
            grant_type="authorization_code",
            code=query["code"],
            redirect_uri=REDIRECT,
            client_id=other,
            code_verifier=verifier,
        )
        assert r.status_code == 400


@db
class TestConnector:
    def test_without_a_token_it_says_where_to_sign_in(self) -> None:
        r = mcp(None, "tools/list")
        assert r.status_code == 401
        assert 'resource_metadata="' in r["WWW-Authenticate"]
        assert mcp("rma_made_up", "tools/list").status_code == 401

    def test_it_introduces_itself_and_offers_no_files(self) -> None:
        _user, tokens, _client_id = tokens_for()
        token = tokens["access_token"]
        hello = mcp(token, "initialize", {"protocolVersion": "2025-06-18"}).json()
        info = hello["result"]["serverInfo"]
        assert info["name"] == "routemaker" and info["title"] == "RouteMaker"
        # The app's logo, from this site's own address (the connector list's icon).
        assert [(i["src"].split("/", 3)[3], i["mimeType"]) for i in info["icons"]] == [
            ("favicon.svg", "image/svg+xml"),
            ("icons/icon-192.png", "image/png"),
            ("icons/icon-512.png", "image/png"),
        ]
        assert all(i["src"].startswith("http://testserver/") for i in info["icons"])
        assert mcp(token, "notifications/initialized", msg_id=None).status_code == 202
        tools = mcp(token, "tools/list").json()["result"]["tools"]
        save = next(t for t in tools if t["name"] == "save_route")
        assert "gpx_file" not in save["inputSchema"]["properties"]

    def test_a_planned_draft_is_saved_to_the_rider_s_own_routes(self, planner) -> None:
        user, tokens, _client_id = tokens_for()
        token = tokens["access_token"]
        planned = call(token, "plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
        assert not planned["isError"], planned
        draft = planned["structuredContent"]
        assert draft["saved"] is False and not SavedRoute.objects.filter(user=user).exists()
        # The link opens this exact route, kept as the rider's own shared link.
        route_id = draft["link"].rsplit("route=", 1)[1]
        assert draft["link"].startswith(f"http://testserver/s/{route_id}#p=")
        assert SharedRoute.objects.get(pk=route_id).owner_id == user.pk
        # Drafts live in the database: the next request (any process) finds it.
        revised = call(token, "revise_route", {"draft_id": draft["draft_id"], "stress": 90})
        assert planner[-1]["stress"] == 90 and not revised["isError"]
        new_id = revised["structuredContent"]["draft_id"]
        saved = call(token, "save_route", {"draft_id": new_id, "name": "Rock Creek"})
        assert not saved["isError"], saved
        row = SavedRoute.objects.get(user=user)
        assert row.name == "Rock Creek"

    def test_a_rider_cannot_reach_another_rider_s_draft(self, planner) -> None:
        _a, a_tokens, _ = tokens_for()
        _b, b_tokens, _ = tokens_for()
        planned = call(
            a_tokens["access_token"], "plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]}
        )
        draft_id = planned["structuredContent"]["draft_id"]
        stolen = call(b_tokens["access_token"], "save_route", {"draft_id": draft_id, "name": "x"})
        assert stolen["isError"] and "no draft" in stolen["content"][0]["text"]
        assert not SavedRoute.objects.exists()

    def test_a_ban_ends_every_grant_and_drops_the_drafts(self, planner) -> None:
        user, tokens, _client_id = tokens_for()
        call(tokens["access_token"], "plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
        assert ConnectorDraft.objects.filter(user=user).exists()
        user.is_banned = True
        user.save()
        assert not ConnectorGrant.objects.filter(user=user).exists()
        assert mcp(tokens["access_token"], "ping").status_code == 401
        assert not ConnectorDraft.objects.filter(user=user).exists()

    @pytest.mark.usefixtures("weekday_clock")
    def test_a_plan_goes_through_the_site_s_own_route_view(self, segments, router) -> None:
        router(standard_router())
        _user, tokens, _client_id = tokens_for()
        points = [list(VERTICES[0]), list(VERTICES[-1])]
        planned = call(tokens["access_token"], "plan_route", {"points": points})
        assert not planned["isError"], planned
        assert planned["structuredContent"]["summary"]["distance_mi"] > 0

    def test_the_site_s_own_views_answer_in_process(self) -> None:
        user = make_user()
        browser_request = Client().get("/healthz").wsgi_request
        api = connector.InProcessApi(browser_request, user)
        status, payload, _ = api._request("GET", "/api/shared-routes/doesNotExist1")
        assert status == 404 and isinstance(payload, dict)

    def test_each_rider_is_counted_at_their_own_address(self) -> None:
        a, b = make_user(), make_user()
        assert connector.rider_address(a) != connector.rider_address(b)
        from core.ratelimit import client_address

        request = Client().get("/healthz").wsgi_request
        request.META["HTTP_X_FORWARDED_FOR"] = connector.rider_address(a)
        assert client_address(request) != "unknown"

    def test_drafts_are_kept_a_while_and_capped(self) -> None:
        user = make_user()
        store = connector.DatabaseDrafts(user, a_grant(user))
        module = connector.mcp_module()
        plan = module.Plan([(-77.03, 38.9), (-77.02, 38.91)], [], "default", {"a": 1}, None, {})
        ids = [store.put(module.Draft(plan, {}, None, "x")) for _ in range(3)]
        assert store.get(ids[0]).plan.points == [(-77.03, 38.9), (-77.02, 38.91)]
        assert ConnectorDraft.objects.filter(user=user).count() == 3
        assert store.get("dnothere") is None

    def test_a_draft_keeps_its_spur_choice_and_intervals(self) -> None:
        # revise_route reads both back: losing them dropped the interval check and trimmed a
        # spur the rider had asked to keep.
        user = make_user()
        store = connector.DatabaseDrafts(user, a_grant(user))
        module = connector.mcp_module()
        plan = module.Plan([(-77.03, 38.9), (-77.02, 38.91)], [], "default", {"a": 1}, None, {})
        intervals = {"on_minutes": 5, "sets": 4}
        draft_id = store.put(
            module.Draft(plan, {}, None, "x", trim_spurs=False, intervals=intervals)
        )
        kept = store.get(draft_id)
        assert kept.trim_spurs is False
        assert kept.intervals == intervals
        # A draft kept before v0.12.3 has neither key: the module's defaults.
        row = ConnectorDraft.objects.get(draft_id=draft_id)
        row.data = {k: v for k, v in row.data.items() if k not in ("trim_spurs", "intervals")}
        row.save()
        older = store.get(draft_id)
        assert older.trim_spurs is True and older.intervals is None


@db
class TestRoutePostDrafts:
    """The owner, 2026-10-25: "Enable a mechanism for me to have the blog posts sent directly
    from claude." An instance admin's grant may write Featured routes posts, as drafts only."""

    POINTS = [[-77.03, 38.9], [-77.02, 38.91]]
    POST = {
        "title": "Rock Creek to the river",
        "abstract": "A calm ride.",
        "audience": "Everyone.",
        "sections": [{"heading": "The trail", "body": "Shady.", "from_mile": 0, "to_mile": 0.5}],
    }

    def admin_token(self):
        from test_accounts import make_user

        user, tokens, _ = tokens_for(make_user(is_instance_admin=True))
        return user, tokens["access_token"]

    def test_only_an_instance_admin_is_offered_the_tool(self, planner) -> None:
        _user, tokens, _ = tokens_for()
        token = tokens["access_token"]
        names = [t["name"] for t in mcp(token, "tools/list").json()["result"]["tools"]]
        assert "draft_route_post" not in names
        r = mcp(token, "tools/call", {"name": "draft_route_post", "arguments": self.POST})
        assert r.json()["error"]["code"] == -32602
        assert not RoutePost.objects.exists()
        _admin, admin_token = self.admin_token()
        names = [t["name"] for t in mcp(admin_token, "tools/list").json()["result"]["tools"]]
        assert "draft_route_post" in names

    def test_the_consent_page_says_so_to_an_admin_only(self) -> None:
        from test_accounts import make_user

        for admin in (False, True):
            client_id = register().json()["client_id"]
            _verifier, challenge = pkce()
            browser, _user, _csrf = signed_in(make_user(is_instance_admin=admin))
            page = browser.get("/oauth/authorize", authorize_params(client_id, challenge), **addr())
            assert (b"Featured routes posts as drafts" in page.content) is admin

    def test_a_planned_draft_becomes_a_draft_post(self, planner) -> None:
        user, token = self.admin_token()
        planned = call(token, "plan_route", {"points": self.POINTS})
        out = call(
            token,
            "draft_route_post",
            {**self.POST, "draft_id": planned["structuredContent"]["draft_id"]},
        )
        assert not out["isError"], out
        answer = out["structuredContent"]
        assert answer["slug"] == "rock-creek-to-the-river" and answer["status"] == "draft"
        assert answer["page"] == "http://testserver/routes/rock-creek-to-the-river"
        post = RoutePost.objects.get()
        assert post.status == RoutePost.Status.DRAFT and post.author_id == user.pk
        assert post.saved_route_id is None and post.stats["distance_m"] > 0
        assert post.route.keep == "forever" and post.route.owner_id is None
        assert [(s.heading, float(s.end_mi)) for s in post.sections.all()] == [("The trail", 0.5)]
        assert AuditLogEntry.objects.filter(action="route_post.draft").count() == 1
        # A draft: nobody but an admin sees the page.
        assert Client().get("/routes/rock-creek-to-the-river", **addr()).status_code == 404
        # Nothing went to the admin's My routes.
        assert not SavedRoute.objects.filter(user=user).exists()

    def test_sending_the_slug_again_rewrites_the_draft_until_it_is_published(self, planner) -> None:
        _user, token = self.admin_token()
        draft_id = call(token, "plan_route", {"points": self.POINTS})["structuredContent"][
            "draft_id"
        ]
        call(token, "draft_route_post", {**self.POST, "draft_id": draft_id})
        # Without replace, a draft at the slug (one written in the admin, say) is left alone.
        taken = call(token, "draft_route_post", {**self.POST, "draft_id": draft_id})
        assert taken["isError"] and "send replace" in taken["content"][0]["text"]
        again = call(
            token,
            "draft_route_post",
            {
                **self.POST,
                "abstract": "Calmer.",
                "sections": [],
                "draft_id": draft_id,
                "replace": True,
            },
        )
        assert not again["isError"], again
        post = RoutePost.objects.get()
        assert post.abstract == "Calmer." and not post.sections.exists()
        # The copy it was rewritten from had no public link, so it went.
        assert SharedRoute.objects.filter(keep="forever").count() == 1
        for status in ("published", "unlisted", "withdrawn"):
            RoutePost.objects.filter(pk=post.pk).update(status=status)
            refused = call(
                token, "draft_route_post", {**self.POST, "draft_id": draft_id, "replace": True}
            )
            assert refused["isError"] and "no longer a draft" in refused["content"][0]["text"]
        assert RoutePost.objects.get().abstract == "Calmer."

    def test_a_line_to_follow_is_planned_as_an_opened_file(self, planner) -> None:
        _user, token = self.admin_token()
        line = [[-77.03, 38.9], [-77.025, 38.905], [-77.02, 38.91]]
        out = call(
            token,
            "draft_route_post",
            {
                **self.POST,
                "follow": {"polyline": encode_polyline(line), "preset": "trailmaxxing"},
            },
        )
        assert not out["isError"], out
        sent = planner[-1]
        assert sent["follow"] == encode_polyline(line) and sent["preset"] == "trailmaxxing"
        assert sent["points"] == [line[0], line[-1]]
        post = RoutePost.objects.get()
        assert post.route.source == "gpx" and post.stats["preset"] == "trailmaxxing"
        # Open in RouteMaker opens it (the owner, 2026-10-25: "It just opens RouteMaker"): the app
        # takes a shared line with a plan link (frontend/src/lib/sharedRoutes.ts isRoute) and
        # opens a followed line from its file (App.tsx openSaved).
        shared = Client().get(f"/api/shared-routes/{post.route_id}", **addr()).json()
        ends = "p=-77.03000,38.90000;-77.02000,38.91000"
        assert shared["inputs"]["hash"] == f"{ends}&preset=trailmaxxing"
        assert shared["gpx"].count("<trkpt") == len(line)
        assert "<name>Rock Creek to the river</name>" in shared["gpx"]

    def test_the_route_is_one_or_the_other(self, planner) -> None:
        _user, token = self.admin_token()
        out = call(token, "draft_route_post", self.POST)
        assert out["isError"] and "one of the two" in out["content"][0]["text"]

    def test_a_route_from_home_is_refused(self, planner) -> None:
        user, token = self.admin_token()
        MyGo.objects.create(user=user, home_lon=self.POINTS[0][0], home_lat=self.POINTS[0][1])
        draft_id = call(token, "plan_route", {"points": self.POINTS})["structuredContent"][
            "draft_id"
        ]
        out = call(token, "draft_route_post", {**self.POST, "draft_id": draft_id})
        assert out["isError"] and connector.POST_ROUTE_REFUSED in out["content"][0]["text"]
        assert not RoutePost.objects.exists()

    def test_a_route_refused_for_home_does_not_say_home_and_stops_after_three(
        self, planner
    ) -> None:
        user, token = self.admin_token()
        MyGo.objects.create(user=user, home_lon=self.POINTS[0][0], home_lat=self.POINTS[0][1])
        draft_id = call(token, "plan_route", {"points": self.POINTS})["structuredContent"][
            "draft_id"
        ]
        for _ in range(3):
            out = call(token, "draft_route_post", {**self.POST, "draft_id": draft_id})
            assert out["isError"] and "Home" not in out["content"][0]["text"]
        # After three, even a route far from Home is not written today.
        far = call(token, "plan_route", {"points": [[-77.1, 38.95], [-77.09, 38.96]]})
        out = call(
            token,
            "draft_route_post",
            {**self.POST, "draft_id": far["structuredContent"]["draft_id"]},
        )
        assert out["isError"] and connector.POST_REFUSED_TODAY in out["content"][0]["text"]
        assert not RoutePost.objects.exists()

    def test_a_stretch_past_the_route_s_end_is_refused(self, planner) -> None:
        _user, token = self.admin_token()
        draft_id = call(token, "plan_route", {"points": self.POINTS})["structuredContent"][
            "draft_id"
        ]
        # An end past the route is held to its length; a start past it is refused.
        held = {"heading": "Whole", "from_mile": 0, "to_mile": 1e6}
        out = call(
            token, "draft_route_post", {**self.POST, "sections": [held], "draft_id": draft_id}
        )
        assert not out["isError"], out
        assert 0 < float(RoutePost.objects.get().sections.get().end_mi) < 5
        long = {"heading": "Far", "from_mile": 50, "to_mile": 60}
        out = call(
            token,
            "draft_route_post",
            {**self.POST, "sections": [long], "draft_id": draft_id, "replace": True},
        )
        assert out["isError"] and "mi long" in out["content"][0]["text"]

    def test_an_admin_no_longer_is_offered_nothing(self, planner) -> None:
        from test_accounts import make_user

        user, token = self.admin_token()
        make_user(is_instance_admin=True)  # the site always keeps one
        user.is_instance_admin = False
        user.save()
        names = [t["name"] for t in mcp(token, "tools/list").json()["result"]["tools"]]
        assert "draft_route_post" not in names


@db
def test_a_registration_grants_nothing_by_itself() -> None:
    client_id = register().json()["client_id"]
    assert ConnectorClient.objects.filter(client_id=client_id).exists()
    assert not ConnectorGrant.objects.exists()


@db
class TestReview:
    """The connector review's findings (2026-10-19)."""

    def test_allow_works_when_the_browser_sends_the_site_s_origin(self) -> None:
        client_id = register().json()["client_id"]
        _verifier, challenge = pkce()
        browser, _user, csrf = signed_in()
        params = authorize_params(client_id, challenge)
        page = browser.get("/oauth/authorize", params, **addr())
        # A no-referrer page makes browsers post "Origin: null", which the CSRF check refuses.
        assert page["Referrer-Policy"] == "same-origin"
        answered = browser.post(
            "/oauth/authorize",
            {**params, "answer": "allow", "csrfmiddlewaretoken": csrf},
            HTTP_ORIGIN="http://testserver",
            **addr(),
        )
        assert answered.status_code == 302 and "code=" in answered["Location"]

    @pytest.mark.parametrize(
        "changes",
        [
            {"response_type": "token"},
            {"code_challenge_method": "plain"},
            {"resource": "https://elsewhere.example/mcp"},
        ],
    )
    def test_a_bad_request_is_answered_here_not_redirected(self, changes) -> None:
        client_id = (
            Client()
            .post(
                "/oauth/register",
                data=json.dumps({"client_name": "x", "redirect_uris": ["https://evil.example/l"]}),
                content_type="application/json",
                **addr(),
            )
            .json()["client_id"]
        )
        _verifier, challenge = pkce()
        params = authorize_params(
            client_id, challenge, redirect_uri="https://evil.example/l", **changes
        )
        r = Client().get("/oauth/authorize", params, **addr())
        assert r.status_code == 400 and "Location" not in r

    def test_a_redirect_host_cannot_carry_csp_text(self) -> None:
        assert register("https://a.com;script-src */cb").status_code == 400
        assert register("https://a.com,b.com/cb").status_code == 400

    def test_the_same_app_registers_once(self) -> None:
        assert register().json()["client_id"] == register().json()["client_id"]
        assert ConnectorClient.objects.count() == 1

    def test_a_wrong_verifier_spends_the_code(self) -> None:
        _browser, user, query, client_id, verifier = allow()
        form = {
            "grant_type": "authorization_code",
            "code": query["code"],
            "redirect_uri": REDIRECT,
            "client_id": client_id,
        }
        assert trade(**form, code_verifier="wrong" * 10).status_code == 400
        assert trade(**form, code_verifier=verifier).status_code == 400
        assert not ConnectorGrant.objects.filter(user=user).exists()

    def test_a_replayed_code_ends_the_grant_it_bought(self) -> None:
        _browser, _user, query, client_id, verifier = allow()
        form = {
            "grant_type": "authorization_code",
            "code": query["code"],
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        }
        tokens = trade(**form).json()
        assert trade(**form).status_code == 400
        assert mcp(tokens["access_token"], "ping").status_code == 401

    def test_a_replayed_refresh_token_ends_the_grant(self) -> None:
        _user, tokens, client_id = tokens_for()
        old = tokens["refresh_token"]
        new = trade(grant_type="refresh_token", refresh_token=old, client_id=client_id).json()
        assert (
            trade(grant_type="refresh_token", refresh_token=old, client_id=client_id).status_code
            == 400
        )
        assert mcp(new["access_token"], "ping").status_code == 401

    def test_signing_out_everywhere_ends_grants(self) -> None:
        from core.revocation import bump_session_epoch

        user, tokens, _client_id = tokens_for()
        bump_session_epoch(user, "test")
        assert mcp(tokens["access_token"], "ping").status_code == 401

    def test_an_id_that_is_not_a_string_or_number_is_refused(self) -> None:
        _user, tokens, _client_id = tokens_for()
        r = mcp(tokens["access_token"], "ping", msg_id=[1])
        assert r.status_code == 400 and r.json()["error"]["code"] == -32600

    def test_only_unsigned_requests_count_against_the_address(self, monkeypatch) -> None:
        from core import ratelimit

        _user, tokens, _client_id = tokens_for()
        tight = ratelimit.Limit(scope="connector-ip-test", requests=1, window_s=60)
        monkeypatch.setattr(ratelimit, "CONNECTOR_ADDRESS", tight)
        one = {"HTTP_X_FORWARDED_FOR": "203.0.113.7"}  # claude.ai's riders share addresses

        def ping(token=None):
            auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            return (
                Client()
                .post("/mcp", data=body, content_type="application/json", **auth, **one)
                .status_code
            )

        assert ping() == 401
        assert ping() == 429
        assert ping(tokens["access_token"]) == 200

    def test_in_process_plans_count_from_when_the_mcp_request_began(self, monkeypatch) -> None:
        user = make_user()
        outer = Client().get("/healthz").wsgi_request
        outer.routing_started = 12.5
        seen = []

        def view(request):
            seen.append(request.routing_started)
            from django.http import JsonResponse

            return JsonResponse({})

        api = connector.InProcessApi(outer, user)
        from types import SimpleNamespace

        match = SimpleNamespace(func=view, args=(), kwargs={})
        monkeypatch.setattr(connector, "resolve", lambda _path: match)
        api._request("GET", "/api/geocode?q=x")
        assert seen == [12.5]

    def test_the_sweep_clears_what_will_never_be_used(self) -> None:
        from datetime import timedelta

        from django.utils import timezone

        user = make_user()
        old = timezone.now() - timedelta(days=8)
        ConnectorDraft.objects.create(user=user, draft_id="dold", data={})
        ConnectorDraft.objects.filter(draft_id="dold").update(created_at=old)
        app = ConnectorClient.objects.create(
            client_id="rmc_old", name="x", redirect_uris=[REDIRECT]
        )
        ConnectorClient.objects.filter(pk=app.pk).update(created_at=old)
        _user, tokens, _client_id = tokens_for()
        assert connector.sweep_connector() == 2
        assert mcp(tokens["access_token"], "ping").status_code == 200


@db
class TestGpx:
    def test_a_draft_s_gpx_downloads_from_its_link_and_nothing_else_does(self, planner) -> None:
        _user, tokens, _client_id = tokens_for()
        token = tokens["access_token"]
        planned = call(token, "plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
        draft_id = planned["structuredContent"]["draft_id"]
        gpx = call(token, "gpx_route", {"draft_id": draft_id, "name": "Rock Creek"})
        assert not gpx["isError"], gpx
        link = gpx["structuredContent"]["gpx_link"]
        assert link.startswith("http://testserver/mcp/gpx/")
        r = Client().get(urllib.parse.urlsplit(link).path, **addr())
        assert r.status_code == 200 and r["Content-Type"] == "application/gpx+xml"
        assert 'filename="rock-creek.gpx"' in r["Content-Disposition"]
        assert b"<trkpt" in r.content and b"Rock Creek" in r.content
        path = urllib.parse.urlsplit(link).path
        assert Client().get(path[:-2] + "xx", **addr()).status_code == 404

    def test_a_banned_rider_s_link_stops_working(self, planner) -> None:
        user, tokens, _client_id = tokens_for()
        token = tokens["access_token"]
        planned = call(token, "plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
        draft_id = planned["structuredContent"]["draft_id"]
        link = call(token, "gpx_route", {"draft_id": draft_id})["structuredContent"]["gpx_link"]
        user.is_banned = True
        user.save()
        assert Client().get(urllib.parse.urlsplit(link).path, **addr()).status_code == 404

    def test_the_gpx_link_names_no_account_and_no_route(self, planner) -> None:
        import zlib

        user, tokens, _client_id = tokens_for()
        token = tokens["access_token"]
        planned = call(token, "plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
        draft_id = planned["structuredContent"]["draft_id"]
        link = call(token, "gpx_route", {"draft_id": draft_id, "name": "Rock Creek"})[
            "structuredContent"
        ]["gpx_link"]
        secret = urllib.parse.urlsplit(link).path.rsplit("/", 1)[1]
        readable = []
        for part in secret.split(".") + secret.split(":"):
            try:
                raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
            except ValueError:
                continue
            for text in (raw, zlib.decompress(raw) if raw[:1] == b"x" else b""):
                readable.append(text.decode("latin-1"))
        assert not any("Rock Creek" in text or '"u"' in text for text in readable)
        # The file still has its name.
        r = Client().get(urllib.parse.urlsplit(link).path, **addr())
        assert r.status_code == 200 and 'filename="rock-creek.gpx"' in r["Content-Disposition"]

    def test_the_gpx_link_stops_with_its_draft_after_a_day(self, planner) -> None:
        from datetime import timedelta

        from django.utils import timezone

        _user, tokens, _client_id = tokens_for()
        token = tokens["access_token"]
        planned = call(token, "plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
        draft_id = planned["structuredContent"]["draft_id"]
        link = call(token, "gpx_route", {"draft_id": draft_id})["structuredContent"]["gpx_link"]
        path = urllib.parse.urlsplit(link).path
        ConnectorDraft.objects.update(created_at=timezone.now() - timedelta(hours=23))
        assert Client().get(path, **addr()).status_code == 200
        ConnectorDraft.objects.update(created_at=timezone.now() - timedelta(hours=25))
        r = Client().get(path, **addr())
        assert r.status_code == 404 and b"no longer kept" in r.content


@db
class TestDraftKeeping:
    """A draft holds the route's points, often the rider's door: kept a day, long enough to plan
    in the evening and save or download the next morning, and dropped with its links when the
    app is disconnected."""

    POINTS = [[-77.03, 38.9], [-77.02, 38.91]]

    def plan(self, token) -> dict:
        planned = call(token, "plan_route", {"points": self.POINTS})
        assert not planned["isError"], planned
        return planned["structuredContent"]

    @staticmethod
    def age(hours: float) -> None:
        from datetime import timedelta

        from django.utils import timezone

        then = timezone.now() - timedelta(hours=hours)
        ConnectorDraft.objects.update(created_at=then)
        SharedRoute.objects.update(created_at=then, last_opened_at=then)

    def test_a_draft_is_kept_a_day_and_then_dropped(self, planner) -> None:
        _user, tokens, _ = tokens_for()
        token = tokens["access_token"]
        draft = self.plan(token)
        self.age(23)
        assert not call(token, "revise_route", {"draft_id": draft["draft_id"]})["isError"]
        self.age(25)
        later = call(token, "save_route", {"draft_id": draft["draft_id"], "name": "x"})
        assert later["isError"] and "no draft" in later["content"][0]["text"]
        connector.sweep_connector()
        assert not ConnectorDraft.objects.exists()
        assert not SavedRoute.objects.exists()

    def test_a_draft_s_link_goes_with_its_draft_and_says_so(self, planner) -> None:
        _user, tokens, _ = tokens_for()
        route_id = self.plan(tokens["access_token"])["link"].rsplit("route=", 1)[1]
        assert Client().get(f"/api/shared-routes/{route_id}", **addr()).status_code == 200
        self.age(25)
        gone = Client().get(f"/api/shared-routes/{route_id}", **addr())
        assert gone.status_code == 404 and gone.json()["code"] == "not_found"
        assert "no longer kept" in gone.json()["error"]
        preview = Client().get(f"/s/{route_id}", HTTP_USER_AGENT="Slackbot 1.0", **addr())
        assert preview.status_code == 404 and b"no longer kept" in preview.content
        assert not SharedRoute.objects.filter(pk=route_id).exists()

    def test_draft_ids_are_long_random_values(self, planner) -> None:
        import re

        _user, tokens, _ = tokens_for()
        assert re.fullmatch(r"d[0-9a-f]{32}", self.plan(tokens["access_token"])["draft_id"])

    def test_another_app_of_the_same_rider_cannot_reach_the_draft(self, planner) -> None:
        user, first, _ = tokens_for()
        _same, second, _ = tokens_for(user)
        draft_id = self.plan(first["access_token"])["draft_id"]
        other = call(second["access_token"], "save_route", {"draft_id": draft_id, "name": "x"})
        assert other["isError"] and "no draft" in other["content"][0]["text"]
        assert not SavedRoute.objects.exists()

    def test_disconnecting_an_app_drops_its_drafts_and_links(self, planner) -> None:
        browser, user, query, client_id, verifier = allow()
        tokens = trade(
            grant_type="authorization_code",
            code=query["code"],
            redirect_uri=REDIRECT,
            client_id=client_id,
            code_verifier=verifier,
        ).json()
        token = tokens["access_token"]
        draft = self.plan(token)
        route_id = draft["link"].rsplit("route=", 1)[1]
        gpx = call(token, "gpx_route", {"draft_id": draft["draft_id"]})["structuredContent"]
        # Another app of the same rider keeps its own.
        _same, kept_tokens, _ = tokens_for(user)
        kept = self.plan(kept_tokens["access_token"])
        apps = browser.get("/api/me/connected-apps", **addr()).json()["apps"]
        first = ConnectorGrant.objects.filter(user=user).order_by("created_at").first()
        assert first.pk in [a["id"] for a in apps]
        csrf = browser.cookies["csrftoken"].value
        r = send(browser, "post", f"/api/me/connected-apps/{first.pk}/delete", {}, csrf)
        assert r.status_code == 200
        assert list(ConnectorDraft.objects.values_list("draft_id", flat=True)) == [kept["draft_id"]]
        gone = Client().get(f"/api/shared-routes/{route_id}", **addr())
        assert gone.status_code == 404 and "no longer kept" in gone.json()["error"]
        page = Client().get(urllib.parse.urlsplit(gpx["gpx_link"]).path, **addr())
        assert page.status_code == 404 and b"no longer kept" in page.content
        kept_id = kept["link"].rsplit("route=", 1)[1]
        assert Client().get(f"/api/shared-routes/{kept_id}", **addr()).status_code == 200

    def test_signing_out_everywhere_drops_every_app_s_drafts_and_links(self, planner) -> None:
        from core.revocation import bump_session_epoch

        user, tokens, _ = tokens_for()
        token = tokens["access_token"]
        draft = self.plan(token)
        gpx = call(token, "gpx_route", {"draft_id": draft["draft_id"]})["structuredContent"]
        bump_session_epoch(user, "test")
        assert not ConnectorDraft.objects.exists()
        route_id = draft["link"].rsplit("route=", 1)[1]
        assert Client().get(f"/api/shared-routes/{route_id}", **addr()).status_code == 404
        path = urllib.parse.urlsplit(gpx["gpx_link"]).path
        assert Client().get(path, **addr()).status_code == 404

    def test_drop_for_user_drops_the_rider_s_drafts_and_links_only(self, planner) -> None:
        user, tokens, _ = tokens_for()
        _other, other_tokens, _ = tokens_for()
        mine = self.plan(tokens["access_token"])
        theirs = self.plan(other_tokens["access_token"])
        assert connector.drop_for_user(user) == 1
        assert list(ConnectorDraft.objects.values_list("draft_id", flat=True)) == [
            theirs["draft_id"]
        ]
        assert not SharedRoute.objects.filter(pk=mine["link"].rsplit("route=", 1)[1]).exists()


@db
class TestConnectedApps:
    """Settings lists the apps a rider connected, each with Disconnect (the owner, 2026-10-19)."""

    def test_the_rider_sees_their_apps_and_disconnects_one(self) -> None:
        browser, user, query, client_id, verifier = allow()
        tokens = trade(
            grant_type="authorization_code",
            code=query["code"],
            redirect_uri=REDIRECT,
            client_id=client_id,
            code_verifier=verifier,
        ).json()
        _other, _other_tokens, _ = tokens_for()  # another rider's app: not listed here
        apps = browser.get("/api/me/connected-apps", **addr()).json()["apps"]
        assert [a["name"] for a in apps] == ["Claude"]
        csrf = browser.cookies["csrftoken"].value
        r = send(browser, "post", f"/api/me/connected-apps/{apps[0]['id']}/delete", {}, csrf)
        assert r.status_code == 200 and r.json() == {"apps": []}
        assert mcp(tokens["access_token"], "ping").status_code == 401
        assert ConnectorGrant.objects.exclude(user=user).count() == 1

    def test_another_rider_s_app_cannot_be_disconnected(self) -> None:
        _user, tokens, _ = tokens_for()
        grant = ConnectorGrant.objects.get()
        browser, _me, csrf = signed_in()
        send(browser, "post", f"/api/me/connected-apps/{grant.pk}/delete", {}, csrf)
        assert mcp(tokens["access_token"], "ping").status_code == 200

    def test_signed_out_sees_nothing(self) -> None:
        assert Client().get("/api/me/connected-apps", **addr()).status_code == 401
