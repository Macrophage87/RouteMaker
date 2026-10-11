#!/usr/bin/env bash
# Runs one rebuild on the cloud box and sends the result back to S3. Run ON THE BOX, as
# the ubuntu user, from any checkout of this repository. Pairs with
# scripts/cloud/send-inputs.sh (before) and scripts/cloud/import-result.sh (after);
# docs/OPERATIONS.md, "Rebuilding on the cloud box".
#
#   scripts/cloud/box-rebuild.sh [options] RUN_URL
#
#   RUN_URL   the same s3://<bucket>/rebuild-checkpoints/transfer/<run> send-inputs.sh used
#
# Steps, each recorded in ~/cloud-runs/<run>/state/ once done, so running the same command
# again (after a spot reclaim stopped the box, or after fixing a failure) carries on where
# it stopped instead of starting over:
#
#   fetch     RUN_URL/in/ to ~/cloud-runs/<run>/in, every file checked against SHA256SUMS
#   checkout  the commit in MANIFEST.txt, in --build-dir (a clone kept apart from the
#             checkout this script runs from, so it never rewrites itself while running)
#   env       the box's own .env, fresh random secrets, never sent anywhere; plus
#             compose.override.yaml giving the rebuild the box's memory
#   data      prepare_data_root.sh, then reference/, elevation/ and extracts/ unpacked
#   images    docker compose build api rebuild
#   restore   the backup into an EMPTY database (OPERATIONS.md, "Restoring one"), then every
#             job the home stack had queued or running is cancelled in this copy
#   fire      migrate and the rebuild worker started, run_rebuild_now --fresh
#   wait      until that job succeeds; a failed job stops here (and the box, see below).
#             A job left `doing` by a worker that died (a spot reclaim, an OOM kill) is
#             put back with unwedge_job, which changes nothing while the worker is alive
#   export    the new segment schema renamed to `staging` and dumped, each graph's build
#             directory tarred, the rebuild's reports tarred (reports.tar, kept for
#             reading; the import does not use it), MANIFEST.txt and SHA256SUMS
#   upload    to RUN_URL/out/, SHA256SUMS last
#
# Then the box powers itself off (with the launch template's "Shutdown behavior: Stop" that
# is a stop, which costs only the disk). It powers off after a failed rebuild too, with the
# rebuild's log saved under ~/cloud-runs/<run>/, and after --deadline-hours with the job
# still unfinished; --no-stop keeps it running. To try a failed rebuild again, run the
# same command with --refire: it fires a new job and carries on from there.
#
# Run it so that it outlives the Session Manager window, e.g.
#   nohup scripts/cloud/box-rebuild.sh RUN_URL >>~/cloud-rebuild.log 2>&1 &
# and follow it with `tail -f ~/cloud-rebuild.log`.
#
# EVERYTHING here is the box's own: it replaces the box's database and DATA_ROOT
# subdirectories. Never run it on a host that serves anything.
#
# Options:
#   --build-dir DIR        the clone the stack runs from [~/rm-build]
#   --repo-url URL         cloned into --build-dir when it is missing
#                          [https://github.com/Macrophage87/RouteMaker.git]
#   --data-root DIR        the box's DATA_ROOT [/srv/routemaker/data]
#   --rebuild-memory SIZE  the rebuild container's memory cap [26G]
#   --tile-threads N       REBUILD_TILE_CONCURRENCY [4]
#   --deadline-hours N     give up on the job after N hours of waiting [24]
#   --refire               fire a new rebuild job even though one was fired already
#   --no-stop              leave the box running at the end
#   -h, --help
# Environment (for tests): CLOUD_AWS [aws], CLOUD_DOCKER [docker], CLOUD_SUDO [sudo],
# CLOUD_GIT [git], CLOUD_POLL_S [60], CLOUD_POWEROFF [sudo poweroff], CLOUD_RUNS [~/cloud-runs],
# CLOUD_DEADLINE_S [--deadline-hours in seconds].
set -Eeuo pipefail

