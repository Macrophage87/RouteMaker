"""The 2026-10-16 review's stress-rating fixes that land with the next map rebuild: RL-3 (a
painted lane on a wide two-way street; the owner: agencies win where they rate, the formula
holds LTS 3, and a list of both for his review), RL-5 (a bare `maxspeed` read as mph by the
router too), RL-6 (an open motorway is Avoid) and RL-8 (`lanes=2;3`). RL-2 (contraflow taggings)
is pinned in `test_lts_sides.py`."""

from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest

from core import segment_info
from pipeline import run as run_module
from pipeline import variants
from pipeline.extract import Way
from pipeline.rebuild import Stage
from pipeline.run import RebuildContext, build_handlers
from pipeline.schema import MOTOR_ONLY_RULE
from routemaker import agency_lts
from routemaker.agency_lts import AgencyRating
from routemaker.facility import MapClass, map_class
from routemaker.massflow import usable_width_m
from routemaker.stress import (
    MOTORWAY_AVOID_RULE,
    Stress,
    classify,
    painted_lane_two_way_multilane,
)
from routemaker.tags import lanes_per_direction, maxspeed_in_mph_words, parse_lanes

# -- RL-3 ----------------------------------------------------------------------------------------

SIX_LANE = {"highway": "secondary", "maxspeed": "25 mph", "lanes": "6", "parking:both": "no"}
LANE = {"cycleway:both": "lane", "cycleway:both:width": "1.8"}


class TestAPaintedLaneOnAWideTwoWayStreet:
    @pytest.mark.parametrize("urban", (True, False))
    @pytest.mark.parametrize("width", ("1.8", "2.4"))
    def test_it_stays_lts3(self, urban: bool, width: str) -> None:
        """Measured, before this: LTS 3 bare and LTS 1 with the lane (LTS 2 rural)."""
        tags = {**SIX_LANE, "cycleway:both": "lane", "cycleway:both:width": width}
        result = classify(tags, urban=urban)
        assert result.tier is Stress.LTS3
        assert result.rule.startswith("bike lane")
        assert "a wide two-way road, so rated at least this" in segment_info.rule_words(result.rule)

    def test_four_lanes_two_each_way_and_a_buffered_lane(self) -> None:
        road = {**SIX_LANE, "lanes": "4", "cycleway:both": "buffered_lane"}
        assert classify(road).tier is Stress.LTS3

    def test_one_lane_each_way_keeps_furths_table(self) -> None:
        road = {**SIX_LANE, "lanes": "2", "cycleway:both:width": "2.4", "cycleway:both": "lane"}
        assert classify(road).tier is Stress.LTS1

    def test_a_one_way_keeps_its_relief_and_a_divided_carriageway_does_not(self) -> None:
        one_way = {**SIX_LANE, "lanes": "2", "oneway": "yes", **LANE}
        assert classify(one_way).tier < Stress.LTS3
        assert classify(one_way, divided=True).tier is Stress.LTS3

    def test_a_track_is_still_separation(self) -> None:
        assert classify({**SIX_LANE, "cycleway:both": "track"}).tier is Stress.LTS1

    def test_the_predicate(self) -> None:
        assert painted_lane_two_way_multilane({**SIX_LANE, **LANE})
        assert not painted_lane_two_way_multilane(SIX_LANE)
        assert not painted_lane_two_way_multilane({**SIX_LANE, "cycleway:both": "track"})
        assert not painted_lane_two_way_multilane({**SIX_LANE, "lanes": "2", **LANE})
        assert not painted_lane_two_way_multilane({**SIX_LANE, "oneway": "yes", **LANE})
        assert painted_lane_two_way_multilane({**SIX_LANE, "oneway": "yes", **LANE}, divided=True)
        # The classifier's count wins over the tags' (the rebuild passes `rated.lanes`,
        # which may come from an agency's block data).
        untagged = {key: v for key, v in {**SIX_LANE, **LANE}.items() if key != "lanes"}
        assert not painted_lane_two_way_multilane(untagged)
        assert painted_lane_two_way_multilane(untagged, lanes=2)
        assert not painted_lane_two_way_multilane({**SIX_LANE, **LANE}, lanes=1)
        assert not painted_lane_two_way_multilane({"highway": "cycleway", "lanes": "4", **LANE})

    def test_an_agency_still_wins_and_the_rural_floor_stays(self) -> None:
        formula = classify({**SIX_LANE, **LANE})
        rated = agency_lts.apply(formula, [AgencyRating("ddot", 2)])
        assert rated.tier is Stress.LTS2 and rated.formula_tier is Stress.LTS3
        assert agency_lts.apply(formula, [AgencyRating("ddot", 5)]).tier is Stress.AVOID
        # Montgomery's 5 is very high stress, not Avoid (the owner, 2026-10-19): our 4.5.
        moco = agency_lts.apply(formula, [AgencyRating("moco", 5)])
        assert moco.tier is Stress.LTS4 and moco.half


