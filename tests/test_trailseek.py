"""The trail seek's geometry (`core.trailseek`): which corridors of trail and
protected lane near the line are worth asking the router for, and the points that
ask for them. OWNER-DECISIONS 194, FOLLOWUP-TRAIL-SEEK.

The geometry is pure; the one query (`corridor_segments`) runs against a scratch
segment table.
"""

from __future__ import annotations

import math

import pytest

from core import trailseek as ts
from pipeline.schema import PATH_RULES

START = (-77.0, 38.9)
# 0.1 degrees east: 8.7 km.
END = (-76.9, 38.9)
# Metres per degree here, as the plane has them.
KX = 111_320.0 * math.cos(math.radians(38.9))
KY = 110_540.0


def line(lon0: float, lon1: float, north_m: float = 300.0, step: float = 0.002) -> list[tuple]:
    """A trail running east from START + lon0 to START + lon1 (degrees), `north_m`
    north of the line, as pairs of vertices (one segment each), so that the
    network has to be joined from its pieces."""
    n = max(1, round((lon1 - lon0) / step))
    lat = START[1] + north_m / KY
    pts = [(START[0] + lon0 + (lon1 - lon0) * i / n, lat) for i in range(n + 1)]
    return [[a, b] for a, b in zip(pts, pts[1:], strict=False)]


def metres(a, b) -> float:
    return math.hypot((a[0] - b[0]) * KX, (a[1] - b[1]) * KY)


def corridor(**kw) -> ts.Corridor:
    base = {
        "entry": START,
        "exit": END,
        "trail_m": 5000.0,
        "gain_m": 5000.0,
        "detour_m": 100.0,
        "score": 4900.0,
        "t_in": 0.0,
        "t_out": 5000.0,
    }
    base.update(kw)
    return ts.Corridor(**base)


class TestPlane:
    def test_along_and_across_the_line(self) -> None:
        plane = ts.Plane(START, END)
        assert plane.span == pytest.approx(0.1 * KX)
        x, y = plane.xy(START[0] + 0.05, START[1] + 200 / KY)
        assert plane.along(x, y) == pytest.approx(0.05 * KX)
        # North is to the left of a line running east.
        assert plane.across(x, y) == pytest.approx(200.0)

    def test_the_plane_round_trips(self) -> None:
        plane = ts.Plane(START, END)
        lon, lat = plane.lonlat(*plane.xy(-76.95, 38.93))
        assert (lon, lat) == pytest.approx((-76.95, 38.93))

    def test_a_line_running_north_east(self) -> None:
        plane = ts.Plane((-77.0, 38.9), (-76.99, 38.91))
        x, y = plane.xy(-76.995, 38.905)
        assert plane.along(x, y) == pytest.approx(plane.span / 2, rel=1e-6)
        assert plane.across(x, y) == pytest.approx(0.0, abs=1e-6)


LENGTH = 0.1 * KX


def route_xy() -> list[tuple[float, float]]:
    """The route: the straight line, as lon/lat vertices every 0.01 degrees."""
    return [(START[0] + i * 0.01, START[1]) for i in range(11)]


def seek(segments, spans=((3000.0, 6000.0, 1.0),), rate=10.0, route=None, end=END, traced=None):
    return ts.find_corridors(
        segments, START, end, route or route_xy(), spans, traced or LENGTH, rate
    )


