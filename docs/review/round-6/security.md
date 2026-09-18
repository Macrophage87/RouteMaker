# Round 6 — Access control / sign-in / privacy — REVISE (1 blocking)

Reviewed at `00ee400` (the wave-4 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-5 disposition of every item is in `../../../handoff.md` §3.


All round-5 items closed by reversion (12 + 2 extras, each with the exact edit and failing test).
Full permission matrix re-derived over HTTP as a guild admin (7 changelists 200, 6 at 403, index
advertises exactly the seven); nine guild-admin write attempts all 403 with one refused audit row
and nothing changed; autocomplete and legacy admin URLs probed as leak vectors (403/404). Fifteen
further mutations: 13 killed by name, 1 = SF-1, 1 equivalent (_may_read → is_staff). All wave-4
design choices weighed and upheld (anchor + secret scoping; allow-list nothing wrongly exempted;
listing tight under 11 query shapes; BootstrapClaim race-safe; 5-min sweep outside the gate;
Caddyfile coherent with SECURE_PROXY_SSL_HEADER — header_up replaces; uid 10001 layout).

**B-1. `GET <admin>/logout/` signs the person out cross-site.** ORCHESTRATOR CONFIRMED (code
order): the override deletes the core.Session row BEFORE delegating to Django 5's POST-only
LogoutView, so the 405 arrives after the row is gone; csrf_protect does not cover GET. Executed:
GET → 405, rows 1 → 0, index 404 after; same with a foreign Referer and no token. An <img src> on
any page signs an admin out; ADMIN_PATH default is in the repo; no audit row. The POST-only rule
is stated in tests/test_auth_views.py:268 for the site's own logout. Fix (verified): call super
first, delete only when request.method == "POST".

**SHOULD-FIX.** SF-1 GuildScopedAdmin's `_admin_guild_ids` → `_member_guild_ids` survives 2590:
"member but not admin" is never constructed (other_guild is a guild the actor has nothing in);
under the mutation a member of A who administers B reads A's roster. SF-2 ENVIRONMENT_LOOKUP
requires a literal `(`: misses os.environ["X"], os.getenv("X"), environ.get — row 28's guarantee
is false (executed: two undeclared reads, 74 passed). SF-3 no Closure model/admin though PLAN:299
lists "closure editing" in phase 1 (PLAN contradicts itself two clauses later; closures are an
issue category, PLAN:227, phase 4) — §7 row owed saying which reading was taken. SF-4 the admin
logout test covers POST only.

**NIT.** N-1 standing.py:248-253 comment says instance admin is "a mapped Discord role like any
other" — the opposite of the behaviour and PLAN:212; instance_admin_guild_ids assigned by nothing.
N-2 api.Dockerfile stale STATIC_ROOT comment (= deployment; fixed in wave 5). N-3
test_deploy_surface pins the header_up NAME only; `X-Forwarded-Proto https` literal survives.
N-4 :80 default with Secure cookies (= deployment B-5; fixed in wave 5).
