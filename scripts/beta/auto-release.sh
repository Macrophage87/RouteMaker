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
#                                     is running now, and --wait waits for that pass to end; it says
#                                     if a stopped pass left a deploy half done (IN PROGRESS), which
#                                     nothing rolls back while paused
#   auto-release.sh mark-deployed [--force] vX.Y.Z   after a release shipped by hand (the runbook),
#                                     or to clear a BROKEN state once the owner has looked; --force
#                                     also drops a half-done deploy's record, once the owner has
#                                     checked the stack by hand
#   auto-release.sh retry vX.Y.Z      allow a held or failed tag to be tried again
#   auto-release.sh hold vX.Y.Z [REASON]   keep a tag from being deployed (after a rollback by hand)
#   auto-release.sh ship-held vX.Y.Z (--map RUN_URL | --no-map) [--allow-sha-mismatch] [--dry-run]
#                                     the owner's one command for a release held because it needs a
#                                     map: its code through the agent's deploy, then the cloud run's
#                                     map (import-result.sh --beta, then --swap); "ship-held" below
#   auto-release.sh rollback [--dry-run] [--keep-db | --restore-db] [--force]
#                                     the owner's one command to put the previous release back (the
#                                     deployed one is then held); "rollback" below explains the flags
#   auto-release.sh rollback-map [--dry-run] [--graphs-only]
#                                     the owner's one command to put the previous map back (graphs and
#                                     map tables trade places with the ones the last update replaced;
#                                     run it again to undo it); "rollback-map" below says what it does
#   auto-release.sh set-report-url URL|none
#
# One pass (`run`), in order; anything but a deploy only reports and changes nothing:
#   1. paused, BROKEN, a setting that makes no sense, or another pass still running (flock):
#      nothing to do (while paused, not even the recovery below). Then a deploy that a stopped pass
#      left half done ($RM_STATE/cd/in-progress) is rolled back, if it had touched the stack, and
#      its tag marked failed; if it had not, the record is dropped and the pass goes on.
#   2. the checkout must be clean, at the deployed tag's commit, with .env's TAG matching it, and
#      its origin https://github.com/$RM_CD_GITHUB_REPO, the repository whose CI is read.
#   3. `git fetch --tags`; the highest strict vX.Y.Z tag newer than the deployed one.
#   4. it must be an annotated tag, or a lightweight one on the commit whose subject is "Release
#      vX.Y.Z" (optionally a signed one: RM_CD_REQUIRE_SIGNED_TAGS=1), its commit an ancestor of
#      origin/main and a descendant of the deployed release, and GitHub's `test` and `a11y` check
#      runs green for that commit (an unauthenticated read of the public repository; a rate limit
#      is tried again next pass).
#      A tag the release workflow made (.github/workflows/release.yml) names the api image it built
#      from the tagged commit by digest (`api-image: ...@sha256:...` in its message): that image is
#      pulled and tagged here instead of built, and a change to the image's own files (Dockerfile,
#      requirements, entrypoint) is deployed rather than held for a hand ship (the owner,
#      2026-11-12). A pull that fails waits for the next pass.
#   5. the gate (cd_logic.py gate): only a code release is deployed by itself. Anything needing
#      data from home, sudo or the nginx site stops with a report in $RM_STATE/cd/hold/<tag>. A
#      release with nothing for the server (documentation, CI) is only recorded, if the running api
#      image is on the host (if not, it is a full deploy): the checkout and TAG move (the running
#      api image is tagged with it), nothing is stopped.
#   6. "A new release sha" from the runbook without sudo, inside RM_CD_WINDOW if one is set: the
#      tag's tree is exported (`git archive`), and the api image (3 tries; skipped if it is already
#      on the host) and, if frontend/ changed, the front end are built while the beta still runs;
#      then, only for a release that carries a migration file (or with RM_CD_ALWAYS_STOP=1), the api
#      and worker stop and the database is snapshotted (pg_dump into $RM_STATE/cd/backups); any
#      other release keeps them running and `up -d` swaps them onto the new image. The front end's top-level files
#      (index.html, beta-build.txt) are saved, the checkout moves to the tag, TAG is set in .env,
#      the compose gate runs, migrations run (only after the snapshot), the front end is installed
#      (index.html last), the api and worker start, photon and the routers are recreated if a
#      compose file changed, the routers restart if a valhalla/*.json changed (the routers: the
#      four, and valhalla-offroad, valhalla-mtb, valhalla-paved and valhalla-paved-weekend once their tiles
#      are on the host; a stopped valhalla-paved or valhalla-paved-weekend only with the memory for it,
#      RM_CD_PAVED_MIN_MIB), /healthz is waited for,
#      `migrate --check` and collectstatic run in the api, and the local smoke tests run. The
#      release is then recorded as deployed. Last,
#      if a tile FORMAT_VERSION changed, the pre-draw runs and is waited for (OWNER-DECISIONS 436);
#      a pre-draw that fails is a warning, not a rollback. After a deploy, a release that changed
#      the agent's own files has them reinstalled in $RM_STATE/cd/bin for the next pass, and old
#      api images, build cache and node_modules copies are pruned (never the previous release's).
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
#   RM_CD_WINDOW                 HH-HH Washington hours in which a deploy may start (e.g. 02-06; the two
#                                hours differ; 22-04 wraps past midnight) [any]
#   RM_CD_DOCKER_FREE_GIB        GiB that must be free on Docker's root before a deploy [3]
#   RM_CD_REQUIRE_SIGNED_TAGS    1: also require `git verify-tag` to pass [0]
#   RM_CD_KEEP                   release snapshots kept in $RM_STATE/cd/backups [3]
#   RM_CD_ALWAYS_STOP            1: stop the api and worker and snapshot for every release, not only
#                                one that carries a migration file [0]
#   RM_CD_WAIT_ALERT_MIN         minutes a release may wait (CI, node_modules, the node image, the
#                                network) before the owner is alerted [30]
#   RM_CD_PAVED_MIN_MIB          MiB of available memory plus what this project's running containers
#                                hold, below which a stopped valhalla-paved or valhalla-paved-weekend
#                                is left stopped [8806]
#   RM_CD_HOST                   Host header for the local health check [RM_BETA_HOST from the
#                                checkout's .env; one of the two is required]
# DOCKER and CURL name the docker and curl binaries [docker, curl] (the tests use stubs).
set -uo pipefail
export LC_ALL=C

NODE_IMAGE="docker.io/library/node@sha256:363e1587494626837fa7f9a23bdb453d13b0ff3c67c705c2805cfc69c2d2fad7"
API_IMAGE="ghcr.io/macrophage87/routemaker-api"
ROUTERS="valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend"
# The trail routers (Gravel and Mountain Goat's, Mountain Bike's; profile `offroad`, which naming
# them turns on): run beside the four once their promoted build is on the host, never before, since
# a bind with create_host_path: false stops the whole `up` without it (the owner, 2026-10-20).
TRAIL_ROUTERS="valhalla-offroad valhalla-mtb valhalla-paved valhalla-paved-weekend"
SECRET_KEYS="PGPASSWORD DJANGO_SECRET_KEY KEY_ENCRYPTION_KEY DISCORD_CLIENT_SECRET DISCORD_BOT_TOKEN BOT_INTERNAL_SECRET FEEDBACK_WEBHOOK_URL"
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
	wait_alert_min=${RM_CD_WAIT_ALERT_MIN:-30}
	case "$wait_alert_min" in '' | *[!0-9]*) die "RM_CD_WAIT_ALERT_MIN must be a whole number of minutes" ;; esac
	# The beta's name is server config, never in the repository (review sec-infra-8).
	health_host=${RM_CD_HOST:-$(env_value RM_BETA_HOST 2>/dev/null)}
	[ -n "$health_host" ] || die "no host for the health check: set RM_BETA_HOST=<the beta's name> in $RM_SRC/.env (docs/BETA-RUNBOOK.md, section 0)"
	docker_free_gib=${RM_CD_DOCKER_FREE_GIB:-3}
	case "$docker_free_gib" in '' | *[!0-9]*) die "RM_CD_DOCKER_FREE_GIB must be a whole number of GiB" ;; esac
	# Road Bike's routers start only where available memory plus what this project's running
	# containers already hold reaches the startup peak (8406 MiB, every cap) plus the 0.39 GiB
	# margin of check_beta_compose.py: 8806 MiB. It was 8086 MiB plus 0.7 GiB (8803) until Road
	# Bike's weekend router came in (the owner, 2026-11-08, "New weekend graph", at a start-up
	# margin of about 0.4 GiB).
	# Counting `available` alone, with the stack up, counted postgis, photon and memcached twice
	# and left it stopped on a host with room (2026-11-03: 5759 available + 3258 held = 9017).
	paved_min_mib=${RM_CD_PAVED_MIN_MIB:-8806}
	case "$paved_min_mib" in '' | *[!0-9]*) die "RM_CD_PAVED_MIN_MIB must be a whole number of MiB" ;; esac
	progress="$cd_dir/in-progress"
	# The agent's own files: the installed copy, so a release cannot change the agent under a pass.
	logic="$cd_dir/bin/cd_logic.py"
	receive="$cd_dir/bin/receive-data.sh"
	build_fe="$cd_dir/bin/frontend-build.sh"
}

