"""The walkways inside DC's circle parks are open to bicycles
(routemaker.circleparks; the owner, 2026-10-17)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from routemaker import circleparks

DUPONT = (-77.04339, 38.90968)
LOGAN = (-77.02962, 38.90964)
OUTSIDE = (-77.0400, 38.9120)  # a block north of Dupont Circle
WALKWAY = {"highway": "footway"}


def line(lon, lat, n=3, dlon=0.00005):
    return [(lon + i * dlon, lat) for i in range(n)]


@dataclass
class FakeWay:
    osm_id: int
    tags: dict
    coordinates: list = field(default_factory=list)


class TestTheFixture:
    def test_it_holds_the_named_circles_and_not_the_forts(self) -> None:
        data = json.loads(circleparks.POLYGON_FILE.read_text())
        names = {f["properties"]["name"] for f in data["features"]}
        assert {"Dupont Circle", "Logan Circle", "Thomas Circle", "Grant Circle"} <= names
        assert all(name.endswith(" Circle") for name in names)
        assert "Fort Circle Park" not in names

    def test_dupont_and_logan_are_inside_and_the_street_beside_is_not(self) -> None:
        assert circleparks.contains(DUPONT)
        assert circleparks.contains(LOGAN)
        assert not circleparks.contains(OUTSIDE)


class TestOpens:
    def test_an_untagged_walkway_inside_opens(self) -> None:
        assert circleparks.opens(WALKWAY, line(*DUPONT))
        assert circleparks.opens({"highway": "path", "surface": "paving_stones"}, line(*LOGAN))
        assert circleparks.opens({"highway": "pedestrian", "area": "yes"}, line(*DUPONT))

    def test_outside_a_circle_nothing_changes(self) -> None:
        assert not circleparks.opens(WALKWAY, line(*OUTSIDE))

    def test_a_bicycle_tag_already_there_stands(self) -> None:
        for value in ("no", "dismount", "designated", "yes"):
            assert not circleparks.opens({**WALKWAY, "bicycle": value}, line(*DUPONT))

    def test_a_closed_access_stands(self) -> None:
        assert not circleparks.opens({**WALKWAY, "access": "no"}, line(*DUPONT))
        assert not circleparks.opens({**WALKWAY, "access": "private"}, line(*DUPONT))
        assert circleparks.opens({**WALKWAY, "access": "yes"}, line(*DUPONT))

    def test_sidewalks_crossings_steps_and_roads_are_not_walkways(self) -> None:
        for tags in (
            {"highway": "footway", "footway": "sidewalk"},
            {"highway": "footway", "footway": "crossing"},
            {"highway": "steps"},
            {"highway": "service"},
            {"highway": "cycleway"},
        ):
            assert not circleparks.opens(tags, line(*DUPONT)), tags

    def test_a_natural_surface_path_stays_closed(self) -> None:
        assert not circleparks.opens({"highway": "path", "surface": "grass"}, line(*DUPONT))

    def test_no_coordinates_opens_nothing(self) -> None:
        assert not circleparks.opens(WALKWAY, [])


class TestOpenWays:
    def test_writes_bicycle_yes_on_the_opened_ways_only(self) -> None:
        inside = FakeWay(1, dict(WALKWAY), line(*DUPONT))
        refused = FakeWay(2, {**WALKWAY, "bicycle": "no"}, line(*DUPONT))
        outside = FakeWay(3, dict(WALKWAY), line(*OUTSIDE))
        opened = circleparks.open_ways([inside, refused, outside])
        assert opened == {1}
        assert inside.tags["bicycle"] == "yes"
        assert refused.tags["bicycle"] == "no"
        assert "bicycle" not in outside.tags


class TestTripPoints:
    def test_a_point_inside_a_circle_is_kept_off_the_underpass(self) -> None:
        from core.routing import circle_park_filter

        assert circle_park_filter(*DUPONT) == {"search_filter": {"exclude_tunnel": True}}
        assert circle_park_filter(*OUTSIDE) == {}
