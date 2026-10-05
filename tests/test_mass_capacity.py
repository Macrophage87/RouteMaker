"""The Mass Ride capacity (OWNER-DECISIONS 325-327, 387): the flow model that gives
each segment its riders a minute, the column's validation, and the route's
coloured sections that carry it. The tile property is in test_stress_tiles.py and
the rebuild's writing of the column in test_pipeline_end_to_end.py."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.db import connection

from core import routing
from pipeline import mass_capacity
from pipeline.schema import MASS_WIDTH_COLUMN, SEGMENT_DDL
from routemaker import agency_roads, massflow
from routemaker.agency_roads import DC_AGENCY, RoadFacts

ROOT = Path(__file__).resolve().parent.parent


FT = 0.3048


def dc_block(**facts) -> RoadFacts:
    """A District Roadway Block record, as the parser gives it (widths per lane)."""
    return RoadFacts(agency=DC_AGENCY, **facts)


class TestTheModel:
    """The plan's headline throughput (PLAN.md): 0.37 riders per m2, a pack using 0.7
    of the width, at 1.9 m/s, so about 100 riders a minute for each 11 ft lane."""

    def test_a_lane_carries_about_a_hundred_a_minute(self) -> None:
        assert massflow.capacity_rpm({"highway": "service"}) == 99
        assert 98 <= massflow.LANE_WIDTH_M * massflow.RPM_PER_METRE <= 100

    def test_the_constants_are_the_plans(self) -> None:
        assert (massflow.SAFE_DENSITY_PER_M2, massflow.UTILISATION, massflow.PACE_MS) == (
            0.37,
            0.7,
            1.9,
        )
        assert massflow.RPM_PER_METRE == pytest.approx(29.5, abs=0.05)
        assert massflow.LANE_WIDTH_M == pytest.approx(11 * FT, abs=0.01)
        assert massflow.DOOR_ZONE_M == pytest.approx(3.5 * FT, abs=0.001)

    def test_a_two_lane_street_gives_the_ride_its_own_lane(self) -> None:
        """OWNER-DECISIONS 404: a corked ride holds the cross streets, not the oncoming
        lanes, so a plain two-lane street is one 11 ft lane, about 99 a minute."""
        assert massflow.capacity_rpm({"highway": "residential"}) == 99
        assert massflow.capacity_rpm({"highway": "tertiary", "width": "22'"}) == 99

    @pytest.mark.parametrize(
        ("tags", "lanes", "expected"),
        [
            # Two-way: the narrower direction's lanes.
            ({"highway": "primary", "lanes": "4"}, None, 198),
            ({"highway": "primary", "lanes": "6"}, None, 297),
            (
                {"highway": "primary", "lanes": "5", "lanes:forward": "2", "lanes:backward": "3"},
                None,
                198,
            ),
            ({"highway": "primary", "lanes": "5", "lanes:forward": "3"}, None, 198),
            # A two-way street of one shared lane: the ride has the lane.
            ({"highway": "residential", "lanes": "1"}, None, 99),
            # The classifier's through lanes a direction, where no `lanes` is tagged.
            ({"highway": "secondary"}, 2, 198),
            ({"highway": "secondary", "oneway": "yes"}, 2, 198),
            # One-way: every lane.
            ({"highway": "primary", "oneway": "yes", "lanes": "3"}, None, 297),
            # The class default: a one-way street is one lane, an alley one lane.
            ({"highway": "residential", "oneway": "yes"}, None, 99),
            ({"highway": "service"}, None, 99),
            ({"highway": "primary"}, None, 198),
            # A mapped carriageway width stands for the lanes and the paint, halved on a
            # two-way way.
            ({"highway": "primary", "width": "12", "lanes": "4"}, None, 177),
            ({"highway": "primary", "oneway": "yes", "width": "12"}, None, 354),
            ({"highway": "primary", "width": "garbage", "lanes": "2"}, None, 99),
            ({"highway": "primary", "width": "300", "lanes": "2"}, None, 99),
        ],
    )
    def test_usable_width_comes_from_the_tags(self, tags, lanes, expected) -> None:
        assert massflow.capacity_rpm(tags, lanes) == expected

    def test_a_painted_lane_is_usable_and_a_protected_one_is_not(self) -> None:
        plain = massflow.capacity_rpm({"highway": "secondary", "lanes": "2"})
        painted = massflow.capacity_rpm(
            {"highway": "secondary", "lanes": "2", "cycleway:both": "lane"}
        )
        one_side = massflow.capacity_rpm(
            {"highway": "secondary", "lanes": "2", "cycleway:right": "lane", "cycleway:left": "no"}
        )
        protected = massflow.capacity_rpm(
            {"highway": "secondary", "lanes": "2", "cycleway:both": "track"}
        )
        # Each direction has its side's lane; one side only leaves the other narrower.
        assert painted - plain == pytest.approx(1.5 * massflow.RPM_PER_METRE, abs=1)
        assert one_side == plain, "the direction without the lane is the narrower"
        assert protected == plain, "a protected lane is not usable width (127)"

    def test_a_one_way_street_counts_each_lane_with_it_and_no_contraflow(self) -> None:
        base = {"highway": "secondary", "oneway": "yes", "lanes": "2"}
        plain = massflow.capacity_rpm(base)
        assert plain == 198
        both = massflow.capacity_rpm({**base, "cycleway:both": "lane"})
        assert both - plain == pytest.approx(3.0 * massflow.RPM_PER_METRE, abs=1)
        bare = massflow.capacity_rpm({**base, "cycleway": "lane"})
        assert bare - plain == pytest.approx(1.5 * massflow.RPM_PER_METRE, abs=1)
        contraflow = massflow.capacity_rpm({**base, "cycleway:left": "opposite_lane"})
        assert contraflow == plain
        signed = massflow.capacity_rpm(
            {**base, "cycleway:left": "lane", "cycleway:left:oneway": "-1"}
        )
        assert signed == plain

    def test_a_surveyed_painted_lane_width_is_used(self) -> None:
        wide = massflow.capacity_rpm(
            {
                "highway": "secondary",
                "lanes": "2",
                "cycleway:both": "lane",
                "cycleway:both:width": "2",
            }
        )
        plain = massflow.capacity_rpm({"highway": "secondary", "lanes": "2"})
        assert wide - plain == pytest.approx(2 * massflow.RPM_PER_METRE, abs=1)

    def test_parked_cars_come_out_of_a_mapped_width(self) -> None:
        """OWNER-DECISIONS 404 (1). A 30 ft (9.14 m) curb-to-curb street with parking
        both sides: 30 - 2 x 8 ft = 14 ft, 7 ft (2.17 m) a direction, 64 a minute."""
        base = {"highway": "residential", "width": "30'"}
        assert massflow.usable_width_m(base) == pytest.approx(15 * FT, abs=0.01)
        parked = {**base, "parking:both": "lane"}
        assert massflow.usable_width_m(parked) == pytest.approx((30 * FT - 4.8) / 2, abs=0.01)
        assert massflow.capacity_rpm(parked) == 64
        # The older scheme, one side, and the values that put no car on the road.
        one_side = {**base, "parking:lane:right": "parallel"}
        assert massflow.usable_width_m(one_side) == pytest.approx((30 * FT - 2.4) / 2, abs=0.01)
        for value in ("no", "separate", "no_stopping", "on_kerb", "street_side"):
            assert massflow.usable_width_m({**base, "parking:both": value}) == pytest.approx(
                15 * FT, abs=0.01
            ), value
        angled = {
            **base,
            "oneway": "yes",
            "parking:right": "lane",
            "parking:right:orientation": "diagonal",
        }
        assert massflow.usable_width_m(angled) == pytest.approx(30 * FT - 4.5, abs=0.01)
        half = {**base, "oneway": "yes", "parking:right": "half_on_kerb"}
        assert massflow.usable_width_m(half) == pytest.approx(30 * FT - 1.2, abs=0.01)

    def test_parking_is_not_taken_from_travel_lanes(self) -> None:
        """Lanes are travel lanes: the parked cars are beside them, not in them."""
        base = {"highway": "residential", "lanes": "2"}
        assert massflow.capacity_rpm({**base, "parking:both": "lane"}) == massflow.capacity_rpm(
            base
        )

    def test_a_painted_lane_beside_parking_keeps_a_door_zone_out(self) -> None:
        base = {"highway": "secondary", "lanes": "2", "cycleway:both": "lane"}
        open_kerb = massflow.usable_width_m(base)
        beside = massflow.usable_width_m({**base, "parking:both": "lane"})
        assert open_kerb - beside == pytest.approx(massflow.DOOR_ZONE_M, abs=0.001)

    def test_paths_have_a_width_of_their_own(self) -> None:
        assert massflow.capacity_rpm({"highway": "cycleway"}) == 89
        assert massflow.capacity_rpm({"highway": "footway", "width": "3"}) == 89
        assert massflow.capacity_rpm({"highway": "pedestrian"}) > massflow.capacity_rpm(
            {"highway": "footway"}
        )

    def test_a_way_with_no_highway_or_an_unknown_class_has_none(self) -> None:
        assert massflow.capacity_rpm({}) is None
        assert massflow.capacity_rpm({"highway": "proposed"}) is None

    def test_the_figure_stays_in_the_plausible_range(self) -> None:
        widest = massflow.capacity_rpm({"highway": "primary", "oneway": "yes", "width": "39"})
        assert massflow.capacity_rpm({"highway": "steps"}) >= mass_capacity.FLOOR_RPM
        assert widest <= mass_capacity.CEILING_RPM
        assert (
            massflow.capacity_rpm({"highway": "primary", "oneway": "yes", "lanes": "14"})
            <= mass_capacity.CEILING_RPM
        )
        tiny = {"highway": "residential", "width": "3", "parking:both": "lane"}
        assert massflow.usable_width_m(tiny) == massflow.MIN_USABLE_WIDTH_M

    def test_the_bands(self) -> None:
        cases = [(0, 0), (59, 0), (60, 1), (119, 1), (120, 2), (199, 2), (200, 3), (593, 3)]
        for rpm, band in cases:
            assert massflow.band_of(rpm) == band, rpm


class TestTheDistrictsWidths:
    """OWNER-DECISIONS 404 (3): in DC the Roadway Block's lanes and widths decide the
    width; OSM is the fallback. The worked examples of reports/MASSRIDE-MAP-rev1.md."""

    OSM = {"highway": "secondary", "lanes": "4"}

    @pytest.mark.parametrize(
        ("block", "feet", "rpm"),
        [
            # Two-way, 2 + 2 lanes of 10.5 ft, parking both sides (8 ft): the parked cars
            # are recorded apart from the travel lanes, so a direction is 2 x 10.5 ft.
            (
                dc_block(
                    lanes={"ib": 2, "ob": 2},
                    way="both",
                    lane_width_ft=10.5,
                    parking_lanes=2,
                    parking_width_ft=8.0,
                ),
                21.0,
                189,
            ),
            # A DC residential street: 1 + 1 lanes of 8 ft between parked cars.
            (
                dc_block(
                    lanes={"ib": 1, "ob": 1},
                    way="both",
                    lane_width_ft=8.0,
                    parking_lanes=2,
                    parking_width_ft=8.0,
                ),
                8.0,
                72,
            ),
            # An uneven two-way block (K St NW, 2 + 3 lanes of 13 ft): the narrower.
            (dc_block(lanes={"ib": 2, "ob": 3}, way="both", lane_width_ft=13.0), 26.0, 234),
            # One-way, 3 lanes of 11 ft, no parking: every lane.
            (
                dc_block(
                    lanes={"ib": 0, "ob": 3},
                    way="one",
                    oneway_with=True,
                    lane_width_ft=11.0,
                    parking_lanes=0,
                ),
                33.0,
                297,
            ),
            # A bike lane (5 ft) beside parking each way: 10 ft lane + 5 - 3.5 ft.
            (
                dc_block(
                    lanes={"ib": 1, "ob": 1},
                    way="both",
                    lane_width_ft=10.0,
                    bike={"ib": 1, "ob": 1},
                    bike_width_ft=5.0,
                    bike_beside_parking=("ib", "ob"),
                    parking_lanes=2,
                    parking_width_ft=8.0,
                ),
                11.5,
                103,
            ),
            # The same lane at an open kerb: all 5 ft.
            (
                dc_block(
                    lanes={"ib": 1, "ob": 1},
                    way="both",
                    lane_width_ft=10.0,
                    bike={"ib": 1, "ob": 1},
                    bike_width_ft=5.0,
                ),
                15.0,
                135,
            ),
            # A protected lane is not usable (127).
            (
                dc_block(
                    lanes={"ib": 1, "ob": 1},
                    way="both",
                    lane_width_ft=10.0,
                    bike={"ib": 3, "ob": 3},
                    bike_width_ft=6.0,
                ),
                10.0,
                90,
            ),
            # Reversible lanes count as zero (405): Connecticut Ave NW's ended in 2020,
            # so 1 + 1 and 2 reversible, 10 ft, is one lane each way.
            (
                dc_block(
                    name="CONNECTICUT AVE NW",
                    lanes={"ib": 1, "ob": 1, "reversible": 2},
                    way="both",
                    lane_width_ft=10.0,
                ),
                10.0,
                90,
            ),
            # Nor does a block of another street where none is verified.
            (
                dc_block(lanes={"ib": 2, "ob": 2, "reversible": 1}, way="both", lane_width_ft=10.0),
                20.0,
                180,
            ),
            # One shared lane (DC's "bidirectional"): the ride has it.
            (dc_block(lanes={"bidirectional": 1}, way="both", lane_width_ft=16.0), 16.0, 144),
            # A one-way block with a contraflow lane: the lane against the ride is out.
            (
                dc_block(
                    lanes={"ib": 1, "ob": 0},
                    way="one",
                    lane_width_ft=12.0,
                    bike={"ib": 1, "ob": 1},
                    bike_width_ft=5.0,
                    contraflow=True,
                ),
                17.0,
                153,
            ),
        ],
    )
    def test_the_table(self, block, feet, rpm) -> None:
        width = massflow.usable_width_m(self.OSM, None, [block])
        assert width == pytest.approx(feet * FT, abs=0.005)
        assert massflow.capacity_rpm(self.OSM, None, [block]) == rpm
        assert massflow.width_source(self.OSM, [block]) == "dc"

    def test_a_block_without_a_width_falls_back_to_osm(self) -> None:
        for block in (
            dc_block(lanes={"ib": 1, "ob": 1}, way="both"),
            dc_block(lanes={"ib": 1, "ob": 1}, way="both", lane_width_ft=1.0),
            dc_block(lanes={}, way="both", lane_width_ft=10.0),
        ):
            assert massflow.usable_width_m(self.OSM, None, [block]) == pytest.approx(
                massflow.usable_width_m(self.OSM)
            )
            assert massflow.width_source(self.OSM, [block]) == "osm"
        assert massflow.capacity_rpm(self.OSM, None, []) == 198

    def test_the_narrowest_block_decides_and_another_agency_does_not(self) -> None:
        wide = dc_block(lanes={"ib": 2, "ob": 2}, way="both", lane_width_ft=11.0)
        narrow = dc_block(lanes={"ib": 1, "ob": 1}, way="both", lane_width_ft=10.0)
        unknown = dc_block(lanes={"ib": 1, "ob": 1}, way="both")
        assert massflow.usable_width_m(self.OSM, None, [wide, unknown, narrow]) == pytest.approx(
            10 * FT
        )
        baltimore = RoadFacts(agency="baltimore-centerline", lanes={"total": 2}, lane_width_ft=8.0)
        assert massflow.width_source(self.OSM, [baltimore]) == "osm"

    def test_a_path_is_never_read_from_a_block(self) -> None:
        block = dc_block(lanes={"ib": 2, "ob": 2}, way="both", lane_width_ft=11.0)
        assert massflow.capacity_rpm({"highway": "cycleway"}, None, [block]) == 89

    def test_the_way_facts_carry_their_blocks(self) -> None:
        """The rebuild hands the blocks over through `WayFacts.block_facts`, which is
        not part of the facts' identity."""
        block = dc_block(lanes={"ib": 1, "ob": 1}, way="both", lane_width_ft=9.0)
        facts = agency_roads.aggregate([("dc-1", block, True)])
        assert facts.block_facts == (block,)
        assert facts == agency_roads.aggregate([("dc-1", block, True)])
        assert massflow.usable_width_m({"highway": "residential"}, None, facts.block_facts) == (
            pytest.approx(9 * FT)
        )


