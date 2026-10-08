#!/usr/bin/env bash
# The beta's release agent: continuous deployment, pulled by the server (OWNER-DECISIONS 431;
# docs/BETA-RUNBOOK.md, "Continuous deployment"). It runs ON the beta server as the beta's login
# user (in the docker group, no sudo), from a systemd --user timer about every 10 minutes.
#
#   auto-release.sh run [--dry-run]   one pass: look for a new release tag and deploy it
#   auto-release.sh status            what is deployed, the last run's result, what is held
#   auto-release.sh install [--deployed-tag vX.Y.Z] [--report-url URL|none] [--no-enable]
#                                     one-time setup (and upgrade): copies the agent into
#                                     $RM_STATE/cd/bin, writes the systemd --user units, enables the timer
#   auto-release.sh uninstall         stop and remove the timer and units (keeps $RM_STATE/cd)
#   auto-release.sh pause [REASON] | resume
#   auto-release.sh mark-deployed vX.Y.Z   after a release shipped by hand (the runbook), or to
#                                     clear a BROKEN state once the owner has looked
#   auto-release.sh retry vX.Y.Z      allow a held or failed tag to be tried again
#   auto-release.sh hold vX.Y.Z [REASON]   keep a tag from being deployed (after a rollback by hand)
#   auto-release.sh set-report-url URL|none
#
# One pass (`run`), in order; anything but a deploy only reports and changes nothing:
#   1. paused, BROKEN, or another pass still running (flock): nothing to do.
#   2. the checkout must be clean, at the deployed tag's commit, with .env's TAG matching it.
#   3. `git fetch --tags`; the highest strict vX.Y.Z tag newer than the deployed one.
#   4. it must be an annotated tag (optionally a signed one: RM_CD_REQUIRE_SIGNED_TAGS=1), its
#      commit an ancestor of origin/main, and GitHub's `test` check run green for that commit
#      (an unauthenticated read of the public repository; a rate limit is tried again next pass).
#   5. the gate (cd_logic.py gate): only a code release is deployed by itself. Anything needing
#      data from home, sudo or the nginx site stops with a report in $RM_STATE/cd/hold/<tag>.
#   6. "A new release sha" from the runbook without sudo: the api image and the front end are
#      built first from a `git archive` of the tag (nothing running is touched); then the api and
#      worker stop, the database is snapshotted (pg_dump into $RM_STATE/cd/backups), index.html
#      is saved, the checkout moves to the tag, TAG is set in .env, the compose gate runs,
#      migrations run (only after the snapshot), the front end is installed (index.html last),
#      the api and worker start, collectstatic, routers restart if valhalla/*.json changed, and
#      the local smoke tests run.
#   7. any failure in 6 rolls back automatically (cd_logic.py rollback: rollback A/C as the
#      runbook defines them) and the tag is marked failed; a failed rollback marks the agent BROKEN.
#
# Never touches nginx, sudo, the data bundle, or anything outside the beta's own checkout,
# $RM_DATA/frontend and $RM_STATE. Holds no token. Logs (in $RM_STATE/cd) carry no secret and no
# rider's data: commit ids, file names, step names, and the smoke tests' PASS/FAIL lines.
#
# Settings, read from $RM_STATE/vars.sh (section 0 of the runbook; RM_VARS names another file):
#   RM_STATE RM_SRC RM_DATA      required (section 0)
#   RM_PY                        the python with pyyaml for check_beta_compose.py [python3]
#   RM_CD_GITHUB_REPO            owner/name on GitHub [Macrophage87/RouteMaker]
#   RM_CD_WINDOW                 HH-HH local hours in which a deploy may start (e.g. 02-06) [any]
#   RM_CD_NPM                    off | registry: whether node_modules may be fetched from the npm
#                                registry for a front-end change (an owner decision) [off]
#   RM_CD_REQUIRE_SIGNED_TAGS    1: also require `git verify-tag` to pass [0]
#   RM_CD_KEEP                   release snapshots kept in $RM_STATE/cd/backups [3]
#   RM_CD_HOST                   Host header for the local health check [routemaker.cieply.com]
# DOCKER and CURL name the docker and curl binaries [docker, curl] (the tests use stubs).
set -uo pipefail
export LC_ALL=C

NODE_IMAGE="docker.io/library/node@sha256:363e1587494626837fa7f9a23bdb453d13b0ff3c67c705c2805cfc69c2d2fad7"
API_IMAGE="ghcr.io/macrophage87/routemaker-api"
ROUTERS="valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend"
SECRET_KEYS="PGPASSWORD DJANGO_SECRET_KEY KEY_ENCRYPTION_KEY DISCORD_CLIENT_SECRET DISCORD_BOT_TOKEN BOT_INTERNAL_SECRET"
UNIT=routemaker-beta-cd

die() { echo "auto-release: $*" >&2; exit 2; }
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
self="$here/$(basename "${BASH_SOURCE[0]}")"

usage() { sed -n '2,/^set -uo/p' "$self" | sed '$d' | sed 's/^# \{0,1\}//'; }

