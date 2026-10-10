#!/usr/bin/env bash
# Start RouteMaker on this computer, at http://localhost. One command, safe to
# rerun: the first run sets everything up, every later run only starts it.
#
#   scripts/local-up.sh [--data-root DIR] [--no-build] [--dry-run] [-- START-STACK-ARGS]
#
# What it does, each step skipped when it is already done:
#
#   1. Checks that Docker answers and that `docker compose` is v2 or later.
#   2. Writes .env if there is none: .env.example in the local plain-HTTP posture
#      (the five-line block at its end), COMPOSE_PROJECT_NAME=routemaker,
#      RESTART_POLICY=no, DATA_ROOT (default ~/rmdata) and a fresh random value
#      for every secret. An existing .env is never changed.
#   3. Prepares DATA_ROOT with scripts/prepare_data_root.sh, run in a container so
#      no sudo is needed (docs/PLAYBOOK.md, 0b).
#   4. Fetches the base map, if DATA_ROOT/basemap has none (docs/PLAYBOOK.md, 4).
#   5. Builds and publishes the front end, when frontend/ changed since the last
#      publish (docs/DEPLOYMENT.md, "The public front end").
#   6. Builds the api and pipeline images (`docker compose build`; cached, so a
#      rerun with nothing changed takes seconds). --no-build skips it.
#   7. Starts the stack:
#        - with routing data (tiles/standard/current/tiles.tar under DATA_ROOT),
#          through scripts/boot/start-stack.sh, the ordered and checked start the
#          home machine already uses; anything after `--` is passed to it, e.g.
#          `-- --force-recreate-all` to put newly built images into service.
#        - without it (a new machine), postgis, migrate, api, worker, rebuild,
#          caddy and photon, then waits for /healthz. The four routers are not
#          started: they have nothing to serve until the first rebuild.
#   8. Collects the admin's static files, and prints what is up and what is next.
#
# One stack per COMPOSE_PROJECT_NAME: if containers of that project exist, they
# must have been started from this checkout, and a first run (no .env) refuses
# when any exist. Otherwise a run from another checkout or worktree would
# rebuild the shared ${TAG} images from its code (the next recreate puts them in
# service) and republish the front end that localhost serves.
#
# The network it needs on a first run: Docker Hub and ghcr.io (images), pypi.org
# and deb.debian.org (the image builds), registry.npmjs.org (the front end) and
# build.protomaps.com plus github.com (the base map). Routing data is not fetched
# here: it is the first rebuild (docs/PLAYBOOK.md, 7), which also needs
# download.geofabrik.de and takes hours. Several of these are blocked in Claude's
# cloud sessions, so this runs on a real computer.
#
# The local stack only: it refuses a .env whose COMPOSE_PROJECT_NAME is not
# routemaker, such as the beta's (docs/BETA-RUNBOOK.md: the beta needs its
# overlay and Docker's restart policy, which this would drop).
#
# Environment (optional): LOCAL_UP_ENV_FILE [<repo>/.env], LOCAL_UP_DOCKER
# [docker], LOCAL_UP_CURL [curl], LOCAL_UP_BASE_URL [http://localhost],
# LOCAL_UP_HEALTHY_S [300], LOCAL_UP_POLL_S [5], LOCAL_UP_START_STACK
# [scripts/boot/start-stack.sh], LOCAL_UP_ROOT_UID [0].
# tests/test_local_up.py points them at temporary files and stubs.
#
# Exit: 0 up; 1 a check failed; 2 started but /healthz never answered 200;
#       64 bad arguments. A command that fails ends the run with its own exit
#       code, and with routing data start-stack.sh's exit code is passed on.

