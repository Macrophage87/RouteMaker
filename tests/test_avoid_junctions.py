"""Avoid-rated junctions (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS 307-310, 335).

The pure half (`routemaker.avoid_junctions`: which junctions a line passes, the
penalty and the words), the plan-time half (`core.avoid_junctions.settle`: the way
round, taken or offered), the admin's list and counts, and POST /api/route through
the real view with a stand-in router that routes round a junction only when it is
excluded.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.gis.geos import Point as GeoPoint
from test_admin_scoping import (  # noqa: F401
    admin_url,
    as_guild_admin,
    as_instance_admin,
    guild,
    guild_admin,
    instance_admin,
)
from test_bikeshare import DUPONT, UNION, FakeServices
from test_bikeshare import run as run_bikeshare
from test_route_api import LAT, VERTICES, post, route_answer

from core import avoid_junctions, gbfs, presets, refine, routing
from core.models import AuditLogEntry, AvoidJunction
from routemaker import avoid_junctions as model
from routemaker import calm

pytestmark = pytest.mark.usefixtures("weekday_clock")

db = pytest.mark.django_db(transaction=True)

JUNCTION = VERTICES[2]  # (-77.035, 38.9), on the direct route
# The way round: north a block at -77.04, east, and back down at -77.03.
DETOUR = [
    VERTICES[0],
    VERTICES[1],
    (-77.04, LAT + 0.003),
    (-77.03, LAT + 0.003),
    VERTICES[3],
    VERTICES[4],
]


def junction(id_=1, name="Main St and 1st Ave", reason="no gap in fast traffic"):
    return model.AvoidJunction(id_, name, reason, JUNCTION[0], JUNCTION[1])


# --- The pure half --------------------------------------------------------------------


class TestPenalty:
    def test_the_junction_penalty_is_the_avoid_roads_entry_charge(self) -> None:
        """308: "Probably a 30 minute penalty like Avoid." One figure, restated where
        `routemaker` cannot import `core`, and the rolling score's copy of the road's."""
        assert presets.AVOID_JUNCTION_PENALTY_S == presets.AVOID_ENTRY_PENALTY_S == 1800
        assert model.AVOID_JUNCTION_PENALTY_S == presets.AVOID_JUNCTION_PENALTY_S
        assert calm.AVOID_ENTRY_S == model.AVOID_JUNCTION_PENALTY_S

    def test_each_pass_pays_it(self) -> None:
        one = model.Passage(junction(), 10.0)
        assert model.penalty_s([]) == 0
        assert model.penalty_s([one]) == 1800
        assert model.penalty_s([one, model.Passage(junction(), 900.0)]) == 3600


class TestPassages:
    def test_a_route_through_the_junction_passes_it_where_it_comes_nearest(self) -> None:
        found = model.passages(VERTICES, [junction()])
        assert len(found) == 1
        # Two vertices along: 0.015 degrees of longitude at 38.9 N, about 1,300 m.
        assert found[0].m == pytest.approx(model.line_length_m(VERTICES[:3]), abs=1.0)
        assert 1250 < found[0].m < 1350

    def test_a_route_a_block_away_does_not(self) -> None:
        assert model.passages(DETOUR, [junction()]) == []

    def test_the_radius_is_15_m(self) -> None:
        # 0.0001 degrees of latitude is about 11 m; 0.0002 about 22 m.
        near = [(lon, lat + 0.0001) for lon, lat in VERTICES]
        far = [(lon, lat + 0.0002) for lon, lat in VERTICES]
        assert len(model.passages(near, [junction()])) == 1
        assert model.passages(far, [junction()]) == []

    def test_a_loop_through_it_twice_passes_it_twice(self) -> None:
        there_and_back = [*VERTICES, *reversed(VERTICES[:-1])]
        found = model.passages(there_and_back, [junction()])
        assert len(found) == 2
        assert found[0].m < found[1].m

    def test_no_list_or_no_line_is_no_passage(self) -> None:
        assert model.passages(VERTICES, []) == []
        assert model.passages(VERTICES[:1], [junction()]) == []


class TestWords:
    def test_the_accessible_name_is_the_rating_and_the_reason_never_the_glyph(self) -> None:
        """309: "its accessible name is 'Avoid-rated junction' plus the reason, not
        'skull and crossbones'"."""
        text = model.label(junction())
        assert text == "Avoid-rated junction: Main St and 1st Ave, no gap in fast traffic"
        assert model.SYMBOL not in text
        assert "skull" not in text.lower()

    def test_the_notice_names_each_junction_once(self) -> None:
        """335: "This route goes through an Avoid-rated junction: <name>, <reason>"."""
        a = junction()
        assert model.notice([]) is None
        assert model.notice([model.Passage(a, 5.0), model.Passage(a, 50.0)]) == (
            "This route goes through an Avoid-rated junction: Main St and 1st Ave,"
            " no gap in fast traffic. Riding through it is a really bad idea."
            " Please reconsider your route."
        )
        b = junction(2, "Oak Rd and Elm St", "blind left turn")
        assert model.notice([model.Passage(a, 5.0), model.Passage(b, 50.0)]) == (
            "This route goes through 2 Avoid-rated junctions: Main St and 1st Ave,"
            " no gap in fast traffic; Oak Rd and Elm St, blind left turn."
            " Riding through them is a really bad idea. Please reconsider your route."
        )

    def test_the_description_says_it_ahead_us_units_first(self) -> None:
        """307: "announced in the description, e.g. 'Avoid-rated junction ahead'"."""
        text = model.ahead_text(junction(), 1931.0)
        assert text == (
            "Avoid-rated junction ahead at 1.2 mi (1.9 km): Main St and 1st Ave,"
            " no gap in fast traffic. Riding through it is a really bad idea."
            " Please reconsider your route."
        )

    def test_its_entries_go_in_route_order(self) -> None:
        description = [
            {"kind": "stretch", "from_m": 0, "to_m": 1000, "text": "a"},
            {"kind": "stretch", "from_m": 1000, "to_m": 2000, "text": "b"},
        ]
        out = model.with_entries(description, [model.Passage(junction(), 1000.0)])
        assert [e["kind"] for e in out] == ["stretch", "avoid", "stretch"]
        assert out[1]["severity"] == "avoid"
        assert out[1]["from_m"] == out[1]["to_m"] == 1000
        assert model.with_entries(None, [model.Passage(junction(), 1.0)]) is None
        assert model.with_entries(description, []) is description


