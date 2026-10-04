#!/usr/bin/env bash
# The server side of scripts/beta/ship-data.sh: verifies a received bundle, installs it
# under DATA_ROOT, restores the database, and checks the result.
#
#   scripts/beta/receive-data.sh --bundle DIR [--env-file FILE] COMMAND
#   scripts/beta/receive-data.sh [--env-file FILE] snapshot-db --label NAME
#   scripts/beta/receive-data.sh [--env-file FILE] restore-dump FILE
#
# COMMANDs, run in this order by docs/BETA-RUNBOOK.md:
#   verify   sha256 of every file against SHA256SUMS. Changes nothing.
#   files    verify, then install tiles, elevation, basemap, photon and the front end under
#            DATA_ROOT, switch each graph's `current` link to the new build, and verify the
#            installed files again. Only files SHA256SUMS lists are installed, and only the
#            tile builds MANIFEST.txt's tiles= line names: anything an earlier bundle left in
#            the bundle directory is skipped (and reported). If the bundle carries the Photon
#            index and photon is running, photon is stopped while its index is replaced and
#            started again afterwards. Run it with sudo: DATA_ROOT's directories are owned by
#            the container uid after scripts/prepare_data_root.sh.
#   db       restore db/routemaker.dump into the running postgis and compare row counts.
#            Needs postgis up (scripts/beta/beta-compose.sh up -d postgis). Run it with sudo
#            when a safety dump is taken (DATA_ROOT/backups is owned by the container uid).
#              First restore: into the empty database, before the api has ever started.
#              --update-data: for a NEW DATA bundle once the beta is running. Restores only the
#                `live` schema and the data of `override` and `stress_tile_cache`, in one
#                transaction, after a safety dump. Accounts, sessions and everything else the
#                beta has made of its own are not touched.
#              --replace-db: replace the whole database with the bundle's. The bundle carries
#                no accounts (OWNER-DECISIONS 367.3), so this deletes the beta's own; it is
#                refused while any exist unless --delete-beta-accounts is given too.
#   snapshot-db --label NAME
#            pg_dump the database to DATA_ROOT/backups/pre-NAME-<utc>.dump and print its path.
#            The runbook takes one before every release update (which may migrate forward).
#   restore-dump FILE
#            put back a dump made by snapshot-db or by a safety dump (rollback). A pre-rollback
#            snapshot is taken first; the dump is restored into a fresh database in one
#            transaction and swapped in by rename, and the current database is kept beside it
#            as <db>_before_<utc> until the owner drops it. Stop the api and worker before it.
#
# Options:
#   --bundle DIR             the directory ship-data.sh sent to (verify, files, db)
#   --env-file FILE          the server's .env [<repo>/.env]; DATA_ROOT is read out of it by sed
#   --update-data            db: the new-data update path (above)
#   --replace-db             db: replace a database that already holds data (above)
#   --delete-beta-accounts   db: with --replace-db, accept that the beta's accounts go
#   --label NAME             snapshot-db: a word naming the snapshot (release, before-x, ...)
#   --allow-sha-mismatch     the bundle was built from a different git sha than this checkout
#   -h, --help
#
# Every step is idempotent: running `files` twice installs the same bytes twice; a graph's old
# build directory is kept (the previous `current` is recorded as `previous`), so the swap is
# undone by pointing the link back (docs/BETA-RUNBOOK.md, Rollback).
set -euo pipefail
export LC_ALL=C

die() { echo "receive-data: $*" >&2; exit 2; }
note() { echo "receive-data: $*" >&2; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)

