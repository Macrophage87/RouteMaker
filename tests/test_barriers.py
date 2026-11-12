"""Barriers on a route, and Cargo and Tandem planned round the impassable ones (core.barriers).

Backlog 2026-11-12 item 12; OWNER-DECISIONS 345 ("Only impassable ones": stiles, turnstiles,
kissing gates and gaps under 1.0 m). Made-up barriers on a made-up trail, never OSM data.
"""

from __future__ import annotations

import pytest

from core import barriers, routing
from core.dedodge import encode_polyline6

LON = -77.0
DEG_M = 111_195.0


def north(metres: float, lat: float = 38.9) -> float:
    return lat + metres / DEG_M


def east(metres: float, lat: float = 38.9) -> float:
    import math

    return LON + metres / (DEG_M * math.cos(math.radians(lat)))


# A north-running trail from 38.9: a stile at 10 m, a 1.2 m bollard at 20 m, an unmapped
# bollard at 30 m, a 0.9 m bollard at 40 m; each excluded 4 m further north on the trail.
TRAIL = [(LON, north(m)) for m in range(0, 60, 10)]
# A trail's bollard on the node it shares with an east-west road at 38.95, its way to the north.
JUNCTION = (LON, 38.95)
# A flight of steps from (east 200 m, 38.9) 20 m north.
STEPS = [(east(200), north(0)), (east(200), north(10)), (east(200), north(20))]


def data() -> dict:
    def row(m: float, kind: str, width: float | None) -> list:
        return [LON, north(m), kind, width, [[LON, north(m + 4)]]]

    return {
        "built": "2026-11-12",
        "barriers": [
            row(10, "stile", None),
            row(20, "bollard", 1.2),
            row(30, "bollard", None),
            row(40, "bollard", 0.9),
            [JUNCTION[0], JUNCTION[1], "bollard", None, [[LON, north(4, 38.95)]]],
        ],
        "steps": [[list(p) for p in STEPS]],
    }


INDEX = barriers.index_of(data())


def test_a_route_along_the_trail_names_each_barrier_in_order() -> None:
    reading = barriers.reading(TRAIL, INDEX)
    assert reading["data"] is True
    assert [i["word"] for i in reading["items"]] == [
        "stile", "bollard", "bollard", "narrow_gap",
    ]  # fmt: skip
    assert reading["counts"] == {"stile": 1, "bollard": 2, "narrow_gap": 1}
    assert reading["impassable"] == 2
    assert reading["unmapped_width"] == 1
    assert [i["width_mapped"] for i in reading["items"]] == [True, True, False, True]
    assert [i["at_m"] for i in reading["items"]] == pytest.approx([10, 20, 30, 40], abs=0.5)


def test_impassable_is_the_owners_list() -> None:
    def make(kind: str, width: float | None = None) -> barriers.Barrier:
        return barriers.Barrier(kind, LON, 38.9, width, ())

    assert barriers.impassable(make("stile"))
    assert barriers.impassable(make("kissing_gate"))
    assert barriers.impassable(make("turnstile"))
    assert barriers.impassable(make("steps"))
    assert barriers.impassable(make("bollard", 0.99))
    assert not barriers.impassable(make("bollard", 1.0))
    # An unmapped width is named as unmapped, never called clear or impassable.
    assert not barriers.impassable(make("bollard"))
    assert not barriers.impassable(make("cycle_barrier"))
    assert not barriers.impassable(make("gate"))


def test_a_road_past_a_trail_end_does_not_cross_its_bollard() -> None:
    road = [(east(-50, 38.95), 38.95), JUNCTION, (east(50, 38.95), 38.95)]
    assert barriers.reading(road, INDEX)["items"] == []
    into_the_trail = [(east(-50, 38.95), 38.95), JUNCTION, (LON, north(30, 38.95))]
    assert [i["word"] for i in barriers.reading(into_the_trail, INDEX)["items"]] == ["bollard"]