# --- The search's score ---------------------------------------------------------------


def test_the_calm_search_scores_a_pass_at_30_minutes_and_ranks_it_above_red() -> None:
    """The search weighs the penalty (308) and, at the top of the slider, keeps it in
    the top figure above red (307: "kept in the stress order's top level")."""
    ctx = refine.Context(
        variant="standard", request={}, costing={}, when="weekend",
        deadline=routing.Deadline(0, 1), traces={}, points=[], roadway_only=False,
        with_facility=False, group=False, rate=0.0, weight=1.0, climb_weight=0.0,
        quiet_cost=0.44,
    )  # fmt: skip
    plain = refine.Analysis(
        length_m=1000, cost_s=500, exposure_m=0, climb_m=0, pieces=[], classes=[], events=[]
    )
    passing = refine.Analysis(
        length_m=1000, cost_s=500, exposure_m=0, climb_m=0, pieces=[], classes=[], events=[],
        avoid_passages=[model.Passage(junction(), 500.0)], avoid_junction_m=1800 / 0.44,
    )  # fmt: skip
    assert passing.score(ctx) - plain.score(ctx) == pytest.approx(1800)
    assert passing.top_m == pytest.approx(1800 / 0.44)
    # The search excludes it first (its own point), clear of the route's ends.
    long_one = refine.Analysis(
        length_m=3000, cost_s=500, exposure_m=0, climb_m=0, pieces=[], classes=[], events=[],
        avoid_passages=[model.Passage(junction(), 1500.0)],
    )  # fmt: skip
    # With the 15 m radius `core.avoid_junctions.exclusions` asks, so every edge at it goes.
    assert refine.crossing_targets(long_one, ctx) == [refine.Target(JUNCTION, 5, 15)]
    near_start = refine.Analysis(
        length_m=3000, cost_s=500, exposure_m=0, climb_m=0, pieces=[], classes=[], events=[],
        avoid_passages=[model.Passage(junction(), 100.0)],
    )  # fmt: skip
    assert refine.crossing_targets(near_start, ctx) == []


# --- The plan-time half ---------------------------------------------------------------


def trip_of(vertices, length_km, cost):
    body = route_answer([(vertices, length_km, [])])["trip"]
    body["summary"]["cost"] = cost
    return body


