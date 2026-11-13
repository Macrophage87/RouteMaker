"""The one refresh of the extract's snapshots after a map rebuild (scripts/refresh_places.py).

The builders are tested on their own (tests/test_build_*.py, tests/test_barrier_census.py);
here they are stood in for, and what is checked is the step around them: every snapshot is
refreshed from the one extract, the dates file says that extract's day, the cities' rack date
moves only when they were fetched, and the change report names what came and went.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "refresh_places", REPO / "scripts" / "refresh_places.py"
)
mod = importlib.util.module_from_spec(spec)
sys.modules["refresh_places"] = mod
spec.loader.exec_module(mod)


def test_every_extract_snapshot_and_builder_is_listed() -> None:
    names = {s.name for s in mod.SNAPSHOTS}
    assert names == {"water-restrooms", "food", "places", "trail-miles", "bike-parking", "barriers"}
    for snapshot in mod.SNAPSHOTS:
        assert (REPO / "scripts" / snapshot.script).is_file(), snapshot.script
        assert snapshot.path.is_file(), snapshot.path
        assert snapshot.items(json.loads(snapshot.path.read_text(encoding="utf-8"))), snapshot.name


def test_the_committed_dates_file_names_every_snapshot() -> None:
    doc = json.loads(mod.AS_OF.read_text(encoding="utf-8"))
    assert set(doc["extract"]) == {s.name for s in mod.SNAPSHOTS}
    for day in [*doc["extract"].values(), doc["cities"]]:
        datetime.strptime(day, "%Y-%m-%d")


def test_the_change_line_counts_added_and_removed_and_flags_a_shrunk_file() -> None:
    assert mod.change_line("food", ["a", "b", "c"], ["b", "c", "d", "e"]) == "food: 3 -> 4 (+2, -1)"
    shrunk = mod.change_line("food", [str(i) for i in range(10)], ["1"])
    assert shrunk.startswith("food: 10 -> 1 (+0, -9)") and "CHECK" in shrunk
    assert "CHECK" not in mod.change_line("food", [], [])


def _setup(tmp_path, monkeypatch):
    snapshots = []
    for s in mod.SNAPSHOTS:
        path = tmp_path / f"{s.name}.json"
        path.write_text(json.dumps({"points": [{"id": "old"}, {"id": "kept"}]}))
        snapshots.append(mod.Snapshot(s.name, path, s.script, s.args, mod._ids("points")))
    monkeypatch.setattr(mod, "SNAPSHOTS", tuple(snapshots))
    monkeypatch.setattr(mod, "AS_OF", tmp_path / "as-of.json")
    mod.AS_OF.write_text(json.dumps({"extract": {}, "cities": "2026-11-01"}))
    pbf = tmp_path / "source.osm.pbf"
    pbf.write_bytes(b"x")
    stamp = datetime(2026, 11, 10, 17, 0, tzinfo=UTC).timestamp()
    os.utime(pbf, (stamp, stamp))
    calls = []

    def run(python, snapshot, given, day, extra):
        calls.append((snapshot.name, snapshot.args(given, day), extra))
        snapshot.path.write_text(json.dumps({"points": [{"id": "kept"}, {"id": "new"}]}))

    return pbf, calls, run


def test_one_run_refreshes_all_from_the_extracts_day(tmp_path, monkeypatch, capsys) -> None:
    pbf, calls, run = _setup(tmp_path, monkeypatch)
    assert mod.main(["--pbf", str(pbf)], run=run) == 0
    assert [c[0] for c in calls] == [s.name for s in mod.SNAPSHOTS]
    assert all(str(pbf) in c[1] for c in calls)
    assert all(c[2] == [] for c in calls), "no network without --cities"
    barriers = next(c for c in calls if c[0] == "barriers")
    assert barriers[1][barriers[1].index("--built") + 1] == "2026-11-10"
    doc = json.loads(mod.AS_OF.read_text())
    assert set(doc["extract"].values()) == {"2026-11-10"}
    assert doc["cities"] == "2026-11-01", "the cities' racks keep their old date"
    out = capsys.readouterr().out
    assert "Refreshed from the 2026-11-10 extract" in out
    assert "- food: 2 -> 2 (+1, -1)" in out


def test_cities_fetches_the_racks_and_dates_them_today(tmp_path, monkeypatch) -> None:
    pbf, calls, run = _setup(tmp_path, monkeypatch)
    mod.main(["--pbf", str(pbf), "--cities", "--extract-date", "2026-11-09"], run=run)
    racks = next(c for c in calls if c[0] == "bike-parking")
    assert racks[2] == ["--ddot", "--baltimore"]
    doc = json.loads(mod.AS_OF.read_text())
    assert set(doc["extract"].values()) == {"2026-11-09"}
    assert doc["cities"] == datetime.now(UTC).date().isoformat()


def test_a_failed_builder_leaves_the_dates_file_alone(tmp_path, monkeypatch) -> None:
    pbf, _, _ = _setup(tmp_path, monkeypatch)
    before = mod.AS_OF.read_text()

    def run(python, snapshot, given, day, extra):
        raise mod.subprocess.CalledProcessError(1, snapshot.script)

    try:
        mod.main(["--pbf", str(pbf)], run=run)
    except mod.subprocess.CalledProcessError:
        pass
    assert mod.AS_OF.read_text() == before
