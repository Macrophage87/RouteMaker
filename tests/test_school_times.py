"""School times (`routemaker.school_times`, `pipeline.school_layer`, `core.route_schools`;
the owner, 2026-11-26): a minor road on a school's grounds or in front of them is searched
at its raters' arrival-time level at weekday rush, and nowhere else."""

from __future__ import annotations

from unittest import mock

import pytest
from shapely.geometry import Polygon
from shapely.strtree import STRtree

from core import route_schools
from core.routing import PieceClass
from pipeline import extract, school_layer
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


def test_a_rating_lifts_a_road_and_never_lowers_one():
    assert school_times.raised("1", False, "none", 3.0) == ("3", False)
    assert school_times.raised("2", False, "lane", 2.5) == ("2", True)
    assert school_times.raised("2", True, "none", 2.5) is None
    assert school_times.raised("3", False, "none", 2.0) is None
    assert school_times.raised("1", False, "path", 3.0) is None
    assert school_times.raised("1", False, "none", None) is None
    assert school_times.raised("unknown", False, "none", 3.0) is None


def test_ratings_load_and_bad_rows_are_refused(tmp_path):
    assert school_times.load(tmp_path / "none.csv") == {}
    good = tmp_path / "good.csv"
    good.write_text("way_id,level,why\n12,3,bus loop of a 900-pupil middle school\n13,2.5,front\n")
    assert school_times.load(good) == {12: 3.0, 13: 2.5}
    for body in (
        "way_id,level,why\n12,2.7,x\n",
        "way_id,level,why\n12,3,\n",
        "way_id,level,why\n12,3,x\n12,2,y\n",
        "way_id,level,why\nabc,3,x\n",
    ):
        bad = tmp_path / "bad.csv"
        bad.write_text(body)
        with pytest.raises(school_times.RushLevelsRefused):
            school_times.load(bad)


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


def test_candidates_name_the_school_beside_the_road():
    school = school_layer.School(osm="way/1", name="Example Middle School", shape=GROUNDS)
    loop = extract.Way(osm_id=7, tags=dict(SERVICE), node_ids=[1, 2, 3])
    loop.coordinates = [
        (-77.0495, LAT + 0.0005),
        (-77.0485, LAT + 0.0005),
        (-77.0485, LAT + 0.0012),
    ]
    loop.located = [0, 1, 2]
    far = extract.Way(osm_id=8, tags={"highway": "residential"}, node_ids=[4, 5])
    far.coordinates = [(-77.050, LAT - 0.0009), (-77.0477, LAT - 0.0009)]
    far.located = [0, 1]
    rows = school_layer.candidates([loop, far], [school])
    assert [r["way_id"] for r in rows] == [7]
    assert rows[0]["school"] == "Example Middle School"
    assert abs(rows[0]["school_lat"] - (LAT + 0.0009)) < 1e-5


def _classes():
    return [
        PieceClass("1", "none", None, None, None, None, False),
        PieceClass("1", "none", None, None, None, None, False),
        PieceClass("1", "path", None, None, None, None, False),
    ]


def test_rated_school_pieces_are_searched_at_their_level_at_rush_hour():
    classes = _classes()
    with mock.patch.object(route_schools, "levels_of", return_value=[3.0, None, 3.0]):
        priced = route_schools.priced_at(classes, [object()] * 3, ridetime.WEEKDAY_RUSH)
    assert [c[0] for c in priced] == ["3", "1", "1"]
    # The rider's own reading is untouched.
    assert [c[0] for c in classes] == ["1", "1", "1"]


def test_unrated_roads_are_unchanged():
    classes = _classes()
    with mock.patch.object(route_schools, "levels_of", return_value=[None, None, None]):
        assert route_schools.priced_at(classes, [object()] * 3, ridetime.WEEKDAY_RUSH) is classes


def test_nothing_changes_outside_school_times():
    classes = _classes()
    with mock.patch.object(route_schools, "levels_of", return_value=[3.0, 3.0, 3.0]) as read:
        for when in (ridetime.WEEKDAY_OFFPEAK, ridetime.WEEKEND, ridetime.NIGHT):
            assert route_schools.priced_at(classes, [object()] * 3, when) is classes
    read.assert_not_called()
