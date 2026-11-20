"""Fast, "as direct as possible" (the owner, 2026-11-20: "Make fast faster"): a Fast ride at its
own traffic position is planned at the most direct end of the slider too, and that route taken
where it is a minute quicker door to door and adds no more than a quarter mile of LTS 4."""

from __future__ import annotations

import pytest

from core import presets, routing


def body(minutes: float, lts4_m: float = 0.0, avoid_m: float = 0.0, stress: int = 10) -> dict:
    return {
        "duration_s": minutes * 60.0,
        "stress_m": {"1": 5000.0, "4": lts4_m, "5": avoid_m},
        "dials": {"stress": stress, "hills": 40},
    }


class TestTheRule:
    def test_a_minute_quicker_and_no_busier_wins(self) -> None:
        assert presets.fast_direct_wins(body(29.0), body(30.0))
        assert not presets.fast_direct_wins(body(29.5), body(30.0))
        assert not presets.fast_direct_wins(body(31.0), body(30.0))

    def test_more_than_a_quarter_mile_of_lts_4_or_avoid_loses(self) -> None:
        own = body(30.0, lts4_m=100.0)
        assert presets.fast_direct_wins(body(25.0, lts4_m=500.0), own)
        assert not presets.fast_direct_wins(body(25.0, lts4_m=600.0), own)
        assert not presets.fast_direct_wins(body(25.0, lts4_m=100.0, avoid_m=450.0), own)


class TestThePlan:
    POINTS = [[-77.0, 38.9], [-77.04, 38.9]]

    def plans(self, monkeypatch, own: dict, direct: dict | Exception) -> list:
        asked: list = []

        def planned(points, preset_name, long_ride, started, dials, quick, candidates):
            asked.append((preset_name, dials.stress, quick))
            if dials.stress == presets.STRESS_MIN and asked[0] != asked[-1]:
                if isinstance(direct, Exception):
                    raise direct
                return direct
            return own

        monkeypatch.setattr(routing, "_plan_graphs", planned)
        return asked

    def test_the_direct_route_answers_where_it_wins_at_the_riders_own_position(
        self, monkeypatch
    ) -> None:
        asked = self.plans(monkeypatch, body(30.0), body(27.0, stress=0))
        answer = routing.plan(self.POINTS, "fast")
        assert asked == [("fast", None, False), ("fast", 0, False)]
        assert answer["duration_s"] == 27.0 * 60
        # The slider the rider sees stays where Fast starts.
        assert answer["dials"]["stress"] == 10

    def test_the_rides_own_answers_where_the_direct_route_is_no_quicker_or_busier(
        self, monkeypatch
    ) -> None:
        own = body(30.0)
        self.plans(monkeypatch, own, body(29.8, stress=0))
        assert routing.plan(self.POINTS, "fast") is own
        self.plans(monkeypatch, own, body(20.0, lts4_m=2000.0, stress=0))
        assert routing.plan(self.POINTS, "fast") is own

    def test_a_direct_plan_that_fails_leaves_the_rides_own(self, monkeypatch) -> None:
        own = body(30.0)
        self.plans(monkeypatch, own, routing.NoRoute("none"))
        assert routing.plan(self.POINTS, "fast") is own

    @pytest.mark.parametrize(
        ("name", "dials", "quick"),
        [
            ("default", routing.Dials(), False),
            ("road-bike", routing.Dials(), False),
            ("fast", routing.Dials(stress=20), False),
            ("fast", routing.Dials(stress=0), False),
            ("fast", routing.Dials(), True),
            ("fast", routing.Dials(follow=((-77.0, 38.9), (-77.04, 38.9))), False),
        ],
    )
    def test_only_a_full_fast_plan_at_its_own_position_is_planned_twice(
        self, name, dials, quick, monkeypatch
    ) -> None:
        asked = self.plans(monkeypatch, body(30.0), body(20.0, stress=0))
        routing.plan(self.POINTS, name, dials=dials, quick=quick)
        assert len(asked) == 1

    def test_the_slider_set_to_fasts_own_start_counts_as_its_own_position(
        self, monkeypatch
    ) -> None:
        asked = self.plans(monkeypatch, body(30.0), body(20.0, stress=0))
        routing.plan(self.POINTS, "fast", dials=routing.Dials(stress=10))
        assert len(asked) == 2