bundle=""; env_file="$repo/.env"; replace_db=0; update_data=0; delete_accounts=0
allow_sha=0; command_name=""; label=""; dump_file=""

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
	case "$1" in
		-h | --help) usage; exit 0 ;;
		--bundle) [ $# -ge 2 ] || die "$1 needs a value"; bundle=$2; shift 2 ;;
		--env-file) [ $# -ge 2 ] || die "$1 needs a value"; env_file=$2; shift 2 ;;
		--label) [ $# -ge 2 ] || die "$1 needs a value"; label=$2; shift 2 ;;
		--replace-db) replace_db=1; shift ;;
		--update-data) update_data=1; shift ;;
		--delete-beta-accounts) delete_accounts=1; shift ;;
		--allow-sha-mismatch) allow_sha=1; shift ;;
		-*) die "unknown option $1" ;;
		*)
			if [ -z "$command_name" ]; then command_name=$1
			elif [ "$command_name" = restore-dump ] && [ -z "$dump_file" ]; then dump_file=$1
			else die "one command at a time"; fi
			shift
			;;
	esac
done
case "$command_name" in verify | files | db | snapshot-db | restore-dump) ;; *) die "give a command: verify, files, db, snapshot-db or restore-dump (--help)" ;; esac
[ "$update_data$replace_db" != 11 ] || die "--update-data and --replace-db are two different paths; give one"

[ -r "$env_file" ] || die "cannot read $env_file"
# Absolute, because beta-compose.sh runs from the checkout whatever the caller's directory.
env_file="$(cd "$(dirname "$env_file")" && pwd -P)/$(basename "$env_file")"
env_value() { sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$env_file" | tail -n 1 | tr -d '\r' | sed "s/^['\"]//; s/['\"]\$//"; }

data_root=$(env_value DATA_ROOT)
[ -n "$data_root" ] || die "no DATA_ROOT= in $env_file"
case "$data_root" in /?*) ;; *) die "DATA_ROOT '$data_root' is not absolute" ;; esac
case "$data_root" in
	/ | /etc | /usr | /var | /home | /root | /bin | /boot | /lib | /data | /data/) die "DATA_ROOT '$data_root' is a system directory; use a directory of its own such as /data/routemaker" ;;
esac
[ -d "$data_root" ] || die "$data_root does not exist; run scripts/prepare_data_root.sh first"

