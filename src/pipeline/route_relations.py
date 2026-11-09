"""Which ways belong to which route relations, read from the source extract.

The NO-BIKE-PATHS rules (`routemaker.trailaccess`) need two facts the way's own
tags do not carry: a path that is a member of hiking or foot route relations and
of no bicycle route relation is a hiking path (OWNER-DECISIONS 278), and a way in
a national or international bicycle route (`network=ncn` or `icn`) keeps its
natural surface (the C&O Canal towpath, the Great Allegheny Passage). The
Cross County Trail is a regional route (`rcn`) that holds its rough sections,
so a regional route keeps nothing.

One pass over the relations of the extract, with no locations to resolve. A
relation of `route=bicycle` counts as a bicycle route; its `network` is kept,
`""` where it names none. A relation of `route=hiking`, `foot` or `walking` is a
hiking route; `route=bicycle;hiking` is both.

A `route=mtb` relation is no bicycle route here; a `route=bicycle;mtb` one still
is, by its `bicycle` half (a national route that is also an MTB route stays
national, as `pipeline.trail_routes` reads it). Being on a mountain-bike loop says
the trail is a mountain biker's, not that it is open to the riders the standard
graphs serve: counting it as a bicycle route lifted the park-path and hiking-route
closures from unrated dirt loops (Schaeffer Farms, Rosaryville, Cabin John), so a
commuter could be sent onto them (hunt A2, 2026-11-08). Membership is kept as its
own fact (`WayRoutes.mtb`) instead: where those two rules, or the natural-surface rule
(terrain hunt 2, T1; the owner, 2026-11-08: "these are very easy trails that nobody bothers
to rate"), would close the way,
`trailaccess.verdict` puts it in the mountain-bike class, closed on the standard
graphs, open on the off-road and Mountain Bike graphs and drawn on the
mountain-bike layer, as rated singletrack on such a loop stays drawn. The hiking
half of a `hiking;mtb` relation still counts.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import osmium

from routemaker.trailaccess import HIKING_ROUTES, WayRoutes

BICYCLE_ROUTES = frozenset({"bicycle"})
MTB_ROUTES = frozenset({"mtb"})


def route_kinds(tags) -> tuple[bool, str | None]:
    """(is a hiking route, the bicycle network or None where it is no bicycle route)."""
    if tags.get("type") != "route":
        return False, None
    kinds = {part.strip() for part in (tags.get("route") or "").split(";")}
    hiking = bool(kinds & HIKING_ROUTES)
    bicycle = tags.get("network", "") if kinds & BICYCLE_ROUTES else None
    return hiking, bicycle


def is_mtb_route(tags) -> bool:
    """Whether a relation is a mountain-bike route (`route=mtb`, or `mtb` in a list)."""
    if tags.get("type") != "route":
        return False
    return bool({part.strip() for part in (tags.get("route") or "").split(";")} & MTB_ROUTES)


class _Relations(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.hiking: set[int] = set()
        self.bicycle: dict[int, set[str]] = defaultdict(set)
        self.mtb: set[int] = set()

    def relation(self, r) -> None:  # noqa: N802 - osmium's callback name
        hiking, bicycle = route_kinds(r.tags)
        mtb = is_mtb_route(r.tags)
        if not hiking and bicycle is None and not mtb:
            return
        for member in r.members:
            if member.type != "w":
                continue
            if hiking:
                self.hiking.add(member.ref)
            if bicycle is not None:
                self.bicycle[member.ref].add(bicycle)
            if mtb:
                self.mtb.add(member.ref)


def read_routes(pbf: str | Path) -> dict[int, WayRoutes]:
    """Every way that is in a hiking, bicycle or mountain-bike route relation, by way id."""
    handler = _Relations()
    handler.apply_file(str(pbf))
    routes: dict[int, WayRoutes] = {}
    for way_id in handler.hiking | set(handler.bicycle) | handler.mtb:
        routes[way_id] = WayRoutes(
            hiking=way_id in handler.hiking,
            bicycle_networks=frozenset(handler.bicycle.get(way_id, ())),
            mtb=way_id in handler.mtb,
        )
    return routes
