# Playbook: from an empty host to a recorded acceptance run

This is the order of operations, with the commands, for standing RouteMaker up on a real host and
running the phase-1 acceptance checklist (`docs/ACCEPTANCE.md`, `scripts/acceptance.py`) against
it. It does not replace the three guides — `docs/DEPLOYMENT.md` says why each piece is the way it
is, `docs/OPERATIONS.md` is the runbook for the second week, `docs/DEVELOPMENT.md` explains the
variables — it puts their first-day steps in one line each, in the sequence they have to happen.
Every command is copied from those guides; where this document and a guide disagree, the guide
is wrong and this document is the newer one, so fix the guide.

Budget for a first pass: an afternoon to the first rebuild, then the rebuild itself (hours; the
elevation download and three Valhalla tile builds), then an hour for the rest. The checklist can be
resumed across that (`--resume`).

## 0. What you need before you start

| Thing | Detail | Where it goes |
|---|---|---|
| A host | 8 vCPU, 32 GB RAM (PLAN.md:293); a small root volume and a **separate ≥200 GB data volume** mounted at the path you will put in `DATA_ROOT`. Ubuntu 24.04 LTS is what the pipeline image is built from and the only distribution these steps have been written against. | §1 |
| Network egress from the host | `ghcr.io` **and** `pkg-containers.githubusercontent.com` (the Valhalla image and its layers), `docker.io` (Caddy, PostGIS), `deb.debian.org` and `pypi.org` (the two image builds), `download.geofabrik.de` (the OSM extracts), `prd-tnm.s3.amazonaws.com` (3DEP elevation), `discord.com` (sign-in), and Let's Encrypt's ACME endpoints (Caddy's certificate). Inbound: 80 and 443 only; SSH by whatever your host uses. | §1 |
| A DNS name | Pointing at the host **before** the first `up`, so Caddy can get a certificate. Without one, use the `:80` posture (§3) and know that Discord sign-in over plain HTTP works only on `localhost`. | §3 |
| A Discord application | Created in the Discord Developer Portal by whoever will own it: its client id and secret, and its OAuth2 redirect set to `https://<your name>/auth/callback`. Phase 1 needs the `identify` scope only and **no bot**; the two bot variables in `.env` get generated placeholders. | §2 |
| Your own Discord user id | The account that becomes the first instance admin. In Discord: Settings → Advanced → Developer Mode, then right-click your name → Copy User ID. | §3 |
| The three reference inputs | `tl_2024_us_uac20.geojson` (Census TIGER/Line urban areas, converted with `ogr2ogr -f GeoJSON -t_srs EPSG:4326`), `vdot-aadt-2024.geojson` (VDOT's traffic-volume export from the Virginia Roads portal) and `ddot-aadt-2024.geojson` (DDOT's AADT layer from the District's open-data portal). `docs/DEVELOPMENT.md` "Reference data" says how the counts are normalised. **Maryland is not installed in phase 1.** | §6 |

## 0b. Running it on a local computer first

The stack is a compose stack and runs wherever Docker runs, so the cheapest place to execute this
checklist for the first time is a machine you already have. A web server is needed for the real
deployment and for the one thing a local run cannot reproduce: a public name with a certificate.
Run it locally first — the first build and the first rebuild will fail on things no review could
see, and a desktop is where that costs least — then again on the server, where A1 to A3 take
minutes and A4 is the only long item.

What changes locally:

- **Posture.** Uncomment the five-line local block at the end of `.env.example` (`:80`,
  `DJANGO_DEBUG=1`, `localhost` hosts, an `http://localhost/auth/callback` redirect) and register
  that redirect on the Discord application; Discord permits `localhost`. The checklist reads the
  `:80` posture, talks to `http://127.0.0.1`, and skips the HSTS check, which exists only under
  https.
- **Machine.** Linux is what these steps were written against. Docker Desktop on macOS or Windows
  (WSL2) runs the stack, but its file sharing makes the data-root ownership step a no-op, so A1
  proves less there. Memory is the real constraint: the rebuild's container is capped at 8 GB and
  its true peak for a DC-region build is unmeasured (`handoff.md` §7), which is why the plan sizes
  the host at 32 GB; 16 GB will probably do, less is a gamble. Disk: 50 GB free for the extract,
  the elevation tiles and two tile sets, and the rebuild refuses to start under 20 GiB.
- **Time.** The same as on a server; the elevation download and the three tile builds take hours
  wherever they run.
- **What it cannot tell you.** Whether the certificate is issued, the name resolves, the firewall
  is right, or the sizing holds under real traffic. Everything else in A1 to A6 is the same path.

Skip §1's provisioning and §2's `https` redirect; do everything else as written, with `DATA_ROOT`
pointing at a directory on a disk with room.

## 1. The host

```sh
# Docker Engine and the compose plugin, from Docker's repository (docs.docker.com/engine/install/ubuntu)
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"      # then log out and in
docker compose version               # v2 or later; the checklist reads `docker compose`, not `docker-compose`
```

Mount the data volume at the path you will use as `DATA_ROOT` and make it come back after a reboot:

```sh
sudo mkfs.ext4 /dev/nvme1n1          # the data volume's device on your host, ONCE, on an empty disk
sudo mkdir -p /srv/routemaker/data
echo "$(sudo blkid -s UUID -o value /dev/nvme1n1) /srv/routemaker/data ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo mount -a && df -h /srv/routemaker/data
```

Unattended security updates and a firewall that allows 22, 80 and 443 are the host's own business;
`docs/DEPLOYMENT.md` "Host requirements" has the reasoning behind the sizes.

## 2. The Discord application

In the Developer Portal: **New Application** → name it → **OAuth2**: copy the **Client ID** and
reset and copy the **Client Secret**; under **Redirects** add exactly
`https://<your name>/auth/callback` (or `http://localhost/auth/callback` for the `:80` posture).
Nothing under **Bot** is needed for phase 1. The redirect has to match `DISCORD_REDIRECT_URI` in
`.env` character for character, and `docs/DEPLOYMENT.md` "What the deployment serves" says which
mismatches produce which error.

## 3. The checkout and `.env`

```sh
sudo mkdir -p /srv/routemaker && sudo chown "$USER" /srv/routemaker
git clone https://github.com/Macrophage87/RouteMaker.git /srv/routemaker/app
cd /srv/routemaker/app
cp .env.example .env
```

Fill `.env` in an editor. Every variable has its reasoning above it in the file; the ones you must
change:

| Variable | Set it to |
|---|---|
| `DATA_ROOT` | the mount from §1, absolute: `/srv/routemaker/data` |
| `CADDY_SITE_ADDRESS` | your DNS name, e.g. `routes.example.org`; **or** `:80` for a local stack |
| `DJANGO_ALLOWED_HOSTS` | the same name; no spaces after commas |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` + the same name |
| `DISCORD_REDIRECT_URI` | `https://` + the same name + `/auth/callback` — the value registered in §2 |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` | from §2 |
| `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` | your Discord user id from §0 |
| `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY`, `PGPASSWORD`, `DISCORD_BOT_TOKEN`, `BOT_INTERNAL_SECRET` | each a fresh value from the generator below |
| `TAG` | leave `dev` for the first run |

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # once per secret
```

The generator's output has no `$`, so it needs no quoting. If you paste a secret from elsewhere and
it contains `$`, wrap it in **single quotes** — `.env.example` has the measured table of what
compose does with each form. Two rules that are not obvious: `.env` is compose's input and is
**never** sourced into a shell (`set -a; . ./.env` puts the pid where `$$` was and runs a backtick),
and `KEY_ENCRYPTION_KEY` cannot be rotated once a ban has been recorded, so back it up with the
database.

For the local `:80` posture instead, uncomment the five-line block at the end of `.env.example` and
use `http://localhost/...` values; sign-in works there only on `localhost`.

## 4. The data root

Before the first `up`, because Docker creates any missing bind source as a root-owned directory:

```sh
sudo sh scripts/prepare_data_root.sh --env-file ./.env
```

It reads the one `DATA_ROOT=` line from the file without sourcing it, creates the thirteen
directories, and hands seven of them to uid 10001 (the images' user), leaving `postgres/`, `caddy/`
and `photon/` alone. It is idempotent; run it again after moving the volume.

## 5. The stack, and the first two checklist items

```sh
python3 scripts/acceptance.py --dry-run          # prints every command the checklist will run
python3 scripts/acceptance.py --only A1 A2       # preflight; build; up; wait for healthy
```

A2 builds the two images (minutes) and starts nine services. It waits for `postgis` healthy,
`migrate` exited 0, `api` healthy, `worker` and `rebuild` running. **The three routers will be
restarting** until the first rebuild gives them tiles; A2 reports their state without judging it.

Then the one deploy step the guides put after every build:

```sh
docker compose run --rm api ./manage.py collectstatic --noinput
```

## 6. Sign-in and the admin rules — A3

```sh
python3 scripts/acceptance.py --only A3
```

The automated half checks the edge (`/healthz` 200 with HSTS, `/auth/login` → Discord with your
redirect URI, the admin path 404 to a stranger). Then it prints four browser steps and waits:

1. Sign in at `https://<name>/auth/login` as the bootstrap account and open the admin at
   `https://<name>/internal-8f3a/` (or your `DJANGO_ADMIN_PATH`); the first admin action claims
   instance admin and disables the environment path — afterwards, blank
   `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` in `.env` and `docker compose up -d api`.
2. As that instance admin, add two configured guilds and a role mapping that makes a second Discord
   account a guild admin of the first.
3. In a private window, sign in as that second account: edit your own guild's name and save.
4. Still as the guild admin, submit a change to the other guild by editing the URL to its id, or by
   ticking it in a bulk action. It must be refused.

Press Enter; the script reads the audit log and confirms all four footprints.

## 7. The first rebuild — A4

```sh
python3 scripts/acceptance.py --only A4
```

On a fresh host this is the runbook's two-phase first rebuild, and the script follows it:

- **First run** (minutes): downloads the three Geofabrik extracts (1–2 GB), merges and clips them,
  and stops at `LOAD_REFERENCE_DATA` with "reference data missing". That is expected; the script
  says so and pauses.
- **You**: put the three GeoJSON inputs from §0 under `${DATA_ROOT}/reference/inputs/` (owned by
  10001) and run the installer the script prints, which is `docs/OPERATIONS.md` step 6:

  ```sh
  sudo install -d -o 10001 -g 10001 /srv/routemaker/data/reference/inputs
  # copy the three files in, then:
  docker compose exec -T rebuild python3 scripts/install_reference_data.py \
      --data-root /data --extract /data/extracts/source.osm.pbf \
      --urban-areas /data/reference/inputs/tl_2024_us_uac20.geojson \
      --volume /data/reference/inputs/vdot-aadt-2024.geojson \
          --volume-source vdot --volume-year 2024 \
      --volume /data/reference/inputs/ddot-aadt-2024.geojson \
          --volume-source ddot --volume-year 2024
  ```

- **Second run** (hours): elevation tiles from 3DEP, the three variant tile builds, validation,
  the swap. The script polls the run row every minute up to eight hours; `docker compose logs -f
  rebuild` in another terminal shows the stages. When it succeeds the script checks the promotion
  links, restarts the three routers, sends a canary route to each, and runs `check_operations`.

If the run fails, `docker compose exec -T worker ./manage.py check_operations` and the operations
page name the stage and the last twenty lines of the failing command; `docs/OPERATIONS.md`
"Firing a rebuild by hand" and "Wedged jobs" are the two sections you will need.

## 8. Backup, restore and rollback — A5 and A6

```sh
python3 scripts/acceptance.py --only A5                                   # a dump, verified, restored beside the live database
python3 scripts/acceptance.py --only A6 --second-rebuild                  # another full rebuild, then a rollback rehearsal
python3 scripts/acceptance.py --only A6 --second-rebuild --confirm-rollback   # …and the live rollback
```

A5 touches nothing live. A6 with `--confirm-rollback` leaves the deployment on the older build; run
A4 again to roll forward, or wait for Tuesday.

## 9. Recording the run

```sh
mkdir -p docs/review/acceptance
cp acceptance-reports/<instant>.md docs/review/acceptance/
git add docs/review/acceptance && git commit -m "Acceptance run on <commit>: <PASS|FAIL>, skipped <items>"
```

Then one line in `handoff.md`'s header: the date, the commit, the outcome, the skipped items. A FAIL
is the next wave's only list. Under the retrospective's rule, phase 1 is accepted when a run passes
A1 to A5 with A6 at least rehearsed and the last diff-scoped review finds no regression.

## 10. Day two

- The cron entry from `docs/OPERATIONS.md` "Where the alerts are", in `worker`, with its `cd`.
- A nightly snapshot of the data volume; `docs/OPERATIONS.md` "Restoring one" is written from a
  measured drill and is the procedure if the host is lost.
- The Tuesday 08:00 UTC rebuild runs on its own; a stack down more than ten minutes across it drops
  that week's run, and `run_rebuild_now` is the catch-up.
- Blank the bootstrap id once the first instance admin exists, if you have not already.
