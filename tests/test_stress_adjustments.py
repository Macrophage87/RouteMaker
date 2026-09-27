"""Curated stress adjustments, and the owner's file of 2026-09-27 that carries them.

The owner, 2026-09-27: "we could have something clickable as a link to why
we'd consider a particular stretch of road level 5, or also why a particular
stretch of road might be adjusted, perhaps hidden. For instance we could
deviate from the typical LTS because of road conditions, known aggressive
drivers, problematic intersections, etc. Also we could down adjust a road if
this is the better route among similar routes."

The data side: every stress row names its adjustment (a stable id, a category,
a visibility, whether the owner has approved the words, and an optional
rider-facing note), a curated tier may sit below the classifier's, and what
reaches the served table is the id alone unless the adjustment is public and
approved. The owner's quoted reason is never part of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.management.commands.load_access_overrides import parse_file
from pipeline.overrides import (
    Override,
    OverrideRefused,
    apply_stress,
    stress_value_problem,
)
from routemaker.stress import (
    ADJUSTMENT_CATEGORIES,
    Stress,
    StressAdjustment,
    StressResult,
)

REPO = Path(__file__).resolve().parents[1]
OWNER_STRESS = REPO / "fixtures" / "overrides" / "2026-09-27-owner-stress.json"

GOOD = {
    "tier": 5,
    "adjustment_id": "a-stretch",
    "category": "sightlines",
    "visibility": "public",
    "annotation_status": "approved",
    "display": "route_only",
    "public_note": "Off-ramp traffic merges in at a blind corner.",
}

# Typed in from the owner's answers of 2026-09-27, not read from the file.
PENN_AFTER_THE_MERGE = {946400435, 50715834, 936339897}
SOUSA_ROADWAY = {50715828, 118727221}


def owner_rows() -> list[dict]:
    return json.loads(OWNER_STRESS.read_text())["rows"]


class TestTheValue:
    def test_a_complete_value_passes(self) -> None:
        assert stress_value_problem(GOOD) is None

    def test_the_note_is_optional(self) -> None:
        assert stress_value_problem({k: v for k, v in GOOD.items() if k != "public_note"}) is None

    def test_the_categories_are_the_owners(self) -> None:
        assert ADJUSTMENT_CATEGORIES == (
            "speed",
            "road_conditions",
            "driver_behaviour",
            "intersection",
            "sightlines",
            "better_among_alternatives",
            "other",
        )
        for category in ADJUSTMENT_CATEGORIES:
            assert stress_value_problem({**GOOD, "category": category}) is None

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"adjustment_id": "Penn Ave"}, "adjustment_id"),
            ({"adjustment_id": "-penn"}, "adjustment_id"),
            ({"adjustment_id": "penn-"}, "adjustment_id"),
            ({"adjustment_id": "a" * 65}, "adjustment_id"),
            ({"adjustment_id": 7}, "adjustment_id"),
            ({"visibility": "private"}, "visibility must"),
            ({"annotation_status": "draft"}, "annotation_status must"),
            ({"display": "everywhere"}, "display must"),
            ({"public_note": ""}, "public_note is non-empty"),
            ({"public_note": " padded"}, "public_note is non-empty"),
            ({"public_note": 3}, "public_note is non-empty"),
            ({"public_note": "x" * 201}, "at most 200"),
        ],
    )
    def test_a_malformed_value_is_named(self, change, message) -> None:
        assert message in stress_value_problem({**GOOD, **change})

    def test_an_id_of_sixty_four_characters_passes(self) -> None:
        assert stress_value_problem({**GOOD, "adjustment_id": "a" * 64}) is None

    @pytest.mark.parametrize(
        "note",
        [
            "Residents drive fast here.",
            "A rough neighborhood.",
            "Known for crime.",
            "People speed through the merge.",
            "Busy community street.",
            "In Ward 8.",
        ],
    )
    def test_a_note_about_a_place_or_its_people_is_refused(self, note) -> None:
        """The owner's rule: notes describe the road and traffic only."""
        assert "never a neighbourhood or its people" in stress_value_problem(
            {**GOOD, "public_note": note}
        )

    @pytest.mark.parametrize(
        "note",
        ["Traffic heading toward the bridge merges fast.", "Drivers merge at speed."],
    )
    def test_a_note_about_the_road_passes(self, note) -> None:
        assert stress_value_problem({**GOOD, "public_note": note}) is None


