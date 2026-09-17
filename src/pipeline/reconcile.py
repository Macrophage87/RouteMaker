"""What ran after the swap, against the live table: the drift report.

The plan's reconciliation job does two things after each swap: re-resolves
every anchor by way id and nearest geometry, flagging what it cannot resolve,
and emits a drift report of routes whose segments changed attributes or lost
their edges. Anchors are phase 2 - nothing exists yet to anchor a comment or
an issue to - so what phase 1 can do is the segment-level half: measure the
new live schema against the retired one while both exist, and record it.

It is a stage rather than a log line because the alert reads rows, and because
a swap that promoted a graph with a third of last week's segments missing is
something an operator should see the morning after, not discover from a
reviewer.
"""

from __future__ import annotations

from django.db import connection

from .schema import schema_exists, validate_schema_name


def drift_report(build_id: str, live: str, retired: str):
    """Compare the promoted schema against the retired one and record it."""
    from core.models import DriftReport

    validate_schema_name(live)
    validate_schema_name(retired)

    if not schema_exists(retired):
        # A first deployment retires nothing; the swap creates an empty live
        # first, so this is unreachable in practice, and if it were reached the
        # honest report is "compared against nothing".
        counts = _counts(live)
        return DriftReport.objects.create(
            build_id=build_id,
            segments_before=0,
            segments_after=counts["segments"],
            segments_lost=0,
            segments_added=counts["segments"],
            segments_regraded=0,
            crossings_before=0,
            crossings_after=counts["crossings"],
            note="no retired schema to compare against",
        )

    before = _counts(retired)
    after = _counts(live)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
              count(*) FILTER (WHERE n.osm_way_id IS NULL) AS lost,
              count(*) FILTER (WHERE o.osm_way_id IS NULL) AS added,
              count(*) FILTER (WHERE o.osm_way_id IS NOT NULL AND n.osm_way_id IS NOT NULL
                                 AND o.stress_tier <> n.stress_tier) AS regraded
            FROM {retired}.segment o
            FULL OUTER JOIN {live}.segment n
              ON o.osm_way_id = n.osm_way_id AND o.ordinal = n.ordinal
            """
        )
        lost, added, regraded = cursor.fetchone()

    return DriftReport.objects.create(
        build_id=build_id,
        segments_before=before["segments"],
        segments_after=after["segments"],
        segments_lost=lost,
        segments_added=added,
        segments_regraded=regraded,
        crossings_before=before["crossings"],
        crossings_after=after["crossings"],
        note="anchor reconciliation is phase 2; segment drift only",
    )


def _counts(schema: str) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {schema}.segment")
        segments = cursor.fetchone()[0]
        cursor.execute(f"SELECT count(*) FROM {schema}.border_crossing")
        crossings = cursor.fetchone()[0]
    return {"segments": segments, "crossings": crossings}
