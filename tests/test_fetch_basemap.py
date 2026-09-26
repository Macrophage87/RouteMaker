"""`scripts/fetch_basemap.sh`, run offline.

Nothing here touches the network. `curl` is a stand-in on PATH that logs every
call and answers downloads from archives the test builds, shaped exactly like
the two pinned ones: a basemaps-assets tarball with `fonts/`, `sprites/v4/`
and the README, and a go-pmtiles tarball whose `pmtiles` logs its argv,
"extracts" by writing a file and "verifies" with an exit code the test picks.

Those archives cannot have the pinned sha256s, so most tests run a copy of the
script whose two sha256 pins are replaced by the archives' own - the only lines
that differ from the repository's script, and the copy is made from it at test
time, so every other line under test is the shipped one. The checksum tests
then serve an impostor for one download at a time, so each checksum is proved
on its own rather than only while both are wrong.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FETCH = REPO / "scripts" / "fetch_basemap.sh"
TEXT = FETCH.read_text()


def pinned(name: str) -> str:
    found = re.search(rf'^{name}="([^"\n]*)"$', TEXT, re.MULTILINE)
    assert found, f"scripts/fetch_basemap.sh pins no {name}"
    return found.group(1)


COMMIT = pinned("ASSETS_COMMIT")
BBOX = pinned("BBOX")
BUILD = pinned("PROTOMAPS_BUILD")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assets_archive(path: Path, glyph: bytes, glyph_range: str = "0-255") -> Path:
    staging = path.with_suffix(".d")
    top = staging / f"basemaps-assets-{COMMIT}"
    (top / "fonts" / "Noto Sans Regular").mkdir(parents=True)
    (top / "fonts" / "Noto Sans Regular" / f"{glyph_range}.pbf").write_bytes(glyph)
    (top / "fonts" / "OFL.txt").write_text("font licence")
    (top / "sprites" / "v4").mkdir(parents=True)
    (top / "sprites" / "v4" / "light.json").write_text("{}")
    (top / "sprites" / "v3").mkdir(parents=True)
    (top / "sprites" / "v3" / "old.json").write_text("{}")
    (top / "README.md").write_text("licences of each directory")
    (top / "scripts").mkdir()
    (top / "scripts" / "create_fonts.sh").write_text("#!/bin/sh\n")
    with tarfile.open(path, "w:gz") as archive:
        archive.add(top, arcname=top.name)
    return path


PMTILES_STUB = """#!/bin/sh
echo "$@" >> "$FAKE_PMTILES_LOG"
case "$1" in
    extract) printf '%s' "$FAKE_REGION" > "$3" ;;
    verify) exit "${FAKE_VERIFY_EXIT:-0}" ;;
esac
exit 0
"""


def pmtiles_archive(path: Path, marker: str) -> Path:
    staging = path.with_suffix(".d")
    staging.mkdir()
    binary = staging / "pmtiles"
    binary.write_text(PMTILES_STUB + f"# {marker}\n")
    binary.chmod(0o755)
    with tarfile.open(path, "w:gz") as archive:
        archive.add(binary, arcname="pmtiles")
    return path


CURL_STUB = """#!/bin/sh
echo "$*" >> "$FAKE_CURL_LOG"
[ -n "${FAKE_CURL_FORBIDDEN:-}" ] && { echo "curl must not be called" >&2; exit 99; }
out=""; url=""
while [ $# -gt 0 ]; do
    case "$1" in -o) out="$2"; shift ;; http*) url="$1" ;; esac
    shift
done
[ -z "$out" ] && exit 0
case "$url" in
    *basemaps-assets*) cp "$FAKE_ASSETS" "$out" ;;
    *go-pmtiles*) cp "$FAKE_PMTILES" "$out" ;;
    *) exit 22 ;;
