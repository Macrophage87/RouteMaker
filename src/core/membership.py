"""Applying Discord gateway events to the membership cache.

The gateway is the mechanism and the six-hourly sweep is the backstop, not the
other way round: a role removed in Discord should revoke the matching
application permission in seconds, and the sweep exists to catch what the
gateway missed during a disconnect.

What the cache stores is deliberately narrow. Guild id, role ids, timeout expiry
and last-confirmed time, keyed by Discord user id, and nothing else - no
usernames, avatars, nicknames or join dates. For a tool whose threat model
includes routes for unpermitted rides, who organizes with whom is the sensitive
part, so rows for people who have never signed in are purged after 30 days and
the cache is excluded from the nightly dump entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .standing import Membership

PURGE_NEVER_SIGNED_IN_AFTER = timedelta(days=30)


@dataclass(frozen=True)
class GatewayEvent:
    """The subset of member events that change standing."""

    kind: str  # add, update, remove
    guild_id: int
    user_id: int
    role_ids: frozenset[int] = frozenset()
    pending: bool = False
    timed_out_until: datetime | None = None
    received_at: datetime | None = None


def apply_event(
    current: Membership | None, event: GatewayEvent, now: datetime
) -> Membership | None:
    """Fold one gateway event into the cached row.

    A removal marks the row rather than deleting it, so that the deliberate-
    removal grace can run from a known instant. Deleting outright would make a
    removal indistinguishable from a row that was never there, and the two have
    different windows.
    """
    if event.kind == "remove":
        if current is None:
            return None
        # last_confirmed is deliberately untouched: stamping it here would extend
        # the row's life against the staleness backstop, so the event that
        # revokes the grant would also lengthen it.
        return replace(current, removed_at=now)

    if event.kind not in {"add", "update"}:
        # Explicit rather than defaulted. An unrecognised kind previously fell
        # through to the add branch and constructed a live membership row, which
        # is the wrong failure direction for a cache whose rule is that absence
        # of a row is absence of standing.
        raise ValueError(f"unknown gateway event kind: {event.kind!r}")

    return Membership(
        guild_id=event.guild_id,
        role_ids=event.role_ids,
        last_confirmed=event.received_at or now,
        pending=event.pending,
        timed_out_until=event.timed_out_until,
        removed_at=None,  # a re-add clears a prior removal
    )


def should_purge(row: Membership, has_ever_signed_in: bool, now: datetime) -> bool:
    """Whether a cached row for someone who never used the site should go.

    Who organizes with whom is the sensitive part, so the cache does not quietly
    accumulate a roster of people who have never touched the application.
    """
    if has_ever_signed_in:
        return False
    return now - row.last_confirmed >= PURGE_NEVER_SIGNED_IN_AFTER


def sweep_priority(rows: list[tuple[Membership, bool]]) -> list[Membership]:
    """Order rows for a degraded-mode sweep, most important first.

    In degraded mode the bot falls back to per-user REST lookups against a
    request budget, so ordering decides who keeps working when the budget runs
    out. Active sessions first, because those are the people the staleness will
    actually be noticed by.
    """
    return [row for row, _ in sorted(rows, key=lambda pair: (not pair[1], pair[0].last_confirmed))]
