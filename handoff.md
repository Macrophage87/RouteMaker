# RouteMaker phase 1 — handoff

**Repository:** `github.com/Macrophage87/RouteMaker` · **Branch:** `phase1/wave3-merge`
(151 commits, local — not pushed) · **Suite:** 1590 tests, green

**Phase 1 is not accepted.** It has been through four rounds of independent review. Rounds 1, 2, 3
and 4 all returned REVISE; round 4 returned REVISE from all five reviewers, with ten blocking
findings across the five areas. Every round-3 and every round-4 finding is closed on this tree,
each fix carrying a mutation confirmed to fail, and the round-4 panel verified every round-3 finding
closed by reverting the fix rather than by reading. **A round-5 panel has not run.** Nothing here has
been accepted by anyone; the next step is that panel.

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

**Why this matters more than it sounds.** Nothing in four rounds has ever run Valhalla. Round 3's
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

---

## 3. The fix list

Rows 1–18 are round 3's findings, with how each closed. Rows 19–27 are round 4's, found on the tree
that closed rows 1–18. **"Mine"** marks a defect I introduced or blessed. **"Verified"** marks one
reproduced by the orchestrator rather than taken on report.

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

**The practice that works** is to write the mutation *after* the test and confirm it fails. Do it
before committing, not in review.

---

## 5. Standing conventions

- **A phase is finished when an independent panel accepts it, not when tests pass.** Send a review
  panel after each phase and revise until acceptance. Four rounds so far; none accepted.
- **An agent's fix reaches the merged tree only after the orchestrator has re-run at least one of
  its claimed mutations.** Wave 3 merged five branches on that rule, one blocker mutation per
  branch reproduced by hand before the merge.
- **Reviewer findings carry no authority of their own.** One that contradicts an owner decision in
  `PLAN.md` is rejected on the record, not quietly. (Rounds 3 and 4 both declined to contest the
  owner decisions and flagged the places where a decision is *missing* — whether a guild admin may
  read a private route, the `instance_admin` role mapping, audit before/after, and the fixture's
  factual content versus the rule governing how it may be presented.)
- **`PLAN.md` is the authority on scope.** Owner decisions include: mass rides are too large for
  bike trails; DC mass rides have legal protections subject to nuances and the UI must never present
  jurisdiction, permit or access information as a legal statement; the Mass Ride preset is tuned on
  District geometry and says so; direct device push is shelved.

---

## 6. What is genuinely solid

Recorded so it is not re-litigated. Everything here was verified by the round-4 panel by execution,
most of it by reverting the fix and confirming a named test fails:

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
- Mutation kill rate **71% → 85.6%** (187 mutants, 160 killed) with coverage at 96%, and 46 of the
  54 reconstructed round-3 survivors killed. Wave 3 added 104 further mutations across the five
  branches and the wiring commit, each one confirmed to fail before its fix was accepted.

**The caveat that has not changed in four rounds: none of this has run against a real Valhalla
binary or a real OSM extract.** Every tile-pipeline claim above is a claim about our code and about
upstream's source, not about a graph that exists. See §2.

---

## 7. Known phase-1 gaps

Recorded rather than left for a round-5 reviewer to discover. None of these is a defect in shipped
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
| **`resolve_sidepath_bridge_ids` has no trail-class guard** - the sibling of item 24, noted by the domain agent while fixing it. Harmless today: a path in the sidepath set is dropped from the no-trail variant anyway. | - | Left as is, deliberately. Revisit if the sidepath set gains another consumer. |
| **The bootstrap claim is check-then-update, not `select_for_update`** - two simultaneous first requests from the bootstrap id could both pass the empty-list check. | PLAN.md:212 | Accepted: the write is idempotent (same id, same flag), so the race writes the same row twice. |
| **The crossings fixture's OSM names are unverified** - every row carries `osm_names_verified: false`; Overpass is blocked here (§2b). The content is now pinned by an independent table (item 26), which pins what we *believe*, not what OSM *says*. | PLAN.md:68 | Needs one Overpass query per structure from a machine that can reach it. |
| **`routemaker/cards.py`** has no production caller (phase-4 surface). | - | Recorded; not ranked. |

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

## 8. Round-4 record

The five round-4 reports are in `docs/review/round-4/`, one per reviewer, with the README carrying
the verdict table and the kill-rate numbers. Each report states which round-3 findings its reviewer
re-verified closed and how, and its own findings are numbered as the reports number them — the
mapping to §3's rows 19–27 is by the parenthetical labels there (database B1, routing B1/B2, domain
B1–B4, security B-1/B-2, the test-quality cluster).

Wave 3 closed all of them on five disjoint branches, merged into `phase1/wave3-merge`. What each
agent changed is summarised per finding in §3; what was deliberately left unbuilt is in §7.

**The next step is the round-5 panel**, on this tree.