die() { echo "box-rebuild: $*" >&2; exit 2; }
note() { echo "box-rebuild: $(date -u +%H:%M:%SZ) $*"; }

build_dir="$HOME/rm-build"
repo_url=https://github.com/Macrophage87/RouteMaker.git
data_root=/srv/routemaker/data
rebuild_memory=26G tile_threads=4 stop=1 url="" deadline_hours=24 refire=0
while [ $# -gt 0 ]; do
	case "$1" in
		--build-dir) [ $# -ge 2 ] || die "$1 needs a value"; build_dir=$2; shift 2 ;;
		--repo-url) [ $# -ge 2 ] || die "$1 needs a value"; repo_url=$2; shift 2 ;;
		--data-root) [ $# -ge 2 ] || die "$1 needs a value"; data_root=$2; shift 2 ;;
		--rebuild-memory) [ $# -ge 2 ] || die "$1 needs a value"; rebuild_memory=$2; shift 2 ;;
		--tile-threads) [ $# -ge 2 ] || die "$1 needs a value"; tile_threads=$2; shift 2 ;;
		--deadline-hours) [ $# -ge 2 ] || die "$1 needs a value"; deadline_hours=$2; shift 2 ;;
		--refire) refire=1; shift ;;
		--no-stop) stop=0; shift ;;
		-h | --help) sed -n '2,/^set -E/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
		-*) die "unknown option $1" ;;
		*) [ -z "$url" ] || die "one RUN_URL only"; url=$1; shift ;;
	esac
