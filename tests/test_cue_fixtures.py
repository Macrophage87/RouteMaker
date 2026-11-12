"""The shared cue fixtures (fixtures/cues, backlog 2026-11-12 item 3): the connector's cue cards
(core/cue_cards.py cue_rows) list the same rows, in the same order, as Ride's cue sheet strip and
phone images (frontend/src/lib/cueSheetPdf.ts cueRows), which the cue bench writes to
fixtures/cues/expected/ (frontend: node scripts/cueBench.ts --update).

The routes are made-up trips planned once (scripts/cue_bench_capture.py), never anyone's ride."""

import json
from pathlib import Path

import pytest

from core.cue_cards import cue_rows

CUES = Path(__file__).resolve().parent.parent / "fixtures" / "cues"
NAMES = sorted(p.stem for p in CUES.glob("*.json") if p.name != "trips.json")


def arrow_key(arrow: dict) -> str:
    """frontend/src/lib/cueBench.ts arrowKey."""
    kind = arrow["kind"]
    if kind == "turn":
        return f"turn{' across' if arrow.get('across') else ''} {','.join(arrow['moves'])}"
    if kind == "stop":
        return f"stop {'' if arrow.get('number') is None else arrow['number']}".strip()
    return kind


def test_there_are_fixtures_and_each_has_its_rows():
    assert len(NAMES) >= 10
    for name in NAMES:
        assert (CUES / "expected" / f"{name}.json").exists(), name
        assert (CUES / "transcripts" / f"{name}.txt").exists(), name


@pytest.mark.parametrize("name", NAMES)
def test_cue_cards_list_what_ride_lists(name):
    fixture = json.loads((CUES / f"{name}.json").read_text())
    expected = json.loads((CUES / "expected" / f"{name}.json").read_text())
    got = [
        {"turn": r["turn"], "road": r["road"], "then": r["then"], "arrow": arrow_key(r["arrow"])}
        for r in cue_rows(fixture["route"])
    ]
    assert got == expected


def test_fixtures_hold_no_ride():
    """Made-up trips only: a planned answer's fields, never a track, a time of day or a name."""
    for name in NAMES:
        fixture = json.loads((CUES / f"{name}.json").read_text())
        assert set(fixture) == {"name", "about", "route"}
        assert set(fixture["route"]) <= {
            "preset",
            "geometry",
            "distance_m",
            "duration_s",
            "time_marks",
            "description",
            "leg_ends",
            "arrival_side",
            "leg_arrival_sides",
            "stress_spans",
        }
