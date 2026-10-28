"""Short links the trail rules close, reopened: ridden where paved or of unknown surface,
walked where dirt.

The owner, 2026-10-28, after the path and tunnel under Airpark Road to the Percheron Trail
(OSM 971529119 and 971529120, `highway=path`, `bicycle=yes`, `surface=unpaved`) was found
closed to every ride type but Mountain Bike: "Short connectors seem to be a common issue".
The audit that followed found every short-link rule (`sidewalks.links`, `cut_throughs`,
`station_links`, `aisle_links`) reads footways or parking aisles only, so a short
`highway=path` the trail rules close (`trailaccess.verdict`) was never a link, however
short. Asked how to open them, the owner chose "Ride paved/unknown, walk dirt": untagged
park paths are ridden, dirt and mountain-bike-class links are walked.

`links` finds them. A link is a group of ways, joined at shared nodes, that:
- each carry one of the reasons the caller names as reopenable (`pipeline.trail_closures`
  passes the mountain-bike class, a natural surface, an untagged park path, a footpath for
  walkers, poor visibility, a hiking route, `sac_scale=hiking` alone, a farm track and a
  working site's walkways) and nothing else closes;
- are no area, nothing indoors and no `bicycle=dismount` way (those keep their own rule);
- add up to at most `CHAIN_MAX_M` (about 500 ft) together, each one too, so a link stays a
  link and a park's whole dirt network stays closed;
- touch bicycle-open ways at two nodes or more, on two ways or more, one of them a trail or
  a public street.

Each way found is ridden or walked by its own tags (`walked`): walked where its surface is
natural, its smoothness bad, or its closure says it is a faint or rated hiking path (poor
visibility, `sac_scale`) or of the mountain-bike class; ridden otherwise. Walking a bicycle
is walking, so a walked link widens nothing a pedestrian may not do.

Pure: `pipeline.trail_closures.add_short_links` calls `links` with the rebuild's ways.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence

from . import trailaccess
from .sidewalks import Placed, _length, bicycle_open, is_trail

# The longest a link may be, all its ways together (about 500 ft): the owner's bound for a
# street-end cut-through (`sidewalks.CUT_THROUGH_M`).
CHAIN_MAX_M = 150.0

# The classes a link may be made of: the trail rules' own (`trailaccess.CANDIDATE_HIGHWAY`),
# a cycleway, and a track (the farm-track rule closes those).
LINK_HIGHWAY = trailaccess.CANDIDATE_HIGHWAY | {"cycleway", "track"}

# The public streets a link may lead to, besides a trail.
STREET_HIGHWAY = frozenset(
    {
        "residential",
        "unclassified",
        "living_street",
        "road",
        "tertiary",
        "tertiary_link",
        "secondary",
        "secondary_link",
        "primary",
        "primary_link",
        "trunk",
        "trunk_link",
    }
)

# The closures that say a way is a hiking path rather than a way to ride: walked whatever
# the surface.
WALKED_REASONS = frozenset(
    {
        trailaccess.MTB,
        trailaccess.NATURAL_SURFACE,
        trailaccess.TRAIL_VISIBILITY,
        trailaccess.SAC_SCALE,
    }
)


def is_candidate(tags: dict[str, str], reason: str | None, reopenable: Collection[str]) -> bool:
    """A way a link may reopen: closed by a reopenable reason alone, and none of the ways
    other rules handle."""
    if reason not in reopenable or tags.get("highway") not in LINK_HIGHWAY:
        return False
    if reason == trailaccess.SAC_SCALE and tags.get("sac_scale") != "hiking":
        return False
    if tags.get("area") == "yes" or tags.get("indoor") not in (None, "no"):
        return False
    return not trailaccess.is_dismount(tags)


def walked(tags: dict[str, str], reason: str | None) -> bool:
    """Whether a link's way is walked rather than ridden: dirt, rough, or a hiking path."""
    return (
        reason in WALKED_REASONS
        or trailaccess.is_natural_surface(tags)
        or tags.get("smoothness") in trailaccess.BAD_SMOOTHNESS
    )


def _anchors(tags: dict[str, str]) -> bool:
    """A bicycle-open way a link may lead from: a trail or a public street."""
    return is_trail(tags) or tags.get("highway") in STREET_HIGHWAY


def links(
    ways: Sequence[Placed],
    reasons: Mapping[int, str],
    reopenable: Collection[str],
    closed: Collection[int] = frozenset(),
) -> dict[int, bool]:
    """The ways to reopen, each mapped to whether it is walked (`walked`). `ways` is (id,
    tags, node ids, a coordinate per node id, None where the extract has none; only a
    candidate's are read); `reasons` the closures by way; `reopenable` the reasons a link
    may lift; `closed` other ways nothing reopens (the Zoo's destination-only spur)."""
    candidates: dict[int, tuple[dict[str, str], Sequence[int], float]] = {}
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or not is_candidate(tags, reasons.get(osm_id), reopenable):
            continue
        metres = _length(coords)
        if metres <= CHAIN_MAX_M and len(node_ids) >= 2:
            candidates[osm_id] = (tags, node_ids, metres)
    if not candidates:
        return {}
    by_node: dict[int, list[int]] = defaultdict(list)
    for osm_id, (_tags, node_ids, _metres) in candidates.items():
        for node in set(node_ids):
            by_node[node].append(osm_id)
    # The bicycle-open ways at the candidates' nodes: node -> (way id, anchors?).
    open_at: dict[int, list[tuple[int, bool]]] = defaultdict(list)
    for osm_id, tags, node_ids, _coords in ways:
        if osm_id in candidates or osm_id in reasons or osm_id in closed:
            continue
        if tags.get("area") == "yes" or not bicycle_open(tags):
            continue
        for node in set(node_ids):
            if node in by_node:
                open_at[node].append((osm_id, _anchors(tags)))
    found: dict[int, bool] = {}
    seen: set[int] = set()
    for start in candidates:
        if start in seen:
            continue
        group, stack = [], [start]
        seen.add(start)
        while stack:
            osm_id = stack.pop()
            group.append(osm_id)
            for node in candidates[osm_id][1]:
                for other in by_node[node]:
                    if other not in seen:
                        seen.add(other)
                        stack.append(other)
        if sum(candidates[osm_id][2] for osm_id in group) > CHAIN_MAX_M:
            continue
        nodes = {node for osm_id in group for node in candidates[osm_id][1]}
        touches = [(node, way, anchor) for node in nodes for way, anchor in open_at.get(node, ())]
        if len({node for node, _w, _a in touches}) < 2 or len({w for _n, w, _a in touches}) < 2:
            continue
        if not any(anchor for _n, _w, anchor in touches):
            continue
        for osm_id in group:
            found[osm_id] = walked(candidates[osm_id][0], reasons.get(osm_id))
    return found
