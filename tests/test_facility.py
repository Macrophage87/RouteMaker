"""The owner's four facility classes (routemaker.facility), and the ride times.

Properties, not sentences: which class a tagging lands in, in the owner's
order, and which ride times a timed closure covers.
"""

from datetime import UTC, datetime

import pytest

from routemaker import facility as facility_rules
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
        # A crossing, or the island in one, is part of the street it crosses.
        ({"highway": "footway", "footway": "crossing", "bicycle": "yes"}, N),
        ({"highway": "footway", "footway": "traffic_island", "bicycle": "permissive"}, N),
        ({"highway": "path", "path": "crossing", "bicycle": "yes"}, N),
        ({"highway": "cycleway", "cycleway": "traffic_island"}, N),
        ({"highway": "footway", "footway": "traffic_island", "bicycle": "designated"}, N),
        # A crossing signed for bicycles carries its trail across the road.
        ({"highway": "cycleway", "cycleway": "crossing"}, P),
        ({"highway": "footway", "footway": "crossing", "bicycle": "designated"}, P),
        ({"highway": "path", "path": "crossing", "bicycle": "designated"}, P),
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
        # motorcar=no alone closes a road too: the C&O Canal towpath's service
        # road, way 1379394513 (mutation review r1, F4).
        ({"highway": "service", "motorcar": "no"}, P),
        # motor_vehicle=no with vehicle=no bars the bicycle as well (F23).
        ({"highway": "service", "motor_vehicle": "no", "vehicle": "no"}, N),
        ({"highway": "service", "motor_vehicle": "no", "vehicle": "no", "bicycle": "yes"}, P),
        # A sidewalk is one whichever key maps it (F9).
        ({"highway": "path", "path": "sidewalk", "bicycle": "designated"}, PR),
        ({"highway": "cycleway", "cycleway": "sidewalk"}, N),
        ({"highway": "path", "path": "sidewalk", "bicycle": "yes"}, N),
        # A kerb is physical separation; paint is not (F15).
        ({"highway": "cycleway", "separation": "kerb"}, PR),
        ({"highway": "cycleway", "separation:right": "solid_line;kerb"}, PR),
        ({"highway": "cycleway", "separation": "solid_line"}, P),
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
        # Morning rush only: the evening instant is open (R21).
        ("no @ (Mo-Fr 07:00-10:00)", set()),
        # An interval's end is outside it: 08:00 and 17:30 are the rush
        # instants, and a closure ending at them does not cover them (R20).
        ("no @ (Mo-Fr 06:00-08:00,16:00-17:30)", set()),
        ("no @ (Mo-Fr 06:00-08:01,16:00-17:31)", {"weekday_rush"}),
        # Saturday alone is not the weekend: Sunday's instant is open (R11).
        ("no @ (Sa 00:00-24:00)", set()),
        ("no @ (Sa)", set()),
        # A span that wraps the week, Friday evening to Monday morning (R12).
        ("no @ (Fr 19:00-Mo 06:00)", {"weekend"}),
        # A day's times that end where they start run into the next day (R14).
        ("no @ (Sa-Su 07:00-07:00)", {"weekend"}),
        # A rule and the public holidays after it, as way 6053480 has it (R18).
        ("no @ (Sa 07:00-Su 19:00, PH)", {"weekend"}),
        # Times with no days are every day: Clark Place NW (the round-1
        # correctness note). Both rush instants are inside; Sunday 11:00 and
        # noon are not.
        ("no @ (06:00-10:15,14:45-19:15)", {"weekday_rush"}),
        ("no @ (08:00-20:00)", {"weekend", "weekday_rush"}),
        ("no @ (00:00-24:00)", {"weekend", "weekday_rush", "weekday_offpeak"}),
        # One unreadable branch makes the value unreadable, in either order
        # and whatever the readable one covers (correctness review, round 3, R19).
        ("no @ (Sa-Su); no @ (sunset-sunrise)", set()),
        ("no @ (sunset-sunrise); no @ (Sa-Su)", set()),
        ("no @ (Mo-Su 00:00-24:00); no @ (sunset-sunrise)", set()),
        # A setting closed by the second `no` branch alone: the branches are a
        # union (the re-check of 152261f, R2). The morning rush branch does not
        # cover 17:30, so rush is open.
        ("no @ (Mo-Fr 07:00-10:00); no @ (Sa-Su)", {"weekend"}),
        # Only the `no` branches are read.
        ("destination @ (sunset-sunrise); no @ (Sa-Su)", {"weekend"}),
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
    assert car_free_when({"highway": "tertiary", "motorcar:conditional": closed}) == {"weekend"}
    # A road bicycles may not use at all is never a path for them (F7).
    for highway in ("motorway", "motorway_link"):
        assert not car_free_when({"highway": highway, "motor_vehicle:conditional": closed})
    assert not car_free_when({"motor_vehicle:conditional": closed})
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
        # Evening rush starts at 16:00, not before (mutation review r1, R2).
        (datetime(2026, 9, 28, 15, 30, tzinfo=ridetime.ZONE), "weekday_offpeak"),
        (datetime(2026, 9, 28, 15, 59, tzinfo=ridetime.ZONE), "weekday_offpeak"),
        # Juneteenth 2026 is Friday 19 June (R3).
        (datetime(2026, 6, 19, 8, 0, tzinfo=ridetime.ZONE), "weekend"),
        # A holiday on a Sunday is observed on the Monday: 4 July 2027 (R5).
        (datetime(2027, 7, 5, 8, 0, tzinfo=ridetime.ZONE), "weekend"),
        (datetime(2027, 7, 2, 8, 0, tzinfo=ridetime.ZONE), "weekday_rush"),
        # Memorial Day is the last Monday of May: 25 May 2026, 31 May 2027 (R7).
        (datetime(2026, 5, 25, 8, 0, tzinfo=ridetime.ZONE), "weekend"),
        (datetime(2026, 5, 18, 8, 0, tzinfo=ridetime.ZONE), "weekday_rush"),
        (datetime(2027, 5, 31, 8, 0, tzinfo=ridetime.ZONE), "weekend"),
        (datetime(2027, 5, 24, 8, 0, tzinfo=ridetime.ZONE), "weekday_rush"),
    ],
)
def test_when_at(moment, when):
    assert ridetime.when_at(moment) == when


