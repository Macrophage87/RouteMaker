"""A Mass Ride's signalised crossings, read as groups (OWNER-DECISIONS 233, 234, 235).

The owner, 2026-10-03, item 233: "Actually, I like merging the runs, that sounds
good." Item 234: "I'd say we'd want some level of clumpings, especially in DC,
given the diagional streets. I'd say something like a quarter mile or so of
clumping." Item 235: "Unsignalled crossings only really matter if it's a
higher-stress road. DC has about 10 road crossings per mile plus alleys. Not all
have lights. Ideally we should be on the higher volume road anyways."

Pure: `routemaker.intersections` (the group reading of `assess` and
`assess_route`), `routemaker.describe` (the entries) and `core.routing`'s two
row builders. No router, no database.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from core import routing
from routemaker import describe as d
from routemaker import intersections as m
from routemaker.intersections import Control, Junction, Movement, Road

MILE = 1609.344
QUIET = Road(2)

STREETS = [
    "17th Street Northwest",
    "15th Street Northwest",
    "14th Street Northwest",
    "13th Street Northwest",
    "12th Street Northwest",
    "11th Street Northwest",
]


def road(name: str, tier: int = 3, **fields) -> Road:
    return Road(
        tier,
        speed_mph=30,
        lanes=2,
        names=frozenset({name.lower()}),
        display=(name,),
        ways=frozenset({sum(map(ord, name))}),
        **fields,
    )


def junction(**fields) -> Junction:
    base = {
        "m": 0.0,
        "lon": -77.0,
        "lat": 38.9,
        "movement": Movement.STRAIGHT,
        "incoming": QUIET,
        "outgoing": QUIET,
    }
    return Junction(**(base | fields))


def crossing(at_m: float, name: str, tier: int = 3, control=Control.SIGNAL) -> Junction:
    return junction(m=at_m, crossed=(road(name, tier),), control=control)


def route(*junctions: Junction) -> list[m.Event]:
    return m.assess_route(list(junctions), group=True)


def spaced(gap_m: float, *tiers: int, control=Control.SIGNAL) -> list[Junction]:
    return [
        crossing(i * gap_m, STREETS[i % len(STREETS)], tier, control)
        for i, tier in enumerate(tiers)
    ]


def groups_of(events: list[m.Event]) -> list[int | None]:
    return [e.group for e in events]


class TestWhichCrossingsJoin:
    def test_a_quarter_mile_is_the_named_distance(self) -> None:
        assert m.GROUP_WITHIN_M == pytest.approx(MILE / 4, abs=1.5)

    def test_consecutive_signalised_crossings_within_a_quarter_mile_are_one_group(self) -> None:
        events = route(*spaced(300.0, 3, 3, 4, 3, 4, 3))
        assert groups_of(events) == [1] * 6

    def test_a_run_of_one_is_not_a_group(self) -> None:
        assert groups_of(route(*spaced(300.0, 3))) == [None]

    def test_two_are_a_group(self) -> None:
        assert groups_of(route(*spaced(300.0, 3, 4))) == [1, 1]

    def test_each_is_measured_from_the_one_before_not_from_the_first(self) -> None:
        """Six crossings 350 m apart span 1,750 m, over a mile: still one group."""
        events = route(*spaced(350.0, 3, 3, 3, 3, 3, 3))
        assert groups_of(events) == [1] * 6
        assert events[-1].m - events[0].m > MILE

    def test_the_gap_is_inclusive_at_the_limit_and_breaks_just_past_it(self) -> None:
        at = m.GROUP_WITHIN_M
        assert groups_of(route(*spaced(at, 3, 3))) == [1, 1]
        assert groups_of(route(*spaced(at + 1.0, 3, 3))) == [None, None]

    def test_a_long_gap_splits_one_run_into_two_numbered_in_route_order(self) -> None:
        near = spaced(200.0, 3, 3, 3)
        far = [crossing(1500.0 + i * 200.0, f"{n}th Street", 4) for i, n in enumerate((8, 7))]
        assert groups_of(route(*near, *far)) == [1, 1, 1, 2, 2]

    def test_the_street_does_not_matter_diagonals_and_circles_join(self) -> None:
        names = ["Pennsylvania Avenue Northwest", "Washington Circle", "K Street Northwest"]
        events = route(*(crossing(i * 250.0, n) for i, n in enumerate(names)))
        assert groups_of(events) == [1, 1, 1]

    def test_the_same_street_crossed_again_joins(self) -> None:
        events = route(crossing(0, "K Street NW"), crossing(300, "K Street NW"))
        assert groups_of(events) == [1, 1]

    def test_an_unsignalised_flagged_crossing_stands_alone_and_breaks_the_run(self) -> None:
        events = route(
            crossing(0, "A Street", 3),
            crossing(150, "B Street", 3),
            crossing(300, "C Street", 4, Control.NONE),
            crossing(450, "D Street", 3),
            crossing(600, "E Street", 3),
        )
        assert [(e.m, e.group) for e in events] == [
            (0, 1),
            (150, 1),
            (300, None),
            (450, 2),
            (600, 2),
        ]

    def test_an_unsignalised_one_between_two_signalised_leaves_both_alone(self) -> None:
        events = route(
            crossing(0, "A Street"),
            crossing(150, "B Street", 4, Control.NONE),
            crossing(300, "C Street"),
        )
        assert groups_of(events) == [None, None, None]

    @pytest.mark.parametrize("control", [Control.STOP, Control.CROSS_STOP, Control.ALL_STOP])
    def test_a_sign_is_not_a_signal(self, control) -> None:
        events = route(
            crossing(0, "A Street"),
            crossing(150, "B Street", 4, control),
            crossing(300, "C Street"),
        )
        assert all(e.group is None for e in events)

    def test_a_turn_at_a_signal_is_not_a_crossing_and_ends_the_run(self) -> None:
        turn = junction(
            m=300.0,
            movement=Movement.LEFT,
            incoming=QUIET,
            outgoing=road("Constitution Avenue", 4),
            control=Control.SIGNAL,
        )
        events = route(
            crossing(0, "A Street"),
            crossing(150, "B Street"),
            turn,
            crossing(450, "C Street"),
            crossing(600, "D Street"),
        )
        assert [(e.kind, e.group) for e in events] == [
            ("crossing", 1),
            ("crossing", 1),
            ("left_onto", None),
            ("crossing", 2),
            ("crossing", 2),
        ]

    def test_a_left_off_a_busy_road_at_a_signal_is_a_turn_and_ends_the_run(self) -> None:
        off = junction(
            m=300.0,
            movement=Movement.LEFT,
            incoming=road("Constitution Avenue", 4),
            outgoing=QUIET,
            control=Control.SIGNAL,
        )
        events = route(
            crossing(0, "A Street"),
            crossing(150, "B Street"),
            off,
            crossing(450, "C Street"),
            crossing(600, "D Street"),
        )
        assert [(e.kind, e.group) for e in events] == [
            ("crossing", 1),
            ("crossing", 1),
            ("left_from", None),
            ("crossing", 2),
            ("crossing", 2),
        ]

    def test_signalised_crossings_nearer_than_a_junction_merge_are_one_crossing(self) -> None:
        """The two carriageways of one avenue are one junction first (`merge_nearby`), so
        they count once towards a group."""
        events = route(crossing(0, "A Street"), crossing(20, "A Street"), crossing(300, "B Street"))
        assert len(events) == 2
        assert groups_of(events) == [1, 1]

    def test_it_is_a_mass_ride_reading_only(self) -> None:
        junctions = spaced(200.0, 3, 3, 3)
        assert all(e.group is None for e in m.assess_route(junctions, group=False))

    def test_the_markers_are_unchanged_every_crossing_stays_flagged(self) -> None:
        events = route(*spaced(300.0, 3, 4, 3))
        assert [e.flagged for e in events] == [True, True, True]
        assert [e.severity for e in events] == [m.ORANGE, m.RED, m.ORANGE]

    def test_the_cost_the_router_weighs_is_not_changed_by_grouping(self) -> None:
        grouped = route(*spaced(300.0, 3, 4, 3))
        alone = [m.assess(j, True) for j in spaced(300.0, 3, 4, 3)]
        assert [e.cost_ft for e in grouped] == [e.cost_ft for e in alone]
        assert m.penalty_m(grouped) == pytest.approx(m.penalty_m(alone))

    def test_unflagged_events_neither_join_nor_end_a_run(self) -> None:
        a, b, c = route(*spaced(200.0, 3, 3, 3))
        hidden = m.Event(
            100.0, 0, 0, "crossing", Movement.STRAIGHT, Control.NONE, 0.0, None, "x", 3, False
        )
        events = m.number_groups([replace(a, group=None), hidden, b, c])
        assert [e.group for e in events] == [1, None, 1, 1]

    def test_a_left_across_a_busy_road_at_a_signal_is_a_crossing_and_joins(self) -> None:
        across = junction(
            m=150.0,
            movement=Movement.LEFT,
            incoming=QUIET,
            outgoing=QUIET,
            crossed=(road("B Street", 4),),
            control=Control.SIGNAL,
        )
        events = route(crossing(0, "A Street"), across, crossing(300, "C Street"))
        assert [(e.kind, e.group) for e in events] == [
            ("crossing", 1),
            ("left_across", 1),
            ("crossing", 1),
        ]

    def test_events_that_are_not_a_mass_rides_are_never_numbered(self) -> None:
        """Only a Mass Ride's events (`group_severity`) can join, whoever asks."""
        events = [
            m.Event(
                i * 200.0,
                0,
                0,
                "crossing",
                Movement.STRAIGHT,
                Control.SIGNAL,
                900.0,
                m.ORANGE,
                "x",
                3,
                True,
            )
            for i in range(3)
        ]
        assert all(e.flagged and not e.group_severity for e in events)
        assert [e.group for e in m.number_groups(events)] == [None, None, None]


