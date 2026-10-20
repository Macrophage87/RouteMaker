"""The major road an unnamed service road, path or sidewalk runs beside (`core.beside_roads`;
the owner, 2026-10-20: "When going on a service road, especially next to a major road, say
so"): read from the router's `/locate` at plan time. Pure: the router is a stand-in."""

from __future__ import annotations

import pytest

from core import beside_roads
from core.dedodge import encode_polyline6
from core.routing import Piece
from routemaker import describe

# East-West Highway near Rock Creek Forest Elementary runs about north-east.
HIGHWAY = [(-77.0600, 38.9910), (-77.0560, 38.9940)]


def edge(way_id, names, cls="primary", shape=HIGHWAY, distance=18.0, link=False, at=None):
    lon, lat = at or ((shape[0][0] + shape[-1][0]) / 2, (shape[0][1] + shape[-1][1]) / 2)
    return {
        "correlated_lon": lon,
        "correlated_lat": lat,
        "distance": distance,
        "edge": {"classification": {"classification": cls, "link": link, "use": "road"}},
        "edge_info": {"way_id": way_id, "names": names, "shape": encode_polyline6(shape)},
    }


def service_pieces(way_id=77, use="service_road", n=6, metres=20.0, names=()):
    """A service road a little south-east of the highway, ridden north-east."""
    step = ((HIGHWAY[1][0] - HIGHWAY[0][0]) / n, (HIGHWAY[1][1] - HIGHWAY[0][1]) / n)
    return [
        Piece(
            way_id,
            HIGHWAY[0][0] + 0.0002 + step[0] * (i + 0.5),
            HIGHWAY[0][1] - 0.0001 + step[1] * (i + 0.5),
            metres,
            names=names,
            use=use,
            heading_in=45.0,
            heading_out=45.0,
        )
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def empty_cache():
    beside_roads._cache.clear()
    yield
    beside_roads._cache.clear()


class TestRoadBeside:
    def test_the_nearest_parallel_major_road_is_named(self):
        edges = [
            edge(77, [], cls="service_other", distance=0.0),
            edge(5, ["MD 410", "East-West Highway"], distance=22.0),
            edge(6, ["Grubb Road"], cls="tertiary", shape=[(-77.058, 38.990), (-77.058, 38.995)]),
        ]
        assert beside_roads.road_beside(edges, 77, 45.0) == "East-West Highway"
        # Ridden the other way it is still beside it.
        assert beside_roads.road_beside(edges, 77, 225.0) == "East-West Highway"

    def test_a_crossing_road_a_minor_road_a_ramp_or_one_too_far_is_not(self):
        north = [(-77.058, 38.990), (-77.058, 38.995)]
        ew = ["East-West Highway"]
        for edges in (
            [edge(6, ["Grubb Road"], cls="tertiary", shape=north)],
            [edge(5, ["Ellingson Drive"], cls="residential")],
            [edge(5, ew, link=True)],
            [edge(5, ew, distance=45.0)],
            [edge(5, [])],
        ):
            assert beside_roads.road_beside(edges, 77, 45.0) is None


class TestNamesOf:
    def test_a_service_road_is_named_for_the_highway_beside_it(self, monkeypatch):
        asked = []

        def locate(spots, timeout_s):
            asked.append(spots)
            return [[edge(5, ["East-West Highway"])] for _ in spots]

        monkeypatch.setattr(beside_roads, "_locate", locate)
        pieces = service_pieces()
        assert beside_roads.names_of(pieces) == {77: "service road beside East-West Highway"}
        assert len(asked) == 1
        # Asked again (another route over it), the answer is remembered.
        assert beside_roads.names_of(pieces) == {77: "service road beside East-West Highway"}
        assert len(asked) == 1

    def test_a_sidewalk_and_a_path_are_named_so(self, monkeypatch):
        monkeypatch.setattr(
            beside_roads,
            "_locate",
            lambda spots, t: [[edge(5, ["East-West Highway"])] for _ in spots],
        )
        sidewalk = beside_roads.names_of(service_pieces(use="sidewalk"))
        assert sidewalk == {77: "sidewalk beside East-West Highway"}
        path = beside_roads.names_of(service_pieces(way_id=78, use="cycleway"))
        assert path == {78: "path beside East-West Highway"}

    def test_named_ways_short_runs_and_plain_roads_are_not_asked(self, monkeypatch):
        def locate(*args):
            raise AssertionError("not asked")

        monkeypatch.setattr(beside_roads, "_locate", locate)
        assert beside_roads.names_of(service_pieces(use="cycleway", names=("Spencer Road",))) == {}
        assert beside_roads.names_of(service_pieces(n=1, metres=20.0)) == {}
        assert beside_roads.names_of(service_pieces(use="road")) == {}
        assert beside_roads.names_of(service_pieces(use="alley")) == {}
        # A path the rebuild named for its street keeps that name.
        named = {77: "X Street bike lane"}
        assert beside_roads.names_of(service_pieces(use="cycleway"), named) == {}

    def test_a_silent_router_leaves_it_a_service_road(self, monkeypatch):
        def locate(*args):
            raise OSError("down")

        monkeypatch.setattr(beside_roads, "_locate", locate)
        assert beside_roads.names_of(service_pieces()) == {}


class TestOneAsk:
    def test_every_way_is_asked_in_one_request_within_the_budget(self, monkeypatch):
        calls = []

        def locate(spots, timeout_s):
            calls.append((len(spots), timeout_s))
            return [[edge(5, ["East-West Highway"])], []]

        monkeypatch.setattr(beside_roads, "_locate", locate)
        pieces = service_pieces() + service_pieces(way_id=78, use="sidewalk")
        assert beside_roads.names_of(pieces) == {77: "service road beside East-West Highway"}
        assert calls == [(2, beside_roads.BUDGET_S)]

    def test_a_plan_short_of_time_does_not_ask(self, monkeypatch):
        from core import routing

        def locate(*args):
            raise AssertionError("not asked")

        monkeypatch.setattr(beside_roads, "_locate", locate)
        token = routing._plan_ends.set(routing.clock() + 0.1)
        try:
            assert beside_roads.names_of(service_pieces()) == {}
        finally:
            routing._plan_ends.reset(token)


class TestNamedServiceRoads:
    """The owner, 2026-10-20: the frontage road is mapped "East-West Highway" too, and the
    ride said "Turn left onto East-West Highway"."""

    def test_one_with_the_highways_name_is_the_service_road_beside_it(self, monkeypatch):
        monkeypatch.setattr(
            beside_roads,
            "_locate",
            lambda spots, t: [[edge(5, ["MD 410", "East-West Highway"])] for _ in spots],
        )
        found = beside_roads.names_of(service_pieces(names=("East-West Highway",)))
        assert found == {77: "service road beside East-West Highway"}
        assert isinstance(found[77], describe.BesideName)

    def test_one_with_a_name_of_its_own_keeps_it(self, monkeypatch):
        monkeypatch.setattr(
            beside_roads,
            "_locate",
            lambda spots, t: [[edge(5, ["East-West Highway"])] for _ in spots],
        )
        assert beside_roads.names_of(service_pieces(names=("Spencer Road",))) == {}

    def test_a_named_path_is_never_asked(self, monkeypatch):
        def locate(*args):
            raise AssertionError("not asked")

        monkeypatch.setattr(beside_roads, "_locate", locate)
        assert (
            beside_roads.names_of(service_pieces(use="cycleway", names=("Rock Creek Trail",))) == {}
        )

    def test_the_description_says_the_beside_name_in_place_of_its_own(self):
        from core import routing

        piece = service_pieces(names=("East-West Highway",))[0]
        name = describe.BesideName("service road beside East-West Highway")
        assert routing._piece_names(piece, {77: name}) == (name,)
        # A street-side name never replaces a way's own name.
        assert routing._piece_names(piece, {77: "X bike lane"}) == ("East-West Highway",)

    def test_a_service_road_carrying_on_in_line_where_its_road_ends_is_not_beside_it(self):
        # Oak Street ends, and a service road also mapped "Oak Street" carries straight on.
        oak = [(-77.0600, 38.9900), (-77.0600, 38.9910)]
        edges = [edge(5, ["Oak Street"], cls="tertiary", shape=oak, distance=25.0, at=oak[1])]
        ahead = (-77.0600, 38.99122)  # 25 m past its end, on its line
        assert beside_roads.road_beside(edges, 77, 0.0, frozenset({"oak street"}), ahead) is None
        beside = (-77.0597, 38.9905)  # 25 m to its side
        assert (
            beside_roads.road_beside(edges, 77, 0.0, frozenset({"oak street"}), beside)
            == "Oak Street"
        )

    def test_the_road_of_its_own_name_wins_over_a_nearer_one(self):
        edges = [
            edge(4, ["Colesville Road"], distance=8.0),
            edge(5, ["East-West Highway"], distance=22.0),
        ]
        same = frozenset({"east-west highway"})
        assert beside_roads.road_beside(edges, 77, 45.0, same) == "East-West Highway"
