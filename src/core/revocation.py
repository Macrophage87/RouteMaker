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
# The plan's figure, and it was 14 days here for three rounds without anything
# noticing, because every test computed its own boundary from this constant
# rather than from the number the plan writes down. `test_settings_security`
# pins it flat now.
IDLE_SESSION_LIFETIME = timedelta(days=30)

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


# The run row the bot writes each time it hears from the gateway. It is a
# `ScheduledRun`, so the existing "nothing has succeeded lately" alert reads it
# with no new table and no new alert mechanism. Writing it is the bot's job (see
# the outstanding gateway-ingest work); this module only reads it.
GATEWAY_HEARTBEAT_TASK = "gateway_heartbeat"


def last_gateway_event(default=None):
    """When the gateway was last heard from, or `default` if never."""
    from .runs import last_success

    run = last_success(GATEWAY_HEARTBEAT_TASK)
    return run.started_at if run is not None else default


_UNSET = object()


def mark_degraded_guilds(now=None, last_event=_UNSET) -> tuple[int, int]:
    """Move guilds into and out of degraded as the gateway comes and goes.

    Returns (marked degraded, restored to active).

    This is the transition `should_mark_degraded` and `degraded_window` were
    written for and never had: both predicates were correct, well tested, and
    called from nowhere, so `ConfiguredGuild.state` was written by nothing and no
    guild could ever leave `active`. A grace period with no way into the state it
    guards is not a grace period.

    The window runs from the *alert*, which fires `GATEWAY_ALERT_AFTER` past the
    last event, not from now and not from the end of a grace period. Stacking two
    windows would leave the whole deployment carrying stale grants for twice as
    long as a single lost guild does, and 72 hours from the alert is the only
    number.

    A guild already degraded is left alone rather than re-marked: re-marking on
    every tick would slide `state_since` forward and make the ceiling in
    `GuildStanding.grants_standing` unreachable, which is the same bug as
    trusting the column. A revoked guild is never touched - revocation is a
    decision, not a symptom, and the gateway coming back does not reverse it.

    Never having heard from the gateway counts as silence. The bot is a phase 1
    deliverable and its absence is exactly the outage this guards; failing open
    would mean a deployment whose bot never started grants full standing forever.

    The worker's task module owns scheduling. Register this on a short cron - the
    bound is five minutes, so six-hourly is not it.
    """
    from django.utils import timezone

    from .models import ConfiguredGuild

    now = now or timezone.now()
    if last_event is _UNSET:
        last_event = last_gateway_event()

    if last_event is not None and not should_mark_degraded(last_event, now):
        return 0, _restore_degraded(now)

    alert_at = (last_event + GATEWAY_ALERT_AFTER) if last_event is not None else now
    marked = 0
    for guild in ConfiguredGuild.objects.filter(state="active"):
        guild.state = "degraded"
        guild.state_since = alert_at
        guild.standing_valid_until = degraded_window(alert_at)
        guild.save(update_fields=["state", "state_since", "standing_valid_until"])
        _audit_worker(
            "mark_degraded",
            guild,
            detail=(
                f"gateway silent since {last_event}; standing lapses {guild.standing_valid_until}"
            ),
        )
        marked += 1
    return marked, 0


def _restore_degraded(now) -> int:
    """Bring degraded guilds back to active once the gateway is talking again.

    Without this one blip degrades the deployment permanently: nothing else
    writes the column back, so every guild would lapse 72 hours later and the
    only repair would be an UPDATE against production.

    Revoked guilds are not restored. A guild that ejected the bot, or that an
    admin revoked by hand, comes back by re-invite and backfill, not by the
    gateway reconnecting.
    """
    from .models import ConfiguredGuild

    restored = 0
    for guild in ConfiguredGuild.objects.filter(state="degraded"):
        guild.state = "active"
        guild.state_since = now
        guild.standing_valid_until = None
        guild.save(update_fields=["state", "state_since", "standing_valid_until"])
        _audit_worker("restore_active", guild, detail="gateway reconnected")
        restored += 1
    return restored


