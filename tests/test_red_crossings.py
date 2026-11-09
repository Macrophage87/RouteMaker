"""The way round a red (very high stress) crossing on a plan the crossing search did not
cover (`core.red_crossings`), with the router and the route's reading replaced.

The owner, 2026-11-08, of a long Mount Vernon ride that crossed the GW Parkway at grade at
Tulane Dr with no signal, drawn red and not avoided: "It's taking people onto dangerous
intersections."

The routes here are real lines (encoded as the router encodes them) running east along
`BASE`'s latitude, so the pass can cut a stretch out of them and splice a way round in. A
red crossing is at the point `event(m)` gives, which is on the line.
"""

from __future__ import annotations

import dataclasses

import pytest
from test_refine import BASE, analysis, context, event

from core import dedodge, red_crossings, refine, routing
from routemaker import intersections as model

# A red crossing 20 km into a 40 km route, clear of both ends.
RED = event(20_000.0, cost_ft=3300.0)
# One step of the line, in `event`'s units (1e-5 degree of longitude a metre).
STEP = 500.0


def east(start: float, end: float, lat: float = BASE[1]) -> list[tuple[float, float]]:
    """A line east along `lat` from `start` to `end` (event metres), a vertex a STEP."""
    n = int(round((end - start) / STEP))
    return [(BASE[0] + (start + k * STEP) * 1e-5, lat) for k in range(n + 1)]


THROUGH = east(0.0, 40_000.0)


def trip_of_line(points, km: float, cost: float = 0.0, legs: int = 1) -> dict:
    """A trip along `points`, cut into `legs` equal legs."""
    if legs == 1:
        cuts = [points]
    else:
        size = (len(points) - 1) // legs
        cuts = [points[k * size : (k + 1) * size + 1] for k in range(legs - 1)]
        cuts.append(points[(legs - 1) * size :])
    return {
        "legs": [
            {
                "shape": dedodge.encode_polyline6(cut),
                "summary": {"length": km / legs, "time": 100.0 * km / legs, "cost": cost / legs},
            }
            for cut in cuts
        ],
        "summary": {"length": km, "time": 100.0 * km, "cost": cost},
    }


def round_leg(a, b, km: float, lat_off: float = 0.002) -> dict:
    """The router's leg from `a` to `b`, a little north of the line between them."""
    points = [a, (a[0], a[1] + lat_off), (b[0], b[1] + lat_off), b]
    leg = {"shape": dedodge.encode_polyline6(points), "summary": {"length": km}}
    return {"legs": [leg], "summary": {"length": km}}


def detoured(trip: dict) -> bool:
    return any(
        lat > BASE[1] + 1e-4
        for leg in trip["legs"]
        for _lon, lat in routing.decode_polyline6(leg["shape"])
    )


class Router:
    """The router (`answers`: called with each request, returns a trip or raises) and the
    reading of each route (`read`: called with the trip)."""

    def __init__(self, monkeypatch, read, answers) -> None:
        self.read = read
        self.answers = answers
        self.asked: list[dict] = []
        monkeypatch.setattr(refine, "analyse", lambda trip, ctx, deadline: self.read(trip))
        monkeypatch.setattr(routing, "_call", self.call)

    def call(self, variant, endpoint, payload, deadline):
        assert endpoint == "route"
        self.asked.append(payload)
        answer = self.answers(payload)
        if isinstance(answer, Exception):
            raise answer
        return {"trip": answer}


def window_answer(km: float = 4.4):
    """The router's way round for a window ask: from its first location to its last."""

    def answer(payload):
        if len(payload["locations"]) != 2 or payload["locations"][0].get("type") != "break":
            raise routing.RouterRefused(400, 442, "no path")
        a, b = payload["locations"]
        return round_leg((a["lon"], a["lat"]), (b["lon"], b["lat"]), km)

    return answer


def plain_through():
    return trip_of_line(THROUGH, 40.0)


ROUND_READ = analysis("round", tiers="1" * 401, cost_s=4100.0)
THROUGH_READ = analysis("through", tiers="1" * 400, events=[RED])


def readings(round_read=ROUND_READ, through_read=THROUGH_READ):
    return lambda trip: round_read if detoured(trip) else through_read


# --- What the pass asks for and takes -------------------------------------------------


