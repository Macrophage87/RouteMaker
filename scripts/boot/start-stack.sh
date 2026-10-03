#!/usr/bin/env bash
# Start the RouteMaker stack safely after a Windows reboot (Docker Desktop + WSL).
#
# THE PROBLEM. Docker Desktop restarts containers at boot before the WSL distro
# that owns ${DATA_ROOT} is up. postgis then initialises an empty cluster on a
# phantom bind path, and caddy, the routers, rebuild and photon fail their binds.
# This script is the ordered, checked replacement for the manual recovery:
#
#   1. wait (bounded, one shared budget) for Docker to answer and for every bind
#      directory under ${DATA_ROOT} to exist;
#   2. decide COLD or WARM. WARM = postgis is running, healthy and sane (sanity is
#      retried 3 times over about 30 s before it is believed to fail): only
#      services that are not running are started, nothing is recreated. COLD =
#      anything else. COLD is refused while rebuild is running, unless
#      --force-recreate-all is given;
#   3. COLD: inside the same budget, a throwaway read-only container must read
#      back a fresh random token this run wrote to ${DATA_ROOT}/.boot-token (a
#      phantom view of the path cannot hold it) and must see postgres/PG_VERSION.
#      Only then: stop api, worker and rebuild, `up -d --no-deps --force-recreate`
#      postgis, wait for healthy, and require migrations >= BOOT_EXPECT_MIGRATIONS
#      (68) and live.segment rows >= BOOT_MIN_SEGMENTS (about 1.36M live). If not,
#      that is the bind-race signature: stop postgis, ABORT LOUDLY, start nothing
#      else;
#   4. start caddy, the four routers, api, worker, rebuild, photon, in that order,
#      each with `up -d --no-deps` (plus --force-recreate when COLD);
#   5. smoke-check route, geocode and a stress tile: all must return 200, and the
#      tile must not be empty.
#
# RULES. Never a plain `docker compose up -d` (it would also run `migrate` and
# recreate on any config drift). Never touches Docker Desktop or WSL. No sudo.
# Every compose call names the repo's .env and the COMPOSE_PROJECT_NAME it sets:
# compose run from a checkout with no .env renders DATA_ROOT as "" and would
# bind the wrong paths, and a second project name would be a second stack.
#
# Usage: start-stack.sh [--dry-run] [--warm-only | --force-recreate-all] [--help]
#   --dry-run             read-only probes run; mutating docker commands are
#                         printed as "DRYRUN:" and skipped; no waits after them;
#                         no status is written and no token is written.
#   --warm-only           for a periodic watchdog: never takes the COLD path.
#                         If postgis is running, healthy and sane, start the
#                         services that are stopped; otherwise exit 3 and
#                         change nothing.
#   --force-recreate-all  recreate every service even when WARM, and allow COLD
#                         while rebuild is running (kills a running rebuild;
#                         use only on purpose).
# Environment (all optional): ROUTEMAKER_DIR, BOOT_ENV_FILE, BOOT_LOG_DIR,
#   BOOT_DOCKER, BOOT_CURL, BOOT_BASE_URL, BOOT_POLL_S, BOOT_WAIT_PREREQ_S (900,
#   shared by the Docker, path and bind checks), BOOT_POSTGIS_HEALTHY_S (300),
#   BOOT_SMOKE_S (300), BOOT_SANE_TRIES (3), BOOT_SANE_GAP_S (15),
#   BOOT_COMPOSE_TIMEOUT_S (120, per mutating compose call), BOOT_EXEC_TIMEOUT_S (60),
#   BOOT_EXPECT_MIGRATIONS (68), BOOT_MIN_SEGMENTS (1000000), BOOT_DATA_ROOT,
#   COMPOSE_PROJECT (must equal COMPOSE_PROJECT_NAME in .env if set).
# Exit: 0 ok; 1 aborted before the stack was started (or prereq timeout, or a
#       concurrent run, or refused COLD); 2 started but a smoke check failed;
#       3 --warm-only and the stack is not warm; 64 bad arguments; 143 SIGTERM.

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
WAIT_PREREQ_S=${BOOT_WAIT_PREREQ_S:-900}
POSTGIS_HEALTHY_S=${BOOT_POSTGIS_HEALTHY_S:-300}
SMOKE_S=${BOOT_SMOKE_S:-300}
SANE_TRIES=${BOOT_SANE_TRIES:-3}
SANE_GAP_S=${BOOT_SANE_GAP_S:-15}
COMPOSE_TIMEOUT_S=${BOOT_COMPOSE_TIMEOUT_S:-120}
EXEC_TIMEOUT_S=${BOOT_EXEC_TIMEOUT_S:-60}
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
WARM_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --force-recreate-all) FORCE_ALL=1 ;;
    --warm-only) WARM_ONLY=1 ;;
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
if [ "$WARM_ONLY" = 1 ] && [ "$FORCE_ALL" = 1 ]; then
  echo "--warm-only and --force-recreate-all contradict each other" >&2
  exit 64
