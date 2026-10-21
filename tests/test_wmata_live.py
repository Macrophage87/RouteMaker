"""WMATA's live data (core.wmata_live) and how the plans and station cards say it
(core.transit_live), against saved API answers shaped as WMATA documents them
(tests/data/wmata). No network: the key and the fetch are fakes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_route_api import router, segments, standard_router
from test_transit import (
    CAPITOL_HILL,
    DOWNTOWN,
    UNION_STATION,
    at,
    db,
    installed,
    plan_bike,
    post_transit,
    schedule,
    transit_legs,
)

from core import presets, transit, transit_live, wmata_live

FIXTURES = (router, segments, installed, schedule)
DATA = Path(__file__).parent / "data" / "wmata"
URLS = {
    wmata_live.STATIONS_URL: "stations.json",
    wmata_live.PREDICTIONS_URL: "predictions.json",
    wmata_live.INCIDENTS_URL: "incidents.json",
    wmata_live.ELEVATORS_URL: "elevators.json",
}


def docs() -> dict:
    return {
        "stations": json.loads((DATA / "stations.json").read_text()),
        "predictions": json.loads((DATA / "predictions.json").read_text()),
        "incidents": json.loads((DATA / "incidents.json").read_text()),
        "elevators": json.loads((DATA / "elevators.json").read_text()),
    }


def snapshot() -> wmata_live.Snapshot:
    return wmata_live.build(docs(), 1_790_000_000.0)


class Clock:
    def __init__(self) -> None:
        self.now = 1_790_000_000.0

    def __call__(self) -> float:
        return self.now


class FakeWmata:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.fail = False

    def __call__(self, url: str, _timeout: float) -> bytes:
        self.urls.append(url)
        if self.fail:
            raise wmata_live.Unavailable("down")
        return (DATA / URLS[url]).read_bytes()


# --- Parsing ------------------------------------------------------------------------------


def test_the_answers_are_read_as_wmata_documents_them() -> None:
    live = snapshot()
    union = live.station_near(UNION_STATION)
    assert union is not None and union.name == "Union Station" and union.lines == ("Red Line",)
    # A train not in service ("--", no minutes) is not a train a rider can take.
    trains = live.trains_at(union)
    assert [(t.line, t.destination, wmata_live.train_minutes(t)) for t in trains] == [
        ("Red Line", "Shady Grove", "arriving"),
        ("Red Line", "Shady Grove", "9 min"),
        ("Red Line", "Glenmont", "boarding"),
    ]
    # Metro Center is two codes, one station: both platforms' trains and lines.
    center = live.station_near([-77.0281, 38.8983])
    assert set(live.codes(center)) == {"A01", "C01"}
    assert live.lines_at(center) == ["Red Line", "Blue Line", "Orange Line", "Silver Line"]
    # An escalator out is not an elevator out.
    assert live.elevators_out(union) == []
    triangle = live.station_near([-77.0282, 38.8937])
    assert [o.where for o in live.elevators_out(triangle)] == [
        "Elevator between street and mezzanine"
    ]
    assert [i.kind for i in live.incidents_on(["Orange Line"])] == ["Delay"]
    assert live.station_near([-77.5, 38.5]) is None


def test_a_line_is_the_same_line_by_its_colour() -> None:
    assert wmata_live.same_line("Red Line", "RED")
    assert wmata_live.same_line("Metrorail Orange Line", "Orange Line")
    assert not wmata_live.same_line("Red Line", "Orange Line")
    assert not wmata_live.same_line("Penn Line", "Red Line")


def test_garbage_is_left_out_not_fatal() -> None:
    assert wmata_live.parse_stations({"Stations": [{"Code": "X"}, "no", {"Lat": "x"}]}) == {}
    assert wmata_live.parse_trains({"Trains": [{"Min": "5"}, None]}) == ()
    assert wmata_live.parse_incidents([]) == ()
    with pytest.raises(wmata_live.Unavailable):
        wmata_live.build({"stations": {}}, 0.0)


# --- The shared reading ---------------------------------------------------------------------


def test_with_no_key_nothing_is_fetched_and_nothing_is_live() -> None:
    fetch = FakeWmata()
    live = wmata_live.Live(fetch=fetch, enabled=lambda: False)
    assert live.snapshot() is None and fetch.urls == []


def test_one_reading_serves_45_seconds_and_the_station_list_a_day() -> None:
    fetch, clock = FakeWmata(), Clock()
    live = wmata_live.Live(fetch=fetch, wall=clock, enabled=lambda: True)
    first = live.snapshot()
    assert first is not None and not first.stale
    assert sorted(fetch.urls) == sorted(URLS)
    clock.now += wmata_live.CACHE_TTL_S - 1
    assert live.snapshot() is not None and len(fetch.urls) == 4
    clock.now += 2
    assert live.snapshot() is not None
    # The second reading reads the live documents again, but not the station list.
    assert len(fetch.urls) == 7 and fetch.urls.count(wmata_live.STATIONS_URL) == 1
    clock.now += wmata_live.STATIONS_TTL_S
    live.snapshot()
    assert fetch.urls.count(wmata_live.STATIONS_URL) == 2
    # The key is never in a URL.
    assert not any("api_key" in url or "?" in url for url in fetch.urls)


def test_a_failed_reading_pauses_serves_the_last_for_a_while_then_nothing() -> None:
    fetch, clock = FakeWmata(), Clock()
    live = wmata_live.Live(fetch=fetch, wall=clock, enabled=lambda: True)
    assert live.snapshot() is not None
    fetch.fail = True
    clock.now += wmata_live.CACHE_TTL_S + 1
    late = live.snapshot()
    assert late is not None and late.stale
    tried = len(fetch.urls)
    clock.now += 1  # within the pause: not tried again
    assert live.snapshot() is not None and len(fetch.urls) == tried
    clock.now += wmata_live.STALE_GRACE_S
    assert live.snapshot() is None


def test_the_key_goes_in_wmatas_header_and_never_in_a_message(monkeypatch, settings) -> None:
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
    assert wmata_live.http_get(wmata_live.ELEVATORS_URL, 1.0) == b"{}"
    assert seen == {"url": wmata_live.ELEVATORS_URL, "key": secret}

    def down(request, timeout):
        raise OSError(f"failed {request.full_url}")

    monkeypatch.setattr(wmata_live._OPENER, "open", down)
    with pytest.raises(wmata_live.Unavailable) as refused:
        wmata_live.http_get(wmata_live.ELEVATORS_URL, 1.0)
    assert secret not in str(refused.value)
    with pytest.raises(wmata_live.Unavailable):
        wmata_live.http_get("https://example.com/x", 1.0)


# --- On a plan ------------------------------------------------------------------------------


def metro_option(plan: transit.Plan) -> transit.Option:
    return next(o for o in plan.options if transit_legs(o) and transit_legs(o)[0].system == "Metro")


def test_an_elevator_out_is_a_warning_and_a_15_min_ranking_cost_not_an_avoidance(schedule):
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    metro = metro_option(plan)
    assert transit_legs(metro)[0].to == "Federal Triangle"
    # Federal Triangle's one street elevator is out (the fixture): the station is blocked.
    blocked = transit_live.blocked_stations(snapshot())
    assert [s.name for s in blocked] == ["Federal Triangle"]
    marked = transit.with_elevators_out(schedule, [(s.lon, s.lat) for s in blocked])
    ranked = plan_bike(marked, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    # The same Orange Line trip rides on to the next station over (Stephen, 2026-10-21: "Most
    # cyclists would just ride from the next station over"): Federal Triangle costs 15 min.
    assert transit.ELEVATOR_OUT_S == 900.0
    lines = transit_legs(metro)[0].lines
    orange = next(
        o for o in ranked.options if len(transit_legs(o)) == 1 and transit_legs(o)[0].lines == lines
    )
    assert transit_legs(orange)[0].to == "Metro Center"
    assert not any(leg.elevator_out for leg in orange.legs)
    order = [transit.rank_key(o) for o in ranked.options]
    assert order == sorted(order)
    # A trip through Federal Triangle chosen all the same is planned, with the warning said.
    chosen = transit.choose(plan, metro.key)
    block = transit_live.annotate(transit.block(chosen, schedule), chosen, snapshot())
    assert block["live"]["warnings"] == [
        "Elevator out at Federal Triangle: carry your bike on the stairs."
    ]
    # The Orange Line's incident, not the Red Line's; the credit and the time of the reading.
    assert [a.split(":")[0] for a in block["live"]["alerts"]] == ["Orange Line"]
    assert block["live"]["credit"] == "Data: WMATA"
    step = next(s for s in block["steps"] if s["mode"] == "metro")
    # Toward Vienna (west, the trip's way), not New Carrollton; the Silver Line is not this step's.
    assert step["live"] == {
        "text": "Live: Orange Line toward Vienna/Fairfax-GMU in 3 min, 11 min.",
        "minutes": [3, 11],
        "source": "live",
    }
    # The step's own time is still the timetable's, and says so.
    assert step["source"] == "scheduled"


def test_with_no_reading_the_plan_is_the_timetables_alone(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    assert transit_live.blocked_stations(None) == []
    block = transit_live.annotate(transit.block(plan, schedule), plan, None)
    assert block["live"] is None and all(s["live"] is None for s in block["steps"])


def test_bikeshare_and_transit_warns_of_no_elevator(schedule) -> None:
    """On foot, an elevator out is no matter: the escalator or the stairs."""
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    walked = transit.Plan(
        presets.BIKESHARE_TRANSIT,
        [_on_foot(o) for o in plan.options],
        plan.moment,
        [],
    )
    assert all(transit_live._outage_stations(o, snapshot()) == [] for o in walked.options)
    chosen = transit.choose(walked, metro_option(walked).key)
    block = transit_live.annotate(transit.block(chosen, schedule), chosen, snapshot())
    assert block["live"]["warnings"] == []


def _on_foot(option: transit.Option) -> transit.Option:
    from dataclasses import replace

    return replace(option, legs=tuple(replace(leg, bike=False) for leg in option.legs))


# --- Through the API ------------------------------------------------------------------------


@db
@pytest.mark.usefixtures("weekday_clock")
class TestApi:
    def test_a_metro_stations_card_says_its_next_trains_live_with_wmatas_credit(
        self, client, installed, monkeypatch
    ) -> None:
        monkeypatch.setattr(wmata_live.client, "snapshot", snapshot)
        lon, lat = UNION_STATION
        response = client.get("/api/transit/station-times", {"lon": lon, "lat": lat})
        assert response.status_code == 200, response.content
        assert response["Cache-Control"] == "public, max-age=30"
        body = response.json()
        # The timetable's lines stay, as the fallback; the live values come beside them.
        assert body["source"] == "scheduled" and body["lines"]
        live = body["live"]
        assert live["station"] == "Union Station" and live["credit"] == "Data: WMATA"
        assert [(t["toward"], t["when"]) for t in live["trains"]] == [
            ("Glenmont", "boarding"),
            ("Shady Grove", "arriving, 9 min"),
        ]
        assert live["elevators"] == [] and [a[:8] for a in live["alerts"]] == ["Red Line"]
        # A time asked for is the timetable's alone.
        asked = client.get(
            "/api/transit/station-times", {"lon": lon, "lat": lat, "at": "2026-09-30T08:00:00"}
        ).json()
        assert asked["live"] is None

    def test_with_no_key_the_card_is_the_timetables(self, client, installed, settings):
        settings.WMATA_API_KEY = ""
        lon, lat = UNION_STATION
        body = client.get("/api/transit/station-times", {"lon": lon, "lat": lat}).json()
        assert body["live"] is None and body["source"] == "scheduled"

    def test_a_plan_says_the_elevator_out_and_the_next_trains_live(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        monkeypatch.setattr(wmata_live.client, "snapshot", snapshot)
        router(standard_router())
        first = post_transit(client, [CAPITOL_HILL, DOWNTOWN]).json()["transit"]
        metro = next(o for o in first["options"] if not o["direct"])
        trip = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=metro["key"])
        assert trip.status_code == 200, trip.content
        block = trip.json()["transit"]
        # Federal Triangle's only street elevator is out: the Orange Line trip rides on to the
        # next station over (Stephen, 2026-10-21), so there is nothing to warn of.
        step = next(s for s in block["steps"] if s["mode"] == "metro")
        assert step["to"] == "Metro Center" and not metro["elevator_out"]
        assert block["live"]["warnings"] == []
        assert step["live"]["text"].startswith("Live: Orange Line toward Vienna")


@db
def test_the_workers_share_one_row_replaced_in_place() -> None:
    from core.models import BikeshareFeedCache

    store = wmata_live.DatabaseStore()
    fetch, clock = FakeWmata(), Clock()
    first = wmata_live.Live(fetch=fetch, wall=clock, store=store, enabled=lambda: True)
    assert first.snapshot() is not None
    # Another worker borrows the reading rather than asking WMATA again.
    other = wmata_live.Live(fetch=fetch, wall=clock, store=store, enabled=lambda: True)
    assert other.snapshot() is not None and other.readings == 0
    clock.now += wmata_live.CACHE_TTL_S + 1
    assert other.snapshot() is not None and other.readings == 1
    assert BikeshareFeedCache.objects.filter(key=wmata_live.ROW_KEY).count() == 1


# --- Stations WMATA's incidents say are closed (the owner, 2026-10-18) ----------------------


def _with_incidents(*texts: str) -> wmata_live.Snapshot:
    from dataclasses import replace

    incidents = tuple(wmata_live.Incident(("Orange Line",), "Alert", t) for t in texts)
    return replace(snapshot(), incidents=incidents)


def test_a_sentence_that_says_closed_closes_the_stations_it_names() -> None:
    live = _with_incidents(
        "This weekend, free shuttles replace trains between Metro Center and Smithsonian due to"
        " planned work. As a result, Federal Triangle and Smithsonian stations are closed."
    )
    assert set(live.closed()) == {"D01", "D02"}
    # Metro Center is named, but only in the sentence about shuttles.
    assert "A01" not in live.closed()


def test_reopened_future_and_nameless_closures_close_nothing() -> None:
    live = _with_incidents(
        "Smithsonian station has reopened and is closed no longer.",
        "Federal Triangle will be closed starting Monday.",
        "Some entrances are closed.",
    )
    assert live.closed() == {}


def test_a_station_both_platforms_close_together() -> None:
    live = _with_incidents("Metro Center station is closed due to a fire department activity.")
    assert {"A01", "C01"} <= set(live.closed())


def replace_options(plan: transit.Plan, options: list) -> transit.Plan:
    from dataclasses import replace

    return replace(plan, options=options, chosen=0)


def test_own_bike_trips_through_a_closed_station_are_left_out(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    metro = metro_option(plan)
    live = _with_incidents("Smithsonian station is closed.")
    # The train passes Smithsonian on the way to Federal Triangle.
    assert transit_live.closed_on(metro, live) == ["Smithsonian"]
    kept = transit_live.skip_closed(plan, live)
    assert metro.key not in [o.key for o in kept.options]
    assert any(o.direct for o in kept.options)
    assert kept.notes[-1] == (
        "Smithsonian is closed (WMATA): trips taking a bike through it are left out."
    )
    # Nothing closed, or no reading: the plan as it was.
    assert transit_live.skip_closed(plan, snapshot()) is plan
    assert transit_live.skip_closed(plan, None) is plan
    # Every trip through it: they stay, and the note says so.
    through = replace_options(plan, [metro])
    left = transit_live.skip_closed(through, live)
    assert [o.key for o in left.options] == [metro.key]
    assert left.notes[-1] == (
        "Smithsonian is closed (WMATA): every trip here takes a bike through it."
    )


def test_bikeshare_and_transit_keeps_its_trips_through_a_closed_station(schedule) -> None:
    """On foot the rider can take the shuttle; the step's WMATA alert says so."""
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    walked = transit.Plan(
        presets.BIKESHARE_TRANSIT, [_on_foot(o) for o in plan.options], plan.moment, []
    )
    live = _with_incidents("Smithsonian station is closed.")
    assert transit_live.skip_closed(walked, live) is walked


