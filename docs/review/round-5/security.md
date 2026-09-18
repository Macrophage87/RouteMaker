# Round 5 — Access control / sign-in / privacy — REVISE (1 blocking)

Reviewed at `9601c34` (the wave-3 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-4 disposition of every item is in `../../../handoff.md` §3.


All round-4 items closed by reversion (33 mutations; each killed with a named test) except: the
ban_tombstone-in-dump decision is pinned by nothing (adding it to BACKUP_EXCLUDED_TABLES → 41
passed); two S-6 guards are redundant-but-correct (allow-list entry, _may_read). Records honest.

**B1. compose.yaml delivers none of the settings the sign-in path reads.** ORCHESTRATOR CONFIRMED:
api gets DJANGO_SETTINGS_MODULE, DJANGO_SECRET_KEY, DISCORD_CLIENT_SECRET, KEY_ENCRYPTION_KEY,
BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID, PGPASSWORD; settings.py reads 24 names incl. DISCORD_CLIENT_ID,
DISCORD_REDIRECT_URI, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS, DJANGO_ADMIN_PATH, PGHOST,
PGUSER, PGDATABASE, VALHALLA_*_URL; no env_file. Under the declared env: ALLOWED_HOSTS=['localhost'],
client_id='', redirect localhost:8000 → DisallowedHost 400 behind Caddy and an authorize URL Discord
refuses. PLAN:299 phase 1 "Discord login with the identify scope"; not in §7. Round-4 B-1 inverted.
test_compose pins only KEY_ENCRYPTION_KEY; no test needs a real client id.

**SHOULD-FIX.** S1 InstanceAdminListing: lookup_allowed permits any local field, so a guild admin
reads is_banned/is_deleted/session_epoch/last_login of instance admins via ?field=… filters
(executed: 200 with rows disappearing); and the queryset lists banned/deleted holders as current.
S2 ban_tombstone-in-dump unpinned. S3 the removal target can cancel their own removal (executed;
plan's literal words allow it) — the delay is unenforceable; re-scheduling only moves later; cancel
audited; guard against self-cancel → 99 passed. OWNER DECISION. S4 effective delay is 1–7 h: the
only applier is membership_sweep on "0 */6 * * *". S5 bootstrap re-arms if the list empties
(.update() path) vs PLAN:212 "permanently disables"; claim counts banned/deleted admins while
check_last_instance_admin excludes them.

**NIT.** N1 allow-list entry and _may_read redundant; docstring claims otherwise. N2 LOGGING omits
`config` so config.procrastinate's INFO line ("degraded mark is held") never reaches the log.
N3 nothing logs a Discord id/session key/token at INFO — confirmed. N4 nothing pins that
test_settings overrides only the key (T1/T2 relaxations are caught; T3 not run on the whole suite).
N5 handoff does not say N-5/N-7 were declined. N6 permission matrix confirmed (guild admin 403 on
valhallaupstream/driftreport/scheduledrun/user/auditlogentry/pendinginstanceadminremoval; member 404).
