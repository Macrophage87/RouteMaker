"""The agency-layer downloader: paging, the record it writes, and the one-download rule.

A local server stands in for the ArcGIS service, so what is checked is what the
script asks for and what it writes down: every page fetched, the features stored
unedited, the licence text verbatim, the digest of the file, and a refusal to
fetch the same layer twice (the owner approves each download once).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from rebuild_fixtures import REPO

SCRIPT = REPO / "scripts" / "fetch_agency_layer.py"
ITEM = "0123456789abcdef0123456789abcdef"
LICENCE_HTML = (
    '<DIV><P>This work is licensed under a <A href="x">'
    "Creative Commons Attribution 4.0 International License</A>.</P></DIV>"
)

FEATURES = [
    {
        "type": "Feature",
        "id": n,
        "properties": {"OBJECTID": n, "NAME": f"BLOCK {n}"},
        "geometry": {
            "type": "LineString",
            "coordinates": [[-77.0, 38.9], [-77.0 + n / 1000, 38.9]],
        },
    }
    for n in range(1, 6)
]


class Service(BaseHTTPRequestHandler):
    """Five features, served two to a page, on a layer at /layer."""

    queries: list[dict] = []
    fail_count = False

    def log_message(self, *args) -> None:  # silence
        pass

    def reply(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == f"/items/{ITEM}":
            return self.reply(
                {
                    "title": "Test Layer",
                    "licenseInfo": LICENCE_HTML,
                    "accessInformation": "Test Agency",
                    "modified": 1_790_000_000_000,
                }
            )
        if url.path == "/layer":
            return self.reply({"maxRecordCount": 2})
        if url.path == "/layer/query":
            if query.get("returnCountOnly"):
                return self.reply({"count": len(FEATURES) + (1 if self.fail_count else 0)})
            Service.queries.append(query)
            start = int(query["resultOffset"])
            size = int(query["resultRecordCount"])
            return self.reply(
                {"type": "FeatureCollection", "features": FEATURES[start : start + size]}
            )
        self.send_response(404)
        self.end_headers()


@pytest.fixture
def service():
    Service.queries = []
    Service.fail_count = False
    server = HTTPServer(("127.0.0.1", 0), Service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def fetch(base: str, out_dir, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--slug",
            "test-layer",
            "--item",
            ITEM,
            "--layer",
            f"{base}/layer",
            "--item-base",
            f"{base}/items",
            "--out-dir",
            str(out_dir),
            "--credit",
            "Test Agency, CC BY 4.0",
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def test_every_page_is_fetched_and_the_features_stored_unedited(service, tmp_path) -> None:
    done = fetch(service, tmp_path)
    assert done.returncode == 0, done.stderr
    stored = json.loads((tmp_path / "test-layer" / "test-layer.geojson").read_text())
    assert stored["features"] == FEATURES
    # Three pages of at most two, ordered by the id so the pages do not overlap.
    assert [(q["resultOffset"], q["resultRecordCount"]) for q in Service.queries] == [
        ("0", "2"),
        ("2", "2"),
        ("4", "2"),
    ]
    assert {q["orderByFields"] for q in Service.queries} == {"OBJECTID"}
    assert {q["outSR"] for q in Service.queries} == {"4326"}
    assert {q["f"] for q in Service.queries} == {"geojson"}


def test_the_readme_records_the_source_licence_time_and_digest(service, tmp_path) -> None:
    fetch(service, tmp_path)
    path = tmp_path / "test-layer" / "test-layer.geojson"
    readme = (tmp_path / "test-layer" / "README.md").read_text()
    assert hashlib.sha256(path.read_bytes()).hexdigest() in readme
    assert f"{path.stat().st_size:,} bytes" in readme
    assert f"{service}/layer" in readme
    assert f"`{ITEM}`" in readme
    assert "5 stored; the service reported 5 (3 pages)" in readme
    assert "Test Agency, CC BY 4.0" in readme
    # The licence as plain text, and the HTML it came from.
    assert (
        "> This work is licensed under a Creative Commons Attribution 4.0 International License."
        in readme
    )
    assert LICENCE_HTML in readme
    assert re.search(r"Retrieved \(UTC\) \| \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", readme)
    assert "modified 2026-09-21" in readme  # the item's own date, from its metadata


def test_a_layer_already_downloaded_is_not_downloaded_again(service, tmp_path) -> None:
    fetch(service, tmp_path)
    queries = len(Service.queries)
    again = fetch(service, tmp_path)
    assert again.returncode == 2
    assert "already downloaded once" in again.stderr
    assert len(Service.queries) == queries, "the second run asked the service for nothing"


def test_a_count_that_does_not_match_what_was_stored_is_a_failure(service, tmp_path) -> None:
    """The service reports a count and the pages must add up to it; a short
    download is not recorded as a complete one."""
    Service.fail_count = True
    done = fetch(service, tmp_path)
    assert done.returncode == 3


def test_a_where_clause_is_passed_to_the_service(service, tmp_path) -> None:
    fetch(service, tmp_path, "--where", "mainSpur <> 'Future Alignment'")
    assert {q["where"] for q in Service.queries} == {"mainSpur <> 'Future Alignment'"}
    readme = (tmp_path / "test-layer" / "README.md").read_text()
    assert "where=mainSpur <> 'Future Alignment'" in readme


def test_an_item_with_no_licence_text_says_so() -> None:
    sys.path.insert(0, str(REPO / "scripts"))
    import fetch_agency_layer

    assert fetch_agency_layer.strip_html(None) == ""
    assert fetch_agency_layer.strip_html("") == ""
    assert (
        fetch_agency_layer.strip_html("<span style='x'>You can &quot;copy&quot;   it</span>")
        == 'You can "copy" it'
    )
