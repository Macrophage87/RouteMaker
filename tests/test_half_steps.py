"""Half steps (OWNER-DECISIONS 441i-441v, 458-458b, 460.1, 461a; HALF-STEP-EDITOR-plan phase 2).

A half step (1.5, 2.5, 3.5, 4.5) is the lower tier plus a flag: the override value's `half`, the
segment table's `stress_half`, the tile's `half`. Pinned here: the value rules, the rebuild, the
editor (service and endpoint), the road panel's words, the tiles, and the midpoints the ranking,
the junction model and the rolling chart give a half step (stress-number.md section 3).
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db import connection
from mvt import decode
from test_stress_edits import (
    CREATE,
    LAT,
    LON,
    REASON,
    STATE,
    WAY,
    addr,
    admin_client,
    body,
    live_row,
    make_segment,
    make_user,
    post,
    token,
)
from test_stress_tiles import tile_of, url

from core import refine, routing, segment_info, stress_edits
from core.models import Override
from pipeline import overrides as pipeline_overrides
from pipeline.overrides import stress_value_problem
from routemaker import calm, intersections
from routemaker.intersections import Control, Road
from routemaker.stress import Stress, StressAdjustment, StressResult

db = pytest.mark.django_db(transaction=True)


def value(tier=3, **extra) -> dict:
    return {
        "tier": tier,
        "adjustment_id": "half-test",
        "category": "speed",
        "visibility": "hidden",
        "annotation_status": "approved",
        "display": "route_only",
        **extra,
    }


# --- The value rules -----------------------------------------------------------------


class TestValue:
    @pytest.mark.parametrize("tier", [1, 2, 3, 4])
    def test_a_half_step_from_one_and_a_half_to_four_and_a_half_is_allowed(self, tier) -> None:
        assert stress_value_problem(value(tier, half=True)) is None

    def test_there_is_no_step_above_avoid(self) -> None:
        assert "above Avoid" in stress_value_problem(value(5, half=True))

    def test_half_is_true_or_false(self) -> None:
        assert "half is true" in stress_value_problem(value(3, half="yes"))
        assert stress_value_problem(value(3, half=False)) is None

    def test_the_step_and_the_direction_count_the_half(self) -> None:
        adj = StressAdjustment("a", Stress(3), Stress(3), "speed", "hidden", "approved", half=True)
        assert adj.step == 3.5 and adj.direction == "up"
        down = StressAdjustment("a", Stress(3), Stress(4), "speed", "hidden", "approved", half=True)
        assert down.direction == "down"


def row(tier=3, **extra):
    return pipeline_overrides.Override(
        kind="stress", osm_way_id=WAY, value=value(tier, **extra), reason="r"
    )


class TestRebuild:
    def test_a_half_step_row_rates_the_way_and_carries_the_half(self) -> None:
        by_way = {WAY: StressResult(tier=Stress(3), rule="mixed traffic")}
        applied, _ = pipeline_overrides.apply_stress(by_way, [row(2, half=True)])
        assert applied == 1 and by_way[WAY].tier == 2 and by_way[WAY].adjustment.half is True

    def test_a_half_step_floor_raises_a_whole_step_at_its_lower_level(self) -> None:
        by_way = {WAY: StressResult(tier=Stress(3), rule="mixed traffic")}
        pipeline_overrides.apply_stress(by_way, [row(3, half=True, at_least=True)])
        assert by_way[WAY].adjustment.step == 3.5

    def test_a_half_step_floor_the_way_already_meets_changes_nothing(self) -> None:
        by_way = {WAY: StressResult(tier=Stress(4), rule="mixed traffic")}
        applied, _ = pipeline_overrides.apply_stress(by_way, [row(3, half=True, at_least=True)])
        assert applied == 0 and by_way[WAY].tier == 4 and by_way[WAY].adjustment is None

    def test_the_writer_writes_the_half(self) -> None:
        from pipeline.writers import _half

        adj = StressAdjustment("a", Stress(2), Stress(3), "speed", "hidden", "approved", half=True)
        assert _half(StressResult(tier=Stress(2), rule="r", adjustment=adj)) is True
        assert _half(StressResult(tier=Stress(2), rule="r")) is False


# --- The editor ------------------------------------------------------------------------


@pytest.fixture
def live(segment_schemas):
    schema, _staging = segment_schemas
    make_segment(schema, WAY, 3)
    segment_info.forget_columns()
    yield schema
    segment_info.forget_columns()


def half_spec(tier=3, **kw) -> stress_edits.Spec:
    return stress_edits.Spec(
        tier=tier,
        half=True,
        at_least=kw.pop("at_least", False),
        category="speed",
        reason=REASON,
        **kw,
    )


@db
class TestEditor:
    def test_every_step_by_halves(self) -> None:
        assert stress_edits.STEPS == (1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5)
        assert stress_edits.split_step(3.5) == (3, True)
        assert stress_edits.split_step(4) == (4, False)
        for bad in (5.5, 2.25, 0, True, "3"):
            with pytest.raises(stress_edits.Invalid):
                stress_edits.split_step(bad)

    def test_a_half_step_is_written_as_the_lower_tier_and_the_flag(self, live) -> None:
        result = stress_edits.apply(make_user(), [WAY], half_spec(3), token(live))
        held = live_row(live)
        assert held["stress_tier"] == 3 and held["stress_half"] is True
        assert result.ways[0]["step"] == 3.5 and result.ways[0]["changed"] is True
        row_ = Override.objects.get(source="panel")
        assert row_.value["half"] is True and row_.value["tier"] == 3

    def test_a_whole_step_after_a_half_clears_the_flag_and_undo_brings_it_back(self, live) -> None:
        admin = make_user()
        stress_edits.apply(admin, [WAY], half_spec(2), token(live))
        whole = stress_edits.Spec(tier=4, at_least=False, category="speed", reason=REASON)
        edit = stress_edits.apply(admin, [WAY], whole, token(live)).edit
        assert live_row(live)["stress_half"] is False
        stress_edits.undo(admin, edit.pk)
        held = live_row(live)
        assert held["stress_tier"] == 2 and held["stress_half"] is True

    def test_a_half_step_floor_above_the_road_raises_it(self, live) -> None:
        result = stress_edits.apply(make_user(), [WAY], half_spec(3, at_least=True), token(live))
        assert result.ways[0]["step"] == 3.5 and live_row(live)["stress_half"] is True

    def test_a_half_step_floor_below_the_road_changes_nothing(self, live) -> None:
        result = stress_edits.apply(make_user(), [WAY], half_spec(2, at_least=True), token(live))
        held = live_row(live)
        assert (
            result.ways[0]["step"] == 3
            and held["stress_tier"] == 3
            and held["stress_half"] is False
        )

    def test_the_starting_state_offers_nine_steps_and_says_the_exact_one(self, live) -> None:
        stress_edits.apply(make_user(), [WAY], half_spec(3), token(live))
        state = stress_edits.editor_state(make_user(), WAY)
        assert [s["value"] for s in state["steps"]] == [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]
        words = {s["value"]: s["words"] for s in state["steps"]}
        assert words[1.5] == "Probably comfortable for older children"
        assert words[2.5] == "Fine for most confident adults"
        assert words[3.5] == "Stressful even for experienced cyclists"
        assert words[4.5] == "A very high-stress road"
        assert state["current"]["step"] == 3.5 and state["half_steps"] is True
        assert state["current"]["words"] == "Stressful even for experienced cyclists"

    def test_without_the_column_whole_steps_work_and_a_half_is_refused(self, live) -> None:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN stress_half")
        segment_info.forget_columns()
        assert stress_edits.editor_state(make_user(), WAY)["half_steps"] is False
        with pytest.raises(stress_edits.Invalid) as refused:
            stress_edits.apply(make_user(), [WAY], half_spec(3), token(live))
        assert refused.value.code == "half_unavailable" and refused.value.field == "step"
        assert Override.objects.count() == 0
        whole = stress_edits.Spec(tier=4, at_least=False, category="speed", reason=REASON)
        stress_edits.apply(make_user(), [WAY], whole, token(live))
        assert live_row(live)["stress_tier"] == 4

    def test_the_command_adds_the_column_dry_first(self, live) -> None:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN stress_half")
        out = io.StringIO()
        call_command("add_stress_half_column", stdout=out)
        assert "dry run" in out.getvalue()
        segment_info.forget_columns()
        assert "stress_half" not in segment_info.live_columns(live)
        call_command("add_stress_half_column", "--confirm", stdout=io.StringIO())
        segment_info.forget_columns()
        assert "stress_half" in segment_info.live_columns(live)
        out = io.StringIO()
        call_command("add_stress_half_column", "--confirm", stdout=out)
        assert "nothing to do" in out.getvalue()

    def test_the_endpoint_takes_a_half_step(self, live) -> None:
        client, csrf = admin_client()
        r = post(client, CREATE, body(live, step=2.5), csrf)
        assert r.status_code == 200, r.json()
        assert r.json()["ways"][0]["step"] == 2.5
        state = client.get(STATE.format(WAY), **addr()).json()
        assert state["current"]["step"] == 2.5 and 4.5 in [s["value"] for s in state["steps"]]

    @pytest.mark.parametrize("step", [2.25, 5.5, 0.5])
    def test_the_endpoint_refuses_a_step_that_is_not_a_half(self, live, step) -> None:
        client, csrf = admin_client()
        r = post(client, CREATE, body(live, step=step), csrf)
        assert r.status_code == 400 and r.json().get("field") == "step"


# --- The road panel ------------------------------------------------------------------------


class TestPanelWords:
    def test_every_step_has_the_owners_words(self) -> None:
        assert list(segment_info.STEP_WORDS) == [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]
        assert segment_info.tier_text(3, True) == (
            "LTS 3.5: Stressful even for experienced cyclists"
        )
        assert segment_info.stress_short(4, True) == "LTS 4.5 · A very high-stress road"
        assert segment_info.stress_short(5, True) == "Avoid"
        assert segment_info.tier_text(2) == "LTS 2: Fine for adults"

    def test_the_rows_and_the_answer_say_the_exact_step(self) -> None:
        row_ = {"stress_tier": 1, "stress_half": True, "stress_rule": "override: x"}
        level = segment_info.stress_rows(row_)[0]
        assert level["value"] == "LTS 1.5: Probably comfortable for older children"


@db
class TestTiles:
    def test_a_half_step_tile_carries_half_and_a_whole_step_does_not(self, client, live) -> None:
        make_segment(live, WAY + 1, 2, lon=LON, lat=LAT + 0.0003, stress_half=True)
        z, x, y = tile_of(LON, LAT, 14)
        features = decode(client.get(url(z, x, y)).content)["stress"].features
        halves = {f.properties.get("tier"): f.properties.get("half") for f in features}
        assert halves == {3: None, 2: True}


# --- The midpoints (461a) ------------------------------------------------------------------


def piece(metres=100.0):
    return SimpleNamespace(metres=metres, lon=0.0, lat=0.0)


def cls(tier, half=False):
    return routing.PieceClass(tier, "none", half=half)


class TestRanking:
    def test_a_half_step_weighs_the_midpoint(self) -> None:
        standard = {"3": 1.0, "4": 2.0, "5": 3.0}
        averse = {"3": 1.0, "4": 8.0, "5": 16.0}
        assert refine.half_weight("2", standard) == 0.5
        assert refine.half_weight("3", standard) == 1.5
        assert refine.half_weight("4", standard) == 2.5
        assert refine.half_weight("3", averse) == 4.5
        assert refine.half_weight("4", averse) == 12.0
        assert refine.half_weight("1", standard) == 0.0

    def test_the_half_steps_add_their_share_of_the_exposure(self) -> None:
        pieces = [piece(), piece(), piece()]
        classes = [cls("2", True), cls("3", True), cls("1", True)]
        halves = refine.half_metres(pieces, classes)
        assert halves == {"1": 100.0, "2": 100.0, "3": 100.0, "4": 0.0}
        standard = {"3": 1.0, "4": 2.0, "5": 3.0}
        # 2.5 adds 0.5 over LTS 2's 0; 3.5 adds 0.5 over LTS 3's 1.
        assert refine.half_exposure_m(halves, standard) == 100.0

    def test_on_and_off_rules_take_the_cautious_side_but_four_and_a_half_is_never_avoid(self):
        assert refine.cautious_tier(cls("2", True)) == 3
        assert refine.cautious_tier(cls("3", True)) == 4
        assert refine.cautious_tier(cls("4", True)) == 4
        assert refine.cautious_tier(cls("2")) == 2
        assert refine.cautious_tier(cls("unknown")) is None
        assert routing.PieceClass("5", "none", half=True).half is False

    def test_a_half_step_is_its_own_section_of_the_route(self) -> None:
        spans = routing.stress_spans(
            [
                (100.0, "3", "none", None, None, False, False),
                (100.0, "3", "none", None, None, False, True),
            ]
        )
        assert [s.get("half") for s in spans] == [None, True]
        assert [s["tier"] for s in spans] == [3, 3]


class TestJunctions:
    def test_a_half_step_road_costs_the_midpoint(self) -> None:
        def cost(tier, half, control=Control.NONE):
            return intersections.crossing_ft(Road(tier, half=half), control, 1)

        assert cost(2, True) == 600.0
        assert cost(3, True) == 2100.0
        assert cost(4, True) == 3000.0
        assert cost(2, True, Control.SIGNAL) == 75.0
        assert cost(3, True, Control.SIGNAL) == 225.0

    def test_two_and_a_half_is_busy_and_two_is_not(self) -> None:
        assert Road(2, half=True).busy and not Road(2).busy and Road(3).busy

    def test_left_across_oncoming_at_the_midpoint(self) -> None:
        road = Road(3, half=True, oneway=False, lanes=1)
        assert intersections.left_from_ft(road, Control.NONE) == 1050.0


class TestRollingChart:
    def test_a_half_step_counts_the_midpoint_multiplier(self) -> None:
        pricing = calm.Pricing(use_roads=0.1)
        m3 = calm.multiplier(3, None, pricing)
        m4 = calm.multiplier(4, None, pricing)
        assert calm.multiplier(3, None, pricing, half=True) == pytest.approx((m3 + m4) / 2)
        m2 = calm.multiplier(2, None, pricing)
        assert calm.multiplier(2, None, pricing, half=True) == pytest.approx((m2 + m3) / 2)
        steps = calm.steps_of([{"from_m": 0, "to_m": 10, "tier": 3, "half": True}], pricing)
        assert steps[0].ratio == pytest.approx((m3 + m4) / 2)
