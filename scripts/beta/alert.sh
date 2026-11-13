#!/usr/bin/env bash
# The beta's alerts (review OPS-1): a message in the owner's Discord channel when the site or
# routing breaks, or when the release agent needs the owner (docs/BETA-RUNBOOK.md, "Alerts").
# It runs ON the beta server as the beta's login user, like auto-release.sh, with no sudo.
#
#   alert.sh set-webhook           reads the webhook address from standard input (paste it, then
#                                  Enter, then Ctrl-D) into $RM_STATE/alert-webhook, mode 600;
#                                  it is never an argument, so it is in no process list or history
#   alert.sh test                  posts one test message
#   alert.sh watch                 one check: the local smoke tests and `check_operations`; a
#                                  failure seen twice in a row is posted, and posted again only
#                                  when it changes or once a day while it lasts; "working again"
#                                  is posted when it clears. Also posts when the PC's copy of the
#                                  backups ($RM_STATE/pc-backup-pull) is over 36 h old; when the
#                                  public address (nginx, TLS, DNS) stops answering or its
#                                  certificate is near its end; when the api's log shows server
#                                  errors or slow route plans; and when a container restarts or
#                                  is killed for memory, or the host runs low on memory or disk
#                                  (docs/BETA-RUNBOOK.md, "Alerts"). Skipped while a deploy pass runs.
#   alert.sh status updating|done  the release agent's calls around a deploy: riders' status line
#                                  says "Updating" until done (see "The riders' status line")
#   alert.sh send KEY ID MESSAGE   post MESSAGE unless KEY last posted the same ID (within a day)
#   alert.sh note MESSAGE          post MESSAGE (no repeat check)
#   alert.sh clear KEY MESSAGE     KEY is fine: post MESSAGE if KEY had posted, and forget it
#   alert.sh heartbeat             ping HEALTHCHECK_PING_URL from the beta's .env (an off-host
#                                  uptime check, such as Healthchecks.io), only while the api's
#                                  local /healthz answers ok; unset, nothing is pinged
#   alert.sh scorecard             the nightly route scorecard (docs/SCORECARD.md): plan the fixed
#                                  trips on the local api, keep the run in $RM_STATE/scorecard, and
#                                  post once what moved since the nights before; nothing when
#                                  nothing moved. A run during which a container or a map changed
#                                  is kept as mixed, never compared and never posted. Waits up to
#                                  10 minutes for a deploy or watch pass; a run that fails is
#                                  posted once that day.
#   alert.sh scorecard-report      the newest kept run's whole table, against the nights before
#   alert.sh install [--no-enable] copy this script into $RM_STATE/cd/bin and write three systemd
#                                  --user timers: `watch` about every 10 minutes, `heartbeat`
#                                  every 5, `scorecard` at 3 AM Eastern
#   alert.sh uninstall             stop and remove those timers (keeps the webhook and state)
#
# Release notes go to a second channel, one riders can read and not post in:
#   alert.sh set-release-webhook   as set-webhook, into $RM_STATE/release-webhook
#   alert.sh release-test          posts one test message there
#   alert.sh release-notes TAG [FILE]
#                                  posts "RouteMaker TAG is on beta" and FILE's text (the release's
#                                  docs/releases/TAG.md), split at line ends to fit; once per tag,
#                                  resuming where a failed pass stopped (exit 1 until all posted)
#
# With no webhook set, nothing is posted and every command still succeeds, so the release
# agent's calls never fail a pass. Messages carry no secret and no rider's data: release tags,
# step names, the smoke tests' PASS/FAIL lines and check_operations' own report. Release notes are
# the repository's own rider-facing text, with no server address in them.
#
# Settings: $RM_STATE/vars.sh, as auto-release.sh reads it (RM_VARS names another file).
# The heartbeat reads three lines of the checkout's .env (BETA_ENV_FILE names another file):
# HEALTHCHECK_PING_URL, BETA_API_PORT and RM_BETA_HOST; it never sources the file.
# CURL names the curl binary [curl]; RM_ALERT_COMPOSE and RM_ALERT_SMOKE stand in for
# beta-compose.sh and smoke-test.sh, and RM_ALERT_DOCKER, RM_ALERT_OPENSSL, RM_ALERT_DF and
# RM_ALERT_MEMINFO for docker, openssl, df and /proc/meminfo (the tests use stubs).
# Thresholds, all our defaults and unmeasured until beta has a dozen riders; any can be set in
# vars.sh: RM_ALERT_TRAILS (1: the smoke tests plan on the trail graphs too; 0 for a host
# without trail routers), RM_ALERT_CERT_DAYS (14), RM_ALERT_5XX (3 in the last 10 minutes),
# RM_ALERT_SLOW_S (30 s for a route plan) and RM_ALERT_SLOW_N (3 of them), RM_ALERT_MEM_MIB
# (300 MiB available), RM_ALERT_DISK_MIB (2048 MiB free on / and on Docker's disk).
set -uo pipefail
export LC_ALL=C

