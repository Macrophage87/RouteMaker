# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""A ride's re-route turns round only where that saves half a mile (the owner, 2026-10-18:
"Penalize U turns. Basically you'd have to save about half a mile on that road for it to make
sense", "For rerouting").

The router is the fake of tests/test_route_api.py; its route sets off east (bearing 90)."""

from __future__ import annotations

import pytest
from test_route_api import (  # noqa: F401 (fixtures)
    good_body,
    post,
    router,
    segments,
    standard_router,
)

from core import routing

pytestmark = pytest.mark.usefixtures("weekday_clock")

db = pytest.mark.django_db(transaction=True)


def routes(fake) -> list[dict]:
    return [call[1] for call in fake.calls if "locations" in call[1]]


@db
class TestThroughTheApi:
    def test_a_route_that_sets_off_ahead_is_planned_once(self, client, segments, router) -> None:
        fake = router(standard_router())
        response = post(client, {**good_body(), "heading": 85})
        assert response.status_code == 200, response.content
        assert all("heading" not in r["locations"][0] for r in routes(fake))

    def test_a_u_turn_start_is_planned_again_setting_off_ahead(
        self, client, segments, router
    ) -> None:
        fake = router(standard_router())
        response = post(client, {**good_body(), "heading": 270})
        assert response.status_code == 200, response.content
        ahead = [r for r in routes(fake) if "heading" in r["locations"][0]]
        assert ahead, "no route was asked to set off ahead"
        assert ahead[0]["locations"][0]["heading"] == 270
        assert ahead[0]["locations"][0]["heading_tolerance"] == routing.HEADING_TOLERANCE_DEG

    def test_ahead_only_reaches_the_plan(self, client, segments, router, monkeypatch) -> None:
        router(standard_router())
        seen: list[routing.Dials] = []
        real = routing.plan_onward

        def spy(points, preset_name, dials=None, **kw):
            seen.append(dials)
            return real(points, preset_name, dials=dials, **kw)

        monkeypatch.setattr(routing, "plan_onward", spy)
        response = post(client, {**good_body(), "heading": 270, "ahead_only": True})
        assert response.status_code == 200, response.content
        assert seen and seen[0].ahead_only is True

    @pytest.mark.parametrize("heading", [-1, 360, "north"])
    def test_a_heading_out_of_range_is_refused(self, client, router, heading) -> None:
        fake = router(standard_router())
        assert post(client, {**good_body(), "heading": heading}).status_code == 400
        assert fake.calls == []


def answer(coords: list[tuple[float, float]], distance_m: float) -> dict:
    return {"geometry": {"coordinates": [list(c) for c in coords]}, "distance_m": distance_m}


# East along a street, then the same street west: 0.001 deg of longitude is about 87 m here.
EAST = [(-77.050, 38.9), (-77.049, 38.9), (-77.040, 38.9)]
WEST = [(-77.050, 38.9), (-77.051, 38.9), (-77.060, 38.9)]


class TestPlanOnward:
    @pytest.fixture
    def planned(self, monkeypatch):
        """routing.plan answers the U-turn without a heading and `ahead` with one."""
        asked: list[routing.Dials] = []

        def install(ahead):
            def fake_plan(points, preset_name, dials=None, **_):
                asked.append(dials)
                if dials.heading is None:
                    return answer(WEST, 2000.0)
                if isinstance(ahead, Exception):
                    raise ahead
                return ahead

            monkeypatch.setattr(routing, "plan", fake_plan)
            return asked

        return install

    def onward(self, heading=90.0):
        dials = routing.Dials(heading=heading)
        return routing.plan_onward([[-77.05, 38.9], [-77.06, 38.9]], "default", dials=dials)

    def test_the_way_ahead_wins_when_the_u_turn_saves_under_half_a_mile(self, planned) -> None:
        asked = planned(answer(EAST, 2000.0 + 800.0))
        assert self.onward()["geometry"]["coordinates"][1] == list(EAST[1])
        assert [d.heading for d in asked] == [None, 90.0]

    def test_the_u_turn_wins_when_it_saves_half_a_mile(self, planned) -> None:
        planned(answer(EAST, 2000.0 + routing.UTURN_SAVING_M))
        assert self.onward()["geometry"]["coordinates"][1] == list(WEST[1])

    def test_after_two_u_turns_the_way_ahead_wins_whatever_turning_saves(self, planned) -> None:
        # The owner, 2026-10-20: "on the third time assume that the user wants to stay on that path"
        planned(answer(EAST, 2000.0 + 10 * routing.UTURN_SAVING_M))
        dials = routing.Dials(heading=90.0, ahead_only=True)
        onward = routing.plan_onward([[-77.05, 38.9], [-77.06, 38.9]], "default", dials=dials)
        assert onward["geometry"]["coordinates"][1] == list(EAST[1])

    def test_ahead_only_with_no_way_ahead_still_turns_round(self, planned) -> None:
        planned(routing.NoRoute("no route"))
        dials = routing.Dials(heading=90.0, ahead_only=True)
        onward = routing.plan_onward([[-77.05, 38.9], [-77.06, 38.9]], "default", dials=dials)
        assert onward["geometry"]["coordinates"][1] == list(WEST[1])

    def ahead_only(self, **kw):
        dials = routing.Dials(heading=90.0, ahead_only=True, **kw)
        return routing.plan_onward(
            [[-77.05, 38.9], [-77.06, 38.9]], "default", dials=dials, started=123.0
        )

    def test_ahead_only_plans_the_way_ahead_first_and_once(self, planned) -> None:
        # Audit S5 (the owner approved planning ahead first, 2026-10-27): the plan that ignores
        # the heading would almost certainly turn round, and be thrown away.
        asked = planned(answer(EAST, 2000.0 + 10 * routing.UTURN_SAVING_M))
        assert self.ahead_only()["geometry"]["coordinates"][1] == list(EAST[1])
        assert [d.heading for d in asked] == [90.0]

    def test_ahead_only_whose_way_ahead_turns_round_keeps_it_in_one_plan(self, planned) -> None:
        # Audit round 2, R1 option (the owner, 2026-10-27 7:52 PM ET: "make the banked
        # changes"; this replaces the test that planned again without the heading): the route
        # ahead that still turns round is the answer, and no second plan is made.
        asked = planned(answer(WEST, 2100.0))
        assert self.ahead_only()["distance_m"] == 2100.0
        assert [d.heading for d in asked] == [90.0]

    @pytest.mark.parametrize(
        "error",
        [
            routing.NoRoute("no route"),
            routing.DeadlineExceeded(),
            routing.RouterUnavailable("down"),
            routing.TooLong("far"),
        ],
    )
    def test_ahead_only_falls_back_on_any_error(self, planned, error) -> None:
        asked = planned(error)
        assert self.ahead_only()["geometry"]["coordinates"][1] == list(WEST[1])
        assert [d.heading for d in asked] == [90.0, None]

    def test_ahead_only_with_both_plans_failing_raises(self, monkeypatch) -> None:
        def fake_plan(points, preset_name, dials=None, **_):
            raise routing.NoRoute("no route")

        monkeypatch.setattr(routing, "plan", fake_plan)
        with pytest.raises(routing.NoRoute):
            self.ahead_only()

    def test_a_cancel_on_the_second_ahead_only_plan_keeps_no_route(self, monkeypatch) -> None:
        # The second plan runs only after the first failed; a cancel there still stops it.
        def fake_plan(points, preset_name, dials=None, **_):
            if dials.heading is None:
                raise routing.PlanCancelled("replaced")
            raise routing.NoRoute("no route")

        monkeypatch.setattr(routing, "plan", fake_plan)
        with pytest.raises(routing.PlanCancelled):
            self.ahead_only()

    def test_a_cancel_on_the_way_ahead_starts_no_second_plan(self, planned) -> None:
        # A PlanCancelled is a DeadlineExceeded, but the rider has moved on (review of S7).
        asked = planned(routing.PlanCancelled("replaced"))
        with pytest.raises(routing.PlanCancelled):
            self.ahead_only()
        assert [d.heading for d in asked] == [90.0]

    def test_a_cancel_on_the_second_plan_keeps_no_u_turn(self, planned) -> None:
        planned(routing.PlanCancelled("replaced"))
        with pytest.raises(routing.PlanCancelled):
            self.onward()

    def test_ahead_only_keeps_the_plans_clock(self, monkeypatch) -> None:
        clocks: list = []

        def fake_plan(points, preset_name, dials=None, started=None, **_):
            clocks.append(started)
            if dials.heading is not None:
                raise routing.DeadlineExceeded()
            return answer(WEST, 2000.0)

        monkeypatch.setattr(routing, "plan", fake_plan)
        self.ahead_only()
        assert clocks == [123.0, 123.0]

    def test_ahead_only_on_a_loop_is_one_plan_without_the_heading(self, planned) -> None:
        asked = planned(answer(EAST, 1.0))
        self.ahead_only(loop=True)
        assert [d.heading for d in asked] == [None]

    def test_ahead_only_on_a_followed_line_is_one_plan_without_the_heading(self, planned) -> None:
        asked = planned(answer(EAST, 1.0))
        self.ahead_only(follow=((-77.05, 38.9), (-77.06, 38.9)))
        assert [d.heading for d in asked] == [None]

    def test_no_way_ahead_keeps_the_u_turn(self, planned) -> None:
        planned(routing.NoRoute("no route"))
        assert self.onward()["geometry"]["coordinates"][1] == list(WEST[1])

    def test_no_time_left_keeps_the_u_turn(self, planned) -> None:
        planned(routing.DeadlineExceeded())
        assert self.onward()["geometry"]["coordinates"][1] == list(WEST[1])

    def test_a_router_that_still_turns_round_keeps_the_shorter_u_turn(self, planned) -> None:
        planned(answer(WEST, 2100.0))
        assert self.onward()["distance_m"] == 2000.0

    def test_without_a_heading_it_is_one_plan(self, planned) -> None:
        asked = planned(answer(EAST, 1.0))
        assert self.onward(heading=None)["geometry"]["coordinates"][1] == list(WEST[1])
        assert len(asked) == 1

    def test_a_loop_is_one_plan(self, planned) -> None:
        asked = planned(answer(EAST, 1.0))
        dials = routing.Dials(heading=90.0, loop=True)
        routing.plan_onward([[-77.05, 38.9], [-77.06, 38.9]], "default", dials=dials)
        assert len(asked) == 1

    def test_a_followed_line_is_one_plan(self, planned) -> None:
        asked = planned(answer(EAST, 1.0))
        dials = routing.Dials(heading=90.0, follow=((-77.05, 38.9), (-77.06, 38.9)))
        routing.plan_onward([[-77.05, 38.9], [-77.06, 38.9]], "default", dials=dials)
        assert len(asked) == 1


class TestSetsOffBack:
    def test_reads_past_the_snap(self) -> None:
        # A metre east, then west: the snap's wiggle is not the way the route goes.
        line = [(-77.05, 38.9), (-77.04999, 38.9), (-77.051, 38.9)]
        assert routing.sets_off_back(answer(line, 100.0), 90.0)

    def test_a_turn_is_not_a_u_turn(self) -> None:
        north = [(-77.05, 38.9), (-77.05, 38.901)]
        assert not routing.sets_off_back(answer(north, 100.0), 90.0)
        assert routing.sets_off_back(answer(north, 100.0), 180.0)
