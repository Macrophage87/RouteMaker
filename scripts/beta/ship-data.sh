#!/usr/bin/env bash
# Packages what the beta server needs from the LOCAL live stack and sends it there.
# Run at home. Pairs with scripts/beta/receive-data.sh on the server.
#
#   scripts/beta/ship-data.sh [options] HOST REMOTE_DIR
#
#   HOST        user@host (anything `ssh` and `rsync -e ssh` accept)
#   REMOTE_DIR  an absolute directory ON THE SERVER for the bundle, such as
#               /data/routemaker-incoming. It is created if missing; it is not DATA_ROOT.
#
# What goes in the bundle (it mirrors DATA_ROOT, so receive-data.sh is a straight copy):
#   tiles/<variant>/<build>/{tiles.tar,admin.sqlite,tz_world.sqlite,build-config.json}
#                       the promoted build (`current`) of each router graph, found by
#                       reading the `current` symlink; standard, no-trail, ebike, weekend
#                       (and offroad once it exists). The unpacked tiles/ directory is left
#                       out: Valhalla serves from tiles.tar (tile_extract), verified.
#   elevation/          the .hgt files the routers read at runtime for elevation profiles
#   basemap/            region.pmtiles, fonts, sprites
#   photon/             the Photon index (photon_data/)
#   frontend/           the built front end, made with VITE_BETA=1 so it carries the beta banner
#   db/routemaker.dump  pg_dump --format=custom of the `live` and `public` schemas, minus the
#                       data of sessions, rate-limit rows, membership cache, job queues and
#                       every table holding an identity (accounts, audit log, guild roster)
#   db/row-counts.tsv   what receive-data.sh checks the restore against
#   SHA256SUMS          one line per file; MANIFEST.txt the bundle's facts
#
# What is never in it: .env or any secret (the script checks), the other test databases,
# the `live_old` schema, the tiger geocoder schema, sessions.
#
# READ-ONLY on the live stack: it reads files under DATA_ROOT and runs pg_dump, psql SELECTs
# and pg_restore --list through `docker compose exec`. It writes only into --stage (default
# ~/beta-bundle), which it refuses to place inside DATA_ROOT or the live checkout. The stage
# holds symlinks to the big live files, not copies, so staging costs almost no disk.
#
# Resumable: rsync keeps partial files (--partial-dir), so rerunning the same command after a
# dropped connection picks up where it stopped. The remote's old SHA256SUMS and MANIFEST.txt are
# removed before anything is sent and the new ones are sent last, so a bundle that did not
# finish has no manifest and receive-data.sh refuses it. rsync does not delete on the remote:
# files left there by an earlier bundle stay, and receive-data.sh installs only what the new
# SHA256SUMS lists (and only the tile builds MANIFEST.txt names).
#
# Options:
#   --live-dir DIR       the live stack's checkout: compose.yaml and .env [this repository]
#   --stage DIR          where the bundle is assembled [~/beta-bundle, or $BETA_STAGE]
#   --build-frontend     build the front end in the pinned node image, offline, with VITE_BETA=1
#   --dist DIR           use an already-built front end instead (must contain index.html)
#   --node-modules DIR   node_modules for --build-frontend [<repo>/frontend/node_modules]
#   --without PART       leave a part out: tiles, elevation, basemap, photon, frontend, db
#                        (repeatable; for an update that changes only some of them)
#   --with-tile-dirs     also send each build's unpacked tiles/ directory (about 0.5 GB each)
#   --no-transfer        build and verify the stage, send nothing
#   --dry-run            do everything but have rsync only report what it would send
#   --bwlimit KBPS       rsync bandwidth limit
#   -h, --help
# Environment: BETA_SSH_OPTS extra ssh options; BETA_RSYNC_RETRIES (default 5).
set -euo pipefail

die() { echo "ship-data: $*" >&2; exit 2; }
note() { echo "ship-data: $*" >&2; }

