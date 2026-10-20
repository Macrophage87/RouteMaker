"""The route description (`routemaker.describe`, OWNER-DECISIONS 220): stretches
merged from the traced pieces, the wording of each, the turns and junctions, the
via-point split, and the totals. Pure: no router, no database."""

from __future__ import annotations

from dataclasses import replace

import pytest

from routemaker import describe as d
from routemaker.intersections import Control, Event, Movement

FT = 0.3048


def road(name, tier, metres, h_in=0.0, h_out=0.0, facility="none", use="road", names=None):
    """A stretch of one street, cut into pieces about 60 m long, as the trace's
    vertices cut it. `names` overrides `name` (a street with two names)."""
    count = max(1, round(metres / 60))
    listed = tuple(names) if names is not None else ((name,) if name else ())
    return [
        d.Atom(
            metres / count,
            str(tier),
            facility,
            listed,
            use,
            h_in,
            h_out,
        )
        for _ in range(count)
    ]


def event(
    m,
    movement="left",
    control=Control.SIGNAL,
    severity="orange",
    kind="left_onto",
    flagged=True,
    names=("wisconsin avenue",),
    tier=3,
):
    return Event(
        m=m,
        lon=-77.0,
        lat=38.9,
        kind=kind,
        movement=Movement(movement),
        control=control,
        cost_ft=1000.0,
        severity=severity,
        reason="x",
        crossed_tier=tier,
        flagged=flagged,
        road_names=frozenset(names),
    )


def flat(*parts):
    return [atom for part in parts for atom in part]


def texts(entries):
    return [e["text"] for e in entries]


# A realistic trip: a trail, a busy avenue, a quiet street, and a bike lane.
def bethesda():
    return flat(
        road("Capital Crescent Trail", 1, 1931, 90, 90, facility="path", use="cycleway"),
        # Left (90 -> 0 is anticlockwise) onto Bethesda Avenue, LTS 3.
        road("Bethesda Avenue", 3, 480, 0, 0),
        # Right onto a quiet street.
        road("Willow Lane", 1, 800, 90, 90),
        road("Woodmont Avenue", 2, 600, 90, 90, facility="lane"),
    )


class TestMerge:
    def test_one_street_one_tier_is_one_stretch(self):
        entries = d.describe([road("Capital Crescent Trail", 1, 1931, facility="path")])
        assert len(entries) == 1
        assert entries[0]["text"] == (
            "0.0 to 1.2 mi (0.0 to 1.9 km): Capital Crescent Trail, traffic-free path."
        )
        assert entries[0]["from_m"] == 0 and entries[0]["to_m"] == 1931

    def test_the_example_trip(self):
        entries = d.describe([bethesda()])
        assert texts(entries) == [
            "0.0 to 1.2 mi (0.0 to 1.9 km): Capital Crescent Trail, traffic-free path.",
            "1.2 to 1.5 mi (1.9 to 2.4 km): Left onto Bethesda Avenue, busy road (LTS 3).",
            "1.5 to 2.0 mi (2.4 to 3.2 km): Right onto Willow Lane, low stress (LTS 1).",
            "2.0 to 2.4 mi (3.2 to 3.8 km): Continue onto Woodmont Avenue, "
            "fairly low stress (LTS 2), painted bike lane.",
        ]

    def test_a_new_tier_on_the_same_street_is_a_new_stretch_without_a_turn(self):
        entries = d.describe(
            [flat(road("Old Georgetown Road", 2, 700), road("Old Georgetown Road", 4, 500))]
        )
        assert texts(entries) == [
            "0.0 to 0.4 mi (0.0 to 0.7 km): Old Georgetown Road, fairly low stress (LTS 2).",
            "0.4 to 0.7 mi (0.7 to 1.2 km): Continue on Old Georgetown Road, "
            "heavy traffic (LTS 4).",
        ]
        assert entries[1]["turn"] is None

    def test_a_new_facility_is_a_new_stretch(self):
        entries = d.describe(
            [
                flat(
                    road("Main St", 2, 700, facility="none"),
                    road("Main St", 2, 700, facility="lane"),
                )
            ]
        )
        assert [e["facility"] for e in entries] == [None, "lane"]

    def test_a_street_with_two_names_is_one_street(self):
        entries = d.describe(
            [
                flat(
                    road(None, 3, 500, names=("Rockville Pike", "MD 355")),
                    road(None, 3, 500, names=("MD 355",)),
                )
            ]
        )
        assert len(entries) == 1
        assert entries[0]["street"] == "Rockville Pike"

    def test_a_route_number_is_not_preferred_to_a_name(self):
        assert d.street_label(("MD 355", "Rockville Pike")) == "Rockville Pike"
        assert d.street_label(("MD 355",)) == "MD 355"
        assert d.street_label(()) is None

    def test_a_mid_route_name_change_at_the_same_tier_is_a_turn_entry(self):
        entries = d.describe([flat(road("A St", 1, 500), road("B St", 1, 500, 0, 0))])
        assert len(entries) == 2 and entries[1]["turn"]["onto"] == "B St"


class TestTiny:
    def test_a_short_quiet_stretch_is_folded_into_the_longer_neighbour(self):
        entries = d.describe(
            [flat(road("A St", 1, 800), road("Alley", 1, 60), road("B St", 1, 400))]
        )
        # 60 m (197 ft) joins A St, the longer one.
        assert [e["street"] for e in entries] == ["A St", "B St"]
        assert entries[0]["to_m"] == 860

    def test_it_is_not_folded_when_it_is_300_ft_or_more(self):
        entries = d.describe(
            [flat(road("A St", 1, 800), road("Alley", 1, 92), road("B St", 1, 400))]
        )
        assert [e["street"] for e in entries] == ["A St", "Alley", "B St"]

    def test_a_short_lts3_stretch_goes_into_a_more_stressful_neighbour_only(self):
        # Into LTS 4, the worse side: it is not understated.
        entries = d.describe(
            [flat(road("A", 2, 800), road("Busy", 3, 30), road("Hwy", 4, 400), road("B", 2, 300))]
        )
        assert [(e["street"], e["tier"]) for e in entries] == [("A", 2), ("Hwy", 4), ("B", 2)]
        # Between two LTS 2 stretches it stays.
        entries = d.describe([flat(road("A", 2, 800), road("Busy", 3, 30), road("B", 2, 400))])
        assert [e["tier"] for e in entries] == [2, 3, 2]

    def test_a_short_stretch_prefers_the_neighbour_on_its_own_street(self):
        entries = d.describe(
            [flat(road("A St", 1, 900), road("B St", 2, 40, 90, 90), road("B St", 3, 300, 90, 90))]
        )
        # The 40 m LTS 2 stretch is B St's: it joins the B St stretch, not the longer A St.
        assert [e["street"] for e in entries] == ["A St", "B St"]
        assert entries[1]["from_m"] == 900

    def test_a_short_lts3_stretch_is_never_hidden(self):
        entries = d.describe(
            [flat(road("A St", 1, 800), road("Busy Rd", 3, 20), road("B St", 1, 400))]
        )
        assert "Busy Rd" in [e["street"] for e in entries]

    def test_a_short_avoid_stretch_is_never_hidden(self):
        entries = d.describe([flat(road("A St", 1, 800), road("Ramp", 5, 15), road("B", 1, 400))])
        assert any(e["tier"] == 5 for e in entries)

    def test_a_short_lts4_stretch_is_never_hidden(self):
        entries = d.describe([flat(road("A", 2, 800), road("Hwy", 4, 30), road("B", 2, 400))])
        assert any(e["tier"] == 4 for e in entries)

    def test_a_tiny_stretch_at_the_start_goes_to_the_next(self):
        entries = d.describe([flat(road("Drive", 1, 50), road("A St", 1, 700))])
        assert [e["street"] for e in entries] == ["A St"]
        assert entries[0]["from_m"] == 0 and entries[0]["to_m"] == 750

    def test_a_tiny_stretch_at_the_end_goes_to_the_previous(self):
        entries = d.describe([flat(road("A St", 1, 700), road("Drive", 1, 50))])
        assert [e["street"] for e in entries] == ["A St"]

    def test_folding_can_rejoin_the_neighbours(self):
        entries = d.describe(
            [flat(road("A St", 1, 400), road("Alley", 2, 40), road("A St", 1, 400))]
        )
        assert len(entries) == 1 and entries[0]["to_m"] == 840

    def test_folding_another_street_in_does_not_make_the_neighbours_one_street(self):
        # A 190 ft stretch of Water St folds into K St (the only neighbour as
        # stressful); K St is still a street to turn onto, from the earlier Water St.
        legs = [
            flat(
                road("Water St", 2, 600, 0, 0),
                road("Water St", 3, 50, 0, 0),
                road("K St", 4, 500, 90, 90),
            )
        ]
        entries = d.describe(legs)
        assert [e["street"] for e in entries] == ["Water St", "K St"]
        assert entries[1]["turn"]["onto"] == "K St"
        assert entries[1]["text"].split(": ")[1].startswith("Right onto K St,")
        assert entries[1]["from_m"] == 600

    def test_folding_back_into_another_street_does_not_take_its_names_either(self):
        # X's short LTS 3 stretch may only go back into the LTS 4 street before it (the
        # next X stretch is calmer); the X that follows is still a street to turn onto.
        legs = [
            flat(
                road("A", 4, 800, 0, 0),
                road("X", 3, 40, 90, 90),
                road("X", 1, 500, 90, 90),
            )
        ]
        entries = d.describe(legs)
        assert [(e["street"], e["tier"]) for e in entries] == [("A", 4), ("X", 1)]
        assert entries[1]["turn"]["movement"] == "right"

    def test_a_tie_between_neighbours_goes_to_the_earlier(self):
        entries = d.describe([flat(road("A", 1, 500), road("Mid", 1, 40), road("B", 1, 500))])
        assert [e["street"] for e in entries] == ["A", "B"]
        assert entries[0]["to_m"] == 540

    def test_a_folded_stretch_of_the_same_street_carries_the_heading_it_was_entered_on(self):
        # B's short LTS 1 start (heading 90) folds into B's longer LTS 2 stretch (heading
        # 180): A -> B is entered on 90, a right turn, not on 180 (which would read as a left).
        legs = [
            flat(
                road("A", 1, 800, 0, 0),
                road("B", 1, 40, 90, 90),
                road("B", 2, 900, 180, 180),
            )
        ]
        entries = d.describe(legs)
        assert [e["street"] for e in entries] == ["A", "B"]
        assert entries[1]["turn"]["movement"] == "right"

    def test_a_third_street_folded_in_leaves_the_turn_to_be_read_across_it(self):
        legs = [
            flat(road("A", 1, 800, 0, 0), road("Tiny", 1, 40, 90, 90), road("B", 1, 900, 90, 90))
        ]
        entries = d.describe(legs)
        assert [e["street"] for e in entries] == ["A", "B"]
        assert entries[1]["turn"]["movement"] == "right"

    def test_a_lone_short_stretch_is_kept(self):
        assert len(d.describe([road("A St", 1, 40)])) == 1

    def test_folding_does_not_cross_a_via_point(self):
        entries = d.describe([road("A St", 1, 700), road("Alley", 1, 40)])
        assert [e["kind"] for e in entries] == ["stretch", "via", "stretch"]

    def test_the_turn_after_a_folded_stretch_is_read_from_the_stretches_that_remain(self):
        entries = d.describe(
            [
                flat(
                    road("A St", 1, 800, 0, 0),
                    road("Tiny", 1, 40, 90, 90),
                    road("B St", 1, 800, 90, 90),
                )
            ]
        )
        # Tiny folds into A St (longer); B St is entered from A St's end heading 90.
        assert entries[1]["turn"]["movement"] in ("straight", "right")