esac
"""


class Host:
    """A DATA_ROOT, a stand-in curl, the genuine-shaped archives and a copy of
    the script pinned to them."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "data"
        self.basemap = self.root / "basemap"
        self.basemap.mkdir(parents=True)
        self.genuine_assets = assets_archive(tmp_path / "assets.tar.gz", b"real glyphs")
        self.genuine_pmtiles = pmtiles_archive(tmp_path / "pmtiles.tar.gz", "genuine")
        self.impostor_assets = assets_archive(tmp_path / "bad-assets.tar.gz", b"impostor")
        self.impostor_pmtiles = pmtiles_archive(tmp_path / "bad-pmtiles.tar.gz", "impostor")

        body = TEXT
        for name, archive in (
            ("PMTILES_SHA256", self.genuine_pmtiles),
            ("ASSETS_SHA256", self.genuine_assets),
        ):
            line = f'{name}="{pinned(name)}"'
            assert body.count(line) == 1, f"{name} is not pinned exactly once"
            body = body.replace(line, f'{name}="{sha256(archive)}"')
        self.script = tmp_path / "fetch_basemap.sh"
        self.script.write_text(body)

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "curl").write_text(CURL_STUB)
        (bin_dir / "curl").chmod(0o755)
        self.curl_log = tmp_path / "curl.log"
        self.pmtiles_log = tmp_path / "pmtiles.log"
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DATA_ROOT": str(self.root),
            "FAKE_CURL_LOG": str(self.curl_log),
            "FAKE_PMTILES_LOG": str(self.pmtiles_log),
            "FAKE_ASSETS": str(self.genuine_assets),
            "FAKE_PMTILES": str(self.genuine_pmtiles),
            "FAKE_REGION": "PMTiles region",
        }

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        for log in (self.curl_log, self.pmtiles_log):
            log.unlink(missing_ok=True)
        # umask 077, so a file is world-readable afterwards only because the
        # script made it so - Caddy reads these as its own uid.
        return subprocess.run(
            ["sh", "-c", 'umask 077; exec sh "$0" "$@"', str(self.script), *args],
            capture_output=True,
            text=True,
            env={**self.env, **env},
            stdin=subprocess.DEVNULL,
        )

    def repin(self, name: str, value: str) -> None:
        """Change one pin in the copy, as a commit bumping it would."""
        body, count = re.subn(
            rf'^{name}="[^"\n]*"$', f'{name}="{value}"', self.script.read_text(), flags=re.M
        )
        assert count == 1, f"{name} is not pinned exactly once"
        self.script.write_text(body)

    def curl_calls(self) -> str:
        return self.curl_log.read_text() if self.curl_log.exists() else ""

    def snapshot(self) -> dict[str, bytes]:
        return {
            str(p.relative_to(self.basemap)): p.read_bytes()
            for p in sorted(self.basemap.rglob("*"))
            if p.is_file()
        }

    def installed(self) -> subprocess.CompletedProcess:
        first = self.run()
        assert first.returncode == 0, first.stderr
        return first


@pytest.fixture
def host(tmp_path) -> Host:
    return Host(tmp_path)


def test_a_first_run_installs_the_three_parts_readable_by_anyone(host) -> None:
    host.installed()
    files = host.snapshot()
    assert files["region.pmtiles"] == b"PMTiles region"
    assert files["fonts/Noto Sans Regular/0-255.pbf"] == b"real glyphs"
    assert "fonts/OFL.txt" in files
    assert "sprites/v4/light.json" in files
    assert "sprites/README.md" in files, "the licence statement is not installed"
    # Only what the contract serves: not the v3 sprites, not the build scripts.
    assert not any(p.startswith(("sprites/v3", "scripts")) for p in files), sorted(files)
    assert not (host.basemap / ".work").exists()
    for path in [host.basemap, *host.basemap.rglob("*")]:
        mode = path.stat().st_mode
        assert mode & stat.S_IROTH, f"{path} is not world-readable"
        if path.is_dir():
            assert mode & stat.S_IXOTH, f"{path} cannot be entered by another uid"


def test_the_extract_is_of_the_pinned_build_over_the_coverage_box(host) -> None:
    host.installed()
    extract = next(
        line.split() for line in host.pmtiles_log.read_text().splitlines()
        if line.startswith("extract")
    )  # fmt: skip
    assert extract[1] == f"https://build.protomaps.com/{BUILD}.pmtiles", extract
    assert f"--bbox={BBOX}" in extract, extract


def test_the_stamps_a_run_writes_are_the_ones_it_checks(host) -> None:
    host.installed()
    printed = host.run("--print-stamps").stdout.splitlines()
    assert printed, "--print-stamps printed nothing"
    for line in printed:
        name, _, value = line.partition(" ")
        assert (host.basemap / name).read_text().strip() == value


def test_a_second_run_makes_no_request(host) -> None:
    host.installed()
    before = host.snapshot()
    again = host.run(FAKE_CURL_FORBIDDEN="1")
    assert again.returncode == 0, again.stderr
    assert host.curl_calls() == "", host.curl_calls()
    assert host.snapshot() == before


def test_a_new_build_refetches_the_region_and_only_the_region(host) -> None:
    host.installed()
    refresh = host.run("--build", "20260101", FAKE_REGION="newer region")
    assert refresh.returncode == 0, refresh.stderr
    calls = host.curl_calls()
    assert "go-pmtiles" in calls and "build.protomaps.com/20260101.pmtiles" in calls, calls
    assert "basemaps-assets" not in calls, calls
    assert (host.basemap / "region.pmtiles").read_bytes() == b"newer region"
    assert "20260101" in (host.basemap / ".region.source").read_text()


def test_a_changed_bbox_refetches_the_region_over_the_new_box(host) -> None:
    """COVERAGE_BBOX moving is a new region even on the same build day."""
    host.installed()
    wider = "-78.5,38.0,-75.5,40.0"
    host.repin("BBOX", wider)
    rerun = host.run(FAKE_REGION="wider region")
    assert rerun.returncode == 0, rerun.stderr
    calls = host.curl_calls()
    assert "go-pmtiles" in calls and "basemaps-assets" not in calls, calls
    extract = next(
        line.split() for line in host.pmtiles_log.read_text().splitlines()
        if line.startswith("extract")
    )  # fmt: skip
    assert f"--bbox={wider}" in extract, extract
    assert (host.basemap / "region.pmtiles").read_bytes() == b"wider region"


