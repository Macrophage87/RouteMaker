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
#     sprites/v4/<flavor>.json|.png|@2x.*
#                           the sprites, from the same commit
#     .region.source, .assets.source
#                           what each was made from; a run whose pins match
#                           these, with the files present, does nothing
#
# Every input is pinned below. The pmtiles binary and the assets archive are
# checked against a sha256 before anything is unpacked, and a mismatch installs
# nothing. The region is not checksummed, because there is nothing to check it
# against - Protomaps publishes no digest for a daily build and an extract is
# a new file - so `pmtiles verify` is run on it instead before it is moved in.
#
# Usage, from the repository root, as the owner of ${DATA_ROOT}/basemap
# (scripts/prepare_data_root.sh creates it and hands it to uid 10001):
#
#     sudo -u '#10001' env DATA_ROOT=<DATA_ROOT> sh scripts/fetch_basemap.sh
#     sudo -u '#10001' env DATA_ROOT=<DATA_ROOT> sh scripts/fetch_basemap.sh --build 20261026
#
# The path is given rather than `--env-file ./.env` in that form because the
# env file holds every secret the stack has and uid 10001 has no business
# reading it; `--env-file` is there for a caller who owns both.
#
# `--build` overrides PROTOMAPS_BUILD for one run. build.protomaps.com keeps
# daily builds for a limited time only, so a pin older than that is a 404 and
# the refresh is to name a newer day (docs/OPERATIONS.md, "The base map").
# Needs curl, tar, sha256sum and an x86_64 Linux host (the pinned binary).
#
# Nothing here touches the running stack: Caddy reads the files on each
# request, so a replaced region.pmtiles is served on the next one. The files
# are made world-readable, since the edge reads them as its own uid.

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
# settings.COVERAGE_BBOX, west,south,east,north; tests/test_basemap.py holds
# the two equal.
BBOX="-78.0,38.2,-76.02,39.72"

usage() {
	echo "usage: fetch_basemap.sh [--env-file <path>] [--build YYYYMMDD] [--print-stamps]" >&2
	exit 2
}

env_file=""
print_stamps=""
while [ $# -gt 0 ]; do
	case "$1" in
		--env-file)
			[ $# -ge 2 ] || usage
			env_file="$2"
			shift 2
			;;
		--build)
			[ $# -ge 2 ] || usage
			PROTOMAPS_BUILD="$2"
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

if [ -n "$env_file" ]; then
	# The same reading of compose's env file as scripts/prepare_data_root.sh:
	# the last uncommented DATA_ROOT line, a trailing CR and one pair of
	# quotes removed, nothing evaluated.
	[ -r "$env_file" ] || { echo "cannot read env file '$env_file'" >&2; exit 2; }
	value=$(sed -n 's/^[[:space:]]*DATA_ROOT[[:space:]]*=//p' "$env_file" | tail -n 1)
	value=$(printf '%s' "$value" | tr -d '\r')
	case "$value" in
		\'*\') value=$(printf '%s' "$value" | sed "s/^'//; s/'\$//") ;;
		'"'*'"') value=$(printf '%s' "$value" | sed 's/^"//; s/"$//') ;;
	esac
	[ -n "$value" ] || { echo "no DATA_ROOT= line in '$env_file'" >&2; exit 2; }
	DATA_ROOT="$value"
fi

: "${DATA_ROOT:?DATA_ROOT is not set. Pass --env-file ./.env, or export DATA_ROOT yourself}"
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

current() {
	# $1 stamp file, $2 expected stamp, $3... paths that must exist
	stamp_file="$1"
	expected="$2"
	shift 2
	[ -f "$target/$stamp_file" ] || return 1
	[ "$(cat "$target/$stamp_file")" = "$expected" ] || return 1
	for path in "$@"; do
		[ -e "$target/$path" ] || return 1
	done
	return 0
}

need_region=1
need_assets=1
current .region.source "$REGION_STAMP" region.pmtiles && need_region=""
current .assets.source "$ASSETS_STAMP" fonts sprites && need_assets=""

if [ -z "$need_region" ] && [ -z "$need_assets" ]; then
	echo "$target is current: $REGION_STAMP; $ASSETS_STAMP"
	exit 0
fi

# Inside the target, so every move into place is a rename on one filesystem.
# The Caddyfile serves only region.pmtiles, fonts/ and sprites/, so neither
# this directory nor the stamps are ever reachable from outside.
work="$target/.work"
rm -rf "$work"
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
	tar -xzf "$work/assets.tar.gz" -C "$work/assets" --strip-components=1 \
		"basemaps-assets-$ASSETS_COMMIT/fonts" "basemaps-assets-$ASSETS_COMMIT/sprites/v4"
fi

if [ -n "$need_region" ]; then
	case "$(uname -s)-$(uname -m)" in
		Linux-x86_64) ;;
		*) echo "the pinned pmtiles binary is Linux x86_64; this is $(uname -s)-$(uname -m)" >&2; exit 2 ;;
	esac
	echo "fetching go-pmtiles $PMTILES_VERSION"
	fetch_checked "$PMTILES_URL" "$PMTILES_SHA256" "$work/pmtiles.tar.gz"
	tar -xzf "$work/pmtiles.tar.gz" -C "$work" pmtiles
	source_url="https://build.protomaps.com/$PROTOMAPS_BUILD.pmtiles"
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

echo "basemap in $target: $REGION_STAMP; $ASSETS_STAMP"