def revoke_guild(guild, actor=None, now=None, reason: str = ""):
    """Collapse a guild's window at once - the plan's audited revoke-now.

    "Either way an instance admin, or an admin of the affected guild, can
    collapse the window at once with an audited revoke-now action." Who may call
    it is the admin's business; that this writes the state and the audit row
    together is this function's.

    `standing_valid_until` is cleared rather than left behind. A revoked guild
    grants nothing whatever the column says, but a stale expiry sitting on the
    row is the thing that made a previously degraded guild keep granting standing
    once, and leaving it would invite the same reading again.
    """
    from django.utils import timezone

    now = now or timezone.now()
    guild.state = "revoked"
    guild.state_since = now
    guild.standing_valid_until = None
    guild.save(update_fields=["state", "state_since", "standing_valid_until"])
    _audit_worker("revoke_now", guild, actor=actor, detail=reason or "revoke-now")
    return guild


def _audit_worker(action: str, guild, actor=None, detail: str = "") -> None:
    from .audit import record
    from .models import AuditLogEntry

    record(
        actor,
        action,
        guild._meta.model_name,
        guild.pk,
        AuditLogEntry.Outcome.ALLOWED,
        detail=f"guild {guild.guild_id}: {detail}",
    )


def bump_session_epoch(user, reason: str, actor=None) -> int:
    """End every one of this person's sessions, and nobody else's.

    The counter existed, the middleware read it, and nothing anywhere
    incremented it - so ban, suspension, deletion and sign-out-everywhere all
    left the person signed in, which is the whole mechanism this module opens by
    describing.

    The rows are deleted as well as invalidated. The epoch alone is enough to
    refuse the session on its next request, but a row nothing will ever accept
    again is a user id and a timestamp sitting in the table for up to ninety
    days.

    Ban and deletion reach the counter through `User.save()` instead, so that
    every path - the admin, a management command, the deletion flow - gets it
    without remembering to. This is the *explicit* sign-out-everywhere, and the
    account page it belongs on arrives with the rest of the account surface; it
    is here now because the primitive is what ban and deletion are built on.
    """
    from .models import Session, User

    user.session_epoch += 1
    User.objects.filter(pk=user.pk).update(session_epoch=user.session_epoch)
    Session.objects.filter(user=user).delete()
    _audit_user(user, "sign_out_everywhere", actor=actor, detail=reason)
    return user.session_epoch


def _audit_user(user, action: str, actor=None, detail: str = "") -> None:
    from .audit import record
    from .models import AuditLogEntry

    record(actor, action, "user", user.pk, AuditLogEntry.Outcome.ALLOWED, detail=detail)


def sweep_sessions(now=None) -> int:
    """Drop application session rows that can never be accepted again.

    Three shapes, and none of them is theoretical. A row whose Django session has
    already gone - expired, flushed, or cleared by `clearsessions` - is orphaned:
    nothing can present its key, and the middleware only ever reaches a row when
    a request carries the matching cookie, so an orphan is never looked at again
    and never deleted. A row past the absolute or idle lifetime is the same. A
    row belonging to a banned or deleted account is the same, and is the one that
    matters: it names who was signed in and when, for someone who asked to be
    forgotten.

    Register this alongside the membership sweep in the worker's task module.
    """
    from django.contrib.sessions.models import Session as DjangoSession
    from django.utils import timezone

    from .models import Session

    now = now or timezone.now()
    live_keys = set(
        DjangoSession.objects.filter(expire_date__gt=now).values_list("session_key", flat=True)
    )

    doomed = [
        row.session_key
        for row in Session.objects.select_related("user")
        if row.session_key not in live_keys
        or now - row.created_at >= ABSOLUTE_SESSION_LIFETIME
        or now - row.last_seen_at >= IDLE_SESSION_LIFETIME
        or row.issued_epoch != row.user.session_epoch
        or not row.user.is_active
    ]
    # Collected first and deleted in one statement, rather than deleted while the
    # cursor that produced them is still open.
    dropped, _ = Session.objects.filter(session_key__in=doomed).delete()
    return dropped
