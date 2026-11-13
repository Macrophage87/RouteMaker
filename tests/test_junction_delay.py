"""The time a rider loses at junctions (`routemaker.junction_delay`)."""

from __future__ import annotations

import math

import pytest

from core import presets
from routemaker import intersections as m
from routemaker import junction_delay as d
from routemaker import trace_junctions as t
from routemaker.intersections import Beacon, Control, Junction, Movement, Road, beacon_at

SHAPE = [(-77.0 + i * 0.001, 38.9) for i in range(12)]


def junction(
    *others: tuple[str, str],
    m: float = 100.0,
    movement: Movement = Movement.STRAIGHT,
    in_class: str = "residential",
    out_class: str = "residential",
    in_use: str = "road",
    out_use: str = "road",
    in_way: int = 1,
    out_way: int = 1,
    signal: bool = False,
    headings: tuple[float, ...] | None = None,
) -> t.RawJunction:
    """A junction with the other edges at the node as (use, road class) pairs, heading
    east (90 degrees) into it; `headings`: those edges' headings away from the node."""
    return t.RawJunction(
        m=m,
        lon=-77.0,
        lat=38.9,
        in_edge_id=None,
        in_way=in_way,
        out_way=out_way,
        movement=movement,
        in_use=in_use,
        out_use=out_use,
        others=tuple((use, False) for use, _cls in others),
        in_class=in_class,
        out_class=out_class,
        other_classes=tuple(cls for _use, cls in others),
        signal=signal,
        in_heading=90.0,
        other_headings=headings if headings is not None else (),
    )


CROSS_STREET = (("road", "residential"), ("road", "residential"))
# Giving way to a primary road the junction model has not read: the typical primary's wait
# (`junction_delay.TYPICAL_BIG_ROAD`), off-peak.
PRIMARY_GIVE_WAY_S = 13.8


