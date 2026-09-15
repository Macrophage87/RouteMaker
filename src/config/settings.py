"""Django settings.

The security-relevant values here are not defaults to be revisited later: the
threat model in the plan includes routes for unpermitted rides, so the cookie,
host, and proxy settings are asserted in CI rather than trusted to review.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-development-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # After authentication, because it needs request.user: an epoch that nothing
    # reads revokes nothing, so without this ban, suspension, deletion and
    # sign-out-everywhere all leave the person signed in.
    "core.middleware.SessionEpochMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.request",
            ]
        },
    }
]

# The custom user carries no usable password, no stored is_staff and no stored
# is_superuser. Django's default carries all three, and each is a credential or
# grant class this threat model does not have.
AUTH_USER_MODEL = "core.User"

# No ModelBackend: there is no password to authenticate, and with no superuser
# and no auth_permission rows its has_perm would answer false for everyone, so
# the admin would render empty.
AUTHENTICATION_BACKENDS = ["core.auth_backend.DiscordStandingBackend"]

# The admin is reached only through a Discord session, under a path that is not
# guessed at. That is obscurity rather than a control, and it is not what
# protects it - the disabled login, derived staff and per-object checks are.
ADMIN_PATH = os.environ.get("DJANGO_ADMIN_PATH", "internal-8f3a/")

# Everything with state in it lives on the separate data volume, so nothing
# durable sits on the root volume and the code directory holds no data. The
# scheduled tasks resolve their paths from here rather than from their own
# environment lookups, so one variable moves all of them together.
DATA_ROOT = Path(os.environ.get("DATA_ROOT", BASE_DIR / "data"))
REBUILD_WORK_DIR = DATA_ROOT / "rebuild"
REBUILD_SOURCE_PBF = DATA_ROOT / "extracts" / "source.osm.pbf"
REBUILD_REFERENCE_DIR = DATA_ROOT / "reference"
BACKUP_DIR = DATA_ROOT / "backups"

# Discord login, identify scope only. The client secret is used once per login to
# exchange an authorization code and is never written anywhere; no per-user
# Discord token is retained at all.
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")

# Keys a ban tombstone. A Discord id is a structured 64-bit value whose candidate
# set any guild's member list resolves directly, so an unkeyed hash of one gives
# no privacy against whoever holds a dump. This lives in SSM and never appears in
# one. Encoded rather than stored as text so it is bytes at the point of use.
TOMBSTONE_KEY = os.environ.get("TOMBSTONE_KEY", "insecure-development-tombstone-key").encode()

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The live/staging schema pair the weekly rebuild swaps between.
#
# Read from the environment so two runs on one host cannot corrupt each other.
# The database name is already an environment variable; the schema names were
# not, so a second test run reached into the first one's `live` and `staging`,
# dropped them mid-test, and left failures that read as code defects - a stale
# database whose next run errors with "relation django_content_type does not
# exist" is not obviously a concurrency problem to whoever hits it.
SEGMENT_SCHEMA_LIVE = os.environ.get("ROUTEMAKER_LIVE_SCHEMA", "live")
SEGMENT_SCHEMA_STAGING = os.environ.get("ROUTEMAKER_STAGING_SCHEMA", "staging")
SEGMENT_SCHEMA_RETIRED = f"{SEGMENT_SCHEMA_LIVE}_old"

# The search path has to name both. `live` carries the rebuilt segment tables,
# which are unmanaged and owned by the pipeline; `public` carries everything
# migrations own, including the jurisdiction table the pipeline queries
# unqualified. Without this the unmanaged Segment model is unreadable through
# the ORM in every environment - it resolves to a bare `segment` that exists in
# no schema on the path - and nothing catches it, because the database tests
# reach the same tables through schema-qualified raw SQL.
#
# Set both as a connection option, so a checkout runs correctly without a manual
# grant, and on the role by scripts/devdb.sh and the deploy, so a psql session or
# any tooling that bypasses Django lands on the same path. The comment used to
# claim the role grant happened and nothing performed it.
# public FIRST. PostgreSQL creates an unqualified table in the first *existing*
# schema on the path, and Django migrations are never schema-qualified. With
# `live` first, a deploy onto a box that had already run one rebuild put every
# application table - users, sessions, memberships, overrides, django_migrations -
# inside the schema the weekly swap renames away, and the swap after that dropped
# it with CASCADE. One deploy plus two rebuilds is unrecoverable data loss, and
# it is invisible on a fresh checkout because `live` does not exist yet, so
# migrations land in public and every test passes.
SEARCH_PATH = f"public,{SEGMENT_SCHEMA_LIVE}"

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
        # preview path. Zero under test, because a connection surviving teardown
        # leaves the test database "being accessed by other users" and the next
        # run fails in a way that looks like a code failure.
        "CONN_MAX_AGE": 0
        if "pytest" in sys.modules
        else int(os.environ.get("DJANGO_CONN_MAX_AGE", "60")),
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
