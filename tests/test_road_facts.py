"""The facts behind a road's level in the road panel (`core.segment_info.road_facts`; the owner,
2026-11-13: "redesign the panel of each road to adequately reflect the available raw data when
people look at a spot"). Pure: rows are the live segment table's columns as dicts."""

from __future__ import annotations

import json
from datetime import date

from core import segment_info as si
from routemaker import pavement


def road(**columns) -> dict:
    return {
        "osm_way_id": 1,
        "stress_tier": 3,
        "stress_rule": "mixed traffic, 25 mph, 2 lanes each way",
        "stress_assumed": json.dumps([]),
        "volume_source": None,
        "volume_aadt": None,
        "volume_year": None,
        "is_trail_class": False,
        "facility": "none",
        **columns,
    }


def by_id(facts):
    return {f["id"]: f for f in facts}


CITY = road(
    road_speed_mph=25,
    road_lanes=2,
    road_oneway=False,
    road_urban=True,
    volume_source="ddot",
    volume_aadt=24_100,
    volume_year=2023,
    attr_sources=json.dumps(
        {"maxspeed": "dc-roadway-block", "lanes": "dc-roadway-block", "bike": "dc-roadway-block"}
    ),
    pavement_pci=78.4,
    pavement_surveyed=date(2026, 3, 2),
)

COUNTRY = road(
    stress_rule="rural, 55 mph, single lane",
    stress_assumed=json.dumps(["maxspeed", "lanes", "shoulder"]),
    road_default_speed_mph=55,
    road_urban=False,
)


def test_a_city_road_with_records_shows_each_with_its_source_and_date():
    facts = by_id(si.road_facts(CITY))
    assert list(facts) == ["speed", "traffic", "lanes", "facility", "setting", "pavement"]
    assert facts["speed"]["kind"] == si.RECORD
    assert facts["speed"]["value"] == "25 mph (40 km/h), posted"
    assert facts["speed"]["source"] == "DDOT street record"
    assert facts["traffic"]["value"] == "24,100 vehicles a day"
    assert (facts["traffic"]["source"], facts["traffic"]["date"]) == ("DDOT count", "2023")
    assert facts["lanes"]["value"] == "2 each way"
    assert facts["facility"]["value"] == "None"
    assert facts["facility"]["source"] == "DDOT street record"
    assert facts["setting"]["value"] == "Urban"
    # Pavement is shown, with its survey year, but is no input to the level.
    assert facts["pavement"]["value"] == "Good (78 of 100)"
    assert facts["pavement"]["date"] == "2026"
    assert facts["pavement"]["input"] is False
    assert "surveyed 2026-03-02" in facts["pavement"]["detail"]


def test_travel_speed_has_no_line_since_no_department_publishes_it():
    # The owner, 2026-11-13: "If no department of transportation has it, then don't include it".
    ids = {f["id"] for f in si.road_facts(CITY)} | {f["id"] for f in si.road_facts(COUNTRY)}
    assert "travel_speed" not in ids
    assert all(f["label"] != "Travel speed" for f in si.road_facts(CITY))


def test_a_country_road_with_little_data_looks_thin():
    facts = by_id(si.road_facts(COUNTRY))
    # No bike tags at all: no Bike lane line, since absence is not a record.
    assert list(facts) == ["speed", "traffic", "lanes", "shoulder", "setting"]
    assert facts["speed"]["kind"] == si.ESTIMATED
    assert facts["speed"]["value"] == "55 mph (89 km/h)"
    assert facts["speed"]["source"] == "Nothing posted; the law's default here"
    assert facts["traffic"]["kind"] == si.ESTIMATED
    assert facts["lanes"] == {**facts["lanes"], "kind": si.ESTIMATED, "value": "1 each way"}
    assert facts["shoulder"]["value"] == "Under 4 ft"
    assert facts["setting"]["kind"] == si.RECORD
    evidence = si.evidence_of(list(facts.values()))
    assert evidence["strength"] == "thin"
    assert evidence["words"] == "Thin evidence: 1 of 5 from records"


def test_evidence_counts_only_the_level_inputs():
    evidence = si.evidence_of(si.road_facts(CITY))
    assert (evidence["records"], evidence["inputs"]) == (5, 5)
    assert evidence["words"] == "Strong evidence: 5 of 5 from records"


def test_an_estimated_speed_is_the_one_the_level_used():
    # The rule read a narrow rural road at 25 mph; the law's 50 is not what the level used.
    narrow = road(
        stress_rule="narrow rural road, 25 mph",
        stress_assumed=json.dumps(["maxspeed"]),
        road_default_speed_mph=50,
    )
    speed = by_id(si.road_facts(narrow))["speed"]
    assert speed["value"] == "25 mph (40 km/h)"
    assert speed["source"] == "Nothing posted; read from the road's type"


def test_a_speed_with_no_unit_is_an_estimate():
    row = road(road_speed_mph=30, stress_assumed=json.dumps(["maxspeed unit"]))
    speed = by_id(si.road_facts(row))["speed"]
    assert (speed["kind"], speed["source"]) == (si.ESTIMATED, "Unit not mapped; read as mph")


def test_no_bike_lane_is_a_record_only_where_a_source_said_so():
    def facility(sources):
        row = road(attr_sources=json.dumps(sources)) if sources is not None else road()
        return by_id(si.road_facts(row)).get("facility")

    assert facility(None) is None
    assert facility({"bike": "default"}) is None
    assert facility({"bike": "osm"})["value"] == "None"
    assert facility({"bike": "dc-roadway-block"})["source"] == "DDOT street record"
    # A mapped lane is a record whatever the attr sources say.
    assert by_id(si.road_facts(road(facility="lane")))["facility"]["value"] == "Painted"