class AroundRouter:
    """Answers /route with the way round where the junction is excluded."""

    def __init__(self, around=None, refuse=False):
        self.around = around
        self.refuse = refuse
        self.calls: list[dict] = []

    def __call__(self, variant, endpoint, payload, deadline):
        self.calls.append(payload)
        if self.refuse:
            raise routing.RouterRefused(400, "no path", 442)
        return {"trip": self.around}


@pytest.fixture
def around(monkeypatch):
    def install(fake: AroundRouter) -> AroundRouter:
        monkeypatch.setattr(routing, "_call", fake)
        return fake

    return install


def far_deadline():
    return routing.Deadline(routing.clock() + 60, 10)


class TestSettle:
    def test_a_route_that_passes_none_is_left_alone_with_no_router_call(self, around) -> None:
        fake = around(AroundRouter())
        trip = trip_of(DETOUR, 2.5, 600)
        assert avoid_junctions.settle(
            trip, {}, "standard", "default", far_deadline(), [junction()], False
        ) == (trip, None, None)
        assert fake.calls == []

    def test_the_way_round_is_asked_with_the_junction_excluded(self, around) -> None:
        fake = around(AroundRouter(trip_of(DETOUR, 2.5, 3000)))
        request = {"locations": [], "alternates": 3, "exclude_locations": [{"lon": 1, "lat": 2}]}
        avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), request, "standard", "default", far_deadline(),
            [junction()], False,
        )  # fmt: skip
        sent = fake.calls[0]
        assert "alternates" not in sent
        assert sent["exclude_locations"] == [
            {"lon": 1, "lat": 2},
            {"lon": JUNCTION[0], "lat": JUNCTION[1], "radius": 15},
        ]

    def test_a_way_round_cheaper_than_30_minutes_replaces_the_route(self, around) -> None:
        around(AroundRouter(trip_of(DETOUR, 2.5, 500 + 1799)))
        trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), {}, "standard", "default", far_deadline(),
            [junction()], False,
        )  # fmt: skip
        assert trip["summary"]["length"] == 2.5
        assert offered is None
        assert info == {
            "passed": 0, "penalty_s": 0, "decision": "avoided", "alternate": None, "avoided": 1,
        }  # fmt: skip

    def test_a_dearer_way_round_is_offered_and_the_route_kept(self, around) -> None:
        """335: the route uses one only when there is no reasonable alternative, and
        then offers "the best route that avoids it, even if much longer"."""
        around(AroundRouter(trip_of(DETOUR, 9.0, 500 + 1801)))
        trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), {}, "standard", "default", far_deadline(),
            [junction()], False,
        )  # fmt: skip
        assert trip["summary"]["length"] == 2.2
        assert offered["summary"]["length"] == 9.0
        assert info["decision"] == "kept"
        assert info["alternate"] == "found"
        assert info["penalty_s"] == 1800

    def test_where_the_search_weighed_it_the_way_round_is_offered_not_imposed(self, around) -> None:
        around(AroundRouter(trip_of(DETOUR, 2.5, 600)))
        trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), {}, "standard", "default", far_deadline(),
            [junction()], True,
        )  # fmt: skip
        assert trip["summary"]["length"] == 2.2
        assert offered is not None
        assert info["decision"] == "kept"

    @pytest.mark.parametrize("preset", ["mass-ride", "group-ride"])
    @pytest.mark.parametrize(
        ("route_km", "around_km", "lts4", "taken"),
        [
            (2.2, 3.5, (0, 0), True),  # 0.8 mi longer: within the 1 mi
            (2.2, 4.0, (0, 0), False),  # 1.1 mi longer: past the 1 mi (and past 25%)
            (10.0, 12.4, (0, 0), True),  # 24% longer: past the 1 mi, within 25%
            (10.0, 12.6, (0, 0), False),  # 26% longer
            (2.2, 2.5, (0, 120), False),  # takes on LTS 4
            (2.2, 2.5, (300, 300.5), True),  # no LTS 4 beyond the route's own (rounding)
        ],
    )
    def test_mass_ride_and_group_ride_take_a_way_round_within_the_default_limits(
        self, around, monkeypatch, preset, route_km, around_km, lts4, taken
    ) -> None:
        """307: "Mass Ride and Group Ride exclude Avoid junctions where an alternative
        exists", within the default the coordinator picked for the owner (the review of
        351e65b): no LTS 4 added, at most 1 mi (1.6 km) or 25% longer, whichever is more.
        Outside it, the route is kept and the way round offered."""
        around(AroundRouter(trip_of(DETOUR, around_km, 99_999)))
        read = {route_km: lts4[0], around_km: lts4[1]}
        monkeypatch.setattr(
            refine,
            "analyse",
            lambda trip, ctx, deadline, with_events=True: SimpleNamespace(
                lts4_m=read[trip["summary"]["length"]]
            ),
        )
        trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, route_km, 500), {}, "standard", preset, far_deadline(),
            [junction()], True, ctx=object(),
        )  # fmt: skip
        if taken:
            assert trip["summary"]["length"] == around_km
            assert info["decision"] == "avoided" and offered is None
        else:
            assert trip["summary"]["length"] == route_km
            assert info["decision"] == "kept" and info["alternate"] == "found"
            assert offered["summary"]["length"] == around_km

    def test_group_ride_keeps_the_route_where_the_stress_cannot_be_read(self, around) -> None:
        around(AroundRouter(trip_of(DETOUR, 2.5, 99_999)))
        trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), {}, "standard", "group-ride", far_deadline(),
            [junction()], True, ctx=None,
        )  # fmt: skip
        assert trip["summary"]["length"] == 2.2
        assert info["decision"] == "kept" and offered is not None

    @pytest.mark.parametrize("preset", ["default", "mass-ride"])
    def test_a_loop_keeps_its_route_and_is_offered_the_way_round(
        self, around, monkeypatch, preset
    ) -> None:
        """A loop's way back was made by a different way (`refine.make_loop`); the way
        round is a plain route through the same points, so it is offered, never swapped
        in, and the loop's own figures describe the route shown (the review of 351e65b)."""
        around(AroundRouter(trip_of(DETOUR, 2.3, 500 + 10)))
        monkeypatch.setattr(refine, "analyse", lambda *a, **k: SimpleNamespace(lts4_m=0.0))
        trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), {}, "standard", preset, far_deadline(),
            [junction()], False, ctx=object(), loop=True,
        )  # fmt: skip
        assert trip["summary"]["length"] == 2.2
        assert info["decision"] == "kept"
        assert offered["summary"]["length"] == 2.3

    def test_no_way_round_keeps_the_route_and_says_so(self, around) -> None:
        around(AroundRouter(refuse=True))
        trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), {}, "standard", "mass-ride", far_deadline(),
            [junction()], False,
        )  # fmt: skip
        assert trip["summary"]["length"] == 2.2
        assert offered is None
        assert info["alternate"] == "no_route"

    def test_a_way_round_still_through_it_is_no_way_round(self, around) -> None:
        around(AroundRouter(trip_of(VERTICES, 2.2, 400)))
        _trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), {}, "standard", "default", far_deadline(),
            [junction()], False,
        )  # fmt: skip
        assert offered is None
        assert info["alternate"] == "no_route"

    def test_with_no_time_left_nothing_is_asked(self, around) -> None:
        fake = around(AroundRouter(trip_of(DETOUR, 2.5, 600)))
        _trip, info, offered = avoid_junctions.settle(
            trip_of(VERTICES, 2.2, 500), {}, "standard", "default",
            routing.Deadline(routing.clock() + 1, 1), [junction()], False,
        )  # fmt: skip
        assert fake.calls == [] and offered is None
        assert info["alternate"] == "time"


