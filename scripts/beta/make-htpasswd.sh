#!/bin/sh
# Creates the beta's HTTP basic-auth file, with a random password per user.
#
#   make-htpasswd.sh [--file PATH] [--group GROUP] USER [USER ...]
#
# Default file /etc/nginx/routemaker-beta.htpasswd. The passwords are generated here,
# shown ONCE on standard output for the owner to hand to each person, and never written
# anywhere but as an apr1 hash in the file. Nothing is stored in the repository.
#
# Refuses to overwrite an existing file (so rerunning cannot lock the testers out);
# to add or change a user later use `htpasswd`, or remove the file and run this again.
# To choose a password yourself, skip this script:
#   printf '%s:%s\n' alice "$(openssl passwd -apr1)" | sudo tee -a FILE   (it prompts)
#
# The file must be readable by the nginx worker user (www-data on Ubuntu), because
# auth_basic_user_file is read per request by the workers, not by the master. This script
# sets root:GROUP mode 640, GROUP defaulting to the `user` nginx.conf names, else www-data.
# It needs root to write under /etc/nginx; run it with sudo.
set -eu

die() { echo "make-htpasswd: $*" >&2; exit 2; }

file=/etc/nginx/routemaker-beta.htpasswd
group=""
while [ $# -gt 0 ]; do
	case "$1" in
		--file) [ $# -ge 2 ] || die "--file needs a value"; file=$2; shift 2 ;;
		--group) [ $# -ge 2 ] || die "--group needs a value"; group=$2; shift 2 ;;
		--*) die "unknown option $1" ;;
		*) break ;;
	esac
done
[ $# -ge 1 ] || die "give at least one user name"
command -v openssl >/dev/null 2>&1 || die "openssl is required"
[ ! -e "$file" ] || die "$file exists; not overwriting"

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

umask 037
: >"$file"
chown "root:$group" "$file"
chmod 640 "$file"

echo "Passwords (shown once; not stored anywhere):"
for user in "$@"; do
	password=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
	hash=$(printf '%s' "$password" | openssl passwd -apr1 -stdin)
	printf '%s:%s\n' "$user" "$hash" >>"$file"
	printf '  %s  %s\n' "$user" "$password"
done
echo "make-htpasswd: wrote $file (root:$group, 640)"
