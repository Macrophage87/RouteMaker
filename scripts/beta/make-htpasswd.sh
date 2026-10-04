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
		'' | *[!A-Za-z0-9._-]*) die "user names are letters, digits, dot, dash, underscore: '$user'" ;;
	esac
done

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
chown "root:$group" "$file"
chmod 640 "$file"

for user in "$@"; do
	password=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
	hash=$(printf '%s' "$password" | openssl passwd -6 -stdin)
	case "$hash" in '$6$'*) ;; *) die "openssl passwd -6 did not give a SHA-512 crypt hash" ;; esac
	printf '%s:%s\n' "$user" "$hash" >>"$file"
	printf '%s %s\n' "$user" "$password" >>"$passwords"
done
echo "make-htpasswd: wrote $file (root:$group, 640) with $# user(s)"
echo "make-htpasswd: the passwords are in $passwords (mode 600${owner:+, owner $owner}); they are not shown here"
