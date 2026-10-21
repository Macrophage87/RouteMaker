"""The OSM edit uploader: one approved tag change, one changeset, nothing more.

A local server stands in for the OSM API, so what is checked is what the script sends:
the changeset tags, the element with only the approved tags changed, the conflict retry,
the refusals (a changed tag, a second upload, live OSM without --live, a tag the tool may
not touch), and that the token never reaches the output.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "osm_edit.py"
TOKEN = "test-token-never-printed"

spec = importlib.util.spec_from_file_location("osm_edit", SCRIPT)
osm_edit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(osm_edit)

NODE = (
    '<osm version="0.6"><node id="101" visible="true" version="{version}" changeset="9" '
    'timestamp="2026-01-01T00:00:00Z" user="someone" uid="7" lat="38.9" lon="-77.0">'
    '<tag k="name" v="Corner"/>{extra}</node></osm>'
)


class FakeOsm:
    def __init__(self) -> None:
        self.version = 3
        self.extra = ""
        self.conflicts = 0
        self.after_conflict_extra: str | None = None
        self.calls: list[tuple[str, str, bytes, str | None]] = []


@pytest.fixture
def osm(tmp_path, monkeypatch):
    state = FakeOsm()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status: int, body: str) -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            state.calls.append(("GET", self.path, b"", self.headers.get("Authorization")))
            if self.path.endswith("/node/101"):
                self._send(200, NODE.format(version=state.version, extra=state.extra))
            elif self.path.endswith("/node/404"):
                self._send(410, "")
            else:
                self._send(404, "")

        def do_PUT(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            state.calls.append(("PUT", self.path, body, self.headers.get("Authorization")))
            if self.path.endswith("/changeset/create"):
                self._send(200, "555")
            elif self.path.endswith("/changeset/555/close"):
                self._send(200, "")
            elif self.path.endswith("/node/101"):
                if state.conflicts:
                    state.conflicts -= 1
                    state.version += 1
                    if state.after_conflict_extra is not None:
                        state.extra = state.after_conflict_extra
                    self._send(409, "Version mismatch")
                    return
                sent = ET.fromstring(body).find("node")
                if sent.get("version") != str(state.version):
                    self._send(409, "Version mismatch")
                    return
                state.version += 1
                self._send(200, str(state.version))
            else:
                self._send(404, "")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ROUTEMAKER_OSM_API", f"http://127.0.0.1:{server.server_port}/api/0.6")
    monkeypatch.setenv("ROUTEMAKER_OSM_STATE", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "osm-dev.token").write_text(TOKEN)
    yield state
    server.shutdown()


def _edit(tmp_path: Path, **changes) -> Path:
    edit = {
        "server": "dev",
        "element": "node",
        "id": 101,
        "expect": {"highway": None},
        "set": {"highway": "traffic_signals"},
        "comment": "Traffic signal, surveyed",
        "source": "survey",
    }
    edit.update(changes)
    path = tmp_path / "edit.json"
    path.write_text(json.dumps(edit))
    return path


def _puts(osm: FakeOsm) -> list[tuple[str, bytes, str | None]]:
    return [(path, body, auth) for method, path, body, auth in osm.calls if method == "PUT"]


def test_upload_sends_one_changeset_with_only_the_approved_tag(osm, tmp_path, capsys):
    path = _edit(tmp_path)
    assert osm_edit.main(["upload", str(path), "--approved"]) == 0

    puts = _puts(osm)
    assert [p for p, _, _ in puts] == [
        "/api/0.6/changeset/create",
        "/api/0.6/node/101",
        "/api/0.6/changeset/555/close",
    ]
    assert all(auth == f"Bearer {TOKEN}" for _, _, auth in puts)
    changeset_tags = {t.get("k"): t.get("v") for t in ET.fromstring(puts[0][1]).iter("tag")}
    assert changeset_tags == {
        "comment": "Traffic signal, surveyed",
        "source": "survey",
        "created_by": osm_edit.CREATED_BY,
    }
    node = ET.fromstring(puts[1][1]).find("node")
    assert node.get("changeset") == "555" and node.get("version") == "3"
    assert (node.get("lat"), node.get("lon")) == ("38.9", "-77.0")
    assert {t.get("k"): t.get("v") for t in node.iter("tag")} == {
        "name": "Corner",
        "highway": "traffic_signals",
    }
    result = json.loads((tmp_path / "edit.uploaded.json").read_text())
    assert result["changeset"] == 555 and result["version"] == 4
    out = capsys.readouterr()
    assert "changeset/555" in out.out
    assert TOKEN not in out.out + out.err
    assert TOKEN not in (tmp_path / "state" / "osm-edits.log").read_text()


def test_a_second_upload_of_the_same_file_is_refused(osm, tmp_path):
    path = _edit(tmp_path)
    assert osm_edit.main(["upload", str(path), "--approved"]) == 0
    osm.calls.clear()
    assert osm_edit.main(["upload", str(path), "--approved"]) == 1
    assert _puts(osm) == []


def test_upload_needs_the_approval_flag(osm, tmp_path):
    assert osm_edit.main(["upload", str(_edit(tmp_path))]) == 1
    assert osm.calls == []


def test_live_osm_needs_live_flag_and_the_flag_needs_a_live_edit(osm, tmp_path):
    assert osm_edit.main(["upload", str(_edit(tmp_path, server="live")), "--approved"]) == 1
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved", "--live"]) == 1
    assert osm.calls == []


def test_a_tag_changed_since_approval_stops_the_upload(osm, tmp_path, capsys):
    osm.extra = '<tag k="highway" v="stop"/>'
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 1
    assert _puts(osm) == []
    assert "shown None, now 'stop'" in capsys.readouterr().err


def test_a_conflict_retries_once_on_the_new_version(osm, tmp_path):
    osm.conflicts = 1
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 0
    node_puts = [b for p, b, _ in _puts(osm) if p.endswith("/node/101")]
    assert len(node_puts) == 2
    assert ET.fromstring(node_puts[1]).find("node").get("version") == "4"
    assert _puts(osm)[-1][0].endswith("/changeset/555/close")


def test_a_conflict_that_changed_the_tag_stops_and_still_closes(osm, tmp_path):
    osm.conflicts = 1
    osm.after_conflict_extra = '<tag k="highway" v="stop"/>'
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 1
    assert _puts(osm)[-1][0].endswith("/changeset/555/close")
    assert not (tmp_path / "edit.uploaded.json").exists()


def test_repeated_conflicts_give_up_after_one_retry(osm, tmp_path):
    osm.conflicts = 5
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 1
    node_puts = [p for p, _, _ in _puts(osm) if p.endswith("/node/101")]
    assert len(node_puts) == 2


def test_a_deleted_element_stops(osm, tmp_path):
    assert osm_edit.main(["upload", str(_edit(tmp_path, id=404)), "--approved"]) == 1
    assert _puts(osm) == []


def test_removing_a_tag(osm, tmp_path):
    osm.extra = '<tag k="bicycle" v="no"/>'
    path = _edit(tmp_path, expect={"bicycle": "no"}, set={"bicycle": None})
    assert osm_edit.main(["upload", str(path), "--approved"]) == 0
    node = ET.fromstring([b for p, b, _ in _puts(osm) if p.endswith("/node/101")][0])
    assert "bicycle" not in {t.get("k") for t in node.iter("tag")}


def test_show_prints_the_diff_and_flags_a_stale_draft(osm, tmp_path, capsys):
    assert osm_edit.main(["show", str(_edit(tmp_path))]) == 0
    assert "highway: None -> 'traffic_signals'" in capsys.readouterr().out
    osm.extra = '<tag k="highway" v="stop"/>'
    assert osm_edit.main(["show", str(_edit(tmp_path))]) == 2
    assert _puts(osm) == []


@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"set": {"name": "X"}, "expect": {"name": None}}, "not one this tool may change"),
        ({"element": "way", "set": {"highway": "traffic_signals"}}, "only change on a node"),
        ({"set": {"highway": "motorway"}}, "may only be set to"),
        ({"set": {"highway": "traffic_signals"}, "expect": {}}, "exactly the tags"),
        ({"element": "relation"}, "node or way"),
        ({"comment": ""}, "changeset note"),
        ({"source": "Google Street View"}, "survey or local_knowledge"),
        (
            {
                "set": {
                    k: "yes" for k in ("bicycle", "crossing", "surface", "smoothness", "mtb:scale")
                },
                "expect": {
                    k: None for k in ("bicycle", "crossing", "surface", "smoothness", "mtb:scale")
                },
            },
            "at most 4",
        ),
    ],
)
def test_edits_the_tool_will_not_send(osm, tmp_path, capsys, changes, words):
    assert osm_edit.main(["upload", str(_edit(tmp_path, **changes)), "--approved"]) == 1
    assert words in capsys.readouterr().err
    assert osm.calls == []


def test_not_signed_in(osm, tmp_path, capsys):
    (tmp_path / "state" / "osm-dev.token").unlink()
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 1
    assert "not signed in" in capsys.readouterr().err
    assert _puts(osm) == []
