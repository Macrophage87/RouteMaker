"""The District ways OSM edited after DC's Roadway Block record, for the owner's call
(`pipeline.dc_osm_newer`; hunt D6).

The owner, 2026-11-08: "We should build a flag in. If there's a newer OSM rating, then on a
rebuild it should flag it and I can make the call." The record still wins (OWNER-DECISIONS
190); a way OSM last edited after the record's date that disagrees with it is listed, with the
override that takes OSM's value and the kept entry that keeps DC's, until the owner decides.
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta

import pytest

from pipeline import dc_osm_newer as N
from pipeline import discrepancies
from pipeline.overrides import Override, stress_value_problem
from routemaker import agency_roads as A
from routemaker.stress import classify

AFTER = A.DC_RECORD_AS_OF + timedelta(days=1)
FINGERPRINT = {
    "name": "Diet Street NW",
    "highway": "secondary",
    "length_m": 300.0,
    "line": "-77.0,38.9 -77.0,38.903",
}


def _overlaid(tags: dict, edited, **facts_kwargs):
    """The overlay the rebuild classifies with, and the report's row for it."""
    facts = A.WayFacts(agency=A.DC_AGENCY, blocks=("dc-1-0",), **facts_kwargs)
    result = A.overlay(tags, facts)
    before = classify(tags, urban=True, jurisdiction="DC")
    after = classify(result.tags, urban=True, jurisdiction="DC")
    built = discrepancies.row(
        way=7,
        name=tags.get("name"),
        highway=tags["highway"],
        length_m=300.0,
        blocks=facts.blocks,
        tier0=int(before.tier),
        tier1=int(after.tier),
        tier0_half=before.half,
        tier1_half=after.half,
        disagreements=result.disagreements,
        agreements=result.agreements,
        osm=tags,
        after=result.tags,
        facts=discrepancies.facts_summary(facts),
        sources=result.sources,
        osm_edited=edited,
        block_keys=[("4f98key", "DIET ST NW")],
    )
    return result, built


DIET = {
    "highway": "secondary",
    "name": "Diet Street NW",
    "maxspeed": "25 mph",
    "lanes": "2",
    "cycleway:both": "lane",
}
RECORD = {"lanes_per_direction": 2, "one_way": False, "speed_mph": 30}
SPEED_ONLY = {"highway": "secondary", "name": "Diet Street NW", "maxspeed": "25 mph"}


def test_a_newer_osm_edit_that_disagrees_is_flagged_and_dc_still_applies() -> None:
    """A road diet OSM mapped after the record (4 lanes to 2 with painted lanes): the
    record's 2 + 2 lanes, 30 mph and no lane are still what the classifier reads, and the
    way is open, with what each says and the stress row that would take OSM's tier."""
    result, built = _overlaid(DIET, AFTER, **RECORD)
    assert result.tags["lanes:forward"] == result.tags["lanes:backward"] == "2"
    assert result.tags["maxspeed"] == "30 mph" and "cycleway:both" not in result.tags
    [flag] = N.newer_osm([built], A.DC_RECORD_AS_OF, fingerprint_of=lambda way: FINGERPRINT)
    assert flag["status"] == N.OPEN
    assert (flag["way"], flag["street"], flag["edited"]) == (7, "Diet Street NW", AFTER.isoformat())
    assert flag["kinds"] == [N.SPEED, N.LANES, N.BIKE]
    assert flag["dc"] == "30 mph; 2 lanes a direction; no bike lane"
    assert flag["osm"] == "25 mph; 1 lane a direction; painted lane both sides"
    entry = json.loads(flag["override"])
    assert entry["kind"] == "stress" and entry["osm_way_id"] == 7
    assert entry["value"]["tier"] == built["tier0"] < built["tier1"]
    assert "at_least" not in entry["value"]  # OSM's tier is the lower: it sets the tier
    assert stress_value_problem(entry["value"]) is None
    assert entry["fingerprint"] == FINGERPRINT
    # Said plainly: the row holds the tier, the tags stay DC's.
    assert "tier" in flag["how"] and "stay DC's" in flag["how"]
    assert json.loads(flag["keep"]) == {
        "osm_way_id": 7,
        "osm_edited": AFTER.isoformat(),
        "reason": A.REASON_PLACEHOLDER,
    }


