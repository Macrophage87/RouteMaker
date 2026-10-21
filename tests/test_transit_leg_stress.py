"""Every ride of a transit trip coloured by traffic stress (v0.7.0; Stephen: "When a trip includes
a mix of modes, it doesn't seem to include the LTS of the section towards the destination").

The answer's own line is the chosen option's first ride, routed by `routing.plan`; each later ride
(own bike from the exit station, or the far end's share bike) is now routed the same way, beside
it, and its step in the `transit` block carries its routed line and `stress_spans`. A later ride
the router does not answer in time keeps its plain line, and the plan never fails for it.
"""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from test_route_api import router, segments, standard_router
from test_transit import CAPITOL_HILL, DOWNTOWN, SHARE, installed, post_transit

from core import api, gbfs, parallel, presets, routing, transit

# The fixtures these tests take by name.
FIXTURES = (router, segments, installed)


@pytest.fixture(autouse=True)
def pooled(router, settings):
    """The later rides run on the router pool here, which these tests tell apart by
    `parallel.inside()`: test_route_api's router fixture runs calls in turn, so put the pool
    back."""
    settings.ROUTER_PARALLEL_CALLS = 3


db = pytest.mark.django_db(transaction=True)


def later_leg() -> bool:
    """Whether this router call is a later ride's (they run on the router pool, core.parallel)."""
    return parallel.inside()


def metro_key(client) -> str:
    trip = post_transit(client, [CAPITOL_HILL, DOWNTOWN]).json()["transit"]
    return next(o for o in trip["options"] if not o["direct"])["key"]


