#!/usr/bin/env bash
# Copy the beta's nightly encrypted database dumps to this PC (docs/OPERATIONS.md, "Off-box
# copies of beta backups"). Runs in WSL on the owner's PC, nightly from Windows Task Scheduler
# (scripts/pc/install-backup-pull-task.ps1), or by hand. Asks nothing: everything is set below
# or by the environment.
#
# What it copies: <DATA_ROOT>/backups/routemaker-<UTC>.dump.age on the beta, the dumps the worker
# writes at 07:00 UTC (config.procrastinate perform_backup; DATA_ROOT is /data/routemaker,
# docs/BETA-RUNBOOK.md). Only `.dump.age` files, which are encrypted to the owner's key and
# useless without it: never the plain pre-*.dump files beside them, never a `.part`.
#
# On the beta it runs only a listing (find) and a copy (rsync --sender, or cat). The backups
# folder is 0700 and owned by the containers' uid 10001 (scripts/prepare_data_root.sh), so both
# run under `sudo -n` there (RM_BETA_SUDO): a sudo that would ask for a password fails instead.
#
# Here it writes each file as <name>.part, checks its size against the beta's, then renames it;
# keeps the newest RM_BACKUP_KEEP that are under RM_BACKUP_MAX_AGE_H old (by the UTC time in the
# name; the newest copy is always kept) and deletes the other routemaker-*.dump.age, only in
# RM_BACKUP_DIR. That retention runs on every run, a failed one too, as the beta's does
# (config.procrastinate BACKUP_MAX_AGE), so a run of failures never keeps old copies past the week.
# It appends one line per run to RM_BACKUP_DIR/pull-beta-backups.log. Exit 0 ok, 1 failed.
#
# After a run that ends ok it writes the newest dump's name to RM_BETA_STATE/pc-backup-pull on
# the beta (the login user's own state folder; written only if that folder exists). The beta's
# alert.sh watch posts in the owner's channel when that file is over 36 h old, so a pull that fails
# or stops running (the PC off, the task gone, the key not loading) is reported there.
#
# Environment (defaults in brackets):
#   RM_BETA_SSH         ssh host alias of the beta [chubby]
#   RM_BACKUP_DIR       local folder [/mnt/c/Users/steph/Documents/RouteMaker/beta-backups]
#   RM_BETA_BACKUPS     the backups folder on the beta [/data/routemaker/backups]
#   RM_BETA_SUDO        prefix for the two commands on the beta ["sudo -n"]; empty if the
#                       login user can read that folder itself
#   RM_BACKUP_KEEP      copies kept here [7, as on the beta: the privacy page promises deleted data leaves backups within a week]
#   RM_BACKUP_MAX_AGE_H hours a copy is kept, the newest excepted [156, the beta's 6.5 days]
#   RM_BETA_STATE       the beta's state folder, from the login user's home [routemaker-beta-state]
set -euo pipefail
export LC_ALL=C

host=${RM_BETA_SSH:-chubby}
dest=${RM_BACKUP_DIR:-/mnt/c/Users/steph/Documents/RouteMaker/beta-backups}
remote_dir=${RM_BETA_BACKUPS:-/data/routemaker/backups}
sudo_cmd=${RM_BETA_SUDO-sudo -n}
keep=${RM_BACKUP_KEEP:-7}
max_age_h=${RM_BACKUP_MAX_AGE_H:-156}
remote_state=${RM_BETA_STATE:-routemaker-beta-state}
log="$dest/pull-beta-backups.log"
name_re='^routemaker-[0-9]{8}T[0-9]{6}Z\.dump\.age$'
# BatchMode: a key that needs a passphrase (no agent in a scheduled run) fails at once, not waits.
ssh_opts=(-o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=30)