# --- The stored list ------------------------------------------------------------------


def add_row(approved=True, **fields) -> AvoidJunction:
    values = {
        "name": "Main St and 1st Ave",
        "reason": "no gap in fast traffic",
        "location": GeoPoint(JUNCTION[0], JUNCTION[1], srid=4326),
        "approved": approved,
        **fields,
    }
    return AvoidJunction.objects.create(**values)


@db
class TestStoredList:
    def test_it_ships_empty(self) -> None:
        """307: "Ships with an empty list"."""
        assert AvoidJunction.objects.count() == 0
        assert avoid_junctions.approved() == ()

    def test_only_approved_rows_route(self) -> None:
        kept = add_row()
        add_row(approved=False, name="Pending")
        assert avoid_junctions.approved() == (
            model.AvoidJunction(kept.id, kept.name, kept.reason, JUNCTION[0], JUNCTION[1]),
        )

    def test_a_plan_through_one_is_counted_and_nothing_else_is_kept(self) -> None:
        """335's admin view: how often plans pass through them; a counter and a date."""
        row = add_row()
        found = model.passages(VERTICES, avoid_junctions.approved())
        avoid_junctions.record(found)
        avoid_junctions.record(found)
        row.refresh_from_db()
        assert row.plans_through == 2
        assert row.last_planned_through_at is not None


