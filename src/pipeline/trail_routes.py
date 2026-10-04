"""Which paths and trails are long ones: OSM route relations and named runs.

The zoomed-out stress tiles keep only the long trails (OWNER-DECISIONS 375;
`pipeline.schema.long_trails_predicate` says what is kept). This module
writes the two facts that rule reads, beside the rest of a segment's row:

- `route_level`, from the OSM route relations a way is a member of, read from
  the source extract (`read_routes`); and
- the length of the way's named run, derived in the staging schema once the
  rows are written (`derive_trail_runs`).

The relations are OSM's, cited as the rest of the map's data is.
"""

from __future__ import annotations

import osmium

from .schema import (
    ROUTE_ANY_BICYCLE,
    ROUTE_LONG_BICYCLE,
    ROUTE_LONG_WALK,
    TRAIL_NAME_COLUMN,
    TRAIL_RUN_COLUMN,
    TRAIL_RUN_GAP_M,
    trails_predicate,
    validate_schema_name,
)

# The networks that make a bicycle route a long one: international, national,
# regional. A local route (lcn) and one with no network are routes, not long ones.
LONG_BICYCLE_NETWORKS = frozenset({"icn", "ncn", "rcn"})

# Walking routes that are long ones: the national scenic trails (US:NST is the
# Potomac Heritage), and national and regional walking networks. The local and
# unnetworked ones are the park trails the owner called a mess, so they do not count.
LONG_WALKING_NETWORKS = frozenset({"US:NST", "iwn", "nwn", "rwn"})
WALKING_ROUTES = frozenset({"hiking", "foot"})

# UTM zone 18N, in metres: the region lies between 78 W and 72 W, and the run
# gap is a distance on the ground.
RUN_PROJECTION_SRID = 32618


def route_level(route: str | None, network: str | None) -> int:
    """The level a route relation gives its member ways: 0 none, 1 a bicycle
    route at a local or no network, 2 a long walking route, 3 a bicycle route at
    a long network. A mountain-bike route is the park's own trail, and gives
    nothing."""
    if route == "bicycle":
        return ROUTE_LONG_BICYCLE if network in LONG_BICYCLE_NETWORKS else ROUTE_ANY_BICYCLE
    if route in WALKING_ROUTES and network in LONG_WALKING_NETWORKS:
        return ROUTE_LONG_WALK
    return 0


class RouteMembers(osmium.SimpleHandler):
    """The highest route level of each way that is a member of a route relation."""

    def __init__(self) -> None:
        super().__init__()
        self.levels: dict[int, int] = {}

    def relation(self, r) -> None:  # noqa: N802 - osmium's callback name
        if r.tags.get("type") != "route":
            return
        level = route_level(r.tags.get("route"), r.tags.get("network"))
        if not level:
            return
        for member in r.members:
            if member.type == "w" and self.levels.get(member.ref, 0) < level:
                self.levels[member.ref] = level


def read_routes(path) -> dict[int, int]:
    """{way id: route level} for every way in a route relation of the extract."""
    handler = RouteMembers()
    handler.apply_file(str(path))
    return handler.levels


def way_name(tags: dict[str, str]) -> str | None:
    """The way's OSM name, or None when it has none worth chaining by."""
    name = tags.get("name", "").strip()
    return name or None


# The ways a run is made of: those the zoomed-out map would draw, the plain
# trails' rule on a table with the facility and car-free columns.
_DERIVE_RUNS = """
UPDATE {schema}.segment AS s
SET {run} = runs.run_m
FROM (
    SELECT id, round(sum(length_m) OVER (PARTITION BY name_key, chain))::integer AS run_m
    FROM (
        SELECT id,
               lower({name}) AS name_key,
               ST_Length(geometry::geography) AS length_m,
               ST_ClusterDBSCAN(
                   ST_Transform(geometry, {srid}), eps := {gap}, minpoints := 1
               ) OVER (PARTITION BY lower({name})) AS chain
        FROM {schema}.segment
        WHERE {name} IS NOT NULL AND map_class = 'road' AND {trails}
    ) AS chained
) AS runs
WHERE s.id = runs.id
"""


def derive_trail_runs(schema: str) -> int:
    """Set `trail_run_m` on every named trail way of the staging schema: the
    length of the run of same-named trail ways it chains into. Returns the
    number of ways set. Run after `write_segments`, which writes the names."""
    from django.db import connection

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(
            _DERIVE_RUNS.format(
                schema=schema,
                run=TRAIL_RUN_COLUMN,
                name=TRAIL_NAME_COLUMN,
                srid=RUN_PROJECTION_SRID,
                gap=TRAIL_RUN_GAP_M,
                trails=trails_predicate(True, True),
            )
        )
        return cursor.rowcount
