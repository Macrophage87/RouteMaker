"""The nearest stations to pick up from or return to (OWNER-DECISIONS 466, 466a), the freshness
rule for a silent station, and a rider's chosen station.

The planner part uses synthetic streets (stations at known distances east of one point) so the
answer is arithmetic; the API part uses the sampled GBFS fixtures through a fake network.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_bikeshare import FakeServices, east
from test_bikeshare_api import Routers, body
from test_gbfs import FEED_NOW, Clock, FakeNetwork, feed_wall
from test_route_api import db, post

from core import bikeshare, gbfs, presets, routing
from core.bikeshare import NoBikeshare

NOW = float(FEED_NOW)
ORIGIN = east(0)
STATIONS_PATH = "/api/bikeshare/stations"


@pytest.fixture
def world(monkeypatch, segment_schemas):
    """The routers and the operator's feeds, both faked (as tests/test_bikeshare_api.py)."""
    routers = Routers()
    monkeypatch.setattr(routing, "_transport", routers)
    net = FakeNetwork()
    monkeypatch.setattr(gbfs, "client", gbfs.Gbfs(net, Clock(), wall=feed_wall))
    return routers, net


def dock(name, at, bikes, slots, *, ebikes=0, age=60, **flags) -> tuple:
    return (name, at, bikes, slots, ebikes, age, flags)


def street(*docks, status=True, **changes) -> gbfs.Snapshot:
    """A snapshot of docks as (name, metres east, bikes, free slots, e-bikes, age in s, flags)."""
    stations, statuses = [], {}
    for index, (name, at, bikes, slots, ebikes, age, flags) in enumerate(docks):
        lon, lat = east(at)
        stations.append(gbfs.Station(f"s{index}", name, lon, lat, 20))
        statuses[f"s{index}"] = gbfs.StationStatus(
            f"s{index}",
            bikes,
            ebikes,
            slots,
            flags.get("renting", True),
            flags.get("returning", True),
            flags.get("installed", True),
            last_reported=None if age is None else int(NOW - age),
        )
    return gbfs.Snapshot(
        fetched_at=0.0,
        stations=stations,
        status=statuses if status else None,
        free_bikes=[],
        pricing=[],
        zones=None,
        alerts=[],
        unlisted=frozenset({"geofencing_zones"}),
        as_of=NOW,
        **changes,
    )


def names(found) -> list[str]:
    return [s.name for s in found]


# --- The fullness of a station -----------------------------------------------------------


@pytest.mark.parametrize(
    ("bikes", "slots", "full"),
    [(3, 1, 0.75), (1, 3, 0.25), (0, 5, 0.0), (5, 0, 1.0), (299, 100, 299 / 399)],
)
def test_fullness_is_bikes_over_bikes_plus_free_docks(bikes, slots, full) -> None:
    status = gbfs.StationStatus("a", bikes, 0, slots, True, True, True)
    assert status.fullness == pytest.approx(full)


def test_a_station_with_no_bikes_and_no_free_docks_has_no_fullness() -> None:
    assert gbfs.StationStatus("a", 0, 0, 0, True, True, True).fullness is None


def test_disabled_bikes_and_docks_and_the_last_report_are_kept_from_the_feed() -> None:
    status = gbfs.parse_status(
        {
            "data": {
                "stations": [
                    {
                        "station_id": "a",
                        "num_bikes_available": 4,
                        "num_bikes_disabled": 2,
                        "num_docks_available": 5,
                        "num_docks_disabled": 3,
                        "num_ebikes_available": 1,
                        "last_reported": 1791098532,
                    }
                ]
            }
        }
    )["a"]
    assert (status.bikes_disabled, status.docks_disabled, status.last_reported) == (
        2,
        3,
        1791098532,
    )
    # The operator's own counts of broken bikes and docks are in neither side of the share.
    assert status.fullness == pytest.approx(4 / 9)


@pytest.mark.parametrize("value", [None, "1791098532", True, 0, -5, 12345])
def test_a_last_report_that_is_not_a_time_is_none(value) -> None:
    doc = {"data": {"stations": [{"station_id": "a", "last_reported": value}]}}
    assert gbfs.parse_status(doc)["a"].last_reported is None


# --- Reporting freshness: a long silent station is unavailable --------------------------------


