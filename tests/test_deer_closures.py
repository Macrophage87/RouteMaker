"""The parks' deer-management closures as "Check before you go" notices (v0.12.3,
`routemaker.deer_closures`): on a route that runs along the closed roads or trails, and only
while the ride is inside a closure window (the owner, 2026-10-25: "Make sure it's only for the
duration of the closure")."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from routemaker import dc_closures as dc
from routemaker import deer_closures as deer
from routemaker import workzones as wz
from routemaker.ridetime import ZONE


def local(*args) -> datetime:
    return datetime(*args, tzinfo=ZONE).astimezone(UTC)


def along(area: str, index: int = 0) -> list[tuple[float, float]]:
    """A route that rides the area's `index`th longest closed way end to end."""
    lines = sorted(deer.ways()[area].lines, key=len, reverse=True)
    return list(lines[index])


def found(coordinates, at: datetime, now: datetime | None = None) -> list[dc.Notice]:
    return dc.notices_along(deer.notices(now or at), coordinates, at)


BEACH_DRIVE = "rocr-deer"
SLIGO = "moco-P61"
LITTLE_BENNETT = "moco-G06"


class TestRockCreek:
    def test_a_night_ride_on_beach_drive_is_told_it_may_close(self) -> None:
        at = local(2026, 12, 1, 20, 0)
        [notice] = found(along(BEACH_DRIVE), at)
        assert notice.source == deer.NPS and notice.area == BEACH_DRIVE
        assert "may close" in notice.title
        assert dc.notice_when_text(notice, at, False) == "today 6:45 pm to tomorrow 4 am"
        assert dc.area_of(notice.area).name == "Rock Creek Park"

    @pytest.mark.parametrize(
        "at",
        [
            local(2026, 12, 1, 12, 0),  # midday: outside the hours
            local(2026, 12, 2, 4, 30),  # after 4 am
            local(2026, 6, 10, 21, 0),  # out of season
            local(2026, 11, 9, 21, 0),  # the night before the season
        ],
    )
    def test_only_inside_the_closure_hours_and_season(self, at) -> None:
        assert found(along(BEACH_DRIVE), at) == []

    def test_a_ride_starting_just_before_it_closes_is_told(self) -> None:
        assert found(along(BEACH_DRIVE), local(2026, 12, 1, 18, 0))
        assert not found(along(BEACH_DRIVE), local(2026, 12, 1, 17, 30))

    def test_this_winter_is_said_as_expected_last_winter_as_posted(self) -> None:
        [this] = found(along(BEACH_DRIVE), local(2026, 12, 1, 20, 0))
        [last] = found(along(BEACH_DRIVE), local(2025, 12, 1, 20, 0))
        assert "expected" in this.text and "expected" not in last.text

    def test_a_route_that_only_crosses_is_not_told(self) -> None:
        line = along(BEACH_DRIVE)
        lon, lat = line[len(line) // 2]
        across = [(lon - 0.001, lat), (lon + 0.001, lat)]
        assert found(across, local(2026, 12, 1, 20, 0)) == []

    def test_a_route_elsewhere_is_not_told(self) -> None:
        downtown = [(-77.03, 38.90), (-77.02, 38.90)]
        assert found(downtown, local(2026, 12, 1, 20, 0)) == []


class TestMontgomeryParks:
    def test_sharpshooting_closes_a_park_on_weeknights_sunset_to_sunrise(self) -> None:
        at = local(2027, 1, 20, 21, 0)  # a Wednesday
        [notice] = found(along(SLIGO), at)
        assert notice.source == deer.MOCO and "closed at night" in notice.title
        assert notice.title.startswith("Sligo Creek Stream Valley Park Unit 5")
        assert notice.url == deer.MOCO_URL

    @pytest.mark.parametrize(
        "at",
        [
            local(2027, 1, 23, 21, 0),  # a Saturday night
            local(2027, 1, 20, 13, 0),  # a weekday afternoon
            local(2027, 1, 14, 21, 0),  # before Jan 15
            local(2027, 4, 1, 21, 0),  # after Mar 31
        ],
    )
    def test_not_on_weekends_by_day_or_out_of_season(self, at) -> None:
        assert found(along(SLIGO), at) == []

    def test_a_firearms_hunt_closes_the_park_all_day(self) -> None:
        at = local(2026, 12, 8, 13, 0)
        [notice] = found(along(LITTLE_BENNETT), at)
        assert "all day" in notice.title
        assert dc.notice_when_text(notice, at, False) == "All day today"
        assert found(along(LITTLE_BENNETT), local(2026, 12, 10, 13, 0)) == []

    def test_black_hill_and_bucklodge_are_hunted_together(self) -> None:
        days = {
            w.area
            for w in deer.windows(date(2026, 10, 29), date(2026, 10, 29))
            if w.source == deer.MOCO
        }
        assert days == {"moco-G07", "moco-S12"}


def test_sunrise_and_sunset_in_january() -> None:
    sunrise, sunset = deer.sun_times(date(2027, 1, 15))
    # Washington DC, Jan 15: sunrise about 7:25 am, sunset about 5:13 pm (EST); to a few minutes.
    assert abs((sunrise - local(2027, 1, 15, 7, 25)).total_seconds()) < 8 * 60
    assert abs((sunset - local(2027, 1, 15, 17, 14)).total_seconds()) < 8 * 60


def test_every_area_in_the_file_is_named_and_marked() -> None:
    areas = deer.areas()
    assert set(areas) == set(deer.ways())
    assert BEACH_DRIVE in areas and SLIGO in areas and LITTLE_BENNETT in areas
    for area in areas.values():
        assert area.name and area.point and area.url


def test_notices_are_made_for_the_days_ahead_only() -> None:
    now = local(2026, 11, 20, 10, 0)
    made = deer.notices(now)
    assert made and all(n.end > now for n in made)
    assert max(n.start for n in made) < local(2026, 12, 7, 0, 0)


def test_the_sources_are_named() -> None:
    for source in deer.SOURCES:
        assert wz.SOURCES[source]


def test_a_notice_survives_the_stored_copy() -> None:
    [notice] = found(along(BEACH_DRIVE), local(2026, 12, 1, 20, 0))
    assert dc.Notice.from_json(json.loads(json.dumps(notice.to_json()))) == notice


def test_a_route_answer_carries_the_notice_on_its_map_and_in_its_description() -> None:
    from core import workzones as core_zones

    at = local(2026, 12, 1, 20, 0)
    plan = wz.PlanZones(status={"md": "current"}, at=at, notices=deer.notices(at))
    body = {
        "geometry": {"coordinates": along(BEACH_DRIVE)},
        "distance_m": 1000.0,
        "description": [],
    }
    out = core_zones.with_work_zones(body, plan, now=at)
    [row] = out["work_zones"]["notices"]
    assert row["area_name"] == "Rock Creek Park" and row["point"]
    assert row["when_text"] == "today 6:45 pm to tomorrow 4 am"
    assert row["source_name"] == "NPS, Rock Creek Park deer management"
    assert any("Check before you go" in str(entry) for entry in out["description"])
    # By day, nothing.
    noon = local(2026, 12, 1, 12, 0)
    plan = wz.PlanZones(status={"md": "current"}, at=noon, notices=deer.notices(noon))
    body = {
        "geometry": {"coordinates": along(BEACH_DRIVE)},
        "distance_m": 1000.0,
        "description": [],
    }
    assert core_zones.with_work_zones(body, plan, now=noon)["work_zones"]["notices"] == []


def test_the_last_night_and_the_night_the_clocks_change() -> None:
    assert found(along(BEACH_DRIVE), local(2027, 3, 31, 23, 0))
    assert found(along(BEACH_DRIVE), local(2027, 4, 1, 3, 30))
    assert not found(along(BEACH_DRIVE), local(2027, 4, 1, 20, 0))
    # Mar 14, 2027 springs forward at 2 am: the window still opens at 6:45 pm local.
    [notice] = found(along(BEACH_DRIVE), local(2027, 3, 14, 19, 0))
    assert notice.start == local(2027, 3, 14, 18, 45) and notice.end == local(2027, 3, 15, 4, 0)


def test_sunday_nights_are_not_sharpshooting_nights() -> None:
    assert found(along(SLIGO), local(2027, 1, 24, 21, 0)) == []  # a Sunday
    assert found(along(SLIGO), local(2027, 1, 22, 21, 0))  # a Friday


def test_back_to_back_hunt_days_are_said_once() -> None:
    # 11:30 pm on Dec 8: the Dec 9 hunt's window is within its hour's lead.
    assert len(found(along(LITTLE_BENNETT), local(2026, 12, 8, 23, 30))) == 1


def test_the_route_cache_turns_over_when_a_notice_comes_in() -> None:
    made = deer.notices(local(2026, 12, 1, 12, 0))
    assert local(2026, 12, 1, 17, 45) in deer.moments(made)
    assert local(2026, 12, 2, 4, 0) in deer.moments(made)


def test_the_api_takes_the_new_sources() -> None:
    from core import workzones as core_zones
    from core.api import ClosureNoticeOut

    at = local(2026, 12, 8, 13, 0)
    for notice in (
        *found(along(BEACH_DRIVE), local(2026, 12, 1, 20, 0)),
        *found(along(LITTLE_BENNETT), at),
    ):
        ClosureNoticeOut(**core_zones.notice_row(notice, at, False))


def test_the_assumed_season_and_the_end_of_the_tables_are_reminders() -> None:
    """Audit 2026-10-29: nothing prompted a check of the assumed Rock Creek season, or next
    season's dates once these run out (`scripts/ddot_advisories.py watch` prints these)."""
    assert deer.check_due(date(2026, 10, 20)) == []
    (assumed,) = deer.check_due(date(2026, 10, 30))
    assert "assumed" in assumed and "2026-11-10" in assumed
    assert deer.check_due(date(2027, 2, 15)) == []
    (end,) = deer.check_due(date(2027, 3, 5))
    assert "end 2027-03-31" in end
