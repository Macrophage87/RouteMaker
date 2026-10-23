"""Wahoo, as views and account actions (core.wahoo holds the protocol).

- GET /auth/wahoo/start: signed in only; keeps the state in the session and sends the rider to
  Wahoo's consent page.
- GET /auth/wahoo/callback: checks the state, exchanges the code once, reads the Wahoo user id,
  keeps the encrypted tokens (core.models.WahooLink) and sends the rider back to the app with
  `?wahoo=connected` (or `declined`, `failed`), which Settings reads to say what happened.

`disconnect` (Settings and account deletion) and `access_for` (sending a route) are the account
actions; the Settings endpoints are in core.api beside Garmin's.
"""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import ratelimit, wahoo

STATE_SESSION_KEY = "wahoo_connect_request"
BACK = "/?wahoo="
OFF = "Wahoo is not set up on this server."
# Account deletion removes at most this many of the rider's routes from Wahoo, one call each.
MAX_ROUTES_REMOVED = 100


def _signed_in(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user is not None and user.is_authenticated)


@require_http_methods(["GET"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
def connect_start(request):
    if not wahoo.offered():
        return HttpResponse(OFF, status=503, content_type="text/plain; charset=utf-8")
    if not _signed_in(request):
        return HttpResponseRedirect(BACK + "signin")
    url, pending = wahoo.begin(
        settings.WAHOO_CLIENT_ID, settings.WAHOO_REDIRECT_URI, timezone.now()
    )
    request.session[STATE_SESSION_KEY] = {
        "state": pending.state,
        "issued_at": pending.issued_at.isoformat(),
    }
    return HttpResponseRedirect(url)


@require_http_methods(["GET"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
def connect_callback(request, transport: wahoo.Transport | None = None):
    """Finish connecting. `transport` is injected so the tests never call Wahoo."""
    if not wahoo.offered():
        return HttpResponse(OFF, status=503, content_type="text/plain; charset=utf-8")
    stored = request.session.pop(STATE_SESSION_KEY, None)
    if not _signed_in(request):
        return HttpResponseRedirect(BACK + "signin")
    pending = (
        wahoo.Pending(state=stored["state"], issued_at=datetime.fromisoformat(stored["issued_at"]))
        if isinstance(stored, dict)
        else None
    )
    now = timezone.now()
    if not wahoo.state_matches(pending, request.GET.get("state", ""), now):
        return HttpResponseRedirect(BACK + "failed")
    code = request.GET.get("code", "")
    if not code:
        # Wahoo sends the rider back with `error=access_denied` and no code when they said no.
        return HttpResponseRedirect(BACK + "declined")
    transport = transport or wahoo.Transport()
    try:
        tokens = wahoo.exchange(code, now, transport)
        wahoo_user = wahoo.user_id(tokens.access, transport)
    except wahoo.WahooError:
        return HttpResponseRedirect(BACK + "failed")
    _keep(request.user, wahoo_user, tokens)
    return HttpResponseRedirect(BACK + "connected")


def _keep(user, wahoo_user: str, tokens: wahoo.Tokens) -> None:
    from .models import WahooLink

    # Routes sent before belong to the Wahoo account connected then: kept only for that one.
    same = WahooLink.objects.filter(user=user, wahoo_user_id=wahoo_user).exists()
    WahooLink.objects.update_or_create(
        user=user,
        defaults={
            **({} if same else {"routes": {}}),
            "wahoo_user_id": wahoo_user,
            "access_token": wahoo.seal(tokens.access, user.pk),
            "access_expires_at": tokens.access_expires_at,
            "refresh_token": wahoo.seal(tokens.refresh, user.pk),
        },
    )


def access_for(user, transport: wahoo.Transport | None = None, fresh: bool = False) -> str:
    """A live access token for the account, refreshed first when it is near its end (or always,
    with `fresh`: Wahoo refused the one kept). Raises NotConnected (the link is then gone) or
    WahooError (try again later)."""
    from .models import WahooLink

    now = timezone.now()
    with transaction.atomic():
        # Taken in turn per account, so two sends at once do not both spend the refresh token.
        link = WahooLink.objects.select_for_update().filter(user=user).first()
        if link is None:
            raise wahoo.NotConnected("Wahoo is not connected.")
        try:
            if not fresh and not wahoo.needs_refresh(link.access_expires_at, now):
                access = wahoo.unseal(link.access_token, user.pk)
            else:
                old = wahoo.unseal(link.refresh_token, user.pk)
                tokens = wahoo.refresh(old, now, transport or wahoo.Transport())
                link.access_token = wahoo.seal(tokens.access, user.pk)
                link.access_expires_at = tokens.access_expires_at
                link.refresh_token = wahoo.seal(tokens.refresh, user.pk)
                access = tokens.access
        except wahoo.NotConnected as error:
            # Deleted after the transaction: raising inside it would roll the delete back.
            ended = error
        else:
            ended = None
            link.last_used_at = now
            link.save()
    if ended is not None:
        WahooLink.objects.filter(user=user).delete()
        raise ended
    return access


def sent_route_ids(user) -> list:
    """The Wahoo routes this account sent through its current connection (WahooLink.routes)."""
    from .models import WahooLink

    link = WahooLink.objects.filter(user=user).first()
    return list((link.routes or {}).values()) if link else []


def remove_routes(access: str, route_ids: list, transport: wahoo.Transport) -> int:
    """Delete these routes from the rider's Wahoo library (account deletion), best effort: stops at
    the first call that does not reach Wahoo. Returns how many went."""
    removed = 0
    for route_id in route_ids[:MAX_ROUTES_REMOVED]:
        try:
            status, _ = transport.delete(f"{wahoo.ROUTES_URL}/{route_id}", access)
        except wahoo.WahooError:
            break
        removed += status in (200, 204)
    return removed


def disconnect(user, transport: wahoo.Transport | None = None) -> bool:
    """End the account's Wahoo connection: withdraw RouteMaker's access in Wahoo (best effort) and
    delete the link. The routes already sent stay in the rider's Wahoo app. True when there was
    a link."""
    from .models import WahooLink

    if not WahooLink.objects.filter(user=user).exists():
        return False
    transport = transport or wahoo.Transport()
    try:
        wahoo.revoke(access_for(user, transport), transport)
    except wahoo.WahooError:
        pass
    WahooLink.objects.filter(user=user).delete()
    return True
