"""Writing the pipeline's output.

Two rules the module and the model docstrings argue for at length and that
nothing asserted: the stress provenance travelling into the row, and the border
crossings being replaced wholesale rather than appended to.
"""

from __future__ import annotations

import json

import pytest
from django.db import connection

from pipeline.writers import segment_row, write_border_crossings, write_segments
from routemaker.stress import Stress, StressResult

pytestmark = pytest.mark.django_db(transaction=True)


class Node:
    def __init__(self, node_id: int, way_id: int = 1) -> None:
        self.node_id = node_id
        self.lon, self.lat = -77.0, 38.9
        self.osm_way_id = way_id
        self.state_a, self.state_b = "DC", "MD"


def test_the_stress_provenance_reaches_the_row(segment_schemas) -> None:
    """A tier derived from assumed inputs and one derived from surveyed inputs
    are different claims. A reviewer comparing a tier against crash history needs
    to know which it is reading, and the published derivative needs to know which
    segments a conditionally licensed source touched."""
    _live, staging = segment_schemas
    rows = [
        {
            "osm_way_id": 1,
            "ordinal": 0,
            "wkt": "LINESTRING(-77 38.9, -77.01 38.91)",
            "stress": StressResult(
                Stress.LTS3, "mixed traffic, 30 mph, single lane", ("maxspeed", "lanes"), "vdot"
            ),
        }
    ]
    assert write_segments(staging, rows) == 1

    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT stress_tier, stress_rule, stress_assumed, volume_source FROM {staging}.segment"
        )
        tier, rule, assumed, source = cursor.fetchone()

    # Django registers a no-op jsonb loader so its JSONField controls decoding,
    # so a raw cursor hands back the text rather than the list.
    assumed = json.loads(assumed)

    assert tier == 3
    assert rule == "mixed traffic, 30 mph, single lane"
    assert assumed == ["maxspeed", "lanes"], "the assumptions behind the tier"
    assert source == "vdot"


def test_a_writer_never_targets_the_live_schema(segment_schemas) -> None:
    """The swap is the only thing that promotes staging, and it is a separate
    step for exactly that reason."""
    live, _staging = segment_schemas
    with pytest.raises(ValueError, match="never target the live schema"):
        write_segments("live", [])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "phase1/pipeline: write_segments guards `schema == \"live\"` literally "
        "instead of `schema == settings.SEGMENT_SCHEMA_LIVE`, so it does not stop "
        "a write to a renamed live schema. Owned by the pipeline cluster "
        "(handoff.md item 18; test-quality.md F2, which also notes the test "
        "above shares this literal with the code and so cannot tell the two "
        "apart). Delete this xfail once writers.py reads the setting."
    ),
)
def test_a_writer_never_targets_the_live_schema_even_when_it_is_renamed(settings) -> None:
    """The test above and the code it tests both write the word "live", so a
    guard that checked the wrong thing entirely could still pass it. This
    drives the guard through the name the rest of the pipeline actually uses,
    the way a deployment with ROUTEMAKER_LIVE_SCHEMA set would exercise it."""
    settings.SEGMENT_SCHEMA_LIVE = "prod_live"
    with pytest.raises(ValueError, match="never target the live schema"):
        write_segments(settings.SEGMENT_SCHEMA_LIVE, [])


def test_border_crossings_are_replaced_wholesale(segment_schemas) -> None:
    """The node ids are reassigned every rebuild and are not persistent identity,
    so last week's rows describe nodes that no longer exist. Appending would
    leave the application resolving a crossing direction from a node id the graph
    reuses for somewhere else."""
    from core.models import BorderCrossing

    assert write_border_crossings([Node(1), Node(2)]) == 2
    assert BorderCrossing.objects.count() == 2

    assert write_border_crossings([Node(3)]) == 1
    assert list(BorderCrossing.objects.values_list("node_id", flat=True)) == [3]


def test_a_rebuild_that_finds_no_crossings_still_clears_the_table(segment_schemas) -> None:
    """The case an append would hide completely."""
    from core.models import BorderCrossing

    write_border_crossings([Node(1)])
    write_border_crossings([])
    assert not BorderCrossing.objects.exists()


