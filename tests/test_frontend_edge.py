"""The front end's routes at the edge, run: the repository's Caddyfile in the
pinned Caddy, against a small built-app directory made for the test.

What is checked is what the SHARED API CONTRACT asks of the edge: the
single-page app at /, and /api/*, /tiles/*, /auth/*, the admin path, /healthz
and /static/* still going where they went. There is no api container here, so
a path that reaches the proxy answers 502 - which is exactly what tells it
apart from the app's file server (200, or 404 for a file the build lacks).

Skipped, not failed, where there is no Docker daemon or the image is not
already present: this pulls nothing.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest
import yaml
from django.conf import settings

REPO = Path(__file__).resolve().parents[1]
IMAGE = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]["caddy"]["image"]
LOCAL_IMAGE = IMAGE.removeprefix("docker.io/library/")

INDEX = b"<!doctype html><title>RouteMaker</title><div id=root></div>"
SCRIPT = b"console.log('app')"
STATIC = b"body{}"


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    probe = subprocess.run(
        ["docker", "image", "inspect", LOCAL_IMAGE], capture_output=True, stdin=subprocess.DEVNULL
    )
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not docker_ready(), reason=f"needs a Docker daemon and {LOCAL_IMAGE} already present"
)


def get(base: str, path: str) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(base + path)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), refused.read()


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    root = tmp_path_factory.mktemp("frontend-edge")
    frontend = root / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_bytes(INDEX)
    (frontend / "favicon.svg").write_bytes(b"<svg/>")
    (frontend / "assets" / "index-abc123.js").write_bytes(SCRIPT)
    static = root / "static"
    (static / "admin").mkdir(parents=True)
    (static / "admin" / "base.css").write_bytes(STATIC)
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)

    name = f"rm-test-frontend-edge-{uuid.uuid4().hex[:8]}"

    def logs() -> str:
        out = subprocess.run(
            ["docker", "logs", name], capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        return out.stdout + out.stderr

    try:
        subprocess.run(
            [
                "docker", "run", "-d", "--name", name, "--label", "rm-test=frontend-edge",
                "-p", "127.0.0.1::80",
                "-e", "CADDY_SITE_ADDRESS=:80",
                "-v", f"{REPO / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
                "-v", f"{frontend}:/srv/frontend:ro",
                "-v", f"{static}:/srv/static:ro",
                LOCAL_IMAGE,
            ],
            check=True, capture_output=True, stdin=subprocess.DEVNULL,
        )  # fmt: skip
        mapped = subprocess.run(
            ["docker", "port", name, "80/tcp"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )  # fmt: skip
        if mapped.returncode != 0 or not mapped.stdout.split():
            pytest.fail(f"caddy published no port ({mapped.stderr.strip()}): {logs()}")
        base = f"http://127.0.0.1:{int(mapped.stdout.split()[0].rsplit(':', 1)[1])}"
        deadline = time.monotonic() + 20
        while True:
            try:
                get(base, "/favicon.svg")
                break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail(f"caddy never answered: {logs()}")
                time.sleep(0.2)
        yield base
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, stdin=subprocess.DEVNULL)


def test_the_app_is_served_at_the_root(edge) -> None:
    status, headers, body = get(edge, "/")
    assert status == 200, (status, headers)
    assert body == INDEX
    # Revalidated on every load, so a deploy is seen at once.
    assert "no-cache" in headers.get("Cache-Control", ""), headers
    status, _, body = get(edge, "/index.html")
    assert (status, body) == (200, INDEX)


def test_the_app_keeps_the_referer_the_basemap_guard_needs(edge) -> None:
    """MapLibre fetches the archive, glyphs and sprites on the page's thread,
    and /basemap/* refuses a request whose Referer is not a page on this site.
    `no-referrer` (or any policy that strips a same-origin Referer) would blank
    the map."""
    _, headers, _ = get(edge, "/")
    policy = headers.get("Referrer-Policy", "")
    assert policy, "the app is served without a Referrer-Policy"
    assert policy in {
        "same-origin",
        "strict-origin-when-cross-origin",
        "origin-when-cross-origin",
    }, f"Referrer-Policy {policy!r} does not send the full same-origin Referer"


def test_hashed_assets_are_cached_for_good(edge) -> None:
    status, headers, body = get(edge, "/assets/index-abc123.js")
    assert (status, body) == (200, SCRIPT)
    control = headers.get("Cache-Control", "")
    assert "immutable" in control and "max-age=31536000" in control, control
    assert headers.get("X-Content-Type-Options") == "nosniff"


def test_a_missing_asset_is_the_file_servers_404_not_the_api(edge) -> None:
    status, _, _ = get(edge, "/assets/gone.js")
    assert status == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/route",
        "/api/openapi.json",
        "/tiles/stress/12/1171/1566.pbf",
        "/auth/login",
        "/auth/callback",
        "/healthz",
        f"/{settings.ADMIN_PATH}",
        f"/{settings.ADMIN_PATH}core/scheduledrun/",
        "/some/unknown/path",
    ],
)
def test_everything_else_still_reaches_the_api(edge, path) -> None:
    """No api container is running, so reaching the proxy is a 502."""
    status, _, _ = get(edge, path)
    assert status == 502, f"{path} answered {status}, so it did not reach the api proxy"


def test_static_is_still_served_from_the_collected_assets(edge) -> None:
    status, _, body = get(edge, "/static/admin/base.css")
    assert (status, body) == (200, STATIC)
