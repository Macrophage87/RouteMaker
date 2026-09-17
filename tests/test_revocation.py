from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.revocation import (
    ABSOLUTE_SESSION_LIFETIME,
    DEGRADED_WINDOW,
    GATEWAY_ALERT_AFTER,
    IDLE_SESSION_LIFETIME,
    SessionRecord,
    degraded_window,
    should_mark_degraded,
    tombstone,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def session(**kwargs) -> SessionRecord:
    return SessionRecord(
        key=kwargs.pop("key", "abc"),
        user_id=kwargs.pop("user_id", 1),
        issued_epoch=kwargs.pop("issued_epoch", 1),
        created_at=kwargs.pop("created_at", NOW - timedelta(days=1)),
        last_seen_at=kwargs.pop("last_seen_at", NOW - timedelta(minutes=1)),
    )


class TestSessionEpoch:
    def test_bumping_the_epoch_invalidates_the_session(self) -> None:
        """One write revokes that user's sessions and nobody else's. Django's
        session table has no user column, so without this the only global lever
        is rotating the secret key, which signs everybody out."""
        assert session().is_valid(current_epoch=1, now=NOW)
        assert not session().is_valid(current_epoch=2, now=NOW)

    def test_absolute_lifetime_is_enforced(self) -> None:
        """Django implements idle expiry natively but not an absolute cap."""
        old = session(created_at=NOW - ABSOLUTE_SESSION_LIFETIME - timedelta(hours=1))
        assert not old.is_valid(current_epoch=1, now=NOW)

    def test_idle_lifetime_is_enforced(self) -> None:
        idle = session(last_seen_at=NOW - IDLE_SESSION_LIFETIME - timedelta(hours=1))
        assert not idle.is_valid(current_epoch=1, now=NOW)


class TestTombstone:
    def test_tombstone_is_keyed(self) -> None:
        """A Discord id has an enumerable candidate set, so an unkeyed hash gives
        no privacy against anyone holding a dump."""
        a = tombstone(123456789, key=b"secret-one")
        b = tombstone(123456789, key=b"secret-two")
        assert a != b

    def test_tombstone_is_stable_for_ban_enforcement(self) -> None:
        key = b"secret"
        assert tombstone(123456789, key) == tombstone(123456789, key)

    def test_unkeyed_tombstone_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unkeyed hash is reversible"):
            tombstone(123456789, key=b"")


class TestDegradedWindow:
    def test_window_runs_from_the_alert_not_from_a_grace_period(self) -> None:
        """Stacking two windows would leave the deployment carrying stale grants
        for twice as long as a single lost guild does."""
        assert degraded_window(NOW) == NOW + DEGRADED_WINDOW

    def test_mark_uses_the_same_threshold_as_the_alert(self) -> None:
        assert should_mark_degraded(NOW - GATEWAY_ALERT_AFTER, NOW)
        assert not should_mark_degraded(NOW - GATEWAY_ALERT_AFTER + timedelta(seconds=1), NOW)

    def test_maximum_stale_grant_is_one_window_not_two(self) -> None:
        """72 hours from the alert, everywhere, and that is the only number."""
        from core.standing import MAX_STALE_GRANT

        lapses_at = degraded_window(NOW)
        assert lapses_at - NOW == MAX_STALE_GRANT


# Everything below drives real rows. The predicates above are correct and were
# always correct; what they lacked was anything that ever wrote the column they
# describe, which is a defect no test of a predicate can see.

db = pytest.mark.django_db(transaction=True)


@pytest.fixture
def guild(db):
    from core.models import ConfiguredGuild

    return ConfiguredGuild.objects.create(guild_id=7000, name="Test Club")


@pytest.fixture
def guild_admin(db, guild):
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from core.auth_backend import attach_standing
    from core.models import CachedMembership, RoleMapping

    user = get_user_model().objects.create(discord_user_id=7001)
    RoleMapping.objects.create(
        guild=guild, role_id=7, permission=RoleMapping.Permission.GUILD_ADMIN
    )
    CachedMembership.objects.create(
        discord_user_id=7001, guild=guild, role_ids=[7], last_confirmed=timezone.now()
    )
    attach_standing(user)
    assert user.is_staff, "the standing this is about must exist before it is taken away"
    return user


@db
class TestMarkingGuildsDegraded:
    """`should_mark_degraded` and `degraded_window` had no callers and nothing
    wrote `ConfiguredGuild.state`, so no guild could ever leave `active`.

    A grace period is two things - a predicate and a transition into the state it
    guards - and only the predicate existed. The plan makes the degraded window a
    phase 1 deliverable.
    """

    def test_a_silent_gateway_marks_every_active_guild(self, guild) -> None:
        from django.utils import timezone

        from core.revocation import GATEWAY_ALERT_AFTER, mark_degraded_guilds

        now = timezone.now()
        silent_since = now - GATEWAY_ALERT_AFTER - timedelta(minutes=1)
        marked, restored = mark_degraded_guilds(now=now, last_event=silent_since)

        assert (marked, restored) == (1, 0)
        guild.refresh_from_db()
        assert guild.state == "degraded"

    def test_the_window_runs_from_the_alert_and_not_from_now(self, guild) -> None:
        """Stacking the alert threshold and the window would leave the whole
        deployment carrying stale grants for longer than a single lost guild
        does. 72 hours from the alert is the only number."""
        from django.utils import timezone

        from core.revocation import (
            DEGRADED_WINDOW,
            GATEWAY_ALERT_AFTER,
            mark_degraded_guilds,
        )

        now = timezone.now()
        silent_since = now - timedelta(hours=3)
        mark_degraded_guilds(now=now, last_event=silent_since)

        guild.refresh_from_db()
        alert_at = silent_since + GATEWAY_ALERT_AFTER
        assert guild.state_since == alert_at
        assert guild.standing_valid_until == alert_at + DEGRADED_WINDOW

    def test_a_gateway_that_is_talking_marks_nothing(self, guild) -> None:
        from django.utils import timezone

        from core.revocation import mark_degraded_guilds

        now = timezone.now()
        marked, _restored = mark_degraded_guilds(now=now, last_event=now - timedelta(seconds=30))
        assert marked == 0
        guild.refresh_from_db()
        assert guild.state == "active"

    def test_never_having_heard_from_the_gateway_counts_as_silence(self, guild) -> None:
        """Failing open would mean a deployment whose bot never started grants
        full standing to everyone forever."""
        from core.revocation import mark_degraded_guilds

        marked, _restored = mark_degraded_guilds()
        assert marked == 1
        guild.refresh_from_db()
        assert guild.state == "degraded"

    def test_a_guild_already_degraded_is_not_re_marked(self, guild) -> None:
        """Re-marking on every tick would slide `state_since` forward and make
        the ceiling in `grants_standing` unreachable - the same bug as trusting
        the column."""
        from django.utils import timezone

        from core.revocation import mark_degraded_guilds

        now = timezone.now()
        mark_degraded_guilds(now=now, last_event=now - timedelta(hours=3))
        guild.refresh_from_db()
        first_mark = guild.state_since

        marked, _restored = mark_degraded_guilds(
            now=now + timedelta(hours=1), last_event=now - timedelta(hours=3)
        )
        assert marked == 0
        guild.refresh_from_db()
        assert guild.state_since == first_mark

    def test_the_gateway_coming_back_restores_active(self, guild) -> None:
        """Without this one blip degrades the deployment permanently: nothing
        else writes the column back, so every guild lapses 72 hours later and the
        repair is an UPDATE against production."""
        from django.utils import timezone

        from core.revocation import mark_degraded_guilds

        now = timezone.now()
        mark_degraded_guilds(now=now, last_event=now - timedelta(hours=3))

        marked, restored = mark_degraded_guilds(now=now, last_event=now)
        assert (marked, restored) == (0, 1)
        guild.refresh_from_db()
        assert guild.state == "active"
        assert guild.standing_valid_until is None

    def test_a_revoked_guild_is_never_restored_by_a_reconnect(self, guild) -> None:
        """Revocation is a decision, not a symptom. A guild that ejected the bot
        comes back by re-invite and backfill."""
        from django.utils import timezone

        from core.revocation import mark_degraded_guilds, revoke_guild

        now = timezone.now()
        revoke_guild(guild, now=now)
        mark_degraded_guilds(now=now, last_event=now)

        guild.refresh_from_db()
        assert guild.state == "revoked"

    def test_a_marked_guild_still_grants_inside_its_window_and_not_after(
        self, guild, guild_admin
    ) -> None:
        """End to end through the resolver, which is the only thing that makes
        the column mean anything."""
        from django.utils import timezone

        from core.auth_backend import attach_standing
        from core.revocation import DEGRADED_WINDOW, mark_degraded_guilds

        now = timezone.now()
        mark_degraded_guilds(now=now, last_event=now - timedelta(hours=3))

        attach_standing(guild_admin, now)
        assert guild_admin.is_staff, "cached standing is honoured inside the window"

        attach_standing(guild_admin, now + DEGRADED_WINDOW + timedelta(minutes=1))
        assert not guild_admin.is_staff, "and lapses after it"

    def test_marking_writes_an_audit_row(self, guild) -> None:
        from django.utils import timezone

        from core.models import AuditLogEntry
        from core.revocation import mark_degraded_guilds

        now = timezone.now()
        mark_degraded_guilds(now=now, last_event=now - timedelta(hours=3))

        entry = AuditLogEntry.objects.get(action="mark_degraded")
        assert entry.outcome == AuditLogEntry.Outcome.ALLOWED
        assert entry.actor is None, "a worker has no request and therefore no actor"
        assert str(guild.guild_id) in entry.detail

    def test_the_heartbeat_the_bot_writes_is_what_it_reads(self, guild) -> None:
        """The deployment-wide clock is a ScheduledRun row, so the existing
        "nothing has succeeded lately" alert reads it with no new table."""
        from django.utils import timezone

        from core.models import ScheduledRun
        from core.revocation import GATEWAY_HEARTBEAT_TASK, mark_degraded_guilds

        now = timezone.now()
        ScheduledRun.objects.create(
            task=GATEWAY_HEARTBEAT_TASK, started_at=now, finished_at=now, succeeded=True
        )
        marked, _restored = mark_degraded_guilds(now=now)
        assert marked == 0

        ScheduledRun.objects.all().delete()
        ScheduledRun.objects.create(
            task=GATEWAY_HEARTBEAT_TASK,
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=3),
            succeeded=True,
        )
        marked, _restored = mark_degraded_guilds(now=now)
        assert marked == 1

    def test_a_failed_heartbeat_still_counts_as_the_bot_existing(self, guild) -> None:
        """ "Any row counts, not only a successful one."

        The gate answers a different question from the window: not "is the
        gateway healthy" but "is there a bot on this deployment at all". A
        heartbeat task that ran and failed is a bot that exists and is in
        trouble, which is precisely the outage the degraded window is for -
        while filtering the gate to successful rows would read the same
        deployment as one that has never had a bot and leave every guild at full
        standing through the outage.

        Every other test here writes `succeeded=True`, so narrowing the gate to
        successes changed nothing anybody could see.
        """
        from django.utils import timezone

        from core.models import ScheduledRun
        from core.revocation import GATEWAY_HEARTBEAT_TASK, gateway_has_ever_reported

        assert not gateway_has_ever_reported()

        now = timezone.now()
        ScheduledRun.objects.create(
            task=GATEWAY_HEARTBEAT_TASK,
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=3),
            succeeded=False,
            detail="the gateway connection dropped",
        )
        assert gateway_has_ever_reported()