@db
@pytest.mark.usefixtures("weekday_clock")
class TestLaterRides:
    def test_the_ride_to_the_destination_is_routed_and_coloured_like_the_first(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        router(standard_router())
        real = routing.plan
        seen: list[tuple[str, list, dict]] = []

        def spy(points, preset_name, long_ride=False, started=None, dials=None):
            answered = real(points, preset_name, long_ride=long_ride, started=started, dials=dials)
            kind = "later" if later_leg() else "line"
            seen.append((kind, points, {"preset": preset_name, "dials": dials, "started": started}))
            seen[-1][2]["answer"] = answered
            return answered

        monkeypatch.setattr(routing, "plan", spy)
        key = metro_key(client)
        seen.clear()
        response = post_transit(
            client, [CAPITOL_HILL, DOWNTOWN], transit_option=key, closure_bypass=["c1"]
        )
        assert response.status_code == 200, response.content
        body = response.json()
        steps = body["transit"]["steps"]
        assert [s["mode"] for s in steps] == ["ride", "enter", "metro", "exit", "ride"]
        line = next(s for s in seen if s[0] == "line")
        later = [s for s in seen if s[0] == "later"]
        assert len(later) == 1
        _kind, points, call = later[0]
        # The same ride type, dials (the closure bypass among them) and budget as the first.
        assert call["preset"] == line[2]["preset"] and call["dials"] == line[2]["dials"]
        assert call["dials"].closure_bypass == ("c1",) and call["started"] == line[2]["started"]
        # The last step is drawn as routed, with its stress sections in the main line's form.
        last = steps[-1]
        assert not last["route_line"]
        answer = call["answer"]
        assert last["coordinates"] == answer["geometry"]["coordinates"]
        assert (
            last["stress_spans"] == [{"rpm": None, "rough": None, **span} for span in answer["stress_spans"]]
            and last["stress_spans"]
        )
        assert set(last["stress_spans"][0]) == set(body["stress_spans"][0])
        assert len(points) == 2  # the leg's two ends, as the first ride is asked
        # Timed as routed, as the first ride is; the total follows.
        assert last["seconds"] == round(answer["duration_s"])
        assert steps[0]["seconds"] == round(body["duration_s"])
        # The first ride's step is still the body's own line.
        assert steps[0]["route_line"] and steps[0]["coordinates"] == []
        assert steps[0].get("stress_spans") is None

    def test_novice_legs_route_the_later_ride_as_novice_too(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        router(standard_router())
        real = routing.plan
        presets_seen = []

        def spy(points, preset_name, **kwargs):
            presets_seen.append((later_leg(), preset_name))
            return real(points, preset_name, **kwargs)

        monkeypatch.setattr(routing, "plan", spy)
        key = metro_key(client)
        presets_seen.clear()
        response = post_transit(
            client, [CAPITOL_HILL, DOWNTOWN], transit_option=key, novice_legs=True
        )
        assert response.status_code == 200, response.content
        assert (True, presets.NOVICE) in presets_seen and (False, presets.NOVICE) in presets_seen
        assert response.json()["preset"] == presets.BIKE_TRANSIT

    def test_a_later_ride_that_times_out_keeps_its_plain_line_and_the_plan_stands(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        router(standard_router())
        real = routing.plan

        def late_for_later(points, preset_name, **kwargs):
            if later_leg():
                raise routing.DeadlineExceeded("the router did not answer in time")
            return real(points, preset_name, **kwargs)

        monkeypatch.setattr(routing, "plan", late_for_later)
        key = metro_key(client)
        response = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=key)
        assert response.status_code == 200, response.content
        body = response.json()
        last = body["transit"]["steps"][-1]
        # The plain line the search found (the fixture's router: the leg's two ends).
        assert len(last["coordinates"]) == 2 and last.get("stress_spans") is None
        # The answer's own line is routed as ever, and nothing says it was not.
        assert len(body["stress_spans"]) >= 1 and api.UNROUTED_NOTE not in body["transit"]["notes"]

    def test_a_later_ride_still_running_at_the_budgets_end_is_let_go(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        router(standard_router())
        real = routing.plan
        release = threading.Event()

        def hangs(points, preset_name, **kwargs):
            if later_leg():
                release.wait(20)
                raise routing.RouterUnavailable("never answered")
            return real(points, preset_name, **kwargs)

        key = metro_key(client)
        monkeypatch.setattr(routing, "plan", hangs)
        # A budget of two seconds for the routers, so the wait is short.
        monkeypatch.setattr(routing, "PLAN_BUDGET_S", routing.ANSWER_RESERVE_S + 2)
        try:
            started = routing.clock()
            response = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=key)
            took = routing.clock() - started
        finally:
            release.set()
        assert response.status_code == 200, response.content
        assert took < 10
        last = response.json()["transit"]["steps"][-1]
        assert len(last["coordinates"]) == 2 and last.get("stress_spans") is None

    def test_any_failure_of_a_later_ride_is_never_the_plans(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        router(standard_router())
        real = routing.plan

        def refused(points, preset_name, **kwargs):
            if later_leg():
                raise routing.NoRoute("no route")
            return real(points, preset_name, **kwargs)

        monkeypatch.setattr(routing, "plan", refused)
        key = metro_key(client)
        response = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=key)
        assert response.status_code == 200, response.content
        assert response.json()["transit"]["steps"][-1].get("stress_spans") is None

    def test_the_far_ends_share_bike_is_routed_and_coloured_too(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        """Bikeshare + Transit: a share bike at each end (the fixture's docks give a walk to the
        station, so the walks are made share rides here); the far end's ride is coloured."""
        router(standard_router())
        monkeypatch.setattr(gbfs.client, "snapshot", lambda: SHARE)
        real_plan = transit.plan_bikeshare

        def share_both_ends(*args, **kwargs):
            plan = real_plan(*args, **kwargs)
            options = [
                replace(
                    o,
                    legs=tuple(
                        replace(leg, mode=transit.SHARE, to="A dock")
                        if leg.mode == transit.WALK
                        else leg
                        for leg in o.legs
                    ),
                )
                if o.scheduled
                else o
                for o in plan.options
            ]
            return replace(plan, options=options)

        monkeypatch.setattr(transit, "plan_bikeshare", share_both_ends)
        trip = post_transit(client, [CAPITOL_HILL, DOWNTOWN], presets.BIKESHARE_TRANSIT).json()
        key = next(o for o in trip["transit"]["options"] if not o["direct"])["key"]
        response = post_transit(
            client, [CAPITOL_HILL, DOWNTOWN], presets.BIKESHARE_TRANSIT, transit_option=key
        )
        assert response.status_code == 200, response.content
        steps = response.json()["transit"]["steps"]
        assert steps[0]["mode"] == "bikeshare" and steps[0]["route_line"]
        last = steps[-1]
        assert last["mode"] == "bikeshare" and not last["route_line"]
        assert last["stress_spans"] and len(last["coordinates"]) >= 2


@db
@pytest.mark.usefixtures("weekday_clock")
@pytest.mark.parametrize("bound", [1, 2, 3])
def test_a_transit_plan_keeps_to_the_router_pools_bound(
    client, segments, router, installed, monkeypatch, settings, bound
) -> None:
    """The later rides run on the router pool (`core.parallel`), not a pool of their own, so a
    transit request never has more than ROUTER_PARALLEL_CALLS + 1 router calls in flight (the
    pool's threads and the request's own). With the pool off they run in turn after the line."""
    import time

    settings.ROUTER_PARALLEL_CALLS = bound
    fake = router(standard_router())
    lock = threading.Lock()
    state = {"now": 0, "most": 0}

    def slow(url, payload, timeout):
        with lock:
            state["now"] += 1
            state["most"] = max(state["most"], state["now"])
        try:
            time.sleep(0.02)
            return fake(url, payload, timeout)
        finally:
            with lock:
                state["now"] -= 1

    real = routing.plan
    order: list[str] = []

    def spy(points, preset_name, **kwargs):
        order.append("later" if later_leg() else "line")
        return real(points, preset_name, **kwargs)

    key = metro_key(client)
    monkeypatch.setattr(routing, "_transport", slow)
    monkeypatch.setattr(routing, "plan", spy)
    state["most"] = 0
    response = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=key)
    assert response.status_code == 200, response.content
    assert response.json()["transit"]["steps"][-1]["stress_spans"]
    assert 1 <= state["most"] <= max(1, bound) + (1 if bound > 1 else 0)
    if bound == 1:
        assert order == ["line", "line"]  # the later ride, in turn, on the request's thread
    else:
        assert sorted(order) == ["later", "line"]


def test_with_rides_times_each_routed_ride_and_keeps_walks() -> None:
    from datetime import date

    moment = transit._moment(
        transit.day_zero(date(2026, 9, 30)).replace(hour=12), date(2026, 9, 30)
    )
    legs = (
        transit.Leg(transit.RIDE, 300.0, ((0.0, 0.0), (0.01, 0.0)), estimated=True),
        transit.Leg(transit.METRO, 600.0, wait_s=120.0, system="Metro"),
        transit.Leg(transit.WALK, 60.0, ((0.02, 0.0), (0.021, 0.0))),
        transit.Leg(transit.RIDE, 400.0, ((0.03, 0.0), (0.04, 0.0)), estimated=True),
    )
    plan = transit.Plan(presets.BIKE_TRANSIT, [transit.Option("x", legs)], moment, [])
    timed = transit.with_rides(plan, {0: 360.0, 2: 999.0, 3: 500.0})
    out = timed.option.legs
    assert [leg.seconds for leg in out] == [360.0, 600.0, 60.0, 500.0]
    assert not out[0].estimated and not out[3].estimated
    assert timed.option.total_s == pytest.approx(360 + 600 + 120 + 60 + 500)
    # The one-ride form is the same thing for the route line alone.
    assert transit.with_ride(plan, 360.0).option.legs[3].seconds == 400.0
