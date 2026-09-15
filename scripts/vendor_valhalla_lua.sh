#!/bin/sh
# Vendor Valhalla's own graph.lua at the pinned version.
#
# Pinned rather than read out of the image at runtime, so the tags a tile build
# produces are a function of this repository and not of whichever image tag
# happened to be pulled.
set -eu
VERSION="${1:-3.5.1}"
DEST="$(dirname "$0")/../lua/vendor"
mkdir -p "$DEST"
curl -fsSL \
  "https://raw.githubusercontent.com/valhalla/valhalla/${VERSION}/lua/graph.lua" \
  -o "$DEST/graph_upstream.lua"
echo "vendored Valhalla ${VERSION} graph.lua to $DEST/graph_upstream.lua"
