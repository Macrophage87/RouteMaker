# RouteMaker phase 1 — handoff

> **Next implementer: start with `handoff-local.md`** — the short handoff for a local machine with
> Docker (written for Windows/WSL2), with the task list. This file is the full record of rounds 3–10.

**Repository:** `github.com/Macrophage87/RouteMaker` · **Branch:** `claude/beautiful-mayer-4f7gg9`
(285 commits, all pushed — 284 plus this round-10 record) · **Suite:** 3293 tests, green

**Phase 1 is not accepted, and the loop is on hold.** It has been through ten rounds of
independent review. Round 10 returned **one ACCEPT** — access control, sign-in and privacy, for the
first time — and five REVISE with one blocker each, **four of them wave 8's own**: a compose pull
policy read as a fallback that is unconditional, the side rule not applied within a side, a
documented rollback refusal made false by a new mount with a half-swapped state reachable behind
it, and a directional override withholding the fixture's bidirectional grant. The fifth is a test
hole. Every round-3 through round-9 finding is closed on this tree; round 10's five are **open**,
recorded in `docs/review/round-10/` and in §3 below, and **no wave 9 has run**: the owner asked for
a hold after round 10 and for a retrospective over the whole review history, which is at
`docs/review/retrospective.md`. Its conclusion in one line: the loop's exit condition cannot be met
by a loop whose brief mandates fresh reach, the last two waves seeded the next round's blockers, and
the one thing that genuinely blocks the phase — the stack has never been built or run — is not
something a review round can close. It proposes an executable acceptance checklist, one scoped
consolidation wave on three hot spots, and a first run on a host with a Docker daemon. **The
checklist exists**: `scripts/acceptance.py` (`docs/ACCEPTANCE.md`), six items A1–A6 answering
PASS/FAIL/SKIP with evidence and a report, standard-library only so it runs on the deploy host;
its dry run is the one part that has run here. Whether it replaces the six-ACCEPT rule is still
the owner's decision.

The blocker count per round has been 10, 14, 9, 5, 6, 8, 5 across rounds 4 to 10; the composition
moved from things that did not exist, to pre-existing defects reached by fresh review, to
regressions from the fix waves. The retrospective classifies all 77.

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

Round 7's reviewer walked the same ground again and further: the rendered compose configuration;
`migrate` from empty; gunicorn on `config.wsgi` under the rendered `api` environment, including the
login redirect, the `Secure` cookie and the 400 on a foreign `Host`; `collectstatic`; **a real Caddy
2.8.4** validate-and-run for both postures again; `scripts/prepare_data_root.sh` against a temporary
tree with both of its refusals; `run_rebuild_now` twice; `check_operations`; a rollback dry run in
the right container; `perform_backup` **end to end**; and bootstrapping the first instance admin and
reaching the operations page **over the test client**. It also confirmed all eight dependency pins
carry cp311 and cp312 wheels, pulled registry manifests for the four external images, and read
upstream's Valhalla 3.5.1 Dockerfile to confirm the runner is `ubuntu:24.04` with no ENTRYPOINT,
CMD or USER. Everything above the daemon line is still unexecuted.

**The shipped `.env.example` is a hostname deployment over HTTPS**, not a local stack. One name in
four places — the Caddy site address, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and the
Discord redirect — so the four agree by construction. The local plain-HTTP stack is a commented
block of **five** lines, four of them standing in place of the four above (`CADDY_SITE_ADDRESS=:80`,
`http://` origins, `http://localhost/auth/callback`) and the fifth being `DJANGO_DEBUG=1` — round 7
found this block described as four lines, which is the line whose omission reproduces row 50. It
needs `DJANGO_DEBUG` because `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` are `not DEBUG`: over
plain HTTP without it a browser throws both cookies away and sign-in fails with no error anywhere. The two postures must not be mixed — the example
that shipped before this one mixed them and nobody could sign in (row 50) — and `PGHOST` is
commented out on purpose, because compose reads `${PGHOST:-postgis}` and any value in the file
overrides that for all four Django services (row 46).

**`scripts/prepare_data_root.sh` has to run before the first `up`.** A bind mount whose source does
not exist on the host is not an error: the daemon creates it, root-owned, and both images run as
uid 10001, so a first `up` that skips this manufactures `backups`, `static`, `elevation` and the
three `tiles/<variant>/current` directories as root and every write fails with EACCES hours later
(row 48). The script creates every directory compose binds — the list is derived from `compose.yaml`
by a test, so a new mount cannot be forgotten — and, as of wave 6, **chowns per directory rather
than the tree**: the seven this project's own images write (`static`, `backups`, `elevation`,
`tiles`, `extracts`, `reference`, `rebuild`), and not `postgres/` (PGDATA, which the postgis image
chowns to its own uid on every start), `caddy/` (the ACME account key and the deployment's TLS
private key) or `photon/` (an image that is not ours, behind a profile). The `chown -R 10001:10001
"$DATA_ROOT"` it used to end with swept all three into the uid every container of ours runs as.
Re-running it is safe, and the remedy for a host that already ran `up` is in its header.

**The `rebuild` service binds five directories, not the whole data volume.** `tiles`, `elevation`,
`extracts`, `reference` and `rebuild`, each at the `/data/<name>` path it had before, so `DATA_ROOT:
/data` and every setting derived from it are unchanged and the five sources stay on one filesystem
for the disk gate to speak for. What it no longer reaches is `caddy/`, `postgres/` and `backups/` —
the TLS private key, PGDATA and a dump of the whole database. That narrowing and the chown above are
one finding seen from two sides (round 7, access control).

**The `postgis` healthcheck probes TCP.** `pg_isready -h 127.0.0.1 …`, which is how `migrate`
connects. The bare form probes the unix socket, and the socket is exactly what the image's
init-phase server listens on while initdb, the PostGIS extension scripts and
`/docker-entrypoint-initdb.d` run — so the gate `migrate` waits on could go green with the port
still closed, and `migrate` could still race the first boot (row 56). It self-healed on a second
`up`, which is why nothing had noticed.

**The whole first-host sequence is `docs/OPERATIONS.md`, "First rebuild on a fresh host"**, in the
order the code forces rather than a preferred one: prepare the volume → `docker compose build` →
`up -d` → `collectstatic` → bootstrap the first instance admin at `/auth/login` → `manage.py
run_rebuild_now`, which stops terminally at `LOAD_REFERENCE_DATA` having produced the extract →
`install_reference_data.py --extract /data/extracts/source.osm.pbf` → `run_rebuild_now` again →
restart the three Valhalla containers. Elevation is a stage of the rebuild, not a step of its own.
`manage.py run_rebuild_now` is new in wave 5: it defers `weekly_rebuild` once and returns. A second
call while one is **queued or running** is refused with a non-zero exit naming the job in flight by
id and status — the command reads the job table for a `todo` *or* `doing` `weekly_rebuild` before it
defers, because Procrastinate's queueing-lock index is partial (`WHERE status = 'todo'`) and had no
opinion at all about a running one (row 55); the lock still settles the race between the read and the
insert, and that refusal is reported too. **The task itself refuses to double-run**: `weekly_rebuild`
will not *start* while another is `doing`, raising before the run row and without retrying. That is
the guarantee; `--concurrency=1` on the `rebuild` service is a slot count that only looked like one.
`run_rebuild_now`, `rollback_rebuild` and the reference-data install all run in `rebuild` — never in
`api`, which sets no `DATA_ROOT` and mounts no part of the data volume (row 47).

**`bot`, `renderer` and — as of wave 6 — `photon` sit behind the `unbuilt` compose profile.**
Neither the bot nor the renderer has source in this repository, so the documented `docker compose up
-d` used to stop on two images that exist in no registry (row 49); the default `up` now skips them
and `--profile unbuilt` includes them once there is something to run. **Photon is there for a
different reason**: the pinned `rtuszik/photon-docker:2.4.0` image's entrypoint downloads the ~61 GB
planet index on first boot when `REGION` is unset, onto the writable layer of the small root volume
`docs/DEPLOYMENT.md` specifies, and exits 75 into a restart loop when it will not fit (row 54). Its
mount now names `/photon/data`, the path 2.4.0's own `src/utils/config.py:36` reads — the
`/photon/photon_data` it had is the 1.x path and was inert — and `INITIAL_DOWNLOAD` is `"False"`, so
turning the profile on is safe once PLAN.md:60's index import exists. `check_compose_limits` still
counts the service deliberately, because a host has to size for it.

**The admin's map widget makes no request off this deployment's origin.** GeoDjango's default widget
loads OpenLayers from `cdn.jsdelivr.net` and draws tiles from the public OpenStreetMap servers, both
of which PLAN.md:15 and :52 rule out, so an unpinned third party's script was executing on the most
privileged page in the deployment with the admin's session (row 57). OpenLayers 7.2.2 is now
**self-hosted** under `src/core/static/core/ol/` — release URL and per-file sha256 in the `SOURCE`
file beside it, and the version re-derived from the installed Django's own widget so an upgrade
fails the pin — and reaches the browser through the same `collectstatic` step and the same
`/srv/static` as the rest of the admin. There is no basemap in phase 1: the widget draws the polygon
over a plain background, with OpenLayers' own draw, modify and delete controls. `ADMIN_BASEMAP_TILE_URL`
takes one XYZ template for a deployment that has tiles it is entitled to use, but **`compose.yaml`
does not pass it to `api` yet** — `tests/test_compose.py` allow-lists it with that reason, and
`.env.example` says at the line that setting it has no effect until that line exists (§7).

**A failed pipeline command now quotes what it said.** `_run_command` ran under `capture_output=True,
check=True` and nothing read `CalledProcessError.stderr`, so every first-rebuild failure reported an
argv and an exit status and nothing else — including the osmium multiple-versions warning that
`docs/OPERATIONS.md` names as the detection mechanism, and the "Could not detect file format"
diagnosis it documents, which could therefore never appear. It now raises `CommandFailed` carrying
the argv and the last `COMMAND_OUTPUT_TAIL_LINES` (20) lines of *each* stream and logs at WARNING,
and `source.py` logs each command's stderr at INFO and the multiple-versions warning at WARNING by
name. Retryability is unchanged — a reported failure is not a terminal one.

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

**Why this matters more than it sounds.** Nothing in seven rounds has ever run Valhalla. Round 3's
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
deployability reviewer's second and carried as one row. Rows 54–58 are round 7's, found on the tree
that closed rows 46–53: one each from deployability, access control and test quality and two from
the database reviewer, the routing and domain reviewers returning no blockers at all. **"Mine"**
marks a defect I introduced or blessed. **"Verified"** marks one reproduced by the orchestrator
rather than taken on report — in round 7 that is row 54 alone, read against the pinned image's own
`config.py`; the other four were reproduced by their reviewers' executed probes, named in each row.

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
| Security | Instance-admin removal delay with a cancel action and `apply_due_instance_admin_removals()` in the sweep; `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` with an audited first claim; `AuditLogEntry.actor_user_id` plus `actor_label()` ("deleted user *pk*" / "no actor (worker or host operator)", the label wave 7 widened); an `InstanceAdminListing` proxy model so guild admins can see who the instance admins are without the user table; admin logout deletes the `core.Session` row; the middleware uses `filter().update()`; `BorderCrossingAdmin` renders an empty page with a message before the first rebuild; a `LOGGING` config. |
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