class TestTheGroup:
    def numbered(self, *tiers: int) -> m.CrossingGroup:
        (group,) = m.crossing_groups(route(*spaced(300.0, *tiers)))
        return group

    def test_the_severity_is_the_worst_member(self) -> None:
        assert self.numbered(3, 3, 3).severity == m.ORANGE
        assert self.numbered(3, 4, 3).severity == m.RED
        assert self.numbered(3, 5, 3).severity == m.RED

    def test_an_avoid_road_counts_with_the_lts_4_ones(self) -> None:
        assert self.numbered(3, 4, 5, 3).lts4 == 2

    def test_count_and_span(self) -> None:
        group = self.numbered(3, 3, 4, 3)
        assert (group.count, group.from_m, group.to_m) == (4, 0.0, 900.0)

    def test_groups_are_numbered_in_route_order(self) -> None:
        events = route(*spaced(300.0, 3, 3), crossing(5000, "X Street"), crossing(5200, "Y Street"))
        assert [g.number for g in m.crossing_groups(events)] == [1, 2]

    def test_no_events_no_groups(self) -> None:
        assert m.crossing_groups([]) == []


def named(streets: list[str], tiers: list[int], gap_m: float = 300.0) -> list[m.Event]:
    return route(
        *(crossing(i * gap_m, s, t) for i, (s, t) in enumerate(zip(streets, tiers, strict=True)))
    )


