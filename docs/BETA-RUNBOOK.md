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
| `/var/www/routemaker-acme` | Only if certbot's webroot method is chosen | `rm -rf` it |

It does not touch the other sites, `nginx.conf`, the firewall, the system packages' configuration,
or Docker's daemon settings. If a step seems to need any of those, **stop and ask the owner**.

The memory budget is hard: every container has a cap (`compose.beta.yaml`, about 6.75 GiB in all
against the host's 8.6 GiB available), so a spike restarts a RouteMaker container rather than
starving another site.

### Rules while running this

1. Never run a bare `docker compose up`. Use `scripts/beta/beta-compose.sh`, which always adds the
   overlay and `.env`, and refuses `up` without service names. Name services as the steps below do.
2. Never `docker compose down -v`, `docker system prune`, or `rm -rf` anything outside the directories
   in the table above.
3. `nginx -t` must pass before every `nginx -s reload`. If it fails, remove the new file and do not reload.
4. Do not put a password, key or token in a command line you display, a file in the checkout, or a
   message. `make-env.sh` and `make-htpasswd.sh` generate them for you.
5. If any check says to stop, stop, and report the exact output to the owner.

## 0. Variables

Set these in the shell you work in (nothing else is read from your environment):

```sh
export RM_SHA=<the 40-character git sha from the bundle's MANIFEST.txt, git_sha=>
export RM_REPO_URL=<the repository URL the owner gave you>
export RM_DATA=/data/routemaker
export RM_SRC=/data/routemaker-src
export RM_INCOMING=/data/routemaker-incoming
```

## 1. Prerequisites and checks (changes nothing)

```sh
free -m                                  # "available" must be at least 7500 MiB; the beta's caps total 6916 MiB
df -h /data /                            # /data: at least 25 GB free (bundle 4 GB, installed copy 4 GB, images, backups)
id -nG | tr ' ' '\n' | grep -x docker    # you must be in the docker group (or use sudo for every docker command)
docker version --format '{{.Server.Version}}'; docker compose version   # Docker 29, compose 2.40 or newer
ss -ltn | awk '{print $4}' | grep -E ':(8087)$' || echo "port 8087 is free"
nginx -v; sudo nginx -T 2>/dev/null | grep -E '^\s*(include|user) ' | head   # which directory does nginx include? which user?
command -v git rsync openssl curl python3 sha256sum
python3 -c 'import yaml' && echo "pyyaml ok"      # only for the pre-flight checker; apt install python3-yaml if you want it
command -v certbot && sudo certbot certificates  # which certificates already exist?
getent hosts routemaker.cieply.com               # must resolve to THIS server's public address
```

Decide and note down:

- **The api port.** `8087` unless `ss` shows it taken; then pick a free one and use it as `--api-port`
  in step 3 and `BETA_API_PORT` everywhere. Only `127.0.0.1` is ever bound.
- **Where nginx reads site files from.** On Ubuntu this is normally `/etc/nginx/sites-enabled/*`
  (files live in `sites-available/`, linked) or `/etc/nginx/conf.d/*.conf`. Use whichever the
  `include` lines above show and whichever the other sites already use. `$NGINX_SITE` below is the
  full path of the one file you will add.
- **Whether `routemaker.cieply.com` already points here.** If `getent` shows another address, stop;
  the owner has to change DNS first.

Record the "before" state so you can prove nothing else changed:

```sh
sudo nginx -T > /tmp/nginx-before.txt 2>&1
docker ps --format '{{.Names}} {{.Status}}' > /tmp/docker-before.txt
# a status line for each of the host's other sites (the server_name values in nginx-before.txt):
sudo grep -hE '^\s*server_name ' /tmp/nginx-before.txt | tr -d ';' | awk '{for(i=2;i<=NF;i++)print $i}' | sort -u > /tmp/sites-before.txt
while read -r s; do printf '%s %s\n' "$s" "$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$s/" || echo fail)"; done < /tmp/sites-before.txt > /tmp/sites-before-status.txt
cat /tmp/sites-before-status.txt
```

## 2. Get the code at the exact sha (adds `$RM_SRC`)

```sh
sudo install -d -o "$(id -un)" -g "$(id -gn)" "$RM_SRC" "$RM_INCOMING"
git clone "$RM_REPO_URL" "$RM_SRC" && cd "$RM_SRC" && git checkout --detach "$RM_SHA"
git rev-parse HEAD            # must print exactly $RM_SHA
git status --short            # must print nothing
```

If the repository is not reachable from the server, the owner can send a tarball from home
(`git archive --format=tar.gz -o routemaker-<sha>.tar.gz <sha>`, then `rsync` it); unpack it into
`$RM_SRC` and use `git`-free checks: the bundle's `MANIFEST.txt` records the sha, and
`receive-data.sh` will need `--allow-sha-mismatch` because there is no `.git` to read it from.

Undo: `rm -rf "$RM_SRC"`.

## 3. Make `.env` (adds `$RM_SRC/.env`, mode 600)

```sh
cd "$RM_SRC"
scripts/beta/make-env.sh --data-root "$RM_DATA" --api-port 8087       # TAG defaults to the first 12 characters of the sha
```

It generates `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY` and `PGPASSWORD` as random hex and prints
no secret. It refuses to overwrite an existing `.env`: a new `PGPASSWORD` would no longer match the
database initialised with the old one. The required values and what is optional:

| Variable | Required | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY`, `KEY_ENCRYPTION_KEY`, `PGPASSWORD` | yes | generated by `make-env.sh` |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | yes | already `routemaker.cieply.com` / `https://routemaker.cieply.com` |
| `DATA_ROOT`, `TAG`, `COMPOSE_PROJECT_NAME` | yes | `/data/routemaker`, the short sha, `routemaker-beta` |
| `BETA_API_PORT`, `BETA_WEB_CONCURRENCY` | yes | `8087`, `3` |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI` | **no** | Planning works signed out. Leave empty and there is no sign-in. To enable it the owner adds `https://routemaker.cieply.com/auth/callback` to the Discord application and gives you the id and secret; edit `.env`, then `beta-compose.sh up -d api`. |
| `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` | no | the first instance admin's Discord user id |
| VDOT token | no | this release has no such variable; there is nothing to set |

Never `source .env`; compose reads it. Never print it. Do not add `$` to a value (compose expands it).

Undo: `rm .env` (only before the database exists; after, keep it).

## 4. Pre-flight check of the overlay (changes nothing)

```sh
cd "$RM_SRC"
python3 scripts/check_beta_compose.py --render      # needs pyyaml; prints the memory table and "beta compose: ok"
scripts/beta/beta-compose.sh config --services      # exactly: api migrate photon postgis valhalla-ebike valhalla-no-trail valhalla-standard valhalla-weekend worker
```

If the checker prints a problem, stop and report it. It checks: no caddy or rebuild, a memory cap
and CPU cap and `memswap_limit` on every container, only the api publishing a port and only on
`127.0.0.1`, the memory total under 7.0 GiB, three gunicorn workers, the weekly rebuild paused.

## 5. Prepare `DATA_ROOT` (adds `$RM_DATA`)

```sh
cd "$RM_SRC"
sudo install -d "$(dirname "$RM_DATA")"
sudo sh scripts/prepare_data_root.sh --env-file ./.env
```

It creates `$RM_DATA` and its subdirectories owned by the right users (this is the repository's own
script; it chowns only directories under `DATA_ROOT`). Undo: `sudo rm -rf "$RM_DATA"` only if no
data has been installed yet or the owner agreed.

## 6. Build the api image and pull the third-party images (adds Docker images)

```sh
cd "$RM_SRC"
scripts/beta/beta-compose.sh build api                 # the worker and migrate services use the same image
scripts/beta/beta-compose.sh pull postgis photon valhalla-standard
docker image ls | grep -E 'routemaker-api|postgis|photon-docker|valhalla'
```

The build needs network access (pip) and a few minutes. Images land in Docker's storage on `/data`.
Undo: `docker image rm ghcr.io/macrophage87/routemaker-api:<TAG>` (the third-party images may be used
by others; leave them).

## 7. Receive the data (adds files under `$RM_DATA`)

At home the owner runs (this is for you to know, and to ask the owner for if the bundle is not
at `$RM_INCOMING` yet):

```sh
scripts/beta/ship-data.sh --live-dir <live checkout> --build-frontend  user@server  /data/routemaker-incoming
```

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
the front end. It verifies every installed file's sha256 again. It refuses if `/data` lacks room.

Then the database, which needs postgis running first:

```sh
scripts/beta/beta-compose.sh up -d postgis
scripts/beta/beta-compose.sh ps postgis           # wait for "healthy" (up to a minute on first start)
scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env db
```

`db` restores the dump (the `live` and `public` schemas), analyses, and compares each table's row
count with the bundle's. It takes about two minutes and uses about 530 MiB of postgis's 1 GiB cap.
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

Migrations check, and Django's static files (the admin's CSS; nginx serves `$RM_DATA/static`):

