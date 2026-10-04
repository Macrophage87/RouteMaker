"""POST /api/route for FOLLOWUP-LONG-CALM (OWNER-DECISIONS 256-271): the target distance and
the system weight as request fields, the first route where the router's own is past the
target (`routing._fit_target`, `_past_target`), the long budget and slot of a long calm plan, the
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
    def test_a_target_distance_and_a_system_weight_are_taken_and_echoed(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        response = post(client, top_body(target_distance_m=96_561, system_weight_kg=110))
        assert response.status_code == 200
        body = response.json()
        assert body["dials"]["target_distance_m"] == 96_561
        assert body["dials"]["system_weight_kg"] == 110
        search = body["calm_search"]
        assert search["target_distance_m"] == 96_561
        assert search["target_distance_set"] is True
        # OWNER-DECISIONS 271: the hard ceiling is 1.25 times the target, and the route
        # (2.2 km) is within the target: no overage.
        assert search["ceiling_m"] == pytest.approx(1.25 * 96_561, abs=0.1)
        assert search["fits"] is True and search["over_target_m"] == 0.0

    def test_the_old_names_are_not_taken(self, client) -> None:
        """No back-compat alias: the field was never released (OWNER-DECISIONS 271)."""
        assert post(client, top_body(max_distance_m=96_561)).status_code == 400

    def test_they_are_not_sent_to_the_router(self, client, segments, router) -> None:
        fake = router(standard_router())
        post(client, top_body(target_distance_m=96_561, system_weight_kg=110))
        for _url, payload in fake.calls:
            assert "target_distance" not in str(payload) and "system_weight" not in str(payload)

    def test_without_them_there_is_no_target_and_the_default_ceiling(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        body = post(client, top_body()).json()
        assert body["dials"]["target_distance_m"] is None
        assert body["dials"]["system_weight_kg"] is None
        search = body["calm_search"]
        assert search["target_distance_set"] is False and search["target_distance_m"] is None
        assert search["fits"] is None and search["over_target_m"] is None
        # 1.6 times the router's own route (2.2 km), or a mile more if that is more.
        assert search["ceiling_m"] == pytest.approx(presets.default_ceiling_m(2200.0), abs=0.2)

    def test_below_the_top_they_are_ignored(self, client, segments, router) -> None:
        router(standard_router())
        body = post(
            client, {**top_body(target_distance_m=5_000, system_weight_kg=110), "stress": 90}
        ).json()
        assert body["dials"]["target_distance_m"] is None
        assert body["dials"]["system_weight_kg"] is None
        assert "target_distance_m" not in (body["calm_search"] or {}) or (
            body["calm_search"]["target_distance_m"] is None
        )

    @pytest.mark.parametrize("value", [999, 1_000_001, 96_561.5, "60", True, -1])
    def test_a_target_distance_out_of_range_or_not_a_whole_number_is_refused(
        self, client, value
    ) -> None:
        assert post(client, top_body(target_distance_m=value)).status_code == 400

    @pytest.mark.parametrize("value", [90.5, "90", True])
    def test_a_system_weight_not_a_whole_number_is_refused(self, client, value) -> None:
        assert post(client, top_body(system_weight_kg=value)).status_code == 400

    @pytest.mark.parametrize(
        ("value", "used"), [(10, 25), (-5, 25), (24, 25), (701, 700), (800, 700), (9_999, 700)]
    )
    def test_a_system_weight_out_of_range_is_planned_at_the_nearer_limit(
        self, client, segments, router, value, used, monkeypatch
    ) -> None:
        """OWNER-DECISIONS 338, 352: accepted, not refused, and the effort model reads the
        limit (the answer's dials echo it, never the number sent)."""
        seen = []
        real = refine.refine

        def spy(trip, ctx):
            seen.append(ctx.mass_kg)
            return real(trip, ctx)

        monkeypatch.setattr(refine, "refine", spy)
        router(standard_router())
        response = post(client, top_body(system_weight_kg=value))
        assert response.status_code == 200
        assert response.json()["dials"]["system_weight_kg"] == used
        assert seen == [float(used)]

    @pytest.mark.parametrize("value", [1_000, 96_561, 1_000_000])
    def test_the_ends_of_the_range_are_taken(self, client, segments, router, value) -> None:
        router(standard_router())
        assert post(client, top_body(target_distance_m=value)).status_code == 200

    @pytest.mark.parametrize("value", [25, 48, 90, 450])
    def test_the_weights_range_is_taken_as_sent(self, client, segments, router, value) -> None:
        """OWNER-DECISIONS 337: 25 to 450 kg on every ride type, the ends included."""
        router(standard_router())
        response = post(client, top_body(system_weight_kg=value))
        assert response.status_code == 200
        assert response.json()["dials"]["system_weight_kg"] == value


class TestNoRouteWithinTheTarget:
    def test_the_least_stressful_within_the_ceiling_is_answered_with_a_note(
        self, client, segments, router, monkeypatch
    ) -> None:
        """The router's route (2.2 km) and every rung's are past a 1.2 km target: the least
        stressful within the 1.5 km ceiling (here the one route there, all reading alike)
        is answered (OWNER-DECISIONS 267), `fits` is false, `limited` says why and
        `over_target_m` how far over it is."""
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
        body = post(client, top_body(target_distance_m=1_200)).json()
        search = body["calm_search"]
        assert search["fits"] is False and search["limited"] == "target_distance"
        # The front end's no-fit sentence keys on this alone (correctness review, S2).
        assert search["no_fit"] is True
        assert body["distance_m"] == pytest.approx(1500.0)
        assert search["target_distance_set"] is True and search["target_distance_m"] == 1200.0
        assert search["over_target_m"] == pytest.approx(300.0)
        assert search["ceiling_m"] == pytest.approx(1500.0)
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
        body = post(client, top_body(target_distance_m=2_000)).json()
        search = body["calm_search"]
        # Every rung fits here, so the bisection runs to its end toward the calmest. The
        # router's own (2.2 km, within the 2.5 km ceiling) reads the same: not worth it.
        assert search["fits"] is True and search["fitted_at"] == 78
        assert search["over_target_m"] == 0.0 and search["no_fit"] is False
        assert body["distance_m"] == pytest.approx(1900.0)

    def test_a_route_within_the_limit_asks_no_second_route(self, client, segments, router) -> None:
        fake = router(standard_router())
        body = post(client, top_body(target_distance_m=10_000)).json()
        assert body["calm_search"].get("fitted_at") is None
        assert body["calm_search"]["no_fit"] is False
        assert fake.endpoints().count("route") >= 1
        assert all(
            p["costing_options"]["bicycle"]["use_roads"] == 0.0
            for _u, p in fake.calls
            if "costing_options" in p
        )


class TestTheLongCalmPlan:
    def test_the_rule(self) -> None:
        from core.routing import long_calm_for

        assert long_calm_for("trailmaxxing", [US, PENN], 100, False)
        assert not long_calm_for("trailmaxxing", [US, PENN], 99, False)
        assert not long_calm_for("default", [US, PENN], 100, False), "Trailmaxxing's alone"
        assert not long_calm_for("trailmaxxing", [US, [-77.0, 38.95]], 100, False)
        assert not long_calm_for("trailmaxxing", [US, PENN], 100, True), "a long ride has its own"
        assert not long_calm_for("trailmaxxing", [US], 100, False)

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

    def candidates_with(self, client, router, monkeypatch, body: dict) -> dict:
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
        extra = route_answer([(VERTICES[:4], 2.5, [10.0, 20.0, 15.0, 30.0])])["trip"]

        def with_another(trip, ctx):
            out = real(trip, ctx)
            ctx.candidates = [(out[0], None), (extra, None)]
            return out

        monkeypatch.setattr(refine, "refine", with_another)
        return post(client, body).json()

    def test_each_says_how_far_over_the_target_it_is(
        self, client, segments, router, monkeypatch
    ) -> None:
        """OWNER-DECISIONS 271: the overage is always said, the alternates' too."""
        body = self.candidates_with(client, router, monkeypatch, top_body(target_distance_m=2_200))
        (other,) = body["candidates"]
        assert other["over_target_m"] == pytest.approx(300.0)
        assert body["calm_search"]["over_target_m"] == 0.0

    def test_with_no_target_none_says_it(self, client, segments, router, monkeypatch) -> None:
        body = self.candidates_with(client, router, monkeypatch, top_body())
        (other,) = body["candidates"]
        assert other["over_target_m"] is None

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
        assert routing.long_calm_for("trailmaxxing", loop, 100, False), "by span alone it would be"
        assert routing.loop_wanted([US, PENN], True, "trailmaxxing")


class TestFittingATarget:
    """`routing._fit_target`: the calmest route within the target, found by the ladder and
    then by bisecting the last stretch of it, and every route found past it."""

    def run(self, monkeypatch, length_km, target_m, time_left=100.0):
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
        got = routing._fit_target(
            first,
            {"locations": []},
            {"bicycle": {}},
            {"bicycle": {}},
            target_m,
            "trailmaxxing",
            0,
            False,
            False,
            "standard",
            deadline,
        )
        return got, calls

    @staticmethod
    def km(option: tuple) -> float:
        return option[0]["summary"]["length"]

    def test_a_route_within_the_target_is_kept_and_nothing_is_asked(self, monkeypatch) -> None:
        (fit, past), calls = self.run(monkeypatch, lambda u: 60 - 20 * u, 61_000.0)
        assert fit[4] is None and calls == [] and fit[0]["legs"][0]["shape"] == "own"
        assert past == []

    def test_the_ladder_then_the_bisection_find_the_calmest_that_fits(self, monkeypatch) -> None:
        # 60 km at use_roads 0, 40 km at 1: it fits 50 km from use_roads 0.5.
        (fit, past), calls = self.run(monkeypatch, lambda u: 60 - 20 * u, 50_000.0)
        assert calls[:3] == [presets.use_roads_for(p) for p in routing.FIT_STRESS_LADDER]
        assert len(calls) == 3 + routing.FIT_BISECT_STEPS
        # Positions 70 and 40 are over, 0 fits; 20 fits, 30 fits, 35 fits (use_roads 0.55 -> 49 km).
        assert fit[4] == 35
        assert self.km(fit) * 1000.0 <= 50_000.0
        assert self.km(fit) * 1000.0 > 48_000.0, "the calmest of those that fit"
        # The routes past the target: the router's own first, then the rungs over it.
        assert [o[4] for o in past] == [None, 70, 40]
        assert all(self.km(o) * 1000.0 > 50_000.0 for o in past)

    def test_a_bisection_probe_that_does_not_fit_narrows_it_the_other_way(
        self, monkeypatch
    ) -> None:
        # Fits only from use_roads 0.62.
        (fit, past), _calls = self.run(monkeypatch, lambda u: 60 - 20 * u, 47_600.0)
        # 20 fits, 30 does not (47.7 km), so 25 is tried and fits.
        assert fit[4] == 25
        assert self.km(fit) * 1000.0 <= 47_600.0
        assert [o[4] for o in past] == [None, 70, 40, 30]

    def test_when_nothing_fits_every_route_found_is_past_it(self, monkeypatch) -> None:
        (fit, past), calls = self.run(monkeypatch, lambda u: 60 - 20 * u, 30_000.0)
        assert fit is None
        assert [o[4] for o in past] == [None, 70, 40, 0]
        assert self.km(past[-1]) == pytest.approx(40.0)
        assert len(calls) == len(routing.FIT_STRESS_LADDER), "no bisection where nothing fits"

    def test_with_no_time_it_stops_asking(self, monkeypatch) -> None:
        (fit, past), calls = self.run(
            monkeypatch, lambda u: 60 - 20 * u, 50_000.0, time_left=routing.FIT_MIN_S - 1
        )
        assert calls == [] and fit is None and [o[4] for o in past] == [None]

    def test_a_refusal_stops_it(self, monkeypatch) -> None:
        def refuse(variant, endpoint, payload, deadline):
            raise routing.RouterRefused(400, 442, "no path")

        monkeypatch.setattr(routing, "_call", refuse)
        first = {"legs": [{"shape": "own"}], "summary": {"length": 60.0}}
        got = routing._fit_target(
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
        fit, past = got
        assert fit is None and len(past) == 1 and past[0][0] is first


def option(name: str, km: float, position: int | None) -> tuple:
    trip = {"legs": [{"shape": name}], "summary": {"length": km}}
    return (trip, {"r": name}, {"c": name}, {"t": name}, position)


class TestPastTheTarget:
    """`routing._past_target` (OWNER-DECISIONS 267, 268, 271): which first route a plan
    keeps where the router's own route is past the rider's target."""

    def run(self, monkeypatch, fit, past, readings, target=50_000.0):
        read = []

        def analyse(trip, ctx, deadline, with_events=True):
            name = trip["legs"][0]["shape"]
            read.append((name, ctx.costing))
            return readings.get(name)

        monkeypatch.setattr(refine, "analyse", analyse)
        ctx = refine.Context(
            variant="standard",
            request={},
            costing={},
            when="weekday_offpeak",
            deadline=routing.Deadline(routing.clock() + 40, 35),
            traces={},
            points=[],
            roadway_only=False,
            with_facility=False,
            group=False,
            rate=10.0,
            weight=1.0,
            climb_weight=0.0,
            quiet_cost=1.0,
            maxcalm=True,
            ceiling_m=presets.target_ceiling_m(target),
            target_m=target,
            exposure=presets.EXPOSURE_STRESS_AVERSE,
        )
        got = routing._past_target(fit, past, presets.target_ceiling_m(target), ctx)
        return got, read

    @staticmethod
    def reading(km: float, lts4: float = 0.0, lts3: float = 0.0) -> refine.Analysis:
        return refine.Analysis(
            length_m=km * 1000.0,
            cost_s=1.0,
            exposure_m=lts3 + 8.0 * lts4,
            climb_m=0.0,
            pieces=[],
            classes=[],
            events=[],
            lts4_m=lts4,
            lts3_m=lts3,
            effort_m=km * 1000.0,
        )

    def test_a_route_past_the_target_worth_its_miles_is_kept(self, monkeypatch) -> None:
        fit = option("fit", 48.0, 35)
        own = option("own", 58.0, None)
        # 8 km past the target buys 3,200 m at 1 in 2.5: 4 km of LTS 4 saved is plenty.
        readings = {"fit": self.reading(48.0, lts4=4000.0), "own": self.reading(58.0)}
        got, read = self.run(monkeypatch, fit, [own], readings)
        assert got is own
        # Each read with its own trace costing.
        assert read == [("fit", {"t": "fit"}), ("own", {"t": "own"})]

    def test_one_not_worth_them_is_not(self, monkeypatch) -> None:
        fit = option("fit", 48.0, 35)
        own = option("own", 58.0, None)
        readings = {"fit": self.reading(48.0, lts3=3000.0), "own": self.reading(58.0)}
        got, _read = self.run(monkeypatch, fit, [own], readings)
        assert got is fit

    def test_one_past_the_ceiling_is_not_read(self, monkeypatch) -> None:
        fit = option("fit", 48.0, 35)
        own = option("own", 63.0, None)  # past 62.5 km
        readings = {"fit": self.reading(48.0, lts4=9000.0), "own": self.reading(63.0)}
        got, read = self.run(monkeypatch, fit, [own], readings)
        assert got is fit and read == []

    def test_the_calmest_of_several_worth_it(self, monkeypatch) -> None:
        fit = option("fit", 48.0, 35)
        own, rung = option("own", 60.0, None), option("r70", 55.0, 70)
        readings = {
            "fit": self.reading(48.0, lts4=4000.0),
            "own": self.reading(60.0),
            "r70": self.reading(55.0, lts4=1500.0),
        }
        got, _read = self.run(monkeypatch, fit, [own, rung], readings)
        assert got is own

    def test_where_none_fits_the_least_stressful_within_the_ceiling(self, monkeypatch) -> None:
        """OWNER-DECISIONS 267: "Least-stress route, flagged", not the shortest."""
        own, r40, r0 = option("own", 62.0, None), option("r40", 56.0, 40), option("r0", 52.0, 0)
        readings = {
            "own": self.reading(62.0, lts4=100.0),
            "r40": self.reading(56.0, lts4=2000.0),
            "r0": self.reading(52.0, lts4=5000.0),
        }
        got, _read = self.run(monkeypatch, None, [own, r40, r0], readings)
        assert got is own

    def test_where_none_fits_a_tie_on_stress_is_the_shorter(self, monkeypatch) -> None:
        own, r40 = option("own", 62.0, None), option("r40", 56.0, 40)
        readings = {"own": self.reading(62.0), "r40": self.reading(56.0)}
        got, _read = self.run(monkeypatch, None, [own, r40], readings)
        assert got is r40

    def test_where_none_is_within_the_ceiling_the_calmest_found(self, monkeypatch) -> None:
        """OWNER-DECISIONS 298(2), "Calmest found, flagged (Recommended)": it amends the
        shortest, as first built."""
        own, r0 = option("own", 70.0, None), option("r0", 64.0, 0)
        readings = {"own": self.reading(70.0), "r0": self.reading(64.0, lts4=3000.0)}
        got, read = self.run(monkeypatch, None, [own, r0], readings)
        assert got is own and {name for name, _c in read} == {"own", "r0"}

    def test_where_none_is_within_the_ceiling_a_tie_is_the_shorter(self, monkeypatch) -> None:
        own, r0 = option("own", 70.0, None), option("r0", 64.0, 0)
        readings = {"own": self.reading(70.0), "r0": self.reading(64.0)}
        got, _read = self.run(monkeypatch, None, [own, r0], readings)
        assert got is r0

    def test_where_none_past_the_ceiling_can_be_read_the_shortest(self, monkeypatch) -> None:
        own, r0 = option("own", 70.0, None), option("r0", 64.0, 0)
        got, _read = self.run(monkeypatch, None, [own, r0], {})
        assert got is r0

    def test_the_options_are_read_inside_the_late_deadline(self, monkeypatch) -> None:
        """Keeping the answer's reserve (combined correctness review, S3)."""
        seen = []

        def analyse(trip, ctx, deadline, with_events=True):
            seen.append(deadline)
            return self.reading(56.0)

        monkeypatch.setattr(refine, "analyse", analyse)
        own, r40 = option("own", 62.0, None), option("r40", 56.0, 40)
        ctx = refine.Context(
            variant="standard", request={}, costing={}, when="weekday_offpeak",
            deadline=routing.Deadline(routing.clock() + 40, 35), traces={}, points=[],
            roadway_only=False, with_facility=False, group=False, rate=10.0, weight=1.0,
            climb_weight=0.0, quiet_cost=1.0, maxcalm=True, target_m=50_000.0,
        )  # fmt: skip
        routing._past_target(None, [own, r40], presets.target_ceiling_m(50_000.0), ctx)
        assert seen and all(d.at == ctx.deadline.at - refine.REFINE_TRACE_RESERVE_S for d in seen)

    def test_one_that_cannot_be_read_is_not_chosen(self, monkeypatch) -> None:
        own, r40 = option("own", 62.0, None), option("r40", 56.0, 40)
        readings = {"r40": self.reading(56.0, lts4=3000.0)}  # own reads as None
        got, _read = self.run(monkeypatch, None, [own, r40], readings)
        assert got is r40
        fit = option("fit", 48.0, 35)
        got, _read = self.run(monkeypatch, fit, [own], {"own": self.reading(62.0)})
        assert got is fit, "the one that fits, unread, stays"


class TestTheTargetFields:
    def test_over_the_target(self) -> None:
        got = routing.target_fields(96_561.0 + 4_000.0, 96_561.0, 120_701.25)
        assert got == {
            "target_distance_m": 96_561.0,
            "target_distance_set": True,
            "ceiling_m": 120_701.2,
            "fits": False,
            "over_target_m": 4_000.0,
        }

    def test_within_it(self) -> None:
        got = routing.target_fields(90_000.0, 96_561.0, 120_701.25)
        assert got["fits"] is True and got["over_target_m"] == 0.0

    def test_no_target(self) -> None:
        got = routing.target_fields(90_000.0, None, 148_000.0)
        assert got["fits"] is None and got["over_target_m"] is None
        assert got["target_distance_set"] is False and got["ceiling_m"] == 148_000.0


class TestTheSearchStoppedAtTheCeiling:
    """Combined correctness review, S2: a round whose routes were all past the ceiling
    stops the search with `ceiling`, its own code, never the no-fit answer's
    `target_distance`, so "no route within your target" is never said of a route that
    fits (and `no_fit` is false)."""

    def test_a_route_that_fits_is_not_called_no_fit(self, client, segments, router) -> None:
        fake = FakeRouter(
            {
                # The router's own (2.2 km) fits a 2.4 km target; the search's next
                # round only finds a 3.5 km route, past the 3 km ceiling.
                "route": [route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])])]
                + [route_answer([(VERTICES, 3.5, [10.0, 20.0, 15.0, 30.0])])] * 20,
                "trace_attributes": trace_answer(VERTICES, STANDARD_EDGES),
            }
        )
        router(fake)
        body = post(client, top_body(target_distance_m=2_400)).json()
        search = body["calm_search"]
        assert search["fits"] is True and search["no_fit"] is False
        assert search["limited"] != "target_distance"
        # The search's own stop at the ceiling is `ceiling` (tests/test_longcalm.py,
        # TestTheCeilingInTheSearch).


