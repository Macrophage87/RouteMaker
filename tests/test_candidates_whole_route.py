"""The routes to choose from are whole routes (combined correctness review, B1).

On a plan with more than one leg (a loop, or a plan with stops) the trail seek asks
the router for one leg at a time. A leg's candidate is one leg of the trip, and it
must never reach the routes to choose from as if it were a whole route: every
candidate has the answer's legs and the answer's ends.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_longcalm_api import segments  # noqa: F401 - the fixture
from test_route_api import LAT, VERTICES, encode_polyline6, good_body, post

from core import presets, refine, routing, trailseek

db = pytest.mark.django_db(transaction=True)
pytestmark = [pytest.mark.usefixtures("weekday_clock"), db]

# The ways of the fixture's road (tests/test_longcalm_api.py, `segments`), by
# vertex; any other vertex is on a way of its own.
WAYS = {0: 101, 1: 202, 2: 202, 3: 303}
EAST = (-76.99, LAT)


def _way_of(point) -> int:
    for i, vertex in enumerate(VERTICES[:-1]):
        if abs(vertex[0] - point[0]) < 1e-6 and abs(vertex[1] - point[1]) < 1e-6:
            return WAYS[i]
    return 900 + int(abs(point[0]) * 1000) % 50 + (0 if point[1] > LAT else 50)


def _line(a, b, n: int = 5) -> list[tuple[float, float]]:
    """`n` vertices from `a` to `b` in a straight line, or the fixture's road
    where that is what `a` to `b` is."""
    if tuple(a) == VERTICES[0] and tuple(b) == VERTICES[-1]:
        return list(VERTICES)
    if tuple(a) == VERTICES[-1] and tuple(b) == VERTICES[0]:
        return list(reversed(VERTICES))
    return [(a[0] + (b[0] - a[0]) * i / (n - 1), a[1] + (b[1] - a[1]) * i / (n - 1)) for i in range(n)]


def _leg(vertices, km: float) -> dict:
    return {
        "shape": encode_polyline6(vertices),
        "summary": {"length": km, "time": 100.0 * km},
        "elevation": [10.0] * 4,
    }


def _trip(*legs) -> dict:
    total = sum(leg["summary"]["length"] for leg in legs)
    return {"trip": {"legs": list(legs), "summary": {"length": total, "time": 100.0 * total}}}


def _router(call_log: list):
    """A router whose seek routes (through a `through` location) are one leg each,
    by a way north of the line going east and south of it going west (so a loop's
    way back is a different way), and whose plain routes follow the plan's legs."""

    def call(url, payload, timeout):
        endpoint = url.rsplit("/", 1)[1]
        call_log.append(endpoint)
        if endpoint == "route":
            locs = [(loc["lon"], loc["lat"]) for loc in payload["locations"]]
            if any(loc.get("type") == "through" for loc in payload["locations"]):
                a, b = locs[0], locs[-1]
                side = LAT + 0.01 if b[0] > a[0] else LAT - 0.01
                way = [a, (a[0] + (b[0] - a[0]) * 0.25, side), (a[0] + (b[0] - a[0]) * 0.75, side), b]
                return _trip(_leg(way, 3.0))
            return _trip(*(_leg(_line(a, b), 2.2) for a, b in zip(locs, locs[1:], strict=False)))
        if endpoint == "trace_attributes":
            shape = routing.decode_polyline6(payload["encoded_polyline"])
            edges = [
                {
                    "way_id": _way_of(shape[i]),
                    "begin_shape_index": i,
                    "end_shape_index": i + 1,
                    "length": 0.5,
                    "names": ["S"],
                }
                for i in range(len(shape) - 1)
            ]
            return {"units": "kilometers", "shape": payload["encoded_polyline"], "edges": edges}
        if endpoint == "locate":
            return [{} for _ in payload["locations"]]
        raise AssertionError(endpoint)

    return call


@pytest.fixture
def seek_everywhere(monkeypatch):
    """The trail seek proposes one corridor on every leg, through a point north of
    the leg's line."""
    monkeypatch.setattr(trailseek, "corridor_segments", lambda *a, **k: [])
    monkeypatch.setattr(trailseek, "in_band", lambda *a, **k: [])
    monkeypatch.setattr(trailseek, "points_in_band", lambda *a, **k: [])
    monkeypatch.setattr(trailseek, "find_corridors", lambda *a, **k: ["c"])
    monkeypatch.setattr(
        trailseek,
        "propose",
        lambda c, *a, **k: [
            SimpleNamespace(
                vias=[(-77.035, LAT + 0.01)], corridors=("c",), gain_m=100.0, detour_m=800.0
            )
        ],
    )


def _assert_whole(body: dict) -> None:
    assert body["leg_ends"], body
    first, last = body["geometry"]["coordinates"][0], body["geometry"]["coordinates"][-1]
    for candidate in body.get("candidates") or []:
        assert len(candidate["leg_ends"]) == len(body["leg_ends"]), candidate["rank"]
        coordinates = candidate["geometry"]["coordinates"]
        assert coordinates[0] == first and coordinates[-1] == last, candidate["rank"]


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"loop": True}, id="loop"),
        pytest.param(
            {"points": [list(VERTICES[0]), list(VERTICES[-1]), list(EAST)]}, id="stops"
        ),
    ],
)
def test_a_multi_leg_plan_offers_only_whole_routes(
    client, segments, monkeypatch, seek_everywhere, extra
) -> None:
    calls: list = []
    monkeypatch.setattr(routing, "_transport", _router(calls))
    body = post(client, {**good_body("trailmaxxing"), "stress": 100, **extra}).json()
    assert len(body["leg_ends"]) == 2
    seek = (body.get("calm_search") or {}).get("seek") or {}
    # The seek ran on the legs (so the per-leg candidates existed to leak).
    assert seek.get("asked", 0) >= 1, body.get("calm_search")
    _assert_whole(body)


def test_pick_candidates_never_takes_a_trip_with_other_legs() -> None:
    from test_longcalm import alt_context, road

    ctx = alt_context(ceiling_m=50_000.0)
    ctx.exposure = presets.exposure_for("trailmaxxing", None)
    _trip_, read = road("answer", list(range(1, 11)), "1111311113")
    read.via_m = [5000.0]
    answer = {"legs": [{"shape": "out"}, {"shape": "back"}], "summary": {"length": 10.0}}
    leg_trip, leg_read = road("leg0-only", [101, 102, 103, 104, 105, 106], "111111")
    assert len(leg_trip["legs"]) == 1
    picked = refine.pick_candidates([(answer, read), (leg_trip, leg_read)], ctx, [0.0, 0.0])
    assert [t for t, _ in picked] == [answer]


def test_a_two_point_plan_still_pools_its_seek_candidates(monkeypatch) -> None:
    """The guard is on the leg count: a plan of one leg keeps its seek candidates
    for the routes to choose from, as before."""
    seen: list = []

    def fake_seek_leg(*args, **kwargs):
        seen.append(kwargs.get("pooled"))
        return None

    monkeypatch.setattr(refine, "_seek_leg", fake_seek_leg)
    from test_longcalm import alt_context, road

    ctx = alt_context(ceiling_m=50_000.0)
    trip, read = road("answer", list(range(1, 11)), "1111311113")
    ctx.points = [[-77.2, LAT], [-77.0, LAT]]
    ctx.request = {"locations": [{"lon": -77.2, "lat": LAT}, {"lon": -77.0, "lat": LAT}]}
    trip = {"legs": [{"shape": "x"}], "summary": {"length": 10.0}}
    refine._seek(read, trip, read.exposure_m, ctx, {})
    assert seen == [True]
