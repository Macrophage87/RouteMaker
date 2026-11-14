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
#   files    verify, then install tiles, elevation, basemap, photon, the transit schedule and the front end under
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
#              --update-data: for a NEW DATA bundle once the beta is running, WHILE IT SERVES
#                (the owner, 2026-11-02: "do the staging swap"). The bundle's `live` schema is
#                restored beside the served one as `live_next` (by way of a scratch database,
#                <db>_stage, dropped afterwards), its row counts are checked, and then one short
#                transaction renames `live` to `live_old` and `live_next` to `live`, the same
#                rename the home rebuild's swap makes (pipeline.swap.swap_schemas). The api and
#                worker keep running throughout: requests queue while the rename holds its locks
#                (a second or two; 5 tries of 3 s at worst, RECEIVE_DATA_SWAP_TRIES and
#                RECEIVE_DATA_LOCK_TIMEOUT_MS, and then nothing changes). The same transaction replaces the data of `override`,
#                `junction_override` (the approved junction ratings) and `avoid_junction` (home's
#                Avoid junctions), all shipped with their person columns blanked; the beta's own
#                half-step edit history goes with the overrides it pointed at, its own stress
#                suggestions lose their link to that history, and its own junction suggestions
#                lose their link to a rating or Avoid junction it replaces (the suggestions
#                themselves are kept). It empties its own `stress_tile_cache`, which the new live
#                table makes stale. A safety dump is taken before the rename. Accounts, sessions
#                and everything else the beta has made of its own are not touched. The replaced
#                tables stay as `live_old` until the next update. Needs room on DATA_ROOT for
#                about two more copies of the live tables while it stages.
#              --stage-only: with --update-data, stage `live_next` and stop before the rename
#                (no sudo needed). A later `db --update-data` with the same bundle reuses it, so
#                the slow part can run before `files` moves the tile links and the rename follows
#                within seconds of them.
#              --replace-db: replace the whole database with the bundle's. The bundle carries
#                no accounts (OWNER-DECISIONS 367.3), so this deletes the beta's own; it is
#                refused while any exist unless --delete-beta-accounts is given too.
#   snapshot-db --label NAME
#            pg_dump the database to DATA_ROOT/backups/pre-NAME-<utc>.dump (or the same name
#            under --backups-dir) and print its path.
#            The runbook takes one before every release update (which may migrate forward).
#   restore-dump FILE
#            put back a dump made by snapshot-db or by a safety dump (rollback). A pre-rollback
#            snapshot is taken first; the dump is restored into a fresh database in one
#            transaction and swapped in by rename, and the current database is kept beside it
#            as <db>_before_<utc> (yyyymmddHHMMSS); the release agent (auto-release.sh) drops it
#            once it is 6.5 days old (while paused or BROKEN, every one but the newest), or the owner
#            sooner. Stop the api and worker before it.
#
# Options:
#   --bundle DIR             the directory ship-data.sh sent to (verify, files, db)
#   --env-file FILE          the server's .env [<repo>/.env]; DATA_ROOT is read out of it by sed
#   --update-data            db: the new-data update path (above)
#   --stage-only             db --update-data: stage only, rename nothing (above)
#   --replace-db             db: replace a database that already holds data (above)
#   --delete-beta-accounts   db: with --replace-db, accept that the beta's accounts go
#   --label NAME             snapshot-db: a word naming the snapshot (release, before-x, ...)
#   --allow-sha-mismatch     the bundle was built from a different git sha than this checkout
#   --backups-dir DIR        snapshot-db and restore-dump: write the safety dumps to DIR instead
#                            of DATA_ROOT/backups. The no-sudo mode the release agent uses
#                            (scripts/beta/auto-release.sh): DIR is a directory of the caller's
#                            own, absolute, outside DATA_ROOT, and writable by nobody else.
#                            Without it, each safety dump keeps the newest RECEIVE_DATA_KEEP [3]
#                            of its kind (pre-<label>-*.dump) in DATA_ROOT/backups and removes
#                            older ones, never the dump being restored; under --backups-dir the
#                            caller prunes its own.
#   -h, --help
#
# RECEIVE_DATA_REPO names the checkout whose beta-compose.sh and .env to use [the one this
# script is in]: the release agent runs its own installed copy of this script against the
# beta's checkout, whatever release that checkout is at.
#
# Every step is idempotent: running `files` twice installs the same bytes twice; a graph's old
# build directory is kept (the previous `current` is recorded as `previous`), so the swap is
# undone by pointing the link back (docs/BETA-RUNBOOK.md, Rollback).
set -euo pipefail
export LC_ALL=C

