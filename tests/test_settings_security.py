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


class TestTheAdminBasemapHasNoPublicDefault:
    """PLAN:15 ends "Do not use the public OpenStreetMap tile servers", and
    PLAN:52 names the GeoDjango map widget as one "configured against the
    self-hosted basemap rather than its default, which would otherwise call the
    public OpenStreetMap tile servers this plan rules out".

    The self-hosted basemap does not exist yet - the PMTiles extract and the
    renderer are unbuilt - so the setting that would point at it is optional and
    empty, and that is the whole of the rule: there is no value a default could
    honestly carry, and every value it could dishonestly carry is either the
    thing the plan forbids or a path this deployment does not serve.
    """

    def source(self) -> str:
        import importlib

        return Path(importlib.import_module("config.settings").__file__).read_text()

    def test_it_is_read_from_the_environment_with_an_empty_default(self) -> None:
        assert settings.ADMIN_BASEMAP_TILE_URL == ""
        assert 'os.environ.get("ADMIN_BASEMAP_TILE_URL", "")' in self.source(), (
            "the default has to be the empty string, in the source, where a "
            "change to it is a diff somebody reads"
        )

    def test_no_setting_names_a_tile_server_or_a_cdn(self) -> None:
        """Not just this one setting: the whole module. A default that moved
        into a different name would be the same finding under a new spelling.

        `openstreetmap.org` covers `tile.openstreetmap.org` and its `[abc].`
        siblings, which is what `ol.source.OSM` resolves to; the CDN hosts are
        the ones GeoDjango's own widget media names.
        """
        source = self.source().lower()
        for forbidden in (
            "openstreetmap.org",
            "tile.osm",
            "cdn.jsdelivr.net",
            "unpkg.com",
            "cdnjs.cloudflare.com",
            "basemaps.arcgis.com",
            "vis.earthdata.nasa.gov",
        ):
            assert forbidden not in source, f"settings.py names {forbidden}"

    def test_the_env_example_offers_it_only_commented_out(self) -> None:
        """An operator copies this file and fills in the `change-me`s. A live
        line here would be a value they did not choose, pointing somewhere this
        deployment has not earned the right to call."""
        repo = Path(__file__).resolve().parents[1]
        lines = [
            line
            for line in (repo / ".env.example").read_text().splitlines()
            if "ADMIN_BASEMAP_TILE_URL" in line
        ]
        assert lines, ".env.example does not mention the setting at all"
        live = [line for line in lines if not line.lstrip().startswith("#")]
        assert not live, f".env.example sets it for the operator: {live}"


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


