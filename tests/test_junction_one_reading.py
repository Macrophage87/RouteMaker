"""One reading of each junction across the two junction models (the independent review of
2026-11-13): the price (`routemaker.intersections`) and the time and ranked wait
(`routemaker.junction_delay`) are made from the same answers.

- A signal never ranks dearer than a stop sign across the same road, at any wait weight
  (Broach, Dill and Gliebe 2012 and Furth both order them so).
- The time shown has a stop exactly where the price has one, in both directions.
- The wait priced is the wait shown, capped the same way.
- A divided road is one crossing for the price and for the wait, whatever its median.

Each test goes through the functions a plan goes through (`assess_route`, `give_ways`,
`junction_delay.waits`, `ranked_s`), on roads made from a grid of facts, none of them a
real road."""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from routemaker import intersections as m
from routemaker import junction_delay as d
from routemaker import ridetime
from routemaker import trace_junctions as t
from routemaker.intersections import Control, GiveWay, Junction, Movement, Road

LON, LAT = -77.0, 38.9
QUIET = Road(1, speed_mph=25.0, lanes=1, oneway=False)


def raw(
    classes: tuple[str, ...],
    movement: Movement = Movement.STRAIGHT,
    signal: bool = False,
    own: str = "residential",
    out: str | None = None,
    metres: float = 100.0,
    lon: float = LON,
    ways: tuple[int, int] = (1, 1),
) -> t.RawJunction:
    """The traced junction the waits read: the rider on a road of class `own` (leaving on
    `out`), the other edges at the node of `classes`."""
    return t.RawJunction(
        m=metres,
        lon=lon,
        lat=LAT,
        in_edge_id=None,
        in_way=ways[0],
        out_way=ways[1],
        movement=movement,
        in_use="road",
        out_use="road",
        others=tuple(("road", False) for _ in classes),
        in_class=own,
        out_class=out or own,
        other_classes=classes,
        signal=signal,
        in_heading=90.0,
        other_headings=(0.0, 180.0)[: len(classes)],
    )


def key(junction: t.RawJunction) -> tuple[float, float, int, int]:
    return (junction.lon, junction.lat, junction.in_way, junction.out_way)


def crossing(road: Road, control: Control, **more) -> Junction:
    return Junction(100.0, LON, LAT, Movement.STRAIGHT, QUIET, QUIET, (road,), control, **more)


ROADS = [
    Road(tier, speed_mph=speed, lanes=lanes, oneway=False, aadt=aadt)
    for tier, speed, lanes, aadt in itertools.product(
        (2, 3, 4), (25.0, 30.0, 35.0, 40.0, 45.0), (1, 2, 3), (None, 3_000, 9_000, 20_000, 38_000)
    )
]
CLASSES = ("primary", "secondary", "tertiary", "residential")
# What a foot of the junction model's price is worth in seconds of waiting
# (`refine.stop_wait_s_per_ft`): about 0.061 at the Default setting; here from a third of
# it to three times.
S_PER_FT = (0.02, 0.061, 0.18)
WHENS = (None, ridetime.WEEKDAY_RUSH, "night")


def everywhere(_lon: float, _lat: float) -> bool:
    return True


def ranked_total(
    junction: Junction, traced: t.RawJunction, s_per_ft: float, weight: float, when, suburban
) -> float:
    """What one junction costs the ranking, in weighted seconds of waiting, as
    `core.refine` counts it (`junction_over_cap_m`, short of its cap): with no signal the
    larger of the price and the wait, at a signal their sum."""
    events = m.assess_route([junction], when=when)
    (reading,) = m.give_ways([junction], when)
    extra = {p: ft * s_per_ft for p, ft in m.stop_extra_ft(events).items()}
    own = {p: ft * s_per_ft for p, ft in m.signal_own_ft(events).items()}
    found = d.waits(
        [traced],
        signals=m.signal_points(events),
        suburban=everywhere if suburban else None,
        big=m.big_signal_points(events),
        own_big=m.own_big_signal_points(events),
        stop_extra_s=extra,
        signal_own_s=own,
        when=when,
        given_way={} if reading is None else {key(traced): reading},
    )
    price = weight * s_per_ft * sum(event.cost_ft for event in events)
    wait = weight * d.ranked_s(found, weight)
    return price + wait if junction.control is Control.SIGNAL else max(price, wait)


