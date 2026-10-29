#!/usr/bin/env bash
# Brings a cloud rebuild's result home and swaps it in. Run at home, from the live stack's
# checkout. Pairs with scripts/cloud/send-inputs.sh and scripts/cloud/box-rebuild.sh;
# docs/OPERATIONS.md, "Rebuilding on the cloud box".
#
#   scripts/cloud/import-result.sh [options] RUN_URL          install, then a dry run
#   scripts/cloud/import-result.sh [options] --swap RUN_URL   the swap, then the routers
#   scripts/cloud/import-result.sh --beta [options] RUN_URL   on the beta server (below)
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
#   4. unpacks the six graphs' build directories under DATA_ROOT/tiles, beside the ones
#      being served, and restores the box's segment table as the staging schema
#   5. runs `manage.py import_cloud_build <build> --overrides-read-at <the dump's read_at>`, dry:
#      every check the swap makes, and what it would change; it also precomputes Review's queue
#      (the roads whose rating the build changes, for an instance admin's rulings), reading the
#      box's reports.tar, unpacked (again on every run) under
#      DATA_ROOT/rebuild/cloud-reports/<build>; with none, those queues say the build had none
# The swap says how many changed roads have no ruling yet; it does not wait for them.
# Run it again after a failure and it carries on: a build directory left by an unpack
# that stopped is unpacked again, and once step 4 has finished it goes straight to step 5.
#
# The second stage, --swap: `import_cloud_build --confirm` (the rebuild's own swap;
# `rollback_rebuild` undoes it), then restarts the routers and draws the stress tiles
# again, as after any rebuild. Then run the post-swap closure probes (OPERATIONS.md,
# "Bicycle closures in the tiles", step 3). Options after `--` go to import_cloud_build,
# e.g. `--swap RUN_URL -- --accept-later-overrides`.
#
# On the beta server (--beta), for a run the box made with --beta-bundle: the beta's own
# "New data only" update (docs/BETA-RUNBOOK.md), with S3 in place of ship-data.sh's rsync.
#   Without --swap: downloads RUN_URL/beta/ to --incoming and runs receive-data.sh verify.
#   With --swap: refuses unless what is in --incoming was downloaded from this run, and,
#   where continuous deployment is installed, unless it is paused with no pass running and
#   no deploy left half done. Then receive-data.sh verify and `files` (sudo; each graph's
#   old build stays as `previous`), stops the api and worker, `db --update-data` (sudo;
#   after its own safety dump, in one transaction; resets override and junction_override to
#   home's and empties the beta's stress_edit history, as every data update does), starts
#   them again (also when the update fails), restarts the four routers (and starts the trail
#   routers whose tiles are there, then writes the settings rows: sync_upstreams), starts the
#   stress-tile pre-draw in the background, and runs the local smoke test, retried while the
#   app and routers start. Then run smoke-test.sh --public yourself. Rollback is the
#   runbook's (rollback A for the tiles, the pre-update dump for the database).
#
# Options:
#   --beta                  the beta server's mode (above)
#   --incoming DIR          --beta: where the bundle is downloaded [$RM_INCOMING]
#   --state DIR             --beta: the runbook's state directory [$RM_STATE, or
#                           ~/routemaker-beta-state]
#   --live-dir DIR          the live stack's checkout: compose.yaml and .env [this repository]
#   --stage DIR             where the result is downloaded [~/cloud-runs/<run>/out]
#   --profile NAME          the AWS CLI profile (`aws login --remote --profile NAME` first)
#   --swap                  the second stage above, after an install and its dry run
#   --no-safety-dump        skip step 3 (rollback_rebuild still works without it)
#   --remove-tars           delete the downloaded graph tars once they are unpacked
#   --allow-sha-mismatch    install a build made from another commit than this checkout's
#                           (with --beta, passed to receive-data.sh)
#   -h, --help
# Environment (for tests): CLOUD_AWS [aws], CLOUD_DOCKER [docker], CLOUD_SUDO [sudo],
# CLOUD_GIT [git], CLOUD_RECEIVE, CLOUD_BETA_COMPOSE, CLOUD_SMOKE [the scripts/beta/ ones],
# CLOUD_SMOKE_TRIES [20], CLOUD_SMOKE_WAIT_S [15].
set -Eeuo pipefail

