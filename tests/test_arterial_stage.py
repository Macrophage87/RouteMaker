"""The rebuild's CLASSIFY_STRESS stage with the AADT smoothing and the named corridors
(OWNER-DECISIONS 285, 286, 294-296), on the real 1st Street NW and North Capitol
Street ways of the 2026-10-03 extract (tests/data)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import run as run_module
from pipeline.conflation import Match
from pipeline.extract import Way
from pipeline.overrides import Override
from pipeline.rebuild import Stage
from pipeline.run import RebuildContext, build_handlers
from routemaker.stress import Stress

DATA = Path(__file__).parent / "data"
FIRST_ST_WAY = 483241819


def load(name):
    return json.loads((DATA / name).read_text())


def make_context(tmp_path, monkeypatch, *, smooth=True) -> RebuildContext:
    first = load("first_street_nw.json")
    capitol = load("north_capitol_ways.json")
    ways = [
        Way(osm_id=r["id"], tags=dict(r["tags"]), node_ids=[], coordinates=r["coords"])
        for r in (*first, *capitol)
    ]
    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
        tiles_dir=tmp_path / "tiles",
    )
    context.ways = ways
    context.ways_by_id = {w.osm_id: w for w in ways}
    context.reference = SimpleNamespace(urban_way_ids={w.osm_id for w in ways}, road_blocks=[])
    context.aadt_by_way = {
        r["id"]: Match(
            osm_way_id=r["id"], feature_id="f", aadt=r["aadt"], source="count", year=2024,
            score=1.0, agency=r["agency"],
        )
        for r in first
    }  # fmt: skip
    context.smooth_volume = smooth
    monkeypatch.setattr(run_module.states, "state_polygons", lambda pbf: {})
    monkeypatch.setattr(
        run_module.states, "way_states", lambda ways, polygons: {w.osm_id: "DC" for w in ways}
    )
    return context


def classify(context, rows=()):
    handlers = build_handlers(context, load_overrides=lambda: list(rows))
    handlers[Stage.CLASSIFY_STRESS]()
    return handlers


def test_1st_street_nw_drops_from_lts_3_to_lts_2(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    assert context.aadt_by_way[FIRST_ST_WAY].aadt == 10665
    classify(context)
    result = context.stress_by_way[FIRST_ST_WAY]
    assert result.tier is Stress.LTS2
    assert result.volume_aadt == 7520, "the count the classifier read"
    assert "high volume" not in result.rule
    assert context.aadt_raw_by_way[FIRST_ST_WAY].aadt == 10665, "the agency's count is kept"
    assert FIRST_ST_WAY in {s.way_id for s in context.smoothing_report.replaced}


def test_the_owner_can_veto_smoothing(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch, smooth=False)
    classify(context)
    result = context.stress_by_way[FIRST_ST_WAY]
    assert result.tier is Stress.LTS3 and "high volume" in result.rule
    assert result.volume_aadt == 10665
    assert context.smoothing_report is None


def test_the_rule_says_when_the_street_median_crossed_a_volume_gate(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    classify(context)
    assert context.stress_by_way[FIRST_ST_WAY].rule.endswith(", street volume (median)")
    # A way whose count stands, or moved without crossing a gate, says nothing.
    unchanged = next(i for i, m in context.aadt_by_way.items() if m.raw_aadt is None)
    assert "median" not in context.stress_by_way[unchanged].rule


def test_a_count_lowered_within_a_band_is_not_marked(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    # 6,000 among its neighbours' 4,253: lowered, but 1,500 to 8,000 either way.
    old = context.aadt_by_way[345074765]
    context.aadt_by_way[345074765] = Match(**{**old.__dict__, "aadt": 6000})
    classify(context)
    assert context.aadt_by_way[345074765].aadt == 4253
    assert context.aadt_raw_by_way[345074765].aadt == 6000
    assert "median" not in context.stress_by_way[345074765].rule


def test_a_state_boundary_keeps_a_count_out_of_another_states_street(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    monkeypatch.setattr(
        run_module.states,
        "way_states",
        lambda ways, polygons: {w.osm_id: "VA" if w.osm_id == FIRST_ST_WAY else "DC" for w in ways},
    )
    classify(context)
    assert context.stress_by_way[FIRST_ST_WAY].volume_aadt == 10665


def test_north_capitol_underpasses_are_set_through_the_stage(tmp_path, monkeypatch, caplog) -> None:
    context = make_context(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger="pipeline.run"):
        classify(context)
    tiers = {i: int(r.tier) for i, r in context.stress_by_way.items()}
    assert tiers[130772891] == 5 and tiers[468472149] == 4 and tiers[122079300] == 4
    assert tiers[1501632583] == 3
    assert context.stress_by_way[130772891].rule.startswith("named corridor: north-capitol-st")
    assert context.corridor_report.changed
    assert any("named corridors:" in r.getMessage() for r in caplog.records)
    # The at-grade rest of the street keeps the rating the classifier gave it.
    at_grade = context.stress_by_way[623353237]
    assert "named corridor" not in at_grade.rule


def test_an_approved_override_outranks_a_named_corridor(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    row = Override(
        "stress",
        130772891,
        {
            "tier": 2,
            "adjustment_id": "owner-says-two",
            "category": "other",
            "visibility": "hidden",
            "annotation_status": "approved",
            "display": "route_only",
        },
    )
    handlers = classify(context, [row])
    assert context.stress_by_way[130772891].tier is Stress.AVOID
    handlers[Stage.APPLY_OVERRIDES]()
    assert context.stress_by_way[130772891].tier is Stress.LTS2


def test_corridors_that_match_nothing_are_warned_about(tmp_path, monkeypatch, caplog) -> None:
    context = make_context(tmp_path, monkeypatch)
    context.ways = [w for w in context.ways if "Capitol" not in (w.name or "")]
    context.ways_by_id = {w.osm_id: w for w in context.ways}
    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        classify(context)
    assert any("matched no way" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("smooth", [True, False])
def test_the_stage_is_a_no_op_for_ways_no_rule_touches(tmp_path, monkeypatch, smooth) -> None:
    context = make_context(tmp_path, monkeypatch, smooth=smooth)
    classify(context)
    southern = [
        i
        for i in context.stress_by_way
        if context.ways_by_id[i].tags.get("name", "").startswith("North Capitol")
        and context.ways_by_id[i].coordinates[0][1] > 38.935
    ]
    assert southern
    assert all("named corridor" not in context.stress_by_way[i].rule for i in southern)


def test_a_lane_the_agency_recorded_exempts_a_way_through_the_stage(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    tags = dict(context.ways_by_id[130772891].tags)
    context.class_tags_by_way[130772891] = {**tags, "cycleway:both": "track"}
    classify(context)
    assert context.stress_by_way[130772891].tier is Stress.LTS3
    assert context.stress_by_way[920784194].tier is Stress.AVOID