# --- POST /api/route ------------------------------------------------------------------


def trace_for(payload):
    """A /trace_attributes answer for whatever line was asked: one edge a segment,
    all of way 101 (LTS 3)."""
    shape = routing.decode_polyline6(payload["encoded_polyline"])
    return {
        "units": "kilometers",
        "shape": payload["encoded_polyline"],
        "edges": [
            {"way_id": 101, "begin_shape_index": i, "end_shape_index": i + 1, "length": 0.4}
            for i in range(len(shape) - 1)
        ],
    }


class PlanRouter:
    """The direct route through the junction, unless the junction is excluded; then
    the way round, `detour_km` long, which costs `detour_cost` against the direct
    route's 500."""

    def __init__(self, detour_cost: float, detour_km: float = 6.0) -> None:
        self.detour_cost = detour_cost
        self.detour_km = detour_km
        self.excluded: list[list] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        endpoint = url.rsplit("/", 1)[1]
        if endpoint == "trace_attributes":
            return trace_for(payload)
        if endpoint == "locate":
            return []
        excludes = payload.get("exclude_locations") or []
        if any(
            abs(e["lon"] - JUNCTION[0]) < 1e-6 and abs(e["lat"] - JUNCTION[1]) < 1e-6
            for e in excludes
        ):
            self.excluded.append(excludes)
            answer = route_answer([(DETOUR, self.detour_km, [])])
            answer["trip"]["summary"]["cost"] = self.detour_cost
            return answer
        answer = route_answer([(VERTICES, 2.2, [])])
        answer["trip"]["summary"]["cost"] = 500.0
        return answer


@pytest.fixture
def plan_router(monkeypatch):
    def install(fake):
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def body_for(preset="mass-ride"):
    return {"points": [list(VERTICES[0]), list(VERTICES[-1])], "preset": preset}


