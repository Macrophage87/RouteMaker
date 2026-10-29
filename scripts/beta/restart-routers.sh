#!/usr/bin/env bash
# Restart a router whose map was swapped under it (the owner, 2026-10-29). valhalla_service opens
# its tiles once at start, so after `tiles/<variant>/current` moves (a data ship, a rollback, a
# rebuild's swap) the running router serves the old build until it is restarted
# (docs/OPERATIONS.md, "After a rebuild: restart the routers"). This is the host-side hook that
# does that restart; `check_operations` still flags a router left on an older build after an hour,
# as the backstop. It runs ON the beta server as the beta's login user, with no sudo.
#
#   restart-routers.sh check             one pass: restart each running router that started
#                                        before its variant's `current` link last changed, once
#                                        the link has been still for RM_ROUTER_SETTLE_S seconds
#                                        (a swap that fails undoes itself well inside that)
#   restart-routers.sh install [--no-enable]
#                                        copy this script into $RM_STATE/cd/bin and write a
#                                        systemd --user timer that runs `check` every 2 minutes
#   restart-routers.sh uninstall         stop and remove that timer
#
# The routers are the four, plus each trail router whose `current` link is on this host, as the
# release agent starts them. A router that is not running is left alone (starting one is the
# deploy's or the owner's call), and so is everything while a deploy pass holds the agent's lock.
# Restarts go one at a time, a few seconds of 502s each for that ride type.
#
# Settings: $RM_STATE/vars.sh, as auto-release.sh reads it (RM_VARS names another file):
# RM_STATE, RM_SRC and RM_DATA. RM_ROUTER_SETTLE_S [300]. RM_ROUTER_COMPOSE stands in for
# beta-compose.sh and DOCKER for docker (the tests use stubs).
set -uo pipefail
export LC_ALL=C

UNIT=routemaker-beta-routers
ROUTERS="valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend"
TRAIL_ROUTERS="valhalla-offroad valhalla-mtb"

die() { echo "restart-routers: $*" >&2; exit 2; }
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
	for v in RM_STATE RM_SRC RM_DATA; do
		[ -n "${!v:-}" ] || die "$v is not set in $vars"
		case "${!v}" in /?*) ;; *) die "$v ('${!v}') is not an absolute path" ;; esac
	done
	settle=${RM_ROUTER_SETTLE_S:-300}
	[[ $settle =~ ^[0-9]+$ ]] || die "RM_ROUTER_SETTLE_S is a number of seconds ('$settle')"
	cd_dir="$RM_STATE/cd"
}

# Every call names the offroad profile, so the trail routers are found like the four.
bc() { "${RM_ROUTER_COMPOSE:-$RM_SRC/scripts/beta/beta-compose.sh}" --profile offroad "$@"; }

cmd_check() {
	local router variant link changed now cid started started_s journal restarted=0 failed=0
	if [ -f "$cd_dir/lock" ]; then
		exec 9<"$cd_dir/lock"
		flock -n 9 || { echo "restart-routers: a deploy pass is running; skipped"; return 0; }
	fi
	# A swap the journal says is unfinished (pipeline.promotion's swap-journal.json, its state not
	# yet "swapped", or a journal that cannot be read) has moved some links but not the live
	# tables: restarting onto those tiles would serve them against the old segments. The repair
	# (unwedge_job or a rollback) comes first; the routers stay on the build they started on.
	journal="$RM_DATA/tiles/swap-journal.json"
	if [ -e "$journal" ] && ! grep -Eq '"state"[[:space:]]*:[[:space:]]*"swapped"' "$journal" 2>/dev/null; then
		echo "restart-routers: $journal says a map swap is unfinished; no router restarted until it is repaired"
		return 0
	fi
	now=$(date +%s)
	for router in $ROUTERS $TRAIL_ROUTERS; do
		variant=${router#valhalla-}
		link="$RM_DATA/tiles/$variant/current"
		[ -L "$link" ] || continue
		# The link's own time (stat does not follow it): a swap replaces the link, so this is when
		# the variant's map last moved.
		changed=$(stat -c %Y "$link") || continue
		cid=$(bc ps -q "$router" 2>/dev/null </dev/null | head -n 1)
		[ -n "$cid" ] || continue
		started=$("${DOCKER:-docker}" inspect -f '{{.State.StartedAt}}' "$cid" 2>/dev/null </dev/null) || continue
		started_s=$(date -u -d "$started" +%s 2>/dev/null) || { echo "restart-routers: $router: cannot read its start time ('$started')" >&2; continue; }
		[ "$started_s" -lt "$changed" ] || continue
		if [ $((now - changed)) -lt "$settle" ]; then
			echo "restart-routers: $router: its map moved $((now - changed))s ago; restarted once it has been still ${settle}s"
			continue
		fi
		echo "restart-routers: $router started before its map moved to $(readlink "$link"); restarting it"
		if bc restart "$router" </dev/null; then
			restarted=$((restarted + 1))
		else
			echo "restart-routers: $router: the restart failed" >&2
			failed=$((failed + 1))
		fi
	done
	[ "$restarted" = 0 ] || echo "restart-routers: restarted $restarted router(s)"
	[ "$failed" = 0 ]
}

cmd_install() {
	local enable=1 unit_dir bin="$cd_dir/bin"
	[ "${1:-}" != --no-enable ] || { enable=0; shift; }
	[ $# = 0 ] || die "install takes only --no-enable"
	[ "$(id -u)" != 0 ] || die "run this as the beta's login user, not root"
	for c in flock date readlink; do command -v "$c" >/dev/null 2>&1 || die "$c is not installed"; done
	mkdir -p "$bin" && chmod 700 "$cd_dir"
	install -m 700 "$self" "$bin/restart-routers.sh"
	unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
	mkdir -p "$unit_dir"
	cat >"$unit_dir/$UNIT.service" <<UNITEOF
# Written by scripts/beta/restart-routers.sh install (docs/BETA-RUNBOOK.md, "The routers after a map swap").
[Unit]
Description=RouteMaker beta: restart a router whose map was swapped under it

[Service]
Type=oneshot
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=RM_VARS=$vars
ExecStart="$bin/restart-routers.sh" check
TimeoutStartSec=15min
UNITEOF
	cat >"$unit_dir/$UNIT.timer" <<UNITEOF
# Written by scripts/beta/restart-routers.sh install (docs/BETA-RUNBOOK.md, "The routers after a map swap").
[Unit]
Description=RouteMaker beta: look for a swapped map every 2 minutes

[Timer]
OnActiveSec=2min
OnUnitInactiveSec=2min

[Install]
WantedBy=timers.target
UNITEOF
	echo "installed $bin/restart-routers.sh; units: $unit_dir/$UNIT.service, $unit_dir/$UNIT.timer"
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
	echo "timer and units removed"
}

main() {
	local command=${1:-}
	case "$command" in '' | -h | --help) usage; return 0 ;; esac
	shift
	load_vars
	case "$command" in
		check) [ $# = 0 ] || die "check takes no arguments"; cmd_check ;;
		install) cmd_install "$@" ;;
		uninstall) cmd_uninstall ;;
		*) die "unknown command '$command' (--help)" ;;
	esac
}

main "$@"; exit $?
