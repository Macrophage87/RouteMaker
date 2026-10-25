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
#   basemap/            region.pmtiles, fonts, sprites, and contours.pmtiles once
#                       scripts/build_contours.py has written it (the Topo lines layer)
#   photon/             the Photon index (photon_data/)
#   tiles/transit/transit-schedule.json
#                       the transit ride types' schedule (scripts/build_transit_schedule.py), when
#                       it has been built; without it the beta's transit plans answer "not
#                       available". Sending the agencies' timetables to our own server is not
#                       redistribution (docs/SOURCES.md); the file is never committed.
#   frontend/           the built front end, made with VITE_BETA=1 so it carries the beta banner
#   db/routemaker.dump  pg_dump --format=custom of the `live` and `public` schemas, minus the
#                       data of sessions, rate-limit rows, membership cache, job queues and
#                       every table holding an identity (accounts, audit log, guild roster)
#   db/blanked/*.copy   the tables that name a person but are needed (override, approved
#                       junction ratings, Avoid junctions), with every person column NULL
#   db/row-counts.tsv   what receive-data.sh checks the restore against
#   SHA256SUMS          one line per file; MANIFEST.txt the bundle's facts
#
# What is never in it: .env or any secret (the script checks), the other test databases,
# the `live_old` schema, the tiger geocoder schema, sessions. Nor the api image: the runbook sends
# that separately (step 6), and after sending the script warns if the server does not have the
# image for this checkout's sha.
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
#   --build-frontend     test (npm test) and build the front end in the pinned node image,
#                        offline, with VITE_BETA=1 (the preferred way)
#   --report-url URL     with --build-frontend: an https address the beta notice links to as
#                        "Report a problem" (VITE_BETA_REPORT_URL; OWNER-DECISIONS 382). Without
#                        it the notice shows only its built-in Discord and sign-up links.
#   --dist DIR           use an already-built front end instead (must contain index.html)
#                        Unless --without frontend, one of --build-frontend or --dist is required.
#   --node-modules DIR   node_modules for --build-frontend [<repo>/frontend/node_modules], installed
#                        for Linux x64 (in WSL with no Linux node, `npm ci` is Windows npm: install
#                        it in the pinned image instead; frontend-build.sh refuses a Windows one)
#   --without PART       leave a part out: tiles, elevation, basemap, photon, transit, frontend, db
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

