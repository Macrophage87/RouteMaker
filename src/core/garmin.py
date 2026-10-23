"""Garmin Connect: a rider's connection, for sending courses (the owner, 2026-10-23: approved for
Garmin's Connect Developer Program, Starter; "Keep it, encrypted" over a sign-in on every send).

The protocol, and no views: the OAuth 2.0 PKCE sign-in Garmin's developer program specifies
(OAuth2PKCE, Garmin Connect Developer Program), the token refresh, the Garmin user id, the
deregistration call, and the encryption the tokens are kept under. `core.garmin_views` is the half
that touches requests; `core.models.GarminLink` is the row.

This is the deployment's one kept third-party credential, so it is narrow on purpose:

- Courses only. The app is registered with Garmin for the Courses API alone, so a token reads no
  activity, health or other data; this module calls nothing that would.
- One link per account, made only by the rider, in Settings, and removed by Disconnect, by the
  rider disconnecting in Garmin Connect (Garmin's deregistration notice), or by deleting the
  account.
- Both tokens are encrypted (AES-GCM) under a key derived from KEY_ENCRYPTION_KEY, which is never
  in the database, and bound to the account they belong to, so a row copied onto another account
  does not decrypt. The table is left out of the nightly backup as well.

HTTP goes through `Transport`, which the tests replace, so no test calls Garmin.
"""

from __future__ import annotations

import base64
import hashlib
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

AUTHORIZE_URL = "https://connect.garmin.com/oauth2Confirm"
TOKEN_URL = "https://diauth.garmin.com/di-oauth2-service/oauth/token"
USER_ID_URL = "https://apis.garmin.com/wellness-api/rest/user/id"
REGISTRATION_URL = "https://apis.garmin.com/wellness-api/rest/user/registration"

USER_AGENT = "RouteMaker (https://github.com/Macrophage87/RouteMaker, 1)"
STATE_LIFETIME = timedelta(minutes=10)
# Garmin asks that a token be refreshed at least 600 seconds before it expires.
REFRESH_MARGIN = timedelta(seconds=600)
TIMEOUT_S = 10


class GarminError(RuntimeError):
    """A call to Garmin failed, for a reason that may be shown to the rider."""


class NotConnected(GarminError):
    """The account has no live Garmin connection (none, or Garmin refused its refresh token)."""


# Whether Settings offers Connect. The course send is wired in (core.garmin_courses), but the
# privacy page still says the connection is not offered: it is turned on with that page's update,
# once v0.11.1's page is in this release. Until then the sign-in and the send work for testing.
COURSES_WIRED = False


def offered() -> bool:
    """Whether Settings offers riders a Garmin connection."""
    return COURSES_WIRED and available()


def available() -> bool:
    """Whether this deployment can connect riders: both Garmin keys are set."""
    return bool(
        str(getattr(settings, "GARMIN_CLIENT_ID", "") or "").strip()
        and str(getattr(settings, "GARMIN_CLIENT_SECRET", "") or "").strip()
    )


# The sign-in.


@dataclass(frozen=True)
class Pending:
    """A sign-in in progress, kept in the rider's session until Garmin sends them back."""

    state: str
    verifier: str
    issued_at: datetime

    def is_live(self, now: datetime) -> bool:
        return now - self.issued_at < STATE_LIFETIME


def challenge_of(verifier: str) -> str:
    """PKCE S256: the verifier's SHA-256, base64url without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def begin(client_id: str, redirect_uri: str, now: datetime) -> tuple[str, Pending]:
    """The authorize URL and what to keep in the session until the callback."""
    # 64 random bytes as base64url is 86 characters, all from the set PKCE allows (43 to 128).
    pending = Pending(
        state=secrets.token_urlsafe(32), verifier=secrets.token_urlsafe(64), issued_at=now
    )
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": pending.state,
            "code_challenge": challenge_of(pending.verifier),
            "code_challenge_method": "S256",
        }
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
    refresh_expires_at: datetime


def tokens_from(body: dict, now: datetime) -> Tokens:
    """Garmin's token response, with lifetimes made into times. Raises GarminError if malformed."""
    try:
        access = str(body["access_token"])
        refresh = str(body["refresh_token"])
        access_s = int(body["expires_in"])
        # The refresh token's lifetime is documented as about 90 days; when it is missing, the
        # refresh call itself says when it has run out.
        refresh_s = int(body.get("refresh_token_expires_in") or 90 * 24 * 3600)
    except (KeyError, TypeError, ValueError) as error:
        raise GarminError("Garmin's sign-in answer was not in the expected form.") from error
    if not access or not refresh or access_s <= 0:
        raise GarminError("Garmin's sign-in answer was not in the expected form.")
    return Tokens(
        access=access,
        access_expires_at=now + timedelta(seconds=access_s),
        refresh=refresh,
        refresh_expires_at=now + timedelta(seconds=refresh_s),
    )


