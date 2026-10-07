"""DDL for the tables the weekly rebuild owns.

These tables are rebuilt from scratch each week into a staging schema and
renamed into place, so their DDL lives here rather than in a Django migration.
A migration that owned them would fight the swap, and `migrate` deliberately
creates none of them: test and CI databases call `create_segment_schema`.

Nothing outside the swapped schema may hold a foreign key into it. Anchors -
comments, issues, closures, cue overrides, reviewer penalties - reference the
segment key as plain columns instead, because a cross-schema constraint would
make the rename impossible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import connection

from routemaker.classes import (
    TRAIL_CLASS_HIGHWAY,
    TrailKind,
)
from routemaker.stress import trail_rule

# Schema names are interpolated into DDL, which no parameter placeholder can
# carry. They come from settings, which itself reads them straight from
# ROUTEMAKER_LIVE_SCHEMA and ROUTEMAKER_STAGING_SCHEMA - so this guard is not a
# defense against some hypothetical future change, it is what stands between
# whatever an operator's environment happens to set and arbitrary SQL running
# against production today, in the one module that runs DDL there.
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

# PostgreSQL truncates an identifier at NAMEDATALEN-1 bytes, silently, and the
# swap derives the retired name by appending a suffix. So a live name of the
# full 63 bytes makes `<live>_old` truncate straight back to the live name, and
# the swap's `DROP SCHEMA IF EXISTS {retired} CASCADE` drops the very schema the
# rename on the next line is about to move - the served graph, deleted by the
# statement that exists to clear the way for it. Executed against a real server,
# not reasoned about.
#
# The bound is therefore on the name the suffix is appended to: at most 59, so
# that `<live>_old` is a name of its own. The one exception is a name that
# already carries the suffix, which is the derived retired name itself - nothing
# appends anything to that, so it only has to fit in an identifier. Without the
# exception a 59-character live name would pass every check the settings layer
# makes and then fail here, in the reconcile, on its own rollback target.
MAX_IDENTIFIER_LENGTH = 63
RETIRED_SUFFIX = "_old"
MAX_SCHEMA_NAME_LENGTH = MAX_IDENTIFIER_LENGTH - len(RETIRED_SUFFIX)

# Names that are not this deployment's to drop, whatever role a setting puts
# them in. `public` carries every migrated table - users, sessions, memberships,
# the audit log - and the other three are the system catalogs: `DROP SCHEMA
# information_schema CASCADE` takes out the view `schema_exists` itself reads,
# and `pg_catalog` is the database. They are listed here rather than only at the
# one call site that used to know about `public`, because the rebuild runs three
# different drops against three different settings-supplied names.
RESERVED_SCHEMAS = {
    "public": "the schema every migrated table lives in",
    "information_schema": "the catalog every schema query reads",
    "pg_catalog": "the system catalog",
    "pg_toast": "the system catalog's out-of-line storage",
}


def validate_schema_name(schema: str) -> str:
    if not _SCHEMA_NAME.match(schema):
        raise ValueError(f"refusing to interpolate {schema!r} into DDL")
    limit = MAX_IDENTIFIER_LENGTH if schema.endswith(RETIRED_SUFFIX) else MAX_SCHEMA_NAME_LENGTH
    if len(schema) > limit:
        raise ValueError(
            f"refusing to interpolate {schema!r} into DDL: it is {len(schema)} characters "
            f"and at most {limit} are allowed here. PostgreSQL truncates identifiers at "
            f"{MAX_IDENTIFIER_LENGTH} bytes, so a longer name makes {schema + RETIRED_SUFFIX!r} "
            "truncate back onto a schema that already exists - and the swap drops what it is "
            "about to rename."
        )
    return schema


def refuse_reserved_schema(schema: str) -> str:
    """Refuse a name that belongs to PostgreSQL or to every migration.

    Every destructive statement in the rebuild reaches this: the staging reset,
    the swap's drop of the retired schema, and the rollback's drop of a staging
    schema a failed rebuild left behind. Each of the three is handed a name that
    came from the environment by way of settings, and none of the three has any
    business dropping a catalog.
    """
    if schema in RESERVED_SCHEMAS:
        raise ValueError(
            f"refusing to drop {schema!r}: it is {RESERVED_SCHEMAS[schema]}, "
            "and no part of the rebuild may drop it."
        )
    return schema


def _text_list(values) -> str:
    """A SQL list of literals for the fixed strings below. They are this
    module's own constants, but they are pasted into DDL and into a query run
    with parameters, so a quote, a percent sign or a brace in one is refused
    rather than escaped."""
    items = sorted(values)
    for item in items:
        if any(c in item for c in "'%\\{}"):
            raise ValueError(f"not a plain rule string: {item!r}")
    return ", ".join(f"'{item}'" for item in items)


# What the stress tiles draw zoomed out (`core.stress_tiles.TRAILS`, below
# `core.stress_tiles.BUSY_ROADS_MIN_ZOOM`): the traffic-free paths and trails
# and nothing else. The owner, 2026-09-28: "It looks way too busy zoomed out
# though." and then "Zoomed out just show the trails." (OWNER-DECISIONS 64,
# 65); and 2026-09-29, "Show roadside trails (Recommended)" (66).
#
# - A path is what `routemaker.facility` calls one - the rule routing reads,
#   written by the rebuild to `segment.facility` - so a car-free road (Beach
#   Drive in DC) is on the zoomed-out map and a hiking trail barred to
#   bicycles is not.
# - A roadside trail is a way of its own - trail class, `is_trail_class` -
#   that `routemaker.facility` calls protected because it runs beside a road:
#   a sidewalk or path designated for bicycles, an `is_sidepath`, a cycleway
#   along a road whose own tags say its facility is mapped separately. The
#   Cross County Trail's sidewalk stretches, the Old Georgetown Road sidepath.
# - A protected lane tagged on the road way itself (`cycleway=track`, a lane
#   with posts) is not trail class, and waits for z13 with the roads.
#
# The segment table records no more than that: a cycle track in DC's roadway
# mapped as a way of its own (15th Street NW) is trail class too, and is drawn
# zoomed out like the trail beside a road.
#
# Written once because the partial index below is created with it and the tile
# query filters with it, and PostgreSQL uses a partial index only when it can
# prove the query's condition implies the index's - which it does for the same
# expression.
FACILITY_COLUMN = "facility"
TRAIL_FACILITY = "path"
ROADSIDE_TRAIL_FACILITY = "protected"

# The ride times a road closed to motor traffic only at set times is car-free
# in (`routemaker.ridetime`, written by the rebuild beside the facility). The
# owner, 2026-09-29: "One note: Car-free roads should be regarded the same as
# an off-road path on a map." (OWNER-DECISIONS 67) - a road closed for good is
# a path already (`facility`); one closed on weekends is a path when the map's
# ride time is Weekend ("Path on weekends only"), so the zoomed-out tiles
# carry it too and the map's style decides (`core.stress_tiles`).
CAR_FREE_COLUMN = "car_free_when"

# A live table promoted before the facility column has no such column, and the
# tiles derive the facility from the rule the rebuild recorded
# (`routemaker.classes.trail_kind`, in the text of `stress_rule`), by the
# routing lane's rule for trails: a trail a bicycle may ride is a path, a
# sidepath is the protected facility, and nothing else is anything. On a table
# from before the kinds were recorded only a cycleway is a path; a plain
# "path" there may be a hiking trail barred to bicycles.
TRAILS = sorted(TRAIL_CLASS_HIGHWAY - {"steps"})
OPEN_TRAIL_RULES = frozenset(trail_rule(h, TrailKind.OPEN) for h in TRAILS)
SIDEPATH_RULES = frozenset(trail_rule(h, TrailKind.SIDEPATH) for h in TRAILS)
PATH_RULES = OPEN_TRAIL_RULES | {trail_rule("cycleway")}

TRAIL_NETWORK_FACILITY = (
    "CASE WHEN stress_rule IN ("
    + _text_list(PATH_RULES)
    + ") THEN 'path' WHEN stress_rule IN ("
    + _text_list(SIDEPATH_RULES)
    + ") THEN 'protected' END"
)


def trails_predicate(has_facility: bool, has_car_free: bool = False) -> str:
    """The zoomed-out tiles' condition on a table with or without the facility
    column: its paths, and the protected ways that are trails of their own.
    Also the overview index's predicate on that table. Without the column the
    recorded rule says it: a sidepath for bicycles is a trail-class way beside
    a road (`routemaker.classes.trail_kind`). With `has_car_free`, the roads
    closed to cars at set times as well, which are paths in those ride times."""
    if has_facility:
        trails = (
            f"({FACILITY_COLUMN} = '{TRAIL_FACILITY}' OR "
            f"({FACILITY_COLUMN} = '{ROADSIDE_TRAIL_FACILITY}' AND is_trail_class))"
        )
    else:
        trails = "stress_rule IN (" + _text_list(PATH_RULES | SIDEPATH_RULES) + ")"
    if has_car_free:
        return f"({trails} OR cardinality({CAR_FREE_COLUMN}) > 0)"
    return trails


# THE LONG TRAILS (OWNER-DECISIONS 375, 377, 378, 380 and 381, 2026-10-04):
# "Also zoomed out, can we stick to mostly the longer trails, it's getting
# messy." At z10-11 Columbia's pathways and Patapsco Valley State Park's
# singletrack tangles merged into solid blobs, so the zoomed-out tiles keep a
# path or trail only when it is part of something long. Two facts about a way
# say so, both written by the rebuild (`pipeline.trail_routes`) and read from
# OSM:
#
# - `trail_route`: the way is a member of an OSM route relation. 0 none; 1 a
#   bicycle route at a local network, or none (recorded, but it qualifies
#   nothing: 377); 2 a long-distance walking route
#   (US:NST, or a national, regional or international walking network), which
#   keeps a paved way only (378); 3 a bicycle route at a regional, national or
#   international network. A mountain-bike trail (a way in a route=mtb relation
#   or tagged `mtb:scale` 1 or more, `mtb=designated` or `mtb:type`, unless
#   paved) has route 0 and no `trail_name`: it never qualifies (378).
# - `trail_run_m`: the length in metres of the way's named run, the ways of that
#   name (case-insensitive) that chain end to end across the region, within
#   TRAIL_RUN_GAP_M of one another so a road crossing does not break a trail in
#   two. A name is not a trail ("Red Trail" is every park's), so the run is not
#   the name's whole length; and a connected network is not a run either, since
#   Columbia's paths are one network. Null on a way with no name.
#
# OWNER-DECISIONS 377: "Local trails only at higher zooms. Basically, at birds
# eye view I want to see a bicycle version of the interstate routes." So a local
# bicycle route (lcn) does not keep a way at z10 or z11 by itself; a regional,
# national or international one does. And "Car free roads stay. The point at
# this zoom is to see what would be a great long distance trip.": a road closed
# to cars at set times is kept whatever its length (long_trails_predicate). A road
# closed to cars for good is not exempt: it is a path, judged like any trail by
# its route and its named run, and otherwise shown from z12 (OWNER-DECISIONS 381,
# "I think off is fine here. Nobody routes around the tiny roads.").
#
# A way is kept at a level when its route level is at least the bar for its
# surface, or its run is at least that level's length. An unpaved way must clear
# a higher bar, which is what drops the Patapsco tangles; the C&O towpath stays,
# on a national bicycle route. An unpaved way needs a long bicycle route at
# either zoom: a walking route is mostly a park's own trail, and the Patapsco
# Traverse, a regional walking route, "appears to be a mountain bike trail"
# (OWNER-DECISIONS 378). An unknown surface is read as paved, as the map reads it.
TRAIL_NAME_COLUMN = "trail_name"
TRAIL_ROUTE_COLUMN = "trail_route"
TRAIL_RUN_COLUMN = "trail_run_m"
# A short bridge inside a kept trail is kept with it, whatever its surface
# (OWNER-DECISIONS 375; the orchestrator's decision, not the owner's, after the
# Grist Mill Trail's two wooden bridges, `surface=wood`, left holes in a paved
# trail at z11). A drawn trail way tagged bridge=* (not "no") is a candidate.
# Candidates whose ends meet (a bridge and its boardwalk, or one bridge OSM
# splits in two) are one chain, judged as one: no longer than TRAIL_BRIDGE_MAX_M
# (330 ft) in all, with a trail way at each of its outer ends. Each way of the
# chain takes the greater of its own route level and run and the lower of its
# ends' (an end on a route that keeps its trail sets no bar on the run), and is
# judged on its trail's surface: `trail_bridge` 1 between paved trail ways, 2
# where an end is unpaved, 0 for every other way, and 3 only transiently, a
# candidate the rebuild has not yet judged (`pipeline.trail_routes.judge_bridges`).
# It keeps no bridge on its own (every end must be a trail way) and lowers none.
TRAIL_BRIDGE_COLUMN = "trail_bridge"
TRAIL_BRIDGE_MAX_M = 100
ROUTE_ANY_BICYCLE = 1
ROUTE_LONG_WALK = 2
ROUTE_LONG_BICYCLE = 3
# The route level a paved way needs, at every zoom (OWNER-DECISIONS 375, 377:
# a long walking route or a regional-or-larger bicycle route, not a local one).
PAVED_ROUTE_MIN = ROUTE_LONG_WALK
# Same-named ways within this many metres (1,300 ft) chain into one run.
TRAIL_RUN_GAP_M = 400
METRES_PER_MILE = 1609.344
# A run the length of these, by surface, keeps a way that is not on a route
# (OWNER-DECISIONS 375; 377 and 378 left them as they were). z11 and z10 differ:
# the further out, the longer. An unpaved way needs a long bicycle route at both
# (378: a walking route no longer counts for it). 380: the z11 paved bar came down
# from 3 to 2.5 mi ("Yes, bring it in.") so the Grist Mill Trail, whose 2.54 mi is
# all OSM maps of it, shows at z11; every other bar is as 375 set it.
Z11_PAVED_RUN_MI = 2.5
Z11_UNPAVED_RUN_MI = 5.0
Z11_UNPAVED_ROUTE_MIN = ROUTE_LONG_BICYCLE
Z10_PAVED_RUN_MI = 5.0
Z10_UNPAVED_RUN_MI = 8.0
Z10_UNPAVED_ROUTE_MIN = ROUTE_LONG_BICYCLE


@dataclass(frozen=True)
class LongTrails:
    """One zoom's bars for a path to count as a long trail."""

    paved_run_mi: float
    unpaved_run_mi: float
    unpaved_route_min: int