# The pinned node image is frontend-build.sh's (--print-image); the api image is sent separately.
API_IMAGE="ghcr.io/macrophage87/routemaker-api"
# Data the app does not need on a fresh server, or must not carry: sessions and the
# rate-limit table (client address digests) and the membership cache are the app's own nightly
# backup exclusions (config.procrastinate.BACKUP_EXCLUDED_TABLES), plus the job queue, Django's
# own sessions, the admin log and run history, which belong to the home install.
#
# stress_tile_cache is excluded too (it is also a nightly-backup exclusion). Each row is keyed on
# the pg_class oid of the live segment table (core.tile_cache, stress_tiles.etag_for), and the
# beta's restore creates that table afresh with a new oid, so not one shipped row could ever be
# served there. The beta fills its own cache: docs/BETA-RUNBOOK.md runs predraw_stress_tiles
# after the first start and after every `db --update-data`.
#
# bikeshare_feed_cache is excluded too: its one row is the operator's live feed, replaced every
# minute (core.gbfs); a shipped copy would be stale on arrival and is not ours to distribute.
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
#   stress_suggestion                 suggester_id and decided_by_id -> app_user, plus the plain
#                                     suggester_user_id: riders' suggestions belong to the home
#                                     install's review (core.suggestions)
#   mass_hazard                       reporter_id and decided_by_id -> app_user, plus the plain
#                                     reporter_user_id: riders' hazard reports, the same (core.mass_hazards)
#   junction_suggestion               the same for junctions (suggester_id, decided_by_id,
#                                     suggester_user_id; core.junction_suggestions)
#   stress_edit                       actor_id -> app_user, plus the plain actor_user_id: home's
#                                     half-step editor history. What it changed is already in the
#                                     shipped live table and override rows; it also points at
#                                     override rows, which the beta's update replaces.
#   my_go                             user_id -> app_user: a rider's own My Go, with their Home
#                                     (a place they live; core.models.MyGo). Never leaves home.
#   account_settings                  user_id -> app_user: a rider's saved settings (v0.7.0).
#   saved_route                       user_id -> app_user: a rider's saved routes and GPX files (v0.7.0).
#   signed_out_send                   salted daily hashes of signed-out suggesters' addresses (v0.7.0;
#                                     core.signed_out_suggestions), kept 24 hours: never shipped.
#   shared_route                      routes riders shared with the Share button (v0.7.0;
#                                     core.shared_routes): a rider's own lines, never shipped.
#   saved_route_version               earlier versions of a rider's saved routes (v0.7.0): never shipped.
#   reviewed_closure                  closures home's reviewers confirmed (v0.7.0; core.reviewed_closures):
#                                     the reviewer's account and a rider's reported words, never shipped.
#   review_item review_ruling         Review mode's queues, rulings and their maps (v0.7.0;
#   review_queue_state                core.stress_review): an instance admin's own, and ratings whose
#                                     public use is pending (agency_lts.PENDING_AGENCIES), never shipped.
#   stress_suggestion_review          reviewers' agree and disagree on home's waiting suggestions
#                                     (v0.7.0; core.suggestions.review): suggestion_id ->
#                                     stress_suggestion, reviewer_id -> app_user. Never shipped.
#   assistant_key                     user_id -> app_user: a rider's AI assistant key digest. The
#                                     table is dropped by migration 0046 (v0.12.2); kept here while a
#                                     home not yet migrated could still dump it. Never shipped.
#   connector_client connector_grant  the MCP connector's apps, riders' grants to them (token
#   connector_draft                   digests) and unsaved drafts (v0.10.0; core.connector):
#                                     user_id -> app_user. Never shipped.
#   report311_log                     user_id -> app_user: a rider's own 311 checklist, with where
#                                     they saw each problem (v0.10.0; core.models.Report311Log).
#   garmin_link                       user_id -> app_user: a rider's encrypted Garmin tokens
#                                     (v0.12.0; core.models.GarminLink). Never shipped.
#   wahoo_link                        user_id -> app_user: a rider's encrypted Wahoo tokens
#                                     (v0.12.0; core.models.WahooLink). Never shipped.
#   route_post route_post_section     Featured routes posts (v0.12.1; core.route_posts): author_id ->
#                                     app_user, saved_route_id -> saved_route, route_id -> shared_route.
#                                     Written on the site that shows them, never shipped.
# tests/test_beta_overlay.py asserts this list, and that every table pointing at one of these is
# excluded too or blanked (below); ship-data.sh refuses a dump that carries data for any name in it.
EXCLUDED_TABLE_DATA=(
	app_session django_session rate_limit_window cached_membership
	procrastinate_events procrastinate_jobs procrastinate_periodic_defers procrastinate_workers
	django_admin_log scheduled_run stress_tile_cache bikeshare_feed_cache
	app_user audit_log bootstrap_claim pending_instance_admin_removal ban_tombstone
	configured_guild role_mapping stress_suggestion mass_hazard junction_suggestion stress_edit
	my_go account_settings saved_route saved_route_version signed_out_send shared_route reviewed_closure
	review_item review_ruling review_queue_state
	stress_suggestion_review assistant_key connector_client connector_grant connector_draft
	report311_log garmin_link wahoo_link route_post route_post_section
)
# Tables the beta needs from home that also name a person or carry a rider's words: shipped with
# those columns blanked, never whole. Each is left out of the dump and written instead as
# db/blanked/<table>.copy from a SELECT that blanks every listed column, so nothing in the bundle
# points at app_user (which is excluded) and the restore's foreign keys hold, and no rider's reason
# leaves home; receive-data.sh loads the files after the restore. The approver's account and the
# rider's words are home's alone; what was approved is what the beta needs.
#   override           the access and stress corrections (created_by, approved_by; and the
#                      reason of a row an approved rider suggestion made, "Rider suggestion N,
#                      approved: <the rider's reason>", core.suggestions.approve)
#   junction_override  riders' approved junction ratings (core.junction_suggestions; evidence is
#                      "Rider suggestion N: <the rider's reason>")
#   avoid_junction     approved Avoid junctions (core.avoid_junctions; evidence the same where a
#                      rider's suggestion made it, and private to the admin where not)
# Format TABLE:COLUMN,COLUMN. A column ending in _by_id or user_id becomes NULL; COLUMN=rider keeps
# the text unless it is a rider suggestion's ("Rider suggestion ..."), which becomes
# RIDER_REASON_BLANKED; any other column becomes '' (a NOT NULL text column). The script refuses a
# table that has a foreign key to app_user, or a column ending in user_id, not listed here, so a
# person column added later is not shipped by accident.
# The commas are part of each entry, not separators (read with IFS=, below).
# shellcheck disable=SC2054
BLANKED_TABLE_DATA=(
	override:created_by_id,created_by_user_id,approved_by_id,approved_by_user_id,reason=rider
	junction_override:created_by_id,created_by_user_id,evidence
	avoid_junction:created_by_id,created_by_user_id,approved_by_id,approved_by_user_id,evidence
)
RIDER_REASON_BLANKED="Rider suggestion (its reason stays at home)"

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)

