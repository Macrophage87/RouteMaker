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


def is_forgotten(discord_user_id: int) -> bool:
    """Whether this Discord id has asked to be forgotten, or is banned outright.

    Two sources, because deletion removes the account row and a ban has to
    survive it: the account's own `is_deleted`, and the keyed tombstone that is
    all that is kept of a deleted id. Either one means no cached membership row
    for this person may exist, however many gateway events arrive and however
    firmly they are still in the guild.
    """
    from django.conf import settings

    from .models import BanTombstone, User
    from .revocation import tombstone

    if User.objects.filter(discord_user_id=discord_user_id, is_deleted=True).exists():
        return True
    return BanTombstone.objects.filter(
        tombstone=tombstone(discord_user_id, settings.TOMBSTONE_KEY)
    ).exists()


def record_event(event: GatewayEvent, now: datetime | None = None):
    """Apply a gateway event to the cached row for one person in one guild.

    This is the half that was missing. `apply_event` folded an event into a
    `standing.Membership` dataclass and handed it back to a caller that did not
    exist, so nothing ever wrote a `CachedMembership` row - the table
    `attach_standing` reads was filled by nothing, and "a role removed in Discord
    revokes the matching application permission" had no path from one end to the
    other.

    A guild the bot is in but that this deployment has not configured is ignored
    rather than cached. Caching it would build a roster of a server that has not
    asked to be here, which is the opposite of what the narrow cache is for.
    """
    from django.utils import timezone

    from .models import CachedMembership, ConfiguredGuild

    now = now or timezone.now()
    guild = ConfiguredGuild.objects.filter(guild_id=event.guild_id).first()
    if guild is None:
        return None

    if is_forgotten(event.user_id):
        # Deletion removes the cached rows; without this the next gateway event
        # writes them straight back, because the person is still in the guild and
        # the gateway has no idea an account here ever existed. The tombstone is
        # exactly what the plan says keeps the bot "from recreating [them] on the
        # next gateway event or sweep even though the person is still in the
        # guild". Any row that survived an earlier event goes with it.
        CachedMembership.objects.filter(discord_user_id=event.user_id).delete()
        return None

    row = CachedMembership.objects.filter(discord_user_id=event.user_id, guild=guild).first()
    current = (
        Membership(
            guild_id=guild.guild_id,
            role_ids=frozenset(int(r) for r in row.role_ids),
            last_confirmed=row.last_confirmed,
            pending=row.pending,
            timed_out_until=row.timed_out_until,
            removed_at=row.removed_at,
        )
        if row is not None
        else None
    )

    updated = apply_event(current, event, now)
    if updated is None:
        # A removal for someone with no row. Nothing to mark, and creating one to
        # mark it removed would turn "never a member" into "was a member".
        return None

    if row is None:
        row = CachedMembership(discord_user_id=event.user_id, guild=guild)
    row.role_ids = sorted(updated.role_ids)
    row.last_confirmed = updated.last_confirmed
    row.pending = updated.pending
    row.timed_out_until = updated.timed_out_until
    row.removed_at = updated.removed_at
    row.save()
    return row


def sweep_memberships(now: datetime | None = None) -> tuple[int, int]:
    """The six-hourly backstop. Returns (rows purged, departed rows dropped).

    Three deletions, each for its own reason, and one deliberate non-deletion.

    Rows for an account that has been deleted, or whose Discord id carries a ban
    tombstone, go on sight. They are counted with the purge because they are the
    same rule: this deployment does not hold rows it has no business holding.

    Rows for people who have never signed in go after thirty days, because this
    deployment should not hold a roster of a guild it only ever saw through the
    gateway.

    Rows marked removed go once they are past the staleness ceiling, at which
    point they grant nothing under any circumstance and a re-add would write a
    fresh row anyway. Keeping them indefinitely would be the same roster by
    another name.

    What is *not* deleted is a stale row for a current member. An earlier version
    of this swept those too, which reads as tidiness and is a revocation bug: the
    bot confirms a row when an event arrives, and a member whose roles have not
    changed generates no events, so every quiet member's row ages past the
    ceiling within three days. Deleting it would leave nothing for a
    reconfirmation to refresh and would drop that member's standing until they
    happened to change a role. Staleness is already handled where it belongs -
    `attach_standing` refuses to read a row past the ceiling - so the row stays
    and simply grants nothing until the bot reconfirms it.
    """
    from django.conf import settings
    from django.utils import timezone

    from .models import BanTombstone, CachedMembership, User
    from .revocation import tombstone
    from .standing import MAX_ROW_AGE

    now = now or timezone.now()

    signed_in = set(
        User.objects.filter(last_login__isnull=False, is_deleted=False).values_list(
            "discord_user_id", flat=True
        )
    )

    # A deleted or ban-tombstoned account keeps its own `last_login`, so the
    # never-signed-in purge below steps straight over its rows and they stayed
    # forever. This is the sweep's half of the same rule `record_event` enforces
    # on the gateway: someone who asked to be forgotten is forgotten by both
    # paths, or by neither.
    #
    # Resolved in two queries and a pass of HMACs rather than two queries per
    # row: this runs against every cached row every six hours, and the tombstone
    # lookup cannot be a join because a tombstone is a keyed hash of the id.
    cached_ids = set(CachedMembership.objects.values_list("discord_user_id", flat=True))
    forgotten = set(
        User.objects.filter(discord_user_id__in=cached_ids, is_deleted=True).values_list(
            "discord_user_id", flat=True
        )
    )
    if cached_ids - forgotten:
        tombstones = set(BanTombstone.objects.values_list("tombstone", flat=True))
        key = settings.TOMBSTONE_KEY
        forgotten |= {i for i in cached_ids - forgotten if tombstone(i, key) in tombstones}

    purged, _ = CachedMembership.objects.filter(discord_user_id__in=forgotten).delete()

    for row in CachedMembership.objects.exclude(discord_user_id__in=signed_in):
        if should_purge(
            Membership(
                guild_id=row.guild_id,
                role_ids=frozenset(int(r) for r in row.role_ids),
                last_confirmed=row.last_confirmed,
            ),
            has_ever_signed_in=False,
            now=now,
        ):
            row.delete()
            purged += 1

    departed, _ = CachedMembership.objects.filter(
        removed_at__isnull=False, removed_at__lt=now - MAX_ROW_AGE
    ).delete()
    return purged, departed


def sweep_priority(rows: list[tuple[Membership, bool]]) -> list[Membership]:
    """Order rows for a degraded-mode sweep, most important first.

    In degraded mode the bot falls back to per-user REST lookups against a
    request budget, so ordering decides who keeps working when the budget runs
    out. Active sessions first, because those are the people the staleness will
    actually be noticed by.
    """
    return [row for row, _ in sorted(rows, key=lambda pair: (not pair[1], pair[0].last_confirmed))]
