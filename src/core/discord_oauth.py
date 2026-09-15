"""Discord login, identify scope only.

No Discord token is ever retained. The authorization code is exchanged once, the
user id is read from it, and the access and refresh tokens are discarded rather
than stored. That is why revoking the application in Discord's authorized-apps
page does not log anyone out here and does not need to: the tokens it revokes
were never kept, and standing comes from the bot's view of the roster instead.

The consequence worth stating is that this system holds no per-user third-party
credential at all. There is nothing to encrypt, refresh, leak, or revoke on
deletion, and a database compromise yields no access to anyone's Discord account.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"

# identify alone. `guilds` would list every server the person is in, which is
# more than this needs and more than they should have to disclose to plan a
# bike ride; membership is established by the bot's own view of the roster.
SCOPES = ("identify",)

STATE_LIFETIME = timedelta(minutes=10)


class OAuthStateError(RuntimeError):
    """The callback's state did not match a live, unconsumed request."""


@dataclass(frozen=True)
class LoginRequest:
    state: str
    issued_at: datetime
    redirect_after: str = "/"

    def is_live(self, now: datetime) -> bool:
        return now - self.issued_at < STATE_LIFETIME


def begin_login(client_id: str, redirect_uri: str, now: datetime, redirect_after: str = "/"):
    """Build the authorize URL and the state to store against the session."""
    request = LoginRequest(
        state=secrets.token_urlsafe(32), issued_at=now, redirect_after=redirect_after
    )
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": request.state,
            "prompt": "none",
        }
    )
    return f"{AUTHORIZE_URL}?{query}", request


def verify_state(stored: LoginRequest | None, returned: str, now: datetime) -> LoginRequest:
    """Check the callback's state against the stored one.

    Compared in constant time and consumed by the caller, so a replayed callback
    cannot mint a second session from one authorization.
    """
    if stored is None:
        raise OAuthStateError("no login was in progress for this session")
    if not stored.is_live(now):
        raise OAuthStateError("the login request expired")
    if not hmac.compare_digest(stored.state, returned):
        raise OAuthStateError("state mismatch")
    return stored


def scopes_are_minimal(granted: str) -> bool:
    """Whether Discord granted only what was asked for.

    A grant carrying more than identify means the authorize URL was tampered with
    or the application's configuration drifted; either way the extra scope is not
    used and its presence is worth refusing rather than ignoring.
    """
    return set(granted.split()) <= set(SCOPES)
