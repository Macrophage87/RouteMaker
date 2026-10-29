# Development environment

The plan's deployment target is one Docker Compose stack on one AWS host. For
development the same components run natively, which is faster to iterate against
and, for the database layer, tests the real thing rather than a stand-in.

## Environment variables

`.env.example` is the full list; three of them decide whether the deployment
works at all and are explained here rather than in a comment beside a default.

**The example ships a hostname deployment over HTTPS.** `CADDY_SITE_ADDRESS`,
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and
`DISCORD_REDIRECT_URI` all name `routes.example.org`, which is replaced with
your own name in four places. A plain-HTTP stack on a laptop is the commented
block at the end of the file, and it is a block rather than a single variable
because `:80` on its own does not work: `settings.py` derives
`SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` from `not DEBUG`, so without
`DJANGO_DEBUG=1` every cookie is `Secure` and a plain-HTTP browser throws the
session away without saying anything. Take the five lines together or take the
hostname. `tests/test_compose_render.py` refuses any other combination.

Nothing on this page needs the compose stack: "The native loop" below is what
to develop against. If you are standing up a real host, the order
the code forces is in docs/OPERATIONS.md, "First rebuild on a fresh host" —
notably that the reference data below cannot be installed until a first rebuild
has fetched the extract it is checked against.

**How a variable reaches a container.** There is no `env_file`: one shared file
would hand the key-encryption key to Photon and Valhalla and contradict the
claim that one component alone holds the bot token. Every variable is declared
on the services that read it, in `compose.yaml`. The non-secret settings that
every Django process needs the same value of live in the `x-django-env` anchor
at the top of that file and are merged into `api`, `worker`, `migrate` and
`rebuild`; the secrets stay written out per service, so which container holds
which one is readable at a glance.

`tests/test_compose.py` derives the set of names `config/settings.py` reads from
that module's own source and fails until each one is either declared on `api` or
named in the small, commented allow-list there - so adding an
`os.environ.get("NEW_THING")` to settings without also delivering it fails the
suite rather than producing a container that quietly runs on the default. That
test exists because the stack had declared six of the twenty-four: under it,
`ALLOWED_HOSTS` was the module's `["localhost"]` fallback, so every request that
arrived through Caddy was a `DisallowedHost` 400, and the Discord authorize URL
carried an empty `client_id` and a redirect back to `localhost:8000`.

### `KEY_ENCRYPTION_KEY` — required, no default

Every process that imports `config.settings` needs it, including `migrate` and
the rebuild worker, and settings **refuse to import without it**. It keys the
ban tombstones: `settings.TOMBSTONE_KEY` is derived from it with one HMAC over
a fixed label (`routemaker/ban-tombstone/v1`), which is HKDF-Expand with a
single output block, so the key that encrypts and the key that tombstones are
two distinct values from one delivered secret.

There is deliberately no fallback. A Discord id is a structured 64-bit value
whose candidate set any guild's member list resolves directly, so an unkeyed —
or publicly keyed — digest of one gives no privacy at all against whoever holds
a dump. With a development default in the settings file, the published literal
*was* the key on every deployment that had not set the variable, and nothing
declared it. A container without the key now stops at import instead.

It comes from SSM (SecureString, KMS-backed) in production and from the
environment file locally.

**It is not rotatable in phase 1, and the failure mode is silent.** A
`BanTombstone` row holds the HMAC and nothing else — `tombstone`, `created_at`
and a free-text `reason` (`core/models.py`) — which is the property that makes
the table safe to keep in the nightly dump, and it is also the property that
makes a rotation unrecoverable: the Discord id the digest was taken over is not
stored anywhere, so there is nothing to re-derive the new digest from. This was
once written down here as "a re-tombstoning job", which implies a job exists.
None does, and none can from the data that is kept.

What a rotation actually does is **re-admit every banned account**. The ban
check computes `tombstone(discord_user_id, settings.TOMBSTONE_KEY)` at sign-in
and looks the result up; under a new key no stored row ever matches, so every
tombstoned id signs in again as if it had never been banned, the old rows sit
in the table matching nothing, and nothing logs or refuses. Treat the value as
permanent for the life of a deployment: back it up with the database rather
than rotating it, and if it has to change, the bans have to be re-entered from
whatever record exists outside this system. handoff.md section 7 carries that
as an open row.

`DJANGO_SECRET_KEY` is the opposite case and is worth stating beside it, since
both are "a random string in `.env`" and they are not alike. Rotating it is
safe and it is not free: sessions are database-backed, their payload is signed
with that key, `settings.py` sets no `SECRET_KEY_FALLBACKS`, and so every
session fails to decode on the next request and is discarded. **Every signed-in
user is signed out**, and signs back in through Discord. Nothing is corrupted
and nothing needs repair. docs/DEPLOYMENT.md, "Secrets, and what rotating one
costs", has the same two alongside `PGPASSWORD`, whose rotation is a procedure
rather than an edit. It is required too unless `DJANGO_DEBUG=1`: outside DEBUG an
unset or empty `DJANGO_SECRET_KEY` stops the process at import, since the
development default is a string in this repository.

The suite supplies its own values through `config.test_settings`, which is
`config.settings` plus those two defaults and nothing else. It cannot come from
`tests/conftest.py`: pytest-django sets Django up while it loads the initial
conftests, before any conftest body has run.

### `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` — how a new deployment gets its first admin

There is no password login, no `createsuperuser`, and the only surface that
writes `is_instance_admin` is an admin page only an instance admin can reach, so
a fresh database has no way into the admin at all. Set this to one Discord id
before the first start:

```sh
BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID=123456789012345678
```

Before the first `docker compose up`, and in `.env` rather than in a shell:
compose reads the environment file when it *creates* a container, so an id
added to `.env` afterwards reaches the running api only on
`docker compose up -d api`, which recreates it. `docker compose restart api`
does not — it restarts the process with the environment the container was
created with, and the sign-in that follows gets the admin's ordinary 404 with
nothing anywhere to say why. docs/OPERATIONS.md, "First rebuild on a fresh
host", puts it in the sequence.

That id grants standing **only while the instance-admin list is empty**. Sign in
with that Discord account and open the admin once: the first admitted request
writes the id into the instance-admin list, records a `bootstrap_instance_admin`
audit row, and from then on the variable is inert even if it still names
somebody. Nothing has to be unset afterwards for the deployment to be safe,
though leaving it set is pointless.

It reaches the `api` service alone, since the admin is the only reader.

**It is spent once, permanently.** The claim writes a `bootstrap_claim` row -
one row, enforced by a unique index - and from then on the environment path is
refused whatever the instance-admin list looks like. That is what "permanently
disables the environment path" has to mean: the earlier version tested the list
instead, so emptying the list re-armed the variable, and anyone who had ever
read `.env` held a standing offer of instance admin against any future moment
the list happened to be empty. A refused second claim logs at WARNING saying the
path is spent, so the 404 has a reason attached to it.

The list counts the holders who could actually sign in - banned and deleted
accounts excluded - which is the same count `check_last_instance_admin` uses, so
a deployment whose only instance admin has been banned is one both rules agree is
empty.

The consequence is worth stating plainly: **once the claim row exists, an
instance-admin list that empties cannot be refilled through the application at
all.** There is no password login and no `createsuperuser`, so the only repair is
direct database access:

```sql
-- Break glass. Run against the deployment database by whoever has access.
UPDATE app_user SET is_instance_admin = true WHERE discord_user_id = <id>;
```

`check_last_instance_admin` exists so this should never be needed: it refuses
every application path - `save()`, the admin, and `delete()` through the
`pre_delete` guard - that would remove the last instance admin. What it cannot
cover is `QuerySet.update()`, which issues one UPDATE and emits no signal, so a
management shell or a data migration can still empty the list. That is the case
the break-glass above is for.

The `bootstrap_claim` row is in the nightly dump, so a restore restores the
disabling along with everything else.

### `INSTANCE_ADMIN_REMOVAL_DELAY_SECONDS` — the removal window

Removing an *other* instance admin does not take effect immediately. It writes a
pending removal with an effective time this many seconds out (default 3600, the
plan's hour), during which any instance admin can cancel it from the "pending
instance admin removals" page; without the window, one admin removes every peer
down to themselves in a single unstoppable action. Standing down — clearing your
own flag — is immediate, and the last instance admin can never be removed by
either path.

Re-requesting a removal that is already pending updates who asked and moves the
effective time later or not at all - never earlier - so a window that is already
running cannot be shortened by asking for the same removal again under a
shortened delay.

Due removals are applied by `core.models.apply_due_instance_admin_removals()`,
which the five-minute `degraded_guild_sweep` calls (outside that task's
gateway-heartbeat gate, which has nothing to do with removals) and which the
six-hourly membership sweep also calls as a backstop. It used to be the
six-hourly sweep alone, which made the plan's hour an effective one-to-seven
hours; it is now the hour plus at most five minutes. Notification of the removed party
and the remaining admins is **not** implemented: phase 1 has no Discord DM path
and no email path, so the window and the cancel exist and the notice does not.

## The native loop

The host this is written for is Ubuntu 26.04, which is also the production
host's OS; under Windows it is the same distribution in WSL2 (handoff-local.md
section 3 has the Windows side). Two things on it differ from what the stack
runs, and each is pinned back by hand below.

**PostgreSQL 16 does not come from Ubuntu.** 26.04 packages PostgreSQL 18 and
not 16, while the stack runs `postgis/postgis:16-3.4` and `scripts/devdb.sh`
starts cluster 16. The PostgreSQL project's own repository (PGDG) carries 16:

```sh
sudo apt-get update && sudo apt-get install -y postgresql-common ca-certificates curl
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y postgresql-16-postgis-3 postgresql-16-postgis-3-scripts \
    luajit lua5.4 python3-venv
```

GeoDjango also needs GEOS, GDAL and PROJ; the PostGIS package pulls all three
in. PGDG's PostGIS for 16 is the current 3.x (3.6 at the time of writing), not
the image's 3.4, so the native loop runs two PostGIS minors ahead of the stack.
`ca-certificates` is on the first line because the PGDG script fetches over
HTTPS: without it (a minimal image lacks it) the script prints a certificate
error, still reports success, and the next line cannot find the packages.
`curl` is for uv's installer below.

**Python 3.11 does not come from Ubuntu either.** 26.04 ships 3.14; the api
image runs 3.11 (`PYTHON_VERSION` in `docker/api.Dockerfile`). `uv` installs
the interpreter and builds the venv; it is not an Ubuntu package, so it comes
from its own installer:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"   # the installer does not change the running shell's PATH
uv python install 3.11
uv venv --python 3.11 .venv
uv pip install -r docker/requirements.txt -r requirements-dev.txt
```

Both requirement files, always. `requirements-dev.txt` is loose and
`docker/requirements.txt` is the exact pin the images install; from the loose
file alone, on 3.14, pip picked Django 6.1 (it resolves 6.1 on 3.12 to 3.14 and
5.2.17 on 3.11), and the admin's guild scoping answered a guild admin's write
to another guild's row with a 302 rather than a 403 or 404 - a test failure
caused by a Django the stack does not run.
In that case `tests/test_native_environment.py` also fails, naming each pin the
interpreter does not have; it does not run first, so read its failure before
the others. CI installs the same two files.

Then the database and the suite, from the checkout:

```sh
sudo sh scripts/devdb.sh
PGDATABASE=routemaker_dev .venv/bin/python -m pytest tests/ -q -p no:randomly
```

`devdb.sh` starts cluster 16 if it is down, and creates the `routemaker` role,
the `routemaker` database and the PostGIS extension if any is missing; under
systemd (a desktop, or WSL with systemd enabled) the cluster is already up at
boot and the script only does the second half. It runs as root because it
switches to the `postgres` account. The suite creates and drops schemas, so give
each concurrent run its own `PGDATABASE` (below, "Running the suite twice at
once").

`/tmp` on 26.04 is a tmpfs, sized from RAM and shared by every process on the
host, so a test that measures free space under `tmp_path` sees a few gigabytes
rather than a disk, and how full they are depends on whatever else is running.
The rebuild tests therefore neutralise both halves of the disk gate: what it
reserves is scaled to their toy extract, and its fullness fraction is set to
100 percent, the way `tests/test_operations.py` already did. The gate's own
refusals are tested with a stand-in `disk_usage`. A `/tmp` that genuinely runs
out still fails the suite, and can abort it outright: a pyosmium writer that
hits ENOSPC can raise from its destructor, which ends the process. When `/tmp`
is short, point `TMPDIR` at a real disk: pytest's `tmp_path` and the tests that
call `tempfile` directly both follow it, where `--basetemp` moves only the first.

## The front end

`frontend/` is the public map (docs/DEPLOYMENT.md, "The public front end").
Node is not needed on the host; the official image runs everything, as you, in
the checkout:

```sh
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/frontend:/app" -w /app node:22 npm ci
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/frontend:/app" -v "$PWD/src:/src:ro" -w /app node:22 npm test
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/frontend:/app" -w /app node:22 npm run build
```

- `npm test` needs `src/` mounted read-only at `/src`: one test reads the API's
  own wording from `src/routemaker/avoid_junctions.py`.
- `npm test` is `node --test` over `src/**/*.test.{mjs,ts}`: the pure logic
  (error mapping, request pacing, the long-ride rule, stress bar maths, the
  plan in the link) and the stress palette's contrast against the base map's
  own colours, which reads `@protomaps/basemaps` from `node_modules` - so
  `npm ci` first. The TypeScript runs through Node's own type stripping, on by
  default from Node 22.18; `tests/test_frontend.py` runs the same files inside
  pytest, skips on a machine without Node (WSL here) and fails in CI if the
  Node there is older or missing.
- The junction markers (OWNER-DECISIONS 172; an orange triangle for higher stress and a red
  diamond for very high stress, the diamond an octagon until 311) are `lib/intersectionMarkers.ts`
  (what is listed, worded and drawn, tested without a DOM), `IntersectionList.tsx`
  (the route summary's list) and `MapView.tsx` (a DOM marker for each, a card on
  click, the list's click opening the same card); the slider's words, its note at
  the top end and the detour tiers are `lib/dials.ts`, `lib/dialsPanel.ts` and
  `lib/summary.ts`. A look at them without the live stack: build the front end,
  serve it from a Caddy (the repository's Caddyfile, `CADDY_SITE_ADDRESS=:80`) on a
  private network beside an api container started from the api image with
  `PYTHONPATH` at the checkout's `src` (`python -m django runserver`), label every
  container of the check `com.docker.compose.project=isect`, and remove them after.
- `frontend/.npmrc` turns off npm's update notifier, which otherwise asks the
  registry for npm's latest version on every run in a fresh container.
- `npm run build` typechecks (`tsc --noEmit`) and then builds `dist/`, which
  is not committed; `npm run typecheck` is the first half alone.
- `npm run dev` serves the UI with hot reload and proxies `/api`, `/tiles` and
  `/basemap` to a stack, rewriting `Origin` and `Referer` to that stack's own
  because the base map refuses any other origin. `DEV_STACK` names the stack;
  inside a container on the compose network that is the edge's name, e.g.
  `docker run --rm -it -u "$(id -u):$(id -g)" -e HOME=/tmp -e DEV_STACK=http://<caddy container> --network routemaker_default -p 127.0.0.1:5173:5173 -v "$PWD/frontend:/app" -w /app node:22 npx vite --host 0.0.0.0`.
  The dev server is for looking at the UI; proofs go through a Caddy serving
  the build, as docs/DEPLOYMENT.md describes, because only that exercises the
  edge's headers.

### The accessibility switch and the colour-blind-friendly palette

The panel's High contrast switch, called Accessibility until OWNER-DECISIONS 384
(208, 209, 211, 212; PLAN.md,
Owner amendments) turns on the `cvd` palette in `frontend/src/stressStyle.js`
and draws the overlay stronger. The state lives in that module and is read
through `currentTiers()`, never kept from import time; `subscribePalette()`
announces a change, and `useStressStyle()` (React) and `MapView`'s effect (the
map) repaint on it. What is chosen is held in `localStorage` as
`routemaker.accessibility`.

Where it starts: the stored "on" or "off" first, then the browser's
`prefers-contrast: more` (followed live while nothing is stored), then off. The
palette: `?palette=` in the link, then the switch, then the default, `twotone` (since
OWNER-DECISIONS 351; `blended` before, "The default palette", below). A link names
the palettes neutrally (OWNER-DECISIONS 321): `warm` (blended), `twotone` and
`cool` (cvd), and still reads the older `blended` and `cvd` silently, and on load
renames them in the address bar (`neutralPaletteSearch`, the release re-check's S4);
`frontend/src/lib/linkPrivacy.test.ts` scans every link the page writes, over every
ride type and option, for words that reveal a disability or assistive need. The
colours of the switch's state are one place, `tiersFor(palette, strong)`.

The `cvd` palette, with casings (the casing is the dark or light line drawn
under a tier so it holds against the base map; the switch makes the calm tiers'
black or white and leaves the busy tiers' as they are):

| Tier | Line | Casing |
| --- | --- | --- |
| LTS 1 | #d2eafc | #0a1a2f |
| LTS 2 | #5d99d2 | #0a1a2f (gaps #a7b4c1, 356) |
| LTS 3 | #cd4b0a | #0a1a2f |
| LTS 4 | #6a0a06 | #ffffff |
| Avoid | #08081e | #f0e442 |

It was chosen by search, not by eye: random and grid search over sRGB with the
hue of each tier held to a family (light and mid blue, orange, dark red,
blue-black), scored by the smallest CIEDE2000 between neighbours under normal
vision and each simulation, with the luminance falling by at least 1.5:1 a step
and 3:1 against every base-map surface (with a casing) as constraints. (1.5:1
was the search's target; the test's floor is 1.4:1, which leaves a later retune
a margin. The smallest step chosen is 1.51:1.) Avoid is blue-black on purpose:
a protanope sees LTS 4's dark red as near-black, and a neutral black Avoid
beside it measures about 17 apart (#000000 is 16.9 under protanopia, and
#242424 14.1), under the floor of 20. Its casing is a light yellow (Okabe-Ito
#f0e442; white until the release review's accessibility SF5), a cue of its own
beside LTS 4's white: the Avoid line is 14.9:1 on it, the two casings are 28.9
CIEDE2000 apart under normal vision (29.9 protan, 28.3 deutan, 16.8 tritan), and
the LTS 4 and Avoid lines are at least 27.2 apart under every vision.
Blue against orange is the pair all three deficiencies keep.

CIEDE2000 between neighbouring tiers, LTS 1-2, 2-3, 3-4, 4-Avoid, and the
closest pair of any two tiers, for every palette and each vision (Machado,
Oliveira and Fernandes 2009, severity 1.0, applied in linear RGB). Only `cvd`
is held to the floor of 20 (and 35 for LTS 2-3); the others are reported by
`node --test src/stressContrast.test.ts`, which prints this table as test
diagnostics:

| Palette | Vision | LTS 1-2 | LTS 2-3 | LTS 3-4 | LTS 4-Avoid | Closest pair |
| --- | --- | --- | --- | --- | --- | --- |
| blended | normal | 16.1 | 40.2 | 28.5 | 38.9 | LTS 1-2, 16.1 |
| blended | protan | 15.4 | 14.9 | 19.9 | 27.9 | LTS 2-3, 14.9 |
| blended | deutan | 16.2 | 15.5 | 11.0 | 40.2 | LTS 3-4, 11.0 |
| blended | tritan | 16.0 | 51.7 | 15.5 | 42.0 | LTS 3-4, 15.5 |
| twotone | normal | 16.1 | 35.4 | 21.0 | 29.4 | LTS 1-2, 16.1 |
| twotone | protan | 15.4 | 20.5 | 12.4 | 28.3 | LTS 3-4, 12.4 |
| twotone | deutan | 16.2 | 26.0 | 8.3 | 17.8 | LTS 3-4, 8.3 |
| twotone | tritan | 16.0 | 46.9 | 13.4 | 18.3 | LTS 3-4, 13.4 |
| cvd | normal | 24.0 | 48.3 | 25.8 | 31.1 | LTS 1-2, 24.0 |
| cvd | protan | 23.0 | 51.4 | 23.2 | 27.2 | LTS 1-2, 23.0 |
| cvd | deutan | 25.5 | 51.7 | 26.9 | 34.1 | LTS 1-2, 25.5 |
| cvd | tritan | 24.0 | 59.8 | 23.1 | 32.3 | LTS 3-4, 23.1 |

This option left the default `blended` palette as it was; item 274 later
changed its LTS 4 (#c80018) and Avoid (#14040a over a #ee3b2c casing), and
LTS 1 to 3 are as they were ("Stress salience", below). It does not meet 20 for
every pair under protanopia and deuteranopia (LTS 2 and 3 are 15 apart; the
dashes and widths tell them apart, as the comment in `stressStyle.js` says).
Item 274's red lowered LTS 3 against LTS 4 under deuteranopia from 18.0 to 11.0,
by choice: it holds that pair's luminance at 1.47:1, over the 1.4:1 floor, and
the pair also differs by dash, width and casing. LTS 4 against Avoid rose from
about 20 to 28 or more under every vision. That is the reason for the option,
not something it changes.

WCAG relative luminance between neighbours (greyscale order): `cvd` Y 0.796,
0.298, 0.180, 0.033, 0.003, steps of 2.43, 1.51, 2.78 and 1.56 to 1; `blended`
Y 0.568, 0.283, 0.234, 0.123, 0.003, steps of 1.86, 1.17, 1.64 and 3.30 to 1; `twotone`, the
default since 351, does not fall: Y 0.568, 0.283, 0.575, 0.378, 0.151 (LTS 3 is the lightest
tier and LTS 4 is lighter than LTS 2), reported in `defaultPalette.test.ts`.

Contrast of a tier against the base map (every surface of `@protomaps/basemaps`'
light flavour) and both panel themes, the worst case per tier, by the rule in
`stressContrast.test.ts` (the line itself, or its casing against the surface
and the line against its casing; 3:1 needed):

| Palette | LTS 1 | LTS 2 | LTS 3 | LTS 4 | Avoid |
| --- | --- | --- | --- | --- | --- |
| twotone (the default since 351; LTS 3 and 4 reported) | 4.42 | 4.82 | 1.44 | 2.34 | 3.20 |
| twotone, switch on | 9.83 | 4.82 | 1.44 | 2.34 | 3.20 |
| blended | 4.42 | 4.82 | 3.60 | 3.54 | 4.21 |
| blended, switch on | 9.83 | 4.82 | 3.60 | 3.54 | 4.21 |
| cvd | 10.23 | 5.53 | 3.66 | 7.41 | 11.55 |
| cvd, switch on | 12.29 | 5.53 | 3.66 | 7.41 | 11.55 |

LTS 1 and 2 changed with 357 (LTS 1's softer edge, #2f5d47; LTS 2's slate blue,
#1a2638, which the switch keeps).

The route line in the `cvd` palette. The route's sections were drawn in a 5 px
line on a 9 px casing (4 to 6 px on 11 px since item 274). The casing was the route's blue (#1d4ed8), which the
`cvd` palette's LTS 2 mid blue matched: 2.22:1 and 19.5 to 25.5 CIEDE2000
apart, so an LTS 2 section read as a plain route (review r1, accessibility).
In the `cvd` palette the casing is a dark slate, #344c4c (`ROUTE_CASING_CVD`
in `frontend/src/lib/routeColours.ts`). The blue stays for the other palettes.
No one colour can be 3:1 from both LTS 1 (Y 0.796) and Avoid (Y 0.003) and also
from LTS 2 (Y 0.298). So the casing was chosen by a grid search over sRGB: LTS 2
at least 3:1 and 30 CIEDE2000 under every vision as constraints, and then the
smallest CIEDE2000 to every other class as the score. A white casing also
gives LTS 2 3:1, but it is 1.24:1 and 9.7 apart from LTS 1, and it is not 3:1
from the base map. The casing against each class (contrast, and the smallest
CIEDE2000 over normal vision and the three simulations; the blue it replaces in
brackets):

| Class | #344c4c | (#1d4ed8) |
| --- | --- | --- |
| LTS 1 #d2eafc | 7.41:1, 52.8 | (5.40:1, 38.6) |
| LTS 2 #5d99d2 | 3.04:1, 32.3 | (2.22:1, 19.5) |
| LTS 3 #cd4b0a | 2.02:1, 26.8 | (1.47:1, 50.4) |
| LTS 4 #6a0a06 | 1.38:1, 19.6 | (1.89:1, 43.6) |
| Avoid #08081e | 2.15:1, 19.1 | (2.95:1, 30.8) |
| Not rated #9f9c93 | 3.35:1, 32.6 | (2.44:1, 32.4) |
| Traffic-free #4c1d95 | 1.19:1, 19.3 | (1.63:1, 11.0) |

The dark classes stand on the casing by hue, not lightness. The casing is also
at least 3:1 from every base-map surface, so the route still stands out from the
map. `stressContrast.test.ts` holds it to the following and prints the table as
diagnostics:
- LTS 2 at 3:1 and 30;
- every class at least 19, the search's best with LTS 2 held there;
- the base map at 3:1.

"Not rated" (`#9aa0a6`, a cool grey) was not in the delta check. Against the
`cvd` blues it is 16.3 (LTS 2) and 19.0 (LTS 1) apart, under the floor of 20.
In the `cvd` palette it is `#9f9c93` (`UNRATED_CVD_COLOUR` in
`frontend/src/lib/stressBar.ts`), a warm grey of about the same lightness, which
is used on the route line and in the stress bar. Its smallest CIEDE2000 under
every vision is:

| Against | #9f9c93 | (#9aa0a6) |
| --- | --- | --- |
| LTS 1 | 24.0 | (19.0) |
| LTS 2 | 24.8 | (16.3) |
| LTS 3 | 24.0 | (31.3) |
| LTS 4 | 40.5 | (45.8) |
| Avoid | 50.0 | (50.9) |
| Traffic-free | 38.1 | (39.5) |

The test holds it to 20 against every tier and the violet.

The tests: `src/lib/accessibilitySwitch.test.ts` (precedence with `location`,
`localStorage` and `matchMedia` stubbed on a fresh copy of the module, storage
and `matchMedia` failures, live changes, the repaint wiring against a recording
map, the component, the legend's widths through `legendWidths()` plain and
strong, and a scan of the shipped source, parsed with the bundler's own parser,
for a module that names a removed constant or calls `currentTiers()`,
`furthTiers()`, `routeClasses()` or `legend()` at its top level, where the call
would run once at import), `src/stressContrast.test.ts` (3:1 and the delta floor, plain
and with the switch on), `src/stylesAccessibility.test.ts` (the `.a11y` and
forced-colors blocks of `styles.css`, and that the stylesheet does not read
`prefers-contrast`) and `src/testSupport/colourVision.test.ts` (the simulation
and CIEDE2000 helper, `src/testSupport/colourVision.ts`, against Sharma, Wu and
Dalal's published pairs and the Python script the palette was chosen with).
A mutation pass on the first version of this change ran each of eighteen
mutants (the address losing to the switch, a contrast request beating a stored
choice, storage failure reading as on, the live follow moving a chosen switch,
the repaint skipping widths, MapView not repainting, strong lines no wider,
a style key ignoring the switch, a brightened LTS 4, a light LTS 1 casing, the
forced-colors block dropping the segments, a `prefers-contrast` rule in the
stylesheet, tiers frozen after the first read, the stored choice not read or not
written, the root class never following, the switch losing its role, casings not
stronger) against the whole suite. Three survived at first (the strong widths
and the style key, which the tests derived from the constants they mutated, and
a stylesheet mutant whose pattern matched nothing); the tests were tightened
(the literal widths, a flip under an address-chosen palette) and all eighteen
are killed.

Looking at it without WebGL or a network: the panel's pieces as the app renders
them, with the real `styles.css`, in the Chromium of the Playwright image
already on the machine (`mcr.microsoft.com/playwright/python:v1.58.0-noble`,
its headless shell, driven over the DevTools Protocol by Node 22's own
WebSocket from a second container sharing its network namespace, both with
`--network none`; the Python `playwright` package is not in that image). The
emulated media were `forced-colors: active`, `prefers-contrast: more` and both
colour schemes, for the switch off and on. The map itself needs the stack and
was not looked at.

**The release review's accessibility fixes** (front end, f0f2ed9):
- A plan still running after 3 s says "Still planning." once in the status line,
  and a labelled indeterminate progress bar shows while it plans.
- The routes to choose from are short-named radios, "Route N: X mi, Y more than
  Route 1" (miles first, km in brackets, as in "Route 2: 7.2 mi (11.6 km), 0.2 mi
  (0.4 km) more than Route 1"), each described by its own figures. The shared
  hint describes the group and no longer asks the rider to look at the map.
- Target distance says a bad entry in a persistent assertive live region, and the
  weight dialog does the same.
- The "Show bike lanes on high-stress roads" switch is always shown with a route,
  with or without the stress map, in its own words.
- The plan's points on federal land are listed in words ("Your points on federal
  land"), so a rider who cannot point at the map gets the names.
- The a11y harness counts every check: `EXPECTED = 187` in `scripts/a11y/check.mjs`.

### Stress salience: the tiers' shapes and the facility rails (items 274 to 283, 290, 292, 302)

PLAN.md, Owner amendments, "FOLLOWUP-STRESS-SALIENCE", has the owner's words.
The rule behind every number here: **visual weight rises with stress**, and
what tells two classes apart never rests on colour alone. Everything is in
`frontend/src/stressStyle.js` (`TIER_SHAPES`, `PALETTES`, `FACILITIES`), and
the owner approved it on the r1 preview (297). Display only: no rating and no
data changed.

**The tiers** (the warm `blended` palette, the default until 351; the two-tone
default is in "The default palette", below; widths with the High contrast switch
off):

| Tier | Line | Casing | Dash | Width | Ink | Gap harshness |
| --- | --- | --- | --- | --- | --- | --- |
| LTS 1 | #9ed3ac | #2f5d47 | solid (`null`) | 2.5 px | 2.50 | 0 |
| LTS 2 | #57a06c | #1a2638, gaps #7a8fa3 | [4, 1] | 3.25 px | 2.60 | 0.21 |
| LTS 3 | #bf730b | #45290a | [2, 0.4] | 4.25 px | 3.54 | 0.60 |
| LTS 4 | #c80018 | #ffffff | [8, 1] | 5 px | 4.44 | 0.67 |
| Avoid | #14040a | #ee3b2c | [5, 1, 0.5, 1] | 6.5 px | 4.77 | 1.34 |

- **The dash ladder (283).** Ink is the share of the line that is drawn (the
  dash duty cycle) times its width, and it rises strictly from LTS 1 to Avoid
  in all three palettes (`stressSalience.test.ts`). Before this change it was
  3.00, 2.40, 1.75, 1.33 and 2.86, so LTS 4's sparse `[1, 2]` carried the least
  ink on the map. Now LTS 4 is 89% drawn, near-solid and heavy. Avoid is the
  widest line and keeps a dash-dot that no other tier has. The duty cycle
  alone is not monotonic (LTS 1 is solid and Avoid 73% drawn); the product is
  what rises. Dashes scale with the line width, so LTS 3's dash is 8.5 px.
- **LTS 4 and Avoid (274).** LTS 4 is a saturated red, CIELAB chroma about 82
  against the LTS 3 amber's 65, so it is no longer the duller of the two.
  Avoid differs from it by more than hue: a near-black line on a coral-red
  casing (its own colour, not black or white), 1.3 times the width, the
  dash-dot, and a **cross-hatch** in the casing colour on its legend swatch and
  stress-bar segment (`.stress-seg-5` in `styles.css`, `--seg-accent`), a
  pattern no other tier has. The two-tone and colour-blind-friendly palettes
  take the same dashes and widths with their own colours; `cvd`'s Avoid sits on
  a light yellow casing (#f0e442), its own cue beside LTS 4's white. The legend
  swatches are 64 px (`LEGEND_SWATCH_PX`, 40 before), so each shows a whole dash
  cycle of every tier (the longest, Avoid with the switch on, is 52.5 px).
- **No odd dash lists (279).** LTS 1 is `dash: null`, not `[1]`. A one-entry
  list is odd, MapLibre and SVG repeat it, and the legend's swatch drew `[1]`
  dashed. A test forbids any odd list. Each facility's pattern is its own over
  every tier: the solid casing lies between the rail and the tier line, so a
  rail never shows through a tier's gaps.
- **Gap harshness (292).** A dash's gaps show the casing under it. Harshness
  is the gap share times the casing's contrast with the line
  (`gapHarshness`). LTS 3's old `[2, 1]` over a near-black #2b1a05 scored 1.51
  against LTS 4's 0.67, which is the black the owner found too harsh. Now its
  gap is 0.4 of the width over a mid-dark amber-brown, #45290a, which gives
  0.60, while the amber stays 3.60:1 on its casing and the casing 12.0:1 on the
  base map. `stressSalience.test.ts` holds harshness non-decreasing from LTS 3
  to LTS 4 to Avoid in every palette, plain and strong. To make that hold in
  two-tone, its LTS 4 casing moved from #d42020 to #c81e1e. **LTS 2 is not held
  to the rule:** its 0.90 (1.33 with the switch on) is harsher than LTS 3's.
  That is reported, not enforced, because fixing it means changing LTS 2. The
  owner accepted it as built (297).
- **The High contrast switch** still widens every line by half a pixel and
  every casing by a pixel more. Since 292 it pushes only the calm tiers'
  casings (LTS 1 and 2) to black or white. A busy tier's casing, which is what
  its gaps show, is left as it is: black under LTS 3 would score 0.97 against
  LTS 4's 0.67. Avoid's coral is its cue. The owner accepted this too (297).
  With the switch on, the busy tiers' lines on their casings are LTS 3 3.60:1,
  LTS 4 6.05:1 and Avoid 5.04:1 (`cvd` 3.83, 12.66 and 14.93; two-tone, reported
  only, 1.46, 2.34 and 3.62), all over the 3:1 floor where it is held.

**The facility rails (276, 277, 290).** Each facility is a pair of rails, one
either side of the tier's casing, so the tier's own colour and dash are left
alone. Shape comes first and colour second:

| Facility | Colour | Rail, each side | Pattern | Legend label |
| --- | --- | --- | --- | --- |
| Path | #4c1d95 | 2.5 px | solid | Off-road bike path |
| Protected | #a21caf | 4 px | blocks like posts, [0.3, 0.3] | Protected bike lane |
| Painted | #9370f0 | 1 px (1.5 px with the switch on) | sparse dots, [0.14, 0.4] | Painted lane (no separation) |

- Painted is the weakest cue (277): it is the thinnest rail in both modes,
  sparse, and at the lowest contrast that still meets 3:1 (3.26:1 on the base
  map, held below 3.5:1). It is drawn lowest (`FACILITY_DRAW_ORDER`: lane,
  protected, path) and listed last. The rails' colours are at least 15
  CIEDE2000 from every stress colour, the route blue and the unrated greys.
  Under protanopia and deuteranopia the violet comes close to the route blue,
  so the shape carries the difference there.
- The path rail is 2.5 px, not the protected lane's 4 px. Drawn at 4 px, a
  trail network read as double-outlined and heavier than the streets.
- **Unpaved (280, 290 (a)).** The path rails' filter leaves out a feature with
  `unpaved == true`, so an unpaved trail is never drawn like a protected path.
  A missing `unpaved` means an unknown surface, and that keeps its rails.
  Unpaved roads and trails get a dotted centre mark (`UNPAVED_DASH` `[1, 1.2]`,
  `unpavedWidth`: 0.4 of the line, at least 1.5 px) in the tier's unpaved
  casing, drawn over the line. The mark is not drawn where the line is faint
  or on alleys. The legend has an Unpaved entry, which says an unpaved trail
  has no path edges. The tiles carry `unpaved` but no `is_rough`.
- **Mountain-bike trails (452a, 454).** Drawn, while the "Mountain-bike
  trails" map layer is on (454, below), in a not-for-routes look of their
  own (the owner: "I want people to know where the trails
  are, but make them clear that it's not routing."; this supersedes 452's
  hiding and 290 (b)'s faint drawing). The stress tiles mark the class with
  `mtb` (true or left out; `segment.mtb_only`, written for
  `routemaker.trailaccess.MTB` and rated singletrack, which was hidden until
  456 and is now drawn where only its rating closes it: next bullet).
  `stressFilters` puts `mtbHides` (`["!=", ["get", "mtb"], true]`) into every
  routable layer's filter, right after the ride time's drawn-at clause, and
  the one layer `mtb-trail` (`mtbTrailLayers`, the bottom of
  `stressOverlayLayers`, `minzoom` 14) draws them: `MTB_TRAIL`, a 1.5 px
  #5f6368 line of fine dots (dash [1, 2]), no casing or rails; 2 px #4b5260
  with the accessibility switch (`mtbTrailPaint`, which `setStressPalette`
  re-applies). The dots carry the meaning; the grey is 3:1 or more from every
  base map surface (mtbTrail.test.ts). `MTB_TRAILS_ROUTABLE` (false) /
  `routableMtb` is the switch a future MTB mode turns on: the class moves back
  into the routable layers and `mtb-trail` draws nothing. The Mass Ride layers'
  `isRoad` leaves `mtb` out; the routable stress layers stay hidden there, but
  `mtb-trail` follows its own switch and keeps its filter without `massHides`
  (nearly every trail row carries a capacity), and the Mass Ride legend gets
  its row too (`MtbTrailLegend`). The tiles' `rough` is a rough surface, not this class. The
  legend has a row for it in the "Traffic stress legend" list (`MTB_LEGEND`,
  `MtbTrailSwatch`: the dots on the base map's earth colour, aria-hidden), and
  the road panel (`core.segment_info`, `is_mtb_trail`) says "Mountain-bike
  trail, not used for routes (Gravel and Mountain Goat may use it)" and, in
  `choose()`, prefers a normal drawn way within `DRAWN_PREFERENCE_M` to a
  nearer mountain-bike trail. Routing is unchanged: Gravel and Mountain Goat
  ride the class on the off-road graph, and their route draws over the dots.
  Since 454 the line is an optional map layer, off until the rider turns it on:
  the "Mountain-bike trails" switch under "Trails and terrain" in the Map
  layers sheet (`lib/mtbTrailsSwitch.ts`; `stressStyle.js` `mtbTrailsOn`,
  `setMtbTrails`, kept per browser under `routemaker.mtbTrails`, "on" or
  "off"). `overlayLayerShown` shows `mtb-trail` by that switch alone, with the
  stress map on or off and in every ride type, Mass Ride too; MapView sets the
  visibility again in place when it changes. The legend row shows only while
  the layer is on. The road panel answers from the segment table, so it still
  describes a mountain-bike trail with the layer off; its Bike access line
  says the dotted line is drawn "when the Mountain-bike trails map layer is
  on". docs/MTB-TOPO-PLAN.md has the
  rest of the mountain-bike and topo work.
- **Mountain-bike levels (456, 456a-c; MTB-TOPO-PLAN slice 2).** The tiles
  carry `mtb_level` (1-4, left out when null; `segment.mtb_level` from
  `routemaker.singletrack.mtb_level`, the higher of `mtb:scale` and
  `mtb:scale:imba`, 0 being no level, 456b). `MTB_LEVELS` in `stressStyle.js`
  holds each level's colour, name, dash (in line widths) and pattern words;
  `mtbTrailLayers` adds, after the grey dots (now filtered to the trails with
  no `mtb_level`), `mtb-level-casing-1..4` (the shared dark cross-ticks,
  `MTB_LEVEL.tick` in `MTB_LEVEL.tickDash`; 452a) and then
  `mtb-level-1..4` (`mtbLevelPaint`), all from zoom 14 and all in
  `MTB_LAYER_IDS`, which `overlayLayerShown` (`isMtbLayerId`) shows by the
  layer's switch alone and the Mass Ride filter leaves without `massHides`.
  `setStressPalette` re-applies the widths with the accessibility switch.
  The legend adds a row a level after the dots' row (`mtbLevelLegend`,
  `MtbLevelSwatch`, aria-hidden swatch; "Level 2 (blue)" then the rating,
  colour and pattern in words), in the Mass Ride legend too. The road panel
  (`core.segment_info`, `mtb_summary`, `MTB_LEVEL_COLOURS`, held equal to the
  front end's names by a test) says "Mountain-bike trail, level 2 (blue), not
  used for routes" and adds a "Mountain-bike difficulty" row under Riding.
  The rebuild draws rated singletrack (`map_class` road, with `mtb`) where
  nothing but its rating closes it (`pipeline.trail_closures.drawn_singletrack`),
  and hides the rest as before. mtbLevels.test.ts holds each colour at 3:1
  from the base map (`testSupport/baseSurfaces.ts`, shared with
  mtbTrail.test.ts), each pattern distinct from the others and from every
  other line pattern on the map, every level unlike every stress tier on
  dash (gaps 1.5 widths or more) and edge (ticks against a solid casing,
  in every palette), and the filters. The rebuild writes `mtb_level` on rated singletrack
  only (`pipeline.trail_closures.mtb_level`). Since v0.6.0 (the owner could
  hardly see them) every trail is a 3 px line on a solid white edge
  (`MTB_HALO`; `mtb-trail-casing`, `mtb-level-casing-1..4`), unrated as grey
  dashes, over one shared layer of dark cross-ticks (`mtb-trail-ticks`,
  `MTB_TICKS`; LTS 4's casing is white, so the ticks are the 452a mark).
- **Major trail names (2026-10-21).** The owner: "Major off road bike trails
  like the Metropolitan Branch Trail should be named on the map." The tiles
  carry `trail_name` (`core.stress_tiles.trail_name_rule`, format 11) on a
  traffic-free path that clears the z11 long-trails bar (`Z11_LONG_TRAILS`:
  a long walking or regional-or-larger bicycle route, or a named run of
  2.5 mi, 5 mi unpaved), from z12, from a table with the long-trail
  columns; `segment.trail_name` is the way's name, else its route's. The
  `trail-name` symbol layer (`stressStyle.js`, `trailLabelLayers`,
  `TRAIL_LABEL`) draws it along the line from zoom 12 in the street names'
  face, size and halo, in the path rail's purple (`#4c1d95`, 10.9:1;
  `#2e1065` with the accessibility switch), under the base map's labels so
  street and station names win; MapView sets 20 px and the shortened field
  (`rideTrailLabelField`) in a ride and puts the climbs under it. The base
  map's own path names (z15+, kind `path`) take the same purple
  (`roadLabelPaint`).
- **Unpaved in brown (302).** An unpaved road or trail is drawn in one brown
  ramp instead of the stress hues, light to dark from LTS 1 to Avoid, with the
  tier's own dash and width, so the stress still reads without colour
  (`UNPAVED_PALETTES`; on the overlay and the route's sections). The dotted mark
  stays as the cue that is not colour at all, and the legend row reads "Brown,
  darker = busier".

  | Palette | LTS 1 | LTS 2 | LTS 3 | LTS 4 | Avoid | Casings |
  | --- | --- | --- | --- | --- | --- | --- |
  | twotone (default) | #e6dad4 | #c2a698 | #7d604b | #53392a | #2b1c14 | LTS 1 #33231a, LTS 2 #1a2638 (gaps #7a8fa3), LTS 3 up #f6ead2 |
  | blended | #ebddd1 | #ac9888 | #7b6250 | #543e2c | #2e2118 | LTS 1 #3b2410, LTS 2 #1a2638 (gaps #7a8fa3), LTS 3 up #f6ead2 |
  | cvd | #e0c68a | #bc9a52 | #7a6046 | #544018 | #2a200c | LTS 1 #2a200c, LTS 2 #2a200c (gaps #7a8fa3), LTS 3 up #f6ead2 |

  Since 350 the warm ramp is a sepia (L* 88.9, 64.2, 43.5, 28.1, 14.0), two-tone's
  LTS 1 a paler taupe and `cvd`'s LTS 3 a duller brown, so that paved LTS 3 is 20
  CIEDE2000 or more from every unpaved step under normal vision, and 10 or more
  under every vision, in every palette, plain and strong (the closest: warm's
  amber against its LTS 2, 20.8; two-tone's yellow against its LTS 1, 25.7, and
  15.2 under tritanopia; `cvd`'s orange against its LTS 3, 21.3, and 12.5 under
  protanopia, where the ochre #7e6028 was 4.5). Every step is 1.5:1 or more in
  lightness and 10 or more CIEDE2000 from the last under every vision, and every
  tier is 3:1 or more on every base-map surface (the worst is the unpaved LTS 3,
  3.32 to 3.42:1). Gap harshness rises from LTS 1 (0, 0.21 to 0.25, 0.79 to 0.82,
  0.92 to 0.99, 3.49 to 3.67), 292's rule from LTS 1 up since 356. Two-tone uses a greyer taupe, because its paved LTS 3 is a
  yellow a warm tan would sit on; `cvd` uses an ochre-olive on the yellow side
  of the blue-yellow axis. **Weak spot:** under deuteranopia unpaved LTS 1 and
  2 are only about 5 to 6 CIEDE2000 from the paved green LTS 1 and 2; the
  dotted mark tells them apart there. Each `stress_spans` entry of a route
  says `unpaved` (true, false or null), and a section ends where the surface
  changes. The preview is ~/rmdata/demo/stress-salience-preview.html
  (r1's is kept as stress-salience-preview-r1.html).

### The default palette (351), LTS 2's blue edge (356, 357) and the unpaved ramps (350)

The owner, on the warm palette's LTS 3 beside the brown unpaved ramp: "LTS3 looks
unpaved" (350), then "2 tone is better", "Make two-tone the default" (351). The
default is `twotone` in the owner's colours; `blended` stays as `?palette=warm`,
and the switch's palette is still `cvd`. The rules still apply on top, and where
the owner's colours break one the break is reported, not fixed (351: "If two-tone's
colours break any of them, report it rather than silently changing the owner's
choice"). `frontend/src/testSupport/defaultConflicts.ts` lists them, and
`frontend/src/defaultPalette.test.ts` holds the default to every other rule and to
exactly these breaks (one more fails, and so does one fewer):

| Tier | Line | Edge (casing) | Gaps | Harshness | Worst on the base map |
| --- | --- | --- | --- | --- | --- |
| LTS 1 | #9ed3ac | #2f5d47 | (solid) | 0 | 4.42:1 |
| LTS 2 | #57a06c | #1a2638 | #7a8fa3 | 0.21 | 4.82:1 |
| LTS 3 | #f3c81a | #f28c28, ringed #1c1917 | the edge | 0.25 | 7.13:1 |
| LTS 4 | #f28c28 | #c81e1e, ringed #1c1917 | the edge | 0.26 | 3.05:1 |
| Avoid | #d42020 | #111111 | the edge | 0.97 | 3.20:1 |

**371** (the owner, on the final preview: "Apply both"): the near-black ring and the
yellow #f3c81a are applied. The ring (#1c1917, a pixel outside the edge) is drawn on the
map (`ringLayers`, under the rest of the overlay, paved roads only, not at the faint
zooms), round the route's sections (`route-ring`) and in both legends; Avoid gets a
legend-only grey ring (#9aa0a6, `legendRing`), 3:1 on the dark soft panel. Two-tone's
unpaved LTS 1 moved to #e6dad4 to stay 15 from the lighter yellow. What the ring mends and
what it does not, item by item below: 3:1 on the base map (mended), LTS 3-4 for a
deuteranope (mended by the yellow, 1.44:1), Avoid on the dark panel (mended by the legend
ring); greyscale order, 274's salience and Avoid against LTS 4 under deuteranopia are left,
with the line on its own edge inside the ring (1.53:1, 2.34:1).

The release re-check (accessibility) added three to the record, and one fix:

- **Paved and unpaved of the same tier** (SF-A): two-tone LTS 2 was one colour to a
  deuteranope (2.1 CIEDE2000, 1.01:1). Its unpaved brown moved from #ac8b73 to #c2a698
  (9.1 from the approved value, inside 363's 10), so the pair is 10.5 apart under every
  vision. `unpavedBrown.test.ts` now holds every same-tier pair, in every palette, to 10
  under every vision, but for the pairs listed in `defaultConflicts.ts`
  (`unpavedSameTierClose`), where the dotted mark carries it: two-tone LTS 1 (8.0
  deutan); warm LTS 1 (7.3), LTS 2 (6.1), LTS 4 (9.3), Avoid (8.0); cool LTS 4 (4.4).
- **LTS 3 against LTS 4 for a deuteranope** (N-B): 1.44:1 in luminance, over the floor,
  but 9.2 CIEDE2000 (13.7 protan), the weakest colour-blind pair in the default.
- **LTS 3's dash gaps** (N-E) show the orange edge, 1.53:1 from the yellow, so the dash,
  LTS 3's cue that is not colour, is faint for low vision in the default. An owner trade
  (292, 351, 371); the cool palette has no such gap.

What two-tone breaks, as first reported for 351, with the smallest tweak proposed:

- **3:1 (WCAG 1.4.11), LTS 3 and LTS 4.** The yellow on its orange edge is 1.46:1
  and the orange on its red edge 2.34:1, and neither the line nor the edge is 3:1
  on the light base map, the light panel or the route halo. Smallest tweak: a 1 px
  near-black ring outside the edge (as the faint roads have), which keeps both of
  the owner's colours; or darken LTS 3's edge to an orange-brown, which brings the
  350 look back.
- **Greyscale order.** LTS 3 (Y 0.575) is the lightest tier and LTS 4 (0.378) is
  lighter than LTS 2 (0.283); every neighbour is still 1.4:1 or more apart, so a
  print tells them apart but does not order them. No small tweak: it is the
  yellow-and-orange reading itself.
- **LTS 3 against LTS 4 for a deuteranope**, 1.38:1 in luminance, under 1.4:1.
  Smallest tweak: a slightly lighter yellow, #f3c81a (1.44:1, 3.6 CIEDE2000 from
  #f2c21b).
- **274's salience.** LTS 4's orange (CIELAB chroma 72.5) is less saturated than
  LTS 3's yellow (78.7); LTS 4 is still more contrasting on the base map, and its
  dash and width are heavier. Tweak: a more saturated orange-red for LTS 4, which
  changes the owner's colour, so not proposed as small.
- **Avoid against LTS 4**, 17.8 CIEDE2000 under deuteranopia (the warm palette is
  held to 20); the dash-dot, the width and the near-black edge still differ.
- **Avoid on the dark theme's soft panel** (#262a32), 2.76:1, in the legend only.
  Tweak: a light outline on the dark theme's legend swatch.
- **LTS 4's edge** is #c81e1e, which 292 chose, not the #d42020 351's text lists:
  with #d42020 LTS 3's gaps (0.24) would be harsher than LTS 4's (0.24 against
  0.237).
- **The Mass Ride orange** (#f28e2b, 327) is 0.5 CIEDE2000 from LTS 3's edge and
  LTS 4's line (#f28c28): the same colour. Where Mass Ride's capacity map (325-334)
  is built it replaces the stress colours in that mode, so the two do not meet on
  one map; until then it is a note for that work. The junction marker's orange
  (#f59e0b) is 13.4 from LTS 3's yellow under normal vision, 5.1 under
  deuteranopia; the marker's triangle and dark outline carry it there.

**LTS 2's edge and gaps (356, 357).** "For Lts 2 maybe use a blue instead of black.
Especially unpaved, LTS2 can almost be harsher than LTS3." and, on the sketch,
"Good!". LTS 2's edge is a dark slate blue, #1a2638, paved and unpaved, which the
switch keeps (the cool palette's paved LTS 2 keeps its navy and its unpaved one its
brown), and its gaps a steel blue, #7a8fa3, drawn as a line of their own between the
casing and the dashes (`gapLayers`, layer `stress-gap-2`, and the legend's swatch;
the cool palette's paved one is a pale grey-blue, #a7b4c1). Paved LTS 1's edge is a
softer green, #2f5d47. The sketch's #5f7d99 could not be used as it was: as the edge
it leaves LTS 2 2.4:1 on the base map (3:1 needs a dark ring), and as the gap it is
15.4 CIEDE2000 from the route blue and would make LTS 2's gaps (0.27) harsher than
two-tone LTS 3's (0.24); the gap chosen is 7.6 from it, 22.6 from the route blue and
19 L* lighter, and the edge 23.8 from it and 24 L* darker. The 292 rule now runs
from LTS 1 up: gap harshness never falls as stress rises, paved and unpaved, in every
palette, plain and strong (`stressSalience.test.ts`, `unpavedBrown.test.ts`). The
trade: LTS 2's green and its steel-blue gaps are 1.06:1 apart in lightness, so in
greyscale its dashes are faint, and LTS 2 is told from LTS 1 by its width and edge
more than its dash. The unrated route class has a halo of its own, #202326
(`UNRATED_HALO` in `lib/routeColours.ts`): LTS 1's softer edge
left the grey at 2.86:1.
- The facility bar takes its colours and patterns from the rails
  (`.facility-seg-*`). Its old green, blue and amber collided with the stress
  colours.

**Painted lanes on high-stress roads (275).** A switch, "Show bike lanes on
high-stress roads" (`role="switch"`, after the High contrast switch), is off by
default and remembered as `routemaker.highStressLanes`. While it is off:
- the painted-lane layer leaves out tiers 4 and 5 (`HIGH_STRESS_LANE_MIN_TIER`);
- the facility bar counts a painted lane on LTS 4 or Avoid as no facility;
- the description drops ", painted bike lane" from a stretch whose lane is
  entirely on LTS 4 or Avoid. The API marks such a stretch with
  `text_lanes_hidden`. An overview merge of an LTS 3 lane with an LTS 4 one
  keeps its words, matching the bar. The front end strips the words itself
  only for an older API.

Protected lanes and paths show at every tier. `tests/test_describe.py`
(`TestFrontEndAgrees`) ties the front end's `PAINTED_LANE_WORDS` and
`HIGH_STRESS_LANE_MIN_TIER` to the backend's words and tiers.

**The route line.** The route's sections widen with the class too
(`ROUTE_SECTION_WIDTHS`: traffic-free and LTS 1 4 px, LTS 2 4.5, LTS 3 5,
LTS 4 5.5, Avoid 6, unrated 5). Each has a halo a pixel wider each side
(`ROUTE_HALO_EXTRA`), and the route's casing is 11 px (`ROUTE_CASING_WIDTH`,
9 px before), so the blue still shows round the widest halo. Avoid's halo is
its coral casing, the one exception to "dark under light, white under dark"
(the test asserts it is that palette's own casing and at least 3:1).

**The route's corridor.** The sections take the map's own colours (a Mass
Ride's the capacity bands' colours, widths and dashes, the same as the roads
under them), so the 11 px casing left the route reading as one more road
(Stephen, 2026-10-12). A route in sections is drawn as a corridor
(`routeCorridorPaint`): a 16 px white band (`route-band`) inside a 22 px
casing in the route's blue (the dark slate in the colour-blind-friendly
palette), about 3 px of each round the widest halo. Every class's edge on the
white is 3:1 (its ring, its halo, or the section itself where a light halo
merges into the band). A one-colour route keeps its 11 px white casing.

Under a route the overlay's lines fade (`overlayFade`): to 0.45 under a Mass
Ride's capacity route (`MASS_NETWORK_DIMMED`), to 0.8 under any other
(`ROUTE_OVERLAY_FADE`; Stephen: "mute most of the colors when there's a
route, for default too"). The fade multiplies each layer's own opacity
(`fadedOpacity` scales a zoom step's outputs, so the zoom fades stay); Avoid
roads fade too (the route will not ride them); the hazard rails and the trail
names keep full strength (`keptUnderRoute`).
With the High contrast switch on there is no fade, since the overlay's 3:1
edges are measured at its own opacities. `lib/routeCorridor.test.ts` holds
the widths, the contrasts, the fade and the wiring.

**Tests.** `stressSalience.test.ts` covers: the rising ink and width, LTS 4's
duty, chroma and contrast rising from LTS 3 to Avoid, the harshness rule, no
black under LTS 3, LTS 2 against LTS 3 by dash length, period and width, the
rails' patterns, widths, contrast and order. Also: `stressPatterns.test.ts` (no
odd dash list, the legend's dash the map's, each facility's pattern over every
tier and under the switch, the unpaved mark and the path rail left off unpaved
trails at every tier and ride time, the rail widths),
`stressContrast.test.ts` (3:1 for every tier, plain and strong), the a11y
harness's 8 checks of the lane switch (`scripts/a11y/check.mjs`), and
`tests/test_describe.py` for `text_lanes_hidden` and `surface`. The mutants are
`scripts/mutants_salience.py` (`--check`, `--runner`): the salience
developer's r0 and r1 mutants, first run ad hoc, the release review's seams, and
new ones for the legend, `cvd` Avoid's casing, the brown unpaved ramp (302) and
the credits (301). The front-end ones are 71 of 71 killed; the Python ones need a
`PGDATABASE`.

### The federal-land overlay (items 236-239, the map part)

PLAN.md FOLLOWUP-FEDERAL-LAYER. The Mass Ride map shades the land under federal
control, as information and not legal advice: ownership is not police
jurisdiction. The routing and description half of item 239 (stops inside federal
land, the parkway stretches) is the next section.

* **Data.** `scripts/build_federal_land.py` merges the National Parks, Reservations
  and Military Bases layers (fetched once each, records in
  `fixtures/datasets/README.md`) and the Architect of the Capitol polygon
  (`fixtures/cbd`) into `frontend/src/federal-data/federal-land.json`, GeoJSON with
  `kind` (`nps`, `reservation`, `military`, `capitol`; `federal` is reserved for a
  Federal Land layer that was not downloaded), `name` and, where the source names
  one, `agency`. Run it with the shapely virtualenv; the output is reproducible byte
  for byte. It is named `.json` so the edge serves and compresses it as JSON, and
  Vite emits it as a hashed `/assets/` file (`?url`), which the existing Caddy
  matcher, deploy copy and cache rules already cover.
* **Layers** (`lib/federalLand.ts`). A tint (10%), an 8 by 8 pixel pattern per kind
  at 45% (`fill-pattern`, the tiles drawn in code), and one outline layer per kind
  with its own dash. They are added once, hidden or shown, directly under the first
  stress-overlay layer when it is on the map, else under the base map's first label,
  so they sit under the stress lines, the stations and the route whichever is added
  first. No map labels: the cue is the pattern, the outline and the legend and
  popup names.
* **Colour plus a cue.** `FEDERAL_STYLE` gives each kind a colour, a pattern (dots,
  cross-hatch, rising stripes, falling stripes, horizontal stripes), an outline
  dash and the pattern's name in words; the legend (`lib/federalLegend.ts`) draws the
  map's own pixels in an SVG swatch and says "shaded with ...". A test holds every
  colour, pattern and dash distinct.
* **Mass Ride only.** `federalShown(preset, switch)` is true only for `mass-ride`
  with the panel's switch on (default on); `App` gives `MapView` that as
  `federalVisible` and renders the `FederalLandSection` for a Mass Ride alone.
  `MapView` fetches the file the first time it is shown, never otherwise, and
  hides the layers (without removing them) when it goes off; a failed fetch leaves
  the overlay off and the panel says so ("Federal land shading is unavailable for
  now"), and asking again retries.
* **The popup** (`federalInteraction.ts`). A click or tap on a shaded area opens a
  card (name, kind, "Managed by: agency" where known, and "Federal land - permit
  rules may differ (information, not legal advice)."). It is information beside the
  planner's own click, not instead of it: the click still adds a point as it always
  does, so the planner's tap keeps one meaning. It closes on the next click, its
  button and Escape, and stays out of the way while another card is open.
* **Credit.** `FEDERAL_CREDITS` in `lib/mapStyle.ts` (CC BY 4.0, adapted), on every
  map view; docs/OPERATIONS.md, "Licences, and the credits every map must carry".

Tests: `lib/federalLand.test.ts` (Mass Ride only, colour plus cue, loading,
layer order and visibility on a stand-in map, popup text, the rendered legend and
section, the checked-in file, the credit), `tests/test_build_federal_land.py` (the
build's rules on synthetic layers, the script's output, the checked-in file's
validity and a few known places), and the browser check section 9 of
`scripts/a11y/check.mjs` (`scripts/a11y/run.sh`: the section, switch, legend at 320
px with text spacing, and no section and no fetch for another ride type).
`scripts/mutants_federal.py` runs 36 mutants against them.

### Federal stops and parkways (item 239, the routing part)

PLAN.md FOLLOWUP-FEDERAL-LAYER, "Still to do". On a Mass Ride, the places the group
stops on federal land and the stretches it rides on a National Park Service parkway,
in the map, the points list, the route description and the road panel. All of it is
`frontend/src/lib/federalStops.ts`; every other ride type is unchanged.

* **Client side, not the API.** The overlay's file is already in the page for a Mass
  Ride (MapView fetches it whatever the shading switch says, `federalWanted`), and
  `federalLand.ts` already had the point-in-polygon test. Reading the same file on the
  server would mean shipping a front-end asset into the api image, a second parser
  and a new field on the route answer, for the same answer; the points list and the
  markers need it before any route is planned anyway. So the stops and the parkway
  test run in the browser, with a bounding box per area cached so a point is tested
  against only the few areas near it. The cost: the description lines are worded in
  `federalStops.ts`, not `describe.py`, so they are placed before the API's entries
  rather than among them, and they come only once the file has loaded. Until then, or
  if it cannot be had, a Mass Ride's description, copied text, cue sheet and GPX
  description carry one line instead, "Federal land could not be checked for this
  route." (`FEDERAL_UNCHECKED`, `federalRouteLines`).
* **Stops** (239 (b)). `federalAreaAt` (`federalLand.ts`, which `federalPoints` uses
  too) gives a point's most specific area (FEDERAL_KINDS order) with its agency; failing
  that, the most specific area whose outer edge is within `FEDERAL_EDGE_M`, 66 ft (20 m),
  marked `near` and said "next to" (238: "err on the side of flagging", for a stop on a
  simplified boundary). `stopWarning` says "End is inside U.S.
  Capitol grounds, managed by Architect of the Capitol – federal land: check permit
  requirements for gathering here." Where the data names no agency (Military Bases)
  the kind is said instead ("Fort Leslie J. McNair (Military installation)"), never an
  invented manager. The start, the end and every Stop N are checked. The planner has
  no separate regroup or staging point: a regroup is planned as a stop, so it is a
  Stop N here.
* **Riding through** (239 (c)). A stretch on an ordinary city street inside an area is
  not warned.
* **Parkways** (239 (d)). `PARKWAYS` lists the five the owner named. A description
  stretch is on one when its OpenStreetMap street name matches it ("Rock Creek and
  Potomac Parkway Northwest", "Rock Creek Parkway", "Clara Barton Parkway", ...), or
  when it is an unnamed or parkway-named road stretch with two of its quarter points
  inside the NPS layer's polygon of that parkway (only those inside the District are in
  that layer). Unnamed means the API's own words, `describe.py` `UNNAMED_ROAD` ("unnamed
  road") and `UNTRACED_STREET` ("this part of the route"), which `federalStops.ts` repeats
  and `tests/test_describe.py` holds equal. A path is never a federal road, by name or by
  polygon: a stretch with `facility` "path" or the street "unnamed path" is skipped
  (Rock Creek's trail is inside the parkway's polygon, and a "Suitland Parkway Trail"
  matches the parkway's name).
  Stretches on one parkway less than `PARKWAY_JOIN_M` (525 ft, 160 m) apart are one run, said
  as "1.9 to 2.2 mi (3.0 to 3.6 km): Rock Creek and Potomac Pkwy, a National Park
  Service parkway – federal road: check permit requirements for riding it as a group."
  OpenStreetMap's `operator` tag is not in the routing data (the segments carry the
  name, not the operator), so it is not read; adding it is a pipeline change for a
  rebuild.
* **Where it shows.**
  - *The map:* a marker for a point on federal land has the class `pin-federal`, a
    square "!" badge at its corner (a shape, not only a colour), and the warning in its
    accessible name and title (`MapView` `pointWarnings`, part of `markerDeps`).
  - *The points list:* the row gets the warning on a line of its own with the same
    badge (`PointsList` `warnings`), before Remove in the reading order. The planner's
    separate list of points on federal land is gone (the rows say it); the planner
    still says "None of your points is on federal land." when none is, and the Map
    layers sheet keeps its list and says what the badge means (`FEDERAL_BADGE`).
  - *The description:* `federalLines` (a heading line that says it is information, not
    legal advice, and that federal ownership is not police jurisdiction; the stops; the
    parkway runs) is listed under its heading before the steps in Directions, and is in
    the copied text, the downloaded cue sheet and the GPX file's description
    (`descriptionText`, `gpxDescriptionText`, `exportOf`). Nothing is said when there is
    nothing to say. The GPX description keeps the lines where the API gave no entries,
    and counts them when it chooses the full text or the overview (`GPX_FULL_MAX_CHARS`).
  - *The road panel:* the keyboard's and screen reader's way to ask what a shaded area
    is. "Road info at map center" (I on the map) and a right-click or long press, on a
    Mass Ride, show "Federal land: Inside ... – federal land: check permit requirements
    for gathering here." with the caveat, whether or not a road is found, and the
    dialog's status sentence ends with it, said again if the data comes after the road's
    answer.
* **Units.** The run's range goes through `format.ts` `formatMileRange` (miles first,
  kilometres in brackets), as every unit does. For a short run it follows `describe.py`
  `range_words`' feet rule (under a tenth of a mile, where it starts and its length in
  feet), and it also uses feet where both ends round to the same tenth, which
  `range_words` does not check.

Tests: `lib/federalStops.test.ts` (the area and its words, the rows and markers only on
a Mass Ride with the data, the five parkways by name and nothing else, runs joined and
by the NPS layer with a path and a city street left out, the description, text and GPX
lines, the rendered row, the marker and road-panel wiring, the real file at Lafayette
Square, the Capitol and the Rock Creek and Potomac Parkway), and the browser check's
section "The Mass Ride's stops on federal land and its parkway stretches"
(`scripts/a11y/check.mjs`, 8 checks: the End row and marker at the Capitol and not the
Start, the Directions list and its name, I at the map's center over the Capitol and off
it, no warning on another ride type, and the row at 320 px with text spacing).

### The Mass Ride capacity map (FOLLOWUP-MASSRIDE-MAP part 1, items 325-327, 387)

"The focus is on carrying capacity, not LTS here ... The headline color should be riders per
minute." In Mass Ride mode the map and the route line are coloured by riders per minute, and the
LTS colours and the path, protected-lane and painted-lane rails are not drawn. Part 1 is the
capacity map; part 2 is the route chart (it needs the elevation chart, 322, 323) and part 3 is
the rider-marked hazards, which wait for the peer-review backend. Hazards are not built: the
seam is `hazardLayers()` in `frontend/src/massStyle.js` (an empty list, in its place in the draw
order), and nothing asks for hazards.

* **The model** (`src/routemaker/massflow.py`, the plan's headline throughput; the working
  model, OWNER-DECISIONS 394, sources pending FOLLOWUP-FLOW-CALIBRATION): riders a minute =
  60 x 0.37 riders per m2 x 0.7 utilisation x usable width x 1.9 m/s, so 29.5 riders a minute
  for every metre of usable width: 99 for an 11 ft (3.35 m) lane. The flat, straight,
  clear-road figure; the climbs, signals and surface of part 2 reduce it.
* **Usable width** (OWNER-DECISIONS 404; `massflow.usable_width_m`, one function; the table
  cases are `tests/test_mass_capacity.py` `TestTheDistrictsWidths`). The width a corked group
  has in the direction it rides. The corkers hold the cross streets at each junction, not the
  oncoming traffic, and a DC Bike Party keeps to its own side, so:
  - a two-way street gives the ride its own direction's travel lanes and the painted lane on
    its side (not the oncoming lanes, not a centre turn lane); a segment is drawn once for both
    directions, so it carries the NARROWER direction's width (a ride flows at its narrowest
    point; a divided road's carriageway is a one-way way and gets its own lanes);
  - a one-way street gives every travel lane and every painted lane running with it (a
    contraflow lane is not counted; a bare `cycleway=lane` on a one-way is one lane);
  - a street of one shared lane (DC's "bidirectional" lane, OSM `lanes=1` two-way) is the ride's;
  - parked cars are never usable width (404 (1)), and a painted lane beside parking keeps a door
    zone out, `DOOR_ZONE_M` 3.5 ft (1.07 m); no margin is taken beside a travel lane;
  - protected lanes are never usable (127).

  **In DC** (404 (3)) the way's Roadway Block records decide it (`WayFacts.block_facts`, handed
  over by `pipeline.run.write_segments`; the narrowest block along the way): lanes by direction
  times the block's lane width (`TOTALTRAVELLANEWIDTH` / `TOTALTRAVELLANES`, which the parser
  divides), plus the painted bike lanes at their width (5 ft where none), less door zones. DC
  records parking lanes apart from travel lanes, so the parked cars are out of that width by
  construction (curb to curb less parking). Reversible lanes count as ZERO (405, the safe,
  narrower reading): DC's `TOTALTRAVELLANESREVERSIBLE` is stale where the lanes were removed
  (Connecticut Ave NW's ended in 2020; DCist, 2021-12-15, credited in docs/SOURCES.md), so a
  block's reversible lanes count only where the reviewed allowlist
  (`settings.MASS_RIDE_DC_VERIFIED_REVERSIBLE_BLOCKS`, BLOCKKEYs, empty for now) names it, half
  (rounded down) to each direction, and never on a street in
  `MASS_RIDE_DC_ENDED_REVERSIBLE_STREETS` (Connecticut Ave NW). The 57 blocks DC still records
  as reversible (7.5 mi) are listed in reports/MASSRIDE-MAP-rev2.md (not in the repository) for the owner to check. A
  block recording a lane width of `MASS_RIDE_DC_WIDE_LANE_FT` (16 ft) or more and no parking lane
  (`parking_lanes` 0) is read at `MASS_RIDE_DC_WIDE_LANE_CAP_FT` (11 ft) a lane (407 (3): likely
  shared parking and driving lanes); 453 blocks, 25.4 mi. Both are `massflow.DcRules`. The
  classifier's LTS reading of DC lanes (179) counts reversible lanes in each direction
  (OWNER-DECISIONS 425, `agency_roads.classifier_reversible`), except on Connecticut Ave NW,
  whose lanes 412's override sets; the width keeps 405's zero. See "Reversible lanes and the
  reference LTS 4 road". Bus lanes are in DC's
  counts and are counted. A block with no
  lanes, or a lane width outside 6 to 20 ft, gives nothing and the way falls back to OSM.
  **Elsewhere**, and as that fallback: a mapped `width` (2.4 to 40 m, curb to curb) less the
  parked cars (`parking_width_m`: from `parking:<side>` or `parking:lane:<side>`, 8 ft (2.4 m) a
  side parallel, 4.5 m angled, 5 m end-on, half on the kerb half; none for `no`, `separate`,
  `on_kerb`, `street_side` and the no-parking values) and door zones, halved on a two-way way;
  otherwise the lanes in each direction (`lanes:forward`/`lanes:backward`, else half of `lanes`,
  else the classifier's through lanes a direction, else half the class default) times 11 ft,
  plus the painted lane on that side less a door zone where OSM says parking there.

  Worked examples, ft (m), riders a minute: DC two-way 2 + 2 lanes of 10.5 ft, parking both
  sides: 21 ft (6.40 m) a direction, 189. DC one lane each way of 8 ft between parked cars:
  8 ft (2.44 m), 72. DC one-way 3 lanes of 11 ft, no parking: 33 ft (10.06 m), 297. DC 10 ft
  lane and a 5 ft bike lane beside parking, each way: 10 + 5 - 3.5 = 11.5 ft (3.51 m), 103.
  Connecticut Ave NW north of Calvert St (1 + 1 and 2 reversible, 10 ft; before the 412 lane
  override): 10 ft (3.05 m), 90, the reversible lanes being zero (405). With the override, 3 + 3
  lanes less the part-time parking lane is 2 lanes of DC's 9 ft: 18 ft (5.49 m), 162. A DC lane of 18 ft with no parking: 11 ft, 99. A block with no lane
  width: OSM's, e.g. an untagged residential street, 11 ft (3.35 m), 99. OSM 30 ft curb-to-curb
  with `parking:both=lane`: (30 - 2 x 7.9) / 2 = 7.1 ft (2.17 m), 64.
* **One model with the elevation chart.** There is one `src/routemaker/flow.py`, the elevation
  chart's (the rebuild bundle dropped wip/massride-map's verbatim copy); `massflow` takes its
  constants, `level_riders_per_min` and band edges from it. The WIDTH is `massflow`'s: the
  column `segment.mass_usable_width_m` is the source of truth. The route chart reads it per
  piece (`core.routing.PieceClass.width_m`, `_flow_stretches(..., capacity=True)`), the route's
  coloured sections take their `rpm` from the same width, and the tiles' `rpm` too, so the
  chart, the route line and the map always agree. `flow.usable_width_m` is now only the
  estimate for a table built before the column, and reads one direction's lanes (406).
  The column is the flat-ground (level) figure only: the grade adjustment depends on direction
  and on distance into a climb, so the route chart applies it, not the tiles. The legend says
  "on the flat".
* **The column.** `segment.mass_usable_width_m real` (metres; `pipeline.schema.MASS_WIDTH_COLUMN`; revised
  from riders a minute on the coordinator's call: the column is physical width, and `routemaker.flow` turns it
  into riders when tiles and routes are served, so tuning the flow constants needs no rebuild and the map
  and chart cannot disagree), written by the segment writer for every row from the way's tags and the classifier's lanes
  (`pipeline.run.write_segments`), with the way's District blocks since 404: the width a ride
  has in its narrower direction, parked cars out. Nullable: a table built before it has none,
  and nothing breaks.
* **The tile property** (`core.stress_tiles`): `rpm`, an optional property in the same way as
  `facility` and the long-trail columns (`OPTIONAL_PROPERTIES`), computed in the tile SQL from the width and `flow`'s constant (`RPM_PER_METRE_SQL`), rounded down to a multiple of 10
  (`RPM_STEP`) so the band edges (60, 120, 200) never move and the zoomed-out levels, which merge
  every segment of one value into one feature, are not split a feature per integer. ETag letter
  `w` (`r` is the rough surface's; the tag is `+kcfrmwoesbtl` on a full table). FORMAT_VERSION 7
  (the rebuild bundle).
* **The VALIDATE_SEGMENTS sentinel** (`pipeline.mass_capacity`, `pipeline.run.assert_mass_capacity`): at
  least 98% of the road rows and of the path rows carry a figure; no road row is under 44 or over
  1,181 riders a minute; and the median road lies in `settings.REBUILD_MASS_CAPACITY_MEDIAN_RANGE`,
  60 to 200 since 404 (90 to 260 while a two-way street counted both directions; a model in the
  wrong units, or with a zero constant, is a refused build). The tests'
  toy extracts set the median range wide (`tests/conftest.py`).
* **The route.** `core.routing.classify` reads the column where the live table has it
  (`PieceClass.rpm`), and for a Mass Ride `stress_spans` ends a section where the capacity changes
  band and gives each `rpm`, the lowest along it (a stretch marked Avoid is one section with null).
  Another ride type, and a table without the column, carry no figures, and the route is drawn by
  stress as it was. A section folded away for being under 10 m does not lower its neighbour's
  figure, so a section's figure always lies in the band its colour says.
* **The front end.** `frontend/src/massStyle.js` (bands, layers, filters), `lib/massCapacity.ts`
  (the narrowest point, the shares, the words), `lib/massLegend.ts` (the legend and the route's
  list), and the route line's classes in `lib/routeColours.ts` (`m0` to `m3`, `mavoid`; the dashed
  ones have a layer of their own each, `lib/mapGlue.ts` `routeDashLayers`). The capacity layers
  are on the map always and drawn only in Mass Ride mode (`setMassMode`), from the Mass Ride
  tiles below, not the stress tiles. In that mode EVERY stress-map layer is hidden, at every zoom
  (`overlayLayerShown`; OWNER-DECISIONS 417: "Mass rides should mainly only show capacity and
  federal land. Trails and PBLs aren't relevant here."; 417a: "The major trail PBL etc should not
  be shown at any zoom in mass ride."): the LTS colours, the path, protected-lane and painted-lane
  rails, the trails and surface marks, the z7-11 long trails and the z12-13 ride layer's calm
  roads. The base map's `roads_labels_minor` names no path then (`MASS_PATH_LABEL_FILTER`: no
  trail-name labels); the base map itself, the federal-land overlay, the rail stations and the
  planned route with its markers stay. Every other ride type is unchanged. (`massHides` is still
  on the stress layers' filters in that mode; it no longer matters, as they are hidden.)
  **The fallback:** a table without the column gives empty Mass Ride tiles, so the capacity
  layers draw nothing, and the legend and panel (which learn it from the map, `watchForCapacity`,
  now from either tile set, and from the route's sections) are the stress ones, never an error;
  the map then shows no road colours at all in Mass Ride mode (the stress layers stay hidden).
  The bundle's rebuild writes the column, so this is only a table promoted before it.
* **The Mass Ride tiles** (`GET /tiles/mass/{z}/{x}/{y}.pbf`, `core.mass_tiles`; OWNER-DECISIONS
  415, 418). The stress tiles' z12-13 is the ride layer (391), which holds only the long calm
  roads, and the owner asked for the busy roads' capacity there too ("Busy roads should yes.").
  So the Mass Ride map has its own tile set, read only in that mode (`mapStyle.ts` `massSource`,
  source id `mass`; a source no visible layer reads fetches nothing, so the stress map never
  loads them and the Mass Ride map loads no stress tile past MapView's one probe). Layer
  `stress`, properties `tier` and `rpm` (the stress tiles' own `rpm` expression); every public
  road with a capacity, no trail, path or alley (`map_class = 'road'`, not trail class, facility
  not `path`). z10-13 merged by (tier, rpm) and simplified, as the stress tiles' zoomed-out
  levels; z14 one feature per segment, buffer 64; past z14 empty (the map draws z15-16 from z14).
  The stress tiles and their ride layer are unchanged, and so is their FORMAT_VERSION (7).
* **Focus by zoom** (421, 422: "Maybe focus on higher capacity roads at large zooms", "The focus
  option sounds good.", "Looks like a good start!"). z10-11: only Wide open (200 and up), and only
  a block in at least 0.5 mi (0.8 km) of continuous Wide open road, so the isolated blocks that
  pass 200 on a turn lane or a wide approach are not specks; z12-13: Good and Wide open (120 and
  up); z14 on: every band; Avoid at every zoom. The settings are `core.mass_tiles`
  (`WIDE_OPEN_RPM`, `GOOD_RPM`, `GOOD_MIN_ZOOM`, `EVERY_BAND_MIN_ZOOM`, `WIDE_RUN_MI`,
  `min_rpm_for`), mirrored by `massStyle.js` (`MASS_BANDS[].minzoom`, which the band layers carry
  too, `MASS_WIDE_RUN_MI`, `massBandsAt`); `tests/test_mass_tiles.py` holds them equal. **The run
  is computed in the tiles, not the pipeline:** the band is the tiles' own rounded `rpm`
  expression, so the run and the colour can never disagree; the District's Wide open road is
  small (about 74 mi, 120 km); only the ten z10-11 tiles over the District (4 at z10, 6 at z11) need it, and the
  pre-draw draws them; so no column, schema change or rebuild. A run is the total length of the
  Wide open lines (clipped as drawn) that share a vertex, `ST_ClusterDBSCAN(ST_Points(clipped), 0, 1)`
  (so a run goes on through a junction, OWNER-DECISIONS 423, and not across a bridge over a road),
  found over the whole District in each z10-11 tile's query (the `wide`, `clustered` and
  `in_run` CTEs), so a tile's edge never cuts a run. Measured read-only on the live table with a
  stand-in width: z10 0.7-0.8 s warm (5.5 s the very first, cold), z11 0.45-0.6 s, z12 0.26 s.
  **In words** (`lib/massCapacity.ts` `massBandsSaid`): the legend has one persistent
  `role="status"` line (`.mass-bands`, as the federal-land section's status) whose words name
  the bands shown, the floor and the run, and what zooming in adds; they change only when the
  set of bands changes, so zooming within a level says nothing. With the Map layers sheet off
  screen, a change of bands is said through the app's polite region instead (`App.tsx`,
  `massBandsChangeSaid`), and never on arriving at the map or switching the colours on.
* **Border roads** (420: "Border roads are inside DC"). Western, Eastern and Southern Ave run
  along the line, and the boundary is simplified to about 30 ft, so a point within
  `DC_EDGE_TOLERANCE_M`, 22 m (72 ft), of the District counts as inside: the simplification's
  error (0.0001 degree, up to 11.1 m, and the 1e-5 degree grid) plus 10 m, half a four-lane road
  with parking (every vertex of the three roads outside the simplified boundary is within 19.5 m
  of it on the 2026-10-03 build). The tiles keep a line whole when it is wholly within the
  tolerance (a buffer of the boundary in UTM 18N, EPSG:26918) and cut every other line at the
  boundary itself, so a Maryland or Virginia street that meets the line gets no stub; the
  District's box grows by the tolerance for the empty-tile test and the pre-draw. The planner's
  notice uses the same tolerance (`lib/dcBoundary.ts` `nearDc`, `metresToDcEdge`). The grey
  mask and its dashed edge stay on the boundary.
* **DC only** (418, 418a: "Grey out everywhere outside DC on that map too as we don't support it
  yet."; "Yes" to a warning). The District's boundary is OpenStreetMap's admin_level=4 US-DC
  relation, written by `scripts/build_dc_boundary.py` (with the rebuild's `pipeline.states` ring
  code; 163 vertices, simplified to about 30 ft) to two identical files,
  `src/core/geodata/dc-boundary.geojson` and `frontend/src/massride-data/dc-boundary.json`
  (`tests/test_mass_tiles.py` holds them equal; credited in docs/SOURCES.md and under the
  legend). The tiles clip every line to it in SQL (`ST_Intersection` where a line is not covered,
  lines only), and a tile that misses the District's box is empty without a query. The map greys
  everything outside it in Mass Ride mode (`lib/dcBoundary.ts` `DC_MASK_LAYERS`: the coverage
  mask's grey at 0.5 opacity, and a dashed dark edge so the boundary is not told by shading
  alone), over the base map and under its labels and the overlays. In words: the legend and the
  planner say "Mass Ride planning covers DC only for now. Outside the District of Columbia the
  map is grayed out and no riders-per-minute figures are drawn." (`MASS_DC_ONLY`). A Mass Ride
  route with any vertex, or any stretch's middle, outside the boundary gets "Part of this route
  is outside the area Mass Ride planning covers (DC only for now)." (`outsideDcNote`; a point
  within the border tolerance counts as inside, below): shown in
  the route view (`.mass-outside-dc`, role note) and said with the route's sentence in the
  route's polite live region (`summary.ts` `announceRoute`). Other ride types never get it.
* **Zooms in Mass Ride mode.** Roads in DC show their riders per minute from zoom 10, busy
  roads included, by band (focus by zoom, above; `MASS_ZOOM_HINT`); below zoom 10 the legend
  says to zoom in. The legend keeps
  "6-8 mph" (404). Trails, paths, protected bike lanes, bike lanes and alleys are never drawn in
  this mode.
* **Colours** (327): red #d7191c 4 px short dash, orange #f28e2b 5.5 px long dash, green #1a9850 7
  px solid, purple #6a3d9a 8.5 px solid; each outlined by a halo 3:1 from it (dark under the red,
  orange and green, white under the purple), which shows in the dash gaps. Avoid: near-black
  #14040a on coral #ee3b2c, dash-dot, labelled AVOID. The widths thin out below zoom 16.
* **The colour-blind check** (327: "the implementation must verify it under CVD simulation").
  `frontend/src/massStyle.test.ts`, with the repo's own simulator and CIEDE2000
  (`testSupport/colourVision.ts`, Machado 2009 at severity 1.0). A pair of bands whose colours
  are under 20 apart for any vision must differ in a cue besides colour (width by 1.5 px or more,
  or dash), and the red and the green must differ in both. The colour distances, CIEDE2000:

  | pair | normal | protan | deutan | tritan |
  |---|---|---|---|---|
  | under 60 / 60-120 | 29.7 | 29.0 | 17.6 | 18.8 |
  | under 60 / 120-200 (red / green) | 70.0 | 21.4 | 10.8 | 63.1 |
  | under 60 / 200+ | 39.4 | 47.3 | 54.6 | 33.6 |
  | 60-120 / 120-200 | 49.6 | 9.6 | 20.1 | 59.8 |
  | 60-120 / 200+ | 59.7 | 62.2 | 65.1 | 38.1 |
  | 120-200 / 200+ | 52.0 | 52.6 | 45.8 | 41.4 |

  Red and green are 10.8 apart for a deuteranope and 21.4 for a protanope; they differ in width
  (4 against 7 px) and dash (dashed against solid). Orange and green are 9.6 apart for a
  protanope; they differ in width (5.5 against 7 px) and dash.
* **Measured, before 404** (read-only against the live table, 2026-10-05, the whole-street,
  OSM-only rule): roads median 198; band shares of road length 0.0% under 60, 25.5% 60-120,
  69.6% 120-200, 4.9% 200+; three quarters of road rows took a class default. Superseded.
* **Measured, after 404** (offline, from the installed Roadway Block,
  `$DATA_ROOT/reference/roadway.json`, 13,833 DC blocks, 1,179.5 mi, weighted by
  block length; no database). 1,158.5 mi take the District's width and 21.0 mi fall back to OSM.
  Bands (riders a minute, as the tiles round them): under 60 0.1 mi (0.0%), 60-120 801.0 mi
  (69.1%), 120-200 251.6 mi (21.7%), 200+ 105.8 mi (9.1%); median 90. By DC functional class
  (under 60 / 60-120 / 120-200 / 200+): 1 interstate 0 / 0 / 38 / 62%, 2 freeway 0 / 6 / 23 /
  71%, 3 principal arterial 0 / 9 / 53 / 37%, 4 minor arterial 0 / 54 / 32 / 14%, 5 collector
  0 / 77 / 18 / 5%, 7 local 0 / 84 / 15 / 1%. The ride's own direction (406) is what moves most
  of DC from good to tight, against a reading of the whole street (0.0 / 9.0 / 58.5 / 32.5%) the
  owner has ruled out. The region outside DC is not
  re-measured here (no live reads): an untagged two-lane street is now 99 (was 198).
* **Measured, after 405 and 407 (3)** (the same offline method). Reversible lanes at zero and
  the 16 ft lane capped at 11 ft move 0.0 / 69.2 / 21.7 / 9.1% to 0.0 / 71.6 / 19.3 / 9.1%
  (under 60 0.1 mi; 60-120 830.6 mi, 120-200 224.1 mi, 200+ 105.0 mi of 1,159.8 mi on DC's width);
  the cap alone moves 24.5 mi (453 blocks) and the reversible lanes 3.4 mi, in DC's 7.5 mi of
  them. The median road is unchanged, so the sentinel's 60 to 200 stands. By DC functional class
  (under 60 / 60-120 / 120-200 / 200+): 1: 0 / 0 / 38 / 62%, 2: 0 / 10 / 19 / 71%, 3: 0 / 12 / 51 /
  37%, 4: 0 / 54 / 32 / 14%, 5: 0 / 79 / 16 / 5%, 7: 0 / 87 / 12 / 1%.
* **Provisional (OWNER-DECISIONS 406, 407).** The ride's own direction only (406: the oncoming
  side is never counted, and no text in the app suggests using it), the 3.5 ft door zone, the 8 ft
  OSM parking default and the 16 ft to 11 ft cap (407) are provisional: revisit them with
  FOLLOWUP-FLOW-CALIBRATION.
* **Why red is all but empty, and why that is not a bug.** The band edge of 60 riders a minute
  is 2.03 m (6.7 ft) of usable width at 29.5 a metre: narrower than any travel lane. Before 404
  it was unreachable by construction for a road: the least a road got was one 11 ft lane (99) or
  a mapped width of at least 2.4 m (70). The tile SQL (`floor(round(width x 29.5) / 10) x 10`),
  the band filters (`massStyle.js`, `min` inclusive) and the edges are right: a 2.0 m row is 59,
  tiled 50, red. Now a road reaches red where a direction has under 6.7 ft: one DC block (46th Pl
  NE, a 6 ft lane) and an OSM street whose mapped width, less parked cars, leaves under that a
  direction (a 30 ft street parked both sides is 64, tight; a 26 ft one is 46, red). Paths are
  often under 60 but are not drawn. Red bottlenecks will mostly come from part 2's reductions
  (grade, turns, signals) on the route chart.
* **Tests.** `tests/test_mass_capacity.py` (the model, the sentinel, the sections),
  `tests/test_stress_tiles.py::TestMassCapacity` (the tile property, the fallback, the ETag),
  `tests/test_route_api.py::TestMassRideCapacitySections`, `tests/test_pipeline_end_to_end.py` (the
  column written, and a build that loses it refused), and on the front end
  `src/massStyle.test.ts`, `src/lib/massCapacity.test.ts`, `src/lib/mapGlue.test.ts`; for the
  Mass Ride map's own tiles, the DC mask and the zoom focus (415-422), `tests/test_mass_tiles.py`
  and `src/lib/dcBoundary.test.ts`; for both narrowest figures (424) the "424" tests in
  `src/lib/massCapacity.test.ts` and `src/lib/profileChart.test.ts`, and for the parts outside DC (427) the "427"
  test in `src/lib/massCapacity.test.ts`, `tests/test_profile_flow.py` and `tests/test_mass_capacity.py`; in the browser, section 20 of scripts/a11y/check.mjs.

### Mass Ride routing by road capacity (items 120-123, 128; v0.15.0)

The riders a minute the capacity map draws now choose the route, for the ride size the rider
set (the "Anticipated ride size" slider, sent as `ride_size`, 100 to 2,000, 500 by default;
moving it plans again). `routemaker.mass_route.price` turns a route's stretches (the answer's
own `_flow_stretches`: each piece's usable width, Avoid, untraced, outside DC) into seconds:

- **Too narrow for the ride.** A road needs riders / 5 a minute (the riders chart's dashed line,
  a 5-minute hold). Where it carries less, each metre costs its time at the 7 mph cruise times
  (need / carried - 1), at most 3 times; Avoid carries nothing and pays the cap. So the same road
  is free for 100 riders and costly for 1,500.
- **Changes of capacity** (120-123, "It tends to scatter the group"): 60 s stepping down and 30 s
  stepping up, times (the change / the larger figure) squared, times the group scale (ride size
  / 500, between 0.5 and 3). Changes under 15% and stretches under 25 m (a junction's own metres)
  are not changes.

`core.routing.choose_by_capacity` reads every one of the router's routes that way (traced as the
answer traces them) and keeps the one whose router cost plus climbing plus capacity price is
least, the router's own unless another saves more than 5 s. Busier roads are not held against a
Mass Ride's choice (the LTS checks `calmer_or_own` and `no_busier_than_middle` are skipped once
it has run): a corked ride is judged by what a road carries (325). Where the router's own route
cannot be read in time, the choice is made as before. The router gives alternatives only between
two points up to 25 km (15.5 mi) apart on the hills slider's avoid half (`AVOID_MAX_SPAN_M`), where
a Mass Ride starts: with stops or vias, or a longer span, the route is the router's own and
`mass_capacity` reports on it without choosing. The weights are proposals for the owner.

The answer's `mass_capacity` says what the ride size needs and the route carries: the narrowest
point, the metres below the need, the narrow stretches by street (longest 15), the capacity
changes, the corkers (`mass_route.corker_load`, the Corker load chart's count in Python, held to
the front end's figures by tests/test_mass_route.py) and how the router's routes were weighed.
The assistants' tool (`mcp/routemaker_mcp.py`, `plan_route` and the other plan tools) takes
`ride_size` and returns the same in miles as `mass_capacity`, so an assistant can move a via
point onto a wider street and plan again (the owner, 2026-10-29).

Not priced yet: the signal waits, pavement and tight turns (PLAN's other reductions) and the
busy-road crossings (133-136). Not built: Avoid marks for Mass Ride alone (stretches marked Avoid
for every ride type are priced, at the cap); flagging narrow roads on the map.

### Mass Ride hazards (FOLLOWUP-MASSRIDE-MAP part 3, items 325-327)

"Some stretches can be marked as a caution or warning where we've had problems. They go along side like
a trail or pbl. If we've marked it avoid, It should be just marked avoid with no carrying capacity. These
hazards will be marked by riders and will be for this mode only." (325)

* **Reporting** (`core/mass_hazards.py` `create`, `POST /api/mass-hazards`). A signed-in rider whom
  `SuggestionSettings` allows (`Me.can_suggest`) sees **Mark a hazard** in the road panel, on a Mass Ride
  only, and not on an Avoid road. The form (`HazardReport.tsx`) asks "How serious is it?" with two radios,
  **Caution** and **Warning** (326: "Severity only", both routable), and a required reason of at most
  500 characters. The level and the reason are in words, and the result is said in a polite status region.
  The server reads the road's name from the live table (`suggestions._road`), snaps the clicked point
  with `suggestions.snap` (refused past 98 ft (30 m)), refuses it (`avoid`) when the way's segment nearest
  the point is tier 5 (`_piece_tier`: a way can be Avoid along only part of it, so not its first row),
  throws the point away, and refuses the same level already approved (`same`). Only `osm_way_id` is stored: no lat/lon
  column exists. The checks match the suggestions': one open report per rider per road (a partial unique
  constraint `mass_hazard_one_open_per_road`), 20 open in all, the shared 10 writes an hour
  (`SUGGEST_WRITES`), CSRF and same-site. Instance admins review rather than report.
* **Review** (`SuggestionReview.tsx`, now generic over a `ReviewSource`, `lib/reviewSources.ts`;
  `HAZARD_REVIEW`). The same three actions: **Approve now** (an earlier approved hazard on that way
  becomes `removed`; the partial unique constraint `mass_hazard_one_approved_per_road` keeps one approved
  per way, so of two approvals at the same moment the second is a 409 and its report stays waiting), **Delete**, and **Send to Discord**, which gives a copy-paste poll built by
  `suggestion_post.build_hazard` ("Should the Mass Ride map warn big group rides about ...?",
  options Warning / Caution / No mark needed / Not sure). The Django admin's `MassHazardAdmin`
  is read-only, with one action, **Take the selected approved hazards off the Mass Ride map**. Every action is an
  `audit_log` entry (`mass_hazard_report|approve|delete|discord|remove`).
* **The layer: API, not tiles.** The approved hazards are few, so they come from
  `GET /api/mass-hazards`, a GeoJSON FeatureCollection with one feature per way (geometry from the
  live table, Avoid-rated pieces left out; properties `way`, `level`, `level_name`, `words`, `reason`,
  `road`). It is public, with `Cache-Control: public, max-age=60` and an ETag (304; `If-None-Match` is
  compared weakly, `W/` and `*` too, by the tiles' `stress_tiles._matches`). The tiles, their ETags and the
  tile cache do not change. `App.tsx` fetches it only on a Mass Ride, and again after an approval with
  `cache: "no-cache"`, so the admin sees the rail now. It does not poll.
  `MapView` hands it to `setHazardData`, which fills the `mass-hazards` GeoJSON source that
  `addStressOverlay` adds.
* **The rails** (`massStyle.js` `MASS_HAZARDS`, `hazardLayers`; 327). Near-black (#111111) rails on a
  white casing, drawn on both sides of the road with `line-offset` (±9.5 px at z16, clear of the
  widest band line) from zoom 12. Caution is dotted (2.5 px) and Warning dash-dot (3.5 px), so the
  pattern and weight differ as well as the words. The rail is at least 3:1 against its casing and the
  land, and the rail or its casing at least 3:1 beside every band colour (`massStyle.test.ts`). The layers are in
  `massLayerIds`/`massFilters`, so they show in Mass Ride mode only.
* **In words.** The legend has a "Rider-marked hazards" list (`HazardLegend` in `MassLegend`: swatch,
  meaning and the look, "Drawn as dotted black rails on both sides of the road."). The road panel has a
  `.road-info-hazard` line ("Warning: riders have had serious problems here. Riders' reason: ..."), and its
  status sentence adds "Rider-marked hazard: Warning.". The route answer's `mass_hazards` (`along`, in
  riding order, null on other ride types, Avoid pieces left out) feeds the directions' list ("1 rider-marked
  hazard on this route, in riding order:", then "Warning on Oak Street, 0.6 to 0.8 mi (1.0 to 1.3 km): ..."),
  copied text and GPX, and the route's polite announcement (`hazardsSaid`).
* **Tests.** `tests/test_mass_hazards.py` (model, API, privacy, limits, review, layer, along, poll text,
  route answer); `src/lib/massHazards.test.ts`, `src/massStyle.test.ts` (layers, offset clearance,
  contrast), `src/lib/mapGlue.test.ts`, `src/lib/massCapacity.test.ts`; in the browser, section 22c of
  scripts/a11y/check.mjs (13 checks).

## What migrations do and do not create

`Segment` is `managed = False` on purpose, so `migrate` does not create it. The
weekly rebuild writes segment data into a staging schema and renames it into
place, so its DDL comes from the pipeline; a migration that owned the table
would fight the swap. Anything anchored to a segment — comments, issues,
closures, cue overrides, reviewer penalties — refers to it by plain columns
rather than a foreign key, because a cross-schema constraint would make the
rename impossible.

Test and CI databases therefore take segment DDL from the pipeline, not from
`migrate`.

## When the database stops

In an ephemeral container the cluster does not survive an idle period: the
process is killed uncleanly rather than shut down, so the next run finds a stale
pid file. A test run that fails with "connection refused" rather than with
something about the code usually means this. One command fixes it:

```sh
scripts/devdb.sh
```

It is idempotent, creates the role, database and PostGIS extension if they are
absent, and waits for the socket before returning.


## The public API

`POST /api/route` is Django Ninja (`core/api.py`); the presets it offers are
`core/presets.py`, the router calls and the stress join `core/routing.py`, and
the limits `core/ratelimit.py`. The schema is at `/api/openapi.json` on any
running api. A request, against the native loop's `runserver` or the stack:

```sh
curl -s -X POST http://localhost:8000/api/route -H 'Content-Type: application/json' \
    -d '{"points": [[-77.0434, 38.9097], [-77.0091, 38.8899]], "preset": "default"}'
```

It needs the four routers (`VALHALLA_UPSTREAMS`) and a populated live segment
schema; without the routers the answer is a 502, which is the API working.
`tests/test_route_api.py` replaces the router at `core.routing._transport`,
the one function that touches the network, so the suite needs neither.

Two settings worth knowing. `WEB_CONCURRENCY` - gunicorn's worker count - also
sizes `ROUTING_CONCURRENCY`, the routes the api may run at once (the count less
two, less the two geocoding slots, at least one); `runserver` is one process,
and the default of 7 gives it 3. And the per-client limit keys on the last `X-Forwarded-For` entry, so a
local client that sets that header chooses its own bucket - harmless here,
because on the stack only Caddy reaches the api and Caddy overwrites it.

**What a client should do.** Keep one route in flight: send the next plan only
when the last has answered, and on a drag replace the pending points rather
than queue another request. Do not retry on a timer. A 429 or 503 carries
`Retry-After`; wait that long once, then send the current points. The per-client
slot is one route on the default pool, so a second concurrent request from the
same browser is refused rather than served.

**Long rides.** Past 150 km of straight line a signed-out request gets 409 with
`"code": "confirm_long"` and `span_km`, and nothing is routed; resend the same
body with `"confirm_long": true` once the visitor agrees. A signed-in session
never sees the 409. Past 200 km the answer is 400 however it is asked. A
route whose traces ran out of time comes back with that part of `stress_m` as
`"unknown"`; treat it like any other unknown stretch.

**The sliders, the ride time and Cargo Bike** (PUBLIC-DIALS, the owner's
requests of 2026-09-27; PLAN.md, "Owner amendments"). All optional and additive; a body without them is planned as
before, at the preset's own starting positions:

```sh
curl -s -X POST http://localhost:8000/api/route -H 'Content-Type: application/json' \
    -d '{"points": [[-77.0434, 38.9097], [-77.0091, 38.8899]], "preset": "cargo",
         "carrying": "people", "stress": 80, "hills": -40, "when": "weekend"}'
```

- `stress`, integer 0-100, rescaled on 2026-10-01 (OWNER-DECISIONS 163 and 164;
  "Intersection costs, the calm search and the detour warning", below): 0 to 70
  is the old 0 to 90 and 70 to 80 the old 90 to 100, `use_roads` 1.0 falling to
  0.10 at 70 (Default) and 0 at 80; above 80 `use_roads` stays 0 and a search
  over the router's routes prices LTS 3, 4 and Avoid at a rate rising
  exponentially to ten metres of detour per metre at 100, with no cap and a
  warning (`detour`). 0 is traffic
  tolerant (the planner warns at 10 or below: the owner, 2026-09-28; a true
  fastest option is a later custom-costing phase), 80 keeps to low-stress ways
  unless avoiding them takes much longer, and past it the route goes out of its
  way for them. The positions in the measurements below are on the scale before
  the rescale; the old position `q` is now `q * 7 / 9` up to 90.
  The graph carries the stress tiers (LTS 3-4 ways as `bicycle=use_sidepath`,
  `lua/routemaker_remap.lua`), and Valhalla weighs that `3 * (1 - use_roads)`,
  so one graph serves every position. LTS 4 and up cost more again ("Graded
  stress", below).
- `hills`, integer -100-100, detent at 0: it sets the rider's LT1 grade, 1% at
  -100, 8% at 0 and 15% at 100 in a straight line (`hill_cost.lt1_grade_for`;
  "Hill cost past LT1", below). Below the detent `use_hills = 1 + hills/100` still
  shapes what the router offers, but every route is scored with the rider's own
  hill cost in place of the router's climbing charge. Above it, on every
  ride type but Mountain Goat, "fine with hills" (FOLLOWUP-HILLS-TOLERATE,
  OWNER-DECISIONS 242): the same scoring at a steeper LT1 grade, and `hills_tolerate`
  says
  what was compared and chosen. On Mountain Goat above it a climb
  search among the router's `alternates` (3), choosing the one that climbs most
  within `1 + 0.5 * hills/100` of the direct route's length, with routes through
  the categorised climbs near the line added to them (the hill seek, "Seeking
  hills" below). Two-point plans
  only, and not past 50 km of straight line (`routing.SEEK_MAX_SPAN_M`: a cold
  65 km search with alternates took 51 s on the live router); `hills_seek.limited`
  says when it was not done.
  Mass Ride refuses `hills > 0` (400).
- `when`: `weekend`, `weekday_rush` (Mon-Fri 07:00-10:00 and 16:00-19:00,
  America/New_York; federal holidays count as weekend), `weekday_offpeak` or
  `night` (21:00-07:00 on any day, OWNER-DECISIONS 469c; it routes on the
  standard graph, as a weekday does, so a weekend night does not count the
  weekend's daytime closures, such as Beach Drive, as paths); absent, the
  setting of the moment. Off-peak's sample instant is 20:30, before night
  begins (it was 21:00), so a closure ending at 21:00 now counts as off-peak
  car-free. It
  sets Valhalla's `date_time` (the next Saturday 09:00, Tuesday 08:00, Tuesday
  12:00 or Tuesday 22:00), which is what the
  conditional restrictions Valhalla reads are evaluated against, and it decides
  whether a road closed to cars at set times counts as a path in `facility_m`
  and as tier 1 in `stress_m`. The closure is read from
  `motor_vehicle:conditional` / `motorcar:conditional` (`routemaker.ridetime`):
  day ranges, week spans that wrap (`Fr 19:00-Mo 06:00`), `PH`, and times with
  no days, which name every day (Clark Place NW's `no @ (06:00-10:15,14:45-19:15)`
  is car-free at weekday rush; supported since the round-1 mutation review).
  A condition it cannot read - a month range, `sunset` - closes nothing.
- `carrying`: `cargo` or `people` ("Cargo with passengers", item 241), Cargo Bike only
  (400 elsewhere); it sets the stress slider's start (70, Default's, or 80).
- `assist`: boolean, Cargo Bike only (400 elsewhere): electric assist. The ride
  routes on the e-bike graph (e-bike legality) at 18 km/h rather than 14; the
  hills slider keeps Cargo Bike's start, since a heavy bike's motor rarely
  cancels a climb (the owner, 2026-09-27).
- Mass Ride refuses `stress > 0` (400): the owner's "Lock at 0".
- `intersections`, `calm_search` and `detour` (FOLLOWUP-INTERSECTIONS, additive):
  the route's stressful junctions with their reasons, what the search over the
  router's routes did, and how much longer the route is than the direct one;
  the contract is in "Intersection costs, the calm search and the detour
  warning", below.
- `stress_m` has a key `"5"`, "legal but avoid" (additive; the keys still sum to
  the distance): an expressway posted 50 mph or more inside an urban area (outside
  one it is LTS 4.5 since v0.8.1, `routemaker.stress.rural_expressway`), or a way the owner
  curated (`fixtures/overrides/2026-09-27-owner-stress.json`, loaded as that
  directory's README says). In the graph it is the LTS 3-4 stress penalty
  plus Valhalla's alley use (`service=alley`, written by
  `routemaker_remap.remap_way`); every preset sends `alley_penalty` =
  `presets.AVOID_ENTRY_PENALTY_S` (1800 s of cost, no time) for entering one,
  which reaches Mass Ride at `use_roads` 1.0 too. Only tier-5 ways pay it (the
  owner's "Only tier-5 roads", 2026-09-27): OSM's own alleys become plain
  service roads in the graph (Valhalla's service penalty, 15 s, where an alley
  had 5 s), and destination-only and private ways keep Valhalla's own
  `destination_only_penalty` (600 s, not sent). The access of a tier-5 way is
  untouched, so it stays routable when it is the only way.
  Measured on the DC box graph (PUBLIC-DIALS round 3, Valhalla `/locate`
  against the graph of 7a04862): all 9,322 destination-only or
  private-for-cars road ways located keep the base graph's
  `destination_only` flag and bicycle access, and 49 of them, OSM's own
  alleys, are service roads; all 1,273 tier-5 ways located are alleys, not
  destination-only, open to bicycles. With every other Anacostia crossing
  excluded, Mass Ride still routes over the tier-5 Douglass roadway.
- A curated tier is a stress adjustment (`routemaker.stress.StressAdjustment`,
  the format in `fixtures/overrides/README.md`): `segment.stress_adjustment_id`
  names it, and only a public adjustment whose words the owner approved also
  fills `stress_computed_tier`, `stress_adjustment_direction` (`up`, `down`,
  `same`), `stress_adjustment_category`, `stress_adjustment_note` and
  `stress_adjustment_display` (`writers._adjustment_columns`, and a table
  constraint that refuses the rest without an id). The answer's
  `stress_adjustments` lists, in route order, each adjustment the traced route
  rides over: `adjustment_id`, `tier`, `adjusted`, `length_m`, and for a
  public, approved one `direction`, `category`, `public_note` and `display`
  (the owner: "Only provide the warnings if the route goes over the road").
  Empty until the live table has the columns. The tiles do not read them.
- `stress_spans` (OWNER-DECISIONS item 81: "Could we also get a color on the
  route for what LTS it is?"): the route's sections, in route order,
  `[{from_m, to_m, tier, facility, unpaved}]` in whole metres along the traced
  length from 0, each starting where the one before ends. `tier` is 1-5 or null
  (unknown), `facility` the class or null, `unpaved` true, false or null where
  the segments do not say (OWNER-DECISIONS 302; additive, and a section also
  ends where the surface changes, so the route can draw unpaved sections in
  brown). They come from the same per-piece
  join as `stress_m` and `facility_m` (`routing.classify`; a road closed to cars
  at the ride's time is tier 1 and a path, and on the no-trail variant a lane is
  "none"), with adjacent equal sections merged and a section under 10 m
  (`routing.MIN_SPAN_M`) folded into its neighbour, so a long ride stays a
  short list; the totals are summed from the pieces and stay exact. A leg that
  could not be traced is one null section of its length, and a plan whose
  joins ran past the budget is one null section over the whole route. The map
  scales the sections to the line it draws (`frontend/src/lib/routeColours.ts`)
  and colours them with the stress map's own tokens (`stressStyle.js`).
- The graph a ride routes on (`variant` in the answer): a weekend ride on a
  preset whose graph is the standard one routes on the weekend graph
  (`Variant.WEEKEND`), where roads closed to cars at the weekend are off-road
  paths; if that router does not answer, the standard graph answers instead
  and `variant` says so. E-bike, Cargo with assist and Mass Ride keep their own
  graphs at the weekend.
- Dirt trails on a ride type that skips them (`core.trail_touch`, v0.11.0; the
  owner, 2026-10-21). A stop, via or end within 15 m (50 ft) of a dirt trail
  (`bike_access_reason` `mtb`) plans the ride on the off-road graph with its own
  costing, so `variant` is `offroad`. The trail is ridden, and so are trails
  joined to it, which means less than 30 m (100 ft) of other ways between them.
  The start alone does not count, nor the start again at a loop's end, because
  riding dirt depends on the weather. A dirt trail the plan finds for itself is
  left out by a strip a few metres across, and the plan is made again. This
  happens up to 3 times, and then the plan is made on the ride type's own graph.
  Green singletrack is always left out. A ride's re-plans send `ride_replan`.
  When the rider is on a dirt trail, or `dirt_ridden` is sent, any dirt trail
  may be ridden. The answer's `dirt_trails` says the route rides one, and Ride
  then sends `dirt_ridden` for the rest of the ride. A `blocked_lines` stretch with
  two of its quarter, half and three-quarter points within 15 m of a dirt trail (Road
  closed pressed on one; a road crossing a trail has one at most) means bad conditions:
  that re-plan rides no dirt trail (`trail_touch.closed_on_dirt`), its answer's
  `dirt_closed` says so, and Ride sends `dirt_closed` for the rest of the ride.

**The stress and hills sliders, measured** (PUBLIC-DIALS, 2026-09-27: a box
graph, -77.22,38.78,-76.90,39.02, rebuilt from the real extract by the real
pipeline stages before and after the graph change). Share of the route on LTS
3-4 and moving time; "today" is the old graph at the old Default (use_roads
and use_hills 0.5), which reproduced the live Dupont Circle to Capitol answer
(33% LTS1, 48% LTS3, 19% LTS4):

| Trip | today | stress 0 | stress 25 | stress 75 | stress 90 (Default) | stress 100 |
|---|---|---|---|---|---|---|
| Dupont Circle - Capitol | 67%, 21.6 min | 90%, 19.6 | 52%, 21.8 | 17%, 25.9 | 6%, 26.0 | 6%, 26.0 |
| Bethesda - Georgetown | 98%, 29.3 | 98%, 29.3 | 3%, 42.0 | 3%, 42.0 | 3%, 42.0 (92% path) | 3%, 42.0 |
| Silver Spring - Union Station | 10%, 48.6 | 92%, 39.7 | 10%, 48.6 | 10%, 49.2 | 7%, 50.3 | 6%, 50.4 |
| Courthouse - Farragut | 51%, 20.8 | 77%, 19.3 | 11%, 23.7 | 13%, 24.7 | 13%, 24.7 | 13%, 24.7 |
| Logan Circle - Eastern Market | 81%, 18.5 | 90%, 18.1 | 20%, 21.9 | 18%, 22.0 | 9%, 29.4 | 9%, 29.4 |
| Falls Church - DC | 9%, 48.9 | 92%, 41.6 | 1%, 50.2 | 1%, 50.2 | 1%, 50.2 | 1%, 50.2 |

Stress 0 is within 3% of the time of Valhalla's `shortest` route on every
trip, so the direct end is the fastest legal route. (Positions in this table
and the paragraph below are on the scale before the 2026-10-01 rescale: the
old 90 is 70 now.) Default starts at 90, the
owner's answer of 2026-09-27 to "75 or 90?": against 75 it takes Dupont
Circle - Capitol from 17% to 6% on LTS 3-4 for 0.1 min, and Logan Circle -
Eastern Market from 18% to 9% for 7.4 min; the other trips do not move. The hills slider below
its detent moves routes only where the terrain offers a choice (Rosslyn -
Ballston: 105 m of climb at 0, 65 m at -100); above it the climb search found
a hillier alternative on 6 of 14 trips (Bethesda - Georgetown +97 m for
+0.2 km; Takoma - Navy Yard +24 m for +1.8 km), each search under 5 s.

The weekend graph, on the same box (Default, the same trip at the weekend and
on a weekday): Little Falls Parkway 2.84 km at the weekend on the closed
parkway against 3.09 km around it on a weekday; lower Sligo Creek Parkway
0.63 km against 1.07 km; Beach Drive NW at Carter Barron the same line both
ways, 76% against 59% traffic-free. Mass Ride from Anacostia to Nationals Park
took the Frederick Douglass bridge roadway before its tier 5 and takes the
11th Street local span after (3.00 km against 3.05 km); with every other
crossing excluded it still routes over Douglass, and every ordinary preset
crosses on the Riverwalk paths.

The answer adds `facility_m` (`path`, `protected`, `lane`, `none`,
`unknown`, metres summing to the traced length, from `segment.facility` and
`segment.car_free_when`), `dials` (the positions actually planned with) and
`hills_seek` (null unless the hills slider was past its detent). Until the
live segment table has been rebuilt with the facility columns, `facility_m`
is all `unknown` and nothing else changes. On the no-trail graph (Mass Ride)
protected and painted lanes count as `none`: the field rides the roadway (the
owner: "Even protected bike lanes aren't used."); a road closed to cars is
still `path`.

**Sustained grades** (the owner, 2026-09-28: "I'd probably have an increasing
penalty for steeper hills instead" of a hard grade cap; "In many cases it's not
just stepness but steepness and length. 10% can be done for 100m of riding,
people would just sprint before it. If continued over kilometers, that becomes
a hike-a-bike"; and "I'd say a descent over about 2-3% might actually want to
be penalized. There's a point where it's a fun downhill and a point where
you're riding the breaks.").

Valhalla's own grade penalty is already progressive per metre climbed. Its
edge cost is `time * (1 + grade_penalty + ...)`, with `grade_penalty =
(1 - use_hills) * kAvoidHillsStrength[grade]` and a slower bicycle speed
uphill (`kGradeBasedSpeedFactor`); the extra cost per metre climbed over flat
riding, on a quiet street, in metres of flat riding:

| Hills slider | 3% | 5% | 6.5% | 8% | 10% | 13% | 15% |
|---|---|---|---|---|---|---|---|
| 0 (use_hills 1.0) | 12 | 13 | 17 | 20 | 20 | 23 | 31 |
| -60 (0.4) | 18 | 26 | 45 | 61 | 74 | 138 | 191 |
| -100 (0.0) | 22 | 34 | 63 | 88 | 109 | 215 | 297 |

So at -100 a 10% pitch costs 3.2 times a 5% one per metre climbed. What it
cannot do is tell a kick from a long climb: each edge is priced alone, from
its own grade. The grade is Valhalla's, computed from the DEM when the graph is
built (mjolnir/elevationbuilder.cc); no tag feeds it, and no other edge cost
scales with `use_hills`, so a graph tag cannot carry a hills-slider-scaled,
length-aware penalty in the pinned Valhalla. The avoid half therefore weighs
the router's alternatives (`core.routing.choose_gentlest`), as the seek half
does: the router's elevation along each (every 30 m, in the direction ridden)
is read as sustained climbs and descents (`routemaker.climbs`: a run survives a
3 m dip and a 150 m flat), each priced in seconds by

    cost = 1.7 * w(grade - threshold) * past * (1 + past / 1000)

with `past` the metres beyond the first 150 (the kick, free whatever its
grade), `w(x) = x * (1 + x / 0.03)` and a climb's threshold 3%; and the
route with the least `time + (-hills / 100) * cost` is kept. One kilometre at
8% costs 356 s at -100, about what walking it adds. A descent is priced the
same way from the ride type's brake grade (approved by the owner,
2026-09-28: "Approve the table"):

| Ride type | Descents cost past | Why |
|---|---|---|
| Cargo | 3% | the owner's "about 2-3%", braking a loaded bike |
| Mass Ride | 4% | PLAN's low grade tolerance; a field cannot brake as one |
| Group Ride | 5% | a group brakes earlier to stay together |
| Default, Trailmaxxing, Gravel, E-bike | 6% | most riders brake in earnest past 6% |
| Mountain Goat, Fast | never | riders who choose these want the descent |

The avoid half never answers with a route busier than the same trip at the
middle of the slider (the owner, 2026-09-28: "Traffic wins (Recommended)"):
the same request is made again at the middle - one /route without
alternatives, at most 18 s - both routes are traced, and if the hill-avoiding
one's exposure (LTS 3 + 2 x LTS 4 + 3 x tier 5 metres) is worse, the middle's
route is the answer (`hills_avoid.kept_middle`); a middle call or trace that
fails keeps the hill-avoiding route. The check leaves the answer's own traces
8 s of the budget (`MIDDLE_TRACE_RESERVE_S`): the middle call gets at most what
is left less that (and 15 s on the weekend graph), and is not made when that is
under 4 s, so a slow first route no longer leaves the breakdown "unknown". The
route answered is traced once; the check's trace is reused. On the correctness
reviewer's grid (3060
plans on the r6 box graph) the avoid-half plans busier than the middle went
from 89 to 0, the middle's route was kept 93 times, and an avoid-half plan's
time went from a median of 0.12 s (p95 0.53 s) to 0.25 s (p95 0.87 s).

Nothing changes at the middle of the slider or above it, and nothing is
rebuilt: the graph is the same. The limits are the seek half's - a start and
an end only, up to 50 km apart, three alternatives - and every ride below the
middle now asks for them (Cargo starts at -60), which roughly doubles the
router's work for such a ride.

The data (region extract and 1-arc-second DEM, named roads and trails chained
by name, both directions, `routemaker.climbs.runs`): 75,436 climbs past 150 m,
of which 79 are 8% or steeper for a kilometre or more, all in the Catoctins,
the Blue Ridge and around Sugarloaf (Coxey Brown Road, 2.9 km at 10.2%, 4,451
s; Middlepoint Road, 2.3 km at 9.9%; Harp Hill Road, 1.9 km at 9.0%; Park
Mills Road by Sugarloaf, 660 m at 9.0%). The costliest in the District and
Arlington are 1-2 km at 5-7% (Massachusetts Avenue NW, 1.9 km at 5.5%, 360
s; Arizona Avenue NW, Fulton Street NW, Morris Road SE) or short and steep
(Calvert Street NW, 420 m at 10.1%); around Great Falls the steepest roads
are 400-700 m at 7-11%. The DC box has no climb of 8% for a kilometre.

Measured on the box graph through the API's own code: of 16 ridge-crossing
trips, the avoid half changed the route on a few - Georgetown to Glover Park
at -60 takes a 3.72 km route with 86 s of sustained-climb cost against the
router's 103 s; down Massachusetts Avenue NW, Cargo at -60 takes a route 99 m
shorter with 239 s of descent cost against 297 s, while Fast keeps the
direct descent. On most city trips the router offers no gentler alternative,
and the kept route is its own. A per-edge sustained-grade cost - the same
model priced into every edge from the pipeline's elevation - would need a fork
of the costing (PLAN's layer 3); the owner chose "Ship this, fork later
(Recommended)".

**Fine with hills** (FOLLOWUP-HILLS-TOLERATE, OWNER-DECISIONS 242). The owner:
"I'm wondering for future releases if it wouldn't make sense for the hill slider,
outside mountain goat to not nessicarily perfer hills, but mostly tolerate them.
For instance lighter individuals would probably move the slider to more hilly as
it's faster than them. People with ebikes would probably just want a more direct
route as hills wouldn't affect them too much." So the right half of the hills
slider means "fine with hills" on every ride type but Mountain Goat
(`presets.Preset.hills_tolerate`), and the E-bike ride type starts there, at 50
(`presets.EBIKE_HILLS`). The slider's words follow: "Fine with hills" at the right
end (Mountain Goat keeps "Seek hills"), "Hills matter less" and "Fine with hills"
for the positions right of the middle.

Valhalla's `use_hills` stops at 1.0, the detent, where a climb still costs the time
its slower uphill speed takes (`kGradeBasedSpeedFactor`). So the discount is taken
on the router's alternatives, as the avoid half's weighing is: each route's cost
loses `w x` its climbing charge, with `w = hills / 100`
(`presets.tolerate_weight`), and the least is kept (`routing.choose_direct`):

    score = router cost - w x QUIET COST x sum over rising windows (rise x K(grade))

`K` is the router's extra cost per metre climbed at the detent, in metres of quiet
flat riding, from the table above (12 at 3%, 13 at 5%, 20 at 8%, 31 at 15%, read in a
straight line between, 0 on the flat; `climbs.ROUTER_CLIMB_FLAT_M`), over the effort
model's windows of at least 984 ft (300 m) (`effort.windows`), so a sample's noise is not a
steep pitch. QUIET COST is the calm search's (2.2 times a quiet metre's time at the
ride's speed). At the top of the slider a climb costs what the same distance on the
flat does, so the shorter or more direct route wins even where it climbs more;
since only the router's own charge comes off, a climb never earns a route a credit
(that stays Mountain Goat's). An alternative must save 5 cost seconds
(`routing.TOLERATE_EPS_S`). Never a busier route: the alternative is traced and
kept only where its exposure is no worse than the router's own route's
(`routing.calmer_or_own`, the avoid half's guard). The calm search below the top of
the stress slider scores its candidates the same way (`refine.Analysis.score`,
`Context.hills_tolerate_weight`); at the top the stress order decides and its
distance level is the actual distance, which counts no climbing already, so "fine
with hills" plans as the detent does there (`hills_tolerate.limited` is
`"calm_first"`). The limits are the avoid half's: two-point plans up to 16 mi
(25 km) of straight line (`routing.AVOID_MAX_SPAN_M`), since E-bike rides start
here. Planner and costing only; no rebuild.

The answer's `hills_tolerate` (null unless the slider was right of the middle on a
ride type but Mountain Goat): `candidates`, `chosen` (0 is the router's own),
`weight`, `discount_s` (what came off the kept route, cost seconds),
`extra_climb_m` and `extra_distance_m` (the kept route against the router's own,
negative where shorter), and `limited` (`two_points`, `long_ride`, `timed_out`,
`calm_first`).

**Hill cost past LT1** (v0.12.0; this replaces the sustained-grade price and the
"fine with hills" discount above as the hills slider's weighing, which are kept as
the record of how it got here). The owner, 2026-10-23: "I'm thinking for hill stress
to always assume time equivalent, but the slider should determine a further penalty
for steepness. We could have the penalty start around the max steepness someone can
ride an extended period without labored breating ( LT1 threshold essentially)";
"Below LT1 you can basically downshift and chill, so it's essentially the same as a
slightly longer flat piece. Above that, fatigue can set in. Above FTP, fatigue is
even higher, so a higher penalty. Let's mainly try to focus on one metric and
extrapolate. Simplicity is better."; "Just do a standard model ... nobody wants to
put in 50 parameters"; "You can use the slider standards for the levels ... or
1-15"; "The curve should probably start around 65% of FTP as thats a casual
endurance pace"; "then go much more rapidly after FTP. look at a stanard power
curve"; "In general it's more long term stamina than short term."; "Just make it clear
that while we're using an FTP model, were just basing it on a comfortable climb grade.
It's unlikely that a precise number would change routing much. Weight should only really
affect the extra time component, as heavily loaded touring bikes tend to have good
climbing gears. Penalty is by slider."; "mostly a hidden calculation, less so for the
actual time. Basically if you are having to push a bike up a hill it's going to be a
last resort"; and "Can the slider positions just be percent?"

The one metric is the rider's **LT1 grade**: the steepest grade they can climb for
several minutes in their lowest gear without labored breathing. The hills slider shows
it in whole percent, 1% at full avoid, 8% at the detent and 15% at the far end, in a
straight line (`hill_cost.lt1_grade_for`; the front end's `hillsGradePosition` and
`hillsAtGrade` map the slider's percent to the API's `hills`, -100 to 100, which is
unchanged); each ride type's start is its standard rider (Cargo -60 is 4%, Fast 40 is
11%). Mountain Goat keeps its old slider, whose right half seeks climbs. FTP is only
the shape of the curve: the rider sets nothing but the grade. The effort is worked out
for a standard rider and bike of 198 lb (90 kg, `effort.MASS_KG`) with the effort
model's forces (`routemaker.effort`, Martin et al. 1998: rolling resistance 0.006, CdA
0.4 m², air 1.225 kg/m³), 95% drivetrain, so the penalty follows the slider alone:

- **LT1 power** is what holds 5 mph (8 km/h), a hybrid's lowest gear at an easy
  cadence, on the LT1 grade. It is the top of Zone 2, 75% of FTP (Allen and Coggan,
  "Training and Racing with a Power Meter"; LT1 is the first ventilatory threshold,
  the talk-test intensity, Foster and Porcari, ACE 2010). So FTP = LT1 power / 0.75.
- **Endurance pace**, 65% of FTP and never less than what holds the ride's flat speed
  on the flat, is the power the rider climbs at.
- **Time, always.** Over each of the effort model's rising windows (at least 984 ft
  (300 m), so a short kick averages out) the standard rider climbs at the endurance
  pace, never faster than the flat speed and never slower than 5 mph. The request's
  system weight moves at that same power, so a loaded bike climbs slower, down to
  pushing pace in its low gears, and no rider climbs a steeper grade faster than a
  gentler one (timed in steps of 0.1% of grade); the steepness penalty never changes with
  weight (the calm search's effort blend and Mountain Goat's effort tiebreak still weigh
  it). The extra seconds over the flat cost what the same seconds of flat riding do.
- **Past the endurance pace**, where holding 5 mph takes more, the penalty is the
  window's seconds times `(e^(d / 0.2) - 1) / (e^(0.35 / 0.2) - 1)`
  (`hill_cost.steepness_rate`), with `d` the power past the endurance pace as a share of
  FTP: 0.06 s a second at 70%, 0.24 at 80%, 0.52 at 90%, 1 at FTP, 1.8 at 110%, 3.1 at
  120%. It sits close to the table the owner approved ("That table looks about right":
  0.08, 0.33, 0.66, 1, 2.4 at 110%).
- **How long the climb lasts.** A climb is the rising windows around a window, until
  the road drops more than 10 ft (3 m, `climbs.DIP_M`) below the climb's top or goes
  two windows without rising; elevation noise and via points do not split it. Each
  window's effort is weighed as the sustained effort it equals over the whole climb's
  riding time `t` (the standard rider's, at the pace above): the power needed divided
  by `1 + W'/t`, with W' = 70 s of FTP. The whole effort is scaled, so the endurance
  pace and LT1 move with it: the slider's own grade, held for the several minutes the
  slider's help asks about (up to about 7.5 minutes, where LT1 power over `1 + W'/t`
  reaches the endurance pace), costs nothing past its time, and a little more on longer
  climbs (about 49 s over 1.2 mi (2 km), 105 s over 1.9 mi (3 km)) (`hill_cost.W_PRIME_S`; the power-duration curve
  FTP x (1 + W'/t), Monod and Scherrer 1965, Skiba et al. 2012; cyclists' W' of 18 to
  23 kJ, Weigend et al. 2021, arXiv 2108.04510). The owner: "10% can be done for 100m
  of riding, people would just sprint before it" and "more long term stamina than short
  term". A 2-minute pitch weighs a little over a third less, a 20-minute climb about 5% less. Added
  after the PC check of 2026-10-23, where at 3% Georgetown to Tenleytown took 0.75 mi
  more, Reno Rd and a busier junction to save 10 ft (3 m) of climb: without it a 1,000
  ft (300 m) pitch at 6% cost a quarter of an hour of penalty at 3%; now it costs a
  minute.
- **Pushing is a last resort.** Where riding a window would cost more than pushing it,
  it is pushed, at Tobler's hiking speed (Tobler 1993, NCGIA 93-1:
  `6 e^(-3.5 |grade + 0.05|)` km/h) times 0.75 for the bike (`hill_cost.push_ms`; the
  owner: "2.5 mph is probably fast"): 1.9 mph (3.1 km/h) at 6%, 1.7 mph (2.7 km/h) at
  10%, 1.4 mph (2.2 km/h) at 15%. It costs its time plus 4 s of penalty a second pushed
  (`WALK_PENALTY`), so a route that needs pushing loses to almost any ridable one.

The penalty is for choosing routes only: no time shown to riders includes it. Descents
add nothing here; riding the brakes is still priced from the ride type's brake grade
(the table above). At 198 lb (90 kg) and 11 mph (18 km/h), 0.6 mi (1 km) costs, in
minutes of time plus penalty: at the detent (8%), 4.2 + 0 at 8%, 4.2 + 1.7 at 10% and
4.2 + 5.2 at 12%; at Cargo's start, -60 (3.8%, shown as 4%), 4.2 + 0.2 at 4%, 4.2 + 6.0
at 6% and, pushed, 19.2 + 90.2 at 10%; at Fast's start, 40 (10.8%, shown as 11%), 4.2 +
0.6 at 12%. At 3% (-71), 1,000 ft (300 m) at 6% costs 1.2 + 1.0.

Where it is used. Valhalla's own climbing charge (the router's cost per metre climbed
at the request's `use_hills`, the table above, read between its 1.0, 0.4 and 0.0 rows:
`climbs.router_climb_m`) is taken off each route and the rider's hill cost
(`hill_cost.hill_cost_m`, metres of flat riding at the ride's speed) put in its place:

- the router's alternatives, on both halves of the slider for every ride type but
  Mountain Goat (`routing.choose_by_hills`, `routing.hill_s`; an alternative must save
  5 cost seconds, `HILLS_EPS_S`), still never a busier route (`routing.calmer_or_own`)
  and with the same limits (two points, up to 16 mi (25 km) apart);
- the calm search's score (`refine.Analysis.score`: `hill_m - router_climb_m`) and its
  distance level (`refine.level3`: length plus `hill_m`), so at the top of the stress
  slider climbing counts as the time it takes and the penalty past LT1.

`hills_avoid.grade_cost_s` and `direct_grade_cost_s` are now the rider's hill cost in
cost seconds (`routing.rider_hill_s`); `hills_tolerate.discount_s` is the climbing cost
the kept route saves against the detent. Scoring only: nothing is rebuilt.

**The climb card** (v0.6.0; the owner, 2026-10-12). A press on a climb's summit marker (in Go,
its dashed line too) opens its card (`climbInteraction.ts`, `lib/climbCard.ts`): MapView's click asks
`climbAt` before `runClick`, after a station and a water or restroom icon (`water.hits`), so the press
is never also a point or (in Go) a destination; in Plan a press on the dashed line places a point as
before. The next click only closes the card (`climbClosing` keeps the water and federal cards from
opening under it); a press on another climb opens that climb's card, and one on the climb shown only
closes it (`climbCardAfterClose`). "Climb details" focuses the card from ClimbCardView's own mount effect. The profile is GET /api/climbs/{id}/profile (`core.climbprofile`, read-only, rate-limited
`climb-profile` 60 a minute, `ROUTING_IN_FLIGHT`): the climb is looked up by id in the committed
file, the router asked once for a /route foot to summit through `hillseek.via_points` with
`elevation_interval` 30 (standard, then offroad), the heights and grades read as the route chart's
(`routemaker.profile`), kept per process (512 climbs) and cached a day. "Ride this climb": Plan,
`rideClimbEdit` (bottom then top before the destination, 25 m in from the ends); Go, `goTo(top, ...,
[bottom])`. The keyboard path is the road panel's "Climb here" (`climbNearSpot`, 165 ft (50 m)) and
"Climb details". "Show climbs from" (`routemaker.climbsFrom`) filters both layers by `rank`.

**Seeking hills** (FOLLOWUP-HILL-SEEK, OWNER-DECISIONS 205: "a candidate generator
that finds climbs near the line and routes through them, like the trail seek").
Mountain Goat right of the detent chooses the route that climbs most within
`presets.seek_distance_ratio` (1.05 at 10, 1.5 at 100) of the router's own route
(`routing.choose_climb`). The router's three alternatives are its near-ties on time and
rarely go out of their way for a hill, so the hill seek (`core.hillseek`, called by
`routing.hill_seek`) adds routes through the categorised climbs near the line to them.
It runs where the climb search does (below the top of the stress slider, two points,
up to `SEEK_MAX_SPAN_M`, the alternatives' ask not timed out), but not on a round trip
(the end within `LOOP_SAME_M`, 165 ft (50 m), of the start, or a loop: the corridor
would be a circle and a route through a climb an out-and-back), and needs no rebuild:

- **The climbs** are the Climbs layer's file, `frontend/src/climb-data/climbs.json`
  (Cat 5 to HC, `pipeline.climb_layer`), read once per change of the file
  (`hillseek.load`). The api image copies it. Without it (or with a file it cannot
  read) nothing is asked, the plan is as before, and `climb_seek.limited` is
  `no_climbs`; the log says so once for each path (a missing file) or each change of
  the file (one it cannot read).
- **The corridor** scales with the budget. A climb is kept when
  `CIRCUITY x (start to foot + summit to end) + climb length <= ratio x the router's
  own length`, with `CIRCUITY` 1.2: an ellipse round the straight line, which widens
  as the dial goes right. Left out: climbs the router's own routes already ride uphill
  (they add nothing), and mostly unpaved ones under Avoid gravel. Ranked by category
  (HC first), then height gained, then the shorter estimate.
- **The proposals**, at most `MAX_CANDIDATES` (3) router calls, as the trail seek's:
  the best climb with the best other one that fits the budget beside it (both, in the
  shorter order; two climbs whose feet or summits are under 1,000 ft (300 m) apart are
  two sides of one hill and are not paired), the best alone, then the next best alone
  that the calls before have not covered (the pair's partner is not asked for again).
- **Uphill.** A climb is asked for as `through` locations along its line from 82 ft
  (25 m) above its foot to 82 ft (25 m) below its summit, at most about 0.9 mi
  (1.5 km) apart, three to six of them (`via_points`): the router must pass them in
  order, so it rides the climb up. The request is the plan's own without
  `alternates` (the work zones closed to bicycles stay left out).
- **Time.** The seek has `SEEK_BUDGET_S` (8 s) from when it starts and stops 8 s
  short of the plan's budget (`TRACE_RESERVE_S`, the answer's traces); a call is not
  started with under 2 s left. A route the router has none for is skipped; a router
  that times out ends the seek (`climb_seek.limited` `time`).
- **The choice** is the climb search's, unchanged: the routes found join the router's
  own and `choose_climb` keeps the one that climbs most within the budget (the
  router's own on a tie).
- **Naming.** The kept route's climbs are those it rides uphill by the front end's
  rule (`climbsAlongRoute`; `hillseek.ridden`): every point of the climb's line within
  165 ft (50 m) of the route, each further along than the last, and the stretch from
  foot to summit 0.8 to 1.3 times the climb. Each is a row of `hills_seek.climbs`
  (`id`, `category`, `length_m`, `gain_m`, `grade_pct`, `from_m`, `to_m` along the
  route, `unpaved`, `name`, `text`, and `sought`, whether the seek asked for it), a
  `climb` entry of the description ("At 3.2 mi (5.1 km): Category 4 climb, 0.8 miles
  (1.3 km) at 6.2%, 262 ft (80 m) gained, to the summit at 4.0 mi (6.4 km).", at the
  climb's foot; not a ride-mode cue), and a sentence of the route summary's hills note
  ("It rides 1 climb: ...", with "Looking for routes through nearby climbs took too
  long; only some were compared." when its time ran out and "The Climbs layer is not
  available on this server, ..." without the file). Gains of 1,000 ft or more are
  written with a thousands separator on both sides ("2,930 ft (893 m)"; the front end's
  `formatClimb`, which the contour labels follow). `hills_seek.climb_seek` is `near` (climbs in the
  corridor), `asked` (router calls), `found` (routes added) and `limited`, or null
  where the seek did not run.

Tests: `tests/test_hillseek.py` (pure: the file, the corridor, the proposals, the
points, the ridden rule, the words, the seek with a stand-in router, and
`routing.hill_seek` against a stand-in transport) and `TestHillSeek` in
`tests/test_route_dials.py` (the plan, through the API). `scripts/mutants_hillseek.py`
is their mutation pass, as `mutants_trailseek.py` is the trail seek's.

**Calibration of the tiers** (OWNER-DECISIONS 83-143; `routemaker.stress`
unless named; PLAN.md quotes the owner's words):

- *Lane count in a city.* Inside the urban-area layer
  (`reference/urban-areas.json`) a one-way street with up to two through lanes
  is read on Furth's single-lane row, speed and volume deciding ("Multi-lane in
  a city isn t nearly that problematic"; "1 Way is typically lower stress at
  similar characteristics"). A two-way multi-lane street, a one-way of three
  lanes or more (`wide one-way floor`, item 143) and a carriageway of a divided
  road are LTS 3 at least (`two-way floor`), and LTS 4 from 30 mph over 8,000
  vehicles a day (`two-way busy`, Furth v2.2's threshold). A quiet one (1,500 a
  day or fewer) keeps its low-volume relief down to the floor, so a 35 mph
  four-lane street at a low count is LTS 3 (item 140, owner-approved, as v2.2
  rates it). Outside urban areas Furth's multilane rule stands. Lanes are
  counted per direction (`tags.lanes_per_direction`).
- *Divided roads* (`routemaker.divided`, item 132). OSM maps a road with a
  median as two one-way ways; a one-way of a divided class (trunk to
  unclassified), named, with a same-named way running the other direction
  alongside it - 13-150 ft (4-45 m) to one side, at two or more points 65 ft
  (20 m) apart - is scored as the two-way road it is. Same-named ways that close
  into a ring under 0.6 mi (1 km) round are circles or loops (Ward, Tenley,
  Blair and Americana Circles) and are left out, as is every roundabout (item
  228, below). 46,206 ways on the region; 133 MiB and 19 s on this host.
- *Roundabouts* (item 228). `junction=roundabout` or `circular` is one-way
  whether or not a `oneway` tag says so, unless it is tagged `oneway=no`, as
  routing has it (`tags.is_oneway`, the one reading of one-way for the
  classifier, the segment table's `road_oneway` and `road_lanes`, the
  divided-road pairing and the agency overlay; the junction model prices the
  ring as one-way through `road_oneway`). On the 2026-09-25 extract's own tags
  (no agency block) that reads
  1,238 of the region's 2,729 roundabout ways (45.3 of 82.2 mi) one-way that
  were read two-way: 1,089 with no `oneway` tag and 149 a divided-road flag
  had made two-way. Two ways changed tier (Marcus-David Peters Circle, VA,
  LTS 3 to 4: two lanes are now a direction's). Upstream makes a roundabout
  tagged `oneway=no` one-way as well; the classifier reads the mapper's word
  (one such way, Kenton Court 1536402606).
- *A decent painted lane.* At 40 mph a decent lane is LTS 3, a tier below
  mixed traffic (item 84), and not from three through lanes a direction, where
  Montgomery's Appendix D keeps LTS 4. Decent: buffered, or not tagged narrower
  than 5 ft; an untagged width counts.
- *Missing speed limits* take the state's default (items 108, 112): the
  District 20 mph on every class, 15 in alleys; Maryland and Virginia urban
  areas 25 residential, 30 tertiary and unclassified, 35 secondary and primary;
  elsewhere the old class tables. A `maxspeed:type` or `source:maxspeed` naming a
  state (`US-DC:urban`) says the same. The state is the one each way's middle
  vertex lies in, from the rebuild's own extract (`pipeline.states`, item 137;
  a vertex on a shared line goes to Maryland or Virginia, the higher default).
- *Arterials* (item 141): a trunk, primary or secondary road or its link is
  LTS 3 at least without a painted, buffered or protected lane, a paved shoulder
  the bike-lane table credited (item 145: "Yes, count it"), or a facility mapped as its own way beside it
  (`facility.separate_pairs`) - everywhere (`arterial floor`). And v2.2's middle
  band at 20 mph and below: 1,500-8,000 vehicles a day is LTS 2 (`mid volume`);
  it is not redundant after the floor, since it moves the non-arterials.
  *Collectors* (item 176: "At least LTS 2 (Recommended)"): a tertiary street
  or its link without bike infrastructure is LTS 2 at least (`collector
  floor`), and a count may push it higher; this moves up to 50.6 mi of the
  District's collectors from LTS 1 (15.0 mi in Maryland, 44.8 mi in
  Virginia). Under either floor a rideable shoulder reads as a lane of its
  width (`shoulder read as a lane`): never worse than the same road with that
  lane, never better.
- *Curated speed limits* (`routemaker.speed_corrections`, `fixtures/speed/`,
  item 131): the Montgomery County parkways with no posted speed are read at
  25 mph; a posted speed wins.
- *Alleys* keep their tier and pay the LTS 3 stress penalty in routing (item
  110, `lua/routemaker_remap.lua`), on top of the tier-5 alley charge.
- *Singletrack* (`routemaker.singletrack`, item 111): a trail rated 1 or more on
  `mtb:scale` or `mtb:scale:imba`, unless paved, is closed to bicycles on every
  graph (`rm:no_bicycle=singletrack`). The C&O towpath stays a path either side
  of lock 21.
- *The CBD rule* (`routemaker.cbd`, item 104): a sidewalk inside DDOT's Central
  Business District and outside the federal areas and the Architect of the
  Capitol's polygon is closed to bicycles (`rm:no_bicycle=cbd_sidewalk`).
- *Avoid gravel* (items 91, 92): the box raises `avoid_bad_surfaces` to 0.9 and
  rides the route as a Road bicycle at the preset's own speed, so every surface
  worse than compacted is priced steeply on every preset; a ride that starts or
  ends on gravel is still planned.

Measured over the region's source extract (2026-09-30, the current head's
rules; 98,411 road miles, proposed, construction, platform and corridor ways
left out; states from the merged extract's boundaries): LTS 1 goes from 47.6%
to 48.1% of the miles against 20d975d, LTS 4 from 17.8% to 17.0%; in the
District LTS 1 from 44.9% to 71.3%, LTS 3 from 10.6% to 12.2% and LTS 4 from
12.8% to 6.3%. Against the 0889eee rules the arterial floor moves 286 mi region-wide (the
District 70 mi, 32 mi of it from LTS 1) and the middle band 73 mi (the District
50 mi). 261 mi of the coverage
lie in West Virginia and Pennsylvania, whose boundaries do not close in the
merged extract; they keep the class tables.

**Deviations from the literature review**
(`reports/LTS-literature-review.md` (not in the repository)), kept here because each is a decision,
not an oversight:

1. A one-way street with up to two lanes stays on the single-lane row; the
   review reads two lanes a direction on the multilane rows (items 106, 109).
2. The District's default is a flat 20 mph on every class; the review suggests
   20/25/25 by class. The arterial floor (item 141) covers the arterials that a
   flat 20 would have put at LTS 1.
3. Lanes on a two-way road are halved with floor, not ceil, and
   `lanes:both_ways` is not subtracted.
4. v2.2's bike-lane table is not built; a decent lane at 40 mph is one tier
   below mixed traffic, and an untagged lane width counts as decent.
5. Alleys keep their tier and are priced like LTS 3 in routing; the review
   suggests LTS 2 and a penalty ("Stronger", item 110).
6. A curated 25 mph on the named parkways replaces Montgomery's parkway rule
   (item 131).
7. A quiet multi-lane street at 35 mph keeps its low-volume relief down to
   LTS 3; the review's summary table says LTS 4 at 35 mph and above, while v2.2
   itself agrees with the branch (item 140).
8. Road class is an input: arterials are LTS 3 at least without a facility
   (item 141). Furth's tables read speed, lanes and volume, not class.
9. A one-way of three lanes or more takes the two-way floor, after SFMTA's
   comfort index rather than Furth (item 143).
10. A carriageway of a divided road is scored as two-way, lanes per direction
    from its own `lanes` (item 132).
11. A rideable paved shoulder counts as bike infrastructure for the class
    floors and reads as a lane of its width (item 145: "Yes, count it");
    the review counts only a marked lane or track.
12. Collectors are LTS 2 at least without a facility (item 176); like item
    8, a class floor no Furth table has.

**Graded stress** (the owner, 2026-09-28: "Yes, grade them (Recommended)" and
"I'd probably want LTS 4 to be twice the stress level of LTS 3 at least.").
A way's *stress level* at a slider position is the cost its tier adds per
metre over the same edge with no tier, as a multiple of the edge's time cost:
Valhalla's bicycle edge cost (3.5.1 to 3.9.1) is `time * factor`, with
`factor = 1 + grade + accommodation * roadway_stress` (sif/bicyclecost.cc;
from 3.6.0 it then multiplies by a per-request linear-feature factor, 1 unless a
request sends `linear_cost_factors`, which RouteMaker does not), so the stress
level is `factor(tier) - factor(no tier)` for the same edge, grade and speed.
LTS 3 is `bicycle=use_sidepath`, which adds `3 * (1 - use_roads)` to the
accommodation factor. LTS 4 and up add the graph's top practical speed (140,
`kMaxOSMSpeed`) and lane count (15 each way, `kMaxLaneCount`), which raise the
roadway stress through its speed penalty and lane term; the bicycle's time
comes from its own speed, so no duration changes, and the speed limit and
access stay OSM's. Not on the no-trail graph: Mass Ride is locked at 0.

The stress levels, LTS 3 / LTS 4 (and the ratio), modelled from the costing
code for representative roadways at each slider position. (Positions in this
table and the measurements below it are on the scale before the 2026-10-01
rescale: the old position `q` is now `q * 7 / 9` up to 90, so the columns are
about today's 0, 19, 39, 58, 70 and 80, and "5 to 100" is about today's 4 to 80.)

| Roadway | 0 | 25 | 50 | 75 | 90 | 100 |
|---|---|---|---|---|---|---|
| secondary, 1 lane each way, 30 mph | 0 / 1.14 | 0.92 / 4.64 (5.0x) | 1.98 / 10.21 (5.2x) | 3.26 / 20.22 (6.2x) | 4.13 / 28.38 (6.9x) | 4.75 / 34.82 (7.3x) |
| primary, 2 lanes each way, 35 mph | 0 / 1.05 | 1.14 / 4.62 (4.1x) | 2.63 / 10.42 (4.0x) | 4.70 / 21.06 (4.5x) | 6.23 / 29.80 (4.8x) | 7.38 / 36.74 (5.0x) |
| primary, 2 lanes each way, 40 mph, painted lane | 0 / 0.82 | 1.26 / 3.97 (3.1x) | 3.00 / 9.10 (3.0x) | 5.51 / 18.42 (3.3x) | 7.39 / 26.08 (3.5x) | 8.82 / 32.14 (3.6x) |
| trunk, 3 lanes each way, 45 mph | 0 / 0.91 | 1.55 / 4.63 (3.0x) | 3.85 / 10.88 (2.8x) | 7.58 / 22.74 (3.0x) | 10.54 / 32.62 (3.1x) | 12.84 / 40.52 (3.2x) |
| primary, 2 lanes each way, 55 mph (89 km/h) | 0 / 0.81 | 1.47 / 4.18 (2.8x) | 3.61 / 9.77 (2.7x) | 6.81 / 20.12 (3.0x) | 9.27 / 28.68 (3.1x) | 11.16 / 35.48 (3.2x) |

Over every combination of class, 1-4 lanes, no, shared or painted lane and a
prior truck route, the smallest ratio at slider positions 5 to 100 is at
least 2.0 on roads posted up to 50 mph, 1.99 at 55 mph and 1.75 at 65 mph;
closing that gap needs a costing fork (PLAN's layer 3), since the graph's
speed and lane count are at their maximum. At 0 LTS 3 adds nothing and LTS 4
about 0.8-1.1, so the most direct route leans off LTS 4 too. Tier 5 is LTS 4
plus the alley charge on entry.

Measured on the DC box graph (PUBLIC-DIALS, 2026-09-28, head fc9bab7):

- Every tier-4 edge located (27,141 of 36,121 ways, 5,148 km open to
  bicycles) carries the marks but 37; with each edge's own class, lanes,
  speed and cycle lane from the ungraded graph, 99.8% of that length is at
  2x or more at every slider position from 5 to 100. 9.9 km falls short
  (1.78x at worst, a bicycle-legal motorway-class way at 105 km/h).
- L Street to Massachusetts Avenue, the review's probe: LTS 4 was 393 m at
  0, 1,675 m at 25 and 482 m at 100 before; it is 393, 393, 300, 77, 77 and
  77 m at 0, 25, 50, 75, 90 and 100 now, trading LTS 4 for LTS 3 as the
  slider rises. Over the 21 box trips LTS 4 never rises by more than 34 m
  from one position to the next (Chevy Chase to Peirce Mill at 50, where the
  route drops 3.1 km of LTS 3; Logan Circle to Eastern Market, 11 m); before,
  five trips rose, by up to 1.3 km.
- The cost at 0: on 10 of the 21 trips the direct end is now 3-19% slower
  than the fastest route (Bethesda to Georgetown 34.9 against 29.3 minutes),
  where before only one was; it leans off LTS 4 at 0 as the owner's "at
  every slider position" asks, and no longer reads as "the fastest legal
  route" there.

**Half steps in the graph** (OWNER-DECISIONS 441i-441l, 461a; HALF-STEP-EDITOR phase 3). A
half step reaches the transform as `rm:stress_half=yes` beside its lower `rm:stress_tier`
(`pipeline.run`, from the override's `half`), and `half_step_marks` adds: 3.5 LTS 3's
`use_sidepath` plus `maxspeed:practical` at the road's own speed but at least 90 and 11 lanes
each way (0.8-1.2 of the midpoint between LTS 3 and LTS 4, modelled as for the table above); 2.5
10 lanes each way and no `use_sidepath` (short of the midpoint, below LTS 3 except at
`use_roads` 1.0); 1.5 nothing; 4.5 LTS 4's marks and never the alley mark. The rolling chart
reads the same marks (`calm.road_multiplier`'s `half`, `HALF_GRADED_LANES`). docs/stress/
stress-number.md section 3 has the table, why 2.5 stops short, and the one exception;
`tests/test_half_step_model.py` pins them.

**Legs.** Besides the shared contract's fields, a 200 carries `leg_ends`: for
each leg (one fewer than the points) the index in `geometry.coordinates` of its
last vertex, so leg k runs from `leg_ends[k - 1]` (0 for the first) to
`leg_ends[k]`. The planner uses it to put a via dragged off the line into the
leg that was grabbed. It is additive; a client that predates it ignores it.

**The stress tiles.** `GET /tiles/stress/{z}/{x}/{y}.pbf` is a plain Django
view (`core/stress_tiles.py`), not Ninja: a Mapbox Vector Tile drawn by
PostGIS's `ST_AsMVT` from the live segment table, one layer `stress` with
`tier`, `trail`, `unpaved` and `facility` on each feature. It needs only a
populated live schema, no router:

```sh
curl -s -o /tmp/t.pbf -w '%{http_code} %{size_download}\n' http://localhost:8000/tiles/stress/14/4686/6267.pbf
```

A tile is served from the `stress_tile_cache` table once drawn
(`core/tile_cache.py`); `python manage.py predraw_stress_tiles` fills z7-14 for
the live table, and a local `runserver` with an empty cache draws on request.
What each zoom draws, the limits, the cache, the draw slots and timeout and the
overview index are in docs/OPERATIONS.md, "The stress tiles". `tests/mvt.py` decodes a tile for
the tests (`tests/test_stress_tiles.py`) and for looking at one by hand.

**The covered area.** `GET /api/coverage` (Ninja, in `core/api.py`) is the
area routes may be planned in, as a GeoJSON polygon feature - the
`settings.COVERAGE_BBOX` the route validator enforces, which the map greys
out the rest of. `tests/test_coverage_api.py` holds every edge of it to the
validator.

### Place search and place names: `GET /api/geocode`, `GET /api/reverse`

Both are signed out (PLAN.md's owner amendments of 2026-09-27), in
`core/api.py` and `core/geocode.py`, with the limits in `core/ratelimit.py`.
Search needs Photon (`PHOTON_URL`); names need the standard router
(`VALHALLA_UPSTREAMS["standard"]`) and use Photon only for a nearby place.

```sh
curl -s 'http://localhost:8000/api/geocode?q=1100+Wilson+Blvd&lat=38.89&lon=-77.07&limit=6'
curl -s 'http://localhost:8000/api/reverse?lat=38.90133&lon=-77.260598'
```

| | `GET /api/geocode` | `GET /api/reverse` |
| --- | --- | --- |
| Parameters | `q` (2-200 characters after white space is collapsed), optional `lat` and `lon` together (a bias, inside `COVERAGE_BBOX`), `limit` 1-10 (default 6), `lang` (`en` only, the imported language) | `lat`, `lon` (inside `COVERAGE_BBOX`), `lang` (`en`), optional `address=true` (Go's tapped-spot card) |
| What reaches Photon | the query with US street abbreviations spelled out (`Blvd`, `St`, `Ave`, `Rd`, `Dr`, `Pkwy`, `Hwy`, `Ct`, `Ln`, `Pl`, `Sq`, `Ter`, `N`/`S`/`E`/`W`, `NE`/`NW`/`SE`/`SW`; `geocode.expand_abbreviations` has the rules), the bias with its strength (`zoom` 14 and `location_bias_scale` 0.2, `geocode.BIAS_ZOOM` and `BIAS_SCALE`, so nearby places rank first; the page sends the rider's location when it already has one, else the map's centre), a count a few above `limit`, `lang`, and `bbox` = `COVERAGE_BBOX`; nothing else the request carries | `lat`, `lon`, `lang`, `limit=1`, `radius=0.25` km; with `address=true`, first `layer=house`, `limit=1`, `radius=0.04` km |
| 200 | `{"results": [...], "attribution": [...]}`, at most `limit` results, each inside the box, rows with the same name and OSM key within 300 m folded into one | the same shape, zero or one result |

Each result is `{name, label, lon, lat, kind, osm_type, osm_id, osm_key,
osm_value}`. `label` is the name with up to two of neighbourhood, town, county
and state. The four `osm_*` fields may be null; a client shows what the place
is from `osm_key`/`osm_value` (the front end's `placeType`) and can match a
station to its own records by `osm_type`/`osm_id`. For search, `kind` is
Photon's layer (`house`, `street`, `city`, `district`, `other`, ...). For a
name, `kind` is `trail` or `street` when the name is the road or trail the
point snaps to on the standard router's graph (the nearest named edge within
25 m; a named trail within 5 m of the nearest named edge wins, and a route
number such as "US 29" gives way to the street's name), with
`osm_type`/`osm_id` that way; or `near`, worded "near X", in two cases: the
point is on an unnamed trail and the nearest name is more than 5 m further
off - a street, or another, named trail (X is that edge's name, with its
`osm_type` "W" and `osm_id`); or no
named edge is close enough and X is a place Photon knows, never with a house
number (or `address`, below). Ferry edges never name a point. If the
router does not answer, the name is the `near` one; if Photon does not, the
label has no neighbourhood.

With `address=true` (Go's tapped-spot card; the owner, 2026-10-29: "provide
the address if possible"), a house number and street within 40 m (about 130
ft, `geocode.ADDRESS_RADIUS_KM`) names the point first: `kind` `address`, name
"1234 Franklin Street Northeast", the four `osm_*` fields null. With none that
near, the name is the one above, at the cost of a second Photon call; if
Photon does not answer the first, it is not asked again and the label has no
neighbourhood. Route points never
ask, since the nearest house to a point on a road is a neighbour's.

Refusals, all `{"error": "..."}`: 400 for a parameter above; 403 when the
browser says `Sec-Fetch-Site: cross-site` or `same-site` (refused before it is
counted: any page can make a visitor's browser send a GET); 429 with
`Retry-After` for a spent per-client budget or a geocoding request already in
flight from the client past a second's wait; 503 with `Retry-After` when the
deployment's geocoding slots are still busy after it, or at once when another
request is already waiting; 502 when Photon (search) or both Photon and the router (names) do not
answer in time; 500 for anything else. `tests/test_geocode_api.py` replaces
Photon at `core.geocode._get` and the router at `core.geocode._locate`.

**What a client should do.** Keep one geocoding request in flight for the
page, search and names together - the per-client slot is shared, so a second
concurrent request waits (up to 1 s) and is then refused - and send search
first. The api waits up to a second for one of its two geocoding slots before
answering 503, and names may take only one of the two, so another visitor's
plan being named does not make search busy. A failed name (not an empty one)
is worth asking again later - the front end waits 30 s - rather than showing
coordinates for the rest of the visit. Debounce the search box
(the front end waits 250 ms) and answer only the latest query; ask a name for a
point once, after it stops moving, and cache it by a rounded coordinate. On a
429, 503 or 502 try once more after the `Retry-After` (at most a couple of
seconds), then show the coordinates or "not available". Never put a name in the
link: the fragment is points and ride type, and names are asked again when a
link is opened.

## Intersection costs, the calm search and the detour warning

The whole traffic-stress model (classification, overrides, costs per preset, the stress
number, drawing) is documented in [docs/stress/](stress/README.md).

FOLLOWUP-INTERSECTIONS (2026-10-01, revised 2026-10-02 after the round-1 and
round-2 reviews; OWNER-DECISIONS 133-136, 138, 163-169, 171, 172, 185-188,
194-196; the crossing
costs and the slider's top end are from "Bicycle stress literature in depth",
`reports/LTS-literature-review-2.md` (not in the repository): "Crossing penalties by control type and
right of way", "Left turns, multi-lane merges capped by box turns, and slip
lanes" and "The stress slider's top end"; the Mass Ride flow figures are from
"Mass ride flow evidence", `reports/MASSRIDE-flow-evidence.md` (not in the repository)). Three things,
built on one mechanism: the traffic slider has a top end, a junction costs what
it costs a rider, and a route shows its stressful junctions.

### What Valhalla already does at a junction (measured, read-only, live router)

Valhalla's bicycle costing (3.5.1 to 3.9.1) prices a node through its stop impact and turn
type, a few seconds. Measured on the live standard router (2026-10-01):
`/trace_attributes` over routes along Wisconsin Avenue, Pennsylvania Avenue SE,
K Street, Rhode Island Avenue, Georgia Avenue and Rockville Pike and across
Capitol Hill, Petworth and Takoma, `node.elapsed_time` less each edge's own
length over speed, with `/locate` giving each node's signal flag. Seconds of
transition time per node:

| Movement and place | Nodes | Median | p10 - p90 | Max |
|---|---|---|---|---|
| Straight on, residential cross streets, no signal | 760 | 0.5 | 0.0 - 2.3 | 5.3 |
| Straight on, signalized | 67 | 0.8 | 0.0 - 3.0 | 4.5 |
| Straight across a primary, secondary or tertiary road, from a minor street, no signal | 28 | 3.7 | 3.0 - 4.5 | 5.3 |
| The same, signalized | 15 | 3.7 | 3.0 - 4.5 | 4.5 |
| Right turn, no signal | 33 | 3.0 | 1.2 - 4.1 | 6.0 |
| Left turn, no signal | 33 | 0.9 | 0.6 - 2.3 | 3.8 |

So the built-in intersection cost is a few seconds, the same whether or not
there is a signal (the crossing of a busy road is 3.7 s either way), scaled by
the road class difference and nothing else (not the crossed road's stress,
speed, lanes or volume), and it prices a right turn above a left, the opposite
of the owner's item 166. Against it the literature review's costs are 30 to 100
seconds of riding. The tiles do carry stop, yield and signal flags
(`/locate`'s `edge.stop_sign`, `yield_sign`, `traffic_signal` and the node's own
`traffic_signal`, matched to a traced edge by `edge.id`); `/trace_attributes`
did not return them under 3.5.1 and `/expansion` is not enabled. (From 3.6.0
`/trace_attributes` returns `node.traffic_signal` and `edge.traffic_signal`,
valhalla/valhalla#5121 and #5385, but still no stop or yield flags; the
junction model keeps reading `/locate`.) The router's cost for a
metre of quiet residential street, from the same traces, is 2.2 times its time
(median; 1.8 to 2.9 at `use_roads` 0 to 1).

### Why the mechanism is on the route, not in the graph

The options were derived node tags in the tag transform plus costing
parameters, or approach-edge penalties. Neither can price a movement:

- Valhalla's per-node knobs are `gate_cost` and `gate_penalty` (gate nodes) and
  the country crossing costs (border control nodes), each a flat charge for
  passing the node in any direction, and both already used (narrow gaps; state
  lines, sent as zero). A charge on every busy-road junction would be paid by
  the rider riding along the busy road as much as by the one crossing it, which
  is item 169's opposite.
- The transform sees one way or one node, never the roads that meet at a node,
  so a tag it derives cannot say "a left across four lanes" or "the stopped
  side". A pipeline stage could, but it would be a graph rebuild to try, and it
  would still hand the router only a per-edge number, and an edge's direction
  does not say whether a rider is turning left or right onto it.
- Edge costs scale with an edge's length, so a penalty on the approach edge
  would charge a long approach more than a short one for the same crossing,
  unless the way were split at every junction (the rebuild adds border nodes
  that way; doing it at every busy junction is the most invasive option).

So `routemaker.intersections` reads the traced route. For each node the route
passes (`routemaker.trace_junctions`, from `/trace_attributes` with
`edge.id`, `edge.begin_heading`, `edge.end_heading`, `edge.use`,
`edge.road_class` and `node.intersecting_edge.*`):

1. the movement, from the headings: left, straight or right (35 degrees is
   straight). The trace's indices count in the trace's own `shape`, which the
   router thins of repeated vertices: round 1 read them in the route's shape,
   and on Falls Church to the Capitol 245 of 342 junctions drifted onto the
   wrong node (`trace_junctions.trace_shape`);
2. the roads that meet there, from `/locate` at the node (batches of 50, a
   radius of 1 m so that a service road a fraction of a metre nearer does not
   hide the node; a wider radius is no good for the node itself, since the
   router may then report an edge at the node by another point of it: at
   Rockville Pike and Edmonston Dr the rider's own edge came back 4.7 m away at
   30 m): its directed edges, grouped into arms by way and heading,
   each with whether a car may drive it towards the node and away (one-way or
   not), whether it is a turn channel or ramp, and the stop, yield and signal
   flags of the edges that ARRIVE at the node (an edge leaving it carries its
   far end's). The node is every node `/locate` lists at the in-edge's end point:
   a node exists once per level of the router's hierarchy (Rockville Pike's
   edges end at its level 0 node, Dodge St's at the level 1 node, at one point).
   An answer that does not have the route's own arriving edge is another node,
   and nothing in it is used: that junction is priced on its own roads alone
   (measured: 96 to 100 per cent of busy junctions match on the eight trips
   below, against 81 per cent in round 1);
3. which roads the movement crosses, from the arms' sides: the rider's path
   through the node splits the compass in two. Straight on, a road is crossed
   only where roads leave the node on BOTH sides (a road that continues through,
   or a one-way pair in on one side and out on the other); a road on one side
   only is a side road joining the rider's (a T-junction, a one-way carriageway
   merging or diverging), which the rider on the through road does not cross. A
   left turn crosses what is on the right of its path; a right turn crosses
   nothing. A turn channel or ramp is never a crossed road: it is a slip lane
   (item 169). Round 1 took every road of the busiest tier within 4.4 m of the
   node from the segment table, which read a road's own turn channel, a one-way
   merge or a ramp as a road crossed (26 of 42 red "crossing" events in the
   review's sample were the rider going straight along an LTS 3-4 road), and
   picked the road under a bridge deck;
4. how busy each road is, from the live segment table (one query for the
   route): the segment of each way nearest the node, its LTS and, from the first
   rebuild after this, its speed and through lanes a direction where they were
   read from the map or an agency (`road_speed_mph`, `road_lanes`,
   `road_oneway`; an assumed speed or lane count is not stored, so a reason never
   states one as fact), and its count where there is one;
5. who has the right of way: a signal at the node, on the rider's approach or on
   any other road's approach (a signal for the cross traffic is a signalized
   junction); else a stop or yield on the rider's approach, on another road's,
   on both (all-way), or none. OSM in the District and Maryland puts the
   signal (and often the stop sign) on the stop-line node 7-30 m before the
   junction, and the router flags the edge that ends there, not the junction:
   round 1 read the junction node only, and the round-2 review found a signal
   flag within 30 m at 49 of the 95 junctions it saw priced as having none (8
   of its 15 reds). So for each node whose control is not already a signal,
   `/locate` is asked again around it with a radius of 30 m (100 ft,
   `trace_junctions.APPROACH_M`), and each road arm, the rider's own included,
   is walked out from the node along edges of the same road (its way or a name
   in common) to 30 m: a signal at a node it reaches makes the junction
   signalized (`core.junctions._Approaches`), on a road's edge arriving there
   travelling towards the junction (the router sets the edge flag by
   `traffic_signals:direction`; an edge flagged at its far end going away is
   the next junction's), or the node's own flag where no edge there is
   flagged. The walk stops at, and does not count, a node that a road of a
   name none of the junction's arms has joins: that is another junction
   (review r3, B1: of six driveways and side streets within 30 m of another
   junction's signal, all six had taken it). A rider arriving on a path
   (footway, path, cycleway, crossing way, steps, track: `TRAIL_USES`) is let
   past such a node, since a trail crossing beside a road junction is crossed
   on that junction's signal. A rider leaving a driveway, a parking aisle or a
   drive-through is not (gate 1, B1: five such lefts onto Randolph Rd, Powder
   Mill Rd and Connecticut Ave NW, 35-90 ft (11-27 m) from a signal, had taken it; they
   are 1,800 to 4,500 ft again). The rider's own edges before the junction
   within 30 m along the route (`RawJunction.back_edge_ids`) are read too, up
   to the first that arrives at another road's junction (the rider has passed
   it: a left off 17th St SW 18 m past the Constitution Ave signal): a stop
   or yield sign there is the rider's, a signal the junction's. The first,
   1 m answer is read for what is at the node only; a node with no signal
   there is asked again at 30 m, which shows the roads joining up the arms. A stop
   sign up a cross road is NOT read as the cross traffic's: it may be another
   junction's, and reading it would price the rider as having priority (25 ft);
6. the nodes of one junction share its strongest control: junctions within
   45 m along the route about a road with a name in common (the roads crossed,
   turned onto or turned off, not the road ridden straight along) take a
   signal, else an all-way stop, from any of them (`share_controls`; a stop
   sign is one approach's and is not shared). At Plyers Mill Rd and Columbus
   Circle one carriageway's node read the signal and the other's did not. Two
   such junctions are one only where the rider reaches the later by the
   earlier one's road out, and a road both are about, other than that road
   (riding along it between them is a jog: left onto Main St, then right off
   it at a signal 35 m on, review r3 B2), is crossed at one of them: two
   carriageways crossed, a turn off one and a crossing of the other, a
   crossing of one and a turn onto the other (Columbus Circle NE). A road
   only turned onto at one and off at the other is two junctions;
7. the model's cost and severity.

Grade-separated crossings need no case: a bridge or underpass shares no node
with the road it passes, so there is no junction for the model to price.

### The model, and the proposals for the owner

Feet of equivalent quiet-street riding, in `routemaker/intersections.py`, every
number a named constant. They are PROPOSALS taken from the literature review's
table, within its ranges, for the owner to move:

| Situation | Constant | Proposed | Review range and basis |
|---|---|---|---|
| Straight across an LTS 3 road, from the stopped side | `STOPPED_CROSSING_FT[3]` | 1,200 ft | 800-1,600 ft (Eugene 818 ft; Broach 10-20k ADT 6-10% a mile) |
| A turn off one busy road onto a busier one, or with a stop on the rider's side (review r1, B3) | `MOVEMENT_FACTOR_ONTO` on the crossing above | the stopped side's: 1,800 ft for a left onto LTS 3 from a stop, up to 4,500 ft onto LTS 4 | stopped side against free-flowing traffic (item 169) |
| Straight across an LTS 4 or Avoid road, stopped side | `STOPPED_CROSSING_FT[4]`, `[5]` | 3,000 ft | 2,500-3,500 ft (Broach 20k+ ADT, 1,700-3,260 ft) |
| Scaled by the crossed road's speed | `SPEED_FACTORS` | 0.8 at 25 mph, 1.0 at 35, 1.3 past 45 | Oregon's tables by speed |
| Scaled by its width | `LANE_FACTORS` | 1.0, 1.1 (two lanes a direction), 1.25 wider | a longer crossing |
| Scaled by its volume, where there is a count | `VOLUME_FACTORS` | 0.85 under 5,000 to 1.2 over 20,000 | Broach ADT bands |
| Rural: 45 mph and over, stopped side | `RURAL_SPEED_MPH`, `RURAL_FACTOR` | x1.25 | "rural drivers do not expect bicycles"; Oregon R2-R4 |
| At a traffic signal | `SIGNALISED_CROSSING_FT` | 150 ft (LTS 3), 300 ft (LTS 4, 5) | 100-200 ft, mostly delay (Broach signal 2.1-3.6% a mile) |
| All-way stop | `ALL_WAY_STOP_FT` | 75 ft | 50-100 ft (Broach stop 0.5-0.9%; Arlington -1) |
| On the free-flowing side, cross traffic controlled (item 169) | `PRIORITY_SIDE_FT` | 25 ft | 0-50 ft |
| A trail crossing with no signal flag at it or within 30 m up the roads it crosses: a mapped crossing way, or a path, trail, cycletrack or sidewalk meeting the road at a node of its own | `MARKED_CROSSING_FACTOR`, `MARKED_CROSSING_MAX_SEVERITY` | x0.5, and never drawn red, worded "no signal mapped" as at any junction | item 185; from FOLLOWUP-SIGNAL-DERIVE a crossing node or crossing way tagged `crossing=traffic_signals` (or `crossing:signals=yes`) reaches the router's flag, so this is the crossing with no signal mapped on either. Round 1 said the Pennsylvania Ave and Virginia Ave cycletracks had no flag on the road's arms; that was wrong: the round-2 review found one within 30 m at 31 of 48 trail crossings, and those now read as signalized |
| A divided road's two carriageways, crossed at one junction | `MEDIAN_REFUGE_FACTOR` | counted once, the costlier, x0.75; only two or more crossings, each of a one-way road of its own ways, with a name in common, never a turn or a slip lane with a crossing | items 185 and 196 ("x0.75 (Recommended)"); Mineta and Oregon read a refuge as a level lower (about x0.4 by the base costs), 0.75 keeps an unsignalized divided LTS 4 crossing red |
| Straight on along the same road (its way, or a name in common) where its tier rises | `Junction.continues` | no "Joining" cost | review r2: S Stonestreet Ave and Nebel St (1,200 ft), West St in Annapolis (3,000 ft) were "Joining" the road the rider was already on |
| Left onto a busy road (item 166) | `MOVEMENT_FACTOR_ONTO["left"]` | x1.5 of the crossing | Copenhagen 154 ft left against 62 ft right; the review: lefts 2-3 times rights |
| Right onto a busy road (item 166) | `MOVEMENT_FACTOR_ONTO["right"]` | x0.1 | "close to 0" |
| Left off an LTS 3 road, across its oncoming lanes | `LEFT_ACROSS_ONCOMING_FT[3]` | 600 ft | BELOW the review's 800-1,600 ft LTS 3 crossing range (a left across one oncoming lane from a lane the rider holds, Oregon's vehicular left at LTS 3); an owner question |
| Left off an LTS 4 road | `LEFT_ACROSS_ONCOMING_FT[4]` | 1,500 ft | Oregon, LTS 4 (capped below) |
| ... where the road is one-way ("unless it's a 1-way", item 133) | | 0 | no oncoming traffic |
| ... at a signal | `SIGNALISED_LEFT_FACTOR` | x0.4 | its own phase |
| Merging across lanes to reach a left (item 167) | `MERGE_FT_PER_LANE`, `BOX_TURN_CAP_FT` | 250 ft a lane, capped at 500 ft | the review's two-stage box turn, 200-500 ft |
| At a signal, the whole left off a busy road (item 186) | `BOX_TURN_CAP_FT` | at most 500 ft, oncoming lanes and merge together | "Cap at box turn": a left never costs more than the two-stage box turn (round 1: 910 ft for two lanes a direction on LTS 4) |
| A right turn off a busy road | `RIGHT_FROM_BUSY_FT` | 15 ft | |
| A slip lane the route crosses (items 169, 195) | `SLIP_LANE_FT`, `SIGNALISED_SLIP_FACTOR`, `core.junctions.crossed_links` | 800 ft, x0.5 at a signal; none riding straight past it along the road | "at least an LTS 3 unsignalized crossing, about 800 ft"; 195: "Flag only when you cross it (Recommended)" |
| LTS 1-2 meeting LTS 1-2, with a stop sign (item 171) | `NEIGHBOURHOOD_STOP_FT` | 10 ft, never flagged | the owner's account that DC lets bikes roll through when safe; not legal advice |
| Cap | `MAX_CROSSING_FT` | 4,500 ft | |
| Junctions within 45 m along the route | `MERGE_WITHIN_M`, `MERGED_SHARE` | one junction: a divided road's carriageway crossings counted once with the refuge credit (one way crossed twice: once, no credit), then the costliest event and half of each other's cost, a turn and a crossing of the same road included; the colour never above the worst single event's | item 185: "A merge must never raise the colour of one road's crossing"; review r2: a right onto an arterial and a left off it 30 m later had cost less than the left alone |

**Option C, current values (OWNER-DECISIONS 467, 468, 468a; 2026-10-09).** The table
above is the model as first proposed (2026-10-01); these constants replaced it. Costs are
said in calm miles, US first, km in brackets (5,280 ft = 1 calm mi). The ordinary tiers are
at the top of the literature's ranges; the severe tier (unsignalised, LTS 4 or Avoid) is
above the literature, the owner's choice (467: "intersections that I'd detour 2 miles to
avoid, though rare").

| Constant | Was | Now | Calm miles [km] |
|---|---|---|---|
| `STOPPED_CROSSING_FT` LTS 3 / 4 / Avoid | 1,200 / 3,000 / 3,000 | 1,600 / 4,000 / 4,000 | 0.30 / 0.76 / 0.76 [0.49 / 1.22 / 1.22] |
| `SIGNALISED_CROSSING_FT` LTS 3 / 4 / Avoid | 150 / 300 / 300 | 150 / 600 / 600 | 0.03 / 0.11 / 0.11 [0.05 / 0.18 / 0.18] |
| `LEFT_ACROSS_ONCOMING_FT` LTS 3 / 4 / Avoid | 600 / 1,500 / 1,500 | 800 / 4,000 / 4,000 | 0.15 / 0.76 / 0.76 [0.24 / 1.22 / 1.22] (a left off an unsignalised LTS 4 road costs as much as crossing it from a stop) |
| `SLIP_LANE_FT` | 800 | 1,000 | 0.19 [0.30] |
| `MERGE_MILES_PER_LANE` LTS 3 / 4 / Avoid | 250 ft a lane (all) | 0.15 / 0.30 / 0.30 mi a lane | 792 / 1,584 / 1,584 ft a lane, x the speed rise below |
| Merge speed rise (the severe speed factors, never below 1) | none | 1.2 at 40 mph, 1.4 at 45, 1.6 above | |
| `BOX_TURN_CAP_FT` (a left at a signal, whole) | 500 | 750 | 0.14 [0.23]; not applied where OSM maps a bike box: the router data carries no such tag |
| Severe tier speed factors (LTS 4, Avoid) | 1.1 / 1.2 / 1.3 at 40 / 45 / above | 1.2 / 1.4 / 1.6 | |
| Severe tier lane factors | 1.1 / 1.25 | 1.25 (two lanes a direction) / 1.6 (three or more) | |
| Rural factor (45 mph and over) | stopped side only | also a left off a severe road | |
| Unposted speed (469, 469a) | none | the jurisdiction's statutory default (`stress.statutory_default_mph`, stored as `road_default_speed_mph`): the District 20 mph (alleys 15); Maryland 30 in an urban area (35 divided), 50 elsewhere (55 divided); Virginia 25 in an urban area, 55 elsewhere, 35 unpaved; where the state is unknown, the classifier's assumption. Any tier, for cost only, never said. An assumed speed inside an urban area never adds the rural factor | on a table built before that column, `UNKNOWN_SPEED_SEVERE_MPH` 45 mph for an LTS 4 / Avoid road (468's stopgap) |
| `MAX_CROSSING_FT` | 4,500 | 10,560 | 2.00 [3.22] |
| `ORANGE_MIN_FT` | 600 | 800 | 0.15 [0.24] |
| `RED_MIN_FT` (and the search trigger `REFINE_MIN_EVENT_FT`) | 2,000 | 3,100 (2,900 in 468; raised 2026-10-10, below) | 0.59 [0.94] (was 0.55 [0.88]) |
| `TIME_FACTORS`, `NIGHT_URBAN_FACTOR`, `NIGHT_RURAL_FACTOR` (468a, 469c-469e) | none | weekday rush x1.25 (x2, `UNSIGNALISED_RUSH_FACTOR`, giving way to an LTS 4 or Avoid road no signal stops, and a crossing, join or left there never under 1.86 calm mi [3.0 km], ten minutes' riding, `UNSIGNALISED_RUSH_MIN_FT`: 2026-10-23), weekday off-peak (to 9 PM) x1.0, weekend daytime x0.85, night (9 PM-7 AM, any day) x0.5 in a Census urban area and x0.85 outside one | on busy-road junctions only; the crossed road's `road_urban` decides, and where a table has no such column, x0.85 |

The ride time is the plan's `when` (`weekday_rush`, `weekday_offpeak`, `weekend`, `night`).
The owner's words: "Put some more intersection stress during rush hour too and a little less
on weekends and off hours" (468a); "Evenings are probably 1x till about 9. Then reduced to
about half to 7" (469c); "in most cases, intersection stress is a lot lower. At least on the
city" (469d); "Yes, do that for rural areas" (469e, x0.85 outside urban areas). The rush
windows are the existing 07-10 and 16-19 (469c: "existing is fine"). These are typical values,
not measured ones: the literature's peak-hour figure is a small Portland wearable study
(about 1.75 times the stress at peak), and nothing published gives a night factor. The two new
segment columns, `road_default_speed_mph` and `road_urban`, arrive with the next rebuild;
until then an unposted LTS 4 road is read at 45 mph and every night junction at x0.85.

The factor is applied before the colour, so a rush-hour plan has more orange and red
junctions and refines more often (the red trigger reads the factored cost), and a night plan
fewer. A signalised left stays at the box-turn cap at every hour (468: "box-turn cap at
signals"), so rush hour never lifts one to orange.

**Red from 3,100 ft (owner, 2026-10-10: "Raise red slightly").** The 468 sample re-run
on 2026-10-10 showed that 21 of its 38 rush-hour orange-to-red changes were one case: an
ordinary unsignalised left onto an LTS 3 road, 0.45 calm mi [0.73 km; 2,400 ft], times 1.25
at rush hour = 0.57 calm mi [0.91 km; 3,000 ft], pushed just over the 2,900 ft line by the
factor. `RED_MIN_FT` (and with it `core.refine.REFINE_MIN_EVENT_FT`, which is defined as
`RED_MIN_FT`) is now 0.59 calm mi [0.94 km; 3,100 ft], so that left stays orange at rush hour
(`tests/test_intersections.py`,
`TestTimeOfDay.test_a_plain_left_onto_an_lts3_road_stays_orange_at_rush_hour`). This is the
recommended option on the owner's decision card, not yet confirmed. Off-peak it also turns
a few junctions from red to orange: those costing 2,900 to 3,099 ft, such as a stopped
crossing of a 45 mph LTS 3 road with three lanes each way (3,000 ft), a left onto a 35 mph
LTS 3 road with three lanes (3,000 ft) or a 40 mph one with two (2,904 ft), each with no
traffic count mapped. With none mapped, a stopped crossing of an LTS 3 road is now red
off-peak only at 50 mph or more with three lanes (3,250 ft).

The statutory sources (469, 469a): the District's 20 mph default since 2020-06-01 (DDOT,
https://ddot.dc.gov/page/twenty-mph-20-mph-default-speed-limit-frequently-asked-questions);
Maryland Transportation 21-801.1 (MDOT SHA,
https://roads.maryland.gov/mdotsha/pages/Index.aspx?PageId=295); Code of Virginia 46.2-870
to 46.2-878 and 46.2-1300 (VDOT,
https://www.vdot.virginia.gov/about/our-system/highways/speed-limits/). A business or
residence district is read as inside a Census urban area, and divided as a carriageway of a
divided road (`routemaker.divided`).

Owner 469 also asks that the classifier read the same statutory defaults. It does in the
District (20 mph). In Maryland's and Virginia's urban areas it reads OWNER-DECISIONS 112's MDOT
imputation by class (25-35 mph), which is not the statute; outside them it reads one table for
both states (unclassified and tertiary 50 mph, secondary, primary and trunk 55), where the
statutes differ. Moving the classifier to the statutory figures changes tiers on many roads,
so it is left for the owner to confirm and is not in this change; only junction cost reads them.

`debug_junctions: true` on a route request adds `junctions_debug`, every junction event with
its cost, calm miles, severity, ride-time factor and whether the speed was assumed. The
answer's `intersections` rows carry `calm_mi` and `calm_km`, which the junction list and the
marker's card show ("Costs 0.74 calm mi (1.19 calm km)"), and `time_band`, the ride time where
it moved that junction's cost, which they add in words ("more at rush hour", "a little less at
the weekend", "less at night, when traffic is usually calmer"; 468a). The words give no factor,
so they hold before and after the rebuild that brings `road_urban` (docs/stress/intersections.md,
section 7).

**Which slip lanes are crossed** (item 195, `core.junctions.crossed_links`). The
owner: "Flag only when you cross it (Recommended)"; "no marker when the rider
rides straight past it along the road". From the arms at the node and the
rider's movement, as for a road (step 3 above), a turn channel or ramp is
crossed where:

- the rider goes straight across a node with channel arms on BOTH sides of
  their path: a crosswalk or trail across the channel, or a road through it;
- the rider turns left with a channel on the right of the path (the left
  crosses what is there, as it crosses the oncoming lanes);
- the rider goes straight on in a bicycle lane of their own, painted or
  separated (the router's `cycle_lane` `dedicated` or `separated` on the
  rider's edge), where a channel LEAVES the road on the rider's right: the cars
  turning into it cross the lane (the right hook).

Not crossed: riding straight past a channel in the traffic lane or a shared
lane (the owner's case), past a channel merging in from the right, a right
turn, and riding along the channel itself (the route's own way is the channel:
the turn is priced as the turn onto or off the road it is). The right-hook case
was this implementation's reading of "cross"; the owner kept it (item 199,
2026-10-02: right hooks are flagged). The marker says "Crossing a slip lane
off" the road.

Severity, `ORANGE_MIN_FT` 600 and `RED_MIN_FT` 2,000: orange is "higher stress"
and red "very high" (item 172). An unsignalized crossing of an LTS 3 road
(about 1,200 ft) is orange; of an LTS 4 road (3,000 ft) red; a left onto or
across an LTS 3 road orange, red when the road is fast; any signalized
crossing, the priority side and a neighbourhood stop sign are neither; a trail
crossing with no signal mapped is orange at most, whatever its cost (item 185),
and a merge never raises a colour. The thresholds are unchanged (item 185: "keep
the thresholds for now"). On a
Mass Ride (`assess(..., group=True)`) the colour is the crossed road's tier
instead (item 138): orange for LTS 3, red for LTS 4 or Avoid, a left across a
one-way road none.

### The calm search, and the slider's rescale

Valhalla's `use_roads` runs 0 to 1, and at 0 its price on an LTS 3 way is at the
ceiling `docs/DEVELOPMENT.md`, "Graded stress" gives (about 5 to 13 times the
way's time). The old slider reached `use_roads` 0 at 90, so the last ten points
changed almost nothing (the baseline below: Bethesda to the Capitol and Falls
Church to Union Station plan the same route at 90 and at 100). The rescale
(`core.presets.use_roads_for`, mirrored in `frontend/src/lib/dials.ts`):

| Position | `use_roads` | Old position | Calm rate |
|---|---|---|---|
| 0 | 1.000 | 0 | 0 |
| 35 | 0.550 | 45 | 0 |
| 50 | 0.357 | 64 | 0 |
| 70 (Default) | 0.100 | 90 | 0 |
| 80 (the old top; Cargo with passengers) | 0.000 | 100 | 0 |
| 85 | 0.000 | | 0.585 |
| 90 | 0.000 | | 1.824 |
| 95 | 0.000 | | 4.447 |
| 100 (Trailmaxxing, item 194) | 0.000 | | 10.0 |

Links made before the rescale say nothing of it, so a link now carries `v=2`
(`frontend/src/lib/planHash.ts`), and a link without `v` has its `stress`
mapped onto the new scale: old x 70/90 up to the old 90, then 70 + (old - 90),
rounded (review r1, B4). An old Default link (90) opens Default (70), an old
Trailmaxxing link (100) the old top (80) rather than the calm search, and an old
Group Ride link (50) 39 (`use_roads` 0.499 against the old 0.5). Fast now starts
at 10 (`use_roads` 0.871): the old 0.90 sits between the slider's steps of five,
and 10 is nearer than 5 (0.936).

Every route the old slider could plan is one position's of the new. Above 80 the
router's price is as high as it goes, and `core.refine` takes over: it asks the
router for the best route, reads it (the same trace and stress join as the
answer, plus the junctions), excludes the LTS 4 and Avoid stretches with
`exclude_locations` (one point per edge, up to 60 a round, at most 150 in all, the
router's limit being 200), asks again, then excludes every LTS 3 stretch of the
new route as well, and so on, each round's route calmer and longer than the last.
The score of a candidate, in the router's cost seconds:

    router cost + QUIET_COST x (calm rate x (LTS 3 m + 2 x LTS 4 m + 3 x Avoid m)
                                + intersection weight x (events' cost in m)
                                + climb weight x climb in m)

`QUIET_COST` is 2.2 times the time of a metre at the request's speed. The calm
rate is `calm_rate_for(stress)`: 0 to 80, then `CALM_RATE_MAX` (10, a proposal) x
(e^(3t) - 1) / (e^3 - 1) with t the fraction of the way from 80 to 100: "a
steep (exponential) curve above Default". The intersection weight runs from 0.25
at the traffic tolerant end to 1 at Default and up, so turn and intersection
costs stay active at every position; the climb weight is the hills slider's avoid
half (`-hills / 100` x 12 m of riding a metre of climb), so a relaxed ride is not
a zig-zag over a hill. Turn costs and hill costs are costing options and are
sent at every position.

**Uphill stress: one stress figure** (FOLLOWUP-GRADE-STRESS, OWNER-DECISIONS 409). The
owner, 2026-10-05, of Connecticut Ave NW: "It's a bit weird here because of a hill. I'd
definitely ride down it, but not so much up." 2026-10-10, asked how: "Maybe make it
multiplicitive? Hill distance * traffic-relative distance." And 2026-10-11: "Why not
combine it all into a single stress metric? Basically you calculate the uphill portion
and then the traffic stress portion. Multiply the two together." "The sliders control
the various coefficients for each component." "So a fine with hills will basically be
multiplying everything by 1." "We wanted some stress for extreme downhills." So every
stretch of a route counts, in the calm search's stress figures, one figure:

    stress-weighted metres = run x traffic weight(tier) x hill factor
    hill factor            = 1 + hills coefficient x extra

- The traffic weight is the ride's own exposure weight for the tier (LTS 3 once, LTS 4
  twice, Avoid three times; 8 and 16 on the stress-averse ride types; LTS 2 only where
  the ride weighs it), and the stress slider sets how much it counts (the calm rate in
  the score, the stress order and the worth ratio at the top), as before.
- `extra` is the window's extra effort over the flat, in effort-equivalent metres a
  metre (`routemaker.effort`, the standard cycling power model, Martin et al. 1998; 8%
  costs 6.5 times the flat), over the effort model's windows of at least 984 ft (300 m)
  of the router's elevation profile, in the direction ridden: on a climb of `GRADE_FROM`
  (3%) or more, `effort_factor(grade) - 1`; on a descent steeper than the ride type's
  brake grade (`presets.BRAKE_GRADES`, OWNER-DECISIONS 56: 3% on Cargo and Kids, 4% on
  Mass Ride and Bikeshare, 5% on Group ride, 6% on the rest, none on Mountain Goat and
  Fast), what a climb as steep as the excess would be, `effort_factor(grade - brake
  grade) - 1` (the shape of `climbs.descent_cost_s`, which weighs a descent's excess past
  the brake grade as a climb's past 3%); 0 elsewhere, so the factor is 1 on the flat, on
  gentle climbs and on gentle descents.
- The hills coefficient is the hills slider's (`grade_stress.coefficient_for`):
  `FACTOR` (0.25) at the detent, rising in proportion to the avoid half's weight to 0.5
  at full avoid, and falling with the right half to 0 at its end ("fine with hills", and
  Mountain Goat's seeking end), where every factor is exactly 1. At each ride type's
  starting position: 0.25 on Default, Trailmaxxing, Gravel and Fast; 0.375 on Group ride;
  0.4 on Cargo and Bikeshare; 0.45 on Kids; 0.49 on Mass Ride; 0.125 on E-bike; 0 on
  Mountain Goat.

Each traced piece gets its factor from the windows that overlap it, shared by metres
(`grade_stress.hill_factors`, `refine.hill_of`), and `refine.analyse` sums each piece's
metres times its factor into every stress figure: `exposure_m` (the score), `lts4_m`,
`lts3_m`, `lts2_m`, `avoid_m` and `lts45_m` (the stress order's top and second figures,
the worth rule's saving, `stress_weight_m`), and each leg's LTS 4 (`lts4_by_leg`, the
LTS 4 hold). A long plan's legs are combined from those (`refine.combine`). No consumer
adds the hill on its own. What the rider is shown, the map's LTS colours, the stress
chart, the route summary's LTS miles and the descriptions, is the rated metres, from the
same pieces unweighted (`routing.totals`): the hill only changes which route is chosen.
The calm search's diagnostics (`calm_search`'s `exposure_*`, `lts4_m_*` and `lts3_m_*`)
are the weighted figures.

Two refinements (review of #87, the coordinator's recommended option while the owner
decides; reverted if the owner picks "Only above 80"):
- The hill counts at every slider position. At 80 and below (Default starts at 70) the
  calm rate is 0, so a plain product would drop the hill there and the owner's own case,
  the Connecticut Ave NW climb at Default, would no longer change the default ranking. So
  in the score the hill's share of the exposure (`Analysis.hill_exposure_m`: traffic
  weight x (hill factor - 1) x metres, at the ride's own exposure weights) counts at the
  calm rate where that is over 1 and one for one in quiet metres below it (`max(rate,
  1)`), as #76's term did from Default up; the flat part keeps its rate exactly
  (`flat_exposure_m`). A flat route scores as before at every position, and "fine with
  hills" is still exactly 1. At Default the 0.62 mi (1 km) climb at 6% on LTS 4 adds
  about 2,060 quiet metres to the score, about 15 minutes of the router's cost at a
  quiet cost of 0.44 s a metre. On a ride that weighs LTS 2, the score's LTS 2 term at a
  rate of 0 (`lts3_added_m`) reads the rated LTS 2 metres, so a climb on LTS 2 comes in
  once, through the hill's share.
- The LTS 4 hold (250, on Trailmaxxing, Cargo with passengers and Kids) compares the
  rated LTS 4 metres (`refine.lts4_by_leg`), not hill-weighted ones: leaving out a hill
  never buys more LTS 4, and a climb never refuses a route with no more LTS 4 than the
  router's first. The answer's `lts4_before_m` and `lts4_after_m`, the hold's figures,
  are the rated metres too (`refine.rated_lts4_m`).
- The Traffic-wins guard (OWNER-DECISIONS 61: hill avoidance never makes a route busier;
  `_busier` and the seek's guards) compares the rated exposure (`Analysis.rated_exposure_m`),
  not the hill-weighted one: a route that leaves out a busy 0.62 mi (1 km) climb by riding
  1.24 mi (2 km) of flat LTS 4 is still busier and refused. The group rides' check that a way
  round a junction adds no LTS 4 (`avoid_junctions.group_takes`) reads the rated LTS 4
  metres too (`refine.rated_lts4_m`), as the hold does.
- From 81 to 87 on the stress slider the calm rate is above 0 but under 1, so the hill's
  share counts at 1 while the flat part counts at the rate: there the hill weighs more,
  relative to the flat traffic, than a plain product would.

The worked example: 0.62 mi (1 km) of LTS 4 up 6% at the detent has a factor of about
2.03, so it counts as 1.26 mi (2,030 m) of LTS 4. In the worth rule (435's "One rule",
the owner's "Count it" of 2026-10-11: "A longer route can win by avoiding a busy climb,
so some plans get longer"), at its 1 / 2 / 3 weights:
- what the climb adds over the same road on the flat: about 1.28 mi (2,060 m) of LTS 3,
  which on its own buys about 2.2 mi (3.6 km) of extra riding at 90 on the slider (ratio
  1.7) and 6.4 mi (10.3 km) at 100 (ratio 5);
- the total for avoiding the climb on a quiet street: about 2.52 mi (4,060 m) of LTS 3,
  the road's own 2,000 m and the climb's 2,060 m, which buys about 4.3 mi (6.9 km) at 90
  and 12.6 mi (20.3 km) at 100.
On LTS 3 the climb adds half that; on a quiet street nothing. At 4%, the climb adds
0.43 mi (690 m) of LTS 3 on LTS 3 and 0.86 mi (1,380 m) on LTS 4. A descent of 0.62 mi
(1 km) at 8% on LTS 4 on Cargo (brake grade 3%, coefficient 0.4 at its start) has a
factor of about 2.37: 1.47 mi (2,370 m) of LTS 4 where the flat road counts 1,000 m. The
rule's ratios and targets are unchanged.

The steep-descent term and the hills slider's brake cost are separate steps.
`climbs.grade_cost_s` (a time cost on sustained climbs past 3% and descents past the brake
grade, OWNER-DECISIONS 56) still picks among the router's alternatives on the avoid half
of the hills slider (`routing.choose_gentlest`), before the calm search, and is unchanged:
a steep descent on an LTS 1 path has no traffic weight to multiply, so only that step
prices it. The calm search's score reads the hill-weighted figure and not
`grade_cost_s`; its own climb term (`CLIMB WEIGHT x climb`, the avoid half) is
unchanged. So neither consumer counts a descent twice.

Defaults for the owner to confirm with before and after routes: `GRADE_FROM` 3%, `FACTOR`
0.25, the coefficient's mapping, and the descent term. It is in the calm search only (and
its ranking of the router's alternatives, 435): the router's own costs and the graph are
not changed, so no rebuild. Mass Ride, whose plans the calm search does not run on, is
unchanged. Before and after routes on the live router are still to be measured.

**One rule for the extra miles** (OWNER-DECISIONS 435, the owner's "One rule",
2026-10-10). Below the top of the slider a longer candidate must also be worth its
miles, as at the top: the stress it saves (`refine.stress_weight_m`, metres of LTS 3
with LTS 4, Avoid and the flagged junctions weighted as at the top) must be at least
the metres it adds over `refine.worth_ratio`, which rises with the calm rate from 1
just above 80 to 5 at 100 (`WORTH_DEFAULT`): about 1.2 at 85, 1.7 at 90 and 2.8 at 95,
so at 90 a mile [1.6 km] of LTS 3 saved buys about 1.7 mi [2.8 km] of riding. The score
still decides first. Crossing avoidance alone (80 and below, no calm rate) is
unchanged. The proposal's worked case, 2.75 mi [4.4 km] more for 650 ft [198 m] less
LTS 3 with more flagged crossings, is refused at every position, with a target or
without.

There is no cap on the detour. The search keeps the best-scoring candidate, and
never one that is busier than the router's own route ("Traffic wins", OWNER-DECISIONS
61, said of hill avoidance and carried here): a candidate with more than 2 per
cent and 50 m more LTS 3, 4 and Avoid exposure (`EXPOSURE_TOLERANCE`,
`EXPOSURE_SLACK_M`) is not taken however many crossings it avoids (measured on
the live router, before the guard: Rockville to Silver Spring at the old top of the
slider traded 1.6 mi more LTS 3-4 for fewer crossings). The guard counts the red
junctions' cost (`Analysis.red_m`, quiet metres) as exposure on both sides, one for
one, as it counts an Avoid-rated junction's penalty (2026-10-23, the owner of an
unsignalised crossing of Connecticut Ave at Decatur Ave at rush hour: "essentially
impassable"): on beta the search had excluded both red crossings there and the router
found the way by the Plyers Mill Rd signal, 0.3 mi (0.5 km) longer with 0.2 mi
(0.3 km) more LTS 3 and no red junction, which the guard refused for its LTS 3 alone.
A metre of a red junction's cost is a metre of LTS 3 and, at the standard weights,
half a metre of LTS 4 (weight 2; 8 on a stress-averse ride), so one 4,500 ft (1,372 m)
red crossing still never buys 0.6 mi (1 km) of LTS 4. It stops after two rounds that do not improve it, when no route is left (every way
out excluded: asked again once with only the LTS 4 stretches), when a round
cannot be started with five seconds left, and never excludes within 500 m of the
route's ends or of a via point (a trailhead's only way out is often the one busy
road). `calm_search` in the answer says what it did; `limited` is `time`,
`no_route`, `untraceable` or, where it did not run, `span` (past 19 mi
[30 km] apart), `long_ride`, `points` (a start only), `seeking` (the hills
slider's climb search uses the alternatives) or `mass_ride`.

**The router's own alternatives** (OWNER-DECISIONS 435, 2026-10-05: "Yes, rank
alternatives by our own stress measures"; found comparing a planned route with a
ridden one: the search only rerouted around the router's first route and never
looked at the router's own alternatives). Wherever the calm search runs (above
80, `Context.rank_alternates`), before its first round it asks the router once for
the same route with `alternates` 3 (`refine.ROUTER_ALTERNATES`, the service's
`max_alternates`), reads each alternative (its trace, stress and junctions) and
ranks it with the first route by the rule every candidate meets (`refine.better`:
below the top of the slider the score above, so the slider's rate sets how much
distance a metre of LTS 3 avoided is worth; at the top the stress order and the
worth of the extra miles) and the same guards (not busier than the first route, the
LTS 4 hold, junctions read, within the ceiling). The rounds then start from
whichever ranks first, so their exclusions are that route's busy stretches; the
Traffic-wins guard and the LTS 4 hold stay the router's first route's. At the top
of the slider every alternative that passes the guards also joins the routes the
rider is offered (`candidates`).

Where the plan already asked for them with the same request (the hills slider's
avoid half, `Context.router_trips`) those are ranked and none is asked again, and
where that ask timed out none is asked at all; a route the target fitting
(`_fit_target`, `_past_target`) asked for again with another costing gets the
search's own ask. The ask and the readings end `ALTERNATES_ROUND_RESERVE_S` (6 s,
a round's least and a second) before the search's own end, so at least one round is always
left (the rounds were the whole calm search before 435), and the ask is not
started with less than `ALTERNATES_MIN_S` (1 s) left before that; the weekend
router's ask is held to its own `WEEKEND_TIMEOUT_S`.

`calm_search.alternates` (`api.AlternatesOut`) says how many routes the router gave
other than the one the search starts from (`given`: where the hills slider chose
one of the router's alternatives, the router's first route is one of them), how
many passed the guards (`ranked`), whether one was taken (`taken`), and `limited`,
`time` where the ask or a reading ran out of its time (the search's own `limited`
is unaffected: its rounds still run). It is null where none were asked for: a plan
with stops or a loop (Valhalla gives alternatives between two locations only), a
long calm plan's legs (each has only its share of the time, and alternatives
roughly double a long leg's route; "Time, alternates and limits" below), or too
little time left. The ask is one more `/route` (with alternatives: on the live
router a warm 7.5 mi [12 km] route went from 0.2 s to 1 to 2 s with them, the
climb search's measurements at `routing.SEEK_MAX_SPAN_M`) and a reading of each
alternative. Not measured on the live router from this branch (it was built where
the router cannot be reached; docs/OPERATIONS.md, "Cost per plan", has the check to
run after deploy). The detour acceptance rule decision 435 asks to revisit is
the owner's "One rule" ("One rule for the extra miles", below).

Crossing avoidance is the same search with the approaches to the worst junctions
(the red ones, from `REFINE_MIN_EVENT_FT` = `RED_MIN_FT`, 2,000 ft; three a
round) as the exclusions, one round, at every position but Mass Ride's: the new
route is kept if its score, router cost plus the junction events, is lower. An
approach is the point half way along the edge the route arrives by,
interpolated; a calm sample is the interpolated middle of a traced edge (edges
under 6 m are not sampled): round 1 used a vertex, which on a two-vertex edge is
the upstream node, and an exclusion on a node takes out every edge there, the
cross street's too.

Round 1's review found four more things the search now does:

- A candidate whose junctions could not be read (the database or the router
  failing) is not taken: it would score as having none.
- An exclusion list is never sent twice, and never longer than the router's
  limit: what does not fit is not asked for, and a full list ends the search
  (`limited: "excludes"`).
- How many search at once is the api's routing slots: the search runs only
  inside an api routing request, which holds one of the deployment's
  `ROUTING_CONCURRENCY` advisory-lock slots (3 on compose's 7 workers), and a
  long ride never runs it, so at most three run at once, under each router's
  four threads. Round 1 added a slot of its own (one a process, three a
  container, by lock files); the round-2 review found it could never be the
  limit, and it is gone, with `limited: "busy"`.
- `limited` is then `time`, `no_route`, `untraceable`, `excludes`, or where it
  did not run `span`, `long_ride`, `points`, `seeking`, `mass_ride`. Where the
  rider asked for the calm detour (above 80, not Mass Ride) the planner says
  `time`, `untraceable`, `span`, `long_ride` and `seeking` in plain words under
  the route ("The calmer-route search ran out of time, so there may be a
  calmer route than this one."; `frontend/src/lib/summary.ts`,
  `calmSearchNote`).

**Time, alternates and limits** (live router, 2026-10-01): a calm round is a
`/route` (0.5 to 1.5 s), a `/trace_attributes` (0.1 to 0.3 s), the stress and road
joins (0.1 to 0.5 s) and up to four `/locate` calls (0.3 to 0.6 s each), 1 to 3 s a
round. On a quiet host a Default plan took 0.2 to 3 s (1 to 3 s before) and a plan
above 80 1 to 8 s over the 16 trips above; the same plans with other jobs loading
the host took 4 to 17 s, and the first plan after a process starts a few seconds
more. All inside the 40 s budget (`routing.PLAN_BUDGET_S`; the search's own
is `REFINE_BUDGET_S`, 14 s, and it keeps `REFINE_TRACE_RESERVE_S` for the answer).
The router's limits are not in the way: `max_exclude_locations` is 200,
`max_alternates` 3 (the calm search asks for all three once, below) and
`max_distance` 500 km. Where long calm detours are NOT found:

- starts and ends more than 19 mi (30 km) apart, on a long ride, and rides
  with more than a start and an end where the hills slider is seeking (the
  search says so, `limited`);
- a start or end whose only way out is a busy road (the first 500 m are never
  excluded), so the stretch at each end stays: the Bethesda to Capitol ride
  keeps its first LTS 4 stretch at every position;
- places with no calm connection at all: every exclusion leaves no route, and
  the search ends (Columbia to Baltimore keeps its LTS 3 at 100);
- where the router's best route is already the calmest it can find, which is not
  a failure (Old Town to Mount Vernon, Reston to Leesburg).

**Measured before and after, round 0** (live router and segment table, 2026-10-01, a
quiet host, `when=weekend`, Default's other settings; each cell is the route's
length and the miles of it on LTS 3, 4 and Avoid; "before" is the deployed
code at the old positions 90 and 100, "after" this branch at the same routes'
new positions 70 and 80 and above them):

| Trip (straight line) | Before, old 90 | Before, old 100 | After, 70 | After, 80 | After, 90 | After, 100 |
|---|---|---|---|---|---|---|
| Rockville - Silver Spring (9.2 mi) | 11.0, 5.2 | 12.5, 3.1 | 11.0, 5.2 | 12.5, 3.1 | 13.7, 1.7 | 14.1, 1.9 |
| Bethesda - Capitol (8.0 mi) | 12.0, 1.3 | 12.0, 1.1 | 12.0, 1.3 | 12.0, 1.1 | 13.3, 1.7 | 13.3, 1.7 |
| Falls Church - Union Station (8.9 mi) | 11.5, 1.5 | 11.5, 1.5 | 11.5, 1.5 | 12.7, 0.9 | 12.7, 0.9 | 12.7, 0.9 |
| Vienna - Georgetown (10.9 mi) | 12.9, 0.5 | 12.9, 0.5 | 13.3, 0.3 | 13.3, 0.3 | 13.6, 0.2 | 13.6, 0.2 |
| Laurel - College Park (9.5 mi) | 13.4, 6.0 | 13.7, 5.9 | 13.4, 6.0 | 13.7, 5.9 | 16.6, 5.3 | 16.6, 5.3 |
| Old Town - Mount Vernon (7.1 mi) | 10.5, 0.0 | 10.5, 0.0 | 10.5, 0.0 | 10.5, 0.0 | 10.5, 0.0 | 10.5, 0.0 |
| Reston - Leesburg (15.5 mi) | 16.9, 0.0 | 16.9, 0.0 | 16.9, 0.0 | 16.9, 0.0 | 16.9, 0.0 | 16.9, 0.0 |
| Columbia - Baltimore (14.5 mi) | 20.2, 7.7 | 20.3, 7.6 | 20.2, 7.7 | 20.3, 7.6 | 20.3, 7.6 | 20.3, 7.6 |
| Silver Spring - College Park (4.8 mi) | | | | 6.3, 2.3 | 7.1, 0.6 | 7.1, 0.6 |
| Courthouse - Mount Vernon (12.5 mi) | | | | 19.3, 0.3 | 20.0, 0.1 | 20.0, 0.1 |
| Silver Spring - Laurel (12.0 mi) | | | | 16.9, 8.5 | 17.4, 8.3 | 17.4, 8.3 |

What it shows. Positions 70 and 80 plan the old 90 and 100's routes, to the
mile (Falls Church - Union Station at 80 is the one place crossing avoidance found
a calmer route, 1.2 mi longer with 0.6 mi less LTS 3-4). Above 80 the slider now
does what the old top could not: Rockville - Silver Spring goes from 5.2 mi on
LTS 3-4 at Default to 1.7 mi at 90 for 2.7 mi more riding, Silver Spring - College
Park from 2.3 to 0.6 mi. Where it does not: 90 and 100 plan the same route on most
trips, because the search's candidates are nested and the detour per metre of
busy road a calm candidate costs is almost always under the rate at 90 (1.8); only
the rare candidate dearer than that (Rockville - Silver Spring) needs the top. And
on trips whose busy stretches have no calmer way round within the router's reach
(Columbia - Baltimore, where every exclusion leaves no route; Laurel - College
Park, where excluding its LTS 3 edges sends the router onto LTS 4 roads, which
the guard against a busier route refuses) the route stays; Alexandria - Fort
Washington and Frederick - Urbana did not move above 80 either. Time, a quiet host, `core.routing.plan` in a proof container
against the live routers: 0.2 to 3 s at Default and 1 to 8 s above 80
(the same container under load from other jobs: up to 17 s at Default).

**Bowie - Annapolis no longer reproduces.** Round 0 reported Bowie - Annapolis
at 90 and 100 as 31.4 mi with 10.5 mi of LTS 3-4, the biggest gain of the top
end. That result does not reproduce: through the review harness, at 100, both
the round-0 code (c1b52e3) and round 1's (f9b08e2) end with `no_route` and keep
the router's own 21.2 mi route (13.4 mi of LTS 3-4), because every exclusion
round leaves the router no route at all (review r2). It is not a regression of
round 1, and the round-0 row is dropped from the table above; the tables below
are the measured ones.


### Round 1, re-measured (2026-10-02)

**How it was measured, and what that means.** The round-1 code was run against
the live routers and live map data without a proof container on the live
network (which the session's permissions did not allow): `core.routing.plan`
ran on the WSL host, its router calls forwarded read-only (`/route`,
`/trace_attributes`, `/locate` only) through a process in `routemaker-api-1`,
and its segment table was a scratch database filled, for every edge the router
answered with and every edge at the nodes of every traced route, with the tier
the live stress tiles (`/tiles/stress/14/...`, the public endpoint) draw for
that edge, matched by geometry and heading. So the tiers are the live table's,
as the tiles draw them, the speeds and lanes are absent (as live until the
rebuild), and a route's facility split is not measured. Both the code before
(c1b52e3, in a throwaway worktree) and after ran through the same harness on
the same data; each plan was run twice and the second timed, the harness's own
work excluded from the plan's clock. The trips' points are the harness's own,
not round 0's, so their counts are not comparable with round 0's "15 red in 11
mi" (the same trip from round 0's points).

**Markers at Default (70)**, each route's miles and miles on LTS 3 and worse,
then red and orange markers:

| Trip | Before (c1b52e3): route | Before: red, orange | After: route | After: red, orange | After, by kind |
|---|---|---|---|---|---|
| Rockville - Silver Spring | 10.3 mi, 4.4 | 12, 5 | 10.3, 4.4 | 1, 9 | red: 1 crossing; orange: 3 trail crossings, 2 slip lanes, 4 turns onto or off busy roads |
| Bethesda - Capitol | 12.0, 1.3 | 15, 12 | 12.1, 1.3 | 0, 15 | orange: 10 trail crossings (the Virginia Ave and Pennsylvania Ave cycletracks), 2 slip lanes, 3 turns |
| Falls Church - Union Station | 10.5, 1.4 | 8, 12 | 10.5, 1.4 | 2, 14 | red: a crossing, a left across; orange: 10 trail crossings, 2 slip lanes, 2 turns |
| Silver Spring - College Park | 8.2, 2.6 | 6, 5 | 7.2, 2.2 | 1, 5 | red: a left onto; orange: 2 slip lanes, 3 turns |
| Bethesda - Silver Spring | 4.7, 0.8 | 4, 5 | 4.7, 0.8 | 2, 1 | red: 2 crossings; orange: a turn |
| Laurel - College Park | 11.6, 7.2 | 17, 13 | 11.6, 7.2 | 0, 21 | orange: 15 slip lanes (US 1), 4 trail crossings, 2 others |
| Poolesville - Darnestown (rural) | 8.8, 7.3 | 5, 1 | 8.8, 7.3 | 0, 3 | orange: 2 slip lanes, a left onto |
| Bowie - Annapolis | 21.2, 13.4 | 17, 9 | 21.2, 13.4 | 4, 11 | red: 2 crossings, 2 joins of a busier road; orange: 11 |
| **All eight** | | **84, 62** | | **10, 79** | |

What moved them: the router's own edges at the node (B1: 77 red "crossing"
events before, 6 after; a road's own turn channel, merge or ramp is no longer a
crossing), the trace's own shape (B2a: before, junctions on drifting routes sat
on the wrong nodes), the control from the right node with a signal on any
approach (B2), the divided-road refuge and the no-raise merge (item 185), and
trail crossings with no signal mapped capped at orange (item 185: 28 of the 79
oranges). Slip lanes are the other large share (28), as item 169 asks: a turn
channel the rider rides straight past is now the 800 ft slip lane, not a 3,000
ft crossing. Six of the eight routes are the same line before and after. Two
differ by crossing avoidance: Silver Spring - College Park, where round 1's
false reds had taken a route 1.2 mi (1,938 m) longer and the new reading takes
one 0.15 mi (245 m) longer, and Bethesda - Capitol, 0.1 mi (138 m) longer round
a red crossing. /locate matched the route's own edge at 96 to 100 per cent of
busy junctions (round 1: 81 per cent).

Time at Default, the plan alone: 0.15 to 1.2 s. Router calls: on six trips the
router's own route still had a red junction 500 m or more from both ends, so
crossing avoidance asked for a second route (2 routes, 2 traces, 3 to 11
`/locate`s); on the other two 1, 1 and 2 to 4. `/locate` is now asked at every
busy-class junction (round 1: only where the right of way changed the cost),
one call for each 50.

### Round 2, re-measured (2026-10-02)

The same harness as round 1 (above), the same day, a fresh scratch database;
"before" is round 1's code (f9b08e2, in a throwaway worktree), "after" this
branch, on the same data. "Before" reproduces round 1's own "after" exactly (10
red, 79 orange).

**The review's eight signalized reds** (review r2, blocker), through the
review's own probe (`junctions_of_trace`, `events_of`, the live router):

| Junction | Before | After |
|---|---|---|
| Plyers Mill Rd across Connecticut Ave (two trips) | red, 2,250-2,344 ft, "no signal mapped" | signal, 450-825 ft with the lefts at the same junction, not flagged |
| Rockville Pike across Edmonston Dr | red, 2,250 ft | signal, 225 ft |
| Colesville Rd across East-West Hwy | red, 3,000 ft | signal, 300 ft |
| Veirs Mill Rd across Connecticut Ave | red, 2,250 ft | signal, 225 ft |
| Pennsylvania Ave cycle track, left onto 3rd St NW | red, 3,375 ft | signal, 458 ft |
| Dupont Circle | red, 3,000 ft | signal, 300 ft |
| Veirs Mill Rd channel at Rockville Pike | red, 3,200 ft | signal, 450 ft |
| Columbus Circle, Union Station | red, 3,125 ft | signal, 425 ft |

Each "after" is the merged junction's cost; none is flagged. Of the review's 15
reds the other seven stay red, as they should: a driveway
left onto Rockville Pike, the left onto 16th St NW across its median at
Jonquil St (the stop sign 16 m up Jonquil St is the cross traffic's approach,
not the rider's, and is not read as the cross traffic's: still 4,500 ft), three
Bowie - Annapolis crossings with nothing mapped within 30 m, and one "Joining"
of a road of another name; the eighth, West St in Annapolis, was the rider
staying on the same road and is now nothing (SHOULD_FIX 1). A stop sign 16 m up
the rider's own approach is read as the rider's (`tests/test_junctions.py`,
`TestApproaches`).

**The review's 95 junctions priced as having no signal** (`nonectl.json`): 66
had a signal flag of some kind within 30 m in the review's search (an edge or a
node), and 63 of those now read as signalized: 13 of 13 road crossings, 47 of
49 trail crossings, 3 of 4 turns. The three that do not: the Virginia Ave
cycletrack's crossing of Virginia Ave NW at G St (on two trips), whose only
flag is on the far carriageway's approach, which the crossed carriageway's
arms do not lead to; and a straight-on that is now no event at all (the same
road). The 29 with no flag within 30 m are unchanged. /locate still matches the
route's own edge at 1,265 of 1,278 busy junctions (98.98 per cent), as in round 1:
the node is read from the 1 m answer, the approaches from the 30 m one.

**Markers at Default (70)**, each route's miles and miles on LTS 3 and worse,
then red and orange markers:

| Trip | Before (f9b08e2): route | Before: red, orange | After: route | After: red, orange | After, by kind |
|---|---|---|---|---|---|
| Rockville - Silver Spring | 10.3, 4.4 | 1, 9 | 10.3, 4.4 | 0, 3 | orange: a crossing, a left onto from a stop, a slip lane crossed by the Millennium Trail |
| Bethesda - Capitol | 12.1, 1.3 | 0, 15 | 12.0, 1.3 | 0, 3 | orange: 2 crossings, a join |
| Falls Church - Union Station | 10.5, 1.4 | 2, 14 | 10.5, 1.4 | 0, 2 | orange: 2 crossings |
| Silver Spring - College Park | 7.2, 2.2 | 1, 5 | 7.2, 2.2 | 1, 2 | red: a left onto; orange: a left off, a join |
| Bethesda - Silver Spring | 4.7, 0.8 | 2, 1 | 4.7, 0.8 | 1, 0 | red: Leland St across Connecticut Ave (both carriageways, no signal) |
| Laurel - College Park | 11.6, 7.2 | 0, 21 | 11.6, 7.2 | 0, 6 | orange: 4 crossings, a left off, a slip lane (the right hook, Contee Rd) |
| Poolesville - Darnestown (rural) | 8.8, 7.3 | 0, 3 | 8.8, 7.3 | 0, 1 | orange: a left onto |
| Bowie - Annapolis | 21.2, 13.4 | 4, 11 | 21.2, 13.4 | 3, 3 | red: 2 crossings, a join; orange: a crossing, 2 lefts off |
| **All eight** | | **10, 79** | | **5, 20** | |

What moved them:

- Signals on the approaches and shared across a junction's nodes (the
  blocker): every "no signal mapped" red at a signalized junction in the sample
  is gone, and so are the trail crossings that sit in a signalized junction's
  crosswalks (31 of round 1's 79 oranges were crossings, 10 are left).
- Slip lanes only where the route crosses them (item 195): 28 slip-lane oranges
  before (15 along US 1 on Laurel - College Park), 2 after: the Millennium
  Trail across the MD 28 channel (the channel on both sides of the trail), and
  a right hook on Contee Rd at Konterra Dr (a channel leaving on the right of a
  rider in a bike lane). Riding past a channel along the road is no longer
  flagged.
- Straight on along the same road (SHOULD_FIX 1): 11 "Joining" events before
  (9 orange, 2 red), 3 after, each onto a road of another name.
- The refuge only for a divided road's carriageways (SHOULD_FIX 2) raises some
  costs (a turn and a crossing of the same road now add) and colours none on
  these trips.

Seven of the eight routes are the same line before and after. Bethesda -
Capitol went 0.1 mi round a false red before; with no red, crossing avoidance
keeps the router's own route. The remaining 25 markers were each checked with
a 30 m signal search: 22 have no signal flag within 30 m; two have stop signs,
read or priced as the rider's (Leland St, and the left with "stop sign on your
side"); the MD
28 slip lane has signal nodes 17-27 m away, at the junction the channel bypasses
(a channel's crossing is not given the junction's signal: free-flowing right
turns are what a slip lane is).

Time at Default, the plan alone: 0.25 to 2.9 s (before: 0.3 to 2.4 s).

**Round 3** (review r3, B1 and B2), the same eight trips at Default, the same
day as a re-run of b7182b6 on the same harness (which gave round 2's numbers
exactly): the same eight lines, and 5 red and 22 orange (were 5 and 20).
Bethesda - Capitol and Falls Church - Union Station each gain one orange, the
left off 17th St SW across it onto the Mall crosswalk 18 m past the
Constitution Ave signal (1,765 ft; it took that signal from Constitution
Ave's own node 18 m back along the rider's way, and by sharing with the right
onto 17th St there).
/locate calls a plan are unchanged (4 to 11); plan time 0.3 to 1.5 s on this
harness. On the review's probes (its 64 side-street routes, its 17 trip runs
and its 15 cases), five of the six driveways it named keep their colour
(lefts onto East-West Hwy, Twinbrook Pkwy, E St NE and Mass Ave NW twice:
1,800 to 4,500 ft), and so does a sixth, a driveway left onto Plyers Mill Rd
(4,500 ft), and 25th St NW joining Juarez Circle at a stop sign 34 m short of
the Virginia Ave signal (3,200 ft, red, B2). The sixth it named, the service
road across Veirs Mill Rd from Gridley Rd, no longer takes the signal at its
own node but shares it with the Gridley Rd node it leaves from, 21 m back
(both crossings of one divided road), so its event stays 225 ft. Every one of round 2's eight signalized
junctions and the review's signalized trail crossings reads as before. One
signal is lost: Plyers Mill Rd straight across Metropolitan Ave, whose signal
is on the Concord St node 16 m away (orange, 1,200 ft; was 150).
`/locate` calls a plan: 4 to 11 (the second, 30 m pass for each node whose
control is not already a signal), against 3 to 11.

Mutation pass (`scripts/mutants_intersections.py`, each mutant against whole
test files, one file per process): 45 new mutants on the round-2 code and the
review's M03, 183 in all; the first pass killed 174, tests closed eight of the
nine survivors and the ninth went with the code it mutated (the second
wording), so all 183 are killed.

**Trailmaxxing at 100** (item 194), against its old start at 80, the same
eight trips, Trailmaxxing's own costing; each cell is miles, miles on LTS 3+,
the length against the most direct legal route ("-" where none was asked
for), the plan's time, then red and orange markers:

| Trip | 80 (before) | 100 (now) |
|---|---|---|
| Rockville - Silver Spring | 10.9, 2.0, -, 2.6 s, 1 and 3 | 14.3, 0.2, 1.48x, 5.4 s, 2 and 11 |
| Bethesda - Capitol | 12.2, 0.9, 1.24x, 5.9 s, 0 and 2 | the same, 4.7 s |
| Falls Church - Union Station | 10.5, 1.4, 1.09x, 1.5 s, 0 and 2 | the same, 5.8 s |
| Silver Spring - College Park | 7.2, 2.2, 1.08x, 2.3 s, 1 and 2 | 10.1, 1.0, 1.52x, 5.4 s, 1 and 6 |
| Bethesda - Silver Spring | 4.7, 0.8, 1.11x, 0.7 s, 1 and 0 | the same, 1.5 s |
| Laurel - College Park | 13.8, 4.9, 1.35x, 0.6 s, 0 and 4 | 16.9, 4.7, 1.65x, 4.1 s, 0 and 11 |
| Poolesville - Darnestown | 9.7, 6.3, 1.10x, 0.5 s, 1 and 2 | the same, 2.0 s |
| Bowie - Annapolis | 21.2, 13.4, 1.04x, 1.4 s, 3 and 3 | the same (`no_route`), 1.5 s |

Three of the eight take a calmer, longer route (Rockville - Silver Spring from
2.0 mi of LTS 3+ to 0.2 for 3.4 mi more; Silver Spring - College Park from 2.2
to 1.0 for 2.9 mi more, with the detour warning; Laurel - College Park 0.2 mi
less for 3.1 mi more, mostly less LTS 4), and every plan runs the search: 1.5 to
5.8 s against 0.5 to 5.9 s. The longer routes cross more busy roads, so they
carry more markers (Rockville - Silver Spring's 14.3 mi route crosses 13 busy
roads, two of them unsignalized LTS 4). Cargo with passengers stays at 80, and
its routes are unchanged.

### The top of the slider: what 150 would do (item 187, an exploration)

The owner, 2026-10-01: "Make max calm even higher. Let's see what 150 would do.
Trailmaxxing is about relaxation, not commuting." Measured through the same
harness, Default's other settings, `when` the moment of planning, each cell the
route's miles, its miles on LTS 3 and worse, its length against the most direct
legal route and the plan's time (the second of two runs, the harness's own work
excluded):

| Trip | 80 (the old top) | 100 (rate 10) | "125" (rate 447) | "150" (rate 19,027) |
|---|---|---|---|---|
| Rockville - Silver Spring | 10.3, 4.4, -, 1.2 s | 13.9, 0.2, 1.44x, 2.3 s | 13.9, 0.2, 1.44x, 4.2 s | 13.9, 0.2, 1.44x, 3.8 s |
| Bethesda - Capitol | 12.1, 1.1, 1.23x, 2.4 s | 14.1, 1.0, 1.43x, 4.2 s | 12.0, 1.1, 1.22x, 4.2 s | 12.0, 1.1, 1.22x, 3.1 s |
| Falls Church - Union Station | 10.5, 1.4, 1.07x, 1.3 s | 10.5, 1.4, 1.07x, 1.8 s | 10.7, 0.9, 1.09x, 6.4 s | 10.7, 0.9, 1.09x, 4.4 s |
| Silver Spring - College Park | 7.2, 2.2, 1.08x, 1.4 s | 10.1, 1.0, 1.52x, 3.9 s | 10.1, 1.0, 1.52x, 4.1 s | 10.1, 1.0, 1.52x, 3.6 s |
| Bethesda - Silver Spring | 4.7, 0.8, 1.11x, 0.6 s | 4.7, 0.8, 1.11x, 1.9 s | 4.7, 0.8, 1.11x, 1.6 s | 4.7, 0.8, 1.11x, 0.9 s |
| Laurel - College Park | 14.1, 4.6, 1.38x, 0.8 s | 16.9, 4.7, 1.65x, 2.8 s | 16.9, 4.7, 1.65x, 2.7 s | 16.9, 4.7, 1.65x, 1.9 s |
| Poolesville - Darnestown | 8.8, 7.3, -, 0.1 s | 8.8, 7.3, -, 0.9 s | 8.8, 7.3, -, 1.0 s | 8.8, 7.3, -, 0.6 s |
| Bowie - Annapolis | 21.2, 13.4, 1.04x, 2.1 s | 21.2, 13.4, 1.04x, 1.1 s (no route) | the same | the same |

"125" and "150" are the current curve carried on (`CALM_RATE_MAX` × (e^(3t) -
1) / (e^3 - 1), t = (position - 80) / 20): metres of detour accepted per metre
of LTS 3 avoided. At 19,027 the rate is in effect "busy-road metres first,
whatever the length": the score is the router's cost plus the weighted LTS 3, 4
and Avoid metres times 19,027, so the junction costs and the length stop
counting. "-" is where the route was within the straight line's allowance and
no direct route was asked for. Laurel - College Park at 100 rides about the same
LTS 3 and worse miles as at 80, but less of it LTS 4 (the score weighs LTS 4
twice).

What it shows:

- 80 to 100 is where the top end works: four of the eight trips take a calmer,
  longer route (Rockville - Silver Spring from 4.4 mi of LTS 3+ to 0.2 for 3.6 mi
  more; Silver Spring - College Park from 2.2 to 1.0 for 2.9 mi more).
- 100 to "150" changes two of the eight. Falls Church - Union Station rides 0.5
  mi less LTS 3+ for 0.2 mi more. Bethesda - Capitol goes back to the shorter
  12.0 mi route with less weighted exposure but more junction stress (one red
  and 19 orange markers, against none and 10 at 100): at that rate the
  crossings no longer count. The rest are the same: the candidates are nested
  (each round excludes the last one's busy stretches), so a higher rate picks
  among the same few routes, and on Bowie - Annapolis every exclusion leaves no
  route at all.
- "125" plans exactly what "150" does on these trips.

**The wider search.** To give the top end routes the nesting cannot reach,
`core.refine` can also ask the router for the route through a point off the
straight line, either side of its middle at a quarter and a half of the span
(`WIDE_OFFSETS`), as a `through` location, each scored and guarded as every
other candidate (`WIDE_SEARCH_FROM_RATE`, off). Measured:

| Trip | 100 | 100 + wide | "150" | "150" + wide |
|---|---|---|---|---|
| Rockville - Silver Spring | 13.9, 0.2, 2.3 s | the same, 5.6 s | 13.9, 0.2, 3.8 s | the same, 4.3 s |
| Bethesda - Capitol | 14.1, 1.0, 4.2 s | the same, 8.1 s | 12.0, 1.1, 3.1 s | the same, 6.6 s |
| Falls Church - Union Station | 10.5, 1.4, 1.8 s | the same, 5.9 s | 10.7, 0.9, 4.4 s | the same, 10.0 s |
| Silver Spring - College Park | 10.1, 1.0, 3.9 s | the same, 5.1 s | 10.1, 1.0, 3.6 s | the same, 11.1 s (time) |
| Bethesda - Silver Spring | 4.7, 0.8, 1.9 s | the same, 2.5 s | 4.7, 0.8, 0.9 s | the same, 3.7 s |
| Laurel - College Park | 16.9, 4.7, 2.8 s | the same, 3.2 s | 16.9, 4.7, 1.9 s | the same, 2.7 s |
| Poolesville - Darnestown | 8.8, 7.3, 0.9 s | the same, 1.2 s | 8.8, 7.3, 0.6 s | the same, 1.9 s |
| Bowie - Annapolis | 21.2, 13.4, 1.1 s | 39.8, 11.9, 1.96x, 5.0 s | 21.2, 13.4, 1.6 s | 39.8, 11.9, 1.96x, 6.6 s |

It adds four routes, their traces and their junctions to each plan (1 to 6 s on
these trips, 11 s on the slowest, which then ran out of the search's budget)
and changed one route: Bowie - Annapolis, 18.6 mi longer for 1.5 mi less LTS 3+,
with 5 red and 29 orange markers against 4 and 11.

**Not adopted.** Neither "150" nor the wider search is clearly better, so the
slider is unchanged (100 is the top, at a rate of 10) and the wider search is
off (`WIDE_SEARCH_FROM_RATE = None`). The constraint at the top end is the
candidates, not the rate: past about 10 the search keeps choosing among the
same nested few. What would make the top end differ is a candidate generator
that goes looking for calm infrastructure (via points on the trails and
protected lanes near the line, from the segment table) rather than points at
fixed offsets, which is layer 4's candidate search proper.

**The owner's answer** (2026-10-02, OWNER-DECISIONS 194: "Build trail-seeking
search"): Trailmaxxing moves to 100 and Cargo with passengers stays at 80, and
the generator was the backlog item FOLLOWUP-TRAIL-SEEK (PLAN, Owner amendments),
which is what would make a calm setting above 100 mean something. (Superseded:
the generator is built, item 201; see "The trail seek", next.) So:

- Trailmaxxing starts at 100 (`core.presets`, `frontend/src/lib/dials.ts`):
  every Trailmaxxing plan runs the calm search at its top rate, with
  Trailmaxxing's own costing (Cross, low surface avoidance). Its routes and
  times are in "Round 2, re-measured" above.
- Cargo with passengers (item 241; it was "carrying people") stays at 80: a
  heavy bike with a child on it pays for every extra mile and every climb, and
  80 already keeps to low-stress ways unless avoiding them takes much longer.
- The rate stays at 10 at 100, and the wider search stays built and off, until
  FOLLOWUP-TRAIL-SEEK gives the top end candidates worth a higher rate. (The seek
  is now built and did not: positions above 100 plan what 100 does, "The trail
  seek", next, so both stay as they are.)

### The trail seek (FOLLOWUP-TRAIL-SEEK, items 187, 194, 201)

The owner, 2026-10-02: item 194 asked for a candidate generator that seeks
trails and protected lanes near the line, and 201 for it before the rebuild.
`core.trailseek` is that generator; `core.refine._seek` runs it. Round 2 had shown
why one was needed: the exclusion rounds' candidates are nested, and the wider
search's points at fixed offsets asked for places nobody rides.

**What it does.**

1. After the exclusion rounds, from a calm rate of 10 (stress 100), it reads from
   the segment table the paths and trails, the protected ways and the car-free
   roads at LTS 1 or 2 (`pipeline.schema.trails_predicate`'s rule; with the
   facility column, `facility` `path` or `protected`, and the roads closed to cars
   at this ride time; gravel left out when the rider asked) within a band of
   the straight line and of the best route so far: 15% of the span, between 0.9
   and 2.5 mi (1.5 to 4 km), at most 30,000 rows.
2. It joins them into a graph and looks for corridors: a run of trail that leaves
   the route (from a point within 200 m, 650 ft, of it) and rejoins it later. The
   route is a line with a running total of its exposure (the weighted metres of
   LTS 3, 4 twice, Avoid three times, the search's own `Analysis.exposure_m`). A
   corridor's score is

       rate x (exposure of the stretch it replaces) - (way to the entry + trail + way from the exit - stretch replaced)

   in metres of detour, so a rate of 10 values a metre of LTS 3 avoided at ten
   metres of detour, as the slider says. The score is a part for the entry, a part
   for the exit and the trail's length, so one Dijkstra over each network, started
   from every node near the route at once, finds the best entry, trail and exit
   together. A corridor must save at least 150 m of exposure, replace at least 500
   m of the route and score 300 m, and add no more than the larger of 3.7 mi (6 km)
   and the span. A route with nothing busy on it has no corridor: there is nothing
   to replace.
3. It proposes, best first: the best corridor with the best one beside it (ridden
   in order), the best alone, and the best different trail over the same stretch;
   at most three. Each is the entry and exit, 25 m (80 ft) inside the trail, sent as
   `through` locations between the start and the end.
4. `_seek` asks the router for each (with the exclusions the best route was found
   under, so the way to the trail is as calm as the way the search found, and
   without them where the router has no route with them), reads the route and
   scores it with the same score as every other candidate, so the junction costs,
   the climb price and the Traffic-wins guard (2% + 50 m over the router's own
   route's exposure) decide. `calm_search.seek` in the answer records each try
   and its outcome.

Its own budget is 6 s past the exclusion search's 14 s, and a candidate is not
started with less than 2 s of it left. As first built it ran for a start and an end
only (superseded by part 2, "The trail credit and the seek leg by leg": it now runs
once per leg of a plan with stops). The
measurement harness filled a scratch segment table from the live stress tiles
(the paths and protected ways with LTS 1 or 2, about 2,500 segments over the twelve
trips' bands); the live table has no facility column until the rebuild, so on-road
cycle tracks that are not trail class are not corridors yet.

**What it found** (Default, `when` the moment of planning, the second of two plans
of each trip so the tables are warm, the harness's own work excluded; each cell is
miles / miles of LTS 3+ / trail miles (path and protected) / length against the
most direct route / red and orange markers / plan time):

| Trip | 80 | 100 before the seek | 100 with the seek |
|---|---|---|---|
| Rockville - Silver Spring | 10.3 / 4.42 / 0.5 / - / 0r 3o / 1.3 s | 13.9 / 0.23 / 4.6 / 1.44x / 3r 10o / 4.5 s | the same, 4.9 s |
| Bethesda - Capitol | 12.0 / 1.08 / 10.1 / 1.22x / 0r 3o / 1.5 s | 12.0 / 1.08 / 10.1 / 1.22x / 0r 3o / 8.8 s | 12.3 / 1.02 / 10.2 / 1.25x / 0r 3o / 5.8 s |
| Falls Church - Union Station | 10.5 / 1.36 / 8.5 / 1.07x / 0r 2o / 1.4 s | 10.7 / 0.90 / 9.2 / 1.09x / 0r 2o / 5.3 s | 11.1 / 0.78 / 9.6 / 1.13x / 0r 3o / 5.7 s |
| Silver Spring - College Park | 7.2 / 2.17 / 1.0 / 1.08x / 1r 2o / 1.8 s | 10.1 / 1.04 / 6.3 / 1.52x / 1r 6o / 5.1 s | the same, 5.5 s |
| Bethesda - Silver Spring | 4.7 / 0.82 / 0.3 / 1.11x / 1r 0o / 1.1 s | the same, 1.8 s | the same, 1.6 s |
| Laurel - College Park | 14.1 / 4.58 / 7.1 / 1.38x / 1r 7o / 1.6 s | 16.9 / 4.65 / 9.8 / 1.65x / 0r 11o / 3.8 s | the same, 2.4 s |
| Poolesville - Darnestown | 8.8 / 7.34 / 0.0 / - / 0r 1o / 0.3 s | the same, 1.4 s | the same, 0.7 s |
| Bowie - Annapolis | 21.2 / 13.41 / 1.8 / 1.04x / 3r 3o / 2.1 s | the same, 1.8 s (no route left after exclusions) | the same, 1.6 s |
| Tysons - Ballston (the W&OD runs south of the line) | 9.2 / 1.41 / 7.3 / 1.20x / 1r 4o / 1.0 s | 10.0 / 0.97 / 7.8 / 1.31x / 2r 5o / 4.1 s | the same, 3.0 s |
| Eastern Market - Prince George's Plaza (the Anacostia trail) | 7.9 / 4.66 / 2.6 / 1.11x / 1r 0o / 1.0 s | 8.8 / 0.45 / 4.1 / 1.24x / 0r 4o / 4.7 s | the same, 3.6 s |
| Friendship Heights - Rosslyn (the Capital Crescent) | 5.3 / 1.79 / 1.3 / - / 0r 3o / 0.9 s | the same, 0.7 s | the same, 0.6 s |
| Takoma - Hyattsville (the Sligo and NW Branch trails) | 3.5 / 2.60 / 0.6 / - / 0r 2o / 0.6 s | 4.8 / 0.63 / 3.4 / 1.42x / 0r 3o / 3.9 s | the same, 1.8 s |

The two columns at 100 ran in different processes, some of the time at once, so
their times differ by 1 to 3 s from run to run; the seek's own cost is better read
from the same process, which planned each trip at a rate of 19,027 with and
without it: less than 1.5 s apart either way on all twelve (+0.6 s on Rockville
- Silver Spring and on Bethesda - Capitol, +0.9 s on Bowie - Annapolis, the rest
equal or faster, which is noise). At Trailmaxxing's own costing (Cross) and
100, 12 trips: the seek changed one route (Bethesda - Capitol, 12.2 mi and 0.87 mi of
LTS 3+ to 12.4 and 0.81), asked nothing on seven, and took 4.8 s more than without
on Rockville - Silver Spring, the most it added.

- **The seek changed two of twelve routes**, each a little calmer and a little
  longer: Falls Church - Union Station 0.12 mi less LTS 3+ for 0.4 mi more,
  Bethesda - Capitol 0.06 mi less for 0.26 mi more. On four more it asked for
  routes and none beat the best: the candidates were busier (the guard) or cost more
  than the exposure they saved. On six it asked for nothing, because the route
  the calm search had found had no busy road to replace, or no trail within 650 ft of
  it: the W&OD, the Capital Crescent, the Anacostia and Sligo trails are on or
  beside those routes already.
- **Above 100 is the same route.** At rates of 447 and 19,027 (the "125" and "150"
  of item 187, the current curve carried on) with the seek, all twelve trips plan
  what 100 with the seek plans, every time: the candidates are the limit, still,
  just more of them. The exposure the seek can replace is the same at any rate
  above 10, and the corridors it finds are few. So the slider is not extended and
  nothing in `dials.ts`, the calm note or the link's `v=` changes.
- **What would make above 100 different** is something the score does not have: a
  value for trail miles as such. A quiet street and a trail with equal exposure
  score the same here, and the router's own costing (Cross, `use_roads` 0) is what
  prefers the trail. A credit per metre of trail would send a rider off the quiet
  street onto a trail that adds miles; whether that is what "relaxation, not
  commuting" means is the owner's call, and is not built.

Tests: `tests/test_trailseek.py` (62, the corridor finding, the score, the
proposals, the via points, the band and the query against a scratch table) and
`TestTrailSeek` in `tests/test_refine.py` (a fake router: what is asked, what is
kept, the guard, the budget, the exclusions, the failures). `scripts/mutants_trailseek.py`
has 56 mutants run against whole test files.


### The trail credit and the seek leg by leg (FOLLOWUP-TRAIL-SEEK part 2, items 202, 203)

*Superseded in part, 2026-10-03: the trail credit described here (item 202) was dropped by item 257 and removed from the code (FOLLOWUP-LONG-CALM, below). The seek leg by leg (203) stands.*

The owner, 2026-10-02: 202, "Trail bonus for Trailmaxxing only (Recommended)" (only
Trailmaxxing rewards each mile of trail), and 203, "Now, before rebuild" (the seek
runs leg by leg on plans with stops).

**The credit.** `Preset.trail_credit`, a preset dial: 0.5 on Trailmaxxing, 0 on
every other ride type, not a slider value and not in the router's costing. The
search's score is

    router cost + QUIET COST x (CALM RATE x exposure + ... - TRAIL CREDIT x trail metres)

so a metre of trail takes the credit, in metres of quiet riding, off a route. Trail
is the seek's own predicate (`refine.trail_flags`): a path or protected way, or a
road closed to cars at the ride time (facility `path`), at LTS 1 or 2; before the
facility column exists, the table's recorded trail rule. The seek's corridor score
gains the credit: a corridor is worth `rate x exposure replaced + credit x (trail it
rides - trail it replaces) - detour`, each trail step costing `1 - credit` of a
detour metre (the credit is held under 0.95), and a corridor needs only 400 m more
trail than it replaces when it replaces nothing busy. The Traffic-wins guard
(2% and 50 m) and the detour warning are untouched, so the credit buys no LTS 3 or 4.

**The slider.** The link carries the ride type and the slider position, never the
credit, so a shared link and the plan hash need no change; the API works the credit
out (`presets.trail_credit_for`). A rider who moves Trailmaxxing's Traffic slider
down gets the credit in proportion to the calm rate: all of it at 100, a fifth at 90,
none at 80 and below (no calm search there). The seek itself still runs only at 100.
Another ride type's slider at 100 has no credit.

**Leg by leg.** For a plan with stops the seek runs for each stretch between
consecutive locations that is at least 1.2 mi apart: its table read, corridors and
candidates are the leg's, the router is asked for the leg alone (start, `through`
points, end), the candidate is scored against the leg's own reading and guarded
against the leg's exposure as the router first gave it, and a leg taken is spliced
into the trip. The 6 s is shared by the legs that can run, by straight-line span of
what is left, at least 2.5 s each; a leg's unused time goes to the next. A taken
splice is read once as a whole for the answer to reuse.

Each leg's own route is read first (its trace and junctions, what the leg is
measured against), on an allowance of its own, `refine.SEEK_LEG_READ_S` (2 s),
which the budget is extended by but never past `REFINE_TRACE_RESERVE_S`; the leg's
share is worked out after it. And a leg that runs out of its share ("time") leaves
the rest to the legs after it; only a table that cannot be read ends the seek for
every leg. The combined correctness review found the seek never ran on Bethesda -
Silver Spring - College Park at Trailmaxxing 100 (6 of 6 runs): leg 0's share was
the 2.5 s floor, its reading took 0.45-0.6 s and its table 0.13 s, which left it
under `SEEK_ROUND_MIN_S`, and the loop stopped there before the longer leg 1. On
the live routers since, 3 of 3 runs sought both legs (leg 1 asked one corridor).

**Measured**, Trailmaxxing at 100 (stress 100, Cross), the twelve trips, each cell
miles / miles of LTS 3+ / trail miles (path and protected) / ratio to the direct
route / red and orange markers / plan time:

| Trip | credit 0 | 0.25 | 0.5 | 0.75 |
|---|---|---|---|---|
| Rockville - Silver Spring | 14.3 / 0.23 / 4.8 / 1.48x / 2r 11o / 12.2 s | 14.3 / 0.23 / 4.8 / 1.48x / 2r 11o / 12.3 s | 14.3 / 0.23 / 4.8 / 1.48x / 2r 11o / 9.5 s | 14.3 / 0.23 / 4.8 / 1.48x / 2r 11o / 12.3 s |
| Bethesda - Capitol | 12.2 / 0.87 / 9.9 / 1.24x / 0r 2o / 6.5 s | 12.4 / 0.81 / 9.9 / 1.27x / 0r 2o / 15.2 s | 12.4 / 0.81 / 9.9 / 1.27x / 0r 2o / 11.8 s | 12.4 / 0.81 / 9.9 / 1.27x / 0r 2o / 10.3 s |
| Falls Church - Union Station | 10.5 / 1.36 / 8.5 / 1.09x / 0r 2o / 7.1 s | 10.5 / 1.36 / 8.5 / 1.09x / 0r 2o / 13.7 s | 10.5 / 1.36 / 8.5 / 1.09x / 0r 2o / 9.6 s | 10.5 / 1.36 / 8.5 / 1.09x / 0r 2o / 9.7 s |
| Silver Spring - College Park | 10.1 / 1.04 / 6.3 / 1.52x / 1r 6o / 9.9 s | 10.1 / 1.04 / 6.3 / 1.52x / 1r 6o / 12.8 s | 11.1 / 0.79 / 8.0 / 1.67x / 0r 2o / 18.0 s | 11.1 / 0.79 / 8.0 / 1.67x / 0r 2o / 10.0 s |
| Bethesda - Silver Spring | 4.7 / 0.82 / 0.3 / 1.11x / 1r 0o / 3.4 s | 4.7 / 0.82 / 0.3 / 1.11x / 1r 0o / 3.4 s | 4.7 / 0.82 / 0.3 / 1.11x / 1r 0o / 4.5 s | 4.7 / 0.82 / 0.3 / 1.11x / 1r 0o / 3.2 s |
| Laurel - College Park | 16.9 / 4.65 / 9.8 / 1.65x / 0r 11o / 7.0 s | 16.9 / 4.65 / 9.8 / 1.65x / 0r 11o / 6.6 s | 16.9 / 4.65 / 9.8 / 1.65x / 0r 11o / 7.0 s | 16.9 / 4.65 / 9.8 / 1.65x / 0r 11o / 6.1 s |
| Poolesville - Darnestown | 9.7 / 6.30 / 0.0 / 1.10x / 1r 2o / 1.7 s | 9.7 / 6.30 / 0.0 / 1.10x / 1r 2o / 1.1 s | 9.7 / 6.30 / 0.0 / 1.10x / 1r 2o / 2.5 s | 9.7 / 6.30 / 0.0 / 1.10x / 1r 2o / 1.3 s |
| Bowie - Annapolis | 21.2 / 13.41 / 1.8 / 1.04x / 3r 3o / 2.0 s | 21.9 / 13.32 / 2.6 / 1.08x / 3r 3o / 4.6 s | 21.9 / 13.32 / 2.6 / 1.08x / 3r 3o / 4.5 s | 21.9 / 13.32 / 2.6 / 1.08x / 3r 3o / 4.7 s |
| Tysons - Ballston (W&OD) | 10.0 / 0.97 / 7.8 / 1.30x / 2r 5o / 6.4 s | 10.0 / 0.97 / 7.8 / 1.30x / 2r 5o / 4.6 s | 10.0 / 0.97 / 7.8 / 1.30x / 2r 5o / 6.5 s | 10.0 / 0.97 / 7.8 / 1.30x / 2r 5o / 5.8 s |
| Eastern Market - PG Plaza (Anacostia) | 8.8 / 0.45 / 4.1 / 1.24x / 0r 4o / 11.2 s | 8.8 / 0.45 / 4.1 / 1.24x / 0r 4o / 8.2 s | 8.8 / 0.45 / 4.1 / 1.24x / 0r 4o / 9.5 s | 8.8 / 0.45 / 4.1 / 1.24x / 0r 4o / 8.2 s |
| Friendship Heights - Rosslyn (Capital Crescent) | 5.3 / 1.79 / 1.3 / - / 0r 3o / 2.4 s | 5.3 / 1.79 / 1.3 / - / 0r 3o / 1.0 s | 5.3 / 1.79 / 1.3 / - / 0r 3o / 1.0 s | 5.3 / 1.79 / 1.3 / - / 0r 3o / 1.2 s |
| Takoma - Hyattsville (Sligo) | 4.8 / 0.63 / 3.4 / 1.42x / 0r 3o / 4.3 s | 4.8 / 0.63 / 3.4 / 1.42x / 0r 3o / 3.6 s | 4.8 / 0.63 / 3.4 / 1.42x / 0r 3o / 3.5 s | 4.8 / 0.63 / 3.4 / 1.42x / 0r 3o / 4.3 s |

- **The credit changes three of twelve routes**: Bethesda - Capitol (+0.2 mi, 0.06 mi
  less LTS 3+), Bowie - Annapolis (+0.7 mi, 0.8 mi more trail) and, from 0.5, Silver
  Spring - College Park (+1.0 mi, 1.7 mi more trail, 0.25 mi less LTS 3+, 5 markers
  fewer; its ratio goes from 1.52 to 1.67, past the detour warning's 1.5, which says
  so). 0.25 takes the first two; 0.5 and 0.75 plan the same routes on all twelve.
- **The W&OD, Capital Crescent, Anacostia and Sligo trips do not change**: the seek
  now asks (the credit finds a corridor on four trips where it asked nothing) but the
  routes already ride the trails beside them, so there is no 400 m of trail to add.
  Of the others, the candidate through the corridor was busier or dearer.
- **Recommended: 0.5.** It takes every change 0.25 does and the one more that is
  clearly a trail route, and 0.75 adds nothing. Typical trips stay under 1.6 times
  the direct route (ten of twelve; Laurel - College Park was 1.65 before the credit).
  The plan times in this table come from runs that overlapped; credit 0 against 0.5
  measured in one process is in "Round 1 revision" below.
- **Plans with stops** (credit 0.5, seek on against off, one process): a plan with no
  stop, Bethesda to College Park, 10.9 s on against 9.2 s off (+1.7 s); one stop
  (Bethesda, Silver Spring, College Park) 13.1 s against 8.3 s (+4.8 s); three stops
  (Tysons, Ballston, Rosslyn, Union Station, Takoma, 25 mi) 20.0 s against 15.2 s
  (+4.8 s). With one stop the seek read the table for both legs and asked once; with
  three the exclusion search used its time (`limited: time`), the seek read its
  corridors (3) and had under the least left to ask: it adds the table reads and the
  legs' readings and asks nothing. Corrected in round 1's review: the 24.9 km
  (15.5 mi) candidate was the plan with no stop (Bethesda to College Park, one leg,
  150 kept exclusions), against a best of 23.4 km (about 1.07 times); the one-stop
  plan's candidate was leg 1 at 17.1 km with 145 exclusions. Neither was better.

Tests: `TestSeekLegByLeg`, `TestRouteSpansAndLegs`, `TestTrailCredit*` in
`tests/test_refine.py`, `TestTheTrailCredit` in `tests/test_trailseek.py`,
`TestTrailCredit` in `tests/test_presets.py`, the link and the notes in the front
end's `planHash`, `dialsPanel` and `presets` tests. `scripts/mutants_trailseek.py`
now has 98 mutants, 42 of them on this code.

### Round 1 revision (FOLLOWUP-TRAIL-SEEK review r1)

**Hard bounds.** The corridor search no longer rests on one clamp for its
termination. `trailseek._check_step` refuses a trail step that is not finite and
positive (`SeekError`); the walk back from a corridor's exit is at most the
network's node count and raises past it; the clock is read every 1,024 nodes
settled, between networks and between components (`SeekOutOfTime`), against the
leg's stop less a candidate's least. `refine._seek_leg` looks at the leg's
deadline before the table and again before the corridor search, and the table
read runs under `SET LOCAL statement_timeout` (`set_config(..., true)`, as
`core.stress_tiles.render` does), at most 2.5 s and never past the leg's time (since
v0.15.0 through `routing.plan_cursor(cap_s=...)`, so also never past the plan's own time);
a cancelled read is `limited: "time"`, a plan replaced by a newer one ends there
(`PlanCancelled`), a `SeekError` is `limited: "error"` (logged),
and the plan is answered without the seek. Proved on the mutant that froze the
host (the clamp removed): `tests/test_trailseek.py` now fails in 20 s, under a
300 s timeout, with `SeekError: a trail step must cost something, not -6.0`; with
the clamp and the step check both removed, the walk's bound raises ("longer than
its network") and the file fails in 19 s.

**The table read after the rebuild.** The query is read a strip of the band at a
time (`trailseek.band_cells`: 1 km cells within the band of either guide line,
each row's run one index scan through a lateral join), not one `ST_DWithin` over
the guide's bounding box. With the facility column it carries
`pipeline.schema.SEEK_INDEX_PREDICATE` word for word, and the segment DDL builds a
partial GiST index on it, `segment_seek_geom_idx` (paths and protected ways at LTS
1-2, and any car-free road). Measured with `EXPLAIN (ANALYZE, BUFFERS)`, warm, three
runs each, on a 20 mi (33 km) diagonal from (-77.20, 39.14) to (-76.93, 38.93),
the straight line and a 400-point route wandering 0.9 mi (1.5 km) either side, a
2.5 mi (4 km) band, 33 strips:

| Table and predicate | One geometry (before) | Strips (now) |
|---|---|---|
| Live table, today's (trail rule, `segment_overview_geom_idx`) | 349-386 ms, 2,334 rows | 42-61 ms, 2,360 rows |
| Live table, a proxy no partial index implies (`segment_geom_idx`) | 795-1,203 ms | 185-285 ms |
| Copy with a facility column, post-rebuild predicate, no seek index | 740-812 ms | 227-329 ms |
| The same copy with `segment_seek_geom_idx` | 756-1,442 ms (the old form cannot use it) | 15-42 ms |

Planning took 10-42 ms in every case. The live table was read-only (SELECT and
EXPLAIN). The copy is the live table's 1,357,800 rows in a scratch database with
the facility derived from the recorded rule (15,207 paths; the live table records
no sidepaths, so the on-road protected ways the rebuild adds are not in it).
`CREATE INDEX CONCURRENTLY` of the seek index on the copy took 1.6 s and 648 kB.
How it runs: at a rebuild the index is created in staging with the rest of the
schema (on the empty table, before the load) and promoted by the swap, so nothing
runs on the live table; the segment DDL is the pipeline's, not a Django migration's
("What migrations do and do not create"). Today's live table has no facility
column and needs no index (the overview index serves the trail rule); a table
promoted with the column but without the index can have it added in place with the
`CREATE INDEX CONCURRENTLY` in docs/OPERATIONS.md, "The seek index".

**Traffic wins for the whole trip.** A plan with stops whose legs were taken is
read once spliced and held to the whole trip's allowance (2% and 164 ft, 50 m, over
the router's first exposure), as each leg is to its own: n legs can no longer add
n x 50 m between them. A splice past it is not taken (`limited: "busier"`, and
`whole_trip: "busier"`, which a `limited: "time"` from a later leg does not hide).

**Kept exclusions.** A candidate is asked with only the search's kept exclusions
within the leg's band (`trailseek.points_in_band`), and asked again without them
when the route with them is more than 15% and 500 m longer than the leg and the
corridor's detour (`refine.SEEK_RETRY_OVER`, `SEEK_RETRY_SLACK_M`), time allowing;
both answers are scored and guarded, and the second's `tried` row says
`retry: "longer"`. So a leg is up to six routes.

**No trails, no seek.** A ride on the no-trail graph (`ctx.roadway_only`: Mass Ride,
or any ride with the "Keep to roads, not trails" switch on, at 100) is not seeked (`limited: "roadway_only"`).

**Credit 0 against 0.5, one process.** Trailmaxxing at 100, the twelve trips, the
harness's plan time (the second of two plans, the harness's own work excluded), two
runs each, the runs in the order 0, 0.5, 0, 0.5, nothing else running:

| Trip | credit 0 | credit 0.5 | Difference (means) | Asks (0 / 0.5) |
|---|---|---|---|---|
| Rockville - Silver Spring | 9.8, 7.8 s | 7.5, 7.6 s | -1.3 s | 1 / 1 |
| Bethesda - Capitol | 10.0, 5.6 s | 6.7, 11.3 s | +1.2 s | 1 / 2 |
| Falls Church - Union Station | 9.9, 6.1 s | 6.7, 8.1 s | -0.6 s | 2 / 2 |
| Silver Spring - College Park | 9.6, 8.6 s | 7.3, 9.6 s | -0.6 s | 2 / 2 |
| Bethesda - Silver Spring | 2.9, 1.9 s | 2.3, 2.6 s | +0.1 s | 1 / 2 |
| Laurel - College Park | 5.2, 4.8 s | 5.3, 5.1 s | +0.2 s | 2 / 2 |
| Poolesville - Darnestown | 0.9, 0.9 s | 1.1, 0.9 s | +0.1 s | 0 / 0 |
| Bowie - Annapolis | 1.7, 1.7 s | 3.4, 3.3 s | +1.7 s | 0 / 1 |
| Tysons - Ballston (W&OD) | 3.6, 4.0 s | 4.0, 3.7 s | +0.0 s | 0 / 0 |
| Eastern Market - PG Plaza (Anacostia) | 6.1, 5.8 s | 6.5, 5.6 s | +0.1 s | 1 / 1 |
| Friendship Heights - Rosslyn (Capital Crescent) | 0.8, 0.8 s | 0.9, 0.8 s | +0.1 s | 0 / 0 |
| Takoma - Hyattsville (Sligo) | 2.5, 2.8 s | 2.5, 2.3 s | -0.2 s | 0 / 0 |
| Mean of all | 4.8 s | 4.8 s | +0.0 s | |

The routes are the ones in the table above (three change). The credit's own cost
shows where it adds an ask: Bowie - Annapolis +1.7 s in both runs (none to one ask)
and Bethesda - Silver Spring and Bethesda - Capitol one more each; elsewhere the
differences are within the same trip's run-to-run spread (up to 4.6 s, Bethesda -
Capitol at 0.5). The earlier 9.9 to 18.0 s on Silver Spring - College Park came
from overlapping runs: here it is 9.1 s at 0 and 8.5 s at 0.5.

Tests: `TestHardBounds`, `TestTheStrips`, `TestTheIndexAndTheTimeout`,
`TestTheDetourCapExactly` and `TestPointsInTheBand` in `tests/test_trailseek.py`;
the `review r1` tests in `TestTrailSeek` and `TestSeekLegByLeg` in
`tests/test_refine.py` (asymmetric legs, a late leg held to the stop, a table
failure read once, the whole-trip guard, the deadlines, the exclusions and the
retry, the roadway-only graph). `scripts/mutants_trailseek.py` has 125 mutants.


### Doubling back and stop matching (v0.4.1, 2026-10-11)

Two faults on one Trailmaxxing plan at 100 with an 80 mi target (DC, Fort Hunt,
Kingstowne, Fairfax), fixed in patch v0.4.1 (PR #63; PLAN.md, the 2026-10-11 entry).

**Doubling back.** The trail seek asks for the router's route through each corridor's
entry and exit as `through` locations. Where the router cannot pass them in the order
asked, it rides out along a way to one of them and back the same way: here 0.5 mi
(0.8 km) down the trail by Island Creek and straight back. `refine.retrace_m` measures
it: the metres of a leg on an edge the same leg already rode, either way. Edges are
matched by their middles (`Analysis.marks`) within 7 ft (2 m), of lengths within 7 ft
(2 m) or a tenth, the longer; the way out and the way back of an edge have the same
middle, and a sidepath beside the road or the next short edge along a straight way do
not match. A leg is the stretch between the plan's own locations (`Analysis.mark_legs`,
kept by `analyse`; `via_m` where a reading has none), so out to a stop the rider placed
down a dead end and back is two legs and never counted. `through` points never split a
leg, so a seek candidate's spur always is.

A seek candidate is refused, outcome `doubles_back`, where it retraces more than
164 ft (50 m, `RETRACE_SLACK_M`) beyond the leg's own route (the incumbent the seek
started from, never the best so far, so each candidate taken cannot raise the bar).
The outcomes are tried in the order `busier`, `more_lts4`, `doubles_back`,
`too_long`, then `taken` or `not_better`; a refused candidate is not offered among the
routes to choose from. The wide search holds its candidates the same way against the
route it started from (it is off, `WIDE_SEARCH_FROM_RATE = None`; the guard keeps its
guards alike). On the plan above both seek candidates are now refused: the one taken
before only scored calmer because of its spur, and the route carries 272 ft (83 m) more
LTS 3 for dropping it, never more LTS 4 or Avoid.

**Stop matching.** The rider's locations (start, stops and end, on every ride type) go to
the router with a 49 ft (15 m) `radius` (`routing.STOP_RADIUS_M`): Valhalla takes every
way within that distance as a candidate and the route takes the cheapest, where before
it had only the nearest. The stop on the Fairfax County Parkway Trail lay 15 ft (4.5 m)
from a ramp and 19 ft (5.9 m) from the trail; matched to the ramp, the route left the
trail for 0.6 mi (1.0 km) of the Avoid-rated parkway. The search's own requests reuse
the plan's locations, so they match alike, and so do the stop-order leg costs and
its matrix past ten stops (`stoporder`); `core.nearest` matches the rider the same way and
keeps the nearest way at its fixed places. The cut points of a long plan (`refine.long_legs`) and the dedodge
locations are on the route and get no radius; a bikeshare walk leg (pedestrian, to and
from the dock) keeps the nearest way. Only ways the ride's costing allows are
candidates, so a way closed to bicycles is never matched (err closed is unchanged), and
on the no-trail graph there is no trail to match.

The trade-off, CONFIRMED by the owner for every ride type (2026-10-11: "Any ride type.
15m is inconsequential for bike riding"): the radius ignores height and the rider's
intent. On a direct ride (or Mass Ride) a stop put on a sidepath to pull the route onto
it can be served from the road beside it when that is cheaper, and a stop on a trail
under a bridge can be served from the deck above, or the other way (the same problem as
the wider `/locate` radius at Rockville Pike, above). Ride mode's arrival reads the
distance along the route line, so a stop matched up to 49 ft (15 m) off still arrives.

Tests: `TestRetrace`, `TestTrailSeek::test_a_route_that_rides_out_and_back_to_a_through_point_is_not_taken`
and `::test_each_candidate_is_held_to_the_legs_own_route`,
`TestWideSearch::test_a_wide_route_that_rides_out_and_back_is_not_taken` (tests/test_refine.py),
`test_each_stop_is_matched_to_every_way_near_it` (tests/test_route_api.py) and the
radius in the stop-order request tests (tests/test_stop_order.py); 19 mutants in
scripts/mutants_trailseek.py ("doubling back", all killed).

### The detour warning

`routemaker.detour` (item 164: "just warn people"): the route's length against
the most direct legal route (the router at stress 0 and the hills detent, asked
once, only when the route is longer than the larger of 1.25 times or 0.33 mi
over the straight line, which the direct route cannot beat). Silent within the
larger of 1.25 times or +0.33 mi; `note` up to 1.5 times; `warning` above;
`strong` above 2 times (the review's "let it run long, warn at 1.5x and 2x").
The direct route is asked for only above Default, or at any position where the
route is at least twice the straight line (`core.routing._detour`): at Default and
below a route between 1.25 and 2 times the straight line gets no note at all,
which saves a second route on most plans. The planner calls the route "calm"
only above 80, where the rider asked for the calm detour.
The answer's `detour` has `basis`, `reference_m`, `ratio`, `extra_m`, `level` and
`avoided_m` (metres of LTS 3 and worse the direct route has and this one does
not, where there was time to trace it). Where the direct route could not be had
in time, and on Mass Ride, it compares with the straight line and only the old
rule says anything (at least twice as long and 3 km more, a `warning`). The
planner words it with miles first: "This calm route is 2.6x the direct distance
(+18.0 mi, 29.0 km)", with what it buys at a note and "Move the Traffic slider
down" at a warning.

### The route description (item 220)

Many blind cyclists in this area ride as tandem stokers (the owner, 2026-10-02),
so what the map shows by colour and position is also written out.
`POST /api/route` answers `description` (additive; `core.api.DescriptionEntryOut`):
a list of entries in route order, built by `routemaker.describe` from what the
plan already has, with no router call and no query. Its only new input is the
street name, asked for as `edge.names` in the `trace_attributes` call the plan
makes anyway (`Piece` now carries `names`, `use` and the edge's begin and end
headings, none of them part of its identity).

- **Stretches.** Consecutive pieces on one street (a name in common, or both
  unnamed) with one tier and one facility are one stretch. A stretch under 300
  ft is folded into the longer neighbour in its leg, but never an LTS 3, LTS 4
  or Avoid stretch, and never an untraced one. A stretch never spans a stop:
  each leg is described on its own and `Stop 1`, `Stop 2` (the points list's own
  words, item 224) are entries between them ("Stop 1 at 4.7 mi (7.6 km)."). A via
  point is ridden through: the legs either side of it are read as one line, so a
  turn at it is said, and its entry is "Via point at 2.1 mi (3.4 km)."; stops are
  numbered among the stops only (round-3 audit D29, `describe_both`'s `through`).
- **Turns.** Where the street changes, the entry says how the rider turns into
  it (`left`, `right`, or `Continue onto`), from the previous stretch's last
  heading and this one's first (`routemaker.intersections.movement_of`). If the
  junction model read the junction within 30 m ("at a signal", "at a stop
  sign", "at an all-way stop", "where cross traffic stops") that is said; where
  it flagged it, the severity words follow ("Higher stress junction", "Very
  high stress junction"; flagged with nothing mapped says "no signal mapped").
  Where the model did not read a junction nothing is claimed about it.
- **Junction entries.** A flagged junction that is not a change of street (a
  crossing of a busy road) is an entry of its own, at a point.
- **Words.** US units first, the metric once per entry, and "to" rather than a
  dash so a screen reader does not say "dash": `0.0 to 1.2 mi (0.0 to 1.9 km):
  Capital Crescent Trail, traffic-free path.` Tier words follow the legend:
  traffic-free path (facility `path`, whatever the tier), low stress (LTS 1),
  fairly low stress (LTS 2), busy road (LTS 3), heavy traffic (LTS 4), Avoid
  (legal, but best avoided), stress not rated; a protected or painted bike lane
  is added. A stretch with no name is "unnamed path" (a path facility or a
  path `use`) or "unnamed road". Crossed roads' names are as mapped
  ("MacArthur Boulevard", "I-395", "US 29", item 230): `core.junctions` keeps the
  lower-case key for matching (`Arm.names`, `Road.names`) and the name as mapped,
  in the router's order, beside it (`display`, carried to `Event.road_display`);
  neither is part of equality. An event built without them falls back to the
  keys, capitalised by `readable()`. A road with no name is "a busy road".
- **Distances** are measured along the traced pieces and scaled so the last
  stretch ends at the route's `distance_m`; the stretches' lengths add up to it
  to the metre. Junction events are placed in the same measure.
- **Entry fields.** `kind` (`stretch`, `junction`, `via`), `from_m`, `to_m`,
  `from_mi`, `to_mi`, `street`, `tier`, `facility`, `turn`
  (`movement`, `onto`, `control`, `severity`), `severity`, `via`, `surface`,
  `text`, one sentence, and `text_lanes_hidden`. `description` is null where it
  could not be built (an error is logged and the route is answered without it)
  and absent from an older API.
- **Surface** (OWNER-DECISIONS 280). `routing.classify` reads the segment's
  `is_unpaved` beside its tier and facility (a `PieceClass`, still a pair), and a
  stretch says ", unpaved" where at least half of it is unpaved and ", partly
  unpaved" where at least 0.1 mi is; `surface` is the same as a field. A change
  of surface alone does not start a stretch.
- **Painted lanes on LTS 4 and Avoid** (OWNER-DECISIONS 275). The planner's
  "Show bike lanes on high-stress roads" switch is off by default, and with it
  off such a lane is not called a bike lane. The wording stays in Python: a
  stretch whose lane is all on LTS 4 or Avoid (`HIGH_STRESS_LANE_TIERS`) has
  `text_lanes_hidden`, its sentence without the lane, and every other entry has
  null. An overview stretch that merges an LTS 3 lane with an LTS 4 one keeps
  its lane, as the facility bar counts the LTS 3 part. The planner uses the
  field, and takes ", painted bike lane" out itself only for an older API
  (`tests/test_describe.py`, `TestFrontEndAgrees`, holds its words and the
  tiers equal to `describe.py`'s).

The planner lists the sentences in `frontend/src/RouteDescription.tsx` (a
component of its own: a heading, a disclosure button and an ordered list,
closed unless the rider has opened it before, "Copy description" and "Download
as text"). It words nothing itself, and announces nothing when the route
changes; the only live region is the reply to pressing Copy.

**Stops, the overview and the GPX (items 224 to 226).**

- Stops are "Stop N" in the description, the points list, the map markers and
  their announcements, "Add as stop" and the GPX route points (`planPointName`).
  The GPX import still treats `Via N` as RouteMaker's own name, not a place
  name, so older exports re-open the same way.
- `describe_both` answers the full list and an overview. The overview merges a
  stretch under `OVERVIEW_M` (0.25 mi) into a neighbour of its own leg, so it
  never spans a stop. It never hides or understates: a stretch of LTS 3 or
  worse folds only into one at least as stressful, and a calm stretch (LTS 1 or
  2) is never merged with a busy one; a merged stretch is worded at its most
  stressful tier, with a facility ("traffic-free path") only where all
  of it has one; a stretch that begins at a flagged junction is never folded
  away and nothing is folded in front of one; the stops and the separate
  flagged-junction entries are the full list's, unchanged; an untraced leg and a
  rated stretch against an unrated one are never merged. A merged entry says
  the street it begins on and "then" up to three other streets, each with its
  turn (item 229: "Right onto Ramsey Avenue at a signal, then left on Ripley
  Street and right on Colonial Lane"; a street straight on is just named), and
  "and N more turns" for the rest.
- The API sends both lists (`description` full, `description_overview`), not
  grouping indices: a merged sentence needs its own wording (a tier, a facility
  and a street list that no member has), which is wording kept in one place,
  and a client that switches views needs no second request or wording of its
  own. The cost is a second list; the overview is the shorter one, so the
  answer grows by less than the full list did.
- The planner shows the overview by default; a "Full detail" checkbox (only
  where the overview is shorter) shows every entry and is remembered in
  localStorage (inside try/catch). Copy and Download use the view shown.
- The GPX route's `<desc>` carries the ride type and then the description as
  plain text, a numbered line to an entry, escaped like all the file's text. It
  is the full text where that is at most `GPX_FULL_MAX_CHARS` (4,000), else the
  overview, labelled which it is: a file is read on a device, not on the
  rider's screen, so it does not follow the screen's view.

Cost (2026-10-02, five plans on the live router through the forwarder
harness, read-only): the same router calls as the code before it (route,
`trace_attributes` and `/locate` counts are equal plan for plan) and the same
routes. Building the description took 1 to 14 ms in a plan (0.8 ms for a 2.5 mi
Mass Ride, 4 to 14 ms for 10 to 13 mi), about 0.2% of a plan's 1.5 to 7 s; a
benchmark of 1,200 pieces is 0.3 ms with a few long stretches and 3.7 ms in a
worst case that changes tier every 7 pieces. The answer grows by about 370
bytes an entry (9 to 20 kB for 10 to 13 mi, 17 to 50 entries), which gzip takes
to a tenth. `~/rmdata/demo/reports/ROUTE-DESCRIPTION-plan-notes.md` has the plans.

Tests: `tests/test_describe.py` (merging, tiny stretches, wording, turns,
junctions, vias, totals), `tests/test_route_description.py` (through the view:
no extra router call, every preset, the schema), and
`frontend/src/lib/routeDescription.test.ts`. The mutants are
`scripts/mutants_describe.py` (each mutant against whole test files).

### The contract

`POST /api/route` answers three more fields (all additive; `core.api.RouteOut`):

- `intersections`: a list, in route order, of `{m, lon, lat, severity
  ("orange" or "red"), reason, crossed_tier, movement, control, kind, cost_ft}`,
  null where the junctions could not be read in time (the route is answered
  all the same). Neighbourhood stop signs and anything below 600 ft are not
  listed. `reason` is US units first: "Left turn across a 4-lane 35 mph (56
  km/h) road, no signal mapped"; where only the tier is known, the stress map
  legend's words, "Crossing a heavy-traffic road (LTS 4), no signal mapped".
  `control: "none"` means no signal or sign is MAPPED, not that there is none.
- `intersection_groups` and `intersections[].group` (Mass Ride, additive): see the next section.
- `calm_search`: null where no search was asked for, else the object above.
- `detour`: null within the allowance, else the block above.

The planner draws the markers (`frontend/src/lib/intersectionMarkers.ts`, the
`IntersectionList` and `MapView`), a click on one or on its row in the route
summary shows the reason, and dragging the route away re-plans it as any drag
does. The slider's words and its note at the top end are
`frontend/src/lib/dials.ts` and `dialsPanel.ts`.

### Mass Ride: groups of signalized crossings (items 233, 234, 235)

The owner, 2026-10-03: "Actually, I like merging the runs, that sounds good." (233) and "I'd say we'd want some level of clumpings, especially in DC, given the diagional streets. I'd say something like a quarter mile or so of clumping." (234). On a Mass Ride (`assess_route(..., group=True)`) `intersections.number_groups` numbers each run of two or more signalized crossings in `Event.group`: flagged, `Control.SIGNAL`, kind `crossing` or `left_across` (`GROUPED_KINDS`), each within `GROUP_WITHIN_M` (402 m) of the one before. Any other flagged event, including a turn at a signal, stands alone and ends the run. Every crossing stays an event and a marker and the cost is unchanged; only the list and the description say the group once.

- `intersections[].group`: the group's number or null. `intersection_groups` (null where `intersections` is): `{group, from_m, to_m, count, lts4, streets, more, severity, members, text}`, `members` being positions in `intersections`, `text` the phrase without the severity ("1.0 to 1.6 mi (1.6 to 2.6 km): 6 crossings with traffic signals (17th Street Northwest, 15th Street Northwest, 14th Street Northwest and 3 more), 2 of them heavy-traffic roads (LTS 4)").
- `description` and `description_overview`: one `junction` entry for the group, text ending "(Very high stress junctions).", with `group: {number, count, lts4, streets, more, crossings}`; null on every other entry. `crossings` (OWNER-DECISIONS 248) lists each crossing in the full description, `{from_m, from_mi, street, severity, crossed_tier, text}` with `text` worded as a junction entry ("At 1.1 mi (1.8 km): Cross 17th Street Northwest (LTS 4) at a signal (Very high stress junction)."), and is null in the overview. The page shows them as a nested, named `<ol>`; Copy, Download and the GPX `<desc>` set them in under the group ("   3.1. At ...").
- The list (`IntersectionList`, `junctionRows`): a group is a disclosure button over its crossings, the ordinary rows. Closed first; nothing announced; the focus stays on the button.
- A group never spans a stop (OWNER-DECISIONS 247): `number_groups(events, stops)` closes the run at each leg end, and `core.routing.plan` numbers the events again with the plan's `stops_m` (each leg's end along the traced length, the events' own measure), since the search's readings were numbered without them. A crossing at the stop begins the next leg's run. A crossing that is also the turn into a stretch is counted in the group and said in the turn.
- Density on live DC (Mass Ride, weekend, read-only): Lincoln Memorial to the Capitol along Constitution Ave, 9 flags in 2.52 mi (3.6 a mile), list entries 9 to 3; with vias on Constitution Ave, 13 flags in 3.20 mi (4.1), 13 to 7; Pennsylvania Ave NW from Washington Circle with vias, 23 flags in 3.52 mi (6.5), 23 to 5; direct, 23 in 2.78 mi (8.3), 23 to 3.
- Tests: `tests/test_crossing_groups.py` (joining, the window and its edge, breaks, wording, description, API rows, and item 235's flagging rules), `frontend/src/lib/intersectionMarkers.test.ts`, `frontend/src/a11yFixes.test.ts`, and the browser check (`scripts/a11y/check.mjs`, section 6). Mutants: `scripts/mutants_groups.py`.

### Known gaps, and what would close them

- Valhalla's parser reads a node's signal from `highway=traffic_signals`
  alone. From the Track B rebuild (FOLLOWUP-SIGNAL-DERIVE) a signalised trail
  crossing (a signal or a HAWK) away from a signalized road junction reaches
  the flag where OSM maps it on the crossing node (`highway=crossing` with
  `crossing=traffic_signals` or `crossing:signals=yes`; `remap.derives_signal`)
  or on the crossing way alone (`pipeline.signals` marks the node the way
  shares with the road, `rm:crossing_signal`). What is left: a crossing with
  the signal mapped on neither, a node that says `crossing=uncontrolled` under
  a way that says signals (read as no signal), and a node with a `bicycle=no`
  that upstream reopens only on a `highway=crossing` node. These read "no
  signal mapped", are counted at `MARKED_CROSSING_FACTOR` and are never red
  (item 185). A cycletrack crossing at a node of its own beside a signalized
  road junction is read as signalized from round 2 (the approach walk reaches
  the junction's stop lines).
- A signal tagged more than 30 m up an approach, or only on an approach the
  junction's arms do not lead to (the far carriageway's, where the route
  crosses one carriageway alone, as the Virginia Ave cycletrack does at G St
  NW), is not read. A stop sign on a cross road's stop line short of the
  junction is not read as the cross traffic's (it may be another junction's),
  so where only the cross traffic stops the rider is priced as the stopped
  side. The other way round, a side street or driveway within 30 m of a
  signalized junction does not take its signal where a road of another name
  joins at the signal's node or the signal faces away from it (review r3, B1);
  it still does where the signal is on a stop line of its own road with no
  other road there and facing it, or where the other junction's road has no
  name. That under-warns, only within 100 ft (30 m) of a signal. And the rule
  costs a signal where one junction is mapped as two named ones a few metres
  apart: Plyers Mill Rd across Metropolitan Ave reads the signal 16 m away at
  Concord St as Concord St's (orange, 1,200 ft, where it was 150).
- A median refuge is credited where both carriageways carry the road's name
  (`MEDIAN_REFUGE_FACTOR`); an unnamed divided road's carriageways are two
  roads. Raised crossings, bike signals and queue boxes are not read.
- A residential street that is LTS 3 on its own speed or volume is not looked
  for at junctions (only tertiary and up are); its stretch still colours the
  route.
- Valhalla's `use_sidepath` price on LTS 3-4 ways applies by tier and not by
  junction density; the calm search is the only thing above it.
- The live segment table has no speed, lanes or one-way until the first rebuild
  after this change; reasons say "heavy-traffic road (LTS 4)" until then, and
  the one-way reading comes from the router's own arms. `core.junctions.
  has_trait_columns` checks, as `core.routing` does for the facility columns.
  After the rebuild, only speeds and lane counts read from the map or an agency
  are stored (`routemaker.stress`); the merge cost assumes lanes by tier where
  none was read. None of the post-rebuild pricing has been run live.

## Junction delay: the time stops and signals cost

The owner, 2026-10-20: a route the planner chose over a rider's usual, flatter way took
11 minutes longer than the router said, through a grid of stop signs, and the owner chose
"Both": the delay counts in the time shown and in which route is picked.

Valhalla's bicycle costing (3.9.1) times a junction as its `stopimpact` (0 to 7, from the
roads' classes) times a turn cost of 0.15 s straight on, about a second at most, whatever
controls it. `routemaker.junction_delay` adds what a rider loses, read at every node of the
route's trace where it crosses or joins a road (`trace_junctions.junctions_of_trace`, with
the router's `node.traffic_signal` and `edge.traffic_signal` flags):

| At the junction | Delay | Why |
|---|---|---|
| A traffic signal on the node or within 30 m (100 ft) up the rider's approach | 15 s | the average wait for a random arrival at a 100 s cycle with 50 s of red (Webster's uniform delay), plus half a stop; inferred |
| The rider gives way to a neighbourhood street (unclassified or residential): crossing one as busy as their own, turning onto one where their own street does not go on ahead, or crossing or leaving a path | 8 s | one stop at a steady effort: Fajans and Curry, ["Why Bicyclists Hate Stop Signs"](https://www.accessmagazine.org/spring-2001/bicyclists-hate-stop-signs), ACCESS 18 (2001), 14.2 against 10.9 mph |
| The same in the District, where the road given way to is unclassified or residential | 4 s | DC lets a rider take a stop sign as a yield (the owner: "bikes aren't required to stop at stop signs if there's no cross traffic"); a slow-and-roll, inferred |
| The rider gives way to a busier road that does not stop: tertiary, secondary, primary or busier | 12, 20, 30 s | the wait for a gap (the owner: "a stop sign against a busy street without one probably costs more"); one value per class through the day, from the Highway Capacity Manual's two-way-stop levels of service (HCM 6th ed., Exhibit 20-2: A up to 10 s, B 10-15, C 15-25, D 25-35); inferred |
| The rider on the busier road, a side road from one side, a turn off a through street at a T onto one no busier, a turn off onto a quieter street, driveways and alleys | 0 | |

Junctions that cost something and lie within 35 m (115 ft) of the first of them along the
route are one stop at the dearest, or at the signal's wait where one is a signal (a divided
road, a stop line and its junction). Junctions that cost nothing (driveways, way splits)
neither start nor stretch the run, so a street with a driveway every few metres still counts
each stop sign. A flashing beacon mapped as a signal (`core.flashing_signals`) is priced by
who gives way, not as a signal. The answer's `duration_s` is the router's
time plus `junction_delay_s`, and the calm search's score (`refine.Analysis.score`) adds the
delay at what that much quiet riding costs the router (`QUIET_COST_FACTOR`); at the top of
the slider the same quiet metres join the ranking's distance level (`refine.level3`), so
between equally calm routes the one with fewer stops ranks first. A Mountain Bike route's
singletrack retiming applies to the router's time, and the delay is added after it. This is time,
not stress: a junction's stress is still the intersection model's (section above) and the
two do not replace each other. Stop and yield signs reach the router only through
`/locate`, so the model reads who gives way from the roads' classes, not from the signs; no
map rebuild is needed.

## The worker

Procrastinate runs through its Django integration, so its job tables are
ordinary migrations and the worker is a management command:

```sh
./manage.py migrate                      # includes the procrastinate_* tables
./manage.py procrastinate worker         # every queue; compose splits them
```

Compose runs two workers from the same task module: `worker` on the
`maintenance` queue (the backup and the membership sweep, in the API image) and
`rebuild` on the `rebuild` queue (the weekly rebuild, in the pipeline image that
carries the Valhalla and GDAL binaries, with the five data directories it
writes bound under `/data`). The queue split is what puts the eight-hour build in the container with
the binaries and the 8 GB limit rather than in the API's.

A worker started any other way does not work. `procrastinate --app=... worker`
never sets Django up: it dies on the missing schema, and with the schema applied
by hand every task raises `AppRegistryNotReady`. The suite starts a worker cold
in a subprocess and runs a job through it for exactly this reason.

## The source extract

The rebuild makes its own. `FETCH_EXTRACT` downloads Geofabrik's three state
extracts — District of Columbia, Maryland, Virginia, about **1–2 GB together at
today's sizes**, and that figure moves with the map — merges them, and clips the
merge to the coverage region, leaving two files under `<DATA_ROOT>/extracts/`:

- `merged.osm.pbf`, the three states before the clip. This is what
  `valhalla_build_admins` is given (PLAN:13): the clip cuts boundary relations
  at the coverage edge, so admin polygons built from the clipped file stop where
  the box does.
- `source.osm.pbf`, the clip, which every other stage reads.

```sh
curl -fsSL --retry 3 -o district-of-columbia-latest.osm.pbf.part <url>
osmium merge --overwrite -f pbf dc.osm.pbf md.osm.pbf va.osm.pbf \
    -o merged.osm.pbf.part
osmium extract --overwrite -f pbf -s smart -S types=boundary,multipolygon \
    --bbox -78.05,38.2,-76.02,39.72 -o source.osm.pbf.part merged.osm.pbf
```

`-s smart` is PLAN:13's, and the `-S` half is the one that is easy to lose:
without it the strategy keeps multipolygon relations complete and cuts every
other type, which is exactly the administrative boundaries. PLAN:13 writes
`types=any`; the clip names `boundary,multipolygon` instead, because `any` also
completes route relations, and the East Coast Greenway and the US Bicycle Routes
touching the box brought about 5,100 mi of route from outside it into the v0.8.0
graph (southwest Virginia, Pennsylvania, Delmarva). A route relation reaching
into the box is still in the clip, with its member list whole, so the ways
inside it still carry the route.

Every command writes a `.part` and moves it into place on success, so a killed
download is never mistaken for a small region — and `-f pbf` is what that
costs. osmium takes the output format from the output file's suffix, and
`.osm.pbf.part` has the wrong one: without the flag it exits during argument
setup with "unknown format", so the whole staging scheme depends on naming the
format explicitly. `tests/test_source.py` holds every one of these arguments
against `pipeline.source.merge_command` and `clip_command`, and
`tests/test_deploy_docs.py` holds the lines restated here against the same two
functions, because a runbook that prints a command osmium refuses is worse than
one that prints none.

It is not downloaded every run. The extract is rebuilt only when either file is
missing or older than `SOURCE_EXTRACT_MAX_AGE` (six days, just under the weekly
cadence), so a rebuild re-run in the same week reuses it. Force a fresh pull by
deleting either file or setting `SOURCE_EXTRACT_FORCE_REFRESH=1`;
`SOURCE_EXTRACT_URLS` points the download at a mirror. Operations covers the
same rules from the deployment's side, including why the disk gate runs before
the download.

Neither `curl` nor `osmium` is on PATH in this development container and there
is no route to Geofabrik, so this stage has never been executed here:
`tests/test_source.py` holds the command lines argument by argument and
`tests/test_pipeline_end_to_end.py` drives the stage through the rebuild with
both binaries stood in for. Developing against a real extract means either
running the rebuild on the deployment host or putting a small hand-made
`merged.osm.pbf`/`source.osm.pbf` pair in `<DATA_ROOT>/extracts/`, which the
freshness rule will then reuse.

### The coverage box (west edge -78.05 W since v0.7.0)

The box is **(-78.05, 38.2, -76.02, 39.72)**, west, south, east, north: 78.05° W
(78° 3′ W) to 76.02° W, 38.2° N to 39.72° N, about 109 mi (175 km) east to west
and 105 mi (169 km) north to south. v0.7.0 moved the west edge from -78.0 so
all of Martinsburg, West Virginia is in (the owner, 2026-10-12; its city limits
reach about -78.02); Harpers Ferry (-77.74), Shepherdstown and Charles Town were
already inside, and Winchester, Virginia (-78.16) stays out.

`settings.COVERAGE_BBOX` is the one value. Its copies, each held equal to it by a
test, are `frontend/src/lib/geo.ts` (`COVERAGE_BBOX`, the map's coverage mask and
GPX import), `scripts/fetch_basemap.sh` and `scripts/import_photon.sh` (`BBOX`),
`scripts/build_contours.py` (`BBOX`) and `scripts/build_water_restrooms.py`
(`COVERAGE_BBOX`, which `build_food.py` reads). What reads it, and what the new
edge means for each:

- The extract clip (`pipeline.source.clip_command`) and the classification
  checkpoint (`pipeline.checkpoint`, a CLASSIFICATION setting): the first rebuild
  after the change re-clips and does not resume an old checkpoint.
- The elevation stage (`elevation.tiles_covering`): -78.05 lies in the W079
  column, so two more one-degree HGT tiles, N38W079 and N39W079, about 26 MB
  each, are fetched once and cached.
- Contours (`scripts/build_contours.py`): the n39w079 and n40w079 3DEP cells join
  the four, six in all.
- The stress tiles (`core.stress_tiles.outside_coverage`, `straddles_coverage`)
  and the pre-draw (`core.tile_cache`) cover the wider box: a few more tiles at
  each zoom along the west edge, drawn by the post-promotion pre-draw.
- The API's coverage checks (`core.api`, `RouteIn.inside_coverage`), Photon's
  search box (`core.geocode`) and the More links (`routemaker.more_links`) read
  settings and need nothing but the deploy.

What the box does not do is add a state. The rebuild downloads the Geofabrik
extracts in `pipeline.source.GEOFABRIK_REGIONS` (DC, Maryland, Virginia) and
`pipeline.states.REQUIRED_STATES` lists the same three, so West Virginia's roads
are in the map only once `west-virginia` joins them; that work, with West
Virginia's statutory speed default and the closed-by-default US 340
expressway, is the owner's local branch wip/wv (reports/WV-dev-r0.md (not in the repository) on the
PC), to be merged before the v0.7.0 rebuild. On the PC, after the merge and
before the rebuild: re-fetch the basemap (`scripts/fetch_basemap.sh`),
re-import Photon (`scripts/import_photon.sh`), rebuild contours and the water,
restroom and food layers, then run the rebuild; the pre-draw follows the swap.

## Reference data

The rebuild refuses to run without three files under `<DATA_ROOT>/reference/`,
because each stood in for real data in an early version and each produced a
plausible, wrong map when empty. `scripts/install_reference_data.py` installs
them:

```sh
export DATA_ROOT=/srv/routemaker/data   # a checkout's own path here; see below
python scripts/install_reference_data.py --data-root "$DATA_ROOT" \
    --extract "$DATA_ROOT/extracts/source.osm.pbf" \
    --urban-areas "$DATA_ROOT/reference/inputs/tl_2024_us_uac20.geojson" \
    --volume "$DATA_ROOT/reference/inputs/vdot-aadt-2024.geojson" \
        --volume-source vdot --volume-year 2024 --aadt-property ADT \
    --volume "$DATA_ROOT/reference/inputs/ddot-aadt-2024.geojson" \
        --volume-source ddot --volume-year 2024 --aadt-property AADT
```

Two agencies rather than one, because a single one is the case the conflation
step has nothing to arbitrate — `--volume` and its two companions repeat and
are matched up in order. And every input path is absolute: on the deployment
this runs inside the `rebuild` container, whose working directory is `/app`, so
a bare file name resolves somewhere the file is not. Put the GeoJSON files
under `$DATA_ROOT/reference/inputs/`, which that container binds; nothing
outside the five directories it binds is visible to it at all.

`export DATA_ROOT=...` by hand, and never `set -a; . ./.env; set +a`. That file
is compose's input: sourcing it puts every secret in it through a shell, where
`$$` is the pid rather than a literal `$` and a backtick in a value runs a
command, and an exported value then takes precedence over the file when compose
reads it. docs/DEPLOYMENT.md, "`.env` is compose's input, not the shell's", has
the failure this produced.

- `crossings.json` is `fixtures/crossings/potomac-anacostia.json`, copied. Its
  content is community knowledge maintained under the fixture's own README;
  the rebuild logs every row it cannot match against the extract.
- `urban-areas.json` is the list of OSM way ids with **at least half their
  length** inside a Census urban area (`MIN_URBAN_FRACTION = 0.5` in the
  installer). The input is the Census TIGER/Line urban-areas layer
  (`tl_<year>_us_uac20`), converted to GeoJSON with `ogr2ogr -f GeoJSON
  -t_srs EPSG:4326`. A majority of length rather than either extreme, and the
  two errors it sits between are both real: bare intersection graded a Loudoun
  through road urban end to end because a hundred metres of it clipped
  Leesburg's polygon, which is the *lower*-stress reading of an ambiguous input
  on every mile of that road, and containment would grade a District street
  rural because its last block leaves the boundary. The switch is binary — it
  chooses the default speed table, 30 mph urban against 50 rural — so it should
  describe the way rather than its ends.
- `volume.json` is every agency count line with a bidirectional AADT, in the
  shape `conflation.AgencyFeature` loads. The Virginia layer is VDOT's traffic
  volume export from the Virginia Roads portal (`--volume-source vdot`, AADT
  property `ADT`: the export has no `AADT` field, so without `--aadt-property ADT`
  the installer reads 0 lines from it, with exit 0); the District's is DDOT's AADT layer (`--volume-source
  ddot`) and arrives the same way. Directional counts are summed before they
  reach here, which is why the property name is an argument rather than
  guessed.

  **Phase 1 installed VDOT and DDOT; v0.5.0 adds Maryland** (FOLLOWUP-MDOT-AADT,
  OWNER-DECISIONS 429, download approved for that rebuild). MDOT SHA's layer is
  conditionally licensed, and the pipeline can say which agency touched a way
  but cannot yet withhold those ways from a published derivative — identifiable,
  not excludable. No published derivative is built, so nothing carries the
  condition onward today; one that is built must withhold `volume_source =
  'mdot-sha'` until PLAN.md:31-34's waiver is in hand (handoff.md section 7
  carries the row). The Maryland file is MDOT SHA's AADT Segments
  (`--volume-source mdot-sha`, AADT property `AADT`, the default), and two things
  are Maryland's alone. The installer reads the year from the layer's fields
  (`routemaker.mdot_aadt.current_year`: the newest `AADT_<year>` plus one) where
  no `--volume-year` is typed, and leaves out rows whose `LOC_ERROR` says the
  line is misplaced. And the rebuild gives a divided road's second carriageway
  the count conflation gave the first (`conflation.share_with_carriageways`):
  exclusivity along a count line otherwise leaves one carriageway uncounted, and
  MD 185 north of Chevy Chase Circle, the case 429 is about, is two
  carriageways. VDOT's and DDOT's counts are not shared that way, so no tier the
  owner has already seen moves.

  One `--volume-source` flag sets two things, through `SOURCE_TIERS`. `source`
  is the **precedence tier** — `locality`, `state`, `osm` — and it is the only
  vocabulary `conflation.conflate` ranks on. `agency` is the **publisher** —
  `ddot`, `vdot`, `mdot-sha` — and it is the one that travels into the segment
  table's `volume_source` column. The distinction is load-bearing because VDOT
  and MDOT SHA both rank at `state`: a tier in that column could not tell the
  two apart, which is precisely the question a licence asks. The flag is
  casefolded and `mdsha` is accepted for `mdot-sha` (`AGENCY_ALIASES`), and the
  agency is recorded under its one canonical name however it was typed.

  The three columns that carry a count's provenance on the segment table, none
  of them with a Django migration because `create_segment_schema` creates the
  whole schema on every rebuild and the swap promotes it by rename:

  | column | type | meaning |
  |---|---|---|
  | `volume_source` | text | the publishing agency, e.g. `ddot`, `vdot`, `mdot-sha`; null where no count reached the way |
  | `volume_aadt` | integer | the bidirectional count itself, as normalised at install time |
  | `volume_year` | smallint | the count's vintage, nullable: a count nobody can date is a different claim from a current one |

  All three are set whenever a count was in hand, whether or not the volume
  modifier moved the tier, and a stress override keeps them: the question the
  derivative asks is which segments a source touched, not which ones it changed.
  `core.models.Segment` does not declare the last two yet, so they are read by
  SQL and not through the ORM.

Run with only `--data-root`, the script installs the crossings and exits
non-zero naming whichever of the other two is still missing.

### Agency street layers: `roadway.json`

A fourth file, **optional**, which a rebuild reads when it is there and warns
about when it is not (`ReferenceData.road_blocks`): the District's, Baltimore's
and Alexandria's own street records, which know what OSM only guesses at. The
owner approved the first two (OWNER-DECISIONS 151, 159); Alexandria's Transport
Streets is CC0 from the city's OpenData portal (Alex311 reply 2026-10-16, request
26-00041150) and gives only a posted speed where OSM has none (PLAN.md item 183); the records of what was downloaded,
under what licence, and what was found in each are in
`fixtures/datasets/README.md`.

```sh
export DATA_ROOT=/srv/routemaker/data   # by hand, as above
python scripts/fetch_agency_layer.py --slug dc-roadway-block \
    --item 6fcba8618ae744949630da3ea12d90eb --layer <MapServer/163 url> \
    --out-dir "$DATA_ROOT/reference/inputs" --credit "..."   # once; refuses to run twice
python scripts/install_reference_data.py --data-root "$DATA_ROOT" \
    --roadway-block  "$DATA_ROOT/reference/inputs/dc-roadway-block/dc-roadway-block.geojson" \
    --baltimore-centerline "$DATA_ROOT/reference/inputs/baltimore-street-centerline/baltimore-street-centerline.geojson" \
    --alexandria-streets "$DATA_ROOT/reference/inputs/alexandria-transport-streets/alexandria-transport-streets.geojson"
```

`routemaker.agency_roads` parses each layer into `RoadFacts` (per-direction
speed and lanes, one-way, bike facility rank, parking, count), `pipeline.conflation`
matches blocks to ways, `agency_roads.aggregate` combines the blocks along a way,
and `agency_roads.overlay` writes the result onto the tags `classify` reads.

**Matching** (`conflate_blocks`) is not `conflate`. A count is claimed once; a
posted speed describes every way along the block, so a block is shared by both
carriageways of a divided road. And OSM ways and blocks do not break at the
same places (a way can run past twenty blocks), so the question is asked per
stretch: for each probe along a way (every 20 m), which block is it running
along - the nearest within 20 m whose *local* heading agrees, preferring a block
whose street name agrees (`names_agree`: abbreviations expanded, street type and
quadrant ignored). A block that wins at least two probes is one of the way's
blocks; the way is matched when its blocks cover half of it. Trail-class ways
are never matched; a `service` or `track` way is matched only to a block whose
name agrees (`NAME_REQUIRED_HIGHWAYS`), because without that the unnamed
service ways beside Baltimore's streets took 118 miles of the street's 25 mph.
And a block whose name is a *different street's* is vetoed for every other
class except freeways (`NAME_FREE_HIGHWAYS`: motorway and trunk and their
links, which OSM and the agencies name differently: "Anacostia Freeway" is
"INTERSTATE 295"; the matcher is passed these few ways, not the many vetoed
ones): without the veto DC's 36th Place NE, a frontage road beside New York
Avenue, took the avenue's 45 mph, three lanes and 53,745 vehicles a day and
went from LTS 1 to LTS 4. Primary and secondary roads were free of the veto
until review r1 found them taking a neighbour's or a cross street's block
(North Capitol Street took Clermont Drive's; Ohio Drive SW East Basin Drive's
33,679 vehicles). Where one of a way's blocks has a name that agrees, a block
naming a different street is dropped from its shares, and a freeway-class way
takes a differently named block only where the agency classes the block as a
freeway itself (`FREEWAY_CLASSES`: DC's FHWA class 1 or 2, Baltimore's `INT` or
`FWY`; review r2: Canal Road NW, a trunk, took M Street NW's block and went from
35 to 20 mph, and the Whitehurst Freeway and the 3rd Street Tunnel took M Street's
and Washington Avenue's). "BRG" is "Bridge", so the Key Bridge's name agrees. Names: "E Street" and "N
ST NW" are named by their letter (a compass word just before the street type is
the street's name), and plurals are singular ("East Meadow Court" is "EAST
MEADOWS CT"). A way left unmatched falls back to OSM's own tags, the safe
answer. A road OSM has only as `highway=proposed` takes no block
(`UNBUILT_HIGHWAYS`; review r3: 17th Street NE and I Street NE did). The wiring
of these rules to the OSM classes is in one place,
`pipeline.conflation.road_facts_by_way`, shared by the rebuild and the analysis
scripts.

**Direction.** DC's outbound is the block's digitising direction and inbound is
against it (on the one-way blocks `OB` runs with the line 1,023 times to 49, `IB`
against it 888 to 33), and each share records whether its way runs with the
block's line or against it (`BlockShare.along`). So a one-way carriageway of a
divided road takes its own direction's lanes and bike lane, not the busier
direction's (review r1: 384 ways overstated, 51 given the other direction's
lane), and an agency one-way is written in the direction its traffic runs. A
lane is a contraflow lane (`cycleway:left=opposite_lane` with
`oneway:bicycle=no`, which the classifier does not credit to the rider going
with the traffic) **only where DC sets `BIKELANE_CONTRAFLOW`**. On a one-way
block without the flag the bike lane's direction label is not reliable - where
OSM maps a with-flow lane, DC labels it against the traffic 200 times and with
it 56, while all 43 OSM-mapped contraflow lanes carry the flag (review r2) - so
a lone lane there is the with-flow lane, whichever label it has
(`agency_roads._block_bike`). Round 1 read the label and turned 159 ways' with-flow
lanes (13.5 mi; R Street NW, 4th Street SE, V Street NW) into contraflow lanes.
A flagged block whose traffic direction DC does not record (58 of the 110) puts
its lone lane against the way's OSM one-way direction, which is what the flag
says it is (review r3: Argonne Place, Champlain Street, T Street and 8th Street
NW, 8 ways, had OSM's contraflow lane rewritten as a with-flow lane).

**Precedence.** Where matched, the agency's posted speed, lanes per direction
(the larger direction plus any reversible lanes: Connecticut Avenue's are
`TOTALTRAVELLANES` 4, one each way and two reversible, three in the peak
direction), one-way, bike-lane type and width, and parking replace the way's
own tags in what the classifier reads, and so replace the DC default speed
(20 mph), the Maryland and Virginia urban defaults and the arterial-floor's
inputs; those remain the fallback where nothing matched or the block is silent.

In the District the record wins over OSM's own tagging too. OWNER-DECISIONS 190
(2026-10-02): "DC data takes priority over OSM. It's updated regularly." -
speed, lanes, one-way and bike facility, a record of *no* facility included,
with one exception the owner kept: a facility OSM draws as its own way stays on
that way. Review r2 measured where the round-1 rules had left OSM standing in
the District and which of those places a block can and cannot speak for, since
a block describes the whole road and not each of its ways. Each override is
named in `Overlay.precedence` (`dcbal.tsv`'s `item190` column), and each
exception is counted as a disagreement with its reason:

- **A. No facility recorded**: OSM's painted lane (`lane`, `opposite_lane`,
  `buffered_lane`, with its width and buffer) is removed - decided per block:
  only where *no* block along the way records a facility in any direction (the
  weakest-block reading would otherwise erase a lane the District itself
  records on the next block), and where a direction has a lane on one block and
  none on the next, OSM's lane on that side stays. A track OSM maps on the road
  is kept and reported. Another agency's silence (Baltimore's centerline has no
  bike field) never removes anything.
- **B. One-way recorded, OSM explicitly two-way** (`oneway=no`, or lanes counted
  each way): the way is one-way, in the direction the block's traffic runs,
  except on a block with reversible lanes (Clara Barton Parkway: one-way at the
  peak only), a junction stub of 30 m [100 ft] or less, to the whole metre the
  reports print (`MIN_ONE_WAY_OVERRIDE_M`, `is_junction_stub`; review r3: New
  Jersey Avenue NW 1508260473, listed at 30 m, was 30.2 m and overridden), or
  where the direction is not known. The same exceptions hold where OSM tags no
  one-way at all and the record fills one in: since OWNER-DECISIONS 216 the
  record's direction is the routing graph's (below), and a direction the record
  does not give, or a reversible road, is not written. Outside the District an
  explicit two-way stands (review r1: Baltimore's Key Highway). A two-way way
  left on a one-way block keeps OSM's lanes: the busier direction's count is not
  copied into the other (review r2: New Jersey Avenue NW read four lanes each
  way).
- **C. Two-way recorded, OSM one-way**: the way is two-way (C4) - except a
  carriageway of a divided road (C1, `routemaker.divided`), one of two opposite
  one-way ways sharing a block (C2, `agency_roads.block_context`: the pairs the
  divided detector missed), a one-way side lane on a block whose two-way main
  carriageway OSM maps as a way of a busier class (`block_context`'s
  `side_lane`; review r3: K Street NW's tertiary service lanes beside its trunk
  centre - such a lane also keeps OSM's lanes, the block's being the main
  road's; 41 ways), a slip road, a motorway or a trunk road (C3), a roundabout, a
  way that runs on onto a one-way block, a junction stub, and an unnamed way (a
  turn channel beside the named street). A side lane runs beside its main road:
  a roundabout is not a two-way main road (OSM implies its one-way, `junction=
  roundabout` or `circular` without `oneway=no`), and a one-way that shares an
  end node with the main road is one only where at least 66 ft [20 m] of it
  runs beside it, short of its ends (`MIN_SIDE_LANE_BESIDE_M`; the gate review
  found Cedar Avenue, a one-way carrying Cedar Street NW on from its end, and
  Water Street SW, the street changing class, taken for side lanes). The
  overlay also reads a roundabout as one-way (`tags.is_oneway`, item 228) and
  writes `oneway=yes` on it, so a block's lane count is written as one
  direction's and not as two lanes each way. C1 is read wider than the stress reading's divided
  road (item 109 keeps `divided.PAIR_M`, 45 m, and the names as mapped):
  `divided.carriageway_pairs` pairs a one-way with an opposite one-way of the
  same street alongside it within `C4_PAIR_M`, 100 m [330 ft], the name read
  without the District's quadrant, on the residential classes too. The combined
  correctness review found row C4 making carriageways two-way: South Capitol
  Street SW 910656491 (its other carriageway is named Southeast, 12 m away),
  910656606 (88 m) and 1122669898, E Street NW 6056366 (57 to 65 m) and H Street
  NW 50511181 (52 m). With item 216 that would route against their traffic;
  what the wide band can get wrong is the safe way round (a one-way left
  one-way). `tests/data/c4_carriageways.json` holds those ways.
- **D.** A slip road (`*_link`) keeps its own lanes and is never given a block's
  count (review r1: a one-lane ramp took its parent's block and read as 2 to 4
  lanes); the block is the parent road, not the ramp.
- **E. A bike facility OSM maps as its own way is never written onto the road**
  (item 190's own exception): where the way has `cycleway*=separate`,
  `facility.separate_pairs` found its facility's own way beside it, or **any
  other way matched to one of its blocks is so mapped**
  (`agency_roads.block_context`), the agency's track is that way, and writing it
  onto the road rated the motor lanes LTS 1 (review r1: 15th Street NW; review r2:
  Irving Street's motor carriageway, which shares DC's protected-lane blocks
  with the carriageway OSM marks separate); it is counted as agreement. Nor is
  a protected lane written where OSM says the road has none for bicycles:
  `bicycle=no`, `bicycle=use_sidepath` or any `cycleway*=no` (review r2: Arizona
  Avenue NW, `cycleway:both=no`) - counted as a disagreement. A painted lane the
  District records is still written there.
- **Baltimore's speed fills only where OSM has no `maxspeed`** (OWNER-DECISIONS
  184, "Fill gaps only (Recommended)"); DC's posted speed takes precedence
  (item 151). **Baltimore's one-way and lanes are never used** (OWNER-DECISIONS
  222, "Ignore it; keep OSM (Recommended)"; 223: a gap-filler only), for stress
  or routing (`agency_roads.DIRECTION_AND_LANES_IGNORED`): where they differ
  from OSM's the overlay records a disagreement ending "not used
  (OWNER-DECISIONS 222)", which `dcbal.tsv` carries for the report. The
  correctness review found 279 untagged ways (25.0 mi) made one-way by the
  centerline, among them W Cold Spring Ln 66418027 and Broening Hwy 54675215,
  4-lane two-way primaries read one-way with 4 lanes a direction.
- **Owner overrides of a block's record.** A block the owner has corrected is
  named, with the facts withheld, in an override file's `agency_blocks`
  (`agency_roads.withheld_blocks`, read by `road_facts_by_way` from the image's
  `fixtures/overrides/`; fixtures/overrides/README.md), by the layer's own key
  for it (DC's `BLOCKKEY`, kept by the installer as `RoadFacts.block_key`) with
  its street (`ROUTENAME`) as a check, not by the installed block id, which is
  built from OBJECTID, the ArcGIS row number (`agency_roads.resolve_withheld`).
  One that names no installed block, or another street, withholds nothing and
  the rebuild warns of it. Only the posted speed may be withheld: OSM's stands
  on every way matched to the block, and the discrepancy report lists the way
  as not applied, "owner override".
  OWNER-DECISIONS 197 withholds DC's 20 mph on Canal Road NW (dc-4633425-0) and
  the Whitehurst Freeway (dc-4636053-0), which stay LTS 4 on OSM's 35 mph.

The wiring - the block context, the divided-road flag and each way's length -
is in one place, `pipeline.conflation.overlay_road_facts`, which the rebuild and
the analysis scripts call. Where blocks along one way differ, the most
stressful reading describes the way (the highest speed, the most lanes, the
weakest facility): one tier is stored per way.

**Parking width** is used, not only parking's presence: Furth measures a bike
lane beside parking by its *reach*, the lane plus the parking lane, adequate at
**15 ft** [4.57 m] (Mekuria, Furth & Nixon, MTI Report 11-19, 2012, Table 2:
15 ft or more LTS 1, 14 to 14.5 ft LTS 2, 13.5 ft or less LTS 3; the same line
in v2.0 and v2.2). `FURTH_LANE_BESIDE_PARKING_M` was 4.1 m (13.5 ft), the top of
the narrow bin, until review r1. OSM's `cycleway:width` is the lane alone, so
`classify(parking_width_m=...)` adds the parking lane's width (the block's total
divided by its lanes, **narrowest** block) to the lane's for the bike-lane table,
and only where DC records the lane beside a parking lane
(`BIKELANE_PARKINGLANE_ADJACENT`, in every direction that has a painted lane;
`WayFacts.parking_reach_m`). Elsewhere the lane is measured on its own, the
narrower reading. Whether a lane is *decent* (the 40 mph credit) stays on the
lane's own width. The overlay writes the lane's width to the millimetre and the
criterion is met within `stress.WIDTH_TOLERANCE_M` (half a centimetre): the
combined correctness review found a 5 ft lane written as 1.52 m, which beside a
10 ft parking lane came to 4.568 m, 4 mm under the 15 ft line, and 13 DC ways
(0.41 mi) at LTS 2 that are LTS 1. A seven-foot lane beside eight feet of parking passes (15 ft);
a six-foot one does not (14 ft, LTS 2 as Furth has it). The effect of the reach
on its own is a section of `reports/data-comparison/before-after.md`.

**AADT.** A matched way takes the busiest of its blocks' counts (DC's Roadway
Block AADT, 2020) **where no count layer reached the way**, never on a slip
road (`conflation.block_count`), and never replaces one: DDOT's own 2024 layer
is the newer survey. It is recorded as a `Match` of
source `inventory` and agency `dc-roadway-block`, so `volume_source` says where
it came from. Both carriageways of a divided road take the block's count, which
is the two-way road's count and is what the classifier treats each as.

**Graph tags are unchanged but for the direction.** The overlay is what the
classifier reads, as `speed_corrections` is; `facility_by_way` is read from the
same tags, so the facility the map draws is the facility the tier was scored on,
and what Valhalla sees of a way's lane or speed is not touched. The direction of
traffic is the exception (OWNER-DECISIONS 216, "Enforce on all maps"): what the
overlay decides about a way's one-way - rows B and C4 and the one-ways it fills,
with item 190's exceptions, which item 217 approved - is `Overlay.routing`, and
`variants.agency_routing_tags` turns it into the keys it changes in the way's OSM
tags (`run.routing_tags_by_way`), which `inject_tags` lays over the way's tags on
every variant before `variants.inject`. A C4 two-way is written `oneway=no`, not
removed, since the extract writer lays the changes over the source's tags. Where
the record makes a way one-way and flags a contraflow lane, the graph takes it as
OSM would map it (`oneway:bicycle=no` and the `opposite*` lane), which the
standard graph rides and the no-trail graph closes (items 192, 219); where it
flags none, the OSM two-way tagging that upstream would read as a reverse
direction on a one-way (a lane each side, an `opposite*` value) is closed on
every graph, as `close_contraflow` closes it. An approved access override that
set one of those keys stands. So the classifier's `oneway`, the segment row's
`road_oneway` and `road_lanes`, and the graph come from one decision and agree by
construction; `tests/test_pipeline_end_to_end.py` checks it way by way
(`_assert_graph_and_traits_agree`), and `tests/test_lua_remap.py` reads each case
back through `lua/graph.lua`.

**Audit.** Each segment on a matched way carries `attr_sources` (jsonb):

| key | value |
|---|---|
| `maxspeed`, `lanes`, `oneway`, `bike`, `parking` | `dc-roadway-block`, `baltimore-centerline` or (`maxspeed` only) `alexandria-transport-streets` where the agency's value took precedence, `osm` where the way's own tag stood, `default` where neither said and the classifier assumed |
| `aadt` | the agency of the count the classifier read (DDOT's or VDOT's where a count layer reached the way, `dc-roadway-block` where the block's filled in), or `none` |
| `blocks` | the matched block ids (up to 12), `dc-<OBJECTID>-<part>` / `baltimore-<OBJECTID>-<part>` |

`attr_sources` is null on a way no block reached. `volume_source` is
`dc-roadway-block` where the inventory's count was the one used.

Reference notes: Baltimore's `speed` field is the city's street-database speed
and not a survey of signs (its posted-limit fields hold 19 zeros), and it is
read with that source named, where OSM has none; DC's `SPEEDLIMITS_IB` is empty
everywhere and the outbound field holds the limit on 96% of two-way blocks and
1,157 of 1,222 outbound one-way blocks (an inbound one-way block has it on 26 of
1,097 and falls back to OSM or the default). DC's lane totals include bus lanes
(`BUSLANE_*`), counted as travel lanes, and reversible lanes are assumed to
operate (both conservative; OWNER-DECISIONS 179 keeps 16th Street NW and
Connecticut Avenue NW at LTS 4 on that reading). `functional_class` never
reaches the classifier: the Furth tables take no class, and the class the
classifier does read is OSM's `highway`, present everywhere in the region. Its
one reader is the matcher's freeway check above; it is also kept for the
reports and the decimal stress model (FOLLOWUP-DECIMAL-STRESS).

**The discrepancy report** (OWNER-DECISIONS 191: "report the discrepancies when
you see them") is written by every rebuild: the classification stage, from the
overlay it classified with, writes `<DATA_ROOT>/rebuild/reports/dc-osm-discrepancies.md`
and `.csv` (`pipeline.discrepancies`; `run.DISCREPANCY_REPORT_DIR`). Each
District way where the Roadway Block and OSM disagree, by type, applied or not;
the not-applied items (mostly item 190's carriageway exceptions) are summarised
by reason with the longest as examples, every owner override is listed, and the
CSV has every item. It costs one more classification of the District's matched
ways (about 13,600) and never fails a rebuild: an error is logged as a warning
and the stage goes on. The copy in `reports/data-comparison/` is the same report
written from `dcbal.tsv` by the script below.

**The comparison and match reports** are scripts, not stages:
`scripts/analysis/data_before_after.py` (DC and Baltimore, with and without the
layers, over the source extract, the rebuild's own steps; its output feeds
`before_after_tables.py`, `match_report.py` and `dc_osm_discrepancies.py`, the
last of which writes the checked-in copy of the DC-against-OSM discrepancy
report; nothing in it is for importing into OSM, CC BY 4.0 into ODbL needing a
waiver) and
`scripts/analysis/compare_agency_lts.py moco|alexandria|alexandria-lanes|baltimore`
(an agency's LTS against ours, Alexandria's CC0 street speeds and lanes and
Baltimore's facility records against OSM; with `--roadway`, classified as the rebuild does, the
street layers conflated). They load nothing. The reports are in
`reports/data-comparison/`, and the two override files the owner approved from
them (OWNER-DECISIONS 181, 182) in `fixtures/overrides/` (`moco` and
`baltimore` write them; fixtures/overrides/README.md). `arlington` is
internal only (`alexandria`, Transport Streets, was too until the city's CC0
reply of 2026-10-16): it writes to `--internal-out`, which the script refuses inside the repository, and
`reports/**/internal/` is ignored by git as a backstop. Nothing that feeds the
rebuild or a published report reads a layer under `internal-only/`
(`agency_roads.refuse_internal_only`; the installer refuses one).

On a deployment, `$DATA_ROOT/extracts/source.osm.pbf` does not exist until a
rebuild has produced it: `FETCH_EXTRACT` is the stage that downloads, merges and
clips it, and `LOAD_REFERENCE_DATA` is the one after it. So the first rebuild on
a fresh host is run knowing it will stop at stage two, and this script is run
against the extract that run left behind. docs/OPERATIONS.md, "First rebuild on
a fresh host", has the whole sequence; the script runs in the `rebuild`
container, which is the one that binds `reference` and `extracts`.

### Scenic designations: `scenic.json` (v0.8.0)

The Scenic map layer (the owner, 2026-10-16: "Basically looking for a scenic layer in
general. Off by default. How about including covered bridges") names, per way, the
designations it carries, in words: "Rustic Road (Montgomery County)", "Exceptional Rustic
Road (Montgomery County)", "`<name>` Scenic Byway", "East Coast Greenway", "USBR 50", and a
covered bridge's name, joined by " · " in that order, each once (a way along records of
both kinds of rustic road says both)
(`routemaker.scenic.phrase`). Three inputs:

- `reference/scenic.json`, optional, from `install_reference_data.py --rustic-roads
  --scenic-byways` (`routemaker.scenic.rustic_rows`, `byway_rows`): one row a line,
  `{"id", "source", "label", "name", "coordinates"}`, `source` `moco-rustic` or
  `md-byways`. `pipeline.scenic_layer.labels_by_way` matches each source on its own with
  `conflation.conflate_blocks`, as the agency stress ratings are: never a trail, a service
  or track way only where the record's road name agrees, and a differently named way never
  (every rustic road record carries its road's name: the installer refuses a layer with
  none). A byway record never carries one, its name being the byway's, so the name veto
  cannot guard it; instead only trunk, primary, secondary, tertiary and unclassified ways
  are candidates (`BYWAY_HIGHWAYS`: no parallel residential street, ramp, service road or
  track) and a record must cover 70% of a way (`BYWAY_MIN_COVERAGE`, not the blocks'
  half). A way takes the words of every record it lies along.
- the extract's bicycle route relations (`scenic_layer.read_routes`, one more pass over the
  relations, in `FETCH_EXTRACT`'s read with `trail_routes.read_routes`). A USBR is tagged
  three ways in OSM and all are read (`routemaker.scenic.usbr_number`): `ref="USBR N"`; a
  bare `ref=N` with `network=ncn` and `cycle_network` `US:US` or `US` (not `US:MD`, a state
  route's own number); or a name "U.S. Bicycle Route N". The Greenway, relation 1774795 or
  a relation named "East Coast Greenway…", is checked first and is never a USBR, though it
  is on the national network too (`cycle_network=US`). A
  relation's words reach the ways of every relation under it, so a state section of the
  Greenway is the Greenway; cycles are cut.
- the way's own tags: `bridge=covered`, named by `bridge:name`, else by a `name` that names
  a bridge, else "Covered bridge".

The words go to `segment.scenic` (text; no migration, as `sidepath_name`: the rebuild
creates the table whole). The stress tiles carry only `scenic` = true (ETag letter `v`);
the road panel (`core.segment_info`) has a Scenic summary row and a Scenic row under Road
or path with its credits. **Nothing in the classifier, `variants` or the Lua reads it**
(`tests/test_scenic.py` holds that): a scenic road keeps its tier and gets no routing
bonus. The front end is `frontend/src/lib/scenicLayer.ts` and `app/ScenicOverlay.tsx`: a
casing of two 1.5 px teal lines whose `line-gap-width` is the tier's casing, ring and
rails, added under the lowest stress layer; and the covered bridges and viewpoints from
`amenity-data/places.json` (`build_places.py` marks a covered bridge `cv`). The switch is
in Plan's Layers only (`LayersSheetProps.scenic` is null in Go).

### Agency traffic signals: `signals.json` (v0.10.0)

Signals an agency lists and OSM does not map (the owner, 2026-10-19: "I noticed some
traffic signals weren't marked, however, DC has a full listing of them"). DC data beats
OSM (2026-10-11), and so do the other agencies' lists where OSM says nothing or says
less.

- `reference/signals.json`, optional, from `install_reference_data.py --dc-signals
  --md-signals --va-signals --arlington-signals --alexandria-signals --alexandria-hawks`
  (`pipeline.agency_signals.ddot_rows`, `mdot_sha_rows`, `vdot_rows`, `arlington_rows`,
  `alexandria_rows`; field names read in any case): one row a signal,
  `{"id", "source", "lon", "lat", "kind"}`, `kind` `signal` or `hawk`. Each source's
  licence is in `LICENCE_CONFIRMED`; a row of a source not confirmed (Arlington, for now)
  is installed but not read. Alexandria's two layers are one table (257 records), so
  `alexandria_rows` splits it by `signal_type`: a HAWK only from `--alexandria-hawks`,
  the rest (and a record with no `signal_type`) only from `--alexandria-signals`. A
  `REPORT_ONLY` source (VDOT's 2023 snapshot) is matched and reported (`would add`)
  but never marked.
- `INJECT_TAGS` matches them (`agency_signals.match`): a signal with an OSM signal within
  30 m whose nearest junction is the one the agency point marks is "in OSM"; otherwise
  every road junction node within 20 m (three or more road arms; alleys, parking aisles
  and driveways are not arms) is marked `rm:agency_signal=yes`, and a HAWK marks its
  nearest crosswalk node. Only way nodes near a listed signal are indexed, and the
  extract's OSM signals are read in one more pass over its `highway` nodes.
- The transform (`remap.derives_signal`) turns the mark into `highway=traffic_signals`
  over an `uncontrolled` or `unmarked` crossing and a stop or give-way sign on the node;
  a crossing whose `bicycle=no` upstream reopens keeps its class.
- The log line `agency signals: ddot: N added, N already in OSM, N with no junction in
  reach` and `reports/agency-signals.csv` (one row a signal) say what happened. Tests:
  `tests/test_agency_signals.py`, `tests/lua/test_remap.lua`.

## Tiles and the swap

Each variant's tiles live under `<DATA_ROOT>/tiles/<variant>/`: a dated build
directory per rebuild (`20260917T080000Z/`, holding `tiles/`, `tiles.tar` and
the build config), and a `current` symlink the serving container mounts. The
checked-in configs name `/data/tiles/<variant>/current/...`, which resolves to
the same host file inside the rebuild container (`${DATA_ROOT}/tiles` at
`/data/tiles`) and
the serving one (that directory at the same path). The rebuild builds through
a derived config with `current` replaced by the dated directory, promotes by
replacing the symlink, keeps `previous` for rollback, and repoints the
`valhalla_upstream` table before renaming the schema.

`valhalla_service` does not reload tiles, so after a promotion the serving
containers are restarted to load the new extract (`docker compose restart
valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`, and, where the
off-road router runs, `docker compose --profile offroad restart valhalla-offroad valhalla-mtb`:
a `restart` naming a service with no container fails and restarts none of the rest); starting them against the
new build before stopping the old ones is the blue/green arrangement the plan
describes and phase 1 does not implement. `pipeline.promotion.rollback` undoes
a completed swap: schema, tiles and settings table together.

## Container notes

This page was first written in a cloud container whose egress proxy blocked
image pulls, so the Compose stack could not be brought up there. On a
workstation with Docker (Docker Desktop's WSL integration, handoff-local.md
section 3) it can; the native loop above is still the faster one to develop
against, and the stack is where a change to an image, `compose.yaml` or the
pipeline is run (`scripts/acceptance.py --only A1 A2` is the short gate).

`docs/DEPLOYMENT.md` is what the images are: what `docker compose build` builds,
what each image installs and why, the `collectstatic` deploy step, and the list
of things that still stop a `docker compose up`.

### Logs and the rider's position (OWNER-DECISIONS 395, 401)

395 says the rider's position is "never stored or logged beyond the route request, like any
clicked point". A point reaches the server three ways: the route request (a POST with a JSON
body, so no request line holds it), a reverse look-up (`/api/reverse?lat=..&lon=..`) and a search
near the map centre (`/api/geocode?...&lat=..&lon=..`). What keeps it out of the logs:

- **gunicorn** logs the path without the query (`%(U)s`, docker/api-entrypoint.sh), with the
  duration (`%(D)s`): that is where a slow route now shows.
- **Valhalla** (401): no Valhalla release RouteMaker has run, 3.5.1 to 3.9.1, reads a
  `long_request` key. Only upstream's config generator and test configs name it, so there is no
  slow-request log that could carry a request's locations. The `long_request` overrides set under
  401 (`NEVER_LONG_MS`) never did anything, and the 3.9.1 upgrade dropped them
  (reports/valhalla-3.9/README.md). The routers' own per-request lines are the `400::` and `500::`
  error lines, which carry the error text and a request id, not the request. From 3.7.0 every
  Valhalla program reads only the top-level `logging` section, which
  scripts/build_valhalla_configs.py sets to std_out with colour off;
  tests/test_valhalla_config.py::test_every_program_logs_plainly_to_stdout pins that and that no
  per-module section is left. Route timing comes from the app's side: the time of the whole plan
  request, not of each router call (gunicorn's `%(D)s`; the beta's nginx `$request_time`; home's
  Caddy keeps no access log).
- **Beta nginx** (deploy/beta/nginx-routemaker.conf.template): the access log is
  `rmbeta_noquery`, the path only, with no query string, Referer, client address or tester name.
  `/api/reverse` and `/api/geocode` log errors at `crit` only, to their own file (a review addition,
  not asked for by name: owner to confirm, and the same for dropping the client address and tester name), because an
  upstream error line (a 502 while the api restarts, a 504) records the whole request. Every other
  path's upstream errors still reach the host's error log; none of them has a location in a query.
  tests/test_beta_overlay.py pins the format, both servers' access log, and that every
  `/api/...?` path in the front end is one of the two.
- **Tile paths** (`/tiles/stress/{z}/{x}/{y}.pbf`) are logged by nginx and gunicorn and show the
  area viewed, to about a mile [2 km] at zoom 14. That is true of any map pan and is
  not a position fix.

Open: Photon's own request logging is unverified (`docker logs photon` after one search on a dev
stack; a log4j override if queries show). Whether Valhalla logs a request on an error path (no
suitable edges, say) is unverified, and so is the app's own log of Valhalla's refusal text (src/core/routing.py logs it
when a router refuses a route request or a trace_attributes call); `"do_not_track": true` in the route request would be belt and
braces. A `Permissions-Policy: geolocation=(self)` header at the edge is a separate deploy change.

## Contraflow on the no-trail graph

The owner, 2026-10-02 (OWNER-DECISIONS 192 and 193): "contraflow lanes are not
for group rides or mass rides, many routing engines put people on this when it's
not appropriate." and, for a Group Ride with trails on, "with trails on that's
fine". So the closure is built into one graph. A ride chooses its graph through
`core.presets.variant_for_ride`, which `routing.py` calls and which gives
`Variant.NO_TRAIL` to Mass Ride (its preset's own variant) and to any ride whose
request has `trails_off` (the "Keep to roads, not trails" switch, below). Group Ride with trails
on is on the standard graph, which keeps contraflow.

### Trails off (OWNER-DECISIONS 463, 463a, 463b)

The owner, 2026-10-09: "add it". A trails-off switch is offered on every ride
type (2026-09-26, "Every type, roadways ok"). Its label is "Keep to roads, not
trails" (463b; checked is roads only); the link parameter and the API field keep
the names `trailsoff` and `trails_off`. The request field is
`trails_off` (`core.api.RouteIn`, a strict boolean, default false), carried as
`Dials.trails_off` to `presets.variant_for_ride(name, when, assist, trails_off)`,
which gives `Variant.NO_TRAIL` whatever else the ride asks. The answer's
`dials.trails_off` says what was planned: true on Mass Ride whether or not it
was sent, because Mass Ride is always trails off.

What it means is what the no-trail graph leaves out (`pipeline.variants.inject`,
`is_trail_class`): every way whose `highway` is `cycleway`, `footway`, `path`,
`pedestrian`, `bridleway` or `steps`, whatever its bicycle tag, plus the roadways
of the sidepath-only bridges (Chain Bridge, the George Mason span, the Wilson
Bridge). It also gives no ride a one-way street against its traffic
(`close_contraflow`) and no credit for painted or protected lanes
(`facility_neutral`); the lanes tagged on a road stay in the graph as the road.
The Key Bridge and Arlington Memorial Bridge roadways (`roadway_mass_ride_only`)
are barred on the standard and e-bike graphs and open here, so any trails-off
ride may use them. The switch's hint says this in plain words
(`frontend/src/lib/dialsPanel.ts`, `TRAILS_OFF_HINT`, `TRAILS_OFF_HOW`).

E-bike rides (463a). The owner, 2026-10-09: "Most ebikes are allowed on
multiuse trails." So an e-bike ride with the switch on, the E-bike ride type or
electric assist on Cargo Bike, plans on the no-trail graph like any other ride,
with no lock, at its assist pace. It does not get the e-bike graph's one rule,
`bicycle=no` on ways tagged `electric_bicycle=no`
(`pipeline.variants.bars_electric_bicycle`); with the trails gone, that rule
would matter only on a road that bars e-bikes. Counted on 2026-10-09: the
clipped source extract (`source.osm.pbf`, 4,564,476 ways) has no way at all with
`electric_bicycle=no`, so no road, and the e-bike and standard variant extracts
of that build are byte for byte the same. The full three-state extract has 14,
every one a `highway=path` trail in western Virginia, outside the coverage and
trail class anyway. If a road inside the coverage is ever tagged so, carrying
the bar into the no-trail graph is a tile change and a rebuild (a recorded
follow-up, not built).

Confirmed by the owner (OWNER-DECISIONS 463c): Gravel and Mountain Goat with
trails off take the no-trail graph, not the off-road graph; a weekend ride takes
it without a weekend twin, as Mass Ride does. The trail seek does not run (`limited: "roadway_only"`), as on Mass Ride.

What differs from Mass Ride, which shares the graph (the correctness review of
wip/trails-off):

- `highway=track` is not trail class, so unpaved farm and forest roads stay on
  the no-trail graph and a roads-only ride may use them; "How this works" says
  so ("Unpaved farm and forest roads stay.").
- The breakdown counts a painted or protected lane as a lane. Bike lanes are
  "none" only on Mass Ride, which takes the roadway (`Context.lanes_as_roadway`,
  `routing.classify(..., roadway_only=...)`, from the preset's own variant); the
  graph's `facility_neutral` still gives the lanes no credit on every
  trails-off ride.
- No long calm plan (`routing.long_calm_for(..., trails_off=True)` is false):
  Trailmaxxing at the top with trails off plans as the other ride types do at
  the top, rather than spending the long ride's budget on a leg-by-leg search
  for trails it has turned off.
- Its no-route message names the switch ("With Keep to roads, not trails, this
  ride routes only on roadways ..."); a Mass Ride's names Mass Ride, as before.

`pipeline.variants.variant_for` and the `Variant` docstring still say the
no-trail and e-bike variants are mutually exclusive and that Group Ride is the
one ride with the toggle. They are stale after 463 and 463a (the route API asks
`core.presets.variant_for_ride` and never calls `variant_for`), and are left as
they are on this branch because `src/pipeline/variants.py` is a beta CD stop
path (`scripts/beta/cd_logic.py`): a recorded follow-up for the next branch that
changes that file anyway.

The front end holds it as `Dials.trailsOff`, absent for off. It is in the link as
`trailsoff=1` (written only when on; a link without it is trails on, so every
older link opens as before, and Mass Ride is trails off whatever the link says),
in the request as `trails_off: true`, in the Ride line as "roads only" (not on
Mass Ride), in a GPX export's dials comment as `trailsoff=1` (read back on
import, so the file reopens on roads only) and its description as "roads only,
no trails" (neither on Mass Ride), and stays when the ride type changes, as
Avoid gravel does. The
control is a real checkbox with the label "Keep to roads, not trails",
described by its hint ("No bike paths, trails or stairs. Can use the Key and
Memorial Bridge roadways."; on Mass Ride it starts "A mass ride always keeps to
roads."), with its own "How this works" (read "How this works: keep to roads");
on Mass Ride it is checked and `aria-disabled` (in the Tab order, a press changes
nothing), as "Make it a loop" is when the ride is a loop already. The browser
check (`scripts/a11y/check.mjs`) covers it.

**Deploying it.** API and front end only: no migration, no data rebuild, no
tile, router or compose change, and no CD stop path (`src/pipeline/variants.py`
is as on main). Roads-only rides move load onto `valhalla-no-trail`, which has
the same limits and threads as the standard router; watch its latency and
memory on the beta after release. Rollback: revert the API and the front end
together (a new front end sending `trails_off` to an old API gets a 400 until
the page reloads); `trailsoff=1` links and GPX files then plan with trails on,
with no error shown.

`pipeline.variants.inject` calls `close_contraflow` last on the no-trail
variant, after the trail and sidepath drop. On a way that is one-way for motor
traffic (`is_motor_oneway`: `oneway` of `yes`, `true`, `1` or `-1`, or
`junction=roundabout` or `circular`; not `reversible`, `alternating`, `no` or a
way that says nothing) it rewrites the tags so that upstream's `ways_proc` gives
a bicycle the way's own direction only. What upstream reads as a reverse
direction on a one-way, measured through `lua/graph.lua` under LuaJIT
(`tests/test_lua_remap.py`), and what closes each:

| What opens the other direction | Closed by |
|---|---|
| `oneway:bicycle=no` (also `-1`, which double-flips on a `oneway=-1` way) | `oneway:bicycle=yes` |
| `cycleway`, `:left`, `:right`, `:both` of `opposite`, `opposite_lane`, `opposite_track` | that value rewritten to `no` |
| a lane, track or sharrow on both sides, or `cycleway:both` (the District's usual shape: `cycleway:left=lane`, `cycleway:left:oneway=-1`, a sharrow on the right) | the side against the traffic rewritten to `no`; a `:both` spoken for on the traffic's side (the right, or the left on `oneway=-1`) |
| `vehicle:backward` | rewritten to `no` |
| `bicycle:backward` (`yes`, `no` or any other value) | rewritten to `none` |
| `bicycle:backward:conditional`, or `bicycle:conditional` on a one-way that grants contraflow, which `remap_conditional_access` turns into a direction | `bicycle:backward:conditional=no` |

Three things are not obvious, and each is pinned by a test.

- Everything is rewritten, never removed, because `extract.write_extract` lays
  `inject_tags`' diff over the source's own tags and a deleted key would come
  back (`bar_mass_ride_only_roadway` says the same).
- `bicycle:backward` is written `none`, not `no`. Upstream reads a
  `bicycle:backward` of `yes` or `no` as a second direction and, beside
  `oneway:bicycle=yes`, closes the *with-flow* direction. `none` is the other
  value its bicycle table reads as false. A blanket `bicycle:backward=no` on
  every one-way, the shorter rule, was rejected for a second reason:
  `routemaker_remap.access_is_unrestricted` reads that key, and a way it calls
  restricted loses the stress penalty (`bicycle=use_sidepath` on tier 3 and up)
  and the no-trail lane removal. Of the keys the closure writes, that is the
  only one the restriction test reads, and the closure writes it only on a way
  that already carries `bicycle:backward` (one such way in the extract). So the
  remap does not count `bicycle:backward=none` on a one-way as a restriction
  (`CLOSED_REVERSE_BICYCLE`): it closes a direction the road's class never gave
  and says nothing about riding with the traffic. Without that, a one-way tagged
  `bicycle:backward=yes`, `designated` or `permissive` would turn restricted on
  the no-trail graph alone. Nowhere else is `none` excused: on a two-way way, or
  on another key, it is a restriction as before, and no way in the source
  extract carries it.
- A with-flow conditional (`bicycle:forward:conditional`) is left alone.

**Stress and the map are not touched.** The stress tier and the facility class
are computed once, from the way's own tags (`classify_facilities`, `stress_by_way`),
before any variant exists; `run.inject_tags` hands each variant those values as
derived tags and only the routing tags differ. So the stress tiles, the map
layers and the segment table read the contraflow lane as the facility it is
(11th Street NW is a `lane` on the map and its no-trail routing tags no longer
carry one). `tests/test_pipeline_end_to_end.py::test_the_no_trail_graph_closes_contraflow_and_nothing_else_moves`
runs a one-way through the rebuild and compares the tier, the facility and the
segment row across the variants.

**The Roadway Block overlay.** The District overlay (`agency_roads.overlay`,
which writes `cycleway:left=opposite_lane` and `oneway:bicycle=no` from
`BIKELANE_CONTRAFLOW`) puts its tags in `context.class_tags_by_way`, which
classification and the facility read. Since OWNER-DECISIONS 216 its direction
reaches every variant's routing tags as well (`run.routing_tags`, above), laid
over the way's tags before `variants.inject`, so `inject` is still the last word:
a one-way the District records is closed on this graph like any OSM one-way,
its flagged contraflow lane included, and a District two-way has nothing to
close. An approved access override that writes `bicycle:backward=yes` onto a
one-way is likewise closed on this graph and only this graph, as the mass-ride
bar is (OWNER-DECISIONS 219: "No, Mass Ride never goes against traffic").

**A conditional never opens a one-way against its traffic, on any graph.**
`remap_conditional_access` resolves a bicycle conditional onto the directional
keys, and it used to write the undirected `bicycle:conditional`'s least
restrictive branch onto `bicycle:backward` too. On a one-way upstream reads that
key as a second direction, so Pulaski Highway (two ways, 2.93 miles: `highway=trunk`,
`oneway=yes`, `bicycle=no`, `bicycle:conditional=yes @ (Sa-Su dawn-dusk; ...)`)
was rideable against its traffic on the standard, weekend and e-bike graphs. That
is a remap artifact, not a contraflow lane, so item 193 does not cover it. On a
way that is one-way for motor traffic (`routemaker_remap.is_motor_oneway`, the
same values as `variants.is_motor_oneway`) the reverse is now widened from a
conditional only where the way speaks for the reverse itself
(`speaks_for_reverse`): `oneway:bicycle` of `no`, `false`, `0` or `-1`, an
`opposite*` cycleway value, a `bicycle:backward` or `vehicle:backward` of `yes`,
`designated` or `permissive`, or a directional `bicycle:backward:conditional`,
which is the mapper's own statement about that direction. The with-flow side
is resolved as before, so the weekend grant still opens Pulaski Highway with
the traffic, and a two-way way's undirected conditional still opens both
directions. Nothing else moves: the mass-ride bar's bare `no` conditionals
(Key and Memorial bridges) open nothing either way, and the weekend graph's
car-free roads come from the motor-vehicle conditionals
(`routemaker.facility.car_free_when`), which this function does not read. `tests/test_lua_remap.py` checks it through `lua/graph.lua` on every
variant and every one-way spelling.

**The router applies the time window** (FOLLOWUP-CONDITIONAL-ACCESS, the owner,
2026-10-29). The static grant above opens the way; Valhalla's C++ parser then reads
the undirected `bicycle:conditional` as a timed restriction, so the edge is open
only inside the window at the request's `date_time` (every plan sends the ride
time's representative moment: Saturday 9:00 for a weekend ride, Tuesday 8:00 or
12:00 for a weekday one). The parser drops a rule with a sun event in it,
reads only `yes`, `designated`, `private` and `delivery` as grants (`permissive`
reads as a denial), and reads one rule set. So for an undirected grant
`remap_conditional_access` writes `bicycle:conditional` again as one `yes @ (...)`
of the granting branches, each sun event a fixed time that keeps inside the real
window every day of the year here (`SUN_LATEST` for a start, `SUN_EARLIEST` for an
end: dawn 07:15, dusk 17:10, so Pulaski Highway reads `yes @ (Sa-Su 07:15-17:10;
PH 07:15-17:10)`). A grant whose condition cannot be so written (`wet`, a window
between sun events across midnight) is not opened at all, as unclear access is
closed; nor is one on holidays alone (`PH dawn-dusk`), since the parser drops a rule
that starts with a holiday and a grant with no rule left would reach it as open at
every hour. A bare grant with no condition opens the way unconditionally, as before.
A request with no `date_time` (map matching, the stop-order matrix) leaves timed
restrictions unchecked, so there the way reads open at every hour, as before. A directional conditional (`bicycle:forward:conditional`), which the parser
does not read, is still resolved statically. A Saturday 9:00 plan should ride Pulaski
Highway with the traffic and a Tuesday plan should not (not yet checked on built tiles). The fixed times are a
conservative approximation, short of the real window in summer.

**Measured** on the 2026-09-25 clipped region extract
(`scripts/contraflow_census.py`, read-only; 137,518 non-trail one-way ways):
192 ways and 15.97 miles (25.70 km) have contraflow on the standard reading
(the router's answer for the way's own tags) and none on the closed one. 187 of
them (15.86 miles) are named by a contraflow tag; 5 (0.11 miles) are lanes on
both sides, which upstream reads as two-way (Covington Street in Baltimore,
Prince Frederick Boulevard, South Dakota Avenue NE and two more). The census
also asks the transform again with the bicycle conditionals taken off, which
`has_contraflow_tag` does not see, and lists every one-way, trail class
included, that a conditional alone opens against the traffic on the standard
reading: Pulaski Highway's two ways before the fix above, none after it, and
no other way in the extract (14 one-ways carry `bicycle:conditional`, all on or
beside Pulaski Highway; none carries `bicycle:backward:conditional`). Zero ways are still open
after the closure, and zero lose the with-flow direction. The count is OSM's
tags only; where the Roadway Block records a contraflow lane that OSM does not
tag, the standard graph does not have it either.

`tests/test_contraflow_fixture.py` runs nine real District streets from that
extract (`fixtures/contraflow/dc-contraflow-streets.json`: R Street NE, 8th
Street NW and NE, 11th Street NW, M Street NW, Kentucky Avenue SE and others)
through the injection and the real transform: contraflow on the standard graph,
none on the no-trail graph, only the contraflow keys changed, the classifier's
answer on the source tags pinned.

## Lua

The tag transform runs under LuaJIT, because Valhalla's build (3.5.1 to 3.9.1) requires it
(`pkg_check_modules(LuaJIT REQUIRED IMPORTED_TARGET luajit)`) and its own
`graph.lua` calls `bit.bor`, which stock Lua 5.2 and later do not provide. Code
under `lua/` therefore has to stay within Lua 5.1 syntax; `//`, the bitwise
operators and `goto` parse under a developer's `lua5.4` and fail inside the
container, where the failure shows up as Valhalla silently falling back to its
compiled-in transform rather than as a crash.

```sh
apt-get install -y luajit lua5.4
```

`lua/vendor/graph_upstream.lua` is Valhalla's own transform at the pinned
version, checked in so the entry-point contract can be tested against the real
file. Refresh it with `scripts/vendor_valhalla_lua.sh [VERSION]`; do not edit it. The
script fetches it and `valhalla/vendor/valhalla_build_config.py` to a scratch directory,
checks them (a pinned re-vendor must reproduce the sha256 in each folder's `SHA256SUMS`,
which the suite also checks) before moving them into place, and then regenerates
`supported_keys.txt` and the service configs; read the diff.

Setting `CI=1` turns the suite's missing-interpreter skips into failures.

The Lua suites prove what the transform hands Valhalla, not what the tile says:
Valhalla's C++ parser reads tags off that table afterwards, and its reading of
`mtb:*` ratings reopened every rated singletrack way while both suites passed
(docs/OPERATIONS.md, "Bicycle closures in the tiles"). `tests/test_tile_build_access.py`
builds and serves real tiles to check that. It needs `valhalla_build_tiles`,
`valhalla_service` and `osmium`, so it **skips** here and in CI, and `CI=1` does
not change that. `ROUTEMAKER_REQUIRE_TILE_BUILD=1` does: a missing binary then
fails the run. Run it in the pipeline image, where it cannot skip:

```sh
scripts/check_tile_build_access.sh
```

## Running the suite twice at once

**A private `PGDATABASE` is enough on its own.** Each Postgres database is its
own namespace, so two runs against two different databases cannot drop each
other's schemas no matter what either one names `live` and `staging` — the
whole failure mode below only exists when two runs share one database.

```sh
PGDATABASE=routemaker_b .venv/bin/python -m pytest
```

`ROUTEMAKER_LIVE_SCHEMA` and `ROUTEMAKER_STAGING_SCHEMA` exist for the
narrower case that actually needs them: two runs sharing one database — a
shared CI Postgres instance, say — where the `live`, `staging` and `live_old`
schema names themselves would otherwise collide and each run would drop the
other's tables mid-test, producing failures that read as code defects rather
than as contention. `tests/test_schema_swap.py` and the rest of the suite take
their schema names from the `segment_schemas` fixture and from
`settings.SEGMENT_SCHEMA_LIVE` / `SEGMENT_SCHEMA_STAGING` rather than writing
`"live"` / `"staging"` as literals, so setting these alongside a private
`PGDATABASE` is safe:

```sh
PGDATABASE=routemaker_shared \
ROUTEMAKER_LIVE_SCHEMA=live_b \
ROUTEMAKER_STAGING_SCHEMA=staging_b \
  .venv/bin/python -m pytest
```

The suite is green both with these two variables unset and with them set to
non-default names; both invocations are exercised before either is relied on.

The production side has no such literals either: the rebuild's staging schema, the
writers' live guard and the swap all read the settings, and
`tests/test_pipeline_end_to_end.py` runs a whole rebuild under renamed schemas to hold
them to it.

## The final-fix round (2026-10-03)

The fixes after the six-reviewer re-check of 2b0cf00, and OWNER-DECISIONS 246 to 250.

### `road_oneway` is the graph's direction

`StressResult` has two readings of a way's direction. `oneway` is item 109's: the
classifier's one-way relief, False on a carriageway of a divided road (the other
direction is across the median, so for the tier it is half of a two-way road).
`graph_oneway` is `tags.is_oneway` of the tags the classifier read (a roundabout
included, item 228), carriageway or not: the routing graph's own direction. The
segment table's `road_oneway` is written from `graph_oneway`
(`pipeline.run.write_segments`); the override and car-free copies carry both. The
junction model (`core.junctions._with_graph`) keeps the table's value over the car
arms, both ways, and lets the arms decide only where the table has nothing (the live
table before its rebuild); tests/test_junctions.py `TestTheSegmentTablesDirectionWins`.
Written from `oneway`, every carriageway would have been read two-way after the
rebuild: no median-refuge credit, its lanes doubled ("6-lane" for Connecticut Ave
NW's three), and a Mass Ride left-across marker off it.

### Mass Ride keeps one-way (item 246)

`pipeline.variants.routing_for(variant, tags, routed)`: the no-trail graph does not
take a District two-way record (`oneway=no`, row C4) over a way OSM has one-way. The
classifier and `road_*` follow the solo graphs (they are one per way), so on a Mass
Ride the junction model reads those streets two-way: it can only overstate a
junction there. 181 ways (13.8 mi) on the 09-25 extract, 21 of them (0.9 mi) LTS 3
or worse.

### The junction list and the description, for a screen reader

- Every junction row, group and member is named by one `aria-label`
  (`intersectionMarkers.rowName`: "Very high stress, Group: ...", "Higher stress, At
  0.6 mi (1.0 km): ..."). The spans are grid items, and a name computed from them put
  a space before each comma and colon.
- The description list has no scroll box of its own (its `max-height` is gone): the
  panel's scrolling part (`.panel-scroll`, or on a short or zoomed screen the whole
  `.panel`; "The sidebar (312)" below) is the one scroll container, and it holds the
  fold's summary, the checkbox and the buttons, so it is scrolled by keyboard in every
  browser. A
  focusable `tabIndex={0}` box would have added a Tab stop with nothing to do and,
  with a group's crossings nested in it, a box inside a box on a phone. The browser
  check asserts that every visible scroll box in the panel is focusable or holds
  something focusable.
- In the app the list is the route summary's Directions fold, a native `<details>`
  whose summary reads "Directions (11 steps)", after a hidden h3 "Directions". Without
  `fold` the component still draws its own heading and a toggle named "Route
  description: 11 steps, overview" (no caller in the app uses it now). "Full detail"
  has no leading space and a 24 px target; Copy clears its reply and sets it again 150 ms
  later, so a second press is said again.
- At 320 px with WCAG text spacing a row's severity and distance wrap inside it
  (`grid-template-columns: 18px minmax(0, auto) minmax(0, 1fr)`, `white-space:
  normal`).
- The browser check (scripts/a11y/check.mjs) adds sections 7 and 8: the rows at
  320 px with text spacing, and the description (the Directions fold's summary, the
  scroll boxes, Full detail, the copy reply, a group's nested crossings).

### The App.tsx split (UI-CLEANUP step 4)

`App.tsx` holds the planner's state, its effects and the handlers, and renders the page
shell (the skip links, the map, the road panel, the live regions, Ride mode, the panel
and its header). What the panel shows is in `app/`, moved out unchanged:

- `app/Planner.tsx`: `PointsSection` (the search, the loop toggle, the points, the
  nearest finder, the point tools, More tips, the Points notice) and `RideSection` (the
  Ride line and, behind its Edit, the ride type and every dial).
- `app/RoutePanel.tsx`: `RouteSection` (planning, the long-ride question, errors, the
  Avoid notice, `RouteSummary`, water along the route, Start ride's question),
  `RouteSummary` itself, `RouteActions` (the pinned Download GPX, Copy link, Share and
  Keep for offline) and the `Status` type.
- `app/Sheets.tsx`: `LayersSheet`, `GpxSheet` and `SettingsSheet`, each in its `SheetFrame`
  (since the UI-CLEANUP build also the Legend, Suggest, Review, Nearest, Find food and Ride
  sheets; and `app/Go.tsx`, below).
- `lib/layerSection.ts`: `LayerSection`, one Layers section (the owner, 2026-10-12): a row of
  its heading, one switch for the section (Off remembers which layers were on, in
  `routemaker.layerSections`; On brings them back, else all; some on says "Some on") and a
  disclosure, closed to begin with, over the layers' own switches. A layer's extra control (the
  Climbs layer's "Show climbs from") goes inside, under that layer's switch; long help goes by
  the legend in the Legend sheet, not in Layers.
- `app/hooks.ts`: `useNarrow` (and `NARROW`), `useLongerThan`, `useSettled`.

Each component is a pass-through: it takes its props under the names App gives them, keeps
no state and calls no hook (`RouteSummary` keeps its own `useStressStyle()`), and App renders
it with `<PointsSection key="points" {...{ pointsHeadingRef, zoom, ... }} />`, so the elements,
their order, the focus moves and every announcement are as they were. `useId` stays in App
(the loop hint's id), because React numbers a client render's ids in render order.
`appSplit.test.ts` holds that shape.

The source tests that read App's wiring read `testSupport/appSource.mjs`'s `appSource()`:
App.tsx with each component's JSX put back where App renders it, then the rest of the
modules (their imports, `RouteSummary`, the hooks) without the props interfaces, which only
repeat App's names. A new test of what the planner renders reads it the same way.

Checked when it was split: the DOM of the whole page but the map's own internals was the
same before and after in 60 snapshots (30 states at 390 px and 1,440 px: empty, a route,
Bikeshare, Mass Ride, Trailmaxxing, routes to choose from, an Avoid junction, each sheet,
the ride settings, Edit points, every fold open, Start ride's question, the panel hidden and
shown), and `scripts/a11y/check.mjs` passed the same checks.

### Go and Plan (UI-CLEANUP, the approved mockup of 2026-10-11)

The layout Stephen approved on 2026-10-11 (reports/v0.5.0/ui-mockup.html (not in the repository) and its 72-row
control table; PLAN.md, UI-CLEANUP). Nothing was removed: every control is where the table
puts it, at most two presses away.

- **Two views of one planner** (`lib/appMode.ts`): Go, a phone's few steps (one Where to?
  box, four place chips, the commute ride types, then the route's time, stress bar, one
  alert and Start), and Plan, the full panel. Same state, same link. Which one opens:
  the tab's own (sessionStorage, so a reload stays), else Plan for a link with a plan in
  it on a wider screen, else a phone (`NARROW`) opens in Go and a wider screen in Plan. My Go's
  Open in was dropped on 2026-10-22 (the owner: "It should open in plan on a computer and go on
  a phone"); a saved `open_in` is kept in the data but never read to choose a view.
  The switch (`app/Go.tsx` `ModeSwitch`: `aria-pressed` buttons in a named group, Go and Plan, plus
  Review for an admin) is in Go's bar over the map and Plan's header; a press is remembered for the tab only.
- **Go** (`app/Go.tsx`): `GoTopBar` (Menu, the switch, Layers, Locate, and the destination
  with a clear button) is before the map in the page, as it is at the top of the screen.
  `GoSheet` (inside the panel, `peek`/`half`/`full` by its handle) holds `PlaceSearch
  variant="go"` (the place is the destination, the start the rider's location, in one edit
  with the loop off: App `goTo`), the Home, Food, Water and Restroom chips (Home needs sign-in
  and a Home; without one it opens My Go and says why), `RideChips` (Default, Cargo, Bikeshare
  and More; a My Go ride that is none of them takes Bikeshare's place: `lib/myGo.ts`
  `goRideChips`) and the Route section's Go variant. The Menu is the Settings sheet with
  Plan, Suggest, GPX and an admin's Review on top; a Go sheet's Back reads "Close".
- **Go's start** (the owner, 2026-10-11: "in go, make the current location the starting
  location by default"; `lib/appMode.ts` `shouldAskGoStart`, `goStartLine`, `goRouteStart`):
  when Go opens with an empty plan, App asks for the location once (through Use my location's
  gate; never in Plan, never with a start from the link). The found start is stamped with its
  time (`goHereStart`): older than `GO_START_MAX_AGE_MS` (2 min; the owner, 2026-10-19: "Go
  mode sometimes picks a stale current location") it is not routed from (`goStartStale`), so a
  pick looks the location up again, and when the page comes back into view in Go with an empty
  plan a stale start is looked up again quietly; Go's Locate moves it too. A destination set in
  Go from a fresh start looks the location up again too (the owner, 2026-10-19: "update when
  setting a destination too"; `goPickStart`): a fix within `GO_PICK_LOOK_MS` (3 s) more than 25 m
  away is the start; otherwise the start Go had stands (so a rider who has not moved keeps the early
  route), and a later fix still moves Go's start. So that look-up is quick, Go warms the location
  up while the rider is in Where to? (routing audit S28; `goWarmDue`): when the box takes the focus
  or an early start fires and the start is over `GO_WARM_AFTER_MS` (20 s) old, it is looked up
  again in the background, at most once per 20 s, around the gate (the locate button does not look
  busy) and with nothing waiting on it; the tap's own look-up then gets the browser's recent fix
  (`maximumAge` 30 s) at once. A press still looking after 1 s is said with "Finding
  your location for the start…", as one waiting for a start is. Found, it is the start, shown on Go's
  start line and said politely ("Start: your current location.") but not yet a point, so the
  link holds no position until a destination is picked; denied, unavailable or timed out, the
  start stays empty, the start box opens and "Current location not available; type a start." is
  shown and said politely. A start typed in (Change start, `PlaceSearch variant="start"`), or
  one placed in Plan, is the plan's first point and replaces the location (a press on the map in Go opens the spot's card, whose Route here makes it the destination). A destination picked
  before there is a start is never dropped nor made the start (`goPickAction`): while the
  location is still being found it waits ("To …: finding your location for the start…") and is
  routed when the location comes; with no location, it is kept ("To …. Current location not
  available; type a start.") and a start typed in the start box plans the route to it at once. A
  press on the map in Go, the route line included (a drag of the line still adds a stop; `lineTapIsPoint`), opens
  the spot's card (`GoSpotDialog.tsx`, lib/spotNearby.ts, the owner 2026-10-28): its address, the places near it as
  pins on the map, and Route here; the press alone never routes. That Route here, or Map tools' "Set destination at
  map center" (at once), is the destination, routed as a picked one is and said "Destination set: …" (named by `goPlaceName`, the same on the sheet: its coordinates until
  its place name comes; a press on a water, climb or federal-land card's feature, or one that only closes such a card,
  is the card's alone, `featureCardPress`; `goTapSetsEnd`, the owner 2026-10-12; it replaces #95's tap-as-start). Picking a
  destination with a start plans at once (a location start after its look-up, at most 3 s); Go then shows the routes to choose from open, and the ride types under the
  route, so Bikeshare is one press, and only a Bikeshare route names its pick-up and drop-off
  stations (the route's Bikeshare plan).
- **Few presses** (the owner, 2026-10-11 20:23 UTC: "just ... find a destination and go"): from
  opening Go, a typed destination is three taps to riding: Where to?, the place picked, then
  Start ride (the review of #95 counted them); with the Home chip it is two: Home, then Start ride
  (signed in, three: Favorites, Home, Start ride; see Favorite places below). Go
  starts the ride with Settings > Ride mode's cues and asks nothing first (Plan still asks the
  first time). **Screen-reader detail** (it was Announcements; `lib/announceLevel.ts`, Settings > Display): Brief or Full,
  kept on this device; unset, Go is Brief and Plan is Full. The route found, guidance, the start
  Go found, errors and notices are always said; Brief leaves out the narration (`announceExtra`:
  finding your location, planning a route to, the view or ride type changed, the map moved).
- **Lettered places** (the owner, 2026-10-11 21:04 UTC; `lib/letteredPlaces.ts`): the nearest
  water, restrooms or Metro stations and the food found are lettered A, B, C... in their list (a
  pin, aria-hidden, with the letter heard first) and on the map (MapView `lettered`: 44 px
  buttons, a pin with the letter, named "B: Drinking water, Garfield Park, 0.3 mi (0.5 km)"),
  while that list's sheet is open; the map fits them in, above a phone's sheet. A marker's tap
  or the letter's key (not while typing, on the map or in a dialog), and a row of Go's Repair or
  Sights, opens the place's **stop card**; the rows' own Ride here and Add as stop act at once.
  Food's numbered circle layer is gone; its list and markers use the letters. The Choose a
  station lists (Plan) are not lettered.
- **Stop cards** (Stephen 2026-10-19: "when pressing on food or other stops provide information
  on what's there including a link to the website if available. Then offer a route/detour here",
  and "don't auto route"; `lib/stopCard.ts`, `lib/stopWords.ts`, `app/mapOverlay.ts` `stopCard`):
  a press on a lettered pin, a food, places-to-see or repair-stand dot, or a water or restroom
  icon opens one card and never routes or places a point by itself, in Go or Plan (MapView's
  main click counts the stop layers as feature cards in both modes). Most important first: the
  name, what it is, Open now or Closed now where the mapped hours can be read (else the hours as
  mapped), how far or the detour; then one action and the website (http or https only, a new
  tab, named "Website: <place> (opens in a new tab)"). The action is Route here before there is
  a route (Go: from Go's start; Plan: from the rider's location with an empty plan, else as the
  end) and Add as stop with one (Go: where it is shortest; Plan: as a stop). Nothing while
  riding.
- **Bikeshare options** (`lib/bikeshareOptions.ts`; #94's `bikeshare.options`): a Bikeshare route
  in Go lists its pick-up and drop-off pairs as buttons lettered A, B, C, each named by the
  option's own `text`, the one the shown plan rides pressed (aria-pressed and a "Planned" tag),
  and letters them on the map at each pick-up station. A button, a marker or the letter's key
  sets that option's stations (the station pins) and ending, which re-plans it. A re-plan's
  answer lists only the pair asked for, so the first answer's list is kept for the same start
  and end; the order is the server's. A free-floating e-bike's option has no pick-up station id
  (the server offers one only as the plan's own start, the first answer's), so its pins would let
  the server plan the best option again: picked after another option, it is shown again from the
  first answer, kept with the list (`replaysFirst`, `replayFor`: the scheduler answers that one
  request from it, matching the plan sent with its stations, `sentPlanKey`), with "Option A:
  picking up at an e-bike outside a dock, as first planned." If the ride's settings changed since,
  it is not re-planned, and Go's notice says so (`stationlessUnavailable`).
- **Start and end pins** (the owner, 2026-10-11 21:29 UTC): a play triangle and a stop square
  (`lib/pointText.ts` `START_GLYPH`, `END_GLYPH`, hidden; the pins' names stay "Start", "End" and
  "Start and finish"), so A, B, C are only the offered places; stops keep their numbers.
- **My Go** (`lib/myGo.ts`; `core.models.MyGo`, migration 0019; GET/POST `/api/me/go`):
  Go's ride type and Home (`open_in` stays in the saved shape, unused). Signed in it is the account's (saved only
  after it has been read, so an early save never clears a Home), with a copy on the device
  (without Home) so the next visit has the ride type at once; signed out it is the
  device's. The POST needs the CSRF cookie the GET sets, a JSON body and a same-site
  request; Home must be in the coverage box and is rounded to 5 places; the row goes with the
  account and is deleted when the account is marked deleted; `my_go` never ships to the beta
  (`scripts/beta/ship-data.sh` `EXCLUDED_TABLE_DATA`). `tests/test_my_go.py`.
- **Favorite places** (`lib/favoritePlaces.ts`; `MyGo.places`, migrations 0049-0050; GET/POST
  `/api/me/places`; Stephen 2026-10-26): signed in, Go's Home chip is a Favorites chip whose
  popout lists Home (or Set Home), Work (or Set Work), then the rest; a tap rides there. Add a
  place and Set Work search; Edit shows Change Home and Remove. A held map spot and the ride
  summary offer Save to Favorites. The POST is the whole list (at most 20, one Work, each spot
  once, inside the coverage box, rounded to 5 places) with My Go's guards, saved apart from
  `/api/me/go` so neither save clears the other. The page saves nothing until it has read the
  list, and its saves go one at a time (`favoritesSaver`). Never on the device or in a log;
  deleted with the account's `my_go` row. Signed out, the Home chip is unchanged.
  `tests/test_favorite_places.py`.
- **Plan's panel**: the Points heading's row holds Swap (Reverse), Loop, Edit and Info (the
  how-to, the access switch and Install, which were More tips); the Ride line shows its
  summary as chips. The route: the totals and Info on one line, the stress bar, the Avoid
  notice as one line (`AvoidNotice`: the short line shown, the whole sentence read, Avoid it
  with its extra distance, Details) with the other warnings counted behind it
  (`lib/routeNotices.ts`), each note one line with an icon (full words in Info), then Start,
  GPX, Link and More (Share, Keep for offline) in one row, then one-line closed folds with
  their counts on the right (`Fold`'s `count` and `icon`): Elevation and climbs (with the
  climbs list), Stress and facilities (the four quick figures first), Directions, Junctions to
  watch, Other routes, Water and restrooms. Bikeshare's station lists are a "Choose a station"
  fold under Route.
- **Sheets** (`app/Sheets.tsx`, `lib/sidebar.ts` `PanelView`): the bar is Plan, Layers,
  Suggest, GPX and Settings. Layers holds the switches only, with a Legend button that opens
  the Legend sheet one step in; Suggest says how to suggest from the road panel and opens it
  at the map's center, with DC 311 and an admin's Review; Settings is My Go (Home, one line with
  Change, and Go's ride type), Riding (cues, rider and bike weight), Display (Accessibility mode, with High
  contrast and Large text during a ride indented under it, Screen-reader detail, Language) and Account, most used
  first, one row per setting; on a phone it takes the panel's whole height.
  Plan's map has Eat, Water and Places to see chips behind one Find chip (`PlanMapChips`),
  which open the Find food, Nearest and Places to see sheets. `openOnto`/`backFrom` keep the way back through nested sheets; Back returns the
  focus to what opened the sheet, and a sheet's heading takes it on the way in.
- **Road panel**: two or more ways to suggest (a road's level, a junction, a Mass Ride
  hazard) are one "Suggest a change…" disclosure; one is its own button, as before.
- **Ride mode**: the 311 button (`lib/ride311.ts`), 60 px round on the right edge at thumb
  height, only while the rider's place on the route is inside DC; it opens a menu with the
  place line and the six problems as large buttons, and a pick opens "Report a problem to DC
  311" with that problem chosen (the note, the text or DC 311 online and Copy as before). Large
  text (which replaced Big text, 2026-10-20) has the text-size icon; Where am I? (which re-centres
  too) and End ride have icons too.
- **Icons**: `lib/iconPaths.ts` (the mockup's own line icons, minus Work, plus cargo,
  text size, tree and bikeshare) drawn by `Icon.tsx` (or `lineIcon` in createElement
  modules), always `aria-hidden` beside words.

`lib/goPlan.test.ts` holds the pure parts and the wiring; `scripts/a11y/check.mjs` drives Go,
the switch, the sheets, My Go and the 311 menu in a browser.

### The sidebar (312)

OWNER-DECISIONS 312's layout, from mockup v3 (PLAN.md, FOLLOWUP-SIDEBAR-REDESIGN, has
what differs). Code: `App.tsx` places it (its parts in `app/`, above); `Sidebar.tsx` (QuickFigures,
BottomBar, SheetFrame); `lib/sidebarParts.ts` (RideSettings, Fold, JunctionLegend and
the two parts for open questions, written with createElement so a test renders them);
`lib/sidebar.ts` (the decisions, pure); `lib/rideSummary.ts`; `lib/quickFigures.ts`.
Tests: `lib/sidebar.test.ts`.

- **Views, not modals.** The panel body shows the planner or one of the bar's sheets
  (Map layers, which Legend opens at its legend; GPX; Settings); the bar's first button,
  Plan, is the way back (below). Each is in the page all
  the time, `hidden` when not shown, so the search, the opened GPX file, the slider
  drafts and the switches keep their state, and a GPX import keeps fitting while
  another view shows.
- **The focus** (`focusOnViewChange`, tested over every transition): a sheet takes it
  to its heading (the legend's, for Legend); Back or Escape returns it to the bar
  button that opened the sheet; the Plan button takes it to the planner's heading, the
  `h1` (cause `planButton`, `{ kind: "planner" }`; on the planner already, App focuses the
  heading and scrolls the panel to the top itself); an error that brings the planner back takes it to the
  error, the long-ride question to "Plan it". Escape is not the sheet's inside a
  dialog or on the place search's list (`sheetEscape`). When a route arrives and the
  points compact, a focus in the search or the point tools goes to
  "Edit points" (`rescueCompactFocus`), so it is never left in a hidden element.
- **Live regions.** The route's (`.status-line`) and the points' (`said`) are outside
  the panel, so a bar sheet or the phone's hidden sheet does not silence them; the
  planner's visible copy of the slow and waiting lines is `aria-hidden`, and "No route
  yet." is plain text read where it stands. The points notice is a status in the Points
  section, and is also said through `said` while the planner is hidden
  (`noticeSaidElsewhere`), never both at once. A Mass Ride loads the federal-land data
  whatever the shading switch says (`federalWanted`), for the planner's points list.
- **Scrolling.** `.panel-body` is a column: the status bar, the
  scrolling `.panel-scroll`, then the pinned route actions and bottom bar. On a short
  or zoomed screen (`@media (max-height: 32.5em), (max-width: 22.5em)`, 520 px and
  360 px at 16 px text) the whole `.panel` scrolls as one instead, so at 400% zoom of
  1280x800 (320x200) the 96 px phone sheet scrolls all of its content, where the
  pinned parts left the planner 0 px. (The beta notice is not in the panel: it is the
  "Beta" chip in the map's bottom-left corner, lib/betaBanner.ts.)
- **Copy link** copies `linkToCopy`: this page and `encodePlan(points, preset, dials)`,
  the fragment App writes to the address bar, which never holds the weight (313). Its
  "Link copied." is polite, said again on a second press, and cleared when the plan
  changes.
- **Share** (owner, 2026-10-10; `lib/share.ts`) sits right after Copy link, only where
  `canShareLink` finds `navigator.share` (and `canShare({ url })` says yes, where the
  browser has it); elsewhere it is not rendered and Copy link stays. It hands
  `navigator.share` the title "RouteMaker route", `shareText` ("4.7 mi (7.6 km) bike
  route. Ride type: Default.") and `linkToCopy`'s URL unchanged. Visible word "Share",
  accessible name "Share route", described by the location line (395) like Copy link.
  `shareLink` maps the result: the sheet opened says nothing (browsers do not report
  where the link went, so "Shared" could be untrue); AbortError (the rider closed the
  sheet) and InvalidStateError (a sheet already open) say nothing; any other failure
  goes to the same polite status and visible line as Copy link: "Could not open the
  share sheet. Use Copy link instead." A press while a sheet is open is skipped (a
  ref). `shareLink` calls `navigator.share` synchronously and `shareRoute` calls it
  before any await, so the press's user activation holds (a test pins both). The text
  leaves the distance out ("Bike route. Ride type: …") while a re-plan is pending, as
  the route shown is then not the points the link carries. The a11y check stubs
  `navigator.share` before the app starts (`open({ init })`), refusing a call without
  user activation or while one is open, as browsers do.
- **FacilityBreakdown's `part`**: "notices" (the traffic-tolerant warning, the roads
  best avoided, the hills search) stays in view; "figures" (the route colors and the
  bike facilities) goes in the Stress and facilities fold (`breakdownParts`).
- **The font (switched on, OWNER-DECISIONS 384).** `--font` names Atkinson Hyperlegible
  first, so an installed copy is used before the downloaded one. The self-hosted files
  are in `frontend/src/fonts/` (`atkinson-hyperlegible-regular.woff2` at 400,
  `atkinson-hyperlegible-bold.woff2` at 700, and `OFL.txt`, the SIL Open Font License;
  sha256 in docs/SOURCES.md), with relative `url()`s in `fonts/fonts.css`, which
  `main.tsx` imports after `./styles.css`. Vite fingerprints the files into `/assets/`
  (a build gives `/assets/atkinson-hyperlegible-regular-<hash>.woff2` and
  `...-bold-<hash>.woff2`, and the built CSS names only those): both edges already
  serve `/assets/` with a year's immutable cache and every publish path copies it, so
  no Caddy, nginx or deploy change is needed. The files are well over Vite's 4 KB
  inline limit, so they are never `data:` URIs (which `font-src 'self'` would refuse).
  The credit: the `licenceNotices` plugin (`src/licences/notices.mjs`, `BUNDLED_FONTS`,
  `withFontNotices`) appends "Atkinson Hyperlegible - 2020 (OFL-1.1)" and the full OFL
  text to the built `licenses.txt`, and fails the build if the licence file is missing;
  docs/SOURCES.md records it with no `Credit:` line: it is a bundled asset, credited in
  `licenses.txt` (which the map's "Software licences" link opens), not a data credit. The sidebar test fails if the import and the
  two files are not both there, or the licence is missing; `notices.test.mjs` checks
  that the credit and the licence text reach `licenses.txt`.
- **The map's label font (the owner, 2026-10-20).** Every map label is Atkinson Hyperlegible
  Next; the street names (`stressStyle.js`, `ROAD_LABEL`) are its SemiBold at 15 px. The
  neighbourhood and town names (`PLACE_LABEL`, the base map's `places_subplace` and
  `places_locality`; the owner, 2026-10-21) are its ExtraBold on a 2.5 px white halo: a
  neighbourhood in capitals, 11-14 px; a town in mixed case, 13-17 px; a large town
  (population_rank 9 or more) 15-17 px, so a town reads above a neighbourhood, a neighbourhood
  apart from a street, and both stay under the station names. The base map's other labels
  (`OTHER_LABEL`: park and place names, water, islands, house numbers, route shields) and the
  app's own names (mountain-bike trails, scenic spots, waypoints, route choices at 15 px; mile
  markers and contour heights at 12-13 px) are SemiBold on a white halo too, in dark shades of
  their colours (7:1 or more); counts inside icons (climbs, docks, Review badges) keep their
  sizes. In a city grid (a feature the tiles mark `dense`: its 1 km square of EPSG:3857 holds
  8 km or more of drawn road, `core.stress_tiles.DENSE_RULE`, tile format 12; unmarked, as a
  rural road or an older tile, it is always drawn) the map climbs a bike ladder (`CITY_LADDER`,
  the owner 2026-10-23: "Kind of like how you'd see interstate highways at highest zoom, then
  arterial roads ... For bikes, we want something similar"): from z12 paths, protected lanes,
  popular class 2-3 corridors, long calm streets and named trails; from z13 painted lanes and
  class 1; from z14 every
  other street and sidewalk, so a city grid is a mesh, not a carpet. An on- or off-ramp (tile
  `link`, `segment.road_link`) waits for z14 in a city grid or not, unless it is on the
  ladder (the owner 2026-10-23: "the various onramps and offramps aren't needed at this
  level"). The tile `overview` (`segment.overview`, `pipeline.bike_network`, after `tidy` in
  the rebuild) shapes z12-13 in a city grid or not: 1 a short street or crossing (one or two
  ways, 650 ft (200 m) or less) between two bike facilities, or an LTS 1-2 way of 1,300 ft
  (400 m) or less joining a bit of the network under half a mile (800 m) to the rest; 4 the
  calmest way (cost by LTS: 1, 1.15, 2, 4 times its length; no sidewalks) from a z11 piece to
  its nearest other piece within a cost of 800 m (half a mile), or 3 km (1.9 mi) between two
  pieces of a mile or more, plus every off-road path in a joined piece of a mile or more (the
  owner: "make connections across from the MBT to Rock Creek trail ... Include the minor
  trails"); both draw from z12, busy or not (a ramp still waits for z14), and 4 also zoomed out with the long trails, from z7 (`popular_and_calm`). The joins found in every box are taken shortest first (Kruskal) and kept only where the pieces they join reach a mile; the search for them passes through smaller pieces and uses a 0.04-degree margin. A run of ways of LTS 3 or more, 820 ft (250 m) or less in all and running straight on (within 30 degrees), is a join too (`overview` 1) when it leaves a drawn way going on in the same direction and comes to another, or to a drawn street it meets in a T (no road going on straight); a drawn way's end up to 80 ft (25 m) on along the run counts as met (an offset junction). So a calm street does not break at a busy block or two. A join inside a bit that joins nothing becomes an orphan with it. 2 a bit of
  the network under 800 m that could not be joined ("If it doesn't connect to anything, don't
  include it") and 3 a dead end of 800 m or less off it, sidewalks not counted ("all these
  cul-de-sacs") wait for z14; 3 only where the ladder would not draw the way anyway. Zoomed out,
  `segment.stray_zoom` (10 or 11, `bike_network.mark_strays`) leaves out of the z10 or z11 tiles
  a piece of what they draw under a mile long ("These bits too"). The graph is worked in
  0.05-degree boxes with a 0.02-degree margin, cut at shared vertices. Lanes,
  paths, trails and unpaved roads keep their widths (the owner, 2026-10-21). MapLibre
  draws text from glyph files, not web fonts, and the style has one glyph URL template (the
  base map's `/basemap/fonts/`), so the three Latin ranges (`corridor.ts` `GLYPH_RANGES`) of
  Regular, SemiBold, ExtraBold and Italic are made once with `scripts/make_map_glyphs.mjs` and bundled in
  `frontend/src/fonts/map-glyphs/` (sha256 in docs/SOURCES.md). Each file is the font's glyphs
  with the base map's matching Noto Sans face filling the code points the font lacks, since
  MapLibre draws nothing for a code point missing from a range it has. Vite serves them as
  hashed `/assets/*.pbf` files (no edge change) and the service worker precaches them (about
  1.1 MB uncompressed, 640 KB gzipped). The layers keep naming the base map's faces; the
  `transformRequest` of both the app's map (`MapView.tsx`) and the share card's
  (`app/shareCardRender.ts`), `lib/mapGlyphAssets.ts` `mapGlyphRequest`,
  sends a request for Noto Sans Regular, Medium or Italic (or the street names' face) to its
  Atkinson file through `lib/mapGlyphs.ts` `glyphRequestUrl`, and leaves other ranges to the
  base map. A kept ride's prefetch skips the bundled faces. The licence is the second
  `BUNDLED_FONTS` entry, in `licenses.txt`.
- **The Plan button (OWNER-DECISIONS 392, 393).** The bar is Plan, Map layers, Legend, GPX,
  Settings (`BAR_ITEMS`; Plan is `id: "plan"`, `opens: "planner"`, so `barCurrent` marks it
  `aria-current` while the planner shows and no other button then). It returns from any
  sheet; on the planner it focuses the heading and scrolls to the top. The focus differs on
  purpose (the reading of 392): Plan goes to the planner as a whole, so to its `h1`; Back and
  Escape undo the opening of a sheet, so they return to the bar button that opened it. The
  hint of each bar button is a sibling `hidden` span (`aria-describedby`), so a
  button's name is its label alone. The phone header's toggle reads "Hide planner" / "Show
  planner" (`aria-expanded`, `aria-controls`), and Show always shows the planner and leaves the focus on the toggle (cause `panelToggle`). The sheets' Back button reads "Back to planner"
  in visible words (`BACK_LABEL`, no `aria-label`, so its name is its label); it and Escape
  still return the focus to the bar button that opened the sheet. There is no title link.
  The bar is a grid of tracks at least 3.5rem wide (five across at 320 px, a second row
  under large text); at 720 px and below each button is the icon over its words, which wrap
  ("Map layers" on two lines), 48 px high, with 44 px targets; the Back button is 44 px high
  and the sheet header wraps.
- **Settings, High contrast (OWNER-DECISIONS 384).** Settings is a bar button
  (`BAR_ITEMS`, id `settings`; it was About; since 392/393 it is the fifth of five, Plan first): its sheet holds a "Display" group with the
  High contrast switch, then a "Signing in" section with the sign-in note. No other settings are listed. The switch
  is the former Accessibility switch, renamed in words only: `AccessibilitySwitch`, the
  `routemaker.accessibility` storage key, the `a11y` root class and the `palette=` link
  value (`cool` and the older `cvd`) are unchanged, so existing share links decode the
  same. Its hint is "Bolder lines, stronger borders and text, and colors that don't rely on
  red and green." (no disability word). It is one state (`stressStyle.js`) shown twice, in Map
  layers (ids `a11y-switch`, `a11y-label`, `a11y-hint`) and in Settings (ids
  `settings-contrast-*`, from the component's `idBase`), because both sheets are in the
  page at once. `barCurrent` (`lib/sidebar.ts`) decides which bar button is current.
- **Decided, ready to change.** The theme follows the system's light or dark setting
  (384: "system"). `PLANNER_EXTRAS` holds two parts built and decided off (384): the
  planner's zoom notice (`PlannerZoomNotice`, a live region of its own, which only speaks
  while the planner shows; the notice lives in the Map layers sheet) and the planner's
  High contrast shortcut (`HighContrastShortcut`, described by the switch's hint and its
  from-link note, with no ids the switch uses).
- **The browser check** (scripts/a11y/check.mjs, 280 checks with the route chart, section 17 for the loop box
  and the Plan button, section 18 for Use my location, and section 20 for the Mass Ride capacity map: its
  legend, bands by zoom and their status line, the DC-only words and mask, the outside-DC notice, both
  narrowest figures, the outside-DC words, and a table without the capacity column keeping the stress map; 325-327, 387, 417,
  417a, 418, 418a, 421, 422, 424, 427) opens the Ride settings and the "Junctions to watch" fold on every page it
  checks, and the Map layers sheet or the Directions fold where a section needs them.
  A closed fold's rows cannot take the focus, as for a rider, so a check that focuses
  a junction row must open the fold first.

### Use my location (OWNER-DECISIONS 395)

Front end only; the server-side log changes the review found (beta nginx, Valhalla's `long_request`) were on
their own branch, wip/privacy-logs (OWNER-DECISIONS 401), which the rebuild bundle has merged; there the
fifth (off-road) router carries the same `long_request` (31fd734). (Later found to be read by no
Valhalla release, and dropped in the 3.9.1 upgrade: see "Logs and the rider's position".) A "Use my location" button sits beside the search box (`.place-search-row`, in
`PlaceSearch.tsx`, 44 px each way), and "Your location" leads the search's list while the box is
empty or starts to say "your/my/current location" (`locationMatches`). Enter with nothing highlighted
never takes it (`pickTarget` in `lib/geocode.ts`: a look-up asks the browser's permission); an arrow
key and Enter, or a click, does. Its second line says what it will do ("Sets the start.", "Adds it as
a stop.", `hereEffectLine`), and the spoken result count includes it ("3 places found, plus Your location.").

- **The look-up** is `lib/geolocation.ts`, behind `GeoEnv` (`isSecureContext` and a `getCurrentPosition`
  that tests stub; `browserEnv()` is the only reader of `window`). One `getCurrentPosition` per press, with
  `enableHighAccuracy`, a 10 s timeout and a 30 s `maximumAge`; after a browser timeout, one more try
  without high accuracy (`RETRY_OPTIONS`), in the same press. No `watchPosition`, no tracking. Each call
  settles once, and an app-side watchdog (`LOCATE_WATCHDOG_MS`, timeout + 20 s) ends a look-up the browser
  never answers (a dismissed or ignored prompt, which the browser's own timeout does not cover) as a
  timeout, with no retry. Where the browser has the Permissions API (`GeoEnv.permission`), a prompt still
  open gets `PROMPT_WATCHDOG_MS` (60 s) instead, and the first watchdog starts again when it is answered,
  so a rider who reads the prompt for a while and then grants it is not cut off by a cold GPS; the
  query never delays the call. `locate` never rejects: every outcome is a `LocateResult` (`denied`,
  `unavailable`, `timeout`, `unsupported`, `insecure`), each with a plain sentence in `LOCATE_MESSAGES`.
  `locateGate` keeps it to one look-up at a time; a press while one runs says "Finding your location..." again.
- **The result** is decided by `placeFix` (pure, unit-tested; `App.tsx` only calls it), with the loop
  flag read after the wait. From the button it goes in by the map click's path (`addPoint`, loop-aware,
  one undo step): the start of an empty plan, else the next point. From the "Your location" choice it
  follows the search's Start / Destination / Stop choice, as a picked place does (`applyPlace`). It is
  announced once through the app region ("Start set to your location, accurate to about 50 ft (15 m).",
  US units first, rounded to a friendly figure by `formatRadius`; over about 330 ft (100 m) it adds
  "That is rough; search for the exact place if you can."), after "Finding your location..." (also said
  through that region, shown beside the button as plain text and its description while busy). The hint
  says it is approximate: "Drag its marker, or search for the exact place, to adjust it." The map flies
  there and draws an accuracy circle (`MapView.tsx`, `location-accuracy` source, under the route) while
  the point is in the plan.
- **Failures** are the Points notice (a `role="status"` line that is always rendered, empty when there is
  no notice, so screen readers speak a new message; said through the app region only while the planner
  is hidden, as the other notices). Outside coverage says "Your location is outside the area this map
  covers (the DC region to Baltimore)."; "25 points" reuses the click's text. The notice is cleared and
  set again 150 ms later, so a second press with the same answer is said again; a map edit in that window
  cancels it. On an insecure page or without geolocation the button stays in the Tab order,
  `aria-disabled`, with the reason as its description and in plain text beside it.
- **Privacy.** Links and GPX keep full precision (the feature is for navigating on the go), so the point
  itself is in the link, the address bar and GPX like any clicked point, by design. What is never in the
  link, GPX, storage or a log is the flag that a point came from the location (`fromHere`) and the fix's
  accuracy (`here`): React state only (a test reads the sources for that, and that they reach only the
  note, the hint and the circle). Copy link shows one line, "This link includes your location as the
  start." (`linkLocationNote`; "as a point on the route" when only a later point came from the location),
  decided by point object identity. The button (and Share, where shown, so it is read before the share
  sheet opens) is described by it, and a Copy link press says it with the
  confirmation ("Link copied. This link includes your location as the start."). A drag of a point that
  came from the location keeps the note (`movedFromHere`: the moved point is still the rider's spot); an
  undo that brings a point back restores it.
  - The address bar holds the location as soon as it is in the plan (the plan's hash, as for any point),
    so the browser's own share or copy of the address, and its history, carry it with no note.
  - A reload, back or forward, or the sign-in round trip loses the note (the flag is memory only), while
    the link still holds the location.
  - The sign-in round trip (`lib/signIn.ts`) keeps the plan's hash, location and all, in this tab's
    sessionStorage only for the round trip; it is read once and removed on the next load, and nothing is
    sent to the server. This is the accepted exception to "never stored" (OWNER-DECISIONS 398, "yes, keep
    location"): `SKIP_SIGN_IN_PLAN_WITH_LOCATION` stays false. Flipping it would also need the Settings
    sheet's sign-in sentence and two test pins changed (the comment at the switch).
  - Server logs are not this branch's: with wip/privacy-logs (PLAN 401), which merges first, the location
    in a reverse look-up's or a search's query stays out of the beta nginx logs. (Valhalla turned out to have no
    slow-request log to switch off; see "Logs and the rider's position".) Tile paths in the nginx and gunicorn logs (`/tiles/stress/{z}/{x}/{y}.pbf`) do show the area
    viewed, as any map pan does.
- **Testing on a phone:** the local stack by LAN IP (`http://192.168.x.x`) is not a secure context, so the
  button is disabled there. Test on the beta, or over `localhost` (`adb reverse`, or a tunnel with TLS).
- **Tests:** `lib/geolocation.test.ts` (look-up, watchdog, retry, `placeFix`, gate, note rules, the
  never-stored source scan over all of App, the real watchdog limits and the open prompt under
  `mock.timers`, and source pins on App's and PlaceSearch's handoffs: the ride read after the wait, the
  list's choice, Enter through `pickTarget`, the drag's captured point), `planEdits.test.ts` (undo gives back the same point objects; a drag makes a
  new one); the browser check (section 18) uses CDP's `Emulation.setGeolocationOverride` and
  `Browser.setPermission` (granted, denied, no position) and a script that makes `isSecureContext`
  false. A timeout is covered by the unit tests only (CDP cannot make one).

### Groups at stops and in full detail (items 247, 248)

See "Mass Ride: groups of signalized crossings" above. The copy: "6 crossings with
traffic signals", "1 of them a heavy-traffic road (LTS 4)", "2 of them heavy-traffic
roads (LTS 4)", "all of them heavy-traffic roads (LTS 4)".

An LTS 3 stretch merged into an LTS 4 overview entry is worded at LTS 4 (item 249,
the spec re-check's note): the overview words a merged entry at its most stressful
tier, which overstates and never understates.

### LTS 4 on the stress-averse rides (item 250)

`presets.Exposure` (a preset field): Trailmaxxing and Cargo with passengers weigh LTS
3, LTS 4 and Avoid at 1, 8 and 16 in the search's exposure and hold LTS 4
(`refine.more_lts4`: never more LTS 4 and Avoid metres than the router's first route,
whole trip and each leg, 1 m of slack); every other ride keeps 1, 2, 3 and no hold.

Measured on the twelve trail-seek trips (scratchpad configs ts/ and ts2/), Trailmaxxing
at 100, weekend, through the read-only forwarder on the live routers (graph
20260927). "Router's own" is the plan with the search skipped, which is what live
(0ec8fdc, no calm search) answers. Miles of LTS 4 (and Avoid) / LTS 3, miles of
trail (path and protected), total miles and minutes:

| Trip | Router's own (live behaviour) | 2b0cf00 | FINAL-FIX |
|---|---|---|---|
| rockville-silver-spring | 0.76 LTS 4 / 1.22 LTS 3, 3.8 trail, 10.9 mi, 65 min | 0.21 LTS 4 / 0.01 LTS 3, 4.8 trail, 14.3 mi, 78 min | 0.21 LTS 4 / 1.06 LTS 3, 5.0 trail, 13.5 mi, 73 min |
| bethesda-capitol | 0.74 LTS 4 / 0.12 LTS 3, 9.9 trail, 12.2 mi, 69 min | 0.69 LTS 4 / 0.12 LTS 3, 9.9 trail, 12.4 mi, 70 min | 0.69 LTS 4 / 0.12 LTS 3, 9.9 trail, 12.4 mi, 70 min |
| falls-church-union-station | 0.19 LTS 4 / 1.17 LTS 3, 8.5 trail, 10.5 mi, 56 min | 0.19 LTS 4 / 1.17 LTS 3, 8.5 trail, 10.5 mi, 56 min | 0.19 LTS 4 / 1.17 LTS 3, 8.5 trail, 10.5 mi, 56 min |
| silver-spring-college-park | 1.09 LTS 4 / 1.37 LTS 3, 1.1 trail, 7.0 mi, 37 min | 0.09 LTS 4 / 0.70 LTS 3, 8.0 trail, 11.1 mi, 60 min | 0.26 LTS 4 / 0.48 LTS 3, 3.7 trail, 8.7 mi, 46 min |
| bethesda-silver-spring | 0.74 LTS 4 / 0.08 LTS 3, 0.3 trail, 4.7 mi, 26 min | 0.74 LTS 4 / 0.08 LTS 3, 0.3 trail, 4.7 mi, 26 min | 0.74 LTS 4 / 0.08 LTS 3, 0.3 trail, 4.7 mi, 26 min |
| laurel-college-park | 3.07 LTS 4 / 1.81 LTS 3, 7.0 trail, 13.8 mi, 71 min | 1.26 LTS 4 / 3.38 LTS 3, 9.8 trail, 16.9 mi, 87 min | 1.26 LTS 4 / 3.38 LTS 3, 9.8 trail, 16.9 mi, 87 min |
| poolesville-darnestown | 4.87 LTS 4 / 1.43 LTS 3, 0.0 trail, 9.7 mi, 51 min | 4.87 LTS 4 / 1.43 LTS 3, 0.0 trail, 9.7 mi, 51 min | 4.87 LTS 4 / 1.43 LTS 3, 0.0 trail, 9.7 mi, 51 min |
| bowie-annapolis | 11.93 LTS 4 / 1.48 LTS 3, 1.8 trail, 21.2 mi, 105 min | 11.93 LTS 4 / 1.40 LTS 3, 2.6 trail, 21.9 mi, 108 min | 11.93 LTS 4 / 1.40 LTS 3, 2.6 trail, 21.9 mi, 108 min |
| tysons-ballston-wod | 0.44 LTS 4 / 0.97 LTS 3, 7.3 trail, 9.2 mi, 47 min | 0.40 LTS 4 / 0.58 LTS 3, 7.8 trail, 10.0 mi, 52 min | 0.40 LTS 4 / 0.58 LTS 3, 7.8 trail, 10.0 mi, 52 min |
| eastern-market-pg-plaza-anacostia | 1.33 LTS 4 / 3.33 LTS 3, 2.6 trail, 7.9 mi, 43 min | 0.25 LTS 4 / 0.20 LTS 3, 4.1 trail, 8.8 mi, 51 min | 0.25 LTS 4 / 0.20 LTS 3, 4.1 trail, 8.8 mi, 51 min |
| friendship-heights-rosslyn-cct | 0.01 LTS 4 / 1.78 LTS 3, 1.3 trail, 5.3 mi, 31 min | 0.01 LTS 4 / 1.78 LTS 3, 1.3 trail, 5.3 mi, 31 min | 0.01 LTS 4 / 1.78 LTS 3, 1.3 trail, 5.3 mi, 31 min |
| takoma-hyattsville-sligo | 1.49 LTS 4 / 1.11 LTS 3, 0.6 trail, 3.5 mi, 18 min | 0.00 LTS 4 / 0.63 LTS 3, 3.4 trail, 4.8 mi, 25 min | 0.00 LTS 4 / 0.63 LTS 3, 3.4 trail, 4.8 mi, 25 min |
| Total | 26.68 LTS 4, 44.0 trail, 116.0 mi, 618 min | 20.63 LTS 4, 60.5 trail, 130.4 mi, 694 min | 20.80 LTS 4, 56.4 trail, 127.2 mi, 675 min |

The router's own Trailmaxxing route uses LTS 4 where a calmer route of modest extra
length exists (Takoma to Hyattsville, Eastern Market to Anacostia, Silver Spring to
College Park, Rockville to Silver Spring, Laurel to College Park), so the live
behaviour the owner saw is the router's route alone; both searches find those. On no
trip did either search end with more LTS 4 than the router's route. With the new
weights the hold refused both seek candidates on Bethesda to Silver Spring. On Silver
Spring to College Park the new search ends at 0.26 mi of LTS 4 where 2b0cf00 ended at
0.09: its exclusion rounds stopped after three (two rounds in a row did not improve
the score at the new weights), before the round 2b0cf00 found its route in; still a
quarter of the router's 1.09 mi.

### LTS 2 on Trailmaxxing and Cargo with passengers (FOLLOWUP-LTS2-WEIGHT, items 240 (A), 241)

The owner, 2026-10-03, item 240: "A and B sound good." (A): "a small LTS 2 weight in the
calm-search score, about a quarter of LTS 3, on"
"Cargo-carrying-people and at the top of the slider (Trailmaxxing). Planner only; no rebuild."
Item 241's rationale applies: a rider who
is not in control of the ride is stress-averse.

- `presets.Exposure.lts2` (0 by default) and `presets.LTS2_WEIGHT` (0.25).
  `presets.EXPOSURE_NOT_IN_CONTROL` is item 250's 1 / 8 / 16 with the hold, plus LTS 2 at
  0.25; Trailmaxxing and Cargo with passengers use it. Carrying cargo, Default at 100 and
  every other ride keep LTS 2 at nothing. Bikeshare keeps item 250's weights without the
  LTS 2 weight, since 240 (A) does not name it.
- Below the top of the slider the weight is in the score: `Analysis.exposure_m` (the
  weights dict now has a `"2"` key) is priced at the calm rate, so a metre of LTS 2 costs a
  quarter of what a metre of LTS 3 does. The Traffic-wins allowance and the seek's guards
  weigh it the same way.
- At 80 and below, where the calm rate is 0, the exposure is not priced, so on its own the
  weight would never price a route where Cargo with passengers starts (review, blocking).
  There the score adds a separate LTS 2 term instead: LTS 2 metres x the ride's weight x
  what a metre of LTS 3 adds to the router's own cost at the request's `use_roads`, in
  quiet metres (`refine.lts3_added_m`: the graded-stress model's middle LTS 3 figure,
  `calm.added_cost`, over `QUIET_COST_FACTOR`; about 4 at 80). So at 80 a metre of LTS 2
  costs about 1 quiet metre more, a quarter of LTS 3's added cost, as 240 (A) asks. The
  slider does not move, the calm search does not turn on, and the router's requests are
  unchanged: only the choice among the routes it returns (the crossing rounds') changes.
  Default, Bikeshare and carrying cargo weigh LTS 2 at 0, so their scores are unchanged.
  The term follows the ride, not the preset's start: Trailmaxxing (0.25) and Riding with
  kids (0.5) get it too when the rider moves their slider down to 80 or below. It fades
  with LTS 3's added cost toward the slider's busiest end, where `use_roads` is 1 and LTS 3
  adds nothing.
  If the owner prefers the weight to wait until the rider moves the slider above 80, the
  term is one commit to drop.
- At the top (100, maxcalm) the weight is in the second figure of the ranking:
  `Analysis.second_m` is LTS 3 + orange junctions + 0.25 x LTS 2, so between two routes
  with the same LTS 4 and red junctions, 656 ft (200 m) more LTS 2 is worth one 164 ft
  (50 m) tie step. The worth rule counts the same figure (`stress_weight_m`, `_second_weight_m`), so
  1 mi (1.6 km) of LTS 2 saved can buy 1.25 mi (2 km) of extra riding with no target, a
  quarter of what a mile of LTS 3 buys. LTS 4 still ranks first whatever the LTS 2.
- LTS 2 never starts a search of its own, so it adds no router calls: `calm_targets` still
  excludes only LTS 3 and worse, and the trail seek is handed the busy spans of LTS 3 and
  worse only (`refine.seek_weights`), so a stretch of LTS 2 never starts a seek. The routing
  graph does not grade LTS 2 (240 (C) stays with
  FOLLOWUP-DECIMAL-STRESS in the backlog), so nothing is rebuilt.
- The rolling stress chart is unchanged: it shows traffic stress, not the ranking's LTS 2
  preference, so LTS 2 is priced by the road's own cost alone and an all-quiet route still
  reads about 1 (461d) on these rides too.
- Not measured on the live routers in this change (no router here). The 12 trips and the
  owner's route are the place to measure it, as item 250 was.
- Tests: `tests/test_refine.py::TestLts2Weight`, `tests/test_calm.py`; mutants `240A: ...` in
  `scripts/mutants_trailseek.py`.

### Riding with kids (FOLLOWUP-KIDS-PRESET, item 240 (B))

The owner, 2026-10-03, item 240 (B): "a 'Riding with kids' preset for children on their own
bikes. LTS 1 strongly preferred, LTS 2 allowed but costly, LTS 3+ avoided hard, slower
planning speeds and gentler hills. It builds on (A)."

The ride type id is `kids` (links `/#preset=kids`, the short path `/kids`), the label
"Riding with kids". It is defined like every other preset: `core.presets` (`KIDS`,
`EXPOSURE_KIDS`, the `_preset("kids", ...)` row, `BRAKE_GRADES`), `frontend/src/lib/presets.ts`
(the card's label and sentence), `frontend/src/lib/dials.ts` (`STARTS`, held equal to the API by
`tests/test_presets.py`), the Caddyfile and the beta nginx template's preset redirects, and the
stress page's cost table.

**Developer defaults, for the owner to confirm.** The owner gave no numbers for these:

| What | Default | Why |
|---|---|---|
| Traffic slider start | 100 (the top) | "LTS 3+ avoided hard": the least stressful route, LTS 4, Avoid and red junctions ranked first, with the LTS 4 hold, as Trailmaxxing |
| LTS 2 weight | 0.5 of LTS 3 (`KIDS_LTS2_WEIGHT`) | "LTS 2 allowed but costly": twice 240 (A)'s quarter; a metre of LTS 3 still counts two of LTS 2 |
| Planning speed | 6.2 mph (10 km/h) | a child of about six to ten on their own bike; Hybrid's own is 11.2 mph (18 km/h), Cargo Bike 8.7 mph (14 km/h), Mass Ride 6 mph (9.7 km/h) |
| Hills slider start | -80 (`use_hills` 0.2) | "gentler hills": more hill-averse than Cargo Bike (-60), short of Mass Ride (-95) |
| Descent that costs | over 3% | a child brakes with small hands; Cargo Bike's figure |
| Living streets | 1.0 (fully preferred) | as Trailmaxxing |
| Bicycle type, gates, surface | Hybrid; Valhalla's 30 s a gate; surface 0.25 | as Default |
| Turn penalty | Default's 5 s (Valhalla's own) | item 254 suggests a higher one for groups and young riders; that is FOLLOWUP-TURN-LOAD's to decide |
| Long trips | no calm search past 19 mi (30 km) of straight line (`refine.REFINE_MAX_SPAN_M`) | as every ride but Trailmaxxing, which plans those leg by leg (`long_calm`); a ride with children that long is rare |

At the top of the slider the ceiling is Default's: 1.6 times the router's own route, and at
least 1 mi (1.6 km) more, or 1.25 times the rider's target distance where one is set. It is
not planned leg by leg (`long_calm` stays Trailmaxxing's alone). The rider and bike weight
keeps the model's 198 lb (90 kg) default; a child's lighter total is the rider's to set.

**No rebuild.** It rides the existing graphs: the standard graph and its weekend twin, or
the no-trail graph with "Keep to roads, not trails". No new Valhalla graph or variant was
needed, because everything that makes it a kids' ride is a per-request costing option or
the planner's search; LTS 2 is graded only in the search, not in the graph (240 (C),
FOLLOWUP-DECIMAL-STRESS, backlog). Bike access is the graph's as for every ride: a way
whose bicycle access is unclear stays closed.

**Load.** Like Trailmaxxing it starts at 100, so every plan runs the calm search (about 20
router calls; docs/OPERATIONS.md).

**Screen readers.** The card is a toggle button in the ride-type dialog named by its label
and sentence; choosing it moves the sliders (their values are said in words), the Ride
line's spoken summary says "Riding with kids, calmest, avoids hills", and the link carries
it. `scripts/a11y/check.mjs` section 25 covers the dialog, the keyboard, the request, the
sliders, the target distance, a shared link and 320 px (`EXPECTED` 423); the mocked answer
is `S_KIDS` in `scripts/a11y/cdp.mjs`.

Tests: `tests/test_presets.py::TestRidingWithKids` and the tables there,
`tests/test_refine.py`, `tests/test_route_description.py`, `tests/test_preset_links.py`,
`tests/test_beta_overlay.py`, every test parametrised over the presets, and
`frontend/src/lib/presets.test.ts`, `dials.test.ts`, `dialsPanel.test.ts`, `stressPage.test.ts`.

## The ride layer and surface-unknown paths (OWNER-DECISIONS 376, 391, 402a, 403)

What shipped, and where to look. The server side and the measurements are in
docs/OPERATIONS.md, "The ride layer (z12-13)".

- **Pipeline.** `pipeline.schema` holds the constants (`RIDE_PATH_RUN_MI`,
  `RIDE_ROAD_RUN_MI`, `CALM_ROAD_MAX_TIER`, `CALM_PATH_GAP_M`; 403's `ROADSIDE_M`,
  `ROADSIDE_FRACTION`, `ROADSIDE_SAMPLE_M`),
  `ride_layer_predicate` and the partial index; `pipeline.trail_routes` holds
  `is_calm_candidate`, the two derive UPDATEs (`derive_calm_runs`) and the VALIDATE_SEGMENTS
  summary (`calm_run_summary`); `pipeline.run.assert_calm_runs` is the check, and the
  tests' autouse fixture (`tests/conftest.py`) blanks its sentinels and floors as it does the
  long trails'. `routemaker.stress.inferred_unpaved` is 376 C.
- **Tests.** `tests/test_trail_routes.py` (candidates, runs, VALIDATE_SEGMENTS), `tests/test_stress.py`
  (the track rule), `tests/test_stress_tiles.py` (`TestRideLayer`, which adds the column back:
  every other test of that file runs on a table without it, the fallback, so they hold
  today's z12-13 and each is one `DROP COLUMN` from the new one), and the front end's
  `stressStyle.test.mjs`, `stressPatterns.test.ts`, `stressLegend.test.ts` and
  `format.test.ts`. The `STRESS_ZOOMS` parity test reads `ride` and `quiet`; the legend's
  `RIDE_RUN_MI` is held equal to the schema's constants.
- **Style.** `stressStyle.js` has `unknownSurfaceLayers` (two layers,
  `stress-unknown-casing` and `stress-unknown`, drawn after the casings and before the
  tier lines; `setStressPalette` repaints them, and their edge's dash with them, since the
  dash is in the edge's own width, which the High contrast switch changes). LTS 1's
  `stress-1`, `stress-casing-1` and the path rails leave a feature with `trail` true and
  no `unpaved` to them. The dashes are the cue that is not colour; the legend row says
  so in words.
- **Calm roads (402, 402a).** `pipeline.calm_roads` is the road half of the calm runs:
  `_JUNCTIONS` (SQL) lists, for each named LTS 1-2 candidate row, its ends and every
  vertex it shares with another candidate or with a road at LTS 3 or above, with the
  distance along the row and the bearings either side; `runs_of` (pure Python, a
  union-find over the pieces between junctions, `pairs` deciding which ends go on into
  which) gives each row the longest run it is in. `derive` reads the junctions through a
  server-side cursor and writes the runs with one `UPDATE ... FROM unnest`. The pure part
  is tested without a database (`tests/test_trail_routes.py`: `turn_deg`, `pairs`,
  `runs_of`); the derive on shared vertices built in metres (`road`, `busy`), so two roads
  given one point share it exactly as OSM ways share a node.
- **Trails beside a road (403).** `routemaker.facility.roadside_by_tags` and
  `roadside_start` (what the writer stores before the geometry: True, False or None),
  `pipeline.trail_routes.derive_roadside` (the geometry, in SQL, on the rows left None),
  the `roadside` column and tile property (`core.stress_tiles.OPTIONAL_PROPERTIES`, ETag
  `e`), and the front end's `surfaceUnknown` filter in `stressStyle.js`, which leaves a
  feature with `roadside` true to the paved path's layers. `tests/test_stress_tiles.py`
  drops the column in its fixture (a table from before it) and `TestRoadside` adds it.
- **Measuring.** The figures in docs/OPERATIONS.md were taken on a private copy of the live
  table (read-only `COPY` out of the live database, never a write to it), with names from
  the source extract read by osmium and the old and new derives run on the copy.
- **Not done here:** decision 390 (solid LTS 3 and 4 below zoom 14), which is its own
  change; on a table with `calm_run_m` it is moot at z12-13.

## Long calm trips, the target distance and the routes to choose from (FOLLOWUP-LONG-CALM, items 256 to 271)

The owner's words are in PLAN.md, Owner amendments, "FOLLOWUP-LONG-CALM"; this is how it is built
and what it measured. Planner-only: no rebuild, no new graph.

### The motivating case

Union Station to Baltimore Penn Station at Trailmaxxing 100. Before this round the calm search
was skipped on it (`limited: "span"`, `REFINE_MAX_SPAN_M` 19 mi (30 km) of straight line), so the
router alone answered: 57.7 mi, 0.3 mi of LTS 4 and 7.2 mi of LTS 3. Cut into four legs by hand
it gave 58.0 mi, 0.24 mi and 7.2 mi, which is the router again, leg by leg, with no search.

### What changed, in the order the owner asked

**1. No span cap for Trailmaxxing (`refine.refine_long`, `core.legsplit`).**
- A Trailmaxxing plan at the top of the slider (`Preset.long_calm`, `routing.long_calm_for`) past
  19 mi (30 km) of straight line, and under the confirm span (93 mi, 150 km), is a *long calm plan*.
  The router's own route for the whole trip is asked for first, as before, and traced for its
  stress alone (no junctions).
- It is cut into legs of about 7.5 mi (12 km) of straight line (`legsplit.LEG_TARGET_SPAN_M`), at
  points on that route: the middle of a traced edge, at least 400 yd (500 m) from any LTS 3, 4 or
  Avoid stretch where there is such a place within a quarter leg of the even split, otherwise the
  place with the most room (the search keeps its exclusions 500 m from a leg's ends, so a cut in the
  middle of a busy stretch would put that stretch out of its reach). Each plan leg (the stretch
  between the rider's own points) is cut on its own.
- Each leg's own route is asked for (a short /route, 0.5 s warm) and traced. The legs with LTS 3, 4
  or Avoid are searched one at a time, the worst first (LTS 4 and Avoid, then LTS 3), each with its
  share of the time that is left by its weight (8 x LTS 4 and Avoid metres + LTS 3 metres), 70% of
  it to the exclusion rounds and 30% to the trail seek. A leg whose share is under 6 s is not
  searched and keeps the router's route. Legs with no busy road are not searched at all.
- The legs go back together as one trip (`refine._joined`; the plan's own legs are put back in the
  answer: `leg_ends`, `stops_m` and the description's runs are the plan's, not the internal legs').
  The whole route's junctions are read once at the end. If what is put together is not as calm as
  the router's own route (LTS 4 and Avoid, then LTS 3, by the tolerances below) or nothing
  changed, the router's own route is answered (`calm_search.long.answered`: `legs` or `router`).
- **Time.** The plan has the long ride's budget, 50 s in all (`LONG_PLAN_BUDGET_S`, 47 s for the
  router and its traces once the 3 s answer reserve is taken), under gunicorn's 60 s timeout: the
  owner's own figure for a long ride (2026-09-26), kept rather than a new one. An ordinary plan
  keeps 40 s. Inside it, the legs' time is scaled to the trip: the legs are read first (about 1 to 2
  s a leg), the last 6 s are kept for the answer's own traces and the whole route's junctions, and
  the rest is shared by weight. A leg stops at its share; a trip with more legs gives each less.
  Measured on an idle host (before 267-271), Union Station to Penn plans in 16.8 s at its default (1.6 times) and
  11.8 s at 60 mi, and in 19.3 and 29.2 s when the target is 50 and 47 mi, which asks for more
  routes (186 and 343 router calls); the twelve trail-seek trips take 0.7 to 11.8 s. The
  hard bounds and the `statement_timeout` patterns of the trail seek (TRAILSEEK r1) are unchanged:
  every table read and corridor search is bounded by its leg's own stop time.
- **A long calm plan takes the long ride's in-flight slot** as well as an ordinary one
  (`ratelimit.LONG_ROUTING_IN_FLIGHT`: one per client, one in the deployment), and needs no
  confirmation (it is under the confirm span). Its timed-out 503 carries `long_ride_timed_out`.
- Other ride types keep today's limits: past 19 mi the calm search does not run (`limited: "span"`).
  Cargo with passengers, the only other stress-averse ride, tops out at 80, where there is no calm
  search at all.

**2. A rider-set target distance (`Dials.target_distance_m`, API `target_distance_m`; items 256, 271).**
- "Target distance" (named "Longest ride" and `max_distance_m` / `maxmi` until item 271, with no
  alias since they were never released), optional, at the top of the slider (100) only: below it the
  field is ignored (and `dials.target_distance_m` says null). In miles first, kilometres in brackets,
  in the UI and the link (`targetmi`, miles to a tenth). The API takes whole metres from 1,000
  (0.6 mi) to 1,000,000 (620 mi).
- **It is a target, not a maximum** (271): the planner aims at or under it, and up to it the extra
  distance costs half the default's price, 1 mi [1.6 km] of LTS 3 saved per 10 mi [16 km]
  (`refine.WORTH_UP_TO_TARGET`; OWNER-DECISIONS 435, the owner's "One rule" of 2026-10-10: free
  until then, so a route a little calmer could add any miles up to the target). Past it a longer
  route is taken only where the stress it saves pays for the miles past the target at the stricter
  bar (`refine.WORTH_OVER_TARGET`, below),
  and never past **1.25 times it** (`presets.TARGET_CEILING_RATIO`, the hard ceiling,
  `presets.target_ceiling_m`). The answer always says how far over it is
  (`calm_search.over_target_m`, and each candidate's `over_target_m`); the page says "X mi over your
  target", miles first with km in brackets, in the summary and in the announcement.
- **With no target: the ceiling is 1.6 times the router's own route** (the use_roads 0 route
  Trailmaxxing plans without a search), and at least a mile more (`presets.default_ceiling_m`,
  `DEFAULT_CEILING_RATIO`, `DEFAULT_CEILING_EXTRA_M`), and inside it every extra mile must buy
  stress at the default bar (268, `refine.WORTH_DEFAULT`). The router's own route is the reference
  rather than the straight line because that is what the rider sees as "the direct route".
- The search minimises stress inside the ceiling (see "The order"). A candidate past the ceiling is
  never taken: it is not even read (its router answer's length is checked first), a round whose
  every exclusion set sends the route past it is asked again with each half of the targets, and a
  long plan's legs share the detour (below).
- **If the router's own route is past the target**, the router is asked at lower traffic positions,
  calmest first, until a route fits (`routing.FIT_STRESS_LADDER`: 70, 40, 0), and then the stretch
  between the last two is bisected three times (`FIT_BISECT_STEPS`) for a calmer route that still
  fits (`routing._fit_target`). Then (`routing._past_target`) every route found past the target but
  within the ceiling, the router's own first, is read and weighed against the one that fits by
  `refine.better` (so it must be calmer and worth its miles past the target); the one kept is the
  search's first route, and its costing the search's costing (`calm_search.fitted_at` says the
  position where it is a rung). Union Station to Penn at 50 mi: the calm route is 57.7 mi; routes of
  54.5, 48.1 and 40.4 mi exist at use_roads 0.5, 0.7 and 1.0.
- **If no route fits the target** (267, "Least-stress route, flagged (Recommended)"): the least
  stressful route found within the ceiling, in the 258-262 order (`refine.calmer`, the shorter on a
  tie), is answered with `calm_search.fits: false`, `calm_search.no_fit: true`,
  `limited: "target_distance"` and `over_target_m` ("No route within your target distance ... This is the least stressful one found.
  It is X mi over your target."), and nothing is searched. Not the shortest, as before 267.
- **If not even one is within the ceiling** (298(2), "Calmest found, flagged (Recommended)"): the
  least stressful of all the routes found (the same order, then the shorter) is answered, flagged
  the same way (`no_fit: true`, `over_target_m`), so "the least stressful one found" is true here
  too. The first build answered the shortest in this case; the shortest is now answered only where
  none of them can be read. These readings, like `settle`'s and a long plan's final reading, stop
  at `refine.late_deadline(ctx)` (the deadline less `REFINE_TRACE_RESERVE_S`).
- **`calm_search.no_fit`**: true only where no route within the target was found, false where one
  was, null with no target. The front end keys its "No route within your target distance"
  sentence on it. After the dodge pass it is cleared only where the route now fits.
- **`calm_search.limited`**: `"target_distance"` is the no-fit answer's alone. `"ceiling"` is its own
  code: the exclusion search's next round found only routes past `ceiling_m`, so it stopped there.
  A calmer, longer route may exist, and the answer may well fit the target.
- The plan hash carries it (`targetmi`, and `loop`; the weight's `sysweight` was taken out by
  OWNER-DECISIONS 313, and an older link's is ignored); they are additive and the link
  version stays 2, because no field a link already carried changes its meaning, and a bump to 3
  would make an older page's `stressFromV1` remap a v3 link's stress.

**3. No trail credit (257 supersedes 202).** `Preset.trail_credit`, `presets.trail_credit_for`,
`refine.trail_flags`, `Analysis.trail_m` and the corridor search's trail term (`RouteLine.trail_to`,
`MIN_TRAIL_GAIN_M`, `best_in`'s credit) are gone. The corridor search stays: a corridor is worth
the busy road it replaces (rate x exposure) less its detour, and it finds routes the exclusion
rounds cannot reach (it was taken on the long trips below), so it is kept as the second candidate
generator; with no credit a route with nothing busy on it has no corridor. A quiet street counts the
same as a trail. The card and the calm note no longer say "favors trails".

**4. The hills choice and the patience (GATE-corr SF1, SF2).**
- `routing.calmer_or_own` and `no_busier_than_middle` weigh the plan's own `presets.Exposure`
  (Trailmaxxing 1/8/16, not the fixed 1/2/3) and, on a ride with the LTS 4 hold, never choose an
  alternate or the middle route with more LTS 4 and Avoid metres than the router's own route (1 m of
  slack), so `refine`'s hold measures against the router's own route.
- A round the LTS 4 hold refuses no longer counts as a non-improving round (`REFINE_PATIENCE` is
  about rounds that did not improve, not rounds that were refused). Silver Spring to College Park
  is re-measured in the table.

### The order (items 258 to 263)

At the top of the slider (`presets.maxcalm_for`: calm rate at its maximum, position 100, on any ride
type) a candidate is ranked by `refine.better`, not by the score, in strict order with a tolerance at
each level (`MAXCALM_STEPS`: 15 m, 50 m, 50 m):

1. **LTS 4 and Avoid metres plus the cost of each very high stress (red) junction**, in the junction
   model's own unit (feet-equivalent, 2,000 to 4,500 ft each, converted to metres): the owner's "weight
   Very Stressful and LTS4 equally" (259). Tolerance 15 m, about 50 ft: ties within it go to level 2.
2. **LTS 3 metres plus the cost of each higher stress (orange) junction** (260), tolerance 50 m.
3. **Effort-equivalent distance blended with the actual distance by the Hills slider**
   (`(1 - w) x actual + w x effort`, w = 0 at the detent and 1 at full avoid) (262), tolerance 50 m. At
   the detent it is the actual distance. **Right of the detent** (Hills set to seek hills; 298(3),
   "Keep stress order + target (Recommended)") the search runs as at the detent, in this order and
   to the same target, and a long calm plan runs too (`long_calm_for` no longer takes a `seeking`
   argument). Only the effort term inverts: `Context.hills_seek_weight` (the Hills position / 100)
   subtracts that share of the effort in `refine.level3`, so of two equally calm routes the one with
   more climbing is preferred. The 268 distance charge does not see that credit: its `blended_m` is
   `refine.charged_m`, the avoid-side blend alone, so seeking climbs never buys miles (the release
   re-check's S1: a 40 km hilly route against a 20 km flat one was charged nothing at full seek, and
   any stress saving was worth it). On Trailmaxxing and Cargo with passengers at the top of the stress
   slider no climb search among the router's alternatives is asked, and the answer's
   `hills_seek.limited` is `"calm_first"`; below the top the climb search is as before. Before 298(3) the stress-order search and the target fit were
   skipped while the slider sought, though the target dial was still offered. What seeking should
   mean in the end is FOLLOWUP-HILLS-TOLERATE (242).

The router's own price for a route is not in it, nor is any credit for trail. The target distance and
the ceiling are in *actual* metres. The 250 hold now compares the same top figure (LTS 4 and Avoid plus red junction
cost): a candidate is refused only if it is more than the router's own route's by 1 m, so LTS 4 may
be traded for a red junction's worth, never for nothing (`refine.top_by_leg`, `more_lts4`).

**Effort (`routemaker.effort`).** The standard cycling-power model (Martin et al. 1998): force per
metre F = Crr m g cos t + 1/2 rho CdA v^2 + m g sin t at a steady 12.4 mph (20 km/h); a stretch's
effort is its length times F / F0, F0 the force on the flat; floored at 1, so a descent costs the flat
and never offsets a climb (263). The grade is read over 300 m windows of the 30 m elevation samples
(a 2 m error between neighbours is 7%). Constants: Crr 0.006, CdA 0.40 m^2, air 1.225 kg/m^3,
mass 90 kg by default; 8% costs 6.5 times the flat. The system weight is optional (item 264, and
private since 313-318: see "The rider and bike weight" below): 25 kg
(55 lb) to 700 kg (1,543 lb), clamped silently outside (337, 338, 352; 68 to 140 kg when first
built), default 90 kg (198 lb), 120 kg (265 lb) for Cargo with passengers; only
the climbing and rolling terms scale with it, so a flat route's effort-distance is its length at any
weight. Elevation is the router's own profile (the data `climb_m` uses). Sensitivity: every percent of
grade adds about 9 N to a 12.7 N flat force, so noise of 2 m over 300 m inflates a flat stretch by
half; both candidates carry the same noise, but the effort level should be read as a tiebreaker.

### Diminishing returns on extra distance (items 268, 271)

The owner, 268: "Diminishing returns (Recommended)": 1.6 times the router's own route stays the
ceiling, but "extra distance is taken only when it buys a meaningful stress cut. Roughly: at least
1 mi of LTS 3 saved per 5 mi added, LTS 4/Avoid and red junctions weighted higher." So at the top of
the slider `refine.better` takes a longer candidate only if it is calmer (the order above) **and**
worth its miles (`refine.worth_it`), and a shorter one replaces a calmer longer one whose extra miles
were not worth it:

- **The stress figure** (`refine.stress_weight_m`, metres of LTS 3): LTS 3 x1, LTS 4 x2 and Avoid
  x3 (`refine.WORTH_WEIGHTS`, the standard level weights, `presets.EXPOSURE_STANDARD`, on every ride),
  plus each red junction's cost at the LTS 4 weight and each orange junction's at the LTS 3 weight
  (the junction model's own cost, 259 and 260). 1 mi of LTS 4 saved buys up to 10 mi by default; a
  3,000 ft red junction about 5.7 mi. **Not** the stress-averse rides' 1/8/16 (item 250): measured
  first with them, one red junction (8 x 3,000 ft, about 4.5 mi of LTS 3) bought 23 mi, so Union
  Station to Penn kept its 73.2 mi default (leg 3 went from 11.5 to 26.0 mi to clear 0.9 mi of LTS
  3 and a red junction while taking on 0.07 mi more LTS 4) and went 12.2 mi past a 60 mi target to
  72.2 mi with 0.33 mi of LTS 4. The ranking still puts LTS 4 first whatever the weight; the weights
  only say how many miles a cut is worth. The owner confirmed the standard weights, 287(1), "Normal
  weights (Recommended)".
- **Which level pays** (release review, spec SF2; `refine.stress_saved_m`). The distance is charged
  against the highest level that improves: a saving at the top figure (LTS 4, Avoid and red junctions) pays for its
  miles on its own, and extra LTS 3 never subtracts from it. Within a level the 1/2/3 weights still
  set the trade. The first build netted every level into one `stress_weight_m`, so a 10 km route
  with 200 m of LTS 4 beat a 12 km route with none and 600 m more LTS 3: the LTS 3 cancelled the
  LTS 4 saving, against 287(1), which keeps LTS 4 first in the stress order. `choose_options` and the loop's way
  back use the same rule through `worth_it`.
- **The charge** (`refine.distance_charge_m`), the stress the extra distance must save:
  - no target: the metres added over the slider's `worth_ratio` (435, "One rule"): `WORTH_DEFAULT` =
    **5** at the top (1 mi of LTS 3 per 5 mi), and below it about 1.2 at 85, 1.7 at 90 and 2.8 at 95,
    measured as the Hills slider weighs distance (`level3`), so a longer route that is less effort
    with Hills set to avoid is not charged for it;
  - with a target (271): the actual metres up to it over `WORTH_UP_TO_TARGET` = **10** (1 mi of LTS 3
    per 10 mi; 435, where 271 made them free), and those past it over `WORTH_OVER_TARGET` = **2.5**
    (1 mi of LTS 3 per 2.5 mi past the target: stricter than the default);
  - a leg of a plan with stops is charged at the whole trip's length (`rest_m`), and a spliced trip
    is checked again as a whole (`seek.whole_trip: "not_worth"`).
- **A long plan**: each leg's search keeps every option with no price on distance of its own
  (`Context.worth_rule` off), and `choose_options` takes an upgrade only where its stress saved pays
  the charge at the whole trip's length (so the target and its bar are the whole trip's).
- **A loop**: the way back is chosen by `better` among those sharing at most 30%, so the whole loop's
  extra distance has the same diminishing returns.

Both bars are documented assumptions and tunable (`refine.WORTH_DEFAULT`, `WORTH_OVER_TARGET`); the
measurements are in the tables below.

### Sharing the detour among the legs (`choose_options`)

A first version gave each leg a share of the detour by its weight. Measured, it wasted the detour:
Union Station to Penn at 60 mi had 2.3 mi to spare, and the leg searched first took a corridor 1 mi
longer that cleared 0.3 mi of LTS 3 while a later leg had no use for its share. Now every leg's
search may use all of the detour the ceiling leaves the whole and keeps every candidate it reads
(`Context.options`); each leg's candidates are reduced to a chain, each calmer and longer than the one
before (`frontier`), and the detour is then spent where it buys the most, by the benefit of each
upgrade per metre it adds, weighted 1000 : 1 : 0.01 down the order (`choose_options`, greedy), each
upgrade only where it is worth its miles (above). The legs that were not searched count against the
ceiling. The whole is never past it (tested).

### Routes to choose from (item 265)

At the top of the slider the answer carries up to three more routes (`candidates`, each a whole route
body with its `rank`; the answer is rank 1 and unchanged). Nothing scores scenery. A candidate is picked
(`refine.pick_candidates`) if it: is within the ceiling, and no further past the rider's target than
the answer (`refine.over_answer`, 271: past the target only where it buys stress, which a near-tie
does not); passes the hold; is a near-tie with the answer on stress (top figure no more than 150 m
[490 ft], level 2 no more than 800 m [0.5 mi] worse; 45 m and 300 m until item 287(4), "Loosen a bit
(Recommended)"); and is meaningfully different from every route already chosen,
which is **under 70% shared road by matched way length (`ALT_OVERLAP`; 60% until item 269, "Loosen a
little (Recommended)"), or at least 5 mi (8 km) of different road** (the second test is the
"different corridor" the owner asked for, since 70% of a 58 mi route is never different). For a plan searched in one piece the pool is the
candidates the search read, and where that gives nothing different enough the router is asked for a
route that avoids the roads of those already chosen (`refine.more_routes`: points every 500 ft (150 m)
along them, none within 500 m of an end or a stop; at most 3 asks and 9 s; a route that is not a near-tie
ends the asking, since avoiding more only makes it busier). For a long plan it is the answer with one
leg's route swapped for another the search read. They are read in full (junctions across the joints)
inside the budget, with at least 6 s left for each (`ALTERNATE_MIN_S`); fewer are returned if time is
short. On a plan of more than one leg (a loop, or a ride with stops) the seek's per-leg candidates
are never offered as routes of their own: a trip for one leg is not a route from start to end
(release review, correctness B1), and every route offered has the answer's legs, start and end
(`_seek_leg` pools its candidates only on a one-leg plan, and `pick_candidates` skips a trip with a
different number of legs). A long calm plan's candidates take the answer's grouping of search
legs into the plan's legs, so none shows the search's internal `leg_ends` or a stop the rider never
placed (release review S1).
They are answered as the search found them: the dodge pass (below, "No dodging through side
streets") is the answer's alone, and where it changed the answer they are picked again against it. On the measured trips almost every plan has one obvious corridor and returns one route (see the
tables): the route that avoids the first is usually far busier, as it should be for a trail corridor.

### Make it a loop (item 266)

A ride whose last point is its first (50 m) is a loop, and the request's `loop: true` closes a
point-to-point ride on its start (`routing.loop_wanted`, `loop_points`); not on a Mass Ride, which
stays point-to-point with no loop control (owner, 298(4): "Keep excluded"). The plan
is asked for through the start again; then the way back (the last leg) is asked for alone
(`refine.make_loop`) with points along the way out excluded (every 120 m, none within 500 m of an end
or a stop; up to 150), thinned to every second, fourth and eighth point if the router has no route or
it is past the ceiling (the whole loop, not each half): every one is asked (four routes at
most), and the least stressful of the ways back that share at most 30% of their road with the way out
(matched by way) is kept (at the top of the slider by `better`, with the diminishing returns on the
whole loop's distance); if none does the one that shares least is kept, so the overlap is preferred away, not forced, and a loop may still use one bridge. If
the way back is the way out whatever is excluded (90% or more), the router's own route is kept and
`loop.fallback` says `out_and_back`. `loop` reports `overlap_pct`, `shared_m`, `return_m`, the points
excluded and the routes asked. The search that follows keeps the way back different: a candidate that
shares more than the loop does (or 30%, if the loop shares less) is refused. A loop past 19 mi (30 km)
of straight line in all is not searched (`limited: "span"`; `refine_long` would ask each leg of the
way back without its exclusions); the way back is still made different. **A loop is never a long
calm plan** (`routing.plan`: `long_calm` is false for a loop), so a long Trailmaxxing loop gets no
calm search at all. The span is `straight_span_m` over the loop's points, the way back included, so
a loop with a 9.5 mi out-leg is already past it, and its note ("over 19 mi in a straight line")
counts both halves.

**Make it a loop by the search (OWNER-DECISIONS 388, 389).** The checkbox is in the Points
section, under the search and above the points list (`App.tsx`, `.loop-toggle`, a 44 px row),
not behind the Ride line's Edit; it is outside the part that hides while the points are
compact, so a route being shown does not take it away. It shows with no point placed, and
never on Mass Ride (`loopView` returns null there). Checked before any point, its visible hint,
also its description, is `LOOP_FIRST_HINT` ("Place the starting point, then a stop or two
along the way."), and "Loop on." plus those words are said once (`LOOP_FIRST_SAID`, from
`loopChangeSaid`, the one function the toggle, a ride-type change and undo or redo call; with
no points the state alone is said: the loop on with what to place, or "Loop off."). Its hint id is
a `useId()`. `emptyPlanHint` and `loneStartHint` say "check Make it a loop under the search". `DialsPanel` no longer has the toggle or a `points` prop.

**Stops in a loop (OWNER-DECISIONS 374).** With "Make it a loop" on, the page treats the ride as a
cycle that starts and finishes at the first point, so no second point has to be stacked on the
start. The toggle can be chosen with the start alone; the route is asked for once there is a second
point. Every later click is a stop (`geo.addPoint(points, point, loop)`: the closing leg, last point
back to the start, is one of the slots and wins a tie; with a start and one stop the two legs tie
exactly, so the second stop is appended and the stops are visited in the order they were clicked).
Points are named "Start and finish" (`loop.LOOP_START_NAME`), "Stop 1", "Stop 2" and never "End" or
"B" in the points list, map markers, search choices ("Start", "Stop"), rail station cards ("Start
here", "Add as stop"), announcements and the GPX (`summary.pointName`, `pointText.pointLabel`,
`gpx.planPointName`, `loop.loopStops`). Inside a sentence the start is "the start" ("Stop 2 added,
between Stop 1 and the start"), and a change that renames the points is announced: the toggle, a
ride type into or out of Mass Ride (which has no loop), and an undo or redo that brings another loop
state back (`pointText.loopChangeSaid`). A new ride type keeps the toggle, as it keeps Avoid gravel
(`rideTypeDialog.choose`), so only Mass Ride turns the loop off; it keeps the flag unused (it is no
moved setting there, and Reset keeps it), and the next ride type brings the loop back.
Dragging the route line works on the closing leg too: the
legs run over the points and the start again (`lineEdit.legPoints`), so the API's `leg_ends` fit
them, and a drag on the way back appends the stop as a click there does (`lineEdit.insertIntoRide`);
the preview runs to the start. Reverse keeps the start and finish and reverses the stops
(`loop.reversedPoints`); with a start and one stop that changes nothing, so the button is
`aria-disabled` with the reason as its description, and a press says it
(`pointText.reverseUnavailableHint`), as the loop toggle does. A ride that already ends on its start
is reversed whole. The GPX names its points from the toggle as it was when the route shown was
planned (recorded with the route, as its points are, so a replan in progress does not mix the two),
not the API's echoed `dials.loop` (which is also true for a ride ending on its start), and writes
`loop=1` in its dials comment, which the import reads back, so a loop reopens as one. The request is
unchanged (`loop_points` already passes through every point after the start and returns to it), and
so are links (`loop=1`). A Mass Ride's link keeps `loop=1`, but its request leaves the flag out
(`api.requestRoute`; `routing.loop_wanted` ignores it there anyway).
A loop implied by an end on the start, with the toggle off, keeps "Start"
and "End". Mass Ride has no loop, and its hints do not mention the toggle.

**Stops in any order (OWNER-DECISIONS 449).** "Best order" (`App.tsx`, in the point tools after
Reverse; `lib/stopOrder.ts`; a one-press button, the owner's choice of 2026-10-10 over 449's switch)
puts the stops in the order that is best as any route is best (the owner, 2026-10-10: "the same
best as any other route. It's adjusted by both traffic stress and elevation"): least by the router's
own cost: riding time (a climb counting through the router's grade-speed model) with the ride's
stress penalties, and below the hills slider's middle its hills penalty, priced in. It is never shown on a Mass Ride, and the API
refuses one (400). Otherwise it shows only with two or more stops to order (`stopsThatMove`): the points between the start and the end, or in a
loop the rider chose every point after the start (a ride that already ends on its start keeps that
end). On a shorter ride it could change nothing, so it is left out rather than shown disabled with a
standing reason under every short ride's tools; More tips says when it appears (`editingTips`). If
it leaves while it has the focus (an undo or a removal takes a stop away), the focus goes to Reverse
beside it. A press sends the ride as a route request would (points, preset and dials, with the riding
speed and the closure choices, `closureFields`; not the weight, which the order does not use) to
`POST /api/stop-order`
(`core.api.stop_order`, the route request's body, its rate and in-flight limits). While the order is
found the button keeps its label and is `aria-disabled`, "Finding the best order for the stops." is
said, and another press says "Still finding the best order." The answer is used only if the points,
ride type and dials are still those it was asked for, and only if it fits them (`applyAnswer`,
`fitsOrder`: every point once, the start first, the end last unless it is a stop). A new order is one
`commit`, so Undo puts the old one back, and the route is asked for as after any edit; an order
already best commits nothing. What came of it is the Points notice (a status, so it is seen and said
once; cleared when the points change again): each stop that moved, by place name or coordinates, with
its old number, how many stayed, and what it saves (`bestOrderSaid`; an order no quicker, chosen for
its cost, says "but on calmer or flatter roads"; an order by riding time alone says why), for example "Stops put in the
best order: Stop 1 is now Eastern Market (was Stop 2), Stop 2 is now Union Market (was Stop 1). The
other stop stays where it was. About 12 min less riding, 1.0 mi (1.6 km) shorter. Undo puts the old
order back." An order already best, an answer by straight line, a refusal and a ride changed meanwhile
each say so there.

On the server, `core.stoporder.order` asks the ride's own router (the graph and costing `/route`
would use, `presets.variant_for_ride` and `presets.costing`; a test plans the same bodies through
both and compares) for the cost of the route between every pair of points an order may ride. Valhalla's
matrix answers only times and distances, so up to ten stops (`COST_MAX_STOPS`; k stops are k(k+1)
pairs, 110 at ten) the costs are the legs' `summary.cost` from ordinary `/route` requests with
`break` locations and the plan's `date_time` (`_leg_costs`), chained so each pair is one leg once
(`_pairs_chains`: an Euler walk through every stop-to-stop pair from the start to the end, and a
start-stop-end chain for each other stop; a request holds at most 50 locations, the routers'
`max_locations`, and 250 mi (400 km) of straight line between them in turn, under their
`max_distance`), within 12 s (`COST_BUDGET_S`). Every cost comes from one graph: a weekend or
off-road router that stops answering part way leaves the standard graph to answer every leg again,
and one still silent when the 12 s end is not marked down (it had less than its own limit) but the
matrix asks the standard graph. Past ten stops, or when the legs are refused (a
pair the router cannot join refuses its whole request), out of time or carry no cost, the order is by
the riding times of Valhalla's matrix (`sources_to_targets`, added to `loki.actions` by
`scripts/build_valhalla_configs.py`) along the same least-cost ways, and the page says it did not
weigh stress and hills. A weekend or
off-road router is handled as `/route` handles it: at most 15 s, and one that does not answer or has
no tiles leaves the standard graph to answer and is remembered as down.
`routemaker.stoporder.best_order` chooses the order: exact (Held-Karp) up to 13 stops, about a quarter of a second; past
that, local moves (or-opt and 2-opt) from the rider's order, the nearest-neighbour order and eight
seeded shuffles, stopping new starts after 3 s, which is not proven best (`exact` false). Costs are
read in the direction ridden (one-way streets, climbs); a pair the router cannot join is never chosen.
The rider's order is kept unless the new one saves at least 1% (`MIN_SAVING_FRACTION`), so a
reshuffle for nothing does not renumber the stops. The times are the router's own routes between the
points, not the calm search's or the hills slider's choice, which run only when the route itself is
planned (the hills slider's search among alternatives does not run on a ride with stops; the calm
search does, leg by leg, so a planned route can differ from the legs ordered), and the matrix is
asked without a `date_time`. Past 93 mi (150 km) of straight line (the
route API's long-ride line) the router is not asked, and a ride past 124 mi (200 km), a loop's way
back included, is refused as `/route` refuses it. A router out of time also leaves the straight-line order. A router that does not serve the matrix (one started
before this change, or one that is down) is not an error: the order is chosen by straight-line
distance and the answer's `by` says so, as the page then does. Whether the ride is a loop and ends on
its start is read from the rider's points, as the page reads it; the router is asked about the
points it would route (a Zoo point at the racks). The answer: `order` (indices into the points sent;
a loop's return to the start is not in it), `changed`, `by` (`route_cost`, `riding_time`, `straight_line`, or null
with fewer than two stops, when the router is not asked), `exact`, and `before_s`/`after_s`,
`before_m`/`after_m` for the rider's order and the new one. Tests: tests/test_stop_order.py (the
solver against brute force over every order, and the endpoint through a fake router) and
frontend/src/lib/stopOrder.test.ts.

### The tables

**The motivating trips and the target distance** (before items 267-271) (Trailmaxxing 100; LTS 1 / 2 / 3 / 4 / Avoid miles; red and orange junctions; plan time; router calls). The new code through the harness; "live" is the deployed API (47c2f52), which skips the calm search past 19 mi.

| Trip | Target | Miles | LTS 1 / 2 / 3 / 4 / Avoid | Red, orange | Plan time | Router calls | Live, before |
|---|---|---|---|---|---|---|---|
| Union Station to Baltimore Penn | default (1.6x) | 73.2 | 35.39 / 28.69 / 6.01 / 0.33 / 0.00 | 0, 37 | 16.8 s | 184 | 57.7 mi; 28.92 / 21.23 / 7.24 / 0.26 / 0.00; 1r 23o; 4.8 s |
| Union Station to Baltimore Penn | 60 mi | 58.6 | 26.51 / 21.67 / 6.94 / 0.26 / 0.00 | 1, 30 | 11.8 s | 138 | 57.7 mi; 28.92 / 21.23 / 7.24 / 0.26 / 0.00; 1r 23o; 4.8 s |
| Union Station to Baltimore Penn | 50 mi | 47.7 | 24.04 / 8.39 / 12.19 / 2.94 / 0.00 | 3, 16 | 19.3 s | 186 | - |
| Union Station to Baltimore Penn | 47 mi | 46.9 | 9.01 / 8.01 / 24.47 / 4.70 / 0.00 | 1, 14 | 29.2 s | 343 | - |
| The owner's ride, its own start and end | 60 mi | 59.0 | 27.37 / 20.44 / 7.14 / 0.26 / 0.00 | 2, 27 | 13.9 s | 152 | - |
| The owner's ride, its own start and end | 47 mi | 46.4 | 23.85 / 8.77 / 10.74 / 2.87 / 0.00 | 4, 19 | 13.8 s | 111 | - |
| Bethesda to Frederick | default (1.6x) | 53.7 | 28.14 / 15.21 / 5.31 / 1.81 / 0.00 | 4, 27 | 9.7 s | 97 | 53.7 mi; 31.33 / 15.26 / 5.31 / 1.81 / 0.00; 4r 25o; 4.8 s |
| Alexandria to Annapolis | default (1.6x) | 72.0 | 51.36 / 9.58 / 8.48 / 1.49 / 0.00 | 2, 33 | 20.3 s | 187 | 65.1 mi; 47.13 / 8.20 / 8.15 / 1.64 / 0.00; 2r 30o; 6.5 s |

The owner's ride of 2026-10-03 itself, map-matched against today's graph: 46.7 mi; 25.2 / 5.1 / 11.3 / 5.2 / 0.06 mi.

**The twelve trail-seek trips** at Trailmaxxing 100 with no target (the default ceiling). Miles; LTS 1 / 2 / 3 / 4 / Avoid miles; red (r) and orange (o) junctions; plan time. Live is the deployed API, "old code" is 47c2f52 in the same harness as the new code.

| Trip | Live (47c2f52) | Old code, harness | New code, harness |
|---|---|---|---|
| rockville-silver-spring | 14.0 mi; 7.78 / 5.89 / 0.26 / 0.11 / 0.00; 1r 9o; 3.6 s | 14.7 mi; 8.45 / 5.75 / 0.26 / 0.11 / 0.00; 1r 10o; 2.0 s | 13.8 mi; 7.34 / 5.75 / 0.32 / 0.11 / 0.00; 1r 10o; 5.1 s |
| bethesda-capitol | 14.0 mi; 12.36 / 1.38 / 0.29 / 0.00 / 0.00; 0r 1o; 2.7 s | 14.4 mi; 13.03 / 0.58 / 0.30 / 0.00 / 0.00; 0r 3o; 1.4 s | 14.0 mi; 11.76 / 1.38 / 0.29 / 0.00 / 0.00; 0r 3o; 3.6 s |
| falls-church-union-station | 11.7 mi; 10.46 / 1.24 / 0.00 / 0.00 / 0.00; 0r 1o; 2.4 s | 11.7 mi; 10.24 / 1.24 / 0.00 / 0.00 / 0.00; 0r 1o; 0.7 s | 11.7 mi; 10.24 / 1.24 / 0.00 / 0.00 / 0.00; 0r 1o; 2.6 s |
| silver-spring-college-park | 9.9 mi; 7.18 / 2.36 / 0.25 / 0.07 / 0.00; 0r 3o; 1.0 s | 9.9 mi; 7.33 / 2.19 / 0.20 / 0.07 / 0.00; 0r 5o; 0.7 s | 9.9 mi; 7.33 / 2.19 / 0.20 / 0.07 / 0.00; 0r 5o; 1.1 s |
| bethesda-silver-spring | 5.3 mi; 2.40 / 2.23 / 0.56 / 0.11 / 0.00; 0r 5o; 0.9 s | 5.3 mi; 2.40 / 2.23 / 0.56 / 0.11 / 0.00; 0r 5o; 0.5 s | 5.3 mi; 2.40 / 2.23 / 0.56 / 0.11 / 0.00; 0r 5o; 1.1 s |
| laurel-college-park | 15.0 mi; 8.98 / 3.11 / 2.78 / 0.16 / 0.00; 1r 9o; 1.4 s | 15.1 mi; 8.24 / 3.11 / 2.78 / 0.16 / 0.00; 0r 10o; 1.2 s | 15.1 mi; 8.24 / 3.11 / 2.78 / 0.16 / 0.00; 0r 10o; 4.1 s |
| poolesville-darnestown | 21.0 mi; 12.06 / 5.21 / 2.10 / 1.65 / 0.02; 5r 3o; 1.4 s | 21.0 mi; 4.81 / 5.21 / 2.10 / 1.65 / 0.02; 5r 3o; 0.9 s | 21.0 mi; 4.81 / 5.21 / 2.10 / 1.65 / 0.02; 5r 3o; 3.2 s |
| bowie-annapolis | 43.7 mi; 25.43 / 7.17 / 9.00 / 2.09 / 0.00; 3r 17o; 4.2 s | 43.7 mi; 25.28 / 5.77 / 9.00 / 2.09 / 0.00; 3r 20o; 2.0 s | 43.7 mi; 25.28 / 5.77 / 9.00 / 2.09 / 0.00; 3r 20o; 11.8 s |
| tysons-ballston-wod | 10.9 mi; 9.48 / 1.05 / 0.35 / 0.00 / 0.00; 1r 5o; 2.4 s | 10.9 mi; 9.14 / 1.05 / 0.36 / 0.00 / 0.00; 1r 7o; 2.4 s | 10.9 mi; 9.14 / 1.05 / 0.36 / 0.00 / 0.00; 1r 7o; 4.1 s |
| eastern-market-pg-plaza-anacostia | 9.7 mi; 7.85 / 1.74 / 0.13 / 0.00 / 0.00; 0r 5o; 0.7 s | 9.7 mi; 7.79 / 1.74 / 0.13 / 0.00 / 0.00; 0r 5o; 0.7 s | 9.7 mi; 7.79 / 1.74 / 0.13 / 0.00 / 0.00; 0r 5o; 1.4 s |
| friendship-heights-rosslyn-cct | 7.7 mi; 7.13 / 0.15 / 0.42 / 0.00 / 0.00; 1r 1o; 0.7 s | 7.7 mi; 7.04 / 0.15 / 0.42 / 0.00 / 0.00; 1r 1o; 0.7 s | 7.7 mi; 7.04 / 0.15 / 0.42 / 0.00 / 0.00; 1r 1o; 1.1 s |
| takoma-hyattsville-sligo | 4.9 mi; 3.00 / 1.86 / 0.04 / 0.00 / 0.00; 0r 2o; 0.4 s | 4.9 mi; 2.88 / 1.86 / 0.04 / 0.00 / 0.00; 0r 3o; 0.5 s | 4.9 mi; 2.88 / 1.86 / 0.04 / 0.00 / 0.00; 0r 3o; 0.7 s |
| Total | 167.9 mi; LTS 4+ 4.21; LTS 3 16.19; 12r 61o | 169.0 mi; LTS 4+ 4.21; LTS 3 16.15; 11r 73o | 167.7 mi; LTS 4+ 4.21; LTS 3 16.20; 11r 73o |

- rockville-silver-spring calm: {'limited': None, 'rounds': 3, 'ceiling_m': 35451.2, 'fits': True, 'fitted_at': None} calls {'route': 6, 'trace_attributes': 6, 'locate': 19} candidates 0
- bethesda-capitol calm: {'limited': None, 'rounds': 1, 'ceiling_m': 31793.6, 'fits': True, 'fitted_at': None} calls {'route': 6, 'trace_attributes': 6, 'locate': 16} candidates 1
- falls-church-union-station calm: {'limited': None, 'rounds': 0, 'ceiling_m': 30156.8, 'fits': True, 'fitted_at': None} calls {'route': 3, 'trace_attributes': 2, 'locate': 10} candidates 0
- silver-spring-college-park calm: {'limited': None, 'rounds': 0, 'ceiling_m': 25411.2, 'fits': True, 'fitted_at': None} calls {'route': 3, 'trace_attributes': 3, 'locate': 4} candidates 0
- bethesda-silver-spring calm: {'limited': None, 'rounds': 0, 'ceiling_m': 13632.0, 'fits': True, 'fitted_at': None} calls {'route': 4, 'trace_attributes': 3, 'locate': 9} candidates 0
- laurel-college-park calm: {'limited': None, 'rounds': 5, 'ceiling_m': 38742.4, 'fits': True, 'fitted_at': None} calls {'route': 8, 'trace_attributes': 8, 'locate': 33} candidates 0
- poolesville-darnestown calm: {'limited': None, 'rounds': 2, 'ceiling_m': 54180.8, 'fits': True, 'fitted_at': None} calls {'route': 7, 'trace_attributes': 4, 'locate': 6} candidates 0
- bowie-annapolis calm: {'limited': None, 'rounds': 5, 'ceiling_m': 112529.6, 'fits': True, 'fitted_at': None} calls {'route': 23, 'trace_attributes': 8, 'locate': 59} candidates 0
- tysons-ballston-wod calm: {'limited': None, 'rounds': 5, 'ceiling_m': 26022.4, 'fits': True, 'fitted_at': None} calls {'route': 8, 'trace_attributes': 7, 'locate': 21} candidates 0
- eastern-market-pg-plaza-anacostia calm: {'limited': None, 'rounds': 0, 'ceiling_m': 25019.2, 'fits': True, 'fitted_at': None} calls {'route': 3, 'trace_attributes': 4, 'locate': 4} candidates 0
- friendship-heights-rosslyn-cct calm: {'limited': None, 'rounds': 1, 'ceiling_m': 19832.0, 'fits': True, 'fitted_at': None} calls {'route': 5, 'trace_attributes': 5, 'locate': 8} candidates 0
- takoma-hyattsville-sligo calm: {'limited': None, 'rounds': 2, 'ceiling_m': 12622.4, 'fits': True, 'fitted_at': None} calls {'route': 5, 'trace_attributes': 5, 'locate': 8} candidates 0

**Loops** (item 266), Trailmaxxing 100 unless named:

| Ride | Loop | Overlap | Way back shared | Asked / excluded | Plan |
|---|---|---|---|---|---|
| loop-takoma-hyattsville | 8.8 mi; 3.50 / 4.36 / 0.71 / 0.00 / 0.00; 0r 5o; 2.8 s | 17.4% | 1094.0 of 6296.0 m | 4 / 37 | fallback None; calls {'route': 10, 'trace_attributes': 11, 'locate': 21} |
| loop-bethesda-silver-spring | 11.4 mi; 4.64 / 5.62 / 0.88 / 0.19 / 0.00; 0r 9o; 7.8 s | 21.6% | 2115.0 of 9771.0 m | 4 / 5 | fallback None; calls {'route': 14, 'trace_attributes': 28, 'locate': 67} |
| round-trip-tysons-ballston | 21.3 mi; 14.85 / 4.03 / 2.03 / 0.06 / 0.00; 3r 13o; 8.9 s | 7.9% | 1429.0 of 18007.0 m | 4 / 41 | fallback None; calls {'route': 11, 'trace_attributes': 15, 'locate': 69} |
| loop-rockville-silver-spring-60mi-cap-12 | 21.1 mi; 1.81 / 4.59 / 12.19 / 2.26 / 0.00; 1r 10o; 3.9 s | 88.1% | 14887.0 of 16905.0 m | 4 / 0 | fallback out_and_back; calls {'route': 8, 'trace_attributes': 4, 'locate': 37} |
| loop-default-preset-bethesda-capitol | 25.4 mi; 20.21 / 4.11 / 0.82 / 0.00 / 0.00; 1r 6o; 4.7 s | 1.5% | 313.0 of 20948.0 m | 4 / 44 | fallback None; calls {'route': 6, 'trace_attributes': 7, 'locate': 25} |


### Measured after items 267 to 271

The same harness and graph as the tables above, re-run on 2026-10-03 for this round: "before" is
2b92cc6 (the round above), "after" this code. Trailmaxxing 100; LTS 1 / 2 / 3 / 4 / Avoid miles.

| Trip | Target | Before | After | Plan time, router calls (after) |
|---|---|---|---|---|
| Union Station to Baltimore Penn | none (1.6x ceiling, 92.8 mi) | 73.2 mi; 35.39 / 28.69 / 6.01 / 0.33 / 0.00; 0r 37o | **58.6 mi**; 26.51 / 21.67 / 6.94 / 0.26 / 0.00; 1r 30o | 19.1 s, 182 |
| Union Station to Baltimore Penn | 60 mi (ceiling 75.0 mi) | 58.6 mi; 26.51 / 21.67 / 6.94 / 0.26 / 0.00; 1r 30o | 58.6 mi, within it; the same | 18.1 s, 182 |
| The owner's ride, its own start and end | 60 mi | 59.0 mi; 27.37 / 20.44 / 7.14 / 0.26 / 0.00; 2r 27o | 57.2 mi, within it; 25.79 / 20.23 / 7.14 / **0.26** / 0.00; 2r 28o | 16.0 s, 170 |
| Union Station to Baltimore Penn | 50 mi (ceiling 62.5 mi) | 47.7 mi; 2.94 mi LTS 4, 12.19 LTS 3; 3r 16o | 57.5 mi, **7.5 mi (12.1 km) over**; 25.94 / 21.06 / 7.23 / 0.26 / 0.00; 1r 29o | 34.3 s, 216, `limited: time` |
| Union Station to Baltimore Penn | 47 mi (ceiling 58.8 mi) | 46.9 mi; 4.70 mi LTS 4, 24.47 LTS 3; 1r 14o | 57.5 mi, **10.5 mi (16.9 km) over**; the same | 35.7 s, 191, `limited: time` |
| The owner's ride, its own start and end | 47 mi | 46.4 mi; 2.87 mi LTS 4, 10.74 LTS 3 | 56.6 mi, 9.6 mi over, no route within the target found (267); 26.30 / 19.67 / 7.40 / 0.26 / 0.00; 2r 30o | 24.2 s, 204 |
| Bethesda to Frederick | none | 53.7 mi; 1.81 LTS 4, 5.31 LTS 3 | 53.7 mi; the same | 11.8 s, 97 |
| Alexandria to Annapolis | none | 72.0 mi; 51.36 / 9.58 / 8.48 / 1.49 / 0.00; 2r 33o | **65.2 mi**; 46.59 / 8.20 / 8.11 / 1.54 / 0.00; 2r 32o | 24.9 s, 187 |

- **268 at the default:** Union Station to Penn no longer takes the 73.2 mi route (+15.5 mi for
  1.2 mi less LTS 3, 0.07 mi more LTS 4 and 14 more orange junctions): the answer is the 58.6 mi
  route of the 60 mi run. Alexandria to Annapolis drops from 72.0 to 65.2 mi for 0.37 mi more LTS 3
  and 0.05 mi more LTS 4.
- **271 at 50 and 47 mi:** the target is soft, so the calm 57.5 mi route is answered past it: 7.5 and
  10.5 mi over, inside the 1.25x ceiling, because it avoids 2.7 and 4.4 mi of LTS 4 against the
  routes that fit. Both plans take 34 to 36 s (the readings of the routes past the target) and stop
  the search at `limited: "time"`, inside the 47 s deadline.
- **267:** the owner's ride at 47 mi found no route within 47 mi and answers the least stressful
  within the ceiling (56.6 mi, 0.26 mi of LTS 4), flagged, not the shortest.
- **The twelve trail-seek trips** at the default are unchanged from the round above (167.7 mi in all,
  4.21 mi of LTS 4 and Avoid, 16.20 mi of LTS 3, 11 red and 73 orange; 0.9 to 9.7 s each).
- **269, alternates:** with the overlap loosened to 70%, still **1 of the 12** offers a second route
  (bethesda-capitol, 13.2 mi beside the 14.0 mi answer). The other eleven have one corridor that is a
  near-tie on stress: the routes the search reads are mostly the same corridor (over 70% shared) or
  not a near-tie (past the 45 m / 300 m bands), so the overlap threshold is not what limits them.
- **Loops:** the four Trailmaxxing loops are as in the round above (8.8, 11.4, 21.3 mi; the 12 mi
  loop near Rockville finds nothing within its 15 mi ceiling and answers its 21.1 mi out-and-back,
  9.2 mi over, flagged); the Default-preset loop 25.4 mi.

### Tests and mutants

- `tests/test_longcalm.py` (order and tolerances, diminishing returns, the target distance, effort
  blending, the hold on the top figure, the ceiling in the search, leg cuts, the long search, sharing
  the detour, candidates), `tests/test_effort.py`, `tests/test_loop.py`, `tests/test_refine.py`
  (`TestTheWorthLegByLeg`), `tests/test_longcalm_api.py` (the request, the fit and the choice past the
  target, the no-fit choice, the answer's target fields, the budget and slot, the candidates, the
  loop), `tests/test_route_dials.py` (the hills choice's exposure and hold),
  `tests/test_plan_constants.py`, and the front end's `targetDistance.test.ts`, `candidates.test.ts`,
  `loop.test.ts`.
- `scripts/mutants_longcalm.py` (90 mutants since 267-271, all killed: 35 new on the no-fit choice,
  the diminishing returns, the 1.25x ceiling, the target fields and the overlap threshold; 55 before; the trail-seek script's 138 all killed too) and `scripts/mutants_trailseek.py` (updated: the 27
  mutants of the trail credit are removed, 16 rewritten against the new code).

### Harness

The runs through the read-only forwarder (`docker exec routemaker-api-1 python -c <forwarder>`: only
POSTs to the routers' `route`, `trace_attributes` and `locate`), with the stress of every edge from the
live stress tiles into a scratch segment table, as in the final-fix round; the plan's own clock does not
count the harness's tile matching. Rides are weekday off-peak (the standard graph) for both the live
and the harness runs. "Live" is the deployed API (47c2f52, graph 20261003T142804Z); "old code" is
47c2f52 in the same harness.

## No dodging through side streets (FOLLOWUP-DEDODGE, items 272, 273)

The owner's words are in PLAN.md, Owner amendments, items 272 and 273. A route should not "dodge
back and forth into side streets along a busier road" unless that "bought a meaningful distance of
calm". The code is `core/dedodge.py`; it is the planner only (no graph change), and it applies to
every ride type.

### The rule as built

After the search has chosen the route, and before it is answered (`routing.plan`, on the answer's
route only; not on a loop, whose way back is kept as it was made, item 266; not on the routes to choose
from, below):

1. **Detect** (`find_dodges`). The route's traced edges are grouped into roads (consecutive edges that
   share a street name; an unnamed edge is a road of its own). A dodge is a run of streets only
   (`STREET_USES`; a trail, a pedestrian crossing, steps or a ramp is not one) between two stretches of
   one named road (`MAIN_USES`, 30 m [100 ft] or more each) that is rejoined within 1 mi [1.6 km]
   (`DODGE_MAX_M`). The road is rejoined by name (going on within 90 degrees of the way it was left, and
   ahead of where it was left), or on a different name on its line (within 35 degrees and 150 m [490 ft],
   `PARALLEL_*`): a road that changes name at a junction is one road. The same road wins over a road on its
   line, which is what makes the Konterra Drive case one dodge (Konterra Drive, Virginia Manor Road,
   Konterra Drive) and not a turn onto a road that happens to run on beside it.
2. **Skip what is no weave** (`skip_reason`, review r0 item 4). A dodge under 50 m [160 ft]
   (`MIN_DODGE_M`), one of unnamed edges alone under 60 m [200 ft] (`MIN_UNNAMED_DODGE_M`), or one that
   turns fewer than two times from the road's last edge before it to its first after it (`BASE_TURNS`: a
   straight run through an unnamed edge, or a way inside one road) is listed as `skipped` and not
   checked, so it spends neither the router nor the cap. On the measured trips these were stubs such as
   Konterra Drive via an unnamed 27 m edge on Union Station to Penn, whose "main road" without them was a
   detour 250 to 1,600 m longer.
3. **Compare.** The plan's own request (same graph, costing, ride time, elevation) for the route between
   the dodge's two ends, each facing the way the route goes, with the middle of each of the dodge's edges
   excluded (at most 40; none within 6 m [20 ft] of a node, which would take out the cross street). Where
   the router finds no path facing a heading it is asked again without. The stretch is spliced into the
   leg (shape, length, time, cost and elevation; where the router gives the stretch no elevation the leg
   keeps its own, the stretch drawn in a straight line between the heights where the dodge left and came
   back) and the leg is read whole with its junctions (`refine.analyse`), as the route as it was. A reading
   the pass's clock ran out in is neither judged nor kept (`_cut_short`): `junctions.nodes_at` leaves out a
   `/locate` batch the clock cut off, so such a reading can be missing junctions, and `refine.analyse`
   would have handed it to the answer. Since the release review such a batch raises
   `junctions.ReadingCutShort`, and the reading is discarded and never cached, wherever it is taken. (Found in this round: on Bowie to Annapolis at Default a removal
   judged on such a reading answered 1 red and 12 orange junctions fewer, along the whole route.)
4. **Judge** (`judge`). The stress the dodge avoids is what the main road carries more of at the top figure
   (LTS 4 and Avoid metres plus the cost of red junctions) plus the second (LTS 3 plus the cost of orange
   junctions): `Analysis.top_m` and `second_m`, the two figures of items 258 to 260.
   - **On every ride type, Default included** (item 298(1), "Same as Trailmaxxing (Recommended)";
     `dedodge.TIE_RULE_ALL_PRESETS`), the dodge is kept if it avoids more than the second level's tie
     step, `dedodge.TIE_STEP_M` (`refine.MAXCALM_STEPS[1]`, 50 m [160 ft]), and no turns are charged.
     Distance ranks below LTS 3 in the order (258 to 262), and the search itself takes 5 m of extra
     distance for each metre of LTS 3 it saves (268). A dodge that avoids no more than a tie step is a
     weave and goes. One that avoids more is a real saving and stays. A dodge that avoids nothing, like
     Konterra Drive's, goes everywhere.
   - **How it was first built** (r0 and r1). The tie step applied only at the top of the slider
     (`TOP_TIE_RULE`, review r0 item 1). Below it a dodge was kept only if
     `avoided >= 0.25 mi [402 m] + 260 ft [80 m] x (the turns it adds - 2)` (`MIN_AVOIDED_M`,
     `TURN_CHARGE_M`, `BASE_TURNS`, item 254's turn load), following item 272's quarter mile.
     Measured at Default, that gave back up to 0.34 mi of LTS 3 a dodge to save 130 to 650 m (the
     table below: LTS 3 16.80 to 18.04 mi over the twelve trips for 1.2 mi less riding), against the
     stress-averse default. 298(1) amends 272's quarter mile, and the turn charge went with it.
     `TIE_RULE_ALL_PRESETS = False` (read by `dedodge.tie_rule()`) restores 272's rule, which is kept
     as the documented fallback and still tested with the switch off.

   Otherwise the main road replaces the dodge.
5. **Guards**, which override the rule: the dodge is kept where taking it out would put the top figure more
   than a metre above the leg as the pass found it or as it now is, whichever is lower (so the slack is the
   leg's, not each dodge's, and the order of items 258 to 262 and the hold of item 250 are never broken:
   any LTS 4, Avoid or red junction a dodge avoids keeps it, however little), where the main road is longer
   than the route was (the target and ceiling of 267 to 271 only get easier), where it is worse on the
   Hills slider's blended distance (`refine.level3`), and where the junctions were read for one route and
   not the other. The Mass Ride and Group Ride keep their graph (the no-trail variant, which has no
   contraflow: the request is the plan's own, so contraflow is as off as it was) and their legs and stops.

   The "longer" guard stays strict (review r0's fuller report asked whether a main road a little longer
   might replace a dodge where the stress is the same and it saves 3 or more turns, since distance was free
   within the target, 287(2), until 435 made it half price). Not taken: every "longer" keep measured is 250 to 6,400 m longer, so the
   replacement is never the main road a few metres on and the case does not arise; and turns are not in
   the stress order until item 254 is built, so trading distance for turns would be a rule of the pass's
   own, outside 258 to 262.
6. **Bounds**, all hard and per plan, since the pass runs once a plan: 8 checks (`MAX_CHECKS`), 40
   exclusions to a request, 5 s (`BUDGET_S`) ending 6 s before the plan's deadline
   (`refine.REFINE_TRACE_RESERVE_S`), 8 s to a call, a pass that is given less than 3 s does not start, and a
   router that fails leaves the route as it was. The pass never raises. The last dodge of a leg is looked at
   first, and each pass reads the leg as it now is, so a dodge is judged against the route after the ones
   after it were taken out.

**After the pass** (`settle`, review r0 items 3 and 5). Where a dodge was taken out, `calm_search` gives the
route as answered (`extra_distance_m` less the metres taken off; `exposure_after_m`, `lts3_m_after`,
`lts4_m_after`, `top_m_after`, `lts4_after_m` read again), and the routes to choose from are picked again
(`refine.pick_candidates`, with the hold's reference the search used, `Context.candidate_reference`)
against the answer as it now is: none goes further past the target than the answer, each is still a
near-tie with it on stress, and each is still meaningfully different from it and from the others (where
removing a dodge made two routes converge, the near-duplicate is dropped). The candidates themselves are
answered as the search found them (their `dodges` is null). Of the two fixes the review offered, one shared
budget across the answer and its candidates or no pass on candidates, this is the second: it keeps the
pass at one bounded run a plan (the review measured up to 32 checks and about 20 s of dodge work a plan when
each candidate had its own), the candidates are never changed after they were picked (so nothing about
them needs checking again but their place beside the changed answer), and they are near-ties offered for
the rider to choose by the map, where a side-street weave is on view; the pass takes out only dodges that
avoid 50 m or less anyway (on every ride type since 298(1)). Reading
the answer again is no extra router work: `refine.analyse` remembers it and the answer uses that reading.

The answer's `dodges` (`DodgesOut`) lists every dodge found, once, in the route's order: the road, the
streets it went through, where, its length, what was done (`removed`, `kept`, `skipped`, `unchecked`),
why, the metres it avoided against what it had to, the turns the main road saves and its extra distance;
`found` is the sum of removed, kept, skipped and unchecked (`skipped` is counted too), including dodges a
removal uncovered on a later pass over the leg. `limited: target_distance` is cleared where taking a dodge
out made the route fit the target. The front end's type is `Dodges` in `frontend/src/lib/api.ts`
(optional; nothing displays it).

### Reproduction (item 273)

Live routers (47c2f52, graph 20261003T142804Z), read-only through the harness; Konterra Drive end to end,
from -76.88905, 39.06785 to -76.89068, 39.08179:

| Ride type | North | South |
|---|---|---|
| Default, Trailmaxxing, Cargo | 1.84 mi [2.97 km]: leaves Konterra Dr (way 256386638) at -76.885651, 39.074958 for Virginia Manor Rd (ways 235061913, 1473496057, 240334415), 0.25 mi [408 m], rejoins way 256386638 | 1.08 mi [1.74 km], straight |
| Fast, Group Ride, Mass Ride, E-bike | 1.75 mi [2.82 km] (Mass Ride 2.12 mi [3.41 km]: its own graph), straight | 1.08 mi |

Both streets are LTS 3 (1.82 mi [2.93 km] of LTS 3 in all), so the dodge avoids nothing and adds 3 turns
and 0.09 mi [147 m]. With the pass: 1.75 mi [2.82 km], LTS 3 1.74 mi [2.80 km], and the route is the Fast
plan's, on every one of the three, Trailmaxxing included (it avoids 0 m, within the tie step). The
recorded routers' answers (route, traces and the stretch between the dodge's ends) are
`tests/data/dedodge_konterra.json`. The saved Union Station to Penn plan's 0.14 mi on Konterra Drive is a
turn from Virginia Manor Road onto Konterra Drive and on to Contee Road, not a dodge.

### Measured

Same harness as the long-calm rounds (a scratch segment table filled from the live stress tiles; weekday
off-peak, the live routers read-only), three runs back to back on the same routers: the pass off, the
pass as first built (r0, ccd75a3) and as revised (r1). LTS 3 and LTS 4 in miles, junctions red plus
orange.

| Trips | Miles off, r0, r1 | LTS 3 off, r0, r1 | LTS 4 (all) | Junctions off, r0, r1 | r1 dodges: found, skipped, checked, removed, kept, unchecked |
|---|---|---|---|---|---|
| Twelve standard trips, Trailmaxxing | 167.7, 166.9, 167.4 | 16.20, 16.99, 16.24 | 4.21 | 11+73, 11+71, 11+69 | 26, 8, 18, 2, 16, 0 |
| Twelve standard trips, Default | 163.3, 162.6, 162.1 | 16.80, 17.67, 18.04 | 4.32 | 12+79, 12+79, 12+77 | 28, 9, 19, 6, 13, 0 |
| Union Station to Penn, Trailmaxxing, no target | 58.70, 58.61, 58.61 | 6.94, 7.17, 7.17 | 0.26 | 1+30, 1+28, 1+28 | 11, 2, 8, 1, 7, 1 |
| Union Station to Penn, Trailmaxxing, 60 mi target | 58.70, 58.61, 58.61 | 6.94, 7.17, 7.17 | 0.26 | 1+30, 1+28, 1+28 | 11, 2, 8, 1, 7, 1 |
| The FIT ride, 60 mi target | 57.28, 57.19, 57.19 | 7.14, 7.37, 7.37 | 0.26 | 2+28, 2+26, 2+26 | 11, 2, 8, 1, 7, 1 |
| Union Station to Penn, Default | 56.05, 56.05, 56.03 | 7.27, 7.27, 7.44 | 0.26 | 1+30, 1+30, 1+28 | 19, 4, 3, 1, 1, 13 (`limited: time`) |

- **Trailmaxxing** (r1): 2 removed, both avoiding 0 m: Konterra Drive via Virginia Manor Road (Laurel to
  College Park, 15.05 to 14.93 mi, LTS 3 2.78 to 2.69) and Lottsford Vista Road via Caribon Street
  (Bowie to Annapolis, 43.70 to 43.53 mi, LTS 3 9.00 to 9.13). Kept at the top that r0 removed: Van Dusen
  Road twice (they avoid 289 and 366 m), Governor Ritchie Highway (214 m) and Dicus Mill Road (541 m), and
  Lottsford Vista Road via Parrish Lane (390 m). LTS 3 over the twelve: 16.20 off, 16.99 r0, 16.24 r1.
- **Default** (r1, the 0.25 mi rule): 6 removed, avoiding 0 to 541 m (0 to 0.34 mi): Van Dusen Road twice
  (289, 366 m), Lottsford Vista Road twice (390, 0 m), Governor Ritchie Highway (214 m) and Dicus Mill Road
  (541 m: over the quarter mile, removed only because its 4 turns raised the bar to 562 m, the turn
  charge deciding it). LTS 3 over the twelve rises 1.24 mi (16.80 to 18.04) for 1.2 mi less riding, which
  runs against the stress-averse default; the owner's answer, 298(1), put Default on the tie step (the rule
  above), and of these six only the Lottsford Vista Road dodge that avoids 0 m is within the tie step.
  More are removed than in r0 because the
  skip frees checks for real dodges (Bowie to Annapolis: 6 of 6 checked, against 4 of 5 with 2 stubs).
- **Record correction (review r0 item 2).** r0's note said the removed dodges each avoided "0.13 to 0.23
  mi ... under the quarter mile, as the rule says". They avoided 0 to 0.34 mi (0 to 541 m): Konterra Drive
  and Lottsford Vista Road 0 m, Dicus Mill Road 541 m, removed by the turn charge (4 turns: 562 m needed).
- **Checks within the cap** (review r0 item 4): skipped stubs on the twelve trips are 8 at Trailmaxxing
  and 9 at Default (Leland Street via Meadow Lane 18 m, Montrose Avenue 21 m, Elm Avenue 20 m, and straight
  runs of 150 to 1,150 m: Maple Avenue via Clagett Drive and the like). The cap or the clock left 1 real
  dodge unchecked on the twelve trips at r0, none at r1; Union Station to Penn checks 8 of 9 real dodges at
  r1 (Tamar Drive is the one left; r0 spent 1 of its 8 checks on a stub). Union Station to Penn at Default,
  a long plan with little of its time left after the search, checks 3 (the third cut short by the clock)
  and leaves 13 of its 15 real dodges unchecked (`limited: time`). Some "longer" keeps are still named one-block jogs (Old Scaggsville
  Road via Clarke Springs Ridge, 65 m) that turn twice and so are checked.
- **Routes to choose from** (item 287(4), below): with the bands at 150 m and 800 m, 2 of the twelve
  Trailmaxxing trips offer a second route (Bethesda to the Capitol, 13.21 mi against 14.03, LTS 3 0.47 mi
  against 0.29, 6.12 mi of path, 0 red and 2 orange, 180 m of climb; Friendship Heights to Rosslyn, 8.82
  mi against 7.70, LTS 3 0.43 against 0.42, 3.42 mi of path, 1 red and 3 orange, 106 m of climb); 1 did
  at 45 m and 300 m (Bethesda to the Capitol).
- LTS 4 and Avoid are unchanged on every trip and the LTS 4 hold holds.

**Latency** (review r0 item 3; Trailmaxxing, the harness, three rounds with the pass off, r0 and r1 in
turn on the same routers, the median): Laurel to College Park 3.63 s off, 4.57 s r0, 4.50 s r1 (+0.9 s);
Bowie to Annapolis 5.96 s, 10.35 s and 9.72 s (+3.8 s: 6 checks of a 43 mi leg, inside the 5 s budget,
then the answer's reading of the changed route). The review's 3.94 to 11.61 s on Laurel to College Park
(cold routers, a candidate's pass of its own as well) is not reproduced warm; with no pass on the
candidates the dodge work is the answer's 5 s at most.

### Load

One pass a plan, on the answer alone. Each check is 1 or 2 `/route` calls (the second without headings),
one `trace_attributes` of the **whole spliced leg** (a plan of one leg is the whole route: 58.6 mi on Union
Station to Penn, 43.5 mi on Bowie to Annapolis), and the junction reading of that leg: `/locate` in batches
of 50 nodes (`junctions.LOCATE_BATCH`), twice (the nodes, then the approaches of those without a signal).
Measured over the pass off: Union Station to Penn, 8 checks, 11 more `/route`, 8 more `trace_attributes`
and 35 more `/locate`; Bowie to Annapolis at Trailmaxxing, 6 checks, 15, 8 and 67; a short trip with one
check, 1 to 2, 1 and 2 to 4. The worst case a plan is 8 checks of 2 `/route`, 1 `trace_attributes` and
2 x (the leg's junction nodes / 50) `/locate` each (on a 58 mi leg, about 10 a check), inside 5 s, plus
the answer's own reading of the changed route afterwards, which the plan does anyway, within its
deadline.

### Tests and mutants

`tests/test_dedodge.py` (the rule at and below the top of the slider, the turn weighting, the corridor
match, the skip, the counting, the edges, the splice and its elevation, the pass and its bounds with each
bound pinned by value, a reading cut short, `settle`, and the Konterra Drive regression on the recorded
routers), `tests/test_dedodge_plan.py` (the plan's wiring through the real planner on a synthetic graph
and the real segment table: every ride type, Trailmaxxing's tie step, a loop, the target's fields, the
search's figures after a removal, the answer's `dodges`, one pass a plan and none on a candidate),
`tests/test_longcalm.py` (the near-tie bands at their boundaries, the reference kept for `settle`) and
`tests/test_route_api.py` (the contract key). `scripts/mutants_dedodge.py` has 212 mutants: the
first round's 131 (three of them, on the candidates' pass that is gone, turned round or replaced, and the
stale-elevation one dropped with its branch), review r0's 32 on the r1 text (its "candidates not dedodged"
turned round, since r1 does not pass them), and r1's own (the top of the slider's rule, the skip, the
counting, the leg as found, the reading cut short, `settle`, the elevation kept, the near-tie bands). All
212 are killed (one, the clock not read between checks, survived the first run and was killed by a test
added for it). `scripts/mutants_longcalm.py`: 90 of 90 killed.

### Route halo, faint-road edge and swatch borders (item 215, colours)

WCAG 1.4.11 asks 3:1 of a graphic against what it touches. Three places fell short;
`stressContrast.test.ts` holds each one.

**The route line.** The route is drawn as a casing (blue, `ROUTE_BLUE`; slate
`ROUTE_CASING_CVD` in the colour-blind-friendly palette), the sections in the stress
colours, and nothing else. No one casing colour can be 3:1 from every class: contrast
depends only on luminance, the amber, greens and unrated grey need a casing darker
than about 0.045, and the traffic-free violet, LTS 4 and Avoid one lighter than about
0.5 (the test scans every luminance and finds the best a single casing reaches is
under 3:1). So each section carries a one-pixel halo, `route-halo` (a layer on the
sections' source, a pixel wider each side than its section, `haloWidth`, inside
the 11 px casing; it was 7 px between a 9 px casing and a 5 px line until item 274
widened the sections by class, "Stress salience" above; colour in the feature's
`halo` property, opacity set with the sections in
`setRouteSections`): the tier's own casing, which is dark under LTS 1 to 3, white
under LTS 4 and Avoid's own colour under Avoid (coral in the default palette, yellow
in `cvd`; with the switch on, black or white under the calm tiers, and a busy tier's
own casing, which the switch leaves: OWNER-DECISIONS 292), the unpaved casing under
an unpaved section (item 302: the route has twelve classes, the five unpaved ones
drawn in the brown ramp with the dotted mark over them, layer `route-unpaved`; since
2026-10-21 five more, gravel, `g1`-`g5`, in the grey ramp with the same mark, where the
API's section says `rough: false`), the
a dark neutral of its own under the unrated grey (#202326, since 357 softened LTS 1's
casing, which it was before), and white under the violet. The
figures below were computed from the colours by the test's rule. The blue stays outside as
the route's identity and is itself 3:1 from every base-map surface. The panel's route
legend draws the same halo.

| Class | default palette (halo, ratio) | colour-blind-friendly, switch on (halo, ratio) |
|---|---|---|
| Traffic-free #4c1d95 | #ffffff, 10.95 | #ffffff, 10.95 |
| LTS 1 | #2f5d47, 4.45 | #000000, 16.92 |
| LTS 2 | #1a2638, 4.82 | #0a1a2f, 5.79 |
| LTS 3 | #f28c28, 1.46 (reported, 351) | #0a1a2f, 3.83 |
| LTS 4 | #c81e1e, 2.34 (reported, 351) | #ffffff, 12.66 |
| Avoid | #111111, 3.62 | #f0e442, 14.93 |
| Not rated | #202326, 5.98 | #202326, 5.75 |
| Unpaved LTS 1 | #33231a, 11.01 | #000000, 12.61 |
| Unpaved LTS 2 | #1a2638, 4.86 | #2a200c, 6.02 |
| Unpaved LTS 3 | #f6ead2, 4.83 | #f6ead2, 4.91 |
| Unpaved LTS 4 | #f6ead2, 8.87 | #f6ead2, 8.30 |
| Unpaved Avoid | #f6ead2, 13.78 | #f6ead2, 13.45 |

The default palette's column is two-tone's since 351 (the warm palette's halos
are its casings, as in "Stress salience").

Against the blue alone the default palette was 1.09:1 (LTS 4) to 3.95:1 (LTS 1).

**Faint busy roads (z12-13, a road beside a bikeway, an alley).** `FAINT` keeps the
owner's 40% opacity and 60% width ("faint", OWNER-DECISIONS 76). That is 1.1:1 to
2.6:1 on the earth, and no faint line can be 3:1 without being the heavy line the owner
did not want. The second cue is a thin dark edge: the tier's casing layer, where the
line is faint, becomes a one-pixel ring around the line (`line-gap-width` equal to the
faint line's width) at `FAINT.edgeOpacity` 0.65 of the casing when that is dark, else
`FAINT.edge`. A ring, not a band under the line, so the tier's colour inside is not
muddied. 3.61:1 or more from every base-map surface in both palettes. `setStressPalette`
sets the gap too, since the switch changes the line widths. The trade: a faint road now
reads as a hairline outline rather than as a tint.

**Swatch borders.** `--swatch-border` (#7a808c light, #8b93a1 dark) for `.swatch` and
`.stress-bar`: 3.97:1 and 5.4:1 on `--bg`, 3.60:1 and 4.65:1 on `--bg-soft`. `--border`
(1.49:1 and 1.68:1) is unchanged, since it is also the panels' and inputs' border; the
switch still sets the swatch borders to the text colour, and forced colours to CanvasText.

Mutant pass on these changes (20 single-line mutants of the halo colours, the halo
opacity and wiring, the faint edge's colour, opacity, width, gap and alley rule, the
swatch tokens and the bar's border, the legend and the map layer): 17 killed at once;
the 3 survivors (the edge's width, the legend's halo stroke, the map layer's halo
colour) each got a test (`stressContrast.test.ts`) and are now killed.

## The rider and bike weight (OWNER-DECISIONS 313-318, 337-340, 352)

The weight is private. It is kept apart from the plan's dials, so it is in no link (an
older link's `sysweight` is ignored), no GPX download, and nothing the panel, the route
summary or the announcements say; only the request carries it, as the total in whole
kilograms (`system_weight_kg`, `lib/weight.ts` `withWeight` and `dials.ts` `dialFields`).

- **The panel** (`lib/weightDialog.ts` `WeightSetting`, at the top of the Traffic slider):
  the line "Rider and bike weight: not set, defaults used", or "... set today", "set 1 day
  ago", "set N days ago" (`weightLine`, by calendar day), and a Change button described by it.
- **The dialog**: a native `<dialog>` opened modal, named by its heading and described by its
  two lines (318); Escape closes it and the focus goes back to Change. Rider, Bike and Cargo
  and an editable Total, labelled pounds first and kilograms in brackets ("Rider, lb (kg)",
  316), with the kilograms a typed figure comes to in each field's description, said politely as it changes. A Total typed replaces the
  parts; a part typed recomputes the Total. Blank parts are the ride type's defaults
  (`defaultSplit`): rider 75 kg, bike 15 kg, no cargo (90 kg); Cargo with passengers rider
  75 kg, bike 30 kg and passengers 15 kg (120 kg). Every open starts blank (`openedState`);
  a saved weight is said to exist, with its date, never its numbers. Save replaces, Clear
  uses the defaults, Cancel keeps it. Save, Cancel, Clear and Escape all leave the dialog
  blank as it closes (the release re-check's S2: a closed `<dialog>` is still in the DOM,
  and an in-range Save used to leave the figures in it).
- **Range and clamp (337-340, 352).** Every total is taken. One outside 25 to 700 kg (55 to
  1,543 lb; 450 kg until 352 raised the top for "people who ride pedicabs with 2
  passengers") is planned at the nearer limit, silently: no note anywhere (352 removed 338's).
  The parts have no limits of their own, only that each is a non-negative number (339, 340),
  and the total alone is clamped, in the page (`dials.ts` `SYSTEM_WEIGHT_MIN_KG`,
  `SYSTEM_WEIGHT_MAX_KG`, `fitWeight`; `weight.ts` `toStored`) and in the API
  (`routemaker.effort.clamp_mass_kg`, the `RouteIn.system_weight_kg` validator, no `ge`/`le`).
  The effort model stays well-behaved to the top: an 8% climb's factor is 6.5 at 90 kg, 11.3
  at 450 and 12.2 at 700, flattening towards 1 + grade / CRR (14.3), so above about 450 kg
  routes barely change (337's "any end where routes stop changing"; tests/test_effort.py).
- **Where it is kept** (`WeightStore`): always in this browser (localStorage,
  `routemaker.weight`; for the visit only if storage refuses). There is no "remember"
  checkbox (the owner, 2026-10-19). Signed in it is also the `weight` key of the account's
  settings (`lib/accountSettings.ts`, checked by `core.accounts.settings_problem`, which never
  echoes it), so it follows the rider to another device; account settings win on sign-in as
  for the rest. Clear stores `cleared` (`WEIGHT_CLEARED`), sent as `weight: null`, so every
  signed-in device clears its copy instead of putting its own back; an account from before
  this keeps the device's. App passes `WeightStore.setting()` to `deviceSettings`, so a
  browser that refuses storage still syncs. Delete account erases it with the
  `AccountSettings` row. It is never in the plan setting, a link, a log or
  MCP output. The shape is `{name, totalKg, parts?, setAt}`, ready for named loadouts (315);
  `migrate` reads earlier shapes.
- **Tests**: `lib/weight.test.ts` (the line, the worksheet, storage, migration, never in a
  link or a GPX file, the saved number in no markup), the a11y harness's section 15 (focus
  in and back, the name and description, Escape, the saved number absent from the page and
  its accessibility tree after save and reopen), and `scripts/mutants_a11y.py`'s weight entries.

## Reversible lanes and the reference LTS 4 road (OWNER-DECISIONS 405, 408, 409, 411-414, 416, 419, 425)

**Two reversible-lane rules, one list** (425 split them). For the Mass Ride width,
`routemaker.agency_roads.counted_reversible(facts)` gives the reversible lanes of a District
block that count: none unless the block's BLOCKKEY is on `VERIFIED_REVERSIBLE_BLOCKS` (empty),
and none on a street in `ENDED_REVERSIBLE_STREETS` (Connecticut Ave NW, whose reversible
operation ended in 2020; DCist 2021-12-15) even then; `massflow.DcRules.reversible_lanes`
delegates to it (405: zero is the narrow, safe reading). For the LTS classifier and the
crossing stress, `classifier_reversible(facts)` counts every block's reversible lanes in each
direction, except on a street in `ENDED_REVERSIBLE_STREETS` (OWNER-DECISIONS 425: "Keep
counting them, probably in each direction in most cases. These tend to be high stress commuter
roads."; 16th St NW, Canal Rd, Clara Barton Pkwy, Chain Bridge Rd, Independence Ave). So one
lane each way and two reversible is three each way; a block with only reversible lanes gives
that count. Between 408 and 425 the classifier used the width's rule, which lowered lanes, and
the junction crossing cost, on roads whose reversible lanes still run. `settings.MASS_RIDE_DC_*`
must equal the module's lists
(`test_agency_roads.test_the_classifier_and_the_mass_ride_width_share_the_reversible_lists`).

Effect on the 2026-10-03 inputs, before the lane override below: Connecticut Ave NW north
of Calvert St (1 + 1 lanes, 2 reversible) read one lane a direction, not three; at 30 mph
and 17,000 to 28,000 vehicles a day the single-lane row plus the volume bump was still
LTS 4. Decision 412 now gives that road three lanes each way (next section).

**Connecticut Ave NW's lanes (412, 413, 414, 416).** North of Calvert St the street has
three travel lanes each way today ("Connect is 3 but one is sometimes used for parking,
though double and even triple parking also happens."): the old reversible lanes became
ordinary lanes. `fixtures/lane_overrides/2026-10-05-owner-connecticut-lanes.json`, read by
`routemaker.lane_overrides` as `pipeline.run.load_road_blocks` loads the District's blocks
(the one place a block's geometry and facts are together), sets a Connecticut Ave NW block
whose middle is at or north of 38.9235 N (Calvert St NW) to 3 + 3 (never fewer than DC
records), drops its reversible count (405's zero holds everywhere else) and marks one lane
a direction as part-time parking (`RoadFacts.part_time_parking_lanes`). The classifier and
crossing stress (`road_lanes`) count all three. The Mass Ride width
(`massflow._dc_block_width_m`) leaves the parking lane out: two lanes on the ride's own
side at DC's per-lane width, 9 ft, so 18 ft (5.49 m), 162 riders a minute (it was one
lane, 9 ft, 81, under 405's zero). Double and triple parking is a known hazard, not
modelled. It covers 44 of the layer's 61 Connecticut Ave NW blocks (the 2026-10-03 data):
those recording reversible lanes, and those north of Calvert St recording 2 + 2 or 3 + 2
(the far north, past 38.9625 N, reads 2 + 2 in the layer and now 3 + 3 by the owner's
"north of Calvert St", confirmed by 419: "The 3 conneticut lanes end at chevy chase circle"). Blocks south of Calvert St, including R St to Calvert St and the Dupont
underpass, are untouched. 413: K St to Dupont Circle stays LTS 3; the 411 corridor runs
from R St north.

**The Dupont Circle underpass (414, 416).** Between N St and R St the commuter traffic is
in the underpass, so the surface roadway and the service lanes around the circle are lower
stress (414): they are not in the 411 corridor and keep the classifier's tier (LTS 3 on the
2026-10-03 build). OSM tags the underpass's ten ways (the tunnel, layer -1, and its portal
ramps) `bicycle=no`, so the build bars them. The owner (416): "Bikes can pass underneath.
There's no sign to say they are prohibited. Underneath is LTS4." The access and stress rows
of `fixtures/overrides/2026-10-05-owner-dupont-underpass.json` set `bicycle=yes` and tier 4
on those ten ways (hidden, category other, no public note). Load them with
`load_overrides` before the rebuild (fixtures/overrides/README.md).

**Connecticut Ave NW, R St to Calvert St (409).** Rated LTS 3 because DC posts it 25 mph:
`stress.urban_two_way_floor` steps a two-way city street of two lanes a direction to LTS 4
only from 30 mph. The owner's "LTS4 north of R" is a named corridor
(`fixtures/corridors/2026-10-05-owner-connecticut-north-of-r.json`): the axis is DC's
centre line of blocks dc-4632193-0 to dc-4634051-0 extended 60 m past each end, the through
lanes within 10 m (the divided part's carriageways are up to about 8 m out), `along_m`
60 to 1,432. `tests/data/connecticut_ways.json` is the 2026-10-03 extract's ways there;
`test_corridors.test_connecticut_is_lts4_from_r_st_to_calvert_st_and_nowhere_else` holds
the 22 ways it lifts. Direction on a hill is FOLLOWUP-GRADE-STRESS, not here.

**The sentinel (408).** `pipeline.lts_sentinels`: the street's blocks by the agency's name
(`settings.REBUILD_SENTINEL_LTS4_STREET`, "CONNECTICUT AVE NW"), its segment rows by
`attr_sources->'blocks'` (the classifier records up to 12 matched blocks a way), lengths by
row (both carriageways of a divided stretch), a row's latitude at its middle, LTS 4 meaning
tier 4 or Avoid. VALIDATE_SEGMENTS (`pipeline.run.assert_reference_lts4_street`) refuses under 60%
overall or under 95% north of 38.9126 N (R St NW). Skipped, with a warning, when no agency
street layer is installed; refused when the layer has no block of that name; off with an
empty street (the suite's toy extracts, `tests/conftest.py`). On the 2026-10-03 build: 49%
overall (6.62 mi of rows, K St to Dupont Circle posted 20 and 25 mph is LTS 3) and 72% north
of R St; with the corridor about 67% and 99%. Tests: `tests/test_lts_sentinels.py`, and the
end-to-end pass, refuse and missing-street cases in `tests/test_pipeline_end_to_end.py`.

## Arterial calibration and the override re-match (2026-10-04)

OWNER-DECISIONS 282, 284-286, 294-296 and 303. Three pieces, each in its own
module, all applied by the rebuild (`pipeline.run`); docs/OPERATIONS.md, "AADT
smoothing, named corridors and the override re-match", has the reports and the
switches.

### Same-street AADT smoothing (`pipeline.aadt_smoothing`)

After the states are known and before CLASSIFY_STRESS reads a count, each count
is compared with the length-weighted median of the counts of the same street
(the name without its quadrant, `routemaker.streets.street_key`, in the same
state) whose way midpoints lie within 1,312 ft (400 m), where that window holds
at least 3 ways and 820 ft (250 m) of road. Service and trail ways neither vote
nor are smoothed. Lower only (303): a count is replaced only where the median is
lower, so a tier can fall and never rise. The link is classified on the median;
the segment row publishes the agency's count (`volume_aadt`) and, where the tier
fell, the tier on that count (`stress_unsmoothed_tier`, from
`StressResult.unsmoothed_tier`), which `core.junctions.roads_by_way` reads as
`GREATEST(stress_tier, stress_unsmoothed_tier)`. Anything that sets the tier
afresh (an override row, a named corridor, a closure to motor traffic) drops it.
The case it was built for: 1st St NW way 483241819, DDOT 10,665 between blocks at
7,520, LTS 3 to LTS 2 as a link (285), while the Q St junction is still rated
LTS 3 on 10,665. Tests: `tests/test_aadt_smoothing.py`,
`tests/test_arterial_stage.py`, and the segment-table reads in
`tests/test_junctions.py` and `tests/test_writers.py`.

### Named corridors (`routemaker.corridors`, `fixtures/corridors/`)

The owner's named stretches, matched by street name and position on an axis
(through within 23 ft (7 m) of it, side within 66 ft (20 m), within 40 degrees
of its direction, at least half the way's length in the entry's range), never by
way id. Applied at the end of CLASSIFY_STRESS, under the approved override rows.
Protected lanes, separate bikeways, path-class facilities and trail-class ways
are exempt (294). `load` refuses a missing folder. Tests:
`tests/test_corridors.py`, on the real North Capitol Street ways.

### The override re-match (`pipeline.rematch`)

Each override row in `fixtures/overrides/` carries a fingerprint (name, highway
class, length, a simplified line). At APPLY_OVERRIDES a row whose way is missing
is re-pointed only when every test holds: same name and class; each candidate at
least 90% within 20 ft (6 m) of the stored line and running within 30 degrees
of its direction; together covering 90% of it and adding up to its length
within a factor of 1.25; no two candidates side by side (their stretches of the
line overlap by no more than 49 ft (15 m), nor by half the shorter one, so this
holds on a line under 49 ft (15 m) too); no same-name way overlapping it by more
than an end-on neighbour; no collision with another row. Anything else fails,
with its reason, and the row stays as it was. Tests:
`tests/test_override_rematch.py`.

### Mutants

`scripts/mutants_arterial.py` runs a mutation pass over the three modules, the
corridor fixture and the stage wiring, against whole test files, one process at
a time (`--check` only checks that every mutant applies). It includes the
boundary mutants of ARTERIAL review r0 (each re-match, corridor and smoothing
threshold moved past its tested edge); every one is killed.

### Floor rows (OWNER-DECISIONS 445a-c)

A stress override row can be a floor (`"at_least": true` beside its `tier`;
`pipeline.overrides`): the rebuild rates the way max(the classifier's tier, the row's
tier), and where the classifier already meets it, the way keeps its own tier and reason and
the row is not counted as applied. The east-of-the-Anacostia file's Minnesota Ave,
Pennsylvania Ave SE (non-trunk) and Nannie Helen Burroughs Ave NE rows are floors
(445a-c). Without the key a row sets the tier, up or down, as before.

## Military areas (owner report 2026-10-05; OWNER-DECISIONS 330, 437)

`pipeline.restricted_areas.military_closures` runs in CLASSIFY_FACILITIES, after APPLY_OVERRIDES,
over every highway way and the `landuse=military` / `military=*` areas of the source extract.

- **Inside** is the share of a way's length inside the areas, at least `INSIDE_FRACTION` (0.5),
  by `_Shapes` (shapely: the outer rings less the inner ones; overlapping areas are unioned so no
  stretch counts twice; a stretch along the boundary is not inside). The cemetery, parking and
  park rules still count vertices (`_inside`).
- **Open inside a base**, and nothing else (437): a way an approved access override wrote a
  bicycle key on (`RebuildContext.bicycle_override_ways`, from `overrides.apply_access`), a
  numbered public road (`public_route`), the Pentagon's listed ways inside its reservation
  (`PENTAGON_OPEN_WAYS`), and `bicycle=designated` with no closing `access`, `vehicle` or
  `bicycle` key (`motor_vehicle=no` does not close a shared-use path), unless
  `DESIGNATED_BASE_ONLY` lists its id (438.1, 439: closed with its own reason). A way's own
  `access=yes`/`permissive` or `bicycle=yes`/`permissive` is listed as
  `WHY_TAGGED_OPEN` and closed.
- Closed ways are `rm:no_bicycle=military` (first in `trail_closures.ORDER`, on every graph);
  closed roads are left off the map. `military-closures.csv` lists every way with its share.
- **VALIDATE_SEGMENTS** (`run.assert_military_closures`): the three JBAB sentinels, a floor per large
  installation (`REBUILD_SENTINEL_MILITARY_MIN_CLOSED`, by OSM name, or a tuple of names held
  as one sum where outlines overlap, as Bolling's old outline and JBAB do; empty in the test
  settings), and `through_networks`: an open network inside a base that meets the bicycle-open
  network outside at two or more nodes refuses the build unless every way in it is open for a
  listed reason (`THROUGH_EXCEPTIONS`). A listed Pentagon way not seen open is warned about.

Tests: `tests/test_military_closures.py`, with `tests/data/military_through.json` (Fort Belvoir
and Fort Detrick, the open-by-tag ways that formed the through networks before 437, and their
outside neighbours) and `tests/data/military_edges.json` (Telegraph Rd, Russell Rd, South Fern St
and Saint Elizabeths Rd SE with their outlines clipped round them); the tile-build cases for a
closed tier-3/4 road with directional grants are in `tests/test_tile_build_access.py`.

## Secured federal compounds (owner report 2026-10-06; OWNER-DECISIONS 330, 446-446c, 447)

`pipeline.restricted_areas.secured_closures` runs beside `military_closures`, on the same
read of the source extract's areas, and judges every way inside a secured federal compound
by the military rule.

- **A secured compound** (`area_kind` returns `SECURED`, checked after `MILITARY`): an area
  `SECURED_AREAS` names by OSM id, or, by the tag rule (`is_secured_area`), a government
  area (`landuse=government`, `office=government` or `government=*`, not a building) whose
  own `access` is in `SECURED_ACCESS` (no, private, military, restricted, permit).
  `SECURED_AREAS` stays a short curated list of campuses whose internal roads and paths
  would look open and routable on the map (446c), each filed under a name of its own that
  holds if OSM renames it. At the 2026-10-03 extract the tag rule catches Goddard alone.
  `access=private` on a commercial, industrial or residential area is not caught.
- **Inside and open:** inside as for a base (at least `INSIDE_FRACTION` of the way's
  length). Open only for an approved override's bicycle permission, a numbered public road,
  a public road the outline takes in (`SECURED_PUBLIC_WAYS`: Good Luck Rd, Soil
  Conservation Rd, Brock Bridge Rd's bridge at Jessup, Slacks Rd at Sykesville), the
  public way in to the Goddard Visitor Center (`SECURED_VISITOR_WAYS`, 446) and a way
  signed for bicycles. A listed way
  is open only while its own tags do not close it, and a listed id renumbered upstream
  closes (err closed). A way inside both a base and a compound is the base's (`skip`).
- Closed ways are `rm:no_bicycle=secured`, after `military` in `trail_closures.ORDER`, on
  every graph; closed roads are left off the map. `secured-closures.csv` lists every way
  (the military report's columns, `facility` for `installation`), and `secured_missing`
  warns about a listed outline the extract no longer has.
- **Through networks:** `run.military_through_networks` runs a second time over the secured
  ways. Every reason a secured way can be open today is in `THROUGH_EXCEPTIONS` (override,
  numbered route, the listed public roads, the Visitor Center ways, signed for bicycles),
  so this check cannot refuse a build yet; it guards an open reason added later.
- **VALIDATE_SEGMENTS** (`run.assert_secured_closures`): the Rowley sentinel ways
  (`REBUILD_SENTINEL_SECURED_CLOSED_WAYS`, closed where the extract has them; a missing one
  is warned about) and a floor per compound (`REBUILD_SENTINEL_SECURED_MIN_CLOSED`, by its
  `SECURED_AREAS` name, or OSM's for Goddard), about three quarters of the 2026-10-03
  count, so an outline lost or renumbered upstream fails the build instead of reopening the
  compound.

The correctional department's land at Sykesville (w736540664, "Sykesville correctional
land") is listed under the err-closed default (447) while the owner's answer is pending:
60 ways, 7.3 mi (11.7 km) closed, floor 45; Slacks Rd, the county road through it, stays
open. Take the entry out of `SECURED_AREAS` and its floor out of settings if the owner
says to open it.

Tests: `tests/test_secured_areas.py`, on real ways (`tests/data/secured_areas.json`,
`tests/data/secured_goddard_jessup.json`, `tests/data/secured_sykesville.json`); the
wiring through the rebuild stages (report, skip, through check, map) in
`tests/test_pipeline_end_to_end.py`
(`test_a_secured_compound_is_closed_reported_and_left_off_the_map_through_the_rebuild`).

## Car-free bike roads on the map (OWNER-DECISIONS 442)

`facility.map_class` draws a trail-class way signed `bicycle_road=yes` or `cyclestreet=yes`
(`BICYCLE_ROAD_KEYS`) with no bicycle tag as a road (`facility.is_bicycle_road`), as on the
car-free piece of Beach Drive (way 24976160, `highway=pedestrian`), which had read as a
trail a bicycle may not ride and was left off the map. The map only: the facility class,
which routing reads, and access are unchanged, and the closed-access check (`access` or
`vehicle` closing it with no bicycle or foot tag reopening it) runs first, so a private one
stays hidden. Tests: `tests/test_facility.py`.

## Hard surfaces (OWNER-DECISIONS 440)

`routemaker.surfaces` is the one definition of a paved surface. `is_paved` is the
map's (but for a judged short bridge, drawn in its trail's surface: `core.stress_tiles.
BRIDGE_UNPAVED`, docs/OPERATIONS.md "Short bridges") and the segment table's reading (`stress.is_unpaved`, `inferred_unpaved`) and the
graph's (`lua/routemaker_remap.lua`, `M.PAVED_SURFACES` and `M.PAVED_PREFIXES`, kept
equal by `tests/test_surfaces.py`): road paving and its `:` variants, wood and
`boardwalk`, metal and `metal_grid`, brick, bricks, sett, tartan, rubber, cobblestone and
unhewn cobblestone. The two cobblestones are also rough (`stress.is_rough`), so a road
on them floors at LTS 2 as a dirt one does.

Two narrower readings keep access where it was:

- `is_sealed`, road paving only, is what lets a rated way out of singletrack
  (`singletrack.is_paved`). A wooden ladder, berm or skinny rated `mtb:scale` 1 or more
  is a mountain-bike feature whatever its class: The Boss Trail's wooden features are
  `highway=cycleway`, and the jump lines `bicycle=designated`. A wooden trail bridge
  rated 0 (the Rock Creek Trail's) was never singletrack.
- `is_hard_for_access` is the no-bike-path rules' hard-surface exemption
  (`trailaccess.is_hard_surface`): every paved surface but wood, which counts only on a
  bridge or boardwalk that is a cycleway or `bicycle=designated`. A wooden footbridge on
  a hiking path keeps its `foot_designated`, `hiking_route` or `sac_scale` closure.

Valhalla (3.5.1 to 3.9.1) prices `surface=wood` and `boardwalk` as `compacted`, the gravel class,
and `brick` and `bricks` as `paved_rough`. The remap hands those four to the graph as
`paving_stones` (`M.GRAPH_SURFACE`), which it prices `paved`, before any reviewer surface
penalty (which still wins). A paved way's mountain-bike rating comes off as before
(`M.strip_paved_ratings`), now on a wooden deck too, which only ever removes the
parser's access grant; a rated wooden feature is closed by `rm:no_bicycle=singletrack`.
`scripts/check_tile_build_access.sh` reads each hard surface's price in a real tile.

## Roads closed or restricted to motor traffic (owner report 2026-10-06, the WB&A Trail)

`stress.motor_restriction` caps the tier of a road whose motor traffic is barred or
limited, so the class's default speed (35 mph on an unclassified road) does not set it.
The most specific of `motorcar`, `motor_vehicle` and `vehicle` decides; with none of
them, `access` decides where the way's own bicycle tag keeps bicycles on it. `no`,
`agricultural` and `forestry` cap at LTS 1; `private`, `destination`, `permit` and
`delivery` at LTS 2; a posted limit above 30 mph raises the cap one tier. It only lowers,
is skipped where a traffic count is known, and leaves a way closed to bicycles too to
the tables, since there is no ride on it to rate (444): a `bicycle` tag outside
`BICYCLE_ALLOWED_VALUES` (`no`, `private`, `dismount`, ...; `use_sidepath` is legal,
review RL-1), or, with no
bicycle tag, an `access` or `vehicle` that is not a public value. It changes no access: the rule text says why the tier is low, and
the rough-surface floor still applies after it. Bragers Road (way 11507607) on the
WB&A Trail is the test case.

## The route chart (OWNER-DECISIONS 322, 323, 325, 328-333, 387, 394, 396, 397, 399, 400)

The "Elevation and stress" fold of the route summary, and on a Mass Ride "Riders per
minute, corker load and elevation" (three charts; see "A Mass Ride's three charts" below).
Built on `wip/elevation-chart`; the capacity map (part 1 of 387) and
the rider-marked hazards (part 3) are not part of it. Both folds stay: the chart's sits
above "Stress and facilities" (decided, 394: "keep both").

**The API contract.** `RouteBody.profile` (`core.api.ProfileOut`, additive, null where no
leg had any elevation), built by `core.routing.route_profile`:

- Parallel arrays, one entry a router sample: `m` (metres along the route), `elevation_m`,
  `grade_pct` (signed, positive uphill), and `climbs`. The samples are the router's own
  per-leg `elevation`, every `routing.ELEVATION_INTERVAL_M` (30 m: 3DEP at 1 arc-second is
  about that on the ground, so a finer interval would read one cell twice). A leg's sample
  `i` is at the leg's start plus `i x 30`, never past the leg's end; the first sample of
  the next leg is at the same distance, so a joint is two samples at one place. A leg the
  router gave no elevation for is a gap, a null height at its start and end, so no grade,
  climb or line is read across it. The legs' starts are the sums of the legs' summary
  lengths, which is the router's length, not the traced pieces' (`stress_spans` use the
  traced pieces; the two differ by metres).
- `grade_pct` is the rise over the window of two samples either side (`routemaker.profile`
  `GRADE_SPAN_SAMPLES`, four samples, 120 m). The grade between two neighbours is mostly
  noise (3 m over 30 m is 10%), so a one-cell blip is smoothed and a real 5% hill is not.
- `climbs` are `routemaker.climbs.runs` (the sustained climbs the hills slider prices, with
  its dip and flat tolerances) kept where they average 3% or reach 5%: `from_m`, `to_m`,
  `gain_m`, `avg_grade_pct`, `max_grade_pct`, and `tier` (the highest LTS of the stress
  sections they ride).
- On a Mass Ride only: `riders_per_min` (one per sample, null where the width is not
  known: an untraced leg, an unrated segment, or a stretch marked Avoid), `flow`
  (`narrowest_riders_per_min`, `narrowest_m`, `typical_riders_per_min`, the median), each
  climb's `capacity_drop_pct` (the most it takes off a stretch) and `min_riders_per_min`,
  `avoid` and `unchecked` (the stretches marked Avoid, and those on an untraced leg, as
  `{from_m, to_m}`: the stretches' own ends, summed along the route, not their first and
  last samples, so a 20 m Avoid between two samples keeps its range), and `crossings`.
  `crossings` is null where the junctions were not read (over budget, a deadline, a
  failed read): the chart says "not checked", never "none", which is `[]`.
  `crossings_complete` is false where only the flagged junctions could be read (finding
  the busy-road ones failed): the summary and the table caption say once that only the
  higher or very high stress junctions were found, so the list may be incomplete; the
  scrub's sentence names them so ("Next higher or very high stress junction: ...") without
  repeating the caveat at every arrow press.
- A Mass Ride's riders are read at more places than the heights (`routing._flow_samples`):
  a pair of samples at each place the width or the note changes (the end of one stretch
  and the start of the next, at one distance), so a one-block bottleneck is never stepped
  over and the line steps where the width does; and one every 30 m along a leg the router
  gave no heights for (a null height, a figure all the same). The climbs are found on the
  height samples alone; the typical figure is the median of the regular samples only.
- Cost and size: `climbs.runs` is found once and shared; each climb's samples are found by
  bisection and the climb distance by one pointer, so the profile is about linear in the
  samples. Its time is in the plan's "joins" warning ("the chart's profile N s of them").
  Every figure is worked out on every sample, then a route of more than
  `profile.MAX_SAMPLES` (2,000, about 60 km or 37 mi) is thinned to close to that many
  (`profile.thin`: each window keeps its steepest grade, its highest and lowest heights,
  its lowest riders figure and its first gap), so the grade bands, the summits and valley
  floors, the bottlenecks and the gaps survive. On a Mass Ride the first and last sample
  of every run under 60 riders a minute are kept as well (`profile._bottleneck_ends`, at
  most a quarter of the limit, else none), so the bottlenecks table's lengths are the
  unthinned ones on a long route. The window is first sized for the most picks a window
  can make (4, or 6 on a Mass Ride) in what those ends leave, then narrowed by bisection
  to the narrowest that keeps the picks actually made within the limit.

**The flow model** is `routemaker.flow`; there was no flow code before it, only PLAN's
"The headline number: modelled throughput". It is accepted as the working model
(OWNER-DECISIONS 394); FOLLOWUP-FLOW-CALIBRATION's literature check is in
docs/FLOW-CALIBRATION.md, its references in docs/SOURCES.md ("The Mass Ride flow
model"), and the owner's video check is pending. The level figure rests on the owner's
DC Bike Party counts (item 173, indicative, good to about ±25%, item 175); the grade
factors are not from a measurement.

- Level capacity: `60 x 0.37 riders/m2 x 0.7 utilisation x usable width x 1.9 m/s`, about
  99 riders a minute for an 11 ft (3.35 m) lane.
- Usable width: the segment's through lanes a direction (`road_lanes`, one where the table
  has none) times 1 for a one-way street or 2 for a two-way, times 11 ft (3.35 m); about
  10 ft (3.0 m) for a path; none for an unrated segment, and none for a stretch marked
  Avoid (325: "no carrying capacity"; the chart and the sentence say "Avoid").
  `classify` reads `road_lanes` and `road_oneway` into `PieceClass.lanes` and `.oneway`
  (NULL columns where the live schema predates the trait columns, as
  `core.junctions.has_trait_columns` says). Parking and painted bike lanes are not in the
  width, so the figure errs low.
- Grade (328(b)): the climbing pace is `1 / (1 + 12 x (grade - 1%))` of the level pace
  (63% at 6%, 54% at 8%, never under 30%), taking `KICK_M` (150 m, the climbs module's
  free stretch) of climbing to set in, linearly, so a short ramp costs little and a long
  climb the whole figure; a descent past 4% spaces the group, the density falling to
  `1 / (1 + 5 x (grade - 4%))` (83% at 8%, never under 60%). The pace is not raised.
- Bands (326, 327): under 60 bottleneck, 60 to 120 tight, 120 to 200 good, 200 and up wide
  open. `flow.BAND_EDGES` and `flow.BAND_WORDS` are the one source: the front end's
  `FLOW_BANDS` is held to them by `tests/test_profile_flow.py`.

**The flow API** (one module since the rebuild bundle: `routemaker.flow` is shared by the
route chart, `routemaker.massflow`, the route's sections and the tiles):

- The width a group has is the segment table's `mass_usable_width_m`
  (`routemaker.massflow.usable_width_m`, written by the rebuild: the ride's own direction,
  parked cars out, DC's Roadway Block first; OWNER-DECISIONS 404-407). The route chart reads
  it per piece (`core.routing.PieceClass.width_m`; `_flow_stretches` with `capacity`, which is
  true for a Mass Ride on a table that has the column), so the chart and the capacity map
  always agree. Riders are made from the width when served, so a change to a constant
  reaches the map and the chart without a rebuild.
- `usable_width_m(tier, facility, lanes, oneway) -> float | None`: the ESTIMATE, metres,
  used only on a table without the column. `tier` may be the router's text key ("1"-"5",
  "unknown") or the pipeline's int (1-5, None); tier 5 (Avoid) and unrated give None.
  `lanes` is through lanes a direction, and the estimate is that one direction's lanes x
  11 ft (406: own side only; `oneway` no longer doubles it). Before the bundle it took both
  directions of a two-way road, so `tests/test_profile_flow.py`'s two-way cases changed
  from 13.4 m to 6.7 m (2 + 2 lanes) and from 6.7 m to 3.35 m (no lane count).
- `level_riders_per_min(width_m) -> float`: the level figure (unrounded). The tiles'
  `RPM_PER_METRE_SQL` is `level_riders_per_min(1.0)`, as now.
- `grade_factor(grade, climbed_m=0) -> float`: `speed_ratio x spacing_ratio`, 0.3 to 1; 1
  where the grade is None. The grade is signed in the direction ridden and `climbed_m` is
  metres into the sustained climb, so it applies along a route at query time, never in a
  per-segment column.
- `riders_at(width_m, grade, climbed_m=0) -> float`: `level_riders_per_min(width_m) x
  grade_factor(...)`, unrounded; `adjusted_riders_per_min` is the same under its old name.
- `per_sample(samples, grade_at, stretches, runs=None) -> (riders, level)`: floats or None
  per sample, from `(metres, width)` stretches in the order ridden; `stretch_index` and
  `climbed_along` are its parts.
- `BAND_EDGES`, `BAND_WORDS`, `band_index`, `is_avoid`, `tier_number`.
- `massflow` uses `UTILISATION`, `PACE_MS`, `LANE_WIDTH_M`, `level_riders_per_min`,
  `BAND_EDGES` and `BAND_WORDS`; the tiles' SQL uses `level_riders_per_min(1.0)`.

**Major junctions** (333 as 396 redefines it) are
`routemaker.intersections.major_crossings`: every flagged event (a junction with a stress
rating), and every other junction whose crossed or joined road is LTS 3 or higher, whatever
its control (`busy_roads_at`). "Joined" is the road turned or run onto from another one,
not the rider's own road going on and not straight on from one busy road into the next
(as `cost_of` judges joining). So a signalised right onto an arterial, and a busy cross
street passed while riding along a busy road, are marked though group mode makes no event
of them. One junction gives one major, for its busiest road; one at the same node as one
already counted, or of the same street (or an unnamed one) within `MERGE_WITHIN_M`, is the
same junction; an unnamed major (a path crossing) does not hide a named busy road beside
it, and only the majors within `MERGE_WITHIN_M` are looked at (bisection). `kind` says why
(`flagged`, `crossing`, `joining`), and `corkers_needed` is true where the crossed or
joined road is LTS 3 or worse (item 142; 400: a turn onto a busy road needs corkers as a
crossing does). `Major.crossed_tier` (the API's `crossed_tier`) is that road's tier. There is no lane counting and
no stop-sign rule. They ride beside the events as `RouteEvents.majors`
(`core.junctions.with_majors`, Mass Ride only), which falls back to the flagged events
(`majors_of_events`) if finding the majors fails, so the planner's own junction events
always survive; where the events were merged into a plain list (a long plan's reads) the
flagged ones alone are used. Both fallbacks are marked incomplete (`RouteEvents.complete`,
and `plan()`'s own), sent as `crossings_complete: false`. They are not extra events: the description, the refine search
and the junction list never see them.

**The front end.**

- `lib/profileChart.ts` holds every decision, tested without a browser
  (`lib/profileChart.test.ts`): the chart kind, the grade bands (each with a pattern), the
  riders bands (colours, words, patterns), the scales, the shapes (elevation line and area,
  band polygons, the riders area cut where it crosses 60/120/200, rising or falling), the
  stress strip's sections (with their facility and surface), the nearest sample, the keys'
  steps and jumps, the point on the map, the sentence at a position (`readingAt`, with
  `ridersWords` and `crossingClause`), the summary, the climbs, bottlenecks and
  intersections tables' rows, the narrowest point's mark, and the thinning of junction
  names (`placeCrossings`). Units come from `format.ts` (`formatAxisDistance` was added
  there: nothing else writes a unit).
- `ElevationChart.tsx` draws it for every ride type but Mass Ride, and hands a Mass Ride to
  `MassRideCharts.tsx` (below); what the two share (the plot's edges, the patterns, the
  junction shapes, the tables) is in `chartParts.tsx`. The picture is one `role="slider"` with `aria-valuetext`
  the spoken sentence at the keyboard's (or a click's) position, never the hover's, and
  `aria-describedby` the key hint alone (the summary is the text just before it). Its SVG
  is `aria-hidden`, and so is the visible readout under it, which follows the hover: a
  live region beside the slider would say everything twice. Left/Down and Right/Up step,
  Page keys step five, Home and End go to the ends, C and Shift+C go to the next and
  previous climb, and on a Mass Ride I and Shift+I to the next and previous major
  intersection. Hovering or touching reads the same, a click or a touch pins the position;
  focus shows the marker and leaving hides it, keeping the position for the return. The
  tables are behind a closed "Climbs as a table" (on a Mass Ride "Climbs, bottlenecks and
  intersections as tables"), with captions and header cells. C and I read the Shift key,
  not the letter's case, so Caps Lock does not reverse them. A source line under the
  chart cites USGS 3DEP and, on a Mass Ride, OpenStreetMap lane counts and DC Bike Party
  counts ("indicative (level roads about ±25%; hill adjustment not yet checked)"). The
  summary's stress shares and the climbs' Stress column say the map's class
  ("traffic-free path", "unpaved, LTS 2"), as the key and the sentence do; a path rated
  Avoid is "Avoid" ("unpaved, Avoid"), as `routeColours.spanClass` draws it.
- `App.tsx` puts the fold first in the route summary (`ROUTE_FOLDS.elevation`; "Stress and
  facilities" stays after it), open beside the map and closed on a small screen
  (`sidebar.chartFoldOpen(narrow)`). `scrubPoint` goes to `MapView`, which draws the
  `.scrub-marker` (a ring with a cross, dark outside and white inside: a shape, not a
  colour; `aria-hidden`; not in the tab order) and eases the map to it if it leaves the
  screen (kept: OWNER-DECISIONS 399, "auto pan").
- Colour is never the only cue: the 5% to 8% band is amber with dark dots and the
  8%-or-more band amber with a hatch; the strip's tiers carry the stress bar's patterns,
  a path is drawn in the map's path colour and an unpaved stretch in its brown with dots;
  each riders band has a pattern of its own (cross-hatch, diagonal, dots, horizontal
  lines); Avoid (397) is magenta #d6008f, the route line's own Avoid, with dark chevrons,
  a two-tone frame (near-black outside, white inside: one tone is 3:1 from any band or
  panel, which no single fill can be) and a white AVOID at the 11-unit type (4.9:1), or
  "A" on a block under 36 units (drawn at least 10 wide), listed in the key ("Avoid (A
  where narrow)") only when the route has some; the route panel's stress bar draws it in
  the same magenta with its near-black cross-hatch (the "Stress and facilities" list's
  "Avoid 0%" row, on a route with none, keeps the palette's Avoid colour), and the route
  line's paved Avoid has a
  white dash-dot down its middle (`routeColours.ROUTE_AVOID_MARK`, the route-avoid layer),
  so it is not told from LTS 3 by colour alone in the high contrast palette; the
  narrowest point is a downward triangle with its figure; junction markers are a triangle,
  a diamond and a dot, each named in the key and the table. The guides' figures are in the
  text colour beside a band-colour swatch; their lines are 3:1 on the panel (the light
  theme's orange is #b45309). In forced colours the chart and its key keep their colours,
  the key's swatches framed in CanvasText, and the chart's words and line are CanvasText;
  the Avoid block's outer frame is CanvasText and its inner frame Canvas.
  The chart's type is 11 viewBox units.

**A Mass Ride's three charts** (the owner, 2026-10-10: "Have 3 charts for mass ride: Riders
per minute, Corker load, Elevation. They should all be there."; 147: "visualize rider flow,
elevation, and anticipated corker requirements over the route"). `MassRideCharts.tsx` draws
three charts in that order, one under the other, each 360 viewBox units wide with the same
plot edges (`chartParts.LEFT`, `RIGHT`) and the same distance scale, so a mile is at the same
place on all three and on each one's own distance axis (miles, km in brackets).

- **Riders per minute**: the riders area in the band colours and patterns, the 60/120/200
  guides, the narrowest point's caret and figure (147's "with the bottleneck marked"), the
  Avoid blocks, as before, and the ride size's requirement (below).
- **Corker load**: a step area (one series: a blue fill under a step line in the text
  colour), a tick from the marker row down through the plot at each junction needing
  corkers, the junction markers (triangle, diamond, dot) above, their thinned names under
  it (`placeCrossings`), a dotted line at half the top, and the side's top figure in
  corkers held at once ("4", "corkers", "at once"). A stretch not checked for intersections
  (`profile.unchecked`) is a grey hatched block with a dashed frame and "NOT CHECKED" (or
  "?" where narrow); intersections not checked at all (`crossings: null`) draw no area and
  say "Intersections not checked" in the plot, never a load of 0 (an older answer with no
  cruising pace says "Group length not known").
- **Elevation**: the elevation line and area with the amber grade bands, dotted and hatched.

**The corker load rolls with the length of the ride.** The owner, 2026-10-10: "Corkers were
intended to also have a rollback based on the length of the ride." So the window is the
group's length at the anticipated ride size, slid along the route (PLAN "Corkers needed",
139's "at once"), and the chart is **the corkers held at once with the group's head at each
point** (`lib/profileChart.ts`, "The corker load"):

- **Anticipated ride size** (128, 129): a slider in the Mass Ride dials, after Hills,
  100 to 2,000 riders in steps of 50, 500 by default (`dials.ts` `RIDE_SIZE_*`). Its name is
  "Anticipated ride size (riders)" and its value text "500 riders"; it is an `input
  type="range"`, so the arrow keys, Page Up/Down, Home and End move it. It is kept with the
  other dials: in the plan link as `riders=N` (absent at 500, so older links read 500), and
  only on a Mass Ride (`fitDials`). It never reaches the API: App leaves it out of the dials
  a plan is made from, so moving it redraws the corker load and plans nothing.
- **The group's length**: riders ÷ (cruising density × usable width), which is riders over
  the flow a second times the cruising pace. Nothing is copied into the front end: the API
  sends `profile.level_riders_per_min` (the level figure at each sample, from the width
  alone, `flow.level_riders_per_min`), `flow.cruise_pace_ms` (`flow.CRUISE_PACE_MS`, 7 mph)
  and `flow.default_level_riders_per_min` (two 11 ft lanes, `flow.GROUP_DEFAULT_WIDTH_M`);
  `flow.group_length_m` is the same rule in Python. 500 riders on a 22 ft (6.7 m) road at
  7 mph are about 1,560 ft (474 m); 2,000 about 1.18 mi (1.9 km), PLAN's worked example.
- **The width at each point** (the choice made here): the group fills the road behind its
  head until the road holds every rider (`groupRoad`, `tailAt`), so it is shorter on a wide
  avenue and longer on a narrow street, and across a change of width it is in between.
  Where no width is known (Avoid, an untraced leg, outside DC) the route's median level
  figure stands in, and with none at all the default road. Before the start the group is
  still forming, at the first stretch's width; past the end, at the last one's.
- **Held at once**: a junction needing corkers (`corkers_needed`: 142 and 400, a crossing of
  or a turn onto an LTS 3 or worse road) is held from when the head reaches it until the
  tail passes it, so the load steps up at each tick and down a group's length later
  (`exitOf`). Corkers held at once = the junctions in the window × the corkers each needs
  (`corkersFor`, PLAN 139): **one for each approach lane** of the busy road, or **one an
  approach at a traffic signal**, whatever its lanes, since the red already holds the cross
  traffic and the corker covers the change to green (the group goes through as one once
  its head enters on green, 124). The approaches: **2 for a two-way road, 1 for a one-way**
  (crossings carry `oneway`, from the road's OSM tags), **and 2 where it is not known** (no
  mapping, or an older answer). A divided road (two one-way carriageways counted as one junction, by the refuge merge or by name within 45 m) has 2: crossings carry `divided`, which leaves `oneway` as the junction costs read it. The lanes: crossings carry
  `approach_lanes`, the road's through lanes a direction (`Road.lanes`; a divided road's
  busier carriageway), and **1 where not known**, so an older answer counts as before. So a
  four-lane two-way road with no signal takes 4, the same road at a signal 2, a three-lane
  one-way street with no signal 3. The intersections table says each junction's count and
  how it was counted ("4 needed: 2 approaches; 2 lanes each", `corkerBasisWords`), and the
  scrub says the count ("Next: 14th St at mile 1.3, 2 corkers needed"). Near the end
  the junctions stay held to the end, so a group longer than the route holds every one at
  its end.
- **The ride's headline**: "about N corkers" = the most held at once × the rotation factor
  (2: corkers leapfrog to the junctions ahead), rounded up (`ROTATION_FACTOR`). It is in the
  chart's summary and in the route's figures beside the carrying capacity ("Corkers: About 8
  for 500 riders", `corkerFigure`, `CapacityStats`). Where only the flagged junctions were
  found (`crossings_complete: false`) or part of the route was not checked, it is "At least
  about N ... (may be low: ...)", never a firm figure.
- The top is the peak rounded up to an even number, at least 4.

**The ride size's requirement on the riders chart** (128: the ride size sets "how long it
holds intersections and the flow it needs; ... a road whose throughput is too low for the
size is flagged"; PLAN "Route profile (item 147)": "the requirement for the chosen ride size
(item 128) drawn as a line"). The group holds a junction for its riders over the flow, so a
road needs the ride size over the longest hold accepted, `RIDE_HOLD_MINUTES` (5, a proposal):
`rideNeed` is riders ÷ 5, rounded up, so 100 a minute at the default 500 (about one 11 ft
lane, 99), 20 at 100 riders, 400 at 2,000. It is drawn across the riders chart as a long
dash in the text colour over a casing in the panel's colour (one of the two is 3:1 against
every band), with "100 needed for 500 riders" at its left, told from the dotted band guides
by its dash and its words; the axis rises to fit it (`ridersTop`). The key says "Dashed line
(proposed): about 100 a minute, what 500 riders need to pass a junction within 5 minutes"; the summary
says the hold is a proposal, not yet confirmed, and how much of the route with a figure is below it and from where (`needSentence`,
`belowNeed`: a stretch counts by the mean of its two samples; Avoid, untraced and outside-DC
stretches have no figure and are not counted); the scrub adds "below the proposed 100 needed for
500 riders" to the band words where the figure is under it. It moves with the ride size slider
and is never sent to the API; routing does not use it yet (PLAN "The main control": the
flagging on the map and the routing penalty by ride size are not built). Forced colours: the
line follows the system's text colour and its casing the system's background.

Defaults still open for the owner: the rotation factor (2, PLAN's proposal), 2 corkers per
junction where it is not known whether the road is one-way, 1 lane an approach where the
lanes are not known, the signal rule applied at every signalised junction (the group enters
on green, 119 and 124), the 5-minute hold behind the requirement line, and the 500-rider
default (PLAN's proposal; the range is the owner's, 129). Complex junctions (a traffic
circle, a diagonal avenue meeting the grid) are still counted as one road's approaches, not
by their actual approaches.

Screen readers: each chart is a `role="group"` named by its `h4` heading, with its own
summary before the picture, a slider (`aria-label` "Riders per minute along the route",
"Corker load along the route", "Elevation along the route") over an `aria-hidden` SVG,
an `aria-hidden` readout, and its own key (`aria-label` "Riders per minute key" ...). The
three sliders share one position (and one key hint, which also says so): Tab from one to
the next carries on at the same mile, and moving any of them moves the map's marker and the
other two charts' markers. Tab between them keeps the position (the blur looks at
`relatedTarget`), so the map's marker neither flickers off nor pans again. Value texts: riders, the sentence as before ("Mile 1.2: grade 6%,
about 90 riders per minute (tight, slowed by the climb, below the proposed 100 needed for 500 riders).
Next: 15th Street Northwest at mile 1.3, 2 corkers needed."); corker load, "Mile 1.2: 2 corkers holding 1 junction at once (500
riders, group about 1,560 ft (475 m) long). Next: ..." (with "Part of the group's stretch was
not checked for intersections." where it was not, and "intersections not checked, so the
corkers needed are not known" with no crossings; where only the flagged junctions were
found, every reading says so too: "Mile 1.2: at least 2 corkers holding 1 junction at once
(500 riders, group about 1,560 ft (475 m) long; only flagged junctions were found)", and the
key adds "Only flagged junctions were found, so the load may be low"); elevation, "Mile 1.2: elevation 341 ft (104 m), grade 6%."
The summaries split the old one: riders (narrowest and typical figures, outside DC, Avoid,
and "Part of the route could not be traced, so its width is not known." where it was not),
corker load (the intersections and how many need corkers, the group's length at the ride
size, the most held at once, where, and how many more places reach it, the ride's corkers,
and how they are counted; with no junction needing corkers it says "No junction needing
corkers was found where the route was checked." wherever part was not checked, never that
none are needed), elevation (range, steepest, climbs); `summaryText(.., "mass")` is
unchanged, pinned word for word in the tests. The key names the dotted line ("Dotted line:
2 corkers at once, half the chart's height"). The intersections table gains a "Corkers held at
once when the head reaches it" column ("4 at 2 junctions", or "None"). Colour is never the only cue: the load is
one series with its line, the ticks are shapes at places, the unchecked block has a hatch,
frame and word; in forced colours the step line, ticks, half line and the unchecked frame
and word follow CanvasText. Every other ride type keeps "Elevation and stress" unchanged.

**Deploying it.** Code only: no migration, no data rebuild, no new setting.

- Localhost: tag the running image first, so a rollback is a retag and not a rebuild
  (`TAG=dev` is mutable): `docker tag ghcr.io/macrophage87/routemaker-api:dev
  ghcr.io/macrophage87/routemaker-api:pre-elev`. Then rebuild the api image (the `api`, `worker`
  and `migrate` services share it, and the code is baked in, not mounted), `up -d` them, and
  rebuild the front end into `${DATA_ROOT}/frontend`. Rollback: retag `pre-elev` as `dev`,
  `up -d` again, and put the previous front end back.
- Beta: the sha-tagged image and `scripts/beta/ship-data.sh --build-frontend`, as in
  docs/BETA-RUNBOOK.md; rollback is the previous sha tag and the previous front end.
- Order is free: an old front end ignores `profile`, and a new front end without it shows
  no chart fold (`usableProfile`). Nothing is cached across a deploy (the profile lives in
  one request; saved routes store points, not bodies).

**Tests.** `tests/test_profile_flow.py` (profile, grades, gaps, climbs and their keep
rule, every flow figure, floor, edge and the linear set-in, the widths for int and text
tiers and Avoid, the band parity with the front end, the thinning, the route profile
builder with Avoid, untraced and unchecked, and the 396 major junctions and the fallback),
`tests/test_route_api.py` (the contract key, the answer's profile, a Mass Ride's riders,
and a 2-lane one-way's width end to end), `lib/profileChart.test.ts`, the sidebar tests
(`chartFoldOpen`), and section 19 of the a11y check (45 checks: the fold, the slider's
role, name, key-hint description and value text, the summary, the patterns and the strip's
path, the arrow, C, Home and End keys, a hover leaving the spoken value alone, the map
marker, the position kept, the tables and their names, a phone's collapsed fold and fit,
and the Mass Ride chart's area, patterns, guide colours and contrast, the narrowest mark,
Avoid, thinned names, sentence, I key and tables, and forced colours; and five more for a
Mass Ride's three charts: the groups, headings, slider names and keys in order, the corker
load's summary, its area, ticks, side figures, key and shared axis, and Tab on to the corker
load's and the elevation's sliders at the same mile with their value texts; and three for
the ride size: the slider's name, value text and range, the route's corkers figure, and ten
steps to 1,000 riders redrawing the load and the figure, carried in the link, with no new
plan; and two for the corker load not known: crossings `null` (the plot's words, no area, the
key, summary and value text, no corker figure) and an unchecked stretch (the hatched NOT
CHECKED block, its key, and "At least about 8"); EXPECTED 422 after the release merge).
`node scripts/a11y/check.mjs --port <vite> --cdp <chromium>` (or `A11Y_CDP_PORT`) runs it
against a Vite and a Chromium of your own; Chromium's port defaults to 9222. The three charts' math is in `lib/corkerLoad.test.ts` (the group's
length and the worked example, the width at each point, an unknown width and an older
answer, the sliding window, close junctions adding up, the ends, a group longer than the
route, one-way junctions, junctions needing none, the headline and its rounding, may be low,
no intersections, not checked, unchecked stretches with no corkers, the partial caveat in
the reading, the readings and summaries, the one-chart summary as a literal, the riders
summary's untraced width, the shapes, the table's column, and the ride size's range, plan
link and slider);
`tests/test_profile_flow.py` checks the group length's worked example, the level figure and
pace the API sends, and a major's `oneway`. `scripts/a11y/cdp.mjs` mocks a profile on every
route and riders, the level figure (22 ft), an Avoid stretch and crossings (13th Street
one-way) on the Mass Ride.

## The rolling stress chart (OWNER-DECISIONS 460.12, 461, 461a-e, 469b)

460.12: "A chart of rolling traffic stress makes more sense than a strip. That way, spikes
show up." On every ride type but Mass Ride the route chart's stress strip is replaced by a
line of **calm miles per actual mile** (461d) over the mile around each point (461e),
junctions included. The design is docs/stress/stress-number.md section 4 (on
`wip/stress-docs` until it merges); this is what was built, and where it differs.

**The score** (`routemaker.calm`, called from `core.routing.route_profile` with a
`calm.Pricing` made in `plan` from the slider position, the preset's exposure weights, the
target, the graph and `refine.quiet_cost_per_m`):

- **Each road at its own routing cost** (stress-number.md section 4; 461c). `trace_leg`
  also asks for `calm.TRACE_ATTRIBUTES` (each edge's use, class, lane count, cycle lane,
  shoulder, truck route, bicycle network, tagged speed, density, roundabout flag and
  surface); `calm.road_of_edge` puts them on each `Piece` (`Piece.road`), and `plan` hands
  the pieces with their tiers to `route_profile` (`_calm_pieces`). `calm.edge_factor`
  restates Valhalla 3.9.1's bicycle edge cost for the edge (sif/bicyclecost.cc
  `BicycleCost::EdgeCost`: `1 + accommodation x roadway stress`, the lane, truck, class and
  speed terms, `use_sidepath` from LTS 3 off trail-class ways, the network factor), with
  the speed the graph gave the edge (`road_speed_kph`: 140 on a graded edge, which reports
  15 lanes, taken as tagged, so 130 rough and 175 on a turn channel; a tagged `maxspeed`;
  else the class default or, density over 8, the builder's urban speed,
  mjolnir/speed_assigner.h). A graded edge carries the sidepath term whatever the live
  tier says. Grade, surface, turns, gates and the alley charge are left out (not traffic,
  or counted on their own). `M = factor / calm.quiet_factor`, the same factor for a
  residential street with no lane at its default speed (urban or rural, as the road is) at
  the ride's `use_roads`, so each figure is relative to the local quiet street: the
  reference road (an untagged residential street) reads exactly 1 (461d), a residential
  street tagged 25 mph about 1.13, and a path about 0.67 at Default; plus the calm-rate term above 80. At the top of the slider LTS 3 and up keep
  the worth rule's figure (the ranking's own price), and stairs and ferries their tier's.
  It reproduces the "Graded stress" table above, every cell, to 0.01 (`tests/test_calm.py`
  `TestOwnCost`). Each piece is priced at its stress section's tier and rating
  (`calm.with_section_tiers`), so a folded sliver is neither a rated island nor an
  unshown Avoid entry. The sums run over every piece; each section's step is its mean.
  A Valhalla upgrade that touches `bicyclecost.cc` or the speed assigner must be checked
  against `edge_factor`.
- **The tier's figure** (`calm.multiplier`) stands in for a piece with no edge attributes (a
  router or test double not asked for them; `estimate: true`). So does a stress edit since
  the last rebuild: where the live tier and the graph disagree about grading
  (`calm.disagrees`), the road keeps the graph's cost and the answer says `estimate: true`.
  Each stress section (`stress_spans`) then counts its length times its
  multiplier `M`, a quiet street's metre being 1. At LTS 3 and up, `M = 1 + added / 2.2 + rate x w(L)`: `added` is
  the middle of the five modelled road types' range for the slider's `use_roads` (the
  "Graded stress" table above; linear between its columns), 2.2 is
  `refine.QUIET_COST_FACTOR`, and the calm-rate term is the score's above 80. Avoid is LTS
  4 per metre plus its 1,800 s entry charge, as quiet metres at the ride's speed, where the
  route enters it. On the no-trail graph LTS 4 costs what LTS 3 does (no grading). At the
  top of the slider the worth rule stands in: `1 + 5 x w` with no target, `1 + 10 x w`
  with one (`refine.WORTH_UP_TO_TARGET`, 435 "One rule": the answer is fitted to the
  target, so the price of the miles up to it stands) (1 / 2 / 3). At LTS 1-2 the facility class sets it: a path `(1.1 + 0.9u) / 2.2`,
  a protected lane `(1 + (0.15 + 0.6u) x 1.2) / 2.2`, a painted lane
  `(1 + (0.9 + 0.05u) x 1.2) / 2.2`, a quiet street 1 (all 1 on the no-trail graph).
- Every junction the model charges for, flagged or not, adds what the ranking charges for
  it, at its point: its cost (`cost_ft`, after the ride-time factor: rush hour x1.25 (x2, and at least 1.86 calm mi [3.0 km], unsignalised on LTS 4 or Avoid),
  weekend x0.85, night x0.5 in town and x0.85 outside; "Intersection costs", option C)
  times `refine.intersection_weight` at the slider
  position (461d: "times its factors and the preset's intersection weight"; 0.25 at 0,
  0.679 at 40, 1 from 70). At the top of the slider the worth rule's exchange stands in
  (`refine.stress_weight_m`): a red junction 5 x 2 x its cost, an orange one 5 x 1, an
  unflagged one nothing (10 in place of 5 with a target). A junction's cost is in feet of
  quiet riding and Avoid's entry in quiet metres, so both count one for one beside each
  road's own cost (461d: "1,200 ft = about 0.23 calm mi"), and the worth figure is
  unscaled at the top of the slider, like the LTS 3 and up stretches. This is not 469b(5)'s
  `calm_mi`, which is the junction's own cost for the junction list (the
  `intersections` rows); at 70 and above the two agree. Each is counted once in every
  window that holds it, so a crossing raises the mile around it. A junction or Avoid
  entry on an unrated stretch is not counted (it has no miles to be over).
- The window is `calm.WINDOW_M` (1 mi, one setting), centred and cut at the route's ends.
  An unrated section counts in neither the calm miles nor the miles; a window with nothing
  rated has no value.
- **`estimate`** is false where every rated piece was priced by its own cost, true where
  any took the tier's figure. The chart's key and source line call the figure an estimate
  only then. (Valhalla's per-node `elapsed_cost` was not used: it holds the grade, surface
  and turn costs in one figure, and the trace gives a turn's time, not its cost, so the
  traffic part cannot be taken out of it.)

**The contract.** `profile.calm` (`core.api.ProfileCalmOut`, null on a Mass Ride or where
it failed; a failure costs only the score): `ratio` (one per `profile.m`), `steps` (each
section's own multiplier and tier), `points` (junctions and Avoid entries, with a flagged
junction's marker), `total_calm_m`, `rated_m`, `junctions_counted` (false where the
junctions were not read), `bands` (461a; read from representative roads at their own cost, `calm.BAND_*`: halfway
between a 25 mph collector at LTS 2 and at LTS 3, and between a 40 mph two-lane-each-way
primary at LTS 3 and a graded street at LTS 4; 2.01 and 11.26 at Default; a guide, so at 10 on
the slider a 35 mph two-lane-each-way LTS 2 primary reads "LTS 3 level", and at the top
of the slider they mix a road's own cost with the worth rule's tier prices), `window_m` and `estimate`. `points` lists only what the chart marks (the flagged junctions
and the Avoid entries); the others count in `ratio` and the total. On a long route the
highest window's sample is kept when the profile is thinned (`calm.peak_index`), so the
most stressful mile survives.

**Where it differs from the design** (stress-number.md section 4): the step line is each
section's mean, not every edge; the band edges come from representative roads, so each
tier's typical road lands in its own band; half steps are not read yet; Mass Ride has no
calm-mile score (it has its three charts instead, from the owner's words of 2026-10-10,
below). The owner's question of 2026-10-10 (was the per-tier estimate acceptable?) is
answered by building the exact cost, normalised so the local quiet street is 1 (the scale
the owner sees is unchanged); the estimate is now only the fallback.

**The chart** (`ElevationChart.tsx`; the decisions in `lib/profileChart.ts`, "The rolling
stress chart"): a log scale from 0.5 to the next of 2, 5, 10, 20 ... above the highest
value, so 1.4 and a spike at 14 both read; the area filled in the map's LTS 2, 3 and 4
colours with the stress bar's patterns, cut where the line crosses a guide; dotted guides
at the two band edges, labelled "LTS 3 from 2.0" and "LTS 4 from 11.3" in the text colour
beside a swatch with the band's colour and pattern (only the LTS 4 guide where both edges
are one, at 0 on the slider, where LTS 3 costs nothing extra); the side's figures 0.5, 1,
2, 5, 10 ... to the top; a quiet line at 1; a dashed step line of each section's own
figure, so a short busy stretch is seen at its true level (the step line and the guides are
the text colour over a casing in the panel colour, so one is 3:1 from any band); Avoid stretches as the magenta "A" blocks;
and the flagged junctions' triangle and diamond above the track. The key says it is a log scale and
that about 1 is all quiet streets (and calls it an estimate only with `estimate: true`). The scrub's sentence adds "Mile around: 1.4 calm miles per mile, LTS 1 to 2
level" (", Avoid nearby" where the window holds some) and "Next junction to watch: very
high stress, mile 1.4", so the markers have words. The summary gives the route's total in
calm miles with calm km in brackets, the average (calm km per km), the most stressful mile
and the flagged junctions in it, and whether junctions were counted; the source line says
each road is priced by its own speed, lanes and bike lane (or, with `estimate: true`, that it is an estimate). "Climbs and rolling stress as tables" adds a table of the value every
half mile (a mile past 10 mi, two past 40, five past 80), what it reads as, and the flagged
junctions since the row before. An older answer with no `calm`, or one whose score failed
(`calm: null`), keeps the strip.

Mass Ride has no rolling stress line (its routing charges no junction cost and almost
nothing for traffic: use_roads 1, no grading). The owner wrote on 2026-10-10: "Have 3
charts for mass ride: Riders per minute, Corker load, Elevation. They should all be
there." That matches 147 ("visualize rider flow, elevation, and anticipated corker
requirements over the route"). So a Mass Ride has no calm-mile score: the riders per
minute stay the headline figure (116, 118, 328-329), and a Mass Ride draws three charts on
one distance axis, riders per minute, the corker load and the elevation (built on
`claude/v0-4-0-mass-charts`; "A Mass Ride's three charts" in the route chart above). The
corker load rolls with the length of the ride (the owner, 2026-10-10: "Corkers were
intended to also have a rollback based on the length of the ride"): the corkers held at
once by a group of the anticipated ride size, with "about N corkers" for the ride; its
defaults (rotation factor 2, 2 corkers a junction where one-way is not known, 500 riders)
are open for the owner. Half steps arrive with the half-step editor
(the score reads whole tiers); the panel's stress bar stays as it is. Junction costs
change when `wip/isect-costs-c` (468, 469) merges, and the chart follows, since it reads
the model's own `cost_ft`.

## Accessibility mode (OWNER-DECISIONS 455, 455a)

`frontend/src/lib/accessMode.ts`. Off by default; with it on, Map tools (below) is on the
page by the map's zoom buttons; with it off, App does not render `<MapTools>` at all. The
keys (I, the arrows, + and -) work in both modes.

- **Storage.** localStorage key `routemaker.accessMode`, "on" or "off"; only "on" means
  on, so a missing or unknown value reads as off. Reading and writing are in try/catch
  (`browserStore` also catches a throwing `localStorage`), so with storage blocked the mode
  is off at load and lasts only for the visit. It is unrelated to the High contrast
  switch, whose key is `routemaker.accessibility` (`stressStyle.js`; the switch is
  `lib/accessibilitySwitch.ts`).
- **Two switches**, both a `<button aria-pressed>` with the constant name "Accessibility
  mode": the page's first element and first Tab stop (`.access-link`, off screen until
  focused like the skip link, which is now the second stop; both at least 44 px tall), and
  one in More tips (`.access-toggle`). `accessModeToggle` gives the new state, what the
  page's polite region says ("Accessibility mode on: high contrast, large text during a ride, and Map
  tools by the map's zoom buttons." / "Accessibility mode off: high contrast and large ride text are off,
  and Map tools is hidden.") and whether the focus moves:
  only the first switch, turning the mode on, moves it to the Map tools button. The move
  waits for Map tools to mount (`MapTools`' `onShown`; the map may still be loading) and is
  dropped if the focus has moved on since the press.
- **One shared mode** (P5; the owner: "Accessibility = one shared mode with screen-reader tweaks"). Every
  press of the mode's switch (the first button, Points' Info, Settings > Display) goes through App's
  `toggleAccessMode`, which also sets High contrast (`setAccessibility`) and Large text during a ride
  (`setRideText`) the same way (`accessModeParts`). Those two stay switches of their own, indented under the
  mode in Settings > Display; changing one leaves the mode and the other alone. Each keeps its own key
  (`routemaker.accessibility`, `routemaker.ride.bigText`; the mode's is `routemaker.accessMode`), so a rider who
  had only High contrast on keeps it. None of the three syncs with the account (lib/accountSettings.ts). While the
  mode is on, `access-mode` on the page's root brings Go's small text to 15 px (place and ride-type chips, the
  stress line, Settings' headings, the map's scale).
- **Help that changes with the mode.** Off: the search lede and the lone-start hint (shown
  outside More tips) say "For keyboard or screen reader use, turn on accessibility mode
  (the first button on the page, or in More tips)."; in More tips, the keyboard hints and
  the road help say "turn on accessibility mode" before naming Map tools, and its own line
  says "For keyboard or screen reader use, turn on accessibility mode. It turns on high contrast,
  large text during a ride, and Map tools by the map's zoom buttons, and is kept on this device. It is
  also the first button on the page." On: the hints name Map tools directly (`mapToolsWays`, `infoHelp`, `searchLede`,
  `loneStartHint`, `editingTips`, `emptyPlanHint` all take the mode).
- **Upgrade note.** v0.2.1 showed Map tools to everyone; after this change it is behind the
  mode, which starts off on every device (no earlier key to migrate from). The release
  note tells riders to turn it on once.
- **Tests.** `lib/accessMode.test.ts` (storage, blocked and missing storage, the press, the
  wording), `pointText.test.ts`, `roadInfo.test.ts`, `sidebar.test.ts`,
  `a11yFixes.test.ts`; the browser suite (`scripts/a11y/check.mjs`, EXPECTED 319): section
  1 checks that the switch is the first stop, not pressed, shown and 44 px tall when
  focused and off screen otherwise; 7 checks before the Map tools ones cover off by
  default, the help when off, Enter turning it on (Map tools closed and focused, kept),
  the announcement, a new page remembering it, Enter turning it off (the focus stays) and
  the More tips switch.

## The map's road panel (OWNER-DECISIONS 441, 441a-441f, 441m-441q, 450, 455; v0.2.1)

**What a rider does.** A right-click on the map (a computer), a finger held still for
0.6 s (a phone; `lib/roadInfo.ts` `LongPress`, called off by a drift past 10 px, a second
finger, the finger lifting or the map moving, and never preventing a default, so the map
pans and pinches as before), I with the map focused, or "Road info at map center" in Map
tools (450; `MapTools.tsx`; on the page only in accessibility mode, 455, above): one small button, at least 44 px, in a map control under the
zoom buttons, a disclosure (`aria-expanded`, two plain buttons, not an ARIA menu) holding
"Add point at map center" and "Road info at map center"; Escape closes it and the focus
goes back to it, as it does before either action runs, and the crosshair shows the center
while it is open. The two were wide planner buttons before 450. Each way opens
`RoadInfoDialog.tsx`, the platform's modal `<dialog>`: the focus goes to its heading,
Escape and Close close it and the focus goes back to what opened it, Tab stays inside.
It opens compact (the owner: "a bit wordy and I have to scroll"), so the common case fits
a phone without scrolling: the name and kind ("Main road, nearest the spot you picked"),
then a top row of real buttons (441n), "Set as start", "Set as end" (not in a loop) and
"Add as stop", which put the spot (the map's center by keyboard) in the plan as the search's
Start / Destination / Stop choice does (`applyPlace`: loop-aware, the coverage check, the
cap; an unavailable one is `aria-disabled` with its reason beside it and as its
description), say "Stop 2 set here." and the like, and close the panel, the focus going
back to what opened it (the map, after a long press); then the API's `summary` as a list, one short line a fact with no source under it
("Traffic stress: LTS 3 · For experienced cyclists", "Why", "Speed", "Lanes", "Traffic:
22,000 a day (DDOT 2024)", "Bike lane", "Surface" off a plain paved road, "Bikes: Allowed"
or "Not allowed — military area", and "Room for: About 160 riders a minute" on the Mass Ride map
only); a line with nothing useful is left out, but bike access is always said. A nearby
station's pages follow, then a closed native `<details>` "Details and sources" with every
section (a heading each, the figures a description list with the source in words), the
way's OSM id and distance, and the credit; then the bottom action row (441m), links drawn
as buttons: "Street View" (its privacy note its description) and "Edit in OSM"
(`https://www.openstreetmap.org/edit?way=ID`, hidden without a way id, its note "Needs an
OpenStreetMap account; don't copy from Google Street View"). "Change LTS" is an instance
admin's third button in the row (StressEditor.tsx; docs/OPERATIONS.md, "Change LTS"); a rider
the suggestion setting allows gets "Suggest a change" there instead (SuggestChange.tsx,
`core.suggestions`; the admin reviews in the Settings sheet, SuggestionReview.tsx, and "Send to
Discord" builds the copy-paste poll in `core.suggestion_post`; docs/OPERATIONS.md, "Rider
suggestions"). Where the piece is part of a named stretch, the editor's "What to change" radio
group offers the whole stretch (its pieces and length, miles first, kilometres in brackets;
`core.stress_edits.named_stretch`, names from `core.road_names`; docs/OPERATIONS.md, "The whole
named stretch"). A polite status region inside the dialog (always rendered, empty until the
answer comes) says one short sentence ("Connecticut Avenue Northwest: LTS 3, for experienced
cyclists." and on a closed way "Bikes not allowed here."); the page's own region would be
silent, since the modal makes everything outside it inert. On a phone it is a sheet from
the bottom. The help (More tips) names all four ways (right-click, hold, I, Map tools; with
accessibility mode off it says to turn the mode on for Map tools) and
says that NVDA and JAWS pass I to the map only in focus mode; the map's own name says
"Press I" (and only the canvas has `aria-keyshortcuts="I"`). A right-button drag that rotates the map is not a
request (`MapView.tsx`: the contextmenu waits for the release on platforms that send it
with the press, and a release that moved more than 5 px is a rotation). A held finger on
the route line still picks the line up; the panel's long press only starts off it.

**What it shows** (`core.segment_info`, GET /api/segment-info?lat=&lon=). The nearest
row of the live segment table within `SNAP_RADIUS_M` (30 m, 100 ft; "No road here"
otherwise), a drawn way winning over a hidden one (a mapped sidewalk) up to 15 m nearer.
Its name and kind come from the standard router's `/locate` at the spot on the way, as the
route's street names do, matched by OSM way id; the bicycle costing's edges say whether the
graph lets a bicycle on, and the pedestrian then auto costing name a way it does not. Then:
the stress tier with the step words (1 "Comfortable for everyone" to 5 "Avoid", and the
half steps' own words, 441i-441l: 1.5 "Probably comfortable for older children", 2.5 "Fine
for most confident adults", 3.5 "Stressful even for experienced cyclists", 4.5 "A very
high-stress road"; the answer's `step` is 3 or 3.5) and `stress_rule` in plain words (`rule_words`:
"35 mph or above, mixed traffic", "Owner-rated corridor", "Avoid: highway-like road
(posted 55 mph)"), an override's tier before it and its category, its note only where the
row's display is `map` (a `route_only` note is never shown on a click); the lanes, "each
way" or, where `road_oneway` is true (a one-way street, or one carriageway of a divided
road), "in this direction", since `road_lanes` counts one direction; and
the speed limit, posted (with `attr_sources`' source) or assumed (the classifier's figure
from the rule); the count, its publisher and year, or "No count"; the facility class,
`car_free_when`, the shared surface rule (`is_unpaved`, `is_rough`, a roadside path's
"probably paved", 403, 440); bike access; and the Mass Ride width and riders a minute on
the level (`flow.level_riders_per_min`), shown on the Mass Ride map only. The answer's
`kind` and `summary` (`summary_rows`: `{id, label, value}`, no sources) are the compact
lines; the sections stay the full record. "Street View" is Google's public URL for the nearest point on the way (the answer's
`on_way`, `[lon, lat]`, 441o; the spot itself when no road is found), in a new tab with
`rel="noopener noreferrer"`, named in text only, with the note that the spot is sent to
Google only if the link is followed. No person is ever named: an owner's row is "Owner
override" or "Owner-rated corridor".

**Bike access and its reason.** Open or closed is the router's answer when it gives one
(the graph is the truth routing uses), else the table's (`map_class` barred, or a closing
reason). The reason is the new column `segment.bike_access_reason`
(`routemaker.facility.bike_access_reason`, written in WRITE_SEGMENTS): an approved access
override that reopened or closed the way (`override_open`, `override_closed`), else its
`rm:no_bicycle` reason (`military`, `secured`, the trail rules, `cbd_sidewalk`, `zoo`,
`singletrack`, `mtb`, `dismount`), else its own tags (`bicycle_no`,
`bicycle_use_sidepath`, open, where a side path is mapped beside it: review RL-1,
`private`, `motorway`, `motorroad`). `ACCESS_WORDS` words each,
and a test holds every code the rebuild can write to having words. The military and
secured rules are the err-closed ones (OWNER-DECISIONS 330), and say so.

**An older live table.** Every column newer than the oldest table is optional
(`OPTIONAL_COLUMNS`, read from `information_schema` and looked for again every 5 minutes
while one is missing, so a swap is picked up without a restart). The live table of
2026-10-07 has no capacity, access-reason, trail or roadside columns: the Mass Ride rows
then say "Available after the next data update", and a closed way "Closed to bicycles;
the reason is available after the next data update".

**Limits and privacy.** Signed out; refused uncounted when the browser says a foreign page
sent it (as place search is); 20 per 10 s and 60 a minute per client
(`ratelimit.SEGMENT_INFO_BURST`, `SEGMENT_INFO`); the place names' router slot
(`GEOCODE_IN_FLIGHT`, `name_slots`), so a burst of panels never holds a search's slot;
`Cache-Control: private, max-age=300`. The spot is in the query string, which gunicorn's
access log leaves out, and the beta's nginx location for reverse look-ups and searches now
covers `/api/segment-info` too (its error log at `crit` only; `tests/test_beta_overlay.py`
holds every path the front end sends a query to to that location). Nothing logs the
coordinates (a test).

**Stations (441b-441f).** A station's tap card (railInteraction.ts) offers its pages under
Start here / End here / Add as stop: a Metro station's WMATA page from
`rail-data/wmata-station-slugs.json` (curated and checked, rail-data/README.md) and a MARC
Penn station's Penn Line timetable; Union Station and New Carrollton offer both. Offered,
never followed by itself (441c). The road panel lists the pages of the nearest station the
map shows within 0.25 mi (400 m) of its spot, which is how a keyboard or screen-reader rider
reaches them: the station's name in view ("Nearby station: Dupont Circle"), then the short
links "Station site" and "MARC timetable" (441q), whose accessible names stay specific and
hold the visible words ("Dupont Circle station site, WMATA, opens in a new tab"; "MARC
timetable, Penn Line, MTA Maryland, opens in a new tab").

**Deploying it.** Code, no migration, and one new segment column, which arrives with the
next rebuild (its DDL is in `SEGMENT_DDL`; until then the endpoint tolerates its absence).
The front end and the API may ship in either order: an old API answers 404 for the
endpoint and the panel says the information is not available right now. The beta's nginx
template changed (the location regex): re-render it with `scripts/beta/render-nginx.sh` on
the next beta deploy (with `--no-password` since the beta was opened; BETA-RUNBOOK, before step 10).

**Tests.** `tests/test_segment_info_api.py` (the answer on a real live table with the router
faked at `segment_info.locate_edges`; no road; a hidden sidewalk nearer than the road; an
unnamed path; assumed speed and lanes; a closed way's reason; an owner's reopening and
corridor; the route-only note kept off; a silent router; an old table; no coordinates in
any log; 400, 403 uncounted, 429; the rule and reason words; `bike_access_reason`),
`tests/test_beta_overlay.py`, `lib/roadInfo.test.ts`, `lib/stationLinks.test.ts` (every
Metro station on the map has a slug, no stray, Penn and Union Station, the nearby station),
and section 21 of the a11y check (36 checks: 29 since the v0.2.1 fix round and 7 for
accessibility mode, 455; among them Map tools
by keyboard, the answer read from the accessibility tree inside the dialog, Shift+Tab, an
unavailable top-row button, the station links near Union Station and the focus after a long
press; the first 15: a right-click opens a modal dialog with the
focus on its heading, one request with the spot in the query only, labelled sections with
sources in words, no capacity off the Mass Ride map, the Street View link and its note,
the polite announcement, the dialog's accessible name, Tab held inside, I on the focused
map and the canvas's name, Escape back to the map, the button and Close back to it, the
help, the Mass Ride width and riders, a pan that opens nothing, and a held finger that
opens it and adds no point). `scripts/a11y/cdp.mjs` mocks one road for
/api/segment-info.

## Find the nearest water, restroom or Metro

The owner, 2026-10-10: "Have the option to route to the nearest public water source, restroom, or
metro stop. Let people choose the three closest." A fold in the planner under the points
(`lib/nearestFinder.ts`, written with createElement so `lib/nearest.test.ts` renders it): "Search
from" (My location where the browser can share it, the default; the map's center; the plan's start
once there is one), then Nearest water, Nearest restroom and Nearest Metro. The places are the map's
own (`lib/nearest.ts`): the water layer's points (drinking water only; restrooms of every type, titled
with their type; the file is loaded for the search even with the layer off),
and Metrorail's stations at their bike entrance (`railStations.bikeEntrance`), MARC left out. The 8
nearest in straight lines (`NEAREST_CANDIDATES`) go to `POST /api/nearest` with the ride's preset and
dials, with the riding speed and the closure choices (`closureFields`; not the weight, loop or
target), which answers each one's riding distance and time from
Valhalla's `sources_to_targets` on the ride's own graph and costing (`stoporder.ride_graph`, shared
with Best order), or straight lines when the router gives none. Like Best order's legs and matrix,
it is asked at the rider's own speed where the request gives one (`cycling_speed_kmh`), and leaves
out what the plan would (`stoporder.ride_exclusions`): the closures to bicycles in force at the ride
time, but those routed through (`closure_bypass`, `closures_now`), and the roads the rider marked
closed (`blocked_lines`, which the page does not send yet: Ride keeps them for its re-plans
only). The 3 nearest by bike
(`NEAREST_SHOWN`; one the router cannot reach is left out) are listed in words, US units first, each
with Ride here (a new plan from the search's origin to it: one `commit`, so Undo puts the plan back;
a loop is turned off in the same edit) and, for water and restrooms with a plan of two or more
points, Add as stop (`placeSpot("via")`). One status line, always rendered, says what is happening
and what was found, the nearest by name and distance; it is cleared and set again a moment later so a
repeat is said again, and with the planner out of sight it is said through the app's region. The
buttons are `aria-disabled` while a search runs. The search itself is `searchNearest` (plain, tested
with stand-ins); App hands it the look-up, the map's center, the water file and the request. A list
is put away when the ride type or a slider changes, when "Search from" changes, or when the plan's
start moves under a search from the start. The location look-up goes
through Use my location's gate, so there is one look-up at a time (a press during the other's says
so); the fix stays in memory as that
button's does, and the position leaves the device only in the search's own request, as a route's
points do (`geolocation.test.ts` pins both look-up paths). While riding, Ride mode's "Water or restroom" fold (`RideMode.tsx`) runs the same
`searchNearest` from the ride's own fix (`rideLocate`; no new look-up), water and restrooms only
(`DETOUR_KINDS`), on the ride's preset and dials without the loop. Its answer is said through the
rider's outputs as Where am I? is (`announcer.answer`, and the polite region with neither chosen).
Detour here re-plans through `replan(here, via)`: `replanPoints` gives here, the stops not yet passed
and the end, and `detourPoints` puts the place second, so the new route cues it as a stop. It goes
through the re-plan gate (`gate.online()` first, since the rider asked), and a re-plan already under
way is said and left alone.

## Transit assist (TRANSIT-ASSIST, v0.6.0)

There are two ride types, `bike-transit` (Own Bike + 🚆🚌) and `bikeshare-transit` (Bikeshare +
🚶🚆🚌). The emoji names are the owner's (2026-10-12, 20:35); the ids and links did not change.
Wherever a name shows, its emoji are aria-hidden and the spoken name (`spoken` in
`lib/presets.ts`: "Own bike plus train or bus", "Bikeshare plus walk, train or bus") is read
instead: `PresetName` (`lib/presetName.ts`) in JSX, `presetSaid` in plain text. The ride type
search also matches the spoken name and `keywords` ("transit"). Both are planned by `core.transit` from a compact schedule built from each system's static
GTFS (`scripts/build_transit_schedule.py`, schema 2). The systems, their bike rules and the sources
are listed in `src/core/transitdata/systems.json`. Sources and terms: docs/SOURCES.md. Running it:
docs/OPERATIONS.md, "Transit schedule". The design note is plans/v0.6.0-transit-assist.md.

- **Options.** Riding the whole way is always one option. Up to three transit trips are added,
  quickest total first, one per distinct sequence of boardings. A trip has one or two transit legs,
  with a same-stop change or a walk or ride of up to 400 m (1,300 ft) between them.
  - Own Bike + 🚆🚌 never walks and never leaves the bike.
  - Bikeshare + 🚶🚆🚌 docks before boarding. Each end is a walk or a bikeshare ride, whichever is
    quicker. It also offers walking the whole way (`transit.WALK_ONLY`) when walking is the
    quickest option or the trip is under 1 mi (1.6 km) in a straight line (`WALK_ONLY_M`). The walk
    is routed with Valhalla's pedestrian costing, as the bikeshare planner's walks are, and is the
    answer's line itself (no bike route is asked for it).
  - Each option carries `legs`, its legs compactly (walks and rides with a station's way in or out,
    a transit leg with its wait). A transit trip's row shows them as marks, "🚶 4 min · 🚲 12 min ·
    🔴 18 min", and a screen reader hears "walk 4 minutes, bikeshare 12 minutes, Red Line 18
    minutes". The marks live in one module, `lib/transitMarks.ts`, shared with the station popups:
    🚶 walk, 🚲 bike, Metro by line colour (🔴🟠🔵🟢🟡⚪), a bus "🚌C53", MARC and VRE "🚆Penn",
    "🚆Fredericksburg", Light RailLink 🚈, Metro SubwayLink 🚇.
  - The rider's choice goes back as `transit_option`. A stale key falls back to the quickest, with
    a note.
- **Calendars.** Each service's days come from `calendar.txt` and `calendar_dates.txt` for 45 days
  from the build date, so holidays, weekend-only service and published shutdowns are exact. The
  service day turns over at 3 am.
- **Waits.** From the next three or four departures (two leaving the same minute count once): if
  every gap is 15 min or less, the wait is half the mean gap. Otherwise (a near pair before a long
  gap included) the plan takes the next departure, names it and the one after, and returns it as
  `transit.departure`. A routed first ride that misses it moves to the next catchable departure
  (and names the one after that); with none within the hour the option is dropped.
- **Metro's typical timetable.** Until WMATA's rail GTFS is built (it needs a WMATA key), Metro
  runs on `src/core/transitdata/metro-typical.json` (`transit.with_typical_metro`), added when the
  schedule is loaded, or alone when no schedule is installed. It holds the opening hours per day
  type, each line's minutes between trains per time band (wmata.com's line pages), each line's
  stations in order with estimated run times, and the map's 98 stations (held equal to
  `metro_stations()` by a test). Trains are laid out evenly, and a wait is always half the
  interval (or the time to the first or last train), so no Metro departure is named or counted
  down. Before the first train the step names it instead of the interval ("first train 5:00 am
  scheduled"). A holiday runs the typical Sunday timetable, and the holiday note says so. An
  installed schedule that has run out (or does not reach the date asked for) leaves Metro on its
  typical timetable alone, with a note; `check_operations` still asks for a rebuild. Its credit reads "WMATA, wmata.com (typical service)"; there is no separate note. A built
  schedule with WMATA's rail GTFS replaces it with no setting. Metrobus stays out until its GTFS is
  built.
- **"Scheduled" on every transit time** (the owner, 2026-10-12: "Make it clear whether it's a
  schedule or live."). One word after each time the rider sees, GTFS or typical alike, in the
  step text, the departure, the next departure, the countdown, the map label and the screen
  reader's milestones: "Board the MARC Penn Line at 7:42 am scheduled", "every 8 min,
  scheduled". Each transit step and `transit.departure` carry `source: "scheduled"`, and the
  page takes the word from it (`sourceWord`, `lib/departure.ts`), so live times (v0.7) can say
  "live" without new UI.
- **Times.** A service-day minute is real elapsed time from GTFS's zero (noon less 12 hours), so
  daylight-saving days are right. From 1 to 5 am both service days are searched (owl trips past
  27:00 included). Stops without times (not timepoints) are interpolated by the build.
- **Router budget.** The direct ride is routed first. Candidate legs are capped at 5 s a call and
  `MAX_ROUTER_CALLS`, and stop 12 s into the request (`api.TRANSIT_CANDIDATES_S`); a refusal, a
  timeout or a router that is down estimates the leg from the straight line, never fails the plan.
  The answer's own line has the rest of the budget. If the router does not draw it in time (a
  timeout or the router down), the leg is drawn straight with the plan's estimated time and a note
  says so, as a short leg is. The api logs each plan's seconds in the search, the candidates' router
  calls and the line, at info level.
- **Clock times.** A departure's clock ("1:30 am") is the wall time of its service day's minute,
  so a daylight-saving night says the time the station clock shows.
- **Blackout dates.** Own Bike + 🚆🚌 takes no bike on Metro on them ("Bikes aren't allowed on
  Metro today (July 4)."); Bikeshare + 🚶🚆🚌 still rides Metro on foot.
- **Departure in the app.**
  - The panel shows the departure in words (`lib/departure.ts`). Under 5 min to spare it adds a
    mm:ss countdown and the spare time (`DepartureTimer.tsx`).
  - The map shows a label at the boarding stop. It sits above the stop, or below when the start or
    end marker is near, and turns into the countdown when time is short.
  - Neither is a live region. The milestones (10, 5 and 2 min) and a miss go through the page's
    status line. A miss plans again; `core.transit.with_ride` moves to the next departure.
- **Closed stations.** `GET /api/transit/closures` lists the rail stations with no service all day,
  and `lib/railClosures.ts` matches them to the map's stations.
  - On the map, a closed station is struck through, grey and named "(closed)".
  - Its card and the nearest-Metro list say "closed: reason".
  - Routing never uses a closed station, because it has no departures that day.
- **Station times.** `GET /api/transit/station-times?lon=&lat=` (`core.transit.station_times`)
  gives the lines at the rail stops by a map station (the nearest stop of each system within
  400 m), cached for a minute. `lib/stationTimes.ts` words them, with `lib/transitMarks.ts`'s marks.
  - A frequent line (Metro, Light RailLink, SubwayLink): "🔴 Red Line: every 8 min, scheduled",
    read from at least three trains within the hour, the next one within the interval; otherwise
    (before the first train, or the last few of the night) the next train each way.
  - A commuter line (MARC, VRE): the next train each way, "🚆Penn to Baltimore Penn Station 5:42
    pm, to Union Station 6:10 pm, scheduled"; "no more trains today", or "no trains today".
  - Each departure is timed with the run times of its own time band. Between midnight and 3 am
    (the day before's service day), a way with nothing more that night gives the new day's first
    train, timed on its own service day, so a daylight-saving night says the clock's time.
  - Shown in the station's card (fetched when it opens; in the hover card once known) and under
    the road panel's nearby station, the keyboard's way to it. The emoji text is aria-hidden; a
    visually hidden twin says it in words ("Red Line every 8 minutes, scheduled"). Both show the
    lines of the systems the map's toggles show. A closed station keeps its "closed" words and
    shows no times; a 503 shows none.
- **Tests.** `tests/test_transit.py` runs on a synthetic fixture
  (`tests/data/transit/make_fixture.py`: WMATA rail and bus, MARC Penn and Camden lines, Light
  RailLink) with a straight-line router. Front-end tests: `lib/transit.test.ts`,
  `lib/departure.test.ts`, `lib/railClosures.test.ts` and `lib/stationTimes.test.ts`. a11y checks: the "transit (Go)" checks in
  `scripts/a11y/check.mjs`.

## Bikeshare (FOLLOWUP-BIKESHARE, OWNER-DECISIONS 243-245, 299-301, 466, 466a)

`POST /api/route` with `preset: "bikeshare"`, `bike` (`classic`, the default, or `ebike`) and
optionally `ending` (`dock`, or `outside_dock` for an e-bike) plans a walk, a ride dock to dock and
a walk. Two points only. The answer is the ride leg's route body, with the walks, docks,
availability, fee information and notes under `bikeshare` (`core.api.BikesharePlanOut`).

- `core/gbfs.py`: the operator's official GBFS feeds. One live copy for the whole deployment, not one
  per api worker: a worker looks at its own memory (`CACHE_TTL_S` 60 s), then at the shared copy
  (`DatabaseStore`: the single row of `core.models.BikeshareFeedCache`, replaced in place at each
  refresh, with a PostgreSQL advisory lock so only one worker reads the feeds while the others wait up
  to `SHARED_WAIT_S` for its row), and only then reads the feeds. A `STALE_GRACE_S` of 120 s serves the
  last copy when a refresh fails, and `FAILURE_PAUSE_S` 15 s (noted in the row, so every worker
  honours it) before trying again; only `https` on `ALLOWED_HOSTS`, redirects included; no history is
  kept (no earlier reading, no row per station or reading), nothing is republished or exported, and a
  request carries no user data (no cookie, no address, no body). A feed that fails is "unknown", never
  "empty": no `station_status` means availability is unknown and the plan says so. `StationStatus`
  keeps `num_bikes_disabled`, `num_docks_disabled`, `is_renting`, `is_returning` and `last_reported`;
  a station whose `last_reported` is more than `STATION_STALE_S` (30 min) before the reading
  (`Snapshot.as_of`) is unavailable everywhere (`Snapshot.reporting_stale`; a station with no
  `last_reported` is stale once the reading time is known). Tests pass a `wall` clock and a fake store
  and never touch the network.
- `core/bikeshare.py`: the plan. Candidates are the 3 best docks that can start (a bike of the type,
  renting) and end (a free slot, returning) a ride, and for an e-bike the 2 best free-floating
  e-bikes, "best" by the direction rule below (within 1.9 mi (3 km)); each is walked for real, the
  quickest pair is chosen (real walks plus the estimated ride; ties by the walks plus extra riding),
  and only that pair is routed as a ride. The time, not the rule, picks the pair because it also
  credits a dock ahead for the riding it saves; by the rule alone about a quarter of trips came out
  slower (1 in 10 by 17 s or more, the worst by over 3 min) for almost no more docks on the way (a simulation in the review of PR #94). Walking is Valhalla pedestrian costing on the standard graph at 3 mph.
  The answer's `bikeshare.options` lists up to 3 pairs, best first, the first being the plan itself
  (below).
- The ride leg is `routing.plan` on the `bikeshare` preset: stress 80 with the stress-averse
  exposure weights (casual riders, calm by default), classic hills -60 at 13 km/h (8 mph), e-bike
  hills -20 at 20 km/h (12 mph) on the e-bike graph. The sliders still apply.
- The out-of-dock ending (244) needs the operator's `geofencing_zones` (GBFS 2.1) and a destination in
  no zone that bars ending a ride. The operator publishes none today, so only docks are offered, and
  the answer says why (`endings[].reason`). The fee is read from `system_pricing_plans`, matched by
  what the plan says (`gbfs.OUT_OF_DOCK`); with none named the answer says the fee is not in the
  operator's data. Fees are shown as information, never as a quote, and none is built in.
- Tiles: the standard graph is built with `include_pedestrian: true`; a pedestrian route over it was
  checked on 2026-10-04 (Union Station to the Capitol area, 1.04 km). The graph's stress remap can
  make a cycleway cost like a path closed to pedestrians for bicycles only; walking uses Valhalla's
  own pedestrian costing and is not routed by stress.
- Tests: `tests/test_gbfs.py`, `tests/test_bikeshare.py`, `tests/test_bikeshare_api.py`,
  `tests/test_bikeshare_shared.py` (the shared copy), `tests/test_bikeshare_nearby.py` (the nearest
  stations, stale stations, a chosen station) (fixtures in `tests/data/gbfs`, a sample and not a
  dataset), `frontend/src/lib/bikeshare.test.ts`, `frontend/src/lib/stations.test.ts`, sections 23 and 24 of
  `scripts/a11y/check.mjs`, and `scripts/mutants_bikeshare.py`.

Source citation and licence notes (OWNER-DECISIONS 301, 304, 305): the map attribution and the route
credits say "Capital Bikeshare" and nothing more (`core.gbfs.CREDIT`, `BIKESHARE_CREDIT` in
`frontend/src/lib/bikeshare.ts`; a test holds them equal). What it cites is the operator's official GBFS
feed, operated by Lyft, used under the operator's Data License Agreement (item 300: official endpoints
only, short in-memory caching, no republishing, no logos, no implied affiliation, nothing tied to users).
Out-of-dock endings stay off for good: the operator's no-parking zones exist only inside its app, with no
public map or feed, so using them would breach the licence. The plan says so in plain words and links
https://capitalbikeshare.com/how-it-works/ebike for the current parking rules. No fee is built in.

### The nearest stations to pick up from or return to (OWNER-DECISIONS 466, 466a)

When a rider is choosing where to undock, the Bikeshare panel lists the 3 stations nearest the start
that are **at least 3/4 full** (bikes / (bikes + free docks) >= 0.75, installed, renting, reporting in
the last 30 minutes); when choosing where to dock, the 3 nearest to the end that are **at most 1/4 full**
(<= 0.25, installed, returning, reporting in the last 30 minutes). Live feed only: no history, no
reports, no fitted formula (the crowdsourced points reports of 464-464b are parked pending the licence
question). The lists are labelled generically ("Nearby stations to pick up a bike") and name no
programme, and the rider chooses. Once both ends are placed, stations on the rider's way come first
(below); with only a start, the pick-up list is by distance.

- `POST /api/bikeshare/stations` `{point: [lon, lat], action: "pickup" | "dropoff", toward?: [lon,
  lat]}` answers `{action, availability, stations: [{station_id, name, lon, lat, percent_full,
  distance_m, bikes, ebikes, docks, extra_m, on_the_way}], credit}` (`core.bikeshare.nearby_stations`,
  no distance cap (the owner, 2026-10-10), up to 3, best first by the direction rule toward
  `toward`; nearest first, with `extra_m` and `on_the_way` null, without it). A POST so the point is in the body and in no URL; `Cache-Control:
  no-store`; its own limit (`ratelimit.BIKESHARE_STATIONS`); 503 `bikeshare_unavailable` when there is
  no station list; with no availability feed `availability` is `unknown` and the list is empty.
- A chosen station goes to `POST /api/route` as `pickup_station` / `dropoff_station` (the station's
  id; Bikeshare only; not a drop-off with the `outside_dock` ending). The plan starts or ends there in
  place of the nearest docks; if the station can no longer serve (no bike of the type, not renting,
  full, silent for 30 minutes) the answer is 422 `no_bikeshare` saying why, never a silent swap.
- Front end: `NearbyStations.tsx` under the points while the ride type is Bikeshare, a pick-up list
  once a start is placed and a drop-off list once an end is. Each station is a real `<button>` named
  exactly as it is read, "Station name, 82% full, 2 e-bikes, 0.2 mi (320 m)" (`lib/stations.ts` `stationLabel`, US
  units first, metric in brackets), with `aria-pressed` for the chosen one (also marked in text, not by
  colour alone) and a polite status line (loading, how many, none, an error). Pressing the chosen
  station again hands the choice back. A chosen station is session state in `App` (`stationPins`),
  forgotten when its point moves or the ride type changes, added to the request by
  `lib/stations.ts` `withStations`, and in no link (the counts change by the minute).
- Tests: `tests/test_bikeshare_nearby.py`, `frontend/src/lib/stations.test.ts`, and the a11y check's
  section 24 (Tab order, the button names, `aria-pressed`, the status line, the 375 px layout).

### Stations on your way first, and the route options (the owner, 2026-10-11)

"For rideshare, we should prioritize the stations that would be in the direction of the route." One
rule ranks the station lists, the plan's candidate docks, its choice of pair and its route options:
**a station costs its walk plus the extra riding it adds.** The extra riding is how much farther the
station is from the trip's other end than the rider's own point is, never below zero
(`core.bikeshare.extra_riding_m`, straight lines):

- picking up near the start, the other end is the destination: a dock toward it adds nothing, a dock
  behind the rider adds its distance back;
- returning near the destination, the other end is the start: a dock on the way in adds nothing, a
  dock past the destination adds how far past it is.

So a dock 100 m (330 ft) behind ranks with one 200 m (660 ft) ahead, and nearer still wins among
docks on the way. It was chosen over a bearing penalty because it has no tuning angle and can be
checked with a ruler. A station adding under 50 m (165 ft) is "on your way"
(`ON_THE_WAY_M`, so a dock a little to one side of a long trip still counts); any other says
"adds 0.1 mi (160 m) of riding". The words are in the button's own text, so a screen reader hears
the reason; nothing is said by colour or an arrow. Unchanged: 3 stations shown, no distance cap,
the 3/4 and 1/4 fullness rules, stations with no bikes or docks or silent for 30 minutes left out,
and the e-bike counts.

Route options, for the Go screen ("pull out your phone, then select a destination ... offer the
options for routing to it with stations"; Bikeshare only, the owner: "only if youre in bikeshare
mode"): a Bikeshare `POST /api/route` answer carries `bikeshare.options`, up to 3 pairs, quickest
first, from the docks the rule chose (`core.api.BikeshareOptionOut`): `rank`, `chosen` (the first, which is the plan the
answer routed), `pickup` and `dropoff` (each a `BikeshareStopOut` plus `walk_m`, `walk_s`,
`extra_m`, `on_the_way` and `way_text`), `pickup_station`, `dropoff_station` and `ending` (send
them on `POST /api/route` to plan that option), `ride_m` and `total_s` (the routed figures for the
chosen one, estimates by straight line and the detour factor otherwise, `estimated`), `cost_m` (both walks
plus the extra riding, the tie-break) and `text`, the option in plain words for a button: "Pick up at Ahead, 0.1 mi (0.2
km) walk, on your way. Return at Before, 0.1 mi (0.2 km) walk, on your way. About 27 min in all."
No extra routing is done for them: they reuse the walks the plan already asked for. An answer
planned with a chosen station lists only the pair asked for, so a screen keeps the first answer's
list; a free-floating e-bike is offered only as the plan's own start (it has no id to ask for
again). Tests: `tests/test_bikeshare_direction.py` (each ranking case fails on nearest-first),
`tests/test_bikeshare_api.py`, `tests/test_bikeshare_nearby.py`, `frontend/src/lib/stations.test.ts`.

### Rebalance Ride (REBALANCE-RIDE; Stephen, 2026-10-12)

An Adventure ride type, id `rebalance` (short path `/rebalance`), label "Rebalance Ride": move a
share bike from a crowded station to one that needs bikes. The operator's reward points have no
public feed (they are only in its app), so fill stands in for them, from the station status the
Bikeshare plan already reads: bikes / (bikes + free docks), e-bikes counted. No points are shown
and there are no new settings; the ride type is not given the operator's programme name, which
appears only in its description.

- `POST /api/route` with `preset: "rebalance"` is a Bikeshare plan (`core.bikeshare.plan` with
  `rebalance=True`; two points, `bike` as Bikeshare's, `pickup_station` / `dropoff_station` as
  Bikeshare's) whose docks are the station lists' own: the 3 best crowded stations near the start
  (at least 3/4 full, renting, with a bike of the chosen type) and the 3 best near the destination
  that need bikes (at most 1/4 full, returning), each ranked by the direction rule above, with no
  distance cap (`rebalance_starts`, `rebalance_ends`). The quickest pair is chosen as on Bikeshare.
- Always a dock at each end: no free-floating e-bike, no ending outside a dock (`ending:
  "outside_dock"` is refused). With no availability feed, or no crowded station, or none that
  needs bikes, the answer is 422 `no_bikeshare` saying which.
- The steps say "which is crowded" and "which needs bikes"; the summary starts "Rebalance Ride";
  `bikeshare.rebalance` is true.
- The ride leg is Bikeshare's (`core.presets` `REBALANCE`): stress 80 with the stress-averse
  exposure, classic hills -60 at 13 km/h (8 mph), e-bike hills -20 at 20 km/h (12 mph) on the
  e-bike graph, descents costed past 4%.
- Front end: `lib/presets.ts` (`usesBikeshare`), the station lists and route options as on
  Bikeshare, in the Adventure group.
- Tests: `tests/test_rebalance.py`, `frontend/src/lib/rebalance.test.ts`.

## Avoid-rated junctions (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS 307-310, 335)

An "Avoid" rating above red for a junction, given only by a person (the owner, an instance
admin, or a reviewed community suggestion), never by the junction model. It ships with an empty
list. How an admin adds one: docs/OPERATIONS.md, "Avoid-rated junctions: adding one".

### Storage

`core.models.AvoidJunction` (table `avoid_junction`, migration `0015_avoid_junction`): a name, a
point (`location`, SRID 4326, placed on the admin's map), a reason (shown to riders), evidence
(not shown), `source` ("admin" or "community") with `suggestion_ref` for the suggestion it came
from, the approval (who and when; an audited admin action, read-only on the form, as `Override`),
and `plans_through` with `last_planned_through_at` (335's admin counts). It is kept apart from
`Override` (way-keyed, applied by the rebuild) and from any rider-suggestion table: a reviewed
junction suggestion becomes a row here with `source` "community" and the suggestion's id in
`suggestion_ref`, so the suggestion flow (STRESS-SUGGEST, the half-step editor) can feed it
without either table depending on the other's shape. No junction override table existed on
release/v0.4.0; PR #38 (intersection costs) adds cost machinery to `routemaker.intersections` and
`core.junctions` but no table, and this work does not touch either module.

The migration is numbered 0015. It was written against 0012 and was re-pointed at
`0014_segment_mtb_name`, the leaf of release/v0.4.0, when that was merged in; if another migration
lands first it must be re-pointed again (or joined with a merge migration). The table is new and
empty, so its order against the others does not matter.

### Which junctions a route passes

`routemaker.avoid_junctions.passages`: the route's line (lon, lat) comes within `MATCH_RADIUS_M`
(15 m, 49 ft) of the junction's point; the pass is placed where the line comes nearest, and a
second pass counts once the line has gone `LEAVE_RADIUS_M` (30 m) away again (a loop through it
pays twice). It reads the line, not the junction model's events: the model reads only junctions
where a road that can be busy is involved (`core.junctions.wanted`), and an Avoid rating is a
person's judgement about a place whatever its roads.

### How the 30-minute penalty reaches routing, and why no rebuild

308: "Probably a 30 minute penalty like Avoid." An Avoid road pays `presets.AVOID_ENTRY_PENALTY_S`
(1,800 cost seconds) on entry, through the graph: its tier-5 ways are the graph's alleys and the
costing's `alley_penalty` is 1,800. A junction has no such hook. Valhalla's bicycle costing has
no per-node charge a request can set, and marking junction nodes in the graph would need a
rebuild for every change to the list, which 307 ("Planner-side where possible ... so no rebuild
if feasible") rules out. So the penalty, `presets.AVOID_JUNCTION_PENALTY_S` (= the road's 1,800,
restated as `routemaker.avoid_junctions.AVOID_JUNCTION_PENALTY_S` and held equal by
`tests/test_avoid_junctions.py`), is charged on whole routes, in the router's own unit:

- **The calm search** (`core.refine`). `Analysis.avoid_passages` are read with every candidate;
  `Analysis.score` adds 1,800 s a pass; `avoid_junction_m` (the penalty over the ride's quiet
  cost per metre, as `routemaker.calm.avoid_entry_m` counts an Avoid road's entry) joins the top
  figure (`top_m`, 307: "kept in the stress order's top level ... above red") and the
  diminishing-returns weights (`stress_weight_m`, `_top_weight_m`), so at the top of the slider
  the way round is worth its extra miles. `crossing_targets` puts the junction's own point first
  among a round's exclusions (`avoid_targets`), clear of the route's ends. The Traffic-wins guard
  (`_busier`, on the router's alternatives, the rounds and the wide search) counts each pass's
  `avoid_junction_m` as exposure on both sides, so the LTS 3 a way round takes on in place of an
  Avoid junction does not make it "busier"; the LTS 4 hold (250) and the trail seek's guard are
  unchanged.
- **A long ride** (`refine_long`): each leg's weight counts its Avoid junctions with its LTS 4
  (`LONG_LTS4_PRIORITY * (lts4_m + avoid_junction_m) + lts3_m`), so a leg whose only fault is
  one is searched, and before a leg with LTS 3; the whole is judged "not as calm" by the same
  sum, with the legs' passes counted as the whole route's (`combine`, `_joined_passages`): a
  junction within 15 m of a joint (a via point, or where the legs were cut) is passed by the
  legs on both sides of it but counts once, as on the whole route's line. Every exclusion of a junction's point, in a round (`Target.radius`) or a kept point
  (`_exclusion`), carries the 15 m radius `core.avoid_junctions.exclusions` asks.
- **The guard's allowance.** `_busier` is `exposure_m + avoid_junction_m > _allowance(first
  exposure) + first_avoid_m`: the tolerance is on the exposure alone.
- **Every plan** (`core.avoid_junctions.settle`, after the search and the dodge pass, or where
  the search does not run: Mass Ride, long rides, seeking hills, past the span). Where the answer
  still passes one, the router is asked once more with the junction excluded
  (`exclude_locations`, its point with a 15 m radius, which takes out every edge at the junction).
  - `searched` is what the search did, not that it was asked: at least one round and not cut
    short (`calm_search.rounds > 0` and no `limited`). Where it searched, its own decision stands
    (it already weighed the penalty under its guards).
  - Otherwise the way round replaces the answer where its router cost is less than the answer's
    plus 1,800 s a pass.
  - On Mass Ride and Group Ride (307) it replaces it where it takes on no LTS 4 (or Avoid road)
    the answer did not have (`GROUP_LTS4_SLACK_M`, 1 m, for the traces' rounding) and is at most
    1 mi (1.6 km) (`GROUP_EXTRA_MAX_M`) or 25% (`GROUP_EXTRA_SHARE`) of the answer longer,
    whichever is more. **A default open for the owner**: the coordinator picked it on the review
    of 351e65b (307 said only "where an alternative exists", which took any way round however
    long). Reading both routes' stress costs a trace a leg of each (remembered).
  - A loop never swaps: its way back was made by a different way (`refine.make_loop`, 266) and
    the way round is a plain route through the same points, so it is offered, and the loop's
    figures (`loop`) describe the route shown. (Adding the junction to `make_loop`'s excludes was
    not done: its thinning ends with no excludes at all, which a fixed junction would remove.)
  - After a swap the routes to choose from are dropped (`candidates` null): they were near-ties
    of the route that was replaced, not weighed against the way round.
  - Otherwise the answer keeps the junction and the way round is offered as `avoid_alternate`.
    A way round that still passes the junction (the point is off the graph's node) is no way
    round.
  - Cost: **1 + legs** router calls: one `/route` for the way round, then a trace for each of its
    legs where it is answered (swapped in, or offered as `avoid_alternate`), and on Mass Ride and
    Group Ride a trace for each leg of the answer where not already remembered.
- **Bikeshare** (`core.bikeshare.plan`): the ride leg's `avoid_alternate` carries the plan's
  `bikeshare` (`alternate_block`: the same walks and docks, its own ride, total, ride step and
  summary) and the GBFS credit in its `attribution`, so it can be shown in place of the ride.

### The answer

Every route body has `avoid_junctions` (each pass: id, name, reason, point, metres along the
route scaled to `distance_m`, and `label`, the accessible name "Avoid-rated junction: <name>,
<reason>") and `avoid_notice` (335's sentence, null where none). The answer also has
`avoid_search` (passes left, their penalty, `decision` "kept" or "avoided", whether the way round
was found) and `avoid_alternate` (the way round as a whole route body, with `extra_distance_m`
and `extra_duration_s`). The description gains an `avoid` entry, severity "avoid": "Avoid-rated
junction ahead at 0.7 mi (1.1 km): <name>, <reason>. Riding through it is a really bad idea.
Please reconsider your route." (US units first). All additive.

The notice and the description's entry end with the plea, `routemaker.avoid_junctions.PLEA`
("Riding through it is a really bad idea. Please reconsider your route."; `PLEA_MANY` for
several), and the front end's `AVOID_PLEA` is the same words (a test holds them equal). The
owner, 2026-10-10 15:08 UTC, on the marker being named in the directions and the notice: "Yes, also when clicking on the intersection. Make it larger than a normal icon. Basically something to say: this is a really bad idea, please reconsider."

### The front end

- `lib/avoidJunctions.ts` (pure): the items, the row name, the offer ("Show the route that avoids
  it: 3.9 mi (6.3 km), 1.0 mi (1.6 km) longer"), and the marker's SVG; `lib/avoidIcon.ts` inlines
  the Noto Emoji skull (`icons/noto-emoji-u2620.svg?raw`, so nothing is fetched and the CSP is
  unchanged) on a dark disc (#1f2937) ringed in white, the halo of 310: the glyph's pale fills on
  the disc, the disc on a light map and the ring on a dark one are each above 3:1.
- `AvoidNotice.tsx`: first in the Route section, `role="alert"` so it is said as soon as it
  appears, ahead of the route's own sentence (which waits `ANNOUNCE_SETTLE_MS`). It is the chosen
  route's own notice (`avoidNoticeFor`): a route to choose from that avoids the junction has none,
  one that passes it has its own; the way round is the answer's, so its button (`aroundAvoid` in
  `App`, `shownRoute`) is offered only while the answer is chosen.
- The map marker (`MapView`, `.avoid-marker`) is a `<button type="button">`, as the junction
  markers are, so Tab reaches it, named by `avoidMarkerName` (the `label` and the plea); a click,
  a tap, Enter or Space opens the road panel on the junction, and the focus comes back to it when
  the panel closes. It is 40 px (`AVOID_ICON_PX`) against the junction markers' 24 ("Make it
  larger than a normal icon"; markers keep their size at every zoom). The junction list
  (`AvoidJunctionList`, its row name also ending with the plea), the description's entry and the
  notice show the Unicode character (310) with `aria-hidden`, and their words name the rating.
  Nowhere is the glyph's own name the accessible name (309). There is no legend row. The owner,
  2026-10-10 15:03 UTC: "For avoid markers in intersection. No need to put it in legend. You'll only see this if you really try to force things." (309's "It gets a legend entry" is superseded.)
- The road panel on the junction ("also when clicking on the intersection"): the marker opens
  the road panel (`RoadInfoDialog`) at the junction's point, and the panel opened any other way
  (a right-click, a long press, the I key, "Road info at map center") within `AVOID_SPOT_M` (25 m,
  82 ft) of an Avoid-rated junction on the route shown (`avoidNearSpot`) leads with a warning
  above its heading: "Avoid this intersection." and `avoidCardText` ("<name> is rated as
  dangerous for bikes: <reason>. Riding through it is a really bad idea. Please reconsider your
  route."). It opens the dialog's `aria-describedby`, so it is said as the panel opens; it is not
  also an alert (the two together were said twice). The front end knows only the junctions the
  route shown passes (the list is not sent otherwise), so the panel warns of those; the route
  that avoids it, shown in place of the planned one, passes none.
- Ride mode says an `avoid` entry as a hazard at every level but Quiet.
- The Mass Ride route chart (333) does not mark Avoid junctions: its intersection ticks have a
  table, a per-mile readout, a key and forced-colours rules, and a skull on the ticks alone would
  be seen and not heard. Left out (PLAN.md, FOLLOWUP-ISECT-AVOID); on Mass Ride the plan goes
  round one wherever the default limits allow.
- The icon's Apache 2.0 notice and licence ship in `licenses.txt` (`BUNDLED_ICONS` in
  `licences/notices.mjs`); the source record is docs/SOURCES.md and `fixtures/icons/README.md`.

### Tests

`tests/test_avoid_junctions.py` (the passes, the words, the score, `settle` with the Mass Ride
and Group Ride limits and loops, the stored list and counts, POST /api/route with a stand-in
router that routes round the junction only when it is excluded, a search that stopped before a
round, the guard's allowance, the exclusion radius, a long ride's legs, bikeshare's way round,
and the admin's counts, audited approval and withdrawal and a guild admin refused);
`frontend/src/lib/avoidJunctions.test.ts` (the glyph's sha256 and contents, the marker and its
size, the halo's contrast, the names, the plea against the API's, the offer, the chosen route's
notice, the road panel's spot and warning); `frontend/src/licences/notices.test.mjs`; the a11y
browser check's section 25 (the notice first and as an alert, the offer's name, the marker's
button and computed name, the list row, the description, the way round by keyboard and back, the
road panel's warning from a click on the marker, from Tab and Enter on it (the focus coming back)
and from the I key on the junction, none away from it, and that the legend has no Avoid row).

`scripts/a11y/check.mjs` reads the debugging port from `A11Y_CDP_PORT` (default 9222, as
`run.sh` starts Chromium), so it can run beside another browser:
`A11Y_CDP_PORT=9847 node scripts/a11y/check.mjs --port 5847`.

## Junction suggestions and junction overrides (FOLLOWUP-STRESS-SUGGEST, OWNER-DECISIONS 232)

"In some times the road is fine, but the intersection can be especially dangerous." The road
suggestions' twin for a node (operations: docs/OPERATIONS.md, "Junction suggestions").

### Storage

Migration `0018_junction_suggestions` (after `0017_mass_hazard`, one leaf) adds two tables:

- `core.models.JunctionSuggestion` (`junction_suggestion`): the junction's node (`lon`, `lat`, and
  `node`, the pair to 6 decimals as text, which the partial unique constraint "one waiting per rider
  per junction" is on), the roads there busiest first (`roads`, JSON), the level the map showed
  (`current_level`), the rider's level (`level`, nullable) and comparison (`direction`, "", "more"
  or "less"), the resolved `target_level` (2 to 5, a check constraint), the reason, the status (the
  roads' four), and what an approval made (`override` or `avoid`).
- `core.models.JunctionOverride` (`junction_override`): an approved level (2 to 4, a check
  constraint) at a point, `active` (withdrawn rows stay, for the record), the rider's reason as
  `evidence`. Made only by approving a suggestion; Avoid (5) becomes an `AvoidJunction` instead.

### Finding the junction

`core.junction_suggestions.locate` takes the nearest vertex, within `SNAP_MAX_M` (82 ft (25 m)), of a
`map_class = 'road'` row that another way also has a vertex at (within `road_names.TOUCH_M`): OSM
ways meet at a shared node, and a bridge over a road shares none. The names are the router's, then
the table's (`road_names.Names`, as the road suggestions' cross streets). Two ways and no second
name are a bend, refused: two pieces of one name, or two unnamed pieces (a named road meeting an
unnamed one is a junction). Nothing about the spot asked is kept.

### In the intersection model

`routemaker.intersections.Rating` (id, lon, lat, level) is the pure model's view of an active
override. `with_ratings` gives each `Junction` within `RATING_MATCH_M` (15 m, the Avoid junctions'
match) its `rating`; `assess` then returns `rated(...)`: the level's cost (`RATING_COST_FT`: the
all-way stop's 75 ft, the LTS 3 stopped-side crossing's 1,600 ft, the LTS 4's 4,000 ft, as the model sets them) and colour
(`RATING_SEVERITY`: none, orange, red), never capped, on the standard and the Mass Ride reading
alike (on the Mass Ride the event carries `group_severity`, so a rated signalized crossing still
joins a group), with the riders' words after the model's reason ("Riders rate this junction hard").
A junction the model has nothing to say about (two quiet streets) becomes an event of kind "rated".
"Easy" only ever lowers: it costs the lesser of 75 ft and the model's own figure for the ride time
(468a; a rating's own cost is not scaled by the hour), and where the
model has no event it adds none. Ratings apply to every movement through the junction.
`merge_nearby` lets a rated event stand for its own junction's other nodes, the events within
`RATING_MATCH_M` (15 m) of it along the route (`_rated_stand_in`); events farther off are other
junctions and merge as before (worst colour, the capped sum), so "easy" at one junction never hides
a red crossing 40 or 80 m on. A rated event takes no refuge credit (`_one_road`).

`core.junctions.events_of(..., ratings=)` keeps a raw junction that `wanted` would drop (no road
there can be busy) where one is rated, so it is read at all. The plan reads the active overrides once
at request time (`core.routing.plan`, `junction_suggestions.approved_ratings`, beside the Avoid
list) into `refine.Context.junction_ratings`, which `refine.events_of_raws` passes on: every
candidate, the answer's markers and the route description use them. No graph change, no rebuild.

### The front end

`frontend/src/lib/junctionSuggest.ts` (levels, what the route shows near a spot, the form's check,
the API calls, the one review list's entries); `SuggestJunction.tsx` (the form, two native radio
groups as fieldsets with `role="radiogroup"` named by their legends, each one Tab stop through the
road panel's Tab trap); `RoadInfoDialog.tsx` (asks `GET /api/junction-suggestions/at` only for a
rider who may suggest, and shows the button before Suggest a change; `InfoRequest.junction` opens
the form at once); `MapView.tsx` (the junction card's button, added once `fetchMe` says the rider may
suggest); `SuggestionReview.tsx` (roads' and junctions' suggestions in one list, oldest first, by
`ReviewEntry`, each kind at its own endpoints: `STRESS_REVIEW` in `lib/reviewSources.ts`, the review's first
source, beside the Mass Ride hazard reports' `HAZARD_REVIEW`; a source may answer part of its list with a
sentence naming what did not load, and an item may carry a `warning` that Approve now confirms first).

### Tests

`tests/test_junction_ratings.py` (the model: raising a quiet junction, lowering a red one, easy
never above the model, the group reading and Mass Ride groups, the 15 m match, the merge within
15 m and not beyond, the plan handing its ratings on);
`tests/test_junction_suggestions.py` (locate, the node kept, bends, the shown level, unclear choices
refused, the limits shared with roads, the database constraint, the three actions, Avoid and its
withdrawal, the poll's wording and its 4-decimal link, nothing about the rider);
`tests/test_suggestion_post.py`; `frontend/src/lib/junctionSuggest.test.ts`; the a11y browser
check's section 22c (the button and its description, the form's groups and Tab stops, Escape, the
empty send, the node sent, the card's button, the admin's list, Discord and Approve now, the
warning before approving a level that withdraws an approved Avoid junction, and a list that did not
load named).

The review list's junction entries carry `withdraws_avoid` (`avoid_withdrawn_by`: the approved Avoid
junctions within 15 m that approving would withdraw); where it is above 0, Approve now opens a
confirmation group with the warning before anything is sent.

### The beta's data shipment

`junction_override` and `avoid_junction` name a person (`created_by`, `approved_by`), and so does
`override`; `app_user` is not shipped, so a whole copy would break the restore's foreign keys.
`scripts/beta/ship-data.sh` ships them in `BLANKED_TABLE_DATA`: left out of the dump and written as
`db/blanked/<table>.copy` (COPY text format) from a SELECT with NULL in every person column. The
riders' words are blanked too: `junction_override.evidence` and `avoid_junction.evidence` ("Rider
suggestion N: <reason>", written by `junction_suggestions.approve`) ship as '', and an `override`
row's `reason` that an approved road suggestion wrote ("Rider suggestion N, approved: ...") ships as
"Rider suggestion (its reason stays at home)" (`reason=rider`); every other reason ships. It refuses
a table with a foreign key to `app_user` (read from `pg_constraint`) or a `*user_id` column not
listed. `receive-data.sh` loads them after the restore, and `--update-data` replaces `override` and
`junction_override` in its one transaction (a missing file aborts it).
`stress_edit` (the editor's history, `actor` a person) is excluded. `tests/test_beta_overlay.py`
reads every foreign key in `core/models.py` (bare, quoted or `settings.AUTH_USER_MODEL`) and fails
when shipped data points at an excluded table without that column blanked.

## Ride mode in dead spots and the 311 report (WEB-NAV N5-N7; OWNER-DECISIONS 369, 370, 465)

**The map in dead spots (N5).** At Start ride, and again for each re-plan's new route, RideMode calls
`keepCorridor(line)` (`lib/corridorStore.ts`), which fetches every tile within `CORRIDOR_M` (300 m,
about 1,000 ft) of the line (`corridorTiles`, `corridorJobs` in `lib/corridor.ts`): the stress tiles at
z14, 13 and 12 and the base map at z15 down to z12, deepest first and each in route order, leaving out
any a previous route of the ride already kept. `prefetchCorridor` runs them one at a time,
`STRESS_GAP_MS` (450 ms, after a random wait of up to `START_JITTER_MS`, 2 s, so riders behind one carrier NAT stay under the per-address tile limit) after a stress tile and `BASE_GAP_MS` after a base map tile; a stress tile goes
through `fetchTile` and so the protocol's page queue (two of the page's requests in flight, the API's
per-client draw cap, `TILES_IN_FLIGHT`) and its 429/503 backoff. At most `MAX_JOBS` tiles a route and
`MAX_BYTES` (40 MB) kept in all (`ByteBudget`: full once a take is refused, since tiles never fill it
to the byte, and freed again when bytes are given back); a tile counts as kept only when its write
succeeded (the Cache Storage put resolved, every IndexedDB range's transaction completed; a failed
write gives its bytes back), and the counts are per kind; a kind failing `STOP_AFTER_FAILURES` times in a row is
dropped (no signal at the start, or a base map that is not served); from a kind's second failure in a row the next
tile waits `FAILURE_WAIT_MS` (1 s), then 2 s, then 4 s, so a kind is dropped only after about 7 s without a
signal and a brief loss (a cell hand-off) no longer drops it for the whole ride; a lone failure waits only
the kind's gap, so a patchy signal does not hold the other kind back. Where they are kept:

* Stress tiles: the Cache Storage bucket `routemaker-corridor-v1`, keyed by the tile's URL without its
  `?rev=` (`stressKey`), the edit generation kept beside it in a header, so an admin's edit mid-ride
  replaces the tile rather than orphaning it. The protocol's loader (`loadTile` in
  `lib/stressProtocol.ts`, given `corridorStress` by App) during a ride reads a kept tile of the same
  generation first (in a real dead spot the phone often still says it is online, and a request hangs
  rather than fails), then gives the network `NETWORK_TIMEOUT_MS` (6 s, above the 5.46 s cold draw in docs/OPERATIONS.md) before falling back to a kept
  tile of any generation; it keeps each tile the map loads during a ride. Outside a ride the bucket is
  neither read nor opened (opening would create it).
* The base map: `region.pmtiles` is read by HTTP range, and Cache Storage refuses 206 answers, so
  MapView adds the protocol's archive itself (`basemapArchive`), a `PMTiles` over a `CorridorSource`
  over the usual `FetchSource`. While keeping, it stores every range it reads (header, root and leaf
  directories, tiles) in IndexedDB (`routemaker-corridor`, store `ranges`, keyed `offset:length`) with
  the archive's ETag (an answer with no ETag is not kept, since a later file could not be told
  apart); a range asked for with that ETag is answered from the store first, the header
  (asked with none) from the network first, and any kept range answers when the network fails. A new
  ETag (the archive refreshed under the same name) empties the store. Outside a ride with nothing kept,
  the store is never touched: a first IndexedDB open takes about a second, and a header refusal held
  back that long kept MapLibre's style from loading in the browser suite.
* Glyphs (the style's Latin stacks, `fontStacks`, ranges 0-255, 256-511 and 8192-8447) and the sprite:
  fetched once into the browser's HTTP cache, which the edge lets keep them a day
  (`/basemap/fonts/*`, `/sprites/*`: `private, max-age=86400`) and which answers MapLibre's own
  requests with no network.

What is kept is for one ride: a ride never outlives the page (the service worker keeps the app, never a ride). End ride clears
it (`clearCorridor`, from RideMode's unmount), the next ride's first `keepCorridor` (`first`) clears
before it fetches, and a time stamp in localStorage (`routemaker.corridor`, a time and never a place)
lets the next page load clear whatever an earlier page kept (`sweepCorridor`; a page that never rode
opens nothing). The clears run in order on one promise chain and End ride bumps a generation, so a
quick Start ride after End ride waits for the clear and a `keepCorridor` still waiting when End ride
comes starts nothing. RideMode shows `corridorWorry` under its controls only when nothing along the route could be kept
("Map not saved offline: it needs a signal."); a part kept, or one kind of tile only, shows nothing
(the owner, 2026-10-27, of the older per-kind note: "This prompt made no sense"). It is not said,
since it changes nothing the rider must do. A re-plan still needs a
signal.

**The 311 report (N6).** "Report a problem to DC 311" (`Report311` in `RideMode.tsx`,
`lib/report311.ts`), inside DC only (`inDc` on the rider's place on the line). DC's Text to 311 page
(ouc.dc.gov/service/text-311, read 2026-10-10) gives the short code 32311 and the keywords POTHOLE,
STREETLIGHT and TRASH that go straight to a request; it names none for a fallen tree, and anything else
goes through MENU to "Other Service Requests", which sends the texter to 311 Online. So Pothole and
Streetlight out, on a phone (`canText`: Android, iPhone, an iPad that says it is a Mac), are a Text to
DC 311 link first, `smsHref` (iOS reads `sms:32311&body=`, Android `sms:32311?body=`, RFC 5724),
named "Text to DC 311 (3 2 3 1 1)" so a screen reader reads the code digit by digit. "Open DC 311
online (new tab)" (https://311.dc.gov/) and Copy the report are always there too, since a tablet or a
phone may not send texts; for Something else, and on a desktop (370), they are the way. `reportText`
is "Location: <place>, Washington, DC. GPS <lat>, <lon>." then the rider's note (at most 120 characters), shown and
copied as is; the text adds DC's keyword in front (`forText`), which a hint says. US units only, since
it is the message itself. Whether DC's service reads a keyword and a place in one message is not
verified until a real text is sent (the owner's).

The kinds (`REPORT_KINDS`; the owner, 2026-10-11: "311 should have the following at least: Pothole /
Downed tree / Vehicle parked in a bike lane / Roadway/bikeway obstructed"), in this order: Pothole (the
default), Downed tree, Vehicle parked in a bike lane, Roadway or bikeway obstructed (the owner's words, with "or" for
the slash, which a screen reader reads aloud), Streetlight out, Something
else. DC's page (read again 2026-10-11) still names keywords only for POTHOLE, STREETLIGHT and TRASH, so
the three new kinds go to DC 311 online like Something else, and their words name the problem first
(`problem`: "Downed tree. Location: ...", "Vehicle parked in a bike lane. Location: ...", "Roadway or
bikeway obstructed. Location: ...") so DC knows what it is without a note; Something else still relies
on the note, and its hint says so. The hint beside DC 311 online (`onlineHint`) names the request there
where one is known: DC GIS's open service requests of the last 30 days
(https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/SR_30days_Open/MapServer/0, distinct
`SERVICECODEDESCRIPTION`, read 2026-10-11) include "Tree Inspection", "Tree Removal" and "Parking
Enforcement", and DPW places its bike lane enforcement officers partly by 311 requests
(dpw.dc.gov/node/1442566, 2019-11-12, read 2026-10-11). Neither says which request a vehicle in a bike
lane is (DPW's "Request Parking Enforcement" page, https://dpw.dc.gov/service/request-parking-enforcement,
read 2026-10-11, lists meters, permits, driveways, bus stops, crosswalks and hydrants, not bike lanes),
so its hint says only that DC's parking requests include Parking Enforcement. No request for an obstructed roadway or
bikeway was found there, and 311.dc.gov's own form could not be read (its robots.txt refuses fetches),
so that hint names none.

The place is `reportPlace` (`lib/report311.ts`), from the route's own data, never a lookup with the
position (plan section 7, owner question 7). Since v0.6.0 (the owner, 2026-10-12: "Put the GPS
coordinates in the 311. Sometimes it says, about 1.2 miles south of unnamed path." and "Description if
you can. Like put the road and the coordinates"): the way the rider is on at that point (`stretchAt`,
the route's own street name, "on R Street Northwest", "on Capital Crescent Trail"; a way with no name is
said plainly, "on an unnamed path" or "on an unnamed road"), then a cross street only when a named
junction of the route (`routeJunctions`: each change of named street and each flagged crossing) is
within `PLACE_NEAR_M` (500 ft, about 0.1 mi; "on R Street Northwest near Q Street Northwest"), and
always the GPS position, latitude first in decimal degrees to 5 places (about 1 m), the point on the
line the words describe (`pointAt`): "Location: on R Street Northwest near Q Street Northwest,
Washington, DC. GPS 38.91234, -77.03890." A distance from a far junction ("about 1.2 miles south of
...", the old trail marker) is never said: it named unnamed ways and helped no one find the spot. The
coordinates are never trimmed; the only cap is the note's 120 characters. The 311 menu's place line
(`menuPlaceLine` in `lib/ride311.ts`) shows the same words and coordinates. Where am I? keeps its trail
marker (`placeOnRoute`, `TRAIL_MARKER_M` in `lib/navigate.ts`), measured only from a junction on the
trail itself with a named street; an unnamed way (`isUnnamed`, `wayRidden`) is said plainly ("On an
unnamed path.") and is never used as a trail or a reference point.

**Trail mile markers (v0.8.0).** 465: "some trails like the MBT and CCT should have mile markers as
they can go a distance without crossing a road"; Stephen, 2026-10-16: "Make sure the mile markers are
added to 311 when built." `lib/trailMiles.ts` reads `amenity-data/trail-miles.json`, a committed
snapshot built from the extract by `scripts/build_trail_miles.py` as the water, food and places files
are (`frontend/src/amenity-data/README.md`, "Trail mile markers"): no tiles, no Valhalla, no API, so
no map rebuild, only that script on the build host. The file holds the OSM mile markers
(`highway=milestone` or `waterway=milestone` with `distance=*`, or "Mile 3", "MM 3", "MP 3" in `ref`,
`name` or `inscription`; `railway=milestone` and an old road's `historic=milestone` are not trail
markers), each with the named trail it stands on (within 80 ft, 25 m) and its posted figure in miles.
A post nearer a main road (motorway, trunk, primary, secondary or their links) than the trail is the
road's (I-66's mileposts beside the Custis Trail) and is left out. The file also holds lines, each
piece of a named trail over 2 miles (3.2 km) drawn from cycleways and `bicycle=yes`/`designated`
ways, from its mile 0 with `s`, the metres at the line's first point, but only where mile 0 is known:
two or more of its posts that fit (posted miles grow 0.8 to 1.25 a mile along, none more than a
quarter mile off; `s` their median), one post (`s` from it), or the build's `MILE_ZERO` table (the C&O
Canal towpath and the Capital Crescent Trail from Georgetown, the Metropolitan Branch Trail from Union
Station, the W&OD from Shirlington) with its mile-0 point within about a mile of the piece's end. Any
other line is left out, so no mile is guessed: a trail not in the table and with no posts gets none,
and a piece split from the rest by more than a quarter mile (400 m) never restarts at mile 0. The
Mount Vernon and Custis trails stay out of the table until their posts' numbering is checked; their
posts still work. The build fails (exit 1, nothing written) over 600,000 bytes. The docstring has the
rest, with the OSM wiki pages it follows.

All of it is worked out on the device, with the trail's name from the route (the stretch's street,
the way's OSM name, matched by `trailKey`, worked out once per row as the file is read: case, "&" and punctuation aside) and the point the report
already uses (`pointAt`): the position goes nowhere new. `trailMileAt` gives the nearest post of that
trail within `MARKER_NEAR_M` (500 ft, about 0.1 mi, as `PLACE_NEAR_M`), else the computed mile on the
nearest of its lines within `LINE_NEAR_M` (200 ft, 60 m; to a tenth, never below 0), else a post within
half a mile, else nothing. `mileWords` says it: "mile marker 3" (as the post says it), "near mile
marker 3" (a post farther than 500 ft, with no line), "about mile 3.2" (computed, never passed off as
a post). Miles only, as a post says miles and the report is the message itself.

* The 311 report: `reportPlace(model, progressM, miles)` adds it after the way ridden on any named way
  the file knows, `placeWords`: "on Capital Crescent Trail at mile marker 3", "on Capital Crescent
  Trail at about mile 3.2 near River Road" (a cross street within 500 ft still follows), then
  "Washington, DC. GPS ...", the coordinates beside it as before. The 311 menu's place line, the copy for
  DC 311 online, the text and the server's send all carry the same words.
* "Where am I?": on a trail the file knows and away from a junction (`placeOnRoute` not a junction),
  "On the Capital Crescent Trail, at about mile 3.2." in place of the distance from a junction of it,
  which stays where the file has no line or post (465: "Navigation cues on those trails can use the
  same markers"). Turn cues are unchanged: they already name the street turned onto.
* The road panel: for a trail way, a "Trail mile" summary line after the server's, at the nearest
  place on the way (`on_way`, else the spot): "Mile marker 3, 300 ft (91 m) away" or "About mile 3.2
  here" (`milePanelRow`), US units first.
* The map: the posts from z14 in (`MILE_MIN_ZOOM`), always, with no switch (the owner keeps Go to one
  control a feature): a small brown dot with a white ring and "MM 3" beside it in text with a halo
  (`TrailMilesOverlay`, `app/trailMilesOverlay.ts`, the v0.7.0 overlays' way), under the route; a tap
  gives a card in words ("Capital Crescent Trail", "Mile marker 3.", "From OpenStreetMap."), and the
  road panel is the keyboard's and screen reader's way to the same facts. The lines are never drawn.

App fetches the file once the map reaches z14, a ride starts or the road panel opens; it is under
`/assets/` and not a `LAZY_ASSET`, so the service worker precaches it and a ride has it in a dead
spot. Until the build host fills it the file is empty and every place reads as before.
`trailMiles.test.ts`, the trail cases in `report311.test.ts` and `navigate.test.ts`, and
`tests/test_build_trail_miles.py` (which builds from a small made-up extract) check it.

**Checks (N7).** `corridor.test.ts`, `report311.test.ts`, the trail cases in `navigate.test.ts` and
`loadTile` in `stressProtocol.test.ts`; the browser suite's Ride mode section checks that the stress
tiles along the mocked route are kept at z12-14, that one answers the tile loader at once with the
network emulated offline (`Network.emulateNetworkConditions`; the mock serves no base map archive, so
its ranges are not shown there), that End ride clears the bucket and empties the IndexedDB store, and the report's words, links,
radios, note field and 44 px targets, on a desktop and (with an Android user agent) a phone. The ride
on a real phone with a tandem captain and a blind stoker, and a dead-spot ride, are the owner's.

## The installable app (WEB-NAV P1-P4; OWNER-DECISIONS 434, 465, 465a, 465b)

**Manifest and icons (P1).** `frontend/public/manifest.webmanifest` names the app RouteMaker, opens `/`
standalone (Q8, 465) with scope `/`, and lists four icons: 192 and 512 px, `any` and `maskable`.
The icons, the 180 px `apple-touch-icon.png` and `favicon.ico` (16, 32 and 48 px, for Google's favicon
service: OPERATIONS.md, "The connector's icon"), are drawn from `frontend/public/favicon.svg` (Q10,
465b) by `python3 scripts/make_app_icons.py`, which renders the SVG with Chromium's headless shell
(full Chrome's `--headless=new` crops the bottom of a small window) and is run again only when the
favicon changes; the PNGs are committed. The maskable icons draw the glyph at 75 % on full-bleed blue,
so a launcher's circle or squircle cuts nothing. The same run draws the Android app's icons from the
favicon: the adaptive icon's vector foreground (also its monochrome layer, for Android 13 themed icons)
inside the 66 dp safe circle, its blue background, the round and square PNGs for Android 7, and the
launch screens (`mobile/android/app/src/main/res/`). The icon is the owner's design of 2026-10-18 (a
route line running into a bicycle with a map pin in the front wheel), redrawn by hand as strokes.
The favicon's own `<style>` doubles the stroke widths when it is drawn 40 px or smaller (a browser
tab), where the full-size lines blurred.
`index.html` links the manifest with
`crossorigin="use-credentials"` (so the beta's password is sent with it), carries the light and dark
theme colours and the Apple tags.

**The service worker (P2).** Hand-written, no Workbox: `frontend/src/sw/swCore.mjs` is both the worker
and a module the tests import. The Vite plugin `swPlugin.mjs` (`appWorker()` in `vite.config.ts`)
writes `index.html`'s `<meta name="routemaker-build">` and emits `dist/sw.js` (the module with its
`export` words dropped, then the build id and the list of every `/assets/*` file) and `dist/sw-kill.js`.
Its rules (`ruleFor`, an allowlist; the table is at the top of the file): the shell network first,
falling back after `SHELL_TIMEOUT_MS` (3 s) to the kept copy; `/assets/*` precached and cache first,
but for `LAZY_ASSET` (the Find food places, `/assets/food-*.json`, about 555 KB compressed, and the
Climbs layer's `/assets/climbs-*.json`, about 400 KB compressed, off until turned on), which no
install downloads: kept in the build's cache on first use, and copied into the next build's cache at
its install while its hashed name is unchanged (`lazyList` in `swPlugin.mjs`);
the favicon, icons and licence notices stale-while-revalidate; the base map's glyphs and sprite from
the kept routes' bucket first. Everything else is not intercepted at all (no `respondWith`):
`/api/*`, `/auth/*`, `/tiles/*`, the base map archive, the admin, every other navigation and every
non-GET. Nothing private is cached. Matches use `ignoreVary` (a module script's request carries Origin
and the precache's did not, so an edge that varies on Origin, as `vite preview` does, missed every one).

A new worker precaches only when the edge's `index.html` carries its own build id (`precache`), so a
deploy caught half published fails the install and the browser retries on the next load. It then
waits; `lib/appWorker.ts` (registered only in a production build in a secure context, with
`updateViaCache: 'none'`, checked again at most hourly when the page comes back to the front) shows
"A new version of RouteMaker is ready" with Reload at the top of the planner (`AppStatusBar` in
`InstallableApp.tsx`), said once through App's live region and held during a ride. Only Reload sends
`SKIP_WAITING`; activate deletes older builds' caches (never the kept routes'). The kill switch,
`swKill.mjs`, deletes the worker's own caches, unregisters, and reloads only the pages it controls (no
loop); the owner copies it over `sw.js` on disk (OPERATIONS, "The app's service worker").

**Routes kept for offline (P3).** "Keep for offline" under a route's figures, in the installed app
(465a) and in a browser tab (the owner's choice of 2026-10-10; `keepOffered` with its one switch
`KEEP_IN_BROWSER_TAB` in `lib/offlineRoutes.ts`;
`keepForOffline` in App, `lib/offlineKeep.ts`) saves the plan, its API answer and its title first (IndexedDB
`routemaker-offline`, store `routes`), then walks the corridor with N5's `prefetchCorridor` (same
pacing and caps) into its own store: base map ranges in the store `ranges`, stress tiles, glyphs and the
sprite in the Cache Storage bucket `routemaker-offline-v1` (`lib/offlineRouteStore.ts`). It asks
`navigator.storage.persist()` at that press. At most `MAX_KEPT` (10) routes of the rider's; the last
ride is one more, replaced by the next. A route is kept under `keptPlanKey`: the plan the route on
screen answers (set with the answer, so a keep during a re-plan in flight files it under its own plan),
without Mass Ride's ride size, which the planner never gets; the scheduler's offline lookup, the last
ride and Settings' Open use the same key (Open keeps the ride size set now). The record names each
tile and range before it is written (`progressSaver` writes the record every 2 s and at the end), and
keeping a plan again starts from what its record named (`keptRecord`). Tiles are shared between routes,
so the Web Locks lock `routemaker-kept` orders every tab: a keep and a hand-on hold it shared for their
whole run, the final record write included; Remove's freeing, the last ride's replacement and
`sweepKept` (what no record names, after a Remove and 20 s after load) take it exclusive and work out
what to free only once they hold it. Remove deletes the record at once and frees later; Remove of the
route being kept stops that keep and waits for it first (and that keep's press stays quiet). Whatever
decides what to free reads the list strictly (`listKeptOrThrow`): iOS drops the IndexedDB connection
after the app is in the background, and a read that fails frees nothing (a keep then fails) rather than
reading as "no routes". Without Web Locks this page's keeps wait for a freeing asked for before them,
freeings take turns and wait for the keeps before them, and the sweep is skipped (`keptLocks`; `offlineKeep.test.ts` runs each order with an
in-memory store and a fake lock manager). Start ride stops a keep still fetching, and the last ride's
freeing waits for its final write.
In the installed app (465a) the last ride's route is kept automatically: at End ride, RideMode's
`clearCorridor(lastRideAdopter())` hands the ride's own corridor over, so nothing is fetched twice. End
ride stops keeping at once and runs the hand-on inside the clears' chain, so a quick Start ride waits for
it and is never stopped by the old ride's clear. The hand-on is bound to its ride's record (the savedAt
taken at Start ride) and adopts nothing into a next ride's record that got there first.
Reading back: `CorridorSource` takes a read-only `fallback` (the kept ranges), consulted only when the
network fails; `corridorStress.kept` reads the ride's copy and then the kept routes'. When a plan
request fails with a network error, App's scheduler answers from the kept route with a notice that it
may be out of date (`offlineRouteNotice`); a planner error is shown as usual. Settings lists them
(`KeptRoutes`) with Open and Remove; Remove frees only the tiles and ranges no other kept route uses
(`orphans`); a failed Remove says so. With nothing kept the store is never opened (`anyKept`, a count
in localStorage): a failed base map range waiting on a first IndexedDB open kept MapLibre's style from
loading. Nothing kept holds a position (a unit test checks).

**Install offer (P4).** `watchInstall(window)` in `main.tsx` holds `beforeinstallprompt` before the
first render and hears `appinstalled`. `InstallOffer` (Settings, and short in More tips) shows "Install
RouteMaker", the iOS line "Press Share, then Add to Home Screen." (any iOS browser has it), or a
note that it is installed when running standalone. Never a pop-up. After the browser's dialog the
outcome stays as a note and the focus goes to the heading (Settings) or the note (More tips).

**Accessibility.** Real buttons, 44 px tall, whose names include the route (visually hidden text);
offline, back online (not said during a ride), the new version, kept, removed and the install outcome
said politely once; after a Remove the focus goes to the next row's Remove, else the heading
(`focusAfterRemove`). Forced-colours styles for every new part.

**Tests.** `node --test frontend/src/sw/swCore.test.mjs` (the rule table row by row, precache's build
check, activate, the kill switch, the generated scripts run in `vm`); `npm test` (node's test runner)
for `appWorker`, `installOffer`, `offlineRoutes`, the `CorridorSource` fallback and End ride's hand-on
order (`corridorStore.test.ts`); the browser suite's installable-app
group runs against `vite preview` of a build (`--preview-port`, default 4173; `--cdp` picks the
debugging port), with offline emulated on the page and the worker's target,.

## Course export: FIT and TCX (v0.7.0, "All the sharing and export")

Plan's GPX section (the GPX sheet; Go's Menu opens the same sheet with GPX alone, so Go gains no control) has a
"File type" choice, GPX track, FIT course or TCX course, and for a course a "Device" choice; the button is
"Download GPX", "Download FIT" or "Download TCX". The choice is remembered on the device (localStorage, guarded;
the defaults, GPX and "Any bike computer", stand without it). A course download is checked against the closures in
force as Download GPX is (App.tsx `downloadCourseRoute`), and the line saying what was fitted to the device is said
in the section's existing polite status region ("FIT course for Garmin Edge: all 42 cues and 3,120 points fit.").
An opened GPX file still downloads verbatim as GPX; a course is always the route shown.

- **One compiled route** (`frontend/src/lib/course.ts`, `compileCourse`). The line and elevations are the GPX
  export's (`gpxText.ts elevationsAlong`); the cues are Ride's (`navigate.ts rideModel`), so a turn is "Left onto R
  Street Northwest." and nothing else. Each cue is pinned to its nearest record. Via points are not cues, as in
  Ride. The plan's points are Start, Stop N and Finish: a saved place's label (Home) is never written.
- **Times** are the route's moving time spread along the line from 2000-01-01T00:00:00Z, never the clock, so one
  route gives the same bytes every time (PLAN.md, Clean exports).
- **Device profiles** (`frontend/src/lib/deviceProfiles.ts`, the profile table): Any bike computer (the default),
  Garmin Edge, Wahoo ELEMNT, Hammerhead Karoo, each with a cue budget (200, PLAN.md's default), a point budget
  (10,000; 20,000 for Wahoo and Karoo), a file-size budget (4 MB; 8 MB for Wahoo and Karoo) and name lengths (15;
  32 for Wahoo and Karoo). The size budgets are unverified working figures, not limits measured on a unit or
  published by a maker. `verified` is null on every row: none has yet been loaded on its device. Record the date
  there when one is.
- **Over the cue budget** the least important go first: notes on busier, calmer or unpaved stretches, then flagged
  crossings (orange before red), then turns onto unnamed ways, then named turns and walks; within a rank, the cue
  nearest the one before it. Never dropped: start, finish, stops, Avoid-rated junctions and work zones. Where those
  alone pass the budget, nothing is dropped (giving up the turns would still not make it fit) and the line says to
  split the route.
- **Over the point budget** the line is thinned by Douglas-Peucker at the smallest of 1, 2, 5 and 10 m that fits,
  every cue's record kept; the line says the tolerance ("within 3 ft (1 m) of the route"). **Over the size budget**
  (the written file measured) it is thinned further, doubling past 10 m (20, 40 ... m), until the file fits; one
  that still does not is said ("still larger than the 4 MB it takes").

The cue mapping (PLAN.md: "The mapping table names every collapse for every format"). The turn model gives left and
right only today (describe.py has no slight, sharp, u-turn or fork yet), so FIT's richer types are not written.

| Cue (course.ts)                | FIT course_point type | TCX PointType | Name (FIT; TCX cut to 10)  | TCX Notes            |
| ------------------------------ | --------------------- | ------------- | -------------------------- | -------------------- |
| start                          | generic (0)           | Generic       | Start                      | Start.               |
| left / right turn              | left (6) / right (7)  | Left / Right  | street, abbreviated; else Left / Right | Ride's words |
| hazard: Avoid, work zone (never dropped) | danger (5) | Danger      | street, abbreviated; else Caution | Ride's words  |
| hazard: flagged crossing (can be dropped) | generic (0) | Generic    | street, abbreviated; else Caution | Ride's words  |
| walk                           | generic (0)           | Generic       | Walk bike                  | Ride's words         |
| busier, calmer, unpaved notes  | generic (0)           | Generic       | Busy road / Calmer / Unpaved | Ride's words       |
| stop                           | generic (0)           | Generic       | Stop N                     | Stop N.              |
| finish                         | generic (0)           | Generic       | Finish                     | The end of the route. |

FIT has no notes field, so a course point carries its short name only. Only the warnings a course never drops are
danger (PLAN.md: "danger-type cues are never dropped"), so a flagged crossing, which the cue budget can drop, is a
note.

**FIT** (`frontend/src/lib/fit.ts`) is written here to the FIT protocol and Global Profile, with no library: PLAN.md
named fit-tool (BSD-3, Python), but the export runs in the browser beside the GPX export, and a course needs only
plain records and the CRC. Protocol 1.0, profile 21.00, little-endian, normal headers. Messages, in order:
file_id (type course, manufacturer development, product 0, time_created the fixed base, number a 16-bit fold of
an FNV-1a hash of the file's bytes after file_id, so two courses do not share a file_id; no serial number), course
(name, sport cycling), lap (start and end time and position, elapsed and timer time, distance, ascent, descent),
event timer start, the records (time, position, altitude, distance), event timer stop_all, the course points
(index, time, position, distance, type, name). No file_creator, device_info or user profile. Attribution: FIT has no
notice field, so the course name carries " (c) OSM" (plain ASCII: a unit's font may have no ©): the longest
wording of the name that leaves room for it is used, and only where none does the name alone, with the GPX
section's hint carrying the credit beside the download (PLAN.md's recorded FIT carve-out). Altitude is held to
uint16's range (-500 m to 12,606 m).
`fit.test.ts` decodes each file back with a reader driven by the file's own definitions, checking both CRCs; the
same file was also decoded with fitdecode 0.10.0 (MIT) once, by hand (before file_id carried its number), with every message and field read as
written. Not yet loaded on a real head unit.

**TCX** (`frontend/src/lib/tcx.ts`): TrainingCenterDatabase v2, Course_t's order (Name, Lap, Track, Notes,
CoursePoint), the course name cut to 15 characters and point names to 10, the full cue in CoursePoint/Notes, the
route's credits in Course/Notes. No Author or Creator element. Not validated against Garmin's XSD in the suite (the
schema is not in the repository) and not yet loaded on a device.

Tests: `course.test.ts` (cues, pinning, Home naming, budgets, thinning, names, the trimmed line, TCX), `fit.test.ts`
(the round trip), `courseWiring.test.ts` (the section's controls, its live region, no control in Go).

## PDF cue sheets (v0.7.0, "All the sharing and export")

The same "File type" choice in Plan's GPX section has two more entries, "PDF cue sheet, to print" and "PDF handlebar
strip, to print"; the button says "Download PDF", there is no Device choice for them, and Go is unchanged (GPX
alone). The download goes through the same closure check as a course (App.tsx `downloadCourseRoute`), and its line
("PDF cue sheet: 42 cues, on letter paper.") is said in the same polite status region. Marshal sheets, the
intersection list and the agency packet are not built yet.

- **The cues** are the FIT and TCX courses' (`course.ts routeCues`, Ride's `rideModel` cues with the start first),
  never trimmed to a budget: paper has room. Rows: miles from the start with km in brackets (`format.ts
  formatMileMarker`, always tenths, never feet), the turn (Start, Left, Right, Caution, Walk, Note, Stop N,
  Finish), the road as the API names it, and Ride's words as notes where the turn and road do not say it all.
- **The rider sheet** (`frontend/src/lib/cueSheetPdf.ts`): US Letter, the GPX export's name (`exportName`: ride
  type and distance), distance, climb, descent and moving time, the route's warnings (the Avoid notice, the
  traffic-tolerant warning, parks to check before you go), the cue table, and the credits. **The handlebar strip**:
  a 3 by 11 inch page to print at actual size and cut out, the miles at 16 pt, the turn and the road (abbreviated
  as on a unit's screen, "17th St NW") at 13 pt, a caution's short reason (Avoid-rated, Work zone, Crossing) small
  under it, no notes on busier, calmer or unpaved stretches. Flagged crossings are notes to a course (the FIT and TCX
  budget can drop them) but a Caution on paper, as Ride says them.
- **No place is named**, so a Home never is: the name is the ride type and distance, the plan's points Start,
  Stop N and Finish. Credits are `creditLine` (the GPX export's words) in every page's footer and once at the end.
- **The writer** (`frontend/src/lib/pdf.ts`), with no library: PDF 1.7, the standard Helvetica faces in
  WinAnsiEncoding (not embedded; widths in docs/SOURCES.md), uncompressed ASCII content. Tagged, not
  PDF/UA-conformant (standard fonts not embedded, no XMP): a structure tree of Document, H1, H2, P and Table
  (THead and TBody, TR, TH with column scope, TD), each text run a marked-content sequence in the parent tree;
  footers, rules and a table header carried onto a later page are Artifacts; /Lang en-US, /MarkInfo (Marked,
  Suspects false), DisplayDocTitle, /Tabs /S. The bottom margin is set from the footer's measured height; a heading
  is kept with what follows it, and the table header with its first row at that row's height. Clean and reproducible: Info has the title and Creator RouteMaker only (no
  author, producer or dates) and the /ID is a hash of the body, so one route gives the same bytes.

Tests: `cueSheetPdf.test.ts` (the rows, units, warnings, Home, credits, the xref and trailer, the structure tree,
paging, determinism, the writer's encoding and wrapping), `courseWiring.test.ts` (the two file types, no device
choice for them, one button). Checked by hand once with poppler (`pdfinfo` reports Tagged: yes and reads the
structure tree in order; `pdftotext` the text layer) and pypdf in strict mode; not yet checked with a PDF/UA
validator or read aloud by a screen reader.

**Cue sheet image, for a phone lock screen** (the owner: "a lot of people take pictures of them on their phones and
use them as lock screens"): one more entry in the same choice, "Download image". A PNG drawn on a canvas in the
browser (`frontend/src/app/lockScreenRender.ts`) from a pure layout (`frontend/src/lib/lockScreen.ts`): 1179 by
2556 (an iPhone Pro; an Android phone fits it), white with dark text, the strip's rows in large type (miles 96 px
with km small, the turn 64 px with a caution's reason, the road abbreviated 60 px). The top 28% and bottom 12%
are left clear for the lock screen's clock and controls; the name and distance sit small under the top band and
the credits small above the bottom one. Rows that do not fit go on further images, each headed "Part N of M"
(`...-lock-1-of-3.png`). Where the browser can share files (a phone), all of them go to one share sheet; otherwise
(a browser saves only one file per press) part 1 is saved and the same button becomes "Download part 2 of 3" and
so on, no new control. The status line says only what was saved or sent. No place is named. Tests:
`lockScreen.test.ts` (the bands, the width, cues per image and all of them once, naming, the line). Not yet
drawn on a real phone's lock screen; the layout was checked by eye from a rasterised copy, not from the canvas.

## Rider roles on a Mass Ride or Group Ride link (Stephen, 2026-10-16)

The one question a ride link asks ("Show me as a dot to others on this ride?") also asks "Riding as":
Participant (already chosen, so Yes alone answers), Lead line, Sweep or Corker. The role is kept with the
answer for that ride on the device (`rideGroup.ts keepConsent`; in the question a compact "Riding as" list)
and changed in the riders panel, under "Show me as a dot", where the next position goes as soon as the server
takes one (within 15 s); Go's bar gains nothing. Each position the page sends carries the role
(`POST /api/rides/{ride}/here`, `role`); `core.ride_presence` takes the four ids only (anything else is a 400,
none sent is a participant) and answers each dot's `role`. Still no name, token or id on a dot.

- **Self-declared.** A ride link has no sign-in, so the server cannot know who leads or sweeps: a role is what
  that phone chose, nothing more. Anyone on the link can mark themselves Sweep. Do not build anything that
  trusts a role (an alert only a lead can send, say) without an identity behind it first.
- **On the map** (`rideDotsLayer.ts`): a colour and a shape for each role, so neither carries it alone. A
  participant is a small blue dot (#0000ee); the lead line a near-black violet chevron (#220044) turned to
  point the way the route goes at that spot (`project().bearingDeg`; on an out-and-back the pass nearest the
  mark's last place along the route, its own layer aligned to the map); the sweep a magenta square (#7a1f7a);
  a corker a dark grey diamond (#444444). Chosen by a search, not from a palette: an orange lead vanished on
  the LTS 3 and 4 lines and a blue-black sweep was Avoid's line. Each is 3:1 or more on every light-map
  surface and from its white edge, every pair 15 or more CIEDE2000 apart and each 7 or more from every route
  line and casing colour, under normal vision and each simulated deficiency. Four fills 3:1 apart from one
  another cannot also all be 3:1 on the light map, so the white edge and the shapes separate touching marks.
  The marks are images drawn pixel by pixel; the age rules are unchanged (solid, white hole, hollow outline,
  gone at 2 minutes).
- **In words.** Tapping a mark says "Sweep, 0.5 mi (0.8 km) behind. Seen 40 s ago." The riders button's
  summary adds the nearest of each role on the ride after the nearest rider. The panel's key lists only the
  roles present, each with its swatch (decoration, `aria-hidden`; kept in its colours in forced-colours mode)
  and its count in words.
- Tests: `tests/test_ride_presence.py` (validation, default, the role on the dot) and
  `frontend/src/lib/rideGroup.test.ts` (kept role, the body, the images and layers, colours, names, the key,
  the page's wiring).

## Phone app (v0.8.0)

The owner, 2026-10-16: a standalone app is needed for bikeshare riding with the phone in a pocket,
because a browser's cues stop when the screen is off. `mobile/` is a thin Android app (Capacitor 8)
that opens the live site; `mobile/README.md` is the full account (install, workflow, permissions,
screen readers). No build carries the site's address (a public repository's Actions artifacts are
public): the app's first-launch screen (`SetupActivity.java`) asks for it, https only, checks it
against `/healthz` (`SiteAddress.java`, unit-tested in `app/src/test`) and keeps it in the app's
preferences; `ROUTEMAKER_URL` is a local build's override only, refused when `CI` is set. The site's
side:

- `frontend/src/lib/nativeShell.ts` finds the shell through the injected `window.Capacitor`
  (`isNativePlatform()`, `nativePromise`, `nativeCallback`); no Capacitor package is in
  `frontend/package.json` or the bundle. In a browser `shell` is null and `rideGeoEnv()`,
  `rideSpeech()` and `rideWake()` return `browserRideEnv()`, `browserSpeech()` and `browserWake()`, so
  the site is unchanged.
- In the shell, Ride mode (`RideMode.tsx`) gets the background-geolocation watch behind the same
  `RideGeoEnv` (`watchRide` is unchanged; Start ride's watch first asks location, then notifications,
  through `askRidePermissions`, and only then adds the watcher with the plugin's own request off, since
  plugin 1.2.26 would start its foreground service before the grant and Android 14+ refuses that; End
  ride's `clearWatch` removes the native watcher, which stops the foreground service), the native voice behind the same `SpeechEnv` (rideOutput's `Voice`
  is unchanged), a wake lock that never says "keep your screen on yourself", no `HIDDEN_STOP_MS` pause
  (`ridesHidden()`), Android's silent "Latest cue" notification (`showCue`, each delivered sentence),
  and `speaksAloud()`: the rider's output choice as before, plus "My screen reader" spoken while the
  page is hidden (TalkBack reads nothing of a hidden page, so nothing is said twice). `RIDE_SAFETY`
  drops "needs the screen on" in the app. RideGroup's own watch stays the browser's.
- The page is marked `window.__routemakerNativeShell`, so the app's compatibility layer for sites older
  than v0.8.0 (`mobile/android/app/src/main/assets/routemaker-compat.js`) stands aside. That layer
  hands a watch to background location only when Ride mode's screen
  (`section.ride[aria-labelledby="ride-heading"]`) is on the page as it starts, never Group or Mass
  Ride sharing; keep that section's class and label, or update the layer and `mobile/test/compat.test.mjs`
  (which reads `RideMode.tsx` and `RideGroup.tsx`) with them.
- Tests: `frontend/src/lib/nativeShell.test.ts` (browser fallbacks, the watch, the notification's
  order and silence, the voice's turn-taking, the wake lock, no Capacitor import) and
  `rideWatch.test.ts` (nativeShell.ts is the one other `watchPosition`, held to the same no-leak rule);
  `cd mobile && npm test` for the config, the manifest's permissions and the compatibility layer.