class TestASignalNeverRanksDearerThanAStopSignAcrossTheSameRoad:
    @pytest.mark.parametrize("cls", CLASSES)
    @pytest.mark.parametrize("suburban", [False, True])
    @pytest.mark.parametrize("weight", [1.0, 3.0])
    def test_straight_across(self, cls, suburban, weight) -> None:
        """Before 2026-11-13 the hold was for wait weights above 1 only, and set against a
        class figure (30, 20 or 12 s): at Default a suburban signal across a 9,000-a-day
        two-lane road ranked 60 s against the stop sign's 23."""
        checked = 0
        for road, s_per_ft, when in itertools.product(ROADS, S_PER_FT, WHENS):
            if not m.by_traffic(crossing(road, Control.STOP)).crossed[0].busy:
                continue
            both = [
                ranked_total(
                    crossing(road, control),
                    raw((cls, cls), signal=control is Control.SIGNAL),
                    s_per_ft,
                    weight,
                    when,
                    suburban,
                )
                for control in (Control.SIGNAL, Control.STOP)
            ]
            assert both[0] <= both[1] + 1e-6, (road, s_per_ft, when, both)
            checked += 1
        assert checked > 300

    @pytest.mark.parametrize("movement", [Movement.LEFT, Movement.RIGHT])
    @pytest.mark.parametrize("weight", [1.0, 3.0])
    def test_turning_onto_it(self, movement, weight) -> None:
        for road, s_per_ft, suburban in itertools.product(ROADS, S_PER_FT, (False, True)):
            if not m._by_traffic(road).busy:
                continue
            both = []
            for control in (Control.SIGNAL, Control.STOP):
                turn = Junction(100.0, LON, LAT, movement, QUIET, road, (road,), control)
                traced = raw(
                    ("secondary",),
                    movement,
                    signal=control is Control.SIGNAL,
                    out="secondary",
                    ways=(1, 2),
                )
                both.append(ranked_total(turn, traced, s_per_ft, weight, None, suburban))
            assert both[0] <= both[1] + 1e-6, (road, s_per_ft, suburban, both)

    def test_the_reviews_case_at_default(self) -> None:
        """Two lanes, 30 mph, 9,000 a day, in the suburbs, at the Default setting."""
        road = Road(3, speed_mph=30.0, lanes=1, oneway=False, aadt=9_000)
        args = (0.061, 1.0, None, True)
        light = ranked_total(
            crossing(road, Control.SIGNAL), raw(("tertiary",) * 2, signal=True), *args
        )
        stop = ranked_total(crossing(road, Control.STOP), raw(("tertiary",) * 2), *args)
        assert light <= stop < d.SUBURBAN_SIGNAL_S * d.SUBURBAN_SIGNAL_WEIGHT