case "$command_name" in
	verify | files | db)
		[ -n "$bundle" ] || die "--bundle DIR is required"
		[ -d "$bundle" ] || die "$bundle is not a directory"
		bundle=$(cd "$bundle" && pwd -P)
		[ -r "$bundle/SHA256SUMS" ] && [ -r "$bundle/MANIFEST.txt" ] ||
			die "$bundle has no SHA256SUMS and MANIFEST.txt: the transfer did not finish (rerun ship-data.sh to resume)"
		case "$bundle/" in "$data_root"/*) die "the bundle ($bundle) is inside DATA_ROOT; keep it beside it, such as /data/routemaker-incoming" ;; esac
		;;
esac

manifest_value() { sed -n "s/^$1=//p" "$bundle/MANIFEST.txt" | head -n 1; }
has_part() { grep -qw "$1" <<<"$(manifest_value parts)"; }
bc() { BETA_ENV_FILE="$env_file" "$here/beta-compose.sh" "$@"; }

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

# The paths SHA256SUMS lists under a prefix, one per line, sorted. A sha256sum line is 64 hex
# digits, two characters, then the path.
listed() { awk -v p="$1" '{ f = substr($0, 67); if (index(f, p) == 1) print f }' "$bundle/SHA256SUMS" | sort; }

rsync_in=(rsync -a --no-owner --no-group --chmod=D755,F644)

# Install exactly the files SHA256SUMS lists under PREFIX (such as photon/), nothing else from
# the bundle directory. With delete=1, files under the same prefix in DATA_ROOT that the new
# bundle does not list are removed afterwards, which is what `rsync --delete` used to do.
install_listed() { # prefix delete(0|1) [path to leave out]
	local prefix=$1 delete=$2 skip=${3:-} list unlisted
	list=$(mktemp)
	listed "$prefix" | { if [ -n "$skip" ]; then grep -vxF -- "$skip" || true; else cat; fi; } >"$list"
	# (the front end's index.html is left out here and installed last by the caller, so for it an
	# empty remainder is fine)
	[ -s "$list" ] || [ -n "$skip" ] || { rm -f "$list"; die "SHA256SUMS lists nothing under $prefix"; }
	mkdir -p "$data_root/$prefix"
	if [ -s "$list" ]; then "${rsync_in[@]}" --files-from="$list" "$bundle/" "$data_root/"; fi
	unlisted=$(cd "$bundle" && find "${prefix%/}" -type f ! -path '*/.rsync-partial/*' | sort | comm -23 - "$list" | { if [ -n "$skip" ]; then grep -vxF -- "$skip" || true; else cat; fi; } | wc -l)
	[ "$unlisted" = 0 ] || note "$prefix: $unlisted file(s) in the bundle directory are not in SHA256SUMS (left by an earlier bundle); not installed"
	if [ "$delete" = 1 ]; then
		(cd "$data_root" && find "${prefix%/}" -type f | sort | comm -23 - "$list") | while IFS= read -r stale; do
			rm -f -- "$data_root/$stale"
		done
		find "$data_root/${prefix%/}" -mindepth 1 -type d -empty -delete
	fi
	rm -f "$list"
}

# ================================================================================================
if [ "$command_name" = files ]; then
	verify_bundle

	need=$(manifest_value bytes)
	avail=$(df -B1 --output=avail "$data_root" | tail -n 1 | tr -d ' ')
	# a copy plus 10 %: the bundle stays until the owner removes it
	if [ "$avail" -lt $((need + need / 10)) ]; then die "not enough room on $data_root: need about $((need / 1048576)) MiB, have $((avail / 1048576)) MiB"; fi

	photon_stopped=0; photon_restarted=0
	trap '[ "$photon_stopped" = 0 ] || [ "$photon_restarted" = 1 ] || note "photon was stopped for the install and is STILL STOPPED: once files succeeds, scripts/beta/beta-compose.sh start photon"' EXIT
	if has_part photon && command -v docker >/dev/null 2>&1; then
		if bc ps --status running --services 2>/dev/null | grep -qx photon; then
			note "stopping photon while its index is replaced (place search is unavailable meanwhile)"
			bc stop photon
			photon_stopped=1
		fi
	fi

	if has_part tiles; then
		pairs=$(manifest_value tiles)
		[ -n "$pairs" ] || die "the manifest carries tiles but names no builds (tiles=)"
		for pair in $pairs; do
			variant=${pair%%=*}; build=${pair#*=}
			case "$variant" in '' | *[!A-Za-z0-9._-]*) die "odd variant in the manifest: '$pair'" ;; esac
			case "$build" in '' | . | .. | *[!A-Za-z0-9._-]*) die "odd build in the manifest: '$pair'" ;; esac
			[ -d "$bundle/tiles/$variant/$build" ] || die "the manifest names tiles/$variant/$build, which is not in the bundle"
		done
		for build_dir in "$bundle"/tiles/*/*/; do
			[ -d "$build_dir" ] || continue
			rel=${build_dir#"$bundle"/tiles/}; rel=${rel%/}
			grep -qxF "${rel%%/*}=${rel#*/}" <<<"$(tr ' ' '\n' <<<"$pairs")" ||
				note "skipping tiles/$rel: not in this bundle's MANIFEST (left by an earlier bundle)"
		done
		for pair in $pairs; do
			variant=${pair%%=*}; build=${pair#*=}
			dest="$data_root/tiles/$variant"
			install_listed "tiles/$variant/$build/" 1
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
	fi

	if has_part elevation; then install_listed elevation/ 1; note "elevation installed"; fi
	if has_part basemap; then install_listed basemap/ 1; note "basemap installed"; fi

	if has_part photon; then
		install_listed photon/ 1
		# Photon's image runs as uid 9011 and writes lock files beside its index.
		if [ "$(id -u)" = 0 ]; then chown -R 9011:9011 "$data_root/photon"; else note "not root: left photon/ owned by $(id -un); the image's entrypoint re-owns it on start"; fi
		note "photon index installed"
	fi

	if has_part frontend; then
		# Hashed assets first, index.html last by rename: a page loaded mid-deploy gets the old app
		# or the new one, never an index naming files that are not there yet (docs/DEPLOYMENT.md).
		# No delete: a page loaded before the swap still asks for the old hashed files.
		[ -n "$(listed frontend/index.html)" ] || die "SHA256SUMS does not list frontend/index.html"
		install_listed frontend/ 0 frontend/index.html
		cp "$bundle/frontend/index.html" "$data_root/frontend/.index.html.new"
		chmod 644 "$data_root/frontend/.index.html.new"
		mv -f "$data_root/frontend/.index.html.new" "$data_root/frontend/index.html"
		note "front end installed"
	fi

	verify_installed
	if [ "$photon_stopped" = 1 ]; then
		bc start photon
		photon_restarted=1
		note "photon started again; it needs about a minute before its first search answers"
	fi
	note "files done. Restart the routers if they were already running: scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend"
	exit 0
fi

# ================================================================================================
# db, snapshot-db, restore-dump: all need the running postgis
pguser=$(env_value PGUSER); pguser=${pguser:-routemaker}
pgdatabase=$(env_value PGDATABASE); pgdatabase=${pgdatabase:-routemaker}
if [ "$command_name" = db ]; then live_schema=$(manifest_value live_schema); else live_schema=$(env_value ROUTEMAKER_LIVE_SCHEMA); fi
live_schema=${live_schema:-live}
case "$pguser$pgdatabase$live_schema" in *[!A-Za-z0-9_]*) die "odd database, user or schema name" ;; esac

# </dev/null on every `exec -T` that needs no input: it reads standard input otherwise, and would
# swallow whatever the caller is feeding this script (a heredoc, a pipe, the rest of a loop).
psql_q() { bc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -At -c "$1" </dev/null; }

running=$(bc ps --status running --services 2>/dev/null || true)
grep -qx postgis <<<"$running" || die "postgis is not running: scripts/beta/beta-compose.sh up -d postgis, and wait for it to be healthy"
for _ in $(seq 1 30); do
	[ "$(bc ps postgis --format '{{.Health}}' 2>/dev/null)" = healthy ] && break
	sleep 2
done
[ "$(bc ps postgis --format '{{.Health}}' 2>/dev/null)" = healthy ] || die "postgis is not healthy yet"

app_is_down() { # nothing may write while the database is replaced
	if grep -Eqx 'api|worker' <<<"$running"; then
		die "the api or worker is running; stop them first: scripts/beta/beta-compose.sh stop api worker"
	fi
}

# pg_dump of public and live into DATA_ROOT/backups/pre-<label>-<utc>.dump; prints the path.
# Not a name the worker's nightly pruning matches (routemaker-<utc>.dump), so it is kept.
snapshot() {
	local file
	file="$data_root/backups/pre-$1-$(date -u +%Y%m%dT%H%M%SZ).dump"
	[ -d "$data_root/backups" ] && [ -w "$data_root/backups" ] ||
		die "cannot write $data_root/backups (it is owned by the container uid): run this with sudo"
	note "safety dump of the current database to $file"
	# umask 077: the dump holds the beta's own accounts.
	(umask 077 && bc exec -T postgis pg_dump -U "$pguser" -d "$pgdatabase" --format=custom --no-owner -n public -n "$live_schema" </dev/null >"$file.part") ||
		{ rm -f "$file.part"; die "pg_dump failed; stopping before anything is replaced"; }
	[ -s "$file.part" ] || { rm -f "$file.part"; die "the safety dump is empty; stopping before anything is replaced"; }
	mv "$file.part" "$file"
	printf '%s\n' "$file"
}

# The dump names schema `public`, which every database already has, so a plain pg_restore ends with
# `schema "public" already exists` and exit 1 (tested against the shipped dump). Restoring from a
# table of contents with that one line removed is clean. The list is made here and copied in.
# Not --single-transaction: a failed statement should be seen, and rerunning is safe (--clean).
restore_whole() { # dump-file clean(0|1)
	local dump=$1 clean=$2 toc args=(--no-owner --no-privileges)
	[ "$clean" = 0 ] || args+=(--clean --if-exists)
	toc=$(mktemp)
	bc exec -T postgis pg_restore --list <"$dump" >"$toc" || die "could not read the table of contents of $dump"
	sed -i '/ SCHEMA - public /d' "$toc"
	bc exec -T postgis sh -c 'cat > /tmp/beta.use' <"$toc"
	rm -f "$toc"
	bc exec -T postgis pg_restore -U "$pguser" -d "$pgdatabase" "${args[@]}" -L /tmp/beta.use <"$dump" ||
		die "pg_restore reported errors (above); read them before using the database"
	bc exec -T postgis rm -f /tmp/beta.use </dev/null
	psql_q "analyze" >/dev/null
}

if [ "$command_name" = snapshot-db ]; then
	case "$label" in '' | *[!A-Za-z0-9._-]*) die "snapshot-db needs --label WORD (letters, digits, dot, dash, underscore)" ;; esac
	snapshot "$label"
	exit 0