@pytest.mark.parametrize(
    ("moment", "when"),
    [
        # 12:30 UTC on Tuesday 29 September is 08:30 in Washington (R9).
        (datetime(2026, 9, 29, 12, 30, tzinfo=UTC), "weekday_rush"),
        # 02:00 UTC on Saturday 3 October is 22:00 on Friday there.
        (datetime(2026, 10, 3, 2, 0, tzinfo=UTC), "weekday_offpeak"),
        # 03:30 UTC on Monday 28 September is still Sunday evening.
        (datetime(2026, 9, 28, 3, 30, tzinfo=UTC), "weekend"),
        # And in winter, five hours behind: 13:30 UTC on 12 January is 08:30.
        (datetime(2027, 1, 12, 13, 30, tzinfo=UTC), "weekday_rush"),
        (datetime(2027, 1, 12, 11, 30, tzinfo=UTC), "weekday_offpeak"),
    ],
)
def test_when_at_reads_a_utc_moment_in_the_regions_time(moment, when):
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


def test_at_the_representative_instant_itself_the_next_is_a_week_on():
    """R10: the router is told the next such instant, never the present one."""
    saturday_nine = datetime(2026, 10, 3, 9, 0, tzinfo=ridetime.ZONE)
    assert ridetime.representative_time("weekend", saturday_nine) == "2026-10-10T09:00"
    a_minute_before = datetime(2026, 10, 3, 8, 59, tzinfo=ridetime.ZONE)
    assert ridetime.representative_time("weekend", a_minute_before) == "2026-10-03T09:00"


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


