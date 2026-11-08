"""The DC-against-OSM discrepancy report (pipeline.discrepancies, written by each rebuild
and by scripts/analysis/dc_osm_discrepancies.py).

OWNER-DECISIONS 191: "report the discrepancies when you see them". Each way where the
District's record and OSM's tags disagree is listed by type, with whether the District's
value was applied (OWNER-DECISIONS 190) or not, and why not.
"""

from __future__ import annotations

import csv
import importlib.util
import json

import pytest
from rebuild_fixtures import REPO

from pipeline import discrepancies

SCRIPT = REPO / "scripts" / "analysis" / "dc_osm_discrepancies.py"


@pytest.fixture(scope="module")
def report():
    spec = importlib.util.spec_from_file_location("dc_osm_discrepancies", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def items(report, rows):
    return discrepancies.items([report.from_dcbal(r) for r in rows])


def row(**kwargs) -> dict:
    base = {
        "way": "1",
        "region": "dc",
        "state": "DC",
        "matched": "1",
        "name": "R Street Northwest",
        "highway": "residential",
        "m": "200",
        "blocks": "dc-1-0,dc-2-0",
        "tier0": "2",
        "tier1": "2",
        "disagree": "",
        "agree": "",
        "sources": "{}",
        "tags": "{}",
        "tags1": "{}",
        "facts": "{}",
    }
    for key, value in kwargs.items():
        base[key] = json.dumps(value) if isinstance(value, dict) else value
    return base


def test_an_osm_lane_the_district_does_not_record_is_a_presence_item(report) -> None:
    found = list(
        items(
            report,
            [
                row(
                    tags={"cycleway:right": "lane"},
                    tags1={},
                    facts={"bike": {}, "bike_recorded": False},
                    tier0="2",
                    tier1="1",
                )
            ],
        )
    )
    assert [i["type"] for i in found] == ["presence"]
    assert found[0]["applied"] is True
    assert found[0]["dc"] == "none recorded"


def test_a_separate_facility_is_not_applied_and_says_why(report) -> None:
    """Irving Street's pattern: the motor carriageway OSM tags with nothing, on a
    block whose protected lane OSM maps as its own way beside the other one."""
    found = list(
        items(
            report,
            [
                row(
                    tags={},
                    tags1={},
                    facts={"bike": {"ib": 3, "ob": 3}, "bike_recorded": True},
                    agree="bike facility: OSM maps it as a separate way",
                )
            ],
        )
    )
    assert [i["type"] for i in found] == ["presence"]
    assert found[0]["applied"] is False
    assert discrepancies.reason(found[0]["disagree"], found[0]["agree"], "presence").startswith(
        "separate"
    )


def test_a_way_osm_marks_separate_agrees_with_a_district_facility(report) -> None:
    agreeing = row(
        tags={"cycleway:right": "separate"},
        tags1={"cycleway:right": "separate"},
        facts={"bike": {"ib": 3, "ob": 3}, "bike_recorded": True},
        agree="bike facility: OSM maps it as a separate way",
    )
    assert list(items(report, [agreeing])) == []
    silent = row(
        tags={"cycleway:right": "separate"},
        tags1={"cycleway:right": "separate"},
        facts={"bike": {}, "bike_recorded": False},
    )
    found = list(items(report, [silent]))
    assert [(i["type"], i["applied"], i["own_separate"]) for i in found] == [
        ("presence", False, True)
    ]


def test_one_way_lanes_and_speed_items(report) -> None:
    found = {
        i["type"]: i
        for i in items(
            report,
            [
                row(
                    tags={"oneway": "yes", "lanes": "2", "maxspeed": "25 mph"},
                    tags1={"oneway": "yes", "lanes": "2", "maxspeed": "20 mph"},
                    facts={"one_way": False, "lanes_per_dir": 1, "speed_mph": 20},
                    sources={"lanes": "osm"},
                    disagree="oneway: agency two-way, OSM one-way, kept (divided carriageway)",
                )
            ],
        )
    }
    assert found["oneway"]["applied"] is False
    assert discrepancies.reason(found["oneway"]["disagree"], "", "oneway") == "divided carriageway"
    assert found["lanes"]["applied"] is False
    assert found["speed"]["applied"] is True
    assert (found["speed"]["osm"], found["speed"]["dc"]) == ("25 mph", "20 mph")


def test_the_report_and_csv_are_written(report, tmp_path, monkeypatch) -> None:
    tsv = tmp_path / "dcbal.tsv"
    rows = [
        row(
            tags={"cycleway:left": "opposite_lane", "oneway": "yes"},
            tags1={"cycleway:right": "lane", "oneway": "yes"},
            facts={"bike": {"ob": 1}, "bike_recorded": True, "contraflow": False, "one_way": True},
        )
    ]
    with tsv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr("sys.argv", ["x", "--dcbal", str(tsv), "--out", str(tmp_path)])
    assert report.main() == 0
    text = (tmp_path / "dc-osm-discrepancies.md").read_text()
    assert "https://www.openstreetmap.org/way/1" in text
    assert "licence waiver" in text
    with (tmp_path / "dc-osm-discrepancies.csv").open() as handle:
        written = list(csv.DictReader(handle))
    assert {r["type"] for r in written} == {"contraflow"}
    assert written[0]["applied"] == "1"


# -- review r3 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metres", "text"),
    [(304, "997 ft [304 m]"), (305, "0.19 mi [305 m]"), (1609, "1.00 mi [1,609 m]")],
)
def test_a_length_is_in_feet_under_1000_ft_and_miles_from_there(metres, text) -> None:
    """M35 of review r3: US units first, metric in brackets."""
    assert discrepancies.length_text(metres) == text


