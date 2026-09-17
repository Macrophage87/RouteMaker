from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.variants import (
    Variant,
    inject,
    is_sidepath_only,
    is_trail_class,
    resolve_bridge_bicycle_legality,
    resolve_sidepath_bridge_ids,
    unverified_crossing_names,
    variant_for,
)


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


def test_is_trail_class_takes_the_highway_tag_alone() -> None:
    """Whether a way is trail class is one question, asked once and answered
    the same everywhere: the shared per-way `trail_class` tag (all three
    variants) and the segment table's `is_trail_class` column both read this
    function, and a roadway that happens to be a sidepath-only bridge is not
    trail class for either of them - Chain Bridge's roadway is an ordinary,
    bike-legal road on the segment table and on the standard and e-bike
    variants, even though the no-trail variant refuses to route across it.
    Folding the sidepath lookup in here was the bug: Chain Bridge's roadway
    came out trail-class on every variant and polluted Trailmaxxing's
    road-exposure report, which counts trail mileage by this exact flag."""
    assert not is_trail_class({"highway": "trunk"})
    assert not is_trail_class({"highway": "secondary", "bridge": "yes", "name": "Chain Bridge"})
    assert is_trail_class({"highway": "path"})


def test_sidepath_bridges_are_dropped_only_by_the_no_trail_variant(): # noqa: D103
    """The no-trail variant's own drop decision, not `is_trail_class`, is where
    a sidepath-only bridge's roadway is excluded - and only from that one
    variant. The id is a parameter rather than a tag: an earlier version read
    it from `tags["_osm_id"]`, which only a test ever set, so the lookup could
    never match a way read from a real PBF while the test passed."""
    tags = {"highway": "trunk"}
    # is_trail_class no longer acts on the sidepath id, whether or not a
    # caller passes it - accepted only so run.py's two existing call sites
    # (the derived `trail_class` tag, the segment table's `is_trail_class`
    # column) do not have to change to get the fix.
    assert not is_trail_class(tags)
    assert not is_trail_class(tags, 99, frozenset({99}))
    # But inject() on the no-trail variant still drops the way when its id is
    # in the sidepath set, and only on that variant.
    assert inject(Variant.NO_TRAIL, tags, 99, frozenset({99})) is None
    assert inject(Variant.NO_TRAIL, tags, 98, frozenset({99})) is not None
    assert inject(Variant.STANDARD, tags, 99, frozenset({99})) is not None
    assert inject(Variant.EBIKE, tags, 99, frozenset({99})) is not None


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


