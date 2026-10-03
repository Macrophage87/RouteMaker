#!/usr/bin/env bash
# Start the RouteMaker stack safely after a Windows reboot (Docker Desktop + WSL).
#
# THE PROBLEM. Docker Desktop restarts containers at boot before the WSL distro
# that owns ${DATA_ROOT} is up. postgis then initialises an empty cluster on a
# phantom bind path, and caddy, the routers, rebuild and photon fail their binds.
# This script is the ordered, checked replacement for the manual recovery:
#
#   1. wait (bounded) for Docker to answer and for ${DATA_ROOT} and every bind
#      directory to exist, and Docker can see the real postgres cluster (PG_VERSION);
#   2. decide COLD or WARM. WARM = postgis is running, healthy and sane: only
#      services that are not running are started, nothing is recreated, so it is
#      safe to run by hand on a live stack. COLD = anything else;
#   3. COLD: stop api, worker and rebuild, `up -d --no-deps --force-recreate`
#      postgis, wait for healthy, then require migrations >= BOOT_EXPECT_MIGRATIONS
#      (68) and live.segment rows >= BOOT_MIN_SEGMENTS (about 1.36M live). If not,
#      that is the bind-race signature: stop postgis, ABORT LOUDLY, start nothing
#      else. Before postgis starts, a throwaway container must see
#      postgres/PG_VERSION, so an empty path is never initialised by this script;
#   4. start caddy, the four routers, api, worker, rebuild, photon, in that order,
#      each with `up -d --no-deps` (plus --force-recreate when COLD);
#   5. smoke-check route, geocode and a stress tile: all must return 200.
#
# RULES. Never a plain `docker compose up -d` (it would also run `migrate` and
# recreate on any config drift). Never touches Docker Desktop or WSL. No sudo.
# Every compose call names the repo's .env explicitly: compose run from a
# checkout with no .env renders DATA_ROOT as "" and would bind the wrong paths.
#
# Usage: start-stack.sh [--dry-run] [--force-recreate-all] [--help]
#   --dry-run             read-only probes run; mutating docker commands are
#                         printed as "DRYRUN:" and skipped; no waits after them.
#   --force-recreate-all  WARM path too recreates every service (restarts a
#                         running rebuild; use only on purpose).
# Environment (all optional): ROUTEMAKER_DIR, BOOT_ENV_FILE, BOOT_LOG_DIR,
#   BOOT_DOCKER, BOOT_CURL, BOOT_BASE_URL, BOOT_POLL_S, BOOT_WAIT_PREREQ_S (600),
#   BOOT_POSTGIS_HEALTHY_S (300), BOOT_SMOKE_S (300), BOOT_EXPECT_MIGRATIONS (68),
#   BOOT_MIN_SEGMENTS (1000000), BOOT_DATA_ROOT, COMPOSE_PROJECT (routemaker).
# Exit: 0 ok; 1 aborted before the stack was started (or prereq timeout);
#       2 started but a smoke check failed.

set -Eeuo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
# Containers created from here on must not be auto-started by Docker at boot.
export RESTART_POLICY=no

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=${ROUTEMAKER_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}
ENV_FILE=${BOOT_ENV_FILE:-$REPO_DIR/.env}
LOG_DIR=${BOOT_LOG_DIR:-/home/steph/rmdata/boot}
DOCKER=${BOOT_DOCKER:-docker}
CURL=${BOOT_CURL:-curl}
BASE_URL=${BOOT_BASE_URL:-http://localhost}
POLL_S=${BOOT_POLL_S:-5}
WAIT_PREREQ_S=${BOOT_WAIT_PREREQ_S:-600}
POSTGIS_HEALTHY_S=${BOOT_POSTGIS_HEALTHY_S:-300}
SMOKE_S=${BOOT_SMOKE_S:-300}
EXPECT_MIGRATIONS=${BOOT_EXPECT_MIGRATIONS:-68}
MIN_SEGMENTS=${BOOT_MIN_SEGMENTS:-1000000}

# Every directory compose binds under ${DATA_ROOT}. tests/test_boot_scripts.py
# fails if compose.yaml binds one that is not listed here.
REQUIRED_DIRS=(backups basemap caddy elevation extracts frontend photon postgres
  rebuild reference static tiles tiles/standard tiles/no-trail tiles/ebike tiles/weekend)
# Start order after postgis. migrate is deliberately absent (one-shot, already run).
START_ORDER=(caddy valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
  api worker rebuild photon)
# Services that hold database connections; stopped first on the COLD path.
DB_CLIENTS=(api worker rebuild)

DRY_RUN=0
FORCE_ALL=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --force-recreate-all) FORCE_ALL=1 ;;
    -h | --help)
      sed -n '2,/^set -E/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown argument: $arg (try --help)" >&2
      exit 64
      ;;
  esac
