"""Per-variant tag injection.

All three tile variants are built from the same clipped source extract, with
their differences injected as tags rather than produced by separate pipelines.
One extract means one set of way ids, which is what keeps the segment key, the
stats join and anchor reconciliation meaningful across variants; three extracts
would let the same road carry different ids in different variants.

Variant behaviour is a toggle, never a slider. A dial belongs at layer 2 where
it costs a request option; anything that needs a different graph is a variant.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import Enum

# Trail-class ways are defined once, by highway alone and regardless of bicycle
# tag, because DC-area trails are tagged inconsistently and a definition that
# consulted the bicycle tag would classify the same trail differently on either
# side of a jurisdiction line.
TRAIL_CLASS_HIGHWAY = frozenset({"cycleway", "footway", "path", "pedestrian", "bridleway", "steps"})


class Variant(Enum):
    """Named for what it does, not for who uses it.

    The no-trail variant is not the "mass ride variant": Group Ride uses it
    whenever its trail toggle is off, and naming it after one preset invites the
    assumption that it encodes that preset's other opinions.

    One such opinion it does encode: a crossing row's `roadway_mass_ride_only`
    keeps the roadway in this variant alone, so a Group Ride with trails off is
    routed on the Key Bridge and Memorial Bridge roadways too. The owner
    decided on 2026-09-26 that it may be: asked whether a trails-off Group Ride
    should be kept off those roadways, "No, allow them" - "A trails-off Group
    Ride may use those bridge roadways like a mass ride." `variant_for` gives
    this variant to those two rides and refuses trails-off to any other
    (fixtures/crossings/README.md).
    """

    STANDARD = "standard"
    NO_TRAIL = "no-trail"
    EBIKE = "ebike"


def is_trail_class(
    tags: dict[str, str],
    osm_id: int | None = None,
    sidepath_bridge_ids: frozenset[int] = frozenset(),
) -> bool:
    """Whether a way is trail class, by its highway tag alone.

    A sidepath-only bridge - Chain Bridge, the George Mason span, the Wilson
    Bridge roadway; Key Bridge until 2026-09-26 - does *not* count here, even
    though its roadway must still be kept off the no-trail variant. Those
    are two different questions: this one is "what is this way", asked once and
    answered the same for the segment table and for every variant; the other is
    "should the no-trail variant drop it", which is variant-specific and lives
    in `inject()`'s own combination of this function and the sidepath id lookup.

    Folding the sidepath lookup into this function's *return value* was the
    bug: `is_trail_class` fed both the shared per-way `trail_class` tag (all
    three variants, via `run.py`'s `inject_tags`) and the segment table's
    `is_trail_class` column (via `write_segments`), so Chain Bridge's
    *roadway* - a standard, bike-legal climb out of Georgetown - came out
    trail-class on every variant and on the segment table, and Trailmaxxing's
    road-exposure report counted a roadway bridge as trail.

    `osm_id` and `sidepath_bridge_ids` are still accepted, and still ignored,
    for exactly one reason: both of `run.py`'s existing call sites
    (`inject_tags`'s derived `trail_class` tag, `write_segments`'s
    `is_trail_class` column) pass them today, and the fix that matters is this
    function no longer *acting* on them, not forcing an unrelated call-site
    edit to land in the same change. `inject()` is the only caller that still
    needs the sidepath answer, and it now computes that itself rather than
    asking this function to.
    """
    return tags.get("highway") in TRAIL_CLASS_HIGHWAY


class DuplicateCrossingName(ValueError):
    """Two crossing rows claim the same OSM name.

    Names are how this fixture resolves against the extract, and the lookups
    below merge every row's `osm_names` into one flat dict keyed by the
    casefolded name. A name claimed twice therefore resolves to whichever row
    happened to be written last, silently, and the two rows disagree about the
    two things the fixture exists to record - so this is raised at load time,
    where an operator sees it, rather than resolved by file order.
    """


def crossing_names(row: dict) -> list[str]:
    """Every OSM name this row claims: its `osm_names` spellings, or its label.

    One definition, shared by both resolvers, so the sidepath half and the
    legality half can never disagree about which names belong to a row.
    """
    return list(row.get("osm_names") or ([row["name"]] if row.get("name") else []))


def check_crossing_names_unique(rows: Sequence[dict]) -> None:
    """Refuse a fixture where two rows claim the same OSM name.

    Checked across every row rather than only the rows one resolver looks at,
    because the two resolvers read different subsets - `sidepath_only` rows and
    rows with a `roadway_bicycle_legal` opinion - and a name duplicated across
    the two subsets would be caught by neither while still deciding, by file
    order, which row a bridge in the extract resolves to.
    """
    claimed: dict[str, int] = {}
    for index, row in enumerate(rows):
        for name in crossing_names(row):
            key = name.casefold()
            if claimed.setdefault(key, index) != index:
                first = rows[claimed[key]].get("name")
                raise DuplicateCrossingName(
                    f"{first!r} and {row.get('name')!r} both claim the OSM name {name!r}; "
                    f"one of them is wrong and the file cannot say which"
                )


# The two tags a bridge way can carry a structure's name in. `name` on a road
# way is the *street*: the way over the Anacostia at Pennsylvania Avenue SE is
# named "Pennsylvania Avenue Southeast", because that is what the road is
# called, and the structure's own name lives in `bridge:name` - which is OSM's
# conventional home for it, and the only place "John Philip Sousa Bridge"
# appears on that way. Reading `name` alone meant a row whose crossing is named
# after the structure rather than after the street could never resolve, on
# either side of the fixture, and the miss was silent in the same way a stale
# way id was: the name simply reported unmatched.
#
# Both keys are read, and both are still filtered by the bridge, trail-class
# and region guards below (`is_crossing_candidate`) - `bridge:name` widens which
# *names* a bridge way answers to, not which ways are eligible to answer.
NAME_KEYS = ("name", "bridge:name")


def way_names(way) -> list[str]:
    """Every casefolded name a way carries, from whichever of `NAME_KEYS` it has.

    One definition, shared by both resolvers, for the same reason
    `crossing_names` is shared on the fixture side: the sidepath half and the
    legality half must never disagree about which OSM ways a row's names reach.
    """
    return [value.casefold() for key in NAME_KEYS if (value := way.tags.get(key))]


# The region the crossings fixture is about, as (west, south, east, north): the
# Potomac from the American Legion Bridge down to the Woodrow Wilson Bridge, and
# the Anacostia from the Benning Road Bridge down to the confluence. A row is
# matched by name, and a name is not a place - when the owner extended the
# coverage region to Baltimore and the Mason-Dixon line on 2026-09-24, the
# "Key Bridge" row began matching Baltimore's Francis Scott Key Bridge (I-695,
# `bridge:name`) as well as the District's (US 29), sixty kilometres apart.
#
# Derived from the real extract, not from a map: on the Geofabrik DC+MD+VA
# extract of 2026-09-24, clipped to COVERAGE_BBOX, the ways the fixture's rows
# correctly reach span -77.1800 (American Legion Bridge, west end) to -76.9607
# (Benning Road and Whitney Young bridges, east ends) and 38.7924 (Woodrow Wilson
# Bridge roadway, south edge) to 38.9711 (American Legion Bridge, north end).
# Rounded out by 0.02 degrees on every side - about 1.7 km east-west and 2.2 km
# north-south - so a remapped abutment or a split way does not fall out of it,
# while every other structure sharing a fixture name in that extract lies far
# outside it.
#
# One box for the whole fixture rather than a point per row, because the
# question it answers is "is this way about these two rivers at all", which is
# one question for every row; which structure *within* the region a name means
# is the name's job, and a box drawn per row would be a second, weaker way of
# saying it.
CROSSINGS_SCOPE = (-77.20, 38.77, -76.94, 38.99)


def in_crossing_scope(way) -> bool:
    """Whether every located point of this way lies inside `CROSSINGS_SCOPE`.

    Every point rather than any: a way with one end in the region and the other
    outside it is not a crossing of these two rivers. And a way with no located
    point is refused rather than assumed to be inside - a clipped extract gives
    no location for nodes beyond the clip, so such a way is one the extract
    cannot place, and a row's legality written onto it would be a guess.
    """
    west, south, east, north = CROSSINGS_SCOPE
    points = way.coordinates
    return bool(points) and all(
        west <= lon <= east and south <= lat <= north for lon, lat in points
    )


def is_crossing_candidate(way) -> bool:
    """Whether a crossing row's names may reach this way at all.

    Three guards, in one function so that the two resolvers cannot disagree
    about which ways are eligible:

    * a bridge - a street approaching a crossing and named after it does not
      inherit the crossing's answers;
    * not trail class - a trail-class way carrying the bridge's name is the
      sidepath on it, which is what the sidepath rule routes a mass ride onto
      and what the legality column says nothing about (see each resolver);
    * inside `CROSSINGS_SCOPE` - a structure elsewhere in the coverage region
      that shares a crossing's name is not that crossing.

    An explicit `osm_way_id` on a row bypasses this: it is a pin someone made
    against the clipped extract by hand, and it is honoured as written.
    """
    if way.tags.get("bridge") in (None, "no"):
        return False
    if way.tags.get("highway") in TRAIL_CLASS_HIGHWAY:
        return False
    return in_crossing_scope(way)


def pinned_way_id(row: dict) -> int:
    """The way id a row is pinned to by hand, or 0 for a row matched by name."""
    return int(row.get("osm_way_id") or 0)


def crossing_misses(
    wanted: dict[str, list[str]],
    seen: set[str],
    pinned: dict[str, int],
    present: set[int],
) -> list[str]:
    """The rows a resolver could not find in the extract, by label.

    Two kinds of miss, one list, and one definition for both resolvers so that
    they cannot disagree about a row they both read:

    * a row matched by name none of whose names any eligible way carries;
    * a row pinned to an `osm_way_id` the given ways do not include at all.

    The second is the owner's decision of 2026-09-25. A pin is honoured as
    written - outside `CROSSINGS_SCOPE`, on any way - and still is; but a pin
    the map has since split or replaced wrote its answer onto a way no longer
    in the graph, and nothing said so, which is the silent failure matching by
    name was introduced to end. It is reported, not refused: the row's answer
    still goes out for the id, and the rebuild runs.
    """
    missed = {label for label, names in wanted.items() if not any(name in seen for name in names)}
    missed |= {label for label, way_id in pinned.items() if way_id not in present}
    return sorted(missed)


def crossing_label(row: dict) -> str:
    """How an operator is told about a row: its name, or its pin if it has none."""
    return row.get("name") or f"osm_way_id {pinned_way_id(row)}"


def is_sidepath_only(row: dict) -> bool:
    """Whether a crossing row's *routing-relevant* provision is a sidepath.

    `sidepath_only` alone, not OR'd with `roadway_bicycle_legal is False`. Those
    are different claims about different bridges: `sidepath_only` says a mass
    ride cannot practically use this crossing's roadway, and drives the no-trail
    variant's drop decision (Key Bridge carried it until the owner's decision
    of 2026-09-26 that a mass ride crosses on its roadway; Chain Bridge carries
    it because the owner decided the same day it is not a mass-ride crossing);
    `roadway_bicycle_legal` says whether OSM's `bicycle=no` bars the roadway
    outright (the 14th Street freeway spans, the Wilson Bridge roadway, the
    Theodore Roosevelt Bridge) and drives `resolve_bridge_bicycle_legality`
    instead, applied to every variant because access is not a request-time
    dial. The two columns happened to be perfectly correlated in the fixture
    this file used to ship with, which is why OR-ing them together tested green
    while being inert: every row where it mattered had both flags agreeing.
    American Legion Bridge and the Theodore Roosevelt Bridge are the fixture
    rows that pull them apart - barred outright, with no sidepath standing in.
    """
    return bool(row.get("sidepath_only"))


def is_roadway_mass_ride_only(row: dict) -> bool:
    """Whether a crossing row's roadway is reserved for mass rides.

    The owner's rule of 2026-09-26 for Key Bridge and Arlington Memorial Bridge:
    a mass ride takes the roadway, and an ordinary rider is sent by the sidepath
    ("I wouldn't route someone onto that outside of a mass ride"). So the
    no-trail variant keeps the roadway and the standard and e-bike variants bar
    it, the opposite split to `sidepath_only`. The no-trail variant is not
    itself mass-ride-only - PLAN gives it to Group Ride with trails off too -
    and the owner ruled on that too, on 2026-09-26: "No, allow them" ("A
    trails-off Group Ride may use those bridge roadways like a mass ride.").
    So the roadway is for a mass ride or a trails-off Group Ride, and
    `variant_for` refuses trails-off to any other ride. It is a routing rule,
    not a legal claim: `roadway_bicycle_legal` stays the legality column, and
    is true on both rows.
    """
    return bool(row.get("roadway_mass_ride_only"))


class ContradictoryCrossingRow(ValueError):
    """A crossing row whose columns cannot all be obeyed at once."""


def check_crossing_rows_consistent(rows: Sequence[dict]) -> None:
    """Refuse a row that says its roadway is a mass ride's and also that it is not.

    `roadway_mass_ride_only` bars the roadway from the standard and e-bike
    variants and leaves it to the no-trail one. With `sidepath_only` the no-trail
    variant drops it too, and with `roadway_bicycle_legal: false` it is barred
    to every bicycle - either way the roadway would be in no graph at all, for a
    row that says a mass ride rides it. Checked at load, where an operator sees
    it, by every resolver, like the duplicate-name check.
    """
    for row in rows:
        if not is_roadway_mass_ride_only(row):
            continue
        if is_sidepath_only(row) or row.get("roadway_bicycle_legal") is False:
            raise ContradictoryCrossingRow(
                f"{crossing_label(row)!r} is roadway_mass_ride_only, but its roadway is "
                "also sidepath_only or not bicycle-legal, so no variant could use it"
            )


def _resolve_flagged_bridge_ids(
    rows: list[dict], ways: Iterable, flagged
) -> tuple[frozenset[int], list[str]]:
    """The roadway ways of the rows `flagged` selects, and the rows not found.

    One matcher for the two per-way id sets (`sidepath_only`,
    `roadway_mass_ride_only`): by name against `is_crossing_candidate` ways, or
    by a hand pin, with misses reported by `crossing_misses`.
    """
    check_crossing_names_unique(rows)
    check_crossing_rows_consistent(rows)
    wanted: dict[str, list[str]] = {}
    explicit: set[int] = set()
    pinned: dict[str, int] = {}
    for row in rows:
        if not flagged(row):
            continue
        if way_id := pinned_way_id(row):
            explicit.add(way_id)
            pinned[crossing_label(row)] = way_id
            continue
        if names := crossing_names(row):
            wanted[row["name"]] = [name.casefold() for name in names]

    by_name = {name for names in wanted.values() for name in names}
    matched_ids: set[int] = set()
    seen: set[str] = set()
    present: set[int] = set()
    for way in ways:
        # Every way, before any guard: a pin bypasses them, so the question
        # for a pin is only whether the extract carries its way at all.
        present.add(way.osm_id)
        # A bridge, the roadway only (the sidepath is what these rules route
        # onto, so it is never what they match; see the docstrings), and
        # inside the fixture's region.
        if not is_crossing_candidate(way):
            continue
        for name in way_names(way):
            if name in by_name:
                matched_ids.add(way.osm_id)
                seen.add(name)

    return frozenset(matched_ids | explicit), crossing_misses(wanted, seen, pinned, present)


def resolve_mass_ride_only_bridge_ids(
    rows: Iterable[dict], ways: Iterable
) -> tuple[frozenset[int], list[str]]:
    """The roadway ways of the `roadway_mass_ride_only` rows, and the rows not found.

    Matched exactly as `resolve_sidepath_bridge_ids` matches, through the same
    guards. The trail-class guard matters most here: the sidewalk or cycleway
    named after the bridge is the crossing an ordinary rider is sent by, and
    barring it with the roadway would leave the standard and e-bike variants
    no crossing there at all.
    """
    return _resolve_flagged_bridge_ids(list(rows), ways, is_roadway_mass_ride_only)


# The column naming the ways an ordinary ride is steered off by a penalty.
ORDINARY_RIDE_PENALTY_COLUMN = "ordinary_ride_penalty_way_ids"


class MalformedCrossingRow(ValueError):
    """A crossing row whose column cannot be read as the file documents it."""


def ordinary_ride_penalty_way_ids(row: dict) -> list[int]:
    """The ways a row puts an ordinary-ride penalty on, by OSM way id.

    A list of ids rather than names, because the ways it names are not the
    bridge: they are the roads a rider lands on, which no name match reaches
    (`is_crossing_candidate` admits bridge ways only, and a street is not named
    after its landing). The rows are pins, reported when the extract no longer
    carries them, like a row's `osm_way_id`. Absent means none. Anything but a
    list of positive integers is refused rather than read as none.
    """
    ids = row.get(ORDINARY_RIDE_PENALTY_COLUMN)
    if ids is None:
        return []
    if not isinstance(ids, list) or not all(
        isinstance(way_id, int) and not isinstance(way_id, bool) and way_id > 0 for way_id in ids
    ):
        raise MalformedCrossingRow(
            f"{crossing_label(row)!r}: {ORDINARY_RIDE_PENALTY_COLUMN} must be a list of "
            f"positive OSM way ids, not {ids!r}"
        )
    return list(ids)


def resolve_ordinary_ride_penalty_ids(
    rows: Iterable[dict], ways: Iterable
) -> tuple[frozenset[int], list[str]]:
    """The ways the standard and e-bike variants carry a routing penalty on.

    The owner's answer of 2026-09-26 on the 11th Street local span, asked
    whether the planner should steer ordinary riders going south from the Navy
    Yard back to the Anacostia Riverwalk once the span's south landing was open
    to them: "Steer to the path" - "Keep it legal but add a penalty on that
    roadway for ordinary rides so the Riverwalk wins when it's close in
    length." A penalty, not a bar: the ways stay legal and routable, and a
    route still takes them where they are clearly shorter or the only way. The
    no-trail variant is left as it was (`run.inject_tags` emits the tag on the
    other two only), since the owner's question was about ordinary rides.

    Returns the ids and, per row, the ids the given ways do not include, as
    `crossing_misses` reports a stale pin: the penalty still goes out for the
    id, and the rebuild runs.
    """
    ids: set[int] = set()
    missing: dict[str, list[int]] = {}
    rows = list(rows)
    for row in rows:
        for way_id in ordinary_ride_penalty_way_ids(row):
            ids.add(way_id)
            missing.setdefault(crossing_label(row), []).append(way_id)
    present = {way.osm_id for way in ways}
    misses = [
        f"{label} ({ORDINARY_RIDE_PENALTY_COLUMN}: {', '.join(str(i) for i in absent)})"
        for label, wanted in sorted(missing.items())
        if (absent := [way_id for way_id in wanted if way_id not in present])
    ]
    return frozenset(ids), misses


def resolve_sidepath_bridge_ids(
    rows: Iterable[dict], ways: Iterable
) -> tuple[frozenset[int], list[str]]:
    """Match the crossing rows against the extract, by name and then by id.

    Returns the way ids and the names that matched nothing.

    By name, because a way id is the wrong thing to check into a repository: OSM
    ids change whenever a mapper splits a bridge into two ways or replaces it
    after a rebuild, and a fixture full of stale ids fails the way this one did -
    every row carried id 0, so the set was empty, so the no-trail variant treated
    the Key Bridge sidewalk as a roadway and nothing reported it. A name is
    community knowledge that ages at the pace of the bridge rather than the pace
    of the map, which is also how the authority columns in this fixture work.

    Restricted to ways tagged as bridges, so a street approaching a crossing and
    named after it does not inherit the crossing's legality. And to *roadway*
    bridges: a trail-class way carrying the bridge's name is the sidepath on it,
    which is the thing this rule routes a mass ride onto and can never be the
    thing it drops. And to ways inside `CROSSINGS_SCOPE`, the region the fixture
    is about, because a name is not a place: Baltimore has a Francis Scott Key
    Bridge too. All three guards are `is_crossing_candidate`, shared with
    `resolve_bridge_bicycle_legality` so the two cannot disagree.

    That guard is the one `resolve_bridge_bicycle_legality` has had, for the
    same reason and on the same OSM shape - a shared-use path on a bridge is its
    own `highway=cycleway` or `footway` way, tagged `bridge=yes` and named after
    the structure. Without it here the match was satisfied by the wrong ways and
    said nothing: the two footways named "Francis Scott Key Bridge" matched, so
    the name came off the `unmatched` list, so nothing warned - and the Key
    Bridge *roadway*, the way the whole rule exists to keep a field of hundreds
    off, stayed in the no-trail graph while the sidewalk it should have routed
    onto was dropped from it as trail class.

    Unmatched names are returned rather than swallowed. A crossing this
    deployment has an opinion about and cannot find in the extract is a thing an
    operator needs told - it means either the clip moved or the name changed, and
    either way the sidepath rule is not biting on that bridge. So is a row
    pinned to an `osm_way_id` the given ways do not carry (`crossing_misses`).
    """
    return _resolve_flagged_bridge_ids(list(rows), ways, is_sidepath_only)


def resolve_bridge_bicycle_legality(
    rows: Iterable[dict], ways: Iterable
) -> tuple[dict[int, bool], list[str]]:
    """Per-way *roadway* bicycle legality, from the crossing fixture.

    Roadway, as the column and this docstring have always said, and now as the
    code does: trail-class ways are excluded even when they carry the bridge's
    own name.

    A different question from `resolve_sidepath_bridge_ids`, matched the same
    way (by name against a bridge-tagged way, or by an explicit `osm_way_id`).
    That one asks "should the no-trail variant drop this way", a routing
    decision that applies to one variant. This asks "does OSM's `bicycle` tag
    bar the roadway outright" - a legal fact, true or false on every variant
    alike, because access is not a request-time dial. It is what
    `rm:bridge_bicycle` carries into `graph.lua`, which the transform already
    reads (`derived.bridge_bicycle_legal`) but which no stage has ever emitted -
    the caller (`run.py`'s `inject_tags`) needs to set
    `changes["rm:bridge_bicycle"] = "yes" if legal else "no"` for every way this
    returns, on every variant, not only the no-trail one.

    Rows with no opinion (`roadway_bicycle_legal` absent or `None`) are left out
    entirely, so the pipeline never injects a legality tag it has no fixture
    backing for and OSM's own tagging is left to stand.

    Returns the mapping *and* the names that matched nothing, exactly as
    `resolve_sidepath_bridge_ids` does, and for the same reason. Only that one
    reported its misses, so the only crossings an operator ever heard about were
    the four `sidepath_only` rows; the fourteen rows that carry a legality
    opinion and no sidepath flag - the Theodore Roosevelt Bridge among them -
    resolved against nothing and said nothing. A reviewer ran it: with an extract carrying only
    the four sidepath bridges, `unmatched` was empty and fourteen legality rows
    were inert, reported nowhere. The two lists are logged as one union by
    `ReferenceData.load`, because "this crossing is not in the extract" is one
    fact about one bridge however many of the fixture's columns it silences.
    """
    rows = list(rows)
    check_crossing_names_unique(rows)
    check_crossing_rows_consistent(rows)
    by_name: dict[str, bool] = {}
    explicit: dict[int, bool] = {}
    wanted: dict[str, list[str]] = {}
    pinned: dict[str, int] = {}
    for row in rows:
        legal = row.get("roadway_bicycle_legal")
        if legal is None:
            continue
        if way_id := pinned_way_id(row):
            explicit[way_id] = bool(legal)
            pinned[crossing_label(row)] = way_id
            continue
        if names := crossing_names(row):
            wanted[row["name"]] = [name.casefold() for name in names]
        for name in crossing_names(row):
            by_name[name.casefold()] = bool(legal)

    out: dict[int, bool] = dict(explicit)
    seen: set[str] = set()
    present: set[int] = set()
    for way in ways:
        # Every way, before any guard; see `resolve_sidepath_bridge_ids`.
        present.add(way.osm_id)
        # A bridge, inside the fixture's region, and the roadway only. A
        # trail-class way carrying the bridge's name is the sidepath on it, not
        # the roadway this column describes, and it is the ordinary OSM shape
        # for a shared-use path on a bridge: the Woodrow
        # Wilson path, the 14th Street path and the Key Bridge sidewalk are all
        # `highway=cycleway` or `footway` ways tagged `bridge=yes` and named
        # after the structure they run on.
        #
        # Without this the name match reached them, every variant got
        # `rm:bridge_bicycle=no`, and `routemaker_remap` turned that into
        # `bicycle=no` - deleting the only bicycle crossing of the Potomac at
        # those three points from all three graphs, on the strength of a column
        # that says nothing about the path. The guard is the one `conflate()`
        # takes on the same geometry (a trail beside a road is not the road) and
        # the one the `cycleway=track` write already has for the same reason (a
        # derived tag written onto a trail-class way changes its access).
        if not is_crossing_candidate(way):
            continue
        for name in way_names(way):
            if name not in by_name:
                continue
            # Seen whether or not this way is the one recorded: the question the
            # unmatched list answers is whether the extract carries the
            # crossing at all, and an id an operator pinned by hand does not
            # make the name a miss.
            seen.add(name)
            if way.osm_id not in out:
                out[way.osm_id] = by_name[name]

    return out, crossing_misses(wanted, seen, pinned, present)


def unverified_crossing_names(rows: Iterable[dict]) -> list[str]:
    """Names of crossing rows whose `osm_names` have not been checked against a
    real extract.

    Overpass is blocked in this environment, so every name in the fixture -
    including the ones a reviewer supplied - is `osm_names_verified: false`
    today. The loader (`ReferenceData.load` in `run.py`) logs this list at
    rebuild time alongside the unmatched-name warning the two resolvers produce
    between them, because a name that resolves against the extract and a
    name that is merely believed to be correct are different levels of
    confidence and an operator should be able to tell which crossings are
    which without reading this file.
    """
    return sorted(
        row["name"] for row in rows if row.get("name") and row.get("osm_names_verified") is False
    )


def bars_electric_bicycle(tags: dict[str, str]) -> bool:
    """Whether this way bars electric bicycles, by the rule the e-bike bar uses.

    A function rather than a comparison written twice, because two places have
    to agree about it exactly: `inject` writes `bicycle=no` on these ways for
    the e-bike variant, and `run.inject_tags` withholds the crossings fixture's
    roadway legality from that same variant on them, so that the transform does
    not grant back the access this bar has just taken away. A second spelling of
    the rule in the second place - `!= "yes"`, or any of `private`, `destination`
    and `customers` folded in - would suppress the fixture's row on ways the bar
    never touched.

    `== "no"` and nothing wider, deliberately. `electric_bicycle=private` or
    `=destination` restricts who may ride, not whether an e-bike is a vehicle
    the way admits, and `inject` does not bar those ways; what this function
    answers is "did the e-bike variant bar this way", which is one question with
    one answer.
    """
    return tags.get("electric_bicycle") == "no"


# The keys `bar_mass_ride_only_roadway` writes `no` on: the plain key, and a
# directional key already present, because Valhalla lets `bicycle:forward` and
# `bicycle:backward` override the plain key one direction at a time. Not the
# only keys Valhalla opens a way from - see `REOPENING_KEYS` below.
BICYCLE_KEYS = ("bicycle", "bicycle:forward", "bicycle:backward")

# And the conditional keys, where present. Valhalla reads none of them, but
# `routemaker_remap.remap_conditional_access` does: it writes the least
# restrictive branch of a conditional onto `bicycle:forward`/`:backward`, so a
# `bicycle:conditional=yes @ (Sa,Su)` would reopen the roadway the bar closed.
# A bare `no` parses as an unconditional `no`, which is never less restrictive
# than the base, so the remap writes nothing.
BICYCLE_CONDITIONAL_KEYS = (
    "bicycle:conditional",
    "bicycle:forward:conditional",
    "bicycle:backward:conditional",
)


# And the keys the bar closes. Upstream's `ways_proc` (lua/graph_upstream.lua)
# derives bicycle access from more than the bicycle keys: a `cycleway`,
# `cycleway:both`, `cycleway:left`/`:right` lane or shared lane turns bike
# access on in both directions, `cycleway=opposite_lane` on a oneway opens the
# contraflow, as does `oneway:bicycle=no`, and `vehicle:forward`/`:backward=yes`
# opens that direction - each of them over a plain `bicycle=no`, measured
# through lua/graph.lua under LuaJIT (tests/test_lua_remap.py). None is on the
# Key or Memorial roadway today (Memorial carries `cycleway:both=no`); one OSM
# edit adding sharrows would have put ordinary riders back on it with nothing
# reporting it. Each is set to the value that grants nothing - `no` for the
# cycleway and vehicle keys, `yes` for `oneway:bicycle` so a bicycle follows
# the way's oneway - and not removed, because a removal cannot reach the
# written extract (`bar_mass_ride_only_roadway`). The vehicle keys only ever
# describe this variant's graph, which no motor-vehicle router reads.
REOPENING_KEYS = ("vehicle:forward", "vehicle:backward", "oneway:bicycle")
REOPENING_KEYS_CLOSED = {"oneway:bicycle": "yes"}


def is_reopening_key(key: str) -> bool:
    return key == "cycleway" or key.startswith("cycleway:") or key in REOPENING_KEYS


def bar_mass_ride_only_roadway(tags: dict[str, str]) -> None:
    """Bar a `roadway_mass_ride_only` roadway to the variant being built, in place.

    The bar wins over an approved `bicycle=yes` access override on the same
    way, deliberately. The override says bicycles are *legal* there, which the
    fixture's `roadway_bicycle_legal: true` already says of both such roadways;
    the bar says ordinary riders are not *routed* there (owner, 2026-09-26),
    which is a different question the override does not answer. The no-trail
    variant is untouched by the bar and carries the override as written.
    """
    tags["bicycle"] = "no"
    for key in (*BICYCLE_KEYS[1:], *BICYCLE_CONDITIONAL_KEYS):
        if key in tags:
            tags[key] = "no"
    # Rewritten, not removed: `inject_tags` diffs this against the source and
    # `extract.write_extract` lays the difference over the source's own tags,
    # so a deleted key comes back in the written extract with OSM's value.
    for key in tags:
        if is_reopening_key(key):
            tags[key] = REOPENING_KEYS_CLOSED.get(key, "no")


def inject(
    variant: Variant,
    tags: dict[str, str],
    osm_id: int | None = None,
    sidepath_bridge_ids: frozenset[int] = frozenset(),
    mass_ride_only_ids: frozenset[int] = frozenset(),
) -> dict[str, str] | None:
    """Return the tags this variant should build with, or None to drop the way.

    Dropping rather than tagging inaccessible, because a way tagged bicycle=no
    still occupies the graph and still lands in trace results; the no-trail
    variant is meant not to have trails in it at all.

    A `roadway_mass_ride_only` roadway (`mass_ride_only_ids`) is the other way
    round, and barred rather than dropped: it stays in the standard and e-bike
    graphs, as the road a trace can still land on, with `bicycle=no`, and the
    no-trail variant keeps it as it is.
    """
    is_mass_ride_only = osm_id is not None and osm_id in mass_ride_only_ids

    if variant is Variant.STANDARD:
        out = dict(tags)
        if is_mass_ride_only:
            bar_mass_ride_only_roadway(out)
        return out

    if variant is Variant.NO_TRAIL:
        # A sidepath-only bridge is dropped here and only here: it is not trail
        # class (its roadway is an ordinary road on the segment table and on
        # the other two variants), but the row says a mass ride cannot use it,
        # so the no-trail variant's own drop decision folds the two together
        # rather than `is_trail_class` doing it for every caller.
        is_sidepath_bridge = osm_id is not None and osm_id in sidepath_bridge_ids
        return None if (is_trail_class(tags) or is_sidepath_bridge) else dict(tags)

    if variant is Variant.EBIKE:
        out = dict(tags)
        if is_mass_ride_only:
            bar_mass_ride_only_roadway(out)
        # An e-bike is barred where electric bicycles are barred, which is not
        # the same set of ways as where bicycles are barred. Expressed through
        # the bicycle tag because Valhalla's bicycle costing is what reads it.
        if bars_electric_bicycle(out):
            out["bicycle"] = "no"
        return out

    raise ValueError(f"unknown variant: {variant}")


class NoTrailIsNotForThisRide(ValueError):
    """A ride PLAN gives no trails-off option asked for the no-trail variant."""


# The rides PLAN gives a trails-off option, by the route API's preset names:
# Mass Ride, whose trails are fixed off (PLAN.md:100, "L1: no-trail variant"),
# and Group Ride, whose "Allow bike paths and trails" toggle "switches to the
# no-trail variant when off" (PLAN.md:99). No other preset's layer assignment
# names the no-trail variant.
TRAILS_OFF_RIDES = frozenset({"mass-ride", "group-ride"})


def variant_for(allow_trails: bool, ebike_rules: bool, *, ride: str | None = None) -> Variant:
    """Pick the variant for a request's toggles.

    The two are mutually exclusive until the phase 6 path-avoidance dial, so the
    UI disables e-bike rules while trails are disallowed and explains why rather
    than silently choosing one.

    And trails off gives the no-trail variant only to a ride in
    `TRAILS_OFF_RIDES`. That variant keeps the roadways the crossings fixture
    marks `roadway_mass_ride_only` (Key Bridge and Arlington Memorial Bridge),
    which the owner reserved on 2026-09-26 ("I wouldn't route someone onto that
    outside of a mass ride.") and then, the same day, opened to a trails-off
    Group Ride: asked whether Group Ride with the toggle off should be kept off
    those roadways, "No, allow them" - "A trails-off Group Ride may use those
    bridge roadways like a mass ride." So Group Ride with trails off shares the
    variant, roadways and all, and any other ride asking for trails off is
    refused, since PLAN gives it no such option. A caller that picks
    `Variant.NO_TRAIL` by name bypasses this - the Mass Ride preset does.
    """
    if not allow_trails and ebike_rules:
        raise ValueError("no-trail and e-bike variants are mutually exclusive until phase 6")
    if not allow_trails:
        if ride not in TRAILS_OFF_RIDES:
            raise NoTrailIsNotForThisRide(
                f"PLAN gives no trails-off option to ride {ride!r}; the no-trail variant "
                f"is for {', '.join(sorted(TRAILS_OFF_RIDES))} only"
            )
        return Variant.NO_TRAIL
    return Variant.EBIKE if ebike_rules else Variant.STANDARD
