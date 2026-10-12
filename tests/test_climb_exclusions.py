"""Climbs taken off by hand (`routemaker.climb_exclusions`; owner report 2026-10-12, the
Travilah quarry's Cat 4): the builder never writes one, the hill seek never reads one, and the
front end's copy of the list is the same list."""

from __future__ import annotations

import json
import re
from pathlib import Path

from core import hillseek
from pipeline import climb_layer as cl
from routemaker import climb_exclusions

REPO = Path(__file__).resolve().parents[1]
TS = REPO / "frontend" / "src" / "lib" / "climbExclusions.ts"
BUNDLED = REPO / "frontend" / "src" / "climb-data" / "climbs.json"
QUARRY = "bd93dd04dc"


def test_the_quarry_climb_is_listed_with_a_reason_and_a_source():
    entry = climb_exclusions.EXCLUDED[QUARRY]
    assert "quarry" in entry.reason and "2026-10-12" in entry.source
    for climb_id, entry in climb_exclusions.EXCLUDED.items():
        assert re.fullmatch(r"[0-9a-f]{10}", climb_id)
        assert entry.reason.strip() and entry.source.strip()


def test_the_front_end_lists_the_same_ids():
    text = TS.read_text()
    body = text[text.index("new Set([") : text.index("]);")]
    assert set(re.findall(r'"([0-9a-f]{10})"', body)) == set(climb_exclusions.EXCLUDED)


def test_the_hill_seek_never_reads_an_excluded_climb():
    doc = json.loads(BUNDLED.read_text())
    ids = {c["id"] for c in doc["climbs"]}
    climbs = hillseek.parse(doc)
    assert climbs is not None
    read = {c.id for c in climbs}
    assert not read & set(climb_exclusions.EXCLUDED)
    # Every other climb is still read.
    assert read == ids - set(climb_exclusions.EXCLUDED)


def test_the_builder_never_writes_an_excluded_climb():
    quarry = {"id": QUARRY, "c": "4", "l": 1903, "r": 156, "g": 8.2}
    kept = {"id": "0123456789", "c": "5", "l": 900, "r": 20, "g": 2.2}

    class FakeFound:
        def __init__(self, entry):
            self._entry = entry
            self.climb = type("C", (), {"gain_m": entry["r"]})()

        def entry(self):
            return self._entry

    out = cl.document([FakeFound(quarry), FakeFound(kept)])
    assert [c["id"] for c in out["climbs"]] == [kept["id"]]
    assert out["counts"]["4"] == 0 and out["counts"]["5"] == 1
