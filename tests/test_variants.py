from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.variants import Variant, inject, is_trail_class, variant_for


def test_standard_passes_tags_through() -> None:
    tags = {"highway": "residential"}
    assert inject(Variant.STANDARD, tags) == tags


def test_no_trail_drops_trail_class_ways() -> None:
    """Dropped rather than tagged inaccessible: a way tagged bicycle=no still
    occupies the graph and still lands in trace results."""
    assert inject(Variant.NO_TRAIL, {"highway": "cycleway"}) is None
    assert inject(Variant.NO_TRAIL, {"highway": "residential"}) is not None


def test_trail_class_ignores_the_bicycle_tag() -> None:
    """DC-area trails are tagged inconsistently, so a definition that consulted
    the bicycle tag would classify the same trail differently along its length."""
    assert is_trail_class({"highway": "path", "bicycle": "designated"})
    assert is_trail_class({"highway": "path", "bicycle": "no"})


def test_sidepath_bridges_count_as_trail_class() -> None:
    """Most Potomac and Anacostia crossings are bike-legal only by a sidepath;
    missing them would leave the no-trail variant thinking they are roadways.

    The id is a parameter, not a tag. The earlier version read `_osm_id` from the
    tag dict, which only this test ever set - a way read from a real PBF carries
    OSM's own tags and nothing else, so the lookup could never match in the
    pipeline while the test passed.
    """
    tags = {"highway": "trunk"}
    assert not is_trail_class(tags, 99)
    assert is_trail_class(tags, 99, frozenset({99}))
    assert not is_trail_class(tags, 98, frozenset({99}))


def test_ebike_bars_only_where_electric_bicycles_are_barred() -> None:
    barred = inject(Variant.EBIKE, {"highway": "path", "electric_bicycle": "no"})
    allowed = inject(Variant.EBIKE, {"highway": "path"})
    assert barred["bicycle"] == "no"
    assert "bicycle" not in allowed


def test_variant_selection_from_toggles() -> None:
    assert variant_for(allow_trails=True, ebike_rules=False) is Variant.STANDARD
    assert variant_for(allow_trails=True, ebike_rules=True) is Variant.EBIKE
    assert variant_for(allow_trails=False, ebike_rules=False) is Variant.NO_TRAIL


def test_exclusive_combination_is_refused_not_guessed() -> None:
    """The UI disables the combination and explains why; the pipeline refuses it
    rather than silently picking one."""
    with pytest.raises(ValueError, match="mutually exclusive"):
        variant_for(allow_trails=False, ebike_rules=True)


# The checked-in crossings fixture, asserted by the legality tagger as the
# quality bar asks. Until now nothing anywhere opened this file: every row
# carried osm_way_id 0, so the sidepath set was empty, so the no-trail variant
# treated the Key Bridge sidewalk as an ordinary roadway - and the pipeline test
# wrote its own synthetic crossings file, so the committed one was never read.

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "crossings" / "potomac-anacostia.json"


def crossing_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text())


class FakeWay:
    def __init__(self, osm_id: int, tags: dict[str, str]) -> None:
        self.osm_id = osm_id
        self.tags = tags


def extract_from_fixture() -> list[FakeWay]:
    """One bridge way per row, named as the fixture names it."""
    return [
        FakeWay(1000 + index, {"highway": "secondary", "bridge": "yes", "name": row["name"]})
        for index, row in enumerate(crossing_rows())
    ]


def test_the_committed_crossings_fixture_is_well_formed() -> None:
    rows = crossing_rows()
    assert rows, "the fixture is the checked-in list the plan calls for"
    for row in rows:
        assert row["name"]
        assert isinstance(row["roadway_bicycle_legal"], bool)
        assert isinstance(row["sidepath_only"], bool)
        # Not a legal statement about access: it records what a rider can use and
        # who to ask, which is why every row carries an authority and a note.
        assert row["police"] and row["note"]


def test_every_sidepath_only_crossing_is_trail_class_on_the_no_trail_variant() -> None:
    """The failure this exists to prevent: the router handing a mass ride the Key
    Bridge sidewalk - an eight-foot path with no way off it mid-span, for a field
    of hundreds."""
    from pipeline.variants import Variant, inject, is_trail_class, resolve_sidepath_bridge_ids

    rows = crossing_rows()
    ways = extract_from_fixture()
    bridge_ids, unmatched = resolve_sidepath_bridge_ids(rows, ways)
    assert not unmatched, "every row in the fixture must resolve against its own names"

    for row, way in zip(rows, ways, strict=True):
        expected = row["sidepath_only"] or row["roadway_bicycle_legal"] is False
        assert is_trail_class(way.tags, way.osm_id, bridge_ids) is expected, row["name"]
        dropped = inject(Variant.NO_TRAIL, way.tags, way.osm_id, bridge_ids) is None
        assert dropped is expected, f"{row['name']} on the no-trail variant"


def test_a_crossing_the_extract_does_not_carry_is_reported_rather_than_ignored() -> None:
    """A way id is the wrong thing to check in - OSM ids change whenever a mapper
    splits a bridge - so these resolve by name, and a name that finds nothing
    means either the clip moved or the name changed. Either way the sidepath rule
    is not biting on that bridge, and an operator needs told which."""
    from pipeline.variants import resolve_sidepath_bridge_ids

    ids, unmatched = resolve_sidepath_bridge_ids(crossing_rows(), [])
    assert ids == frozenset()
    assert "Key Bridge" in unmatched
    assert "Arlington Memorial Bridge" not in unmatched, "it is not a sidepath-only crossing"


def test_a_street_named_after_a_crossing_does_not_inherit_its_legality() -> None:
    """The approach to Key Bridge is not Key Bridge."""
    from pipeline.variants import resolve_sidepath_bridge_ids

    approach = FakeWay(2000, {"highway": "secondary", "name": "Key Bridge"})
    ids, _unmatched = resolve_sidepath_bridge_ids(crossing_rows(), [approach])
    assert 2000 not in ids


def test_an_explicitly_recorded_way_id_is_still_honoured() -> None:
    """Name matching is the default, not the only path: where someone has pinned
    an id against the clipped extract, that id is used."""
    from pipeline.variants import resolve_sidepath_bridge_ids

    row = {"name": "Some Bridge", "osm_way_id": 4242, "sidepath_only": True}
    ids, unmatched = resolve_sidepath_bridge_ids([row], [])
    assert ids == frozenset({4242})
    assert unmatched == []
