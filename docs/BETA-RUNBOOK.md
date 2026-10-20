# Beta runbook: RouteMaker on the owner's server

For the owner's Claude on the server. It stands up a private beta of RouteMaker at
`https://beta.example.org` for trusted friends and family (OWNER-DECISIONS 360-362). Read
the whole file before running anything. Every step says what it changes and how to undo it.

**`beta.example.org` stands for the beta's real name** throughout: the owner gives it to you, and
it lives only in the server's `.env` (`RM_BETA_HOST`, written by `make-env.sh --host`), never in
this repository. Type the real name wherever this file says `beta.example.org`.
`render-nginx.sh`, `smoke-test.sh --local` and the deploy agent read it from `.env` and stop with
a message naming `RM_BETA_HOST` when it is missing; on a server set up before v0.7.0, add the line
`RM_BETA_HOST=<the beta's name>` to `.env` once.

## What this changes on the host, and nothing else

| Where | What | Undo |
| --- | --- | --- |
| Docker | One compose project, `routemaker-beta`: containers postgis, api, worker, photon and four routers, plus the two trail routers (valhalla-offroad, valhalla-mtb) once their tiles are on the host; one network | `scripts/beta/beta-compose.sh down` |
| `/data/routemaker-src` | The checkout of the exact release sha | `rm -rf` it |
| `/data/routemaker` | `DATA_ROOT`: tiles, database files, Photon index, base map, front end, backups | `rm -rf` it, only after the owner agrees |
| `/data/routemaker-incoming` | The bundle as shipped from home (about 4 GB) | `rm -rf` it |
| nginx | **One new file** (`routemaker-beta.conf`) and one htpasswd file beside `nginx.conf`. No existing file is edited. Once running, nginx also writes the beta's own two logs, `/var/log/nginx/rmbeta-access.log` and `/var/log/nginx/rmbeta-error.log` (rotated with the host's other nginx logs) | delete both files, `nginx -t`, reload; then `rm -f` the two logs and their rotated copies (`rmbeta-*.log*`) |
| `/var/www/routemaker-acme` | Only if option A (certbot `--webroot`) is chosen | `rm -rf` it |
| `~/routemaker-beta-state` | Mode 700: the before/after copies of `nginx -T` and the other sites' status codes | `rm -rf` it |
| `~/routemaker-beta-passwords.txt` | Mode 600: the testers' passwords, for the owner to read and hand out | the owner deletes it (`shred -u`) |
| `~/routemaker-beta-state/cd`, `~/.config/systemd/user/routemaker-beta-cd.*` | Only once continuous deployment is installed ("Continuous deployment", below): the release agent, its state, logs and pre-release snapshots, and its user timer | `auto-release.sh uninstall`, then `rm -rf` the `cd` directory |
| `~/routemaker-beta-state/alert-webhook`, `~/routemaker-beta-state/release-webhook`, `~/routemaker-beta-state/alerts`, `~/.config/systemd/user/routemaker-beta-alert.*` | Only once alerts are installed ("Alerts", below): the Discord webhook addresses (mode 600), what was last posted, and the check timer | `alert.sh uninstall`, then `rm` the webhook files and the `alerts` directory |