def test_beside_is_within_twenty_metres():
    """F17: 15 m is the lane; 30 m is the far side of a boulevard."""
    road = (1, {"highway": "primary", "cycleway:right": "separate"}, _line(-77.03, 38.90))
    near = (2, {"highway": "cycleway"}, _line(-77.03, 38.90 + 15 / 111_195))
    far = (3, {"highway": "cycleway"}, _line(-77.03, 38.90 + 30 / 111_195))
    assert beside_separate_roads([road, near, far]) == {2}


def test_beside_is_measured_to_the_road_not_its_line_beyond_its_end():
    """F21: a trail carrying straight on past the road's end lies on the
    road's line but is not beside it."""
    road = (1, {"highway": "primary", "cycleway:both": "separate"}, _line(-77.03, 38.90, n=3))
    # The road ends at -77.0296; the trail starts 50 m further east.
    onward = (2, {"highway": "cycleway"}, _line(-77.0290, 38.90))
    assert beside_separate_roads([road, onward]) == set()


@pytest.mark.parametrize(
    ("point", "metres"),
    [((30.0, 0.0), 20.0), ((-5.0, 0.0), 5.0), ((5.0, 3.0), 3.0), ((13.0, 4.0), 5.0)],
)
def test_the_distance_to_a_road_piece_stops_at_its_ends(point, metres):
    """F21, where the grid cannot hide it: past either end of a piece the
    distance is to that end, not to the piece's line."""
    from routemaker.facility import _point_segment_m

    assert _point_segment_m(point, (0.0, 0.0), (10.0, 0.0)) == pytest.approx(metres)


@pytest.mark.parametrize(("near", "beside"), [(5, False), (6, True)])
def test_beside_needs_six_tenths_of_the_way(near, beside):
    """F18: of ten vertices, six near the road is beside it, five is not."""
    road = (1, {"highway": "primary", "cycleway:both": "separate"}, _line(-77.03, 38.90, n=12))
    points = [(-77.03 + i * 0.0002, 38.9001 if i < near else 38.902) for i in range(10)]
    assert beside_separate_roads([road, (2, {"highway": "cycleway"}, points)]) == (
        {2} if beside else set()
    )


def test_only_a_road_is_the_road_a_lane_lies_beside():
    """F19: a trail-class way that carries a `cycleway*=separate` tag is not
    a road, and the path beside it stays a path."""
    odd = (1, {"highway": "footway", "cycleway:right": "separate"}, _line(-77.03, 38.90))
    beside = (2, {"highway": "cycleway"}, _line(-77.03, 38.9001))
    assert beside_separate_roads([odd, beside]) == set()


def test_beside_needs_most_of_the_way():
    road = (1, {"highway": "primary", "cycleway:both": "separate"}, _line(-77.03, 38.90, n=3))
    # Crosses the road and runs off: two of eight vertices near it.
    crossing = (2, {"highway": "cycleway"}, [(-77.0298, 38.8999 + i * 0.0003) for i in range(8)])
    assert beside_separate_roads([road, crossing]) == set()


