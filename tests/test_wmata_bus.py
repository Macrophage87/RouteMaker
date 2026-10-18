"""Metrobus live (core.wmata_bus) and where the next train or bus is (core.wmata_trains,
core.transit_live; v0.9.0), against saved API answers shaped as WMATA documents them
(tests/data/wmata). No network: the key, the fetch and the budget are fakes."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from test_route_api import router, segments, standard_router
from test_transit import (
    LINCOLN_PARK,
    UNION_STATION,
    at,
    db,
    installed,
    plan_bike,
    post_transit,
    schedule,
    stop_named,
    transit_legs,
)
from test_wmata_live import snapshot

from core import transit, transit_live, wmata_bus, wmata_live, wmata_trains

FIXTURES = (router, segments, installed, schedule)
DATA = Path(__file__).parent / "data" / "wmata"
STANTON_PARK = (-76.9993, 38.8935)
BUS_BAY = (-77.007, 38.8972)
LINCOLN_STOP = (-76.9895, 38.8897)


def doc(name: str) -> dict:
    return json.loads((DATA / name).read_text())


class Clock:
    def __init__(self) -> None:
        self.now = 1_790_000_000.0

    def __call__(self) -> float:
        return self.now


class FakeWmata:
    """WMATA's bus answers by path; `fail` makes every call fail, `slow` makes it wait."""

    FILES = {
        "/Bus.svc/json/jStops": "bus-stops.json",
        "/NextBusService.svc/json/jPredictions": "bus-predictions.json",
        "/Bus.svc/json/jBusPositions": "bus-positions.json",
        "/TrainPositions/TrainPositions": "train-positions.json",
        "/TrainPositions/StandardRoutes": "standard-routes.json",
    }

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.fail = False
        self.slow = 0.0

    def __call__(self, url: str, _timeout: float) -> bytes:
        from urllib.parse import urlsplit

        self.urls.append(url)
        if self.slow:
            time.sleep(self.slow)
        if self.fail:
            raise wmata_live.Unavailable("down")
        return (DATA / self.FILES[urlsplit(url).path]).read_bytes()

    def asked(self, path: str) -> int:
        return sum(1 for u in self.urls if path in u)


def buses(fetch=None, clock=None, budget=None, enabled=True) -> wmata_bus.Buses:
    return wmata_bus.Buses(
        fetch=fetch or FakeWmata(),
        budget=budget or wmata_live.LocalBudget(per_min=1000, per_s=1000),
        wall=clock or Clock(),
        enabled=lambda: enabled,
    )


# --- Matching the route and the way ---------------------------------------------------------


def test_the_next_buses_are_the_steps_route_its_way_variants_included() -> None:
    predictions = wmata_bus.parse_predictions(doc("bus-predictions.json"))
    # Lincoln Park to Stanton Park is west: the eastbound B10 and route 90 are left out, and
    # WMATA's variant "B10v1" is the timetable's B10.
    found = wmata_bus.coming(predictions, "B10", LINCOLN_STOP, STANTON_PARK)
    assert [(p.route, p.minutes, p.vehicle) for p in found] == [
        ("B10", 4, "7203"),
        ("B10v1", 13, "7210"),
        ("B10", 27, "7211"),
    ]
    # The other way round: east.
    back = wmata_bus.coming(predictions, "B10", STANTON_PARK, LINCOLN_STOP)
    assert [p.minutes for p in back] == [2]
    # A route the stop does not see: nothing.
    assert wmata_bus.coming(predictions, "X2", LINCOLN_STOP, STANTON_PARK) == []


def test_a_stop_one_way_needs_no_compass_and_two_ways_without_one_match_nothing() -> None:
    one_way = [wmata_bus.Prediction("52", "0", "Loop", 5, "1")]
    assert [p.minutes for p in wmata_bus.coming(one_way, "52", (0, 0), (0, 0.01))] == [5]
    both = [*one_way, wmata_bus.Prediction("52", "1", "Clockwise", 7, "2")]
    assert wmata_bus.coming(both, "52", (0, 0), (0, 0.01)) == []
    # A heading across both ways (due north, between East and West words) matches neither.
    across = [
        wmata_bus.Prediction("52", "0", "East to A", 5, "1"),
        wmata_bus.Prediction("52", "1", "West to B", 7, "2"),
    ]
    assert wmata_bus.coming(across, "52", (0, 0), (0, 0.01)) == []


