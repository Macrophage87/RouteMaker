"""Garmin Connect, as views and account actions (core.garmin holds the protocol).

- GET /auth/garmin/start: signed in only; keeps the PKCE verifier and state in the session and sends
  the rider to Garmin's consent page.
- GET /auth/garmin/callback: checks the state, exchanges the code once, reads the Garmin user id,
  keeps the encrypted tokens (core.models.GarminLink) and sends the rider back to the app with
  `?garmin=connected` (or `declined`, `failed`), which Settings reads to say what happened.
- POST /garmin/deregistrations: Garmin's notice that riders disconnected in Garmin Connect;
  their links are deleted. It carries no secret, so the most a forged one can do is end a
  connection, which the rider makes again in one tap, and only for a Garmin user id the sender
  already knows (Garmin's are opaque).

`disconnect` (Settings and account deletion) and `access_for` (sending a course) are the account
actions; the Settings endpoints are in core.api beside the AI assistant key.
"""

from __future__ import annotations

import json
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import garmin, ratelimit

STATE_SESSION_KEY = "garmin_connect_request"
BACK = "/?garmin="
OFF = "Garmin is not set up on this server."
NOTICE_MAX_BYTES = 256 * 1024


def _signed_in(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user is not None and user.is_authenticated)


@require_http_methods(["GET"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
def connect_start(request):
    if not garmin.available():
        return HttpResponse(OFF, status=503, content_type="text/plain; charset=utf-8")
    if not _signed_in(request):
        return HttpResponseRedirect(BACK + "signin")
    url, pending = garmin.begin(
        settings.GARMIN_CLIENT_ID, settings.GARMIN_REDIRECT_URI, timezone.now()
    )
    request.session[STATE_SESSION_KEY] = {
        "state": pending.state,
        "verifier": pending.verifier,
        "issued_at": pending.issued_at.isoformat(),
    }
    return HttpResponseRedirect(url)


@require_http_methods(["GET"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
def connect_callback(request, transport: garmin.Transport | None = None):
    """Finish connecting. `transport` is injected so the tests never call Garmin."""
    if not garmin.available():
        return HttpResponse(OFF, status=503, content_type="text/plain; charset=utf-8")
    stored = request.session.pop(STATE_SESSION_KEY, None)
    if not _signed_in(request):
        return HttpResponseRedirect(BACK + "signin")
    pending = (
        garmin.Pending(
            state=stored["state"],
            verifier=stored["verifier"],
            issued_at=datetime.fromisoformat(stored["issued_at"]),
        )
        if isinstance(stored, dict)
        else None
    )
    now = timezone.now()
    if not garmin.state_matches(pending, request.GET.get("state", ""), now):
        return HttpResponseRedirect(BACK + "failed")
    code = request.GET.get("code", "")
    if not code:
        # Garmin sends the rider back without a code when they said no.
        return HttpResponseRedirect(BACK + "declined")
    transport = transport or garmin.Transport()
    try:
        tokens = garmin.exchange(code, pending.verifier, now, transport)
        garmin_user = garmin.user_id(tokens.access, transport)
    except garmin.GarminError:
        return HttpResponseRedirect(BACK + "failed")
    _keep(request.user, garmin_user, tokens)
    return HttpResponseRedirect(BACK + "connected")


def _keep(user, garmin_user: str, tokens: garmin.Tokens) -> None:
    from .models import GarminLink

    GarminLink.objects.update_or_create(
        user=user,
        defaults={
            "garmin_user_id": garmin_user,
            "access_token": garmin.seal(tokens.access, user.pk),
            "access_expires_at": tokens.access_expires_at,
            "refresh_token": garmin.seal(tokens.refresh, user.pk),
            "refresh_expires_at": tokens.refresh_expires_at,
        },
    )


def access_for(user, transport: garmin.Transport | None = None, fresh: bool = False) -> str:
    """A live access token for the account, refreshed first when it is near its end (or always,
    with `fresh`: Garmin refused the one kept). Raises NotConnected (the link is then gone) or
    GarminError (try again later)."""
    from .models import GarminLink

    now = timezone.now()
    with transaction.atomic():
        # Taken in turn per account: Garmin's refresh token is single-use, so two sends at once
        # must not both spend it.
        link = GarminLink.objects.select_for_update().filter(user=user).first()
        if link is None:
            raise garmin.NotConnected("Garmin is not connected.")
        try:
            if not fresh and not garmin.needs_refresh(link.access_expires_at, now):
                access = garmin.unseal(link.access_token, user.pk)
            else:
                old = garmin.unseal(link.refresh_token, user.pk)
                tokens = garmin.refresh(old, now, transport or garmin.Transport())
                link.access_token = garmin.seal(tokens.access, user.pk)
                link.access_expires_at = tokens.access_expires_at
                link.refresh_token = garmin.seal(tokens.refresh, user.pk)
                link.refresh_expires_at = tokens.refresh_expires_at
                access = tokens.access
        except garmin.NotConnected as error:
            # Deleted after the transaction: raising inside it would roll the delete back.
            ended = error
        else:
            ended = None
            link.last_used_at = now
            link.save()
    if ended is not None:
        GarminLink.objects.filter(user=user).delete()
        raise ended
    return access


def disconnect(user, transport: garmin.Transport | None = None) -> bool:
    """End the account's Garmin connection: tell Garmin (best effort) and delete the link. True
    when there was one."""
    from .models import GarminLink

    if not GarminLink.objects.filter(user=user).exists():
        return False
    transport = transport or garmin.Transport()
    try:
        garmin.deregister(access_for(user, transport), transport)
    except garmin.GarminError:
        pass
    GarminLink.objects.filter(user=user).delete()
    return True


@csrf_exempt
@require_http_methods(["POST"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
def deregistrations(request):
    """Garmin's deregistration notice. Always 200 once read, so Garmin does not retry a notice
    whose riders are already gone."""
    from .models import GarminLink

    if not garmin.available():
        return HttpResponse(status=404)
    if len(request.body) > NOTICE_MAX_BYTES:
        return HttpResponse(status=413)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)
    ids = garmin.deregistered_user_ids(body)
    removed = GarminLink.objects.filter(garmin_user_id__in=ids).delete()[0] if ids else 0
    return JsonResponse({"removed": removed})