done

mkdir -p "$LOG_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SUFFIX=""
[ "$DRY_RUN" = 1 ] && SUFFIX="-dryrun"
LOG_FILE="$LOG_DIR/start-stack-$STAMP$SUFFIX.log"
: >>"$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1
ln -sf "$LOG_FILE" "$LOG_DIR/latest.log"
# Keep the 30 newest logs. Housekeeping must never stop a boot: no match makes
# `ls` exit 2, which pipefail would turn into a silent errexit.
# shellcheck disable=SC2012
{ ls -1t "$LOG_DIR"/start-stack-*.log 2>/dev/null | tail -n +31 | xargs -r rm -f --; } || true

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
status() {
  [ "$DRY_RUN" = 1 ] || printf '%s %s %s\n' "$1" "$(date -u +%FT%TZ)" "${2:-}" >"$LOG_DIR/last-status"
}
die() {
  local code=${2:-1}
  log "################################################################"
  log "# ROUTEMAKER BOOT ABORTED: $1"
  log "# Log: $LOG_FILE"
  log "################################################################"
  status FAILED "$1"
  exit "$code"
}
trap 'die "unexpected error at line $LINENO (command: $BASH_COMMAND)"' ERR

# Compose, always with the repo's own .env and the fixed project name.
dc() {
  "$DOCKER" compose --project-name "${COMPOSE_PROJECT:-routemaker}" \
    --project-directory "$REPO_DIR" --env-file "$ENV_FILE" \
    -f "$REPO_DIR/compose.yaml" "$@" </dev/null
}
# Mutating compose call: skipped under --dry-run.
mutate() {
  if [ "$DRY_RUN" = 1 ]; then
    log "DRYRUN: docker compose $*"
    return 0
  fi
  log "+ docker compose $*"
  dc "$@"
}