class TestTurns:
    def test_left_right_and_straight(self):
        legs = [
            flat(
                road("A", 1, 500, 0, 0),
                road("B", 1, 500, 270, 270),
                road("C", 1, 500, 0, 0),
                road("D", 1, 500, 5, 5),
            )
        ]
        entries = d.describe(legs)
        assert [e["turn"]["movement"] for e in entries[1:]] == ["left", "right", "straight"]
        assert entries[1]["text"].split(": ")[1].startswith("Left onto B,")
        assert entries[2]["text"].split(": ")[1].startswith("Right onto C,")
        assert entries[3]["text"].split(": ")[1].startswith("Continue onto D,")

    def test_a_signal_is_said_where_the_model_read_one(self):
        legs = [flat(road("A", 1, 500, 0, 0), road("B", 1, 500, 270, 270))]
        entries = d.describe(
            legs, [event(500, "left", Control.SIGNAL, severity=None, flagged=False)]
        )
        assert entries[1]["text"] == (
            "0.3 to 0.6 mi (0.5 to 1.0 km): Left onto B at a signal, low stress (LTS 1)."
        )

    def test_nothing_is_said_of_a_junction_the_model_did_not_read(self):
        legs = [flat(road("A", 1, 500, 0, 0), road("B", 1, 500, 270, 270))]
        assert "signal" not in d.describe(legs)[1]["text"]

    def test_a_flagged_turn_carries_its_severity_words(self):
        legs = [flat(road("A", 3, 500, 0, 0), road("B", 3, 500, 270, 270))]
        text = d.describe(legs, [event(500, "left", Control.SIGNAL, "orange")])[1]["text"]
        assert text == (
            "0.3 to 0.6 mi (0.5 to 1.0 km): Left onto B at a signal "
            "(Higher stress junction), busy road (LTS 3)."
        )
        text = d.describe(legs, [event(500, "left", Control.NONE, "red")])[1]["text"]
        assert "no signal mapped (Very high stress junction)" in text

    @pytest.mark.parametrize(
        ("control", "words"),
        [
            (Control.STOP, " at a stop sign"),
            (Control.ALL_STOP, " at an all-way stop"),
            (Control.CROSS_STOP, " where cross traffic stops"),
        ],
    )
    def test_controls(self, control, words):
        legs = [flat(road("A", 3, 500, 0, 0), road("B", 3, 500, 270, 270))]
        text = d.describe(legs, [event(500, "left", control, "orange")])[1]["text"]
        assert f"Left onto B{words} (Higher" in text

    def test_an_event_near_the_turn_is_its_junction(self):
        legs = [flat(road("A", 3, 500, 0, 0), road("B", 3, 500, 270, 270))]
        entries = d.describe(legs, [event(520, "left", Control.SIGNAL, "orange")])
        assert [e["kind"] for e in entries] == ["stretch", "stretch"]
        assert "at a signal (Higher stress junction)" in entries[1]["text"]
        assert entries[1]["severity"] == "orange"
        assert (
            entries[1]["turn"]["control"] == "signal" and entries[1]["turn"]["severity"] == "orange"
        )

    def test_an_unread_flagless_junction_with_nothing_mapped_says_nothing(self):
        legs = [flat(road("A", 1, 500, 0, 0), road("B", 1, 500, 270, 270))]
        quiet = event(500, "left", Control.NONE, severity=None, flagged=False)
        entries = d.describe(legs, [quiet])
        assert entries[1]["text"].endswith("Left onto B, low stress (LTS 1).")
        assert entries[1]["severity"] is None

    def test_a_flagged_turns_event_is_not_listed_again(self):
        legs = [flat(road("A", 3, 500, 0, 0), road("B", 3, 500, 270, 270))]
        entries = d.describe(legs, [event(500, "left", Control.SIGNAL, "red")])
        assert [e["kind"] for e in entries] == ["stretch", "stretch"]

    def test_an_event_far_from_the_turn_is_not_its_junction(self):
        legs = [flat(road("A", 3, 500, 0, 0), road("B", 3, 500, 270, 270))]
        entries = d.describe(legs, [event(560, "left", Control.SIGNAL, "red")])
        assert "signal" not in entries[1]["text"]
        # ... and a flagged one is listed as a junction of its own.
        assert [e["kind"] for e in entries] == ["stretch", "stretch", "junction"]

    def test_the_turn_is_read_from_the_edge_ends_not_its_start(self):
        # A curving edge arrives heading 0 having begun at 270, and leaves on 90: a right.
        before = [d.Atom(500, "1", "none", ("A",), "road", 270.0, 0.0)]
        after = [d.Atom(500, "1", "none", ("B",), "road", 90.0, 90.0)]
        assert d.describe([before + after])[1]["turn"]["movement"] == "right"

    def test_missing_headings_still_name_the_street(self):
        a = [d.Atom(500, "1", "none", ("A",)), d.Atom(500, "1", "none", ("B",))]
        entries = d.describe([a])
        assert entries[1]["text"].endswith("Continue onto B, low stress (LTS 1).")

    def test_missing_headings_take_the_events_movement(self):
        a = [d.Atom(500, "3", "none", ("A",)), d.Atom(500, "3", "none", ("B",))]
        entries = d.describe([a], [event(500, "right", Control.SIGNAL, "orange")])
        assert "Right onto B at a signal" in entries[1]["text"]


class TestBearsAndJogs:
    """The owner, 2026-10-16, riding east on Q Street NW in Shaw: "complex turns which
    aren't announced". A change of street 20 to 60 degrees off straight is a bear; a
    jog (a short named street entered and left by turns) is never folded away, but a
    divided road, an offset crossing, a sidewalk cut, a slip lane and a circle are."""

    @staticmethod
    def q_onto(heading, metres=1300):
        return d.describe(
            [
                flat(
                    road("Q Street Northwest", 2, 900, 90, 90),
                    road("Rhode Island Avenue Northwest", 2, metres, heading, heading),
                )
            ]
        )

    def test_a_lenfant_diagonal_off_q_street_is_a_bear(self):
        # East on Q St, then 22 or 45 degrees right onto a diagonal: a bear.
        for heading in (112, 135):
            entries = self.q_onto(heading)
            assert entries[1]["turn"]["movement"] == "bear_right", heading
            assert (
                entries[1]["text"]
                .split(": ")[1]
                .startswith("Bear right onto Rhode Island Avenue Northwest,")
            )

    def test_past_the_bear_band_is_a_turn_and_under_it_straight_on(self):
        assert self.q_onto(155)[1]["turn"]["movement"] == "right"
        assert self.q_onto(105)[1]["turn"]["movement"] == "straight"

    def test_a_fork_left_is_a_bear(self):
        legs = [flat(road("Main St", 1, 600, 0, 0), road("Fork Rd", 1, 600, 328, 328))]
        entries = d.describe(legs)
        assert entries[1]["turn"]["movement"] == "bear_left"
        assert "Bear left onto Fork Rd," in entries[1]["text"]

    def test_a_curving_road_that_keeps_its_name_is_no_turn(self):
        legs = [
            flat(
                road("Beach Dr", 1, 400, 0, 0),
                road("Beach Dr", 1, 400, 32, 32),
                road("Beach Dr", 1, 400, 70, 70),
            )
        ]
        entries = d.describe(legs)
        assert len(entries) == 1 and entries[0]["turn"] is None

    def test_a_jog_under_300_ft_is_kept_with_both_its_turns(self):
        # East on Q St, right onto 6th St (100 ft south), then bear left onto a
        # south-east diagonal: two turns, not one folded across them.
        legs = [
            flat(
                road("Q Street Northwest", 2, 900, 90, 90),
                road("6th Street Northwest", 2, 30, 180, 180),
                road("Rhode Island Avenue Northwest", 2, 1300, 145, 145),
            )
        ]
        entries = d.describe(legs)
        assert [e["street"] for e in entries] == [
            "Q Street Northwest",
            "6th Street Northwest",
            "Rhode Island Avenue Northwest",
        ]
        assert [e["turn"]["movement"] for e in entries[1:]] == ["right", "bear_left"]
        assert entries[1]["text"].split(": ")[1].startswith("Right onto 6th Street Northwest,")

    @staticmethod
    def across(middle):
        """Q St, a short middle, Q St again: what is said of it."""
        entries = d.describe(
            [
                flat(
                    road("Q Street Northwest", 2, 400, 90, 90),
                    middle,
                    road("Q Street Northwest", 2, 400, 90, 90),
                )
            ]
        )
        return [(e["street"], (e["turn"] or {}).get("movement")) for e in entries]

    def test_a_divided_road_crossed_is_no_jog(self):
        # 8 m of the avenue's far carriageway between the two halves of Q St.
        middle = road("Rhode Island Avenue Northwest", 2, 8, 180, 180)
        assert self.across(middle) == [("Q Street Northwest", None)]

    def test_a_median_piece_of_a_cross_street_is_no_jog(self):
        middle = road("New Jersey Avenue Northwest", 2, 3, 125, 125)
        assert self.across(middle) == [("Q Street Northwest", None)]

    def test_a_sidewalk_cut_through_is_no_jog(self):
        middle = road("", 1, 20, 180, 180, facility="path", use="footway")
        assert self.across(middle) == [("Q Street Northwest", None)]

    def test_an_offset_crossing_back_onto_the_same_street_is_no_jog(self):
        # 40 m south on 7th St, then on east on Q St: the turns cancel.
        middle = road("7th Street Northwest", 2, 40, 170, 170)
        assert self.across(middle) == [("Q Street Northwest", None)]

    def test_an_unnamed_slip_lane_is_no_jog(self):
        legs = [
            flat(
                road("Q Street Northwest", 2, 400, 90, 90),
                road("", 2, 40, 130, 150),
                road("14th Street Northwest", 2, 400, 180, 180),
            )
        ]
        entries = d.describe(legs)
        assert [(e["street"], (e["turn"] or {}).get("movement")) for e in entries] == [
            ("Q Street Northwest", None),
            ("14th Street Northwest", "right"),
        ]

    def test_a_circle_is_read_across_as_the_net_turn(self):
        # Mass Ave into Dupont Circle and out on P St: "Left onto P Street", by its
        # name or by the map's roundabout flag.
        for name, roundabout in (("Dupont Circle Northwest", False), ("Dupont Ring", True)):
            circle = [replace(atom, roundabout=roundabout) for atom in road(name, 3, 80, 95, 250)]
            legs = [
                flat(
                    road("Massachusetts Avenue Northwest", 3, 400, 60, 60),
                    circle,
                    road("P Street Northwest", 3, 400, 280, 280),
                )
            ]
            entries = d.describe(legs)
            assert [(e["street"], (e["turn"] or {}).get("movement")) for e in entries] == [
                ("Massachusetts Avenue Northwest", None),
                ("P Street Northwest", "left"),
            ], name

    def test_the_overview_names_a_bear(self):
        legs = [
            flat(
                road("Long St", 1, 900, 0, 0),
                road("B St", 1, 150, 35, 35),
                road("C St", 1, 150, 35, 35),
            )
        ]
        _full, short = d.describe_both(legs)
        assert "then bear right on B St" in short[0]["text"]


