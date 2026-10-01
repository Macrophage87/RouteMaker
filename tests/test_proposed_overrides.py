"""The proposed override files under fixtures/overrides/proposed/.

Proposals for the owner (the Montgomery County LTS 5 roads as Avoid; the Baltimore
facilities OSM lacks), written by `scripts/analysis/compare_agency_lts.py` and
**not loaded**: the loader reads the files it is given and these are in a
subdirectory the approved-file tests do not look in. What is checked here is that
they stay loadable - the loader's own validation passes on them - and that they
stay proposals: hidden, no public note, annotation `proposed`, nothing approved or
decided, so that loading one is a decision somebody makes rather than a default.
"""

from __future__ import annotations

import json

import pytest
from rebuild_fixtures import REPO

PROPOSED = REPO / "fixtures" / "overrides" / "proposed"
FILES = sorted(PROPOSED.glob("*.json"))


def test_there_are_proposals_to_check() -> None:
    assert {path.name for path in FILES} >= {
        "PROPOSED-moco-lts5-avoid.json",
        "PROPOSED-baltimore-facilities.json",
    }


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_a_proposed_file_passes_the_loaders_validation(path) -> None:
    from core.management.commands.load_access_overrides import parse_file

    rows = parse_file(path.read_text(), path.name)
    assert rows


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_a_proposal_is_not_approved_decided_or_public(path) -> None:
    document = json.loads(path.read_text())
    assert document["decided"] is None
    assert "PROPOSED" in document["decided_by"] and "not loaded" in document["decided_by"]
    assert document["status"].startswith("proposed")
    for row in document["rows"]:
        assert "PROPOSED, not loaded" in row["reason"]
        value = row["value"]
        if row["kind"] == "stress":
            assert value["visibility"] == "hidden"
            assert value["annotation_status"] == "proposed"
            assert "public_note" not in value
        else:
            assert set(value) == {"bicycle"}


def test_the_montgomery_proposal_is_avoid_and_only_avoid() -> None:
    """OWNER-DECISIONS 149: the layer's LTS 5 maps to Avoid (tier 5) and nothing else."""
    document = json.loads((PROPOSED / "PROPOSED-moco-lts5-avoid.json").read_text())
    assert {row["kind"] for row in document["rows"]} == {"stress"}
    assert {row["value"]["tier"] for row in document["rows"]} == {5}
    assert all("fb903d1ffbc84b219bdb47629bd02b82" in row["evidence"] for row in document["rows"])
    assert all(
        not row["value"]["adjustment_id"].startswith("baltimore") for row in document["rows"]
    )


def test_the_baltimore_proposal_never_raises_a_tier() -> None:
    """A facility OSM lacks can only make a road calmer; a stress row here that
    named a tier above the way's own would be a different claim."""
    document = json.loads((PROPOSED / "PROPOSED-baltimore-facilities.json").read_text())
    for row in document["rows"]:
        if row["kind"] == "stress":
            assert "tier now" in row["evidence"]
            now = int(row["evidence"].rsplit("tier now ", 1)[1].rstrip("."))
            assert row["value"]["tier"] < now