fi

if [ "$command_name" = restore-dump ]; then
	[ -n "$dump_file" ] && [ -r "$dump_file" ] || die "restore-dump needs a readable dump file"
	app_is_down
	snapshot rollback >/dev/null
	# Into a FRESH database, then swapped in by rename (review r1, N4). A --clean restore over the
	# live database cannot undo schema growth: a table a newer release added (often with a foreign
	# key to a restored table) blocks the DROP and survives the restore, and the next forward
	# migrate then fails on it. The fresh database has exactly the dump's schema; the current one
	# is kept, renamed, until the owner drops it.
	stamp=$(date -u +%Y%m%d%H%M%S)
	fresh="${pgdatabase}_restore"
	kept="${pgdatabase}_before_${stamp}"
	psql_on() { bc exec -T postgis psql -U "$pguser" -d "$1" -v ON_ERROR_STOP=1 -At "${@:2}" </dev/null; }
	psql_on postgres -c "drop database if exists \"$fresh\"" >/dev/null
	template=template0
	[ "$(psql_on postgres -c "select count(*) from pg_database where datname = 'template_postgis'")" = 1 ] && template=template_postgis
	psql_on postgres -c "create database \"$fresh\" template $template" >/dev/null
	# The same extensions as the current database (pg_dump -n leaves extensions out of the dump).
	for ext in $(psql_q "select extname from pg_extension where extname <> 'plpgsql' order by oid"); do
		case "$ext" in *[!a-z0-9_]*) die "odd extension name '$ext'" ;; esac
		psql_on "$fresh" -c "create extension if not exists \"$ext\" cascade" >/dev/null
	done
	note "restoring $dump_file into a fresh database ($fresh), in one transaction"
	toc=$(mktemp)
	bc exec -T postgis pg_restore --list <"$dump_file" >"$toc" || die "could not read the table of contents of $dump_file"
	sed -i '/ SCHEMA - public /d' "$toc"
	bc exec -T postgis sh -c 'cat > /tmp/beta.use' <"$toc"
	rm -f "$toc"
	if ! bc exec -T postgis pg_restore -U "$pguser" -d "$fresh" --no-owner --no-privileges --single-transaction --exit-on-error -L /tmp/beta.use <"$dump_file"; then
		bc exec -T postgis rm -f /tmp/beta.use </dev/null
		psql_on postgres -c "drop database if exists \"$fresh\"" >/dev/null
		die "the restore failed (above) and was discarded; the current database is untouched"
	fi
	bc exec -T postgis rm -f /tmp/beta.use </dev/null
	[ "$(psql_on "$fresh" -c "select to_regclass('public.django_migrations') is not null")" = t ] ||
		die "the restored database ($fresh) has no django_migrations; it was left beside the current one, unused"
	psql_on "$fresh" -c "analyze" >/dev/null
	note "swapping it in: $pgdatabase becomes $kept, $fresh becomes $pgdatabase"
	# No session may be connected to either database while it is renamed: end them, wait until
	# they are gone, then both renames in one transaction (both happen, or neither).
	busy="select count(*) from pg_stat_activity where datname in ('$pgdatabase', '$fresh') and pid <> pg_backend_pid()"
	for _ in $(seq 1 10); do
		psql_on postgres -c "select count(pg_terminate_backend(pid)) from pg_stat_activity where datname in ('$pgdatabase', '$fresh') and pid <> pg_backend_pid()" >/dev/null
		[ "$(psql_on postgres -c "$busy")" = 0 ] && break
		sleep 1
	done
	psql_on postgres -1 -c "alter database \"$pgdatabase\" rename to \"$kept\"" -c "alter database \"$fresh\" rename to \"$pgdatabase\"" >/dev/null ||
		die "the swap failed (above) and was rolled back: $pgdatabase is unchanged, and the restored copy is $fresh"
	note "restored. The database as it was is kept as $kept; once the beta works, drop it: scripts/beta/beta-compose.sh exec -T postgis dropdb -U $pguser $kept"
	note "Start the stack on the release this dump belongs to: scripts/beta/beta-compose.sh up -d api worker"
	exit 0