die() { echo "receive-data: $*" >&2; exit 2; }
note() { echo "receive-data: $*" >&2; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "${RECEIVE_DATA_REPO:-$here/../..}" && pwd)
[ -x "$repo/scripts/beta/beta-compose.sh" ] || die "$repo has no scripts/beta/beta-compose.sh"

bundle=""; env_file="$repo/.env"; replace_db=0; update_data=0; stage_only=0; delete_accounts=0
allow_sha=0; command_name=""; label=""; dump_file=""; backups_dir=""; prune_dumps=0

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
	case "$1" in
		-h | --help) usage; exit 0 ;;
		--bundle) [ $# -ge 2 ] || die "$1 needs a value"; bundle=$2; shift 2 ;;
		--env-file) [ $# -ge 2 ] || die "$1 needs a value"; env_file=$2; shift 2 ;;
		--label) [ $# -ge 2 ] || die "$1 needs a value"; label=$2; shift 2 ;;
		--replace-db) replace_db=1; shift ;;
		--update-data) update_data=1; shift ;;
		--stage-only) stage_only=1; shift ;;
		--delete-beta-accounts) delete_accounts=1; shift ;;
		--allow-sha-mismatch) allow_sha=1; shift ;;
		--backups-dir) [ $# -ge 2 ] || die "$1 needs a value"; backups_dir=$2; shift 2 ;;
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
[ "$stage_only" = 0 ] || { [ "$command_name" = db ] && [ "$update_data" = 1 ]; } || die "--stage-only goes with db --update-data"

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

# Where safety dumps go. The default is DATA_ROOT/backups, owned by the container uid (sudo).
# --backups-dir is the caller's own directory: it must already exist, be absolute, be owned by
# the caller, sit outside DATA_ROOT (the worker's nightly pruning and the containers see that
# tree), and be writable by nobody else (a dump holds the beta's accounts).
if [ -n "$backups_dir" ]; then
	case "$command_name" in snapshot-db | restore-dump | db) ;; *) die "--backups-dir is for snapshot-db, restore-dump and db" ;; esac
	case "$backups_dir" in /?*) ;; *) die "--backups-dir '$backups_dir' is not absolute" ;; esac
	[ -d "$backups_dir" ] && [ ! -L "$backups_dir" ] || die "--backups-dir $backups_dir is not a directory (create it first, mode 700)"
	backups_dir=$(cd "$backups_dir" && pwd -P)
	case "$backups_dir/" in "$(cd "$data_root" && pwd -P)"/*) die "--backups-dir $backups_dir is inside DATA_ROOT; use a directory of your own outside it" ;; esac
	[ "$(stat -c %u "$backups_dir")" = "$(id -u)" ] || die "--backups-dir $backups_dir is not owned by $(id -un)"
	case "$(stat -c %A "$backups_dir")" in ?????w???? | ????????w?) die "--backups-dir $backups_dir is writable by others; chmod 700 it" ;; esac
else
	backups_dir="$data_root/backups"
	prune_dumps=1
fi
dump_keep=${RECEIVE_DATA_KEEP:-3}
case "$dump_keep" in '' | *[!0-9]* | 0) die "RECEIVE_DATA_KEEP must be a whole number of 1 or more" ;; esac

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
bc() { BETA_ENV_FILE="$env_file" "$repo/scripts/beta/beta-compose.sh" "$@"; }
# Write each variant's valhalla_upstream row from its tile links (manage.py sync_upstreams), in
# the api container when it is running; otherwise say the line to run once it is.
SYNC_UPSTREAMS="scripts/beta/beta-compose.sh exec -T api ./manage.py sync_upstreams"
sync_upstreams_or_say() {
	if bc ps --status running --services 2>/dev/null | grep -x api >/dev/null; then
		note "writing the routers' settings rows from the tile links (manage.py sync_upstreams)"
		bc exec -T api ./manage.py sync_upstreams </dev/null ||
			note "WARNING: sync_upstreams failed; run it once the api is up: $SYNC_UPSTREAMS"
	else
		note "once the api is up, write the routers' settings rows from the tile links: $SYNC_UPSTREAMS"
	fi
}

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

rsync_in=(rsync -a --no-owner --no-group "--chmod=D755,F644")

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
			# The region packs travel as their own part (packs), not as a router graph.
			[ "${rel%%/*}" != offline-packs ] || continue
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

	if has_part transit; then
		# The transit ride types' schedule, beside the tile builds; the api reads it again when it
		# changes, so nothing restarts.
		install_listed tiles/transit/ 1
		note "transit schedule installed"
	fi

	if has_part packs; then
		# The region packs for riding off grid: the build folder first, the manifest that names it
		# last by rename, so the api never lists a pack that is not there yet. No delete: a phone
		# part way through a download still finishes it; builds beyond the newest two other than
		# the manifest's are removed after.
		[ -n "$(listed tiles/offline-packs/manifest.json)" ] || die "SHA256SUMS does not list tiles/offline-packs/manifest.json"
		install_listed tiles/offline-packs/ 0 tiles/offline-packs/manifest.json
		cp "$bundle/tiles/offline-packs/manifest.json" "$data_root/tiles/offline-packs/.manifest.json.new"
		chmod 644 "$data_root/tiles/offline-packs/.manifest.json.new"
		mv -f "$data_root/tiles/offline-packs/.manifest.json.new" "$data_root/tiles/offline-packs/manifest.json"
		packs_now=$(sed -n 's/^ *"dir": *"\(packs-[^"]*\)".*/\1/p' "$data_root/tiles/offline-packs/manifest.json" | head -n 1)
		(cd "$data_root/tiles/offline-packs" && find . -maxdepth 1 -mindepth 1 -type d -name 'packs-*' ! -name '*.part' -printf '%f\n' | sort -r | { grep -vxF -- "$packs_now" || true; } | tail -n +2) | while IFS= read -r old; do
			rm -rf -- "$data_root/tiles/offline-packs/$old"
		done
		note "region packs installed: $packs_now"
	fi

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
	note "files done. Restart the routers if they were already running: scripts/beta/beta-compose.sh restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend (restart-routers.sh, once installed, does it within about 7 minutes)"
	# The trail routers (the owner, 2026-10-20): started, or recreated onto the new build, once their tiles are here.
	trail=""
	for variant in offroad mtb paved paved-weekend; do
		[ -L "$data_root/tiles/$variant/current" ] && trail="$trail valhalla-$variant"
	done
	[ -z "$trail" ] || note "and start the trail routers on the new tiles: scripts/beta/beta-compose.sh up -d --force-recreate$trail"
	# The settings rows the api serves a variant by (core.routing._promoted_row) follow the
	# links just moved: nothing else on the beta writes them, and without an mtb or offroad row
	# Mountain Bike, Gravel and Mountain Goat are planned on the standard graph (2026-10-28).
	sync_upstreams_or_say
	exit 0
