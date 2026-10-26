"""The beta's nginx site file, rendered and given to nginx itself: `nginx -t` in a pinned nginx.

The text checks in tests/test_beta_overlay.py read the template; they cannot see what nginx
refuses. v0.12.3's robots.txt line held a bare `$` (`Allow: /$`), which nginx reads as the start
of a variable name, so every render failed `nginx -t` ("invalid variable name") and the beta's
file had to be patched by hand. This renders the file as the runbook does (stage full, the beta
open with --no-password, with and without --no-ipv6 and --no-401-page), includes it inside
`http { }` as the host's nginx.conf does, and has nginx test it; then serves it and reads
robots.txt back.

Skipped, not failed, where there is no Docker daemon or the image is not already present: this
pulls nothing. In CI (`CI` set) a missing image is a failure: the workflow pulls IMAGE before
pytest, so a skip there would be the site file going untested in silence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RENDER = REPO / "scripts" / "beta" / "render-nginx.sh"
# nginx 1.27.5 on Alpine. The beta's host runs its distribution's nginx; this is the parser the
# rendered file must get past, not the host's exact build.
IMAGE = (
    "docker.io/library/nginx:1.27-alpine"
    "@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10"
)
LOCAL_IMAGE = IMAGE.removeprefix("docker.io/library/")
SERVER_NAME = "beta.example.test"

# What robots.txt serves, byte for byte: the home page, the favicons and the icons for Google's
# favicon service (the connector's icon, docs/OPERATIONS.md), nothing else.
ROBOTS = (
    "User-agent: *\n"
    "Allow: /$\n"
    "Allow: /favicon.ico\n"
    "Allow: /favicon.svg\n"
    "Allow: /icons/\n"
    "Disallow: /\n"
)

# The host's nginx.conf includes the site file inside http, beside its other sites.
NGINX_CONF = """\
events {}
http {
    include /etc/nginx/mime.types;
    include /rmtest/site.conf;
}
"""

VARIANTS = {
    "open": ["--no-password"],
    "open-no-ipv6": ["--no-password", "--no-ipv6"],
    "open-no-401-page": ["--no-password", "--no-401-page"],
    "open-no-ipv6-no-401-page": ["--no-password", "--no-ipv6", "--no-401-page"],
}


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    probe = subprocess.run(
        ["docker", "image", "inspect", LOCAL_IMAGE], capture_output=True, stdin=subprocess.DEVNULL
    )
    return probe.returncode == 0


@pytest.fixture(scope="module", autouse=True)
def _nginx_present():
    if not docker_ready():
        why = f"needs a Docker daemon and {LOCAL_IMAGE} already present"
        if os.environ.get("CI"):
            pytest.fail(f"CI: {why} (the workflow pulls it before pytest)")
        pytest.skip(why)


def render(tmp: Path, flags: list[str]) -> Path:
    """The site file and the files nginx -t opens: a throwaway certificate, nginx.conf."""
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", f"/CN={SERVER_NAME}",
            "-keyout", str(tmp / "key.pem"), "-out", str(tmp / "fullchain.pem"),
        ],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    subprocess.run(
        [
            "sh", str(RENDER), "--stage", "full", *flags,
            "--server-name", SERVER_NAME, "--api-port", "8087",
            "--data-root", "/rmtest/data", "--acme-root", "/rmtest/acme",
            "--cert-fullchain", "/rmtest/fullchain.pem", "--cert-key", "/rmtest/key.pem",
            "--env-file", str(tmp / "no.env"), "--out", str(tmp / "site.conf"),
        ],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    (tmp / "nginx.conf").write_text(NGINX_CONF)
    for f in tmp.iterdir():
        f.chmod(0o644)
    tmp.chmod(0o755)
    return tmp


def in_nginx(tmp: Path, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--pull", "never",
            "--label", "rm-test=beta-nginx", "-v", f"{tmp}:/rmtest:ro",
            "--entrypoint", "sh", LOCAL_IMAGE, "-c", script,
        ],
        capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
    )  # fmt: skip


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_render_the_runbook_uses_passes_nginx_t(tmp_path, variant) -> None:
    site = render(tmp_path, VARIANTS[variant])
    result = in_nginx(site, "nginx -t -c /rmtest/nginx.conf")
    # The whole file parses ("invalid variable name" and every other syntax error come first).
    assert "syntax is ok" in result.stderr, result.stderr
    # Then nginx opens the listen sockets. A host (or CI runner) with no IPv6 cannot open [::],
    # which is the runbook's reason for --no-ipv6, not a fault in the file.
    no_ipv6 = "socket() [::]:80 failed (97: Address family not supported by protocol)"
    ok = result.returncode == 0 and "test is successful" in result.stderr
    assert ok or ("--no-ipv6" not in VARIANTS[variant] and no_ipv6 in result.stderr), result.stderr


def test_robots_txt_is_served_exactly(tmp_path) -> None:
    site = render(tmp_path, VARIANTS["open-no-ipv6"])
    result = in_nginx(
        site,
        "nginx -c /rmtest/nginx.conf && curl -sk --resolve "
        f"{SERVER_NAME}:443:127.0.0.1 https://{SERVER_NAME}/robots.txt",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ROBOTS