def test_a_station_silent_for_thirty_minutes_is_stale_and_one_a_second_inside_is_not() -> None:
    snap = street(dock("Edge", 100, 5, 5, age=1800), dock("Over", 200, 5, 5, age=1801))
    assert not snap.reporting_stale(snap.status["s0"])
    assert snap.reporting_stale(snap.status["s1"])
    assert gbfs.STATION_STALE_S == 30 * 60


def test_a_station_that_gave_no_report_time_is_stale_when_the_reading_time_is_known() -> None:
    snap = street(dock("Unsure", 100, 5, 5, age=None))
    assert snap.reporting_stale(snap.status["s0"])
    # A snapshot built by hand, with no reading time, judges nothing.
    assert not replace(snap, as_of=None).reporting_stale(snap.status["s0"])


def test_a_report_from_the_future_is_not_stale() -> None:
    snap = street(dock("Ahead", 100, 5, 5, age=-120))
    assert not snap.reporting_stale(snap.status["s0"])


def test_a_stale_nearest_dock_is_passed_over_with_a_note_and_the_next_is_used() -> None:
    snap = street(
        dock("Silent", 50, 6, 4, age=3 * 3600),
        dock("Live", 300, 6, 4),
        dock("Far", 3000, 0, 9),
    )
    body_, _ = plan(east(0), east(3000), snap)
    plan_ = body_["bikeshare"]
    assert plan_["start"]["name"] == "Live"
    assert any("Silent" in n and "has not reported in over 30 minutes" in n for n in plan_["notes"])


def test_a_stale_dock_cannot_end_a_ride_either() -> None:
    snap = street(dock("Start", 0, 6, 0), dock("Silent", 3000, 0, 9, age=7200))
    with pytest.raises(NoBikeshare, match="No dock within"):
        plan(east(0), east(3000), snap)


def plan(origin, dest, snap, bike="classic", **chosen):
    services = FakeServices(ride_speed_kmh=presets.BIKESHARE_BIKES[bike].speed_kmh)
    return (
        bikeshare.plan(
            origin,
            dest,
            bike,
            bikeshare.ENDING_DOCK,
            snap,
            services,
            presets.BIKESHARE_BIKES[bike].speed_kmh,
            **chosen,
        ),
        services,
    )


# --- The three nearest stations at least 3/4 full -----------------------------------------


def test_pickup_lists_the_three_nearest_stations_at_least_three_quarters_full() -> None:
    snap = street(
        dock("A", 100, 3, 1),  # 75%: exactly at the bar
        dock("B", 200, 7, 3),  # 70%
        dock("C", 300, 8, 2),  # 80%
        dock("D", 400, 9, 1),  # 90%
        dock("E", 500, 10, 0),  # 100%: a fourth, left out
    )
    found = bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap)
    assert names(found) == ["A", "C", "D"]
    assert [s.percent_full for s in found] == [75, 80, 90]


def test_a_station_just_under_three_quarters_is_not_listed_and_just_at_it_is() -> None:
    snap = street(dock("Under", 100, 299, 100), dock("At", 200, 3, 1))
    assert names(bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap)) == ["At"]


def test_nearest_first_and_nothing_else_a_fuller_farther_station_does_not_jump_the_queue() -> None:
    snap = street(dock("Near", 100, 3, 1), dock("Fuller", 150, 10, 0), dock("Far", 900, 10, 0))
    found = bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap)
    assert names(found) == ["Near", "Fuller", "Far"]
    assert [s.distance_m for s in found] == sorted(s.distance_m for s in found)


def test_pickup_skips_stations_that_cannot_rent() -> None:
    snap = street(
        dock("Not renting", 100, 9, 1, renting=False),
        dock("Not installed", 150, 9, 1, installed=False),
        dock("Fine", 200, 9, 1),
    )
    assert names(bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap)) == ["Fine"]


def test_pickup_skips_a_station_that_has_not_reported_for_thirty_minutes() -> None:
    snap = street(
        dock("Silent", 100, 9, 1, age=1801),
        dock("No time", 120, 9, 1, age=None),
        dock("Fine", 200, 9, 1, age=1790),
    )
    assert names(bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap)) == ["Fine"]


def test_a_station_with_no_bikes_and_no_slots_is_not_listed_for_either() -> None:
    snap = street(dock("Zero", 100, 0, 0))
    assert bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap) == []
    assert bikeshare.nearby_stations(ORIGIN, bikeshare.DROPOFF, snap) == []


# --- The three nearest at most 1/4 full --------------------------------------------------------


