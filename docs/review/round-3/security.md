### Authorization, authentication and privacy — REVISE (5 blocking)

All six round-1/2 items verified genuinely fixed, by execution: the visibility tier gate bites
(3 mutations caught), the admin returns 200 over real HTTP to both admin classes, `has_perm` reads
the permission string, `search_path` resolves all app tables to `public` against a live database,
and 51 of 57 targeted mutations were caught (2 of the 5 survivors were the reviewer's own no-ops).
Cross-guild isolation confirmed by request: a guild admin of club A sees none of club B's rows on
any index, changelist, change form or `?q=`/filter, and every cross-guild POST returns 403 with the
row unchanged. The reading halves are solid; the writing halves are what is missing.

**B1. Open redirect in the Discord login flow.** CONFIRMED BY ME — MINE, this session:

    GET /auth/login?next=https://evil.example.com/phish  -> complete callback
    callback status=302  Location='https://evil.example.com/phish'

`auth_views.py:51` takes `request.GET["next"]` into the session and line 112 redirects to it with no
host or scheme validation. A credential-phishing primitive on a deployment whose users are
mass-ride and assembly organizers: the link starts on the real host, passes a genuine Discord
consent (often silent, `prompt=none`), and lands anywhere. Fix:
`url_has_allowed_host_and_scheme` against ALLOWED_HOSTS at both `login_start` and the callback,
falling back to `/`.

**B2. Every refused admin write is audited into a transaction that is then rolled back.**
CONFIRMED BY ME — MINE, this session:

    outside a transaction:                      1 row
    inside Django's atomic + PermissionDenied:  0 rows

Django calls `has_*_permission` inside `transaction.atomic()` in `changeform_view`/`delete_view`
and then raises `PermissionDenied`, which rolls the audit row back with it. Reviewer's HTTP table:
a read-only admin index GET writes 28 rows; a POST escalating a role mapping to `instance_admin`
returns 403 and writes 0. So the plan's "refused and audited" is met on the refusal and never on
the audit, while navigation floods the log at ~20 rows per page view. My test called
`has_change_permission` directly with a hand-rolled Request, so it could not see it. Fix: write
refusals outside the atomic block, and audit the POST rather than every permission probe — the
hooks fire during rendering and are not a proxy for intent.

**B3. A deleted, tombstoned account's membership rows are recreated by the next gateway event.**
`record_event` consults neither `BanTombstone` nor `User.is_deleted`. Executed: delete the account,
feed one gateway event, the row is back — and `sweep_memberships` never removes it, because the
purge only touches rows with no `last_login` and a deleted account keeps its own. Contradicts a
named plan test ("A deleted user still present in a guild is not re-cached") and the deletion
paragraph. `tests/test_auth_wiring.py:200` carries that test's name but asserts a different rule
(that `attach_standing` grants a deleted user nothing). Squarely in the data the plan identifies as
sensitive, for someone who asked to be forgotten.

**B4. No guild can ever be marked degraded or revoked.** `should_mark_degraded` and
`degraded_window` have no callers; nothing writes `ConfiguredGuild.state` or
`standing_valid_until`; `ConfiguredGuildAdmin.readonly_fields` locks both for everyone including
instance admins, with no admin actions. So the degraded-guild grace period — a phase 1 deliverable
— is a correct, well-tested predicate with no transition into the state it guards, and the plan's
"audited revoke-now action" exists on no surface.

**B5. Nothing writes the membership cache in production.** `record_event` has no caller anywhere in
`src/`; there is no bot source, gateway handler or ingest route. `compose.yaml` declares
`BOT_INTERNAL_SECRET` and nothing reads it. Phase 1 owes "the bot with gateway-driven membership
and role caching"; as shipped the cache stays empty and nobody holds standing at all.

**SHOULD-FIX:** S1 `has_perm` is allow-by-default keyed on three action prefixes — a guild admin
holds `core.approve_override`, `core.remap_configuredguild`, `auth.add_permission`,
`admin.delete_logentry` and `has_module_perms('admin')`. Not exploitable today (every ModelAdmin
overrides its hooks) but phase 1's job is "the pattern every later admin surface follows", and
phase 4 brings exactly those custom actions. Deleting `"rolemapping"` or `"auditlogentry"` from
INSTANCE_ADMIN_ONLY_MODELS leaves 431 passed — the test loop covers five of seven entries.
`has_module_perms` returns True for every app label. S2 a role mapped to `instance_admin` grants
nothing (`attach_standing` interprets only REVIEWER and GUILD_ADMIN), and no `User` admin is
registered, so a fresh deployment has exactly one instance admin forever — the situation
`check_last_instance_admin` exists to prevent. S3 ban and deletion do not end sessions: nothing
increments `session_epoch` anywhere. S4 idle lifetime is 14 days not the plan's 30, and
`SESSION_COOKIE_AGE` (14 days, never refreshed) binds before either app clock, so the 90-day
absolute cap is unreachable; orphaned `core.Session` rows are never cleaned up. S5 losing guild
membership drops a user below guest standing for 72 hours — `is_sanctioned` treats any `removed_at`
as an active sanction, so voluntary departure from club A costs guest commenting on club C, against
the plan's explicit rule. S6 `can_review` denies review to a guild reviewer who is also a named
collaborator (COLLABORATOR 40 outranks REVIEWER 30). S7 guild admin and instance admin outrank the
PRIVATE tier — plausibly intended, but needs an owner decision in PLAN.md and a test either way.
S8 deleting `CsrfViewMiddleware` leaves 431 passed.

**NIT:** N1 the admin path is confirmable by a 302 despite a docstring claiming 404. N2
`check_last_instance_admin` lives in `save()`, so `.update()` and `.delete()` bypass it. N3
`AuditLogEntry.actor` is SET_NULL against the plan's "keep the numeric id". N4 no `Closure` model
though phase 1 names closure editing. N5 no LOGGING config at all.
