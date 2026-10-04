"""Paths and trails a bicycle is routed on that it should not be.

OWNER-DECISIONS 278, 280, 281, decided in 290 and 291. A path where cycling is
not allowed is neither routed nor drawn as a bike facility, and a trail only a
mountain bike rides is not a standard route's LTS 1 path.

The rebuild marks such a way `rm:no_bicycle=<reason>` and the transform closes
it to bicycles on every graph that does not reopen the reason. Reasons written
here (singletrack, cbd_sidewalk and zoo live in their own modules):

- `private`: `access` private/permit/customers/restricted, or `bicycle`
  private/permit/residents, with no bicycle tag that says yes.
- `sac_scale`: a hiking-difficulty rating, no bicycle tag (Valhalla reads
  `sac_scale=hiking` as a grant; this takes it back). Paved exempt.
- `informal`: `informal=yes`, no bicycle tag.
- `foot_designated`: a `path` designated for foot, no bicycle tag. Paved exempt.
- `trail_visibility`: intermediate or worse, no bicycle tag. Paved exempt.
- `hiking_route`: a `path` in hiking/foot route relations and no bicycle route
  relation, no bicycle tag. Paved exempt.
- `natural_surface`: a `path` on a natural surface, no bicycle tag, no exemption.
- `park_path`: a plain `highway=path` (no bicycle, surface, smoothness signal)
  inside a park or protected-area polygon (291(1)); kept elsewhere.
- `mtb`: the mountain-bike class below.
- `dismount`: a `bicycle=dismount` connector that is not short (291(5)).

Never touched: cycleways, sidewalks, crossings, steps, and ways upstream's
transform already leaves closed (`upstream_open`).

Exemptions from the natural-surface rules: hard surface or gravel, fine_gravel,
compacted; membership of an ncn/icn bicycle route (not rcn: the Cross County
Trail is rcn and holds its rough sections); smoothness good or excellent;
tracktype grade 1-3; width >= 2 m; mtb:scale 0.

Mountain-bike class (280, 281, 291(2)), section by section: a non-exempt path or
footway whose surface is natural, or smoothness bad or worse, or mtb:scale
>= 1, or sac_scale beyond hiking. Rated singletrack keeps its own reason and
stays closed everywhere; the rest is closed on the standard graphs and open on
the off-road graph Gravel and Mountain Goat ride (Variant.OFFROAD).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from . import facility, singletrack

PRIVATE = "private"
SAC_SCALE = "sac_scale"
INFORMAL = "informal"
FOOT_DESIGNATED = "foot_designated"
TRAIL_VISIBILITY = "trail_visibility"
HIKING_ROUTE = "hiking_route"
NATURAL_SURFACE = "natural_surface"
PARK_PATH = "park_path"
MTB = "mtb"
DISMOUNT = "dismount"

TAG_REASONS = (
    PRIVATE,
    SAC_SCALE,
    INFORMAL,
    FOOT_DESIGNATED,
    TRAIL_VISIBILITY,
    HIKING_ROUTE,
    NATURAL_SURFACE,
    PARK_PATH,
    MTB,
    DISMOUNT,
)

CANDIDATE_HIGHWAY = frozenset({"path", "footway", "pedestrian", "bridleway"})
PRIVATE_ACCESS = frozenset({"private", "permit", "customers", "restricted"})
PRIVATE_BICYCLE = frozenset({"private", "permit", "residents"})

NATURAL_SURFACES = frozenset(
    {
        "ground",
        "dirt",
        "earth",
        "grass",
        "mud",
        "sand",
        "woodchips",
        "unpaved",
        "rock",
        "pebblestone",
        "clay",
        "soil",
        "snow",
        "ice",
        "grass_paver",
    }
)
LOOSE_EXEMPT_SURFACES = frozenset({"gravel", "fine_gravel", "compacted"})
HARD_SURFACES = singletrack.PAVED_SURFACES | frozenset(
    {"sett", "brick", "bricks", "metal", "tartan", "rubber", "cobblestone", "unhewn_cobblestone"}
)
SMOOTH_ENOUGH = frozenset({"excellent", "good"})
BAD_SMOOTHNESS = frozenset({"bad", "very_bad", "horrible", "very_horrible", "impassable"})
TRACKTYPE_FIRM = frozenset({"grade1", "grade2", "grade3"})
POOR_VISIBILITY = frozenset({"intermediate", "bad", "poor", "horrible", "very_bad", "no"})
DEMANDING_SAC_SCALE = frozenset(
    {
        "mountain_hiking",
        "demanding_mountain_hiking",
        "alpine_hiking",
        "demanding_alpine_hiking",
        "difficult_alpine_hiking",
    }
)
# bicycle values the vendored upstream transform opens a way on
UPSTREAM_BICYCLE_OPEN = frozenset(
    {
        "yes",
        "designated",
        "use_sidepath",
        "permissive",
        "destination",
        "dismount",
        "lane",
        "track",
        "shared",
        "shared_lane",
        "sidepath",
        "share_busway",
        "allowed",
        "private",
        "official",
        "permit",
        "residents",
    }
)
UPSTREAM_ACCESS_CLOSED = frozenset(
    {"no", "agricultural", "discouraged", "forestry", "emergency", "psv"}
)
HIKING_ROUTES = frozenset({"hiking", "foot", "walking"})
KEEPING_NETWORKS = frozenset({"ncn", "icn"})
DISMOUNT_KEEP_M = 150.0

_WIDTH = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m|ft|')?\s*$")


@dataclass(frozen=True)
class WayRoutes:
    """What the route relations of an extract say about one way."""

    hiking: bool = False
    bicycle_networks: frozenset[str] = field(default_factory=frozenset)

    @property
    def bicycle_route(self) -> bool:
        return bool(self.bicycle_networks)

    @property
    def keeping_route(self) -> bool:
        return bool(self.bicycle_networks & KEEPING_NETWORKS)


NO_ROUTES = WayRoutes()


def width_m(tags: dict[str, str]) -> float | None:
    match = _WIDTH.match(tags.get("width") or "")
    if not match:
        return None
    value = float(match.group(1))
    return value * 0.3048 if match.group(2) in ("ft", "'") else value


def is_hard_surface(tags: dict[str, str]) -> bool:
    surface = tags.get("surface") or ""
    return surface in HARD_SURFACES or surface.startswith(
        ("concrete:", "paving_stones:", "asphalt:")
    )


def is_natural_surface(tags: dict[str, str]) -> bool:
    return (tags.get("surface") or "") in NATURAL_SURFACES


def _scale(tags: dict[str, str]) -> int | None:
    known = [
        g for key in singletrack.SCALE_KEYS if (g := singletrack.grade(tags.get(key))) is not None
    ]
    return max(known) if known else None


def upstream_open(tags: dict[str, str]) -> bool:
    """Whether Valhalla's transform leaves a candidate way open to bicycles,
    from the tags alone: highway default (path open; footway, pedestrian,
    bridleway closed), the bicycle table, sac_scale without a bicycle tag
    (hiking grants, any other value closes), then access."""
    highway = tags.get("highway")
    if highway not in CANDIDATE_HIGHWAY:
        return False
    bicycle = tags.get("bicycle")
    if tags.get("access") in UPSTREAM_ACCESS_CLOSED or tags.get("vehicle") == "no":
        return bicycle in UPSTREAM_BICYCLE_OPEN
    if bicycle is not None:
        return bicycle in UPSTREAM_BICYCLE_OPEN
    sac_scale = tags.get("sac_scale")
    if sac_scale is not None:
        return sac_scale == "hiking"
    return highway == "path"


def _kept_by_class(tags: dict[str, str]) -> bool:
    """A sidewalk, crossing or sidepath: never touched."""
    return facility._sidewalk_or_crossing(tags) or bool(
        {tags.get(key) for key in facility.CROSSING_KEYS} & {"sidewalk", "crossing"}
    )


def _hard_or_loose(tags: dict[str, str]) -> bool:
    return is_hard_surface(tags) or (tags.get("surface") or "") in LOOSE_EXEMPT_SURFACES


def has_exemption(tags: dict[str, str], routes: WayRoutes) -> bool:
    if _hard_or_loose(tags) or routes.keeping_route:
        return True
    if tags.get("smoothness") in SMOOTH_ENOUGH or tags.get("tracktype") in TRACKTYPE_FIRM:
        return True
    width = width_m(tags)
    if width is not None and width >= 2.0:
        return True
    return _scale(tags) == 0


def is_mtb_class(tags: dict[str, str], routes: WayRoutes = NO_ROUTES) -> bool:
    """The mountain-bike class; rated singletrack is singletrack's own."""
    if tags.get("highway") not in CANDIDATE_HIGHWAY:
        return False
    if _kept_by_class(tags) or singletrack.is_singletrack(tags):
        return False
    if _hard_or_loose(tags) or routes.keeping_route:
        return False
    if tags.get("tracktype") in TRACKTYPE_FIRM:
        return False
    width = width_m(tags)
    if width is not None and width >= 2.0:
        return False
    # mtb:scale of 1 or more is not asked here: such a way that is not paved or
    # gravel is rated singletrack, which returned above and is closed everywhere.
    scale = _scale(tags)
    if tags.get("smoothness") in BAD_SMOOTHNESS or tags.get("sac_scale") in DEMANDING_SAC_SCALE:
        return True
    if tags.get("smoothness") in SMOOTH_ENOUGH or scale == 0:
        return False
    return is_natural_surface(tags)


