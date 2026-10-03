"""OWNER-DECISIONS 241, 2026-10-03: "Cargo with people yes. In general, even adults
wouldn't enjoy more stressful roads if they aren't in control of the ride. Let's also
call it passengers, as people bring dogs too."

The rider-visible name of the Cargo Bike load that is not cargo is "Cargo with
passengers"; it was "carrying people". The id, `people`, is what links, saved plans and
the API carry, so it does not change. The interface's own scan is
frontend/src/passengersName.test.ts; this one holds the back end and the documents.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.test import Client

from core import api, presets

REPO = Path(__file__).resolve().parent.parent
OLD_NAME = re.compile(r"carrying[\s_-]+people", re.IGNORECASE)


def _unquoted_hits(text: str) -> list[str]:
    """Each line where the old name is said in the document's own voice. Inside double quotes
    it is history (the owner's words, or "it was ..."), which stays as it was said."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in OLD_NAME.finditer(line):
            # `CARRYING_PEOPLE` is the id's constant, which does not change.
            if "_" in match.group(0):
                continue
            if line.count('"', 0, match.start()) % 2 == 0:
                hits.append(f"{number}: {line.strip()[:100]}")
    return hits


def _sources() -> list[Path]:
    found = sorted((REPO / "src").rglob("*.py"))
    found += sorted((REPO / "src").rglob("*.html"))
    found += sorted((REPO / "docs").glob("*.md"))
    found += [REPO / "README.md", REPO / "PLAN.md"]
    return [p for p in found if p.is_file()]


def test_the_back_end_and_the_documents_never_say_carrying_people_in_their_own_voice() -> None:
    sources = _sources()
    assert len(sources) > 30, "the scan found the source and the documents"
    found = {
        str(path.relative_to(REPO)): hits
        for path in sources
        if (hits := _unquoted_hits(path.read_text(encoding="utf-8")))
    }
    assert found == {}


def test_the_scan_sees_the_old_name_and_lets_a_quotation_stand() -> None:
    assert _unquoted_hits("a rider carrying people on a bike") == [
        "1: a rider carrying people on a bike"
    ]
    assert _unquoted_hits("Cargo-carrying-people stays") != []
    assert _unquoted_hits('it was "carrying people" until item 241') == []
    assert _unquoted_hits('the owner: "Cargo-carrying-people stays at 80"') == []
    assert _unquoted_hits("fine: Cargo with passengers") == []
    assert _unquoted_hits("presets.CARRYING_PEOPLE is the id") == []


def test_the_id_is_unchanged_so_links_keep_working() -> None:
    assert presets.CARRYING_PEOPLE == "people"
    assert presets.CARRYING_CARGO == "cargo"
    assert set(presets.CARGO_CARRYING_STRESS) == {"cargo", "people"}


def test_the_contract_still_takes_people_and_describes_passengers() -> None:
    field = api.RouteIn.model_fields["carrying"]
    assert "passengers" in (field.description or "")
    assert not OLD_NAME.search(field.description or "")
    assert api.RouteIn(points=[[-77.04, 38.91], [-77.01, 38.89]], preset="cargo", carrying="people")


@pytest.mark.django_db
def test_the_api_has_no_old_name_in_any_message_a_rider_can_be_shown() -> None:
    response = Client().post(
        "/api/route",
        data={
            "points": [[-77.04, 38.91], [-77.01, 38.89]],
            "preset": "default",
            "carrying": "people",
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert not OLD_NAME.search(response.content.decode())