def test_a_withheld_speed_is_listed_as_an_owner_override(report) -> None:
    """OWNER-DECISIONS 197: DC's 20 mph on Canal Road NW is withheld; it stays
    listed, not applied, as an owner override. M38 of review r3: the applied flag
    is whether the classifier read the District's speed."""
    held = row(
        name="Canal Road Northwest",
        highway="trunk",
        tags={"maxspeed": "35 mph"},
        tags1={"maxspeed": "35 mph"},
        facts={"speed_mph": None, "speed_withheld": 20},
        disagree="maxspeed: agency 20 mph withheld by the owner, OSM kept (owner override)",
        tier0="4",
        tier1="4",
    )
    applied = row(
        way="2", tags={"maxspeed": "35 mph"}, tags1={"maxspeed": "20 mph"}, facts={"speed_mph": 20}
    )
    found = {i["way"]: i for i in items(report, [held, applied])}
    assert (found[1]["type"], found[1]["applied"]) == ("speed", False)
    assert (found[1]["osm"], found[1]["dc"]) == ("35 mph", "20 mph")
    assert discrepancies.reason(found[1]["disagree"], "", "speed") == "owner override"
    assert found[2]["applied"] is True


def test_not_applied_items_are_summarised_by_reason_and_owner_overrides_listed(
    report, tmp_path
) -> None:
    """Item 191 follow-up (review r3): the 2,767 not-applied one-way items swamped
    the report. They are summarised by reason with the longest as examples; every
    item stays in the CSV, and every owner override is listed."""
    pair = "oneway: agency two-way, OSM one-way, kept (carriageway pair)"
    rows = [
        report.from_dcbal(
            row(
                way=str(n),
                m=str(100 + n),
                tags={"oneway": "yes"},
                tags1={"oneway": "yes"},
                facts={"one_way": False},
                disagree=pair,
            )
        )
        for n in range(1, 6)
    ]
    rows.append(
        report.from_dcbal(
            row(
                way="9",
                name="Canal Road Northwest",
                tags={"maxspeed": "35 mph"},
                tags1={"maxspeed": "35 mph"},
                facts={"speed_withheld": 20},
                disagree="maxspeed: agency 20 mph withheld by the owner, OSM kept (owner override)",
            )
        )
    )
    rows.append(
        report.from_dcbal(
            row(
                way="7",
                tags={"lanes": "1", "oneway": "yes"},
                tags1={"lanes": "1", "oneway": "yes"},
                facts={"lanes_per_dir": 2},
                sources={"lanes": "osm"},
                disagree="lanes: a side lane beside a two-way carriageway, OSM kept",
            )
        )
    )
    rows.append(
        report.from_dcbal(
            row(
                way="8",
                tags={"maxspeed": "25 mph"},
                tags1={"maxspeed": "20 mph"},
                facts={"speed_mph": 20},
            )
        )
    )
    found = discrepancies.write_report(rows, tmp_path, "Test.")
    assert len(found) == 8
    side = next(i for i in found if i["way"] == 7)
    assert side["reason"] == "side lane beside a two-way carriageway"
    text = (tmp_path / "dc-osm-discrepancies.md").read_text()
    summary = next(line for line in text.splitlines() if "| carriageway pair |" in line)
    assert "| One-way | carriageway pair | 5 |" in summary
    # The three longest as examples, and no listing of the five.
    assert all(f"/way/{n})" in summary for n in (5, 4, 3))
    assert "/way/1)" not in text and "/way/2)" not in text
    assert "## Owner overrides: every one, 1" in text
    assert "| Canal Road Northwest | [9](https://www.openstreetmap.org/way/9) |" in text
    with (tmp_path / "dc-osm-discrepancies.csv").open() as handle:
        written = list(csv.DictReader(handle))
    assert len(written) == 8
    assert {r["not_applied_reason"] for r in written} == {
        "",
        "carriageway pair",
        "owner override",
        "side lane beside a two-way carriageway",
    }
    # An applied item is in no reason's row of the summary.
    summary_rows = text.split("## Not applied, by reason", 1)[1].split("## Owner overrides")[0]
    assert "| Posted speed |  |" not in summary_rows
    assert summary_rows.count("| Posted speed |") == 1
    assert not list(tmp_path.glob(".*partial"))