class TestTheAdjustment:
    def adjustment(self, tier: Stress, computed: Stress, **fields) -> StressAdjustment:
        return StressAdjustment(
            adjustment_id="a-stretch",
            tier=tier,
            computed_tier=computed,
            category=fields.get("category", "sightlines"),
            visibility=fields.get("visibility", "public"),
            annotation_status=fields.get("annotation_status", "approved"),
            public_note=fields.get("public_note", "A note."),
            display=fields.get("display", "route_only"),
        )

    @pytest.mark.parametrize(
        ("tier", "computed", "direction"),
        [
            (Stress.AVOID, Stress.LTS4, "up"),
            (Stress.LTS2, Stress.LTS4, "down"),
            (Stress.LTS4, Stress.LTS4, "same"),
        ],
    )
    def test_the_direction_is_taken_against_the_classifier(self, tier, computed, direction):
        assert self.adjustment(tier, computed).direction == direction

    def test_a_public_approved_adjustment_exposes_its_why(self) -> None:
        assert self.adjustment(Stress.AVOID, Stress.LTS4).exposed() == {
            "adjustment_id": "a-stretch",
            "adjusted": True,
            "direction": "up",
            "computed_tier": 4,
            "category": "sightlines",
            "public_note": "A note.",
            "display": "route_only",
        }

    @pytest.mark.parametrize(
        "fields",
        [{"visibility": "hidden"}, {"annotation_status": "proposed"}],
        ids=["hidden", "proposed"],
    )
    def test_hidden_or_unapproved_exposes_only_the_id(self, fields) -> None:
        assert self.adjustment(Stress.AVOID, Stress.LTS4, **fields).exposed() == {
            "adjustment_id": "a-stretch",
            "adjusted": True,
        }


class TestApplyingIt:
    def test_a_down_adjustment_is_applied(self) -> None:
        classified = {1: StressResult(Stress.LTS4, "mixed traffic, 35 mph or above")}
        value = {**GOOD, "tier": 2, "category": "better_among_alternatives"}
        assert apply_stress(classified, [Override("stress", 1, value)]) == (1, [])
        assert classified[1].tier is Stress.LTS2
        assert classified[1].adjustment.direction == "down"
        assert classified[1].adjustment.computed_tier is Stress.LTS4

    def test_the_computed_tier_is_the_classifiers_even_under_two_rows(self) -> None:
        classified = {1: StressResult(Stress.LTS3, "x")}
        rows = [
            Override("stress", 1, {**GOOD, "tier": 5}),
            Override("stress", 1, {**GOOD, "tier": 2, "adjustment_id": "b"}),
        ]
        apply_stress(classified, rows)
        assert classified[1].adjustment.computed_tier is Stress.LTS3
        assert classified[1].adjustment.direction == "down"

    def test_the_rule_names_the_adjustment_and_not_the_reason(self) -> None:
        classified = {1: StressResult(Stress.LTS4, "x")}
        apply_stress(classified, [Override("stress", 1, GOOD, reason="The owner's own words.")])
        assert classified[1].rule == "override: stress adjustment a-stretch"

    def test_a_legacy_row_is_a_hidden_adjustment_named_for_its_way(self) -> None:
        classified = {9: StressResult(Stress.LTS2, "x")}
        apply_stress(classified, [Override("stress", 9, {"tier": 4})])
        adjustment = classified[9].adjustment
        assert (adjustment.adjustment_id, adjustment.visibility) == ("way-9", "hidden")
        assert adjustment.exposed() == {"adjustment_id": "way-9", "adjusted": True}

    @pytest.mark.parametrize(
        "value",
        [{**GOOD, "category": "gossip"}, {"tier": 7}, {"tier": "5"}, {**GOOD, "tier": 0}],
    )
    def test_a_malformed_approved_row_refuses_the_rebuild(self, value) -> None:
        with pytest.raises(OverrideRefused):
            apply_stress({1: StressResult(Stress.LTS4, "x")}, [Override("stress", 1, value)])


class TestTheOwnersFile:
    def test_it_loads(self) -> None:
        parse_file(OWNER_STRESS.read_text(), OWNER_STRESS.name)

    def test_every_note_is_approved_for_a_routes_summary_only(self) -> None:
        """The owner, 2026-09-27: "Only provide the warnings if the route goes
        over the road." Approved as proposed, for route_only display."""
        for row in owner_rows():
            assert row["value"]["visibility"] == "public"
            assert row["value"]["annotation_status"] == "approved"
            assert row["value"]["display"] == "route_only"
            assert row["value"]["public_note"]

    def test_us_340_is_speed(self) -> None:
        (row,) = [r for r in owner_rows() if r["osm_way_id"] == 15561007]
        assert row["value"]["category"] == "speed"

    def test_pennsylvania_avenue_after_the_merge_is_a_sightline(self) -> None:
        penn = [r for r in owner_rows() if r["osm_way_id"] in PENN_AFTER_THE_MERGE]
        assert {r["osm_way_id"] for r in penn} == PENN_AFTER_THE_MERGE
        assert {r["value"]["adjustment_id"] for r in penn} == {"pennsylvania-ave-se-dc-295-merge"}
        assert all(r["value"]["tier"] == 5 for r in penn)
        assert all(r["value"]["category"] == "sightlines" for r in penn)
        assert all("blind corner" in r["value"]["public_note"] for r in penn)
        assert all("a level 5 road afterwards" in r["reason"] for r in penn)

    def test_the_sousa_bridge_roadway_stays_lts_4(self) -> None:
        sousa = [r for r in owner_rows() if r["osm_way_id"] in SOUSA_ROADWAY]
        assert {r["osm_way_id"] for r in sousa} == SOUSA_ROADWAY
        assert all(r["value"]["tier"] == 4 for r in sousa)

    def test_no_note_repeats_the_owners_reason(self) -> None:
        """The quoted reason is audit-only; the note is written for a rider."""
        for row in owner_rows():
            assert row["value"]["public_note"] not in row["reason"]
            assert '"' not in row["value"]["public_note"]