dk() { "${DOCKER:-docker}" "$@"; }
bc() { "$RM_SRC/scripts/beta/beta-compose.sh" "$@"; }
paved_room_mib() { # available memory plus this project's containers' resident memory, in MiB
	local avail ids held=0
	# RM_CD_MEMINFO: the tests' stand-in for /proc/meminfo
	avail="$(awk '/^MemAvailable:/ {print int($2 / 1024)}' "${RM_CD_MEMINFO:-/proc/meminfo}")"
	[ -n "$avail" ] || return 1
	ids="$(bc ps -q </dev/null)" || return 1
	if [ -n "$ids" ]; then
		# shellcheck disable=SC2086 # one argument per container id
		held="$(timeout 30 "${DOCKER:-docker}" stats --no-stream --format '{{.MemUsage}}' $ids </dev/null |
			awk '{ v = $1; u = v; sub(/^[0-9.]+/, "", u); sub(/[A-Za-z]+$/, "", v)
				f = (u == "GiB") ? 1024 : (u == "MiB") ? 1 : (u == "KiB") ? 1 / 1024 : (u == "B") ? 1 / 1048576 : 0
				s += v * f } END { print int(s) }')" || return 1
	fi
	printf '%s\n' "$((avail + held))"
}
# The routers this host runs: the four, then each trail router whose tiles are here.
routers() {
	printf '%s' "$ROUTERS"
	for router in $TRAIL_ROUTERS; do
		[ -L "$RM_DATA/tiles/${router#valhalla-}/current" ] && printf ' %s' "$router"
	done
	echo
}
gitc() { git -C "$RM_SRC" "$@"; }
# The pass runs under umask 022: the release's files are read inside the containers as another
# user, and the v0.8.1 deploy failed at the migration on an unreadable manage.py written under 077.
# Its logs, reports and snapshots are private because $RM_STATE/cd and its backups are mode 700;
# the pre-draw log and pg_dump write under their own 077. The checkout stays 022 explicitly.
checkout_at() { (umask 022 && gitc checkout --quiet --detach "$1"); }
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
		[ "$word" = waiting ] || rm -f "$cd_dir/waiting"
		tail -n 2000 "$cd_dir/agent.log" >"$cd_dir/agent.log.new" && mv "$cd_dir/agent.log.new" "$cd_dir/agent.log"
		[ -z "$report" ] || cp "$report" "$cd_dir/last-report.txt"
		# The last pass that did something about a release, kept past the idle passes after it.
		case "$word" in deployed | rolled-back | failed | broken | held | interrupted) [ -z "$report" ] || cp "$report" "$cd_dir/last-release-report.txt" ;; esac
		notify "$word" "$*"
		rider_status done
		# A held, waiting or failed newer tag leaves the deployed one live: its notes are still due.
		# A release shipped by hand is nearly always followed by such a tag.
		case "$word" in deployed | up-to-date | held | waiting | failed) release_notes "$cd_dir/bin/alert.sh" ;; esac
		case "$word" in deployed | up-to-date) reports_live ;; esac
	fi
}
# The riders' status line (alert.sh status): "Updating" while a deploy has the api stopped.
# $cd_dir/rider-updating marks it, so only a pass after a deploy began (this one, or one a stop
# cut short) calls "done".
rider_status() { # updating | done
	case "$1" in
		updating) : >"$cd_dir/rider-updating" ;;
		done) [ -f "$cd_dir/rider-updating" ] || return 0 ;;
	esac
	if [ -x "$cd_dir/bin/alert.sh" ]; then
		"$cd_dir/bin/alert.sh" status "$1" >/dev/null 2>&1 </dev/null || return 0
	fi
	[ "$1" != done ] || rm -f "$cd_dir/rider-updating"
}
# The owner's alert channel (alert.sh, review OPS-1): a result that needs the owner is posted once
# (again once a day while it lasts), a deploy always. alert.sh posts nothing without a webhook and
# never fails, and a slow channel cannot hold a pass for long (its curl has a 20 s limit).
notify() { # word message
	local word=$1 message=$2 alert="$cd_dir/bin/alert.sh" id
	[ -x "$alert" ] || return 0
	id=${message%%[ :]*}
	case "$word" in
		deployed)
			# The installed copy is the one the timer and this agent run: the deployed release's own,
			# so a release that teaches alert.sh something new uses it at once.
			[ ! -f "$RM_SRC/scripts/beta/alert.sh" ] || install -m 700 "$RM_SRC/scripts/beta/alert.sh" "$alert"
			"$alert" note "deployed $message" && "$alert" clear deploy "the release agent is working again (deployed ${message%% *})" ;;
		up-to-date) "$alert" clear deploy "the release agent is working again ($message deployed)" ;;
		rolled-back | failed) "$alert" send deploy "failed $id" "$word: $message" ;;
		held | interrupted) "$alert" send deploy "$word $id" "$word: $message" ;;
		broken | error | drift) "$alert" send deploy "$word $(printf '%s' "$message" | sed 's/[0-9][0-9.]*/N/g' | sha256sum | cut -c1-12)" "$word: $message" ;;
		waiting)
			case "$message" in
				*" free "*) "$alert" send deploy "disk" "waiting: $message" ;;
				*) ! waited_long "$message" || "$alert" send deploy "waiting $(same_wait "$message")" "waiting for over $wait_alert_min min: $message" ;;
			esac
			;;
	esac >>"$run_log" 2>&1 </dev/null
	return 0
}
# A wait's identity: its words without their numbers, as alert.sh's repeat check reads them.
same_wait() { printf '%s' "$1" | sed 's/[0-9][0-9.]*/N/g' | sha256sum | cut -c1-12; }
# Whether a release has waited for the same reason for RM_CD_WAIT_ALERT_MIN minutes: the first
# pass that waits for it records the time in $cd_dir/waiting; a wait for another reason starts
# again, and any other result forgets it (finish). The planned waits (the deploy window, the
# nightly backup's slot, a pre-draw) never alert.
waited_long() { # message
	local id since now
	case "$1" in *"outside the deploy window"* | *"nightly backup runs at"* | *"pre-draw is running"*) rm -f "$cd_dir/waiting"; return 1 ;; esac
	id=$(same_wait "$1"); now=$(date +%s)
	since=$(sed -n "s/^$id \([0-9]*\)$/\1/p" "$cd_dir/waiting" 2>/dev/null | head -n 1)
	if [ -z "$since" ]; then printf '%s %s\n' "$id" "$now" >"$cd_dir/waiting"; return 1; fi
	[ $((now - since)) -ge $((wait_alert_min * 60)) ]
}
# The riders' changelog: the live release's notes, docs/releases/<tag>.md from its checkout, once
# per tag. Posted by the owner's bot (scripts/discord_reports.py changelog) once he has stored a bot
# token and $RM_STATE/discord/changelog-channel; otherwise by the old release webhook (alert.sh
# release-notes) while one is stored. Tried on every deploy, up-to-date, held, waiting or failed
# pass (with the checkout at the deployed release) until posted; a failure is reported once a day
# in the owner's channel and never fails the pass.
release_notes() { # alert
	local tag discord="$RM_STATE/discord" script="$RM_SRC/scripts/discord_reports.py" ok
	tag=$(deployed_tag)
	is_semver "$tag" || return 0
	! grep -qxF "$tag" "$RM_STATE/alerts/release-posted" 2>/dev/null || return 0
	# The notes are read from the checkout, so it must be at the deployed release.
	[ "$(gitc rev-parse HEAD 2>/dev/null)" = "$(deployed_sha)" ] || return 0
	if [ -s "$discord/bot-token" ] && [ -s "$discord/changelog-channel" ] && [ -f "$script" ]; then
		{
			if timeout 120 "$py" "$script" --dir "$discord" changelog "$tag" "$RM_SRC/docs/releases/$tag.md" \
				--live-date "$(TZ=America/New_York date +%F)"; then
				mkdir -p "$RM_STATE/alerts" && echo "$tag" >>"$RM_STATE/alerts/release-posted"
				ok=1
			else
				ok=0
			fi
			[ ! -x "$1" ] || if [ "$ok" = 1 ]; then
				"$1" clear release-notes "the release notes for $tag are posted"
			else
				"$1" send release-notes "$tag" "the release notes for $tag were not posted; tried again at the next pass"
			fi
		} >>"$run_log" 2>&1 </dev/null
		return 0
	fi
	[ -s "$RM_STATE/release-webhook" ] && [ -x "$1" ] && grep -q 'release-notes)' "$1" || return 0
	{
		if "$1" release-notes "$tag" "$RM_SRC/docs/releases/$tag.md"; then
			"$1" clear release-notes "the release notes for $tag are posted"
		else
			"$1" send release-notes "$tag" "the release notes for $tag were not posted; tried again at the next pass"
		fi
	} >>"$run_log" 2>&1 </dev/null
	return 0
}
# The testers' report posts (scripts/discord_reports.py live, docs/BETA-RUNBOOK.md, "Tester
# reports"): every forum post whose change is in the live release is told it is live, once per
# tag, only when the owner has stored a bot token in $RM_STATE/discord. A failure is reported
# once a day in the owner's channel and never fails the pass; the next pass tries again. Five
# minutes at most, since the pass holds the deploy lock.
reports_live() {
	local tag script="$RM_SRC/scripts/discord_reports.py" alert="$cd_dir/bin/alert.sh"
	tag=$(deployed_tag)
	is_semver "$tag" && [ -s "$RM_STATE/discord/bot-token" ] && [ -f "$script" ] || return 0
	! grep -qxF "$tag" "$RM_STATE/alerts/live-posted" 2>/dev/null || return 0
	{
		if timeout 300 "$py" "$script" --dir "$RM_STATE/discord" live "$tag"; then
			mkdir -p "$RM_STATE/alerts" && echo "$tag" >>"$RM_STATE/alerts/live-posted"
			[ ! -x "$alert" ] || "$alert" clear reports-live "the testers' posts are told $tag is live"
		else
			[ ! -x "$alert" ] || "$alert" send reports-live "$tag" "the testers' posts were not all told $tag is live; tried again at the next pass"
		fi
	} >>"$run_log" 2>&1 </dev/null
	return 0
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
# A release tag: annotated, or a lightweight one (`git tag vX.Y.Z`, GitHub's release page) on the
# commit whose subject names that release ("Release vX.Y.Z", the release procedure's last commit).
release_tag() {
	local subject
	annotated "$1" && return 0
	[ "$(gitc cat-file -t "refs/tags/$1" 2>/dev/null)" = commit ] || return 1
	subject=$(gitc log -1 --format=%s "refs/tags/$1" 2>/dev/null) || return 1
	case "$subject" in "Release $1" | "Release $1 "*) return 0 ;; esac
	return 1
}
tag_commit() { gitc rev-parse --verify --quiet "refs/tags/$1^{commit}"; }
# Prints what is wrong with RM_CD_WINDOW, and succeeds, if anything is (a pass reports it as an error).
window_problem() {
	local w=${RM_CD_WINDOW:-} from to
	[ -n "$w" ] || return 1
	case "$w" in [0-2][0-9]-[0-2][0-9]) ;; *) echo "RM_CD_WINDOW '$w' is not HH-HH"; return 0 ;; esac
	from=$((10#${w%-*})); to=$((10#${w#*-}))
	if [ "$from" -gt 23 ] || [ "$to" -gt 24 ]; then echo "RM_CD_WINDOW '$w': the hours run from 00 to 23 (24 may end a window)"; return 0; fi
	[ "$from" != "$to" ] || { echo "RM_CD_WINDOW '$w' opens and closes at the same hour, so it would never open; leave it unset for any hour"; return 0; }
	# Without the zone's data, date answers in UTC under the zone's name: say so, not a wrong hour.
	case "$(TZ=America/New_York date +%Z)" in
		EST | EDT) ;;
		*) echo "RM_CD_WINDOW is read in Washington time, and this host has no time zone data for America/New_York: install tzdata"; return 0 ;;
	esac
	return 1
}
in_window() { # RM_CD_WINDOW has passed window_problem
	local w=${RM_CD_WINDOW:-} from to now
	[ -n "$w" ] || return 0
	# Washington's hours, whatever zone the host keeps (a cloud server's is often UTC).
	from=$((10#${w%-*})); to=$((10#${w#*-})); now=$((10#$(TZ=America/New_York date +%H)))
	if [ "$from" -le "$to" ]; then [ "$now" -ge "$from" ] && [ "$now" -lt "$to" ]; else [ "$now" -ge "$from" ] || [ "$now" -lt "$to" ]; fi
}
# From 5 minutes before the nightly backup to 30 after it (06:55 to 07:30 UTC for 07:00): a
# deploy that started then would take its pre-release snapshot and restart the stack under the
# dump. Its time is NIGHTLY_BACKUP_CRON ("M H * * *", UTC) in the checkout, else 07:00.
backup_minute() {
	local m="" h=""
	read -r m h < <(sed -n 's/^NIGHTLY_BACKUP_CRON = "\([0-9]\{1,2\}\) \([0-9]\{1,2\}\) \* \* \*"$/\1 \2/p' \
		"$RM_SRC/src/config/procrastinate.py" 2>/dev/null | tail -n1) || true
	if [[ "$m" =~ ^[0-9]+$ ]] && [[ "$h" =~ ^[0-9]+$ ]] && [ $((10#$m)) -lt 60 ] && [ $((10#$h)) -lt 24 ]; then
		echo $((10#$h * 60 + 10#$m))
	else
		echo 420
	fi
}
hhmm() { printf '%02d:%02d' $(($1 / 60)) $(($1 % 60)); }
in_backup_slot() {
	local now
	now=$((10#$(date -u +%H%M)))
	now=$((now / 100 * 60 + now % 100))
	[ $(((now - $1 + 5 + 1440) % 1440)) -lt 35 ]
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
# Green is every check run cd_logic.py names (CHECK_NAMES: `test` and `a11y`) green.
ci_status() { # sha
	local sha=$1 body code
	body=$(mktemp)
	code=$("${CURL:-curl}" -sS --max-time 30 -o "$body" -w '%{http_code}' \
		-H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' -H 'User-Agent: routemaker-beta-cd' \
		"https://api.github.com/repos/$gh_repo/commits/$sha/check-runs?filter=latest&per_page=100" 2>>"$run_log") || code=000
	case "$code" in
		200) "$py" "$logic" ci-verdict --sha "$sha" <"$body" ;;
		403 | 429) echo "unknown GitHub's rate limit (HTTP $code)" ;;
		*) echo "unknown GitHub answered HTTP $code" ;;
	esac
	rm -f "$body"
}

# --- the front end --------------------------------------------------------------------------------
# The lockfile's hash without its version fields, which every release bumps (cd_logic.py lock-hash;
# the runbook's send command makes the same one).
lock_hash() { gitc show "$1:frontend/package-lock.json" 2>/dev/null | "$py" "$logic" lock-hash; }
# The node_modules for a lockfile, offline: $cd_dir/node_modules/<cd_logic.py lock-hash>/
# node_modules, put there by the owner from home (the server never downloads npm packages:
# OWNER-DECISIONS 436). Prints why not, and fails, if it is missing.
frontend_ready() { # sha
	local h why
	h=$(lock_hash "$1")
	if ! dk image inspect "$NODE_IMAGE" >/dev/null 2>&1; then
		echo "the pinned node image is not on this host ($NODE_IMAGE); the owner loads it once, saved under a tag (docker save at home | docker load here; BETA-RUNBOOK.md, \"Front-end releases need two things on the server\"), or approves a docker pull of that digest"
		return 1
	fi
	if [ ! -d "$cd_dir/node_modules/$h/node_modules" ]; then
		echo "the front end changed and there is no node_modules for its lockfile at $cd_dir/node_modules/$h/node_modules (owner: send it from home)"
		return 1
	fi
	# Refused here, before anything stops, rather than by the build after the api is down.
	if ! why=$("$build_fe" --check "$cd_dir/node_modules/$h/node_modules" 2>&1); then
		echo "${why#frontend-build: } (owner: send a Linux one from home)"
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
	say "testing and building the front end (pinned node image, no network, VITE_BETA=1, report link: ${url:-none})"
	# frontend-build.sh holds the mounts and steps, shared with ship-data.sh and CI.
	# --oom-score-adj 1000: if the host runs short, the kernel kills this build before any other
	# site's process (and before the beta's own containers, at 500).
	quiet env DOCKER="${DOCKER:-docker}" "$build_fe" --docker-opt --memory=1536m --docker-opt --memory-swap=1536m --docker-opt --cpus=1.5 --docker-opt --oom-score-adj=1000 \
		"$src" "$cd_dir/node_modules/$h/node_modules" "$out" "$url" || return 1
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
	out=$("$RM_SRC/scripts/beta/smoke-test.sh" --local --host "$health_host" 2>&1) && { printf '%s\n' "$out" >>"$run_log"; grep -E '^(PASS|FAIL)' <<<"$out" >>"$report"; return 0; }
	printf '%s\n' "$out" >>"$run_log"
	say "smoke tests failed once; trying again in a minute (photon needs one after a start)"
	sleep "${RM_CD_SMOKE_RETRY_S:-60}"
	out=$("$RM_SRC/scripts/beta/smoke-test.sh" --local --host "$health_host" 2>&1); local rc=$?
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
done_steps=""; deploy_tag=""; deploy_new=""; deploy_old=""; deploy_old_tag=""; predraw_warning=""; predraw_started=0
restore_from="" # rollback --restore-db: the snapshot deploy() restores in place of the migrations
map_importing="" # ship-held: what the map import is doing, for a stop part-way
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
	# The snapshot taken before this deploy (none without a migration): what `rollback --restore-db`
	# puts back, the database as the previous release left it.
	if [ -s "$cd_dir/run-snapshot" ]; then mv -f "$cd_dir/run-snapshot" "$cd_dir/deployed-snapshot"; else rm -f "$cd_dir/deployed-snapshot"; fi
	rm -f "$progress" "$cd_dir/run-snapshot" "$cd_dir/run-index"
}
# Who rolls back a deploy a stopped pass left half done: the next pass, unless the agent is paused.
rolled_back_when() {
	if [ -f "$cd_dir/PAUSED" ]; then
		echo "the agent is PAUSED, so nothing rolls it back until auto-release.sh resume (then the next pass does), or the owner puts it right by hand and runs mark-deployed --force <tag>"
	else
		echo "the next pass rolls it back"
	fi
}
# What a leftover $progress means when no pass holds the lock: none; harmless (it had touched
# nothing, or the release had been recorded); or half-done.
leftover() {
	[ -f "$progress" ] || { echo none; return; }
	if [ -z "$(kv steps "$progress")" ] || { [ "$(kv new "$progress")" = "$(deployed_sha)" ] && [ "$(kv tag "$progress")" = "$(deployed_tag)" ]; }; then
		echo harmless
	else
		echo half-done
	fi
}
in_progress_line() {
	echo "IN PROGRESS: left by a stopped pass: $(kv tag "$progress") after steps $(kv steps "$progress") $(kv interrupted "$progress"); $(rolled_back_when)"
}
# TERM, INT or HUP during a pass: systemd stopping the unit (TimeoutStartSec, a reboot, the user
# manager ending at logout without linger), or ^C. The steps done stay in $progress for the next pass.
on_signal() { # signal-name exit-code
	trap - TERM INT HUP
	if [ -f "$progress" ]; then
		printf 'interrupted=%s SIG%s\n' "$(utc)" "$1" >>"$progress"
		finish interrupted "${deploy_tag:-a deploy}: the pass was stopped (SIG$1) mid-deploy after steps ${done_steps:-none}; $(rolled_back_when) ($progress)"
	elif [ -n "$map_importing" ]; then
		finish interrupted "$deploy_tag's code is live, but the pass was stopped (SIG$1) while the map was $map_importing; the agent stays paused. Look at what import-result.sh left (its swap undoes itself on failure; auto-release.sh rollback-map puts the previous map back), then auto-release.sh resume"
	elif [ -n "$deploy_tag" ] && [ "$(deployed_tag)" = "$deploy_tag" ]; then
		if [ "$predraw_started" = 1 ]; then
			finish deployed "$deploy_tag ($deploy_new), was $deploy_old_tag; WARNING: the pass was stopped (SIG$1) during the pre-draw: the tiles not yet drawn are drawn on request"
		else
			finish deployed "$deploy_tag ($deploy_new), was $deploy_old_tag; the pass was stopped (SIG$1) after the release was recorded"
		fi
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
			checkout-old) step "check out the previous release" checkout_at "$old" && [ "$(gitc rev-parse HEAD)" = "$old" ] || ok=0 ;;
			tag-old) step "set TAG back" set_tag "$old_short" || ok=0 ;;
			gate) compose_gate || { say "FAILED: the compose gate on the previous release"; ok=0; } ;;
			restore-db)
				dump=$(cat "$cd_dir/run-snapshot" 2>/dev/null)
				if [ -n "$dump" ] && [ -f "$dump" ]; then
					if step "restore the pre-release snapshot" env RECEIVE_DATA_REPO="$RM_SRC" "$receive" --env-file "$RM_SRC/.env" --backups-dir "$cd_dir/backups" restore-dump "$dump" </dev/null; then
						say "note: the database as it was before the rollback is kept beside it as <db>_before_<time> (receive-data.sh's last lines in the run log name it); a pass drops it once it is 6.5 days old"
					else
						ok=0
					fi
				else
					say "FAILED: no pre-release snapshot to restore"; ok=0
				fi
				;;
			restore-index) restore_frontend "$(cat "$cd_dir/run-index" 2>/dev/null)" || { say "FAILED: put the old front end's top-level files back (index.html, beta-build.txt)"; ok=0; } ;;
			start-app) { step "start the api and worker" bc up -d api worker </dev/null && wait_healthy && sync_rows; } || ok=0 ;;
			# The four only: the release rolled back to may be one whose compose gives the trail routers their old
			# 768M caps, over the budget, so a rollback never starts them; nothing here stops them either, that is
			# done by hand (docs/BETA-RUNBOOK.md, rollback A).
			recreate-services) step "recreate photon and the routers" bc up -d photon $ROUTERS </dev/null || ok=0 ;;
			restart-routers) step "restart the routers" bc restart $ROUTERS </dev/null || ok=0 ;;
			# A missing pre-draw only means tiles are drawn on request (OWNER-DECISIONS 436): a warning.
			predraw) predraw || say "WARNING: the pre-draw after the restore did not finish cleanly (see $RM_STATE/predraw.log); tiles not yet drawn are drawn on request" ;;
			smoke) { wait_healthy && smoke; } || { say "FAILED: the smoke tests on the previous release"; ok=0; } ;;
		esac
	done
	[ "$ok" = 1 ]
}