Z11_LONG_TRAILS = LongTrails(Z11_PAVED_RUN_MI, Z11_UNPAVED_RUN_MI, Z11_UNPAVED_ROUTE_MIN)
Z10_LONG_TRAILS = LongTrails(Z10_PAVED_RUN_MI, Z10_UNPAVED_RUN_MI, Z10_UNPAVED_ROUTE_MIN)


def long_trails_predicate(rule: LongTrails, car_free: bool = False) -> str:
    """The long trails' condition, on a table with the route, run and bridge
    columns (`core.stress_tiles.LONG_TRAIL_COLUMNS`): a way on a route of a high
    enough level for its surface, or in a named run long enough for it; with
    `car_free`, also any road closed to cars at set times (OWNER-DECISIONS 377),
    but not one closed for good, which is judged like any trail (381). Written
    for the tile query alone; the overview index is built on the plain trails'
    predicate, which this implies when ANDed."""
    paved_m = round(rule.paved_run_mi * METRES_PER_MILE)
    unpaved_m = round(rule.unpaved_run_mi * METRES_PER_MILE)
    run = f"COALESCE({TRAIL_RUN_COLUMN}, 0)"
    # A bridge is judged on its trail's surface, not its own deck's.
    unpaved = (
        f"(CASE WHEN {TRAIL_BRIDGE_COLUMN} = 1 THEN false WHEN {TRAIL_BRIDGE_COLUMN} = 2 "
        "THEN true ELSE is_unpaved IS TRUE END)"
    )
    long = (
        f"(CASE WHEN {unpaved} "
        f"THEN ({TRAIL_ROUTE_COLUMN} >= {rule.unpaved_route_min} OR {run} >= {unpaved_m}) "
        f"ELSE ({TRAIL_ROUTE_COLUMN} >= {PAVED_ROUTE_MIN} OR {run} >= {paved_m}) END)"
    )
    if car_free:
        return f"({long} OR cardinality({CAR_FREE_COLUMN}) > 0)"
    return long


