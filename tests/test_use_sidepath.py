"""Roads tagged `bicycle=use_sidepath` (review RL-1; the owner, 2026-10-16: "It's very
much not recommended, but I believe still legal", and "For the use-sidepath roads, make
sure there's a sidepath marked."): legal and drawn; Avoid where a side path is mapped
beside them, their own rating and a report row where none is."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import segment_info
from pipeline import run as run_module
from pipeline.extract import Way
from pipeline.overrides import Override
from pipeline.rebuild import Stage
from pipeline.run import USE_SIDEPATH_REPORT_NAME, RebuildContext, build_handlers
from routemaker import agency_lts, facility
from routemaker.stress import USE_SIDEPATH_RULE, Stress, classify, motor_restriction

ROAD = {
    "highway": "secondary",
    "name": "Test Road",
    "maxspeed": "25 mph",
    "lanes": "2",
    "bicycle": "use_sidepath",
}


def line(lat: float, lon0: float = -77.0, lon1: float = -76.995) -> list[tuple[float, float]]:
    return [(lon0, lat), ((lon0 + lon1) / 2, lat), (lon1, lat)]


# A road at each latitude; 0.00012 degrees of latitude is about 13 m.
WITH_PATH = 1  # a named cycleway alongside
NO_PATH = 2  # nothing alongside
FOOTWAY_ONLY = 3  # a footway bicycles may not use alongside
SIDEWALK = 4  # an unnamed shared-use sidewalk alongside
CROSSING = 5  # only a path that crosses it
FAR = 6  # a cycleway 50 m away
PLAIN = 7  # a road with no bicycle tag, a cycleway alongside (Benning Road's case)


def ways() -> list[tuple[int, dict[str, str], list[tuple[float, float]]]]:
    return [
        (WITH_PATH, dict(ROAD), line(38.90)),
        (101, {"highway": "cycleway", "name": "Riverwalk Trail"}, line(38.90012)),
        (NO_PATH, dict(ROAD), line(38.91)),
        (FOOTWAY_ONLY, dict(ROAD), line(38.92)),
        (103, {"highway": "footway", "footway": "sidewalk"}, line(38.92012)),
        (SIDEWALK, dict(ROAD), line(38.93)),
        (
            104,
            {"highway": "footway", "footway": "sidewalk", "bicycle": "yes"},
            line(38.93012),
        ),
        (CROSSING, dict(ROAD), line(38.94)),
        (105, {"highway": "cycleway"}, [(-76.9975, 38.9395), (-76.9975, 38.9405)]),
        (FAR, dict(ROAD), line(38.95)),
        (106, {"highway": "cycleway"}, line(38.95045)),
        (PLAIN, {k: v for k, v in ROAD.items() if k != "bicycle"}, line(38.96)),
        (107, {"highway": "cycleway"}, line(38.96012)),
    ]


class TestTheSidePathMatch:
    def test_which_roads_have_a_side_path_and_its_name(self) -> None:
        found, missing = facility.use_sidepath_paths(ways())
        assert found == {WITH_PATH: "Riverwalk Trail", SIDEWALK: None}
        assert missing == {NO_PATH, FOOTWAY_ONLY, CROSSING, FAR}

    def test_a_path_along_part_of_the_road_is_not_enough(self) -> None:
        short = [
            (1, dict(ROAD), line(38.90)),
            (2, {"highway": "cycleway"}, line(38.90012, -77.0, -76.999)),
        ]
        assert facility.use_sidepath_paths(short) == ({}, {1})

    def test_the_report_lists_way_name_county_and_state(self) -> None:
        text = facility.use_sidepath_report_csv(
            [(9, "Main Street, North", "Montgomery, MD", "MD"), (3, "Elm", "", "DC")]
        )
        rows = list(csv.reader(text.splitlines()))
        assert rows == [
            ["way_id", "name", "county", "state"],
            ["3", "Elm", "", "DC"],
            ["9", "Main Street, North", "Montgomery, MD", "MD"],
        ]


class TestTheRating:
    def test_with_a_side_path_it_is_avoid(self) -> None:
        result = classify(ROAD, side_path=True)
        assert result.tier is Stress.AVOID
        assert result.rule.startswith(USE_SIDEPATH_RULE)

    def test_without_one_it_is_rated_on_its_own_merits(self) -> None:
        plain = {k: v for k, v in ROAD.items() if k != "bicycle"}
        result = classify(ROAD)
        assert result.tier is classify(plain).tier
        assert result.tier is not Stress.AVOID

    def test_a_side_path_alone_makes_no_other_road_avoid(self) -> None:
        plain = {k: v for k, v in ROAD.items() if k != "bicycle"}
        assert classify(plain, side_path=True).tier is classify(plain).tier

    def test_a_motor_restriction_caps_it_as_any_road_open_to_bicycles(self) -> None:
        tags = {"highway": "unclassified", "motor_vehicle": "private", "bicycle": "use_sidepath"}
        assert motor_restriction(tags) == (Stress.LTS2, "motor_vehicle=private")

    def test_an_agency_rating_outranks_it(self) -> None:
        rating = agency_lts.AgencyRating(agency="moco", level=3.0)
        result = agency_lts.apply(classify(ROAD, side_path=True), [rating])
        assert result.tier is Stress.LTS3


class TestTheMapAndPanel:
    def test_it_is_drawn_as_a_road(self) -> None:
        assert facility.map_class(ROAD) is facility.MapClass.ROAD

    def test_the_access_reason_only_where_a_side_path_is_mapped(self) -> None:
        assert facility.bike_access_reason(ROAD, side_path=True) == "bicycle_use_sidepath"
        assert facility.bike_access_reason(ROAD) is None

    def test_the_panel_says_legal_and_names_the_side_path(self) -> None:
        row = {
            "bike_access_reason": "bicycle_use_sidepath",
            "sidepath_name": "Riverwalk Trail",
            "is_trail_class": False,
        }
        open_, rows = segment_info.access_rows(row, None)
        assert open_ is True
        assert rows[0]["value"] == (
            "Legal, but riders are asked to use the side path: Riverwalk Trail"
        )
        open_, rows = segment_info.access_rows({**row, "sidepath_name": None}, True)
        assert rows[0]["value"] == "Legal, but riders are asked to use the side path"

    def test_the_summary_and_the_why(self) -> None:
        row = {
            "osm_way_id": 1,
            "stress_tier": 5,
            "stress_rule": f"{USE_SIDEPATH_RULE} (Furth: mixed traffic, 25 mph)",
            "bike_access_reason": "bicycle_use_sidepath",
            "sidepath_name": "Riverwalk Trail",
            "is_trail_class": False,
        }
        summary = {r["id"]: r["value"] for r in segment_info.summary_rows(row, {}, True)}
        assert summary["bikes"] == (
            "Legal, but riders are asked to use the side path: Riverwalk Trail"
        )
        assert summary["why"] == "Avoid: riders are asked to use the side path"

    def test_the_side_path_is_never_the_roads_own_name(self) -> None:
        row = {
            "osm_way_id": 1,
            "stress_tier": 5,
            "stress_rule": USE_SIDEPATH_RULE,
            "stress_assumed": None,
            "volume_source": None,
            "volume_aadt": None,
            "volume_year": None,
            "bike_access_reason": "bicycle_use_sidepath",
            "sidepath_name": "Riverwalk Trail",
            "is_trail_class": False,
            "distance_m": 3.0,
            "on_lon": -77.0,
            "on_lat": 38.9,
        }
        described = segment_info.describe(row, {"bicycle": True})
        assert described["title"] != "Riverwalk Trail"

    def test_it_is_open_wherever_the_open_reasons_are_read(self) -> None:
        assert segment_info.ACCESS_WORDS["bicycle_use_sidepath"][0] is True
        assert "bicycle_use_sidepath" not in segment_info.ACCESS_SHORT


def stage_context(tmp_path, monkeypatch) -> RebuildContext:
    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
        tiles_dir=tmp_path / "tiles",
    )
    found = []
    for osm_id, tags, coords in ways():
        if osm_id == NO_PATH:
            tags = {**tags, "tiger:county": "Montgomery, MD"}
        found.append(Way(osm_id=osm_id, tags=tags, node_ids=[], coordinates=coords))
    context.ways = found
    context.ways_by_id = {w.osm_id: w for w in found}
    context.reference = SimpleNamespace(urban_way_ids={w.osm_id for w in found}, road_blocks=[])
    monkeypatch.setattr(run_module.states, "state_polygons", lambda pbf: {})
    monkeypatch.setattr(
        run_module.states, "way_states", lambda ways, polygons: {w.osm_id: "MD" for w in ways}
    )
    return context


class TestTheStage:
    def test_avoid_with_a_side_path_and_a_report_row_without(self, tmp_path, monkeypatch) -> None:
        context = stage_context(tmp_path, monkeypatch)
        handlers = build_handlers(context, load_overrides=lambda: [])
        handlers[Stage.CLASSIFY_STRESS]()
        tiers = {i: context.stress_by_way[i].tier for i in context.stress_by_way}
        assert tiers[WITH_PATH] is Stress.AVOID and tiers[SIDEWALK] is Stress.AVOID
        for way in (NO_PATH, FOOTWAY_ONLY, CROSSING, FAR):
            assert tiers[way] is tiers[PLAIN] and tiers[way] is not Stress.AVOID
        assert context.use_sidepath_paths == {WITH_PATH: "Riverwalk Trail", SIDEWALK: None}
        report = context.work_dir / "reports" / USE_SIDEPATH_REPORT_NAME
        rows = list(csv.DictReader(report.open()))
        assert [r["way_id"] for r in rows] == [
            str(i) for i in sorted((NO_PATH, FOOTWAY_ONLY, CROSSING, FAR))
        ]
        assert rows[0] == {
            "way_id": str(NO_PATH),
            "name": "Test Road",
            "county": "Montgomery, MD",
            "state": "MD",
        }

    def test_an_owner_rating_outranks_it(self, tmp_path, monkeypatch) -> None:
        context = stage_context(tmp_path, monkeypatch)
        row = Override(
            "stress",
            WITH_PATH,
            {
                "tier": 2,
                "adjustment_id": "owner-says-two",
                "category": "other",
                "visibility": "hidden",
                "annotation_status": "approved",
                "display": "route_only",
            },
        )
        handlers = build_handlers(context, load_overrides=lambda: [row])
        handlers[Stage.CLASSIFY_STRESS]()
        assert context.stress_by_way[WITH_PATH].tier is Stress.AVOID
        handlers[Stage.APPLY_OVERRIDES]()
        assert context.stress_by_way[WITH_PATH].tier is Stress.LTS2


OWNER_STRESS = Path(__file__).parents[1] / "fixtures/overrides/2026-09-27-owner-stress.json"


@pytest.mark.parametrize(
    ("way_id", "adjustment"),
    [
        # The Frederick Douglass bridge roadway (OSM bicycle=use_sidepath) and the Benning
        # Road Bridge roadway (no bicycle tag) keep the owner's Avoid, which outranks the
        # side-path rule whichever way it goes (the RL-1 line of the v0.7.0 plan).
        (910656490, "frederick-douglass-bridge-roadway"),
        (910656491, "frederick-douglass-bridge-roadway"),
        (6061612, "benning-road-bridge-roadway"),
        (135146249, "benning-road-bridge-roadway"),
    ],
)
def test_douglass_and_benning_keep_the_owners_avoid(way_id, adjustment) -> None:
    rows = json.loads(OWNER_STRESS.read_text())["rows"]
    row = next(r for r in rows if r["osm_way_id"] == way_id and r["kind"] == "stress")
    assert row["value"]["tier"] == 5
    assert row["value"]["adjustment_id"] == adjustment
