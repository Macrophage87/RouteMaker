"""The stress tiles at the edge, run: the repository's Caddyfile in the pinned
Caddy, in front of a stand-in api (a second Caddy answering as `api:8000`).

What is checked is what the Caddyfile adds for /tiles/*: a vector tile is
compressed for a client that asks, keeps its ETag so a revalidation still
reaches the API's 304, and nothing else the API answers is encoded.

Skipped, not failed, where there is no Docker daemon or the image is not
already present: this pulls nothing.
"""

from __future__ import annotations

import gzip
import subprocess
import time
import uuid

import pytest
from test_frontend_edge import LOCAL_IMAGE, REPO, docker_ready, get

pytestmark = pytest.mark.skipif(
    not docker_ready(), reason=f"needs a Docker daemon and {LOCAL_IMAGE} already present"
)

# Longer than Caddy's minimum_length (512 bytes), so size is not why a
# response goes unencoded.
BODY = "stress " * 200
ETAG = 'W/"stress-1-v1"'

STUB = f"""
:8000 {{
	@tile path /tiles/*
	header @tile Content-Type application/vnd.mapbox-vector-tile
	header @tile ETag `{ETAG}`
	respond @tile "{BODY}" 200
	header /api/* Content-Type application/json
	respond /api/* "{BODY}" 200
}}
"""


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, stdin=subprocess.DEVNULL)


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    root = tmp_path_factory.mktemp("tiles-edge")
    stub = root / "Caddyfile"
    stub.write_text(STUB)
    stub.chmod(0o644)
    root.chmod(0o755)
    tag = uuid.uuid4().hex[:8]
    network = f"rm-test-tiles-edge-{tag}"
    upstream, name = f"{network}-api", f"{network}-caddy"
    try:
        _run("docker", "network", "create", "--label", "rm-test=tiles-edge", network)
        started = _run(
            "docker", "run", "-d", "--name", upstream, "--label", "rm-test=tiles-edge",
            "--network", network, "--network-alias", "api",
            "-v", f"{stub}:/etc/caddy/Caddyfile:ro", LOCAL_IMAGE,
        )  # fmt: skip
        assert started.returncode == 0, started.stderr
        started = _run(
            "docker", "run", "-d", "--name", name, "--label", "rm-test=tiles-edge",
            "--network", network, "-p", "127.0.0.1::80", "-e", "CADDY_SITE_ADDRESS=:80",
            "-v", f"{REPO / 'Caddyfile'}:/etc/caddy/Caddyfile:ro", LOCAL_IMAGE,
        )  # fmt: skip
        assert started.returncode == 0, started.stderr
        mapped = _run("docker", "port", name, "80/tcp")
        base = f"http://127.0.0.1:{int(mapped.stdout.split()[0].rsplit(':', 1)[1])}"
        deadline = time.monotonic() + 20
        while True:
            try:
                if get(base, "/tiles/stress/14/1/1.pbf")[0] == 200:
                    break
            except OSError:
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"the edge never reached the stand-in: {_run('docker', 'logs', name)}")
            time.sleep(0.2)
        yield base
    finally:
        _run("docker", "rm", "-f", name, upstream)
        _run("docker", "network", "rm", network)


def test_a_tile_is_compressed_for_a_client_that_asks(edge) -> None:
    status, headers, body = get(edge, "/tiles/stress/14/1/1.pbf", Accept_Encoding="gzip")
    assert status == 200
    assert headers.get("Content-Encoding") == "gzip", headers
    assert gzip.decompress(body).decode() == BODY
    assert "Accept-Encoding" in headers.get("Vary", ""), headers


def test_the_etag_survives_so_a_revalidation_still_matches(edge) -> None:
    _, headers, _ = get(edge, "/tiles/stress/14/1/1.pbf", Accept_Encoding="gzip")
    assert headers.get("Etag") == ETAG, headers


def test_a_client_that_does_not_ask_gets_the_tile_as_is(edge) -> None:
    status, headers, body = get(edge, "/tiles/stress/14/1/1.pbf")
    assert (status, body.decode()) == (200, BODY)
    assert "Content-Encoding" not in headers, headers


def test_nothing_else_the_api_answers_is_encoded(edge) -> None:
    status, headers, _ = get(edge, "/api/openapi.json", Accept_Encoding="gzip")
    assert status == 200
    assert "Content-Encoding" not in headers, headers