```sh
scripts/beta/beta-compose.sh run --rm --no-deps api ./manage.py migrate --check && echo "migrations current"
scripts/beta/beta-compose.sh run --rm --no-deps api ./manage.py collectstatic --noinput
```

Health and memory:

```sh
curl -s -H 'Host: routemaker.cieply.com' http://127.0.0.1:8087/healthz          # ok
scripts/beta/smoke-test.sh --local                                              # route, search, reverse, stress tile; all PASS
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' | grep routemaker-beta
free -m
```

Every container should sit well under its cap (api about 0.3 GiB, photon about 1 GiB, each router
under 0.7 GiB). Photon needs a minute after start before its first search answers. If any container
is near its cap or `docker inspect -f '{{.State.OOMKilled}}' <name>` prints `true`, report it with
the numbers; do not raise a cap on your own.

Undo: `scripts/beta/beta-compose.sh down` (containers and network only; `$RM_DATA` is untouched).

## 9. nginx: add one file, in two stages (adds `$NGINX_SITE`, the htpasswd file, optionally a certificate)

Nothing public is served until stage 2. `render-nginx.sh` only prints or writes the file you name;
it never touches `/etc`.

### 9a. The password file

```sh
cd "$RM_SRC"
sudo scripts/beta/make-htpasswd.sh <name1> <name2> ...      # one name per tester; refuses to overwrite
```