def test_a_long_plans_red_crossing_is_ridden_round(monkeypatch):
    # Before #1054: a plan the crossing search skipped (past its span) kept the red crossing.
    # A plain plan is first asked whole, every red excluded, as #1054 did.
    ctx = context()
    ctx.request["exclude_locations"] = [{"lon": 1.0, "lat": 2.0}]
    whole_round = round_leg(THROUGH[0], THROUGH[-1], 43.0)
    router = Router(monkeypatch, readings(), lambda payload: whole_round)
    trip, info = red_crossings.settle(plain_through(), ctx, searched=False)
    assert detoured(trip)
    assert info["decision"] == "avoided" and info["avoided"] == 1
    assert info["reds"] == 1 and info["reds_after"] == 0
    (asked,) = router.asked
    # The request's own exclusions are kept (P1b), and the red's node is excluded with a
    # 3 m radius, not the 15 m that took out the sidepath beside it (J6).
    assert asked["exclude_locations"] == [
        {"lon": 1.0, "lat": 2.0},
        {"lon": RED.lon, "lat": RED.lat, "radius": refine.CROSSING_EXCLUDE_RADIUS_M},
    ]
    assert refine.CROSSING_EXCLUDE_RADIUS_M == 3
    assert "alternates" not in asked
    assert ctx.red_excludes == [
        {"lon": RED.lon, "lat": RED.lat, "radius": refine.CROSSING_EXCLUDE_RADIUS_M}
    ]


def test_a_red_with_no_way_round_no_longer_keeps_the_others(monkeypatch):
    # Before (S1): one ask with both reds excluded; the router found no route past the one
    # with no way round, and both reds stayed. After: that ask, then each red alone by its
    # own stretch, the worst first: the avoidable one is ridden round, the other kept.
    stuck = event(30_000.0, cost_ft=3200.0)
    worst = event(12_000.0, cost_ft=4000.0)
    both = analysis("through", tiers="1" * 400, events=[worst, stuck])
    one = analysis("round", tiers="1" * 401, cost_s=4100.0, events=[stuck])

    def answers(payload):
        excluded = {(e["lon"], e["lat"]) for e in payload["exclude_locations"]}
        if (stuck.lon, stuck.lat) in excluded:
            raise routing.RouterRefused(400, 442, "no path")
        return window_answer()(payload)

    router = Router(monkeypatch, lambda trip: one if detoured(trip) else both, answers)
    trip, info = red_crossings.settle(plain_through(), context(), searched=False)
    assert detoured(trip)
    assert info["decision"] == "avoided"
    assert info["avoided"] == 1 and info["no_way_round"] == 1 and info["reds_after"] == 1
    # The whole-plan ask first, then the worst red's own window (it is ridden round at once).
    whole, first_window = router.asked[0], router.asked[1]
    assert len(whole["exclude_locations"]) == 2
    assert {(e["lon"], e["lat"]) for e in first_window["exclude_locations"]} == {
        (worst.lon, worst.lat)
    }
    # The way round's ends are on the route, either side of the red, facing along it.
    a, b = first_window["locations"]
    assert a["lon"] < worst.lon < b["lon"] and a["type"] == b["type"] == "break"
    assert a["heading"] == b["heading"] == 90


def test_the_widest_window_is_tried_where_the_narrow_finds_no_way_round(monkeypatch):
    def answers(payload):
        a, b = payload["locations"]
        if b["lon"] - a["lon"] < 2 * red_crossings.WINDOWS_M[1] * 1e-5 * 0.9:
            raise routing.RouterRefused(400, 442, "no path")
        return window_answer()(payload)

    ctx = context()
    ctx.seek_climb = True  # not a plain plan: windows only
    router = Router(monkeypatch, readings(), answers)
    trip, info = red_crossings.settle(plain_through(), ctx, searched=False)
    assert detoured(trip) and info["avoided"] == 1
    # The narrow window facing the route and without headings, then the wide one.
    assert len(router.asked) == 3


def test_a_loop_has_its_reds_ridden_round_and_keeps_its_way_back(monkeypatch):
    # Before (R1, H4): `if not loop` skipped the pass, and a loop past about 15 km out had
    # no crossing search either. After: each red by its own stretch of the loop; the rest of
    # the route, the way back `make_loop` made among it, is untouched.
    out_and_back = trip_of_line(THROUGH, 40.0, legs=2)
    ctx = context()
    ctx.loop_overlap = 0.1
    out_red = event(10_000.0)
    loop_read = dataclasses.replace(THROUGH_READ, events=[out_red], via_m=[20_000.0])
    router = Router(monkeypatch, readings(through_read=loop_read), window_answer())
    trip, info = red_crossings.settle(out_and_back, ctx, searched=False, loop=True)
    assert info["decision"] == "avoided" and len(router.asked) == 1
    # Never the plan's own request, which would ask the way back again (266).
    assert router.asked[0]["locations"] != ctx.request["locations"]
    # The leg without the red is the loop's own, unchanged.
    assert trip["legs"][1] == out_and_back["legs"][1]
    assert detoured({"legs": [trip["legs"][0]]})


