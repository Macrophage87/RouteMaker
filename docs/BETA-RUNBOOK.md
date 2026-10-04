# Beta runbook: RouteMaker on the owner's server

For the owner's Claude on the server. It stands up a private beta of RouteMaker at
`https://routemaker.cieply.com` for trusted friends and family (OWNER-DECISIONS 360-362). Read
the whole file before running anything. Every step says what it changes and how to undo it.

## What this changes on the host, and nothing else

| Where | What | Undo |
| --- | --- | --- |
| Docker | One compose project, `routemaker-beta`: containers postgis, api, worker, photon and four routers; one network | `scripts/beta/beta-compose.sh down` |
| `/data/routemaker-src` | The checkout of the exact release sha | `rm -rf` it |
| `/data/routemaker` | `DATA_ROOT`: tiles, database files, Photon index, base map, front end, backups | `rm -rf` it, only after the owner agrees |
| `/data/routemaker-incoming` | The bundle as shipped from home (about 4 GB) | `rm -rf` it |
| nginx | **One new file** (`routemaker-beta.conf`) and one htpasswd file beside `nginx.conf`. No existing file is edited. | delete both, `nginx -t`, reload |
| `/var/www/routemaker-acme` | Only if option A (certbot `--webroot`) is chosen | `rm -rf` it |
| `~/routemaker-beta-state` | Mode 700: the before/after copies of `nginx -T` and the other sites' status codes | `rm -rf` it |
| `~/routemaker-beta-passwords.txt` | Mode 600: the testers' passwords, for the owner to read and hand out | the owner deletes it (`shred -u`) |

