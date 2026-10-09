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
#   auto-release.sh pause [--wait] [REASON] | resume
#                                     pause: no pass starts a deploy until resume; it says if a pass
#                                     is running now, and --wait waits for that pass to end
#   auto-release.sh mark-deployed vX.Y.Z   after a release shipped by hand (the runbook), or to
#                                     clear a BROKEN state once the owner has looked
#   auto-release.sh retry vX.Y.Z      allow a held or failed tag to be tried again
#   auto-release.sh hold vX.Y.Z [REASON]   keep a tag from being deployed (after a rollback by hand)
#   auto-release.sh set-report-url URL|none
#
# One pass (`run`), in order; anything but a deploy only reports and changes nothing:
#   1. paused, BROKEN, a setting that makes no sense, or another pass still running (flock):
#      nothing to do. A deploy that a stopped pass left half done ($RM_STATE/cd/in-progress) is
#      rolled back first, and its tag marked failed.
#   2. the checkout must be clean, at the deployed tag's commit, with .env's TAG matching it, and
#      its origin https://github.com/$RM_CD_GITHUB_REPO, the repository whose CI is read.
#   3. `git fetch --tags`; the highest strict vX.Y.Z tag newer than the deployed one.
#   4. it must be an annotated tag (optionally a signed one: RM_CD_REQUIRE_SIGNED_TAGS=1), its
#      commit an ancestor of origin/main and a descendant of the deployed release, and GitHub's
#      `test` check run green for that commit (an unauthenticated read of the public repository;
#      a rate limit is tried again next pass).
#   5. the gate (cd_logic.py gate): only a code release is deployed by itself. Anything needing
#      data from home, sudo or the nginx site stops with a report in $RM_STATE/cd/hold/<tag>. A
#      release with nothing for the server (documentation, CI) is only recorded: the checkout and
#      TAG move (the running api image is tagged with it), nothing is stopped.
#   6. "A new release sha" from the runbook without sudo, inside RM_CD_WINDOW if one is set: the
#      tag's tree is exported (`git archive`); then the api and worker stop, and the api image (3
#      tries; skipped if it is already on the host) and, if frontend/ changed, the front end are
#      built, in the memory the api and worker had and not the other sites' headroom; the database
#      is snapshotted (pg_dump into $RM_STATE/cd/backups), the front end's top-level files
#      (index.html, beta-build.txt) are saved, the checkout moves to the tag, TAG is set in .env,
#      the compose gate runs, migrations run (only after the snapshot), the front end is installed
#      (index.html last), the api and worker start, collectstatic, the four routers restart if a
#      valhalla/*.json they read changed (never for valhalla-offroad.json: that router does not run
#      on the beta), and the local smoke tests run. The release is then recorded as deployed. Last,
#      if a tile FORMAT_VERSION changed, the pre-draw runs and is waited for (OWNER-DECISIONS 436);
#      a pre-draw that fails is a warning, not a rollback.
#   7. any failure in 6 before the release is recorded rolls back automatically (cd_logic.py
#      rollback: rollback A/C as the runbook defines them) and the tag is marked failed; a failed
#      rollback marks the agent BROKEN. Each step is written to $RM_STATE/cd/in-progress before it
#      runs, so a pass stopped mid-deploy (TERM/INT/HUP, a reboot, a kill) leaves a record that the
#      next pass acts on (step 1).
#
# Never touches nginx, sudo, the data bundle, or anything outside the beta's own checkout,
# $RM_DATA/frontend and $RM_STATE. Holds no token. Logs (in $RM_STATE/cd) carry no secret and no
# rider's data: commit ids, file names, step names, and the smoke tests' PASS/FAIL lines.
#
# Settings, read from $RM_STATE/vars.sh (section 0 of the runbook; RM_VARS names another file):
#   RM_STATE RM_SRC RM_DATA      required (section 0)
#   RM_PY                        the python with pyyaml for check_beta_compose.py [python3]
#   RM_CD_GITHUB_REPO            owner/name on GitHub [Macrophage87/RouteMaker]
#   RM_CD_WINDOW                 HH-HH local hours in which a deploy may start (e.g. 02-06; the two
#                                hours differ; 22-04 wraps past midnight) [any]
#   RM_CD_DOCKER_FREE_GIB        GiB that must be free on Docker's root before a deploy [3]
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
	health_host=${RM_CD_HOST:-routemaker.cieply.com}
	docker_free_gib=${RM_CD_DOCKER_FREE_GIB:-3}
	case "$docker_free_gib" in '' | *[!0-9]*) die "RM_CD_DOCKER_FREE_GIB must be a whole number of GiB" ;; esac
	progress="$cd_dir/in-progress"
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
		case "$word" in deployed | rolled-back | failed | broken | held | interrupted) [ -z "$report" ] || cp "$report" "$cd_dir/last-release-report.txt" ;; esac
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
# Prints what is wrong with RM_CD_WINDOW, and succeeds, if anything is (a pass reports it as an error).
window_problem() {
	local w=${RM_CD_WINDOW:-} from to
	[ -n "$w" ] || return 1
	case "$w" in [0-2][0-9]-[0-2][0-9]) ;; *) echo "RM_CD_WINDOW '$w' is not HH-HH"; return 0 ;; esac
	from=$((10#${w%-*})); to=$((10#${w#*-}))
	if [ "$from" -gt 23 ] || [ "$to" -gt 24 ]; then echo "RM_CD_WINDOW '$w': the hours run from 00 to 23 (24 may end a window)"; return 0; fi
	[ "$from" != "$to" ] || { echo "RM_CD_WINDOW '$w' opens and closes at the same hour, so it would never open; leave it unset for any hour"; return 0; }
	return 1
}
in_window() { # RM_CD_WINDOW has passed window_problem
	local w=${RM_CD_WINDOW:-} from to now
	[ -n "$w" ] || return 0
	from=$((10#${w%-*})); to=$((10#${w#*-})); now=$((10#$(date +%H)))
	if [ "$from" -le "$to" ]; then [ "$now" -ge "$from" ] && [ "$now" -lt "$to" ]; else [ "$now" -ge "$from" ] || [ "$now" -lt "$to" ]; fi
}
# Prints why the checkout's origin is not the GitHub repository whose CI the agent reads, and
# succeeds, if it is not: code and CI must come from the same place, over https.
origin_problem() {
	local url want
	url=$(gitc config --get remote.origin.url 2>/dev/null)
	want="https://github.com/$gh_repo"
	case "${url,,}" in "${want,,}" | "${want,,}.git") return 1 ;; esac
	url=$(printf '%s' "$url" | sed 's#//[^/]*@#//(credentials hidden)@#')
	echo "the checkout's origin (${url:-none}) is not $want(.git), the repository whose CI check the agent reads (RM_CD_GITHUB_REPO)"
}
docker_root() { dk info -f '{{.DockerRootDir}}' 2>/dev/null </dev/null; }
free_kib() { df -P -k "$1" 2>/dev/null | awk 'NR == 2 { print $4 }'; }
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
# node_modules, put there by the owner from home (the server never downloads npm packages:
# OWNER-DECISIONS 436). Prints why not, and fails, if it is missing.
frontend_ready() { # sha
	local h
	h=$(lock_hash "$1")
	if ! dk image inspect "$NODE_IMAGE" >/dev/null 2>&1; then
		echo "the pinned node image is not on this host ($NODE_IMAGE); the owner loads it once (docker save at home | docker load here), or approves a docker pull of that digest"
		return 1
	fi
	if [ ! -d "$cd_dir/node_modules/$h/node_modules" ]; then
		echo "the front end changed and there is no node_modules for its lockfile at $cd_dir/node_modules/$h/node_modules (owner: send it from home)"
		return 1
	fi
	if ! check_report_url "$(report_url)" || [ ! -f "$cd_dir/report-url" ]; then
		echo "the beta notice's report link is not recorded: auto-release.sh set-report-url URL|none"
		return 1
	fi
}
# Test and build exactly as ship-data.sh --build-frontend does: pinned image, no network, VITE_BETA=1,
# the recorded report link; then refuse a build that carries the value of any secret in .env.
build_frontend() { # src-dir sha out-dir
	local src=$1 sha=$2 out=$3 h url key value
	h=$(lock_hash "$sha")
	[ -d "$cd_dir/node_modules/$h/node_modules" ] || { say "no node_modules for lockfile $h"; return 1; }
	url=$(report_url)
	rm -rf "$out"; mkdir -p "$out"; chmod 755 "$out"
	# The mount point for node_modules inside the read-only source (docker cannot make it there).
	mkdir -p "$src/frontend/node_modules"
	say "testing and building the front end (pinned node image, no network, VITE_BETA=1, report link: ${url:-none})"
	# --oom-score-adj 1000: if the host runs short, the kernel kills this build before any other
	# site's process (and before the beta's own containers, at 500).
	quiet dk run --rm --pull never --network none --memory 1536m --memory-swap 1536m --cpus 1.5 --oom-score-adj 1000 -u "$(id -u):$(id -g)" -e HOME=/tmp \
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
# The front end's top-level files (index.html, beta-build.txt, the unhashed public files): saved
# before an install, so a rollback puts back the page and the record of which build is live.
save_frontend_top() { # dir
	[ -f "$RM_DATA/frontend/index.html" ] || return 1
	mkdir -p "$1" && chmod 755 "$1" &&
		find "$RM_DATA/frontend" -mindepth 1 -maxdepth 1 -type f -exec cp -p {} "$1"/ \; &&
		[ -f "$1/index.html" ]
}
restore_frontend() { # saved-dir: back as they were, index.html last by rename
	local saved=$1 img owner
	[ -f "$saved/index.html" ] || { say "no saved index.html in ${saved:-(none recorded)}"; return 1; }
	img=$(util_image) && [ -n "$img" ] || return 1
	owner=$(stat -c '%u:%g' "$RM_DATA/frontend")
	quiet dk run --rm --pull never --network none --user "$owner" -v "$saved:/saved:ro" -v "$RM_DATA/frontend:/dest" --entrypoint sh "$img" -c \
		'umask 022 && cd /saved && tar --exclude=./index.html -cf - . | tar -C /dest --no-same-owner -xf - && cp /saved/index.html /dest/.index.html.new && mv -f /dest/.index.html.new /dest/index.html' </dev/null
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
# $cd_dir/in-progress: written when a deploy starts and before each of its steps runs, removed once
# the release is recorded or rolled back. A pass stopped mid-deploy leaves it, and the next pass
# rolls that deploy back (recover) instead of reporting the moved checkout as drift.
done_steps=""; deploy_tag=""; deploy_new=""; deploy_old=""; deploy_old_tag=""; predraw_warning=""
write_progress() {
	printf 'tag=%s\nnew=%s\nold=%s\nold_tag=%s\nsteps=%s\npid=%s\n' "$deploy_tag" "$deploy_new" "$deploy_old" "$deploy_old_tag" "$done_steps" "$$" >"$progress.new" &&
		mv -f "$progress.new" "$progress"
}
start_progress() { # tag new-sha
	deploy_tag=$1; deploy_new=$2; deploy_old=$(deployed_sha); deploy_old_tag=$(deployed_tag); done_steps=""
	write_progress || { say "FAILED: could not write $progress"; return 1; }
}
mark() { # step description: recorded in $progress before the step runs
	done_steps="$done_steps${done_steps:+,}$1"
	write_progress || { say "FAILED: could not record the step in $progress"; return 1; }
	say "step: $2"
}
step() { # description command...: runs it, its output in the log; fails the deploy on error
	local what=$1; shift
	"$@" >>"$run_log" 2>&1 && return 0
	say "FAILED: $what"
	return 1
}
# The release is live and smoke-tested: record it now, before anything optional (the pre-draw) runs.
commit_release() { # tag sha
	printf '%s\n' "$deploy_old_tag" >"$cd_dir/previous-tag.new" && printf '%s\n' "$2" >"$cd_dir/deployed-sha.new" &&
		printf '%s\n' "$1" >"$cd_dir/deployed-tag.new" || return 1
	mv -f "$cd_dir/previous-tag.new" "$cd_dir/previous-tag" && mv -f "$cd_dir/deployed-sha.new" "$cd_dir/deployed-sha" &&
		mv -f "$cd_dir/deployed-tag.new" "$cd_dir/deployed-tag" || return 1
	rm -f "$progress" "$cd_dir/run-snapshot" "$cd_dir/run-index"
}
# TERM, INT or HUP during a pass: systemd stopping the unit (TimeoutStartSec, a reboot, the user
# manager ending at logout without linger), or ^C. The steps done stay in $progress for the next pass.
on_signal() { # signal-name exit-code
	trap - TERM INT HUP
	if [ -f "$progress" ]; then
		printf 'interrupted=%s SIG%s\n' "$(utc)" "$1" >>"$progress"
		finish interrupted "${deploy_tag:-a deploy}: the pass was stopped (SIG$1) mid-deploy after steps ${done_steps:-none}; the next pass rolls it back ($progress)"
	elif [ -n "$deploy_tag" ] && [ "$(deployed_tag)" = "$deploy_tag" ]; then
		finish deployed "$deploy_tag ($deploy_new), was $deploy_old_tag; WARNING: the pass was stopped (SIG$1) during the pre-draw: the tiles not yet drawn are drawn on request"
	fi
	[ -z "$report" ] || rm -f "$report"
	exit "$2"
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
			restore-index) restore_frontend "$(cat "$cd_dir/run-index" 2>/dev/null)" || { say "FAILED: put the old front end's top-level files back (index.html, beta-build.txt)"; ok=0; } ;;
			start-app) step "start the api and worker" bc up -d api worker </dev/null || ok=0 ;;
			recreate-services) step "recreate photon and the routers" bc up -d photon $ROUTERS </dev/null || ok=0 ;;
			restart-routers) step "restart the routers" bc restart $ROUTERS </dev/null || ok=0 ;;
			# A missing pre-draw only means tiles are drawn on request (OWNER-DECISIONS 436): a warning.
			predraw) predraw || say "WARNING: the pre-draw after the restore did not finish cleanly (see $RM_STATE/predraw.log); tiles not yet drawn are drawn on request" ;;
			smoke) { wait_healthy && smoke; } || { say "FAILED: the smoke tests on the previous release"; ok=0; } ;;
		esac
	done
	[ "$ok" = 1 ]
}

