"""POST /api/route for FOLLOWUP-LONG-CALM (OWNER-DECISIONS 256-265): the longest ride and the
system weight as request fields, the long budget and slot of a long calm plan, the
routes to choose from in the answer, and the hills choice's hold (GATE-corr SF1).

The router is the fake of tests/test_route_api.py.
"""

from __future__ import annotations

import pytest
from test_route_api import (
    STANDARD_EDGES,
    VERTICES,
    FakeRouter,
    clock,  # noqa: F401 - a fixture, used by name
    good_body,
    post,
    route_answer,
    standard_router,
    trace_answer,
)

from core import api, presets, ratelimit, refine, routing

db = pytest.mark.django_db(transaction=True)

pytestmark = [pytest.mark.usefixtures("weekday_clock"), db]

US = [-77.0063, 38.8973]
PENN = [-76.6158, 39.3074]


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


@pytest.fixture
def segments(segment_schemas):
    from django.db import connection

    live, _staging = segment_schemas
    rows = [(101, 0, 3, VERTICES[0:2]), (202, 0, 1, VERTICES[1:3]), (202, 1, 4, VERTICES[2:4])]
    with connection.cursor() as cursor:
        for way, ordinal, tier, line in rows:
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, 'test')",
                [way, ordinal, wkt, tier],
            )
    return live


def top_body(**extra) -> dict:
    return {**good_body("trailmaxxing"), "stress": 100, **extra}


class TestTheDialsOnTheRequest:
    def test_a_longest_ride_and_a_system_weight_are_taken_and_echoed(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        response = post(client, top_body(max_distance_m=96_561, system_weight_kg=110))
        assert response.status_code == 200
        body = response.json()
        assert body["dials"]["max_distance_m"] == 96_561
        assert body["dials"]["system_weight_kg"] == 110
        assert body["calm_search"]["max_distance_m"] == 96_561
        assert body["calm_search"]["max_distance_set"] is True

    def test_they_are_not_sent_to_the_router(self, client, segments, router) -> None:
        fake = router(standard_router())
        post(client, top_body(max_distance_m=96_561, system_weight_kg=110))
        for _url, payload in fake.calls:
            assert "max_distance_m" not in str(payload) and "system_weight" not in str(payload)

    def test_without_them_the_default_longest_ride_is_the_answers_and_not_set(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        body = post(client, top_body()).json()
        assert body["dials"]["max_distance_m"] is None and body["dials"]["system_weight_kg"] is None
        search = body["calm_search"]
        assert search["max_distance_set"] is False and search["fits"] is True
        # 1.6 times the router's own route (2.2 km), or a mile more if that is more.
        assert search["max_distance_m"] == pytest.approx(presets.default_max_m(2200.0), abs=0.2)

    def test_below_the_top_they_are_ignored(self, client, segments, router) -> None:
        router(standard_router())
        body = post(
            client, {**top_body(max_distance_m=5_000, system_weight_kg=110), "stress": 90}
        ).json()
        assert body["dials"]["max_distance_m"] is None
        assert body["dials"]["system_weight_kg"] is None
        assert "max_distance_m" not in (body["calm_search"] or {}) or (
            body["calm_search"]["max_distance_m"] is None
        )

    @pytest.mark.parametrize("value", [999, 1_000_001, 96_561.5, "60", True, -1])
    def test_a_longest_ride_out_of_range_or_not_a_whole_number_is_refused(
        self, client, value
    ) -> None:
        assert post(client, top_body(max_distance_m=value)).status_code == 400

    @pytest.mark.parametrize("value", [67, 141, 90.5, "90", True])
    def test_a_system_weight_out_of_range_is_refused(self, client, value) -> None:
        assert post(client, top_body(system_weight_kg=value)).status_code == 400

    @pytest.mark.parametrize("value", [1_000, 96_561, 1_000_000])
    def test_the_ends_of_the_range_are_taken(self, client, segments, router, value) -> None:
        router(standard_router())
        assert post(client, top_body(max_distance_m=value)).status_code == 200

    @pytest.mark.parametrize("value", [68, 140])
    def test_the_ends_of_the_weights_range_are_taken(self, client, segments, router, value) -> None:
        router(standard_router())
        assert post(client, top_body(system_weight_kg=value)).status_code == 200


class TestNoRouteWithinTheLongestRide:
    def test_the_shortest_found_is_answered_with_a_note(
        self, client, segments, router, monkeypatch
    ) -> None:
        """The router's route (2.2 km) and every rung's are past a 1.2 km limit: the shortest
        is answered, `fits` is false and `limited` says why."""
        fake = FakeRouter(
            {
                "route": [
                    route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
                    route_answer([(VERTICES, 2.1, [10.0, 20.0, 15.0, 30.0])]),
                    route_answer([(VERTICES, 1.9, [10.0, 20.0, 15.0, 30.0])]),
                    route_answer([(VERTICES, 1.5, [10.0, 20.0, 15.0, 30.0])]),
                ],
                "trace_attributes": trace_answer(VERTICES, STANDARD_EDGES),
            }
        )
        router(fake)
        body = post(client, top_body(max_distance_m=1_200)).json()
        search = body["calm_search"]
        assert search["fits"] is False and search["limited"] == "max_distance"
        assert body["distance_m"] == pytest.approx(1500.0)
        assert search["max_distance_set"] is True and search["max_distance_m"] == 1200.0
        # The router was asked at each rung of the ladder, calmest first.
        sent = [
            p["costing_options"]["bicycle"]["use_roads"]
            for _u, p in fake.calls
            if "costing_options" in p
        ]
        assert sent[0] == 0.0 and sent[1:4] == [
            presets.use_roads_for(s) for s in routing.FIT_STRESS_LADDER
        ]

    def test_a_calmer_rung_that_fits_is_the_first_route(self, client, segments, router) -> None:
        fake = FakeRouter(
            {
                "route": [route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])])]
                + [route_answer([(VERTICES, 1.9, [10.0, 20.0, 15.0, 30.0])])] * 5,
                "trace_attributes": trace_answer(VERTICES, STANDARD_EDGES),
            }
        )
        router(fake)
        body = post(client, top_body(max_distance_m=2_000)).json()
        search = body["calm_search"]
        # Every rung fits here, so the bisection runs to its end toward the calmest.
        assert search["fits"] is True and search["fitted_at"] == 78
        assert body["distance_m"] == pytest.approx(1900.0)

    def test_a_route_within_the_limit_asks_no_second_route(self, client, segments, router) -> None:
        fake = router(standard_router())
        body = post(client, top_body(max_distance_m=10_000)).json()
        assert body["calm_search"].get("fitted_at") is None
        assert fake.endpoints().count("route") >= 1
        assert all(
            p["costing_options"]["bicycle"]["use_roads"] == 0.0
            for _u, p in fake.calls
            if "costing_options" in p
        )


