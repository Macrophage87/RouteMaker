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


class TestSetsOffBack:
    def test_reads_past_the_snap(self) -> None:
        # A metre east, then west: the snap's wiggle is not the way the route goes.
        line = [(-77.05, 38.9), (-77.04999, 38.9), (-77.051, 38.9)]
        assert routing.sets_off_back(answer(line, 100.0), 90.0)

    def test_a_turn_is_not_a_u_turn(self) -> None:
        north = [(-77.05, 38.9), (-77.05, 38.901)]
        assert not routing.sets_off_back(answer(north, 100.0), 90.0)
        assert routing.sets_off_back(answer(north, 100.0), 180.0)