# --- settings -------------------------------------------------------------------------------------
load_vars() {
	vars=${RM_VARS:-$HOME/routemaker-beta-state/vars.sh}
	[ -f "$vars" ] || die "no $vars: write it first (docs/BETA-RUNBOOK.md, section 0)"
	# Sourcing runs it: it must be the user's own and writable by nobody else.
	[ "$(stat -c %u "$vars")" = "$(id -u)" ] || die "$vars is not owned by $(id -un)"
	case "$(stat -c %A "$vars")" in ?????w???? | ????????w?) die "$vars is writable by others; chmod 600 it" ;; esac
	# shellcheck disable=SC1090
	. "$vars"
	for v in RM_STATE RM_SRC RM_DATA; do
		[ -n "${!v:-}" ] || die "$v is not set in $vars"
		case "${!v}" in /?*) ;; *) die "$v ('${!v}') is not an absolute path" ;; esac
	done
	cd_dir="$RM_STATE/cd"
	py=${RM_PY:-python3}
	gh_repo=${RM_CD_GITHUB_REPO:-Macrophage87/RouteMaker}
	case "$gh_repo" in *[!A-Za-z0-9._/-]* | */*/* | /* | */) die "RM_CD_GITHUB_REPO '$gh_repo' is not owner/name" ;; */*) ;; *) die "RM_CD_GITHUB_REPO '$gh_repo' is not owner/name" ;; esac
	keep=${RM_CD_KEEP:-3}
	case "$keep" in '' | *[!0-9]* | 0) die "RM_CD_KEEP must be a whole number of 1 or more" ;; esac
	npm_mode=${RM_CD_NPM:-off}
	case "$npm_mode" in off | registry) ;; *) die "RM_CD_NPM must be off or registry" ;; esac
	health_host=${RM_CD_HOST:-routemaker.cieply.com}
	# The agent's own files: the installed copy, so a release cannot change the agent under a pass.
	logic="$cd_dir/bin/cd_logic.py"
	receive="$cd_dir/bin/receive-data.sh"
}

dk() { "${DOCKER:-docker}" "$@"; }
bc() { "$RM_SRC/scripts/beta/beta-compose.sh" "$@"; }
gitc() { git -C "$RM_SRC" "$@"; }
utc() { date -u +%Y%m%dT%H%M%SZ; }
env_value() { sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$RM_SRC/.env" | tail -n 1 | tr -d '\r' | sed "s/^['\"]//; s/['\"]\$//"; }
kv() { sed -n "s/^$1=//p" "$2" | head -n 1; }

# --- reporting ------------------------------------------------------------------------------------
# say: to the journal (stdout) and the pass's report. Never a secret, never .env.
run_log=/dev/null; report=""
say() { printf '%s\n' "$*"; [ -z "$report" ] || printf '%s\n' "$*" >>"$report"; }
# The pass's outcome: one status line, the report kept as last-report.txt, one line in agent.log.
finish() { # word message
	local word=$1; shift
	say "result: $word: $*"
	if [ "$dry_run" = 0 ]; then
		printf '%s %s: %s\n' "$(utc)" "$word" "$*" >"$cd_dir/status"
		printf '%s %s: %s\n' "$(utc)" "$word" "$*" >>"$cd_dir/agent.log"
		tail -n 2000 "$cd_dir/agent.log" >"$cd_dir/agent.log.new" && mv "$cd_dir/agent.log.new" "$cd_dir/agent.log"
		[ -z "$report" ] || cp "$report" "$cd_dir/last-report.txt"
		# The last pass that did something about a release, kept past the idle passes after it.
		case "$word" in deployed | rolled-back | failed | broken | held) [ -z "$report" ] || cp "$report" "$cd_dir/last-release-report.txt" ;; esac
	fi
}
# A release that needs the owner: kept in hold/<tag>, so later passes do not retry it.
hold() { # tag message
	local tag=$1; shift
	if [ "$dry_run" = 0 ]; then
		{ echo "$(utc) $tag held: $*"; [ -z "$report" ] || cat "$report"; } >"$cd_dir/hold/$tag"
	fi
	finish held "$tag: $*"
}
# Run a command with its output in the pass's log only (build output, compose chatter).
quiet() { "$@" >>"$run_log" 2>&1; }

# --- small checks ---------------------------------------------------------------------------------
is_semver() { [[ $1 =~ ^v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$ ]]; }
deployed_tag() { cat "$cd_dir/deployed-tag" 2>/dev/null; }
deployed_sha() { cat "$cd_dir/deployed-sha" 2>/dev/null; }
annotated() { [ "$(gitc cat-file -t "refs/tags/$1" 2>/dev/null)" = tag ]; }
tag_commit() { gitc rev-parse --verify --quiet "refs/tags/$1^{commit}"; }
in_window() {
	local w=${RM_CD_WINDOW:-} from to now
	[ -n "$w" ] || return 0
	case "$w" in [0-2][0-9]-[0-2][0-9]) ;; *) die "RM_CD_WINDOW '$w' is not HH-HH" ;; esac
	from=$((10#${w%-*})); to=$((10#${w#*-})); now=$((10#$(date +%H)))
	[ "$from" -le 23 ] && [ "$to" -le 24 ] || die "RM_CD_WINDOW '$w' is not HH-HH"
	if [ "$from" -le "$to" ]; then [ "$now" -ge "$from" ] && [ "$now" -lt "$to" ]; else [ "$now" -ge "$from" ] || [ "$now" -lt "$to" ]; fi
}
predraw_running() {
	local w
	w=$(bc ps -q worker 2>/dev/null </dev/null) || return 1
	[ -n "$w" ] || return 1
	dk top "$w" -eo pid,args 2>/dev/null | grep -q '[p]redraw_stress_tiles'
}
util_image() { # an image already on the host with sh, cp, mv and tar: the running postgis's
	dk inspect -f '{{.Config.Image}}' "$(bc ps -q postgis </dev/null)" 2>/dev/null
}
frontend_owner() { # the uid:gid that owns what the front end's files are written into
	local d="$RM_DATA/frontend"
	[ -d "$d/assets" ] && d="$d/assets"
	stat -c '%u:%g' "$d"
}
report_url() { cat "$cd_dir/report-url" 2>/dev/null; }
check_report_url() {
	case "$1" in '') return 0 ;; https://?*) ;; *) return 1 ;; esac
	case "$1" in *[!A-Za-z0-9._~:/?#!\$\&*+,\;=%-]* | *@*) return 1 ;; esac
}

# --- GitHub ---------------------------------------------------------------------------------------
# Prints green, pending, red, or "unknown <reason>" (rate limit, network): try again next pass.
ci_status() { # sha
	local sha=$1 body code
	body=$(mktemp)
	code=$("${CURL:-curl}" -sS --max-time 30 -o "$body" -w '%{http_code}' \
		-H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' -H 'User-Agent: routemaker-beta-cd' \
		"https://api.github.com/repos/$gh_repo/commits/$sha/check-runs?check_name=test&filter=latest&per_page=100" 2>>"$run_log") || code=000
	case "$code" in
		200) "$py" "$logic" ci-verdict --sha "$sha" <"$body" ;;
		403 | 429) echo "unknown GitHub's rate limit (HTTP $code)" ;;
		*) echo "unknown GitHub answered HTTP $code" ;;
	esac
	rm -f "$body"
}

# --- the front end --------------------------------------------------------------------------------
lock_hash() { gitc show "$1:frontend/package-lock.json" 2>/dev/null | sha256sum | cut -c1-64; }
# The node_modules for a lockfile, offline: $cd_dir/node_modules/<sha256 of package-lock.json>/
# node_modules, put there by the owner (from home) or, with RM_CD_NPM=registry, by `npm ci
# --ignore-scripts` in the pinned node image. Prints why not, and fails, if it cannot be had.
frontend_ready() { # sha
	local h
	h=$(lock_hash "$1")
	if ! dk image inspect "$NODE_IMAGE" >/dev/null 2>&1; then
		echo "the pinned node image is not on this host ($NODE_IMAGE); the owner loads it once (docker save at home | docker load here), or approves a docker pull of that digest"
		return 1
	fi
	if [ ! -d "$cd_dir/node_modules/$h/node_modules" ] && [ "$npm_mode" != registry ]; then
		echo "the front end changed and there is no node_modules for its lockfile at $cd_dir/node_modules/$h/node_modules (owner: send it from home, or set RM_CD_NPM=registry)"
		return 1
	fi
	if ! check_report_url "$(report_url)" || [ ! -f "$cd_dir/report-url" ]; then
		echo "the beta notice's report link is not recorded: auto-release.sh set-report-url URL|none"
		return 1
	fi
}
fetch_node_modules() { # src-dir hash: only with RM_CD_NPM=registry (a download from the npm registry)
	local src=$1 h=$2 dest="$cd_dir/node_modules/$h"
	[ -d "$dest/node_modules" ] && return 0
	[ "$npm_mode" = registry ] || return 1
	rm -rf "$dest.part"; mkdir -p "$dest.part"
	cp "$src/frontend/package.json" "$src/frontend/package-lock.json" "$dest.part/"
	say "fetching node_modules for lockfile $h from the npm registry (npm ci --ignore-scripts; RM_CD_NPM=registry)"
	quiet dk run --rm --pull never --memory 1536m --memory-swap 1536m --cpus 1 -u "$(id -u):$(id -g)" -e HOME=/tmp \
		-v "$dest.part:/work" -w /work "$NODE_IMAGE" npm ci --ignore-scripts --no-audit --no-fund --loglevel=warn </dev/null || { rm -rf "$dest.part"; return 1; }
	mv -T "$dest.part" "$dest"
}
# Test and build exactly as ship-data.sh --build-frontend does: pinned image, no network, VITE_BETA=1,
# the recorded report link; then refuse a build that carries the value of any secret in .env.
build_frontend() { # src-dir sha out-dir
	local src=$1 sha=$2 out=$3 h url key value
	h=$(lock_hash "$sha")
	fetch_node_modules "$src" "$h" || { say "no node_modules for lockfile $h"; return 1; }
	url=$(report_url)
	rm -rf "$out"; mkdir -p "$out"; chmod 755 "$out"
	# The mount point for node_modules inside the read-only source (docker cannot make it there).
	mkdir -p "$src/frontend/node_modules"
	say "testing and building the front end (pinned node image, no network, VITE_BETA=1, report link: ${url:-none})"
	quiet dk run --rm --pull never --network none --memory 1536m --memory-swap 1536m --cpus 1.5 -u "$(id -u):$(id -g)" -e HOME=/tmp \
		-e VITE_BETA=1 -e VITE_BETA_REPORT_URL="$url" \
		-v "$src/frontend:/app:ro" -v "$cd_dir/node_modules/$h/node_modules:/app/node_modules" -v "$out:/out" -w /app \
		"$NODE_IMAGE" sh -c 'umask 022 && npm test && npx tsc --noEmit && npx vite build --outDir /out --emptyOutDir' </dev/null || return 1
	[ -f "$out/index.html" ] || { say "the build made no index.html"; return 1; }
	printf 'VITE_BETA=1\nVITE_BETA_REPORT_URL=%s\ngit=%s\n' "$url" "$sha" >"$out/beta-build.txt"
	chmod -R u=rwX,go=rX "$out"
	for key in $SECRET_KEYS; do
		value=$(env_value "$key")
		[ "${#value}" -ge 8 ] || continue
		case "$value" in change-me*) continue ;; esac
		if grep -rlF -- "$value" "$out" >/dev/null 2>&1; then say "the value of $key from .env appears in the built front end; refusing it"; return 1; fi
	done
}
# Hashed assets first, index.html last by rename (as receive-data.sh files does), as the uid that
# owns the front end's files, in an image already on the host, with no network.
install_frontend() { # out-dir
	local out=$1 img owner
	img=$(util_image) && [ -n "$img" ] || { say "cannot find the postgis image to install with"; return 1; }
	owner=$(frontend_owner)
	quiet dk run --rm --pull never --network none --user "$owner" -v "$out:/src:ro" -v "$RM_DATA/frontend:/dest" --entrypoint sh "$img" -c \
		'umask 022 && cd /src && tar --exclude=./index.html -cf - . | tar -C /dest --no-same-owner -xf - && cp /src/index.html /dest/.index.html.new && mv -f /dest/.index.html.new /dest/index.html' </dev/null
}
restore_index() { # saved-index-file
	local saved=$1 img owner
	[ -f "$saved" ] || { say "no saved index.html at $saved"; return 1; }
	img=$(util_image) && [ -n "$img" ] || return 1
	owner=$(stat -c '%u:%g' "$RM_DATA/frontend")
	quiet dk run --rm --pull never --network none --user "$owner" -v "$saved:/saved/index.html:ro" -v "$RM_DATA/frontend:/dest" --entrypoint sh "$img" -c \
		'umask 022 && cp /saved/index.html /dest/.index.html.new && mv -f /dest/.index.html.new /dest/index.html' </dev/null
}

# --- the stack ------------------------------------------------------------------------------------
compose_gate() {
	local out
	out=$(cd "$RM_SRC" && "$py" scripts/check_beta_compose.py --env-file .env 2>&1)
	printf '%s\n' "$out" >>"$run_log"
	grep -q 'beta compose: ok' <<<"$out"
}
set_tag() { # short-sha
	sed -i "s/^TAG=.*/TAG=$1/" "$RM_SRC/.env" && [ "$(grep -c '^TAG=' "$RM_SRC/.env")" = 1 ] && [ "$(env_value TAG)" = "$1" ]
}
wait_healthy() {
	local port code
	port=$(env_value BETA_API_PORT); port=${port:-8087}
	for _ in $(seq 1 60); do
		code=$("${CURL:-curl}" -s -o /dev/null -w '%{http_code}' --max-time 5 -H "Host: $health_host" "http://127.0.0.1:$port/healthz" 2>/dev/null) || code=000
		[ "$code" = 200 ] && return 0
		sleep 3
	done
	return 1
}
smoke() {
	local out
	out=$("$RM_SRC/scripts/beta/smoke-test.sh" --local 2>&1) && { printf '%s\n' "$out" >>"$run_log"; grep -E '^(PASS|FAIL)' <<<"$out" >>"$report"; return 0; }
	printf '%s\n' "$out" >>"$run_log"
	say "smoke tests failed once; trying again in a minute (photon needs one after a start)"
	sleep "${RM_CD_SMOKE_RETRY_S:-60}"
	out=$("$RM_SRC/scripts/beta/smoke-test.sh" --local 2>&1); local rc=$?
	printf '%s\n' "$out" >>"$run_log"
	grep -E '^(PASS|FAIL)' <<<"$out" >>"$report"
	return "$rc"
}
predraw() { # the step 8 pre-draw, waited for here (a systemd pass ends by killing what it started)
	say "pre-drawing the stress tiles (the step 8 pre-draw; log: $RM_STATE/predraw.log)"
	(umask 077 && { bc exec -T worker ./manage.py predraw_stress_tiles; echo "predraw exit $?"; } </dev/null >"$RM_STATE/predraw.log" 2>&1)
	tail -n 2 "$RM_STATE/predraw.log" >>"$report"
	grep -q '^predraw exit 0$' "$RM_STATE/predraw.log"
}

