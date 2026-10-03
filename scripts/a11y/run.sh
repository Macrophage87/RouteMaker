#!/usr/bin/env bash
# The a11y browser check (scripts/a11y/check.mjs), offline: Vite in node:22 and
# Chromium from the Playwright image, sharing one loopback-only network
# namespace (--network none); the API is mocked in the page over CDP.
#
#   scripts/a11y/run.sh NODE_MODULES_DIR [SHOTS_DIR]
#
# NODE_MODULES_DIR is a frontend node_modules installed from this lockfile. Vite
# writes its caches into node_modules and next to its config, so it runs on a
# copy of the frontend (and of NODE_MODULES_DIR) under $TMPDIR; the source tree
# and NODE_MODULES_DIR are only read. One browser at a time: the containers and
# the copy are removed at the end.
set -euo pipefail
here="$(cd "$(dirname "$0")/../.." && pwd)"
modules="${1:?a frontend node_modules directory}"
shots="${2:-$here/.a11y-shots}"
mkdir -p "$shots"
NODE_IMAGE="node@sha256:363e1587494626837fa7f9a23bdb453d13b0ff3c67c705c2805cfc69c2d2fad7"
CHROME_IMAGE="mcr.microsoft.com/playwright/python@sha256:678457c4c323b981d8b4befc57b95366bb1bb6aa30057b1269f6b171e8d9975a"
name="a11ycheck-$$"
work="$(mktemp -d "${TMPDIR:-/tmp}/a11ycheck.XXXXXX")"
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then docker logs "$name-vite" 2>&1 | tail -20 || true; fi
  docker rm -f "$name-chrome" "$name-vite" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

mkdir -p "$work/frontend" "$work/scripts"
(cd "$here/frontend" && tar --exclude=./node_modules --exclude=./dist -cf - .) | tar -xf - -C "$work/frontend"
cp -a "$here/scripts/a11y" "$work/scripts/"
cp -a "$modules" "$work/frontend/node_modules"

# -i: Vite stops when its stdin ends.
docker run -d -i --name "$name-vite" --network none -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$work:/w" -v "$shots:/shots" -w /w/frontend "$NODE_IMAGE" \
  node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort >/dev/null
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Running}}' "$name-vite")" = true ] || { echo "Vite stopped" >&2; exit 1; }
  docker exec "$name-vite" node -e 'fetch("http://127.0.0.1:5173/").then(r=>process.exit(r.ok?0:1),()=>process.exit(1))' && break
  sleep 1
done
docker run -d --name "$name-chrome" --network "container:$name-vite" --shm-size 512m "$CHROME_IMAGE" \
  /ms-playwright/chromium-1208/chrome-linux64/chrome --headless=new --no-sandbox --disable-gpu \
  --use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir=/tmp/chrome about:blank >/dev/null
docker exec "$name-vite" node /w/scripts/a11y/check.mjs --shots /shots