# THE RIDE LAYER (OWNER-DECISIONS 391, 2026-10-05): "I'm more concerned with the
# places to ride than the places not to." At z12-13 the stress map is a "where to
# ride" view: no LTS 3, LTS 4 or Avoid road is drawn (they come in from z14, with
# the quiet streets), and what is drawn is
#
# - the long and connected traffic-free paths: a path whose connected network
#   (traffic-free paths within CALM_PATH_GAP_M of one another, so a road crossing
#   does not break a trail in two) or whose named run (`trail_run_m`) is at least
#   RIDE_PATH_RUN_MI; short isolated stubs and mountain-bike trails wait for z14;
# - the calm roads worth a long ride (402, 402a: "For calm streets, I'm thinking
#   more calm roads. Places someone would likely want to ride for a while. In the
#   cities that's just too dense." and "LTS2 counts. Suburban streets would rarely
#   qualify because they tend to have a lot of intersection stress rather than
#   roadway stress."): a continuous run of named LTS 1 and LTS 2 road, of any class
#   and across changes of name, that ends at every junction with a road at LTS 3 or
#   above, of at least RIDE_ROAD_RUN_MI (`pipeline.calm_roads`, which says how a run
#   goes through a junction); and
# - the roads closed to cars at set times, whatever their length (as 377 does).
#
# `calm_run_m` holds the length of that run or network, in metres, on the ways
# that are candidates (`pipeline.trail_routes.derive_calm_runs`): 0 on a candidate
# before it is derived, and null on every other way (a way that is not a path and
# not a road at LTS 1 or 2, or a mountain-bike trail). Written by the rebuild alone,
# so a live table from before it has no such column and draws today's z12-13.
#
# The thresholds are tunable and measured against the region before review
# (docs/OPERATIONS.md, "The ride layer (z12-13)").
CALM_RUN_COLUMN = "calm_run_m"
# Traffic-free paths within this many metres (100 ft) are one network: a road
# crossing, a trailhead's parking lot.
CALM_PATH_GAP_M = 30
# "short isolated stubs (under about 0.25 mi)".
RIDE_PATH_RUN_MI = 0.25
# The calmest tiers a calm road is made of: LTS 1 and LTS 2 ("LTS2 counts").
CALM_ROAD_MAX_TIER = 2
# A calm road is a long one at this run, in miles (3.2 km): the owner's proposed bar (402a,
# "2 mi (3.2 km) continuous as proposed, not yet confirmed"), the one setting to move. Measured
# on a copy of the live table's rows with names from the 2026-10-03 extract (docs/OPERATIONS.md,
# "The ride layer (z12-13)"): 1,642 mi in the region, nearly all of it rural (Montgomery County
# 38 mi, all in the Agricultural Reserve; DC and Baltimore none); at 1 mi, 4,831 mi (DC 33, MoCo
# 184, Baltimore 38).
RIDE_ROAD_RUN_MI = 2.0


