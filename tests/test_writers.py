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
