"""scripts/fetch_transit_gtfs.py: a bad download never replaces the last good zip, and the
README keeps the rows of the feeds not fetched this time (review pipeline-2, TB-12)."""

from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "fetch_transit_gtfs", REPO / "scripts" / "fetch_transit_gtfs.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fetch_gtfs = _module()


def a_zip(*names: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name in names:
            archive.writestr(name, "x\n")
    return out.getvalue()


GOOD = a_zip(*sorted(fetch_gtfs.REQUIRED))


def test_a_good_zip_is_written_and_described(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fetch_gtfs, "fetch", lambda url, headers: GOOD)

    assert fetch_gtfs.main(["--out-dir", str(tmp_path), "--only", "marc"]) == 0

    assert (tmp_path / "marc-gtfs.zip").read_bytes() == GOOD
    assert not list(tmp_path.glob("*.part"))
    assert "`marc-gtfs.zip`" in (tmp_path / "README.md").read_text()


def test_an_error_page_or_an_incomplete_zip_keeps_the_last_good_copy(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fetch_gtfs, "fetch", lambda url, headers: GOOD)
    fetch_gtfs.main(["--out-dir", str(tmp_path), "--only", "marc", "--only", "vre"])
    before = (tmp_path / "README.md").read_text()

    for body in (b"<html>503 Service Unavailable</html>", a_zip("stops.txt")):
        monkeypatch.setattr(fetch_gtfs, "fetch", lambda url, headers, body=body: body)
        assert fetch_gtfs.main(["--out-dir", str(tmp_path), "--only", "marc"]) == 3
        assert (tmp_path / "marc-gtfs.zip").read_bytes() == GOOD
        assert not list(tmp_path.glob("*.part"))
        assert (tmp_path / "README.md").read_text() == before, "both rows are kept"


def test_the_readme_keeps_the_rows_of_feeds_not_fetched_this_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fetch_gtfs, "fetch", lambda url, headers: GOOD)
    fetch_gtfs.main(["--out-dir", str(tmp_path), "--only", "vre"])
    vre = next(line for line in (tmp_path / "README.md").read_text().splitlines() if "vre-" in line)

    fetch_gtfs.main(["--out-dir", str(tmp_path), "--only", "marc"])

    readme = (tmp_path / "README.md").read_text()
    assert vre in readme and "`marc-gtfs.zip`" in readme
    assert readme.index("marc-gtfs") < readme.index("vre-gtfs"), "in systems.json's order"


def test_a_refused_request_says_its_status_and_is_not_asked_again(monkeypatch) -> None:
    import urllib.error

    import pytest

    asked, slept = [], []

    def refuse(code):
        def opened(request, timeout):
            asked.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, code, "no", {}, None)

        return opened

    monkeypatch.setattr(fetch_gtfs.time, "sleep", slept.append)
    monkeypatch.setattr(fetch_gtfs.urllib.request, "urlopen", refuse(401))
    with pytest.raises(RuntimeError, match=r"HTTP 401$"):
        fetch_gtfs.fetch("https://example.test/feed.zip", {})
    assert len(asked) == 1 and slept == []

    # A server error is worth asking again, and still says its status.
    asked.clear()
    monkeypatch.setattr(fetch_gtfs.urllib.request, "urlopen", refuse(503))
    with pytest.raises(RuntimeError, match=r"HTTP 503$"):
        fetch_gtfs.fetch("https://example.test/feed.zip", {})
    assert len(asked) == fetch_gtfs.RETRIES and slept == [5, 10]