@db
@pytest.mark.usefixtures("weekday_clock")
class TestClosedStationsApi:
    def test_the_map_strikes_through_a_station_wmata_says_is_closed(
        self, client, installed, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            wmata_live.client,
            "snapshot",
            lambda: _with_incidents("As a result, Smithsonian station is closed."),
        )
        response = client.get("/api/transit/closures")
        assert response.status_code == 200, response.content
        assert response["Cache-Control"] == "public, max-age=60"
        found = [s for s in response.json()["stations"] if s["name"] == "Smithsonian"]
        assert found == [
            {
                "name": "Smithsonian",
                "system": "Metro",
                "lon": found[0]["lon"],
                "lat": found[0]["lat"],
                "reason": "WMATA service alert",
            }
        ]
        # A day asked for is the timetable's alone.
        later = client.get("/api/transit/closures", {"at": "2026-09-30T12:00:00"}).json()
        assert all(s["name"] != "Smithsonian" for s in later["stations"])


# --- Badges on stations with an alert or an elevator out (the owner, 2026-10-18) -------------


def test_stations_an_incident_names_get_a_badge_and_line_wide_ones_none() -> None:
    live = snapshot()
    # "an earlier equipment problem at Eastern Market"; Takoma and Silver Spring are not in
    # the fixture.
    assert live.named() == {"D06"}
    assert _with_incidents("Orange Line: expect delays in both directions.").named() == set()
    # Elevators only, both platforms of a station.
    assert live.elevator_out_codes() == {"D01"}


