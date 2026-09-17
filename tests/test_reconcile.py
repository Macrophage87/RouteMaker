"""The drift report, against two real schemas.

It is the one thing that looks at a swap afterwards and says what changed, and
the alert reads its rows: a graph promoted with a third of last week's segments
missing is something an operator should see the morning after.

The fixtures here carry ways with several segments on purpose. A way is split
into ordinals, so the segment key is (way id, ordinal) and the join that
compares two schemas has to use both. With a single-segment fixture it does not:
every way matches exactly one row either way, and dropping `o.ordinal =
n.ordinal` from the join changes nothing at all.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.db import connection

pytestmark = pytest.mark.django_db(transaction=True)


def insert_segment(schema: str, way_id: int, ordinal: int, tier: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""INSERT INTO {schema}.segment
                (osm_way_id, ordinal, geometry, stress_tier, stress_rule)
                VALUES (%s, %s,
                        ST_GeomFromText('LINESTRING(-77 38.9, -77.01 38.91)', 4326),
                        %s, 'test')""",
            [way_id, ordinal, tier],
        )


def insert_crossing(schema: str, node_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""INSERT INTO {schema}.border_crossing
                (node_id, location, osm_way_id, state_a, state_b)
                VALUES (%s, ST_GeomFromText('POINT(-77 38.9)', 4326), 1, 'DC', 'MD')""",
            [node_id],
        )


@pytest.fixture
def retired_schema(segment_schemas):
    """The retired schema beside the live one, as it exists between the rename
    and the drop. The `segment_schemas` fixture drops all three afterwards."""
    from pipeline.schema import create_segment_schema

    live, _staging = segment_schemas
    retired = settings.SEGMENT_SCHEMA_RETIRED
    create_segment_schema(retired)
    return live, retired


def test_drift_is_counted_per_segment_rather_than_per_way(retired_schema) -> None:
    """The join is on (way, ordinal), and both halves of it matter.

    Way 100 has three segments in both schemas and one of them is regraded, so
    the honest answer is one. Joined on the way id alone, the two sides of a
    three-segment way produce nine pairs, three of which disagree about the
    stress tier - a way whose middle segment was regraded is reported as three
    regradings, and a way split differently by a rebuild is reported as dozens.
    """
    from pipeline.reconcile import drift_report

    live, retired = retired_schema

    for ordinal in (0, 1, 2):
        insert_segment(retired, 100, ordinal, tier=1)
    insert_segment(live, 100, 0, tier=1)
    insert_segment(live, 100, 1, tier=3)  # the one real regrading
    insert_segment(live, 100, 2, tier=1)

    report = drift_report("20260917T080000Z", live, retired)

    assert report.segments_before == 3
    assert report.segments_after == 3
    assert report.segments_regraded == 1, "one segment changed tier, not three"
    assert report.segments_lost == 0
    assert report.segments_added == 0


def test_a_segment_that_disappeared_from_a_multi_segment_way_is_lost(retired_schema) -> None:
    """Losing one ordinal of a way is exactly the drift the report exists to
    catch, and it is invisible to a join that only compares way ids: the way is
    still there."""
    from pipeline.reconcile import drift_report

    live, retired = retired_schema

    for ordinal in (0, 1, 2):
        insert_segment(retired, 200, ordinal, tier=2)
    insert_segment(live, 200, 0, tier=2)
    insert_segment(live, 200, 1, tier=2)
    insert_segment(live, 200, 3, tier=2)  # renumbered: ordinal 2 is gone, 3 is new

    report = drift_report("20260917T080000Z", live, retired)

    assert report.segments_lost == 1
    assert report.segments_added == 1
    assert report.segments_regraded == 0


def test_the_report_counts_whole_ways_and_crossings_too(retired_schema) -> None:
    from pipeline.reconcile import drift_report

    live, retired = retired_schema

    insert_segment(retired, 300, 0, tier=1)  # lost with its way
    insert_segment(retired, 301, 0, tier=1)
    insert_segment(live, 301, 0, tier=4)  # regraded
    insert_segment(live, 302, 0, tier=1)  # a new way
    insert_crossing(retired, 5_000_000_001)
    insert_crossing(live, 5_000_000_001)
    insert_crossing(live, 5_000_000_002)

    report = drift_report("20260917T080000Z", live, retired)

    assert (report.segments_before, report.segments_after) == (2, 2)
    assert (report.segments_lost, report.segments_added) == (1, 1)
    assert report.segments_regraded == 1
    assert (report.crossings_before, report.crossings_after) == (1, 2)
    assert report.build_id == "20260917T080000Z"


def test_a_first_deployment_compares_against_nothing_and_says_so(segment_schemas) -> None:
    """The swap creates an empty live first, so this is unreachable in practice;
    reached, the honest report is "compared against nothing" rather than a
    hundred-percent loss."""
    from pipeline.reconcile import drift_report
    from pipeline.schema import drop_segment_schema

    live, _staging = segment_schemas
    drop_segment_schema(settings.SEGMENT_SCHEMA_RETIRED)
    insert_segment(live, 400, 0, tier=1)

    report = drift_report("20260917T080000Z", live, settings.SEGMENT_SCHEMA_RETIRED)

    assert report.segments_before == 0
    assert report.segments_added == 1
    assert report.segments_lost == 0
    assert "no retired schema" in report.note
