"""Winding trails for Group Ride and Fast at plan time (`core.winding_round`, hunt 4 P4-1),
with the router, the route's reading and the segment table faked (and the table read once
against a scratch table).

Asked "Should Group Ride and Fast pay for winding trails the way Road Bike does?", the owner,
2026-11-09: "yes"; and of the round 4 fixes, "Ok. Make sure they are included."
"""

from __future__ import annotations

import pytest
from test_refine import BASE, context

from core import refine, route_cache, routing, winding_round
from routemaker import winding

# The way ids of the trips' pieces: a winding trail, a straight trail and a car-free parkway.
WINDING, STRAIGHT, PARKWAY = 11, 12, 13


def read_of(ways_tiers: list[tuple[int, str]], cost_s: float) -> refine.Analysis:
    """A route read: one 100 m piece per (way, tier), east along BASE's latitude."""
    pieces = [
        routing.Piece(way, BASE[0] + 0.01 + i * 1e-3, BASE[1], 100.0)
        for i, (way, _tier) in enumerate(ways_tiers)
    ]
    classes = [(tier, "path" if tier == "1" else "none") for _way, tier in ways_tiers]
    tiers = [tier for _way, tier in ways_tiers]
    stress = {"3": 1, "4": 2, "5": 3}
    return refine.Analysis(
        length_m=100.0 * len(tiers),
        cost_s=cost_s,
        exposure_m=sum(100.0 * stress.get(t, 0) for t in tiers),
        climb_m=0.0,
        pieces=pieces,
        classes=classes,
        events=[],
        lts4_m=100.0 * sum(t in "45" for t in tiers),
        lts3_m=100.0 * tiers.count("3"),
    )


# The hunt's weekend trip in small: 1.2 km of winding trail beside the car-free parkway the
# router would take for a little more cost.
ON_TRAIL = read_of([(STRAIGHT, "1")] * 4 + [(WINDING, "1")] * 12 + [(STRAIGHT, "1")] * 4, 2000.0)
ON_PARKWAY = read_of([(STRAIGHT, "1")] * 4 + [(PARKWAY, "1")] * 13 + [(STRAIGHT, "1")] * 4, 2060.0)
BUSY = read_of([(STRAIGHT, "1")] * 4 + [(PARKWAY, "4")] * 13 + [(STRAIGHT, "1")] * 4, 2010.0)


def trip(name: str) -> dict:
    return {"legs": [{"shape": name}], "summary": {"length": 2.0}}


class Fake:
    """The router (answers `answer` or raises it) and the readings (by the trip's shape)."""

    def __init__(self, monkeypatch, readings: dict, answer, winding_ways=frozenset({WINDING})):
        self.asked: list[dict] = []
        self.answer = answer
        monkeypatch.setattr(
            refine,
            "analyse",
            lambda trip, ctx, deadline, with_events=True: readings[trip["legs"][0]["shape"]],
        )
        monkeypatch.setattr(routing, "_call", self.call)
        monkeypatch.setattr(
            winding_round,
            "winding_ways",
            lambda schema, ways: {w for w in ways if w in winding_ways},
        )

    def call(self, variant, endpoint, payload, deadline):
        assert endpoint == "route"
        self.asked.append(payload)
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"trip": self.answer}


def ctx_for():
    ctx = context()
    ctx.points = [[BASE[0], BASE[1]], [BASE[0] + 0.05, BASE[1]]]
    return ctx


def test_it_runs_on_group_ride_and_fast_only() -> None:
    assert winding_round.applies("group-ride") and winding_round.applies("fast")
    # Road Bike pays in its own graphs; the rest share the standard graph without the price.
    for name in ("road-bike", "default", "trailmaxxing", "cargo", "mass-ride"):
        assert not winding_round.applies(name)


def test_the_winding_trail_is_read_at_lts_3_and_the_parkway_taken(monkeypatch) -> None:
    fake = Fake(monkeypatch, {"trail": ON_TRAIL, "parkway": ON_PARKWAY}, trip("parkway"))
    ctx = ctx_for()
    # Before the round the trail route scores better: the router's own choice.
    assert ON_TRAIL.score(ctx) < ON_PARKWAY.score(ctx)
    answered, info = winding_round.settle(trip("trail"), ctx)
    assert answered["legs"][0]["shape"] == "parkway"
    assert info == {"winding_m": 0.0, "asked": True, "taken": True, "limited": None}
    # The router was asked once, its own request with points on the winding trail excluded
    # and no alternatives.
    (payload,) = fake.asked
    assert "alternates" not in payload
    excluded = payload["exclude_locations"]
    assert excluded and all(
        BASE[0] + 0.01 + 4e-3 <= x["lon"] <= BASE[0] + 0.01 + 15e-3 for x in excluded
    )
    # And the later ways round keep off them too.
    assert ctx.level_excludes == excluded