say() { echo "pull-beta-backups: $*" >&2; }
log_line() { [ -d "$dest" ] && printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$log" || true; }
# Set once the settings are checked: from then on a failure still applies the retention.
can_prune=0
removed=0
fail() {
	local note=""
	say "FAILED: $*"
	if [ "$can_prune" = 1 ]; then
		prune_local || true
		note=" (removed $removed by age or count)"
	fi
	log_line "FAILED $*$note"
	exit 1
}

# Seconds since the epoch of the UTC time in a dump's name, or nothing.
taken_at() { # name
	local stamp=${1#routemaker-}
	stamp=${stamp%.dump.age}
	date -u -d "${stamp:0:8} ${stamp:9:2}:${stamp:11:2}:${stamp:13:2}" +%s 2>/dev/null
}
# Retention, only of our own file names, only in this folder: the newest is always kept; of the
# rest, those past the keep-th newest or over max_age_h old go.
prune_local() {
	local old n=0 t now
	now=$(date -u +%s)
	while IFS= read -r old; do
		n=$((n + 1))
		[ "$n" -gt 1 ] || continue
		t=$(taken_at "$old") || t=""
		if [ "$n" -gt "$keep" ] || { [ -n "$t" ] && [ $((now - t)) -gt $((max_age_h * 3600)) ]; }; then
			rm -f -- "$dest/$old" && removed=$((removed + 1))
		fi
	done < <(find "$dest" -maxdepth 1 -type f -name 'routemaker-*.dump.age' -printf '%f\n' | grep -E "$name_re" | sort -r)
}

[[ $keep =~ ^[1-9][0-9]*$ ]] || fail "RM_BACKUP_KEEP must be a whole number of 1 or more"
[[ $max_age_h =~ ^[1-9][0-9]*$ ]] || fail "RM_BACKUP_MAX_AGE_H must be a whole number of 1 or more"
case "$remote_dir" in /*) ;; *) fail "RM_BETA_BACKUPS must be an absolute path" ;; esac
case "$remote_dir$sudo_cmd$remote_state" in *"'"*) fail "RM_BETA_BACKUPS, RM_BETA_SUDO and RM_BETA_STATE may not contain a quote" ;; esac
mkdir -p "$dest" || { say "FAILED: cannot create $dest"; exit 1; }
can_prune=1

# A .part left by a run that was killed (ours, or rsync's own temporary file) is never a backup.
current_part=""
cleanup() { [ -z "$current_part" ] || rm -f -- "$current_part"; }
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
find "$dest" -maxdepth 1 -type f \( -name 'routemaker-*.dump.age.part' -o -name '.routemaker-*.dump.age*' \) -delete

# One read-only call: is rsync there, and which dumps (name and size) are there.
remote_cmd="if command -v rsync >/dev/null 2>&1; then echo rsync=1; else echo rsync=0; fi; \
$sudo_cmd find '$remote_dir' -maxdepth 1 -type f -name 'routemaker-*.dump.age' -printf '%f %s\n'"
set +e
# shellcheck disable=SC2029 # expanded here on purpose: the paths are checked above
listing=$(ssh "${ssh_opts[@]}" "$host" "$remote_cmd" </dev/null)
status=$?
set -e
if [ "$status" = 255 ]; then
	fail "ssh $host did not connect (exit 255). Is the beta ($host) reachable, and does the ssh key load without a prompt? A key with a passphrase needs an agent; see docs/OPERATIONS.md, \"Off-box copies of beta backups\"."
elif [ "$status" != 0 ]; then
	fail "listing $remote_dir on $host failed (exit $status). If sudo wants a password there, see docs/OPERATIONS.md, \"Off-box copies of beta backups\"."
fi

use_rsync=0
if command -v rsync >/dev/null 2>&1 && grep -qx 'rsync=1' <<<"$listing"; then use_rsync=1; fi

# The keep-th newest copy here: anything older on the beta would be deleted again at once.
# Names carry a fixed-width UTC time, so name order is time order.
mapfile -t have < <(find "$dest" -maxdepth 1 -type f -name 'routemaker-*.dump.age' -printf '%f\n' | sort -r)
cutoff=""
[ "${#have[@]}" -lt "$keep" ] || cutoff=${have[$((keep - 1))]}

copied=0; errors=0; seen=0
while read -r name size; do
	[ -n "$name" ] || continue
	case "$name" in rsync=*) continue ;; esac
	[[ $name =~ $name_re ]] && [[ $size =~ ^[0-9]+$ ]] || { say "skipping an odd listing line: $name"; continue; }
	seen=$((seen + 1))
	[ ! -e "$dest/$name" ] || continue
	if [ -n "$cutoff" ] && [[ $name < $cutoff ]]; then continue; fi
	current_part="$dest/$name.part"
	rm -f -- "$current_part"
	if [ "$use_rsync" = 1 ]; then
		rsync -t -e "ssh ${ssh_opts[*]}" --rsync-path="${sudo_cmd:+$sudo_cmd }rsync" \
			"$host:$remote_dir/$name" "$current_part" </dev/null || { say "rsync of $name failed"; }
	elif [ -z "$sudo_cmd" ]; then
		scp -q -p "${ssh_opts[@]}" "$host:$remote_dir/$name" "$current_part" </dev/null || { say "scp of $name failed"; }
	else
		# scp cannot use sudo; this is the same copy as a plain read through ssh.
		# shellcheck disable=SC2029
		ssh "${ssh_opts[@]}" "$host" "$sudo_cmd cat -- '$remote_dir/$name'" </dev/null >"$current_part" || { say "copy of $name failed"; }
	fi
	got=$(stat -c %s -- "$current_part" 2>/dev/null || echo missing)
	if [ "$got" = "$size" ]; then
		mv -f -- "$current_part" "$dest/$name"
		copied=$((copied + 1))
	else
		say "$name: got $got bytes, the beta has $size; not kept"
		rm -f -- "$current_part"
		errors=$((errors + 1))
	fi
	current_part=""
done <<<"$listing"

[ "$errors" = 0 ] || fail "$errors of the new dumps did not copy whole (copied $copied)"
[ "$seen" -gt 0 ] || fail "no routemaker-*.dump.age in $remote_dir on $host"

prune_local

newest=$(find "$dest" -maxdepth 1 -type f -name 'routemaker-*.dump.age' -printf '%f\n' | grep -E "$name_re" | sort -r | head -n 1 || true)
kept=$(find "$dest" -maxdepth 1 -type f -name 'routemaker-*.dump.age' -printf '%f\n' | grep -cE "$name_re" || true)
# The beta keeps its newest dump whatever its age, so a beta whose backups stopped still copies
# "ok"; this is the line that says so. 48 h: one missed night is not yet an alarm.
taken=$(taken_at "$newest") || taken=0
age_h=$((($(date -u +%s) - taken) / 3600))
[ "$age_h" -le 48 ] || fail "the newest dump ($newest) is ${age_h} h old: the beta's nightly backup has stopped (copied $copied, kept $kept)"

# The beta's alert.sh watch reads this file's age (see the header). Not written, the run is still
# ok here, and the beta reports the pull as stale once the file is over 36 h old.
mark_cmd="cd && [ -d '$remote_state' ] && umask 077 && printf '%s\\n' '$newest' >'$remote_state/pc-backup-pull.new' && mv -f '$remote_state/pc-backup-pull.new' '$remote_state/pc-backup-pull'"
marked=yes
# shellcheck disable=SC2029 # expanded here on purpose: the names are checked above
ssh "${ssh_opts[@]}" "$host" "$mark_cmd" </dev/null >/dev/null 2>&1 || {
	marked=no
	say "note: could not record this run in $remote_state/pc-backup-pull on $host; the beta will report the pull as stale"
}
log_line "ok host=$host copied=$copied removed=$removed kept=$kept newest=$newest via=$([ "$use_rsync" = 1 ] && echo rsync || echo copy) marked=$marked"
say "ok: copied $copied, removed $removed, keeping $kept; newest $newest"
