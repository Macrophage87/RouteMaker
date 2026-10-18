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
#                                  is posted when it clears. Skipped while a deploy pass runs.
#   alert.sh send KEY ID MESSAGE   post MESSAGE unless KEY last posted the same ID (within a day)
#   alert.sh note MESSAGE          post MESSAGE (no repeat check)
#   alert.sh clear KEY MESSAGE     KEY is fine: post MESSAGE if KEY had posted, and forget it
#   alert.sh install [--no-enable] copy this script into $RM_STATE/cd/bin and write a systemd
#                                  --user timer that runs `watch` about every 10 minutes
#   alert.sh uninstall             stop and remove that timer (keeps the webhook and state)
#
# With no webhook set, nothing is posted and every command still succeeds, so the release
# agent's calls never fail a pass. Messages carry no secret and no rider's data: release tags,
# step names, the smoke tests' PASS/FAIL lines and check_operations' own report.
#
# Settings: $RM_STATE/vars.sh, as auto-release.sh reads it (RM_VARS names another file).
# CURL names the curl binary [curl]; RM_ALERT_COMPOSE and RM_ALERT_SMOKE stand in for
# beta-compose.sh and smoke-test.sh (the tests use stubs).
set -uo pipefail
export LC_ALL=C

UNIT=routemaker-beta-alert
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
	state="$RM_STATE/alerts"
	cd_dir="$RM_STATE/cd"
}

webhook() { [ -f "$hook_file" ] && head -n 1 "$hook_file" | tr -d '\r'; }
good_webhook() {
	case "$1" in https://?*) ;; *) return 1 ;; esac
	case "$1" in *[!A-Za-z0-9._~:/?#!\$\&*+,\;=%-]* | *@*) return 1 ;; esac
}

# Post one message. The address goes to curl as a config on standard input and the body as a
# file, so neither is in a process listing; the address is never printed.
post() { # message
	local url body text code
	url=$(webhook)
	[ -n "$url" ] || { echo "alert: no webhook set (alert.sh set-webhook); not posted: $1"; return 0; }
	good_webhook "$url" || { echo "alert: $hook_file does not hold a plain https:// address; not posted" >&2; return 0; }
	text="RouteMaker beta: $1"
	[ "${#text}" -le "$MAX_CHARS" ] || text="${text:0:$MAX_CHARS}..."
	body=$(mktemp)
	# allowed_mentions: no @everyone or role ping, whatever a message happens to contain.
	ALERT_TEXT=$text "$py" -c 'import json, os, sys; json.dump({"content": os.environ["ALERT_TEXT"], "allowed_mentions": {"parse": []}}, sys.stdout)' >"$body" ||
		{ rm -f "$body"; echo "alert: could not build the message" >&2; return 0; }
	code=$(printf 'url = "%s"\n' "$url" | "${CURL:-curl}" -K - -sS --max-time 20 -o /dev/null -w '%{http_code}' \
		-H 'Content-Type: application/json' --data-binary "@$body" 2>/dev/null) || code=000
	rm -f "$body"
	case "$code" in 2??) echo "alert: posted: $1"; return 0 ;; esac
	echo "alert: the webhook answered HTTP $code; not posted: $1" >&2
	return 1
}

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
	if [ -f "$cd_dir/lock" ]; then
		exec 9<"$cd_dir/lock"
		flock -n 9 || { echo "alert: a deploy pass is running; skipped"; return 0; }
		exec 9<&-
	fi
	out=$("${RM_ALERT_SMOKE:-$RM_SRC/scripts/beta/smoke-test.sh}" --local 2>&1 </dev/null); rc=$?
	if [ "$rc" = 0 ]; then
		cmd_clear site "working again: the local smoke tests pass"
	else
		fails=$(printf '%s\n' "$out" | grep -E '^(FAIL|smoke-test:)' | head -n 8)
		failing site "$(printf '%s' "$fails" | sha256sum | cut -c1-16)" \
			"the local smoke tests fail:"$'\n'"${fails:-$(printf '%s\n' "$out" | tail -n 4)}"
	fi
	out=$("${RM_ALERT_COMPOSE:-$RM_SRC/scripts/beta/beta-compose.sh}" exec -T worker ./manage.py check_operations 2>&1 </dev/null); rc=$?
	if [ "$rc" = 0 ]; then
		cmd_clear operations "check_operations is clear again"
	else
		out=$(printf '%s\n' "$out" | grep -v '^[[:space:]]*$' | head -n 12)
		failing operations "$(printf '%s' "$out" | sha256sum | cut -c1-16)" "check_operations reports:"$'\n'"$out"
	fi
	return 0
}

cmd_set_webhook() {
	local url
	[ -t 0 ] && echo "Paste the webhook address, press Enter, then Ctrl-D:" >&2
	IFS= read -r url || [ -n "$url" ] || die "no address read"
	url=${url%$'\r'}
	good_webhook "$url" || die "that is not a plain https:// address; nothing was written"
	mkdir -p "$RM_STATE"
	(umask 077 && printf '%s\n' "$url" >"$hook_file.new") && mv -f "$hook_file.new" "$hook_file"
	echo "webhook saved in $hook_file (mode 600); try it: alert.sh test"
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
	echo "installed $bin/alert.sh; units: $unit_dir/$UNIT.service, $unit_dir/$UNIT.timer"
	[ -n "$(webhook)" ] || echo "no webhook yet: alert.sh set-webhook, then alert.sh test"
	if [ "$enable" = 1 ]; then
		systemctl --user daemon-reload && systemctl --user enable --now "$UNIT.timer" || die "systemctl --user could not enable the timer"
		echo "timer enabled: $(systemctl --user is-active "$UNIT.timer")"
	else
		echo "not enabled (--no-enable): systemctl --user daemon-reload && systemctl --user enable --now $UNIT.timer"
	fi
}
cmd_uninstall() {
	local unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
	systemctl --user disable --now "$UNIT.timer" 2>/dev/null || true
	rm -f "$unit_dir/$UNIT.service" "$unit_dir/$UNIT.timer"
	systemctl --user daemon-reload 2>/dev/null || true
	echo "timer and units removed; $hook_file and $state are kept"
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
		test) post "test message from alert.sh test; alerts reach this channel" ;;
		set-webhook) cmd_set_webhook ;;
		install) cmd_install "$@" ;;
		uninstall) cmd_uninstall ;;
		*) die "unknown command '$command' (--help)" ;;
	esac
}

main "$@"; exit $?