def test_the_rebuild_s_rows_are_the_script_s_rows(report) -> None:
    """Each rebuild writes the report from its own overlay (`discrepancies.row`),
    the checked-in copy from `dcbal.tsv` (`from_dcbal`): one shape."""
    from routemaker import agency_roads as A

    facts = A.aggregate(
        [("dc-1-0", A.RoadFacts(agency=A.DC_AGENCY, speed_mph={"ob": 20}, way="both"), True)]
    )
    tags = {"highway": "residential", "name": "R Street Northwest", "maxspeed": "25 mph"}
    after = {**tags, "maxspeed": "20 mph"}
    built = discrepancies.row(
        way=1,
        name=tags["name"],
        highway="residential",
        length_m=200.4,
        blocks=facts.blocks,
        tier0=2,
        tier1=1,
        disagreements=(),
        agreements=(),
        osm=tags,
        after=after,
        facts=discrepancies.facts_summary(facts),
        sources={"maxspeed": A.DC_AGENCY},
    )
    read = report.from_dcbal(
        row(
            blocks="dc-1-0",
            tier0="2",
            tier1="1",
            tags={"maxspeed": "25 mph"},
            tags1={"maxspeed": "20 mph"},
            facts=discrepancies.facts_summary(facts),
            sources={"maxspeed": A.DC_AGENCY},
        )
    )
    assert built == read


# -- OSM edited after the record (hunt D6; the owner, 2026-11-08) ----------------------
#
# "We should build a flag in. If there's a newer OSM rating, then on a rebuild it should
# flag it and I can make the call." The District's record still wins (OWNER-DECISIONS 190);
# a way OSM last edited after the record's date that disagrees with it is listed.


def _overlaid(tags: dict, edited, **facts_kwargs):
    """The overlay the rebuild classifies with, and the report's row for it."""
    from routemaker import agency_roads as A
    from routemaker.stress import classify

    facts = A.WayFacts(agency=A.DC_AGENCY, blocks=("dc-1-0",), **facts_kwargs)
    result = A.overlay(tags, facts)
    built = discrepancies.row(
        way=7,
        name=tags.get("name"),
        highway=tags["highway"],
        length_m=300.0,
        blocks=facts.blocks,
        tier0=int(classify(tags, urban=True, jurisdiction="DC").tier),
        tier1=int(classify(result.tags, urban=True, jurisdiction="DC").tier),
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


def test_a_newer_osm_edit_that_disagrees_is_flagged_and_dc_still_applies() -> None:
    """A road diet OSM mapped after the record (4 lanes to 2 with painted lanes): the
    record's 2 + 2 lanes, 30 mph and no lane are still what the classifier reads, and the
    way is flagged with what each says and the stress row that would take OSM's tier."""
    from datetime import timedelta

    from pipeline.overrides import stress_value_problem
    from routemaker import agency_roads as A

    edited = A.DC_RECORD_AS_OF + timedelta(days=1)
    result, built = _overlaid(DIET, edited, **RECORD)
    assert result.tags["lanes:forward"] == result.tags["lanes:backward"] == "2"
    assert result.tags["maxspeed"] == "30 mph" and "cycleway:both" not in result.tags
    [flag] = discrepancies.newer_osm([built], A.DC_RECORD_AS_OF)
    assert flag["way"] == 7 and flag["street"] == "Diet Street NW"
    assert flag["edited"] == edited.isoformat()
    assert flag["kinds"] == ["speed", "lanes", "bike facility"]
    assert flag["dc"] == "30 mph; 2 lanes a direction; no bike lane"
    assert flag["osm"] == "25 mph; 1 lane a direction; painted lane both sides"
    entry = json.loads(flag["override"])
    assert entry["kind"] == "stress" and entry["osm_way_id"] == 7
    assert entry["value"]["tier"] == built["tier0"] < built["tier1"]
    assert stress_value_problem(entry["value"]) is None
    assert "load_access_overrides" in flag["where"]


def test_an_osm_edit_no_newer_than_the_record_is_not_flagged() -> None:
    from datetime import date

    from routemaker import agency_roads as A

    for edited in (A.DC_RECORD_AS_OF, date(2025, 6, 1), None):
        _, built = _overlaid(DIET, edited, **RECORD)
        assert discrepancies.newer_osm([built], A.DC_RECORD_AS_OF) == []


def test_a_newer_osm_edit_that_agrees_with_the_record_is_not_flagged() -> None:
    from datetime import timedelta

    from routemaker import agency_roads as A

    agreeing = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "4"}
    _, built = _overlaid(agreeing, A.DC_RECORD_AS_OF + timedelta(days=30), **RECORD)
    assert discrepancies.newer_osm([built], A.DC_RECORD_AS_OF) == []


