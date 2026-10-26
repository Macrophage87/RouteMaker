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
from urllib.parse import parse_qs

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "osm_edit.py"
TOKEN = "test-token-never-printed"

spec = importlib.util.spec_from_file_location("osm_edit", SCRIPT)
osm_edit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(osm_edit)

NODE = (
    '<osm version="0.6"><node id="101" visible="true" version="{version}" '
    'changeset="{changeset}" timestamp="2026-01-01T00:00:00Z" user="someone" uid="7" '
    'lat="38.9" lon="-77.0">{tags}</node></osm>'
)
# A junction: Main St (two carriageways, ways 1 and 2) crosses Side St (way 3) at nodes 201
# and 202, with signal nodes 301 (signal) and 302 (already a blinker) beside them, and a
# signal 303 about 90 m away that a report at the junction must leave alone.
AREA = """<osm version="0.6">
<node id="201" version="2" lat="39.0225800" lon="-77.0764850"/>
<node id="202" version="1" lat="39.0225497" lon="-77.0763385"/>
<node id="203" version="1" lat="39.0230000" lon="-77.0764000"/>
<node id="204" version="1" lat="39.0220000" lon="-77.0763000"/>
<node id="205" version="1" lat="39.0225600" lon="-77.0770000"/>
<node id="301" version="1" lat="39.0226500" lon="-77.0764000">
  <tag k="highway" v="traffic_signals"/><tag k="traffic_signals" v="signal"/></node>
<node id="302" version="1" lat="39.0224800" lon="-77.0763600">
  <tag k="highway" v="traffic_signals"/><tag k="traffic_signals" v="blinker"/></node>
<node id="303" version="1" lat="39.0233600" lon="-77.0764000">
  <tag k="highway" v="traffic_signals"/></node>
<way id="1" version="1"><nd ref="203"/><nd ref="201"/><nd ref="204"/>
  <tag k="highway" v="primary"/></way>
<way id="2" version="1"><nd ref="204"/><nd ref="202"/><nd ref="203"/>
  <tag k="highway" v="primary"/></way>
<way id="3" version="1"><nd ref="205"/><nd ref="201"/><nd ref="202"/>
  <tag k="highway" v="residential"/></way>
</osm>"""
CHANGESET = '<osm><changeset id="555" open="{open}" changes_count="{count}"/></osm>'


class FakeOsm:
    def __init__(self) -> None:
        self.version = 3
        self.extra = ""
        self.conflicts = 0
        self.after_conflict_extra: str | None = None
        self.token_form: dict[str, list[str]] = {}
        # What a successful PUT stored (the node's tags and its changeset), served back by
        # later GETs; `drop_write` accepts a PUT without storing it, for the smoke test.
        self.stored_tags: str | None = None
        self.changeset = "9"
        self.changeset_open = True
        self.changes = 0
        self.drop_write = False
        self.area = AREA
        # Area nodes saved by a PUT, served back by later GETs; ids in `refuse` answer 412.
        self.saved: dict[str, str] = {}
        self.refuse: set[str] = set()
        self.calls: list[tuple[str, str, bytes, str | None]] = []


