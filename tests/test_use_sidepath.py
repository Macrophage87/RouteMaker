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

        # The why line says the deciding rating, not the side-path rule.
        rule = context.stress_by_way[WITH_PATH].rule
        assert rule.startswith("override:")
        assert "side path" not in segment_info.rule_words(rule)


# One degree of latitude in the matcher's plane (`facility._xy`), metres.
M_PER_DEG = 6_371_008.8 * 3.141592653589793 / 180


class TestTheReviewFixes:
    """The review of 1b529533 (RL-1 revision)."""

    @pytest.mark.parametrize(
        ("tags", "map_class", "reason"),
        [
            ({"highway": "motorway", "bicycle": "use_sidepath"}, "barred", "motorway"),
            (
                {"highway": "trunk", "motorroad": "yes", "bicycle": "use_sidepath"},
                "barred",
                "motorroad",
            ),
            (
                {"highway": "service", "access": "private", "bicycle": "use_sidepath"},
                "hidden",
                "private",
            ),
            (
                {"highway": "residential", "vehicle": "no", "bicycle": "use_sidepath"},
                "hidden",
                "private",
            ),
        ],
    )
    def test_use_sidepath_never_opens_a_closed_road(self, tags, map_class, reason) -> None:
        assert facility.map_class(tags).value == map_class
        assert facility.bike_access_reason(tags, side_path=True) == reason
        assert not facility.is_use_sidepath_road(tags)
        found, missing = facility.use_sidepath_paths(
            [(1, tags, line(38.90)), (2, {"highway": "cycleway"}, line(38.90012))]
        )
        assert (found, missing) == ({}, set())
        assert classify(tags, side_path=True).tier is classify(tags).tier

    def test_a_crossing_is_never_the_side_path(self) -> None:
        crossing = {"highway": "footway", "footway": "crossing", "bicycle": "yes"}
        found, missing = facility.use_sidepath_paths(
            [
                (1, dict(ROAD), line(38.90)),
                (2, crossing, line(38.90012)),
                (3, {"highway": "cycleway", "cycleway": "crossing"}, line(38.90015)),
            ]
        )
        assert (found, missing) == ({}, {1})

    @pytest.mark.parametrize(
        "extra",
        [
            {"cycleway": "track"},
            {"cycleway:right": "track"},
            {"cycleway:both": "track"},
            {"sidewalk:both:bicycle": "yes"},
            {"sidewalk:left:bicycle": "designated"},
        ],
    )
    def test_a_side_path_on_the_road_itself_counts(self, extra) -> None:
        found, missing = facility.use_sidepath_paths([(1, {**ROAD, **extra}, line(38.90))])
        assert (found, missing) == ({1: None}, set())

    def test_a_side_path_named_as_the_road_is_not_named(self) -> None:
        found, _missing = facility.use_sidepath_paths(
            [
                (1, dict(ROAD), line(38.90)),
                (2, {"highway": "cycleway", "name": "TEST ROAD"}, line(38.90012)),
            ]
        )
        assert found == {1: None}

    def test_a_north_south_road(self) -> None:
        road = [(-77.0, 38.90), (-77.0, 38.904)]
        path = [(-76.99985, 38.90), (-76.99985, 38.904)]  # about 13 m east
        found, missing = facility.use_sidepath_paths(
            [(1, dict(ROAD), road), (2, {"highway": "path", "name": "Spine"}, path)]
        )
        assert (found, missing) == ({1: "Spine"}, set())

    @pytest.mark.parametrize(("metres", "matched"), [(29.0, True), (31.0, False)])
    def test_just_inside_and_just_outside_30_m(self, metres, matched) -> None:
        offset = metres / M_PER_DEG
        found, missing = facility.use_sidepath_paths(
            [(1, dict(ROAD), line(38.90)), (2, {"highway": "cycleway"}, line(38.90 + offset))]
        )
        assert (1 in found) is matched
        assert (1 in missing) is not matched

    @pytest.mark.parametrize("coords", [[(-77.0, 38.9)], [(-77.0, 38.9), (-77.0, 38.9)], []])
    def test_a_way_with_no_length_is_skipped(self, coords) -> None:
        assert facility.use_sidepath_paths([(1, dict(ROAD), coords)]) == ({}, set())

    def test_an_agency_rating_says_its_own_why(self) -> None:
        rating = agency_lts.AgencyRating(agency="moco", level=3.0)
        result = agency_lts.apply(classify(ROAD, side_path=True), [rating])
        words = segment_info.rule_words(result.rule)
        assert "side path" not in words
        assert words.startswith("Rated LTS 3 by")


