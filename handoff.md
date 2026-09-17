# RouteMaker phase 1 — handoff

**Repository:** `github.com/Macrophage87/RouteMaker` · **Branch:** `claude/beautiful-mayer-4f7gg9`
(14 commits, all pushed) · **Suite:** 431 tests, green

**Phase 1 is not accepted.** Round 3 of independent review returned **REVISE from all five
reviewers**, with roughly fourteen distinct blocking findings. Rounds 1 and 2 also returned REVISE;
the round-2 blockers are all closed and were verified closed by the round-3 panel, by execution
rather than by reading.

Read §3 first if you only read one section.

---

## 1. How to run it

```sh
scripts/devdb.sh                                   # idempotent; Postgres stops when the container idles
PGDATABASE=routemaker_$USER .venv/bin/python -m pytest tests/ -q
```

**Use a private `PGDATABASE`.** The suite creates and drops the `live`, `staging` and `live_old`
schemas, so two concurrent runs drop each other's schemas mid-test and produce failures that read
as code defects.

**Do not set `ROUTEMAKER_LIVE_SCHEMA` / `ROUTEMAKER_STAGING_SCHEMA`**, despite what
`docs/DEVELOPMENT.md` says — see item 18.

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

**Why this matters more than it sounds.** Nothing in three rounds has ever run Valhalla. Of round
3's fourteen blockers, at least six (items 6–11) are "this could not have run at all" defects that a
single real `valhalla_build_tiles` invocation would have surfaced in minutes. The guards for exactly
these checks are already written in `src/pipeline/run.py` — `assert_lua_script_was_loaded`,
`assert_derived_tags_reached_the_tiles`, `assert_elevation_reached_the_tiles` — and have never
executed against a real build.

First three things to run once the image pulls:

```sh
# 1. Does the service start on the generated config?
docker run --rm -v "$PWD/valhalla:/conf:ro" -v "$PWD/lua:/conf/lua:ro" \
  ghcr.io/valhalla/valhalla:3.5.1 valhalla_service /conf/valhalla-standard.json 2
#    A boost::property_tree exception naming a key = the generated config is still short one.

# 2. Build tiles over a small extract with ROUTEMAKER_LUA_DIR set. Check the log for
#    "Using LUA script:" and confirm the path is OUR graph.lua, not the compiled-in one.

# 3. Read a known steep edge back and confirm weighted_grade is nonzero (it will not be — item 9).
```

### 2b. Overpass is blocked — the crossings fixture is unverified

`overpass-api.de` is denied by the same policy, which is why item 14 could not be closed here.

---

## 3. The fix list

Ordered by what I would do first. **"Mine"** marks a defect I introduced or blessed during this
session — five of the fourteen. **"Verified"** marks one I reproduced myself rather than taking on
report.

### Security-critical

| # | Finding | |
|---|---|---|
| 1 | **Open redirect in the login flow.** `auth_views.py:51` takes `?next=` into the session unvalidated; line 112 redirects to it. `GET /auth/login?next=https://evil.example.com/phish` → `302 Location: https://evil.example.com/phish`. A phishing primitive that starts on the real host and passes a genuine (often silent, `prompt=none`) Discord consent, on a deployment whose users are assembly organizers. Fix: `url_has_allowed_host_and_scheme` against `ALLOWED_HOSTS` at both `login_start` and the callback. | Mine · Verified |
| 2 | **The audit log records the inverse of its purpose.** Django calls `has_*_permission` inside `transaction.atomic()` then raises `PermissionDenied`, rolling the audit row back. Measured: 1 row outside a transaction, **0 inside**. A POST escalating a role mapping to `instance_admin` returns 403 and audits nothing; a read-only admin index GET writes 28 rows. Fix: write refusals outside the atomic block and audit the POST, not every permission probe. | Mine · Verified |
| 3 | **The authorization tables are writable behind a single unasserted override.** `cachedmembership` is *not* in `INSTANCE_ADMIN_ONLY_MODELS`, so `CachedMembershipAdmin`'s own `has_add_permission` is the only gate on the table that "grants any role in any guild" — and mutating it to `True` leaves 431 passed. Same for `ConfiguredGuildAdmin` add/delete. Both `save_model`/`delete_model` audit calls also survive deletion, so PLAN's "admin writes go to the same audit log" is asserted nowhere. | Mine |
| 4 | **The stress remap grants bicycle access on `access=no` ways Valhalla would drop.** `classify()` rates them LTS1 (it grades stress, not access), then the remap writes `cycleway=track`, from which upstream derives access. End to end: private farm track / closed service road / gated living street all go `filter=1` → `filter=0, bike_forward=true, bike_backward=true`. The graph asserts a legal claim in the *widening* direction with no override row and no review — bypassing the override table PLAN makes the sole audited path. Fix: one condition, alongside the existing `tags.cycleway` and `is_trail_class` guards. | Verified |
| 5 | **A deleted, tombstoned account's membership rows are recreated by the next gateway event.** `record_event` consults neither `BanTombstone` nor `is_deleted`, and `sweep_memberships` never removes them (the purge only touches rows with no `last_login`). Contradicts a named plan test, for someone who asked to be forgotten. `test_a_deleted_user_is_not_re_cached` carries that name and asserts a different rule. | |