def _element_key(path: str) -> str | None:
    """'node/201' or 'way/3' for an element URL of the fake API, else None."""
    parts = path.split("?")[0].rsplit("/", 2)
    if len(parts) == 3 and parts[1] in ("node", "way") and parts[2].isdigit():
        return f"{parts[1]}/{parts[2]}"
    return None


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
            if "/map?bbox=" in self.path:
                self._send(200, state.area)
            elif self.path.endswith("/node/101"):
                tags = state.stored_tags
                if tags is None:
                    tags = '<tag k="name" v="Corner"/>' + state.extra
                node = NODE.format(version=state.version, changeset=state.changeset, tags=tags)
                self._send(200, node)
            elif self.path.endswith("/changeset/555"):
                open_ = "true" if state.changeset_open else "false"
                self._send(200, CHANGESET.format(open=open_, count=state.changes))
            elif self.path.endswith("/user/details.json"):
                self._send(200, json.dumps({"user": {"display_name": "Mapper"}}))
            elif self.path.endswith("/node/404"):
                self._send(410, "")
            elif _element_key(self.path) in state.saved:
                saved = state.saved[_element_key(self.path)]
                self._send(200, f'<osm version="0.6">{saved}</osm>')
            elif _element_key(self.path):
                kind, wanted = _element_key(self.path).split("/")
                for node in ET.fromstring(state.area).iter(kind):
                    if node.get("id") == wanted:
                        body = ET.tostring(node, encoding="unicode")
                        self._send(200, f'<osm version="0.6">{body}</osm>')
                        return
                self._send(404, "")
            else:
                self._send(404, "")

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            state.token_form = parse_qs(self.rfile.read(length).decode())
            if self.path == "/oauth2/token" and state.token_form.get("code") == ["good"]:
                self._send(200, json.dumps({"access_token": TOKEN, "token_type": "Bearer"}))
            else:
                self._send(400, "invalid_grant")

        def do_PUT(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            state.calls.append(("PUT", self.path, body, self.headers.get("Authorization")))
            if self.path.endswith("/changeset/create"):
                # Every changeset is 555 here; a new one starts empty and open.
                state.changes, state.changeset_open = 0, True
                self._send(200, "555")
            elif self.path.endswith("/changeset/555/close"):
                state.changeset_open = False
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
                state.changes += 1
                if not state.drop_write:
                    state.stored_tags = "".join(
                        ET.tostring(tag, encoding="unicode") for tag in sent.iter("tag")
                    )
                    state.changeset = sent.get("changeset")
                self._send(200, str(state.version))
            elif _element_key(self.path):
                wanted = _element_key(self.path)
                sent = ET.fromstring(body).find(wanted.split("/")[0])
                if wanted in state.refuse:
                    self._send(412, "Precondition failed")
                    return
                sent.set("version", str(int(sent.get("version")) + 1))
                state.saved[wanted] = ET.tostring(sent, encoding="unicode")
                state.changes += 1
                self._send(200, sent.get("version"))
            else:
                self._send(404, "")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    local = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setitem(osm_edit.SERVERS, "dev", {"web": local, "api": f"{local}/api/0.6"})
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


def test_a_way_s_oneway_may_be_reversed(osm, tmp_path, capsys):
    path = _edit(tmp_path, element="way", expect={"oneway": "yes"}, set={"oneway": "-1"})
    assert osm_edit.edit_problem(json.loads(path.read_text())) is None


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
        ({"set": {"oneway": "-1"}, "expect": {"oneway": None}}, "oneway may only change on a way"),
        (
            {"element": "way", "set": {"oneway": "reversible"}, "expect": {"oneway": "yes"}},
            "oneway may only be set to",
        ),
        ({"element": "relation"}, "node or way"),
        ({"id": True}, "positive OSM id"),
        ({"set": {"highway": " traffic_signals"}}, "no spaces at the ends"),
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


def test_login_sends_a_pkce_exchange_and_keeps_the_token_owner_only(
    osm, tmp_path, monkeypatch, capsys
):
    path = tmp_path / "state" / "osm-dev.token"
    path.unlink()
    path.write_text("old")
    path.chmod(0o644)
    monkeypatch.setattr("builtins.input", lambda prompt: "good")
    assert osm_edit.main(["login", "--server", "dev", "--client-id", "abc"]) == 0
    out = capsys.readouterr().out
    authorize = parse_qs(out.split("/oauth2/authorize?", 1)[1].split()[0])
    assert authorize["scope"] == ["read_prefs write_api"]
    assert authorize["code_challenge_method"] == ["S256"]
    assert authorize["redirect_uri"] == [osm_edit.REDIRECT_URI]
    form = osm.token_form
    assert form["grant_type"] == ["authorization_code"] and form["client_id"] == ["abc"]
    verifier = form["code_verifier"][0]
    expected = (
        osm_edit.base64.urlsafe_b64encode(osm_edit.hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert authorize["code_challenge"] == [expected]
    assert path.read_text() == TOKEN
    assert path.stat().st_mode & 0o777 == 0o600
    assert "Mapper" in out and TOKEN not in out


def test_login_with_a_bad_code_writes_nothing(osm, tmp_path, monkeypatch):
    path = tmp_path / "state" / "osm-dev.token"
    path.unlink()
    monkeypatch.setattr("builtins.input", lambda prompt: "bad")
    assert osm_edit.main(["login", "--server", "dev", "--client-id", "abc"]) == 1
    assert not path.exists()


def test_a_failed_upload_never_prints_the_token(osm, tmp_path, capsys):
    osm.conflicts = 5
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 1
    out = capsys.readouterr()
    assert "Not uploaded" in out.err
    assert TOKEN not in out.out + out.err


def test_the_same_change_from_a_copied_file_is_refused(osm, tmp_path):
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 0
    copy = tmp_path / "copy.json"
    copy.write_text((tmp_path / "edit.json").read_text())
    osm.calls.clear()
    assert osm_edit.main(["upload", str(copy), "--approved"]) == 1
    assert _puts(osm) == []


def test_a_conflict_where_someone_made_the_same_change_does_not_upload_again(osm, tmp_path):
    osm.conflicts = 1
    osm.after_conflict_extra = '<tag k="highway" v="traffic_signals"/>'
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 1
    node_puts = [p for p, _, _ in _puts(osm) if p.endswith("/node/101")]
    assert len(node_puts) == 1
    assert _puts(osm)[-1][0].endswith("/changeset/555/close")


def test_an_unreachable_server_is_a_plain_refusal(osm, tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(
        osm_edit.SERVERS, "dev", {"web": "http://127.0.0.1:9", "api": "http://127.0.0.1:9/api"}
    )
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 1
    assert "could not reach" in capsys.readouterr().err


def test_a_draft_inside_the_repo_is_refused(osm, tmp_path):
    inside = SCRIPT.parent / "osm-edit-test-draft.json"
    inside.write_text(_edit(tmp_path).read_text())
    try:
        assert osm_edit.main(["upload", str(inside), "--approved"]) == 1
    finally:
        inside.unlink()
    assert _puts(osm) == []


def test_upload_ends_with_a_passing_smoke_test(osm, tmp_path, capsys):
    path = _edit(tmp_path)
    assert osm_edit.main(["upload", str(path), "--approved"]) == 0
    assert "Checked: node 101 has the change, changeset closed" in capsys.readouterr().out
    assert osm_edit.main(["check", str(path)]) == 0


def test_the_smoke_test_catches_an_upload_that_did_not_land(osm, tmp_path, capsys):
    osm.drop_write = True
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--approved"]) == 3
    err = capsys.readouterr().err
    assert "Check FAILED" in err
    assert "version 4 belongs to changeset 9" in err


def test_the_smoke_test_catches_an_open_changeset(osm, tmp_path, capsys):
    path = _edit(tmp_path)
    assert osm_edit.main(["upload", str(path), "--approved"]) == 0
    osm.changeset_open = True
    assert osm_edit.main(["check", str(path)]) == 3
    assert "still open" in capsys.readouterr().err


def test_a_later_edit_by_someone_else_does_not_fail_the_check(osm, tmp_path):
    path = _edit(tmp_path)
    assert osm_edit.main(["upload", str(path), "--approved"]) == 0
    osm.version += 1
    osm.stored_tags = '<tag k="name" v="Renamed"/>'
    assert osm_edit.main(["check", str(path)]) == 0


def test_check_needs_a_recorded_upload(osm, tmp_path, capsys):
    assert osm_edit.main(["check", str(_edit(tmp_path))]) == 1
    assert "no upload recorded" in capsys.readouterr().err


def test_the_smoke_test_catches_wrong_tags_at_the_uploads_version(osm, tmp_path, capsys):
    path = _edit(tmp_path)
    assert osm_edit.main(["upload", str(path), "--approved"]) == 0
    osm.stored_tags = '<tag k="highway" v="stop"/>'
    assert osm_edit.main(["check", str(path)]) == 3
    err = capsys.readouterr().err
    assert "highway: expected 'traffic_signals', OSM has 'stop'" in err
    assert "changeset" not in err.split("Check FAILED:")[1]


def test_the_smoke_test_catches_a_changeset_with_more_than_one_change(osm, tmp_path, capsys):
    path = _edit(tmp_path)
    assert osm_edit.main(["upload", str(path), "--approved"]) == 0
    osm.changes = 2
    assert osm_edit.main(["check", str(path)]) == 3
    assert "holds 2 changes, not 1" in capsys.readouterr().err


def test_a_smoke_test_that_cannot_run_never_says_not_uploaded(osm, tmp_path, capsys, monkeypatch):
    path = _edit(tmp_path)
    real = osm_edit.check_problems

    def unreachable(edit, result):
        raise osm_edit.EditError("could not reach the server")

    monkeypatch.setattr(osm_edit, "check_problems", unreachable)
    assert osm_edit.main(["upload", str(path), "--approved"]) == 3
    err = capsys.readouterr().err
    assert "Not uploaded" not in err and "could not check" in err
    monkeypatch.setattr(osm_edit, "check_problems", real)
    assert (tmp_path / "edit.uploaded.json").exists()


def _draft(kind, tmp_path, *extra):
    out = tmp_path / "drafts"
    argv = [kind, "--name", "Main St and Side St", "--place", "Town"]
    argv += ["--lat", "39.0225574", "--lon", "-77.0763584"]
    argv += ["--server", "dev", "--out", str(out), *extra]
    return osm_edit.main(argv), out


@pytest.fixture
def beacon_files(tmp_path, monkeypatch):
    folder = tmp_path / "fixtures"
    folder.mkdir()
    monkeypatch.setattr(osm_edit, "_fixture_dirs", lambda: [folder])
    return folder


def test_draft_beacon_writes_blinker_edits_and_our_row(osm, tmp_path, capsys, beacon_files):
    code, out = _draft("draft-beacon", tmp_path, "--evidence", "flashing all day, seen 2026-10-21")
    assert code == 0
    edit = json.loads((out / "main-st-side-st-town-301.json").read_text())
    assert edit["expect"] == {"traffic_signals": "signal"}
    assert edit["set"] == {"traffic_signals": "blinker"}
    assert edit["server"] == "dev" and edit["source"] == "survey"
    assert not (out / "main-st-side-st-town-302.json").exists()  # already a blinker
    assert not (out / "main-st-side-st-town-303.json").exists()  # too far
    (fixture,) = out.glob("*-owner-main-st-side-st-town.json")
    beacon = json.loads(fixture.read_text())
    (row,) = beacon["rows"]
    assert beacon["source"] == "owner" and row["id"] == "main-st-side-st-town"
    assert row["name"] == "Main St and Side St, Town"
    assert (row["lat"], row["lon"]) == (39.0225574, -77.0763584)
    assert row["evidence"] == "flashing all day, seen 2026-10-21"
    printed = capsys.readouterr().out
    assert "traffic_signals: 'signal' -> 'blinker'" in printed
    assert "302" in printed and f"apply {out} --approved --actor" in printed
    assert _puts(osm) == []


def test_draft_beacon_with_no_signal_there_points_to_draft_signal(osm, tmp_path, capsys):
    osm.area = '<osm version="0.6"></osm>'
    code, _ = _draft("draft-beacon", tmp_path, "--evidence", "x")
    assert code == 1
    assert "draft-signal" in capsys.readouterr().err


def test_draft_signal_picks_the_nearest_junction_node(osm, tmp_path, capsys):
    osm.area = osm.area.replace('<tag k="highway" v="traffic_signals"/>', "")
    code, out = _draft("draft-signal", tmp_path)
    assert code == 0
    edit = json.loads((out / "main-st-side-st-town-202.json").read_text())
    assert edit["expect"] == {"highway": None}
    assert edit["set"] == {"highway": "traffic_signals"}
    assert "two nodes" in capsys.readouterr().out
    assert _puts(osm) == []


def test_draft_signal_refuses_a_junction_that_already_has_a_highway_tag(osm, tmp_path, capsys):
    osm.area = osm.area.replace(
        '<node id="202" version="1" lat="39.0225497" lon="-77.0763385"/>',
        '<node id="202" version="1" lat="39.0225497" lon="-77.0763385">'
        '<tag k="highway" v="stop"/></node>',
    )
    code, _ = _draft("draft-signal", tmp_path)
    assert code == 1
    assert "highway=stop" in capsys.readouterr().err


def test_drafts_refuse_a_folder_inside_the_repo(osm, tmp_path):
    argv = ["draft-signal", "--name", "X and Y", "--place", "Z", "--lat", "39", "--lon", "-77"]
    argv += ["--out", str(SCRIPT.parent / "drafts-test")]
    assert osm_edit.main(argv) == 1
    assert not (SCRIPT.parent / "drafts-test").exists()


def test_drafts_never_overwrite(osm, tmp_path, beacon_files):
    assert _draft("draft-beacon", tmp_path, "--evidence", "x")[0] == 0
    edit = tmp_path / "drafts" / "main-st-side-st-town-301.json"
    edit.write_text("{}")
    assert _draft("draft-beacon", tmp_path, "--evidence", "x")[0] == 1
    assert edit.read_text() == "{}"


def test_a_taken_name_stops_every_draft_before_any_is_written(osm, tmp_path, beacon_files):
    out = tmp_path / "drafts"
    out.mkdir()
    (out / "main-st-side-st-town-301.json").write_text("{}")
    assert _draft("draft-beacon", tmp_path, "--evidence", "x")[0] == 1
    assert sorted(p.name for p in out.iterdir()) == ["main-st-side-st-town-301.json"]


def test_draft_beacon_writes_no_second_row_where_we_already_have_one(
    osm, tmp_path, capsys, beacon_files
):
    row = {"id": "old", "name": "old", "lat": 39.02256, "lon": -77.07636, "evidence": "x"}
    (beacon_files / "2026-10-20-owner-old.json").write_text(json.dumps({"rows": [row]}))
    code, out = _draft("draft-beacon", tmp_path, "--evidence", "x")
    assert code == 0
    assert (out / "main-st-side-st-town-301.json").exists()
    assert not list(out.glob("*-owner-*"))
    assert "already has an owner beacon here: old" in capsys.readouterr().out


def test_slugs_fit_the_loader_and_need_a_real_name():
    with pytest.raises(osm_edit.EditError):
        osm_edit._slug("and", "&")
    assert len(osm_edit._slug("Very Long Street " * 10, "Town")) <= 80
    assert osm_edit._slug("Very Long Street " * 10, "Town")[-1] != "-"


def test_a_street_split_end_to_end_is_not_a_junction(osm, tmp_path, capsys):
    osm.area = """<osm version="0.6">
      <node id="1" version="1" lat="39.0225" lon="-77.0765"/>
      <node id="2" version="1" lat="39.0225574" lon="-77.0763584"/>
      <node id="3" version="1" lat="39.0226" lon="-77.0762"/>
      <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/>
        <tag k="name" v="Main St"/></way>
      <way id="11"><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/>
        <tag k="name" v="Main St"/><tag k="bridge" v="yes"/></way>
    </osm>"""
    code, _ = _draft("draft-signal", tmp_path)
    assert code == 1
    assert "no junction node" in capsys.readouterr().err
    osm.area = osm.area.replace(
        '<tag k="name" v="Main St"/><tag k="bridge"', '<tag k="name" v="Side St"/><tag k="bridge"'
    )
    assert _draft("draft-signal", tmp_path)[0] == 0


def test_upload_takes_several_files_and_stops_at_the_first_failure(osm, tmp_path):
    first = _edit(tmp_path)
    second = tmp_path / "second.json"
    second.write_text(first.read_text().replace('"id": 101', '"id": 404'))
    assert osm_edit.main(["upload", str(first), str(second), "--approved"]) == 1
    assert (tmp_path / "edit.uploaded.json").exists()


def test_a_rerun_after_a_failure_skips_what_already_went_up(osm, tmp_path, capsys):
    first = _edit(tmp_path)
    second = tmp_path / "second.json"
    second.write_text(first.read_text().replace('"id": 101', '"id": 404'))
    assert osm_edit.main(["upload", str(first), str(second), "--approved"]) == 1
    assert f"Still to upload: {second}" in capsys.readouterr().err
    assert osm_edit.main(["upload", str(first), str(second), "--approved"]) == 1
    out = capsys.readouterr()
    assert "edit.json: already uploaded, skipped" in out.out
    assert "already uploaded" not in out.err
    assert osm_edit.main(["upload", str(first), "--approved"]) == 1
    assert "every file is already uploaded" in capsys.readouterr().err


FAKE_LOADER = """#!/usr/bin/env python3
import json, sys
from pathlib import Path
state = Path(sys.argv[1])
args = sys.argv[2:]
assert args[:6] == ["exec", "-T", "api", "python", "manage.py", "load_flashing_signals"], args
assert args[6:9] == ["-", "--actor", "42"], args
rows = json.loads(sys.stdin.read())["rows"]
loaded = state.read_text().split() if state.exists() else []
if "--confirm" in args:
    if state.with_suffix(".broken").exists():
        print("written")
        sys.exit(0)
    state.write_text(" ".join(loaded + [r["id"] for r in rows]))
    print("written")
    sys.exit(0)
new = [r for r in rows if r["id"] not in loaded]
for r in new:
    print(f"create: {r['id']} {r['name']}")
counts = {"create": len(new), "present": len(rows) - len(new)}
print("<stdin>: owner, " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items()) if n))
print("dry run: nothing written; pass --confirm to write")
"""


@pytest.fixture
def stack(tmp_path):
    loader = tmp_path / "fake-compose"
    loader.write_text(FAKE_LOADER)
    loader.chmod(0o755)
    return tmp_path, f"{loader} {tmp_path / 'loaded'}"


def _apply(out, stack, *extra):
    folder, compose = stack
    argv = ["apply", str(out), "--actor", "42", "--to", "pc", "--stack", str(folder)]
    return osm_edit.main([*argv, "--compose", compose, *extra])


def _owner_file(folder, row_id="x"):
    row = {"id": row_id, "name": "X", "lat": 39.0, "lon": -77.0, "evidence": "e"}
    path = folder / f"2026-10-21-owner-{row_id}.json"
    path.write_text(json.dumps({"version": 1, "source": "owner", "rows": [row]}))
    return path


def test_apply_uploads_the_osm_edits_then_loads_and_checks_our_row(osm, tmp_path, capsys, stack):
    _edit(tmp_path)
    _owner_file(tmp_path)
    assert _apply(tmp_path, stack) == 1  # not approved
    assert _puts(osm) == []
    assert _apply(tmp_path, stack, "--approved") == 0
    printed = capsys.readouterr().out
    assert "Uploaded:" in printed and "create: x X" in printed
    assert "Checked: 1 row(s) active on pc" in printed
    assert (tmp_path / "loaded").read_text() == "x"
    # A rerun skips the upload and finds the row already there.
    assert _apply(tmp_path, stack, "--approved") == 0
    assert "already uploaded, skipped" in capsys.readouterr().out


def test_apply_loads_nothing_when_the_osm_side_stops(osm, tmp_path, capsys, stack):
    edit = _edit(tmp_path)
    edit.write_text(edit.read_text().replace('"id": 101', '"id": 404'))
    _owner_file(tmp_path)
    assert _apply(tmp_path, stack, "--approved") == 1
    assert "Our map not loaded" in capsys.readouterr().err
    assert not (tmp_path / "loaded").exists()


def test_apply_needs_the_actor_for_our_row(osm, tmp_path, capsys):
    _edit(tmp_path)
    _owner_file(tmp_path)
    assert osm_edit.main(["apply", str(tmp_path), "--approved"]) == 1
    assert "--actor" in capsys.readouterr().err
    assert _puts(osm) == []


def test_load_is_a_dry_run_without_confirm_and_checks_after(tmp_path, capsys, stack):
    fixture = _owner_file(tmp_path)
    folder, compose = stack
    argv = ["load", str(fixture), "--actor", "42", "--to", "pc", "--stack", str(folder)]
    argv += ["--compose", compose]
    assert osm_edit.main(argv) == 0
    assert not (tmp_path / "loaded").exists()
    assert "add --confirm" in capsys.readouterr().out
    (tmp_path / "loaded.broken").write_text("")
    assert osm_edit.main([*argv, "--confirm"]) == 3
    err = capsys.readouterr().err
    assert "pc: the row is not active after the load" in err and "--to pc --confirm" in err


def test_load_reaches_beta_over_ssh_through_its_compose_wrapper(tmp_path, monkeypatch, capsys):
    fixture = _owner_file(tmp_path)
    argv = ["load", str(fixture), "--actor", "42"]
    monkeypatch.delenv("ROUTEMAKER_BETA_SSH", raising=False)
    assert osm_edit.main([*argv, "--to", "beta"]) == 1
    assert "ROUTEMAKER_BETA_SSH" in capsys.readouterr().err
    calls = []

    def run(command, cwd, stdin, **kwargs):
        calls.append((command, cwd, stdin.read()))
        return osm_edit.subprocess.CompletedProcess(command, 0, "dry run\n", "")

    monkeypatch.setattr(osm_edit.subprocess, "run", run)
    monkeypatch.setenv("ROUTEMAKER_BETA_SSH", "beta-box")
    assert osm_edit.main(argv) == 0  # both sites by default
    (pc, pc_cwd, _), (beta, beta_cwd, sent) = calls
    assert pc[:2] == ["docker", "compose"] and pc_cwd == osm_edit.DEFAULT_STACK
    assert beta[:2] == ["ssh", "beta-box"] and beta_cwd is None
    assert beta[2].endswith(
        "scripts/beta/beta-compose.sh exec -T api python manage.py load_flashing_signals - "
        "--actor 42"
    )
    assert json.loads(sent)["rows"][0]["id"] == "x"


def test_apply_checks_every_site_before_anything_goes_to_osm(
    osm, tmp_path, capsys, stack, monkeypatch
):
    _edit(tmp_path)
    _owner_file(tmp_path)
    folder, compose = stack
    monkeypatch.delenv("ROUTEMAKER_BETA_SSH", raising=False)
    argv = ["apply", str(tmp_path), "--approved", "--actor", "42", "--stack", str(folder)]
    assert osm_edit.main([*argv, "--compose", compose]) == 1  # pc and beta by default
    assert "ROUTEMAKER_BETA_SSH" in capsys.readouterr().err
    assert _puts(osm) == [] and not (tmp_path / "loaded").exists()


def test_one_site_failing_does_not_stop_the_other(tmp_path, capsys, stack, monkeypatch):
    fixture = _owner_file(tmp_path)
    folder, compose = stack
    real = osm_edit._loader

    def beta_down_on_write(args, site, path, confirm):
        if site == "beta":
            if confirm:
                raise osm_edit.EditError("ssh: connection refused")
            return "<stdin>: owner, 1 create\n"
        return real(args, site, path, confirm)

    monkeypatch.setattr(osm_edit, "_loader", beta_down_on_write)
    argv = ["load", str(fixture), "--actor", "42", "--stack", str(folder), "--compose", compose]
    assert osm_edit.main([*argv, "--to", "beta", "--to", "pc", "--confirm"]) == 3
    out = capsys.readouterr()
    assert "active on pc" in out.out and (tmp_path / "loaded").read_text() == "x"
    assert "beta: ssh: connection refused" in out.err and "--to beta --confirm" in out.err


def test_the_load_check_needs_the_loaders_all_present_line(tmp_path, capsys, monkeypatch):
    fixture = _owner_file(tmp_path)
    for said in (
        "",
        "withdrawn: x X (an admin withdrew it; left alone)\n<stdin>: owner, 1 withdrawn\n",
    ):
        monkeypatch.setattr(osm_edit, "_loader", lambda *a, said=said, **k: said)
        argv = ["load", str(fixture), "--actor", "42", "--to", "pc", "--confirm"]
        assert osm_edit.main(argv) == 3
        assert "not active after the load" in capsys.readouterr().err


def test_an_edit_whose_name_says_owner_is_still_an_edit(osm, tmp_path, capsys, stack):
    edit = _edit(tmp_path)
    edit.rename(tmp_path / "old-owner-rd-town-101.json")
    assert _apply(tmp_path, stack, "--approved") == 0
    assert "Uploaded:" in capsys.readouterr().out
    assert not (tmp_path / "loaded").exists()


def test_load_refuses_an_agency_file(tmp_path, capsys):
    fixture = tmp_path / "flashing-signals.json"
    fixture.write_text(json.dumps({"version": 1, "source": "mdot-sha", "rows": []}))
    assert osm_edit.main(["load", str(fixture), "--actor", "42", "--to", "pc"]) == 1
    assert "not an owner flashing-signal file" in capsys.readouterr().err


def _together(tmp_path, ids=(201, 202, 203), changes=None):
    changes = changes or {}
    paths = []
    for node in ids:
        edit = {
            "server": "dev",
            "element": "node",
            "id": node,
            "expect": {"surface": None},
            "set": {"surface": "asphalt"},
            "comment": "Grounds walks: surface, surveyed",
            "source": "survey",
        }
        edit.update(changes.get(node, {}))
        path = tmp_path / f"n{node}.json"
        path.write_text(json.dumps(edit))
        paths.append(str(path))
    return paths


def test_one_changeset_holds_every_edit_and_checks_each(osm, tmp_path, capsys):
    paths = _together(tmp_path)
    assert osm_edit.main(["upload", *paths, "--approved", "--one-changeset"]) == 0
    puts = [p for p, _, _ in _puts(osm)]
    assert puts.count("/api/0.6/changeset/create") == 1
    assert [p for p in puts if "/node/" in p] == [f"/api/0.6/node/{n}" for n in (201, 202, 203)]
    for node in (201, 202, 203):
        sent = ET.fromstring(osm.saved[f"node/{node}"])
        assert sent.get("changeset") == "555"
        assert sent.find("tag[@k='surface']").get("v") == "asphalt"
    out = capsys.readouterr().out
    assert "Uploaded 3 changes" in out and out.count("Checked:") == 3
    result = json.loads((tmp_path / "n202.uploaded.json").read_text())
    assert result["changes"] == 3 and result["changeset"] == 555
    assert osm_edit.main(["check", paths[1]]) == 0


def test_one_changeset_dry_run_needs_no_approval_and_writes_nothing(osm, tmp_path, capsys):
    paths = _together(tmp_path)
    assert osm_edit.main(["upload", *paths, "--one-changeset", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "surface: None -> 'asphalt'" in out and "One changeset, 3 changes" in out
    assert _puts(osm) == [] and not list(tmp_path.glob("*.uploaded.json"))


def test_one_changeset_refuses_mixed_notes_and_stale_tags_before_uploading(osm, tmp_path, capsys):
    mixed = _together(tmp_path, changes={202: {"comment": "something else"}})
    assert osm_edit.main(["upload", *mixed, "--approved", "--one-changeset"]) == 1
    assert "comment differs" in capsys.readouterr().err
    stale = _together(
        tmp_path, changes={203: {"expect": {"highway": "residential"}, "set": {"highway": "stop"}}}
    )
    assert osm_edit.main(["upload", *stale, "--approved", "--one-changeset"]) == 1
    err = capsys.readouterr().err
    assert "nothing uploaded" in err and "n203.json" in err
    assert _puts(osm) == []


def test_one_changeset_stopping_partway_records_and_checks_what_went_in(osm, tmp_path, capsys):
    osm.refuse = {"node/203"}
    paths = _together(tmp_path)
    assert osm_edit.main(["upload", *paths, "--approved", "--one-changeset"]) == 3
    err = capsys.readouterr().err
    assert "Stopped at n203.json" in err and paths[2] in err.split("Not uploaded")[1]
    assert (tmp_path / "n201.uploaded.json").exists() and not (
        tmp_path / "n203.uploaded.json"
    ).exists()
    assert osm.changeset_open is False
    assert json.loads((tmp_path / "n201.uploaded.json").read_text())["changes"] == 2


def test_dry_run_alone_is_refused(osm, tmp_path, capsys):
    assert osm_edit.main(["upload", str(_edit(tmp_path)), "--dry-run"]) == 1
    assert "--one-changeset" in capsys.readouterr().err


def test_a_rerun_after_a_stop_uploads_only_what_is_left(osm, tmp_path, capsys):
    osm.refuse = {"node/203"}
    paths = _together(tmp_path)
    assert osm_edit.main(["upload", *paths, "--approved", "--one-changeset"]) == 3
    osm.refuse = set()
    capsys.readouterr()
    assert osm_edit.main(["upload", *paths, "--approved", "--one-changeset"]) == 0
    out = capsys.readouterr().out
    assert "n201.json: already uploaded, skipped" in out and "One changeset, 1 changes" in out
    assert (tmp_path / "n203.uploaded.json").exists()


def test_a_rerun_with_the_same_glob_skips_the_result_files(osm, tmp_path, capsys):
    osm.refuse = {"node/203"}
    _together(tmp_path)
    assert (
        osm_edit.main(
            ["upload", *map(str, sorted(tmp_path.glob("n*.json"))), "--approved", "--one-changeset"]
        )
        == 3
    )
    osm.refuse = set()
    capsys.readouterr()
    again = [str(p) for p in sorted(tmp_path.glob("n*.json"))]
    assert any(p.endswith(".uploaded.json") for p in again)
    assert osm_edit.main(["upload", *again, "--approved", "--one-changeset"]) == 0
    assert (tmp_path / "n203.uploaded.json").exists()


def test_an_interruption_mid_set_still_records_what_went_in(osm, tmp_path, monkeypatch):
    real = osm_edit._put_change
    calls = []

    def interrupted(element, edit, changeset, token):
        calls.append(edit["id"])
        if len(calls) == 3:
            raise KeyboardInterrupt
        return real(element, edit, changeset, token)

    monkeypatch.setattr(osm_edit, "_put_change", interrupted)
    with pytest.raises(KeyboardInterrupt):
        osm_edit.main(["upload", *_together(tmp_path), "--approved", "--one-changeset"])
    assert (tmp_path / "n201.uploaded.json").exists() and (tmp_path / "n202.uploaded.json").exists()
    assert not (tmp_path / "n203.uploaded.json").exists()
    assert osm.changeset_open is False


def test_one_changeset_of_ways_keeps_their_nodes(osm, tmp_path, capsys):
    paths = []
    for way in (1, 2, 3):
        edit = {
            "server": "dev",
            "element": "way",
            "id": way,
            "expect": {"bicycle": None},
            "set": {"bicycle": "yes"},
            "comment": "Grounds walks: bicycles allowed, surveyed",
            "source": "survey",
        }
        path = tmp_path / f"w{way}.json"
        path.write_text(json.dumps(edit))
        paths.append(str(path))
    assert osm_edit.main(["upload", *paths, "--approved", "--one-changeset"]) == 0
    sent = ET.fromstring(osm.saved["way/3"])
    assert [nd.get("ref") for nd in sent.iter("nd")] == ["205", "201", "202"]
    assert sent.find("tag[@k='highway']").get("v") == "residential"
    assert sent.find("tag[@k='bicycle']").get("v") == "yes"
    assert capsys.readouterr().out.count("Checked: way") == 3