@pytest.fixture(autouse=True)
def buttons_priced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most of these tests pin the beg-button rule, which is kept but switched off since
    the owner's word of 2026-11-10 (`junction_delay.BUTTONS_PRICED`): it is switched on
    here so the kept rule stays right. `TestButtonsOff` checks what the planner does now."""
    monkeypatch.setattr(d, "BUTTONS_PRICED", True)


class TestOneJunction:
    def test_a_crosswalk_over_a_slip_lane_waits_for_a_gap(self) -> None:
        """The owner, 2026-10-21: riders take an LTS 4 road over a sidewalk, "especially
        with sliplanes". A last-resort sidewalk's crosswalk over a slip lane (Valhalla's
        turn channel, at its road's class) gives way to it."""
        slip = (("turn_channel", "secondary"), ("turn_channel", "secondary"))
        crossing = junction(
            *slip,
            in_class="service_other",
            out_class="service_other",
            in_use="pedestrian_crossing",
            out_use="pedestrian_crossing",
        )
        assert d.delay_at(crossing) == d.GIVE_WAY_DELAY_S[d.ROAD_RANK["secondary"]]

    def test_a_neighbourhood_crossing_is_a_full_stop(self) -> None:
        assert d.delay_at(junction(*CROSS_STREET)) == d.STOP_DELAY_S

    def test_the_busier_the_road_given_way_to_the_longer_the_wait(self) -> None:
        waits = [
            d.delay_at(junction(("road", cls), ("road", cls)))
            for cls in ("residential", "tertiary", "secondary", "primary")
        ]
        assert waits == sorted(waits)
        assert waits[0] == d.STOP_DELAY_S < waits[1] < waits[2] < waits[3]

    def test_a_signal_is_the_signal_wait(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        assert d.delay_at(junction(*busy, signal=True)) == d.SIGNAL_DELAY_S

    def test_a_flashing_beacon_mapped_as_a_signal_is_a_stop(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        assert d.delay_at(junction(*busy, signal=True), beacon=True) == d.GIVE_WAY_DELAY_S[2]

    def test_the_rider_on_the_busier_road_does_not_stop(self) -> None:
        assert d.delay_at(junction(*CROSS_STREET, in_class="tertiary", out_class="tertiary")) == 0

    def test_a_side_road_from_one_side_does_not_stop_the_rider(self) -> None:
        assert d.delay_at(junction(("road", "residential"))) == 0

    def test_a_street_split_into_two_ways_with_nothing_crossing_is_free(self) -> None:
        assert d.delay_at(junction(in_way=1, out_way=2)) == 0

    def test_driveways_and_alleys_cost_nothing(self) -> None:
        others = (("driveway", "service_other"), ("road", "service_other"))
        assert d.delay_at(junction(*others)) == 0

    def test_a_trail_crossing_a_road_gives_way(self) -> None:
        trail = {"in_use": "cycleway", "out_use": "cycleway"}
        trail |= {"in_class": "service_other", "out_class": "service_other"}
        assert d.delay_at(junction(*CROSS_STREET, **trail)) == d.STOP_DELAY_S

    def test_a_trail_meeting_another_trail_is_free(self) -> None:
        trail = {"in_use": "cycleway", "out_use": "cycleway"}
        trail |= {"in_class": "service_other", "out_class": "service_other"}
        assert d.delay_at(junction(("cycleway", "service_other"), **trail)) == 0

    def test_a_trail_coming_out_onto_a_street_gives_way(self) -> None:
        out = {"in_use": "cycleway", "in_class": "service_other"}
        assert d.delay_at(junction(movement=Movement.RIGHT, out_way=2, **out)) == d.STOP_DELAY_S

    def test_turning_onto_a_busier_road_gives_way(self) -> None:
        turn = {"movement": Movement.LEFT, "out_way": 2, "out_class": "secondary"}
        assert d.delay_at(junction(("road", "secondary"), **turn)) == d.GIVE_WAY_DELAY_S[3]

    def test_turning_off_a_through_street_at_a_t_is_free(self) -> None:
        # Own street goes on ahead (east); the rider turns left onto a side street.
        turn = {"movement": Movement.LEFT, "out_way": 2}
        assert d.delay_at(junction(("road", "residential"), headings=(92.0,), **turn)) == 0

    def test_turning_at_the_end_of_a_street_gives_way(self) -> None:
        # Own street ends at the T: the cross street's other half leaves to the south.
        turn = {"movement": Movement.LEFT, "out_way": 2}
        found = junction(("road", "residential"), headings=(180.0,), **turn)
        assert d.delay_at(found) == d.STOP_DELAY_S

    def test_turning_at_a_crossroads_gives_way(self) -> None:
        turn = {"movement": Movement.LEFT, "out_way": 2}
        found = junction(*CROSS_STREET, headings=(90.0, 180.0), **turn)
        assert d.delay_at(found) == d.STOP_DELAY_S

    def test_turning_off_onto_a_quieter_street_is_free(self) -> None:
        turn = {"movement": Movement.RIGHT, "out_way": 2, "in_class": "secondary"}
        assert d.delay_at(junction(("road", "secondary"), **turn)) == 0


class TestWholeRoute:
    def test_junctions_add_up(self) -> None:
        stops = [junction(*CROSS_STREET, m=100.0 * i) for i in range(1, 6)]
        assert d.delay_s(stops) == pytest.approx(5 * d.STOP_SIGN_S)

    def test_a_divided_road_is_crossed_as_one_stop_at_its_dearest(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        near = [junction(*busy, m=100.0), junction(*busy, m=118.0, signal=True)]
        # The signal's time shown, a city's big road with the ride-time setting not known.
        assert d.delay_s(near) == d.CITY_PASS_S[None][0]

    def test_a_stop_sign_is_one_figure_everywhere(self) -> None:
        """Before 2026-11-13: 8 s, and 4 s where a stop may be rolled (the District). Now
        one figure everywhere, what riders weigh a stop sign at (Broach et al. 2012), and
        no test of where the rider is."""
        stops = [junction(*CROSS_STREET, m=100.0), junction(*CROSS_STREET, m=300.0)]
        assert d.delay_s(stops) == 2 * d.STOP_SIGN_S == 6.0
        assert not hasattr(d, "YIELD_DELAY_S")

    def test_the_beacon_test_is_asked_only_at_signals(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        stops = [junction(*busy, m=100.0, signal=True), junction(*CROSS_STREET, m=300.0)]
        asked = []

        def beacon(lon: float, lat: float) -> bool:
            asked.append((lon, lat))
            return True

        assert d.delay_s(stops, beacon=beacon) == PRIMARY_GIVE_WAY_S + d.STOP_SIGN_S
        assert len(asked) == 1

    def test_a_known_beacon_on_the_list_prices_the_signal_as_a_stop(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        at_beacon = [junction(*busy, m=100.0, signal=True)]
        beacons = (Beacon(id=1, lon=-77.0001, lat=38.9),)
        near = d.delay_s(
            at_beacon, beacon=lambda lon, lat: beacon_at(lon, lat, beacons) is not None
        )
        far = (Beacon(id=2, lon=-77.01, lat=38.9),)
        away = d.delay_s(at_beacon, beacon=lambda lon, lat: beacon_at(lon, lat, far) is not None)
        assert (near, away) == (PRIMARY_GIVE_WAY_S, d.CITY_PASS_S[None][0])

    def test_driveways_between_stops_do_not_merge_them(self) -> None:
        driveway = (("driveway", "service_other"),)
        route = []
        for block in range(4):
            route.append(junction(*CROSS_STREET, m=100.0 * block))
            route += [junction(*driveway, m=100.0 * block + k) for k in range(20, 100, 20)]
        assert d.delay_s(route) == pytest.approx(4 * d.STOP_SIGN_S)

    def test_no_junctions_no_delay(self) -> None:
        assert d.delay_s([]) == 0

    def test_a_signal_the_junction_model_reads_up_the_roads_arms_is_a_signal_wait(self) -> None:
        """Hunt J5: a trail crossing an arterial at a junction whose signal is on the
        road's stop lines, not on the rider's own approach. The trace shows no signal, and
        it was a 30 s give-way where the junction model (`core.junctions`) priced it as
        signalised; given the model's signals, it is the signal's wait."""
        busy = (("road", "primary"), ("road", "primary"))
        trail = junction(
            *busy, in_use="cycleway", out_use="cycleway", in_class=None, out_class=None
        )
        assert d.delay_s([trail]) == PRIMARY_GIVE_WAY_S
        shown = d.CITY_PASS_S[None][0]
        assert d.delay_s([trail], signals={(-77.0, 38.9)}) == shown
        assert d.delay_runs([trail], signals={(-77.0, 38.9)}) == [(100.0, shown)]
        # Another junction's signal is not this one's.
        assert d.delay_s([trail], signals={(-77.001, 38.9)}) == PRIMARY_GIVE_WAY_S

    def test_a_known_beacon_is_still_a_stop_where_the_model_reads_a_signal(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        here = [junction(*busy)]
        assert (
            d.delay_s(here, beacon=lambda lon, lat: True, signals={(-77.0, 38.9)})
            == PRIMARY_GIVE_WAY_S
        )


def edge(way, begin, end, length_km, **fields):
    return {
        "way_id": way,
        "begin_shape_index": begin,
        "end_shape_index": end,
        "length": length_km,
        "begin_heading": 90,
        "end_heading": 90,
        "road_class": "residential",
        "use": "road",
        **fields,
    }


class TestSignalFromTheTrace:
    def test_a_signal_on_the_node(self) -> None:
        first = edge(1, 0, 2, 0.1)
        first["end_node"] = {
            "traffic_signal": True,
            "intersecting_edges": [{"use": "road", "road_class": "primary"}],
        }
        (found,) = t.junctions_of_trace({"edges": [first, edge(1, 2, 4, 0.1)]}, SHAPE)
        assert found.signal

    def test_a_signal_on_the_stop_line_before_the_junction(self) -> None:
        approach = edge(1, 0, 2, 0.1, traffic_signal=True)
        last = edge(1, 2, 3, 0.012)
        last["end_node"] = {"intersecting_edges": [{"use": "road", "road_class": "primary"}]}
        trace = {"edges": [approach, last, edge(1, 3, 5, 0.1)]}
        (found,) = t.junctions_of_trace(trace, SHAPE)
        assert found.signal

    def test_a_signal_a_block_back_is_not_this_junctions(self) -> None:
        approach = edge(1, 0, 2, 0.1, traffic_signal=True)
        last = edge(1, 2, 3, 0.1)
        last["end_node"] = {"intersecting_edges": [{"use": "road", "road_class": "primary"}]}
        trace = {"edges": [approach, last, edge(1, 3, 5, 0.1)]}
        (found,) = t.junctions_of_trace(trace, SHAPE)
        assert not found.signal

    def test_the_other_directions_stop_line_past_a_signal_is_not_the_next_junctions(
        self,
    ) -> None:
        """Hunt J2-1: a signalised crossroads, 15 m past it the stop line for the other
        direction (`highway=traffic_signals` with no direction, so the node flag), and 25 m
        on a residential T: before, the T read the passed stop line as its own signal and
        was timed as a second signal (15 s shown, 60 ranked); after, it costs nothing."""
        crossroads = edge(1, 0, 2, 0.1, road_class="secondary")
        crossroads["end_node"] = {
            "traffic_signal": True,
            "intersecting_edges": [
                {"use": "road", "road_class": "primary", "begin_heading": 0},
                {"use": "road", "road_class": "primary", "begin_heading": 180},
            ],
        }
        stop_line = edge(1, 2, 3, 0.015, road_class="secondary")
        stop_line["end_node"] = {"traffic_signal": True, "intersecting_edges": []}
        to_t = edge(1, 3, 5, 0.025, road_class="secondary")
        to_t["end_node"] = {
            "intersecting_edges": [{"use": "road", "road_class": "residential", "begin_heading": 0}]
        }
        trace = {"edges": [crossroads, stop_line, to_t, edge(1, 5, 8, 0.1)]}
        found = t.junctions_of_trace(trace, SHAPE)
        assert [j.signal for j in found] == [True, False]
        (only,) = d.waits(found, suburban=everywhere)
        assert only.m == pytest.approx(100.0)

    def test_a_signal_on_the_junction_behind_is_that_junctions(self) -> None:
        """A driveway 20 m past a signalised crossroads (or the next junction) reads no
        signal of its own from the crossroads' node: that junction's."""
        crossroads = edge(1, 0, 2, 0.1)
        crossroads["end_node"] = {
            "traffic_signal": True,
            "intersecting_edges": [{"use": "road", "road_class": "primary"}],
        }
        driveway = edge(1, 2, 3, 0.02)
        driveway["end_node"] = {
            "intersecting_edges": [{"use": "driveway", "road_class": "service_other"}]
        }
        trace = {"edges": [crossroads, driveway, edge(1, 3, 5, 0.1)]}
        assert [j.signal for j in t.junctions_of_trace(trace, SHAPE)] == [True, False]

    def test_the_riders_own_stop_line_nearer_this_junction_is_still_its_own(self) -> None:
        """A stop line 12 m before the junction and 40 m past the last one: this one's."""
        earlier = edge(1, 0, 2, 0.1)
        earlier["end_node"] = {"intersecting_edges": [{"use": "road", "road_class": "residential"}]}
        to_line = edge(1, 2, 3, 0.04)
        to_line["end_node"] = {"traffic_signal": True, "intersecting_edges": []}
        last = edge(1, 3, 4, 0.012)
        last["end_node"] = {"intersecting_edges": [{"use": "road", "road_class": "primary"}]}
        trace = {"edges": [earlier, to_line, last, edge(1, 4, 6, 0.1)]}
        assert [j.signal for j in t.junctions_of_trace(trace, SHAPE)] == [False, True]


# --- Signals outside the major cities, and beg buttons (the owner, 2026-11-08) -----------

PRIMARY = (("road", "primary"), ("road", "primary"))
SECONDARY = (("road", "secondary"), ("road", "secondary"))


def suburban_signal(*others, **fields) -> t.RawJunction:
    return junction(*others, signal=True, **fields)


def everywhere(_lon: float, _lat: float) -> bool:
    return True


class TestSuburbanSignals:
    """The owner's rides: a red at a big suburban crossing held the rider a median
    66 s (16 stops) against 19 s on the cities' grids (4). He chose 45 s across a big road,
    30 s at any other suburban signal (no 15 s signal outside the cities: "30 is probably
    more realistic"), and twice those in the ranking."""

    def test_a_dc_signal_at_a_big_road_is_30_s_shown_and_ranked_once(self) -> None:
        crossing = suburban_signal(*PRIMARY)
        wait = d.signal_wait(crossing, suburban=False)
        assert (wait.red_s, wait.ranked_s, wait.button) == (30.0, 30.0, False)
        (run,) = d.waits([crossing], suburban=lambda _lon, _lat: False)
        assert (run.red_s, run.ranked_s) == (d.CITY_BIG_SIGNAL_S, d.CITY_BIG_SIGNAL_S)

    def test_a_dc_signal_at_a_secondary_road_is_15_s_and_at_a_side_street_20_s(self) -> None:
        """The owner's city rides: a secondary road's signals were the quickest."""
        secondary = suburban_signal(
            ("road", "secondary"),
            ("road", "secondary"),
            in_class="residential",
            out_class="residential",
        )
        side = suburban_signal(
            ("road", "residential"),
            ("road", "residential"),
            in_class="residential",
            out_class="residential",
        )
        assert d.signal_wait(secondary, suburban=False).red_s == 15.0
        assert d.signal_wait(side, suburban=False).red_s == 20.0
        # A big road the junction model reads by its lanes or speed counts as big.
        assert d.signal_wait(side, suburban=False, big=True).red_s == 30.0

    def test_before_and_after_a_suburban_big_crossing_is_45_s_at_a_red_and_90_ranked(self) -> None:
        # From a tertiary road: a rider on a minor road or a path also needs the button
        # (`TestBegButtons`).
        crossing = suburban_signal(*PRIMARY, in_class="tertiary", out_class="tertiary")
        # Before (no suburban reading): a city's big road, 12 s shown on average.
        assert d.delay_s([crossing]) == d.CITY_PASS_S[None][0] == 12.0
        (run,) = d.waits([crossing], suburban=everywhere)
        assert run.red_s == d.SUBURBAN_BIG_SIGNAL_S == 45.0
        assert run.ranked_s == 90.0
        # Shown: the average a pass through a big suburban signal waits, greens included.
        assert run.seconds == d.SUBURBAN_PASS_S[0] == 24.0
        assert d.delay_s([crossing], suburban=everywhere) == 24.0
        assert d.ranked_s([run]) == 90.0
        assert d.delay_runs([crossing], suburban=everywhere) == [(100.0, 24.0)]

    def test_the_time_shown_is_the_average_per_pass_and_the_ranking_the_red(self) -> None:
        """The owner, 2026-11-08: "Averages for time, reds for choice", from a year of his
        rides with the green passes counted ("sometimes the light is green")."""
        crossing = suburban_signal(*SECONDARY, in_class="tertiary", out_class="tertiary")
        city = d.signal_wait(crossing, suburban=False)
        assert (city.seconds, city.ranked_s, city.red_s) == (5.0, 15.0, 15.0)
        suburb = d.signal_wait(crossing, suburban=True)
        assert (suburb.seconds, suburb.ranked_s, suburb.red_s) == (15.0, 60.0, 30.0)

    def test_a_city_signal_is_quicker_before_7_am_and_slowest_at_rush_hour(self) -> None:
        """ "Separate by time of day on cities. Early morning might actually have shorter
        times." The ranking does not change with the hour."""
        crossing = suburban_signal(*PRIMARY)
        shown = {
            when: d.signal_wait(crossing, when=when).seconds
            for when in ("night", "weekday_rush", "weekday_offpeak", "weekend")
        }
        assert shown == {
            "night": 9.0,
            "weekday_rush": 15.0,
            "weekday_offpeak": 14.0,
            "weekend": 11.0,
        }
        ranked = {d.signal_wait(crossing, when=w).ranked_s for w in shown}
        assert ranked == {d.CITY_BIG_SIGNAL_S}
        (run,) = d.waits([crossing], when="night")
        assert run.seconds == 9.0
        # The suburbs' passes ran no quicker early: one set at every hour.
        assert d.signal_wait(crossing, suburban=True, when="night").seconds == 24.0

    def test_a_trunk_road_is_a_big_road_too(self) -> None:
        trunk = (("road", "trunk"), ("road", "trunk"))
        assert d.signal_wait(suburban_signal(*trunk), suburban=True).red_s == 45.0

    def test_a_suburban_secondary_crossing_is_30_s_shown_and_60_ranked(self) -> None:
        crossing = suburban_signal(*SECONDARY, in_class="tertiary", out_class="tertiary")
        wait = d.signal_wait(crossing, suburban=True)
        assert (wait.red_s, wait.ranked_s) == (d.SUBURBAN_SIGNAL_S, 60.0)

    def test_a_secondary_road_of_four_lanes_or_40_mph_is_a_big_road(self) -> None:
        crossing = suburban_signal(*SECONDARY, in_class="tertiary", out_class="tertiary")
        assert d.signal_wait(crossing, suburban=True, big=True).red_s == 45.0
        (run,) = d.waits([crossing], suburban=everywhere, big={(-77.0, 38.9)})
        assert (run.red_s, run.ranked_s) == (45.0, 90.0)

    def test_a_tertiary_crossing_outside_the_cities_is_30_s_not_15(self) -> None:
        # Before the owner's second choice of 2026-11-08 this was the cities' 15 s (30 ranked).
        tertiary = (("road", "tertiary"), ("road", "tertiary"))
        wait = d.signal_wait(suburban_signal(*tertiary), suburban=True)
        assert (wait.red_s, wait.ranked_s) == (30.0, 60.0)

    def test_riding_along_the_big_road_through_its_own_signal_is_30_s(self) -> None:
        along = suburban_signal(
            *CROSS_STREET, in_class="primary", out_class="primary", headings=(0.0, 180.0)
        )
        assert d.signal_crossed_rank(along) is None
        wait = d.signal_wait(along, suburban=True)
        # Was 15 s (the cities' figure); the owner, 2026-11-08: "30 is probably more realistic".
        assert (wait.red_s, wait.ranked_s, wait.button) == (30.0, 60.0, False)

    def test_turning_off_the_big_road_onto_a_side_street_is_30_s_with_no_button(self) -> None:
        # The primary going on ahead (east, 90 degrees) is the rider's own road.
        turn = suburban_signal(
            ("road", "primary"),
            ("road", "residential"),
            movement=Movement.RIGHT,
            in_class="primary",
            out_class="residential",
            out_way=2,
            headings=(90.0, 0.0),
        )
        wait = d.signal_wait(turn, suburban=True)
        assert (wait.red_s, wait.button) == (30.0, False)
        # The same turn in a city: the cities' 30 s at a big road, the rider's own.
        assert d.signal_wait(turn, suburban=False).red_s == 30.0

    def test_turning_onto_the_big_road_from_a_side_street_is_45_s(self) -> None:
        turn = suburban_signal(
            ("road", "primary"),
            ("road", "residential"),
            movement=Movement.LEFT,
            in_class="residential",
            out_class="primary",
            out_way=2,
            headings=(180.0, 90.0),
        )
        wait = d.signal_wait(turn, suburban=True)
        assert (wait.red_s, wait.button) == (45.0, True)

    def test_the_cities_are_the_district_baltimore_alexandria_and_arlington(self) -> None:
        from core.city_limits import city_names, in_major_city

        assert set(city_names()) == {"Baltimore City", "City of Alexandria", "Arlington County"}
        # Downtown Baltimore, Old Town Alexandria, Courthouse in Arlington, the White House.
        for lon, lat in ((-76.6122, 39.2904), (-77.0469, 38.8048), (-77.0857, 38.8904)):
            assert in_major_city(lon, lat), (lon, lat)
        assert in_major_city(-77.0365, 38.8977)
        # Springfield (Fairfax County) and Beltsville (Prince George's County) are suburbs.
        assert not in_major_city(-77.1872, 38.7893)
        assert not in_major_city(-76.9075, 39.0348)

    def test_the_planner_reads_a_suburban_signal_outside_the_cities_only(self) -> None:
        from core import routing

        assert not routing.suburban_signal(-77.0857, 38.8904)
        assert routing.suburban_signal(-77.1872, 38.7893)


class TestBegButtons:
    """The owner, 2026-11-08: "something like a 2 minute wait, still not as bad as a stop
    sign across the same road"; ride time stays the measured 45/30 s."""

    def test_a_path_crossing_a_big_suburban_road_needs_its_button(self) -> None:
        crossing = suburban_signal(
            *PRIMARY, in_use="cycleway", out_use="cycleway", in_class=None, out_class=None
        )
        wait = d.signal_wait(crossing, suburban=True)
        assert wait.button
        assert wait.red_s == 45.0
        assert wait.ranked_s == d.BUTTON_RANKED_S == 120.0

    def test_a_minor_road_crossing_a_suburban_secondary_needs_it_shown_30_s(self) -> None:
        wait = d.signal_wait(suburban_signal(*SECONDARY), suburban=True)
        assert wait.button and (wait.red_s, wait.ranked_s) == (30.0, 120.0)

    def test_a_tertiary_rider_crossing_a_secondary_road_needs_no_button(self) -> None:
        crossing = suburban_signal(*SECONDARY, in_class="tertiary", out_class="tertiary")
        wait = d.signal_wait(crossing, suburban=True)
        assert (wait.red_s, wait.button) == (30.0, False)

    def test_a_side_street_crossing_a_tertiary_road_needs_no_button(self) -> None:
        # Every suburban signal is 30 s now, but a button is read only across a big or
        # secondary road.
        tertiary = (("road", "tertiary"), ("road", "tertiary"))
        wait = d.signal_wait(suburban_signal(*tertiary), suburban=True)
        assert (wait.red_s, wait.ranked_s, wait.button) == (30.0, 60.0, False)

    def test_in_the_cities_no_button_is_inferred(self) -> None:
        assert not d.signal_wait(suburban_signal(*PRIMARY), suburban=False).button

    def test_a_crossing_tagged_button_operated_needs_it_in_the_district_too(self) -> None:
        crossing = suburban_signal(
            *PRIMARY,
            in_use="pedestrian_crossing",
            out_use="pedestrian_crossing",
            in_class="service_other",
            out_class="service_other",
            in_way=77,
            out_way=77,
        )
        (untagged,) = d.waits([crossing])
        assert not untagged.button
        (run,) = d.waits([crossing], buttons={77})
        assert run.button
        # The city's 30 s at a big road shown; two minutes in the ranking.
        assert (run.red_s, run.ranked_s) == (30.0, 120.0)

    def test_the_planner_asks_the_map_only_about_crossings_and_paths(self, monkeypatch) -> None:
        from core import routing

        asked: list[str] = []
        monkeypatch.setattr(routing, "_has_button_column", lambda schema: asked.append(schema))
        on_roads = [suburban_signal(*PRIMARY, in_way=5, out_way=5)]
        assert routing.button_ways(on_roads) == frozenset()
        assert asked == [], "no query for a route on roads alone"
        # A crossing with no signal cannot become a button: nothing asked.
        unsignalled = junction(*PRIMARY, in_use="pedestrian_crossing", in_way=77)
        assert routing.button_ways([unsignalled]) == frozenset()
        assert asked == []
        # A table built before the column: no beg buttons from the map, and no query.
        crossing = suburban_signal(*PRIMARY, in_use="pedestrian_crossing", in_way=77)
        assert routing.button_ways([crossing]) == frozenset()
        assert len(asked) == 1
        # The junction model's signal points count as signals.
        assert routing.button_ways([unsignalled], {(-77.0, 38.9)}) == frozenset()
        assert len(asked) == 2

    def test_the_planner_asks_about_each_way_once_a_plan(self, monkeypatch) -> None:
        from core import routing

        asked: list[list[int]] = []

        def tagged(ways):
            asked.append(ways)
            return frozenset({77})

        monkeypatch.setattr(routing, "_tagged_button_ways", tagged)
        cache: dict = {}
        one = suburban_signal(*PRIMARY, in_use="pedestrian_crossing", in_way=77, out_way=78)
        assert routing.button_ways([one], cache=cache) == {77}
        assert routing.button_ways([one], cache=cache) == {77}
        # Only the crossing the rider is on is asked about, not the road they leave on.
        assert asked == [[77]]

    def test_a_plan_out_of_time_stops_at_the_button_read(self, monkeypatch) -> None:
        from core import routing

        monkeypatch.setattr(routing, "_has_button_column", lambda schema: True)

        def no_time(*args, **kwargs):
            raise routing.PlanCancelled("cancelled")

        monkeypatch.setattr(routing, "plan_cursor", no_time)
        crossing = suburban_signal(*PRIMARY, in_use="pedestrian_crossing", in_way=77)
        with pytest.raises(routing.DeadlineExceeded):
            routing.button_ways([crossing])

    def test_a_road_through_a_tagged_crossing_is_not_on_the_crossing(self) -> None:
        on_road = suburban_signal(*PRIMARY, in_way=77, out_way=77)
        assert not d.signal_wait(on_road, tagged_button=True).button

    def test_held_below_the_stop_sign_across_the_same_road(self) -> None:
        crossing = suburban_signal(*SECONDARY)
        # A stop sign there would cost the ranking 80 s, the junction model's price for it
        # over the signal's (before 2026-11-13 a class figure, 20 s, was added to it, which
        # counted the wait twice): the button is held 1 s below that, at 79 s.
        wait = d.signal_wait(crossing, suburban=True, stop_extra_s=80.0)
        assert wait.stop_s == 80.0
        assert wait.ranked_s == 80.0 - d.BUTTON_BELOW_STOP_S < d.BUTTON_RANKED_S
        # The stop sign is never less than its own expected wait, the junction model's
        # seconds for the same road (`read_wait`).
        timed = d.signal_wait(crossing, suburban=True, stop_extra_s=5.0, stop_wait_s=14.0)
        assert timed.stop_s == 14.0
        # `signal_wait` gives the signal's own ranked wait, never a button below it;
        # `ranked_s` holds both below the stop sign, at every wait weight.
        free = d.signal_wait(crossing, suburban=True, stop_extra_s=20.0)
        assert (free.ranked_s, free.signal_ranked_s) == (60.0, 60.0)
        (run,) = d.waits([crossing], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 20.0})
        assert d.ranked_s([run]) == 20.0 - d.BUTTON_BELOW_STOP_S

    def test_two_minutes_stays_below_the_junction_models_stop_sign_at_default(self) -> None:
        """In the ranking's own units: the junction model's feet for a stop sign across an
        LTS 4 primary over its signal, at the default slider (weight 1) and 18 km/h."""
        from core import refine
        from routemaker import intersections as m

        road = m.Road(4, speed_mph=45.0, lanes=2, names=frozenset({"telegraph road"}))
        quiet = m.Road(1)
        events = m.assess_route(
            [
                m.Junction(
                    m=100.0,
                    lon=-77.0,
                    lat=38.9,
                    movement=Movement.STRAIGHT,
                    incoming=quiet,
                    outgoing=quiet,
                    crossed=(road,),
                    control=m.Control.SIGNAL,
                )
            ]
        )
        extra_ft = m.stop_extra_ft(events)[(-77.0, 38.9)]
        assert extra_ft > 0
        assert m.big_signal_points(events) == {(-77.0, 38.9)}
        costing = {"bicycle": {"cycling_speed": 18.0}}
        ctx = refine.Context(
            variant="standard",
            request={},
            costing=costing,
            when="weekday_offpeak",
            deadline=None,
            traces={},
            points=[],
            roadway_only=False,
            with_facility=False,
            group=False,
            rate=0.0,
            weight=1.0,
            quiet_cost=refine.quiet_cost_per_m(costing),
        )
        extra_s = extra_ft * refine.stop_wait_s_per_ft(ctx)
        crossing = suburban_signal(*PRIMARY)
        (run,) = d.waits(
            [crossing],
            suburban=everywhere,
            big=m.big_signal_points(events),
            stop_extra_s={(-77.0, 38.9): extra_s},
        )
        stop_sign_s = extra_s
        assert run.button
        assert run.ranked_s == 120.0 < stop_sign_s
        assert run.red_s == 45.0


def rb(found, weight: float = 3.0) -> float:
    """`d.ranked_s` with Road Bike's button rule (`presets.ROAD_BIKE_BUTTON_RIDES`)."""
    return d.ranked_s(found, weight, road_bike_buttons=True)


class TestRoadBikeStackedWeight:
    """The owner, 2026-11-08: "Maybe go to 5. People prefer free flow on road bikes." Road
    Bike's 3x wait weight on a suburban signal's 2x is held at 5x the wait at a red."""

    def test_a_suburban_signal_on_road_bike_ranks_at_5x_not_6x(self) -> None:
        crossing = suburban_signal(*PRIMARY, in_class="tertiary", out_class="tertiary")
        (run,) = d.waits([crossing], suburban=everywhere)
        # Before the cap: 3 x 90 = 270 s (6x); after: 225 s (5x the 45 s red).
        assert 3.0 * d.ranked_s([run], 3.0) == 5.0 * 45.0
        assert d.ranked_s([run]) == 90.0

    def test_a_city_signal_on_road_bike_stays_at_3x(self) -> None:
        (run,) = d.waits([suburban_signal(*PRIMARY)])
        assert 3.0 * d.ranked_s([run], 3.0) == 3.0 * 30.0

    def test_a_button_crossing_on_road_bike_ranks_ten_minutes_below_2_3_of_the_stop_sign(
        self,
    ) -> None:
        """The owner, 2026-11-08: "Call that 10 minutes on a road bike in pain level. ...
        Just make sure it's less than half a stop sign against an uncontrolled busy road",
        then, told half a stop sign could fall under a plain signal, "make it 2/3 of one".
        """
        crossing = suburban_signal(*PRIMARY)
        (run,) = d.waits([crossing], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 400.0})
        assert run.button and run.ranked_s == 120.0
        # Before: held at 5x the 45 s red, 225 s; after: ten minutes.
        assert 3.0 * rb([run]) == d.ROAD_BIKE_BUTTON_S == 600.0
        # Less than 2/3 of the stop sign there at Road Bike's weight, 400 s.
        assert 3.0 * rb([run]) < 3.0 * 400.0 * 2.0 / 3.0
        # A cheaper stop sign (50 s, 150 s at 3x): held 1 s below its 2/3.
        (cheap,) = d.waits([crossing], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 50.0})
        assert 3.0 * rb([cheap]) == pytest.approx(3.0 * 50.0 * 2.0 / 3.0 - 1.0)
        # Not known: ten minutes.
        (unpriced,) = d.waits([crossing], suburban=everywhere)
        assert 3.0 * rb([unpriced]) == 600.0
        # Off Road Bike's weight, the two minutes stand.
        assert d.ranked_s([run]) == 120.0

    def test_a_plain_light_ranks_below_the_button_at_the_same_light_when_the_stop_is_cheap(
        self,
    ) -> None:
        """The blocking review, 2026-11-08: with the stop sign across the road cheap, the
        button's hold (then half the stop sign) ranked it below the same light with no
        button. Now on Road Bike: the plain light, then the button, then 2/3 of the stop."""
        tagged = {"in_use": "pedestrian_crossing", "out_use": "pedestrian_crossing"}
        here = (-77.0, 38.9)
        # A city light onto a primary from a crossing: a 30 s red, 90 s at 3x; the stop sign
        # 40 s, 120 s at 3x, whose 2/3 is 80 s, below the plain light.
        light = suburban_signal(*PRIMARY, in_way=77, **tagged)
        (plain,) = d.waits([light], stop_extra_s={here: 40.0})
        (button,) = d.waits([light], buttons={77}, stop_extra_s={here: 40.0})
        assert (plain.button, button.button) == (False, True)
        plain_s = 3.0 * rb([plain])
        button_s = 3.0 * rb([button])
        stop_s = 3.0 * 40.0
        # Before: the plain light 90 s and the button 59 s (1 s below half the stop sign).
        assert plain_s == pytest.approx(stop_s * 2.0 / 3.0 - 2.0)
        assert button_s == pytest.approx(stop_s * 2.0 / 3.0 - 1.0)
        assert plain_s < button_s < stop_s * 2.0 / 3.0
        # The same in the suburbs, the button read from a residential street.
        street = suburban_signal(*PRIMARY)
        tertiary = suburban_signal(*PRIMARY, in_class="tertiary", out_class="tertiary")
        (pressed,) = d.waits([street], suburban=everywhere, stop_extra_s={here: 50.0})
        (unpressed,) = d.waits([tertiary], suburban=everywhere, stop_extra_s={here: 50.0})
        assert pressed.button and not unpressed.button
        assert rb([unpressed]) < rb([pressed]) < 2.0 / 3.0 * 50.0

    def test_a_suburban_signal_never_ranks_above_the_stop_sign_across_the_same_road(
        self,
    ) -> None:
        """Hunt J2-4: on Road Bike (and at the traffic-tolerant end of the slider), the
        suburban 2x put a signal above the stop sign a block away across the same road.
        Since 2026-11-13 the hold is at every wait weight (Broach et al. 2012 and Furth
        both order a signal below an unsignalised crossing of the same road)."""
        tertiary_rider = {"in_class": "tertiary", "out_class": "tertiary"}
        crossing = suburban_signal(("road", "tertiary"), ("road", "tertiary"), **tertiary_rider)
        # A stop sign across the tertiary: 17 s as the model prices it, 51 s at 3x. No button
        # is read at this light, so the stop sign alone holds it.
        (run,) = d.waits([crossing], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 17.0})
        assert not run.button and not run.button_light
        # Before: 3 x 60 = 180 s (150 s at the 5x cap), above the 51 s stop sign; after: 50 s.
        assert 3.0 * rb([run]) == 3.0 * 17.0 - 1.0
        # At 1x too: 16 s (from 2026-11-08 to 2026-11-13 the suburban 2x stood at 1x, 60 s).
        assert d.ranked_s([run]) == 16.0
        # Across a secondary, where a button is read for a rider from a side street, the
        # plain light is held below 2/3 of the stop sign (33 s, 99 s at 3x): 64 s.
        busy = suburban_signal(*SECONDARY, **tertiary_rider)
        (run,) = d.waits([busy], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 33.0})
        assert not run.button and run.button_light
        assert 3.0 * rb([run]) == pytest.approx(99.0 * 2.0 / 3.0 - 2.0)
        assert d.ranked_s([run]) == 32.0
        # The time shown is the average pass, unchanged.
        assert run.seconds == 15.0
        # Riding along the road through its signal, no road crossed: nothing to compare.
        along = suburban_signal(
            ("road", "residential"), in_class="secondary", out_class="secondary"
        )
        (run,) = d.waits([along], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 0.0})
        assert run.ranked_s == 60.0

    def test_riding_along_the_busier_road_has_no_stop_sign_to_hold_the_light_below(
        self,
    ) -> None:
        """The 2026-11-08 hunt, J3-1: a right turn off a suburban primary onto a tertiary at
        a signal crosses no road, yet the junction model's extra for a stop sign on the
        rider's approach (2 s here) and a plain 8 s stop had held Road Bike's light at
        3 x 10 - 1 = 29 weighted seconds, below Default's 60."""
        turn = suburban_signal(
            ("road", "primary"),
            movement=Movement.RIGHT,
            in_class="primary",
            out_class="tertiary",
            out_way=2,
            headings=(90.0,),
        )
        assert d.signal_crossed_rank(turn) is None
        (run,) = d.waits([turn], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 2.0})
        assert run.stop_s is None
        # Road Bike's own rule: 3 x 60 held at 5 x the 30 s red, 150 (before: 29).
        assert 3.0 * d.ranked_s([run], 3.0) == 150.0
        assert d.ranked_s([run]) == 60.0

    def test_at_1x_nothing_is_capped(self) -> None:
        tagged = suburban_signal(
            *PRIMARY, in_use="pedestrian_crossing", out_use="pedestrian_crossing", in_way=77
        )
        (run,) = d.waits([tagged], buttons={77})
        assert d.ranked_s([run]) == 120.0