It writes `/etc/nginx/routemaker-beta.htpasswd` (root, group of the nginx worker user, mode 640) and
prints each generated password once, on standard output. **Give those to the owner in your report and
nowhere else**; they are stored only as hashes. To choose a password yourself skip the script and use
`htpasswd` or `openssl passwd -apr1`. To add a tester later: `sudo htpasswd /etc/nginx/routemaker-beta.htpasswd <name>`.
Undo: `sudo rm /etc/nginx/routemaker-beta.htpasswd` (only after the site file is removed).

### 9b. TLS: choose one, and do not assume either

First look at what exists: `sudo certbot certificates`, and how the other sites get theirs
(`sudo grep -R ssl_certificate /etc/nginx | head`).

**Option A: certbot issues a certificate for `routemaker.cieply.com`.** Install the stage-1 file,
which answers only the ACME challenge on port 80, and let certbot's nginx authenticator use it. Use
`certonly` rather than the installer form, because the installer would rewrite the site file this
runbook generated.

```sh
cd "$RM_SRC"
sudo install -d /var/www/routemaker-acme
scripts/beta/render-nginx.sh --stage acme --out /tmp/routemaker-beta.acme.conf
sudo install -m 644 /tmp/routemaker-beta.acme.conf "$NGINX_SITE"           # sites-available: also link into sites-enabled if that is the host's pattern
sudo nginx -t && sudo nginx -s reload
sudo certbot certonly --webroot -w /var/www/routemaker-acme -d routemaker.cieply.com
#   (or:  sudo certbot certonly --nginx -d routemaker.cieply.com   if that is how the other sites' certificates were made)
sudo ls /etc/letsencrypt/live/routemaker.cieply.com/        # fullchain.pem and privkey.pem
```

