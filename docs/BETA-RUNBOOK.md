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
already exists (`/data` included: it holds Docker's storage and other people's data).

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
```

## 1. Prerequisites and checks (changes nothing)

```sh
free -m                                  # "available" must be at least 7900 MiB; the caps total 7102 MiB resident, 7358 at the startup peak
df -h /data /                            # /data: at least 25 GB free (bundle 4 GB, installed copy 4 GB, images, backups)
id -nG | tr ' ' '\n' | grep -x docker    # you must be in the docker group (or use sudo for every docker command)
docker version --format '{{.Server.Version}}'; docker compose version   # Docker 29, compose 2.40 or newer
ss -ltn | awk '{print $4}' | grep -E ':(8087)$' || echo "port 8087 is free"
nginx -v; sudo nginx -T 2>/dev/null | grep -E '^\s*(include|user) ' | head   # which directory does nginx include? which user?
command -v git rsync openssl curl python3 sha256sum
python3 -c 'import yaml' && echo "pyyaml ok"      # only for the pre-flight checker; apt install python3-yaml if you want it
getent hosts routemaker.cieply.com               # must resolve to THIS server's public address
sudo nginx -T 2>/dev/null | grep -c 'listen \[::\]'   # 0: the other sites do not listen on IPv6; render with --no-ipv6 in 9c
for p in "$RM_SRC" "$RM_INCOMING" "$RM_DATA" "$HOME/routemaker-beta-state" "$HOME/routemaker-beta-passwords.txt" \
         /var/www/routemaker-acme /etc/nginx/routemaker-beta.htpasswd; do
  [ ! -e "$p" ] || echo "EXISTS: $p"          # any EXISTS line is a stop: ask the owner before going on
done
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

Neither option changes another site's TLS. Do not use certbot's `--nginx` authenticator or
installer: it edits and reloads the host's nginx configuration at issue time and again at every
renewal.

Decide and note down:

- **The api port.** `8087` unless `ss` shows it taken; then pick a free one and use it as `--api-port`
  in step 3 and `BETA_API_PORT` everywhere. Only `127.0.0.1` is ever bound.
- **Where nginx reads site files from.** On Ubuntu this is normally `/etc/nginx/sites-enabled/*`
  (files live in `sites-available/`, linked) or `/etc/nginx/conf.d/*.conf`. Use whichever the
  `include` lines above show and whichever the other sites already use. `$NGINX_SITE` below is the
  full path of the one file you will add.
- **Whether `routemaker.cieply.com` already points here.** If `getent` shows another address, stop;
  the owner has to change DNS first.

Record the "before" state so you can prove nothing else changed. `nginx -T` prints every site's
configuration, so the copies go in a private directory (mode 700, files 600), not in `/tmp`:

```sh
export RM_STATE="$HOME/routemaker-beta-state"
[ ! -e "$RM_STATE" ] && mkdir -m 700 "$RM_STATE"
umask 077                                       # for this shell: every file below is 600
sudo nginx -T > "$RM_STATE/nginx-before.txt" 2>&1
docker ps --format '{{.Names}} {{.Status}}' > "$RM_STATE/docker-before.txt"
# a status line for each of the host's other sites (the server_name values in nginx-before.txt):
grep -hE '^\s*server_name ' "$RM_STATE/nginx-before.txt" | tr -d ';' | awk '{for(i=2;i<=NF;i++)print $i}' | sort -u > "$RM_STATE/sites-before.txt"
while read -r s; do printf '%s %s\n' "$s" "$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$s/" || echo fail)"; done < "$RM_STATE/sites-before.txt" > "$RM_STATE/sites-before-status.txt"
cat "$RM_STATE/sites-before-status.txt"
```

## 2. Get the code at the exact sha (adds `$RM_SRC`)

```sh
for p in "$RM_SRC" "$RM_INCOMING"; do [ ! -e "$p" ] || { echo "$p exists: stop and ask the owner"; false; }; done &&
sudo install -d -o "$(id -un)" -g "$(id -gn)" "$RM_SRC" "$RM_INCOMING"     # only ever creates: the check above saw neither
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
| `BETA_API_PORT`, `BETA_WEB_CONCURRENCY` | yes | `8087`, `6` (two route plans at once, one worker always free; the checker refuses more) |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI` | **no** | Planning works signed out. Leave empty and there is no sign-in. To enable it the owner adds `https://routemaker.cieply.com/auth/callback` to the Discord application and gives you the id and secret; edit `.env`, then `beta-compose.sh up -d api`. |
| `BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID` | no | The beta's database carries **no accounts** (the dump strips them, OWNER-DECISIONS 367.3), so the owner claims instance admin afresh. Set this to the owner's Discord user id only if Discord sign-in is turned on, and have the owner sign in once promptly after the api starts. Otherwise leave it empty. |
| VDOT token | no | this release has no such variable; there is nothing to set |

