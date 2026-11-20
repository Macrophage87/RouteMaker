"""Raters' junction ratings in the planner (the owner, 2026-11-20: "Build, free below 2.5").

A junction node the raters rated sets the stress cost of the movement the route makes there:
nothing below 2.5, the model's own scale from 2.5 up, the ride time's factor on top. A
divided road's crossing rated at both carriageway nodes is charged once.
"""

from __future__ import annotations

import gzip
import io
from dataclasses import replace

import pytest
from django.core.management import call_command

from routemaker import intersections as m
from routemaker import ridetime
from routemaker.intersections import Control, Junction, Movement, RaterRating, Road

QUIET = Road(2, names=frozenset({"quiet st"}))
BUSY = Road(4, speed_mph=40.0, lanes=2, oneway=False, urban=True, names=frozenset({"big rd"}))


def rater(cross=None, left=None, along=None, lon=-77.0, lat=38.9) -> RaterRating:
    return RaterRating(lon, lat, (cross, left, along), (None, None, None))


def junction(**fields) -> Junction:
    base = {
        "m": 0.0,
        "lon": -77.0,
        "lat": 38.9,
        "movement": Movement.STRAIGHT,
        "incoming": QUIET,
        "outgoing": QUIET,
        "crossed": (BUSY,),
        "control": Control.STOP,
    }
    return Junction(**(base | fields))


def test_a_rated_crossing_below_two_and_a_half_costs_nothing() -> None:
    for level in (1.0, 1.5, 2.0):
        assert m.assess(junction(rater=rater(cross=level))) is None


def test_a_rated_crossing_costs_the_models_scale() -> None:
    for level, ft in ((2.5, 800.0), (3.0, 1600.0), (3.5, 2800.0), (4.0, 4000.0), (5.0, 10560.0)):
        event = m.assess(junction(rater=rater(cross=level)))
        assert event is not None and event.cost_ft == pytest.approx(ft), level
        assert event.rater_level == level
    assert m.rater_cost_ft(4.5) == pytest.approx((4000.0 + 10560.0) / 2)


def test_the_rating_replaces_the_models_cost() -> None:
    model = m.assess(junction())
    rated = m.assess(junction(rater=rater(cross=3.0)))
    assert model is not None and model.cost_ft > 1600.0
    assert rated is not None and rated.cost_ft == pytest.approx(1600.0)


def test_rush_hour_multiplies_a_rated_gap_wait() -> None:
    plain = m.assess(junction(rater=rater(cross=4.0)))
    rush = m.assess(junction(rater=rater(cross=4.0)), when=ridetime.WEEKDAY_RUSH)
    assert plain is not None and rush is not None
    assert rush.cost_ft == pytest.approx(4000.0 * m.UNSIGNALISED_RUSH_FACTOR)
    assert rush.untimed_ft == pytest.approx(4000.0)


def test_the_route_s_movement_picks_the_rating() -> None:
    r = rater(cross=4.0, left=5.0, along=1.0)
    left = m.assess(junction(movement=Movement.LEFT, crossed=(), outgoing=BUSY, rater=r))
    assert left is not None and left.rater_level == 5.0
    # Riding along the big road past a quiet side street: `along`, free.
    along = junction(incoming=BUSY, outgoing=BUSY, crossed=(QUIET,), continues=True, rater=r)
    assert m.rater_move(along) == "along"
    assert m.assess(along) is None


def test_a_right_turn_and_a_missing_movement_keep_the_models_cost() -> None:
    right = junction(movement=Movement.RIGHT, crossed=(), outgoing=BUSY)
    assert m.rater_move(right) is None
    assert m.assess(replace(right, rater=rater(cross=1.0))) == m.assess(right)
    # The loader drops a move the one-way check flags: no rating, the model's cost.
    assert m.assess(junction(rater=rater(left=2.0))) == m.assess(junction())


def test_a_rider_rating_still_comes_first() -> None:
    event = m.assess(junction(rating=2, rater=rater(cross=5.0)))
    assert event is not None and event.rating == 2 and event.rater_level is None


def test_a_mass_ride_keeps_its_own_reading() -> None:
    assert m.assess(junction(rater=rater(cross=1.0)), group=True) == m.assess(
        junction(), group=True
    )


def test_a_quiet_junction_the_raters_find_hard_costs_something() -> None:
    quiet = junction(crossed=(replace(QUIET, names=frozenset({"other st"})),))
    assert m.assess(quiet) is None
    event = m.assess(replace(quiet, rater=rater(cross=3.0)))
    assert event is not None and event.kind == "rated" and event.cost_ft == pytest.approx(1600.0)


