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
    tags = {"highway": "primary", **tags}
    return Way(osm_id, tags, list(range(len(LINE))), LINE)


def _close(ways, rated, reasons=None, reopened=()):
    prohibited = agency_ratings.prohibited_ways(rated)
    return agency_ratings.prohibited_closures(ways, prohibited, reasons or {}, set(reopened))


def test_an_mdot_5_closes_a_road():
    added, rows = _close([_way(1)], {1: (AgencyRating("mdot-sha", 5),)})
    assert added == {1: PROHIBITED_NO_BICYCLE}
    assert [(r.way_id, r.outcome) for r in rows] == [(1, agency_ratings.CLOSED)]


def test_a_county_5_alone_is_45_and_open():
    """Montgomery's 5 is very high stress, our 4.5 (the owner, 2026-10-19), and open."""
    rated = {1: (AgencyRating("moco", 5),)}
    added, rows = _close([_way(1)], rated)
    assert (added, rows) == ({}, [])
    result = agency_lts.apply(agency_lts_formula(), rated[1])
    assert (result.tier, result.half) == (Stress.LTS4, True)


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


def test_a_minor_road_is_closed_and_flagged():
    added, rows = _close([_way(1, highway="residential")], {1: (AgencyRating("mdot-sha", 5),)})
    assert added == {1: PROHIBITED_NO_BICYCLE}
    assert [r.outcome for r in rows] == [agency_ratings.CLOSED_MINOR]


def test_a_bridge_the_fixture_opens_is_listed_and_not_closed():
    rated = {1: (AgencyRating("mdot-sha", 5),)}
    prohibited = agency_ratings.prohibited_ways(rated)
    added, rows = agency_ratings.prohibited_closures(
        [_way(1)], prohibited, {}, set(), bridge_legal={1}
    )
    assert added == {}
    assert [r.outcome for r in rows] == [agency_ratings.NOT_CLOSED_BRIDGE]


def test_an_owner_override_that_closes_it_is_the_owners_closure():
    added, rows = _close([_way(1, bicycle="no")], {1: (AgencyRating("mdot-sha", 5),)}, reopened={1})
    assert added == {}
    assert [r.outcome for r in rows] == [agency_ratings.CLOSED_BY_OVERRIDE]


def test_closed_miles_are_counted_by_class():
    ways = [_way(1), _way(2, highway="residential"), _way(3, highway="path")]
    rated = {w: (AgencyRating("mdot-sha", 5),) for w in (1, 2, 3)}
    _added, rows = _close(ways, rated)
    by_class = agency_ratings.closed_by_class(rows)
    assert set(by_class) == {"primary", "residential"}
    count, miles = by_class["primary"]
    assert count == 1 and 0.5 < miles < 0.6  # 0.01 degrees of longitude at 39.2 N


def test_the_installed_bans_are_counted():
    ratings = {
        "a": AgencyRating("mdot-sha", 5),
        "b": AgencyRating("moco", 5),
        "c": AgencyRating("mdot-sha", 4),
    }
    assert agency_ratings.prohibiting_records(ratings) == 1


def test_the_panel_words_the_ban_as_a_ban_not_avoid():
    import json

    from core import segment_info

    held = {
        "agencies": [
            {"agency": "moco", "name": "Montgomery County Planning", "level": 3},
            {"agency": "mdot-sha", "name": "MDOT SHA", "level": 5},
        ],
        "used": "moco",
    }
    rows = segment_info.rating_rows({"stress_ratings": json.dumps(held)})
    values = {r["label"]: r["value"] for r in rows}
    assert values["MDOT SHA rates it"] == segment_info.PROHIBITED_LEVEL_WORDS
    assert "Avoid" not in values["MDOT SHA rates it"]


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
    assert not is_open and "Maryland State Highway Administration (MDOT SHA)" in words
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


ROAD = 400


def _write_road_extract(path):
    import osmium

    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, (lon, lat) in {1: (-77.20, 39.10), 2: (-77.19, 39.10)}.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=ROAD, nodes=[1, 2], version=1, tags={"highway": "trunk", "name": "Probe Pike"}
            )
        )
    finally:
        writer.close()


def test_the_rebuild_closes_the_road_in_every_graph_and_writes_the_report(tmp_path):
    from rebuild_fixtures import write_reference_data

    from pipeline.extract import read_ways
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, ReferenceData, build_handlers
    from pipeline.variants import Variant

    source_pbf = tmp_path / "source.osm.pbf"
    _write_road_extract(source_pbf)
    reference_dir = write_reference_data(tmp_path)
    context = RebuildContext(
        source_pbf=source_pbf,
        work_dir=tmp_path / "work",
        reference_dir=reference_dir,
        tiles_dir=tmp_path / "tiles",
    )
    context.ways = read_ways(source_pbf)
    context.ways_by_id = {way.osm_id: way for way in context.ways}
    context.reference = ReferenceData.load(reference_dir, context.ways)
    # What CLASSIFY_STRESS records from an MDOT SHA 5 matched onto the road.
    context.agency_prohibited = {ROAD}

    handlers = build_handlers(context, load_overrides=lambda: [])
    handlers[Stage.APPLY_OVERRIDES]()
    handlers[Stage.INJECT_TAGS]()

    assert context.no_bicycle[ROAD] == PROHIBITED_NO_BICYCLE
    for variant in Variant:
        tags = {way.osm_id: way.tags for way in read_ways(context.variant_pbf(variant))}
        assert tags[ROAD].get("rm:no_bicycle") == PROHIBITED_NO_BICYCLE, variant
    report = context.work_dir / "reports" / agency_ratings.PROHIBITED_REPORT_NAME
    rows = list(csv.DictReader(report.open()))
    assert [(r["way_id"], r["outcome"]) for r in rows] == [(str(ROAD), agency_ratings.CLOSED)]
