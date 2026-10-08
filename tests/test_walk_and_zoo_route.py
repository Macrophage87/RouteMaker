"""The route's walk-your-bike note and the Zoo destination (OWNER-DECISIONS 291(4), 291(5))."""

from __future__ import annotations

from contextlib import contextmanager

from core import routing
from core.routing import Piece
from routemaker import describe


def atoms(*lengths):
    return [describe.Atom(m, "1", "path", ("Trail",), "path") for m in lengths]


def test_a_walk_entry_is_in_both_descriptions_in_route_order() -> None:
    full, overview = describe.describe_both([atoms(300.0, 100.0, 300.0)], walks=[(300.0, 400.0)])
    for entries in (full, overview):
        kinds = [e["kind"] for e in entries]
        assert "walk" in kinds
        walk = next(e for e in entries if e["kind"] == "walk")
        assert (walk["from_m"], walk["to_m"]) == (300, 400)
        assert "walk your bike here" in walk["text"]
        assert "ft" in walk["text"] and "(100 m)" in walk["text"]


def test_no_walks_no_entry() -> None:
    full, _ = describe.describe_both([atoms(300.0)])
    assert all(e["kind"] != "walk" for e in full)


class FakeCursor:
    def __init__(self, ways):
        self.ways = ways
        self.params = None

    def execute(self, sql, params=None):
        self.params = params

    def fetchall(self):
        return [(w,) for w in self.ways if w in self.params[0]]

    def fetchone(self):
        return (1,)


def piece(way, metres):
    return Piece(way, -77.0, 38.9, metres)


def test_walk_spans_join_neighbouring_pieces_and_end_with_the_route(monkeypatch) -> None:
    cursor = FakeCursor({7, 8})

    @contextmanager
    def fake_cursor():
        yield cursor

    monkeypatch.setattr(routing.connection, "cursor", fake_cursor)
    monkeypatch.setattr(routing, "_walk_column_seen", True)
    pieces = [piece(1, 100), piece(7, 40), piece(8, 60), piece(2, 100), piece(7, 30)]
    spans = routing.walk_spans([(0, 5)], pieces)
    assert spans == [(100.0, 200.0), (300.0, 330.0)]


def test_walk_spans_are_empty_without_the_column(monkeypatch) -> None:
    monkeypatch.setattr(routing, "_walk_column_seen", False)
    monkeypatch.setattr(routing, "_has_walk_column", lambda schema: False)
    assert routing.walk_spans([(0, 1)], [piece(7, 40)]) == []


def test_a_zoo_point_is_moved_to_the_racks_and_says_so() -> None:
    from routemaker import zoo

    points, moved = routing.move_zoo_points([[-77.0495, 38.929], [-77.03, 38.9]])
    assert points[0] == list(zoo.racks()) and points[1] == [-77.03, 38.9]
    assert [m["index"] for m in moved] == [0]
    assert moved[0]["reason"] == "zoo_racks" and "racks" in moved[0]["note"]
    assert routing.move_zoo_points([[-77.03, 38.9]])[1] == []
