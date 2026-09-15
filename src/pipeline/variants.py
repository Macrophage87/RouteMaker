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

from collections.abc import Iterable
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
    """Whether a way is trail class.

    Sidepath-only bridge ways count, because most Potomac and Anacostia
    crossings are bike-legal only by a sidepath, and a definition that missed
    them would leave the no-trail variant thinking those crossings are roadways
    and hand a mass ride the Key Bridge sidewalk.

    The id set is taken pre-built rather than as an iterable, because building a
    set per way turns a whole-extract pass into a quadratic one.
    """
    if tags.get("highway") in TRAIL_CLASS_HIGHWAY:
        return True
    # The id is a parameter rather than a tag. An earlier version read it from
    # `tags["_osm_id"]`, which only a test ever set: a way read from a real PBF
    # carries OSM's own tags and nothing else, so the sidepath lookup could never
    # match and the test proved the function rather than the pipeline.
    return osm_id is not None and osm_id in sidepath_bridge_ids


def is_sidepath_only(row: dict) -> bool:
    """Whether a crossing row describes a bridge bike-legal only by a sidepath."""
    return bool(row.get("sidepath_only") or row.get("roadway_bicycle_legal") is False)


def load_sidepath_bridge_ids(rows: Iterable[dict]) -> frozenset[int]:
    """The explicitly recorded way ids among the crossing rows.

    Most rows carry no id. See `resolve_sidepath_bridge_ids` for why, and for the
    path that actually populates the set.
    """
    return frozenset(
        int(row["osm_way_id"])
        for row in rows
        # Way id 0 means no id has been recorded for this crossing. Skipped
        # rather than matched against way 0, which exists and is not a bridge.
        if int(row.get("osm_way_id") or 0) != 0 and is_sidepath_only(row)
    )


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
    named after it does not inherit the crossing's legality.

    Unmatched names are returned rather than swallowed. A crossing this
    deployment has an opinion about and cannot find in the extract is a thing an
    operator needs told - it means either the clip moved or the name changed, and
    either way the sidepath rule is not biting on that bridge.
    """
    wanted: dict[str, list[str]] = {}
    explicit: set[int] = set()
    for row in rows:
        if not is_sidepath_only(row):
            continue
        if int(row.get("osm_way_id") or 0) != 0:
            explicit.add(int(row["osm_way_id"]))
            continue
        names = row.get("osm_names") or ([row["name"]] if row.get("name") else [])
        if names:
            wanted[row["name"]] = [name.casefold() for name in names]

    by_name = {name for names in wanted.values() for name in names}
    matched_ids: set[int] = set()
    seen: set[str] = set()
    for way in ways:
        if way.tags.get("bridge") in (None, "no"):
            continue
        name = (way.tags.get("name") or "").casefold()
        if name and name in by_name:
            matched_ids.add(way.osm_id)
            seen.add(name)

    unmatched = [
        label for label, names in wanted.items() if not any(name in seen for name in names)
    ]
    return frozenset(matched_ids | explicit), sorted(unmatched)


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
        return None if is_trail_class(tags, osm_id, sidepath_bridge_ids) else dict(tags)

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
