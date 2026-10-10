"""Which paths and trails are long ones: OSM route relations and named runs.

The zoomed-out stress tiles keep only the long trails (OWNER-DECISIONS 375;
`pipeline.schema.long_trails_predicate` says what is kept). This module
writes what that rule reads, beside the rest of a segment's row:

- `trail_name`, the way's OSM name (or its route's, `way_name`);
- `trail_route`, the level of the OSM route relations a way is a member of,
  read from the source extract (`read_routes`);
- `trail_run_m`, the length of the way's named run, derived in the staging
  schema once the rows are written (`derive_trail_runs`); and
- `trail_bridge`, how a short bridge inside a trail is judged
  (`judge_bridges`); and
- `calm_run_m`, the length of the connected network or named run a path is part
  of, or of the calm run of a road at LTS 1 or 2 (`pipeline.calm_roads`), which the
  z12-13 "where to ride" layer keeps it for (OWNER-DECISIONS 391, 402a;
  `derive_calm_runs`); and
- `roadside`, whether a drawn trail lies beside a road, so that one with no surface
  mapped keeps the paved path's look (OWNER-DECISIONS 403; `derive_roadside`).

The relations are OSM's, cited as the rest of the map's data is.
"""

from __future__ import annotations

from typing import NamedTuple

import osmium

from routemaker.singletrack import SCALE_KEYS, grade, is_paved
from routemaker.trailaccess import KEEPING_NETWORKS