def ride_ranked_s(found, name: str) -> float:
    """`d.ranked_s` as the plan calls it for ride type `name`, in weighted seconds."""
    weight = presets.wait_weight_for(name)
    return weight * d.ranked_s(found, weight, road_bike_buttons=presets.road_bike_buttons_for(name))


class TestButtonPriceByRideType:
    """Which ride types price a beg button at Road Bike's ten minutes is named
    (`presets.ROAD_BIKE_BUTTON_RIDES`), not read from a wait weight above 1."""

    def button(self) -> d.Wait:
        (run,) = d.waits([suburban_signal(*PRIMARY)], suburban=everywhere)
        assert run.button and run.red_s == 45.0
        return run

    def test_road_bike_prices_a_button_at_ten_minutes(self) -> None:
        assert presets.road_bike_buttons_for(presets.ROAD_BIKE)
        assert ride_ranked_s([self.button()], presets.ROAD_BIKE) == d.ROAD_BIKE_BUTTON_S

    def test_tandem_prices_a_button_at_ten_minutes_by_owner_decision(self) -> None:
        """The owner, 2026-11-08: "That should be at the 10x. It's really obnoxious to try to
        navigate to a button on a tandem." Tandem's own weight is 2x, not Road Bike's 3x."""
        assert presets.wait_weight_for(presets.TANDEM) == 2.0
        assert presets.road_bike_buttons_for(presets.TANDEM)
        assert ride_ranked_s([self.button()], presets.TANDEM) == d.ROAD_BIKE_BUTTON_S

    def test_other_ride_types_keep_the_stacked_rule(self) -> None:
        run = self.button()
        # Cargo (1x): the usual two-minute button, as before.
        assert not presets.road_bike_buttons_for("cargo")
        assert ride_ranked_s([run], "cargo") == d.BUTTON_RANKED_S == 120.0
        # Any ride type above 1x not named: the stacked rule, 2 x 120 = 240 held at 5x the
        # 45 s red, 225 s; not ten minutes.
        assert 2.0 * d.ranked_s([run], 2.0) == d.MAX_STACKED_WEIGHT * 45.0 == 225.0
        assert 2.0 * d.ranked_s([run], 2.0) < d.ROAD_BIKE_BUTTON_S