done
[ -n "$url" ] || die "usage: box-rebuild.sh [options] s3://<bucket>/rebuild-checkpoints/transfer/<run>"
url=${url%/}
case "$url" in s3://?*/?*) ;; *) die "RUN_URL must be s3://<bucket>/.../<run>, not $url" ;; esac
run=${url##*/}
[[ "$run" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || die "the run name '$run' must be lowercase letters, digits and hyphens"
case "$data_root" in /?*/?*) ;; *) die "--data-root must be an absolute path at least two levels deep, not $data_root" ;; esac
[[ "$data_root" =~ ^[A-Za-z0-9._/-]+$ ]] || die "--data-root has a character .env should not carry"
[[ "$rebuild_memory" =~ ^[0-9]+[MG]$ ]] || die "--rebuild-memory must look like 26G"
[[ "$tile_threads" =~ ^[1-9][0-9]?$ ]] || die "--tile-threads must be a whole number of at least 1"
[[ "$deadline_hours" =~ ^[1-9][0-9]?$ ]] || die "--deadline-hours must be a whole number from 1 to 99"

AWS=${CLOUD_AWS:-aws}
DOCKER=${CLOUD_DOCKER:-docker}
SUDO=${CLOUD_SUDO-sudo}
GIT=${CLOUD_GIT:-git}
POLL_S=${CLOUD_POLL_S:-60}
POWEROFF=${CLOUD_POWEROFF:-sudo poweroff}
work="${CLOUD_RUNS:-$HOME/cloud-runs}/$run"
state="$work/state"
mkdir -p "$work/in" "$work/out" "$state"
if [ "$refire" = 1 ]; then
	rm -f "$state/fire.done" "$state/job" "$state/wait.done" "$state/export.done" "$state/upload.done"
fi
# The AWS CLI wants a region; on the box it is the box's own, from the instance metadata.
if [ -z "${AWS_DEFAULT_REGION:-}${AWS_REGION:-}" ]; then
	token=$(curl -sf -m 5 -X PUT http://169.254.169.254/latest/api/token \
		-H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null) &&
		AWS_DEFAULT_REGION=$(curl -sf -m 5 -H "X-aws-ec2-metadata-token: $token" \
			http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null) &&
		export AWS_DEFAULT_REGION || true
fi

# Once the rebuild is fired nobody is watching, so from then on the box powers off when
# this script ends, however it ends (unless --no-stop). Before that a failure is a typo
# or a missing file, and the box stays up for you to fix it.
unattended=0
powered_off=0
power_off() {
	[ "$stop" = 1 ] && [ "$powered_off" = 0 ] || return 0
	powered_off=1
	note "powering off; start the box again to look, or rerun this command to carry on"
	$POWEROFF || true
}
# shellcheck disable=SC2329 # invoked by the trap below
on_exit() {
	local rc=$?
	if [ "$rc" != 0 ] && [ "$unattended" = 1 ]; then power_off; fi
}
trap on_exit EXIT
finish() {
	power_off
	exit "$1"
}

done_already() { [ -e "$state/$1.done" ]; }
mark() { date -u +%Y%m%dT%H%M%SZ >"$state/$1.done"; }
compose() { (cd "$build_dir" && "$DOCKER" compose "$@"); }
env_value() { sed -n "s/^$1=//p" "$build_dir/.env" | tail -n1; }
psql_() { compose exec -T postgis psql -U "$pguser" -d "$pgdb" -AtX -v ON_ERROR_STOP=1 -c "$1" </dev/null; }
manifest() { sed -n "s/^$1=//p" "$work/in/MANIFEST.txt" | tail -n1; }

# --- fetch -------------------------------------------------------------------------------
if ! done_already fetch; then
	note "fetching $url/in/"
	rm -f "$work/in/SHA256SUMS"
	"$AWS" s3 cp "$url/in/" "$work/in/" --recursive --only-show-errors
	[ -s "$work/in/SHA256SUMS" ] || die "$url/in/ has no SHA256SUMS: send-inputs.sh did not finish. Run it again at home"
	(cd "$work/in" && sha256sum --quiet -c SHA256SUMS) || die "a file in $work/in does not match SHA256SUMS; send it again"
	mark fetch
fi
commit=$(manifest commit)
read_at=$(manifest read_at)
backup=$(manifest backup)
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || die "MANIFEST.txt names no commit"
[[ "$read_at" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "MANIFEST.txt names no read_at"
[ -f "$work/in/$backup" ] || die "MANIFEST.txt names $backup, which is not in $work/in"

# --- checkout ----------------------------------------------------------------------------
if ! done_already checkout; then
	if [ ! -d "$build_dir/.git" ]; then
		note "cloning into $build_dir"
		"$GIT" clone --quiet "$repo_url" "$build_dir"
	fi
	[ -z "$("$GIT" -C "$build_dir" status --porcelain --untracked-files=no)" ] ||
		die "$build_dir has local changes; it is the box's build clone and should have none"
	"$GIT" -C "$build_dir" fetch --quiet --tags origin
	"$GIT" -C "$build_dir" checkout --quiet --detach "$commit"
	mark checkout
fi
note "building commit $commit in $build_dir"

# --- env ---------------------------------------------------------------------------------
set_env() {
	local key=$1 value=$2
	if grep -q "^$key=" "$build_dir/.env"; then
		sed -i "s|^$key=.*|$key=$value|" "$build_dir/.env"
	else
		printf '%s=%s\n' "$key" "$value" >>"$build_dir/.env"
	fi
}
if [ ! -f "$build_dir/.env" ]; then
	# Fresh secrets that never leave the box: it serves nobody, signs nobody in and
	# sends nothing, so nothing from home's .env is needed here.
	(umask 077 && cp "$build_dir/.env.example" "$build_dir/.env")
	for key in DJANGO_SECRET_KEY PGPASSWORD KEY_ENCRYPTION_KEY BOT_INTERNAL_SECRET; do
		set_env "$key" "$(openssl rand -hex 32)"
	done
fi
set_env TAG cloud
set_env DATA_ROOT "$data_root"
set_env COMPOSE_PROJECT_NAME routemaker
# A Tuesday tick on a box left running records a pause instead of building;
# run_rebuild_now ignores it.
set_env WEEKLY_REBUILD_PAUSED 1
set_env REBUILD_TILE_CONCURRENCY "$tile_threads"
cat >"$build_dir/compose.override.yaml" <<EOF
# Written by scripts/cloud/box-rebuild.sh on the cloud box only; never committed.
services:
  rebuild:
    deploy:
      resources:
        limits: { memory: $rebuild_memory }
EOF
pguser=$(env_value PGUSER); pguser=${pguser:-routemaker}
pgdb=$(env_value PGDATABASE); pgdb=${pgdb:-routemaker}

# --- data --------------------------------------------------------------------------------
if ! done_already data; then
	note "preparing $data_root and unpacking the inputs"
	(cd "$build_dir" && $SUDO sh scripts/prepare_data_root.sh --env-file ./.env)
	for part in reference elevation extracts; do
		$SUDO rm -rf "${data_root:?}/$part"
		$SUDO tar -C "$data_root" --numeric-owner -xf "$work/in/$part.tar"
	done
	mark data
fi

# --- images ------------------------------------------------------------------------------
if ! done_already images; then
	note "building the api and pipeline images (the first time takes a while)"
	compose build api rebuild
	mark images
fi

# --- restore -----------------------------------------------------------------------------
if ! done_already restore; then
	note "restoring $backup into an empty database"
	compose down
	$SUDO rm -rf "${data_root:?}/postgres"
	(cd "$build_dir" && $SUDO sh scripts/prepare_data_root.sh --env-file ./.env)
	compose up -d --wait postgis
	compose exec -T postgis dropdb -U "$pguser" "$pgdb" </dev/null
	compose exec -T postgis createdb -U "$pguser" -T template0 "$pgdb" </dev/null
	compose exec -T postgis pg_restore --no-owner -U "$pguser" -d "$pgdb" <"$work/in/$backup" ||
		die "pg_restore did not exit 0; the database is not a clean copy. Rerun this command to restore again"
	# The home stack's queue came with the copy. Nothing here should run it: a queued
	# Tuesday rebuild would start the moment the rebuild worker does, and a job home was
	# running would make run_rebuild_now refuse.
	psql_ "UPDATE procrastinate_jobs SET status = 'cancelled' WHERE status IN ('todo', 'doing')" >/dev/null
	mark restore
fi

# --- fire --------------------------------------------------------------------------------
resumed=0
if ! done_already fire; then
	note "starting migrate and the rebuild worker, and firing the rebuild"
	compose up -d rebuild
	out=$(compose exec -T rebuild ./manage.py run_rebuild_now --fresh </dev/null)
	echo "$out"
	job=$(sed -n 's/.*as job \([0-9][0-9]*\) .*/\1/p' <<<"$out" | head -n1)
	[ -n "$job" ] || die "run_rebuild_now named no job"
	echo "$job" >"$state/job"
	mark fire
else
	resumed=1
	compose up -d rebuild
fi
unattended=1
job=$(cat "$state/job")

# --- wait --------------------------------------------------------------------------------
save_log() { compose logs --no-color rebuild 2>&1 | gzip >"$work/rebuild-$(date -u +%Y%m%dT%H%M%SZ).log.gz" || true; }
if ! done_already wait; then
	note "waiting for rebuild job $job (hours; this checks every ${POLL_S}s)"
	# On a resume the first `doing` is tried at once; after that every ten minutes, in
	# case the rebuild container was killed and restarted while this script ran on.
	if [ "$resumed" = 1 ]; then last_unwedge=0; else last_unwedge=$(date +%s); fi
	deadline=$(($(date +%s) + ${CLOUD_DEADLINE_S:-$((deadline_hours * 3600))}))
	last_report=0
	while :; do
		# A database still starting after a reboot is not an answer; ask again.
		status=$(psql_ "SELECT status FROM procrastinate_jobs WHERE id = $job" 2>/dev/null) ||
			status=unreachable
		case "$status" in
			unreachable) ;;
			succeeded) break ;;
			todo) ;;
			doing)
				# Back from a spot reclaim: the worker that held the job died with the box,
				# so the row says `doing` with nothing behind it. unwedge_job puts it back
				# to `todo` and the rebuild resumes from its checkpoints; it refuses, and
				# changes nothing, when the worker is alive.
				if [ $(($(date +%s) - last_unwedge)) -ge 600 ]; then
					[ "$last_unwedge" != 0 ] || sleep "$POLL_S"
					last_unwedge=$(date +%s)
					if compose exec -T rebuild ./manage.py unwedge_job "$job" </dev/null >/dev/null 2>&1; then
						note "job $job had lost its worker; it is queued again and resumes from its checkpoints"
					fi
				fi ;;
			*)
				note "rebuild job $job ended $status; its log is saved under $work"
				save_log
				finish 1 ;;
		esac
		now=$(date +%s)
		if [ "$now" -ge "$deadline" ]; then
			note "rebuild job $job is still $status after $deadline_hours hours; giving up. Its log is saved under $work"
			save_log
			finish 1
		fi
		if [ $((now - last_report)) -ge 600 ]; then
			note "job $job is $status: $(compose logs --no-color --tail=1 rebuild 2>/dev/null | tail -n1)"
			last_report=$now
		fi
		sleep "$POLL_S"
	done
	save_log
	mark wait
