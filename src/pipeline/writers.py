"""Writing the pipeline's output into the staging schema.

Written with `execute_values`-style batching rather than the ORM, because the
segment table is unmanaged and rebuilt whole each week: there is no model
lifecycle to respect and several million rows to insert.

Everything here targets a schema by name and never `live`, so a writer cannot
touch the schema currently being served. The swap is the only thing that
promotes staging, and it is a separate step for exactly that reason.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from django.db import connection

from routemaker.stress import StressResult

BATCH = 1_000


def _batched(rows: Sequence[tuple], size: int = BATCH) -> Iterable[Sequence[tuple]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def write_segments(schema: str, rows: Sequence[dict]) -> int:
    """Insert segment rows into a staging schema.

    Each row carries the stress provenance alongside the tier, because a tier
    derived from assumed inputs and one derived from surveyed inputs are
    different claims, and the published derivative needs to know which segments
    a conditionally licensed source touched.
    """
    from .schema import validate_schema_name

    validate_schema_name(schema)
    if schema == "live":
        raise ValueError("writers never target the live schema; write to staging and swap")

    values = [
        (
            row["osm_way_id"],
            row["ordinal"],
            row["wkt"],
            int(row["stress"].tier),
            row["stress"].rule,
            list(row["stress"].assumed),
            row["stress"].volume_source,
            row.get("sinuosity"),
            row.get("is_trail_class", False),
            row.get("is_unpaved"),
            row.get("is_rough", False),
            row.get("lit"),
        )
        for row in rows
    ]

    written = 0
    with connection.cursor() as cursor:
        for batch in _batched(values):
            args = ",".join(
                cursor.mogrify(
                    "(%s,%s,ST_GeomFromText(%s,4326),%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)",
                    (
                        way_id,
                        ordinal,
                        wkt,
                        tier,
                        rule,
                        _json_list(assumed),
                        source,
                        sinuosity,
                        trail,
                        unpaved,
                        rough,
                        lit,
                    ),
                )
                for (
                    way_id,
                    ordinal,
                    wkt,
                    tier,
                    rule,
                    assumed,
                    source,
                    sinuosity,
                    trail,
                    unpaved,
                    rough,
                    lit,
                ) in batch
            )
            cursor.execute(
                f"""INSERT INTO {schema}.segment
                    (osm_way_id, ordinal, geometry, stress_tier, stress_rule,
                     stress_assumed, volume_source, sinuosity, is_trail_class,
                     is_unpaved, is_rough, lit)
                    VALUES {args}"""
            )
            written += len(batch)
    return written


def _json_list(values: Iterable[str]) -> str:
    import json

    return json.dumps(list(values))


def write_border_crossings(nodes: Sequence) -> int:
    """Record what each synthetic border node means.

    Valhalla keeps no custom node tags, so the two states a node separates live
    here and the application resolves crossing direction from this table. These
    rows are replaced wholesale each rebuild, because the node ids are
    reassigned each time and are not persistent identity.
    """
    from core.models import BorderCrossing

    BorderCrossing.objects.all().delete()
    BorderCrossing.objects.bulk_create(
        [
            BorderCrossing(
                node_id=node.node_id,
                location=f"SRID=4326;POINT({node.lon} {node.lat})",
                osm_way_id=node.osm_way_id,
                state_a=node.state_a,
                state_b=node.state_b,
            )
            for node in nodes
        ],
        batch_size=BATCH,
    )
    return len(nodes)


def segment_row(
    way_id: int,
    ordinal: int,
    coordinates: Sequence[tuple[float, float]],
    stress: StressResult,
    **extra,
) -> dict:
    """Build one segment row from a piece of way geometry."""
    wkt = "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in coordinates) + ")"
    return {"osm_way_id": way_id, "ordinal": ordinal, "wkt": wkt, "stress": stress, **extra}
