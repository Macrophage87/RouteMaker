# Round 8 — Deployability — REVISE (1 blocking)

Reviewed at `60436a6`. Every round-7 item closed, by rendering, execution or reading with the check
recorded: Photon behind the `unbuilt` profile with the 2.x mount and `INITIAL_DOWNLOAD` off; the
TCP healthcheck; the narrowed rebuild binds and the per-directory chown (executed, all three
refusals); S-1 to S-8 and N-1 to N-6 each at the line. Executed on this host: the render from
`.env.example`, `prepare_data_root.sh`, `migrate` from empty, `check_operations` fresh / wedged /
failed, `run_rebuild_now` three ways, `weekly_rebuild.func` driven to a real stage failure with the
stderr tail read out of the run row, `perform_backup` and `prune_backups`, `rollback_rebuild`
refusal / dry run / `--confirm` / second refusal against real symlinks and a retired schema, a real
Caddy 2.8.4 serving the collected assets, gunicorn under the rendered `api` environment with PSS
measured. 242 deploy-surface tests pass.

**What would change my verdict:** a written way out of a `doing` `weekly_rebuild` row whose worker
is gone.

## BLOCKING
**B-1.** `rebuild` has no `stop_grace_period`, so any `down`, `up -d`, `restart`, reboot or OOM
during a six-hour build SIGKILLs the worker. Procrastinate 3.9.0 prunes stalled *worker* rows only;
`get_stalled_jobs` has no caller; the row stays `doing` for ever. `run_rebuild_now` then refuses for
ever (executed), the Tuesday task refuses for ever and lands `failed` (executed), and every surface
stops at the diagnosis. The remedy — `procrastinate shell` → `retry <id>` — is one line and appears
nowhere.

## SHOULD-FIX
- **SF-1.** The documented cron line has no `cd` into the compose project and fails on every tick
  (executed), while the deployment guide blesses it.
- **SF-2.** Rotating `PGPASSWORD` on an initialised PGDATA: `pg_isready` green under the wrong
  password (executed), `migrate` fails auth, three services never start; procedure recorded nowhere.
- **SF-3.** No log rotation anywhere.
- **SF-4.** PLAN:65's backwards-compatible-migration rule appears only in PLAN; a `TAG` rollback
  says nothing about the applied schema or re-running `collectstatic`.
- **SF-5.** `WEB_CONCURRENCY` derived from the host's cores: 17 gunicorn workers in a 2 GB cgroup
  (~54 MiB PSS each, measured).
- **SF-6.** `KEY_ENCRYPTION_KEY` rotation described as "a re-tombstoning job"; tombstones store only
  the HMAC, so rotation silently re-admits every banned account.
- **SF-7.** Nothing alerts on free space before the disk gate refuses.
- **SF-8.** A stack down more than ten minutes across Tuesday 08:00 UTC silently drops the week.

## NIT
N-1 the nightly prunes run after the dump; N-2 the rollback dry run omits the restart hint; N-3
`up -d` during a rebuild is undocumented as a kill.

Reasoning only: symlink bind re-resolution on restart; `rmdir` of a held bind source; recreate
ordering on a `TAG` bump. Cannot verify here: build, `up`, healthcheck timing.

**Wave 7:** B-1 closed on two branches — `manage.py unwedge_job` (refuses unless `doing`, refuses
while the worker still beats, refuses behind a queued lock holder, audits) named on both alert
surfaces and in both guides, with `stop_grace_period: 60s` on `rebuild`. Reading `worker.py`
established that Procrastinate's graceful stop waits unboundedly on a running synchronous job, so a
stop mid-build still ends at SIGKILL and `unwedge_job` is the repair; the residual is a §7 row.
SF-1 to SF-8 and the nits all closed; the free-space check moved the cron entry to the `rebuild`
container, the one that mounts the tiles. F80, F85, F89/F90 and F87 pinned.