class TestRouteLine:
    def make(self, spans, traced=None) -> ts.RouteLine:
        return ts.RouteLine([(0.0, 0.0), (5000.0, 0.0), (10_000.0, 0.0)], spans, traced)

    def test_the_exposure_is_weighted_metres_up_to_a_distance(self) -> None:
        line = self.make([(1000.0, 2000.0, 1.0), (3000.0, 4000.0, 2.0)])
        assert line.busy_to(500.0) == 0.0
        assert line.busy_to(1500.0) == pytest.approx(500.0)
        assert line.busy_to(2500.0) == pytest.approx(1000.0)
        assert line.busy_to(3500.0) == pytest.approx(1000.0 + 1000.0)
        assert line.busy_to(9000.0) == pytest.approx(1000.0 + 2000.0)

    def test_spans_are_scaled_to_the_lines_length(self) -> None:
        # The trace says the route is 20,000 m; the line is 10,000 m.
        line = self.make([(2000.0, 4000.0, 1.0)], traced=20_000.0)
        assert line.busy_to(5000.0) == pytest.approx(1000.0)
        assert line.busy_to(10_000.0) == pytest.approx(1000.0)

    def test_overlapping_spans_are_not_counted_twice_and_empty_ones_are_dropped(self) -> None:
        line = self.make([(1000.0, 3000.0, 1.0), (2000.0, 4000.0, 1.0), (5000.0, 5000.0, 1.0)])
        assert line.busy_to(10_000.0) == pytest.approx(3000.0)
        assert self.make([(0.0, 1000.0, 0.0)]).starts == []

    def test_no_spans_no_exposure(self) -> None:
        assert self.make([]).busy_to(5000.0) == 0.0

    def test_the_nearest_point_is_within_the_join_distance(self) -> None:
        line = self.make([])
        s, d = line.nearest(2500.0, 150.0)
        assert s == pytest.approx(2500.0, abs=15.0) and d == pytest.approx(150.0, abs=1.0)
        assert line.nearest(2500.0, ts.JOIN_M + 1.0) is None
        assert line.nearest(2500.0, ts.JOIN_M - 1.0) is not None

    def test_the_gaps_between_vertices_are_filled(self) -> None:
        line = ts.RouteLine([(0.0, 0.0), (50_000.0, 0.0)])
        s, _d = line.nearest(25_000.0, 10.0)
        assert s == pytest.approx(25_000.0, abs=ts.ROUTE_STEP_M)

    def test_a_wide_radius_looks_across_its_own_cells(self) -> None:
        line = ts.RouteLine([(0.0, 0.0), (10_000.0, 0.0)], radius=1500.0)
        assert line.nearest(5000.0, 1400.0) is not None
        assert line.nearest(5000.0, 1600.0) is None

    def test_a_route_point_in_the_next_cell_is_still_near(self) -> None:
        line = ts.RouteLine([(190.0, 0.0), (190.0, 100.0)])
        s, d = line.nearest(210.0, 0.0)
        assert d == pytest.approx(20.0)
        assert line.nearest(-10.0, 0.0) is not None and line.nearest(190.0, -150.0) is not None

    def test_an_empty_route_is_near_nothing(self) -> None:
        line = ts.RouteLine([])
        assert line.nearest(0.0, 0.0) is None and line.length == 0.0


