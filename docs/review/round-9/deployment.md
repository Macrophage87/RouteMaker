# Round 9 — Deployability — REVISE (1 blocking)

Reviewed at `17a912b`. Every wave-7 item closed by rendering, execution or reading; F80/F85/F87/
F89/F90 could not be re-verified as labels (the proof files are not in the tree) but the assertions
are derivations. Executed: the render in both shell modes, `prepare_data_root.sh` on a fresh and a
promoted tree and a `DATA_ROOT` move, the api entrypoint in five cgroup shapes, gunicorn with PSS
(280 MiB for five workers), a real Caddy 2.8.4 in three postures, `migrate`, `collectstatic`,
`perform_backup`, a three-order restore drill, `check_operations` in four states, `run_rebuild_now`
three ways, `unwedge_job` on five paths, the cron line from a foreign directory, 192 deploy tests.

**What would change my verdict:** the `.env` quoting guidance corrected, and the two guide blocks
that source `.env` into the shell before `docker compose` stopped from doing so.

## BLOCKING
**B9-1.** Two defects composing into one outage. (a) `.env.example`'s `$` guidance was wrong in its
worked example and false about quoting. The reviewer's stronger claim — that `$$` reaches the
container verbatim — turned out to be a misreading of `docker compose config`, which re-escapes a
literal `$` as `$$` in its own output; wave 8 measured the value through the process environment
and found `$$` correct, the single-`$` example wrong (`pa`, not `paw0rd`), and "quotes become part
of the value" false (compose strips a matching pair, and single quotes suppress expansion). (b)
`docs/DEPLOYMENT.md` ran `set -a; . ./.env; set +a` and then `docker compose` in the same shell,
so every value reached compose through the shell, where `$$` is the PID and backticks execute; two
runs of the documented procedure produce two different database passwords, which is exactly the
outage the guide attributed to a rotated password. Measured here: `pa$$w0rd` → `pa19137w0rd`.

## SHOULD-FIX
SF9-1 no restore runbook (restore after `up -d`: 169 errors, exit 0; into an empty database: 0);
SF9-2 the alternative cron form still in `api`; SF9-3 no grace period on `worker`; SF9-4
`unwedge_job`'s next steps rebuild-specific; SF9-5 unqualified Docker Hub image names into a
namespace nobody here owns; SF9-6 no `/healthz`, no api healthcheck, no `/metrics`, not in §7;
SF9-7 a stale §7 row; SF9-8 posture change undocumented; SF9-9 the second instance admin
undocumented; SF9-10 a restore pages for hours; SF9-11 the monitor inside the rebuild cgroup;
SF9-12 `DISCORD_CLIENT_SECRET` missing from rotation; SF9-13 no PostGIS bump procedure; SF9-14
moving `DATA_ROOT` undocumented.

## NIT
`down` waits a minute during a build; the cron `||` pages once per `up -d`; the single-`$` case;
`worker_id` left pointing at the dead row after an unwedge.

**Wave 8:** B9-1 closed — `.env.example` rewritten from a fourteen-row measurement with single
quotes as the one rule that needs no bookkeeping, pinned by a render test; `prepare_data_root.sh
--env-file` reads the one line without evaluating the file, `collectstatic` is a bare
`docker compose run`, and a doc test refuses any line that sources `.env`. Every should-fix
closed: the restore runbook written from the drill, `stop_grace_period` on `worker`, images under
`ghcr.io/macrophage87/` with `pull_policy: build` and a test refusing unqualified names, the api
healthcheck against `/healthz` sending a real `Host`, the read-only tiles bind on `api` and `worker`
with the cron entry back in `worker`, the procedures that existed only as knowledge written down,
an access-log format without the query string or the referer (measured on the pinned gunicorn),
and HSTS at the edge (measured on a real Caddy). `/metrics`, the off-host uptime check, the
un-pushed images and the never-run-against-the-stack restore are §7 rows.