class TestTheLongCalmPlan:
    def test_the_rule(self) -> None:
        from core.routing import long_calm_for

        assert long_calm_for("trailmaxxing", [US, PENN], 100, False, False)
        assert not long_calm_for("trailmaxxing", [US, PENN], 99, False, False)
        assert not long_calm_for("default", [US, PENN], 100, False, False), "Trailmaxxing's alone"
        assert not long_calm_for("trailmaxxing", [US, [-77.0, 38.95]], 100, False, False)
        assert not long_calm_for("trailmaxxing", [US, PENN], 100, True, False), (
            "a long ride has its own"
        )
        assert not long_calm_for("trailmaxxing", [US, PENN], 100, False, True), (
            "no search while seeking"
        )
        assert not long_calm_for("trailmaxxing", [US], 100, False, False)

    def test_the_span_that_makes_it_long_is_the_searchs_working_span(self) -> None:
        assert refine_span() == 30_000

    @pytest.mark.parametrize(
        ("points", "budget"),
        [([US, PENN], routing.LONG_PLAN_BUDGET_S), ([US, [-77.0, 38.95]], routing.PLAN_BUDGET_S)],
    )
    def test_it_has_the_long_rides_budget_and_an_ordinary_plan_keeps_its_own(
        self, monkeypatch, points, budget
    ) -> None:
        seen = []

        def first(variant, request, deadline):
            seen.append(deadline)
            raise routing.RouterUnavailable("stop")

        monkeypatch.setattr(routing, "_route", first)
        started = routing.clock()
        with pytest.raises(routing.RouterUnavailable):
            routing.plan(
                points,
                "trailmaxxing",
                started=started,
                dials=routing.Dials(stress=100, when="weekday_offpeak"),
            )
        assert seen[0].at == pytest.approx(started + budget - routing.ANSWER_RESERVE_S, abs=0.5)
        assert seen[0].per_call_s == (
            routing.LONG_ROUTER_TIMEOUT_S
            if budget == routing.LONG_PLAN_BUDGET_S
            else routing.ROUTER_TIMEOUT_S
        )

    def test_a_loop_has_the_ordinary_budget_whatever_its_span(self, monkeypatch) -> None:
        """A loop is searched in one piece or not at all, so it is not a long calm plan."""
        seen = []

        def first(variant, request, deadline):
            seen.append(deadline)
            raise routing.RouterUnavailable("stop")

        monkeypatch.setattr(routing, "_route", first)
        started = routing.clock()
        with pytest.raises(routing.RouterUnavailable):
            routing.plan(
                [US, PENN],
                "trailmaxxing",
                started=started,
                dials=routing.Dials(stress=100, when="weekday_offpeak", loop=True),
            )
        assert seen[0].at == pytest.approx(
            started + routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S, abs=0.5
        )

    def test_a_loop_does_not_take_the_long_slot(self, client, monkeypatch) -> None:
        taken = []
        real = ratelimit.acquire
        monkeypatch.setattr(
            ratelimit, "acquire", lambda r, limit: (taken.append(limit), real(r, limit))[1]
        )
        monkeypatch.setattr(
            routing,
            "plan",
            lambda *a, **k: (_ for _ in ()).throw(routing.NoRoute("stop", no_path=True)),
        )
        post(client, {"points": [US, PENN], "preset": "trailmaxxing", "stress": 100, "loop": True})
        assert ratelimit.LONG_ROUTING_IN_FLIGHT not in taken

    def test_the_budget_is_the_long_rides_and_under_gunicorns_timeout(self) -> None:
        assert routing.LONG_PLAN_BUDGET_S == 50 and routing.LONG_PLAN_BUDGET_S < 60

    def test_a_trailmaxxing_request_past_the_span_takes_the_long_slot(
        self, client, monkeypatch
    ) -> None:
        taken = []
        real = ratelimit.acquire

        def acquire(request, limit):
            taken.append(limit)
            return real(request, limit)

        monkeypatch.setattr(ratelimit, "acquire", acquire)
        monkeypatch.setattr(
            routing,
            "plan",
            lambda *a, **k: (_ for _ in ()).throw(routing.NoRoute("stop", no_path=True)),
        )
        response = post(client, {"points": [US, PENN], "preset": "trailmaxxing", "stress": 100})
        assert response.status_code == 422  # the stub's NoRoute, after the slot was taken
        assert ratelimit.LONG_ROUTING_IN_FLIGHT in taken

    def test_a_short_one_does_not(self, client, monkeypatch) -> None:
        taken = []
        real = ratelimit.acquire
        monkeypatch.setattr(
            ratelimit, "acquire", lambda r, limit: (taken.append(limit), real(r, limit))[1]
        )
        monkeypatch.setattr(
            routing,
            "plan",
            lambda *a, **k: (_ for _ in ()).throw(routing.NoRoute("stop", no_path=True)),
        )
        post(client, {"points": [US, [-77.0, 38.95]], "preset": "trailmaxxing", "stress": 100})
        assert ratelimit.LONG_ROUTING_IN_FLIGHT not in taken

    def test_a_timed_out_one_is_not_to_be_resent_unasked(self, client, monkeypatch) -> None:
        def run_out(*a, **k):
            raise routing.DeadlineExceeded("late")

        monkeypatch.setattr(routing, "plan", run_out)
        response = post(client, {"points": [US, PENN], "preset": "trailmaxxing", "stress": 100})
        assert response.status_code == 503 and response.json()["code"] == api.LONG_RIDE_TIMED_OUT


