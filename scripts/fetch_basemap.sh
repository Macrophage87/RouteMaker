#!/bin/sh
# Fetch the self-hosted base map into ${DATA_ROOT}/basemap, which compose binds
# read-only into Caddy at /srv/basemap and the Caddyfile serves at /basemap/*.
#
# PLAN.md "Base map": a PMTiles file extracted with `pmtiles extract` from the
# Protomaps daily build against the coverage region, with glyphs and sprites
# self-hosted beside it. What ends up in the directory:
#
#     region.pmtiles        the Protomaps basemap (v4 schema) over BBOX
#     fonts/<stack>/<range>.pbf, fonts/OFL.txt
#                           the glyphs, from protomaps/basemaps-assets
#     sprites/v4/<flavor>.json|.png|@2x.*, sprites/README.md
#                           the sprites, from the same commit, with that
#                           commit's README, which is where it states the
#                           licence of each directory
#     .region.source, .assets.source
#                           what each was made from; a run whose pins match
#                           these, with the files present, does nothing
#
# Licences and required credits are in docs/OPERATIONS.md, "The base map".
#
# Every input is pinned below. The pmtiles binary and the assets archive are
# checked against a sha256 before anything is unpacked, and a mismatch installs
# nothing. The region is not checksummed, because there is nothing to check it
# against - Protomaps publishes no digest for a daily build and an extract is
# a new file - so `pmtiles verify` is run on it instead before it is moved in.
#
# Usage. DATA_ROOT must be set, and the run must be as the owner of
# ${DATA_ROOT}/basemap, which scripts/prepare_data_root.sh hands to uid 10001.
# That uid has no account on the host and cannot read a checkout under a home
# directory, so the documented form runs the script in a container as 10001
# with only the script and that one directory mounted (docs/OPERATIONS.md,
# "The base map", has the command). The image needs sh, curl, tar, sha256sum
# and cut; the pinned pmtiles binary needs x86_64 Linux.
#
# `--build YYYYMMDD` overrides PROTOMAPS_BUILD for one run. build.protomaps.com
# keeps daily builds for a limited time only, so a pin older than that is a 404.
# Without --build, a pinned day that is gone does not fail the run: a region
# already installed over BBOX is kept, then our own kept copy (below) over BBOX,
# and otherwise the newest day available in the last FALLBACK_DAYS is used; each
# way it says to bump the pin. A pin older than REFRESH_AFTER_DAYS is reminded
# about on every run. `--print-stamps` prints what the stamps of a finished run
# with these pins would hold, and exits.
#
# Our own copy (the owner, 2026-10-29): after a good region is in place, a copy
# of it and its stamp is kept in BASEMAP_KEEP_DIR, by default
# ${DATA_ROOT}/backups/basemap, so a rebuild of the directory never depends on
# Protomaps still publishing the day. A region whose stamp the copy matches is
# installed from the copy with no download. Left at the default, a keep
# directory that is missing or not writable only skips the copy, with a note;
# named in BASEMAP_KEEP_DIR, it is an error.
#
# Nothing here touches the running stack: Caddy reads the files on each
# request, so a replaced region.pmtiles is served on the next one. The files
# are made world-readable, since the edge reads them as its own uid. There is
# no lock: two runs at once over the same directory delete each other's work.

set -eu

PMTILES_VERSION="1.31.2"
# The release asset's sha256 as GitHub records it for the asset (the release
# publishes no separate checksums file).
PMTILES_SHA256="3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f"
PMTILES_URL="https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz"

ASSETS_COMMIT="028c18f713baecad011301ff7a69acc39bcc2ae7"
ASSETS_SHA256="57e40e8c512bd8042d0a3a251f19d0d1c8523ad963c666c3c6643bada4dc92d0"
ASSETS_URL="https://github.com/protomaps/basemaps-assets/archive/${ASSETS_COMMIT}.tar.gz"

PROTOMAPS_BUILD="20260926"
# How far back to look for a build when the pin is gone, and how old a pin gets
# before every run says to refresh it.
FALLBACK_DAYS=30
REFRESH_AFTER_DAYS=45
# settings.COVERAGE_BBOX, west,south,east,north; tests/test_basemap.py holds
# the two equal.
BBOX="-78.05,38.2,-76.02,39.72"

usage() {
	echo "usage: DATA_ROOT=<path> fetch_basemap.sh [--build YYYYMMDD] [--print-stamps]" >&2
	exit 2
}

print_stamps=""
explicit_build=""
while [ $# -gt 0 ]; do
	case "$1" in
		--build)
			[ $# -ge 2 ] || usage
			PROTOMAPS_BUILD="$2"
			explicit_build=1
			shift 2
			;;
		--print-stamps)
			print_stamps=1
			shift
			;;
		*) usage ;;
	esac
done

case "$PROTOMAPS_BUILD" in
	20[0-9][0-9][0-9][0-9][0-9][0-9]) ;;
	*) echo "--build must be a date, YYYYMMDD, not '$PROTOMAPS_BUILD'" >&2; exit 2 ;;
esac

