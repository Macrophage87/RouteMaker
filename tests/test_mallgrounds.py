"""The walks of the Washington Monument grounds and Constitution Gardens are open to
bicycles, and their memorials and the Tidal Basin's walks are not
(routemaker.mallgrounds; the owner, 2026-10-25)."""

from __future__ import annotations

from dataclasses import dataclass, field

from routemaker import mallgrounds

# Midpoints of OSM ways in the 2026-10-25 data.
MONUMENT_LAWN = (-77.03642, 38.89092)  # way 895025358, north-west of the Monument
FRIENDSHIP_GARDEN = (-77.03699, 38.89178)  # way 895025362, German-American Friendship Garden
GARDENS_LAKE = (-77.04600, 38.89170)  # way 398788061, Constitution Gardens' west lawn
WALL_APPROACH = (-77.04833, 38.89050)  # way 398788057, the path to the Vietnam Veterans Memorial
MONUMENT_PLAZA = (-77.03560, 38.88951)  # way 895025351, the plaza's ring walk
VIETNAM_WALL = (-77.04749, 38.89123)  # way 398788059, the walk along the wall
SIGNERS_ISLAND = (-77.04287, 38.89114)  # way 379782130, the 56 Signers' memorial
TIDAL_BASIN = (-77.03569, 38.88498)  # way 367203258, the Tidal Basin's shore walk
LINCOLN_MEMORIAL = (-77.0502, 38.8893)  # off the grounds, west
DOWNTOWN = (-77.0300, 38.8990)
WALK = {"highway": "footway", "surface": "concrete"}


def line(lon, lat, n=3, dlon=0.00002):
    """A short way whose midpoint is (lon, lat)."""
    return [(lon + (i - (n - 1) / 2) * dlon, lat) for i in range(n)]


@dataclass
class FakeWay:
    osm_id: int
    tags: dict
    coordinates: list = field(default_factory=list)
    node_ids: list = field(default_factory=list)


class TestTheArea:
    def test_the_grounds_and_the_paths_to_the_memorials_are_inside(self) -> None:
        for point in (MONUMENT_LAWN, FRIENDSHIP_GARDEN, GARDENS_LAKE, WALL_APPROACH):
            assert mallgrounds.contains(point), point

    def test_the_memorials_and_the_tidal_basin_walks_are_not(self) -> None:
        for point in (MONUMENT_PLAZA, VIETNAM_WALL, SIGNERS_ISLAND, TIDAL_BASIN):
            assert not mallgrounds.contains(point), point

    def test_off_the_grounds_is_not(self) -> None:
        assert not mallgrounds.contains(LINCOLN_MEMORIAL)
        assert not mallgrounds.contains(DOWNTOWN)


class TestOpens:
    def test_an_untagged_walk_on_the_grounds_opens(self) -> None:
        for point in (MONUMENT_LAWN, FRIENDSHIP_GARDEN, GARDENS_LAKE, WALL_APPROACH):
            assert mallgrounds.opens(WALK, line(*point)), point
        assert mallgrounds.opens({"highway": "pedestrian"}, line(*MONUMENT_LAWN))

    def test_the_memorials_and_the_tidal_basin_walks_stay_closed(self) -> None:
        for point in (MONUMENT_PLAZA, VIETNAM_WALL, SIGNERS_ISLAND, TIDAL_BASIN):
            assert not mallgrounds.opens(WALK, line(*point)), point

    def test_off_the_grounds_nothing_changes(self) -> None:
        assert not mallgrounds.opens(WALK, line(*LINCOLN_MEMORIAL))
        assert not mallgrounds.opens(WALK, line(*DOWNTOWN))

    def test_the_capitol_grounds_exceptions_hold_here_too(self) -> None:
        for tags in (
            {**WALK, "bicycle": "no"},
            {**WALK, "bicycle": "dismount"},
            {**WALK, "access": "private"},
            {"highway": "footway", "footway": "sidewalk"},
            {"highway": "footway", "footway": "crossing"},
            {"highway": "steps"},
            {"highway": "path", "surface": "grass"},
            {**WALK, "tunnel": "yes"},
        ):
            assert not mallgrounds.opens(tags, line(*MONUMENT_LAWN)), tags


class TestOpenWays:
    def test_opens_the_walk_and_the_crossing_that_meets_it_only(self) -> None:
        walk = FakeWay(1, dict(WALK), line(*MONUMENT_LAWN), [10, 11, 12])
        crossing = {"highway": "footway", "footway": "crossing"}
        touching = FakeWay(2, dict(crossing), line(*MONUMENT_LAWN), [12, 13])
        apart = FakeWay(3, dict(crossing), line(*MONUMENT_LAWN), [20, 21])
        wall = FakeWay(4, dict(WALK), line(*VIETNAM_WALL), [30, 31])
        shore = FakeWay(5, dict(WALK), line(*TIDAL_BASIN), [40, 41])
        outside = FakeWay(6, dict(WALK), line(*DOWNTOWN), [50, 51])
        opened = mallgrounds.open_ways([walk, touching, apart, wall, shore, outside])
        assert opened == {1, 2}
        assert walk.tags["bicycle"] == "yes" and touching.tags["bicycle"] == "yes"
        for way in (apart, wall, shore, outside):
            assert "bicycle" not in way.tags