@db
class TestRevokeNow:
    def test_revoking_ends_standing_at_once(self, guild, guild_admin) -> None:
        from django.utils import timezone

        from core.auth_backend import attach_standing
        from core.revocation import revoke_guild

        now = timezone.now()
        revoke_guild(guild, now=now, reason="the bot was kicked")

        guild.refresh_from_db()
        assert guild.state == "revoked"
        attach_standing(guild_admin, now)
        assert not guild_admin.is_staff

    def test_it_clears_a_window_left_behind_by_a_degraded_spell(self, guild) -> None:
        """A revoked guild grants nothing whatever the column says, but a stale
        expiry on the row is what made a previously degraded guild keep granting
        standing once, and leaving it invites the same reading again."""
        from django.utils import timezone

        from core.revocation import mark_degraded_guilds, revoke_guild

        now = timezone.now()
        mark_degraded_guilds(now=now, last_event=now - timedelta(hours=3))
        guild.refresh_from_db()
        assert guild.standing_valid_until is not None

        revoke_guild(guild, now=now)
        guild.refresh_from_db()
        assert guild.standing_valid_until is None

    def test_it_is_audited_with_its_actor(self, guild, guild_admin) -> None:
        from core.models import AuditLogEntry
        from core.revocation import revoke_guild

        revoke_guild(guild, actor=guild_admin, reason="revoke-now from the admin")
        entry = AuditLogEntry.objects.get(action="revoke_now")
        assert entry.actor == guild_admin
        assert entry.outcome == AuditLogEntry.Outcome.ALLOWED


