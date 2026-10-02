"""The contraflow closure on real District streets.

The tags in fixtures/contraflow/dc-contraflow-streets.json are nine one-way
streets copied from the clipped region extract (R Street NE, 8th Street NW,
M Street NW and others), each carrying a contraflow provision in the shape the
District's mappers use. They are read through the no-trail variant's tag
injection and upstream's own transform, as the Lua-level tests do, so no graph
is built: what is asserted is what a built no-trail graph would hold for each of
them.

Owner, 2026-10-02 (items 192 and 193): "contraflow lanes are not for group rides
or mass rides, many routing engines put people on this when it's not
appropriate."; and, for a Group Ride with trails on, "with trails on that's
fine".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_lua_remap import CONTRAFLOW_WRITES, _bike_access

from pipeline.variants import Variant, has_contraflow_tag, inject
from routemaker.facility import facility

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "contraflow"
WAYS = json.loads((FIXTURE / "dc-contraflow-streets.json").read_text())["ways"]
IDS = [f"{way['name']} ({way['osm_way_id']})" for way in WAYS]


def test_the_fixture_is_what_it_says() -> None:
    assert len(WAYS) == 9
    assert {way["tags"]["oneway"] for way in WAYS} == {"yes"}
    # Every one of them is named by a contraflow tag but one, which is the
    # lanes-on-both-sides shape upstream reads as a second direction.
    assert sum(has_contraflow_tag(way["tags"]) for way in WAYS) == len(WAYS)
    assert any(way["tags"].get("cycleway:both") == "lane" for way in WAYS)
    assert any(way["tags"].get("cycleway:left") == "opposite_lane" for way in WAYS)
    assert any(way["tags"].get("cycleway:left") == "lane" for way in WAYS)


@pytest.mark.parametrize("way", WAYS, ids=IDS)
def test_the_standard_graph_rides_against_the_traffic_and_the_no_trail_graph_does_not(way) -> None:
    tags = way["tags"]
    assert _bike_access(tags) == ("true", "true"), "the control: contraflow on the standard graph"
    for variant in (Variant.STANDARD, Variant.WEEKEND, Variant.EBIKE):
        assert inject(variant, dict(tags), way["osm_way_id"]) == tags, variant.value
    closed = inject(Variant.NO_TRAIL, dict(tags), way["osm_way_id"])
    assert _bike_access(closed) == ("true", "false"), closed


@pytest.mark.parametrize("way", WAYS, ids=IDS)
def test_the_closure_writes_only_the_contraflow_keys(way) -> None:
    tags = way["tags"]
    closed = inject(Variant.NO_TRAIL, dict(tags), way["osm_way_id"])
    changed = {key for key in {*tags, *closed} if tags.get(key) != closed.get(key)}
    assert changed <= CONTRAFLOW_WRITES, changed - CONTRAFLOW_WRITES
    # Rewritten, never removed: a deleted key would come back in the written
    # extract with OSM's value.
    assert set(tags) <= set(closed)


# The facility class `routemaker.facility` reads from each street's own tags, which
# is what the map layer draws and what the segment table stores.
SOURCE_FACILITY = {
    112192545: "none",  # R Street NE: a contraflow lane is no facility with the traffic
    130927103: "none",
    29235004: "lane",  # 11th Street NW: a lane on the left, with a sharrow on the right
    6257737: "lane",
    6061168: "lane",
    6052569: "none",
    50511364: "none",
    131463016: "lane",
    50797092: "none",
}


@pytest.mark.parametrize("way", WAYS, ids=IDS)
def test_the_map_and_stress_classification_are_not_the_variants(way) -> None:
    """The rebuild classifies stress and facility from the way's own tags, once,
    and hands the answer to every variant (`run.inject_tags` reads
    `stress_by_way` and `facility_by_way`, not the injected tags), so a street's
    lane still draws as a lane and the tiles are the standard pipeline's. The
    injection neither reads nor changes the classifier's input."""
    tags = way["tags"]
    before = json.loads(json.dumps(tags))
    inject(Variant.NO_TRAIL, tags, way["osm_way_id"])
    assert tags == before, "the injection handed back a copy; the source tags are untouched"
    assert facility(tags).value == SOURCE_FACILITY[way["osm_way_id"]]


def test_the_classifier_would_answer_differently_on_the_closed_tags() -> None:
    """Why the order matters: 11th Street NW is a lane on the map and, read
    from its no-trail routing tags, no longer one. The pipeline never does the
    second."""
    way = next(w for w in WAYS if w["osm_way_id"] == 29235004)
    closed = inject(Variant.NO_TRAIL, dict(way["tags"]), way["osm_way_id"])
    assert facility(way["tags"]).value == "lane"
    assert facility(closed).value == "none"