# The owner, 2026-09-29 (OWNER-DECISIONS 73, 78, 80): how the stress map draws a way.
@pytest.mark.parametrize(
    ("tags", "drawn_as"),
    [
        ({"highway": "motorway"}, "barred"),
        ({"highway": "motorway_link"}, "barred"),
        ({"highway": "motorway", "bicycle": "yes"}, "road"),
        ({"highway": "trunk", "bicycle": "no"}, "barred"),  # the George Washington Parkway
        ({"highway": "trunk", "motorroad": "yes"}, "barred"),
        ({"highway": "trunk"}, "road"),  # US 1, US 50: bicycle-legal
        ({"highway": "trunk", "expressway": "yes", "maxspeed": "55 mph"}, "road"),  # US 340: Avoid
        ({"highway": "secondary", "bicycle": "no", "covered": "yes"}, "barred"),  # BWI arrivals
        # "Don't show roads that most typical people can't ride on" (88): the
        # public may not enter, so the road is hidden, not a barred public road.
        ({"highway": "service", "access": "private", "bicycle": "no"}, "hidden"),
        ({"highway": "service", "access": "private"}, "hidden"),  # BWI's 790013218
        ({"highway": "tertiary", "access": "private"}, "hidden"),  # Pentagon Access Road
        ({"highway": "unclassified", "access": "no", "foot": "private"}, "hidden"),
        ({"highway": "residential", "access": "military"}, "hidden"),
        ({"highway": "residential", "access": "restricted"}, "hidden"),
        ({"highway": "residential", "access": "permit"}, "hidden"),
        ({"highway": "residential", "vehicle": "private"}, "hidden"),
        ({"highway": "residential", "bicycle": "private"}, "hidden"),
        ({"highway": "service", "access": "private", "bicycle": "yes"}, "road"),
        ({"highway": "residential", "access": "no", "bicycle": "designated"}, "road"),  # car-free
        ({"highway": "tertiary", "access": "permissive"}, "road"),  # Patton Drive
        ({"highway": "residential", "access": "destination"}, "road"),
        ({"highway": "primary", "bicycle": "use_sidepath"}, "barred"),
        ({"highway": "residential"}, "road"),
        ({"highway": "corridor", "indoor": "yes", "level": "1"}, "hidden"),  # BWI's terminal
        ({"highway": "corridor"}, "hidden"),
        ({"highway": "footway", "indoor": "yes"}, "hidden"),
        ({"highway": "footway", "indoor": "no"}, "road"),
        ({"highway": "elevator"}, "hidden"),
        ({"highway": "construction"}, "hidden"),
        (
            {"highway": "footway", "bicycle": "no"},
            "road",
        ),  # a public path; its facility says the rest
        ({"highway": "path", "access": "private"}, "hidden"),  # inside the fence
        ({"highway": "footway", "access": "private", "foot": "yes"}, "road"),
        ({"highway": "cycleway", "access": "no", "bicycle": "designated"}, "road"),
        ({"highway": "footway", "access": "private", "bicycle": "private"}, "hidden"),
    ],
)
def test_the_map_class_of_a_way(tags, drawn_as) -> None:
    assert facility_rules.map_class(tags).value == drawn_as


@pytest.mark.parametrize(
    ("tags", "beside"),
    [
        ({"highway": "primary", "cycleway:left": "separate"}, True),  # 15th Street NW
        ({"highway": "primary", "cycleway:both": "separate"}, True),
        ({"highway": "primary", "cycleway": "track"}, False),  # the lane is on the road way
        ({"highway": "primary"}, False),
        ({"highway": "cycleway", "cycleway": "separate"}, False),  # the facility itself
    ],
)
def test_a_road_with_its_bikeway_mapped_beside_it(tags, beside) -> None:
    assert facility_rules.has_separate_bikeway(tags) is beside