def test_a_stop_that_sees_the_route_one_way_only_the_wrong_way_matches_nothing() -> None:
    """The nearest stop serving the route can be the one across the street (review #2)."""
    south = [wmata_bus.Prediction("52", "1", "South to L'Enfant Plaza", 4, "7")]
    assert wmata_bus.coming(south, "52", (0, 0), (0, 0.01)) == []  # the step goes north
    assert [p.minutes for p in wmata_bus.coming(south, "52", (0, 0.01), (0, 0))] == [4]
    # Unknown compass words, or no alighting point: taken as before.
    assert wmata_bus.coming(south, "52", (0, 0), None) == south


def test_the_boarding_stop_is_the_nearest_wmata_stop_the_route_serves() -> None:
    stops = wmata_bus.parse_stops(doc("bus-stops.json"))
    assert wmata_bus.stop_for(stops, LINCOLN_STOP, "B10").stop_id == "1001195"
    # 1001196 is nearer the corner for route 92, and the only one serving it.
    assert wmata_bus.stop_for(stops, (-76.9892, 38.8899), "92").stop_id == "1001196"
    # Farther than STOP_NEAR_M from any stop serving the route: none.
    assert wmata_bus.stop_for(stops, (-76.9700, 38.8897), "B10") is None


def test_the_live_line_reads_as_a_metro_steps_does() -> None:
    predictions = wmata_bus.parse_predictions(doc("bus-predictions.json"))
    found = wmata_bus.coming(predictions, "B10", LINCOLN_STOP, STANTON_PARK)
    assert wmata_bus.live_words("B10", found) == {
        "text": "Live: bus B10 in 4 min, 13 min.",
        "minutes": [4, 13],
        "source": "live",
    }
    arriving = [wmata_bus.Prediction("52", "0", "North", 0, None)]
    assert wmata_bus.live_words("52", arriving)["text"] == "Live: bus 52 arriving."
    assert wmata_bus.live_words("52", []) is None


def test_garbage_is_left_out_not_fatal() -> None:
    assert wmata_bus.parse_predictions({"Predictions": [{"RouteID": "52"}, None, 3]}) == ()
    assert wmata_bus.parse_stops({"Stops": [{"StopID": "1", "Lat": "x"}]}) == ()
    assert wmata_bus.parse_positions([]) == ()


# --- The cache, the budget and the fallbacks ------------------------------------------------


def test_each_stops_answer_is_kept_40_seconds_and_its_place_a_day() -> None:
    fetch, clock = FakeWmata(), Clock()
    client = buses(fetch, clock)
    first = client.step_live("B10", LINCOLN_STOP, STANTON_PARK)
    assert first[0]["text"] == "Live: bus B10 in 4 min, 13 min."
    client.step_live("B10", LINCOLN_STOP, STANTON_PARK)
    assert (fetch.asked("jStops"), fetch.asked("jPredictions")) == (1, 1)
    clock.now += wmata_bus.PREDICTIONS_TTL_S + 1
    client.step_live("B10", LINCOLN_STOP, STANTON_PARK)
    assert (fetch.asked("jStops"), fetch.asked("jPredictions")) == (1, 2)
    # The stop is asked for by WMATA's StopID; the key is never in a URL.
    assert all("StopID=1001195" in u for u in fetch.urls if "jPredictions" in u)
    assert all(wmata_live._allowed(u) for u in fetch.urls)


def test_with_no_key_nothing_is_fetched_and_nothing_is_live() -> None:
    fetch = FakeWmata()
    client = buses(fetch, enabled=False)
    assert client.lives([(1, "B10", LINCOLN_STOP, STANTON_PARK)]).steps == {}
    assert client.where("B10", LINCOLN_STOP, STANTON_PARK) is None
    assert fetch.urls == []


def test_wmata_down_adds_nothing_and_is_not_asked_again_at_once() -> None:
    fetch, clock = FakeWmata(), Clock()
    fetch.fail = True
    client = buses(fetch, clock)
    assert client.lives([(1, "B10", LINCOLN_STOP, STANTON_PARK)]) == wmata_bus.StepLives({}, None)
    tried = len(fetch.urls)
    assert client.lives([(1, "B10", LINCOLN_STOP, STANTON_PARK)]).steps == {}
    assert len(fetch.urls) == tried
    clock.now += wmata_bus.FAILED_TTL_S + 1
    fetch.fail = False
    assert client.lives([(1, "B10", LINCOLN_STOP, STANTON_PARK)]).steps[1]["minutes"] == [4, 13]