die() { echo "import-result: $*" >&2; exit 2; }
note() { echo "import-result: $*"; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
live_dir=$(cd "$here/../.." && pwd)
stage="" profile="" swap=0 safety=1 allow_mismatch=0 remove_tars=0 url="" extra=()
beta=0 incoming=${RM_INCOMING:-} beta_state=${RM_STATE:-$HOME/routemaker-beta-state}
while [ $# -gt 0 ]; do
	case "$1" in
		--live-dir) [ $# -ge 2 ] || die "$1 needs a value"; live_dir=$2; shift 2 ;;
		--stage) [ $# -ge 2 ] || die "$1 needs a value"; stage=$2; shift 2 ;;
		--profile) [ $# -ge 2 ] || die "$1 needs a value"; profile=$2; shift 2 ;;
		--swap) swap=1; shift ;;
		--no-safety-dump) safety=0; shift ;;
		--allow-sha-mismatch) allow_mismatch=1; shift ;;
		--remove-tars) remove_tars=1; shift ;;
		--beta) beta=1; shift ;;
		--incoming) [ $# -ge 2 ] || die "$1 needs a value"; incoming=$2; shift 2 ;;
		--state) [ $# -ge 2 ] || die "$1 needs a value"; beta_state=$2; shift 2 ;;
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

if [ "$beta" = 1 ]; then
	[ -n "$incoming" ] || die "--beta needs --incoming DIR (the runbook's \$RM_INCOMING)"
	incoming=$(realpath -m "$incoming")
	case "$incoming/" in
		"$(realpath -m "$data_root")"/* | "$(realpath -m "$live_dir")"/*)
			die "--incoming $incoming is inside DATA_ROOT or the checkout; put it elsewhere" ;;
	esac
	receive=${CLOUD_RECEIVE:-$live_dir/scripts/beta/receive-data.sh}
	bcompose=${CLOUD_BETA_COMPOSE:-$live_dir/scripts/beta/beta-compose.sh}
	smoke=${CLOUD_SMOKE:-$live_dir/scripts/beta/smoke-test.sh}
	sha_opt=()
	[ "$allow_mismatch" = 0 ] || sha_opt=(--allow-sha-mismatch)
	receive_() { "$receive" --bundle "$incoming" --env-file "$env_file" ${sha_opt[@]+"${sha_opt[@]}"} "$@"; }
	# DATA_ROOT's directories belong to the containers' uid, so `files` and `db` run as root.
	sudo_receive() { $SUDO "$receive" --bundle "$incoming" --env-file "$env_file" ${sha_opt[@]+"${sha_opt[@]}"} "$@"; }
	routers=(valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend)

	if [ "$swap" = 0 ]; then
		# Checked first, so a run with no beta bundle leaves whatever is in --incoming alone.
		aws_ s3 ls "$url/beta/MANIFEST.txt" >/dev/null 2>&1 ||
			die "$url/beta/ has no finished bundle: the box ran without --beta-bundle, its bundle failed, or its upload did not finish"
		mkdir -p "$incoming"
		note "downloading $url/beta/ to $incoming"
		# The old manifest and checksums first, so a download that stops is one verify refuses.
		rm -f "$incoming/SHA256SUMS" "$incoming/MANIFEST.txt" "$incoming/.cloud-run"
		aws_ s3 sync "$url/beta/" "$incoming/" --only-show-errors
		[ -s "$incoming/MANIFEST.txt" ] && [ -s "$incoming/SHA256SUMS" ] ||
			die "$url/beta/ has no finished bundle: the box ran without --beta-bundle, or its upload did not finish"
		receive_ verify
		echo "$url" >"$incoming/.cloud-run"
		note "downloaded and verified. To install it: scripts/cloud/import-result.sh --beta --swap $url"
		exit 0
	fi

	if [ -d "$beta_state/cd/bin" ]; then
		[ -f "$beta_state/cd/PAUSED" ] ||
			die "continuous deployment is not paused; first: \"$beta_state/cd/bin/auto-release.sh\" pause --wait \"cloud data\""
		if [ -e "$beta_state/cd/lock" ] && ! (exec 8>>"$beta_state/cd/lock" && flock -n 8); then
			die "a deployment pass is still running; wait for it: \"$beta_state/cd/bin/auto-release.sh\" pause --wait \"cloud data\""
		fi
		[ ! -e "$beta_state/cd/in-progress" ] ||
			die "a stopped deploy is half done ($beta_state/cd/in-progress); see BETA-RUNBOOK, \"Shipping an update later\", before installing data"
	fi
	[ -s "$incoming/MANIFEST.txt" ] && [ "$(cat "$incoming/.cloud-run" 2>/dev/null)" = "$url" ] ||
		die "$incoming does not hold this run's bundle: run this without --swap first"
	receive_ verify
	note "installing the graphs (each one's old build stays as \`previous\`)"
	sudo_receive files
	note "stopping the api and worker for the database update"
	"$bcompose" stop api worker
	if ! sudo_receive db --update-data; then
		"$bcompose" up -d api worker
		die "db --update-data failed; it runs in one transaction, so the database is as it was. The api and worker are started again; the new graphs are installed (rollback A puts the old ones back)"
	fi
	"$bcompose" up -d api worker
	note "restarting the routers so they serve the new graphs"
	"$bcompose" restart "${routers[@]}"
	# The trail routers (Mountain Bike's, Gravel and Mountain Goat's): started, or recreated onto the
	# new build, whenever their tiles are here. A restart alone never starts one that is not running,
	# and without them the api plans those rides on the standard graph (`mtb.limited` no_mtb_graph).
	trail=()
	for variant in offroad mtb; do
		[ -L "$data_root/tiles/$variant/current" ] && trail+=("valhalla-$variant")
	done
	if [ "${#trail[@]}" -gt 0 ]; then
		note "starting the trail routers on the new graphs: ${trail[*]}"
		"$bcompose" up -d --force-recreate "${trail[@]}" ||
			note "WARNING: a trail router did not start; Mountain Bike, Gravel and Mountain Goat stay on the standard graph until: $bcompose up -d --force-recreate ${trail[*]}"
	fi
	# The settings rows the api serves each variant by, written from the links `files` moved
	# (receive-data.sh runs it too, when the api is up; run again here, it changes nothing).
	"$bcompose" exec -T api ./manage.py sync_upstreams </dev/null ||
		note "WARNING: sync_upstreams failed; run it once the api is up: $bcompose exec -T api ./manage.py sync_upstreams"
	note "drawing the stress tiles again, in the background: $beta_state/predraw.log"
	mkdir -p "$beta_state"
	# shellcheck disable=SC2016 # $1 and $? are the inner shell's
	( umask 077; setsid nohup sh -c '"$1" exec -T worker ./manage.py predraw_stress_tiles; echo "predraw exit $?"' \
		sh "$bcompose" </dev/null >"$beta_state/predraw.log" 2>&1 & )
	# The api and the routers take a while to come up; the smoke test only reads.
	tries=${CLOUD_SMOKE_TRIES:-20} smoke_rc=0
	until "$smoke" --local; do
		tries=$((tries - 1))
		if [ "$tries" -le 0 ]; then
			note "WARNING: the local smoke test still fails. The data is installed; look at it before the testers do"
			smoke_rc=1
			break
		fi
		note "the smoke test failed; the app may still be starting, so trying again"
		sleep "${CLOUD_SMOKE_WAIT_S:-15}"
	done
	note "installed. Wait for \"predraw exit 0\" in $beta_state/predraw.log, run $smoke --public,"
	note "then resume continuous deployment if it was paused: \"$beta_state/cd/bin/auto-release.sh\" resume"
	exit "$smoke_rc"
fi

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
	[ "$(cat "$stage/installed" 2>/dev/null)" = "$build" ] ||
		die "the install of $build did not finish: run this without --swap first"
	note "swapping in build $build"
	import_cmd --confirm ${extra[@]+"${extra[@]}"}
	note "restarting the routers so they serve the new graphs"
	compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend
	for router in valhalla-offroad valhalla-mtb; do
		if [ -n "$(compose --profile offroad ps -q "$router" 2>/dev/null)" ]; then
			compose --profile offroad restart "$router"
		fi
	done
	note "drawing the stress tiles again"
	compose exec -T api python manage.py predraw_stress_tiles </dev/null
	note "done. Now the post-swap closure probes (OPERATIONS.md, \"Bicycle closures in the tiles\", step 3)."
	note "to undo: docker compose exec -T rebuild ./manage.py rollback_rebuild, then the same with --confirm, then restart the routers"
	exit 0
fi

# --- 1. download -------------------------------------------------------------------------
note "downloading $url/out/ to $stage"
rm -f "$stage/SHA256SUMS"
# sync, so a second run downloads only what changed; once a build is installed its graph
# tars are not needed again (and --remove-tars may have deleted them).
skip=()
if [ -s "$stage/installed" ] && [ "$(cat "$stage/installed")" = "$(manifest build 2>/dev/null)" ]; then
	skip=(--exclude 'tiles-*.tar')
fi
aws_ s3 sync "$url/out/" "$stage/" ${skip[@]+"${skip[@]}"} --only-show-errors
[ -s "$stage/SHA256SUMS" ] || die "$url/out/ has no SHA256SUMS: the box did not finish its upload"
if [ ${#skip[@]} -gt 0 ]; then
	(cd "$stage" && sha256sum --quiet --ignore-missing -c SHA256SUMS)
else
	(cd "$stage" && sha256sum --quiet -c SHA256SUMS)
fi || die "a file in $stage does not match SHA256SUMS; download it again"
read_manifest
note "build $build, made from commit $commit with the database as of $read_at"

# --- 2. pre-flight -----------------------------------------------------------------------
# safe.directory: run as root (or another user) on the owner's checkout, git otherwise
# refuses it as "dubious ownership" and this reads as "not a git checkout".
here_commit=$("$GIT" -c safe.directory="$live_dir" -C "$live_dir" rev-parse HEAD) ||
	die "$live_dir is not a git checkout"
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
	for variant in standard no-trail ebike weekend offroad mtb; do
		[ -f "$stage/tiles-$variant.tar" ] || die "the result has no tiles-$variant.tar"
		for link in current previous; do
			[ "$($SUDO readlink "$data_root/tiles/$variant/$link" 2>/dev/null)" != "$build" ] ||
				die "$variant's $link link already names $build; it was swapped in before"
		done
		need=$((need + $(stat -c %s "$stage/tiles-$variant.tar")))
		# A directory left by an unpack that stopped is removed before unpacking again.
		if [ -d "$data_root/tiles/$variant/$build" ]; then
			need=$((need - $($SUDO du -sb "$data_root/tiles/$variant/$build" | cut -f1)))
		fi
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
	# sessions, client addresses and riders' Garmin and Wahoo tokens do not belong in a file that
	# sits in a home folder.
	(umask 077 && compose exec -T postgis pg_dump -U "$pguser" -d "$pgdb" -Fc \
		--exclude-table-data='*.cached_membership' --exclude-table-data='*.app_session' \
		--exclude-table-data='*.django_session' --exclude-table-data='*.rate_limit_window' \
		--exclude-table-data='*.stress_tile_cache' --exclude-table-data='*.bikeshare_feed_cache' \
		--exclude-table-data='*.signed_out_send' --exclude-table-data='*.garmin_link' \
		--exclude-table-data='*.wahoo_link' \
		</dev/null >"$dump")
fi

# --- 4. install --------------------------------------------------------------------------
if [ "$installed" = 0 ]; then
	note "unpacking the graphs under $data_root/tiles"
	for variant in standard no-trail ebike weekend offroad mtb; do
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
# The box's reports, for Review's queues: unpacked again on every run (a re-run after a stopped
# one, or a newer download), and none at all where this build sent none, so a queue read from
# a report says "No report from this build" rather than showing another build's.
$SUDO rm -rf "${data_root:?}/rebuild/cloud-reports/$build"
if [ -f "$stage/reports.tar" ]; then
	$SUDO mkdir -p "$data_root/rebuild/cloud-reports/$build"
	$SUDO tar -C "$data_root/rebuild/cloud-reports/$build" --numeric-owner -xf "$stage/reports.tar"
fi
review=()
if [ -d "$data_root/rebuild/cloud-reports/$build/reports" ]; then
	review=(--review-reports-dir "cloud-reports/$build/reports")
fi
import_cmd ${review[@]+"${review[@]}"} ${extra[@]+"${extra[@]}"}
note "installed. Nothing served has changed. To swap it in: scripts/cloud/import-result.sh --swap $url"
