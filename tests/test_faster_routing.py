# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""v0.7.0, "Faster routing, mainly for Go": the Server-Timing header and its log line
(step 1), the first good route (`quick`, step 2), the router calls run together on a
bounded pool (step 3) and the short-term answer cache with what invalidates it (step 5).

The router is the fake of tests/test_route_api.py; where time matters it sleeps for
real, on the real clock, so the pool's overlap is measured, not assumed."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from test_route_api import (  # noqa: F401 (fixtures)
    VERTICES,
    FakeRouter,
    encode_polyline6,
    good_body,
    post,
    route_answer,
    router,
    segments,
    standard_router,
    trace_answer,
)

from core import parallel, route_cache, routing, stress_tiles, timing, workzones
from core.models import BikeshareFeedCache, LiveEditGeneration
from routemaker import workzones as wz

pytestmark = pytest.mark.usefixtures("weekday_clock")

db = pytest.mark.django_db(transaction=True)


def timing_parts(response) -> dict[str, str]:
    """The Server-Timing header, by metric name."""
    header = response["Server-Timing"]
    return {part.split(";")[0].strip(): part.strip() for part in header.split(",")}


# --- Step 1: where the time goes ---------------------------------------------------------


@db
class TestServerTiming:
    def test_a_route_says_each_phase_its_router_calls_and_its_total(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        response = post(client, good_body())
        assert response.status_code == 200
        parts = timing_parts(response)
        for name in ("wait", "cache", "route", "choose", "search", "answer", "total"):
            assert name in parts and ";dur=" in parts[name], name
        # One /route and one trace: the router's own time and how many calls.
        assert parts["router"].startswith('router;desc="2 calls";dur=')
        # The answer cache is off in the suite (conftest); said as such.
        assert parts["cache"].startswith('cache;desc="off"')

    def test_a_refusal_has_its_timing_too(self, client, segments, router) -> None:
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "no path")}))
        response = post(client, good_body())
        assert response.status_code == 422
        parts = timing_parts(response)
        assert "total" in parts and parts["router"].startswith('router;desc="1 calls"')

    def test_the_log_line_has_steps_and_a_band_and_no_place(
        self, client, segments, router, caplog
    ) -> None:
        router(standard_router())
        with caplog.at_level(logging.INFO, logger="core.timing"):
            post(client, good_body())
        (line,) = [r.getMessage() for r in caplog.records if r.name == "core.timing"]
        assert "preset=default" in line and "band=0-2mi" in line and "status=200" in line
        assert "route=" in line and "answer=" in line and "total=" in line
        # No coordinate of the request, in any precision.
        for lon, lat in VERTICES:
            assert str(lat)[:5] not in line and str(lon)[:6] not in line

    def test_the_bands(self) -> None:
        mile = timing.METRES_PER_MILE
        assert [timing.band(m * mile) for m in (0.5, 3, 9.9, 10, 30, 80)] == [
            "0-2mi",
            "2-5mi",
            "5-10mi",
            "10-25mi",
            "25-50mi",
            "50mi+",
        ]


# --- Step 2: the first good route -------------------------------------------------------


