"""Flashing beacons the map has as signals (the owner, 2026-10-20, Connecticut Ave and
Baltimore St, Kensington: "a traffic light that's a blinking red against free flowing
traffic. It wasn't passable").

The pure half (`routemaker.intersections.with_beacons`) prices such a junction with no
signal; MDOT SHA's beacons are read by `pipeline.agency_signals.mdot_sha_beacons`; the
rows are loaded by `manage.py load_flashing_signals` and read at plan time by
`core.flashing_signals`.
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from pipeline import agency_signals
from routemaker import describe
from routemaker import intersections as m
from routemaker.intersections import Beacon, Control, Junction, Movement, Road

ROOT = Path(__file__).resolve().parents[1]
# The beacon's point as MDOT SHA has it (OBJECTID 3035).
LON, LAT = -77.0759572, 39.0243093
CONNECTICUT = Road(4, speed_mph=35, lanes=3, names=frozenset({"connecticut avenue"}))
BALTIMORE = Road(2, names=frozenset({"baltimore street"}))
BEACON = Beacon(1, LON, LAT)
# About 11 m (36 ft), 25 m (82 ft) and 41 m (134 ft) east of the beacon.
NEAR_LON = LON + 0.000128
OTHER_NODE_LON = LON + 0.00029
FAR_LON = LON + 0.000475


def crossing(lon: float = LON, control: Control = Control.SIGNAL, **fields) -> Junction:
    """The rider on Baltimore St crossing Connecticut Ave straight over."""
    base = {
        "m": 100.0,
        "lon": lon,
        "lat": LAT,
        "movement": Movement.STRAIGHT,
        "incoming": BALTIMORE,
        "outgoing": BALTIMORE,
        "crossed": (CONNECTICUT,),
        "control": control,
    }
    return Junction(**(base | fields))


class TestPricing:
    def test_a_signal_at_a_beacon_is_priced_as_the_stopped_side_of_an_lts4_road(self) -> None:
        signalised = m.assess(crossing())
        (beaconed,) = m.with_beacons([crossing()], [BEACON])
        event = m.assess(beaconed)
        assert beaconed.control is Control.NONE and beaconed.beacon
        assert signalised.cost_ft == pytest.approx(600.0)
        # The stopped side's LTS 4 crossing, scaled by the road (3 lanes, 35 mph): far
        # above the signal's 600 ft and the "Hard" rating's 4,000 ft.
        assert event.cost_ft == pytest.approx(
            m.crossing_ft(CONNECTICUT, Control.NONE, BALTIMORE.level)
        )
        assert event.cost_ft > m.STOPPED_CROSSING_FT[4]
        assert event.severity == m.RED and event.flagged
        assert event.beacon
        assert event.reason.endswith("flashing light, not a signal")

    def test_rush_hour_costs_more_at_a_beacon_and_nothing_more_at_a_signal(self) -> None:
        (beaconed,) = m.with_beacons([crossing()], [BEACON])
        off_peak = m.assess(beaconed, when=None).cost_ft
        rush = m.assess(beaconed, when="weekday_rush").cost_ft
        assert rush > off_peak

    def test_riding_along_the_main_road_keeps_its_priority(self) -> None:
        # Flashing yellow on Connecticut Ave: the side street stops, not the rider.
        along = crossing(incoming=CONNECTICUT, outgoing=CONNECTICUT, crossed=(BALTIMORE,))
        (beaconed,) = m.with_beacons([along], [BEACON])
        assert m.assess(beaconed) is None

    def test_a_signal_beyond_reach_of_the_beacon_stays_a_signal(self) -> None:
        near, far = m.with_beacons(
            [crossing(lon=NEAR_LON), crossing(lon=FAR_LON, m=200.0)], [BEACON]
        )
        assert near.control is Control.NONE and near.beacon
        assert far.control is Control.SIGNAL and not far.beacon

    def test_a_junction_with_no_signal_is_left_as_it_is(self) -> None:
        stop = crossing(control=Control.STOP)
        assert m.with_beacons([stop], [BEACON]) == [stop]

    def test_a_neighbouring_node_does_not_lend_the_beacon_junction_its_signal(self) -> None:
        # A divided road's other carriageway node, 30 m on and outside the beacon's reach,
        # still carries the map's signal flag: it is the same beacon, not a signal.
        one_way = Road(
            4, speed_mph=35, lanes=3, oneway=True, names=CONNECTICUT.names, ways=frozenset({1})
        )
        other_way = replace(one_way, ways=frozenset({2}))
        first = crossing(crossed=(one_way,))
        second = crossing(lon=OTHER_NODE_LON, m=125.0, crossed=(other_way,))
        shared = m.share_controls(m.with_beacons([first, second], [BEACON]))
        assert [j.control for j in shared] == [Control.NONE, Control.NONE]
        # And a node beyond reach keeps its signal and lends it to no beacon node.
        third = crossing(lon=FAR_LON, m=141.0, crossed=(other_way,))
        shared = m.share_controls(m.with_beacons([first, third], [BEACON]))
        assert [j.control for j in shared] == [Control.NONE, Control.SIGNAL]

    def test_the_signs_still_count_once_the_signal_is_read_as_nothing(self) -> None:
        (beaconed,) = m.with_beacons([crossing()], [BEACON], [Control.STOP])
        event = m.assess(beaconed)
        assert beaconed.control is Control.STOP and beaconed.beacon
        assert event.reason.endswith("stop sign on your side, flashing light, not a signal")

    def test_no_beacons_changes_nothing(self) -> None:
        assert m.with_beacons([crossing()], []) == [crossing()]

    def test_beacons_near_keeps_only_those_in_reach_of_the_route(self) -> None:
        far_off = Beacon(2, LON + 0.05, LAT)
        assert m.beacons_near([(NEAR_LON, LAT)], [BEACON, far_off]) == [BEACON]
        assert m.beacons_near([], [BEACON]) == []


class TestRideCue:
    def test_the_cue_says_flashing_light_not_no_signal_mapped(self) -> None:
        assert describe._control_words(Control.NONE, True, True) == ", flashing light, not a signal"
        assert describe._control_words(Control.NONE, True, False) == ", no signal mapped"
        assert describe._control_words(Control.NONE, False, True) == ""
        assert describe._control_words(Control.STOP, True, True) == (
            " at a stop sign, flashing light, not a signal"
        )


def feature(objectid: int, tcd: str, lon: float, lat: float, owner: str = "County") -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "OBJECTID": objectid,
            "SIGNAL_ID": f"sig{objectid}",
            "TCD_Type": tcd,
            "OWNER_DESC": owner,
            "MR_ROAD_NAME": "CONNECTICUT AVE",
            "SR_ROAD_NAME": "BALTIMORE ST (MB)",
        },
    }


class TestMdotBeacons:
    def test_junction_beacons_are_read_and_everything_else_left_out(self) -> None:
        doc = {
            "features": [
                feature(1, "3", LON, LAT),
                feature(2, "2", LON + 0.01, LAT),
                feature(3, "1", LON + 0.02, LAT),
                feature(4, "F", LON + 0.03, LAT),  # a school warning beacon's own code
                feature(5, "3", LON + 0.04, LAT, owner="Proposed"),
            ]
        }
        out = agency_signals.mdot_sha_beacons(doc)
        assert out["version"] == 1 and out["source"] == "mdot-sha"
        # The Intersection Control Beacon may be an all-way stop: counted and left out.
        assert [r["id"] for r in out["rows"]] == ["mdot-sha:sig1"]
        first = out["rows"][0]
        assert first["name"] == "Connecticut Ave and Baltimore St (MB)"
        assert (first["lon"], first["lat"]) == (LON, LAT)
        assert "Warning Beacon" in first["evidence"]
        assert out["dropped"] == {
            "OWNER_DESC Proposed": 1,
            "an Intersection Control Beacon (may be an all-way stop)": 1,
        }

    def test_a_beacon_at_a_junction_with_a_signal_too_is_left_out(self) -> None:
        signals = [
            {
                "id": "mdot-sha:x",
                "source": "mdot-sha",
                "lon": NEAR_LON,
                "lat": LAT,
                "kind": "signal",
            }
        ]
        out = agency_signals.mdot_sha_beacons({"features": [feature(1, "3", LON, LAT)]}, signals)
        assert out["rows"] == []
        assert out["dropped"] == {"a signal at the same junction": 1}

    def test_the_owner_file_and_the_beacon_agree_on_the_point(self) -> None:
        owner = json.loads(
            (
                ROOT / "fixtures/flashing-signals/2026-10-20-owner-connecticut-baltimore.json"
            ).read_text()
        )
        (row,) = owner["rows"]
        assert m.beacon_at(row["lon"], row["lat"], [BEACON]) is BEACON


# --- The loader and the plan-time read -------------------------------------------------


@pytest.fixture
def admin(db):
    from core.models import User

    return User.objects.create(discord_user_id=881201, is_instance_admin=True)


def load(document: dict, *args: str) -> str:
    out = io.StringIO()
    old, sys.stdin = sys.stdin, io.StringIO(json.dumps(document))
    try:
        call_command("load_flashing_signals", "-", *args, stdout=out)
    finally:
        sys.stdin = old
    return out.getvalue()


def agency(*ids: str) -> dict:
    return {
        "version": 1,
        "source": "mdot-sha",
        "rows": [
            {
                "id": key,
                "name": f"Junction {key}",
                "lon": LON + i * 0.01,
                "lat": LAT,
                "evidence": "e",
            }
            for i, key in enumerate(ids)
        ],
    }


@pytest.mark.django_db
class TestLoader:
    def test_a_dry_run_writes_nothing(self, admin) -> None:
        from core.models import FlashingSignal

        said = load(agency("mdot-sha:a"), "--actor", "881201")
        assert "create: mdot-sha:a" in said and "dry run" in said
        assert not FlashingSignal.objects.exists()

    def test_the_owner_file_loads_and_is_read_at_plan_time(self, admin) -> None:
        from core import flashing_signals
        from core.models import AuditLogEntry, FlashingSignal

        owner = json.loads(
            (
                ROOT / "fixtures/flashing-signals/2026-10-20-owner-connecticut-baltimore.json"
            ).read_text()
        )
        load(owner, "--actor", "881201", "--confirm")
        row = FlashingSignal.objects.get()
        assert row.source == "owner" and row.active
        assert AuditLogEntry.objects.filter(model="flashingsignal", action="add").count() == 1
        (beacon,) = flashing_signals.active()
        assert (beacon.lon, beacon.lat) == pytest.approx((LON, LAT))
        # Loading it again changes nothing.
        assert "owner, 1 present" in load(owner, "--actor", "881201", "--confirm")
        assert FlashingSignal.objects.count() == 1

    def test_an_agency_reload_retires_what_left_its_list_and_never_touches_owner_rows(
        self, admin
    ) -> None:
        from core import flashing_signals
        from core.models import FlashingSignal

        owner = {
            "version": 1,
            "source": "owner",
            "rows": [{"id": "mine", "name": "Mine", "lon": LON, "lat": LAT + 0.01}],
        }
        load(owner, "--actor", "881201", "--confirm")
        load(agency("mdot-sha:a", "mdot-sha:b"), "--actor", "881201", "--confirm")
        assert len(flashing_signals.active()) == 3
        said = load(agency("mdot-sha:a"), "--actor", "881201", "--confirm")
        assert "retire: mdot-sha:b" in said
        assert set(
            FlashingSignal.objects.filter(active=True).values_list("source_id", flat=True)
        ) == {
            "mine",
            "mdot-sha:a",
        }
        assert len(flashing_signals.active()) == 2

    def test_a_row_an_admin_withdrew_stays_withdrawn(self, admin, rf) -> None:
        from core import flashing_signals
        from core.admin import FlashingSignalAdmin, site
        from core.models import AuditLogEntry, FlashingSignal

        load(agency("mdot-sha:a"), "--actor", "881201", "--confirm")
        assert len(flashing_signals.active()) == 1
        request = rf.post("/")
        request.user = admin
        model_admin = FlashingSignalAdmin(FlashingSignal, site)
        model_admin.message_user = lambda *args, **kwargs: None
        model_admin.withdraw_selected(request, FlashingSignal.objects.all())
        assert FlashingSignal.objects.get().withdrawn_by == "admin"
        assert AuditLogEntry.objects.filter(model="flashingsignal", action="withdraw").exists()
        assert flashing_signals.active() == ()
        said = load(agency("mdot-sha:a"), "--actor", "881201", "--confirm")
        assert "withdrawn: mdot-sha:a" in said
        assert not FlashingSignal.objects.filter(active=True).exists()

    def test_a_beacon_back_on_the_list_is_restored(self, admin) -> None:
        from core import flashing_signals

        load(agency("mdot-sha:a"), "--actor", "881201", "--confirm")
        load(agency(), "--actor", "881201", "--confirm")
        assert flashing_signals.active() == ()
        said = load(agency("mdot-sha:a"), "--actor", "881201", "--confirm")
        assert "restore: mdot-sha:a" in said
        assert len(flashing_signals.active()) == 1

    def test_a_moved_point_is_updated_and_seen_by_the_next_plan(self, admin) -> None:
        from core import flashing_signals

        load(agency("mdot-sha:a"), "--actor", "881201", "--confirm")
        assert flashing_signals.active()[0].lon == pytest.approx(LON)
        moved = agency("mdot-sha:a")
        moved["rows"][0]["lon"] = LON + 0.001
        assert "update: mdot-sha:a" in load(moved, "--actor", "881201", "--confirm")
        assert flashing_signals.active()[0].lon == pytest.approx(LON + 0.001)

    def test_only_an_instance_admin_may_load(self, db) -> None:
        from core.models import User

        User.objects.create(discord_user_id=881202, is_instance_admin=False)
        with pytest.raises(CommandError, match="not an active instance admin"):
            load(agency("mdot-sha:a"), "--actor", "881202", "--confirm")

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"source": "osm"}, "source must be"),
            ({"rows": [{"id": "a", "name": "A", "lon": 500, "lat": LAT}]}, "lon must be"),
            ({"rows": [{"id": "a", "name": "", "lon": LON, "lat": LAT}]}, "name must be"),
            (
                {"rows": [{"id": "a", "name": "A", "lon": LON, "lat": LAT}] * 2},
                "appears twice",
            ),
        ],
    )
    def test_a_malformed_file_is_refused(self, admin, change, message) -> None:
        with pytest.raises(CommandError, match=message):
            load(agency("mdot-sha:a") | change, "--actor", "881201")