from . import calm_roads
from .schema import (
    CALM_PATH_GAP_M,
    CALM_ROAD_MAX_TIER,
    CALM_RUN_COLUMN,
    PAVED_ROUTE_MIN,
    ROADSIDE_COLUMN,
    ROADSIDE_FRACTION,
    ROADSIDE_M,
    ROADSIDE_SAMPLE_M,
    ROADSIDE_TRAIL_FACILITY,
    ROUTE_ANY_BICYCLE,
    ROUTE_LONG_BICYCLE,
    ROUTE_LONG_WALK,
    TRAIL_BRIDGE_COLUMN,
    TRAIL_BRIDGE_MAX_M,
    TRAIL_FACILITY,
    TRAIL_NAME_COLUMN,
    TRAIL_ROUTE_COLUMN,
    TRAIL_RUN_COLUMN,
    TRAIL_RUN_GAP_M,
    Z10_UNPAVED_ROUTE_MIN,
    Z11_UNPAVED_ROUTE_MIN,
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

# How close, in degrees, a way must come to a bridge's end to be what the bridge
# meets: about 2 m (1.7 m of longitude and 2.2 m of latitude at 39 N). OSM joins
# the two at a shared node, so this only absorbs rounding.
BRIDGE_END_TOLERANCE_DEG = 0.00002

# The route level a bridge's end needs to keep its trail by route alone, by the
# surface the bridge is judged on; a run is then not needed of it.
_UNPAVED_ROUTE_MIN = min(Z10_UNPAVED_ROUTE_MIN, Z11_UNPAVED_ROUTE_MIN)


def route_level(route: str | None, network: str | None) -> int:
    """The level a route relation gives its member ways: 0 none, 1 a bicycle
    route at a local or no network (which qualifies nothing, OWNER-DECISIONS 377),
    2 a long walking route (a paved way only, 378), 3 a bicycle route at a long
    network. A mountain-bike route gives nothing, and its ways never qualify (378).
    A `route` of several values (`bicycle;hiking`) is the highest of them."""
    routes = route_routes(route)
    if "mtb" in routes:
        return 0
    level = 0
    for each in routes:
        if each == "bicycle":
            level = max(
                level,
                ROUTE_LONG_BICYCLE if network in LONG_BICYCLE_NETWORKS else ROUTE_ANY_BICYCLE,
            )
        elif each in WALKING_ROUTES and network in LONG_WALKING_NETWORKS:
            level = max(level, ROUTE_LONG_WALK)
    return level


def route_routes(route: str | None) -> frozenset[str]:
    """The values of a relation's `route` tag, which OSM separates by `;`
    (`hiking;mtb` is a mountain-bike route as well as a walking one)."""
    return frozenset(part.strip() for part in (route or "").split(";") if part.strip())


def is_mountain_bike_way(tags: dict[str, str]) -> bool:
    """Whether the way's own tags mark it a mountain-bike trail (OWNER-DECISIONS
    378: "Patapsco Traverse appears to be a mountain bike trail. Make sure to not
    include those."): rated one or more on either MTB difficulty scale, or
    `mtb=designated`, or any `mtb:type`. A paved way is not one whatever it
    carries, as `routemaker.singletrack` reads it (Upper Rock Creek, Northwest
    Branch and the Cross County Trail carry an mtb:scale on asphalt), and a
    zero on a scale is a trail anyone rides (the C&O towpath)."""
    if is_paved(tags):
        return False
    if any((g := grade(tags.get(key))) is not None and g >= 1 for key in SCALE_KEYS):
        return True
    return tags.get("mtb") == "designated" or bool(tags.get("mtb:type"))


# A way on a national or international bicycle route is never a mountain-bike trail to the
# map, whatever an mtb relation or tag also says of it: the owner, 2026-10-09, on the C&O
# towpath (USBR 50) missing from z13 and below east of Seneca Creek while it drew at z14,
# "On the localhost version, there seems to be breaks in the C&O canal towpath. However,
# this isn't reflected in OSM." The way he tapped (OSM 68565884) is an open, unpaved,
# traffic-free path; the only rule left that drops such a way from z10-13 and still draws
# it at z14 is this one. The networks are the no-bike-paths rules' own exemption
# (`routemaker.trailaccess.KEEPING_NETWORKS`, ncn and icn: the towpath, the Great
# Allegheny Passage), so a regional route (the Cross County Trail's rough sections, rcn)
# and the Patapsco Traverse (a walking route, OWNER-DECISIONS 378) are judged as before.
NATIONAL_BICYCLE_NETWORKS = KEEPING_NETWORKS


def is_mountain_bike(in_mtb_route: bool, tags: dict[str, str], national_route: bool) -> bool:
    """Whether the map treats a way as a mountain-bike trail (never a long trail, never in
    the ride layer): in a route=mtb relation or tagged as one (`is_mountain_bike_way`),
    unless it is on a national or international bicycle route."""
    if national_route:
        return False
    return in_mtb_route or is_mountain_bike_way(tags)


def is_zoomed_out_trail(facility: str, is_trail_class: bool, car_free_when) -> bool:
    """Whether the zoomed-out map draws the way at all: the rows
    `pipeline.schema.trails_predicate` selects on a table with the facility and
    car-free columns. Only these are named for a run or judged as a bridge."""
    return (
        facility == TRAIL_FACILITY
        or (facility == ROADSIDE_TRAIL_FACILITY and is_trail_class)
        or bool(car_free_when)
    )


def is_calm_candidate(
    *,
    zoomed_out_trail: bool,
    mountain_bike: bool,
    mtb_only: bool,
    is_trail_class: bool,
    stress_tier: int,
    map_class: str,
) -> bool:
    """Whether the way can be in the z12-13 ride layer (OWNER-DECISIONS 391, 402a),
    and so is written with a `calm_run_m` of 0 for `derive_calm_runs` to set: a path
    or trail the zoomed-out map draws (`is_zoomed_out_trail`), or a road at LTS 1 or
    LTS 2 that is not a trail, of any class ("LTS2 counts"); never a mountain-bike
    trail (a way in a route=mtb relation, one tagged as such, or one the no-bike-paths
    rules call mountain-bike only), and nothing that is not a drawn road (a hidden,
    barred or alley way)."""
    if mountain_bike or mtb_only or map_class != "road":
        return False
    return zoomed_out_trail or (stress_tier <= CALM_ROAD_MAX_TIER and not is_trail_class)


class Routes(NamedTuple):
    """What the extract's route relations say of its ways."""

    # {way id: route level} (route_level), the highest of the relations it is in.
    levels: dict[int, int]
    # Ways in a route=mtb relation: mountain-bike trails, which never qualify.
    mountain_bike: set[int]
    # {way id: the name of the long route relation it is in}, the highest level's:
    # what a way with no name of its own is chained by (`way_name`). A local route's
    # name is not used, so a local route cannot keep a way through it (377).
    names: dict[int, str]
    # Ways in a bicycle route at a national or international network
    # (NATIONAL_BICYCLE_NETWORKS), which no mountain-bike marker takes off the map.
    national: frozenset[int] = frozenset()


class RouteMembers(osmium.SimpleHandler):
    """The highest route level of each way that is a member of a route relation,
    and the ways in a mountain-bike route relation."""

    def __init__(self) -> None:
        super().__init__()
        self.levels: dict[int, int] = {}
        self.mountain_bike: set[int] = set()
        self.names: dict[int, str] = {}
        self.national: set[int] = set()
        self._name_levels: dict[int, int] = {}

    def relation(self, r) -> None:  # noqa: N802 - osmium's callback name
        if r.tags.get("type") != "route":
            return
        if "mtb" in route_routes(r.tags.get("route")):
            self.mountain_bike.update(m.ref for m in r.members if m.type == "w")
            return
        level = route_level(r.tags.get("route"), r.tags.get("network"))
        if not level:
            return
        if (
            "bicycle" in route_routes(r.tags.get("route"))
            and r.tags.get("network") in NATIONAL_BICYCLE_NETWORKS
        ):
            self.national.update(m.ref for m in r.members if m.type == "w")
        # OWNER-DECISIONS 377, "Local trails only at higher zooms.": a local
        # route's name would let its unnamed ways join a named run.
        name = r.tags.get("name", "").strip() if level >= ROUTE_LONG_WALK else ""
        for member in r.members:
            if member.type != "w":
                continue
            if self.levels.get(member.ref, 0) < level:
                self.levels[member.ref] = level
            if name and self._name_levels.get(member.ref, 0) < level:
                self._name_levels[member.ref] = level
                self.names[member.ref] = name


def read_routes(path) -> Routes:
    """The route levels, mountain-bike ways and national-route ways of the extract's route
    relations."""
    handler = RouteMembers()
    handler.apply_file(str(path))
    return Routes(handler.levels, handler.mountain_bike, handler.names, frozenset(handler.national))


def is_bridge_way(tags: dict[str, str]) -> bool:
    """Whether the way is a bridge candidate (bridge=yes, boardwalk, viaduct...:
    anything but "no"); `judge_bridges` judges it by its length and its ends."""
    return tags.get("bridge", "no") not in ("", "no")


def way_name(tags: dict[str, str], route_name: str | None = None) -> str | None:
    """The way's OSM name, else the name of the long route relation it is in (a
    way that is part of "Gwynns Falls Trail" and says nothing itself is still one
    of its ways), or None when neither has one."""
    name = tags.get("name", "").strip() or (route_name or "").strip()
    return name or None


# What two ways must share to be one trail: the name, lower case, without a
# trailing parenthetical or bracket ("(white)", "(Extension)", "[north]") and
# without a trailing Extension, Extn, Connector or Connection, since OSM names an
# extension or a connector of a trail after it ("Rock Creek Trail Connector").
# Stored names are as OSM has them; this is applied only to chain a run. POSIX
# classes keep the backslashes out of it.
NAME_KEY = (
    "NULLIF(trim(regexp_replace(regexp_replace(regexp_replace(lower({name}), "
    "'[[:space:]]*[([].*$', ''), "
    "'[[:space:]]+(extension|extn|connector|connection)$', ''), "
    "'[[:space:]]+', ' ', 'g')), '')"
)


# The ways a run is made of: those the zoomed-out map would draw, the plain
# trails' rule on a table with the facility and car-free columns.
_DERIVE_RUNS = """
UPDATE {schema}.segment AS s
SET {run} = runs.run_m
FROM (
    SELECT id, round(sum(length_m) OVER (PARTITION BY name_key, chain))::integer AS run_m
    FROM (
        SELECT id,
               {key} AS name_key,
               ST_Length(geometry::geography) AS length_m,
               ST_ClusterDBSCAN(
                   ST_Transform(geometry, {srid}), eps := {gap}, minpoints := 1
               ) OVER (PARTITION BY {key}) AS chain
        FROM {schema}.segment
        WHERE {key} IS NOT NULL AND map_class = 'road' AND {trails}
    ) AS chained
) AS runs
WHERE s.id = runs.id
"""


# The calm runs (`derive_calm_runs`, OWNER-DECISIONS 391, 402a). A candidate is
# written with `calm_run_m` 0 (`is_calm_candidate`). A path or trail (the zoomed-out
# map's `trails` rule) gets the length of the connected network of such candidates
# (eps CALM_PATH_GAP_M), or of its named run (`trail_run_m`) if that is longer. A
# road gets the length of its calm run (`pipeline.calm_roads`: continuous LTS 1 and 2
# road, ended at every junction with a road at LTS 3 or above); a road with no name
# stays 0: it has no run. A path's run is at least 1 m, as a road's is
# (`calm_roads.runs_of`): 0 is "not derived" to VALIDATE, and a lone named trail
# piece under half a metre rounds to 0. `trail_run_m` rounds the same way and is left
# as it is: nothing reads its 0 as "not derived" (its readers compare it with floors
# of hundreds of metres, and the tiles carry it as it is).
_DERIVE_CALM_PATHS = """
UPDATE {schema}.segment AS s
SET {calm} = GREATEST(1, runs.run_m, COALESCE(s.{run}, 0))
FROM (
    SELECT id, round(sum(length_m) OVER (PARTITION BY chain))::integer AS run_m
    FROM (
        SELECT id,
               ST_Length(geometry::geography) AS length_m,
               ST_ClusterDBSCAN(
                   ST_Transform(geometry, {srid}), eps := {gap}, minpoints := 1
               ) OVER () AS chain
        FROM {schema}.segment
        WHERE {calm} = 0 AND map_class = 'road' AND {trails}
    ) AS chained
) AS runs
WHERE s.id = runs.id
"""


# The trails beside a road (`derive_roadside`, OWNER-DECISIONS 403). The writer sets
# `roadside` true where a drawn trail's tags or facility say it is a sidepath, false
# where they say it is not or the way is not a drawn trail, and leaves it null for the
# geometry to decide: points ROADSIDE_SAMPLE_M apart along the trail (both ends
# included), each beside a road when one lies within ROADSIDE_M of it on the ground.
# The degrees only find the candidates through the geometry index (0.0005 degrees is
# 43 m of longitude and 56 m of latitude at 39 N, more than ROADSIDE_M).
_ROADSIDE_SEARCH_DEG = 0.0005
_DERIVE_ROADSIDE = """
UPDATE {schema}.segment AS t
SET {roadside} = near.beside
FROM (
    SELECT u.id, avg(CASE WHEN EXISTS (
               SELECT 1 FROM {schema}.segment AS r
               WHERE NOT r.is_trail_class AND r.map_class IN ('road', 'barred')
                 AND ST_DWithin(r.geometry, p.point, {search})
                 AND ST_DWithin(r.geometry::geography, p.point::geography, {within})
           ) THEN 1.0 ELSE 0.0 END) >= {fraction} AS beside
    FROM {schema}.segment AS u
    CROSS JOIN LATERAL (
        SELECT GREATEST(1, ceil(ST_Length(u.geometry::geography) / {step}))::integer AS n
    ) AS k
    CROSS JOIN LATERAL generate_series(0, k.n) AS i
    CROSS JOIN LATERAL (
        SELECT ST_LineInterpolatePoint(u.geometry, i::float8 / k.n) AS point
    ) AS p
    WHERE u.{roadside} IS NULL AND u.is_trail_class AND u.map_class = 'road'
    GROUP BY u.id
) AS near
WHERE t.id = near.id
"""


# The short bridges (`judge_bridges`). A candidate (trail_bridge 3) is a drawn
# trail way tagged bridge=*. Candidates whose ends meet are one chain (a bridge
# and its boardwalk, or a bridge OSM splits in two), judged as one: the chain is
# no longer than TRAIL_BRIDGE_MAX_M in all, and each of its outer ends (an end no
# other way of the chain meets) must meet a drawn trail way that is not a
# candidate: the same-named one first, then the one on the highest route, with
# the longest run, nearest. The chain is judged on its trail's surface (unpaved
# if any end is) and takes, way by way, the greater of its own route and run and
# the lower of its ends'. An end that keeps its trail by its route alone sets no
# bar on the run, so a bridge where a trail leaves its route is judged by the
# other end's run. A chain that is too long or misses a trail at an end is left
# to its own deck (0).
_JUDGE_BRIDGES = """
WITH c AS (
    SELECT id, geometry, {key_c} AS name_key, ST_Length(geometry::geography) AS length_m,
           ST_ClusterDBSCAN(
               ST_Collect(ST_StartPoint(geometry), ST_EndPoint(geometry)),
               eps := {tolerance}, minpoints := 1
           ) OVER () AS chain
    FROM {schema}.segment
    WHERE {bridge} = 3 AND map_class = 'road' AND {trails}
),
chains AS (
    SELECT chain FROM c GROUP BY chain HAVING sum(length_m) <= {cap}
),
ends AS (
    SELECT c.chain, c.name_key, p.point
    FROM c
    JOIN chains USING (chain)
    CROSS JOIN LATERAL (
        VALUES (ST_StartPoint(c.geometry)), (ST_EndPoint(c.geometry))
    ) AS p (point)
    WHERE NOT EXISTS (
        SELECT 1 FROM c AS o
        WHERE o.chain = c.chain AND o.id <> c.id
          AND ST_DWithin(o.geometry, p.point, {tolerance})
    )
),
met AS (
    SELECT e.chain, n.route, n.run, n.unpaved
    FROM ends AS e
    LEFT JOIN LATERAL (
        SELECT t.{route} AS route, COALESCE(t.{run}, 0) AS run,
               t.is_unpaved IS TRUE AS unpaved
        FROM {schema}.segment AS t
        WHERE t.{bridge} = 0 AND t.map_class = 'road' AND {trails}
          AND ST_DWithin(t.geometry, e.point, {tolerance})
        ORDER BY (e.name_key IS NOT NULL AND {key_t} = e.name_key) DESC,
                 t.{route} DESC, COALESCE(t.{run}, 0) DESC,
                 ST_Distance(t.geometry, e.point)
        LIMIT 1
    ) AS n ON true
),
surfaced AS (
    SELECT met.*, bool_or(met.unpaved) OVER (PARTITION BY met.chain) AS chain_unpaved
    FROM met
),
verdict AS (
    SELECT chain, chain_unpaved AS unpaved, min(route) AS route,
           min(run) FILTER (
               WHERE route < CASE WHEN chain_unpaved THEN {unpaved_route} ELSE {paved_route} END
           ) AS run
    FROM surfaced
    GROUP BY chain, chain_unpaved
    HAVING count(*) >= 2 AND count(route) = count(*)
)
UPDATE {schema}.segment AS b
SET {route} = GREATEST(b.{route}, v.route),
    {run} = GREATEST(b.{run}, v.run),
    {bridge} = CASE WHEN v.unpaved THEN 2 ELSE 1 END
FROM c
JOIN verdict AS v USING (chain)
WHERE b.id = c.id
"""


def runs_sql(schema: str) -> str:
    """The UPDATE that sets every named trail way's run (`derive_trail_runs`)."""
    validate_schema_name(schema)
    return _DERIVE_RUNS.format(
        schema=schema,
        run=TRAIL_RUN_COLUMN,
        key=NAME_KEY.format(name=TRAIL_NAME_COLUMN),
        srid=RUN_PROJECTION_SRID,
        gap=TRAIL_RUN_GAP_M,
        trails=trails_predicate(True, True),
    )


def calm_paths_sql(schema: str) -> str:
    """The UPDATE that sets the paths' calm runs (`derive_calm_runs`)."""
    validate_schema_name(schema)
    return _DERIVE_CALM_PATHS.format(
        schema=schema,
        calm=CALM_RUN_COLUMN,
        run=TRAIL_RUN_COLUMN,
        srid=RUN_PROJECTION_SRID,
        trails=trails_predicate(True, True),
        gap=CALM_PATH_GAP_M,
    )


def roadside_sql(schema: str) -> str:
    """The UPDATE that decides, by geometry, the drawn trails whose tags left
    `roadside` open (`derive_roadside`)."""
    validate_schema_name(schema)
    return _DERIVE_ROADSIDE.format(
        schema=schema,
        roadside=ROADSIDE_COLUMN,
        search=_ROADSIDE_SEARCH_DEG,
        within=ROADSIDE_M,
        fraction=ROADSIDE_FRACTION,
        step=ROADSIDE_SAMPLE_M,
    )


def bridges_sql(schema: str) -> str:
    """The UPDATE that judges the short bridges (`judge_bridges`)."""
    validate_schema_name(schema)
    return _JUDGE_BRIDGES.format(
        schema=schema,
        bridge=TRAIL_BRIDGE_COLUMN,
        route=TRAIL_ROUTE_COLUMN,
        run=TRAIL_RUN_COLUMN,
        trails=trails_predicate(True, True),
        key_c=NAME_KEY.format(name=TRAIL_NAME_COLUMN),
        key_t=NAME_KEY.format(name="t." + TRAIL_NAME_COLUMN),
        tolerance=BRIDGE_END_TOLERANCE_DEG,
        cap=TRAIL_BRIDGE_MAX_M,
        paved_route=PAVED_ROUTE_MIN,
        unpaved_route=_UNPAVED_ROUTE_MIN,
    )


def judge_bridges(schema: str) -> None:
    """Set `trail_bridge` on the staging schema's bridge candidates: 1 or 2 on
    the chains judged as their trail, 0 on the rest, so none is left at 3."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(bridges_sql(schema))
        cursor.execute(
            f"UPDATE {schema}.segment SET {TRAIL_BRIDGE_COLUMN} = 0 WHERE {TRAIL_BRIDGE_COLUMN} = 3"
        )


def derive_trail_runs(schema: str) -> int:
    """Set `trail_run_m` on every named trail way of the staging schema: the
    length of the run of same-named trail ways it chains into. Returns the
    number of ways set; then the short bridges between trail ways are judged
    (`judge_bridges`). Run after `write_segments`, which writes the names.

    The table was bulk-loaded moments before, so it is analyzed first: the
    bridge ends are found through the geometry index, and a plan made without
    statistics could scan the whole table for each of them."""
    from django.db import connection

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(f"ANALYZE {schema}.segment")
        cursor.execute(runs_sql(schema))
        set_runs = cursor.rowcount
    judge_bridges(schema)
    return set_runs


def derive_calm_runs(schema: str) -> tuple[int, int]:
    """Set `calm_run_m` on the staging schema's candidates (OWNER-DECISIONS 391, 402a):
    the paths' networks here, the roads' calm runs in `pipeline.calm_roads`. Run after
    `derive_trail_runs`, whose `trail_run_m` a path's run is at least. Returns the
    number of rows set: (the paths, the roads)."""
    from django.db import connection

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(calm_paths_sql(schema))
        set_paths = cursor.rowcount
    set_roads = calm_roads.derive(schema)
    with connection.cursor() as cursor:
        cursor.execute(f"ANALYZE {schema}.segment")
    return set_paths, set_roads


def derive_roadside(schema: str) -> int:
    """Decide `roadside` on the staging schema's drawn trails that their tags left open
    (OWNER-DECISIONS 403; `roadside_sql`), and set it false on any row still null.
    Returns the number of rows beside a road."""
    from django.db import connection

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(roadside_sql(schema))
        cursor.execute(
            f"UPDATE {schema}.segment SET {ROADSIDE_COLUMN} = false WHERE {ROADSIDE_COLUMN} IS NULL"
        )
        cursor.execute(f"SELECT count(*) FROM {schema}.segment WHERE {ROADSIDE_COLUMN}")
        (beside,) = cursor.fetchone()
    return beside


class LongTrailSummary(NamedTuple):
    """What VALIDATE reads of the long-trail columns before a promotion."""

    # Rows on a long walking or long bicycle route (trail_route >= 2).
    on_long_route: int
    # Rows in a named run of at least `run_floor_m`.
    in_long_run: int
    # Bridge candidates left unjudged (trail_bridge 3): always 0 after the derive.
    unjudged_bridges: int
    # {sentinel way id: (its highest route level, its longest run)}; a way the
    # table does not hold is absent.
    sentinels: dict[int, tuple[int, int]]


def long_trail_summary(schema: str, sentinel_ways, run_floor_m: int) -> LongTrailSummary:
    """Count the staging schema's long-trail rows and read the sentinel ways."""
    from django.db import connection

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FILTER (WHERE {TRAIL_ROUTE_COLUMN} >= %s), "
            f"count(*) FILTER (WHERE {TRAIL_RUN_COLUMN} >= %s), "
            f"count(*) FILTER (WHERE {TRAIL_BRIDGE_COLUMN} = 3) FROM {schema}.segment",
            [PAVED_ROUTE_MIN, run_floor_m],
        )
        on_route, in_run, unjudged = cursor.fetchone()
        cursor.execute(
            f"SELECT osm_way_id, max({TRAIL_ROUTE_COLUMN}), COALESCE(max({TRAIL_RUN_COLUMN}), 0) "
            f"FROM {schema}.segment WHERE osm_way_id = ANY(%s) GROUP BY osm_way_id",
            [list(sentinel_ways)],
        )
        sentinels = {way: (route, run) for way, route, run in cursor.fetchall()}
    return LongTrailSummary(on_route, in_run, unjudged, sentinels)


