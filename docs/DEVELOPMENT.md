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
rather than an edit.

The suite supplies its own value through `config.test_settings`, which is
`config.settings` plus that one default and nothing else. It cannot come from
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
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/frontend:/app" -w /app node:22 npm test
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/frontend:/app" -w /app node:22 npm run build
```

- `npm test` is `node --test` over `src/**/*.test.{mjs,ts}`: the pure logic
  (error mapping, request pacing, the long-ride rule, stress bar maths, the
  plan in the link) and the stress palette's contrast against the base map's
  own colours, which reads `@protomaps/basemaps` from `node_modules` - so
  `npm ci` first. The TypeScript runs through Node's own type stripping, on by
  default from Node 22.18; `tests/test_frontend.py` runs the same files inside
  pytest, skips on a machine without Node (WSL here) and fails in CI if the
  Node there is older or missing.
- The junction markers (OWNER-DECISIONS 172) are `lib/intersectionMarkers.ts`
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

The panel's Accessibility switch (OWNER-DECISIONS 208, 209, 211, 212; PLAN.md,
Owner amendments) turns on the `cvd` palette in `frontend/src/stressStyle.js`
and draws the overlay stronger. The state lives in that module and is read
through `currentTiers()`, never kept from import time; `subscribePalette()`
announces a change, and `useStressStyle()` (React) and `MapView`'s effect (the
map) repaint on it. What is chosen is held in `localStorage` as
`routemaker.accessibility`.

Where it starts: the stored "on" or "off" first, then the browser's
`prefers-contrast: more` (followed live while nothing is stored), then off. The
palette: `?palette=` in the link, then the switch, then `blended`. The
colours of the switch's state are one place, `tiersFor(palette, strong)`.

The `cvd` palette, with casings (the casing is the dark or white line drawn
under a tier so it holds against the base map; the switch makes each black or
white):

| Tier | Line | Casing |
| --- | --- | --- |
| LTS 1 | #d2eafc | #0a1a2f |
| LTS 2 | #5d99d2 | #0a1a2f |
| LTS 3 | #cd4b0a | #0a1a2f |
| LTS 4 | #6a0a06 | #ffffff |
| Avoid | #08081e | #ffffff |

It was chosen by search, not by eye: random and grid search over sRGB with the
hue of each tier held to a family (light and mid blue, orange, dark red,
blue-black), scored by the smallest CIEDE2000 between neighbours under normal
vision and each simulation, with the luminance falling by at least 1.5:1 a step
and 3:1 against every base-map surface (with a casing) as constraints. (1.5:1
was the search's target; the test's floor is 1.4:1, which leaves a later retune
a margin. The smallest step chosen is 1.51:1.) Avoid is blue-black on purpose:
a protanope sees LTS 4's dark red as near-black, and a neutral black Avoid
beside it measures about 17 apart (#000000 is 16.9 under protanopia, and
#242424 14.1), under the floor of 20.
Blue against orange is the pair all three deficiencies keep.

CIEDE2000 between neighbouring tiers, LTS 1-2, 2-3, 3-4, 4-Avoid, and the
closest pair of any two tiers, for every palette and each vision (Machado,
Oliveira and Fernandes 2009, severity 1.0, applied in linear RGB). Only `cvd`
is held to the floor of 20 (and 35 for LTS 2-3); the others are reported by
`node --test src/stressContrast.test.ts`, which prints this table as test
diagnostics:

| Palette | Vision | LTS 1-2 | LTS 2-3 | LTS 3-4 | LTS 4-Avoid | Closest pair |
| --- | --- | --- | --- | --- | --- | --- |
| blended | normal | 16.1 | 40.2 | 26.7 | 20.9 | LTS 1-2, 16.1 |
| blended | protan | 15.4 | 14.9 | 21.0 | 19.3 | LTS 2-3, 14.9 |
| blended | deutan | 16.2 | 15.5 | 18.0 | 21.8 | LTS 2-3, 15.5 |
| blended | tritan | 16.0 | 51.7 | 18.1 | 19.3 | LTS 1-2, 16.0 |
| twotone | normal | 16.1 | 35.4 | 21.0 | 29.4 | LTS 1-2, 16.1 |
| twotone | protan | 15.4 | 20.5 | 12.4 | 28.3 | LTS 3-4, 12.4 |
| twotone | deutan | 16.2 | 26.0 | 8.3 | 17.8 | LTS 3-4, 8.3 |
| twotone | tritan | 16.0 | 46.9 | 13.4 | 18.3 | LTS 3-4, 13.4 |
| cvd | normal | 24.0 | 48.3 | 25.8 | 31.1 | LTS 1-2, 24.0 |
| cvd | protan | 23.0 | 51.4 | 23.2 | 27.2 | LTS 1-2, 23.0 |
| cvd | deutan | 25.5 | 51.7 | 26.9 | 34.1 | LTS 1-2, 25.5 |
| cvd | tritan | 24.0 | 59.8 | 23.1 | 32.3 | LTS 3-4, 23.1 |

The default `blended` palette is unchanged and does not meet 20 for every pair
under protanopia and deuteranopia (LTS 2 and 3 are 15 apart; the dashes tell
them apart, as the comment in `stressStyle.js` says). That is the reason for the
option, not something it changes.

WCAG relative luminance between neighbours (greyscale order): `cvd` Y 0.796,
0.298, 0.180, 0.033, 0.003, steps of 2.43, 1.51, 2.78 and 1.56 to 1; `blended`
1.86, 1.17, 1.98, 2.15 to 1; `twotone` does not fall (LTS 3 is lighter than
LTS 2).

Contrast of a tier against the base map (every surface of `@protomaps/basemaps`'
light flavour) and both panel themes, the worst case per tier, by the rule in
`stressContrast.test.ts` (the line itself, or its casing against the surface
and the line against its casing; 3:1 needed):

| Palette | LTS 1 | LTS 2 | LTS 3 | LTS 4 | Avoid |
| --- | --- | --- | --- | --- | --- |
| blended | 8.31 | 4.50 | 4.51 | 4.28 | 9.22 |
| blended, switch on | 9.83 | 5.29 | 4.51 | 4.28 | 9.22 |
| cvd | 10.23 | 5.53 | 3.66 | 7.41 | 11.55 |
| cvd, switch on | 12.29 | 5.53 | 3.66 | 7.41 | 11.55 |
| twotone (reported only) | 8.31 | 4.50 | 1.44 | 2.13 | 3.20 |

The route line in the `cvd` palette. The route's sections are drawn in a 5 px
line on a 9 px casing. The casing was the route's blue (#1d4ed8), which the
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
         "carrying": "people", "stress": 90, "hills": -40, "when": "weekend"}'
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
- `hills`, integer -100-100, detent at 0: below it `use_hills = 1 + hills/100`
  (0 is `use_hills` 1.0, no grade penalty, the fastest time); above it a climb
  search among the router's `alternates` (3), choosing the one that climbs most
  within `1 + 0.5 * hills/100` of the direct route's length. Two-point plans
  only, and not past 50 km of straight line (`routing.SEEK_MAX_SPAN_M`: a cold
  65 km search with alternates took 51 s on the live router); `hills_seek.limited`
  says when it was not done.
  Mass Ride refuses `hills > 0` (400).
- `when`: `weekend`, `weekday_rush` (Mon-Fri 07:00-10:00 and 16:00-19:00,
  America/New_York; federal holidays count as weekend) or `weekday_offpeak`;
  absent, the setting of the moment. It sets Valhalla's `date_time` (the next
  Saturday 09:00, Tuesday 08:00 or Tuesday 12:00), which is what the
  conditional restrictions Valhalla reads are evaluated against, and it decides
  whether a road closed to cars at set times counts as a path in `facility_m`
  and as tier 1 in `stress_m`. The closure is read from
  `motor_vehicle:conditional` / `motorcar:conditional` (`routemaker.ridetime`):
  day ranges, week spans that wrap (`Fr 19:00-Mo 06:00`), `PH`, and times with
  no days, which name every day (Clark Place NW's `no @ (06:00-10:15,14:45-19:15)`
  is car-free at weekday rush; supported since the round-1 mutation review).
  A condition it cannot read - a month range, `sunset` - closes nothing.
- `carrying`: `cargo` or `people` ("Cargo with passengers", item 241), Cargo Bike only
  (400 elsewhere); it sets the stress slider's start (90, Default's, or 100).
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
  the distance): an expressway posted 50 mph or more, or a way the owner
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
  `[{from_m, to_m, tier, facility}]` in whole metres along the traced length
  from 0, each starting where the one before ends. `tier` is 1-5 or null
  (unknown), `facility` the class or null. They come from the same per-piece
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
(`reports/LTS-literature-review.md`), kept here because each is a decision,
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
Valhalla 3.5.1's bicycle edge cost is `time * factor`, with `factor = 1 +
grade + accommodation * roadway_stress` (sif/bicyclecost.cc), so the stress
level is `factor(tier) - factor(no tier)` for the same edge, grade and speed.
LTS 3 is `bicycle=use_sidepath`, which adds `3 * (1 - use_roads)` to the
accommodation factor. LTS 4 and up add the graph's top practical speed (140,
`kMaxOSMSpeed`) and lane count (15 each way, `kMaxLaneCount`), which raise the
roadway stress through its speed penalty and lane term; the bicycle's time
comes from its own speed, so no duration changes, and the speed limit and
access stay OSM's. Not on the no-trail graph: Mass Ride is locked at 0.

The stress levels, LTS 3 / LTS 4 (and the ratio), modelled from the costing
code for representative roadways at each slider position:

| Roadway | 0 | 25 | 50 | 75 | 90 | 100 |
|---|---|---|---|---|---|---|
| secondary, 1 lane each way, 30 mph | 0 / 1.14 | 0.92 / 4.64 (5.0x) | 1.98 / 10.21 (5.2x) | 3.26 / 20.22 (6.2x) | 4.13 / 28.38 (6.9x) | 4.75 / 34.82 (7.3x) |
| primary, 2 lanes each way, 35 mph | 0 / 1.05 | 1.14 / 4.62 (4.1x) | 2.63 / 10.42 (4.0x) | 4.70 / 21.06 (4.5x) | 6.23 / 29.80 (4.8x) | 7.38 / 36.74 (5.0x) |
| primary, 2 lanes each way, 40 mph, painted lane | 0 / 0.82 | 1.26 / 3.97 (3.1x) | 3.00 / 9.10 (3.0x) | 5.51 / 18.42 (3.3x) | 7.39 / 26.08 (3.5x) | 8.82 / 32.14 (3.6x) |
| trunk, 3 lanes each way, 45 mph | 0 / 0.91 | 1.55 / 4.63 (3.0x) | 3.85 / 10.88 (2.8x) | 7.58 / 22.74 (3.0x) | 10.54 / 32.62 (3.1x) | 12.84 / 40.52 (3.2x) |
| primary, 2 lanes each way, 55 mph | 0 / 0.82 | 1.46 / 4.19 (2.9x) | 3.59 / 9.78 (2.7x) | 6.76 / 20.15 (3.0x) | 9.20 / 28.70 (3.1x) | 11.07 / 35.51 (3.2x) |

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
(`core/tile_cache.py`); `python manage.py predraw_stress_tiles` fills z10-14 for
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
| Parameters | `q` (2-200 characters after white space is collapsed), optional `lat` and `lon` together (a bias, inside `COVERAGE_BBOX`), `limit` 1-10 (default 6), `lang` (`en` only, the imported language) | `lat`, `lon` (inside `COVERAGE_BBOX`), `lang` (`en`) |
| What reaches Photon | the query with US street abbreviations spelled out (`Blvd`, `St`, `Ave`, `Rd`, `Dr`, `Pkwy`, `Hwy`, `Ct`, `Ln`, `Pl`, `Sq`, `Ter`, `N`/`S`/`E`/`W`, `NE`/`NW`/`SE`/`SW`; `geocode.expand_abbreviations` has the rules), the bias, a count a few above `limit`, `lang`, and `bbox` = `COVERAGE_BBOX`; nothing else the request carries | `lat`, `lon`, `lang`, `limit=1`, `radius=0.25` km |
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
number. Ferry edges never name a point. If the
router does not answer, the name is the `near` one; if Photon does not, the
label has no neighbourhood.

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

FOLLOWUP-INTERSECTIONS (2026-10-01, revised 2026-10-02 after the round-1 and
round-2 reviews; OWNER-DECISIONS 133-136, 138, 163-169, 171, 172, 185-188,
194-196; the crossing
costs and the slider's top end are from "Bicycle stress literature in depth",
`reports/LTS-literature-review-2.md`: "Crossing penalties by control type and
right of way", "Left turns, multi-lane merges capped by box turns, and slip
lanes" and "The stress slider's top end"; the Mass Ride flow figures are from
"Mass ride flow evidence", `reports/MASSRIDE-flow-evidence.md`). Three things,
built on one mechanism: the traffic slider has a top end, a junction costs what
it costs a rider, and a route shows its stressful junctions.

### What Valhalla already does at a junction (measured, read-only, live router)

Valhalla 3.5.1's bicycle costing prices a node through its stop impact and turn
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
does not return them and `/expansion` is not enabled. The router's cost for a
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
| A trail crossing with no signal flag at it or within 30 m up the roads it crosses: a mapped crossing way, or a path, trail, cycletrack or sidewalk meeting the road at a node of its own | `MARKED_CROSSING_FACTOR`, `MARKED_CROSSING_MAX_SEVERITY` | x0.5, and never drawn red, worded "no signal mapped" as at any junction | item 185; `crossing=traffic_signals` does not reach the router's flag. Round 1 said the Pennsylvania Ave and Virginia Ave cycletracks had no flag on the road's arms; that was wrong: the round-2 review found one within 30 m at 31 of 48 trail crossings, and those now read as signalized |
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

There is no cap on the detour. The search keeps the best-scoring candidate, and
never one that is busier than the router's own route ("Traffic wins", OWNER-DECISIONS
61, said of hill avoidance and carried here): a candidate with more than 2 per
cent and 50 m more LTS 3, 4 and Avoid exposure (`EXPOSURE_TOLERANCE`,
`EXPOSURE_SLACK_M`) is not taken however many crossings it avoids (measured on
the live router, before the guard: Rockville to Silver Spring at the old top of the
slider traded 1.6 mi more LTS 3-4 for fewer crossings). It stops after two rounds that do not improve it, when no route is left (every way
out excluded: asked again once with only the LTS 4 stretches), when a round
cannot be started with five seconds left, and never excludes within 500 m of the
route's ends or of a via point (a trailhead's only way out is often the one busy
road). `calm_search` in the answer says what it did; `limited` is `time`,
`no_route`, `untraceable` or, where it did not run, `span` (past 19 mi
[30 km] apart), `long_ride`, `points` (a start only), `seeking` (the hills
slider's climb search uses the alternatives) or `mass_ride`.

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
`max_alternates` 3 (the search does not use alternates; Valhalla's alternates
are near-optimal in its own cost, which is not where a calmer route is) and
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
`core.stress_tiles.render` does), at most 2.5 s and never past the leg's time; a
cancelled read is `limited: "time"`, a `SeekError` is `limited: "error"` (logged),
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

**No trails, no seek.** A ride on the no-trail graph (`ctx.roadway_only`: Group Ride
with trails off at 100) is not seeked (`limited: "roadway_only"`).

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
  or Avoid stretch, and never an untraced one. A stretch never spans a via
  point: each leg is described on its own and `Stop 1`, `Stop 2` (the points
  list's own words, item 224) are entries between them ("Stop 1 at 4.7 mi
  (7.6 km).").
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
to a tenth. `/home/steph/rmdata/demo/reports/ROUTE-DESCRIPTION-plan-notes.md` has the plans.

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

- A trail crossing a road at a mapped crossing with `crossing=traffic_signals`
  (a signal or a HAWK) away from any signalized road junction does not reach
  the router's signal flag: Valhalla's transform reads `highway=traffic_signals`
  alone. Such a crossing reads "no signal mapped", is counted at
  `MARKED_CROSSING_FACTOR` and is never red (item 185). A cycletrack crossing
  at a node of its own beside a signalized road junction is read as signalized
  from round 2 (the approach walk reaches the junction's stop lines). Deriving
  the crossing's own signal in `lua/routemaker_remap.lua` (`forward_signal`
  and `backward_signal` on the node) is the fix for the rest and needs a
  rebuild to verify, so it is a recorded follow-up.
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
osmium extract --overwrite -f pbf -s smart -S types=any \
    --bbox -78.0,38.2,-76.02,39.72 -o source.osm.pbf.part merged.osm.pbf
```

