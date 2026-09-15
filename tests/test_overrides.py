"""Approved override rows, applied during preprocessing.

The override table is the plan's sole path for access corrections. Until the
stage these tests cover existed, it was a table the admin could edit and no stage
ever read: a row could be written, reviewed and approved, and the graph was built
exactly as if it were not there.
"""

from __future__ import annotations

import pytest

from pipeline.overrides import (
    Override,
    OverrideRefused,
    apply_access,
    apply_jurisdiction,
    apply_stress,
    load_approved,
)
from routemaker.stress import Stress, StressResult


class Way:
    def __init__(self, osm_id: int, **tags: str) -> None:
        self.osm_id = osm_id
        self.tags = dict(tags)


def test_an_access_override_rewrites_the_tag_before_the_transform() -> None:
    """Applied before the extract is written, so Valhalla derives its access
    attributes from the corrected value rather than from the original."""
    way = Way(1, highway="secondary", bicycle="no")
    applied, unmatched = apply_access([way], [Override("access", 1, {"bicycle": "yes"})])
    assert (applied, unmatched) == (1, [])
    assert way.tags["bicycle"] == "yes"


def test_an_access_override_may_not_write_outside_the_access_keys() -> None:
    """An override is a correction to what a rider may legally do, not a second
    tag editor. `highway` sets the hierarchy level an edge lands on, whether
    shortcuts are built over it, and whether a maneuver is emitted at all."""
    way = Way(1, highway="secondary")
    with pytest.raises(OverrideRefused, match="not an access key"):
        apply_access([way], [Override("access", 1, {"highway": "residential"})])
    assert way.tags["highway"] == "secondary", "and nothing was written"


def test_a_stress_override_replaces_the_tier_and_says_so() -> None:
    """After classification rather than before: there is no set of tags the rule
    "this road is LTS2, whatever the table says" corresponds to."""
    classified = {1: StressResult(Stress.LTS4, "mixed traffic, 35 mph or above", ("maxspeed",))}
    applied, unmatched = apply_stress(
        classified, [Override("stress", 1, {"tier": 2, "reason": "resurfaced with a shoulder"})]
    )
    assert (applied, unmatched) == (1, [])
    assert classified[1].tier is Stress.LTS2
    assert "override" in classified[1].rule
    assert "resurfaced with a shoulder" in classified[1].rule
    assert classified[1].assumed == ("maxspeed",), "the provenance of the inputs survives"


def test_a_jurisdiction_override_replaces_the_authority_assignment() -> None:
    way = Way(1, highway="secondary")
    way.tags["_jurisdictions"] = "Fairfax County"
    applied, _unmatched = apply_jurisdiction(
        [way], [Override("jurisdiction", 1, {"authorities": ["National Park Service"]})]
    )
    assert applied == 1
    assert way.tags["_jurisdictions"] == "National Park Service"


def test_a_jurisdiction_override_naming_nothing_is_refused() -> None:
    """Silently clearing the authority would read as "no authority applies",
    which is the one answer the jurisdiction layer must never invent."""
    with pytest.raises(OverrideRefused, match="names no authorities"):
        apply_jurisdiction([Way(1)], [Override("jurisdiction", 1, {"authorities": []})])


def test_an_override_matching_no_way_is_reported_rather_than_dropped() -> None:
    """An approved correction that reaches nothing is a correction that is not in
    force. The clip moved, or the way was replaced upstream, and either way
    someone needs told."""
    applied, unmatched = apply_access([Way(1)], [Override("access", 999, {"bicycle": "yes"})])
    assert (applied, unmatched) == (0, [999])


def test_each_kind_only_applies_to_its_own_stage() -> None:
    """The three kinds correct three different things and land in three different
    places; a stress row reaching the access stage would be a tag written from a
    tier."""
    rows = [
        Override("access", 1, {"bicycle": "yes"}),
        Override("stress", 1, {"tier": 1}),
        Override("jurisdiction", 1, {"authorities": ["DDOT"]}),
    ]
    way = Way(1, highway="secondary")
    assert apply_access([way], rows)[0] == 1
    assert apply_stress({1: StressResult(Stress.LTS3, "x")}, rows)[0] == 1
    assert apply_jurisdiction([way], rows)[0] == 1


@pytest.mark.django_db
def test_only_approved_rows_reach_the_pipeline() -> None:
    """Approval crosses guilds - a correction to a Virginia parkway is not
    Arlington's to make alone - so an unapproved row is a proposal, and a
    proposal that changed the graph while it waited would make the review
    meaningless. Filtered in the query, so no later stage can decide to apply
    one."""
    from core.models import Override as OverrideRow

    OverrideRow.objects.create(
        kind="access",
        osm_way_id=1,
        value={"bicycle": "yes"},
        reason="r",
        evidence="e",
        approved=True,
    )
    OverrideRow.objects.create(
        kind="access",
        osm_way_id=2,
        value={"bicycle": "yes"},
        reason="r",
        evidence="e",
    )

    loaded = load_approved()
    assert [row.osm_way_id for row in loaded] == [1]


@pytest.mark.django_db
def test_the_rebuild_stage_applies_every_kind_and_reports_what_it_did(tmp_path) -> None:
    """The wiring, not the functions. The stage sits after jurisdiction tagging
    and before the extract is written, which is the one position that is late
    enough for all three kinds and early enough for the graph."""
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, build_handlers

    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
    )
    way = Way(1, highway="secondary", bicycle="no")
    context.ways = [way]
    context.stress_by_way = {1: StressResult(Stress.LTS4, "mixed traffic, 35 mph or above")}

    rows = [
        Override("access", 1, {"bicycle": "yes"}),
        Override("stress", 1, {"tier": 2, "reason": "reviewed"}),
        Override("jurisdiction", 1, {"authorities": ["DDOT"]}),
    ]
    handlers = build_handlers(context, load_overrides=lambda: rows)
    handlers[Stage.APPLY_OVERRIDES]()

    assert way.tags["bicycle"] == "yes"
    assert context.stress_by_way[1].tier is Stress.LTS2
    assert way.tags["_jurisdictions"] == "DDOT"
    assert context.override_report.total == 3
    assert context.override_report.unmatched_way_ids == ()


def test_the_stage_runs_after_jurisdiction_tagging_and_before_the_extract_is_written() -> None:
    from pipeline.rebuild import Stage

    order = list(Stage)
    assert order.index(Stage.TAG_JURISDICTIONS) < order.index(Stage.APPLY_OVERRIDES)
    assert order.index(Stage.CLASSIFY_STRESS) < order.index(Stage.APPLY_OVERRIDES)
    assert order.index(Stage.APPLY_OVERRIDES) < order.index(Stage.INJECT_TAGS)