class TestSeekingHillsAtTheTop:
    """OWNER-DECISIONS 298(3), "Keep stress order + target (Recommended)": with the Hills
    slider seeking climbs at the top of the stress slider the stress-order search and the
    target still apply; only the effort tiebreak inverts (`refine.level3`)."""

    def test_the_search_runs_and_the_target_counts(
        self, client, segments, router, monkeypatch
    ) -> None:
        seen = []
        real = refine.refine

        def spy(trip, ctx):
            seen.append(ctx.hills_seek_weight)
            return real(trip, ctx)

        monkeypatch.setattr(refine, "refine", spy)
        router(standard_router())
        body = post(client, top_body(hills=50, target_distance_m=10_000)).json()
        assert seen == [0.5], "the search ran, preferring climbs at half the slider"
        search = body["calm_search"]
        assert search["limited"] != "seeking"
        assert search["target_distance_m"] == 10_000.0 and search["fits"] is True
        assert body["hills_seek"]["limited"] == "calm_first"
        assert body["hills_seek"]["chosen"] == 0

    def test_no_climb_search_among_alternatives_is_asked(self, client, segments, router) -> None:
        fake = router(standard_router())
        post(client, top_body(hills=50))
        assert all("alternates" not in p for _u, p in fake.calls)

    def test_below_the_top_it_is_the_climb_search_as_before(self, client, segments, router) -> None:
        router(standard_router())
        body = post(client, {**good_body("trailmaxxing"), "stress": 60, "hills": 50}).json()
        assert body["hills_seek"]["limited"] != "calm_first"
        assert (body["calm_search"] or {}).get("limited") in (None, "seeking")

    def test_a_long_calm_plan_is_long_calm_while_seeking(self) -> None:
        assert routing.long_calm_for("trailmaxxing", [US, PENN], 100, False)


