#!/usr/bin/env bash
# Build a tiny extract with the real valhalla_build_tiles and check that every
# bicycle closure reaches the tiles (tests/test_tile_build_access.py).
#
# Runs inside the pipeline image, which has Valhalla and osmium but no pytest,
# using a local image only (--pull never), with no network, a memory cap and a
# timeout. The repo is mounted read-only. The tiles go to a throwaway directory.
#
#   scripts/check_tile_build_access.sh [image]
#
# Exit 0: every closure held. 1: at least one case failed. 2: missing binaries.
set -euo pipefail

IMAGE="${1:-ghcr.io/macrophage87/routemaker-pipeline:dev}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tile-build-access.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

MSYS_NO_PATHCONV=1 timeout 600 docker run --rm --pull never \
  --memory=1g --memory-swap=1g --network none \
  --user "$(id -u):$(id -g)" \
  -v "$REPO:/repo:ro" -v "$WORK:/work" \
  -e TMPDIR=/work -e ROUTEMAKER_REQUIRE_TILE_BUILD=1 \
  --entrypoint /opt/venv/bin/python3 \
  "$IMAGE" /repo/tests/test_tile_build_access.py </dev/null