class TestTheTimeHasAStopExactlyWhereThePriceDoes:
    """`give_way` is made of the answers `cost_of` is: `has_way` for who stops, `wait_s`
    for how long."""

    def priced_as_stopped(self, junction: Junction, road: Road) -> bool:
        read = m.by_traffic(junction)
        return not m.has_way(read, read.crossed[0])

    @pytest.mark.parametrize("control", [Control.NONE, Control.STOP, Control.CROSS_STOP])
    @pytest.mark.parametrize("own", [QUIET, Road(3, speed_mph=35.0, lanes=1, oneway=False)])
    def test_both_directions(self, control, own) -> None:
        for road in ROADS:
            junction = replace(crossing(road, control), incoming=own, outgoing=own)
            reading = m.give_way(junction)
            stopped = self.priced_as_stopped(junction, road)
            if reading is None:
                # No answer of the model's: nothing mapped, and no road with a price.
                assert control is Control.NONE and not m._by_traffic(road).busy
                continue
            assert reading.stops is stopped, (control, own, road)
            traced = raw(("primary", "primary"), own="residential")
            (found,) = d.waits([traced], given_way={key(traced): reading}) or [None]
            assert (found is not None) is stopped, (control, own, road)

    def test_a_stop_sign_on_the_riders_side_is_timed_whatever_the_classes_say(self) -> None:
        """Before: the rider on a primary by class crossing a 'residential' road had the
        right of way by the classes alone and was timed nothing at their own stop sign."""
        road = Road(4, speed_mph=40.0, lanes=2, oneway=False, aadt=22_000)
        traced = raw(("residential", "residential"), own="primary")
        assert d.delay_at(traced) == 0.0
        (reading,) = m.give_ways([crossing(road, Control.STOP)])
        (found,) = d.waits([traced], given_way={key(traced): reading})
        assert found.seconds == round(d.STOP_SIGN_S + m.wait_s(road), 1)

    def test_the_cross_traffic_stopping_is_no_stop_whatever_the_classes_say(self) -> None:
        road = Road(4, speed_mph=40.0, lanes=2, oneway=False, aadt=22_000)
        traced = raw(("primary", "primary"))
        assert d.delay_at(traced) > 0.0
        (reading,) = m.give_ways([crossing(road, Control.CROSS_STOP)])
        assert reading == GiveWay(False)
        assert d.waits([traced], given_way={key(traced): reading}) == []

    def test_a_side_path_with_its_roads_priority_is_timed_nothing_at_a_quiet_mouth(self) -> None:
        """Before: a quiet mouth was asked of the classes, and a path (the lowest class)
        stopped at every one."""
        path = Road(1)
        main = Road(4, speed_mph=40.0, lanes=2, oneway=False)
        for mouth in (QUIET, Road(2, speed_mph=35.0, lanes=1, oneway=False)):
            passing = Junction(
                100.0, LON, LAT, Movement.STRAIGHT, path, path, (mouth,),
                path_crossing=True, beside=main,
            )  # fmt: skip
            assert m.give_way(passing) == GiveWay(False)
            assert m.cost_of(m.by_traffic(passing))[0] < m.STOPPED_CROSSING_FT[2]
        # With no road beside it, the model has no answer at a quiet mouth.
        alone = Junction(100.0, LON, LAT, Movement.STRAIGHT, path, path, (QUIET,))
        assert m.give_way(alone) is None


