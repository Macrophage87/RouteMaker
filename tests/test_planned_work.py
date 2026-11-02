"""Planned work for Plan's Potential closures layer (v0.17.0, `routemaker.planned_work`):
DDOT's ProTrack+ projects, DC Water's work zones and WSSC Water's water mains. Pure parsing,
on made-up records in each layer's shape (checked live 2026-11-01)."""

from __future__ import annotations

from datetime import UTC, datetime

from routemaker import planned_work as pw
from routemaker import workzones as wz

NOW = datetime(2026, 11, 1, 14, 0, tzinfo=UTC)


def ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


LINE = {"type": "LineString", "coordinates": [[-77.0, 38.9], [-77.0, 38.901]]}


def protrack(**props) -> dict:
    base = {
        "ObjectID": 7,
        "ProjectName": "Pavement Restoration",
        "ProjectStatus": "Under Construction",
        "PrimaryWorkType": "Pavement Resurface/Restoration",
        "RouteName": "3RD ST NW",
        "FromStreet": "E ST NW",
        "ToStreet": "F ST NW",
        "ActualStartDate": ms(2026, 10, 1),
        "EstimatedCompletionDate": ms(2026, 12, 1),
    }
    return {"type": "Feature", "properties": {**base, **props}, "geometry": LINE}


class TestProtrack:
    def test_a_project_under_construction_is_a_possible_closure_on_its_block(self) -> None:
        (zone,) = pw.parse_protrack({"features": [protrack()]}, NOW)
        assert zone.source == "protrack" and wz.possible(zone)
        assert zone.title == "3rd St NW, E St NW to F St NW: pavement resurface/restoration"
        assert zone.end == datetime(2026, 12, 1, tzinfo=UTC)

    def test_past_projects_still_marked_under_construction_are_left_out(self) -> None:
        """The layer keeps 2017 projects "Under Construction": the date decides."""
        old = protrack(EstimatedCompletionDate=ms(2020, 3, 27))
        assert pw.parse_protrack({"features": [old]}, NOW) == []

    def test_work_that_leaves_the_road_open_is_left_out(self) -> None:
        sidewalk = protrack(PrimaryWorkType="Sidewalk Construction")
        alley = protrack(PrimaryWorkType="Alley Restoration")
        assert pw.parse_protrack({"features": [sidewalk, alley]}, NOW) == []

    def test_streetscape_work_is_kept_though_it_contains_tree(self) -> None:
        """"Streetscape" rebuilds the road; only tree work leaves it as it was."""
        streetscape = protrack(PrimaryWorkType="Streetscape")
        trees = protrack(PrimaryWorkType="Tree Planting")
        (zone,) = pw.parse_protrack({"features": [streetscape, trees]}, NOW)
        assert zone.title.endswith("streetscape")


class TestDcWater:
    def test_a_work_zone_is_placed_by_its_middle(self) -> None:
        feature = {
            "properties": {
                "OBJECTID": 93207,
                "LocationDescription": "400 Block Ridge Rd SE",
                "ActivityStart": ms(2026, 6, 9),
                "ActivityFinish": ms(2026, 11, 20),
                "ActivityType": "Road concrete base and paving",
                "ProjectLongDescription": "Laying a concrete base before paving the road",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-77.0, 38.9], [-77.002, 38.9], [-77.002, 38.902], [-77.0, 38.9]]],
            },
        }
        (work,) = pw.parse_dcwater({"features": [feature]}, NOW)
        assert work.title == "400 Block Ridge Rd SE: DC Water work"
        zone = pw.area_zone(work, [[-77.001, 38.9], [-77.001, 38.901]])
        assert zone.zone_id == "dcwater-93207" and wz.possible(zone)

    def test_finished_work_is_left_out(self) -> None:
        done = {
            "properties": {"OBJECTID": 1, "ActivityFinish": ms(2026, 10, 1)},
            "geometry": {"type": "Polygon", "coordinates": [[[-77.0, 38.9], [-77.0, 38.91]]]},
        }
        assert pw.parse_dcwater({"features": [done]}, NOW) == []


