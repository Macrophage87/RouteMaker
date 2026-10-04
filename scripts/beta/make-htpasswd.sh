#!/bin/sh
# Creates the beta's HTTP basic-auth file, with a random password per user.
#
#   make-htpasswd.sh [--file PATH] [--group GROUP] [--passwords-file PATH] USER [USER ...]
#
# Default file /etc/nginx/routemaker-beta.htpasswd. The passwords are generated here and
# written ONCE, in plain text, to a private file (mode 600, owned by the person who ran sudo)
# for the owner to read and hand to each person; this script prints only that file's PATH,
# never a password, so none lands in a terminal transcript or a log. The htpasswd file holds
# only hashes. Nothing is stored in the repository.
#
# The passwords are written to be read out, typed and pasted (final review, accessibility S3):
# four dash-separated groups of five characters from 31 lowercase letters and digits with
# no look-alikes (no i, l, o, 0 or 1), about 99 bits, such as `abcde-fghjk-mnpqr-stuvw` (not a
# real one). Screen readers say lowercase letters plainly, and nothing in it can be misread.
# User names must be lowercase too: nginx compares them case-sensitively, and a tester who
# types "Alice" for "alice" just gets the sign-in box again with no reason given.
# docs/BETA-TESTER-HANDOUT.md is what goes to each tester with theirs.
#
# The hash is SHA-512 crypt (`openssl passwd -6`, `$6$...`), stronger than apr1. nginx checks
# any hash it does not know itself (apr1, {SHA}, {SSHA}, {PLAIN}) with the system's crypt(),
# and glibc/libxcrypt on Ubuntu verifies `$6$` (checked on Ubuntu's libxcrypt, 2026-10-04).
#
# Default passwords file: ~/routemaker-beta-passwords.txt of the user who ran sudo ($SUDO_USER),
# else of the caller. The owner reads it in his own terminal, hands the passwords out, and
# deletes it (shred -u). Refuses to overwrite either file (so rerunning cannot lock the
# testers out); to add or change a user later use `htpasswd -B` or `openssl passwd -6`, or
# remove both files and run this again. To choose a password yourself, skip this script:
#   printf '%s:%s\n' alice "$(openssl passwd -6)" | sudo tee -a FILE   (it prompts)
#
# The htpasswd file must be readable by the nginx worker user (www-data on Ubuntu), because
# auth_basic_user_file is read per request by the workers, not by the master. This script
# sets root:GROUP mode 640, GROUP defaulting to the `user` nginx.conf names, else www-data.
# It needs root to write under /etc/nginx; run it with sudo.
set -eu

die() { echo "make-htpasswd: $*" >&2; exit 2; }

file=/etc/nginx/routemaker-beta.htpasswd
group=""
passwords=""
while [ $# -gt 0 ]; do
	case "$1" in
		--file) [ $# -ge 2 ] || die "--file needs a value"; file=$2; shift 2 ;;
		--group) [ $# -ge 2 ] || die "--group needs a value"; group=$2; shift 2 ;;
		--passwords-file) [ $# -ge 2 ] || die "--passwords-file needs a value"; passwords=$2; shift 2 ;;
		--*) die "unknown option $1" ;;
		*) break ;;
	esac
done
[ $# -ge 1 ] || die "give at least one user name"
command -v openssl >/dev/null 2>&1 || die "openssl is required"
[ ! -e "$file" ] || die "$file exists; not overwriting"

owner=""
if [ -z "$passwords" ]; then
	if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
		owner=$SUDO_USER
		home=$(getent passwd "$SUDO_USER" | cut -d: -f6)
	else
		home=${HOME:-}
	fi
	[ -n "$home" ] && [ -d "$home" ] || die "no home directory for the passwords file; pass --passwords-file"
	passwords="$home/routemaker-beta-passwords.txt"
elif [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
	owner=$SUDO_USER
fi
[ ! -e "$passwords" ] || die "$passwords exists; not overwriting (hand those out, delete it, then rerun)"

for user in "$@"; do
	case "$user" in
		'' | *[!a-z0-9._-]*) die "user names are lowercase letters, digits, dot, dash or underscore (nginx compares them case-sensitively): '$user'" ;;
	esac
done

# 31 symbols: a-z without i, l and o, and 2-9. tr -dc keeps only those bytes of uniformly random
# input, so each kept character is uniform over the 31 (no modulo bias); 1024 bytes keep about
# 124, far more than the 20 needed.
ALPHABET=abcdefghjkmnpqrstuvwxyz23456789
new_password() {
	raw=$(openssl rand 1024 | LC_ALL=C tr -dc "$ALPHABET" | cut -c1-20)
	[ "${#raw}" -eq 20 ] || die "could not draw a password from openssl rand"
	printf '%s-%s-%s-%s' "$(printf %s "$raw" | cut -c1-5)" "$(printf %s "$raw" | cut -c6-10)" \
		"$(printf %s "$raw" | cut -c11-15)" "$(printf %s "$raw" | cut -c16-20)"
}

if [ -z "$group" ]; then
	group=$(sed -n 's/^[[:space:]]*user[[:space:]]\{1,\}\([A-Za-z0-9_-]\{1,\}\).*/\1/p' /etc/nginx/nginx.conf 2>/dev/null | head -n 1)
	[ -n "$group" ] || group=www-data
fi
getent group "$group" >/dev/null 2>&1 || die "group '$group' does not exist; pass --group"

# The private file first, mode 600 before anything is in it.
umask 077
: >"$passwords"
chmod 600 "$passwords"
[ -z "$owner" ] || chown "$owner" "$passwords"
printf '# RouteMaker beta testers: user password. Hand each person theirs, then delete this file.\n' >>"$passwords"

: >"$file"
# root:GROUP when run as root (the normal case, under sudo); otherwise only the group can be set,
# which is what lets the tests run this without root.
if [ "$(id -u)" = 0 ]; then chown "root:$group" "$file"; else chgrp "$group" "$file"; fi
chmod 640 "$file"

for user in "$@"; do
	password=$(new_password)
	hash=$(printf '%s' "$password" | openssl passwd -6 -stdin)
	case "$hash" in '$6$'*) ;; *) die "openssl passwd -6 did not give a SHA-512 crypt hash" ;; esac
	printf '%s:%s\n' "$user" "$hash" >>"$file"
	printf '%s %s\n' "$user" "$password" >>"$passwords"
done
echo "make-htpasswd: wrote $file (root:$group, 640) with $# user(s)"
echo "make-htpasswd: the passwords are in $passwords (mode 600${owner:+, owner $owner}); they are not shown here"
