"""What the classifier read a road at, kept for the intersection model.

`routemaker.intersections` prices a crossing by the crossed road's speed and
width and a left turn by the lanes the rider must cross (OWNER-DECISIONS 165 to
167), and its reasons say "a 4-lane 35 mph road" (item 172). The segment table
did not carry them; it now does: `road_speed_mph`, `road_lanes` (through lanes a
direction) and `road_oneway`, written from `StressResult`.
"""

from __future__ import annotations

import pytest
from django.db import connection

from pipeline import overrides, schema
from pipeline.run import _smallint
from pipeline.writers import segment_row, write_segments
from routemaker.stress import Stress, StressResult, classify


class TestClassifierKeepsWhatItRead:
    def test_a_posted_speed_two_lanes_a_direction_and_two_way(self) -> None:
        result = classify(
            {"highway": "primary", "maxspeed": "35 mph", "lanes": "4", "oneway": "no"}, urban=True
        )
        assert result.speed_mph == 35
        assert result.lanes == 2, "lanes a direction: four lanes two-way"
        assert result.oneway is False

    def test_a_one_way_keeps_its_lanes_and_says_so(self) -> None:
        result = classify(
            {"highway": "secondary", "maxspeed": "30 mph", "lanes": "3", "oneway": "yes"}
        )
        assert (result.speed_mph, result.lanes, result.oneway) == (30, 3, True)

    def test_an_assumed_speed_is_kept_and_marked_assumed(self) -> None:
        result = classify({"highway": "residential"}, urban=True)
        assert result.speed_mph is not None
        assert "maxspeed" in result.assumed

    def test_a_trail_has_no_road_traits(self) -> None:
        result = classify({"highway": "cycleway"})
        assert (result.speed_mph, result.lanes, result.oneway) == (None, None, None)

    def test_a_motor_only_class_has_none_either(self) -> None:
        result = classify({"highway": "motorway"})
        assert (result.speed_mph, result.lanes, result.oneway) == (None, None, None)

    def test_the_avoid_mark_keeps_them(self) -> None:
        """ "Legal but avoid" replaces the tier only (`dataclasses.replace`)."""
        result = classify(
            {"highway": "trunk", "expressway": "yes", "maxspeed": "55 mph", "lanes": "4"}
        )
        assert result.tier is Stress.AVOID
        assert result.speed_mph == 55 and result.lanes == 2


class TestAnOwnerOverrideDoesNotChangeTheRoad:
    def test_the_curated_tier_keeps_the_roads_traits(self) -> None:
        classified = {
            7: StressResult(
                Stress.LTS3,
                "classified",
                (),
                None,
                None,
                None,
                speed_mph=35.0,
                lanes=2,
                oneway=False,
            )
        }
        row = {
            "tier": 4,
            "adjustment_id": "a",
            "category": "speed",
            "visibility": "public",
            "annotation_status": "approved",
            "display": "route_only",
            "public_note": "A note.",
        }
        assert overrides.apply_stress(classified, [overrides.Override("stress", 7, row)]) == (1, [])
        after = classified[7]
        assert after.tier is Stress.LTS4
        assert (after.speed_mph, after.lanes, after.oneway) == (35.0, 2, False)


@pytest.mark.django_db(transaction=True)
class TestTheTableCarriesThem:
    def test_the_columns_are_declared_nullable_in_the_ddl(self) -> None:
        ddl = schema.SEGMENT_DDL
        assert schema.ROAD_TRAIT_COLUMNS == ("road_speed_mph", "road_lanes", "road_oneway")
        assert "road_speed_mph  smallint," in ddl
        assert "road_lanes      smallint," in ddl
        assert "road_oneway     boolean," in ddl
        for column in schema.ROAD_TRAIT_COLUMNS:
            line = next(row for row in ddl.splitlines() if row.strip().startswith(column))
            assert "NOT NULL" not in line, "null on a trail, and on a table before the column"

    def test_the_writer_stores_them(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        stress = StressResult(
            Stress.LTS4, "x", (), None, None, None, speed_mph=40.0, lanes=3, oneway=True
        )
        rows = [
            segment_row(
                11,
                0,
                [(-77.0, 38.9), (-77.001, 38.9)],
                stress,
                road_speed_mph=40,
                road_lanes=3,
                road_oneway=True,
            ),
            segment_row(
                12, 0, [(-77.0, 38.91), (-77.001, 38.91)], StressResult(Stress.LTS1, "trail")
            ),
        ]
        assert write_segments(staging, rows) == 2
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT osm_way_id, road_speed_mph, road_lanes, road_oneway "
                f"FROM {staging}.segment ORDER BY osm_way_id"
            )
            assert cursor.fetchall() == [(11, 40, 3, True), (12, None, None, None)]

    def test_a_rebuilt_row_has_what_the_classifier_read(self) -> None:
        stress = classify({"highway": "primary", "maxspeed": "35 mph", "lanes": "4"})
        assert _smallint(stress.speed_mph) == 35
        assert _smallint(stress.lanes) == 2

    @pytest.mark.parametrize(("value", "expected"), [(None, None), (24.6, 25), (30, 30), (0.4, 0)])
    def test_traits_are_whole_numbers(self, value, expected) -> None:
        assert _smallint(value) == expected