def test_a_name_inside_a_longer_named_station_is_not_named_too() -> None:
    from dataclasses import replace

    base = snapshot()
    stations = {
        **base.stations,
        "C07": wmata_live.Station("C07", "Pentagon", -77.054, 38.869),
        "C08": wmata_live.Station("C08", "Pentagon City", -77.059, 38.863),
    }
    live = replace(base, stations=stations)
    words = "elevator work at pentagon city."
    assert [s.code for s in live._named_in(words)] == ["C08"]
    assert {s.code for s in live._named_in("pentagon and pentagon city.")} == {"C07", "C08"}


@db
@pytest.mark.usefixtures("weekday_clock")
class TestStationAlertsApi:
    def test_the_map_badges_alerts_and_elevators_out_but_not_closed_stations(
        self, client, installed, monkeypatch
    ) -> None:
        from dataclasses import replace

        live = replace(
            _with_incidents(
                "Delays due to an equipment problem at Eastern Market.",
                "Smithsonian station is closed.",
            ),
            outages=(
                wmata_live.Outage("D01", "Federal Triangle", "ELEVATOR", "Street", None),
                wmata_live.Outage("D02", "Smithsonian", "ELEVATOR", "Street", None),
                wmata_live.Outage("B03", "Union Station", "ESCALATOR", "Mezzanine", None),
            ),
        )
        monkeypatch.setattr(wmata_live.client, "snapshot", lambda: live)
        body = client.get("/api/transit/closures").json()
        alerts = {a["name"]: (a["alert"], a["elevator_out"]) for a in body["alerts"]}
        # Smithsonian is struck through instead; an escalator out is no badge.
        assert alerts == {"Eastern Market": (True, False), "Federal Triangle": (False, True)}
        # A day asked for, or no reading: no badges.
        later = client.get("/api/transit/closures", {"at": "2026-09-30T12:00:00"}).json()
        assert later["alerts"] == []
        monkeypatch.setattr(wmata_live.client, "snapshot", lambda: None)
        assert client.get("/api/transit/closures").json()["alerts"] == []


