"""Run (Stephen, 2026-11-02: "would run use any different routing?", "Yes, make it in its own
thread"): `core.run_plan` on a hand-made router, and the API's answer for it."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core import presets, refine, routing, run_plan, walk_pricing
from core.dedodge import encode_polyline6

EASTERN = ZoneInfo("America/New_York")
START = (-77.05, 38.92)
END = (-77.03, 38.92)


def line(a, b, n=20):
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


def leg(shape, seconds, km, maneuvers=()):
    return {
        "shape": encode_polyline6(shape),
        "summary": {"time": seconds, "length": km},
        "maneuvers": list(maneuvers),
    }


def answer(*legs):
    first, *rest = legs
    return {
        "trip": {"legs": [first]},
        "alternates": [{"trip": {"legs": [other]}} for other in rest],
    }


def edges(shape, use, km, signals=0, elevations=None):
    """A trace of one edge a step of `shape`, all of `use`; the first `signals` crossings
    signalled across a busy road."""
    out = []
    steps = len(shape) - 1
    for i in range(steps):
        e = {
            "use": use,
            "length": km / steps,
            "road_class": "service_other",
            "names": [],
            "begin_shape_index": i,
            "end_shape_index": i + 1,
            "end_node": {"intersecting_edges": []},
        }
        if elevations is not None:
            e["mean_elevation"] = elevations[i]
        out.append(e)
    # Signalled crossings: a crossing edge with a busy road at its node, signalled.
    for k in range(signals):
        i = 1 + 2 * k
        out[i]["use"] = "pedestrian_crossing"
        out[i]["traffic_signal"] = True
        out[i - 1]["end_node"] = {
            "intersecting_edges": [{"road_class": "primary", "use": "road", "driveability": "both"}]
        }
    return {"edges": out, "shape": encode_polyline6(shape)}


class FakeCall:
    """The router, as `run_plan.Router` asks it: `route` from `routes(payload)`, traces from
    `traces[shape]`, `/locate` answering nothing."""

    def __init__(self, routes, traces):
        self.routes = routes
        self.traces = traces
        self.asked: list[tuple[str, dict]] = []

    def __call__(self, action, payload, cap_s):
        self.asked.append((action, payload))
        if action == "route":
            found = self.routes(payload)
            if found is None:
                raise routing.RouterRefused(400, 442, "no route")
            return found
        if action == "trace_attributes":
            return self.traces[payload["encoded_polyline"]]
        return []


def router(fake, seconds=30.0):
    return run_plan.Router(routing.clock() + seconds, fake)


class TestDials:
    def test_the_pace_is_the_runners_held_to_the_range(self) -> None:
        assert run_plan.pace_of(None) == pytest.approx(9.7)
        assert run_plan.pace_of(11.3) == pytest.approx(11.3)
        assert run_plan.pace_of(30.0) == run_plan.RUN_PACE_MAX_KMH
        assert run_plan.pace_of(1.0) == run_plan.RUN_PACE_MIN_KMH

    def test_the_costing_is_on_foot_at_the_pace_with_the_hills_slider(self) -> None:
        ask = run_plan.RunAsk(pace_kmh=11.3, hills=-100)
        options = run_plan.costing_options(ask)["pedestrian"]
        assert options["walking_speed"] == pytest.approx(11.3)
        assert options["use_hills"] == presets.use_hills_for(-100) == 0.0
        assert options["use_tracks"] == run_plan.USE_TRACKS
        assert "use_lit" not in options

    def test_after_dark_lit_ways_are_favoured(self) -> None:
        options = run_plan.costing_options(run_plan.RunAsk(dark=True))["pedestrian"]
        assert options["use_lit"] == run_plan.USE_LIT_AFTER_DARK

    @pytest.mark.parametrize(
        ("hour", "minute", "dark"),
        [
            (12, 0, False),
            (6, 0, True),
            (6, 30, False),
            (17, 30, False),
            (18, 15, True),
            (23, 0, True),
        ],
    )
    def test_dark_is_civil_dusk_to_civil_dawn(self, hour, minute, dark) -> None:
        # 2 November 2026 in Washington: sunrise about 6:35 am, sunset 5:06 pm (EST); civil
        # twilight about 27 min either side.
        at = datetime(2026, 11, 2, hour, minute, tzinfo=EASTERN)
        assert run_plan.is_dark(at) is dark

    def test_the_night_ride_time_is_dark_whatever_the_clock(self) -> None:
        assert run_plan.is_dark(datetime(2026, 11, 2, 12, 0, tzinfo=EASTERN), "night")


class TestWeigh:
    def test_a_trail_beats_a_street_as_quick(self) -> None:
        street = walk_pricing.Reading(metres=1000.0)
        trail = walk_pricing.Reading(metres=1000.0, trail_m=1000.0)
        assert run_plan.weigh(400.0, trail) < run_plan.weigh(400.0, street)
        # A trail second counts TRAIL_WEIGHT of a street's.
        assert run_plan.weigh(400.0, trail) == pytest.approx(400.0 * run_plan.TRAIL_WEIGHT)

    def test_a_quiet_street_beats_a_busier_one_and_a_long_stretch_counts_more(self) -> None:
        """Stephen, 2026-11-02: "Runners like long safe paths and roads too"."""
        busy = walk_pricing.Reading(metres=1000.0)
        quiet = walk_pricing.Reading(metres=1000.0, quiet_m=1000.0)
        unbroken = walk_pricing.Reading(metres=1000.0, quiet_m=1000.0, long_m=1000.0)
        assert run_plan.weigh(400.0, unbroken) < run_plan.weigh(400.0, quiet)
        assert run_plan.weigh(400.0, quiet) < run_plan.weigh(400.0, busy)
        trail = walk_pricing.Reading(metres=1000.0, trail_m=1000.0)
        assert run_plan.weigh(400.0, trail) < run_plan.weigh(400.0, quiet)

    def test_a_crossing_breaks_a_long_stretch(self) -> None:
        def edge(use, metres, road_class="residential"):
            return {"use": use, "length": metres / 1000.0, "road_class": road_class}

        unbroken = [edge("road", 500), edge("footway", 500)]
        broken = [edge("road", 500), edge("pedestrian_crossing", 10), edge("footway", 500)]
        busy = [edge("road", 900, "primary")]
        assert walk_pricing._calm(unbroken) == (500.0, 1000.0)
        assert walk_pricing._calm(broken) == (500.0, 0.0)
        assert walk_pricing._calm(busy) == (0.0, 0.0)

    def test_each_light_costs_its_wait_three_times(self) -> None:
        light = walk_pricing.Crossing(
            m=10.0, point=(0.0, 0.0), level=walk_pricing.BUSY, signal=True, marked=True, slip=False
        )
        reading = walk_pricing.Reading(metres=1000.0, crossings=(light, light))
        assert presets.wait_weight_for(presets.RUN) == 3.0
        assert run_plan.weigh(400.0, reading) == pytest.approx(
            400.0 + 2 * 3 * run_plan.SIGNAL_WAIT_S
        )


class TestALeg:
    def test_the_way_with_the_trail_and_fewer_lights_is_run(self) -> None:
        streets = line(START, END)
        trail = line(START, (-77.04, 38.925)) + line((-77.04, 38.925), END)[1:]
        found = answer(leg(streets, 600.0, 1.7), leg(trail, 640.0, 1.8))
        fake = FakeCall(
            lambda payload: found,
            {
                encode_polyline6(streets): edges(streets, "road", 1.7, signals=3),
                encode_polyline6(trail): edges(trail, "cycleway", 1.8),
            },
        )
        walked = run_plan.run_leg(router(fake), [START, END], run_plan.RunAsk())
        assert walked is not None
        assert walked.metres == pytest.approx(1800.0)
        assert walked.reading.trail_m == pytest.approx(1800.0)
        route = next(p for a, p in fake.asked if a == "route")
        assert route["costing"] == "pedestrian"
        assert route["alternates"] == run_plan.ALTERNATES
        assert route["costing_options"]["pedestrian"]["walking_speed"] == pytest.approx(9.7)

    @pytest.mark.parametrize(
        ("cap_m", "metres"),
        [(None, 1700.0), (3000.0, 2600.0), (2000.0, 1700.0)],
        ids=["no target: the quicker street", "the trail fits the target", "past its ceiling"],
    )
    def test_with_stops_a_target_takes_the_most_trail_at_or_under_it(self, cap_m, metres) -> None:
        """Stephen, 2026-11-02: with stops placed a run's target works as Trailmaxxing's."""
        streets = line(START, END)
        trail = line(START, (-77.04, 38.93)) + line((-77.04, 38.93), END)[1:]
        found = answer(leg(streets, 600.0, 1.7), leg(trail, 920.0, 2.6))
        fake = FakeCall(
            lambda payload: found,
            {
                encode_polyline6(streets): edges(streets, "road", 1.7),
                encode_polyline6(trail): edges(trail, "cycleway", 2.6),
            },
        )
        walked = run_plan.run_leg(router(fake), [START, END], run_plan.RunAsk(), cap_m=cap_m)
        assert walked is not None and walked.metres == pytest.approx(metres)

    def test_each_leg_gets_its_share_of_the_target(self) -> None:
        caps = run_plan.leg_caps([START, END, (-77.03, 38.94)], 6000.0)
        assert sum(caps) == pytest.approx(6000.0)
        assert run_plan.leg_caps([START, END], None) == [None]

    def test_climb_is_read_from_the_edges_elevations(self) -> None:
        shape = line(START, END, 4)
        fake = FakeCall(
            lambda payload: answer(leg(shape, 600.0, 1.7)),
            {encode_polyline6(shape): edges(shape, "path", 1.7, elevations=[10, 20, 15, 30])},
        )
        walked = run_plan.run_leg(router(fake), [START, END], run_plan.RunAsk())
        assert walked.reading.climb_m == pytest.approx(25.0)
        assert walked.reading.descent_m == pytest.approx(5.0)


class TestLoops:
    def test_the_way_back_avoids_the_way_out(self) -> None:
        out = line(START, END)
        back = line(END, (-77.04, 38.93)) + line((-77.04, 38.93), START)[1:]
        same = list(reversed(out))

        def routes(payload):
            ends = [(loc["lon"], loc["lat"]) for loc in payload["locations"]]
            if ends[0] == START:
                return answer(leg(out, 600.0, 1.7))
            # Home: another way only with the way out avoided.
            return answer(
                leg(back, 700.0, 2.2) if "exclude_locations" in payload else leg(same, 600.0, 1.7)
            )

        fake = FakeCall(
            routes,
            {encode_polyline6(s): edges(s, "path", 2.0) for s in (out, back, same)},
        )
        run = run_plan.plan([START, END], run_plan.RunAsk(loop=True), router(fake))
        assert run.metres == pytest.approx(1700.0 + 2200.0)
        assert run.shape[0] == pytest.approx(START) and run.shape[-1] == pytest.approx(START)
        assert run.loop["overlap_pct"] < 100 * refine.LOOP_OVERLAP_OK
        assert run.loop["excluded"] > 0
        assert run.leg_ends == [len(out) - 1, len(run.shape) - 1]
        excluded = next(p for a, p in fake.asked if a == "route" and "exclude_locations" in p)
        # None of the points avoided is near either end: the way back can leave and arrive.
        for point in excluded["exclude_locations"]:
            assert abs(point["lon"] - START[0]) > 0.001 and abs(point["lon"] - END[0]) > 0.001

    def test_with_one_way_only_the_way_out_is_run_back(self) -> None:
        out = line(START, END)
        same = list(reversed(out))

        def routes(payload):
            ends = [(loc["lon"], loc["lat"]) for loc in payload["locations"]]
            return answer(leg(out if ends[0] == START else same, 600.0, 1.7))

        fake = FakeCall(routes, {encode_polyline6(s): edges(s, "path", 1.7) for s in (out, same)})
        run = run_plan.plan([START, END], run_plan.RunAsk(loop=True), router(fake))
        assert run.loop["fallback"] == "out_and_back"
        assert run.metres == pytest.approx(3400.0)

    def test_a_start_alone_runs_a_loop_near_its_target(self) -> None:
        target = 8000.0

        def routes(payload):
            points = [(loc["lon"], loc["lat"]) for loc in payload["locations"]]
            assert points[0] == points[-1] == START
            assert [loc["type"] for loc in payload["locations"]] == [
                "break",
                "through",
                "through",
                "break",
            ]
            shape = []
            for a, b in zip(points, points[1:], strict=False):
                shape.extend(line(a, b, 10)[1 if shape else 0 :])
            # The router's run is 1.3 times the triangle's straight sides, as the guess has it.
            straight = sum(
                run_plan.haversine(run_plan.Point(*a), run_plan.Point(*b))
                for a, b in zip(points, points[1:], strict=False)
            )
            km = straight * 1.3 / 1000.0
            found = answer(leg(shape, km * 370.0, km))
            fake.traces[encode_polyline6(shape)] = edges(shape, "path", km)
            return found

        fake = FakeCall(routes, {})
        run = run_plan.plan([START], run_plan.RunAsk(loop=True, target_m=target), router(fake))
        assert abs(run.metres - target) / target <= run_plan.TARGET_TOLERANCE
        assert run.shape[0] == pytest.approx(START) and run.shape[-1] == pytest.approx(START)
        assert run.loop["tried"] >= len(run_plan.TARGET_BEARINGS)
        # No way out and back to compare, so no "way back shares..." note (lib/loop.ts loopNote).
        assert run.loop["overlap_pct"] is None and run.loop["shared_m"] is None
        # The chosen triangle is not routed again to say its crossings.
        assert (
            sum(1 for action, _ in fake.asked if action == "route")
            <= len(run_plan.TARGET_BEARINGS) + 1
        )

    def test_a_start_alone_needs_a_loop_and_a_target(self) -> None:
        with pytest.raises(run_plan.NoRun):
            run_plan.plan([START], run_plan.RunAsk(), router(FakeCall(lambda p: None, {})))

    def test_a_router_that_answers_nothing_is_down_not_no_way(self) -> None:
        def down(action, payload, cap_s):
            raise routing.RouterUnavailable("down")

        with pytest.raises(run_plan.RouterDown):
            run_plan.plan([START, END], run_plan.RunAsk(), router(down))

    def test_a_run_out_of_time_is_busy_not_no_way(self) -> None:
        def slow(action, payload, cap_s):
            raise routing.DeadlineExceeded("late")

        with pytest.raises(run_plan.RunTimedOut):
            run_plan.plan([START, END], run_plan.RunAsk(), router(slow))

    def test_a_run_of_many_legs_asks_for_no_alternates(self) -> None:
        stops = [(-77.05 + 0.004 * i, 38.92) for i in range(run_plan.MANY_LEGS + 2)]

        def routes(payload):
            a, b = ((loc["lon"], loc["lat"]) for loc in payload["locations"])
            shape = line(a, b, 4)
            fake.traces[encode_polyline6(shape)] = edges(shape, "path", 0.3)
            return answer(leg(shape, 120.0, 0.3))

        fake = FakeCall(routes, {})
        run_plan.plan(stops, run_plan.RunAsk(), router(fake))
        assert all(
            "alternates" not in payload for action, payload in fake.asked if action == "route"
        )

    def test_self_overlap_finds_a_spur_run_out_and_back(self) -> None:
        loop = line(START, END) + line(END, (-77.04, 38.93))[1:] + line((-77.04, 38.93), START)[1:]
        spur_end = (-77.04, 38.90)
        spur = line(START, spur_end) + line(spur_end, START)[1:]
        assert run_plan.self_overlap(loop) == pytest.approx(0.0)
        assert run_plan.self_overlap(spur) > 0.5


# --- The API -----------------------------------------------------------------------------------

db = pytest.mark.django_db(transaction=True)


@pytest.fixture
def fake_router(monkeypatch):
    out = line(START, END)
    back = line(END, (-77.04, 38.93)) + line((-77.04, 38.93), START)[1:]
    traces = {encode_polyline6(s): edges(s, "cycleway", 2.0) for s in (out, back)}
    asked: list[tuple[str, dict]] = []

    def transport(url, payload, timeout):
        action = url.rsplit("/", 1)[1]
        asked.append((action, payload))
        if action == "route":
            starts = (payload["locations"][0]["lon"], payload["locations"][0]["lat"])
            if starts == START:
                return answer(
                    leg(
                        out,
                        600.0,
                        1.7,
                        [
                            {
                                "type": 10,
                                "begin_shape_index": 5,
                                "street_names": ["Rock Creek Trail"],
                                "length": 0.5,
                            }
                        ],
                    )
                )
            return answer(leg(back, 700.0, 2.2))
        if action == "trace_attributes":
            return traces[payload["encoded_polyline"]]
        return []

    monkeypatch.setattr(routing, "_transport", transport)
    return asked


def post(client, body):
    return client.post("/api/route", data=json.dumps(body), content_type="application/json")


@db
class TestTheApi:
    def test_a_run_is_answered_as_a_walk_line_with_its_turns(self, client, fake_router) -> None:
        response = post(
            client,
            {
                "points": [list(START), list(END)],
                "preset": "run",
                "run_pace_kmh": 11.3,
                "hills": -50,
            },
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["preset"] == "run"
        assert body["distance_m"] == pytest.approx(1700.0)
        assert body["transit"]["mode"] == "run"
        step = body["transit"]["steps"][0]
        assert step["mode"] == "walk" and step["route_line"] is True
        assert step["turns"][0]["street"] == "Rock Creek Trail"
        assert body["run"]["pace_kmh"] == pytest.approx(11.3)
        assert body["run"]["trail_m"] == pytest.approx(2000.0)
        pedestrian = next(p for a, p in fake_router if a == "route")["costing_options"][
            "pedestrian"
        ]
        assert pedestrian["walking_speed"] == pytest.approx(11.3)
        assert pedestrian["use_hills"] == presets.use_hills_for(-50)

    def test_a_loop_comes_home_another_way(self, client, fake_router) -> None:
        response = post(client, {"points": [list(START), list(END)], "preset": "run", "loop": True})
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["distance_m"] == pytest.approx(3900.0)
        assert body["loop"]["excluded"] > 0

    def test_a_start_alone_needs_a_loop_and_a_target(self, client, fake_router) -> None:
        assert post(client, {"points": [list(START)], "preset": "run"}).status_code == 400
        assert (
            post(
                client,
                {
                    "points": [list(START)],
                    "preset": "default",
                    "loop": True,
                    "target_distance_m": 5000,
                },
            ).status_code
            == 400
        )

    def test_a_run_out_of_time_is_a_retryable_busy_answer(self, client, monkeypatch) -> None:
        def late(url, payload, timeout):
            raise routing.DeadlineExceeded("late")

        monkeypatch.setattr(routing, "_transport", late)
        response = post(client, {"points": [list(START), list(END)], "preset": "run"})
        assert response.status_code == 503
        assert response["Retry-After"]

    def test_a_long_target_with_stops_is_a_ceiling_not_a_refusal(self, client, fake_router) -> None:
        body = {"points": [list(START), list(END)], "preset": "run", "target_distance_m": 80_000}
        response = post(client, body)
        assert response.status_code == 200
        assert response.json()["run"]["fits"] is True
        alone = {
            "points": [list(START)],
            "preset": "run",
            "loop": True,
            "target_distance_m": 80_000,
        }
        assert post(client, alone).status_code == 400

    def test_the_pace_is_for_run_only(self, client, fake_router) -> None:
        response = post(
            client, {"points": [list(START), list(END)], "preset": "default", "run_pace_kmh": 10}
        )
        assert response.status_code == 400

    def test_a_run_may_say_when_it_starts(self, client, fake_router) -> None:
        response = post(
            client,
            {
                "points": [list(START), list(END)],
                "preset": "run",
                "depart_at": "2026-11-02T19:00:00-05:00",
            },
        )
        assert response.status_code == 200, response.content
        assert response.json()["run"]["dark"] is True
        pedestrian = next(p for a, p in fake_router if a == "route")["costing_options"][
            "pedestrian"
        ]
        assert pedestrian["use_lit"] == run_plan.USE_LIT_AFTER_DARK