def result_for(ratings=()) -> object:
    return agency_lts.apply(classify({**SIX_LANE, **LANE}), ratings)


class TestTheFlagList:
    def test_a_ddot_and_a_montgomery_row(self) -> None:
        row = agency_lts.painted_lane_row(1, "K St", "DC", result_for([AgencyRating("ddot", 2)]))
        assert row is not None
        assert (row["scope"], row["agency"], row["agency_level"]) == ("DC", "ddot", "2")
        assert (row["formula_level"], row["differs"]) == ("3", "yes")
        assert row["formula_rule"].endswith("two-way floor")
        moco = agency_lts.painted_lane_row(
            2, "", "MD", result_for([AgencyRating("mdot-sha", 4), AgencyRating("moco", 3)])
        )
        assert (moco["scope"], moco["agency"], moco["differs"]) == ("MoCo", "moco", "no")

    def test_scope(self) -> None:
        assert agency_lts.painted_lane_row(3, "", "DC", result_for())["scope"] == "DC"
        # Maryland outside Montgomery's ratings is not on the list; the state's rating alone
        # does not put it there.
        assert agency_lts.painted_lane_row(4, "", "MD", result_for()) is None
        assert (
            agency_lts.painted_lane_row(5, "", "MD", result_for([AgencyRating("mdot-sha", 2)]))
            is None
        )
        # Virginia: the formula's level only, for Review's Arlington comparison.
        row = agency_lts.painted_lane_row(6, "", "VA", result_for())
        assert row["scope"] == "comparison" and row["agency"] == "" and row["agency_level"] == ""

    def test_the_csv_holds_no_pending_agency(self) -> None:
        rows = [
            agency_lts.painted_lane_row(9, 'A "b", c', "DC", result_for()),
            agency_lts.painted_lane_row(7, "", "VA", result_for()),
        ]
        text = agency_lts.painted_lane_report_csv(rows)
        read = list(csv.DictReader(text.splitlines()))
        assert [r["way_id"] for r in read] == ["7", "9"]
        assert read[1]["name"] == 'A "b", c'
        assert tuple(read[0]) == agency_lts.PAINTED_LANE_COLUMNS
        for pending in agency_lts.PENDING_AGENCIES:
            assert pending not in text.lower()


DC_LANE, VA_LANE, MD_LANE, PLAIN = 11, 12, 13, 14