### Round 7 — deployability

| # | Finding | | State |
|---|---|---|---|
| 54 | **Photon 2.4.0 downloads the planet index onto the root volume on the first `up`.** `compose.yaml:240` mounted `${DATA_ROOT}/photon` at `/photon/photon_data`, which is the **1.x** path: at 2.4.0 `src/utils/config.py` puts `DATA_DIR` at `/photon/data` and defaults `INITIAL_DOWNLOAD` to `True`. So the bind mount was inert and the entrypoint fetched the ~61 GB planet index (`REGION` is unset) onto the writable layer of the small root volume `docs/DEPLOYMENT.md` specifies — ~104 GB free needed, and otherwise `sys.exit(75)`, which under `restart: unless-stopped` is a crash loop from the very first `up` on every fresh host. §7 and `DEPLOYMENT.md` both said the opposite ("answers queries about nothing"). Nothing in phase 1 calls Photon. | Mine · Verified | Closed: `profiles: ["unbuilt"]`, like `bot` and `renderer`; the mount corrected to `/photon/data` and `INITIAL_DOWNLOAD: "False"`, each cited at the line it sits on, so enabling the profile is safe once PLAN.md:60's index import exists. `check_compose_limits` still counts the service deliberately, because a host must size for it. `docs/DEPLOYMENT.md` gains a "Photon" section with the arithmetic and the two lines that make the difference; §7's row is rewritten. |

### Round 7 — database, scheduler, operations

| # | Finding | | State |
|---|---|---|---|
| 55 | **`run_rebuild_now` refuses a queued duplicate but not a running one — and the extra job breaks the running one's retry.** The queueing lock is a partial index, `WHERE status = 'todo'` (`schema.sql:100`), while the docstring, `--help`, `docs/OPERATIONS.md:291-302` and the test all claimed "queued or running". Executed by the reviewer: defer, set the job `doing`, call again → "queued … as job 2". Worse, `procrastinate_retry_job` puts a retried job back to `todo`, straight onto the row the second deferral inserted — executed: `duplicate key … procrastinate_jobs_queueing_lock_idx_v1` — so a transient `RebuildFailed` becomes an error inside the job-finishing path instead of a retry, and is misreported. It also falsified the runbook's "a hand-fired run in flight on a Tuesday means that tick is dropped": the periodic deferrer skips only on `AlreadyEnqueued`, which a *running* job does not raise. What kept two rebuilds apart was `--concurrency=1`, which is a slot count and not a guarantee. | | Closed on both sides. The command reads `core.runs.jobs_in_flight` for a `todo` **or** `doing` `weekly_rebuild` and refuses by id and status, keeps the `AlreadyEnqueued` handler for the race between the read and the insert, and audits a successful defer. `weekly_rebuild` itself (now `pass_context`) raises `RebuildAlreadyRunning` before the run row, not retried, while another is `doing` — **the in-task check is the guarantee**, `--concurrency=1` only today's serialisation. The runbook's sentence is corrected: a running hand-fired job is *doubled* by the tick unless the task refuses. |
| 56 | **The `postgis` healthcheck probes the socket the init-phase server listens on.** `pg_isready -U … -d …` with no `-h` probes the unix socket, and the socket is exactly what the image's entrypoint (`docker-entrypoint.sh:290-306`) starts its temporary server on, with `listen_addresses=''`, while initdb, the PostGIS extension scripts and `/docker-entrypoint-initdb.d` run — TCP is closed the whole time. Executed against a socket-only cluster: the probe returns rc=0 while TCP refuses; with `-h 127.0.0.1` it returns rc=2. So `migrate`, which waits on `service_healthy`, could still race the first boot. `-d` buys nothing either (`PQPING_OK` without touching the database). It self-heals on a second `up`, which is why nothing had noticed; it was in no document and not in §7. | | Closed: `pg_isready -h 127.0.0.1 -U ${PGUSER:-routemaker} -d ${PGDATABASE:-routemaker}` — TCP, the way `migrate` connects — with the reasoning at the line, a `start_period` covering first-boot work on an empty volume, and the first-`up` self-heal written into `docs/DEPLOYMENT.md` rather than left as folklore. |

### Round 7 — access control, sign-in, privacy

| # | Finding | | State |
|---|---|---|---|
| 57 | **`JurisdictionAdmin` used GeoDjango's default `OSMWidget`.** Executed over the test client: the add and change pages reference `cdn.jsdelivr.net` (OpenLayers 7.2.2, no SRI, no CSP) and emit `ol.source.OSM()`, i.e. `tile.openstreetmap.org`. PLAN.md:15 rules out the public OpenStreetMap tile servers in as many words; PLAN.md:52 says the widget is "configured against the self-hosted basemap rather than its default"; PLAN.md:299 puts the map widget in phase 1. It appeared in no document, in no test and in §7 nowhere — dropping `GISModelAdmin` entirely left 2731 passed. The independent weight is the script, not the tiles: an unpinned third party's code executing on the most privileged page in the deployment, in an instance admin's authenticated session. | | Closed: OpenLayers 7.2.2 vendored under `src/core/static/core/ol/` from the GitHub release zip, with the URL, a sha256 per file and the BSD-2 licence in `SOURCE`, and the version re-derived from the installed Django's own widget so an upgrade fails the pin. `SelfHostedOpenLayersWidget` (`Media.extend = False`, its own template) sits on `JurisdictionAdmin` **and** `BorderCrossingAdmin` — on the latter inert, since a form with every write refused binds no field and emits no media (round 8 N8-1; kept, recorded in §7) — and adds a tile layer only when `ADMIN_BASEMAP_TILE_URL` is set, XYZ only, never `ol.source.OSM`; with it unset, draw and modify work over a plain background. The test asserts that every `src`, `href` and `url` in the rendered add and change pages names no host but the request's own. |

### Round 7 — test quality by mutation

