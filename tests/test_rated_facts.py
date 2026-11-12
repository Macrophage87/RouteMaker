"""Facts changed since rated (`pipeline.rated_facts`; backlog 2026-11-12 item 6, the owner's
call 2026-11-12: "Keep our level, queue it for you")."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from rebuild_fixtures import REPO

from pipeline import rated_facts as rf

OVERRIDES = REPO / "fixtures" / "overrides"
OWN_PICKS = sorted(OVERRIDES.glob("2026-11-09-owner-*-own-picks.json"))

SENTENCE = (
    "Own-picks review 2026-11-09 (blind to agency levels), group G00042: secondary, urban, "
    "speed 35 posted, lanes 2, two way, 8,000-11,999, facility lane (lane,shoulder); "
    "reports/agency-roads-sweep."
)


def test_an_own_picks_sentence_reads_as_facts() -> None:
    assert rf.from_evidence(SENTENCE) == {
        "highway": "secondary",
        "urban": True,
        "speed_mph": 35,
        "speed_source": "posted",
        "lanes": 2,
        "oneway": False,
        "count_band": [8000, 11999],
        "facility": "lane",
    }


@pytest.mark.parametrize(
    ("text", "band"),
    [("no count", None), ("<500", [0, 499]), ("30,000+", [30000, None]), ("500-999", [500, 999])],
)
def test_count_bands(text, band) -> None:
    assert rf.count_band(text) == band


def test_no_speed_no_lanes_and_a_default_speed_read_as_none() -> None:
    facts = rf.from_evidence(
        "group G00007: residential:driveway, rural, speed 50 default, lanes None, one way, "
        "no count, facility none; reports"
    )
    assert facts["highway"] == "residential"
    assert facts["speed_mph"] is None and facts["lanes"] is None and facts["oneway"]
    assert facts["count_band"] is None and facts["facility"] == "none"


def test_a_hand_written_sentence_is_not_read() -> None:
    assert rf.from_evidence("Owner's report from the street, 2026-11-10") is None


@pytest.mark.parametrize("path", OWN_PICKS, ids=lambda p: p.name)
def test_every_own_picks_group_states_its_facts(path) -> None:
    """Every group of the 2026-11-09 files (222,844 ways) is read, so none is left unwatched."""
    for group in json.loads(path.read_text())["groups"]:
        assert rf.from_evidence(group["evidence"]), group["evidence"][:120]


STORED = rf.from_evidence(SENTENCE)
SAME_NOW = {"highway": "secondary", "speed_mph": 35, "lanes": 2, "count": 9500, "facility": "lane"}


def test_nothing_changed() -> None:
    assert rf.changes(STORED, SAME_NOW) == []


@pytest.mark.parametrize(
    ("now", "said"),
    [
        ({"facility": "protected"}, "bike facility lane -> protected"),
        ({"speed_mph": 25}, "speed 35 -> 25 mph"),
        ({"speed_mph": None}, "speed 35 mph when rated, none read now"),
        ({"lanes": 4}, "lanes 2 -> 4"),
        ({"lanes": None}, "lanes 2 -> untagged"),
        ({"count": 16000}, "count 8,000-11,999 a day -> 16,000 a day"),
        ({"count": 5000}, "count 8,000-11,999 a day -> 5,000 a day"),
        ({"highway": "tertiary"}, "class secondary -> tertiary"),
    ],
)
def test_each_fact_that_moves_is_said(now, said) -> None:
    assert rf.changes(STORED, {**SAME_NOW, **now}) == [said]


@pytest.mark.parametrize(
    "now",
    [
        {"speed_mph": 38},  # under SPEED_STEP_MPH
        {"count": 13000},  # inside the band's margin (COUNT_MARGIN)
        {"count": None},  # a count lost is the match changing, not the road
        {"highway": "secondary_link"},  # a link of the same class
    ],
)
def test_small_moves_are_not_changes(now) -> None:
    assert rf.changes(STORED, {**SAME_NOW, **now}) == []


def test_a_count_or_speed_where_there_was_none() -> None:
    stored = {**STORED, "count_band": None, "speed_mph": None, "speed_source": None}
    assert rf.changes(stored, SAME_NOW) == [
        "speed now read: 35 mph (none when rated)",
        "count now 9,500 a day (none when rated)",
    ]


def test_current_facts_read_the_tags_and_the_classifier() -> None:
    result = SimpleNamespace(speed_mph=34.6, volume_aadt=1200)
    now = rf.current_facts({"highway": "tertiary", "lanes": "2;3"}, result, "lane")
    assert now == {
        "highway": "tertiary",
        "speed_mph": 35,
        "lanes": 2,
        "count": 1200,
        "facility": "lane",
    }


def _file(tmp_path, document) -> None:
    (tmp_path / "x.json").write_text(
        json.dumps({"version": 1, "decided": "2026-11-09", **document})
    )


def test_load_reads_groups_rows_and_a_facts_object_first(tmp_path) -> None:
    facts = {**STORED, "facility": "protected"}
    _file(
        tmp_path,
        {
            "rows": [
                {"kind": "stress", "osm_way_id": 1, "evidence": SENTENCE, "facts": facts},
                {"kind": "access", "osm_way_id": 2, "evidence": SENTENCE},
                {"kind": "stress", "osm_way_id": 3, "evidence": "by hand"},
            ],
            "groups": [{"kind": "stress", "evidence": SENTENCE, "ways": [4, 5]}],
        },
    )
    found = rf.load(tmp_path)
    assert sorted(found) == [1, 4, 5]
    assert found[1].facts["facility"] == "protected"
    assert found[4].facts == STORED and found[4].decided == "2026-11-09"


def test_a_rematched_row_carries_its_facts_to_the_new_ways() -> None:
    rated = {1: rf.Rated(STORED, "x.json", "2026-11-09")}
    entry = SimpleNamespace(kind="stress", old_way_id=1, new_way_ids=(7, 8))
    assert sorted(rf.follow_rematch(rated, [entry])) == [1, 7, 8]


def test_compare_lists_only_moved_ways_with_both_levels() -> None:
    rated = {
        1: rf.Rated(STORED, "x.json", "2026-11-09"),
        2: rf.Rated(STORED, "x.json", "2026-11-09"),
        3: rf.Rated(STORED, "x.json", "2026-11-09"),  # not in this extract
    }
    tags = {"highway": "secondary", "lanes": "2", "name": "Sample Road"}
    ways = {1: SimpleNamespace(tags=tags), 2: SimpleNamespace(tags={**tags, "lanes": "4"})}
    result = SimpleNamespace(speed_mph=35, volume_aadt=9000, tier=3)
    changed, checked = rf.compare(
        rated, ways, {1: result, 2: result}, {2: 2.5}, lambda t: "lane", lambda r: 3.0
    )
    assert checked == 2
    assert [(c.way_id, c.our_level, c.formula_level, c.what) for c in changed] == [
        (2, 2.5, 3.0, ["lanes 2 -> 4"])
    ]
    text = rf.report_csv(changed)
    assert "Facts changed since rated: lanes 2 -> 4" in text and text.startswith("way_id,")
    assert "Facts changed: 1" in rf.report_markdown(changed, checked)


@pytest.mark.parametrize(
    ("facts", "problem"),
    [
        ({"facility": "painted"}, "facility"),
        ({"speed_mph": "35"}, "speed_mph"),
        ({"count_band": [1]}, "count_band"),
        ({"colour": "red"}, "has no"),
    ],
)
def test_a_malformed_facts_object_is_refused(facts, problem) -> None:
    assert problem in rf.facts_problem(facts)


def test_a_good_facts_object_passes() -> None:
    assert rf.facts_problem(STORED) is None


def test_a_retired_row_no_longer_pins_its_facts(tmp_path) -> None:
    group = {"kind": "stress", "evidence": SENTENCE, "ways": [4, 5]}
    (tmp_path / "a.json").write_text(json.dumps({"version": 1, "groups": [group]}))
    retire = [{"kind": "stress", "osm_way_id": 4, "value": {}, "reason": "r"}]
    (tmp_path / "b.json").write_text(json.dumps({"version": 1, "retire": retire}))
    assert sorted(rf.load(tmp_path)) == [5]


def test_the_own_picks_files_pin_every_way_but_the_retired() -> None:
    found = rf.load(OVERRIDES)
    assert len(found) > 200_000
    assert 553709201 not in found, "Woodglen Drive, retired by the North Bethesda file"