`-s smart -S types=any` is PLAN:13's, and the `-S` half is the one that is easy
to lose: without it the strategy keeps multipolygon relations complete and cuts
every other type, which is exactly the administrative boundaries.

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
        --volume-source vdot --volume-year 2024 \
    --volume "$DATA_ROOT/reference/inputs/ddot-aadt-2024.geojson" \
        --volume-source ddot --volume-year 2024
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
  property `AADT`); the District's is DDOT's AADT layer (`--volume-source
  ddot`) and arrives the same way. Directional counts are summed before they
  reach here, which is why the property name is an argument rather than
  guessed.

  **Phase 1 installs VDOT and DDOT, and deliberately not Maryland.** MDOT SHA's
  layer is conditionally licensed, and while the pipeline can say which agency
  touched a way it cannot yet withhold those ways from the published
  derivative — identifiable, not excludable — so installing it today would mean
  publishing something that source influenced. PLAN.md:31-34's waiver mechanism
  is what closes that; handoff.md section 7 carries the row.

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
about when it is not (`ReferenceData.road_blocks`): the District's and
Baltimore's own street records, which know what OSM only guesses at. The owner
approved both (OWNER-DECISIONS 151, 159); the records of what was downloaded,
under what licence, and what was found in each are in
`fixtures/datasets/README.md`.