UNIT=routemaker-beta-alert
HEARTBEAT_UNIT=routemaker-beta-heartbeat
SCORECARD_UNIT=routemaker-beta-scorecard
# Discord refuses a message over 2000 characters.
MAX_CHARS=1900
# A failure that lasts is posted again once a day, so a muted channel is not the only record.
REPEAT_MIN=1440

die() { echo "alert: $*" >&2; exit 2; }
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
self="$here/$(basename "${BASH_SOURCE[0]}")"
usage() { sed -n '2,/^set -uo/p' "$self" | sed '$d' | sed 's/^# \{0,1\}//'; }

load_vars() {
	vars=${RM_VARS:-$HOME/routemaker-beta-state/vars.sh}
	[ -f "$vars" ] || die "no $vars: write it first (docs/BETA-RUNBOOK.md, section 0)"
	[ "$(stat -c %u "$vars")" = "$(id -u)" ] || die "$vars is not owned by $(id -un)"
	case "$(stat -c %A "$vars")" in ?????w???? | ????????w?) die "$vars is writable by others; chmod 600 it" ;; esac
	# shellcheck disable=SC1090
	. "$vars"
	for v in RM_STATE RM_SRC; do
		[ -n "${!v:-}" ] || die "$v is not set in $vars"
		case "${!v}" in /?*) ;; *) die "$v ('${!v}') is not an absolute path" ;; esac
	done
	py=${RM_PY:-python3}
	hook_file="$RM_STATE/alert-webhook"
	release_hook_file="$RM_STATE/release-webhook"
	state="$RM_STATE/alerts"
	cd_dir="$RM_STATE/cd"
}

webhook() { [ -f "${1:-$hook_file}" ] && head -n 1 "${1:-$hook_file}" | tr -d '\r'; }
good_webhook() {
	case "$1" in https://?*) ;; *) return 1 ;; esac
	case "$1" in *[!A-Za-z0-9._~:/?#!\$\&*+,\;=%-]* | *@*) return 1 ;; esac
}

# Post one message to the webhook in FILE: 0 sent, 1 the webhook refused it, 3 not sent (no
# webhook, a bad address, no message built). The address goes to curl as a config on standard
# input and the body as a file, so neither is in a process listing; the address is never printed.
# Python builds the body and cuts it to Discord's limit by characters, never inside one.
post_to() { # file setter text
	local url body code
	url=$(webhook "$1")
	[ -n "$url" ] || { echo "alert: no webhook set (alert.sh $2); not posted: ${3%%$'\n'*}"; return 3; }
	good_webhook "$url" || { echo "alert: $1 does not hold a plain https:// address; not posted" >&2; return 3; }
	body=$(mktemp)
	# allowed_mentions: no @everyone or role ping, whatever a message happens to contain.
	ALERT_TEXT=$3 ALERT_MAX=$MAX_CHARS PYTHONUTF8=1 "$py" -c '
import json, os, sys
text, limit = os.environ["ALERT_TEXT"], int(os.environ["ALERT_MAX"])
if len(text) > limit:
    text = text[:limit] + "..."
json.dump({"content": text, "allowed_mentions": {"parse": []}}, sys.stdout)' >"$body" ||
		{ rm -f "$body"; echo "alert: could not build the message" >&2; return 3; }
	code=$(printf 'url = "%s"\n' "$url" | "${CURL:-curl}" -K - -sS --max-time 20 -o /dev/null -w '%{http_code}' \
		-H 'Content-Type: application/json' --data-binary "@$body" 2>/dev/null) || code=000
	rm -f "$body"
	case "$code" in 2??) echo "alert: posted: ${3%%$'\n'*}"; return 0 ;; esac
	echo "alert: the webhook answered HTTP $code; not posted: ${3%%$'\n'*}" >&2
	return 1
}
# The owner's channel: a message that cannot be sent at all (no webhook yet) counts as done, so
# the repeat checks and the agent behave as they did before alerts were set up.
post() {
	local rc
	post_to "$hook_file" set-webhook "RouteMaker beta: $1"; rc=$?
	[ "$rc" != 3 ] || return 0
	return "$rc"
}

# A failure's repeat-check id: its words without their numbers, so "running for 610s" and "12
# GiB free" are the same failure at the next check, not a new one to post.
same_id() { printf '%s' "$1" | sed 's/[0-9][0-9.]*/N/g' | sha256sum | cut -c1-16; }

key_ok() { [[ $1 =~ ^[a-z0-9-]+$ ]] || die "a key is lower-case letters, digits and dashes ('$1')"; }

