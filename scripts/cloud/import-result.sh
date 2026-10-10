#!/usr/bin/env bash
# Brings a cloud rebuild's result home and swaps it in. Run at home, from the live stack's
# checkout. Pairs with scripts/cloud/send-inputs.sh and scripts/cloud/box-rebuild.sh;
# docs/OPERATIONS.md, "Rebuilding on the cloud box".
#
#   scripts/cloud/import-result.sh [options] RUN_URL          install, then a dry run
#   scripts/cloud/import-result.sh [options] --swap RUN_URL   the swap, then the routers
#
#   RUN_URL   the same s3://<bucket>/rebuild-checkpoints/transfer/<run> as the other two
#
# Without --swap (changes nothing that is served):
#   1. downloads RUN_URL/out/ to --stage and checks every file against SHA256SUMS
#   2. refuses unless: the box built the commit this checkout is on (or
#      --allow-sha-mismatch); no rebuild is queued or running here; there is no staging
#      schema; no graph is serving or keeping the box's build id; there is room for the
#      graphs under DATA_ROOT/tiles
#   3. takes a safety dump of the database into --stage, leaving out the same tables the
#      nightly backup does (--no-safety-dump skips it)
#   4. unpacks the five graphs' build directories under DATA_ROOT/tiles, beside the ones
#      being served, and restores the box's segment table as the staging schema
#   5. runs `manage.py import_cloud_build <build> --overrides-read-at <backup time>`, dry:
#      every check the swap makes, and what it would change
# Run it again after a failure and it carries on: a build directory left by an unpack
# that stopped is unpacked again, and once step 4 has finished it goes straight to step 5.
#
# The second stage, --swap: `import_cloud_build --confirm` (the rebuild's own swap;
# `rollback_rebuild` undoes it), then restarts the routers and draws the stress tiles
# again, as after any rebuild. Then run the post-swap closure probes (OPERATIONS.md,
# "Bicycle closures in the tiles", step 3). Options after `--` go to import_cloud_build,
# e.g. `--swap RUN_URL -- --accept-later-overrides`.
#
# Options:
#   --live-dir DIR          the live stack's checkout: compose.yaml and .env [this repository]
#   --stage DIR             where the result is downloaded [~/cloud-runs/<run>/out]
#   --profile NAME          the AWS CLI profile (`aws sso login --profile NAME` first)
#   --swap                  the second stage above, after an install and its dry run
#   --no-safety-dump        skip step 3 (rollback_rebuild still works without it)
#   --remove-tars           delete the downloaded graph tars once they are unpacked
#   --allow-sha-mismatch    install a build made from another commit than this checkout's
#   -h, --help
# Environment (for tests): CLOUD_AWS [aws], CLOUD_DOCKER [docker], CLOUD_SUDO [sudo],
# CLOUD_GIT [git].
set -Eeuo pipefail

die() { echo "import-result: $*" >&2; exit 2; }
note() { echo "import-result: $*"; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
live_dir=$(cd "$here/../.." && pwd)
stage="" profile="" swap=0 safety=1 allow_mismatch=0 remove_tars=0 url="" extra=()
while [ $# -gt 0 ]; do
	case "$1" in
		--live-dir) [ $# -ge 2 ] || die "$1 needs a value"; live_dir=$2; shift 2 ;;
		--stage) [ $# -ge 2 ] || die "$1 needs a value"; stage=$2; shift 2 ;;
		--profile) [ $# -ge 2 ] || die "$1 needs a value"; profile=$2; shift 2 ;;
		--swap) swap=1; shift ;;
		--no-safety-dump) safety=0; shift ;;
		--allow-sha-mismatch) allow_mismatch=1; shift ;;
		--remove-tars) remove_tars=1; shift ;;
		--) shift; extra=("$@"); break ;;
		-h | --help) sed -n '2,/^set -E/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
		-*) die "unknown option $1" ;;
		*) [ -z "$url" ] || die "one RUN_URL only"; url=$1; shift ;;
	esac