def test_steps_are_crossed_only_when_ridden_along() -> None:
    up = [(east(200), north(-20)), *STEPS, (east(200), north(40))]
    assert [i["word"] for i in barriers.reading(up, INDEX)["items"]] == ["steps"]
    across = [(east(180), north(10)), STEPS[1], (east(220), north(10))]
    assert barriers.reading(across, INDEX)["items"] == []


def test_no_snapshot_is_not_no_barriers() -> None:
    empty = barriers.index_of({})
    assert barriers.reading(TRAIL, empty) == {
        "data": False, "counts": {}, "impassable": 0, "unmapped_width": 0, "items": [],
    }  # fmt: skip


def _trip(line) -> dict:
    return {"legs": [{"shape": encode_polyline6(list(line))}]}


ROUND_THE_TRAIL = [(LON, north(0)), (east(30), north(20)), (LON, north(50))]


def test_settle_takes_the_way_round(monkeypatch) -> None:
    asked = []

    def route(variant, request, deadline):
        asked.append(request["exclude_locations"])
        return {"trip": _trip(ROUND_THE_TRAIL)}, False

    monkeypatch.setattr(routing, "_route", route)
    excludes: list = []
    trip, info = barriers.settle(
        _trip(TRAIL), {"locations": [], "alternates": 2}, "standard", None,
        points=[], level_excludes=excludes, index=INDEX,
    )  # fmt: skip
    assert info == {"rounds": 1, "impassable": 0, "limited": None, "in_the_way": []}
    assert trip == _trip(ROUND_THE_TRAIL)
    # The stile's and the narrow bollard's points, and nothing else.
    assert len(asked[0]) == 2
    assert excludes == asked[0]


def test_settle_says_when_there_is_no_way_round(monkeypatch) -> None:
    def refused(variant, request, deadline):
        raise routing.RouterRefused(400, 442, "No path could be found for input")

    monkeypatch.setattr(routing, "_route", refused)
    trip, info = barriers.settle(_trip(TRAIL), {}, "standard", None, points=[], index=INDEX)
    assert info["limited"] == "no_way_round"
    assert info["impassable"] == 2
    assert [b["word"] for b in info["in_the_way"]] == ["stile", "narrow_gap"]


def test_a_barrier_at_the_start_is_named_not_excluded(monkeypatch) -> None:
    monkeypatch.setattr(routing, "_route", lambda *a: pytest.fail("asked the router"))
    start = [[LON, north(5)]]
    near = [(LON, north(5)), (LON, north(10)), (LON, north(15))]
    trip, info = barriers.settle(_trip(near), {}, "standard", None, points=start, index=INDEX)
    assert info["limited"] == "at_stop"
    assert info["rounds"] == 0


def test_no_snapshot_leaves_the_route(monkeypatch) -> None:
    monkeypatch.setattr(routing, "_route", lambda *a: pytest.fail("asked the router"))
    trip = _trip(TRAIL)
    got, info = barriers.settle(trip, {}, "standard", None, [], index=barriers.index_of({}))
    assert got is trip and info["limited"] == "no_data"


def test_the_committed_snapshot_reads() -> None:
    index = barriers.index_of(__import__("json").loads(barriers.BARRIERS_PATH.read_text()))
    assert isinstance(index.barriers, list)


def test_an_answer_cut_short_in_the_barrier_round_is_not_kept() -> None:
    from core import route_cache

    body = {"variant": "standard", "barrier_round": {"limited": "time"}}
    assert not route_cache.keepable(body, "standard", 0)
    body["barrier_round"] = {"limited": "no_way_round"}
    assert route_cache.keepable(body, "standard", 0)


def test_the_answer_schema_carries_both() -> None:
    from core.api import BarrierRoundOut, BarriersOut

    reading = barriers.reading(TRAIL, INDEX)
    assert BarriersOut(**reading).items[0].word == "stile"
    with pytest.raises(ValueError):
        BarrierRoundOut(rounds=1, impassable=1, limited="somehow", in_the_way=[])
