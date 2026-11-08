"""The time a rider loses at junctions (`routemaker.junction_delay`)."""

from __future__ import annotations

import pytest

from routemaker import junction_delay as d
from routemaker import trace_junctions as t
from routemaker.intersections import Beacon, Movement, beacon_at

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

    def test_in_the_district_it_is_a_slow_and_roll(self) -> None:
        assert d.delay_at(junction(*CROSS_STREET), rolls=True) == d.YIELD_DELAY_S

    def test_crossing_a_busier_road_waits_for_a_gap_in_the_district_too(self) -> None:
        busy = (("road", "tertiary"), ("road", "tertiary"))
        assert d.delay_at(junction(*busy), rolls=True) == d.GIVE_WAY_DELAY_S[4]

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
        assert d.delay_s(stops) == pytest.approx(5 * d.STOP_DELAY_S)

    def test_a_divided_road_is_crossed_as_one_stop_at_its_dearest(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        near = [junction(*busy, m=100.0), junction(*busy, m=118.0, signal=True)]
        # The signal's time shown, a city's big road with the ride-time setting not known.
        assert d.delay_s(near) == d.CITY_PASS_S[None][0]

    def test_the_district_test_is_asked_at_each_junction(self) -> None:
        stops = [junction(*CROSS_STREET, m=100.0), junction(*CROSS_STREET, m=300.0)]
        asked = []

        def rolls(lon: float, lat: float) -> bool:
            asked.append((lon, lat))
            return len(asked) == 1

        assert d.delay_s(stops, rolls) == d.YIELD_DELAY_S + d.STOP_DELAY_S

    def test_the_beacon_test_is_asked_only_at_signals(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        stops = [junction(*busy, m=100.0, signal=True), junction(*CROSS_STREET, m=300.0)]
        asked = []

        def beacon(lon: float, lat: float) -> bool:
            asked.append((lon, lat))
            return True

        assert d.delay_s(stops, beacon=beacon) == d.GIVE_WAY_DELAY_S[2] + d.STOP_DELAY_S
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
        assert (near, away) == (d.GIVE_WAY_DELAY_S[2], d.CITY_PASS_S[None][0])

    def test_driveways_between_stops_do_not_merge_them(self) -> None:
        driveway = (("driveway", "service_other"),)
        route = []
        for block in range(4):
            route.append(junction(*CROSS_STREET, m=100.0 * block))
            route += [junction(*driveway, m=100.0 * block + k) for k in range(20, 100, 20)]
        assert d.delay_s(route) == pytest.approx(4 * d.STOP_DELAY_S)

    def test_the_district_test_is_not_asked_where_nothing_stops(self) -> None:
        asked = []

        def rolls(lon: float, lat: float) -> bool:
            asked.append((lon, lat))
            return True

        d.delay_s([junction(("road", "residential"), m=100.0)], rolls)
        assert asked == []

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
        assert d.delay_s([trail]) == d.GIVE_WAY_DELAY_S[2]
        shown = d.CITY_PASS_S[None][0]
        assert d.delay_s([trail], signals={(-77.0, 38.9)}) == shown
        assert d.delay_runs([trail], signals={(-77.0, 38.9)}) == [(100.0, shown)]
        # Another junction's signal is not this one's.
        assert d.delay_s([trail], signals={(-77.001, 38.9)}) == d.GIVE_WAY_DELAY_S[2]

    def test_a_known_beacon_is_still_a_stop_where_the_model_reads_a_signal(self) -> None:
        busy = (("road", "primary"), ("road", "primary"))
        here = [junction(*busy)]
        assert (
            d.delay_s(here, beacon=lambda lon, lat: True, signals={(-77.0, 38.9)})
            == (d.GIVE_WAY_DELAY_S[2])
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
    """The owner's rides, 2026-11: a red at a big suburban crossing held the rider a median
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
        # A stop sign there would cost the ranking its 30 s wait plus 80 s of the junction
        # model's price over the signal's: the button is held 1 s below that, at 109 s.
        wait = d.signal_wait(crossing, suburban=True, stop_extra_s=80.0)
        stop_sign = d.GIVE_WAY_DELAY_S[d.ROAD_RANK["secondary"]] + 80.0
        assert wait.ranked_s == stop_sign - d.BUTTON_BELOW_STOP_S < d.BUTTON_RANKED_S
        # Never below the signal's own ranked wait (a button does not make it quicker), but
        # that wait is itself held 1 s below the stop sign now (hunt J2-4): before 60 s,
        # above the 20 s stop sign; after 19 s, the button with it.
        free = d.signal_wait(crossing, suburban=True, stop_extra_s=0.0)
        assert (free.ranked_s, free.signal_ranked_s) == (19.0, 19.0)

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
        stop_sign_s = d.GIVE_WAY_DELAY_S[d.ROAD_RANK["primary"]] + extra_s
        assert run.button
        assert run.ranked_s == 120.0 < stop_sign_s
        assert run.red_s == 45.0


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

    def test_a_button_crossing_on_road_bike_ranks_ten_minutes_below_half_the_stop_sign(
        self,
    ) -> None:
        """The owner, 2026-11-08: "Call that 10 minutes on a road bike in pain level. ...
        Just make sure it's less than half a stop sign against an uncontrolled busy road."
        """
        crossing = suburban_signal(*PRIMARY)
        (run,) = d.waits([crossing], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 400.0})
        assert run.button and run.ranked_s == 120.0
        # Before: held at 5x the 45 s red, 225 s; after: ten minutes.
        assert 3.0 * d.ranked_s([run], 3.0) == d.ROAD_BIKE_BUTTON_S == 600.0
        # Less than half the stop sign there at Road Bike's weight: its 30 s and the 400 s.
        assert 3.0 * d.ranked_s([run], 3.0) < 3.0 * (30.0 + 400.0) / 2.0
        # A cheaper stop sign (30 + 50 s, 240 s at 3x): held 1 s below its half.
        (cheap,) = d.waits([crossing], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 50.0})
        assert 3.0 * d.ranked_s([cheap], 3.0) == 3.0 * 80.0 / 2.0 - 1.0
        # Not known: ten minutes.
        (unpriced,) = d.waits([crossing], suburban=everywhere)
        assert 3.0 * d.ranked_s([unpriced], 3.0) == 600.0
        # Off Road Bike's weight, the two minutes stand.
        assert d.ranked_s([run]) == 120.0

    def test_a_suburban_signal_never_ranks_above_the_stop_sign_across_the_same_road(
        self,
    ) -> None:
        """Hunt J2-4: on Road Bike (and at the traffic-tolerant end of the slider), the
        suburban 2x put a signal above the stop sign a block away across the same road."""
        tertiary_rider = {"in_class": "tertiary", "out_class": "tertiary"}
        crossing = suburban_signal(*SECONDARY, **tertiary_rider)
        # A stop sign across the secondary: 20 s and 13 s of the model's price over the signal
        # (LTS 3 at Road Bike's 25 km/h, the slider at 0.625): 99 s at 3x.
        (run,) = d.waits([crossing], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 13.0})
        assert not run.button
        # Before: 3 x 60 = 180 s, above the 99 s stop sign; after: below it.
        assert 3.0 * d.ranked_s([run], 3.0) == 3.0 * 32.0 < 3.0 * 33.0
        # At 1x too: before 60 s against the 33 s stop sign; after 32 s.
        assert d.ranked_s([run]) == 32.0
        # The time shown is the average pass, unchanged.
        assert run.seconds == 15.0
        # Riding along the road through its signal, no road crossed: nothing to compare.
        along = suburban_signal(
            ("road", "residential"), in_class="secondary", out_class="secondary"
        )
        (run,) = d.waits([along], suburban=everywhere, stop_extra_s={(-77.0, 38.9): 0.0})
        assert run.ranked_s == 60.0

    def test_at_1x_nothing_is_capped(self) -> None:
        tagged = suburban_signal(
            *PRIMARY, in_use="pedestrian_crossing", out_use="pedestrian_crossing", in_way=77
        )
        (run,) = d.waits([tagged], buttons={77})
        assert d.ranked_s([run]) == 120.0


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
        # A give-way 40 m on from a signal is still a stop of its own.
        give_way = at(junction(*PRIMARY), 140.0, -76.9995)
        assert len(d.waits([at(suburban_signal(*PRIMARY), 100.0, -77.0), give_way])) == 2

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

    def test_the_button_cue_is_at_the_button_signal_not_the_runs_first_junction(self) -> None:
        """The signal review, 2026-11-08: a run that begins at a stop sign or a stop line
        short of the button signal put Ride's "Light may need a button press" there."""
        from core import routing

        stop_first = at(junction(*SECONDARY), 90.0, -77.0002)
        button = at(suburban_signal(*SECONDARY), 110.0, -77.0)
        (run,) = d.waits([stop_first, button], suburban=everywhere)
        assert run.button and (run.m, run.lon) == (90.0, -77.0002)
        assert run.button_at == (110.0, -77.0, 38.9)
        cue = routing.light_buttons([run], 1000.0, 1000.0)
        # Before: at 90 m and the stop sign's node; after: the signal's.
        assert cue == [{"at_m": 110.0, "lon": -77.0, "lat": 38.9}]
        (plain,) = d.waits([stop_first, at(suburban_signal(*SECONDARY), 110.0, -77.0)])
        assert routing.light_buttons([plain], 1000.0, 1000.0) == []