def test_dropoff_lists_the_three_nearest_stations_at_most_one_quarter_full() -> None:
    snap = street(
        dock("A", 100, 1, 3),  # 25%: exactly at the bar
        dock("B", 200, 2, 5),  # 28.6%
        dock("C", 300, 0, 8),  # 0%
        dock("D", 400, 2, 8),  # 20%
        dock("E", 500, 0, 4),  # a fourth, left out
    )
    found = bikeshare.nearby_stations(ORIGIN, bikeshare.DROPOFF, snap)
    assert names(found) == ["A", "C", "D"]
    assert [s.percent_full for s in found] == [25, 0, 20]


def test_dropoff_skips_stations_that_cannot_take_a_bike_back() -> None:
    snap = street(
        dock("Not returning", 100, 0, 9, returning=False),
        dock("Not installed", 150, 0, 9, installed=False),
        dock("Silent", 160, 0, 9, age=4000),
        dock("Fine", 200, 0, 9),
    )
    assert names(bikeshare.nearby_stations(ORIGIN, bikeshare.DROPOFF, snap)) == ["Fine"]


def test_the_two_lists_never_hold_the_same_station() -> None:
    snap = street(*(dock(f"S{i}", 100 * (i + 1), i, 10 - i) for i in range(11)))
    pick = set(names(bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap)))
    drop = set(names(bikeshare.nearby_stations(ORIGIN, bikeshare.DROPOFF, snap)))
    assert not pick & drop


def test_fewer_than_three_that_fit_are_listed_and_none_is_an_empty_list() -> None:
    snap = street(dock("Only", 100, 9, 1), dock("Half", 200, 5, 5))
    assert names(bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap)) == ["Only"]
    assert bikeshare.nearby_stations(ORIGIN, bikeshare.DROPOFF, snap) == []


def test_with_no_availability_feed_nothing_is_listed() -> None:
    snap = street(dock("A", 100, 9, 1), status=False)
    assert bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap) == []


def test_stations_beyond_the_search_radius_are_not_listed() -> None:
    snap = street(dock("Far", 3500, 9, 1))
    assert bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap) == []


def test_a_listed_station_carries_its_distance_and_counts() -> None:
    snap = street(dock("A", 320, 6, 2, ebikes=2))
    (found,) = bikeshare.nearby_stations(ORIGIN, bikeshare.PICKUP, snap)
    assert found.station_id == "s0" and found.percent_full == 75
    assert found.distance_m == pytest.approx(320, abs=2)
    assert (found.bikes, found.ebikes, found.docks) == (6, 2, 2)


def test_an_action_that_is_neither_is_refused() -> None:
    with pytest.raises(ValueError):
        bikeshare.nearby_stations(ORIGIN, "both", street())


# --- A station the rider chose ------------------------------------------------------------------


def test_a_chosen_pickup_is_used_instead_of_the_nearest_dock() -> None:
    snap = street(
        dock("Near", 50, 6, 4),
        dock("Chosen", 400, 9, 1),
        dock("Far end", 3000, 0, 9),
    )
    body_, _ = plan(east(0), east(3000), snap, pickup_station="s1")
    start = body_["bikeshare"]["start"]
    assert start["name"] == "Chosen" and start["station_id"] == "s1"
    # No note about a nearer dock: the rider chose this one.
    assert not any("Near" in n for n in body_["bikeshare"]["notes"])


def test_a_chosen_dropoff_is_used_instead_of_the_nearest_dock() -> None:
    snap = street(
        dock("Start", 0, 6, 4),
        dock("Near end", 2950, 0, 9),
        dock("Chosen end", 2600, 1, 9),
    )
    body_, _ = plan(east(0), east(3000), snap, dropoff_station="s2")
    assert body_["bikeshare"]["end"]["name"] == "Chosen end"


def test_a_chosen_station_that_can_no_longer_serve_says_why_instead_of_guessing() -> None:
    snap = street(dock("Start", 0, 6, 4), dock("Empty now", 400, 0, 9), dock("End", 3000, 0, 9))
    with pytest.raises(NoBikeshare, match="Empty now.*no classic bikes right now.*let the plan"):
        plan(east(0), east(3000), snap, pickup_station="s1")
    snap = street(dock("Start", 0, 6, 4), dock("Full now", 2900, 5, 0), dock("End", 3000, 0, 9))
    with pytest.raises(NoBikeshare, match="Full now.*no free slots"):
        plan(east(0), east(3000), snap, dropoff_station="s1")