fi

# The lock comes before anything is written: a refused concurrent run must not
# touch last-status or latest.log, which belong to the run that holds it.
mkdir -p "$LOG_DIR"
exec 9>"$LOG_DIR/.lock"
if ! flock -n 9; then
  printf '%s start-stack.sh: another run holds %s; refused, nothing written\n' \
    "$(date -u +%FT%TZ)" "$LOG_DIR/.lock"
  exit 1
fi

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
FINAL_STATUS=0
status() {
  [ "$1" = RUNNING ] || FINAL_STATUS=1
  [ "$DRY_RUN" = 1 ] || printf '%s %s %s\n' "$1" "$(date -u +%FT%TZ)" "${2:-}" >"$LOG_DIR/last-status"
}
die() {
  local code=${2:-1}
  # Status first: under a systemd stop, tee may already be gone and a write to
  # the log could be the last thing this shell does.
  status FAILED "$1"
  log "################################################################"
  log "# ROUTEMAKER BOOT ABORTED: $1"
  log "# Log: $LOG_FILE"
  log "################################################################"
  exit "$code"
}
trap 'die "unexpected error at line $LINENO (command: $BASH_COMMAND)"' ERR
trap 'die "terminated by SIGTERM (systemd TimeoutStartSec or a stop)" 143' TERM
trap 'die "interrupted (SIGINT)" 130' INT
# Any other non-zero exit that did not record an outcome must not leave RUNNING.
trap 'rc=$?; if [ "$rc" != 0 ] && [ "$FINAL_STATUS" = 0 ]; then status FAILED "exit $rc"; fi' EXIT
status RUNNING "pid=$$"