# The api image, with pip's network: a failure is tried again twice (a pip index or network blip),
# a minute apart, before the deploy fails.
build_api() { # src-dir short-sha
	local src=$1 short=$2 n=1 tries=3
	while :; do
		say "step: build the api image $API_IMAGE:$short (pip needs the network; a few minutes; try $n of $tries)"
		step "build the api image" dk build -f "$src/docker/api.Dockerfile" -t "$API_IMAGE:$short" "$src" </dev/null && return 0
		[ "$n" -lt "$tries" ] || return 1
		sleep "${RM_CD_BUILD_RETRY_S:-60}"
		n=$((n + 1))
	done
}

# A release with nothing for the server (documentation, CI, a new tag on the deployed commit):
# the checkout and TAG move, the running image is tagged with the new TAG, nothing is stopped.
noop_release() { # tag new-sha
	local tag=$1 new=$2 old old_short new_short
	old=$(deployed_sha); old_short=${old:0:12}; new_short=${new:0:12}
	start_progress "$tag" "$new" || return 3
	if [ "$new" != "$old" ]; then
		mark image "tag the running api image $API_IMAGE:$old_short as $new_short" || return 1
		step "tag the api image" dk tag "$API_IMAGE:$old_short" "$API_IMAGE:$new_short" </dev/null || return 1
		mark checkout "check out $tag" || return 1
		step "check out $tag" gitc checkout --quiet --detach "$new" || return 1
		[ "$(gitc rev-parse HEAD)" = "$new" ] || { say "FAILED: the checkout is not at $new"; return 1; }
		mark tag_set "set TAG=$new_short in .env" || return 1
		step "set TAG in .env" set_tag "$new_short" || return 1
		compose_gate || { say "FAILED: the compose gate (check_beta_compose.py --env-file .env); its output is in the run log"; return 1; }
	fi
	commit_release "$tag" "$new" || { say "FAILED: recording $tag as deployed in $cd_dir"; return 1; }
}

