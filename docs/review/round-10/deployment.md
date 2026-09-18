# Round 10 — Deployability — REVISE (1 blocking)

Reviewed at `0d79759`. All fifteen wave-8 items closed by rendering, execution or reading; the
`$` guidance re-measured through `docker compose config --environment` (which prints the
interpolation environment without the YAML re-escaping) and through the process environment as a
control: every row of `.env.example`'s six-row table is right, and round 9's correction stands.
Executed: the render, `prepare_data_root.sh --env-file`, `migrate` from empty, the pinned gunicorn
under the rendered environment with the healthcheck's exact command in two `ALLOWED_HOSTS` shapes,
`collectstatic` with the tiles bind read-only, a real Caddy 2.8.4 with HSTS on both handlers, a
two-order restore drill with exit codes measured, `check_operations` in three states,
`run_rebuild_now` after a simulated restore, `rollback_rebuild` dry run, the entrypoint's cgroup
branch in seven shapes, 204 deployment tests.

**What would change my verdict:** `pull_policy: never` on the four built services, or the
rollback documented as `up -d --no-build` with the compose header, the guide and §7 corrected.

## BLOCKING
**B10-1.** `pull_policy: build` is unconditional in the installed Compose (v5.1.1): a present local
image is skipped only when the policy is not `build`, `up` builds on every run, and `--no-build` is
the opt-out ("Don't build an image, even if it's policy", from the CLI's own help). So
`TAG=<previous> && docker compose up -d` builds the current working tree, tags it with the previous
release's tag, and orphans the real previous image, which the next prune removes. The operator
believes they have rolled back; the containers run the code they were rolling back from. Every
`up -d` in the guides (the restore's step 4, the posture change, the rotation, the volume move) and
`docker compose run … collectstatic` now build first. Three places state the fallback reading —
the compose header, the deployment guide's rollback section, and §7's row — so §7 records a milder
and opposite limitation. A wave-8 change whose semantics were read one way and are the other.
Verified by reading the exact installed version's source plus its help text; no daemon.

## SHOULD-FIX
- **SF10-1.** The rollback section of the operations guide still says `api` mounts nothing and
  `worker` mounts only backups, contradicting two other sections; and `tests/test_deploy_docs.py`
  pins the stale sentence, so correcting the guide fails the suite.
- **SF10-2.** The deployment guide describes flags `rollback_rebuild` no longer has and bolds the
  no-mount claim 22 lines above the table listing both mounts.
- **SF10-3.** The restore runbook claims 169 errors and exit 0 after `up -d`; measured on the same
  PostgreSQL major: 169 errors and exit 1. The procedure is right, its justification is not.
- **SF10-4.** A dump taken during a `doing` rebuild restores the job row, and the runbook's next
  instruction, `run_rebuild_now`, is then refused; nothing connects the two to `unwedge_job`.
- **SF10-5.** The api healthcheck is red for ever under `DJANGO_ALLOWED_HOSTS=*` (nothing gates on it).

## NIT
Reading a password back with `config` and decoding `$$` by hand, where `config --environment`
needs no decoding; the quickstart block lacks the `collectstatic` line; `collectstatic` is 139
files now, unasserted.

Executed / read / reasoning / cannot-verify: as itemised above; the build itself, `up`, and the
pull-policy behaviour under a daemon remain unverifiable here and are §7 rows.
