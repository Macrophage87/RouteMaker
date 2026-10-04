#!/bin/sh
# Writes the beta server's .env from deploy/beta/env.beta.template.
#
#   make-env.sh [--out FILE] [--data-root PATH] [--api-port N] [--tag TAG]
#
# Defaults: --out <repo>/.env, --data-root /data/routemaker, --api-port 8087,
# --tag the first 12 characters of the checkout's HEAD.
#
# Every @GENERATE@ becomes a fresh `openssl rand -hex 32`. The file is created mode 600
# before anything is written to it. The script REFUSES to overwrite: a regenerated
# PGPASSWORD no longer matches the one the database was initialised with. It prints
# no secret, only the names it filled.
set -eu

die() { echo "make-env: $*" >&2; exit 2; }

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
template="$repo/deploy/beta/env.beta.template"
[ -r "$template" ] || die "cannot read $template"

out="$repo/.env"; data_root=/data/routemaker; api_port=8087; tag=""
while [ $# -gt 0 ]; do
	[ $# -ge 2 ] || die "$1 needs a value"
	case "$1" in
		--out) out=$2 ;;
		--data-root) data_root=$2 ;;
		--api-port) api_port=$2 ;;
		--tag) tag=$2 ;;
		*) die "unknown option $1" ;;
	esac
	shift 2
done

[ -n "$tag" ] || tag=$(git -C "$repo" rev-parse --short=12 HEAD 2>/dev/null) || die "no --tag and not a git checkout"
case "$tag" in *[!A-Za-z0-9._-]* | '') die "bad tag '$tag'" ;; esac
case "$api_port" in *[!0-9]* | '') die "--api-port must be a number" ;; esac
case "$data_root" in /?*) ;; *) die "--data-root must be an absolute path" ;; esac
case "$data_root" in *[!A-Za-z0-9._/-]*) die "--data-root has a character .env should not carry" ;; esac
command -v openssl >/dev/null 2>&1 || die "openssl is required"

[ ! -e "$out" ] || die "$out already exists; not overwriting (a new PGPASSWORD would not match the database). Move it aside if you mean it."

umask 077
: >"$out"
chmod 600 "$out"

filled=""
while IFS= read -r line || [ -n "$line" ]; do
	case "$line" in
		[A-Z_]*=@GENERATE@)
			key=${line%%=*}
			value=$(openssl rand -hex 32)
			printf '%s=%s\n' "$key" "$value" >>"$out"
			filled="$filled $key"
			;;
		*)
			printf '%s\n' "$line" |
				sed -e "s|@TAG@|$tag|" -e "s|@DATA_ROOT@|$data_root|" -e "s|@API_PORT@|$api_port|" >>"$out"
			;;
	esac
done <"$template"

if grep -n '@[A-Z_]*@' "$out" >/dev/null; then
	rm -f "$out"
	die "unfilled placeholders remained; removed $out"
fi

echo "make-env: wrote $out (mode 600). Generated:$filled"
echo "make-env: still empty on purpose, fill in if wanted: DISCORD_CLIENT_ID DISCORD_CLIENT_SECRET BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID"