Certbot's existing renewal timer renews it; the port-80 ACME location stays in the final file for
that. Then continue to 9c with `--cert-fullchain /etc/letsencrypt/live/routemaker.cieply.com/fullchain.pem`
and `--cert-key /etc/letsencrypt/live/routemaker.cieply.com/privkey.pem`.

**Option B: a certificate already on the host covers the name** (for example a wildcard for
`*.cieply.com`, or a certificate the owner supplies). Use its paths as they are, and skip stage 1:

```sh
sudo certbot certificates        # find the entry whose Domains include routemaker.cieply.com or *.cieply.com
```

Continue to 9c with that entry's `Certificate Path` as `--cert-fullchain` and `Private Key Path` as `--cert-key`.
Do not run `certbot renew --force` or alter any existing certificate.

Whichever option, if the host's other sites include certbot's `options-ssl-nginx.conf`, add
`--tls-options-include /etc/letsencrypt/options-ssl-nginx.conf` in 9c to match them.

### 9c. The full site

```sh
cd "$RM_SRC"
scripts/beta/render-nginx.sh --stage full --api-port 8087 \
    --cert-fullchain <path> --cert-key <path> [--tls-options-include <path>] \
    --out /tmp/routemaker-beta.full.conf
sudo install -m 644 /tmp/routemaker-beta.full.conf "$NGINX_SITE"        # replaces the stage-1 file, or adds the file if you skipped stage 1
sudo nginx -t                                                           # must say "syntax is ok" and "test is successful"
sudo nginx -s reload
```

If `nginx -t` complains about `http2 on`, the host's nginx is older than 1.25.1: edit the installed file,
delete the `http2 on;` line and write `listen 443 ssl http2;` and `listen [::]:443 ssl http2;`, then test again.

Prove nothing else changed:

```sh
sudo nginx -T > /tmp/nginx-after.txt 2>&1
diff <(sed 's/[[:space:]]*$//' /tmp/nginx-before.txt) <(sed 's/[[:space:]]*$//' /tmp/nginx-after.txt) | grep '^<' | head   # no output: nothing was removed or edited
while read -r s; do printf '%s %s\n' "$s" "$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$s/" || echo fail)"; done < /tmp/sites-before.txt | diff - /tmp/sites-before-status.txt && echo "other sites unchanged"
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
BETA_USER=<one of the names> BETA_PASSWORD=<its password> scripts/beta/smoke-test.sh --public https://routemaker.cieply.com
```

(Type the password into the environment variable only for that one command, from the list `make-htpasswd.sh`
printed. It is passed to curl on standard input.) Every line must say `PASS`. It checks: robots.txt is
public and disallows everything; `/` and `/healthz` return 401 without credentials and a wrong password is
refused; noindex and the content security policy are present; http redirects to https; the front end loads;
a preset link redirects; the base map is served to this site and refused to a foreign origin; a route,
a place search, a reverse lookup and a stress tile all answer.

Then check by eye, once, in a browser the owner can use: the page loads behind the password prompt,
the map draws, a two-point route appears, and the **Beta banner** is shown at the top (it appears only in the
front end built with `VITE_BETA=1`, which `ship-data.sh --build-frontend` does).

## 11. Report back to the owner

Say: the sha running, that all checks passed (or exactly which did not), `docker stats` numbers against the
caps, the other-sites comparison, the testers' passwords (once, in the reply to the owner and nowhere else),
and the `df -h /data` figure.

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

**B. Go back to the previous database:** `receive-data.sh ... db --replace-db` with the old bundle, or restore the
safety dump the last `--replace-db` wrote:

```sh
scripts/beta/beta-compose.sh exec -T postgis pg_restore -U routemaker -d routemaker --no-owner --clean --if-exists < "$RM_DATA/backups/pre-restore-<time>.dump"
```

**C. Go back to the previous release:** the previous api image is still on the host under its own tag.

```sh
cd "$RM_SRC" && git checkout --detach <previous sha>
sed -i 's/^TAG=.*/TAG=<previous 12-character sha>/' .env          # the one edit to .env a release change needs
scripts/beta/beta-compose.sh up -d api worker                     # recreates them on the old image
```

(If the old image was removed, `scripts/beta/beta-compose.sh build api` rebuilds it from that checkout.)

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
sudo rm -rf /data/routemaker /data/routemaker-incoming /data/routemaker-src /var/www/routemaker-acme
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
3. If the bundle has a db part: `... db --replace-db` (a safety dump is taken first). Stop the api and worker first so
   nothing writes during the restore: `scripts/beta/beta-compose.sh stop api worker`, then start them again.
4. `scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`
   (a router keeps the old archive mapped until restarted), and `restart photon` if the index changed.
5. `scripts/beta/smoke-test.sh --local`, then `--public`.

**A new release sha** (code changes):

1. Owner gives the new sha and a new bundle if the data changed.
2. `cd "$RM_SRC" && git fetch && git checkout --detach <new sha>`.
3. `scripts/beta/make-env.sh` will not overwrite `.env`; set the image tag by hand:
   `sed -i "s/^TAG=.*/TAG=$(git rev-parse --short=12 HEAD)/" .env`.
4. `python3 scripts/check_beta_compose.py --render` (a release may change the compose file; the checker is the gate).
5. `scripts/beta/beta-compose.sh build api`, then, if the data changed, the data steps above.
6. `scripts/beta/beta-compose.sh up -d api worker` (recreates them; `migrate` runs first), then the migrations check and
   `collectstatic` from step 8, and the smoke tests. Routers and Photon restart only if their image or command changed
   in the release (`beta-compose.sh up -d <name>` recreates exactly the ones that did).
7. The front end comes in the bundle (`frontend/`), so `files` installs it; the new `index.html` goes in last.

**Front end only:** ship with `--without tiles --without elevation --without basemap --without photon --without db`,
then `sudo ... files`. Nothing restarts; `index.html` is read per request.

## Operating notes

- **Memory events:** `docker inspect -f '{{.Name}} {{.State.OOMKilled}} {{.RestartCount}}' $(docker ps -q --filter label=com.docker.compose.project=routemaker-beta)`.
  A container that was OOM-killed restarts by itself (`restart: unless-stopped`); report it with its `docker stats` history.
- **Routing capacity:** three gunicorn workers allow one route plan at a time across the whole site; a second person's plan waits
  up to about 50 seconds. That is a consequence of the memory budget, not a fault. `compose.beta.yaml` explains the arithmetic.
- **Backups:** the worker writes a nightly dump to `$RM_DATA/backups` (seven kept, about 200 MB each, without sessions or
  client-address rows). They are on the same disk; copying them off the server is the owner's decision.
- **Reboot:** containers restart with Docker (`unless-stopped`). `/data` must be mounted before Docker starts, as it already is
  for Docker's own storage there.
- **Logs:** `scripts/beta/beta-compose.sh logs --tail 100 api`. Access logs carry no query strings or addresses by design.
- **No rebuild runs here.** `WEEKLY_REBUILD_PAUSED=1` and there is no rebuild container. New routing data always comes
  from home as a bundle.
- **What the bundle holds** (sizes measured 2026-10-04): the four routing graphs' `tiles.tar` and sqlite files 2.2 GB
  (standard 611 MB, no-trail 450 MB, ebike 611 MB, weekend 611 MB), the Photon index 742 MB, elevation 310 MB, the base map
  298 MB, the database dump 207 MB, the front end 3 MB: about 3.74 GiB in 1259 files, checksummed one by one.
