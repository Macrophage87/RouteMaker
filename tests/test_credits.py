"""Every data source behind what a rider sees is cited (OWNER-DECISIONS 301: "Even if
the license doesn't require crediting them, sources need citing"), briefly, with the
full reference on the sources page (306: "keep it brief and put the full information
in documentation. Sort of like how you'd cite in a paragraph"): each credit the API
and the front end display has a `Credit:` line in docs/SOURCES.md, and each credited
source there is displayed. The internal-comparison layers (Arlington's Bike Comfort
Index, Alexandria's Transport Streets: OWNER-DECISIONS 152, 153, 155) are cited
nowhere a rider sees."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core import geocode, routing

REPO = Path(__file__).resolve().parents[1]
SOURCES = REPO / "docs" / "SOURCES.md"
FRONTEND_CREDITS = REPO / "frontend" / "src" / "lib" / "credits.json"
NEVER = ("arlington", "alexandria", "bike comfort index", "transport streets")
# A brief credit is a short name: no description of what it is used for (306).
LONGEST_M = 60


def page_credits() -> list[str]:
    """The `Credit:` values on the sources page, in its order."""
    return re.findall(r"^- Credit: `([^`]+)`$", SOURCES.read_text(), re.M)


def plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def matches(credit: str) -> str | None:
    """The sources page's credit that `credit` cites (it begins with it), or None."""
    hits = [c for c in page_credits() if plain(credit).startswith(c)]
    return max(hits, key=len) if hits else None


def frontend_credits() -> list[str]:
    return [entry["text"] for entry in json.loads(FRONTEND_CREDITS.read_text())]


def displayed() -> list[tuple[str, str]]:
    return (
        [("route", c) for c in routing.ATTRIBUTION]
        + [("place search", c) for c in geocode.ATTRIBUTION]
        + [("map", c) for c in frontend_credits()]
    )


def test_the_page_lists_each_credit_once() -> None:
    credits = page_credits()
    assert len(credits) >= 9 and len(set(credits)) == len(credits)


@pytest.mark.parametrize(("where", "credit"), displayed())
def test_every_displayed_credit_is_on_the_sources_page(where, credit) -> None:
    assert matches(credit), f"{where}: {credit!r} has no Credit: line in docs/SOURCES.md"


@pytest.mark.parametrize(("where", "credit"), displayed())
def test_every_displayed_credit_is_brief(where, credit) -> None:
    assert len(plain(credit).split(": http")[0]) <= LONGEST_M, (where, credit)


def test_every_credited_source_is_displayed() -> None:
    shown = {matches(c) for _where, c in displayed()}
    assert set(page_credits()) == shown


def test_the_licence_forms_are_kept() -> None:
    """ODbL's credit form, and CC BY 4.0's licence and change named, linked in the API."""
    for credits in (routing.ATTRIBUTION, geocode.ATTRIBUTION, frontend_credits()):
        assert plain(credits[0]).startswith("© OpenStreetMap contributors")
    dc = [c for c in routing.ATTRIBUTION if c.startswith("DC Open Data")]
    assert dc and "creativecommons.org/licenses/by/4.0" in dc[0]


def test_what_each_answer_is_made_from_is_cited() -> None:
    route = {matches(c) for c in routing.ATTRIBUTION}
    assert {
        "© OpenStreetMap contributors",
        "DC Open Data (CC BY 4.0, adapted)",
        "VDOT",
        "Open Baltimore",
        "Montgomery County Planning Department",
        "USGS 3DEP",
        "U.S. Census Bureau",
    } <= route
    assert {matches(c) for c in geocode.ATTRIBUTION} == {"© OpenStreetMap contributors", "Photon"}


def test_the_internal_comparison_layers_are_cited_nowhere() -> None:
    for _where, credit in displayed():
        assert not any(word in credit.lower() for word in NEVER), credit
    shown = SOURCES.read_text().split("## Used inside the project only")[0].lower()
    assert not any(word in shown for word in NEVER)
