"""Wahoo: a rider's connection, for sending routes to their Wahoo app and ELEMNT (the owner,
2026-10-23: Wahoo's Cloud API approved the app, "routes_read" and "routes_write").

The protocol, and no views: the OAuth 2.0 authorization-code sign-in Wahoo's Cloud API specifies
(https://cloud-api.wahooligan.com, Authentication; a confidential app, so the client secret
stays on this server and there is no PKCE), the token refresh, the Wahoo user id, the route
calls, and the encryption the tokens are kept under. `core.wahoo_views` is the half that touches
requests; `core.models.WahooLink` is the row.

Kept as narrow as the Garmin connection (core.garmin):

- Routes only. The app is registered with Wahoo for routes_read and routes_write, with the
  user_read Wahoo requires (read once, for the account number); a token reads no workouts,
  plans, power zones or rides, and this module calls nothing that would.
- One link per account, made only by the rider, in Settings, and removed by Disconnect or by
  deleting the account. Wahoo sends no notice when a rider disconnects in Wahoo's own settings;
  the next refresh is refused instead, and the link goes then.
- Both tokens are encrypted (AES-GCM) under a key derived from KEY_ENCRYPTION_KEY, never in the
  database, and bound to the account they belong to. The table is left out of the nightly backup.

HTTP goes through `Transport`, which the tests replace, so no test calls Wahoo.
"""

from __future__ import annotations

import base64
import hmac
import http.client
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings

BASE_URL = "https://api.wahooligan.com"
AUTHORIZE_URL = f"{BASE_URL}/oauth/authorize"
TOKEN_URL = f"{BASE_URL}/oauth/token"
USER_URL = f"{BASE_URL}/v1/user"
ROUTES_URL = f"{BASE_URL}/v1/routes"
PERMISSIONS_URL = f"{BASE_URL}/v1/permissions"
SCOPES = "user_read routes_read routes_write"

USER_AGENT = "RouteMaker (https://github.com/Macrophage87/RouteMaker, 1)"
STATE_LIFETIME = timedelta(minutes=10)
# Wahoo's access tokens last 2 hours; a call is never made on one with under 5 minutes left.
REFRESH_MARGIN = timedelta(minutes=5)
TIMEOUT_S = 10


class WahooError(RuntimeError):
    """A call to Wahoo failed, for a reason that may be shown to the rider."""


class NotConnected(WahooError):
    """The account has no live Wahoo connection (none, or Wahoo refused its refresh token)."""


def offered() -> bool:
    """Whether Settings offers riders a Wahoo connection: both Wahoo keys are set."""
    return bool(
        str(getattr(settings, "WAHOO_CLIENT_ID", "") or "").strip()
        and str(getattr(settings, "WAHOO_CLIENT_SECRET", "") or "").strip()
    )


# The sign-in.


@dataclass(frozen=True)
class Pending:
    """A sign-in in progress, kept in the rider's session until Wahoo sends them back."""

    state: str
    issued_at: datetime

    def is_live(self, now: datetime) -> bool:
        return now - self.issued_at < STATE_LIFETIME


def begin(client_id: str, redirect_uri: str, now: datetime) -> tuple[str, Pending]:
    """The authorize URL and what to keep in the session until the callback."""
    pending = Pending(state=secrets.token_urlsafe(32), issued_at=now)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "response_type": "code",
            "state": pending.state,
        },
        quote_via=urllib.parse.quote,
    )
    return f"{AUTHORIZE_URL}?{query}", pending


def state_matches(pending: Pending | None, returned: str, now: datetime) -> bool:
    """The callback's state is the live one this session started (constant-time, as bytes)."""
    if pending is None or not pending.is_live(now):
        return False
    return hmac.compare_digest(pending.state.encode(), returned.encode())


# Tokens.


@dataclass(frozen=True)
class Tokens:
    access: str
    access_expires_at: datetime
    refresh: str


def tokens_from(body: dict, now: datetime) -> Tokens:
    """Wahoo's token response, its lifetime made a time. Raises WahooError if malformed."""
    try:
        access = str(body["access_token"])
        refresh = str(body["refresh_token"])
        access_s = int(body["expires_in"])
    except (KeyError, TypeError, ValueError) as error:
        raise WahooError("Wahoo's sign-in answer was not in the expected form.") from error
    if not access or not refresh or access_s <= 0:
        raise WahooError("Wahoo's sign-in answer was not in the expected form.")
    return Tokens(
        access=access, access_expires_at=now + timedelta(seconds=access_s), refresh=refresh
    )


