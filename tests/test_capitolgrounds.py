"""The walks of the US Capitol grounds are open to bicycles
(routemaker.capitolgrounds; the owner, 2026-10-21)."""

from __future__ import annotations

from dataclasses import dataclass, field

from routemaker import capitolgrounds

WEST_FRONT = (-77.0115, 38.8895)  # the lawn below the West Front
UPPER_SENATE_PARK = (-77.0095, 38.8930)
LOWER_SENATE_PARK = (-77.0080, 38.8956)  # north of D Street, east of North Capitol
UNION_SQUARE = (-77.0135, 38.8898)  # the Reflecting Pool's walks
OUTSIDE = (-77.0300, 38.8990)  # downtown, a mile west
COLUMBUS_PLAZA = (-77.0075, 38.8968)  # Union Station's plaza: National Park Service land
WALK = {"highway": "footway", "foot": "yes"}


def line(lon, lat, n=3, dlon=0.00005):
    return [(lon + i * dlon, lat) for i in range(n)]


@dataclass
class FakeWay:
    osm_id: int
    tags: dict
    coordinates: list = field(default_factory=list)
    node_ids: list = field(default_factory=list)


class TestTheArea:
    def test_the_grounds_and_both_senate_parks_are_inside(self) -> None:
        for point in (WEST_FRONT, UPPER_SENATE_PARK, LOWER_SENATE_PARK, UNION_SQUARE):
            assert capitolgrounds.contains(point), point

    def test_downtown_and_union_stations_plaza_are_not(self) -> None:
        assert not capitolgrounds.contains(OUTSIDE)
        assert not capitolgrounds.contains(COLUMBUS_PLAZA)


class TestOpens:
    def test_an_untagged_walk_path_or_plaza_on_the_grounds_opens(self) -> None:
        assert capitolgrounds.opens(WALK, line(*WEST_FRONT))
        assert capitolgrounds.opens({"highway": "footway"}, line(*LOWER_SENATE_PARK))
        assert capitolgrounds.opens({"highway": "path"}, line(*UPPER_SENATE_PARK))
        assert capitolgrounds.opens({"highway": "pedestrian"}, line(*UNION_SQUARE))

    def test_off_the_grounds_nothing_changes(self) -> None:
        assert not capitolgrounds.opens(WALK, line(*OUTSIDE))
        assert not capitolgrounds.opens(WALK, line(*COLUMBUS_PLAZA))

    def test_a_sidewalk_keeps_the_sidewalk_rule(self) -> None:
        sidewalk = {"highway": "footway", "footway": "sidewalk"}
        assert not capitolgrounds.opens(sidewalk, line(*WEST_FRONT))

    def test_what_osm_says_stands(self) -> None:
        for value in ("no", "dismount", "yes"):
            assert not capitolgrounds.opens({**WALK, "bicycle": value}, line(*WEST_FRONT))
        assert not capitolgrounds.opens({**WALK, "access": "private"}, line(*WEST_FRONT))
        assert not capitolgrounds.opens({**WALK, "vehicle": "no"}, line(*WEST_FRONT))

    def test_steps_crossings_and_natural_surfaces_are_not_walks(self) -> None:
        for tags in (
            {"highway": "steps"},
            {"highway": "footway", "footway": "crossing"},
            {"highway": "footway", "footway": "access_aisle"},
            {"highway": "path", "surface": "grass"},
            {"highway": "corridor"},
        ):
            assert not capitolgrounds.opens(tags, line(*WEST_FRONT)), tags

    def test_passages_through_and_under_the_buildings_stay_closed(self) -> None:
        for extra in (
            {"tunnel": "building_passage"},
            {"tunnel": "yes", "layer": "-1"},
            {"indoor": "yes"},
            {"covered": "yes"},
        ):
            assert not capitolgrounds.opens({**WALK, **extra}, line(*WEST_FRONT)), extra
        assert capitolgrounds.opens({**WALK, "tunnel": "no", "covered": "no"}, line(*WEST_FRONT))


class TestOpenWays:
    def test_opens_the_walk_and_the_crossing_that_meets_it_only(self) -> None:
        walk = FakeWay(1, dict(WALK), line(*WEST_FRONT), [10, 11, 12])
        crossing = {"highway": "footway", "footway": "crossing"}
        touching = FakeWay(2, dict(crossing), line(*WEST_FRONT), [12, 13])
        apart = FakeWay(3, dict(crossing), line(*WEST_FRONT), [20, 21])
        sidewalk = FakeWay(4, {"highway": "footway", "footway": "sidewalk"}, line(*WEST_FRONT))
        outside = FakeWay(5, dict(WALK), line(*OUTSIDE))
        opened = capitolgrounds.open_ways([walk, touching, apart, sidewalk, outside])
        assert opened == {1, 2}
        assert walk.tags["bicycle"] == "yes" and touching.tags["bicycle"] == "yes"
        for way in (apart, sidewalk, outside):
            assert "bicycle" not in way.tags
