"""Where a route's time falls along it, for a ride's arrival times (`routemaker.time_marks`).

The owner, 2026-10-26: "Does on ride ETA also consider elevation?" then "yes. make sure
intersection waits are considered too".
"""

from __future__ import annotations

from test_junction_delay import junction

from routemaker import junction_delay, time_marks

# Two legs along a parallel, about 100 m a vertex: four vertices, the joint at index 2.
LINE = [(-77.0, 38.9), (-76.99885, 38.9), (-76.9977, 38.9), (-76.99655, 38.9)]
ENDS = [2, 3]


def leg(maneuvers=None, seconds=0.0):
    out = {"summary": {"time": seconds}}
    if maneuvers is not None:
        out["maneuvers"] = maneuvers
    return out


def test_router_marks_keep_a_slow_climb_where_it_is():
    # Leg one: a flat 20 s then a climb of 80 s over the same length; leg two, 20 s flat.
    legs = [
        leg(
            [
                {"time": 20, "begin_shape_index": 0},
                {"time": 80, "begin_shape_index": 1},
                {"time": 0, "begin_shape_index": 2},
            ]
        ),
        leg([{"time": 20, "begin_shape_index": 0}, {"time": 0, "begin_shape_index": 1}]),
    ]
    marks = time_marks.router_marks(legs, LINE, ENDS)
    assert marks is not None
    at = {round(f, 2): s for f, s in marks}
    assert at[0.0] == 0.0
    assert at[0.33] == 20.0
    assert at[0.67] == 100.0
    assert at[1.0] == 120.0


def test_a_leg_without_maneuver_times_is_spread_over_itself():
    legs = [leg(None, 50.0), leg([], 10.0)]
    marks = time_marks.router_marks(legs, LINE, ENDS)
    assert [(round(f, 2), s) for f, s in marks] == [(0.0, 0.0), (0.67, 50.0), (1.0, 60.0)]


def test_no_marks_without_length_time_or_matching_legs():
    assert time_marks.router_marks([leg(None, 10.0)], [(0.0, 0.0)], [0]) is None
    assert time_marks.router_marks([leg(None, 0.0), leg(None, 0.0)], LINE, ENDS) is None
    assert time_marks.router_marks([leg(None, 10.0)], LINE, ENDS) is None
    assert time_marks.time_marks(None, [(10.0, 15.0)], 300.0) is None


def test_each_junction_wait_is_a_step_at_its_place():
    router = [(0.0, 0.0), (1.0, 60.0)]
    # A signal a quarter of the way along, a stop three quarters.
    marks = time_marks.time_marks(router, [(75.0, 15.0), (225.0, 8.0)], 300.0)
    assert marks == [
        [0.0, 0.0],
        [0.25, 15.0],
        [0.25, 30.0],
        [0.75, 60.0],
        [0.75, 68.0],
        [1.0, 83.0],
    ]
    # The end is the router's time and every wait.
    assert marks[-1][1] == 60.0 + 15.0 + 8.0


def test_a_wait_at_the_very_end_is_kept():
    marks = time_marks.time_marks([(0.0, 0.0), (1.0, 60.0)], [(300.0, 8.0)], 300.0)
    assert marks[-1] == [1.0, 68.0]


def test_delay_runs_sum_to_delay_s_and_sit_where_the_runs_begin():
    cross = (("road", "residential"), ("road", "residential"))
    signal = junction(*cross, m=100.0, signal=True)
    stop = junction(*cross, m=400.0)
    stop_again = junction(*cross, m=405.0)
    runs = junction_delay.delay_runs([stop_again, signal, stop])
    assert [m for m, _s in runs] == [100.0, 400.0]
    assert runs[0][1] == junction_delay.SIGNAL_DELAY_S
    assert junction_delay.delay_s([stop_again, signal, stop]) == sum(s for _m, s in runs)
    assert junction_delay.delay_runs([]) == []


def test_legs_of_uneven_vertex_counts_index_their_own_shapes():
    # Leg one is a single edge (vertices 0-1), leg two three (1-4): its indices start at the joint.
    line = [(-77.0 + i * 0.00115, 38.9) for i in range(5)]
    legs = [
        leg([{"time": 10, "begin_shape_index": 0}, {"time": 0, "begin_shape_index": 1}]),
        leg(
            [
                {"time": 10, "begin_shape_index": 0},
                {"time": 50, "begin_shape_index": 2},
                {"time": 0, "begin_shape_index": 3},
            ]
        ),
    ]
    marks = time_marks.router_marks(legs, line, [1, 4])
    at = sorted({(round(f, 2), s) for f, s in marks})
    assert at == [(0.0, 0.0), (0.25, 10.0), (0.75, 20.0), (1.0, 70.0)]


def test_a_wait_on_a_maneuver_mark_comes_after_the_router_time_there():
    marks = time_marks.time_marks([(0.0, 0.0), (0.5, 30.0), (1.0, 60.0)], [(150.0, 15.0)], 300.0)
    assert marks == [[0.0, 0.0], [0.5, 30.0], [0.5, 45.0], [1.0, 75.0]]