deploy() { # tag new-sha gate-file
	local tag=$1 new=$2 gate_file=$3 old_short new_short stamp src out="" dump saved
	old_short=$(deployed_sha); old_short=${old_short:0:12}; new_short=${new:0:12}; stamp=$(utc)
	src="$cd_dir/build/src-$new_short"
	rm -f "$cd_dir/run-snapshot" "$cd_dir/run-index"
	start_progress "$tag" "$new" || return 3

	# Before anything running is touched: the release's tree.
	rm -rf "$src"; mkdir -p "$src"
	step "export the release's tree" sh -c 'git -C "$1" archive --format=tar "$2" | tar -x -C "$3"' sh "$RM_SRC" "$new" "$src" || return 3

	# The runbook's "A new release sha", steps 2 to 8, without sudo. The builds come after the stop,
	# so they use the memory the api and worker had and not the other sites' headroom (the api
	# build is not capped: BuildKit runs in the daemon; docs/BETA-RUNBOOK.md, install step 6).
	mark stopped "stop the api and worker" || return 1
	step "stop the api and worker" bc stop api worker </dev/null || return 1
	mark image "the api image $API_IMAGE:$new_short" || return 1
	if dk image inspect "$API_IMAGE:$new_short" >/dev/null 2>&1; then
		say "step: the api image $API_IMAGE:$new_short is already on the host (built or loaded earlier)"
	else
		build_api "$src" "$new_short" || return 1
	fi
	if [ "$(kv frontend "$gate_file")" = 1 ]; then
		out="$cd_dir/build/frontend-$new_short"
		build_frontend "$src" "$new" "$out" || { say "FAILED: the front-end test or build"; return 1; }
	fi
	mark snapshot "snapshot the database (pre-release)" || return 1
	dump=$(RECEIVE_DATA_REPO="$RM_SRC" "$receive" --env-file "$RM_SRC/.env" --backups-dir "$cd_dir/backups" snapshot-db --label release </dev/null 2>>"$run_log") && [ -s "$dump" ] ||
		{ say "FAILED: the database snapshot"; return 1; }
	printf '%s\n' "$dump" >"$cd_dir/run-snapshot"
	say "snapshot: $dump"
	mark index_saved "save the front end's top-level files (index.html, beta-build.txt)" || return 1
	saved="$cd_dir/backups/frontend.pre-release-$stamp"
	step "save the front end's top-level files" save_frontend_top "$saved" || return 1
	printf '%s\n' "$saved" >"$cd_dir/run-index"
	mark checkout "check out $tag" || return 1
	step "check out $tag" gitc checkout --quiet --detach "$new" || return 1
	[ "$(gitc rev-parse HEAD)" = "$new" ] || { say "FAILED: the checkout is not at $new"; return 1; }
	mark tag_set "set TAG=$new_short in .env" || return 1
	step "set TAG in .env" set_tag "$new_short" || return 1
	compose_gate || { say "FAILED: the compose gate (check_beta_compose.py --env-file .env); its output is in the run log"; return 1; }
	if ! bc run --rm --no-deps migrate ./manage.py migrate --check </dev/null >>"$run_log" 2>&1; then
		mark migrate "migrate (after the snapshot)" || return 1
		step "migrate" bc run --rm --no-deps migrate ./manage.py migrate --noinput </dev/null || return 1
	else
		say "step: no migrations to apply"
	fi
	if [ -n "$out" ]; then
		mark frontend "install the front end (index.html last)" || return 1
		install_frontend "$out" || { say "FAILED: the front-end install"; return 1; }
	fi
	mark started "start the api and worker" || return 1
	step "start the api and worker" bc up -d api worker </dev/null || return 1
	if [ "$(kv compose_changed "$gate_file")" = 1 ]; then
		mark services "recreate photon and the routers whose compose settings changed" || return 1
		step "recreate photon and the routers" bc up -d photon $ROUTERS </dev/null || return 1
	fi
	if [ "$(kv routers_restart "$gate_file")" = 1 ]; then
		mark routers "restart the four routers (a valhalla/*.json they read changed)" || return 1
		step "restart the routers" bc restart $ROUTERS </dev/null || return 1
	fi
	wait_healthy || { say "FAILED: /healthz did not answer 200 (60 tries, 3 s apart)"; return 1; }
	step "migrations check" bc exec -T api ./manage.py migrate --check </dev/null || return 1
	step "collectstatic" bc exec -T api ./manage.py collectstatic --noinput </dev/null || return 1
	smoke || { say "FAILED: the smoke tests"; return 1; }
	# Live and smoke-tested: recorded before the pre-draw, so a pass stopped during the pre-draw
	# leaves a deployed release, not a half-done one.
	commit_release "$tag" "$new" || { say "FAILED: recording $tag as deployed in $cd_dir"; return 1; }
	say "step: $tag recorded as deployed"
	if [ "$(kv predraw "$gate_file")" = 1 ]; then
		# A tile FORMAT_VERSION changed (OWNER-DECISIONS 436): the cache is keyed on it, so the
		# new tiles are drawn now (step 8). A pre-draw that fails or runs out of budget is a
		# warning, not a rollback: what is left is drawn on request.
		say "step: pre-draw the tiles (a tile FORMAT_VERSION changed)"
		if ! predraw; then
			predraw_warning="the pre-draw did not finish cleanly (tiles not yet drawn are drawn on request)"
			say "WARNING: the pre-draw did not finish cleanly; the release is live and tiles not yet drawn are drawn on request. Re-run step 8 of docs/BETA-RUNBOOK.md by hand if you want them all warm."
		fi
	fi
	return 0
}