def test_a_stretch_a_trains_way_or_a_closed_entrance_closes_no_station() -> None:
    from dataclasses import replace

    base = snapshot()
    extra = {
        "C05": ("Rosslyn", -77.0716, 38.8962),
        "C06": ("Arlington Cemetery", -77.0632, 38.8846),
        "K01": ("Court House", -77.0855, 38.8907),
        "K04": ("Ballston-MU", -77.1112, 38.8820),
        "C04": ("Foggy Bottom-GWU", -77.0502, 38.9009),
        "A02": ("Farragut North", -77.0397, 38.9032),
    }
    stations = {**base.stations}
    for code, (name, lon, lat) in extra.items():
        stations[code] = wmata_live.Station(code, name, lon, lat)
    live = replace(base, stations=stations)

    def closed(text: str) -> set[str]:
        return set(
            replace(
                live, incidents=(wmata_live.Incident(("Orange Line",), "Alert", text),)
            ).closed()
        )

    assert (
        closed(
            "Trains single tracking between Rosslyn and Arlington Cemetery due to a track closure."
        )
        == set()
    )
    # The shuttle's ends stay open; the stations closed between them are closed.
    assert closed(
        "Shuttle buses replace trains between Ballston-MU and Foggy Bottom-GWU due to the"
        " closure of Rosslyn and Court House."
    ) == {"C05", "K01"}
    assert closed("The L Street entrance at Farragut North is closed.") == set()
    # A train's way names its end in passing: no badge.
    delays = replace(
        live,
        incidents=(
            wmata_live.Incident(
                ("Orange Line",), "Delay", "Trains to Vienna/Fairfax-GMU are delayed."
            ),
        ),
    )
    assert delays.named() == set()