def test_no_evidence_line_where_a_rating_row_set_the_level():
    row = {**CITY, "stress_adjustment_id": "2026-11-12-owner-side-streets:1"}
    assert si.evidence_of(si.road_facts(row), row) is None
    assert si.evidence_of(si.road_facts(CITY), CITY) is not None


def test_evidence_breaks():
    def facts(records, estimates):
        return [{"input": True, "kind": si.RECORD}] * records + [
            {"input": True, "kind": si.ESTIMATED}
        ] * estimates

    assert si.evidence_of(facts(3, 1))["strength"] == "strong"
    assert si.evidence_of(facts(2, 2))["strength"] == "some"
    assert si.evidence_of(facts(1, 2))["strength"] == "thin"
    assert si.evidence_of([]) is None


def test_lane_width_and_parking_only_beside_a_painted_lane():
    assumed = json.dumps(["cycleway width", "parking"])
    plain = by_id(si.road_facts(road(stress_assumed=assumed)))
    lane = by_id(si.road_facts(road(stress_assumed=assumed, facility="lane")))
    assert "lane_width" not in plain and "parking" not in plain
    assert lane["lane_width"]["value"] == "Read as narrow"
    assert lane["parking"]["kind"] == si.ESTIMATED
    assert lane["facility"]["value"] == "Painted"


def test_paths_and_trails_have_no_facts():
    assert si.road_facts(road(is_trail_class=True)) == []


def test_the_plain_sentence():
    assert si.plain_sentence(si.road_facts(CITY)) == (
        "Two lanes each way at 25 mph, about 24,100 vehicles a day."
    )
    assert si.plain_sentence(si.road_facts(COUNTRY)) == (
        "Nothing is posted or counted here, so speed and traffic are estimates."
    )
    one = road(road_speed_mph=30, road_lanes=1, road_oneway=True)
    assert si.plain_sentence(si.road_facts(one)) == (
        "One lane in this direction at 30 mph, traffic not counted."
    )
    assert si.plain_sentence([]) is None


def test_the_summary_leaves_the_facts_lines_to_the_facts():
    summary = [
        {
            "id": "stress",
            "label": "Traffic stress",
            "value": "LTS 3 · For experienced cyclists · measured",
        },
        {"id": "why", "label": "Why", "value": "mixed traffic"},
        {"id": "speed", "label": "Speed", "value": "25 mph"},
        {"id": "lanes", "label": "Lanes", "value": "2 each way"},
        {"id": "traffic", "label": "Traffic", "value": "24,100 a day"},
        {"id": "bikes", "label": "Bikes", "value": "Allowed"},
    ]
    kept = si.with_facts(summary, CITY, si.road_facts(CITY))
    assert [line["id"] for line in kept] == ["stress", "why", "bikes"]
    # The how-sure words go: the evidence line says it now.
    assert kept[0]["value"] == si.stress_short(3)
    # With no facts (a path), the summary is as it was.
    assert si.with_facts(summary, CITY, []) == summary


def test_a_rider_checked_level_keeps_its_word():
    row = {**CITY, "stress_adjustment_id": "edit-12"}
    summary = [{"id": "stress", "label": "Traffic stress", "value": "x"}]
    assert si.with_facts(summary, row, si.road_facts(row))[0]["value"].endswith("rider-checked")


def test_pavement_columns_only_where_the_survey_speaks_for_the_street():
    def reading(why):
        return pavement.Reading(1, 61.0, date(2026, 2, 27), ("a",), None, why)

    assert pavement.panel_columns(None) == {"pavement_pci": None, "pavement_surveyed": None}
    assert pavement.panel_columns(reading("not_street"))["pavement_pci"] is None
    assert pavement.panel_columns(reading("unpaved"))["pavement_pci"] is None
    # An approved correction says the survey is wrong or stale there: not shown.
    assert pavement.panel_columns(reading("override"))["pavement_pci"] is None
    for why in ("pci", "osm_newer"):
        assert pavement.panel_columns(reading(why)) == {
            "pavement_pci": 61.0,
            "pavement_surveyed": date(2026, 2, 27),
        }


def test_the_narrative_says_why_from_the_rule_and_the_facts():
    def said(row):
        facts = si.road_facts(row)
        return si.narrative(row, facts, si.evidence_of(facts, row))

    assert said(CITY) == (
        "Bikes share the lane with two lanes of traffic each way at 25 mph and about 24,100 "
        "vehicles a day."
    )
    lane = road(
        stress_tier=2,
        stress_rule="bike lane, 30 mph",
        facility="lane",
        road_speed_mph=30,
        road_lanes=1,
        volume_source="vdot",
        volume_aadt=6000,
        volume_year=2024,
    )
    assert said(lane) == (
        "A painted bike lane beside one lane of traffic each way at 30 mph and about 6,000 "
        "vehicles a day."
    )
    # A thin road says its level is a best guess.
    thin = road(
        stress_rule="mixed traffic, 55 mph", stress_assumed=json.dumps(["maxspeed", "lanes"])
    )
    assert said(thin).startswith("Bikes share the lane with one lane of traffic each way at 55 mph")
    assert said(thin).endswith("best guess until the road is counted or mapped.")
    # A path, and an owner's row with its own note.
    assert said(road(is_trail_class=True)).startswith("A path away from traffic")
    noted = {
        **CITY,
        "stress_adjustment_id": "2026-11-12-owner:1",
        "stress_adjustment_note": "Underpass with fast merging traffic",
        "stress_adjustment_display": "map",
    }
    assert said(noted) == "Underpass with fast merging traffic."