@db
class TestRouteApi:
    def test_with_the_list_empty_the_answer_carries_empty_fields(
        self, client, segment_schemas, plan_router
    ) -> None:
        fake = plan_router(PlanRouter(detour_cost=600.0))
        body = post(client, body_for()).json()
        assert body["avoid_junctions"] == []
        assert body["avoid_notice"] is None
        assert body["avoid_search"] is None
        assert body["avoid_alternate"] is None
        assert fake.excluded == []

    def test_mass_ride_goes_round_and_says_nothing_is_passed(
        self, client, segment_schemas, plan_router
    ) -> None:
        """A way round 0.8 mi (1.3 km) longer with no LTS 4 added: within the default."""
        add_row()
        fake = plan_router(PlanRouter(detour_cost=99_999.0, detour_km=3.5))
        body = post(client, body_for("mass-ride")).json()
        assert fake.excluded
        assert body["distance_m"] == 3500.0
        assert body["avoid_junctions"] == []
        assert body["avoid_notice"] is None
        assert body["avoid_search"]["decision"] == "avoided"
        assert body["avoid_alternate"] is None
        assert AvoidJunction.objects.get().plans_through == 0

    def test_mass_ride_keeps_a_route_whose_way_round_is_too_long_and_offers_it(
        self, client, segment_schemas, plan_router
    ) -> None:
        """2.4 mi (3.8 km) longer is past 1 mi and past 25%: the notice and the offer."""
        add_row()
        plan_router(PlanRouter(detour_cost=99_999.0, detour_km=6.0))
        body = post(client, body_for("mass-ride")).json()
        assert body["distance_m"] == 2200.0
        assert body["avoid_notice"].startswith("This route goes through an Avoid-rated junction")
        assert body["avoid_search"]["decision"] == "kept"
        assert body["avoid_alternate"]["distance_m"] == 6000.0
        assert AvoidJunction.objects.get().plans_through == 1

    def test_a_search_that_stopped_before_a_round_leaves_the_plan_to_weigh_it(
        self, client, segment_schemas, plan_router, monkeypatch
    ) -> None:
        """`searched` is what the search did (a round, not cut short), not that it was
        asked for: one that returned early has weighed nothing, so the plan's own
        comparison takes the cheaper way round. The routes to choose from were the
        replaced route's near-ties: none are offered (the review of 351e65b)."""
        add_row()

        def stopped(trip, ctx):
            ctx.candidates = [(trip, None), (trip, None)]
            return trip, {"rate": ctx.rate, "rounds": 0, "excluded": 0, "limited": "time"}

        monkeypatch.setattr(refine, "refine", stopped)
        plan_router(PlanRouter(detour_cost=500.0 + 900.0))
        body = post(client, body_for("default")).json()
        assert body["avoid_search"]["decision"] == "avoided"
        assert body["distance_m"] == 6000.0
        assert body["avoid_notice"] is None
        assert body["candidates"] is None

    def test_a_kept_junction_is_noticed_described_counted_and_the_way_round_offered(
        self, client, segment_schemas, plan_router, monkeypatch
    ) -> None:
        """335: the notice at the top, the way round as an alternate, the count; 307:
        the description says it ahead. The search is off (a long ride's rules), so the
        plan's own comparison decides: 30 minutes is less than the way round's extra
        cost, so the route keeps the junction."""
        row = add_row()
        monkeypatch.setattr(routing, "_refine_limit", lambda *a, **k: "long_ride")
        plan_router(PlanRouter(detour_cost=500.0 + 5000.0))
        body = post(client, body_for("default")).json()
        assert body["distance_m"] == 2200.0
        assert body["avoid_notice"] == (
            "This route goes through an Avoid-rated junction: Main St and 1st Ave,"
            " no gap in fast traffic. Riding through it is a really bad idea."
            " Please reconsider your route."
        )
        [passed] = body["avoid_junctions"]
        assert passed["id"] == row.id
        assert passed["label"] == (
            "Avoid-rated junction: Main St and 1st Ave, no gap in fast traffic"
        )
        # Scaled to the router's 2.2 km from the line's 2.6 km.
        assert 1050 < passed["m"] < 1150
        assert body["avoid_search"] == {
            "passed": 1, "penalty_s": 1800, "decision": "kept", "alternate": "found",
            "avoided": 0,
        }  # fmt: skip
        alternate = body["avoid_alternate"]
        assert alternate["distance_m"] == 6000.0
        assert alternate["extra_distance_m"] == 3800.0
        assert alternate["avoid_junctions"] == []
        kinds = [e["kind"] for e in body["description"]]
        assert "avoid" in kinds
        [said] = [e for e in body["description"] if e["kind"] == "avoid"]
        assert said["text"].startswith("Avoid-rated junction ahead at 0.7 mi (1.1 km)")
        assert [e for e in body["description_overview"] if e["kind"] == "avoid"]
        row.refresh_from_db()
        assert row.plans_through == 1

    def test_the_calm_search_excludes_it_and_takes_the_way_round(
        self, client, segment_schemas, plan_router
    ) -> None:
        """Where the search runs, it scores the pass at 30 minutes and its first round
        excludes the junction; the way round is taken although it rides more LTS 3
        (the Traffic-wins guard counts the junction's penalty on both sides)."""
        add_row()
        fake = plan_router(PlanRouter(detour_cost=500.0 + 900.0))
        body = post(client, body_for("default")).json()
        assert fake.excluded, "the search asked for the way round"
        assert body["calm_search"]["rounds"] >= 1
        assert body["distance_m"] == 6000.0
        assert body["avoid_junctions"] == []
        assert body["avoid_search"] is None

    def test_a_cheap_way_round_replaces_the_route(
        self, client, segment_schemas, plan_router, monkeypatch
    ) -> None:
        add_row()
        monkeypatch.setattr(routing, "_refine_limit", lambda *a, **k: "long_ride")
        plan_router(PlanRouter(detour_cost=500.0 + 900.0))
        body = post(client, body_for("default")).json()
        assert body["distance_m"] == 6000.0
        assert body["avoid_notice"] is None
        assert body["avoid_search"]["decision"] == "avoided"