def needs_refresh(access_expires_at: datetime, now: datetime) -> bool:
    return access_expires_at - REFRESH_MARGIN <= now


# HTTP.


class Transport:
    """The calls to Garmin, one method each, replaced in the tests."""

    def post_form(self, url: str, form: dict) -> tuple[int, dict]:
        data = urllib.parse.urlencode(form).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        return self._send(urllib.request.Request(url, data=data, headers=headers, method="POST"))

    def get_json(self, url: str, access: str) -> tuple[int, dict]:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})
        return self._send(request)

    def send_json(self, method: str, url: str, access: str, body: dict) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}
        data = json.dumps(body).encode()
        return self._send(urllib.request.Request(url, data=data, headers=headers, method=method))

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
            raise GarminError("Garmin could not be reached just now.") from error


def _json(raw: bytes) -> dict:
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def exchange(code: str, verifier: str, now: datetime, transport: Transport) -> Tokens:
    status, body = transport.post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": settings.GARMIN_CLIENT_ID,
            "client_secret": settings.GARMIN_CLIENT_SECRET,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": settings.GARMIN_REDIRECT_URI,
        },
    )
    if status != 200:
        raise GarminError("Garmin did not accept the sign-in. Try connecting again.")
    return tokens_from(body, now)


def refresh(refresh_token: str, now: datetime, transport: Transport) -> Tokens:
    """New tokens from the refresh token. Garmin answers `invalid_grant` when it has expired or the
    rider withdrew consent; that is NotConnected, and the link should go. Any other refusal (our
    own client secret wrong or mid-rotation: `invalid_client`) is a GarminError, and every link is
    kept for when the secret is right again."""
    status, body = transport.post_form(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": settings.GARMIN_CLIENT_ID,
            "client_secret": settings.GARMIN_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
    )
    if status in (400, 401) and body.get("error") == "invalid_grant":
        raise NotConnected("The Garmin connection has ended. Connect again in Settings.")
    if status != 200:
        raise GarminError("Garmin could not be reached just now.")
    return tokens_from(body, now)


def user_id(access: str, transport: Transport) -> str:
    status, body = transport.get_json(USER_ID_URL, access)
    value = body.get("userId") if status == 200 else None
    if not isinstance(value, str) or not value or len(value) > 64:
        raise GarminError("Garmin did not say which account was connected. Try again.")
    return value


def deregister(access: str, transport: Transport) -> bool:
    """Tell Garmin the rider disconnected, so the app leaves their Garmin Connect consent list.
    True when Garmin took it; False is not an error, since the link is deleted either way."""
    try:
        status, _ = transport.delete(REGISTRATION_URL, access)
    except GarminError:
        return False
    return status in (200, 204)


# Encryption at rest.

TOKEN_FORMAT = "v1"


def _cipher():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(settings.GARMIN_TOKEN_KEY)


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
        raise NotConnected("The Garmin connection could not be read. Connect again.") from error
    return plain.decode()


# Garmin's deregistration notice (the rider disconnected in Garmin Connect).


def deregistered_user_ids(body) -> list[str]:
    """The Garmin user ids in a deregistration notice: {"deregistrations": [{"userId": …}, …]}."""
    rows = body.get("deregistrations") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return []
    ids = [row.get("userId") for row in rows[:1000] if isinstance(row, dict)]
    return [i for i in ids if isinstance(i, str) and 0 < len(i) <= 64]