Every RouteMaker path above is created only after a check that it **does not exist yet**; if one
does, stop and ask the owner. Nothing here changes the owner, group or mode of a directory that
already exists (`/data` included: it holds other people's data).

It does not touch the other sites, `nginx.conf`, the firewall, the system packages' configuration,
or Docker's daemon settings. If a step seems to need any of those, **stop and ask the owner**.

The memory budget is hard: every container has a cap (`compose.beta.yaml`, 7230 MiB = 7.06 GiB
resident in all with the two trail routers, 7486 MiB = 7.31 GiB at the startup peak, against the host's 8.6 GiB available), so a spike restarts a
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
7. Start every command block with `. "$HOME/routemaker-beta-state/vars.sh"` (section 0): each tool
   call is a fresh shell, so the variables and `rm_absent` would otherwise be gone, and some lines
   (`[ "$TLS_OPTION" = A ] && ...`, `cd "$RM_SRC"`) would silently do nothing. Append each later
   decision to that file; never a secret.

## 0. Variables

**Every tool call is a fresh shell.** The working directory survives between your commands, but
exported variables and shell functions do not. So this section writes them once to a private file,
`$HOME/routemaker-beta-state/vars.sh` (directory 700, file 600), and **every block below starts by
sourcing it**. When a later step decides something (the api port, the nginx paths and user, the TLS
option, the checker's python), it appends that `export` line to the file. The file holds paths, the
sha, the port and those choices only: **never a password, key or token, and no value from `.env`**.
In a later session (an update, a rollback) the file is already there: source it, do not rerun this.

Fill in each `<...>` as you write it (nothing else is read from your environment):

```sh
export RM_STATE="$HOME/routemaker-beta-state"
# The guard every creating step uses: true only if NONE of the paths exists yet, naming each that
# does; an empty argument (an unset variable) also fails it. Every command that creates a RouteMaker path is written `rm_absent <paths> && <command>`
# on one line, so an existing path stops that command (a `for` loop's status alone would not).
rm_absent() { ok=1; [ "$#" -gt 0 ] || ok=0; for p in "$@"; do if [ -z "$p" ]; then echo "EMPTY path (an unset variable?): stop and ask the owner" >&2; ok=0; elif [ -e "$p" ] || [ -L "$p" ]; then echo "EXISTS: $p: stop and ask the owner" >&2; ok=0; fi; done; [ "$ok" = 1 ]; }
rm_absent "$RM_STATE" && mkdir -m 700 "$RM_STATE"
( umask 077; set -C; cat > "${RM_STATE:?}/vars.sh" ) <<'VARS' && declare -f rm_absent >> "$RM_STATE/vars.sh"   # set -C: never overwrites; the function is added only after a fresh write
export RM_STATE="$HOME/routemaker-beta-state"
export RM_SHA=<the 40-character git sha the owner gave you (the bundle's MANIFEST.txt git_sha= matches it)>
export RM_REPO_URL=<the repository URL the owner gave you>
export RM_DATA=/data/routemaker
export RM_SRC=/data/routemaker-src
export RM_INCOMING=/data/routemaker-incoming
export RM_SSH_HOST=<the ssh host the owner ships from, as the owner names this server in ~/.ssh/config>
export BETA_API_PORT=8087
VARS
grep -n '<[^>]*>' "$RM_STATE/vars.sh" && echo "STOP: fill in the <...> on those lines first" || { . "$RM_STATE/vars.sh"; ls -l "$RM_STATE/vars.sh"; }   # -rw------- ; then check its exports: grep '^export' "$RM_STATE/vars.sh"
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
- `beta.example.org` resolves to this server's own public address (checked live below; the
  address is not written down here).

```sh
. "$HOME/routemaker-beta-state/vars.sh"
free -m                                  # "available" must be at least 8510 MiB: the 7486 MiB startup peak plus the checker's 1 GiB margin (the caps total 7230 MiB = 7.06 GiB resident)
uname -m; docker info -f '{{.Architecture}}'   # both x86_64: the api image is built at home on x86_64; anything else is a stop
df -h /data /                            # /data: at least 25 GB free (bundle 4 GB, installed copy 4 GB, backups)
findmnt -no SOURCE,FSTYPE,OPTIONS /data  # a filesystem of its own; nofail in the options is expected (see "Reboot and a late /data")
stat -c '%A %U:%G' /data                 # read-only: needs x for others (or for nginx's group): nginx must pass through /data. If not, STOP and ask the owner; never change /data's mode
docker info -f '{{.DockerRootDir}}'      # where images and logs go; often /var/lib/docker on the root disk
df -h "$(docker info -f '{{.DockerRootDir}}')"   # at least 6 GB free for the images (about 3.7 GB) and the containers' logs (capped at 50 MB each)
systemctl is-enabled docker containerd   # both "enabled", or nothing comes back after a reboot (read-only; change nothing)
id -nG | tr ' ' '\n' | grep -x docker    # you must be in the docker group (or use sudo for every docker command)
docker version --format '{{.Server.Version}} API {{.Server.APIVersion}}'   # Docker 23 or newer (API 1.42+, which has BindOptions.CreateMountpoint); 29 is what the owner found. Step 8 proves the binds
v=$(docker compose version --short); v=${v#v}; if printf '%s\n' "$v" | grep -Eq '^[0-9]+[.][0-9]+'; then [ "$(printf '%s\n' 2.40.0 "$v" | sort -V | head -n 1)" = 2.40.0 ] && echo "compose $v: at least 2.40.0" || echo "STOP: compose $v is older than 2.40.0"; else echo "STOP: unreadable compose version '$v'"; fi   # the minimum this runbook supports; step 8 proves the binds on this host
ss -ltn | awk '{print $4}' | grep -E ":($BETA_API_PORT)\$" || echo "port $BETA_API_PORT is free"
nginx -v; sudo nginx -T 2>/dev/null | grep -E '^\s*(include|user) ' | head   # which directory does nginx include? which user?
command -v git rsync openssl curl python3 sha256sum
sudo docker compose version                      # the compose plugin must also work under sudo (receive-data.sh files/db run with sudo)
python3 -c 'import yaml' && echo "pyyaml ok"      # the pre-flight checker needs it; if missing, see below (no system package is installed)
dns=$(getent ahostsv4 beta.example.org | awk 'NR == 1 {print $1}'); me=$(curl -s -m 10 https://api.ipify.org)
[ -n "$dns" ] && [ -n "$me" ] && [ "$dns" = "$me" ] && echo "DNS points here" || echo "STOP: beta.example.org does not resolve to this server's public address (or the check could not run)"
sudo nginx -T 2>/dev/null | grep -c 'listen \[::\]'   # 0: the other sites do not listen on IPv6; render with --no-ipv6 in 9c
rm_absent "$RM_SRC" "$RM_INCOMING" "$RM_DATA" "$HOME/routemaker-beta-passwords.txt" "$HOME/routemaker-beta-venv" /var/www/routemaker-acme /etc/nginx/routemaker-beta.htpasswd && echo "all absent"   # any EXISTS line is a stop
```

If `import yaml` failed, give the checker a private virtualenv rather than a system package (the
runbook does not change the host's packages; if `python3 -m venv` itself is missing, ask the owner):

```sh
. "$HOME/routemaker-beta-state/vars.sh"
rm_absent "$HOME/routemaker-beta-venv" && python3 -m venv "$HOME/routemaker-beta-venv" && "$HOME/routemaker-beta-venv/bin/pip" install --quiet pyyaml
echo 'export RM_PY="$HOME/routemaker-beta-venv/bin/python"' >> "$RM_STATE/vars.sh"   # step 4 runs the checker with "${RM_PY:-python3}"
```

**TLS discovery (read-only, OWNER-DECISIONS 367.1).** Find out which certificates exist and which
server blocks use them, without changing anything:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
command -v certbot && sudo certbot certificates     # names, domains, expiry, paths; certbot renews these itself
sudo nginx -T 2>/dev/null | awk '/server_name/{n=$0} /ssl_certificate /{print n" -> "$2}' | sort -u   # which site uses which certificate
for c in $(sudo nginx -T 2>/dev/null | awk '/ssl_certificate /{print $2}' | tr -d ';' | sort -u); do
  echo "== $c"; sudo openssl x509 -in "$c" -noout -subject -enddate -ext subjectAltName
done
```

Then apply this rule, and report which option it gave and why:

- **Option B (reuse)** if some certificate's subjectAltName contains `beta.example.org` or
  `*.example.org`, **and** its `notAfter` is more than 14 days away, **and** it renews automatically
  (it is listed by `certbot certificates`, or the owner confirms how it is renewed).
- **Option A (a new certificate for this one name)** otherwise: `certbot certonly --webroot` for
  `beta.example.org` only (step 9b).

Record the choice for step 9c, which branches on it, in the vars file:
`echo 'export TLS_OPTION=A' >> "$RM_STATE/vars.sh"` or `echo 'export TLS_OPTION=B' >> "$RM_STATE/vars.sh"`.

Neither option changes another site's TLS. Do not use certbot's `--nginx` authenticator or
installer: it edits and reloads the host's nginx configuration at issue time and again at every
renewal.

Decide and note down:

- **The api port.** `8087` unless `ss` shows it taken; then pick a free one and append
  `export BETA_API_PORT=<it>` to `$RM_STATE/vars.sh` (a later line wins); the commands below use it (`--api-port` in steps 3 and 9c, the local curls). Only `127.0.0.1` is
  ever bound.
- **nginx's worker user.** The `user` line `nginx -T` printed (`www-data` on Ubuntu):
  append `export NGINX_USER=<that user>` to `$RM_STATE/vars.sh`. Step 8 checks with it that nginx
  can read what it serves.
- **Where nginx reads site files from.** On Ubuntu this is normally `/etc/nginx/sites-enabled/*`
  (files live in `sites-available/`, linked) or `/etc/nginx/conf.d/*.conf`. Use whichever the
  `include` lines above show and whichever the other sites already use. `$NGINX_SITE` below is the
  full path of the one file you will add, and `$NGINX_LINK` the `sites-enabled` link to it if that
  is the host's pattern (otherwise set `NGINX_LINK="$NGINX_SITE"`, and no link is made), for example
  `export NGINX_SITE=/etc/nginx/sites-available/routemaker-beta.conf NGINX_LINK=/etc/nginx/sites-enabled/routemaker-beta.conf`.
  Append that `export NGINX_SITE=... NGINX_LINK=...` line to `$RM_STATE/vars.sh`.
  Then `rm_absent "$NGINX_SITE" "$NGINX_LINK" && echo "site file absent"`; an EXISTS line is a stop.
- **Whether `beta.example.org` already points here.** If `getent` shows another address, stop;
  the owner has to change DNS first.

Never run anything under `scripts/boot/`, nor `scripts/local-up.sh`, and do not follow
`docs/DEPLOYMENT.md`'s boot section, on this server: they are for the home machine (Docker Desktop
on WSL); `local-up.sh` also refuses a `.env` whose project is not `routemaker`. `start-stack.sh` runs the base
compose file without the overlay and exports `RESTART_POLICY=no`, which here would start caddy and
the rebuild uncapped and stop the stack coming back after a reboot. Docker restarts the beta itself.

Record the "before" state so you can prove nothing else changed. `nginx -T` prints every site's
configuration, so the copies go in a private directory (mode 700, files 600), not in `/tmp`:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
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
. "$HOME/routemaker-beta-state/vars.sh"
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
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/make-env.sh --host <the beta's name> --data-root "$RM_DATA" --api-port "$BETA_API_PORT"   # TAG defaults to the first 12 characters of the sha
```

It generates `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY` and `PGPASSWORD` as random hex and prints
no secret. It refuses to overwrite an existing `.env`: a new `PGPASSWORD` would no longer match the
database initialised with the old one. The required values and what is optional:

| Variable | Required | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY`, `PGPASSWORD` | yes | generated by `make-env.sh` |
| `RM_BETA_HOST`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | yes | from `--host`: the name, the name, `https://` the name |
| `DATA_ROOT`, `TAG`, `COMPOSE_PROJECT_NAME` | yes | `/data/routemaker`, the short sha, `routemaker-beta` |
| `BETA_API_PORT`, `BETA_WEB_CONCURRENCY` | yes | `8087`, `6` (two route plans at once, one worker always free; the checker refuses more) |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI` | **no** | Planning works signed out. Leave empty and there is no sign-in. To enable it the owner adds `https://beta.example.org/auth/callback` to the Discord application and gives you the id and secret; edit `.env`, rerun the gate (`"${RM_PY:-python3}" scripts/check_beta_compose.py --env-file .env`, which must print "beta compose: ok"), then `beta-compose.sh up -d api`. From v0.7.0 sign-in is on by itself once both keys are set (the Settings line "Sign in with Discord to save routes and sync settings across devices." appears); migration 0020 adds saved settings and routes. Ride links keep anonymous rider dots in the api container's `/dev/shm` (a tmpfs, memory only), so the api needs no volume for them. |
| `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` | no | The beta's database carries **no accounts** (the dump strips them, OWNER-DECISIONS 367.3), so the owner claims instance admin afresh. Set this to the owner's Discord user id only if Discord sign-in is turned on, and have the owner sign in once promptly after the api starts. Otherwise leave it empty. |
| `WMATA_API_KEY`, `MAPILLARY_ACCESS_TOKEN` | no | v0.7.0 live data. The owner pastes them into `.env` himself (nobody else reads or types them); then `beta-compose.sh up -d api`. Empty: timetable times only, no street photo. Allow outbound `api.wmata.com`, `graph.mapillary.com` and `*.fbcdn.net` from the api: the server fetches the photo's file from Mapillary's image host and serves the browser its own copy, so the CSP's `img-src` stays `'self'` and the browser never contacts Mapillary. Check: a Metro station's card says "live" and "Data: WMATA"; a road panel shows "Photo from <month year>" or "No street photo here." |
| `DC311_API_KEY` | no | v0.7.0 Ride mode's 311 sent from the server (`core/dc311.py`), read by the api. The owner pastes it himself, only once DC issues one; then `beta-compose.sh up -d api`. Empty: Ride mode opens the phone's text app to 311 instead. Allow outbound `app.311.dc.gov` from the api. Each send needs a 15-minute ticket from `GET /api/report311`, and at most 60 reports an hour leave the server in all. |
| `NPS_API_KEY` | no | v0.7.0 National Park Service closure alerts, read by the **worker** (`refresh_dc_closures`). The owner pastes it himself; then `beta-compose.sh up -d worker`. Empty: the NPS feed is skipped, the DC feeds still run. Allow outbound `developer.nps.gov` from the worker, beside the DC closure hosts below. |
| `SUGGEST_SIGNED_OUT_MIN_AGREE` | no | `1` (the default): every signed-out LTS suggestion shows in the review list. Raise it (e.g. `2`) once volume grows, so a road's signed-out sends show only when that many agree; then `beta-compose.sh up -d api`. |
| VDOT token | no | this release has no such variable; there is nothing to set |

Never `source .env`; compose reads it. Never print it. Do not add `$` to a value (compose expands it).

Outbound hosts the app reaches at runtime (v0.7.0; all TCP 443; the full server list, with the
CD agent's and the host's own, is kept outside this repository, with the owner):

- **api:** `gbfs.capitalbikeshare.com`, `gbfs.lyft.com` (bikeshare); `api.wmata.com` (with
  `WMATA_API_KEY`); `graph.mapillary.com` and `*.fbcdn.net` (with `MAPILLARY_ACCESS_TOKEN`: the
  server fetches the street photo's file and serves the browser its own copy); `app.311.dc.gov`
  (with `DC311_API_KEY`); the short map links a shared place is followed through
  (`core/share_links.py`): `maps.app.goo.gl`, `goo.gl`, `maps.apple`, `www.google.com`,
  `google.com`, `maps.google.com`, `consent.google.com`, `maps.apple.com`; `discord.com` only
  with Discord sign-in.
- **worker** (`refresh_dc_closures`, every 15 minutes): `maps2.dcgis.dc.gov`, `mpdc.dc.gov`,
  `trainingtrack.hsema.dc.gov`, and `developer.nps.gov` (with `NPS_API_KEY`); and
  (`refresh_work_zones`, every 5 minutes) `filter.ritis.org` (Maryland) and
  `data.511-atis-ttrip-prod.iteriscloud.com` (Virginia, with `SMARTERROADS_TOKEN`). It also reaches
  Photon and the Valhalla containers on the compose network, as the api does.

Undo: `rm .env` (only before the database exists; after, keep it).

## 4. Pre-flight check of the overlay (changes nothing)

```sh
. "$HOME/routemaker-beta-state/vars.sh"
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
7.1 GiB (the two trail routers always counted) and the startup peak (plus the largest one-shot) leaving 1 GiB of the host's 8.6; at most
six gunicorn workers with one left free beside the routing, geocoding and tile pools; Photon's heap
plus capped direct buffers inside its cap; the weekly rebuild paused; every long-running service
restarting `unless-stopped` and Django debug off; and in `.env`, no `COMPOSE_PROFILES` or
`COMPOSE_FILE`, no `RESTART_POLICY` other than empty or `unless-stopped`, and no `DJANGO_DEBUG`.

Rerun the gate after **every** edit to `.env`: `beta-compose.sh` refuses the worst lines itself,
but only the gate checks the whole render.

## 5. Prepare `DATA_ROOT` (adds `$RM_DATA`)

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
rm_absent "$RM_DATA" && sudo sh scripts/prepare_data_root.sh --env-file ./.env
```

`/data` itself already exists (step 1) and is not touched: no `install -d`, `chown` or `chmod` on
it, because it holds other people's data. The script creates `$RM_DATA` and its subdirectories owned by the right users (this is the repository's own
script; it chowns only directories under `DATA_ROOT`). Undo: `sudo rm -rf "$RM_DATA"` only if no
data has been installed yet or the owner agreed.

## 6. Build the api image and pull the third-party images (adds Docker images)

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/beta-compose.sh build api                 # the worker and migrate services use the same image
scripts/beta/beta-compose.sh pull postgis photon valhalla-standard
docker image ls | grep -E 'routemaker-api|postgis|photon-docker|valhalla'
```

The postgis image is pinned by digest in `compose.beta.yaml` (the build home runs, PostgreSQL 16.4, PostGIS 3.4.3):
a pull by digest fetches exactly that image and does **not** move the shared `postgis/postgis:16-3.4` tag that
another stack on the host may use. Check first which images other stacks run:
`docker ps --format '{{.Image}}' | grep -E 'postgis|photon|valhalla'`. The photon and valhalla tags are fixed
release versions (`2.4.0`, `3.9.1`); if another stack uses the same tag, the pull fetches the same release.

The build needs network access (pip) and a few minutes. Images land in Docker's storage,
Docker's root from step 1, which may be the root disk and not `/data` (the four images are about 3.7 GB).
**The build is not capped:** BuildKit runs inside the Docker daemon, outside every container
limit, and pip's install can take a core and several hundred MB for a few minutes on a host other
sites share. So either build only when the owner says the other sites are quiet, or (preferred)
have the owner build at home from the same sha and send the image, which needs no build here
(the release agent, "Continuous deployment" below, builds only after it has stopped the api and
worker, so its builds use their memory):

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
export RM_SHA=<the release sha>  RM_HOME_SRC=<a clean checkout of it, with frontend/node_modules installed (the beta worktree has one)>  RM_LIVE_DIR=<the live stack's checkout>
cd "$RM_HOME_SRC"
[ "$(git rev-parse HEAD)" = "$RM_SHA" ] && [ -z "$(git status --porcelain)" ] && [ -d frontend/node_modules ] && echo "clean at the release sha"   # --build-frontend builds offline from frontend/node_modules
git ls-remote origin | grep "$RM_SHA"                          # the server can clone it
ssh "$RM_SSH_HOST" 'id -nG; uname -m'                          # in the docker group; x86_64
T=$(git rev-parse --short=12 HEAD)                             # the TAG make-env.sh writes
docker build -f docker/api.Dockerfile -t "ghcr.io/macrophage87/routemaker-api:$T" .
docker save "ghcr.io/macrophage87/routemaker-api:$T" | gzip | ssh "$RM_SSH_HOST" 'gunzip | docker load'
ssh "$RM_SSH_HOST" "docker image ls ghcr.io/macrophage87/routemaker-api:$T"   # loaded
ssh "$RM_SSH_HOST" 'stat -c %U /data/routemaker-incoming; id -un'   # the same user twice
scripts/beta/ship-data.sh --live-dir "$RM_LIVE_DIR" --build-frontend  "$RM_SSH_HOST"  /data/routemaker-incoming
```

With the image loaded this way, skip step 6's `build` line and run only its `pull` line.
`ship-data.sh` does not carry the api image; after sending, it warns if the server has no image for
the checkout's sha and prints the two lines above to send it.
`frontend/node_modules` must be installed for Linux x64. In WSL with no Linux node, `npm ci` finds
Windows npm and installs Windows bindings, which `--build-frontend` refuses; install it in the pinned
node image instead (`scripts/beta/frontend-build.sh --print-image` names it), as the refusal shows.
`--build-frontend` runs the front-end tests and builds it with the beta notice; `ship-data.sh` stops if
neither it nor `--dist` is given. To add a "Report a problem" link to the notice (OWNER-DECISIONS 382,
for example a Discord invite once there is one), the owner adds `--report-url https://...`; without it
the notice says only to tell the person who gave you access. The link is built into the front end, so
repeat the same `--report-url` on every later ship that carries the front end (data updates and
releases included), or the next `files` installs a notice without it.

The bundle carries the transit ride types' schedule when it has been built at home
(`$DATA_ROOT/tiles/transit/transit-schedule.json`, docs/OPERATIONS.md, "Transit schedule"). Without it
`ship-data.sh` warns and leaves the `transit` part out, and the beta's transit plans say they are not
available. Build it before shipping, and ship it again (`--without` every other part) when it is
refreshed, at least every 45 days. Sending the agencies' timetables to our own server is not
redistribution; the file is never committed (docs/SOURCES.md).

It sends about 4 GB (see "What the bundle holds" below) and is resumable: if the connection drops the
owner reruns the same command. `SHA256SUMS` arrives last, so a half-sent bundle has none.

On the server:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env verify      # must print "bundle ok" and exit 0
sudo scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env files  # installs, switches `current`, re-verifies
```

`files` copies the four routing graphs under `tiles/<graph>/<build>/` and points `current` at the new
build (the old one is recorded as `previous` and kept), then elevation, base map, the Photon index, the
transit schedule (`tiles/transit/transit-schedule.json`, read by the transit ride types; docs/OPERATIONS.md,
"Transit schedule") and the front end. It installs only the files `SHA256SUMS` lists and only the builds `MANIFEST.txt`
names, so anything an earlier bundle left in `$RM_INCOMING` is skipped (and reported). If photon is
running and the bundle carries its index, `files` stops photon first and starts it again after.
It verifies every installed file's sha256 again. It refuses if `/data` lacks room.

Then the database, which needs postgis running first:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
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
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/beta-compose.sh up -d photon valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
scripts/beta/beta-compose.sh up -d api worker
scripts/beta/beta-compose.sh ps
scripts/beta/beta-compose.sh logs --tail 30 migrate        # "No migrations to apply" (the dump carries the migration history)
```

Migrations check, and Django's static files (the admin's CSS; nginx serves `$RM_DATA/static`). Both
run inside the running api container, under its cap (rule 2), not as a second api container:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/beta-compose.sh exec -T api ./manage.py migrate --check && echo "migrations current"
scripts/beta/beta-compose.sh exec -T api ./manage.py collectstatic --noinput
```

nginx's worker user (`$NGINX_USER`, from step 1) must be able to read what the site file serves;
read-only checks:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
for f in "$RM_DATA/frontend/index.html" "$RM_DATA/basemap/region.pmtiles" "$RM_SRC/deploy/beta/401.html" "$RM_SRC/deploy/beta/502.html"; do
  sudo -u "$NGINX_USER" test -r "$f" && echo "nginx can read $f" || echo "NOT READABLE by nginx: $f (stop and ask the owner)"
done
```

**Binds that refuse a missing source (the proof; this is the authority).** `compose.beta.yaml`
asks for every RouteMaker bind with `create_host_path: false`, and the checker reads that from the
files, but whether this host's Compose and engine honour it is proved here, read-only. Compose
passes a bind that may be created as a legacy `Binds` entry, and one that must not be created as a
`Mounts` entry, which the engine refuses when the source is missing:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
for c in $(docker ps -aq --filter label=com.docker.compose.project=routemaker-beta); do
  docker inspect -f '{{.Name}}{{range .HostConfig.Binds}} LEGACY-BIND={{.}}{{end}}{{range .HostConfig.Mounts}}{{if eq .Type "bind"}} mount={{.Source}}{{if .BindOptions}}{{if .BindOptions.CreateMountpoint}}(CREATES){{end}}{{end}}{{end}}{{end}}' "$c"
done   # every RouteMaker source must show as mount=...; any LEGACY-BIND= or (CREATES) is a STOP
```

Then the engine itself, once, in two legs, in one block (each tool call is a fresh shell, so
both legs need the image found in its first line). Each leg passes only on the engine's own error
text: an empty image name or a leftover path prints "probe did not run", never a pass. The first
leg is at create, on a path that does not exist; the second is at start, the late-/data case (an
existing container restarted while its source is missing): create on a directory that exists,
remove the directory, start.

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
img=$(docker inspect -f '{{.Config.Image}}' "$(scripts/beta/beta-compose.sh ps -aq postgis)" 2>/dev/null); out=""; id=""
[ -n "$img" ] && [ ! -e "${RM_STATE:?}/no-such-dir" ] && out=$(docker create --mount "type=bind,source=$RM_STATE/no-such-dir,target=/x" --entrypoint true "$img" 2>&1) || out=${out:-PROBE-NOT-RUN}
case $out in (*"bind source path does not exist"*) echo "PROOF OK (create): the engine refuses a missing source" ;; (PROBE-NOT-RUN) echo "STOP (create): the probe did not run (no postgis image, or $RM_STATE/no-such-dir exists)" ;; (*) if printf '%s' "$out" | grep -Eqx '[0-9a-f]{64}'; then echo "STOP (create): the engine made a container, $out: docker rm it, rmdir $RM_STATE/no-such-dir if present, report"; else echo "STOP (create): unexpected output, report it exactly: $out"; fi ;; esac
out=""; [ -n "$img" ] && rm_absent "$RM_STATE/probe-src" && mkdir "$RM_STATE/probe-src" && id=$(docker create --mount "type=bind,source=$RM_STATE/probe-src,target=/x" --entrypoint true "$img") && rmdir "$RM_STATE/probe-src" && out=$(docker start "$id" 2>&1) || out=${out:-PROBE-NOT-RUN}
case $out in (*"bind source path does not exist"* | *mount*"no such file or directory"*) if [ -e "$RM_STATE/probe-src" ]; then echo "STOP (start): the start failed, but the source came back"; else echo "PROOF OK (start): a restart with a missing source fails, and nothing was recreated"; fi ;; (PROBE-NOT-RUN) rmdir "$RM_STATE/probe-src" 2>/dev/null; echo "STOP (start): the probe did not run before the engine was asked; cleaned up, safe to retry" ;; (*) echo "STOP (start): the start did not fail as expected: $out" ;; esac
[ -z "$id" ] || docker rm "$id" >/dev/null
```

Both legs must print PROOF OK. At start the refusal may come from the daemon ("bind source path
does not exist") or from runc mounting into the container ("error mounting ... no such file or
directory"); either counts only if the directory did not come back, which is the deciding test.
"The probe did not run" is a STOP to look into and retry (nothing was proved either way). Any other
STOP: report the exact output to the owner, and remove what the probe made (`docker rm`, `rmdir`).
If a container id was printed, or the source came back, the engine creates missing sources and
the /data safeguard does not hold on this host.

Health and memory:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
curl -s -H 'Host: beta.example.org' "http://127.0.0.1:$BETA_API_PORT/healthz"   # ok
scripts/beta/smoke-test.sh --local                                              # route, search, reverse, stress tile; all PASS
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' | grep routemaker-beta
free -m
```

Every container should sit well under its cap (api about 0.5 GiB at six workers, photon about
1 GiB, each router under 0.7 GiB). Then measure the two-plans-at-once case once (OWNER-DECISIONS
367.2), and report the api's and photon's peaks against their 1450M and 1300M caps:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
for i in 1 2; do curl -s -o /dev/null -w "plan $i: %{http_code} in %{time_total}s\n" -H 'Host: beta.example.org' \
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
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
( umask 077; setsid nohup sh -c 'scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles ; echo "predraw exit $?"' < /dev/null > "${RM_STATE:?set RM_STATE (section 0)}/predraw.log" 2>&1 & )
tail -n 3 "$RM_STATE/predraw.log"   # repeat, a minute or so apart, until a "predraw exit N" line
docker top "$(scripts/beta/beta-compose.sh ps -q worker)" -eo pid,etime,args | grep '[p]redraw_stress_tiles' || echo "no predraw running"   # is it still drawing?
```

When the log ends in `predraw exit N`:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
tail -n 5 "$RM_STATE/predraw.log"   # exit 0, after a "stress tiles: N drawn, ..., in S s" line: done
docker inspect -f '{{.State.OOMKilled}} {{.RestartCount}}' $(scripts/beta/beta-compose.sh ps -q worker)   # false 0
```

Any exit but 0: read `tail -n 30` of the log and the inspect line, and report them. **Never start it
again while the log has no `predraw exit` line and the `docker top` line shows it running**: the
command that started it ending (or being killed) does not stop the draw inside the worker, so a
second one would draw beside it, inside the same cap and against the same postgis. If there is no
`predraw exit` line and `docker top` prints "no predraw running", the draw died without its last
line (the starting process was killed, or the worker restarted): read the log's tail, report it,
and only then start it once more. Expected time: the whole z10-14 box is 11,068
tiles, which took 155 s at home with one draw at a time; here postgis has 1.5 CPUs on a shared host,
so allow 5 to 15 minutes. It has a one-hour budget; if its "stress tiles:" line says it stopped
short with some left, start it once more (it draws only those). Do not invite testers (step 11) until it has
finished. If the worker was OOM-killed, report it with the numbers; do not raise its cap. This is
"the step 8 pre-draw" that the update and rollback paths below repeat.

Undo: `scripts/beta/beta-compose.sh down` (containers and network only; `$RM_DATA` is untouched).

## 9. nginx: add one file, in two stages (adds `$NGINX_SITE`, the htpasswd file, optionally a certificate)

Nothing public is served until stage 2. `render-nginx.sh` only prints or writes the file you name;
it never touches `/etc`.

### 9a. The password file

```sh
. "$HOME/routemaker-beta-state/vars.sh"
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
`beta.example.org` or `*.example.org`, is more than 14 days from expiry and renews
automatically; **A** otherwise. Say in your report which one, with the `openssl x509` lines that
decided it.

**Option A: certbot issues a certificate for `beta.example.org` only, by webroot.** Install
the stage-1 file, which answers only the ACME challenge on port 80, then run certbot's `--webroot`
authenticator. It writes the challenge into `/var/www/routemaker-acme` and touches no nginx file;
its renewals reuse the same `webroot_path`. Not `--nginx` (it edits and reloads the host's nginx
config at issue and at every renewal), and not the installer form (it would rewrite this site file).

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
rm_absent /var/www/routemaker-acme "$NGINX_SITE" "$NGINX_LINK" && sudo install -d /var/www/routemaker-acme
scripts/beta/render-nginx.sh --stage acme [--no-ipv6] --out "$RM_STATE/routemaker-beta.acme.conf"
rm_absent "$NGINX_SITE" "$NGINX_LINK" && sudo install -m 644 "$RM_STATE/routemaker-beta.acme.conf" "$NGINX_SITE" && { [ "$NGINX_LINK" = "$NGINX_SITE" ] || sudo ln -s "$NGINX_SITE" "$NGINX_LINK"; }
sudo nginx -t && sudo nginx -s reload
sudo certbot certonly --webroot -w /var/www/routemaker-acme -d beta.example.org
sudo ls /etc/letsencrypt/live/beta.example.org/        # fullchain.pem and privkey.pem
```

Certbot's existing renewal timer renews it; the port-80 ACME location stays in the final file for
that. Then continue to 9c with `--cert-fullchain /etc/letsencrypt/live/beta.example.org/fullchain.pem`
and `--cert-key /etc/letsencrypt/live/beta.example.org/privkey.pem`.

**Option B: reuse the certificate step 1 found.** Use its paths as they are, and skip stage 1.
For a certbot certificate, `sudo certbot certificates` gives them: its `Certificate Path` is
`--cert-fullchain` and its `Private Key Path` is `--cert-key`. For a certificate certbot does not
manage, use the `ssl_certificate` and `ssl_certificate_key` paths of the site that already uses it.
Do not run `certbot renew --force` or alter any existing certificate.

Whichever option, if the host's other sites include certbot's `options-ssl-nginx.conf`, add
`--tls-options-include /etc/letsencrypt/options-ssl-nginx.conf` in 9c to match them.

### 9c. The full site

First record the two certificate paths the chosen option gave, so 9c and the step 10 recovery use
exactly the same ones (paths only: the files are never read, printed or copied):
`echo 'export RM_CERT_FULLCHAIN=<fullchain path> RM_CERT_KEY=<private key path>' >> "$RM_STATE/vars.sh"`,
with the two paths filled in. After this and every other line appended to vars.sh, the file must
still pass the placeholder check (`grep -n '<[^>]*>' "$RM_STATE/vars.sh"` prints nothing); the
render lines below refuse to run while it does not.

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
{ ! grep -n '<[^>]*>' "$RM_STATE/vars.sh" || { echo "STOP: fill in the <...> on those vars.sh lines first"; false; }; } && scripts/beta/render-nginx.sh --stage full --api-port "$BETA_API_PORT" \
    --cert-fullchain "$RM_CERT_FULLCHAIN" --cert-key "$RM_CERT_KEY" [--tls-options-include <path>] [--no-ipv6] \
    --out "$RM_STATE/routemaker-beta.full.conf"
# exactly one of the next two lines acts, the one for the TLS_OPTION step 1 chose:
# option A: replace the stage-1 file, only if it is the one this runbook installed in 9b (its link already points at it)
[ "$TLS_OPTION" = A ] && grep -q 'Rendered by scripts/beta/render-nginx.sh (stage acme)' "$NGINX_SITE" && sudo install -m 644 "$RM_STATE/routemaker-beta.full.conf" "$NGINX_SITE"
# option B: stage 1 was skipped, so this is a new file and must not exist yet
[ "$TLS_OPTION" = B ] && rm_absent "$NGINX_SITE" "$NGINX_LINK" && sudo install -m 644 "$RM_STATE/routemaker-beta.full.conf" "$NGINX_SITE" && { [ "$NGINX_LINK" = "$NGINX_SITE" ] || sudo ln -s "$NGINX_SITE" "$NGINX_LINK"; }
sudo nginx -t && sudo nginx -s reload                                   # -t must say "syntax is ok" and "test is successful"
curl -s -m 10 -o /dev/null -w '%{http_code}\n' https://beta.example.org/   # must print 401 at once; 403 or 404: nginx cannot serve the sign-in page (step 10, "If the 401 lines fail"); 000: no answer (TLS, listen or DNS): take the site offline with rollback D and report
```

`--no-ipv6` drops the `listen [::]:80` and `listen [::]:443` lines: give it when step 1 found no
`listen [::]` in the other sites (an IPv6-disabled host makes `nginx -t` fail on them, safely).
The rendered file says at its top which template, stage and git sha it was rendered from.

If `nginx -t` complains about `http2 on`, the host's nginx is older than 1.25.1: edit the installed file,
delete the `http2 on;` line and write `listen 443 ssl http2;` and `listen [::]:443 ssl http2;`, then test again.

Prove nothing else changed:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
(umask 077; sudo nginx -T > "$RM_STATE/nginx-after.txt" 2>&1)
diff <(sed 's/[[:space:]]*$//' "$RM_STATE/nginx-before.txt") <(sed 's/[[:space:]]*$//' "$RM_STATE/nginx-after.txt") | grep '^<' | head   # no output: nothing was removed or edited
while read -r s; do printf '%s %s\n' "$s" "$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$s/" || echo fail)"; done < "$RM_STATE/sites-before.txt" | diff - "$RM_STATE/sites-before-status.txt" && echo "other sites unchanged"
```

Undo, whenever: `sudo rm "$NGINX_SITE"` (and the `sites-enabled` link if you made one), `sudo nginx -t && sudo nginx -s reload`,
then `sudo rm -f /var/log/nginx/rmbeta-access.log* /var/log/nginx/rmbeta-error.log* /etc/nginx/routemaker-beta.htpasswd`
(the two logs and the password file this step created). The site is then gone and the other sites never noticed.

What the site does, so you can explain it to the owner: only `robots.txt`, `/delete-account`
(Google Play's account-deletion page) and the port-80 ACME challenge path are public; everything else, including `/healthz`, `/auth/` and the admin path, asks for
a password. Every response carries `X-Robots-Tag: noindex, nofollow`. `/api` has 75-second timeouts
(a plan takes up to 47 seconds). JSON and vector tiles are gzipped. The base map answers only this
site's own pages.

## 10. Smoke test through nginx

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/smoke-test.sh --public https://beta.example.org --passwords-file ~/routemaker-beta-passwords.txt
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
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
{ ! grep -n '<[^>]*>' "$RM_STATE/vars.sh" || { echo "STOP: fill in the <...> on those vars.sh lines first"; false; }; } && scripts/beta/render-nginx.sh --stage full --api-port "$BETA_API_PORT" --no-401-page \
    --cert-fullchain "$RM_CERT_FULLCHAIN" --cert-key "$RM_CERT_KEY" [--tls-options-include <path>] [--no-ipv6] \
    --out "$RM_STATE/routemaker-beta.full-no401.conf"
grep -q 'Rendered by scripts/beta/render-nginx.sh (stage full)' "$NGINX_SITE" && sudo install -m 644 "$RM_STATE/routemaker-beta.full-no401.conf" "$NGINX_SITE"
sudo nginx -t && sudo nginx -s reload
```

Use the same options as in 9c, plus `--no-401-page`. Cancel then shows nginx's own plain
"401 Authorization Required" page; the sign-in box itself is unchanged. The flag also leaves out
the "Back soon" page (`deploy/beta/502.html`, read from the same directory), so a 502 shows nginx's
own page again. The same goes for a 403 or 404 where a 502 was expected (nginx cannot read
`deploy/beta/502.html`): the same re-render is the recovery. Rerun the smoke test with
`--no-401-page` too: it then skips (and says so) the one line about the sign-in page's text, and
every other line must PASS.

Then check by eye, once, in a browser the owner can use: the page loads behind the password prompt,
the map draws, a two-point route appears, and a small **Beta** chip is in the map's bottom-left
corner (beside the planner on a computer, above the sheet on a phone); pressing it opens the beta
note over the map (it appears only in the front end built with `VITE_BETA=1`, which
`ship-data.sh --build-frontend` does). And one screen-reader pass (VoiceOver or NVDA): the password
prompt is read and can be filled; the "Beta notice" button is reached by Tab after the map's
controls and says collapsed or expanded; opened, the "Beta notice" region is read next, and Escape
closes it with the focus on the button.

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
. "$HOME/routemaker-beta-state/vars.sh"
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
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/beta-compose.sh stop api worker
ls -l "$RM_DATA"/backups/pre-*.dump
sudo scripts/beta/receive-data.sh --env-file .env restore-dump "$RM_DATA/backups/pre-update-<time>.dump"
scripts/beta/beta-compose.sh up -d api worker
( umask 077; setsid nohup sh -c 'scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles ; echo "predraw exit $?"' < /dev/null > "${RM_STATE:?set RM_STATE (section 0)}/predraw.log" 2>&1 & )
tail -n 3 "$RM_STATE/predraw.log"   # the step 8 pre-draw: poll for "predraw exit N" as step 8 says
```

**C. Go back to the previous release:** the previous api image is still on the host under its own tag. Retagging
alone is not enough when the new release migrated the database forward: the old code would run against a
newer schema. So rollback C also puts back the `pre-release` snapshot taken just before the update
("Shipping an update later", new release, step 2), and the old front end's `index.html` saved in the
same step (the hashed assets it names are never deleted, so `index.html` alone brings back the old app):

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/beta-compose.sh stop api worker
git checkout --detach <previous sha>
sed -i 's/^TAG=.*/TAG=<previous 12-character sha>/' .env          # the one edit to .env a release change needs
"${RM_PY:-python3}" scripts/check_beta_compose.py --env-file .env    # the gate, after every .env edit: "beta compose: ok"
sudo scripts/beta/receive-data.sh --env-file .env restore-dump "$RM_DATA/backups/pre-release-<time>.dump"
sudo cp -p "$RM_DATA/backups/index.html.pre-release-<time>" "$RM_DATA/frontend/index.html.new" && sudo mv -T "$RM_DATA/frontend/index.html.new" "$RM_DATA/frontend/index.html"
scripts/beta/beta-compose.sh up -d api worker                     # recreates them on the old image; migrate finds nothing to do
scripts/beta/beta-compose.sh up -d photon valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend   # recreates only those whose image or command the release changed
scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend   # needed if the release changed valhalla/*.json or lua/: the routers read them only at start
( umask 077; setsid nohup sh -c 'scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles ; echo "predraw exit $?"' < /dev/null > "${RM_STATE:?set RM_STATE (section 0)}/predraw.log" 2>&1 & )
tail -n 3 "$RM_STATE/predraw.log"   # the step 8 pre-draw: poll for "predraw exit N" as step 8 says
```

If the release changed `deploy/beta` (its step 9), also put the old nginx site back (owner steps): render it from
this checkout, now at the previous sha, with the same command as step 9c of the install, `sudo install -m 644` it
over `$NGINX_SITE`, then `sudo nginx -t && sudo nginx -s reload`.

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
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
sudo rm -f "$NGINX_SITE"; sudo rm -f /etc/nginx/sites-enabled/routemaker-beta.conf     # whichever exist
sudo nginx -t && sudo nginx -s reload
sudo rm -f /etc/nginx/routemaker-beta.htpasswd
sudo rm -f /var/log/nginx/rmbeta-access.log* /var/log/nginx/rmbeta-error.log*   # the beta's own nginx logs, rotated copies too
scripts/beta/beta-compose.sh down
docker image rm ghcr.io/macrophage87/routemaker-api:<TAG>
# destructive, owner's say-so: the data and the checkout
sudo rm -rf /data/routemaker /data/routemaker-incoming /data/routemaker-src /var/www/routemaker-acme "$HOME/routemaker-beta-state"
# only if Option A created it and nothing else uses it:
sudo certbot delete --cert-name beta.example.org
```

## Shipping an update later

The tooling is the same each time. Ask the owner which kind it is.

If continuous deployment is installed (next section), pause it first so no pass starts while you
work, and let a pass that is already running end: `"$RM_STATE/cd/bin/auto-release.sh" pause --wait "shipping by hand"`
(plain `pause` does not stop a running pass; it says if one is running). Then check
`... status` before touching anything. If it (or `pause`) shows `IN PROGRESS`, a stopped pass left a
deploy half done: the api and worker may be stopped and the checkout part-way to the new tag, and a
paused agent does not roll it back. `pause` says whether it is safe to work by hand, and its
verdict decides. If it says it is not yet safe, do not ship. Either let one pass roll the deploy
back, with the three commands back to back so the timer cannot start another pass in between
(`... resume; ... run; ... pause --wait "shipping by hand"`), then check `... status` again; or put
it right by hand and record what is running with `... mark-deployed --force vX.Y.Z`. Otherwise a later
pass would roll your work back (with a database restore from its snapshot if it had migrated).
When you are done, tell it what is running (`... mark-deployed vX.Y.Z` for a release, nothing for
data only), then `... resume`. `mark-deployed` also reads the report link from `$RM_DATA/frontend/beta-build.txt`,
so if that ship used another `--report-url`, the agent's next front-end build keeps it (check with
`... status`, or set it with `... set-report-url URL|none`).

**Once, on the first update to v0.7.0** (owner and server steps, in this order):

1. Add `RM_BETA_HOST=<the beta's name>` to `$RM_SRC/.env`. The name is no longer in the
   repository: without the line `render-nginx.sh`, `smoke-test.sh --local` and the deploy agent stop
   with a message naming `RM_BETA_HOST`.
2. The release changes compose `image:` lines (each third-party image now carries its digest) and
   the nginx template, so the deploy gate stops it: ship it by hand as below, then re-render nginx
   (step 9 of "A new release sha" below), which adds the error-log rule for the newer place-bearing api paths.
3. Sign everyone out once, after the api is up (backups no longer carry Django's session
   table; sessions written before were in the old dumps):
   `scripts/beta/beta-compose.sh exec -T api ./manage.py shell -c "from django.contrib.sessions.models import Session; Session.objects.all().delete()"`.
4. Tighten what is already on disk (new files get these modes by themselves):
   `chmod 700 "$RM_DATA/backups"` and `chmod 600 "$RM_DATA"/backups/*` (with sudo where root owns them).
5. The v0.7.0 data bundle was built on the cloud box at commit `4f34f76d`, not the release's, so its
   data update takes `--allow-sha-mismatch`:
   `scripts/cloud/import-result.sh --beta --allow-sha-mismatch [--swap] "$RUN_URL"`, which passes it to
   `receive-data.sh` (run by hand, `receive-data.sh --bundle "$RM_INCOMING" --env-file .env
   --allow-sha-mismatch verify`, and the same for `files` and `db`). At home, that run's
   `import-result.sh` takes the same flag (OPERATIONS.md, "Rebuilding on the cloud box").

**New data only** (a fresh build of the tiles, database or Photon index, same release):

A rebuild run on the cloud box with `--beta-bundle` brings the tiles and database by S3
instead of step 1: `scripts/cloud/import-result.sh --beta "$RUN_URL"`, then `--beta --swap`,
which runs steps 2 to 5 below except `smoke-test.sh --public`, which you run once the
pre-draw has finished (OPERATIONS.md, "The beta server from the same run"). Pause
continuous deployment first, as above, and resume it after.

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
   the beta. The junction overrides (`junction_override`, approved junction suggestions) and the Avoid
   junctions (`avoid_junction`) are reset to home's the same way, and the beta's own half-step edit history
   (`stress_edit`, which points at the overrides it replaces) is emptied. The beta's own rider suggestions, road
   and junction, are kept; an approved one loses only its link to the edit, rating or Avoid junction it made.
   Stop the api and worker first so nothing writes during it:

   ```sh
   . "$HOME/routemaker-beta-state/vars.sh"
   cd "$RM_SRC"
   scripts/beta/beta-compose.sh stop api worker
   sudo scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env db --update-data
   scripts/beta/beta-compose.sh up -d api worker
   ( umask 077; setsid nohup sh -c 'scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles ; echo "predraw exit $?"' < /dev/null > "${RM_STATE:?set RM_STATE (section 0)}/predraw.log" 2>&1 & )
   tail -n 3 "$RM_STATE/predraw.log"   # the step 8 pre-draw: poll for "predraw exit N" as step 8 says
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
   . "$HOME/routemaker-beta-state/vars.sh"
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
   exactly the ones that did). The four routers also need a restart if `valhalla/*.json` or `lua/` changed, because
   they read those files only at start and `up -d` sees nothing to recreate:
   `scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`
   (the same line as rollback A), with `valhalla-offroad valhalla-mtb` added once their tiles are on the host.
   Check with `git diff --stat <old sha>..<new sha> -- valhalla lua`.
9. **Only if `git diff --stat <old sha>..<new sha> -- deploy/beta` lists the nginx template** (owner steps, because
   they use sudo): re-render it with the same command and flags as step 9c of the install into `$RM_STATE`, install it
   over the site file (`sudo install -m 644 "$RM_STATE/routemaker-beta.full.conf" "$NGINX_SITE"`), then
   `sudo nginx -t && sudo nginx -s reload`, and run the 401 `curl` check from step 9c. Without this the beta keeps
   the old log settings, and any other template change, until it is next installed.
10. The front end comes in the bundle (`frontend/`), so `files` installs it; the new `index.html` goes in last.

**Front end only:** ship with `ship-data.sh --live-dir "$RM_LIVE_DIR" --build-frontend [--report-url <the same as before>]
--without tiles --without elevation --without basemap --without photon --without db "$RM_SSH_HOST" /data/routemaker-incoming`,
then save the old `index.html` and run `sudo ... files`. `files` replaces `frontend/index.html` without keeping the old one, so
save it first, as the full release path does:

```
sudo cp -p "$RM_DATA/frontend/index.html" "$RM_DATA/backups/index.html.pre-frontend-<time>"   # then: sudo ... files
```

Nothing restarts; `index.html` is read per request. **Undo** (the old hashed assets are still on disk, so this brings the old
app back): `sudo cp -p "$RM_DATA/backups/index.html.pre-frontend-<time>" "$RM_DATA/frontend/index.html.new" && sudo mv -T "$RM_DATA/frontend/index.html.new" "$RM_DATA/frontend/index.html"`.

Once the front end has the installable app's service worker (`sw.js`), save it beside `index.html` the same way
(`sudo cp -p "$RM_DATA/frontend/sw.js" "$RM_DATA/backups/sw.js.pre-frontend-<time>"`) and put it back with the same
`cp` and `mv -T` in an undo, so the worker and the page stay the same build (OPERATIONS.md, "The app's service worker:
updates, rollback and the kill switch", which also has the kill switch). **An undo to a build from before the worker**
has no saved `sw.js`, and neither this undo nor the agent's own restore removes the new one: after it, copy the kill
switch over it (`sudo cp -p "$RM_DATA/frontend/sw-kill.js" "$RM_DATA/frontend/.sw.js.new" && sudo mv -T "$RM_DATA/frontend/.sw.js.new" "$RM_DATA/frontend/sw.js"`),
which also reloads any page mid-ride (OPERATIONS.md, same section). The installable app's edge changes, in this
template and the Caddyfile, are OPERATIONS.md, "The installable app at the edge".

## Continuous deployment

OWNER-DECISIONS 431: the beta server checks GitHub for a new release tag itself and ships it with
"A new release sha" above, without sudo. Nothing is pushed into the server, and no SSH key, token or
server detail goes into GitHub or the repository: the agent reads the public repository, and the
server's user, paths and `RM_SSH_HOST` stay in `vars.sh` here. The local live stack at home is not
part of it.

**How a release flows.** The change is reviewed and merged to `main`; CI's `test` check goes green on
that commit; the owner says go; the owner (and only the owner, or someone on the owner's word)
pushes an **annotated** tag on that commit. Before the tag, at home, on that commit (a tag goes
live within about 10 minutes, and nothing after it checks what a screen reader hears):

- If `frontend/` changed since the deployed tag, run the browser accessibility check,
  `scripts/a11y/run.sh <a node_modules for that lockfile>` (offline; docs/DEVELOPMENT.md), and it
  must pass. CI and the agent run only `npm test`.
- If the release changes anything `docs/BETA-TESTER-HANDOUT.md` describes (the skip link, the
  landmarks, the headings, the beta notice and its Beta chip), update the handout in
  the same release and send it to the testers again once the release is deployed.
- The release that brings this agent (wip/beta-cd) also adds a paragraph about updates to the
  handout's section 8 (what testers hear during a deploy, and how long to wait): resend the
  handout to the testers once it is deployed, adding the update hours if `RM_CD_WINDOW` is set
  (the sender's notes at its top say how).

- The tagged commit carries the release's version in `pyproject.toml` (`version`) and
  `src/routemaker/__init__.py` (`__version__`): bump both in the release's last commit
  (tests/test_deploy_docs.py checks that they agree).

```sh
# at home, on the owner's go:
git tag -a v0.2.0 -m "RouteMaker 0.2.0" <the main commit>
git push origin v0.2.0
# about 15 minutes later, what the server made of it (deployed, waiting, held or failed):
ssh "$RM_SSH_HOST" '"$HOME/routemaker-beta-state/cd/bin/auto-release.sh" status'
```

Within about 10 minutes a pass on the server sees it and either deploys it or stops and says why.
A tag is never moved or reused: a fix is the next patch number. The agent's script is
`scripts/beta/auto-release.sh`; its decisions are in `scripts/beta/cd_logic.py` (tested in
`tests/test_beta_cd.py`).

### What one pass does

1. Nothing at all if the agent is paused, BROKEN (a rollback failed earlier), another pass is
   still running (`flock`), or a setting makes no sense (`RM_CD_WINDOW` not `HH-HH`, or with the
   same hour twice: an `error` in `status`). If a pass was stopped mid-deploy (it left
   `$RM_STATE/cd/in-progress`, step 7), this pass first rolls that deploy back, if it had touched
   the stack (if not, it drops the record and goes on); while paused, not even that. A pass that would
   deploy also waits while a stress-tile pre-draw runs, outside the deploy window if one is set,
   with less than 1 GiB free for the snapshot, or with less than `RM_CD_DOCKER_FREE_GIB` (3 GiB)
   free on Docker's root.
2. Checks that the checkout is clean, at the deployed tag's commit, with that commit's `TAG` in
   `.env`. Anything else ("drift") means someone shipped or edited by hand: it stops until
   `mark-deployed` says what is running. The checkout's `origin` must be
   `https://github.com/<RM_CD_GITHUB_REPO>` (`.git` or not), the repository whose CI it reads.
3. `git fetch --tags`, then the highest strict `vX.Y.Z` tag (no `-rc`, no leading zeros) newer than
   the deployed one. Only the highest: if it cannot go, the agent waits for the owner rather than
   deploying an older one.
4. The tag must be annotated (`git tag -a`), its commit on `origin/main` and descended from the
   deployed release, and GitHub's `test` check run (by GitHub Actions, on exactly that commit, the
   newest run) green. The check is an unauthenticated read of the public API, a few calls an hour at
   most; a rate limit or a network failure is tried again next pass. Signed tags: the repository has
   none today; setting `RM_CD_REQUIRE_SIGNED_TAGS=1` makes `git verify-tag` a requirement too (the
   server then needs the signer's public key in its keyring).
5. The gate, over `git diff <deployed>..<new>` (only a code release deploys by itself):

| A change to | Means | What the agent does |
| --- | --- | --- |
| docs, reports, `*.md`, `.github/`, fixtures | nothing on the server | ignored |
| `src/` (not the items below), `frontend/`, `scripts/` | a code release | deploys |
| `src/*/migrations/` | a migration | deploys; migrate runs after the pre-release snapshot |
| `valhalla/*.json`, only keys a router reads at start (`logging`, `loki`, `thor`, `service_limits`, `httpd`, `odin`, `meili`, `statsd`, mjolnir's cache keys) | a router setting | deploys, then restarts the routers: the four, and valhalla-offroad and valhalla-mtb once their tiles (`$RM_DATA/tiles/<variant>/current`) are on the host |
| compose files, other than the lines below | a stack setting | deploys if the compose gate passes, then `up -d` photon and the routers (recreates only those whose settings changed) |
| `deploy/` (the nginx template, the 401 and 502 pages, the env template) | owner steps with sudo | **stops** |
| `scripts/prepare_data_root.sh`, a compose line adding a `DATA_ROOT` path | a data directory with sudo | **stops** |
| a compose `image:` line | a third-party image to pull, maybe a data mismatch | **stops** |
| `docker/api.Dockerfile`, `docker/requirements*.txt`, `docker/api-entrypoint.sh` | a new base image, system package or dependency in the api image | **stops** |
| `lua/`, `valhalla/vendor/`, any other `valhalla/*.json` key (graph build), `src/pipeline/schema.py`, `variants.py`, `tiles.py` | new data from home | **stops** |
| `FORMAT_VERSION` in `src/core/stress_tiles.py` or `src/core/mass_tiles.py` | a new tile format (the cache is keyed on it; no data from home) | deploys, then the agent runs the step 8 pre-draw (`predraw_stress_tiles`, which draws both tile sets) and waits for it. The release is already live and smoke-tested by then, so a pre-draw that fails or runs out of its budget is a warning in the report, not a rollback: the tiles not yet drawn are drawn on request |
| a migration that names the live schema, or a migration removed | data from home | **stops** |
| a file name with a space, a quote, a backslash, or a control or non-ASCII character | a path the gate cannot be sure of | **stops** (check it by hand) |

   A release whose only changes are ignored ones (documentation, CI), or a new tag on the deployed
   commit, is recorded as deployed without touching the stack, if the running api image
   (`ghcr.io/macrophage87/routemaker-api:<the deployed TAG>`) is on the host (if not, it is a full
   deploy): the checkout and `TAG` move and the running api image is tagged with the new `TAG`.

   A stop writes its reasons to `$RM_STATE/cd/hold/<tag>` and the agent does nothing else for that
   tag. Ship it by hand ("Shipping an update later", with `pause` first), then `mark-deployed <tag>`.
6. The deploy. First, with nothing running touched, a `git archive` of the tag into
   `$RM_STATE/cd/build`. Then the runbook's steps: stop the api and worker; build the api image
   (`docker build` of that tree, tried 3 times a minute apart, since pip needs the network; skipped
   if `ghcr.io/macrophage87/routemaker-api:<TAG>` is already on the host because the owner loaded it
   from home) and, if `frontend/` changed, the front end. The builds come after the stop on
   purpose: the api build is not capped (BuildKit runs in the daemon), so it uses the memory the api
   and worker had instead of the other sites' headroom, and the front-end build runs with
   `--memory 1536m` and `--oom-score-adj 1000`, so a host short of memory kills it first. The cost
   is downtime: roughly 10-20 minutes per release (the api build, up to 3 tries; the front-end
   test and build; the snapshot; `/healthz` and the smoke tests), longer when a build fails before
   the rollback, and much less when the owner has loaded the api image from home. During it nginx
   still serves the page, so testers see it open, but planning a route says "Router unavailable",
   place search and the road information say they are "not available right now", and Sign in
   shows the "Back soon" page (`deploy/beta/502.html`; nginx's bare "502 Bad Gateway" on a site
   file rendered before that page existed, or with `--no-401-page`). The handout's section 8 tells
   testers to wait about 20 minutes. Set `RM_CD_WINDOW` to quiet hours. Then: snapshot the
   database (`receive-data.sh --backups-dir "$RM_STATE/cd/backups" snapshot-db`:
   `pg_dump` through `beta-compose.sh exec -T postgis`, into a directory of the user's own, so no
   sudo); save the front end's top-level files (`index.html`, `beta-build.txt`) there; `git checkout --detach` the tag; `TAG=` in `.env` by `sed`; the
   compose gate (`check_beta_compose.py --env-file .env`); migrate in the migrate container, only if
   `migrate --check` says something is pending; install the front end (hashed files first, `index.html`
   last by rename, as the uid that owns `$RM_DATA/frontend`'s files, in the postgis image already on
   the host, no network); `up -d api worker`; photon and the routers if the gate said so; `/healthz`;
   `migrate --check` and `collectstatic` in the api; `smoke-test.sh --local` (retried once after a
   minute). The release is then recorded as deployed (`$RM_STATE/cd/deployed-tag`). If the gate saw a tile `FORMAT_VERSION` change (`core.stress_tiles` or `core.mass_tiles`), the
   step 8 pre-draw (`predraw_stress_tiles`, both tile sets) then runs and the pass waits for it (log:
   `$RM_STATE/predraw.log`); the release is already live by then, so a pre-draw that fails or runs out
   of its budget is a WARNING in the report and not a rollback. Every log line is a step name, a commit id or a PASS/FAIL line; `.env` is never printed.
7. **Any failure after the stop rolls back by itself** (rollback A/C as above, without sudo): stop the
   api and worker, check out the previous release, `TAG` back, the compose gate; the database from
   the pre-release snapshot **only if a migration ran** (`restore-dump`, which keeps the database as
   it was beside it as `routemaker_before_<time>` for the owner to drop); `index.html` and `beta-build.txt` back only if
   the new front end was installed; start the api and worker; the routers again if they were
   restarted; the step 8 pre-draw after a database restore (a failure there is a warning); the smoke tests. The tag is then marked
   failed (`$RM_STATE/cd/failed/<tag>`) and not tried again until `retry <tag>`. A failure before the
   stop (exporting the tag's tree) changes nothing and marks the tag failed the same way. If the rollback itself fails,
   the agent marks itself BROKEN, stops making passes, and waits for the owner.

   **A pass stopped mid-deploy.** Each step is written to `$RM_STATE/cd/in-progress` before it
   runs. If the pass is stopped (systemd's `TimeoutStartSec`, a reboot, `systemctl --user stop`, a
   logout without linger, a kill), the next pass rolls that deploy back from the steps written there,
   if it had touched the stack, and marks the tag failed (`retry <tag>` to try it again); if that
   rollback fails, BROKEN. A pass stopped before the stop (while exporting the tree) touched nothing:
   the next pass drops the record and carries on. A pass stopped during the pre-draw has already
   recorded the release, so nothing is rolled back. While the agent is paused nothing rolls it back:
   `status` and `pause` say so (`IN PROGRESS`), and `mark-deployed` refuses to drop that record
   without `--force` ("Shipping an update later"). Do not stop a pass mid-deploy on purpose:
   `pause --wait` and let it end. Without linger, a logout can stop one; the crontab line below does
   not depend on a login. Stopping a pass kills the docker CLI, not a container the daemon already
   runs: a `migrate` one-off can go on running for a while (`scripts/beta/beta-compose.sh ps -a` in `$RM_SRC` shows it).
   A reboot stops it; otherwise let it finish before a pass rolls back, since a restore with the
   migration still connected fails and leaves the agent BROKEN (it errs closed).

What it never does: touch nginx, use sudo, receive or install a data bundle, touch Photon's index or
the routing graphs, write outside the checkout, `$RM_DATA/frontend` and `$RM_STATE`, or remove an
image (the old one stays for rollback C).

### Install (once, by the beta's login user; no sudo)

The agent comes with a release, so the first release that carries `scripts/beta/auto-release.sh` is
shipped by hand ("A new release sha"). Then, in the checkout at that release:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
scripts/beta/auto-release.sh install      # deployed tag: the one HEAD is at; report link: read from $RM_DATA/frontend/beta-build.txt
"$RM_STATE/cd/bin/auto-release.sh" run --dry-run
"$RM_STATE/cd/bin/auto-release.sh" status
```

**Reinstall before v0.5.0.** An agent installed from v0.4.x keeps its own front-end build, which
mounts only `frontend/`; v0.5.0's front-end tests read `src/` and `scripts/` too, so that agent would
stop the api, fail the build and roll back on every front-end release. Once the beta runs v0.5.0
(shipped by hand, or with the agent paused), run `auto-release.sh install` again from that checkout:
it installs `frontend-build.sh` beside the agent, which builds with the whole tree mounted.

`install` checks the user is in the docker group and not root, that the checkout is clean at an
annotated release tag with the matching `TAG`, copies the agent (`auto-release.sh`, `cd_logic.py`,
`receive-data.sh`, `frontend-build.sh`) into `$RM_STATE/cd/bin` (so a release can never change the agent under a pass, and
a rollback to a release older than the agent still has the agent's no-sudo snapshot and restore),
records the deployed tag and the beta notice's report link (`--report-url URL|none` if
`beta-build.txt` is missing: give the one `ship-data.sh --report-url` used), writes
`~/.config/systemd/user/routemaker-beta-cd.service` and `.timer` (a oneshot pass, every 10 minutes
after the last one ended, three hours at most) and enables the timer.

**Linger** (the owner's one possible sudo, once): a user timer runs while the user is logged out
only if linger is on. `install` says which it is; check with `loginctl show-user "$(id -un)" -p Linger`.
Try `loginctl enable-linger` first: systemd's own policy lets a user turn it on for themselves
without sudo (`org.freedesktop.login1.set-self-linger`, where polkit runs). If that is refused, the owner runs `sudo loginctl enable-linger <the beta user>` once. If the
owner would rather not, a crontab line needs neither (`crontab -e`, then
`*/10 * * * * "$HOME/routemaker-beta-state/cd/bin/auto-release.sh" run >/dev/null 2>&1`; `uninstall`
does not remove it).

Optional settings, appended to `vars.sh` like any later decision (never a secret):

| Setting | Default | Meaning |
| --- | --- | --- |
| `export RM_CD_WINDOW=02-06` | any hour | Washington hours (America/New_York, whatever the host's zone) in which a deploy may start, never from 5 minutes before the nightly backup to 30 after it (06:55 to 07:30 UTC for `NIGHTLY_BACKUP_CRON`'s 07:00, read from the checkout; the two hours differ; `22-04` wraps past midnight). A host without time zone data (tzdata) reports a set window as an error. Recommended: a deploy stops the api and worker while it builds (step 6), so a window keeps the builds and the downtime to quiet hours |
| `export RM_CD_DOCKER_FREE_GIB=5` | `3` | GiB that must be free on Docker's root (`docker info`) before a deploy; less, and the release waits |
| `export RM_CD_REQUIRE_SIGNED_TAGS=1` | `0` | also require a good tag signature |
| `export RM_CD_KEEP=5` | `3` | release snapshots kept in `$RM_STATE/cd/backups` (each about 200 MB, on `$HOME`'s disk) |
| `export RM_CD_GITHUB_REPO=owner/name` | `Macrophage87/RouteMaker` | where the check runs are read |

**Front-end releases need two things on the server**, neither of which the agent ever downloads
(OWNER-DECISIONS 436). While either is missing, a release that changes `frontend/` waits (status says which):

- the pinned node image, `docker.io/library/node@sha256:363e1587494626837fa7f9a23bdb453d13b0ff3c67c705c2805cfc69c2d2fad7`
  (the one `ship-data.sh --build-frontend` uses at home). Once, from home, under a tag: `docker save` of the
  bare digest loads on the server with no name, and the agent's lookup by digest then does not find it.

  ```sh
  # at home, with RM_SSH_HOST set to your alias for the server
  N=docker.io/library/node@sha256:363e1587494626837fa7f9a23bdb453d13b0ff3c67c705c2805cfc69c2d2fad7
  docker tag "$N" docker.io/library/node:rm-pinned-363e1587
  docker save docker.io/library/node:rm-pinned-363e1587 | gzip | ssh "$RM_SSH_HOST" 'gunzip | docker load'
  ssh "$RM_SSH_HOST" "docker image inspect $N -f '{{.Id}}'"   # prints an image id: the agent will find it
  ```

  If that prints an error instead of an id (a Docker that does not keep the digest through save and load), the
  way left is the one the agent's status offers: the owner approves a `docker pull` of that digest on the server.
- `node_modules` for the release's lockfile, at `$RM_STATE/cd/node_modules/<sha256 of frontend/package-lock.json>/node_modules`
  (status prints the exact path). From home, in a checkout at the release with `npm ci` done:
  `h=$(sha256sum frontend/package-lock.json | cut -c1-64); tar -C frontend -czf - node_modules | ssh "$RM_SSH_HOST" "d=\$HOME/routemaker-beta-state/cd/node_modules/$h; mkdir -p \$d.part && tar -C \$d.part -xzf - && mv -T \$d.part \$d"`.
  A copy is reused for every release with the same lockfile. There is no download fallback: the
  release waits until the copy arrives.

The build is the same as `ship-data.sh --build-frontend`: `npm test`, `tsc --noEmit` and `vite build`
in the pinned image with `--network none`, `VITE_BETA=1` and the recorded report link (kept in
`$RM_STATE/cd/report-url`; change it with `set-report-url URL|none`), and it is refused if the value
of any secret in `.env` appears in it.

### Day to day

```sh
. "$HOME/routemaker-beta-state/vars.sh"
A="$RM_STATE/cd/bin/auto-release.sh"
"$A" status                       # deployed tag, the last pass's result, holds, failures, a pass running or stopped mid-deploy, disk, the timer, linger
cat "$RM_STATE/cd/last-release-report.txt"   # the last deploy, rollback or hold; last-report.txt is the last pass; runs/<time>.log has the build output
journalctl --user -u routemaker-beta-cd --since today  # the passes, if the journal keeps user units
"$A" pause "why"                  # no pass deploys until resume; says if a pass is running now (it is not stopped)
"$A" pause --wait "why"           # the same, then waits for a running pass to end: use this before working by hand
"$A" resume
"$A" run --dry-run                # what the next pass would do (it fetches; it changes nothing)
"$A" retry v0.2.0                 # try a held or failed tag again, once its cause is fixed
"$A" hold v0.2.0 "why"            # keep a tag from being deployed
"$A" mark-deployed v0.2.0         # after shipping by hand, or to clear BROKEN once the owner has looked
"$A" mark-deployed --force v0.2.0 # the same over a half-done deploy's record (IN PROGRESS), once the owner has put the stack right by hand
systemctl --user stop routemaker-beta-cd.timer        # or stop the timer altogether
```

**Rollback by hand** is rollback C above, with the files the agent kept: the snapshot is
`$RM_STATE/cd/backups/pre-release-<time>.dump` (restore it with
`receive-data.sh --env-file .env --backups-dir "$RM_STATE/cd/backups" restore-dump <file>`, no sudo),
the old front end's top-level files (`index.html`, `beta-build.txt`) are in `$RM_STATE/cd/backups/frontend.pre-release-<time>/`, and the previous
tag is in `$RM_STATE/cd/previous-tag`. If that saved directory has no `sw.js` (a tag from before the installable
app), the restore leaves the newer `sw.js` in place, and so does the agent's own automatic rollback: copy the kill
switch over it as in the "Front end only" undo above. Pause the agent first (`pause --wait`); once the checkout and `TAG` are back,
`"$A" hold <the newer tag> "rolled back by hand"` (or the next pass would deploy it again),
`"$A" mark-deployed <the previous tag>` (with `--force` if `status` showed `IN PROGRESS`: the
hand rollback replaces the agent's), then `"$A" resume`. A later release (a higher tag) is the
usual way forward.

**Upgrading the agent.** A release that changes the agent says so in its report; once it is
deployed, rerun `"$RM_SRC/scripts/beta/auto-release.sh" install` (it keeps the state). Until then the
installed copy keeps running.

**Disk.** `status` shows the free space on Docker's root and `$RM_STATE`, the number of api
images (one a release, kept for rollback C), the `<db>_before_<time>` databases automatic restores
left, and the `node_modules` copies. The agent removes none of the images or databases; the owner
does, once a release has run well: `docker image rm ghcr.io/macrophage87/routemaker-api:<old TAG>`
(never the running one or the previous one), `drop database "<db>_before_<time>"` in postgis, and
old `$RM_STATE/cd/node_modules/<hash>` directories. The agent keeps `RM_CD_KEEP` snapshots.

**Uninstall:** `"$A" uninstall` stops and removes the timer and units; `rm -rf "$RM_STATE/cd"`
removes the agent, its logs and its snapshots (owner's say-so: they hold database dumps).

## Alerts

`scripts/beta/alert.sh` (review OPS-1) posts to a Discord channel the owner reads when the beta
needs him. Nothing else reaches him: without it a broken router, a failed rollback or a timetable
about to run out is found only by riding.

What is posted, each as one short message starting "RouteMaker beta:":

- **The site:** every 10 minutes a user timer runs the local smoke tests (`smoke-test.sh --local`:
  health, a route, place search, a tile) and `manage.py check_operations` in the worker (backups,
  failed or wedged jobs, disk, the transit timetable's end). A failure seen twice in a row is
  posted with its FAIL lines or the check's report; the same failure is posted again only once a
  day while it lasts, and "working again" when it clears. No check runs while a deploy pass holds
  the agent's lock (a deploy stops the api on purpose). The weekly rebuild's waiting job is
  reported as paused, not stale (above), so it never posts.
- **Releases:** the release agent posts each deploy, and a rollback, a failure, a hold, an
  interrupted pass, BROKEN, a setting error, checkout drift or a disk stall once per tag (again
  once a day while it lasts). Idle passes post nothing.

Messages carry release tags, step names, the smoke tests' FAIL lines and `check_operations`' own
report: no secret, no address and no rider's data. Mentions are switched off in every message.
Outbound: `discord.com` from the host (the webhook is posted by the login user, not a container).

**Install (once, as the beta's login user; no sudo).** In Discord: the channel's settings,
Integrations, Webhooks, New Webhook, Copy Webhook URL. Then on the server:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
"$RM_SRC/scripts/beta/alert.sh" set-webhook   # paste the address, Enter, Ctrl-D; it is never an argument, so it is in no history
"$RM_SRC/scripts/beta/alert.sh" install       # copies alert.sh into $RM_STATE/cd/bin and enables the 10-minute timer
"$RM_STATE/cd/bin/alert.sh" test              # one test message in the channel
"$RM_SRC/scripts/beta/auto-release.sh" install  # once, so the agent's installed copy posts its results too
```

**Release notes for riders (a second, read-only channel).** The live release's notes,
`docs/releases/<tag>.md` from its checkout (docs/releases/README.md), go to a second webhook: the
title "RouteMaker vX.Y.Z is on beta", then the notes, split at line ends to fit. The agent tries on
each deploy and each up-to-date pass until they are posted, once per tag
(`$RM_STATE/alerts/release-posted`; a pass that stops part-way resumes at the next message). A
deploy first refreshes the installed `alert.sh` from the deployed checkout, so the release that
brings this posts its own notes. A tag without a notes file posts the title alone; a failure is
reported once a day in the alerts channel and never fails a pass. By hand:
`alert.sh release-notes vX.Y.Z "$RM_SRC/docs/releases/vX.Y.Z.md"`.
In Discord: a text channel whose `@everyone` permissions allow View Channel and Read Message
History and deny Send Messages and Create Threads (a webhook still posts there), then its own
webhook. On the server:

```sh
. "$HOME/routemaker-beta-state/vars.sh"
cd "$RM_SRC"
"$RM_SRC/scripts/beta/alert.sh" set-release-webhook   # skip if $RM_STATE/release-webhook is already stored (it is); paste, Enter, Ctrl-D; mode 600
"$RM_SRC/scripts/beta/alert.sh" release-test          # one test message in the release channel
```

Without `release-webhook` nothing is posted there, and the alerts channel is unchanged.

Day to day: `journalctl --user -u routemaker-beta-alert --since today` shows each check;
`ls "$RM_STATE/alerts"` shows what is currently posted (a `.strike` file is a failure seen once).
`alert.sh uninstall` stops the checks; the agent then posts only its own results while a webhook
is set, and nothing once `alert-webhook` is removed. An off-host uptime check of the public URL is
not part of this: if the whole server is down, nothing on it can post.

## Operating notes

- **Memory events:** `docker inspect -f '{{.Name}} {{.State.OOMKilled}} {{.RestartCount}}' $(docker ps -q --filter label=com.docker.compose.project=routemaker-beta)`.
  A container that was OOM-killed restarts by itself (`restart: unless-stopped`); report it with its `docker stats` history.
- **Routing capacity:** six gunicorn workers allow two route plans at once across the whole site (OWNER-DECISIONS 367.2),
  beside two place searches and one stress-tile draw, with one worker always free for `/healthz`. A third person's plan waits
  for a slot, up to about 50 seconds. That is a consequence of the memory budget, not a fault. `compose.beta.yaml` explains
  the arithmetic.
- **Overrides:** the beta's `override` table comes from home. `db --update-data` replaces it with home's, so an
  override made on the beta does not survive a data update (the `pre-update` dump keeps it). Curate overrides at home.
- **Review is home's only:** its lists are never shipped and the beta has no rebuild reports to compute them, and a
  ruling made here would go with the next data update like any override. Rule at home (OPERATIONS.md, "Review mode:
  shipping and its lists").
- **Link previews are inert here** while the basic auth covers `/s/`: a chat app's fetcher is refused, so a shared link
  shows as a bare link. Opening it in a browser (signed in to the beta) works.
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
- **Backups:** the worker writes a nightly dump to `$RM_DATA/backups` (seven kept, about 200 MB each, without the
  `BACKUP_EXCLUDED_TABLES` in `config/procrastinate.py`: both session tables, client-address rows and caches). Dumps
  written before v0.7.0 still carry Django's session table, so the release flushes the beta's sessions once. They are on the same disk; copying them off the server is the owner's decision.
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
- **Logs:** `scripts/beta/beta-compose.sh logs --tail 100 api`. Access logs carry no query strings or addresses by design:
  the api's gunicorn log and nginx's `/var/log/nginx/rmbeta-access.log` keep the method, the path, the status and the time,
  with no query string, no client address and no tester name. The paths whose queries hold a place (`/api/reverse`,
  `/api/geocode`, `/api/segment-info`, `/api/street-photo`, `/api/junction-suggestions/at`,
  `/api/stress-suggestions/ticket`, `/api/stress-suggestions/mine`, `/api/transit/station-times`, `/api/transit/next-vehicle`, `/api/bikeshare/docks`,
  and Review's `/api/review/items`, `/api/review/map`, `/api/review/next`, `/api/review/road/<way>` and `/api/review/street-photo`) log nginx errors at `crit` only, to `/var/log/nginx/rmbeta-error.log`, so
  a 502 or 504 there leaves no error-log line; `rmbeta-access.log` still shows the status and the time (about 0 s:
  the api was down; about 75 s: it timed out), and for a 502 the api's own log usually has nothing, because the
  request never reached it. The time in the nginx and gunicorn logs is the whole request's, not one router call's. Upstream errors on every other path still go to the
  host's own nginx error log, with the request line (those paths carry no location in a query; a tile path does show
  the area viewed, as any map pan does).
- **No rebuild runs here.** There is no rebuild container, and `WEEKLY_REBUILD_PAUSED=1` is set so that a rebuild
  worker started by mistake would only record a pause. New routing data always comes from home as a bundle. Expected,
  and not a fault: the worker's schedule still queues the weekly tick, and with no rebuild worker to take it one
  `weekly_rebuild` job waits on the `rebuild` queue (its queueing lock keeps it to one). `check_operations` and
  the admin's operations page list `weekly_rebuild` as **paused**, not stale, while `WEEKLY_REBUILD_PAUSED` is set
  (from v0.7.0; before it, they called it stale from about eight days after setup), and the free-space check drops
  the rebuild's 20 GiB floor. Do not start a rebuild worker to clear the waiting job. **Never run `run_rebuild_now` here** (for example `beta-compose.sh exec worker ./manage.py
  run_rebuild_now`): a hand-fired rebuild ignores the pause by design, and the wrapper does not catch it.
- **`scripts/boot/` is for the home machine only.** Never install its unit or run `start-stack.sh` here (step 1).
- **What the bundle holds** (sizes measured 2026-10-04): the four routing graphs' `tiles.tar` and sqlite files 2.2 GB
  (standard 611 MB, no-trail 450 MB, ebike 611 MB, weekend 611 MB), the Photon index 742 MB, elevation 310 MB, the base map
  298 MB, the database dump 207 MB (that figure still held the stress-tile cache, which is no longer shipped, so it is
  smaller now), the front end 3 MB: about 3.74 GiB in 1259 files, checksummed one by one. The transit schedule, once
  built, is one JSON file.