def test_a_chosen_station_that_went_silent_is_refused_in_words() -> None:
    snap = street(dock("Start", 0, 6, 4, age=9000), dock("End", 3000, 0, 9))
    with pytest.raises(NoBikeshare, match="Start.*has not reported in over 30 minutes"):
        plan(east(0), east(3000), snap, pickup_station="s0")


def test_an_unknown_station_id_is_refused_in_words() -> None:
    with pytest.raises(NoBikeshare, match="no longer in the operator's list"):
        plan(
            east(0),
            east(3000),
            street(dock("A", 0, 6, 4), dock("B", 3000, 0, 9)),
            pickup_station="zz",
        )


# --- The API -----------------------------------------------------------------------------


def stations_post(client, payload, **extra):
    data = payload if isinstance(payload, str | bytes) else json.dumps(payload)
    return client.post(STATIONS_PATH, data=data, content_type="application/json", **extra)


UNION_POINT = [-77.0063, 38.8973]


@db
class TestStationsEndpoint:
    def test_pickup_answers_with_up_to_three_stations_nearest_first_all_three_quarters_full(
        self, client, world
    ) -> None:
        response = stations_post(client, {"point": UNION_POINT, "action": "pickup"})
        assert response.status_code == 200, response.content
        assert response["Cache-Control"] == "no-store"
        data = response.json()
        assert set(data) == {"action", "availability", "stations", "credit"}
        assert data["action"] == "pickup" and data["availability"] == "live"
        assert data["credit"] == gbfs.CREDIT
        found = data["stations"]
        assert 1 <= len(found) <= 3
        assert [s["distance_m"] for s in found] == sorted(s["distance_m"] for s in found)
        for s in found:
            assert s["percent_full"] >= 75
            assert set(s) == {
                "station_id",
                "name",
                "lon",
                "lat",
                "percent_full",
                "distance_m",
                "bikes",
                "ebikes",
                "docks",
            }

    def test_dropoff_answers_with_stations_at_most_one_quarter_full(self, client, world) -> None:
        data = stations_post(client, {"point": UNION_POINT, "action": "dropoff"}).json()
        assert data["action"] == "dropoff"
        assert 1 <= len(data["stations"]) <= 3
        assert all(s["percent_full"] <= 25 and s["docks"] > 0 for s in data["stations"])

    def test_the_sampled_stations_that_were_silent_for_hours_are_not_listed(
        self, client, world
    ) -> None:
        silent = {
            station_id
            for station_id, status in gbfs.client.snapshot().status.items()
            if gbfs.client.snapshot().reporting_stale(status)
        }
        assert silent  # the sample has two (8.5 and 3.7 hours quiet)
        for action in ("pickup", "dropoff"):
            data = stations_post(client, {"point": UNION_POINT, "action": action}).json()
            assert not silent & {s["station_id"] for s in data["stations"]}

    def test_the_point_is_not_in_the_operators_requests(self, client, world) -> None:
        _, net = world
        stations_post(client, {"point": UNION_POINT, "action": "pickup"})
        assert net.calls and not any("38.89" in u or "77.00" in u for u in net.calls)

    def test_many_lists_are_one_read_of_the_operator(self, client, world) -> None:
        _, net = world
        for action in ("pickup", "dropoff", "pickup"):
            assert (
                stations_post(client, {"point": UNION_POINT, "action": action}).status_code == 200
            )
        assert gbfs.client.refreshes == 1 and len(net.calls) == 6

    def test_with_no_availability_feed_it_says_unknown_and_lists_none(
        self, client, monkeypatch, segment_schemas
    ) -> None:
        monkeypatch.setattr(
            gbfs, "client", gbfs.Gbfs(FakeNetwork(fail={"station_status"}), Clock(), wall=feed_wall)
        )
        data = stations_post(client, {"point": UNION_POINT, "action": "pickup"}).json()
        assert data["availability"] == "unknown" and data["stations"] == []

    def test_with_no_station_list_it_is_a_503_with_its_own_code(
        self, client, monkeypatch, segment_schemas
    ) -> None:
        net = FakeNetwork()
        net.down = True
        monkeypatch.setattr(gbfs, "client", gbfs.Gbfs(net, Clock(), wall=feed_wall))
        response = stations_post(client, {"point": UNION_POINT, "action": "pickup"})
        assert response.status_code == 503
        assert response.json()["code"] == "bikeshare_unavailable" and response["Retry-After"]

    @pytest.mark.parametrize(
        "payload",
        [
            {"point": UNION_POINT},
            {"action": "pickup"},
            {"point": UNION_POINT, "action": "both"},
            {"point": [-100.0, 40.0], "action": "pickup"},
            {"point": [-77.0], "action": "pickup"},
            {"point": UNION_POINT, "action": "pickup", "bike": "ebike"},
            {"point": [float("nan"), 38.9], "action": "pickup"},
        ],
    )
    def test_what_it_will_not_take(self, client, world, payload) -> None:
        response = stations_post(client, json.dumps(payload))
        assert response.status_code == 400, response.content

    def test_a_non_json_body_is_refused_before_it_counts(self, client, world) -> None:
        response = client.post(STATIONS_PATH, data="point=1", content_type="text/plain")
        assert response.status_code == 400

    def test_a_get_is_not_the_way_to_ask(self, client, world) -> None:
        assert (
            client.get(STATIONS_PATH, {"lon": -77.0, "lat": 38.9, "action": "pickup"}).status_code
            == 405
        )

    def test_it_has_its_own_limit_apart_from_routing(self, client, world) -> None:
        from core import ratelimit

        assert ratelimit.BIKESHARE_STATIONS.scope == "bikeshare-stations"
        assert ratelimit.BIKESHARE_STATIONS.scope != ratelimit.ROUTING.scope
        payload = {"point": UNION_POINT, "action": "pickup"}
        codes = [stations_post(client, payload).status_code for _ in range(61)]
        assert codes[:60] == [200] * 60 and codes[60] == 429
        # ... and it spent none of the routing budget.
        assert post(client, body()).status_code == 200

    def test_the_schema_describes_it(self, client) -> None:
        schema = client.get("/api/openapi.json").json()
        assert STATIONS_PATH in schema["paths"] and "post" in schema["paths"][STATIONS_PATH]
        assert "NearbyStationsOut" in schema["components"]["schemas"]
        route_in = schema["components"]["schemas"]["RouteIn"]["properties"]
        assert "pickup_station" in route_in and "dropoff_station" in route_in


