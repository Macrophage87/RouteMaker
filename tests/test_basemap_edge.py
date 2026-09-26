"""The /basemap/* route, run: the repository's Caddyfile in the pinned Caddy.

tests/test_basemap.py reads the Caddyfile's text, which says which directives
are there and nothing about what the same-origin expression decides - an
inverted comparison or a `startsWith` turned into `contains` reads almost the
same. So the file is run here, in the same caddy image compose pins, against
a small basemap directory made for the test, and the answers are read off real
responses. Both site postures are run: `:80` (plain HTTP, what a local stack
uses) and a hostname over TLS (Caddy's internal CA for `localhost`), because
`{scheme}` is only exercised when the two differ.

Skipped, not failed, where there is no Docker daemon or the image is not
already present: this pulls nothing.
"""

from __future__ import annotations

import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
IMAGE = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]["caddy"]["image"]
LOCAL_IMAGE = IMAGE.removeprefix("docker.io/library/")

# Bytes that are not a real archive but are distinct at every offset, so a
# range that returns the wrong slice cannot compare equal by accident.
REGION = bytes((i * 7 + i // 251) % 256 for i in range(64 * 1024))
FONT = b"glyphs " * 100
SPRITE = b'{"sprite": "light"}'

# One of each of the contract's three kinds.
SERVED = (
    "/basemap/region.pmtiles",
    "/basemap/fonts/Noto%20Sans%20Regular/0-255.pbf",
    "/basemap/sprites/v4/light.json",
)


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


class Edge:
    def __init__(self, scheme: str, host: str, port: int) -> None:
        self.scheme, self.host, self.port = scheme, host, port
        self.site = f"{scheme}://{host}:{port}"
        self.context = ssl.create_default_context()
        self.context.check_hostname = False
        self.context.verify_mode = ssl.CERT_NONE

    def get(self, path: str, **headers: str) -> tuple[int, dict[str, str], bytes]:
        request = urllib.request.Request(
            f"{self.site}{path}", headers={k.replace("_", "-"): v for k, v in headers.items()}
        )
        try:
            with urllib.request.urlopen(request, timeout=5, context=self.context) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as refused:
            return refused.code, dict(refused.headers), refused.read()


def basemap_dir(root: Path) -> Path:
    basemap = root / "basemap"
    (basemap / "fonts" / "Noto Sans Regular").mkdir(parents=True)
    (basemap / "sprites" / "v4").mkdir(parents=True)
    (basemap / "region.pmtiles").write_bytes(REGION)
    (basemap / "fonts" / "Noto Sans Regular" / "0-255.pbf").write_bytes(FONT)
    (basemap / "sprites" / "v4" / "light.json").write_bytes(SPRITE)
    (basemap / ".region.source").write_text("build=20260926\n")
    (basemap / ".work").mkdir()
    (basemap / ".work" / "partial").write_text("half an archive")
    for path in [basemap, *basemap.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    return basemap


@pytest.fixture(scope="module", params=["http", "https"])
def edge(request, tmp_path_factory):
    scheme = request.param
    basemap = basemap_dir(tmp_path_factory.mktemp(f"edge-{scheme}"))
    name = f"rm-test-basemap-edge-{uuid.uuid4().hex[:8]}"
    port_inside = "80" if scheme == "http" else "443"
    address = ":80" if scheme == "http" else "localhost"

    def logs() -> str:
        out = subprocess.run(
            ["docker", "logs", name], capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        return out.stdout + out.stderr

    try:
        # Inside the try: a run that fails after creating the container still
        # leaves one behind, and the finally removes it.
        subprocess.run(
            [
                "docker", "run", "-d", "--name", name, "--label", "rm-test=basemap-edge",
                "-p", f"127.0.0.1::{port_inside}",
                "-e", f"CADDY_SITE_ADDRESS={address}",
                "-v", f"{REPO / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
                "-v", f"{basemap}:/srv/basemap:ro",
                LOCAL_IMAGE,
            ],
            check=True, capture_output=True, stdin=subprocess.DEVNULL,
        )  # fmt: skip
        mapped = subprocess.run(
            ["docker", "port", name, f"{port_inside}/tcp"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )  # fmt: skip
        if mapped.returncode != 0 or not mapped.stdout.split():
            pytest.fail(f"caddy published no port ({mapped.stderr.strip()}): {logs()}")
        port = int(mapped.stdout.split()[0].rsplit(":", 1)[1])
        served = Edge(scheme, "127.0.0.1" if scheme == "http" else "localhost", port)
        deadline = time.monotonic() + 20
        while True:
            try:
                served.get("/basemap/region.pmtiles", Referer=served.site + "/")
                break
            except (OSError, ssl.SSLError):
                if time.monotonic() > deadline:
                    pytest.fail(f"caddy never answered: {logs()}")
                time.sleep(0.2)
        yield served
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, stdin=subprocess.DEVNULL)


def test_a_same_site_origin_gets_the_named_bytes(edge) -> None:
    status, headers, body = edge.get(
        "/basemap/region.pmtiles", Origin=edge.site, Range="bytes=1000-1999"
    )
    assert status == 206, (status, headers)
    assert body == REGION[1000:2000]
    assert headers.get("Content-Range") == f"bytes 1000-1999/{len(REGION)}"


def test_a_same_site_referer_gets_the_named_bytes(edge) -> None:
    """What a browser actually sends on a same-origin GET: no Origin, the page
    as Referer."""
    status, _, body = edge.get(
        "/basemap/region.pmtiles", Referer=f"{edge.site}/map", Range="bytes=0-126"
    )
    assert status == 206
    assert body == REGION[:127]


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(lambda site: {}, id="neither header"),
        pytest.param(lambda site: {"Origin": "https://evil.example"}, id="foreign origin"),
        pytest.param(
            lambda site: {"Origin": "https://evil.example", "Referer": site + "/"},
            id="foreign origin with our referer",
        ),
        pytest.param(lambda site: {"Referer": "https://evil.example/"}, id="foreign referer"),
        pytest.param(lambda site: {"Referer": site + ".evil.example/"}, id="lookalike host"),
        pytest.param(lambda site: {"Referer": site + "0/"}, id="lookalike port"),
        pytest.param(
            lambda site: {"Referer": f"https://evil.example/?{site}/"}, id="embedded referer"
        ),
        pytest.param(lambda site: {"Origin": site + ".evil.example"}, id="lookalike origin"),
    ],
)
def test_anything_else_is_refused_and_not_cached(edge, headers) -> None:
    for path in SERVED:
        status, response, body = edge.get(path, Range="bytes=0-126", **headers(edge.site))
        assert status == 403, (path, status)
        assert not any(part[:16] in body for part in (REGION, FONT, SPRITE))
        # A refusal cached for a day would leave a page of ours that lost its
        # Referer once broken for that day.
        assert "no-store" in response.get("Cache-Control", ""), (path, response)


@pytest.mark.parametrize("path", ["/basemap/.region.source", "/basemap/.work/partial"])
def test_the_scripts_own_files_are_not_served(edge, path) -> None:
    status, _, body = edge.get(path, Referer=edge.site + "/")
    assert status == 404, status
    assert b"build=" not in body and b"half an archive" not in body


@pytest.mark.parametrize("path", SERVED)
def test_what_is_served_is_kept_out_of_shared_caches(edge, path) -> None:
    """The answer depends on Origin and Referer, which a shared cache does not
    key on, so it must not hold one."""
    status, headers, _ = edge.get(path, Referer=edge.site + "/")
    assert status == 200
    assert "private" in headers.get("Cache-Control", ""), headers


def test_the_archive_is_revalidated_on_every_use(edge) -> None:
    """A refresh replaces region.pmtiles under the same name. A browser that
    reused cached ranges of the old archive against a directory read from the
    new one would decode garbage, so every use revalidates (a 304 is cheap)."""
    status, headers, _ = edge.get("/basemap/region.pmtiles", Referer=edge.site + "/")
    assert status == 200
    assert "no-cache" in headers.get("Cache-Control", ""), headers