class TestWording:
    def test_the_owners_example(self) -> None:
        events = named(STREETS, [3, 3, 4, 3, 4, 3], gap_m=MILE * 0.12)
        (group,) = m.crossing_groups(events)
        text = d.group_words(group, MILE * 1.0, MILE * 1.6)
        assert text == (
            "1.0 to 1.6 mi (1.6 to 2.6 km): 6 signalised crossings (17th Street Northwest, "
            "15th Street Northwest, 14th Street Northwest and 3 more), 2 of LTS 4 roads"
        )

    def test_the_sentence_adds_the_severity_in_words(self) -> None:
        events = named(STREETS, [3, 3, 4, 3, 4, 3])
        (group,) = m.crossing_groups(events)
        text = d.group_sentence(group, MILE, MILE * 1.6)
        assert text.endswith("2 of LTS 4 roads (Very high stress junctions).")
        orange = named(STREETS[:3], [3, 3, 3])
        (low,) = m.crossing_groups(orange)
        assert d.group_sentence(low, 0, 600).endswith("(Higher stress junctions).")

    def test_three_streets_are_listed_with_and(self) -> None:
        (group,) = m.crossing_groups(named(STREETS[:3], [3, 3, 3]))
        assert "(17th Street Northwest, 15th Street Northwest and 14th Street Northwest)" in (
            d.group_words(group, 0, 600)
        )

    def test_two_streets(self) -> None:
        (group,) = m.crossing_groups(named(STREETS[:2], [3, 3]))
        assert "(17th Street Northwest and 15th Street Northwest)" in d.group_words(group, 0, 300)

    def test_exactly_four_streets_say_and_1_more(self) -> None:
        (group,) = m.crossing_groups(named(STREETS[:4], [3] * 4))
        assert "14th Street Northwest and 1 more)" in d.group_words(group, 0, 900)

    def test_a_street_crossed_twice_is_named_once(self) -> None:
        (group,) = m.crossing_groups(
            named(["K Street", "L Street", "K Street", "M Street"], [3] * 4)
        )
        assert d.group_streets(group) == ["K Street", "L Street", "M Street"]
        assert "(K Street, L Street and M Street)" in d.group_words(group, 0, 900)

    def test_a_group_with_no_lts_4_says_nothing_of_it(self) -> None:
        (group,) = m.crossing_groups(named(STREETS[:3], [3, 3, 3]))
        assert "LTS 4" not in d.group_words(group, 0, 600)

    def test_one_lts_4_road(self) -> None:
        (group,) = m.crossing_groups(named(STREETS[:3], [3, 4, 3]))
        assert d.group_words(group, 0, 600).endswith(", 1 of them an LTS 4 road")

    def test_all_lts_4(self) -> None:
        (group,) = m.crossing_groups(named(STREETS[:3], [4, 4, 4]))
        assert d.group_words(group, 0, 600).endswith(", all of LTS 4 roads")

    def test_unnamed_roads_are_left_out_of_the_street_list(self) -> None:
        unnamed = Road(3, speed_mph=30, lanes=2, names=frozenset({"way 5"}), display=("way 5",))
        events = route(
            junction(m=0.0, crossed=(unnamed,), control=Control.SIGNAL),
            crossing(300, "K Street"),
        )
        (group,) = m.crossing_groups(events)
        assert d.group_streets(group) == ["K Street"]

    def test_no_names_at_all(self) -> None:
        bare = Road(3, speed_mph=30, lanes=2)
        events = route(
            junction(m=0.0, crossed=(bare,), control=Control.SIGNAL),
            junction(m=300.0, crossed=(bare,), control=Control.SIGNAL),
        )
        (group,) = m.crossing_groups(events)
        assert d.group_words(group, 0, 300).endswith(": 2 signalised crossings")

    def test_a_short_span_says_its_length(self) -> None:
        (group,) = m.crossing_groups(named(STREETS[:2], [3, 3], gap_m=100.0))
        assert d.group_words(group, 1609.344, 1709.344).startswith(
            "1.0 mi (1.6 km), for 330 ft (100 m): 2 signalised crossings"
        )