REGION_STAMP="build=$PROTOMAPS_BUILD bbox=$BBOX"
ASSETS_STAMP="commit=$ASSETS_COMMIT sha256=$ASSETS_SHA256"

if [ -n "$print_stamps" ]; then
	printf '.region.source %s\n.assets.source %s\n' "$REGION_STAMP" "$ASSETS_STAMP"
	exit 0
fi

: "${DATA_ROOT:?DATA_ROOT is not set; name the data root, e.g. DATA_ROOT=/srv/routemaker-data}"
case "$DATA_ROOT" in
	/?*) ;;
	*) echo "DATA_ROOT must be an absolute path, not '$DATA_ROOT'" >&2; exit 2 ;;
esac

target="$DATA_ROOT/basemap"
[ -d "$target" ] || {
	echo "$target does not exist; run scripts/prepare_data_root.sh first" >&2
	exit 2
}
[ -w "$target" ] || { echo "cannot write $target; run this as its owner" >&2; exit 2; }

keep="${BASEMAP_KEEP_DIR:-$DATA_ROOT/backups/basemap}"
case "$keep" in
	/?*) ;;
	*) echo "BASEMAP_KEEP_DIR must be an absolute path, not '$keep'" >&2; exit 2 ;;
esac
if [ ! -d "$keep" ] || [ ! -w "$keep" ]; then
	if [ -n "${BASEMAP_KEEP_DIR:-}" ]; then
		echo "cannot write BASEMAP_KEEP_DIR $keep; create it, owned by this user" >&2
		exit 2
	fi
	echo "note: $keep is missing or not writable, so no copy of the region is kept" >&2
	keep=""
fi
# The kept copy's stamp, or nothing when there is no whole copy.
kept_stamp=""
if [ -n "$keep" ] && [ -f "$keep/region.pmtiles" ]; then
	kept_stamp=$(cat "$keep/.region.source" 2>/dev/null || true)
fi

# Inside the target, so every move into place is a rename on one filesystem.
# The Caddyfile serves only region.pmtiles, fonts/ and sprites/, so neither
# this directory nor the stamps are ever reachable from outside. Removed first,
# before the "already current" exit, so a killed run's leftovers never outlive
# the next run.
work="$target/.work"
rm -rf "$work"

current() {
	# $1 stamp file, $2 expected stamp, $3... paths that must exist
	stamp_file="$1"
	expected="$2"
	shift 2
	# A missing stamp reads as empty, which matches no pin.
	[ "$(cat "$target/$stamp_file" 2>/dev/null)" = "$expected" ] || return 1
	for path in "$@"; do
		[ -e "$target/$path" ] || return 1
	done
	return 0
}

# The day `$1` days before today, YYYYMMDD, or nothing where `date` cannot say
# (GNU and busybox date both take -d @<epoch>).
days_ago() {
	date -u -d "@$(( $(date -u +%s) - $1 * 86400 ))" +%Y%m%d 2>/dev/null || true
}
build_url() {
	echo "https://build.protomaps.com/$1.pmtiles"
}
available() {
	curl -fsSI "$(build_url "$1")" >/dev/null 2>&1
}
remind() {
	echo "reminder: $1; bump PROTOMAPS_BUILD in scripts/fetch_basemap.sh to a recent day" >&2
	echo "(docs/OPERATIONS.md, \"The base map\")" >&2
}

cutoff=$(days_ago "$REFRESH_AFTER_DAYS")
if [ -z "$explicit_build" ] && [ -n "$cutoff" ] && [ "$PROTOMAPS_BUILD" -lt "$cutoff" ]; then
	remind "the pinned Protomaps build $PROTOMAPS_BUILD is over $REFRESH_AFTER_DAYS days old"
fi

need_region=1
need_assets=1
current .region.source "$REGION_STAMP" region.pmtiles && need_region=""
current .assets.source "$ASSETS_STAMP" fonts sprites sprites/README.md && need_assets=""

# Our kept copy of exactly this region: installed from there, with no request.
from_keep=""
if [ -n "$need_region" ] && [ -n "$kept_stamp" ] && [ "$kept_stamp" = "$REGION_STAMP" ]; then
	from_keep=1
fi

# A pinned day that build.protomaps.com no longer has. Named with --build it is
# the operator's own choice and fails below as before; the pin itself falls back,
# so a fresh host or a disaster rebuild is not stopped by a stale day: first to
# the installed region, then to our kept copy, then to a recent day.
if [ -n "$need_region" ] && [ -z "$from_keep" ] && [ -z "$explicit_build" ] && ! available "$PROTOMAPS_BUILD"; then
	installed=$(cat "$target/.region.source" 2>/dev/null || true)
	if [ -e "$target/region.pmtiles" ] && [ "${installed##* }" = "bbox=$BBOX" ]; then
		remind "the pinned build $PROTOMAPS_BUILD is gone; keeping the installed region ($installed)"
		REGION_STAMP="$installed"
		need_region=""
	elif [ "${kept_stamp##* }" = "bbox=$BBOX" ]; then
		remind "the pinned build $PROTOMAPS_BUILD is gone; installing the kept copy ($kept_stamp)"
		REGION_STAMP="$kept_stamp"
		from_keep=1
	else
		n=1
		found=""
		while [ "$n" -le "$FALLBACK_DAYS" ]; do
			day=$(days_ago "$n")
			[ -n "$day" ] || break
			if available "$day"; then
				found="$day"
				break
			fi
			n=$((n + 1))
		done
		if [ -n "$found" ]; then
			remind "the pinned build $PROTOMAPS_BUILD is gone; using $found instead"
			PROTOMAPS_BUILD="$found"
			REGION_STAMP="build=$PROTOMAPS_BUILD bbox=$BBOX"
		fi
	fi
