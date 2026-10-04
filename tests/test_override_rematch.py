"""Re-matching an override whose way left the extract (OWNER-DECISIONS 282)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from pipeline import rematch
from pipeline.overrides import Override
from routemaker.stress import Stress, StressResult

OVERRIDES = Path(__file__).resolve().parents[1] / "fixtures" / "overrides"
M_PER_DEG = 111_195.0
LON0, LAT0 = -76.60, 39.30


@dataclass
class W:
    osm_id: int
    tags: dict
    coordinates: list = field(default_factory=list)


def line(east_m, north_m, length_m, bearing="n"):
    """Two points: from (east_m, north_m) of the origin, `length_m` north or east."""
    lon = LON0 + east_m / 86_000.0
    lat = LAT0 + north_m / M_PER_DEG
    if bearing == "n":
        return [[lon, lat], [lon, lat + length_m / M_PER_DEG]]
    return [[lon, lat], [lon + length_m / 86_000.0, lat]]


def way(osm_id, coords, name="Harford Road", highway="primary", **tags):
    out = {"highway": highway, **tags}
    if name:
        out["name"] = name
    return W(osm_id, out, coords)


def stress_row(way_id, tier=1, adjustment="harford-lts1"):
    return Override(
        "stress",
        way_id,
        {
            "tier": tier,
            "adjustment_id": adjustment,
            "category": "other",
            "visibility": "hidden",
            "annotation_status": "approved",
            "display": "route_only",
        },
    )


def old_way():
    return way(1, line(0, 0, 90))


def fingerprint():
    return rematch.fingerprint_of(old_way().tags, old_way().coordinates)


def by_id(*ways):
    return {w.osm_id: w for w in ways}


# --- Fingerprints -----------------------------------------------------------


def test_a_fingerprint_is_name_class_length_and_a_compact_line() -> None:
    fp = fingerprint()
    assert fp["name"] == "Harford Road" and fp["highway"] == "primary"
    assert fp["length_m"] == pytest.approx(90, abs=0.5)
    assert rematch.fingerprint_problem(fp) is None
    assert len(rematch.parse_line(fp["line"])) == 2


def test_a_fingerprint_simplifies_a_long_way_but_keeps_its_shape() -> None:
    coords = [[LON0 + i * 0.00002, LAT0 + (0.00001 if i % 7 == 0 else 0)] for i in range(200)]
    coords += [[coords[-1][0] + 0.0001 * k, LAT0 + 0.0001 * k] for k in range(1, 8)]
    fp = rematch.fingerprint_of({"highway": "secondary"}, coords)
    kept = rematch.parse_line(fp["line"])
    assert fp["name"] is None
    assert 3 <= len(kept) < len(coords) / 3, "the bend is kept"
    assert kept[0] == pytest.approx(tuple(coords[0]), abs=1e-6)
    assert kept[-1] == pytest.approx(tuple(coords[-1]), abs=1e-6)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "x",
        {"name": "A"},
        {"name": 1, "highway": "primary", "length_m": 1, "line": "0,0 1,1"},
        {"name": "A", "highway": "primary", "length_m": 0, "line": "0,0 1,1"},
        {"name": "A", "highway": "primary", "length_m": 5, "line": "0,0"},
        {"name": "A", "highway": "primary", "length_m": 5, "line": "0,0 1,x"},
        {"name": "A", "highway": "primary", "length_m": 5, "line": "0,0 1,95"},
        {"name": "A", "highway": "primary", "length_m": 5, "line": ["0,0", "1,1"]},
        {"name": "A", "highway": "primary", "length_m": 5, "line": "0,0 1,1", "extra": 1},
    ],
)
def test_a_malformed_fingerprint_is_refused(bad) -> None:
    assert rematch.fingerprint_problem(bad)


# --- find: when a re-match is applied ---------------------------------------


def test_a_way_split_in_three_matches_all_three_pieces() -> None:
    pieces = [
        way(11, line(0, 0, 30)),
        way(12, line(0, 30, 30)),
        way(13, line(0, 60, 30)),
    ]
    match = rematch.find(fingerprint(), pieces)
    assert match.way_ids == (11, 12, 13) and match.ok


def test_it_tolerates_the_nodes_having_moved_a_few_metres() -> None:
    moved = [way(11, line(3, 0, 45)), way(12, line(-3, 45, 45))]
    assert rematch.find(fingerprint(), moved).way_ids == (11, 12)
    too_far = [way(11, line(20, 0, 45)), way(12, line(20, 45, 45))]
    assert not rematch.find(fingerprint(), too_far).ok


def test_the_street_name_must_match_but_not_the_quadrant() -> None:
    assert rematch.find(fingerprint(), [way(11, line(0, 0, 90), name="Harford Road")]).ok
    renamed = rematch.find(fingerprint(), [way(11, line(0, 0, 90), name="Belair Road")])
    assert not renamed.ok and "name" in renamed.reason
    unnamed = rematch.find(fingerprint(), [way(11, line(0, 0, 90), name=None)])
    assert not unnamed.ok
    fp = rematch.fingerprint_of(
        {"highway": "primary", "name": "N Capitol Street Northwest"}, line(0, 0, 90)
    )
    assert rematch.find(fp, [way(11, line(0, 0, 90), name="N Capitol Street NW")]).ok


def test_an_unnamed_way_matches_only_unnamed_ways_of_its_class() -> None:
    footway = way(1, line(0, 0, 90), name=None, highway="footway")
    fp = rematch.fingerprint_of(footway.tags, footway.coordinates)
    assert fp["name"] is None
    assert rematch.find(fp, [way(11, line(0, 0, 90), name=None, highway="footway")]).ok
    assert not rematch.find(fp, [way(11, line(0, 0, 90), name=None, highway="path")]).ok
    assert not rematch.find(fp, [way(11, line(0, 0, 90), name="Trail", highway="footway")]).ok


def test_a_way_that_runs_on_beyond_the_line_is_not_a_match() -> None:
    """The old way was merged into a longer one: applying the row to all of it would
    reach further than was decided."""
    merged = way(11, line(0, -200, 400))
    match = rematch.find(fingerprint(), [merged])
    assert not match.ok and "11" in match.reason


def test_half_a_street_is_not_a_match() -> None:
    match = rematch.find(fingerprint(), [way(11, line(0, 0, 30)), way(12, line(0, 60, 30))])
    assert not match.ok


def test_two_ways_side_by_side_are_not_one_answer() -> None:
    """Two carriageways within tolerance of one centreline: two answers, so none."""
    pair = [way(11, line(-2, 0, 90)), way(12, line(2, 0, 90))]
    match = rematch.find(fingerprint(), pair)
    assert not match.ok and "side by side" in match.reason


def test_a_junction_stub_of_the_same_name_that_overlaps_the_line_is_ambiguous() -> None:
    """More than an end-on neighbour overlaps: the junction was redrawn, so applying
    the row to the rest would be a guess (the Harford Road case, way 1562097553)."""
    pieces = [way(11, line(0, 0, 90))]
    redrawn = way(12, line(0, 60, 50))
    match = rematch.find(fingerprint(), [*pieces, redrawn])
    assert not match.ok and "12" in match.reason


def test_an_end_on_neighbour_does_not_spoil_a_clean_split() -> None:
    pieces = [way(11, line(0, 0, 45)), way(12, line(0, 45, 45))]
    neighbour = way(13, line(0, 90, 120))
    before = way(14, line(0, -120, 120))
    assert rematch.find(fingerprint(), [*pieces, neighbour, before]).way_ids == (11, 12)


def test_nothing_nearby_is_a_failure_with_a_reason() -> None:
    match = rematch.find(fingerprint(), [way(11, line(0, 5000, 90))])
    assert not match.ok and match.reason


# --- resolve: the rows of a rebuild -----------------------------------------


def test_a_present_way_passes_through_untouched() -> None:
    row = replace(stress_row(1), fingerprint=fingerprint())
    rows, report = rematch.resolve([row], by_id(old_way()))
    assert rows == [row] and not report.rematched and not report.failed


def test_a_missing_way_is_repointed_at_every_piece() -> None:
    row = replace(stress_row(1), fingerprint=fingerprint())
    pieces = by_id(way(11, line(0, 0, 45)), way(12, line(0, 45, 45)))
    rows, report = rematch.resolve([row], pieces)
    assert [(r.osm_way_id, r.value) for r in rows] == [(11, row.value), (12, row.value)]
    (entry,) = report.rematched
    assert (entry.old_way_id, entry.new_way_ids, entry.kind) == (1, (11, 12), "stress")
    assert "1 re-matched" in report.summary()


def test_the_fingerprint_can_come_from_the_fixtures_by_kind_and_way() -> None:
    row = stress_row(1)
    pieces = by_id(way(11, line(0, 0, 90)))
    rows, _ = rematch.resolve([row], pieces, {("stress", 1): fingerprint()})
    assert [r.osm_way_id for r in rows] == [11]
    rows, report = rematch.resolve([row], pieces, {("access", 1): fingerprint()})
    assert rows == [row] and "no fingerprint" in report.failed[0].reason


def test_a_failed_row_is_left_exactly_as_it_was_and_named() -> None:
    row = replace(stress_row(1), fingerprint=fingerprint())
    ambiguous = by_id(way(11, line(-2, 0, 90)), way(12, line(2, 0, 90)))
    rows, report = rematch.resolve([row], ambiguous)
    assert rows == [row], "never silently dropped, never re-pointed on a guess"
    (entry,) = report.failed
    assert entry.old_way_id == 1 and entry.new_way_ids == () and entry.reason
    text = report.summary()
    assert "1 failed" in text and "stress 1" in text


def test_rows_with_no_fingerprint_fail_loudly_rather_than_vanish() -> None:
    rows, report = rematch.resolve([stress_row(1)], by_id(way(11, line(0, 0, 90))))
    assert rows[0].osm_way_id == 1
    assert report.failed[0].reason.startswith("no fingerprint")


def test_a_target_that_already_has_the_same_row_is_covered() -> None:
    """The re-pointed fixture row is already loaded on the new way: the stale row has
    nothing left to do."""
    stale = replace(stress_row(1), fingerprint=fingerprint())
    loaded = stress_row(11)
    pieces = by_id(way(11, line(0, 0, 90)))
    rows, report = rematch.resolve([stale, loaded], pieces)
    assert [r.osm_way_id for r in rows] == [11]
    assert [e.outcome for e in report.entries] == ["covered"]
    assert not report.failed


def test_a_target_with_a_different_row_is_a_conflict_not_an_overwrite() -> None:
    stale = replace(stress_row(1, tier=1), fingerprint=fingerprint())
    other = stress_row(11, tier=4, adjustment="other")
    rows, report = rematch.resolve([stale, other], by_id(way(11, line(0, 0, 90))))
    assert sorted(r.osm_way_id for r in rows) == [1, 11]
    assert "different value" in report.failed[0].reason


def test_two_missing_rows_claiming_one_way_with_different_values_both_fail() -> None:
    a = replace(stress_row(1, tier=1), fingerprint=fingerprint())
    b = replace(stress_row(2, tier=4, adjustment="b"), fingerprint=fingerprint())
    rows, report = rematch.resolve([a, b], by_id(way(11, line(0, 0, 90))))
    assert [r.osm_way_id for r in rows] == [1, 2]
    assert len(report.failed) == 2


def test_two_missing_rows_with_the_same_value_do_not_duplicate_the_target() -> None:
    a = replace(stress_row(1), fingerprint=fingerprint())
    b = replace(stress_row(2), fingerprint=fingerprint())
    rows, report = rematch.resolve([a, b], by_id(way(11, line(0, 0, 90))))
    assert [r.osm_way_id for r in rows] == [11]
    assert len(report.rematched) == 2


def test_kinds_are_re_matched_independently() -> None:
    access = Override("access", 1, {"bicycle": "yes"}, fingerprint=fingerprint())
    stress = replace(stress_row(1), fingerprint=fingerprint())
    rows, _ = rematch.resolve([access, stress], by_id(way(11, line(0, 0, 90))))
    assert sorted((r.kind, r.osm_way_id) for r in rows) == [("access", 11), ("stress", 11)]


def test_a_present_way_that_no_longer_looks_like_its_fingerprint_is_reported_drifted() -> None:
    row = replace(stress_row(1), fingerprint=fingerprint())
    drifted = by_id(way(1, line(500, 0, 90)))
    rows, report = rematch.resolve([row], drifted)
    assert rows == [row], "it still applies where the id is"
    assert [e.outcome for e in report.entries] == ["drifted"]
    renamed = by_id(way(1, line(0, 0, 90), name="Belair Road"))
    assert rematch.resolve([row], renamed)[1].entries[0].outcome == "drifted"


def test_the_report_lists_every_missing_row_and_writes_markdown_and_csv() -> None:
    ok = replace(stress_row(1), fingerprint=fingerprint())
    gone = replace(
        stress_row(2),
        fingerprint=rematch.fingerprint_of(
            {"highway": "primary", "name": "Elsewhere"}, line(900, 0, 60)
        ),
    )
    rows, report = rematch.resolve([ok, gone], by_id(way(11, line(0, 0, 90))))
    assert [e.outcome for e in report.entries] == ["failed", "rematched"]
    md, csv_text = report.to_markdown(), report.to_csv()
    assert "| stress | 2 | failed |" in md and "| stress | 1 | rematched | 11 |" in md
    assert csv_text.splitlines()[0] == "kind,old_way_id,outcome,new_way_ids,name,reason"
    assert len(csv_text.splitlines()) == 3 and rows
    empty = rematch.resolve([replace(stress_row(1), fingerprint=fingerprint())], by_id(old_way()))[
        1
    ]
    assert "Every override row's way is in the extract" in empty.to_markdown()


# --- The fixtures -------------------------------------------------------------


def fixture_documents():
    return {p.name: json.loads(p.read_text()) for p in sorted(OVERRIDES.glob("2026-*.json"))}


def test_every_row_of_every_override_file_carries_a_valid_fingerprint() -> None:
    """Stored with each override so a re-match is possible later (decision 282b)."""
    documents = fixture_documents()
    assert sum(len(d["rows"]) for d in documents.values()) == 1785
    for name, document in documents.items():
        for row in document["rows"]:
            assert rematch.fingerprint_problem(row.get("fingerprint")) is None, (
                name,
                row["osm_way_id"],
            )


def test_the_override_counts_the_owner_asked_about() -> None:
    kinds = [row["kind"] for d in fixture_documents().values() for row in d["rows"]]
    assert kinds.count("access") == 232
    # 1,551 stress rows, and decision 282a turned one into three.
    assert kinds.count("stress") == 1551 - 1 + 3


def test_the_harford_road_row_is_repointed_at_the_three_ways() -> None:
    document = fixture_documents()["2026-10-01-owner-baltimore-facilities.json"]
    stress = {r["osm_way_id"]: r for r in document["rows"] if r["kind"] == "stress"}
    assert 424993005 not in stress
    new = {1562097553, 1562097555, 1562097556}
    assert new <= set(stress)
    values = {json.dumps(stress[i]["value"], sort_keys=True) for i in new}
    assert len(values) == 1
    assert stress[1562097553]["value"]["tier"] == 1
    assert stress[1562097553]["value"]["adjustment_id"] == "baltimore-track-harford-rd-lts1"
    for way_id in new:
        assert "record 634" in stress[way_id]["evidence"]
        assert "424993005" in stress[way_id]["evidence"]
    (moved,) = document["superseded"]
    assert moved["osm_way_id"] == 424993005 and sorted(moved["replaced_by"]) == sorted(new)
    assert rematch.fingerprint_problem(moved["fingerprint"]) is None
    assert rematch.load_fingerprints()[("stress", 424993005)] == moved["fingerprint"]


def test_the_harford_ways_lie_along_open_baltimore_record_634() -> None:
    """Decision 282a: verified against the City's geometry (the record's line, copied
    from the layer the owner approved, in tests/data)."""
    record = json.loads(
        (Path(__file__).parent / "data" / "open_baltimore_record_634.json").read_text()
    )
    target = rematch._Line(record["coordinates"], 39.35)
    document = fixture_documents()["2026-10-01-owner-baltimore-facilities.json"]
    for row in document["rows"]:
        if row["osm_way_id"] in (1562097553, 1562097555, 1562097556):
            pts = rematch.parse_line(row["fingerprint"]["line"])
            samples = rematch._Line(pts, 39.35).samples()
            assert max(target.distance(s) for s in samples) < 10.0, row["osm_way_id"]


def test_the_fixture_fingerprints_load_by_kind_and_way() -> None:
    found = rematch.load_fingerprints()
    assert len(found) == 1785 + 1
    assert ("access", 50426889) in found and ("stress", 1562097556) in found


def test_a_malformed_fingerprint_in_a_file_refuses_the_load(tmp_path) -> None:
    (tmp_path / "2026-x.json").write_text(
        json.dumps({"rows": [{"kind": "stress", "osm_way_id": 5, "fingerprint": {"name": "A"}}]})
    )
    with pytest.raises(rematch.FingerprintRefused):
        rematch.load_fingerprints(tmp_path)


def test_load_approved_attaches_the_fixtures_fingerprints() -> None:
    from pipeline.overrides import load_approved

    class Row:
        def __init__(self, kind, way):
            self.kind, self.osm_way_id, self.value, self.reason = kind, way, {"tier": 1}, ""

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, **kwargs):
            return self

        def order_by(self, *args):
            return self.rows

    class Model:
        objects = Query([Row("stress", 424993005), Row("access", 50426889), Row("stress", 1)])

    loaded = load_approved(Model)
    assert loaded[0].fingerprint["name"] == "Harford Road"
    assert loaded[1].fingerprint["highway"] == "trunk"
    assert loaded[2].fingerprint is None


# --- Through the rebuild stage --------------------------------------------------


def context_with(tmp_path, ways, stress):
    from pipeline.run import RebuildContext

    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
    )
    context.ways = ways
    context.ways_by_id = {w.osm_id: w for w in ways}
    context.stress_by_way = stress
    return context


@dataclass
class StageWay(W):
    source_tags: dict = field(default_factory=dict)


def test_the_stage_re_points_a_split_way_and_writes_the_report(tmp_path) -> None:
    from pipeline.rebuild import Stage
    from pipeline.run import build_handlers

    ways = [
        StageWay(11, {"highway": "primary", "name": "Harford Road"}, line(0, 0, 45)),
        StageWay(12, {"highway": "primary", "name": "Harford Road"}, line(0, 45, 45)),
        StageWay(20, {"highway": "primary", "name": "Elsewhere Road"}, line(3000, 0, 45)),
    ]
    stress = {w.osm_id: StressResult(Stress.LTS3, "x") for w in ways}
    context = context_with(tmp_path, ways, stress)
    gone = rematch.fingerprint_of({"highway": "primary", "name": "Lost Road"}, line(9000, 0, 60))
    rows = [
        replace(stress_row(1, tier=1), fingerprint=fingerprint()),
        replace(stress_row(2, tier=2, adjustment="lost"), fingerprint=gone),
        stress_row(20, tier=2, adjustment="elsewhere"),
    ]
    build_handlers(context, load_overrides=lambda: rows)[Stage.APPLY_OVERRIDES]()

    assert context.stress_by_way[11].tier is Stress.LTS1
    assert context.stress_by_way[12].tier is Stress.LTS1
    assert context.stress_by_way[20].tier is Stress.LTS2
    report = context.override_report
    assert (report.stress, report.rematched, report.rematch_failed) == (3, 1, 1)
    assert report.unmatched_way_ids == (2,), "the failed row is still listed as unmatched"
    assert "1 rows re-matched to new ways by geometry and name, 1 could not be" in report.summary()
    reports = tmp_path / "work" / "reports"
    assert "| stress | 1 | rematched | 11 12 |" in (reports / "override-rematch.md").read_text()
    assert "stress,2,failed" in (reports / "override-rematch.csv").read_text()


def test_the_stage_with_nothing_missing_still_writes_an_empty_report(tmp_path) -> None:
    from pipeline.rebuild import Stage
    from pipeline.run import build_handlers

    ways = [StageWay(1, {"highway": "primary", "name": "Harford Road"}, line(0, 0, 90))]
    context = context_with(tmp_path, ways, {1: StressResult(Stress.LTS3, "x")})
    rows = [replace(stress_row(1), fingerprint=fingerprint())]
    build_handlers(context, load_overrides=lambda: rows)[Stage.APPLY_OVERRIDES]()
    assert context.override_report.rematched == 0
    assert (
        "Every override row's way is in the extract"
        in (tmp_path / "work" / "reports" / "override-rematch.md").read_text()
    )


def test_the_loader_checks_a_rows_fingerprint(tmp_path) -> None:
    from django.core.management.base import CommandError

    from core.management.commands.load_access_overrides import parse_file

    row = {
        "kind": "access",
        "osm_way_id": 5,
        "value": {"bicycle": "yes"},
        "reason": "r",
        "evidence": "e",
        "fingerprint": fingerprint(),
    }
    assert parse_file(json.dumps({"version": 1, "rows": [row]}), "f") == [row]
    bad = {**row, "fingerprint": {"name": "x"}}
    with pytest.raises(CommandError, match="fingerprint"):
        parse_file(json.dumps({"version": 1, "rows": [bad]}), "f")
    plain = {k: v for k, v in row.items() if k != "fingerprint"}
    assert parse_file(json.dumps({"version": 1, "rows": [plain]}), "f")


def test_the_backfill_script_adds_fingerprints_and_keeps_each_files_indent(tmp_path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "backfill",
        OVERRIDES.parents[1] / "scripts" / "analysis" / "backfill_override_fingerprints.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ways = tmp_path / "ways.jsonl"
    coords = line(0, 0, 90)
    ways.write_text(
        json.dumps({"id": 7, "t": {"highway": "primary", "name": "Harford Road"}, "c": coords})
        + "\n"
    )
    files = tmp_path / "overrides"
    files.mkdir()
    rows = [
        {"kind": "stress", "osm_way_id": 7, "value": {"tier": 1}, "reason": "r", "evidence": "e"},
        {"kind": "stress", "osm_way_id": 8, "value": {"tier": 1}, "reason": "r", "evidence": "e"},
    ]
    path = files / "2026-x.json"
    path.write_text(json.dumps({"version": 1, "rows": rows}, indent=1) + "\n")
    import sys

    sys.argv = ["x", "--ways-jsonl", str(ways), "--overrides", str(files), "--write"]
    assert module.main() == 0
    raw = path.read_text()
    written = json.loads(raw)["rows"]
    assert written[0]["fingerprint"]["name"] == "Harford Road"
    assert "fingerprint" not in written[1], "a way missing from the extract is listed, not invented"
    assert raw == json.dumps(json.loads(raw), indent=1) + "\n", "the file's own indent is kept"
