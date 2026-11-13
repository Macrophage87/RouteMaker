"""The 2026-11-13 DC own-picks files: our own rating on the DC streets that still took DDOT's 2020
level with no reasoning of ours (the owner, 2026-11-09: "We should always list our reasoning for
roads"; 2026-11-13: "Don't use my calls as one-offs but guides to inference"). Four files, one
approval each: same level as the map, calmer, busier, and big moves."""

from __future__ import annotations

import json
import re
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


LEVEL = re.compile(
    r"(?<![\d.,\-])([1-5](?:\.5)?)(?![\d,]|\.\d|\s*(?:-?lanes?|-?lane\b|mph|mi\b|ft|%|percent|-?way|"
    r"cars|blocks?|signals?|times|st\b|nd\b|rd\b|th\b))",
    re.I,
)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_the_why_line_names_no_level_but_the_rows_own(path) -> None:
    """A skeptic, a hold or an owner call that changes the level also changes the Why line
    (the rebuild readiness check, 2026-11-13, found notes still naming the rater's level)."""
    for group in json.loads(path.read_text())["groups"]:
        level = step_of(group["value"])
        ours = group["value"]["public_note"].split(" DDOT's")[0].split(" Agrees")[0]
        assert all(float(m.group(1)) == level for m in LEVEL.finditer(ours)), group["value"]


def test_whole_street_owner_calls_hold() -> None:
    """16th St NW and Canal Rd NW at 4 (OWNER-DECISIONS 179, 197; fixtures/known-roads)."""
    for path in FILES:
        for group in json.loads(path.read_text())["groups"]:
            names = {f.get("name") for f in (group.get("fingerprints") or {}).values()}
            if names & {"16th Street Northwest", "Canal Road Northwest"}:
                assert step_of(group["value"]) == 4, group["value"]["adjustment_id"]