fi

# --- db ---------------------------------------------------------------------------------------
has_part db || die "this bundle carries no db part"
[ -r "$bundle/db/routemaker.dump" ] && [ -r "$bundle/db/row-counts.tsv" ] || die "the bundle's db/ is incomplete"
verify_bundle db/
dump="$bundle/db/routemaker.dump"

existing=$(psql_q "select to_regclass('public.django_migrations') is not null")
accounts=0
if [ "$existing" = t ]; then
	accounts=$(psql_q "select coalesce((select count(*) from public.app_user), 0)")
fi

if [ "$update_data" = 1 ]; then
	# --- the new-data update: live, override and stress_tile_cache only, in one transaction ---
	[ "$existing" = t ] || die "--update-data needs a database restored once already; run db without it first"
	app_is_down
	toc=$(mktemp)
	bc exec -T postgis pg_restore --list <"$dump" >"$toc" || die "could not read the dump's table of contents"
	use=$(mktemp)
	# Every entry of the live schema (pre-data, data, post-data), the schema itself, and the data
	# and sequence position of the two public tables that come from home. Nothing else: no
	# account, session, guild or audit table is named, so none is dropped or written.
	grep -E "^[0-9]+; [0-9]+ [0-9]+ ([A-Z][A-Z ]* $live_schema |SCHEMA - $live_schema |TABLE DATA public (override|stress_tile_cache) |SEQUENCE SET public (override|stress_tile_cache)_)" "$toc" >"$use" || true
	rm -f "$toc"
	grep -q "TABLE DATA $live_schema " "$use" || { rm -f "$use"; die "the dump has no $live_schema data to update from"; }
	grep -q "TABLE DATA public override " "$use" || { rm -f "$use"; die "the dump has no override data"; }
	bc exec -T postgis sh -c 'cat > /tmp/beta.use' <"$use"
	rm -f "$use"
	snapshot update >/dev/null
	before_oid=$(psql_q "select coalesce(to_regclass('public.app_user')::oid::text, 'none')")
	note "updating $live_schema, override and stress_tile_cache in one transaction ($accounts beta account(s) are left alone)"
	# pg_restore writes SQL; psql runs it as ONE transaction that stops at the first error. If
	# pg_restore itself fails part-way, a deliberately failing statement follows its output so the
	# transaction rolls back instead of committing half an update.
	# shellcheck disable=SC2016
	bc exec -T postgis sh -c '{ echo "TRUNCATE public.override, public.stress_tile_cache;"; pg_restore --no-owner --no-privileges --clean --if-exists -L /tmp/beta.use -f - || echo "SELECT pg_restore_failed_so_this_rolls_back();"; } | psql -U "$1" -d "$2" -q -1 -v ON_ERROR_STOP=1 >/dev/null' sh "$pguser" "$pgdatabase" <"$dump" ||
		{ bc exec -T postgis rm -f /tmp/beta.use </dev/null; die "the update failed and was rolled back (above); the database is as it was"; }
	bc exec -T postgis rm -f /tmp/beta.use </dev/null
	psql_q "analyze" >/dev/null
	after_oid=$(psql_q "select coalesce(to_regclass('public.app_user')::oid::text, 'none')")
	[ "$before_oid" = "$after_oid" ] || die "public.app_user was recreated by the update; this should not happen, report it"
	after_accounts=$(psql_q "select count(*) from public.app_user")
	[ "$after_accounts" = "$accounts" ] || die "the beta had $accounts accounts and now has $after_accounts; report it"
	note "beta accounts untouched: $after_accounts"