def refine_span() -> int:
    return refine.REFINE_MAX_SPAN_M


class TestRoutesToChooseFrom:
    """OWNER-DECISIONS 265: the answer first, others as bodies of their own."""

    def alternate(self):
        return route_answer([(VERTICES[:4], 2.0, [10.0, 20.0, 15.0, 30.0])])["trip"]

    def test_a_route_with_no_others_has_no_candidates(self, client, segments, router) -> None:
        router(standard_router())
        body = post(client, top_body()).json()
        assert body["candidates"] is None and body["rank"] is None

    def test_other_routes_are_whole_bodies_ranked_after_the_answer(
        self, client, segments, router, monkeypatch
    ) -> None:
        router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
                    "trace_attributes": [trace_answer(VERTICES, STANDARD_EDGES)] * 4
                    + [trace_answer(VERTICES[:4], STANDARD_EDGES[:2])] * 4,
                }
            )
        )
        real = refine.refine
        extra = self.alternate()

        def with_another(trip, ctx):
            out = real(trip, ctx)
            ctx.candidates = [(out[0], None), (extra, None)]
            return out

        monkeypatch.setattr(refine, "refine", with_another)
        body = post(client, top_body()).json()
        assert body["rank"] == 1 and len(body["candidates"]) == 1
        (other,) = body["candidates"]
        assert other["rank"] == 2
        for key in (
            "geometry",
            "stress_m",
            "facility_m",
            "intersections",
            "description",
            "dials",
            "distance_m",
        ):
            assert key in other, key
        assert other["distance_m"] == pytest.approx(2000.0)
        assert "candidates" not in other, "a candidate has none of its own"
        assert other["effort_m"] is not None and body["effort_m"] is not None

    def test_the_answer_is_unchanged_by_them(self, client, segments, router, monkeypatch) -> None:
        router(standard_router())
        plain = post(client, top_body()).json()
        router(standard_router())
        monkeypatch.setattr(refine, "pick_candidates", lambda pool, ctx, ref: pool[:1])
        again = post(client, top_body()).json()
        for key in ("geometry", "distance_m", "stress_m", "intersections", "description"):
            assert again[key] == plain[key], key
        assert again["candidates"] is None


