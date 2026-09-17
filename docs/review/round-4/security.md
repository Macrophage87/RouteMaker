# Round 4 — Authorization / authentication / privacy — REVISE (2 blocking)

Reviewed at `66ccb03` (the wave-2 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-3 disposition of every item is in `../../../handoff.md` §3.


Round-3 items all closed, verified over HTTP: 74 mutations, 68 caught (6 survivors: 3 redundant-but-
correct guards, 1 redundant, 2 real gaps = S-7, S-8). Open redirect: 13 extra payloads all → "/", CRLF
neutralised. Audit: refused POSTs write one REFUSED row with actor, 403 unchanged. Degraded transition
walked through a bot's life (dies, 4 days → degraded, grants_standing false; returns → active).
Session: expire_date does not move; epoch bump → 404 + zero rows; 90d cookie cannot outlive it.

**B-1. TOMBSTONE_KEY never reaches a production container.** ORCHESTRATOR CONFIRMED. settings.py:153
defaults to "insecure-development-tombstone-key"; compose passes KEY_ENCRYPTION_KEY (which PLAN:283
names for this HMAC) to api and worker, and nothing in src/ reads it. With a public key anyone holding
a dump computes the tombstone of every candidate id from a member list. ban_tombstone not in
BACKUP_EXCLUDED_TABLES. Fails open and silent: the empty-key guard in tombstone() is defeated by the
non-empty default. No BanTombstone is written yet (ban/deletion have no phase-1 surface); the readers
(login refusal, is_forgotten) are live.

**B-2. Bulk delete through the admin writes no audit row.** ORCHESTRATOR CONFIRMED (no
delete_queryset on AuditedAdmin). Measured: two role mappings via delete_selected → gone, 0 app audit
rows; configuredguild/jurisdiction/override same. PLAN:247 names role-mapping changes; PLAN:56 "admin
writes go to the same audit log". The allowed half of round-3 B2; the log gives a false account.

**SHOULD-FIX.** S-1 instance-admin removal is immediate (PLAN:212: notify + configurable delay
default 1h + any admin can cancel); measured 3 POSTs → one admin left. S-2 no bootstrap path
(PLAN:212 env bootstrap id valid only while the list is empty; first action writes it and disables
the path, audited); fresh deployment → 404 at admin, only a hand UPDATE works. S-3 AuditLogEntry.actor
SET_NULL: worker action and deleted person's action identical (PLAN:283 "keep the numeric actor id,
display 'deleted user'"); round-3 N3 unaddressed. S-4 guild admin's delete_selected on a readable
table → 200 "No action selected", unaudited (PLAN:326 "refused and audited"). S-5 last-admin refusal
is a form error → 200, 0 audit rows. S-6 guild admins cannot see the instance-admin list (PLAN:212
"visible to the clubs it holds power over"). S-7 is_sanctioned lapsed-timeout comparison survives
mutation (219 passed). S-8 sweep_sessions' epoch clause and is_active clause each survive deletion
(329 passed) because every test bans via both.

**NIT.** N-1 admin logout leaves core.Session row. N-2 middleware save(update_fields) on a vanished
row → DatabaseError 500; use filter().update(). N-3 is_staff conjunct unasserted. N-4 middleware
user=user conjunct unasserted. N-5 cycle_key() redundant with login(). N-6 BorderCrossingAdmin
changelist → ProgrammingError before the first rebuild. N-7 heartbeats that never succeed → fresh 72h
window. N-8 degraded_guild_sweep not in STALE_AFTER (= database S3). N-9 no LOGGING config. N-10
AuditLogEntry has no before/after and no retention vs PLAN:247 — model docstring argues privacy;
PLAN does not record the decision. S7 private tier / instance_admin role mapping: reviewer's view
recorded (gate on visibility + break-glass; delete INSTANCE_ADMIN permission).