def stage_context(tmp_path, monkeypatch) -> RebuildContext:
    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
        tiles_dir=tmp_path / "tiles",
    )
    found = []
    for n, (way_id, tags) in enumerate(
        [
            (DC_LANE, {**SIX_LANE, **LANE, "name": "K Street"}),
            (VA_LANE, {**SIX_LANE, **LANE}),
            (MD_LANE, {**SIX_LANE, **LANE}),
            (PLAIN, dict(SIX_LANE)),
        ]
    ):
        lat = 38.9 + n * 0.01
        coords = [(-77.0, lat), (-76.9975, lat), (-76.995, lat)]
        found.append(Way(osm_id=way_id, tags=tags, node_ids=[], coordinates=coords))
    context.ways = found
    context.ways_by_id = {w.osm_id: w for w in found}
    context.reference = SimpleNamespace(
        urban_way_ids={w.osm_id for w in found},
        road_blocks=[],
        agency_lts_features=("stand-in",),
        agency_lts_ratings={},
    )
    states = {DC_LANE: "DC", VA_LANE: "VA", MD_LANE: "MD", PLAIN: "DC"}
    monkeypatch.setattr(run_module.states, "state_polygons", lambda pbf: {})
    monkeypatch.setattr(run_module.states, "way_states", lambda ways, polygons: states)
    monkeypatch.setattr(
        run_module.agency_ratings,
        "ratings_by_way",
        lambda ways, entries, features, ratings: {
            DC_LANE: [AgencyRating("ddot", 2)],
            MD_LANE: [AgencyRating("moco", 1.5)],
        },
    )
    return context


def test_the_rebuild_writes_the_flag_list(tmp_path, monkeypatch) -> None:
    context = stage_context(tmp_path, monkeypatch)
    build_handlers(context, load_overrides=lambda: [])[Stage.CLASSIFY_STRESS]()
    # The agencies' levels decide; the formula's is kept beside them.
    assert context.stress_by_way[DC_LANE].tier is Stress.LTS2
    assert context.stress_by_way[MD_LANE].tier is Stress.LTS1
    assert context.stress_by_way[VA_LANE].tier is Stress.LTS3
    report = context.work_dir / "reports" / agency_lts.PAINTED_LANE_REPORT_NAME
    rows = {int(r["way_id"]): r for r in csv.DictReader(report.open())}
    assert set(rows) == {DC_LANE, VA_LANE, MD_LANE}
    assert rows[DC_LANE]["name"] == "K Street"
    assert (rows[DC_LANE]["agency_level"], rows[DC_LANE]["formula_level"]) == ("2", "3")
    assert (rows[MD_LANE]["scope"], rows[MD_LANE]["agency_level"]) == ("MoCo", "1.5")
    assert rows[VA_LANE]["scope"] == "comparison"


# -- RL-5 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "words"),
    [
        ("45", "45 mph"),
        ("45 MPH", "45 mph"),
        ("45Mph", "45 mph"),
        ("22.5", "22.5 mph"),
        ("45 mph", None),
        ("45mph", None),
        ("50 km/h", None),
        ("US:urban", None),
        ("none", None),
        ("signals", None),
        (None, None),
    ],
)
def test_a_posted_speed_is_written_as_the_router_reads_mph(value, words) -> None:
    assert maxspeed_in_mph_words(value) == words


@pytest.mark.parametrize("variant", list(variants.Variant))
def test_every_variant_extract_carries_the_speed_in_mph(variant) -> None:
    """`maxspeed=45` was a 45 mph road to the classifier and a 28 mph (45 km/h) edge to the
    router; the extract every graph is built from now says `45 mph`."""
    tags = {
        "highway": "secondary",
        "maxspeed": "45",
        "maxspeed:forward": "40 MPH",
        "maxspeed:practical": "60",
    }
    out = variants.inject(variant, tags)
    assert out is not None
    assert out["maxspeed"] == "45 mph" and out["maxspeed:forward"] == "40 mph"
    # Not a sign: the remap's own km/h.
    assert out["maxspeed:practical"] == "60"
    assert tags["maxspeed"] == "45", "the caller's tags are not changed"
    assert variants.with_speed_units({"maxspeed": "45 mph"}) == {"maxspeed": "45 mph"}