class TestMakeItALoop:
    """OWNER-DECISIONS 266: a ride that ends where it starts, or "Make it a loop", returns by a
    different way where there is one, and says how much it shares where there is not."""

    def loop_router(self, back_km=2.2):
        legs_out = (VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])
        legs_back = (list(reversed(VERTICES)), back_km, [30.0, 15.0, 20.0, 10.0])
        return FakeRouter(
            {
                "route": [route_answer([legs_out, legs_back])] + [route_answer([legs_back])] * 6,
                "trace_attributes": [trace_answer(VERTICES, STANDARD_EDGES)] * 40,
            }
        )

    def body(self, **extra):
        a, b = list(VERTICES[0]), list(VERTICES[-1])
        return {"points": [a, b], "preset": "default", **extra}

    def test_the_toggle_plans_there_and_back_to_the_start(self, client, segments, router) -> None:
        fake = router(self.loop_router())
        response = post(client, self.body(loop=True))
        assert response.status_code == 200
        body = response.json()
        locations = fake.calls[0][1]["locations"]
        assert len(locations) == 3 and locations[0]["lon"] == locations[2]["lon"]
        assert body["dials"]["loop"] is True and body["loop"] is not None
        assert len(body["leg_ends"]) == 2

    def test_a_ride_ending_where_it_starts_is_a_loop_without_the_toggle(
        self, client, segments, router
    ) -> None:
        fake = router(self.loop_router())
        a, b = list(VERTICES[0]), list(VERTICES[-1])
        body = post(client, {"points": [a, b, a], "preset": "default"}).json()
        assert len(fake.calls[0][1]["locations"]) == 3
        assert body["dials"]["loop"] is True and body["loop"] is not None

    def test_a_point_to_point_ride_is_not_a_loop(self, client, segments, router) -> None:
        router(standard_router())
        body = post(client, self.body()).json()
        assert body["dials"]["loop"] is False and body["loop"] is None

    def test_an_unavoidable_there_and_back_is_an_out_and_back_and_says_so(
        self, client, segments, router
    ) -> None:
        router(self.loop_router())
        loop = post(client, self.body(loop=True)).json()["loop"]
        # Every way back the fake gives rides the way out's ways.
        assert loop["fallback"] == "out_and_back"
        assert loop["overlap_pct"] == 100.0 and loop["shared_m"] == loop["return_m"]

    def test_the_whole_loops_span_counts_toward_the_limit(self, client) -> None:
        a = [-77.3, 38.9]
        far = [
            -76.5,
            38.9,
        ]  # about 69 km: there and back is 139 km, past the confirm span? no, under 150
        assert (
            post(client, {"points": [a, far], "preset": "default", "loop": True}).status_code != 400
        )
        wide = [[-77.4, 38.9], [-76.2, 38.9]]  # 104 km each way: 208 km there and back
        refused = post(client, {"points": wide, "preset": "default", "loop": True})
        assert refused.status_code == 400 and "longer than" in refused.json()["error"]

    def test_a_mass_ride_is_not_made_one(self, client, segments, router) -> None:
        router(standard_router())
        body = post(client, {**self.body(loop=True), "preset": "mass-ride"}).json()
        assert body["loop"] is None and body["dials"]["loop"] is False

    def test_a_loop_is_not_a_long_calm_plan(self) -> None:
        loop = routing.loop_points([US, PENN], True)
        assert routing.long_calm_for("trailmaxxing", loop, 100, False, False), (
            "by span alone it would be"
        )
        assert routing.loop_wanted([US, PENN], True, "trailmaxxing")


