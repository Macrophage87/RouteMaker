"""Preset links (owner item 204): /<preset-id> on the edge opens the planner on
that ride type, by a redirect to `/#preset=<id>`.

Three things are held here. The Caddyfile's list of redirects equals the ride
types the front end offers (frontend/src/lib/presets.ts) and the API knows
(core/presets.py), no more and no fewer. No redirected path is a route anywhere
else - the Django URLconf, the admin path, or the Caddyfile's own prefixes. And,
where the pinned Caddy image is already present, the file is run: the redirect
is a 302 to the lowercase fragment link, case and a trailing slash included, and
everything else still goes where it went.
"""

from __future__ import annotations

import re
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
from django.urls import Resolver404, resolve

from core.presets import PRESETS

REPO = Path(__file__).resolve().parents[1]
CADDYFILE = (REPO / "Caddyfile").read_text()
FRONTEND_PRESETS = (REPO / "frontend" / "src" / "lib" / "presets.ts").read_text()


def caddy_redirects() -> dict[str, tuple[list[str], str, str]]:
    """Each `redir @preset-<id> <to> <status>` with the paths its matcher names."""
    matchers = {
        m.group(1): m.group(2).split()
        for m in re.finditer(r"^\s*@preset-(\S+) path (.+)$", CADDYFILE, re.M)
    }
    redirs = {
        m.group(1): (m.group(2), m.group(3))
        for m in re.finditer(r"^\s*redir @preset-(\S+) (\S+) (\d+)$", CADDYFILE, re.M)
    }
    assert set(matchers) == set(redirs), "a preset matcher without a redir, or the reverse"
    return {i: (matchers[i], *redirs[i]) for i in matchers}


def frontend_preset_ids() -> list[str]:
    """The ids in `PRESETS = [...]`, and the same set in the `PresetId` union."""
    options = re.findall(r'^\s{4}id: "([^"]+)",$', FRONTEND_PRESETS, re.M)
    union = re.search(r"export type PresetId =((?:\s*\|\s*\"[^\"]+\")+);", FRONTEND_PRESETS)
    assert union, "the PresetId union was not found"
    assert sorted(re.findall(r'"([^"]+)"', union.group(1))) == sorted(options)
    return options


def test_every_preset_has_a_redirect_and_there_are_no_extras() -> None:
    redirects = set(caddy_redirects())
    front = frontend_preset_ids()
    assert len(front) == len(set(front)) and front, front
    assert redirects == set(front), (
        f"missing {sorted(set(front) - redirects)}, extra {sorted(redirects - set(front))}"
    )
    assert redirects == set(PRESETS), (
        f"core/presets.py has {sorted(PRESETS)}; the Caddyfile has {sorted(redirects)}"
    )


def test_each_redirect_is_exact_and_a_302_to_the_fragment_link() -> None:
    for preset_id, (paths, target, status) in caddy_redirects().items():
        assert paths == [f"/{preset_id}", f"/{preset_id}/"], (preset_id, paths)
        assert target == f"/#preset={preset_id}", (preset_id, target)
        # Not 301/308: a browser keeps those for good, and the list is the owner's to change.
        assert status == "302", (preset_id, status)
    assert not re.search(r"^\s*@preset\S* path .*\*", CADDYFILE, re.M), "a wildcard preset matcher"


def test_no_preset_path_is_a_route_elsewhere() -> None:
    admin = settings.ADMIN_PATH.strip("/")
    for preset_id in caddy_redirects():
        for path in (f"/{preset_id}", f"/{preset_id}/", f"/{preset_id.upper()}"):
            with pytest.raises(Resolver404):
                resolve(path)
        assert preset_id != admin, f"the admin path {admin!r} is a preset id"
        # The Caddyfile's own prefixes, other than the app's `@frontend` paths.
        for prefix in ("static", "basemap", "assets", "api", "tiles", "auth", "healthz"):
            assert preset_id != prefix
    # And the app's own listed paths are not preset ids either.
    frontend = re.search(r"@frontend path (.+)", CADDYFILE)
    assert frontend
    names = {p.strip("/").split(".")[0] for p in frontend.group(1).split()}
    assert not names & set(caddy_redirects()), names


