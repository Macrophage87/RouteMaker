"""core.mtb.settle: the Mountain Bike ride type's choice among the router's routes and its
rounds of excluding harder trails (docs/MTB-TOPO-PLAN.md, slice 6), with the router and the
traces faked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import mtb, routing
from routemaker import mtbmode
from routemaker.mtbmode import Stretch


def road(metres, tier=2):
    return Stretch(metres=metres, tier=tier, trail=False, singletrack=False, level=None)


def single(metres, level=2):
    return Stretch(metres=metres, tier=1, trail=True, singletrack=True, level=level)


def piece(lon, lat, metres=100.0):
    return SimpleNamespace(lon=lon, lat=lat, metres=metres, way_id=1)


@pytest.fixture
def readings(monkeypatch):
    """Each trip carries its own stretches and pieces; reading_of reads them."""

    def reading_of(trip, variant, costing, when, deadline, traces, max_level):
        if trip.get("untraced"):
            return None
        stretches = trip["stretches"]
        pieces = trip.get("pieces") or [
            piece(-77.0 + i * 0.01, 38.9) for i in range(len(stretches))
        ]
        return mtbmode.read(stretches, max_level), pieces, stretches

    monkeypatch.setattr(mtb, "reading_of", reading_of)


def trip(name, stretches, **extra):
    return {"name": name, "legs": [{"shape": ""}], "stretches": stretches, **extra}


FAR_POINTS = [(-80.0, 30.0), (-80.1, 30.0)]


def settle(trips, max_level=2, points=FAR_POINTS):
    return mtb.settle(
        trips, trips[0], {"locations": []}, "mtb", {}, "weekend", None, {}, max_level, points
    )


def test_the_trail_rich_route_wins_at_half_weight(readings) -> None:
    roads = trip("roads", [road(1609)])
    trails = trip("trails", [single(2800)])
    chosen, info = settle([roads, trails])
    assert chosen["name"] == "trails"
    assert info["candidates"] == 2 and info["rounds"] == 0 and info["limited"] is None
    assert info["singletrack_m"] == 2800.0 and info["over_level_m"] == 0.0


def test_a_harder_trail_ranks_below_any_route_without_one(readings) -> None:
    hard = trip("hard", [single(500, level=3)])
    long_easy = trip("easy", [road(4000), single(1000)])
    chosen, info = settle([hard, long_easy])
    assert chosen["name"] == "easy" and info["rounds"] == 0


def test_rounds_exclude_the_harder_trail_and_ask_again(readings, monkeypatch) -> None:
    hard = trip("hard", [road(200), single(800, level=4), road(200)])
    asked = []

    def route(variant, request, deadline):
        asked.append(request)
        return {"trip": trip("round", [road(1500), single(400)])}, False

    monkeypatch.setattr(routing, "_route", route)
    chosen, info = settle([hard])
    assert chosen["name"] == "round"
    assert info["rounds"] == 1 and info["limited"] is None and info["over_level_m"] == 0.0
    excluded = asked[0]["exclude_locations"]
    assert excluded and all(set(p) == {"lon", "lat"} for p in excluded)
    assert "alternates" not in asked[0]


def test_nothing_to_exclude_near_the_points_is_no_way_round(readings, monkeypatch) -> None:
    """A harder trail at the start: it cannot be excluded (the router must leave from it),
    so the route is answered and says how much."""
    hard = trip("hard", [single(800, level=4)], pieces=[piece(-80.0, 30.0)])
    monkeypatch.setattr(routing, "_route", lambda *a: pytest.fail("nothing to exclude"))
    chosen, info = settle([hard])
    assert chosen is hard
    assert info["limited"] == "no_way_round" and info["over_level_m"] == 800.0


def test_a_refused_round_keeps_the_best_so_far(readings, monkeypatch) -> None:
    hard = trip("hard", [road(100), single(800, level=3)])

    def refuse(*args):
        raise routing.RouterRefused(400, 442, "no path")

    monkeypatch.setattr(routing, "_route", refuse)
    chosen, info = settle([hard])
    assert chosen is hard and info["limited"] == "no_way_round" and info["rounds"] == 1


def test_rounds_stop_at_the_limit(readings, monkeypatch) -> None:
    hard = trip("hard", [road(100), single(800, level=4)])
    monkeypatch.setattr(
        routing,
        "_route",
        lambda *a: ({"trip": trip("still", [road(100), single(700, level=4)])}, False),
    )
    chosen, info = settle([hard])
    assert info["rounds"] == mtb.LEVEL_ROUNDS
    assert chosen["name"] == "still" and info["over_level_m"] == 700.0


def test_an_untraced_route_is_said(readings) -> None:
    chosen, info = settle([trip("x", [], untraced=True)])
    assert info["limited"] == "untraced" and info["candidates"] == 0


def test_the_level_is_clamped_and_defaults_to_2(readings) -> None:
    assert settle([trip("a", [road(10)])], max_level=None)[1]["max_level"] == 2
    assert settle([trip("a", [road(10)])], max_level=9)[1]["max_level"] == 4