def test_with_raters_matches_the_node_only() -> None:
    # A degree of longitude at 38.9 N is about 86.6 km: 0.00001 is about 0.9 m, 0.0001 9 m.
    same = rater(cross=4.0, lon=-77.00001)
    beside = rater(cross=4.0, lon=-77.0001)
    assert m.with_raters([junction()], [same])[0].rater == same
    # A sidepath's crossing of a side street 9 m from the arterial's rated junction is its
    # own junction: it never reads the arterial's crossing (review, 2026-11-20).
    assert m.with_raters([junction()], [beside])[0].rater is None


def test_a_divided_roads_far_carriageway_takes_the_near_nodes_rating() -> None:
    side = replace(BUSY, oneway=True, ways=frozenset({1}))
    other = replace(BUSY, oneway=True, ways=frozenset({2}))
    near = junction(crossed=(side,))
    far = junction(m=25.0, lon=-76.9997, crossed=(other,))
    for level, cost in ((2.0, None), (4.0, 4000.0)):
        built = m.with_raters([near, far], [rater(cross=level)])
        assert all(j.rater is not None for j in built)
        events = m.merge_nearby([e for e in map(m.assess, built) if e is not None])
        if cost is None:
            assert events == []
        else:
            assert len(events) == 1 and events[0].cost_ft == pytest.approx(cost)


def test_riding_on_where_the_name_changes_is_riding_along() -> None:
    renamed = replace(BUSY, names=frozenset({"new rd"}))
    j = junction(incoming=BUSY, outgoing=renamed, crossed=(QUIET,), continues=False)
    assert m.rater_move(j) == "along"
    # Two roads alike, met from one onto the other's crossing: the crossing is rated.
    alike = junction(incoming=BUSY, outgoing=BUSY, crossed=(replace(BUSY, names=frozenset()),))
    assert m.rater_move(alike) == "cross"


def test_a_divided_road_rated_at_both_carriageways_is_charged_once() -> None:
    side = replace(BUSY, oneway=True, ways=frozenset({1}))
    other = replace(BUSY, oneway=True, ways=frozenset({2}))
    first = m.assess(junction(crossed=(side,), rater=rater(cross=4.0)))
    second = m.assess(junction(m=25.0, crossed=(other,), rater=rater(cross=4.0)))
    assert first is not None and second is not None
    merged = m.merge_nearby([first, second])
    assert len(merged) == 1 and merged[0].cost_ft == pytest.approx(4000.0)


# --- The raters' seconds scale the measured waits ---------------------------------------


def _raw(**fields):
    from routemaker import trace_junctions as t

    base = {
        "m": 100.0,
        "lon": -77.0,
        "lat": 38.9,
        "in_edge_id": None,
        "in_way": 1,
        "out_way": 1,
        "movement": Movement.STRAIGHT,
        "in_use": "road",
        "out_use": "road",
        "others": (("road", False), ("road", False)),
        "in_class": "residential",
        "out_class": "residential",
        "other_classes": ("primary", "primary"),
        "signal": True,
        "in_heading": 90.0,
        "other_headings": (0.0, 180.0),
    }
    return t.RawJunction(**(base | fields))


def _signal_rater(cross_s: float) -> RaterRating:
    return RaterRating(-77.0, 38.9, (2.0, 3.0, 1.0), (cross_s, 40.0, 6.0), "signal")


MEDIANS = {("signal", "cross"): 30.0, ("signal", "left"): 40.0, ("signal", "along"): 6.0}


def test_a_wait_is_scaled_by_its_rated_seconds_over_the_median() -> None:
    from routemaker import junction_delay as d

    raw = _raw()
    found = d.waits([raw])
    assert len(found) == 1
    model = found[0]
    # Rated at the median: the measured wait as it is.
    same = d.rater_scaled(found, [raw], [_signal_rater(30.0)], MEDIANS)
    assert same[0].seconds == pytest.approx(model.seconds)
    # Rated at 45 s against a 30 s median: half as long again, shown, ranked and red.
    longer = d.rater_scaled(found, [raw], [_signal_rater(45.0)], MEDIANS)[0]
    assert longer.seconds == pytest.approx(model.seconds * 1.5)
    assert longer.ranked_s == pytest.approx(model.ranked_s * 1.5)
    assert longer.red_s == pytest.approx(model.red_s * 1.5)


def test_the_ratio_is_held_in_range() -> None:
    from routemaker import junction_delay as d

    raw = _raw()
    found = d.waits([raw])
    long = d.rater_scaled(found, [raw], [_signal_rater(300.0)], MEDIANS)[0]
    short = d.rater_scaled(found, [raw], [_signal_rater(1.0)], MEDIANS)[0]
    assert long.seconds == pytest.approx(found[0].seconds * d.RATER_RATIO_MAX)
    assert short.seconds == pytest.approx(found[0].seconds * d.RATER_RATIO_MIN)