def verdict(
    tags: dict[str, str], routes: WayRoutes = NO_ROUTES, in_park: bool = False
) -> str | None:
    """The rm:no_bicycle reason these rules give a way, or None. First match
    wins. singletrack, cbd_sidewalk, zoo and dismount are decided elsewhere and
    take precedence."""
    if not upstream_open(tags) or _kept_by_class(tags):
        return None
    bicycle = tags.get("bicycle")
    if bicycle is not None and bicycle not in PRIVATE_BICYCLE:
        return MTB if is_mtb_class(tags, routes) else None
    if tags.get("access") in PRIVATE_ACCESS or bicycle in PRIVATE_BICYCLE:
        return PRIVATE
    if routes.keeping_route:
        return None
    hard = is_hard_surface(tags)
    if tags.get("sac_scale") is not None and not hard:
        return SAC_SCALE
    if tags.get("informal") == "yes":
        return INFORMAL
    if tags.get("highway") != "path":
        return None
    if tags.get("foot") in ("designated", "official") and not hard:
        return FOOT_DESIGNATED
    if tags.get("trail_visibility") in POOR_VISIBILITY and not hard:
        return TRAIL_VISIBILITY
    if routes.hiking and not routes.bicycle_route and not hard:
        return HIKING_ROUTE
    if has_exemption(tags, routes):
        return None
    if is_natural_surface(tags):
        return NATURAL_SURFACE
    if (
        in_park
        and not routes.bicycle_route
        and tags.get("surface") is None
        and tags.get("smoothness") is None
        and tags.get("tracktype") is None
        and width_m(tags) is None
    ):
        return PARK_PATH
    return None