@db
class TestRouteWithAChosenStation:
    def test_a_chosen_pickup_starts_the_plan_there(self, client, world) -> None:
        listed = stations_post(client, {"point": UNION_POINT, "action": "pickup"}).json()[
            "stations"
        ]
        chosen = listed[-1]
        response = post(client, body(pickup_station=chosen["station_id"]))
        assert response.status_code == 200, response.content
        start = response.json()["bikeshare"]["start"]
        assert start["station_id"] == chosen["station_id"]

    def test_a_chosen_dropoff_ends_the_plan_there(self, client, world) -> None:
        dupont = [-77.0436, 38.9096]
        listed = stations_post(client, {"point": dupont, "action": "dropoff"}).json()["stations"]
        chosen = listed[-1]
        response = post(client, body(dropoff_station=chosen["station_id"]))
        assert response.status_code == 200, response.content
        assert response.json()["bikeshare"]["end"]["station_id"] == chosen["station_id"]

    def test_a_chosen_station_that_cannot_serve_is_a_422_in_words(self, client, world) -> None:
        silent = next(
            sid
            for sid, status in gbfs.client.snapshot().status.items()
            if gbfs.client.snapshot().reporting_stale(status)
        )
        response = post(client, body(pickup_station=silent))
        assert response.status_code == 422
        assert response.json()["code"] == "no_bikeshare"
        assert "let the plan choose" in response.json()["error"]

    def test_the_stations_belong_to_bikeshare_only(self, client, world) -> None:
        for extra in ({"pickup_station": "x"}, {"dropoff_station": "x"}):
            response = post(
                client, {"points": [UNION_POINT, [-77.02, 38.9]], "preset": "default", **extra}
            )
            assert response.status_code == 400
            assert "Bikeshare ride type only" in response.json()["error"]

    def test_a_chosen_dropoff_is_not_for_an_outside_dock_ending(self, client, world) -> None:
        response = post(client, body("ebike", ending="outside_dock", dropoff_station="x"))
        assert response.status_code == 400
        assert "ending at a dock" in response.json()["error"]

    @pytest.mark.parametrize("value", ["", "x" * 65, 7])
    def test_a_station_id_must_be_short_text(self, client, world, value) -> None:
        assert post(client, body(pickup_station=value)).status_code == 400
