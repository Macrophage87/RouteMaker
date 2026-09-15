"""Django settings.

The security-relevant values here are not defaults to be revisited later: the
threat model in the plan includes routes for unpermitted rides, so the cookie,
host, and proxy settings are asserted in CI rather than trusted to review.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-development-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The live/staging schema pair the weekly rebuild swaps between.
SEGMENT_SCHEMA_LIVE = "live"
SEGMENT_SCHEMA_STAGING = "staging"

# The search path has to name both. `live` carries the rebuilt segment tables,
# which are unmanaged and owned by the pipeline; `public` carries everything
# migrations own, including the jurisdiction table the pipeline queries
# unqualified. Without this the unmanaged Segment model is unreadable through
# the ORM in every environment - it resolves to a bare `segment` that exists in
# no schema on the path - and nothing catches it, because the database tests
# reach the same tables through schema-qualified raw SQL.
#
# Set as a connection option rather than only on the role, so a checkout runs
# correctly without a manual grant; the deploy also runs
# `ALTER ROLE ... IN DATABASE ... SET search_path` so a psql session and any
# tooling that bypasses Django land on the same path.
SEARCH_PATH = f"{SEGMENT_SCHEMA_LIVE},public"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("PGDATABASE", "routemaker"),
        "USER": os.environ.get("PGUSER", "routemaker"),
        "PASSWORD": os.environ.get("PGPASSWORD", "routemaker"),
        "HOST": os.environ.get("PGHOST", "127.0.0.1"),
        "PORT": os.environ.get("PGPORT", "5432"),
        "OPTIONS": {"options": f"-c search_path={SEARCH_PATH}"},
        # Persistent connections, which the latency budget assumes: at 0 Django
        # opens and closes one per request and pays a connect round-trip on the
        # preview path.
        "CONN_MAX_AGE": int(os.environ.get("DJANGO_CONN_MAX_AGE", "60")),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"

# Asserted in CI. A share link is a bearer token in a URL, so a cookie that
# travels cross-site or a page that can be framed is a real leak, not a lint.
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