# The settings rows the api serves each variant by, from the tile links (manage.py sync_upstreams):
# nothing else on the beta writes them, and a restored snapshot brings back the old ones. Idempotent,
# and a warning only (an image from before the command has none).
sync_rows() {
	step "write the routers' settings rows from the tile links" bc exec -T api ./manage.py sync_upstreams </dev/null ||
		say "WARNING: sync_upstreams failed (see the run log); run it by hand: scripts/beta/beta-compose.sh exec -T api ./manage.py sync_upstreams"
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

# The image a release-workflow tag names: its build provenance first (GitHub's attestations for the
# digest must say this repository's release workflow on main built it, the run the owner approved),
# then the pull, tagged with the release's TAG; the digest reference is dropped again so pruning the
# tag frees the image. Returns 0 when the image is here, 1 when its provenance does not check out
# (hold the tag), 2 when GitHub or the registry did not answer (try again next pass).
pull_ci_image() { # image@sha256:... short-sha
	local image=$1 short=$2 body code verdict
	body=$(mktemp)
	code=$("${CURL:-curl}" -sS --max-time 30 -o "$body" -w '%{http_code}' \
		-H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' -H 'User-Agent: routemaker-beta-cd' \
		"https://api.github.com/repos/$gh_repo/attestations/sha256:${image##*@sha256:}" 2>>"$run_log") || code=000
	case "$code" in
		200) verdict=$("$py" "$logic" provenance --digest "$image" --repo "$gh_repo" <"$body") ;;
		404) verdict=no ;;
		*) verdict=unknown ;;
	esac
	rm -f "$body"
	case "$verdict" in
		ok) say "the image's provenance checks out: built by $gh_repo's release workflow on main" ;;
		no) say "the image's provenance does not check out: GitHub has no attestation that $gh_repo's release workflow on main built $image"; return 1 ;;
		*) say "GitHub answered HTTP $code for the image's attestations"; return 2 ;;
	esac
	say "step: pull the api image the release workflow built ($image)"
	quiet dk pull "$image" </dev/null && quiet dk tag "$image" "$API_IMAGE:$short" </dev/null || return 2
	quiet dk image rm "$image" </dev/null || true
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
		step "check out $tag" checkout_at "$new" || return 1
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
	rm -rf "$src"; mkdir -p "$src"; chmod 755 "$src"
	step "export the release's tree" sh -c 'umask 022 && git -C "$1" archive --format=tar "$2" | tar -x -C "$3"' sh "$RM_SRC" "$new" "$src" || return 3

	# The builds, while the beta still runs: a build that fails (pip, the network, a test) leaves
	# the running release alone, and the downtime is the stop to the smoke tests, not the builds.
	# No step is recorded yet, so a pass stopped here has nothing to roll back. The front-end
	# build is capped (1536m, killed first if the host runs short); the api build runs in the
	# daemon (BuildKit) and is not (docs/BETA-RUNBOOK.md, install step 6).
	if dk image inspect "$API_IMAGE:$new_short" >/dev/null 2>&1; then
		say "step: the api image $API_IMAGE:$new_short is already on the host (built or loaded earlier)"
	else
		build_api "$src" "$new_short" || return 3
	fi
	if [ "$(kv frontend "$gate_file")" = 1 ]; then
		out="$cd_dir/build/frontend-$new_short"
		build_frontend "$src" "$new" "$out" || { say "FAILED: the front-end test or build"; return 3; }
	fi

	# The runbook's "A new release sha", steps 2 to 8, without sudo. A release that carries no
	# migration file (most of them) keeps the api and worker running and takes no snapshot: the
	# database is not changed, so there is nothing to snapshot, and `up -d` below swaps them onto
	# the new image in seconds instead of minutes of "Router unavailable" (backlog 2026-11-12,
	# area 09 item 3). RM_CD_ALWAYS_STOP=1 keeps the old stop-and-snapshot path for every release.
	local quick=0
	if [ "$(kv migrations "$gate_file")" != 1 ] && [ "${RM_CD_ALWAYS_STOP:-0}" != 1 ] && [ -z "$restore_from" ]; then quick=1; fi
	if [ "$quick" = 1 ]; then
		say "step: no migration in this release: the api and worker keep running and no snapshot is taken; they are swapped onto the new image below"
	else
		# Riders see "Updating" from here until the pass finishes (alert.sh status; finish clears
		# it). The quick path's swap takes seconds, so it says nothing.
		rider_status updating
		mark stopped "stop the api and worker" || return 1
		step "stop the api and worker" bc stop api worker </dev/null || return 1
		mark snapshot "snapshot the database (pre-release)" || return 1
		dump=$(RECEIVE_DATA_REPO="$RM_SRC" "$receive" --env-file "$RM_SRC/.env" --backups-dir "$cd_dir/backups" snapshot-db --label release </dev/null 2>>"$run_log") && [ -s "$dump" ] ||
			{ say "FAILED: the database snapshot"; return 1; }
		printf '%s\n' "$dump" >"$cd_dir/run-snapshot"
		say "snapshot: $dump"
	fi
	mark index_saved "save the front end's top-level files (index.html, beta-build.txt)" || return 1
	saved="$cd_dir/backups/frontend.pre-release-$stamp"
	step "save the front end's top-level files" save_frontend_top "$saved" || return 1
	printf '%s\n' "$saved" >"$cd_dir/run-index"
	mark checkout "check out $tag" || return 1
	step "check out $tag" checkout_at "$new" || return 1
	[ "$(gitc rev-parse HEAD)" = "$new" ] || { say "FAILED: the checkout is not at $new"; return 1; }
	mark tag_set "set TAG=$new_short in .env" || return 1
	step "set TAG in .env" set_tag "$new_short" || return 1
	compose_gate || { say "FAILED: the compose gate (check_beta_compose.py --env-file .env); its output is in the run log"; return 1; }
	if [ -n "$restore_from" ]; then
		# `rollback --restore-db`: the database goes back to the snapshot taken before the release
		# being undone was deployed. Recorded as "migrate" (the database moved), so a failure from
		# here restores the snapshot just taken, the database as it was a minute ago.
		mark migrate "put back the database from before $deploy_old_tag was deployed ($restore_from)" || return 1
		step "restore the database from before $deploy_old_tag" env RECEIVE_DATA_REPO="$RM_SRC" "$receive" --env-file "$RM_SRC/.env" --backups-dir "$cd_dir/backups" restore-dump "$restore_from" </dev/null || return 1
	elif ! bc run --rm --no-deps migrate ./manage.py migrate --check </dev/null >>"$run_log" 2>&1; then
		# Never a migration without its snapshot: a pending one the gate did not see (no migration
		# file changed, so the database is behind the release for some other reason) fails the
		# deploy here, before the api moves; the rollback puts the checkout and TAG back.
		[ "$quick" = 0 ] || { say "FAILED: a migration is pending although the release carries no migration file; deploy it with the stop and the snapshot (RM_CD_ALWAYS_STOP=1, then auto-release.sh retry $tag)"; return 1; }
		mark migrate "migrate (after the snapshot)" || return 1
		step "migrate" bc run --rm --no-deps migrate ./manage.py migrate --noinput </dev/null || return 1
	else
		say "step: no migrations to apply"
	fi
	if [ -n "$out" ]; then
		mark frontend "install the front end (index.html last)" || return 1
		install_frontend "$out" || { say "FAILED: the front-end install"; return 1; }
	fi
	if [ "$quick" = 1 ]; then
		mark started "swap the api and worker onto the new image" || return 1
		step "swap the api and worker onto the new image" bc up -d api worker </dev/null || return 1
	else
		mark started "start the api and worker" || return 1
		step "start the api and worker" bc up -d api worker </dev/null || return 1
	fi
	# The routers to recreate or restart: the four, and each trail router whose tiles are there.
	# Road Bike's router is the one a short host leaves stopped (BETA-RUNBOOK.md, the memory
	# threshold): a stopped one without room for its startup peak is dropped from the list, so
	# no step below (recreate, start, restart) starts it. A running one stays in.
	local -a running=() all
	local router room
	read -ra all <<<"$(routers)"
	for router in "${all[@]}"; do
		if { [ "$router" = valhalla-paved ] || [ "$router" = valhalla-paved-weekend ]; } &&
			[ -z "$(bc ps -q --status running "$router" </dev/null 2>/dev/null)" ]; then
			if ! { room="$(paved_room_mib)" && [ "$room" -ge "$paved_min_mib" ]; }; then
				if [ "$router" = valhalla-paved ]; then
					say "WARNING: valhalla-paved left stopped: ${room:-unknown} MiB of the $paved_min_mib it needs (available plus what this project's containers hold); Road Bike is planned on the standard graph"
				else
					say "WARNING: valhalla-paved-weekend left stopped: ${room:-unknown} MiB of the $paved_min_mib it needs (available plus what this project's containers hold); a weekend Road Bike ride is planned on the paved graph"
				fi
				continue
			fi
		fi
		running+=("$router")
	done
	if [ "$(kv compose_changed "$gate_file")" = 1 ]; then
		mark services "recreate photon and the routers whose compose settings changed" || return 1
		step "recreate photon and the routers" bc up -d photon "${running[@]}" </dev/null || return 1
	fi
	# A trail router whose tiles are here but which is not running (never started, or stopped) is
	# started on every deploy: only a compose change recreated them before, so a beta whose trail
	# tiles arrived with a map swap planned Mountain Bike on the standard graph for releases on end.
	# `up -d` leaves a running one alone.
	local -a trail=()
	for router in "${running[@]}"; do
		case "$router" in valhalla-offroad | valhalla-mtb | valhalla-paved | valhalla-paved-weekend) trail+=("$router") ;; esac
	done
	if [ "${#trail[@]}" -gt 0 ]; then
		# Never a reason to roll a release back: without them those rides are planned on the
		# standard graph, as before.
		step "start the trail routers if they are not running" bc up -d "${trail[@]}" </dev/null ||
			say "WARNING: a trail router did not start (see the run log); Mountain Bike, Gravel and Mountain Goat are planned on the standard graph"
	fi
	if [ "$(kv routers_restart "$gate_file")" = 1 ]; then
		mark routers "restart the routers (a valhalla/*.json they read changed)" || return 1
		step "restart the routers" bc restart "${running[@]}" </dev/null || return 1
	fi
	wait_healthy || { say "FAILED: /healthz did not answer 200 (60 tries, 3 s apart)"; return 1; }
	sync_rows
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
		predraw_started=1
		if ! predraw; then
			predraw_warning="the pre-draw did not finish cleanly (tiles not yet drawn are drawn on request)"
			say "WARNING: the pre-draw did not finish cleanly; the release is live and tiles not yet drawn are drawn on request. Re-run step 8 of docs/BETA-RUNBOOK.md by hand if you want them all warm."
		fi
	fi
	return 0
}