done
[ -n "$url" ] || die "usage: import-result.sh [--swap] [options] s3://<bucket>/rebuild-checkpoints/transfer/<run>"
url=${url%/}
case "$url" in s3://?*/?*) ;; *) die "RUN_URL must be s3://<bucket>/.../<run>, not $url" ;; esac
run=${url##*/}
[[ "$run" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || die "the run name '$run' must be lowercase letters, digits and hyphens"

AWS=${CLOUD_AWS:-aws}
DOCKER=${CLOUD_DOCKER:-docker}
SUDO=${CLOUD_SUDO-sudo}
GIT=${CLOUD_GIT:-git}
aws_() { if [ -n "$profile" ]; then "$AWS" --profile "$profile" "$@"; else "$AWS" "$@"; fi; }

live_dir=$(cd "$live_dir" && pwd) || die "no such directory: $live_dir"
env_file="$live_dir/.env"
[ -r "$env_file" ] || die "no .env in $live_dir: --live-dir names the checkout the live stack runs from"
env_value() { local v; v=$(sed -n "s/^$1=//p" "$env_file" | tail -n1); v=${v%\"}; echo "${v#\"}"; }
data_root=$(env_value DATA_ROOT)
case "$data_root" in /?*) ;; *) die "DATA_ROOT in $env_file is not an absolute path" ;; esac
pguser=$(env_value PGUSER); pguser=${pguser:-routemaker}
pgdb=$(env_value PGDATABASE); pgdb=${pgdb:-routemaker}
compose() { (cd "$live_dir" && "$DOCKER" compose "$@"); }
psql_() { compose exec -T postgis psql -U "$pguser" -d "$pgdb" -AtX -v ON_ERROR_STOP=1 -c "$1" </dev/null; }

[ -n "$stage" ] || stage="$HOME/cloud-runs/$run/out"
# Checked before anything is created, so a mistaken --stage never writes into DATA_ROOT.
stage=$(realpath -m "$stage")
case "$stage/" in
	"$(realpath -m "$data_root")"/* | "$(realpath -m "$live_dir")"/*)
		die "--stage $stage is inside DATA_ROOT or the checkout; put it elsewhere" ;;
esac
mkdir -p "$stage"
manifest() { sed -n "s/^$1=//p" "$stage/MANIFEST.txt" | tail -n1; }
read_manifest() {
	build=$(manifest build)
	read_at=$(manifest read_at)
	commit=$(manifest commit)
	[[ "$build" =~ ^[0-9]{8}T[0-9]{6}Z(-[0-9]+)?$ ]] || die "MANIFEST.txt names no build id"
	[[ "$read_at" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "MANIFEST.txt names no read_at"
}
import_cmd() {
	compose exec -T rebuild ./manage.py import_cloud_build "$build" --overrides-read-at "$read_at" "$@" </dev/null
}

if [ "$swap" = 1 ]; then
	[ -f "$stage/MANIFEST.txt" ] || die "nothing installed from $run yet: run this without --swap first"
	read_manifest
	note "swapping in build $build"
	import_cmd --confirm ${extra[@]+"${extra[@]}"}
	note "restarting the routers so they serve the new graphs"
	compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
	if [ -n "$(compose --profile offroad ps -q valhalla-offroad 2>/dev/null)" ]; then
		compose --profile offroad restart valhalla-offroad
	fi
	note "drawing the stress tiles again"
	compose exec -T api python manage.py predraw_stress_tiles </dev/null
	note "done. Now the post-swap closure probes (OPERATIONS.md, \"Bicycle closures in the tiles\", step 3)."
	note "to undo: docker compose exec -T rebuild ./manage.py rollback_rebuild, then the same with --confirm, then restart the routers"
	exit 0
fi

# --- 1. download -------------------------------------------------------------------------
note "downloading $url/out/ to $stage"
rm -f "$stage/SHA256SUMS"
# sync, so a second run downloads only what changed.
aws_ s3 sync "$url/out/" "$stage/" --only-show-errors
[ -s "$stage/SHA256SUMS" ] || die "$url/out/ has no SHA256SUMS: the box did not finish its upload"
(cd "$stage" && sha256sum --quiet -c SHA256SUMS) || die "a file in $stage does not match SHA256SUMS; download it again"
read_manifest
note "build $build, made from commit $commit with the database as of $read_at"

# --- 2. pre-flight -----------------------------------------------------------------------
here_commit=$("$GIT" -C "$live_dir" rev-parse HEAD) || die "$live_dir is not a git checkout"
if [ "$here_commit" != "$commit" ]; then
	[ "$allow_mismatch" = 1 ] || die "the box built $commit and this checkout is on $here_commit; deploy that commit first, or pass --allow-sha-mismatch"
	note "WARNING: built from $commit, this checkout is on $here_commit"
fi
in_flight=$(psql_ "SELECT string_agg(id || ' ' || status, ', ') FROM procrastinate_jobs WHERE task_name = 'weekly_rebuild' AND status IN ('todo', 'doing')")
[ -z "$in_flight" ] || die "a rebuild is in flight here (job $in_flight); let it finish first"
installed=0
if [ "$(cat "$stage/installed" 2>/dev/null)" = "$build" ] &&
	[ "$(psql_ "SELECT to_regclass('staging.segment') IS NOT NULL")" = t ]; then
	installed=1
	note "build $build is already installed; going straight to the dry run"
fi
if [ "$installed" = 0 ]; then
	[ "$(psql_ "SELECT to_regnamespace('staging') IS NULL")" = t ] ||
		die "a staging schema already exists here (left by a rebuild that did not swap, or an install that stopped). If you are sure nothing needs it: docker compose exec -T postgis psql -U $pguser -d $pgdb -c 'DROP SCHEMA staging CASCADE', then run this again"
	need=0
	for variant in standard no-trail ebike weekend offroad; do
		[ -f "$stage/tiles-$variant.tar" ] || die "the result has no tiles-$variant.tar"
		for link in current previous; do
			[ "$($SUDO readlink "$data_root/tiles/$variant/$link" 2>/dev/null)" != "$build" ] ||
				die "$variant's $link link already names $build; it was swapped in before"
		done
		need=$((need + $(stat -c %s "$stage/tiles-$variant.tar")))
	done
	free=$(df -B1 --output=avail "$data_root/tiles" | tail -n1 | tr -d ' ')
	[ "$free" -gt $((need + need / 10)) ] ||
		die "$data_root/tiles has $((free / 1073741824)) GB free and the graphs need $((need / 1073741824)) GB and a margin; make room first"
fi

# --- 3. safety dump ----------------------------------------------------------------------
if [ "$installed" = 0 ] && [ "$safety" = 1 ]; then
	dump="$stage/before-import-$(date -u +%Y%m%dT%H%M%SZ).dump"
	note "safety dump of the database to $dump"
	# The same tables left out as the nightly backup (config.procrastinate.BACKUP_EXCLUDED_TABLES):
	# sessions and client addresses do not belong in a file that sits in a home folder.
	(umask 077 && compose exec -T postgis pg_dump -U "$pguser" -d "$pgdb" -Fc \
		--exclude-table-data='*.cached_membership' --exclude-table-data='*.app_session' \
		--exclude-table-data='*.rate_limit_window' --exclude-table-data='*.stress_tile_cache' \
		</dev/null >"$dump")
fi

# --- 4. install --------------------------------------------------------------------------
if [ "$installed" = 0 ]; then
	note "unpacking the graphs under $data_root/tiles"
	for variant in standard no-trail ebike weekend offroad; do
		# Neither link names it (checked above), so a directory here is an unpack that stopped.
		$SUDO rm -rf "${data_root:?}/tiles/$variant/$build"
		$SUDO tar -C "$data_root/tiles" --numeric-owner -xf "$stage/tiles-$variant.tar"
	done
	note "restoring the box's segment table as the staging schema"
	compose exec -T postgis pg_restore --no-owner -U "$pguser" -d "$pgdb" <"$stage/staging.dump" ||
		die "pg_restore did not exit 0. Nothing is served from staging; drop it (docker compose exec -T postgis psql -U $pguser -d $pgdb -c 'DROP SCHEMA staging CASCADE') and run this again"
	echo "$build" >"$stage/installed"
	if [ "$remove_tars" = 1 ]; then
		rm -f "$stage"/tiles-*.tar
	fi
fi

# --- 5. dry run --------------------------------------------------------------------------
import_cmd ${extra[@]+"${extra[@]}"}
note "installed. Nothing served has changed. To swap it in: scripts/cloud/import-result.sh --swap $url"