Every RouteMaker path above is created only after a check that it **does not exist yet**; if one
does, stop and ask the owner. Nothing here changes the owner, group or mode of a directory that
already exists (`/data` included: it holds other people's data).

It does not touch the other sites, `nginx.conf`, the firewall, the system packages' configuration,
or Docker's daemon settings. If a step seems to need any of those, **stop and ask the owner**.

The memory budget is hard: every container has a cap (`compose.beta.yaml`, 6.94 GiB resident in
all, 7.19 GiB at the startup peak, against the host's 8.6 GiB available), so a spike restarts a
RouteMaker container rather than starving another site. Every RouteMaker container also has
`cpu_shares: 512` and `oom_score_adj: 500`: under CPU contention the other sites win, and a
host-wide out-of-memory kill picks a RouteMaker process first.

### Rules while running this

1. Never run `docker compose` directly. Use `scripts/beta/beta-compose.sh`, which always adds the
   overlay and `.env`, refuses `up` or `create` without service names, refuses caddy, rebuild,
   renderer and bot under every subcommand (even as a word in an `exec` command), and refuses
   `-p`, `-f`, `--scale` and any profile but `offroad`. Name services as the steps below do.
2. One-shot management commands run inside the api (`beta-compose.sh exec -T api ./manage.py check`, for example)
   or in the small migrate container (`beta-compose.sh run --rm --no-deps migrate ./manage.py migrate --check`),
   never as `run --rm api ...`: that starts a second container with the api's 1450M cap beside
   the running one, which the memory budget does not have room for.
3. Never `docker compose down -v`, `docker system prune`, or `rm -rf` anything outside the directories
   in the table above.
4. `nginx -t` must pass before every `nginx -s reload`. If it fails, remove the new file and do not reload.
5. Do not put a password, key or token in a command line you display, a file in the checkout, or a
   message, and do not `cat` the files that hold them. `make-env.sh` and `make-htpasswd.sh`
   generate them and print only where they are.
6. If any check says to stop, stop, and report the exact output to the owner.

## 0. Variables

Set these in the shell you work in (nothing else is read from your environment):

```sh
export RM_SHA=<the 40-character git sha from the bundle's MANIFEST.txt, git_sha=>
export RM_REPO_URL=<the repository URL the owner gave you>
export RM_DATA=/data/routemaker
export RM_SRC=/data/routemaker-src
export RM_INCOMING=/data/routemaker-incoming
export RM_SSH_HOST=<the ssh host the owner ships from, as the owner names this server in ~/.ssh/config>
export BETA_API_PORT=8087      # the api's loopback port; step 1 may choose another, then use it everywhere
# The guard every creating step uses: true only if NONE of the paths exists yet, naming each that
# does; an empty argument (an unset variable) also fails it. Every command that creates a RouteMaker path is written `rm_absent <paths> && <command>`
# on one line, so an existing path stops that command (a `for` loop's status alone would not).
rm_absent() { ok=1; [ "$#" -gt 0 ] || ok=0; for p in "$@"; do if [ -z "$p" ]; then echo "EMPTY path (an unset variable?): stop and ask the owner" >&2; ok=0; elif [ -e "$p" ] || [ -L "$p" ]; then echo "EXISTS: $p: stop and ask the owner" >&2; ok=0; fi; done; [ "$ok" = 1 ]; }
```

## 1. Prerequisites and checks (changes nothing)

What to expect on this server (the owner's check, 2026-10-04); a check below that disagrees is a stop:

- the owner reaches it as `ssh "$RM_SSH_HOST"` (section 0), and ships the bundle there;
- `/data` is a separate filesystem mounted `nofail`, with far more than the 25 GB this needs;
- Docker's root may be on the root disk rather than on `/data` (that is why binds never create
  their source: "Reboot and a late `/data`"), so its free space is checked on its own;
- available memory is at least the 8400 MiB threshold below (the 7358 MiB startup peak plus the
  checker's 1 GiB margin);
- an x86_64 machine (the api image is built at home, on x86_64);
- `routemaker.cieply.com` resolves to this server's own public address (checked live below; the
  address is not written down here).

```sh
free -m                                  # "available" must be at least 8400 MiB: the 7358 MiB startup peak plus the checker's 1 GiB margin (the caps total 7102 MiB resident)
uname -m; docker info -f '{{.Architecture}}'   # both x86_64: the api image is built at home on x86_64; anything else is a stop
df -h /data /                            # /data: at least 25 GB free (bundle 4 GB, installed copy 4 GB, backups)
findmnt -no SOURCE,FSTYPE,OPTIONS /data  # a filesystem of its own; nofail in the options is expected (see "Reboot and a late /data")
stat -c '%A %U:%G' /data                 # read-only: needs x for others (or for nginx's group): nginx must pass through /data. If not, STOP and ask the owner; never change /data's mode
docker info -f '{{.DockerRootDir}}'      # where images and logs go; often /var/lib/docker on the root disk
df -h "$(docker info -f '{{.DockerRootDir}}')"   # at least 6 GB free for the images (about 3.7 GB) and the containers' logs (capped at 50 MB each)
systemctl is-enabled docker containerd   # both "enabled", or nothing comes back after a reboot (read-only; change nothing)
id -nG | tr ' ' '\n' | grep -x docker    # you must be in the docker group (or use sudo for every docker command)
docker version --format '{{.Server.Version}}'; docker compose version   # Docker 29, compose 2.40 or newer
v=$(docker compose version --short); [ "$(printf '%s\n' 2.40.0 "${v#v}" | sort -V | head -n 1)" = 2.40.0 ] && echo "compose $v: at least 2.40.0" || echo "STOP: compose $v is older than 2.40.0"   # the minimum this runbook supports; step 8 proves the binds on this host
ss -ltn | awk '{print $4}' | grep -E ":($BETA_API_PORT)\$" || echo "port $BETA_API_PORT is free"
nginx -v; sudo nginx -T 2>/dev/null | grep -E '^\s*(include|user) ' | head   # which directory does nginx include? which user?
command -v git rsync openssl curl python3 sha256sum
sudo docker compose version                      # the compose plugin must also work under sudo (receive-data.sh files/db run with sudo)
python3 -c 'import yaml' && echo "pyyaml ok"      # the pre-flight checker needs it; if missing, see below (no system package is installed)
dns=$(getent ahostsv4 routemaker.cieply.com | awk 'NR == 1 {print $1}'); me=$(curl -s -m 10 https://api.ipify.org)
[ -n "$dns" ] && [ -n "$me" ] && [ "$dns" = "$me" ] && echo "DNS points here" || echo "STOP: routemaker.cieply.com does not resolve to this server's public address (or the check could not run)"
sudo nginx -T 2>/dev/null | grep -c 'listen \[::\]'   # 0: the other sites do not listen on IPv6; render with --no-ipv6 in 9c
rm_absent "$RM_SRC" "$RM_INCOMING" "$RM_DATA" "$HOME/routemaker-beta-state" "$HOME/routemaker-beta-passwords.txt" "$HOME/routemaker-beta-venv" /var/www/routemaker-acme /etc/nginx/routemaker-beta.htpasswd && echo "all absent"   # any EXISTS line is a stop
```

If `import yaml` failed, give the checker a private virtualenv rather than a system package (the
runbook does not change the host's packages; if `python3 -m venv` itself is missing, ask the owner):

```sh
rm_absent "$HOME/routemaker-beta-venv" && python3 -m venv "$HOME/routemaker-beta-venv" && "$HOME/routemaker-beta-venv/bin/pip" install --quiet pyyaml
export RM_PY="$HOME/routemaker-beta-venv/bin/python"      # step 4 runs the checker with "${RM_PY:-python3}"
```

**TLS discovery (read-only, OWNER-DECISIONS 367.1).** Find out which certificates exist and which
server blocks use them, without changing anything:

```sh
command -v certbot && sudo certbot certificates     # names, domains, expiry, paths; certbot renews these itself
sudo nginx -T 2>/dev/null | awk '/server_name/{n=$0} /ssl_certificate /{print n" -> "$2}' | sort -u   # which site uses which certificate
for c in $(sudo nginx -T 2>/dev/null | awk '/ssl_certificate /{print $2}' | tr -d ';' | sort -u); do
  echo "== $c"; sudo openssl x509 -in "$c" -noout -subject -enddate -ext subjectAltName
done
```

Then apply this rule, and report which option it gave and why:

- **Option B (reuse)** if some certificate's subjectAltName contains `routemaker.cieply.com` or
  `*.cieply.com`, **and** its `notAfter` is more than 14 days away, **and** it renews automatically
  (it is listed by `certbot certificates`, or the owner confirms how it is renewed).
- **Option A (a new certificate for this one name)** otherwise: `certbot certonly --webroot` for
  `routemaker.cieply.com` only (step 9b).

Record the choice for step 9c, which branches on it: `export TLS_OPTION=A` or `export TLS_OPTION=B`.

Neither option changes another site's TLS. Do not use certbot's `--nginx` authenticator or
installer: it edits and reloads the host's nginx configuration at issue time and again at every
renewal.

Decide and note down:

- **The api port.** `8087` unless `ss` shows it taken; then pick a free one, `export BETA_API_PORT=<it>`,
  and the commands below use it (`--api-port` in steps 3 and 9c, the local curls). Only `127.0.0.1` is
  ever bound.
- **nginx's worker user.** The `user` line `nginx -T` printed (`www-data` on Ubuntu):
  `export NGINX_USER=<that user>`. Step 8 checks with it that nginx can read what it serves.
- **Where nginx reads site files from.** On Ubuntu this is normally `/etc/nginx/sites-enabled/*`
  (files live in `sites-available/`, linked) or `/etc/nginx/conf.d/*.conf`. Use whichever the
  `include` lines above show and whichever the other sites already use. `$NGINX_SITE` below is the
  full path of the one file you will add, and `$NGINX_LINK` the `sites-enabled` link to it if that
  is the host's pattern (otherwise set `NGINX_LINK="$NGINX_SITE"`, and no link is made), for example
  `export NGINX_SITE=/etc/nginx/sites-available/routemaker-beta.conf NGINX_LINK=/etc/nginx/sites-enabled/routemaker-beta.conf`.
  Then `rm_absent "$NGINX_SITE" "$NGINX_LINK" && echo "site file absent"`; an EXISTS line is a stop.
- **Whether `routemaker.cieply.com` already points here.** If `getent` shows another address, stop;
  the owner has to change DNS first.

Never run anything under `scripts/boot/`, and do not follow `docs/DEPLOYMENT.md`'s boot section,
on this server: they are for the home machine (Docker Desktop on WSL). `start-stack.sh` runs the base
compose file without the overlay and exports `RESTART_POLICY=no`, which here would start caddy and
the rebuild uncapped and stop the stack coming back after a reboot. Docker restarts the beta itself.

Record the "before" state so you can prove nothing else changed. `nginx -T` prints every site's
configuration, so the copies go in a private directory (mode 700, files 600), not in `/tmp`:

```sh
export RM_STATE="$HOME/routemaker-beta-state"
rm_absent "$RM_STATE" && mkdir -m 700 "$RM_STATE"
( umask 077                                     # inside this subshell only: these files are 600
  sudo nginx -T > "$RM_STATE/nginx-before.txt" 2>&1
  docker ps --format '{{.Names}} {{.Status}}' > "$RM_STATE/docker-before.txt"
  # a status line for each of the host's other sites (the server_name values in nginx-before.txt):
  grep -hE '^\s*server_name ' "$RM_STATE/nginx-before.txt" | tr -d ';' | awk '{for(i=2;i<=NF;i++)print $i}' | sort -u > "$RM_STATE/sites-before.txt"
  while read -r s; do printf '%s %s\n' "$s" "$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$s/" || echo fail)"; done < "$RM_STATE/sites-before.txt" > "$RM_STATE/sites-before-status.txt"
)
cat "$RM_STATE/sites-before-status.txt"
```

The `umask 077` stays inside the parentheses on purpose: left on for the shell, it would make the
checkout in step 2 and `$RM_DATA` in step 5 unreadable to the containers and to nginx.

## 2. Get the code at the exact sha (adds `$RM_SRC`)

```sh
rm_absent "$RM_SRC" "$RM_INCOMING" && sudo install -d -o "$(id -un)" -g "$(id -gn)" "$RM_SRC" "$RM_INCOMING"   # only ever creates
git clone "$RM_REPO_URL" "$RM_SRC" && cd "$RM_SRC" && git checkout --detach "$RM_SHA"
git rev-parse HEAD            # must print exactly $RM_SHA
git status --short            # must print nothing
stat -c '%U' "$RM_INCOMING"   # the user you are logged in as: the one `ssh "$RM_SSH_HOST"` logs in as
```

**The order of setup and shipping.** The owner ships the bundle only after this step, because steps 1
and 2 stop if `$RM_INCOMING` already exists. Tell the owner now that `$RM_INCOMING` is ready and which
user owns it: `ship-data.sh` writes into it over `ssh "$RM_SSH_HOST"` (`mkdir -p` and `rsync`, as that ssh
user, with no sudo), so the owner's ssh login and the owner of `$RM_INCOMING` must be the same user.
If they differ, stop and ask the owner; do not change the directory's owner or mode to make it fit.

If the repository is not reachable from the server, the owner can send a tarball from home
(`git archive --format=tar.gz -o routemaker-<sha>.tar.gz <sha>`, then `rsync` it); unpack it into
`$RM_SRC` and use `git`-free checks: the bundle's `MANIFEST.txt` records the sha, and
`receive-data.sh` will need `--allow-sha-mismatch` because there is no `.git` to read it from.

Undo: `rm -rf "$RM_SRC"`.

## 3. Make `.env` (adds `$RM_SRC/.env`, mode 600)

```sh
cd "$RM_SRC"
scripts/beta/make-env.sh --data-root "$RM_DATA" --api-port "$BETA_API_PORT"       # TAG defaults to the first 12 characters of the sha
```

It generates `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY` and `PGPASSWORD` as random hex and prints
no secret. It refuses to overwrite an existing `.env`: a new `PGPASSWORD` would no longer match the
database initialised with the old one. The required values and what is optional:

| Variable | Required | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY`, `PGPASSWORD` | yes | generated by `make-env.sh` |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | yes | already `routemaker.cieply.com` / `https://routemaker.cieply.com` |
| `DATA_ROOT`, `TAG`, `COMPOSE_PROJECT_NAME` | yes | `/data/routemaker`, the short sha, `routemaker-beta` |
| `BETA_API_PORT`, `BETA_WEB_CONCURRENCY` | yes | `8087`, `6` (two route plans at once, one worker always free; the checker refuses more) |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI` | **no** | Planning works signed out. Leave empty and there is no sign-in. To enable it the owner adds `https://routemaker.cieply.com/auth/callback` to the Discord application and gives you the id and secret; edit `.env`, rerun the gate (`"${RM_PY:-python3}" scripts/check_beta_compose.py --env-file .env`, which must print "beta compose: ok"), then `beta-compose.sh up -d api`. |
| `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` | no | The beta's database carries **no accounts** (the dump strips them, OWNER-DECISIONS 367.3), so the owner claims instance admin afresh. Set this to the owner's Discord user id only if Discord sign-in is turned on, and have the owner sign in once promptly after the api starts. Otherwise leave it empty. |
| VDOT token | no | this release has no such variable; there is nothing to set |

Never `source .env`; compose reads it. Never print it. Do not add `$` to a value (compose expands it).

Undo: `rm .env` (only before the database exists; after, keep it).

## 4. Pre-flight check of the overlay (changes nothing)

```sh
cd "$RM_SRC"
"${RM_PY:-python3}" scripts/check_beta_compose.py --render            # the overlay itself, with dummy values
"${RM_PY:-python3}" scripts/check_beta_compose.py --env-file .env      # THE GATE: the overlay with this server's .env
scripts/beta/beta-compose.sh config --services            # exactly: api migrate photon postgis valhalla-ebike valhalla-no-trail valhalla-standard valhalla-weekend worker
```

Both checker runs need pyyaml and print the memory table and "beta compose: ok". `--env-file`
renders through `beta-compose.sh config` and parses the result in memory: it never prints a value
from `.env` (the rendered config holds every secret), only the table and any problem. If either
prints a problem, stop and report it. It checks: no caddy or rebuild; a memory cap, CPU cap and
`memswap_limit` on every container; `cpu_shares` below 1024 and `oom_score_adj` at least 500 on
every container; only the api publishing a port and only on `127.0.0.1`; the resident total under
7.0 GiB and the startup peak (plus the largest one-shot) leaving 1 GiB of the host's 8.6; at most
six gunicorn workers with one left free beside the routing, geocoding and tile pools; Photon's heap
plus capped direct buffers inside its cap; the weekly rebuild paused; every long-running service
restarting `unless-stopped` and Django debug off; and in `.env`, no `COMPOSE_PROFILES` or
`COMPOSE_FILE`, no `RESTART_POLICY` other than empty or `unless-stopped`, and no `DJANGO_DEBUG`.

Rerun the gate after **every** edit to `.env`: `beta-compose.sh` refuses the worst lines itself,
but only the gate checks the whole render.

## 5. Prepare `DATA_ROOT` (adds `$RM_DATA`)

```sh
cd "$RM_SRC"
rm_absent "$RM_DATA" && sudo sh scripts/prepare_data_root.sh --env-file ./.env
```

`/data` itself already exists (step 1) and is not touched: no `install -d`, `chown` or `chmod` on
it, because it holds other people's data. The script creates `$RM_DATA` and its subdirectories owned by the right users (this is the repository's own
script; it chowns only directories under `DATA_ROOT`). Undo: `sudo rm -rf "$RM_DATA"` only if no
data has been installed yet or the owner agreed.

## 6. Build the api image and pull the third-party images (adds Docker images)

```sh
cd "$RM_SRC"
scripts/beta/beta-compose.sh build api                 # the worker and migrate services use the same image
scripts/beta/beta-compose.sh pull postgis photon valhalla-standard
docker image ls | grep -E 'routemaker-api|postgis|photon-docker|valhalla'
```

The postgis image is pinned by digest in `compose.beta.yaml` (the build home runs, PostgreSQL 16.4, PostGIS 3.4.3):
a pull by digest fetches exactly that image and does **not** move the shared `postgis/postgis:16-3.4` tag that
another stack on the host may use. Check first which images other stacks run:
`docker ps --format '{{.Image}}' | grep -E 'postgis|photon|valhalla'`. The photon and valhalla tags are fixed
release versions (`2.4.0`, `3.5.1`); if another stack uses the same tag, the pull fetches the same release.

The build needs network access (pip) and a few minutes. Images land in Docker's storage,
Docker's root from step 1, which may be the root disk and not `/data` (the four images are about 3.7 GB).
**The build is not capped:** BuildKit runs inside the Docker daemon, outside every container
limit, and pip's install can take a core and several hundred MB for a few minutes on a host other
sites share. So either build only when the owner says the other sites are quiet, or (preferred)
have the owner build at home from the same sha and send the image, which needs no build here:

```sh
# at home, in a clean checkout of the release sha (NOT the live stack's: its .env has TAG=dev, and
# `docker compose build` there would rebuild and retag the live image from that checkout):
T=$(git rev-parse --short=12 HEAD)    # the 12-character TAG make-env.sh wrote
docker build -f docker/api.Dockerfile -t "ghcr.io/macrophage87/routemaker-api:$T" .
docker save "ghcr.io/macrophage87/routemaker-api:$T" | gzip | ssh "$RM_SSH_HOST" 'gunzip | docker load'
```

Then skip the `build` line above and run only the `pull` line.
Undo: `docker image rm ghcr.io/macrophage87/routemaker-api:<TAG>` (the third-party images may be used
by others; leave them).

## 7. Receive the data (adds files under `$RM_DATA`)

**At home (owner).** This box is for the owner; you only need to know it, and to ask for the
bundle if it is not at `$RM_INCOMING` yet. The owner runs it one line at a time, in a shell of their
own, once you report step 2 done. `RM_SSH_HOST` is typed in that shell only and never written into a
file in the checkout. The live stack must be up (ship-data reads its database).

```sh
export RM_SSH_HOST=<your ssh alias for the server, from ~/.ssh/config>
export RM_SHA=<the release sha>  RM_HOME_SRC=<a clean checkout of it>  RM_LIVE_DIR=<the live stack's checkout>
cd "$RM_HOME_SRC"
[ "$(git rev-parse HEAD)" = "$RM_SHA" ] && [ -z "$(git status --porcelain)" ] && echo "clean at the release sha"
git ls-remote origin | grep "$RM_SHA"                          # the server can clone it
ssh "$RM_SSH_HOST" 'id -nG; uname -m'                          # in the docker group; x86_64
T=$(git rev-parse --short=12 HEAD)                             # the TAG make-env.sh writes
docker build -f docker/api.Dockerfile -t "ghcr.io/macrophage87/routemaker-api:$T" .
docker save "ghcr.io/macrophage87/routemaker-api:$T" | gzip | ssh "$RM_SSH_HOST" 'gunzip | docker load'
ssh "$RM_SSH_HOST" 'stat -c %U /data/routemaker-incoming; id -un'   # the same user twice
scripts/beta/ship-data.sh --live-dir "$RM_LIVE_DIR" --build-frontend  "$RM_SSH_HOST"  /data/routemaker-incoming
```

With the image loaded this way, skip step 6's `build` line and run only its `pull` line.
`--build-frontend` runs the front-end tests and builds it with the beta notice; `ship-data.sh` stops if
neither it nor `--dist` is given. To add a "Report a problem" link to the notice (OWNER-DECISIONS 382,
for example a Discord invite once there is one), the owner adds `--report-url https://...`; without it
the notice says only to tell the person who gave you access. The link is built into the front end, so
repeat the same `--report-url` on every later ship that carries the front end (data updates and
releases included), or the next `files` installs a notice without it.

It sends about 4 GB (see "What the bundle holds" below) and is resumable: if the connection drops the
owner reruns the same command. `SHA256SUMS` arrives last, so a half-sent bundle has none.

On the server:

```sh
cd "$RM_SRC"
scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env verify      # must print "bundle ok" and exit 0
sudo scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env files  # installs, switches `current`, re-verifies
```

`files` copies the four routing graphs under `tiles/<graph>/<build>/` and points `current` at the new
build (the old one is recorded as `previous` and kept), then elevation, base map, the Photon index and
the front end. It installs only the files `SHA256SUMS` lists and only the builds `MANIFEST.txt`
names, so anything an earlier bundle left in `$RM_INCOMING` is skipped (and reported). If photon is
running and the bundle carries its index, `files` stops photon first and starts it again after.
It verifies every installed file's sha256 again. It refuses if `/data` lacks room.

Then the database, which needs postgis running first:

```sh
scripts/beta/beta-compose.sh up -d postgis
scripts/beta/beta-compose.sh ps postgis           # wait for "healthy" (up to a minute on first start)
sudo scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env db
```

`db` restores the dump (the `live` and `public` schemas), analyses, and compares each table's row
count with the bundle's. The dump carries **no identities**: no accounts, audit log, bootstrap
claims, pending admin removals, ban tombstones, guild roster or role mappings (OWNER-DECISIONS
367.3); every foreign key is still created, because nothing left points at what was stripped.
The beta starts with no accounts and the owner claims admin afresh (step 3, `BOOTSTRAP_...`). It takes about a minute (56 s for the stripped dump in a throwaway postgis under this overlay's caps, 2026-10-04): PostgreSQL's own memory stays small, and the cgroup fills to its 1 GiB cap with page cache, which the kernel reclaims (no OOM kill).
It refuses to replace a database that already has data unless you pass `--replace-db`, which first
writes a safety dump to `$RM_DATA/backups/pre-restore-<time>.dump`. A `MISMATCH` line in the `live`
schema is a stop: do not start the api.

Undo: the routers and api read `current`; to go back to the previous graphs see "Rollback".
To remove the data entirely, stop the stack and `sudo rm -rf` the directories under `$RM_DATA` the
owner names.

## 8. Start the stack (adds containers)

Named services, in this order. `up -d api` also runs `migrate` first (compose waits for it to finish).

```sh
cd "$RM_SRC"
scripts/beta/beta-compose.sh up -d photon valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
scripts/beta/beta-compose.sh up -d api worker
scripts/beta/beta-compose.sh ps
scripts/beta/beta-compose.sh logs --tail 30 migrate        # "No migrations to apply" (the dump carries the migration history)
```

Migrations check, and Django's static files (the admin's CSS; nginx serves `$RM_DATA/static`). Both
run inside the running api container, under its cap (rule 2), not as a second api container:

```sh
scripts/beta/beta-compose.sh exec -T api ./manage.py migrate --check && echo "migrations current"
scripts/beta/beta-compose.sh exec -T api ./manage.py collectstatic --noinput
```

nginx's worker user (`$NGINX_USER`, from step 1) must be able to read what the site file serves;
read-only checks:

```sh
for f in "$RM_DATA/frontend/index.html" "$RM_DATA/basemap/region.pmtiles" "$RM_SRC/deploy/beta/401.html"; do
  sudo -u "$NGINX_USER" test -r "$f" && echo "nginx can read $f" || echo "NOT READABLE by nginx: $f (stop and ask the owner)"
done
```

**Binds that refuse a missing source (the proof; this is the authority).** `compose.beta.yaml`
asks for every RouteMaker bind with `create_host_path: false`, and the checker reads that from the
files, but whether this host's Compose and engine honour it is proved here, read-only. Compose
passes a bind that may be created as a legacy `Binds` entry, and one that must not be created as a
`Mounts` entry, which the engine refuses when the source is missing:

```sh
for c in $(docker ps -q --filter label=com.docker.compose.project=routemaker-beta); do
  docker inspect -f '{{.Name}}{{range .HostConfig.Binds}} LEGACY-BIND={{.}}{{end}}{{range .HostConfig.Mounts}}{{if eq .Type "bind"}} mount={{.Source}}{{if .BindOptions}}{{if .BindOptions.CreateMountpoint}}(CREATES){{end}}{{end}}{{end}}{{end}}' "$c"
done   # every RouteMaker source must show as mount=...; any LEGACY-BIND= or (CREATES) is a STOP
```

Then the engine itself, once, on a path that does not exist (it creates nothing when it works):

```sh
rm_absent "$RM_STATE/no-such-dir" && docker create --mount "type=bind,source=$RM_STATE/no-such-dir,target=/x" --entrypoint true "$(docker inspect -f '{{.Config.Image}}' "$(scripts/beta/beta-compose.sh ps -q postgis)")"
ls -d "$RM_STATE/no-such-dir" 2>/dev/null || echo "not created"   # expected: the create failed with "bind source path does not exist", and "not created"
```

If `docker create` printed a container id instead, the engine would create missing sources:
`docker rm` that id, `rmdir "$RM_STATE/no-such-dir"` if it appeared, and stop and report it to the
owner. The /data safeguard would then not hold on this host.

Health and memory:

```sh
curl -s -H 'Host: routemaker.cieply.com' "http://127.0.0.1:$BETA_API_PORT/healthz"   # ok
scripts/beta/smoke-test.sh --local                                              # route, search, reverse, stress tile; all PASS
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' | grep routemaker-beta
free -m
```

Every container should sit well under its cap (api about 0.5 GiB at six workers, photon about
1 GiB, each router under 0.7 GiB). Then measure the two-plans-at-once case once (OWNER-DECISIONS
367.2), and report the api's and photon's peaks against their 1450M and 1300M caps:

```sh
for i in 1 2; do curl -s -o /dev/null -w "plan $i: %{http_code} in %{time_total}s\n" -H 'Host: routemaker.cieply.com' \
  -H 'Content-Type: application/json' -d '{"points":[[-77.0353,38.8895],[-77.0369,38.9072]],"preset":"default"}' \
  "http://127.0.0.1:$BETA_API_PORT/api/route" & done; wait
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' | grep -E 'api|photon'
```
 Photon needs a minute after start before its first search answers. If any container
is near its cap or `docker inspect -f '{{.State.OOMKilled}}' <name>` prints `true`, report it with
the numbers; do not raise a cap on your own.

**Draw the stress tiles, before any tester is invited.** The bundle carries no stress-tile cache:
each cached tile is keyed on the oid of the live segment table, and the restore here created that
table afresh, so home's rows could never match. Until this runs, every map view draws its tiles
live through the api's one draw slot, and a street-level screen takes 20-30 s. It runs inside the
worker's own cap (one draw at a time, `STRESS_PREDRAW_WORKERS=1`), not as a second api. It runs
longer than a tool call may wait, so start it detached, with its output in a private log, and poll:

```sh
( umask 077; nohup scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles < /dev/null > "${RM_STATE:?set RM_STATE as in step 1}/predraw.log" 2>&1 & )
tail -n 3 "$RM_STATE/predraw.log"   # repeat, a minute or so apart, until the last line is "stress tiles: N drawn, ..., in S s"
docker inspect -f '{{.State.OOMKilled}} {{.RestartCount}}' $(scripts/beta/beta-compose.sh ps -q worker)   # false 0
```

**Never start it again while the log has no `stress tiles:` line.** Stopping or timing out the
command that started it does not stop the draw inside the worker, so a second one would draw beside
it, inside the same cap and against the same postgis. Expected time: the whole z10-14 box is 11,068
tiles, which took 155 s at home with one draw at a time; here postgis has 1.5 CPUs on a shared host,
so allow 5 to 15 minutes. It has a one-hour budget; if the final line says it stopped short with
some left, start it once more (it draws only those). Do not invite testers (step 11) until it has
finished. If the worker was OOM-killed, report it with the numbers; do not raise its cap. This is
"the step 8 pre-draw" that the update and rollback paths below repeat.

Undo: `scripts/beta/beta-compose.sh down` (containers and network only; `$RM_DATA` is untouched).

## 9. nginx: add one file, in two stages (adds `$NGINX_SITE`, the htpasswd file, optionally a certificate)

Nothing public is served until stage 2. `render-nginx.sh` only prints or writes the file you name;
it never touches `/etc`.

### 9a. The password file

```sh
cd "$RM_SRC"
sudo scripts/beta/make-htpasswd.sh <name1> <name2> ...      # one name per tester; refuses to overwrite
```

It writes `/etc/nginx/routemaker-beta.htpasswd` (root, group of the nginx worker user, mode 640)
with SHA-512 crypt hashes (`openssl passwd -6`; nginx checks them with the system's crypt(), which
on Ubuntu verifies `$6$`), and the generated passwords to `~/routemaker-beta-passwords.txt`
(mode 600, yours). It prints only that path, never a password. **Do not `cat` the file and do not
put a password in your report**: tell the owner where the file is; he reads it in his own
terminal, sends each tester theirs with `docs/BETA-TESTER-HANDOUT.md` (plain text: open the link
in a real browser, the browser's own sign-in box, the case-sensitive user name, pasting and
saving the password, what a wrong password looks like, the screen-reader layout, and where to
report), and deletes the file (`shred -u`).

User names must be lowercase (letters, digits, dot, dash, underscore; nginx compares them
case-sensitively). Each password is four dash-separated groups of five lowercase letters and
digits with no look-alikes (no i, l, o, 0 or 1), about 99 bits, so it can be read out by a
screen reader and pasted without confusion. To choose a password yourself skip the script and
use `openssl passwd -6` (it prompts). To add a tester later:
`sudo htpasswd -B /etc/nginx/routemaker-beta.htpasswd <lowercase name>` (bcrypt, also fine for nginx
on Ubuntu), with a password in the same format. Undo: `sudo rm /etc/nginx/routemaker-beta.htpasswd`
(only after the site file is removed).

### 9b. TLS: the option step 1's discovery chose

Use the rule from step 1 (OWNER-DECISIONS 367.1): **B** if an existing certificate covers
`routemaker.cieply.com` or `*.cieply.com`, is more than 14 days from expiry and renews
automatically; **A** otherwise. Say in your report which one, with the `openssl x509` lines that
decided it.

**Option A: certbot issues a certificate for `routemaker.cieply.com` only, by webroot.** Install
the stage-1 file, which answers only the ACME challenge on port 80, then run certbot's `--webroot`
authenticator. It writes the challenge into `/var/www/routemaker-acme` and touches no nginx file;
its renewals reuse the same `webroot_path`. Not `--nginx` (it edits and reloads the host's nginx
config at issue and at every renewal), and not the installer form (it would rewrite this site file).

```sh
cd "$RM_SRC"
rm_absent /var/www/routemaker-acme "$NGINX_SITE" "$NGINX_LINK" && sudo install -d /var/www/routemaker-acme
scripts/beta/render-nginx.sh --stage acme [--no-ipv6] --out "$RM_STATE/routemaker-beta.acme.conf"
rm_absent "$NGINX_SITE" "$NGINX_LINK" && sudo install -m 644 "$RM_STATE/routemaker-beta.acme.conf" "$NGINX_SITE" && { [ "$NGINX_LINK" = "$NGINX_SITE" ] || sudo ln -s "$NGINX_SITE" "$NGINX_LINK"; }
sudo nginx -t && sudo nginx -s reload
sudo certbot certonly --webroot -w /var/www/routemaker-acme -d routemaker.cieply.com
sudo ls /etc/letsencrypt/live/routemaker.cieply.com/        # fullchain.pem and privkey.pem
```

Certbot's existing renewal timer renews it; the port-80 ACME location stays in the final file for
that. Then continue to 9c with `--cert-fullchain /etc/letsencrypt/live/routemaker.cieply.com/fullchain.pem`
and `--cert-key /etc/letsencrypt/live/routemaker.cieply.com/privkey.pem`.

**Option B: reuse the certificate step 1 found.** Use its paths as they are, and skip stage 1.
For a certbot certificate, `sudo certbot certificates` gives them: its `Certificate Path` is
`--cert-fullchain` and its `Private Key Path` is `--cert-key`. For a certificate certbot does not
manage, use the `ssl_certificate` and `ssl_certificate_key` paths of the site that already uses it.
Do not run `certbot renew --force` or alter any existing certificate.

Whichever option, if the host's other sites include certbot's `options-ssl-nginx.conf`, add
`--tls-options-include /etc/letsencrypt/options-ssl-nginx.conf` in 9c to match them.

### 9c. The full site

```sh
cd "$RM_SRC"
scripts/beta/render-nginx.sh --stage full --api-port "$BETA_API_PORT" \
    --cert-fullchain <path> --cert-key <path> [--tls-options-include <path>] [--no-ipv6] \
    --out "$RM_STATE/routemaker-beta.full.conf"
# exactly one of the next two lines acts, the one for the TLS_OPTION step 1 chose:
# option A: replace the stage-1 file, only if it is the one this runbook installed in 9b (its link already points at it)
[ "$TLS_OPTION" = A ] && grep -q 'Rendered by scripts/beta/render-nginx.sh (stage acme)' "$NGINX_SITE" && sudo install -m 644 "$RM_STATE/routemaker-beta.full.conf" "$NGINX_SITE"
# option B: stage 1 was skipped, so this is a new file and must not exist yet
[ "$TLS_OPTION" = B ] && rm_absent "$NGINX_SITE" "$NGINX_LINK" && sudo install -m 644 "$RM_STATE/routemaker-beta.full.conf" "$NGINX_SITE" && { [ "$NGINX_LINK" = "$NGINX_SITE" ] || sudo ln -s "$NGINX_SITE" "$NGINX_LINK"; }
sudo nginx -t && sudo nginx -s reload                                   # -t must say "syntax is ok" and "test is successful"
curl -s -o /dev/null -w '%{http_code}\n' https://routemaker.cieply.com/   # must print 401 at once; a 403 or 404 means nginx cannot serve the sign-in page (step 10, "If the 401 lines fail")
```

`--no-ipv6` drops the `listen [::]:80` and `listen [::]:443` lines: give it when step 1 found no
`listen [::]` in the other sites (an IPv6-disabled host makes `nginx -t` fail on them, safely).
The rendered file says at its top which template, stage and git sha it was rendered from.

If `nginx -t` complains about `http2 on`, the host's nginx is older than 1.25.1: edit the installed file,
delete the `http2 on;` line and write `listen 443 ssl http2;` and `listen [::]:443 ssl http2;`, then test again.

Prove nothing else changed:

```sh
(umask 077; sudo nginx -T > "$RM_STATE/nginx-after.txt" 2>&1)
diff <(sed 's/[[:space:]]*$//' "$RM_STATE/nginx-before.txt") <(sed 's/[[:space:]]*$//' "$RM_STATE/nginx-after.txt") | grep '^<' | head   # no output: nothing was removed or edited
while read -r s; do printf '%s %s\n' "$s" "$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$s/" || echo fail)"; done < "$RM_STATE/sites-before.txt" | diff - "$RM_STATE/sites-before-status.txt" && echo "other sites unchanged"
```

Undo, whenever: `sudo rm "$NGINX_SITE"` (and the `sites-enabled` link if you made one), `sudo nginx -t && sudo nginx -s reload`.
The site is then gone and the other sites never noticed.

What the site does, so you can explain it to the owner: only `robots.txt` (and the port-80 ACME
challenge path) is public; everything else, including `/healthz`, `/auth/` and the admin path, asks for
a password. Every response carries `X-Robots-Tag: noindex, nofollow`. `/api` has 75-second timeouts
(a plan takes up to 47 seconds). JSON and vector tiles are gzipped. The base map answers only this
site's own pages.

## 10. Smoke test through nginx

```sh
cd "$RM_SRC"
scripts/beta/smoke-test.sh --public https://routemaker.cieply.com --passwords-file ~/routemaker-beta-passwords.txt
```

(It signs in as the first tester in the file, reading the password itself and passing it to curl on
standard input; no password is in the command line, the output or your transcript.) Every line must
say `PASS`. It checks: robots.txt is public and disallows everything; `/` and `/healthz` return 401
without credentials and a wrong password is refused; the 401 still asks for a password
(`WWW-Authenticate: Basic`) and its page says how to get in; noindex and the content security policy are
present; http redirects to https; the front end loads; a preset link redirects; the base map answers
this site's byte-range request with 206 and is refused to a foreign origin; an unlisted base-map path
is a 404; Django's static files are served; a route, a place search, a reverse lookup and a stress
tile all answer.

**If the 401 lines fail with 403 or 404** (here or in 9c's curl), nginx cannot serve the sign-in page
(`$RM_SRC/deploy/beta/401.html`), and nobody gets the browser's sign-in box. Re-render without the
page, install it over the file this runbook put there, reload, rerun this step, and report it to the
owner (do not edit the installed file by hand):

```sh
scripts/beta/render-nginx.sh --stage full --api-port "$BETA_API_PORT" --no-401-page \
    --cert-fullchain <path> --cert-key <path> [--tls-options-include <path>] [--no-ipv6] \
    --out "$RM_STATE/routemaker-beta.full-no401.conf"
grep -q 'Rendered by scripts/beta/render-nginx.sh (stage full)' "$NGINX_SITE" && sudo install -m 644 "$RM_STATE/routemaker-beta.full-no401.conf" "$NGINX_SITE"
sudo nginx -t && sudo nginx -s reload
```

Use the same options as in 9c, plus `--no-401-page`. Cancel then shows nginx's own plain
"401 Authorization Required" page; the sign-in box itself is unchanged.

Then check by eye, once, in a browser the owner can use: the page loads behind the password prompt,
the map draws, a two-point route appears, and the **Beta notice** is shown in the planner panel, under the
RouteMaker heading (it appears only in the front end built with `VITE_BETA=1`, which
`ship-data.sh --build-frontend` does). And one screen-reader pass (VoiceOver or NVDA): the password
prompt is read and can be filled; "Beta notice" is in the landmarks list and is read after the
heading; Dismiss puts focus on "Route planner".

## 11. Report back to the owner

Say: the sha running, that all checks passed (or exactly which did not), `docker stats` numbers against the
caps (including the two-plans-at-once measurement), the other-sites comparison, which TLS option step 1's
rule chose and why, **where** the testers' passwords are (`~/routemaker-beta-passwords.txt`; never the
passwords themselves), and the `df -h /data` figure. Remind the owner to send each tester
`docs/BETA-TESTER-HANDOUT.md` with their user name and password, as text they can copy, and only
once the stress-tile pre-draw (step 8) has finished.

---

## Rollback and uninstall

Smallest undo first. None of these touch the other sites.

**A. Go back to the previous routing graphs** (after a data update that turned out wrong):

```sh
cd "$RM_SRC"
for g in standard no-trail ebike weekend; do
  sudo ln -sfn "$(readlink "$RM_DATA/tiles/$g/previous")" "$RM_DATA/tiles/$g/current.new" && sudo mv -T "$RM_DATA/tiles/$g/current.new" "$RM_DATA/tiles/$g/current"
done
scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
```

If that update also carried a db part (`db --update-data`), do **B** as well, with the
`pre-update-<time>.dump` it wrote: the graphs and the `live` schema are one build, and the old graphs
against the new `live` mix segment attributes from one build with edges from another. A Photon index
that the update's `files` replaced has no `previous`: rollback A does not bring it back.

**B. Go back to the previous database:** restore the safety dump the last data update wrote
(`pre-update-<time>.dump` from `db --update-data`, or `pre-restore-<time>.dump` from `--replace-db`).
`restore-dump` takes a `pre-rollback` snapshot of what is there first, restores the dump into a
**fresh** database in one transaction (a failure discards it and leaves the current database
untouched), and swaps it in by rename. The database as it was stays beside it as
`routemaker_before_<time>`; once the beta works, drop it
(`scripts/beta/beta-compose.sh exec -T postgis dropdb -U routemaker routemaker_before_<time>`). It needs
free space on `/data` for a second copy of the database (about 1.5 GB):

```sh
scripts/beta/beta-compose.sh stop api worker
ls -l "$RM_DATA"/backups/pre-*.dump
sudo scripts/beta/receive-data.sh --env-file .env restore-dump "$RM_DATA/backups/pre-update-<time>.dump"
scripts/beta/beta-compose.sh up -d api worker
( umask 077; nohup scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles < /dev/null > "${RM_STATE:?set RM_STATE as in step 1}/predraw.log" 2>&1 & )
tail -n 3 "$RM_STATE/predraw.log"   # the step 8 pre-draw: the restored database has a new live table, so the tile cache is cold
```

**C. Go back to the previous release:** the previous api image is still on the host under its own tag. Retagging
alone is not enough when the new release migrated the database forward: the old code would run against a
newer schema. So rollback C also puts back the `pre-release` snapshot taken just before the update
("Shipping an update later", new release, step 2), and the old front end's `index.html` saved in the
same step (the hashed assets it names are never deleted, so `index.html` alone brings back the old app):

```sh
cd "$RM_SRC"
scripts/beta/beta-compose.sh stop api worker
git checkout --detach <previous sha>
sed -i 's/^TAG=.*/TAG=<previous 12-character sha>/' .env          # the one edit to .env a release change needs
"${RM_PY:-python3}" scripts/check_beta_compose.py --env-file .env    # the gate, after every .env edit: "beta compose: ok"
sudo scripts/beta/receive-data.sh --env-file .env restore-dump "$RM_DATA/backups/pre-release-<time>.dump"
sudo cp -p "$RM_DATA/backups/index.html.pre-release-<time>" "$RM_DATA/frontend/index.html.new" && sudo mv -T "$RM_DATA/frontend/index.html.new" "$RM_DATA/frontend/index.html"
scripts/beta/beta-compose.sh up -d api worker                     # recreates them on the old image; migrate finds nothing to do
scripts/beta/beta-compose.sh up -d photon valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend   # recreates only those whose image or command the release changed
( umask 077; nohup scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles < /dev/null > "${RM_STATE:?set RM_STATE as in step 1}/predraw.log" 2>&1 & )
tail -n 3 "$RM_STATE/predraw.log"   # the step 8 pre-draw: the restored database has a new live table
```

If the release also shipped new graphs (its step 7 ran `files`), do **A** as well, before the
`up -d api worker` line: the restored `live` is the old build's, and `current` would still point at the
new graphs. A Photon index replaced in that step is not rolled back.

Because the dump goes into a fresh database, tables the newer release added do not survive into
the restored one (a restore over the current database could not drop them). Anything the beta's users saved after the update is lost by this (the `pre-rollback` snapshot `restore-dump`
takes first still has it). (If the old image was removed, `scripts/beta/beta-compose.sh build api` rebuilds it
from that checkout.)

**D. Take the beta offline, keep everything:** `sudo rm "$NGINX_SITE"` (and its link), `sudo nginx -t && sudo nginx -s reload`.
The containers can keep running, bound to `127.0.0.1`, or stop with `scripts/beta/beta-compose.sh down`.

**E. Uninstall completely**, in this order, with the owner's agreement for the destructive lines:

```sh
cd "$RM_SRC"
sudo rm -f "$NGINX_SITE"; sudo rm -f /etc/nginx/sites-enabled/routemaker-beta.conf     # whichever exist
sudo nginx -t && sudo nginx -s reload
sudo rm -f /etc/nginx/routemaker-beta.htpasswd
scripts/beta/beta-compose.sh down
docker image rm ghcr.io/macrophage87/routemaker-api:<TAG>
# destructive, owner's say-so: the data and the checkout
sudo rm -rf /data/routemaker /data/routemaker-incoming /data/routemaker-src /var/www/routemaker-acme "$HOME/routemaker-beta-state"
# only if Option A created it and nothing else uses it:
sudo certbot delete --cert-name routemaker.cieply.com
```

## Shipping an update later

The tooling is the same each time. Ask the owner which kind it is.

**New data only** (a fresh build of the tiles, database or Photon index, same release):

1. At home: `ship-data.sh ...` as before; `--without` leaves out parts that did not change
   (`--without photon --without basemap --without elevation` for a new tile build and database). It sends only
   what differs, because rsync compares.
2. Server: `receive-data.sh --bundle "$RM_INCOMING" --env-file .env verify`, then `sudo ... files`.
   `files` adds the new build beside the old and swaps `current` (the old stays as `previous`, which is rollback A).
   If the bundle carries the Photon index, `files` stops photon, replaces the index and starts it again.
3. If the bundle has a db part, use the **update path**, never `--replace-db`: it restores only the `live` schema
   and the `override` data (and empties the beta's stress-tile cache, which the new `live` table makes stale), in
   one transaction, after a `pre-update` safety dump, and leaves
   the beta's own accounts, sessions and audit log alone (`--replace-db` would delete them; it refuses while any
   exist). **It resets `override` to home's**: an override added or edited on the beta is lost (it is in the
   `pre-update` safety dump). Make override changes at home, or ask the owner before updating if any were made on
   the beta. Stop the api and worker first so nothing writes during it:

   ```sh
   scripts/beta/beta-compose.sh stop api worker
   sudo scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env db --update-data
   scripts/beta/beta-compose.sh up -d api worker
   ( umask 077; nohup scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles < /dev/null > "${RM_STATE:?set RM_STATE as in step 1}/predraw.log" 2>&1 & )
   tail -n 3 "$RM_STATE/predraw.log"   # 5-15 min; poll until the "stress tiles:" line (step 8)
   ```

   The pre-draw is not optional: until it finishes, every map view draws its tiles live (step 8,
   "Draw the stress tiles"). Run it before telling the testers the update is in.