def test_the_bands_are_the_front_ends() -> None:
    """massStyle.js holds its own copy of the band edges, colours and widths
    (OWNER-DECISIONS 326, 327): the one is held equal to the other."""
    style = (ROOT / "frontend" / "src" / "massStyle.js").read_text()
    mins = [int(m) for m in re.findall(r"\bmin: (\d+),", style)]
    assert tuple(mins) == massflow.BAND_FLOORS
    names = re.findall(r'name: "([a-z ]+)", short:', style)
    assert tuple(names) == massflow.BAND_NAMES
    stress_tiles = (ROOT / "src" / "core" / "stress_tiles.py").read_text()
    assert "RPM_STEP = 10" in stress_tiles
    assert all(floor % 10 == 0 for floor in massflow.BAND_FLOORS)


class TestTheColumn:
    def test_the_segment_table_has_it_as_an_optional_integer(self) -> None:
        assert MASS_WIDTH_COLUMN == "mass_usable_width_m"
        assert "mass_usable_width_m real" in SEGMENT_DDL
        # Nullable: a table, and a row, from before it has none.
        assert "mass_usable_width_m real      CHECK" in SEGMENT_DDL
        assert "NOT NULL" not in SEGMENT_DDL.split("mass_usable_width_m")[1].split("\n")[0]

    def test_the_writer_writes_it(self) -> None:
        source = (ROOT / "src" / "pipeline" / "writers.py").read_text()
        assert 'row.get("mass_usable_width_m")' in source
        assert "mass_usable_width_m)" in source