class TestIsSidepathOnly:
    """`is_sidepath_only` reads one column, `sidepath_only`, not two OR'd
    together. Stated directly on synthetic rows rather than against the
    checked-in fixture, because the earlier version of this test recomputed
    the production disjunct from the fixture's own fields and asserted the
    result matched itself - it could not fail no matter which two columns the
    function actually read. These rows are built so the two columns disagree,
    which the checked-in fixture's rows did not always do before round 3."""

    def test_reads_sidepath_only_when_true(self) -> None:
        assert is_sidepath_only({"sidepath_only": True, "roadway_bicycle_legal": True})

    def test_does_not_infer_sidepath_from_illegal_roadway_alone(self) -> None:
        """The disjunct this replaces: a roadway barred outright with no
        sidepath (Theodore Roosevelt Bridge, American Legion Bridge) must not
        be treated as sidepath-only - there is no sidepath to route onto."""
        barred_with_no_sidepath = {"sidepath_only": False, "roadway_bicycle_legal": False}
        assert not is_sidepath_only(barred_with_no_sidepath)

    def test_a_legal_roadway_can_still_be_sidepath_only(self) -> None:
        """Key Bridge and Chain Bridge: the roadway is legal, but the mass-ride
        provision is still the sidepath."""
        assert is_sidepath_only({"sidepath_only": True, "roadway_bicycle_legal": True})


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
    """One bridge way per row, named as a real OSM way would be - which, for a
    row carrying `osm_names`, is the OSM spelling, not this file's label. A
    fixture that used the label here for a row where the two differ (Key
    Bridge / Francis Scott Key Bridge) would never be exercising the
    `osm_names` lookup at all, only the label matching itself."""
    return [
        FakeWay(
            1000 + index,
            {
                "highway": "secondary",
                "bridge": "yes",
                "name": (row.get("osm_names") or [row["name"]])[0],
            },
        )
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


def test_the_fixture_has_a_row_barred_with_no_sidepath_alternative() -> None:
    """Domain finding (b): at least one crossing where roadway access is
    barred and there is no sidepath standing in - the case that pulls
    `sidepath_only` and `roadway_bicycle_legal` apart and would be lost if
    someone re-introduced the OR."""
    barred_outright = [
        row
        for row in crossing_rows()
        if row["roadway_bicycle_legal"] is False and row["sidepath_only"] is False
    ]
    assert barred_outright, "no row demonstrates a bar with no sidepath alternative"


def test_the_fixtures_two_legality_columns_are_not_perfectly_correlated() -> None:
    """Test-quality F8: the earlier fixture's `sidepath_only` and
    `roadway_bicycle_legal` happened to agree on every row, which is exactly
    what let `is_sidepath_only`'s OR ship as a silent no-op. Guard against
    that shape recurring."""
    rows = crossing_rows()
    pairs = {(row["sidepath_only"], row["roadway_bicycle_legal"]) for row in rows}
    assert len(pairs) > 2, "the two legality columns must not move in lockstep"


def test_every_sidepath_only_crossing_is_trail_class_on_the_no_trail_variant() -> None:
    """The failure this exists to prevent: the router handing a mass ride the Key
    Bridge sidewalk - an eight-foot path with no way off it mid-span, for a field
    of hundreds.

    The expectation is read straight off the fixture's own `sidepath_only`
    field, not recomputed from a disjunct of two columns - that recomputation
    was test-quality finding F8: it could not fail regardless of which rule
    the pipeline actually implemented, because every row in the old fixture
    made the two columns agree. `roadway_bicycle_legal` is deliberately not
    consulted here: it is checked separately, against
    `resolve_bridge_bicycle_legality`, below.
    """
    rows = crossing_rows()
    ways = extract_from_fixture()
    bridge_ids, unmatched = resolve_sidepath_bridge_ids(rows, ways)
    assert not unmatched, "every row in the fixture must resolve against its own names"

    for row, way in zip(rows, ways, strict=True):
        expected_drop = row["sidepath_only"]
        # is_trail_class alone must never answer for the sidepath rule - only
        # a way's own highway tag does, which none of these bridges carry.
        assert not is_trail_class(way.tags), row["name"]
        dropped = inject(Variant.NO_TRAIL, way.tags, way.osm_id, bridge_ids) is None
        assert dropped is expected_drop, f"{row['name']} on the no-trail variant"
        # And never on the other two variants, regardless of sidepath_only -
        # the roadway is not gone, it is just refused to a mass ride.
        assert inject(Variant.STANDARD, way.tags, way.osm_id, bridge_ids) is not None, row["name"]
        assert inject(Variant.EBIKE, way.tags, way.osm_id, bridge_ids) is not None, row["name"]


def test_a_crossing_the_extract_does_not_carry_is_reported_rather_than_ignored() -> None:
    """A way id is the wrong thing to check in - OSM ids change whenever a mapper
    splits a bridge - so these resolve by name, and a name that finds nothing
    means either the clip moved or the name changed. Either way the sidepath rule
    is not biting on that bridge, and an operator needs told which."""
    ids, unmatched = resolve_sidepath_bridge_ids(crossing_rows(), [])
    assert ids == frozenset()
    assert "Key Bridge" in unmatched
    assert "Arlington Memorial Bridge" not in unmatched, "it is not a sidepath-only crossing"


def test_a_street_named_after_a_crossing_does_not_inherit_its_legality() -> None:
    """The approach to Key Bridge is not Key Bridge."""
    approach = FakeWay(2000, {"highway": "secondary", "name": "Key Bridge"})
    ids, _unmatched = resolve_sidepath_bridge_ids(crossing_rows(), [approach])
    assert 2000 not in ids


def test_an_explicitly_recorded_way_id_is_still_honoured() -> None:
    """Name matching is the default, not the only path: where someone has pinned
    an id against the clipped extract, that id is used."""
    row = {"name": "Some Bridge", "osm_way_id": 4242, "sidepath_only": True}
    ids, unmatched = resolve_sidepath_bridge_ids([row], [])
    assert ids == frozenset({4242})
    assert unmatched == []


class TestBridgeBicycleLegality:
    """`resolve_bridge_bicycle_legality`: the legality half of the fixture, a
    different question from the sidepath half above and matched the same way.
    This is the function `run.py`'s `inject_tags` needs to call, on every
    variant, and emit as `rm:bridge_bicycle` - `graph.lua` already reads that
    tag (`derived.bridge_bicycle_legal`), but until this existed nothing in
    the pipeline ever emitted it, so the Lua remap's legality tagger had no
    tagger."""

    def test_a_barred_roadway_resolves_to_false(self) -> None:
        row = {
            "name": "Theodore Roosevelt Bridge",
            "osm_way_id": 0,
            "roadway_bicycle_legal": False,
        }
        way = FakeWay(500, {"highway": "trunk", "bridge": "yes", "name": "Theodore Roosevelt Bridge"})
        legality = resolve_bridge_bicycle_legality([row], [way])
        assert legality == {500: False}

    def test_a_legal_roadway_resolves_to_true_even_when_sidepath_only(self) -> None:
        """Key Bridge: legal roadway, sidepath-only for mass rides. The two
        functions must not agree with each other by accident - they read
        different fixture columns and answer different questions."""
        row = {
            "name": "Key Bridge",
            "osm_way_id": 0,
            "roadway_bicycle_legal": True,
            "sidepath_only": True,
        }
        way = FakeWay(501, {"highway": "primary", "bridge": "yes", "name": "Key Bridge"})
        assert resolve_bridge_bicycle_legality([row], [way]) == {501: True}

    def test_a_row_with_no_opinion_is_left_out_entirely(self) -> None:
        """A row that never mentions `roadway_bicycle_legal` must not inject a
        tag the fixture has no backing for - OSM's own tagging stands."""
        row = {"name": "Untracked Bridge", "osm_way_id": 0}
        way = FakeWay(502, {"highway": "secondary", "bridge": "yes", "name": "Untracked Bridge"})
        assert resolve_bridge_bicycle_legality([row], [way]) == {}

    def test_a_street_named_after_a_bridge_is_not_matched(self) -> None:
        row = {"name": "Key Bridge", "osm_way_id": 0, "roadway_bicycle_legal": True}
        approach = FakeWay(503, {"highway": "secondary", "name": "Key Bridge"})
        assert resolve_bridge_bicycle_legality([row], [approach]) == {}

    def test_the_fixture_resolves_cleanly_against_its_own_names(self) -> None:
        """Every row that states an opinion resolves against a same-named
        bridge way, the same as the sidepath set does."""
        rows = crossing_rows()
        ways = extract_from_fixture()
        legality = resolve_bridge_bicycle_legality(rows, ways)
        opinionated = [row for row in rows if row.get("roadway_bicycle_legal") is not None]
        assert len(legality) == len(opinionated)
        assert set(legality.values()) == {True, False}, "the fixture must exercise both values"


class TestUnverifiedCrossingNames:
    def test_every_row_in_the_shipped_fixture_is_unverified(self) -> None:
        """Overpass is blocked in this environment, so every row - including
        the ones a round-3 reviewer supplied by name - is unverified today."""
        rows = crossing_rows()
        assert unverified_crossing_names(rows) == sorted(row["name"] for row in rows)

    def test_a_row_marked_verified_is_not_reported(self) -> None:
        rows = [
            {"name": "Verified Bridge", "osm_names_verified": True},
            {"name": "Unverified Bridge", "osm_names_verified": False},
        ]
        assert unverified_crossing_names(rows) == ["Unverified Bridge"]