# -- bicycle=dismount connectors ----------------------------------------------


def is_dismount(tags: dict[str, str]) -> bool:
    return tags.get("highway") in CANDIDATE_HIGHWAY and tags.get("bicycle") == "dismount"


def dismount_chains(
    ways: Iterable[tuple[int, dict[str, str], Sequence[int], float]],
) -> dict[int, float]:
    """Length in metres of the connected run of dismount ways each way is part
    of (ways sharing a node are one connector). `ways` is (id, tags, node ids,
    length in metres)."""
    parent: dict[int, int] = {}

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    members = []
    for osm_id, tags, node_ids, length in ways:
        if is_dismount(tags):
            parent[osm_id] = osm_id
            members.append((osm_id, node_ids, length))
    by_node: dict[int, int] = {}
    for osm_id, node_ids, _length in members:
        for node in node_ids:
            other = by_node.setdefault(node, osm_id)
            if other != osm_id:
                parent[find(osm_id)] = find(other)
    totals: dict[int, float] = defaultdict(float)
    for osm_id, _nodes, length in members:
        totals[find(osm_id)] += length
    return {osm_id: totals[find(osm_id)] for osm_id, _nodes, _length in members}


def dismount_reasons(chains: dict[int, float]) -> tuple[set[int], set[int]]:
    """(kept and flagged walk-your-bike, closed): under DISMOUNT_KEEP_M stays."""
    kept = {osm_id for osm_id, metres in chains.items() if metres < DISMOUNT_KEEP_M}
    return kept, set(chains) - kept