4. `scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`
   (a router keeps the old archive mapped until restarted).
5. `scripts/beta/smoke-test.sh --local`, then `--public`.

**A new release sha** (code changes). The order matters: the database is snapshotted **before**
anything can run `migrate` (rollback C restores that snapshot), and the app starts once, at the end.

1. Owner gives the new sha and a new bundle if the data changed.
2. Stop the app and snapshot the database, still on the old release:

   ```sh
   cd "$RM_SRC"
   scripts/beta/beta-compose.sh stop api worker
   sudo scripts/beta/receive-data.sh --env-file .env snapshot-db --label release   # prints $RM_DATA/backups/pre-release-<time>.dump
   sudo cp -p "$RM_DATA/frontend/index.html" "$RM_DATA/backups/index.html.pre-release-<the same time>"   # rollback C puts it back
   ```
3. `git fetch && git checkout --detach <new sha>`. `scripts/beta/make-env.sh` will not overwrite `.env`; set the
   image tag by hand: `sed -i "s/^TAG=.*/TAG=$(git rev-parse --short=12 HEAD)/" .env`.
4. `"${RM_PY:-python3}" scripts/check_beta_compose.py --env-file .env` (a release may change the compose file; the
   checker is the gate).
5. `scripts/beta/beta-compose.sh build api` (or load the image built at home, step 6).
6. Migrate, in the small migrate container (the api stays stopped):
   `scripts/beta/beta-compose.sh run --rm --no-deps migrate ./manage.py migrate --noinput`.