def test_real_closures_worded_other_ways_still_close() -> None:
    from dataclasses import replace

    base = snapshot()
    stations = {**base.stations}
    for code, name in {
        "C05": "Rosslyn",
        "K01": "Court House",
        "K04": "Ballston-MU",
        "C04": "Foggy Bottom-GWU",
    }.items():
        stations[code] = wmata_live.Station(code, name, -77.07, 38.89)
    live = replace(base, stations=stations)

    def closed(text: str) -> set[str]:
        return set(
            replace(
                live, incidents=(wmata_live.Incident(("Orange Line",), "Alert", text),)
            ).closed()
        )

    assert closed("Rosslyn station closure due to a fire.") == {"C05"}
    assert closed("Closures at Rosslyn and Court House.") == {"C05", "K01"}
    assert closed(
        "Rosslyn station is closed due to a fire; shuttle buses board at the N Moore St entrance."
    ) == {"C05"}
    assert closed(
        "Rosslyn and Court House stations are closed until further notice; parking is free at"
        " Ballston-MU."
    ) == {"C05", "K01"}
    assert closed("Due to a fire, service to Rosslyn is suspended and the station is closed.") == {
        "C05"
    }
    assert closed("Stations are closed from Rosslyn to Ballston-MU.") == {"C05", "K04"}
    assert closed(
        "Single tracking between Ballston-MU and Foggy Bottom-GWU and Rosslyn is closed."
    ) == {"C05"}


