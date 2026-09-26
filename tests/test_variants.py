from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import pytest

from pipeline.variants import (
    ContradictoryCrossingRow,
    DuplicateCrossingName,
    NoTrailIsNotForThisRide,
    Variant,
    bars_electric_bicycle,
    check_crossing_names_unique,
    crossing_names,
    inject,
    is_roadway_mass_ride_only,
    is_sidepath_only,
    is_trail_class,
    resolve_bridge_bicycle_legality,
    resolve_mass_ride_only_bridge_ids,
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
    assert variant_for(allow_trails=False, ebike_rules=False, mass_ride=True) is Variant.NO_TRAIL
    for ebike_rules in (False, True):
        assert variant_for(allow_trails=True, ebike_rules=ebike_rules, mass_ride=True) in (
            Variant.STANDARD,
            Variant.EBIKE,
        ), "a mass ride with trails allowed is not moved to the no-trail variant"


def test_trails_off_is_refused_to_a_ride_that_is_not_a_mass_ride() -> None:
    """Owner, 2026-09-26, of the Key Bridge roadway: "I wouldn't route someone
    onto that outside of a mass ride." The no-trail variant keeps it, and PLAN
    gives that variant to Group Ride's trails-off toggle too, so the toggle is
    refused until Group Ride has a variant without those roadways."""
    with pytest.raises(NoTrailIsNotForThisRide):
        variant_for(allow_trails=False, ebike_rules=False)
    # The property the refusal protects: the variant it would have handed out
    # keeps every mass-ride-only roadway.
    kept = inject(Variant.NO_TRAIL, {"highway": "trunk"}, 7, frozenset(), frozenset({7}))
    assert kept is not None and kept.get("bicycle") != "no"


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
        """A roadway can be legal and still be one a mass ride cannot use - the
        shape Key Bridge and Chain Bridge had until the owner's decision of
        2026-09-26 put a mass ride on both roadways."""
        assert is_sidepath_only({"sidepath_only": True, "roadway_bicycle_legal": True})


# The checked-in crossings fixture, asserted by the legality tagger as the
# quality bar asks. Until now nothing anywhere opened this file: every row
# carried osm_way_id 0, so the sidepath set was empty, so the no-trail variant
# treated the Key Bridge sidewalk as an ordinary roadway - and the pipeline test
# wrote its own synthetic crossings file, so the committed one was never read.

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "crossings" / "potomac-anacostia.json"


def crossing_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text())


# Where a synthetic way sits when a test is not about where it sits: on the Key
# Bridge, inside the region the crossings fixture is about. A way has to be
# somewhere now, because the resolvers match a row only against ways inside that
# region (`variants.CROSSINGS_SCOPE`), and a way with no location is refused.
DC_POTOMAC = ((-77.0707, 38.9006), (-77.0694, 38.9035))


class FakeWay:
    def __init__(
        self,
        osm_id: int,
        tags: dict[str, str],
        coordinates: tuple[tuple[float, float], ...] = DC_POTOMAC,
    ) -> None:
        self.osm_id = osm_id
        self.tags = tags
        self.coordinates = list(coordinates)


def by_name(legality: dict[int, bool]) -> dict[int, bool]:
    """What the name match produced, without the fixture's `osm_way_id` pins.

    A pinned row's way is in every legality result whatever the extract holds,
    because a pin is honoured as written; the tests below that are about the
    name match compare what is left.
    """
    pinned = {int(row.get("osm_way_id") or 0) for row in crossing_rows()} - {0}
    return {osm_id: legal for osm_id, legal in legality.items() if osm_id not in pinned}


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
    # `roadway_mass_ride_only`: the roadway is for mass rides alone, and the
    # standard and e-bike variants bar it. Owner statements of 2026-09-26, for
    # Key Bridge and Arlington Memorial Bridge.
    mass_ride_only: bool = False