NODE_IMAGE="docker.io/library/node@sha256:363e1587494626837fa7f9a23bdb453d13b0ff3c67c705c2805cfc69c2d2fad7"
# Data the app does not need on a fresh server, or must not carry: sessions and the
# rate-limit table (client address digests) and the membership cache are the app's own nightly
# backup exclusions (config.procrastinate.BACKUP_EXCLUDED_TABLES, less stress_tile_cache, which
# is worth shipping: without it every first map view draws its tiles live), plus the job queue,
# Django's own sessions, the admin log and run history, which belong to the home install.
#
# And no identities (OWNER-DECISIONS 367.3, "strip users"): the beta starts with no accounts and
# the owner claims instance admin there afresh. Every table that holds a person, or a row that
# points at one, is excluded as a whole, so the restore's foreign keys (added in post-data) have
# nothing to point at that is missing:
#   app_user                          the accounts (the owner's Discord id)
#   audit_log                         actor_id -> app_user, plus the plain actor_user_id
#   bootstrap_claim                   user_id -> app_user, plus a plaintext discord_user_id
#   pending_instance_admin_removal    user_id and requested_by_id -> app_user
#   ban_tombstone                     HMACs of Discord ids under the HOME KEY_ENCRYPTION_KEY:
#                                     identity-derived, and useless under the beta's own key
#   configured_guild, role_mapping    the home guild roster, role names and admin_contact_email.
#                                     Beyond 367.3's wording: excluded so the beta holds no
#                                     identity at all; the owner sets the guild up afresh there.
#                                     (Coordinator's call; the owner can reverse it by deleting
#                                     these two names, since role_mapping -> configured_guild is
#                                     the only foreign key involved.)
# `override` has no user column and is shipped whole. tests/test_beta_overlay.py asserts this
# list; ship-data.sh refuses a dump that carries data for any name in it.
EXCLUDED_TABLE_DATA=(
	app_session django_session rate_limit_window cached_membership
	procrastinate_events procrastinate_jobs procrastinate_periodic_defers procrastinate_workers
	django_admin_log scheduled_run
	app_user audit_log bootstrap_claim pending_instance_admin_removal ban_tombstone
	configured_guild role_mapping
)

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)

live_dir=$repo
stage=${BETA_STAGE:-$HOME/beta-bundle}
dist=""; build_frontend=0; node_modules=""; with_tile_dirs=0
no_transfer=0; dry_run=0; bwlimit=""
declare -A without=()
positional=()

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
	case "$1" in
		-h | --help) usage; exit 0 ;;
		--live-dir) [ $# -ge 2 ] || die "$1 needs a value"; live_dir=$2; shift 2 ;;
		--stage) [ $# -ge 2 ] || die "$1 needs a value"; stage=$2; shift 2 ;;
		--build-frontend) build_frontend=1; shift ;;
		--dist) [ $# -ge 2 ] || die "$1 needs a value"; dist=$2; shift 2 ;;
		--node-modules) [ $# -ge 2 ] || die "$1 needs a value"; node_modules=$2; shift 2 ;;
		--without)
			[ $# -ge 2 ] || die "$1 needs a value"
			case "$2" in tiles | elevation | basemap | photon | frontend | db) without[$2]=1 ;; *) die "--without: unknown part '$2'" ;; esac
			shift 2
			;;
		--with-tile-dirs) with_tile_dirs=1; shift ;;
		--no-transfer) no_transfer=1; shift ;;
		--dry-run) dry_run=1; shift ;;
		--bwlimit) [ $# -ge 2 ] || die "$1 needs a value"; bwlimit=$2; shift 2 ;;
		--) shift; positional+=("$@"); break ;;
		-*) die "unknown option $1 (--help lists them)" ;;
		*) positional+=("$1"); shift ;;
	esac
done