7. If the data changed: the "New data only" steps 2 and 3 (`verify`, `files`, `db --update-data`) **without** their
   final `up -d api worker` line; the app is started once, in the next step.
8. `scripts/beta/beta-compose.sh up -d api worker` (recreates them on the new image; `migrate` finds nothing to do),
   then the migrations check and `collectstatic` from step 8 (`exec -T api ...`), the stress-tile pre-draw from
   step 8 if step 7 ran `db --update-data` (or the release changed what the tiles draw), and the smoke tests. Routers and
   Photon restart only if their image or command changed in the release (`beta-compose.sh up -d <name>` recreates
   exactly the ones that did).
9. The front end comes in the bundle (`frontend/`), so `files` installs it; the new `index.html` goes in last.

**Front end only:** ship with `ship-data.sh --live-dir "$RM_LIVE_DIR" --build-frontend [--report-url <the same as before>]
--without tiles --without elevation --without basemap --without photon --without db "$RM_SSH_HOST" /data/routemaker-incoming`,
then `sudo ... files`. Nothing restarts; `index.html` is read per request.

## Operating notes

- **Memory events:** `docker inspect -f '{{.Name}} {{.State.OOMKilled}} {{.RestartCount}}' $(docker ps -q --filter label=com.docker.compose.project=routemaker-beta)`.
  A container that was OOM-killed restarts by itself (`restart: unless-stopped`); report it with its `docker stats` history.
