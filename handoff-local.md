# RouteMaker — handoff to the local implementer (Windows, Docker)

**For:** whoever picks this up next on a Windows machine with Docker, working with Claude Code.
**Branch:** `claude/beautiful-mayer-4f7gg9` · **Suite:** 3309 tests, green · **Written:** 2026-09-24.

This is the short handoff. `handoff.md` is the full record of ten review rounds and stays as the
reference (its §7 is the list of known gaps, 49 rows); read this one first and that one when a task
points at it.

---

## 1. Where things stand

- **Phase 1 is built and not accepted.** Every plan-named phase-1 component exists: the rebuild
  pipeline (extract, elevation, LTS classifier, conflation, jurisdiction, border nodes, the Lua tag
  transform, three Valhalla variants, validation, the schema swap, promotion and rollback), the
  Procrastinate worker and its schedule, the admin with guild scoping and the audit log, Discord
  sign-in, backups, and a compose stack with Caddy in front.
- **Nothing has ever been built or run.** Ten review rounds happened in a cloud container with no
  Docker daemon, no Valhalla and a blocked network. Every claim about the images, the stack, a
  rebuild or a restore is a claim about text, checked by tests that render and read. **Your machine
  is the first place the stack can actually start.** Expect the first build and the first rebuild
  to fail on things no review could see; those failures are the most valuable output of the next
  week.
- **The review loop is on hold, by the owner's decision.** Round 10 returned one ACCEPT (access
  control) and five REVISE with one blocker each, four of them regressions from the previous fix
  wave. `docs/review/retrospective.md` explains why the loop stopped converging and proposes the
  route this handoff implements: fix the open items, then run an executable checklist on a real
  stack instead of convening another panel.
- **The checklist exists.** `scripts/acceptance.py` (six items A1–A6, PASS/FAIL/SKIP with
  evidence), described in `docs/ACCEPTANCE.md`; `docs/PLAYBOOK.md` takes an empty host to a
  recorded run. Only its dry run has executed.

## 2. Decisions waiting on the owner

These are not yours to make; each is recorded in `handoff.md` §7 with its reasoning. Do not build
around them — if a task below touches one, stop and ask.

| Decision | Options on the record |
|---|---|
| **The exit condition for phase 1** | The retrospective's proposal: a checklist run passing A1–A5 with A6 at least rehearsed, plus one diff-scoped review finding no regression — in place of six simultaneous ACCEPTs. |
| `KEY_ENCRYPTION_KEY` rotation | Accept it as permanent for the life of a deployment, or add a key id column so bans survive a rotation. |
| `admin_contact_email` scope (PLAN:61 vs :208) | Amend :61, narrow the field to instance admins, or accept the guild-scoped write and gate it when email exists. |
| An instance admin cancelling their own removal | Exclude the target, require a second admin, or accept. |
| Audit rows' before/after and retention | Amend the plan or widen the model. |
| Maryland iMAP | Not installed in phase 1; waits on the ODbL waiver request (PLAN phase 0). |

## 3. Setting up on Windows