if [ "$no_transfer" = 0 ]; then
	[ ${#positional[@]} -eq 2 ] || die "give HOST and REMOTE_DIR (or --no-transfer); --help for usage"
	remote_host=${positional[0]}
	remote_dir=${positional[1]}
	case "$remote_dir" in /?*) ;; *) die "REMOTE_DIR must be an absolute path, not '$remote_dir'" ;; esac
	case "$remote_dir" in /etc | /usr | /var | /bin | /boot | /root | /home | /data | /data/ | /lib) die "REMOTE_DIR '$remote_dir' is a system directory; name a directory for the bundle" ;; esac
	case "$remote_dir" in *[!A-Za-z0-9._/-]*) die "REMOTE_DIR has a character this script will not pass to a remote shell: '$remote_dir'" ;; esac
	case "$remote_host" in '' | -* | *[!A-Za-z0-9._@:-]*) die "odd HOST '$remote_host'" ;; esac
else
	[ ${#positional[@]} -eq 0 ] || [ ${#positional[@]} -eq 2 ] || die "with --no-transfer give nothing, or HOST and REMOTE_DIR"
fi

want() { [ -z "${without[$1]:-}" ]; }

env_file="$live_dir/.env"
[ -r "$env_file" ] || die "cannot read $env_file (--live-dir names the live stack's checkout)"
[ -r "$live_dir/compose.yaml" ] || die "no compose.yaml in $live_dir"

env_value() { # last KEY= line of the live .env, quotes stripped; never sourced
	sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$env_file" | tail -n 1 | tr -d '\r' | sed "s/^['\"]//; s/['\"]\$//"
}

data_root=$(env_value DATA_ROOT)
[ -n "$data_root" ] || die "no DATA_ROOT= in $env_file"
case "$data_root" in /?*) ;; *) die "DATA_ROOT '$data_root' is not absolute" ;; esac
[ -d "$data_root" ] || die "DATA_ROOT $data_root is not a directory"
pguser=$(env_value PGUSER); pguser=${pguser:-routemaker}
pgdatabase=$(env_value PGDATABASE); pgdatabase=${pgdatabase:-routemaker}
live_schema=$(env_value ROUTEMAKER_LIVE_SCHEMA); live_schema=${live_schema:-live}
case "$live_schema$pguser$pgdatabase" in *[!A-Za-z0-9_]*) die "odd schema, user or database name in $env_file" ;; esac

# --- the stage must not be inside anything it reads -----------------------------------------
mkdir -p "$stage"
stage=$(cd "$stage" && pwd -P)
for protected in "$data_root" "$live_dir"; do
	real=$(cd "$protected" && pwd -P)
	case "$stage/" in "$real"/*) die "--stage $stage is inside $real; that would write into the live stack" ;; esac
done
[ "$stage" != "/" ] && [ "$stage" != "$HOME" ] || die "refusing --stage $stage"

dc() { docker compose --project-directory "$live_dir" -f "$live_dir/compose.yaml" --env-file "$env_file" "$@"; }

if want db; then
	running=$(dc ps --status running --services 2>/dev/null || true)
	grep -qx postgis <<<"$running" || die "the live stack's postgis is not running (docker compose in $live_dir)"
fi

# --- start from a clean stage ------------------------------------------------------------------
# Only what this script put there: it owns these names and nothing else in the stage.
for part in tiles elevation basemap photon frontend db; do rm -rf "${stage:?}/$part"; done
rm -f "$stage/SHA256SUMS" "$stage/MANIFEST.txt"

link() { mkdir -p "$(dirname "$2")"; ln -s "$1" "$2"; }

tile_summary=""
# --- tiles -------------------------------------------------------------------------------------------
if want tiles; then
	found=0
	for variant_dir in "$data_root"/tiles/*/; do
		variant=$(basename "$variant_dir")
		[ -L "$variant_dir/current" ] || continue
		build=$(basename "$(readlink "$variant_dir/current")")
		src="$variant_dir/$build"
		[ -f "$src/tiles.tar" ] || die "$variant: current -> $build has no tiles.tar"
		for f in tiles.tar admin.sqlite tz_world.sqlite build-config.json; do
			[ -f "$src/$f" ] || die "$variant/$build is missing $f"
			link "$src/$f" "$stage/tiles/$variant/$build/$f"
		done
		[ "$with_tile_dirs" = 0 ] || link "$src/tiles" "$stage/tiles/$variant/$build/tiles"
		tile_summary="$tile_summary $variant=$build"
		found=$((found + 1))
	done
	for need in standard no-trail ebike weekend; do
		[ -d "$stage/tiles/$need" ] || die "no promoted build (a current symlink) for the $need graph under $data_root/tiles"
	done
	note "tiles: $found graphs:$tile_summary"