def needs_refresh(access_expires_at: datetime, now: datetime) -> bool:
    return access_expires_at - REFRESH_MARGIN <= now


# HTTP.


class Transport:
    """The calls to Wahoo, one method each, replaced in the tests."""

    def post_form(self, url: str, form: dict, access: str | None = None) -> tuple[int, dict]:
        return self.send_form("POST", url, form, access)

    def send_form(
        self, method: str, url: str, form: dict, access: str | None = None
    ) -> tuple[int, dict]:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if access is not None:
            headers["Authorization"] = f"Bearer {access}"
        data = urllib.parse.urlencode(form).encode()
        return self._send(urllib.request.Request(url, data=data, headers=headers, method=method))

    def get_json(self, url: str, access: str) -> tuple[int, dict]:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})
        return self._send(request)

    def delete(self, url: str, access: str) -> tuple[int, dict]:
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {access}"}, method="DELETE"
        )
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> tuple[int, dict]:
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - constant https endpoints
                return response.status, _json(response.read())
        except urllib.error.HTTPError as error:
            return error.code, _json(error.read())
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as error:
            raise WahooError("Wahoo could not be reached just now.") from error


def _json(raw: bytes) -> dict:
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def exchange(code: str, now: datetime, transport: Transport) -> Tokens:
    status, body = transport.post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": settings.WAHOO_CLIENT_ID,
            "client_secret": settings.WAHOO_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.WAHOO_REDIRECT_URI,
        },
    )
    if status != 200:
        raise WahooError("Wahoo did not accept the sign-in. Try connecting again.")
    return tokens_from(body, now)


def refresh(refresh_token: str, now: datetime, transport: Transport) -> Tokens:
    """New tokens from the refresh token. Wahoo answers `invalid_grant` when it has expired or the
    rider disconnected RouteMaker in Wahoo's settings; that is NotConnected, and the link should
    go. Any other refusal (our own client secret wrong: `invalid_client`) is a WahooError, and
    every link is kept for when the secret is right again."""
    status, body = transport.post_form(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": settings.WAHOO_CLIENT_ID,
            "client_secret": settings.WAHOO_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
    )
    if status in (400, 401) and body.get("error") == "invalid_grant":
        raise NotConnected("The Wahoo connection has ended. Connect again in Settings.")
    if status != 200:
        raise WahooError("Wahoo could not be reached just now.")
    return tokens_from(body, now)


def user_id(access: str, transport: Transport) -> str:
    status, body = transport.get_json(USER_URL, access)
    value = body.get("id") if status == 200 else None
    if isinstance(value, bool) or not isinstance(value, int | str) or not str(value):
        raise WahooError("Wahoo did not say which account was connected. Try again.")
    value = str(value)
    if len(value) > 64:
        raise WahooError("Wahoo did not say which account was connected. Try again.")
    return value


def revoke(access: str, transport: Transport) -> bool:
    """Withdraw RouteMaker's access in Wahoo (every permission the rider gave the app). True when
    Wahoo took it; False is not an error, since the link is deleted either way."""
    try:
        status, _ = transport.delete(PERMISSIONS_URL, access)
    except WahooError:
        return False
    return status in (200, 204)


# Encryption at rest, as core.garmin's, under Wahoo's own subkey.

TOKEN_FORMAT = "v1"


def _cipher():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(settings.WAHOO_TOKEN_KEY)


def seal(token: str, account_id: int) -> str:
    """The token, AES-GCM encrypted, bound to the account (associated data), as text."""
    nonce = os.urandom(12)
    sealed = _cipher().encrypt(nonce, token.encode(), f"account:{account_id}".encode())
    return f"{TOKEN_FORMAT}.{base64.urlsafe_b64encode(nonce + sealed).decode('ascii')}"


def unseal(value: str, account_id: int) -> str:
    """The token back. Raises NotConnected if it cannot be read (another key, another account)."""
    from cryptography.exceptions import InvalidTag

    version, _, payload = value.partition(".")
    try:
        if version != TOKEN_FORMAT:
            raise ValueError(version)
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        plain = _cipher().decrypt(raw[:12], raw[12:], f"account:{account_id}".encode())
    except (InvalidTag, ValueError) as error:
        raise NotConnected("The Wahoo connection could not be read. Connect again.") from error
    return plain.decode()