# --- The admin ------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdmin:
    def test_the_list_page_leads_with_the_counts(self, as_instance_admin) -> None:  # noqa: F811
        """335: "a count of Avoid junctions and how often plans pass through them"."""
        add_row(plans_through=3)
        add_row(approved=False, name="Pending")
        response = as_instance_admin.get(admin_url("core_avoidjunction_changelist"))
        assert response.status_code == 200
        text = response.content.decode()
        assert 'id="avoid-junction-counts"' in text
        assert "<strong>1</strong> approved" in text
        assert "(1 awaiting approval)" in text
        assert "<strong>3</strong>" in text

    def test_approval_is_an_audited_action_not_a_form_field(
        self,
        as_instance_admin,  # noqa: F811
    ) -> None:
        row = add_row(approved=False)
        response = as_instance_admin.post(
            admin_url("core_avoidjunction_changelist"),
            {"action": "approve_selected", "_selected_action": [row.pk], "index": 0},
        )
        assert response.status_code == 302
        row.refresh_from_db()
        assert row.approved and row.approved_at is not None
        assert row.approved_by_user_id is not None
        assert AuditLogEntry.objects.filter(
            action="approve", model="avoidjunction", object_id=str(row.pk)
        ).exists()
        from core.admin import AvoidJunctionAdmin

        assert "approved" in AvoidJunctionAdmin.readonly_fields

    def test_withdrawal_is_audited_and_clears_who_approved_it(
        self,
        as_instance_admin,  # noqa: F811
    ) -> None:
        row = add_row(approved=True)
        row.approved_by_user_id = 77
        row.save()
        response = as_instance_admin.post(
            admin_url("core_avoidjunction_changelist"),
            {"action": "withdraw_selected", "_selected_action": [row.pk], "index": 0},
        )
        assert response.status_code == 302
        row.refresh_from_db()
        assert not row.approved
        assert row.approved_at is None
        assert row.approved_by is None and row.approved_by_user_id is None
        assert AuditLogEntry.objects.filter(
            action="withdraw",
            model="avoidjunction",
            object_id=str(row.pk),
            outcome=AuditLogEntry.Outcome.ALLOWED,
        ).exists()
        assert avoid_junctions.approved() == ()

    def test_a_guild_admin_is_refused_and_the_refusal_audited(
        self,
        as_guild_admin,  # noqa: F811
    ) -> None:
        """An approved row changes routing for every guild: one club's admin may not
        approve, withdraw or edit one."""
        row = add_row(approved=False)
        response = as_guild_admin.post(
            admin_url("core_avoidjunction_changelist"),
            {"action": "approve_selected", "_selected_action": [row.pk], "index": 0},
        )
        assert response.status_code == 403
        row.refresh_from_db()
        assert not row.approved
        assert AuditLogEntry.objects.filter(
            model="avoidjunction", outcome=AuditLogEntry.Outcome.REFUSED
        ).exists()
        assert as_guild_admin.get(admin_url("core_avoidjunction_change", row.pk)).status_code == 403


# --- The review of 351e65b: the search's guards, exclusions and long rides -------------------


def plain_ctx(**changes):
    ctx = refine.Context(
        variant="standard", request={}, costing={}, when="weekend",
        deadline=routing.Deadline(routing.clock() + 60, 10), traces={}, points=[],
        roadway_only=False, with_facility=False, group=False, rate=1.0, weight=1.0,
        climb_weight=0.0, quiet_cost=0.44,
    )  # fmt: skip
    for key, value in changes.items():
        setattr(ctx, key, value)
    return ctx


def test_the_traffic_wins_allowance_is_on_the_exposure_not_on_the_junctions_metres() -> None:
    """`_busier`: exposure plus the Avoid junctions' metres against the first route's
    allowance plus its Avoid junctions' metres, unscaled (the review's 9)."""
    ctx = plain_ctx(first_avoid_m=10_000.0)
    first_exposure = 1000.0
    allowance = refine._allowance(first_exposure) + 10_000.0
    read = refine.Analysis(
        length_m=1, cost_s=1, exposure_m=allowance, climb_m=0, pieces=[], classes=[], events=[]
    )
    assert not refine._busier(read, first_exposure, ctx)
    read.exposure_m = allowance + 1.0
    assert refine._busier(read, first_exposure, ctx)


def test_an_exclusion_on_an_avoid_junction_carries_its_15_m_radius() -> None:
    ctx = plain_ctx(avoid=(junction(),))
    assert refine._exclusion(JUNCTION[0], JUNCTION[1], ctx) == {
        "lon": JUNCTION[0], "lat": JUNCTION[1], "radius": 15,
    }  # fmt: skip
    assert refine._exclusion(-77.0, 38.0, ctx) == {"lon": -77.0, "lat": 38.0}
    assert refine._exclusion(-77.0, 38.0, ctx, 15)["radius"] == 15