def summary(**changes) -> mass_capacity.CapacitySummary:
    base = {
        "road_rows": 1000,
        "road_with": 1000,
        "path_rows": 100,
        "path_with": 100,
        "road_min": 99,
        "road_max": 593,
        "road_median": 198.0,
    }
    return mass_capacity.CapacitySummary(**{**base, **changes})


class TestTheSentinel:
    """VALIDATE reads the column back before a promotion (as zoomed-trails'
    `assert_long_trails` does): present on nearly every road and path row, plausible."""

    def test_a_good_column_passes(self) -> None:
        assert mass_capacity.problems(summary()) == []

    def test_a_column_nobody_wrote_is_refused(self) -> None:
        found = mass_capacity.problems(summary(road_with=0, path_with=0, road_min=None))
        assert len(found) == 2 and "0 of 1000 road rows" in found[0] and "path rows" in found[1]

    def test_a_missing_share_is_refused_at_the_floor(self) -> None:
        assert mass_capacity.problems(summary(road_with=981)) == []
        assert "road rows" in mass_capacity.problems(summary(road_with=979))[0]
        assert "path rows" in mass_capacity.problems(summary(path_with=97))[0]

    def test_an_implausible_range_is_refused(self) -> None:
        assert "outside the plausible" in mass_capacity.problems(summary(road_min=10))[0]
        assert "outside the plausible" in mass_capacity.problems(summary(road_max=99_999))[0]

    def test_a_wrong_median_is_refused_and_says_units(self) -> None:
        """A model in the wrong units (a factor of 60) or with a zero constant."""
        for median in (3.3, 11_880.0, 0.0):
            found = mass_capacity.problems(summary(road_median=median))
            assert any("units or constants" in line for line in found), median

    def test_the_medians_range_is_settable_and_a_table_with_no_roads_is_not_judged(self) -> None:
        assert mass_capacity.problems(summary(road_median=600.0), median_range=(0, 5000)) == []
        empty = summary(road_rows=0, road_with=0, road_min=None, road_max=None, road_median=None)
        assert mass_capacity.problems(empty) == []


