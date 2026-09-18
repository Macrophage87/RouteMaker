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

# Schema names are interpolated into DDL, which no parameter placeholder can
# carry. They come from settings, which itself reads them straight from
# ROUTEMAKER_LIVE_SCHEMA and ROUTEMAKER_STAGING_SCHEMA - so this guard is not a
# defense against some hypothetical future change, it is what stands between
# whatever an operator's environment happens to set and arbitrary SQL running
# against production today, in the one module that runs DDL there.
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_schema_name(schema: str) -> str:
    if not _SCHEMA_NAME.match(schema):
        raise ValueError(f"refusing to interpolate {schema!r} into DDL")
    return schema


SEGMENT_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE {schema}.segment (
    id              bigserial PRIMARY KEY,
    osm_way_id      bigint      NOT NULL,
    ordinal         integer     NOT NULL,
    geometry        geometry(LineString, 4326) NOT NULL,
    stress_tier     smallint    NOT NULL CHECK (stress_tier BETWEEN 1 AND 4),
    stress_rule     text        NOT NULL,
    stress_assumed  jsonb       NOT NULL DEFAULT '[]'::jsonb,
    volume_source   text,
    sinuosity       double precision,
    is_trail_class  boolean     NOT NULL DEFAULT false,
    -- Nullable on purpose: absent `surface` is unknown, not paved. Untagged
    -- rural gravel is common in Loudoun, and reading absence as paved
    -- understates the unpaved share the rural ranking keys on.
    is_unpaved      boolean,
    is_rough        boolean     NOT NULL DEFAULT false,
    lit             boolean,
    CONSTRAINT segment_key UNIQUE (osm_way_id, ordinal)
);

CREATE INDEX segment_way_idx ON {schema}.segment (osm_way_id);
CREATE INDEX segment_geom_idx ON {schema}.segment USING gist (geometry);
CREATE INDEX segment_stress_idx ON {schema}.segment (stress_tier);

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
        cursor.execute(SEGMENT_DDL.format(schema=schema))


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

    Settings refuses these three names at import as well. Both layers, because
    the settings check is what an operator meets on the next deploy and this
    one is what stands in front of the DDL however the name arrived.
    """
    from django.conf import settings

    validate_schema_name(schema)
    protected = {
        settings.SEGMENT_SCHEMA_LIVE: "the schema being served",
        settings.SEGMENT_SCHEMA_RETIRED: "the schema a rollback puts back",
        "public": "the schema every migrated table lives in",
    }
    if schema in protected:
        raise ValueError(
            f"refusing to drop and recreate {schema!r}: it is {protected[schema]}. "
            "The rebuild resets its staging schema only."
        )
    return schema


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
