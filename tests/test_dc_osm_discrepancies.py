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
