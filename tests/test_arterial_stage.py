"""The rebuild's CLASSIFY_STRESS stage with the AADT smoothing and the named corridors
(OWNER-DECISIONS 285, 286, 294-296), on the real 1st Street NW and North Capitol
Street ways of the 2026-10-03 extract (tests/data)."""

from __future__ import annotations

import csv
import dataclasses
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import run as run_module
from pipeline import writers
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


def four_lanes(context) -> None:
    """The block as a 30 mph street of two lanes each way: the one place in Furth v2.2's
    mixed-traffic table where 10,665 and 7,520 vehicles a day read differently (the 8,001
    break of the two-lanes-a-direction row). As mapped, one lane each way at 25 mph, the
    block is LTS 3 on either count."""
    context.ways_by_id[FIRST_ST_WAY].tags.update({"lanes": "4", "maxspeed": "30 mph"})


def test_1st_street_nw_is_classified_on_the_street_median(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    assert context.aadt_by_way[FIRST_ST_WAY].aadt == 10665
    classify(context)
    result = context.stress_by_way[FIRST_ST_WAY]
    # One lane each way at 25 mph is LTS 3 from 1,501 a day up (Furth v2.2), so the
    # median no longer moves this block; it is still what the block was classified on.
    assert result.tier is Stress.LTS3
    assert result.rule.endswith("street volume (median)")
    assert context.aadt_raw_by_way[FIRST_ST_WAY].aadt == 10665, "the agency's count is kept"
    assert FIRST_ST_WAY in {s.way_id for s in context.smoothing_report.replaced}


def test_a_median_under_the_multilane_break_lowers_the_link(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    four_lanes(context)
    classify(context)
    result = context.stress_by_way[FIRST_ST_WAY]
    assert result.tier is Stress.LTS3
    assert "low volume" in result.rule


def test_the_published_count_is_the_agencys_not_the_median(tmp_path, monkeypatch) -> None:
    """`segment.volume_aadt` says what DDOT counted (10,665), not the 7,520 the link was
    classified on (ARTERIAL review r0, SF1: the schema documents it as the agency's
    count, beside `volume_source` and `volume_year`)."""
    context = make_context(tmp_path, monkeypatch)
    classify(context)
    result = context.stress_by_way[FIRST_ST_WAY]
    assert result.volume_aadt == 10665
    assert (result.volume_source, result.volume_year) == ("ddot", 2024)
    row = writers.segment_row(FIRST_ST_WAY, 0, [(-77.0, 38.9), (-77.0, 38.901)], result)
    assert row["stress"].volume_aadt == 10665
    # A way whose count was not replaced keeps it, and has no pre-smoothing tier.
    unchanged = next(i for i, m in context.aadt_by_way.items() if m.raw_aadt is None)
    kept = context.stress_by_way[unchanged]
    assert kept.volume_aadt == context.aadt_by_way[unchanged].aadt
    assert kept.unsmoothed_tier is None


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
    # 4,900 among its neighbours' 4,253: lowered, but 1,501 to 4,999 either way
    # (5,000 is the busy-street gate, so a count above it would cross one).
    old = context.aadt_by_way[345074765]
    context.aadt_by_way[345074765] = Match(**{**old.__dict__, "aadt": 4900})
    classify(context)
    assert context.aadt_by_way[345074765].aadt == 4253
    assert context.aadt_raw_by_way[345074765].aadt == 4900
    assert "median" not in context.stress_by_way[345074765].rule
    # The tier did not move, so the junction has no other tier to read.
    assert context.stress_by_way[345074765].unsmoothed_tier is None
    assert context.stress_by_way[345074765].volume_aadt == 4900


def test_a_state_boundary_keeps_a_count_out_of_another_states_street(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch)
    monkeypatch.setattr(
        run_module.states,
        "way_states",
        lambda ways, polygons: {w.osm_id: "VA" if w.osm_id == FIRST_ST_WAY else "DC" for w in ways},
    )
    four_lanes(context)
    classify(context)
    # Alone in its state the block keeps its own 10,665: over the 8,001 break, LTS 4.
    assert context.stress_by_way[FIRST_ST_WAY].tier is Stress.LTS4
    assert context.stress_by_way[FIRST_ST_WAY].unsmoothed_tier is None
    assert FIRST_ST_WAY not in {s.way_id for s in context.smoothing_report.replaced}


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


def test_the_stage_writes_the_smoothing_and_corridor_reports(tmp_path, monkeypatch) -> None:
    """Beside the re-match report, under `<DATA_ROOT>/rebuild/reports/` (ARTERIAL review
    r0, SF4): each replaced count with both tiers, and every corridor way."""
    context = make_context(tmp_path, monkeypatch)
    classify(context)
    reports = context.work_dir / "reports"
    rows = list(csv.DictReader((reports / "aadt-smoothing.csv").open()))
    first = next(r for r in rows if r["way_id"] == str(FIRST_ST_WAY))
    assert (first["raw_aadt"], first["smoothed_aadt"]) == ("10665", "7520")
    assert (first["link_tier"], first["tier_on_raw_count"]) == ("3", "3")
    assert first["crosses_volume_gate"] == "yes"
    assert len(rows) == len(context.smoothing_report.replaced)
    corridor = (reports / "named-corridors.md").read_text()
    row = "| 130772891 | north-capitol-st | first-underpass-through | through | 3 | 5 |"
    assert row in corridor
    assert "named corridors:" in corridor


def test_with_the_veto_the_smoothing_report_is_empty_not_stale(tmp_path, monkeypatch) -> None:
    context = make_context(tmp_path, monkeypatch, smooth=False)
    stale = context.work_dir / "reports" / "aadt-smoothing.csv"
    stale.parent.mkdir(parents=True)
    stale.write_text("way_id\n1\n")
    classify(context)
    assert stale.read_text().splitlines() == [
        "way_id,street,raw_aadt,smoothed_aadt,ways_in_window,window_length_m,"
        "crosses_volume_gate,link_tier,tier_on_raw_count"
    ]


def test_a_named_corridor_sets_the_junctions_tier_too(tmp_path, monkeypatch) -> None:
    """A corridor tier is the owner's judgement of the way; a pre-smoothing tier no
    longer describes it."""
    context = make_context(tmp_path, monkeypatch)
    handlers = build_handlers(context, load_overrides=lambda: [])
    original = run_module.corridors.apply

    def with_a_stale_tier(corridor_list, ways, stress_by_way, **kwargs):
        stress_by_way[130772891] = dataclasses.replace(
            stress_by_way[130772891], unsmoothed_tier=Stress.LTS4
        )
        return original(corridor_list, ways, stress_by_way, **kwargs)

    monkeypatch.setattr(run_module.corridors, "apply", with_a_stale_tier)
    handlers[Stage.CLASSIFY_STRESS]()
    assert context.stress_by_way[130772891].tier is Stress.AVOID
    assert context.stress_by_way[130772891].unsmoothed_tier is None