@db
class TestQuick:
    def test_the_first_route_is_the_routers_own_marked_provisional(
        self, client, segments, router
    ) -> None:
        """At 90 the full plan runs the calm search, asks for alternatives and checks the
        detour; the first route asks the router once and traces it, and says it is
        provisional."""
        fake = router(standard_router())
        body = post(client, {**good_body(), "stress": 90, "quick": True}).json()
        assert body["provisional"] is True
        assert body["calm_search"] is None and body["candidates"] is None
        assert body["detour"] is None and body["dodges"] is None
        assert fake.endpoints() == ["route", "trace_attributes"]
        assert body["stress_m"]["3"] == pytest.approx(900.0)
        full_fake = router(standard_router())
        full = post(client, {**good_body(), "stress": 90}).json()
        assert full["provisional"] is False and full["calm_search"] is not None
        assert len(full_fake.calls) > len(fake.calls)
        # The same route, the same stress: the first route is a true one, only unsearched.
        assert full["geometry"] == body["geometry"] and full["stress_m"] == body["stress_m"]

    def test_the_hills_slider_asks_no_alternatives_on_a_first_route(
        self, client, segments, router
    ) -> None:
        fake = router(standard_router())
        body = post(client, {**good_body("cargo"), "hills": -60, "quick": True}).json()
        assert body["provisional"] is True
        assert all("alternates" not in p for _u, p in fake.calls)
        assert body["hills_avoid"]["candidates"] == 1 and body["hills_avoid"]["chosen"] == 0

    @pytest.mark.parametrize(
        "extra",
        [
            {"loop": True},
            {"preset": "mountain-bike"},
        ],
    )
    def test_where_a_first_route_cannot_stand_alone_the_full_plan_is_answered(
        self, client, segments, router, extra
    ) -> None:
        router(standard_router())
        body = {**good_body(), **extra, "quick": True}
        response = post(client, body)
        assert response.status_code == 200, response.content
        assert response.json()["provisional"] is False

    def test_novice_offers_wait_for_the_full_plan(self, client, segments, router) -> None:
        """The first route of a Novice and Nervous ride carries no offer (it would come and
        go as the better route arrives); the full plan carries it as before."""
        router(standard_router())
        quick = post(client, {**good_body("novice"), "quick": True}).json()
        assert quick["provisional"] is True and quick["novice"] is None
        full = post(client, good_body("novice")).json()
        assert full["novice"] is not None and full["novice"]["transit"] is True

    def test_quick_applies(self) -> None:
        assert routing.quick_applies("default", False, False, False)
        assert not routing.quick_applies("default", True, False, False)
        assert not routing.quick_applies("default", False, True, False)
        assert not routing.quick_applies("default", False, False, True)
        assert not routing.quick_applies("mountain-bike", False, False, False)


def _closure_row(zone: wz.Zone) -> None:
    BikeshareFeedCache.objects.update_or_create(
        key=workzones.KEY,
        defaults={
            "payload": {
                "feeds": {
                    "md": {"read_at": datetime.now(UTC).isoformat(), "zones": [zone.to_json()]}
                }
            },
            "fetched_at": datetime.now(UTC),
        },
    )
    workzones.forget()


@db
@pytest.mark.usefixtures("segments")
def test_a_first_route_still_goes_round_a_closure_and_says_so(client, monkeypatch) -> None:
    """Closures stay correct on the first route: the zone closed to bicycles is left out of
    its /route, and the answer carries the closures as the full plan does."""
    side = ((-77.045, 38.905), (-77.045, 38.910))
    until = datetime.now(UTC) + timedelta(days=30)
    _closure_row(wz.Zone("md-c", "md", wz.CLOSED, 0, side, "Side Road", None, None, until))
    fake = standard_router()
    monkeypatch.setattr(routing, "_transport", fake)
    try:
        body = post(client, {**good_body(), "quick": True}).json()
        full = post(client, good_body()).json()
    finally:
        workzones.forget()
    routes = [p for url, p in fake.calls if url.endswith("/route")]
    assert len(routes[0]["exclude_polygons"]) == 1
    assert body["provisional"] is True
    assert body["work_zones"]["routed_round"] == 1
    # What the first route says of the closures is what the full plan says (ride_at is
    # "now" for each request, so milliseconds apart).
    said = {k: v for k, v in body["work_zones"].items() if k != "ride_at"}
    assert said == {k: v for k, v in full["work_zones"].items() if k != "ride_at"}


# --- Step 3: independent calls together, on a bounded pool --------------------------------


class SlowRouter:
    """Answers by what is asked (never by order, so calls may come in any order), each
    call taking `seconds` of real time, and counts the calls in flight at once."""

    def __init__(self, legs: list[list[tuple[float, float]]], seconds: float) -> None:
        self.legs = legs
        self.seconds = seconds
        self.lock = threading.Lock()
        self.now = 0
        self.most = 0
        self.calls: list[str] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        endpoint = url.rsplit("/", 1)[1]
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
            self.calls.append(endpoint)
        try:
            time.sleep(self.seconds)
            if endpoint == "route":
                return route_answer([(leg, 0.5, [1.0] * len(leg)) for leg in self.legs])
            shape = payload["encoded_polyline"]
            (leg,) = [leg for leg in self.legs if encode_polyline6(leg) == shape]
            return trace_answer(leg, [(101, 0, len(leg) - 1, 0.5)])
        finally:
            with self.lock:
                self.now -= 1


def four_legs() -> list[list[tuple[float, float]]]:
    return [list(VERTICES[i : i + 2]) for i in range(4)]


