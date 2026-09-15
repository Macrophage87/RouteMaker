#!/bin/sh
# Vendor Valhalla's own graph.lua at the pinned version.
#
# Pinned rather than read out of the image at runtime, so the tags a tile build
# produces are a function of this repository and not of whichever image tag
# happened to be pulled.
set -eu
PINNED="$(cat "$(dirname "$0")/../lua/vendor/VERSION" 2>/dev/null || echo 3.5.1)"
VERSION="${1:-$PINNED}"
DEST="$(dirname "$0")/../lua/vendor"
mkdir -p "$DEST"
curl -fsSL \
  "https://raw.githubusercontent.com/valhalla/valhalla/${VERSION}/lua/graph.lua" \
  -o "$DEST/graph_upstream.lua"
echo "vendored Valhalla ${VERSION} graph.lua to $DEST/graph_upstream.lua"

# The wrapper captures the globals this chunk installs; it is not a module.
# Catching a changed contract here is cheaper than catching it one way into a
# tile build.
for proc in ways_proc nodes_proc rels_proc; do
  grep -q "^function ${proc} " "$DEST/graph_upstream.lua" ||
    { echo "upstream graph.lua no longer defines ${proc}; lua/graph.lua needs updating" >&2; exit 1; }
done
printf '%s\n' "$VERSION" > "$DEST/VERSION"