@pytest.mark.parametrize(
    ("tags", "drawn_as"),
    [
        # "There's a lot of side paths and parking lots that probably don't need
        # to show up." - "Sidewalks + small paths" (OWNER-DECISIONS 82).
        ({"highway": "footway", "footway": "sidewalk"}, "hidden"),
        ({"highway": "footway", "footway": "sidewalk", "bicycle": "yes"}, "hidden"),
        (
            {"highway": "footway", "footway": "sidewalk", "bicycle": "designated"},
            "road",
        ),  # a roadside trail
        ({"highway": "path", "path": "sidewalk"}, "hidden"),
        # The Anacostia Riverwalk Trail's sidewalk stretches (ways 1165002638, 1444409547).
        (
            {
                "highway": "footway",
                "footway": "sidewalk",
                "bicycle": "yes",
                "name": "Anacostia Riverwalk Trail",
            },
            "road",
        ),
        ({"highway": "footway", "footway": "sidewalk", "name": "K Street Northwest"}, "hidden"),
        # A trail not yet built (the Mount Vernon Trail's 2030 section) is not drawn.
        (
            {"highway": "construction", "construction": "cycleway", "name": "Mount Vernon Trail"},
            "hidden",
        ),
        ({"highway": "cycleway", "cycleway": "sidewalk", "bicycle": "designated"}, "road"),
        ({"highway": "footway", "footway": "crossing"}, "hidden"),
        ({"highway": "footway", "footway": "crossing", "bicycle": "designated"}, "road"),
        ({"highway": "cycleway", "cycleway": "crossing"}, "road"),  # the trail's own crossing
        ({"highway": "footway", "footway": "traffic_island"}, "hidden"),
        ({"highway": "service", "service": "parking_aisle"}, "hidden"),
        ({"highway": "service", "service": "driveway"}, "hidden"),
        ({"highway": "service", "service": "drive-through"}, "hidden"),
        ({"highway": "service", "service": "alley"}, "alley"),  # item 100: close in, faint
        ({"highway": "service"}, "road"),
        ({"highway": "footway"}, "road"),  # its length and ends decide (short_paths_to_hide)
    ],
)
def test_sidewalks_crossings_and_parking_lots_are_left_off_the_map(tags, drawn_as) -> None:
    assert facility_rules.map_class(tags).value == drawn_as


def _west_east(lon0, lat, metres):
    """A west-east line `metres` long at latitude `lat`."""
    import math

    return [(lon0, lat), (lon0 + metres / (111_320 * math.cos(math.radians(lat))), lat)]


def test_short_unnamed_paths_are_hidden_unless_they_join_two_kept_trails() -> None:
    trail = {"highway": "cycleway", "name": "Rock Creek Trail"}
    link = {"highway": "footway"}
    ways = [
        (1, trail, [10, 11, 12], _west_east(-77.05, 38.95, 900)),
        (2, trail, [20, 21], _west_east(-77.04, 38.95, 900)),
        (3, link, [12, 20], _west_east(-77.045, 38.95, 60)),  # joins the two: kept
        (4, link, [12, 30], _west_east(-77.045, 38.951, 60)),  # a spur: hidden
        (5, link, [40, 41], _west_east(-77.03, 38.95, 140)),  # alone, short: hidden
        (6, link, [50, 51], _west_east(-77.02, 38.95, 400)),  # long: kept
        (
            7,
            {"highway": "path", "name": "Glover Trail"},
            [60, 61],
            _west_east(-77.01, 38.95, 50),
        ),  # named
        (
            8,
            {"highway": "footway", "bicycle": "designated"},
            [70, 71],
            _west_east(-77.0, 38.95, 50),
        ),
        (9, {"highway": "footway", "footway": "sidewalk"}, [12, 21], _west_east(-77.0, 38.96, 50)),
        (10, {"highway": "residential"}, [80, 81], _west_east(-76.99, 38.95, 50)),
    ]
    assert facility_rules.short_paths_to_hide(ways) == {4, 5}
    assert facility_rules.SHORT_PATH_M == 150
    # A sidewalk is not a kept trail for the joining rule: a link to one is a spur.
    assert facility_rules.short_paths_to_hide(
        [ways[0], ways[8], (11, link, [12, 21], _west_east(0, 0, 30))]
    ) == {11}


