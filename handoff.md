# RouteMaker phase 1 — handoff

**Repository:** `github.com/Macrophage87/RouteMaker` · **Branch:** `claude/beautiful-mayer-4f7gg9`
(206 commits, all pushed) · **Suite:** 2731 tests, green

**Phase 1 is not accepted.** It has been through six rounds of independent review. Round 6 was the
first to return an **ACCEPT** — the cycling / DC-region domain, one area of six — alongside five
REVISE, each carrying a single blocking finding except deployability, the sixth reviewer added this
round, whose walk-through found five. Every round-3, round-4, round-5 and round-6 finding is closed
on this tree, each fix carrying a mutation confirmed to fail, and each panel has verified the
previous round's findings closed by reverting the fix rather than by reading. **A round-7 panel has
not run.** One reviewer of six has accepted one area of six; nobody has accepted the phase, and the
next step is that panel.

Read §3 first if you only read one section.

---

## 1. How to run it

```sh
scripts/devdb.sh                                   # idempotent; Postgres stops when the container idles
PGDATABASE=routemaker_$USER .venv/bin/python -m pytest tests/ -q
```

**Use a private `PGDATABASE`.** The suite creates and drops the `live`, `staging` and `live_old`
schemas, so two concurrent runs against one database drop each other's schemas mid-test and produce
failures that read as code defects. `ROUTEMAKER_LIVE_SCHEMA` / `ROUTEMAKER_STAGING_SCHEMA` now work
as documented — item 18 is closed and the suite is green both with them unset and set to non-default
names — but a private database is the simpler isolation and the one to reach for first.

Three environment variables decide whether a *deployment* works at all; `docs/DEVELOPMENT.md`
("Environment variables") is the long form.

| Variable | Required | What it does |
|---|---|---|
| `KEY_ENCRYPTION_KEY` | **Yes, no default** | Settings refuse to import without it. `TOMBSTONE_KEY` is derived from it by one HMAC over a fixed label, so the encryption key and the tombstone key are two values from one delivered secret. The suite gets its value from `config.test_settings` (`config.settings` plus that one default), which `pyproject.toml` sets as `DJANGO_SETTINGS_MODULE` — it cannot come from `tests/conftest.py`, because pytest-django sets Django up while it loads the initial conftests. |
| `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` | Optional, but a fresh deployment needs it once | There is no password login and no `createsuperuser`, so this is how a new deployment appoints its first instance admin. The id grants standing **only while the instance-admin list is empty**; the first admitted request writes it into the list, audits that as `bootstrap_instance_admin`, and the variable is inert from then on. `api` only. |
| `INSTANCE_ADMIN_REMOVAL_DELAY_SECONDS` | Optional, default 3600 | How long removing *another* instance admin waits before taking effect, during which any instance admin can cancel it. Standing down yourself is immediate; the last instance admin cannot be removed by either path. |

### Deploying it

As of wave 4 the repository carries the things the stack starts against, none of which existed
before: `docker/api.Dockerfile` and `docker/pipeline.Dockerfile`, with `build:` stanzas on `api`,
`worker`, `migrate` and `rebuild`; `src/config/wsgi.py`, the module `WSGI_APPLICATION` has always
named; `STATIC_ROOT = DATA_ROOT / "static"`, without which `collectstatic` refuses to run at all;
and a `Caddyfile` at the path `compose.yaml` bind-mounts. `compose.yaml` now delivers every
variable `config/settings.py` reads, per service, with a test that derives the list of names from
the settings source rather than restating it. `docs/DEPLOYMENT.md` is the long form: build, `TAG`,
the `collectstatic` deploy step and the two flags it needs, TLS at the edge, and the uid-10001
ownership `${DATA_ROOT}` has to have.

**No image has been built and no container has been started in this environment.** There is no
Docker daemon here and the registries are blocked (§2a), so every claim about the images is a claim
about their text, checked by `tests/test_images.py` and `tests/test_deploy_surface.py` and nothing
more. The first `docker compose build` on a host with a daemon is the first real test. Round 6's
deployability reviewer did execute everything that does not need a daemon: it rendered the compose
configuration from `.env.example`, ran `migrate` against an empty PostGIS, booted gunicorn on
`config.wsgi` under the rendered `api` environment, ran `collectstatic` (135 files), and validated
*and ran* the `Caddyfile` under a real Caddy 2.8.4 binary for both `:80` and a hostname. That pass
is where rows 46–50 come from, and wave 5 is why the stack starts now.

**The shipped `.env.example` is a hostname deployment over HTTPS**, not a local stack. One name in
four places — the Caddy site address, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and the
Discord redirect — so the four agree by construction. The local plain-HTTP stack is a commented
block of four lines (`CADDY_SITE_ADDRESS=:80`, `DJANGO_DEBUG=1`, `http://` origins,
`http://localhost/auth/callback`), and it needs `DJANGO_DEBUG` because `SESSION_COOKIE_SECURE` and
`CSRF_COOKIE_SECURE` are `not DEBUG`: over plain HTTP without it a browser throws both cookies
away and sign-in fails with no error anywhere. The two postures must not be mixed — the example
that shipped before this one mixed them and nobody could sign in (row 50) — and `PGHOST` is
commented out on purpose, because compose reads `${PGHOST:-postgis}` and any value in the file
overrides that for all four Django services (row 46).

**`scripts/prepare_data_root.sh` has to run before the first `up`.** A bind mount whose source does
not exist on the host is not an error: the daemon creates it, root-owned, and both images run as
uid 10001, so a first `up` that skips this manufactures `backups`, `static`, `elevation` and the
three `tiles/<variant>/current` directories as root and every write fails with EACCES hours later
(row 48). The script creates every directory compose binds — the list is derived from `compose.yaml`
by a test, so a new mount cannot be forgotten — and chowns the tree to 10001; re-running it is safe,
and the remedy for a host that already ran `up` is in its header.

**The whole first-host sequence is `docs/OPERATIONS.md`, "First rebuild on a fresh host"**, in the
order the code forces rather than a preferred one: prepare the volume → `docker compose build` →
`up -d` → `collectstatic` → bootstrap the first instance admin at `/auth/login` → `manage.py
run_rebuild_now`, which stops terminally at `LOAD_REFERENCE_DATA` having produced the extract →
`install_reference_data.py --extract /data/extracts/source.osm.pbf` → `run_rebuild_now` again →
restart the three Valhalla containers. Elevation is a stage of the rebuild, not a step of its own.
`manage.py run_rebuild_now` is new in wave 5: it defers `weekly_rebuild` once and returns, and a
second call while one is queued or running is refused by the queueing lock with a non-zero exit. It,
`rollback_rebuild` and the reference-data install all run in `rebuild` — never in `api`, which sets
no `DATA_ROOT` and mounts no part of the data volume (row 47).

**`bot` and `renderer` sit behind the `unbuilt` compose profile.** Neither has source in this
repository, so the documented `docker compose up -d` used to stop on two images that exist in no
registry (row 49); the default `up` now skips them and `--profile unbuilt` includes them once there
is something to run.

Variables a deployment gained in wave 4, on top of the three above. `.env.example` carries all of
them with the reasoning.

| Variable | Required | What it does |
|---|---|---|
| `CADDY_SITE_ADDRESS` | Optional, default `:80` | The address Caddy serves on, read by the `Caddyfile` through Caddy's own `{$VAR}` substitution when the config loads, so one file serves a deployment and a local stack. A hostname commits Caddy to obtaining a Let's Encrypt certificate for it, so it must resolve to the host first; `:80` is plain HTTP with no certificate. As of wave 5 `.env.example` ships a hostname and keeps `:80` in a commented local block. `caddy` alone. |
| `DISCORD_CLIENT_ID`, `DISCORD_REDIRECT_URI` | **Yes for sign-in** | Neither is a secret — both appear in every authorize URL the browser follows — and without them the login path builds a URL naming an empty application and sends the browser back to `localhost`. The redirect must match one registered on the Discord application exactly. `compose.yaml` delivered neither until wave 4 (row 28). `api` only. |
| `SOURCE_EXTRACT_URLS`, `SOURCE_EXTRACT_MAX_AGE_DAYS`, `SOURCE_EXTRACT_FORCE_REFRESH`, `COVERAGE_POLYGON` | All optional | The four knobs on the source extract the rebuild now produces for itself (row 31): a comma-separated mirror list for the three Geofabrik files, the age in days past which they are downloaded again (default 6, just under the weekly cadence), a force flag for a rebuild that must start from today's Geofabrik build, and a polygon file to clip to instead of the bounding box in settings. There is no polygon file in the repository. `rebuild` only; `docs/OPERATIONS.md`, "The source extract". |

Native deps: PostgreSQL 16 + PostGIS 3.4, GDAL/PROJ/GEOS, Node 22, **LuaJIT** (not lua5.4 —
Valhalla 3.5.1 requires LuaJIT and its transform calls `bit.bor`). `CI=1` turns missing-interpreter
skips into failures.

---

## 2. What the environment could not do, and the exact fix

Nothing was ever blocked by a *permission prompt*. Two limits were network policy.

### 2a. The Valhalla image cannot be pulled — one host away from working

Docker **works** here: the daemon starts (`dockerd`), and `ghcr.io` (registry API and token
endpoint) is allowed. But the layer blobs live on `pkg-containers.githubusercontent.com`, which the
egress proxy denies:

```
docker pull ghcr.io/valhalla/valhalla:3.5.1
  failed to copy: ... Get "https://pkg-containers.githubusercontent.com/ghcr1/blobs/sha256:...": Forbidden
curl https://pkg-containers.githubusercontent.com/   →  CONNECT tunnel failed, response 403
```

**So the fix is to allow `pkg-containers.githubusercontent.com` in the environment's network
policy** (or pre-bake the image), not to find a different machine. Network policy is chosen when
the environment is created: https://code.claude.com/docs/en/claude-code-on-the-web

GitHub *raw content* is reachable, which is worth knowing before the next round assumes otherwise:
in wave 3 the routing agent fetched three of Valhalla's 3.5.1 source files from GitHub and read the
behaviour out of them directly. So source can be checked against upstream at any time; what cannot
be reached is `ghcr.io`'s blob host and Overpass.

**Why this matters more than it sounds.** Nothing in five rounds has ever run Valhalla. Round 3's
"could not have run at all" cluster (items 6–11) and round 4's `trace_attributes` blocker (item 21)
are the same class of defect: a single real `valhalla_build_tiles` or `valhalla_service` invocation
would have surfaced each in minutes. The guards are written — `assert_lua_script_was_loaded`,
`assert_derived_tags_reached_the_tiles`, `assert_elevation_reached_the_tiles`, and now the
ROUTEMAKER-VIOLATION assertion in `validate()` — and none has executed against a real build.

First three things to run once the image pulls:

```sh
# 1. Does the service start on the generated config?
docker run --rm -v "$PWD/valhalla:/conf:ro" -v "$PWD/lua:/conf/lua:ro" \
  ghcr.io/valhalla/valhalla:3.5.1 valhalla_service /conf/valhalla-standard.json 2
#    A boost::property_tree exception naming a key = the generated config is still short one.

# 2. Build tiles over a small extract with ROUTEMAKER_LUA_DIR set. Check the log for
#    "Using LUA script:" and confirm the path is OUR graph.lua, not the compiled-in one.

# 3. Read a known steep edge back and confirm weighted_grade is nonzero, and that
#    trace_attributes' JSON really does arrive on stdout with the log on stderr (item 21).
```

### 2b. Overpass is blocked — the crossings fixture is unverified

`overpass-api.de` is denied by the same policy. Item 14 could not be closed against real OSM data
here, and round 4's items 25 and 26 are the third and fourth findings on the same file. Every row
still carries `osm_names_verified: false`; the names remain the one thing nobody here can check.

### 2c. Two more hosts the policy denies, and one it allows

Wave 4 found two more, both with the same `CONNECT tunnel failed, response 403` from the proxy:

- **Geofabrik** (`download.geofabrik.de`). The source-extract stage written in wave 4 (row 31)
  downloads the three state extracts from it, so that stage has never fetched a byte here; its
  tests drive it against fakes and a local file tree. Nothing suggests a *deployment* cannot reach
  it — it is an ordinary public download host, and PLAN:13 names it — but that is presumed here,
  not observed. The first real rebuild is the first time anyone finds out.
- **The Debian package index** (`packages.debian.org` and `deb.debian.org`). So the apt package
  names in `docker/api.Dockerfile`, which is Debian bookworm, are knowledge-based. The pipeline
  image is Ubuntu noble and `packages.ubuntu.com` *is* reachable, so those names were checked one
  by one.

**GitHub raw content is reachable**, and has now been used in two waves to read pinned upstream
source directly (§2a). Overpass and `ghcr.io`'s blob host remain the two denials that cost the most.

---

## 3. The fix list

Rows 1–18 are round 3's findings, with how each closed. Rows 19–27 are round 4's, found on the tree
that closed rows 1–18. Rows 28–45 are round 5's, found on the tree that closed rows 19–27: rows
28–41 are the panel's fourteen blockers, and rows 42–45 are the deployability gaps the wave-4
agents found outside the panel and were given in the same wave. Rows 46–53 are round 6's, found on
the tree that closed rows 28–45: five from the new deployability reviewer and one each from routing,
access control and test quality, with the database reviewer's blocker the same finding as the
deployability reviewer's second and carried as one row. **"Mine"** marks a defect I
introduced or blessed. **"Verified"** marks one reproduced by the orchestrator rather than taken on
report.

### Round 3 — security-critical

| # | Finding | | State |
|---|---|---|---|
| 1 | **Open redirect in the login flow.** `auth_views.py:51` takes `?next=` into the session unvalidated; line 112 redirects to it. `GET /auth/login?next=https://evil.example.com/phish` → `302 Location: https://evil.example.com/phish`. A phishing primitive that starts on the real host and passes a genuine (often silent, `prompt=none`) Discord consent, on a deployment whose users are assembly organizers. Fix: `url_has_allowed_host_and_scheme` against `ALLOWED_HOSTS` at both `login_start` and the callback. | Mine · Verified | Closed by validating at both ends. Round 4 threw 13 further payloads over HTTP: all landed on `/`, CRLF neutralised. |
| 2 | **The audit log records the inverse of its purpose.** Django calls `has_*_permission` inside `transaction.atomic()` then raises `PermissionDenied`, rolling the audit row back. Measured: 1 row outside a transaction, **0 inside**. A POST escalating a role mapping to `instance_admin` returns 403 and audits nothing; a read-only admin index GET writes 28 rows. Fix: write refusals outside the atomic block and audit the POST, not every permission probe. | Mine · Verified | Closed. Round 4 measured one REFUSED row per refused POST, with actor, and the 403 unchanged. Reopened for *bulk* delete only — item 20. |
| 3 | **The authorization tables are writable behind a single unasserted override.** `cachedmembership` is *not* in `INSTANCE_ADMIN_ONLY_MODELS`, so `CachedMembershipAdmin`'s own `has_add_permission` is the only gate on the table that "grants any role in any guild" — and mutating it to `True` leaves 431 passed. Same for `ConfiguredGuildAdmin` add/delete. Both `save_model`/`delete_model` audit calls also survive deletion, so PLAN's "admin writes go to the same audit log" is asserted nowhere. | Mine | Closed. Round 4 ran 74 mutations over the auth surface, 68 caught; of the 6 survivors 3 were redundant-but-correct guards, 1 redundant, and 2 real gaps (its S-7 and S-8), both closed in wave 3. |
| 4 | **The stress remap grants bicycle access on `access=no` ways Valhalla would drop.** `classify()` rates them LTS1 (it grades stress, not access), then the remap writes `cycleway=track`, from which upstream derives access. End to end: private farm track / closed service road / gated living street all go `filter=1` → `filter=0, bike_forward=true, bike_backward=true`. The graph asserts a legal claim in the *widening* direction with no override row and no review — bypassing the override table PLAN makes the sole audited path. Fix: one condition, alongside the existing `tags.cycleway` and `is_trail_class` guards. | Verified | Closed by an access allowlist ahead of the write. Round 4 reverted it: 5 mutations caught. |
| 5 | **A deleted, tombstoned account's membership rows are recreated by the next gateway event.** `record_event` consults neither `BanTombstone` nor `is_deleted`, and `sweep_memberships` never removes them (the purge only touches rows with no `last_login`). Contradicts a named plan test, for someone who asked to be forgotten. `test_a_deleted_user_is_not_re_cached` carries that name and asserts a different rule. | | Closed: `record_event` consults both, and the sweep removes them. Round 4 killed all four `is_forgotten` mutations. |

### Round 3 — cannot run at all

| # | Finding | | State |
|---|---|---|---|
| 6 | **The worker cannot execute a single job.** Nothing calls `django.setup()`; `procrastinate.contrib.django` is not in `INSTALLED_APPS`; there is no `procrastinate schema --apply` step anywhere. The worker dies on a missing schema function; past that every task raises `AppRegistryNotReady`. My test calls `app.tasks[...].func()` from inside pytest, where conftest has already run `django.setup()` — it asserts registration, never startability. | Mine · Verified | Closed. Round 4 verified by reversion with a cold-worker test: 3 mutations caught. |
| 7 | **The weekly rebuild raises on every fire.** `build_handlers` returns 11 of 13 stages; `SWAP` and `RECONCILE` have no handler and the task passes no `skip`, so `StageNotImplemented`. It does not even reach that: `validate()` raises first because no samplers are injected. `swap_schemas` has no caller outside tests — the rename is dead code in production. My test monkeypatched `run_rebuild` itself. | Mine · Verified | Closed: full stage set, `perform_swap` as the caller. Round 4 reverted the SWAP stage (16 failed) and substituted a bare `swap_schemas` for `perform_swap` (caught), and fired a rebuild twice against a real database. The promotion path it exposed is item 22. |
| 8 | **The three variant configs are byte-identical and share one tile directory.** `build(variant)` ignores its argument (`scripts/build_valhalla_configs.py:139`); all three md5 `f37b638c…`, all `tile_dir=/data/valhalla`. `valhalla_build_tiles` has no tile-dir CLI option, so the builds overwrite each other and only the last variant survives — destroying all of layer 1. My test compares each file to `build(variant)`, i.e. identical things. Worse: the rebuild service mounts only `/tiles` and `/extracts`, so `/data/valhalla`, `/data/elevation` and `/conf/lua/graph.lua` are covered by **nothing** — tiles land on ephemeral storage and vanish. There is no dated tile directory and no promotion step. | Mine · Verified | Closed: per-variant dated tile directories, mounts, and a promotion step. Round 4 reverted `TILE_ROOT`: 28 failed. |
| 9 | **There is no elevation stage.** `pipeline/elevation.py` is imported only by its own test; `Stage` has no elevation member; nothing fetches 3DEP. Valhalla warns and continues, so no grade is ever baked: `use_hills` inert, Mass Ride's grade cap with no `max_grade`, Recovery and Mountain Goat gain invariants tying. Phase 1 lists "elevation tiles". | | Closed: the stage exists and the config key sits at top-level `additional_data.elevation` (`elevationbuilder.cc:318`). Round 4 reverted both halves, 2+2 caught. The HGT side was still wrong — see the should-fix table. |
| 10 | **A pre-swap stage rewrites the LIVE crossings table.** `BorderCrossing` is a *managed* model in `public`; `INSERT_BORDER_NODES` is stage 7, `SWAP` is stage 12. So `objects.all().delete()` + `bulk_create` hits live data five stages and a multi-hour tile build before promotion, neither staged nor rolled back. A failed rebuild leaves the served graph's node ids resolving against a table describing a graph that never existed — and per item 7 no rebuild can succeed to repair it. I wrote the test that blessed this. | Mine · Verified | Closed: crossings are written into the staged schema and move with the swap (migration 0005). Round 4 reverted the migration's DROP to `SELECT 1` and removed the guard, and wrote crossings to live: caught both ways. |
| 11 | **Nothing writes the membership cache in production.** `record_event` has no caller; there is no bot source, gateway handler or ingest route. `compose.yaml` declares `BOT_INTERNAL_SECRET` and nothing reads it. Phase 1 owes "the bot with gateway-driven membership and role caching"; as shipped nobody ever holds standing. | | Half closed, deliberately. `record_event` has a caller; it still has no *producer*, because the bot is not built. That half is §7's first row, not a fix pending here. |
| 12 | **No guild can ever be marked degraded or revoked.** `should_mark_degraded` and `degraded_window` have no callers; nothing writes `ConfiguredGuild.state`; the admin locks both fields for everyone. The grace period is a correct, well-tested predicate with no transition into the state it guards. | | Closed: the sweep writes the state. Round 4 walked a bot's whole life through it — dies, 4 days, degraded, `grants_standing` false, returns, active. |

### Round 3 — correctness