# --- deploy and roll back -------------------------------------------------------------------------
done_steps=""
mark() { done_steps="$done_steps${done_steps:+,}$1"; say "step: $2"; }
step() { # description command...: runs it, its output in the log; fails the deploy on error
	local what=$1; shift
	"$@" >>"$run_log" 2>&1 && return 0
	say "FAILED: $what"
	return 1
}

rollback() { # old-sha old-short
	local old=$1 old_short=$2 action ok=1 dump
	say "rolling back (steps done: ${done_steps:-none})"
	local plan
	plan=$("$py" "$logic" rollback --done "$done_steps") || { say "the rollback plan failed"; return 1; }
	for action in $plan; do
		say "rollback: $action"
		case "$action" in
			stop-app) step "stop the api and worker" bc stop api worker </dev/null || ok=0 ;;
			checkout-old) step "check out the previous release" gitc checkout --quiet --detach "$old" && [ "$(gitc rev-parse HEAD)" = "$old" ] || ok=0 ;;
			tag-old) step "set TAG back" set_tag "$old_short" || ok=0 ;;
			gate) compose_gate || { say "FAILED: the compose gate on the previous release"; ok=0; } ;;
			restore-db)
				dump=$(cat "$cd_dir/run-snapshot" 2>/dev/null)
				if [ -n "$dump" ] && [ -f "$dump" ]; then
					if step "restore the pre-release snapshot" env RECEIVE_DATA_REPO="$RM_SRC" "$receive" --env-file "$RM_SRC/.env" --backups-dir "$cd_dir/backups" restore-dump "$dump" </dev/null; then
						say "note: the database as it was before the rollback is kept beside it as <db>_before_<time> (receive-data.sh's last lines in the run log name it); the owner drops it once the beta works"
					else
						ok=0
					fi
				else
					say "FAILED: no pre-release snapshot to restore"; ok=0
				fi
				;;
			restore-index) restore_index "$(cat "$cd_dir/run-index" 2>/dev/null)" || { say "FAILED: put the old index.html back"; ok=0; } ;;
			start-app) step "start the api and worker" bc up -d api worker </dev/null || ok=0 ;;
			recreate-services) step "recreate photon and the routers" bc up -d photon $ROUTERS </dev/null || ok=0 ;;
			restart-routers) step "restart the routers" bc restart $ROUTERS </dev/null || ok=0 ;;
			predraw) predraw || { say "the pre-draw did not finish cleanly (see $RM_STATE/predraw.log)"; ok=0; } ;;
			smoke) { wait_healthy && smoke; } || { say "FAILED: the smoke tests on the previous release"; ok=0; } ;;
		esac
	done
	[ "$ok" = 1 ]
}

