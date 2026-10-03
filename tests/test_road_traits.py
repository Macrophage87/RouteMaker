"""What the classifier read a road at, kept for the intersection model.

`routemaker.intersections` prices a crossing by the crossed road's speed and
width and a left turn by the lanes the rider must cross (OWNER-DECISIONS 165 to
167), and its reasons say "a 4-lane 35 mph road" (item 172). The segment table
did not carry them; it now does: `road_speed_mph`, `road_lanes` (through lanes a
direction) and `road_oneway`, written from `StressResult`.
"""

from __future__ import annotations

from dataclasses import replace

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


# Connecticut Ave NW 6051314's tags as the classifier reads them (the 2026-09-25
# extract, with the District's parking record): a carriageway of a divided road,
# three lanes one way at 25 mph (correctness re-check of 2b0cf00, blocker 1).
CONNECTICUT = {
    "highway": "primary",
    "name": "Connecticut Avenue Northwest",
    "lanes": "3",
    "maxspeed": "25 mph",
    "oneway": "yes",
    "parking:both": "no",
}


class TestADividedRoadsCarriagewayIsOneWayForTheJunctions:
    """`StressResult.oneway` is item 109's relief reading (a carriageway is not a
    one-way street there); `graph_oneway` is the way's own direction, which the
    segment table's `road_oneway` carries to the junction model."""

    def test_the_classifier_keeps_both_readings(self) -> None:
        result = classify(CONNECTICUT, aadt=30149, urban=True, jurisdiction="DC", divided=True)
        assert (result.lanes, result.oneway, result.graph_oneway) == (3, False, True)
        alone = classify(CONNECTICUT, aadt=30149, urban=True, jurisdiction="DC")
        assert (alone.oneway, alone.graph_oneway) == (True, True)
        # The relief reading still decides the tier (item 109): a carriageway
        # is read as the two-way road it is half of.
        assert "two-way floor" in result.rule

    @pytest.mark.parametrize(
        ("tags", "expected"),
        [
            ({"highway": "primary", "oneway": "no", "lanes": "4"}, False),
            ({"highway": "primary", "lanes": "4"}, False),
            ({"highway": "primary", "oneway": "-1"}, True),
            ({"highway": "primary", "junction": "roundabout"}, True),
            ({"highway": "primary", "junction": "roundabout", "oneway": "no"}, False),
            # Mutation re-check TG1: an odd `oneway` value on a roundabout is not
            # the mapper saying two-way.
            ({"highway": "primary", "junction": "roundabout", "oneway": "reversible"}, True),
            ({"highway": "primary", "junction": "circular", "oneway": "alternating"}, True),
            ({"highway": "cycleway", "oneway": "yes"}, None),
            ({"highway": "motorway", "oneway": "yes"}, None),
        ],
    )
    def test_the_graph_direction_is_the_tags_own(self, tags, expected) -> None:
        for divided in (False, True):
            assert classify(tags, divided=divided).graph_oneway is expected, (tags, divided)

    def test_the_junction_model_prices_the_carriageway_pair_as_divided(self) -> None:
        """The reviewer's probe: the pair crossing has the median-refuge credit,
        the marker says "3-lane", and a Mass Ride's left off it draws no
        left-across marker (it was 1,200 ft with no credit, "6-lane", and an
        orange marker with `oneway` written)."""
        from routemaker import intersections as m
        from routemaker.intersections import Control, Junction, Movement, Road

        stress = classify(CONNECTICUT, aadt=30149, urban=True, jurisdiction="DC", divided=True)
        name = frozenset({"connecticut avenue northwest"})

        def road(way: int, oneway) -> Road:
            return Road(
                int(stress.tier),
                speed_mph=stress.speed_mph,
                lanes=stress.lanes,
                oneway=oneway,
                aadt=30149,
                names=name,
                display=("Connecticut Avenue Northwest",),
                ways=frozenset({way}),
            )

        quiet = Road(1, names=frozenset({"quiet street"}))

        def crossing(at: float, crossed: Road) -> Junction:
            return Junction(at, -77.05, 38.93, Movement.STRAIGHT, quiet, quiet, (crossed,))

        def pair(oneway):
            return m.assess_route(
                [crossing(100.0, road(1, oneway)), crossing(130.0, road(2, oneway))]
            )

        (written,) = pair(stress.graph_oneway)
        one = m.assess(crossing(0.0, road(1, True)))
        assert written.cost_ft == pytest.approx(one.cost_ft * m.MEDIAN_REFUGE_FACTOR)
        assert "3-lane" in written.reason and "6-lane" not in written.reason
        (relief,) = pair(stress.oneway)
        assert relief.cost_ft == pytest.approx(one.cost_ft) and "6-lane" in relief.reason
        # A Mass Ride's left off the carriageway: no oncoming traffic, no marker.
        left = Junction(
            0.0,
            -77.05,
            38.93,
            Movement.LEFT,
            road(1, stress.graph_oneway),
            quiet,
            control=Control.SIGNAL,
        )
        assert m.assess(left, group=True) is None
        two_way = replace(left, incoming=road(1, stress.oneway))
        assert m.assess(two_way, group=True) is not None


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
                graph_oneway=True,
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
        assert after.graph_oneway is True


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
