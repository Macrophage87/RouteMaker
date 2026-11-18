"""The interval-capable stretches near a point (core.intervals_near), from the layer's file."""

from __future__ import annotations

import json

import pytest

from core import intervals_near as near_mod


def _row(id_, x0, length_deg=0.03, **extra):
    return {
        "id": id_,
        "l": round(length_deg * 86_500),
        "r": 10,
        "g": 0.4,
        "line": [[x0, 39.0], [x0 + length_deg / 2, 39.0], [x0 + length_deg, 39.0]],
        **extra,
    }


@pytest.fixture
def file(tmp_path, monkeypatch):
    rows = [
        _row("near", -77.0),
        _row("busy", -77.0, b=1),
        _row("gravel", -76.99, s="g", w=1, k=2),
        _row("far", -76.5),
    ]
    path = tmp_path / "intervals.json"
    path.write_text(json.dumps({"version": 1, "built": "2026-11-16", "intervals": rows}))
    monkeypatch.setattr(near_mod, "INTERVALS_FILE", path)
    near_mod._cache.clear()
    return path


def test_the_stretches_near_are_listed_nearest_first(file):
    found = near_mod.near(-77.0, 39.0, 5)
    assert [s["id"] for s in found] == ["near", "busy", "gravel"]
    first = found[0]
    assert first["start"] == [-77.0, 39.0] and first["end"] == [-76.97, 39.0]
    assert first["through"] == [[-76.985, 39.0]] and first["surface"] == "road"
    assert found[2]["both_ways"] and found[2]["surface"] == "gravel"


def test_filters(file):
    found = near_mod.near(-77.0, 39.0, 5, paved_only=True, quiet_only=True)
    assert [s["id"] for s in found] == ["near"]
    assert near_mod.near(-77.0, 39.0, 5, min_miles=5) == []
    # Bollards are counted and left out only where asked (the owner, 2026-11-18).
    assert [s["bollards"] for s in near_mod.near(-77.0, 39.0, 5)] == [0, 0, 2]
    assert [s["id"] for s in near_mod.near(-77.0, 39.0, 5, no_bollards=True)] == ["near", "busy"]


def test_no_file_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(near_mod, "INTERVALS_FILE", tmp_path / "none.json")
    with pytest.raises(near_mod.Unavailable):
        near_mod.near(-77.0, 39.0, 5)


def test_an_unbuilt_file_is_unavailable_not_empty(tmp_path, monkeypatch):
    path = tmp_path / "intervals.json"
    path.write_text(json.dumps({"version": 1, "built": None, "intervals": []}))
    monkeypatch.setattr(near_mod, "INTERVALS_FILE", path)
    near_mod._cache.clear()
    with pytest.raises(near_mod.Unavailable):
        near_mod.near(-77.0, 39.0, 5)