fi

# ================================================================================================
# db, snapshot-db, restore-dump: all need the running postgis
pguser=$(env_value PGUSER); pguser=${pguser:-routemaker}
pgdatabase=$(env_value PGDATABASE); pgdatabase=${pgdatabase:-routemaker}
if [ "$command_name" = db ]; then live_schema=$(manifest_value live_schema); else live_schema=$(env_value ROUTEMAKER_LIVE_SCHEMA); fi
live_schema=${live_schema:-live}
case "$pguser$pgdatabase$live_schema" in *[!A-Za-z0-9_]*) die "odd database, user or schema name" ;; esac

# One database change at a time: db and restore-dump share the files they copy into the postgis
# container (/tmp/beta.use, /tmp/beta-blanked.sql), and two updates would share the scratch
# database and the staged schema and undo each other's work. (So whoever runs these must be able to
# read DATA_ROOT, which prepare_data_root.sh leaves 0755.) The lock is DATA_ROOT itself,
# opened read-only: root and the login user can both open it, and no other user can make it
# fail or hold it, as they could a file in /tmp.
if [ "$command_name" = db ] || [ "$command_name" = restore-dump ]; then
	exec 7<"$data_root" || die "cannot open $data_root to lock it"
	flock -n 7 || die "another receive-data.sh db or restore-dump is running; wait for it"