class TestJunctions:
    def test_a_crossing_of_a_busy_road_is_an_entry_of_its_own(self):
        legs = [road("Capital Crescent Trail", 1, 2000, facility="path")]
        crossing = event(1000, "straight", Control.SIGNAL, "orange", kind="crossing")
        entries = d.describe(legs, [crossing])
        assert [e["kind"] for e in entries] == ["stretch", "junction"]
        assert entries[1]["text"] == (
            "At 0.6 mi (1.0 km): Cross Wisconsin Avenue (LTS 3) at a signal "
            "(Higher stress junction)."
        )
        assert entries[1]["severity"] == "orange"
        assert entries[1]["from_m"] == entries[1]["to_m"] == 1000

    def test_an_unflagged_event_is_not_listed(self):
        legs = [road("A", 1, 2000)]
        flagged_no = event(1000, "straight", severity=None, flagged=False, kind="crossing")
        assert len(d.describe(legs, [flagged_no])) == 1

    def test_an_unnamed_crossed_road_is_a_busy_road(self):
        legs = [road("A", 1, 2000)]
        crossing = event(
            1000, "straight", Control.NONE, "red", kind="crossing", names=("way 123",), tier=4
        )
        text = d.describe(legs, [crossing])[1]["text"]
        assert text == (
            "At 0.6 mi (1.0 km): Cross a busy road (LTS 4), no signal mapped "
            "(Very high stress junction)."
        )

    def test_other_kinds_have_their_own_verbs(self):
        legs = [road("A", 1, 2000)]
        left = event(1000, "left", Control.NONE, "red", kind="left_across")
        assert "Left turn across Wisconsin Avenue (LTS 3)" in d.describe(legs, [left])[1]["text"]
        slip = event(1000, "straight", Control.NONE, "orange", kind="slip_lane")
        assert "Cross a slip lane off Wisconsin Avenue" in d.describe(legs, [slip])[1]["text"]

    def test_a_junction_sorts_between_the_stretches_by_distance(self):
        legs = [flat(road("A", 1, 1000), road("B", 1, 1000, 270, 270))]
        crossing = event(500, "straight", kind="crossing")
        entries = d.describe(legs, [crossing])
        assert [e["kind"] for e in entries] == ["stretch", "junction", "stretch"]

    def test_names_are_made_readable(self):
        assert d.readable("wisconsin avenue") == "Wisconsin Avenue"
        assert d.readable("14th street nw") == "14th Street NW"
        assert d.readable("Capital Crescent Trail") == "Capital Crescent Trail"

    @pytest.mark.parametrize(
        "mapped",
        [
            "MacArthur Boulevard",
            "I-395",
            "US 29",
            "MD 355;Rockville Pike",
            "Rockville Pike;MD 355",
            "O'Brien Way",
        ],
    )
    def test_a_crossed_road_is_named_as_mapped(self, mapped):
        """Item 230: the junction model's lower-case keys are for matching; the
        words use the name as mapped."""
        names = tuple(mapped.split(";"))
        crossing = replace(
            event(500, "straight", kind="crossing", names=tuple(n.lower() for n in names)),
            road_display=names,
        )
        legs = [flat(road("A", 1, 1000), road("B", 1, 1000, 270, 270))]
        entries = d.describe(legs, [crossing])
        junction = next(e for e in entries if e["kind"] == "junction")
        want = "Rockville Pike" if ";" in mapped else mapped
        assert f"Cross {want} (LTS 3)" in junction["text"]
        assert junction["street"] == want

    def test_an_event_without_mapped_names_falls_back_to_readable_keys(self):
        legs = [flat(road("A", 1, 1000), road("B", 1, 1000, 270, 270))]
        entries = d.describe(legs, [event(500, "straight", kind="crossing")])
        assert (
            "Cross Wisconsin Avenue" in next(e for e in entries if e["kind"] == "junction")["text"]
        )


class TestVias:
    def test_the_leg_boundary_is_an_entry_and_nothing_spans_it(self):
        first = road("Capital Crescent Trail", 1, 1500, facility="path")
        second = road("Capital Crescent Trail", 1, 1500, facility="path")
        entries = d.describe([first, second])
        assert texts(entries) == [
            "0.0 to 0.9 mi (0.0 to 1.5 km): Capital Crescent Trail, traffic-free path.",
            "Stop 1 at 0.9 mi (1.5 km).",
            "0.9 to 1.9 mi (1.5 to 3.0 km): Capital Crescent Trail, traffic-free path.",
        ]
        assert entries[1]["via"] == 1 and entries[1]["kind"] == "via"

    def test_two_vias_are_numbered(self):
        legs = [road("A", 1, 500), road("B", 1, 500), road("C", 1, 500)]
        vias = [e for e in d.describe(legs) if e["kind"] == "via"]
        assert [v["via"] for v in vias] == [1, 2]

    def test_no_turn_is_claimed_at_a_via_point(self):
        legs = [road("A", 1, 500, 0, 0), road("B", 1, 500, 270, 270)]
        entries = d.describe(legs)
        assert entries[2]["turn"] is None and entries[2]["text"].split(": ")[1].startswith("B,")

    def test_an_untraced_leg_is_said_and_not_hidden(self):
        entries = d.describe([road("A", 1, 500), 800.0, road("C", 1, 500)])
        assert [e["kind"] for e in entries] == ["stretch", "via", "stretch", "via", "stretch"]
        assert entries[2]["text"] == (
            "0.3 to 0.8 mi (0.5 to 1.3 km): no street details for this part of the route, "
            "stress not rated."
        )
        assert entries[2]["tier"] is None

    def test_the_junction_search_does_not_reach_across_a_via(self):
        legs = [road("A", 1, 500, 0, 0), road("B", 1, 500, 270, 270)]
        text = d.describe(legs, [event(500, "left", Control.SIGNAL, "red")])
        assert [e["kind"] for e in text] == ["stretch", "via", "stretch", "junction"]


class TestNamesAndKinds:
    def test_unnamed_pieces_longer_than_a_tiny_stretch_are_still_one_stretch(self):
        atoms = [d.Atom(300.0, "1", "path", (), "cycleway", 90.0, 90.0) for _ in range(4)]
        entries = d.describe([atoms])
        assert len(entries) == 1 and entries[0]["to_m"] == 1200

    def test_unnamed_stretches_around_a_folded_one_rejoin(self):
        def unnamed(metres, tier):
            return [d.Atom(metres, tier, "none", (), "road", 90.0, 90.0)]

        entries = d.describe([unnamed(300.0, "1") + unnamed(40.0, "2") + unnamed(300.0, "1")])
        assert len(entries) == 1 and entries[0]["to_m"] == 640

    def test_an_unnamed_trail_is_a_path(self):
        # The owner, 2026-10-15: "path", not "unnamed path".
        entries = d.describe([road(None, 1, 700, facility="path", use="cycleway")])
        assert len(entries) == 1  # its unnamed pieces are one stretch
        assert entries[0]["street"] == "path"
        assert entries[0]["text"].endswith(": Path, traffic-free.")
        assert "unnamed" not in entries[0]["text"]

    def test_an_unnamed_sidewalk_is_a_path_by_its_use(self):
        entries = d.describe([road(None, 2, 700, use="footway")])
        assert entries[0]["street"] == "path"

    def test_an_unnamed_path_is_not_called_a_path_twice(self):
        text = d.describe([road(None, 1, 700, facility="path", use="cycleway")])[0]["text"]
        assert text.endswith("Path, traffic-free.")

    def test_a_turn_onto_an_unnamed_path_is_onto_the_path(self):
        entries = d.describe(
            [
                [
                    d.Atom(400.0, "2", "none", ("A Street",), "road", 0.0, 0.0),
                    d.Atom(600.0, "1", "path", (), "cycleway", 270.0, 270.0),
                ]
            ]
        )
        assert entries[1]["street"] == "path"
        assert ": Left onto the path, traffic-free." in entries[1]["text"]

    def test_a_bike_lane_named_for_its_street_says_its_name_once(self):
        # An unnamed protected lane beside 9th Street NW, named at the rebuild
        # (`routemaker.facility.side_street_names`) and handed in as the piece's name.
        entries = d.describe(
            [
                [
                    d.Atom(400.0, "2", "none", ("R Street Northwest",), "road", 90.0, 90.0),
                    d.Atom(
                        600.0,
                        "1",
                        "protected",
                        ("9th Street Northwest protected bike lane",),
                        "cycleway",
                        0.0,
                        0.0,
                    ),
                ]
            ]
        )
        lane = entries[1]
        assert lane["street"] == "9th Street Northwest protected bike lane"
        assert lane["turn"]["onto"] == "9th Street Northwest protected bike lane"
        assert (
            ": Left onto 9th Street Northwest protected bike lane, low stress (LTS 1)."
            in lane["text"]
        )
        assert lane["text"].count("protected bike lane") == 1

    def test_an_unnamed_stretch_that_is_a_path_for_part_of_it_is_a_path(self):
        atoms = [
            d.Atom(300.0, "2", "none", (), "road", 90.0, 90.0),
            d.Atom(300.0, "2", "none", (), "footway", 90.0, 90.0),
        ]
        assert d.describe([atoms])[0]["street"] == "path"

    def test_an_unnamed_road_is_an_unnamed_road(self):
        entries = d.describe([road(None, 2, 700)])
        assert entries[0]["street"] == "unnamed road"

    def test_unrated_stress_is_said(self):
        entries = d.describe([road("A St", "unknown", 700, facility="unknown")])
        assert entries[0]["text"].endswith("A St, stress not rated.")
        assert entries[0]["tier"] is None and entries[0]["facility"] is None

    @pytest.mark.parametrize(
        ("tier", "words"),
        [
            (1, "low stress (LTS 1)"),
            (2, "fairly low stress (LTS 2)"),
            (3, "busy road (LTS 3)"),
            (4, "heavy traffic (LTS 4)"),
            (5, "Avoid (legal, but best avoided)"),
        ],
    )
    def test_tier_words(self, tier, words):
        assert d.tier_words(str(tier), "none") == words

    def test_a_path_is_traffic_free_whatever_its_tier(self):
        assert d.tier_words("3", "path") == "traffic-free path"

    def test_a_protected_lane_is_named(self):
        assert d.tier_words("1", "protected") == "low stress (LTS 1), protected bike lane"

    def test_a_short_stretch_says_its_length(self):
        entries = d.describe([flat(road("A", 1, 800), road("Ramp", 3, 40, 0, 0))])
        assert entries[1]["text"].startswith("0.5 mi (0.8 km), for 130 ft (40 m): ")


class TestTotals:
    def test_the_stretches_add_up_to_the_route(self):
        entries = d.describe([bethesda()])
        stretches = [e for e in entries if e["kind"] == "stretch"]
        assert stretches[0]["from_m"] == 0
        for a, b in zip(stretches, stretches[1:], strict=False):
            assert a["to_m"] == b["from_m"]
        assert stretches[-1]["to_m"] == round(1931 + 480 + 800 + 600)

    def test_distances_are_scaled_to_the_stated_length(self):
        entries = d.describe([bethesda()], total_m=3900.0)
        assert entries[-1]["to_m"] == 3900
        assert sum(e["to_m"] - e["from_m"] for e in entries) == 3900

    def test_the_sum_survives_via_points_and_folding(self):
        legs = [
            flat(road("A", 1, 700), road("x", 1, 30), road("B", 3, 900, 90, 90)),
            flat(road("B", 3, 400), road("C", 2, 650, 0, 0)),
        ]
        entries = d.describe(legs, total_m=2700.4)
        stretches = [e for e in entries if e["kind"] == "stretch"]
        assert stretches[-1]["to_m"] == round(2700.4)
        assert sum(e["to_m"] - e["from_m"] for e in stretches) in range(2699, 2703)

    def test_miles_are_consistent_with_the_text(self):
        entry = d.describe([road("A", 1, 1609.344 * 2)])[0]
        assert entry["to_mi"] == 2.0 and "0.0 to 2.0 mi (0.0 to 3.2 km)" in entry["text"]

    def test_empty_and_zero_length(self):
        assert d.describe([]) == []
        assert d.describe([[]]) == []
        assert d.describe([[d.Atom(0.0, "1", "none")]]) == []

    def test_the_plain_text_is_one_line_per_entry(self):
        entries = d.describe([bethesda()])
        assert d.plain_text(entries).count("\n") == len(entries) - 1