# env_get NAME [DEFAULT]: read one value from .env without sourcing it.
env_get() {
  local v
  v=$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true)
  v=${v%%[[:space:]]#*}
  v=${v#\"}
  v=${v%\"}
  printf '%s' "${v:-${2:-}}"
}

# wait_until SECONDS CMD...: poll CMD until it succeeds or the time is up.
wait_until() {
  local end=$((SECONDS + $1))
  shift
  until "$@"; do
    if ((SECONDS >= end)); then return 1; fi
    sleep "$POLL_S"
  done
}

docker_answers() { timeout 60 "$DOCKER" info >/dev/null 2>&1; }
missing_dirs() {
  local d
  for d in "${REQUIRED_DIRS[@]}"; do
    [ -d "$DATA_ROOT/$d" ] || printf '%s ' "$DATA_ROOT/$d"
  done
}
paths_exist() { [ -z "$(missing_dirs)" ]; }

# postgres/ is owned by uid 999 and mode 0700, so this user cannot look inside it.
# Ask Docker instead, which is also the view that matters: a throwaway container
# (the postgis image already on the host, no pull, no network) binds the same path
# read-only and looks for PG_VERSION. A phantom (not yet mounted) path has none.
postgis_image() { dc config --images 2>/dev/null | grep -m1 'postgis' || true; }
postgres_visible_to_docker() {
  local image
  image=$(postgis_image)
  [ -n "$image" ] || { log "cannot find the postgis image name in compose config"; return 1; }
  timeout 120 "$DOCKER" run --rm --pull never --network none --entrypoint test     -v "$DATA_ROOT/postgres:/pgcheck:ro" "$image" -f /pgcheck/PG_VERSION </dev/null >/dev/null 2>&1
}

# "service state health" lines for every container of the project.
SNAPSHOT=""
snapshot() { SNAPSHOT=$(dc ps --all --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null || true); }
svc_state() { awk -v s="$1" '$1 == s { print $2; exit }' <<<"$SNAPSHOT"; }
svc_health() { awk -v s="$1" '$1 == s { print $3; exit }' <<<"$SNAPSHOT"; }
is_running() { [ "$(svc_state "$1")" = running ]; }
postgis_healthy() {
  snapshot
  is_running postgis && [ "$(svc_health postgis)" = healthy ]
}

# Prints "MIGRATIONS SEGMENTS". Non-zero if postgis cannot answer (an empty
# cluster has no django_migrations or live.segment, so that lands here too).
db_numbers() {
  local out
  out=$(dc exec -T postgis psql -X -q -At -F ' ' \
    -U "$PGUSER" -d "$PGDATABASE" \
    -c "select (select count(*) from django_migrations), (select count(*) from live.segment)" 2>&1) || {
    log "psql failed: $(head -c 300 <<<"$out" | tr '\n' ' ')"
    return 1
  }
  if ! [[ "$out" =~ ^[0-9]+\ [0-9]+$ ]]; then
    log "unparseable psql output: $out"
    return 1
  fi
  printf '%s' "$out"
}
# 0 = sane. Logs the numbers either way.
db_sane() {
  local nums mig seg
  nums=$(db_numbers) || return 1
  read -r mig seg <<<"$nums"
  log "postgis: migrations=$mig (expect >= $EXPECT_MIGRATIONS), live.segment=$seg (expect >= $MIN_SEGMENTS)"
  [ "$mig" -ge "$EXPECT_MIGRATIONS" ] && [ "$seg" -ge "$MIN_SEGMENTS" ]
}

# ---------------------------------------------------------------- start
log "start-stack: repo=$REPO_DIR dry_run=$DRY_RUN force_all=$FORCE_ALL log=$LOG_FILE"
[ -f "$REPO_DIR/compose.yaml" ] || die "no compose.yaml in $REPO_DIR"
[ -f "$ENV_FILE" ] || die "no env file at $ENV_FILE (compose without it renders a blank DATA_ROOT)"
DATA_ROOT=${BOOT_DATA_ROOT:-$(env_get DATA_ROOT)}
[ -n "$DATA_ROOT" ] || die "DATA_ROOT is not set in $ENV_FILE"
PGUSER=$(env_get PGUSER routemaker)
PGDATABASE=$(env_get PGDATABASE routemaker)
log "DATA_ROOT=$DATA_ROOT project=${COMPOSE_PROJECT:-routemaker}"
if ! grep -Eq '^[[:space:]]*RESTART_POLICY=no' "$ENV_FILE"; then
  log "WARN: $ENV_FILE has no RESTART_POLICY=no. This script's containers get restart=no anyway, but a later plain 'docker compose up' would recreate them with unless-stopped and bring the boot race back. Add the line."
fi

exec 9>"$LOG_DIR/.lock"
flock -n 9 || die "another start-stack.sh is already running"

log "waiting up to ${WAIT_PREREQ_S}s for Docker to answer"
wait_until "$WAIT_PREREQ_S" docker_answers || die "Docker did not answer within ${WAIT_PREREQ_S}s (not resetting Docker Desktop; start it and rerun)"
log "waiting up to ${WAIT_PREREQ_S}s for bind paths under $DATA_ROOT"
wait_until "$WAIT_PREREQ_S" paths_exist || die "bind paths still missing after ${WAIT_PREREQ_S}s: $(missing_dirs)"
log "docker answers; all ${#REQUIRED_DIRS[@]} bind dirs exist"

snapshot
log "current state: $(tr '\n' ';' <<<"$SNAPSHOT")"

MODE=COLD
if postgis_healthy && db_sane; then MODE=WARM; fi
log "mode: $MODE"

if [ "$MODE" = COLD ]; then
  if is_running postgis; then
    log "postgis is running but not healthy or not sane: bind-race signature; recreating it"
  fi
  log "stopping database clients: ${DB_CLIENTS[*]}"
  mutate stop "${DB_CLIENTS[@]}"
  # Never let postgis initdb an empty directory: Docker must see a real cluster.
  log "checking that Docker sees a real cluster at $DATA_ROOT/postgres (PG_VERSION)"
  wait_until "$WAIT_PREREQ_S" postgres_visible_to_docker ||
    die "Docker cannot see $DATA_ROOT/postgres/PG_VERSION after ${WAIT_PREREQ_S}s (phantom or empty bind path); postgis NOT started"
  mutate up -d --no-deps --force-recreate postgis
  if [ "$DRY_RUN" = 0 ]; then
    log "waiting up to ${POSTGIS_HEALTHY_S}s for postgis healthy"
    if ! wait_until "$POSTGIS_HEALTHY_S" postgis_healthy; then
      mutate stop postgis || true
      die "postgis not healthy within ${POSTGIS_HEALTHY_S}s; NOT starting the rest"
    fi
    if ! db_sane; then
      mutate stop postgis || true
      die "postgis is up but EMPTY or short (bind-race signature: migrations or segments below expectation). Rest of the stack NOT started; postgis stopped. Check ls $DATA_ROOT/postgres and the Docker Desktop WSL integration, then rerun."
    fi
    log "postgis verified"
  else
    log "DRYRUN: would wait for postgis healthy and verify migrations and segments"
  fi
fi

for svc in "${START_ORDER[@]}"; do
  if [ "$MODE" = COLD ] || [ "$FORCE_ALL" = 1 ]; then
    mutate up -d --no-deps --force-recreate "$svc"
  elif is_running "$svc"; then
    log "$svc already running; left alone"
  else
    mutate up -d --no-deps "$svc"
  fi
done

# ---------------------------------------------------------------- smoke
ROUTE_BODY='{"points":[[-77.0311,38.9937],[-77.0390,38.9020]],"preset":"default","when":"weekday_offpeak"}'
http_code() { "$CURL" -s -o /dev/null -w '%{http_code}' --max-time 90 "$@" 2>/dev/null || true; }
SMOKE_RESULT=""
smoke_once() {
  local r g t
  r=$(http_code -X POST "$BASE_URL/api/route" -H 'Content-Type: application/json' -d "$ROUTE_BODY")
  g=$(http_code "$BASE_URL/api/geocode?q=Dupont%20Circle")
  t=$(http_code "$BASE_URL/tiles/stress/11/585/783.pbf")
  SMOKE_RESULT="route=$r geocode=$g tile=$t"
  [ "$r" = 200 ] && [ "$g" = 200 ] && [ "$t" = 200 ]
}
if [ "$DRY_RUN" = 1 ]; then
  log "DRYRUN: would smoke-check route, geocode and tile (up to ${SMOKE_S}s)"
  log "dry run complete"
  exit 0
fi
log "smoke checks (up to ${SMOKE_S}s): route, geocode, tile"
if ! wait_until "$SMOKE_S" smoke_once; then
  die "stack started but smoke checks failed: $SMOKE_RESULT (see docker compose ps and logs)" 2
fi
log "smoke ok: $SMOKE_RESULT"
status OK "mode=$MODE"
log "start-stack finished OK"