def long_calm_cut_plan():
    """A 40 km plan with no stops as `refine_long` answers it: two cut legs joined, the cut
    at 20.5 km (the search's own break, on the calm trail), a red 300 m before it."""
    near_cut = event(20_200.0, cost_ft=3300.0)
    cut_read = dataclasses.replace(THROUGH_READ, events=[near_cut], via_m=[20_500.0])
    legs = [east(0.0, 20_500.0), east(20_500.0, 40_000.0)]
    trip = {
        "legs": [
            {
                "shape": dedodge.encode_polyline6(cut),
                "summary": {"length": 20.0, "time": 2000.0, "cost": 0.0},
            }
            for cut in legs
        ],
        "summary": {"length": 40.0, "time": 4000.0, "cost": 0.0},
    }
    return trip, cut_read


def test_a_red_near_a_long_plans_cut_is_asked_round(monkeypatch):
    """Hunt 2, P2-1: the red is within ENDPOINT_CLEARANCE_M of a cut, not of a stop the
    rider placed. The leg searches cannot exclude it (it is at a leg's end), and before,
    this pass dropped it too ("reds": 0, nothing asked); the plan answered it."""
    trip, cut_read = long_calm_cut_plan()
    router = Router(monkeypatch, readings(through_read=cut_read), window_answer())
    refined = {"long": {"legs": 2, "stops": [2]}}
    out, info = red_crossings.settle(trip, context(), searched=False, refined=refined)
    assert info["reds"] == 1 and len(router.asked) >= 1
    assert info["decision"] == "avoided" and detoured(out)


def test_a_red_near_a_stop_the_rider_placed_is_asked_round(monkeypatch):
    """Routing hunt 4, J4-1: the same boundary as a stop of the rider's own (two legs of one
    each). Before, a red within ENDPOINT_CLEARANCE_M of it was left ("reds": 0)."""
    trip, cut_read = long_calm_cut_plan()
    router = Router(monkeypatch, readings(through_read=cut_read), window_answer())
    refined = {"long": {"legs": 2, "stops": [1, 1]}}
    out, info = red_crossings.settle(trip, context(), searched=False, refined=refined)
    assert info["reds"] == 1 and len(router.asked) >= 1
    assert info["decision"] == "avoided" and detoured(out)


def test_a_loops_way_round_onto_its_way_out_is_refused(monkeypatch):
    out_and_back = trip_of_line(THROUGH, 40.0, legs=2)
    ctx = context()
    ctx.loop_overlap = 0.1
    loop_read = dataclasses.replace(THROUGH_READ, events=[event(10_000.0)], via_m=[20_000.0])
    Router(monkeypatch, readings(through_read=loop_read), window_answer())
    monkeypatch.setattr(refine, "loop_refused", lambda read, ctx: True)
    trip, info = red_crossings.settle(out_and_back, ctx, searched=False, loop=True)
    assert trip is out_and_back and info["decision"] == "kept"


def test_a_climb_seeks_route_is_not_asked_again_from_its_bare_points(monkeypatch):
    # Before (P1): the way round was the plan's request, start and end only, and a flat
    # way round replaced the climb the hill seek chose. After: only the red's own stretch is
    # asked again, and a way round that gives up the climb is refused.
    ctx = context()
    ctx.seek_climb = True
    climb = dataclasses.replace(THROUGH_READ, climb_m=300.0)
    flat = dataclasses.replace(ROUND_READ, climb_m=100.0)
    router = Router(monkeypatch, readings(flat, climb), window_answer())
    trip, info = red_crossings.settle(plain_through(), ctx, searched=False)
    assert not detoured(trip) and info["decision"] == "kept"
    assert all(len(asked["locations"]) == 2 for asked in router.asked)
    assert all(asked["locations"][0].get("type") == "break" for asked in router.asked)


def test_mountain_bikes_level_exclusions_go_with_every_ask(monkeypatch):
    # Before (P1b): the ask dropped every exclusion the request had and Mountain Bike's
    # rounds had made, so the way round could be a trail above the rider's level.
    ctx = context()
    level = {"lon": -77.1, "lat": 38.95}
    ctx.level_excludes = [level]
    router = Router(monkeypatch, readings(), window_answer())
    red_crossings.settle(plain_through(), ctx, searched=False)
    assert router.asked and all(level in asked["exclude_locations"] for asked in router.asked)


