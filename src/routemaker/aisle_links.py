"""Parking aisles and driveways that join a trail to the street, routed as the service
roads they are.

The owner, riding north on Beach Drive at the Maryland line on 2026-10-26: "There seems
to be a missed trail connection here". The Rock Creek Trail (OSM 910564126, `highway=
cycleway`) starts in the small parking lot where Beach Drive crosses into Maryland, and
its only joins to Beach Drive are the lot's aisles (618484538 and 293373615, about 60 ft
[18 m] together, `service=parking_aisle` with no bicycle tag). Valhalla's parser makes
every parking aisle, driveway and drive-through destination-only, and bicycle costing
charges `destination_only_penalty` (600 s) on entering one, so a ride north stayed on
the stretch of Beach Drive open to cars for half a mile (0.8 km) beside the trail.

PR #197 (`lua/routemaker_remap.lua`, `bicycle_link_service`) already routes such a way as
a plain service road where its own tags open it to bicycles. Most trailhead aisles carry
no bicycle tag, though, so here the rebuild finds them by where they lie: where a trail
(a path, cycleway, or a footway or bridleway open to bicycles) ends at a node no other
bicycle-open way reaches (a dead end), and aisles with no bicycle tag lead from it to
another bicycle-open way within `GAP_M`, those aisles become links (`rm:aisle_link`), and
the remap drops their service value as it does for #197's. Bounds, so a link stays a link:
- the gap is at most `GAP_M` (about 260 ft) along the aisles;
- each aisle it opens is at most `WAY_MAX_M` (about 500 ft) long, since the remap changes
  the whole way;
- never an aisle whose `access` or `vehicle` grants less than the public (a private or
  customers-only lot keeps upstream's flag), an area, or one a closure rule closes.
Nothing is widened: an aisle with no bicycle tag is already open to bicycles; only the
price of entering it changes.

Pure: `pipeline.trail_closures.add_aisle_links` calls `links` with the rebuild's ways.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence, Set

from . import tags as osm_tags
from .facility import HIDDEN_SERVICE
from .sidewalks import (
    MANY,
    TRAIL_HIGHWAY,
    Placed,
    _length,
    _metres,
    _shortest_gap,
    bicycle_open,
)

# The longest gap a link may bridge, along the aisles (about 260 ft): a trailhead lot's
# way through, not a drive across a shopping centre.
GAP_M = 80.0
# The longest aisle a link may open (about 500 ft).
WAY_MAX_M = 150.0


def is_candidate(tags: dict[str, str]) -> bool:
    """A parking aisle, driveway or drive-through no bicycle tag speaks for or against, open
    to the public: upstream's transform opens it and makes it destination-only."""
    if tags.get("highway") != "service" or tags.get("service") not in HIDDEN_SERVICE:
        return False
    if any(key == "bicycle" or key.startswith("bicycle:") for key in tags):
        return False
    if tags.get("area") == "yes":
        return False
    tags = osm_tags.narrow_access_lists(tags)
    for key in ("access", "vehicle"):
        value = tags.get(key)
        if value is not None and value not in osm_tags.PERMISSIVE_ACCESS:
            return False
    return bicycle_open(tags)


def links(ways: Sequence[Placed], closed: Set[int] = frozenset()) -> set[int]:
    """The aisles to route as links. `ways` is (id, tags, node ids, a coordinate per node
    id, None where the extract has none; only a candidate's are read, so other ways may
    carry none); `closed` the ways a closure rule closes.

    Two passes, as `sidewalks.links`: the aisle network first, then the bicycle-open
    ways only at the nodes it reaches."""
    adjacent: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
    lengths: dict[int, float] = {}
    aisles: set[int] = set()
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not is_candidate(tags):
            continue
        aisles.add(osm_id)
        lengths[osm_id] = _length(coords)
        for i in range(len(node_ids) - 1):
            a, b = coords[i], coords[i + 1]
            if a is None or b is None:
                continue
            step = _metres(a, b)
            adjacent[node_ids[i]].append((node_ids[i + 1], step, osm_id))
            adjacent[node_ids[i + 1]].append((node_ids[i], step, osm_id))

    # At each node the aisles reach: the one other bicycle-open way there, or MANY.
    open_at: dict[int, int] = {}
    ends: list[tuple[int, int]] = []
    for osm_id, tags, node_ids, _coords in ways:
        if osm_id in closed or osm_id in aisles or len(node_ids) < 2 or not bicycle_open(tags):
            continue
        for node in set(node_ids):
            if node in adjacent:
                open_at[node] = osm_id if open_at.get(node, osm_id) == osm_id else MANY
        if tags.get("highway") in TRAIL_HIGHWAY and node_ids[0] != node_ids[-1]:
            ends.extend(((osm_id, node_ids[0]), (osm_id, node_ids[-1])))

    found: set[int] = set()
    for osm_id, end in ends:
        if open_at.get(end) != osm_id:
            continue  # no aisle meets it, or another bicycle-open way does: no dead end
        gap = _shortest_gap(end, osm_id, open_at, adjacent, GAP_M)
        if gap is None:
            continue
        _metres_used, _reached, used = gap
        if any(lengths[way] > WAY_MAX_M for way in used):
            continue
        found.update(used)
    return found