| # | Finding | | State |
|---|---|---|---|
| 58 | **The conflation ranking's overlap term can be a constant with the suite green.** `conflation.rank`'s `-overlap` → `0.0` survives the whole suite. Executed: an arterial on the survey line for 98% of its length at 12.2 m against a frontage road at 71% and 2.8 m — unmutated the 42,000 AADT goes to the arterial, mutated it goes to the frontage road, and the count feeds `classify()` → `rm:stress` → the router's cost. N79 (`mean_distance` → `0.0`) and N44 (`-overlap` → `overlap`, which hands the count to the *worse* candidate) survived with it. Every ranking test constructed equal precedence and equal overlap and asserted only the tie-break wave 5 added — which is itself pinned. Precedence was held (N80 killed). | | Closed: each rank term is pinned independently — overlap strictly, mean distance, `feature_id` — plus the reviewer's arterial-versus-frontage pair driven through `conflate()` rather than through `rank` alone. This is the round's pattern rather than one test; see §4. |
| 59 | **An approved `access` override never reached any variant extract.** `apply_access` rewrote `Way.tags` in memory; `inject_tags` computed `changes` by diffing `variants.inject`'s output against those same tags — a copy of themselves on STANDARD and NO_TRAIL — so the correction cancelled against itself, and `write_extract` rebuilt every way from the source PBF. Executed by the reviewer through the real handler set: `Override("access", 100, {"bicycle": "no"})` held in memory and the written PBF had no `bicycle` key, on all three variants, both directions. PLAN.md:28 names the correction; :18 rests an argument on the table being the sole audited path; round 4's #4 referred widening to it; `overrides.py`'s docstring asserted the opposite. Only the in-memory dict was tested. | Verified | Closed: `extract.Way` snapshots `source_tags` at read and `inject_tags` diffs against them, with an end-to-end test through APPLY_OVERRIDES → INJECT_TAGS → `write_extract` reading the PBFs back; underscore keys are filtered at the same comprehension, so `_jurisdictions` can never reach a PBF (pinned). The jurisdiction stage stays, its docstrings now say it has no consumer, and §7 records that gap. |
| 60 | **A deployment whose maintenance worker never dequeued a job was "ok" for ever.** `first_run_at()` was the oldest `ScheduledRun` of any task, so with no rows nothing was ever stale, `wedged_jobs` reads `doing` only and the failed count was zero. Executed: four jobs `todo`, zero run rows, `check_operations` → `ok`, rc 0 — the one outage PLAN's heartbeat alert exists for, unreported. | Verified | Closed: `core.runs.deployment_epoch()` is the earlier of the oldest run row and `MAX(django_migrations.applied)`, which exists from the first `migrate`; a task never succeeded is measured from it. Pinned both ways (rc 1 once the heartbeat window has passed, rc 0 before), and the migration epoch also removes the drift `prune_run_rows` caused (round 8 N8-1). The cost — a task newly added to `STALE_AFTER` on an old deployment alerts on its first tick until it succeeds once — is a §7 row. |
| 61 | **`rollback_rebuild` had no pre-flight against a running rebuild, and `rollback_swap` drops the staging schema that rebuild is writing.** Executed with a `doing` rebuild and ten staging rows: rows gone, job still running, the rebuild failing hours later as a retried `RebuildFailed`. Between `perform_swap`'s repoint and its `swap_schemas`, a rollback would leave tile links and the served schema naming different builds with neither procedure raising. | Verified | Closed: the command reads `jobs_in_flight("weekly_rebuild")` over `todo`/`doing` before `rollback_target`, dry run included, and refuses by id, status and queue; `docs/OPERATIONS.md` says to finish or clear the rebuild first and how to tell. The dry run now prints the restart hint too. |
| 62 | **A rebuild worker killed mid-run wedged every future rebuild, and the repository held no way out.** No `stop_grace_period` on `rebuild`, so any `down`, `up -d`, `restart`, reboot or OOM during a six-hour build SIGKILLed the worker; Procrastinate 3.9.0 prunes stalled *worker* rows only and `get_stalled_jobs` has no caller, so the row stayed `doing`; `run_rebuild_now` and the Tuesday task then refused for ever (both executed), the latter landing a `failed` job that paged for thirty days; every surface stopped at the diagnosis. | Verified | Closed on two branches: `manage.py unwedge_job <id>` — refuses unless `doing`, refuses while the worker's heartbeat is within Procrastinate's own 30 s stalled threshold, refuses behind a queued holder of the same lock, otherwise `retry_job_by_id` plus a null-actor audit row — named by `wedged_jobs()`' rows on both surfaces and in both guides; `stop_grace_period: 60s` on `rebuild`; and `RebuildAlreadyRunning` now subclasses `JobAborted`, so a refused duplicate lands `aborted` and pages nobody. Reading `worker.py` established that Procrastinate's graceful stop waits unboundedly on a running synchronous job, so a stop *mid-build* still ends at SIGKILL and `unwedge_job` is the repair — a §7 row, with the guides warning against `up -d` during a rebuild. |
| 63 | **The guild admin's audited role-mapping action is absent and was recorded nowhere.** PLAN.md:208, :210, :226 and :272 give a guild admin their own guild's mapping "through the dedicated audited mapping action"; executed as one: POST to their own guild's mapping → 403 and a refused audit row. The read-only form is what :272 asks for; the action beside it is unbuilt, and §7 recorded the three sibling features of the same paragraph but not this one. `RoleMappingAdmin`'s docstring called an own-guild edit "the definition of privilege escalation", which it is not: `attach_standing` ignores `INSTANCE_ADMIN` rows and the scoping blocks other guilds. | Verified | Closed as recorded, not built: a §7 row beside its siblings with the same reason (every clause presupposes a live bot) and what a guild admin does today, and the docstring now gives PLAN:272's actual reason. The 403 and its audit row are unchanged. |
| 64 | **F66: the shipped no-basemap `base_layer` could be nulled with the suite green.** Django's `OLMapWidget.js` builds `new ol.source.OSM()` on a falsy layer, the vendored bundle carries `tile.openstreetmap.org`, and the widget test asserted only absences (`ol.source.XYZ`, `ol.layer.Tile`), both of which a falsy layer satisfies because the OSM source is constructed in the browser. Round 7's pattern verbatim: wave 6 pinned everything it added and not the branch it added it to. Filed by the test-quality and the access-control reviewers independently. | Verified | Closed: the test asserts `var base_layer = new ol.layer.Vector` and `new ol.source.Vector()` present; `js_string_literal` — previously unpinned in full — is pinned on shape, each escape, a `</script>` payload and the `ensure_ascii` property. |
| 65 | **The crossings fixture outranked the audited override table on all eighteen crossing rows.** New since wave 7: once an approved `access` override reached the extract it collided there with the fixture's `rm:bridge_bicycle`, and `remap_way` wrote the fixture's answer over the override's (`bridge_may_be_granted` reads `access`/`vehicle` only, by design). Executed by the reviewer through the real handlers and under luajit: Memorial Bridge, fixture-legal, with an approved `bicycle=no` → the served graph grants. The mirror on the ten illegal rows; an `access=no` override survived, which hid the shape; the report counted the row as applied. PLAN.md:18 and :28 put the table above a checked-in file. | Verified | Closed: `apply_access` returns the ways an approved row wrote a bicycle key onto, the handler keeps those the fixture has an opinion about, `inject_tags` withholds `rm:bridge_bicycle` on them on every variant, and the `OverrideReport` counts them as `fixture_rows_superseded` with an INFO line per way. Tested end to end both ways with the PBFs read back; an `access=no`-only row still gets the fixture's tag. The e-bike protection moved with it into `inject_tags` on the EBIKE variant alone, and the Lua clause that had declined a fixture-legal grant on every variant is gone. |
| 66 | **The operations page's free-space block reassured about a filesystem it could not see.** Served from `api`, which mounted no data volume, so `TILES_DIR` fell inside the image, the nearest-existing-ancestor walk landed on `/`, and the page rendered "The tiles volume has room for the next rebuild." Two mutations survived: measuring `/` outright, and the sentence itself. §7's row read as settled and offered `worker` as an honest home, which binds backups only. | Verified | Closed on two branches: `disk_headroom()` answers ok / short / **unmeasured** with the path it read, `unmeasured` (the directory absent) is an alert line and exit 1 on `check_operations` and a plain statement on the page, never a reassurance; and `api` and `worker` bind `${DATA_ROOT}/tiles` read-only, with the cron entry back in `worker` — which also takes the monitor's ~95 MiB spawn out of the rebuild's cgroup (round 9 S9-4/SF9-11). Both survivors now fail. |
| 67 | **Provisioning the second side of a road rated it worse than provisioning one.** `cycleway_values` was a set union over the four side keys (presence: any side) while the width functions took the minimum (width: worst side), and `has_shoulder` was "at least one side". Executed: `secondary, 25 mph, lanes=2, parking:both=no` with a 2.0 m lane on the left and `cycleway:right=no` → LTS1; lanes on both sides at 2.0 and 1.2 m → LTS2; bare → LTS2. The shoulder mirror at 30 mph did the same, and a one-sided track on a 35 mph four-lane two-way secondary → LTS1. `cycleway:right=no` was discarded; every side-key test was a one-way case. | Verified | Closed by one rule for both provisions: score the worst side a rider may be made to use. On a two-way street each side is a direction, a side with no facility (absent or `no`) is no facility, the road's provision is the weaker side's and the width the narrower; on a one-way street only the used side exists and the union stands, which keeps the District's contraflow tagging. The three cases now read LTS2, LTS2, LTS2; the two-way one-sided track LTS4 and LTS1 when one-way. Nine mutations over the rule each fail a named test; the round-7/8 pins (widths, the shoulder floor, the parking sets) did not move. |
| 68 | **A count's agency and year were dropped before anything durable, so the derivative could not name a conditionally licensed source's influence.** `aadt_by_way` stored the precedence *tier* (`state`/`locality`), not the agency — MDOT SHA and VDOT indistinguishable — and dropped `Match.year`; the segment table had no aadt, year or agency column; `write_segments`' and `StressResult`'s docstrings claimed the opposite. PLAN.md:16, :17, :31-34 and :40; both guides told an operator to install Maryland as a third pair. Not in §7. | Verified (by reading; an absence) | Closed in code: the agency travels through `AgencyFeature`, `Match` and `classify` into `volume_source` (now the publisher, the tier kept for ranking), with `volume_aadt` and `volume_year` added to the DDL and the writer, and the stress override carries all three across. Both docstrings true; both guides say Maryland is not installed in phase 1 and why; a §7 row for what remains — identifiable, not yet excludable. |
| 69 | **Every refused admin write could be made to record nothing by padding the URL.** `record()` passed `object_id` unbounded into a 64-character column while truncating `detail`, a `TextField`. Executed as a guild admin: a change or delete URL padded to 120 characters → `DataError`, 500, **no** refused row, on the three tables PLAN.md:326 names; `delete_selected` with 25 rows ticked → 500, no row; wave 7's `revoke_now` refusal with 20 extra ids → 500, no row. The one-line bound left the suite green, which is why it survived eight rounds. | Verified | Closed: `object_id` bounded at the writer to a constant asserted equal to the column, and both bulk paths write the first id with the count and the whole list in `detail` rather than a truncated join. Measured on seven models: every probe 403 (or 302) plus exactly one refused row. |
| 70 | **A duplicate `action` parameter walked past the admin's action guard.** `_refuse_unpermitted_action` read the *last* posted value while Django's `response_action` reads the indexed one: `action=["delete_selected", ""]`, `index=0` → 200 "No action selected" and no audit row, on every guild-readable model. Nothing was deleted; the state the guard's own docstring says it was written to end was back. | Verified | Closed: `_posted_action` mirrors Django's resolution exactly, including its fallback to the last value on `IndexError` — a naive "first or none" would have reopened the hole via `index=9`, and that choice has its own test. Fifteen tests fail on the old read. |
| 71 | **The documented way to fill in and use `.env` could leave four services unable to start, and the guide blamed a rotated password.** Two defects composing: `.env.example`'s `$` guidance was wrong in its example and false about quoting (the reviewer's stronger claim, that `$$` reaches the container verbatim, was a misreading of `docker compose config`'s re-escaped output — wave 8 measured through the process environment: `$$` correct, `pa$w0rd` → `pa`, quotes stripped); and `docs/DEPLOYMENT.md` ran `set -a; . ./.env; set +a` and then `docker compose` in the same shell, so every value reached compose through the shell, where `$$` is the PID — measured: `pa$$w0rd` → `pa19137w0rd`. Two runs of the procedure, two passwords; `pg_isready` green, `migrate` fails auth, `api`/`worker`/`rebuild` never start. | Verified | Closed: `.env.example` rewritten from a fourteen-row measurement (single quotes as the rule that needs no bookkeeping; the generator first), pinned by a render test; `prepare_data_root.sh --env-file` reads the one line without evaluating the file; `collectstatic` is a bare `docker compose run`; a doc test refuses any line in `docs/` that sources `.env`; the outage section names both causes. |
| 72 | **The api entrypoint's cgroup cpu-quota read was pinned by its own comment.** The wave-7 test asserted that `/sys/fs/cgroup/cpu.max` appears before `$(nproc)` in the raw file text, and the comment block describing the mechanism satisfies it after the mechanism is deleted: the whole `if cores=$(cgroup_cpus) … else cores=$(nproc)` block → `cores=$(nproc)` left the suite green, and so did deleting the function. The two tests that execute the script took the `nproc` fallback in both the mutant and the original, because the box has no `cpu.max`. Reverted, a hand-run container falls back to 17 workers in a 2 GB cgroup — row SF-5's outage, and the first wave-7 claimed kill that did not reproduce. | Verified | Closed on the wave-8 test-quality branch: the entrypoint's cgroup file is overridable, and a test executes the branch under `sh` with a stub `cpu.max` in the shapes that pin the ceiling division and the floor of one as well as the `max` fallback. See the wave-8 table. |

### Open after round 10 (no wave has run)

| Area | Finding | State |
|---|---|---|
| Deployability | `pull_policy: build` is unconditional in Compose v5.1.1, so `TAG=<previous> && up -d` builds the current tree under the old tag and orphans the real previous image; the compose header, the deployment guide and the §7 images row all state the fallback reading. | **Open.** `pull_policy: never` on the four built services, plus the three passages. |
| Domain | The worst-side rule is not applied within a side: `_side_values` unions the general keys with the side key and takes the best, so `cycleway=track` + `cycleway:right=no` on a 35 mph arterial is LTS1; the shoulder's width fallback reads `shoulder:width` for a side tagged `no`. `is_oneway` accepts any `oneway` value (test quality). | **Open.** Specific-wins within a side, per-side widths, `oneway=no` read as two-way; a grid test. |
| Database | `rollback_rebuild` in `api` (now mounting the tiles read-only) swaps the schemas before the tile demotion, fails on the mount, and can lose the re-swap lock to the api's own readers; end state reproduced: last week's rows served under this week's tiles, no rollback target, the served rows in `staging` for the next rebuild to drop. Both guides and a doc test still say `api` mounts nothing. | **Open.** Demote tiles before the schema swap or write-probe `TILES_DIR` in the pre-flight; correct both guides and the test. |
| Routing | A directional-only approved override (`bicycle:forward=no`) on a fixture bridge withholds the fixture's bidirectional grant wholesale, so the bridge is served barred both ways. | **Open.** Scope the withholding to the keys the row wrote. |
| Test quality | `sample_cycle_lane`'s "one and the same way" guard is deletable with the suite green; the covering test's edges also disagree about the lane. | **Open.** One assertion with edges that agree. |
| Access control (should-fix) | A pending instance-admin removal survives the target's stand-down and later strips a re-appointment. | **Open.** Clear the pending row on re-appointment. |