def test_a_newer_osm_speed_alone_takes_the_owner_s_block_correction() -> None:
    """The posted speed alone: the `agency_blocks` entry withholding the record's speed
    (OWNER-DECISIONS 197), in the shape the override loader reads."""
    from datetime import timedelta

    from routemaker import agency_roads as A

    tags = {"highway": "secondary", "name": "Diet Street NW", "maxspeed": "25 mph"}
    _, built = _overlaid(tags, A.DC_RECORD_AS_OF + timedelta(days=1), speed_mph=30)
    [flag] = discrepancies.newer_osm([built], A.DC_RECORD_AS_OF)
    assert flag["kinds"] == ["speed"] and "agency_blocks" in flag["where"]
    entries = json.loads(flag["override"])
    assert entries == [
        {
            "blockkey": "4f98key",
            "routename": "DIET ST NW",
            "withhold": ["speed"],
            "reason": discrepancies.OWNER_REASON,
            "evidence": discrepancies.OWNER_EVIDENCE,
        }
    ]


def test_a_suggested_block_correction_is_one_the_override_loader_reads(tmp_path) -> None:
    from datetime import timedelta

    from routemaker import agency_roads as A

    tags = {"highway": "secondary", "name": "Diet Street NW", "maxspeed": "25 mph"}
    _, built = _overlaid(tags, A.DC_RECORD_AS_OF + timedelta(days=1), speed_mph=30)
    [flag] = discrepancies.newer_osm([built], A.DC_RECORD_AS_OF)
    (tmp_path / "x.json").write_text(json.dumps({"agency_blocks": json.loads(flag["override"])}))
    assert A.withheld_blocks(tmp_path)["4f98key"].facts == frozenset({"speed"})


def test_the_rebuild_s_report_lists_the_flagged_ways_and_the_script_s_copy_does_not(
    report, tmp_path
) -> None:
    from datetime import timedelta

    from routemaker import agency_roads as A

    _, built = _overlaid(DIET, A.DC_RECORD_AS_OF + timedelta(days=1), **RECORD)
    newer = discrepancies.newer_osm([built], A.DC_RECORD_AS_OF)
    rebuild = tmp_path / "rebuild"
    discrepancies.write_report(
        [built], rebuild, discrepancies.REBUILD_SOURCE, newer=newer, as_of=A.DC_RECORD_AS_OF
    )
    text = (rebuild / discrepancies.MD_NAME).read_text()
    section = text.split("## OSM edited after the record: for the owner's call, every one, 1")[1]
    assert "| Diet Street NW | [7](https://www.openstreetmap.org/way/7) | 2026-10-02 |" in section
    assert "1 of 1 matched ways carry an OSM edit date" in section
    with (rebuild / discrepancies.NEWER_CSV_NAME).open() as handle:
        [written] = list(csv.DictReader(handle))
    assert (written["osm_way_id"], written["osm_edited"]) == ("7", "2026-10-02")
    assert written["dc_applies"] == "30 mph; 2 lanes a direction; no bike lane"
    assert json.loads(written["override"])["kind"] == "stress"
    copy = tmp_path / "copy"
    discrepancies.write_report([built], copy, report.SOURCE)
    assert "OSM edited after the record" not in (copy / discrepancies.MD_NAME).read_text()
    assert not (copy / discrepancies.NEWER_CSV_NAME).exists()
