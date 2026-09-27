"""The owner's four facility classes (routemaker.facility), and the ride times.

Properties, not sentences: which class a tagging lands in, in the owner's
order, and which ride times a timed closure covers.
"""

from datetime import datetime

import pytest

from routemaker import ridetime
from routemaker.facility import (
    Facility,
    beside_separate_roads,
    car_free_when,
    closed_to_motor_traffic,
    facility,
)

P, PR, L, N = Facility.PATH, Facility.PROTECTED, Facility.LANE, Facility.NONE


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "cycleway"}, P),
        ({"highway": "cycleway", "bicycle": "designated"}, P),
        ({"highway": "path"}, P),
        ({"highway": "path", "bicycle": "yes", "foot": "designated"}, P),
        ({"highway": "footway", "bicycle": "designated"}, P),
        # A footway a bicycle may not ride is no facility for a bicycle.
        ({"highway": "footway"}, N),
        ({"highway": "path", "bicycle": "no"}, N),
        ({"highway": "cycleway", "bicycle": "dismount"}, N),
        ({"highway": "path", "access": "private"}, N),
        ({"highway": "steps", "bicycle": "yes"}, N),
        # Sidewalks: a signed sidepath is protected; a sidewalk a bike may use is not a facility.
        ({"highway": "footway", "footway": "sidewalk", "bicycle": "designated"}, PR),
        ({"highway": "footway", "footway": "sidewalk", "bicycle": "yes"}, N),
        ({"highway": "cycleway", "is_sidepath": "yes"}, PR),
        ({"highway": "cycleway", "separation:left": "flex_post;bump"}, PR),
        ({"highway": "cycleway", "separation:left": "no"}, P),
        # Roads.
        ({"highway": "residential"}, N),
        ({"highway": "residential", "cycleway": "shared_lane"}, N),
        ({"highway": "secondary", "cycleway:both": "share_busway"}, N),
        ({"highway": "tertiary", "cycleway:both": "lane"}, L),
        ({"highway": "tertiary", "cycleway:both": "lane", "cycleway:both:buffer": "yes"}, L),
        ({"highway": "tertiary", "cycleway:both": "lane", "cycleway:separation": "flex_post"}, PR),
        ({"highway": "tertiary", "cycleway:both": "lane", "cycleway:separation": "solid_line"}, L),
        ({"highway": "primary", "cycleway:both": "track"}, PR),
        ({"highway": "primary", "oneway": "yes", "cycleway:left": "track"}, PR),
        # The worst direction: a lane one way only on a two-way street is none.
        ({"highway": "secondary", "cycleway:right": "lane"}, N),
        # A road that points at a separately mapped facility is scored as the roadway.
        ({"highway": "primary", "cycleway:both": "separate"}, N),
        ({"highway": "motorway", "cycleway": "track"}, N),
        # Closed to motor traffic outright.
        ({"highway": "living_street", "motor_vehicle": "no", "bicycle": "designated"}, P),
        ({"highway": "service", "motor_vehicle": "no", "bicycle": "yes"}, P),
        ({"highway": "service", "motor_vehicle": "no"}, P),
        ({"highway": "tertiary", "access": "no", "bicycle": "yes"}, P),
        ({"highway": "service", "access": "no"}, N),
        ({"highway": "service", "motor_vehicle": "no", "bicycle": "no"}, N),
        ({"highway": "service", "motor_vehicle": "no", "access": "private"}, N),
        ({"highway": "unclassified", "vehicle": "no"}, N),
        ({"highway": "unclassified", "vehicle": "no", "bicycle": "yes"}, P),
    ],
)
def test_facility_class(tags, expected):
    assert facility(tags) is expected


def test_the_classes_are_the_owners_four_in_his_order():
    assert [f.value for f in Facility] == ["path", "protected", "lane", "none"]


def test_a_timed_closure_is_not_a_path_on_its_own():
    beach = {
        "highway": "tertiary",
        "bicycle": "designated",
        "motor_vehicle:conditional": "no @ (Fr 09:00-Su 16:00)",
    }
    assert facility(beach) is N
    assert not closed_to_motor_traffic(beach)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Beach Drive, Montgomery County (way 771171205).
        ("no @ (Fr 09:00-Su 16:00)", {"weekend"}),
        # Sligo Creek Parkway.
        ("no @ (Fr 09:00-24:00; Sa; Su 00:00-18:00)", {"weekend"}),
        # Beach Drive NW (way 435217294).
        ("no @ (PH 07:00-19:00; Sa 07:00-24:00; Su 00:00-19:00)", {"weekend"}),
        ("no @ (Sa-Su 00:00-24:00)", {"weekend"}),
        # Little Falls Parkway: Sunday 11:00 is inside, so the whole weekend is.
        ("no @ (Sa 07:00-Su 16:00)", {"weekend"}),
        # Closed only Sunday afternoon: a Saturday ride is on the open road.
        ("no @ (Su 12:00-18:00)", set()),
        # Evening rush only: not every rush instant, so not rush.
        ("no @ (Mo-Fr 16:00-19:00)", set()),
        ("no @ (Mo-Fr 07:00-10:00,16:00-19:00)", {"weekday_rush"}),
        ("no @ (Mo-Su 00:00-24:00)", {"weekend", "weekday_rush", "weekday_offpeak"}),
        # Local traffic only is not car-free.
        ("destination @ (Sa 07:00-Su 19:00, PH)", set()),
        # A condition this reader cannot read closes nothing.
        ("no @ (Oct 1 - Jan 15)", set()),
        ("no @ (sunset-sunrise)", set()),
        (None, set()),
    ],
)
def test_car_free_when(value, expected):
    tags = {"highway": "tertiary", "bicycle": "designated"}
    if value:
        tags["motor_vehicle:conditional"] = value
    assert car_free_when(tags) == frozenset(expected)