| # | Finding | | State |
|---|---|---|---|
| 13 | **Shoulder credit inverts the provision hierarchy.** On a 55 mph 8-lane arterial: 8 ft shoulder → **LTS3**, painted bike lane → LTS4, nothing → LTS4. A shoulder is worse provision than a painted lane and rates a tier safer, because `_bike_lane_tier` floors at LTS4 above 40 mph and the mixed-traffic path has no floor. `is_top_tier` is LTS4-only and both Beginner's "zero top-tier distance" invariant and the road-exposure report key on it — so Beginner routes onto Leesburg Pike and River Road and reports nothing. I wrote the shoulder tests using a 45 mph two-lane secondary. | Mine · Verified | Closed for the facility step; round 4 reverted it and 104 tests failed. The *volume gate* was a second, unguarded path to the same inversion — item 23. |
| 14 | **The crossings fixture is on its third round of the same failure.** Mechanism moved from dead way ids to unmatchable names; the data did not. "Key Bridge" ≠ OSM's `Francis Scott Key Bridge`; "14th Street Bridge (Mount Vernon Trail connection)" is a label, not a name; "Woodrow Wilson Bridge path" ≠ `Woodrow Wilson Memorial Bridge`. Only Chain Bridge matches. **And the fixture is not wired in at all** — `ReferenceData.load` reads `<DATA_ROOT>/reference/crossings.json`, which nothing populates. **And** Key and Chain are recorded roadway-*illegal* when both roadways are legal to ride, so Chain Bridge's roadway is marked trail-class on every variant and pollutes Trailmaxxing's road-exposure denominator. Needs §2b. | | Closed as filed: the fixture is wired in, the OR matcher, `is_trail_class` and the `rm:bridge_bicycle` emitter all verified by reversion. Round 4 then found the fixture's *content* wrong in two more ways and unpinned in a third — items 24, 25, 26. Names still unverified (§2b). |
| 15 | **Three of five paths to LTS4 are untested.** `if speed_mph >= 35` → `>= 45` leaves **431 passed** — verified. 35 mph is the LTS3/LTS4 boundary and the most common arterial posting in the region. The e2e test asserts `tiers[100] >= 3`, exactly weak enough to let it through. Also surviving: 30 mph multilane → LTS3, and the high-volume bump. | Verified | Closed. Round 4 ran eleven boundary mutations across the five paths; all eleven caught. |
| 16 | **Session lifetimes disagree with the plan and the absolute cap is unreachable.** PLAN says "30 days idle, 90 days absolute"; `IDLE_SESSION_LIFETIME` is **14 days**. `SESSION_COOKIE_AGE` is unset, so Django's 14-day cookie expires first and neither app clock can bind. Also: nothing anywhere increments `session_epoch`, so ban and deletion do not end sessions. | Verified | Closed. Round 4 confirmed over HTTP: `expire_date` does not move, an epoch bump gives 404 and zero rows, and a 90-day cookie cannot outlive the cap. |

### Round 3 — systemic

| # | Finding | | State |
|---|---|---|---|
| 17 | **The suite asserts rules and does not assert values.** Ten constants the plan writes down can each change by two orders of magnitude with 431 tests green — session lifetimes, `DEGRADED_WINDOW`, `MAX_ROW_AGE`, `GUILD_REMOVAL_GRACE`, `PURGE_NEVER_SIGNED_IN_AFTER`, the swap's timeout/attempts/backoff, `DEFAULT_MIN_CROSSING_M`. The mechanism is always the same: *the test computes its boundary from the constant it is testing*. This already cost item 16, and nobody could have known. A flat table of `assert CONSTANT == <plan figure>` is cheap. | | Closed for those ten: `test_plan_constants` is typed in and round 4 killed all ten mutations. The same shape survived elsewhere — `STALE_AFTER`'s windows and the swap defaults — and those are pinned flat in wave 3. |
| 18 | **My test-isolation fix is broken.** Setting the schema env vars fails 11 tests, because `test_schema_swap.py` (21 literal occurrences) and `test_pipeline_end_to_end.py` write `"live"`/`"staging"` as strings. It was also partly misdirected — a private `PGDATABASE` already isolated concurrent runs. Worse, **production has the same hardcoding**: `run.py:117` `staging_schema: str = "staging"` while `swap_schemas` reads `settings.SEGMENT_SCHEMA_STAGING`, which silently promotes an *empty* segment table; and `writers.py:39`'s `if schema == "live"` guard does not guard a renamed live schema. | Mine | Closed on both sides: the suite and the pipeline read the settings, and `test_pipeline_end_to_end.py` runs a whole rebuild under renamed schemas. Round 4 reverted the staging literal and caught it. The §1 warning is withdrawn. |

### Round 4 — security-critical

| # | Finding | | State |
|---|---|---|---|
| 19 | **The ban tombstone is keyed by a literal in the repository.** `settings.py:153` defaulted `TOMBSTONE_KEY` to `"insecure-development-tombstone-key"`; compose passed `KEY_ENCRYPTION_KEY` (which PLAN:283 names for exactly this) to `api` and `worker` and nothing in `src/` read it, so the published literal *was* the key on every deployment. A Discord id's candidate set is any guild's member list, so anyone holding a dump computes the tombstone of every candidate. It failed open and silent: the empty-key guard in `tombstone()` was defeated by the non-empty default. | Verified | Closed: `TOMBSTONE_KEY = HMAC(KEY_ENCRYPTION_KEY, "routemaker/ban-tombstone/v1")`, the variable is required with no default (`ImproperlyConfigured` at import), it reaches `api`/`worker`/`migrate`/`rebuild` and is pinned never to reach `bot`/`caddy`/`postgis`/`photon`/`valhalla`, and `config.test_settings` supplies the suite's value. `ban_tombstone` stays in the dump on purpose (a restore without it readmits every banned account); the reasoning is in the `BanTombstone` docstring. |
| 20 | **Bulk delete through the admin writes no audit row.** `AuditedAdmin` has no `delete_queryset`, so `delete_selected` bypasses `delete_model`: two role mappings deleted through the changelist, 0 app audit rows, same for `configuredguild`, `jurisdiction` and `override`. PLAN:56 says admin writes go to the same audit log; the log gives a false account of who removed what. | Verified | Closed: `delete_queryset` audits each object, an unpermitted bulk action returns 403 *and* writes a REFUSED row, and the last-admin refusal is audited too (round 4's S-4 and S-5, which were the same hole seen from two other angles). |

### Round 4 — cannot run at all

| # | Finding | | State |
|---|---|---|---|
| 21 | **`trace_attributes` parses `stdout + stderr` as if the log came first.** `valhalla_service` configures logging to stderr and writes the response on stdout, and `graphreader.cc:110` logs on the tile-extract success path, so the concatenation is JSON first and log after: `json.loads(output[start:])` raises "Extra data". `validate()` calls `sample_grade` first, so every fire ends `RebuildFailed` at VALIDATE. The suite was green because the fakes in `tests/test_tiles.py:174` and `rebuild_fixtures.py:268` both put the log **before** the JSON — they modelled the stream order backwards. Same class as item 7, one stage later. | Verified | Closed: `_run_command` returns `CommandOutput(stdout, stderr)`, `trace_attributes` parses stdout alone and bounds the object with `raw_decode`, and the fakes now put the log on stderr after the JSON. |
| 22 | **`pipeline/promotion.py` leaves, and creates, the half-swapped states its docstring says it never leaves.** Four holes, all reproduced against a real database (promotion.py:77-88, :70, :107; tiles.py:161-163). (a) `repoint_upstreams` is not atomic and its result binds only on full success, so a failure on the third variant leaves two rows naming a build nothing describes — and the wrapped error is retryable, so the partial repoint repeats ×5. (b) `tiles.demote` returns None with no `previous`, so on the *first* rebuild a swap failure leaves `current` pointing at an unpromoted build while `restore_upstreams` blanks every row. (c) `restore_upstreams` writes `previous_build_id=""` unconditionally, destroying the only thing `rollback()` reads. (d) `rollback()` has no precondition that a swap ever happened: after the first-ever swap it promotes the empty schema, live 5 → 0 segments. (e) `rollback_swap` lacks the in-transaction refusal `swap_schemas` has. | Verified | Closed: `repoint_upstreams` is atomic; `perform_swap` captures `upstream_states()` and `tiles.links()` *before* the first promote and restores both on any failure, including "there was no link"; `restore_upstreams` restores url/build_id/previous_build_id and deletes a row the repoint created; `demote` is operator-only and clears `previous`; `rollback()` refuses with `RollbackUnavailable` unless every variant names a previous build, has a `previous` link that agrees, and the retired schema exists with segments in it; `rollback_swap` drops a leftover staging schema with a warning and refuses inside a transaction. |

### Round 4 — correctness

| # | Finding | | State |
|---|---|---|---|
| 23 | **The provision-hierarchy inversion survives through the volume modifier.** The gate `if aadt is not None and lanes <= 1 and not has_facility` reads cycleway tags only, so a shoulder takes the bike-lane table's credit *and* the volume credit while a painted lane takes only the first: 30 mph, 1 lane per direction, 8 ft shoulder, AADT 900 → LTS1, better than a painted lane at LTS2; MacArthur Blvd at 35 mph with AADT 12000 inverts the other way into `is_top_tier`. `TestTheProvisionHierarchy` swept speed × lanes × width × parking and never passed `aadt`. | Verified | Closed: `has_facility` is now the single "has a provision" predicate read by both the facility step and the volume gate, and a shoulder counts only where the bike-lane table produced the tier (`shoulder_credited`). The sweep gained `aadt ∈ {None, 900, 12000}` (216 → 648 cases), compares a shoulder against a painted lane on a road that declares parking absent, and asserts the opposite bound as well; the one permitted difference is pinned by name. |
| 24 | **A bridge's sidepath inherits the roadway's `bicycle=no`.** `resolve_bridge_bicycle_legality` has no way-class filter, so a cycleway/path/footway carrying the bridge's name — the ordinary OSM case — resolves illegal, `run.py` emits `rm:bridge_bicycle=no` on every variant and the remap writes `bicycle=no`, deleting the Woodrow Wilson and 14th Street paths from all three graphs. The `is_trail_class` guard the `cycleway=track` write got in round 3 is absent here, and the docstring says "per-way ROADWAY legality". Filed by both the routing and the domain reviewer. | Verified | Closed: the resolver skips `TRAIL_CLASS_HIGHWAY` ways, with an explicit `osm_way_id` still able to bypass. Tested as a unit and by PBF read-back through `build_named_bridge_extract`. |
| 25 | **The 14th Street rows misidentify the structures.** The Arland D. Williams Jr. Memorial Bridge is the 1950 *highway* span (Air Florida 90; I-395), not the Metro bridge — that is the Charles R. Fenwick Bridge, absent from the fixture entirely. The path is a sidewalk on a highway span (George Mason Memorial, medium-high confidence), which the fixture marked `sidepath_only: false`. Five structures, not three. With item 24 this was a live routing defect: the span carrying the path asserted roadway-illegal and the path inherited it. | | Closed: 14 rows → 15. Williams is the 1950 highway span with `sidepath_only: false`; George Mason carries the path with `sidepath_only: true` and its confidence stated; the Fenwick Metro bridge is added with no bicycle access (WMATA). Round 4's authority corrections went in with it — see the should-fix table. |

### Round 4 — systemic

| # | Finding | | State |
|---|---|---|---|
| 26 | **Nothing pins the crossings fixture's content — third round on this file.** `osm_names: ["Ponte Vecchio"]` → 945 passed; Key and Chain flipped back to roadway-illegal, which is the exact round-3 error, → 945 passed; every `osm_names` array deleted → 945 passed. `extract_from_fixture` builds the extract's names *from the fixture under test*, so matching was tautological on the one thing that has failed three rounds running. | Verified | Closed: `tests/test_variants.py` carries an `EXPECTED_CROSSINGS` literal table written independently of the fixture; the reviewer's three mutations go from 0 failures to 4, 2 and 4. |
| 27 | **Three class-set and tier mutations survive the whole suite.** `derived["stress_tier"] = 1` in `inject_tags` → 945 passed, because the e2e test asserts presence only (`tags[100].get("rm:stress_tier")`) and the segment-table tier is asserted on a different path. Dropping `motorway_link` from `ALWAYS_TOP_TIER_HIGHWAY` → 945 passed, admitting an on-ramp to Beginner. Dropping `steps` from `TRAIL_CLASS_HIGHWAY` → 945 passed, scoring a staircase as a road. | | Closed: `rm:stress_tier` is compared per way against `classify()` on all three variant extracts, and the class-set members are pinned individually — the six class-set, width, parking, shoulder and length-threshold survivors each got a test at the level the constant takes effect. |

### Round 4 should-fixes and nits that were built

One line each; the full text is in `docs/review/round-4/`.

| Area | Built in wave 3 |
|---|---|
| Routing | `LIT_BY_OSM_VALUE` mirrors upstream's table (the test re-extracts the Lua table) instead of `== "yes"`; `validate()` asserts no ROUTEMAKER-VIOLATION lines per variant; `valhalla_build_admins` and `valhalla_build_timezones` actually run, once, then copy to the other variants, both before `valhalla_build_tiles`; `SUPPORTED_SIDES = (3601,)` (skadi's only HGT dimension); per-variant `build_logs`; Lua `parse_width_m` handles `3'`, `5'6"`, `3ft`, `1,5`, `2 m` and refuses the rest; `configured_paths` = mounted set + `UNUSED_PATH_KEYS` with reasons; `gdalwarp -r bilinear` pinned. |
| Domain | `install_reference_data.py` takes `--volume/--volume-source/--volume-year/--aadt-property` repeatably and matched, with `SOURCE_TIERS` mapping agency → tier; the shoulder is measured against Furth's no-parking width and the two Furth widths are named constants; `urban_way_ids` requires `MIN_URBAN_FRACTION = 0.10`; Purple Line crosses four times into two counties (PLAN:322 and the reference-routes README corrected); crossing authority columns corrected (Key/Chain police MPD and owner DDOT on the 1791 shoreline, Wilson adds PG County and MPD with owner MDOT SHA, the unplaceable "George Kennan" alias removed) and the fixture README rewritten; `has_shoulder` reads every presence key with a width fallback; `check_crossing_names_unique`; `is_boundary_street` handles "Ave". |
| Security | Instance-admin removal delay with a cancel action and `apply_due_instance_admin_removals()` in the sweep; `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` with an audited first claim; `AuditLogEntry.actor_user_id` plus `actor_label()` ("deleted user *pk*" / "no actor (worker)"); an `InstanceAdminListing` proxy model so guild admins can see who the instance admins are without the user table; admin logout deletes the `core.Session` row; the middleware uses `filter().update()`; `BorderCrossingAdmin` renders an empty page with a message before the first rebuild; a `LOGGING` config. |
| Database / scheduler | `RebuildTimedOut` and `TimeoutExpired` are terminal causes; `BACKUP_TIMEOUT_S` = 30 min over one monotonic deadline for `pg_dump` and `pg_restore --list`, with the half archive deleted; `STALE_AFTER` gains `degraded_guild_sweep` (30 min) and `worker_heartbeat` (10 min), every window pinned flat; an operations page at `<DJANGO_ADMIN_PATH>core/scheduledrun/` and `manage.py check_operations` exiting 1; `worker_heartbeat` every 5 minutes; `src/pipeline/retention.py` — `prune_builds` (keep 2, never the current or previous target), `prune_backups` (keep 7, after a verified dump), `prune_run_rows` and `prune_job_rows` nightly; the abandoned deadline thread's query cancelled and its connection closed; `unique_build_id`/`taken_build_ids` so two fires in one second cannot share a directory; migration 0005's reverse recreates the GiST index; swap defaults pinned and the worker run at `--concurrency=4`; `docs/OPERATIONS.md`. |

