"""The production settings the plan says are asserted in CI.

They were not: the settings module's own docstring claimed "asserted in CI
rather than trusted to review", and no test anywhere named a single one of them.
A share link is a bearer token in a URL, so a cookie that travels cross-site or
a page that can be framed is a real leak rather than a lint.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("SESSION_COOKIE_HTTPONLY", True),
        ("SESSION_COOKIE_SAMESITE", "Lax"),
        ("CSRF_COOKIE_SAMESITE", "Lax"),
        ("X_FRAME_OPTIONS", "DENY"),
        ("SECURE_CONTENT_TYPE_NOSNIFF", True),
        ("SECURE_REFERRER_POLICY", "same-origin"),
    ],
)
def test_pinned_security_settings(name: str, expected) -> None:
    assert getattr(settings, name) == expected


def test_the_proxy_ssl_header_is_set() -> None:
    """Caddy terminates TLS, so Django needs the forwarded header to know a
    request arrived over HTTPS. This is safe only while nothing but Caddy can
    reach the API, which the compose stack enforces."""
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_cookies_are_secure_outside_debug() -> None:
    assert settings.SESSION_COOKIE_SECURE is not settings.DEBUG
    assert settings.CSRF_COOKIE_SECURE is not settings.DEBUG


def test_the_search_path_names_both_schemas() -> None:
    """The live schema carries the rebuilt segment tables; public carries
    everything migrations own, including the jurisdiction table the pipeline
    queries unqualified."""
    options = settings.DATABASES["default"]["OPTIONS"]["options"]
    assert "live" in options and "public" in options


def test_the_admin_is_not_at_the_default_path() -> None:
    assert not settings.ADMIN_PATH.startswith("admin")


def test_the_swapped_schema_names_come_from_the_environment() -> None:
    """The database name was already an environment variable and the schema names
    were not, so two runs on one host reached into each other's `live` and
    `staging` and dropped them mid-test."""
    import importlib
    import os

    from django.conf import settings

    assert settings.SEGMENT_SCHEMA_RETIRED == f"{settings.SEGMENT_SCHEMA_LIVE}_old"

    module = importlib.import_module("config.settings")
    source = Path(module.__file__).read_text()
    assert 'os.environ.get("ROUTEMAKER_LIVE_SCHEMA"' in source
    assert 'os.environ.get("ROUTEMAKER_STAGING_SCHEMA"' in source
    assert os.environ.get("ROUTEMAKER_LIVE_SCHEMA") in (None, settings.SEGMENT_SCHEMA_LIVE)


def test_the_search_path_still_names_public_first_whatever_the_live_schema_is() -> None:
    """The ordering is the data-loss guard and must not depend on the name."""
    from django.conf import settings

    assert settings.SEARCH_PATH.split(",")[0] == "public"
    assert settings.SEGMENT_SCHEMA_LIVE in settings.SEARCH_PATH.split(",")


class TestEveryAuthDurationAgainstThePlansOwnFigure:
    """A flat table of literals, which is the only kind of test that could have
    caught this.

    Ten plan-named durations could each change by two orders of magnitude with
    431 tests green, and the mechanism was always the same: the test computed its
    boundary from the constant it was testing, so `now - IDLE_SESSION_LIFETIME -
    timedelta(minutes=1)` is idle for any value of the constant and proves only
    that a subtraction works. That is how `IDLE_SESSION_LIFETIME` shipped at 14
    days against the plan's 30 for three rounds with nobody able to have known.

    So these are written out as numbers, from the plan, with the plan's sentence
    against each one. Changing behaviour here should mean editing this table, in
    a diff somebody reads.
    """

    @pytest.mark.parametrize(
        ("dotted", "expected", "because"),
        [
            # "Sessions. ... 30 days idle, 90 days absolute."
            ("core.revocation.IDLE_SESSION_LIFETIME", timedelta(days=30), "30 days idle"),
            ("core.revocation.ABSOLUTE_SESSION_LIFETIME", timedelta(days=90), "90 days absolute"),
            # "the bot's gateway disconnected for 5 minutes or any guild marked
            # degraded" - the same five minutes raises the alert and marks.
            ("core.revocation.GATEWAY_ALERT_AFTER", timedelta(minutes=5), "5 minute alert"),
            # "honors cached standing for a grace period, default 72 hours
            # running from the alert rather than the disconnection"
            ("core.revocation.DEGRADED_WINDOW", timedelta(hours=72), "72 hour grace"),
            # "The maximum stale-grant window is 72 hours from the alert,
            # everywhere, and that is the only number."
            ("core.standing.MAX_STALE_GRANT", timedelta(hours=72), "72 hours everywhere"),
            ("core.standing.MAX_ROW_AGE", timedelta(hours=72), "maximum staleness bound"),
            # "Deliberate removal of the bot from a guild ends that guild's
            # standing within 15 minutes"
            ("core.standing.GUILD_REMOVAL_GRACE", timedelta(minutes=15), "15 minute removal"),
            # "rows for people who have never signed in are purged after 30 days"
            (
                "core.membership.PURGE_NEVER_SIGNED_IN_AFTER",
                timedelta(days=30),
                "30 day purge",
            ),
            # The OAuth state's own life. Not a plan figure; pinned because it is
            # the window a stolen authorize URL is replayable in.
            ("core.discord_oauth.STATE_LIFETIME", timedelta(minutes=10), "state lifetime"),
        ],
    )
    def test_the_duration_is_the_plans_figure(self, dotted, expected, because) -> None:
        import importlib

        module_name, _, attribute = dotted.rpartition(".")
        value = getattr(importlib.import_module(module_name), attribute)
        assert value == expected, f"{dotted} should be {expected} ({because}), not {value}"

    def test_the_cookie_clock_matches_the_absolute_cap_exactly(self) -> None:
        """Not merely "long enough". SESSION_COOKIE_AGE was unset, which means 14
        days - shorter than either figure the plan names - so Django's cookie
        expired first, `IDLE_SESSION_LIFETIME` could have been any value above a
        fortnight without a session living long enough to notice, and the 90-day
        absolute cap that `core.Session` exists to carry could never fire once.

        Equal rather than greater so the cookie and the row agree on when a
        session dies of old age, instead of one of them quietly being the real
        rule.
        """
        from core.revocation import ABSOLUTE_SESSION_LIFETIME

        assert settings.SESSION_COOKIE_AGE == int(ABSOLUTE_SESSION_LIFETIME.total_seconds())

    def test_the_cookie_clock_is_not_rolling(self) -> None:
        """SESSION_SAVE_EVERY_REQUEST re-issues the cookie with a fresh 90 days on
        every request, so a session in daily use would never reach its own
        expiry. A rolling cap is not a cap.

        Nothing is lost: the idle clock is `core.Session.last_seen_at`, which
        SessionEpochMiddleware writes per request whatever the session store does.
        """
        assert settings.SESSION_SAVE_EVERY_REQUEST is False

    def test_the_idle_clock_is_shorter_than_the_absolute_one(self) -> None:
        """Otherwise one of the two is unreachable, which is the shape of the
        whole defect."""
        from core.revocation import ABSOLUTE_SESSION_LIFETIME, IDLE_SESSION_LIFETIME

        assert IDLE_SESSION_LIFETIME < ABSOLUTE_SESSION_LIFETIME

    def test_the_degraded_window_never_exceeds_the_stated_maximum(self) -> None:
        """ "72 hours from the alert, everywhere, and that is the only number" -
        so these are one figure and not two that happen to agree."""
        from core.revocation import DEGRADED_WINDOW
        from core.standing import MAX_STALE_GRANT

        assert DEGRADED_WINDOW == MAX_STALE_GRANT