def test_roads_inside_a_military_base_are_found_and_trails_along_it_are_not() -> None:
    """ "Don't show roads that most typical people can't ride on, such as within
    military bases, or the pentagon" (OWNER-DECISIONS 88)."""
    from pipeline import restricted_areas as military

    square = [(-77.06, 38.866), (-77.05, 38.866), (-77.05, 38.876), (-77.06, 38.876)]
    hole = [(-77.057, 38.869), (-77.053, 38.869), (-77.053, 38.873), (-77.057, 38.873)]
    pentagon = ((-77.06, 38.866, -77.05, 38.876), [square], [hole])
    assert military.is_military_area({"landuse": "military", "name": "The Pentagon"})
    assert military.is_military_area({"military": "base"})
    assert not military.is_military_area({"military": "no"})
    assert not military.is_military_area({"landuse": "residential"})
    ways = [
        (
            1,
            {"highway": "tertiary", "name": "Connector Road"},
            [(-77.059, 38.867), (-77.058, 38.868)],
        ),
        (2, {"highway": "tertiary"}, [(-77.055, 38.871), (-77.054, 38.872)]),  # in the hole
        (
            3,
            {"highway": "secondary"},
            [(-77.059, 38.867), (-77.04, 38.867), (-77.03, 38.867)],
        ),  # mostly out
        (
            4,
            {"highway": "cycleway", "name": "Mount Vernon Trail"},
            [(-77.059, 38.867), (-77.058, 38.868)],
        ),
        (5, {"highway": "tertiary"}, [(-77.07, 38.86), (-77.069, 38.861)]),  # outside
        (6, {"building": "yes"}, [(-77.059, 38.867)]),
    ]
    assert military.roads_inside(ways, [pentagon]) == {1}
    assert military.roads_inside(ways, []) == set()


def test_the_riverwalk_through_the_navy_yard_stays_and_the_streets_beside_it() -> None:
    """The owner, 2026-09-29, of the Washington Navy Yard: "There's a trail that
    open near the water." (OWNER-DECISIONS 94). On the dials box extract the
    Anacostia Riverwalk Trail's two ways inside the Navy Yard's area are
    highway=cycleway, bicycle=designated, foot=designated, no access or
    opening_hours tag: a public trail, routable, and never area-tested."""
    from pipeline import restricted_areas as military

    riverwalk = {
        "highway": "cycleway",
        "name": "Anacostia Riverwalk Trail",
        "bicycle": "designated",
        "foot": "designated",
    }
    assert facility_rules.map_class(riverwalk).value == "road"
    yard = (
        (-77.0, 38.871, -76.991, 38.8765),
        [[(-77.0, 38.871), (-76.991, 38.871), (-76.991, 38.8765), (-77.0, 38.8765)]],
        [],
    )
    ways = [
        (1, riverwalk, [(-76.998, 38.8715), (-76.994, 38.8715)]),  # along the water, inside
        (
            2,
            {"highway": "service", "name": "Dahlgren Avenue Southeast"},
            [(-76.996, 38.874), (-76.995, 38.874)],
        ),
        (
            3,
            {"highway": "primary", "name": "M Street Southeast"},
            [(-77.0, 38.877), (-76.99, 38.877)],
        ),  # outside
        (
            4,
            {"highway": "unclassified", "name": "Water Street Southeast"},
            [(-77.003, 38.873), (-77.001, 38.873)],
        ),
    ]
    assert military.roads_inside(ways, [yard]) == {2}
    for tags in (ways[2][1], ways[3][1]):
        assert facility_rules.map_class(tags).value == "road"


@pytest.mark.parametrize(
    ("tags", "drawn_as"),
    [
        # "Alley cut throughs should only be used if the roads are very problematic
        # nearby. Cut down on showing them" (OWNER-DECISIONS 100).
        ({"highway": "service", "service": "alley"}, "alley"),
        ({"highway": "service", "service": "alley", "access": "private"}, "hidden"),
        ({"highway": "service"}, "road"),
        ({"highway": "residential", "name": "Alley Street"}, "road"),
        # The Lua marks tier-5 roads service=alley in Valhalla's extract only; the
        # source road is what map_class reads.
        ({"highway": "trunk", "expressway": "yes", "maxspeed": "55 mph"}, "road"),
    ],
)
def test_an_alley_is_its_own_map_class(tags, drawn_as) -> None:
    assert facility_rules.map_class(tags).value == drawn_as


def _box(west, south, east, north):
    ring = [(west, south), (east, south), (east, north), (west, north)]
    return ((west, south, east, north), [ring], [])