Not built, by decision rather than oversight: the measured size table (needs a real build), the
backup's remote half, `rm:reviewer_surface`'s producer, the instance-admin removal notification, and
Mass Ride's crossing report. All five are in §7.

### Round 5 — security-critical

| # | Finding | | State |
|---|---|---|---|
| 28 | **`compose.yaml` delivers none of the settings the sign-in path reads.** `api` got six variables; `settings.py` reads 24, and there is no `env_file`. Missing were `DISCORD_CLIENT_ID`, `DISCORD_REDIRECT_URI`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_ADMIN_PATH`, `PGHOST`, `PGUSER`, `PGDATABASE` and the three `VALHALLA_*_URL`. Under the declared environment `ALLOWED_HOSTS` is `['localhost']` and the client id is the empty string: `DisallowedHost` 400 behind Caddy, and an authorize URL Discord refuses. PLAN:299 puts Discord login in phase 1; §7 did not record it missing, and round 4's B-1 had it inverted. | Verified | Closed: a shared `x-django-env` anchor merged into `api`, `worker`, `migrate` and `rebuild`, with the secrets and the sign-in settings on `api` alone, `DATA_ROOT` on `worker` and `rebuild` (row 32), and `REBUILD_MIN_FREE_BYTES` and the `VALHALLA_*_URL` on `rebuild`. Three tests hold it: every name `settings.py` reads is derived from the settings source and must be declared on `api` unless it is in a commented `NOT_DELIVERED_TO_THE_API` allow-list, every allow-listed name must reach the services named for it, and every `${VAR}` without a default must be in `.env.example`. |

### Round 5 — domain

| # | Finding | | State |
|---|---|---|---|
| 29 | **`cycleway=separate` in `SEPARATED_CYCLEWAY` rates the ROADWAY LTS1.** `separate` means the facility is mapped as its own way, so the sidepath already carries LTS1 as trail class and the provision is counted twice — the second time on the arterial. A 45 mph six-lane primary with `cycleway=separate` came out LTS1 "separated track alongside" where the bare road is LTS4, and it shut the volume gate as well. MacArthur, Rockville Pike and Georgia Ave are the corridors that carry the tag. `tags.py:133` reads the same value the opposite, correct, way for parking. Removing `"separate"` left 1590 passed. | Verified | Closed: `SEPARATED_CYCLEWAY = {track, opposite_track}`, with the argument written at the constant rather than in the orphaned comment block that let the value in. The 45 mph primary is LTS4 again, and both sets are now enumerated member by member so a value cannot be added without a test. |
| 30 | **Shoulder credit where parking is DECLARED present.** `stress.py:414` passed `parking=False` unconditionally, so a residential 25 mph street with `parking:both=parallel` and a 2.4 m shoulder came out LTS1 while the same street with a painted lane of the same width came out LTS2 — the provision hierarchy inverted again, one round after item 23, on the parameter the round-4 sweep held fixed. Beside declared parking the strip is occupied or it is a door zone. In a sweep over AADT ∈ {None, 900, 1500, 8000, 12000} with parking present, the shoulder beat the painted lane in 80 of 640 cases; and the property that was meant to compare them forced `parking:both=no` onto the painted side for every parameter, including `parking="parallel"`. | Verified | Closed: the call passes `parking if parking is True else False`, so beside declared parking the shoulder is measured against Furth's beside-parking width and a 4.5 m strip still earns the table; unknown parking keeps the wave-3 reading, which the reviewer would not overturn. The property forces `parking:both=no` only for the `parking=None` parameter, and the sweep is zero-failure over the five AADT values × widths {1.3, 1.4, 2.4, 4.5}. |

### Round 5 — routing

| # | Finding | | State |
|---|---|---|---|
| 31 | **Nothing produces the source extract; `FETCH_EXTRACT` only checks that one exists.** No Geofabrik fetch, no `osmium merge`, no `osmium extract` anywhere in the repository; `extract.py` only reads a PBF with pyosmium. So the first rebuild on a new deployment stops at stage one with "source extract missing" and no document says how to make the file, and wherever somebody made one by hand every weekly rebuild re-derived the whole map from that frozen snapshot — the drift report reading near-zero and calling it healthy. `tiles.py:164-165` also cited PLAN:13 as endorsing admins from `context.source_pbf`, which is the *clipped* extract. Round-3 domain S8's "no osmium extract" half, which never got a §3 row. | Verified | Closed: `src/pipeline/source.py` downloads the three Geofabrik `-latest.osm.pbf` files with `curl -fsSL --retry 3` to a `.part`, merges them, and clips with `osmium extract -s smart -S types=any --bbox`, taking `--polygon` instead when `COVERAGE_POLYGON` is set. Both results are kept: `merged.osm.pbf` is what `valhalla_build_admins` reads, per PLAN:13, and `source.osm.pbf` is what every other stage reads. A `.part` is never resumed. The disk gate runs before the download, sized from `source.ESTIMATED_BYTES` when nothing is on disk, and `SourceExtractFailed` is retryable because a dropped download is what a retry fixes. `docs/OPERATIONS.md` "The source extract" and a `docs/DEVELOPMENT.md` section carry the operator half. |

### Round 5 — database, scheduler, operations

| # | Finding | | State |
|---|---|---|---|
| 32 | **The `worker` service has no `DATA_ROOT`.** So `settings.DATA_ROOT` falls back to `BASE_DIR / "data"` inside the image and `BACKUP_DIR` with it: the nightly dump lands on the container's writable layer, `prune_backups` prunes a directory nobody writes to, the `${DATA_ROOT}/backups` mount stays empty, and the run row says success. The backup is the one job whose whole purpose is to be trusted. | | Closed on the security branch with the rest of row 28: `DATA_ROOT: /data` on `worker` and on `rebuild`, pinned by the compose test. |
| 33 | **A dump that fails without timing out, or that the verifier rejects, stays on disk under the ordinary name.** Only the `TimeoutExpired` branch unlinked, so a non-zero `pg_dump` exit left the partial archive, and an archive the `pg_restore --list` verification rejected was kept — and, being the newest by name, is what a restore picks. A rejected archive may still carry `cached_membership` rows. | Verified (structurally) | Closed: `perform_backup` writes a `.part` and renames only after verification passes, and every failure path unlinks. Three tests drive it against a real `pg_dump`. |
| 34 | **`prune_tile_builds` runs only after a successful `run_rebuild`, and downstream of the disk gate.** `DiskGateRefused` is terminal, so a refusal is self-perpetuating even with prunable builds sitting there, and a failure after `BUILD_TILES` leaves a third tile set until the second following success. | Verified (structurally) | Closed: retention now brackets the rebuild — `prune_tile_builds(keep=KEEP_BUILDS)` before the disk gate, and in a `finally` after the run `prune_tile_builds(keep=0, protect=[this build])`, so a failed build's directory survives its own run for diagnosis and is reclaimed at the end of the next one. Prune errors are logged, never raised. |

### Round 5 — test quality by mutation

| # | Finding | | State |
|---|---|---|---|
| 35 | **F_LUA3: the Lua remap's tier gate `stress_tier == 1` → `<= 2` survives.** The Lua tests cover tiers 1 and 4 only, so nothing holds the boundary the whole remap turns on. | | Closed: `tests/lua/test_remap.lua` pins the `cycleway=track` gate at tiers 2 and 3 as well. |
| 36 | **F_STR7: `SEPARATED_CYCLEWAY` can drop `opposite_track` with the suite green** — the value appears nowhere in the tests — and neither the separated nor the painted set is enumerated the way `classes.py`'s sets are. | | Closed: both sets are pinned member by member, which is also what removed the inert `"left"`/`"right"` entries from `PAINTED_CYCLEWAY`. Same fix as row 29 seen from the test side. |
| 37 | **F_STR8: `if shoulder_tier < tier` → `<=` survives.** On a tie `shoulder_credited` flips, which makes `has_facility` true, which exempts the road from the volume gate. The 648-case sweep never lands on the tie. | | Closed: the tie at the shoulder's adoption is pinned by name, `<` and not `<=`. |
| 38 | **F_VAR3: the `bridge in (None, "no"): continue` guard in `resolve_sidepath_bridge_ids` is deletable** — Key Bridge Road and its like then resolve sidepath-only. The identical guard in `resolve_bridge_bicycle_legality` *is* caught, which is how the gap is visible at all. Round-5 domain SF-1 is the same function from the other side: it had no trail-class guard either, so two footways named "Francis Scott Key Bridge" satisfied the match and the Key Bridge roadway stayed in the no-trail graph. | | Closed: the trail-class guard is added and the bridge guard is pinned. §7's "harmless today" row is retired with it. |
| 39 | **F_AOP2: `admin_operations.changelist_view`'s `PermissionDenied` is deletable, and a guild admin gets the operations page.** `admin_view` raises 404 on `has_permission`, which a guild admin satisfies as staff, and the override never calls `super()` — so that one statement is the whole gate. | | Closed: the gate is pinned over HTTP, along with the stale-task row, the nightly prune wiring, the newest-successful keep set and the `"doing"` exclusion (round-5 SF-5, SF-6, F_RNS1 and F_RNS4). |
| 40 | **F_TIL2: the disk gate drops its `usage.free < required` clause with the suite green.** The fraction clause alone passes with 2 GB free on a 10 TB volume. | | Closed: the free-space clause is pinned on its own. |
| 41 | **Three of `rollback_target`'s four preconditions are individually deletable.** Both refusal tests are satisfied by the fourth and assert only `"previous" in str(...)`; the deletable ones include the clause that reopens item 22's "live 5 → 0 segments". | | Closed: the four clauses each have a test that isolates them, and `_retired_holds_a_graph` uses `EXISTS` rather than a full `count(*)`. |

### Round 5 — deployability (found by the wave-4 agents, outside the panel)

| # | Finding | | State |
|---|---|---|---|
| 42 | **No image in the repository had a Dockerfile.** `compose.yaml` names four images under `routemaker/` and there was no Dockerfile anywhere and no `build:` stanza, so `docker compose up` on a host with a working daemon stops at the first pull of an image that exists in no registry. | Verified | Closed for the two that have source: `docker/api.Dockerfile` (python:3.11-slim-bookworm, two stages, `gdal-bin`, `postgresql-client-16` pinned to major 16 to match the server, non-root uid 10001) and `docker/pipeline.Dockerfile` (`FROM ghcr.io/valhalla/valhalla:3.5.1`, the tag the serving containers run, read out of `compose.yaml` by the test; `gdal-bin`, `osmium-tool`, `sqlite3`, `curl`, `unzip`, `spatialite-bin`, with a build-time `command -v` loop over every binary the rebuild shells out to). `routemaker/renderer` and `routemaker/bot` have no source, so neither has a Dockerfile; that is recorded in the test and in §7. `tests/test_images.py`, 25 cases, 12 break-it confirmations. Never built — §1. |
| 43 | **`config.wsgi` did not exist.** `settings.py` declares `WSGI_APPLICATION = "config.wsgi.application"` and the api entrypoint names the same path, so the api container exits at start with `ModuleNotFoundError` while every other service comes up — `worker`, `migrate` and `rebuild` run `./manage.py` and never load it. | Verified | Closed: `src/config/wsgi.py`, the standard four lines. The api command is held to the settings value by `tests/test_images.py` rather than written twice, and `tests/test_deploy_surface.py` imports that dotted path and checks what it resolves to is callable. |
| 44 | **There was no `STATIC_ROOT`, so `collectstatic` could not run.** PLAN:64 has the admin and Ninja assets collected into the volume Caddy serves; the command refuses without a `STATIC_ROOT` and it is not overridable from the command line, so the admin rendered unstyled and there was no way to fix it from the deploy side. | Verified | Closed: `STATIC_ROOT = DATA_ROOT / "static"` — the same host directory Caddy mounts at `/srv/static` — with a real `collectstatic` test. It stays a deploy step rather than a build step because `settings.py` refuses to import without `KEY_ENCRYPTION_KEY`, and a secret in a build argument is a secret in the image metadata; `docs/DEPLOYMENT.md` carries the command and the two flags it needs. |
| 45 | **There was no `Caddyfile`, though `compose.yaml` bind-mounts one.** Docker creates a *directory* at a missing bind-mount source, so this was never a startup error: Caddy came up against a directory where its config should be and served nothing. | Verified | Closed: a `Caddyfile` with `{$CADDY_SITE_ADDRESS}` as the site, `handle_path /static/*` to a file server rooted at `/srv/static`, and everything else reverse-proxied to `api:8000` with `X-Forwarded-Proto` — the header `SECURE_PROXY_SSL_HEADER` reads, and the reason Django sees https form posts as secure. Photon, Valhalla and the renderer are deliberately not proxied (PLAN:65) and the suite fails if one appears. Caddy has never run here. |

### Round 5 should-fixes and nits that were built

One line per branch; the full text is in `docs/review/round-5/`.

| Branch | Built in wave 4 |
|---|---|
| Security | `InstanceAdminListing.lookup_allowed` is `discord_user_id` only (a filter on any other column is a 400) and its queryset excludes banned and deleted holders; the `ban_tombstone`-in-dump decision is pinned; due removals are also applied by the 5-minute `degraded_guild_sweep` rather than only by the 6-hourly membership sweep, which was the 1–7 hour effective delay; a `BootstrapClaim` singleton row (migration 0007) written in the same transaction as the flag makes the bootstrap one-shot and race-safe, counting admins the way `check_last_instance_admin` does; `LOGGING` covers `config`; `test_settings` is pinned to relax nothing but the key. |
| Domain | `resolve_sidepath_bridge_ids` gets the trail-class guard; the `bicycle=yes` half of the bridge write gets `M.bridge_may_be_granted` (never past an access or vehicle restriction, never on motorway or motorway_link, and may override an explicit OSM `bicycle=no` on an ordinary roadway per PLAN:68); the Purple Line re-enters at Silver Spring/Takoma, so four District-line crossings but **five** jurisdiction transitions (PLAN:322 and the README corrected, measured from the GPX against the 1791 cornerstones); `distinct_authorities` includes `also_authority`; Python's `parse_width_m` grammar matches the Lua parser's; `measure.revisits` divides the longitude cell by `cos(lat)`; the fixture pins authority columns in `EXPECTED_CROSSINGS`, gives Sousa its OSM name, splits 11th Street into the legal local span and the two I-695 freeway spans, adds Long Bridge under one rule with Fenwick, and corrects American Legion and the Williams / George Mason directions; `--volume-source` has no default and feature ids keep the file stem; `load_sidepath_bridge_ids` deleted as dead code. |
| Routing | `_least_grade_across_variants`' `min` pinned with a per-variant grade fake; `_run_command`'s stream split pinned with a real `sh -c`; `validate()`'s build-log completeness pinned; the admin and timezone databases checked by row count (`admins`, `tz_world`) instead of file size, with the fakes writing real SQLite; the `traffic_extract` reasoning written down — the file must never exist, so never pass `-t`; `docs/OPERATIONS.md` gains "After a rebuild: restart the routers"; two masked schema leaks in `test_pipeline_end_to_end.py` fixed. |
| Database / operations | `perform_swap`'s undo is best-effort, each step wrapped and failures attached with `add_note`; `rollback()` captures links and upstream states before `rollback_swap` and restores and re-swaps on a per-variant failure; failures after a completed swap are terminal, derived from the stage order, and the message says the swap completed and reconcile must be re-run by hand; `run_with_deadline` closes the abandoned connection only when `pgconn.transaction_status` is not ACTIVE and otherwise leaves it to the thread with a WARNING, because `PQfinish` under a thread still inside libpq segfaults the worker; `manage.py rollback_rebuild` (dry by default, `--confirm` performs it) with `docs/OPERATIONS.md` "Rolling back a rebuild"; the "Build ids" and queue-slot text corrected; `check_operations` prints the total; `new_build_id` takes the tiles root from the context. |
| Images and deploy | Covered by rows 42–45. `docker/requirements*.txt` are exact pins read out of the venv, since `pyproject.toml` declares no dependencies; every pinned version was confirmed on PyPI with a manylinux wheel for its interpreter. `docs/DEPLOYMENT.md` is new. |

### Round 6 — deployability (the sixth reviewer, first pass)

Five blockers from the first review that asked whether `docker compose up` produces a running
system. Rows 46–50.

| # | Finding | | State |
|---|---|---|---|
| 46 | **`.env.example:20 PGHOST=127.0.0.1` defeats compose's `${PGHOST:-postgis}`.** A value in the env file overrides the default, so all four Django services were pointed at the container they run in, where nothing listens on 5432. `migrate` cannot connect, and `api`, `worker` and `rebuild` all wait on migrate completing: the stack comes up as Caddy and three routers and nothing else. `tests/test_compose.py` asserted the compose **literal** — never the rendered value, never the example's — so the round-3 defect was reintroduced one file away from the test that was meant to hold it. | Verified (by rendering) | Closed: `PGHOST` is commented out with the whole argument written at the line, and `tests/test_compose_render.py` renders `docker compose config --format json` against a copy of `.env.example` through `--env-file` — ten tests, skipped with a stated reason where the CLI is absent. The example is rewritten around it as a hostname-over-HTTPS posture (row 50). |
| 47 | **The documented rollback runs in the one container that cannot see the tiles.** `docs/OPERATIONS.md` gave `rollback_rebuild` in `api`, which sets no `DATA_ROOT` and mounts no part of the data volume, so `TILES_DIR` resolves to `/app/data/tiles` on the container's own writable layer: the command refuses with "there is no previous build to go back to" on a deployment that has one, which reads like a deployment that has never rebuilt. Filed twice — deployability B-2 and database B1, the latter executed through two real rebuilds — and it is **one finding, carried as one row**. | | Closed: the runbook runs it in `rebuild`, with the reason written down (`worker` sets `DATA_ROOT` but mounts only `backups`, so the tiles are equally absent there), and the same rule stated for every other data command. `docs/DEPLOYMENT.md` gains "The api is not the container to run data commands in". |
| 48 | **`${DATA_ROOT}` subdirectories end up root-owned.** The documented `chown -R` ran *before* the first `up`, and Docker auto-creates a missing bind-mount source itself, as root: `tiles/<variant>/current`, `elevation`, `backups`, `static` and `photon` were therefore manufactured root-owned after the chown, and both images run as uid 10001. The first rebuild's mkdir, the promotion symlink replace, the nightly dump and `collectstatic` all fail with EACCES — six hours in, and not reading as an ownership problem. | | Closed: `scripts/prepare_data_root.sh` creates every directory compose binds, as 10001, before the first `up`; `tests/test_deploy_docs.py` derives that list from `compose.yaml`'s `${DATA_ROOT}` bind mappings and fails if the script stops covering them; the script refuses a `DATA_ROOT` that is unset or not absolute, and documents the after-the-fact remedy. `docs/OPERATIONS.md` step 1 and `docs/DEPLOYMENT.md` both lead with it. |
| 49 | **`bot` and `renderer` were in the default profile** with no source, no `build:` stanza and no image in any registry, so the `docker compose up -d` the documents give cannot resolve two of its images — and no document said so or offered a remedy. | | Closed: both carry `profiles: ["unbuilt"]`, so the default `up` skips them and `--profile unbuilt` includes them once there is something to run. They stay declared, with their limits, so the sizing arithmetic and the no-published-ports rule keep counting them. §7 records them. |
| 50 | **On the shipped `.env.example` nobody could sign in.** Three ways at once: `CADDY_SITE_ADDRESS=:80` with `DJANGO_DEBUG` unset marks every session and CSRF cookie `Secure`, which a browser on plain HTTP discards (executed) — the login round-trip completes and the next request arrives with no session; `DISCORD_REDIRECT_URI` named port 8000, which nothing in the stack publishes, a default `tests/test_compose.py` forbade in compose while the example shipped it; and `DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost` stood in front of an http site, refusing every POST from the site itself. | | Closed: the example is one hostname deployment over HTTPS, the name appearing in exactly four places that agree by construction, with the local plain-HTTP stack as a commented four-line block that sets `DJANGO_DEBUG=1` and says why. The reasoning for each is at the line rather than in a document, and the rendered-configuration tests hold it. |

### Round 6 — routing and tile pipeline

| # | Finding | | State |
|---|---|---|---|
| 51 | **osmium cannot detect an output format from a `.part` name.** libosmium's `detect_format_from_suffix` (io/file.hpp:179-254) inspects only the *last* dot-element, so `merged.osm.pbf.part` and `source.osm.pbf.part` are unknown formats and `check()` throws "Could not detect file format" during argument setup — identical at v1.16.0 and v2.20.0. Neither `osmium merge` nor `osmium extract` passed `-f`, so the first rebuild on any host downloads three Geofabrik files and dies at the merge: row 31's original failure, one message later, on a row recorded Closed. `tests/test_source.py:143,159` pinned the defective argv. | | Closed: both commands carry `OUTPUT_FORMAT_FLAG` (`-f pbf`) — man/output-options.md names the flag, and it is ignored only under `-c`, which the clip does not use — with a regression test that every osmium command writing a `.part` names `-f`, and `docs/OPERATIONS.md` "The source extract", which restated the broken lines verbatim, corrected with them. **No osmium ran here**; this is upstream's source read against our argv. |

### Round 6 — access control, sign-in, privacy

| # | Finding | | State |
|---|---|---|---|
| 52 | **`GET <admin>/logout/` signs the person out cross-site.** The override deleted the `core.Session` row *before* delegating to Django 5's POST-only `LogoutView`, so the 405 arrives after the row is already gone, and `csrf_protect` does not cover GET. Executed: GET → 405, rows 1 → 0, admin index 404 afterwards, the same with a foreign `Referer` and no token. An `<img src>` on any page signs an admin out; the default `DJANGO_ADMIN_PATH` is in the repository; nothing is audited. The POST-only rule was already stated for the site's own logout in `tests/test_auth_views.py:268`. | Verified (by code order) | Closed: `super()` is called first and the row is deleted only when `request.method == "POST"`. Tests cover the GET (405, with the row and the admin index surviving), the cross-origin GET, and the POST that must still end the session. |

### Round 6 — test quality by mutation

| # | Finding | | State |
|---|---|---|---|
| 53 | **FR57: the instance-admin listing's allowed-lookup set is unpinned.** `InstanceAdminListingAdmin.ALLOWED_LOOKUPS` gaining `is_banned` or `session_epoch` survives the whole suite: every case in the refusal test carries a `__suffix` (`session_epoch__gt`, `last_login__isnull`) while `ALLOWED_LOOKUPS` is matched against the whole lookup string, and the positive test asserts only that `discord_user_id` is answered. Demonstrated over the test client as a guild admin — `?session_epoch=7` → rows `{2}`, `?session_epoch=3` → `{}` — a working oracle over every instance admin's revocation counter, on the proxy model built in wave 3 so guild admins could see who the instance admins are. | Verified (the agent's kill re-run) | Closed: the frozenset is pinned member by member and the refusal test gains bare-name cases, so a new member cannot be added without a test. Row 36's lesson, one round later and one model over — see §4. |

### Round 6 should-fixes and nits that were built

One line per branch; the full text is in `docs/review/round-6/`.

| Branch | Built in wave 5 |
|---|---|
| Deployment | `postgis` gains a healthcheck (`pg_isready` on the app's own role and database, with `POSTGRES_DB`/`POSTGRES_USER` taken from `PGDATABASE`/`PGUSER` so it probes what `migrate` connects to) and `migrate` waits on `service_healthy`; `manage.py run_rebuild_now`, so that `docs/OPERATIONS.md` has a command behind the three places it has referred to "a hand-fired rebuild" since wave 3; `docs/OPERATIONS.md` "First rebuild on a fresh host" in the order the code forces, including the reference-data chicken-and-egg — the first `run_rebuild_now` exists to produce the extract the installer needs and is expected to stop terminally at `LOAD_REFERENCE_DATA`; Photon pinned to `2.4.0` (the tag list read off Docker Hub) with its unbuilt index recorded in §7; a host-requirements section (8 vCPU / 32 GB / 200 GB, `REBUILD_MIN_FREE_BYTES`, and the 32 GB `check_compose_limits` hardcodes); every `$DATA_ROOT` snippet loads `.env` first, so no `chown -R ""` can target `/`; the stale `STATIC_ROOT` comment in `api.Dockerfile` removed and the wrong cross-reference in `DEPLOYMENT.md:204` corrected; `/auth/login` named as the entry point, since `/` is a 404. |
| Database / operations | `schema.refuse_unswappable_schema` — `reset_segment_schema`, the first thing `FETCH_EXTRACT` does, refuses a staging name that is the live, retired or `public` schema (executed before the fix: staging set to the live name took the served graph out), and settings raise `ImproperlyConfigured` unless the three schema names are distinct and none is `public`; one `ROUTER_RESTART_NOTICE` shared by the success detail and the post-swap `RebuildAbandoned` message, which now says the swap completed and names the router restart instead of claiming the new build is being served; the backup's `.part` staging name pinned (the final name cannot appear until verification passes, and a stray `.part` is neither pruned nor counted toward `BACKUP_KEEP`); `apply_due_instance_admin_removals` under `select_for_update(skip_locked=True, of=("self",))` in a transaction, tested from a second real connection, now that two tasks can run it concurrently; `retention.py`'s protected set written as a literal minus `None`. |
| Routing | Covered by row 51, plus: `valhalla_build_admins` built **once** per rebuild and copied to the other variants, the shape the timezone database already had — two redundant parses of a ~1.5 GB PBF against a six-hour terminal budget — with the end-to-end test asserting one build and four copies; `spatialite_tool` added to the pipeline image's `command -v` guard (the timezone script calls it; noble's `spatialite-bin` ships it) behind a `PIPELINE_GUARDED_BINARIES` test; the Dockerfile header cites functions rather than `tiles.py` line numbers that drift; the same-snapshot assumption behind `osmium merge` over three separately-built Geofabrik extracts written down in `source.py`; a compose test that the extracts and the tiles share the one `/data` volume the disk gate measures. |
| Domain | The **accepted** area's four should-fixes, built anyway: `resolve_bridge_bicycle_legality` returns `(dict, unmatched)` and `ReferenceData.load` logs the union, so the 14 sidepath-false rows that could never reach the log the README promised now do (`unmatched_crossings` carries both resolvers' misses); `NAME_KEYS = ("name", "bridge:name")` read by both resolvers, `bridge:name` being OSM's conventional home for a structure's name on a road way; `MIN_URBAN_FRACTION = 0.5`, decoupled from `MIN_JURISDICTION_FRACTION` with the asymmetry written at the constant — jurisdiction over-reports safely, urban is a binary switch to the *lower*-stress default — and a real-PBF test at 40% and 60%; the cycleway value-set tests parametrised over `cycleway`, `cycleway:both`, `:left` and `:right`, the last being the dominant DC tagging for a one-way street (SF-D4, the round's one domain survivor); a README scope section for the crossing set; the `revisits` longitude cell padded by 1.01; the conflate rank tuple ended in `way_id, feature_id` so a three-way tie is not input order; the `shoulder=no` + `shoulder:width` reading stated as deliberate in `has_shoulder`. |
| Security | Covered by row 52, plus: a scoping test with a guild admin who is only a **member** elsewhere, which is the shape `_admin_guild_ids` → `_member_guild_ids` needed and the suite never constructed; `tests/test_compose.py` derives settings' environment reads by an **ast walk** over `environ[...]`, `environ.get`, `environ.setdefault` and `getenv`, imported forms included, with a canary over eight shapes — the regex form required a literal `(` and missed `os.environ["X"]`, so row 28's guarantee was false and two undeclared reads passed; `standing.py`'s comment corrected (an instance admin is not a mapped Discord role, and `instance_admin_guild_ids` is assigned by nothing — an open owner decision, §7); `test_deploy_surface` pins `header_up`'s **value**, `{scheme}`, and not only its name. |
| Test quality | Twenty of round 6's thirty survivors pinned, nineteen of them test-only and one a comment in `lua/graph.lua` (FR87: the `nodes_proc` guard reads the *merged* tags and its second half is what passes an upstream `access=no` crossing through, which the old comment had backwards). Flat pins for the figures the suite reached only through themselves — `COVERAGE_BBOX` corner by corner, `SOURCE_EXTRACT_MAX_AGE_DAYS` at six through a fresh import with the variable unset, `SOURCE_EXTRACT_FORCE_REFRESH` on `1` and nothing else, `WEEKLY_REBUILD_CRON`'s discarded day-of-week field, `RUN_ROW_RETENTION_S`, `ABANDON_GRACE_S`, `MIN_RIDABLE.Road`, `DUMP_NAME`'s `$`, and the api image's `PYTHONPATH` derived from its own `WORKDIR`. Boundaries at the value that occurs: `RIDEABLE_SHOULDER_M` at exactly 1.2 m, `least_restrictive`'s `>` , `_least_grade`'s completeness clause, the gate's `>=`, "(and 0 more)". Guards a test would not have missed: a zero-byte `.part` never renamed into place, a stale one removed before curl and not after, a symlinked variant directory not walked through by `rmtree`, the newest finished dump surviving a `.part` in the last kept slot. Four survivors accepted as equivalent on the record (FR18, FR27, FR45, FR99), as were the database reviewer's two and `F_ROLL_C`. |

---

## 4. The pattern worth carrying forward

Every round has found the same thing, and each round finds it in the code written to fix the last:

> **The tests assert the functions and not the pipeline.**

Round 2's domain reviewer named it. Round 3's test-quality reviewer measured it: 95% line coverage,
71% mutation kill rate. Round 4 measured it again at 96% and 85.6% — better, and still the same
shape underneath.

Round 3's instances were mine: I monkeypatched `run_rebuild` in the test meant to prove the rebuild
was wired (item 7), compared a config file against the function that generates it (item 8), called a
permission hook directly with a hand-rolled request object instead of making a request (item 2), and
asserted the replace-wholesale rule without noticing the table was live (item 10).

Round 4 added two more, both from the fix work itself:

- The routing fakes **modelled Valhalla's stream order backwards** — log before JSON, on one
  concatenated string. The parser was written to match the fakes, so a stage that cannot complete
  against the real binary had a green test (item 21). A fake is an assertion about someone else's
  behaviour, and it needs a citation like any other.
- The promotion agent wrote **two mutations that each survived alone**, because each of the two
  fixes masked the other. One test per fix is not one mutation per fix; the two were split apart
  and given a test each before the branch merged.

Round 5 added two more, both out of wave 4 rather than out of the panel:

- The security branch's compose-completeness test — which derives the variable names from
  `settings.py` instead of listing them — **failed at merge on the routing branch's four new
  environment reads**. The six branches were disjoint by file and collided anyway. A test that
  reads the source catches that; a test that carries a list somebody maintains does not.
- The database agent's first design for row 34 put the prune in a `finally` that could not run in
  the cases it existed for, and **two mutations survived it**. It was redesigned rather than given
  more tests. That is round 4's masking lesson one step earlier: a mutation that survives is a
  statement about the code, not only about the test.

Round 6 added one instance, and it is the same shape one round later:

- The test-quality pass found **a set read by name and never enumerated** again —
  `ALLOWED_LOOKUPS`, which admits `session_epoch` with the suite green (row 53) — one round after
  F_STR7 found and fixed exactly that for the cycleway sets (row 36). The fix was applied to the two
  sets it was found on, not to the shape.
- The deployability pass found the compose test **asserting the YAML literal rather than the
  rendered configuration**: `${PGHOST:-postgis}` was pinned in the file while the shipped
  `.env.example` overrode it (row 46). A test that reads the source catches a collision between two
  branches; only a test that renders catches a value.

**The practice that works** is to write the mutation *after* the test and confirm it fails. Do it
before committing, not in review.

---

## 5. Standing conventions

- **A phase is finished when an independent panel accepts it, not when tests pass.** Send a review
  panel after each phase and revise until acceptance. Six rounds so far; one area accepted in round
  6, the phase not.
- **An agent's fix reaches the merged tree only after the orchestrator has re-run at least one of
  its claimed mutations.** Wave 3 merged five branches on that rule, one blocker mutation per
  branch reproduced by hand before the merge.
- **Reviewer findings carry no authority of their own.** One that contradicts an owner decision in
  `PLAN.md` is rejected on the record, not quietly. (Rounds 3 and 4 both declined to contest the
  owner decisions and flagged the places where a decision is *missing* — whether a guild admin may
  read a private route, the `instance_admin` role mapping, audit before/after, and the fixture's
  factual content versus the rule governing how it may be presented.)
- **A panel reviews what it is asked to review, and nothing else.** Five rounds read the code for
  correctness and not one asked whether the stack could start; the four gaps in rows 42–45 were
  found by the agents fixing other findings. **Round 6 therefore gained a sixth reviewer, for
  deployment** — images, compose, the edge, and whether `docker compose up` produces a running
  system. It returned five of the round's nine blocking findings on its first pass. Round 7 keeps
  the six.
- **Record the exact mutation text beside every verdict.** Done on both sides since round 5 — the
  panel's reports and the fix branches — because round 4's catalogue was never committed and two of
  its "equivalent" acceptances could not be re-derived a round later.
- **Assert the rendered configuration, not the file.** A compose assertion over the YAML literal is
  an assertion about a default the environment may override, which is how row 46 shipped past the
  test written to prevent it. `tests/test_compose_render.py` renders `docker compose config` against
  a copy of the shipped example instead, and the literal-YAML assertions that remain are the ones
  about structure rather than about values.
- **`PLAN.md` is the authority on scope.** Owner decisions include: mass rides are too large for
  bike trails; DC mass rides have legal protections subject to nuances and the UI must never present
  jurisdiction, permit or access information as a legal statement; the Mass Ride preset is tuned on
  District geometry and says so; direct device push is shelved.

---

## 6. What is genuinely solid

Recorded so it is not re-litigated. Everything here was verified by a panel by execution, most of
it by reverting the fix and confirming a named test fails; each panel re-verifies the previous
round's findings the same way, and round 6's six reviewers did so with the exact edit recorded
beside every verdict:

- The vendored Valhalla files are byte-identical to upstream 3.5.1 (md5-checked), the Lua wrapper
  runs end to end under LuaJIT, and the design claims about `barrier=border_control`,
  `country_crossing_cost`, `gate_cost`, `tagged_access` and HGT banding all check out against the
  pinned C++ source, cited by file and line.
- `search_path` ordering and the data-loss fix, verified against a live database in both directions;
  the schema names come from settings on both the test and the production side.
- The swap's ACCESS EXCLUSIVE lock and `lock_timeout`, killed by real contention from a second
  backend rather than by source-reading; and, since wave 3, a promotion that restores every upstream
  row and tile link it touched and a `rollback()` that refuses when there is nothing to go back to.
- Cross-guild admin isolation, confirmed by request: a guild admin of club A sees none of club B's
  rows on any index, changelist, change form or filter, and every cross-guild POST returns 403.
- The auth surface under 74 round-4 mutations, 68 caught; the login flow against 13 further
  open-redirect payloads; the session rules (idle, absolute, epoch bump) walked over HTTP.
- A rebuild fired twice against a real database, succeeding both times and reporting drift 5 → 4.
- Conflation's point-to-line distance and span claiming; border-node insertion; the urban/rural
  speed split; boundary-street handling; lanes normalised per direction before the Furth tables;
  reference-route measurements reproducing the README tables exactly, including the Purple Line's
  four county crossings measured from the GPX.
- **The cycling / DC-region domain was accepted in round 6** — the phase's first ACCEPT, and the
  first time any reviewer has signed off on an area. It rests on a fresh campaign of 37 mutations
  (36 killed, the one survivor built anyway) and an independent re-run of the provision-hierarchy
  property over 1,069,200 cases at zero failures, with the ~19,800 cases where a shouldered road
  rates below a bike-laned one explained as Furth's table making a narrow painted lane worse than
  bare mixed traffic at ≤25 mph, and correctly excluded. The Purple Line's four crossings were
  recomputed from the GPX, and the Python and Lua width parsers agree on all 33 cases.
- Mutation kill rate **71% → 85.6% → 86.5% → 79.2%** — round 6 ran 144 mutants and killed 114 —
  with coverage at **97%**. The last figure is lower because the pass was **targeted**, not because
  the suite regressed: round 6's fresh selection was argued constants, tie boundaries and one-clause
  guards (fresh-pass rate 75.5%, 74 of 98), while every one of round 5's seven blockers and six
  should-fixes was re-verified closed as a literal edit and 25 of 26 sampled wave-4 claims were
  re-killed. Wave 3 added 104 confirmed-failing mutations across five branches; wave 4 added its own
  on six; wave 5 added its own on six again and pinned twenty of round 6's thirty survivors. The
  orchestrator re-ran at least one claimed mutation per branch before each merge.

**The caveat has not changed in six rounds. None of this has run against a real Valhalla binary or
a real OSM extract, no osmium has run here, no image has been built and no container has been
started.** Every tile-pipeline claim above is a claim about our code, about upstream's source and
about the text of a Dockerfile — not about a graph that exists. The one part that has moved is the
edge and the Django side of the deployment: round 6's deployability reviewer rendered the compose
configuration, migrated an empty PostGIS, booted gunicorn under the rendered `api` environment, ran
`collectstatic`, and validated and ran the `Caddyfile` under a real Caddy 2.8.4 (§1). See §1 and §2.

---

## 7. Known phase-1 gaps

Recorded rather than left for a round-7 reviewer to discover. None of these is a defect in shipped
code: each is a plan-named behaviour with no implementation, a decision the owner has to make, or a
measurement that cannot be taken here.

| Gap | Where the plan says it | State |
|---|---|---|
| **No bot** (item 11, restated). `record_event` has a caller now but no *producer*: there is no bot source, no gateway handler and no ingest route, so nothing writes the membership cache in production and nobody ever holds standing. Nothing writes the gateway heartbeat either - the `ScheduledRun(task="gateway_heartbeat")` row `core.revocation.last_gateway_event` reads. | PLAN.md:270 ("The bot"), :274 ("Re-validation") | Not built. Phase 1 owes it. |
| Guild **re-invite token's 24-hour expiry** - "wrapped in a single-use token expiring in 24 hours". | PLAN.md:272 | No token, no expiry, no code anywhere. |
| **Unmapped-guild alert, default 30 days** - "A guild left unmapped beyond a configurable period, default 30 days, alerts instance admins and offers bulk reassignment or archival". | PLAN.md:272 | No setting, no alert. |
| **Remap-reversal window of 7 days** - "an instance admin can reverse a remap within 7 days, restoring the prior ids and mapping but never cached standing". | PLAN.md:272 | No remap action, so no reversal window. |
| **Mass Ride's crossing report** - "the router reports that no roadway-legal crossing of that river is available under Mass Ride and names the ones that are, in the style of the road exposure report". The data half exists and is tested: the crossings fixture records `roadway_bicycle_legal` per structure, `resolve_bridge_bicycle_legality` turns it into `rm:bridge_bicycle`, the remap turns that into `bicycle=no`, and the no-trail variant drops the sidepath-only roadways - so the router really will find no roadway-legal Potomac crossing outside Memorial Bridge and the Anacostia spans. What is missing is the *report*: nothing catches that failure and turns it into a named list of the crossings that remain. | PLAN.md:100 (Mass Ride, L1) | Not built, and deliberately not built here. |
| **Reviewer surface penalty** - `rm:reviewer_surface` is read by `lua/graph.lua` and bounded by the remap, but `overrides.py` supports `access`, `stress` and `jurisdiction` only, so no reviewer can record one and no stage emits the tag. | PLAN.md:69 | Consumer built, no producer. Needs an override kind and an emitter in `inject_tags`. |
| **Instance-admin removal notification** - the delay and the cancel window exist as of wave 3; "notifies every remaining instance admin and the removed party" does not, because phase 1 has no notification channel (no Discord DM path, no email). | PLAN.md:212 | Not built. Wire when the bot exists. |
| **Backup upload, SSE-KMS, 30-day remote retention** - dumps are local with a keep-newest-N prune (wave 3). | PLAN.md:285-292 | Not built. Needs the bucket and the key. |
| **Measured size table** - tile, extract and schema sizes per variant, the numbers the disk gate's threshold and the volume sizing rest on. | PLAN.md:290 | Cannot be produced before a real build; the first full-access rebuild is the measurement. |
| **Audit rows: before/after and retention** - `AuditLogEntry` carries no before/after and has no archival; the model docstring argues the narrowing on privacy grounds (a before/after of a membership row is a membership history). PLAN.md:247 says the opposite. | PLAN.md:247 | **Owner decision needed**: amend the plan or widen the model. Not changed in wave 3. |
| **Admin standing against the private tier / `instance_admin` role mapping** - recorded as open owner decisions in PLAN.md; the security reviewer's view is recorded in `docs/review/round-4/security.md`. | PLAN.md (open decisions) | Recorded owner decisions. Pinned as-is by `TestAdminStandingAgainstThePrivateTier`. |
| ~~**`resolve_sidepath_bridge_ids` has no trail-class guard**~~ - the sibling of item 24, recorded here as harmless. It was not: round 5 found two footways named "Francis Scott Key Bridge" satisfying the match while the Key Bridge roadway stayed in the no-trail graph. | - | **Closed in wave 4** (row 38). Kept here as the record of a gap that was accepted on a reading that did not hold. |
| **Bootstrap claim is one-shot and race-safe as of wave 4** (`BootstrapClaim` singleton row written in the same transaction as the flag; a concurrent second claim loses on the unique index). An emptied instance-admin list is recoverable only by the raw-SQL break-glass in `docs/DEVELOPMENT.md`. | PLAN.md:212 | Built. |
| **The crossings fixture's OSM names are unverified** - every row carries `osm_names_verified: false`; Overpass is blocked here (§2b). The content is now pinned by an independent table (item 26), which pins what we *believe*, not what OSM *says*. | PLAN.md:68 | Needs one Overpass query per structure from a machine that can reach it. |
| **`routemaker/cards.py`** has no production caller (phase-4 surface). | - | Recorded; not ranked. |
| **Instance-admin removal: the target can cancel their own removal.** PLAN.md:212's words "any instance admin can cancel it" permit it literally; the effect is that the delay is unenforceable against a peer who is watching. Pinned by name in `test_the_target_can_cancel_their_own_removal_pending_the_owner_decision`. | PLAN.md:212 | **Owner decision needed**: exclude the target, require a second admin, or accept. Behaviour unchanged in wave 4. |
| **Blue/green Valhalla validation and the post-swap restart.** `valhalla_service` does not reload tiles; after a promotion the three routers serve the previous build until their containers restart. The restart is documented in `docs/OPERATIONS.md` and named in the rebuild's run detail; nothing performs it. | PLAN.md:290 | Not built. Phase 2 owes the second-container arrangement; until then the restart is an operator step. |
| **Renderer and bot images.** `compose.yaml` names `routemaker/renderer` and `routemaker/bot`; neither has source in the repository, so neither has a Dockerfile (the api and pipeline images do, as of wave 4, unbuilt in this environment). As of wave 5 both services sit behind the **`unbuilt` compose profile**, so the default `up` skips them instead of failing to resolve two images (row 49); they stay declared, with their limits, so the sizing arithmetic keeps counting them, and `--profile unbuilt` is what includes them once there is something to run. | PLAN.md:63, :270 | Not built; follows the bot and the thumbnail renderer. |
| **Round-4 nits declined, not missed:** N-5 (`cycle_key()` redundant with `login()`, harmless) and N-7 (a bot whose heartbeats never succeed gets a fresh 72-hour window; `mark_degraded_guilds` only touches `active` guilds so the window is not re-opened per tick). | - | Declined on the record. |
| **The fixture's two least-confident claims** are the two 11th Street freeway spans' `osm_names` and the Long Bridge authority columns. Both were written in wave 4 from knowledge, both say so in the file, and both are the rows an Overpass check should start with. | PLAN.md:68 | Needs §2b, ahead of the rest of the fixture. |
| **`config/settings.py` imports `pipeline.source`** for the Geofabrik URL list, so that one list is not restated. The module imports nothing from Django and is stdlib-only, so there is no cycle - but it is the settings module's only project import, and a reviewer's eye on that was asked for by the agent that wrote it. | - | Deliberate; flagged for round 6, which did not contest it. Left standing, and flagged again for round 7. |
| **No management command re-runs a post-swap reconciliation.** A rebuild that fails after a completed swap is terminal as of wave 4 - a retry would re-run the swap, which begins by dropping the schema a rollback needs - and its message says the new build is being served and the drift report must be re-run by hand. There is nothing to run it with. | PLAN.md:290 | Not built. A `reconcile` command is the obvious next step. |
| **The api image's apt package names are knowledge-based.** Debian bookworm names, written without the package index, which is blocked here (§2c). The pipeline image's Ubuntu noble names were checked one by one against `packages.ubuntu.com`. | - | Cannot be checked here; the first `docker compose build` checks them. |
| **Photon geocoder.** `compose.yaml` runs Photon (pinned 2.4.0 as of wave 5) but PLAN.md:60's index population from a country dump is unbuilt, nothing under `src/` calls Photon, and there is no API route to it; the service consumes its limit and answers nobody. | PLAN.md:60, :64 | Not built. Phase 2 owes the geocoder route and the import. |
| **Closure editing.** PLAN.md:299 lists "closure editing" among the phase-1 admin surfaces and, two clauses later, defers "the rest of the admin" to phase 4; a closure is an issue category (PLAN.md:227). No `Closure` model or admin exists. | PLAN.md:56, :227, :299 | **Owner reading taken:** phase 4 with the issue system. Recorded rather than built. |
| **Anacostia rail crossings** are absent from the crossings fixture; the README states the scope rule and names this as a real, unreviewed gap. | — | Fixture content; needs a survey. |
| **`revisits` cell padding** is 1.01 at the route's mean latitude; a route whose bulk sits far south of a revisit at its northern extreme leaves ~0.3% of alignments uncovered. The minimum-cosine cell would be exact. | PLAN.md:100 | Recorded; not reachable on any fixture. |
| **Border-control denial guard is unreachable today.** `denies_bicycle_at_border` returns early unless `barrier=border_control`, while `remap_node` writes only on `cycle_barrier` and narrow `bollard` nodes; a node carries one `barrier` value, so the violation branch in `nodes_proc` cannot fire. Pinned as a unit (PLAN.md:72); becomes live when `remap_node` learns to write to a border-control node. | PLAN.md:72 | Recorded; restructure when a border-node write exists. |

The Mass Ride crossing report is listed with the bot-dependent rows for one reason and not the
others: it is router behaviour, not pipeline behaviour. It lives where a no-route result is turned
into something an organizer can read, alongside the road exposure report it is explicitly written
"in the style of" - which is layer 4, and which does not exist yet either. Building it from the
pipeline side would mean the tile build deciding what a routing failure means, which is the wrong
component holding the decision and a thing that would have to be unpicked when the report is
actually written. The fixture it needs is checked in and asserted; the rest is the router's.

The three durations belong to guild-lifecycle features (re-invite link, guild remap, unmapped-guild
alerting) that all presuppose a live bot: the re-invite link is an OAuth install URL for it, the
remap's precondition is that it is already present in the new guild with its backfill complete, and
"unmapped" is a state only the backfill can leave. So they are not three missing constants that
could be added to `test_plan_constants.py`; they are three windows on features that do not exist.
They are deliberately **not** implemented here.

One consequence is already wired for, and is the reason it is worth writing down.
`core.revocation.mark_degraded_guilds` fails closed when no heartbeat has ever been recorded -
correct for a bot that goes silent, and on this deployment it would mark every guild degraded on the
first tick and lapse the whole deployment's standing 72 hours later. Its scheduler
(`config.procrastinate.degraded_guild_sweep`) therefore holds the mark until one heartbeat row
exists, and arms itself the moment the bot writes one. Anything else built against the heartbeat
needs the same reading.

---

## 8. Review record

The reports are in `docs/review/round-4/`, `docs/review/round-5/` and `docs/review/round-6/`, one
per reviewer, each directory's README carrying the verdict table and the kill-rate numbers. Each
report states which of the previous round's findings its reviewer re-verified closed and how, and
its own findings are numbered as the reports number them — the mapping to §3 is by the parenthetical
labels in the row text (rows 19–27 from round 4, rows 28–41 from round 5's five reports, rows 42–45
from the wave-4 agents' own finds recorded in round 5's README, rows 46–53 from round 6's six
reports).

Wave 3 closed round 4's findings on five disjoint branches; wave 4 closed round 5's on six, merged
into `phase1/wave4-merge`; wave 5 closed round 6's on six again — one per reviewer, the sixth being
the test-quality pinning branch — merged into `phase1/wave5-merge`. What each agent changed is
summarised per finding in §3 and per branch in the should-fix table above; what was deliberately
left unbuilt is in §7.

From round 5 on, the exact mutation text is recorded beside every verdict: round 4's catalogue was
never committed, so two of its "equivalent" acceptances could not be re-derived a round later.
Round 6 kept that on both sides, which is how its two equivalent survivors in the database area and
`F_ROLL_C` are recorded as settled rather than re-opened next round.

**The next step is the round-7 panel**, on this tree, with the same **six reviewers**. Round 6's
new one returned five of the round's nine blocking findings on its first pass — carried here as
rows 46–50, since its B-2 and the database reviewer's B1 are one finding — which is the argument
for keeping it.