### Cannot run at all

| # | Finding | |
|---|---|---|
| 6 | **The worker cannot execute a single job.** Nothing calls `django.setup()`; `procrastinate.contrib.django` is not in `INSTALLED_APPS`; there is no `procrastinate schema --apply` step anywhere. The worker dies on a missing schema function; past that every task raises `AppRegistryNotReady`. My test calls `app.tasks[...].func()` from inside pytest, where conftest has already run `django.setup()` — it asserts registration, never startability. | Mine · Verified |
| 7 | **The weekly rebuild raises on every fire.** `build_handlers` returns 11 of 13 stages; `SWAP` and `RECONCILE` have no handler and the task passes no `skip`, so `StageNotImplemented`. It does not even reach that: `validate()` raises first because no samplers are injected. `swap_schemas` has no caller outside tests — the rename is dead code in production. My test monkeypatched `run_rebuild` itself. | Mine · Verified |
| 8 | **The three variant configs are byte-identical and share one tile directory.** `build(variant)` ignores its argument (`scripts/build_valhalla_configs.py:139`); all three md5 `f37b638c…`, all `tile_dir=/data/valhalla`. `valhalla_build_tiles` has no tile-dir CLI option, so the builds overwrite each other and only the last variant survives — destroying all of layer 1. My test compares each file to `build(variant)`, i.e. identical things. Worse: the rebuild service mounts only `/tiles` and `/extracts`, so `/data/valhalla`, `/data/elevation` and `/conf/lua/graph.lua` are covered by **nothing** — tiles land on ephemeral storage and vanish. There is no dated tile directory and no promotion step. | Mine · Verified |
| 9 | **There is no elevation stage.** `pipeline/elevation.py` is imported only by its own test; `Stage` has no elevation member; nothing fetches 3DEP. Valhalla warns and continues, so no grade is ever baked: `use_hills` inert, Mass Ride's grade cap with no `max_grade`, Recovery and Mountain Goat gain invariants tying. Phase 1 lists "elevation tiles". | |
| 10 | **A pre-swap stage rewrites the LIVE crossings table.** `BorderCrossing` is a *managed* model in `public`; `INSERT_BORDER_NODES` is stage 7, `SWAP` is stage 12. So `objects.all().delete()` + `bulk_create` hits live data five stages and a multi-hour tile build before promotion, neither staged nor rolled back. A failed rebuild leaves the served graph's node ids resolving against a table describing a graph that never existed — and per item 7 no rebuild can succeed to repair it. I wrote the test that blessed this. | Mine · Verified |
| 11 | **Nothing writes the membership cache in production.** `record_event` has no caller; there is no bot source, gateway handler or ingest route. `compose.yaml` declares `BOT_INTERNAL_SECRET` and nothing reads it. Phase 1 owes "the bot with gateway-driven membership and role caching"; as shipped nobody ever holds standing. | |
| 12 | **No guild can ever be marked degraded or revoked.** `should_mark_degraded` and `degraded_window` have no callers; nothing writes `ConfiguredGuild.state`; the admin locks both fields for everyone. The grace period is a correct, well-tested predicate with no transition into the state it guards. | |

### Correctness