OWNER_STRESS = Path(__file__).parents[1] / "fixtures/overrides/2026-09-27-owner-stress.json"
DOUGLASS = (910656490, 910656491)
BENNING = (6061612, 135146249)


@pytest.mark.parametrize("with_path", [True, False])
def test_douglass_and_benning_keep_the_owners_avoid(tmp_path, monkeypatch, with_path) -> None:
    """The Frederick Douglass bridge roadway (OSM bicycle=use_sidepath) and the Benning
    Road Bridge roadway (no bicycle tag) keep the owner's Avoid through the real
    precedence code (classify, then the fixture's approved override rows), whether or
    not a side path is found (the RL-1 line of the v0.7.0 plan)."""
    context = stage_context(tmp_path, monkeypatch)
    douglass = {
        "highway": "primary",
        "name": "South Capitol Street Southeast",
        "bicycle": "use_sidepath",
        "foot": "no",
        "oneway": "yes",
        "maxspeed": "40 mph",
    }
    benning = {
        "highway": "primary",
        "name": "Benning Road Northeast",
        "oneway": "yes",
        "maxspeed": "35 mph",
    }
    extra = []
    for i, way_id in enumerate((*DOUGLASS, *BENNING)):
        lat = 38.80 + i * 0.01
        tags = douglass if way_id in DOUGLASS else benning
        extra.append(Way(osm_id=way_id, tags=dict(tags), node_ids=[], coordinates=line(lat)))
        if with_path:
            path = {"highway": "cycleway", "name": "Anacostia Riverwalk Trail"}
            extra.append(
                Way(osm_id=900 + i, tags=path, node_ids=[], coordinates=line(lat + 0.00012))
            )
    context.ways = [*context.ways, *extra]
    context.ways_by_id = {w.osm_id: w for w in context.ways}
    context.reference.urban_way_ids = {w.osm_id for w in context.ways}
    fixture = json.loads(OWNER_STRESS.read_text())["rows"]
    rows = [
        Override("stress", r["osm_way_id"], r["value"])
        for r in fixture
        if r["kind"] == "stress" and r["osm_way_id"] in (*DOUGLASS, *BENNING)
    ]
    assert len(rows) == 4
    handlers = build_handlers(context, load_overrides=lambda: rows)
    handlers[Stage.CLASSIFY_STRESS]()
    assert (DOUGLASS[0] in context.use_sidepath_paths) is with_path
    handlers[Stage.APPLY_OVERRIDES]()
    for way_id in (*DOUGLASS, *BENNING):
        result = context.stress_by_way[way_id]
        assert result.tier is Stress.AVOID, way_id
        assert result.rule.startswith("override: stress adjustment"), result.rule


def test_write_segments_writes_the_access_reason_and_side_path_name(tmp_path, monkeypatch) -> None:
    context = stage_context(tmp_path, monkeypatch)
    context.reference.sidepath_bridge_ids = frozenset()
    handlers = build_handlers(context, load_overrides=lambda: [])
    handlers[Stage.CLASSIFY_STRESS]()
    # The facility stage has run (it returns early once it has a class per way).
    context.facility_by_way = {w.osm_id: "none" for w in context.ways}
    written: list[dict] = []
    monkeypatch.setattr("pipeline.schema.schema_exists", lambda schema: True)
    monkeypatch.setattr(run_module.writers, "write_segments", lambda s, rows: written.extend(rows))
    for name in ("derive_trail_runs", "derive_calm_runs", "derive_roadside"):
        monkeypatch.setattr(run_module.trail_routes, name, lambda schema: None)
    monkeypatch.setattr(run_module.trail_routes, "mtb_level_counts", lambda schema: {})
    monkeypatch.setattr(run_module.trail_routes, "mtb_name_counts", lambda schema: (0, 0))
    monkeypatch.setattr(run_module.writers, "mark_links", lambda schema, ids: 0)
    monkeypatch.setattr(run_module.bikeshare_corridors, "tidy", lambda schema, named=(): {})
    handlers[Stage.WRITE_SEGMENTS]()
    by_way = {row["osm_way_id"]: row for row in written}
    assert by_way[WITH_PATH]["bike_access_reason"] == "bicycle_use_sidepath"
    assert by_way[WITH_PATH]["sidepath_name"] == "Riverwalk Trail"
    assert by_way[WITH_PATH]["map_class"] == "road"
    assert by_way[SIDEWALK]["bike_access_reason"] == "bicycle_use_sidepath"
    assert by_way[SIDEWALK]["sidepath_name"] is None
    assert by_way[NO_PATH]["bike_access_reason"] is None
    assert by_way[NO_PATH]["sidepath_name"] is None