def test_an_unrated_wait_or_no_medians_keeps_the_model() -> None:
    from routemaker import junction_delay as d

    raw = _raw()
    found = d.waits([raw])
    far = replace(_signal_rater(60.0), lon=-77.01)
    assert d.rater_scaled(found, [raw], [far], MEDIANS) == found
    assert d.rater_scaled(found, [raw], [_signal_rater(60.0)], {}) == found


def test_a_run_reads_the_rated_node_past_its_first() -> None:
    from routemaker import junction_delay as d

    # The run starts at a stop line 10 m short of the rated signal node.
    stop_line = _raw(m=90.0, lon=-77.0002, others=(), other_classes=(), other_headings=())
    raw = _raw()
    found = d.waits([stop_line, raw])
    assert len(found) == 1
    scaled = d.rater_scaled(found, [stop_line, raw], [_signal_rater(45.0)], MEDIANS)
    assert scaled[0].seconds == pytest.approx(found[0].seconds * 1.5)


def test_a_left_reads_the_left_seconds() -> None:
    from routemaker import junction_delay as d

    raw = _raw(movement=Movement.LEFT)
    found = d.waits([raw])
    scaled = d.rater_scaled(found, [raw], [_signal_rater(60.0)], MEDIANS)
    # The left is rated 40 s against a 40 s median: as it was, whatever the crossing says.
    assert scaled[0].seconds == pytest.approx(found[0].seconds)


# --- Loading and reading the table ----------------------------------------------------

HEADER = "junction,control_tagged,movement,stress,delay_s,decided_by,oneway_flag"
CSV = "\n".join(
    [
        HEADER,
        "j1,signal,cross,3.5,30,first pass opus,",
        "j1,signal,left,4,45,opus review,",
        "j1,signal,along,1,6,first pass opus,",
        "j2,stop,cross,4.5,40,first pass sonnet,one-way main road (driveway or service road)",
        "j2,stop,left,,,cannot be made (opus review),",
        "j2,stop,along,1,0,first pass sonnet,",
        "j3,none,cross,2,5,first pass sonnet,",
    ]
)
NODES = "\n".join(
    [
        "junction\tnode\tlon\tlat",
        "j1\t1\t-77.0\t38.9",
        "j1\t5\t-76.9997\t38.9",
        "j2\t2\t-77.01\t38.9",
    ]
)


def _files(tmp_path):
    ratings = tmp_path / "ratings.csv.gz"
    with gzip.open(ratings, "wt", encoding="utf-8") as out:
        out.write(CSV + "\n")
    nodes = tmp_path / "junction-nodes.tsv"
    nodes.write_text(NODES + "\n")
    return str(ratings), str(nodes)


@pytest.mark.django_db
def test_the_loader_is_dry_unless_confirmed(tmp_path) -> None:
    from core.models import JunctionRater

    out = io.StringIO()
    call_command("load_junction_raters", *_files(tmp_path), stdout=out)
    text = out.getvalue()
    assert "2 junctions at 3 nodes, 5 movements rated" in text
    assert "dropped 1 movements: one-way flag" in text
    assert "dropped 1 movements: cannot be made" in text
    assert "dropped 1 junctions: no nodes" in text
    assert JunctionRater.objects.count() == 0


@pytest.mark.django_db
def test_a_confirmed_load_replaces_the_table_and_reads_near_a_route(tmp_path) -> None:
    from core import junction_raters
    from core.models import JunctionRater

    call_command("load_junction_raters", *_files(tmp_path), "--confirm", stdout=io.StringIO())
    call_command("load_junction_raters", *_files(tmp_path), "--confirm", stdout=io.StringIO())
    assert JunctionRater.objects.count() == 3
    # Both of j1's nodes carry its rating.
    assert len(junction_raters.near([(-76.9997, 38.9)])) == 1
    found = junction_raters.near([(-77.00002, 38.9)])
    assert len(found) == 1
    rated = found[0]
    assert rated.control == "signal"
    assert rated.stress == (3.5, 4.0, 1.0) and rated.delay_s == (30.0, 45.0, 6.0)
    # j2's crossing was flagged one-way and its left cannot be made: only riding along.
    (j2,) = junction_raters.near([(-77.01, 38.9)])
    assert j2.stress == (None, None, 1.0)
    assert junction_raters.near([(-76.9, 38.9)]) == ()
    medians = junction_raters.medians()
    assert medians[("signal", "cross")] == pytest.approx(30.0)
    assert junction_raters.digest()