# The plain pre-release and pre-rollback dumps go after 6.5 days (9360 minutes), as the nightly
# dumps do (config.procrastinate BACKUP_MAX_AGE): the privacy page says copies taken before an
# update stay at most a week. They stay plain because a rollback here restores them and the
# server has no key to decrypt with. Every pass runs this, so it holds between releases too.
# Spared: the snapshot a stopped pass's rollback will restore ($cd_dir/run-snapshot).
prune_aged_snapshots() {
	local keep_file f
	keep_file=$(cat "$cd_dir/run-snapshot" 2>/dev/null)
	find "$cd_dir/backups" -maxdepth 1 -type f \( -name 'pre-release-*.dump' -o -name 'pre-rollback-*.dump' \) -mmin +9360 2>/dev/null |
		while IFS= read -r f; do
			{ [ -n "$keep_file" ] && [ "$f" -ef "$keep_file" ]; } && continue
			rm -f -- "$f"
		done
}

# The databases restore-dump keeps beside the one it puts back (<db>_before_<UTC yyyymmddHHMMSS>)
# are whole copies, sign-ins and connections included, so they go after 6.5 days too, by the
# instant in the name. Every pass runs this, paused and BROKEN included. Only a name that is
# exactly <db>_before_ and 14 digits is dropped: never the live database, never one whose instant
# cannot be read or is younger. While the agent is paused or BROKEN the newest kept database is
# spared, since it may be the one the owner restores from; once it is over 6.5 days old the owner's
# channel is told (alert.sh, once a day). postgis not answering drops nothing and is tried again
# next pass.
KEPT_DB_MAX_AGE_S=561600
prune_kept_dbs() {
	local pguser pgdb names name stamp made now held="" spare="" alert="$cd_dir/bin/alert.sh"
	pguser=$(env_value PGUSER 2>/dev/null); pguser=${pguser:-routemaker}
	pgdb=$(env_value PGDATABASE 2>/dev/null); pgdb=${pgdb:-routemaker}
	case "$pguser$pgdb" in *[!A-Za-z0-9_]*) say "WARNING: PGUSER or PGDATABASE in .env is not a plain name; no kept database dropped"; return 0 ;; esac
	names=$(bc exec -T postgis psql -U "$pguser" -d postgres -At -c "select datname from pg_database where datname like '%\_before\_%' order by datname" </dev/null 2>>"$run_log") ||
		{ echo "kept databases: postgis did not answer; none dropped this pass" >>"$run_log"; return 0; }
	now=$(date -u +%s)
	if [ -f "$cd_dir/PAUSED" ]; then held=paused; elif [ -f "$cd_dir/BROKEN" ]; then held=BROKEN; fi
	# Fixed-width stamps: the last in name order is the newest.
	# shellcheck disable=SC2086 # one name per word, as the loop below reads them
	[ -z "$held" ] || spare=$(printf '%s\n' $names | grep -E "^${pgdb}_before_[0-9]{14}\$" | sort | tail -n 1)
	for name in $names; do
		[ "$name" != "$pgdb" ] || continue
		stamp=${name#"${pgdb}_before_"}
		[ "$stamp" != "$name" ] || continue
		case "$stamp" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;; *) continue ;; esac
		made=$(date -u -d "${stamp:0:4}-${stamp:4:2}-${stamp:6:2} ${stamp:8:2}:${stamp:10:2}:${stamp:12:2}" +%s 2>/dev/null) || continue
		[ $((now - made)) -gt "$KEPT_DB_MAX_AGE_S" ] || continue
		if [ "$name" = "$spare" ]; then
			say "WARNING: the kept database $name is over 6.5 days old and is kept only because the agent is $held; drop it once it is not needed: scripts/beta/beta-compose.sh exec -T postgis dropdb -U $pguser $name"
			[ ! -x "$alert" ] || "$alert" send kept-db "$name" "the kept database $name (made $stamp UTC) is over 6.5 days old and is kept only because the release agent is $held; drop it once it is not needed" >>"$run_log" 2>&1 </dev/null
			continue
		fi
		if bc exec -T postgis psql -U "$pguser" -d postgres -v ON_ERROR_STOP=1 -At -c "drop database if exists \"$name\"" </dev/null >>"$run_log" 2>&1; then
			say "dropped the kept database $name (made $stamp UTC, over 6.5 days ago)"
		else
			say "WARNING: could not drop the kept database $name (over 6.5 days old; a session may hold it); tried again next pass"
		fi
	done
	return 0
}

