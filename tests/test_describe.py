"""The route description (`routemaker.describe`, OWNER-DECISIONS 220): stretches
merged from the traced pieces, the wording of each, the turns and junctions, the
via-point split, and the totals. Pure: no router, no database."""

from __future__ import annotations

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


class TestVias:
    def test_the_leg_boundary_is_an_entry_and_nothing_spans_it(self):
        first = road("Capital Crescent Trail", 1, 1500, facility="path")
        second = road("Capital Crescent Trail", 1, 1500, facility="path")
        entries = d.describe([first, second])
        assert texts(entries) == [
            "0.0 to 0.9 mi (0.0 to 1.5 km): Capital Crescent Trail, traffic-free path.",
            "Via 1: stop at 0.9 mi (1.5 km).",
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

    def test_an_unnamed_trail_is_an_unnamed_path(self):
        entries = d.describe([road(None, 1, 700, facility="path", use="cycleway")])
        assert len(entries) == 1  # its unnamed pieces are one stretch
        assert entries[0]["street"] == "unnamed path"
        assert entries[0]["text"].endswith("unnamed path, traffic-free.")

    def test_an_unnamed_sidewalk_is_an_unnamed_path_by_its_use(self):
        entries = d.describe([road(None, 2, 700, use="footway")])
        assert entries[0]["street"] == "unnamed path"

    def test_an_unnamed_path_is_not_called_a_path_twice(self):
        text = d.describe([road(None, 1, 700, facility="path", use="cycleway")])[0]["text"]
        assert text.endswith("unnamed path, traffic-free.")

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
