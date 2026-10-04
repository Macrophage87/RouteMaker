#!/usr/bin/env bash
# The server side of scripts/beta/ship-data.sh: verifies a received bundle, installs it
# under DATA_ROOT, restores the database, and checks the result.
#
#   scripts/beta/receive-data.sh --bundle DIR [--env-file FILE] COMMAND
#
# COMMANDs, run in this order by docs/BETA-RUNBOOK.md:
#   verify   sha256 of every file against SHA256SUMS. Changes nothing.
#   files    verify, then install tiles, elevation, basemap, photon and the front end under
#            DATA_ROOT, switch each graph's `current` link to the new build, and verify the
#            installed files again. Run it with sudo: DATA_ROOT's directories are owned by
#            the container uid after scripts/prepare_data_root.sh.
#   db       restore db/routemaker.dump into the running postgis and compare row counts.
#            Needs postgis up (scripts/beta/beta-compose.sh up -d postgis); runs as the docker user.
#
# Options:
#   --bundle DIR          the directory ship-data.sh sent to (required)
#   --env-file FILE       the server's .env [<repo>/.env]; DATA_ROOT is read out of it by sed
#   --replace-db          allow `db` to replace a database that already holds data. A safety dump of
#                         what is there goes to DATA_ROOT/backups first.
#   --allow-sha-mismatch  the bundle was built from a different git sha than this checkout
#   -h, --help
#
# Every step is idempotent: running `files` twice installs the same bytes twice; a graph's old
# build directory is kept (the previous `current` is recorded as `previous`), so the swap is
# undone by pointing the link back (docs/BETA-RUNBOOK.md, Rollback).
set -euo pipefail

die() { echo "receive-data: $*" >&2; exit 2; }
note() { echo "receive-data: $*" >&2; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)

bundle=""; env_file="$repo/.env"; replace_db=0; allow_sha=0; command_name=""

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
	case "$1" in
		-h | --help) usage; exit 0 ;;
		--bundle) [ $# -ge 2 ] || die "$1 needs a value"; bundle=$2; shift 2 ;;
		--env-file) [ $# -ge 2 ] || die "$1 needs a value"; env_file=$2; shift 2 ;;
		--replace-db) replace_db=1; shift ;;
		--allow-sha-mismatch) allow_sha=1; shift ;;
		-*) die "unknown option $1" ;;
		*) [ -z "$command_name" ] || die "one command at a time"; command_name=$1; shift ;;
	esac
done
case "$command_name" in verify | files | db) ;; *) die "give a command: verify, files or db (--help)" ;; esac
[ -n "$bundle" ] || die "--bundle DIR is required"
[ -d "$bundle" ] || die "$bundle is not a directory"
bundle=$(cd "$bundle" && pwd -P)
[ -r "$bundle/SHA256SUMS" ] && [ -r "$bundle/MANIFEST.txt" ] ||
	die "$bundle has no SHA256SUMS and MANIFEST.txt: the transfer did not finish (rerun ship-data.sh to resume)"

[ -r "$env_file" ] || die "cannot read $env_file"
env_value() { sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$env_file" | tail -n 1 | tr -d '\r' | sed "s/^['\"]//; s/['\"]\$//"; }
manifest_value() { sed -n "s/^$1=//p" "$bundle/MANIFEST.txt" | head -n 1; }

data_root=$(env_value DATA_ROOT)
[ -n "$data_root" ] || die "no DATA_ROOT= in $env_file"
case "$data_root" in /?*) ;; *) die "DATA_ROOT '$data_root' is not absolute" ;; esac
case "$data_root" in
	/ | /etc | /usr | /var | /home | /root | /bin | /boot | /lib | /data | /data/) die "DATA_ROOT '$data_root' is a system directory; use a directory of its own such as /data/routemaker" ;;