prune() {
	local pattern
	for pattern in 'pre-release-*.dump' 'pre-rollback-*.dump' 'frontend.pre-release-*'; do
		# shellcheck disable=SC2012
		ls -1dt "$cd_dir/backups"/$pattern 2>/dev/null | tail -n +"$((keep + 1))" | while IFS= read -r f; do rm -rf -- "$f"; done
	done
	# shellcheck disable=SC2012
	ls -1t "$cd_dir/runs"/*.log 2>/dev/null | tail -n +31 | while IFS= read -r f; do rm -f -- "$f"; done
	rm -rf "$cd_dir/build"; mkdir -p "$cd_dir/build"
}

# A deploy that a stopped pass left half done: roll it back from the steps $progress records.
# Returns 0 when the pass may go on (nothing had been touched, or it had been recorded), 1 when
# the pass ends here (rolled back, or BROKEN).
recover() {
	local steps
	deploy_tag=$(kv tag "$progress"); deploy_new=$(kv new "$progress"); deploy_old=$(kv old "$progress")
	deploy_old_tag=$(kv old_tag "$progress"); steps=$(kv steps "$progress")
	say "found $progress: a pass was stopped mid-deploy of ${deploy_tag:-?} after steps: ${steps:-none} ($(kv interrupted "$progress"))"
	if [ -n "$deploy_new" ] && [ "$deploy_new" = "$(deployed_sha)" ] && [ "$deploy_tag" = "$(deployed_tag)" ]; then
		rm -f "$progress" "$cd_dir/run-snapshot" "$cd_dir/run-index"
		say "it had already been recorded as deployed"
		return 0
	fi
	if ! is_semver "$deploy_tag" || [[ ! $deploy_old =~ ^[0-9a-f]{40}$ ]] || [ "$deploy_old" != "$(deployed_sha)" ]; then
		{ echo "$(utc) a stopped pass left $progress, which does not match the deployed release"; cat "$progress"; cat "$report"; } >"$cd_dir/BROKEN"
		finish broken "a stopped pass left $progress, which does not match the deployed release: the owner is needed (see $cd_dir/BROKEN)"
		return 1
	fi
	if [ -z "$steps" ]; then
		rm -f "$progress"
		say "it had not touched the stack; carrying on"
		return 0
	fi
	done_steps=$steps
	write_progress
	if rollback "$deploy_old" "${deploy_old:0:12}"; then
		{ echo "$(utc) $deploy_tag: a pass was stopped mid-deploy, and it was rolled back to $deploy_old_tag"; cat "$report"; } >"$cd_dir/failed/$deploy_tag"
		rm -f "$progress" "$cd_dir/run-snapshot" "$cd_dir/run-index"; prune
		finish rolled-back "$deploy_tag: a pass was stopped mid-deploy; it was rolled back and $deploy_old_tag is running again (see $cd_dir/failed/$deploy_tag; auto-release.sh retry $deploy_tag to try it again)"
	else
		{ echo "$(utc) $deploy_tag: a pass was stopped mid-deploy and the rollback to $deploy_old_tag did not complete"; cat "$report"; } >"$cd_dir/BROKEN"
		finish broken "$deploy_tag: a pass was stopped mid-deploy AND the rollback did not complete: the owner is needed (see $cd_dir/BROKEN and the run log)"
	fi
	return 1
}

# --- one pass -------------------------------------------------------------------------------------
pass() {
	local cur cur_sha tag new verdict reason gate_file why free h root noop=0
	predraw_warning=""
	[ -f "$cd_dir/BROKEN" ] && { finish broken "a rollback failed earlier and needs the owner (see $cd_dir/BROKEN); after fixing, auto-release.sh mark-deployed <tag>"; return 1; }
	[ -f "$cd_dir/PAUSED" ] && { finish paused "$(head -n 1 "$cd_dir/PAUSED")"; return 0; }
	why=$(window_problem) && { finish error "$why (in $vars)"; return 1; }
	cur=$(deployed_tag); cur_sha=$(deployed_sha)
	[ -n "$cur" ] && [ -n "$cur_sha" ] || { finish error "no deployed tag recorded: run auto-release.sh install"; return 1; }
	[ -f "$logic" ] && [ -x "$receive" ] || { finish error "the agent is not installed in $cd_dir/bin: run auto-release.sh install"; return 1; }

	# A deploy a stopped pass left half done comes first: the checkout may be anywhere in it.
	if [ -f "$progress" ]; then
		if [ "$dry_run" = 1 ]; then
			finish dry-run "a stopped pass left $progress ($(kv tag "$progress"), steps: $(kv steps "$progress")); the next pass rolls that deploy back"
			return 0
		fi
		recover || return 1
		cur=$(deployed_tag); cur_sha=$(deployed_sha)
	fi

	# The checkout must be what the agent last left there: anything else is someone's hand at work.
	if [ "$(gitc rev-parse HEAD 2>/dev/null)" != "$cur_sha" ] || [ -n "$(gitc status --porcelain 2>/dev/null)" ] || [ "$(env_value TAG)" != "${cur_sha:0:12}" ]; then
		finish drift "the checkout is not clean at $cur ($cur_sha) with TAG=${cur_sha:0:12} in .env; if a release was shipped by hand, run auto-release.sh mark-deployed <tag>"
		return 1
	fi
	why=$(origin_problem) && { finish error "$why"; return 1; }

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
	[ "$(kv lockfile_changed "$gate_file")" = 1 ] && say "note: the front end's package files changed, so the release needs node_modules for its new lockfile, sent from home"
	if [ "$(kv changed_files "$gate_file")" = 0 ] && dk image inspect "$API_IMAGE:${cur_sha:0:12}" >/dev/null 2>&1; then
		noop=1
		say "nothing in this release is for the server (documentation or CI only): it is recorded without touching the stack"
	fi

	if [ "$noop" = 0 ]; then
		if [ "$(kv frontend "$gate_file")" = 1 ]; then
			why=$(frontend_ready "$new") || { rm -f "$gate_file"; finish waiting "$tag: $why"; return 0; }
			h=$(lock_hash "$new")
		fi
		in_window || { rm -f "$gate_file"; finish waiting "$tag: outside the deploy window RM_CD_WINDOW=$RM_CD_WINDOW"; return 0; }
		predraw_running && { rm -f "$gate_file"; finish waiting "$tag: a stress-tile pre-draw is running; deploying after it"; return 0; }
		free=$(free_kib "$cd_dir/backups")
		[ "${free:-0}" -ge 1048576 ] || { rm -f "$gate_file"; finish waiting "$tag: less than 1 GiB free for the snapshot in $cd_dir/backups"; return 0; }
		root=$(docker_root)
		free=""; [ -z "$root" ] || free=$(free_kib "$root")
		if [ -z "$free" ]; then
			say "note: could not read the free space on Docker's root (docker info); going on"
		elif [ "$free" -lt $((docker_free_gib * 1048576)) ]; then
			rm -f "$gate_file"
			finish waiting "$tag: less than $docker_free_gib GiB free on Docker's root ($root) for the image build; the owner frees space (old api images: docker image ls $API_IMAGE)"
			return 0
		fi
	fi
	if [ "$dry_run" = 1 ]; then
		say "dry run: would deploy $tag ($new) over $cur: nothing_for_the_server=$noop frontend=$(kv frontend "$gate_file") lockfile_changed=$(kv lockfile_changed "$gate_file") migrations=$(kv migrations "$gate_file") compose_changed=$(kv compose_changed "$gate_file") routers_restart=$(kv routers_restart "$gate_file") predraw=$(kv predraw "$gate_file")"
		rm -f "$gate_file"; finish dry-run "$tag would be deployed"; return 0
	fi

	say "deploying $tag ($new) over $cur at $(utc)"
	if [ "$noop" = 1 ]; then noop_release "$tag" "$new"; else deploy "$tag" "$new" "$gate_file"; fi
	local rc=$?
	rm -f "$gate_file"
	if [ "$rc" = 0 ]; then
		prune
		if [ "$noop" = 1 ]; then
			finish deployed "$tag ($new), was $cur: nothing in it for the server, so it was recorded without touching the stack"
		else
			finish deployed "$tag ($new), was $cur${predraw_warning:+; WARNING: $predraw_warning}"
		fi
		return 0
	fi
	if [ "$rc" = 3 ]; then # failed before anything running was touched
		rm -f "$progress"
		{ echo "$(utc) $tag failed before the deploy touched the stack"; cat "$report"; } >"$cd_dir/failed/$tag"
		prune; finish failed "$tag: the release's tree could not be prepared; nothing was changed (see $cd_dir/failed/$tag)"
		return 1
	fi
	if rollback "$cur_sha" "${cur_sha:0:12}"; then
		{ echo "$(utc) $tag failed and was rolled back to $cur"; cat "$report"; } >"$cd_dir/failed/$tag"
		rm -f "$progress" "$cd_dir/run-snapshot" "$cd_dir/run-index"; prune
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
	if [ "$dry_run" = 0 ]; then
		trap 'on_signal TERM 143' TERM
		trap 'on_signal INT 130' INT
		trap 'on_signal HUP 129' HUP
	fi
	if [ "$dry_run" = 1 ]; then say "auto-release pass at $stamp (dry run: fetches, then changes nothing)"; else say "auto-release pass at $stamp"; fi
	say "run log: $run_log"
	pass; local rc=$?
	trap - TERM INT HUP
	rm -f "$report"
	[ -s "$run_log" ] || rm -f "$run_log"
	return "$rc"
}

# --- the other commands ---------------------------------------------------------------------------
cmd_status() {
	local root pguser n
	echo "deployed:   $(deployed_tag || echo '(none recorded)') $(deployed_sha)"
	echo "checkout:   $(gitc describe --tags --exact-match HEAD 2>/dev/null || gitc rev-parse --short=12 HEAD 2>/dev/null) (TAG=$(env_value TAG 2>/dev/null))"
	echo "last pass:  $(cat "$cd_dir/status" 2>/dev/null || echo '(none yet)')"
	[ -f "$cd_dir/PAUSED" ] && echo "PAUSED:     $(head -n 1 "$cd_dir/PAUSED")  (auto-release.sh resume)"
	[ -f "$cd_dir/BROKEN" ] && echo "BROKEN:     $(head -n 1 "$cd_dir/BROKEN")  (the owner looks; then auto-release.sh mark-deployed <tag>)"
	if [ -f "$progress" ]; then
		if pass_running; then
			echo "deploying:  $(kv tag "$progress") now (steps so far: $(kv steps "$progress"))"
		else
			echo "IN PROGRESS: left by a stopped pass: $(kv tag "$progress") after steps $(kv steps "$progress") $(kv interrupted "$progress"); the next pass rolls it back"
		fi
	elif pass_running; then
		echo "running:    a pass is running now"
	fi
	w=$(window_problem) && echo "SETTING:    $w"
	for f in "$cd_dir"/hold/* "$cd_dir"/failed/*; do [ -f "$f" ] && echo "$(basename "$(dirname "$f")"):  $(head -n 1 "$f")"; done
	echo "report url: $(if [ -f "$cd_dir/report-url" ]; then r=$(report_url); echo "${r:-none}"; else echo '(not recorded)'; fi)"
	root=$(docker_root)
	echo "disk free:  Docker's root ${root:-(unknown)}: $( [ -n "$root" ] && df -P -h "$root" 2>/dev/null | awk 'NR == 2 { print $4 " of " $2 }')  $RM_STATE: $(df -P -h "$RM_STATE" 2>/dev/null | awk 'NR == 2 { print $4 " of " $2 }')"
	n=$(dk image ls -q "$API_IMAGE" 2>/dev/null </dev/null | sort -u | grep -c .)
	echo "api images: ${n:-0} (one a release, kept for rollback C; the owner removes old ones: docker image ls $API_IMAGE)"
	pguser=$(env_value PGUSER 2>/dev/null); pguser=${pguser:-routemaker}
	n=$(bc exec -T postgis psql -U "$pguser" -d postgres -At -c "select count(*) from pg_database where datname like '%\_before\_%'" </dev/null 2>/dev/null)
	echo "kept dbs:   ${n:-unknown} <db>_before_<time> databases left by restores (the owner drops them once the beta works)"
	echo "node_modules: $(find "$cd_dir/node_modules" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | grep -c .) lockfile copies in $cd_dir/node_modules"
	if command -v systemctl >/dev/null 2>&1; then
		echo "timer:      $(systemctl --user is-enabled "$UNIT.timer" 2>/dev/null || echo not-installed), $(systemctl --user is-active "$UNIT.timer" 2>/dev/null)"
		echo "next pass:  $(systemctl --user list-timers "$UNIT.timer" --no-legend 2>/dev/null | awk '{ print $1, $2, $3 }')"
	fi
	command -v loginctl >/dev/null 2>&1 && echo "linger:     $(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || echo unknown)"
	echo "last report: $cd_dir/last-report.txt (the last release's: $cd_dir/last-release-report.txt)"
}

# Whether a pass holds the run lock now (a subshell takes it and lets it go at once).
pass_running() { [ -e "$cd_dir/lock" ] || return 1; ! (exec 8>>"$cd_dir/lock" && flock -n 8); }

cmd_pause() { # [--wait] reason...
	local wait=0
	[ "${1:-}" != --wait ] || { wait=1; shift; }
	mkdir -p "$cd_dir"; printf '%s %s\n' "$(utc)" "${*:-paused by hand}" >"$cd_dir/PAUSED"
	echo "paused: no pass starts a deploy until auto-release.sh resume"
	pass_running || { echo "no pass is running now: it is safe to work by hand"; return 0; }
	if [ "$wait" = 0 ]; then
		echo "WARNING: a pass is running now ($(cat "$cd_dir/status" 2>/dev/null || echo 'see status')); pause does not stop it. Wait until it ends before working by hand: auto-release.sh pause --wait waits for it." >&2
		return 0
	fi
	echo "a pass is running now; waiting for it to end (it may be building, deploying or pre-drawing) ..."
	exec 9>>"$cd_dir/lock"
	flock 9 || die "could not wait for the running pass"
	flock -u 9
	echo "it ended: $(cat "$cd_dir/status" 2>/dev/null); it is safe to work by hand"
}
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
	local tag=${1:-} sha url
	[ -n "$tag" ] || die "mark-deployed needs a tag"
	sha=$(verify_at_tag "$tag") || exit 2
	exec 9>"$cd_dir/lock"; flock -n 9 || die "a pass is running; try again when it ends"
	record_deployed "$tag" "$sha"
	rm -f "$cd_dir/hold/$tag" "$cd_dir/failed/$tag" "$cd_dir/BROKEN" "$cd_dir/run-snapshot" "$cd_dir/run-index" "$progress"
	printf '%s marked-deployed: %s (%s) by hand\n' "$(utc)" "$tag" "$sha" | tee -a "$cd_dir/agent.log" >"$cd_dir/status"
	echo "recorded $tag ($sha) as deployed"
	# A front end shipped by hand may carry another report link: the live one is the one CD keeps.
	if [ -f "$RM_DATA/frontend/beta-build.txt" ]; then
		url=$(sed -n 's/^VITE_BETA_REPORT_URL=//p' "$RM_DATA/frontend/beta-build.txt" | head -n 1)
		if [ ! -f "$cd_dir/report-url" ] || [ "$url" != "$(report_url)" ]; then
			if check_report_url "$url"; then
				cmd_set_report_url "${url:-none}" >/dev/null
				echo "report link: ${url:-none} (read from $RM_DATA/frontend/beta-build.txt, the live front end)"
			else
				echo "WARNING: the report link in $RM_DATA/frontend/beta-build.txt is not a plain https:// address; the recorded one is kept (auto-release.sh set-report-url URL|none)" >&2
			fi
		fi
	fi
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
	local tag="" url="__unset__" enable=1 sha linger why
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
	why=$(window_problem) && die "$why (in $vars)"
	why=$(origin_problem) && die "$why"
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
		pause) cmd_pause "$@" ;;
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
