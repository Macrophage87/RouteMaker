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

    A sidepath-only bridge - Key Bridge, Chain Bridge - does *not* count here,
    even though its roadway must still be kept off the no-trail variant. Those
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


def is_sidepath_only(row: dict) -> bool:
    """Whether a crossing row's *routing-relevant* provision is a sidepath.

    `sidepath_only` alone, not OR'd with `roadway_bicycle_legal is False`. Those
    are different claims about different bridges: `sidepath_only` says a mass
    ride cannot practically use this crossing's roadway even though an ordinary
    rider legally can (Key Bridge, Chain Bridge - narrow, no shoulder, no way off
    mid-span) and drives the no-trail variant's drop decision;
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
    thing it drops.

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
    either way the sidepath rule is not biting on that bridge.
    """
    rows = list(rows)
    check_crossing_names_unique(rows)
    wanted: dict[str, list[str]] = {}
    explicit: set[int] = set()
    for row in rows:
        if not is_sidepath_only(row):
            continue
        if int(row.get("osm_way_id") or 0) != 0:
            explicit.add(int(row["osm_way_id"]))
            continue
        if names := crossing_names(row):
            wanted[row["name"]] = [name.casefold() for name in names]

    by_name = {name for names in wanted.values() for name in names}
    matched_ids: set[int] = set()
    seen: set[str] = set()
    for way in ways:
        if way.tags.get("bridge") in (None, "no"):
            continue
        # The roadway only; see the docstring. The sidepath is what this rule
        # routes onto, so it is never what the rule matches.
        if way.tags.get("highway") in TRAIL_CLASS_HIGHWAY:
            continue
        name = (way.tags.get("name") or "").casefold()
        if name and name in by_name:
            matched_ids.add(way.osm_id)
            seen.add(name)

    unmatched = [
        label for label, names in wanted.items() if not any(name in seen for name in names)
    ]
    return frozenset(matched_ids | explicit), sorted(unmatched)


def resolve_bridge_bicycle_legality(rows: Iterable[dict], ways: Iterable) -> dict[int, bool]:
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
    """
    rows = list(rows)
    check_crossing_names_unique(rows)
    by_name: dict[str, bool] = {}
    explicit: dict[int, bool] = {}
    for row in rows:
        legal = row.get("roadway_bicycle_legal")
        if legal is None:
            continue
        if int(row.get("osm_way_id") or 0) != 0:
            explicit[int(row["osm_way_id"])] = bool(legal)
            continue
        for name in crossing_names(row):
            by_name[name.casefold()] = bool(legal)

    out: dict[int, bool] = dict(explicit)
    for way in ways:
        if way.tags.get("bridge") in (None, "no"):
            continue
        # The roadway only. A trail-class way carrying the bridge's name is the
        # sidepath on it, not the roadway this column describes, and it is the
        # ordinary OSM shape for a shared-use path on a bridge: the Woodrow
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
        if way.tags.get("highway") in TRAIL_CLASS_HIGHWAY:
            continue
        name = (way.tags.get("name") or "").casefold()
        if name and name in by_name and way.osm_id not in out:
            out[way.osm_id] = by_name[name]
    return out


def unverified_crossing_names(rows: Iterable[dict]) -> list[str]:
    """Names of crossing rows whose `osm_names` have not been checked against a
    real extract.

    Overpass is blocked in this environment, so every name in the fixture -
    including the ones a reviewer supplied - is `osm_names_verified: false`
    today. The loader (`ReferenceData.load` in `run.py`) logs this list at
    rebuild time alongside the unmatched-name warning `resolve_sidepath_bridge_ids`
    already produces, because a name that resolves against the extract and a
    name that is merely believed to be correct are different levels of
    confidence and an operator should be able to tell which crossings are
    which without reading this file.
    """
    return sorted(
        row["name"] for row in rows if row.get("name") and row.get("osm_names_verified") is False
    )


def inject(
    variant: Variant,
    tags: dict[str, str],
    osm_id: int | None = None,
    sidepath_bridge_ids: frozenset[int] = frozenset(),
) -> dict[str, str] | None:
    """Return the tags this variant should build with, or None to drop the way.

    Dropping rather than tagging inaccessible, because a way tagged bicycle=no
    still occupies the graph and still lands in trace results; the no-trail
    variant is meant not to have trails in it at all.
    """
    if variant is Variant.STANDARD:
        return dict(tags)

    if variant is Variant.NO_TRAIL:
        # A sidepath-only bridge is dropped here and only here: it is not trail
        # class (its roadway is an ordinary, bike-legal road on the segment
        # table and on the other two variants), but a mass ride cannot use an
        # eight-foot sidewalk with no way off it mid-span, so the no-trail
        # variant's own drop decision folds the two together rather than
        # `is_trail_class` doing it for every caller.
        is_sidepath_bridge = osm_id is not None and osm_id in sidepath_bridge_ids
        return None if (is_trail_class(tags) or is_sidepath_bridge) else dict(tags)

    if variant is Variant.EBIKE:
        out = dict(tags)
        # An e-bike is barred where electric bicycles are barred, which is not
        # the same set of ways as where bicycles are barred. Expressed through
        # the bicycle tag because Valhalla's bicycle costing is what reads it.
        if out.get("electric_bicycle") == "no":
            out["bicycle"] = "no"
        return out

    raise ValueError(f"unknown variant: {variant}")


def variant_for(allow_trails: bool, ebike_rules: bool) -> Variant:
    """Pick the variant for a request's toggles.

    The two are mutually exclusive until the phase 6 path-avoidance dial, so the
    UI disables e-bike rules while trails are disallowed and explains why rather
    than silently choosing one.
    """
    if not allow_trails and ebike_rules:
        raise ValueError("no-trail and e-bike variants are mutually exclusive until phase 6")
    if not allow_trails:
        return Variant.NO_TRAIL
    return Variant.EBIKE if ebike_rules else Variant.STANDARD