prune() {
	local pattern
	# A dump a stopped snapshot left half written (receive-data.sh writes <name>.part, then renames):
	# never restorable, and only a pass holding the lock writes one.
	rm -f "$cd_dir/backups"/*.dump.part "$cd_dir/backups"/*.dump.age.part
	prune_aged_snapshots
	for pattern in 'pre-release-*.dump' 'pre-rollback-*.dump' 'frontend.pre-release-*'; do
		# shellcheck disable=SC2012
		ls -1dt "$cd_dir/backups"/$pattern 2>/dev/null | tail -n +"$((keep + 1))" | while IFS= read -r f; do rm -rf -- "$f"; done
	done
	# shellcheck disable=SC2012
	ls -1t "$cd_dir/runs"/*.log 2>/dev/null | tail -n +31 | while IFS= read -r f; do rm -f -- "$f"; done
	rm -rf "$cd_dir/build"; mkdir -p "$cd_dir/build"
}

# After a deploy whose release changed the agent: its files from the deployed checkout replace the
# installed ones, each by rename, so this pass (whose script bash has already read) is not
# disturbed and the next pass runs the new ones. A copy that fails is a warning: the old agent
# keeps running, and auto-release.sh install does the rest by hand.
AGENT_BIN="auto-release.sh:700 cd_logic.py:600 receive-data.sh:700 frontend-build.sh:700 alert.sh:700"
reinstall_agent() {
	local entry name mode ok=1
	for entry in $AGENT_BIN; do
		name=${entry%:*}; mode=${entry#*:}
		[ -f "$RM_SRC/scripts/beta/$name" ] || continue
		install -m "$mode" "$RM_SRC/scripts/beta/$name" "$cd_dir/bin/.$name.new" && mv -f "$cd_dir/bin/.$name.new" "$cd_dir/bin/$name" || ok=0
	done
	if [ "$ok" = 1 ]; then
		gitc rev-parse HEAD >"$cd_dir/bin/FROM"
		say "step: the release changed the agent: its files in $cd_dir/bin are the deployed release's from the next pass"
	else
		say "WARNING: the agent's files could not all be reinstalled in $cd_dir/bin; run $RM_SRC/scripts/beta/auto-release.sh install"
	fi
}

# After a deploy, what piles up on the host (review OPS-6): api images of releases before the
# previous one (rollback C needs the previous one, and an image loaded for a later release is not
# an ancestor of the deployed commit, so it stays), BuildKit cache over a week old, and
# node_modules copies for neither the deployed nor the previous lockfile that are over 30 days old
# (a copy sent for a release still to come is newer). Never fails the pass.
prune_deployed() { # new-sha old-sha
	local new=$1 old=$2 keep_new keep_old tag h1 h2 dir n=0
	keep_new=${new:0:12}; keep_old=${old:0:12}
	for tag in $(dk image ls "$API_IMAGE" --format '{{.Tag}}' 2>/dev/null </dev/null | sort -u); do
		[[ $tag =~ ^[0-9a-f]{12}$ ]] || continue
		[ "$tag" != "$keep_new" ] && [ "$tag" != "$keep_old" ] || continue
		gitc merge-base --is-ancestor "$tag" "$new" 2>/dev/null || continue
		quiet dk image rm "$API_IMAGE:$tag" </dev/null && n=$((n + 1))
	done
	quiet dk builder prune -f --filter until=168h </dev/null || true
	h1=$(lock_hash "$new"); h2=$(lock_hash "$old")
	# Without both hashes the copies to keep are unknown: keep them all.
	[[ $h1 =~ ^[0-9a-f]{64}$ && $h2 =~ ^[0-9a-f]{64}$ ]] || { h1=""; h2=""; }
	for dir in "$cd_dir/node_modules"/*; do
		[ -n "$h1" ] || break
		[ -d "$dir" ] || continue
		case "$(basename "$dir")" in "$h1" | "$h2") continue ;; esac
		[ -n "$(find "$dir" -maxdepth 0 -mtime +30 2>/dev/null)" ] || continue
		rm -rf -- "$dir" && n=$((n + 1))
	done
	[ "$n" = 0 ] || say "pruned: $n old api image tags and node_modules copies (kept the deployed and the previous release's)"
	return 0
}

# A deploy that a stopped pass left half done: roll it back from the steps $progress records.
# Returns 0 when the pass may go on (nothing had been touched, or it had been recorded), 1 when
# the pass ends here (rolled back, or BROKEN).
recover() {
	local steps
	deploy_tag=$(kv tag "$progress"); deploy_new=$(kv new "$progress"); deploy_old=$(kv old "$progress")
	deploy_old_tag=$(kv old_tag "$progress"); steps=$(kv steps "$progress")
	say "found $progress: a pass was stopped mid-deploy of ${deploy_tag:-?} after steps: ${steps:-none} ($(kv interrupted "$progress"))"
	# Stopped inside commit_release, between its renames: deployed-sha moves to a new commit only
	# after the smoke tests passed, so that release is live; finish the record.
	if [ -n "$deploy_old" ] && [ -n "$deploy_new" ] && [ "$deploy_new" != "$deploy_old" ] && [ "$deploy_new" = "$(deployed_sha)" ] &&
		[ "$deploy_tag" != "$(deployed_tag)" ] && is_semver "$deploy_tag"; then
		{ printf '%s\n' "$deploy_old_tag" >"$cd_dir/previous-tag" && printf '%s\n' "$deploy_tag" >"$cd_dir/deployed-tag.new" &&
			mv -f "$cd_dir/deployed-tag.new" "$cd_dir/deployed-tag"; } || { finish error "could not finish recording $deploy_tag in $cd_dir"; return 1; }
		say "it had been recorded part-way (deployed-sha written, deployed-tag not): the record is finished"
	fi
	if [ -n "$deploy_new" ] && [ "$deploy_new" = "$(deployed_sha)" ] && [ "$deploy_tag" = "$(deployed_tag)" ]; then
		rm -f "$progress" "$cd_dir/run-snapshot" "$cd_dir/run-index"
		say "it had already been recorded as deployed"
		# Not this pass's deploy: a signal later in the pass must not report it as its own.
		deploy_tag=""
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
	local cur cur_sha tag new verdict reason gate_file why free h root noop=0 ci_image=""
	predraw_warning=""
	[ -f "$cd_dir/BROKEN" ] && { finish broken "a rollback failed earlier and needs the owner (see $cd_dir/BROKEN); after fixing, auto-release.sh mark-deployed <tag>"; return 1; }
	[ -f "$cd_dir/PAUSED" ] && { finish paused "$(head -n 1 "$cd_dir/PAUSED")"; return 0; }
	why=$(window_problem) && { finish error "$why (in $vars)"; return 1; }
	cur=$(deployed_tag); cur_sha=$(deployed_sha)
	[ -n "$cur" ] && [ -n "$cur_sha" ] || { finish error "no deployed tag recorded: run auto-release.sh install"; return 1; }
	[ -f "$logic" ] && [ -x "$receive" ] && [ -x "$build_fe" ] || { finish error "the agent is not installed in $cd_dir/bin: run auto-release.sh install"; return 1; }

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
	release_tag "$tag" || { hold "$tag" "a lightweight tag on a commit whose subject is not \"Release $tag\"; tag releases with git tag -a (a tag is never moved: push the next patch version)"; return 0; }
	new=$(tag_commit "$tag") || { hold "$tag" "the tag names no commit"; return 0; }
	if [ "${RM_CD_REQUIRE_SIGNED_TAGS:-0}" = 1 ]; then
		gitc verify-tag "$tag" >>"$run_log" 2>&1 || { hold "$tag" "the tag's signature does not verify (RM_CD_REQUIRE_SIGNED_TAGS=1)"; return 0; }
	fi
	gitc merge-base --is-ancestor "$new" refs/remotes/origin/main || { hold "$tag" "its commit $new is not on main"; return 0; }
	gitc merge-base --is-ancestor "$cur_sha" "$new" || { hold "$tag" "it does not descend from the deployed release $cur"; return 0; }
	# A tag the release workflow made names the api image it built from this commit, by digest
	# (.github/workflows/release.yml): that image is pulled instead of built, and a change to the
	# image's own files needs no hand ship (the owner, 2026-11-12).
	ci_image=""
	if annotated "$tag"; then ci_image=$(gitc for-each-ref --format='%(contents)' "refs/tags/$tag" | "$py" "$logic" tag-image); fi
	[ -z "$ci_image" ] || say "the tag names the api image the release workflow built: $ci_image"
	verdict=$(ci_status "$new")
	case "$verdict" in
		green) say "CI: the test and a11y check runs are green on $new" ;;
		red) hold "$tag" "GitHub's test or a11y check run is not green on $new"; return 0 ;;
		pending) finish waiting "$tag: the test or a11y check run on $new has not finished (or not started)"; return 0 ;;
		*) finish waiting "$tag: ${verdict#unknown }; trying again next pass"; return 0 ;;
	esac

	gate_file=$(mktemp)
	"$py" "$logic" gate --repo "$RM_SRC" --old "$cur_sha" --new "$new" ${ci_image:+--ci-image} >"$gate_file" || { rm -f "$gate_file"; finish error "the gate failed to run"; return 1; }
	say "gate: $(kv verdict "$gate_file") ($(kv changed_files "$gate_file") server-relevant files changed since $cur)"
	sed -n 's/^note=/note: /p' "$gate_file" | while IFS= read -r reason; do say "$reason"; done
	if [ "$(kv verdict "$gate_file")" != deploy ]; then
		sed -n 's/^reason=/needs the owner: /p' "$gate_file" | while IFS= read -r reason; do say "$reason"; done
		say "Ship it by hand with docs/BETA-RUNBOOK.md (\"Shipping an update later\"), then: auto-release.sh mark-deployed $tag"
		rm -f "$gate_file"; hold "$tag" "the release needs the owner (data from home, sudo or nginx; reasons in the report)"; return 0
	fi
	[ "$(kv agent_changed "$gate_file")" = 1 ] && say "note: this release changes the release agent itself; once it is deployed, its files are reinstalled in $cd_dir/bin for the next pass (the systemd units only by auto-release.sh install)"
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
		backup_at=$(backup_minute)
		! in_backup_slot "$backup_at" || { rm -f "$gate_file"; finish waiting "$tag: the nightly backup runs at $(hhmm "$backup_at") UTC; deploying after $(hhmm $(((backup_at + 30) % 1440))) UTC"; return 0; }
		predraw_running && { rm -f "$gate_file"; finish waiting "$tag: a stress-tile pre-draw is running; deploying after it"; return 0; }
		if [ "$(kv migrations "$gate_file")" = 1 ] || [ "${RM_CD_ALWAYS_STOP:-0}" = 1 ]; then
			free=$(free_kib "$cd_dir/backups")
			[ "${free:-0}" -ge 1048576 ] || { rm -f "$gate_file"; finish waiting "$tag: less than 1 GiB free for the snapshot in $cd_dir/backups"; return 0; }
		fi
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
	if [ "$noop" = 0 ] && [ -n "$ci_image" ] && ! dk image inspect "$API_IMAGE:${new:0:12}" >/dev/null 2>&1; then
		if [ "$dry_run" = 1 ]; then
			say "dry run: would check the provenance of $ci_image and pull it as $API_IMAGE:${new:0:12}"
		else
			pull_ci_image "$ci_image" "${new:0:12}"
			case $? in
				0) ;;
				1) rm -f "$gate_file"; hold "$tag" "the image its tag names was not built by the release workflow on main (no matching attestation)"; return 0 ;;
				*) rm -f "$gate_file"; finish waiting "$tag: could not check or pull $ci_image (GitHub, the network, or the package is not public); trying again next pass"; return 0 ;;
			esac
		fi
	fi
	if [ "$dry_run" = 1 ]; then
		say "dry run: would deploy $tag ($new) over $cur: nothing_for_the_server=$noop frontend=$(kv frontend "$gate_file") lockfile_changed=$(kv lockfile_changed "$gate_file") migrations=$(kv migrations "$gate_file") compose_changed=$(kv compose_changed "$gate_file") routers_restart=$(kv routers_restart "$gate_file") predraw=$(kv predraw "$gate_file")"
		rm -f "$gate_file"; finish dry-run "$tag would be deployed"; return 0
	fi

	say "deploying $tag ($new) over $cur at $(utc)"
	if [ "$noop" = 1 ]; then noop_release "$tag" "$new"; else deploy "$tag" "$new" "$gate_file"; fi
	local rc=$? agent_changed
	agent_changed=$(kv agent_changed "$gate_file")
	rm -f "$gate_file"
	if [ "$rc" = 0 ]; then
		[ "$agent_changed" != 1 ] || reinstall_agent
		prune
		prune_deployed "$new" "$cur_sha"
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
		prune; finish failed "$tag: the release could not be exported or built; the running release was not touched (see $cd_dir/failed/$tag; auto-release.sh retry $tag to try again)"
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
	umask 022
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
	[ "$dry_run" = 1 ] || prune_aged_snapshots
	# Paused or BROKEN too: prune_kept_dbs then spares only the newest kept database.
	[ "$dry_run" = 1 ] || prune_kept_dbs
	pass; local rc=$?
	trap - TERM INT HUP
	rm -f "$report"
	[ -s "$run_log" ] || rm -f "$run_log"
	return "$rc"
}

# --- ship-held: a held release (one that carries a map) by the owner's one command ---------------
# `auto-release.sh ship-held vX.Y.Z (--map RUN_URL | --no-map) [--allow-sha-mismatch] [--dry-run]`:
# what the per-release hand-ship scripts did, checked in. For a tag the agent held because it
# needs a map (lua/, the pipeline's graph or table builders, a graph-build setting, a migration
# naming the live schema): the same checks a pass makes (annotated or release tag, on main,
# descending from the deployed release, `test` and `a11y` green), then the code through the
# agent's own deploy (build or pull, front end, migrations after a snapshot, routers, health,
# smoke tests; a failure rolls the code back by itself), then the cloud run's map through
# scripts/cloud/import-result.sh --beta (download and verify, then --swap: it asks for sudo for the
# files and the table rename, restarts the routers one at a time, pre-draws and smoke-tests). The
# agent stays paused from the start to the end (and is resumed only if this command paused it).
# A held release that needs nginx, sudo or a new data path (deploy/, prepare_data_root.sh, a compose
# image or DATA_ROOT line, an odd file name) is still a hand ship: it says so and changes nothing.
#   --map RUN_URL         the cloud run's s3://.../transfer/<run> (built with --beta-bundle)
#   --no-map              ship the code alone; the map follows by hand (import-result.sh --beta)
#   --allow-sha-mismatch  the run was built from another commit than the tag (as import-result.sh)
#   --dry-run             the checks and the plan; changes nothing (downloads nothing)
ship_held_pass() { # tag map-url no-map allow dry
	local tag=$1 map=$2 no_map=$3 allow=$4 dry=$5 cur cur_sha new verdict gate_file why ci_image="" other map_reasons we_paused=0 rc import
	cur=$(deployed_tag); cur_sha=$(deployed_sha)
	[ ! -f "$cd_dir/BROKEN" ] || { finish broken "a rollback failed earlier and needs the owner (see $cd_dir/BROKEN)"; return 1; }
	[ "$(leftover)" = none ] || { finish error "a stopped pass left $progress; let a pass deal with it first (auto-release.sh status)"; return 1; }
	if [ "$(gitc rev-parse HEAD 2>/dev/null)" != "$cur_sha" ] || [ -n "$(gitc status --porcelain 2>/dev/null)" ] || [ "$(env_value TAG)" != "${cur_sha:0:12}" ]; then
		finish drift "the checkout is not clean at $cur ($cur_sha) with TAG=${cur_sha:0:12} in .env; put it right first"
		return 1
	fi
	why=$(origin_problem) && { finish error "$why"; return 1; }
	gitc fetch --quiet --tags origin "+refs/heads/main:refs/remotes/origin/main" >>"$run_log" 2>&1 || { finish error "git fetch failed"; return 1; }
	release_tag "$tag" || { finish error "$tag is not a release tag (annotated, or on a \"Release $tag\" commit)"; return 1; }
	new=$(tag_commit "$tag") || { finish error "$tag names no commit"; return 1; }
	[ "$new" != "$cur_sha" ] || { finish error "$tag is the deployed commit already"; return 1; }
	if [ "${RM_CD_REQUIRE_SIGNED_TAGS:-0}" = 1 ]; then gitc verify-tag "$tag" >>"$run_log" 2>&1 || { finish error "$tag's signature does not verify"; return 1; }; fi
	gitc merge-base --is-ancestor "$new" refs/remotes/origin/main || { finish error "$tag ($new) is not on main"; return 1; }
	gitc merge-base --is-ancestor "$cur_sha" "$new" || { finish error "$tag does not descend from the deployed release $cur"; return 1; }
	verdict=$(ci_status "$new")
	[ "$verdict" = green ] || { finish error "$tag: CI is ${verdict#unknown } on $new, not green (test and a11y)"; return 1; }
	if annotated "$tag"; then ci_image=$(gitc for-each-ref --format='%(contents)' "refs/tags/$tag" | "$py" "$logic" tag-image); fi
	gate_file=$(mktemp)
	"$py" "$logic" gate --repo "$RM_SRC" --old "$cur_sha" --new "$new" ${ci_image:+--ci-image} >"$gate_file" || { rm -f "$gate_file"; finish error "the gate failed to run"; return 1; }
	say "ship-held: $tag ($new) over $cur"
	sed -n 's/^note=/note: /p' "$gate_file" | while IFS= read -r why; do say "$why"; done
	map_reasons=$(sed -n 's/^map_reason=//p' "$gate_file")
	# Reasons a map does not answer (nginx, sudo, data paths, compose images, odd names; the image's
	# own files when the tag names no workflow-built image): still a hand ship.
	other=$(sed -n 's/^reason=//p' "$gate_file" | grep -vxF -f <(printf '%s\n' "$map_reasons" | grep .) || true)
	if [ -n "$other" ]; then
		printf '%s\n' "$other" | while IFS= read -r why; do say "needs the owner by hand: $why"; done
		rm -f "$gate_file"; finish error "$tag needs steps this command does not take (listed above): ship it by hand (docs/BETA-RUNBOOK.md, \"Shipping an update later\")"; return 1
	fi
	if grep -q 'a migration names the live schema' <<<"$map_reasons"; then
		printf '%s\n' "$map_reasons" | grep 'a migration names the live schema' | while IFS= read -r why; do say "needs the owner by hand: $why"; done
		rm -f "$gate_file"; finish error "$tag carries a migration that reads the map tables, which must run after the new map is in: ship it by hand (check out the tag, import-result.sh --beta, then migrate)"; return 1
	fi
	if [ -n "$map_reasons" ]; then
		printf '%s\n' "$map_reasons" | while IFS= read -r why; do say "needs a map: $why"; done
		[ -n "$map" ] || [ "$no_map" = 1 ] || { rm -f "$gate_file"; finish error "$tag needs a map built from it: give --map RUN_URL (the cloud run), or --no-map to ship the code now and the map by hand"; return 1; }
	elif [ -n "$map" ]; then
		say "note: $tag needs no map, but one was given: it is installed after the code"
	fi
	if [ "$(kv frontend "$gate_file")" = 1 ]; then
		why=$(frontend_ready "$new") || { rm -f "$gate_file"; finish error "$tag: $why"; return 1; }
	fi
	if [ "$dry" = 1 ]; then
		say "dry run: would deploy $tag's code (frontend=$(kv frontend "$gate_file") migrations=$(kv migrations "$gate_file") compose_changed=$(kv compose_changed "$gate_file") routers_restart=$(kv routers_restart "$gate_file")${ci_image:+ image=$ci_image})$([ -n "$map" ] && echo ", then install and swap the map from $map")"
		rm -f "$gate_file"; finish dry-run "$tag would be shipped"; return 0
	fi
	! predraw_running || { rm -f "$gate_file"; finish error "a stress-tile pre-draw is running; try again after it"; return 1; }
	! in_backup_slot "$(backup_minute)" || { rm -f "$gate_file"; finish error "the nightly backup runs now; try again in half an hour"; return 1; }
	if [ ! -f "$cd_dir/PAUSED" ]; then
		printf '%s ship-held %s\n' "$(utc)" "$tag" >"$cd_dir/PAUSED"; we_paused=1
	fi
	if [ -n "$ci_image" ] && ! dk image inspect "$API_IMAGE:${new:0:12}" >/dev/null 2>&1; then
		pull_ci_image "$ci_image" "${new:0:12}" ||
			{ rm -f "$gate_file"; [ "$we_paused" = 0 ] || rm -f "$cd_dir/PAUSED"; finish error "the image $ci_image did not check out or could not be pulled (above); nothing was changed"; return 1; }
	fi
	say "deploying $tag's code ($new) over $cur at $(utc)"
	deploy "$tag" "$new" "$gate_file"
	rc=$?
	rm -f "$gate_file"
	if [ "$rc" != 0 ]; then
		if [ "$rc" = 3 ]; then
			rm -f "$progress"; prune
			finish failed "$tag's code could not be exported or built; $cur was not touched (the agent stays paused: auto-release.sh resume)"
		elif rollback "$cur_sha" "${cur_sha:0:12}"; then
			rm -f "$progress" "$cd_dir/run-snapshot" "$cd_dir/run-index"; prune
			finish rolled-back "$tag's code failed and $cur is running again; no map was installed (the agent stays paused: auto-release.sh resume)"
		else
			{ echo "$(utc) ship-held $tag failed and the rollback to $cur did not complete"; cat "$report"; } >"$cd_dir/BROKEN"
			finish broken "$tag's code failed AND the rollback did not complete: the owner is needed (see $cd_dir/BROKEN and the run log)"
		fi
		return 1
	fi
	rm -f "$cd_dir/hold/$tag" "$cd_dir/failed/$tag"
	prune; prune_deployed "$new" "$cur_sha"
	say "step: $tag's code is live and recorded as deployed"
	if [ -n "$map" ]; then
		# import-result.sh --swap checks that no pass holds the lock: let it go (the pause stays,
		# so no pass deploys meanwhile).
		flock -u 9
		import="$RM_SRC/scripts/cloud/import-result.sh"
		map_importing="downloading and verifying"
		say "step: download and verify the map ($map)"
		if ! "$import" --beta --state "$RM_STATE" ${allow:+--allow-sha-mismatch} "$map" 2>&1 | tee -a "$run_log"; then
			finish error "$tag's code is live, but the map did not download or verify (above); the old map is still served. Fix it, then: $import --beta [--allow-sha-mismatch] --swap $map, and auto-release.sh resume"
			return 1
		fi
		map_importing="being swapped in"
		say "step: swap the map in (sudo is asked for the files and the table rename)"
		if ! "$import" --beta --state "$RM_STATE" ${allow:+--allow-sha-mismatch} --swap "$map" 2>&1 | tee -a "$run_log"; then
			finish error "$tag's code is live, but the map swap failed (above; import-result.sh says what it left). The way back to the old map: auto-release.sh rollback-map. Then auto-release.sh resume"
			return 1
		fi
		map_importing=""
		say "step: the map is swapped in"
	fi
	[ "$we_paused" = 0 ] || rm -f "$cd_dir/PAUSED"
	finish deployed "$tag ($new), was $cur: shipped by ship-held$([ -n "$map" ] && echo " with the map from $map")${predraw_warning:+; WARNING: $predraw_warning}$([ "$we_paused" = 0 ] && echo '; the agent was paused before and stays paused')"
	return 0
}

cmd_ship_held() {
	local tag="" map="" no_map=0 allow="" dry=0 stamp
	while [ $# -gt 0 ]; do
		case "$1" in
			--map) [ $# -ge 2 ] || die "--map needs the run's s3:// address"; map=$2; shift ;;
			--no-map) no_map=1 ;;
			--allow-sha-mismatch) allow=1 ;;
			--dry-run) dry=1 ;;
			-*) die "ship-held: unknown option $1" ;;
			*) [ -z "$tag" ] || die "ship-held takes one tag"; tag=$1 ;;
		esac
		shift
	done
	is_semver "$tag" || die "ship-held needs a vX.Y.Z tag"
	[ -z "$map" ] || [ "$no_map" = 0 ] || die "ship-held: --map or --no-map, not both"
	case "$map" in '' | s3://?*) ;; *) die "--map takes the cloud run's s3:// address" ;; esac
	case "$map" in *[!A-Za-z0-9._~:/=+-]*) die "--map: an address with a character a run's address does not use" ;; esac
	dry_run=$dry
	mkdir -p "$cd_dir/hold" "$cd_dir/failed" "$cd_dir/backups" "$cd_dir/runs" "$cd_dir/build" && chmod 700 "$cd_dir" "$cd_dir/backups"
	exec 9>"$cd_dir/lock"
	flock -n 9 || die "a pass is running; wait for it (auto-release.sh pause --wait) and try again"
	umask 022
	stamp=$(utc)
	run_log="$cd_dir/runs/$stamp-ship-held.log"; : >"$run_log"
	report=$(mktemp)
	if [ "$dry" = 0 ]; then
		trap 'on_signal TERM 143' TERM
		trap 'on_signal INT 130' INT
		trap 'on_signal HUP 129' HUP
		say "auto-release ship-held $tag at $stamp"
	else
		say "auto-release ship-held $tag at $stamp (dry run: changes nothing)"
	fi
	say "run log: $run_log"
	ship_held_pass "$tag" "$map" "$no_map" "$allow" "$dry"; local rc=$?
	trap - TERM INT HUP
	rm -f "$report"
	return "$rc"
}

# --- rollback: the previous release back, by the owner's command --------------------------------
# `auto-release.sh rollback [--dry-run] [--keep-db | --restore-db] [--force]`: the release before the
# deployed one goes back on through the same deploy a new release gets (export, image, front end,
# swap or stop, routers, health, smoke tests; a failure puts the deployed release back). The undone
# tag is then held, so no pass deploys it again; a later tag is the way forward. The owner runs it.
#   --keep-db     the release being undone carried a migration, and the database stays as it is (fine
#                 when the migration only added tables or columns with database defaults)
#   --restore-db  the database goes back to the snapshot taken just before that release was deployed:
#                 accounts, saved routes and rides changed since then are LOST (a snapshot of the
#                 database as it is now is taken first and kept in $RM_STATE/cd/backups)
#   --force       go on although the release being undone changed things outside the code (the map's
#                 tag transform or pipeline, nginx, compose images): the code goes back, they do not
rollback_pass() { # dry-run keep-db restore-db force
	local dry=$1 keep_db=$2 restore_db=$3 force=$4 cur cur_sha prev prev_sha fwd gate_file reasons other why snap=""
	cur=$(deployed_tag); cur_sha=$(deployed_sha)
	[ ! -f "$cd_dir/BROKEN" ] || { finish broken "a rollback failed earlier and needs the owner (see $cd_dir/BROKEN)"; return 1; }
	[ "$(leftover)" = none ] || { finish error "a stopped pass left $progress; let a pass deal with it first (auto-release.sh status)"; return 1; }
	is_semver "$cur" && [ -n "$cur_sha" ] || { finish error "no deployed tag recorded"; return 1; }
	prev=$(cat "$cd_dir/previous-tag" 2>/dev/null)
	is_semver "$prev" || { finish error "no previous release recorded in $cd_dir/previous-tag; roll back by hand (docs/BETA-RUNBOOK.md, \"Rollback by hand\")"; return 1; }
	# Back only: a previous-tag newer than the deployed one would be a roll forward, a new release's job.
	[ "$prev" != "$cur" ] && [ "$(printf '%s\n%s\n' "$prev" "$cur" | sort -V | head -n 1)" = "$prev" ] ||
		{ finish error "the recorded previous release $prev is not older than the deployed $cur"; return 1; }
	if [ "$(gitc rev-parse HEAD 2>/dev/null)" != "$cur_sha" ] || [ -n "$(gitc status --porcelain 2>/dev/null)" ] || [ "$(env_value TAG)" != "${cur_sha:0:12}" ]; then
		finish drift "the checkout is not clean at $cur ($cur_sha) with TAG=${cur_sha:0:12} in .env; put it right first"
		return 1
	fi
	release_tag "$prev" || { finish error "$prev is not a release tag in the checkout (git fetch --tags?)"; return 1; }
	prev_sha=$(tag_commit "$prev") || { finish error "$prev names no commit"; return 1; }
	gitc merge-base --is-ancestor "$prev_sha" "$cur_sha" || { finish error "$prev ($prev_sha) is not an ancestor of $cur"; return 1; }
	say "rollback: $cur ($cur_sha) back to $prev ($prev_sha)"

	# What the release being undone changed, read forward (previous to deployed): the same flags undo it.
	fwd=$(mktemp)
	"$py" "$logic" gate --repo "$RM_SRC" --old "$prev_sha" --new "$cur_sha" >"$fwd" || { rm -f "$fwd"; finish error "the gate failed to run"; return 1; }
	# The api image's own files are no reason to stop: the previous release's image is the one it ran.
	reasons=$(sed -n 's/^reason=//p' "$fwd")
	other=$(printf '%s\n' "$reasons" | grep -v -e '^docker/' -e '^$' || true)
	if [ -n "$other" ]; then
		printf '%s\n' "$other" | while IFS= read -r why; do say "outside the code: $why"; done
		if [ "$force" = 0 ]; then
			rm -f "$fwd"
			finish error "$cur changed things a code rollback does not undo (listed above); if the map changed, put the old map back first (auto-release.sh rollback-map), then rollback --force"
			return 1
		fi
		say "WARNING: --force: only the code goes back; the things above stay as $cur left them"
	fi
	if [ "$(kv migrations "$fwd")" = 1 ]; then
		if [ "$keep_db" = 0 ] && [ "$restore_db" = 0 ]; then
			rm -f "$fwd"
			finish error "$cur carried a migration: add --keep-db (the database stays; fine when the migration only added things with defaults) or --restore-db (the database goes back to the snapshot taken before $cur was deployed, LOSING accounts, saved routes and rides changed since)"
			return 1
		fi
		if [ "$restore_db" = 1 ]; then
			snap=$(cat "$cd_dir/deployed-snapshot" 2>/dev/null)
			[ -n "$snap" ] && [ -f "$snap" ] || { rm -f "$fwd"; finish error "no snapshot from before $cur was deployed is kept (shipped by hand, or over 6.5 days old): roll back by hand (docs/BETA-RUNBOOK.md, rollback B)"; return 1; }
			say "the database goes back to $snap (taken $(date -u -r "$snap" +%FT%TZ 2>/dev/null)); everything changed since is LOST"
		fi
	elif [ "$restore_db" = 1 ]; then
		say "note: $cur carried no migration, so the database stays as it is (--restore-db ignored)"
	fi
	# The deploy's own flags: the front end, compose and router settings as the release changed them;
	# a database put back means the stress tiles are drawn again (their cache follows the tables).
	gate_file=$(mktemp)
	{
		echo "verdict=deploy"
		for k in frontend lockfile_changed compose_changed routers_restart; do echo "$k=$(kv "$k" "$fwd")"; done
		echo "migrations=0"
		if [ -n "$snap" ] || [ "$(kv predraw "$fwd")" = 1 ]; then echo "predraw=1"; else echo "predraw=0"; fi
	} >"$gate_file"
	rm -f "$fwd"
	if [ "$(kv frontend "$gate_file")" = 1 ]; then
		why=$(frontend_ready "$prev_sha") || { rm -f "$gate_file"; finish error "$prev's front end cannot be rebuilt here: $why"; return 1; }
	fi
	if [ "$dry" = 1 ]; then
		say "dry run: would put $prev back over $cur: frontend=$(kv frontend "$gate_file") compose_changed=$(kv compose_changed "$gate_file") routers_restart=$(kv routers_restart "$gate_file") restore_db=$([ -n "$snap" ] && echo 1 || echo 0) predraw=$(kv predraw "$gate_file"); $cur would then be held"
		rm -f "$gate_file"; finish dry-run "$prev would be put back over $cur"; return 0
	fi
	[ ! -f "$cd_dir/PAUSED" ] || say "note: the agent is paused; the rollback goes on (the owner's command) and the pause stays"
	restore_from=$snap
	say "rolling back $cur to $prev at $(utc)"
	deploy "$prev" "$prev_sha" "$gate_file"
	local rc=$?
	restore_from=""
	rm -f "$gate_file"
	if [ "$rc" = 0 ]; then
		{ echo "$(utc) $cur held: rolled back to $prev by auto-release.sh rollback"; cat "$report"; } >"$cd_dir/hold/$cur"
		prune
		finish deployed "$prev ($prev_sha), rolled back from $cur, which is held (auto-release.sh retry $cur lets it deploy again)${predraw_warning:+; WARNING: $predraw_warning}"
		return 0
	fi
	if [ "$rc" = 3 ]; then
		rm -f "$progress"; prune
		finish failed "the rollback to $prev could not be exported or built; $cur was not touched and is still running"
		return 1
	fi
	if rollback "$cur_sha" "${cur_sha:0:12}"; then
		rm -f "$progress" "$cd_dir/run-snapshot" "$cd_dir/run-index"; prune
		finish rolled-back "the rollback to $prev failed, and $cur is running again (the run log says why)"
	else
		{ echo "$(utc) the rollback from $cur to $prev failed and putting $cur back did not complete"; cat "$report"; } >"$cd_dir/BROKEN"
		finish broken "the rollback to $prev failed AND putting $cur back did not complete: the owner is needed (see $cd_dir/BROKEN and the run log)"
	fi
	return 1
}

cmd_rollback() {
	local dry=0 keep_db=0 restore_db=0 force=0 stamp
	while [ $# -gt 0 ]; do
		case "$1" in
			--dry-run) dry=1 ;;
			--keep-db) keep_db=1 ;;
			--restore-db) restore_db=1 ;;
			--force) force=1 ;;
			*) die "rollback: unknown argument $1 (--dry-run, --keep-db, --restore-db, --force)" ;;
		esac
		shift
	done
	[ "$keep_db$restore_db" != 11 ] || die "rollback: --keep-db or --restore-db, not both"
	dry_run=$dry
	mkdir -p "$cd_dir" && chmod 700 "$cd_dir"
	mkdir -p "$cd_dir/hold" "$cd_dir/failed" "$cd_dir/backups" "$cd_dir/runs" "$cd_dir/build"
	chmod 700 "$cd_dir/backups"
	exec 9>"$cd_dir/lock"
	flock -n 9 || die "a pass is running; wait for it (auto-release.sh pause --wait) and try again"
	umask 022
	stamp=$(utc)
	run_log="$cd_dir/runs/$stamp-rollback.log"; : >"$run_log"
	report=$(mktemp)
	if [ "$dry" = 0 ]; then
		trap 'on_signal TERM 143' TERM
		trap 'on_signal INT 130' INT
		trap 'on_signal HUP 129' HUP
		say "auto-release rollback at $stamp"
	else
		say "auto-release rollback at $stamp (dry run: changes nothing)"
	fi
	say "run log: $run_log"
	rollback_pass "$dry" "$keep_db" "$restore_db" "$force"; local rc=$?
	trap - TERM INT HUP
	rm -f "$report"
	return "$rc"
}

# --- rollback-map: the previous map back, by the owner's command ---------------------------------
# `auto-release.sh rollback-map [--dry-run] [--graphs-only]`: rollback A and "B by rename" of
# docs/BETA-RUNBOOK.md in one line, with no sudo. Each graph's `current` and `previous` links trade
# places, and (unless --graphs-only, or there is no `live_old`) the served map tables `live` and the
# ones the last update replaced, `live_old`, trade names in one short transaction, so running it a
# second time puts the newer map back. Then the routers' settings rows follow the links, the routers
# restart one at a time, the stress tiles are pre-drawn, and the smoke tests run. Home's overrides
# and junction ratings stay the newer ones (as in "B by rename"). Run by the owner only; it holds
# the agent's lock, so no deploy runs meanwhile. A failure or a stop part-way marks the agent BROKEN
# with what had moved (a re-run would trade every pair again, so the owner puts the rest right by
# hand, as rollback A and "B by rename", then runs mark-deployed).
map_variants() { # each graph with both a current and a previous link
	local d
	for d in "$RM_DATA"/tiles/*/; do
		d=${d%/}
		[ -L "$d/current" ] && [ -L "$d/previous" ] && basename "$d"
	done
}
swap_links() { # variant: current and previous trade places, each by rename, as the owner of the dir
	local v=$1 dir="$RM_DATA/tiles/$1" cur prev img owner
	cur=$(basename "$(readlink "$dir/current")"); prev=$(basename "$(readlink "$dir/previous")")
	case "$cur$prev" in *[!A-Za-z0-9._-]* | *..*) say "FAILED: odd build names under $dir"; return 1 ;; esac
	img=$(util_image) && [ -n "$img" ] || { say "cannot find the postgis image to move the links with"; return 1; }
	owner=$(stat -c '%u:%g' "$dir")
	quiet dk run --rm --pull never --network none --user "$owner" -v "$RM_DATA/tiles:/tiles" --entrypoint sh "$img" -c \
		'cd "/tiles/$1" && ln -sfn "$2" current.new && mv -T current.new current && ln -sfn "$3" previous.new && mv -T previous.new previous' \
		sh "$v" "$prev" "$cur" </dev/null || { say "FAILED: moving the links of $v"; return 1; }
	[ "$(basename "$(readlink "$dir/current")")" = "$prev" ] || { say "FAILED: $v current is not $prev after the move"; return 1; }
	say "tiles: $v current -> $prev (previous -> $cur)"
}
has_live_old() { # postgis answers whether a live_old schema is there
	local pguser pgdb n
	pguser=$(env_value PGUSER); pguser=${pguser:-routemaker}
	pgdb=$(env_value PGDATABASE); pgdb=${pgdb:-routemaker}
	n=$(bc exec -T postgis psql -U "$pguser" -d "$pgdb" -At -c "select count(*) from pg_namespace where nspname = 'live_old'" </dev/null 2>>"$run_log") || return 2
	[ "$n" = 1 ]
}
swap_tables() { # live and live_old trade names in one transaction, every live table locked first
	local pguser pgdb
	pguser=$(env_value PGUSER); pguser=${pguser:-routemaker}
	pgdb=$(env_value PGDATABASE); pgdb=${pgdb:-routemaker}
	case "$pguser$pgdb" in *[!A-Za-z0-9_]*) say "FAILED: PGUSER or PGDATABASE in .env is not a plain name"; return 1 ;; esac
	step "trade the map tables live and live_old (one transaction)" bc exec -T postgis psql -U "$pguser" -d "$pgdb" -1 -v ON_ERROR_STOP=1 \
		-c "SET LOCAL lock_timeout = '10s'" \
		-c "DO \$\$ DECLARE t text; BEGIN FOR t IN SELECT format('%I.%I', schemaname, tablename) FROM pg_tables WHERE schemaname = 'live' ORDER BY tablename <> 'segment', tablename LOOP EXECUTE 'LOCK TABLE ' || t || ' IN ACCESS EXCLUSIVE MODE'; END LOOP; END \$\$" \
		-c "DROP SCHEMA IF EXISTS live_swap CASCADE" -c "ALTER SCHEMA live RENAME TO live_swap" \
		-c "ALTER SCHEMA live_old RENAME TO live" -c "ALTER SCHEMA live_swap RENAME TO live_old" \
		-c "TRUNCATE public.stress_tile_cache" </dev/null
}
rollback_map_pass() { # dry-run graphs-only
	local dry=$1 graphs_only=$2 variants v tables=0 r ok=1 done_what=""
	[ ! -f "$cd_dir/BROKEN" ] || { finish broken "a rollback failed earlier and needs the owner (see $cd_dir/BROKEN)"; return 1; }
	[ "$(leftover)" = none ] || { finish error "a stopped pass left $progress; let a pass deal with it first (auto-release.sh status)"; return 1; }
	variants=$(map_variants | tr '\n' ' '); variants=${variants% }
	[ -n "$variants" ] || { finish error "no graph under $RM_DATA/tiles has a previous build recorded: nothing to go back to"; return 1; }
	for v in $variants; do say "graph $v: $(basename "$(readlink "$RM_DATA/tiles/$v/current")") now, back to $(basename "$(readlink "$RM_DATA/tiles/$v/previous")")"; done
	if [ "$graphs_only" = 0 ]; then
		has_live_old; case $? in
			0) tables=1; say "map tables: live and live_old trade names (home's overrides and junction ratings stay as they are)" ;;
			1) say "map tables: there is no live_old (the last update carried no tables), so only the graphs go back" ;;
			*) finish error "postgis did not answer whether live_old is there; nothing changed"; return 1 ;;
		esac
	else
		say "map tables: left as they are (--graphs-only); the graphs and the tables are one build, so mixing them is for when only the graphs were shipped"
	fi
	if [ "$dry" = 1 ]; then finish dry-run "the map would go back: graphs $variants$([ "$tables" = 1 ] && echo ', and the tables')"; return 0; fi
	for v in $variants; do
		map_moved="$map_moved $v(started)"
		swap_links "$v" || { ok=0; break; }
		map_moved="${map_moved% "$v(started)"} $v"
		done_what="$done_what $v"
	done
	if [ "$ok" = 1 ] && [ "$tables" = 1 ]; then
		map_moved="$map_moved tables(started)"
		if swap_tables; then map_moved="${map_moved% tables(started)} tables"; done_what="$done_what tables"; else ok=0; fi
	fi
	if [ "$ok" = 0 ]; then
		{ echo "$(utc) rollback-map stopped part-way: moved${done_what:- nothing}"; cat "$report"; } >"$cd_dir/BROKEN"
		finish broken "the map rollback stopped part-way (moved:${done_what:- nothing}); the routers were not restarted. See the run log; once it is put right, auto-release.sh mark-deployed $(deployed_tag)"
		return 1
	fi
	map_moved=""
	sync_rows
	# One router at a time, as the routers' own restart hook does: a few seconds of errors for one ride type at a time.
	for r in $(routers); do
		[ -n "$(bc ps -q --status running "$r" </dev/null 2>/dev/null)" ] || continue
		step "restart $r onto the previous graph" bc restart "$r" </dev/null || ok=0
	done
	if [ "$tables" = 1 ]; then predraw || say "WARNING: the pre-draw did not finish cleanly; tiles not yet drawn are drawn on request"; fi
	{ wait_healthy && smoke; } || ok=0
	if [ "$ok" = 1 ]; then
		finish map-rolled-back "the map is back to the previous build (graphs $variants$([ "$tables" = 1 ] && echo ', tables')); run auto-release.sh rollback-map again to put the newer one back"
		return 0
	fi
	finish error "the map is back to the previous build, but a router restart or the smoke tests failed (see the run log and auto-release.sh status)"
	return 1
}
map_moved="" # what rollback-map has moved so far, for a stop part-way
map_signal() { # signal-name exit-code
	trap - TERM INT HUP
	if [ -n "$map_moved" ]; then
		{ echo "$(utc) rollback-map was stopped (SIG$1) part-way: moved$map_moved"; cat "$report"; } >"$cd_dir/BROKEN"
		finish broken "rollback-map was stopped (SIG$1) part-way (moved:$map_moved); see $cd_dir/BROKEN, put the rest right by hand, then auto-release.sh mark-deployed $(deployed_tag)"
	else
		finish interrupted "rollback-map was stopped (SIG$1) before it moved anything"
	fi
	rm -f "$report"
	exit "$2"
}
cmd_rollback_map() {
	local dry=0 graphs_only=0 stamp
	while [ $# -gt 0 ]; do
		case "$1" in
			--dry-run) dry=1 ;;
			--graphs-only) graphs_only=1 ;;
			*) die "rollback-map: unknown argument $1 (--dry-run, --graphs-only)" ;;
		esac
		shift
	done
	dry_run=$dry
	mkdir -p "$cd_dir/runs" && chmod 700 "$cd_dir"
	exec 9>"$cd_dir/lock"
	flock -n 9 || die "a pass is running; wait for it (auto-release.sh pause --wait) and try again"
	umask 022
	stamp=$(utc)
	run_log="$cd_dir/runs/$stamp-rollback-map.log"; : >"$run_log"
	report=$(mktemp)
	if [ "$dry" = 1 ]; then
		say "auto-release rollback-map at $stamp (dry run: changes nothing)"
	else
		trap 'map_signal TERM 143' TERM
		trap 'map_signal INT 130' INT
		trap 'map_signal HUP 129' HUP
		say "auto-release rollback-map at $stamp"
	fi
	say "run log: $run_log"
	rollback_map_pass "$dry" "$graphs_only"; local rc=$?
	trap - TERM INT HUP
	rm -f "$report"
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
			in_progress_line
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
	echo "api images: ${n:-0} (one a release; each deploy keeps the deployed and the previous one, for rollback C, and prunes older ones)"
	pguser=$(env_value PGUSER 2>/dev/null); pguser=${pguser:-routemaker}
	n=$(bc exec -T postgis psql -U "$pguser" -d postgres -At -c "select count(*) from pg_database where datname like '%\_before\_%'" </dev/null 2>/dev/null)
	echo "kept dbs:   ${n:-unknown} <db>_before_<time> databases left by restores (each pass drops those over 6.5 days old; paused or BROKEN, all but the newest)"
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
	pass_running || { echo "no pass is running now"; safe_by_hand; return 0; }
	if [ "$wait" = 0 ]; then
		echo "WARNING: a pass is running now ($(cat "$cd_dir/status" 2>/dev/null || echo 'see status')); pause does not stop it. Wait until it ends before working by hand: auto-release.sh pause --wait waits for it." >&2
		return 0
	fi
	echo "a pass is running now; waiting for it to end (it may be building, deploying or pre-drawing) ..."
	exec 9>>"$cd_dir/lock"
	flock 9 || die "could not wait for the running pass"
	flock -u 9
	echo "it ended: $(cat "$cd_dir/status" 2>/dev/null)"
	safe_by_hand
}
# After pause: safe to work by hand, unless a stopped pass left a deploy half done (which a paused
# agent does not roll back).
safe_by_hand() {
	if [ "$(leftover)" != half-done ]; then
		echo "it is safe to work by hand"
		return 0
	fi
	in_progress_line
	echo "It is NOT yet safe to work by hand: the api and worker may be stopped and the checkout part-way to $(kv tag "$progress") (auto-release.sh status shows where). Either resume and let one pass roll it back (auto-release.sh resume, then auto-release.sh run, then pause again), or put it right by hand and record what is running with auto-release.sh mark-deployed --force <tag>."
}
cmd_resume() { rm -f "$cd_dir/PAUSED"; echo "resumed"; }