# env_get NAME [DEFAULT]: read one value from .env without sourcing it.
env_get() {
  local v
  v=$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true)
  v=${v%%[[:space:]]#*}
  v=${v#\"}
  v=${v%\"}
  v=${v#\'}
  v=${v%\'}
  printf '%s' "${v:-${2:-}}"
}

# Compose, always with the repo's own .env and its project name. Every call is
# bounded: DC_T overrides the timeout for one call (`DC_T=30 dc ps`).
dc() {
  timeout "${DC_T:-$COMPOSE_TIMEOUT_S}" "$DOCKER" compose --project-name "$PROJECT" \
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

# The shared prerequisite deadline (Docker, paths, bind checks).
PREREQ_END=$((SECONDS + WAIT_PREREQ_S))
prereq_left() { local l=$((PREREQ_END - SECONDS)); ((l > 0)) || l=0; printf '%s' "$l"; }

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

# Docker's view of ${DATA_ROOT} must be the real one before postgis is started.
# 1. A token written by this run seconds ago, read back through a bind by a
#    throwaway container (the postgis image already on the host, no pull, no
#    network, read-only). A phantom view of the path, even one that holds an
#    old cluster from an earlier race, cannot contain it.
# 2. postgres/ (uid 999, mode 0700, so this user cannot look inside it) must
#    hold PG_VERSION as a file, through the very bind postgis uses.
TOKEN_FILE=".boot-token"
BOOT_TOKEN=""
postgis_image() { DC_T=60 dc config --images 2>/dev/null | grep -m1 'postgis' || true; }
bind_is_real() {
  local image seen
  image=$(postgis_image)
  [ -n "$image" ] || { log "cannot find the postgis image name in compose config"; return 1; }
  if [ -n "$BOOT_TOKEN" ]; then
    seen=$(timeout 60 "$DOCKER" run --rm --pull never --network none --entrypoint cat \
      -v "$DATA_ROOT:/bootcheck:ro" "$image" "/bootcheck/$TOKEN_FILE" </dev/null 2>/dev/null) || seen=""
    if [ "$seen" != "$BOOT_TOKEN" ]; then
      log "Docker's view of $DATA_ROOT does not hold this run's token (phantom or stale bind path)"
      return 1
    fi
  fi
  if ! timeout 60 "$DOCKER" run --rm --pull never --network none --entrypoint test \
    -v "$DATA_ROOT/postgres:/pgcheck:ro" "$image" -f /pgcheck/PG_VERSION </dev/null >/dev/null 2>&1; then
    log "Docker sees no postgres/PG_VERSION file under $DATA_ROOT"
    return 1
  fi
}

# "service state health" lines for every container of the project.
SNAPSHOT=""
snapshot() { SNAPSHOT=$(DC_T=30 dc ps --all --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null || true); }
svc_state() { awk -v s="$1" '$1 == s { print $2; exit }' <<<"$SNAPSHOT"; }
svc_health() { awk -v s="$1" '$1 == s { print $3; exit }' <<<"$SNAPSHOT"; }
is_running() { [ "$(svc_state "$1")" = running ]; }
postgis_healthy() {
  snapshot
  is_running postgis && [ "$(svc_health postgis)" = healthy ]
}

# Prints "MIGRATIONS SEGMENTS" (diagnostics go to stderr, which is logged too). Non-zero if postgis cannot answer within the exec timeout
# (an empty cluster has no django_migrations or live.segment, so that lands here).
db_numbers() {
  local out
  out=$(DC_T=$EXEC_TIMEOUT_S dc exec -T postgis psql -X -q -At -F ' ' \
    -U "$PGUSER" -d "$PGDATABASE" \
    -c "select (select count(*) from django_migrations), (select count(*) from live.segment)" 2>&1) || {
    log "psql failed: $(head -c 300 <<<"$out" | tr '\n' ' ')" >&2
    return 1
  }
  if ! [[ "$out" =~ ^[0-9]+\ [0-9]+$ ]]; then
    log "unparseable psql output: $out" >&2
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
# A running, healthy postgis is asked up to SANE_TRIES times, so one failed exec
# under memory pressure does not send a live stack down the COLD path.
db_sane_retried() {
  local i
  for ((i = 1; i <= SANE_TRIES; i++)); do
    db_sane && return 0
    if ((i < SANE_TRIES)); then
      log "postgis sanity check failed (try $i of $SANE_TRIES); retrying in ${SANE_GAP_S}s"
      sleep "$SANE_GAP_S"
    fi
  done
  return 1
}

# ---------------------------------------------------------------- start
log "start-stack: repo=$REPO_DIR dry_run=$DRY_RUN warm_only=$WARM_ONLY force_all=$FORCE_ALL log=$LOG_FILE"
[ -f "$REPO_DIR/compose.yaml" ] || die "no compose.yaml in $REPO_DIR"
[ -f "$ENV_FILE" ] || die "no env file at $ENV_FILE (compose without it renders a blank DATA_ROOT)"
PROJECT=$(env_get COMPOSE_PROJECT_NAME)
[ -n "$PROJECT" ] || die "COMPOSE_PROJECT_NAME is not set in $ENV_FILE; plain compose would then name the project after the directory, a second stack on the same DATA_ROOT"
if [ -n "${COMPOSE_PROJECT:-}" ] && [ "$COMPOSE_PROJECT" != "$PROJECT" ]; then
  die "COMPOSE_PROJECT=$COMPOSE_PROJECT but $ENV_FILE says COMPOSE_PROJECT_NAME=$PROJECT; refusing to start a second stack"
fi
if [ -n "${COMPOSE_PROJECT_NAME:-}" ] && [ "$COMPOSE_PROJECT_NAME" != "$PROJECT" ]; then
  die "the environment has COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME but $ENV_FILE says $PROJECT; refusing to start a second stack"
fi
DATA_ROOT=${BOOT_DATA_ROOT:-$(env_get DATA_ROOT)}
[ -n "$DATA_ROOT" ] || die "DATA_ROOT is not set in $ENV_FILE"
PGUSER=$(env_get PGUSER routemaker)
PGDATABASE=$(env_get PGDATABASE routemaker)
log "DATA_ROOT=$DATA_ROOT project=$PROJECT"
if ! grep -Eq '^[[:space:]]*RESTART_POLICY=no' "$ENV_FILE"; then
  log "WARN: $ENV_FILE has no RESTART_POLICY=no. This script's containers get restart=no anyway, but a later plain 'docker compose up' would recreate them with unless-stopped and bring the boot race back. Add the line."
fi

log "waiting up to ${WAIT_PREREQ_S}s in all for Docker, the bind paths and (COLD) the bind check"
wait_until "$(prereq_left)" docker_answers || die "Docker did not answer within ${WAIT_PREREQ_S}s (not resetting Docker Desktop; start it and rerun)"
wait_until "$(prereq_left)" paths_exist || die "bind paths still missing after ${WAIT_PREREQ_S}s: $(missing_dirs)"
log "docker answers; all ${#REQUIRED_DIRS[@]} bind dirs exist"

snapshot
log "current state: $(tr '\n' ';' <<<"$SNAPSHOT")"

MODE=COLD
if postgis_healthy && db_sane_retried; then MODE=WARM; fi
log "mode: $MODE"

if [ "$MODE" = COLD ] && [ "$WARM_ONLY" = 1 ]; then
  log "--warm-only: postgis is not running, healthy and sane, and this mode never takes the COLD path; nothing changed"
  die "not warm (--warm-only); run scripts/boot/start-stack.sh by hand to recover" 3
fi
if [ "$MODE" = COLD ] && [ "$FORCE_ALL" = 0 ] && is_running rebuild; then
  die "COLD path refused: rebuild is running and COLD would stop it. Nothing changed. Rerun with --force-recreate-all to do it anyway."
fi

if [ "$MODE" = COLD ]; then
  if is_running postgis; then
    log "postgis is running but not healthy or not sane: bind-race signature; recreating it"
  fi
  # Never let postgis initdb an empty or phantom directory: Docker must see the
  # real path first. Checked before anything is stopped.
  if [ "$DRY_RUN" = 1 ]; then
    log "DRYRUN: would write a fresh token to $DATA_ROOT/$TOKEN_FILE and read it back through a bind"
  else
    BOOT_TOKEN=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
    printf '%s' "$BOOT_TOKEN" >"$DATA_ROOT/$TOKEN_FILE" || die "cannot write $DATA_ROOT/$TOKEN_FILE"
  fi
  log "checking that Docker sees the real $DATA_ROOT (token) and a cluster (postgres/PG_VERSION)"
  wait_until "$(prereq_left)" bind_is_real ||
    die "Docker's view of $DATA_ROOT is not the real one after ${WAIT_PREREQ_S}s (phantom or empty bind path); nothing stopped, postgis NOT started"
  log "stopping database clients: ${DB_CLIENTS[*]}"
  mutate stop "${DB_CLIENTS[@]}"
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
# probe ARGS...: prints "HTTP_CODE BYTES".
probe() { "$CURL" -s -o /dev/null -w '%{http_code} %{size_download}' --max-time 90 "$@" 2>/dev/null || true; }
SMOKE_RESULT=""
smoke_once() {
  local rc gc tc tsize _
  read -r rc _ <<<"$(probe -X POST "$BASE_URL/api/route" -H 'Content-Type: application/json' -d "$ROUTE_BODY")"
  read -r gc _ <<<"$(probe "$BASE_URL/api/geocode?q=Dupont%20Circle")"
  read -r tc tsize <<<"$(probe "$BASE_URL/tiles/stress/11/585/783.pbf")"
  SMOKE_RESULT="route=$rc geocode=$gc tile=$tc (${tsize:-?} bytes)"
  [ "$rc" = 200 ] && [ "$gc" = 200 ] && [ "$tc" = 200 ] &&
    [[ "${tsize:-}" =~ ^[0-9]+$ ]] && ((tsize > 0))
}
if [ "$DRY_RUN" = 1 ]; then
  log "DRYRUN: would smoke-check route, geocode and tile (up to ${SMOKE_S}s)"
  log "dry run complete (mode $MODE)"
  exit 0
fi
log "smoke checks (up to ${SMOKE_S}s): route, geocode, tile"
if ! wait_until "$SMOKE_S" smoke_once; then
  die "stack started but smoke checks failed: $SMOKE_RESULT (see docker compose ps and logs)" 2
fi
log "smoke ok: $SMOKE_RESULT"
if [ "$WARM_ONLY" = 1 ]; then status OK "mode=WARM-ONLY"; else status OK "mode=$MODE"; fi
log "start-stack finished OK"
