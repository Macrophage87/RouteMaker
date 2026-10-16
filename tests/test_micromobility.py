"""Bikeshare docks and free e-bikes on the map (v0.7.0; core.micromobility).

GET /api/bikeshare/docks reads the sampled GBFS fixtures through a fake network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_bikeshare_nearby import dock, street
from test_gbfs import Clock, FakeNetwork, feed_wall

from core import gbfs, micromobility

REPO = Path(__file__).resolve().parents[1]
DOCKS = "/api/bikeshare/docks"
VIEW = "-77.06,38.88,-76.99,38.93"  # the sampled stations' part of DC


@pytest.fixture
def feeds(monkeypatch, db):
    net = FakeNetwork()
    monkeypatch.setattr(gbfs, "client", gbfs.Gbfs(net, Clock(), wall=feed_wall))
    return net


# --- The operators ------------------------------------------------------------------------


def test_capital_bikeshare_is_the_only_service():
    # Lime (internal-only) and Veo (no published data terms) were left out (the owner, 2026-10-15).
    assert [o.id for o in micromobility.OPERATORS] == ["cabi"]
    assert [o.id for o in micromobility.OPERATORS if micromobility.usable(o)] == ["cabi"]
    assert [o.id for o in micromobility.OPERATORS if o.on_by_default] == ["cabi"]


def test_an_operator_without_a_licence_is_never_fetched():
    unlicensed = micromobility.Operator(
        id="other",
        name="Other",
        initial="O",
        colour="#000000",
        discovery_url="https://example.com/gbfs.json",
        hosts=frozenset({"example.com"}),
        licensed=False,
        on_by_default=False,
        docked=False,
        credit="Other",
    )
    assert not micromobility.usable(unlicensed) and micromobility.client_for(unlicensed) is None


def test_sources_says_why_lime_and_veo_are_left_out():
    sources = (REPO / "docs" / "SOURCES.md").read_text()
    section = re.search(
        r"^## Other bikeshare and e-bike operators.*?\n(.*?)(?=^## )", sources, re.S | re.M
    )
    assert section, "docs/SOURCES.md has no section for the operators left out"
    text = section.group(1)
    assert "Lime" in text and "Veo" in text and "2026-10-15" in text


def test_every_licensed_operator_has_its_licence_recorded_in_sources():
    sources = (REPO / "docs" / "SOURCES.md").read_text()
    for o in micromobility.OPERATORS:
        if not o.licensed:
            continue
        section = re.search(rf"^## {re.escape(o.name)}\n(.*?)(?=^## )", sources, re.S | re.M)
        assert section, f"docs/SOURCES.md has no section for {o.name}"
        assert "- Licence:" in section.group(1) and f"- Credit: `{o.credit}`" in section.group(1)


def test_the_front_end_knows_the_same_operators():
    """frontend/src/lib/bikeshareDocks.ts KNOWN_OPERATORS: the same ids, names, initials and
    colours, so the Layers sheet before the server answers is the registry's."""
    text = (REPO / "frontend" / "src" / "lib" / "bikeshareDocks.ts").read_text()
    block = re.search(r"KNOWN_OPERATORS: readonly OperatorInfo\[\] = \[(.*?)\n\];", text, re.S)
    assert block, "KNOWN_OPERATORS not found"
    known = re.findall(
        r'id: "([^"]+)", name: "([^"]+)", initial: "([^"]+)", colour: "([^"]+)"', block.group(1)
    )
    assert known == [(o.id, o.name, o.initial, o.colour) for o in micromobility.OPERATORS]


def test_each_operator_has_an_initial_and_a_colour():
    initials = [o.initial for o in micromobility.OPERATORS]
    assert len(set(initials)) == len(initials) and all(len(i) == 1 for i in initials)
    assert all(re.fullmatch(r"#[0-9a-f]{6}", o.colour) for o in micromobility.OPERATORS)


# --- The view -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["", "1,2,3", "a,b,c,d", "-77,38,-78,39", "-77.3,38.8,-77.0,38.9", "-77.1,38.6,-77.0,38.9"],
)
def test_a_view_must_be_four_numbers_and_small(text):
    with pytest.raises(ValueError):
        micromobility.parse_bbox(text)


def test_docks_in_the_view_with_their_counts():
    snapshot = street(
        dock("Open", 0, 7, 3, ebikes=2),
        dock("Shut", 100, 4, 4, installed=False),
        dock("Silent", 200, 4, 4, age=3 * 3600),
        dock("Far", 50_000, 4, 4),
    )
    lon, lat = snapshot.stations[0].lon, snapshot.stations[0].lat
    box = (lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01)
    docks = {d.name: d for d in micromobility.docks_in(snapshot, box)}
    assert set(docks) == {"Open", "Shut", "Silent"}
    assert (docks["Open"].classic, docks["Open"].ebikes, docks["Open"].docks) == (5, 2, 3)
    assert docks["Shut"].closed and docks["Silent"].closed and not docks["Open"].closed


def test_free_bikes_have_no_ids_and_rounded_positions():
    snapshot = street()
    snapshot = gbfs.Snapshot(
        **{
            **snapshot.__dict__,
            "free_bikes": [gbfs.FreeBike("secret-id", -77.012345678, 38.9087654)],
        }
    )
    assert micromobility.free_bikes_in(snapshot, (-77.1, 38.8, -77.0, 39.0)) == [
        (-77.0123, 38.9088)
    ]


def test_the_counts_are_capped(monkeypatch):
    monkeypatch.setattr(micromobility, "MAX_DOCKS", 2)

    snapshot = street(*(dock(f"D{i}", i * 10, 1, 1) for i in range(5)))
    lon, lat = snapshot.stations[0].lon, snapshot.stations[0].lat
    assert (
        len(micromobility.docks_in(snapshot, (lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01))) == 2
    )


# --- The endpoint ---------------------------------------------------------------------------


def test_the_endpoint_answers_the_view(client, feeds):
    response = client.get(DOCKS, {"bbox": VIEW})
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    data = response.json()
    assert data["availability"] in ("live", "stale") and data["as_of"]
    assert data["docks"] and data["credit"] == ["Capital Bikeshare"]
    one = data["docks"][0]
    assert set(one) == {"id", "name", "lon", "lat", "classic", "ebikes", "docks", "closed"}
    assert all("bike_id" not in b and b["operator"] == "cabi" for b in data["free_bikes"])
    ops = {o["id"]: o for o in data["operators"]}
    assert ops["cabi"]["licensed"] and ops["cabi"]["on_by_default"]
    assert list(ops) == ["cabi"]


@pytest.mark.parametrize(
    "params",
    [
        {"bbox": "-78,38,-76,40"},
        {"bbox": VIEW, "operators": "uber"},
        # Left out (the owner, 2026-10-15): no longer operators at all.
        {"bbox": VIEW, "operators": "lime"},
        {"bbox": VIEW, "operators": "cabi,veo"},
        {"bbox": "x"},
    ],
)
def test_bad_views_and_operators_are_refused(client, feeds, params):
    response = client.get(DOCKS, params)
    assert response.status_code == 400 and response.json()["error"]


def test_a_feed_that_is_down_is_unavailable_not_an_error(client, feeds):
    feeds.down = True
    data = client.get(DOCKS, {"bbox": VIEW}).json()
    assert data["availability"] == "unavailable" and data["docks"] == []