### Round 7 should-fixes and nits that were built

One line per branch; the full text is in `docs/review/round-7/`. Every branch's fixes carry a
confirmed-failing mutation, and the orchestrator re-ran one per branch before merging.

| Branch | Built in wave 6 |
|---|---|
| Deployment (15/15 caught) | Row 54, the row-56 healthcheck and the access-control mount narrowing all landed here. `DEVELOPMENT.md`'s osmium lines carry `-f pbf`, held by a doc test over every osmium line in `docs/`; the local block is "five lines", counted by a test; the bootstrap id is set before the first `up` and `up -d api` otherwise; a `TAG` rollback is `up -d`, not `restart`, which re-reads neither `.env` nor the tag; reference inputs are given as `/data/reference/inputs/…` rather than bare relative names that resolve under `/app`; the urban-fraction sentence is the constant, by doc test. `stale_tasks`: a never-run task is stale only once its window has elapsed since the deployment's **first** `ScheduledRun` row, and on a database with no rows nothing is stale — `check_operations` used to page with all five tasks in a fresh deployment's first minute. First-host step 6 installs DDOT *and* VDOT; `DJANGO_ADMIN_PATH` is offered in `.env.example` (commented, the default is public); `down -v` destroys nothing durable, and it says so; secret-generation guidance, with the `$`-interpolation hazard named. |
| Routing (8/8) | `_run_command` raises `CommandFailed` (argv, exit code, the last 20 lines of each stream) and logs at WARNING; `source.py` logs each command's stderr at INFO and the osmium multiple-versions warning at WARNING by name; retryability preserved. The shared-volume test reads the **rendered** configuration. `assert_lua_script_was_loaded` reads `mjolnir.graph_lua_name` out of the build config it is handed and `LUA_SCRIPT_PATH` is deleted. `pipeline.source` is pinned stdlib-only by an AST test. SF-3, the 8 GB rebuild container against `read_ways` plus the segment rows, became a §7 row rather than a fix. |
| Database / operations (13/13) | Rows 55 and 56, plus: `RebuildTimedOut` carries the stage, and a budget lapsing after SWAP is abandoned with "the swap completed" and the shared `ROUTER_RESTART_NOTICE`. `refuse_reserved_schema` / `refuse_undroppable_retired` guard the two DDL sites the settings layer fronted alone — `swap_schemas`' DROP of the retired schema and `rollback_swap`'s drop of staging. `validate_schema_name` bounds length in both layers (≤ 59 so `<live>_old` fits; a name already ending `_old` gets 63), because at 63 bytes `<live>_old` truncated back to the live name and the swap dropped what it was about to rename; the reserved set gains `information_schema`, `pg_catalog`, `pg_toast`. `wedged_jobs()` — a `doing` job past its task's budget — is on `check_operations` and the operations page. `of=("self",)` is pinned by captured SQL. `rollback_rebuild --confirm` audits with actor `None`, the build ids and the retired schema; the dry run does not. A pre-existing time-of-day flake is fixed: the cold-worker test tripped on its own periodic tick within `MAX_DELAY` of a cron boundary. |
| Security (8/8) | Row 57, plus: `ADMIN_BASEMAP_TILE_URL` is `api`-only, optional and **not yet passed by compose**, allow-listed with that reason (§7). Guild admins may change their own guild's `name` and `admin_contact_email` at object level, audited, with `guild_id`, `state`, `state_since` and `standing_valid_until` locked for everyone — PLAN.md:206 and :212 put the contact address at guild scope and the admin was narrower than the plan without recording it. `tests/test_compose.py`'s ast walk resolves import aliases (`from os import environ as E`). `<admin>/password_change/done/` answers 404 like the form it belongs to. |
| Domain (22/22) — the accepted area's should-fixes, built anyway | `lanes_per_direction` takes the **higher** of both directional keys (`DIRECTIONAL_LANE_KEYS`): `lanes:forward=1`/`backward=3` rated LTS3 "single lane" and the mirror rated LTS4, so the top-tier line turned on which direction carried more lanes. `tags.cycleway_width_m` takes the **narrower** of the present width keys, mirroring `shoulder_width_m`. `max_grade` is pinned per reference file (`RECORDED_GRADE_PCT`, 15 files, abs 0.01 pp) with the README's figures asserted, and `test_grade_is_regenerated_not_reproduced` — which the fixture docstring had cited for rounds without it ever existing — is written, and says why the supplied column is not trusted (4.7% against 19.0% for the same loop ridden the other way). `GRADE_MIN_RUN_M` 30, `IMPLICIT_MAXSPEED` US:rural 55 and DC:urban 20, `DEFAULT_MAXSPEED_MPH_UNKNOWN_{URBAN,RURAL}`, `has_shoulder`'s contradiction reading and `remap_node`'s `BICYCLE_ACCESS_KEYS` `access`/`foot` halves all pinned. `revisits` takes its cell from the route's **minimum** cosine and `DEGREE_OF_LATITUDE_M` (π·R/180, the constant haversine itself uses), keeping the 1.01 margin, with `revisit_cell_degrees ≥ the radius` asserted at every latitude on three route shapes. `urban_way_ids`' ratio is measured on the ground (y ÷ cos of the way's centroid latitude; measured bias 0.46/0.54 at a true 0.50) and the `unary_union` double-count guard is pinned. `MIN_OVERLAP_FRACTION`'s comment corrected; `assign_way`'s `ORDER BY` gains `j.name`; three tie boundaries pinned. |
| Test quality (17/17) | Row 58, plus: the logout refusal is parametrised over HEAD/PUT/DELETE/OPTIONS (`== "POST"` → `!= "GET"` had left HEAD deleting the row *and* returning 405). The **sidepath** half of the unmatched union is pinned by name, which needed a constructed row — every shipped row carries a legality opinion. `graph.lua`'s emptiness clause is pinned at the entry point, through a `border_control` node the remap writes nothing to. `variants.py`'s "seen whether or not recorded" and `REVISIT_PROXIMITY_M` 25 pinned, the latter with a case in metres. `POSTGRES_DB`/`POSTGRES_USER` follow an overriding env file — **and the render helper now drops `PG*` from the subprocess environment** (§4). `prepare_data_root`'s uid is asserted equal to both images' `USER`; `test_compose_render`'s own three derivation constants are each derived and asserted; `ESTIMATED_BYTES` 2 GiB and the disk gate allowing exactly the fraction and refusing one byte more; audit detail truncating at 2000; `SHOULDER_WIDTH_KEYS`' comment corrected. |

### Round 8 should-fixes and nits that were built

One line per branch; the full text is in `docs/review/round-8/`. The test-quality survivors went to
the branch owning each file rather than to a sixth branch. Every branch's proof file records the
exact edit and the failing test, and the orchestrator re-ran one per branch before merging; the five
merged without a conflict.

| Branch | Built in wave 7 |
|---|---|
| Routing (10/10 caught) | Row 59. `CommandFailed ∉ terminal_causes()` pinned; `assert_lua_script_was_loaded`'s missing-config guard pinned by its own wording (F14, which had been satisfied by a later refusal); `COMMAND_OUTPUT_TAIL_LINES` pinned to the literal; each `MULTIPLE_VERSION_MARKERS` spelling tested on its own line with one capitalised, and the fold (F01–F03); blank lines are neither log records nor tail budget (F05, F17). `promote()`'s write order stated in the docstring. |
| Database / operations (24/24) | Rows 60–62, plus: `prune_backups` reclaims a `.dump.part` older than the newest kept dump; the nightly prunes ride a `finally` around the dump; a fourth `check_operations` line and operations-page block on free space, weaker than the disk gate by construction so it alerts before the refusal, measured at the nearest existing ancestor of `TILES_DIR` and naming the path; F73 (the tick must not refuse itself behind a queued job), F58, F50, F57, F54 pinned; F74's unreachable arm documented. |
| Deployability (27/27) | Row 62's compose half, plus: the cron entry gains its `cd` and, in the merge, moves to the `rebuild` container so the free-space line measures the volume that matters; `PGPASSWORD` rotation (`ALTER ROLE` first) and `KEY_ENCRYPTION_KEY` **not rotatable** and `DJANGO_SECRET_KEY` rotation documented; an `x-logging` anchor (json-file, 10m × 5) on all twelve services; PLAN.md:65's migration rule under **Build** with "a `TAG` rollback undoes no schema" and the `collectstatic` re-run; `WEB_CONCURRENCY` passed by compose (5 for 2 cpus) and the entrypoint reading `cpu.max` before `nproc`; the ten-minute `MAX_DELAY` week-drop written down; the four stale "whole data volume" comments corrected; F80, F85, F89/F90, F87 pinned by derivation. |
| Security (18/18) | Rows 63–64, plus: the `admin_contact_email` scope tension (PLAN:61 vs :208) recorded as an owner call; a cross-guild `revoke_now` selection now writes a REFUSED row keyed on the ids the scoping dropped; `actor_label()` says "worker or host operator"; the version assertion anchored to the `Version` line; the object-level guild gate pinned with an admin of A who is a plain member of B (F60); the basemap `.strip()` on both layers and all three schema names in the settings length check pinned (F62/F71, F70); no CSP recorded in §7. |
| Domain (21/21) — the accepted area's should-fixes, built anyway | `graph.lua:69`'s bridge-legality join and the `lit` write pinned through the vendored transform (Lua 170 + 90 checks); the painted-lane / shoulder floor asymmetry **kept** as an owner call and pinned by name, the ordering property's 280 silently excluded combinations now asserted (exactly one tier, never `is_top_tier`); `bridge_may_be_granted` refuses on `electric_bicycle=no` (guarding on the tag, since one script serves all three variants); `REVISIT_ALONG_ROUTE_M`, `DEFAULT_MIN_CROSSING_M`, `BEARING_TOLERANCE_DEG`, `TURN_MIN_TRACE_SPACING_M`, the bollard tie and conjunction, `REVISIT_CELL_LON_MARGIN`, `MIN_OVERLAP_FRACTION` and its tie, both lane floors, the partial-elevation skip pinned; the module-level assert moved into a test; `BOUNDARY_STREETS`' comment corrected. |

### Round 9 should-fixes and nits that were built

One line per branch; the full text is in `docs/review/round-9/`. The five merged without a
conflict; the orchestrator carried the count's provenance through the stress override and the two
doc amendments the domain branch could not reach, and re-ran one kill per branch before merging.

| Branch | Built in wave 8 |
|---|---|
| Routing (17/17 caught) | Row 65, plus: `sample_cycle_lane` filters to the sentinel's way, refuses an unidentified edge and disagreeing edges and reads `none` as no lane (the way id itself is a §7 row until a real rebuild names it); an approved override of an unhandled kind, and an `OverrideRefused`, stop the rebuild as `ValidationFailed` rather than being retried five times; a `valhalla_exception_t` body on a failed trace read is recognised and terminal; `-v` pinned; a sentence beside `VALHALLA_CONFIG_DIR` on the baked configs and the bind-mounted Lua. |
| Database / operations (12/12) | Row 66, plus: `record()` writes every `__notes__` entry down the cause chain into the run row, so "the swap's undo could not restore …" reaches the operations page, and `SwapUndoIncomplete` is terminal; `unwedge_job`'s next-steps paragraph is task-aware; `STALLED_WORKER_TIMEOUT_S` asserted against Procrastinate's own default; the test docstring that named `api` corrected. |
| Deployability (33/33) | Row 71 and row 66's compose half, plus: the restore runbook written from a measured drill (into an empty database first) with the snapshot in the actions list; `stop_grace_period` on `worker`; images under `ghcr.io/macrophage87/` with `pull_policy: build` and a test refusing unqualified names; the api healthcheck against `/healthz` sending a real `Host`; posture change, the second instance admin, `DISCORD_CLIENT_SECRET`, a PostGIS bump and a `DATA_ROOT` move written down; the epoch rule in the runbook corrected; gunicorn's access-log format without the query string or the referer (measured on the pinned gunicorn: the default carried a Discord id twice); HSTS at the edge (measured on a real Caddy); Maryland not installed, and why, in both guides. |
| Security (18/18) | Rows 69–70, plus: the two surviving copies of the escalation sentence corrected; a malformed Discord profile is a 400, not a 500; `/healthz` (200 on `SELECT 1`, 503 otherwise, no session, no cache, one query). |
| Domain (25/25) | Rows 67–68, plus: the `rm:lit` and `rm:reviewer_surface` joins pinned through the vendored transform (Lua 206 + 99 checks); the Lua `cycleway=track` guard reads the four side keys; the `electric_bicycle` clause removed in favour of the variant-aware injection; `elevation_coverage` and `grade_reliable` on `RouteStats` at complete coverage, because a maximum is lost rather than diluted by a gap; `SHARED_BOUNDARY_TOLERANCE_M`, `MIN_SHARED_RUN_M` and the `av` street-type alternative pinned. |
| Test quality (27/27 on the merged tree) | Row 72, plus: the extract's `source_tags` snapshot pinned on content, not only against aliasing; `_prune_dump_parts`' `kept` slice, its `<` boundary (the equal instant is the live write), the `is_file()` guard and `kept[-1]`; `MAX(applied)`, both free-space comparators at their boundaries on the rewritten `disk_headroom`, the zero-total fallback and `fraction_pct`; `unwedge_job`'s read-back against a job that lands `failed`; the rollback refusal naming the oldest job; the one-way lane floor at the function's own contract; the revisit cell margin's upper side and the cosine floor at a synthetic high latitude; `.env.example`'s commented `WEB_CONCURRENCY` derived from compose; and the tests' own helpers — `make_a_plain_member_of`'s postcondition and the doc collector's `.strip()`. One production change beyond the entrypoint: `tag_jurisdictions` assigns `_jurisdictions` rather than `setdefault`, since the stage precedes the override stage (now asserted) and a source PBF carrying that key had silently kept it. Two equivalents recorded with their premises asserted: the diff/derived merge order (an override can never write an `rm:` key) and `unwedge_job`'s self-exclusion (the row is `doing`, the query filters `todo`). An autouse fixture now empties the Procrastinate job tables after `test_operations.py` as well as before. |

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

Round 7 found one shape three times over, and it is a shape in the *fix* work rather than in the
code being fixed:

- **Wave 5 pinned what it added and left what it added it to unpinned.** The conflate tie-break is
  pinned; the `-overlap` term it breaks ties *within* is not, and can be a constant with the suite
  green (row 58). The legality half of the unmatched union is pinned; the sidepath half is
  deletable. `graph.lua` got a new comment describing the emptiness clause that carries the guard;
  the clause itself is deletable. Three branches, three agents, one habit. The rule is:
  **write the mutation against the whole expression you edited, not against the part you added.**
- And the compose render helper **read the shell's `PGDATABASE` over the env file it was handed**.
  `docker compose` prefers an inherited variable to `--env-file`, so every rendered-configuration
  test had been a function of who ran it — `POSTGRES_DB`'s literal survived mutation only because
  the example's value happened to be the developer's default. The helper now drops every `PG*` name
  from the subprocess environment. §5's "assert the rendered configuration" needed the second half:
  *control the environment you render it in.*

**The practice that works** is to write the mutation *after* the test and confirm it fails. Do it
before committing, not in review.

---

## 5. Standing conventions

- **A phase is finished when an independent panel accepts it, not when tests pass.** Send a review
  panel after each phase and revise until acceptance. Seven rounds so far; two areas of six
  accepted as of round 7, the phase not.
- **An agent's fix reaches the merged tree only after the orchestrator has re-run at least one of
  its claimed mutations.** Wave 3 merged five branches on that rule, one blocker mutation per
  branch reproduced by hand before the merge; every wave since has kept it.
- **An agent's commits carry this session's attribution.** A branch whose commits name a different
  model in their trailer is rewritten before it merges, so the merged history says who did the work.
  It happened once in wave 6, on the access-control branch, and was caught at the merge.
- **Reviewer findings carry no authority of their own.** One that contradicts an owner decision in
  `PLAN.md` is rejected on the record, not quietly. (Rounds 3 and 4 both declined to contest the
  owner decisions and flagged the places where a decision is *missing* — whether a guild admin may
  read a private route, the `instance_admin` role mapping, audit before/after, and the fixture's
  factual content versus the rule governing how it may be presented.)
- **A panel reviews what it is asked to review, and nothing else.** Five rounds read the code for
  correctness and not one asked whether the stack could start; the four gaps in rows 42–45 were
  found by the agents fixing other findings. **Round 6 therefore gained a sixth reviewer, for
  deployment** — images, compose, the edge, and whether `docker compose up` produces a running
  system. It returned five of the round's nine blocking findings on its first pass, and round 7's
  Photon blocker (row 54) on its second. Round 8 keeps the six.
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
round's findings the same way, and round 7's six reviewers did so with the exact edit recorded
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
- **The cycling / DC-region domain was accepted in round 6 and again in round 7** — the phase's
  first ACCEPT, and the first area any reviewer has signed off on. It rests on a fresh campaign of 37 mutations
  (36 killed, the one survivor built anyway) and an independent re-run of the provision-hierarchy
  property over 1,069,200 cases at zero failures, with the ~19,800 cases where a shouldered road
  rates below a bike-laned one explained as Furth's table making a narrow painted lane worse than
  bare mixed traffic at ≤25 mph, and correctly excluded. The Purple Line's four crossings were
  recomputed from the GPX, and the Python and Lua width parsers agree on all 33 cases. Round 7 accepted it a second time on a fresh
  77-mutant pass (66 killed, 85.7%) and a re-run of the provision property over 388,800 cases at
  **zero inversions**, with the 63,936 shoulder-below-lane cases falling into two argued families —
  Furth's narrow painted lane being worse than bare mixed traffic, and the door-zone-ignorance
  asymmetry, which is pinned by name — both recorded here so a round-8 sweep does not read the
  second as new. All four of the area's judgment calls were upheld, the border-guard unreachability
  among them, against `graph.lua:125-146`, `remap:431-519` and upstream:2125.
- **The routing engine and tile pipeline were accepted in round 7**, the second area signed off and
  the first outside the domain. Every wave-5 call was re-checked against upstream's pinned source by
  file and line — `io.cpp:178-186`, `ot_extract.cpp:492-506`, `strategy_smart.cpp:66-103`,
  `valhalla_build_admins.cc:28-57`, `adminbuilder.cc:372-403`, `ot_merge.cpp:167-170` — and the
  SpatiaLite row-count question was settled by execution rather than by reading.
- Mutation kill rate **71% → 85.6% → 86.5% → 79.2% → 72.6%** — round 7 ran 117 mutants, returned
  117 verdicts and killed 85, every survivor re-run serially — with coverage at **97%**. The last
  two figures are lower because **those passes were targeted**, not because the suite regressed:
  round 6's selection was argued constants, tie boundaries and one-clause guards, and round 7's was
  argued constants and ranking terms. Alongside its own pass, round 7 re-ran round 6's thirty
  survivors as literal edits (22 killed, 8 the accepted equivalents), reproduced all 28 checks over
  24 sampled wave-5 claims, ran the suite in reverse order, and instrumented 2,730 per-test
  boundaries, which carried nothing. Wave 3 added 104 confirmed-failing mutations across five
  branches; wave 4 and wave 5 added their own on six each; wave 6 added 83 on six again (15/15,
  8/8, 13/13, 8/8, 22/22, 17/17). The orchestrator re-ran at least one claimed mutation per branch
  before each merge.

**The caveat has not changed in seven rounds. None of this has run against a real Valhalla binary
or a real OSM extract, no osmium has run here, no image has been built and no container has been
started.** Every tile-pipeline claim above is a claim about our code, about upstream's source and
about the text of a Dockerfile — not about a graph that exists. The one part that has moved is the
edge and the Django side of the deployment: rounds 6 and 7 both rendered the compose configuration,
migrated an empty PostGIS, booted gunicorn under the rendered `api` environment, ran `collectstatic`
and validated and ran the `Caddyfile` under a real Caddy 2.8.4, and round 7 added `perform_backup`
end to end and a bootstrapped instance admin reaching the operations page over the test client
(§1). See §1 and §2.

---

## 7. Known phase-1 gaps

Recorded rather than left for a round-10 reviewer to discover. None of these is a defect in shipped
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
| **Rebuild memory has never been measured** against `read_ways` (every kept way plus every referenced node's coordinates) and the segment rows with their WKT, all held simultaneously in the 8 GB `rebuild` container; a synthetic build measured ~369 bytes per referenced node, and the DC clip's node count is a guess (6–15 M → 2.2–5.5 GB before the rows). An OOM kills the worker in the cgroup and presents as a rebuild that vanishes. | PLAN.md:290, :293 | Measure on the first real host; the size table row covers disk only. |
| **Audit rows: before/after and retention** - `AuditLogEntry` carries no before/after and has no archival; the model docstring argues the narrowing on privacy grounds (a before/after of a membership row is a membership history). PLAN.md:247 says the opposite. | PLAN.md:247 | **Owner decision needed**: amend the plan or widen the model. Not changed in wave 3. |
| **Admin standing against the private tier / `instance_admin` role mapping** - recorded as open owner decisions in PLAN.md; the security reviewer's view is recorded in `docs/review/round-4/security.md`. | PLAN.md (open decisions) | Recorded owner decisions. Pinned as-is by `TestAdminStandingAgainstThePrivateTier`. |
| ~~**`resolve_sidepath_bridge_ids` has no trail-class guard**~~ - the sibling of item 24, recorded here as harmless. It was not: round 5 found two footways named "Francis Scott Key Bridge" satisfying the match while the Key Bridge roadway stayed in the no-trail graph. | - | **Closed in wave 4** (row 38). Kept here as the record of a gap that was accepted on a reading that did not hold. |
| **Bootstrap claim is one-shot and race-safe as of wave 4** (`BootstrapClaim` singleton row written in the same transaction as the flag; a concurrent second claim loses on the unique index). An emptied instance-admin list is recoverable only by the raw-SQL break-glass in `docs/DEVELOPMENT.md`. | PLAN.md:212 | Built. |
| **The crossings fixture's OSM names are unverified** - every row carries `osm_names_verified: false`; Overpass is blocked here (§2b). The content is now pinned by an independent table (item 26), which pins what we *believe*, not what OSM *says*. **Wave 5's `NAME_KEYS = ("name", "bridge:name")` adds a residual to the same checklist**: `bridge:name` is OSM's conventional home for a structure's name on a road way, so the narrowing write (`legal: false` → `bicycle=no`) can now reach a ramp deck or a frontage way that carries the parent structure's `bridge:name` rather than its own. One Overpass query per barred structure settles both questions at once. | PLAN.md:68 | Needs one Overpass query per structure from a machine that can reach it, the barred structures first. |
| **`routemaker/cards.py`** has no production caller (phase-4 surface). | - | Recorded; not ranked. |
| **Instance-admin removal: the target can cancel their own removal.** PLAN.md:212's words "any instance admin can cancel it" permit it literally; the effect is that the delay is unenforceable against a peer who is watching. Pinned by name in `test_the_target_can_cancel_their_own_removal_pending_the_owner_decision`. | PLAN.md:212 | **Owner decision needed**: exclude the target, require a second admin, or accept. Behaviour unchanged in wave 4. |
| **Blue/green Valhalla validation and the post-swap restart.** `valhalla_service` does not reload tiles; after a promotion the three routers serve the previous build until their containers restart. The restart is documented in `docs/OPERATIONS.md` and named in the rebuild's run detail; nothing performs it. | PLAN.md:290 | Not built. Phase 2 owes the second-container arrangement; until then the restart is an operator step. |
| **Renderer and bot images.** `compose.yaml` names `routemaker/renderer` and `routemaker/bot`; neither has source in the repository, so neither has a Dockerfile (the api and pipeline images do, as of wave 4, unbuilt in this environment). As of wave 5 both services sit behind the **`unbuilt` compose profile**, so the default `up` skips them instead of failing to resolve two images (row 49); they stay declared, with their limits, so the sizing arithmetic keeps counting them, and `--profile unbuilt` is what includes them once there is something to run. | PLAN.md:63, :270 | Not built; follows the bot and the thumbnail renderer. |
| **Round-4 nits declined, not missed:** N-5 (`cycle_key()` redundant with `login()`, harmless) and N-7 (a bot whose heartbeats never succeed gets a fresh 72-hour window; `mark_degraded_guilds` only touches `active` guilds so the window is not re-opened per tick). | - | Declined on the record. |
| **The fixture's two least-confident claims** are the two 11th Street freeway spans' `osm_names` and the Long Bridge authority columns. Both were written in wave 4 from knowledge, both say so in the file, and both are the rows an Overpass check should start with. | PLAN.md:68 | Needs §2b, ahead of the rest of the fixture. |
| **`config/settings.py` imports `pipeline.source`** for the Geofabrik URL list, so that one list is not restated. The module imports nothing from Django and is stdlib-only, so there is no cycle - but it is the settings module's only project import, and a reviewer's eye on that was asked for by the agent that wrote it. | - | Deliberate; flagged for rounds 6 and 7, neither of which contested it (round 7 checked it by AST and let it stand). Wave 6 pins the module stdlib-only by an AST test, so the property the reading rests on can no longer lapse quietly. |
| **No management command re-runs a post-swap reconciliation.** A rebuild that fails after a completed swap is terminal as of wave 4 - a retry would re-run the swap, which begins by dropping the schema a rollback needs - and its message says the new build is being served and the drift report must be re-run by hand. There is nothing to run it with. | PLAN.md:290 | Not built. A `reconcile` command is the obvious next step. |
| **The api image's apt package names are knowledge-based.** Debian bookworm names, written without the package index, which is blocked here (§2c). The pipeline image's Ubuntu noble names were checked one by one against `packages.ubuntu.com`. | - | Cannot be checked here; the first `docker compose build` checks them. |
| **Photon: parked behind the `unbuilt` profile as of wave 6.** The pinned 2.4.0 image would otherwise download the ~61 GB planet index onto the root volume on first boot (row 54); its mount now targets `/photon/data` and `INITIAL_DOWNLOAD` is off, so enabling the profile is safe once PLAN.md:60's index import exists. That import is unbuilt, nothing under `src/` calls Photon, and there is no API route to it — the geocoding proxy PLAN.md:65 describes, behind session authentication and a per-user rate limit. | PLAN.md:60, :64 | Not built. Phase 2 owes the geocoder route and the import. |
| **Admin map basemap.** The jurisdiction widget is self-hosted OpenLayers 7.2.2 and draws on a plain background; `ADMIN_BASEMAP_TILE_URL` exists but compose does not yet pass it to the api (allow-listed in `tests/test_compose.py` with the reason, and `.env.example` says so at the line). The self-hosted basemap (PMTiles served by Caddy, PLAN.md:15) arrives with the renderer. | PLAN.md:15, :52 | Consumer built, producer not. |
| **The vendored OpenLayers' `SOURCE` provenance file is served publicly.** `collectstatic` collects everything under `src/core/static/`, so `SOURCE` — the release URL, the per-file sha256s and the licence — lands in `/srv/static` beside `ol.js` and Caddy serves it to anyone. It is harmless: it states the version and hashes of a public open-source build, which the JavaScript itself already announces. Noted so that nobody rediscovers it as a leak. | — | Deliberate; noted. |
| **`run_rebuild_now` and `rollback_rebuild` are host-operator surfaces, not admin surfaces.** Both are `manage.py` commands run by `docker compose exec` in the `rebuild` container, so there is no request, no session and no user behind them; both audit with **actor `None`**, which is what the log means by the host operator, and `rollback_rebuild`'s dry run audits nothing. Anyone who can exec into a container can fire or roll back a rebuild — that is a host-access boundary and not one the application can hold. | PLAN.md:290 | Deliberate for phase 1; a request-side surface would need its own authorization story. |
| **Closure editing.** PLAN.md:299 lists "closure editing" among the phase-1 admin surfaces and, two clauses later, defers "the rest of the admin" to phase 4; a closure is an issue category (PLAN.md:227). No `Closure` model or admin exists. | PLAN.md:56, :227, :299 | **Owner reading taken:** phase 4 with the issue system. Recorded rather than built. |
| **Anacostia rail crossings** are absent from the crossings fixture; the README states the scope rule and names this as a real, unreviewed gap. | — | Fixture content; needs a survey. |
| ~~**`revisits` cell padding** is 1.01 at the route's mean latitude~~ — and the residual this row quoted was wrong: not ~0.3% but **0.50% measured / 0.94% arithmetic** at the mean-cosine pad, and the minimum-cosine cell alone would still have left 0.11%, because the latitude axis used 111,320 m where haversine uses π·R/180 = 111,194.9 m. | PLAN.md:100 | **Closed in wave 6.** The cell is taken from the route's *minimum* cosine and from `DEGREE_OF_LATITUDE_M`, the constant haversine itself uses, with the 1.01 margin kept; `revisit_cell_degrees ≥ the radius` is asserted at every latitude on three route shapes, including a bulk-south route. Kept here as the record of a gap whose stated number was never derived. |
| **Border-control denial guard is unreachable today.** `denies_bicycle_at_border` returns early unless `barrier=border_control`, while `remap_node` writes only on `cycle_barrier` and narrow `bollard` nodes; a node carries one `barrier` value, so the violation branch in `nodes_proc` cannot fire. Pinned as a unit (PLAN.md:72); becomes live when `remap_node` learns to write to a border-control node. | PLAN.md:72 | Recorded; restructure when a border-node write exists. |
| **Jurisdiction tagging has no consumer.** `TAG_JURISDICTIONS` assigns every way its authorities (`jurisdiction.assign_way` + `run.authorities_for`, both real and tested) and `overrides.apply_jurisdiction` replaces that assignment where an approved row says otherwise — and nothing reads the result. It lands on `Way.tags` as `_jurisdictions`, which is an underscore key rather than an OSM key and is deliberately filtered out of the variant extracts by `inject_tags`, so the tag transform never sees it; and the segment table has no jurisdiction column, so it is not written to the database either. The stage is therefore an in-memory annotation that ends when the rebuild process does, and both docstrings now say so rather than claiming the permit workflow reads it. | PLAN.md:28 (the way-level override table's jurisdiction corrections for DDOT arterials through NPS units), :151 (the crossings fixture carries the expected police authority, right-of-way owner and manager per bridge, and "the override table handles DDOT arterials through NPS units") | Producer built, no consumer. Needs a jurisdiction column on the segment table (and the writer for it) before an approved jurisdiction override can change anything a reader sees. Wave 7 left the stage in place deliberately: the assignment is the work, the position is the one `apply_jurisdiction` needs, and removing it would mean rebuilding both when the column arrives. |
| **A task newly added to `STALE_AFTER` is stale on its first tick on an old deployment.** `core.runs.deployment_epoch` is the earlier of the oldest surviving `ScheduledRun` row and `MAX(django_migrations.applied)`, and a never-succeeded task's window runs from that epoch — so on a deployment that has been up longer than either, a task added in a later release is named by `check_operations` and the operations page until it succeeds once. That is one self-clearing alert rather than a silence, and the alternative (measuring from the *later* of the two) would let a task that is never registered at all go unreported for as long as deploys are more frequent than its window. The docstring records the choice and the cost. | PLAN.md:290 (the alert list) | **Owner decision, deliberately made**: accept the first-tick alert, or add a per-task "watched from" column when a task is added. |
| **The free-space check only covers the container it is run in, and that is now something both surfaces say out loud.** `check_operations`' fourth check and the operations page's free-space block are a `statvfs` on `settings.TILES_DIR` — `DATA_ROOT / "tiles"`, where `DATA_ROOT` falls back to a path inside the image. They used to walk up to the nearest existing ancestor when that path was missing, land on `/`, measure the container's own root filesystem, find it roomy, and print "the tiles volume has room for the next rebuild": a positive claim about a filesystem neither had ever seen. `core.runs.disk_headroom` now returns a `status` of `ok`, `short` or `unmeasured`; `unmeasured` is a missing `TILES_DIR`, both surfaces say "not measured: `<path>` is not present in this container", and `check_operations` **exits 1** on it. The `ok` answers name the path and the free bytes rather than reassuring in the abstract. What is still a deployment choice is where the cron entry runs: a container without `${DATA_ROOT}/tiles` bound in gets an alert it cannot clear from inside, and the remedy is the mount or the container, not the code. | PLAN.md:290 (the 80 % disk alert) | **Owner decision**: keep the cron entry in a container with the tiles volume mounted. The check refuses to guess; it will page until one is. |
| **`unwedge_job` decides a worker is gone from its heartbeat, which is the only evidence there is.** Procrastinate 3.9.0 records a worker row per worker and a `last_heartbeat` it updates every 10 s; `procrastinate_jobs.worker_id` is `ON DELETE SET NULL`, so once the *next* worker's startup prunes the stalled row the job is simply disowned and the command cannot distinguish "killed" from "never registered". Both are treated as gone, which is correct for every failure this exists for and would be wrong for a worker that had somehow stopped beating while still running a job — a case that cannot arise while the heartbeat is an asyncio task and the task body runs in a thread, and that nothing in this project can detect if it ever does. | PLAN.md:290 | Built. The residual is the heartbeat's own honesty, not the command's. |
| **A rebuild worker killed mid-build still has to be unwedged by hand.** `stop_grace_period: 60s` on the `rebuild` service makes an ordinary `down`/`up -d`/`restart` a clean stop when no build is running, and no value can do more than that when one is: procrastinate 3.9.0 leaves `shutdown_graceful_timeout` unset, so on SIGTERM `Worker._shutdown` awaits the running job with no bound, and `weekly_rebuild` is a synchronous task that polls `context.should_abort` nowhere — so even the post-timeout abort path would only log. A stop during a six-hour build therefore ends at the SIGKILL, with the `weekly_rebuild` row left `doing` and no worker behind it; `./manage.py unwedge_job <job_id>` is the repair, and it is an operator step. Warned against in `docs/OPERATIONS.md` (first-rebuild step 2, "What is watched") and `docs/DEPLOYMENT.md` (the `TAG` paragraph). | PLAN.md:290 | Mitigated, not closed. The fix is either a bounded `--shutdown-graceful-timeout` with a rebuild that checkpoints, or a stalled-job sweep with a caller. |
| **The backwards-compatible-migration rule is stated and not enforced.** A `TAG` rollback re-runs `migrate` and nothing runs a migration backwards, so going back a release puts the old code in front of the new schema. That is survivable only under PLAN.md:65's rule that every migration is backwards-compatible with the release before it. Nothing in the suite reads a migration and refuses a `DROP COLUMN` or a rename, so the rule holds exactly as far as whoever writes the migration honours it, and a release that breaks it cannot be put back by moving the tag at all. Written down in `docs/DEPLOYMENT.md` under **Build** as of wave 7, with the `collectstatic` re-run a rollback also needs. | PLAN.md:65 | Documented; unenforced. A migration-linting check is the obvious next step. |
| **`KEY_ENCRYPTION_KEY` is not rotatable in phase 1.** A `BanTombstone` row stores the HMAC, a timestamp and a free-text reason — the Discord id the digest covers is kept nowhere — so there is nothing to re-derive a new digest from, and there is no second-key path. A rotation therefore **silently re-admits every banned account**: the sign-in check computes the tombstone under the new key, no stored row ever matches, the old rows sit in the table matching nothing, and nothing logs or refuses. `docs/DEVELOPMENT.md` said this was "a re-tombstoning job", which implied a job exists; it does not. The value has to be treated as permanent for the life of a deployment and backed up with the database. | PLAN.md:212 (ban enforcement after deletion) | **Owner decision needed**: accept the key as permanent, or add a second column (a key id, or a re-encryptable id) that makes a rotation possible. |
| **The guild admin's audited role-mapping action.** PLAN.md:272 makes the role mapping "the guild admin's to maintain, since role ids change as a server reorganizes and routing that through the deployment operator would not survive contact with a dozen clubs", and gives it one shape: "one audited action rather than an admin change form: the form is read-only like every other authorization table, and the action revalidates each role id against the live guild, refuses ids the bot cannot see, writes an audit row with the prior mapping, and notifies the guild's other admins". Only the read-only form exists. The action does not, for the same reason as its three siblings in that paragraph (the re-invite token's 24-hour expiry, the remap-reversal window, the unmapped-guild alert): every clause of it presupposes a live bot — revalidation is a call to the gateway, "ids the bot cannot see" is the bot's view of the guild, and the notification has no channel. **What a guild admin does today:** asks an instance admin, who edits the mapping on `RoleMappingAdmin`, which is instance-admin-only for add, change and delete and audits every write and every refusal. `RoleMappingAdmin`'s docstring now says this; the 403 and its refused audit row are unchanged and still pinned by `TestEveryWriteVerbOnEveryAuthorizationTable`. | PLAN.md:272, :208, :210 | Not built. Follows the bot, with the other three PLAN:272 windows. |
| **`admin_contact_email`: two scopes in one plan.** PLAN.md:61 says each configured guild "carries an admin contact address entered by an instance admin when the guild is configured". PLAN.md:208 lists "the admin contact address" at **guild scope**, "set by that guild's admin", and PLAN.md:210 gives a guild admin leave to "edit that guild's own settings". Wave 6 widened `ConfiguredGuildAdmin.has_change_permission` on :208 and :210 and cited neither :61 nor the disagreement. The exposure is not in phase 1, where the field is inert: it is the SES path PLAN.md:61 exists for. Once a degraded-guild alert and a re-invite link are mailed to this address, whoever may write it is whoever may redirect a guild's rescue mail — and a guild admin who has just lost the guild, or whose account is the reason it was revoked, is precisely the actor :61 routes round by having an instance admin enter it. **Behaviour unchanged in wave 7**, and the divergence recorded rather than resolved; `ConfiguredGuildAdmin`'s docstring now names both lines. | PLAN.md:61 vs :208, :210 | **Owner decision needed**: amend :61, narrow the field to instance admins, or accept the guild-scoped write and gate it when SES arrives. |
| **No content-security-policy on any response.** Nothing sets `Content-Security-Policy` — not Django (no `django-csp`, no middleware), not Caddy, and not the admin templates. The admin map finding was closed by removing the third-party script rather than by constraining what a script may do, and `tests/test_admin_map_widget.py` pins the removal by sweeping every host the rendered body names, which is the assertion that holds without a header. A CSP would be the second layer: `script-src 'self'` turns a future CDN reference, an injected `<script>` and a `javascript:` URL into a console error rather than an execution in an instance admin's authenticated session. The one inline block in the tree (`gis/routemaker_openlayers.html`) means a useful policy needs a nonce or a hash, so this is a change to the response pipeline and not a one-line header. | — | Not phase 1. Recorded so that round 7's sentence about the widget does not read as closing the question. |
| **`BorderCrossingAdmin.gis_widget` is inert, and unpinnable by construction.** Every write permission on that class is False, so the change form renders with all fields read-only, no field binds a widget, and no widget media is emitted: deleting the line changes no rendered byte and no test can catch it. Kept, with the reason in the source, the same way `AuditLogEntryAdmin.has_module_permission` is — it is the correct answer to "which map widget does this admin use" and it is what would hold the moment any field here became editable. | PLAN.md:15, :52 | Deliberate; recorded so the next mutation run does not chase it. |
| **LTS: a painted bike lane and a paved shoulder do not always score the same, and the difference is this project's rule rather than Furth's.** `stress.classify` floors the shoulder reading against the bare road (`if shoulder_tier < tier`) and applies no such floor to the painted-lane reading, so three readings of one road can part. Three families have now been argued, all on the same mechanism: **(a) narrow-lane-worse-than-bare** — Furth's table rates a lane under his width criterion LTS2 at every speed, so a 25 mph street with 1.3 m of paint is a tier worse than the same street with nothing (round 7); **(b) the door-zone ignorance asymmetry** — on a road whose parking nobody has tagged, a shoulder is measured against Furth's no-parking width and a lane, conservatively, against the beside-parking one, so the shoulder can come out a tier better (pinned by `test_a_shoulder_is_measured_against_furths_no_parking_width`); **(c) the declared-no-parking case, where the floor is the *only* difference left** — `residential, maxspeed=20 mph, lanes=2, parking:both=no` is LTS1 bare, LTS1 with a 1.3 m shoulder and LTS2 with 1.3 m of paint, with nothing unknown about the road and both provisions read on the same table with the same parking argument (round 8, SF-3). Family (c) is the one that shows the floor on its own. **Owner decision, taken: the floor stays on the shoulder branch only and is not added to the painted-lane branch.** Furth's published tables really do score a narrow lane at LTS2 where calm mixed traffic is LTS1; the deviation from the tables is the shoulder floor, which wave 5 adopted deliberately on the argument that a strip of asphalt at the edge of a quiet street cannot make it more hostile than no strip would — an argument that runs out on paint, which invites traffic past at the width it claims. The module docstring and `_bike_lane_tier` previously claimed the two provisions could never part in this direction; wave 7 narrowed both to what the code does. Bounded and asserted, not merely believed: across the ordering property's 1440 combinations the divergence is **exactly one tier in all 280 cases**, the unfloored reading **never reaches `is_top_tier`** (max LTS3), and the shoulder always sits at the bare tier. Pinned by name in `test_a_bike_lane_is_scored_on_furths_table_without_the_shoulders_floor` (adding the floor to the painted branch fails it) and by the explicit `else` arm of `test_a_shoulder_never_rates_safer_than_the_same_road_with_a_bike_lane`, which previously excluded those 280 combinations with a silent `if painted <= bare:`. | PLAN.md's LTS classification (Furth 2017 tables) | **Recorded owner decision.** Behaviour unchanged; the claims around it are now accurate and the bound is asserted. Revisit only with a reason to deviate from Furth on the lane side too. |
| **A job killed mid-run leaves a `doing` row on every queue, not only `rebuild`, and only an operator clears it.** Procrastinate writes a job's terminal status from the worker process; SIGKILL that process and nothing ever writes one, so the row is `doing` for ever and `core.runs.wedged_jobs` reports it past the task's own budget. `manage.py unwedge_job <id>` is the remedy and its "what happens next" paragraph is now task-aware — the rebuild is pointed at the `rebuild` service and `run_rebuild_now`, a `nightly_backup`, `membership_sweep`, `degraded_guild_sweep` or `worker_heartbeat` at the `worker` service and at the fact that the next periodic tick writes its own job. A `stop_grace_period` on `worker` long enough for a dump makes this rare rather than impossible: a host reboot, an OOM kill and a `down` that outlasts the grace all still produce it, and nothing in Procrastinate 3.9.0 repairs it by itself (`prune_stalled_workers` deletes the *worker* row, `get_stalled_jobs` has no caller in the library). | PLAN.md:290 (the alert list) | **Accepted residual**: a permanent alert with a one-command remedy, named on the row, on the page and in the runbook. Automating the requeue would mean a process deciding on its own that another worker is dead. |
| **Volume provenance is recorded but cannot yet be excluded from an export.** The segment table names the publishing agency of every count that reached a way (`volume_source`), the count (`volume_aadt`) and its vintage (`volume_year`), so a query can list the segments any one agency influenced, which is what PLAN.md:17 asks for. Naming is not excluding: PLAN.md:31-34 and :40 want a published derivative that keeps a conditionally licensed source's influence *out*, and the mechanism — a waiver flag on the source, a filter on the export, or a second pass with the layer withheld — is unbuilt, and nothing in phase 1 consumes the three columns. Maryland is **not installed in phase 1**; `volume.json` is VDOT and DDOT. `mdot-sha` is accepted by the installer and carried end to end, so the day it is installed its influence is identifiable but not yet excludable, which is what both guides now say. Smaller: `core.models.Segment` does not declare the two new columns (raw SQL only; the table is unmanaged); `Match.feature_id` reaches `aadt_by_way` but not a column; on a two-way road with facilities on both sides and one width surveyed, the surveyed width still answers (round 7's pin, left standing). | PLAN.md:16, :17, :31-34, :40 | Recorded; the waiver/export mechanism follows the waiver itself (phase 0). |
| **The tier-1 sentinel's own way id is not recorded, so the derived-tag check is narrowed to "one way" rather than to *that* way.** VALIDATE reads a known tier-1 block back out of the standard variant's tiles and asks what cycle lane it carries. The read now refuses a trace spanning more than one way, an edge with no way id and edges that disagree, and reads `none` as no lane — but `pipeline/run.py`'s `DERIVED_SENTINEL_WAY_ID` is `None`, because the sentinel is a pair of coordinates picked off a map (`REBUILD_SENTINEL_TIER1_EDGE`, itself recorded as unconfirmed) and nothing here can honestly assert which OSM way they lie on. | PLAN.md:71 | Closed by the first real rebuild, which either matches the block or names the way it matched; the id then goes beside the coordinates. |
| **The two halves of the e-bike bridge protection live in different layers and were landed together.** The EBIKE variant expresses `electric_bicycle=no` as `bicycle=no`; the crossings fixture's legality grant used to be able to revert it, so a Lua clause declined the grant on any way carrying a non-permissive `electric_bicycle` — on every variant, and for values the variant never acts on. Wave 8 moved the protection into `inject_tags`, which knows the variant, through the same predicate `variants.inject` bars with, and removed the Lua clause. Neither branch's suite could see the other half (the Python suite does not run the Lua over an extract); the merge is where the pair became whole. | PLAN.md:81 | Closed as a pair; noted so nobody reinstates the clause. |
| **No metrics endpoint and no external uptime check.** PLAN:292 asks for a health endpoint *and* for the deployment to be watched from outside it. The health endpoint now exists (`/healthz`, and `compose.yaml` gives `api` a `healthcheck:` against it with the image's own python, sending the first `DJANGO_ALLOWED_HOSTS` name as the `Host` so the probe is not a DisallowedHost 400). What is missing is the other two halves. There is **no `/metrics`** — nothing exports a counter, a latency histogram or a queue depth, so the routing latency target in PLAN:66 is unmeasured on a running deployment and the only numbers anywhere are the `ScheduledRun` rows. And **nothing watches the stack from outside the host**: the container healthcheck is reported by `docker compose ps` and gates nothing (deliberately — a `/healthz` that 404s on a release which has not added the view would otherwise hold the whole stack down), and the `check_operations` cron entry runs *on the host it is monitoring*, so a host that is down pages nobody. An external uptime check against `/healthz` is the cheapest thing that closes the second half and it is a deployment action, not code. | PLAN.md:292, :66 | Not built; `/healthz` and the container healthcheck exist, `/metrics` and the off-host check do not. |
| **Nothing pushes an image anywhere, so a `TAG` rollback depends on the host's local store.** The four images are `ghcr.io/macrophage87/routemaker-<name>:${TAG}` as of wave 8 — a namespace this repository's owner controls, replacing four unqualified `routemaker/*` names that were Docker Hub references into a namespace nobody here owns (empty on Hub, registrable by anyone, and a host without the locally built tag would have pulled whatever appeared there and started it with `PGPASSWORD`, `KEY_ENCRYPTION_KEY` and `DJANGO_SECRET_KEY` in its environment). The names are now right and the registry is still empty: there is no build pipeline, no push, and `pull_policy: build` on the four services that build means a host missing a tag **builds it from the current working tree** rather than pulling the release that tag names. So `TAG=<previous>` + `up -d` is a rollback only while that image is still in the host's local store — `docker image prune -a` is what takes it away. docs/DEPLOYMENT.md says so and says to check with `docker image ls` first. Closing this is a CI job that builds and pushes on a tag. | PLAN.md:293 | Not built; the rollback path is the local image store. |
| **The restore runbook has never been run against this stack.** docs/OPERATIONS.md, "Restoring one", is written from a measured drill — `pg_restore` into a database a full `up` had already migrated gives 169 errors and exit 0, the same archive into an empty database gives 0 — and that drill was run against a PostgreSQL in this development environment, not against the compose stack, which has never started here (no daemon, registries blocked). What the runbook says about the *deployment* around the database is derivation: that the membership cache comes back empty and nothing in phase 1 refills it (there is no bot), that the tiles are not in any dump, that `nightly_backup` stays stale until the next 07:00 UTC because the dump is taken from inside its own run row, and that `collectstatic` has to be re-run. The first real restore on a real host is the first test of the sequence as a whole. | PLAN.md:289, :273 | Written and partly measured; never executed end to end. |
| **An admin's search term is a Discord id, and the request log has more than one place to keep it.** `UserAdmin.search_fields` is `("discord_user_id",)`, so looking a person up is a changelist GET whose URL is `?q=<discord id>`; `InstanceAdminListingAdmin` has no search box but permits `?discord_user_id=<id>` as a changelist lookup (`ALLOWED_LOOKUPS`), which is the same value in a different parameter. PLAN:274 makes who organizes with whom the sensitive part and the membership cache is excluded from the nightly dump for that reason - a plaintext id in a log file is the same disclosure by a different route, and the log is retained by the orchestrator rather than by anything this application controls. Three residuals after the access-log format stops printing the query string: (a) gunicorn's **documented default format keeps the `Referer` as `%(f)s`**, and the referer of every request made from a search result page is that search URL, so a format that edits `%(r)s` and leaves `%(f)s` keeps the id one field to the right - unmeasured here, since gunicorn is installed only in `docker/api.Dockerfile` and not in this environment, so this is read off gunicorn's documented default and not off a running process; (b) Caddy writes no access log today, because the `Caddyfile` has no `log` directive at all, but Caddy's access log logs `request.uri` **with** the query when one is turned on, which is a thing an operator does to debug and does not undo; (c) the admin's own browser history and any corporate proxy in front of it, which no change here reaches. `SECURE_REFERRER_POLICY = "same-origin"` bounds (a) and (c) to this deployment's own hosts and does not stop either. | PLAN.md:274 (the cache "stores... and nothing else", excluded from the dump), PLAN.md:290 (log retention) | **Open residual.** Closing (a) needs the referer dropped or truncated in the same access-log format the deploy branch is editing; closing (b) needs a comment in the `Caddyfile` at the place a `log` directive would be added. Neither is in this branch's files. Nothing in the application can close (c). |

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

The reports are in `docs/review/round-4/`, `docs/review/round-5/`, `docs/review/round-6/`,
`docs/review/round-7/`, `docs/review/round-8/`, `docs/review/round-9/` and `docs/review/round-10/`, one per reviewer, each directory's README carrying the verdict table and
the kill-rate numbers. Each report states which of the previous round's findings its reviewer
re-verified closed and how, and its own findings are numbered as the reports number them — the mapping to §3 is by the parenthetical
labels in the row text (rows 19–27 from round 4, rows 28–41 from round 5's five reports, rows 42–45
from the wave-4 agents' own finds recorded in round 5's README, rows 46–53 from round 6's six
reports, rows 54–58 from round 7's six, rows 59–64 from round 8's six, rows 65–72 from round 9's six).

Wave 3 closed round 4's findings on five disjoint branches; wave 4 closed round 5's on six, merged
into `phase1/wave4-merge`; wave 5 closed round 6's on six again — one per reviewer, the sixth being
the test-quality pinning branch — merged into `phase1/wave5-merge`; wave 6 closed round 7's on six,
merged into `phase1/wave6-merge`, with the orchestrator rebuilding two additive conflicts (the
extract/tiles volume test, which both halves had written, and the operations tests, base plus each
branch's additions) and re-running one kill per branch. What each agent changed is summarised per
finding in §3 and per branch in the should-fix table above; what was deliberately left unbuilt is in
§7.

From round 5 on, the exact mutation text is recorded beside every verdict: round 4's catalogue was
never committed, so two of its "equivalent" acceptances could not be re-derived a round later.
Round 6 kept that on both sides, which is how its two equivalent survivors in the database area and
`F_ROLL_C` are recorded as settled rather than re-opened next round. Round 7 did the same: its two
recorded survivors in the database area were not re-opened, and the three it disputed as equivalent
(FR10, FR32, F_AUD2) were pinned in wave 6 instead of argued a second time.

Wave 7 closed round 8's on five: the test-quality survivors were assigned to the branch owning each
file instead of a sixth branch, the five merged without a conflict, and the orchestrator reconciled
the three seams the agents flagged as outside their sections (the runbook paragraph that overstated
the in-task check on a single slot, the alert description's fourth line, and the cron entry's
container) in the merge commit. Round 8's three equivalent survivors (F30, F12, F74) are recorded
with their proofs and were not pinned; F74 got a docstring line instead.

Wave 8 closed round 9's on five area branches plus a sixth, on top of the merged tree, for the
test-quality survivors. The five merged without a conflict; the orchestrator carried the count's
provenance through the stress override and the two doc amendments the domain branch could not
reach, and rewrote one branch's attribution trailers before merging. Two halves of one fix — the
e-bike bridge protection moving from the Lua transform into the variant-aware injection — were
built on different branches, each green alone, and became whole only in the merge; §7 records the
pair so nobody reinstates the clause. Round 9 also corrected one of its own reviewer's claims in the
wave that closed it: the `$$` escape in an env file was right, and `docker compose config`'s
re-escaped output had been read as the container's value.

Round 10 ran under a tightened standard — every wave-8 item verified by reversion and by executing
the fix's claim — and every wave-8 item held; what it found was beside them. Its record is in
`docs/review/round-10/`, its five open findings in the table above §4, and **no wave followed it**:
the owner asked for a hold and for a retrospective, which is `docs/review/retrospective.md`. The
next step is the owner's decision on that document's proposal: an executable acceptance checklist
in place of six simultaneous ACCEPTs, one scoped consolidation wave on the three hot spots (the
LTS side model, the extract's precedence table, the rollback's ordering and its one container),
and a first run of the stack on a host with a Docker daemon.