set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
ENV_FILE=${LOCAL_UP_ENV_FILE:-$REPO_DIR/.env}
DOCKER=${LOCAL_UP_DOCKER:-docker}
CURL=${LOCAL_UP_CURL:-curl}
BASE_URL=${LOCAL_UP_BASE_URL:-http://localhost}
HEALTHY_S=${LOCAL_UP_HEALTHY_S:-300}
POLL_S=${LOCAL_UP_POLL_S:-5}
START_STACK=${LOCAL_UP_START_STACK:-$SCRIPT_DIR/boot/start-stack.sh}
# Whose directories mean Docker made them, not scripts/prepare_data_root.sh.
ROOT_UID=${LOCAL_UP_ROOT_UID:-0}

# The images every helper container runs, pinned to the digests the guides use.
BUSYBOX=docker.io/library/busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662
CURL_IMAGE=docker.io/curlimages/curl@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777
NODE=docker.io/library/node@sha256:363e1587494626837fa7f9a23bdb453d13b0ff3c67c705c2805cfc69c2d2fad7

# Started on a machine with no routing data yet. migrate comes with them, as the
# dependency api, worker and rebuild wait on.
FIRST_RUN_SERVICES=(postgis api worker rebuild caddy photon)

DATA_ROOT_ARG=""
DRY_RUN=0
BUILD=1
STACK_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --data-root)
      [ $# -ge 2 ] || { echo "--data-root needs a directory" >&2; exit 64; }
      DATA_ROOT_ARG=$2
      shift 2
      ;;
    --data-root=*) DATA_ROOT_ARG=${1#--data-root=}; shift ;;
    --no-build) BUILD=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --) shift; STACK_ARGS=("$@"); break ;;
    -h | --help)
      sed -n '2,/^set -E/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 64 ;;
  esac
done

say() { printf 'local-up: %s\n' "$*"; }
warn() { printf 'local-up: %s\n' "$*" >&2; }
die() { warn "$@"; exit 1; }
# Progress as plain lines, not bars redrawn in place, which a screen reader reads
# as noise: BuildKit's builds, and compose's own output where it knows the
# variable. The `docker run` helpers below pass --quiet for their image pulls.
export BUILDKIT_PROGRESS=plain COMPOSE_PROGRESS=plain
# A step that changes something: printed and skipped under --dry-run.
run() {
  if [ "$DRY_RUN" = 1 ]; then
    # %q, so a printed command can be pasted back into a shell as it is.
    local words
    if [ "$1" = dc ]; then shift; words=" docker compose"; else words=""; fi
    printf -v words '%s%s' "$words" "$(printf ' %q' "$@")"
    say "DRYRUN:$words"
    return 0
  fi
  "$@"
}

# One value out of the env file, read the way start-stack.sh reads it. The file is
# compose's input and is never sourced (.env.example says why).
env_get() {
  local v
  v=$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true)
  v=${v%%[[:space:]]#*}
  v=${v#\"}
  v=${v%\"}
  v=${v#\'}
  v=${v%\'}
  printf '%s' "$v"
}

dc() {
  "$DOCKER" compose --project-name "$PROJECT" --project-directory "$REPO_DIR" \
    --env-file "$ENV_FILE" -f "$REPO_DIR/compose.yaml" "$@"
}

# 64 hex characters from the kernel's generator: no `$`, quotes or `#`, so the
# value means the same thing to compose's dotenv reader as it does here.
secret() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }

# --- 1. Docker -------------------------------------------------------------------
"$DOCKER" info >/dev/null 2>&1 || die "Docker is not answering. Start Docker (Docker Desktop, or the docker service) and run this again."
compose_version=$("$DOCKER" compose version --short 2>/dev/null || true)
case "$compose_version" in
  "" | 0.* | 1.*) die "needs the docker compose plugin, v2 or later (found '${compose_version:-none}')" ;;
esac

# --- One stack per project name --------------------------------------------------
# A compose project already holding containers belongs to the checkout that
# started it. Starting it from here would recreate those containers from this
# checkout, and with a new .env against a new, empty data root with new
# secrets: a working stack taken over. So a project that exists must have been
# started from this directory, and a first run (no .env yet) needs no project at all.
if [ -e "$ENV_FILE" ]; then
  project=$(env_get COMPOSE_PROJECT_NAME)
else
  project=routemaker
fi
if [ -n "$project" ]; then
  owners=$("$DOCKER" ps -a --filter "label=com.docker.compose.project=$project" \
    --format '{{.Label "com.docker.compose.project.working_dir"}}' 2>/dev/null | sort -u | sed '/^$/d' || true)
  if [ -n "$owners" ]; then
    if [ ! -e "$ENV_FILE" ]; then
      die "a stack named '$project' already exists (started from: $(echo "$owners" | paste -sd' ')), and there is no $ENV_FILE. Run scripts/local-up.sh from that checkout: writing a new .env here would take that stack over with new secrets and a new data root."
    fi
    while IFS= read -r owner; do
      [ "$owner" = "$REPO_DIR" ] || die "the stack '$project' was started from $owner, not $REPO_DIR. Run scripts/local-up.sh from there: from here it would rebuild that stack's images and republish its front end from this checkout."
    done <<<"$owners"
  fi
fi

# --- 2. .env ---------------------------------------------------------------------
if [ -e "$ENV_FILE" ]; then
  [ -z "$DATA_ROOT_ARG" ] || say "note: $ENV_FILE exists, so --data-root is ignored; DATA_ROOT comes from the file"
else
  data_root=${DATA_ROOT_ARG:-$HOME/rmdata}
  case "$data_root" in /?*) ;; *) die "--data-root must be an absolute path, not '$data_root'" ;; esac
  # It is written into .env unquoted and bound by compose and docker run: keep
  # to characters that mean the same thing to all three (and to sed, below).
  [[ "$data_root" =~ ^[A-Za-z0-9._/+-]+$ ]] || die "--data-root may hold only letters, digits and . _ / + - ('$data_root' has others)"
  say "$([ "$DRY_RUN" = 1 ] && echo "would write" || echo writing) $ENV_FILE (local plain-HTTP posture, DATA_ROOT=$data_root, fresh secrets)"
  if [ "$DRY_RUN" = 0 ]; then
    tmp="$ENV_FILE.tmp.$$"
    trap 'rm -f "$tmp"' EXIT
    # The values in .env.example are replaced where they stand, so the
    # reasoning above each one stays beside it; the lines it only describes in
    # comments are appended.
    sed -e "s|^DATA_ROOT=.*|DATA_ROOT=$data_root|" \
      -e 's|^CADDY_SITE_ADDRESS=.*|CADDY_SITE_ADDRESS=:80|' \
      -e 's|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1|' \
      -e 's|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1|' \
      -e 's|^DISCORD_REDIRECT_URI=.*|DISCORD_REDIRECT_URI=http://localhost/auth/callback|' \
      -e "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$(secret)|" \
      -e "s|^PGPASSWORD=.*|PGPASSWORD=$(secret)|" \
      -e "s|^KEY_ENCRYPTION_KEY=.*|KEY_ENCRYPTION_KEY=$(secret)|" \
      -e "s|^DISCORD_BOT_TOKEN=.*|DISCORD_BOT_TOKEN=$(secret)|" \
      -e "s|^BOT_INTERNAL_SECRET=.*|BOT_INTERNAL_SECRET=$(secret)|" \
      "$REPO_DIR/.env.example" >"$tmp"
    cat >>"$tmp" <<'EOF'

