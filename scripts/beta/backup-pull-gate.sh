#!/usr/bin/env bash
# The only thing the PC's backup-pull key may do on the beta (docs/OPERATIONS.md, "Off-box copies
# of beta backups", "A key that can only pull backups").
#
# Installed once from the PC, over the ordinary login, with the new key's .pub on stdin:
#   bash backup-pull-gate.sh --install < rm_backup_pull.pub
# That copies this file to ~/bin/backup-pull-gate and adds the key to ~/.ssh/authorized_keys as
#   restrict,command="<home>/bin/backup-pull-gate" ssh-ed25519 ...
# so every login with that key runs this file whatever command it asked for, with no shell, pty
# or forwarding. sshd puts the asked-for command in SSH_ORIGINAL_COMMAND. It is never run: it is
# compared with the exact commands scripts/pc/pull-beta-backups.sh sends, and this file then does
# that one thing itself. Anything else is refused with exit 126.
#
# It always answers rsync=0, so the pull copies each dump with the plain `sudo -n cat` read.
set -euo pipefail

BACKUPS=/data/routemaker/backups
STATE=routemaker-beta-state
NAME_RE='^routemaker-[0-9]{8}T[0-9]{6}Z\.dump\.age$'

refuse() {
	echo "backup-pull-gate: refused: this key may only pull backups" >&2
	exit 126
}

install_gate() {
	local key home_bin gate auth line
	IFS= read -r key || true
	[[ $key =~ ^ssh-ed25519\ [A-Za-z0-9+/]+=*(\ [A-Za-z0-9._@-]+)?$ ]] ||
		{ echo "backup-pull-gate: --install wants one ssh-ed25519 public key line on stdin" >&2; exit 1; }
	umask 077
	home_bin="$HOME/bin"
	gate="$home_bin/backup-pull-gate"
	auth="$HOME/.ssh/authorized_keys"
	mkdir -p "$home_bin" "$HOME/.ssh"
	cp -- "$0" "$gate.new"
	chmod 755 "$gate.new"
	mv -f -- "$gate.new" "$gate"
	line="restrict,command=\"$gate\" $key"
	local blob=${key#ssh-ed25519 }
	blob=${blob%% *}
	if [ -f "$auth" ] && grep -qF -- "$blob" "$auth"; then
		echo "backup-pull-gate: that key is already in $auth; left as it is" >&2
	else
		printf '%s\n' "$line" >>"$auth"
		echo "backup-pull-gate: installed $gate and added the key to $auth" >&2
	fi
}

if [ "${1:-}" = --install ]; then
	install_gate
	exit 0
fi

cmd=${SSH_ORIGINAL_COMMAND:-}
listing="if command -v rsync >/dev/null 2>&1; then echo rsync=1; else echo rsync=0; fi; sudo -n find '$BACKUPS' -maxdepth 1 -type f -name 'routemaker-*.dump.age' -printf '%f %s\\n'"

if [ "$cmd" = "$listing" ]; then
	echo rsync=0
	exec sudo -n find "$BACKUPS" -maxdepth 1 -type f -name 'routemaker-*.dump.age' -printf '%f %s\n'
fi

# The one name in the command, if there is one; the command must then be exactly a copy or a mark.
name=$(grep -oE 'routemaker-[0-9]{8}T[0-9]{6}Z\.dump\.age' <<<"$cmd" | head -n 1 || true)
[[ $name =~ $NAME_RE ]] || refuse

if [ "$cmd" = "sudo -n cat -- '$BACKUPS/$name'" ]; then
	exec sudo -n cat -- "$BACKUPS/$name"
fi

mark="cd && [ -d '$STATE' ] && umask 077 && printf '%s\\n' '$name' >'$STATE/pc-backup-pull.new' && mv -f '$STATE/pc-backup-pull.new' '$STATE/pc-backup-pull'"
if [ "$cmd" = "$mark" ]; then
	cd
	[ -d "$STATE" ] || exit 1
	umask 077
	printf '%s\n' "$name" >"$STATE/pc-backup-pull.new"
	mv -f "$STATE/pc-backup-pull.new" "$STATE/pc-backup-pull"
	exit 0
fi

refuse