cmd_send() { # key id message
	[ $# = 3 ] || die "send KEY ID MESSAGE"
	key_ok "$1"
	local file="$state/$1"
	mkdir -p "$state" && chmod 700 "$state"
	if [ -f "$file" ] && [ "$(head -n 1 "$file")" = "$2" ] && [ -z "$(find "$file" -mmin +"$REPEAT_MIN" 2>/dev/null)" ]; then
		return 0
	fi
	if post "$3"; then printf '%s\n%s\n' "$2" "$3" >"$file"; fi
	return 0
}
cmd_clear() { # key message
	[ $# = 2 ] || die "clear KEY MESSAGE"
	key_ok "$1"
	rm -f "$state/$1.strike"
	[ -f "$state/$1" ] || return 0
	post "$2" && rm -f "$state/$1"
	return 0
}

# One failing check: the first sighting is only remembered (a router restarting, a single slow
# answer), the second in a row is posted.
failing() { # key id message
	mkdir -p "$state" && chmod 700 "$state"
	if [ -f "$state/$1.strike" ] || [ -f "$state/$1" ]; then
		cmd_send "$1" "$2" "$3"
	else
		: >"$state/$1.strike"
		echo "alert: $1 failed once; posted if it fails again"
	fi
}

cmd_watch() {
	local out rc fails
	# A deploy stops the api on purpose: no alert for that (the agent reports its own result).
	# The lock is held for the whole check, so a deploy cannot start under it (its pass waits
	# for the next timer tick).
	if [ -f "$cd_dir/lock" ]; then
		exec 9<"$cd_dir/lock"
		flock -n 9 || { echo "alert: a deploy pass is running; skipped"; return 0; }
	fi
	local trails=--trails
	[ "${RM_ALERT_TRAILS:-1}" = 1 ] || trails=""
	# shellcheck disable=SC2086
	out=$("${RM_ALERT_SMOKE:-$RM_SRC/scripts/beta/smoke-test.sh}" --local $trails 2>&1 </dev/null); rc=$?
	if [ "$rc" = 0 ]; then
		cmd_clear site "working again: the local smoke tests pass"
		rm -f "$state/rider-strike"
		rider_parts ""
	else
		fails=$(printf '%s\n' "$out" | grep -E '^(FAIL|smoke-test:)' | head -n 8)
		failing site "$(same_id "$fails")" \
			"the local smoke tests fail:"$'\n'"${fails:-$(printf '%s\n' "$out" | tail -n 4)}"
		# Riders hear of it once it is seen twice in a row (the second check), not at a router's
		# one-off restart, whether or not Discord took the alert.
		if [ -f "$state/rider-strike" ]; then rider_parts "$(parts_of "$out")"; else rider_parts ""; fi
		: >"$state/rider-strike"
	fi
	out=$("${RM_ALERT_COMPOSE:-$RM_SRC/scripts/beta/beta-compose.sh}" exec -T worker ./manage.py check_operations 2>&1 </dev/null); rc=$?
	if [ "$rc" = 0 ]; then
		cmd_clear operations "check_operations is clear again"
	else
		out=$(printf '%s\n' "$out" | grep -v '^[[:space:]]*$' | head -n 12)
		failing operations "$(same_id "$out")" "check_operations reports:"$'\n'"$out"
	fi
	watch_pc_pull
	watch_public
	watch_api_log
	watch_containers
	watch_host
	return 0
}

# --- The riders' status line ---------------------------------------------------------------------
# A small status.json beside the front end (nginx: location = /status.json, read from
# $RM_DATA/status), which the app reads at open and when a request fails, and shows as one line
# only while something is wrong. nginx serves it even while the api is stopped for a deploy.
# {"state": "updating"} while the release agent deploys; {"state": "degraded", "parts": [...]}
# while the watch's smoke tests fail (routing, trails, search); no file at all when all is well.
# No $RM_DATA/status directory (made once at install, BETA-RUNBOOK.md "Alerts"), nothing written.
status_dir() { printf '%s' "${RM_STATUS_DIR:-${RM_DATA:+$RM_DATA/status}}"; }

# What the riders cannot do, from the smoke tests' FAIL lines: routing (no health, no route),
# trails (a trail graph), search (place search or a place name).
parts_of() {
	local fails parts=""
	fails=$(printf '%s\n' "$1" | grep '^FAIL')
	printf '%s\n' "$fails" | grep -qE 'healthz|a route comes back' && parts="$parts routing"
	printf '%s\n' "$fails" | grep -qE 'graph' && parts="$parts trails"
	printf '%s\n' "$fails" | grep -qE 'place search|place name' && parts="$parts search"
	printf '%s' "${parts# }"
}

rider_parts() { # "routing trails search" or "" (all well)
	mkdir -p "$state" && chmod 700 "$state"
	printf '%s\n' "$1" >"$state/rider-parts"
	write_status
}

write_status() {
	local dir json parts
	dir=$(status_dir)
	[ -n "$dir" ] && [ -d "$dir" ] || return 0
	parts=$(cat "$state/rider-parts" 2>/dev/null)
	if [ -f "$state/rider-updating" ]; then
		json='{"state": "updating"}'
	elif [ -n "$parts" ]; then
		json=$(printf '%s\n' $parts | sed 's/.*/"&"/' | paste -sd, - | sed 's/,/, /g; s/^/{"state": "degraded", "parts": [/; s/$/]}/')
	else
		rm -f "$dir/status.json"
		return 0
	fi
	(umask 022 && printf '%s\n' "$json" >"$dir/.status.json.new") && mv -f "$dir/.status.json.new" "$dir/status.json"
}

cmd_status() { # updating | done
	mkdir -p "$state" && chmod 700 "$state"
	case "${1:-}" in
		updating) : >"$state/rider-updating" ;;
		done) rm -f "$state/rider-updating" ;;
		*) die "status updating|done" ;;
	esac
	write_status
	return 0
}

