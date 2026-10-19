"""MDOT SHA's LTS 5 is a bicycle ban, not a stress level (the owner, 2026-10-19:
"MDOT LTS 5 means that bikes are prohibited. MoCo LTS5 is extremely high stress but
allowed." and "Just don't draw them or consider them for routing.")."""

from __future__ import annotations

import csv
import io

from pipeline import agency_ratings
from pipeline.extract import Way
from routemaker import agency_lts, facility
from routemaker.agency_lts import PROHIBITED_NO_BICYCLE, AgencyRating
from routemaker.stress import Stress

LINE = [(-77.30 + i * 0.001, 39.20) for i in range(11)]


def _way(osm_id, **tags):
    tags = {"highway": "secondary", **tags}
    return Way(osm_id, tags, list(range(len(LINE))), LINE)


def _close(ways, rated, reasons=None, reopened=()):
    prohibited = agency_ratings.prohibited_ways(rated)
    return agency_ratings.prohibited_closures(ways, prohibited, reasons or {}, set(reopened))


def test_an_mdot_5_closes_a_road():
    added, rows = _close([_way(1)], {1: (AgencyRating("mdot-sha", 5),)})
    assert added == {1: PROHIBITED_NO_BICYCLE}
    assert [(r.way_id, r.outcome) for r in rows] == [(1, agency_ratings.CLOSED)]


def test_a_county_5_alone_stays_avoid_and_open():
    rated = {1: (AgencyRating("moco", 5),)}
    added, rows = _close([_way(1)], rated)
    assert (added, rows) == ({}, [])
    assert agency_lts.apply(agency_lts_formula(), rated[1]).tier is Stress.AVOID


def test_a_ddot_5_stays_open_too():
    assert agency_ratings.prohibited_ways({1: (AgencyRating("ddot", 5),)}) == set()


def test_an_mdot_4_closes_nothing():
    assert agency_ratings.prohibited_ways({1: (AgencyRating("mdot-sha", 4),)}) == set()


def test_the_ban_holds_under_a_county_level_the_map_uses():
    rated = (AgencyRating("moco", 4), AgencyRating("mdot-sha", 5))
    # The map's level is the county's, but access is not a level: still closed.
    assert agency_lts.chosen(rated).agency == "moco"
    added, _rows = _close([_way(1)], {1: rated})
    assert added == {1: PROHIBITED_NO_BICYCLE}


def test_a_path_is_listed_and_never_closed():
    for highway in ("cycleway", "path", "footway", "track"):
        added, rows = _close([_way(1, highway=highway)], {1: (AgencyRating("mdot-sha", 5),)})
        assert added == {}, highway
        assert [r.outcome for r in rows] == [agency_ratings.NOT_CLOSED_PATH], highway


def test_an_owner_access_override_reopens_it():
    added, rows = _close(
        [_way(1, bicycle="yes")], {1: (AgencyRating("mdot-sha", 5),)}, reopened={1}
    )
    assert added == {}
    assert [r.outcome for r in rows] == [agency_ratings.NOT_CLOSED_OVERRIDE]


def test_a_road_osm_opens_is_closed_and_flagged():
    added, rows = _close([_way(1, bicycle="designated")], {1: (AgencyRating("mdot-sha", 5),)})
    assert added == {1: PROHIBITED_NO_BICYCLE}
    assert [r.outcome for r in rows] == [agency_ratings.CLOSED_OSM_OPEN]


def test_a_road_already_closed_keeps_its_own_reason():
    ways = [_way(1, highway="motorway"), _way(2, bicycle="no"), _way(3)]
    rated = {w: (AgencyRating("mdot-sha", 5),) for w in (1, 2, 3)}
    added, rows = _close(ways, rated, reasons={3: "military"})
    assert (added, rows) == ({}, [])


def test_a_closed_road_is_barred_from_the_map_and_named_in_the_panel():
    from core import segment_info

    reason = facility.bike_access_reason({"highway": "secondary"}, no_bicycle=PROHIBITED_NO_BICYCLE)
    assert reason == PROHIBITED_NO_BICYCLE
    is_open, words = segment_info.ACCESS_WORDS[reason]
    assert not is_open and "MDOT SHA" in words
    assert segment_info.ACCESS_SHORT[reason]
    is_open, rows = segment_info.access_rows(
        {"bike_access_reason": reason, "map_class": "barred"}, False
    )
    assert is_open is False
    assert rows[0]["source"] == segment_info.MDOT_ACCESS_SOURCE


def test_the_report_lists_each_way_once_in_id_order():
    ways = [_way(2), _way(1, highway="path")]
    rated = {w: (AgencyRating("mdot-sha", 5),) for w in (1, 2)}
    _added, rows = _close(ways, rated)
    table = list(csv.reader(io.StringIO(agency_ratings.prohibited_report_csv(rows))))
    assert table[0] == list(agency_ratings.PROHIBITED_COLUMNS)
    assert [r[0] for r in table[1:]] == ["1", "2"]


def agency_lts_formula():
    from routemaker.stress import StressResult

    return StressResult(Stress.LTS4, "mixed traffic, 35 mph or above", ("maxspeed",))


def test_the_stress_stage_records_the_ban_beside_the_level(tmp_path, monkeypatch):
    from test_review_rl_ratings import MD_LANE, PLAIN, stage_context

    from pipeline import run as run_module
    from pipeline.rebuild import Stage
    from pipeline.run import build_handlers

    context = stage_context(tmp_path, monkeypatch)
    monkeypatch.setattr(
        run_module.agency_ratings,
        "ratings_by_way",
        lambda ways, entries, features, ratings: {
            MD_LANE: [AgencyRating("moco", 3), AgencyRating("mdot-sha", 5)],
            PLAIN: [AgencyRating("moco", 5)],
        },
    )
    build_handlers(context, load_overrides=lambda: [])[Stage.CLASSIFY_STRESS]()
    # The county's level is the map's; the state's ban is kept for the closure.
    assert context.stress_by_way[MD_LANE].tier is Stress.LTS3
    assert context.agency_prohibited == {MD_LANE}
