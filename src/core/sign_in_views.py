"""Sign in with Discord, Google or Apple, and link them to one account.

Stephen 2026-11-13: "Yes, and
allow account linking").

- GET /auth/sign-in: the choice of sign-ins this server has keys for. With only Discord's, straight
  to it, as before. Google is left out inside the Android app: Google refuses its sign-in in an
  app's built-in browser (a WebView says "; wv)" in its user agent), and a rider there signs in
  with Discord or Apple.
- GET /auth/google/start, /auth/apple/start, and their /callback: OpenID Connect, `openid` alone
  (core.oidc_login). With `link=1` from a signed-in rider, the sign-in is added to that account
  instead.
- GET /auth/sign-ins: Settings > Account's "Sign-in methods": what is linked, Link and Unlink.
- POST /auth/unlink: takes one off; an account always keeps at least one.

Discord's own flow stays in core.auth_views (its `link=1` lands here too). Nothing but the keyed
subject is kept: no name, email or token.
"""

from __future__ import annotations

import re
from html import escape

from django.conf import settings
from django.contrib.auth import login as django_login
from django.http import HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from . import oidc_login, ratelimit
from .auth_views import PENDING_SESSION_S, issue_session, safe_redirect_target, sign_in_available
from .discord_oauth import LoginRequest, OAuthStateError, verify_state
from .models import CachedMembership, SignInIdentity, User

PENDING_KEY = "oidc_login_request"
SIGN_INS_PATH = "/auth/sign-ins"
ANDROID_WEBVIEW = re.compile(r"; wv\)")

TITLE = "Sign in to RouteMaker"
WHY = (
    "Sign in to save routes and sync settings across devices. RouteMaker keeps only an account"
    " number from the service you pick: no name, email or password."
)
TAKEN = (
    "That {name} sign-in is already linked to another RouteMaker account. Sign in with it and"
    " unlink it there first."
)
HAS_ONE = "This account already has a {name} sign-in. Unlink it first to link a different one."
NOT_ALLOWED = "This account is not permitted to sign in."
LAST_ONE = "An account keeps at least one sign-in, so this one can't be unlinked."
CANCELLED = "Sign-in was cancelled or did not finish. Nothing was changed."


def available(provider: str) -> bool:
    """Whether this server has the keys for `provider`."""
    if provider == "discord":
        return sign_in_available()
    if provider == "google":
        return all(
            str(v or "").strip()
            for v in (
                settings.GOOGLE_CLIENT_ID,
                settings.GOOGLE_CLIENT_SECRET,
                settings.GOOGLE_REDIRECT_URI,
            )
        )
    if provider == "apple":
        return all(
            str(v or "").strip()
            for v in (
                settings.APPLE_CLIENT_ID,
                settings.APPLE_TEAM_ID,
                settings.APPLE_KEY_ID,
                settings.APPLE_PRIVATE_KEY,
                settings.APPLE_REDIRECT_URI,
            )
        )
    return False


def offered(request) -> list[str]:
    """The sign-ins to show this browser, in order: those with keys, less Google inside the Android
    app.
    """
    in_webview = bool(ANDROID_WEBVIEW.search(request.META.get("HTTP_USER_AGENT", "")))
    return [
        p
        for p in ("discord", "google", "apple")
        if available(p) and not (p == "google" and in_webview)
    ]


def linked(user) -> list[str]:
    """The sign-ins on `user`'s account, in the same order."""
    have = set(SignInIdentity.objects.filter(user=user).values_list("provider", flat=True))
    return [
        p
        for p in ("discord", "google", "apple")
        if (p == "discord" and user.discord_user_id is not None) or p in have
    ]


def _signed_in(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user is not None and user.is_authenticated and getattr(user, "is_active", False))


def start_url(provider: str, next_url: str = "/", link: bool = False) -> str:
    from urllib.parse import urlencode

    path = "/auth/login" if provider == "discord" else f"/auth/{provider}/start"
    query = {"next": next_url} if next_url and next_url != "/" else {}
    if provider == "discord" and not link:
        query["pick"] = "discord"
    if link:
        query["link"] = "1"
    return f"{path}?{urlencode(query)}" if query else path