| # | Finding | |
|---|---|---|
| 13 | **Shoulder credit inverts the provision hierarchy.** On a 55 mph 8-lane arterial: 8 ft shoulder → **LTS3**, painted bike lane → LTS4, nothing → LTS4. A shoulder is worse provision than a painted lane and rates a tier safer, because `_bike_lane_tier` floors at LTS4 above 40 mph and the mixed-traffic path has no floor. `is_top_tier` is LTS4-only and both Beginner's "zero top-tier distance" invariant and the road-exposure report key on it — so Beginner routes onto Leesburg Pike and River Road and reports nothing. I wrote the shoulder tests using a 45 mph two-lane secondary. | Mine · Verified |
| 14 | **The crossings fixture is on its third round of the same failure.** Mechanism moved from dead way ids to unmatchable names; the data did not. "Key Bridge" ≠ OSM's `Francis Scott Key Bridge`; "14th Street Bridge (Mount Vernon Trail connection)" is a label, not a name; "Woodrow Wilson Bridge path" ≠ `Woodrow Wilson Memorial Bridge`. Only Chain Bridge matches. **And the fixture is not wired in at all** — `ReferenceData.load` reads `<DATA_ROOT>/reference/crossings.json`, which nothing populates. **And** Key and Chain are recorded roadway-*illegal* when both roadways are legal to ride, so Chain Bridge's roadway is marked trail-class on every variant and pollutes Trailmaxxing's road-exposure denominator. Needs §2b. | |
| 15 | **Three of five paths to LTS4 are untested.** `if speed_mph >= 35` → `>= 45` leaves **431 passed** — verified. 35 mph is the LTS3/LTS4 boundary and the most common arterial posting in the region. The e2e test asserts `tiers[100] >= 3`, exactly weak enough to let it through. Also surviving: 30 mph multilane → LTS3, and the high-volume bump. | Verified |
| 16 | **Session lifetimes disagree with the plan and the absolute cap is unreachable.** PLAN says "30 days idle, 90 days absolute"; `IDLE_SESSION_LIFETIME` is **14 days**. `SESSION_COOKIE_AGE` is unset, so Django's 14-day cookie expires first and neither app clock can bind. Also: nothing anywhere increments `session_epoch`, so ban and deletion do not end sessions. | Verified |

### Systemic

| # | Finding | |
|---|---|---|
| 17 | **The suite asserts rules and does not assert values.** Ten constants the plan writes down can each change by two orders of magnitude with 431 tests green — session lifetimes, `DEGRADED_WINDOW`, `MAX_ROW_AGE`, `GUILD_REMOVAL_GRACE`, `PURGE_NEVER_SIGNED_IN_AFTER`, the swap's timeout/attempts/backoff, `DEFAULT_MIN_CROSSING_M`. The mechanism is always the same: *the test computes its boundary from the constant it is testing*. This already cost item 16, and nobody could have known. A flat table of `assert CONSTANT == <plan figure>` is cheap. | |
| 18 | **My test-isolation fix is broken.** Setting the schema env vars fails 11 tests, because `test_schema_swap.py` (21 literal occurrences) and `test_pipeline_end_to_end.py` write `"live"`/`"staging"` as strings. It was also partly misdirected — a private `PGDATABASE` already isolated concurrent runs. Worse, **production has the same hardcoding**: `run.py:117` `staging_schema: str = "staging"` while `swap_schemas` reads `settings.SEGMENT_SCHEMA_STAGING`, which silently promotes an *empty* segment table; and `writers.py:39`'s `if schema == "live"` guard does not guard a renamed live schema. | Mine |

Plan-named behaviour with no implementation at all - the bot, and three
guild-lifecycle windows that depend on it - is recorded separately in §7.

Beyond these, each reviewer filed 6–12 should-fix items — conflation letting a parallel trail take a
motor-traffic count with extract order as the tie-break, `has_perm` being allow-by-default, the
backup dumping the session table, no disk gate, no region data producers at all. Full reports are
summarised in `docs/review/round-3/`.

---

## 4. The pattern worth carrying forward

Every round has found the same thing, and round 3 found it in the code written to fix round 2:

> **The tests assert the functions and not the pipeline.**

Round 2's domain reviewer named it. Round 3's test-quality reviewer measured it: 95% line coverage,
71% mutation kill rate. Coverage was never the problem; what the assertions *say* about the lines
they execute is.

Concretely, in my own work this session: I monkeypatched `run_rebuild` in the test meant to prove
the rebuild was wired (item 7). I compared a config file against the function that generates it
(item 8). I called a permission hook directly with a hand-rolled request object instead of making a
request (item 2). I asserted the replace-wholesale rule without noticing the table was live
(item 10). Each test passed, and each was testing its own reflection.