@db
class TestParallel:
    def test_a_routes_legs_are_traced_together_within_the_bound(
        self, client, segments, monkeypatch, settings
    ) -> None:
        """Four legs, each trace 0.3 s: one after another 1.2 s; on a pool of two, 0.6 s,
        and never more than two at once. The answer is the same either way."""
        legs = four_legs()
        points = [list(VERTICES[i]) for i in range(5)]
        answers = {}
        for size in (1, 2):
            settings.ROUTER_PARALLEL_CALLS = size
            slow = SlowRouter(legs, 0.3)
            monkeypatch.setattr(routing, "_transport", slow)
            began = time.perf_counter()
            response = post(client, {"points": points, "preset": "default"})
            took = time.perf_counter() - began
            assert response.status_code == 200, response.content
            answers[size] = (response.json(), took, slow.most, slow.calls.count("trace_attributes"))
        serial, pooled = answers[1], answers[2]
        assert serial[2] == 1 and pooled[2] == 2, "the pool's bound holds"
        assert serial[3] == pooled[3] == 4, "each leg traced once"
        assert pooled[1] < serial[1] - 0.45, (serial[1], pooled[1])
        for key in ("geometry", "stress_m", "leg_ends", "stress_spans", "description"):
            assert pooled[0][key] == serial[0][key], key

    def test_a_trace_that_fails_on_the_pool_fails_where_it_is_read(self, settings) -> None:
        """A failure on the pool is raised to the reader that would have asked for it, once,
        and is not remembered (`routing._settled`)."""
        settings.ROUTER_PARALLEL_CALLS = 2
        traces: dict = {}
        key = routing._trace_key("standard", {}, "abc")
        traces[key] = parallel.done(error=routing.RouterUnavailable("down"))
        with pytest.raises(routing.RouterUnavailable):
            routing._settled(traces, key)
        assert key not in traces

    def test_a_trace_prefetched_to_a_shorter_deadline_is_asked_again_inline(
        self, settings, monkeypatch
    ) -> None:
        """A trace prefetched for a step held to a shorter deadline (the middle-of-the-hills
        check) that ran out is not this reader's running out: a reader with budget left asks
        again inline; one with none gets the DeadlineExceeded."""
        settings.ROUTER_PARALLEL_CALLS = 2
        asked = []

        def trace_leg(variant, costing, shape, deadline):
            asked.append(deadline)
            return {"edges": []}

        monkeypatch.setattr(routing, "trace_leg", trace_leg)
        key = routing._trace_key("standard", {}, "abc")
        later = routing.Deadline(routing.clock() + 30, 10)
        traces = {key: parallel.done(error=routing.DeadlineExceeded("step ran out"))}
        assert routing._trace("standard", {}, "abc", later, traces) == {"edges": []}
        assert asked == [later] and traces[key] == {"edges": []}

        spent = routing.Deadline(routing.clock() - 1, 10)
        traces = {key: parallel.done(error=routing.DeadlineExceeded("step ran out"))}
        with pytest.raises(routing.DeadlineExceeded):
            routing._trace("standard", {}, "abc", spent, traces)
        assert len(asked) == 1 and key not in traces

    def test_the_pool_is_bounded_and_carries_the_requests_context(self, settings) -> None:
        settings.ROUTER_PARALLEL_CALLS = 3
        lock = threading.Lock()
        state = {"now": 0, "most": 0}
        timings = timing.Timings()
        token = timing.start(timings)

        def work(_n: int) -> bool:
            with lock:
                state["now"] += 1
                state["most"] = max(state["most"], state["now"])
            time.sleep(0.05)
            timing.record_call(0.05)
            with lock:
                state["now"] -= 1
            return timing.current() is timings

        try:
            futures = [parallel.submit(work, n) for n in range(9)]
            assert all(f.result(timeout=5) for f in futures)
        finally:
            timing.stop(token)
        assert state["most"] == 3
        assert timings.calls == 9

    def test_a_pool_thread_never_waits_on_the_pool(self, settings) -> None:
        """A submit from inside the pool runs where it is (a full pool cannot deadlock)."""
        settings.ROUTER_PARALLEL_CALLS = 2

        def inner() -> str:
            return threading.current_thread().name

        def outer() -> tuple[str, str]:
            return threading.current_thread().name, parallel.submit(inner).result(timeout=1)

        futures = [parallel.submit(outer) for _ in range(4)]
        for future in futures:
            mine, theirs = future.result(timeout=5)
            assert mine == theirs

    def test_at_one_nothing_goes_to_the_pool(self, settings) -> None:
        settings.ROUTER_PARALLEL_CALLS = 1
        assert not parallel.enabled()
        future = parallel.submit(lambda: threading.current_thread().name)
        assert future.done() and future.result() == threading.current_thread().name