# Written by scripts/local-up.sh
# This computer only: plain HTTP on localhost, never a host reachable from
# outside (the local block above says why). Sign-in also needs DISCORD_CLIENT_ID
# and DISCORD_CLIENT_SECRET from a Discord application with
# http://localhost/auth/callback registered; the map works signed out without them.
DJANGO_DEBUG=1
COMPOSE_PROJECT_NAME=routemaker
RESTART_POLICY=no
EOF
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
    trap - EXIT
  fi
fi

if [ "$DRY_RUN" = 1 ] && [ ! -e "$ENV_FILE" ]; then
  # Nothing was written, so the rest of the dry run reads what would have been.
  DATA_ROOT=${DATA_ROOT_ARG:-$HOME/rmdata}
  PROJECT=routemaker
else
  DATA_ROOT=$(env_get DATA_ROOT)
  PROJECT=$(env_get COMPOSE_PROJECT_NAME)
  [ -n "$DATA_ROOT" ] || die "$ENV_FILE has no DATA_ROOT"
  [ -n "$PROJECT" ] || die "$ENV_FILE has no COMPOSE_PROJECT_NAME. Add COMPOSE_PROJECT_NAME=routemaker to it: without one, compose names the project after this directory and a checkout under another name is a second stack on the same data."
  [ "$PROJECT" = routemaker ] || die "$ENV_FILE names the stack '$PROJECT', not routemaker. This script starts only the local stack: it runs compose.yaml without any overlay and turns Docker's restart policy off, which would break a server stack such as the beta (docs/BETA-RUNBOOK.md). Nothing changed."
  case "$(env_get CADDY_SITE_ADDRESS)" in
    :80 | "") ;;
    *) say "note: CADDY_SITE_ADDRESS is '$(env_get CADDY_SITE_ADDRESS)', not :80; this .env is not the local posture, so http://localhost may not answer" ;;
  esac
fi
# Containers started from here on are not restarted by Docker at boot, before the
# data root is there (compose.yaml's header, rule on RESTART_POLICY): this script
# is what starts them.
export RESTART_POLICY=no

# --- 3. The data root ------------------------------------------------------------
if [ "$DRY_RUN" = 0 ]; then
  mkdir -p "$DATA_ROOT" 2>/dev/null || die "cannot create $DATA_ROOT; create it yourself (with room: about 50 GB once there is routing data) and run this again"