# --- Live departures (v0.10.0) ---------------------------------------------------------------

EIGHT = at(2026, 9, 30, 8, 0)


def live_at(wall: float, **changes) -> wmata_live.Snapshot:
    from dataclasses import replace

    return replace(wmata_live.build(docs(), wall), **changes)


def test_a_plan_for_now_boards_the_next_train_wmata_predicts_that_the_rider_can_reach(schedule):
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, EIGHT)
    wall = EIGHT.timestamp()
    timed = transit_live.with_live_trains(plan, live_at(wall), now=wall)
    chosen = transit.choose(timed, metro_option(timed).key)
    metro = transit_legs(chosen.option)[0]
    # At Eastern Market by 8:05 (a minute's ride, 4 min in by the elevator): the train in 3 min
    # is gone, the one in 11 min is caught; the time on board is still the timetable's.
    scheduled = transit_legs(metro_option(plan))[0]
    eight = transit._moment(EIGHT, EIGHT.date()).minute
    assert metro.live and metro.depart == pytest.approx(eight + 11)
    assert metro.wait_s == pytest.approx(chosen.option.legs[2].wait_s)
    assert metro.seconds == scheduled.seconds
    assert transit.minutes(metro.wait_s) == 6
    # The order follows the new totals.
    order = [(transit.minutes(o.total_s), o.key) for o in timed.options]
    assert [m for m, _ in order] == sorted(m for m, _ in order)
    block = transit.block(chosen, schedule)
    step = next(s for s in block["steps"] if s["mode"] == "metro")
    assert step["source"] == "live"
    assert step["text"].startswith(
        "Board the Orange Line at 8:11 am live from Eastern Market: you arrive 8:05 am, 6 min"
        " spare; next train after that: 8:19 am live."
    )
    assert block["live_times"] and block["summary"].endswith("with live departures.")
    # The time on board is the timetable's, so the track-work note stays.
    assert transit.LIVE_WORDS in block["notes"] and transit.SCHEDULED_WORDS in block["notes"]
    # A train every few minutes has no countdown, live or not.
    assert block["departure"] is None


def test_a_ride_routed_slower_than_the_predictions_reach_waits_as_the_timetable_says(schedule):
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, EIGHT)
    wall = EIGHT.timestamp()
    timed = transit_live.with_live_trains(plan, live_at(wall), now=wall)
    chosen = transit.choose(timed, metro_option(timed).key)
    # Routed 16 min instead of 1: at the station after the last train WMATA predicts (8:19).
    slow = transit.with_rides(chosen, {0: 960.0})
    assert slow.option.key == chosen.option.key
    metro = transit_legs(slow.option)[0]
    assert not metro.live and metro.depart is None and metro.wait_s == metro.every * 30.0
    # Routed 9 min: the 8:11 is missed, the 8:19 is caught, still live.
    later = transit_legs(transit.with_rides(chosen, {0: 540.0}).option)[0]
    assert later.live and later.depart == pytest.approx(transit_legs(chosen.option)[0].after)