def test_a_long_rides_leg_through_an_avoid_junction_is_searched_first(monkeypatch) -> None:
    """`refine_long`: a leg's Avoid junctions count with its LTS 4 in its weight, so a leg
    whose only fault is one is searched, and before a leg with LTS 3 (the review's 3)."""
    whole = refine.Analysis(
        length_m=60_000, cost_s=1, exposure_m=500, climb_m=0, pieces=[], classes=[], events=[]
    )
    plain = refine.Analysis(
        length_m=30_000, cost_s=1, exposure_m=500, climb_m=0, pieces=[], classes=[],
        events=[], lts3_m=500.0,
    )  # fmt: skip
    through = refine.Analysis(
        length_m=30_000, cost_s=1, exposure_m=0, climb_m=0, pieces=[], classes=[], events=[],
        avoid_passages=[model.Passage(junction(), 100.0)], avoid_junction_m=1800 / 0.44,
    )  # fmt: skip
    legs = [{"a": {"lon": 0, "lat": 0}, "b": {"lon": 1, "lat": 0}, "user": 0},
            {"a": {"lon": 1, "lat": 0}, "b": {"lon": 2, "lat": 0}, "user": 0}]  # fmt: skip
    leg_trips = [{"legs": [{"shape": "a"}], "summary": {"length": 30.0}},
                 {"legs": [{"shape": "b"}], "summary": {"length": 30.0}}]  # fmt: skip
    asked = iter(leg_trips)
    monkeypatch.setattr(routing, "_call", lambda *a, **k: {"trip": next(asked)})

    def read(trip, ctx, deadline, with_events=True):
        shape = (trip.get("legs") or [{}])[0].get("shape")
        return {"a": plain, "b": through}.get(shape, whole)

    monkeypatch.setattr(refine, "analyse", read)
    monkeypatch.setattr(refine, "long_legs", lambda whole, ctx: legs)
    searched: list[str] = []

    def search(trip, sub):
        searched.append(trip["legs"][0]["shape"])
        return trip, {"rate": 1.0, "rounds": 0, "excluded": 0, "limited": None}

    monkeypatch.setattr(refine, "refine", search)
    ctx = plain_ctx(
        request={"locations": [{"lon": 0, "lat": 0}, {"lon": 2, "lat": 0}]},
        points=[(0, 0), (2, 0)],
        avoid=(junction(),),
    )
    refine.refine_long({"legs": [{"shape": "whole"}], "summary": {"length": 60.0}}, ctx)
    assert searched == ["b", "a"]


def test_a_bikeshare_way_round_keeps_the_walks_docks_and_the_operators_credit() -> None:
    """The review's 8: the way round is shown in place of the ride leg, so it carries the
    plan's `bikeshare` (its ride and totals its own) and the GBFS credit."""

    class WithWayRound(FakeServices):
        def ride(self, a, b):
            body = super().ride(a, b)
            body["avoid_alternate"] = {
                **body,
                "distance_m": body["distance_m"] + 1000.0,
                "duration_s": body["duration_s"] + 300.0,
                "extra_distance_m": 1000.0,
                "extra_duration_s": 300.0,
            }
            return body

    services = WithWayRound(ride_speed_kmh=presets.BIKESHARE_BIKES["classic"].speed_kmh)
    body, _ = run_bikeshare(UNION, DUPONT, services=services)
    plan = body["bikeshare"]
    around = body["avoid_alternate"]
    assert around["attribution"] == ["© OpenStreetMap contributors, ODbL", gbfs.CREDIT]
    block = around["bikeshare"]
    assert block["credit"] == gbfs.CREDIT
    assert block["start"] == plan["start"] and block["end"] == plan["end"]
    assert block["walk_s"] == plan["walk_s"]
    assert block["ride_m"] == pytest.approx(plan["ride_m"] + 1000.0, abs=0.2)
    assert block["total_s"] == pytest.approx(block["walk_s"] + block["ride_s"], abs=0.2)
    ride_step = [s for s in block["steps"] if s["kind"] == "ride"][0]["text"]
    assert ride_step != [s for s in plan["steps"] if s["kind"] == "ride"][0]["text"]
    assert ride_step in block["summary"]
    # The plan's own block is untouched.
    assert plan["ride_m"] != block["ride_m"]