# --- the Caddyfile, run -----------------------------------------------------

IMAGE = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]["caddy"]["image"]
LOCAL_IMAGE = IMAGE.removeprefix("docker.io/library/")


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    probe = subprocess.run(
        ["docker", "image", "inspect", LOCAL_IMAGE], capture_output=True, stdin=subprocess.DEVNULL
    )
    return probe.returncode == 0


needs_caddy = pytest.mark.skipif(
    not docker_ready(), reason=f"needs a Docker daemon and {LOCAL_IMAGE} already present"
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102
        return None


def get(base: str, path: str) -> tuple[int, dict[str, str]]:
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(base + path, timeout=5) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers)


@needs_caddy
def test_caddy_validates_the_caddyfile() -> None:
    out = subprocess.run(
        [
            "docker", "run", "--rm", "--label", "rm-test=preset-links",
            "-e", "CADDY_SITE_ADDRESS=:80",
            "-v", f"{REPO / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
            LOCAL_IMAGE, "caddy", "validate", "--config", "/etc/caddy/Caddyfile",
        ],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr[-2000:]


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    root = tmp_path_factory.mktemp("preset-links")
    frontend = root / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_bytes(b"<!doctype html><title>RouteMaker</title>")
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    name = f"rm-test-preset-links-{uuid.uuid4().hex[:8]}"
    try:
        subprocess.run(
            [
                "docker", "run", "-d", "--name", name, "--label", "rm-test=preset-links",
                "-p", "127.0.0.1::80", "-e", "CADDY_SITE_ADDRESS=:80",
                "-v", f"{REPO / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
                "-v", f"{frontend}:/srv/frontend:ro",
                LOCAL_IMAGE,
            ],
            check=True, capture_output=True, stdin=subprocess.DEVNULL,
        )  # fmt: skip
        mapped = subprocess.run(
            ["docker", "port", name, "80/tcp"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )  # fmt: skip
        base = f"http://127.0.0.1:{int(mapped.stdout.split()[0].rsplit(':', 1)[1])}"
        deadline = time.monotonic() + 20
        while True:
            try:
                get(base, "/")
                break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail("caddy never answered")
                time.sleep(0.2)
        yield base
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, stdin=subprocess.DEVNULL)


@needs_caddy
@pytest.mark.parametrize("preset_id", sorted(PRESETS))
def test_a_preset_path_redirects_to_the_fragment_link(edge, preset_id) -> None:
    for path in (
        f"/{preset_id}",
        f"/{preset_id}/",
        f"/{preset_id.upper()}",
        f"/{preset_id.title()}/",
    ):
        status, headers = get(edge, path)
        assert status == 302, (path, status)
        assert headers["Location"] == f"/#preset={preset_id}", (path, headers)
        assert "Strict-Transport-Security" in headers  # the site-wide header is kept


@needs_caddy
@pytest.mark.parametrize(
    "path",
    [
        "/trailmaxxing/x", "/trailmaxxing.html", "/trailmaxxing2", "/trailmax", "/ebikes",
        "/api/trailmaxxing", "/api/", "/api/routes", "/tiles/stress/14/4700/6300.pbf",
        "/auth/login", "/healthz", f"/{settings.ADMIN_PATH}", "/unknown",
    ],
)  # fmt: skip
def test_nothing_else_is_redirected(edge, path) -> None:
    """No api container, so reaching the proxy is a 502."""
    status, headers = get(edge, path)
    assert status == 502, (path, status)
    assert "Location" not in headers


@needs_caddy
def test_the_apps_own_paths_are_unchanged(edge) -> None:
    assert get(edge, "/")[0] == 200
    assert get(edge, "/index.html")[0] == 200
    assert get(edge, "/static/x.css")[0] == 404
    assert get(edge, "/basemap/region.pmtiles")[0] == 403