class TestFittingALongestRide:
    """`routing._fit_longest`: the calmest route within the limit, found by the ladder and
    then by bisecting the last stretch of it."""

    def run(self, monkeypatch, length_km, max_m, time_left=100.0):
        calls = []

        def call(variant, endpoint, payload, deadline):
            use_roads = payload["costing_options"]["bicycle"]["use_roads"]
            calls.append(use_roads)
            km = length_km(use_roads)
            return {
                "trip": {
                    "legs": [{"shape": "x", "summary": {"length": km}}],
                    "summary": {"length": km},
                }
            }

        monkeypatch.setattr(routing, "_call", call)
        first = {"legs": [{"shape": "own"}], "summary": {"length": length_km(0.0)}}
        deadline = routing.Deadline(routing.clock() + time_left, 35)
        got = routing._fit_longest(
            first,
            {"locations": []},
            {"bicycle": {}},
            {"bicycle": {}},
            max_m,
            "trailmaxxing",
            0,
            False,
            False,
            "standard",
            deadline,
        )
        return got, calls

    def test_a_route_within_the_limit_is_kept_and_nothing_is_asked(self, monkeypatch) -> None:
        got, calls = self.run(monkeypatch, lambda u: 60 - 20 * u, 61_000.0)
        assert got[4] is None and calls == [] and got[0]["legs"][0]["shape"] == "own"

    def test_the_ladder_then_the_bisection_find_the_calmest_that_fits(self, monkeypatch) -> None:
        # 60 km at use_roads 0, 40 km at 1: it fits 50 km from use_roads 0.5.
        got, calls = self.run(monkeypatch, lambda u: 60 - 20 * u, 50_000.0)
        assert calls[:3] == [presets.use_roads_for(p) for p in routing.FIT_STRESS_LADDER]
        assert len(calls) == 3 + routing.FIT_BISECT_STEPS
        # Positions 70 and 40 are over, 0 fits; 20 fits, 30 fits, 35 fits (use_roads 0.55 -> 49 km).
        assert got[4] == 35
        assert got[0]["summary"]["length"] * 1000.0 <= 50_000.0
        assert got[0]["summary"]["length"] * 1000.0 > 48_000.0, "the calmest of those that fit"

    def test_a_bisection_probe_that_does_not_fit_narrows_it_the_other_way(
        self, monkeypatch
    ) -> None:
        # Fits only from use_roads 0.62.
        got, _calls = self.run(monkeypatch, lambda u: 60 - 20 * u, 47_600.0)
        # 20 fits, 30 does not (47.7 km), so 25 is tried and fits.
        assert got[4] == 25
        assert got[0]["summary"]["length"] * 1000.0 <= 47_600.0

    def test_when_nothing_fits_the_shortest_is_answered(self, monkeypatch) -> None:
        got, calls = self.run(monkeypatch, lambda u: 60 - 20 * u, 30_000.0)
        assert got[4] == 0 and got[0]["summary"]["length"] == pytest.approx(40.0)
        assert len(calls) == len(routing.FIT_STRESS_LADDER), "no bisection where nothing fits"

    def test_with_no_time_it_stops_asking(self, monkeypatch) -> None:
        got, calls = self.run(
            monkeypatch, lambda u: 60 - 20 * u, 50_000.0, time_left=routing.FIT_MIN_S - 1
        )
        assert calls == [] and got[4] is None

    def test_a_refusal_stops_it(self, monkeypatch) -> None:
        def refuse(variant, endpoint, payload, deadline):
            raise routing.RouterRefused(400, 442, "no path")

        monkeypatch.setattr(routing, "_call", refuse)
        first = {"legs": [{"shape": "own"}], "summary": {"length": 60.0}}
        got = routing._fit_longest(
            first,
            {"locations": []},
            {"bicycle": {}},
            {"bicycle": {}},
            50_000.0,
            "trailmaxxing",
            0,
            False,
            False,
            "standard",
            routing.Deadline(routing.clock() + 100, 35),
        )
        assert got[0] is first and got[4] is None