def atoms(metres: float = 3200.0, name: str = "Constitution Avenue Northwest"):
    return [d.Atom(metres / 53, "4", "none", (name,), "road", 90.0, 90.0) for _ in range(53)]


def both(events: list[m.Event], metres: float = 3200.0):
    return d.describe_both([atoms(metres)], events, metres)


def junction_entries(entries: list[dict]) -> list[dict]:
    return [e for e in entries if e["kind"] == "junction"]


class TestInTheDescription:
    def events(self) -> list[m.Event]:
        return named(STREETS, [3, 3, 4, 3, 4, 3], gap_m=250.0)

    def test_the_group_is_one_entry_in_the_full_list_and_the_overview(self) -> None:
        full, short = both(self.events())
        for entries in (full, short):
            (entry,) = junction_entries(entries)
            assert "6 signalised crossings" in entry["text"]
            assert entry["group"] == {
                "number": 1,
                "count": 6,
                "lts4": 2,
                "streets": STREETS[:3],
                "more": 3,
            }
            assert entry["severity"] == "red"
            assert entry["text"].endswith("(Very high stress junctions).")

    def test_the_entry_names_its_span(self) -> None:
        full, _short = both(self.events())
        (entry,) = junction_entries(full)
        assert (entry["from_m"], entry["to_m"]) == (0, 1250)
        assert entry["text"].startswith("0.0 to 0.8 mi (0.0 to 1.2 km): 6 signalised crossings")

    def test_without_grouping_each_crossing_is_its_own_entry(self) -> None:
        plain = [m.assess(j, True) for j in spaced(250.0, 3, 3, 4)]
        full, _short = both(plain)
        assert len(junction_entries(full)) == 3
        assert all(e["group"] is None for e in full)

    def test_an_unsignalised_crossing_inside_the_span_is_its_own_entry(self) -> None:
        events = route(
            crossing(0, "A Street"),
            crossing(200, "B Street"),
            crossing(400, "C Street", 4, Control.NONE),
            crossing(600, "D Street"),
            crossing(800, "E Street"),
        )
        full, short = both(events)
        for entries in (full, short):
            rows = junction_entries(entries)
            assert [bool(r["group"]) for r in rows] == [True, False, True]
            assert "Cross C Street (LTS 4), no signal mapped" in rows[1]["text"]

    def test_entries_stay_in_route_order(self) -> None:
        full, _short = both(self.events())
        order = [e["from_m"] for e in full]
        assert order == sorted(order)

    def test_a_group_member_that_is_the_turn_into_a_stretch_is_counted_not_dropped(self) -> None:
        legs = [
            [d.Atom(1000.0, "4", "none", ("A Street",), "road", 90.0, 90.0)]
            + [d.Atom(1000.0, "3", "none", ("B Street",), "road", 0.0, 0.0)]
        ]
        events = route(
            crossing(700, "C Street"), crossing(1000, "B Street"), crossing(1200, "D Street")
        )
        assert [e.group for e in events] == [1, 1, 1]
        full, _short = d.describe_both(legs, events, 2000.0)
        (entry,) = junction_entries(full)
        assert entry["group"]["count"] == 3
        stretch = [e for e in full if e["kind"] == "stretch"][1]
        assert stretch["turn"]["control"] == "signal"

    def test_the_text_reads_as_one_sentence(self) -> None:
        full, _ = both(self.events())
        (entry,) = junction_entries(full)
        assert entry["text"].count(": ") == 1 and entry["text"].endswith(".")

    def test_every_other_entry_has_no_group(self) -> None:
        full, short = both(self.events())
        for entries in (full, short):
            assert all(e["group"] is None for e in entries if e["kind"] != "junction")


