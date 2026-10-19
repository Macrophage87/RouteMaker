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
from test_accounts import addr, make_user, signed_in
from test_mcp_server import straight_answer
from test_route_api import VERTICES, router, segments, standard_router

from core import connector
from core.models import (
    ConnectorClient,
    ConnectorDraft,
    ConnectorGrant,
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
        assert hello["result"]["serverInfo"]["name"] == "routemaker"
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
        store = connector.DatabaseDrafts(user)
        module = connector.mcp_module()
        plan = module.Plan([(-77.03, 38.9), (-77.02, 38.91)], [], "default", {"a": 1}, None, {})
        ids = [store.put(module.Draft(plan, {}, None, "x")) for _ in range(3)]
        assert store.get(ids[0]).plan.points == [(-77.03, 38.9), (-77.02, 38.91)]
        assert ConnectorDraft.objects.filter(user=user).count() == 3
        assert store.get("dnothere") is None


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