deploy() { # tag new-sha gate-file
	local tag=$1 new=$2 gate_file=$3 old old_short new_short stamp src out="" dump
	old=$(deployed_sha); old_short=${old:0:12}; new_short=${new:0:12}; stamp=$(utc)
	src="$cd_dir/build/src-$new_short"
	done_steps=""; rm -f "$cd_dir/run-snapshot" "$cd_dir/run-index"

	# Before anything running is touched: the source, the image and the front end.
	rm -rf "$src"; mkdir -p "$src"
	step "export the release's tree" sh -c 'git -C "$1" archive --format=tar "$2" | tar -x -C "$3"' sh "$RM_SRC" "$new" "$src" || return 3
	if dk image inspect "$API_IMAGE:$new_short" >/dev/null 2>&1; then
		say "step: the api image $API_IMAGE:$new_short is already on the host (built or loaded earlier)"
	else
		say "step: build the api image $API_IMAGE:$new_short (pip needs the network; a few minutes)"
		step "build the api image" dk build -f "$src/docker/api.Dockerfile" -t "$API_IMAGE:$new_short" "$src" </dev/null || return 3
	fi
	if [ "$(kv frontend "$gate_file")" = 1 ]; then
		out="$cd_dir/build/frontend-$new_short"
		build_frontend "$src" "$new" "$out" || { say "FAILED: the front-end test or build"; return 3; }
	fi

	# The runbook's "A new release sha", steps 2 to 8, without sudo.
	mark stopped "stop the api and worker"
	step "stop the api and worker" bc stop api worker </dev/null || return 1
	mark snapshot "snapshot the database (pre-release)"
	dump=$(RECEIVE_DATA_REPO="$RM_SRC" "$receive" --env-file "$RM_SRC/.env" --backups-dir "$cd_dir/backups" snapshot-db --label release </dev/null 2>>"$run_log") && [ -s "$dump" ] ||
		{ say "FAILED: the database snapshot"; return 1; }
	printf '%s\n' "$dump" >"$cd_dir/run-snapshot"
	say "snapshot: $dump"
	mark index_saved "save index.html"
	step "save index.html" cp -p "$RM_DATA/frontend/index.html" "$cd_dir/backups/index.html.pre-release-$stamp" || return 1
	printf '%s\n' "$cd_dir/backups/index.html.pre-release-$stamp" >"$cd_dir/run-index"
	mark checkout "check out $tag"
	step "check out $tag" gitc checkout --quiet --detach "$new" || return 1
	[ "$(gitc rev-parse HEAD)" = "$new" ] || { say "FAILED: the checkout is not at $new"; return 1; }
	mark tag_set "set TAG=$new_short in .env"
	step "set TAG in .env" set_tag "$new_short" || return 1
	compose_gate || { say "FAILED: the compose gate (check_beta_compose.py --env-file .env); its output is in the run log"; return 1; }
	if ! bc run --rm --no-deps migrate ./manage.py migrate --check </dev/null >>"$run_log" 2>&1; then
		mark migrate "migrate (after the snapshot)"
		step "migrate" bc run --rm --no-deps migrate ./manage.py migrate --noinput </dev/null || return 1
	else
		say "step: no migrations to apply"
	fi
	if [ -n "$out" ]; then
		mark frontend "install the front end (index.html last)"
		install_frontend "$out" || { say "FAILED: the front-end install"; return 1; }
	fi
	mark started "start the api and worker"
	step "start the api and worker" bc up -d api worker </dev/null || return 1
	if [ "$(kv compose_changed "$gate_file")" = 1 ]; then
		mark services "recreate photon and the routers whose compose settings changed"
		step "recreate photon and the routers" bc up -d photon $ROUTERS </dev/null || return 1
	fi
	if [ "$(kv routers_restart "$gate_file")" = 1 ]; then
		mark routers "restart the routers (valhalla/*.json changed)"
		step "restart the routers" bc restart $ROUTERS </dev/null || return 1
	fi
	wait_healthy || { say "FAILED: /healthz did not answer 200 (60 tries, 3 s apart)"; return 1; }
	step "migrations check" bc exec -T api ./manage.py migrate --check </dev/null || return 1
	step "collectstatic" bc exec -T api ./manage.py collectstatic --noinput </dev/null || return 1
	smoke || { say "FAILED: the smoke tests"; return 1; }
	if [ "$(kv predraw "$gate_file")" = 1 ]; then
		# A tile FORMAT_VERSION changed (OWNER-DECISIONS 436): the cache is keyed on it, so the
		# new tiles are drawn now (step 8). The release is already live and healthy, so a pre-draw
		# that fails or runs out of budget is a warning, not a rollback: what is left is drawn on request.
		say "step: pre-draw the tiles (a tile FORMAT_VERSION changed)"
		predraw || say "WARNING: the pre-draw did not finish cleanly; the release is live and tiles not yet drawn are drawn on request. Re-run step 8 of docs/BETA-RUNBOOK.md by hand if you want them all warm."
	fi
	return 0
}