- **Routing capacity:** six gunicorn workers allow two route plans at once across the whole site (OWNER-DECISIONS 367.2),
  beside two place searches and one stress-tile draw, with one worker always free for `/healthz`. A third person's plan waits
  for a slot, up to about 50 seconds. That is a consequence of the memory budget, not a fault. `compose.beta.yaml` explains
  the arithmetic.
- **Overrides:** the beta's `override` table comes from home. `db --update-data` replaces it with home's, so an
  override made on the beta does not survive a data update (the `pre-update` dump keeps it). Curate overrides at home.
- **Photon's memory margin (review r1, N8):** heap 896M + direct buffers 192M + about 192M of other native memory is
  1280M of the 1300M cap; the 192M is an estimate. On the first smoke run, report photon's anonymous memory
  (`docker exec <photon container> sh -c 'cat /sys/fs/cgroup/memory.current; grep -E "^(anon|file) " /sys/fs/cgroup/memory.stat'`;
  `anon` is what counts, `file` is the reclaimable index cache), and watch `logs photon` for
  `OutOfMemoryError: Direct buffer memory`, which may be thrown inside Java code without the JVM exiting.
- **CPU shares are per container (review r1, N9):** each RouteMaker container weighs about 20 against 100 for a
  container or service that sets nothing, but there are nine of them, so when several are busy at once (two plans
  hitting the api, the routers and postgis) RouteMaker's total weight can reach about 180. Other sites still get a
  guaranteed share; "they win" holds per container, not in aggregate. If the owner wants a firmer yield, lower
  `cpu_shares` to 256 (weight about 10) in `compose.beta.yaml`.
