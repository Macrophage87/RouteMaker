"""Revocation: sessions, bans, and the degraded-guild window.

Django's database session backend has no user column, so nothing in it can
enumerate one person's sessions and the only global lever is rotating the secret
key, which signs everybody out. Every revocation path in the plan - ban,
suspension, deletion, sign-out-everywhere - needs per-user revocation, so a
session epoch carries it: the user row holds a counter, each session records the
counter it was issued under, and middleware rejects any session whose stored
epoch is stale. Bumping the counter invalidates that user's sessions and nobody
else's, in one write.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

# Django implements idle expiry natively but not an absolute cap, so the
# absolute one is enforced here.
ABSOLUTE_SESSION_LIFETIME = timedelta(days=90)
IDLE_SESSION_LIFETIME = timedelta(days=14)

# The gateway disconnect that raises an alert. The degraded window runs from this
# mark rather than from the end of a grace period; stacking the two would leave
# the whole deployment carrying stale grants for twice as long as a single lost
# guild.
GATEWAY_ALERT_AFTER = timedelta(minutes=5)
DEGRADED_WINDOW = timedelta(hours=72)


@dataclass(frozen=True)
class SessionRecord:
    """A session, with the epoch it was issued under."""

    key: str
    user_id: int
    issued_epoch: int
    created_at: datetime
    last_seen_at: datetime

    def is_valid(self, current_epoch: int, now: datetime) -> bool:
        if self.issued_epoch != current_epoch:
            return False
        if now - self.created_at >= ABSOLUTE_SESSION_LIFETIME:
            return False
        return now - self.last_seen_at < IDLE_SESSION_LIFETIME


def tombstone(discord_user_id: int, key: bytes) -> str:
    """A keyed tombstone for ban enforcement after deletion.

    HMAC rather than a plain hash. A Discord id is a structured 64-bit value
    whose candidate set any guild's member list resolves directly, so an unkeyed
    hash of one gives no privacy at all against anyone holding a dump - which is
    the reason the membership cache is excluded from dumps in the first place.
    The key lives in SSM and never appears in a dump.
    """
    if not key:
        raise ValueError("a tombstone key is required; an unkeyed hash is reversible")
    return hmac.new(key, str(discord_user_id).encode(), hashlib.sha256).hexdigest()


def degraded_window(alert_at: datetime) -> datetime:
    """When standing lapses for a guild marked degraded at `alert_at`."""
    return alert_at + DEGRADED_WINDOW


def should_mark_degraded(last_gateway_event: datetime, now: datetime) -> bool:
    """Whether a disconnect has lasted long enough to mark guilds degraded.

    The same five minutes that raises the alert, deployment-wide. Marking only
    after a full grace period would double the maximum stale-grant window.
    """
    return now - last_gateway_event >= GATEWAY_ALERT_AFTER