def test_a_slow_wmata_never_holds_a_plan_past_its_budget(monkeypatch) -> None:
    monkeypatch.setattr(wmata_bus, "PLAN_BUDGET_S", 0.2)
    fetch = FakeWmata()
    fetch.slow = 1.0
    started = time.monotonic()
    assert buses(fetch).lives([(1, "B10", LINCOLN_STOP, STANTON_PARK)]).steps == {}
    assert time.monotonic() - started < 0.8


def test_at_most_four_stops_are_asked_for_a_plan() -> None:
    fetch = FakeWmata()
    legs = [(i, "B10", LINCOLN_STOP, STANTON_PARK) for i in range(7)]
    got = buses(fetch).lives(legs)
    assert sorted(got.steps) == [0, 1, 2, 3]


def test_the_budget_counts_calls_a_minute_and_a_second() -> None:
    clock = Clock()
    clock.now = 60_000.0
    budget = wmata_live.LocalBudget(per_min=3, per_s=2, wall=clock)
    assert [budget.take(), budget.take(), budget.take()] == [True, True, False]  # 2 a second
    clock.now += 1
    assert [budget.take(), budget.take()] == [True, False]  # 3 a minute
    clock.now += 60
    assert budget.take()
    # Over it, the call is not made and the step shows nothing live.
    fetch = FakeWmata()
    refused = wmata_live.LocalBudget(per_min=0, per_s=0)
    assert buses(fetch, budget=refused).lives([(1, "B10", LINCOLN_STOP, STANTON_PARK)]).steps == {}
    assert fetch.urls == []


def test_the_whole_day_stays_under_wmatas_50000_calls_and_10_a_second() -> None:
    day = 24 * 3600
    metro = 3 * day / wmata_live.CACHE_TTL_S
    trains = day / wmata_trains.CACHE_TTL_S + 1
    bus = wmata_live.BUS_CALLS_PER_MIN * 24 * 60
    assert metro + trains + bus < 50_000
    assert 3 + 2 + wmata_live.BUS_CALLS_PER_S <= 10


@db
def test_the_shared_budget_counts_for_every_worker_in_one_row() -> None:
    from core.models import BikeshareFeedCache

    clock = Clock()
    one = wmata_live.SharedBudget(per_min=2, per_s=5, wall=clock)
    other = wmata_live.SharedBudget(per_min=2, per_s=5, wall=clock)
    assert [one.take(), other.take(), one.take()] == [True, True, False]
    assert BikeshareFeedCache.objects.filter(key=wmata_live.BUDGET_ROW_KEY).count() == 1


def test_a_query_may_name_a_stop_but_never_a_key() -> None:
    assert wmata_live._allowed(f"{wmata_bus.PREDICTIONS_URL}?StopID=1001195")
    assert not wmata_live._allowed(f"{wmata_bus.PREDICTIONS_URL}?StopID=1&api_key=x")
    assert not wmata_live._allowed("https://example.com/NextBusService.svc/json/jPredictions")


def test_the_key_goes_in_the_header_with_the_stop_in_the_query(monkeypatch, settings) -> None:
    secret = "k-test-0000"
    settings.WMATA_API_KEY = secret
    seen = {}

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _n):
            return b"{}"

    def opened(request, timeout):
        seen["url"] = request.full_url
        seen["key"] = request.get_header(wmata_live.KEY_HEADER.capitalize())
        return Answer()

    monkeypatch.setattr(wmata_live._OPENER, "open", opened)
    url = f"{wmata_bus.PREDICTIONS_URL}?StopID=1001195"
    assert wmata_live.http_get(url, 1.0) == b"{}"
    assert seen == {"url": url, "key": secret}
    assert secret not in seen["url"]


# --- On a plan ------------------------------------------------------------------------------


def bus_option(plan: transit.Plan, metro_too: bool = False) -> transit.Option:
    def systems(o):
        return [leg.system for leg in transit_legs(o)]

    want = ["Metrobus", "Metro"] if metro_too else ["Metrobus"]
    return next(o for o in plan.options if systems(o) == want)