class TestFindingCorridors:
    def test_a_trail_beside_a_busy_stretch_replaces_it(self) -> None:
        (c,) = seek(line(0.01, 0.09, north_m=150.0))
        assert c.gain_m == pytest.approx(3000.0)
        # Leaves the route at the start of the busy stretch and rejoins at its end
        # (anywhere along the trail before and after would do as well).
        assert c.t_in <= 3000.0 + 20 and c.t_out >= 6000.0 - 20
        assert c.detour_m == pytest.approx(300.0 + c.trail_m - (c.t_out - c.t_in), abs=1.0)
        assert c.score == pytest.approx(10.0 * c.gain_m - c.detour_m)
        assert c.trail_m == pytest.approx(c.t_out - c.t_in, rel=0.02)

    def test_the_pieces_are_joined_where_their_ends_meet(self) -> None:
        first, second = line(0.01, 0.05, north_m=150.0), line(0.05, 0.09, north_m=150.0)
        # The second trail starts a fifth of a metre from where the first ends: one node.
        second[0] = [(second[0][0][0] + 2.5e-6, second[0][0][1]), second[0][1]]
        (c,) = seek(first + second)
        assert c.gain_m == pytest.approx(3000.0)
        # Two metres away they are two trails, neither covering the stretch.
        second[0] = [(second[0][0][0] + 2.5e-5, second[0][0][1]), second[0][1]]
        assert len(seek(first + second)) == 2

    def test_pieces_with_a_gap_are_separate_networks(self) -> None:
        # The gap is across the busy stretch's middle: neither piece covers it.
        pieces = line(0.01, 0.045, north_m=150.0) + line(0.055, 0.09, north_m=150.0)
        found = seek(pieces)
        assert len(found) == 2
        assert all(c.gain_m < 3000.0 for c in found)

    def test_the_exposure_is_the_stretchs_own_weighted(self) -> None:
        (c,) = seek(line(0.01, 0.09, north_m=150.0), spans=[(3000.0, 6000.0, 2.0)])
        assert c.gain_m == pytest.approx(6000.0)

    def test_what_is_replaced_is_what_the_trail_spans(self) -> None:
        # A trail along only the first part of the busy stretch replaces that part.
        (c,) = seek(line(0.03, 0.045, north_m=150.0))
        assert c.gain_m == pytest.approx(0.045 * KX - 3000.0, abs=60.0)

    def test_the_rate_says_what_a_metre_of_busy_road_is_worth(self) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        assert seek(trail, rate=10.0)
        # 3,000 m of exposure at a rate of 0.05 is 150 m: it cannot pay for the 300 m
        # of joins and clear the least score.
        assert seek(trail, rate=0.05) == []
        assert seek(trail, rate=0.0) == []

    def test_a_route_with_nothing_busy_on_it_has_nothing_to_replace(self) -> None:
        assert seek(line(0.01, 0.09, north_m=150.0), spans=()) == []

    def test_a_trail_away_from_the_busy_stretch_gains_nothing(self) -> None:
        assert seek(line(0.0, 0.03, north_m=150.0)) == []

    def test_a_trail_too_far_from_the_route_cannot_be_joined(self) -> None:
        assert seek(line(0.01, 0.09, north_m=ts.JOIN_M + 20)) == []

    def test_a_trail_too_short_to_replace_much_is_left(self) -> None:
        short = line(0.04, 0.0445, north_m=150.0)
        assert 0.0045 * KX < ts.MIN_REPLACED_M
        assert seek(short, spans=[(3000.0, 6000.0, 3.0)], rate=1000.0) == []

    def test_a_little_exposure_is_not_worth_a_detour(self, monkeypatch) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        assert seek(trail, spans=[(4000.0, 4500.0, 1.0)], rate=1000.0)
        assert seek(trail, spans=[(4000.0, 4000.0 + ts.MIN_EXPOSURE_M - 1, 1.0)], rate=1000.0) == []

    def test_a_trail_shorter_than_the_stretch_it_replaces_adds_no_detour(self) -> None:
        # The route bulges 2 km south; a straight trail joins its two ends.
        bulge = [
            START,
            (START[0] + 0.03, START[1] - 2000 / KY),
            (START[0] + 0.07, START[1] - 2000 / KY),
            END,
        ]
        trail = line(0.002, 0.098, north_m=0.0)
        (c,) = seek(trail, spans=[(0.0, 1e5, 1.0)], route=bulge, traced=1e5)
        assert c.detour_m == 0.0
        assert c.score > 10.0 * c.gain_m

    def test_a_trail_behind_the_start_or_past_the_end_is_not_a_corridor(self) -> None:
        assert seek(line(-0.12, -0.04, north_m=150.0)) == []

    def test_a_span_with_no_room_has_none(self) -> None:
        end = (START[0] + 0.02, START[1])
        assert 0.02 * KX < ts.SEEK_MIN_SPAN_M
        assert seek(line(0.002, 0.018, north_m=100.0), end=end, spans=[(0.0, 1700.0, 1.0)]) == []

    def test_no_route_no_corridors(self) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        assert ts.find_corridors(trail, START, END, [START], [(0.0, 1.0, 1.0)], 1.0, 10.0) == []

    def test_a_detour_over_the_cap_is_not_proposed(self, monkeypatch) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        assert seek(trail)
        monkeypatch.setattr(ts, "DETOUR_CAP_MIN_M", 5.0)
        monkeypatch.setattr(ts, "DETOUR_CAP_SPAN", 0.0)
        assert seek(trail) == []

    def test_the_cap_is_a_floor_or_a_share_of_the_span(self) -> None:
        assert ts.detour_cap_m(1000.0) == ts.DETOUR_CAP_MIN_M
        assert ts.detour_cap_m(20_000.0) == 20_000.0 * ts.DETOUR_CAP_SPAN

    def test_a_trail_that_wanders_scores_less_than_a_straight_one(self) -> None:
        (straight,) = seek(line(0.01, 0.09, north_m=150.0))
        # The same ends by way of a loop 1 km north (a long way round).
        up = [(START[0] + 0.03, START[1] + 150 / KY + i * 0.001) for i in range(10)]
        across = [(up[-1][0] + i * 0.0035, up[-1][1]) for i in range(10)]
        down = [(across[-1][0], across[-1][1] - i * 0.001) for i in range(10)]
        path = [[a, b] for ch in (up, across, down) for a, b in zip(ch, ch[1:], strict=False)]
        (loop,) = seek(path)
        assert loop.score < straight.score and loop.detour_m > straight.detour_m

    def test_the_best_corridor_comes_first(self) -> None:
        near = line(0.01, 0.09, north_m=100.0)
        shorter = line(0.03, 0.06, north_m=-150.0)
        found = seek(near + shorter)
        assert len(found) == 2 and found[0].score > found[1].score

    def test_the_networks_searched_are_the_longest(self, monkeypatch) -> None:
        monkeypatch.setattr(ts, "MAX_NETWORKS", 1)
        found = seek(line(0.01, 0.09, north_m=150.0) + line(0.03, 0.06, north_m=-150.0))
        assert len(found) == 1 and found[0].trail_m > 0.05 * KX

    def test_no_segments_no_corridors(self) -> None:
        assert seek([]) == []

    def test_a_corridor_must_clear_the_exposure_and_the_score(self, monkeypatch) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        monkeypatch.setattr(ts, "MIN_EXPOSURE_M", 1e6)
        assert seek(trail) == []
        monkeypatch.setattr(ts, "MIN_EXPOSURE_M", 1.0)
        monkeypatch.setattr(ts, "MIN_SCORE_M", 1e9)
        assert seek(trail) == []

    def test_a_corridor_must_replace_enough_of_the_route(self, monkeypatch) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        monkeypatch.setattr(ts, "MIN_REPLACED_M", 1e6)
        assert seek(trail) == []

    def test_a_short_network_is_not_a_corridor(self) -> None:
        assert seek(line(0.04, 0.0425, north_m=150.0)) == []


