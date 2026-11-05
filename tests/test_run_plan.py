"""Run (Stephen, 2026-11-02: "would run use any different routing?", "Yes, make it in its own
thread"): `core.run_plan` on a hand-made router, and the API's answer for it."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core import presets, refine, routing, run_plan, walk_pricing
from core.dedodge import encode_polyline6
from routemaker import workzones as wz

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

    def test_a_road_crossing_or_light_breaks_a_long_stretch_without_an_edge_of_its_own(
        self,
    ) -> None:
        def edge(use, metres, road_class="residential"):
            return {"use": use, "length": metres / 1000.0, "road_class": road_class}

        quiet = [edge("road", 750), edge("road", 750)]
        assert walk_pricing._calm(quiet) == (1500.0, 1500.0)
        # Straight on across an arterial at 750 m, no crossing way mapped.
        assert walk_pricing._calm(quiet, [750.0]) == (1500.0, 0.0)
        # A sidewalk and a living street carry a stretch on.
        # A sidewalk carries a stretch on to its 800 m but is never credited itself.
        mixed = [edge("sidewalk", 500), edge("living_street", 400)]
        assert walk_pricing._calm(mixed) == (400.0, 400.0)

    def test_a_long_stretch_of_sidewalk_alone_earns_no_credit(self) -> None:
        """Release review S2: trails over sidewalks, so 1 km of sidewalk beside a main road
        is no runner's long stretch."""
        sidewalk = [{"use": "sidewalk", "length": 0.1, "road_class": "primary"} for _ in range(10)]
        assert walk_pricing._calm(sidewalk) == (0.0, 0.0)

    def test_a_refusal_after_a_slow_call_is_still_no_way(self) -> None:
        calls = []

        def slow_then_no(action, payload, cap_s):
            calls.append(action)
            if len(calls) == 1:
                raise routing.DeadlineExceeded("slow")
            raise routing.RouterRefused(400, 442, "no path")

        r = router(slow_then_no)
        assert r.ask("route", {}) is None and r.last_late
        assert r.ask("route", {}) is None and not r.last_late

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

    def test_the_quicker_way_with_three_lights_loses_to_one_with_none(self) -> None:
        """Release review S3: "fewer stops"; two street ways, the lights alone decide."""
        assert run_plan.SIGNAL_WAIT_S == 15.0
        lights = line(START, END)
        none = line(START, (-77.04, 38.921)) + line((-77.04, 38.921), END)[1:]
        found = answer(leg(lights, 600.0, 1.7), leg(none, 640.0, 1.8))
        fake = FakeCall(
            lambda payload: found,
            {
                # Sidewalks: no quiet-street or long-stretch credit, so only the lights differ.
                encode_polyline6(lights): edges(lights, "sidewalk", 1.7, signals=3),
                encode_polyline6(none): edges(none, "sidewalk", 1.8),
            },
        )
        walked = run_plan.run_leg(router(fake), [START, END], run_plan.RunAsk())
        assert walked is not None and walked.metres == pytest.approx(1800.0)

    @pytest.mark.parametrize("use", ["path", "track"])
    def test_a_track_is_a_trail_too(self, use) -> None:
        """Owner: packed gravel and dirt are fine."""
        assert use in walk_pricing.TRAIL_USES

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

    @staticmethod
    def winding_router(ratio_of, use_of=lambda north: "road"):
        """Triangles run `ratio_of(north, side_m)` times their straight sides, `north` whether
        the first corner is north of the start."""

        def routes(payload):
            points = [(loc["lon"], loc["lat"]) for loc in payload["locations"]]
            north = points[1][1] > START[1] + 1e-6 and abs(points[1][0] - START[0]) < 1e-6
            shape = []
            for a, b in zip(points, points[1:], strict=False):
                shape.extend(line(a, b, 10)[1 if shape else 0 :])
            straight = sum(
                run_plan.haversine(run_plan.Point(*a), run_plan.Point(*b))
                for a, b in zip(points, points[1:], strict=False)
            )
            km = straight * ratio_of(north, straight / 3.0) / 1000.0
            fake.traces[encode_polyline6(shape)] = edges(shape, use_of(north), km)
            return answer(leg(shape, km * 370.0, km))

        fake = FakeCall(routes, {})
        return fake

    def test_a_winding_map_still_gives_a_loop_near_its_target(self) -> None:
        """PC check, v0.18.0: a 5,000 m target came back 8,242 m. Here, as in a city, the
        smaller the triangle the more its run winds (2.2 times its sides at the first guess,
        2.7 once sized down): each direction is sized from the runs before it."""
        target = 5000.0
        fake = self.winding_router(lambda north, side: 1.5 + 900.0 / side)
        run = run_plan.plan([START], run_plan.RunAsk(loop=True, target_m=target), router(fake))
        assert abs(run.metres - target) / target <= run_plan.TARGET_TOLERANCE

    def test_off_target_the_nearest_loop_wins_over_the_better_run(self) -> None:
        """Where no loop is near enough, nearness decides, not trail: the northern loop is all
        path but runs three times its sides; it is never the one kept."""
        target = 5000.0
        fake = self.winding_router(
            lambda north, side: (2.4 if north else 1.5) + 900.0 / side,
            lambda north: "path" if north else "road",
        )
        r = router(fake)
        run = run_plan.plan([START], run_plan.RunAsk(loop=True, target_m=target), r)
        assert abs(run.metres - target) / target <= run_plan.TARGET_TOLERANCE

    def test_every_direction_off_until_resized_is_sized_again_from_its_own_run(self) -> None:
        """Review: only the north winds as the guess expects; the rest wind nine times their
        sides. The north is the nearest, and its resizes bring it within the target."""
        target = 5000.0
        fake = self.winding_router(lambda north, side: (1.5 + 900.0 / side) if north else 9.0)
        run = run_plan.plan([START], run_plan.RunAsk(loop=True, target_m=target), router(fake))
        assert abs(run.metres - target) / target <= run_plan.TARGET_TOLERANCE
        assert run.loop["tried"] > len(run_plan.TARGET_BEARINGS)
        routes = sum(1 for action, _ in fake.asked if action == "route")
        assert routes <= len(run_plan.TARGET_BEARINGS) + run_plan.TARGET_RESIZES

    def test_off_target_the_nearer_loop_is_kept_not_the_better_path(self) -> None:
        """Every loop off whatever its size: the north is all path but 9 km, the rest are
        streets at 7 km; the nearer street loop is kept, not the better run."""
        target = 5000.0

        def routes(payload):
            points = [(loc["lon"], loc["lat"]) for loc in payload["locations"]]
            north = points[1][1] > START[1] + 1e-6 and abs(points[1][0] - START[0]) < 1e-6
            km = 9.0 if north else 7.0
            shape = []
            for a, b in zip(points, points[1:], strict=False):
                shape.extend(line(a, b, 10)[1 if shape else 0 :])
            fake.traces[encode_polyline6(shape)] = edges(shape, "path" if north else "road", km)
            return answer(leg(shape, km * 370.0, km))

        fake = FakeCall(routes, {})
        walked, _info = run_plan.target_loop(
            router(fake), START, run_plan.RunAsk(loop=True, target_m=target)
        )
        assert walked is not None and walked.metres == pytest.approx(7000.0)

    def test_a_loop_that_cannot_shrink_is_not_asked_again(self) -> None:
        """Review: a start whose loops stay 8,242 m whatever the size; no triangle twice."""
        target = 5000.0

        def routes(payload):
            points = [(loc["lon"], loc["lat"]) for loc in payload["locations"]]
            shape = []
            for a, b in zip(points, points[1:], strict=False):
                shape.extend(line(a, b, 10)[1 if shape else 0 :])
            fake.traces[encode_polyline6(shape)] = edges(shape, "road", 8.242)
            return answer(leg(shape, 8.242 * 370.0, 8.242))

        fake = FakeCall(routes, {})
        run_plan.plan([START], run_plan.RunAsk(loop=True, target_m=target), router(fake))
        asked = [json.dumps(p["locations"], sort_keys=True) for a, p in fake.asked if a == "route"]
        assert len(asked) == len(set(asked))

    def test_a_corner_snapped_onto_the_start_does_not_size_a_huge_triangle(self) -> None:
        """Review: a first run of 60 m reads as no ratio below RATIO_RANGE."""
        sides = []
        first = []

        def routes(payload):
            points = [(loc["lon"], loc["lat"]) for loc in payload["locations"]]
            side = run_plan.haversine(run_plan.Point(*points[0]), run_plan.Point(*points[1]))
            sides.append(side)
            km = 0.06 if not first else side * 3 * 1.4 / 1000.0
            first.append(1)
            shape = []
            for a, b in zip(points, points[1:], strict=False):
                shape.extend(line(a, b, 10)[1 if shape else 0 :])
            fake.traces[encode_polyline6(shape)] = edges(shape, "road", km)
            return answer(leg(shape, km * 370.0, km))

        fake = FakeCall(routes, {})
        run_plan.plan([START], run_plan.RunAsk(loop=True, target_m=5000.0), router(fake))
        assert max(sides) <= 5000.0 / (3.0 * run_plan.RATIO_RANGE[0]) + 1.0

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