**The practice that works** — and that caught two of my own bad tests this session — is to write the
mutation *after* the test and confirm it fails. It is cheap and it is the only thing that earns a
coverage claim. Do it before committing, not in review.

---

## 5. Standing conventions

- **A phase is finished when an independent panel accepts it, not when tests pass.** Send a review
  panel after each phase and revise until acceptance. Three rounds so far; none accepted.
- **Reviewer findings carry no authority of their own.** One that contradicts an owner decision in
  `PLAN.md` is rejected on the record, not quietly. (Round 3's reviewers explicitly declined to
  contest the owner decisions and flagged the two places where a decision is *missing* — whether a
  guild admin may read a private route, and the fixture's factual content versus the rule governing
  how it may be presented.)
- **`PLAN.md` is the authority on scope.** Owner decisions include: mass rides are too large for
  bike trails; DC mass rides have legal protections subject to nuances and the UI must never present
  jurisdiction, permit or access information as a legal statement; the Mass Ride preset is tuned on
  District geometry and says so; direct device push is shelved.

---

## 6. What is genuinely solid

Recorded so it is not re-litigated. All verified by the round-3 panel by execution, most by
reverting the fix and confirming a test catches it:

- The vendored Valhalla files are byte-identical to upstream 3.5.1 (md5-checked), the Lua wrapper
  runs end to end under LuaJIT, and the design claims about `barrier=border_control`,
  `country_crossing_cost`, `gate_cost`, `tagged_access` and HGT banding all check out against the
  pinned C++ source, cited by file and line.
- `search_path` ordering and the data-loss fix, verified against a live database in both directions.
- The swap's ACCESS EXCLUSIVE lock and `lock_timeout`, killed by real contention from a second
  backend rather than by source-reading.
- Cross-guild admin isolation, confirmed by request: a guild admin of club A sees none of club B's
  rows on any index, changelist, change form or filter, and every cross-guild POST returns 403.
- Conflation's point-to-line distance and span claiming; border-node insertion; the urban/rural
  speed split; boundary-street handling; lanes normalised per direction before the Furth tables;
  reference-route measurements reproducing the README tables exactly.
- 51 of 57 targeted auth mutations and 123 of 173 total mutations killed.

---

## 7. Known phase-1 gaps

Recorded rather than left for a round-4 reviewer to discover. None of these is a
defect in shipped code: each is a plan-named behaviour with no implementation
anywhere, and the last three cannot be built before the first is.

| Gap | Where the plan says it | State |
|---|---|---|
| **No bot** (item 11, restated). `record_event` has a caller now but no *producer*: there is no bot source, no gateway handler and no ingest route, so nothing writes the membership cache in production and nobody ever holds standing. Nothing writes the gateway heartbeat either - the `ScheduledRun(task="gateway_heartbeat")` row `core.revocation.last_gateway_event` reads. | PLAN.md:270 ("The bot"), :274 ("Re-validation") | Not built. Phase 1 owes it. |
| Guild **re-invite token's 24-hour expiry** - "wrapped in a single-use token expiring in 24 hours". | PLAN.md:272 | No token, no expiry, no code anywhere. |
| **Unmapped-guild alert, default 30 days** - "A guild left unmapped beyond a configurable period, default 30 days, alerts instance admins and offers bulk reassignment or archival". | PLAN.md:272 | No setting, no alert. |
| **Remap-reversal window of 7 days** - "an instance admin can reverse a remap within 7 days, restoring the prior ids and mapping but never cached standing". | PLAN.md:272 | No remap action, so no reversal window. |

The three durations belong to guild-lifecycle features (re-invite link, guild
remap, unmapped-guild alerting) that all presuppose a live bot: the re-invite
link is an OAuth install URL for it, the remap's precondition is that it is
already present in the new guild with its backfill complete, and "unmapped"
is a state only the backfill can leave. So they are not three missing constants
that could be added to `test_plan_constants.py`; they are three windows on
features that do not exist. They are deliberately **not** implemented here.

One consequence is already wired for, and is the reason it is worth writing
down. `core.revocation.mark_degraded_guilds` fails closed when no heartbeat has
ever been recorded - correct for a bot that goes silent, and on this deployment
it would mark every guild degraded on the first tick and lapse the whole
deployment's standing 72 hours later. Its scheduler
(`config.procrastinate.degraded_guild_sweep`) therefore holds the mark until one
heartbeat row exists, and arms itself the moment the bot writes one. Anything
else built against the heartbeat needs the same reading.