@db
class TestSessionEpochIsActuallyBumped:
    """It was a counter the middleware read and nothing anywhere incremented."""

    def signed_in(self, user):
        from django.contrib.sessions.backends.db import SessionStore
        from django.utils import timezone

        from core.models import Session

        store = SessionStore()
        store.create()
        now = timezone.now()
        Session.objects.create(
            session_key=store.session_key,
            user=user,
            issued_epoch=user.session_epoch,
            created_at=now,
            last_seen_at=now,
        )
        return store

    def test_signing_out_everywhere_ends_every_session(self, guild_admin) -> None:
        from core.auth_backend import session_is_current
        from core.models import Session
        from core.revocation import bump_session_epoch

        self.signed_in(guild_admin)
        self.signed_in(guild_admin)
        assert Session.objects.filter(user=guild_admin).count() == 2
        issued_under = guild_admin.session_epoch

        bump_session_epoch(guild_admin, reason="sign out everywhere")

        assert not Session.objects.filter(user=guild_admin).exists()
        assert guild_admin.session_epoch == issued_under + 1
        assert not session_is_current(guild_admin, issued_under, timezone_now(), timezone_now())

    def test_it_is_written_to_the_database_and_not_only_the_instance(self, guild_admin) -> None:
        """A bump that lives on one in-memory object revokes nothing: the
        middleware reads the row."""
        from core.revocation import bump_session_epoch

        before = guild_admin.session_epoch
        bump_session_epoch(guild_admin, reason="sign out everywhere")
        guild_admin.refresh_from_db()
        assert guild_admin.session_epoch == before + 1

    def test_it_touches_nobody_elses_sessions(self, guild_admin) -> None:
        """One write revokes this person's sessions and nobody else's, which is
        the whole reason for the counter rather than rotating the secret key."""
        from django.contrib.auth import get_user_model

        from core.models import Session
        from core.revocation import bump_session_epoch

        other = get_user_model().objects.create(discord_user_id=7002)
        self.signed_in(other)
        self.signed_in(guild_admin)

        bump_session_epoch(guild_admin, reason="ban")
        assert Session.objects.filter(user=other).count() == 1

    def test_it_is_audited(self, guild_admin) -> None:
        from core.models import AuditLogEntry
        from core.revocation import bump_session_epoch

        bump_session_epoch(guild_admin, reason="ban")
        entry = AuditLogEntry.objects.get(action="sign_out_everywhere")
        assert entry.object_id == str(guild_admin.pk)