class TestInTheApi:
    def flagged(self) -> list[m.Event]:
        return named(STREETS, [3, 3, 4, 3, 4, 3], gap_m=250.0)

    def test_every_row_has_its_group_and_the_junctions_are_all_still_there(self) -> None:
        rows = routing._intersection_rows(self.flagged())
        assert len(rows) == 6
        assert [r["group"] for r in rows] == [1] * 6

    def test_the_group_rows_say_where_which_and_how_bad(self) -> None:
        (row,) = routing._intersection_groups(self.flagged())
        text = row["text"]
        assert row == {
            "group": 1,
            "from_m": 0,
            "to_m": 1250,
            "count": 6,
            "lts4": 2,
            "streets": STREETS[:3],
            "more": 3,
            "severity": "red",
            "members": [0, 1, 2, 3, 4, 5],
            "text": text,
        }
        assert text.startswith("0.0 to 0.8 mi (0.0 to 1.2 km): 6 signalised crossings (")
        assert "Very high" not in text

    def test_members_index_the_flagged_list(self) -> None:
        events = route(
            crossing(0, "A Street", 3, Control.NONE),
            crossing(300, "B Street"),
            crossing(500, "C Street"),
        )
        rows = routing._intersection_rows(events)
        (group,) = routing._intersection_groups(events)
        assert group["members"] == [1, 2]
        assert [rows[i]["group"] for i in group["members"]] == [1, 1]
        assert rows[0]["group"] is None

    def test_members_count_only_the_flagged_events(self) -> None:
        a, b, c = route(*spaced(200.0, 3, 3, 3))
        quiet = m.Event(
            100.0, 0, 0, "crossing", Movement.STRAIGHT, Control.NONE, 0.0, None, "x", 3, False
        )
        events = [quiet, a, b, c]
        (group,) = routing._intersection_groups(events)
        assert group["members"] == [0, 1, 2]
        assert [r["group"] for r in routing._intersection_rows(events)] == [1, 1, 1]

    def test_more_streets_than_three_are_counted_not_listed(self) -> None:
        (group,) = routing._intersection_groups(self.flagged())
        assert (len(group["streets"]), group["more"]) == (3, 3)
        (four,) = routing._intersection_groups(named(STREETS[:4], [3] * 4))
        assert (len(four["streets"]), four["more"]) == (3, 1)
        (three,) = routing._intersection_groups(named(STREETS[:3], [3] * 3))
        assert (len(three["streets"]), three["more"]) == (3, 0)

    def test_no_groups_is_an_empty_list(self) -> None:
        assert routing._intersection_groups([]) == []
        assert routing._intersection_groups(route(*spaced(300.0, 3))) == []