def test_segment_row_carries_the_derived_attributes(segment_schemas) -> None:
    stress = StressResult(Stress.LTS2, "bike lane, narrow at 25 mph or below")
    row = segment_row(
        1,
        0,
        [(-77.0, 38.9), (-77.01, 38.91)],
        stress=stress,
        is_trail_class=True,
        is_unpaved=None,
        is_rough=False,
        lit=True,
    )
    assert row["osm_way_id"] == 1
    assert row["stress"] is stress
    assert row["is_trail_class"] is True
    assert row["is_unpaved"] is None, "unknown stays unknown rather than becoming false"
    assert row["lit"] is True


# --- F3: the segment key, protected by nothing ------------------------------
#
# `row["ordinal"] -> 0` in the writer, `UNIQUE (osm_way_id, ordinal)` ->
# `(osm_way_id, ordinal, id)`, and `CHECK (stress_tier BETWEEN 1 AND 4)` ->
# `BETWEEN 0 AND 5` all survived the mutation panel, because nothing wrote two
# segments for one way or tried a tier outside the range.


def test_distinct_ordinals_for_one_way_all_reach_their_own_rows(segment_schemas) -> None:
    """A way chunked into many pipeline segments (this one has 70, deliberately
    past the 64-point chunk size Valhalla's own shape encoding uses as a round
    number) must keep every ordinal distinct in the row. `row["ordinal"] -> 0`
    would collapse them onto the same (osm_way_id, ordinal) key; either the
    UNIQUE constraint raises mid-batch or the count of distinct ordinals
    written comes back wrong, but it does not pass quietly either way.
    """
    _live, staging = segment_schemas
    way_id = 999
    count = 70
    rows = [
        segment_row(
            way_id,
            ordinal,
            [(-77.0 - ordinal * 0.001, 38.9), (-77.0 - ordinal * 0.001 - 0.001, 38.9)],
            stress=StressResult(Stress.LTS1, "trail-class way"),
        )
        for ordinal in range(count)
    ]

    assert write_segments(staging, rows) == count

    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT ordinal FROM {staging}.segment WHERE osm_way_id = %s ORDER BY ordinal",
            [way_id],
        )
        ordinals = [row[0] for row in cursor.fetchall()]
    assert ordinals == list(range(count)), "every ordinal for this way must reach its own row"


def test_the_segment_key_rejects_a_duplicate_way_and_ordinal(segment_schemas) -> None:
    """The UNIQUE constraint asserted directly against the DDL, rather than
    through the writer, so a widened constraint - adding the surrogate `id` to
    it, say - is caught even if every writer call happens to stay well-behaved.
    """
    from django.db import IntegrityError

    _live, staging = segment_schemas
    insert_segment(staging, way_id=5000, tier=2)
    with pytest.raises(IntegrityError):
        insert_segment(staging, way_id=5000, tier=3)  # same (osm_way_id, ordinal)


def test_the_stress_tier_check_rejects_a_tier_outside_one_to_four(segment_schemas) -> None:
    """Asserted directly against the DDL. `classify()` can never itself produce
    a tier outside 1-4 - `Stress` is an IntEnum of exactly those four values -
    so this is the database's own backstop against whatever else ever writes
    this column, and nothing exercised it.
    """
    from django.db import IntegrityError

    _live, staging = segment_schemas
    with pytest.raises(IntegrityError):
        insert_segment(staging, way_id=6000, tier=5)
    with pytest.raises(IntegrityError):
        insert_segment(staging, way_id=6001, tier=0)


def insert_segment(schema: str, way_id: int, tier: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""INSERT INTO {schema}.segment
                (osm_way_id, ordinal, geometry, stress_tier, stress_rule)
                VALUES (%s, 0, ST_GeomFromText('LINESTRING(-77 38.9, -77.01 38.91)', 4326),
                        %s, 'test')""",
            [way_id, tier],
        )