def test_the_kinds_of_restricted_area() -> None:
    from pipeline import restricted_areas as areas

    assert areas.area_kind({"landuse": "military"}) == "military"
    assert (
        areas.area_kind({"landuse": "cemetery", "name": "Arlington National Cemetery"})
        == "cemetery"
    )
    assert (
        areas.area_kind({"amenity": "grave_yard", "name": "Congressional Cemetery"}) == "cemetery"
    )
    assert areas.area_kind({"amenity": "parking"}) == "parking"
    assert areas.area_kind({"parking": "surface"}) == "parking"
    assert areas.area_kind({"parking": "multi-storey"}) == "parking"
    assert areas.area_kind({"parking": "street_side"}) is None
    assert areas.area_kind({"landuse": "residential"}) is None


def test_every_way_inside_a_cemetery_is_found_but_a_signed_trail_and_a_trail_beside_it():
    """ "There's a lot of cemetary roads, such as arlington national cemetary. We
    shouldn't have these roads on here, even if some of them can be technically
    ridden. I don't want to encourage a cemetary cut through as it's
    disrespectful." (OWNER-DECISIONS 98)"""
    from pipeline import restricted_areas as areas

    arlington = _box(-77.08, 38.87, -77.06, 38.885)
    ways = [
        (
            1,
            {"highway": "service", "name": "Eisenhower Drive"},
            [(-77.07, 38.875), (-77.069, 38.876)],
        ),
        (2, {"highway": "footway"}, [(-77.075, 38.878), (-77.074, 38.879)]),
        (
            3,
            {"highway": "cycleway", "bicycle": "designated"},
            [(-77.075, 38.872), (-77.074, 38.873)],
        ),
        # The Mount Vernon Trail and Memorial Avenue run outside the boundary.
        (
            4,
            {"highway": "cycleway", "name": "Mount Vernon Trail"},
            [(-77.055, 38.875), (-77.054, 38.88)],
        ),
        (
            5,
            {"highway": "secondary", "name": "Memorial Avenue"},
            [(-77.059, 38.881), (-77.05, 38.882)],
        ),
        (6, {"building": "yes"}, [(-77.07, 38.875)]),
    ]
    assert areas.cemetery_ways(ways, [arlington]) == {1, 2}
    assert areas.cemetery_ways(ways, []) == set()


def test_a_parking_lots_own_ways_are_found_and_the_street_past_it_is_not():
    """ "Also, no need to stripe through all the parking lots." (OWNER-DECISIONS 99)"""
    from pipeline import restricted_areas as areas

    lot = _box(-77.12, 39.05, -77.11, 39.056)
    ways = [
        (1, {"highway": "service"}, [(-77.118, 39.052), (-77.112, 39.052)]),  # an aisle, no tag
        (2, {"highway": "footway"}, [(-77.117, 39.053), (-77.116, 39.054)]),
        (
            3,
            {"highway": "footway", "name": "Bethesda Trolley Trail"},
            [(-77.117, 39.051), (-77.116, 39.052)],
        ),
        (
            4,
            {"highway": "footway", "bicycle": "designated"},
            [(-77.115, 39.051), (-77.114, 39.052)],
        ),
        (
            5,
            {"highway": "primary", "name": "Rockville Pike"},
            [(-77.119, 39.0505), (-77.105, 39.0505)],
        ),
        (6, {"highway": "residential"}, [(-77.119, 39.055), (-77.111, 39.055)]),  # a street through
        (
            7,
            {"highway": "service", "name": "Capitol Circle Drive"},
            [(-77.118, 39.054), (-77.113, 39.054)],
        ),
    ]
    assert areas.parking_ways(ways, [lot]) == {1, 2}


def test_the_index_finds_an_area_across_its_cells_and_misses_one_far_away():
    from pipeline import restricted_areas as areas

    big = _box(-77.2, 38.8, -76.9, 39.0)  # many grid cells
    far = _box(-76.0, 39.5, -75.99, 39.51)
    ways = [
        (1, {"highway": "service"}, [(-77.1, 38.9)]),
        (2, {"highway": "service"}, [(-76.5, 39.3)]),
    ]
    assert areas.parking_ways(ways, [big, far]) == {1}