def test_a_bus_step_says_its_next_buses_live_and_its_own_time_stays_scheduled(schedule) -> None:
    plan = plan_bike(schedule, LINCOLN_PARK, UNION_STATION, at(2026, 9, 30, 8, 0))
    chosen = transit.choose(plan, bus_option(plan).key)
    legs = transit_live.bus_legs(chosen)
    assert [(route, board) for _i, route, board, _a in legs] == [("B10", LINCOLN_STOP)]
    lives = buses().lives(legs)
    block = transit_live.annotate(transit.block(chosen, schedule), chosen, None, lives)
    step = next(s for s in block["steps"] if s["mode"] == "bus")
    assert step["live"] == {
        "text": "Live: bus B10 in 4 min, 13 min.",
        "minutes": [4, 13],
        "source": "live",
    }
    assert step["source"] == "scheduled"
    assert block["live"]["credit"] == "Data: WMATA"
    assert block["live"]["warnings"] == [] and block["live"]["alerts"] == []
    assert block["live"]["as_of"].startswith("2026-")


def test_a_bus_then_metro_trip_says_both_live(schedule) -> None:
    plan = plan_bike(schedule, LINCOLN_PARK, UNION_STATION, at(2026, 9, 30, 8, 0))
    chosen = transit.choose(plan, bus_option(plan, metro_too=True).key)
    lives = buses().lives(transit_live.bus_legs(chosen))
    block = transit_live.annotate(transit.block(chosen, schedule), chosen, snapshot(), lives)
    said = {s["mode"]: s["live"] for s in block["steps"] if s["mode"] in ("bus", "metro")}
    assert said["bus"]["text"].startswith("Live: bus B10 in ")


def test_with_no_bus_reading_the_step_is_the_timetables_alone(schedule) -> None:
    plan = plan_bike(schedule, LINCOLN_PARK, UNION_STATION, at(2026, 9, 30, 8, 0))
    chosen = transit.choose(plan, bus_option(plan).key)
    empty = wmata_bus.StepLives({}, None)
    block = transit_live.annotate(transit.block(chosen, schedule), chosen, None, empty)
    assert block["live"] is None and all(s["live"] is None for s in block["steps"])


# --- Where the next bus is ------------------------------------------------------------------


def test_where_the_next_bus_is_by_its_vehicle_and_the_stops_back(schedule) -> None:
    client = buses()
    found = client.where("B10", LINCOLN_STOP, STANTON_PARK)
    # The next bus west is 7203 (not the eastbound 7100), about half a mile east of the stop.
    assert found["point"] == [-76.9802, 38.8892]
    assert found["text"] == "Bus B10 is 0.5 mi away (0.8 km)."
    assert found["away"] is None
    # From Stanton Park, a bus at Lincoln Park is one stop back on the timetable's pattern.
    back = transit_live.bus_stops_back(schedule, "B10", STANTON_PARK, BUS_BAY)
    assert back((-76.9894, 38.8898)) == 1
    assert back(STANTON_PARK) == 0
    assert back((-76.95, 38.80)) is None
    # The wrong way (the pattern does not run Stanton Park to Lincoln Park): not known.
    assert transit_live.bus_stops_back(schedule, "B10", STANTON_PARK, LINCOLN_STOP) is None
    assert stop_named(schedule, "Stanton Park").system == next(
        s.index for s in schedule.systems if s.name == "Metrobus"
    )


def test_the_bus_words_us_units_first() -> None:
    assert wmata_bus.where_words("52", 1300, 3) == "Bus 52 is 0.8 mi away (1.3 km), 3 stops back."
    assert wmata_bus.where_words("52", 1300, 1) == "Bus 52 is 0.8 mi away (1.3 km), 1 stop back."
    assert wmata_bus.where_words("52", 120, None) == "Bus 52 is 400 ft away (120 m)."
    assert wmata_bus.where_words("52", 20, 0) == "Bus 52 is at your stop."


def test_no_bus_position_no_answer() -> None:
    class NoPositions(FakeWmata):
        def __call__(self, url, timeout):
            if "jBusPositions" in url:
                return b'{"BusPositions": []}'
            return super().__call__(url, timeout)

    assert buses(NoPositions()).where("B10", LINCOLN_STOP, STANTON_PARK) is None


