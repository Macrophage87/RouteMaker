"""Audit S19: a plan reads each trace once (`routing.trace_reading`, `_reading_memo`): the
shape decoded once, cut into pieces once, its junctions and edge middles found once at the
leg's start and shifted for each caller, exactly as a reading at that offset gives them."""

from __future__ import annotations

import contextvars
import gc
import math
import tracemalloc

import pytest

from core import routing
from routemaker import trace_junctions


def encode(points) -> str:
    """Valhalla's precision-6 polyline of (lon, lat) points."""
    out = []
    last_lat = last_lon = 0
    for lon, lat in points:
        lat6, lon6 = round(lat * 1e6), round(lon * 1e6)
        for delta in (lat6 - last_lat, lon6 - last_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last_lat, last_lon = lat6, lon6
    return "".join(out)


def long_trace(vertices: int = 6000, per_edge: int = 5, seed: float = 0.0) -> dict:
    """A trace of about 30 km (6,000 vertices about 5 m apart, an edge every 5): the size
    of a long leg's, with a cross road at every other node and a hairpin now and then."""
    points = []
    lon, lat = -77.0, 38.9
    for i in range(vertices):
        lon += 0.00005 * math.cos(i / 50.0 + seed)
        lat += 0.00003 * math.sin(i / 70.0 + seed)
        points.append((round(lon, 6), round(lat, 6)))
    edges = []
    for k, begin in enumerate(range(0, vertices - 1, per_edge)):
        end = min(begin + per_edge, vertices - 1)
        edges.append(
            {
                "id": 1000 + k,
                "way_id": 100 + k // 3,
                "length": 0.0051 * (end - begin),
                "begin_shape_index": begin,
                "end_shape_index": end,
                "names": [f"Road {k // 3}"],
                "use": "road",
                "road_class": "residential",
                "begin_heading": (k * 7) % 360,
                "end_heading": (k * 7 + 3) % 360,
                "traffic_signal": k % 17 == 0,
                "end_node": {
                    "intersecting_edges": [
                        {
                            "begin_heading": (k * 11) % 360,
                            "use": "road",
                            "road_class": "tertiary",
                            "driveability": "both",
                        }
                    ]
                    if k % 2 == 0
                    else []
                },
            }
        )
    return {"shape": encode(points), "units": "kilometers", "edges": edges}


def in_a_plan(fn):
    """`fn()` with a plan's reading memo, as `routing.plan` sets it."""

    def run():
        routing._reading_memo.set({})
        return fn()

    return contextvars.copy_context().run(run)


def counted(monkeypatch) -> dict:
    calls = {"pieces": 0, "edges": 0, "decode": 0}
    real_pieces, real_edges = routing.pieces_of_trace, trace_junctions.read_edges
    real_decode = routing.decode_polyline6

    def pieces(trace, shape=None):
        calls["pieces"] += 1
        return real_pieces(trace, shape)

    def edges(*args, **kwargs):
        calls["edges"] += 1
        return real_edges(*args, **kwargs)

    def decode(encoded):
        calls["decode"] += 1
        return real_decode(encoded)

    monkeypatch.setattr(routing, "pieces_of_trace", pieces)
    monkeypatch.setattr(trace_junctions, "read_edges", edges)
    monkeypatch.setattr(routing, "decode_polyline6", decode)
    return calls


def old_marks(trace: dict, offset: float) -> list:
    """`edge_midpoints` as v0.13.0 read it: each edge's middle, its metres added up from
    `offset` edge by edge."""
    shape = routing.decode_polyline6(trace["shape"])
    marks, along = [], offset
    for edge in trace["edges"]:
        length = float(edge.get("length") or 0.0) * 1000.0
        point = trace_junctions.midpoint_along(
            shape, edge["begin_shape_index"], edge["end_shape_index"]
        )
        if point is not None and length > 0:
            marks.append((along + length / 2, point[0], point[1], length))
        along += length
    return marks


def old_junction_m(trace: dict, offset: float) -> list:
    """The metres along of every edge's far node as v0.13.0 added them up from `offset`."""
    out, along = [], offset
    for edge in trace["edges"][:-1]:
        along += float(edge.get("length") or 0.0) * 1000.0
        out.append(along)
    return out


@pytest.mark.parametrize("offset", [0.0, 1234.5678, 0.1])
def test_a_reading_shifted_is_exactly_the_reading_at_that_offset(offset) -> None:
    trace = long_trace()
    shape = routing.decode_polyline6(trace["shape"])
    pieces, read = routing.trace_reading(trace, shape, marks=True)
    assert pieces == routing.pieces_of_trace(trace)
    raws = trace_junctions.junctions_along(read, offset)
    assert raws and raws == trace_junctions.junctions_of_trace(trace, shape, offset)
    # Bit for bit the metres the old reading added up, and each approach its edge's middle.
    ms = old_junction_m(trace, offset)
    for (index, _raw), shifted in zip(read.junctions, raws, strict=True):
        assert shifted.m == ms[index]
        edge = trace["edges"][index]
        assert shifted.approach == trace_junctions.midpoint_along(
            shape, edge["begin_shape_index"], edge["end_shape_index"]
        )
    marks = trace_junctions.marks_along(read, offset)
    assert marks == old_marks(trace, offset) == trace_junctions.edge_midpoints(trace, shape, offset)


def test_a_trace_is_read_once_a_plan_and_each_caller_gets_its_own_lists(monkeypatch) -> None:
    trace = long_trace(600)
    shape = routing.decode_polyline6(trace["shape"])
    calls = counted(monkeypatch)

    def readers():
        # The hill guards' exposure (pieces only), the calm search's reading (pieces, junctions
        # and middles) and the answer (pieces and junctions), at different offsets.
        exposure, _ = routing.trace_reading(trace)
        analysed, read = routing.trace_reading(trace, shape, marks=True)
        answered, again = routing.trace_reading(trace, shape, edges=True)
        return exposure, analysed, answered, read, again

    exposure, analysed, answered, read, again = in_a_plan(readers)
    assert calls["pieces"] == 1
    # Read again once for its junctions and middles, both from the one decode.
    assert calls["edges"] == 1 and calls["decode"] == 2
    assert again is read
    assert exposure == analysed == answered
    assert exposure is not analysed and analysed is not answered
    exposure.append("extended")
    assert routing.trace_reading(trace)[0] == routing.pieces_of_trace(trace)


def test_outside_a_plan_nothing_is_remembered(monkeypatch) -> None:
    trace = long_trace(200)
    calls = counted(monkeypatch)
    routing.trace_reading(trace)
    routing.trace_reading(trace)
    assert calls["pieces"] == 2 and routing._reading_memo.get() is None


def test_another_trace_with_the_same_id_is_not_taken_for_it(monkeypatch) -> None:
    first, second = long_trace(200), long_trace(200, seed=1.0)

    def readers():
        routing.trace_reading(first)
        memo = routing._reading_memo.get()
        # As if `first` were gone and `second` given its id.
        memo[id(second)] = memo.pop(id(first))
        return routing.trace_reading(second)[0]

    assert in_a_plan(readers) == routing.pieces_of_trace(second)


def test_a_reading_from_the_legs_shape_is_not_kept() -> None:
    """A trace with no shape of its own reads its junctions on the leg's (`trace_shape`):
    that reading is the leg's, so it is never kept for the trace."""
    trace = long_trace(200)
    shape = routing.decode_polyline6(trace.pop("shape"))

    def readers():
        _pieces, read = routing.trace_reading(trace, shape, edges=True)
        entry = routing._reading_memo.get()[id(trace)]
        return read, entry.edges

    read, kept = in_a_plan(readers)
    assert read.junctions and kept is None
    assert trace_junctions.junctions_along(read) == trace_junctions.junctions_of_trace(trace, shape)


def test_the_memo_is_capped_by_pieces_and_cleared_as_the_plan_ends(monkeypatch) -> None:
    traces = [long_trace(2000, seed=float(i)) for i in range(8)]
    seen = []

    def rounds(*args):
        for trace in traces:
            routing.trace_reading(trace)
        memo = routing._reading_memo.get()
        seen.append((memo, sum(len(e.pieces) for e in memo.values()), list(memo)))
        return {"ok": True}

    monkeypatch.setattr(routing, "_plan_rounds", rounds)
    assert routing.plan([[-77.0, 38.9], [-77.01, 38.9]], "default") == {"ok": True}
    ((memo, held, kept),) = seen
    assert held <= routing.READING_MEMO_PIECES
    assert kept[-1] == id(traces[-1]), "the most recent kept"
    assert memo == {} and routing._reading_memo.get() is None


def test_the_memo_holds_little_beside_the_plans_own_analyses(capsys) -> None:
    """Peak memory (tracemalloc) of a long plan's readings, with the memo and without: six
    30 km candidates read by the hill guards, the calm search and the answer, each analysis
    keeping its pieces and middles for the plan's life as `refine.Context.analyses` does."""
    traces = [long_trace(seed=float(i)) for i in range(6)]
    shapes = [routing.decode_polyline6(t["shape"]) for t in traces]

    def plan_like():
        kept = []
        for trace in traces[:2]:  # calmer_or_own: the router's own and the alternative
            routing.trace_reading(trace)
        for trace, shape in zip(traces, shapes, strict=True):  # the calm search
            pieces, read = routing.trace_reading(trace, shape, marks=True)
            junctions = trace_junctions.junctions_along(read, 0.0)
            kept.append((pieces, trace_junctions.marks_along(read, 0.0), len(junctions)))
        pieces, read = routing.trace_reading(traces[1], shapes[1], edges=True)  # the answer
        answer = (pieces, trace_junctions.junctions_along(read, 0.0))
        return kept, answer

    def peak(memo: bool) -> tuple[int, int]:
        gc.collect()
        tracemalloc.start()
        try:
            if memo:
                result = in_a_plan(plan_like)
            else:
                result = plan_like()
            current, top = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        del result
        return current, top

    without_now, without_peak = peak(False)
    with_now, with_peak = peak(True)
    with capsys.disabled():
        print(
            f"\nreading memo, 6 x 30 km candidates: peak {with_peak / 2**20:.1f} MiB with, "
            f"{without_peak / 2**20:.1f} MiB without; held at the end {with_now / 2**20:.1f} "
            f"MiB with, {without_now / 2**20:.1f} MiB without"
        )
    # The answer shares the analysed pieces rather than cutting its own: no more at the peak
    # than a megabyte or two over the reading without, and well under the worker's headroom.
    assert with_peak <= without_peak + 2 * 2**20