class TestFlaggingOnAMassRide:
    """Item 235: only crossings of, or turns involving, an LTS 3+ road are flagged. Quiet
    side streets, alleys and riding along the busier road past side streets never are,
    signalised or not."""

    ALL_CONTROLS = list(Control)

    @pytest.mark.parametrize("control", ALL_CONTROLS)
    @pytest.mark.parametrize("tier", [None, 1, 2])
    def test_a_crossing_of_a_quiet_street_or_an_alley_is_never_flagged(self, tier, control) -> None:
        street = Road(tier, speed_mph=20, lanes=1, names=frozenset({"quiet st"}))
        assert m.assess(junction(crossed=(street,), control=control), group=True) is None
        assert m.assess(junction(crossed=(street,), control=control), group=False) is None

    @pytest.mark.parametrize("control", ALL_CONTROLS)
    def test_an_alley_is_never_flagged_whatever_it_is_called(self, control) -> None:
        alley = Road(1, speed_mph=10, lanes=1, names=frozenset({"way 9"}), oneway=False)
        for movement in Movement:
            j = junction(movement=movement, crossed=(alley,), control=control, outgoing=alley)
            assert m.assess(j, group=True) is None

    @pytest.mark.parametrize("control", ALL_CONTROLS)
    @pytest.mark.parametrize("movement", list(Movement))
    def test_a_quiet_street_meeting_a_quiet_street_is_never_flagged(
        self, movement, control
    ) -> None:
        j = junction(movement=movement, incoming=Road(2), outgoing=Road(1), control=control)
        assert m.assess(j, group=True) is None

    @pytest.mark.parametrize("control", ALL_CONTROLS)
    def test_riding_along_the_busier_road_past_side_streets_is_never_flagged(self, control) -> None:
        avenue = road("Constitution Avenue", 4)
        side = Road(2, names=frozenset({"side st"}))
        j = junction(
            incoming=avenue, outgoing=avenue, crossed=(side,), control=control, continues=True
        )
        assert m.assess(j, group=True) is None

    @pytest.mark.parametrize("control", [Control.NONE, Control.CROSS_STOP])
    def test_nor_past_a_lesser_busy_cross_street_where_the_rider_has_priority(
        self, control
    ) -> None:
        avenue = road("Constitution Avenue", 4)
        cross = road("Cross Street", 3)
        j = junction(
            incoming=avenue, outgoing=avenue, crossed=(cross,), control=control, continues=True
        )
        assert m.assess(j, group=True) is None

    def test_a_mile_of_a_busier_road_past_ten_side_streets_is_no_flags_at_all(self) -> None:
        avenue = road("Constitution Avenue", 4)
        side = Road(2, names=frozenset({"side st"}))
        alley = Road(1, names=frozenset({"way 1"}))
        junctions = [
            junction(
                m=i * (MILE / 10),
                incoming=avenue,
                outgoing=avenue,
                crossed=(alley if i % 2 else side,),
                control=Control.SIGNAL if i % 3 == 0 else Control.NONE,
                continues=True,
            )
            for i in range(10)
        ]
        assert m.assess_route(junctions, group=True) == []

    def test_a_busy_cross_street_is_flagged_signalised_or_not(self) -> None:
        for control in (Control.SIGNAL, Control.NONE, Control.STOP):
            assert m.assess(crossing(0, "Wisconsin Avenue", 3, control), group=True) is not None

    def test_a_turn_off_a_quiet_street_onto_a_busy_one_is_flagged(self) -> None:
        j = junction(
            movement=Movement.LEFT,
            incoming=QUIET,
            outgoing=road("Wisconsin Avenue"),
            control=Control.SIGNAL,
        )
        assert m.assess(j, group=True).kind == "left_onto"
