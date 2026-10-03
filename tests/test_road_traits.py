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

    @pytest.mark.parametrize("junction", ["roundabout", "circular"])
    def test_a_roundabout_is_one_way_without_saying_so(self, junction) -> None:
        """OWNER-DECISIONS 228: Washington Circle NW 6059311's tags, which no
        `oneway` tag says: the classifier and `road_oneway` read the ring one-way
        as routing does, and its four lanes are a direction's (it read them as
        two each way, and the ring as a two-way road)."""
        tags = {"highway": "primary", "junction": junction, "lanes": "4", "name": "Circle"}
        result = classify(tags, urban=True, jurisdiction="DC")
        assert (result.lanes, result.oneway) == (4, True)
        assert (
            result.tier == classify({**tags, "oneway": "yes"}, urban=True, jurisdiction="DC").tier
        )
        # A mapper's `oneway=no` stands, and the ring is read two-way.
        two_way = classify({**tags, "oneway": "no"}, urban=True, jurisdiction="DC")
        assert (two_way.lanes, two_way.oneway) == (2, False)
        # Another junction is no roundabout.
        assert classify({**tags, "junction": "jughandle"}, urban=True).oneway is False

    def test_an_assumed_speed_or_lane_count_is_not_kept(self) -> None:
        """Review r1, SHOULD_FIX 7: the class default the tables fell back on is
        not a fact about the road, and the junction reasons would state it as
        one ("2-lane 25 mph road"); and an assumed single lane would zero the
        merge cost the model assumes by tier where the count is unknown."""
        result = classify({"highway": "residential"}, urban=True)
        assert "maxspeed" in result.assumed and "lanes" in result.assumed
        assert result.speed_mph is None and result.lanes is None
        assert result.oneway is False

    def test_a_posted_speed_without_lanes_keeps_the_speed_alone(self) -> None:
        result = classify({"highway": "primary", "maxspeed": "40 mph"}, urban=True)
        assert (result.speed_mph, result.lanes) == (40, None)

    def test_lanes_without_a_posted_speed_keep_the_lanes_alone(self) -> None:
        result = classify({"highway": "primary", "lanes": "6"}, urban=True)
        assert (result.speed_mph, result.lanes) == (None, 3)

    def test_a_unitless_posted_speed_is_kept(self) -> None:
        """The number was surveyed; only its unit is assumed."""
        result = classify({"highway": "secondary", "maxspeed": "30"}, urban=True)
        assert "maxspeed unit" in result.assumed and result.speed_mph == 30

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