def test_an_osm_edit_older_than_the_record_is_not_flagged() -> None:
    for edited in (date(2026, 9, 30), date(2025, 6, 1), None):
        _, built = _overlaid(DIET, edited, **RECORD)
        assert N.newer_osm([built], A.DC_RECORD_AS_OF) == []


def test_an_osm_edit_on_the_records_own_day_is_flagged() -> None:
    """Before the review it was left out; it may have come after the record was taken."""
    _, built = _overlaid(DIET, A.DC_RECORD_AS_OF, **RECORD)
    assert [f["way"] for f in N.newer_osm([built], A.DC_RECORD_AS_OF)] == [built["way"]]


def test_a_kept_date_in_the_future_is_refused(tmp_path) -> None:
    path = tmp_path / "kept.json"
    path.write_text(
        '{"version": 1, "kept": [{"osm_way_id": 5, "osm_edited": "2999-01-01", "reason": "x"}]}'
    )
    with pytest.raises(N.KeptRefused, match="future"):
        N.load_kept(path)


def test_a_newer_osm_edit_that_agrees_with_the_record_is_not_flagged() -> None:
    agreeing = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "4"}
    _, built = _overlaid(agreeing, A.DC_RECORD_AS_OF + timedelta(days=30), **RECORD)
    assert N.newer_osm([built], A.DC_RECORD_AS_OF) == []


def test_a_speed_the_owner_withheld_is_osm_s_already_and_not_listed() -> None:
    facts = A.WayFacts(agency=A.DC_AGENCY, blocks=("dc-1-0",), speed_withheld_mph=30)
    result = A.overlay(SPEED_ONLY, facts)
    assert result.tags["maxspeed"] == "25 mph"
    _, built = _overlaid(SPEED_ONLY, AFTER, speed_withheld_mph=30)
    assert N.newer_osm([built], A.DC_RECORD_AS_OF) == []


def test_a_newer_osm_speed_alone_takes_the_owner_s_block_correction(tmp_path) -> None:
    """The posted speed alone: the `agency_blocks` entry withholding the record's speed
    (OWNER-DECISIONS 197). The loader refuses it until the owner's words replace the
    placeholders, and reads it once they do."""
    _, built = _overlaid(SPEED_ONLY, AFTER, speed_mph=30)
    [flag] = N.newer_osm([built], A.DC_RECORD_AS_OF)
    assert flag["kinds"] == [N.SPEED] and "agency_blocks" in flag["how"]
    entries = json.loads(flag["override"])
    assert [(e["blockkey"], e["routename"], e["withhold"]) for e in entries] == [
        ("4f98key", "DIET ST NW", ["speed"])
    ]
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"agency_blocks": entries}))
    with pytest.raises(A.WithheldBlockRefused, match="placeholder"):
        A.withheld_blocks(tmp_path)
    filled = [{**e, "reason": "The owner: 25 now.", "evidence": "Posted 25 mph."} for e in entries]
    path.write_text(json.dumps({"agency_blocks": filled}))
    assert A.withheld_blocks(tmp_path)["4f98key"].facts == frozenset({"speed"})


def test_a_way_the_owner_set_with_a_stress_row_is_decided_not_open() -> None:
    """The blocker of the first review: the list was written before the approved rows were
    read, so a way the owner had already set was asked about again every rebuild."""
    _, built = _overlaid(DIET, AFTER, **RECORD)
    approved = [
        Override(
            kind="stress",
            osm_way_id=7,
            value={"tier": built["tier0"], "adjustment_id": "way-7-osm-newer"},
            reason="owner",
        )
    ]
    [flag] = N.newer_osm([built], A.DC_RECORD_AS_OF, decided=N.decided_ways(approved))
    assert flag["status"] == N.TOOK_OSM
    assert flag["decided"] == f"approved stress row way-7-osm-newer, LTS {built['tier0']}"