class TestTheSourceExtractsThreeKnobs:
    """The three settings `pipeline.source` is driven by, and the box it clips
    to. Every one of them was reachable only through a test that passed the
    figure in itself, so the deployment's own value was never asserted.
    """

    def test_the_coverage_box_is_the_region_this_deployment_clips_to(self) -> None:
        """West, south, east, north, named corner by corner rather than against
        a constant read out of the same module.

        The box is not decoration: the elevation stage fetches every one-degree
        HGT tile it touches and the extract stage clips the merged PBF to it, so
        a corner moved inward silently drops map - Frederick and Leesburg to the
        north-west, Annapolis to the east, Fredericksburg to the south - out of
        a graph that still builds, still validates and still routes.
        """
        assert settings.COVERAGE_BBOX == (-78.0, 38.2, -76.3, 39.5)

        west, south, east, north = settings.COVERAGE_BBOX
        assert west == -78.0, "Frederick and Leesburg to the north-west"
        assert south == 38.2, "Fredericksburg to the south"
        assert east == -76.3, "Annapolis to the east"
        assert north == 39.5
        assert west < east and south < north, "and it is a box, in that order"

    def test_the_extract_is_stale_at_six_days_not_seven(self) -> None:
        """Just under the weekly cadence, and the difference between the two
        figures is the whole behaviour: at seven the ordinary weekly run accepts
        last week's snapshot and the map ages a week every week, while below six
        a retry in the same week pulls 1-2 GB again.

        The settings value, not only `source.DEFAULT_MAX_AGE`: the rebuild
        passes this one, and the module default it is meant to agree with is
        asserted separately in `tests/test_source.py`.
        """
        assert settings.SOURCE_EXTRACT_MAX_AGE == timedelta(days=6)

        from pipeline import source

        assert source.DEFAULT_MAX_AGE == settings.SOURCE_EXTRACT_MAX_AGE, (
            "the module default and the setting the rebuild passes are one figure"
        )

    def test_the_six_day_figure_is_the_default_and_not_this_environment(self, monkeypatch) -> None:
        """Read back through a fresh import with the variable unset, so the
        assertion above is about the literal in `config/settings.py` rather than
        about whatever the test runner happens to export."""
        monkeypatch.delenv("SOURCE_EXTRACT_MAX_AGE_DAYS", raising=False)
        assert load_settings_module("settings_default_max_age").SOURCE_EXTRACT_MAX_AGE == timedelta(
            days=6
        )

    @pytest.mark.parametrize(
        ("value", "forced"),
        [("1", True), ("", False), ("0", False), ("true", False), ("yes", False)],
    )
    def test_a_forced_refresh_is_the_one_value(self, monkeypatch, value, forced) -> None:
        """A rebuild that ignores the extract on disk downloads 1-2 GB, so the
        override is one exact value rather than anything truthy: a variable left
        at `0` or `false` by an operator who meant to turn it off must not force
        a refresh every week.
        """
        monkeypatch.setenv("SOURCE_EXTRACT_FORCE_REFRESH", value)
        module = load_settings_module(f"settings_force_refresh_{value or 'empty'}")
        assert module.SOURCE_EXTRACT_FORCE_REFRESH is forced

    def test_nothing_forces_a_refresh_when_the_variable_is_absent(self, monkeypatch) -> None:
        monkeypatch.delenv("SOURCE_EXTRACT_FORCE_REFRESH", raising=False)
        module = load_settings_module("settings_force_refresh_absent")
        assert module.SOURCE_EXTRACT_FORCE_REFRESH is False
        assert settings.SOURCE_EXTRACT_FORCE_REFRESH is False, "and not in this deployment either"


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

    @pytest.mark.parametrize("name", ["core", "pipeline", "config"])
    def test_each_application_package_logs_at_info(self, name: str) -> None:
        logger = settings.LOGGING["loggers"][name]
        assert logger["level"] == "INFO"
        assert "console" in logger["handlers"]

    def test_the_configuration_is_the_one_django_resolved(self) -> None:
        """Read back through the logging module rather than from the dict, so a
        LOGGING setting Django never applied fails here."""
        import logging

        assert logging.getLogger("core").getEffectiveLevel() == logging.INFO

    def test_a_record_from_a_scheduled_task_reaches_the_console_handler(self) -> None:
        """The tasks live in `config.procrastinate`, and the line that explains
        why a five-minute sweep is touching nothing - "no gateway heartbeat has
        ever been recorded, so the degraded mark is held" - is logged from there
        at INFO. With only `core` and `pipeline` named, it fell to `root` at
        WARNING and reached nobody, so the operator of a deployment whose guilds
        were not being marked could not tell the arming state from a dead task.

        Asserted by emitting a record and catching it at the configured handler
        rather than by reading the dictionary back: a logger listed in LOGGING
        whose records still go nowhere is the failure this is about.
        """
        import io
        import logging

        logger = logging.getLogger("config.procrastinate")
        assert logger.getEffectiveLevel() <= logging.INFO

        handlers = [h for h in logging.getLogger("config").handlers]
        assert handlers, "the package logger carries the console handler itself"
        handler = handlers[0]
        assert isinstance(handler, logging.StreamHandler)

        captured = io.StringIO()
        original, handler.stream = handler.stream, captured
        try:
            logger.info("no gateway heartbeat has ever been recorded")
        finally:
            handler.stream = original

        written = captured.getvalue()
        assert "no gateway heartbeat has ever been recorded" in written
        assert "config.procrastinate" in written, "the formatter names the logger"

    def test_the_task_module_logs_through_that_logger(self) -> None:
        """The test above is only worth anything if the task really does log
        under this package. `degraded_guild_sweep` takes its logger from
        `__name__`, which is `config.procrastinate`."""
        from pathlib import Path

        import config.procrastinate as tasks

        assert tasks.__name__ == "config.procrastinate"
        source = Path(tasks.__file__).read_text()
        assert "logging.getLogger(__name__)" in source


def test_the_test_settings_relax_nothing() -> None:
    """`config.test_settings` is the production settings plus the one secret
    they refuse to import without, and its own docstring says so: "Nothing else
    is overridden. A test settings module that quietly relaxed a security
    setting would make the assertions in this file assertions about itself."

    Nothing checked it. So this compares the two module namespaces over every
    uppercase name - which is every Django setting - and allows a difference in
    exactly the two names that the supplied key is allowed to move.

    The comparison is against the modules rather than against
    `django.conf.settings`, because the live settings object is whichever of the
    two this process was started with, so asking it can only ever agree with
    itself.
    """
    import config.settings as production
    import config.test_settings as under_test

    # The only names a test value of KEY_ENCRYPTION_KEY is allowed to move: the
    # key itself is never a module attribute (it is read, used and deleted), and
    # TOMBSTONE_KEY is derived from it.
    ALLOWED = {"KEY_ENCRYPTION_KEY", "TOMBSTONE_KEY"}

    def public_settings(module) -> dict:
        return {
            name: value
            for name, value in vars(module).items()
            if name.isupper() and not name.startswith("_")
        }

    theirs = public_settings(production)
    ours = public_settings(under_test)

    added = sorted(set(ours) - set(theirs) - ALLOWED)
    assert not added, f"config.test_settings invents settings the deployment has not: {added}"

    missing = sorted(set(theirs) - set(ours) - ALLOWED)
    assert not missing, f"config.test_settings drops settings the deployment has: {missing}"

    differing = sorted(
        name
        for name in set(theirs) & set(ours)
        if name not in ALLOWED and ours[name] != theirs[name]
    )
    assert not differing, (
        "config.test_settings overrides these, so every assertion in this file about "
        f"them is an assertion about the test settings and not the deployment: {differing}"
    )
