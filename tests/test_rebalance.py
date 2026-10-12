"""Rebalance Ride (REBALANCE-RIDE; Stephen, 2026-10-12): a bikeshare plan from a crowded
station near the start to one that needs bikes near the destination, chosen from the
station status's fill (bikes / (bikes + free docks)), as the station lists choose them.

The fake router and GBFS fixtures are test_bikeshare's. Near Union Station, Columbus Circle
is 23% full (plain Bikeshare starts there) and 2nd & G St NE, 3rd & H St NE and 1st & K St NE
are over 3/4 full; near Dupont Circle, 18th & New Hampshire Ave NW is 11% full.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_bikeshare import (
    COLUMBUS,
    DUPONT,
    UNION,
    FakeServices,
    run,
    set_status,
    snapshot,
)
from test_bikeshare_api import world  # noqa: F401
from test_route_api import db, post

from core import bikeshare, presets
from core.bikeshare import ENDING_DOCK, ENDING_OUTSIDE, NoBikeshare


def rebalance(origin, dest, bike="classic", snap=None, ending=ENDING_DOCK, **kwargs):
    services = FakeServices(ride_speed_kmh=presets.BIKESHARE_BIKES[bike].speed_kmh)
    snap = snap or snapshot()
    body = bikeshare.plan(
        origin,
        dest,
        bike,
        ending,
        snap,
        services,
        presets.BIKESHARE_BIKES[bike].speed_kmh,
        rebalance=True,
        **kwargs,
    )
    return body, services, snap


def fill(snap, station_id: str) -> float:
    return snap.status[station_id].fullness


def test_it_picks_up_at_a_crowded_station_and_returns_to_one_that_needs_bikes() -> None:
    plain, _ = run(UNION, DUPONT)
    assert plain["bikeshare"]["start"]["name"] == COLUMBUS.name
    body, _, snap = rebalance(UNION, DUPONT)
    plan = body["bikeshare"]
    assert plan["rebalance"] is True
    assert plan["start"]["name"] != COLUMBUS.name
    assert fill(snap, plan["start"]["station_id"]) >= bikeshare.FULL_AT_LEAST
    assert fill(snap, plan["end"]["station_id"]) <= bikeshare.EMPTY_AT_MOST
    assert plan["end"]["name"] == "18th & New Hampshire Ave NW"
    # Every option is a rebalancing pair too.
    assert plan["options"]
    for option in plan["options"]:
        assert fill(snap, option["pickup_station"]) >= bikeshare.FULL_AT_LEAST
        assert fill(snap, option["dropoff_station"]) <= bikeshare.EMPTY_AT_MOST
    # Plain Bikeshare is unchanged: it has no rebalance flag set.
    assert plain["bikeshare"]["rebalance"] is False


def test_the_docks_are_the_station_lists_own_ranking() -> None:
    snap = snapshot()
    starts = bikeshare.rebalance_starts(UNION, DUPONT, "classic", snap)
    listed = bikeshare.nearby_stations(UNION, bikeshare.PICKUP, snap, DUPONT)
    assert [p.station_id for _, p in starts] == [s.station_id for s in listed]
    assert len(starts) == bikeshare.NEARBY_COUNT
    ends = bikeshare.rebalance_ends(DUPONT, UNION, snap)
    listed = bikeshare.nearby_stations(DUPONT, bikeshare.DROPOFF, snap, UNION)
    assert [p.station_id for _, p in ends] == [s.station_id for s in listed]


def test_stations_toward_the_destination_come_first() -> None:
    snap = snapshot()
    starts = bikeshare.rebalance_starts(UNION, DUPONT, "classic", snap)
    costs = [bikeshare.station_cost_m(p.point, UNION, DUPONT) for _, p in starts]
    assert costs == sorted(costs)


def test_no_distance_cap() -> None:
    # Empty every crowded station near the start but one far away: it is still offered.
    snap = snapshot()
    near = bikeshare._by_distance(snap, UNION)
    far_station = near[-1][1]
    for _distance, station in near:
        status = snap.status.get(station.station_id)
        if status is None or station is far_station:
            continue
        snap = set_status(snap, station, bikes=0, ebikes=0)
    snap = set_status(
        snap,
        far_station,
        bikes=20,
        ebikes=0,
        docks=1,
        renting=True,
        installed=True,
    )
    assert near[-1][0] > bikeshare.SEARCH_RADIUS_M
    starts = bikeshare.rebalance_starts(UNION, DUPONT, "classic", snap)
    assert [p.station_id for _, p in starts] == [far_station.station_id]


def test_e_bikes_count_toward_the_fill_and_the_bike_type_must_be_there() -> None:
    snap = snapshot()
    station = COLUMBUS
    # 2 classic and 18 e-bikes, 2 free docks: 91% full, crowded by its e-bikes.
    snap = set_status(snap, station, bikes=20, ebikes=18)
    snap = set_status(snap, station, docks=2)
    assert fill(snap, station.station_id) >= bikeshare.FULL_AT_LEAST
    ebike = [p.station_id for _, p in bikeshare.rebalance_starts(UNION, DUPONT, "ebike", snap)]
    assert station.station_id in ebike
    # With no classic bike there, a classic-bike rider is not sent to it.
    snap = set_status(snap, station, bikes=18, ebikes=18)
    snap = set_status(snap, station, docks=1)
    classic = [p.station_id for _, p in bikeshare.rebalance_starts(UNION, DUPONT, "classic", snap)]
    assert station.station_id not in classic


def test_the_steps_say_crowded_and_needs_bikes_and_no_points() -> None:
    body, _, _ = rebalance(UNION, DUPONT)
    plan = body["bikeshare"]
    assert ", which is crowded, take a classic bike" in plan["steps"][0]["text"]
    assert ", which needs bikes (" in plan["steps"][1]["text"]
    assert plan["summary"].startswith("Rebalance Ride, classic bike: about ")
    said = " ".join([plan["summary"], *plan["notes"]]).lower()
    assert "point" not in said and "angel" not in said


def test_it_always_ends_at_a_dock() -> None:
    body, _, _ = rebalance(UNION, DUPONT, bike="ebike", ending=ENDING_OUTSIDE)
    plan = body["bikeshare"]
    assert plan["ending"] == ENDING_DOCK
    assert plan["start"]["kind"] == "dock"


def test_no_crowded_station_or_none_that_needs_bikes_is_said() -> None:
    snap = snapshot()
    for station in snap.stations:
        if station.station_id in snap.status:
            snap = set_status(snap, station, bikes=5, ebikes=0)
            snap = set_status(snap, station, docks=5)
    with pytest.raises(NoBikeshare, match="No station has classic bikes to spare"):
        rebalance(UNION, DUPONT, snap=snap)
    # Crowded starts, but nowhere that needs bikes.
    snap = set_status(snap, COLUMBUS, bikes=20, docks=1)
    with pytest.raises(NoBikeshare, match="No station needs bikes right now"):
        rebalance(UNION, DUPONT, snap=snap)


def test_without_availability_it_says_so() -> None:
    from dataclasses import replace

    with pytest.raises(NoBikeshare, match="can't be read"):
        rebalance(UNION, DUPONT, snap=replace(snapshot(), status=None))


def test_the_programmes_name_is_nowhere_in_the_api() -> None:
    # Stephen, 2026-10-12: not the operator's programme name; it is only in the front end's
    # description of the ride type (frontend/src/lib/rebalance.test.ts holds that).
    programme = " ".join(["Bike", "Angels"])
    src = Path(__file__).resolve().parents[1] / "src"
    assert [p for p in src.rglob("*.py") if programme in p.read_text()] == []


def test_its_ride_leg_is_bikeshares() -> None:
    assert presets.costing(presets.REBALANCE) == presets.costing(presets.BIKESHARE)
    rebalance_preset = presets.PRESETS[presets.REBALANCE]
    bikeshare_preset = presets.PRESETS[presets.BIKESHARE]
    assert rebalance_preset.stress == bikeshare_preset.stress == presets.BIKESHARE_STRESS
    assert rebalance_preset.hills == bikeshare_preset.hills == -60
    assert rebalance_preset.exposure is bikeshare_preset.exposure
    assert rebalance_preset.brake_grade == bikeshare_preset.brake_grade
    assert presets.BIKESHARE_PRESETS == {presets.BIKESHARE, presets.REBALANCE}


# --- POST /api/route with `preset: "rebalance"` ------------------------------------------------


@db
@pytest.mark.usefixtures("weekday_clock", "world")
class TestRebalanceApi:
    def test_a_rebalance_ride_is_a_bikeshare_answer_from_crowded_to_low(self, client) -> None:
        response = post(client, {"points": [UNION, DUPONT], "preset": "rebalance"})
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["preset"] == "rebalance"
        plan = data["bikeshare"]
        assert plan["rebalance"] is True and plan["ending"] == "dock"
        assert plan["start"]["name"] != COLUMBUS.name
        assert plan["end"]["name"] == "18th & New Hampshire Ave NW"
        assert plan["summary"].startswith("Rebalance Ride, classic bike")

    def test_it_takes_the_bike_choice_as_bikeshare_does(self, client) -> None:
        response = post(client, {"points": [UNION, DUPONT], "preset": "rebalance", "bike": "ebike"})
        assert response.status_code == 200, response.content
        assert response.json()["bikeshare"]["bike"] == "ebike"

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"bike": "ebike", "ending": "outside_dock"}, "Rebalance Ride ends at a station"),
            ({"assist": True}, "assist applies to the Cargo Bike"),
            ({"loop": True}, "does not plan loops"),
            ({"points": [UNION, DUPONT, UNION]}, "take a start and an end"),
        ],
    )
    def test_what_it_will_not_take(self, client, changes, message) -> None:
        response = post(client, {"points": [UNION, DUPONT], "preset": "rebalance", **changes})
        assert response.status_code == 400, response.content
        assert message in response.json()["error"]