prune() {
	local pattern
	for pattern in 'pre-release-*.dump' 'pre-rollback-*.dump' 'index.html.pre-release-*'; do
		# shellcheck disable=SC2012
		ls -1t "$cd_dir/backups"/$pattern 2>/dev/null | tail -n +"$((keep + 1))" | while IFS= read -r f; do rm -f -- "$f"; done
	done
	# shellcheck disable=SC2012
	ls -1t "$cd_dir/runs"/*.log 2>/dev/null | tail -n +31 | while IFS= read -r f; do rm -f -- "$f"; done
	rm -rf "$cd_dir/build"; mkdir -p "$cd_dir/build"
}

# --- one pass -------------------------------------------------------------------------------------
pass() {
	local cur cur_sha tag new verdict reason gate_file why free h
	[ -f "$cd_dir/BROKEN" ] && { finish broken "a rollback failed earlier and needs the owner (see $cd_dir/BROKEN); after fixing, auto-release.sh mark-deployed <tag>"; return 1; }
	[ -f "$cd_dir/PAUSED" ] && { finish paused "$(head -n 1 "$cd_dir/PAUSED")"; return 0; }
	cur=$(deployed_tag); cur_sha=$(deployed_sha)
	[ -n "$cur" ] && [ -n "$cur_sha" ] || { finish error "no deployed tag recorded: run auto-release.sh install"; return 1; }
	[ -f "$logic" ] && [ -x "$receive" ] || { finish error "the agent is not installed in $cd_dir/bin: run auto-release.sh install"; return 1; }

	# The checkout must be what the agent last left there: anything else is someone's hand at work.
	if [ "$(gitc rev-parse HEAD 2>/dev/null)" != "$cur_sha" ] || [ -n "$(gitc status --porcelain 2>/dev/null)" ] || [ "$(env_value TAG)" != "${cur_sha:0:12}" ]; then
		finish drift "the checkout is not clean at $cur ($cur_sha) with TAG=${cur_sha:0:12} in .env; if a release was shipped by hand, run auto-release.sh mark-deployed <tag>"
		return 1
	fi

	if ! gitc fetch --quiet --tags origin "+refs/heads/main:refs/remotes/origin/main" >>"$run_log" 2>&1; then
		finish waiting "git fetch failed (network, or a tag moved on the remote); trying again next pass"
		return 0
	fi
	tag=$(gitc tag -l 'v*' | "$py" "$logic" pick --deployed "$cur") || { finish error "could not pick a tag"; return 1; }
	[ -n "$tag" ] || { finish up-to-date "$cur"; return 0; }
	[ -f "$cd_dir/hold/$tag" ] && { finish held "$tag: $(head -n 1 "$cd_dir/hold/$tag" | cut -d' ' -f4-) (auto-release.sh retry $tag after fixing)"; return 0; }
	[ -f "$cd_dir/failed/$tag" ] && { finish failed "$tag failed and was rolled back earlier (see $cd_dir/failed/$tag); auto-release.sh retry $tag to try again"; return 0; }

	say "candidate: $tag (deployed: $cur)"
	annotated "$tag" || { hold "$tag" "not an annotated tag (git tag -a); the agent deploys annotated tags only"; return 0; }
	new=$(tag_commit "$tag") || { hold "$tag" "the tag names no commit"; return 0; }
	if [ "${RM_CD_REQUIRE_SIGNED_TAGS:-0}" = 1 ]; then
		gitc verify-tag "$tag" >>"$run_log" 2>&1 || { hold "$tag" "the tag's signature does not verify (RM_CD_REQUIRE_SIGNED_TAGS=1)"; return 0; }
	fi
	gitc merge-base --is-ancestor "$new" refs/remotes/origin/main || { hold "$tag" "its commit $new is not on main"; return 0; }
	gitc merge-base --is-ancestor "$cur_sha" "$new" || { hold "$tag" "it does not descend from the deployed release $cur"; return 0; }
	verdict=$(ci_status "$new")
	case "$verdict" in
		green) say "CI: the test check run is green on $new" ;;
		red) hold "$tag" "GitHub's test check run is not green on $new"; return 0 ;;
		pending) finish waiting "$tag: the test check run on $new has not finished (or not started)"; return 0 ;;
		*) finish waiting "$tag: ${verdict#unknown }; trying again next pass"; return 0 ;;
	esac

	gate_file=$(mktemp)
	"$py" "$logic" gate --repo "$RM_SRC" --old "$cur_sha" --new "$new" >"$gate_file" || { rm -f "$gate_file"; finish error "the gate failed to run"; return 1; }
	say "gate: $(kv verdict "$gate_file") ($(kv changed_files "$gate_file") server-relevant files changed since $cur)"
	sed -n 's/^note=/note: /p' "$gate_file" | while IFS= read -r reason; do say "$reason"; done
	if [ "$(kv verdict "$gate_file")" != deploy ]; then
		sed -n 's/^reason=/needs the owner: /p' "$gate_file" | while IFS= read -r reason; do say "$reason"; done
		say "Ship it by hand with docs/BETA-RUNBOOK.md (\"Shipping an update later\"), then: auto-release.sh mark-deployed $tag"
		rm -f "$gate_file"; hold "$tag" "the release needs the owner (data from home, sudo or nginx; reasons in the report)"; return 0
	fi
	[ "$(kv agent_changed "$gate_file")" = 1 ] && say "note: this release changes the release agent itself; once it is deployed, reinstall it: $RM_SRC/scripts/beta/auto-release.sh install"
	[ "$(kv migrations "$gate_file")" = 1 ] && say "note: the release carries migrations; they run after the pre-release snapshot"

	if [ "$(kv frontend "$gate_file")" = 1 ]; then
		why=$(frontend_ready "$new") || { rm -f "$gate_file"; finish waiting "$tag: $why"; return 0; }
		h=$(lock_hash "$new")
		[ -d "$cd_dir/node_modules/$h/node_modules" ] || say "note: node_modules for this lockfile will be fetched from the npm registry (RM_CD_NPM=registry)"
	fi
	in_window || { rm -f "$gate_file"; finish waiting "$tag: outside the deploy window RM_CD_WINDOW=$RM_CD_WINDOW"; return 0; }
	predraw_running && { rm -f "$gate_file"; finish waiting "$tag: a stress-tile pre-draw is running; deploying after it"; return 0; }
	free=$(df -P -k "$cd_dir/backups" | awk 'NR == 2 { print $4 }')
	[ "${free:-0}" -ge 1048576 ] || { rm -f "$gate_file"; finish waiting "$tag: less than 1 GiB free for the snapshot in $cd_dir/backups"; return 0; }
	if [ "$dry_run" = 1 ]; then
		say "dry run: would deploy $tag ($new) over $cur: frontend=$(kv frontend "$gate_file") migrations=$(kv migrations "$gate_file") compose_changed=$(kv compose_changed "$gate_file") routers_restart=$(kv routers_restart "$gate_file") predraw=$(kv predraw "$gate_file")"
		rm -f "$gate_file"; finish dry-run "$tag would be deployed"; return 0
	fi

	say "deploying $tag ($new) over $cur at $(utc)"
	deploy "$tag" "$new" "$gate_file"; local rc=$?
	rm -f "$gate_file"
	if [ "$rc" = 0 ]; then
		printf '%s\n' "$cur" >"$cd_dir/previous-tag"
		printf '%s\n' "$tag" >"$cd_dir/deployed-tag.new" && mv "$cd_dir/deployed-tag.new" "$cd_dir/deployed-tag"
		printf '%s\n' "$new" >"$cd_dir/deployed-sha.new" && mv "$cd_dir/deployed-sha.new" "$cd_dir/deployed-sha"
		rm -f "$cd_dir/run-snapshot" "$cd_dir/run-index"; prune
		finish deployed "$tag ($new), was $cur"
		return 0
	fi
	if [ "$rc" = 3 ]; then # failed before anything running was touched
		{ echo "$(utc) $tag failed before the deploy touched the stack"; cat "$report"; } >"$cd_dir/failed/$tag"
		prune; finish failed "$tag: the build failed; nothing was changed (see $cd_dir/failed/$tag)"
		return 1
	fi
	if rollback "$cur_sha" "${cur_sha:0:12}"; then
		{ echo "$(utc) $tag failed and was rolled back to $cur"; cat "$report"; } >"$cd_dir/failed/$tag"
		rm -f "$cd_dir/run-snapshot" "$cd_dir/run-index"; prune
		finish rolled-back "$tag failed and $cur is running again (see $cd_dir/failed/$tag)"
	else
		{ echo "$(utc) $tag failed and the rollback to $cur did not complete"; cat "$report"; } >"$cd_dir/BROKEN"
		finish broken "$tag failed AND the rollback did not complete: the owner is needed (see $cd_dir/BROKEN and the run log)"
	fi
	return 1
}

cmd_run() {
	local stamp
	mkdir -p "$cd_dir" && chmod 700 "$cd_dir"
	mkdir -p "$cd_dir/hold" "$cd_dir/failed" "$cd_dir/backups" "$cd_dir/runs" "$cd_dir/build" "$cd_dir/node_modules"
	chmod 700 "$cd_dir/backups"
	exec 9>"$cd_dir/lock"
	flock -n 9 || { echo "auto-release: another pass is running; nothing to do"; return 0; }
	umask 077
	stamp=$(utc)
	run_log="$cd_dir/runs/$stamp.log"; : >"$run_log"
	report=$(mktemp)
	if [ "$dry_run" = 1 ]; then say "auto-release pass at $stamp (dry run: fetches, then changes nothing)"; else say "auto-release pass at $stamp"; fi
	say "run log: $run_log"
	pass; local rc=$?
	rm -f "$report"
	[ -s "$run_log" ] || rm -f "$run_log"
	return "$rc"
}

# --- the other commands ---------------------------------------------------------------------------
cmd_status() {
	echo "deployed:   $(deployed_tag || echo '(none recorded)') $(deployed_sha)"
	echo "checkout:   $(gitc describe --tags --exact-match HEAD 2>/dev/null || gitc rev-parse --short=12 HEAD 2>/dev/null) (TAG=$(env_value TAG 2>/dev/null))"
	echo "last pass:  $(cat "$cd_dir/status" 2>/dev/null || echo '(none yet)')"
	[ -f "$cd_dir/PAUSED" ] && echo "PAUSED:     $(head -n 1 "$cd_dir/PAUSED")  (auto-release.sh resume)"
	[ -f "$cd_dir/BROKEN" ] && echo "BROKEN:     $(head -n 1 "$cd_dir/BROKEN")  (the owner looks; then auto-release.sh mark-deployed <tag>)"
	for f in "$cd_dir"/hold/* "$cd_dir"/failed/*; do [ -f "$f" ] && echo "$(basename "$(dirname "$f")"):  $(head -n 1 "$f")"; done
	echo "report url: $(if [ -f "$cd_dir/report-url" ]; then r=$(report_url); echo "${r:-none}"; else echo '(not recorded)'; fi)"
	if command -v systemctl >/dev/null 2>&1; then
		echo "timer:      $(systemctl --user is-enabled "$UNIT.timer" 2>/dev/null || echo not-installed), $(systemctl --user is-active "$UNIT.timer" 2>/dev/null)"
		echo "next pass:  $(systemctl --user list-timers "$UNIT.timer" --no-legend 2>/dev/null | awk '{ print $1, $2, $3 }')"
	fi
	command -v loginctl >/dev/null 2>&1 && echo "linger:     $(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || echo unknown)"
	echo "last report: $cd_dir/last-report.txt (the last release's: $cd_dir/last-release-report.txt)"
}

cmd_pause() { mkdir -p "$cd_dir"; printf '%s %s\n' "$(utc)" "${1:-paused by hand}" >"$cd_dir/PAUSED"; echo "paused: no pass deploys until auto-release.sh resume"; }
cmd_resume() { rm -f "$cd_dir/PAUSED"; echo "resumed"; }

verify_at_tag() { # tag: the checkout is clean at the tag's commit with TAG set to it
	local tag=$1 sha
	is_semver "$tag" || die "'$tag' is not a strict vX.Y.Z tag"
	annotated "$tag" || die "$tag is not an annotated tag here (git fetch --tags first?)"
	sha=$(tag_commit "$tag") || die "$tag names no commit"
	[ "$(gitc rev-parse HEAD)" = "$sha" ] || die "the checkout ($RM_SRC) is at $(gitc rev-parse HEAD), not $tag ($sha)"
	[ -z "$(gitc status --porcelain)" ] || die "the checkout has local changes"
	[ "$(env_value TAG)" = "${sha:0:12}" ] || die ".env's TAG is not ${sha:0:12}"
	printf '%s\n' "$sha"
}
record_deployed() { # tag sha
	printf '%s\n' "$1" >"$cd_dir/deployed-tag"; printf '%s\n' "$2" >"$cd_dir/deployed-sha"
}
cmd_mark_deployed() {
	local tag=${1:-} sha
	[ -n "$tag" ] || die "mark-deployed needs a tag"
	sha=$(verify_at_tag "$tag") || exit 2
	exec 9>"$cd_dir/lock"; flock -n 9 || die "a pass is running; try again when it ends"
	record_deployed "$tag" "$sha"
	rm -f "$cd_dir/hold/$tag" "$cd_dir/failed/$tag" "$cd_dir/BROKEN" "$cd_dir/run-snapshot"
	printf '%s marked-deployed: %s (%s) by hand\n' "$(utc)" "$tag" "$sha" | tee -a "$cd_dir/agent.log" >"$cd_dir/status"
	echo "recorded $tag ($sha) as deployed"
}
cmd_hold() { # tag reason...: keep a tag from being deployed (after a rollback by hand, say)
	local tag=${1:-}
	[ -n "$tag" ] && is_semver "$tag" || die "hold needs a vX.Y.Z tag"
	shift
	mkdir -p "$cd_dir/hold"
	printf '%s %s held: %s\n' "$(utc)" "$tag" "${*:-held by hand}" >"$cd_dir/hold/$tag"
	echo "$tag is held: no pass deploys it until auto-release.sh retry $tag"
}
cmd_retry() {
	local tag=${1:-}
	[ -n "$tag" ] && is_semver "$tag" || die "retry needs a vX.Y.Z tag"
	rm -f "$cd_dir/hold/$tag" "$cd_dir/failed/$tag"
	echo "$tag may be tried again on the next pass"
}
cmd_set_report_url() {
	local url=${1:-}
	[ -n "$url" ] || die "set-report-url needs a URL or none"
	[ "$url" != none ] || url=""
	check_report_url "$url" || die "the report link must be a plain https:// address (as ship-data.sh --report-url)"
	mkdir -p "$cd_dir"; printf '%s\n' "$url" >"$cd_dir/report-url"
	echo "report link: ${url:-none}"
}

units() { # bin-dir
	local bin=$1
	cat >"$unit_dir/$UNIT.service" <<UNITEOF
# Written by scripts/beta/auto-release.sh install (docs/BETA-RUNBOOK.md, "Continuous deployment").
[Unit]
Description=RouteMaker beta: one pass of the pull-based release agent

[Service]
Type=oneshot
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=RM_VARS=$vars
ExecStart="$bin/auto-release.sh" run
TimeoutStartSec=3h
Nice=10
UNITEOF
	cat >"$unit_dir/$UNIT.timer" <<UNITEOF
# Written by scripts/beta/auto-release.sh install (docs/BETA-RUNBOOK.md, "Continuous deployment").
[Unit]
Description=RouteMaker beta: look for a new release about every 10 minutes

[Timer]
OnActiveSec=5min
OnUnitInactiveSec=10min
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
UNITEOF
}

cmd_install() {
	local tag="" url="__unset__" enable=1 sha linger
	while [ $# -gt 0 ]; do
		case "$1" in
			--deployed-tag) [ $# -ge 2 ] || die "$1 needs a value"; tag=$2; shift 2 ;;
			--report-url) [ $# -ge 2 ] || die "$1 needs a value"; url=$2; shift 2 ;;
			--no-enable) enable=0; shift ;;
			*) die "install: unknown argument $1" ;;
		esac
	done
	[ "$(id -u)" != 0 ] || die "run this as the beta's login user, not root"
	for c in git curl flock sha256sum "$py"; do command -v "$c" >/dev/null 2>&1 || die "$c is not installed"; done
	id -nG | tr ' ' '\n' | grep -qx docker || die "$(id -un) is not in the docker group"
	[ -f "$here/cd_logic.py" ] && [ -x "$here/receive-data.sh" ] || die "run install from a checkout's scripts/beta (cd_logic.py and receive-data.sh beside it)"
	if [ -z "$tag" ]; then tag=$(gitc describe --tags --exact-match --match 'v*' HEAD 2>/dev/null) || die "the checkout is not at a release tag; give --deployed-tag"; fi
	sha=$(verify_at_tag "$tag") || exit 2
	if [ -f "$cd_dir/deployed-tag" ] && [ "$(deployed_tag)" != "$tag" ]; then
		die "the agent records $(deployed_tag) as deployed, not $tag; if $tag was shipped by hand, run mark-deployed $tag first"
	fi
	mkdir -p "$cd_dir" && chmod 700 "$cd_dir"
	mkdir -p "$cd_dir/bin" "$cd_dir/hold" "$cd_dir/failed" "$cd_dir/backups" "$cd_dir/runs" "$cd_dir/build" "$cd_dir/node_modules"
	chmod 700 "$cd_dir/backups"
	exec 9>"$cd_dir/lock"; flock -n 9 || die "a pass is running; try again when it ends"
	install -m 700 "$self" "$cd_dir/bin/auto-release.sh"
	install -m 600 "$here/cd_logic.py" "$cd_dir/bin/cd_logic.py"
	install -m 700 "$here/receive-data.sh" "$cd_dir/bin/receive-data.sh"
	printf '%s\n' "$(gitc rev-parse HEAD)" >"$cd_dir/bin/FROM"
	[ -f "$cd_dir/deployed-tag" ] || record_deployed "$tag" "$sha"
	if [ "$url" = __unset__ ]; then
		if [ ! -f "$cd_dir/report-url" ]; then
			[ -f "$RM_DATA/frontend/beta-build.txt" ] || die "no $RM_DATA/frontend/beta-build.txt to read the beta notice's report link from: give --report-url URL (the one ship-data.sh used) or --report-url none"
			url=$(sed -n 's/^VITE_BETA_REPORT_URL=//p' "$RM_DATA/frontend/beta-build.txt" | head -n 1)
			cmd_set_report_url "${url:-none}" >/dev/null || exit 2
		fi
	else
		cmd_set_report_url "$url" >/dev/null || exit 2
	fi
	unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
	mkdir -p "$unit_dir"
	units "$cd_dir/bin"
	echo "installed the agent in $cd_dir/bin (from $(cat "$cd_dir/bin/FROM")); deployed: $(deployed_tag); report link: $(r=$(report_url); echo "${r:-none}")"
	echo "units: $unit_dir/$UNIT.service, $unit_dir/$UNIT.timer"
	if [ "$enable" = 1 ]; then
		systemctl --user daemon-reload && systemctl --user enable --now "$UNIT.timer" || die "systemctl --user could not enable the timer (is there a user manager? see the runbook)"
		echo "timer enabled: $(systemctl --user is-active "$UNIT.timer")"
	else
		echo "not enabled (--no-enable): systemctl --user daemon-reload && systemctl --user enable --now $UNIT.timer"
	fi
	linger=$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || echo unknown)
	if [ "$linger" != yes ]; then
		echo "LINGER is '$linger': without it the timer runs only while $(id -un) is logged in. Run: loginctl enable-linger"
		echo "(no sudo on most systems; if it is refused, the owner runs once: sudo loginctl enable-linger $(id -un))"
	fi
	echo "check: $cd_dir/bin/auto-release.sh run --dry-run   then: $cd_dir/bin/auto-release.sh status"
}
cmd_uninstall() {
	unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
	systemctl --user disable --now "$UNIT.timer" 2>/dev/null || true
	rm -f "$unit_dir/$UNIT.service" "$unit_dir/$UNIT.timer"
	systemctl --user daemon-reload 2>/dev/null || true
	echo "timer and units removed; $cd_dir is kept (rm -rf it by hand if the owner wants)"
}

main() {
	local command=${1:-}
	dry_run=0
	case "$command" in
		'' | -h | --help) usage; return 0 ;;
	esac
	shift
	load_vars
	case "$command" in
		run)
			[ "${1:-}" != --dry-run ] || { dry_run=1; shift; }
			[ $# = 0 ] || die "run takes only --dry-run"
			cmd_run
			;;
		status) cmd_status ;;
		install) cmd_install "$@" ;;
		uninstall) cmd_uninstall ;;
		pause) cmd_pause "$*" ;;
		resume) cmd_resume ;;
		mark-deployed) cmd_mark_deployed "$@" ;;
		retry) cmd_retry "$@" ;;
		hold) cmd_hold "$@" ;;
		set-report-url) cmd_set_report_url "$@" ;;
		*) die "unknown command '$command' (--help)" ;;
	esac
}

# The whole file is read before anything runs, so nothing can change it under a pass.
main "$@"; exit $?
