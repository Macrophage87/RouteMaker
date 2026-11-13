"""scripts/load_test.py (backlog 2026-11-12, "Ready for a dozen testers"): against a stub api on
127.0.0.1, so nothing here reaches a server; and its refusals (a public address, the beta host)."""

from __future__ import annotations

import importlib.util
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("load_test", REPO / "scripts" / "load_test.py")
load_test = importlib.util.module_from_spec(spec)
sys.modules["load_test"] = load_test
spec.loader.exec_module(load_test)


class Stub(BaseHTTPRequestHandler):
    seen: list[tuple[str, str, str]] = []

    def answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        Stub.seen.append((self.command, self.path, self.headers.get("X-Forwarded-For", "")))
        code = 429 if self.path.startswith("/api/geocode") else 200
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    do_GET = do_POST = answer

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def stub(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    Stub.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_each_rider_opens_searches_plans_pans_rides_and_reroutes(stub, tmp_path) -> None:
    out = tmp_path / "report.md"
    code = load_test.main(
        [
            "--base",
            stub,
            "--riders",
            "3",
            "--spread",
            "0",
            "--ride-minutes",
            "4",
            "--time-scale",
            "0.001",
            "--tiles",
            "4",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    plans = [s for s in Stub.seen if s[0] == "POST" and s[1] == "/api/route"]
    assert len(plans) == 6  # one plan and one re-route each
    assert {s[2] for s in Stub.seen} == {"10.77.0.1", "10.77.0.2", "10.77.0.3"}  # counted apart
    assert sum(s[1].startswith("/tiles/stress/14/") for s in Stub.seen) == 12
    text = out.read_text()
    assert "# Load test: 3 riders" in text
    assert "| search | 3 | 0 | 3 |" in text  # the stub refuses searches: reported as refused
    assert "| plan | 3 | 3 |" in text
    assert "Every rider counted as one client" not in text


def test_a_public_address_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    public = [(0, 0, 0, "", ("8.8.8.8", 0))]
    monkeypatch.setattr(load_test.socket, "getaddrinfo", lambda *a, **k: public)
    assert load_test.main(["--base", "https://example.org"]) == 2
    assert load_test.allowed("https://example.org", ["example.org"]) is None


def test_the_beta_host_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "routemaker-beta-state").mkdir()
    (tmp_path / "routemaker-beta-state" / "vars.sh").write_text("")
    assert "beta host" in load_test.allowed("http://127.0.0.1:8087", [])


def test_docker_memory_units() -> None:
    assert load_test.to_mib("1.5GiB") == 1536
    assert load_test.to_mib("512MiB") == 512
    assert load_test.to_mib("junk") == 0