# The public address, as a tester's phone reaches it: DNS, nginx and TLS, which the local smoke
# tests and the heartbeat (both on 127.0.0.1) never pass through. Asked from this host, so a dead
# host is still the heartbeat's to report. 200 "ok" or 401 (a site password) both mean nginx and
# the api answered. No RM_BETA_HOST, no check.
watch_public() {
	local host code body days end
	host=${RM_BETA_HOST:-$(env_value RM_BETA_HOST)}
	host=${host:-${RM_CD_HOST:-}}
	[ -n "$host" ] || return 0
	body=$(mktemp)
	code=$("${CURL:-curl}" -sS --max-time 20 -o "$body" -w '%{http_code}' "https://$host/healthz" 2>/dev/null </dev/null) || code=000
	if { [ "$code" = 200 ] && grep -q '^ok' "$body"; } || [ "$code" = 401 ]; then
		cmd_clear public "the public address answers again"
	else
		failing public "$code" "the public address does not answer (/healthz through nginx and TLS: HTTP $code). Check nginx (sudo nginx -t), DNS and the certificate."
	fi
	rm -f "$body"
	command -v "${RM_ALERT_OPENSSL:-openssl}" >/dev/null 2>&1 || return 0
	end=$(timeout 20 "${RM_ALERT_OPENSSL:-openssl}" s_client -servername "$host" -connect "$host:443" </dev/null 2>/dev/null |
		"${RM_ALERT_OPENSSL:-openssl}" x509 -noout -enddate 2>/dev/null | sed -n 's/^notAfter=//p')
	[ -n "$end" ] || return 0
	end=$(date -u -d "$end" +%s 2>/dev/null) || return 0
	days=$(((end - $(date -u +%s)) / 86400))
	if [ "$days" -lt "${RM_ALERT_CERT_DAYS:-14}" ]; then
		cmd_send certificate "$(date -u -d "@$end" +%F)" "the public address's certificate ends in $days days ($(date -u -d "@$end" +%F)); its renewal has failed. See sudo certbot renew --dry-run."
	else
		cmd_clear certificate "the certificate was renewed ($days days left)"
	fi
}

# The api's access log for the last ten minutes (docker/api-entrypoint.sh's format: time, "METHOD
# path", status, bytes, microseconds, agent; paths already carry no ids): server errors and slow
# route plans, which a tester sees as a failed or endless plan and may never report.
watch_api_log() {
	local lines n5 slow
	lines=$("${RM_ALERT_COMPOSE:-$RM_SRC/scripts/beta/beta-compose.sh}" logs --no-color --no-log-prefix --since 10m api 2>/dev/null </dev/null |
		grep -oE '"[A-Z]+ [^" ]+" [0-9]{3} [0-9-]+ [0-9]+') || lines=""
	# 500, 502, 504 and up: a 503 is the planner's own "busy, try again" when both routing
	# slots are full, which the slow-plans check below reports as what it is.
	n5=$(printf '%s\n' "$lines" | awk '$3 ~ /^5/ && $3 != 503' | grep -c .)
	slow=$(printf '%s\n' "$lines" | awk -v s="${RM_ALERT_SLOW_S:-30}" '$2 ~ /^\/api\/route"?$/ && $5 >= s * 1000000' | grep -c .)
	if [ "$n5" -ge "${RM_ALERT_5XX:-3}" ]; then
		cmd_send server-errors "5xx" "the api answered $n5 requests with a server error in the last 10 minutes:"$'\n'"$(printf '%s\n' "$lines" | awk '$3 ~ /^5/ && $3 != 503 { print $1, $2, $3 }' | tr -d '"' | sort | uniq -c | sort -rn | head -n 5)"
	else
		cmd_clear server-errors "server errors are back under ${RM_ALERT_5XX:-3} in 10 minutes"
	fi
	if [ "$slow" -ge "${RM_ALERT_SLOW_N:-3}" ]; then
		cmd_send slow-plans "slow" "$slow route plans took over ${RM_ALERT_SLOW_S:-30} s in the last 10 minutes (riders wait for one of beta's two routing slots; docs/BETA-RUNBOOK.md, \"Alerts\")"
	else
		cmd_clear slow-plans "route plans are quick again"
	fi
}