```sh
export DATA_ROOT=/srv/routemaker/data   # by hand, as above
python scripts/fetch_agency_layer.py --slug dc-roadway-block \
    --item 6fcba8618ae744949630da3ea12d90eb --layer <MapServer/163 url> \
    --out-dir "$DATA_ROOT/reference/inputs" --credit "..."   # once; refuses to run twice
python scripts/install_reference_data.py --data-root "$DATA_ROOT" \
    --roadway-block  "$DATA_ROOT/reference/inputs/dc-roadway-block/dc-roadway-block.geojson" \
    --baltimore-centerline "$DATA_ROOT/reference/inputs/baltimore-street-centerline/baltimore-street-centerline.geojson"
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
| `maxspeed`, `lanes`, `oneway`, `bike`, `parking` | `dc-roadway-block` or `baltimore-centerline` where the agency's value took precedence, `osm` where the way's own tag stood, `default` where neither said and the classifier assumed |
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
`scripts/analysis/compare_agency_lts.py moco|alexandria-lanes|baltimore`
(an agency's LTS against ours, Alexandria's CC0 lanes and Baltimore's facility
records against OSM; with `--roadway`, classified as the rebuild does, the
street layers conflated). They load nothing. The reports are in
`reports/data-comparison/`, and the two override files the owner approved from
them (OWNER-DECISIONS 181, 182) in `fixtures/overrides/` (`moco` and
`baltimore` write them; fixtures/overrides/README.md). `arlington` and
`alexandria` (Transport Streets) are internal only: they write to
`--internal-out`, which the script refuses inside the repository, and
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
valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`); starting them against the
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

