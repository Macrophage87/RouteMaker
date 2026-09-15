### Database and rebuild pipeline — REVISE (3 blocking)

Reviewer re-verified every round-1/2 fix in this area by reverting it and confirming a test
catches it — search_path ordering, the no-default ReferenceData, conflation's distance measure
and span claiming, the swap's LOCK TABLE and SET LOCAL (three mutations, three catches), and the
override stage. All genuinely fixed and genuinely guarded. Also clean: `makemigrations --check`
reports no drift, no migration is schema-qualified, GiST indexes present, no FK into the swapped
schema. 431 passed on a private database, twice.

**B1. The Procrastinate worker cannot execute any job.** CONFIRMED BY ME (structurally):
`src/config/procrastinate.py` never calls `django.setup()`; `procrastinate.contrib.django` is not
in `INSTALLED_APPS`; there is no `procrastinate schema --apply` step anywhere in the repo — not in
compose, not in a manage.py command, not in a migration, and there is no Dockerfile. Reviewer ran
it as compose does:

    $ procrastinate --app=config.procrastinate.app worker
    function procrastinate_prune_stalled_workers_v1(double precision) does not exist

and after applying the schema by hand:

    Starting job weekly_rebuild[2](timestamp=0)
    django.core.exceptions.AppRegistryNotReady: Apps aren't loaded yet.

All three periodic tasks die this way. `tests/test_worker_schedule.py` cannot see it because it
calls `app.tasks[...].func(...)` from inside pytest, where conftest has already run
`django.setup()`. Registration is asserted; startability is not. Round 2 said "no task was
registered"; this is the same defect one layer down — the task exists and nothing can run it.

**B2. The weekly rebuild can never complete.** Same as the routing reviewer's B3, independently
reproduced. Additional consequences this reviewer traced: `swap_schemas`/`rollback_swap` have no
caller outside tests — the rename is dead code in production; the swap's *first half* does not
exist at all (PLAN requires repointing the Valhalla upstreams through "a settings table the API
watches" before the rename — there is no such table among the twelve models, and swap.py's
docstring says "Callers repoint the upstreams before calling this" when there is no caller);
`RebuildReport.succeeded` requires RECONCILE and so can never be true in production.

**B3. A pre-swap stage rewrites the LIVE crossings table.** CONFIRMED BY ME.
`BorderCrossing` is a *managed* model in `public` — the live application schema, not the schema
the swap promotes. `INSERT_BORDER_NODES` is stage 7 of 13; SWAP is stage 12. So
`write_border_crossings` does `objects.all().delete()` + `bulk_create` against live data five
stages and one multi-hour tile build before the swap, and it is neither staged nor rolled back.
Reviewer's reproduction of a rebuild failing at VALIDATE:

    BEFORE: {(-4242, 100)}     <- the currently-served graph
    AFTER : {(1099511627776, 100)}

borders.py's own docstring is what makes it serious: "the ids are not persistent identity: the
crossings table records what each one means, and a rebuild reassigns them." After a failed
rebuild the live tiles' node ids resolve against a table describing a graph that was never
served — and per B2 no rebuild can succeed to repair it. It also breaks rebuild.py's stated
invariant that pre-swap stages leave the live system untouched.

**MY FAULT SPECIFICALLY:** I wrote `test_border_crossings_are_replaced_wholesale` this session and
asserted the destructive behaviour as correct, without noticing the table is live and pre-swap.
`test_validation_failure_leaves_live_untouched` checks `live.segment` only, which is why nothing
caught it.

**SHOULD-FIX:** S4 production code hardcodes `staging`/`live` against the env-configurable
settings — with the documented env vars set, the rebuild writes 5 rows and the swap promotes 0, a
silent empty promotion rather than an error. S5 the DEVELOPMENT.md concurrency recipe does not work
(11 failed) — and it is worse than test literals, because production has the same hardcoding.
S6 the nightly backup dumps the session table (verified by `pg_restore --list`: `TABLE DATA public
app_session` present), and does none of the S3 upload with SSE-KMS, 30-day retention, or
`pg_restore --list` verification the plan specifies. S7 `REBUILD_TIMEOUT_S`/`SWEEP_TIMEOUT_S` are
never enforced — three references in the repo: two definitions and a test comparing one constant
to another. S8 no elevation stage (same as routing B4). S9 no disk gate and no measured size
table, both assigned to phase 1 by name; `docs/` has one file and no data-source document.

**NIT:** N10 `route_crossings` casts both sides to `geography` in ST_DWithin, making the GiST
index unusable (sequential scan per vertex; unverified at scale — but `assign_way` measured at
0.67 ms/way is fine). N11 `write_segments` materialises every row before writing and leaves it on
the context. N12 `tag_jurisdictions` tags a way with every authority regardless of fraction, so a
way clipping a park by a metre is tagged with that park — `assign_way`'s docstring says "the
caller decides"; the caller does not decide.
