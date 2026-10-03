#!/usr/bin/env bash
# Install, inspect or remove the routemaker-boot systemd USER unit. No sudo.
#
#   install-boot-unit.sh install [--now]   render + verify + enable the unit
#                                          (--now also starts it immediately,
#                                          which runs start-stack.sh: WARM on a
#                                          healthy stack, but only do it on purpose)
#   install-boot-unit.sh status            unit, linger, last result, log tail
#   install-boot-unit.sh uninstall         disable and remove the unit
#   install-boot-unit.sh policy no|unless-stopped
#                                          `docker update --restart=...` on the
#                                          project's containers (the project is
#                                          COMPOSE_PROJECT_NAME from .env): changes
#                                          the policy in place, no restart. The
#                                          one-shot migrate container is skipped:
#                                          compose gives it `no` either way. Do this
#                                          once so the NEXT reboot does not race.
#   install-boot-unit.sh --help
#
# Lingering (the one sudo step, run by the owner):  sudo loginctl enable-linger steph

set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=${ROUTEMAKER_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}
UNIT=routemaker-boot.service
UNIT_DIR=${BOOT_UNIT_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}
LOG_DIR=${BOOT_LOG_DIR:-/home/steph/rmdata/boot}
USER_NAME=${USER:-$(id -un)}
DOCKER=${BOOT_DOCKER:-docker}
ENV_FILE=${BOOT_ENV_FILE:-$REPO_DIR/.env}

usage() { sed -n '2,/^set -E/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; }

render() { # render TEMPLATE REPO > stdout
  local repo=$2
  # Paths with these characters would need escaping in a unit file as well.
  case "$repo" in *[[:space:]\&\|\\]*) echo "repo path has unsafe characters: $repo" >&2; return 1 ;; esac
  sed "s|@REPO@|$repo|g" "$1"
}

linger_state() { loginctl show-user "$USER_NAME" -p Linger 2>/dev/null | cut -d= -f2; }

cmd_install() {
  local now=0
  [ "${1:-}" = "--now" ] && now=1
  command -v systemctl >/dev/null || { echo "systemctl not found" >&2; exit 1; }
  systemctl --user is-system-running >/dev/null 2>&1 || systemctl --user show-environment >/dev/null ||
    { echo "systemd user manager is not running (WSL needs systemd=true in /etc/wsl.conf)" >&2; exit 1; }
  [ -x "$REPO_DIR/scripts/boot/start-stack.sh" ] || { echo "$REPO_DIR/scripts/boot/start-stack.sh is not executable" >&2; exit 1; }
  mkdir -p "$UNIT_DIR" "$LOG_DIR"
  # Verify under the real unit name (systemd derives the type from the suffix)
  # in a scratch directory, and only then put it in place.
  local scratch
  scratch=$(mktemp -d)
  render "$SCRIPT_DIR/$UNIT.in" "$REPO_DIR" >"$scratch/$UNIT"
  systemd-analyze --user verify "$scratch/$UNIT" || { rm -rf "$scratch"; echo "unit failed verification" >&2; exit 1; }
  mv "$scratch/$UNIT" "$UNIT_DIR/$UNIT"
  rm -rf "$scratch"
  systemctl --user daemon-reload
  systemctl --user enable "$UNIT"
  echo "installed $UNIT_DIR/$UNIT (repo: $REPO_DIR)"
  if [ "$(linger_state)" != yes ]; then
    echo "WARNING: linger is off for $USER_NAME, so the unit will NOT run at boot until you run:"
    echo "    sudo loginctl enable-linger $USER_NAME"
  fi
  if [ "$now" = 1 ]; then
    systemctl --user start "$UNIT"
  else
    echo "not started now. To run it now: systemctl --user start $UNIT"
  fi
}

cmd_status() {
  echo "unit file : $UNIT_DIR/$UNIT $([ -f "$UNIT_DIR/$UNIT" ] && echo present || echo MISSING)"
  echo "enabled   : $(systemctl --user is-enabled "$UNIT" 2>&1 || true)"
  echo "active    : $(systemctl --user is-active "$UNIT" 2>&1 || true)"
  echo "linger    : $(linger_state || true)   (must be yes for boot-time start)"
  echo "last run  : $(cat "$LOG_DIR/last-status" 2>/dev/null || echo 'no last-status file')"
  echo "--- journal (last 15) ---"
  journalctl --user -u "$UNIT" -n 15 --no-pager 2>&1 || true
  echo "--- $LOG_DIR/latest.log (last 15) ---"
  tail -n 15 "$LOG_DIR/latest.log" 2>&1 || true
}

cmd_uninstall() {
  systemctl --user disable "$UNIT" 2>&1 || true
  rm -f "$UNIT_DIR/$UNIT"
  systemctl --user daemon-reload
  echo "removed $UNIT. Containers were not touched."
  echo "To return Docker to auto-starting the stack at boot (the racy default):"
  echo "    sed -i '/^RESTART_POLICY=no\$/d' .env && $0 policy unless-stopped"
  echo "Lingering is separate: sudo loginctl disable-linger $USER_NAME (only if nothing else needs it)."
}

cmd_policy() {
  local p=${1:-}
  case "$p" in no | unless-stopped) ;; *) echo "usage: $0 policy no|unless-stopped" >&2; exit 64 ;; esac
  local project lines ids
  project=$(project_name) || exit 1
  # Only this project's containers (never e.g. crrev-pg34), and not migrate.
  lines=$("$DOCKER" ps -a --filter "label=com.docker.compose.project=$project" \
    --format '{{.ID}} {{.Label "com.docker.compose.service"}}' </dev/null)
  ids=$(awk '$1 != "" && $2 != "migrate" { print $1 }' <<<"$lines")
  [ -n "$ids" ] || { echo "no $project containers found"; return 0; }
  # shellcheck disable=SC2086
  "$DOCKER" update --restart="$p" $ids </dev/null
  echo "restart policy set to '$p' on $(echo $ids | wc -w) $project containers, migrate left at 'no' (no restart needed)"
}

# env_get NAME: one value from .env without sourcing it (same rules as start-stack.sh).
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
project_name() {
  local p
  p=$(env_get COMPOSE_PROJECT_NAME)
  [ -n "$p" ] || { echo "COMPOSE_PROJECT_NAME is not set in $ENV_FILE; refusing to guess the project" >&2; return 1; }
  if [ -n "${COMPOSE_PROJECT:-}" ] && [ "$COMPOSE_PROJECT" != "$p" ]; then
    echo "COMPOSE_PROJECT=$COMPOSE_PROJECT but $ENV_FILE says COMPOSE_PROJECT_NAME=$p; refusing" >&2
    return 1
  fi
  printf '%s' "$p"
}

case "${1:-}" in
  install) shift; cmd_install "$@" ;;
  status) cmd_status ;;
  uninstall) cmd_uninstall ;;
  policy) shift; cmd_policy "$@" ;;
  -h | --help | "") usage ;;
  *) usage >&2; exit 64 ;;
esac