# Each container's restarts and out-of-memory kills, against the last check's counts
# ($state/restart-counts, never an alert key): compose restarts a killed container on its own, so without this a memory
# spike in the middle of a ride leaves no trace but a failed plan.
watch_containers() {
	local ids now prev="$state/restart-counts" news=""
	command -v "${RM_ALERT_DOCKER:-docker}" >/dev/null 2>&1 || return 0
	ids=$("${RM_ALERT_COMPOSE:-$RM_SRC/scripts/beta/beta-compose.sh}" --profile offroad ps -a -q 2>/dev/null </dev/null | grep -E '^[0-9a-f]+$') || return 0
	# shellcheck disable=SC2086
	now=$("${RM_ALERT_DOCKER:-docker}" inspect -f '{{.Name}} {{.RestartCount}} {{.State.OOMKilled}}' $ids 2>/dev/null | sed 's|^/||') || return 0
	[ -n "$now" ] || return 0
	mkdir -p "$state" && chmod 700 "$state"
	if [ -f "$prev" ]; then
		news=$(awk 'NR == FNR { seen[$1] = $2; next } ($1 in seen) && $2 > seen[$1] { printf "%s restarted %d time(s)%s\n", $1, $2 - seen[$1], ($3 == "true" ? ", killed for memory" : "") }' "$prev" - <<<"$now")
	fi
	printf '%s\n' "$now" >"$prev"
	[ -z "$news" ] || cmd_send restarts "$(printf '%s' "$now" | sha256sum | cut -c1-16)" "containers restarted since the last check:"$'\n'"$news"
}

# The host itself: memory available to new processes (beta has no swap, so a spike kills a
# container) and free space on / and on Docker's disk.
watch_host() {
	local avail root dir free low=""
	avail=$(awk '/^MemAvailable:/ { print int($2 / 1024) }' "${RM_ALERT_MEMINFO:-/proc/meminfo}" 2>/dev/null)
	if [ -n "$avail" ] && [ "$avail" -lt "${RM_ALERT_MEM_MIB:-300}" ]; then
		failing memory "low" "the host has only $avail MiB of memory available (under ${RM_ALERT_MEM_MIB:-300}); the next spike kills a container"
	else
		cmd_clear memory "the host's memory is back over ${RM_ALERT_MEM_MIB:-300} MiB available"
	fi
	root=""
	command -v "${RM_ALERT_DOCKER:-docker}" >/dev/null 2>&1 && root=$("${RM_ALERT_DOCKER:-docker}" info -f '{{.DockerRootDir}}' 2>/dev/null </dev/null)
	for dir in / ${root:+"$root"}; do
		free=$("${RM_ALERT_DF:-df}" -Pm "$dir" 2>/dev/null | awk 'NR == 2 { print $4 }')
		[ -n "$free" ] && [ "$free" -lt "${RM_ALERT_DISK_MIB:-2048}" ] && low="$low $dir ($free MiB free)"
	done
	if [ -n "$low" ]; then
		failing disk "$(printf '%s' "$low" | sed 's/[0-9]* MiB//')" "the host is short of disk:$low (under ${RM_ALERT_DISK_MIB:-2048} MiB). See docs/BETA-RUNBOOK.md, \"Disk\" under continuous deployment."
	else
		cmd_clear disk "the host has enough disk again"
	fi
}