- **Accounts:** the beta has its own, none from home (OWNER-DECISIONS 367.3). Data updates (`db --update-data`) never touch
  them; only `db --replace-db --delete-beta-accounts` or rollback B/C to a dump from before they existed removes them.
- **Backups:** the worker writes a nightly dump to `$RM_DATA/backups` (seven kept, about 200 MB each, without sessions or
  client-address rows). They are on the same disk; copying them off the server is the owner's decision.
- **Reboot:** containers restart with Docker (`unless-stopped`). `RESTART_POLICY` stays unset in `.env`, because
  `no` is the home Docker Desktop machine's setting: `beta-compose.sh` refuses a value other than empty or
  `unless-stopped` in `.env` and in the shell, and the checker refuses it in `.env` and in the rendered config.
- **Reboot and a late `/data`:** `/data` is mounted `nofail` and Docker's own storage may be on the root disk
  (step 1's `DockerRootDir`), so Docker can start, and restart the containers, before `/data` is mounted. Every
  RouteMaker bind mount has `create_host_path: false` (`compose.beta.yaml`, "Bind mounts never create their
  source"), so the engine refuses to start a container whose source is missing instead of handing it an empty
  directory on the root disk (where postgis would initialise an empty database). If `/data` was late, the
  RouteMaker containers are down and `docker ps -a` and `docker inspect` show
  `bind source path does not exist`. Once `findmnt /data` shows it mounted, start them in step 8's order:
  `scripts/beta/beta-compose.sh up -d postgis`, wait for healthy, then
  `scripts/beta/beta-compose.sh up -d photon valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`
  and `scripts/beta/beta-compose.sh up -d api worker`. The host-side fix (a systemd drop-in for `docker.service`
  with `After=data.mount` and `RequiresMountsFor=/data`) is the owner's call: report the event, and never apply
  that drop-in yourself.
- **Debug stays off.** `make-env.sh` never writes `DJANGO_DEBUG`, so the containers run with it off.
  `beta-compose.sh` refuses a non-empty `DJANGO_DEBUG` in `.env` and in the shell, and the checker refuses it in
  `.env` and in the rendered config. Do not add it to `.env`, even to chase a fault: read `beta-compose.sh logs api`.
- **The shell does not reach compose.** `beta-compose.sh` runs compose with only `PATH`, `HOME`, `DOCKER_HOST` and
  `DOCKER_CONFIG` from your environment (the gate renders with the same four), so every setting comes from `.env`.
  Exporting `DATA_ROOT`, `TAG` or a `BETA_...` value in your shell changes nothing; edit `.env` and rerun the gate.
- **Logs:** `scripts/beta/beta-compose.sh logs --tail 100 api`. Access logs carry no query strings or addresses by design.
- **No rebuild runs here.** There is no rebuild container, and `WEEKLY_REBUILD_PAUSED=1` is set so that a rebuild
  worker started by mistake would only record a pause. New routing data always comes from home as a bundle. Expected,
  and not a fault: the worker's schedule still queues the weekly tick, and with no rebuild worker to take it one
  `weekly_rebuild` job waits on the `rebuild` queue (its queueing lock keeps it to one), and `check_operations` and
  the admin's operations page list `weekly_rebuild` as stale, from about eight days after setup (its
  staleness window runs from the deployment; nothing shows in the first week). Do not start a rebuild worker to
  clear either. **Never run `run_rebuild_now` here** (for example `beta-compose.sh exec worker ./manage.py
  run_rebuild_now`): a hand-fired rebuild ignores the pause by design, and the wrapper does not catch it.
- **`scripts/boot/` is for the home machine only.** Never install its unit or run `start-stack.sh` here (step 1).
- **What the bundle holds** (sizes measured 2026-10-04): the four routing graphs' `tiles.tar` and sqlite files 2.2 GB
  (standard 611 MB, no-trail 450 MB, ebike 611 MB, weekend 611 MB), the Photon index 742 MB, elevation 310 MB, the base map
  298 MB, the database dump 207 MB (that figure still held the stress-tile cache, which is no longer shipped, so it is
  smaller now), the front end 3 MB: about 3.74 GiB in 1259 files, checksummed one by one.