# -- RL-6 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("highway", ("motorway", "motorway_link"))
@pytest.mark.parametrize("bicycle", ("yes", "designated", "permissive"))
def test_an_open_motorway_is_avoid(highway, bicycle) -> None:
    result = classify({"highway": highway, "maxspeed": "55 mph", "bicycle": bicycle})
    assert result.tier is Stress.AVOID
    assert result.rule.startswith(MOTORWAY_AVOID_RULE)
    assert segment_info.rule_words(result.rule) == "Avoid: highway-like road"


def test_an_open_motorway_is_drawn_on_the_stress_and_mass_ride_maps() -> None:
    """Avoid is drawn: the map class is a road, and the rule no longer starts with the
    motor-only prefix the tiles' fallback filter drops (`schema.MOTOR_ONLY_RULE`, read
    on a table without `map_class`), so both the stress and the Mass Ride tiles keep
    it; and it has a usable width for the Mass Ride layer."""
    tags = {"highway": "motorway", "maxspeed": "55 mph", "bicycle": "yes", "lanes": "2"}
    result = classify(tags)
    prefix = "motor-only classification ("
    assert f"starts_with(stress_rule, '{prefix}')" == MOTOR_ONLY_RULE
    assert not result.rule.startswith(prefix)
    assert map_class(tags) is MapClass.ROAD
    assert usable_width_m(tags, result.lanes) is not None


def test_a_motorway_with_use_sidepath_stays_lts4_and_barred() -> None:
    tags = {"highway": "motorway", "maxspeed": "55 mph", "bicycle": "use_sidepath"}
    result = classify(tags)
    assert result.tier is Stress.LTS4
    assert result.rule.startswith("motor-only classification (")
    assert map_class(tags) is MapClass.BARRED


@pytest.mark.parametrize("bicycle", (None, "no", "use_sidepath", "unknown"))
def test_a_motorway_not_open_to_bicycles_keeps_lts4(bicycle) -> None:
    tags = {"highway": "motorway", "maxspeed": "55 mph"}
    if bicycle:
        tags["bicycle"] = bicycle
    assert classify(tags).tier is Stress.LTS4


# -- RL-8 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "lanes"), [("2;3", 3), ("3;2", 3), ("2", 2), ("2; x", 2), ("x", None), (None, None)]
)
def test_a_lane_list_is_read_as_its_largest(value, lanes) -> None:
    assert parse_lanes(value) == lanes


@pytest.mark.parametrize(
    ("tags", "lanes"),
    [
        ({"lanes": "2;3", "oneway": "yes"}, 3),
        ({"lanes": "4;6"}, 3),
        ({"lanes": "4", "lanes:forward": "1"}, 3),
        ({"lanes": "4", "lanes:backward": "1"}, 3),
        ({"lanes": "5", "lanes:forward": "2", "lanes:both_ways": "1"}, 2),
        ({"lanes": "4", "lanes:forward": "1", "oneway": "yes"}, 1),
        ({"lanes:forward": "2;3", "lanes:backward": "1"}, 3),
    ],
)
def test_lanes_per_direction_reads_lists_and_the_untagged_direction(tags, lanes) -> None:
    assert lanes_per_direction(tags) == lanes


@pytest.mark.parametrize("oneway", ("reversible", "alternating"))
def test_a_reversible_road_reads_as_two_way(oneway) -> None:
    """`oneway=reversible` or `alternating` is not a one-way (`tags.is_oneway`): the
    lanes not tagged forward are read as the other direction's, as on any two-way road.
    Pinned so a change to that reading is a decision, not an accident."""
    assert lanes_per_direction({"lanes": "4", "lanes:forward": "1", "oneway": oneway}) == 3
    assert lanes_per_direction({"lanes": "4;6", "oneway": oneway}) == 3


def test_a_lane_list_no_longer_rates_a_rural_road_as_one_lane() -> None:
    road = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "2;3", "oneway": "yes"}
    assert classify(road, urban=False).tier is Stress.LTS4
    assert "lanes" not in classify(road, urban=False).assumed