# TRAILS BESIDE A ROAD (OWNER-DECISIONS 403, 2026-10-05): "Most trails near a road are paved.
# There are minor exceptions." 376 A draws a trail with no surface mapped as a dashed line of its
# own, with no path rails; a trail beside a road keeps the paved path's look instead, and only a
# trail away from roads (a park trail) is drawn surface-unknown. The exceptions are left to a
# surface tag in OSM or a surface override, not to the default. A drawn trail is beside a road
# (`roadside`) when its own tags say it is a sidepath or a sidewalk (`routemaker.facility.
# roadside_by_tags`: `footway`, `path` or `cycleway` = sidewalk, `is_sidepath=yes`, any
# `is_sidepath:of*`; `is_sidepath=no` says it is not, whatever the geometry), when its facility
# is already the protected one beside a road, or else when at least ROADSIDE_FRACTION of the
# points ROADSIDE_SAMPLE_M apart along it lie within ROADSIDE_M of a road (a way that is not a
# trail, drawn or barred: a motorway's own sidepath counts). Measured with the rule
# (docs/OPERATIONS.md, "Trails beside a road").
ROADSIDE_COLUMN = "roadside"
ROADSIDE_M = 25.0
ROADSIDE_FRACTION = 0.6
ROADSIDE_SAMPLE_M = 20.0


def ride_layer_predicate(has_facility: bool, has_car_free: bool = False) -> str:
    """The z12-13 ride layer's condition, on a table with the `calm_run_m`
    column (`core.stress_tiles.RIDE_LAYER`): a path or trail in a long enough
    connected network or named run, a road at LTS 1 or 2 in a long enough calm run,
    and with `has_car_free` any road closed to cars at set times. A way that is
    neither a path nor such a road has no run (null), so it is not in it."""
    path_m = round(RIDE_PATH_RUN_MI * METRES_PER_MILE)
    road_m = round(RIDE_ROAD_RUN_MI * METRES_PER_MILE)
    run = f"COALESCE({CALM_RUN_COLUMN}, 0)"
    paths = f"({trails_predicate(has_facility)} AND {run} >= {path_m})"
    roads = f"(stress_tier <= {CALM_ROAD_MAX_TIER} AND NOT is_trail_class AND {run} >= {road_m})"
    if has_car_free:
        return f"({paths} OR {roads} OR cardinality({CAR_FREE_COLUMN}) > 0)"
    return f"({paths} OR {roads})"