class TestWssc:
    def wssc(self, **props) -> dict:
        base = {
            "OBJECTID": 5,
            "PROJECT_NAME": "BR6315A17 - Montgomery Knolls WMR",
            "PROJECT_STATUS": "Construction Started",
            "EST_CONSTR_START_DATE": ms(2025, 4, 29),
            "EST_CONSTR_END_DATE": ms(2027, 4, 14),
        }
        geometry = {"type": "MultiLineString", "coordinates": [LINE["coordinates"]] * 2}
        return {"properties": {**base, **props}, "geometry": geometry}

    def test_a_main_under_construction_is_one_zone_a_pipe_line(self) -> None:
        zones = pw.parse_wssc({"features": [self.wssc()]}, NOW)
        assert [z.zone_id for z in zones] == ["wssc-5-0", "wssc-5-1"]
        assert all(wz.possible(z) and z.source == "wssc" for z in zones)

    def test_completed_projects_are_left_out(self) -> None:
        """The layer keeps "Construction Completed" and "Restoration Completed" projects."""
        done = [
            self.wssc(PROJECT_STATUS="Construction Completed"),
            self.wssc(PROJECT_STATUS="Restoration Completed"),
        ]
        assert pw.parse_wssc({"features": done}, NOW) == []

    def test_no_contact_details_are_kept(self) -> None:
        """The layer also holds contract managers' names, phones and emails: never asked for."""
        from core import closure_sources as cs

        assert "CONTRACT_MGR" not in cs.PLANNED_FIELDS[cs.WSSC]
        assert "PHONE" not in cs.PLANNED_FIELDS[cs.WSSC]


def test_planned_work_is_flagged_only_and_says_so() -> None:
    (zone,) = pw.parse_protrack({"features": [protrack()]}, NOW)
    assert wz.when_text(zone, NOW, False, possible=True).startswith(
        "Planned work may close it some day"
    )


def test_dc_water_dates_are_whole_days_in_dc() -> None:
    """Review: "finish Nov 7" is stored as Nov 7 00:00 UTC (7 pm Nov 6 in DC); it lasts
    through Nov 7, and the card says so."""
    feature = {
        "properties": {
            "OBJECTID": 2,
            "LocationDescription": "1300 29th St NW",
            "ActivityStart": ms(2026, 11, 2),
            "ActivityFinish": ms(2026, 11, 7),
            "ActivityType": "WATER OUTAGE 11/5/2026",
            "ProjectLongDescription": "Water Main Connection",
        },
        "geometry": {"type": "Polygon", "coordinates": [[[-77.0, 38.9], [-77.0, 38.91]]]},
    }
    (work,) = pw.parse_dcwater({"features": [feature]}, NOW)
    assert work.start == datetime(
        2026, 11, 2, 5, tzinfo=UTC
    )  # midnight EST (clocks went back Nov 1)
    assert work.end == datetime(2026, 11, 8, 5, tzinfo=UTC)  # the midnight after Nov 7, EST
    assert work.description.startswith("WATER OUTAGE 11/5/2026")
    zone = pw.area_zone(work, [[-77.0, 38.9], [-77.0, 38.901]])
    assert "through" in wz.when_text(zone, NOW, False, possible=True)
    assert "Nov 7" in wz.when_text(zone, NOW, False, possible=True)


def test_wssc_asks_for_exactly_these_fields() -> None:
    from core import closure_sources as cs

    assert cs.PLANNED_FIELDS[cs.WSSC].split(",") == [
        "OBJECTID",
        "FULL_PROJECT_ID",
        "PROJECT_NAME",
        "PROJECT_STATUS",
        "EST_CONSTR_START_DATE",
        "EST_CONSTR_END_DATE",
    ]


def test_planned_work_never_reaches_go_or_a_ride() -> None:
    (zone,) = pw.parse_protrack({"features": [protrack()]}, NOW)
    points = [[-77.0005, 38.8995], [-77.0005, 38.9015]]
    plan = wz.for_plan([zone], NOW, points, {}, NOW, now_only=True)
    assert not plan.possible and not plan.excluded and not plan.unexcluded
    flagged = wz.for_plan([zone], NOW, points, {}, NOW)
    assert flagged.possible == [zone] and not flagged.excluded and not flagged.exclude
