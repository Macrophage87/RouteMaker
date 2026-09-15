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


def is_trail_class(tags: dict[str, str], sidepath_bridge_ids: frozenset[int] = frozenset()) -> bool:
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
    way_id = tags.get("_osm_id")
    return way_id is not None and int(way_id) in sidepath_bridge_ids


def load_sidepath_bridge_ids(rows: Iterable[dict]) -> frozenset[int]:
    """The way ids of bridges that are bike-legal only by a sidepath.

    Loaded once per rebuild from the checked-in crossings fixture, which records
    roadway and sidepath legality per bridge. Without this threaded into the
    build the fixture has no effect on the graph at all.
    """
    return frozenset(
        int(row["osm_way_id"])
        for row in rows
        if row.get("sidepath_only") or row.get("roadway_bicycle_legal") is False
    )


def inject(
    variant: Variant,
    tags: dict[str, str],
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
        return None if is_trail_class(tags, sidepath_bridge_ids) else dict(tags)

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
