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
    node_ids: list = field(default_factory=list)


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
        assert circleparks.opens({"highway": "pedestrian"}, line(*DUPONT))

    def test_a_plaza_mapped_only_as_an_area_is_left_as_mapped(self) -> None:
        """The hunt of 2026-11-08 (Q5): `pedestrian_areas` is off, so Valhalla never
        builds the area and opening it was inert. Until then the check above asserted
        `{"highway": "pedestrian", "area": "yes"}` opened."""
        assert not circleparks.opens({"highway": "pedestrian", "area": "yes"}, line(*DUPONT))

    def test_outside_a_circle_nothing_changes(self) -> None:
        assert not circleparks.opens(WALKWAY, line(*OUTSIDE))

    def test_a_bicycle_tag_already_there_stands(self) -> None:
        for value in ("no", "dismount", "designated", "yes"):
            assert not circleparks.opens({**WALKWAY, "bicycle": value}, line(*DUPONT))
        for key in ("bicycle:forward", "bicycle:conditional", "vehicle"):
            assert not circleparks.opens({**WALKWAY, key: "no"}, line(*DUPONT)), key

    def test_a_closed_access_stands(self) -> None:
        assert not circleparks.opens({**WALKWAY, "access": "no"}, line(*DUPONT))
        assert not circleparks.opens({**WALKWAY, "access": "private"}, line(*DUPONT))
        assert circleparks.opens({**WALKWAY, "access": "yes"}, line(*DUPONT))

    def test_the_sidewalk_round_the_edge_is_the_parks_own(self) -> None:
        assert circleparks.opens({"highway": "footway", "footway": "sidewalk"}, line(*DUPONT))

    def test_crossings_steps_and_roads_are_not_walkways(self) -> None:
        for tags in (
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

    def test_a_crossing_touching_an_opened_walkway_opens_so_the_park_meets_the_street(self) -> None:
        walkway = FakeWay(1, dict(WALKWAY), line(*DUPONT), [10, 11, 12])
        crossing = {"highway": "footway", "footway": "crossing"}
        touching = FakeWay(2, dict(crossing), line(*OUTSIDE), [12, 13])
        apart = FakeWay(3, dict(crossing), line(*OUTSIDE), [20, 21])
        signed = FakeWay(4, {**crossing, "bicycle": "no"}, line(*OUTSIDE), [12, 14])
        opened = circleparks.open_ways([walkway, touching, apart, signed])
        assert opened == {1, 2}
        assert touching.tags["bicycle"] == "yes" and "bicycle" not in apart.tags
        assert signed.tags["bicycle"] == "no"


class TestEveryMatchOfAPoint:
    """The second 2026-11-08 hunt (P6, P7): only the plan's own /route kept a point in a circle
    off the tunnel below. Best order's matrix, Reach's rings, the nearest places and the walks
    to a dock, a station or a stop matched it to the underpass (before: no `search_filter`)."""

    TUNNEL_OFF = {"exclude_tunnel": True}

    def test_best_order_and_nearest_keep_off_the_underpass(self, monkeypatch) -> None:
        from core import nearest, routing, stoporder

        seen = []
        monkeypatch.setattr(
            stoporder, "ask_matrix", lambda variant, payload, deadline: seen.append(payload) or {}
        )
        monkeypatch.setattr(
            stoporder,
            "_ask",
            lambda variant, endpoint, payload, deadline: seen.append(payload) or ({}, variant),
        )
        deadline = routing.Deadline(routing.clock() + 30, 10)
        stoporder._matrix("standard", [DUPONT, OUTSIDE], {}, deadline)
        assert seen[0]["sources"][0]["search_filter"] == self.TUNNEL_OFF
        assert "search_filter" not in seen[0]["sources"][1]
        stoporder._leg_costs("standard", [list(DUPONT), list(OUTSIDE)], {}, "weekend", deadline)
        assert seen[1]["locations"][0]["search_filter"] == self.TUNNEL_OFF
        nearest._row("standard", list(DUPONT), [list(LOGAN)], {}, deadline)
        assert seen[2]["sources"][0]["search_filter"] == self.TUNNEL_OFF
        assert seen[2]["targets"][0]["search_filter"] == self.TUNNEL_OFF

    def test_reach_grows_from_the_park_not_the_underpass(self) -> None:
        from core import reach

        payload = reach._payload("bicycle", {}, list(DUPONT), [10], False, [])
        assert payload["locations"][0]["search_filter"] == self.TUNNEL_OFF

    def test_a_walk_to_or_from_a_circle_keeps_off_the_underpass(self, monkeypatch) -> None:
        from core import bikeshare, presets, routing, transit

        seen = []

        def call(variant, endpoint, payload, deadline):
            seen.append(payload)
            raise routing.RouterRefused(400, 442, "no path")

        monkeypatch.setattr(routing, "_call", call)
        deadline = routing.Deadline(routing.clock() + 30, 10)
        routing.walk_leg(list(DUPONT), list(OUTSIDE), deadline)
        bikeshare.RoutingServices(deadline, None).walk(DUPONT, OUTSIDE)
        transit.RoutingServices(routing.clock() + 30, presets.BIKE_TRANSIT).walk(OUTSIDE, DUPONT)
        assert len(seen) == 3
        assert seen[0]["locations"][0]["search_filter"] == self.TUNNEL_OFF
        assert seen[1]["locations"][0]["search_filter"] == self.TUNNEL_OFF
        assert seen[2]["locations"][1]["search_filter"] == self.TUNNEL_OFF
        assert all(
            "search_filter" not in s["locations"][i] for s, i in zip(seen, (1, 1, 0), strict=True)
        )


class TestTripPoints:
    def test_a_point_inside_a_circle_is_kept_off_the_underpass(self) -> None:
        from core.routing import circle_park_filter

        assert circle_park_filter(*DUPONT) == {"search_filter": {"exclude_tunnel": True}}
        assert circle_park_filter(*OUTSIDE) == {}
