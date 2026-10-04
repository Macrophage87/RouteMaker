"""Same-street AADT smoothing (OWNER-DECISIONS 285, 296)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pipeline import aadt_smoothing
from pipeline.conflation import Match
from routemaker.stress import classify

DATA = Path(__file__).parent / "data" / "first_street_nw.json"
# Metres per degree of latitude, to lay a synthetic street out in metres.
M_PER_DEG = 111_195.0


@dataclass
class W:
    osm_id: int
    tags: dict
    coordinates: list = field(default_factory=list)


def block(osm_id, north_m, length_m, name="Test Street", highway="tertiary", east_m=0.0):
    """A straight north-south way of `length_m`, its south end `north_m` up the street."""
    lon = -77.0 + east_m / 86_000.0
    return W(
        osm_id,
        {"highway": highway, "name": name},
        [[lon, 38.9 + north_m / M_PER_DEG], [lon, 38.9 + (north_m + length_m) / M_PER_DEG]],
    )


def match(way_id, aadt, agency="ddot", year=2024):
    return Match(
        osm_way_id=way_id, feature_id=f"f{way_id}", aadt=aadt, source="count", year=year,
        score=1.0, agency=agency,
    )  # fmt: skip


def counts(*pairs):
    return {way_id: match(way_id, aadt) for way_id, aadt in pairs}


def street(*aadts, length=110.0, name="Test Street"):
    ways = [block(i + 1, i * length, length, name=name) for i in range(len(aadts))]
    return ways, counts(*((i + 1, a) for i, a in enumerate(aadts)))


def smooth(ways, by_way, jurisdiction=None, **kwargs):
    lookup = jurisdiction if jurisdiction is not None else {}
    return aadt_smoothing.smooth(ways, by_way, lookup, **kwargs)


# --- The rule -----------------------------------------------------------------


def test_one_blocks_outlier_count_is_outvoted_by_its_street() -> None:
    ways, by_way = street(7520, 7520, 10665, 7520, 7520)
    out, report = smooth(ways, by_way)
    assert out[3].aadt == 7520
    assert out[3].raw_aadt == 10665, "what the agency counted is kept"
    assert [r.way_id for r in report.replaced] == [3]
    assert (report.replaced[0].raw, report.replaced[0].smoothed) == (10665, 7520)
    assert by_way[3].aadt == 10665, "the input is not mutated"


def test_agreeing_counts_are_left_alone() -> None:
    ways, by_way = street(7520, 7520, 7520, 7520)
    out, report = smooth(ways, by_way)
    assert out == by_way and not report.replaced


def test_the_median_is_weighted_by_length() -> None:
    """A 20 m stub at 20,000 does not outvote two 150 m blocks at 4,000."""
    ways = [block(1, 0, 150), block(2, 150, 20), block(3, 170, 150)]
    by_way = counts((1, 4000), (2, 20000), (3, 4000))
    out, _ = smooth(ways, by_way)
    assert out[2].aadt == 4000
    # And the other way: the long block's count wins over two short ones.
    ways = [block(1, 0, 20), block(2, 20, 300), block(3, 320, 20)]
    out, _ = smooth(ways, counts((1, 1000), (2, 9000), (3, 1000)))
    assert out[1].aadt == 1000 and out[3].aadt == 1000, "lower counts are never raised"
    assert out[2].aadt == 9000, "the median is 9,000 and the block is at it: not replaced"
    ways = [block(1, 0, 20), block(2, 20, 300), block(3, 320, 20), block(4, 340, 20)]
    out, _ = smooth(ways, counts((1, 4000), (2, 9000), (3, 4000), (4, 4000)))
    assert out[2].aadt == 9000, "9,000 is the median of this window too"


def test_it_needs_three_ways_and_250_m_in_the_window() -> None:
    # Two ways: the agencies' counts stand.
    ways, by_way = street(7520, 10665, length=200)
    assert smooth(ways, by_way)[0] == by_way
    # Three ways but 90 m of road in all: they stand.
    ways, by_way = street(7520, 10665, 7520, length=30)
    assert smooth(ways, by_way)[0] == by_way
    # Three ways and 270 m: smoothed.
    ways, by_way = street(7520, 10665, 7520, length=90)
    assert smooth(ways, by_way)[0][2].aadt == 7520


def test_the_window_is_400_m_from_the_ways_midpoint() -> None:
    near = [block(1, 0, 110), block(2, 110, 110), block(3, 220, 110)]
    far = [block(10, 1000, 110), block(11, 1110, 110), block(12, 1220, 110)]
    by_way = counts((1, 5000), (2, 12000), (3, 5000), (10, 900), (11, 900), (12, 900))
    out, _ = smooth([*near, *far], by_way)
    # The three blocks 1 km up never enter the first three's window, nor theirs.
    assert [out[i].aadt for i in (1, 2, 3)] == [5000, 5000, 5000]
    assert [out[i].aadt for i in (10, 11, 12)] == [900, 900, 900]
    # The window is the distance between midpoints: at 100 m a block sees only itself.
    ways, by_way = street(5000, 12000, 5000, 5000, 5000)
    assert smooth(ways, by_way, window_m=100)[0] == by_way
    assert smooth(ways, by_way, window_m=400)[0][2].aadt == 5000
    # Block 5's midpoint is 440 m from block 1's: outside 400 m, inside 450 m.
    ways, by_way = street(1000, 1000, 1000, 1000, 9000)
    assert smooth(ways, by_way, window_m=400)[0][5].aadt == 1000
    ways, by_way = street(9000, 1000, 1000, 1000, 1000, 1000)
    assert smooth(ways, by_way, window_m=400)[0][1].aadt == 1000


def test_a_street_of_another_name_or_state_is_not_the_street() -> None:
    ways = [
        block(i + 1, i * 110, 110, name="A Street" if i % 2 == 0 else "B Street") for i in range(5)
    ]
    out, _ = smooth(ways, counts(*((i + 1, a) for i, a in enumerate((7000, 999, 7000, 999, 7000)))))
    assert out[3].aadt == 7000, "three A Street ways of 7,000 are unmoved"
    assert out[2].aadt == 999, "two B Street ways are too few to smooth"

    ways, by_way = street(7520, 7520, 10665, 7520, 7520)
    states = {1: "DC", 2: "DC", 3: "VA", 4: "DC", 5: "DC"}
    out, _ = smooth(ways, by_way, states)
    assert out[3].aadt == 10665, "a Virginia way is not smoothed by the District's street"


def test_the_quadrant_is_not_part_of_the_street() -> None:
    ways = [
        block(1, 0, 110, name="1st Street Northwest"),
        block(2, 110, 110, name="1st Street NW"),
        block(3, 220, 110, name="1st Street Northwest"),
        block(4, 330, 110, name="1st street northwest"),
    ]
    out, _ = smooth(ways, counts((1, 7000), (2, 7000), (3, 12000), (4, 7000)))
    assert out[3].aadt == 7000


def test_only_ways_with_a_count_are_candidates_and_none_is_invented() -> None:
    ways, by_way = street(7520, 7520, 10665, 7520, 7520)
    ways.append(block(99, 600, 110))
    out, _ = smooth(ways, by_way)
    assert 99 not in out


@pytest.mark.parametrize("highway", ["service", "footway", "cycleway", "path", "pedestrian"])
def test_driveways_and_trails_neither_vote_nor_are_smoothed(highway) -> None:
    ways, by_way = street(7520, 10665, 7520, 7520)
    extra = block(50, 100, 300, highway=highway)
    by_way[50] = match(50, 100)
    out, _ = smooth([*ways, extra], by_way)
    assert out[50].aadt == 100, "its own count stands"
    assert out[2].aadt == 7520, "and it did not vote the street down"


def test_unnamed_ways_are_left_alone() -> None:
    ways = [block(i + 1, i * 110, 110, name="") for i in range(5)]
    ways = [W(w.osm_id, {"highway": "tertiary"}, w.coordinates) for w in ways]
    by_way = counts(*((i + 1, a) for i, a in enumerate((1, 9, 1, 9, 1))))
    assert smooth(ways, by_way)[0] == by_way


def test_agency_and_year_stay_those_of_the_replaced_count() -> None:
    ways, by_way = street(7520, 7520, 10665, 7520, 7520)
    by_way[3] = match(3, 10665, agency="ddot", year=2024)
    out, _ = smooth(ways, by_way)
    assert (out[3].agency, out[3].year, out[3].feature_id) == ("ddot", 2024, "f3")


def test_a_median_off_the_gate_is_what_the_rule_text_marks() -> None:
    assert aadt_smoothing.crosses_volume_gate(10665, 7520)
    assert aadt_smoothing.crosses_volume_gate(1200, 1800)
    assert not aadt_smoothing.crosses_volume_gate(9000, 12000)
    assert not aadt_smoothing.crosses_volume_gate(3000, 6000)
    assert aadt_smoothing.crosses_volume_gate(7999, 8000)
    # 1,500 is still quiet and 1,501 is not; 8,000 is busy and 7,999 is not.
    assert aadt_smoothing.crosses_volume_gate(1500, 1501)
    assert not aadt_smoothing.crosses_volume_gate(1501, 1502)
    assert not aadt_smoothing.crosses_volume_gate(8000, 8001)


def test_the_midpoint_is_half_way_along_the_line() -> None:
    mid, length = aadt_smoothing.midpoint_and_length(
        [[-77.0, 38.9], [-77.0, 38.901], [-77.001, 38.901]]
    )
    assert length == pytest.approx(111.2 + 86.5, rel=0.01)
    assert mid[1] == pytest.approx(38.901, abs=0.0002)
    assert aadt_smoothing.midpoint_and_length([[-77.0, 38.9]]) is None
    assert aadt_smoothing.midpoint_and_length([[-77.0, 38.9], [-77.0, 38.9]]) is None


# --- The owner's case: 1st Street NW -------------------------------------------


def first_street():
    rows = json.loads(DATA.read_text())
    ways = [W(r["id"], r["tags"], r["coords"]) for r in rows]
    by_way = {
        r["id"]: Match(
            osm_way_id=r["id"], feature_id="f", aadt=r["aadt"], source="count", year=2024,
            score=1.0, agency=r["agency"],
        )
        for r in rows
    }  # fmt: skip
    return ways, by_way


def test_way_483241819_drops_to_the_streets_count() -> None:
    ways, by_way = first_street()
    assert by_way[483241819].aadt == 10665
    out, report = smooth(ways, by_way, {w.osm_id: "DC" for w in ways})
    assert out[483241819].aadt == 7520
    assert 483241819 in {r.way_id for r in report.replaced}


def test_and_that_moves_the_block_from_lts_3_to_lts_2_by_the_unchanged_rules() -> None:
    """Decision 285: LTS 3 "single lane, high volume" on 10,665; the rest of the
    street's 7,520 is LTS 2. No threshold changed (decision 296)."""
    ways, by_way = first_street()
    way = next(w for w in ways if w.osm_id == 483241819)
    tags = {**way.tags, "maxspeed": "25 mph"}
    kwargs = dict(urban=True, jurisdiction="DC")
    raw = classify(tags, aadt=by_way[483241819].aadt, **kwargs)
    out, _ = smooth(ways, by_way, {w.osm_id: "DC" for w in ways})
    after = classify(tags, aadt=out[483241819].aadt, **kwargs)
    assert int(raw.tier) == 3 and "high volume" in raw.rule
    assert int(after.tier) == 2 and "high volume" not in after.rule


