"""The 2026-11-13 DC own-picks files: our own rating on the DC streets that still took DDOT's 2020
level with no reasoning of ours (the owner, 2026-11-09: "We should always list our reasoning for
roads"; 2026-11-13: "Don't use my calls as one-offs but guides to inference"). Four files, one
approval each: same level as the map, calmer, busier, and big moves."""

from __future__ import annotations

import json
from collections import Counter

import pytest
from rebuild_fixtures import REPO

from pipeline.overrides import PUBLIC_NOTE_REFUSED_WORDS, file_rows, step_of

OVERRIDES = REPO / "fixtures" / "overrides"
FILES = sorted(OVERRIDES.glob("2026-11-13-owner-dc-own-picks-*.json"))


def test_there_are_four_files() -> None:
    assert [p.name.removeprefix("2026-11-13-owner-dc-own-picks-") for p in FILES] == [
        "agree.json",
        "big-moves.json",
        "busier.json",
        "calmer.json",
    ]


def test_every_way_is_rated_once_and_by_no_other_file() -> None:
    ours = Counter(
        row["osm_way_id"] for path in FILES for row in file_rows(json.loads(path.read_text()))
    )
    assert ours and max(ours.values()) == 1
    others = {
        int(row["osm_way_id"])
        for path in OVERRIDES.glob("*.json")
        if path not in FILES
        for row in file_rows(json.loads(path.read_text()))
        if row["kind"] == "stress"
    }
    assert not set(ours) & others


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_way_shows_our_reasoning_on_the_map(path) -> None:
    for group in json.loads(path.read_text())["groups"]:
        value = group["value"]
        note = value["public_note"]
        assert (value["visibility"], value["display"], value["annotation_status"]) == (
            "public",
            "map",
            "approved",
        )
        assert len(note) <= 200 and not PUBLIC_NOTE_REFUSED_WORDS.search(note)
        assert "DC own-picks group" in group["reason"] and "principle:" in group["reason"]
        if "DDOT" in note:
            assert "Agrees with DDOT's 2020 rating." in note or "DDOT's 2020 rating says" in note
        assert 1 <= step_of(value) <= 5
