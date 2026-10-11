#!/usr/bin/env bash
# Tests and builds the beta front end the one way every beta path does: ship-data.sh
# --build-frontend at home, the release agent (auto-release.sh) on the server, and CI.
#
#   scripts/beta/frontend-build.sh [--docker-opt OPT]... REPO NODE_MODULES OUT [REPORT_URL]
#   scripts/beta/frontend-build.sh --print-image
#
#   REPO          a checkout (or exported tree) of the release; its front end is REPO/frontend
#   NODE_MODULES  node_modules for REPO/frontend/package-lock.json, installed for Linux x64
#   OUT           where the built front end goes (emptied first)
#   REPORT_URL    the beta notice's "Report a problem" link (VITE_BETA_REPORT_URL), or nothing
#   --docker-opt  an extra `docker run` option, such as --memory 1536m (repeatable)
#   --print-image print the pinned node image and stop (CI pulls it with this)
#
# The pinned node image, no network, VITE_BETA=1: npm test, tsc --noEmit, vite build. The whole
# tree is mounted read-only at /repo, not frontend/ alone: front-end tests read files beside it
# (src/routemaker/avoid_junctions.py for the API's wording, scripts/build_contours.py for the
# topo layers). The mounts live here, once, and CI runs this script, so a build that cannot see
# what its tests read fails in CI, not mid-ship.
# Environment: DOCKER, the docker command [docker].
set -euo pipefail

NODE_IMAGE="docker.io/library/node@sha256:363e1587494626837fa7f9a23bdb453d13b0ff3c67c705c2805cfc69c2d2fad7"

die() { echo "frontend-build: $*" >&2; exit 2; }

opts=()
while [ $# -gt 0 ]; do
	case "$1" in
		--print-image) echo "$NODE_IMAGE"; exit 0 ;;
		--docker-opt) [ $# -ge 2 ] || die "$1 needs a value"; opts+=("$2"); shift 2 ;;
		--) shift; break ;;
		-*) die "unknown option $1" ;;
		*) break ;;
	esac
done
[ $# -ge 3 ] && [ $# -le 4 ] || die "give REPO NODE_MODULES OUT [REPORT_URL]"
repo=$1 nm=$2 out=$3 report_url=${4:-}

[ -d "$repo/frontend" ] || die "no frontend/ in $repo"
[ -d "$nm" ] || die "no node_modules at $nm; the build runs offline"

# node_modules installed for another platform: Windows npm (WSL with no Linux node finds the
# Windows one on PATH) installs only the win32 native bindings, and the tests then die on a
# missing linux-x64 binding. A scope that has a win32 or darwin binding and no linux-x64 one
# was not installed for this image.
for scope in "$nm"/@*/; do
	[ -d "$scope" ] || continue
	foreign=$(find "$scope" -mindepth 1 -maxdepth 1 \( -name '*win32*' -o -name '*darwin*' \) -print -quit)
	[ -n "$foreign" ] || continue
	native=$(find "$scope" -mindepth 1 -maxdepth 1 -name '*linux-x64*' -print -quit)
	[ -n "$native" ] ||
		die "$nm was installed for another platform ($(basename "$scope")$(basename "$foreign") and no linux-x64 binding; Windows npm?). Reinstall it in the pinned image: docker run --rm -u \"\$(id -u):\$(id -g)\" -e HOME=/tmp -v \"$repo/frontend:/app\" -w /app $NODE_IMAGE npm ci"
done

mkdir -p "$out"
# The mount point for node_modules inside the read-only source (docker cannot make it there).
mkdir -p "$repo/frontend/node_modules"
# node_modules is mounted writable because vite writes a temp config beside it; it is removed
# afterwards. A failed test, type check or build fails the whole run, and nothing is built.
status=0
"${DOCKER:-docker}" run --rm --pull never --network none -u "$(id -u):$(id -g)" -e HOME=/tmp \
	-e VITE_BETA=1 -e VITE_BETA_REPORT_URL="$report_url" "${opts[@]}" \
	-v "$repo:/repo:ro" -v "$nm:/repo/frontend/node_modules" -v "$out:/out" -w /repo/frontend \
	"$NODE_IMAGE" sh -c 'umask 022 && npm test && npx tsc --noEmit && npx vite build --outDir /out --emptyOutDir' </dev/null || status=$?
rm -rf "$nm/.vite-temp"
[ "$status" = 0 ] || exit "$status"
[ -f "$out/index.html" ] || die "the build made no index.html"