fi
# Only when a directory it makes is missing, or one it hands to the images' user
# (10001) is root's, as it is when `docker compose up` ran before it and Docker
# created the bind sources: its chowns are recursive, and on a stack with data
# that is a walk over every tile and elevation file for nothing. (Root's, not
# "not 10001's": under Docker Desktop's file sharing the chown is a no-op and the
# directories stay yours, which would rerun it every time.) The list is read
# from its DIRECTORIES block.
missing=""
for d in $(sed -n '/^DIRECTORIES="/,/^"/p' "$REPO_DIR/scripts/prepare_data_root.sh" | sed '1d;$d'); do
  [ -d "$DATA_ROOT/$d" ] || { missing=$d; break; }
done
if [ -z "$missing" ]; then
  for d in static basemap frontend tiles; do
    [ "$(stat -c %u "$DATA_ROOT/$d" 2>/dev/null)" != "$ROOT_UID" ] || { missing=$d; break; }
  done
fi
if [ -n "$missing" ]; then
  say "data root: preparing $DATA_ROOT"
  run "$DOCKER" run --rm --quiet -v "$DATA_ROOT:$DATA_ROOT" -v "$REPO_DIR/scripts/prepare_data_root.sh:/prepare_data_root.sh:ro" \
    -e "DATA_ROOT=$DATA_ROOT" "$BUSYBOX" sh /prepare_data_root.sh
else
  say "data root: ready"
fi

# --- 4. The base map -------------------------------------------------------------
if [ -f "$DATA_ROOT/basemap/region.pmtiles" ]; then
  say "base map: present"
else
  say "base map: fetching (about 300 MB)"
  run "$DOCKER" run --rm --quiet -u 10001:10001 -e "DATA_ROOT=$DATA_ROOT" \
    -v "$DATA_ROOT/basemap:$DATA_ROOT/basemap" \
    -v "$REPO_DIR/scripts/fetch_basemap.sh:/fetch_basemap.sh:ro" \
    --entrypoint sh "$CURL_IMAGE" /fetch_basemap.sh
fi

# --- 5. The front end ------------------------------------------------------------
# The stamp is git's tree id of frontend/ plus a mark when the working tree
# differs from it, so a rerun after an edit rebuilds and one after nothing does
# not. Without git to ask, it always rebuilds.
frontend_tree=$(git -C "$REPO_DIR" rev-parse HEAD:frontend 2>/dev/null || echo unknown)
if [ -n "$(git -C "$REPO_DIR" status --porcelain -- frontend 2>/dev/null)" ]; then
  frontend_tree="$frontend_tree+dirty"
fi
published=$(cat "$DATA_ROOT/frontend/.local-up-source" 2>/dev/null || true)
if [ -f "$DATA_ROOT/frontend/index.html" ] && [ "$published" = "$frontend_tree" ] &&
  [ "${frontend_tree%+dirty}" = "$frontend_tree" ] && [ "$frontend_tree" != unknown ]; then
  say "front end: current"
else
  say "front end: building and publishing"
  run "$DOCKER" run --rm --quiet -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$REPO_DIR/frontend:/app" -w /app \
    "$NODE" sh -c 'npm ci && npm run build'
  # The publish from docs/DEPLOYMENT.md, "The public front end" (keep the two in
  # step; this adds the stamp, and leaves `npm test` to CI): hashed assets first,
  # index.html last by a rename, so a page loaded mid-publish never names files
  # that are not there.
  run "$DOCKER" run --rm --quiet -u 10001:10001 \
    -v "$REPO_DIR/frontend/dist:/dist:ro" -v "$DATA_ROOT/frontend:/out" "$BUSYBOX" \
    sh -c 'mkdir -p /out/assets && cp -n /dist/assets/* /out/assets/ && cp /dist/favicon.svg /dist/licenses.txt /out/ && cp /dist/manifest.webmanifest /out/ && cp /dist/sw-kill.js /out/ && mkdir -p /out/icons && cp /dist/icons/apple-touch-icon.png /out/icons/ && cp /dist/icons/icon-192.png /out/icons/ && cp /dist/icons/icon-512.png /out/icons/ && cp /dist/icons/icon-maskable-192.png /out/icons/ && cp /dist/icons/icon-maskable-512.png /out/icons/ && mkdir -p /out/about && cp /dist/about/stress.html /out/about/.stress.html.new && mv /out/about/.stress.html.new /out/about/stress.html && cp /dist/sw.js /out/.sw.js.new && mv /out/.sw.js.new /out/sw.js && cp /dist/index.html /out/.index.html.new && mv /out/.index.html.new /out/index.html && echo "$1" >/out/.local-up-source' \
    sh "$frontend_tree"
