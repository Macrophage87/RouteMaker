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
from core.models import ConnectorClient, ConnectorDraft, ConnectorGrant, SavedRoute

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
        assert r.status_code == 302 and "error=invalid_request" in r["Location"]

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
        assert trade(**form, code_verifier="wrong" * 10).status_code == 400
        r = trade(**form, code_verifier=verifier)
        assert r.status_code == 200 and r["Cache-Control"] == "no-store"
        tokens = r.json()
        assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600
        again = trade(**form, code_verifier=verifier)
        assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
        row = ConnectorGrant.objects.get(user=user)
        stored = json.dumps([row.access_digest, row.refresh_digest, row.code_digest])
        assert tokens["access_token"] not in stored and query["code"] not in stored

    def test_a_refresh_token_is_replaced_each_time(self) -> None:
        _user, tokens, client_id = tokens_for()
        first = trade(
            grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id
        )
        assert first.status_code == 200
        stale = trade(
            grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id
        )
        assert stale.status_code == 400
        assert mcp(tokens["access_token"], "ping").status_code == 401
        assert mcp(first.json()["access_token"], "ping").status_code == 200

    def test_another_app_cannot_use_the_code(self) -> None:
        _browser, _user, query, _client_id, verifier = allow()
        other = register().json()["client_id"]
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
        assert draft["link"].startswith("http://testserver/#p=")
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
