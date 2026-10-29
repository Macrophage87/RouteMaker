"""The site's own MCP connector: route planning in Claude (or any assistant app) on the web and the
phone, at <site>/mcp (the owner, 2026-10-19: "It's deployed to a website, shouldn't it work
anywhere?", then "Build it, v0.10.0").

`mcp/routemaker_mcp.py` is the assistant's side: the tools, the Metro check, the loop builder and
the drafts. Run on a rider's own computer it plans through the site's API over HTTP. Here the
same module runs inside the site, and three things change:

- It reaches the API in-process (`InProcessApi`), as the signed-in rider, so a route is exactly
  the app's and each rider is counted against their own rate limits, not those of the
  assistant's servers, whose one address every rider would share.
- Drafts are kept in the database (`core.models.ConnectorDraft`), since gunicorn's processes
  share nothing: each app's own, for a day (`ConnectorDraft.KEPT`), with the link each plan
  makes and its GPX link going with it, and all of them when the app is disconnected.
- A call answers inside one web request, which gunicorn ends at 60 s: the module plans again
  only while another long plan still fits, and says so when it stops.

Sign-in is OAuth 2.1 with PKCE, which is what an assistant app speaks: the app registers itself
(RFC 7591), sends the rider to /oauth/authorize, where the rider signs in with Discord as usual
and allows it on a page of this site, and trades the code for tokens at /oauth/token. Only
SHA-256 digests of the code and the tokens are kept. A grant can plan and add routes to My
routes: it signs nobody in to the site and reads none of the account's saved routes. An instance
admin's grant can also write Featured routes posts as drafts (draft_route_post,
core.route_posts.write_draft; the owner, 2026-10-25: "Enable a mechanism for me to have the blog
posts sent directly from claude"); publishing stays theirs, in the admin.

The endpoint speaks MCP's Streamable HTTP transport in its plainest form: each POST carries one
JSON-RPC message and is answered with one JSON body, with no stream and no session.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import logging
import re
import secrets
import sys
import time
import urllib.parse
from datetime import timedelta
from functools import cache

from django.conf import settings
from django.contrib.sessions.backends.base import SessionBase
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.test import RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt

from . import ratelimit
from .models import ConnectorClient, ConnectorDraft, ConnectorGrant, SharedRoute

logger = logging.getLogger(__name__)

SCOPE = "routes"
CODE_LIFETIME = timedelta(minutes=5)
ACCESS_LIFETIME = timedelta(hours=1)
REFRESH_LIFETIME = timedelta(days=30)
# What one tools/call may spend: gunicorn ends a request at 60 s (docker/api-entrypoint.sh).
CALL_BUDGET_S = 55
MAX_REDIRECT_URIS = 5
MAX_BODY_BYTES = 64 * 1024
# What draft_route_post says of a route the admin's own checks refuse for their Home.
POST_ROUTE_REFUSED = "this route cannot be a post; pick another, or pick the route in the admin"
POST_REFUSED_TODAY = "no more post drafts today; write the post in the admin"


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _origin(request) -> str:
    return request.build_absolute_uri("/").rstrip("/")


def _no_store(response):
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


# --- The assistant's module --------------------------------------------------------------------


@cache
def mcp_module():
    """`mcp/routemaker_mcp.py`, loaded once from the repository (or the image's copy of it)."""
    path = settings.BASE_DIR / "mcp" / "routemaker_mcp.py"
    spec = importlib.util.spec_from_file_location("routemaker_mcp", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["routemaker_mcp"] = module  # its dataclasses look themselves up there
    spec.loader.exec_module(module)
    return module


def rider_address(user) -> str:
    """The address a rider's in-process requests are counted as: one of their own, in a
    private IPv6 range (fd00::/8), so each rider has their own budget (the limits count an IPv6
    client by its /64)."""
    uid = int(user.pk)
    return f"fd00:524d:{(uid >> 16) & 0xFFFF:x}:{uid & 0xFFFF:x}::1"


class InProcessApi:
    """The module's `Api`, answered by the site's own views in this process, as the rider."""

    def __init__(self, request, user):
        module = mcp_module()
        self._module = module
        self.base = _origin(request)
        # When the /mcp request began: the site's plan budget counts from it, so the plan that
        # follows a few place searches still ends inside gunicorn's 60 s.
        self._started = getattr(request, "routing_started", None)
        self._host = request.get_host()
        self._secure = request.is_secure()
        self.user = user

    def _request(self, method: str, path: str, body=None, headers=None, timeout=30):
        factory = RequestFactory()
        address = rider_address(self.user)
        meta = {
            "HTTP_HOST": self._host,
            "REMOTE_ADDR": address,
            "HTTP_X_FORWARDED_FOR": address,
            "HTTP_ACCEPT": "application/json",
            "wsgi.url_scheme": "https" if self._secure else "http",
        }
        if method == "GET":
            request = factory.get(path, **meta)
        else:
            request = factory.post(
                path, data=json.dumps(body or {}), content_type="application/json", **meta
            )
        request.user = self.user
        request.session = SessionBase()
        request._dont_enforce_csrf_checks = True
        if self._started is not None:
            request.routing_started = self._started
        match = resolve(urllib.parse.urlsplit(path).path)
        response = match.func(request, *match.args, **match.kwargs)
        try:
            payload = json.loads(response.content or b"null")
        except ValueError:
            payload = None
        return response.status_code, payload, response

    def route(self, body: dict) -> dict:
        for attempt in range(2):
            status, payload, response = self._request("POST", "/api/route", body)
            if status == 200 and isinstance(payload, dict):
                return payload
            code = payload.get("code") if isinstance(payload, dict) else None
            if attempt or status not in (429, 503) or code == "long_ride_timed_out":
                break
            # Busy (parallel calls share the rider's two plans in flight): one short wait.
            try:
                wait = float(response.get("Retry-After", "2"))
            except (TypeError, ValueError):
                wait = 2.0
            time.sleep(min(3.0, max(0.5, wait)))
        message = payload.get("error") if isinstance(payload, dict) else payload
        code = payload.get("code") if isinstance(payload, dict) else None
        if code == "long_ride_timed_out":
            raise self._module.ToolError(
                f"the site ran out of time planning this long ride ({message}). Try fewer"
                " points, a lower stress setting, or plan it in two halves."
            )
        if status in (429, 503):
            raise self._module.ToolError(
                f"the site is busy ({message}); wait {response.get('Retry-After', 'a few')}"
                " seconds and try again"
            )
        raise self._module.ToolError(self._module.refusal(status, message))

    def geocode(self, query, near=None):
        return self._module.Api.geocode(self, query, near)

    def scenic_roads(self, near, miles, designation=""):
        return self._module.Api.scenic_roads(self, near, miles, designation)

    def climbs_near(self, near, miles, **filters):
        return self._module.Api.climbs_near(self, near, miles, **filters)

    def closures_map(self, box, permits):
        return self._module.Api.closures_map(self, box, permits)

    def shared_fragment(self, route_id):
        return self._module.Api.shared_fragment(self, route_id)

    def shared_route(self, route_id):
        return self._module.Api.shared_route(self, route_id)

    def share(self, body: dict) -> str:
        """Keep the exact route under its link id, as the app's Share does: the rider's own
        link (theirs to turn off from My routes), counted against their own limit."""
        return self._module.Api.share(self, body)

    def save(self, body: dict) -> dict:
        """Add to the rider's My routes through My routes' own checks and limits (adding only:
        never a new version of a route already saved)."""
        from .api import _add_saved_route, errors_as_json

        factory = RequestFactory()
        address = rider_address(self.user)
        request = factory.post(
            "/api/me/routes",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=self._host,
            REMOTE_ADDR=address,
            HTTP_X_FORWARDED_FOR=address,
        )
        request.user = self.user
        view = errors_as_json(
            ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES)(
                lambda r: _add_saved_route(r, versions=False)
            )
        )
        response = view(request)
        try:
            payload = json.loads(response.content or b"null")
        except ValueError:
            payload = None
        if response.status_code in (200, 201) and isinstance(payload, dict):
            return payload
        message = payload.get("error") if isinstance(payload, dict) else payload
        raise self._module.ToolError(
            f"the site did not save it ({response.status_code}): {message}"
        )

    def draft_post(self, fields: dict, route: dict) -> dict:
        """Write a Featured routes post as a draft (core.route_posts.write_draft), counted
        against the rider's account writes."""
        from . import route_posts

        decision = ratelimit.hit(
            ratelimit.ACCOUNT_WRITES, ratelimit.client_key(f"user:{self.user.pk}")
        )
        if not decision.allowed:
            raise self._module.ToolError(
                f"too many changes just now; wait {decision.retry_after_s} seconds"
            )
        # A route at the admin's Home is refused in words that do not name Home, and only a few
        # times a day: the route is the caller's to choose, point by point.
        home_key = ratelimit.client_key(f"connector-post-home:{self.user.pk}")
        if not ratelimit.hit(ratelimit.CONNECTOR_POST_HOME, home_key, cost=0).allowed:
            raise self._module.ToolError(POST_REFUSED_TODAY)
        post, problem = route_posts.write_draft(self.user, fields, route)
        if problem == route_posts.HOME_REFUSAL:
            ratelimit.hit(ratelimit.CONNECTOR_POST_HOME, home_key)
            problem = POST_ROUTE_REFUSED
        if problem:
            raise self._module.ToolError(f"the site did not keep the post: {problem}")
        return {
            "slug": post.slug,
            "status": post.status,
            "page": f"{self.base}{post.get_absolute_url()}",
            "admin": self.base + reverse("routemaker_admin:core_routepost_change", args=[post.pk]),
            "figures": dict(route_posts.figures(post)),
            "sections": post.sections.count(),
            "photos_waiting": post.photos.filter(image__isnull=True).count(),
        }


class DatabaseDrafts:
    """The module's draft store, in `ConnectorDraft`: the rider's own, drafted through this one
    app (`grant`), kept `ConnectorDraft.KEPT`. Another app the rider connected finds none of
    them."""

    def __init__(self, user, grant):
        self.user = user
        self.grant_id = getattr(grant, "pk", grant)

    def _rows(self):
        return ConnectorDraft.objects.filter(user=self.user, grant_id=self.grant_id)

    def _row(self, draft_id: str):
        if self.grant_id is None:
            return None
        return (
            self._rows()
            .filter(draft_id=draft_id, created_at__gte=timezone.now() - ConnectorDraft.KEPT)
            .first()
        )

    def get(self, draft_id: str):
        module = mcp_module()
        row = self._row(draft_id)
        if row is None:
            return None
        data = row.data
        plan = module.Plan(
            points=[tuple(p) for p in data["plan"]["points"]],
            vias=list(data["plan"]["vias"]),
            preset=data["plan"]["preset"],
            answer=data["plan"]["answer"],
            check=data["plan"]["check"],
            sent=data["plan"]["sent"],
        )
        return module.Draft(
            plan,
            data["options"],
            data["limit"],
            data["name"],
            # Drafts kept before v0.12.3 have neither: the module's defaults.
            trim_spurs=data.get("trim_spurs", True),
            intervals=data.get("intervals"),
            ride_key=data.get("ride_key"),
        )

    def put(self, draft) -> str:
        plan = draft.plan
        data = {
            "plan": {
                "points": [list(p) for p in plan.points],
                "vias": list(plan.vias),
                "preset": plan.preset,
                # The alternatives are not needed again and are most of an answer's size.
                "answer": {k: v for k, v in plan.answer.items() if k != "candidates"},
                "check": plan.check,
                "sent": plan.sent,
            },
            "options": draft.options,
            "limit": draft.limit,
            "name": draft.name,
            "trim_spurs": draft.trim_spurs,
            "intervals": draft.intervals,
            "ride_key": draft.ride_key,
        }
        # 128 random bits: an id seen in a transcript cannot be walked to its neighbours.
        draft_id = f"d{secrets.token_hex(16)}"
        with transaction.atomic():
            ConnectorDraft.objects.create(
                user=self.user, grant_id=self.grant_id, draft_id=draft_id, data=data
            )
            drop_stale_drafts()
            mine = ConnectorDraft.objects.filter(user=self.user)
            extra = mine.order_by("-created_at", "-pk")[ConnectorDraft.MAX_PER_USER :]
            mine.filter(pk__in=[row.pk for row in extra]).delete()
        return draft_id

    def shared(self, draft_id: str, route_id: str) -> None:
        """The link the module made for this draft (a SharedRoute) goes with the draft."""
        row = self._row(draft_id)
        if row is not None:
            SharedRoute.objects.filter(pk=route_id, owner=self.user).update(connector_draft=row)

    def name_gpx(self, draft_id: str, name: str) -> bool:
        """Keep the name the GPX link's file is given; whether the draft is still kept."""
        row = self._row(draft_id)
        if row is None:
            return False
        row.data = {**row.data, "gpx_name": name}
        row.save(update_fields=["data"])
        return True


def _drafts_deleted(by_model: dict) -> int:
    return by_model.get(ConnectorDraft._meta.label, 0)


def drop_stale_drafts(now=None) -> int:
    """Delete every rider's drafts past `ConnectorDraft.KEPT`, and with them their links
    (SharedRoute.connector_draft); how many drafts."""
    now = now or timezone.now()
    _count, by_model = ConnectorDraft.objects.filter(
        created_at__lt=now - ConnectorDraft.KEPT
    ).delete()
    return _drafts_deleted(by_model)


# --- The MCP endpoint --------------------------------------------------------------------------


def grant_for(request) -> ConnectorGrant | None:
    """The live grant whose access token is the request's Bearer token, or None."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    grant = (
        ConnectorGrant.objects.select_related("user")
        .filter(access_digest=_digest(token.strip()), access_expires_at__gt=timezone.now())
        .first()
    )
    if grant is None or not grant.user.is_active:
        return None
    return grant


def _unauthorized(request):
    response = JsonResponse({"error": "sign in to RouteMaker to use this connector"}, status=401)
    response["WWW-Authenticate"] = (
        f'Bearer resource_metadata="{_origin(request)}/.well-known/oauth-protected-resource"'
    )
    return response


def _too_many(decision) -> JsonResponse:
    response = JsonResponse({"error": "too many requests; try again shortly"}, status=429)
    response["Retry-After"] = str(decision.retry_after_s)
    return response


@csrf_exempt
def mcp_endpoint(request):
    """POST /mcp: one JSON-RPC message in, its answer out. A rider's calls are counted against
    the rider (CONNECTOR_CALLS); only requests without a valid token are counted against the
    address, since every claude.ai rider arrives from the same few."""
    if request.method != "POST":
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response
    grant = grant_for(request)
    if grant is None:
        counted = ratelimit.hit(
            ratelimit.CONNECTOR_ADDRESS, ratelimit.client_key(ratelimit.client_address(request))
        )
        return _unauthorized(request) if counted.allowed else _too_many(counted)
    counted = ratelimit.hit(
        ratelimit.CONNECTOR_CALLS, ratelimit.client_key(rider_address(grant.user))
    )
    if not counted.allowed:
        return _too_many(counted)
    if len(request.body) > MAX_BODY_BYTES:
        return JsonResponse({"error": "request too large"}, status=413)
    module = mcp_module()
    try:
        message = json.loads(request.body)
    except ValueError:
        return JsonResponse(module._error(None, -32700, "parse error"), status=400)
    ConnectorGrant.objects.filter(pk=grant.pk).update(last_used_at=timezone.now())
    user = grant.user
    server = module.Server(
        lambda: InProcessApi(request, user),
        drafts=DatabaseDrafts(user, grant),
        files=False,
        gpx_link=lambda draft_id, name: gpx_link(request, user, grant, draft_id, name),
        posts=bool(getattr(user, "is_instance_admin", False)),
        icons=server_icons(request),
    )
    msg_id = message.get("id") if isinstance(message, dict) else None
    if msg_id is not None and (isinstance(msg_id, bool) or not isinstance(msg_id, (str, int))):
        return JsonResponse(module._error(None, -32600, "id: a string or a number"), status=400)
    calls = {}
    if msg_id is not None:
        calls[msg_id] = module.Call(deadline=time.monotonic() + CALL_BUDGET_S)
    try:
        answer = module.handle(server, message, send=lambda _note: None, calls=calls)
    except Exception as error:  # noqa: BLE001 - a bug is an answer, not the site's error page
        logger.exception("connector call failed")
        answer = module._error(msg_id, -32603, f"internal error: {type(error).__name__}")
    if answer is None:
        return HttpResponse(status=202)  # a notification: nothing to answer
    return _no_store(JsonResponse(answer))


mcp_endpoint.limits = ratelimit.CONNECTOR_CALLS


def server_icons(request) -> list[dict]:
    """The app's icons (frontend/public), as serverInfo names them. claude.ai's connector list
    does not read them yet: it shows the favicon Google's favicon service has for the domain
    (docs/OPERATIONS.md, "The connector's icon"). Other apps, and claude.ai later, may."""
    origin = _origin(request)
    return [
        {"src": f"{origin}/favicon.svg", "mimeType": "image/svg+xml", "sizes": ["any"]},
        {"src": f"{origin}/icons/icon-192.png", "mimeType": "image/png", "sizes": ["192x192"]},
        {"src": f"{origin}/icons/icon-512.png", "mimeType": "image/png", "sizes": ["512x512"]},
    ]


# --- A draft's GPX ------------------------------------------------------------------------------

GPX_SALT = "core.connector.gpx"
# The draft's id, then the keyed digest (`_gpx_mac`).
GPX_TOKEN_RE = re.compile(r"(d[0-9a-f]{32})\.([0-9a-f]{64})")


def _gpx_mac(user_id, grant_id, draft_id: str) -> str:
    message = f"{user_id}:{grant_id}:{draft_id}"
    return salted_hmac(GPX_SALT, message, algorithm="sha256").hexdigest()


def gpx_link(request, user, grant, draft_id: str, name: str) -> str:
    """A link that downloads the rider's draft as GPX, good while the draft is kept (a day) and
    the app that drafted it is connected. Garmin and Wahoo never fetch it (the server sends them
    the route itself: core.garmin_courses, core.wahoo_routes). A person opens it from the
    assistant app, on any device and often in that app's own browser, signed in to nothing
    here, so it carries no sign-in of its own. It is the draft's random id and a keyed digest
    (SECRET_KEY) of that id with the rider and the app: nothing in it can be read, and it opens
    that one file and nothing else. The file's name is kept on the draft, not in the link."""
    if not DatabaseDrafts(user, grant).name_gpx(draft_id, name):
        raise mcp_module().ToolError(
            f"no draft {draft_id} (drafts last only a while; plan it again)"
        )
    return f"{_origin(request)}/mcp/gpx/{draft_id}.{_gpx_mac(user.pk, grant.pk, draft_id)}"


def _gpx_gone():
    return _page("This link has expired", format_html("<p>{}</p>", GPX_GONE), status=404)


@ratelimit.rate_limited(ratelimit.SHARED_ROUTE_READS)
def draft_gpx(request, token: str):
    """GET /mcp/gpx/<token>: the draft as a .gpx download, while the draft is kept."""
    if request.method != "GET":
        return HttpResponse(status=405, headers={"Allow": "GET"})
    found = GPX_TOKEN_RE.fullmatch(token)
    if found is None:
        return _gpx_gone()
    draft_id, mac = found.groups()
    row = (
        ConnectorDraft.objects.select_related("user")
        .filter(
            draft_id=draft_id,
            grant__isnull=False,
            created_at__gte=timezone.now() - ConnectorDraft.KEPT,
        )
        .first()
    )
    if (
        row is None
        or not row.user.is_active
        or not constant_time_compare(mac, _gpx_mac(row.user_id, row.grant_id, draft_id))
        # Disconnecting the app drops its drafts; this holds even where a draft was left behind.
        or not ConnectorGrant.objects.filter(pk=row.grant_id, user_id=row.user_id).exists()
    ):
        return _gpx_gone()
    draft = DatabaseDrafts(row.user, row.grant_id).get(draft_id)
    if draft is None:
        return _gpx_gone()
    module = mcp_module()
    name = str(row.data.get("gpx_name") or draft.name)[:120]
    response = HttpResponse(
        module.gpx_text(name, draft.plan.line), content_type="application/gpx+xml"
    )
    response["Content-Disposition"] = f'attachment; filename="{module.gpx_slug(name)}.gpx"'
    response["X-Content-Type-Options"] = "nosniff"
    return _no_store(response)


GPX_GONE = "The route is no longer kept. Ask the assistant to plan it again for a new link."


# --- OAuth: discovery ---------------------------------------------------------------------------


@ratelimit.rate_limited(ratelimit.CONNECTOR_ADDRESS)
def protected_resource(request):
    """RFC 9728: where this resource's sign-in is."""
    origin = _origin(request)
    return JsonResponse(
        {
            "resource": f"{origin}/mcp",
            "authorization_servers": [origin],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "RouteMaker",
        }
    )


@ratelimit.rate_limited(ratelimit.CONNECTOR_ADDRESS)
def authorization_server(request):
    """RFC 8414: the sign-in's endpoints."""
    origin = _origin(request)
    return JsonResponse(
        {
            "issuer": origin,
            "authorization_endpoint": f"{origin}/oauth/authorize",
            "token_endpoint": f"{origin}/oauth/token",
            "registration_endpoint": f"{origin}/oauth/register",
            "scopes_supported": [SCOPE],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "authorization_response_iss_parameter_supported": True,
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        }
    )


# --- OAuth: registration ------------------------------------------------------------------------


def redirect_uri_allowed(uri: str) -> bool:
    """An https address, or an app on the rider's own computer (http to localhost), with no
    fragment and no user name in it."""
    try:
        parts = urllib.parse.urlsplit(uri)
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not parts.hostname:
        return False
    if not re.fullmatch(r"[A-Za-z0-9.-]+|[0-9A-Fa-f:]+", parts.hostname):
        return False  # no spaces, ";" or "," that could reach the consent page's CSP
    try:
        parts.port  # noqa: B018 - raises on a port that is not a number
    except ValueError:
        return False
    if len(uri) > 500:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")


def _oauth_error(error: str, description: str, status: int = 400):
    return _no_store(
        JsonResponse({"error": error, "error_description": description}, status=status)
    )


def _registered(client: ConnectorClient, method: str) -> dict:
    return {
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "client_name": client.name,
        "redirect_uris": client.redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
        "scope": SCOPE,
    }


@csrf_exempt
@ratelimit.rate_limited(ratelimit.CONNECTOR_REGISTER)
def register(request):
    """POST /oauth/register (RFC 7591): an assistant app introduces itself."""
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    if len(request.body) > 8 * 1024:
        return _oauth_error("invalid_client_metadata", "too large")
    try:
        body = json.loads(request.body)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _oauth_error("invalid_client_metadata", "send the app's details as a JSON object")
    uris = body.get("redirect_uris")
    if (
        not isinstance(uris, list)
        or not 1 <= len(uris) <= MAX_REDIRECT_URIS
        or not all(isinstance(u, str) and redirect_uri_allowed(u) for u in uris)
    ):
        return _oauth_error(
            "invalid_redirect_uri", "redirect_uris: 1 to 5 https (or http://localhost) addresses"
        )
    name = body.get("client_name")
    name = name.strip()[:120] if isinstance(name, str) else ""
    method = body.get("token_endpoint_auth_method") or "none"
    if method not in ("none", "client_secret_post"):
        return _oauth_error("invalid_client_metadata", "token_endpoint_auth_method: none")
    if method == "none":
        # Every rider who adds the connector registers the same app: one row serves them all.
        same = ConnectorClient.objects.filter(
            name=name, redirect_uris=uris, secret_digest=""
        ).first()
        if same is not None:
            return _no_store(JsonResponse(_registered(same, method), status=201))
    client_id = "rmc_" + secrets.token_urlsafe(24)
    secret = "rmcs_" + secrets.token_urlsafe(32) if method == "client_secret_post" else ""
    client = ConnectorClient.objects.create(
        client_id=client_id,
        name=name,
        redirect_uris=uris,
        secret_digest=_digest(secret) if secret else "",
    )
    out = _registered(client, method)
    if secret:
        out["client_secret"] = secret
        out["client_secret_expires_at"] = 0
    return _no_store(JsonResponse(out, status=201))


# --- OAuth: the rider's consent -----------------------------------------------------------------

AUTHORIZE_FIELDS = ("client_id", "redirect_uri", "state", "code_challenge", "scope", "resource")


def _redirect_with(uri: str, **params) -> HttpResponseRedirect:
    parts = urllib.parse.urlsplit(uri)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query += [(k, v) for k, v in params.items() if v]
    response = HttpResponseRedirect(
        urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    )
    response.allowed_schemes = ["http", "https"]
    return response


def _page(title: str, body, status: int = 200, form_to: str = "") -> HttpResponse:
    """A plain page of this site's, readable without the app's scripts."""
    html = format_html(
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{} - RouteMaker</title>
<style>
body {{ font: 18px/1.5 system-ui, sans-serif; margin: 0 auto; max-width: 34rem;
  padding: 1.5rem 1rem; color: #1a1a1a; background: #fff; }}
h1 {{ font-size: 1.5rem; margin-top: 0; }}
ul {{ padding-left: 1.25rem; }}
.actions {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-top: 1.5rem; }}
button {{ font: inherit; min-height: 44px; min-width: 44px; padding: 0.5rem 1.25rem;
  border-radius: 6px; border: 2px solid #1a1a1a; background: #fff; color: #1a1a1a; }}
button.allow {{ background: #1a1a1a; color: #fff; }}
button:focus-visible {{ outline: 3px solid #0b57d0; outline-offset: 2px; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #121212; color: #eee; }}
  button {{ background: #121212; color: #eee; border-color: #eee; }}
  button.allow {{ background: #eee; color: #121212; }}
  button:focus-visible {{ outline-color: #8ab4f8; }}
}}
</style>
</head>
<body>
<main>
<h1>{}</h1>
{}
</main>
</body>
</html>""",
        title,
        title,
        body,
    )
    response = HttpResponse(html, status=status)
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none';"
        f" form-action 'self'{(' ' + form_to) if form_to else ''}"
    )
    response["X-Frame-Options"] = "DENY"
    # Not no-referrer: a form posted from such a page sends "Origin: null", which Django's CSRF
    # check refuses. same-origin is the site's own policy.
    response["Referrer-Policy"] = "same-origin"
    return _no_store(response)


def _refusal(message: str) -> HttpResponse:
    return _page("This sign-in can't go ahead", format_html("<p>{}</p>", message), status=400)


def _checked_authorize(request, params):
    """The app and its return address, or a page saying why not. Nothing is sent back to an
    address that is not the app's own."""
    client = ConnectorClient.objects.filter(client_id=params.get("client_id") or "").first()
    if client is None:
        return None, _refusal("The assistant app is not known here. Add the connector again.")
    redirect_uri = params.get("redirect_uri") or ""
    if redirect_uri not in client.redirect_uris:
        return None, _refusal("The assistant app gave a return address it did not register.")
    # These are answered on a page of this site, not by sending the browser on: anyone can
    # register an app, so a redirect here would make the site an open redirect (RFC 9700 4.11.2).
    if params.get("response_type", "code") != "code":
        return None, _refusal("The assistant app asked for a kind of sign-in this site doesn't do.")
    challenge = params.get("code_challenge") or ""
    if params.get("code_challenge_method") != "S256" or not 43 <= len(challenge) <= 128:
        return None, _refusal("The assistant app's sign-in is missing its PKCE check (S256).")
    resource = params.get("resource")
    if resource and resource.rstrip("/") != f"{_origin(request)}/mcp":
        return None, _refusal("The assistant app asked to use something other than RouteMaker.")
    return client, None


@ratelimit.rate_limited(ratelimit.CONNECTOR_ADDRESS)
def authorize(request):
    """GET: the consent page (signing in first if needed). POST: the rider's answer."""
    params = request.GET if request.method == "GET" else request.POST
    client, refusal = _checked_authorize(request, params)
    if refusal is not None:
        return refusal
    redirect_uri = params["redirect_uri"]
    user = request.user
    if not user.is_authenticated or not user.is_active:
        if request.method != "GET":
            return _refusal("You are signed out. Start again from the assistant app.")
        return HttpResponseRedirect(
            "/auth/login?" + urllib.parse.urlencode({"next": request.get_full_path()})
        )
    if request.method == "POST":
        if request.POST.get("answer") != "allow":
            return _redirect_with(redirect_uri, error="access_denied", state=params.get("state"))
        code = secrets.token_urlsafe(32)
        ConnectorGrant.objects.create(
            user=user,
            client=client,
            redirect_uri=redirect_uri,
            code_digest=_digest(code),
            code_challenge=params["code_challenge"],
            code_expires_at=timezone.now() + CODE_LIFETIME,
        )
        return _redirect_with(
            redirect_uri, code=code, state=params.get("state"), iss=_origin(request)
        )
    if request.method != "GET":
        return HttpResponse(status=405, headers={"Allow": "GET, POST"})
    from django.middleware.csrf import get_token

    target = urllib.parse.urlsplit(redirect_uri)
    hidden = format_html_join(
        "\n",
        '<input type="hidden" name="{}" value="{}">',
        (
            (name, params.get(name))
            for name in (*AUTHORIZE_FIELDS, "code_challenge_method", "response_type")
            if params.get(name)
        ),
    )
    body = format_html(
        """<p><strong>{app}</strong> is asking to use RouteMaker for you.
If you allow it, it can:</p>
<ul>
<li>plan routes with RouteMaker's routing, each with a link to it that lasts a day</li>
<li>add routes to your My routes, when you ask it to</li>
{posts}</ul>
<p>It can't read your saved routes, sign in to the site as you, or change anything else.</p>
<p>After you answer you'll go back to <strong>{host}</strong>.</p>
<form method="post" action="/oauth/authorize">
<input type="hidden" name="csrfmiddlewaretoken" value="{csrf}">
{hidden}
<div class="actions">
<button type="submit" name="answer" value="allow" class="allow">Allow</button>
<button type="submit" name="answer" value="deny">Don't allow</button>
</div>
</form>""",
        app=client.name or "An assistant app",
        posts=mark_safe(
            "<li>write Featured routes posts as drafts, for you to publish in the admin</li>\n"
        )
        if getattr(user, "is_instance_admin", False)
        else "",
        host=target.hostname,
        csrf=get_token(request),
        hidden=hidden,
    )
    return _page(
        f"Allow {client.name or 'this assistant app'} to plan routes?",
        body,
        form_to=f"{target.scheme}://{target.netloc}",
    )


# --- OAuth: tokens ------------------------------------------------------------------------------


def _client_from(request) -> ConnectorClient | None:
    client = ConnectorClient.objects.filter(client_id=request.POST.get("client_id") or "").first()
    if client is None:
        return None
    if client.secret_digest:
        secret = request.POST.get("client_secret") or ""
        if not secrets.compare_digest(_digest(secret), client.secret_digest):
            return None
    return client


def _issue(grant: ConnectorGrant) -> JsonResponse:
    access = "rma_" + secrets.token_urlsafe(32)
    refresh = "rmr_" + secrets.token_urlsafe(32)
    now = timezone.now()
    grant.access_digest = _digest(access)
    grant.access_expires_at = now + ACCESS_LIFETIME
    grant.refresh_digest = _digest(refresh)
    grant.refresh_expires_at = now + REFRESH_LIFETIME
    grant.save(
        update_fields=[
            "access_digest",
            "access_expires_at",
            "refresh_digest",
            "refresh_expires_at",
            "code_digest",
            "code_expires_at",
            "spent_code_digest",
            "previous_refresh_digest",
        ]
    )
    return _no_store(
        JsonResponse(
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": int(ACCESS_LIFETIME.total_seconds()),
                "refresh_token": refresh,
                "scope": SCOPE,
            }
        )
    )


def _pkce_matches(verifier: str, challenge: str) -> bool:
    if not 43 <= len(verifier) <= 128:
        return False
    made = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return secrets.compare_digest(made.decode(), challenge)


@csrf_exempt
@ratelimit.rate_limited(ratelimit.CONNECTOR_ADDRESS)
def token(request):
    """POST /oauth/token: a code (with its PKCE verifier) or a refresh token for new tokens."""
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    client = _client_from(request)
    if client is None:
        return _oauth_error("invalid_client", "unknown app, or a wrong secret", status=401)
    kind = request.POST.get("grant_type")
    now = timezone.now()
    with transaction.atomic():
        if kind == "authorization_code":
            digest = _digest(request.POST.get("code") or "")
            grant = (
                ConnectorGrant.objects.select_for_update(of=("self",))
                .select_related("user")
                .filter(code_digest=digest, client=client)
                .first()
            )
            if grant is None:
                # A code traded once and seen again: someone else has a copy, so the tokens
                # it bought stop working too.
                ConnectorGrant.objects.filter(spent_code_digest=digest, client=client).delete()
                return _oauth_error("invalid_grant", "the code is not valid, or was used")
            # Whatever happens next, the code is spent: a wrong guess does not get another.
            grant.code_digest = None
            grant.spent_code_digest = digest
            fresh = grant.code_expires_at is not None and grant.code_expires_at > now
            grant.code_expires_at = None
            if not fresh:
                grant.delete()
                return _oauth_error("invalid_grant", "the code is not valid, or was used")
            refused = None
            if request.POST.get("redirect_uri") != grant.redirect_uri:
                refused = "the return address does not match"
            elif not _pkce_matches(request.POST.get("code_verifier") or "", grant.code_challenge):
                refused = "the code verifier does not match"
            elif not grant.user.is_active:
                refused = "the account can no longer sign in"
            if refused:
                grant.delete()
                return _oauth_error("invalid_grant", refused)
            return _issue(grant)
        if kind == "refresh_token":
            digest = _digest(request.POST.get("refresh_token") or "")
            grant = (
                ConnectorGrant.objects.select_for_update(of=("self",))
                .select_related("user")
                .filter(refresh_digest=digest, client=client, refresh_expires_at__gt=now)
                .first()
            )
            if grant is None:
                # An old refresh token used again after it was rotated: end the grant.
                ConnectorGrant.objects.filter(
                    previous_refresh_digest=digest, client=client
                ).delete()
                return _oauth_error("invalid_grant", "the refresh token is not valid")
            if not grant.user.is_active:
                return _oauth_error("invalid_grant", "the refresh token is not valid")
            grant.previous_refresh_digest = digest
            return _issue(grant)  # a new refresh token each time; the old one stops working
    return _oauth_error("unsupported_grant_type", "authorization_code or refresh_token")


# --- Clearing up -------------------------------------------------------------------------------


def sweep_connector() -> int:
    """Delete what will never be used again (the membership sweep's backstop): drafts past their
    day, with their links, grants whose code expired untraded or whose refresh token expired, and
    apps a day old with no grant left. Drafts hold route points, often a rider's home, so the
    five-minute sweep drops stale ones as well (`drop_stale_drafts`)."""
    now = timezone.now()
    drafts = drop_stale_drafts(now)
    untraded, _ = ConnectorGrant.objects.filter(
        refresh_digest__isnull=True, created_at__lt=now - CODE_LIFETIME - timedelta(hours=1)
    ).delete()
    lapsed, _ = ConnectorGrant.objects.filter(refresh_expires_at__lt=now).delete()
    apps, _ = ConnectorClient.objects.filter(
        grants__isnull=True, created_at__lt=now - timedelta(days=1)
    ).delete()
    return drafts + untraded + lapsed + apps