# --- Where the next train is ----------------------------------------------------------------


def board() -> wmata_trains.Board:
    return wmata_trains.build(
        {"routes": doc("standard-routes.json"), "positions": doc("train-positions.json")},
        1_790_000_000.0,
    )


def test_the_standard_routes_and_positions_are_read_as_wmata_documents_them() -> None:
    found = board()
    assert set(found.routes) == {("RD", 1), ("RD", 2), ("OR", 1)}
    assert found.routes[("RD", 1)][0] == wmata_trains.Circuit(1001, "A15")
    assert found.routes[("RD", 1)][1] == wmata_trains.Circuit(1002, None)
    # The train not in service is left out.
    assert {t.train for t in found.trains} == {"100", "101", "102", "103", "104", "106"}


def test_the_next_train_is_the_nearest_behind_on_the_track_the_step_goes() -> None:
    found = board()
    # Union Station toward Glenmont (track 1): 100 between Metro Center and Gallery Place, not
    # 101 (farther back), 102 (past it) or the westbound trains.
    east = wmata_trains.next_train(found, "Red Line", {"B03"}, {"B11"})
    assert east == wmata_trains.Approach("Red Line", None, "A01", "B01", 3)
    # Judiciary Square toward Metro Center (track 2): 103, between Union Station and it.
    west = wmata_trains.next_train(found, "Red Line", {"B02"}, {"A01", "C01"})
    assert west == wmata_trains.Approach("Red Line", None, "B03", "B02", 1)
    # Metro Center toward Shady Grove: 104, at Gallery Place, one station away.
    at_station = wmata_trains.next_train(found, "Red Line", {"A01", "C01"}, {"A15"})
    assert at_station == wmata_trains.Approach("Red Line", "B01", None, None, 1)
    # A train at the boarding station itself: zero away.
    here = wmata_trains.next_train(found, "Red Line", {"B01"}, {"A15"})
    assert here.away == 0 and here.at == "B01"
    # A line with no track between the two, or none named: none.
    assert wmata_trains.next_train(found, "Green Line", {"B01"}, {"A15"}) is None
    assert wmata_trains.next_train(found, "Orange Line", {"D06"}, {"K08"}) is None


def test_the_train_is_said_by_its_stations_and_marked_between_them() -> None:
    live = snapshot()
    east = wmata_trains.Approach("Red Line", None, "A01", "B01", 3)
    text, point = wmata_trains.words(east, live)
    assert (
        text
        == "Next Red Line train is between Metro Center and Gallery Pl-Chinatown, 3 stations away."
    )
    assert point == [pytest.approx(-77.024975), pytest.approx(38.8983215)]
    at_station = wmata_trains.Approach("Red Line", "B01", None, None, 1)
    assert wmata_trains.words(at_station, live) == (
        "Next Red Line train is at Gallery Pl-Chinatown, 1 station away.",
        [-77.021851, 38.89834],
    )
    now = wmata_trains.Approach("Red Line", "B03", None, None, 0)
    assert wmata_trains.words(now, live)[0] == "Next Red Line train is at Union Station now."


def test_train_where_from_the_steps_points(schedule) -> None:
    found = transit_live.train_where(
        snapshot(), UNION_STATION, (-77.05341, 39.061713), "Red Line", board()
    )
    assert found["text"].startswith("Next Red Line train is between Metro Center and Gallery")
    assert found["away"] == 3
    assert transit_live.train_where(None, UNION_STATION, UNION_STATION, "Red Line", board()) is None
    assert (
        transit_live.train_where(snapshot(), UNION_STATION, UNION_STATION, "Red Line", None) is None
    )
    out = transit_live.vehicle_out("train", found)
    assert out["credit"] == "Data: WMATA" and out["source"] == "live"
    assert out["label"].startswith("Next Red Line train is between")


