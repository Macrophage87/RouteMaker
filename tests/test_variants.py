from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import pytest

from pipeline.variants import (
    DuplicateCrossingName,
    Variant,
    bars_electric_bicycle,
    check_crossing_names_unique,
    crossing_names,
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


def test_sidepath_bridges_are_dropped_only_by_the_no_trail_variant():  # noqa: D103
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


def test_the_ebike_bar_is_the_no_value_and_not_every_restriction() -> None:
    """`private`, `destination` and `customers` restrict who may ride a way, not
    whether an e-bike is a vehicle it admits, and the variant does not bar them.

    Pinned because a second reader of this rule now has to agree with it
    exactly: `run.inject_tags` withholds the crossings fixture's roadway
    legality from the e-bike variant on the ways this bar covers, so that the
    transform cannot grant the access back. A rule spelled `!= "yes"` in either
    place would take a checked-in legality row off a bridge nothing barred.
    """
    for value in ("private", "destination", "customers", "yes", "designated"):
        tags = {"highway": "trunk", "electric_bicycle": value}
        assert not bars_electric_bicycle(tags), value
        assert "bicycle" not in inject(Variant.EBIKE, tags), value
    assert bars_electric_bicycle({"highway": "trunk", "electric_bicycle": "no"})
    assert not bars_electric_bicycle({"highway": "trunk"})


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


# --- What the fixture is expected to say ------------------------------------
#
# Every value below is typed in here, by hand, and read from nothing. That is
# the whole point of the table: three rounds of review have now found errors in
# this file's *content*, and each time the tests moved with it, because every
# test derived its expectation from the row it was checking. A reviewer
# measured the gap exactly - setting Key Bridge's `osm_names` to
# ["Ponte Vecchio"] left the suite green, flipping Key and Chain back to
# `roadway_bicycle_legal: false` (the round-3 error, verbatim) left the suite
# green, and deleting every `osm_names` array in the file left the suite green.
#
# So the fixture and the expectation cannot move together any more. The names
# here are the OSM spellings a way is expected to carry; the two flags are the
# two columns the pipeline reads, which say different things and are checked
# separately (see `TestIsSidepathOnly`). Changing this table is a deliberate act
# with a reviewer behind it, which is what changing the fixture should be too.
#
class ExpectedCrossing(NamedTuple):
    """One row of the fixture, as this file expects it to read.

    Five columns, not two. `police` and `row_owner` joined the table in round 5
    because round 4's authority corrections - the Potomac shoreline putting Key
    and Chain Bridge wholly under MPD, Chain Bridge's Virginia end being
    Arlington rather than Fairfax, the Wilson Bridge naming all three
    jurisdictions, Wilson's owner moving from MDTA to MDOT SHA - lived only in
    the fixture and in prose. A reviewer reverted every one of them and the
    suite reported 1590 passed.
    """

    names: tuple[str, ...]
    sidepath: bool
    legal: bool
    police: str
    row_owner: str


EXPECTED_CROSSINGS: dict[str, ExpectedCrossing] = {
    "Arlington Memorial Bridge": ExpectedCrossing(
        ("Arlington Memorial Bridge",), False, True, "US Park Police", "National Park Service"
    ),
    # The label in the file is "Key Bridge"; OSM's name is the full one, and
    # this row is the reason `osm_names` exists at all. One authority end to
    # end, because the DC-Virginia boundary on the Potomac is the 1791 Virginia
    # shoreline and not the channel - the police split down the middle was the
    # midpoint heuristic written into the data.
    "Key Bridge": ExpectedCrossing(("Francis Scott Key Bridge",), True, True, "MPD", "DDOT"),
    # Legal roadways, both. Recording either as roadway-illegal is the round-3
    # error: a narrow bridge a mass ride cannot share is not a bridge bicycles
    # are barred from, and Chain Bridge is a standard climb out of Georgetown.
    # Chain Bridge's Virginia end was also recorded as Fairfax County, which was
    # wrong twice over - the abutment is in Arlington, and above the shoreline
    # it is not a Virginia authority's to police at all.
    "Chain Bridge": ExpectedCrossing(("Chain Bridge",), True, True, "MPD", "DDOT"),
    # The 14th Street complex: three highway spans, the Long Bridge (rail) and
    # the Fenwick Bridge (Metro). The shared-use path is a sidewalk on the
    # George Mason span, so that is the row that is sidepath-only; the other two
    # highway spans are barred outright with nothing standing in.
    "George Mason Memorial Bridge": ExpectedCrossing(
        ("George Mason Memorial Bridge",),
        True,
        False,
        "US Park Police / MPD",
        "National Park Service / VDOT",
    ),
    "Rochambeau Bridge": ExpectedCrossing(
        ("Rochambeau Bridge",), False, False, "US Park Police", "National Park Service / VDOT"
    ),
    "Arland D. Williams Jr. Memorial Bridge": ExpectedCrossing(
        ("Arland D. Williams Jr. Memorial Bridge",),
        False,
        False,
        "US Park Police",
        "National Park Service / VDOT",
    ),
    # The Metro crossing, which this file used to describe on the Williams row.
    "Charles R. Fenwick Bridge": ExpectedCrossing(
        ("Charles R. Fenwick Bridge",), False, False, "Metro Transit Police", "WMATA"
    ),
    # And the rail crossing, which had no row at all while Fenwick - rail-only
    # in exactly the same sense - had one. One rule for both.
    "Long Bridge": ExpectedCrossing(
        ("Long Bridge",), False, False, "CSX Police / MPD", "CSX Transportation"
    ),
    # Three authorities, not two: the one Potomac crossing that touches all
    # three jurisdictions. And MDOT SHA, not MDTA - MDTA is Maryland's toll
    # authority and this bridge is toll-free.
    "Woodrow Wilson Bridge path": ExpectedCrossing(
        ("Woodrow Wilson Memorial Bridge",),
        True,
        False,
        "Alexandria PD / Prince George's County Police / MPD",
        "MDOT SHA",
    ),
    # The row's `name` is this file's label; OSM's is the full one. It carried
    # no `osm_names` at all until round 5, so the label - parenthesis and all -
    # was what the resolver matched on.
    "Sousa Bridge (Pennsylvania Avenue SE)": ExpectedCrossing(
        ("John Philip Sousa Bridge",), False, True, "MPD", "DDOT"
    ),
    # The 11th Street crossing, split for the reason the 14th Street one is:
    # the local span carries bikes and the two I-695 freeway spans do not, which
    # is three answers and was one row.
    "11th Street Bridge (local span)": ExpectedCrossing(
        ("11th Street Bridge",), False, True, "MPD", "DDOT"
    ),
    "11th Street Bridge (I-695 inbound)": ExpectedCrossing(
        ("11th Street Bridges (inbound)",), False, False, "MPD", "DDOT"
    ),
    "11th Street Bridge (I-695 outbound)": ExpectedCrossing(
        ("11th Street Bridges (outbound)",), False, False, "MPD", "DDOT"
    ),
    "Frederick Douglass Memorial Bridge": ExpectedCrossing(
        ("Frederick Douglass Memorial Bridge",), False, True, "MPD", "DDOT"
    ),
    "Whitney Young Memorial Bridge": ExpectedCrossing(
        ("Whitney Young Memorial Bridge", "Whitney M. Young Jr. Memorial Bridge"),
        False,
        True,
        "MPD",
        "DDOT",
    ),
    "Benning Road Bridge": ExpectedCrossing(("Benning Road Bridge",), False, True, "MPD", "DDOT"),
    "Theodore Roosevelt Bridge": ExpectedCrossing(
        ("Theodore Roosevelt Bridge",),
        False,
        False,
        "US Park Police",
        "National Park Service / VDOT",
    ),
    # "George Kennan Memorial Bridge" was an alias here and is deliberately not:
    # nothing places that name on this structure, and an unplaceable alias can
    # only ever match the wrong way. The police column was a split down the
    # middle until round 5; the Potomac above Washington is Maryland's to the
    # Virginia bank, so the span is Maryland's along its length and Fairfax is
    # reached only at the approach.
    "American Legion Bridge": ExpectedCrossing(
        ("American Legion Bridge",),
        False,
        False,
        "Montgomery County Police / Maryland State Police",
        "MDOT SHA / VDOT",
    ),
}


def expected_extract() -> list[FakeWay]:
    """One bridge way per expected crossing, named from the table above.

    Built from the *expectation*, never from the fixture. The version this
    replaces took each way's name from the row it was about to check, so the
    extract matched the fixture by construction: every name lookup in the
    pipeline was being tested against a map generated from its own input, and a
    row whose OSM spelling was wrong - or replaced with "Ponte Vecchio" - still
    resolved perfectly.
    """
    return [
        FakeWay(1000 + index, {"highway": "secondary", "bridge": "yes", "name": expected.names[0]})
        for index, expected in enumerate(EXPECTED_CROSSINGS.values())
    ]


class TestTheFixtureSaysWhatItIsExpectedToSay:
    """The fixture's content, against literals rather than against itself."""

    def test_the_rows_are_the_expected_crossings(self) -> None:
        assert [row["name"] for row in crossing_rows()] == list(EXPECTED_CROSSINGS)

    def test_every_row_claims_the_expected_osm_spellings(self) -> None:
        """Including the rows with no `osm_names` array, whose label is the
        spelling - deleting every array in the file has to fail here, and the
        only way it can is if the expectation names the spellings itself."""
        claimed = {row["name"]: tuple(crossing_names(row)) for row in crossing_rows()}
        expected = {name: row.names for name, row in EXPECTED_CROSSINGS.items()}
        assert claimed == expected

    def test_every_row_carries_the_expected_flags(self) -> None:
        """The two columns the pipeline reads, pinned separately because they
        say different things: `sidepath_only` is a routing decision for mass
        rides and `roadway_bicycle_legal` is a legality fact for every variant."""
        actual = {
            row["name"]: (row["sidepath_only"], row["roadway_bicycle_legal"])
            for row in crossing_rows()
        }
        expected = {name: (row.sidepath, row.legal) for name, row in EXPECTED_CROSSINGS.items()}
        assert actual == expected

    def test_every_row_names_the_expected_authorities(self) -> None:
        """SF-6: the authority columns, pinned against literals like the flags.

        Round 4 corrected four of them - the Potomac shoreline putting Key and
        Chain Bridge wholly under MPD rather than split at the midpoint, Chain
        Bridge's Virginia end being Arlington and not Fairfax, the Wilson Bridge
        naming all three jurisdictions, and Wilson's owner moving from MDTA to
        MDOT SHA - and a reviewer then reverted every one of them and watched
        1590 tests pass. Nothing read these columns, so nothing could.

        They are not decoration. `police` and `row_owner` are what the
        jurisdiction report names to an organizer asking whose permit a ride
        needs, and a reverted correction is a wrong agency named with the same
        confidence as a right one. Reverting one now fails here by name.
        """
        actual = {row["name"]: (row["police"], row["row_owner"]) for row in crossing_rows()}
        expected = {name: (row.police, row.row_owner) for name, row in EXPECTED_CROSSINGS.items()}
        assert actual == expected

    def test_no_authority_column_uses_a_spelling_this_file_retired(self) -> None:
        """One agency, one spelling, in the columns a report prints.

        "Maryland SHA" and "MDOT SHA" are the same body, and a file that names
        it both ways reads as though there were two of them. MDTA is a
        different body - Maryland's toll authority - and naming it as the owner
        of a toll-free bridge was round 4's correction. Both are still
        discussed in the notes, which is where the reasoning belongs; neither
        may appear in a value.
        """
        retired = ("Maryland SHA", "MDTA")
        for row in crossing_rows():
            for column in ("police", "row_owner", "manager"):
                value = row.get(column) or ""
                for spelling in retired:
                    assert spelling not in value, f"{row['name']}.{column} says {value!r}"

    def test_the_expected_spellings_resolve_through_the_real_resolvers(self) -> None:
        """And the same table, driven through the production functions against
        an extract built from the expected spellings. A row whose spelling has
        drifted from the one a real OSM way carries stops resolving here, which
        is the failure the fixture's own names could never produce."""
        rows = crossing_rows()
        ways = expected_extract()

        bridge_ids, unmatched = resolve_sidepath_bridge_ids(rows, ways)
        assert not unmatched
        legality, legality_unmatched = resolve_bridge_bicycle_legality(rows, ways)
        assert not legality_unmatched

        for way, (name, expected) in zip(ways, EXPECTED_CROSSINGS.items(), strict=True):
            assert (way.osm_id in bridge_ids) is expected.sidepath, f"{name}: sidepath_only"
            assert legality[way.osm_id] is expected.legal, f"{name}: roadway_bicycle_legal"

    def test_no_two_rows_claim_the_same_osm_name(self) -> None:
        """Names are how this file resolves, and they merge into one flat dict:
        a name claimed twice resolves to whichever row was written last, and the
        two rows disagree about the columns the file exists to record."""
        check_crossing_names_unique(crossing_rows())

        duplicated = [
            {"name": "A", "osm_names": ["Shared Bridge"], "roadway_bicycle_legal": True},
            {"name": "B", "osm_names": ["Shared Bridge"], "roadway_bicycle_legal": False},
        ]
        with pytest.raises(DuplicateCrossingName, match="Shared Bridge"):
            check_crossing_names_unique(duplicated)
        with pytest.raises(DuplicateCrossingName):
            resolve_bridge_bicycle_legality(duplicated, [])


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
    ways = expected_extract()
    bridge_ids, unmatched = resolve_sidepath_bridge_ids(rows, ways)
    assert not unmatched, "every row in the fixture must resolve against the expected names"

    for row, way, expected in zip(rows, ways, EXPECTED_CROSSINGS.values(), strict=True):
        assert way.tags["name"] == expected.names[0]
        # is_trail_class alone must never answer for the sidepath rule - only
        # a way's own highway tag does, which none of these bridges carry.
        assert not is_trail_class(way.tags), row["name"]
        dropped = inject(Variant.NO_TRAIL, way.tags, way.osm_id, bridge_ids) is None
        assert dropped is expected.sidepath, f"{row['name']} on the no-trail variant"
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
        way = FakeWay(
            500, {"highway": "trunk", "bridge": "yes", "name": "Theodore Roosevelt Bridge"}
        )
        legality, unmatched = resolve_bridge_bicycle_legality([row], [way])
        assert legality == {500: False}
        assert unmatched == []

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
        assert resolve_bridge_bicycle_legality([row], [way])[0] == {501: True}

    def test_a_row_with_no_opinion_is_left_out_entirely(self) -> None:
        """A row that never mentions `roadway_bicycle_legal` must not inject a
        tag the fixture has no backing for - OSM's own tagging stands."""
        row = {"name": "Untracked Bridge", "osm_way_id": 0}
        way = FakeWay(502, {"highway": "secondary", "bridge": "yes", "name": "Untracked Bridge"})
        assert resolve_bridge_bicycle_legality([row], [way])[0] == {}

    @pytest.mark.parametrize("highway", ["cycleway", "path", "footway"])
    def test_the_sidepath_on_a_bridge_is_not_the_bridges_roadway(self, highway: str) -> None:
        """The column is about the *roadway*, and a trail-class way carrying the
        bridge's name is the sidepath on it.

        That is the ordinary OSM shape for a shared-use path on a bridge - the
        Woodrow Wilson path, the 14th Street path and the Key Bridge sidewalk are
        all `highway=cycleway` or `footway` ways tagged `bridge=yes` and named
        after the structure. Matching them wrote `rm:bridge_bicycle=no` onto the
        path on every variant, which `routemaker_remap` turns into `bicycle=no`,
        which deletes the only bicycle crossing of the Potomac at those points
        from all three graphs - on the strength of a column that says nothing
        about the path.
        """
        row = {
            "name": "Woodrow Wilson Bridge path",
            "osm_way_id": 0,
            "osm_names": ["Woodrow Wilson Memorial Bridge"],
            "roadway_bicycle_legal": False,
        }
        path = FakeWay(
            600,
            {"highway": highway, "bridge": "yes", "name": "Woodrow Wilson Memorial Bridge"},
        )
        roadway = FakeWay(
            601, {"highway": "motorway", "bridge": "yes", "name": "Woodrow Wilson Memorial Bridge"}
        )
        legality, _unmatched = resolve_bridge_bicycle_legality([row], [path, roadway])
        assert 600 not in legality, "the path is not the roadway this column describes"
        assert legality == {601: False}, "and the roadway still resolves"

    def test_an_explicit_way_id_is_the_operators_own_claim(self) -> None:
        """The trail-class exclusion applies to the *name* lookup, which is a
        guess about which way a name means. An id someone pinned by hand against
        the clipped extract is not a guess, so it is honoured as written."""
        row = {"name": "Pinned Bridge", "osm_way_id": 4242, "roadway_bicycle_legal": False}
        assert resolve_bridge_bicycle_legality([row], []) == ({4242: False}, [])

    def test_a_hand_pinned_way_still_answers_for_the_names_it_carries(self) -> None:
        """A name found in the extract is found, whichever row got to the way
        first.

        `unmatched` answers one question - does the extract carry this crossing
        at all - and the mapping answers another, which row's opinion the way
        ends up with. An operator who pinned a way by id has already answered
        the second for that way, so a later row whose name is on the same way
        writes nothing; the name is still *there*, and recording the match only
        when the write lands reports the crossing as missing from an extract
        that plainly carries it. The operator would then be told the fixture
        cannot find a bridge they pinned by hand, and the rule they pinned it
        for is the thing that is working.

        The shape is ordinary OSM: one bridge way carrying the structure's name
        under `bridge:name` and the roadway's under `name`.
        """
        pinned = {"name": "Pinned Bridge", "osm_way_id": 4242, "roadway_bicycle_legal": False}
        by_name = {"name": "Sousa Bridge", "osm_way_id": 0, "roadway_bicycle_legal": True}
        way = FakeWay(
            4242,
            {
                "highway": "secondary",
                "bridge": "yes",
                "name": "Pinned Bridge",
                "bridge:name": "Sousa Bridge",
            },
        )

        legality, unmatched = resolve_bridge_bicycle_legality([pinned, by_name], [way])

        assert unmatched == [], "the extract carries Sousa Bridge under bridge:name"
        assert legality == {4242: False}, "and the operator's own claim still stands"

    def test_a_street_named_after_a_bridge_is_not_matched(self) -> None:
        row = {"name": "Key Bridge", "osm_way_id": 0, "roadway_bicycle_legal": True}
        approach = FakeWay(503, {"highway": "secondary", "name": "Key Bridge"})
        assert resolve_bridge_bicycle_legality([row], [approach]) == ({}, ["Key Bridge"])

    def test_the_fixture_resolves_cleanly_against_the_expected_names(self) -> None:
        """Every row that states an opinion resolves against a same-named
        bridge way, the same as the sidepath set does. The extract is built from
        the expected spellings, not from the rows, so a row whose spelling has
        drifted stops resolving instead of resolving against itself."""
        rows = crossing_rows()
        ways = expected_extract()
        legality, unmatched = resolve_bridge_bicycle_legality(rows, ways)
        assert not unmatched
        opinionated = [row for row in rows if row.get("roadway_bicycle_legal") is not None]
        assert len(legality) == len(opinionated)
        assert set(legality.values()) == {True, False}, "the fixture must exercise both values"


class TestTheLegalityHalfReportsItsOwnMisses:
    """SF-D1: both resolvers report unmatched names, not just the sidepath one.

    Only `resolve_sidepath_bridge_ids` returned an `unmatched` list, so the only
    crossings a rebuild ever named were the four `sidepath_only` rows. The other
    fourteen - every row whose whole effect on the graph is the
    `roadway_bicycle_legal` column, the Theodore Roosevelt Bridge included -
    could resolve against nothing at all and reach no log anywhere: the mapping
    simply came back short, and nothing counts it.

    A reviewer measured it exactly: with an extract carrying only the four
    sidepath bridges, `unmatched` was empty while fourteen legality rows
    resolved against nothing.
    """

    def sidepath_extract(self) -> list[FakeWay]:
        """Bridge ways for the fixture's `sidepath_only` rows, and nothing else."""
        return [
            FakeWay(
                7000 + index,
                {"highway": "secondary", "bridge": "yes", "name": crossing_names(row)[0]},
            )
            for index, row in enumerate(row for row in crossing_rows() if row["sidepath_only"])
        ]

    def test_the_rows_the_sidepath_half_says_nothing_about_are_reported(self) -> None:
        rows = crossing_rows()
        ways = self.sidepath_extract()

        _ids, sidepath_unmatched = resolve_sidepath_bridge_ids(rows, ways)
        assert sidepath_unmatched == [], "every sidepath row is in this extract"

        _legality, legality_unmatched = resolve_bridge_bicycle_legality(rows, ways)
        expected = [
            row["name"]
            for row in rows
            if not row["sidepath_only"] and row["roadway_bicycle_legal"] is not None
        ]
        assert len(expected) == 14, "the fixture's legality-only rows"
        assert sorted(expected) == legality_unmatched
        # The one the fixture's own note calls out: the no-trail variant's
        # treatment of this bridge rests entirely on `rm:bridge_bicycle`.
        assert "Theodore Roosevelt Bridge" in legality_unmatched

    def test_a_row_that_resolves_is_not_reported(self) -> None:
        row = {"name": "Some Bridge", "roadway_bicycle_legal": False}
        way = FakeWay(7100, {"highway": "trunk", "bridge": "yes", "name": "Some Bridge"})
        assert resolve_bridge_bicycle_legality([row], [way]) == ({7100: False}, [])

    def test_a_row_with_no_opinion_is_neither_resolved_nor_reported(self) -> None:
        """It is not a miss: the fixture never asked. A row with no
        `roadway_bicycle_legal` deliberately leaves OSM's own tagging standing,
        so naming it in a warning would send an operator after a crossing the
        file has nothing to say about."""
        row = {"name": "Untracked Bridge"}
        assert resolve_bridge_bicycle_legality([row], []) == ({}, [])


class TestABridgesNameCanLiveInBridgeName:
    """SF-D2: `bridge:name` is where OSM keeps a *structure's* name on a road way.

    The `name` tag on a road carries the street. The way over the Anacostia at
    Pennsylvania Avenue SE is named "Pennsylvania Avenue Southeast" - that is
    what the road is called - and "John Philip Sousa Bridge" appears on it only
    in `bridge:name`. Both resolvers matched `name` alone, so a row named after
    the structure rather than after the street could never resolve, and the miss
    was silent in the same way a stale way id was: the name reported unmatched
    and the rule was inert.

    Widening which *names* a way answers to is not widening which ways answer:
    the bridge guard and the trail-class guard are unchanged, and are checked
    here on `bridge:name` too.
    """

    SOUSA = {
        "highway": "primary",
        "bridge": "yes",
        "name": "Pennsylvania Avenue Southeast",
        "bridge:name": "John Philip Sousa Bridge",
    }

    def test_the_legality_half_resolves_the_sousa_row(self) -> None:
        """The checked-in row, against the shape the real way carries."""
        way = FakeWay(5001, dict(self.SOUSA))
        legality, unmatched = resolve_bridge_bicycle_legality(crossing_rows(), [way])
        assert legality == {5001: True}
        assert "Sousa Bridge (Pennsylvania Avenue SE)" not in unmatched

    def test_the_sidepath_half_resolves_the_same_way(self) -> None:
        """One definition of "which names does this way carry", shared by both
        resolvers, so the two halves of the fixture can never disagree about
        which OSM way a row reaches."""
        row = {"name": "Sousa Bridge", "osm_names": ["John Philip Sousa Bridge"]}
        row["sidepath_only"] = True
        way = FakeWay(5002, dict(self.SOUSA))
        ids, unmatched = resolve_sidepath_bridge_ids([row], [way])
        assert ids == frozenset({5002})
        assert unmatched == []

    def test_the_street_name_is_still_read(self) -> None:
        """`bridge:name` is read *alongside* `name`, not instead of it: most of
        the fixture's crossings are streets named after the structure and
        resolve on `name` alone."""
        way = FakeWay(5003, {"highway": "trunk", "bridge": "yes", "name": "Some Bridge"})
        row = {"name": "Some Bridge", "roadway_bicycle_legal": False, "sidepath_only": True}
        assert resolve_bridge_bicycle_legality([row], [way]) == ({5003: False}, [])
        assert resolve_sidepath_bridge_ids([row], [way])[0] == frozenset({5003})

    def test_a_bridge_name_on_a_trail_class_way_is_still_the_sidepath(self) -> None:
        """The sidepath on a bridge carries the structure's name in whichever
        tag - the guard is about what the way *is*, not about which tag named
        it."""
        path = FakeWay(
            5004,
            {"highway": "cycleway", "bridge": "yes", "bridge:name": "John Philip Sousa Bridge"},
        )
        row = {
            "name": "Sousa",
            "osm_names": ["John Philip Sousa Bridge"],
            "roadway_bicycle_legal": False,
            "sidepath_only": True,
        }
        assert resolve_bridge_bicycle_legality([row], [path]) == ({}, ["Sousa"])
        assert resolve_sidepath_bridge_ids([row], [path]) == (frozenset(), ["Sousa"])

    def test_a_street_carrying_a_bridge_name_off_the_bridge_is_not_matched(self) -> None:
        """An approach way is not the structure, whichever tag names it."""
        approach = FakeWay(
            5005, {"highway": "secondary", "bridge:name": "John Philip Sousa Bridge"}
        )
        assert resolve_bridge_bicycle_legality(crossing_rows(), [approach])[0] == {}


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


def test_a_footway_carrying_a_bridges_name_is_not_what_the_sidepath_rule_matches() -> None:
    """SF-1: the sidepath rule matches the roadway, never the sidepath.

    A shared-use path on a bridge is its own `highway=footway` or
    `highway=cycleway` way, tagged `bridge=yes` and named after the structure -
    the Key Bridge sidewalk is two such ways, one per side. Without the
    trail-class guard those two satisfied the name match, so "Key Bridge" came
    off the `unmatched` list and nothing warned, while the Key Bridge *roadway*
    - the way this rule exists to keep a field of hundreds off - stayed in the
    no-trail graph. The guard is the one `resolve_bridge_bicycle_legality` has
    had for the same reason on the same OSM shape.
    """
    # Named with the OSM spelling the row's `osm_names` claims, which is what
    # the resolver matches on - the row's own label is the file's, not OSM's.
    roadway = FakeWay(
        3001, {"highway": "secondary", "bridge": "yes", "name": "Francis Scott Key Bridge"}
    )
    north_walk = FakeWay(
        3002, {"highway": "footway", "bridge": "yes", "name": "Francis Scott Key Bridge"}
    )
    south_walk = FakeWay(
        3003, {"highway": "footway", "bridge": "yes", "name": "Francis Scott Key Bridge"}
    )

    ids, unmatched = resolve_sidepath_bridge_ids(crossing_rows(), [north_walk, roadway, south_walk])

    # The roadway is what matched, and it is what the no-trail variant drops.
    assert 3001 in ids, "the Key Bridge roadway is not in the sidepath set"
    assert inject(Variant.NO_TRAIL, roadway.tags, 3001, ids) is None
    # The footways are not what matched. They are dropped from the no-trail
    # variant anyway, by `is_trail_class`, which is a different rule.
    assert 3002 not in ids and 3003 not in ids
    # And nothing was silently satisfied: with only the footways present, the
    # crossing is reported unmatched rather than resolving against them.
    footways_only, unmatched_footways = resolve_sidepath_bridge_ids(
        crossing_rows(), [north_walk, south_walk]
    )
    assert footways_only == frozenset()
    assert "Key Bridge" in unmatched_footways
    assert "Key Bridge" not in unmatched, "the roadway was present and should have matched"


def test_a_street_named_after_a_bridge_is_not_a_bridge() -> None:
    """F_VAR3: the bridge guard, stated on the streets that would resolve without it.

    Key Bridge Road and Chain Bridge Road are ordinary Virginia roads that run
    for miles, and the `name` tag on a way named after a crossing says nothing
    about whether the way is the crossing. Restricting the match to
    `bridge`-tagged ways is what keeps the approach from inheriting the
    crossing's sidepath rule - and the approach is where a mass ride actually
    rides, so treating it as sidepath-only would drop miles of legal roadway
    from the no-trail graph.
    """
    approaches = [
        FakeWay(4001, {"highway": "secondary", "name": "Francis Scott Key Bridge"}),
        FakeWay(4002, {"highway": "secondary", "name": "Chain Bridge"}),
        FakeWay(4003, {"highway": "secondary", "bridge": "no", "name": "Chain Bridge"}),
    ]
    ids, unmatched = resolve_sidepath_bridge_ids(crossing_rows(), approaches)
    assert ids == frozenset()
    assert {"Key Bridge", "Chain Bridge"} <= set(unmatched)
    for way in approaches:
        assert inject(Variant.NO_TRAIL, way.tags, way.osm_id, ids) is not None