def test_a_capped_trail_crossing_that_costs_a_red_is_asked_round(monkeypatch):
    # Before (J1): an unsignalised trail crossing of a fast arterial is drawn orange (item
    # 185) and the pass read only the colour. After: its red-level cost counts.
    capped = dataclasses.replace(
        RED, cost_ft=5280.0, severity=model.ORANGE, max_severity=model.ORANGE
    )
    through = analysis("through", tiers="1" * 400, events=[capped])
    router = Router(monkeypatch, readings(through_read=through), window_answer())
    trip, info = red_crossings.settle(plain_through(), context(), searched=False)
    assert info["reds"] == 1 and detoured(trip) and router.asked
    # An orange crossing that costs an orange is still not a red.
    plain_orange = dataclasses.replace(RED, cost_ft=1500.0, severity=model.ORANGE)
    assert red_crossings.reds_of(analysis("o", events=[plain_orange])) == []


def test_the_splice_keeps_the_route_either_side_and_scales_the_summary():
    leg = trip_of_line(THROUGH, 40.0)["legs"][0]
    leg["elevation"] = [float(k) for k in range(1400)]
    shape = routing.decode_polyline6(leg["shape"])
    i, j = red_crossings.stretch(shape, RED, 2000.0)
    assert shape[i][0] < RED.lon < shape[j][0]
    sub = round_leg(shape[i], shape[j], 5.0)["legs"][0]
    new = red_crossings.splice_leg(leg, shape, i, j, sub, 30.0)
    points = routing.decode_polyline6(new["shape"])

    def rounded(line):
        return [(round(x, 6), round(y, 6)) for x, y in line]

    assert rounded(points[:i]) == rounded(shape[:i])
    assert rounded(points[-3:]) == rounded(shape[-3:])
    share = (j - i) / (len(shape) - 1)
    assert new["summary"]["length"] == pytest.approx(40.0 * (1 - share) + 5.0)
    # A way round whose ends are not the stretch's is no splice.
    off = round_leg((shape[i][0], shape[i][1] + 0.01), shape[j], 5.0)["legs"][0]
    assert red_crossings.splice_leg(leg, shape, i, j, off, 30.0) is None


# --- When it does nothing ---------------------------------------------------------------


def test_a_plan_the_search_covered_is_left_alone(monkeypatch):
    router = Router(monkeypatch, readings(), window_answer())
    trip = plain_through()
    assert red_crossings.settle(trip, context(), searched=True) == (trip, None)
    assert router.asked == []


def test_a_mass_ride_keeps_its_crossings(monkeypatch):
    router = Router(monkeypatch, readings(), window_answer())
    trip = plain_through()
    assert red_crossings.settle(trip, context(group=True), searched=False) == (trip, None)
    assert router.asked == []


def test_no_red_crossing_asks_nothing(monkeypatch):
    router = Router(monkeypatch, lambda trip: analysis("through"), window_answer())
    trip = plain_through()
    out, info = red_crossings.settle(trip, context(), searched=False)
    assert out is trip and info["reds"] == 0 and router.asked == []


@pytest.mark.parametrize("at_m", [300.0, 39_700.0])
def test_a_red_crossing_near_the_start_or_the_end_is_asked_round(monkeypatch, at_m):
    """Routing hunt 4, J4-1: a red 300 m from the start (or the end), the arterial crossing
    nearest the rider's home, was never asked round, even where the way round cost nothing.
    Now it is, by a stretch clipped at the leg's end."""
    near = dataclasses.replace(THROUGH_READ, events=[event(at_m)])
    router = Router(monkeypatch, readings(through_read=near), window_answer())
    trip = plain_through()
    out, info = red_crossings.settle(trip, context(), searched=False)
    assert info["reds"] == 1 and info["decision"] == "avoided" and detoured(out)
    window = router.asked[-1]["locations"]
    ends = THROUGH[0] if at_m < 20_000.0 else THROUGH[-1]
    assert any((p["lon"], p["lat"]) == pytest.approx(ends) for p in window)


