"""The production settings the plan says are asserted in CI.

They were not: the settings module's own docstring claimed "asserted in CI
rather than trusted to review", and no test anywhere named a single one of them.
A share link is a bearer token in a URL, so a cookie that travels cross-site or
a page that can be framed is a real leak rather than a lint.
"""

from __future__ import annotations

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
