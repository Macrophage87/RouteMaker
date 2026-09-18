# Phase-1 acceptance checklist

The checklist that ends phase 1, as a program: `scripts/acceptance.py`. It replaces "six reviewers
report zero blockers in the same round" with six things a deployment either does or does not do,
each answered PASS, FAIL or SKIP with the evidence beside it, on a real host with a Docker daemon.
`docs/review/retrospective.md` §5 is the argument for it.

```sh
python3 scripts/acceptance.py --dry-run        # print what each item would run, touch nothing
python3 scripts/acceptance.py                  # the whole checklist; A3 pauses for the browser steps
python3 scripts/acceptance.py --only A4 A5     # a subset
python3 scripts/acceptance.py --resume acceptance-reports/<earlier>.json   # skip what already passed
python3 scripts/acceptance.py --second-rebuild --confirm-rollback          # A6 in full
```

It runs from the repository checkout on the deploy host, beside a filled-in `.env`, with Docker
and Python 3 and nothing else: it is standard library only and asks every question about the
running stack through `docker compose exec`, the way the runbooks do. It stops at the first FAIL,
because every later item depends on the earlier ones. It writes a JSON and a Markdown report to
`acceptance-reports/` (ignored by git); the Markdown is what goes in the record.

## The items

| Item | What it does | PASS means |
|---|---|---|
| **A1** Preflight | Checks Docker and Compose, that `.env` exists and renders, that no secret is still a placeholder, that `DATA_ROOT` is absolute and holds every directory `scripts/prepare_data_root.sh` creates, and that the volume has at least the disk gate's floor free. | The host can run the stack. |
| **A2** Build and start | `docker compose build`, then `up -d`, then waits up to ten minutes for `postgis` healthy, `migrate` exited 0, `api` healthy, `worker` and `rebuild` running. Reports the routers' state without judging it — they cannot serve before the first rebuild. | The images build and the stack settles in order. |
| **A3** Edge, sign-in, admin | Through the edge: `/healthz` answers 200 (with `Strict-Transport-Security` on the hostname posture), `/auth/login` redirects to Discord carrying the configured `DISCORD_REDIRECT_URI`, and the admin path is 404 to a stranger. Then **four steps by hand in a browser** (printed by the script): sign in as the bootstrap account and take a first admin action; configure two guilds and make a second account a guild admin of one; as that guild admin, edit your own guild; as that guild admin, try to change the other guild. The script then reads the audit log: the bootstrap path is claimed, an instance admin exists, an own-guild change by a guild admin is audited as allowed, and a cross-guild write is audited as refused. `--skip-manual` runs only the automated half. | A person can sign in and the plan's two admin rules hold on the real stack. |
| **A4** First rebuild | `run_rebuild_now` in the `rebuild` container, then polls the run row every minute up to eight hours (`--rebuild-timeout`). Requires the run to have succeeded, `tiles/<variant>/current` to point at a build carrying `tiles.tar` on all three variants, restarts the three routers, sends a canary bicycle route (Lincoln Memorial to Union Station) to each router from inside the network, and runs `check_operations`. | A weekly rebuild completes against the real Valhalla and each variant serves routes. |
| **A5** Backup and restore | `perform_backup()` in `worker`, `pg_restore --list` on the archive (table data present, the excluded tables' rows absent), then the restore runbook's core step against a scratch database beside the live one: `createdb`, `pg_restore --no-owner`, count `django_migrations` and `live.segment`, `dropdb`. Zero errors required. Nothing live is touched. | The nightly dump is real and restores cleanly into an empty database. |
| **A6** Rollback | Needs two promoted builds, so it is SKIP unless `--second-rebuild` (another full A4). Then `rollback_rebuild` must rehearse a target for all three variants; with `--confirm-rollback` it runs, the routers restart, `current` must match the rehearsed targets, and the canary must answer again. The deployment is left on the older build. | The rollback the runbook documents works on the real stack. |

## What it does not do, and where that is recorded

- **It does not run the reference routes through the routers.** PLAN.md:290's "reference-route
  tests against them" has no runner in the repository; the canary route per variant stands in, and
  the rebuild's own VALIDATE stage (the transform loaded, no rule violations, the admin and timezone
  databases, elevation and a derived tag read back from the tiles) is the rest of the evidence. The
  runner is a `handoff.md` §7 row.
- **It does not sign in for you.** Discord's OAuth needs a browser and a real account; A3 tells you
  the four steps and checks their footprints afterwards.
- **A6 leaves the deployment rolled back** by design. Run A4 once more to roll forward, or leave it
  and let Tuesday's rebuild promote the next build.

## Recording a run

Commit the Markdown report under `docs/review/acceptance/` with the commit it ran against, and put
one line in `handoff.md`'s header: the date, the commit, the outcome, and which items were skipped.
A FAIL is the next wave's only list. Under the retrospective's rule, phase 1 is accepted when a run
passes A1 to A5 with A6 at least rehearsed, and the last review panel over the diff since the
previous panel finds no regression.
