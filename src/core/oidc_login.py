"""Google and Apple sign-in, beside Discord's.

Stephen 2026-11-13: "Yes, and allow account linking".

The protocol half, with no Django, as `discord_oauth` is for Discord. Both are OpenID Connect with
the `openid` scope alone, so the only thing either hands back is the account's subject: no name, no
email, no picture. Apple's App Review Guideline 4.8 is why Apple is here at all (an iPhone app that
offers Discord must also offer a sign-in that keeps at most a name and an email and lets the rider
hide it); Google is the other common one.

The subject is not stored as given. `subject_key` keys it with HMAC under the tombstone key, so the
table holds a value that matches the next sign-in and nothing a dump could look up at Google or
Apple.

The ID token comes straight from the provider's token endpoint over TLS, in answer to our own
client authentication, so its signature is not checked again (OpenID Connect Core 1.0, 3.1.3.7,
item 6); its issuer, audience and expiry are.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

PROVIDERS = ("google", "apple")
NAMES = {"discord": "Discord", "google": "Google", "apple": "Apple"}


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    issuers: tuple[str, ...]
    # Apple returns to a query only when no scope is asked for; `openid` is implied there.
    scope: str


GOOGLE = Provider(
    "google",
    "https://accounts.google.com/o/oauth2/v2/auth",
    "https://oauth2.googleapis.com/token",
    ("https://accounts.google.com", "accounts.google.com"),
    "openid",
)
APPLE = Provider(
    "apple",
    "https://appleid.apple.com/auth/authorize",
    "https://appleid.apple.com/auth/token",
    ("https://appleid.apple.com",),
    "",
)
BY_NAME = {"google": GOOGLE, "apple": APPLE}

USER_AGENT = "RouteMaker (https://github.com/Macrophage87/RouteMaker, 1)"


class ExchangeFailed(RuntimeError):
    """The code could not be turned into a subject, for a reason the rider may be told."""


def authorize_url(provider: Provider, client_id: str, redirect_uri: str, state: str) -> str:
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if provider.scope:
        query["scope"] = provider.scope
    if provider is APPLE:
        query["response_mode"] = "query"
    return f"{provider.authorize_url}?{urllib.parse.urlencode(query)}"


def new_state() -> str:
    return secrets.token_urlsafe(32)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def apple_client_secret(
    team_id: str, client_id: str, key_id: str, private_key_pem: str, now: float | None = None
) -> str:
    """Apple's client secret: a short-lived ES256 JWT signed with the key made in Apple's developer
    site.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    issued = int(now if now is not None else time.time())
    header = {"alg": "ES256", "kid": key_id}
    claims = {
        "iss": team_id,
        "iat": issued,
        "exp": issued + 300,
        "aud": "https://appleid.apple.com",
        "sub": client_id,
    }
    signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}"
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ExchangeFailed("the Apple key is not an elliptic-curve key")
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing_input}.{_b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def subject_from_id_token(
    provider: Provider, id_token: str, client_id: str, now: float | None = None
) -> str:
    """The `sub` of an ID token fetched from the provider's own token endpoint, after its claims are
    checked.
    """
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, TypeError) as error:
        raise ExchangeFailed("the ID token could not be read") from error
    if not isinstance(claims, dict):
        raise ExchangeFailed("the ID token could not be read")
    if claims.get("iss") not in provider.issuers:
        raise ExchangeFailed("the ID token is from another issuer")
    audience = claims.get("aud")
    if audience != client_id and not (isinstance(audience, list) and client_id in audience):
        raise ExchangeFailed("the ID token is for another application")
    expires = claims.get("exp")
    if not isinstance(expires, (int, float)) or expires < (now if now is not None else time.time()):
        raise ExchangeFailed("the ID token has expired")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise ExchangeFailed("the ID token names no account")
    return subject


def exchange(
    provider: Provider, code: str, *, client_id: str, client_secret: str, redirect_uri: str
) -> str:
    """Trade the code for the account's subject. Every token is dropped here: only the subject
    leaves."""
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    ).encode()
    request = urllib.request.Request(
        provider.token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - a constant https endpoint
            token = json.load(response)
        return subject_from_id_token(provider, token["id_token"], client_id)
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,
        KeyError,
        ValueError,
        TypeError,
    ) as error:
        raise ExchangeFailed(f"the {NAMES[provider.name]} exchange failed: {error}") from error


def subject_key(provider: str, subject: str, key: bytes) -> str:
    """The stored form of a subject: keyed, so a dump cannot be matched to an account elsewhere."""
    if not key:
        raise ValueError("a key is required; an unkeyed hash of a subject is reversible")
    return hmac.new(key, f"{provider}:{subject}".encode(), hashlib.sha256).hexdigest()