**Work inside WSL2, not in Windows paths.** Everything here — the checkout, the data root, Claude
Code, the native test loop — lives in an Ubuntu 26.04 distribution under WSL2 (26.04 because it is
the production host's OS), and Docker Desktop reaches into it. Three reasons, each of which breaks
something if ignored:

- **Line endings.** Git for Windows converts text files to CRLF by default. `.gitattributes`
  (`* text=auto eol=lf`, task T0) now makes every clone check out LF, which a Git-for-Windows
  default clone was shown to do: 98 CRs in `docker/api-entrypoint.sh` before, none after, and the
  api image built from that clone started gunicorn. Clone inside WSL anyway, for the next two.
- **Ownership.** The images run as uid 10001 and `prepare_data_root.sh` hands the data directories
  to it with `chown`. On the WSL ext4 filesystem that works; on a `/mnt/c/...` path it is silently a
  no-op and the containers cannot write their volumes.
- **Speed.** Bind mounts from `/mnt/c` cross the Windows/Linux boundary on every file access; a
  rebuild writing gigabytes of tiles through that is many times slower.

```powershell
# PowerShell, once
wsl --install -d Ubuntu-26.04
```

Then give the WSL VM enough memory — Docker Desktop's WSL backend lives inside that VM, and WSL's
default cap is half the host's RAM. The rebuild container is capped at 8 GB and its real peak has
never been measured. Create `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=24GB      # or as much as the machine can spare; 16GB is the floor worth trying
processors=8
```

and `wsl --shutdown` to apply it. The machine this was first set up on has 16 GB, so it runs with
`memory=12GB`: below the floor above, enough for the suite and the images, and not yet shown to be
enough for a rebuild (`handoff.md` §7 carries it). Install Docker Desktop, and under Settings →
Resources → WSL integration enable it for the Ubuntu-26.04 distribution — the switch is per
distribution, so a distribution added later starts without `docker`. Free ports 80 and 443 on
Windows (in PowerShell, `netstat -ano | findstr ":80 "`; IIS or another web server is the usual
holder). Leave about 60 GB free on the Windows drive: the WSL disk image grows to hold the extract,
the elevation tiles and two tile sets.

Everything from here runs in the Ubuntu shell. `docs/DEVELOPMENT.md`, "The native loop", explains
each step; in short, 26.04 packages neither PostgreSQL 16 nor Python 3.11, so both are pinned back to
what the stack runs:

```sh
# git inside WSL, signing in through the Windows credential manager (Git for Windows installed)
git config --global credential.helper "/mnt/c/Program\ Files/Git/mingw64/bin/git-credential-manager.exe"

# the checkout, in the Linux filesystem
mkdir -p ~/src && cd ~/src
git clone https://github.com/Macrophage87/RouteMaker.git && cd RouteMaker
git checkout claude/beautiful-mayer-4f7gg9

# PostgreSQL 16 + PostGIS from the PostgreSQL project's repository, and the Lua interpreters
sudo apt-get update && sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y postgresql-16-postgis-3 postgresql-16-postgis-3-scripts luajit lua5.4 python3-venv

# Python 3.11 and the images' exact package pins, through uv
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.11
uv venv --python 3.11 .venv
uv pip install -r docker/requirements.txt -r requirements-dev.txt

sudo sh scripts/devdb.sh
PGDATABASE=routemaker_dev .venv/bin/python -m pytest tests/ -q -p no:randomly   # expect every test to pass

# Claude Code, installed inside WSL per Anthropic's current Claude Code install docs, run from this directory
```

Install from both requirement files: from the loose `requirements-dev.txt` alone, on 26.04's Python
3.14, pip chose Django 6.1 and an admin-scoping test failed that passes on the pinned 5.2.17.
`tests/test_native_environment.py` now fails first when the venv's packages differ from
`docker/requirements.txt`.

**The test database and the stack do not collide.** The suite uses the native Postgres on
`127.0.0.1:5432` inside WSL; the stack's PostGIS lives on the compose network and publishes no
port. Keep a private `PGDATABASE` per concurrent test run: the suite creates and drops schemas.

**For the stack itself**, follow `docs/PLAYBOOK.md` with two substitutions: use the local posture (the
five-line block at the end of `.env.example`: `:80`, `DJANGO_DEBUG=1`, `localhost` hosts, an
`http://localhost/auth/callback` redirect, which Discord permits) and put `DATA_ROOT` in the Linux
filesystem, e.g. `/home/<you>/routemaker-data`. A browser on Windows reaches the stack at
`http://localhost`.

## 4. How to work

The retrospective's lessons, as rules:

1. **Run what you changed.** You have a daemon now. A compose change gets `docker compose up`, a
   pipeline change gets a rebuild, an admin change gets a browser. A test proves the test catches
   the change; running it proves the change is right. The last two fix waves shipped four
   regressions because they could only do the first.
2. **Write the mutation after the test and watch it fail.** Mutate the whole expression you edited,
   not only the part you added, and when a test asserts that something is refused, make the input
   fail for exactly one reason at a time.
3. **One adversarial pass over your own diff before merging**: take each fix's claim and try the
   neighbouring case — the other key form, the other container, the other direction.
4. **Tests assert properties, not sentences.** No new doc test that pins a phrase.
5. **Record rather than defer silently.** Something found and not fixed gets a row in `handoff.md`
   §7 with where the plan says it and what state it is in.
6. **Commits** end with the attribution trailer the session's tooling specifies. Never put a model
   name anywhere else in the repository.

`scripts/acceptance.py --only A1 A2` is a two-minute build-and-start gate after any change to the
images or compose; A4 is the long one, for pipeline changes.

## 5. The tasks, in order

Each has the files, what done looks like, and how to prove it. The round-10 reports in
`docs/review/round-10/` have the reviewers' exact probes; turn each probe into the test.

### T0 — Line endings (15 minutes)

Add `.gitattributes` with `* text=auto eol=lf`. The tree holds no binary files today, so
that one line covers it; add `binary` entries if images arrive. Then `git add --renormalize .`
and confirm the diff is empty. **Done when** a
fresh clone by Git for Windows with default settings builds the api image and its entrypoint runs.

### T1 — The compose pull policy (round-10 deployability blocker)

`pull_policy: build` on the four built services is unconditional in the installed Compose: `up -d`
always rebuilds, so the documented `TAG` rollback rebuilds the current tree under the old tag and
orphans the real previous image. Change it to `never` in `compose.yaml` (the four services and the
header comment), correct `docs/DEPLOYMENT.md`'s rollback section and the `handoff.md` §7 images
row, and update `tests/test_compose_render.py::test_the_services_that_build_never_pull`.
**Prove it:** build, `docker tag` the api image as `ghcr.io/macrophage87/routemaker-api:previous`,
change a comment in the source, `TAG=previous docker compose up -d api`, and confirm the running
container's image id is the tagged one and nothing was built.

### T2 — The LTS side model (round-10 domain blocker, plus three should-fixes)

Wave 8's worst-side rule works across the two sides but not within one: `_side_values` in
`src/routemaker/tags.py` unions the general keys (`cycleway`, `cycleway:both`) with the side key and
takes the best, so `cycleway=track` + `cycleway:right=no` on a 35 mph four-lane secondary rates
**LTS1** where the bare road is LTS4; `_shoulder_on_side` does the same. Rebuild it as one per-side
record — value and width — with explicit precedence (side-specific over `both` over the general
key; a side saying `no` is a side with nothing), then score the worst side. Fold in:
`cycleway_width_m`/`shoulder_width_m` reading the width of the side the facility is on (today a
track's width can rate the painted lane on the other side "adequate"); `is_oneway` accepting only
`yes`/`1`/`-1`/`true` (it currently treats `oneway=no` as one-way); and the one-way carve-out
declining when `oneway:bicycle=no` makes an `opposite_*` facility contraflow-only.
**Prove it:** the round-10 domain report's tables as parametrised cases, and a property test over a
generated grid of every key-form combination (presence × side × width × oneway) asserting that
adding a facility on either side never raises the tier and a narrower width never lowers it. Keep
the shoulder floor (an owner decision) and the round-7/8 pins green. Mirror the precedence in
`lua/routemaker_remap.lua`'s `declares_cycleway`.

### T3 — Rollback ordering and its one container (round-10 database blocker)

`rollback()` in `src/pipeline/promotion.py` swaps the schemas before it demotes the tiles. In a
container where the tiles are read-only (`api` and `worker` since wave 8) the demotion fails after
the rename, and if the undo's re-swap loses its lock to an ordinary reader the deployment is left
serving this week's tiles over last week's rows, with the served rows in `staging` for the next
rebuild to drop. Demote the tiles first, and add a write probe of `TILES_DIR` to
`rollback_rebuild`'s pre-flight so a read-only mount refuses before anything moves. Correct the two
guide passages that still say `api` mounts nothing (`docs/OPERATIONS.md` "Rolling back a rebuild",
the `docs/DEPLOYMENT.md` "which command runs where" table) and the doc test that pins the stale
sentence (`tests/test_deploy_docs.py`, "mounts no part of the data volume"). Add the missing runbook
section for a `SwapUndoIncomplete` alert: what state the deployment is in and how to repair it by
hand, since `rollback_rebuild` refuses there.
**Prove it:** on the running stack, `docker compose exec api ./manage.py rollback_rebuild --confirm`
refuses and nothing changes; in `rebuild` after two promoted builds, the rollback works (checklist A6).

### T4 — Directional overrides (round-10 routing blocker)

An approved override writing only `bicycle:forward=no` on a fixture bridge makes `inject_tags`
withhold the fixture's bidirectional grant wholesale, so the bridge is served barred both ways.
Scope the withholding to what the row wrote: a directional row keeps the fixture's grant in the
other direction. Files: `src/pipeline/overrides.py` (`BICYCLE_ACCESS_KEYS`, `apply_access`),
`src/pipeline/run.py` (`inject_tags`).
**Prove it:** the reviewer's probe — the transform run under `luajit` over the vendored Valhalla Lua
gives `bike_forward=false bike_backward=true` — as an end-to-end test reading the extract back.

### T5 — The sentinel read (round-10 test-quality blocker and routing SF-1)

`tiles.sample_cycle_lane` filters `none` edges before checking agreement, so a half-transformed block
answers "separated", and its "one and the same way" guard is deletable with the suite green because
the only spanning test's edges also disagree. Check agreement over all edges on the way before
filtering, and add the missing case: two different ways that agree answer nothing.
**Prove it:** `if len(way_ids) != 1 or None in way_ids` → `if None in way_ids` fails a named test.

### T6 — Access control should-fixes

- A pending instance-admin removal survives the target's own stand-down and later strips a fresh
  re-appointment (`UserAdmin.save_model` in `src/core/admin.py`; `schedule_instance_admin_removal`
  and `apply_due_instance_admin_removals` in `src/core/models.py`). Clear pending rows when an
  account is re-appointed, audited.
- A refused bulk action's audit row records `action="action"`; record which action was attempted.
- `ALLOWED_HOSTS` in `src/config/settings.py` does not strip whitespace, so `a, b` makes every
  request for `b` a 400; strip it, and make the api healthcheck fall back to `127.0.0.1` when the
  first entry is `*` or empty.

### T7 — The rest of round 10's should-fixes

One commit each, each with its test: the override report reaching the run detail and the log
(`OverrideReport` is currently written and never read); validating the timezone database's `.part`
before it is moved into place (`tiles.tile_build_commands`); the restore runbook's error count and
exit code (169 errors, exit **1**, not 0); `unwedge_job`'s next-steps text after a job lands
`failed`; `HANDLED_KINDS` enumerated in a test; the `- {Stage.SWAP}` exclusion in
`stages_after_swap()` pinned; `prune_backups` with fewer dumps than `keep`; `disk_headroom` pinned
to measure `TILES_DIR`, not only report it; the `DISCORD_REDIRECT_URI` path pinned;
`prepare_data_root.sh`'s env-file parser (last assignment wins, CR strip, quote stripping) tested;
`valhalla_exception` finding a body after leading text; the agency string casefolded with `mdsha`
aliased to `mdot-sha`; the dead negative assertion in `tests/test_auth_wiring.py`.

### T8 — Replace sentence-pinning doc tests

`tests/test_deploy_docs.py` asserts phrases; when the code moves, the tests hold the guides to the
old state (round 10 found one defending a false sentence). Rewrite each as a property (the rendered
configuration, the presence of a section, a command's argv) or delete it.

### T9 — Run the checklist locally, and fix what it finds

`python3 scripts/acceptance.py`, A1 through A6 (`--second-rebuild --confirm-rollback` for A6). You
need the three reference inputs for A4's second run — Census TIGER urban areas, VDOT and DDOT AADT;
`docs/PLAYBOOK.md` §0 and `docs/DEVELOPMENT.md` "Reference data" say where they come from and how to
convert them. Every FAIL is a task: fix it, test it, re-run with `--resume`. Things most likely to
surface here and nowhere else: Debian package names in `docker/api.Dockerfile`, Valhalla config
keys at startup, the rebuild's memory peak (measure it, and put the number in `handoff.md` §7's
memory row), the elevation download, and the timezone build. Commit the passing report under
`docs/review/acceptance/`.

### T10 — One diff-scoped review, then the server

One reviewer over the diff since `41b65bf`, asked only: does anything regress, and does the
checklist still pass. Then the same checklist on the real server with the hostname posture
(`docs/PLAYBOOK.md` §1 onward). If the owner has adopted the retrospective's exit condition, that
run is the acceptance.

## 6. Where to look

| For | Read |
|---|---|
| Why the loop stopped, every blocker classified, the proposed route | `docs/review/retrospective.md` |
| The open findings with the reviewers' exact probes | `docs/review/round-10/` |
| Known gaps and recorded decisions (49 rows) | `handoff.md` §7 |
| The checklist and the order to run it | `docs/ACCEPTANCE.md`, `docs/PLAYBOOK.md` |
| Build, secrets, the edge, host sizing | `docs/DEPLOYMENT.md` |
| Rebuilds, alerts, wedged jobs, backup, restore, rollback | `docs/OPERATIONS.md` |
| Environment variables, the native loop, reference data | `docs/DEVELOPMENT.md` |
| What the product is meant to be | `PLAN.md` |
