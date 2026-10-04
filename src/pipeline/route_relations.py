"""Which ways belong to which route relations, read from the source extract.

The NO-BIKE-PATHS rules (`routemaker.trailaccess`) need two facts the way's own
tags do not carry: a path that is a member of hiking or foot route relations and
of no bicycle route relation is a hiking path (OWNER-DECISIONS 278), and a way in
a national or international bicycle route (`network=ncn` or `icn`) keeps its
natural surface (the C&O Canal towpath, the Great Allegheny Passage). The
Cross County Trail is a regional route (`rcn`) that holds its rough sections,
so a regional route keeps nothing.

One pass over the relations of the extract, with no locations to resolve. A
relation of `route=bicycle` or `route=mtb` counts as a bicycle route; its
`network` is kept, `""` where it names none. A relation of `route=hiking`,
`foot` or `walking` is a hiking route; `route=bicycle;hiking` is both.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import osmium

from routemaker.trailaccess import HIKING_ROUTES, WayRoutes

BICYCLE_ROUTES = frozenset({"bicycle", "mtb"})


def route_kinds(tags) -> tuple[bool, str | None]:
    """(is a hiking route, the bicycle network or None where it is no bicycle route)."""
    if tags.get("type") != "route":
        return False, None
    kinds = {part.strip() for part in (tags.get("route") or "").split(";")}
    hiking = bool(kinds & HIKING_ROUTES)
    bicycle = tags.get("network", "") if kinds & BICYCLE_ROUTES else None
    return hiking, bicycle


class _Relations(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.hiking: set[int] = set()
        self.bicycle: dict[int, set[str]] = defaultdict(set)

    def relation(self, r) -> None:  # noqa: N802 - osmium's callback name
        hiking, bicycle = route_kinds(r.tags)
        if not hiking and bicycle is None:
            return
        for member in r.members:
            if member.type != "w":
                continue
            if hiking:
                self.hiking.add(member.ref)
            if bicycle is not None:
                self.bicycle[member.ref].add(bicycle)


def read_routes(pbf: str | Path) -> dict[int, WayRoutes]:
    """Every way that is in a hiking or bicycle route relation, by way id."""
    handler = _Relations()
    handler.apply_file(str(pbf))
    routes: dict[int, WayRoutes] = {}
    for way_id in handler.hiking | set(handler.bicycle):
        routes[way_id] = WayRoutes(
            hiking=way_id in handler.hiking,
            bicycle_networks=frozenset(handler.bicycle.get(way_id, ())),
        )
    return routes