def at(junction: t.RawJunction, m: float, lon: float) -> t.RawJunction:
    """`junction` moved to `m` metres along the route, at `lon`."""
    from dataclasses import replace

    return replace(junction, m=m, lon=lon)


class TestSignalRuns:
    """The 2026-11-08 hunt (J2-2, J2-5) and the signal review of the same day."""

    def test_a_divided_roads_two_signalised_carriageways_45_m_apart_are_one_wait(self) -> None:
        crossing = junction(*PRIMARY)
        near, far = at(crossing, 100.0, -77.0), at(crossing, 140.0, -76.9995)
        points = {(-77.0, 38.9), (-76.9995, 38.9)}
        found = d.waits([near, far], signals=points, suburban=everywhere, big=points)
        # Before: two waits of 24 s shown and 120 ranked, two button cues; after: one.
        assert [(w.seconds, w.ranked_s, w.button) for w in found] == [(24.0, 120.0, True)]
        # Two signals farther apart than the junction model's one junction stay two.
        apart = at(crossing, 150.0, -76.999)
        both = {(-77.0, 38.9), (-76.999, 38.9)}
        assert len(d.waits([near, apart], signals=both, suburban=everywhere)) == 2
        # A give-way past the junction model's one junction (`MERGE_WITHIN_M`, 45 m; this
        # module's own 35 m until 2026-11-13) is still a stop of its own.
        give_way = at(junction(*PRIMARY), 150.0, -76.9995)
        assert len(d.waits([at(suburban_signal(*PRIMARY), 100.0, -77.0), give_way])) == 2

    def test_the_signal_merge_is_measured_from_the_runs_signal_not_its_first_junction(
        self,
    ) -> None:
        """The 2026-11-08 hunt, J3-3: a path coming out onto a street 15 m short of a divided
        road's first signalised carriageway, the second 40 m past the first, had made two
        waits and two button cues: 45 m was measured from the path's junction."""
        path_out = junction(
            ("road", "residential"),
            m=100.0,
            in_use="cycleway",
            in_class="service_other",
            out_way=2,
        )
        crossing = junction(*PRIMARY, in_way=2, out_way=2, headings=(0.0, 180.0))
        near, far = at(crossing, 115.0, -76.9999), at(crossing, 155.0, -76.9995)
        points = {(-76.9999, 38.9), (-76.9995, 38.9)}
        found = d.waits([path_out, near, far], signals=points, suburban=everywhere)
        # Before: two waits of 24 s shown and 120 ranked, each with a button; after: one.
        assert [(w.seconds, w.ranked_s, w.button) for w in found] == [(24.0, 120.0, True)]
        assert found[0].m == 100.0

    def test_a_signal_at_a_service_road_or_trail_stops_the_rider_on_the_road(self) -> None:
        """A suburban stroad's signal at a shopping-centre entrance, and one for a trail
        crossing it: before, no wait (only service and path arms); after, a signal's."""
        entrance = (("road", "service_other"), ("road", "service_other"))
        trail = (("cycleway", "service_other"), ("cycleway", "service_other"))
        for arms in (entrance, trail):
            along = suburban_signal(*arms, in_class="primary", out_class="primary")
            assert d.delay_at(along) == d.SIGNAL_DELAY_S
            (run,) = d.waits([along], suburban=everywhere)
            # The busiest road there is the rider's own primary: 24 s shown, a 30 s red.
            assert (run.seconds, run.red_s, run.ranked_s) == (24.0, 30.0, 60.0)
        # A mid-block signalised footway crossing (a pedestrian light) stops the rider on the
        # road too (J2-5): priced as a signal by the rider's own road.
        footway = (("footway", "service_other"), ("footway", "service_other"))
        along = suburban_signal(*footway, in_class="primary", out_class="primary")
        assert d.delay_at(along) == d.SIGNAL_DELAY_S
        (run,) = d.waits([along], suburban=everywhere)
        assert (run.seconds, run.red_s, run.ranked_s, run.button) == (24.0, 30.0, 60.0, False)
        # A signal flag at a way split with nothing else at the node is still nothing.
        assert d.delay_at(junction(signal=True, out_way=2)) == 0.0
        # The same entrance without a signal costs the rider on the main road nothing.
        assert d.delay_at(junction(*entrance, in_class="primary", out_class="primary")) == 0.0

    def test_the_riders_own_big_road_counts_in_the_busiest_road_not_the_red(self) -> None:
        """The signal review, 2026-11-08: riding along a 4-lane or 40 mph secondary through
        its signal at a tertiary counted it as a secondary road."""
        tertiary = (("road", "tertiary"), ("road", "tertiary"))
        along = suburban_signal(*tertiary, in_class="secondary", out_class="secondary")
        here = {(-77.0, 38.9)}
        (city_before,) = d.waits([along])
        (city_after,) = d.waits([along], own_big=here)
        # In a city: before the secondary's 15 s red and 5 s shown; after the big road's.
        assert (city_before.red_s, city_before.seconds) == (15.0, 5.0)
        assert (city_after.red_s, city_after.seconds) == (30.0, 12.0)
        # In the suburbs: the time shown by the big road; the red stays 30 s, not 45 s, as
        # the rider does not cross or join a big road.
        (suburb,) = d.waits([along], suburban=everywhere, own_big=here)
        assert (suburb.seconds, suburb.red_s, suburb.ranked_s) == (24.0, 30.0, 60.0)
        (plain,) = d.waits([along], suburban=everywhere)
        assert plain.seconds == 15.0

    def test_the_button_is_at_the_button_signal_not_the_runs_first_junction(self) -> None:
        """The signal review, 2026-11-08: a run that begins at a stop sign or a stop line
        short of the button signal keeps the button signal's own node."""
        stop_first = at(junction(*SECONDARY), 90.0, -77.0002)
        button = at(suburban_signal(*SECONDARY), 110.0, -77.0)
        (run,) = d.waits([stop_first, button], suburban=everywhere)
        assert run.button and (run.m, run.lon) == (90.0, -77.0002)
        assert run.button_at == (110.0, -77.0, 38.9)
        (plain,) = d.waits([stop_first, at(suburban_signal(*SECONDARY), 110.0, -77.0)])
        assert not plain.button and plain.button_at is None