def both(*legs, events=None, total=None):
    return d.describe_both(list(legs), events, total)


class TestOverview:
    """OWNER-DECISIONS 226: the overview merges stretches under 0.25 mi and never
    hides a busy stretch or a flagged junction, nor spans a stop."""

    def test_the_limit_is_a_quarter_of_a_mile(self):
        assert d.OVERVIEW_M == pytest.approx(402.336)

    def test_long_stretches_are_the_same_in_both(self):
        full, short = both(bethesda())
        assert texts(short) == texts(full)

    def test_describe_is_the_full_list(self):
        assert d.describe([bethesda()]) == both(bethesda())[0]

    def test_a_short_quiet_stretch_is_merged_into_its_neighbour(self):
        a, b, c = (
            road("A St", 1, 1000, 0, 0),
            road("B St", 1, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        full, short = both(flat(a, b, c))
        assert len(full) == 3
        assert texts(short) == [
            "0.0 to 0.8 mi (0.0 to 1.4 km): A St, then right on B St, low stress (LTS 1).",
            "0.8 to 1.5 mi (1.4 to 2.4 km): Left onto C St, low stress (LTS 1).",
        ]
        assert short[0]["street"] == "A St" and short[0]["to_m"] == 1350

    def test_a_calm_stretch_is_not_worded_as_busy_nor_a_busy_one_as_calm(self):
        a, b, c = (
            road("A St", 4, 1000, 0, 0),
            road("B St", 1, 350, 90, 90),
            road("C St", 4, 1000, 0, 0),
        )
        short = both(flat(a, b, c))[1]
        assert [e["tier"] for e in short] == [4, 1, 4]
        a, b, c = (
            road("A St", 1, 1000, 0, 0),
            road("B St", 4, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        assert [e["tier"] for e in both(flat(a, b, c))[1]] == [1, 4, 1]

    def test_a_short_lts4_stretch_is_not_worded_as_lts3(self):
        a, b, c = (
            road("A St", 3, 1000, 0, 0),
            road("B St", 4, 350, 90, 90),
            road("C St", 3, 1000, 0, 0),
        )
        assert [e["tier"] for e in both(flat(a, b, c))[1]] == [3, 4, 3]
        a, b, c = (
            road("A St", 4, 1000, 0, 0),
            road("B St", 5, 350, 90, 90),
            road("C St", 4, 1000, 0, 0),
        )
        assert [e["tier"] for e in both(flat(a, b, c))[1]] == [4, 5, 4]

    def test_the_neighbour_of_the_same_tier_is_preferred(self):
        a, b, c = (
            road("A St", 2, 1000, 0, 0),
            road("B St", 1, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        short = both(flat(a, b, c))[1]
        assert [e["tier"] for e in short] == [2, 1]
        assert short[0]["to_m"] == 1000 and short[1]["from_m"] == 1000

    def test_the_neighbour_on_its_own_street_is_preferred(self):
        a, b, c = (
            road("A St", 2, 1000, 0, 0),
            road("C St", 1, 350, 90, 90),
            road("C St", 2, 1000, 90, 90),
        )
        short = both(flat(a, b, c))[1]
        assert len(short) == 2
        assert short[0]["to_m"] == 1000 and short[1]["street"] == "C St"

    def test_the_street_it_begins_on_is_not_listed_as_another(self):
        a, b = road("A St", 1, 1000, 0, 0), road("A St", 2, 350, 0, 0)
        short = both(flat(a, b))[1]
        assert len(short) == 1
        assert short[0]["text"] == "0.0 to 0.8 mi (0.0 to 1.4 km): A St, fairly low stress (LTS 2)."

    def test_a_street_run_along_twice_is_listed_once(self):
        pieces = [road("Long St", 1, 1000, 0, 0), road("B St", 1, 100, 90, 90)]
        pieces += [
            road("C St", 1, 100, 0, 0),
            road("B St", 1, 100, 90, 90),
            road("Z St", 1, 1000, 0, 0),
        ]
        assert "Long St, then right on B St and left on C St," in both(flat(*pieces))[1][0]["text"]

    def test_three_other_streets_are_all_listed(self):
        pieces = [road("Long St", 1, 1000, 0, 0)]
        for name, heading in (("B St", 90), ("C St", 180), ("D St", 270)):
            pieces.append(road(name, 1, 100, heading, heading))
        pieces.append(road("Z St", 1, 1000, 0, 0))
        assert (
            "Long St, then right on B St, right on C St and right on D St,"
            in both(flat(*pieces))[1][0]["text"]
        )

    def test_a_stretch_exactly_at_the_limit_is_kept(self):
        atoms = [
            d.Atom(1000.0, "1", "none", ("A St",), "road", 0.0, 0.0),
            d.Atom(d.OVERVIEW_M, "1", "none", ("B St",), "road", 90.0, 90.0),
            d.Atom(1000.0, "1", "none", ("C St",), "road", 0.0, 0.0),
        ]
        assert len(both(atoms)[1]) == 3
        atoms[1] = d.Atom(d.OVERVIEW_M - 1, "1", "none", ("B St",), "road", 90.0, 90.0)
        assert len(both(atoms)[1]) == 2

    def test_a_stretch_at_a_quarter_mile_or_more_is_kept(self):
        a, b, c = road("A St", 1, 1000), road("B St", 1, 410, 90, 90), road("C St", 1, 1000, 0, 0)
        assert len(both(flat(a, b, c))[1]) == 3

    def test_a_short_lts3_stretch_between_quiet_ones_is_never_hidden(self):
        a, b, c = (
            road("A St", 1, 1000, 0, 0),
            road("B St", 3, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        short = both(flat(a, b, c))[1]
        assert [e["tier"] for e in short] == [1, 3, 1]

    @pytest.mark.parametrize("tier", [3, 4, 5])
    def test_a_short_busy_stretch_merges_only_into_one_at_least_as_stressful(self, tier):
        a = road("A St", tier, 1000, 0, 0)
        b = road("B St", tier, 350, 90, 90)
        c = road("C St", 1, 1000, 0, 0)
        short = both(flat(a, b, c))[1]
        assert [e["tier"] for e in short] == [tier, 1]
        assert "then right on B St" in short[0]["text"]

    def test_a_short_stretch_is_worded_at_the_worst_tier_it_covers(self):
        a, b, c = (
            road("A St", 1, 1000, 0, 0),
            road("B St", 2, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        short = both(flat(a, b, c))[1]
        assert short[0]["tier"] == 2
        assert "fairly low stress (LTS 2)" in short[0]["text"]

    def test_a_trail_with_a_short_road_bit_is_not_called_a_path(self):
        a = road("Trail", 1, 1000, 0, 0, facility="path", use="cycleway")
        b = road("Side St", 1, 350, 90, 90)
        short = both(flat(a, b))[1]
        assert len(short) == 1
        assert "traffic-free" not in short[0]["text"] and short[0]["facility"] is None

    def test_a_stretch_that_begins_at_a_flagged_junction_is_never_merged_away(self):
        a, b, c = (
            road("A St", 1, 1000, 0, 0),
            road("B St", 1, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        events = [event(1000, "right", Control.NONE, "red", flagged=True)]
        short = both(flat(a, b, c), events=events)[1]
        assert len(short) == 3
        assert "Very high stress junction" in short[1]["text"] and short[1]["severity"] == "red"

    def test_nothing_is_merged_in_front_of_a_flagged_turn(self):
        a, b, c = (
            road("A St", 1, 1000, 0, 0),
            road("B St", 1, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        events = [event(1350, "left", Control.SIGNAL, "orange")]
        short = both(flat(a, b, c), events=events)[1]
        assert "Higher stress junction" in short[-1]["text"]
        assert short[-1]["text"].split(": ")[1].startswith("Left onto C St")

    def test_a_flagged_junction_inside_a_merged_stretch_stays_an_entry(self):
        a, b, c = (
            road("A St", 1, 1000, 0, 0),
            road("B St", 1, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        events = [
            event(1100, "left", Control.NONE, "red", kind="crossing", names=("mass ave",), tier=4)
        ]
        full, short = both(flat(a, b, c), events=events)
        assert [e["kind"] for e in short] == ["stretch", "junction", "stretch"]
        assert [e["text"] for e in full if e["kind"] == "junction"] == [
            e["text"] for e in short if e["kind"] == "junction"
        ]

    def test_nothing_spans_a_stop(self):
        first = flat(road("A St", 1, 1000, 0, 0), road("B St", 1, 350, 90, 90))
        second = flat(road("B St", 1, 350, 90, 90), road("C St", 1, 1000, 0, 0))
        full, short = both(first, second)
        assert [e["kind"] for e in short] == ["stretch", "via", "stretch"]
        via = short[1]
        assert short[0]["to_m"] <= via["from_m"] <= short[2]["from_m"]
        assert [e["text"] for e in full if e["kind"] == "via"] == [via["text"]]

    def test_a_short_leg_of_its_own_is_kept_as_it_cannot_merge_across_a_stop(self):
        short = both(road("A St", 1, 1000), road("B St", 1, 300), road("C St", 1, 1000))[1]
        assert [e["kind"] for e in short] == ["stretch", "via", "stretch", "via", "stretch"]

    def test_an_untraced_leg_is_never_merged(self):
        short = both(road("A", 1, 500), 200.0, road("C", 1, 500))[1]
        assert any("no street details" in e["text"] for e in short)

    def test_rated_and_unrated_stretches_are_not_merged(self):
        rated = road("A St", 1, 1000, 0, 0)
        unrated = road("B St", "unknown", 350, 90, 90)
        short = both(flat(rated, unrated))[1]
        assert len(short) == 2 and short[1]["tier"] is None

    def test_many_streets_are_listed_three_and_a_count(self):
        pieces = [road("Long St", 1, 1000, 0, 0)]
        for i, name in enumerate(["B St", "C St", "D St", "E St", "F St"]):
            heading = 90 * (i + 1) % 360
            pieces.append(road(name, 1, 100, heading, heading))
        pieces.append(road("Z St", 1, 1000, 0, 0))
        short = both(flat(*pieces))[1]
        assert short[0]["text"].startswith(
            "0.0 to 0.9 mi (0.0 to 1.5 km): Long St, then right on B St, right on C St,"
            " right on D St and 2 more turns, low stress"
        )

    def test_two_other_streets_are_joined_with_and(self):
        pieces = [
            road("Long St", 1, 1000, 0, 0),
            road("B St", 1, 100, 90, 90),
            road("C St", 1, 100, 0, 0),
        ]
        pieces.append(road("Z St", 1, 1000, 90, 90))
        assert "Long St, then right on B St and left on C St," in both(flat(*pieces))[1][0]["text"]

    def test_the_turns_in_a_merged_entry_are_named_briefly(self):
        """Item 229: "Right onto Ramsey Avenue at a signal, then left on Ripley
        Street and right on Colonial Lane"; a street straight on has no turn word."""
        pieces = [
            road("Start St", 2, 1000, 0, 0),
            road("Ramsey Avenue", 2, 1000, 90, 90),
            road("Ripley Street", 2, 100, 0, 0),
            road("Colonial Lane", 2, 100, 90, 90),
            road("Zed Road", 2, 1000, 90, 90),
        ]
        entries = both(flat(*pieces), events=[event(1000, "right", flagged=False)])[1]
        text = next(e["text"] for e in entries if "Ramsey" in e["text"])
        assert (
            "Right onto Ramsey Avenue at a signal, then left on Ripley Street"
            " and right on Colonial Lane, fairly low stress (LTS 2)." in text
        )

    def test_a_street_straight_on_is_named_without_a_turn_word(self):
        pieces = [
            road("A St", 2, 1000, 0, 0),
            road("Ripley Street", 2, 100, 0, 0),
            road("Z St", 2, 1000, 0, 0),
        ]
        text = both(flat(*pieces))[1][0]["text"]
        assert ", then Ripley Street," in text
        assert "on Ripley" not in text and "onto Ripley" not in text

    @pytest.mark.parametrize(
        ("others", "tail"), [(3, ""), (4, " and 1 more turn"), (6, " and 3 more turns")]
    )
    def test_at_most_three_turns_are_named_then_a_count(self, others, tail):
        names = ["B St", "C St", "D St", "E St", "F St", "G St"][:others]
        pieces = [road("Long St", 1, 1000, 0, 0)]
        heading = 0
        for name in names:
            pieces.append(road(name, 1, 100, (heading + 90) % 360, (heading + 90) % 360))
            heading = (heading + 90) % 360
        pieces.append(road("Z St", 1, 1000, 0, 0))
        text = both(flat(*pieces))[1][0]["text"]
        named = [n for n in names if n in text]
        assert len(named) == min(others, d.MAX_NAMED_TURNS)
        assert (f"{tail.strip()}," in text) if tail else ("more turn" not in text)
        assert ", then" in text

    def test_the_overview_covers_the_route_end_to_end(self):
        a, b, c = (
            road("A St", 1, 1000, 0, 0),
            road("B St", 1, 350, 90, 90),
            road("C St", 1, 1000, 0, 0),
        )
        short = both(flat(a, b, c), total=2500.0)[1]
        stretches = [e for e in short if e["kind"] == "stretch"]
        assert stretches[0]["from_m"] == 0 and stretches[-1]["to_m"] == 2500
        assert all(x["to_m"] == y["from_m"] for x, y in zip(stretches, stretches[1:], strict=False))

    def test_random_routes_keep_the_promises(self):
        import random

        rng = random.Random(226)
        for _ in range(300):
            legs = []
            for _leg in range(rng.randint(1, 3)):
                parts = []
                for _k in range(rng.randint(1, 12)):
                    heading = rng.choice([0, 90, 180, 270])
                    parts.append(
                        road(
                            f"S{rng.randint(1, 5)}",
                            rng.choice([1, 1, 2, 3, 4, 5]),
                            rng.choice([40, 150, 250, 380, 500, 900, 1600]),
                            heading,
                            heading,
                            facility=rng.choice(["none", "none", "path", "lane"]),
                        )
                    )
                legs.append(flat(*parts))
            events = [
                event(
                    rng.uniform(0, 5000),
                    rng.choice(["left", "right", "straight"]),
                    rng.choice(list(Control)),
                    rng.choice(["orange", "red"]),
                    kind=rng.choice(["left_onto", "crossing"]),
                    flagged=rng.random() < 0.7,
                )
                for _ in range(rng.randint(0, 6))
            ]
            full, short = both(*legs, events=events)
            assert len(short) <= len(full)
            # Stops and separate junction entries are the full list's, unchanged.
            assert [e for e in short if e["kind"] != "stretch"] == [
                e for e in full if e["kind"] != "stretch"
            ]
            stretches = [e for e in short if e["kind"] == "stretch"]
            assert all(
                x["to_m"] == y["from_m"] for x, y in zip(stretches, stretches[1:], strict=False)
            )
            # Nothing spans a stop.
            vias = [e["from_m"] for e in short if e["kind"] == "via"]
            for e in stretches:
                assert not any(e["from_m"] < v < e["to_m"] for v in vias)
            # No busy metre is understated.
            for e in full:
                if e["kind"] == "stretch" and (e["tier"] or 0) >= 3:
                    holder = next(
                        s
                        for s in stretches
                        if s["from_m"] <= e["from_m"] < max(s["to_m"], s["from_m"] + 1)
                    )
                    assert (holder["tier"] or 0) >= e["tier"]

            # Every flagged junction's words survive.
            def flagged_words(entries):
                return sum(e["text"].count("stress junction") for e in entries)

            assert flagged_words(short) == flagged_words(full)


def surfaced(name, tier, metres, unpaved, facility="none", use="road"):
    """`road`, with each piece's surface set."""
    return [
        replace(atom, unpaved=unpaved)
        for atom in road(name, tier, metres, facility=facility, use=use)
    ]


class TestSurface:
    """OWNER-DECISIONS 280 (review SF5): the map's dotted mark is not all a
    screen-reader rider has; a stretch says it is unpaved."""

    def test_an_unpaved_stretch_says_so_in_its_text_and_its_field(self):
        entry = d.describe([surfaced("Gravel Trail", 1, 900, True, facility="path", use="path")])[0]
        assert entry["text"].endswith(", traffic-free path, unpaved.")
        assert entry["surface"] == "unpaved"

    def test_a_road_says_its_tier_then_its_surface(self):
        entry = d.describe([surfaced("Old Mill Road", 2, 900, True)])[0]
        assert entry["text"].endswith("Old Mill Road, fairly low stress (LTS 2), unpaved.")

    def test_a_paved_or_unknown_surface_says_nothing(self):
        for unpaved in (False, None):
            entry = d.describe([surfaced("A St", 1, 900, unpaved)])[0]
            assert "unpaved" not in entry["text"] and entry["surface"] is None

    def test_partly_unpaved_where_less_than_half_but_at_least_a_tenth_of_a_mile(self):
        leg = flat(
            surfaced("A Trail", 1, 1000, False, "path", "path"),
            surfaced("A Trail", 1, 200, True, "path", "path"),
        )
        entry = d.describe([leg])[0]
        assert entry["surface"] == "partly unpaved" and entry["text"].endswith(", partly unpaved.")
        # Under a tenth of a mile unpaved in a longer stretch is not said.
        leg = flat(
            surfaced("A Trail", 1, 1000, False, "path", "path"),
            surfaced("A Trail", 1, 120, True, "path", "path"),
        )
        assert d.describe([leg])[0]["surface"] is None
        # Half or more is unpaved, the boundary included.
        leg = flat(
            surfaced("A Trail", 1, 600, False, "path", "path"),
            surfaced("A Trail", 1, 600, True, "path", "path"),
        )
        assert d.describe([leg])[0]["surface"] == "unpaved"

    def test_a_change_of_surface_alone_does_not_start_a_stretch(self):
        leg = flat(
            surfaced("A Trail", 1, 600, False, "path", "path"),
            surfaced("A Trail", 1, 600, True, "path", "path"),
        )
        assert len(d.describe([leg])) == 1

    def test_a_folded_stretch_brings_its_unpaved_metres(self):
        # 60 m of unpaved side street folds into a 300 m unpaved trail: all of it is unpaved.
        leg = flat(
            surfaced("A Trail", 1, 300, True, "path", "path"),
            surfaced("x", 1, 60, True),
            surfaced("B St", 1, 900, False),
        )
        entries = d.describe([leg])
        assert entries[0]["surface"] == "unpaved" and entries[1]["surface"] is None

    def test_the_overview_merges_say_the_surface_of_the_whole(self):
        leg = flat(
            surfaced("A Trail", 1, 300, True, "path", "path"),
            surfaced("B Trail", 1, 300, True, "path", "path"),
            surfaced("C St", 1, 900, False),
        )
        full, short = both(leg)
        assert [e["surface"] for e in full] == ["unpaved", "unpaved", None]
        assert short[0]["surface"] == "unpaved" and short[0]["text"].endswith(", unpaved.")

    def test_an_untraced_leg_has_no_surface(self):
        assert d.describe([500.0])[0]["surface"] is None


class TestHighStressLanes:
    """OWNER-DECISIONS 275 (review SF3): a painted lane on LTS 4 or Avoid is worded
    both ways, so the client's switch never edits the wording."""

    def test_the_tiers_are_lts4_and_avoid(self):
        assert d.HIGH_STRESS_LANE_TIERS == frozenset({"4", "5"})

    @pytest.mark.parametrize("tier", [4, 5])
    def test_a_lane_on_a_high_stress_tier_has_its_text_without_the_lane(self, tier):
        entry = d.describe([road("Kenilworth Ave", tier, 900, facility="lane")])[0]
        assert entry["text"].endswith(", painted bike lane.")
        assert entry["text_lanes_hidden"] == entry["text"].replace(", painted bike lane", "")
        assert "bike lane" not in entry["text_lanes_hidden"]

    @pytest.mark.parametrize(
        ("tier", "facility"), [(3, "lane"), (1, "lane"), (4, "protected"), (4, "none"), (4, "path")]
    )
    def test_any_other_stretch_has_none(self, tier, facility):
        entry = d.describe([road("A St", tier, 900, facility=facility)])[0]
        assert entry["text_lanes_hidden"] is None

    def test_the_surface_stays_in_the_hidden_text(self):
        entry = d.describe([surfaced("A Rd", 4, 900, True, facility="lane")])[0]
        assert entry["text_lanes_hidden"].endswith("heavy traffic (LTS 4), unpaved.")

    def test_an_overview_merge_of_lts3_and_lts4_lanes_keeps_its_lane(self):
        # The facility bar counts the LTS 3 part as a lane, so the words stay.
        leg = flat(
            road("A Ave", 3, 200, facility="lane"),
            road("A Ave", 4, 150, facility="lane"),
            road("B St", 3, 900),
        )
        _full, short = both(leg)
        merged = short[0]
        assert (
            merged["tier"] == 4
            and merged["facility"] == "lane"
            and merged["text_lanes_hidden"] is None
        )

    def test_an_overview_merge_all_on_high_stress_tiers_hides_its_lane(self):
        leg = flat(
            road("A Ave", 4, 200, facility="lane"),
            road("A Ave", 5, 150, facility="lane"),
            road("B St", 4, 900),
        )
        _full, short = both(leg)
        merged = short[0]
        assert merged["facility"] == "lane" and merged["tier"] == 5
        assert merged["text_lanes_hidden"] == merged["text"].replace(", painted bike lane", "")

    def test_junctions_and_stops_have_none(self):
        entries = d.describe(
            [road("A", 4, 900, facility="lane"), road("B", 4, 900, facility="lane")]
        )
        via = [e for e in entries if e["kind"] == "via"]
        assert via and all(e["text_lanes_hidden"] is None and e["surface"] is None for e in via)


class TestFrontEndAgrees:
    """Review SF3: the planner takes ", painted bike lane" out of an older API's
    text itself (frontend/src/lib/routeDescription.ts PAINTED_LANE_WORDS), on the
    tiers from frontend/src/stressStyle.js HIGH_STRESS_LANE_MIN_TIER. Both are
    held to the words and tiers this module uses."""

    @staticmethod
    def source(*parts: str) -> str:
        from pathlib import Path

        return Path(__file__).resolve().parents[1].joinpath("frontend", "src", *parts).read_text()

    def test_the_stripped_phrase_is_what_tier_words_adds_for_a_painted_lane(self):
        import re

        match = re.search(
            r'export const PAINTED_LANE_WORDS = "([^"]*)";',
            self.source("lib", "routeDescription.ts"),
        )
        assert match, "routeDescription.ts declares PAINTED_LANE_WORDS"
        words = match.group(1)
        assert words == f", {d.FACILITY_WORDS['lane']}"
        for tier in d.HIGH_STRESS_LANE_TIERS:
            # What the API actually says on a lane stretch, and what is left once the phrase is out.
            assert d.tier_words(tier, "lane") == d.tier_words(tier, "none") + words
            entry = d.describe([road("Kenilworth Ave", int(tier), 900, facility="lane")])[0]
            assert entry["text"].replace(words, "") == entry["text_lanes_hidden"]

    def test_the_unnamed_street_words_are_the_federal_checks(self):
        """FOLLOWUP-FEDERAL-LAYER, item 239 (d): frontend/src/lib/federalStops.ts reads these
        street words as unnamed when it looks for a parkway by the NPS layer, so they must be
        the words this module gives a stretch with no name."""
        import re

        source = self.source("lib", "federalStops.ts")
        for name, value in (
            ("UNNAMED_ROAD", d.UNNAMED_ROAD),
            ("UNTRACED_STREET", d.UNTRACED_STREET),
            ("UNNAMED_PATH", d.UNNAMED_PATH),
        ):
            match = re.search(rf'export const {name} = "([^"]*)";', source)
            assert match, f"federalStops.ts declares {name}"
            assert match.group(1) == value
        # What describe actually puts in `street`.
        assert d.describe([road("", 2, 500)])[0]["street"] == d.UNNAMED_ROAD
        assert d.describe([road("", 1, 500, use="cycleway")])[0]["street"] == d.UNNAMED_PATH
        untraced = d.describe([road("A", 1, 500), 800.0, road("C", 1, 500)])[2]
        assert untraced["street"] == d.UNTRACED_STREET

    def test_the_tiers_are_the_front_ends(self):
        import re

        match = re.search(
            r"export const HIGH_STRESS_LANE_MIN_TIER = (\d+);", self.source("stressStyle.js")
        )
        assert match, "stressStyle.js declares HIGH_STRESS_LANE_MIN_TIER"
        at_least = int(match.group(1))
        assert d.HIGH_STRESS_LANE_TIERS == frozenset(str(t) for t in range(1, 6) if t >= at_least)


class TestSurfaceSums:
    """The unpaved metres travel with every join (mutation run, salience r1)."""

    def test_between_a_third_and_a_half_is_partly(self):
        leg = flat(
            surfaced("A Trail", 1, 1000, False, "path", "path"),
            surfaced("A Trail", 1, 600, True, "path", "path"),
        )
        assert d.describe([leg])[0]["surface"] == "partly unpaved"

    def test_a_stretch_joined_across_a_folded_one_keeps_both_parts_unpaved_metres(self):
        # A Trail, a 30 m bit of another way folded in, then A Trail again: one stretch,
        # 250 m of its 480 m unpaved.
        leg = flat(
            surfaced("A Trail", 1, 200, False, "path", "path"),
            surfaced("Spur", 1, 30, False, "path", "path"),
            surfaced("A Trail", 1, 250, True, "path", "path"),
        )
        entries = d.describe([leg])
        assert len(entries) == 1 and entries[0]["surface"] == "unpaved"

    def test_a_folded_bit_brings_its_unpaved_metres_into_the_next_stretch(self):
        # 80 m of unpaved side way folds into the longer C Trail after it (150 m, 70 m of
        # it unpaved): 150 of 230 m unpaved, where C Trail alone would be under half.
        leg = flat(
            surfaced("B St", 1, 100, False),
            surfaced("x", 1, 80, True),
            surfaced("C Trail", 1, 80, False),
            surfaced("C Trail", 1, 70, True),
        )
        entries = d.describe([leg])
        assert [e["street"] for e in entries] == ["B St", "C Trail"]
        assert entries[1]["surface"] == "unpaved"


class TestTheMergedGroupsCarryWhatTheirMembersDo:
    """Mutation review X22 and X30: an overview group's hidden-lanes text keeps its
    ", then ..." clause, and its surface is its members' together, not its first's."""

    def test_the_hidden_text_keeps_the_then_clause(self):
        leg = flat(
            road("A Ave", 4, 200, facility="lane"),
            road("B Ave", 4, 150, facility="lane"),
            road("C St", 4, 900, facility="lane"),
        )
        _full, short = both(leg)
        merged = short[0]
        assert ", then" in merged["text"], merged["text"]
        assert merged["text_lanes_hidden"] == merged["text"].replace(", painted bike lane", "")
        assert ", then" in merged["text_lanes_hidden"]

    def test_a_group_whose_first_member_is_paved_says_unpaved(self):
        leg = flat(
            surfaced("A Trail", 1, 100, False, "path", "path"),
            surfaced("B Trail", 1, 300, True, "path", "path"),
            surfaced("C Trail", 1, 900, True, "path", "path"),
        )
        _full, short = both(leg)
        assert short[0]["surface"] == "unpaved", [(e["text"], e["surface"]) for e in short]


def forked(atoms, movement):
    """`atoms` with the first marked as begun at a fork (`describe.fork_movement`)."""
    return [replace(atoms[0], fork=movement), *atoms[1:]]


class TestForks:
    """The owner, 2026-10-18, riding the Paint Branch Trail in College Park: "still
    missing some important turns, especially when it seems straight is the default".
    Where another rideable way at a node is as near straight ahead as the route's, the
    route's way is said, even along one trail or straight on."""

    def test_a_branch_straight_ahead_while_the_route_bends_is_a_fork(self):
        # North on the trail, which turns left at a T; a path runs on north.
        assert d.fork_movement(0, 270, [(2, "cycleway", "both")]) == "left"

    def test_a_y_is_a_bear_to_the_route_s_side_of_the_other_branch(self):
        assert d.fork_movement(0, 20, [(340, "cycleway", "both")]) == "bear_right"
        assert d.fork_movement(0, 340, [(20, "footway", None)]) == "bear_left"
        # A little right of straight on, with a way straighter still: keep right.
        assert d.fork_movement(0, 10, [(2, "path", "both")]) == "bear_right"

    def test_plainly_straight_on_is_no_fork(self):
        # The branch is 30 degrees off, the route's way straight: nothing to choose.
        assert d.fork_movement(0, 0, [(30, "cycleway", "both")]) is None
        # Nor is a spur a little off a trail carried straight on.
        assert d.fork_movement(0, 0, [(15, "footway", "both")]) is None
        assert d.fork_movement(0, 5, [(350, "footway", "both")]) is None
        # A cross street at a right angle is not a way on.
        assert d.fork_movement(0, 0, [(90, "road", "both"), (270, "road", "both")]) is None

    def test_ways_that_are_no_choice_are_left_out(self):
        for use, cyclability in (
            ("driveway", "both"),
            ("steps", None),
            ("footway", "none"),
            ("road", "backward"),
            ("pedestrian_crossing", "both"),
        ):
            assert d.fork_movement(0, 270, [(0, use, cyclability)]) is None, use
        assert d.fork_movement(None, 270, [(0, "path", "both")]) is None

    def test_a_fork_along_one_trail_is_a_turn_to_stay_on_it(self):
        legs = [
            flat(
                road("Paint Branch Trail", 1, 600, 0, 0, facility="path", use="cycleway"),
                forked(
                    road("Paint Branch Trail", 1, 600, 270, 270, facility="path", use="cycleway"),
                    "left",
                ),
            )
        ]
        entries = d.describe(legs)
        assert len(entries) == 2
        assert entries[1]["turn"]["movement"] == "left"
        assert entries[1]["turn"]["stay"] is True
        assert "Left to stay on Paint Branch Trail," in entries[1]["text"]

    def test_a_new_name_straight_on_at_a_fork_is_a_bear(self):
        legs = [
            flat(
                road("Paint Branch Trail", 1, 600, 0, 0, facility="path", use="cycleway"),
                forked(
                    road(
                        "Rhode Island Avenue Trolley Trail",
                        1,
                        600,
                        5,
                        5,
                        facility="path",
                        use="cycleway",
                    ),
                    "bear_right",
                ),
            )
        ]
        entries = d.describe(legs)
        assert entries[1]["turn"]["movement"] == "bear_right"
        assert "stay" not in entries[1]["turn"]
        assert "Bear right onto Rhode Island Avenue Trolley Trail," in entries[1]["text"]

    def test_a_short_stretch_begun_at_a_fork_is_never_folded_away(self):
        legs = [
            flat(
                road(None, 1, 400, 0, 0, facility="path", use="footway"),
                forked(road(None, 1, 40, 300, 300, facility="path", use="footway"), "bear_left"),
                road("Lake Artemesia Trail", 1, 400, 300, 300, facility="path", use="cycleway"),
            )
        ]
        entries = d.describe(legs)
        assert [e["turn"]["movement"] if e["turn"] else None for e in entries] == [
            None,
            "bear_left",
            "straight",
        ]

    def test_without_a_fork_a_bend_along_one_trail_is_still_no_turn(self):
        legs = [
            flat(
                road("Paint Branch Trail", 1, 600, 0, 0, facility="path", use="cycleway"),
                road("Paint Branch Trail", 1, 600, 270, 270, facility="path", use="cycleway"),
            )
        ]
        assert len(d.describe(legs)) == 1


class TestTheLastTurn:
    """The owner, 2026-10-18: "Same with destinations". North on the trolley trail,
    then right onto Berwyn Road 50 m before the end: the turn is said, not folded into
    the trail."""

    def test_a_short_last_street_turned_onto_is_kept(self):
        legs = [
            flat(
                road(
                    "Rhode Island Avenue Trolley Trail",
                    1,
                    900,
                    0,
                    0,
                    facility="path",
                    use="cycleway",
                ),
                road("Berwyn Road", 1, 50, 90, 90),
            )
        ]
        entries = d.describe(legs)
        assert entries[-1]["street"] == "Berwyn Road"
        assert entries[-1]["turn"]["movement"] == "right"

    def test_before_a_stop_too(self):
        legs = [
            flat(road("Path A", 1, 900, 0, 0), road("Baltimore Avenue", 2, 60, 270, 270)),
            road("Path A", 1, 900, 90, 90),
        ]
        entries = d.describe(legs)
        streets = [e.get("street") for e in entries if e["kind"] == "stretch"]
        assert streets[:2] == ["Path A", "Baltimore Avenue"]

    def test_straight_on_or_a_few_metres_is_still_folded(self):
        straight = [flat(road("Main St", 1, 900, 0, 0), road("Oak St", 1, 50, 5, 5))]
        assert len(d.describe(straight)) == 1
        stub = [flat(road("Main St", 1, 900, 0, 0), road("Oak St", 1, 10, 90, 90))]
        assert len(d.describe(stub)) == 1


class TestForksAreKeptEverywhere:
    def test_a_tiny_start_before_a_fork_is_folded_into_it_with_the_fork_kept(self):
        legs = [
            flat(
                road("Driveway Lane", 1, 30, 0, 0),
                forked(
                    road("Paint Branch Trail", 1, 600, 0, 0, facility="path", use="cycleway"),
                    "bear_left",
                ),
                road("Other Rd", 1, 600, 90, 90),
            )
        ]
        entries = d.describe(legs)
        assert entries[0]["street"] == "Paint Branch Trail"
        assert entries[0]["from_m"] == 0

    def test_the_overview_never_merges_a_fork_away(self):
        legs = [
            flat(
                road("Paint Branch Trail", 1, 900, 0, 0, facility="path", use="cycleway"),
                forked(
                    road("Paint Branch Trail", 1, 150, 270, 270, facility="path", use="cycleway"),
                    "left",
                ),
                road("Paint Branch Trail", 1, 900, 270, 270, facility="path", use="cycleway"),
            )
        ]
        _full, overview = d.describe_both(legs)
        assert any(e["turn"] and e["turn"].get("stay") for e in overview)


class TestServiceRoads:
    """The owner, 2026-10-20, on a frontage road beside East-West Highway: "When going on a
    service road, especially next to a major road, say so"."""

    EW = "service road beside East-West Highway"

    def test_a_turn_onto_an_unnamed_service_road_names_it(self):
        entries = d.describe(
            [
                road("Grubb Road", 2, 400, 0.0, 0.0)
                + road(None, 2, 400, 270.0, 270.0, use="service_road")
            ]
        )
        assert entries[1]["street"] == "service road"
        assert entries[1]["turn"]["onto"] == "service road"
        assert ": Left onto the service road, fairly low stress" in entries[1]["text"]

    def test_one_beside_a_major_road_says_which(self):
        entries = d.describe(
            [
                road("Grubb Road", 2, 400, 0.0, 0.0)
                + road(self.EW, 2, 400, 270.0, 270.0, use="service_road")
            ]
        )
        assert entries[1]["turn"]["onto"] == "service road beside East-West Highway"
        assert f": Left onto the {self.EW}, fairly low stress" in entries[1]["text"]

    def test_leaving_the_highway_straight_on_for_its_service_road_is_said(self):
        entries = d.describe(
            [
                road("East-West Highway", 4, 400, 45.0, 45.0)
                + road(self.EW, 2, 400, 50.0, 50.0, use="service_road")
            ]
        )
        assert len(entries) == 2
        assert f": Continue onto the {self.EW}, fairly low stress" in entries[1]["text"]

    def test_an_unnamed_road_then_an_unnamed_service_road_is_a_turn(self):
        entries = d.describe(
            [road(None, 2, 400, 0.0, 0.0) + road(None, 2, 400, 90.0, 90.0, use="driveway")]
        )
        assert [e["street"] for e in entries] == ["unnamed road", "service road"]
        assert entries[1]["turn"]["movement"] == "right"

    def test_an_alley_and_a_parking_aisle_are_said_as_such(self):
        entries = d.describe(
            [
                road("A Street", 2, 400, 0.0, 0.0)
                + road(None, 2, 200, 90.0, 90.0, use="alley")
                + road(None, 2, 200, 0.0, 0.0, use="parking_aisle")
            ]
        )
        assert [e["street"] for e in entries] == ["A Street", "alley", "parking aisle"]
        assert ": Right onto the alley," in entries[1]["text"]

    def test_a_path_beside_a_major_road_is_not_called_a_path_twice(self):
        entries = d.describe(
            [
                road("Grubb Road", 2, 400, 0.0, 0.0)
                + road("path beside EW Hwy", 1, 400, 270.0, 270.0, facility="path", use="footway")
            ]
        )
        assert entries[1]["text"].endswith(": Left onto the path beside EW Hwy, traffic-free.")

    def test_beside_words(self):
        assert d.beside_words("service_road", "X Road") == "service road beside X Road"
        assert d.beside_words("driveway", "X Road") == "service road beside X Road"
        assert d.beside_words("sidewalk", "X Road") == "sidewalk beside X Road"
        assert d.beside_words("cycleway", "X Road") == "path beside X Road"
        assert d.beside_words("alley", "X Road") is None
        assert d.beside_words("road", "X Road") is None


def branched(atoms, others):
    """`atoms` with the first given the other ways at its node (`describe.junction_shape`)."""
    return [replace(atoms[0], others=tuple(others)), *atoms[1:]]


class TestJunctionShapes:
    """The owner, 2026-10-20: "Can arrows be made more clear when there's unusual
    intersections? For instance if there's a left turn on a service road show the
    non-picked intersections dashed. Likewise with 5 way intersections and the like."
    The ride card draws the junction where it is unusual; a plain crossroads or T keeps
    its plain arrow."""

    def test_a_plain_crossroads_or_t_keeps_the_plain_arrow(self):
        assert d.junction_shape(0, 270, [(0, "road"), (90, "road")]) is None
        assert d.junction_shape(0, 270, [(90, "road")]) is None
        # A little off square is still square.
        assert d.junction_shape(10, 275, [(5, "road"), (100, "road")]) is None

    def test_a_five_way_junction_is_drawn(self):
        # North into a five-way: the route takes the right-hand diagonal.
        shape = d.junction_shape(0, 45, [(270, "road"), (0, "road"), (90, "road")])
        assert shape == {"out": 45, "others": [-90, 0, 90]}

    def test_a_branch_off_square_is_drawn(self):
        assert d.junction_shape(0, 270, [(30, "road")]) == {"out": -90, "others": [30]}

    def test_two_ways_to_one_side_are_drawn(self):
        # A left and a sharp left: which one the plain arrow means is not plain.
        assert d.junction_shape(0, 270, [(225, "road")]) == {"out": -90, "others": [-135]}

    def test_a_left_onto_a_service_road_is_drawn_with_the_road_on(self):
        assert d.junction_shape(0, 270, [(0, "road")], service=True) == {
            "out": -90,
            "others": [0],
        }
        # With no other way it is only a bend: nothing to draw.
        assert d.junction_shape(0, 270, [], service=True) is None

    def test_driveways_crosswalks_and_sidewalks_are_not_drawn(self):
        others = [
            (0, "road"),
            (90, "road"),
            (30, "driveway"),
            (45, "sidewalk"),
            (60, "pedestrian_crossing"),
        ]
        assert d.junction_shape(0, 270, others) is None

    def test_ways_close_together_are_one_branch(self):
        # A divided road's two carriageways, and a way alongside the route's own.
        shape = d.junction_shape(0, 270, [(40, "road"), (48, "road"), (275, "road")])
        assert shape == {"out": -90, "others": [40]}

    def test_without_headings_nothing_is_drawn(self):
        assert d.junction_shape(None, 270, [(30, "road")]) is None
        assert d.junction_shape(0, 270, None) is None
        assert d.junction_shape(0, 270, [(None, "road")]) is None

    def test_the_turn_carries_its_shape_in_both_lists(self):
        legs = [
            flat(
                road("Grubb Road", 2, 600, 0.0, 0.0),
                branched(
                    road(None, 2, 600, 270.0, 270.0, use="service_road"),
                    [(0.0, "road"), (90.0, "road")],
                ),
            )
        ]
        full, short = d.describe_both(legs)
        assert full[1]["turn"]["shape"] == {"out": -90, "others": [0, 90]}
        assert short[1]["turn"]["shape"] == {"out": -90, "others": [0, 90]}
        # The words are as they were.
        assert ": Left onto the service road, fairly low stress" in full[1]["text"]

    def test_a_plain_turn_carries_no_shape(self):
        legs = [
            flat(
                road("A Street", 2, 400, 0.0, 0.0),
                branched(road("B Street", 2, 400, 270.0, 270.0), [(0.0, "road"), (90.0, "road")]),
            )
        ]
        assert "shape" not in d.describe(legs)[1]["turn"]

    def test_a_way_almost_back_the_way_in_is_not_drawn_over_it(self):
        assert d.junction_shape(0, 270, [(160, "road"), (0, "road"), (90, "road")]) is None

    def test_no_shape_across_a_short_street_folded_in(self):
        # An offset crossing: A Street, 10 m of B Street, then C Street. The heading in
        # is A Street's and the ways out are C Street's node: two nodes, so no picture.
        legs = [
            flat(
                road("A Street", 2, 600, 0.0, 0.0),
                road("B Street", 2, 10, 90.0, 90.0),
                branched(
                    road("C Street", 2, 600, 0.0, 0.0),
                    [(270.0, "road"), (45.0, "road"), (300.0, "road")],
                ),
            )
        ]
        for entry in d.describe(legs):
            assert not (entry["turn"] or {}).get("shape"), entry


class TestServiceRoadMainRoad:
    """The owner, 2026-10-20, on the service road diagram: "In the service road case
    you'd be going further than the main road ... If making a left ... or shorter if
    making a right". The main road beside the service road is drawn where it lies."""

    EW = "service road beside East-West Highway"

    def test_crossed_just_before_it_lies_across_the_way_in(self):
        # North on Grubb Road, across East-West Highway (east-west), then left (west).
        behind = [(90.0, "road", "primary"), (270.0, "road", "primary")]
        assert d.main_road_side(270.0, [(0.0, "road", "residential")], behind) == "before"

    def test_otherwise_it_lies_across_the_way_ahead(self):
        assert d.main_road_side(90.0, [(0.0, "road", "residential")], None) == "after"
        # A busy road behind that is not alongside is not the one.
        assert d.main_road_side(90.0, [], [(0.0, "road", "primary")]) == "after"

    def test_at_the_turn_s_own_junction_it_is_drawn_there_already(self):
        assert d.main_road_side(270.0, [(90.0, "road", "primary")], None) is None

    def test_a_right_short_of_the_main_road_draws_it_ahead(self):
        legs = [
            flat(
                road("Grubb Road", 2, 600, 0.0, 0.0),
                branched(
                    road(self.EW, 2, 600, 90.0, 90.0, use="service_road"),
                    [(0.0, "road", "residential"), (270.0, "service_road", "service_other")],
                ),
            )
        ]
        shape = d.describe(legs)[1]["turn"]["shape"]
        assert shape == {"out": 90, "others": [-90, 0], "main": "after"}

    def test_a_left_across_it_draws_it_behind(self):
        atoms = road(self.EW, 2, 600, 270.0, 270.0, use="service_road")
        atoms[0] = replace(
            atoms[0],
            others=((0.0, "road", "residential"),),
            prior=((90.0, "road", "primary"), (270.0, "road", "primary")),
        )
        shape = d.describe([flat(road("Grubb Road", 2, 600, 0.0, 0.0), atoms)])[1]["turn"]["shape"]
        assert shape == {"out": -90, "others": [0], "main": "before"}

    def test_not_when_riding_the_main_road_itself(self):
        legs = [
            flat(
                road("East-West Highway", 4, 600, 90.0, 90.0),
                branched(
                    road(self.EW, 2, 600, 45.0, 45.0, use="service_road"),
                    [(90.0, "road", "primary")],
                ),
            )
        ]
        assert "main" not in (d.describe(legs)[1]["turn"].get("shape") or {})


def ringed(atoms, *others):
    """Ring atoms, the start of each later ring edge given the ways off at its node."""
    out = [replace(atom, roundabout=True) for atom in atoms]
    for k, ways in enumerate(others, start=1):
        out[k] = replace(out[k], others=tuple(ways))
    return out


class TestCircleExits:
    """The owner, 2026-10-20, on traffic circles: a ring picture and the exit number
    ("Ring picture + exit number")."""

    def legs(self):
        # North on Massachusetts Avenue into the ring, bearing right (anticlockwise);
        # it passes 18th Street (east, two-way) and New Hampshire Avenue (north, only
        # into the ring), a slip lane and a footway, and leaves west on P Street.
        ring = ringed(
            road("Dupont Circle Northwest", 3, 240, 45, 300),
            [(80.0, "road", "secondary", "both"), (60.0, "turn_channel", "secondary", "both")],
            [(0.0, "road", "secondary", "backward"), (20.0, "footway", None, "none")],
            [(330.0, "road", "secondary", "forward")],
        )
        return [
            flat(
                road("Massachusetts Avenue Northwest", 3, 600, 0, 0),
                ring,
                road("P Street Northwest", 3, 600, 270, 270),
            )
        ]

    def test_the_way_off_says_its_exit(self):
        entries = d.describe(self.legs())
        off = entries[-1]
        assert off["turn"]["exit"] == {"number": 3, "circle": "Dupont Circle Northwest"}
        assert (
            ": Take the 3rd exit onto P Street Northwest at Dupont Circle Northwest,"
            in (off["text"])
        )
        assert off["turn"]["shape"] == {"out": -90, "others": [80, -30], "ring": "right"}

    def test_a_small_circle_folded_in_still_says_its_exit(self):
        legs = self.legs()
        small = [a for a in legs[0] if not a.roundabout]
        ring = [a for a in legs[0] if a.roundabout][:2]
        ring = [replace(a, metres=30.0) for a in ring]
        legs = [small[:10] + ring + small[10:]]
        entries = d.describe(legs)
        assert [e["street"] for e in entries] == [
            "Massachusetts Avenue Northwest",
            "P Street Northwest",
        ]
        assert entries[1]["turn"]["exit"]["number"] == 2
        assert entries[1]["turn"]["shape"]["ring"] == "right"

    def test_an_unnamed_roundabout_is_the_roundabout(self):
        ring = ringed(road(None, 2, 60, 300, 330))
        entries = d.describe(
            [flat(road("A Street", 2, 600, 0, 0), ring, road("B Street", 2, 600, 270, 270))]
        )
        assert ": Take the 1st exit onto B Street at the roundabout," in entries[-1]["text"]
        assert entries[-1]["turn"]["shape"]["ring"] == "left"

    def test_ordinals(self):
        assert [d.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == [
            "1st",
            "2nd",
            "3rd",
            "4th",
            "11th",
            "12th",
            "13th",
            "21st",
            "22nd",
        ]

    def test_a_loop_street_named_circle_is_not_a_ring(self):
        # "Oak Circle" by name only: a street, its turns said as turns, no exit counted.
        loop = branched(road("Oak Circle", 2, 60, 90, 0), [(0.0, "road", None, "both")])
        entries = d.describe(
            [flat(road("Elm Street", 2, 600, 0, 0), loop, road("Main Street", 2, 600, 270, 270))]
        )
        assert all("exit" not in (e["turn"] or {}) for e in entries)
        assert "exit" not in entries[-1]["text"]


def bent(atoms, bearing):
    """`atoms` with each piece's own unwrapped bearing (`Atom.bearing`)."""
    return [replace(atom, bearing=bearing) for atom in atoms]


class TestHairpins:
    """The owner, 2026-10-20, by Veirs Mill Road at Rock Creek: "This is a right turn up
    onto a bridge". Valhalla's headings, each over the first or last 30 m or so of an
    edge, put a ramp that curls round to the right a little past straight back: read
    alone, a left. Past HAIRPIN_DEG the side is the one the route's own line turns to."""

    @staticmethod
    def hairpin(line_turn, h_out=190.0):
        return d.describe(
            [
                flat(
                    bent(road("Veirs Mill Road bike lane", 1, 400, 0, 0, "path", "cycleway"), 0),
                    bent(
                        road("Rock Creek Trl", 1, 400, h_out, h_out, "path", "cycleway"),
                        line_turn,
                    ),
                )
            ]
        )

    def test_a_hairpin_right_that_the_headings_read_as_a_left_is_a_right(self):
        # Headings: north, then 190 (a turn of -170). The line set off east (+90).
        entries = self.hairpin(90.0)
        assert entries[1]["turn"]["movement"] == "right"
        assert "Right onto Rock Creek Trl," in entries[1]["text"]

    def test_never_a_turn_of_more_than_240(self):
        before = d.Atom(10, "1", "none", heading_out=0, bearing=0)
        # Headings -125, a line of +300: +235 is the most it may read.
        assert d.turn_between(
            before, d.Atom(10, "1", "none", heading_in=235, bearing=300)
        ) == pytest.approx(235)
        assert d.turn_between(
            before, d.Atom(10, "1", "none", heading_in=125, bearing=300)
        ) == pytest.approx(125)

    def test_a_hairpin_left_stays_a_left(self):
        entries = self.hairpin(-90.0)
        assert entries[1]["turn"]["movement"] == "left"

    def test_without_the_line_the_headings_decide(self):
        legs = [
            flat(
                road("A Trail", 1, 400, 0, 0, "path", "cycleway"),
                road("B Trail", 1, 400, 190, 190, "path", "cycleway"),
            )
        ]
        assert d.describe(legs)[1]["turn"]["movement"] == "left"

    def test_an_ordinary_turn_never_reads_the_line(self):
        # A right of 90 by the headings stays a right even where the line wobbles.
        assert d.turn_between(
            d.Atom(10, "1", "none", heading_out=0, bearing=0),
            d.Atom(10, "1", "none", heading_in=90, bearing=-80),
        ) == pytest.approx(90)

    def test_the_turn_is_read_on_the_lines_side(self):
        before = d.Atom(10, "1", "none", heading_out=0, bearing=0)
        assert d.turn_between(before, d.Atom(10, "1", "none", heading_in=190, bearing=90)) == (
            pytest.approx(190)
        )
        assert d.turn_between(before, d.Atom(10, "1", "none", heading_in=170, bearing=-90)) == (
            pytest.approx(-190)
        )

    def test_a_hairpin_at_a_fork_is_said_on_the_lines_side_too(self):
        legs = [
            flat(
                bent(road("Rock Creek Trail", 1, 400, 0, 0, "path", "cycleway"), 0),
                bent(
                    forked(road("Rock Creek Trail", 1, 400, 190, 190, "path", "cycleway"), "left"),
                    100,
                ),
            )
        ]
        entries = d.describe(legs)
        assert entries[1]["turn"]["movement"] == "right"
        assert "Right to stay on Rock Creek Trail," in entries[1]["text"]

    def test_a_hairpin_drawn_the_other_way_keeps_the_plain_arrow(self):
        legs = [
            flat(
                bent(road("A Trail", 1, 400, 0, 0, "path", "cycleway"), 0),
                [
                    replace(
                        atom,
                        bearing=90,
                        others=((60, "footway", "both"), (300, "footway", "both"))
                        if i == 0
                        else None,
                    )
                    for i, atom in enumerate(road("B Trail", 1, 400, 190, 190, "path", "cycleway"))
                ],
            )
        ]
        turn = d.describe(legs)[1]["turn"]
        assert turn["movement"] == "right"
        assert "shape" not in turn


class TestLeaningForks:
    """The owner, 2026-10-20, on Rock Creek Trail by Norbeck Road: "It missed a trail
    fork". A Y whose branches each lean well off straight is still a fork."""

    def test_a_y_of_two_leaning_branches_is_a_fork(self):
        assert d.fork_movement(0, 300, [(60, "path", "both")], trail=True) == "bear_left"
        assert d.fork_movement(0, 60, [(300, "cycleway", "both")], trail=True) == "bear_right"

    def test_a_branch_well_past_the_routes_own_bend_is_none(self):
        # The route bends 30 left, a branch 70 right: the route is plainly the way on.
        assert d.fork_movement(0, 330, [(70, "path", "both")], trail=True) is None

    def test_a_t_on_a_trail_is_a_turn_to_stay_on_it(self):
        assert d.fork_movement(0, 270, [(90, "path", "both")], trail=True) == "left"

    def test_a_sidewalk_or_a_road_is_no_leaning_choice(self):
        assert d.fork_movement(0, 300, [(60, "sidewalk", "both")], trail=True) is None
        assert d.fork_movement(0, 300, [(60, "road", "both")], trail=True) is None

    def test_off_a_trail_a_leaning_branch_is_no_fork(self):
        # A street curving 50 right with a side street 65 left: no question.
        assert d.fork_movement(0, 50, [(295, "road", "both")]) is None
        # A sidepath bending at a footway.
        assert d.fork_movement(0, 300, [(60, "footway", "both")]) is None

    def test_a_branch_behind_is_never_a_choice(self):
        assert d.fork_movement(0, 240, [(100, "path", "both")], trail=True) is None


class TestCrossings:
    """The owner, 2026-10-20, north on the Needwood Road bike lane at Redland Road: "It
    should have told me to cross the street and turn left". A short path across a road
    between two turns is said as the crossing, not a bear to stay on the path."""

    @staticmethod
    def needwood(events=None, middle_use="cycleway", middle_m=25):
        legs = [
            flat(
                road("Needwood Road bike lane", 1, 400, 0, 0, "path", "cycleway"),
                forked(
                    road("Needwood Road bike lane", 1, middle_m, 30, 30, "path", middle_use),
                    "bear_right",
                ),
                road("Redland Road bike lane", 1, 400, 290, 290, "path", "cycleway"),
            )
        ]
        return d.describe(legs, events)

    def test_a_crossing_between_two_turns_is_said_as_the_crossing(self):
        crossing = event(410, "straight", kind="crossing", names=("redland road",), flagged=False)
        entries = self.needwood([crossing])
        assert entries[1]["turn"]["cross"] == "Redland Road"
        # The junction's control is the crossing's.
        assert "Cross Redland Road at a signal," in entries[1]["text"]
        assert entries[2]["turn"]["movement"] == "left"
        assert "Left onto Redland Road bike lane" in entries[2]["text"]

    def test_a_crosswalk_with_no_event_crosses_the_road(self):
        entries = self.needwood(middle_use="pedestrian_crossing")
        assert entries[1]["turn"]["cross"] == "the road"
        assert "Cross the road," in entries[1]["text"]

    def test_without_a_road_crossed_it_is_the_turn(self):
        entries = self.needwood()
        assert "cross" not in entries[1]["turn"]
        assert "Bear right to stay on Needwood Road bike lane," in entries[1]["text"]

    def test_a_long_middle_is_no_crossing(self):
        crossing = event(420, "straight", kind="crossing", names=("redland road",), flagged=False)
        entries = self.needwood([crossing], middle_m=200)
        assert "cross" not in entries[1]["turn"]

    def test_a_left_across_a_road_is_a_crossing_and_the_nearest_event_names_it(self):
        far = event(395, "left", kind="left_across", names=("muncaster mill road",), flagged=False)
        near = event(412, "left", kind="left_across", names=("redland road",), flagged=False)
        assert self.needwood([far, near])[1]["turn"]["cross"] == "Redland Road"

    def test_an_unnamed_road_crossed_is_the_road(self):
        crossing = event(410, "straight", kind="crossing", names=(), flagged=False)
        assert self.needwood([crossing])[1]["turn"]["cross"] == "the road"

    def test_the_road_turned_onto_is_not_the_one_crossed(self):
        onto = event(424, "left", kind="crossing", names=("redland road bike lane",), flagged=False)
        assert "cross" not in self.needwood([onto])[1]["turn"]

    def test_the_road_the_route_was_on_is_not_the_one_crossed(self):
        crossing = event(
            410, "straight", kind="crossing", names=("needwood road bike lane",), flagged=False
        )
        assert "cross" not in self.needwood([crossing])[1]["turn"]
