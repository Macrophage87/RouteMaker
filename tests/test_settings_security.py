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
    queries unqualified.

    Checked against `settings.SEGMENT_SCHEMA_LIVE` rather than the literal
    "live": with ROUTEMAKER_LIVE_SCHEMA set, a bare substring check on "live"
    would still happen to pass against a name like "live_b", which is exactly
    the kind of accidental pass this cluster exists to remove.
    """
    options = settings.DATABASES["default"]["OPTIONS"]["options"]
    schemas = options.split("search_path=", 1)[1].split(",")
    assert schemas == ["public", settings.SEGMENT_SCHEMA_LIVE]


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


def load_settings_module(module_name: str = "config_settings_under_test"):
    """Execute `config/settings.py` again, under another name.

    Run rather than re-imported: the questions below are about what happens at
    import time under a particular environment, and replacing the entry in
    `sys.modules` would leave every later test importing a module built under
    this one's environment.
    """
    import importlib.util

    import config.settings as live

    spec = importlib.util.spec_from_file_location(module_name, live.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def derived(secret: str, module) -> bytes:
    import hashlib
    import hmac

    return hmac.new(secret.encode(), module.TOMBSTONE_KEY_LABEL, hashlib.sha256).digest()


class TestTheTombstoneKeyHasNoDevelopmentDefault:
    """The tombstone is an HMAC precisely so that a dump gives away nothing.

    It was keyed with `"insecure-development-tombstone-key"`, a literal in this
    repository, read from a variable (`TOMBSTONE_KEY`) that no compose service
    declared - so the default was not a fallback, it was the key. A Discord id
    is a structured 64-bit value whose candidate set any guild's member list
    resolves directly, so with the key public anyone holding a dump computes the
    tombstone of every candidate id and reads the ban list straight off. The
    empty-key guard inside `tombstone()` could never fire, because the default
    is not empty.
    """

    def test_settings_refuse_to_import_without_the_key(self, monkeypatch) -> None:
        """No default at all, so an unset variable is a process that does not
        start rather than a deployment quietly keying every tombstone with a
        published string."""
        from django.core.exceptions import ImproperlyConfigured

        monkeypatch.delenv("KEY_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ImproperlyConfigured, match="KEY_ENCRYPTION_KEY"):
            load_settings_module()

    def test_an_empty_key_is_refused_too(self, monkeypatch) -> None:
        """An exported-but-empty variable is the shape a missing SSM parameter
        actually takes in a container."""
        from django.core.exceptions import ImproperlyConfigured

        monkeypatch.setenv("KEY_ENCRYPTION_KEY", "")
        with pytest.raises(ImproperlyConfigured):
            load_settings_module()

    def test_the_key_is_derived_from_the_delivered_secret(self, monkeypatch) -> None:
        monkeypatch.setenv("KEY_ENCRYPTION_KEY", "a-test-key-encryption-key")
        module = load_settings_module()
        assert module.TOMBSTONE_KEY == derived("a-test-key-encryption-key", module)

    def test_it_is_not_the_encryption_key_itself(self, monkeypatch) -> None:
        """Domain separation. A tombstone is a public-by-design artefact of the
        dump, so an oracle over it must not be an oracle over the key that
        encrypts everything else; one HMAC over a constant label is
        HKDF-Expand with a single block, which is the standard way to split one
        delivered secret into subkeys."""
        monkeypatch.setenv("KEY_ENCRYPTION_KEY", "a-test-key-encryption-key")
        module = load_settings_module()
        assert module.TOMBSTONE_KEY != b"a-test-key-encryption-key"

    def test_a_different_secret_gives_a_different_key(self, monkeypatch) -> None:
        """Otherwise the derivation is decoration and the tombstones of two
        deployments are interchangeable."""
        monkeypatch.setenv("KEY_ENCRYPTION_KEY", "one")
        first = load_settings_module("config_settings_one").TOMBSTONE_KEY
        monkeypatch.setenv("KEY_ENCRYPTION_KEY", "two")
        second = load_settings_module("config_settings_two").TOMBSTONE_KEY
        assert first != second

    def test_the_live_setting_is_not_the_published_literal(self) -> None:
        """Against the settings this process is actually running under, not a
        re-executed copy."""
        assert settings.TOMBSTONE_KEY != b"insecure-development-tombstone-key"
        assert settings.TOMBSTONE_KEY != "insecure-development-tombstone-key"
        assert isinstance(settings.TOMBSTONE_KEY, bytes)
        assert len(settings.TOMBSTONE_KEY) == 32

    def test_the_settings_file_names_no_default_for_it(self) -> None:
        """The literal is gone from the file as well as from the value, so a
        reader cannot find it and wonder which one is live."""
        import config.settings as live

        source = Path(live.__file__).read_text()
        assert "insecure-development-tombstone-key" not in source

    def test_the_tombstone_changes_with_the_key(self) -> None:
        """The property the whole construction rests on: without the key, a
        candidate Discord id resolves to nothing."""
        from core.revocation import tombstone

        assert tombstone(4242, settings.TOMBSTONE_KEY) != tombstone(4242, b"another-key")


class TestApplicationLogsGoSomewhereReadable:
    """Django's default sends application logs nowhere a container operator can
    read, so a deployment's only diagnostics were whatever a traceback produced.
    """

    def test_a_console_handler_is_configured(self) -> None:
        assert settings.LOGGING["handlers"]["console"]["class"] == "logging.StreamHandler"

    @pytest.mark.parametrize("name", ["core", "pipeline"])
    def test_each_application_package_logs_at_info(self, name: str) -> None:
        logger = settings.LOGGING["loggers"][name]
        assert logger["level"] == "INFO"
        assert "console" in logger["handlers"]

    def test_the_configuration_is_the_one_django_resolved(self) -> None:
        """Read back through the logging module rather than from the dict, so a
        LOGGING setting Django never applied fails here."""
        import logging

        assert logging.getLogger("core").getEffectiveLevel() == logging.INFO