def test_a_refreshed_assets_commit_leaves_nothing_of_the_old_one(host) -> None:
    """The directories are replaced, not merged: a glyph the new commit does
    not have is not left behind to be served."""
    host.installed()
    newer = assets_archive(host.tmp / "newer-assets.tar.gz", b"newer", glyph_range="256-511")
    host.repin("ASSETS_SHA256", sha256(newer))
    rerun = host.run(FAKE_ASSETS=str(newer))
    assert rerun.returncode == 0, rerun.stderr
    fonts = host.basemap / "fonts" / "Noto Sans Regular"
    assert (fonts / "256-511.pbf").read_bytes() == b"newer"
    assert not (fonts / "0-255.pbf").exists()


def test_a_stale_assets_stamp_refetches_the_assets_and_only_the_assets(host) -> None:
    host.installed()
    (host.basemap / ".assets.source").write_text("commit=older\n")
    rerun = host.run()
    assert rerun.returncode == 0, rerun.stderr
    calls = host.curl_calls()
    assert "basemaps-assets" in calls, calls
    assert "go-pmtiles" not in calls and "build.protomaps.com" not in calls, calls


@pytest.mark.parametrize(
    ("missing", "refetched", "left_alone"),
    [
        ("region.pmtiles", "go-pmtiles", "basemaps-assets"),
        (".region.source", "go-pmtiles", "basemaps-assets"),
        ("sprites/README.md", "basemaps-assets", "go-pmtiles"),
        (".assets.source", "basemaps-assets", "go-pmtiles"),
    ],
)
def test_a_missing_file_refetches_its_own_part(host, missing, refetched, left_alone) -> None:
    host.installed()
    (host.basemap / missing).unlink()
    rerun = host.run()
    assert rerun.returncode == 0, rerun.stderr
    calls = host.curl_calls()
    assert refetched in calls and left_alone not in calls, calls
    assert (host.basemap / missing).exists()


@pytest.mark.parametrize(
    ("stale_stamp", "impostor", "url_part"),
    [
        (".assets.source", "FAKE_ASSETS", "basemaps-assets"),
        (".region.source", "FAKE_PMTILES", "go-pmtiles"),
    ],
)
def test_each_checksum_refuses_its_own_impostor(host, stale_stamp, impostor, url_part) -> None:
    """One download wrong at a time, the other part current: the refusal is
    that download's own checksum, and what was serving still is."""
    host.installed()
    (host.basemap / stale_stamp).write_text("stale\n")
    before = host.snapshot()
    wrong = host.impostor_assets if impostor == "FAKE_ASSETS" else host.impostor_pmtiles
    refused = host.run(**{impostor: str(wrong)}, FAKE_REGION="impostor region")
    assert refused.returncode != 0, refused.stdout
    mismatch = [line for line in refused.stderr.splitlines() if sha256(wrong) in line]
    assert mismatch and url_part in mismatch[0], refused.stderr
    assert host.snapshot() == before
    assert not (host.basemap / ".work").exists()


def test_an_archive_that_fails_verify_installs_nothing(host) -> None:
    failed = host.run(FAKE_VERIFY_EXIT="1")
    assert failed.returncode != 0, failed.stdout
    assert any(line.startswith("verify") for line in host.pmtiles_log.read_text().splitlines())
    assert sorted(p.name for p in host.basemap.iterdir()) == []


def test_a_killed_runs_work_directory_does_not_outlive_a_current_run(host) -> None:
    host.installed()
    (host.basemap / ".work").mkdir()
    (host.basemap / ".work" / "region.pmtiles").write_text("half")
    rerun = host.run(FAKE_CURL_FORBIDDEN="1")
    assert rerun.returncode == 0, rerun.stderr
    assert not (host.basemap / ".work").exists()


@pytest.mark.parametrize("build", ["2026-09-26", "latest", "19991231", "202609261"])
def test_a_build_that_is_not_a_date_is_refused(host, build) -> None:
    refused = host.run("--build", build)
    assert refused.returncode == 2
    assert build in refused.stderr
    assert host.curl_calls() == ""


def test_a_relative_data_root_is_refused(host) -> None:
    refused = host.run(DATA_ROOT="data")
    assert refused.returncode == 2
    assert "'data'" in refused.stderr
    assert host.curl_calls() == ""


def test_an_unset_data_root_is_refused(host) -> None:
    env = {k: v for k, v in host.env.items() if k != "DATA_ROOT"}
    refused = subprocess.run(
        ["sh", str(host.script)], capture_output=True, text=True, env=env,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert refused.returncode != 0
    assert "DATA_ROOT" in refused.stderr
    assert host.curl_calls() == ""


def test_a_target_it_cannot_write_is_refused(host) -> None:
    if os.geteuid() == 0:
        pytest.skip("root can write a mode-555 directory")
    host.basemap.chmod(0o555)
    try:
        refused = host.run()
    finally:
        host.basemap.chmod(0o755)
    assert refused.returncode == 2
    assert str(host.basemap) in refused.stderr
    assert host.curl_calls() == ""