class TestTheSpanEdge:
    """The long calm plan starts strictly past the working span (mutation review: the
    span-edge mutant on `long_calm_for` survived)."""

    def test_at_the_span_itself_it_is_not_long_calm(self, monkeypatch) -> None:
        points = [US, [-76.9, 38.95]]
        span = routing.straight_span_m(points)
        monkeypatch.setattr(refine, "REFINE_MAX_SPAN_M", span)
        assert not routing.long_calm_for("trailmaxxing", points, 100, False)
        monkeypatch.setattr(refine, "REFINE_MAX_SPAN_M", span - 1.0)
        assert routing.long_calm_for("trailmaxxing", points, 100, False)

    def test_at_the_span_itself_the_search_runs(self, monkeypatch) -> None:
        points = [US, [-76.9, 38.95]]
        span = routing.straight_span_m(points)
        monkeypatch.setattr(refine, "REFINE_MAX_SPAN_M", span)
        deadline = routing.Deadline(routing.clock() + 40, 35)
        assert routing._refine_limit("default", points, False, False, deadline) is None
        monkeypatch.setattr(refine, "REFINE_MAX_SPAN_M", span - 1.0)
        assert routing._refine_limit("default", points, False, False, deadline) == "span"


class TestALongPlansCandidatesAreInThePlansLegs:
    """Combined correctness review, S1, and mutation review X06: a long calm plan searched
    in legs of its own answers in the plan's legs, its candidates too: no `leg_ends` of the
    search's legs, and no "Stop 1" the rider never placed in a candidate's description."""

    def test_the_answer_and_its_candidate(self, client, segments, router, monkeypatch) -> None:
        router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
                    "trace_attributes": trace_answer(VERTICES, STANDARD_EDGES),
                }
            )
        )
        joined = route_answer(
            [(VERTICES[:3], 1.2, [10.0, 20.0]), (VERTICES[2:], 1.0, [15.0, 30.0])]
        )["trip"]
        other = route_answer(
            [(VERTICES[:3], 1.3, [10.0, 20.0]), (VERTICES[2:], 1.1, [15.0, 30.0])]
        )["trip"]

        def fake_refine(trip, ctx):
            ctx.candidates = [(joined, None), (other, None)]
            return joined, {
                "rate": ctx.rate,
                "rounds": 1,
                "excluded": 0,
                "limited": None,
                "long": {"legs": 2, "searched": 1, "skipped": 0, "stops": [2], "answered": "legs"},
            }

        monkeypatch.setattr(refine, "refine", fake_refine)
        monkeypatch.setattr(refine, "refine_long", fake_refine)
        body = post(client, top_body()).json()
        last = len(body["geometry"]["coordinates"]) - 1
        assert body["leg_ends"] == [last]
        (candidate,) = body["candidates"]
        assert candidate["leg_ends"] == [len(candidate["geometry"]["coordinates"]) - 1]
        assert not [e for e in candidate["description"] if e["kind"] == "via"]
        assert not [e for e in body["description"] if e["kind"] == "via"]


class TestOverTheTargetByChoice:
    """A route past the target where one within it was found (worth its miles, 271) is
    not the no-fit answer: `fits` false, `no_fit` false (correctness review S2)."""

    def test_no_fit_is_false(self, client, segments, router, monkeypatch) -> None:
        fake = FakeRouter(
            {
                "route": [route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])])]
                + [route_answer([(VERTICES, 1.9, [10.0, 20.0, 15.0, 30.0])])] * 5,
                "trace_attributes": trace_answer(VERTICES, STANDARD_EDGES),
            }
        )
        router(fake)
        # The route past the target is the one kept, as where it is worth its miles.
        monkeypatch.setattr(routing, "_past_target", lambda fit, past, ceiling, ctx: past[0])
        body = post(client, top_body(target_distance_m=2_000)).json()
        search = body["calm_search"]
        assert search["fits"] is False and search["over_target_m"] > 0
        assert search["no_fit"] is False and search["limited"] != "target_distance"
