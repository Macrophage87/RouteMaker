"""School times (`routemaker.school_times`, `pipeline.school_layer`, `core.route_schools`;
the owner, 2026-11-26): a minor road on a school's grounds or in front of them is searched
at LTS 3 at least at weekday rush, and nowhere else."""

from __future__ import annotations

from unittest import mock

from shapely.geometry import Polygon
from shapely.strtree import STRtree

from core import route_schools
from core.routing import PieceClass
from pipeline import school_layer
from routemaker import ridetime, school_times

# A school's grounds about 200 m square, at Wheaton's latitude.
LAT = 39.05
GROUNDS = Polygon(
    [(-77.050, LAT), (-77.0477, LAT), (-77.0477, LAT + 0.0018), (-77.050, LAT + 0.0018)]
)
TREE = STRtree([school_layer.widened(GROUNDS)])
SERVICE = {"highway": "service", "service": "parking_aisle"}


def test_only_weekday_rush_is_a_school_time():
    assert school_times.at_school_time(ridetime.WEEKDAY_RUSH)
    for when in (ridetime.WEEKDAY_OFFPEAK, ridetime.WEEKEND, ridetime.NIGHT, None):
        assert not school_times.at_school_time(when)


def test_raised_tier_lifts_quiet_roads_only():
    assert school_times.raised_tier("1", "none") == "3"
    assert school_times.raised_tier("2", "lane") == "3"
    assert school_times.raised_tier("3", "none") is None
    assert school_times.raised_tier("4", "none") is None
    assert school_times.raised_tier("1", "path") is None
    assert school_times.raised_tier("unknown", "none") is None


def test_a_bus_loop_on_the_grounds_is_a_school_piece():
    loop = [(-77.0495, LAT + 0.0005), (-77.0485, LAT + 0.0005), (-77.0485, LAT + 0.0012)]
    assert school_layer.is_school_piece(SERVICE, loop, TREE)


def test_the_street_in_front_is_and_the_next_block_is_not():
    # 15 m south of the grounds' edge, along its whole front: the drop-off street.
    front = [(-77.050, LAT - 0.000135), (-77.0477, LAT - 0.000135)]
    assert school_layer.is_school_piece({"highway": "residential"}, front, TREE)
    # 100 m south: the next street over.
    next_block = [(-77.050, LAT - 0.0009), (-77.0477, LAT - 0.0009)]
    assert not school_layer.is_school_piece({"highway": "residential"}, next_block, TREE)


def test_a_street_touching_a_corner_is_not():
    # 300 m long, its first 20 m or so by the grounds' corner.
    corner = [(-77.0477, LAT - 0.0001), (-77.0442, LAT - 0.0001)]
    assert not school_layer.is_school_piece({"highway": "residential"}, corner, TREE)


def test_busier_roads_and_paths_are_never_school_pieces():
    across = [(-77.050, LAT + 0.0009), (-77.0477, LAT + 0.0009)]
    for highway in ("secondary", "tertiary", "footway", "cycleway"):
        assert not school_layer.is_school_piece({"highway": highway}, across, TREE)
    assert not school_layer.is_school_piece(SERVICE, across, None)


def _classes():
    return [
        PieceClass("1", "none", None, None, None, None, False),
        PieceClass("1", "none", None, None, None, None, False),
        PieceClass("1", "path", None, None, None, None, False),
    ]


def test_school_pieces_are_searched_at_lts3_at_rush_hour():
    classes = _classes()
    with mock.patch.object(route_schools, "flags_of", return_value=[True, False, True]):
        priced = route_schools.priced_at(classes, [object()] * 3, ridetime.WEEKDAY_RUSH)
    assert [c[0] for c in priced] == ["3", "1", "1"]
    # The rider's own reading is untouched.
    assert [c[0] for c in classes] == ["1", "1", "1"]


def test_nothing_changes_outside_school_times():
    classes = _classes()
    with mock.patch.object(route_schools, "flags_of", return_value=[True, True, True]) as read:
        for when in (ridetime.WEEKDAY_OFFPEAK, ridetime.WEEKEND, ridetime.NIGHT):
            assert route_schools.priced_at(classes, [object()] * 3, when) is classes
    read.assert_not_called()