EXPECTED_CROSSINGS: dict[str, ExpectedCrossing] = {
    # Owner, 2026-09-26: a mass ride crosses the Potomac on the roadway of Chain,
    # Key and Memorial bridges, and on Key and Memorial the roadway is for mass
    # rides only - an ordinary rider is sent by the sidepath.
    "Arlington Memorial Bridge": ExpectedCrossing(
        ("Arlington Memorial Bridge",),
        False,
        True,
        "US Park Police",
        "National Park Service",
        mass_ride_only=True,
    ),
    # The label in the file is "Key Bridge"; OSM's name is the full one, and
    # this row is the reason `osm_names` exists at all. One authority end to
    # end, because the DC-Virginia boundary on the Potomac is the 1791 Virginia
    # shoreline and not the channel - the police split down the middle was the
    # midpoint heuristic written into the data.
    "Key Bridge": ExpectedCrossing(
        ("Francis Scott Key Bridge",), False, True, "MPD", "DDOT", mass_ride_only=True
    ),
    # A legal roadway, and recording it as roadway-illegal is the round-3 error.
    # Sidepath-only, so the no-trail variant drops it: the owner, 2026-09-26,
    # "Not a mass-ride crossing", its District approach staying barred.
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
    # OSM writes Junior out; the row's label abbreviates it, and the label's
    # spelling matched nothing on the 2026-09-24 extract.
    "Arland D. Williams Jr. Memorial Bridge": ExpectedCrossing(
        ("Arland D. Williams Junior Memorial Bridge",),
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
    # authority and this bridge is toll-free. The names are the roadway's, as
    # the 2026-09-24 extract spells them across its twenty I-95/I-495 ways;
    # "Woodrow Wilson Memorial Bridge" alone is on none of them.
    "Woodrow Wilson Bridge path": ExpectedCrossing(
        (
            "Woodrow Wilson Memorial Bridge (Local)",
            "Woodrow Wilson Memorial Bridge (Thru)",
            "Woodrow Wilson Bridge",
            "Woodrow Wilson Bridge (Thru)",
        ),
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
    # is three answers and was one row. The local span claims no OSM name, so
    # its label is its only spelling: "11th Street Bridge", which it claimed,
    # is the `bridge:name` of an I-695 freeway span on the 2026-09-24 extract,
    # and the row's `true` landed there.
    "11th Street Bridge (local span)": ExpectedCrossing(
        ("11th Street Bridge (local span)",), False, True, "MPD", "DDOT"
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
        ("Whitney Young Memorial Bridge",),
        False,
        True,
        "MPD",
        "DDOT",
    ),
    "Benning Road Bridge": ExpectedCrossing(("Benning Road Bridge",), False, True, "MPD", "DDOT"),
    "Theodore Roosevelt Bridge": ExpectedCrossing(
        ("Theodore Roosevelt Memorial Bridge",),
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
        FakeWay(
            PINNED_WAY_IDS.get(name, 1000 + index),
            {"highway": "secondary", "bridge": "yes", "name": expected.names[0]},
        )
        for index, (name, expected) in enumerate(EXPECTED_CROSSINGS.items())
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
            row["name"]: (
                row["sidepath_only"],
                row["roadway_bicycle_legal"],
                row["roadway_mass_ride_only"],
            )
            for row in crossing_rows()
        }
        expected = {
            name: (row.sidepath, row.legal, row.mass_ride_only)
            for name, row in EXPECTED_CROSSINGS.items()
        }
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
        mass_ride_ids, mass_ride_unmatched = resolve_mass_ride_only_bridge_ids(rows, ways)
        assert not mass_ride_unmatched

        for way, (name, expected) in zip(ways, EXPECTED_CROSSINGS.items(), strict=True):
            assert (way.osm_id in bridge_ids) is expected.sidepath, f"{name}: sidepath_only"
            assert legality[way.osm_id] is expected.legal, f"{name}: roadway_bicycle_legal"
            assert (way.osm_id in mass_ride_ids) is expected.mass_ride_only, (
                f"{name}: roadway_mass_ride_only"
            )

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
        assert isinstance(row["roadway_mass_ride_only"], bool)
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


class TestARoadwayForMassRidesOnly:
    """`roadway_mass_ride_only`, the owner's rule of 2026-09-26 for Key Bridge
    and Arlington Memorial Bridge: the roadway is for a mass ride and for no one
    else. The no-trail variant keeps it; the standard and e-bike variants bar it
    (`bicycle=no`), so an ordinary rider is sent by the sidepath, which is its
    own trail-class way and is never what the rule reaches."""

    def resolved(self):
        rows = crossing_rows()
        ways = expected_extract()
        sidepath_ids, _ = resolve_sidepath_bridge_ids(rows, ways)
        mass_ride_ids, unmatched = resolve_mass_ride_only_bridge_ids(rows, ways)
        assert not unmatched
        return ways, sidepath_ids, mass_ride_ids

    def test_every_crossing_in_every_variant(self) -> None:
        """Over the whole fixture, against the hand-typed expectation: for each
        crossing's roadway, what each of the three variants builds with."""
        ways, sidepath_ids, mass_ride_ids = self.resolved()
        for way, (name, expected) in zip(ways, EXPECTED_CROSSINGS.items(), strict=True):
            no_trail = inject(Variant.NO_TRAIL, way.tags, way.osm_id, sidepath_ids, mass_ride_ids)
            assert (no_trail is None) is expected.sidepath, f"{name}: no-trail drop"
            if no_trail is not None:
                assert no_trail.get("bicycle") != "no", f"{name}: no-trail barred the roadway"
            for variant in (Variant.STANDARD, Variant.EBIKE):
                built = inject(variant, way.tags, way.osm_id, sidepath_ids, mass_ride_ids)
                assert built is not None, f"{name}: {variant.value} dropped the roadway"
                barred = built.get("bicycle") == "no"
                assert barred is expected.mass_ride_only, f"{name}: {variant.value} bar"

    def test_the_owners_potomac_roadways(self) -> None:
        """The owner, 2026-09-26: "Mass ride can cross the Potomac at Chain
        Bridge, Key Bridge, and Memorial bridge without using a trail", and
        then, of Chain Bridge with its District approach barred, "Not a
        mass-ride crossing". So the no-trail variant keeps the Key and Memorial
        roadways and drops Chain's, and none of the three is legally barred -
        the standard and e-bike variants keep Chain's roadway."""
        ways, sidepath_ids, mass_ride_ids = self.resolved()
        by_label = dict(zip(EXPECTED_CROSSINGS, ways, strict=True))
        for label in ("Key Bridge", "Arlington Memorial Bridge"):
            way = by_label[label]
            kept = inject(Variant.NO_TRAIL, way.tags, way.osm_id, sidepath_ids, mass_ride_ids)
            assert kept is not None and kept.get("bicycle") != "no", label
        chain = by_label["Chain Bridge"]
        args = (chain.tags, chain.osm_id, sidepath_ids, mass_ride_ids)
        assert inject(Variant.NO_TRAIL, *args) is None, "Chain Bridge is not a mass-ride crossing"
        for variant in (Variant.STANDARD, Variant.EBIKE):
            assert inject(variant, *args).get("bicycle") != "no", variant.value
        rows = {row["name"]: row for row in crossing_rows()}
        assert all(
            rows[label]["roadway_bicycle_legal"]
            for label in ("Chain Bridge", "Key Bridge", "Arlington Memorial Bridge")
        )

    def test_the_bar_covers_a_directional_grant_too(self) -> None:
        """A `bicycle:forward=yes` left standing would open one direction of a
        roadway the bar closed, since Valhalla lets the directional key win."""
        tags = {"highway": "trunk", "bicycle:forward": "yes", "bicycle:backward": "designated"}
        for variant in (Variant.STANDARD, Variant.EBIKE):
            built = inject(variant, tags, 7, frozenset(), frozenset({7}))
            assert built["bicycle"] == "no", variant.value
            assert built["bicycle:forward"] == "no", variant.value
            assert built["bicycle:backward"] == "no", variant.value
        kept = inject(Variant.NO_TRAIL, tags, 7, frozenset(), frozenset({7}))
        assert kept == tags

    def test_the_bar_covers_a_conditional_grant_too(self) -> None:
        """The remap opens a direction from a conditional's least restrictive
        branch (`remap_conditional_access`), so a weekend `yes` would reopen a
        barred roadway at every hour. Each conditional key present is set to a
        bare `no`, which the remap never reads as a widening."""
        tags = {
            "highway": "trunk",
            "bicycle:conditional": "yes @ (Sa,Su)",
            "bicycle:forward:conditional": "yes @ (Su)",
            "bicycle:backward:conditional": "designated @ (Sa)",
        }
        for variant in (Variant.STANDARD, Variant.EBIKE):
            built = inject(variant, tags, 7, frozenset(), frozenset({7}))
            for key in tags:
                if key.endswith(":conditional"):
                    assert built[key] == "no", (variant.value, key)
        assert inject(Variant.NO_TRAIL, tags, 7, frozenset(), frozenset({7})) == tags

    def test_the_bar_stands_over_an_approved_bicycle_grant(self) -> None:
        """An approved `bicycle=yes` override reaches `inject` in the way's tags.
        It says the roadway is legal, which the fixture already says; it does
        not say ordinary riders are routed there, so the bar stands on the
        standard and e-bike variants and the no-trail variant keeps the grant."""
        tags = {"highway": "trunk", "bicycle": "yes"}
        for variant in (Variant.STANDARD, Variant.EBIKE):
            assert inject(variant, tags, 7, frozenset(), frozenset({7}))["bicycle"] == "no"
        assert inject(Variant.NO_TRAIL, tags, 7, frozenset(), frozenset({7}))["bicycle"] == "yes"

    def test_only_the_listed_ways_are_barred(self) -> None:
        tags = {"highway": "trunk"}
        for variant in (Variant.STANDARD, Variant.EBIKE):
            assert "bicycle" not in inject(variant, tags, 8, frozenset(), frozenset({7}))

    def test_the_rule_reaches_the_roadway_and_never_the_sidepath(self) -> None:
        """The Key Bridge sidewalk and the Memorial Bridge cycleways are how an
        ordinary rider crosses once the roadway is barred. A rule that reached
        them would leave the standard and e-bike variants no crossing at all
        there, so the trail-class guard every resolver shares keeps them out."""
        roadway = FakeWay(
            3101, {"highway": "trunk", "bridge": "yes", "name": "Francis Scott Key Bridge"}
        )
        sidewalk = FakeWay(
            3102, {"highway": "footway", "bridge": "yes", "name": "Francis Scott Key Bridge"}
        )
        cycleway = FakeWay(
            3103, {"highway": "cycleway", "bridge": "yes", "name": "Arlington Memorial Bridge"}
        )
        ids, unmatched = resolve_mass_ride_only_bridge_ids(
            crossing_rows(), [roadway, sidewalk, cycleway]
        )
        assert ids == frozenset({3101})
        assert "Key Bridge" not in unmatched
        # Only the paths present: the rows are reported, not satisfied by them.
        ids, unmatched = resolve_mass_ride_only_bridge_ids(crossing_rows(), [sidewalk, cycleway])
        assert ids == frozenset()
        assert {"Key Bridge", "Arlington Memorial Bridge"} <= set(unmatched)

    def test_a_street_named_after_the_bridge_is_not_barred(self) -> None:
        """Key Bridge's approaches are where every rider rides; the bridge guard
        keeps them off the list."""
        approach = FakeWay(3104, {"highway": "secondary", "name": "Francis Scott Key Bridge"})
        ids, unmatched = resolve_mass_ride_only_bridge_ids(crossing_rows(), [approach])
        assert ids == frozenset()
        assert "Key Bridge" in unmatched

    def test_baltimores_key_bridge_is_not_barred(self) -> None:
        ids, unmatched = resolve_mass_ride_only_bridge_ids(
            crossing_rows(), [DC_KEY_BRIDGE, BALTIMORE_KEY_BRIDGE]
        )
        assert ids == frozenset({DC_KEY_BRIDGE.osm_id})

    def test_a_pinned_row_is_honoured_and_its_absence_reported(self) -> None:
        row = {"name": "Pinned", "osm_way_id": 7401, "roadway_mass_ride_only": True}
        assert resolve_mass_ride_only_bridge_ids([row], []) == (frozenset({7401}), ["Pinned"])
        present = [FakeWay(7401, {"highway": "service"}, ((-76.52, 39.22),))]
        assert resolve_mass_ride_only_bridge_ids([row], present) == (frozenset({7401}), [])

    def test_the_column_is_read_alone(self) -> None:
        assert is_roadway_mass_ride_only({"roadway_mass_ride_only": True})
        assert not is_roadway_mass_ride_only({"roadway_mass_ride_only": False})
        assert not is_roadway_mass_ride_only({"sidepath_only": True, "roadway_bicycle_legal": True})

    @pytest.mark.parametrize(
        "row",
        [
            # No-trail would drop the roadway and the other two would bar it:
            # the roadway would be in no graph, for a row that says a mass ride
            # uses it.
            {"name": "X", "roadway_mass_ride_only": True, "sidepath_only": True},
            # A roadway barred to every bicycle is not a mass ride's either.
            {"name": "X", "roadway_mass_ride_only": True, "roadway_bicycle_legal": False},
        ],
    )
    def test_a_contradictory_row_is_refused(self, row: dict) -> None:
        with pytest.raises(ContradictoryCrossingRow, match="X"):
            resolve_mass_ride_only_bridge_ids([row], [])
        with pytest.raises(ContradictoryCrossingRow, match="X"):
            resolve_sidepath_bridge_ids([row], [])
        with pytest.raises(ContradictoryCrossingRow, match="X"):
            resolve_bridge_bicycle_legality([row], [])


def test_the_mass_ride_only_resolver_refuses_a_duplicated_name() -> None:
    """Each resolver checks the names itself rather than trusting another to
    have done it first: two rows of one name would each resolve, and the one
    whose flags lost would be silent."""
    rows = [
        {"name": "Twice", "roadway_bicycle_legal": True, "roadway_mass_ride_only": True},
        {"name": "Twice", "roadway_bicycle_legal": True, "roadway_mass_ride_only": False},
    ]
    with pytest.raises(DuplicateCrossingName):
        resolve_mass_ride_only_bridge_ids(rows, [])
    with pytest.raises(DuplicateCrossingName):
        resolve_sidepath_bridge_ids(rows, [])


def test_a_crossing_the_extract_does_not_carry_is_reported_rather_than_ignored() -> None:
    """A way id is the wrong thing to check in - OSM ids change whenever a mapper
    splits a bridge - so these resolve by name, and a name that finds nothing
    means either the clip moved or the name changed. Either way the sidepath rule
    is not biting on that bridge, and an operator needs told which."""
    ids, unmatched = resolve_sidepath_bridge_ids(crossing_rows(), [])
    assert ids == frozenset()
    assert "George Mason Memorial Bridge" in unmatched
    assert "Key Bridge" not in unmatched, "it is not a sidepath-only crossing since 2026-09-26"
    ids, unmatched = resolve_mass_ride_only_bridge_ids(crossing_rows(), [])
    assert ids == frozenset()
    assert {"Key Bridge", "Arlington Memorial Bridge"} <= set(unmatched)
    assert "Chain Bridge" not in unmatched, "its roadway is for every rider"


def test_a_street_named_after_a_crossing_does_not_inherit_its_legality() -> None:
    """The approach to Key Bridge is not Key Bridge."""
    approach = FakeWay(2000, {"highway": "secondary", "name": "Key Bridge"})
    ids, _unmatched = resolve_sidepath_bridge_ids(crossing_rows(), [approach])
    assert 2000 not in ids


def test_an_explicitly_recorded_way_id_is_still_honoured() -> None:
    """Name matching is the default, not the only path: where someone has pinned
    an id against the clipped extract, that id is used."""
    row = {"name": "Some Bridge", "osm_way_id": 4242, "sidepath_only": True}
    # Not a bridge and nowhere near the region: a pin bypasses both guards.
    pinned = FakeWay(4242, {"highway": "secondary"}, ((-76.52, 39.22),))
    ids, unmatched = resolve_sidepath_bridge_ids([row], [pinned])
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
        pinned = FakeWay(4242, {"highway": "cycleway", "bridge": "yes"}, ((-76.52, 39.22),))
        assert resolve_bridge_bicycle_legality([row], [pinned]) == ({4242: False}, [])

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
        # Two of the fifteen are pinned by way id, and are named here because
        # this extract does not carry the ways they are pinned to. Fifteen since
        # 2026-09-26, when Key Bridge stopped being sidepath-only.
        assert len(expected) == 15, "the fixture's legality-only rows"
        assert sorted(expected) == legality_unmatched
        # The row whose miss was the one first noticed, when its note still
        # said (wrongly - the 2026-09-24 extract has it motorway class) that
        # nothing but `rm:bridge_bicycle` kept a ride off it.
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
        assert by_name(legality) == {5001: True}
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
        assert by_name(resolve_bridge_bicycle_legality(crossing_rows(), [approach])[0]) == {}


# The rows checked against the Geofabrik DC+MD+VA extract of 2026-09-24 and
# found to land, every name of them, on the structure the row describes. Typed
# in by hand like the table above, because clearing `osm_names_verified` is a
# claim about the map and should take a deliberate edit here as well as there.
# The five left out are the three 11th Street spans, whose names reach no way
# or reached the wrong one, and the two rail structures, which the pipeline
# never reads.
VERIFIED_ON_2026_09_24 = {
    "Arlington Memorial Bridge",
    "Key Bridge",
    "Chain Bridge",
    "George Mason Memorial Bridge",
    "Rochambeau Bridge",
    "Arland D. Williams Jr. Memorial Bridge",
    "Woodrow Wilson Bridge path",
    "Sousa Bridge (Pennsylvania Avenue SE)",
    "Frederick Douglass Memorial Bridge",
    "Whitney Young Memorial Bridge",
    "Benning Road Bridge",
    "Theodore Roosevelt Bridge",
    "American Legion Bridge",
}


class TestUnverifiedCrossingNames:
    def test_the_shipped_fixture_is_verified_exactly_where_it_was_checked(self) -> None:
        """Every row outside the checked set is reported unverified, and every
        row in it is not."""
        rows = crossing_rows()
        assert set(EXPECTED_CROSSINGS) >= VERIFIED_ON_2026_09_24
        assert unverified_crossing_names(rows) == sorted(
            row["name"] for row in rows if row["name"] not in VERIFIED_ON_2026_09_24
        )
        for row in rows:
            assert isinstance(row["osm_names_verified"], bool), row["name"]

    def test_a_row_marked_verified_is_not_reported(self) -> None:
        rows = [
            {"name": "Verified Bridge", "osm_names_verified": True},
            {"name": "Unverified Bridge", "osm_names_verified": False},
        ]
        assert unverified_crossing_names(rows) == ["Unverified Bridge"]


# Key Bridge and Chain Bridge as the fixture had them until the owner's decision
# of 2026-09-26 - both sidepath-only; Chain Bridge still is - kept as synthetic
# rows because the two tests
# below are about the sidepath rule's guards, which the rows that remain
# sidepath-only (motorway spans) do not exercise on a roadway name.
SIDEPATH_ROWS_BEFORE_2026_09_26 = [
    {
        "name": "Key Bridge",
        "osm_names": ["Francis Scott Key Bridge"],
        "roadway_bicycle_legal": True,
        "sidepath_only": True,
    },
    {"name": "Chain Bridge", "roadway_bicycle_legal": True, "sidepath_only": True},
]


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

    ids, unmatched = resolve_sidepath_bridge_ids(
        SIDEPATH_ROWS_BEFORE_2026_09_26, [north_walk, roadway, south_walk]
    )

    # The roadway is what matched, and it is what the no-trail variant drops.
    assert 3001 in ids, "the Key Bridge roadway is not in the sidepath set"
    assert inject(Variant.NO_TRAIL, roadway.tags, 3001, ids) is None
    # The footways are not what matched. They are dropped from the no-trail
    # variant anyway, by `is_trail_class`, which is a different rule.
    assert 3002 not in ids and 3003 not in ids
    # And nothing was silently satisfied: with only the footways present, the
    # crossing is reported unmatched rather than resolving against them.
    footways_only, unmatched_footways = resolve_sidepath_bridge_ids(
        SIDEPATH_ROWS_BEFORE_2026_09_26, [north_walk, south_walk]
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
    ids, unmatched = resolve_sidepath_bridge_ids(SIDEPATH_ROWS_BEFORE_2026_09_26, approaches)
    assert ids == frozenset()
    assert {"Key Bridge", "Chain Bridge"} <= set(unmatched)
    for way in approaches:
        assert inject(Variant.NO_TRAIL, way.tags, way.osm_id, ids) is not None


# --- The match is scoped to the region the fixture is about -----------------
#
# Real ways, typed in by hand from the Geofabrik DC+MD+VA extract of 2026-09-24
# clipped to COVERAGE_BBOX: ids, tags and end points as that extract carries
# them. Two structures in it are called the Francis Scott Key Bridge. One is the
# Potomac crossing this fixture's "Key Bridge" row is about; the other is
# Baltimore's, sixty kilometres away, which came into the extract when the owner
# extended the coverage region to Baltimore and the Mason-Dixon line on
# 2026-09-24 (PLAN.md, Region and data).

DC_KEY_BRIDGE = FakeWay(
    6059971,
    {
        "highway": "trunk",
        "bridge": "yes",
        "name": "Francis Scott Key Bridge",
        "ref": "US 29",
        "bicycle": "no",
    },
    ((-77.0707, 38.9006), (-77.0694, 38.9035)),
)
BALTIMORE_KEY_BRIDGE = FakeWay(
    1266435590,
    {
        "highway": "motorway",
        "bridge": "viaduct",
        "name": "Baltimore Beltway",
        "bridge:name": "Francis Scott Key Bridge",
        "ref": "I 695",
    },
    ((-76.5205, 39.2231), (-76.5227, 39.2213)),
)
# The one way in that extract carrying the name the "11th Street Bridge (local
# span)" row used to claim: an I-695 freeway span, inside the region, so no
# geographic scope can keep a row off it.
SOUTHEAST_FREEWAY_SPAN = FakeWay(
    546095934,
    {
        "highway": "motorway",
        "bridge": "yes",
        "name": "Southeast Freeway",
        "bridge:name": "11th Street Bridge",
        "ref": "I 695",
    },
    ((-76.9889, 38.8711), (-76.9903, 38.8728)),
)

# The ends of the region, from the same extract: the American Legion Bridge's
# upstream end, the Woodrow Wilson Bridge's downstream path, and the Benning
# Road Bridge's eastern abutment.
AMERICAN_LEGION_NORTH_END = (-77.1793, 38.9711)
WILSON_BRIDGE_SOUTH_EDGE = (-77.0216, 38.7922)
BENNING_ROAD_EAST_END = (-76.9607, 38.8969)
COVERAGE_BBOX = (-78.0, 38.2, -76.02, 39.72)  # settings.COVERAGE_BBOX, 2026-09-24


def inside_scope(point: tuple[float, float]) -> bool:
    from pipeline import variants

    west, south, east, north = variants.CROSSINGS_SCOPE
    lon, lat = point
    return west <= lon <= east and south <= lat <= north


class TestTheMatchIsScopedToTheFixturesRegion:
    """A crossing row matches only ways inside the region the fixture is about.

    Rows are matched by name, and a name is not a place. The fixture is about
    the Potomac from the American Legion Bridge to the Woodrow Wilson Bridge and
    the Anacostia below the Benning Road Bridge; the extract it is matched
    against is the whole coverage region, which since 2026-09-24 runs to
    Baltimore. On that extract the "Key Bridge" row matched four trunk ways of
    US 29 across the Potomac and four motorway ways of I-695 across the Patapsco.
    """

    def test_baltimores_key_bridge_matches_nothing(self) -> None:
        rows = crossing_rows()
        ids, unmatched = resolve_mass_ride_only_bridge_ids(rows, [BALTIMORE_KEY_BRIDGE])
        assert ids == frozenset()
        assert "Key Bridge" in unmatched
        legality, legality_unmatched = resolve_bridge_bicycle_legality(rows, [BALTIMORE_KEY_BRIDGE])
        assert by_name(legality) == {}
        assert "Key Bridge" in legality_unmatched

    def test_the_district_key_bridge_still_matches_beside_it(self) -> None:
        rows = crossing_rows()
        both = [DC_KEY_BRIDGE, BALTIMORE_KEY_BRIDGE]
        ids, unmatched = resolve_mass_ride_only_bridge_ids(rows, both)
        assert ids == frozenset({DC_KEY_BRIDGE.osm_id})
        assert "Key Bridge" not in unmatched
        legality, _unmatched = resolve_bridge_bicycle_legality(rows, both)
        assert by_name(legality) == {DC_KEY_BRIDGE.osm_id: True}

    def test_a_way_with_no_location_cannot_be_placed_and_matches_nothing(self) -> None:
        """A way the extract gives no coordinate for cannot be shown to be
        inside the region, so it is refused rather than assumed to be."""
        nowhere = FakeWay(9100, dict(DC_KEY_BRIDGE.tags), ())
        rows = crossing_rows()
        assert resolve_mass_ride_only_bridge_ids(rows, [nowhere])[0] == frozenset()
        assert by_name(resolve_bridge_bicycle_legality(rows, [nowhere])[0]) == {}

    def test_a_way_leaving_the_region_is_not_inside_it(self) -> None:
        """Every located point, not any: a way with one end in the region and
        the other outside it is not a crossing of these two rivers."""
        from pipeline import variants

        west, south, _east, _north = variants.CROSSINGS_SCOPE
        straddling = FakeWay(
            9101, dict(DC_KEY_BRIDGE.tags), ((west + 0.001, south + 0.001), (west - 0.001, south))
        )
        assert by_name(resolve_bridge_bicycle_legality(crossing_rows(), [straddling])[0]) == {}

    def test_the_region_holds_the_fixtures_ends_and_not_baltimore(self) -> None:
        for point in (
            AMERICAN_LEGION_NORTH_END,
            WILSON_BRIDGE_SOUTH_EDGE,
            BENNING_ROAD_EAST_END,
            *DC_KEY_BRIDGE.coordinates,
            *SOUTHEAST_FREEWAY_SPAN.coordinates,
        ):
            assert inside_scope(point), point
        for point in BALTIMORE_KEY_BRIDGE.coordinates:
            assert not inside_scope(point), point

    def test_every_way_either_resolver_matches_lies_inside_the_region(self) -> None:
        """The property, over every name the fixture claims, placed across the
        whole coverage region: whatever either resolver matches is inside the
        region, and it is not vacuous - ways inside it do match, and ways
        outside it carrying the same names do not."""
        west, south, east, north = COVERAGE_BBOX
        rows = crossing_rows()
        names = sorted({name for row in rows for name in crossing_names(row)})
        steps = 24
        ways: list[FakeWay] = []
        for i in range(steps + 1):
            for j in range(steps + 1):
                lon = west + (east - west) * i / steps
                lat = south + (north - south) * j / steps
                name = names[(i * (steps + 1) + j) % len(names)]
                tags = {"highway": "primary", "bridge": "yes", "bridge:name": name}
                ways.append(FakeWay(len(ways) + 1, tags, ((lon, lat), (lon + 0.004, lat + 0.003))))
        # And every name at each end of the region, so every name is tried
        # inside it as well as across the whole coverage area.
        for point in (AMERICAN_LEGION_NORTH_END, WILSON_BRIDGE_SOUTH_EDGE, BENNING_ROAD_EAST_END):
            for name in names:
                tags = {"highway": "primary", "bridge": "yes", "name": name}
                ways.append(FakeWay(len(ways) + 1, tags, (point,)))
        by_id = {way.osm_id: way for way in ways}

        sidepath_ids, _ = resolve_sidepath_bridge_ids(rows, ways)
        legality, _ = resolve_bridge_bicycle_legality(rows, ways)
        mass_ride_ids, _ = resolve_mass_ride_only_bridge_ids(rows, ways)
        assert mass_ride_ids, "the mass-ride-only rows matched nothing, so say nothing"
        # Pins bypass the region by design - an id pinned by hand is honoured
        # as written - so the property is about what the name match reached.
        matched = set(sidepath_ids) | set(by_name(legality)) | set(mass_ride_ids)

        assert matched, "nothing matched, so the property says nothing"
        for osm_id in matched:
            assert all(inside_scope(p) for p in by_id[osm_id].coordinates), osm_id
        outside = {w.osm_id for w in ways if not all(inside_scope(p) for p in w.coordinates)}
        assert outside, "nothing was outside the region, so the property says nothing"
        assert not outside & matched

    def test_the_local_span_row_does_not_land_on_the_freeway_span(self) -> None:
        """Inside the region, so the scope cannot help: the row claiming a
        bike-legal roadway had claimed the name an I-695 span carries in
        `bridge:name`, and its `true` landed on an interstate."""
        legality, _unmatched = resolve_bridge_bicycle_legality(
            crossing_rows(), [SOUTHEAST_FREEWAY_SPAN]
        )
        assert legality.get(SOUTHEAST_FREEWAY_SPAN.osm_id) is not True

    def test_the_wilson_path_is_not_barred_by_the_alias_it_shares(self) -> None:
        """`Woodrow Wilson Bridge` is the `bridge:name` of the Beltway's local
        lanes and the `name` of the shared-use path beside them in the same
        extract. The row claims it for the roadway; the path must still neither
        inherit the roadway's bar nor be taken for the sidepath-only roadway."""
        roadway = FakeWay(
            93187657,
            {
                "highway": "motorway",
                "bridge": "yes",
                "name": "Capital Beltway (Local)",
                "bridge:name": "Woodrow Wilson Bridge",
                "ref": "I 95;I 495",
                "bicycle": "no",
            },
            ((-77.0464, 38.7924), (-77.039, 38.7929)),
        )
        path = FakeWay(
            50601887,
            {"highway": "cycleway", "bridge": "yes", "name": "Woodrow Wilson Bridge"},
            ((-77.0463, 38.793), (-77.0386, 38.7936)),
        )
        rows = crossing_rows()
        ids, unmatched = resolve_sidepath_bridge_ids(rows, [roadway, path])
        assert ids == frozenset({roadway.osm_id})
        assert "Woodrow Wilson Bridge path" not in unmatched
        legality, _ = resolve_bridge_bicycle_legality(rows, [roadway, path])
        assert by_name(legality) == {roadway.osm_id: False}


# --- The 11th Street crossing, pinned by geometry ----------------------------
#
# Every bridge way at the crossing, and the Anacostia's centreline where it
# passes under them, typed in by hand from the real extract
# (/home/steph/routemaker-data/extracts/source.osm.pbf, the Geofabrik DC+MD+VA
# extract of 2026-09-24): ids, the tags that decide the question, and node
# coordinates to 1e-6 degrees. The river line is waterway=river "Anacostia
# River", ways 1211474183 and 1211474184, which meet at (-76.990043, 38.871519).

ANACOSTIA_CENTRELINE = (
    (-76.987055, 38.873045),
    (-76.989763, 38.871679),
    (-76.990043, 38.871519),
    (-76.991807, 38.870508),
)

ELEVENTH_STREET_SE = {"highway": "secondary", "bridge": "yes", "name": "11th Street Southeast"}
ELEVENTH_STREET_WAYS = [
    # The four ways the name "11th Street Southeast" reaches on a bridge.
    FakeWay(
        546096009,
        {**ELEVENTH_STREET_SE, "bicycle": "no", "foot": "no", "sidewalk:right": "separate"},
        (
            (-76.990992, 38.872628),
            (-76.990954, 38.872562),
            (-76.990914, 38.872499),
            (-76.990872, 38.872433),
            (-76.990827, 38.872365),
            (-76.990768, 38.872279),
            (-76.990691, 38.872176),
            (-76.990617, 38.872077),
            (-76.990545, 38.871981),
            (-76.990473, 38.871887),
            (-76.989337, 38.870457),
        ),
    ),
    FakeWay(
        546095991,
        {**ELEVENTH_STREET_SE, "bicycle": "no", "foot": "no"},
        ((-76.988417, 38.869171), (-76.988285, 38.868977)),
    ),
    FakeWay(
        546095992,
        {**ELEVENTH_STREET_SE, "bicycle": "no", "foot": "no"},
        ((-76.988568, 38.869396), (-76.988417, 38.869171)),
    ),
    FakeWay(
        546095994,
        {**ELEVENTH_STREET_SE, "bicycle": "no", "foot": "no"},
        ((-76.988718, 38.869617), (-76.988568, 38.869396)),
    ),
]
I695 = {"highway": "motorway", "bridge": "yes", "oneway": "yes", "ref": "I 695"}
FREEWAY_WAYS = [
    # Drawn south-east to north-west: toward the Southeast Freeway, inbound.
    FakeWay(
        546095934,
        {**I695, "name": "Southeast Freeway", "bridge:name": "11th Street Bridge", "lanes": "4"},
        ((-76.988912, 38.871114), (-76.990327, 38.87282)),
    ),
    # Drawn north-west to south-east: outbound. One four-lane way that splits
    # at node 5277494650, north of the centreline, into the I-295 mainline and
    # the DC-295 ramp - so two ways cross the river on this side, not one.
    FakeWay(
        546095944,
        {**I695, "name": "Southeast Freeway", "lanes": "4"},
        ((-76.990486, 38.872737), (-76.990045, 38.87221)),
    ),
    FakeWay(
        546095942,
        {**I695, "name": "Southeast Freeway", "lanes": "2"},
        (
            (-76.990045, 38.87221),
            (-76.989268, 38.871298),
            (-76.989193, 38.871206),
            (-76.98912, 38.871114),
            (-76.989047, 38.87102),
            (-76.988975, 38.870926),
            (-76.988921, 38.870856),
            (-76.98887, 38.870785),
        ),
    ),
    FakeWay(
        546095943,
        {"highway": "motorway_link", "bridge": "yes", "oneway": "yes", "lanes": "2"},
        ((-76.990045, 38.87221), (-76.989276, 38.870982), (-76.987494, 38.87016)),
    ),
]
# The shared-use path: its own way, trail class, with no access restriction.
RIVERWALK_ON_THE_LOCAL_SPAN = FakeWay(
    546096004,
    {
        "highway": "cycleway",
        "bridge": "yes",
        "name": "Anacostia Riverwalk Trail",
        "bicycle": "designated",
        "foot": "designated",
        "oneway": "no",
    },
    (
        (-76.991106, 38.872588),
        (-76.990952, 38.872351),
        (-76.99066, 38.871979),
        (-76.990358, 38.871584),
        (-76.990065, 38.871214),
        (-76.989818, 38.870906),
        (-76.98944, 38.870405),
    ),
)

# Metres per degree at 38.87 N, near enough for comparing positions tens of
# metres apart.
M_PER_DEG_LON, M_PER_DEG_LAT = 86_700.0, 111_000.0


def centreline_crossing(way: FakeWay) -> tuple[float, float] | None:
    """Where the way crosses the river's centreline, or None if it does not."""

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    for p, q in zip(way.coordinates, way.coordinates[1:], strict=False):
        for r, s in zip(ANACOSTIA_CENTRELINE, ANACOSTIA_CENTRELINE[1:], strict=False):
            d1, d2 = cross(r, s, p), cross(r, s, q)
            d3, d4 = cross(p, q, r), cross(p, q, s)
            if d1 * d2 < 0 and d3 * d4 < 0:
                t = d1 / (d1 - d2)
                return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
    return None


def south_westward(point: tuple[float, float]) -> float:
    """Distance in metres along the river toward the south-west.

    The river runs north-east to south-west under the three spans, which run
    across it, so the order of their crossing points along this axis is their
    order across the crossing, north-east to south-west.
    """
    (x0, y0), (x1, y1) = ANACOSTIA_CENTRELINE[0], ANACOSTIA_CENTRELINE[-1]
    ux, uy = (x1 - x0) * M_PER_DEG_LON, (y1 - y0) * M_PER_DEG_LAT
    norm = (ux * ux + uy * uy) ** 0.5
    return ((point[0] - x0) * M_PER_DEG_LON * ux + (point[1] - y0) * M_PER_DEG_LAT * uy) / norm


def row_named(name: str) -> dict:
    return next(row for row in crossing_rows() if row["name"] == name)


# Pins are claims about the map, so they are typed in here like every other
# column the fixture carries.
PINNED_WAY_IDS = {
    "11th Street Bridge (local span)": 546096009,
    "11th Street Bridge (I-695 inbound)": 546095934,
}


class TestAPinTheExtractDoesNotCarryIsReported:
    """Owner decision, 2026-09-25: a pinned `osm_way_id` the extract does not
    carry is named in the unmatched list, by both resolvers alike.

    A pin is honoured as written - outside the region, on any way - and that is
    unchanged. What was missing is the one thing the name match was introduced
    to guarantee: a rule that is not biting says so. A pin the map has since
    split or replaced wrote its answer onto a way no longer in the graph, and
    nothing in the rebuild noticed.
    """

    ROWS = (
        {"name": "Pinned Sidepath", "osm_way_id": 7301, "sidepath_only": True},
        {"name": "Pinned Legality", "osm_way_id": 7302, "roadway_bicycle_legal": False},
        {
            "name": "Pinned Both",
            "osm_way_id": 7303,
            "sidepath_only": True,
            "roadway_bicycle_legal": True,
        },
    )

    def resolve(self, ways):
        rows = [dict(row) for row in self.ROWS]
        ids, sidepath_unmatched = resolve_sidepath_bridge_ids(rows, ways)
        legality, legality_unmatched = resolve_bridge_bicycle_legality(rows, ways)
        return ids, sidepath_unmatched, legality, legality_unmatched

    def test_an_absent_pin_is_named_and_still_honoured(self) -> None:
        ids, sidepath_unmatched, legality, legality_unmatched = self.resolve([])
        assert sidepath_unmatched == ["Pinned Both", "Pinned Sidepath"]
        assert legality_unmatched == ["Pinned Both", "Pinned Legality"]
        # A warning, not a refusal: the pin still answers for its way.
        assert ids == frozenset({7301, 7303})
        assert legality == {7302: False, 7303: True}

    def test_a_present_pin_is_not_named(self) -> None:
        # Out of the region and not a bridge, as a pin is allowed to be.
        ways = [FakeWay(i, {"highway": "service"}, ((-76.52, 39.22),)) for i in (7301, 7302, 7303)]
        ids, sidepath_unmatched, legality, legality_unmatched = self.resolve(ways)
        assert sidepath_unmatched == [] and legality_unmatched == []
        assert ids == frozenset({7301, 7303})
        assert legality == {7302: False, 7303: True}

    def test_the_two_resolvers_agree_about_a_row_both_read(self) -> None:
        for present in ((), (7301,), (7303,), (7301, 7302, 7303)):
            ways = [FakeWay(i, {"highway": "service"}) for i in present]
            _ids, sidepath_unmatched, _legality, legality_unmatched = self.resolve(ways)
            assert ("Pinned Both" in sidepath_unmatched) is ("Pinned Both" in legality_unmatched)
            assert ("Pinned Both" in sidepath_unmatched) is (7303 not in present)

    def test_only_the_pinned_way_counts(self) -> None:
        """A pin is a claim about one way; another way carrying the row's name
        does not stand in for it."""
        row = {"name": "Key Bridge", "osm_way_id": 7304, "roadway_bicycle_legal": True}
        named = FakeWay(7305, dict(DC_KEY_BRIDGE.tags))
        assert resolve_bridge_bicycle_legality([row], [named])[1] == ["Key Bridge"]

    def test_a_pinned_row_with_no_name_is_named_by_its_pin(self) -> None:
        row = {"osm_way_id": 7306, "roadway_bicycle_legal": False}
        assert resolve_bridge_bicycle_legality([row], [])[1] == ["osm_way_id 7306"]

    def test_the_shipped_pins_are_named_when_the_extract_lacks_them(self) -> None:
        _legality, unmatched = resolve_bridge_bicycle_legality(crossing_rows(), [])
        assert {"11th Street Bridge (local span)", "11th Street Bridge (I-695 inbound)"} <= set(
            unmatched
        )
        ways = [*ELEVENTH_STREET_WAYS, *FREEWAY_WAYS]
        _legality, unmatched = resolve_bridge_bicycle_legality(crossing_rows(), ways)
        assert "11th Street Bridge (local span)" not in unmatched
        assert "11th Street Bridge (I-695 inbound)" not in unmatched


class TestTheEleventhStreetCrossingIsPinnedByGeometry:
    """The local span and the inbound freeway span, pinned by `osm_way_id`.

    By name the local span can only be reached as "11th Street Southeast", which
    four bridge ways carry and only one of which crosses the river, and the
    freeway spans carry no name of their own. So the pins are chosen by where
    the ways cross the Anacostia, and cross-checked against the owner's
    statement of 2026-09-25: the south-westernmost of the three spans is the
    ordinary roadway, carrying the shared-use path on its south-west side, and
    the other two are I-695.
    """

    def test_only_the_pinned_way_named_for_the_street_crosses_the_river(self) -> None:
        crossing = {w.osm_id for w in ELEVENTH_STREET_WAYS if centreline_crossing(w)}
        assert crossing == {PINNED_WAY_IDS["11th Street Bridge (local span)"]}

    def test_the_pinned_local_span_is_the_south_westernmost_road_span(self) -> None:
        local = next(w for w in ELEVENTH_STREET_WAYS if centreline_crossing(w))
        local_at = south_westward(centreline_crossing(local))
        freeway = [w for w in FREEWAY_WAYS if centreline_crossing(w)]
        assert freeway, "the freeway spans must cross the river too"
        for way in freeway:
            assert south_westward(centreline_crossing(way)) < local_at, way.osm_id

    def test_the_path_lies_on_the_local_spans_south_west_edge(self) -> None:
        local = next(w for w in ELEVENTH_STREET_WAYS if centreline_crossing(w))
        path_at = centreline_crossing(RIVERWALK_ON_THE_LOCAL_SPAN)
        assert path_at is not None, "the path crosses the river"
        gap = south_westward(path_at) - south_westward(centreline_crossing(local))
        assert 0 < gap < 30, f"the path is {gap:.0f} m south-west of the roadway"

    def test_the_path_is_a_routable_trail_class_way(self) -> None:
        tags = RIVERWALK_ON_THE_LOCAL_SPAN.tags
        assert is_trail_class(tags)
        assert tags["bicycle"] in ("yes", "designated")
        assert not {"access", "vehicle"} & set(tags)

    def test_the_inbound_pin_is_the_one_freeway_way_drawn_north_west_across_the_river(
        self,
    ) -> None:
        """Oneway ways are drawn in their direction of travel, so the way that
        crosses the river running north-west is the inbound span; it is one
        way. The outbound side is two ways across the centreline, which one
        `osm_way_id` cannot say, so that row stays unpinned."""

        def north_westward(way: FakeWay) -> bool:
            (x0, y0), (x1, y1) = way.coordinates[0], way.coordinates[-1]
            return x1 < x0 and y1 > y0

        crossing = [w for w in FREEWAY_WAYS if centreline_crossing(w)]
        inbound = {w.osm_id for w in crossing if north_westward(w)}
        outbound = {w.osm_id for w in crossing if not north_westward(w)}
        assert inbound == {PINNED_WAY_IDS["11th Street Bridge (I-695 inbound)"]}
        assert len(outbound) > 1

    def test_the_fixture_carries_exactly_these_pins(self) -> None:
        for row in crossing_rows():
            assert int(row.get("osm_way_id") or 0) == PINNED_WAY_IDS.get(row["name"], 0), row[
                "name"
            ]

    def test_the_resolvers_land_the_rows_on_the_pinned_ways_and_nowhere_else(self) -> None:
        ways = [*ELEVENTH_STREET_WAYS, *FREEWAY_WAYS, RIVERWALK_ON_THE_LOCAL_SPAN]
        rows = crossing_rows()
        legality, unmatched = resolve_bridge_bicycle_legality(rows, ways)
        on_these = {w.osm_id for w in ways}
        assert {k: v for k, v in legality.items() if k in on_these} == {
            546096009: True,
            546095934: False,
        }
        assert "11th Street Bridge (local span)" not in unmatched
        assert "11th Street Bridge (I-695 inbound)" not in unmatched
        assert "11th Street Bridge (I-695 outbound)" in unmatched
        ids, _ = resolve_sidepath_bridge_ids(rows, ways)
        assert not ids & on_these, "no 11th Street row is sidepath-only"

    def test_the_owners_legality_answers_stand(self) -> None:
        """Owner, 2026-09-25: the local span's roadway and its path are legal to
        ride, and the I-695 spans restrict bicycles. Pinning moved no column."""
        local = row_named("11th Street Bridge (local span)")
        assert (local["roadway_bicycle_legal"], local["sidepath_only"]) == (True, False)
        for name in ("11th Street Bridge (I-695 inbound)", "11th Street Bridge (I-695 outbound)"):
            row = row_named(name)
            assert (row["roadway_bicycle_legal"], row["sidepath_only"]) == (False, False)