def test_train_positions_are_kept_20_seconds_and_never_served_stale() -> None:
    fetch, clock = FakeWmata(), Clock()
    live = wmata_live.Live(
        fetch=fetch,
        wall=clock,
        enabled=lambda: True,
        urls={"positions": wmata_trains.POSITIONS_URL},
        daily={"routes": wmata_trains.ROUTES_URL},
        builder=wmata_trains.build,
        ttl=wmata_trains.CACHE_TTL_S,
        grace=0.0,
    )
    assert live.snapshot() is not None
    assert (fetch.asked("TrainPositions?"), fetch.asked("StandardRoutes")) == (1, 1)
    clock.now += 10
    assert live.snapshot() is not None and fetch.asked("TrainPositions?") == 1
    clock.now += 11
    assert live.snapshot() is not None
    # Positions again; the standard routes are kept a day.
    assert (fetch.asked("TrainPositions?"), fetch.asked("StandardRoutes")) == (2, 1)
    clock.now += wmata_trains.CACHE_TTL_S + 1
    fetch.fail = True
    assert live.snapshot() is None


# --- Through the API ------------------------------------------------------------------------


@db
@pytest.mark.usefixtures("weekday_clock")
class TestApi:
    def ask(self, client, **params):
        return client.get("/api/transit/next-vehicle", params)

    def test_with_no_key_there_is_no_vehicle(self, client, installed) -> None:
        lon, lat = UNION_STATION
        response = self.ask(
            client, system="Metro", line="Red Line", lon=lon, lat=lat, to_lon=-77.05, to_lat=39.06
        )
        assert response.status_code == 200, response.content
        assert response.json() == {"vehicle": None}

    def test_the_next_train_and_bus_through_the_api(
        self, client, installed, monkeypatch, settings
    ) -> None:
        settings.WMATA_API_KEY = "k-test"
        monkeypatch.setattr(wmata_live.client, "snapshot", snapshot)
        monkeypatch.setattr(wmata_trains.client, "snapshot", board)
        monkeypatch.setattr(wmata_bus, "client", buses())
        lon, lat = UNION_STATION
        train = self.ask(
            client, system="Metro", line="Red Line", lon=lon, lat=lat, to_lon=-77.05, to_lat=39.06
        ).json()["vehicle"]
        assert train["kind"] == "train" and train["away"] == 3
        assert train["text"].startswith("Next Red Line train is between Metro Center")
        assert train["credit"] == "Data: WMATA" and len(train["point"]) == 2
        bus = self.ask(
            client,
            system="Metrobus",
            line="B10",
            lon=STANTON_PARK[0],
            lat=STANTON_PARK[1],
            to_lon=BUS_BAY[0],
            to_lat=BUS_BAY[1],
        )
        assert bus.status_code == 200, bus.content
        assert bus["Cache-Control"] == "private, max-age=15"
        # The fixture's stops are around Lincoln Park only: none at Stanton Park, so nothing.
        assert bus.json() == {"vehicle": None}
        from_lincoln = self.ask(
            client,
            system="Metrobus",
            line="B10",
            lon=LINCOLN_STOP[0],
            lat=LINCOLN_STOP[1],
            to_lon=STANTON_PARK[0],
            to_lat=STANTON_PARK[1],
        ).json()["vehicle"]
        assert from_lincoln["kind"] == "bus"
        assert from_lincoln["text"] == "Bus B10 is 0.5 mi away (0.8 km)."
        assert self.ask(
            client, system="MARC", line="Penn", lon=0, lat=0, to_lon=0, to_lat=0
        ).status_code in (
            400,
            422,
        )

    def test_a_plan_says_a_bus_steps_next_buses_live(
        self, client, segments, router, installed, monkeypatch, settings
    ) -> None:
        settings.WMATA_API_KEY = "k-test"
        monkeypatch.setattr(wmata_live.client, "snapshot", lambda: None)
        monkeypatch.setattr(wmata_bus, "client", buses())
        router(standard_router())
        first = post_transit(client, [LINCOLN_PARK, UNION_STATION]).json()["transit"]
        option = next(
            o
            for o in first["options"]
            if [leg["mode"] for leg in o["legs"]].count("bus") == 1
            and "metro" not in [leg["mode"] for leg in o["legs"]]
        )
        trip = post_transit(client, [LINCOLN_PARK, UNION_STATION], transit_option=option["key"])
        assert trip.status_code == 200, trip.content
        block = trip.json()["transit"]
        step = next(s for s in block["steps"] if s["mode"] == "bus")
        assert step["live"]["text"] == "Live: bus B10 in 4 min, 13 min."
        assert block["live"]["credit"] == "Data: WMATA"