def test_a_way_the_owner_kept_dc_on_is_decided_until_osm_edits_it_again() -> None:
    _, built = _overlaid(DIET, AFTER, **RECORD)
    kept = {7: N.Kept(7, AFTER, "The owner: DC is right, the diet was reverted.")}
    [flag] = N.newer_osm([built], A.DC_RECORD_AS_OF, kept=kept)
    assert flag["status"] == N.KEPT_DC
    _, edited_again = _overlaid(DIET, AFTER + timedelta(days=10), **RECORD)
    [again] = N.newer_osm([edited_again], A.DC_RECORD_AS_OF, kept=kept)
    assert again["status"] == N.OPEN and "OSM edited it since" in again["decided"]


def test_the_kept_list_is_read_and_refuses_a_placeholder(tmp_path) -> None:
    assert N.load_kept() == {}  # the checked-in list loads, and is empty for now
    assert N.load_kept(tmp_path / "missing.json") == {}
    path = tmp_path / "kept.json"
    entry = json.loads(N.keep_dc_entry(7, "2026-10-02"))
    path.write_text(json.dumps({"version": 1, "kept": [entry]}))
    with pytest.raises(N.KeptRefused, match="placeholder"):
        N.load_kept(path)
    path.write_text(json.dumps({"version": 1, "kept": [{**entry, "reason": "Owner: keep DC."}]}))
    assert N.load_kept(path) == {7: N.Kept(7, date(2026, 10, 2), "Owner: keep DC.")}
    path.write_text(json.dumps({"version": 1, "kept": [{**entry, "osm_edited": "soon"}]}))
    with pytest.raises(N.KeptRefused, match="osm_edited"):
        N.load_kept(path)


def test_a_suggested_stress_row_keeps_a_half_step_and_floors_a_higher_osm_tier() -> None:
    r = {
        "way": 9,
        "tier0": 3,
        "tier0_half": True,
        "tier1": 2,
        "tier1_half": False,
        "block_keys": [],
    }
    _, entry = N.take_osm_override(r, [N.LANES], None)
    value = json.loads(entry)["value"]
    assert (value["tier"], value["half"], value["at_least"]) == (3, True, True)
    assert stress_value_problem(value) is None
    assert "fingerprint" not in json.loads(entry)


def test_the_report_lists_open_and_decided_ways_apart(tmp_path) -> None:
    _, open_row = _overlaid(DIET, AFTER, **RECORD)
    _, kept_row = _overlaid(SPEED_ONLY, AFTER, speed_mph=30)
    kept_row = {**kept_row, "way": 8}
    kept = {8: N.Kept(8, AFTER, "Owner: keep DC.")}
    flagged = N.newer_osm([open_row, kept_row], A.DC_RECORD_AS_OF, kept=kept)
    N.write_report(flagged, tmp_path, matched=2, dated=2, as_of=A.DC_RECORD_AS_OF)
    text = (tmp_path / N.MD_NAME).read_text()
    opened, decided = text.split("## Open: 1")[1].split("## Decided: 1")
    assert "| Diet Street NW | [7](https://www.openstreetmap.org/way/7) | 2026-10-02 |" in opened
    assert "[8](" in decided and "kept DC's value" in decided
    assert "2 of 2 matched District ways carry an OSM edit date" in text
    with (tmp_path / N.CSV_NAME).open() as handle:
        written = list(csv.DictReader(handle))
    assert [(w["status"], w["osm_way_id"]) for w in written] == [
        (N.OPEN, "7"),
        (N.KEPT_DC, "8"),
    ]
    assert written[0]["dc_applies"] == "30 mph; 2 lanes a direction; no bike lane"
    assert json.loads(written[0]["take_osm_override"])["kind"] == "stress"
    assert json.loads(written[0]["keep_dc_entry"])["osm_way_id"] == 7