class TestProposals:
    def test_nothing_found_asks_for_nothing(self) -> None:
        assert ts.propose([]) == []

    def test_one_corridor_is_proposed_alone(self) -> None:
        a = corridor()
        assert ts.propose([a]) == [ts.Proposal((a,))]

    def test_two_beside_each_other_are_proposed_together_then_the_best_alone(self) -> None:
        a = corridor(score=900.0, t_in=0.0, t_out=3000.0)
        b = corridor(score=800.0, t_in=4000.0, t_out=7000.0)
        # Ridden in order whichever scores more.
        for first, second in ((a, b), (b, a)):
            got = ts.propose([first, second])
            assert [p.corridors for p in got] == [(a, b), (first,)]

    def test_a_different_trail_over_the_same_stretch_is_the_third(self) -> None:
        a = corridor(score=900.0, t_in=0.0, t_out=5000.0)
        b = corridor(score=800.0, t_in=1000.0, t_out=4000.0)
        c = corridor(score=700.0, t_in=6000.0, t_out=8000.0)
        got = ts.propose([a, b, c])
        assert [p.corridors for p in got] == [(a, c), (a,), (b,)]

    def test_no_more_than_the_limit(self) -> None:
        a = corridor(score=900.0, t_in=0.0, t_out=5000.0)
        b = corridor(score=800.0, t_in=1000.0, t_out=4000.0)
        c = corridor(score=700.0, t_in=6000.0, t_out=8000.0)
        assert len(ts.propose([a, b, c], limit=2)) == 2
        assert len(ts.propose([a, b, c])) == ts.SEEK_MAX_CANDIDATES

    def test_corridors_must_be_a_gap_apart_to_be_ridden_in_order(self) -> None:
        a = corridor(t_in=0.0, t_out=3000.0)
        assert not ts.overlaps(a, corridor(t_in=3000.0 + ts.ORDER_GAP_M, t_out=5000.0))
        assert ts.overlaps(a, corridor(t_in=3000.0 + ts.ORDER_GAP_M - 1, t_out=5000.0))
        # And on the other side.
        b = corridor(t_in=5000.0, t_out=7000.0)
        assert not ts.overlaps(b, corridor(t_in=0.0, t_out=5000.0 - ts.ORDER_GAP_M))
        assert ts.overlaps(b, corridor(t_in=0.0, t_out=5000.0 - ts.ORDER_GAP_M + 1))

    def test_a_proposal_adds_up_its_corridors(self) -> None:
        a = corridor(gain_m=100.0, detour_m=10.0)
        b = corridor(gain_m=200.0, detour_m=20.0)
        p = ts.Proposal((a, b))
        assert p.gain_m == 300.0 and p.detour_m == 30.0