def test_a_red_at_a_cul_de_sacs_only_exit_is_dropped_and_the_next_tried(monkeypatch):
    """J4-1: a red near the start with no way round (the router finds no route without it)
    is left, and the next red is still ridden round."""
    near = event(300.0, cost_ft=4000.0)
    through = dataclasses.replace(THROUGH_READ, events=[near, RED])
    round_read = analysis("round", tiers="1" * 401, cost_s=4100.0, events=[near])
    window = window_answer()

    def answer(payload):
        if any(p["lon"] == near.lon for p in payload["exclude_locations"]):
            raise routing.RouterRefused(400, 442, "no path")
        return window(payload)

    Router(monkeypatch, readings(round_read, through), answer)
    out, info = red_crossings.settle(plain_through(), context(), searched=False)
    assert info["reds"] == 2 and info["no_way_round"] == 1
    assert info["decision"] == "avoided" and info["reds_after"] == 1 and detoured(out)


def test_a_way_round_onto_a_busy_road_is_refused(monkeypatch):
    # The way round trades the crossing for 2 km of LTS 4: the Traffic-wins guard keeps it.
    busy = analysis("round", tiers="1" * 200 + "4" * 200, cost_s=4000.0)
    Router(monkeypatch, readings(busy), window_answer())
    trip, info = red_crossings.settle(plain_through(), context(), searched=False)
    assert not detoured(trip)
    assert info["decision"] == "kept" and info["reds_after"] == 1


def test_a_way_round_with_as_many_reds_is_refused(monkeypatch):
    other = analysis("round", tiers="1" * 401, events=[event(25_000.0)])
    Router(monkeypatch, readings(other), window_answer())
    trip, info = red_crossings.settle(plain_through(), context(), searched=False)
    assert not detoured(trip) and info["decision"] == "kept"


@pytest.mark.parametrize(
    "failure, limited",
    [
        (routing.RouterRefused(400, 442, "no path"), "no_route"),
        (routing.DeadlineExceeded(), "time"),
        (routing.RouterUnavailable("down"), "time"),
    ],
)
def test_the_router_failing_keeps_the_route(monkeypatch, failure, limited):
    Router(monkeypatch, readings(), lambda payload: failure)
    trip = plain_through()
    out, info = red_crossings.settle(trip, context(), searched=False)
    assert out is trip and info["limited"] == limited


def test_no_time_left_asks_nothing(monkeypatch):
    router = Router(monkeypatch, readings(), window_answer())
    ctx = context()
    ctx.deadline = routing.Deadline(routing.clock() + refine.REFINE_TRACE_RESERVE_S + 1, 30)
    trip, info = red_crossings.settle(plain_through(), ctx, searched=False)
    assert info["limited"] == "time" and router.asked == []


def test_the_asks_are_bounded(monkeypatch):
    many = [event(4_000.0 + 3_000.0 * k, cost_ft=3300.0 + k) for k in range(10)]
    router = Router(
        monkeypatch,
        lambda trip: analysis("through", tiers="1" * 400, events=many),
        lambda payload: routing.RouterRefused(400, 442, "no path"),
    )
    trip, info = red_crossings.settle(plain_through(), context(), searched=False)
    assert len(router.asked) == red_crossings.MAX_ASKS and info["limited"] == "asks"


def test_a_way_round_past_the_ceiling_is_refused_below_the_top(monkeypatch):
    # The search's own rounds refuse a route past the ceiling at every rate: so does this.
    ctx = context(ceiling_m=40_050.0)
    Router(monkeypatch, readings(), window_answer())
    trip, info = red_crossings.settle(plain_through(), ctx, searched=False)
    assert not detoured(trip) and info["decision"] == "kept"


def test_a_swap_restates_the_searchs_figures(monkeypatch):
    Router(monkeypatch, readings(), window_answer())
    refined = {"extra_distance_m": 100.0, "exposure_after_m": 999.0, "lts4_m_after": 50.0}
    red_crossings.settle(plain_through(), context(), searched=False, refined=refined)
    assert refined == {"extra_distance_m": 200.0, "exposure_after_m": 0.0, "lts4_m_after": 0.0}


def test_a_route_mountain_bikes_choice_swapped_in_is_not_counted_as_searched():
    # Before (S4): the flag read the search's figures alone, so a router alternative
    # `mtb.settle` answered in place of the searched route was never asked round its reds.
    searched = {"rounds": 2, "limited": None}
    assert routing.searched_route(searched)
    assert not routing.searched_route(searched, replaced=True)
    assert not routing.searched_route({"rounds": 0, "limited": None})
    assert not routing.searched_route({"rounds": 3, "limited": "time"})
    assert not routing.searched_route(None)