class TestButtonsOff:
    """The owner, 2026-11-10: "Remove the 'push button' to cross. It generally only gets
    the ones that are on timers", then "Remove the cue and the penalty". Before, the
    crossings below ranked at 2 minutes (10 on Road Bike and Tandem); now each ranks as the
    plain signal it is, on every ride type."""

    @pytest.fixture(autouse=True)
    def off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(d, "BUTTONS_PRICED", False)

    def test_the_planner_prices_no_buttons(self) -> None:
        # The module's own setting, not this class's fixture.
        import inspect

        assert "\nBUTTONS_PRICED = False\n" in inspect.getsource(d)

    def test_a_path_crossing_a_big_suburban_road_is_a_plain_signal(self) -> None:
        crossing = suburban_signal(
            *PRIMARY, in_use="cycleway", out_use="cycleway", in_class=None, out_class=None
        )
        wait = d.signal_wait(crossing, suburban=True)
        assert not wait.button and not wait.button_light
        # The suburban 45 s red, doubled: no longer BUTTON_RANKED_S.
        assert (wait.red_s, wait.ranked_s) == (45.0, 90.0)

    def test_a_crossing_tagged_button_operated_is_a_plain_signal(self) -> None:
        crossing = suburban_signal(
            *PRIMARY,
            in_use="pedestrian_crossing",
            out_use="pedestrian_crossing",
            in_class="service_other",
            out_class="service_other",
        )
        wait = d.signal_wait(crossing, tagged_button=True)
        assert not wait.button and wait.ranked_s == wait.red_s

    def test_road_bike_and_tandem_rank_it_as_any_signal(self) -> None:
        (run,) = d.waits([suburban_signal(*PRIMARY)], suburban=everywhere)
        assert not run.button and run.button_at is None
        for ride in (presets.ROAD_BIKE, presets.TANDEM):
            weight = presets.wait_weight_for(ride)
            ranked = ride_ranked_s([run], ride)
            # The stacked rule (90 s at 1x, held at 5x the 45 s red), not ten minutes.
            assert ranked == min(weight * 90.0, d.MAX_STACKED_WEIGHT * 45.0)
            assert ranked < d.ROAD_BIKE_BUTTON_S

    def test_road_bike_does_not_hold_a_light_below_a_button_it_no_longer_prices(self) -> None:
        """Where the stop sign across the same road is priced, Road Bike once held a light a
        button was read at 2 s below two-thirds of that stop sign (`_signal`). Off, the light
        ranks by the stacked rule and the J2-4 stop-sign cap alone."""
        crossing = suburban_signal(*PRIMARY)
        on = d.signal_wait(crossing, suburban=True, stop_extra_s=40.0)
        assert not on.button_light and on.stop_s is not None
        (run,) = d.waits([crossing], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 40.0})
        weight = presets.wait_weight_for(presets.ROAD_BIKE)
        expected = min(
            weight * run.ranked_s,
            max(d.MAX_STACKED_WEIGHT * run.red_s, run.ranked_s),
            max(weight * run.stop_s - d.BUTTON_BELOW_STOP_S, 0.0),
        )
        assert ride_ranked_s([run], presets.ROAD_BIKE) == pytest.approx(expected)