def test_the_charge_is_what_lts_3_adds_in_the_routers_cost() -> None:
    ctx = ctx_for()
    assert winding_round.charge_s(1000.0, ctx) == pytest.approx(
        ctx.quiet_cost * refine.lts3_added_m(ctx) * 1000.0
    )
    assert winding_round.priced_score(ON_TRAIL, {WINDING}, ctx) == pytest.approx(
        ON_TRAIL.score(ctx) + winding_round.charge_s(1200.0, ctx)
    )


def test_a_little_winding_trail_asks_nothing(monkeypatch) -> None:
    short = read_of([(STRAIGHT, "1")] * 10 + [(WINDING, "1")] * 3, 2000.0)
    fake = Fake(monkeypatch, {"trail": short}, trip("parkway"))
    answered, info = winding_round.settle(trip("trail"), ctx_for())
    assert answered["legs"][0]["shape"] == "trail" and not fake.asked
    assert info["winding_m"] == 300.0 and info["asked"] is False


def test_a_way_round_onto_a_busy_road_is_refused(monkeypatch) -> None:
    Fake(monkeypatch, {"trail": ON_TRAIL, "busy": BUSY}, trip("busy"))
    answered, info = winding_round.settle(trip("trail"), ctx_for())
    assert answered["legs"][0]["shape"] == "trail"
    assert info["asked"] is True and info["taken"] is False


def test_a_way_round_the_guard_refuses_is_not_taken(monkeypatch) -> None:
    Fake(monkeypatch, {"trail": ON_TRAIL, "parkway": ON_PARKWAY}, trip("parkway"))
    answered, info = winding_round.settle(trip("trail"), ctx_for(), keeps=lambda again: False)
    assert answered["legs"][0]["shape"] == "trail" and info["taken"] is False


@pytest.mark.parametrize(
    ("failure", "limited"),
    [
        (routing.RouterRefused(400, 442, "no path"), "no_way_round"),
        (routing.DeadlineExceeded("late"), "time"),
    ],
)
def test_the_router_failing_keeps_the_route(monkeypatch, failure, limited) -> None:
    Fake(monkeypatch, {"trail": ON_TRAIL}, failure)
    answered, info = winding_round.settle(trip("trail"), ctx_for())
    assert answered["legs"][0]["shape"] == "trail" and info["limited"] == limited


def test_a_newer_plan_still_ends_the_plan(monkeypatch) -> None:
    Fake(monkeypatch, {"trail": ON_TRAIL}, routing.PlanCancelled("replaced"))
    with pytest.raises(routing.PlanCancelled):
        winding_round.settle(trip("trail"), ctx_for())


def test_a_round_cut_short_by_time_is_not_kept_in_the_cache() -> None:
    body = {"variant": "weekend", "winding": {"limited": "time"}}
    assert route_cache.keepable(body, "weekend", 0) is False
    assert route_cache.keepable({**body, "winding": {"limited": None}}, "weekend", 0) is True


def zigzag(lon0: float, lat0: float, n: int, step: float = 3e-4) -> list[tuple[float, float]]:
    """A line that turns back and forth at each vertex (a winding trail)."""
    return [(lon0 + i * step, lat0 + (step if i % 2 else 0.0)) for i in range(n)]


def wkt(points) -> str:
    return "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in points) + ")"


@pytest.mark.django_db(transaction=True)
def test_the_table_is_read_by_the_ways_whole_line(segment_schemas) -> None:
    from django.db import connection

    live = segment_schemas[0]
    bends = zigzag(BASE[0], BASE[1], 9)
    straight = [(BASE[0] + i * 1e-3, BASE[1] + 0.01) for i in range(9)]
    assert winding.is_winding(bends) and not winding.is_winding(straight)
    rows = [
        # A winding trail in two segments, its own ordinals.
        (21, 0, bends[:5], True),
        (21, 1, bends[4:], True),
        (22, 0, straight, True),
        # A road that winds is no trail: Road Bike's graph does not price it either.
        (23, 0, [(x, y + 0.02) for x, y in bends], False),
    ]
    with connection.cursor() as cursor:
        for way, ordinal, points, trail in rows:
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, is_trail_class) VALUES (%s, %s, ST_GeomFromText(%s, 4326), 1, "
                "'x', %s)",
                [way, ordinal, wkt(points), trail],
            )
    assert winding_round.winding_ways(live, [21, 22, 23, 24, 0]) == {21}