class TestTheWaitPricedIsTheWaitShown:
    def test_one_number_capped_one_way(self) -> None:
        """Before: the price weighed the uncapped wait (599 s on a six-lane road at rush
        hour, 10,560 ft) and the rider was shown 33 s."""
        for road, when in itertools.product(ROADS, WHENS):
            wait = m.wait_s(road, when)
            assert wait <= m.GAP_WAIT_MAX_S
            assert m.gap_ft(road, when) == pytest.approx(m.WAIT_PAIN * wait * m.QUIET_FT_PER_S)
            (reading,) = m.give_ways([crossing(road, Control.STOP)], when)
            assert reading.wait_s == wait
            assert d.read_wait(reading) == round(d.STOP_SIGN_S + wait, 1)
            assert d.gap_wait_s(road, when) == wait
        assert not hasattr(d, "GAP_WAIT_MAX_S")

    def test_a_right_turn_waits_for_the_near_direction_only(self) -> None:
        road = Road(4, speed_mph=35.0, lanes=2, oneway=False, aadt=30_000)
        right = Junction(100.0, LON, LAT, Movement.RIGHT, QUIET, road, (road,), Control.STOP)
        left = replace(right, movement=Movement.LEFT)
        near = m.wait_s(road, None, lanes=2)
        assert m.near_lanes(road, Movement.RIGHT) == 2
        assert m.near_lanes(road, Movement.LEFT) is None
        assert m.give_way(right).wait_s == near < m.give_way(left).wait_s == m.wait_s(road)
        # A one-way road has only its own lanes either way.
        one_way = replace(road, oneway=True)
        assert m.near_lanes(one_way, Movement.RIGHT) is None

    def test_a_left_off_a_busy_road_waits_for_its_oncoming_traffic(self) -> None:
        """Before: the time gave no wait at all to a left off an arterial (the rider had
        the "right of way" over the side street), and the price weighed a gap in all of
        the road's lanes."""
        road = Road(4, speed_mph=35.0, lanes=2, oneway=False, aadt=30_000)
        left = Junction(100.0, LON, LAT, Movement.LEFT, road, QUIET, (road,))
        reading = m.give_way(left)
        oncoming = m.wait_s(road, None, lanes=2)
        assert reading == GiveWay(True, oncoming, stop_sign=False)
        assert 0.0 < oncoming < m.wait_s(road)
        assert d.read_wait(reading) == round(oncoming, 1)
        # A right off it, or straight on along it, waits for nothing.
        assert m.give_way(replace(left, movement=Movement.RIGHT)) in (None, GiveWay(False))
        # Off a one-way road there is no oncoming traffic.
        one_way = replace(left, incoming=replace(road, oneway=True))
        assert m.give_way(one_way) in (None, GiveWay(False))


def carriageways(gap_m: float, control: Control = Control.STOP) -> list[Junction]:
    """A quiet street crossing a divided road: two one-way carriageways of one name,
    `gap_m` apart along the route."""
    half = {"speed_mph": 40.0, "lanes": 2, "oneway": True, "aadt": 15_000}
    name = frozenset({"divided road"})
    return [
        Junction(
            100.0 + place * gap_m,
            LON + place * gap_m / 86_700.0,
            LAT,
            Movement.STRAIGHT,
            QUIET,
            QUIET,
            (Road(4, names=name, ways=frozenset({way}), **half),),
            control,
        )
        for place, way in enumerate((70, 71))
    ]


class TestADividedRoadIsOneCrossingWhateverItsMedian:
    @pytest.mark.parametrize("gap_m", [20.0, 40.0, 44.0, 46.0, 60.0, 90.0])
    def test_one_price_and_one_wait(self, gap_m) -> None:
        """Before: 45 m for the price and 35 m for the wait, so a median a metre wider
        priced and timed the two halves as two whole roads."""
        pair = carriageways(gap_m)
        events = m.assess_route(pair)
        assert len(events) == 1
        near = m.assess_route(carriageways(20.0))
        assert events[0].cost_ft == pytest.approx(near[0].cost_ft)
        first, second = m.give_ways(pair)
        assert first.stops and second == GiveWay(False)
        assert first.wait_s == m.give_ways(carriageways(20.0))[0].wait_s
        traced = [raw(("primary",), metres=j.m, lon=j.lon, ways=(1, 1)) for j in pair]
        readings = dict(zip(map(key, traced), (first, second), strict=True))
        assert len(d.waits(traced, given_way=readings)) == 1

    def test_two_roads_of_different_names_stay_two(self) -> None:
        pair = carriageways(40.0)
        other = replace(pair[1].crossed[0], names=frozenset({"another road"}))
        apart = [pair[0], replace(pair[1], crossed=(other,), m=160.0)]
        assert m.divided_pairs(apart) == {}
        assert len(m.assess_route(apart)) == 2

    def test_the_junction_waits_merge_at_the_junction_models_distance(self) -> None:
        assert d.MERGE_M == d.SIGNAL_MERGE_M == m.MERGE_WITHIN_M