@pytest.mark.django_db(transaction=True)
class TestTheSummaryOfARealTable:
    def test_it_counts_roads_and_paths_and_reads_the_range(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        rows = [
            # (way, trail, map_class, rpm)
            (1, False, "road", 99),
            (2, False, "road", 198),
            (3, False, "road", 395),
            (4, False, "road", None),
            (5, False, "alley", 99),
            (6, True, "road", 89),
            (7, True, "road", None),
        ]
        with connection.cursor() as cursor:
            for way, trail, map_class, rpm in rows:
                cursor.execute(
                    f"INSERT INTO {staging}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule, is_trail_class, map_class, mass_usable_width_m) VALUES "
                    "(%s, 0, ST_GeomFromText('LINESTRING(-77 38.9,-77.01 38.91)', 4326), 2, 'x', "
                    "%s, %s, %s)",
                    [way, trail, map_class, None if rpm is None else rpm / massflow.RPM_PER_METRE],
                )
        got = mass_capacity.capacity_summary(staging)
        assert (got.road_rows, got.road_with) == (4, 3)
        assert (got.path_rows, got.path_with) == (2, 1)
        assert (got.road_min, got.road_max) == (99, 395)
        assert got.road_median == pytest.approx(198.0, abs=0.01)

    def test_the_column_refuses_a_width_out_of_range(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        from django.db import DatabaseError

        with connection.cursor() as cursor, pytest.raises(DatabaseError):
            cursor.execute(
                f"INSERT INTO {staging}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, mass_usable_width_m) VALUES (1, 0, "
                "ST_GeomFromText('LINESTRING(-77 38.9,-77.01 38.91)', 4326), 2, 'x', 99)"
            )


class TestTheRoutesSections:
    """`routing.stress_spans` with `capacity`: a Mass Ride's sections end where the
    capacity changes band and carry the lowest figure along them."""

    def test_without_capacity_there_is_no_rpm_key(self) -> None:
        spans = routing.stress_spans(
            [(100.0, "2", "none", None, 90), (100.0, "2", "none", None, 190)]
        )
        assert spans == [{"from_m": 0, "to_m": 200, "tier": 2, "facility": "none", "unpaved": None}]

    def test_a_stretch_outside_dc_is_its_own_section_with_no_figure(self) -> None:
        """OWNER-DECISIONS 427: Mass Ride figures are not supported outside DC."""
        spans = routing.stress_spans(
            [
                (100.0, "2", "none", None, 130, False),
                (100.0, "2", "none", None, 150, True),
                (100.0, "2", "none", None, 140, False),
            ],
            capacity=True,
        )
        assert [(s["from_m"], s["to_m"], s["rpm"], s.get("outside_dc")) for s in spans] == [
            (0, 100, 130, None),
            (100, 200, None, True),
            (200, 300, 140, None),
        ]

    def test_a_section_ends_where_the_band_changes(self) -> None:
        spans = routing.stress_spans(
            [
                (100.0, "2", "none", None, 130),
                (100.0, "2", "none", None, 190),
                (100.0, "2", "none", None, 150),
                (100.0, "2", "none", None, 90),
                (100.0, "2", "none", None, 410),
            ],
            capacity=True,
        )
        assert [(s["from_m"], s["to_m"], s["rpm"]) for s in spans] == [
            (0, 300, 130),
            (300, 400, 90),
            (400, 500, 410),
        ]

    def test_the_section_carries_its_lowest_figure_so_it_lies_in_its_band(self) -> None:
        spans = routing.stress_spans(
            [(50.0, "3", "none", None, 199), (50.0, "3", "none", None, 125)], capacity=True
        )
        assert [s["rpm"] for s in spans] == [125]
        assert massflow.band_of(spans[0]["rpm"]) == 2

    def test_avoid_is_one_section_with_no_capacity(self) -> None:
        spans = routing.stress_spans(
            [
                (100.0, "5", "none", None, 90),
                (100.0, "5", "none", None, 410),
                (100.0, "2", "none", None, 90),
            ],
            capacity=True,
        )
        assert [(s["tier"], s["rpm"]) for s in spans] == [(5, None), (2, 90)]

    def test_a_short_section_folded_away_does_not_lower_its_neighbour(self) -> None:
        spans = routing.stress_spans(
            [
                (100.0, "2", "none", None, 190),
                (5.0, "2", "none", None, 40),
                (100.0, "2", "none", None, 150),
            ],
            capacity=True,
        )
        # The pinch is under 10 m and takes its neighbours' colour: it is folded in, and the
        # section's figure is the lowest of the stretches that colour is, so it stays in its band.
        assert [(s["from_m"], s["to_m"], s["rpm"]) for s in spans] == [(0, 205, 150)]
        assert massflow.band_of(spans[0]["rpm"]) == 2

    def test_a_stretch_with_no_figure_is_its_own_section_with_null(self) -> None:
        spans = routing.stress_spans(
            [(100.0, "2", "none", None, 90), (100.0, "2", "none", None, None)], capacity=True
        )
        assert [s["rpm"] for s in spans] == [90, None]


class TestTheDistrictsAssumptions:
    """OWNER-DECISIONS 405 (reversible lanes) and 407 (3) (wide lanes with no parking)."""

    OSM = {"highway": "primary"}
    REVERSIBLE = {"ib": 1, "ob": 1, "reversible": 2}

    def width(self, block, rules=massflow.DC_RULES) -> float:
        return massflow.usable_width_m(self.OSM, None, [block], rules) / FT

    def test_reversible_lanes_count_as_zero_by_default(self) -> None:
        block = dc_block(
            name="CANAL RD NW", lanes=self.REVERSIBLE, way="both", lane_width_ft=10.0, block_key="a"
        )
        assert self.width(block) == pytest.approx(10.0, abs=0.01)
        assert not massflow.DC_RULES.verified_reversible_blocks

    def test_a_verified_block_counts_half_each_way_but_connecticut_never_does(self) -> None:
        rules = massflow.DcRules(verified_reversible_blocks=frozenset({"a", "c"}))
        canal = dc_block(
            name="CANAL RD NW", lanes=self.REVERSIBLE, way="both", lane_width_ft=10.0, block_key="a"
        )
        assert self.width(canal, rules) == pytest.approx(20.0, abs=0.01)
        other = dc_block(
            name="CANAL RD NW", lanes=self.REVERSIBLE, way="both", lane_width_ft=10.0, block_key="b"
        )
        assert self.width(other, rules) == pytest.approx(10.0, abs=0.01)
        connecticut = dc_block(
            name="CONNECTICUT AVE NW",
            lanes=self.REVERSIBLE,
            way="both",
            lane_width_ft=10.0,
            block_key="c",
        )
        assert self.width(connecticut, rules) == pytest.approx(10.0, abs=0.01)

    def test_a_block_with_only_reversible_lanes_falls_back_to_osm(self) -> None:
        block = dc_block(lanes={"ib": 0, "ob": 0, "reversible": 2}, way="both", lane_width_ft=10.0)
        assert massflow.width_source(self.OSM, [block]) == "osm"

    @pytest.mark.parametrize(
        ("lane_ft", "parking", "expected_ft"),
        [
            (16.0, 0, 11.0),  # at the threshold, no parking lane: capped
            (18.0, 0, 11.0),
            (15.9, 0, 15.9),  # under the threshold: as recorded
            (16.0, 2, 16.0),  # a parking lane is recorded: the width is the lane's
            (16.0, None, 16.0),  # parking not recorded: as recorded
            (10.0, 0, 10.0),  # a narrow lane is never widened
        ],
    )
    def test_a_wide_lane_with_no_parking_is_capped(self, lane_ft, parking, expected_ft) -> None:
        block = dc_block(
            lanes={"ib": 1, "ob": 1}, way="both", lane_width_ft=lane_ft, parking_lanes=parking
        )
        assert self.width(block) == pytest.approx(expected_ft, abs=0.01)

    def test_the_threshold_and_cap_are_settings(self) -> None:
        block = dc_block(lanes={"ib": 1, "ob": 1}, way="both", lane_width_ft=14.0, parking_lanes=0)
        rules = massflow.DcRules(wide_lane_ft=13.0, wide_lane_cap_ft=12.0)
        assert self.width(block, rules) == pytest.approx(12.0, abs=0.01)
        from config import settings

        assert (settings.MASS_RIDE_DC_WIDE_LANE_FT, settings.MASS_RIDE_DC_WIDE_LANE_CAP_FT) == (
            massflow.DC_RULES.wide_lane_ft,
            massflow.DC_RULES.wide_lane_cap_ft,
        )
        assert settings.MASS_RIDE_DC_ENDED_REVERSIBLE_STREETS == (
            massflow.DC_RULES.ended_reversible_streets
        )