fi

# --- elevation, basemap, photon ----------------------------------------------------------------------
if want elevation; then
	[ -d "$data_root/elevation" ] || die "no $data_root/elevation"
	link "$data_root/elevation" "$stage/elevation"
fi
if want basemap; then
	[ -f "$data_root/basemap/region.pmtiles" ] || die "no $data_root/basemap/region.pmtiles"
	link "$data_root/basemap" "$stage/basemap"
fi
if want photon; then
	[ -d "$data_root/photon/photon_data" ] || die "no Photon index at $data_root/photon/photon_data"
	link "$data_root/photon" "$stage/photon"
fi

# --- front end -----------------------------------------------------------------------------------------
if want frontend; then
	mkdir -p "$stage/frontend"
	if [ "$build_frontend" = 1 ]; then
		[ -z "$dist" ] || die "give --build-frontend or --dist, not both"
		nm=${node_modules:-$repo/frontend/node_modules}
		[ -d "$nm" ] || die "no node_modules at $nm (--node-modules); the build runs offline"
		note "building the front end with VITE_BETA=1 in the pinned node image (no network)"
		# node_modules is mounted writable because vite writes a temp config beside it; it is
		# removed afterwards. The source is read-only and the output goes straight to the stage.
		docker run --rm --pull never --network none -u "$(id -u):$(id -g)" -e HOME=/tmp -e VITE_BETA=1 \
			-v "$repo/frontend:/app:ro" -v "$nm:/app/node_modules" -v "$stage/frontend:/out" -w /app \
			"$NODE_IMAGE" sh -c 'npx tsc --noEmit && npx vite build --outDir /out --emptyOutDir' >&2
		rm -rf "$nm/.vite-temp"
		printf 'VITE_BETA=1\ngit=%s\n' "$(git -C "$repo" rev-parse HEAD)" >"$stage/frontend/beta-build.txt"
	else
		[ -n "$dist" ] || dist="$repo/frontend/dist"
		[ -f "$dist/index.html" ] || die "no front end at $dist: use --build-frontend, or --dist DIR with index.html"
		cp -R "$dist"/. "$stage/frontend/"
		if [ ! -f "$stage/frontend/beta-build.txt" ]; then
			note "WARNING: $dist has no beta-build.txt, so it was not built by --build-frontend; it will show the beta banner only if it was built with VITE_BETA=1"
		fi
	fi
	[ -f "$stage/frontend/index.html" ] || die "the front end has no index.html"
fi

# --- database ---------------------------------------------------------------------------------------------
excluded_args=()
for t in "${EXCLUDED_TABLE_DATA[@]}"; do excluded_args+=("--exclude-table-data=public.$t"); done