fi

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
# Without the data of the tables the nightly backup leaves out (config.procrastinate
# BACKUP_EXCLUDED_TABLES): sessions, client addresses and riders' Garmin and Wahoo tokens. A
# restore from it signs riders out and asks them to connect those again.
snapshot_excluded=(cached_membership app_session django_session rate_limit_window stress_tile_cache
	bikeshare_feed_cache signed_out_send garmin_link wahoo_link)
snapshot() {
	local file
	file="$backups_dir/pre-$1-$(date -u +%Y%m%dT%H%M%SZ).dump"
	[ -d "$backups_dir" ] && [ -w "$backups_dir" ] ||
		die "cannot write $backups_dir (DATA_ROOT/backups is owned by the container uid): run this with sudo, or give --backups-dir"
	note "safety dump of the current database to $file"
	# umask 077: the dump holds the beta's own accounts.
	local excluded=() table
	for table in "${snapshot_excluded[@]}"; do excluded+=("--exclude-table-data=*.$table"); done
	(umask 077 && bc exec -T postgis pg_dump -U "$pguser" -d "$pgdatabase" --format=custom --no-owner -n public -n "$live_schema" "${excluded[@]}" </dev/null >"$file.part") ||
		{ rm -f "$file.part"; die "pg_dump failed; stopping before anything is replaced"; }
	[ -s "$file.part" ] || { rm -f "$file.part"; die "the safety dump is empty; stopping before anything is replaced"; }
	mv "$file.part" "$file"
	[ "$prune_dumps" = 0 ] || prune_snapshots "$1" "$file"
	printf '%s\n' "$file"
}
# The newest $dump_keep pre-<label> dumps in DATA_ROOT/backups stay; older ones go, except the one
# just written and the one a restore-dump is putting back. And none of any label older than
# 6.5 days (156 hours), with the same two exceptions: they are plain (an on-server rollback
# restores them, and the server holds no key to decrypt with), so they are kept no longer than
# the encrypted nightly dumps (config.procrastinate BACKUP_MAX_AGE; the nightly task holds the
# same age between updates).
snapshot_max_age_hours=156
prune_snapshots() { # label new-file
	local old stamp cutoff
	# shellcheck disable=SC2012
	ls -1t "$backups_dir"/pre-"$1"-*.dump 2>/dev/null | tail -n +"$((dump_keep + 1))" | while IFS= read -r old; do
		[ "$old" != "$2" ] && { [ -z "$dump_file" ] || [ ! "$old" -ef "$dump_file" ]; } || continue
		rm -f -- "$old" && note "removed an older safety dump: $old (keeping the newest $dump_keep)"
	done
	cutoff=$(date -u -d "-$snapshot_max_age_hours hours" +%Y%m%dT%H%M%SZ) || return 0
	for old in "$backups_dir"/pre-*-*.dump; do
		[ -f "$old" ] || continue
		stamp=${old##*-}; stamp=${stamp%.dump}
		[[ $stamp =~ ^[0-9]{8}T[0-9]{6}Z$ ]] && [[ $stamp < $cutoff ]] || continue
		[ "$old" != "$2" ] && { [ -z "$dump_file" ] || [ ! "$old" -ef "$dump_file" ]; } || continue
		rm -f -- "$old" && note "removed a safety dump older than $snapshot_max_age_hours hours: $old"
	done
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

# The tables ship-data.sh sends with their person columns blanked (db/blanked/<table>.copy,
# listed in SHA256SUMS): SQL that loads each named table and moves its id sequence past the
# loaded rows. Written to the file $1; the tables named in $2 onwards, or every one shipped.
blanked_tables() { sed -n 's|^[0-9a-f]\{64\}  db/blanked/\([a-z_]*\)\.copy$|\1|p' "$bundle/SHA256SUMS"; }
blanked_sql() {
	local out=$1 t header
	shift
	: >"$out"
	for t in "$@"; do
		[ -r "$bundle/db/blanked/$t.copy" ] || continue
		header=$(head -n 1 "$bundle/db/blanked/$t.copy" | tr -d '\r' | tr '\t' ',')
		case "$header" in '' | *[!a-z0-9_,]*) die "db/blanked/$t.copy has an odd header" ;; esac
		case ",$header," in *,id,*) ;; *) die "db/blanked/$t.copy has no id column" ;; esac
		{
			printf 'COPY public.%s (%s) FROM stdin WITH (FORMAT text, HEADER true);\n' "$t" "$header"
			cat "$bundle/db/blanked/$t.copy"
			printf '\\.\n'
			printf "SELECT setval(pg_get_serial_sequence('public.%s', 'id'), coalesce(max(id), 1), max(id) IS NOT NULL) FROM public.%s;\n" "$t" "$t"
		} >>"$out"
	done
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
	# is kept, renamed, for at most 6.5 days
	# (auto-release.sh prune_kept_dbs reads its age from the stamp in the name).
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
	note "restored. The database as it was is kept as $kept; the release agent drops it after 6.5 days (while it is paused or BROKEN, only once a newer one is kept; scripts/beta/auto-release.sh), or drop it sooner once the beta works: scripts/beta/beta-compose.sh exec -T postgis dropdb -U $pguser $kept"
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
	# --- the new-data update: staged beside the served tables, then one short rename ---
	[ "$existing" = t ] || die "--update-data needs a database restored once already; run db without it first"
	# The api and worker keep running: the served tables are not touched until the rename.
	lock_timeout_ms=${RECEIVE_DATA_LOCK_TIMEOUT_MS:-3000}
	swap_tries=${RECEIVE_DATA_SWAP_TRIES:-5}
	[[ $lock_timeout_ms =~ ^[1-9][0-9]*$ ]] && [[ $swap_tries =~ ^[1-9][0-9]*$ ]] ||
		die "RECEIVE_DATA_LOCK_TIMEOUT_MS and RECEIVE_DATA_SWAP_TRIES are whole numbers of 1 or more"
	staged="${live_schema}_next"
	retired="${live_schema}_old"
	scratch="${pgdatabase}_stage"
	# PostgreSQL cuts names at 63 bytes; a cut name could be another schema's or database's.
	[ ${#staged} -le 63 ] && [ ${#scratch} -le 63 ] || die "the live schema or database name is too long to stage beside"
	[ "$(psql_q "select to_regclass('$live_schema.segment') is not null")" = t ] ||
		die "there is no $live_schema.segment to swap out; restore with db (first install) instead"
	dump_sum=$(awk '$2 == "db/routemaker.dump" { print $1 }' "$bundle/SHA256SUMS")
	[[ $dump_sum =~ ^[0-9a-f]{64}$ ]] || die "SHA256SUMS does not list db/routemaker.dump"
	toc=$(mktemp)
	bc exec -T postgis pg_restore --list <"$dump" >"$toc" || die "could not read the dump's table of contents"
	use=$(mktemp)
	# Every entry of the live schema (pre-data, data, post-data) and the schema itself. Nothing
	# else: no account, session, guild or audit table is named, so none is dropped or written.
	# The public tables that come from home, override, junction_override and avoid_junction, are
	# not in the dump: they come blanked (db/blanked, below). (stress_tile_cache is not in the
	# bundle: ship-data.sh says why.)
	grep -E "^[0-9]+; [0-9]+ [0-9]+ ([A-Z][A-Z ]* $live_schema |SCHEMA - $live_schema )" "$toc" >"$use" || true
	rm -f "$toc"
	grep -q "TABLE DATA $live_schema " "$use" || { rm -f "$use"; die "the dump has no $live_schema data to update from"; }
	grep -qx override <<<"$(blanked_tables)" || { rm -f "$use"; die "the bundle has no override data (db/blanked/override.copy)"; }

	psql_db() { bc exec -T postgis psql -U "$pguser" -d "$1" -v ON_ERROR_STOP=1 -At "${@:2}" </dev/null; }
	staged_from=$(psql_q "select coalesce(obj_description(oid, 'pg_namespace'), '') from pg_namespace where nspname = '$staged'")
	if [ "$staged_from" = "bundle $dump_sum" ]; then
		rm -f "$use"
		note "reusing $staged, staged earlier from this bundle"
	else
		# Whatever an earlier staging left (another bundle's, or one cut short) goes first, so
		# the room below is measured without it. WITH (FORCE): a restore left running in the
		# container by an interrupted run would otherwise hold the scratch database open.
		psql_q "drop schema if exists \"$staged\" cascade" >/dev/null
		psql_db postgres -c "drop database if exists \"$scratch\" with (force)" >/dev/null
		# Room for the scratch copy, the staged one and the safety dump, beside the served and the
		# retired tables, with some over for the restores' WAL.
		live_bytes=$(psql_q "select coalesce(sum(pg_total_relation_size(c.oid)), 0) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = '$live_schema' and c.relkind in ('r', 'm')")
		avail=$(df -B1 --output=avail "$data_root" | tail -n 1 | tr -d ' ')
		if [ "$avail" -lt $((live_bytes * 3)) ]; then
			rm -f "$use"
			die "not enough room on $data_root to stage beside the served tables: need about $((live_bytes * 3 / 1048576)) MiB, have $((avail / 1048576)) MiB"
		fi
		note "staging the bundle's $live_schema as $staged while the beta serves (a few minutes per GB; nothing served changes)"
		# A scratch database of its own: the dump names its tables $live_schema.*, a name the
		# served database already uses. There it is renamed, then copied over under its new name.
		# From here on, any way out (a failure, a die, Ctrl-C) drops it again.
		unstage() {
			bc exec -T postgis rm -f /tmp/beta.use </dev/null || true
			psql_db postgres -c "drop database if exists \"$scratch\" with (force)" >/dev/null || note "WARNING: could not drop the scratch database $scratch; drop it by hand"
		}
		trap unstage EXIT
		template=template0
		[ "$(psql_db postgres -c "select count(*) from pg_database where datname = 'template_postgis'")" = 1 ] && template=template_postgis
		psql_db postgres -c "create database \"$scratch\" template $template" >/dev/null
		for ext in $(psql_q "select extname from pg_extension where extname <> 'plpgsql' order by oid"); do
			case "$ext" in *[!a-z0-9_]*) die "odd extension name '$ext'" ;; esac
			psql_db "$scratch" -c "create extension if not exists \"$ext\" cascade" >/dev/null
		done
		bc exec -T postgis sh -c 'cat > /tmp/beta.use' <"$use"
		rm -f "$use"
		if ! bc exec -T postgis pg_restore -U "$pguser" -d "$scratch" --no-owner --no-privileges --single-transaction --exit-on-error -L /tmp/beta.use <"$dump"; then
			die "staging failed (above) and was discarded; nothing served has changed"
		fi
		psql_db "$scratch" -c "alter schema \"$live_schema\" rename to \"$staged\"" >/dev/null
		# Into the served database in one transaction; pg_dump's own exit status is checked too,
		# so a dump cut short is never taken for a whole one.
		# shellcheck disable=SC2016 # the inner shell's
		if ! bc exec -T postgis sh -c 'rc=$(mktemp); trap '\''rm -f "$rc"'\'' EXIT; { pg_dump -U "$1" -d "$2" --format=custom --no-owner -n "$4"; echo $? >"$rc"; } | pg_restore -U "$1" -d "$3" --no-owner --no-privileges --single-transaction --exit-on-error; r=$?; d=$(cat "$rc"); [ "$r" = 0 ] && [ "$d" = 0 ]' sh "$pguser" "$scratch" "$pgdatabase" "$staged" </dev/null; then
			psql_q "drop schema if exists \"$staged\" cascade" >/dev/null
			die "copying the staged tables in failed (above) and was discarded; nothing served has changed"
		fi
		unstage
		trap - EXIT
		# Counted before anything is renamed: a short table is refused here, not after the swap.
		while IFS=$'\t' read -r qualified expected; do
			[[ $qualified == "$live_schema".* ]] || continue
			actual=$(psql_q "select count(*) from \"$staged\".\"${qualified#*.}\"")
			[ "$actual" = "$expected" ] || die "MISMATCH $staged.${qualified#*.}: shipped $expected, staged $actual. Nothing served has changed; stage again"
		done <"$bundle/db/row-counts.tsv"
		for table in $(psql_q "select tablename from pg_tables where schemaname = '$staged'"); do
			case "$table" in *[!a-z0-9_]*) die "odd table name '$table' in $staged" ;; esac
			psql_q "analyze \"$staged\".\"$table\"" >/dev/null
		done
		psql_q "comment on schema \"$staged\" is 'bundle $dump_sum'" >/dev/null
		note "staged: $staged holds this bundle's $live_schema"
	fi
	if [ "$stage_only" = 1 ]; then
		note "stage only: nothing renamed. Next: files, then db --update-data (it reuses $staged and swaps within seconds)"
		exit 0
	fi

	# override, the approved junction ratings and the Avoid junctions come from home
	# blanked (ship-data.sh). override is emptied below; the junction ratings and
	# Avoid junctions are replaced as override's are, the beta's own junction suggestions letting
	# go of them first (their foreign keys would refuse the commit).
	extra=$(mktemp)
	blanked_sql "$extra.part" override
	for t in junction_override avoid_junction; do
		if grep -qx "$t" <<<"$(blanked_tables)"; then
			case $t in
				junction_override) printf 'UPDATE public.junction_suggestion SET override_id = NULL WHERE override_id IS NOT NULL;\n' ;;
				avoid_junction) printf 'UPDATE public.junction_suggestion SET avoid_id = NULL WHERE avoid_id IS NOT NULL;\n' ;;
			esac >>"$extra.part"
			printf 'DELETE FROM public.%s;\n' "$t" >>"$extra.part"
			blanked_sql "$extra.more" "$t"
			cat "$extra.more" >>"$extra.part"
			rm -f "$extra.more"
		else
			note "this bundle carries no $t (db/blanked/$t.copy); the beta's are left as they are"
		fi
	done
	mv "$extra.part" "$extra"
	# After the blanked tables are read and checked, so a malformed one stops before the dump; a
	# failed dump leaves no copy of them behind.
	trap 'rm -f "$extra"' EXIT
	snapshot update >/dev/null
	bc exec -T postgis sh -c 'cat > /tmp/beta-blanked.sql' <"$extra"
	rm -f "$extra"
	trap - EXIT
	before_oid=$(psql_q "select coalesce(to_regclass('public.app_user')::oid::text, 'none')")
	note "swapping $staged in for $live_schema and updating override, the junction ratings and the Avoid junctions in one transaction, and emptying the stale stress tile cache ($accounts beta account(s) are left alone; the beta keeps serving)"
	# psql runs it as ONE transaction that stops at the first error, so a failure renames nothing.
	# lock_timeout bounds each lock it waits for, so a slow reader costs this an attempt (tried
	# again, as pipeline.swap does) rather than queueing every request behind it. The served
	# tables are locked FIRST, as pipeline.swap.swap_schemas locks them, and in the order a road
	# panel edit takes them (segment, then the tile cache), so the two cannot deadlock and
	# nothing else is held while this waits: requests already reading them finish first, later
	# ones wait the moment the rename takes and then read the new tables. At worst (every attempt
	# waiting its full timeout) that is about 35 s of queued requests, and then nothing changes. The beta's own stress_tile_cache is emptied in the same transaction: its rows are
	# keyed on the oid of the live table this replaces, so none could be served again (the
	# runbook predraws afterwards). stress_edit is emptied with override (it points at the
	# overrides it replaced); the beta's own stress suggestions are kept and let go of the edit
	# an approval made first, and so are Review's rulings (review_ruling, the beta's own) of
	# their edit and access override: a ruling keeps its road, decision, level, reason, author
	# and time, so its record and audit line still read whole, and an undo inside its window
	# then only marks it undone (what it changed is the bundle's now). Both are emptied
	# with DELETE, not TRUNCATE: a TRUNCATE refuses a table another table's foreign key points at,
	# even with no row pointing (stress_suggestion.edit_id, migration 0016), and a DELETE does not.
	# Every table of the served schema, segment first: a request that reads two of them (a
	# join) must see both old or both new, and the rename itself locks no table.
	lock_list=$(psql_q "select string_agg(format('%I.%I', schemaname, tablename), ', ' order by tablename <> 'segment', tablename) from pg_tables where schemaname = '$live_schema'")
	[[ $lock_list =~ ^[a-z0-9_.,\ ]+$ ]] || die "odd table names in $live_schema: $lock_list"
	swap_err=$(mktemp)
	swapped=0
	for attempt in $(seq 1 "$swap_tries"); do
		# shellcheck disable=SC2016
		if bc exec -T postgis sh -c '{ echo "SET LOCAL lock_timeout = '\''$7ms'\'';"; echo "LOCK TABLE $6 IN ACCESS EXCLUSIVE MODE;"; echo "UPDATE public.stress_suggestion SET edit_id = NULL WHERE edit_id IS NOT NULL;"; echo "UPDATE public.review_ruling SET edit_id = NULL WHERE edit_id IS NOT NULL;"; echo "UPDATE public.review_ruling SET access_override_id = NULL WHERE access_override_id IS NOT NULL;"; echo "DELETE FROM public.stress_edit;"; echo "DELETE FROM public.override;"; echo "TRUNCATE public.stress_tile_cache;"; echo "DROP SCHEMA IF EXISTS \"$5\" CASCADE;"; echo "ALTER SCHEMA \"$3\" RENAME TO \"$5\";"; echo "ALTER SCHEMA \"$4\" RENAME TO \"$3\";"; echo "COMMENT ON SCHEMA \"$3\" IS NULL;"; cat /tmp/beta-blanked.sql || echo "SELECT blanked_sql_missing_so_this_rolls_back();"; } | psql -U "$1" -d "$2" -q -1 -v ON_ERROR_STOP=1 >/dev/null' sh "$pguser" "$pgdatabase" "$live_schema" "$staged" "$retired" "$lock_list" "$lock_timeout_ms" </dev/null 2>"$swap_err"; then
			swapped=1
			break
		fi
		cat "$swap_err" >&2
		# Only lock contention is worth another try; anything else would fail the same way.
		grep -Eq 'lock timeout|deadlock detected' "$swap_err" || break
		[ "$attempt" = "$swap_tries" ] || { note "the rename waited too long for a reader (attempt $attempt of $swap_tries); trying again"; sleep $((2 * attempt)); }
	done
	rm -f "$swap_err"
	bc exec -T postgis rm -f /tmp/beta-blanked.sql </dev/null
	[ "$swapped" = 1 ] || die "the swap failed and was rolled back (above); the beta still serves the old $live_schema, and $staged is kept for the next try"
	note "the swap is committed: the beta now serves the new $live_schema"
	# The staged tables were analyzed before the rename; only the reloaded ones are new here.
	psql_q "analyze public.override, public.junction_override, public.avoid_junction" >/dev/null
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
	# The tables shipped with their person columns blanked, loaded in one transaction.
	read -r -a shipped_blank <<<"$(blanked_tables | tr '\n' ' ')"
	if [ ${#shipped_blank[@]} -gt 0 ]; then
		extra=$(mktemp)
		blanked_sql "$extra" "${shipped_blank[@]}"
		note "loading ${shipped_blank[*]} (shipped with their person columns blanked)"
		bc exec -T postgis sh -c 'cat > /tmp/beta-blanked.sql' <"$extra"
		rm -f "$extra"
		bc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -q -1 -v ON_ERROR_STOP=1 -f /tmp/beta-blanked.sql </dev/null >/dev/null ||
			{ bc exec -T postgis rm -f /tmp/beta-blanked.sql </dev/null; die "loading the blanked tables (override, the junction ratings and the Avoid junctions) failed and was rolled back (above), so the database has the rest of the bundle without them; restore again with: db --replace-db"; }
		bc exec -T postgis rm -f /tmp/beta-blanked.sql </dev/null
	fi
fi

note "comparing row counts with the bundle's"
fail=0
while IFS=$'\t' read -r qualified expected; do
	[ -n "$qualified" ] || continue
	if [ "$update_data" = 1 ]; then
		case "$qualified" in "$live_schema".* | public.override | public.junction_override | public.avoid_junction) ;; *) continue ;; esac
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
if [ "$fail" != 0 ]; then
	[ "$update_data" = 1 ] && die "the $live_schema schema does not match the bundle, and it is being served. Put the replaced tables back (docs/BETA-RUNBOOK.md, rollback B, \"by rename\"), then look"
	die "the $live_schema schema does not match the bundle; do not start the api. Restore again (--replace-db for a first install)"
fi
if [ "$update_data" = 1 ]; then
	note "db update done; the old tables stay as $retired until the next update. If the api and worker were stopped, start them: scripts/beta/beta-compose.sh up -d api worker"
	note "then restart the routers one at a time onto the new tiles, and write their settings rows: $SYNC_UPSTREAMS"
else
	note "db done. Next: scripts/beta/beta-compose.sh run --rm --no-deps migrate ./manage.py migrate --check"
	# A home dump carries home's rows, which name home's builds, not the beta's links.
	note "and once the api is up, write the routers' settings rows from the tile links: $SYNC_UPSTREAMS"
fi
