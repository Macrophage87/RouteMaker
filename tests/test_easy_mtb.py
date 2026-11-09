"""core.easy_mtb: the "Easy MTB trails" switch on Default and Trailmaxxing (the owner,
2026-11-08): which trails count as easy, the graph it rides, and its rounds off the harder
trails, with the router and the traces faked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import api, easy_mtb, presets, route_cache, routing
from routemaker.mtbmode import Stretch

# --- which trails are easy ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mtb_only", "level", "tags", "easy"),
    [
        # Unrated mountain-bike trails, grass and dirt: "Unknown is typically grass and dirt."
        (True, None, None, True),
        (True, None, {"surface": "dirt"}, True),
        # "yes 0 1 and unknown are counted."
        (True, None, {"mtb:scale": "0"}, True),
        (True, None, {"mtb:scale:imba": "0"}, True),
        (True, 1, {"mtb:scale": "1"}, True),
        (True, None, {"mtb:scale:imba": "1"}, True),
        # Rated 2 or harder stays Mountain Bike only, whichever scale says so, and a rating
        # the singletrack rule does not read (so no `mtb_level` was written) still counts.
        (True, 2, {"mtb:scale": "2"}, False),
        (True, None, {"mtb:scale": "S2"}, False),
        (True, None, {"mtb:scale": "0-2"}, False),
        (True, None, {"mtb:scale": "1", "mtb:scale:imba": "3"}, False),
        (True, 4, None, False),
        # A road or an ordinary path is never a harder trail.
        (False, None, None, True),
        (False, None, {"mtb:scale": "3"}, True),
    ],
)
def test_easy_is_rated_0_or_1_or_unrated(mtb_only, level, tags, easy) -> None:
    assert easy_mtb.is_easy(easy_mtb.level_of(mtb_only, level, tags)) is easy


# --- the graph ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["default", "trailmaxxing"])
@pytest.mark.parametrize("when", ["weekday_offpeak", "weekend"])
def test_on_it_default_and_trailmaxxing_ride_the_offroad_graph(name, when) -> None:
    assert presets.variant_for_ride(name, when, easy_mtb=True) == "offroad"


def test_off_by_default_they_keep_their_own_graphs() -> None:
    assert presets.variant_for_ride("default", "weekday_offpeak") == "standard"
    assert presets.variant_for_ride("trailmaxxing", "weekend") == "weekend"


def test_trails_off_wins_and_other_ride_types_ignore_it() -> None:
    assert presets.variant_for_ride("default", "weekend", trails_off=True, easy_mtb=True) == (
        "no-trail"
    )
    assert presets.variant_for_ride("fast", "weekday_offpeak", easy_mtb=True) == "standard"
    assert presets.EASY_MTB_PRESETS == {"default", "trailmaxxing"}


@pytest.mark.parametrize("name", ["fast", "gravel", "mountain-bike", "mass-ride"])
def test_the_api_takes_it_on_default_and_trailmaxxing_only(name) -> None:
    points = [[-77.04, 38.91], [-77.01, 38.89]]
    assert api.RouteIn(points=points, preset="trailmaxxing", easy_mtb=True).easy_mtb is True
    assert api.RouteIn(points=points, preset=name).easy_mtb is False
    with pytest.raises(ValueError, match="easy_mtb"):
        api.RouteIn(points=points, preset=name, easy_mtb=True)


def test_an_answer_whose_rounds_ran_out_of_time_is_not_kept() -> None:
    body = {"variant": "offroad", "easy_mtb": {"limited": "time"}}
    assert route_cache.keepable(body, "offroad", 0) is False
    assert route_cache.keepable({**body, "easy_mtb": {"limited": None}}, "offroad", 0) is True


# --- the rounds -----------------------------------------------------------------------------


def road(metres):
    return Stretch(metres=metres, tier=None, trail=False, singletrack=False, level=None)


def hard(metres, level=2):
    return Stretch(metres=metres, tier=None, trail=False, singletrack=True, level=level)


def piece(lon, lat, metres=100.0):
    return SimpleNamespace(lon=lon, lat=lat, metres=metres, way_id=1)


@pytest.fixture
def readings(monkeypatch):
    def reading_of(trip, variant, costing, deadline, traces):
        if trip.get("untraced"):
            return None
        stretches = trip["stretches"]
        pieces = trip.get("pieces") or [
            piece(-77.0 + i * 0.01, 38.9) for i in range(len(stretches))
        ]
        return easy_mtb.harder_m(stretches), pieces, stretches

    monkeypatch.setattr(easy_mtb, "reading_of", reading_of)


def trip(name, stretches, **extra):
    return {"name": name, "legs": [{"shape": ""}], "stretches": stretches, **extra}


FAR_POINTS = [(-80.0, 30.0), (-80.1, 30.0)]


def settle(first, points=FAR_POINTS, excludes=None):
    return easy_mtb.settle(
        first, {"locations": [], "alternates": 2}, "offroad", {}, None, {}, points, excludes
    )


def test_an_easy_route_is_kept_as_the_search_chose_it(readings, monkeypatch) -> None:
    monkeypatch.setattr(routing, "_route", lambda *a: pytest.fail("nothing to steer off"))
    easy = trip("easy", [road(500), Stretch(800, None, False, False, None)])
    chosen, info = settle(easy)
    assert chosen is easy
    assert info == {"max_level": 1, "rounds": 0, "harder_m": 0.0, "limited": None}


def test_a_harder_trail_is_excluded_and_the_router_asked_again(readings, monkeypatch) -> None:
    asked = []

    def route(variant, request, deadline):
        asked.append(request)
        return {"trip": trip("round", [road(1500)])}, False

    monkeypatch.setattr(routing, "_route", route)
    excludes: list = []
    chosen, info = settle(trip("hard", [road(200), hard(800, 3), road(200)]), excludes=excludes)
    assert chosen["name"] == "round"
    assert info["rounds"] == 1 and info["harder_m"] == 0.0 and info["limited"] is None
    assert asked[0]["exclude_locations"] and "alternates" not in asked[0]
    # The passes after it keep the same trails out.
    assert excludes == asked[0]["exclude_locations"]


def test_a_harder_trail_with_no_way_round_is_answered_and_said(readings, monkeypatch) -> None:
    monkeypatch.setattr(routing, "_route", lambda *a: pytest.fail("nothing to exclude"))
    first = trip("hard", [hard(800)], pieces=[piece(-80.0, 30.0)])
    chosen, info = settle(first)
    assert chosen is first
    assert info["limited"] == "no_way_round" and info["harder_m"] == 800.0


def test_a_refused_round_keeps_the_route(readings, monkeypatch) -> None:
    def refuse(*args):
        raise routing.RouterRefused(400, 442, "no path")

    monkeypatch.setattr(routing, "_route", refuse)
    first = trip("hard", [road(100), hard(800)])
    chosen, info = settle(first)
    assert chosen is first and info["limited"] == "no_way_round" and info["rounds"] == 1


def test_rounds_stop_at_the_limit_with_the_least_harder_trail(readings, monkeypatch) -> None:
    monkeypatch.setattr(
        routing, "_route", lambda *a: ({"trip": trip("less", [road(100), hard(300)])}, False)
    )
    chosen, info = settle(trip("hard", [road(100), hard(800)]))
    assert info["rounds"] == easy_mtb.ROUNDS
    assert chosen["name"] == "less" and info["harder_m"] == 300.0
    assert info["limited"] == "no_way_round"


def test_a_searched_route_is_not_swapped_for_a_busier_round(readings, monkeypatch) -> None:
    # The third routing hunt, C3-1: the rounds re-ask the plan's own request, so where the
    # route is the calm search's (a via detour, a loop's way back, the target fit), a round's
    # route on harder metres alone threw that work away. Held to `keeps` it is not taken.
    searched = trip("calm loop", [road(200), hard(400), road(200)])
    monkeypatch.setattr(
        routing, "_route", lambda *a: ({"trip": trip("router's own", [road(900)])}, False)
    )
    offered = []

    def keeps(again):
        offered.append(again["name"])
        return False

    excludes: list = []
    chosen, info = easy_mtb.settle(
        searched, {"locations": []}, "offroad", {}, None, {}, FAR_POINTS, excludes, keeps=keeps
    )
    assert chosen is searched
    assert info["harder_m"] == 400.0 and info["limited"] == "no_way_round"
    assert offered and set(offered) == {"router's own"}
    # Nothing it was not answered with is handed to the passes after it.
    assert excludes == []


def test_a_round_the_guard_keeps_replaces_the_searched_route(readings, monkeypatch) -> None:
    searched = trip("calm loop", [road(200), hard(400), road(200)])
    monkeypatch.setattr(routing, "_route", lambda *a: ({"trip": trip("round", [road(900)])}, False))
    chosen, info = easy_mtb.settle(
        searched, {"locations": []}, "offroad", {}, None, {}, FAR_POINTS, keeps=lambda t: True
    )
    assert chosen["name"] == "round" and info["limited"] is None


def test_the_level_round_guard_refuses_busier_longer_or_a_loop_merged(monkeypatch) -> None:
    from test_refine import analysis, context

    from core import refine

    ctx = context(ceiling_m=4000.0)
    searched = analysis("searched", tiers="1" * 30 + "3" * 2)
    assert refine.level_round_kept(analysis("calm", tiers="1" * 32), searched, ctx)
    # Busier past the Traffic-wins allowance.
    assert not refine.level_round_kept(analysis("busy", tiers="1" * 20 + "4" * 12), searched, ctx)
    # Past the ceiling where the searched route was not.
    assert not refine.level_round_kept(analysis("long", tiers="1" * 45), searched, ctx)
    # A loop's way back on its way out.
    ctx.loop_overlap = 0.1
    monkeypatch.setattr(refine, "overlap_share", lambda read: 0.9)
    assert not refine.level_round_kept(analysis("back", tiers="1" * 32), searched, ctx)


def test_the_level_round_guard_refuses_a_route_it_cannot_read(monkeypatch) -> None:
    from test_refine import context

    from core import refine

    def unread(trip, ctx, deadline, with_events=True):
        raise routing.DeadlineExceeded("late")

    monkeypatch.setattr(refine, "analyse", unread)
    assert refine.level_round_keeps({"legs": []}, context())({"legs": []}) is False


def test_an_untraced_route_is_said(readings) -> None:
    first = trip("x", [], untraced=True)
    chosen, info = settle(first)
    assert chosen is first and info["limited"] == "untraced"


def test_no_offroad_graph_is_said() -> None:
    assert easy_mtb.no_graph()["limited"] == "no_offroad_graph"