class CalmRunSummary(NamedTuple):
    """What VALIDATE reads of the calm-run column before a promotion."""

    # Path rows (is_trail_class) in a run of at least the ride layer's path bar.
    path_rows: int
    # Street rows (not is_trail_class) in a run of at least the street bar.
    street_rows: int
    # Named candidates left at 0: always 0 after the derive, so a nonzero count
    # is a derive that did not run to the end.
    unset_named: int
    # {sentinel way id: its longest calm run}; a way the table does not hold is absent.
    sentinels: dict[int, int]


def calm_run_summary(
    schema: str, sentinel_ways, path_floor_m: int, street_floor_m: int
) -> CalmRunSummary:
    """Count the staging schema's ride-layer rows and read the sentinel ways."""
    from django.db import connection

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FILTER (WHERE is_trail_class AND {CALM_RUN_COLUMN} >= %s), "
            f"count(*) FILTER (WHERE NOT is_trail_class AND {CALM_RUN_COLUMN} >= %s), "
            f"count(*) FILTER (WHERE {CALM_RUN_COLUMN} = 0 AND "
            f"{NAME_KEY.format(name=TRAIL_NAME_COLUMN)} IS NOT NULL) "
            f"FROM {schema}.segment",
            [path_floor_m, street_floor_m],
        )
        paths, streets, unset = cursor.fetchone()
        cursor.execute(
            f"SELECT osm_way_id, COALESCE(max({CALM_RUN_COLUMN}), 0) FROM {schema}.segment "
            "WHERE osm_way_id = ANY(%s) GROUP BY osm_way_id",
            [list(sentinel_ways)],
        )
        sentinels = dict(cursor.fetchall())
    return CalmRunSummary(paths, streets, unset, sentinels)