class TestViaPoints:
    def trail(self, metres_long: float) -> ts.Corridor:
        n = int(metres_long // 50)
        path = tuple((START[0] + i * 50 / KX, START[1]) for i in range(n + 1))
        return corridor(entry=path[0], exit=path[-1], trail_m=n * 50.0, path=path)

    def test_the_points_are_a_little_way_along_the_trail_from_each_end(self) -> None:
        c = self.trail(2000.0)
        entry, leave = ts.via_points(c)
        assert metres(entry, c.entry) == pytest.approx(ts.VIA_INSET_M, abs=0.5)
        assert metres(leave, c.exit) == pytest.approx(ts.VIA_INSET_M, abs=0.5)
        # Inside the trail, in the order ridden.
        assert entry[0] > c.entry[0] and leave[0] < c.exit[0]

    def test_a_trail_too_short_to_inset_is_asked_for_by_its_ends(self) -> None:
        c = self.trail(3 * ts.VIA_INSET_M)
        assert ts.via_points(c) == [c.entry, c.exit]
        no_path = corridor(trail_m=5000.0)
        assert ts.via_points(no_path) == [no_path.entry, no_path.exit]

    def test_the_inset_follows_the_bends(self) -> None:
        path = (
            (START[0], START[1]),
            (START[0], START[1] + 100 / KY),
            (START[0] + 100 / KX, START[1] + 100 / KY),
        )
        c = corridor(entry=path[0], exit=path[-1], trail_m=200.0, path=path)
        entry, _leave = ts.via_points(c)
        assert entry == pytest.approx((START[0], START[1] + ts.VIA_INSET_M / KY))
        far = ts.Corridor(
            **{**c.__dict__, "path": ((START[0], START[1]),) + path[1:], "trail_m": 200.0}
        )
        assert ts.via_points(far)[1][1] == pytest.approx(START[1] + 100 / KY)

    def test_an_inset_that_runs_round_a_bend_is_measured_along_the_trail(self) -> None:
        path = (
            (START[0], START[1]),
            (START[0], START[1] + 10 / KY),
            (START[0] + 200 / KX, START[1] + 10 / KY),
        )
        c = corridor(entry=path[0], exit=path[-1], trail_m=210.0, path=path)
        entry, _leave = ts.via_points(c)
        # 10 m north, then 15 m east.
        assert entry == pytest.approx((START[0] + 15 / KX, START[1] + 10 / KY))

    def test_a_proposals_vias_are_in_order(self) -> None:
        a, b = self.trail(2000.0), self.trail(2000.0)
        assert len(ts.Proposal((a, b)).vias) == 4


class TestTheBand:
    def test_the_width_is_a_share_of_the_span_between_limits(self) -> None:
        assert ts.band_m(1000.0) == ts.BAND_MIN_M
        assert ts.band_m(100_000.0) == ts.BAND_MAX_M
        assert ts.band_m(20_000.0) == pytest.approx(20_000.0 * ts.BAND_FRACTION)

    def test_a_segment_beside_the_line_or_the_route_is_kept_and_the_rest_dropped(self) -> None:
        near_line = line(0.02, 0.03, north_m=500.0)
        far = line(0.02, 0.03, north_m=5000.0)
        route = [(START[0] + 0.05, START[1] + 4000 / KY), (START[0] + 0.06, START[1] + 4000 / KY)]
        by_route = line(0.05, 0.06, north_m=4200.0)
        behind = line(-0.1, -0.08, north_m=0.0)
        kept = ts.in_band(near_line + far + by_route + behind, START, END, route, 1500.0)
        assert kept == near_line + by_route

    def test_a_segment_past_the_end_is_dropped(self) -> None:
        past = [[(END[0] + 0.01, END[1]), (END[0] + 0.012, END[1])]]
        stub = [START, (START[0] + 0.001, START[1])]
        assert ts.in_band(past, START, END, stub, 1500.0) == []

    def test_a_segment_with_one_vertex_in_the_band_is_kept(self) -> None:
        crossing = [
            [(START[0] + 0.05, START[1] + 100 / KY), (START[0] + 0.05, START[1] + 9000 / KY)]
        ]
        assert ts.in_band(crossing, START, END, [START, END], 1500.0) == crossing


@pytest.mark.django_db(transaction=True)
class TestTheQuery:
    """`corridor_segments` against a scratch segment table: the map's own trail
    rule, LTS 1 and 2 only."""

    def add(self, cursor, schema, way, wkt, **kw) -> None:
        row = {
            "tier": 1,
            "rule": "x",
            "trail": False,
            "facility": "none",
            "car_free": "{}",
            "unpaved": None,
        }
        row.update(kw)
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, facility, car_free_when, is_unpaved) "
            "VALUES (%s, 0, ST_GeomFromText(%s, 4326), %s, %s, %s, %s, %s::text[], %s)",
            [
                way,
                wkt,
                row["tier"],
                row["rule"],
                row["trail"],
                row["facility"],
                row["car_free"],
                row["unpaved"],
            ],
        )

    def wkt(self, north_m: float, lon0: float = 0.02, lon1: float = 0.03) -> str:
        lat = START[1] + north_m / KY
        return f"LINESTRING({START[0] + lon0} {lat}, {START[0] + lon1} {lat})"

    @pytest.fixture
    def table(self, segment_schemas):
        from django.db import connection

        live = segment_schemas[0]
        with connection.cursor() as cursor:
            self.add(
                cursor,
                live,
                1,
                self.wkt(100),
                facility="path",
                trail=True,
                rule=sorted(PATH_RULES)[0],
            )
            self.add(cursor, live, 2, self.wkt(200), facility="protected", tier=2)
            self.add(cursor, live, 3, self.wkt(300), facility="none", trail=True)  # a sidewalk
            self.add(cursor, live, 4, self.wkt(400), facility="protected", tier=3)  # too busy
            self.add(cursor, live, 5, self.wkt(500), facility="lane", tier=2)  # paint
            self.add(cursor, live, 6, self.wkt(600), facility="none", tier=4, car_free="{weekend}")
            self.add(
                cursor,
                live,
                7,
                self.wkt(700),
                facility="path",
                trail=True,
                unpaved=True,
                rule="gravel",
            )
            self.add(cursor, live, 8, self.wkt(4000), facility="path", trail=True)  # far away
        return live

    def guide(self):
        return [[START, END]]

    def north_of(self, got) -> list[int]:
        return sorted(round((seg[0][1] - START[1]) * KY) for seg in got)

    def test_paths_and_protected_ways_at_lts_1_and_2_are_corridors(self, table) -> None:
        got = ts.corridor_segments(table, self.guide(), 1500.0, True, "weekday_offpeak")
        assert self.north_of(got) == [100, 200, 700]

    def test_a_road_closed_to_cars_at_this_ride_time_is_a_path(self, table) -> None:
        got = ts.corridor_segments(table, self.guide(), 1500.0, True, "weekend")
        assert self.north_of(got) == [100, 200, 600, 700]

    def test_avoiding_gravel_leaves_the_unpaved_out(self, table) -> None:
        got = ts.corridor_segments(table, self.guide(), 1500.0, True, "weekday_offpeak", True)
        assert self.north_of(got) == [100, 200]

    def test_without_the_facility_column_the_trail_rule_says(self, table) -> None:
        got = ts.corridor_segments(table, self.guide(), 1500.0, False, "weekday_offpeak")
        # Only the way whose recorded rule is a path's.
        assert self.north_of(got) == [100]

    def test_the_vertices_come_back_as_lon_lat(self, table) -> None:
        got = ts.corridor_segments(table, self.guide(), 1500.0, True, "weekday_offpeak")
        assert got[0][0][0] == pytest.approx(START[0] + 0.02)

    def test_the_route_is_a_guide_too(self, table) -> None:
        detour = [(START[0] + 0.02, START[1] + 3900 / KY), (START[0] + 0.03, START[1] + 3900 / KY)]
        got = ts.corridor_segments(table, [[START, END], detour], 500.0, True, "weekday_offpeak")
        assert 4000 in self.north_of(got)

    def test_no_guide_no_segments(self, table) -> None:
        assert ts.corridor_segments(table, [], 1500.0, True, "weekend") == []

    def test_the_most_segments_is_the_limit(self, table, monkeypatch) -> None:
        monkeypatch.setattr(ts, "MAX_SEGMENTS", 1)
        assert len(ts.corridor_segments(table, self.guide(), 1500.0, True, "weekend")) == 1


