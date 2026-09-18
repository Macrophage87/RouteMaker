"""Django settings.

The security-relevant values here are not defaults to be revisited later: the
threat model in the plan includes routes for unpermitted rides, so the cookie,
host, and proxy settings are asserted in CI rather than trusted to review.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# The one project import these settings make. `pipeline.source` is the module
# that downloads the extract and it owns the list of what is downloaded; a
# second copy of three URLs here would be the copy that goes stale. It imports
# nothing from Django, so there is no cycle.
from pipeline.source import GEOFABRIK_EXTRACTS

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
    # The worker's schema and connector. Its tables arrive through the same
    # `migrate` one-shot as everything else, which is the only step that can
    # both create the schema on a fresh box and upgrade it on an existing one:
    # `procrastinate schema --apply` does the first and fails on the second.
    # Before this was listed, the worker died on a missing schema function and,
    # once the schema was applied by hand, every task raised AppRegistryNotReady
    # because nothing had set Django up.
    "procrastinate.contrib.django",
    "core",
]

# The task module, named rather than autodiscovered: a module called `tasks`
# anywhere in an installed app would otherwise be imported for its side effects.
PROCRASTINATE_IMPORT_PATHS = ["config.procrastinate"]
PROCRASTINATE_AUTODISCOVER_MODULE_NAME = ""

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

# The XYZ tile template the admin's map widget draws under a jurisdiction
# polygon. Optional, and deliberately empty by default.
#
# PLAN.md:15 ends "Do not use the public OpenStreetMap tile servers", and
# PLAN.md:52 names the GeoDjango map widget as one "configured against the
# self-hosted basemap rather than its default, which would otherwise call the
# public OpenStreetMap tile servers this plan rules out". The self-hosted
# basemap does not exist yet - the PMTiles extract and the renderer are unbuilt
# - so there is nothing honest to default this to. A default that named any
# public server would be the finding this setting exists to close, and one that
# named a path this deployment does not serve would be a broken map plus a 404
# per tile. Empty means the widget draws the geometry over a plain background
# and issues no tile request at all, which is enough to edit a polygon; see
# core/widgets.py.
#
# Nothing in the compose stack delivers it, on purpose: a deployment that does
# have tiles, whether its own renderer or an operator-chosen server, sets it in
# its own environment file. Recorded in tests/test_compose.py's allow-list and
# commented out in .env.example.
ADMIN_BASEMAP_TILE_URL = os.environ.get("ADMIN_BASEMAP_TILE_URL", "").strip()

# Everything with state in it lives on the separate data volume, so nothing
# durable sits on the root volume and the code directory holds no data. The
# scheduled tasks resolve their paths from here rather than from their own
# environment lookups, so one variable moves all of them together.
DATA_ROOT = Path(os.environ.get("DATA_ROOT", BASE_DIR / "data"))
REBUILD_WORK_DIR = DATA_ROOT / "rebuild"
REBUILD_SOURCE_PBF = DATA_ROOT / "extracts" / "source.osm.pbf"
REBUILD_REFERENCE_DIR = DATA_ROOT / "reference"
BACKUP_DIR = DATA_ROOT / "backups"
# Tiles: one directory per variant, a dated build directory under each, and a
# `current` symlink that the serving container mounts. Inside the rebuild
# container DATA_ROOT is /data, so these are the paths the generated Valhalla
# configs name, and the same path resolves to the same file in both containers.
TILES_DIR = DATA_ROOT / "tiles"
ELEVATION_DIR = DATA_ROOT / "elevation"
# The checked-in serving configs the rebuild derives its build configs from.
VALHALLA_CONFIG_DIR = BASE_DIR / "valhalla"

# The coverage polygon's bounding box, west, south, east, north: roughly
# Frederick and Leesburg to the north-west, Annapolis to the east and
# Fredericksburg to the south. The elevation stage fetches every one-degree HGT
# tile this box touches, and the extract stage clips to it.
COVERAGE_BBOX = (-78.0, 38.2, -76.3, 39.5)

# The coverage polygon itself, which `osmium extract --polygon` would take in
# preference to the box. PLAN:13's region is a polygon and the box around it
# reaches past Fredericksburg and Frederick, so clipping to the box carries more
# map than the plan asks for - a size question, not a correctness one. There is
# no polygon file in the repository yet, so this is None and the box is what the
# clip is given; drawing that file and pointing this at it is the whole change.
_coverage_polygon = os.environ.get("COVERAGE_POLYGON", "").strip()
COVERAGE_POLYGON = Path(_coverage_polygon) if _coverage_polygon else None

# The source extract, which the rebuild's first stage now produces rather than
# expecting to find. PLAN:13: the three Geofabrik state extracts, merged, then
# clipped with `osmium extract -s smart -S types=any`, with the admin database
# built from the merged file before the clip. `pipeline.source` is the stage and
# carries the reasoning; these are the three knobs a deployment has.
#
# The URLs come from that module rather than being restated here, so there is
# one list of what this project downloads. A deployment behind a mirror sets
# SOURCE_EXTRACT_URLS to a comma-separated list of its own.
SOURCE_EXTRACT_URLS = (
    tuple(
        url.strip() for url in os.environ.get("SOURCE_EXTRACT_URLS", "").split(",") if url.strip()
    )
    or GEOFABRIK_EXTRACTS
)

# Six days, just under the weekly rebuild cadence: at or above seven the
# ordinary weekly run would accept last week's snapshot and the map would age a
# week every week, while below it a retry or a hand-fired rebuild in the same
# week reuses the extract instead of pulling 1-2 GB again. `pipeline.source`
# holds the same figure as its default and this is what the rebuild passes.
SOURCE_EXTRACT_MAX_AGE = timedelta(days=int(os.environ.get("SOURCE_EXTRACT_MAX_AGE_DAYS", "6")))

# The operator's override, for a rebuild that must start from today's Geofabrik
# build whatever is on disk. Deleting either extract file does the same thing;
# this exists so it can be done without a shell on the data volume.
SOURCE_EXTRACT_FORCE_REFRESH = os.environ.get("SOURCE_EXTRACT_FORCE_REFRESH", "") == "1"

# Where the API's routing client finds each variant's Valhalla. The swap
# repoints these rows (core.models.ValhallaUpstream) before it renames the
# schema; the URL per variant is the compose service name unless overridden.
VALHALLA_UPSTREAMS = {
    "standard": os.environ.get("VALHALLA_STANDARD_URL", "http://valhalla-standard:8002"),
    "no-trail": os.environ.get("VALHALLA_NO_TRAIL_URL", "http://valhalla-no-trail:8002"),
    "ebike": os.environ.get("VALHALLA_EBIKE_URL", "http://valhalla-ebike:8002"),
}

# The disk gate. A rebuild refuses to start unless a second full tile set fits
# beside the current one without taking the data volume past the alert
# threshold. Until a first build has been measured there is no current set to
# size the second from, so a floor applies: the three DC-area variants at
# 3.5.1 are expected well under it, and it is the number to revise once the
# measured size table exists.
DISK_GATE_FRACTION = 0.8
REBUILD_MIN_FREE_BYTES = int(os.environ.get("REBUILD_MIN_FREE_BYTES", 20 * 1024**3))

# Build validation reads two known edges back out of the tiles. The steep edge
# proves elevation was baked; the tier-1 street proves the derived tags reached
# the graph, because a residential street with no cycleway tag in OSM only
# reports a separated cycle lane if this project's remap ran. Both are read
# through valhalla_service in one-shot mode against the freshly built tiles.
# NEITHER HAS BEEN CONFIRMED AGAINST A REAL BUILD: no Valhalla binary has run
# in this environment. The first real rebuild will either pass or name the
# sentinel that needs moving; both are overridable here for that reason.
# Steep: the climb of Chain Bridge Road NW out of the Potomac gorge.
# Tier 1: a 20 mph residential block in Petworth with no bicycle facility.
REBUILD_SENTINEL_STEEP_EDGE = ((-77.1050, 38.9318), (-77.1032, 38.9339))
REBUILD_SENTINEL_TIER1_EDGE = ((-77.0247, 38.9455), (-77.0247, 38.9468))

# Discord login, identify scope only. The client secret is used once per login to
# exchange an authorization code and is never written anywhere; no per-user
# Discord token is retained at all.
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")

# Keys a ban tombstone. A Discord id is a structured 64-bit value whose candidate
# set any guild's member list resolves directly, so an unkeyed hash of one gives
# no privacy against whoever holds a dump. This lives in SSM and never appears in
# one.
#
# Derived from KEY_ENCRYPTION_KEY rather than read from a variable of its own,
# for two reasons.
#
# The plan names the key-encryption key as the key this HMAC uses ("computed as
# an HMAC keyed with the key-encryption key"), and it is the secret compose
# already delivers to the api and the worker and to nothing else. A second
# variable for the same purpose was declared by no service, so the value that
# actually keyed every tombstone was the literal in this file - which is public,
# and with it anyone holding a dump recovers the tombstone of every candidate
# Discord id from a guild member list. That is the whole of the privacy this
# construction exists to provide.
#
# And it is *derived* rather than used directly, so that the key that encrypts
# and the key that tombstones are two distinct values from one delivered secret:
# a tombstone is a public-by-design artefact of the dump, and an oracle over it
# should not be an oracle over the encryption key. One HMAC over a constant
# label is HKDF-Expand with a single output block, which is the standard way to
# split one secret into domain-separated subkeys.
#
# Required, with no default. An unset variable fails at import rather than
# silently keying every tombstone in the deployment with a value that is in the
# repository; the test settings supply one explicitly.
TOMBSTONE_KEY_LABEL = b"routemaker/ban-tombstone/v1"
_key_encryption_key = os.environ.get("KEY_ENCRYPTION_KEY", "")
if not _key_encryption_key:
    raise ImproperlyConfigured(
        "KEY_ENCRYPTION_KEY is required: it keys the ban tombstones, and a "
        "default here would be a published key. Set it from SSM in production "
        "and from the environment file locally."
    )
TOMBSTONE_KEY = hmac.new(_key_encryption_key.encode(), TOMBSTONE_KEY_LABEL, hashlib.sha256).digest()
del _key_encryption_key

# The one bootstrap Discord id, and the only way a deployment gets its first
# instance admin. There is no password login and no `createsuperuser` here, so
# on an empty database every signed-in account was refused at the admin with a
# 404 and the only repair was a hand-written UPDATE against production.
#
# It grants standing *only while the instance-admin list is empty*, and the
# first admin request under that standing writes the id into the list and
# audits it. After that the variable is inert even if it still names someone,
# which is what makes `.env` read access worth nothing on a running deployment.
BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID = (
    int(os.environ["BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID"])
    if os.environ.get("BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID", "").strip()
    else None
)

# How long the removal of an instance admin other than yourself waits before it
# takes effect, during which any instance admin can cancel it. The plan's
# figure: "takes effect after a delay, configurable and defaulting to an hour".
# Without it one admin removes every peer down to themselves in a single
# audited but unstoppable action. Self-removal is immediate, as the plan says.
INSTANCE_ADMIN_REMOVAL_DELAY = timedelta(
    seconds=int(os.environ.get("INSTANCE_ADMIN_REMOVAL_DELAY_SECONDS", 60 * 60))
)

# A minimal logging configuration, because Django's default sends application
# logs nowhere a container operator can read: the three application packages log
# at INFO to stdout, which is where compose and the deployment collect them.
#
# `config` is on the list because the scheduled tasks live in
# `config.procrastinate`, and the one line that explains the state of a
# five-minute sweep - "no gateway heartbeat has ever been recorded, so the
# degraded mark is held" - is logged from there at INFO. Under `root` at WARNING
# it reached nothing, so the operator of a deployment whose guilds were not being
# marked had no way to tell the arming state from a broken task.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{asctime} {levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "core": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "pipeline": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Named at the package, so `config.procrastinate` and anything else this
        # package logs from are covered by one entry.
        "config": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

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

# The three names must be three schemas. The rebuild's first stage drops and
# recreates the staging schema, and the swap drops the retired one, so a staging
# name that collides with either of the other two makes the weekly rebuild delete
# the graph it is serving or the one a rollback would put back - before it has
# fetched anything, with no error to read afterwards. `public` is worse again:
# it carries every migrated table, so `DROP SCHEMA public CASCADE` is the users,
# the sessions, the memberships and the audit log. Refused at import, so a
# deployment with the wrong variable set does not start rather than starting and
# destroying something on Tuesday morning.
_SEGMENT_SCHEMAS = {
    "ROUTEMAKER_LIVE_SCHEMA": SEGMENT_SCHEMA_LIVE,
    "ROUTEMAKER_STAGING_SCHEMA": SEGMENT_SCHEMA_STAGING,
    "the retired schema (<live>_old)": SEGMENT_SCHEMA_RETIRED,
}
if len(set(_SEGMENT_SCHEMAS.values())) != len(_SEGMENT_SCHEMAS):
    raise ImproperlyConfigured(
        "the live, staging and retired segment schemas must be three distinct names, "
        f"not {_SEGMENT_SCHEMAS}"
    )
# `public` carries every migrated table, so `DROP SCHEMA public CASCADE` is the
# users, the sessions, the memberships and the audit log. The catalogs are here
# for the same reason one line down: `information_schema` is the view the
# rebuild's own `schema_exists` reads, and `pg_catalog` is the database. The
# same set is refused again in `pipeline.schema.RESERVED_SCHEMAS`, in front of
# the DDL; this layer is the one an operator meets on the next deploy.
_RESERVED_SCHEMAS = {"public", "information_schema", "pg_catalog", "pg_toast"}
_reserved = sorted(set(_SEGMENT_SCHEMAS.values()) & _RESERVED_SCHEMAS)
if _reserved:
    raise ImproperlyConfigured(
        f"no segment schema may be one of {sorted(_RESERVED_SCHEMAS)} - `public` carries "
        f"every migrated table and the rest are PostgreSQL's own - but {_reserved} is: "
        f"{_SEGMENT_SCHEMAS}"
    )

# PostgreSQL truncates identifiers at 63 bytes, silently, and the retired name
# is the live name plus `_old`. At 63 characters `<live>_old` truncates back to
# `<live>`, so the swap's `DROP SCHEMA IF EXISTS <retired> CASCADE` deletes the
# served graph one statement before renaming it - executed against a real
# server. The bound is therefore on the name the suffix is appended to, and it
# is applied to all three so that one number is the rule rather than three.
# `pipeline.schema.validate_schema_name` enforces the same bound in front of the
# DDL; this is the layer that refuses the deployment at import.
_MAX_SEGMENT_SCHEMA_LENGTH = 63 - len("_old")
# The two names an operator sets. The retired one is derived from the live name
# and is allowed to reach the full 63; bounding it here at 59 would refuse a
# 59-character live name for the length of a string this file computed itself.
_too_long = sorted(
    f"{name}={value!r} ({len(value)} characters)"
    for name, value in (
        ("ROUTEMAKER_LIVE_SCHEMA", SEGMENT_SCHEMA_LIVE),
        ("ROUTEMAKER_STAGING_SCHEMA", SEGMENT_SCHEMA_STAGING),
    )
    if len(value) > _MAX_SEGMENT_SCHEMA_LENGTH
)
if _too_long:
    raise ImproperlyConfigured(
        f"a segment schema name may be at most {_MAX_SEGMENT_SCHEMA_LENGTH} characters, "
        "because PostgreSQL truncates identifiers at 63 bytes and the retired schema is the "
        f"live name plus `_old`: {_too_long}"
    )

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
# collectstatic's destination, and the only reason it can run at all: without a
# STATIC_ROOT the command refuses, and it is not overridable from the command
# line. PLAN.md:64 - "Django's admin and Ninja assets are collected into the
# same named volume, which Caddy serves". That volume is `${DATA_ROOT}/static`,
# which compose mounts into the caddy service at /srv/static read-only, so a
# deploy that points this anywhere else leaves the admin unstyled.
STATIC_ROOT = DATA_ROOT / "static"

# Asserted in CI. A share link is a bearer token in a URL, so a cookie that
# travels cross-site or a page that can be framed is a real leak, not a lint.
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Django's own session clock, set so that the application's two clocks are the
# ones that bind.
#
# It was unset, which means 14 days, which is shorter than either figure the plan
# names - "30 days idle, 90 days absolute" - so Django's cookie expired first and
# both application clocks were unreachable. `IDLE_SESSION_LIFETIME` could have
# been any value at all above a fortnight and no session would ever have lived
# long enough to notice; the 90-day absolute cap, which the plan points out
# Django does not implement and which `core.Session` exists to carry, could never
# fire once.
#
# 90 days, matching ABSOLUTE_SESSION_LIFETIME rather than merely exceeding it, so
# the cookie and the row agree on when a session dies of old age instead of one
# of them quietly being the real rule. Asserted against that constant in
# tests/test_settings_security.py rather than restated here as a number.
SESSION_COOKIE_AGE = 90 * 24 * 60 * 60

# And deliberately False, which is the setting that makes the absolute cap
# absolute. Saving on every request re-issues the cookie with a fresh 90 days
# each time, so a session in daily use would never reach its own expiry - a
# rolling cap is not a cap. With this off the cookie expires 90 days after the
# login that set it, which is exactly `created_at + ABSOLUTE_SESSION_LIFETIME`.
#
# Nothing is lost by it: the idle clock is `core.Session.last_seen_at`, which
# SessionEpochMiddleware writes on every request already, so the idle rule is
# enforced per request whatever Django's session store does.
SESSION_SAVE_EVERY_REQUEST = False
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