@db
class TestTheSessionSweep:
    """Orphaned `core.Session` rows were never cleaned up.

    The middleware only ever reaches a row when a request carries the matching
    cookie, so a row whose Django session has gone is never looked at and never
    deleted - a user id and two timestamps left in the table indefinitely, for a
    deployment whose sensitive data is who organizes with whom.
    """

    def row(self, user, *, key, created_ago=timedelta(0), seen_ago=timedelta(0), live=True):
        from django.contrib.sessions.models import Session as DjangoSession
        from django.utils import timezone

        from core.models import Session

        now = timezone.now()
        if live:
            DjangoSession.objects.create(
                session_key=key, session_data="", expire_date=now + timedelta(days=1)
            )
        return Session.objects.create(
            session_key=key,
            user=user,
            issued_epoch=user.session_epoch,
            created_at=now - created_ago,
            last_seen_at=now - seen_ago,
        )

    def test_a_live_session_is_kept(self, guild_admin) -> None:
        from core.models import Session
        from core.revocation import sweep_sessions

        self.row(guild_admin, key="live-one")
        assert sweep_sessions() == 0
        assert Session.objects.count() == 1

    def test_an_orphan_goes(self, guild_admin) -> None:
        from core.models import Session
        from core.revocation import sweep_sessions

        self.row(guild_admin, key="orphan", live=False)
        assert sweep_sessions() == 1
        assert not Session.objects.exists()

    def test_a_session_past_the_absolute_cap_goes(self, guild_admin) -> None:
        from core.models import Session
        from core.revocation import ABSOLUTE_SESSION_LIFETIME, sweep_sessions

        self.row(
            guild_admin,
            key="ancient",
            created_ago=ABSOLUTE_SESSION_LIFETIME + timedelta(minutes=1),
        )
        assert sweep_sessions() == 1
        assert not Session.objects.exists()

    def test_an_idle_session_goes(self, guild_admin) -> None:
        from core.models import Session
        from core.revocation import IDLE_SESSION_LIFETIME, sweep_sessions

        self.row(guild_admin, key="idle", seen_ago=IDLE_SESSION_LIFETIME + timedelta(minutes=1))
        assert sweep_sessions() == 1
        assert not Session.objects.exists()

    def test_a_banned_accounts_rows_go(self, guild_admin) -> None:
        """The one that matters: it names who was signed in and when, for
        somebody the deployment has ended."""
        from core.models import Session
        from core.revocation import sweep_sessions

        self.row(guild_admin, key="banned")
        guild_admin.is_banned = True
        guild_admin.save(update_fields=["is_banned"])

        assert sweep_sessions() == 1
        assert not Session.objects.exists()

    def test_a_flag_set_without_an_epoch_bump_still_sweeps(self, guild_admin) -> None:
        """The `is_active` clause on its own.

        `User.save()` bumps the epoch when a ban lands, so every other test here
        bans through both clauses at once and either one could be deleted with
        the suite green. A flag written by `.update()` - a hand-written UPDATE
        against production, a fixture, a data migration - emits no signal and
        goes through no save, so the epoch is untouched and this clause is the
        only thing that drops the row. It is also the clause `session_is_current`
        keeps for exactly the same case.
        """
        from core.models import Session, User
        from core.revocation import sweep_sessions

        self.row(guild_admin, key="updated-flag")
        User.objects.filter(pk=guild_admin.pk).update(is_banned=True)
        assert User.objects.get(pk=guild_admin.pk).session_epoch == guild_admin.session_epoch, (
            "the point of this case is that nothing bumped the epoch"
        )

        assert sweep_sessions() == 1
        assert not Session.objects.exists()

    def test_an_epoch_bump_alone_still_sweeps(self, guild_admin) -> None:
        """And the epoch clause on its own.

        Sign-out-everywhere bumps the epoch and touches neither flag, so the
        account stays perfectly active and the row is unacceptable only because
        of the counter it was issued under. Deleting the epoch comparison left
        every test in this class green, because they all banned as well.
        """
        from core.models import Session
        from core.revocation import sweep_sessions

        self.row(guild_admin, key="stale-epoch")
        guild_admin.session_epoch += 1
        guild_admin.save(update_fields=["session_epoch"])
        assert guild_admin.is_active, "nothing about this account is banned or deleted"

        assert sweep_sessions() == 1
        assert not Session.objects.exists()


def timezone_now():
    from django.utils import timezone

    return timezone.now()