## Contraflow on the no-trail graph

The owner, 2026-10-02 (OWNER-DECISIONS 192 and 193): "contraflow lanes are not
for group rides or mass rides, many routing engines put people on this when it's
not appropriate." and, for a Group Ride with trails on, "with trails on that's
fine". So the closure is built into one graph. A ride chooses its graph through
`core.presets.variant_for_ride`, which `routing.py` calls and which gives
`Variant.NO_TRAIL` to Mass Ride (its preset's own variant). Any ride with trails
off would take the same graph (`pipeline.variants.variant_for` maps the trails-off
toggle to it; Group Ride's toggle is not offered yet). Group Ride with trails on
is on the standard graph, which keeps contraflow.

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

The tag transform runs under LuaJIT, because Valhalla 3.5.1's build requires it
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
file. Refresh it with `scripts/vendor_valhalla_lua.sh`; do not edit it.

Setting `CI=1` turns the suite's missing-interpreter skips into failures.

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
  panel (`.panel-body`) is the one scroll container, and it holds the toggle, the
  checkbox and the buttons, so it is scrolled by keyboard in every browser. A
  focusable `tabIndex={0}` box would have added a Tab stop with nothing to do and,
  with a group's crossings nested in it, a box inside a box on a phone. The browser
  check asserts that every visible scroll box in the panel is focusable or holds
  something focusable.
- The toggle is named "Route description: 11 steps, overview"; "Full detail" has no
  leading space and a 24 px target; Copy clears its reply and sets it again 150 ms
  later, so a second press is said again.
- At 320 px with WCAG text spacing a row's severity and distance wrap inside it
  (`grid-template-columns: 18px minmax(0, auto) minmax(0, 1fr)`, `white-space:
  normal`).
- The browser check (scripts/a11y/check.mjs, 80 checks) adds sections 7 and 8: the
  rows at 320 px with text spacing, and the description (the toggle's name, the scroll
  boxes, Full detail, the copy reply, a group's nested crossings).

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
sections' source, width `ROUTE_HALO_WIDTH` 7 between the casing's 9 and the line's 5,
colour in the feature's `halo` property, opacity set with the sections in
`setRouteSections`): the tier's own casing, which is dark under LTS 1 to 3 and white
under LTS 4 and Avoid (with the switch on, black and white under the calm tiers, and
a busy tier's own casing, which the switch leaves: OWNER-DECISIONS 292), the first tier's dark
casing under the unrated grey, and white under the violet. The blue stays outside as
the route's identity and is itself 3:1 from every base-map surface. The panel's route
legend draws the same halo.

| Class | default palette (halo, ratio) | colour-blind-friendly, switch on (halo, ratio) |
|---|---|---|
| Traffic-free #4c1d95 | #ffffff, 10.95 | #ffffff, 10.95 |
| LTS 1 | #17301f, 8.36 | #000000, 16.92 |
| LTS 2 | #17301f, 4.50 | #000000, 6.95 |
| LTS 3 | #45290a, 3.60 | #0a1a2f, 3.83 |
| LTS 4 | #ffffff, 7.31 | #ffffff, 12.66 |
| Avoid | #ffffff, 15.75 | #ffffff, 19.74 |
| Not rated | #17301f, 5.38 | #000000, 7.65 |

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
