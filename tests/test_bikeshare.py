"""The bikeshare planner (core.bikeshare), with a fake router and fake GBFS.

The stations are the sampled fixtures of tests/data/gbfs (Union Station and Dupont Circle
clusters); statuses are set per test. The walks are straight lines at the planner's walking
pace and the ride is a straight line at the bike's pace, so a result is arithmetic.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core import bikeshare, gbfs, presets
from core.bikeshare import ENDING_DOCK, ENDING_OUTSIDE, NoBikeshare, WalkLeg

DATA = Path(__file__).parent / "data" / "gbfs"

UNION = [-77.0063, 38.8973]
DUPONT = [-77.0436, 38.9096]


def doc(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


STATIONS = gbfs.parse_stations(doc("station_information"))
BY_NAME = {s.name: s for s in STATIONS}
COLUMBUS = BY_NAME["Columbus Circle / Union Station"]
NJ_AVE = BY_NAME["New Jersey Ave & F St NW"]
NORTH_CAP_F = BY_NAME["North Capitol St & F St NW"]
DUPONT_SOUTH = BY_NAME["20th & O St NW / Dupont South"]
TWENTIETH_Q = BY_NAME["20th & Q St NW"]
TWENTY_SECOND_P = BY_NAME["22nd & P ST NW"]
DUPONT_NORTH_R = BY_NAME["Connecticut Ave & R St NW"]

ZONE_ALL_SQUARE = {
    "data": {
        "geofencing_zones": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-77.05, 38.905],
                                [-77.04, 38.905],
                                [-77.04, 38.915],
                                [-77.05, 38.915],
                                [-77.05, 38.905],
                            ]
                        ],
                    },
                    "properties": {"rules": [{"ride_allowed": False}]},
                }
            ],
        }
    }
}


def snapshot(**changes) -> gbfs.Snapshot:
    base = gbfs.Snapshot(
        fetched_at=0.0,
        stations=STATIONS,
        status=gbfs.parse_status(doc("station_status")),
        free_bikes=[],
        pricing=gbfs.parse_pricing(doc("system_pricing_plans")),
        zones=None,
        alerts=[],
        unlisted=frozenset({"geofencing_zones"}),
    )
    return replace(base, **changes)


def set_status(snap: gbfs.Snapshot, station: gbfs.Station, **fields) -> gbfs.Snapshot:
    status = dict(snap.status)
    status[station.station_id] = replace(status[station.station_id], **fields)
    return replace(snap, status=status)


class FakeServices:
    """Walks in straight lines at the planner's pace; rides straight at the bike's."""

    def __init__(
        self, no_walk_to: set[tuple[float, float]] | None = None, ride_speed_kmh=13.0
    ) -> None:
        self.walks: list[tuple[list[float], list[float]]] = []
        self.rides: list[tuple[list[float], list[float]]] = []
        self.no_walk_to = no_walk_to or set()
        self.ride_speed = ride_speed_kmh

    def walk(self, a, b):
        self.walks.append((a, b))
        if tuple(a) in self.no_walk_to or tuple(b) in self.no_walk_to:
            return None
        metres = bikeshare._distance(a, b) * 1.2
        return WalkLeg([a, b], metres, metres / (bikeshare.WALK_SPEED_KMH / 3.6))

    def ride(self, a, b):
        self.rides.append((a, b))
        metres = bikeshare._distance(a, b) * 1.3
        return {
            "preset": "bikeshare",
            "geometry": {"type": "LineString", "coordinates": [a, b]},
            "distance_m": metres,
            "duration_s": metres / (self.ride_speed / 3.6),
            "attribution": ["© OpenStreetMap contributors, ODbL"],
        }


def run(origin, dest, bike="classic", ending=ENDING_DOCK, snap=None, services=None):
    services = services or FakeServices(ride_speed_kmh=presets.BIKESHARE_BIKES[bike].speed_kmh)
    snap = snap or snapshot()
    body = bikeshare.plan(
        origin, dest, bike, ending, snap, services, presets.BIKESHARE_BIKES[bike].speed_kmh
    )
    return body, services


# --- The basic plan ---------------------------------------------------------------------------


def test_union_station_to_dupont_circle_on_a_classic_bike() -> None:
    body, services = run(UNION, DUPONT)
    plan = body["bikeshare"]
    assert plan["bike"] == "classic" and plan["ending"] == "dock"
    assert plan["start"]["name"] == "Columbus Circle / Union Station"
    assert plan["start"]["bikes_available"] == 12 and plan["start"]["availability"] == "known"
    assert plan["end"]["kind"] == "dock" and plan["end"]["docks_available"] > 0
    assert plan["walk_start"] and plan["walk_end"]
    # Walk + ride + walk, and the ride is the one planned dock to dock.
    assert services.rides == [
        ([COLUMBUS.lon, COLUMBUS.lat], [plan["end"]["lon"], plan["end"]["lat"]])
    ]
    assert plan["total_s"] == pytest.approx(plan["walk_s"] + plan["ride_s"], abs=0.2)
    assert [s["kind"] for s in plan["steps"]] == ["walk", "ride", "walk"]
    assert plan["availability"] == "live"


def test_the_steps_are_plain_words_with_us_units_first() -> None:
    plan = run(UNION, DUPONT)[0]["bikeshare"]
    first, second, third = (s["text"] for s in plan["steps"])
    assert first.startswith("Walk ") and " mi (" in first or " ft (" in first
    assert (
        "to the dock at Columbus Circle / Union Station, take a classic bike (12 available)."
        in first
    )
    assert second.startswith("Ride ") and " mi (" in second and "free slot" in second
    assert third.startswith("Return the bike, then walk ") and third.endswith(
        "to your destination."
    )
    assert plan["summary"].startswith("Bikeshare, classic bike: about ")
    for text in (first, second, third):
        assert "(" in text and ")" in text  # the metric figure, in brackets
        assert text.index("mi") < text.index("km") if " mi (" in text else True


def test_the_credit_is_in_the_plan_and_the_route_attribution() -> None:
    body = run(UNION, DUPONT)[0]
    assert body["bikeshare"]["credit"] == gbfs.CREDIT
    assert body["attribution"] == ["© OpenStreetMap contributors, ODbL", gbfs.CREDIT]


def test_the_credit_is_plain_factual_and_claims_no_affiliation() -> None:
    credit = gbfs.CREDIT
    assert credit == "Capital Bikeshare"  # the name alone (OWNER-DECISIONS 304)
    for implied in (
        "official",
        "partner",
        "endorse",
        "approved",
        "affiliat",
        "powered by",
        "in association",
    ):
        assert implied not in credit.lower()


def test_a_ride_starts_at_the_dock_when_the_start_is_there() -> None:
    plan = run([COLUMBUS.lon, COLUMBUS.lat], DUPONT)[0]["bikeshare"]
    assert plan["steps"][0]["text"].startswith(
        "Start at the dock at Columbus Circle / Union Station"
    )


# --- Availability and fallback ----------------------------------------------------------------


def test_a_dock_with_no_classic_bike_is_passed_over_with_a_note() -> None:
    snap = set_status(snapshot(), COLUMBUS, num_bikes=0) if False else snapshot()
    status = dict(snap.status)
    status[COLUMBUS.station_id] = replace(status[COLUMBUS.station_id], bikes=0, ebikes=0)
    snap = replace(snap, status=status)
    plan = run(UNION, DUPONT, snap=snap)[0]["bikeshare"]
    assert plan["start"]["name"] != "Columbus Circle / Union Station"
    assert any(
        n.startswith("The nearest dock, Columbus Circle / Union Station")
        and "has no classic bikes" in n
        for n in plan["notes"]
    )


def test_only_ebikes_at_a_dock_do_not_count_for_a_classic() -> None:
    status = dict(snapshot().status)
    status[COLUMBUS.station_id] = replace(status[COLUMBUS.station_id], bikes=5, ebikes=5)
    plan = run(UNION, DUPONT, snap=snapshot(status=status))[0]["bikeshare"]
    assert plan["start"]["name"] != "Columbus Circle / Union Station"
    plan = run(UNION, DUPONT, bike="ebike", snap=snapshot(status=status))[0]["bikeshare"]
    assert plan["start"]["name"] == "Columbus Circle / Union Station"
    assert plan["start"]["bikes_available"] == 5
    assert "take an e-bike (5 available)" in plan["steps"][0]["text"]


def test_a_dock_that_is_not_renting_is_passed_over() -> None:
    plan = run(UNION, DUPONT, snap=set_status(snapshot(), COLUMBUS, renting=False))[0]["bikeshare"]
    assert plan["start"]["name"] != "Columbus Circle / Union Station"
    assert any("is not renting bikes right now" in n for n in plan["notes"])


def test_a_full_dock_cannot_end_the_ride_and_the_next_nearest_is_used() -> None:
    dest = [-77.0487, 38.9094]  # beside 22nd & P St NW, which has 0 free slots in the sample
    plan = run(UNION, dest)[0]["bikeshare"]
    assert plan["end"]["name"] != "22nd & P ST NW"
    assert plan["end"]["docks_available"] > 0
    assert any("22nd & P ST NW" in n and "has no free slots right now" in n for n in plan["notes"])


def test_a_dock_that_is_not_taking_bikes_back_is_passed_over() -> None:
    dest = [DUPONT_SOUTH.lon, DUPONT_SOUTH.lat]
    plan = run(UNION, dest, snap=set_status(snapshot(), DUPONT_SOUTH, returning=False))[0][
        "bikeshare"
    ]
    assert plan["end"]["name"] != DUPONT_SOUTH.name
    assert any("is not taking bikes back right now" in n for n in plan["notes"])


def test_the_nearest_dock_is_not_always_the_best_start() -> None:
    """A dock a little farther but toward the destination can beat the nearest."""
    plan = run([-77.0103, 38.8980], DUPONT)[0]["bikeshare"]
    # North Capitol St & F St NW and New Jersey Ave & F St NW are both near; whichever
    # wins, the others are not chosen and the choice is the shorter walk plus ride.
    assert plan["start"]["name"] in {NJ_AVE.name, NORTH_CAP_F.name, COLUMBUS.name}


def test_with_no_availability_feed_the_nearest_docks_are_used_and_it_says_so() -> None:
    plan = run(UNION, DUPONT, snap=snapshot(status=None, failed=frozenset({"station_status"})))[0][
        "bikeshare"
    ]
    assert plan["availability"] == "unknown"
    assert plan["start"]["availability"] == "unknown" and plan["start"]["bikes_available"] is None
    assert plan["end"]["availability"] == "unknown"
    assert "(availability unknown)" in plan["steps"][0]["text"]
    assert "availability unknown" in plan["steps"][1]["text"]
    assert any("availability data could not be read" in n and "unknown" in n for n in plan["notes"])


def test_a_stale_snapshot_is_said_to_be() -> None:
    plan = run(UNION, DUPONT, snap=snapshot(stale=True))[0]["bikeshare"]
    assert plan["availability"] == "stale"
    assert any("did not answer just now" in n for n in plan["notes"])


def test_the_operators_alerts_are_passed_on_in_its_words() -> None:
    plan = run(UNION, DUPONT, snap=snapshot(alerts=["K St docks closed for repairs"]))[0][
        "bikeshare"
    ]
    assert "The operator reports: K St docks closed for repairs" in plan["notes"]


def test_no_dock_with_a_bike_in_reach_is_a_refusal_in_words() -> None:
    far = [-77.1, 38.99]
    with pytest.raises(NoBikeshare, match="No dock within .* of the start has a classic bike"):
        run(far, DUPONT)
    empty = {k: replace(v, bikes=0, ebikes=0) for k, v in snapshot().status.items()}
    with pytest.raises(NoBikeshare, match="classic bike right now"):
        run(UNION, DUPONT, snap=snapshot(status=empty))
    with pytest.raises(NoBikeshare, match="free slot"):
        run(
            UNION,
            DUPONT,
            snap=snapshot(status={k: replace(v, docks=0) for k, v in snapshot().status.items()}),
        )


def test_a_walk_that_cannot_be_made_drops_that_dock() -> None:
    services = FakeServices(no_walk_to={(COLUMBUS.lon, COLUMBUS.lat)})
    plan = run(UNION, DUPONT, services=services)[0]["bikeshare"]
    assert plan["start"]["name"] != "Columbus Circle / Union Station"


def test_no_walk_to_any_dock_is_a_refusal() -> None:
    services = FakeServices(no_walk_to={tuple(UNION)})
    with pytest.raises(NoBikeshare, match="no way on foot"):
        run(UNION, DUPONT, services=services)


def test_the_same_dock_at_both_ends_is_nothing_to_ride() -> None:
    # Two points beside the one dock, with nothing else near.
    only = [COLUMBUS]
    snap = snapshot(stations=only)
    with pytest.raises(NoBikeshare, match="nothing to ride"):
        run([COLUMBUS.lon + 0.0005, COLUMBUS.lat], [COLUMBUS.lon, COLUMBUS.lat + 0.0005], snap=snap)


def test_walking_is_said_to_be_as_quick_when_it_is() -> None:
    dest = [-77.0090, 38.8990]
    plan = run(UNION, dest)[0]["bikeshare"]
    assert any(
        n.startswith("Walking the whole way,") and "is as quick as this plan" in n
        for n in plan["notes"]
    )
    long_plan = run(UNION, DUPONT)[0]["bikeshare"]
    assert not any(n.startswith("Walking the whole way") for n in long_plan["notes"])


# --- Candidates are limited and real walks are asked only for a few ---------------------------


def test_only_the_nearest_few_docks_are_walked() -> None:
    services = FakeServices()
    run(UNION, DUPONT, services=services)
    # At most 3 start docks + 3 end docks + the direct walk.
    assert len(services.walks) <= bikeshare.START_DOCKS + bikeshare.END_DOCKS + 1
    assert len(services.rides) == 1


# --- E-bike: free-floating start (245) ---------------------------------------------


def free(lon: float, lat: float, n: int = 1) -> list[gbfs.FreeBike]:
    return [gbfs.FreeBike(f"b{n}", lon, lat)]


def test_an_ebike_may_start_at_a_free_floating_bike_when_the_walk_plus_ride_is_shorter() -> None:
    origin = [-77.0300, 38.9000]
    near = free(-77.0302, 38.9001)  # 25 m away; the nearest dock is far
    plan = run(origin, DUPONT, bike="ebike", snap=snapshot(free_bikes=near))[0]["bikeshare"]
    assert plan["start"]["kind"] == "free_bike"
    assert plan["start"]["name"] == "an e-bike outside a dock"
    assert plan["steps"][0]["text"].startswith("Walk ") or plan["steps"][0]["text"].startswith(
        "Walk"
    )
    assert "e-bike parked outside a dock" in plan["steps"][0]["text"]
    assert any("starts at an e-bike parked outside a dock" in n for n in plan["notes"])
    assert plan["walk_start"]["to"] == "an e-bike outside a dock"


def test_a_free_floating_bike_is_not_used_when_a_dock_is_the_shorter_choice() -> None:
    far_free = free(-77.0200, 38.9300)
    plan = run(UNION, DUPONT, bike="ebike", snap=snapshot(free_bikes=far_free))[0]["bikeshare"]
    assert plan["start"]["kind"] == "dock"


def test_a_classic_never_starts_at_a_free_floating_bike() -> None:
    origin = [-77.0300, 38.9000]
    plan = run(origin, DUPONT, bike="classic", snap=snapshot(free_bikes=free(-77.0302, 38.9001)))[
        0
    ]["bikeshare"]
    assert plan["start"]["kind"] == "dock"


def test_without_the_free_bike_feed_only_docks_are_considered_and_it_says_so() -> None:
    plan = run(
        UNION,
        DUPONT,
        bike="ebike",
        snap=snapshot(free_bikes=None, failed=frozenset({"free_bike_status"})),
    )[0]["bikeshare"]
    assert plan["start"]["kind"] == "dock"
    assert any("Free-floating e-bikes could not be checked" in n for n in plan["notes"])


# --- E-bike endings (244) ----------------------------------------------------------


def test_with_no_zone_data_only_a_dock_ending_is_offered() -> None:
    body, services = run(UNION, DUPONT, bike="ebike")
    plan = body["bikeshare"]
    kinds = {e["kind"]: e for e in plan["endings"]}
    assert kinds["dock"]["offered"] and kinds["dock"]["chosen"]
    assert (
        not kinds["outside_dock"]["offered"] and kinds["outside_dock"]["reason"] == "no_zone_data"
    )
    text = kinds["outside_dock"]["reason_text"]
    assert "no-parking zones aren't published" in text
    assert text.endswith("https://capitalbikeshare.com/how-it-works/ebike")
    assert plan["ending"] == "dock"


def test_an_outside_ending_asked_for_without_zone_data_falls_back_to_a_dock_with_a_note() -> None:
    body, services = run(UNION, DUPONT, bike="ebike", ending=ENDING_OUTSIDE)
    plan = body["bikeshare"]
    assert plan["ending"] == "dock" and plan["end"]["kind"] == "dock"
    assert any("isn't offered" in n and "The plan ends at a dock." in n for n in plan["notes"])
    assert services.rides[0][1] != DUPONT  # never the destination itself


def test_with_zones_the_destination_outside_a_dock_is_offered_with_its_fee_from_the_feed() -> None:
    zones = gbfs.parse_zones(
        {"data": {"geofencing_zones": {"type": "FeatureCollection", "features": []}}}
    )
    pricing = gbfs.parse_pricing(
        {
            "data": {
                "plans": [
                    {
                        "plan_id": "EBIKE_SINGLE_RIDE",
                        "name": "EBIKE SINGLE RIDE",
                        "price": "1.00",
                        "description": "$1.00 unlock",
                    },
                    {
                        "plan_id": "OUT_OF_DOCK",
                        "name": "Out-of-dock parking fee",
                        "price": "7.25",
                        "currency": "USD",
                        "description": "Leaving an e-bike outside a dock costs $7.25.",
                    },
                ]
            }
        }
    )
    snap = snapshot(zones=zones, pricing=pricing)
    body, services = run(UNION, DUPONT, bike="ebike", ending=ENDING_OUTSIDE, snap=snap)
    plan = body["bikeshare"]
    assert plan["ending"] == "outside_dock" and plan["end"]["kind"] == "outside_dock"
    assert plan["walk_end"] is None
    assert services.rides[0][1] == DUPONT  # the ride goes to the destination
    outside = next(e for e in plan["endings"] if e["kind"] == "outside_dock")
    assert outside["offered"] and outside["chosen"]
    # The fee is whatever the feed says, never a built-in figure.
    assert outside["fee"]["price"] == "7.25" and "7.25" in outside["fee_text"]
    assert any("leave the e-bike there, outside a dock" in s["text"] for s in plan["steps"])
    # And the dock ending is still on offer beside it.
    assert next(e for e in plan["endings"] if e["kind"] == "dock")["offered"]


def test_the_fee_is_never_hard_coded() -> None:
    zones = gbfs.parse_zones(
        {"data": {"geofencing_zones": {"type": "FeatureCollection", "features": []}}}
    )
    for price in ("3.10", "12.00"):
        pricing = gbfs.parse_pricing(
            {"data": {"plans": [{"plan_id": "x", "name": "Out of dock fee", "price": price}]}}
        )
        plan = run(UNION, DUPONT, bike="ebike", snap=snapshot(zones=zones, pricing=pricing))[0][
            "bikeshare"
        ]
        outside = next(e for e in plan["endings"] if e["kind"] == "outside_dock")
        assert outside["fee"]["price"] == price
    # And no money figure is written into the planner's own text.
    source = Path(bikeshare.__file__).read_text()
    assert "$" not in source
    for literal in ("0.15", "1.00", "2.00", "7.25"):
        assert literal not in source, literal


def test_with_zones_but_no_fee_plan_the_fee_is_said_to_be_unstated() -> None:
    zones = gbfs.parse_zones(
        {"data": {"geofencing_zones": {"type": "FeatureCollection", "features": []}}}
    )
    plan = run(UNION, DUPONT, bike="ebike", ending=ENDING_OUTSIDE, snap=snapshot(zones=zones))[0][
        "bikeshare"
    ]
    outside = next(e for e in plan["endings"] if e["kind"] == "outside_dock")
    assert outside["offered"] and outside["fee"] is None
    assert "does not state the out-of-dock fee" in outside["fee_text"]


def test_never_outside_a_dock_in_a_no_parking_zone() -> None:
    zones = gbfs.parse_zones(ZONE_ALL_SQUARE)
    dest = [-77.0436, 38.9096]  # inside the square
    assert zones is not None and not zones.allows_ending(*dest)
    body, services = run(
        UNION, dest, bike="ebike", ending=ENDING_OUTSIDE, snap=snapshot(zones=zones)
    )
    plan = body["bikeshare"]
    outside = next(e for e in plan["endings"] if e["kind"] == "outside_dock")
    assert not outside["offered"] and outside["reason"] == "no_parking_zone"
    assert plan["ending"] == "dock" and plan["end"]["kind"] == "dock"
    assert services.rides[0][1] != dest
    assert any("destination is in a zone" in n for n in plan["notes"])


def test_just_outside_the_zone_is_offered() -> None:
    zones = gbfs.parse_zones(ZONE_ALL_SQUARE)
    plan = run(UNION, [-77.0300, 38.9096], bike="ebike", snap=snapshot(zones=zones))[0]["bikeshare"]
    assert next(e for e in plan["endings"] if e["kind"] == "outside_dock")["offered"]


def test_zones_that_could_not_be_read_are_not_guessed() -> None:
    snap = snapshot(zones=None, failed=frozenset({"geofencing_zones"}), unlisted=frozenset())
    plan = run(UNION, DUPONT, bike="ebike", ending=ENDING_OUTSIDE, snap=snap)[0]["bikeshare"]
    outside = next(e for e in plan["endings"] if e["kind"] == "outside_dock")
    assert not outside["offered"] and outside["reason"] == "zones_unreadable"
    assert plan["ending"] == "dock"


def test_a_classic_bike_ends_at_a_dock_and_lists_no_outside_ending() -> None:
    zones = gbfs.parse_zones(
        {"data": {"geofencing_zones": {"type": "FeatureCollection", "features": []}}}
    )
    plan = run(UNION, DUPONT, bike="classic", ending=ENDING_OUTSIDE, snap=snapshot(zones=zones))[0][
        "bikeshare"
    ]
    assert plan["ending"] == "dock"
    assert [e["kind"] for e in plan["endings"]] == ["dock"]


def test_the_dock_ending_names_the_walk() -> None:
    plan = run(UNION, DUPONT, bike="ebike")[0]["bikeshare"]
    dock = next(e for e in plan["endings"] if e["kind"] == "dock")
    assert (
        dock["walk_m"]
        and "then walk" in dock["text"]
        and " mi (" in dock["text"]
        or " ft (" in dock["text"]
    )


def test_ebike_prices_are_shown_as_information_from_the_feed() -> None:
    plan = run(UNION, DUPONT, bike="ebike")[0]["bikeshare"]
    assert plan["pricing"] and plan["pricing"][0]["price"] == "1.00"
    assert plan["pricing_note"].startswith("Operator's price information: ")
    assert "not as a quote" in plan["pricing_note"]
    assert run(UNION, DUPONT, bike="classic")[0]["bikeshare"]["pricing_note"] is None


# --- Units and words --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metres", "words"),
    [
        (0, "0 ft (0 m)"),
        (30, "98 ft (30 m)"),
        (120, "390 ft (120 m)"),
        (320, "0.2 mi (0.3 km)"),
        (1609.344, "1.0 mi (1.6 km)"),
        (5000, "3.1 mi (5.0 km)"),
    ],
)
def test_distances_are_us_first_with_metric_in_brackets(metres, words) -> None:
    assert bikeshare.miles(metres) == words


def test_minutes() -> None:
    assert bikeshare.minutes(10) == "1 min" and bikeshare.minutes(600) == "10 min"


# --- Selection on a synthetic street: the pair is the least walk plus ride ------------
LAT0 = 38.9
M_PER_DEG_LON = 111_320 * 0.7784  # cos(38.9 degrees)


def east(metres: float, lat: float = LAT0) -> list[float]:
    """A point `metres` east of -77.0 on one parallel."""
    return [-77.0 + metres / M_PER_DEG_LON, lat]


def street(*docks, free=None, **changes) -> gbfs.Snapshot:
    """A snapshot of docks as (name, metres east, bikes, ebikes, free slots)."""
    stations, status = [], {}
    for index, (name, at, bikes, ebikes, slots) in enumerate(docks):
        lon, lat = east(at)
        stations.append(gbfs.Station(f"s{index}", name, lon, lat, 20))
        status[f"s{index}"] = gbfs.StationStatus(
            f"s{index}", bikes, ebikes, slots, True, True, True
        )
    return gbfs.Snapshot(
        fetched_at=0.0, stations=stations, status=status, free_bikes=free or [], pricing=[],
        zones=None, alerts=[], unlisted=frozenset({"geofencing_zones"}), **changes,
    )  # fmt: skip


def test_the_ride_is_weighed_in_choosing_the_start_dock() -> None:
    # Walking is slower than riding, but a start 150 m ahead saves 250 m of riding: the
    # nearer dock behind the rider (100 m) is not the better one.
    snap = street(("Behind", -100, 5, 0, 5), ("Ahead", 150, 5, 0, 5), ("Far end", 4000, 0, 0, 20))
    plan = run(east(0), east(4000), snap=snap)[0]["bikeshare"]
    assert plan["start"]["name"] == "Ahead"
    assert plan["end"]["name"] == "Far end"


def test_the_walk_to_the_destination_is_weighed_in_choosing_the_end_dock() -> None:
    # The dock 300 m short of the destination is the shorter ride, but the dock at the
    # destination saves 300 m of walking, which costs more than the ride saves.
    snap = street(("Start", 0, 5, 0, 5), ("Short", 3700, 0, 0, 5), ("At it", 4000, 0, 0, 5))
    plan = run(east(0), east(4000), snap=snap)[0]["bikeshare"]
    assert plan["end"]["name"] == "At it"


def test_no_dock_beyond_the_search_radius_is_offered() -> None:
    # Inside the box the docks are looked for in, but past 3 km: the origin is 4 km from both.
    far = [-77.005, 38.935]
    with pytest.raises(NoBikeshare, match="No dock within .* of the start"):
        run(far, DUPONT)
    with pytest.raises(NoBikeshare, match="No dock within .* of the destination"):
        run(UNION, far)
    snap = street(("Only", 0, 5, 0, 5), ("Other", 100, 0, 0, 5))
    with pytest.raises(NoBikeshare, match="of the start"):
        run(east(bikeshare.SEARCH_RADIUS_M + 500), east(0), snap=snap)
    with pytest.raises(NoBikeshare, match="of the destination"):
        run(east(0), east(bikeshare.SEARCH_RADIUS_M + 500), snap=snap)


def test_a_free_floating_bike_beyond_the_search_radius_is_not_offered() -> None:
    # The dock at the rider has no e-bike; the only e-bike is 3.6 km away, past the radius.
    far = free(*east(bikeshare.SEARCH_RADIUS_M + 600))
    snap = street(("No e-bikes", 0, 5, 0, 5), ("Goal", 3600, 0, 0, 20), free=far)
    with pytest.raises(NoBikeshare, match="e-bike right now"):
        run(east(0), east(3600), bike="ebike", snap=snap)


def test_the_nearest_free_floating_bikes_are_the_ones_considered() -> None:
    near = [
        gbfs.FreeBike("a", *east(60)),
        gbfs.FreeBike("b", *east(2500)),
        gbfs.FreeBike("c", *east(2600)),
    ]
    snap = street(("Nowhere", 0, 0, 0, 5), ("Goal", 4000, 0, 0, 20), free=near)
    plan = run(east(0), east(4000), bike="ebike", snap=snap)[0]["bikeshare"]
    assert plan["start"]["kind"] == "free_bike"
    assert plan["start"]["lon"] == pytest.approx(east(60)[0], abs=1e-5)


def test_a_dock_ending_asked_for_is_not_changed_to_outside_where_zones_allow_it() -> None:
    zones = gbfs.parse_zones(
        {"data": {"geofencing_zones": {"type": "FeatureCollection", "features": []}}}
    )
    body, services = run(
        UNION, DUPONT, bike="ebike", ending=ENDING_DOCK, snap=snapshot(zones=zones)
    )
    plan = body["bikeshare"]
    assert plan["ending"] == "dock" and plan["end"]["kind"] == "dock"
    assert services.rides[0][1] != DUPONT
    outside = next(e for e in plan["endings"] if e["kind"] == "outside_dock")
    assert outside["offered"] and not outside["chosen"]