else
	# --- the whole database ---
	clean=0
	if [ "$existing" = t ]; then
		overrides=$(psql_q "select coalesce((select count(*) from public.override), 0)")
		live_tables=$(psql_q "select count(*) from pg_tables where schemaname = '$live_schema'")
		if [ "${accounts:-0}" != 0 ] || [ "${overrides:-0}" != 0 ] || [ "${live_tables:-0}" != 0 ]; then
			[ "$replace_db" = 1 ] || die "the database already holds data ($accounts beta accounts, $overrides overrides, $live_tables tables in $live_schema). For new data use --update-data, which keeps the beta's accounts; --replace-db replaces everything"
			if [ "$accounts" != 0 ] && [ "$delete_accounts" != 1 ]; then
				die "the beta has $accounts account(s) of its own and the bundle carries none, so --replace-db would delete them. Use --update-data for new data; add --delete-beta-accounts only if deleting them is intended"
			fi
			app_is_down
			snapshot restore >/dev/null
		fi
		# Tables exist (migrate has run) or are being replaced: drop what the dump recreates.
		clean=1
	fi
	note "restoring (this takes a few minutes; postgis is capped at 1 GiB, so the index builds are slow, not failed)"
	restore_whole "$dump" "$clean"
fi

note "comparing row counts with the bundle's"
fail=0
while IFS=$'\t' read -r qualified expected; do
	[ -n "$qualified" ] || continue
	if [ "$update_data" = 1 ]; then
		case "$qualified" in "$live_schema".* | public.override | public.stress_tile_cache) ;; *) continue ;; esac
	fi
	actual=$(psql_q "select count(*) from \"${qualified%%.*}\".\"${qualified#*.}\"")
	if [ "$actual" = "$expected" ]; then
		continue
	fi
	case "$qualified" in
		"$live_schema".*) note "MISMATCH $qualified: shipped $expected, restored $actual"; fail=1 ;;
		*) note "note: $qualified had $expected rows when counted at home and has $actual here (the home site was in use; informational)" ;;
	esac
done <"$bundle/db/row-counts.tsv"
[ "$fail" = 0 ] || die "the $live_schema schema does not match the bundle; do not start the api. Restore again (--update-data, or --replace-db for a first install)"
if [ "$update_data" = 1 ]; then
	note "db update done. Start the api and worker again: scripts/beta/beta-compose.sh up -d api worker"
else
	note "db done. Next: scripts/beta/beta-compose.sh run --rm --no-deps migrate ./manage.py migrate --check"
fi