if want db; then
	mkdir -p "$stage/db"
	note "database: pg_dump of schemas public and $live_schema (read-only)"
	dc exec -T postgis pg_dump -U "$pguser" -d "$pgdatabase" --format=custom --no-owner --no-privileges \
		-n public -n "$live_schema" "${excluded_args[@]}" >"$stage/db/routemaker.dump"
	[ -s "$stage/db/routemaker.dump" ] || die "pg_dump wrote nothing"

	listing=$(dc exec -T postgis pg_restore --list <"$stage/db/routemaker.dump")
	# Here-strings, not pipes: under pipefail a grep -q that exits early makes printf fail with SIGPIPE.
	grep -q "TABLE DATA $live_schema " <<<"$listing" || die "the dump has no data for the $live_schema schema"
	grep -q "TABLE DATA public override " <<<"$listing" || die "the dump has no override data"
	for t in "${EXCLUDED_TABLE_DATA[@]}"; do
		if grep -q "TABLE DATA public $t " <<<"$listing"; then die "the dump carries data for $t, which must be excluded"; fi
	done
	if grep -Eq "TABLE DATA (tiger|topology|${live_schema}_old) " <<<"$listing"; then die "the dump carries a schema it should not"; fi

	# Row counts of the tables whose data is shipped; receive-data.sh compares them after the restore.
	tables=$(dc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -At -c \
		"select schemaname||'.'||tablename from pg_tables where schemaname in ('public','$live_schema') order by 1")
	: >"$stage/db/row-counts.tsv"
	while IFS= read -r qualified; do
		[ -n "$qualified" ] || continue
		skip=0
		for t in "${EXCLUDED_TABLE_DATA[@]}"; do [ "$qualified" = "public.$t" ] && skip=1; done
		[ "$skip" = 0 ] || continue
		case "$qualified" in public.spatial_ref_sys) continue ;; esac
		# </dev/null: `compose exec -T` reads stdin, which here is the table list the loop is reading.
		count=$(dc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -At -c "select count(*) from \"${qualified%%.*}\".\"${qualified#*.}\"" </dev/null)
		printf '%s\t%s\n' "$qualified" "$count" >>"$stage/db/row-counts.tsv"
	done <<<"$tables"
	[ -s "$stage/db/row-counts.tsv" ] || die "no row counts were read"
	grep -q "^$live_schema\." "$stage/db/row-counts.tsv" || die "no row counts for the $live_schema schema were read"
	table_count=$(grep -c . <<<"$tables")
	counted=$(grep -c . "$stage/db/row-counts.tsv")
	[ "$counted" -ge $((table_count - ${#EXCLUDED_TABLE_DATA[@]} - 1)) ] || die "counted $counted of $table_count tables; the count loop stopped early"
	db_version=$(dc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -At -c "select split_part(version(), ' ', 2) || ' postgis ' || postgis_lib_version()")
else
	db_version=""
fi

# --- no secrets ---------------------------------------------------------------------------------------------
bad=$(find -L "$stage" \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' -o -name 'id_rsa*' -o -name 'id_ed25519*' -o -name '*.htpasswd' -o -name '.git' -o -name '.netrc' \) -print 2>/dev/null || true)
[ -z "$bad" ] || die "files that look like secrets are in the stage: $bad"
# And not the value of any secret from the live .env, in the text files that go.
for key in PGPASSWORD DJANGO_SECRET_KEY KEY_ENCRYPTION_KEY DISCORD_CLIENT_SECRET DISCORD_BOT_TOKEN BOT_INTERNAL_SECRET; do
	value=$(env_value "$key")
	[ "${#value}" -ge 8 ] || continue
	case "$value" in change-me*) continue ;; esac
	if [ -d "$stage/frontend" ] && grep -rlF -- "$value" "$stage/frontend" >/dev/null 2>&1; then die "the value of $key from the live .env appears in the front end; refusing to ship"; fi
	if [ -d "$stage/db" ] && grep -lF -- "$value" "$stage"/db/*.tsv >/dev/null 2>&1; then die "the value of $key appears in the row counts; refusing to ship"; fi
done

# --- manifest -------------------------------------------------------------------------------------------------
note "checksums (sha256 of every file; this reads the whole bundle once)"
(
	cd "$stage"
	find -L . -type f ! -name SHA256SUMS ! -name MANIFEST.txt ! -path '*/.rsync-partial/*' -print0 |
		sed -z 's|^\./||' | sort -z | xargs -0 -r -n 1 -P 2 sha256sum | sort -k 2 >SHA256SUMS
)
[ -s "$stage/SHA256SUMS" ] || die "nothing to ship (every part was left out?)"
files=$(wc -l <"$stage/SHA256SUMS")
bytes=$(cd "$stage" && find -L . -type f ! -name SHA256SUMS ! -name MANIFEST.txt -printf '%s\n' | awk '{s+=$1} END {printf "%d", s}')
git_sha=$(git -C "$repo" rev-parse HEAD)
git_dirty=$(git -C "$repo" status --porcelain 2>/dev/null | wc -l)
{
	echo "bundle_format=1"
	echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo "git_sha=$git_sha"
	echo "git_dirty_files=$git_dirty"
	echo "tiles=${tile_summary# }"
	echo "live_schema=$live_schema"
	echo "database=$pgdatabase"
	echo "database_server=$db_version"
	echo "excluded_table_data=${EXCLUDED_TABLE_DATA[*]}"
	echo "parts=$(for p in tiles elevation basemap photon frontend db; do want "$p" && printf '%s ' "$p"; done)"
	echo "files=$files"
	echo "bytes=$bytes"
} >"$stage/MANIFEST.txt"
[ "$git_dirty" = 0 ] || note "WARNING: $repo has $git_dirty uncommitted files; the manifest records git_sha=$git_sha, which is not exactly what built the front end"
note "bundle: $files files, $(awk -v b="$bytes" 'BEGIN {printf "%.2f GiB", b / 1073741824}') in $stage"

[ "$no_transfer" = 0 ] || { note "--no-transfer: staged and checksummed, nothing sent"; exit 0; }

# --- transfer -----------------------------------------------------------------------------------------------------
ssh_cmd="ssh ${BETA_SSH_OPTS:-} -o ServerAliveInterval=30 -o ServerAliveCountMax=10"
common=(-aL --partial --partial-dir=.rsync-partial --no-owner --no-group --chmod=D755,F644
	--human-readable --timeout=300 -e "$ssh_cmd")
# A progress line only on a terminal: into a log it is one long unreadable line.
if [ -t 2 ]; then common+=(--info=progress2,stats1); else common+=(--info=stats1); fi
[ -z "$bwlimit" ] || common+=("--bwlimit=$bwlimit")
[ "$dry_run" = 0 ] || common+=(--dry-run)

# The previous bundle's SHA256SUMS and MANIFEST.txt go first: after an interrupted update
# they would sit beside half-new data, and "no manifest means unfinished" is the signal
# receive-data.sh relies on. (Not on --dry-run, which changes nothing remote but the mkdir.)
if [ "$dry_run" = 0 ]; then
	# shellcheck disable=SC2086
	$ssh_cmd "$remote_host" "mkdir -p '$remote_dir' && rm -f '$remote_dir/SHA256SUMS' '$remote_dir/MANIFEST.txt'"
else
	# shellcheck disable=SC2086
	$ssh_cmd "$remote_host" "mkdir -p '$remote_dir'"
fi

retries=${BETA_RSYNC_RETRIES:-5}
run_rsync() {
	local attempt=1 status=0
	while :; do
		rsync "$@" && return 0
		status=$?
		case "$status" in 10 | 12 | 30 | 35 | 255) ;; *) return "$status" ;; esac
		[ "$attempt" -lt "$retries" ] || return "$status"
		note "rsync stopped with $status; resuming in 10 s (attempt $attempt of $retries)"
		attempt=$((attempt + 1))
		sleep 10
	done
}

note "sending the data, manifest last (rerun this same command to resume)"
run_rsync "${common[@]}" --exclude=SHA256SUMS --exclude=MANIFEST.txt --exclude='.rsync-partial' "$stage/" "$remote_host:$remote_dir/"
run_rsync "${common[@]}" "$stage/SHA256SUMS" "$stage/MANIFEST.txt" "$remote_host:$remote_dir/"

note "sent. On the server: scripts/beta/receive-data.sh --bundle $remote_dir --env-file .env verify"
