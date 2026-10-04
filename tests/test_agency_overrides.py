"""The override files the owner approved from the agency layers on 2026-10-01.

`fixtures/overrides/2026-10-01-owner-moco-lts5-avoid.json` (OWNER-DECISIONS 149, 181:
Montgomery Planning's LTS 5 as Avoid) and `2026-10-01-owner-baltimore-facilities.json`
(182: the City of Baltimore's bike facilities OSM lacks), written by
`scripts/analysis/compare_agency_lts.py`. They were proposals until the owner said "Load
it (Recommended)" and "Load Baltimore facilities"; what is checked here is that they pass
the loader's own validation, say what the owner approved and nothing more, and carry the
credit their licences ask for in the same change.
"""

from __future__ import annotations

import json
import re

import pytest
from rebuild_fixtures import REPO

OVERRIDES = REPO / "fixtures" / "overrides"
MOCO = OVERRIDES / "2026-10-01-owner-moco-lts5-avoid.json"
BALTIMORE = OVERRIDES / "2026-10-01-owner-baltimore-facilities.json"
FILES = [MOCO, BALTIMORE]


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_the_file_passes_the_loaders_validation(path) -> None:
    from core.management.commands.load_access_overrides import parse_file

    rows = parse_file(path.read_text(), path.name)
    assert rows


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_the_file_is_the_owners_decision_and_hidden(path) -> None:
    document = json.loads(path.read_text())
    assert document["decided"] == "2026-10-01"
    assert document["decided_by"] == "the deployment owner"
    assert document["status"].startswith("approved for loading by the owner on 2026-10-01")
    for row in document["rows"]:
        assert "PROPOSED" not in row["reason"]
        if row["kind"] == "stress":
            value = row["value"]
            assert value["visibility"] == "hidden"
            assert value["annotation_status"] == "approved"
            assert "public_note" not in value
            assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", value["adjustment_id"])
            assert len(value["adjustment_id"]) <= 64
        else:
            assert row["value"] == {"bicycle": "designated"}


def test_no_way_is_named_twice_across_the_approved_files() -> None:
    """The loader refuses a way named twice in one file and a disagreeing approved
    row on the same way; the generator leaves out ways another file curates."""
    others = {
        (row["kind"], int(row["osm_way_id"]))
        for path in OVERRIDES.glob("*.json")
        if path not in FILES
        for row in json.loads(path.read_text())["rows"]
    }
    new = [
        (row["kind"], int(row["osm_way_id"]))
        for path in FILES
        for row in json.loads(path.read_text())["rows"]
    ]
    assert len(new) == len(set(new))
    assert not set(new) & others


def test_the_montgomery_file_is_avoid_and_only_avoid() -> None:
    """OWNER-DECISIONS 149: the layer's LTS 5 maps to Avoid (tier 5) and nothing else."""
    document = json.loads(MOCO.read_text())
    assert {row["kind"] for row in document["rows"]} == {"stress"}
    assert {row["value"]["tier"] for row in document["rows"]} == {5}
    assert all("fb903d1ffbc84b219bdb47629bd02b82" in row["evidence"] for row in document["rows"])
    assert all(row["value"]["adjustment_id"].startswith("moco-lts5-") for row in document["rows"])
    assert all("LTS5, which we can mark as avoid" in row["reason"] for row in document["rows"])


def test_the_montgomery_file_groups_by_street_not_one_unnamed_bucket() -> None:
    """Review r1: "moco-lts5-unnamed" held 39 unrelated ways. Unnamed ways are grouped
    by where they are."""
    document = json.loads(MOCO.read_text())
    ids = {row["value"]["adjustment_id"] for row in document["rows"]}
    assert "moco-lts5-unnamed" not in ids
    assert all(
        re.fullmatch(r"moco-lts5-unnamed-\d+-\d+n-\d+-\d+w", aid)
        for aid in ids
        if aid.startswith("moco-lts5-unnamed")
    )


def test_the_baltimore_file_never_raises_a_tier() -> None:
    """A facility OSM lacks can only make a road calmer; a stress row naming a tier
    above the way's own would be a different claim."""
    document = json.loads(BALTIMORE.read_text())
    stress = [row for row in document["rows"] if row["kind"] == "stress"]
    assert stress
    for row in stress:
        now = int(row["evidence"].rsplit("tier now ", 1)[1].rstrip("."))
        assert row["value"]["tier"] < now
        assert "Load Baltimore facilities" in row["reason"]


def test_the_credits_ride_with_the_rows() -> None:
    """OWNER-DECISIONS 181: the Montgomery County Planning credit in the same change,
    in the words its licence asks for; Baltimore's, brief since 306 (it was the owner's
    line of 159), with the full reference in docs/SOURCES.md."""
    from core import routing

    credits = " ".join(routing.ATTRIBUTION)
    assert "Montgomery County Planning Department" in credits
    assert "Open Baltimore" in credits
    frontend = (REPO / "frontend" / "src" / "lib" / "credits.json").read_text()
    assert "Montgomery County Planning Department" in frontend
    assert "Open Baltimore" in frontend


def test_nothing_is_left_proposed() -> None:
    assert not list((OVERRIDES / "proposed").glob("*.json"))


APPROVED = REPO / "reports" / "data-comparison" / "owner-approved-override-ways.json"


@pytest.mark.parametrize(("path", "item"), [(MOCO, "181"), (BALTIMORE, "182")])
def test_the_file_keeps_within_the_rows_the_owner_approved(path, item) -> None:
    """Review r2: the re-derived Baltimore file had five stress ways the owner never
    saw. A file keeps within the ways (and, for access rows, the ways) of the
    proposal the owner approved; the report lists what it drops or changes."""
    approved = json.loads(APPROVED.read_text())[item]
    assert approved["file"] == path.name
    rows = json.loads(path.read_text())["rows"]
    stress = {int(row["osm_way_id"]) for row in rows if row["kind"] == "stress"}
    access = {int(row["osm_way_id"]) for row in rows if row["kind"] == "access"}
    assert stress <= {int(way) for way in approved["stress"]}
    assert access <= set(approved.get("access", []))


def test_the_approved_record_is_what_the_owner_was_shown() -> None:
    approved = json.loads(APPROVED.read_text())
    assert len(approved["181"]["stress"]) == 411
    assert len(approved["182"]["stress"]) == 264
    assert len(approved["182"]["access"]) == 180