HERE = (-77.0, 38.9, 1, 1)
BUSY = (("road", "primary"), ("road", "primary"))


def road(level: float, aadt: int | None = None, **facts) -> Road:
    """A road as the junction model reads it, at a traffic level."""
    return Road(tier=int(level), half=level % 1 == 0.5, aadt=aadt, **facts)


def gap(aadt: int, lanes: int, speed_mph: float | None = None, when: str | None = None) -> float:
    """The capped wait for a gap in a two-way road of `lanes` in all."""
    return d.gap_wait_s(Road(3, aadt=aadt, lanes=lanes // 2, speed_mph=speed_mph), when)


def stopped_at(crossed: Road, when: str | None = None, **more) -> dict:
    """The junction model's reading of a rider at a stop sign on a quiet street crossing
    `crossed` (`intersections.give_ways`), as `waits` is handed it."""
    quiet = Road(1)
    crossing = Junction(
        0.0, -77.0, 38.9, Movement.STRAIGHT, quiet, quiet, (crossed,), Control.STOP, **more
    )
    (reading,) = m.give_ways([crossing], when)
    return {HERE: reading}


class TestRealTimeAtAGiveWay:
    """The methodology audit (2026-11-13, section 3.5) and the owner's review of his own
    calls the same day. Before: 30 / 20 / 12 s by road class, 8 s at a quiet street's stop
    sign (4 s in the District), shown and ranked, the give-ways held high as a dislike.
    After: the expected real time, shown and ranked alike."""

    def test_a_quiet_streets_stop_sign(self) -> None:
        (run,) = d.waits([junction(*CROSS_STREET)])
        assert (run.seconds, run.ranked_s) == (d.STOP_SIGN_S, d.STOP_SIGN_S) == (3.0, 3.0)

    def test_the_stop_figure_follows_from_its_sources(self) -> None:
        """Broach, Dill and Gliebe 2012, Table 3: a stop sign is weighed at 0.9% of a mile,
        47.5 ft, 2.9 s at the Default ride's 16.4 ft/s. A full stop is far more, 9.5 s
        (Fajans and Curry 2001: 10.9 mph with a stop every 530 ft, 14.2 mph with one every
        2,800 ft), not the 7.6 s the code once derived from the same paper."""
        assert round(0.009 * 5280.0 / m.GAP_SPEED_FTS) == d.STOP_SIGN_S
        lost = 3600.0 / 10.9 - 3600.0 / 14.2
        extra_stops = 5280.0 / 530.0 - 5280.0 / 2800.0
        assert round(lost / extra_stops, 1) == 9.5

    def test_with_a_count_the_wait_is_the_roads_own(self) -> None:
        """A two-lane 25 mph road with 8,000 a day, off-peak: 4.5 s where it was 20 s."""
        crossed = stopped_at(road(3, 8000, lanes=1, speed_mph=25.0))
        (run,) = d.waits([junction(*BUSY)], given_way=crossed)
        assert run.seconds == run.ranked_s == 4.5
        assert run.seconds == round(d.STOP_SIGN_S + gap(8000, 2, 25.0), 1)

    def test_without_a_count_the_road_is_a_typical_one(self) -> None:
        """Before: 30 / 20 / 12 s. After: 13.8 / 4.5 / 4.5 s off-peak."""
        shown = []
        for cls in ("trunk", "primary", "secondary", "tertiary"):
            (run,) = d.waits([junction(("road", cls), ("road", cls))])
            assert run.seconds == run.ranked_s
            shown.append(run.seconds)
        assert shown == [PRIMARY_GIVE_WAY_S, PRIMARY_GIVE_WAY_S, 4.5, 4.5]
        assert PRIMARY_GIVE_WAY_S == round(d.STOP_SIGN_S + d.gap_wait_s(m.TYPICAL_BIG_ROAD), 1)
        assert 4.5 == round(d.STOP_SIGN_S + d.gap_wait_s(m.TYPICAL_BUSY_ROAD), 1)

    def test_the_ranking_counts_the_same_time(self) -> None:
        """No separate dislike price: riders weigh a stop sign and a signal at about their
        clock time (Broach et al. 2012), and the dislike of an unsignalled busy crossing is
        the junction model's cost in feet."""
        route = [junction(*CROSS_STREET, m=100.0), junction(*BUSY, m=300.0)]
        found = d.waits(route, when="weekday_rush")
        assert [w.ranked_s for w in found] == [w.seconds for w in found]
        assert d.ranked_s(found) == d.delay_s(route, when="weekday_rush")

    def test_ten_secondary_crossings_do_not_add_minutes(self) -> None:
        """The owner-calls review's ETA test (2026-11-13): ten unsignalled crossings of
        secondary roads added 200 s; his rides show about 17 s of waiting and stopping.
        Now 45 s: 15 s of waiting for gaps, and the stop sign's 3 s at each."""
        cls = (("road", "secondary"), ("road", "secondary"))
        route = [junction(*cls, m=200.0 * i) for i in range(1, 11)]
        assert sum(d.delay_at(j) for j in route) == 200.0
        assert d.delay_s(route) == pytest.approx(45.0)
        assert d.delay_s(route) - 10 * d.STOP_SIGN_S == pytest.approx(15.0)

    def test_a_wide_commuter_road_at_a_stop_sign(self) -> None:
        """The review's case: a six-lane divided road, one-way three-lane carriageways,
        30,000 a day, no signal. At rush hour the wait is at the cap; midday about half;
        at night a few seconds. (Its stress is the junction model's, charged there.)"""
        wide = road(4, 30000, lanes=3, oneway=True, speed_mph=35.0)
        seconds = {
            when: d.waits([junction(*BUSY)], given_way=stopped_at(wide, when), when=when)[0].seconds
            for when in ("weekday_rush", "weekday_offpeak", "night")
        }
        assert seconds == {"weekday_rush": 33.0, "weekday_offpeak": 19.2, "night": 5.1}

    def test_road_bikes_weight_still_counts_a_give_way_three_times(self) -> None:
        found = d.waits([junction(*BUSY)])
        assert d.ranked_s(found, 3.0) * 3.0 == pytest.approx(3 * PRIMARY_GIVE_WAY_S)

    def test_a_run_keeps_its_dearest_junction(self) -> None:
        near = [junction(*CROSS_STREET, m=100.0), junction(*BUSY, m=118.0)]
        (run,) = d.waits(near)
        assert (run.seconds, run.ranked_s) == (PRIMARY_GIVE_WAY_S, PRIMARY_GIVE_WAY_S)


class TestGapWait:
    """`gap_wait_s`, the junction model's `intersections.gap_delay_s` capped as a time (ONE
    formula for the wait shown and the stress price): NCHRP Report 562, Appendix A,
    worksheets 1 and 2, step 4 (the Highway Capacity Manual 2000's equations 18-17 and
    18-21)."""

    def test_the_formula_as_printed(self) -> None:
        """tc = L / S + ts; d = (e^(v tc) - v tc - 1) / v. 8,000 a day at 5.5% an hour is
        440 an hour, v = 0.1222 a second; two 12 ft lanes at 16.4 ft/s plus 3 s is 4.46 s."""
        v, tc = 440 / 3600, 24 / 16.4 + 3.0
        assert gap(8000, 2) == pytest.approx((math.exp(v * tc) - v * tc - 1) / v)
        assert gap(8000, 2) == pytest.approx(1.48, abs=0.01)

    def test_the_reports_own_values_give_its_own_critical_gaps(self, monkeypatch) -> None:
        """Its Table 11: 9 s for two lanes and 15 s for four, at a 4 ft/s walk."""
        monkeypatch.setattr(m, "GAP_SPEED_FTS", 4.0)
        monkeypatch.setattr(m, "GAP_WAIT_MAX_S", math.inf)
        for lanes, tc in ((2, 9.0), (4, 15.0)):
            v = 1000 * m.hour_share(None) / 3600
            assert gap(1000, lanes) == pytest.approx((math.exp(v * tc) - v * tc - 1) / v)

    def test_it_is_checked_against_the_owners_rides_not_fitted_to_them(self) -> None:
        """2,882 passes straight across a busier road with no signal (DC, mostly early), in
        the file's own per-pass measure, the mean wait plus 8 s for the share that stopped:
        7.4 / 1.7 / 0.7 s at trunk-or-primary / secondary / smaller roads. The old model
        gave 30 / 20 / 12 s. The formula, with nothing fitted, on a road assumed for each
        class at the night hour: 4.9 / 1.8 / 0.7 s."""
        assumed = {"primary": (20_000, 4), "secondary": (10_000, 2), "tertiary": (4_000, 2)}
        measured = {"primary": 7.4, "secondary": 1.7, "tertiary": 0.7}
        like_the_file = {}
        for cls, (aadt, lanes) in assumed.items():
            flow = aadt * m.hour_share("night") / 3600
            critical = lanes * m.GAP_LANE_FT / m.GAP_SPEED_FTS + m.GAP_STARTUP_S
            stopped = 1 - math.exp(-flow * critical)
            like_the_file[cls] = round(gap(aadt, lanes, 25.0, "night") + 8 * stopped, 1)
        assert like_the_file == {"primary": 4.9, "secondary": 1.8, "tertiary": 0.7}
        for cls, seconds in measured.items():
            assert abs(like_the_file[cls] - seconds) <= 2.5
            assert abs(like_the_file[cls] - seconds) < abs(d.delay_at(junction(*BUSY)) - seconds)

    def test_it_grows_with_volume_width_speed_and_the_hour(self) -> None:
        base = gap(12000, 2, 30.0)
        assert gap(20000, 2, 30.0) > base
        assert gap(12000, 4, 30.0) > base
        # The report's worksheet 2: above 35 mph the flow is divided by 0.7.
        assert gap(12000, 2, 40.0) > base == gap(12000, 2, 35.0)
        rush, night = (gap(12000, 2, 30.0, when) for when in ("weekday_rush", "night"))
        assert rush > base > gap(12000, 2, 30.0, "weekend") > night > 0

    def test_an_empty_road_has_no_wait(self) -> None:
        assert m.gap_delay_s(Road(3, aadt=0, lanes=1)) == 0.0
        assert d.gap_wait_s(Road(1, lanes=1)) == 0.0

    def test_the_wait_stops_at_the_cap(self) -> None:
        """Four lanes at 40 mph with 30,000 a day at rush hour is minutes by the formula;
        the wait stops at 30 s (NCHRP 562 Table 8: above 30 s risk-taking is likely)."""
        assert gap(30000, 4, 40.0, "weekday_rush") == m.GAP_WAIT_MAX_S
        assert gap(10**7, 8, 55.0, "weekday_rush") == m.GAP_WAIT_MAX_S
        assert gap(20000, 4, 25.0, "weekday_rush") < m.GAP_WAIT_MAX_S

    def test_a_one_way_road_is_crossed_in_its_own_lanes(self) -> None:
        assert m.lanes_crossed(Road(4, lanes=2)) == 4
        assert m.lanes_crossed(Road(4, lanes=2, oneway=True)) == 2
        assert m.lanes_crossed(Road(3)) == 2


class TestOneBusyRoad:
    """How busy a road is comes from its count; without one, from its crossing level as
    the junction model reads it (`intersections.wait_s`), the same reading and the same
    seconds its price weighs; by Valhalla class only where the model has no reading. The
    audit's two cases (areas/07, 2.10)."""

    def test_a_calm_two_lane_primary_is_timed_by_its_own_traffic(self) -> None:
        """Primary by class, 25 mph, one lane each way, 5,000 a day. Before: 30 s by its
        class. After: 3.9 s. With no count and level 1: a stop sign's 3 s."""
        assert d.delay_at(junction(*BUSY)) == 30.0
        calm = stopped_at(road(2, 5000, lanes=1, speed_mph=25.0))
        (run,) = d.waits([junction(*BUSY)], given_way=calm)
        assert run.seconds == 3.9
        uncounted = stopped_at(road(2, lanes=1, speed_mph=25.0))
        (run,) = d.waits([junction(*BUSY)], given_way=uncounted)
        assert run.seconds == d.STOP_SIGN_S

    def test_a_fast_wide_residential_road_is_a_big_road(self) -> None:
        """Residential by class, 40 mph, two lanes each way, the map's level 4, no count.
        Before: an 8 s stop, 4 s in the District. After: the typical big road's wait, by
        the junction model's crossing level (Furth's crossing table: 4 at 40 mph). At
        35 mph that table says 3, a busy road and not a big one."""
        wide = stopped_at(road(4, lanes=2, speed_mph=40.0))
        (run,) = d.waits([junction(*CROSS_STREET)], given_way=wide)
        assert run.seconds == PRIMARY_GIVE_WAY_S
        slower = stopped_at(road(4, lanes=2, speed_mph=35.0))
        (run,) = d.waits([junction(*CROSS_STREET)], given_way=slower)
        assert run.seconds == 4.5

    @pytest.mark.parametrize(
        ("level", "typical"),
        [(5, "big"), (4.5, "big"), (4, "big"), (3.5, "busy"), (2.5, "busy"), (2, None), (1, None)],
    )
    def test_without_a_count_the_level_picks_the_typical_road(self, level, typical) -> None:
        """A road the model could not read by its traffic, by the map's level: the crossing
        level's top, 4 (`intersections.crossing_level`), and busy from 2.5 (`Road.busy`)."""
        (run,) = d.waits([junction(*BUSY)], given_way=stopped_at(road(level)))
        roads = {"big": m.TYPICAL_BIG_ROAD, "busy": m.TYPICAL_BUSY_ROAD}
        wait = d.gap_wait_s(roads[typical]) if typical else 0.0
        assert run.seconds == round(d.STOP_SIGN_S + wait, 1)

    def test_a_junction_the_model_did_not_read_falls_back_to_its_class(self) -> None:
        (run,) = d.waits([junction(*BUSY)], given_way={})
        assert run.seconds == PRIMARY_GIVE_WAY_S
        assert d.give_way_wait(d.delay_at(junction(*BUSY))) == PRIMARY_GIVE_WAY_S

    def test_the_traffic_reading_is_the_junction_models(self) -> None:
        """A road the map rates 2 for its bike lane, 40 mph and two lanes each way, is
        level 4 to cross (`intersections.by_traffic`), and timed as one."""
        laned = Road(2, lanes=2, speed_mph=40.0)
        (run,) = d.waits([junction(*CROSS_STREET)], given_way=stopped_at(laned))
        assert run.seconds == PRIMARY_GIVE_WAY_S


class TestTimeOfDay:
    """The hour reaches a junction with no signal through the traffic alone: no separate
    factor on the time shown or the ranking."""

    def test_the_wait_takes_the_hour_through_the_traffic(self) -> None:
        crossed = road(4, 20000, lanes=2, speed_mph=25.0)
        found = {
            when: d.waits([junction(*BUSY)], given_way=stopped_at(crossed, when), when=when)[0]
            for when in ("night", "weekend", "weekday_offpeak", "weekday_rush")
        }
        assert {when: w.seconds for when, w in found.items()} == {
            "night": 4.7,
            "weekend": 12.1,
            "weekday_offpeak": 13.8,
            "weekday_rush": 26.2,
        }
        assert all(w.ranked_s == w.seconds for w in found.values())

    def test_a_quiet_streets_stop_does_not_change_with_the_hour(self) -> None:
        for when in ("night", "weekday_rush"):
            (run,) = d.waits([junction(*CROSS_STREET)], when=when)
            assert run.ranked_s == run.seconds == d.STOP_SIGN_S