def test_a_change_after_an_estimated_wait_is_not_timed_live(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, EIGHT)
    two = next(o for o in plan.options if len(transit_legs(o)) == 2 and o.legs[2].system == "Metro")
    second = next(i for i, leg in enumerate(two.legs) if leg.transit and leg.change)
    moment = plan.moment
    timed = transit_live._timed(
        two, moment, lambda i, _leg: [moment.minute + 30] if i == second else None
    )
    assert timed is two


def test_the_trip_the_rider_chose_stays_chosen_when_the_order_moves(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, EIGHT)
    asked = transit.choose(plan, plan.options[-1].key)
    wall = EIGHT.timestamp()
    timed = transit_live.with_live_trains(asked, live_at(wall), now=wall)
    assert timed.option.key == plan.options[-1].key


def test_a_plan_for_later_or_an_old_reading_stays_on_the_timetable(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, EIGHT)
    wall = EIGHT.timestamp()
    assert transit_live.with_live_trains(plan, live_at(wall), now=wall - 3600) is plan
    assert transit_live.with_live_trains(plan, live_at(wall - 600), now=wall) is plan
    assert transit_live.with_live_trains(plan, live_at(wall, stale=True), now=wall) is plan
    assert transit_live.with_live_trains(plan, None, now=wall) is plan
    trip = transit.choose(plan, metro_option(plan).key)
    block = transit.block(trip, schedule)
    assert not block["live_times"] and block["summary"].endswith("scheduled.")
    assert transit.SCHEDULED_WORDS in block["notes"]


def test_predictions_that_run_out_before_the_rider_gets_there_keep_the_timetable() -> None:
    leg = transit.Leg(transit.METRO, 600.0, system="Metro", wait_s=300.0, every=10.0)
    assert transit_live._caught(leg, 500.0, [490.0, 498.0]) is None
    caught = transit_live._caught(leg, 500.0, [498.0, 503.0, 509.0])
    assert caught.live and caught.depart == 503.0 and caught.after == 509.0
    assert caught.wait_s == pytest.approx(180.0)


def test_a_chosen_trips_bus_boards_the_next_bus_wmata_predicts(schedule) -> None:
    from core import wmata_bus

    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, EIGHT)
    bus = next(
        o for o in plan.options if transit_legs(o) and transit_legs(o)[0].system == "Metrobus"
    )
    chosen = transit.choose(plan, bus.key)
    index = next(i for i, leg in enumerate(chosen.legs) if leg.system == "Metrobus")
    wall = EIGHT.timestamp()
    said = {"text": "Live: bus 90 in 2 min, 9 min.", "minutes": [2, 9], "source": "live"}
    buses = wmata_bus.StepLives({index: said}, wall)
    timed = transit_live.with_live_buses(chosen, buses, now=wall)
    leg = timed.legs[index]
    # At the stop about 8:05.6: the bus at 8:02 is gone, the one at 8:09 is caught.
    assert leg.live and leg.depart == pytest.approx(transit._moment(EIGHT, EIGHT.date()).minute + 9)
    assert transit.minutes(leg.wait_s) == 3
    assert timed.option.total_s < chosen.option.total_s
    assert transit.block(timed, schedule)["steps"][index]["source"] == "live"
    # A plan for later is the timetable's.
    assert transit_live.with_live_buses(chosen, buses, now=wall + 3600) is chosen


@db
@pytest.mark.usefixtures("weekday_clock")
def test_a_plan_asked_for_now_says_its_live_departures(
    client, segments, router, installed, monkeypatch
) -> None:
    noon = at(2026, 9, 30, 12, 0).timestamp()
    monkeypatch.setattr(wmata_live.client, "snapshot", lambda: live_at(noon))
    monkeypatch.setattr(transit_live, "_wall", lambda: noon)
    router(standard_router())
    first = post_transit(client, [CAPITOL_HILL, DOWNTOWN]).json()["transit"]
    metro = next(o for o in first["options"] if not o["direct"] and o["legs"][1]["mode"] == "metro")
    block = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=metro["key"]).json()
    step = next(s for s in block["transit"]["steps"] if s["mode"] == "metro")
    assert step["source"] == "live" and " live from " in step["text"]
    assert block["transit"]["live_times"]