live_dir=$repo
stage=${BETA_STAGE:-$HOME/beta-bundle}
dist=""; build_frontend=0; node_modules=""; with_tile_dirs=0; report_url=""
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
		--report-url) [ $# -ge 2 ] || die "$1 needs a value"; report_url=$2; shift 2 ;;
		--node-modules) [ $# -ge 2 ] || die "$1 needs a value"; node_modules=$2; shift 2 ;;
		--without)
			[ $# -ge 2 ] || die "$1 needs a value"
			case "$2" in tiles | elevation | basemap | photon | transit | frontend | db) without[$2]=1 ;; *) die "--without: unknown part '$2'" ;; esac
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

want() { [ -z "${without[$1]:-}" ]; }

# The front end's source, decided before anything is read or staged.
if want frontend; then
	[ "$build_frontend" = 1 ] || [ -n "$dist" ] ||
		die "give --build-frontend (preferred: tested and built here with VITE_BETA=1) or --dist DIR, or --without frontend"
	[ "$build_frontend" = 0 ] || [ -z "$dist" ] || die "give --build-frontend or --dist, not both"
fi
if [ -n "$report_url" ]; then
	[ "$build_frontend" = 1 ] || die "--report-url needs --build-frontend (the address is built into the front end)"
	case "$report_url" in
		https://[!/]*) ;;
		*) die "--report-url must be an https:// address, not '$report_url'" ;;
	esac
	case "$report_url" in
		*[!A-Za-z0-9._~:/?#!\$\&*+,\;=%-]* | *@*) die "--report-url has a character it may not carry (spaces, quotes, brackets, a user name): '$report_url'" ;;
	esac
fi

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
for part in tiles elevation basemap photon transit frontend db; do rm -rf "${stage:?}/$part"; done
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
	# The whole directory is shipped, so a contour build's leftovers (a --keep-work or failed run of
	# scripts/build_contours.py: gigabytes of DEM and line files, or a half-written archive) would go too.
	for leftover in .contours-work .contours.pmtiles.part; do
		[ ! -e "$data_root/basemap/$leftover" ] ||
			die "$data_root/basemap/$leftover is left from scripts/build_contours.py; delete it (or finish the build) before shipping (docs/OPERATIONS.md, \"Topo lines\")"
	done
	link "$data_root/basemap" "$stage/basemap"
fi
if want photon; then
	[ -d "$data_root/photon/photon_data" ] || die "no Photon index at $data_root/photon/photon_data"
	link "$data_root/photon" "$stage/photon"
fi

# --- transit schedule --------------------------------------------------------------------------------
# Beside the tile builds, where the api reads it (settings.TRANSIT_SCHEDULE_PATH); staged at the
# same path so the bundle still mirrors DATA_ROOT. Not built at home: said, and left out.
if want transit; then
	schedule="$data_root/tiles/transit/transit-schedule.json"
	if [ -f "$schedule" ]; then
		link "$schedule" "$stage/tiles/transit/transit-schedule.json"
		note "transit: the schedule, $(stat -L -c %s "$schedule") bytes"
	else
		note "WARNING: no transit schedule at $schedule, so the beta's transit ride types will say they are not available; build it first (docs/OPERATIONS.md, \"Transit schedule\"), or pass --without transit"
		without[transit]=1
	fi
fi

# --- front end -----------------------------------------------------------------------------------------
if want frontend; then
	mkdir -p "$stage/frontend"
	if [ "$build_frontend" = 1 ]; then
		nm=${node_modules:-$repo/frontend/node_modules}
		[ -d "$nm" ] || die "no node_modules at $nm (--node-modules); the build runs offline"
		note "testing and building the front end with VITE_BETA=1 in the pinned node image (no network); report link: ${report_url:-none}"
		# npm test runs first, on exactly the tree being shipped (the banner's and the planner's
		# accessibility checks live in the front-end suite); a failure ships nothing. The mounts
		# and the steps are frontend-build.sh's, the same script the release agent and CI run.
		"$here/frontend-build.sh" "$repo" "$nm" "$stage/frontend" "$report_url" >&2
		printf 'VITE_BETA=1\nVITE_BETA_REPORT_URL=%s\ngit=%s\n' "$report_url" "$(git -C "$repo" rev-parse HEAD)" >"$stage/frontend/beta-build.txt"
	else
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
for entry in "${BLANKED_TABLE_DATA[@]}"; do excluded_args+=("--exclude-table-data=public.${entry%%:*}"); done

if want db; then
	mkdir -p "$stage/db"
	note "database: pg_dump of schemas public and $live_schema (read-only)"
	dc exec -T postgis pg_dump -U "$pguser" -d "$pgdatabase" --format=custom --no-owner --no-privileges \
		-n public -n "$live_schema" "${excluded_args[@]}" >"$stage/db/routemaker.dump"
	[ -s "$stage/db/routemaker.dump" ] || die "pg_dump wrote nothing"

	listing=$(dc exec -T postgis pg_restore --list <"$stage/db/routemaker.dump")
	# Here-strings, not pipes: under pipefail a grep -q that exits early makes printf fail with SIGPIPE.
	grep -q "TABLE DATA $live_schema " <<<"$listing" || die "the dump has no data for the $live_schema schema"
	for t in "${EXCLUDED_TABLE_DATA[@]}"; do
		if grep -q "TABLE DATA public $t " <<<"$listing"; then die "the dump carries data for $t, which must be excluded"; fi
	done
	for entry in "${BLANKED_TABLE_DATA[@]}"; do
		if grep -q "TABLE DATA public ${entry%%:*} " <<<"$listing"; then die "the dump carries ${entry%%:*} whole; it must ship with its person columns blanked"; fi
	done
	if grep -Eq "TABLE DATA (tiger|topology|${live_schema}_old) " <<<"$listing"; then die "the dump carries a schema it should not"; fi

	# The tables that ship with their person columns blanked (BLANKED_TABLE_DATA): a read-only
	# SELECT with NULL in each of those columns, in COPY's text format (a backslash in the data is
	# doubled, so no line of it can end the inline COPY receive-data.sh feeds psql) with a header
	# line naming every column.
	mkdir -p "$stage/db/blanked"
	for entry in "${BLANKED_TABLE_DATA[@]}"; do
		t=${entry%%:*}
		declare -A spec_of=()
		IFS=, read -r -a wanted_blank <<<"${entry#*:}"
		for spec in "${wanted_blank[@]}"; do spec_of[${spec%%=*}]=$spec; done
		cols=$(dc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -At -c \
			"select string_agg(column_name, ',' order by ordinal_position) from information_schema.columns where table_schema = 'public' and table_name = '$t'" </dev/null)
		[ -n "$cols" ] || die "no table public.$t to ship blanked"
		case "$cols" in *[!a-z0-9_,]*) die "public.$t has a column name this script will not quote" ;; esac
		# The columns that name a person: a foreign key to app_user, or a plain copy of a user id.
		persons=$(dc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -At -c \
			"select string_agg(a.attname, ',') from pg_constraint c join pg_attribute a on a.attrelid = c.conrelid and a.attnum = any(c.conkey) where c.contype = 'f' and c.conrelid = 'public.$t'::regclass and c.confrelid = 'public.app_user'::regclass" </dev/null)
		for c in "${!spec_of[@]}"; do
			case ",$cols," in *",$c,"*) ;; *) die "public.$t has no column $c to blank; update BLANKED_TABLE_DATA" ;; esac
		done
		IFS=, read -r -a all_cols <<<"$cols"
		select=""
		for c in "${all_cols[@]}"; do
			case "${spec_of[$c]:-}" in
				"")
					case ",$persons," in *",$c,"*) die "public.$t has a person column $c (a key to app_user) that BLANKED_TABLE_DATA does not blank" ;; esac
					case "$c" in *user_id) die "public.$t has a person column $c that BLANKED_TABLE_DATA does not blank" ;; esac
					expr=$c
					;;
				*=rider) expr="CASE WHEN $c LIKE 'Rider suggestion %' THEN '$RIDER_REASON_BLANKED' ELSE $c END AS $c" ;;
				*_by_id | *user_id) expr="NULL AS $c" ;;
				*) expr="'' AS $c" ;;
			esac
			select="${select:+$select, }$expr"
		done
		unset spec_of
		dc exec -T postgis psql -U "$pguser" -d "$pgdatabase" -v ON_ERROR_STOP=1 -c \
			"COPY (select $select from public.$t order by 1) TO STDOUT WITH (FORMAT text, HEADER true)" </dev/null >"$stage/db/blanked/$t.copy"
		[ "$(head -n 1 "$stage/db/blanked/$t.copy" | tr '\t' ',')" = "$cols" ] || die "db/blanked/$t.copy does not start with public.$t's columns"
	done
	[ -s "$stage/db/blanked/override.copy" ] || die "the bundle has no override data"

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
	echo "blanked_table_data=${BLANKED_TABLE_DATA[*]}"
	echo "parts=$(for p in tiles elevation basemap photon transit frontend db; do want "$p" && printf '%s ' "$p"; done)"
	echo "files=$files"
	echo "bytes=$bytes"
} >"$stage/MANIFEST.txt"
[ "$git_dirty" = 0 ] || note "WARNING: $repo has $git_dirty uncommitted files; the manifest records git_sha=$git_sha, which is not exactly what built the front end"
note "bundle: $files files, $(awk -v b="$bytes" 'BEGIN {printf "%.2f GiB", b / 1073741824}') in $stage"

