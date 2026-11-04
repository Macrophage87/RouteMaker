"""Public places spread over the covered area, urban, suburban and rural
(fixtures/test-places.json), for tests that should hold all over the map, not at one spot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_DATA = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "test-places.json").read_text()
)
INSIDE: list[dict] = _DATA["inside"]
OUTSIDE: list[dict] = _DATA["outside"]


def params(places: list[dict]) -> list:
    """The places as pytest params, each named for its place (and setting, where it has one)."""
    return [
        pytest.param(p, id=f"{p.get('setting', 'outside')}-{p['name']}".replace(" ", "_"))
        for p in places
    ]