# The ride layer's own index (SEGMENT_DDL): a partial one holding only the rows a
# ride-layer tile can draw, which are well under a tenth of the table, so a z12
# tile's scan does not read every street in the box. The query's predicate implies
# it: each of its terms is a run at or above the shorter of the two bars, or a
# timed closure.
_RIDE_INDEX_MIN_M = round(min(RIDE_PATH_RUN_MI, RIDE_ROAD_RUN_MI) * METRES_PER_MILE)
RIDE_INDEX_PREDICATE = (
    f"COALESCE({CALM_RUN_COLUMN}, 0) >= {_RIDE_INDEX_MIN_M} OR cardinality({CAR_FREE_COLUMN}) > 0"
)


# What they draw at busy-road zoom (`core.stress_tiles.BUSY`, from
# `core.stress_tiles.BUSY_ROADS_MIN_ZOOM`): the paths and trails, and the roads
# at LTS 3 and above - Avoid (tier 5) and the expressways included. The owner,
# 2026-09-29: "Zoom less than 12, show just bike paths and the metro/MARC. 12
# and 13, show LTS 3+, 14+ show show the quiet streets." (OWNER-DECISIONS 73).
BUSY_MIN_TIER = 3


def busy_predicate(has_facility: bool, has_car_free: bool = False) -> str:
    """The busy-road tiles' condition: the trails' (with the timed closures when
    `has_car_free`), or a road at LTS 3 and above. Also the overview index's
    predicate: the trails' condition implies it, so the one index serves both
    zoomed-out levels."""
    return f"({trails_predicate(has_facility, has_car_free)} OR stress_tier >= {BUSY_MIN_TIER})"


# The trail seek's corridors (`core.trailseek.corridor_segments`, OWNER-DECISIONS
# 194): the paths and protected ways at LTS 1 or 2, and the roads closed to cars
# at some time. The seek index (`segment_seek_geom_idx`) is built on it and the
# seek's query carries it word for word, so that the planner proves the one
# implies the other (review r1: no other index's predicate covers an on-road
# cycle track, and the scan fell back to the whole geometry index).
SEEK_INDEX_PREDICATE = (
    f"({FACILITY_COLUMN} IN ('{TRAIL_FACILITY}', '{ROADSIDE_TRAIL_FACILITY}') "
    f"AND stress_tier <= 2) OR cardinality({CAR_FREE_COLUMN}) > 0"
)

# Two facts about a way the map draws from, written by the rebuild beside the
# facility (routemaker.facility.map_class and has_separate_bikeway). The
# owner, 2026-09-29: "there are several expressways shown as LTS4. just show
# them in white." and "there's several cases of a protected bike lane next to
# LTS3 or 4. In that case, don't show the road, perhaps hide it until zoom
# 15-16. The bike lane should show up as the main." (OWNER-DECISIONS 73), "Keep
# it faint if it parallels a protected bike path." (78), and "For some strange
# reason BWI has TLS 3 inside the terminal." (80).
MAP_CLASS_COLUMN = "map_class"
SEPARATE_BIKEWAY_COLUMN = "separate_bikeway"
MTB_ONLY_COLUMN = "mtb_only"
WALK_BIKE_COLUMN = "walk_bike"
ROUGH_COLUMN = "is_rough"
ROAD_TRAIT_COLUMNS = ("road_speed_mph", "road_lanes", "road_oneway")
# The tier the junction model reads where AADT smoothing lowered the link's
# (SEGMENT_DDL); absent on a table built before it.
UNSMOOTHED_TIER_COLUMN = "stress_unsmoothed_tier"

# The Mass Ride map's per-segment usable width, metres (riders a minute follow from it)
# (`routemaker.massflow`; OWNER-DECISIONS 325-327, 387). Carried in a stress tile
# as `rpm` where the live table has the column, and left out of one that has not
# (`core.stress_tiles.OPTIONAL_PROPERTIES`), so a table promoted before it draws the
# Mass Ride map as it was.
MASS_WIDTH_COLUMN = "mass_usable_width_m"

# On a table from before those columns, the public roads a bicycle may not
# use are what the classifier recorded as motor-only: a motorway or its ramp.
MOTOR_ONLY_RULE = "starts_with(stress_rule, 'motor-only classification (')"

# Whether SEGMENT_DDL declares the facility column. Set it True in the change
# that adds the column, so the overview index is created with the predicate
# the tile query then uses; a test fails while the two disagree. True since
# the PUBLIC-DIALS merge, which added the column.
SEGMENT_HAS_FACILITY = True


def overview_index_predicate(has_facility: bool) -> str:
    """The overview index's predicate on a table with or without the facility
    column: the busy-road one, which the trails' implies, so both zoomed-out
    levels read through it. SEGMENT_DDL declares `car_free_when` with the
    facility, so the one flag says both."""
    return busy_predicate(has_facility, has_car_free=has_facility)


OVERVIEW_INDEX_PREDICATE = overview_index_predicate(SEGMENT_HAS_FACILITY)