class TestWhenItRuns:
    def test_from_the_old_top_of_the_slider(self) -> None:
        assert ts.seek_for(ts.SEEK_FROM_RATE)
        assert not ts.seek_for(ts.SEEK_FROM_RATE - 0.001)
        assert ts.SEEK_FROM_RATE == 10.0

    def test_the_budget_is_six_seconds_over_the_search(self) -> None:
        assert ts.SEEK_BUDGET_S == 6
        assert ts.SEEK_MAX_CANDIDATES == 3


def credit_seek(segments, credit=0.5, spans=(), trail=(), rate=10.0, route=None):
    return ts.find_corridors(
        segments, START, END, route or route_xy(), spans, LENGTH, rate, credit, trail
    )


class TestTheTrailCredit:
    """OWNER-DECISIONS 202, "Trail bonus for Trailmaxxing only": a metre of trail
    is worth the credit in metres of detour, so a route with nothing busy on it
    still finds a trail."""

    def test_the_route_counts_its_own_trail_in_metres_along(self) -> None:
        line_ = ts.RouteLine(
            [(0.0, 0.0), (5000.0, 0.0), (10_000.0, 0.0)],
            [],
            None,
            trail_spans=[(1000.0, 2000.0, 1.0), (3000.0, 4000.0, 1.0)],
        )
        assert line_.trail_to(500.0) == 0.0
        assert line_.trail_to(1500.0) == pytest.approx(500.0)
        assert line_.trail_to(2500.0) == pytest.approx(1000.0)
        assert line_.trail_to(3500.0) == pytest.approx(1500.0)
        assert line_.trail_to(9000.0) == pytest.approx(2000.0)
        # Busy road and trail are counted apart.
        assert line_.busy_to(9000.0) == 0.0

    def test_the_trail_is_scaled_to_the_lines_length_like_the_busy_road(self) -> None:
        scaled = ts.RouteLine(
            [(0.0, 0.0), (10_000.0, 0.0)], [], 20_000.0, trail_spans=[(2000.0, 4000.0, 1.0)]
        )
        assert scaled.trail_to(5000.0) == pytest.approx(1000.0)

    def test_overlapping_and_empty_trail_spans_are_not_counted_twice(self) -> None:
        line_ = ts.RouteLine(
            [(0.0, 0.0), (10_000.0, 0.0)],
            [],
            None,
            trail_spans=[(1000.0, 3000.0, 1.0), (2000.0, 4000.0, 1.0), (5000.0, 5000.0, 1.0)],
        )
        assert line_.trail_to(10_000.0) == pytest.approx(3000.0)
        assert (
            ts.RouteLine([(0.0, 0.0), (1.0, 0.0)], [], None, trail_spans=[(0, 1, 0.0)]).t_starts
            == []
        )

    def test_a_route_with_nothing_busy_finds_a_trail_only_with_a_credit(self) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        assert credit_seek(trail, credit=0.0) == []
        (c,) = credit_seek(trail, credit=0.5)
        assert c.gain_m == 0.0
        assert c.trail_gain_m == pytest.approx(c.trail_m) and c.trail_m > 0.07 * KX
        # What the corridor is worth is the credit on its trail less the detour it adds.
        assert c.score == pytest.approx(0.5 * c.trail_m - c.detour_m)

    def test_a_bigger_credit_is_worth_more(self) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        scores = [credit_seek(trail, credit=credit)[0].score for credit in (0.25, 0.5, 0.75)]
        assert scores == sorted(scores) and len(set(scores)) == 3

    def test_a_trail_the_route_already_rides_is_not_a_gain(self) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        assert credit_seek(trail, trail=[(0.0, LENGTH, 1.0)]) == []

    def test_the_gain_is_net_of_the_trail_the_corridor_replaces(self) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        (c,) = credit_seek(trail, trail=[(0.0, 3000.0, 1.0)])
        replaced = max(0.0, min(c.t_out, 3000.0) - c.t_in)
        assert replaced > 0
        assert c.trail_gain_m == pytest.approx(c.trail_m - replaced, abs=2.0)
        # The score pays for the trail it adds and loses the trail it replaces.
        assert c.score == pytest.approx(0.5 * c.trail_m - c.detour_m - 0.5 * replaced, abs=2.0)

    def test_a_corridor_without_busy_road_must_add_enough_trail(self, monkeypatch) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        assert credit_seek(trail)
        monkeypatch.setattr(ts, "MIN_TRAIL_GAIN_M", 1e6)
        assert credit_seek(trail) == []
        # Busy road replaced is its own reason: it needs no trail gain.
        assert credit_seek(trail, spans=[(3000.0, 6000.0, 1.0)])

    def test_a_corridor_must_still_clear_the_score(self, monkeypatch) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        monkeypatch.setattr(ts, "MIN_SCORE_M", 1e9)
        assert credit_seek(trail) == []

    def test_a_credit_leaves_the_busy_road_corridors_as_they_were(self) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        busy = [(3000.0, 6000.0, 1.0)]
        assert credit_seek(trail, credit=0.0, spans=busy) == seek(trail, spans=busy)
        (plain,) = credit_seek(trail, credit=0.0, spans=busy)
        (credited,) = credit_seek(trail, credit=0.5, spans=busy)
        assert credited.gain_m == plain.gain_m and credited.score > plain.score

    def test_the_credit_is_held_under_the_detours_weight(self) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        assert credit_seek(trail, credit=7.0) == credit_seek(trail, credit=0.95)
        assert credit_seek(trail, credit=-1.0) == credit_seek(trail, credit=0.0) == []
        busy = [(3000.0, 6000.0, 1.0)]
        assert credit_seek(trail, credit=-1.0, spans=busy) == credit_seek(
            trail, credit=0.0, spans=busy
        )
        assert 0.95 < 1.0 and ts.DETOUR_WEIGHT == 1.0

    def test_the_detour_cap_still_holds(self, monkeypatch) -> None:
        trail = line(0.01, 0.09, north_m=150.0)
        monkeypatch.setattr(ts, "DETOUR_CAP_MIN_M", 5.0)
        monkeypatch.setattr(ts, "DETOUR_CAP_SPAN", 0.0)
        assert credit_seek(trail) == []