fi

# Copy the installed region into the keep directory when the copy there is not
# of it. The stamp goes first and comes back last, so a copy cut short is never
# taken for a whole one. A failed copy is a note, never a failed run: the region
# itself is in place.
keep_copy() {
	[ -n "$keep" ] && [ -f "$target/region.pmtiles" ] || return 0
	installed=$(cat "$target/.region.source" 2>/dev/null || true)
	[ -n "$installed" ] && [ "$installed" != "$kept_stamp" ] || return 0
	rm -f "$keep/.region.source" "$keep/.region.pmtiles.part"
	if cp "$target/region.pmtiles" "$keep/.region.pmtiles.part" &&
		mv "$keep/.region.pmtiles.part" "$keep/region.pmtiles" &&
		printf '%s\n' "$installed" > "$keep/.region.source"; then
		kept_stamp="$installed"
		echo "kept a copy of the region in $keep: $installed"
	else
		rm -f "$keep/.region.pmtiles.part" "$keep/.region.source"
		kept_stamp=""
		echo "note: could not keep a copy of the region in $keep" >&2
	fi
}

if [ -z "$need_region" ] && [ -z "$need_assets" ]; then
	keep_copy
	echo "$target is current: $REGION_STAMP; $ASSETS_STAMP"
	exit 0
fi

mkdir "$work"
trap 'rm -rf "$work"' EXIT
trap 'exit 1' INT TERM HUP

fetch_checked() {
	# $1 url, $2 sha256, $3 output
	curl -fsSL --retry 3 -o "$3" "$1"
	actual=$(sha256sum "$3" | cut -d' ' -f1)
	if [ "$actual" != "$2" ]; then
		echo "checksum mismatch for $1: expected $2, got $actual" >&2
		exit 1
	fi
}

if [ -n "$need_assets" ]; then
	echo "fetching basemaps-assets $ASSETS_COMMIT"
	fetch_checked "$ASSETS_URL" "$ASSETS_SHA256" "$work/assets.tar.gz"
	mkdir "$work/assets"
	top="basemaps-assets-$ASSETS_COMMIT"
	tar -xzf "$work/assets.tar.gz" -C "$work/assets" --strip-components=1 \
		"$top/fonts" "$top/sprites/v4" "$top/README.md"
	mv "$work/assets/README.md" "$work/assets/sprites/README.md"
fi

if [ -n "$from_keep" ]; then
	# Verified with `pmtiles verify` when it was first extracted.
	echo "installing the region from the kept copy in $keep: $REGION_STAMP"
	cp "$keep/region.pmtiles" "$work/region.pmtiles"
elif [ -n "$need_region" ]; then
	case "$(uname -s)-$(uname -m)" in
		Linux-x86_64) ;;
		*) echo "the pinned pmtiles binary is Linux x86_64; this is $(uname -s)-$(uname -m)" >&2; exit 2 ;;
	esac
	echo "fetching go-pmtiles $PMTILES_VERSION"
	fetch_checked "$PMTILES_URL" "$PMTILES_SHA256" "$work/pmtiles.tar.gz"
	tar -xzf "$work/pmtiles.tar.gz" -C "$work" pmtiles
	source_url=$(build_url "$PROTOMAPS_BUILD")
	curl -fsSI "$source_url" >/dev/null || {
		echo "$source_url is not available; build.protomaps.com keeps recent days only," >&2
		echo "so name a newer build with --build YYYYMMDD" >&2
		exit 1
	}
	echo "extracting $BBOX from $source_url"
	"$work/pmtiles" extract "$source_url" "$work/region.pmtiles" --bbox="$BBOX"
	"$work/pmtiles" verify "$work/region.pmtiles"
fi

# Everything is downloaded, checked and unpacked; only renames from here.
if [ -n "$need_assets" ]; then
	chmod -R a+rX "$work/assets"
	for part in fonts sprites; do
		[ -e "$target/$part" ] && mv "$target/$part" "$work/old-$part"
		mv "$work/assets/$part" "$target/$part"
	done
	printf '%s\n' "$ASSETS_STAMP" > "$target/.assets.source"
fi
if [ -n "$need_region" ]; then
	chmod a+r "$work/region.pmtiles"
	mv "$work/region.pmtiles" "$target/region.pmtiles"
	printf '%s\n' "$REGION_STAMP" > "$target/.region.source"
fi
chmod a+r "$target"/.region.source "$target"/.assets.source 2>/dev/null || true
keep_copy

echo "basemap in $target: $REGION_STAMP; $ASSETS_STAMP"