def test_a_lower_count_that_is_not_an_outlier_is_untouched_and_the_report_counts() -> None:
    ways, by_way = first_street()
    out, report = smooth(ways, by_way, {w.osm_id: "DC" for w in ways})
    assert report.counted_ways == len(by_way)
    assert report.candidate_ways == len(by_way)
    assert "counts replaced" in report.summary()
    # The 4,253 stretch at the north end stands on its own median.
    assert out[345074764].aadt == 4253


def test_smoothing_only_lowers_a_count_never_raises_one() -> None:
    """Decision 303: the bunching is an intersection's volume on one block, and the
    routing already adds intersection stress, so a low block is not raised."""
    ways, by_way = street(7520, 7520, 2000, 7520, 7520)
    out, report = smooth(ways, by_way)
    assert out[3].aadt == 2000 and out[3].raw_aadt is None
    assert not report.replaced
    # A mixed street: the high outlier comes down, the low one stays.
    ways, by_way = street(7520, 10665, 7520, 2000, 7520, 7520)
    out, report = smooth(ways, by_way)
    assert out[2].aadt == 7520 and out[4].aadt == 2000
    assert [r.way_id for r in report.replaced] == [2]
    assert all(r.smoothed < r.raw for r in report.replaced)
    assert all(out[w].aadt <= by_way[w].aadt for w in by_way)