def test_car_free_when_needs_a_bicycle_and_a_road():
    closed = "no @ (Sa-Su)"
    assert car_free_when({"highway": "tertiary", "motor_vehicle:conditional": closed}) == {
        "weekend"
    }
    assert not car_free_when(
        {"highway": "tertiary", "bicycle": "no", "motor_vehicle:conditional": closed}
    )
    assert not car_free_when({"highway": "cycleway", "motor_vehicle:conditional": closed})


@pytest.mark.parametrize(
    ("moment", "when"),
    [
        (datetime(2026, 9, 26, 10, 0, tzinfo=ridetime.ZONE), "weekend"),  # Saturday
        (datetime(2026, 9, 28, 7, 0, tzinfo=ridetime.ZONE), "weekday_rush"),  # Monday
        (datetime(2026, 9, 28, 9, 59, tzinfo=ridetime.ZONE), "weekday_rush"),
        (datetime(2026, 9, 28, 10, 0, tzinfo=ridetime.ZONE), "weekday_offpeak"),
        (datetime(2026, 9, 28, 6, 59, tzinfo=ridetime.ZONE), "weekday_offpeak"),
        (datetime(2026, 9, 28, 16, 0, tzinfo=ridetime.ZONE), "weekday_rush"),
        (datetime(2026, 9, 28, 19, 0, tzinfo=ridetime.ZONE), "weekday_offpeak"),
        # Labor Day 2026 is Monday 7 September; Thanksgiving is 26 November.
        (datetime(2026, 9, 7, 8, 0, tzinfo=ridetime.ZONE), "weekend"),
        (datetime(2026, 11, 26, 8, 0, tzinfo=ridetime.ZONE), "weekend"),
        # Independence Day 2026 falls on a Saturday and is observed Friday 3 July.
        (datetime(2026, 7, 3, 8, 0, tzinfo=ridetime.ZONE), "weekend"),
    ],
)
def test_when_at(moment, when):
    assert ridetime.when_at(moment) == when


def test_representative_time_is_the_next_such_instant():
    now = datetime(2026, 9, 27, 8, 0, tzinfo=ridetime.ZONE)  # Sunday
    assert ridetime.representative_time("weekend", now) == "2026-10-03T09:00"
    assert ridetime.representative_time("weekday_rush", now) == "2026-09-29T08:00"
    assert ridetime.representative_time("weekday_offpeak", now) == "2026-09-29T12:00"
    for when in ridetime.WHENS:
        day, hour, minute = ridetime.REPRESENTATIVE_TIME[when]
        # The router's instant is one of the instants the setting stands for.
        assert (day, hour * 60 + minute) in ridetime.INSTANTS[when]
        # And it is in the setting it stands for.
        stamp = datetime.fromisoformat(ridetime.representative_time(when, now))
        assert ridetime.when_at(stamp.replace(tzinfo=ridetime.ZONE)) == when


def _line(lon, lat, n=6, dlon=0.0002):
    return [(lon + i * dlon, lat) for i in range(n)]


def test_a_cycleway_along_a_road_that_says_separate_is_protected():
    road = (1, {"highway": "primary", "cycleway:right": "separate"}, _line(-77.03, 38.90))
    # 11 m north of the road's centreline.
    beside = (2, {"highway": "cycleway"}, _line(-77.03, 38.9001))
    # 110 m north: a trail, not the lane.
    away = (3, {"highway": "cycleway"}, _line(-77.03, 38.901))
    plain_road = (4, {"highway": "primary"}, _line(-77.03, 38.905))
    by_plain = (5, {"highway": "cycleway"}, _line(-77.03, 38.9051))
    found = beside_separate_roads([road, beside, away, plain_road, by_plain])
    assert found == {2}
    assert facility(beside[1], beside_separate_road=True) is PR


def test_beside_needs_most_of_the_way():
    road = (1, {"highway": "primary", "cycleway:both": "separate"}, _line(-77.03, 38.90, n=3))
    # Crosses the road and runs off: two of eight vertices near it.
    crossing = (2, {"highway": "cycleway"}, [(-77.0298, 38.8999 + i * 0.0003) for i in range(8)])
    assert beside_separate_roads([road, crossing]) == set()