def _page(body: str, status: int = 200, title: str = TITLE) -> HttpResponse:
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        '<meta name="robots" content="noindex">'
        "<style>"
        "body{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:0 auto;padding:1rem;"
        "color:#1a1a1a;background:#fff}"
        "@media (prefers-color-scheme:dark){body{color:#eee;background:#121212}a{color:#8cf}}"
        "h1{font-size:1.5rem}"
        ".choices{list-style:none;padding:0;display:grid;gap:.75rem}"
        ".choices a,.choices button{display:flex;align-items:center;justify-content:center;"
        "min-height:48px;font:inherit;font-weight:600;border-radius:8px;"
        "border:2px solid currentColor;padding:.5rem 1rem;"
        "text-decoration:none;color:inherit;background:none;cursor:pointer;width:100%}"
        ".row{display:flex;justify-content:space-between;align-items:center;gap:1rem}"
        ".row form,.row a{flex:none;width:auto}"
        ".note{font-weight:600}"
        "</style></head><body><main>"
        f"<h1>{escape(title)}</h1>{body}"
        '<p><a href="/">Back to RouteMaker</a></p>'
        "</main></body></html>"
    )
    response = HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex"
    response["Vary"] = "Cookie"
    return response


def _note(text: str, status: int) -> HttpResponse:
    return _page(f'<p class="note" role="alert">{escape(text)}</p>', status=status)


