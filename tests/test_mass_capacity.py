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
from routemaker import massflow

ROOT = Path(__file__).resolve().parent.parent


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
        assert massflow.LANE_WIDTH_M == pytest.approx(11 * 0.3048, abs=0.01)

    def test_the_plans_worked_example_is_about_200_on_22_ft(self) -> None:
        """A two-lane road of about 22 ft (6.7 m) usable: about 200 a minute."""
        assert massflow.capacity_rpm({"highway": "tertiary", "width": "22'"}) == 198
        assert massflow.capacity_rpm({"highway": "residential"}) == 198

    @pytest.mark.parametrize(
        ("tags", "lanes", "expected"),
        [
            # Tagged lanes count across both directions.
            ({"highway": "primary", "lanes": "4"}, None, 396),
            ({"highway": "primary", "lanes": "6"}, None, 593),
            (
                {"highway": "primary", "lanes": "2", "lanes:forward": "2", "lanes:backward": "3"},
                None,
                495,
            ),
            # The classifier's through lanes a direction, where no `lanes` is tagged.
            ({"highway": "secondary"}, 2, 396),
            ({"highway": "secondary", "oneway": "yes"}, 2, 198),
            # The class default: a one-way street is one lane, an alley one lane.
            ({"highway": "residential", "oneway": "yes"}, None, 99),
            ({"highway": "service"}, None, 99),
            ({"highway": "primary"}, None, 396),
            # A mapped carriageway width stands for the lanes and the paint.
            ({"highway": "primary", "width": "12", "lanes": "4"}, None, 354),
            ({"highway": "primary", "width": "garbage", "lanes": "2"}, None, 198),
            ({"highway": "primary", "width": "300", "lanes": "2"}, None, 198),
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
        assert painted - plain == pytest.approx(2 * 1.5 * massflow.RPM_PER_METRE, abs=1)
        assert one_side - plain == pytest.approx(1.5 * massflow.RPM_PER_METRE, abs=1)
        assert protected == plain, "a protected lane is not usable width (127)"

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
        assert wide - plain == pytest.approx(2 * 2 * massflow.RPM_PER_METRE, abs=1)

    def test_parking_is_not_added(self) -> None:
        """Parked cars are in the lane; a pack cannot count on the space (a proposal)."""
        base = {"highway": "residential", "lanes": "2"}
        assert massflow.capacity_rpm({**base, "parking:both": "lane"}) == massflow.capacity_rpm(
            base
        )

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
        widest = massflow.capacity_rpm({"highway": "primary", "width": "39"})
        assert massflow.capacity_rpm({"highway": "steps"}) >= mass_capacity.FLOOR_RPM
        assert widest <= mass_capacity.CEILING_RPM
        assert (
            massflow.capacity_rpm({"highway": "primary", "lanes": "12"})
            <= mass_capacity.CEILING_RPM
        )

    def test_the_bands(self) -> None:
        cases = [(0, 0), (59, 0), (60, 1), (119, 1), (120, 2), (199, 2), (200, 3), (593, 3)]
        for rpm, band in cases:
            assert massflow.band_of(rpm) == band, rpm


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