Never `source .env`; compose reads it. Never print it. Do not add `$` to a value (compose expands it).

Undo: `rm .env` (only before the database exists; after, keep it).

## 4. Pre-flight check of the overlay (changes nothing)

```sh
cd "$RM_SRC"
python3 scripts/check_beta_compose.py --render            # the overlay itself, with dummy values
python3 scripts/check_beta_compose.py --env-file .env      # THE GATE: the overlay with this server's .env
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
plus capped direct buffers inside its cap; the weekly rebuild paused; and in `.env`, no
`COMPOSE_PROFILES` or `COMPOSE_FILE`.

## 5. Prepare `DATA_ROOT` (adds `$RM_DATA`)

```sh
cd "$RM_SRC"
[ ! -e "$RM_DATA" ] || { echo "$RM_DATA exists: stop and ask the owner"; false; }
sudo sh scripts/prepare_data_root.sh --env-file ./.env
```

`/data` itself already exists (step 1) and is not touched: no `install -d`, `chown` or `chmod` on
it, because it holds Docker's storage and other people's data. The script creates `$RM_DATA` and its subdirectories owned by the right users (this is the repository's own
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
**The build is not capped:** BuildKit runs inside the Docker daemon, outside every container
limit, and pip's install can take a core and several hundred MB for a few minutes on a host other
sites share. So either build only when the owner says the other sites are quiet, or (preferred)
have the owner build at home from the same sha and send the image, which needs no build here:

```sh
# at home, in a checkout of the same sha:
docker compose build api && docker save ghcr.io/macrophage87/routemaker-api:<TAG> | gzip | ssh user@server 'gunzip | docker load'
```

Then skip the `build` line above and run only the `pull` line.
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

Health and memory:

```sh
curl -s -H 'Host: routemaker.cieply.com' http://127.0.0.1:8087/healthz          # ok
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
  http://127.0.0.1:8087/api/route & done; wait
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' | grep -E 'api|photon'
```
 Photon needs a minute after start before its first search answers. If any container
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

It writes `/etc/nginx/routemaker-beta.htpasswd` (root, group of the nginx worker user, mode 640)
with SHA-512 crypt hashes (`openssl passwd -6`; nginx checks them with the system's crypt(), which
on Ubuntu verifies `$6$`), and the generated passwords to `~/routemaker-beta-passwords.txt`
(mode 600, yours). It prints only that path, never a password. **Do not `cat` the file and do not
put a password in your report**: tell the owner where the file is; he reads it in his own
terminal, hands each tester theirs, and deletes it (`shred -u`). To choose a password yourself
skip the script and use `openssl passwd -6` (it prompts). To add a tester later:
`sudo htpasswd -B /etc/nginx/routemaker-beta.htpasswd <name>` (bcrypt, also fine for nginx on
Ubuntu). Undo: `sudo rm /etc/nginx/routemaker-beta.htpasswd` (only after the site file is removed).

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
[ ! -e /var/www/routemaker-acme ] && [ ! -e "$NGINX_SITE" ] || { echo "the ACME root or the site file exists: stop"; false; }
sudo install -d /var/www/routemaker-acme                                       # new: the check above saw nothing there
scripts/beta/render-nginx.sh --stage acme [--no-ipv6] --out "$RM_STATE/routemaker-beta.acme.conf"
sudo install -m 644 "$RM_STATE/routemaker-beta.acme.conf" "$NGINX_SITE"         # sites-available: also link into sites-enabled if that is the host's pattern
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
scripts/beta/render-nginx.sh --stage full --api-port 8087 \
    --cert-fullchain <path> --cert-key <path> [--tls-options-include <path>] [--no-ipv6] \
    --out "$RM_STATE/routemaker-beta.full.conf"
[ -e "$NGINX_SITE" ] && echo "replacing the stage-1 file" || echo "new file"     # option B: it must say "new file"; anything else, stop
sudo install -m 644 "$RM_STATE/routemaker-beta.full.conf" "$NGINX_SITE"   # replaces the stage-1 file, or adds the file if you skipped stage 1
sudo nginx -t                                                           # must say "syntax is ok" and "test is successful"
sudo nginx -s reload
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
without credentials and a wrong password is refused; noindex and the content security policy are
present; http redirects to https; the front end loads; a preset link redirects; the base map answers
this site's byte-range request with 206 and is refused to a foreign origin; an unlisted base-map path
is a 404; Django's static files are served; a route, a place search, a reverse lookup and a stress
tile all answer.

Then check by eye, once, in a browser the owner can use: the page loads behind the password prompt,
the map draws, a two-point route appears, and the **Beta banner** is shown at the top (it appears only in the
front end built with `VITE_BETA=1`, which `ship-data.sh --build-frontend` does).

## 11. Report back to the owner

Say: the sha running, that all checks passed (or exactly which did not), `docker stats` numbers against the
caps (including the two-plans-at-once measurement), the other-sites comparison, which TLS option step 1's
rule chose and why, **where** the testers' passwords are (`~/routemaker-beta-passwords.txt`; never the
passwords themselves), and the `df -h /data` figure.

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

**B. Go back to the previous database:** restore the safety dump the last data update wrote
(`pre-update-<time>.dump` from `db --update-data`, or `pre-restore-<time>.dump` from `--replace-db`).
`restore-dump` takes a `pre-rollback` snapshot of what is there first, and restores with the same
table-of-contents handling as `db`:

```sh
scripts/beta/beta-compose.sh stop api worker
ls -l "$RM_DATA"/backups/pre-*.dump
sudo scripts/beta/receive-data.sh --env-file .env restore-dump "$RM_DATA/backups/pre-update-<time>.dump"
scripts/beta/beta-compose.sh up -d api worker
```

**C. Go back to the previous release:** the previous api image is still on the host under its own tag. Retagging
alone is not enough when the new release migrated the database forward: the old code would run against a
newer schema. So rollback C also puts back the `pre-release` snapshot taken just before the update
("Shipping an update later", new release, step 5):

```sh
cd "$RM_SRC"
scripts/beta/beta-compose.sh stop api worker
git checkout --detach <previous sha>
sed -i 's/^TAG=.*/TAG=<previous 12-character sha>/' .env          # the one edit to .env a release change needs
sudo scripts/beta/receive-data.sh --env-file .env restore-dump "$RM_DATA/backups/pre-release-<time>.dump"
scripts/beta/beta-compose.sh up -d api worker                     # recreates them on the old image; migrate finds nothing to do
```

Anything the beta's users saved after the update is lost by this (the `pre-rollback` snapshot `restore-dump`
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
   and the `override` and `stress_tile_cache` data, in one transaction, after a `pre-update` safety dump, and leaves
   the beta's own accounts, sessions and audit log alone (`--replace-db` would delete them; it refuses while any
   exist). Stop the api and worker first so nothing writes during it:

   ```sh
   scripts/beta/beta-compose.sh stop api worker
   sudo scripts/beta/receive-data.sh --bundle "$RM_INCOMING" --env-file .env db --update-data
   scripts/beta/beta-compose.sh up -d api worker
   ```
4. `scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`
   (a router keeps the old archive mapped until restarted).
5. `scripts/beta/smoke-test.sh --local`, then `--public`.

**A new release sha** (code changes):

1. Owner gives the new sha and a new bundle if the data changed.
2. `cd "$RM_SRC" && git fetch && git checkout --detach <new sha>`.
3. `scripts/beta/make-env.sh` will not overwrite `.env`; set the image tag by hand:
   `sed -i "s/^TAG=.*/TAG=$(git rev-parse --short=12 HEAD)/" .env`.
4. `python3 scripts/check_beta_compose.py --render` (a release may change the compose file; the checker is the gate).
5. `scripts/beta/beta-compose.sh build api` (or load the image built at home, step 6), then, if the data changed, the
   data steps above. Then, **before anything migrates**, stop the app and snapshot the database, which is what
   rollback C restores if the release has to be undone:

   ```sh
   scripts/beta/beta-compose.sh stop api worker
   sudo scripts/beta/receive-data.sh --env-file .env snapshot-db --label release   # prints $RM_DATA/backups/pre-release-<time>.dump
   ```
6. `scripts/beta/beta-compose.sh up -d api worker` (recreates them; `migrate` runs first), then the migrations check and
   `collectstatic` from step 8 (`exec -T api ...`), and the smoke tests. Routers and Photon restart only if their image or command changed
   in the release (`beta-compose.sh up -d <name>` recreates exactly the ones that did).
7. The front end comes in the bundle (`frontend/`), so `files` installs it; the new `index.html` goes in last.

**Front end only:** ship with `--without tiles --without elevation --without basemap --without photon --without db`,
then `sudo ... files`. Nothing restarts; `index.html` is read per request.

## Operating notes

- **Memory events:** `docker inspect -f '{{.Name}} {{.State.OOMKilled}} {{.RestartCount}}' $(docker ps -q --filter label=com.docker.compose.project=routemaker-beta)`.
  A container that was OOM-killed restarts by itself (`restart: unless-stopped`); report it with its `docker stats` history.
- **Routing capacity:** six gunicorn workers allow two route plans at once across the whole site (OWNER-DECISIONS 367.2),
  beside two place searches and one stress-tile draw, with one worker always free for `/healthz`. A third person's plan waits
  for a slot, up to about 50 seconds. That is a consequence of the memory budget, not a fault. `compose.beta.yaml` explains
  the arithmetic.
- **Accounts:** the beta has its own, none from home (OWNER-DECISIONS 367.3). Data updates (`db --update-data`) never touch
  them; only `db --replace-db --delete-beta-accounts` or rollback B/C to a dump from before they existed removes them.
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