esac
[ -d "$data_root" ] || die "$data_root does not exist; run scripts/prepare_data_root.sh first"
case "$bundle/" in "$data_root"/*) die "the bundle ($bundle) is inside DATA_ROOT; keep it beside it, such as /data/routemaker-incoming" ;; esac

has_part() { grep -qw "$1" <<<"$(manifest_value parts)"; }

verify_bundle() { # optional argument: only the files under that prefix (the db step needs only db/)
	local prefix=${1:-}
	if [ -n "$prefix" ]; then
		note "verifying the files under $prefix"
		(cd "$bundle" && grep "  $prefix" SHA256SUMS | sha256sum --check --quiet) || die "checksum mismatch under $prefix; rerun ship-data.sh and verify again"
	else
		note "verifying $(wc -l <"$bundle/SHA256SUMS") files against SHA256SUMS (reads the whole bundle once)"
		(cd "$bundle" && sha256sum --check --quiet SHA256SUMS) || die "checksum mismatch in the bundle; rerun ship-data.sh (rsync resumes) and verify again"
	fi
	local sent_sha here_sha
	sent_sha=$(manifest_value git_sha)
	# safe.directory: under sudo the checkout's owner is not root, and git would refuse to read it.
	here_sha=$(git -c safe.directory="$repo" -C "$repo" rev-parse HEAD 2>/dev/null || echo unknown)
	if [ "$sent_sha" != "$here_sha" ]; then
		if [ "$allow_sha" = 1 ]; then
			note "WARNING: the bundle was built at $sent_sha but this checkout is $here_sha"
		else
			die "the bundle was built at git $sent_sha and this checkout is $here_sha; check out the same sha, or pass --allow-sha-mismatch if only data changed"
		fi
	fi
	note "bundle ok: $(manifest_value files) files, $(manifest_value bytes) bytes, created $(manifest_value created_utc)"
}

# bundle paths mirror DATA_ROOT, except db/
verify_installed() {
	note "verifying the installed files against SHA256SUMS"
	(cd "$data_root" && grep -v '  db/' "$bundle/SHA256SUMS" | sha256sum --check --quiet) ||
		die "an installed file differs from the bundle; rerun 'files'"
}

if [ "$command_name" = verify ]; then
	verify_bundle
	exit 0
fi

# ================================================================================================
if [ "$command_name" = files ]; then
	verify_bundle

	need=$(manifest_value bytes)
	avail=$(df -B1 --output=avail "$data_root" | tail -n 1 | tr -d ' ')
	# a copy plus 10 %: the bundle stays until the owner removes it
	if [ "$avail" -lt $((need + need / 10)) ]; then die "not enough room on $data_root: need about $((need / 1048576)) MiB, have $((avail / 1048576)) MiB"; fi

	rsync_in=(rsync -a --no-owner --no-group --chmod=D755,F644)

	if has_part tiles; then
		for variant_dir in "$bundle"/tiles/*/; do
			variant=$(basename "$variant_dir")
			for build_dir in "$variant_dir"*/; do
				build=$(basename "$build_dir")
				dest="$data_root/tiles/$variant"
				mkdir -p "$dest/$build"
				"${rsync_in[@]}" --delete "$build_dir" "$dest/$build/"
				# scripts/prepare_data_root.sh made `current` an empty DIRECTORY (a bind-mount
				# source); `ln -sfn` into it would put the link inside it. Only an empty one goes.
				if [ -d "$dest/current" ] && [ ! -L "$dest/current" ]; then
					rmdir "$dest/current" 2>/dev/null || die "$dest/current is a non-empty directory, not a link; look before replacing it"
				fi
				if [ -L "$dest/current" ]; then
					old=$(basename "$(readlink "$dest/current")")
					if [ "$old" != "$build" ]; then
						ln -sfn "$old" "$dest/previous.new"
						mv -T "$dest/previous.new" "$dest/previous"
					fi
				fi
				ln -sfn "$build" "$dest/current.new"
				mv -T "$dest/current.new" "$dest/current"
				note "tiles: $variant current -> $build"
			done
		done
	fi

	if has_part elevation; then mkdir -p "$data_root/elevation"; "${rsync_in[@]}" --delete "$bundle/elevation/" "$data_root/elevation/"; note "elevation installed"; fi
	if has_part basemap; then mkdir -p "$data_root/basemap"; "${rsync_in[@]}" --delete "$bundle/basemap/" "$data_root/basemap/"; note "basemap installed"; fi

	if has_part photon; then
		mkdir -p "$data_root/photon"
		"${rsync_in[@]}" --delete "$bundle/photon/" "$data_root/photon/"
		# Photon's image runs as uid 9011 and writes lock files beside its index.
		if [ "$(id -u)" = 0 ]; then chown -R 9011:9011 "$data_root/photon"; else note "not root: left photon/ owned by $(id -un); the image's entrypoint re-owns it on start"; fi
		note "photon index installed"
	fi

	if has_part frontend; then
		# Hashed assets first, index.html last by rename: a page loaded mid-deploy gets the old app
		# or the new one, never an index naming files that are not there yet (docs/DEPLOYMENT.md).
		mkdir -p "$data_root/frontend/assets"
		"${rsync_in[@]}" "$bundle/frontend/assets/" "$data_root/frontend/assets/"
		for f in "$bundle"/frontend/*; do
			[ -f "$f" ] || continue
			[ "$(basename "$f")" = index.html ] && continue
			"${rsync_in[@]}" "$f" "$data_root/frontend/"
		done
		cp "$bundle/frontend/index.html" "$data_root/frontend/.index.html.new"
		chmod 644 "$data_root/frontend/.index.html.new"
		mv -f "$data_root/frontend/.index.html.new" "$data_root/frontend/index.html"
		note "front end installed"
	fi

	verify_installed
	note "files done. Restart the routers if they were already running: scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend"
	exit 0
fi

# ================================================================================================
# db
has_part db || die "this bundle carries no db part"
[ -r "$bundle/db/routemaker.dump" ] && [ -r "$bundle/db/row-counts.tsv" ] || die "the bundle's db/ is incomplete"
verify_bundle db/

pguser=$(env_value PGUSER); pguser=${pguser:-routemaker}
pgdatabase=$(env_value PGDATABASE); pgdatabase=${pgdatabase:-routemaker}
live_schema=$(manifest_value live_schema); live_schema=${live_schema:-live}
case "$pguser$pgdatabase$live_schema" in *[!A-Za-z0-9_]*) die "odd database, user or schema name" ;; esac

bc() { "$here/beta-compose.sh" "$@"; }
psql_q() { bc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -At -c "$1"; }

running=$(bc ps --status running --services 2>/dev/null || true)
grep -qx postgis <<<"$running" || die "postgis is not running: scripts/beta/beta-compose.sh up -d postgis, and wait for it to be healthy"
for _ in $(seq 1 30); do
	[ "$(bc ps postgis --format '{{.Health}}' 2>/dev/null)" = healthy ] && break
	sleep 2
done
[ "$(bc ps postgis --format '{{.Health}}' 2>/dev/null)" = healthy ] || die "postgis is not healthy yet"

# Is there already something here worth keeping?
existing=$(psql_q "select to_regclass('public.django_migrations') is not null")
clean_args=()
if [ "$existing" = t ]; then
	rows=$(psql_q "select (select count(*) from public.app_user) + coalesce((select count(*) from public.override), 0)")
	live_tables=$(psql_q "select count(*) from pg_tables where schemaname = '$live_schema'")
	if [ "${rows:-0}" != 0 ] || [ "${live_tables:-0}" != 0 ]; then
		[ "$replace_db" = 1 ] || die "the database already holds data ($rows user/override rows, $live_tables tables in $live_schema); pass --replace-db to replace it (a safety dump is taken first)"
		stamp=$(date -u +%Y%m%dT%H%M%SZ)
		safety="$data_root/backups/pre-restore-$stamp.dump"
		mkdir -p "$data_root/backups"
		note "safety dump of the current database to $safety"
		bc exec -T postgis pg_dump -U "$pguser" -d "$pgdatabase" --format=custom --no-owner -n public -n "$live_schema" >"$safety"
		[ -s "$safety" ] || die "the safety dump is empty; stopping before anything is replaced"
	fi
	# Tables exist (migrate has run) or are being replaced: drop what the dump recreates.
	clean_args=(--clean --if-exists)
fi

note "restoring (this takes a few minutes; postgis is capped at 1 GiB, so the index builds are slow, not failed)"
# The dump names schema `public`, which every database already has, so a plain pg_restore ends with
# `schema "public" already exists` and exit 1 (tested against the shipped dump). Restoring from a
# table of contents with that one line removed is clean. Not --single-transaction: a failed statement
# should be seen, and rerunning is safe (--clean).
bc exec -T postgis sh -c 'pg_restore --list > /tmp/beta.toc && grep -v " SCHEMA - public " /tmp/beta.toc > /tmp/beta.use' <"$bundle/db/routemaker.dump"
bc exec -T postgis pg_restore -U "$pguser" -d "$pgdatabase" --no-owner --no-privileges "${clean_args[@]}" -L /tmp/beta.use <"$bundle/db/routemaker.dump" ||
	die "pg_restore reported errors (above); read them before using the database"
bc exec -T postgis rm -f /tmp/beta.toc /tmp/beta.use
psql_q "analyze" >/dev/null

note "comparing row counts with the bundle's"
fail=0
while IFS=$'\t' read -r qualified expected; do
	[ -n "$qualified" ] || continue
	actual=$(psql_q "select count(*) from \"${qualified%%.*}\".\"${qualified#*.}\"")
	if [ "$actual" = "$expected" ]; then
		continue
	fi
	case "$qualified" in
		"$live_schema".*) note "MISMATCH $qualified: shipped $expected, restored $actual"; fail=1 ;;
		*) note "note: $qualified had $expected rows when counted at home and has $actual here (the home site was in use; informational)" ;;
	esac
done <"$bundle/db/row-counts.tsv"
[ "$fail" = 0 ] || die "the $live_schema schema does not match the bundle; do not start the api. Restore again with --replace-db"
note "db done. Next: scripts/beta/beta-compose.sh run --rm --no-deps api ./manage.py migrate --check"