# --- Closures on a run ---------------------------------------------------------------------------

# Far enough from every hand-read closure in force that only these tests' own are near.
EAST_A = (-76.96, 38.98)
EAST_B = (-76.94, 38.98)
MARKED = [[-76.95, 38.975], [-76.95, 38.977]]


@pytest.fixture
def fresh_zones():
    from core import workzones

    workzones.forget()
    yield
    workzones.forget()


def store_zones(zones) -> None:
    from core import workzones
    from core.models import BikeshareFeedCache

    BikeshareFeedCache.objects.create(
        key=workzones.KEY,
        payload={"feeds": {"md": {"read_at": datetime.now(UTC).isoformat(),
                                  "zones": [z.to_json() for z in zones]}}},
        fetched_at=datetime.now(UTC),
    )  # fmt: skip


def closed(zone_id, zone_line, on_foot) -> wz.Zone:
    until = datetime.now(UTC) + timedelta(days=30)
    return wz.Zone(zone_id, "md", wz.CLOSED, 0, tuple(zone_line), "Side Road", None, None, until,
                   on_foot=on_foot)  # fmt: skip


def run_router(monkeypatch, shape, refuse=lambda payload: False):
    """The router: every route is `shape`, or refused (no path) where `refuse(payload)`."""
    asked: list[tuple[str, dict]] = []
    trace = edges(shape, "footway", 2.0)

    def transport(url, payload, timeout):
        action = url.rsplit("/", 1)[1]
        asked.append((action, json.loads(json.dumps(payload))))
        if action == "route":
            if refuse(payload):
                raise routing.RouterRefused(400, 442, "No path could be found for input")
            return answer(leg(shape, 1200.0, 2.0))
        if action == "trace_attributes":
            return trace
        return []

    monkeypatch.setattr(routing, "_transport", transport)
    return asked


