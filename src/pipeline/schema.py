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
ROAD_TRAIT_COLUMNS = ("road_speed_mph", "road_lanes", "road_oneway")

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
    CONSTRAINT segment_adjustment_shown CHECK (
        stress_adjustment_id IS NOT NULL
        OR (stress_computed_tier IS NULL AND stress_adjustment_direction IS NULL
            AND stress_adjustment_category IS NULL AND stress_adjustment_note IS NULL
            AND stress_adjustment_display IS NULL)),
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
        cursor.execute(SEGMENT_DDL.format(schema=schema, overview=OVERVIEW_INDEX_PREDICATE))


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
