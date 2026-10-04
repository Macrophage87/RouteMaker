"""Every data source the planner's answers are made from is cited (OWNER-DECISIONS 301:
"Even if the license doesn't require crediting them, sources need citing"), and the
internal-comparison layers (Arlington's Bike Comfort Index, Alexandria's Transport
Streets: OWNER-DECISIONS 152, 153, 155) are cited nowhere, as they are used nowhere a
rider sees. The front end's map credits are held to the same list in
frontend/src/lib/credits.test.ts."""

from __future__ import annotations

import pytest

from core import geocode, routing

# What each answer is made from, and the words that cite it.
ROUTE_SOURCES = {
    "OpenStreetMap (the route, its roads and their stress)": "OpenStreetMap contributors, ODbL",
    "DDOT traffic volume and the Central Business District": (
        "District Department of Transportation"
    ),
    "VDOT traffic volume": "Virginia Department of Transportation",
    "the Architect of the Capitol boundary": "Architect of the Capitol",
    "DC's Roadway Block": "Roadway Block, District Department of Transportation (DDOT) / DC GIS",
    "Baltimore's street, bike facility and trail layers": "City of Baltimore, Open Baltimore",
    "Montgomery Planning's Bicycle LTS (the Avoid roads)": "Montgomery County Planning Department",
    "USGS 3DEP elevation (the climb and the effort)": "USGS 3D Elevation Program",
}
GEOCODE_SOURCES = {
    "OpenStreetMap (the places)": "OpenStreetMap contributors, ODbL",
    "Photon (the place search)": "Photon (komoot)",
}
NEVER = ("arlington", "alexandria", "bike comfort index", "transport streets")


@pytest.mark.parametrize(("source", "words"), sorted(ROUTE_SOURCES.items()))
def test_every_route_source_is_cited(source, words) -> None:
    assert any(words in line for line in routing.ATTRIBUTION), source


@pytest.mark.parametrize(("source", "words"), sorted(GEOCODE_SOURCES.items()))
def test_every_place_search_source_is_cited(source, words) -> None:
    assert any(words in line for line in geocode.ATTRIBUTION), source


def test_each_route_credit_cites_a_listed_source() -> None:
    """No credit for a source the list does not know of: a new one is added to both."""
    for line in routing.ATTRIBUTION:
        assert any(words in line for words in ROUTE_SOURCES.values()), line


def test_the_internal_comparison_layers_are_cited_nowhere() -> None:
    for line in (*routing.ATTRIBUTION, *geocode.ATTRIBUTION):
        assert not any(word in line.lower() for word in NEVER), line