@require_http_methods(["GET"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
def choose(request):
    """The sign-in choice. One sign-in set up: straight to it. None: the same 503 as Discord's."""
    next_url = safe_redirect_target(request, request.GET.get("next"))
    choices = offered(request)
    if not choices:
        from .auth_views import SIGN_IN_OFF

        return HttpResponse(SIGN_IN_OFF, status=503, content_type="text/plain; charset=utf-8")
    if len(choices) == 1:
        return HttpResponseRedirect(start_url(choices[0], next_url))
    items = "".join(
        f'<li><a href="{escape(start_url(p, next_url))}">'
        f"Sign in with {escape(oidc_login.NAMES[p])}</a></li>"
        for p in choices
    )
    return _page(f'<p>{escape(WHY)}</p><ul class="choices">{items}</ul>')


@require_http_methods(["GET"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
def provider_start(request, provider: str):
    if provider not in oidc_login.PROVIDERS or not available(provider):
        return _note(
            f"{oidc_login.NAMES.get(provider, 'This')} sign-in is not set up on this server.", 503
        )
    state = oidc_login.new_state()
    link = request.GET.get("link") == "1" and _signed_in(request)
    request.session[PENDING_KEY] = {
        "provider": provider,
        "state": state,
        "issued_at": timezone.now().isoformat(),
        "redirect_after": SIGN_INS_PATH
        if link
        else safe_redirect_target(request, request.GET.get("next")),
        "link_user": request.user.pk if link else None,
    }
    if not _signed_in(request):
        request.session.set_expiry(PENDING_SESSION_S)
    client_id = settings.GOOGLE_CLIENT_ID if provider == "google" else settings.APPLE_CLIENT_ID
    redirect_uri = (
        settings.GOOGLE_REDIRECT_URI if provider == "google" else settings.APPLE_REDIRECT_URI
    )
    return HttpResponseRedirect(
        oidc_login.authorize_url(oidc_login.BY_NAME[provider], client_id, redirect_uri, state)
    )


def exchange_subject(provider: str, code: str) -> str:
    """The account's subject for this code (the tests replace this; nothing else here calls out)."""
    if provider == "google":
        return oidc_login.exchange(
            oidc_login.GOOGLE,
            code,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
        )
    secret = oidc_login.apple_client_secret(
        settings.APPLE_TEAM_ID,
        settings.APPLE_CLIENT_ID,
        settings.APPLE_KEY_ID,
        settings.APPLE_PRIVATE_KEY,
    )
    return oidc_login.exchange(
        oidc_login.APPLE,
        code,
        client_id=settings.APPLE_CLIENT_ID,
        client_secret=secret,
        redirect_uri=settings.APPLE_REDIRECT_URI,
    )


def sign_in_as(request, user) -> None:
    """Sign `user` in on this browser, as the Discord callback does."""
    django_login(request, user, backend="core.auth_backend.DiscordStandingBackend")
    request.session.set_expiry(None)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    issue_session(request, user)


@require_http_methods(["GET"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
def provider_callback(request, provider: str):
    if provider not in oidc_login.PROVIDERS or not available(provider):
        return _note(
            f"{oidc_login.NAMES.get(provider, 'This')} sign-in is not set up on this server.", 503
        )
    stored = request.session.pop(PENDING_KEY, None)
    if not stored or stored.get("provider") != provider:
        return _note(CANCELLED, 400)
    try:
        verify_state(
            LoginRequest(
                state=stored["state"],
                issued_at=timezone.datetime.fromisoformat(stored["issued_at"]),
            ),
            request.GET.get("state", ""),
            timezone.now(),
        )
    except (OAuthStateError, KeyError, ValueError):
        return _note(CANCELLED, 400)
    code = request.GET.get("code", "")
    if not code:
        return _note(CANCELLED, 400)
    try:
        subject = exchange_subject(provider, code)
    except oidc_login.ExchangeFailed:
        return _note(CANCELLED, 400)
    key = oidc_login.subject_key(provider, subject, settings.TOMBSTONE_KEY)
    found = (
        SignInIdentity.objects.filter(provider=provider, subject_key=key)
        .select_related("user")
        .first()
    )
    name = oidc_login.NAMES[provider]

    if stored.get("link_user") is not None:
        if not _signed_in(request) or request.user.pk != stored["link_user"]:
            return _note(CANCELLED, 400)
        if found and found.user_id != request.user.pk:
            return _note(TAKEN.format(name=name), 409)
        if not found:
            if SignInIdentity.objects.filter(user=request.user, provider=provider).exists():
                return _note(HAS_ONE.format(name=name), 409)
            SignInIdentity.objects.create(user=request.user, provider=provider, subject_key=key)
        return HttpResponseRedirect(SIGN_INS_PATH)

    if found:
        user = found.user
    else:
        user = User.objects.create(discord_user_id=None)
        SignInIdentity.objects.create(user=user, provider=provider, subject_key=key)
    if user.is_banned or user.is_deleted:
        return _note(NOT_ALLOWED, 403)
    sign_in_as(request, user)
    return HttpResponseRedirect(safe_redirect_target(request, stored.get("redirect_after", "/")))


def link_discord(request, discord_user_id: int) -> HttpResponse:
    """The Discord callback's half for `link=1`: add this Discord account to the signed-in
    account."""
    from .models import BanTombstone
    from .revocation import tombstone

    if BanTombstone.objects.filter(
        tombstone=tombstone(discord_user_id, settings.TOMBSTONE_KEY)
    ).exists():
        return _note(NOT_ALLOWED, 403)
    other = User.objects.filter(discord_user_id=discord_user_id).exclude(pk=request.user.pk).first()
    if other is not None:
        return _note(TAKEN.format(name="Discord"), 409)
    if request.user.discord_user_id not in (None, discord_user_id):
        return _note(HAS_ONE.format(name="Discord"), 409)
    request.user.discord_user_id = discord_user_id
    request.user.save(update_fields=["discord_user_id"])
    return HttpResponseRedirect(SIGN_INS_PATH)


@require_http_methods(["GET"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
@csrf_protect
def sign_ins(request):
    """Settings > Account's "Sign-in methods": each sign-in, linked or not, with Link or Unlink."""
    if not _signed_in(request):
        return HttpResponseRedirect(
            start_url("discord", SIGN_INS_PATH)
            if len(offered(request)) <= 1
            else f"/auth/sign-in?next={SIGN_INS_PATH}"
        )
    have = linked(request.user)
    rows = []
    for provider in ("discord", "google", "apple"):
        name = escape(oidc_login.NAMES[provider])
        if provider in have:
            action = (
                f'<form method="post" action="/auth/unlink">'
                '<input type="hidden" name="csrfmiddlewaretoken" '
                f'value="{escape(get_token(request))}">'
                f'<input type="hidden" name="provider" value="{provider}">'
                f'<button type="submit" aria-label="Unlink {name}">Unlink</button></form>'
                if len(have) > 1
                else ""
            )
            rows.append(f'<li class="row"><span>{name}: linked</span>{action}</li>')
        elif provider in offered(request):
            rows.append(
                f'<li class="row"><span>{name}: not linked</span>'
                f'<a href="{escape(start_url(provider, link=True))}" '
                f'aria-label="Link {name}">Link</a></li>'
            )
    body = (
        "<p>Sign in with any of these to reach the same account. It keeps at least one.</p>"
        f'<ul class="choices">{"".join(rows)}</ul>'
    )
    return _page(body, title="Sign-in methods")


@require_http_methods(["POST"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
@csrf_protect
def unlink(request):
    if not _signed_in(request):
        return HttpResponseRedirect("/")
    provider = request.POST.get("provider", "")
    have = linked(request.user)
    if provider not in have:
        return HttpResponseRedirect(SIGN_INS_PATH)
    if len(have) <= 1:
        return _note(LAST_ONE, 409)
    if provider == "discord":
        # Its cached guild standing goes with it: standing comes from the Discord account.
        CachedMembership.objects.filter(discord_user_id=request.user.discord_user_id).delete()
        request.user.discord_user_id = None
        request.user.save(update_fields=["discord_user_id"])
    else:
        SignInIdentity.objects.filter(user=request.user, provider=provider).delete()
    return HttpResponseRedirect(SIGN_INS_PATH)