fi

# --- 6. Images -------------------------------------------------------------------
if [ "$BUILD" = 1 ]; then
  say "images: building (cached; the first build takes minutes)"
  run dc build
fi

# --- 7. The stack ----------------------------------------------------------------
health() { "$CURL" -s -o /dev/null -m 10 -w '%{http_code}' "$BASE_URL/healthz" 2>/dev/null || true; }

if [ -f "$DATA_ROOT/tiles/standard/current/tiles.tar" ]; then
  say "routing data found: starting through scripts/boot/start-stack.sh"
  boot_args=(${STACK_ARGS[@]+"${STACK_ARGS[@]}"})
  [ "$DRY_RUN" = 1 ] && boot_args+=(--dry-run)
  rc=0
  BOOT_ENV_FILE="$ENV_FILE" BOOT_DOCKER="$DOCKER" BOOT_CURL="$CURL" BOOT_BASE_URL="$BASE_URL" \
    BOOT_DATA_ROOT="$DATA_ROOT" "$START_STACK" ${boot_args[@]+"${boot_args[@]}"} || rc=$?
  [ "$rc" = 0 ] || { warn "start-stack.sh exited $rc; it printed why above, and its log is under ${BOOT_LOG_DIR:-$HOME/rmdata/boot}"; exit "$rc"; }
  HAVE_DATA=1
else
  [ "${#STACK_ARGS[@]}" = 0 ] || say "note: no routing data yet, so the arguments after -- (for start-stack.sh) are not used"
  say "no routing data yet: starting ${FIRST_RUN_SERVICES[*]} (the routers wait for the first rebuild)"
  services=("${FIRST_RUN_SERVICES[@]}")
  # The first rebuild runs for hours with no tiles.tar to show for it until it
  # promotes, and recreating the rebuild container kills it (compose.yaml,
  # rebuild). So a running rebuild container is left alone, as start-stack.sh
  # leaves it unless told otherwise; nothing depends on it, and the rest are
  # started, and recreated where their image or .env changed, as usual.
  if [ -n "$("$DOCKER" ps -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter label=com.docker.compose.service=rebuild --filter status=running 2>/dev/null || true)" ]; then
    say "note: the rebuild container is running and is left as it is, so a rebuild in progress carries on"
    services=()
    for svc in "${FIRST_RUN_SERVICES[@]}"; do [ "$svc" = rebuild ] || services+=("$svc"); done
  fi
  run dc up -d --no-build "${services[@]}"
  if [ "$DRY_RUN" = 0 ]; then
    say "waiting up to ${HEALTHY_S}s for $BASE_URL/healthz"
    waited=0
    said=0
    until [ "$(health)" = 200 ]; do
      if [ "$waited" -ge "$HEALTHY_S" ]; then
        warn "the stack started but $BASE_URL/healthz has not answered 200 in ${HEALTHY_S}s."
        warn "Look at: docker compose --project-name $PROJECT --env-file $ENV_FILE ps -a"
        warn "and then: docker compose --project-name $PROJECT --env-file $ENV_FILE logs migrate api caddy"
        exit 2
      fi
      sleep "$POLL_S"
      waited=$((waited + POLL_S))
      if [ $((waited - said)) -ge 30 ]; then
        say "still waiting for $BASE_URL/healthz (${waited}s)"
        said=$waited
      fi
    done
  fi
  HAVE_DATA=0
fi

# --- 8. Static files, and what next ---------------------------------------------
run dc exec -T api ./manage.py collectstatic --noinput

if [ "$DRY_RUN" = 1 ]; then
  say "dry run: nothing was written, built or started"
  exit 0
fi
say "up: $BASE_URL"
if [ "$HAVE_DATA" = 0 ]; then
  cat <<EOF
local-up: The map, the admin and /healthz work now.
local-up: Routes and the stress overlay need routing data, which comes from the first rebuild: python3 scripts/acceptance.py --only A4
local-up: docs/PLAYBOOK.md section 7 walks through it; it pauses once for the three reference files, then builds for hours.
local-up: Once it has promoted a build, run scripts/local-up.sh again and it starts the routers too.
local-up: Place search needs a Photon index as well: docs/DEPLOYMENT.md, "Photon".
EOF
fi