[ "$no_transfer" = 0 ] || { note "--no-transfer: staged and checksummed, nothing sent"; exit 0; }

# --- transfer -----------------------------------------------------------------------------------------------------
ssh_cmd="ssh ${BETA_SSH_OPTS:-} -o ServerAliveInterval=30 -o ServerAliveCountMax=10"
common=(-aL --partial --partial-dir=.rsync-partial --no-owner --no-group "--chmod=D755,F644"
	--human-readable --timeout=300 -e "$ssh_cmd")
# A progress line only on a terminal: into a log it is one long unreadable line.
if [ -t 2 ]; then common+=("--info=progress2,stats1"); else common+=(--info=stats1); fi
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

# The api image is not in the bundle: the runbook sends it separately (BETA-RUNBOOK step 6, built
# at home from the release sha). Say so when the server does not have the one for this sha yet.
# (A data-only update from a checkout ahead of the deployed release names an image the server does
# not need yet; the warning says which sha it looked for.)
api_tag="$API_IMAGE:${git_sha:0:12}"
[ "$dry_run" = 0 ] || exit 0
# shellcheck disable=SC2086
have=$($ssh_cmd "$remote_host" "if docker image inspect --format ok '$api_tag' 2>/dev/null; then :; elif docker info >/dev/null 2>&1; then echo missing; else echo no-docker; fi" 2>/dev/null) || have=""
case "$have" in
	ok) ;;
	missing)
		note "WARNING: the server has no api image $api_tag; the bundle does not carry it. From a clean checkout of $git_sha:"
		note "  docker build -f docker/api.Dockerfile -t $api_tag ."
		note "  docker save $api_tag | gzip | ssh ${BETA_SSH_OPTS:+$BETA_SSH_OPTS }$remote_host 'gunzip | docker load'"
		;;
	*) note "could not ask docker on the server whether it has the api image $api_tag (docker image ls there)" ;;
esac