fi

# --- export ------------------------------------------------------------------------------
if ! done_already export; then
	builds=$(psql_ "SELECT count(DISTINCT build_id) || ' ' || max(build_id) FROM valhalla_upstream")
	[ "${builds%% *}" = 1 ] || die "the settings rows name more than one build ($builds); the swap did not finish"
	build=${builds#* }
	[[ "$build" =~ ^[0-9]{8}T[0-9]{6}Z(-[0-9]+)?$ ]] || die "the settings rows name no build id: '$build'"
	note "exporting build $build"
	rm -rf "${work:?}/out" && mkdir -p "$work/out"
	# The box's copy is disposable: its new table is renamed to the name the home swap
	# promotes from. Skipped when a stopped export already renamed it.
	if [ "$(psql_ "SELECT to_regnamespace('live') IS NOT NULL")" = t ]; then
		[ "$(psql_ "SELECT to_regnamespace('staging') IS NULL")" = t ] ||
			die "both live and staging exist; the swap did not finish"
		psql_ "ALTER SCHEMA live RENAME TO staging" >/dev/null
	fi
	compose exec -T postgis pg_dump -U "$pguser" -d "$pgdb" -Fc -n staging </dev/null >"$work/out/staging.dump"
	for variant in standard no-trail ebike weekend offroad; do
		[ -f "$data_root/tiles/$variant/$build/tiles.tar" ] || die "$variant has no build $build"
		$SUDO tar -C "$data_root/tiles" --numeric-owner -cf "$work/out/tiles-$variant.tar" "$variant/$build"
	done
	if [ -d "$data_root/rebuild/reports" ]; then
		$SUDO tar -C "$data_root/rebuild" --numeric-owner -cf "$work/out/reports.tar" reports
	fi
	$SUDO chown "$(id -u):$(id -g)" "$work/out"/*.tar 2>/dev/null || true
	{
		echo "run=$run"
		echo "commit=$commit"
		echo "build=$build"
		echo "backup=$backup"
		echo "read_at=$read_at"
		echo "finished=$(date -u +%Y%m%dT%H%M%SZ)"
	} >"$work/out/MANIFEST.txt"
	(cd "$work/out" && find . -maxdepth 1 -type f -printf '%P\n' | sort |
		xargs sha256sum -- >"$work/SHA256SUMS.out" && mv "$work/SHA256SUMS.out" SHA256SUMS)
	mark export
fi

# --- upload ------------------------------------------------------------------------------
if ! done_already upload; then
	note "uploading to $url/out/ ($(du -sh "$work/out" | cut -f1))"
	"$AWS" s3 rm "$url/out/SHA256SUMS" >/dev/null 2>&1 || true
	"$AWS" s3 cp "$work/out/" "$url/out/" --recursive --exclude SHA256SUMS --only-show-errors
	"$AWS" s3 cp "$work/out/SHA256SUMS" "$url/out/SHA256SUMS" --only-show-errors
	mark upload
fi
note "done: build $(sed -n 's/^build=//p' "$work/out/MANIFEST.txt") is at $url/out/"
note "next, at home: scripts/cloud/import-result.sh $url"
finish 0