SEGMENT_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE {schema}.segment (
    id              bigserial PRIMARY KEY,
    osm_way_id      bigint      NOT NULL,
    ordinal         integer     NOT NULL,
    geometry        geometry(LineString, 4326) NOT NULL,
    stress_tier     smallint    NOT NULL CHECK (stress_tier BETWEEN 1 AND 5),
    stress_rule     text        NOT NULL,
    stress_assumed  jsonb       NOT NULL DEFAULT '[]'::jsonb,
    -- Volume provenance, three columns because three separate facts have to
    -- survive into the published derivative. `volume_source` is the publishing
    -- AGENCY (`ddot`, `vdot`, `mdot-sha`) and never the precedence tier it once
    -- held: with "state" in this column an MDOT SHA count and a VDOT count were
    -- the same row, and PLAN:31-34 asks the derivative to be able to name the
    -- segments a conditionally licensed source influenced. `volume_aadt` is the
    -- count and `volume_year` its vintage; a count nobody can date is a
    -- different claim from a current one, which is why the year is stored
    -- rather than assumed and is nullable rather than defaulted. All three are
    -- null on a way no count reached.
    --
    -- No migration accompanies these: the segment schema is created whole by
    -- `create_segment_schema` on every rebuild and promoted by rename, and
    -- `core.models.Segment` is unmanaged.
    volume_source   text,
    volume_aadt     integer,
    volume_year     smallint,
    sinuosity       double precision,
    is_trail_class  boolean     NOT NULL DEFAULT false,
    -- Nullable on purpose: absent `surface` is unknown, not paved. Untagged
    -- rural gravel is common in Loudoun, and reading absence as paved
    -- understates the unpaved share the rural ranking keys on.
    is_unpaved      boolean,
    is_rough        boolean     NOT NULL DEFAULT false,
    lit             boolean,
    -- The owner's facility class (`routemaker.facility`, 2026-09-27): path,
    -- protected, lane or none. The one source the route breakdown and the
    -- facility tiles read. `car_free_when` names the ride times
    -- (`routemaker.ridetime.WHENS`) in which a timed closure to motor traffic
    -- makes the way a path as well; empty on every other way.
    facility        text        NOT NULL DEFAULT 'none'
                    CHECK (facility IN ('path', 'protected', 'lane', 'none')),
    car_free_when   text[]      NOT NULL DEFAULT '{{}}',
    -- How the stress map draws the way (`routemaker.facility.map_class`):
    -- `road`; `barred`, a public road a bicycle may not use, and `hidden`, a
    -- way no typical rider could use (a terminal hallway, a sidewalk, a
    -- private road, a road inside a base, a cemetery or a parking lot), both
    -- not drawn; `alley`, drawn only close in and faint. And whether a road's
    -- own tags say its bike facility is mapped as a way of its own beside it
    -- (`routemaker.facility.has_separate_bikeway`), which the map draws faint
    -- and late so that facility is the main line (the owner, 2026-09-29;
    -- OWNER-DECISIONS 73, 78, 80, 82, 88, 89, 98, 99, 100).
    map_class       text        NOT NULL DEFAULT 'road'
                    CHECK (map_class IN ('road', 'barred', 'hidden', 'alley')),
    separate_bikeway boolean    NOT NULL DEFAULT false,
    -- NO-BIKE-PATHS (OWNER-DECISIONS 291): a way the standard graphs close for
    -- being mountain-bike class or rated singletrack
    -- (`routemaker.trailaccess.MTB`, `routemaker.singletrack`), kept for a
    -- future MTB mode, with tile property `mtb` for the map to draw it faint
    -- (290(b); not read by the front end yet). And a short
    -- `bicycle=dismount` connector routing keeps, which the route description
    -- flags "walk your bike here" (`walk_bike`).
    mtb_only        boolean     NOT NULL DEFAULT false,
    walk_bike       boolean     NOT NULL DEFAULT false,
    -- What the classifier read the road at, for the intersection model
    -- (`routemaker.intersections`; OWNER-DECISIONS 165-167, 172): the speed and
    -- through lanes a direction as read (tags, an agency's record, a curated
    -- speed; null where the classifier assumed them), and whether it is one-way.
    -- Null on a trail or a motor-only class, and on every row of a table built
    -- before this column existed (the route's intersection reasons then name
    -- the tier alone; `core.routing` checks for the columns).
    road_speed_mph  smallint,
    road_lanes      smallint,
    road_oneway     boolean,
    -- A curated stress adjustment (`routemaker.stress.StressAdjustment`; the
    -- owner, 2026-09-27, asking for a clickable "why", perhaps hidden).
    -- `stress_adjustment_id` is stable across rebuilds and shared by the ways
    -- of one stretch; null where no curated row set the tier. The rest is
    -- what a rider may read, and is null on an adjustment that is hidden or
    -- whose category and note the owner has not approved: such a row says
    -- only that the tier was adjusted. `stress_computed_tier` is the
    -- classifier's tier and `stress_adjustment_direction` follows from it.
    -- The owner's quoted reason is never here; it stays in the override row.
    stress_adjustment_id        text,
    stress_computed_tier        smallint CHECK (stress_computed_tier BETWEEN 1 AND 5),
    stress_adjustment_direction text CHECK (stress_adjustment_direction IN ('up', 'down', 'same')),
    stress_adjustment_category  text CHECK (stress_adjustment_category IN (
        'speed', 'road_conditions', 'driver_behaviour', 'intersection', 'sightlines',
        'better_among_alternatives', 'other')),
    stress_adjustment_note      text,
    -- `route_only`: the note is for the summary of a route over the stretch
    -- and nowhere else (the owner: "Only provide the warnings if the route
    -- goes over the road"); `map`: also on a click on the map.
    stress_adjustment_display   text CHECK (stress_adjustment_display IN ('route_only', 'map')),
    -- The tier on the agency's own count where same-street AADT smoothing
    -- lowered `stress_tier` (`pipeline.aadt_smoothing`, OWNER-DECISIONS 285,
    -- 303); null everywhere else. The junction model reads the greater of the
    -- two, so a count bunched at an intersection is still charged at the
    -- intersection after the link stops paying it ("we don't want to double
    -- count"). `volume_aadt` stays the agency's count, never the median. No
    -- migration: this table is created whole on every rebuild; `core.junctions`
    -- checks for the column on a table built before it.
    stress_unsmoothed_tier      smallint CHECK (stress_unsmoothed_tier BETWEEN 1 AND 5),
    CONSTRAINT segment_adjustment_shown CHECK (
        stress_adjustment_id IS NOT NULL
        OR (stress_computed_tier IS NULL AND stress_adjustment_direction IS NULL
            AND stress_adjustment_category IS NULL AND stress_adjustment_note IS NULL
            AND stress_adjustment_display IS NULL)),
    -- Where each input the classifier read came from, on a way an agency's
    -- street layer (DC's Roadway Block, Baltimore's street centerline) was
    -- matched to: an object of attribute to source (maxspeed, lanes, oneway,
    -- bike, parking, aadt), with `blocks` the matched block ids. An agency name
    -- means the agency's value took precedence over OSM's and over the
    -- project's defaults; `osm` that the way's own tag stood; `default` that
    -- nothing said and the classifier assumed. Null on a way no layer reached,
    -- which reads as `stress_assumed` already does.
    attr_sources    jsonb,
    -- The long trails (`trail_route`, `trail_run_m`, `trail_bridge`;
    -- OWNER-DECISIONS 375, 377, 378, 380, 381): what the zoomed-out tiles keep a
    -- path for. `trail_name` is the OSM name of a way the zoomed-out map draws
    -- (or of its long route), `trail_route` the level of the route relation it
    -- is in (0-3) and `trail_run_m` the length of its named run, set after the
    -- rows are written (`pipeline.trail_routes.derive_trail_runs`). A
    -- mountain-bike way is written with no name and route 0, so it can never
    -- qualify.
    trail_name      text,
    trail_route     smallint    NOT NULL DEFAULT 0 CHECK (trail_route BETWEEN 0 AND 3),
    trail_run_m     integer,
    -- A short bridge in a kept trail (`TRAIL_BRIDGE_MAX_M`): 1 between paved trail
    -- ways, 2 where an end is unpaved, 0 otherwise (3 only during the rebuild).
    trail_bridge    smallint    NOT NULL DEFAULT 0 CHECK (trail_bridge BETWEEN 0 AND 3),
    -- The ride layer (`calm_run_m`; OWNER-DECISIONS 391, 402a): the length in metres of
    -- the connected network or named run of a traffic-free path, or the calm run of a
    -- named road at LTS 1 or 2 (`pipeline.calm_roads`), which the z12-13 tiles keep it
    -- for. 0 on such a way until `pipeline.trail_routes.derive_calm_runs` sets it; null
    -- on every other way and on a mountain-bike trail.
    calm_run_m      integer,
    -- A drawn trail beside a road (OWNER-DECISIONS 403; `pipeline.trail_routes.
    -- derive_roadside`): a sidepath by its tags or by lying along a road. Such a trail
    -- with no surface mapped is drawn as the paved path it most likely is, not as a
    -- surface-unknown one. Null only during the rebuild; false on every other way.
    roadside        boolean,
    -- The width a mass-ride group has on the way, metres (`routemaker.massflow`;
    -- OWNER-DECISIONS 325-327, 387). Riders a minute is computed from it by
    -- `routemaker.flow` when tiles and routes are served (the stress tiles carry `rpm`),
    -- so tuning the flow constants needs no rebuild.
    -- Null on a table built before the column existed (the map then draws as it did).
    mass_usable_width_m real      CHECK (mass_usable_width_m BETWEEN 0 AND 60),
    -- Why a bicycle may not use the way, or why an owner override reopened it, as a
    -- short code (`routemaker.facility.bike_access_reason`), for the map's road panel
    -- (OWNER-DECISIONS 441a; `core.segment_info` words it and asks the router whether
    -- the graph lets a bicycle on). Null on a way with nothing to say, and on every row
    -- of a table built before the column existed (the panel then says the reason comes
    -- with the next data update).
    bike_access_reason text,
    CONSTRAINT segment_key UNIQUE (osm_way_id, ordinal)
);

CREATE INDEX segment_way_idx ON {schema}.segment (osm_way_id);
CREATE INDEX segment_geom_idx ON {schema}.segment USING gist (geometry);
CREATE INDEX segment_stress_idx ON {schema}.segment (stress_tier);
-- The stress tiles' zoomed-out levels draw only the paths and trails
-- (trails_predicate) and then the busy roads (busy_predicate); this index
-- holds only the busy-road level's rows, which include the trails', so a z10 tile's scan
-- does not read the whole region's streets to find them.
CREATE INDEX segment_overview_geom_idx ON {schema}.segment USING gist (geometry)
    WHERE {overview};
-- The trail seek reads only its corridors (SEEK_INDEX_PREDICATE), a band at a
-- time; this index holds just those rows (core.trailseek.corridor_segments).
CREATE INDEX segment_seek_geom_idx ON {schema}.segment USING gist (geometry)
    WHERE {seek};
-- The z12-13 ride layer's tiles (RIDE_INDEX_PREDICATE).
CREATE INDEX segment_ride_geom_idx ON {schema}.segment USING gist (geometry)
    WHERE {ride};

-- What each synthetic border-control node means. The node ids are reassigned
-- every rebuild, so this table describes one particular graph and changes
-- hands in the same rename as the segment table. It used to be a managed table
-- in public, rewritten five stages before the swap, which left a failed rebuild
-- with a served graph whose node ids resolved against a table describing a
-- graph that never existed. Column names match core.models.BorderCrossing,
-- which reads it unqualified through the search path exactly as Segment does.
CREATE TABLE {schema}.border_crossing (
    id              bigserial PRIMARY KEY,
    node_id         bigint      NOT NULL UNIQUE,
    location        geometry(Point, 4326) NOT NULL,
    osm_way_id      bigint      NOT NULL,
    state_a         varchar(2)  NOT NULL,
    state_b         varchar(2)  NOT NULL
);

CREATE INDEX border_crossing_way_idx ON {schema}.border_crossing (osm_way_id);
"""


def create_segment_schema(schema: str) -> None:
    """Build an empty segment schema. Idempotent only at the schema level."""
    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(
            SEGMENT_DDL.format(
                schema=schema,
                overview=OVERVIEW_INDEX_PREDICATE,
                seek=SEEK_INDEX_PREDICATE,
                ride=RIDE_INDEX_PREDICATE,
            )
        )


def drop_segment_schema(schema: str) -> None:
    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def refuse_unswappable_schema(schema: str) -> str:
    """Refuse a staging name that names something the rebuild must never drop.

    `writers.refuse_live_schema` is the same rule for the additive writers, and
    it was the only one: this function runs `DROP SCHEMA ... CASCADE` as the
    very first thing the rebuild does, against whatever `ROUTEMAKER_STAGING_
    SCHEMA` happens to say. With staging set to the live name - a typo, a
    copied `.env`, a second deployment on one host - the first stage of the
    weekly rebuild deletes the served graph before it has fetched a single
    byte, and the rollback target goes the same way if it names that.

    `public` is here for a harder reason than either: it is where every
    migrated table lives - users, sessions, memberships, the audit log - and
    `DROP SCHEMA public CASCADE` is the whole deployment, not one week's tiles.
    It arrives with the rest of `RESERVED_SCHEMAS`, the catalogs included.

    Settings refuses these names at import as well. Both layers, because the
    settings check is what an operator meets on the next deploy and this one is
    what stands in front of the DDL however the name arrived.
    """
    from django.conf import settings

    validate_schema_name(schema)
    refuse_reserved_schema(schema)
    protected = {
        settings.SEGMENT_SCHEMA_LIVE: "the schema being served",
        settings.SEGMENT_SCHEMA_RETIRED: "the schema a rollback puts back",
    }
    if schema in protected:
        raise ValueError(
            f"refusing to drop and recreate {schema!r}: it is {protected[schema]}. "
            "The rebuild resets its staging schema only."
        )
    return schema


def refuse_undroppable_retired(retired: str, live: str, staging: str) -> str:
    """Refuse to drop a retired name that is really one of the other two.

    The swap's first statement is `DROP SCHEMA IF EXISTS {retired} CASCADE`, and
    `retired` is derived - `<live>_old` - rather than configured, which is
    exactly why nothing checked it. Two ways it stops being a name of its own:
    the identifier truncation `validate_schema_name` now bounds, which collapses
    `<live>_old` onto `<live>`; and a staging setting that happens to spell the
    retired name, which the settings layer refuses but which this function is
    the last stop for. Either way the statement deletes the graph being served
    or the one this rebuild just built, half a second before renaming it.

    Cheap, and it runs inside the swap's transaction on the one path where
    being wrong is unrecoverable.
    """
    refuse_reserved_schema(retired)
    if retired == live:
        raise ValueError(
            f"refusing to drop {retired!r}: it is also the live schema. The retired name is "
            f"{live!r} plus {RETIRED_SUFFIX!r}, so this means the identifier was truncated, "
            "and the drop would delete the graph the next statement renames."
        )
    if retired == staging:
        raise ValueError(
            f"refusing to drop {retired!r}: it is also the staging schema, which holds the "
            "build this swap is about to promote."
        )
    return retired


def reset_segment_schema(schema: str) -> None:
    """Drop and recreate a staging schema, empty.

    The first stage of every rebuild. Nothing created the schema before the
    first rebuild on a real box, so it failed on a missing relation, and every
    later one inserted into a schema still holding last week's rows. It runs
    first rather than in the segment writer because the crossings table is
    written several stages earlier than the segments and would otherwise be
    dropped along with the schema it had just been written into.

    Which is why the name is checked before anything is dropped: the first
    thing the first stage of the rebuild does is destructive, and the name it
    is handed comes from the environment.
    """
    refuse_unswappable_schema(schema)
    drop_segment_schema(schema)
    create_segment_schema(schema)


def schema_exists(schema: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", [schema])
        return cursor.fetchone() is not None