# The nightly route scorecard (docs/SCORECARD.md; the owner, 2026-11-12, "Both": nightly on the
# beta and on the PC when he starts it). It plans through the api's own /api/route on this host,
# so riders' routing slots and rate limits apply to it as to anyone, one plan at a time. What
# serves the plans is fingerprinted before and after (every container, routers included, and each
# graph's `current` build): a run that saw a deploy, a map swap or a router restart is kept as
# mixed and says nothing.
scorecard_dir() { printf '%s/scorecard' "$RM_STATE"; }
scorecard_print() { # what serves routes: every container (api and routers) and each graph's build
	local data link
	"${RM_ALERT_COMPOSE:-$RM_SRC/scripts/beta/beta-compose.sh}" ps -q 2>/dev/null </dev/null | sort
	data=${RM_SCORECARD_DATA_ROOT:-${RM_DATA:-$(env_value DATA_ROOT)}}
	[ -n "$data" ] || return 0
	for link in "$data"/tiles/*/current; do
		[ -e "$link" ] || [ -L "$link" ] || continue
		printf '%s %s\n' "$link" "$(readlink "$link")"
	done
}
cmd_scorecard() {
	local port host dir before after newest out id
	if [ -f "$cd_dir/lock" ]; then
		exec 9<"$cd_dir/lock"
		# The watch pass holds this lock for a minute or two every few minutes, a deploy for longer.
		flock -w "${RM_SCORECARD_LOCK_WAIT_S:-600}" 9 || { echo "alert: a deploy pass held the lock for 10 minutes; scorecard skipped tonight"; return 0; }
		flock -u 9
	fi
	port=$(env_value BETA_API_PORT)
	host=${RM_BETA_HOST:-$(env_value RM_BETA_HOST)}
	host=${host:-${RM_CD_HOST:-}}
	[ -n "$host" ] || { echo "alert: no RM_BETA_HOST in .env; scorecard not run" >&2; return 0; }
	dir=$(scorecard_dir)
	mkdir -p "$dir" && chmod 700 "$dir"
	before=$(scorecard_print | sha256sum | cut -c1-16)
	"$py" "$RM_SRC/scripts/route_scorecard.py" nightly --base-url "http://127.0.0.1:${port:-8087}" \
		--host "$host" --dir "$dir" </dev/null || {
		echo "alert: the scorecard run failed" >&2
		cmd_send scorecard-failed "$(date -u +%F)" "the nightly route scorecard did not run (see journalctl --user -u $SCORECARD_UNIT)"
		return 0
	}
	after=$(scorecard_print | sha256sum | cut -c1-16)
	newest=$(find "$dir" -maxdepth 1 -name 'run-*Z.json' | sort | tail -n 1)
	[ -n "$newest" ] || return 0
	if [ "$before" != "$after" ]; then
		mv "$newest" "${newest%.json}.mixed.json"
		echo "alert: the api or a map changed during the scorecard run; kept as mixed, not compared"
		return 0
	fi
	out=$("$py" "$RM_SRC/scripts/route_scorecard.py" findings --dir "$dir" </dev/null) || return 0
	id=$(printf '%s\n' "$out" | head -n 1 | tr -cd '0-9TZ')
	[ -n "$id" ] || { echo "alert: scorecard: nothing moved"; return 0; }
	cmd_send scorecard "$id" "$(printf '%s\n' "$out" | tail -n +2)"
}

# The owner's PC copies the nightly dumps off this host (scripts/pc/pull-beta-backups.sh) and,
# after each run that ends ok, writes the newest dump's name to $RM_STATE/pc-backup-pull. Once that
# file is over PC_PULL_STALE_MIN old the copy has stopped: failing, or not running at all. No file
# means the PC copy is not set up, and nothing is said.
PC_PULL_STALE_MIN=2160
watch_pc_pull() {
	local mark="$RM_STATE/pc-backup-pull" last
	[ -f "$mark" ] || return 0
	last=$(head -n 1 "$mark" | tr -cd 'A-Za-z0-9._-')
	if [ -n "$(find "$mark" -mmin +"$PC_PULL_STALE_MIN" 2>/dev/null)" ]; then
		cmd_send pc-backup-pull "$last" "the PC has not copied the beta's backups for over $((PC_PULL_STALE_MIN / 60)) h (last copied: ${last:-unknown}, $(date -u -r "$mark" +%Y-%m-%dT%H:%MZ)). See pull-beta-backups.log on the PC and docs/OPERATIONS.md, \"Off-box copies of beta backups\"."
	else
		cmd_clear pc-backup-pull "the PC is copying the beta's backups again (newest ${last:-unknown})"
	fi
}

# One value from the beta's .env: the last line naming the key, without quotes. Only that key is
# read; the file is never sourced (it holds every secret the stack has).
env_value() {
	sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "${BETA_ENV_FILE:-$RM_SRC/.env}" 2>/dev/null |
		tail -n 1 | tr -d '\r' | sed "s/^['\"]//; s/['\"]\$//"
}

# The off-host uptime check: the service tells the owner when the pings stop, which covers what
# nothing on this host can report (the host, Docker, the timers or the webhook gone). It pings
# only while the api answers its own health check, so a dead api stops the pings like a dead host.
# Exit 0 whether or not it pinged: a missing or odd setting is a line in the journal, not a failure.
cmd_heartbeat() {
	local url port host answer code
	url=$(env_value HEALTHCHECK_PING_URL)
	[ -n "$url" ] || { echo "alert: no HEALTHCHECK_PING_URL in .env; not pinged"; return 0; }
	good_webhook "$url" || { echo "alert: HEALTHCHECK_PING_URL is not a plain https:// address; not pinged" >&2; return 0; }
	port=$(env_value BETA_API_PORT)
	host=${RM_BETA_HOST:-$(env_value RM_BETA_HOST)}
	host=${host:-${RM_CD_HOST:-}}
	[ -n "$host" ] || { echo "alert: no RM_BETA_HOST in .env; not pinged" >&2; return 0; }
	answer=$("${CURL:-curl}" -sS --max-time 10 -H "Host: $host" "http://127.0.0.1:${port:-8087}/healthz" 2>/dev/null </dev/null) || answer=""
	case "$answer" in
		ok*) ;;
		*) echo "alert: the api's /healthz did not answer ok; not pinged"; return 0 ;;
	esac
	# The address goes to curl as a config on standard input, like the webhook: never an argument.
	code=$(printf 'url = "%s"\n' "$url" | "${CURL:-curl}" -K - -sS --max-time 10 --retry 2 -o /dev/null -w '%{http_code}' 2>/dev/null) || code=000
	case "$code" in
		2??) echo "alert: healthy; pinged" ;;
		*) echo "alert: the uptime check answered HTTP $code; not pinged" >&2 ;;
	esac
	return 0
}

cmd_set_webhook() { # file test-command
	local url
	[ -t 0 ] && echo "Paste the webhook address, press Enter, then Ctrl-D:" >&2
	IFS= read -r url || [ -n "$url" ] || die "no address read"
	url=${url%$'\r'}
	good_webhook "$url" || die "that is not a plain https:// address; nothing was written"
	mkdir -p "$RM_STATE"
	(umask 077 && printf '%s\n' "$url" >"$1.new") && mv -f "$1.new" "$1"
	echo "webhook saved in $1 (mode 600); try it: alert.sh $2"
}

# A release's notes in the release channel: the title, then the notes in as many messages as
# Discord needs, cut at line ends (a line longer than a message is cut by characters). Python
# does the cutting, so a cut never lands inside a character. state/release-posted holds "TAG"
# once every message is posted, or "TAG:N" after the first N: a failed pass resumes there.
# Exit 0 posted, already posted or nothing to post to; 1 not (yet) posted, tried again next time.
cmd_release_notes() { # tag [file]
	[ $# = 1 ] || [ $# = 2 ] || die "release-notes TAG [FILE]"
	[[ $1 =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "a tag is vX.Y.Z ('$1')"
	local tag=$1 file=${2:-} posted="$state/release-posted" url dir count done_n=0 n rc
	url=$(webhook "$release_hook_file")
	[ -n "$url" ] || { echo "alert: no release webhook set (alert.sh set-release-webhook); notes for $tag not posted"; return 0; }
	good_webhook "$url" || { echo "alert: $release_hook_file does not hold a plain https:// address; notes for $tag not posted" >&2; return 0; }
	mkdir -p "$state" && chmod 700 "$state"
	if [ -f "$posted" ] && grep -qxF "$tag" "$posted"; then echo "alert: notes for $tag were already posted"; return 0; fi
	[ -f "$posted" ] && n=$(grep -E "^${tag//./\\.}:[0-9]+$" "$posted" | tail -n 1) && done_n=${n#*:}
	dir=$(mktemp -d)
	count=$(PYTHONUTF8=1 "$py" - "$file" "**RouteMaker $tag is on beta**" "$MAX_CHARS" "$dir" <<'PY'
import pathlib, sys
path, title, limit, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), pathlib.Path(sys.argv[4])
lines = [title]
if path and pathlib.Path(path).is_file():
    lines += [""] + pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
chunks, cur, size = [], [], 0
for line in lines:
    line = line.rstrip()
    for piece in [line[i : i + limit] for i in range(0, len(line), limit)] or [""]:
        add = len(piece) + (1 if cur else 0)
        if cur and size + add > limit:
            chunks.append("\n".join(cur))
            cur, size, add = [], 0, len(piece)
        cur.append(piece)
        size += add
chunks.append("\n".join(cur))
chunks = [c.strip("\n") for c in chunks if c.strip()]
for n, chunk in enumerate(chunks):
    (out / str(n)).write_text(chunk, encoding="utf-8")
print(len(chunks))
PY
	) || { rm -rf "$dir"; echo "alert: could not read the notes for $tag" >&2; return 1; }
	for ((n = done_n; n < count; n++)); do
		[ "$n" = "$done_n" ] || sleep "${RM_ALERT_CHUNK_SLEEP:-1}"
		post_to "$release_hook_file" set-release-webhook "$(cat "$dir/$n")"; rc=$?
		if [ "$rc" != 0 ]; then
			record_release "$tag" "$tag:$n"
			rm -rf "$dir"
			echo "alert: notes for $tag stopped after $n of $count messages; the rest are tried next time" >&2
			return 1
		fi
	done
	rm -rf "$dir"
	record_release "$tag" "$tag"
	return 0
}
record_release() { # tag line: the tag's one line in release-posted
	local posted="$state/release-posted"
	{ [ ! -f "$posted" ] || grep -vE "^${1//./\\.}(:[0-9]+)?$" "$posted"; printf '%s\n' "$2"; } >"$posted.new"
	mv -f "$posted.new" "$posted"
}

cmd_install() {
	local enable=1 unit_dir bin="$cd_dir/bin"
	[ "${1:-}" != --no-enable ] || { enable=0; shift; }
	[ $# = 0 ] || die "install takes only --no-enable"
	[ "$(id -u)" != 0 ] || die "run this as the beta's login user, not root"
	for c in curl flock sha256sum "$py"; do command -v "$c" >/dev/null 2>&1 || die "$c is not installed"; done
	mkdir -p "$bin" && chmod 700 "$cd_dir"
	install -m 700 "$self" "$bin/alert.sh"
	unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
	mkdir -p "$unit_dir"
	cat >"$unit_dir/$UNIT.service" <<UNITEOF
# Written by scripts/beta/alert.sh install (docs/BETA-RUNBOOK.md, "Alerts").
[Unit]
Description=RouteMaker beta: check the site and post an alert if it is broken

[Service]
Type=oneshot
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=RM_VARS=$vars
ExecStart="$bin/alert.sh" watch
TimeoutStartSec=10min
Nice=10
UNITEOF
	cat >"$unit_dir/$UNIT.timer" <<UNITEOF
# Written by scripts/beta/alert.sh install (docs/BETA-RUNBOOK.md, "Alerts").
[Unit]
Description=RouteMaker beta: check the site about every 10 minutes

[Timer]
OnActiveSec=3min
OnUnitInactiveSec=10min
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
UNITEOF
	cat >"$unit_dir/$HEARTBEAT_UNIT.service" <<UNITEOF
# Written by scripts/beta/alert.sh install (docs/BETA-RUNBOOK.md, "Alerts").
[Unit]
Description=RouteMaker beta: ping the off-host uptime check while the api is healthy

[Service]
Type=oneshot
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=RM_VARS=$vars
ExecStart="$bin/alert.sh" heartbeat
TimeoutStartSec=2min
UNITEOF
	cat >"$unit_dir/$HEARTBEAT_UNIT.timer" <<UNITEOF
# Written by scripts/beta/alert.sh install (docs/BETA-RUNBOOK.md, "Alerts").
[Unit]
Description=RouteMaker beta: ping the uptime check every 5 minutes

[Timer]
OnActiveSec=1min
OnUnitActiveSec=5min
AccuracySec=20s

[Install]
WantedBy=timers.target
UNITEOF
	cat >"$unit_dir/$SCORECARD_UNIT.service" <<UNITEOF
# Written by scripts/beta/alert.sh install (docs/SCORECARD.md).
[Unit]
Description=RouteMaker beta: the nightly route scorecard

[Service]
Type=oneshot
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=RM_VARS=$vars
ExecStart="$bin/alert.sh" scorecard
TimeoutStartSec=120min
Nice=10
UNITEOF
	cat >"$unit_dir/$SCORECARD_UNIT.timer" <<UNITEOF
# Written by scripts/beta/alert.sh install (docs/SCORECARD.md).
[Unit]
Description=RouteMaker beta: the route scorecard at 3 AM Eastern

[Timer]
OnCalendar=*-*-* 03:00:00 America/New_York
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
UNITEOF
	echo "installed $bin/alert.sh; units: $unit_dir/$UNIT.{service,timer}, $unit_dir/$HEARTBEAT_UNIT.{service,timer}, $unit_dir/$SCORECARD_UNIT.{service,timer}"
	[ -n "$(webhook)" ] || echo "no webhook yet: alert.sh set-webhook, then alert.sh test"
	[ -n "$(env_value HEALTHCHECK_PING_URL)" ] || echo "no HEALTHCHECK_PING_URL in .env yet: the heartbeat pings nothing until it is there"
	if [ "$enable" = 1 ]; then
		systemctl --user daemon-reload && systemctl --user enable --now "$UNIT.timer" "$HEARTBEAT_UNIT.timer" "$SCORECARD_UNIT.timer" ||
			die "systemctl --user could not enable the timers"
		echo "timers enabled: $(systemctl --user is-active "$UNIT.timer" "$HEARTBEAT_UNIT.timer" "$SCORECARD_UNIT.timer" | tr '\n' ' ')"
	else
		echo "not enabled (--no-enable): systemctl --user daemon-reload && systemctl --user enable --now $UNIT.timer $HEARTBEAT_UNIT.timer $SCORECARD_UNIT.timer"
	fi
}
cmd_uninstall() {
	local unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user unit
	for unit in "$UNIT" "$HEARTBEAT_UNIT" "$SCORECARD_UNIT"; do
		systemctl --user disable --now "$unit.timer" 2>/dev/null || true
		rm -f "$unit_dir/$unit.service" "$unit_dir/$unit.timer"
	done
	systemctl --user daemon-reload 2>/dev/null || true
	echo "timers and units removed; $hook_file, $release_hook_file and $state are kept"
}

main() {
	local command=${1:-}
	case "$command" in '' | -h | --help) usage; return 0 ;; esac
	shift
	load_vars
	case "$command" in
		send) cmd_send "$@" ;;
		note) [ $# = 1 ] || die "note MESSAGE"; post "$1"; return 0 ;;
		clear) cmd_clear "$@" ;;
		watch) cmd_watch ;;
		status) [ $# = 1 ] || die "status updating|done"; cmd_status "$1" ;;
		heartbeat) cmd_heartbeat ;;
		scorecard) cmd_scorecard ;;
		scorecard-report) "$py" "$RM_SRC/scripts/route_scorecard.py" report --dir "$(scorecard_dir)" ;;
		test) post "test message from alert.sh test; alerts reach this channel" ;;
		set-webhook) cmd_set_webhook "$hook_file" test ;;
		release-test) post_to "$release_hook_file" set-release-webhook "RouteMaker: test message; release notes reach this channel"; [ $? != 1 ] ;;
		set-release-webhook) cmd_set_webhook "$release_hook_file" release-test ;;
		release-notes) cmd_release_notes "$@" ;;
		install) cmd_install "$@" ;;
		uninstall) cmd_uninstall ;;
		*) die "unknown command '$command' (--help)" ;;
	esac
}

main "$@"; exit $?
