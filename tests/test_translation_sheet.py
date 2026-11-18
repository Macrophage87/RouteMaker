"""The review sheet a native speaker fixes (scripts/translation_sheet.py): out, back in, and
the app's copy of the route's sentences kept in step with the server's."""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = ROOT / "scripts/translation_sheet.py"
_spec = importlib.util.spec_from_file_location("translation_sheet", _SCRIPT)
assert _spec and _spec.loader
sheet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sheet)


@pytest.mark.parametrize("code", sheet.LANGUAGES)
def test_the_apps_copy_is_in_step(code):
    """frontend/src/i18n/server/<code>.ts is what `sync` writes from lang_<code>.py."""
    path = sheet.SERVER_TS / f"{code}.ts"
    assert path.read_text(encoding="utf-8") == sheet.server_ts(code), (
        f"run: python scripts/translation_sheet.py sync ({code})"
    )


@pytest.fixture
def copy(tmp_path, monkeypatch):
    """The catalogs copied aside, so an import writes there."""
    app = tmp_path / "i18n"
    route = tmp_path / "routemaker"
    shutil.copytree(sheet.APP, app)
    route.mkdir()
    for path in sheet.ROUTE.glob("lang_*.py"):
        shutil.copy(path, route / path.name)
    monkeypatch.setattr(sheet, "APP", app)
    monkeypatch.setattr(sheet, "SERVER_TS", app / "server")
    monkeypatch.setattr(sheet, "CHECKED", app / "checked")
    monkeypatch.setattr(sheet, "ROUTE", route)
    monkeypatch.setattr(sheet, "sync", lambda: None)
    return tmp_path


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sheet.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_a_sheet_holds_both_catalogs(copy):
    rows = _rows(sheet.export("fr", copy / "out"))
    keys = {row["Key"] for row in rows}
    assert keys == {"app", "route"}
    turn = next(r for r in rows if r["Key"] == "app" and r["English"] == "Left onto {street}.")
    assert turn["Draft"] == "Tournez à gauche sur {street}."
    assert turn["Where"].startswith("Turn directions")
    assert any(r["Where"].startswith("Route: ") for r in rows)


def test_a_fix_and_a_check_go_back_in(copy):
    path = sheet.export("fr", copy / "out")
    rows = _rows(path)
    for row in rows:
        if row["Key"] == "app" and row["English"] == "Left onto {street}.":
            row["Your fix"] = "Prenez à gauche sur {street}."
        if row["Key"] == "route" and row["English"] == "Right onto {street}":
            row["Your fix"] = "À droite sur {street}"
        if row["Key"] == "app" and row["English"] == "Right.":
            row["Checked"] = "x"
    _write(path, rows)
    assert sheet.import_sheet("fr", path) == []
    fixed = '"Left onto {street}.": "Prenez à gauche sur {street}."'
    assert fixed in sheet.app_path("fr").read_text()
    route = {english: text for _, english, text in sheet.route_entries("fr")}
    assert route["Right onto {street}"] == "À droite sur {street}"
    done = json.loads((sheet.CHECKED / "fr.json").read_text())
    assert "Right." in done["app"] and "Left onto {street}." in done["app"]
    assert "Right onto {street}" in done["route"]
    # Exported again, the checked phrases come marked.
    again = _rows(sheet.export("fr", copy / "again"))
    assert next(r for r in again if r["English"] == "Right.")["Checked"] == "yes"


def test_a_fix_that_loses_a_place_is_refused(copy):
    path = sheet.export("ko", copy / "out")
    rows = _rows(path)
    before = sheet.app_path("ko").read_text()
    for row in rows:
        if row["Key"] == "app" and row["English"] == "Left onto {street}.":
            row["Your fix"] = "좌회전"
    _write(path, rows)
    problems = sheet.import_sheet("ko", path)
    assert len(problems) == 1 and "{places}" in problems[0]
    assert sheet.app_path("ko").read_text() == before