@db
@pytest.mark.usefixtures("fresh_zones")
class TestClosuresOnARun:
    def test_a_run_goes_round_a_closure_shut_on_foot_and_the_road_the_runner_marked(
        self, client, monkeypatch
    ) -> None:
        north = [(-76.955, 38.985), (-76.945, 38.985)]
        along = [(-76.955, 38.98), (-76.945, 38.98)]
        store_zones([closed("md-shut", north, True), closed("md-unsaid", along, None)])
        asked = run_router(monkeypatch, line(EAST_A, EAST_B))
        response = post(
            client,
            {"points": [list(EAST_A), list(EAST_B)], "preset": "run", "blocked_lines": [MARKED]},
        )
        assert response.status_code == 200, response.content
        rings = next(p for a, p in asked if a == "route")["exclude_polygons"]
        assert rings == [wz.polygon(closed("md-shut", north, True)), wz.line_ring(MARKED)]
        # The closure whose source does not say it shuts the way on foot is run along, warned.
        zones = response.json()["work_zones"]
        [on_route] = zones["on_route"]
        assert on_route["id"] == "md-unsaid" and on_route["warning"] is True
        row = next(r for r in zones["closures"] if r["id"] == "md-unsaid")
        assert "people on foot" in row["effect_text"]

    def test_a_long_loop_from_a_start_alone_goes_round_a_closure_far_from_the_start(
        self, client, monkeypatch
    ) -> None:
        """Audit 2026-11-05: a 30 km loop's corners lie about 8 km out, past the closures' own
        5 km margin round the start; a trail shut on foot up there is still left out."""
        # About 11 km north of EAST_A.
        far = [(-76.965, 39.08), (-76.955, 39.08)]
        store_zones([closed("md-far", far, True)])
        asked = run_router(monkeypatch, line(EAST_A, EAST_B))
        response = post(
            client,
            {
                "points": [list(EAST_A)],
                "preset": "run",
                "loop": True,
                "target_distance_m": 30_000,
            },
        )
        assert response.status_code == 200, response.content
        rings = next(p for a, p in asked if a == "route").get("exclude_polygons")
        assert rings == [wz.polygon(closed("md-far", far, True))]

    def test_with_no_way_round_a_closure_the_run_goes_through_it_warned(
        self, client, monkeypatch
    ) -> None:
        along = [(-76.955, 38.98), (-76.945, 38.98)]
        store_zones([closed("md-shut", along, True)])
        asked = run_router(
            monkeypatch,
            line(EAST_A, EAST_B),
            refuse=lambda payload: len(payload.get("exclude_polygons") or []) > 1,
        )
        response = post(
            client,
            {"points": [list(EAST_A), list(EAST_B)], "preset": "run", "blocked_lines": [MARKED]},
        )
        assert response.status_code == 200, response.content
        routes = [p for a, p in asked if a == "route"]
        assert len(routes[0]["exclude_polygons"]) == 2
        # Asked again with only the runner's own marked road left out.
        assert routes[-1]["exclude_polygons"] == [wz.line_ring(MARKED)]
        [on_route] = response.json()["work_zones"]["on_route"]
        assert on_route["id"] == "md-shut" and on_route["warning"] is True

    def test_a_night_run_in_rock_creek_is_told_of_the_deer_closure_never_sent_round_it(
        self, client, monkeypatch
    ) -> None:
        """The owner, 2026-11-04: the deer closures are "a may close, not a will close": a run
        gets the bike route's notice, and is never routed round them."""
        from core import workzones
        from routemaker import deer_closures as deer
        from routemaker import ridetime

        # In the posted 2025-26 season.
        night = datetime(2026, 1, 15, 20, 0, tzinfo=EASTERN).astimezone(UTC)
        monkeypatch.setattr(workzones, "_now", lambda: night)
        beach = list(max(deer.ways()["rocr-deer"].lines, key=len))
        store_zones([])
        asked = run_router(monkeypatch, beach)
        response = post(
            client,
            {
                "points": [list(beach[0]), list(beach[-1])],
                "preset": "run",
                "when": ridetime.when_at(night),
            },
        )
        assert response.status_code == 200, response.content
        [notice] = response.json()["work_zones"]["notices"]
        assert notice["area_name"] == "Rock Creek Park"
        lons = [p[0] for p in beach]
        lats = [p[1] for p in beach]
        for _action, payload in asked:
            for ring in payload.get("exclude_polygons") or []:
                assert not any(
                    min(lons) <= lon <= max(lons) and min(lats) <= lat <= max(lats)
                    for lon, lat in ring
                ), "a deer closure is never routed round"
