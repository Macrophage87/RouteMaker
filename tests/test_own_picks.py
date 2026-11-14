"""The 2026-11-09 own-picks files: our own rating on every road the earlier reviews left to an
agency or the formula (the owner, 2026-11-09: "We should always list our reasoning for roads.
It should be done independently without looking at agency data. If it agrees, we state our
reasoning and then that it agrees. If it disagrees we need to have more justification.")"""

from __future__ import annotations

import json
from collections import Counter

import pytest
from rebuild_fixtures import REPO

from pipeline.overrides import PUBLIC_NOTE_REFUSED_WORDS, file_rows, step_of

OVERRIDES = REPO / "fixtures" / "overrides"
FILES = sorted(OVERRIDES.glob("2026-11-09-owner-*-own-picks.json"))


def test_there_is_one_file_per_state() -> None:
    assert [p.name.split("-")[4] for p in FILES] == ["md", "va", "wv"]


def test_no_way_is_also_named_by_another_file() -> None:
    """A way another file already rates keeps that file's row (the generator skips it)."""
    others = Counter(
        int(row["osm_way_id"])
        for path in OVERRIDES.glob("*.json")
        if path not in FILES
        for row in file_rows(json.loads(path.read_text()))
        if row["kind"] == "stress"
    )
    ours = [row["osm_way_id"] for path in FILES for row in file_rows(json.loads(path.read_text()))]
    assert len(ours) == len(set(ours))
    # Unless a later file retires our row for its own (the North Bethesda bike lanes, the owner's
    # report from the street, 2026-11-10: Woodglen Drive 553709201).
    retired = {
        int(row["osm_way_id"])
        for path in OVERRIDES.glob("*.json")
        if path not in FILES
        for row in json.loads(path.read_text()).get("retire", [])
        if row["kind"] == "stress"
    }
    assert not (set(ours) - retired) & set(others)
    # The 2026-11-12 recheck (the owner: "Drop the bump, through streets checked", and the
    # Arlington comfort index cited in every Arlington Why line) retires each row it replaces.
    recheck = {
        int(row["osm_way_id"])
        for row in json.loads(
            (OVERRIDES / "2026-11-12-owner-side-streets-and-arlington-index.json").read_text()
        )["retire"]
    }
    # And the 2026-11-13 withdraw-only drafts, whose rows rested on a count the matcher now
    # refuses (an MDOT SHA count past a busy junction; a boulevard's count on its service road).
    withdrawn = {
        int(row["osm_way_id"])
        for path in OVERRIDES.glob("2026-11-13-retire-*.json")
        for row in json.loads(path.read_text())["retire"]
    }
    # The 2026-11-13 re-rate of every road with one brief retires each row whose level it changes.
    rerate = {
        int(row["osm_way_id"])
        for path in OVERRIDES.glob("2026-11-13-owner-*-rerate*.json")
        for row in json.loads(path.read_text())["retire"]
    }
    # It replaces the North Bethesda row on Woodglen Drive too (the owner: "Ignore my own calls").
    assert set(ours) & retired - recheck - withdrawn - rerate == set()
    assert 553709201 in rerate


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
        assert "own-picks group" in group["reason"]
        # A note that names an agency says whether it agrees or what it says.
        for agency in ("MDOT SHA's rating", "Montgomery County's rating"):
            if agency in note:
                assert "agree" in note or f"{agency} says" in note or "varies" in note


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_rural_road_open_to_cars_is_rated_below_the_floor(path) -> None:
    """The rural floor (the owner, 2026-10-13): "LTS1 is something kids can go on"."""
    for group in json.loads(path.read_text())["groups"]:
        if ", rural, " in group["evidence"] and any(
            f"{hw}, rural" in group["evidence"]
            for hw in ("primary", "secondary", "tertiary", "trunk", "motorway")
        ):
            assert step_of(group["value"]) >= 2, group["value"]["adjustment_id"]