verify_at_tag() { # tag: the checkout is clean at the tag's commit with TAG set to it
	local tag=$1 sha
	is_semver "$tag" || die "'$tag' is not a strict vX.Y.Z tag"
	release_tag "$tag" || die "$tag is not a release tag here: annotated, or on a \"Release $tag\" commit (git fetch --tags first?)"
	sha=$(tag_commit "$tag") || die "$tag names no commit"
	[ "$(gitc rev-parse HEAD)" = "$sha" ] || die "the checkout ($RM_SRC) is at $(gitc rev-parse HEAD), not $tag ($sha)"
	[ -z "$(gitc status --porcelain)" ] || die "the checkout has local changes"
	[ "$(env_value TAG)" = "${sha:0:12}" ] || die ".env's TAG is not ${sha:0:12}"
	printf '%s\n' "$sha"
}
record_deployed() { # tag sha
	printf '%s\n' "$1" >"$cd_dir/deployed-tag"; printf '%s\n' "$2" >"$cd_dir/deployed-sha"
}
cmd_mark_deployed() { # [--force] tag
	local tag="" sha url force=0
	while [ $# -gt 0 ]; do
		case "$1" in
			--force) force=1 ;;
			*) [ -z "$tag" ] || die "mark-deployed takes one tag"; tag=$1 ;;
		esac
		shift
	done
	[ -n "$tag" ] || die "mark-deployed needs a tag"
	sha=$(verify_at_tag "$tag") || exit 2
	exec 9>"$cd_dir/lock"; flock -n 9 || die "a pass is running; try again when it ends"
	# A half-done deploy's record is the next pass's rollback plan: dropping it is the owner's call
	# (--force; a BROKEN state already means the owner has looked).
	if [ "$force" = 0 ] && [ ! -f "$cd_dir/BROKEN" ] && [ "$(leftover)" = half-done ]; then
		die "a stopped pass left a deploy of $(kv tag "$progress") half done (steps $(kv steps "$progress"); $progress). Let a pass roll it back (resume, then run), or put it right by hand, check auto-release.sh status, and run mark-deployed --force $tag"
	fi
	# A release shipped by hand: what ran before it is the one `rollback` puts back, and no snapshot of
	# the agent's belongs to it.
	if is_semver "$(deployed_tag)" && [ "$(deployed_tag)" != "$tag" ]; then
		printf '%s\n' "$(deployed_tag)" >"$cd_dir/previous-tag"
		rm -f "$cd_dir/deployed-snapshot"
	fi
	record_deployed "$tag" "$sha"
	rm -f "$cd_dir/hold/$tag" "$cd_dir/failed/$tag" "$cd_dir/BROKEN" "$cd_dir/run-snapshot" "$cd_dir/run-index" "$progress"
	printf '%s marked-deployed: %s (%s) by hand\n' "$(utc)" "$tag" "$sha" | tee -a "$cd_dir/agent.log" >"$cd_dir/status"
	echo "recorded $tag ($sha) as deployed"
	# A front end shipped by hand may carry another report link: the live one is the one CD keeps.
	if [ -f "$RM_DATA/frontend/beta-build.txt" ]; then
		url=$(sed -n 's/^VITE_BETA_REPORT_URL=//p' "$RM_DATA/frontend/beta-build.txt" | head -n 1)
		# A build record without the line (an older one, or made by hand) says nothing: the link stays.
		if ! grep -q '^VITE_BETA_REPORT_URL=' "$RM_DATA/frontend/beta-build.txt"; then
			echo "report link: $(r=$(report_url); echo "${r:-none}") (kept: $RM_DATA/frontend/beta-build.txt names none)"
		elif [ ! -f "$cd_dir/report-url" ] || [ "$url" != "$(report_url)" ]; then
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
	install -m 700 "$here/frontend-build.sh" "$cd_dir/bin/frontend-build.sh"
	[ ! -f "$here/alert.sh" ] || install -m 700 "$here/alert.sh" "$cd_dir/bin/alert.sh"
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
		rollback) cmd_rollback "$@" ;;
		rollback-map) cmd_rollback_map "$@" ;;
		ship-held) cmd_ship_held "$@" ;;
		*) die "unknown command '$command' (--help)" ;;
	esac
}

# The whole file is read before anything runs, so nothing can change it under a pass.
main "$@"; exit $?
