"""The production settings the plan says are asserted in CI.

They were not: the settings module's own docstring claimed "asserted in CI
rather than trusted to review", and no test anywhere named a single one of them.
A share link is a bearer token in a URL, so a cookie that travels cross-site or
a page that can be framed is a real leak rather than a lint.
"""

from __future__ import annotations

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
