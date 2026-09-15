"""The Discord login flow, as views.

`discord_oauth` holds the protocol logic and no Django. This is the half that
touches the request: it stores the state against the session, exchanges the code
once, and mints the application's own session row.

Minting that row is the point. The epoch middleware rejects any request whose
session has no row, so before this existed a person could not have stayed signed
in even if a login had been reachable - and no login was, since nothing routed to
the callback at all.

No Discord token is retained. The exchange yields a user id and the access and
refresh tokens are discarded rather than stored, so there is no per-user
third-party credential anywhere in this deployment: nothing to encrypt, refresh,
leak, or revoke on deletion.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.http import HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .discord_oauth import LoginRequest, OAuthStateError, begin_login, scopes_are_minimal
from .models import BanTombstone, Session, User
from .revocation import tombstone

STATE_SESSION_KEY = "discord_login_request"
DEFAULT_REDIRECT = "/"
USER_URL = "https://discord.com/api/users/@me"
TOKEN_URL = "https://discord.com/api/oauth2/token"


class LoginRefused(RuntimeError):
    """The login cannot proceed, for a reason the person may be told."""


def safe_redirect_target(candidate, request) -> str:
    """Reduce a `next=` to something that can only land on this deployment.

    Checked on the way in *and* on the way out. Storing it in the session is not
    a trust boundary: the session is attacker-influenced here, because a login
    can be started with any `next=` before the person ever authenticates. So the
    value is re-checked when it is finally used rather than trusted because it
    came back out of the session we put it in.
    """
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host(), *settings.ALLOWED_HOSTS},
        require_https=request.is_secure(),
    ):
        return candidate
    return DEFAULT_REDIRECT


@require_http_methods(["GET"])
def login_start(request):
    url, pending = begin_login(
        client_id=settings.DISCORD_CLIENT_ID,
        redirect_uri=settings.DISCORD_REDIRECT_URI,
        now=timezone.now(),
        redirect_after=safe_redirect_target(request.GET.get("next"), request),
    )
    request.session[STATE_SESSION_KEY] = {
        "state": pending.state,
        "issued_at": pending.issued_at.isoformat(),
        "redirect_after": pending.redirect_after,
    }
    return HttpResponseRedirect(url)


@require_http_methods(["GET"])
def login_callback(request, exchange=None):
    """Complete the login. `exchange` is injected so the tests never call out."""
    stored = request.session.pop(STATE_SESSION_KEY, None)
    pending = (
        LoginRequest(
            state=stored["state"],
            issued_at=timezone.datetime.fromisoformat(stored["issued_at"]),
            redirect_after=stored.get("redirect_after", "/"),
        )
        if stored
        else None
    )

    try:
        from .discord_oauth import verify_state

        pending = verify_state(pending, request.GET.get("state", ""), timezone.now())
    except OAuthStateError as error:
        return HttpResponseBadRequest(str(error))

    code = request.GET.get("code", "")
    if not code:
        return HttpResponseBadRequest("no authorization code")

    try:
        discord_user_id, granted_scopes = (exchange or exchange_code)(code)
    except LoginRefused as error:
        return HttpResponseBadRequest(str(error))

    # A grant carrying more than identify means the authorize URL was tampered
    # with or the application's configuration drifted. The extra scope is not
    # used, and its presence is worth refusing rather than ignoring.
    if not scopes_are_minimal(granted_scopes):
        return HttpResponseForbidden("the grant carried more than the identify scope")

    if BanTombstone.objects.filter(
        tombstone=tombstone(discord_user_id, settings.TOMBSTONE_KEY)
    ).exists():
        # Enforced before the account is created, so a deleted-then-returning
        # banned account does not get a fresh row and a fresh start.
        return HttpResponseForbidden("this account is not permitted to sign in")

    user, _created = User.objects.get_or_create(discord_user_id=discord_user_id)
    if user.is_banned or user.is_deleted:
        return HttpResponseForbidden("this account is not permitted to sign in")

    django_login(request, user, backend="core.auth_backend.DiscordStandingBackend")
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    issue_session(request, user)
    return HttpResponseRedirect(safe_redirect_target(pending.redirect_after, request))


@require_http_methods(["POST"])
def logout_view(request):
    """Sign out of this session. Signing out everywhere bumps the epoch instead,
    which is a different action and belongs on the account page."""
    if request.session.session_key:
        Session.objects.filter(session_key=request.session.session_key).delete()
    django_logout(request)
    return HttpResponseRedirect("/")


def issue_session(request, user) -> Session:
    """Record the application's own session row, carrying the epoch.

    Django's session table has no user column, so nothing in it can enumerate one
    person's sessions and the only global lever is rotating the secret key, which
    signs everybody out. This row is what makes ban, suspension, deletion and
    sign-out-everywhere mean anything.
    """
    request.session.cycle_key()
    now = timezone.now()
    return Session.objects.create(
        session_key=request.session.session_key,
        user=user,
        issued_epoch=user.session_epoch,
        created_at=now,
        last_seen_at=now,
    )


def exchange_code(code: str) -> tuple[int, str]:
    """Exchange the authorization code for a user id, keeping nothing else."""
    body = urllib.parse.urlencode(
        {
            "client_id": settings.DISCORD_CLIENT_ID,
            "client_secret": settings.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
        }
    ).encode()
    try:
        with urllib.request.urlopen(  # noqa: S310 - a constant https endpoint
            urllib.request.Request(
                TOKEN_URL,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ),
            timeout=10,
        ) as response:
            token = json.load(response)
        with urllib.request.urlopen(  # noqa: S310 - a constant https endpoint
            urllib.request.Request(
                USER_URL, headers={"Authorization": f"Bearer {token['access_token']}"}
            ),
            timeout=10,
        ) as response:
            profile = json.load(response)
    except (urllib.error.URLError, KeyError, ValueError) as error:
        raise LoginRefused(f"the Discord exchange failed: {error}") from error

    # The tokens go no further than this function. Nothing returns them, nothing
    # stores them, and the only thing kept is the id.
    return int(profile["id"]), token.get("scope", "")
