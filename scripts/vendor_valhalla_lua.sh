#!/bin/sh
# Vendor Valhalla's own graph.lua and config generator at the pinned version.
#
# Pinned rather than read out of the image at runtime, so the tags a tile build
# produces are a function of this repository and not of whichever image tag
# happened to be pulled.
#
# Both files are downloaded to a scratch directory and checked there; only a
# download that passes moves into place, so a failed check leaves the vendored
# copies and their VERSION as they were. Re-vendoring the pinned version must
# reproduce the recorded sha256 (lua/vendor/SHA256SUMS, valhalla/vendor/SHA256SUMS,
# which tests/test_lua_remap.py also checks); a new version records new ones, to
# be read in the diff. The supported-key list and the service configs are then
# regenerated from the new files.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PINNED="$(cat "$ROOT/lua/vendor/VERSION" 2>/dev/null || echo 3.9.1)"
VERSION="${1:-$PINNED}"
LUA_DEST="$ROOT/lua/vendor"
CONFIG_DEST="$ROOT/valhalla/vendor"
BASE="https://raw.githubusercontent.com/valhalla/valhalla/${VERSION}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

curl -fsSL "$BASE/lua/graph.lua" -o "$WORK/graph_upstream.lua"
curl -fsSL "$BASE/scripts/valhalla_build_config" -o "$WORK/valhalla_build_config.py"

# The wrapper captures the globals this chunk installs; it is not a module.
# Catching a changed contract here is cheaper than catching it one way into a
# tile build.
for proc in ways_proc nodes_proc rels_proc; do
  grep -q "^function ${proc} " "$WORK/graph_upstream.lua" ||
    { echo "upstream graph.lua no longer defines ${proc}; lua/graph.lua needs updating" >&2; exit 1; }
done

check_sum() { # file, sums file: the pinned version must reproduce its recorded hash
  if [ "$VERSION" = "$PINNED" ] && [ -f "$2" ]; then
    expected="$(awk -v f="$(basename "$1")" '$2 == f { print $1 }' "$2")"
    actual="$(sha256sum "$1" | awk '{ print $1 }')"
    if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
      echo "$(basename "$1") at ${VERSION} does not match $2 (got ${actual})" >&2
      exit 1
    fi
  fi
}
check_sum "$WORK/graph_upstream.lua" "$LUA_DEST/SHA256SUMS"
check_sum "$WORK/valhalla_build_config.py" "$CONFIG_DEST/SHA256SUMS"

mkdir -p "$LUA_DEST" "$CONFIG_DEST"
mv "$WORK/graph_upstream.lua" "$LUA_DEST/graph_upstream.lua"
mv "$WORK/valhalla_build_config.py" "$CONFIG_DEST/valhalla_build_config.py"
(cd "$LUA_DEST" && sha256sum graph_upstream.lua > SHA256SUMS)
(cd "$CONFIG_DEST" && sha256sum valhalla_build_config.py > SHA256SUMS)
printf '%s\n' "$VERSION" > "$LUA_DEST/VERSION"
printf '%s\n' "$VERSION" > "$CONFIG_DEST/VERSION"
echo "vendored Valhalla ${VERSION} graph.lua and valhalla_build_config"

python3 "$ROOT/scripts/extract_valhalla_keys.py"
python3 "$ROOT/scripts/build_valhalla_configs.py"