# --- Step 5: the short-term cache ----------------------------------------------------------


@pytest.fixture
def cache_on(settings):
    settings.ROUTE_CACHE_TTL_S = route_cache.TTL_S
    route_cache.clear()
    yield
    route_cache.clear()


def cache_said(response) -> str:
    return timing_parts(response)["cache"]


@db
@pytest.mark.usefixtures("cache_on")
class TestCache:
    def test_the_same_request_is_answered_from_the_cache(self, client, segments, router) -> None:
        fake = router(standard_router())
        first = post(client, good_body())
        asked = len(fake.calls)
        again = post(client, good_body())
        assert len(fake.calls) == asked, "no router call"
        assert again.json() == first.json()
        assert cache_said(first).startswith('cache;desc="miss"')
        assert cache_said(again).startswith('cache;desc="hit"')

    def test_points_within_about_ten_metres_are_the_same_request(
        self, client, segments, router
    ) -> None:
        fake = router(standard_router())
        post(client, good_body())
        asked = len(fake.calls)
        moved = good_body()
        moved["points"][0] = [moved["points"][0][0] + 0.00002, moved["points"][0][1] - 0.00002]
        assert cache_said(post(client, moved)).startswith('cache;desc="hit"')
        assert len(fake.calls) == asked
        moved["points"][0] = [moved["points"][0][0] + 0.001, moved["points"][0][1]]
        assert cache_said(post(client, moved)).startswith('cache;desc="miss"')

    @pytest.mark.parametrize(
        "change",
        [
            {"stress": 40},
            {"hills": -40},
            {"when": "night"},
            {"avoid_gravel": True},
            {"trails_off": True},
            {"closure_bypass": ["md-c"]},
            {"preset": "novice"},
        ],
    )
    def test_every_dial_is_part_of_the_key(self, client, segments, router, change) -> None:
        router(standard_router())
        post(client, good_body())
        response = post(client, {**good_body(), **change})
        assert response.status_code == 200, response.content
        assert cache_said(response).startswith('cache;desc="miss"')

    def test_an_edit_makes_every_answer_before_it_stale(self, client, segments, router) -> None:
        """A road-panel edit or undo bumps the live table's edit generation
        (`stress_edits.bump_generation`): the same request is planned again."""
        router(standard_router())
        post(client, good_body())
        oid, _columns, generation = stress_tiles.live_state()
        LiveEditGeneration.objects.update_or_create(
            table_oid=oid, defaults={"generation": generation + 1}
        )
        assert cache_said(post(client, good_body())).startswith('cache;desc="miss"')
        assert cache_said(post(client, good_body())).startswith('cache;desc="hit"')

    def test_a_closure_change_makes_every_answer_before_it_stale(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        until = datetime.now(UTC) + timedelta(days=30)
        side = ((-77.045, 38.905), (-77.045, 38.910))
        try:
            _closure_row(wz.Zone("md-c", "md", wz.CLOSED, 0, side, "Side", None, None, until))
            post(client, good_body())
            assert cache_said(post(client, good_body())).startswith('cache;desc="hit"')
            # The feed's next read ends the closure a day earlier: a new closure state.
            sooner = until - timedelta(days=1)
            _closure_row(wz.Zone("md-c", "md", wz.CLOSED, 0, side, "Side", None, None, sooner))
            assert cache_said(post(client, good_body())).startswith('cache;desc="miss"')
        finally:
            workzones.forget()

    def test_the_ride_time_of_the_moment_is_part_of_the_key(
        self, client, segments, router, monkeypatch
    ) -> None:
        """No `when`: the setting of the moment. A plan made before the evening rush is
        not given once the rush has started."""
        from routemaker import ridetime

        router(standard_router())
        post(client, good_body())
        rush = datetime(2026, 9, 30, 17, 0, tzinfo=ridetime.ZONE)
        assert ridetime.when_at(rush) == ridetime.WEEKDAY_RUSH
        monkeypatch.setattr(routing.timezone, "now", lambda: rush)
        assert cache_said(post(client, good_body())).startswith('cache;desc="miss"')

    def test_a_full_plan_answers_a_first_route_request_not_the_other_way(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        quick = post(client, {**good_body(), "stress": 90, "quick": True}).json()
        assert quick["provisional"] is True
        # A first route kept does not answer a request for the full plan.
        full = post(client, {**good_body(), "stress": 90})
        assert cache_said(full).startswith('cache;desc="miss"')
        assert full.json()["provisional"] is False
        # The full plan kept answers the next request for a first route, and the tap
        # that would have waited for the search does not.
        again = post(client, {**good_body(), "stress": 90, "quick": True})
        assert cache_said(again).startswith('cache;desc="hit"')
        assert again.json()["provisional"] is False

    def test_an_answer_the_budget_cut_short_is_not_kept(self, client, segments, router) -> None:
        router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [1.0])]),
                    "trace_attributes": routing.DeadlineExceeded("no time left"),
                }
            )
        )
        first = post(client, good_body())
        assert first.status_code == 200 and first.json()["stress_m"]["unknown"] > 0
        assert route_cache.size() == 0
        assert cache_said(post(client, good_body())).startswith('cache;desc="miss"')

    def test_bikeshare_and_transit_are_never_kept(self) -> None:
        """They are planned by their own paths (`api._plan`), which never read the cache:
        live docks and departures."""
        import inspect

        from core import api

        source = inspect.getsource(api._plan)
        assert source.index("BIKESHARE_PRESETS") < source.index("_planned(")
        assert source.index("TRANSIT_PRESETS") < source.index("_planned(")