class TestWhoHasPriorityComparesLikeWithLike:
    def test_an_unposted_lane_does_not_outrank_a_posted_busier_road(self) -> None:
        """The review's case: the rider on a lane the map rates 3 with nothing posted,
        crossing a 35 mph road carrying 9,000 a day. The rider's MAP level (3) was set
        against the crossed road's CROSSING level (2.4), and the rider "won": 0 s and a
        priority-side price at a crossing where they give way."""
        lane = Road(3)
        road = Road(3, speed_mph=35.0, lanes=1, oneway=False, aadt=9_000)
        junction = Junction(100.0, LON, LAT, Movement.STRAIGHT, lane, lane, (road,))
        read = m.by_traffic(junction)
        assert not m.has_priority(read, read.crossed[0])
        assert m.give_way(junction).stops
        assert m.cost_of(read)[0] >= m.STOPPED_CROSSING_FT[2]

    def test_both_roads_are_read_on_the_crossing_scale(self) -> None:
        big = Road(4, speed_mph=40.0, lanes=2, oneway=False, aadt=25_000)
        small = Road(2, speed_mph=25.0, lanes=1, oneway=False)
        along = Junction(100.0, LON, LAT, Movement.STRAIGHT, big, big, (small,))
        across = Junction(100.0, LON, LAT, Movement.STRAIGHT, small, small, (big,))
        assert m.has_priority(m.by_traffic(along), m._by_traffic(small))
        assert not m.has_priority(m.by_traffic(across), m._by_traffic(big))
        assert m.priority_level(m._by_traffic(big)) == m.crossing_level(big)


class TestTheStopSignASignalIsHeldBelow:
    """It is the junction model's stop sign for that road: its price over the signal's,
    or its expected wait where that is more, less what the signal itself is charged."""

    def test_the_reading_at_a_signal_is_a_stop_sign_in_its_place(self) -> None:
        road = Road(4, speed_mph=40.0, lanes=2, oneway=False, aadt=22_000)
        (at_signal,) = m.give_ways([crossing(road, Control.SIGNAL)])
        (stopped,) = m.give_ways([crossing(road, Control.STOP)])
        assert at_signal == replace(stopped, at_signal=True)
        assert at_signal.wait_s == m.wait_s(road) > 0

    def test_a_cheap_price_does_not_put_the_stop_sign_below_its_own_wait(self) -> None:
        """At a low junction weight the stop sign's price falls below the seconds a rider
        stands at it; the ranking counts the larger, and so does the hold."""
        road = Road(4, speed_mph=40.0, lanes=2, oneway=False, aadt=22_000)
        junction = crossing(road, Control.SIGNAL)
        events = m.assess_route([junction])
        (reading,) = m.give_ways([junction])
        traced = raw(("primary", "primary"), signal=True)
        s_per_ft = 0.001
        (found,) = d.waits(
            [traced],
            signals=m.signal_points(events),
            stop_extra_s={p: ft * s_per_ft for p, ft in m.stop_extra_ft(events).items()},
            signal_own_s={p: ft * s_per_ft for p, ft in m.signal_own_ft(events).items()},
            given_way={key(traced): reading},
        )
        timed = round(d.STOP_SIGN_S + m.wait_s(road), 1)
        assert found.stop_s == timed > 3260 * s_per_ft
        # Not shown: the time at a signal is the signal's.
        assert found.seconds == d.CITY_PASS_S[None][0]

    def test_what_the_signal_is_charged_itself_comes_off_the_stop_signs_wait(self) -> None:
        """The ranking adds a signal's own price (a left's box turn) to its wait, so the
        wait is held below the stop sign's whole less that price."""
        light = raw(("primary", "primary"), signal=True)
        wait = d.signal_wait(light, stop_extra_s=2.0, stop_wait_s=10.0, signal_own_s=4.0)
        assert wait.stop_s == 6.0
        assert (
            d.signal_wait(light, stop_extra_s=7.0, stop_wait_s=10.0, signal_own_s=4.0).stop_s == 7.0
        )
        assert d.signal_wait(light, stop_extra_s=2.0).stop_s == 2.0
