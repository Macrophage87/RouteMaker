"""How the router's HTTP answers are read (`core.routing._transport`).

Against a real HTTP server on the loopback, so the urllib error path is the one
production takes.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core import routing


def _serve(status: int, body: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the stdlib's name
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def router():
    servers = []

    def start(status: int, body: dict | bytes):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        server = _serve(status, raw)
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}/route"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_no_path_is_a_refusal(router) -> None:
    url = router(400, {"error_code": 442, "error": "No path could be found for input"})
    with pytest.raises(routing.RouterRefused) as caught:
        routing._transport(url, {}, 5)
    assert (caught.value.status, caught.value.code) == (400, 442)


@pytest.mark.parametrize("code", [199, 299, 499])
def test_valhalla_3_6_s_unknown_500_is_still_a_refusal(router, code) -> None:
    """3.6.0 moved these from 400 to 500 (valhalla/valhalla#5359). One request
    the router could not serve must not read as the router being down."""
    url = router(500, {"error_code": code, "error": "Unknown", "status_code": 500})
    with pytest.raises(routing.RouterRefused) as caught:
        routing._transport(url, {}, 5)
    assert (caught.value.status, caught.value.code) == (500, code)


@pytest.mark.parametrize(
    ("status", "body"),
    [(500, b""), (502, b"<html>Bad Gateway</html>"), (503, {"error_code": 499}), (500, b"[]")],
)
def test_anything_else_from_the_server_side_is_an_outage(router, status, body) -> None:
    url = router(status, body)
    with pytest.raises(routing.RouterUnavailable):
        routing._transport(url, {}, 5)