class TestCacheParts:
    def test_entries_expire_and_the_oldest_go_first(self, settings, monkeypatch) -> None:
        settings.ROUTE_CACHE_TTL_S = route_cache.TTL_S
        route_cache.clear()
        now = [1000.0]
        monkeypatch.setattr(route_cache, "_clock", lambda: now[0])
        route_cache.put("a", {"provisional": False}, 5)
        assert route_cache.get("a") is not None
        now[0] += 5
        assert route_cache.get("a") is None
        monkeypatch.setattr(route_cache, "MAX_ENTRIES", 2)
        for key in ("x", "y", "z"):
            route_cache.put(key, {"provisional": False})
        assert route_cache.get("x") is None and route_cache.get("z") is not None
        route_cache.clear()

    def test_never_kept_past_ten_minutes(self, settings, monkeypatch) -> None:
        settings.ROUTE_CACHE_TTL_S = route_cache.TTL_S
        route_cache.clear()
        now = [0.0]
        monkeypatch.setattr(route_cache, "_clock", lambda: now[0])
        route_cache.put("a", {"provisional": False}, 10_000)
        now[0] += route_cache.TTL_S
        assert route_cache.get("a") is None

    def test_a_first_route_is_kept_apart_and_replaced_by_its_full_plan(self, settings) -> None:
        settings.ROUTE_CACHE_TTL_S = route_cache.TTL_S
        route_cache.clear()
        route_cache.put("k", {"provisional": True, "n": 1})
        assert route_cache.get("k") is None
        assert route_cache.get("k", quick=True) == {"provisional": True, "n": 1}
        route_cache.put("k", {"provisional": False, "n": 2})
        assert route_cache.get("k", quick=True) == {"provisional": False, "n": 2}
        assert route_cache.size() == 1
        route_cache.clear()

    @pytest.mark.django_db
    def test_kept_no_later_than_a_closure_starts_or_ends(self, settings, monkeypatch) -> None:
        settings.ROUTE_CACHE_TTL_S = route_cache.TTL_S
        soon = datetime.now(UTC) + timedelta(minutes=3)
        zone = wz.Zone("z", "md", wz.CLOSED, 0, ((0, 0), (0, 1)), None, None, soon, None)
        found = workzones.Snapshot((zone,), {"md": "current"}, {"md": None})
        monkeypatch.setattr(workzones, "snapshot", lambda now=None: found)
        monkeypatch.setattr(route_cache, "_edits_part", lambda: [1, [], 0])
        monkeypatch.setattr(route_cache, "_approved_part", lambda preset: [])
        key = route_cache.key_for({"points": [[0, 0]], "preset": "default"}, "night", "t", "")
        assert key is not None and 150 < key.valid_s <= 180

    def test_the_request_part_leaves_quick_out_and_rounds_the_points(self) -> None:
        a = route_cache.request_part({"points": [[-77.04001, 38.90001]], "quick": True})
        b = route_cache.request_part({"points": [[-77.04002, 38.90002]], "quick": False})
        assert a == b == {"points": [[-77.04, 38.9]]}
        assert json.dumps(a)

    def test_off_at_zero(self, settings) -> None:
        settings.ROUTE_CACHE_TTL_S = 0
        assert route_cache.key_for({"points": [], "preset": "default"}, "night", "t", "") is None
